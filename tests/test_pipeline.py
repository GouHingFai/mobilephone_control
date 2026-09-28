#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_pipeline.py —— 端到端链路测试

不打桩在「匹配」这一层，而是从「听到一句话」一路走到「真的点了某个坐标」。
用一个假的 adb 顶替真机，界面数据用真实抓取的 GRE3000 dump。

这是开发者唯一能做的真机之外的全链路验证：
    听到文字 → 抓屏 → 解析 → 护栏 → 匹配 → 点击坐标

它证明了这条链路是通的，而且点击坐标确实落在正确的选项上。
"""

import re
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from voice_tap import main as app
from voice_tap import screen
from voice_tap.adb import AdbError
from voice_tap.clicker import Clicker
from voice_tap.config import Config
from voice_tap.ui_state import UiState

FIXTURES = Path(__file__).resolve().parent / "fixtures"

GRE_XML = (FIXTURES / "gre_degrade.xml").read_text(encoding="utf-8")

SECOND_XML = (FIXTURES / "gre_prototype.xml").read_text(encoding="utf-8")

QQ_XML = """<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
<hierarchy rotation="0">
  <node index="0" text="" class="android.widget.FrameLayout" package="com.tencent.mobileqq"
        clickable="false" bounds="[0,0][1212,2512]">
    <node index="0" text="消息" class="android.widget.TextView" package="com.tencent.mobileqq"
          clickable="true" bounds="[0,2440][200,2512]" />
    <node index="1" text="联系人" class="android.widget.TextView" package="com.tencent.mobileqq"
          clickable="true" bounds="[400,2440][600,2512]" />
  </node>
</hierarchy>
"""


# 答完题之后的详情页：没有选项，但有一个「下一题」按钮
# （人造数据 —— 真实结构等实测补充，目前只知道按钮文字是「下一题」）
DETAIL_XML = """<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
<hierarchy rotation="0">
  <node index="0" text="" class="android.widget.FrameLayout" package="com.enhance.greapp"
        clickable="false" bounds="[0,0][1212,2512]">
    <node index="0" text="degrade" resource-id="com.enhance.greapp:id/tv_word"
          class="android.widget.TextView" package="com.enhance.greapp"
          clickable="false" bounds="[50,300][1162,500]" />
    <node index="1" text="" class="android.widget.RelativeLayout"
          package="com.enhance.greapp" clickable="true" bounds="[100,2100][1112,2260]">
      <node index="0" text="下一题" class="android.widget.TextView"
            package="com.enhance.greapp" clickable="false" bounds="[500,2140][700,2220]" />
    </node>
  </node>
</hierarchy>
"""


# 一屏「选项挪得很低」的答题界面 —— 专门用来分辨**这一下点的是哪一份界面的坐标**。
#
# 它和 GRE_XML 的第一个选项文字一模一样（都是「adj. 清晰易懂的」），但整排挪到了
# 屏幕下半部分（y≈2005 而不是 811）。于是「用的是读来的屏」还是「用的是 peek 里
# 那份旧屏」在点击坐标上一眼可辨 —— 光断言「读没读屏」是分不出来的。
SHIFTED_OPTION_XML = """<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
<hierarchy rotation="0">
  <node index="0" text="" class="android.widget.FrameLayout" package="com.enhance.greapp"
        clickable="false" bounds="[0,0][1212,2512]">
    <node index="0" text="adj. 清晰易懂的" resource-id="com.enhance.greapp:id/tv_question"
          class="android.widget.TextView" package="com.enhance.greapp"
          clickable="true" bounds="[0,1930][1212,2080]" />
    <node index="1" text="adj. 阴郁的，闷闷不乐的" resource-id="com.enhance.greapp:id/tv_question"
          class="android.widget.TextView" package="com.enhance.greapp"
          clickable="true" bounds="[0,2118][1212,2268]" />
  </node>
</hierarchy>
"""


# 哨兵：区分「没指定，从 XML 里推断」和「明确要模拟查不到」
INFER_FROM_XML = object()


def buttons_by_intent(state):
    """
    把 `collect_state` 给的控件数据摊平成 `{意图名: 按钮字典}`。

    界面拿到的就是这样一串「意图名 + 完整文字」（见 `collect_state`），
    断言按意图名取最省事，也最贴近界面那边真正的用法。
    """
    buttons = [b for row in state["controls"] for b in row] + list(state["actions"])
    return {b["intent"]: b for b in buttons}


class FakeAdb:
    """顶替真机：dump 返回固定 XML，tap 只记录不执行"""

    def __init__(self, xml, foreground=INFER_FROM_XML):
        self.xml = xml
        self.taps = []
        self.dump_calls = 0
        self._foreground = foreground

    def dump_ui(self, retries=3, retry_wait=0.4):
        self.dump_calls += 1
        return self.xml

    def tap(self, x, y):
        self.taps.append((x, y))

    def screencap(self):
        return None

    def foreground_package(self):
        """
        默认从 XML 里推断；传 foreground=None 则模拟「查不到」这种情况。
        """
        if self._foreground is not INFER_FROM_XML:
            return self._foreground
        match = re.search(r'package="([\w.]+)"', self.xml)
        return match.group(1) if match else None



class StubPrefetcher:
    """不做预读，永远返回 None，逼主流程走当场读屏"""

    def __init__(self, on_screen=None):
        self.invalidated = 0
        self.after_click_triggers = 0
        self.on_speech_triggers = 0
        self.noted = 0
        self.cached = None      # 测试可以塞一份进去，模拟「已经预读好了」
        self.peeked = None      # 测试可以塞一份进去，模拟「最近见过的那一屏」
        self.peeked_age = 0.0   # 上面那一屏是多少秒前读到的（日志里要打出来）
        self._miss = "还没有预读结果"
        # 「把新读到的一屏播出去」的回调（真 ScreenPrefetcher 的 on_screen）。
        # 桩必须跟着生产代码的语义走：真预读器改成「存下一份新屏时同时播给界面
        # 和控制台」之后，桩若还只记个数字，`grab_screen` 那条「当场读屏」的路
        # 就会在测试里静默丢掉「界面拿得到屏」这层保护 —— 真机上界面一直空着，
        # 而全套测试照样绿。
        self.on_screen = on_screen

    def take(self):
        # **取用但不删除** —— 跟真的 ScreenPrefetcher 保持一致。
        # 桩若在这里悄悄清空，就会掩盖「同一份界面能不能被反复取用」这类问题：
        # 生产代码改了语义、桩没跟上，测试照样全绿，那就等于没测。
        return self.cached

    def take_or_wait(self, timeout=8.0):
        return self.take()

    def miss_reason(self):
        """主流程落空时会把它打进日志（区分「没有」和「过期了」）"""
        return self._miss

    def invalidate(self):
        self.invalidated += 1
        self.cached = None
        self._miss = "刚点击过，缓存已作废（界面要翻页了）"

    def note(self, snap, read_at=None, source=""):
        """
        收下一次读屏。**带 source 的才播出去** —— 跟真的 ScreenPrefetcher 同一个约定
        （见那边 note() 的说明：不传 source = 没人要求播，一声不吭）。
        """
        self.noted += 1
        if source and self.on_screen is not None:
            self.on_screen(snap, source, 0.0)

    def peek(self):
        """
        看一眼最近见过的界面（不消费）。

        两个用处：主循环拿它当识别的提示词；「下一题」的固定坐标路径拿它
        核对前台应用（设计 §6.1 的护栏）。默认 None = 还没有任何界面数据。
        """
        return self.peeked

    def peek_with_age(self):
        """
        跟 peek() 一样，只是把「那一屏是多少秒前读到的」一起带回来。

        按键那条「不等预读」的路要用它写日志（让用户知道自己在冒多大的险）。
        默认 None = 一次都没读到过 —— 这时调用方只能老老实实当场读一次。
        """
        if self.peeked is None:
            return None
        return self.peeked, self.peeked_age

    def trigger_after_click(self):
        self.after_click_triggers += 1

    def trigger_on_speech(self):
        self.on_speech_triggers += 1


class StubVoiceGate:
    """测试里用假的闸门：只记录被静音了几次，不真的等"""

    def __init__(self):
        self.suppressed = 0
        self.enabled = True

    def suppress(self, seconds=None):
        self.suppressed += 1

    def remaining(self):
        return 0.0

    def wait_until_open(self, stop_event=None, poll=0.05):
        return 0.0

    def toggle(self):
        self.enabled = not self.enabled
        return self.enabled


class StubRecognizer:
    last_timing = {}


def make_ctx(xml, preview=False, ui=None):
    """
    造一个最小可用的 ctx。

    `ui` 默认 None —— **整个 ctx 里就不带 "ui" 这个键**，
    模拟「不带 --gui 启动」。要测界面接线时传一个真的 `UiState()`。

    桩预读器也按 `main()` 的接法挂上「播屏」回调（`make_screen_publisher`）——
    于是「读到新屏 → 界面看得见」这条线在桩上也成立，`grab_screen` 里那处
    直接调 `publish_screen` 才能安全去掉（不然同一屏会被播两遍）。
    回调是闭包，`ctx` 在调用时才取值，所以这里先建 ctx 再挂回调没关系。
    """
    cfg = Config()
    fake = FakeAdb(xml)
    ctx = {
        "adb": fake,
        "cfg": cfg,
        "preview": preview,
        "recognizer": StubRecognizer(),
        "voice_gate": StubVoiceGate(),
        "clicker": Clicker(fake, cfg.click, log=lambda *_: None),
    }
    if ui is not None:
        ctx["ui"] = ui
    ctx["prefetcher"] = StubPrefetcher(on_screen=app.make_screen_publisher(ctx))
    return ctx, fake


def make_prefetch_ctx(xml, ui=None, **prefetch_overrides):
    """
    跟 `make_ctx` 一样，但用的是**真** `ScreenPrefetcher`（同样按 main() 的接法挂上
    播屏回调）。要验「预读读完会自己播出来」这条线时必须用它 ——
    桩的 note() 只会照着我写的规矩走，证明不了生产代码真会调回调。

    返回 `(ctx, fake, prefetcher)`。
    """
    cfg = Config()
    for key, value in prefetch_overrides.items():
        setattr(cfg.prefetch, key, value)
    fake = FakeAdb(xml)
    ctx = {
        "adb": fake,
        "cfg": cfg,
        "preview": False,
        "recognizer": StubRecognizer(),
        "voice_gate": StubVoiceGate(),
        "clicker": Clicker(fake, cfg.click, log=lambda *_: None),
    }
    if ui is not None:
        ctx["ui"] = ui
    prefetcher = app.ScreenPrefetcher(
        fake, cfg, log=lambda *_: None, on_screen=app.make_screen_publisher(ctx))
    ctx["prefetcher"] = prefetcher
    return ctx, fake, prefetcher


def wait_for(predicate, timeout=3.0):
    """等某个条件成立。轮询，不靠 sleep 撞运气 —— 条件一成立就往下走。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.005)
    return False


class CountingUiState(UiState):
    """
    数一数界面被写了几次。

    「同一屏别播两遍」这件事只能这么验：`note()` 播一次、调用方又直接
    `publish_screen` 一次的话，界面结果看起来一模一样，只有次数能说明问题
    （控制台上就是同一屏白白多打了一遍）。
    """

    def __init__(self, keep_inputs=8):
        super().__init__(keep_inputs)
        self.set_calls = 0

    def set_screen(self, view):
        self.set_calls += 1
        super().set_screen(view)


class TestHappyPath(unittest.TestCase):
    """正常答题：说出选项里的一部分，点中它"""

    def test_say_partial_word_clicks_correct_option(self):
        ctx, fake = make_ctx(GRE_XML)

        # 用户说「清晰」，选项里有「adj. 清晰易懂的」
        app.handle_speech("清晰", -0.4, ctx)

        self.assertEqual(len(fake.taps), 1, "应该恰好点击一次")

        x, y = fake.taps[0]
        # 第一个选项行的范围是 [0,736][1212,886]，中心应该在 811 附近
        self.assertTrue(0 <= x <= 1212, f"x={x} 越界")
        self.assertTrue(736 <= y <= 886, f"y={y} 没落在第一个选项行内")

    def test_each_option_is_reachable(self):
        """四个选项 + 不记得了，挨个说都要能点中，而且点的是不同的位置"""
        targets = {
            "清晰": (736, 886),
            "阴郁": (924, 1074),
            "骄奢淫逸": (1112, 1262),
            "降低": (1300, 1450),
            "不记得": (1488, 1638),
        }

        for spoken, (y_lo, y_hi) in targets.items():
            with self.subTest(spoken=spoken):
                ctx, fake = make_ctx(GRE_XML)
                app.handle_speech(spoken, -0.4, ctx)
                self.assertEqual(len(fake.taps), 1, f"说 {spoken!r} 应该点击一次")
                _, y = fake.taps[0]
                self.assertTrue(y_lo <= y <= y_hi,
                                f"说 {spoken!r} 点到了 y={y}，不在 [{y_lo},{y_hi}] 行内")

    def test_homophone_still_clicks(self):
        """听成同音字也要点对"""
        ctx, fake = make_ctx(GRE_XML)
        app.handle_speech("骄奢淫意", -0.4, ctx)   # 正确是「骄奢淫逸」
        self.assertEqual(len(fake.taps), 1)
        _, y = fake.taps[0]
        self.assertTrue(1112 <= y <= 1262, f"同音字没点对，y={y}")


class TestSafetyGuard(unittest.TestCase):
    """安全护栏：不该点的时候绝不能点"""

    def test_does_not_click_on_other_app(self):
        """手机停在 QQ 上时，你说话它必须拒绝点击"""
        ctx, fake = make_ctx(QQ_XML)

        app.handle_speech("消息", -0.4, ctx)

        self.assertEqual(fake.taps, [], "在别的 App 上绝对不能点击")

    def test_does_not_click_when_no_match(self):
        """说的词屏幕上没有，不点"""
        ctx, fake = make_ctx(GRE_XML)

        app.handle_speech("香蕉苹果橘子", -0.4, ctx)

        self.assertEqual(fake.taps, [], "匹配不上时不该点击")


class TestPreviewMode(unittest.TestCase):

    def test_preview_does_not_tap(self):
        ctx, fake = make_ctx(GRE_XML, preview=True)
        app.handle_speech("清晰", -0.4, ctx)
        self.assertEqual(fake.taps, [], "preview 模式不该真的点击")


class TestDebounce(unittest.TestCase):

    def test_second_click_is_dropped(self):
        """连着说两次，第二次会被防连点挡掉"""
        ctx, fake = make_ctx(GRE_XML)

        app.handle_speech("清晰", -0.4, ctx)
        app.handle_speech("阴郁", -0.4, ctx)   # 紧接着又来一句

        self.assertEqual(len(fake.taps), 1, "防连点应该挡掉第二次点击")

    def test_same_option_twice_only_clicks_once(self):
        ctx, fake = make_ctx(GRE_XML)
        app.handle_speech("清晰", -0.4, ctx)
        app.handle_speech("清晰", -0.4, ctx)
        self.assertEqual(len(fake.taps), 1)

    def test_skipped_click_keeps_the_cache(self):
        """
        被挡掉的那次点击没有翻页，**不该白白作废缓存**。

        原来不管点没点成都会作废，于是第二次被挡掉时把一份仍然有效的缓存
        清掉了，下一次操作只能重新读屏（白等约 2.4 秒）。界面根本没动，没必要。
        """
        ctx, fake = make_ctx(GRE_XML)

        app.handle_speech("清晰", -0.4, ctx)     # 这一次真的点了
        app.handle_speech("阴郁", -0.4, ctx)     # 这一次被挡掉

        self.assertEqual(len(fake.taps), 1)
        self.assertEqual(ctx["prefetcher"].invalidated, 1,
                         "只有真的点下去那一次才该作废缓存")


class TestPrefetch(unittest.TestCase):
    """预读到的界面数据应该被真正用上，而不是白读"""

    def test_uses_prefetched_screen(self):
        cfg = Config()
        fake = FakeAdb(GRE_XML)

        class CountingPrefetcher(StubPrefetcher):
            def __init__(self, snap):
                super().__init__()
                self.snap = snap
                self.taken = 0

            def take(self):
                self.taken += 1
                return self.snap, 0.4

        prefetcher = CountingPrefetcher(screen.read_screen(GRE_XML))
        ctx = {
            "adb": fake,
            "cfg": cfg,
            "preview": False,
            "recognizer": StubRecognizer(),
            "prefetcher": prefetcher,
            "voice_gate": StubVoiceGate(),
            "clicker": Clicker(fake, cfg.click, log=lambda *_: None),
        }

        app.handle_speech("清晰", -0.4, ctx)

        self.assertEqual(prefetcher.taken, 1, "应该用上预读的结果")
        self.assertEqual(len(fake.taps), 1)


class TestScreenSnapshotUsedByMatcher(unittest.TestCase):
    """护栏其实是在这一层生效的 —— 确认一下选项来源"""

    def test_options_come_only_from_tv_question(self):
        snap = screen.read_screen(GRE_XML)
        self.assertNotIn(snap.prompt, snap.option_texts())
        self.assertEqual(len(snap.options), 5)


class TestPrefetchInvalidation(unittest.TestCase):
    """
    点完必须把预抓取的界面数据作废。

    点下去那一瞬 App 会翻到下一题。如果不清掉缓存，万一某次预抓取的线程
    回来得特别晚，下一句话就会拿着上一题的选项去匹配 —— 那就点到错的地方了。
    """

    def test_invalidated_after_click(self):
        ctx, fake = make_ctx(GRE_XML)
        app.handle_speech("清晰", -0.4, ctx)
        self.assertEqual(fake.taps and ctx["prefetcher"].invalidated, 1,
                         "点击之后必须作废预抓取缓存")

    def test_not_invalidated_when_nothing_clicked(self):
        ctx, fake = make_ctx(GRE_XML)
        app.handle_speech("香蕉苹果橘子", -0.4, ctx)
        self.assertEqual(ctx["prefetcher"].invalidated, 0,
                         "没点击就不需要作废")

    def test_not_invalidated_in_preview_mode(self):
        """preview 不真点，界面不会翻，手里那份缓存还是有效的 —— 别白作废"""
        ctx, fake = make_ctx(GRE_XML, preview=True)

        app.handle_speech("清晰", -0.4, ctx)

        self.assertEqual(ctx["prefetcher"].invalidated, 0,
                         "preview 模式下不该作废缓存")



class TestLogging(unittest.TestCase):
    """
    主程序的输出必须落盘。

    它是长时间运行、实时刷屏的，窗口一关就什么都不剩。
    出问题时能翻日志是排查的前提 —— 这一条也是踩过坑才补上的：
    第一次真机试跑崩了，可除了启动器那几行以外什么都没留下。

    （这个类曾经被批量删测试的正则误删过一次，是被 test_inventory.py
    揪出来的 —— 当时套件仍然是全绿的。）
    """

    def setUp(self):
        from voice_tap import main as app
        self.app = app
        self._original = app._LOG_HANDLE
        app._LOG_HANDLE = None

    def tearDown(self):
        if self.app._LOG_HANDLE is not None:
            try:
                self.app._LOG_HANDLE.close()
            except Exception:  # noqa: BLE001
                pass
        self.app._LOG_HANDLE = self._original

    def test_say_writes_to_log_file(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "nested" / "run.log"
            self.app.open_log(path)
            self.app.say("听到 apple")
            self.app.say("点击完成")

            self.assertTrue(path.is_file(), "日志文件应该被创建（含父目录）")
            text = path.read_text(encoding="utf-8")
            self.assertIn("听到 apple", text)
            self.assertIn("点击完成", text)

    def test_say_still_works_without_log(self):
        """日志开不起来时也不能影响正常输出"""
        self.app._LOG_HANDLE = None
        self.app.say("没有日志也要能打印")   # 不该抛异常

    def test_exception_is_recorded(self):
        """未捕获的异常也要落盘，否则窗口一关就查不到原因"""
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "run.log"
            self.app.open_log(path)
            try:
                raise ValueError("模拟的崩溃")
            except ValueError:
                self.app.log_exception()

            text = path.read_text(encoding="utf-8")
            self.assertIn("模拟的崩溃", text)
            self.assertIn("Traceback", text)


class TestNextButton(unittest.TestCase):
    """
    小键盘 0 = 点「下一题」。

    答错或点「不记得了」之后会进详情页，得点它才能继续。
    这段测试曾经被我误删过一次（批量删测试类时正则吃掉了后面的类），
    当时套件仍然是全绿的 —— 所以补回来时特意多写几条。
    """

    def test_reads_screen_and_clicks_button(self):
        ctx, fake = make_ctx(DETAIL_XML)

        app.handle_next(ctx)

        self.assertEqual(len(fake.taps), 1)
        self.assertEqual(fake.taps[0], (600, 2180), "应该点在「下一题」按钮中心")

    def test_fixed_next_position_skips_screen_read(self):
        ctx, fake = make_ctx(DETAIL_XML)
        ctx["cfg"].hotkey.fixed_next_position = (909, 2476)

        app.handle_next(ctx)

        self.assertEqual(fake.dump_calls, 0, "配了固定坐标就不该读屏")
        self.assertEqual(fake.taps, [(909, 2476)])

    def test_fixed_position_blocked_when_peeked_screen_is_other_app(self):
        """
        固定坐标这条路也要有前台护栏（设计文档 §6.1）。

        没有护栏时，手机停在**别的 App**（比如微信/QQ）上，说一句「继续」
        或者「next」也会朝固定坐标 (909, 2476) 点下去 —— 那是盲点行为，
        后果不可预期。用 ctx["prefetcher"].peek()（零读屏成本）拦一道：
        最近见过的那一屏前台不是 GRE3000，就拒绝点击。
        """
        ctx, fake = make_ctx(DETAIL_XML)
        ctx["cfg"].hotkey.fixed_next_position = (909, 2476)
        ctx["prefetcher"].peeked = screen.read_screen(QQ_XML)   # 前台是 QQ

        app.handle_next(ctx)

        self.assertEqual(fake.taps, [], "前台不在 GRE3000 时固定坐标也不能点")

    def test_fixed_position_clicks_when_peeked_screen_is_gre(self):
        """最近见过的那一屏确实是 GRE3000 → 护栏放行，照常点"""
        ctx, fake = make_ctx(DETAIL_XML)
        ctx["cfg"].hotkey.fixed_next_position = (909, 2476)
        ctx["prefetcher"].peeked = screen.read_screen(DETAIL_XML)

        app.handle_next(ctx)

        self.assertEqual(fake.taps, [(909, 2476)])

    def test_fixed_position_clicks_when_peek_is_none(self):
        """
        peek() 还没有任何界面数据（比如刚启动、还没读到过屏）→ 照常点。

        「没有依据就不拦」—— 别为了加护栏反而把正常路径挡死。
        """
        ctx, fake = make_ctx(DETAIL_XML)
        ctx["cfg"].hotkey.fixed_next_position = (909, 2476)
        self.assertIsNone(ctx["prefetcher"].peek(), "桩默认没有界面数据")

        app.handle_next(ctx)

        self.assertEqual(fake.taps, [(909, 2476)])

    def test_no_button_does_not_click(self):
        """答题页上没有「下一题」时不该乱点"""
        ctx, fake = make_ctx(GRE_XML)
        self.assertIsNone(screen.read_screen(GRE_XML).next_button, "夹具里不该有下一题按钮")

        app.handle_next(ctx)

        self.assertEqual(fake.taps, [])

    def test_wrong_app_does_not_click(self):
        ctx, fake = make_ctx(QQ_XML)
        app.handle_next(ctx)
        self.assertEqual(fake.taps, [], "在别的 App 上不能点")

    def test_two_presses_of_next_both_work(self):
        """
        连按两下 0，两次都执行。

        「按住不放」的重复是在 hotkey 那一层用按下/抬起状态挡的；
        能走到这一层的，就是用户真的按了两次。
        在这里再按时间拦一遍只会误伤 —— 这正是之前那个坑。
        """
        ctx, fake = make_ctx(DETAIL_XML)
        ctx["cfg"].hotkey.fixed_next_position = None
        app.handle_next(ctx)
        app.handle_next(ctx)
        self.assertEqual(len(fake.taps), 2)

    def test_next_click_is_recorded_as_next_not_speech(self):
        """
        「下一题」这一下，界面「我的输入」里必须标成 next（标签 0），不能标成 speech。

        由来（任务 6 审查实测）：把 `_input_kind_and_label` 里
        「`("next",)` → `kind="next"`」那一支改成 `speech`，**307 条用例照样全绿** ——
        也就是说小键盘 0 / 语音「下一题」这条点击的来源标签零覆盖，
        真标错了界面上会把「按了 0」显示成一次语音输入，而没人拦得住。
        """
        ctx, fake = make_ctx(DETAIL_XML, ui=UiState())
        ctx["cfg"].click.settle_ms = 0
        ctx["cfg"].hotkey.fixed_next_position = (909, 2476)

        app.handle_next(ctx)

        self.assertEqual(len(fake.taps), 1, "先确认这一下真的点了")
        events = ctx["ui"].recent_inputs()
        self.assertTrue(events, "点完之后界面要能看见「我的输入」")
        self.assertEqual(events[0].kind, "next", "这一下是「下一题」，不能标成别的种类")
        self.assertEqual(events[0].label, "0")


class TestPrefetchIsTriggeredAfterClick(unittest.TestCase):
    """
    点击之后必须触发预读 —— 这是「不用等读屏」的收益来源。

    点下去 App 会翻页，那段时间程序本来闲着。趁它把下一屏读好，
    下次要用时就不必等了。
    """

    def test_triggered_after_a_successful_click(self):
        ctx, fake = make_ctx(GRE_XML)

        app.handle_speech("清晰", -0.4, ctx)

        self.assertEqual(len(fake.taps), 1)
        self.assertEqual(ctx["prefetcher"].after_click_triggers, 1,
                         "点完应该让预读在后台跑起来")

    def test_not_triggered_in_preview_mode(self):
        """preview 不真点，界面不会翻，预读没有意义"""
        ctx, fake = make_ctx(GRE_XML, preview=True)

        app.handle_speech("清晰", -0.4, ctx)

        self.assertEqual(ctx["prefetcher"].after_click_triggers, 0)

    def test_not_triggered_when_nothing_clicked(self):
        """匹配不上、没点，就不该预读"""
        ctx, fake = make_ctx(GRE_XML)

        app.handle_speech("香蕉苹果橘子", -0.4, ctx)

        self.assertEqual(ctx["prefetcher"].after_click_triggers, 0)

    def test_not_triggered_when_click_is_debounced(self):
        """被防连点挡掉的那次点击，界面没翻，不该预读"""
        ctx, fake = make_ctx(GRE_XML)

        app.handle_speech("清晰", -0.4, ctx)      # 这一次真的点了
        app.handle_speech("阴郁", -0.4, ctx)      # 这一次被挡掉

        self.assertEqual(len(fake.taps), 1)
        self.assertEqual(ctx["prefetcher"].after_click_triggers, 1,
                         "只有真的点下去才预读")

    def test_triggered_for_numpad_and_next_too(self):
        """语音、小键盘、下一题三条路都要触发预读"""
        ctx, fake = make_ctx(GRE_XML)
        ctx["cfg"].click.debounce_ms = 0

        app.handle_numpad(1, ctx)
        self.assertEqual(ctx["prefetcher"].after_click_triggers, 1)

        ctx2, fake2 = make_ctx(DETAIL_XML)
        app.handle_next(ctx2)
        self.assertEqual(ctx2["prefetcher"].after_click_triggers, 1)


class TestKeyPressesAreNeverTimeBlocked(unittest.TestCase):
    """
    按键动作**不受任何时间限制**。

    真机日志里踩到的坑：
        用户按 3（点中第 3 个）→ 693 毫秒后按 2 想改过来
        → 2 被当成连点**静默丢掉** → 屏幕上留下的是错的那个
        → 用户看到的是「我按了 2，它却选了 3」

    按错一个键、马上按另一个改过来，是完全合法的操作，必须立刻执行。
    「按住不放造成的重复」是在 hotkey 那一层用按下/抬起状态挡的，
    不靠计时 —— 计时分不清这两种情况。这里钉住的是「不再有计时拦截」。
    """

    def make_ctx(self, xml):
        ctx, fake = make_ctx(xml)
        ctx["cfg"].click.debounce_ms = 800     # 故意设得很长
        ctx["cfg"].click.settle_ms = 0         # 测试里不等界面反应
        return ctx, fake

    def test_different_numbers_both_click(self):
        ctx, fake = self.make_ctx(GRE_XML)

        app.handle_numpad(3, ctx)
        app.handle_numpad(1, ctx)      # 立刻改主意

        self.assertEqual(len(fake.taps), 2, "按不同的键必须都执行")
        self.assertEqual(fake.taps[0][1], 1187, "第一次点第 3 个")
        self.assertEqual(fake.taps[1][1], 811, "第二次点第 1 个")

    def test_same_number_twice_also_clicks(self):
        """
        同一个键连按两次，**在这一层也要放行**。

        因为「按住不放」的重复已经被 hotkey 用按下/抬起状态挡掉了；
        能走到这一层的，就是用户真的按了两次。
        在这里再按时间拦一遍，只会误伤。
        """
        ctx, fake = self.make_ctx(GRE_XML)

        app.handle_numpad(2, ctx)
        app.handle_numpad(2, ctx)

        self.assertEqual(len(fake.taps), 2, "到了这一层就是真的按了两次")

    def test_voice_click_does_not_block_numpad(self):
        ctx, fake = self.make_ctx(GRE_XML)

        app.handle_speech("清晰", -0.4, ctx)
        app.handle_numpad(4, ctx)

        self.assertEqual(len(fake.taps), 2, "语音点完，按键应该照样能点")

    def test_voice_still_debounced(self):
        """语音那条路的时间判断还留着（防同一句话被处理两次）"""
        ctx, fake = self.make_ctx(GRE_XML)

        app.handle_speech("清晰", -0.4, ctx)
        app.handle_speech("阴郁", -0.4, ctx)

        self.assertEqual(len(fake.taps), 1, "语音仍受防连点保护")


class TestVoiceMutedAfterClick(unittest.TestCase):
    """
    点击之后必须进入语音静音期。

    理由（真机日志里查出来的）：点完选项之后，**手机会把那个单词的读音播出来**，
    麦克风会收进去。程序误以为用户在说话，送去识别，得到的就是刚答过那个词 ——
    日志里那一串 'Brooke.' 'Benevolent' 'Convey' 'sinistral' 全是手机念的。
    而那时界面早翻过去了，什么都匹配不上。

    所以点完之后的一两秒内干脆不监听。
    """

    def test_muted_after_successful_click(self):
        ctx, fake = make_ctx(GRE_XML)

        app.handle_speech("清晰", -0.4, ctx)

        self.assertEqual(len(fake.taps), 1, "先确认真的点了")
        self.assertEqual(ctx["voice_gate"].suppressed, 1,
                         "点完应该进入静音期，免得把手机的读音当成用户说话")

    def test_not_muted_in_preview_mode(self):
        """preview 不真点，界面不会翻，手机也不会念单词"""
        ctx, fake = make_ctx(GRE_XML, preview=True)

        app.handle_speech("清晰", -0.4, ctx)

        self.assertEqual(ctx["voice_gate"].suppressed, 0)

    def test_not_muted_when_nothing_clicked(self):
        ctx, fake = make_ctx(GRE_XML)

        app.handle_speech("香蕉苹果橘子", -0.4, ctx)

        self.assertEqual(ctx["voice_gate"].suppressed, 0)

    def test_muted_for_numpad_too(self):
        """小键盘点完，手机一样会念单词"""
        ctx, fake = make_ctx(GRE_XML)

        app.handle_numpad(1, ctx)

        self.assertEqual(ctx["voice_gate"].suppressed, 1)


class TestForceRead(unittest.TestCase):
    """
    小键盘「.」：强制重新读一次界面。

    用途：你自己用鼠标动了手机（翻了页、点开了别的界面），
    而程序手里的还是上一次读到的样子 —— 按一下强制同步。

    它必须**先丢掉手里那份**再读，否则读完存进去的还是旧的。
    """

    def test_reads_fresh_and_stores(self):
        ctx, fake = make_ctx(GRE_XML)

        app.handle_force_read(ctx)

        self.assertEqual(fake.dump_calls, 1, "应该当场读一次屏")
        self.assertGreaterEqual(ctx["prefetcher"].invalidated, 1,
                                "读之前要先丢掉手里的旧数据")
        self.assertGreaterEqual(ctx["prefetcher"].noted, 1,
                                "读到的要存下来，接下来的数字键可以直接用")

    def test_does_not_click_anything(self):
        ctx, fake = make_ctx(GRE_XML)

        app.handle_force_read(ctx)

        self.assertEqual(fake.taps, [], "强制读屏不该顺带点任何东西")

    def test_reports_unusable_screen(self):
        """在别的 App 上按「.」，应该如实说你不在答题界面"""
        ctx, fake = make_ctx(QQ_XML)

        app.handle_force_read(ctx)

        self.assertEqual(fake.taps, [])

    def test_broadcasts_the_fresh_screen_to_the_ui(self):
        """
        强制读屏读到的那一屏要**立刻**出现在界面上，来源标「强制读屏」。

        用**真** `ScreenPrefetcher`（按 main() 的接法挂上 `make_screen_publisher`），
        因为要验的正是「真预读器的 note() 会把屏播出去」—— 桩证明不了这件事。

        改坏看红：把 note() 里那次回调调用去掉，这一条变红（界面永远是空的）。
        """
        ctx, fake, _pref = make_prefetch_ctx(GRE_XML, ui=UiState())

        app.handle_force_read(ctx)

        self.assertEqual(fake.dump_calls, 1, "先确认真的当场读了一次")
        view = ctx["ui"].current_screen()
        self.assertIsNotNone(view, "强制读屏之后界面要拿到刚读到的那一屏")
        self.assertEqual(view.source, "强制读屏")
        self.assertEqual(view.prompt, "degrade")
        self.assertEqual([o.text for o in view.options][:1], ["adj. 清晰易懂的"])


class TestCachedScreenIsUsed(unittest.TestCase):
    """预读到的界面要被真正用上，而不是白读"""

    def test_numpad_uses_cached_screen(self):
        ctx, fake = make_ctx(GRE_XML)
        ctx["cfg"].click.debounce_ms = 0

        # 塞一份预读好的界面进去，模拟「点击后已经读好了」
        snap = screen.read_screen(GRE_XML)
        ctx["prefetcher"].cached = (snap, 0.5)

        app.handle_numpad(3, ctx)

        self.assertEqual(fake.dump_calls, 0, "有预读就不该再读屏")
        _, y = fake.taps[0]
        self.assertTrue(1112 <= y <= 1262, f"应该点第三个选项，实际 y={y}")

    def test_next_button_uses_cached_screen(self):
        ctx, fake = make_ctx(DETAIL_XML)
        ctx["cfg"].hotkey.fixed_next_position = None     # 逼它走读屏那条路
        snap = screen.read_screen(DETAIL_XML)
        ctx["prefetcher"].cached = (snap, 0.5)

        app.handle_next(ctx)

        self.assertEqual(fake.dump_calls, 0, "有预读就不该再读屏")
        self.assertEqual(fake.taps, [(600, 2180)])


class TestKeyPressUsesLastSeenScreen(unittest.TestCase):
    """
    按键不再等预读 —— 缓存空就直接用「最近读到的那一屏」的坐标点。

    用户实测确认的症状：飞快连按两次小键盘，**第二下的响应被拖到新题目出现之后**。
    根因就是 `grab_screen` 里那句 `take_or_wait()`：缓存空、预读正在跑时它睡在那儿
    （最多 8 秒），一直等到预读把新题读完 —— 第二下必然落在新题目上，感觉慢一拍。

    用户明确选了这个取舍（理由与代价写在 `grab_screen` 的注释里）：
    不要吞键、也不要排到读屏之后，**马上立刻执行**；代价是这一下只能用
    上一次读到的那一屏的坐标。他能接受，因为选项位置是稳的（实测五个选项
    严格等距 188 像素，题干很长时整排挪 43 像素，而行高 150、中心到行边还有
    75 像素 —— 不会跨到相邻选项）。他也明确**不要**时间保险，一律不等。

    **第一条是这次改动的主证据**：改之前它要么等、要么当场读，总之
    `dump_calls > 0`；改之后必须是 0。
    """

    def test_numpad_clicks_with_last_seen_screen_without_reading(self):
        ctx, fake = make_ctx(GRE_XML)
        snap = screen.read_screen(GRE_XML)
        ctx["prefetcher"].peeked = snap        # 缓存是空的，但最近读到过这一屏
        expected = snap.options[2]             # 第 3 个选项

        app.handle_numpad(3, ctx)

        self.assertEqual(fake.dump_calls, 0,
                         "按键路径不该等预读、更不该当场读屏 —— 一次屏都不该读")
        self.assertEqual(fake.taps, [(expected.x, expected.y)],
                         "应该用「最近读到那一屏」第 3 个选项的坐标点下去")

    def test_numpad_reads_when_nothing_was_ever_seen(self):
        """
        从头到尾一次都没读到过（比如刚启动）—— 没有旧坐标可用，只能当场读一次。

        这是新逻辑的第三档：缓存空 → peek 也是 None → 才读。
        """
        ctx, fake = make_ctx(GRE_XML)
        # peeked 默认就是 None，不用塞
        expected = screen.read_screen(GRE_XML).options[2]

        app.handle_numpad(3, ctx)

        self.assertGreaterEqual(fake.dump_calls, 1,
                                "一次都没读到过时仍然要当场读一次，不能什么都不干")
        self.assertEqual(fake.taps, [(expected.x, expected.y)],
                         "读完之后照常点第 3 个选项")

    def test_speech_path_is_unchanged(self):
        """
        语音那条路**取舍没变**：缓存空就当场读屏，不用 peek 那份旧坐标。

        这里故意让 peek 里那份屏和真读到的屏**选项位置明显不同**（都在屏幕下方
        y≈2005，而真实的在 y=811）—— 于是「点出来的 y」直接说明用了哪一份坐标：
        走对了就是 811，误用 peek 就是 2005。
        """
        ctx, fake = make_ctx(GRE_XML)
        ctx["prefetcher"].peeked = screen.read_screen(SHIFTED_OPTION_XML)
        expected = screen.read_screen(GRE_XML).options[0]

        app.handle_speech("清晰", -0.4, ctx)

        self.assertGreaterEqual(fake.dump_calls, 1,
                                "语音这条路没改：缓存空就当场读屏，不等也不复用旧坐标")
        self.assertEqual(fake.taps, [(expected.x, expected.y)],
                         "语音点的是刚读到的第 1 个选项，不是 peek 里那份旧屏的位置")


class TestStartupProbe(unittest.TestCase):
    """
    启动时读到的那一屏，必须存进预读缓存。

    不存的话，启动后的**第一次操作**（第一句语音、第一个数字键）会因为缓存
    是空的而当场读屏，白等约 2.4 秒 —— 每开一次程序都会碰到这个空窗。

    存下来还顺带补上一个漏洞：拿这一屏当基准，「第一次点击之后的翻页检测」
    才有东西可比；否则第一次点击没有基准，可能把点击**前**的界面当成翻页结果。
    """

    def test_startup_screen_is_cached(self):
        cfg = Config()
        fake = FakeAdb(GRE_XML)
        prefetcher = app.ScreenPrefetcher(fake, cfg, log=lambda *_: None)

        snap = app.probe_startup_screen(fake, prefetcher, log=lambda *_: None)

        self.assertIsNotNone(snap)
        got = prefetcher.take()
        self.assertIsNotNone(got, "启动时读到的那一屏应该已经在缓存里了")
        self.assertIs(got[0], snap)

    def test_first_action_after_startup_does_not_read_screen(self):
        """启动缓存到位之后，第一次按键不该再读屏"""
        cfg = Config()
        cfg.prefetch.after_click = False     # 别让点击后的后台预读来搅乱计数
        cfg.click.settle_ms = 0
        fake = FakeAdb(GRE_XML)
        prefetcher = app.ScreenPrefetcher(fake, cfg, log=lambda *_: None)
        app.probe_startup_screen(fake, prefetcher, log=lambda *_: None)
        reads_so_far = fake.dump_calls

        ctx = {
            "adb": fake,
            "cfg": cfg,
            "preview": False,
            "recognizer": StubRecognizer(),
            "prefetcher": prefetcher,
            "voice_gate": StubVoiceGate(),
            "clicker": Clicker(fake, cfg.click, log=lambda *_: None),
        }
        app.handle_numpad(1, ctx)

        self.assertEqual(fake.dump_calls, reads_so_far,
                         "启动时已经缓存了当前界面，第一次按键不该再读屏")
        self.assertEqual(len(fake.taps), 1)

    def test_probe_failure_is_not_fatal(self):
        """读屏失败也要能正常启动，只是退化成「第一次操作当场读一次」"""
        class BrokenAdb:
            def dump_ui(self, **kwargs):
                raise AdbError("假装连不上手机")

        cfg = Config()
        prefetcher = app.ScreenPrefetcher(BrokenAdb(), cfg, log=lambda *_: None)

        snap = app.probe_startup_screen(BrokenAdb(), prefetcher, log=lambda *_: None)

        self.assertIsNone(snap)
        self.assertIsNone(prefetcher.take(), "读不到就别往缓存里塞东西")


# 这里曾经有一个 TestActionStamp（动作时戳）—— 2026-09-28 整类删除。
#
# 它守的是「按键之后界面翻了页，这一下就别点了」。但真机日志
# （debug/run_20260927_234859.log）显示它误伤严重：9 次「已忽略」里 7 次
# 用户按的是**不同的键**，是在答下一题。根因是时戳取「程序最近见过的那一屏」，
# 而那一刻程序自己已经落后，旧屏 ≠ 用户眼前的屏 ——
# 它比的不是「屏幕变了没有」，而是「程序自己有没有跟上」。
#
# 用户明确要求：按键一律生效，不要吞。（他自评「误触概率很小」。）
# 若将来「连按两下同一个键点到新题」真的复现，再考虑加「只挡同一个键的短时重复」那道轻拦。


class RecordingQueue:
    """假队列：只把 put 进来的东西记下来，不真的排队"""

    def __init__(self):
        self.items = []

    def put(self, item):
        self.items.append(item)


class TestActionWiring(unittest.TestCase):
    """
    「入队 → 解包分派」这条接线。

    这段原本写在 main() 的三个 lambda 和一个闭包里，外部调不到 ——
    于是谁把它改坏了（忘带值、把二元组当三元组解、把分派写反），
    几百个测试照样全绿，而真机上就是「按了没反应 / 点到别的地方」。

    所以现在这段被抽成 make_action_putters / dispatch_action 两个模块级函数，
    在这里直接钉住它的**可观察后果**（队列里真有那条、真的点了那一下），
    而不是去 monkeypatch 模块级处理函数 —— 那样测到的是桩，不是接线。

    2026-09-28：入队格式从「带动作时戳的三元组」改回**二元组** `(kind, value)`，
    时戳整个取消 —— 下面这些用例跟着去掉了所有跟戳有关的断言。
    取消的理由见本文件里那段注释。
    """

    # ---------------------------------------------------------- 入队

    def _prefetcher_with(self, xml=GRE_XML):
        """造一个已经「见过一屏」的真 ScreenPrefetcher（入队已用不到它，留作参数稳定）"""
        cfg = Config()
        fake = FakeAdb(xml)
        pref = app.ScreenPrefetcher(fake, cfg, log=lambda *_: None)
        pref.note(screen.read_screen(xml))
        return pref

    def test_on_option_puts_the_number(self):
        pref = self._prefetcher_with()
        q = RecordingQueue()

        app.make_action_putters(q, pref)["on_option"](3)

        self.assertEqual(q.items, [("numpad", 3)],
                         "点选项要入队二元组 (\"numpad\", 几号)")

    def test_on_next_puts_next(self):
        pref = self._prefetcher_with()
        q = RecordingQueue()

        app.make_action_putters(q, pref)["on_next"]()

        self.assertEqual(q.items, [("next", None)])

    def test_on_force_read(self):
        """强制读屏只带一个 kind，值位留 None —— 别再挂什么附带信息"""
        pref = self._prefetcher_with()
        q = RecordingQueue()

        app.make_action_putters(q, pref)["on_force_read"]()

        self.assertEqual(q.items, [("force_read", None)])

    def test_number_is_captured_at_press_not_at_execution(self):
        """
        按下的号码必须在**按下那一刻**就定格进队列。

        它不跟屏幕挂钩（所以按完再翻页也不该把它改掉），但它是「这一下要点第几号」——
        入队要是取晚了、或者拖到工作线程里才决定，用户按的 2 就可能变成别的数。
        """
        pref = self._prefetcher_with()
        q = RecordingQueue()
        putters = app.make_action_putters(q, pref)

        putters["on_option"](2)                      # 按下

        pref.note(screen.read_screen(SECOND_XML))     # 按完才翻页

        self.assertEqual(q.items[0], ("numpad", 2),
                         "队列里要钉住按下时那个号码，事后翻页不该把它改掉")

    def test_putters_do_not_need_the_prefetcher(self):
        """
        按键回调不再依赖预读器 —— 传 None 也照样入队。

        这是取消时戳的直接后果：以前 `on_option`/`on_next` 要在按下的那一刻
        调 `prefetcher.identity()` 取屏幕指纹，所以非有预读器不可；
        现在它们只是把动作排进队列。`prefetcher` 参数保留只是为了签名稳定，
        哪天真又需要看屏幕了，这条测试会提醒你一起改。
        """
        q = RecordingQueue()

        app.make_action_putters(q, None)["on_option"](1)

        self.assertEqual(q.items, [("numpad", 1)])

    def test_on_intent_puts_two_tuple(self):
        """
        界面意图入队必须是**二元组** `("intent", 名字)` —— 恰好两个元素。

        这条是 2026-09-28 那次 bug 的护栏：入队还在用上一版带动作时戳的
        三元组时，`dispatch_action` 一解包就抛 ValueError、被静默吞掉，
        结果界面上每一个按钮都「点了没反应」。四个入队点现在都由
        `make_action_putters` 决定格式，这条就钉住界面用的那个。
        """
        pref = self._prefetcher_with()
        q = RecordingQueue()

        app.make_action_putters(q, pref)["on_intent"]("toggle_voice")

        self.assertEqual(q.items, [("intent", "toggle_voice")])
        self.assertEqual(len(q.items[0]), 2,
                         "意图条目是二元组，别再挂一个多余的值")

    def test_on_intent_entry_from_queue_really_runs_the_intent(self):
        """
        界面按钮走**真接线**：`on_intent` 入队的那条 → `dispatch_action` → 意图真被执行。

        这里**不手写**那条队列条目，而是让 `on_intent` 自己产生它、原样交给分派 ——
        手写条目会把「入队格式」和「分派格式」两件事悄悄对齐，就测不到这次的 bug 了。
        这条守的是「界面按钮点了有反应」。
        """
        ctx, fake = make_ctx(GRE_XML)
        calls = []
        ctx["intents"] = {"toggle_voice": lambda: calls.append("toggle_voice")}
        q = RecordingQueue()

        app.make_action_putters(q, ctx["prefetcher"])["on_intent"]("toggle_voice")
        for action in q.items:
            app.dispatch_action(action, ctx)

        self.assertEqual(calls, ["toggle_voice"],
                         "界面按钮的意图要真的被执行，不能只是排进队列就没了")

    # ---------------------------------------------------------- 解包分派

    def test_dispatch_numpad_really_clicks(self):
        """numpad 动作要走到底、真的点一下第 1 个选项"""
        ctx, fake = make_ctx(GRE_XML)
        ctx["cfg"].click.debounce_ms = 0

        app.dispatch_action(("numpad", 1), ctx)

        self.assertEqual(len(fake.taps), 1, "numpad 动作应该真点一下")
        _, y = fake.taps[0]
        self.assertTrue(736 <= y <= 886, f"应该点第 1 个选项，实际 y={y}")

    def test_dispatch_next_clicks_the_next_button(self):
        """next 动作去点「下一题」，而不是被当成点选项"""
        ctx, fake = make_ctx(DETAIL_XML)

        app.dispatch_action(("next", None), ctx)

        self.assertEqual(fake.taps, [(600, 2180)],
                         "next 应该点到「下一题」按钮中心")

    def test_dispatch_force_read_reads_and_does_not_click(self):
        """force_read 只重读一次屏，不点任何东西"""
        ctx, fake = make_ctx(GRE_XML)

        app.dispatch_action(("force_read", None), ctx)

        self.assertEqual(fake.dump_calls, 1, "强制读屏应该当场读一次")
        self.assertEqual(fake.taps, [], "强制读屏不该顺带点东西")

    def test_dispatch_passes_the_value_through(self):
        """
        分派时必须把号數**原样传给** handle_numpad。

        要是 dispatch_action 把第二个元素弄丢或弄错（比如写成 handle_numpad(ctx)），
        按 2 就会点到别的选项上。这里按 2，就该落在第 2 个选项的坐标上。
        """
        ctx, fake = make_ctx(GRE_XML)
        ctx["cfg"].click.debounce_ms = 0
        expected_y = screen.read_screen(GRE_XML).options[1].y

        app.dispatch_action(("numpad", 2), ctx)

        self.assertEqual(len(fake.taps), 1)
        self.assertEqual(fake.taps[0][1], expected_y,
                         "按 2 应该点到第 2 个选项，说明号數被原样传到了")

    # ---------------------------------------------------------- 坏格式不崩

    def test_undecomposable_action_warns(self):
        """
        压根解不开的条目要**出声**：意图不执行，并且 `say()` 打出警告。

        这跟「认不出来的 kind 静默忽略」是两回事 —— 后者是设计决定（见
        `dispatch_action` 的注释），前者说明**我们自己的入队格式对不上**，
        正是 2026-09-28 那次「界面按钮全体装死」的根因。所以这里断言
        `say()` 把收到的原样打了出来，坏东西不再无声无息地消失。
        """
        ctx, fake = make_ctx(GRE_XML)
        calls = []
        ctx["intents"] = {"toggle_voice": lambda: calls.append("toggle_voice")}

        with mock.patch.object(app, "say") as fake_say:
            app.dispatch_action(("intent", "toggle_voice", None), ctx)

        self.assertEqual(calls, [], "解不开的条目不该执行任何意图")
        printed = " ".join(str(c.args[0]) for c in fake_say.call_args_list if c.args)
        self.assertIn("解不开", printed, "解不开时要出声，别无声返回")
        self.assertIn("toggle_voice", printed, "警告里要把收到的原样打出来")

    def test_malformed_action_does_not_click_or_crash(self):
        """
        格式不对的条目一律忽略：不抛异常，也不产生点击（改坏时会在日志里喊一声）。

        这是工作线程的最后一道关口 —— 半截元组、None、一个数字之类的东西
        不该把线程掀翻，更不该冒出一个「点一下」的副作用。
        """
        bad_actions = [
            3,                      # 根本不是可迭代对象
            None,
            ("numpad",),            # 太短：缺了号码
            ("numpad", 1, None),    # 太长：三元组是上一版带动作时戳的格式，现在不认了
            ("numpad", 1, None, 2), # 更长
            (),
            "numpad",               # 字符串（会被逐字符拆开，长度也不对）
            "ab",                   # 长度 2 的字符串：解出来 kind 认不出，也不该点
            "abc",                  # 长度 3：解包时值太多，同样不认
        ]

        for bad in bad_actions:
            with self.subTest(bad=bad):
                ctx, fake = make_ctx(GRE_XML)
                # 解不开的那几种现在会往日志喊一声；这是预期行为，
                # 这里把 say 换掉，免得一屏噪音淹了测试输出。
                with mock.patch.object(app, "say"):
                    app.dispatch_action(bad, ctx)    # 不该抛异常
                self.assertEqual(fake.taps, [], f"{bad!r} 不该点任何东西")

    def test_unknown_kind_is_ignored(self):
        """将来加了 kind 而分支没跟上时，宁可什么都不做，也不能乱点"""
        ctx, fake = make_ctx(GRE_XML)

        app.dispatch_action(("nonsense", 1), ctx)

        self.assertEqual(fake.taps, [])


class TestVoiceNextCommand(unittest.TestCase):
    """
    说「下一题」= 点下一题（直给：不读屏校验）。

    2026-09-28：`voice.next_command` 并入 `voice.commands`，并且**默认关**。
    这个开关同时管「说序号」那条路（见 tests/test_matcher.py 的
    TestOrdinalCanBeDisabled）—— 因为两者都是「一句话直接触发一个动作」，
    杂音里冒出「第一个」「继续」就会误点。
    """

    def _ctx(self, xml):
        ctx, fake = make_ctx(xml)
        ctx["cfg"].hotkey.fixed_next_position = (909, 2476)
        return ctx, fake

    def test_saying_next_clicks_the_button(self):
        ctx, fake = self._ctx(DETAIL_XML)
        ctx["cfg"].voice.commands = True

        app.handle_speech("下一题", -0.4, ctx)

        self.assertEqual(fake.taps, [(909, 2476)])
        self.assertEqual(fake.dump_calls, 0, "固定坐标不该读屏")

    def test_works_on_quiz_page_too(self):
        """直给：答题页上说了照样点（用户明确接受这个取舍）"""
        ctx, fake = self._ctx(GRE_XML)
        ctx["cfg"].voice.commands = True

        app.handle_speech("下一题", -0.4, ctx)

        self.assertEqual(fake.taps, [(909, 2476)])

    def test_disabled_by_config(self):
        """开关关着时，说「下一题」不点（默认就是关 —— 这一条钉的是出厂行为）"""
        ctx, fake = self._ctx(DETAIL_XML)

        app.handle_speech("下一题", -0.4, ctx)

        self.assertEqual(fake.taps, [], "关掉之后不该点；应落回普通匹配并提示详情页")

    def test_ordinal_disabled_by_config(self):
        """
        同一个开关也管「说序号」这条路。

        这条钉的是 main 里的接线：`matcher.match(..., allow_ordinal=voice.commands)`。
        只改 matcher 是不够的 —— 忘了传这个参数，「1」照样会点下去，
        而 default 关的意图就落空了。
        """
        ctx, fake = make_ctx(GRE_XML)

        app.handle_speech("3", -0.4, ctx)

        self.assertEqual(fake.taps, [], "开关关着时，说序号不该点任何选项")

    def test_ordinal_clicks_when_enabled(self):
        """开关打开时，说序号仍然照常点（别把关掉做成了彻底废掉）"""
        ctx, fake = make_ctx(GRE_XML)
        ctx["cfg"].voice.commands = True

        app.handle_speech("3", -0.4, ctx)

        expected = screen.read_screen(GRE_XML).options[2]
        self.assertEqual(fake.taps, [(expected.x, expected.y)],
                         "打开开关后，说「3」应当点到第 3 个选项")

    def test_saying_word_still_clicks_when_commands_off(self):
        """说单词选选项**不受这个开关管** —— 它是用户语音的主力用法"""
        ctx, fake = make_ctx(GRE_XML)

        app.handle_speech("清晰", -0.4, ctx)

        expected = screen.read_screen(GRE_XML).options[0]
        self.assertEqual(fake.taps, [(expected.x, expected.y)],
                         "开关管的是序号和控制语，不是「说选项里的词」")


class QuitAfterNCalls:
    """
    假的 `quit_requested`：被 `is_set()` 问到第 N 次时回答「是」。

    主循环是 `while not hotkeys.quit_requested.is_set()`，只要不置位就永远转下去。
    要驱动那些**这一圈不会自己退出**的分支（喂 None、喂空串、语音关掉），
    与其另起一个线程去掐它，不如让这个假事件自己数圈数 —— 数够就走。
    于是这类用例是确定性的、毫秒级结束的，也不会出现「挂死」这种最难看的红。
    """

    def __init__(self, n):
        self._n = n
        self.asked = 0          # 被问了几次（= 循环回到顶部几次）

    def is_set(self):
        self.asked += 1
        return self.asked >= self._n


class StubHotkeys:
    """最小可用的热键替身：主循环只需要这两个事件"""

    def __init__(self, quit_after=None):
        # quit_after=N 时改用「问够 N 次才置位」的假事件，方便驱动循环体（见 QuitAfterNCalls）
        self.quit_requested = (QuitAfterNCalls(quit_after) if quit_after
                               else threading.Event())
        self.ptt_pressed = threading.Event()


class StubRecognizerLoop:
    """只记录被怎么调用的假识别器 —— 用来驱动主循环的各条分支"""

    last_timing = {}

    def __init__(self, utterances=None, record_stop=False):
        self.utterances = list(utterances or [])
        self.calls = []          # [("listen_once", kwargs) | ("listen_pressed", kwargs)]
        self.held_events = []    # listen_pressed 收到的第一个实参（「正在按住」那个事件）
        # 记下进监听那一刻「中断源是否已被置位」——「唤醒有没有被吞掉」就看它。
        # 默认关：stop_event 有时是 QuitAfterNCalls，调一次 is_set() 就多算一圈，
        # 会打乱别的用例对圈数的断言。只在真的要看它时才开。
        self.record_stop = record_stop
        self.stop_states = []

    def listen_once(self, **kwargs):
        self.calls.append(("listen_once", kwargs))
        if self.record_stop:
            stop = kwargs.get("stop_event")
            self.stop_states.append(None if stop is None else stop.is_set())
        return self.utterances.pop(0) if self.utterances else None

    def listen_pressed(self, held_event, **kwargs):
        self.calls.append(("listen_pressed", kwargs))
        self.held_events.append(held_event)
        return self.utterances.pop(0) if self.utterances else None


class WakeDuringGate(StubVoiceGate):
    """
    假闸门：`wait_until_open()` 一被调用就把 `wake_event` 置位。

    这模拟的是审查里那个真实场景 —— 主循环正阻塞在「点击后的静音期」里，
    用户在界面点了开关，于是 handle_intent 置位了 wake_event。
    进监听时那个置位必须还活着，才能立刻把监听打断、回顶部重新判断。
    """

    def __init__(self, wake_event):
        super().__init__()
        self.wake_event = wake_event

    def wait_until_open(self, stop_event=None, poll=0.05):
        self.wake_event.set()
        return 0.0


class TestRunVoiceLoop(unittest.TestCase):
    """
    主循环必须能被单独调用 —— 界面要占主线程，它得能挪到后台线程去。
    这一步是**纯重构**，行为必须和以前一模一样。
    """

    def test_returns_at_once_when_quit_already_requested(self):
        hotkeys = StubHotkeys()
        hotkeys.quit_requested.set()
        ctx = {"mode": "listen", "voice_gate": StubVoiceGate()}

        class MustNotBeCalled:
            def listen_once(self, **kwargs):
                raise AssertionError("已经请求退出了，不该再去监听")

        app.run_voice_loop(ctx, hotkeys, MustNotBeCalled(), once=False)


class TestRunVoiceLoopBranches(unittest.TestCase):
    """
    主循环的**循环体**也要被真的驱动到。

    为什么单开这一类：上面那条 `TestRunVoiceLoop` 只钉住了「入口条件」——
    把 `run_voice_loop` 的循环体整段删空、只留 `return`，它照样绿
    （`quit_requested` 已置位，`while` 根本不进）。也就是说那时的「全绿」
    对循环体是**零约束**，而「加 wake_event」这一步马上要动这个函数。

    所以这里用假识别器 + 假热键把循环真的转起来，**每条分支配一个能变红的断言**。
    不起真线程、不碰真音频。

    两个假事件的分工：
      - `QuitAfterNCalls` 让「这一圈不会自己退出」的用例跑够圈数后自己收尾；
      - `StubRecognizerLoop` 按喂进去的台词回答，并记下自己被怎么调用。
    """

    def _ctx(self, xml=GRE_XML, mode="listen"):
        ctx, fake = make_ctx(xml)
        ctx["mode"] = mode
        return ctx, fake

    # ---------------------------------------------------------- listen 模式

    def test_listen_mode_goes_through_listen_once(self):
        """常驻监听：走 listen_once，带上「屏幕提示词」与「开口了」回调，然后真的点一下"""
        ctx, fake = self._ctx()
        recognizer = StubRecognizerLoop([("清晰", -0.4)])
        hotkeys = StubHotkeys(quit_after=3)

        app.run_voice_loop(ctx, hotkeys, recognizer, once=True)

        kind, kwargs = recognizer.calls[0]
        self.assertEqual(kind, "listen_once")
        self.assertIn("hint_snapshot", kwargs, "要拿屏幕上的选项当提示词喂给识别")
        self.assertIn("on_speech_start", kwargs, "要能感知「你开口了」去触发预读")
        self.assertEqual(len(fake.taps), 1, "喂进去的那一句应该被真的点掉")

    def test_voice_off_short_circuits_before_listening(self):
        """语音关着（F7）时连监听都不该进 —— 省得白忙一场"""
        ctx, fake = self._ctx()
        recognizer = StubRecognizerLoop([("清晰", -0.4)])
        hotkeys = StubHotkeys(quit_after=2)
        ctx["voice_gate"].enabled = False

        app.run_voice_loop(ctx, hotkeys, recognizer)

        self.assertEqual(recognizer.calls, [], "语音关着还去监听，就是白等一次说话")
        self.assertEqual(fake.taps, [])

    # ---------------------------------------------------------- 唤醒不被吞掉

    def test_wake_arriving_during_gate_wait_is_not_swallowed(self):
        """
        唤醒在 `wait_until_open`（点击后的静音期）里到达 —— 不能被抹掉。

        `clear()` 若放在 `wait_until_open` **之后**，这个静音期里置位的
        wake_event 会被那一句清掉，于是合成的 stop_event 报「没被置位」，
        监听带着过期状态老老实实阻塞进去 —— 一次唤醒被静默吞掉，
        用户点了开关却要等到下次开口才生效。

        所以 `clear()` 必须在循环**开头**、进等待之前：
        只丢上一轮的陈旧唤醒，放过等待期间新到的那一次。
        """
        ctx, _fake = self._ctx()
        wake = threading.Event()
        # 喂一句正常台词 + once：跑完这一圈就 break，不会挂死，
        # 也不依赖 QuitAfterNCalls（那个假事件连 stop.is_set() 也会数进去）。
        recognizer = StubRecognizerLoop([("清晰", -0.4)], record_stop=True)
        hotkeys = StubHotkeys()
        ctx["voice_gate"] = WakeDuringGate(wake)   # 静音期里用户点了开关

        app.run_voice_loop(ctx, hotkeys, recognizer, once=True, wake_event=wake)

        self.assertEqual(
            recognizer.stop_states, [True],
            "静音期里到达的唤醒被吞了 —— 进监听时 stop_event 没报置位，"
            "监听会带着过期状态阻塞进去。clear() 必须在循环开头，不能放在 wait_until_open 之后。")

    # ---------------------------------------------------------- hotkey 模式

    def test_hotkey_mode_goes_through_listen_pressed(self):
        """按住说话：走 listen_pressed，且把「正在按住」那个事件原样传下去"""
        ctx, fake = self._ctx(mode="hotkey")
        recognizer = StubRecognizerLoop([("清晰", -0.4)])
        hotkeys = StubHotkeys(quit_after=3)
        hotkeys.ptt_pressed.set()      # 先按住，否则这一圈会在 wait(0.2) 上白等

        app.run_voice_loop(ctx, hotkeys, recognizer, once=True)

        kind, kwargs = recognizer.calls[0]
        self.assertEqual(kind, "listen_pressed")
        self.assertIs(recognizer.held_events[0], hotkeys.ptt_pressed,
                      "必须把「正在按住」那个事件原样传下去，否则松开也停不下来")
        self.assertIn("hint_snapshot", kwargs)
        self.assertEqual(len(fake.taps), 1)

    # ---------------------------------------------------------- 跳过这一句

    def test_none_utterance_keeps_looping_without_clicking(self):
        """识别返回 None（没听清）—— 不点，回到顶部接着听下一句"""
        ctx, fake = self._ctx()
        recognizer = StubRecognizerLoop([None])
        hotkeys = StubHotkeys(quit_after=2)

        app.run_voice_loop(ctx, hotkeys, recognizer)

        self.assertEqual(fake.taps, [], "没听清绝不能点")
        self.assertEqual(fake.dump_calls, 0, "没听清就不用读屏")
        self.assertEqual(hotkeys.quit_requested.asked, 2,
                         "应该回到 while 顶部接着听（被问第二次说明真的转了一圈）")

    def test_blank_text_is_skipped_without_clicking(self):
        """识别成一片空白（只有空格）—— 跳过，别当成一句话去匹配"""
        ctx, fake = self._ctx()
        recognizer = StubRecognizerLoop([("   ", -0.4)])
        hotkeys = StubHotkeys(quit_after=2)

        app.run_voice_loop(ctx, hotkeys, recognizer)

        self.assertEqual(fake.taps, [], "空话不能点")
        self.assertEqual(fake.dump_calls, 0, "空话连屏都不用读")
        self.assertEqual(hotkeys.quit_requested.asked, 2, "应该回到 while 顶部继续下一圈")

    # ---------------------------------------------------------- 兜底与收尾

    def test_adb_error_is_absorbed_and_loop_survives(self):
        """
        读屏失败（比如手机掉了）—— 记下来，循环照常转，不崩。

        这条钉的是**结果**（异常不会掀翻循环），不是循环里那个
        `except AdbError` 分支本身。审查实测：删掉任意**一层** `except AdbError`
        它都还是绿的，只有两层都删才变红 —— `handle_speech` 里一层、
        主循环里一层。而主循环那一层目前其实**不可达**（下游的 adb 调用
        要么自己捕获，要么在预读线程里被吞）。
        所以别为了「真覆盖到那个分支」去加奇怪的桩：那样只会测到测试脚手架，
        不是行为。
        """
        ctx, _fake = self._ctx()

        class BrokenAdb:
            """除了读屏会炸，别的照旧 —— 主循环的兜底就是为它写的"""

            def __init__(self, inner):
                self._inner = inner

            def dump_ui(self, retries=3, retry_wait=0.4):
                raise AdbError("假装手机掉线了")

            def __getattr__(self, name):
                return getattr(self._inner, name)

        real = ctx["adb"]
        ctx["adb"] = BrokenAdb(real)
        recognizer = StubRecognizerLoop([("清晰", -0.4)])
        hotkeys = StubHotkeys(quit_after=3)

        app.run_voice_loop(ctx, hotkeys, recognizer, once=True)

        self.assertEqual(len(recognizer.calls), 1, "循环应该照常走完这一句")
        self.assertEqual(real.taps, [], "读屏都失败了，这一句不可能点成")

    def test_once_returns_after_a_single_utterance(self):
        """--once：跑完一句就真的返回，不再听第二句"""
        ctx, fake = self._ctx()
        recognizer = StubRecognizerLoop([("清晰", -0.4)])
        # quit_after=3 是护栏：万一 break 没了，循环会在数到 3 时退出，
        # 于是下面「只调了一次」的断言变红 —— 而不是把这个用例挂死在那儿。
        hotkeys = StubHotkeys(quit_after=3)

        app.run_voice_loop(ctx, hotkeys, recognizer, once=True)

        self.assertEqual(len(recognizer.calls), 1,
                         "once 模式跑完一句就该退出，不该再听一轮")
        self.assertEqual(len(fake.taps), 1)


class TestHandleIntent(unittest.TestCase):
    """
    界面按钮走这里。**调的必须是和热键完全相同的函数** ——
    不写第二套逻辑，否则会出现「界面显示开着、实际没开」这种分裂。
    """

    def _ctx(self):
        cfg = Config()
        calls = []
        ctx = {
            "cfg": cfg,
            "intents": {
                "toggle_voice": lambda: calls.append("voice"),
                "toggle_mode": lambda: calls.append("mode"),
            },
        }
        return ctx, calls

    def test_dispatches_to_the_same_function(self):
        ctx, calls = self._ctx()
        app.handle_intent("toggle_voice", ctx)
        self.assertEqual(calls, ["voice"])

    def test_unknown_intent_is_ignored(self):
        ctx, calls = self._ctx()
        app.handle_intent("乱写的名字", ctx)
        self.assertEqual(calls, [])

    def test_wakes_the_listener_afterwards(self):
        ctx, _calls = self._ctx()
        wake = threading.Event()

        app.handle_intent("toggle_voice", ctx, wake_event=wake)

        self.assertTrue(wake.is_set(), "执行完要唤醒监听线程，开关才会立刻生效")

    def test_voice_commands_intent_flips_the_real_switch(self):
        """
        「语音选择」按钮走**真接线**：`control_intents` 里那条名字 → 翻 `cfg.voice.commands`。

        这里**不自己另抄一份 lambda**（抄一份就只测了抄的那份，测不到 main() 里那张表）。
        名字或行为哪个对不上，这条当场就红 —— 这正是「界面点了没反应」的护栏。
        """
        ctx = {"cfg": Config()}
        ctx["intents"] = app.control_intents(ctx)

        app.handle_intent("toggle_voice_commands", ctx)
        self.assertTrue(ctx["cfg"].voice.commands, "点一下应当打开语音说序号/下一题")

        app.handle_intent("toggle_voice_commands", ctx)
        self.assertFalse(ctx["cfg"].voice.commands, "再点一下应当关回去")

    def test_cycle_language_intent_rotates_auto_zh_en(self):
        """识别语言按 自动(None) → 中文(zh) → 英文(en) → 自动 轮转（规则在 main.py）"""
        ctx = {"cfg": Config()}
        ctx["intents"] = app.control_intents(ctx)

        seen = []
        for _ in range(3):
            app.handle_intent("cycle_language", ctx)
            seen.append(ctx["cfg"].asr.language)

        self.assertEqual(seen, ["zh", "en", None])


class TestToggleFlag(unittest.TestCase):
    """界面上那两个没有对应热键的开关（预读、语音下一题）"""

    def test_flips_and_flips_back(self):
        ctx = {"cfg": Config()}

        app._toggle_flag(ctx, "prefetch", "after_click", "点击后预读")
        self.assertFalse(ctx["cfg"].prefetch.after_click)

        app._toggle_flag(ctx, "prefetch", "after_click", "点击后预读")
        self.assertTrue(ctx["cfg"].prefetch.after_click)

    def test_works_on_voice_commands(self):
        """界面那个「语音说序号/下一题」开关（没有对应热键，走 _toggle_flag）"""
        ctx = {"cfg": Config()}
        self.assertFalse(ctx["cfg"].voice.commands, "这个开关默认就是关")

        app._toggle_flag(ctx, "voice", "commands", "语音说序号/下一题")
        self.assertTrue(ctx["cfg"].voice.commands, "翻一下应当变成开")

        app._toggle_flag(ctx, "voice", "commands", "语音说序号/下一题")
        self.assertFalse(ctx["cfg"].voice.commands, "再翻一下应当变回关")


class TestAnyEvent(unittest.TestCase):

    def test_true_if_any_set(self):
        a, b = threading.Event(), threading.Event()
        any_event = app._AnyEvent(a, b)
        self.assertFalse(any_event.is_set())
        b.set()
        self.assertTrue(any_event.is_set())


class TestCollectState(unittest.TestCase):
    """
    界面要显示的东西都从这儿来。**纯读**，所以能单测。

    开关的真相源是那些活对象，这里现读 —— 不另存一份，
    否则会出现「界面显示开着、实际没开」的分裂。

    「界面上有哪些按钮、每个按钮写什么、点一下发哪个意图名」**全在这里拼好**，
    `gui.py` 只是照着数据摆控件、点一下把意图名交出去 ——
    界面那边不再认键名、认标签、认快捷键，也就不存在「两边没一起改」的病。
    """

    def _ctx(self):
        cfg = Config()
        gate = StubVoiceGate()
        hotkeys = StubHotkeys()
        hotkeys.numpad_enabled = True
        return {
            "cfg": cfg,
            "mode": "listen",
            "voice_gate": gate,
            "hotkeys": hotkeys,
            "ui": UiState(),
        }

    # ---------------------------------------------------------- 开关状态

    def test_reports_live_toggles(self):
        ctx = self._ctx()
        # 语音控制开关默认关；这里要验的是「现读活对象」，所以先把它打开
        ctx["cfg"].voice.commands = True
        buttons = buttons_by_intent(app.collect_state(ctx))
        self.assertTrue(buttons["toggle_voice"]["on"])
        self.assertIn("开", buttons["toggle_voice"]["text"])
        self.assertIn("常驻监听", buttons["toggle_mode"]["text"])
        self.assertTrue(buttons["toggle_numpad"]["on"])
        self.assertIn("开", buttons["toggle_numpad"]["text"])
        self.assertTrue(buttons["toggle_prefetch"]["on"])
        self.assertIn("开", buttons["toggle_prefetch"]["text"])
        self.assertTrue(buttons["toggle_voice_commands"]["on"])
        self.assertIn("开", buttons["toggle_voice_commands"]["text"])

    def test_voice_commands_toggle_defaults_off(self):
        """界面拿到的值必须跟着配置走 —— 默认关就要显示关"""
        buttons = buttons_by_intent(app.collect_state(self._ctx()))
        self.assertFalse(buttons["toggle_voice_commands"]["on"],
                         "说序号/下一题合并后的开关默认关")
        self.assertIn("关", buttons["toggle_voice_commands"]["text"])

    def test_reflects_changes_immediately(self):
        ctx = self._ctx()
        ctx["cfg"].prefetch.after_click = False
        buttons = buttons_by_intent(app.collect_state(ctx))
        self.assertFalse(buttons["toggle_prefetch"]["on"])
        self.assertIn("关", buttons["toggle_prefetch"]["text"])

    def test_mode_button_shows_the_current_mode(self):
        """模式那个按钮显示的是「当前是什么模式」，不是开/关"""
        ctx = self._ctx()
        buttons = buttons_by_intent(app.collect_state(ctx))
        self.assertIn("常驻监听", buttons["toggle_mode"]["text"])

        ctx["mode"] = "hotkey"
        buttons = buttons_by_intent(app.collect_state(ctx))
        self.assertIn("按住说话", buttons["toggle_mode"]["text"])

    # ---------------------------------------------------------- 快捷键标注

    def test_buttons_carry_their_hotkey_in_the_text(self):
        """用户要求：每个有快捷键的按钮，文字里要看得见那个键"""
        buttons = buttons_by_intent(app.collect_state(self._ctx()))
        self.assertIn("F7", buttons["toggle_voice"]["text"])
        self.assertIn("F9", buttons["toggle_mode"]["text"])
        self.assertIn("F10", buttons["toggle_numpad"]["text"])
        self.assertIn("ESC", buttons["quit"]["text"], "退出也该标出 ESC")

    def test_hotkeys_come_from_config_not_hardcoded(self):
        """快捷键从 `cfg.hotkey` 现取 —— 配置里改了，界面上就得跟着改。

        这条守的是「别在 main.py 里把 f7/f9/f10 写死」：写死的话，
        用户改了 config.yaml、界面却还标着旧键，等于骗人。
        """
        ctx = self._ctx()
        ctx["cfg"].hotkey.toggle_voice = "f1"
        ctx["cfg"].hotkey.toggle_mode = "f2"
        ctx["cfg"].hotkey.toggle_numpad = "f3"

        buttons = buttons_by_intent(app.collect_state(ctx))
        self.assertIn("F1", buttons["toggle_voice"]["text"])
        self.assertIn("F2", buttons["toggle_mode"]["text"])
        self.assertIn("F3", buttons["toggle_numpad"]["text"])
        self.assertNotIn("F7", buttons["toggle_voice"]["text"],
                         "不该还写着配置里那个旧值")

    def test_buttons_without_a_hotkey_have_no_suffix(self):
        """没有快捷键的控件（点击后预读、语音选择、识别语言）不该带任何键名"""
        buttons = buttons_by_intent(app.collect_state(self._ctx()))
        for name in ("toggle_prefetch", "toggle_voice_commands", "cycle_language"):
            for key in ("F7", "F8", "F9", "F10", "ESC"):
                self.assertNotIn(key, buttons[name]["text"],
                                 f"{name} 没有对应快捷键，不该出现 {key}")

    def test_language_button_text_follows_the_current_language(self):
        """识别语言那个按钮的文字要跟着当前语言变（自动 / 中文 / 英文）"""
        ctx = self._ctx()

        def text():
            return buttons_by_intent(app.collect_state(ctx))["cycle_language"]["text"]

        self.assertIn("自动", text(), "默认（None）应当显示「自动」")
        ctx["cfg"].asr.language = "zh"
        self.assertIn("中文", text())
        ctx["cfg"].asr.language = "en"
        self.assertIn("英文", text())

    # ---------------------------------------------------------- 布局

    def test_controls_are_two_rows_of_three(self):
        """控制区是两行、每行三个 —— 布局由数据给出，不是写死在 gui.py 里"""
        state = app.collect_state(self._ctx())
        self.assertEqual([len(row) for row in state["controls"]], [3, 3])

    def test_every_button_knows_its_intent(self):
        """每个按钮都要带着意图名 —— 界面就靠这个名字把点击交出去"""
        state = app.collect_state(self._ctx())
        buttons = buttons_by_intent(state)
        self.assertEqual(
            set(buttons),
            {"toggle_voice", "toggle_mode", "toggle_numpad", "toggle_prefetch",
             "toggle_voice_commands", "cycle_language", "force_read", "quit"},
        )
        for name, button in buttons.items():
            self.assertTrue(button["text"], f"{name} 的按钮文字不能是空的")

    def test_without_ui_returns_empty(self):
        ctx = self._ctx()
        del ctx["ui"]
        state = app.collect_state(ctx)
        self.assertIsNone(state["screen"])
        self.assertEqual(state["inputs"], [])


class TestUnwiredIntents(unittest.TestCase):
    """
    界面按钮的全部行为就是「把意图名交出去」，表里没有 = 这个按钮是死的。

    上回就是这个病：入队格式改了、界面键名没跟上，界面每个按钮都点了没反应，
    而测试全绿。这个函数让 main() 能当场把这种错喊出来。
    """

    def test_flags_a_name_the_table_forgot(self):
        state = {"controls": [[{"intent": "toggle_voice"}, {"intent": "ghost"}]],
                 "actions": []}
        self.assertEqual(app.unwired_intents(state, {"toggle_voice": lambda: None}),
                         ["ghost"])

    def test_flags_names_in_the_bottom_row_too(self):
        state = {"controls": [], "actions": [{"intent": "quit"}]}
        self.assertEqual(app.unwired_intents(state, {}), ["quit"])

    def test_empty_when_everything_is_wired(self):
        state = {"controls": [[{"intent": "a"}, {"intent": "b"}]],
                 "actions": [{"intent": "c"}]}
        self.assertEqual(app.unwired_intents(state, {"a": 1, "b": 1, "c": 1}), [])


class TestPublishScreen(unittest.TestCase):

    def test_publishes_options_without_coordinates(self):
        ctx = {"ui": UiState()}
        snap = screen.read_screen(GRE_XML)

        app.publish_screen(ctx, snap, "预读", age=1.2)

        view = ctx["ui"].current_screen()
        self.assertEqual(view.prompt, "degrade")
        self.assertEqual([o.index for o in view.options], [1, 2, 3, 4, 5])
        self.assertEqual(view.options[0].text, "adj. 清晰易懂的")
        self.assertFalse(hasattr(view.options[0], "y"), "界面不显示坐标")
        self.assertEqual(view.source, "预读")
        self.assertAlmostEqual(view.age_seconds, 1.2)

    def test_noop_without_ui(self):
        app.publish_screen({"ui": None}, screen.read_screen(GRE_XML), "预读")


class TestScreenPublisher(unittest.TestCase):
    """
    `make_screen_publisher` —— 把「程序手里那一屏」播给界面**和控制台**。

    这是本轮修缺陷时新加的接线（用户实测报告：控制台和界面都不显示预读的内容，
    只有点击后才显示上一屏，永远慢一拍）。挂到预读器上之后，`note()` 每次存下
    一份新屏就播一次，于是**预读在后台读好的新题会自己出现在界面和控制台里**。

    控制台那一半是用户点名要的：他得一眼看出「这屏是预读的，不是当前点击用的」。
    所以除了界面，还得有一行标明来源，加上题干、选项那两行。
    """

    def test_publishes_to_the_ui_and_prints_the_source(self):
        ctx = {"ui": UiState()}
        publisher = app.make_screen_publisher(ctx)
        snap = screen.read_screen(GRE_XML)

        with mock.patch("builtins.print") as printed:
            publisher(snap, "预读", 1.5)

        view = ctx["ui"].current_screen()
        self.assertIsNotNone(view, "界面第二块要拿到这一屏")
        self.assertEqual(view.source, "预读")
        self.assertEqual(view.prompt, "degrade")
        self.assertAlmostEqual(view.age_seconds, 1.5, places=3)

        out = "\n".join(str(c.args[0]) for c in printed.call_args_list if c.args)
        self.assertIn("预读", out, "控制台要有一行标明这屏是怎么来的")
        self.assertIn("[屏幕] 题干：degrade", out)
        self.assertIn("[屏幕] 选项：", out)

    def test_works_without_ui(self):
        """没开界面时，控制台那条路照走（「不带 --gui 只是多打两行」）"""
        publisher = app.make_screen_publisher({})

        with mock.patch("builtins.print") as printed:
            publisher(screen.read_screen(GRE_XML), "当场读屏", 0.2)

        out = "\n".join(str(c.args[0]) for c in printed.call_args_list if c.args)
        self.assertIn("当场读屏", out)


class TestNoteInput(unittest.TestCase):

    def test_records(self):
        ctx = {"ui": UiState()}
        app.note_input(ctx, "numpad", "3", outcome="点了第 3 个")
        events = ctx["ui"].recent_inputs()
        self.assertEqual(events[0].label, "3")
        self.assertEqual(events[0].outcome, "点了第 3 个")

    def test_noop_without_ui(self):
        app.note_input({"ui": None}, "numpad", "3")


class TestUiStateWiring(unittest.TestCase):
    """
    「把数据交给界面」这条**接线**本身必须被测到 —— 不能只测那两个纯函数。

    由来（和 TestActionWiring 是同一类问题，台账里这是第四次栽在它上面）：
    `publish_screen` / `note_input` 两个纯函数本身有测试（见 TestPublishScreen /
    TestNoteInput），但它们**被调用**的那几处 —— grab_screen 里的 publish_screen、
    do_click 里的两处 note_input、handle_numpad 与 handle_speech 里各一处 ——
    原本零覆盖。把这些调用点**全部删掉**，275 个用例照样全绿，
    而真机上界面会永远空着（谁把接线接错也没人拦得住）。

    （2026-09-28：当场读屏那一处 `publish_screen` 挪进了 `note()` 的播报里，
    所以 grab_screen 现在只剩「用缓存」那一档还直接调 publish_screen ——
    那一档不经过 note()，播报管不到它。两档各有一条用例。）

    所以这里钉的不是「纯函数会不会算」，而是「主流程有没有真的把线接上」：
    每一条断言都对应一个具体的调用点，把那一处调用删掉它就必须变红。
    """

    def _ctx(self, xml=GRE_XML):
        """带真 UiState 的 ctx。关掉 settle，免得每条用例白等 0.3 秒。"""
        ctx, fake = make_ctx(xml, ui=UiState())
        ctx["cfg"].click.settle_ms = 0
        return ctx, fake

    def _recent_outcomes(self, ctx):
        return [e.outcome for e in ctx["ui"].recent_inputs()]

    # ------------------------------------------------ grab_screen → 界面

    def test_grab_screen_hands_the_fresh_read_screen_to_the_ui(self):
        """当场读屏那条路：读到的这一屏要交给 UiState"""
        ctx, _fake = self._ctx()

        snap, _source = app.grab_screen(ctx)

        view = ctx["ui"].current_screen()
        self.assertIsNotNone(view, "抓屏之后界面必须拿到「手里那一屏」")
        self.assertEqual(view.prompt, snap.prompt, "题干要对得上")
        self.assertEqual([o.text for o in view.options],
                         [n.text for n in snap.options], "选项文字要对得上")
        self.assertEqual([o.index for o in view.options], [1, 2, 3, 4, 5])

    def test_grab_screen_hands_the_prefetched_screen_to_the_ui(self):
        """用预读结果那条路**同样**要交给 UiState（两处调用点各钉一条）"""
        ctx, fake = self._ctx()
        ctx["prefetcher"].cached = (screen.read_screen(GRE_XML), 0.5)

        app.grab_screen(ctx)

        view = ctx["ui"].current_screen()
        self.assertIsNotNone(view, "用预读结果时也要把界面交给 UiState")
        self.assertEqual(view.source, "预读")
        self.assertEqual(len(view.options), 5)
        self.assertEqual(fake.dump_calls, 0, "有预读就不该再读屏（先确认真走了预读那条路）")

    def test_grab_screen_publishes_the_fresh_read_only_once(self):
        """
        当场读屏那条路只许往界面写**一次**。

        这一屏原来有两个来源会写：`note()` 播一次（新增的），以及 grab_screen
        自己紧跟一句 `publish_screen`（老代码）。两处都在的话界面结果看起来一样，
        只有次数看得出来 —— 而控制台上就是同一屏白白多打了一遍。
        """
        ctx, _fake = make_ctx(GRE_XML, ui=CountingUiState())

        app.grab_screen(ctx)

        self.assertEqual(ctx["ui"].set_calls, 1, "同一屏只该播一遍")

    # -------------------------------------------- 点击后留下「我的输入」

    def test_numpad_click_leaves_an_input_record(self):
        """小键盘点完，界面第三块要有一条「我的输入」，且看得出点了第几个"""
        ctx, fake = self._ctx()

        app.handle_numpad(1, ctx)

        self.assertEqual(len(fake.taps), 1, "先确认真的点了")
        events = ctx["ui"].recent_inputs()
        self.assertTrue(events, "点完之后界面要能看见「我的输入」")
        self.assertEqual(events[0].kind, "numpad")
        self.assertEqual(events[0].label, "1")
        self.assertIn("第 1 个", events[0].outcome, "结果里要看得出点了第几个")

    def test_debounced_click_is_recorded_as_skipped(self):
        """被防连点挡掉的那一下，界面也要有个交代 —— 别记成「点了」"""
        ctx, _fake = self._ctx()

        app.handle_speech("清晰", -0.4, ctx)     # 这一下真的点了
        app.handle_speech("阴郁", -0.4, ctx)     # 这一下被防连点挡掉

        outcomes = self._recent_outcomes(ctx)
        self.assertTrue(any("已跳过" in o for o in outcomes),
                        f"被挡掉的那一下要记成「已跳过」，实际记的是 {outcomes!r}")

    def test_press_still_clicks_after_the_screen_turned(self):
        """
        按下那一刻是第一题，轮到执行时界面已经翻到下一题 —— 这一下照样点。

        这正是 2026-09-28 取消动作时戳要保住的行为：那套时戳拿「按下时的屏幕」
        跟「执行时的屏幕」比，不一样就吞掉，结果误伤了大量正常按键
        （真机数据与理由是 test_pipeline.py 里那段注释）。这条走的是**真接线**：
        按键 → 入队 → 翻页 → 出队执行 —— 谁要是又把「比一比、不一样就吞」
        加回来，它会立刻变红。
        """
        cfg = Config()
        cfg.prefetch.after_click = False     # 别让后台预读来搅乱
        cfg.click.settle_ms = 0
        fake = FakeAdb(GRE_XML)
        pref = app.ScreenPrefetcher(fake, cfg, log=lambda *_: None)
        pref.note(screen.read_screen(GRE_XML))
        ctx = {
            "adb": fake,
            "cfg": cfg,
            "preview": False,
            "recognizer": StubRecognizer(),
            "prefetcher": pref,
            "voice_gate": StubVoiceGate(),
            "clicker": Clicker(fake, cfg.click, log=lambda *_: None),
            "ui": UiState(),
        }
        q = RecordingQueue()

        # 用户按下 1（此刻屏幕上还是第一题），动作进了队列
        app.make_action_putters(q, pref)["on_option"](1)
        # 还没轮到执行，界面就翻了页（用户接着在答下一题）
        pref.note(screen.read_screen(SECOND_XML))
        fake.xml = SECOND_XML

        for action in q.items:                 # 工作线程把队列里的动作取出来执行
            app.dispatch_action(action, ctx)

        self.assertEqual(len(fake.taps), 1, "翻页之后轮到执行，这一下也要生效，不能吞")
        outcomes = self._recent_outcomes(ctx)
        self.assertTrue(any("第 1 个" in o for o in outcomes),
                        f"这一下要如实记成点了第 1 个，实际记的是 {outcomes!r}")
        self.assertFalse(any("已忽略" in o for o in outcomes),
                         f"不该再有「已忽略」这种出路，实际记的是 {outcomes!r}")

    # ------------------------------------------- 语音留下「听到了什么」

    def test_speech_records_what_was_heard(self):
        """语音路径要把「听到了什么」记进界面第三块"""
        ctx, _fake = self._ctx()

        app.handle_speech("清晰", -0.4, ctx)

        heard = [e for e in ctx["ui"].recent_inputs() if e.label == "清晰"]
        self.assertTrue(heard, "语音路径要记下「听到了什么」")

    def test_heard_record_does_not_promise_a_followup(self):
        """
        开头那条「听到了什么」的 outcome 必须**留空**。

        它曾经写的是「（见下）」—— 意思是结果在下面。可匹配失败、读屏失败、
        走「下一题」这些分支都不会有后续点击，界面上于是永久留着一条没有下文的
        「见下」，比什么都不说更误导。改完之后这一条只如实显示听到了什么。
        """
        ctx, _fake = self._ctx()

        app.handle_speech("清晰", -0.4, ctx)

        heard = [e for e in ctx["ui"].recent_inputs() if e.label == "清晰"]
        self.assertTrue(heard, "先确认「听到了什么」那条真的记了")
        self.assertEqual(heard[0].outcome, "",
                         "「听到了什么」那条不该预告一个可能不存在的下文")

    def test_unmatched_speech_records_a_clear_outcome(self):
        """没匹配上时补一条说明白的 —— 界面不能只留一句「听到了什么」就没了"""
        ctx, fake = self._ctx()

        app.handle_speech("香蕉苹果橘子", -0.4, ctx)

        self.assertEqual(fake.taps, [], "匹配不上不该点击")
        events = ctx["ui"].recent_inputs()
        self.assertEqual(len(events), 2, "「听到的」和「没匹配上」各一条")
        self.assertIn("没匹配上", events[0].outcome)

    def test_unmatched_ordinal_says_what_actually_went_wrong(self):
        """
        说了超范围的序号 —— 要说清是序号超了，不能笼统说「屏幕上没有这个词」。

        注意：`voice.commands` 默认关（说序号那条路整个不走，也就无所谓
        「超范围」）。这里验的是**开着时**的报错文案，所以先把它打开。
        """
        ctx, fake = self._ctx()
        ctx["cfg"].voice.commands = True

        app.handle_speech("第七个", -0.4, ctx)

        self.assertEqual(fake.taps, [])
        events = ctx["ui"].recent_inputs()
        self.assertIn("没匹配上", events[0].outcome)
        self.assertIn("5 个选项", events[0].outcome,
                      "要说清屏幕上到底有几个选项，别笼统说「没有这个词」")


class TestPrefetchedScreenReachesTheUiWithNoExtraKey(unittest.TestCase):
    """
    **本轮缺陷的主证据**（用户实测报告）：

        控制台和可视化界面都不会显示预读的内容，只有点击后才显示之前的屏幕读屏，
        这样完全滞后，没有意义。

    真正的病根不在「读得慢」，而在「读到了却不说」：预读在后台把新题读好之后只调了
    `note()` 存进缓存（`voice_tap/main.py` 里 `trigger_after_click` 内），**没有播出去**。
    于是用户点完之后的那几秒（**正是他要用界面核对「读屏读对了没有」的时间**）
    界面和控制台显示的都还是上一题；等他按下键，界面才跳到当前题 ——
    而那时他已经点完了。永远慢一拍。

    这条用例走**真接线**：真 `ScreenPrefetcher`（按 main() 的接法挂上
    `make_screen_publisher`）+ 可控的假 adb。**只按一次键，然后什么都不做**，
    界面里那一屏就必须自己变成新题 —— 靠的就是预读读完会播出来。

    改坏看红：把 `note()` 里那次回调调用去掉，界面会永远停在点击前那一屏（"degrade"），
    这条等待超时、变红。
    """

    def test_one_keypress_is_enough_for_the_new_question_to_show_up(self):
        ctx, fake, prefetcher = make_prefetch_ctx(
            SECOND_XML,                                  # 翻页之后读到的是这一屏
            ui=UiState(),
            click_delay_ms=1, click_retry_ms=1,          # 测试里别真等 300 毫秒
        )
        ctx["cfg"].click.settle_ms = 0
        # 程序手里现在是第一题（启动时读到的那一屏）
        prefetcher.note(screen.read_screen(GRE_XML), source="启动时读到的")
        self.assertEqual(ctx["ui"].current_screen().prompt, "degrade",
                         "先确认界面上现在确实是第一题")

        app.handle_numpad(1, ctx)                        # 用户按了一次 1

        self.assertEqual(len(fake.taps), 1, "先确认这一下真的点了")
        # **不用再按键**：预读读完新题会自己播出来
        self.assertTrue(
            wait_for(lambda: (ctx["ui"].current_screen() is not None
                              and ctx["ui"].current_screen().prompt == "prototype")),
            "预读读到的**新题**应该自己出现在界面上（不用再按键），"
            f"界面里现在还是 {ctx['ui'].current_screen()!r}")
        view = ctx["ui"].current_screen()
        self.assertEqual(view.source, "预读", "来源要如实标成「预读」")
        self.assertEqual([o.text for o in view.options],
                         [n.text for n in screen.read_screen(SECOND_XML).options],
                         "播出来的得是新题的选项，不是上一题的")


class TestUiWiringWithoutUi(unittest.TestCase):
    """
    没开界面（ctx 里没有 ui，或 ui 为 None）时一切照旧 —— 「不带 --gui 行为不变」。

    `publish_screen` / `note_input` 都以 `ctx.get("ui") is None` 当空操作。
    这几条钉住那个空操作分支真的在：写成 `ctx["ui"].set_screen(...)` 就会在这里炸。
    """

    def _ctx(self, xml=GRE_XML):
        ctx, fake = make_ctx(xml)            # 故意不带 ui
        ctx["cfg"].click.settle_ms = 0
        return ctx, fake

    def test_grab_screen_is_harmless_without_ui(self):
        ctx, fake = self._ctx()
        app.grab_screen(ctx)                 # 不该抛异常
        self.assertEqual(fake.taps, [])

    def test_speech_path_still_clicks_without_ui(self):
        ctx, fake = self._ctx()
        app.handle_speech("清晰", -0.4, ctx)
        self.assertEqual(len(fake.taps), 1, "不带界面时点击行为必须一模一样")

    def test_numpad_path_still_clicks_without_ui(self):
        ctx, fake = self._ctx()
        app.handle_numpad(2, ctx)
        self.assertEqual(len(fake.taps), 1)

    def test_explicit_none_ui_is_also_safe(self):
        """`ui=None`（键在、值为 None）和「没这个键」都得是空操作"""
        ctx, fake = self._ctx()
        ctx["ui"] = None

        app.handle_speech("清晰", -0.4, ctx)

        self.assertEqual(len(fake.taps), 1)


class TestWindowGeometry(unittest.TestCase):
    """
    「关窗存位置、下次接着用」那两个工具函数。

    它们是模块级函数、能单测，而这条承诺（设计文档 §1.4）此前一个测试都没有。

    要点是**坏文件必须退回 fallback，不能抛异常** —— 存档坏了（手改坏了、
    版本对不上、权限问题）不该把程序拦在门外，大不了用回默认位置。
    """

    def setUp(self):
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        self.path = self.dir / "gui_window.txt"

    def test_save_then_load_round_trips(self):
        """存了再读，拿回来是同一组四个整数"""
        geometry = (120, 240, 640, 480)

        app._save_window_geometry(self.path, geometry)

        self.assertEqual(app._load_window_geometry(self.path, (0, 0, 1, 1)),
                         geometry)

    def test_missing_file_returns_fallback(self):
        """文件还不存在（第一次启动）→ 返回 fallback"""
        fallback = (10, 20, 30, 40)

        self.assertEqual(
            app._load_window_geometry(self.dir / "没有这个文件.txt", fallback),
            fallback)

    def test_corrupt_content_returns_fallback_without_raising(self):
        """内容坏掉 → 返回 fallback，**不抛异常**"""
        fallback = (1, 2, 3, 4)
        self.path.write_text("乱写的", encoding="utf-8")

        self.assertEqual(app._load_window_geometry(self.path, fallback), fallback)

    def test_non_numeric_content_returns_fallback(self):
        """四个词、但都不是整数 —— int() 会炸，同样要吞掉退回 fallback"""
        fallback = (5, 6, 7, 8)
        self.path.write_text("一 二 三 四", encoding="utf-8")

        self.assertEqual(app._load_window_geometry(self.path, fallback), fallback)

    def test_save_creates_missing_parent_directory(self):
        """存的时候父目录不存在也能建出来（debug/ 可能被删过）"""
        nested = self.dir / "a" / "b" / "gui_window.txt"

        app._save_window_geometry(nested, (7, 8, 9, 10))

        self.assertTrue(nested.is_file(), "父目录该被建出来，文件该落地")
        self.assertEqual(app._load_window_geometry(nested, None), (7, 8, 9, 10))


if __name__ == "__main__":
    unittest.main(verbosity=2)

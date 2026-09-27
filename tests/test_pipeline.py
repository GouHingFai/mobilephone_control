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
import unittest
from pathlib import Path

from voice_tap import main as app
from voice_tap import screen
from voice_tap.adb import AdbError
from voice_tap.clicker import Clicker
from voice_tap.config import Config

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


# 哨兵：区分「没指定，从 XML 里推断」和「明确要模拟查不到」
INFER_FROM_XML = object()


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

    def __init__(self):
        self.invalidated = 0
        self.after_click_triggers = 0
        self.on_speech_triggers = 0
        self.noted = 0
        self.cached = None      # 测试可以塞一份进去，模拟「已经预读好了」
        self._miss = "还没有预读结果"

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

    def note(self, snap, read_at=None):
        self.noted += 1

    def peek(self):
        """看一眼最近见过的界面（不消费）—— 主循环要拿它当识别的提示词"""
        return None

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


def make_ctx(xml, preview=False):
    cfg = Config()
    fake = FakeAdb(xml)
    ctx = {
        "adb": fake,
        "cfg": cfg,
        "preview": preview,
        "recognizer": StubRecognizer(),
        "prefetcher": StubPrefetcher(),
        "voice_gate": StubVoiceGate(),
        "clicker": Clicker(fake, cfg.click, log=lambda *_: None),
    }
    return ctx, fake


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


class TestActionStamp(unittest.TestCase):
    """
    按键动作要带「按键那一刻的屏幕」的戳；执行前核对，屏幕变了就不点。

    由来（真机上实测到的 bug）：在第一题上连按两下 `1`，
    第一下点完立刻作废缓存并启动后台预读；第二下还在队列里排队，
    等它被处理时预读已经读回了**第二题**，于是照着第二题点了第 1 个。
    根子是：**第一题时做的动作，被用到了第二题上。**
    """

    def _setup(self, xml=GRE_XML):
        cfg = Config()
        cfg.prefetch.after_click = False     # 别让后台预读来搅乱
        cfg.click.settle_ms = 0
        fake = FakeAdb(xml)
        pref = app.ScreenPrefetcher(fake, cfg, log=lambda *_: None)
        pref.note(screen.read_screen(xml))
        ctx = {
            "adb": fake,
            "cfg": cfg,
            "preview": False,
            "recognizer": StubRecognizer(),
            "prefetcher": pref,
            "voice_gate": StubVoiceGate(),
            "clicker": Clicker(fake, cfg.click, log=lambda *_: None),
        }
        return ctx, fake, pref

    def test_identity_is_none_before_any_read(self):
        fake = FakeAdb(GRE_XML)
        pref = app.ScreenPrefetcher(fake, Config(), log=lambda *_: None)
        self.assertIsNone(pref.identity(), "还没读到过任何界面时不该有指纹")

    def test_identity_reflects_last_seen_screen(self):
        _ctx, _fake, pref = self._setup()
        expected = app.ScreenPrefetcher.signature(screen.read_screen(GRE_XML))
        self.assertEqual(pref.identity(), expected)

    def test_dropped_when_screen_changed_since_press(self):
        """按键时是第一题，轮到执行时已经翻到第二题 —— 必须不点"""
        ctx, fake, pref = self._setup()
        stamp = pref.identity()                     # 按键那一刻：第一题
        pref.note(screen.read_screen(SECOND_XML))   # 界面翻了页
        fake.xml = SECOND_XML

        app.handle_numpad(1, ctx, stamp=stamp)

        self.assertEqual(fake.taps, [], "界面已经变了，这一下不能点")

    def test_runs_when_screen_unchanged(self):
        """界面没翻（比如那一下没生效）—— 照常点，这正是「按错键马上改」要的"""
        ctx, fake, pref = self._setup()
        stamp = pref.identity()

        app.handle_numpad(1, ctx, stamp=stamp)

        self.assertEqual(len(fake.taps), 1)

    def test_runs_when_no_stamp_given(self):
        """没盖戳（比如语音路径）时不做拦截"""
        ctx, fake, _pref = self._setup()

        app.handle_numpad(1, ctx)

        self.assertEqual(len(fake.taps), 1)


class RecordingQueue:
    """假队列：只把 put 进来的东西记下来，不真的排队"""

    def __init__(self):
        self.items = []

    def put(self, item):
        self.items.append(item)


class TestActionWiring(unittest.TestCase):
    """
    「盖戳 → 入队 → 解包分派」这条接线。

    上一轮只测了后半截「核对时戳」（见 TestActionStamp），
    而把时戳**做出来、送进队列、再从队列里分派出去**这段，原本写在
    main() 的三个 lambda 和一个闭包里，外部调不到 ——
    于是谁把它改坏了（比如忘带戳、把两元组当三元组解、把分派写反），
    227 个测试照样全绿，而真机上「连按两下点到新题」原样复现。

    所以现在这段被抽成 make_action_putters / dispatch_action 两个模块级函数，
    在这里直接钉住它的**可观察后果**（队列里真有那条、真的点了那一下），
    而不是去 monkeypatch 模块级处理函数 —— 那样测到的是桩，不是接线。
    """

    # ---------------------------------------------------------- 盖戳

    def _prefetcher_with(self, xml=GRE_XML):
        """造一个已经「见过一屏」的真 ScreenPrefetcher"""
        cfg = Config()
        fake = FakeAdb(xml)
        pref = app.ScreenPrefetcher(fake, cfg, log=lambda *_: None)
        pref.note(screen.read_screen(xml))
        return pref

    def test_on_option_puts_number_with_the_stamp(self):
        pref = self._prefetcher_with()
        expected = app.ScreenPrefetcher.signature(screen.read_screen(GRE_XML))
        q = RecordingQueue()

        app.make_action_putters(q, pref)["on_option"](3)

        self.assertEqual(q.items, [("numpad", 3, expected)],
                         "点选项要入队三元组 (\"numpad\", 几号, 按键时的屏幕指纹)")

    def test_on_next_puts_next_with_the_stamp(self):
        pref = self._prefetcher_with()
        expected = app.ScreenPrefetcher.signature(screen.read_screen(GRE_XML))
        q = RecordingQueue()

        app.make_action_putters(q, pref)["on_next"]()

        self.assertEqual(q.items, [("next", None, expected)],
                         "「下一题」也要带戳 —— 它一样会点到新界面上")

    def test_on_force_read_has_no_stamp(self):
        """强制读屏跟界面无关，不带戳（带了反而会被误拦）"""
        pref = self._prefetcher_with()
        q = RecordingQueue()

        app.make_action_putters(q, pref)["on_force_read"]()

        self.assertEqual(q.items, [("force_read", None, None)])

    def test_stamp_is_taken_at_press_not_at_execution(self):
        """
        戳必须在**按下那一刻**取。

        这条正是那个真机 bug 的要点：按下的那一屏，和轮到执行时的屏幕，
        中间可能已经翻过页了。戳要是取晚了（比如在工作线程里才取），
        它就会等于「新那一屏」，核对时永远相等，等于没拦。
        """
        pref = self._prefetcher_with()
        pressed = pref.identity()                    # 按下那一刻：第一题
        q = RecordingQueue()
        putters = app.make_action_putters(q, pref)

        putters["on_option"](2)                      # 按下

        pref.note(screen.read_screen(SECOND_XML))     # 按完才翻页

        self.assertEqual(q.items[0], ("numpad", 2, pressed),
                         "戳是按下时的屏幕，事后翻页不该把它改掉")

    def test_stamp_is_none_before_any_screen_read(self):
        """还没读到过任何界面时，戳就是 None —— 别硬编个假的出来"""
        pref = self._prefetcher_with()
        pref._last_seen = None
        q = RecordingQueue()

        app.make_action_putters(q, pref)["on_option"](1)

        self.assertIsNone(q.items[0][2])

    # ---------------------------------------------------------- 解包分派

    def test_dispatch_numpad_really_clicks(self):
        """numpad 动作要走到底、真的点一下第 1 个选项"""
        ctx, fake = make_ctx(GRE_XML)
        ctx["cfg"].click.debounce_ms = 0

        app.dispatch_action(("numpad", 1, None), ctx)

        self.assertEqual(len(fake.taps), 1, "numpad 动作应该真点一下")
        _, y = fake.taps[0]
        self.assertTrue(736 <= y <= 886, f"应该点第 1 个选项，实际 y={y}")

    def test_dispatch_next_clicks_the_next_button(self):
        """next 动作去点「下一题」，而不是被当成点选项"""
        ctx, fake = make_ctx(DETAIL_XML)

        app.dispatch_action(("next", None, None), ctx)

        self.assertEqual(fake.taps, [(600, 2180)],
                         "next 应该点到「下一题」按钮中心")

    def test_dispatch_force_read_reads_and_does_not_click(self):
        """force_read 只重读一次屏，不点任何东西"""
        ctx, fake = make_ctx(GRE_XML)

        app.dispatch_action(("force_read", None, None), ctx)

        self.assertEqual(fake.dump_calls, 1, "强制读屏应该当场读一次")
        self.assertEqual(fake.taps, [], "强制读屏不该顺带点东西")

    def test_dispatch_does_not_swallow_the_stamp(self):
        """
        分派时必须把戳**原样传给** handle_numpad。

        这里让界面在按键后翻了页：戳对不上就该不点。
        要是 dispatch_action 忘了传 stamp（比如写成 handle_numpad(value, ctx)），
        这一下就会照点不误 —— 真机上就是「连按两下点到新题」。
        """
        cfg = Config()
        cfg.prefetch.after_click = False
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
        }
        action = ("numpad", 1, pref.identity())      # 按下时：第一题

        pref.note(screen.read_screen(SECOND_XML))    # 翻到第二题
        fake.xml = SECOND_XML

        app.dispatch_action(action, ctx)

        self.assertEqual(fake.taps, [], "界面已变，这一下不能点 —— 戳必须传到")

    # ---------------------------------------------------------- 坏格式不崩

    def test_malformed_action_is_ignored_silently(self):
        """
        格式不对的条目一律忽略：不抛异常，也不产生点击。

        这是工作线程的最后一道关口 —— 半截元组、None、一个数字之类的东西
        不该把线程掀翻，更不该冒出一个「点一下」的副作用。
        """
        bad_actions = [
            3,                      # 根本不是可迭代对象
            None,
            ("numpad",),            # 太短
            ("numpad", 1),          # 少了戳
            ("numpad", 1, None, 2), # 太长
            (),
            "numpad",               # 字符串（会被逐字符拆开，但长度也不对）
            "abc",                  # 长度 3 的字符串：解出来 kind 认不出，也不该点
            "abcdef",
        ]

        for bad in bad_actions:
            with self.subTest(bad=bad):
                ctx, fake = make_ctx(GRE_XML)
                app.dispatch_action(bad, ctx)        # 不该抛异常
                self.assertEqual(fake.taps, [], f"{bad!r} 不该点任何东西")

    def test_unknown_kind_is_ignored(self):
        """将来加了 kind 而分支没跟上时，宁可什么都不做，也不能乱点"""
        ctx, fake = make_ctx(GRE_XML)

        app.dispatch_action(("nonsense", 1, None), ctx)

        self.assertEqual(fake.taps, [])


class TestVoiceNextCommand(unittest.TestCase):
    """说「下一题」= 点下一题（直给：不读屏校验）"""

    def _ctx(self, xml):
        ctx, fake = make_ctx(xml)
        ctx["cfg"].hotkey.fixed_next_position = (909, 2476)
        return ctx, fake

    def test_saying_next_clicks_the_button(self):
        ctx, fake = self._ctx(DETAIL_XML)

        app.handle_speech("下一题", -0.4, ctx)

        self.assertEqual(fake.taps, [(909, 2476)])
        self.assertEqual(fake.dump_calls, 0, "固定坐标不该读屏")

    def test_works_on_quiz_page_too(self):
        """直给：答题页上说了照样点（用户明确接受这个取舍）"""
        ctx, fake = self._ctx(GRE_XML)

        app.handle_speech("下一题", -0.4, ctx)

        self.assertEqual(fake.taps, [(909, 2476)])

    def test_disabled_by_config(self):
        ctx, fake = self._ctx(DETAIL_XML)
        ctx["cfg"].voice.next_command = False

        app.handle_speech("下一题", -0.4, ctx)

        self.assertEqual(fake.taps, [], "关掉之后不该点；应落回普通匹配并提示详情页")


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

    def __init__(self, utterances=None):
        self.utterances = list(utterances or [])
        self.calls = []          # [("listen_once", kwargs) | ("listen_pressed", kwargs)]
        self.held_events = []    # listen_pressed 收到的第一个实参（「正在按住」那个事件）

    def listen_once(self, **kwargs):
        self.calls.append(("listen_once", kwargs))
        return self.utterances.pop(0) if self.utterances else None

    def listen_pressed(self, held_event, **kwargs):
        self.calls.append(("listen_pressed", kwargs))
        self.held_events.append(held_event)
        return self.utterances.pop(0) if self.utterances else None


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
        """读屏失败（比如手机掉了）—— 记下来，循环照常转，不崩"""
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


class TestToggleFlag(unittest.TestCase):
    """界面上那两个没有对应热键的开关（预读、语音下一题）"""

    def test_flips_and_flips_back(self):
        ctx = {"cfg": Config()}

        app._toggle_flag(ctx, "prefetch", "after_click", "点击后预读")
        self.assertFalse(ctx["cfg"].prefetch.after_click)

        app._toggle_flag(ctx, "prefetch", "after_click", "点击后预读")
        self.assertTrue(ctx["cfg"].prefetch.after_click)

    def test_works_on_voice_next(self):
        ctx = {"cfg": Config()}
        app._toggle_flag(ctx, "voice", "next_command", "语音说「下一题」")
        self.assertFalse(ctx["cfg"].voice.next_command)


class TestAnyEvent(unittest.TestCase):

    def test_true_if_any_set(self):
        a, b = threading.Event(), threading.Event()
        any_event = app._AnyEvent(a, b)
        self.assertFalse(any_event.is_set())
        b.set()
        self.assertTrue(any_event.is_set())


if __name__ == "__main__":
    unittest.main(verbosity=2)

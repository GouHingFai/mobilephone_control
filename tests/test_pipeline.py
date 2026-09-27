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
import unittest
from pathlib import Path

from voice_tap import main as app
from voice_tap import screen
from voice_tap.adb import AdbError
from voice_tap.clicker import Clicker
from voice_tap.config import Config

FIXTURES = Path(__file__).resolve().parent / "fixtures"

GRE_XML = (FIXTURES / "gre_degrade.xml").read_text(encoding="utf-8")

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


if __name__ == "__main__":
    unittest.main(verbosity=2)

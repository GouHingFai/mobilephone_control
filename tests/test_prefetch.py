#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_prefetch.py —— 预读界面

预读做的是「点击之后趁翻页的空档，先把下一个界面读好」。它省掉的是
整条链路上最慢的一环，所以值得测细。

这里最要紧的一条是这个模块存在的理由：

    **不能等一个固定时间就认为翻页完成了。** 读得太早拿到的还是上一题的
    界面，然后就会拿着旧坐标去点新题目 —— 点了、不报错、但点错了地方。
    这正是之前「固定坐标」方案栽的跟头。

    所以核心机制是「读到和点击前不一样了才算数」。下面的测试把这条钉住。
"""

import threading
import time
import unittest
from pathlib import Path

from voice_tap import main as app
from voice_tap import screen
from voice_tap.config import Config, PrefetchConfig

FIXTURES = Path(__file__).resolve().parent / "fixtures"

FIRST_XML = (FIXTURES / "gre_degrade.xml").read_text(encoding="utf-8")
SECOND_XML = (FIXTURES / "gre_prototype.xml").read_text(encoding="utf-8")


class SequenceAdb:
    """按顺序返回不同的界面 —— 用来模拟「翻页」"""

    def __init__(self, *xmls):
        self.xmls = list(xmls)
        self.calls = 0

    def dump_ui(self, **kwargs):
        self.calls += 1
        index = min(self.calls - 1, len(self.xmls) - 1)
        return self.xmls[index]


class BlockingAdb:
    """
    第二次 `dump_ui()` 会**阻塞**，由测试决定什么时候放行。

    用它把时序钉死。本任务要测的是「预读正卡在第二次读上」这一刻里发生的事情
    （按键取走第一份、或者点击换代）—— 靠 sleep 去凑那一刻，机器一快一慢
    结论就飘了；阻塞住则是确定的，这一刻里发生的事都能被可靠复现。

    `entered_second`：预读已经进到第二次读里了（测试据此知道可以动手了）
    `release`：测试放行，让第二次读返回
    """

    def __init__(self, *xmls):
        self.xmls = list(xmls)
        self.calls = 0
        self.entered_second = threading.Event()
        self.release = threading.Event()

    def dump_ui(self, **kwargs):
        self.calls += 1
        index = min(self.calls - 1, len(self.xmls) - 1)
        if self.calls == 2:
            self.entered_second.set()
            # 超时只是兜底，免得测试写错时把整个套件挂死
            self.release.wait(timeout=5.0)
        return self.xmls[index]


def make_prefetcher(*xmls, **overrides):
    """造一个用极小延时的预读器，让测试跑得快"""
    cfg = Config()
    params = dict(
        after_click=True,
        click_delay_ms=1,
        click_retry_ms=1,
        cache_max_age=8.0,
        on_speech=False,
    )
    params.update(overrides)
    cfg.prefetch = PrefetchConfig(**params)

    logs = []
    adb = SequenceAdb(*xmls) if xmls else SequenceAdb(FIRST_XML)
    prefetcher = app.ScreenPrefetcher(adb, cfg, log=logs.append)
    return prefetcher, adb, logs, cfg


def wait_idle(prefetcher, timeout=5.0):
    """等后台线程干完活"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not prefetcher._busy:
            return True
        time.sleep(0.005)
    return False


def wait_for(predicate, timeout=5.0):
    """等某个条件成立。轮询事件，不靠 sleep 撞运气 —— 条件一成立就往下走。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.005)
    return False


class TestSignature(unittest.TestCase):
    """指纹：判断界面有没有变，全靠它"""

    def test_same_screen_same_signature(self):
        a = app.ScreenPrefetcher.signature(screen.read_screen(FIRST_XML))
        b = app.ScreenPrefetcher.signature(screen.read_screen(FIRST_XML))
        self.assertEqual(a, b)

    def test_different_question_different_signature(self):
        a = app.ScreenPrefetcher.signature(screen.read_screen(FIRST_XML))
        b = app.ScreenPrefetcher.signature(screen.read_screen(SECOND_XML))
        self.assertNotEqual(a, b, "换了题目，指纹必须不同")

    def test_different_app_different_signature(self):
        qq = ("<hierarchy rotation='0'><node text='消息' class='x' "
              "package='com.tencent.mobileqq' bounds='[0,0][10,10]'/></hierarchy>")
        a = app.ScreenPrefetcher.signature(screen.read_screen(FIRST_XML))
        b = app.ScreenPrefetcher.signature(
            screen.read_screen(qq, expected_package=None))
        self.assertNotEqual(a, b)


class TestCache(unittest.TestCase):

    def test_take_when_empty(self):
        prefetcher, _adb, _logs, _cfg = make_prefetcher()
        self.assertIsNone(prefetcher.take())

    def test_note_then_take(self):
        prefetcher, _adb, _logs, _cfg = make_prefetcher()
        snap = screen.read_screen(FIRST_XML)
        prefetcher.note(snap)

        got = prefetcher.take()
        self.assertIsNotNone(got)
        cached, age = got
        self.assertIs(cached, snap)
        self.assertLess(age, 1.0)

    def test_take_does_not_consume(self):
        """
        取用**不清空** —— 同一份界面能被子反复取用。

        这一条也是踩坑之后改的。原来是「取走即清空」，后果是：
            用语音答 → 听错 → 没匹配上 → **那次取用把有效数据烧掉了**
                     → 重说一遍 → 缓存空了 → 只能当场读屏（白等 2.4 秒）
        而重说的时候界面根本没变过（压根没有点击发生），这份数据正是最该留着的。

        过期交给 cache_max_age（和点击后的 invalidate）管，不靠「取走」。
        """
        prefetcher, _adb, _logs, _cfg = make_prefetcher()
        snap = screen.read_screen(FIRST_XML)
        prefetcher.note(snap)

        first = prefetcher.take()
        second = prefetcher.take()

        self.assertIsNotNone(first)
        self.assertIsNotNone(second, "取过一次之后缓存还得在")
        self.assertIs(first[0], snap)
        self.assertIs(second[0], snap, "两次取到的是同一份界面")

    def test_expired_cache_is_dropped(self):
        """过期缓存必须丢弃 —— 界面可能早被你用鼠标翻掉了"""
        prefetcher, _adb, _logs, _cfg = make_prefetcher(cache_max_age=0.05)
        prefetcher.note(screen.read_screen(FIRST_XML))

        time.sleep(0.1)
        self.assertIsNone(prefetcher.take())

    def test_note_ignores_a_read_that_started_earlier(self):
        """
        一次很慢的后台读，返回时不能覆盖掉中间读到的更新数据。

        关键在比较的是「读屏**开始**的时刻」，不是「调用 note 的时刻」——
        慢读的调用时刻反而更晚，按调用时刻比就拦不住了。
        """
        prefetcher, _adb, _logs, _cfg = make_prefetcher()

        newer = screen.read_screen(SECOND_XML)
        prefetcher.note(newer, read_at=time.monotonic())

        # 模拟：这一次读屏是 5 秒前就开始了，只是刚刚才返回
        stale = screen.read_screen(FIRST_XML)
        prefetcher.note(stale, read_at=time.monotonic() - 5.0)

        cached, _age = prefetcher.take()
        self.assertIs(cached, newer, "开始得更早的那次读屏不该覆盖新数据")


class TestInvalidateKeepsSignature(unittest.TestCase):
    """
    作废缓存**不能**把指纹也清掉。

    点击之后立刻要拿指纹和读到的界面比对，判断翻页发生没有。
    指纹代表的是「点击之前长什么样」—— 清掉了就没法比了，
    整个翻页检测就废了。
    """

    def test_signature_survives_invalidate(self):
        prefetcher, _adb, _logs, _cfg = make_prefetcher()
        prefetcher.note(screen.read_screen(FIRST_XML))
        before = prefetcher._signature
        self.assertIsNotNone(before)

        prefetcher.invalidate()

        self.assertIsNone(prefetcher.take(), "缓存该清掉")
        self.assertEqual(prefetcher._signature, before, "指纹必须留着")


class TestMissReason(unittest.TestCase):
    """
    take 落空时要能说清「为什么」—— 是压根没有，还是过期了。

    加这个是为了查一个孤例：日志里有过一次「刚预读成功，紧接着就说没有缓存」，
    24 次里只出现 1 次。那时落空只会打出一句「没有可用的预读结果」，
    分不清是「压根没预读过」还是「预读过但过期了」—— 分不清就无从下手。

    现在把原因记下来，由调用方打进日志。**关键是落空的原因不能被后来那句
    笼统的「还没有」盖掉** —— 否则记了等于没记。
    """

    def test_reason_when_never_prefetched(self):
        prefetcher, _adb, _logs, _cfg = make_prefetcher()
        self.assertIsNone(prefetcher.take())
        self.assertIn("还没有", prefetcher.miss_reason())

    def test_reason_when_expired(self):
        """「过期了」和「压根没有」的区别，必须在日志里看得出来"""
        prefetcher, _adb, _logs, _cfg = make_prefetcher(cache_max_age=0.05)
        prefetcher.note(screen.read_screen(FIRST_XML))
        time.sleep(0.1)

        self.assertIsNone(prefetcher.take())
        self.assertIn("过期", prefetcher.miss_reason())

    def test_reason_when_invalidated(self):
        """点击之后缓存作废 —— 这个更具体的原因不能被「还没有」盖掉"""
        prefetcher, _adb, _logs, _cfg = make_prefetcher()
        prefetcher.note(screen.read_screen(FIRST_XML))
        prefetcher.invalidate()

        self.assertIsNone(prefetcher.take())
        self.assertIn("作废", prefetcher.miss_reason())

    def test_expiry_reason_survives_repeated_takes(self):
        """反复查同一次落空，原因应该一致 —— 不能被第二次 take 改写"""
        prefetcher, _adb, _logs, _cfg = make_prefetcher(cache_max_age=0.05)
        prefetcher.note(screen.read_screen(FIRST_XML))
        time.sleep(0.1)

        prefetcher.take()
        first = prefetcher.miss_reason()
        prefetcher.take()
        self.assertEqual(prefetcher.miss_reason(), first,
                         "同一次落空的原因不该变来变去")


class TestPeek(unittest.TestCase):
    """
    peek 是给识别用的：看一眼最近见过的界面，不消费。

    识别需要它来（1）判断该按中文还是英文（2）把选项当提示词。
    它必须**不被 take 消费掉**，也必须**扛得过 invalidate** ——
    因为点击之后立刻就会 invalidate，而紧接着识别就要用它。
    """

    def test_returns_none_before_anything_seen(self):
        prefetcher, _adb, _logs, _cfg = make_prefetcher()
        self.assertIsNone(prefetcher.peek())

    def test_returns_last_seen(self):
        prefetcher, _adb, _logs, _cfg = make_prefetcher()
        snap = screen.read_screen(FIRST_XML)
        prefetcher.note(snap)
        self.assertIs(prefetcher.peek(), snap)

    def test_survives_take(self):
        """被取走之后还要留着 —— 识别随时可能要问"""
        prefetcher, _adb, _logs, _cfg = make_prefetcher()
        snap = screen.read_screen(FIRST_XML)
        prefetcher.note(snap)

        prefetcher.take()
        self.assertIs(prefetcher.peek(), snap, "take 不该把 peek 的数据一起清掉")

    def test_survives_invalidate(self):
        """点击之后会立刻作废缓存，但 peek 必须还在 —— 识别紧接着就要用"""
        prefetcher, _adb, _logs, _cfg = make_prefetcher()
        snap = screen.read_screen(FIRST_XML)
        prefetcher.note(snap)

        prefetcher.invalidate()
        self.assertIs(prefetcher.peek(), snap)


class TestPeekWithAge(unittest.TestCase):
    """
    `peek_with_age()`：跟 peek 一样，外加「那一屏是多少秒前读到的」。

    按键那条「不等预读」的路要拿这个年龄写日志 —— 用户要看的是
    「我这一下用的是多少秒前的坐标，冒了多大的险」。

    年龄**必须从那一屏读到的时刻算**，不能拿缓存那一份的 `_at`：
    点击之后 `invalidate()` 会把 `_at` 清零（缓存作废了），而 `_last_seen`
    是故意留着不动的（翻页判断和识别上下文都靠它）。那一刻两者已经不是
    一回事了 —— 用 `_at` 会喊出一个「开机以来」那么大的数（monotonic 从开机算起），
    正是这两条测试要拦住的。

    另外：**年龄没有上限**，这是用户明确要求的「不做时间保险、一律不等」。
    下面最后一条把这件事钉住 —— 它是刻意不要，不是漏了。
    """

    def test_none_before_anything_seen(self):
        prefetcher, _adb, _logs, _cfg = make_prefetcher()
        self.assertIsNone(prefetcher.peek_with_age())

    def test_age_counts_from_when_that_screen_was_read(self):
        prefetcher, _adb, _logs, _cfg = make_prefetcher()
        snap = screen.read_screen(FIRST_XML)
        prefetcher.note(snap, read_at=time.monotonic() - 3.0)

        got = prefetcher.peek_with_age()

        self.assertIsNotNone(got)
        self.assertIs(got[0], snap)
        self.assertAlmostEqual(got[1], 3.0, delta=1.0,
                               msg="年龄要从那一屏读到的时刻算起")

    def test_age_survives_invalidate(self):
        """作废缓存不能把年龄的基准一起清掉（`_at` 会被清零，`_last_seen_at` 不会）"""
        prefetcher, _adb, _logs, _cfg = make_prefetcher()
        snap = screen.read_screen(FIRST_XML)
        prefetcher.note(snap, read_at=time.monotonic() - 2.0)

        prefetcher.invalidate()

        got = prefetcher.peek_with_age()
        self.assertIs(got[0], snap)
        self.assertAlmostEqual(
            got[1], 2.0, delta=1.0,
            msg="作废之后年龄仍应从那一屏读到的时刻算，不能变成「开机以来」")

    def test_no_age_limit_by_design(self):
        """
        **刻意没有年龄上限** —— 用户要求「一律不等、不问这一屏是不是太旧了」。

        所以哪怕这一屏早就超过 `cache_max_age`（缓存那一份已经过期、take() 取不到了），
        peek_with_age() 照样把它交出来，只把年龄如实报出来。这是取舍，不是 bug。
        """
        prefetcher, _adb, _logs, _cfg = make_prefetcher()
        snap = screen.read_screen(FIRST_XML)
        prefetcher.note(snap, read_at=time.monotonic() - 60.0)

        self.assertIsNone(prefetcher.take(), "这一份早就超过 cache_max_age 了")
        got = prefetcher.peek_with_age()
        self.assertIs(got[0], snap, "按键那条路要的是「有旧坐标能用」，不是「够不够新」")
        self.assertGreater(got[1], 30.0, "年龄要如实报出来，用户得知道自己冒了多大的险")


class TestTriggerAfterClick(unittest.TestCase):

    def test_reads_until_screen_changes(self):
        """第一次读到旧界面，第二次（那次确认读）读到新的 —— 应该取新的那份"""
        prefetcher, adb, logs, _cfg = make_prefetcher(FIRST_XML, SECOND_XML)

        prefetcher.note(screen.read_screen(FIRST_XML))   # 点击之前看到的
        prefetcher.invalidate()
        prefetcher.trigger_after_click()
        self.assertTrue(wait_idle(prefetcher))

        cached = prefetcher.take()
        self.assertIsNotNone(cached, "应该读到新界面并存下来")
        snap, _age = cached
        self.assertEqual(snap.prompt, "prototype", "存下来的应该是新题目的界面")
        self.assertEqual(adb.calls, 2, "第一次是旧界面，确认读一次就够了")

    def test_never_changes_still_stores_after_two_reads(self):
        """
        界面一直没变（比如点完根本不翻页）—— 读两次就收下，不无限重试。

        用户的原话：连续两次读到的内容一样，就说明这就是当前屏幕。
        而现在的「读到的还和点击前一样就再读一次」，最多 4 次、白耗十秒，
        期间他的按键全被挡住。
        """
        prefetcher, adb, logs, _cfg = make_prefetcher(FIRST_XML, click_retry_ms=1)

        prefetcher.note(screen.read_screen(FIRST_XML))
        prefetcher.invalidate()
        prefetcher.trigger_after_click()
        self.assertTrue(wait_idle(prefetcher))

        self.assertEqual(adb.calls, 2, "最多读两次，不该有第 3、4 次")
        self.assertIsNotNone(prefetcher.take(), "第二次读到的就是当前屏，要收下")
        self.assertTrue(any("两次" in line or "确认" in line for line in logs))

    def test_reads_once_when_screen_changed(self):
        """读到新界面时只读一次 —— 不再多读一遍去「确认」"""
        prefetcher, adb, _logs, _cfg = make_prefetcher(SECOND_XML)

        prefetcher.note(screen.read_screen(FIRST_XML))
        prefetcher.invalidate()
        prefetcher.trigger_after_click()
        self.assertTrue(wait_idle(prefetcher))

        self.assertEqual(adb.calls, 1, "第一次就读到新界面就不该再读")

    def test_first_read_accepted_when_no_baseline(self):
        """还没有任何指纹时（比如刚启动），第一次读到就直接用"""
        prefetcher, _adb, _logs, _cfg = make_prefetcher(FIRST_XML)

        prefetcher.trigger_after_click()
        self.assertTrue(wait_idle(prefetcher))

        self.assertIsNotNone(prefetcher.take(), "没有基准时第一次读到就算数")

    def test_disabled_by_config(self):
        prefetcher, adb, _logs, _cfg = make_prefetcher(FIRST_XML, after_click=False)

        prefetcher.trigger_after_click()
        time.sleep(0.05)

        self.assertEqual(adb.calls, 0, "关掉之后一次都不该读")
        self.assertIsNone(prefetcher.take())

    def test_logs_include_timing(self):
        """日志里要能看出「读到新界面、还是又读一次确认了，以及距点击多久」——
        这是调等待时长的依据（预读最多两次，没有「第 3、4 次」了）"""
        prefetcher, _adb, logs, _cfg = make_prefetcher(FIRST_XML, SECOND_XML)

        prefetcher.note(screen.read_screen(FIRST_XML))
        prefetcher.invalidate()
        prefetcher.trigger_after_click()
        self.assertTrue(wait_idle(prefetcher))

        joined = "\n".join(logs)
        self.assertIn("预读", joined)
        self.assertIn("距点击", joined)
        self.assertIn("读屏", joined)

    def test_does_not_run_twice_concurrently(self):
        prefetcher, adb, _logs, _cfg = make_prefetcher(FIRST_XML, SECOND_XML)

        prefetcher.trigger_after_click()
        prefetcher.trigger_after_click()      # 第二次应该被挡掉
        self.assertTrue(wait_idle(prefetcher))
        time.sleep(0.05)

        # 因为第二次被挡掉，总共只该读 1 次
        self.assertEqual(adb.calls, 1)


class TestFirstReadIsUsableWhileConfirming(unittest.TestCase):
    """
    预读卡在「确认」那一次读上时，等在它上面的按键要能用**第一次**读到的结果。

    这是本轮改动的目的：按键不必再陪预读跑完第二次读（每次读屏约 2.4 秒，
    加上 retry 等待最长能拖到 5 秒）。物理下限是「最多等一次读屏」≈2.4 秒，
    这次就是把它压到这个下限。

    用户的原话：连续两次读到同一屏，就说明这就是当前屏幕 ——
    第一份本来就是有效数据，没有理由压着不给等着的按键用。

    两条用例都靠 `BlockingAdb` 把「第二次读还在路上」这一刻钉死，
    不靠 sleep 去凑。
    """

    def make_blocking(self, *xmls, **overrides):
        cfg = Config()
        params = dict(
            after_click=True,
            click_delay_ms=1,
            click_retry_ms=1,
            cache_max_age=8.0,
            on_speech=False,
        )
        params.update(overrides)
        cfg.prefetch = PrefetchConfig(**params)

        logs = []
        adb = BlockingAdb(*xmls)
        return app.ScreenPrefetcher(adb, cfg, log=logs.append), adb, logs

    def test_first_read_is_usable_while_confirming(self):
        """界面一直不变、预读卡在第二次读上时，take() 应该能拿到第一次读到的那一屏"""
        prefetcher, adb, _logs = self.make_blocking(FIRST_XML, FIRST_XML)

        prefetcher.note(screen.read_screen(FIRST_XML))   # 点击之前看到的
        prefetcher.invalidate()
        prefetcher.trigger_after_click()

        self.assertTrue(wait_for(lambda: adb.entered_second.is_set()),
                        "预读应该已经进到第二次读里（否则这条用例没测到点上）")
        try:
            got = prefetcher.take()
            self.assertIsNotNone(
                got, "第一次读到的就是当前屏，不该压着不给等着的按键用")
            snap, _age = got
            self.assertEqual(snap.prompt, "degrade",
                             "取到的应该是第一次读到的那一屏")
        finally:
            adb.release.set()
        self.assertTrue(wait_idle(prefetcher))

    def test_confirm_read_is_discarded_if_a_click_happened(self):
        """
        第二次读还在路上时按下键 → 点击 → invalidate()（作废即换代）。
        等第二次读返回，它带回来的是**点击前那一屏** —— 必须作废、不许写回缓存。

        写回去的后果正是本项目最忌讳的「静默点错」：下一次按键拿着过期坐标
        点下去，不报错、但点的是错的地方。
        """
        prefetcher, adb, logs = self.make_blocking(FIRST_XML, SECOND_XML)

        prefetcher.note(screen.read_screen(FIRST_XML))
        prefetcher.invalidate()
        prefetcher.trigger_after_click()

        self.assertTrue(wait_for(lambda: adb.entered_second.is_set()),
                        "预读应该已经进到第二次读里")

        # 模拟：用户按键抢走第一份 → 立刻点击 → do_click 作废缓存
        prefetcher.invalidate()

        adb.release.set()
        self.assertTrue(wait_idle(prefetcher))

        self.assertIsNone(
            prefetcher.take(), "换代之后第二次读到的旧屏绝不许写回缓存")
        self.assertTrue(any("作废" in line for line in logs),
                        "这次预读被作废，日志里要说明白")


class TestTriggerOnSpeech(unittest.TestCase):

    def test_disabled_by_default(self):
        prefetcher, adb, _logs, _cfg = make_prefetcher(FIRST_XML)

        prefetcher.trigger_on_speech()
        time.sleep(0.05)

        self.assertEqual(adb.calls, 0, "默认关着，不该读屏")

    def test_enabled_stores_screen(self):
        prefetcher, adb, _logs, _cfg = make_prefetcher(FIRST_XML, on_speech=True)

        prefetcher.trigger_on_speech()
        self.assertTrue(wait_idle(prefetcher))

        self.assertEqual(adb.calls, 1)
        self.assertIsNotNone(prefetcher.take())

    def test_read_failure_does_not_crash(self):
        class BrokenAdb:
            def dump_ui(self, **kwargs):
                raise RuntimeError("假装读屏失败")

        cfg = Config()
        cfg.prefetch = PrefetchConfig(on_speech=True)
        prefetcher = app.ScreenPrefetcher(BrokenAdb(), cfg, log=lambda *_: None)

        prefetcher.trigger_on_speech()
        self.assertTrue(wait_idle(prefetcher), "读失败也要正常收尾，不能卡住")
        self.assertIsNone(prefetcher.take())


if __name__ == "__main__":
    unittest.main(verbosity=2)

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


def make_prefetcher(*xmls, **overrides):
    """造一个用极小延时的预读器，让测试跑得快"""
    cfg = Config()
    params = dict(
        after_click=True,
        click_delay_ms=1,
        click_retry_ms=1,
        click_max_attempts=3,
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


class TestTriggerAfterClick(unittest.TestCase):

    def test_reads_until_screen_changes(self):
        """第一次读到旧界面，第二次读到新的 —— 应该取新的那份"""
        prefetcher, adb, logs, _cfg = make_prefetcher(FIRST_XML, FIRST_XML, SECOND_XML)

        prefetcher.note(screen.read_screen(FIRST_XML))   # 点击之前看到的
        prefetcher.invalidate()
        prefetcher.trigger_after_click()
        self.assertTrue(wait_idle(prefetcher))

        cached = prefetcher.take()
        self.assertIsNotNone(cached, "应该读到新界面并存下来")
        snap, _age = cached
        self.assertEqual(snap.prompt, "prototype", "存下来的应该是新题目的界面")
        self.assertGreaterEqual(adb.calls, 3)

    def test_gives_up_when_screen_never_changes(self):
        """界面一直没变（比如本来就没翻页），试完次数就放弃"""
        prefetcher, adb, logs, _cfg = make_prefetcher(FIRST_XML, click_max_attempts=3)

        prefetcher.note(screen.read_screen(FIRST_XML))
        prefetcher.invalidate()
        prefetcher.trigger_after_click()
        self.assertTrue(wait_idle(prefetcher))

        self.assertIsNone(prefetcher.take(), "没有变化就不该存东西")
        self.assertEqual(adb.calls, 3, "应该试满次数再放弃")
        self.assertTrue(any("放弃" in line for line in logs))

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
        """日志里要能看出「第几次读到新版、距点击多久」—— 这是调等待时长的依据"""
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

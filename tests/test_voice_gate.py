#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_voice_gate.py —— 语音闸门

它存在的理由是踩过坑才发现的：**点完选项之后手机会把那个单词的读音播出来**，
麦克风会收进去。程序误以为用户在说话，送去识别，得到的就是刚答过的那个词。

真机日志里那一串 `'Brooke.'` `'Benevolent'` `'Convey'` `'sinistral'` 全是
手机念的，不是用户说的。而那时界面早翻过去了，什么都匹配不上。

所以点完之后的一段时间内干脆不监听语音。
"""

import threading
import time
import unittest

from voice_tap.config import VoiceConfig
from voice_tap.voice_gate import VoiceGate


def make_gate(mute_ms=200, enabled=True, log=None):
    cfg = VoiceConfig(mute_after_click_ms=mute_ms, enabled=enabled)
    return VoiceGate(cfg, log=log if log is not None else (lambda *_: None))


class TestSuppress(unittest.TestCase):

    def test_not_suppressed_initially(self):
        gate = make_gate()
        self.assertEqual(gate.remaining(), 0.0)

    def test_suppress_sets_a_deadline(self):
        gate = make_gate(mute_ms=300)
        gate.suppress()
        self.assertGreater(gate.remaining(), 0.0)
        self.assertLessEqual(gate.remaining(), 0.3)

    def test_zero_means_no_suppression(self):
        gate = make_gate(mute_ms=0)
        gate.suppress()
        self.assertEqual(gate.remaining(), 0.0)

    def test_suppress_extends_never_shortens(self):
        """连点几下不能把静音期缩短 —— 取更晚的那个截止时间"""
        gate = make_gate(mute_ms=200)
        gate.suppress(1.0)
        first = gate.remaining()

        gate.suppress(0.1)          # 更短的，不该把长的顶掉
        self.assertGreaterEqual(gate.remaining(), first - 0.05)

    def test_disabled_gate_never_suppresses(self):
        gate = make_gate(mute_ms=300, enabled=False)
        gate.suppress()
        self.assertEqual(gate.remaining(), 0.0, "语音关着时静音期没有意义")


class TestWaitUntilOpen(unittest.TestCase):

    def test_returns_immediately_when_open(self):
        gate = make_gate()
        started = time.monotonic()
        waited = gate.wait_until_open()
        self.assertLess(waited, 0.05)
        self.assertLess(time.monotonic() - started, 0.2)

    def test_waits_out_the_suppression(self):
        gate = make_gate(mute_ms=200)
        gate.suppress()

        started = time.monotonic()
        waited = gate.wait_until_open()
        elapsed = time.monotonic() - started

        self.assertGreaterEqual(elapsed, 0.15, "应该确实等了")
        self.assertLess(elapsed, 1.0, "不该等过头")
        self.assertEqual(gate.remaining(), 0.0)

    def test_stop_event_breaks_out(self):
        """退出时不能卡在静音期里"""
        gate = make_gate(mute_ms=5000)
        gate.suppress()

        stop = threading.Event()
        stop.set()
        started = time.monotonic()
        gate.wait_until_open(stop_event=stop)

        self.assertLess(time.monotonic() - started, 0.3, "收到停止信号要立刻返回")

    def test_logs_once_per_suppression(self):
        logs = []
        gate = make_gate(mute_ms=100, log=logs.append)
        gate.suppress()

        gate.wait_until_open()
        gate.wait_until_open()      # 第二次不该重复打印
        gate.wait_until_open()

        self.assertEqual(len(logs), 1, "同一段静音期只该提示一次，不能刷屏")


class TestToggle(unittest.TestCase):

    def test_toggle_off_and_on(self):
        gate = make_gate(enabled=True)
        self.assertTrue(gate.enabled)

        self.assertFalse(gate.toggle())
        self.assertFalse(gate.enabled)

        self.assertTrue(gate.toggle())
        self.assertTrue(gate.enabled)

    def test_toggle_off_clears_effect(self):
        gate = make_gate(mute_ms=5000, enabled=True)
        gate.suppress()
        self.assertGreater(gate.remaining(), 0)

        gate.toggle()               # 关掉
        self.assertEqual(gate.remaining(), 0.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)

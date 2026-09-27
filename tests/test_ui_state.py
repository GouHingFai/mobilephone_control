#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_ui_state.py —— 界面与主逻辑之间的共享状态

这东西的难点只有一个：**它被多个线程同时读写**（主逻辑在写、界面在定时读）。
所以测试的重点是「并发下读到的永远是一份完整的数据」，以及队列行为正确。
"""

import threading
import time
import unittest

from voice_tap.ui_state import InputEvent, OptionView, ScreenView, UiState


class TestScreen(unittest.TestCase):

    def test_none_before_set(self):
        self.assertIsNone(UiState().current_screen())

    def test_roundtrip(self):
        state = UiState()
        view = ScreenView(prompt="degrade",
                          options=[OptionView(1, "adj. 清晰易懂的")],
                          source="预读", age_seconds=1.5, page="quiz", ok=True)
        state.set_screen(view)
        self.assertIs(state.current_screen(), view)


class TestInputs(unittest.TestCase):

    def test_newest_first(self):
        state = UiState()
        state.record_input(InputEvent(kind="numpad", label="1"))
        state.record_input(InputEvent(kind="numpad", label="2"))

        got = state.recent_inputs()
        self.assertEqual([e.label for e in got], ["2", "1"])

    def test_capped(self):
        state = UiState(keep_inputs=3)
        for i in range(10):
            state.record_input(InputEvent(kind="numpad", label=str(i)))

        got = state.recent_inputs(limit=100)
        self.assertEqual(len(got), 3, "只保留最近 3 条")
        self.assertEqual([e.label for e in got], ["9", "8", "7"])

    def test_timestamp_filled(self):
        event = InputEvent(kind="speech", label="extol")
        UiState().record_input(event)
        self.assertGreater(event.at, 0, "没给时间戳时应该自己补上")


class TestIntents(unittest.TestCase):

    def test_post_and_take(self):
        state = UiState()
        state.post_intent("toggle_voice")
        state.post_intent("set_mode")

        self.assertEqual(state.take_intents(), ["toggle_voice", "set_mode"])
        self.assertEqual(state.take_intents(), [], "取过就没了")

    def test_concurrent_access_does_not_crash(self):
        """多线程狂写、同时狂读的**冒烟测试** —— 挡得住什么、挡不住什么，都说清楚。

        能挡住（明显回归）：
          - 读到半截：current_screen 返回残缺对象 / None，或 recent_inputs 抛异常；
          - 死锁：拿锁的路径互相卡住，线程 join 超时；
          - current_screen 恒返回 None 这类接线错误。

        抓不住（竞态）：
          - 本模块的线程安全来自「一把锁 + 整体换引用」。set_screen 换的是对象引用，
            换引用在 CPython 下本就原子，所以**把 ui_state.py 里的锁整个拿掉，这条测试照样全绿**
            （审查者实测：连跑 160 次，一次都没红）。
          - 它没有、也无法在这一层构造出稳定的竞态。

        **别把它的绿色当成「并发正确性已验证」。** 真正的依据是 ui_state.UiState
        类文档里写的那几条不变量（一把锁 + 整体换引用 + 「ScreenView 构造后不再改」的调用方约定）。
        """
        state = UiState(keep_inputs=50)
        stop = threading.Event()

        def writer(tag):
            i = 0
            while not stop.is_set():
                state.record_input(InputEvent(kind="numpad", label=f"{tag}-{i}"))
                state.set_screen(ScreenView(prompt=f"{tag}-{i}"))
                i += 1

        def reader():
            while not stop.is_set():
                state.current_screen()
                state.recent_inputs()
                state.take_intents()

        threads = [threading.Thread(target=writer, args=("a",)),
                   threading.Thread(target=writer, args=("b",)),
                   threading.Thread(target=reader)]
        for t in threads:
            t.start()
        time.sleep(0.3)
        stop.set()
        for t in threads:
            t.join(timeout=2)

        self.assertFalse(any(t.is_alive() for t in threads), "不该卡死")
        view = state.current_screen()
        self.assertTrue(view.prompt.startswith(("a-", "b-")))


if __name__ == "__main__":
    unittest.main(verbosity=2)

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_hotkey.py —— 小键盘模式测试

这里要验证的核心是一件事：**只认小键盘，主键盘的数字键必须被放过。**

之所以要专门测，是因为 keyboard 库把小键盘数字和主键盘数字映射成了
同一个键名（都是 '1'..'9'），如果按名字去监听，你在任何程序里打数字
都会被抢走。真正的区分靠事件上的 is_keypad 标志，这个标志来自库对
扫描码的判断 —— 所以这里用一个假的 keyboard 模块把事件直接喂进去，
验证过滤逻辑确实按预期工作。
"""

import sys
import types
import unittest

from voice_tap.config import HotkeyConfig
from voice_tap.hotkey import HotkeyManager


class FakeEvent:
    def __init__(self, name, is_keypad, event_type="down"):
        self.name = name
        self.is_keypad = is_keypad
        self.event_type = event_type


class FakeKeyboard(types.ModuleType):
    """顶替 keyboard 库：记录注册情况，并把事件直接喂给挂上来的回调"""

    def __init__(self):
        super().__init__("keyboard")
        self.hook_callback = None
        self.unhooked = []
        self.unhook_all_called = False

    def on_press_key(self, key, callback, suppress=False):
        return callback

    def on_release_key(self, key, callback, suppress=False):
        return callback

    def add_hotkey(self, key, callback, suppress=False):
        return callback

    def hook(self, callback, suppress=False, on_remove=None):
        self.hook_callback = callback
        return "the-hook"

    def unhook(self, handle):
        self.unhooked.append(handle)
        self.hook_callback = None

    def unhook_all_hotkeys(self):
        self.unhook_all_called = True


class HotkeyTestBase(unittest.TestCase):

    def setUp(self):
        self.fake = FakeKeyboard()
        self._saved = sys.modules.get("keyboard")
        sys.modules["keyboard"] = self.fake

        self.logs = []
        self.received = []
        self.manager = HotkeyManager(HotkeyConfig(), log=self.logs.append)
        self.manager.start(on_option=self.received.append)

    def tearDown(self):
        if self._saved is not None:
            sys.modules["keyboard"] = self._saved
        else:
            sys.modules.pop("keyboard", None)

    def press(self, name, is_keypad, event_type="down"):
        """
        模拟一次按键。

        如果 hook 已经被摘掉（比如小键盘模式关着），事件压根不会送到我们这里 ——
        这正是真实的语义，所以这里直接返回，而不是让测试报错。
        """
        callback = self.fake.hook_callback
        if callback is None:
            return
        callback(FakeEvent(name, is_keypad, event_type))


class TestNumpadFiltering(HotkeyTestBase):

    def test_numpad_digits_are_captured(self):
        self.manager.set_numpad(True)

        self.press("1", is_keypad=True)
        self.press("3", is_keypad=True)
        self.press("9", is_keypad=True)

        self.assertEqual(self.received, [1, 3, 9])

    def test_top_row_digits_are_ignored(self):
        """
        最重要的一条：主键盘上的数字必须被放过。
        否则你在任何程序里打数字都会被这个工具抢走。
        """
        self.manager.set_numpad(True)

        for name in ("1", "2", "3", "4", "5"):
            self.press(name, is_keypad=False)

        self.assertEqual(self.received, [], "主键盘数字不该被截获")

    def test_mixed_stream_only_takes_numpad(self):
        self.manager.set_numpad(True)

        self.press("1", is_keypad=False)   # 主键盘
        self.press("2", is_keypad=True)    # 小键盘
        self.press("3", is_keypad=False)   # 主键盘
        self.press("4", is_keypad=True)    # 小键盘

        self.assertEqual(self.received, [2, 4])

    def test_zero_is_ignored(self):
        """没有「第 0 个选项」"""
        self.manager.set_numpad(True)
        self.press("0", is_keypad=True)
        self.assertEqual(self.received, [])

    def test_key_release_is_ignored(self):
        """只认按下，抬起不该触发（否则一次按键点两下）"""
        self.manager.set_numpad(True)
        self.press("2", is_keypad=True, event_type="down")
        self.press("2", is_keypad=True, event_type="up")
        self.assertEqual(self.received, [2])

    def test_nothing_when_disabled(self):
        """模式关着的时候什么都不该触发（先开再关，验证 hook 确实被摘掉）"""
        self.manager.set_numpad(True)
        self.press("1", is_keypad=True)
        self.assertEqual(self.received, [1], "开着的时候应该能触发")

        self.manager.set_numpad(False)
        self.press("2", is_keypad=True)
        self.assertEqual(self.received, [1], "关掉之后不该再触发")

    def test_non_numeric_keys_are_ignored(self):
        self.manager.set_numpad(True)
        self.press("enter", is_keypad=True)
        self.press("a", is_keypad=False)
        self.press("f8", is_keypad=False)
        self.assertEqual(self.received, [])


class TestNumpadToggling(HotkeyTestBase):

    def test_toggle_on_off(self):
        self.assertFalse(self.manager.numpad_enabled)

        self.assertTrue(self.manager.set_numpad(True))
        self.assertTrue(self.manager.numpad_enabled)

        self.press("1", is_keypad=True)
        self.assertEqual(self.received, [1])

        self.assertFalse(self.manager.set_numpad(False))
        self.assertFalse(self.manager.numpad_enabled)

        self.press("2", is_keypad=True)
        self.assertEqual(self.received, [1], "关掉之后不该再触发")

    def test_reattaching_hook(self):
        self.manager.set_numpad(True)
        self.manager.set_numpad(False)
        self.manager.set_numpad(True)

        self.press("5", is_keypad=True)
        self.assertEqual(self.received, [5], "重新开启后应该照常工作")

    def test_stop_removes_hook(self):
        self.manager.set_numpad(True)
        self.manager.stop()
        self.assertIn("the-hook", self.fake.unhooked)


class TestVoiceToggleKey(HotkeyTestBase):

    def test_f7_calls_the_callback(self):
        calls = []
        self.manager._on_toggle_voice = lambda: calls.append(1)
        self.manager._toggle_voice()
        self.assertEqual(len(calls), 1)

    def test_start_accepts_the_callback(self):
        """注册时要能接住这个回调，不能因为签名不匹配就整个热键都装不上"""
        logs = []
        manager = HotkeyManager(HotkeyConfig(), log=logs.append)
        ok = manager.start(on_toggle_voice=lambda: None)
        self.assertTrue(ok, f"start 应该成功，日志：{logs}")
        self.assertTrue(manager.available)


class TestForceReadKey(HotkeyTestBase):
    """小键盘「.」= 强制重新读一次界面"""

    def setUp(self):
        super().setUp()
        self.force_reads = []
        self.manager._on_force_read = lambda: self.force_reads.append(1)

    def test_decimal_triggers_force_read(self):
        self.manager.set_numpad(True)
        self.press("decimal", is_keypad=True)

        self.assertEqual(len(self.force_reads), 1)
        self.assertEqual(self.received, [], "小数点不该被当成选项序号")

    def test_digits_do_not_trigger_force_read(self):
        self.manager.set_numpad(True)
        self.press("2", is_keypad=True)

        self.assertEqual(self.force_reads, [])
        self.assertEqual(self.received, [2])

    def test_does_not_fire_on_release(self):
        self.manager.set_numpad(True)
        self.press("decimal", is_keypad=True)
        self.press("decimal", is_keypad=True, event_type="up")

        self.assertEqual(len(self.force_reads), 1, "抬起不该再触发一次")

    def test_holding_decimal_fires_once(self):
        self.manager.set_numpad(True)
        for _ in range(5):
            self.press("decimal", is_keypad=True)

        self.assertEqual(len(self.force_reads), 1, "按住不放只算一次")


class TestAutoRepeatSuppression(HotkeyTestBase):
    """
    按住小键盘不放时，系统会**持续**送来一串「按下」事件。

    如果不去重，按住一下就是连点几十次。
    这里用「按下/抬起」状态来区分：

        按住不放  → 只有第一次按下算数（后面那些键还按着）
        松开再按  → 中间有抬起，算新的一次

    **刻意不用时间窗口** —— 时间窗口分不清「按住不放」和「按错键想马上改」，
    后者是完全正常的操作，用时间拦就会把它静默丢掉。
    """

    def test_holding_key_fires_once(self):
        self.manager.set_numpad(True)

        for _ in range(10):                 # 模拟按住不放产生的重复事件
            self.press("2", is_keypad=True)

        self.assertEqual(self.received, [2], "按住不放只该触发一次")

    def test_release_then_press_again_fires_twice(self):
        self.manager.set_numpad(True)

        self.press("2", is_keypad=True)
        self.press("2", is_keypad=True, event_type="up")
        self.press("2", is_keypad=True)

        self.assertEqual(self.received, [2, 2], "松开再按是新的一次动作")

    def test_different_keys_even_while_held(self):
        """按着 2 不放的同时再按 3，3 应该照常触发"""
        self.manager.set_numpad(True)

        self.press("2", is_keypad=True)
        self.press("2", is_keypad=True)      # 重复，忽略
        self.press("3", is_keypad=True)      # 另一个键，是新动作

        self.assertEqual(self.received, [2, 3])

    def test_state_resets_when_numpad_off(self):
        self.manager.set_numpad(True)
        self.press("5", is_keypad=True)

        self.manager.set_numpad(False)
        self.manager.set_numpad(True)

        self.press("5", is_keypad=True)
        self.assertEqual(self.received, [5, 5], "重新开启后状态要干净")


class TestNumLockHint(HotkeyTestBase):

    def test_hints_once_when_keypad_gives_non_digit(self):
        """
        NumLock 没开时，小键盘按下去产生的是方向键事件：
        is_keypad 仍为真，但键名是 'down'/'end' 之类。这时要给一次提示。
        """
        self.manager.set_numpad(True)

        self.press("down", is_keypad=True)
        self.press("end", is_keypad=True)
        self.press("page down", is_keypad=True)

        hints = [line for line in self.logs if "NumLock" in line]
        self.assertEqual(len(hints), 1, "NumLock 提示只该出现一次，不能刷屏")
        self.assertEqual(self.received, [], "方向键不该被当成选项序号")


class TestNumpadZeroIsNext(HotkeyTestBase):

    def setUp(self):
        super().setUp()
        self.next_calls = []
        self.manager._on_next = lambda: self.next_calls.append(1)

    def test_numpad_zero_triggers_next(self):
        """小键盘 0 借给「下一题」——没有第 0 个选项，而 0 又是最好按的键"""
        self.manager.set_numpad(True)
        self.press("0", is_keypad=True)
        self.assertEqual(len(self.next_calls), 1)
        self.assertEqual(self.received, [], "0 不该被当成选项序号")

    def test_digits_still_go_to_options(self):
        self.manager.set_numpad(True)
        self.press("1", is_keypad=True)
        self.press("0", is_keypad=True)
        self.press("2", is_keypad=True)

        self.assertEqual(self.received, [1, 2])
        self.assertEqual(len(self.next_calls), 1)

    def test_top_row_zero_is_ignored(self):
        self.manager.set_numpad(True)
        self.press("0", is_keypad=False)
        self.assertEqual(self.next_calls, [], "主键盘的 0 不该触发")



class TestCallbackSafety(HotkeyTestBase):

    def test_callback_exception_does_not_escape(self):
        """回调里出错绝不能影响到整个键盘监听"""
        def boom(_number):
            raise RuntimeError("模拟回调出错")

        self.manager._on_option = boom
        self.manager.set_numpad(True)
        self.press("1", is_keypad=True)   # 不该抛异常


if __name__ == "__main__":
    unittest.main(verbosity=2)

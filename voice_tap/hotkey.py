#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
hotkey.py —— 全局热键

用全局热键而不是监听窗口按键，是因为 scrcpy 的窗口始终占着焦点 ——
如果只在某个窗口里监听，你按快捷键时压根收不到。

几个键：
    F8    按住说话，松开触发识别（hotkey 模式）
    F9    在「常驻监听」和「按住说话」两种模式间切换
    F10   开关「小键盘快捷点击」
    F7    开关语音
    ESC   退出

小键盘（模式开启时）：
    1~9   点对应的选项
    0     点「下一题」
    .     强制重新读一次界面（手动同步用）

小键盘模式值得一提：

    它不是简单地监听 '1'..'9'。因为 keyboard 库把**小键盘数字和主键盘数字
    映射成了同一个键名**，那样做会把你在任何程序里打的数字都抢走。

    这里改用底层 hook，读事件上的 is_keypad 标志 —— 那是库根据扫描码算出来的，
    能真正区分两者。所以主键盘上的数字键完全不受影响。

    注意：需要 NumLock 是开的。NumLock 关着时小键盘产生的是方向键的事件，
    is_keypad 仍为真但键名不是数字，这时会给出提示。

热键回调跑在独立线程里，所以这里只做「置位事件」或「塞进队列」这种瞬时动作，
真正耗时的识别与点击由主线程或工作线程去做。
"""

import threading


class HotkeyManager:

    def __init__(self, cfg, log=print):
        self.cfg = cfg
        self.log = log
        self.available = False
        self._keyboard = None
        self._hooks = []

        # 按住说话期间的信号
        self.ptt_pressed = threading.Event()
        self.quit_requested = threading.Event()

        # 小键盘
        self.numpad_enabled = False
        self._numpad_hook = None
        self._numlock_hinted = False
        self._numlock_hint = None
        # 记录「现在哪些键是按着的」。
        # 按住不放时系统会**持续**送来「按下」事件 —— 那不是新的一次动作。
        self._keys_down = set()

        self._on_toggle = None
        self._on_release = None
        self._on_option = None
        self._on_next = None
        self._on_force_read = None
        self._on_toggle_voice = None

    # ---------------------------------------------------------- 生命周期

    def start(self, on_toggle=None, on_release=None, on_option=None, on_next=None,
              on_force_read=None, on_toggle_voice=None):
        """
        注册热键。

        on_toggle     按 F9：切换「常驻监听 / 按住说话」
        on_release    松开 F8
        on_option     小键盘按下 1~9，参数是 1 开始的选项序号
        on_next       小键盘按下 0（点「下一题」）
        on_force_read 小键盘按下「.」（强制重新读一次界面）
        on_toggle_voice 按 F7（开关语音）
        """
        self._on_toggle = on_toggle
        self._on_release = on_release
        self._on_option = on_option
        self._on_next = on_next
        self._on_force_read = on_force_read
        self._on_toggle_voice = on_toggle_voice

        try:
            import keyboard
        except ImportError:
            self.log("      [!!] 没有安装 keyboard，全局热键不可用")
            self.log("           热键模式和小键盘模式都用不了；常驻监听不受影响")
            return False

        self._keyboard = keyboard

        try:
            self._hooks.append(
                keyboard.on_press_key(self.cfg.push_to_talk, self._ptt_down, suppress=False))
            self._hooks.append(
                keyboard.on_release_key(self.cfg.push_to_talk, self._ptt_up, suppress=False))
            self._hooks.append(
                keyboard.add_hotkey(self.cfg.toggle_mode, self._toggle, suppress=False))
            self._hooks.append(
                keyboard.add_hotkey(self.cfg.toggle_numpad, self._toggle_numpad, suppress=False))
            self._hooks.append(
                keyboard.add_hotkey(self.cfg.toggle_voice, self._toggle_voice, suppress=False))
            self._hooks.append(
                keyboard.add_hotkey("esc", self._quit, suppress=False))
        except Exception as exc:  # noqa: BLE001
            self.log(f"      [!!] 注册全局热键失败：{type(exc).__name__}: {exc}")
            self.log("           部分系统需要以管理员身份运行才能注册全局热键")
            return False

        self.available = True
        self.log(f"      热键：F8 按住说话　{self.cfg.toggle_mode.upper()} 切换模式　"
                 f"{self.cfg.toggle_numpad.upper()} 开关小键盘　"
                 f"{self.cfg.toggle_voice.upper()} 开关语音　ESC 退出")

        if self.cfg.numpad_enabled:
            self.set_numpad(True)

        return True

    def stop(self):
        self.set_numpad(False, quiet=True)
        if self._keyboard is None:
            return
        for hook in self._hooks:
            try:
                self._keyboard.unhook(hook)
            except Exception:  # noqa: BLE001
                pass
        self._hooks.clear()
        try:
            self._keyboard.unhook_all_hotkeys()
        except Exception:  # noqa: BLE001
            pass

    # ---------------------------------------------------------- 小键盘

    def set_numpad(self, enabled, quiet=False):
        """
        开关小键盘模式。返回开完之后的状态。

        真正的实现是往底层挂一个 hook：只在 is_keypad 为真（也就是
        小键盘）时才理会，主键盘的数字键一律放过。
        """
        if enabled and not self.available:
            if not quiet:
                self.log("      [!!] 全局热键不可用，小键盘模式也开不了")
            return False

        if enabled and self._numpad_hook is None:
            try:
                self._numpad_hook = self._keyboard.hook(self._numpad_event)
            except Exception as exc:  # noqa: BLE001
                self.log(f"      [!!] 挂载小键盘监听失败：{type(exc).__name__}: {exc}")
                return False
            self.numpad_enabled = True
            if not quiet:
                self.log("      >>> 小键盘模式已开启：1~9 点选项　0 点下一题　. 强制重新读屏")
                self.log("          NumLock 必须是开着的，否则小键盘会被当成方向键")
        elif not enabled and self._numpad_hook is not None:
            try:
                self._keyboard.unhook(self._numpad_hook)
            except Exception:  # noqa: BLE001
                pass
            self._numpad_hook = None
            self.numpad_enabled = False
            self._keys_down.clear()
            if not quiet:
                self.log("      >>> 小键盘模式已关闭")

        return self.numpad_enabled

    def _toggle_numpad(self):
        self.log()
        self.set_numpad(not self.numpad_enabled)

    def _toggle_voice(self):
        """F7：开关语音。点完选项后手机会念单词，觉得干扰大时临时关掉。"""
        if self._on_toggle_voice is not None:
            try:
                self._on_toggle_voice()
            except Exception:  # noqa: BLE001
                pass


    def _numpad_event(self, event):
        """
        底层键盘事件回调。跑在监听线程里，必须快进快出。

        这里用**按下/抬起状态**来挡「按住不放」造成的重复，而不是靠计时：

            按住小键盘 2 不放 → 系统持续送来一串「按下」事件
                               → 键还在按着，全部忽略
            松开再按一次       → 中间有「抬起」，才算新的一次动作

        为什么不用时间窗口：时间窗口分不清「按住不放」和「按错键想马上改」——
        后者是完全正常的操作，用时间拦就会把它静默丢掉。实测踩过这个坑。
        """
        try:
            if not self.numpad_enabled:
                return

            name = (getattr(event, "name", "") or "").strip()
            kind = getattr(event, "event_type", None)

            if kind == "up":
                self._keys_down.discard(name)
                return

            if kind != "down":
                return

            if not getattr(event, "is_keypad", False):
                # 不是小键盘的键，完全不理会 —— 主键盘数字就靠这一行被放过
                return

            # 键还按着 → 这是自动重复，不是新的一次按下
            if name in self._keys_down:
                return
            self._keys_down.add(name)

            if name.isdigit():
                number = int(name)
                if number == 0:
                    # 小键盘 0 借给「下一题」。没有「第 0 个选项」，
                    # 而 0 又是最好按的那个键，正好给它。
                    if self._on_next is not None:
                        self._on_next()
                    return
                if self._on_option is not None:
                    self._on_option(number)
                return

            if name == "decimal":
                # 小键盘的「.」—— 强制重新读一次界面。
                # 你自己用鼠标动了手机、或者觉得程序看到的和屏幕上不一样时按一下。
                # 正常流程不需要它：「点击后预读」关掉之后，按键时本来就会重新读。
                if self._on_force_read is not None:
                    self._on_force_read()
                return

            # 是小键盘、但键名不是数字 —— 几乎可以肯定是 NumLock 没开
            if name and not self._numlock_hinted:
                self._numlock_hinted = True
                self.log()
                self.log("      [注意] 小键盘按下去被识别成了方向键，说明 NumLock 没开。")
                self.log("             按一下键盘上的 NumLock 键，再试小键盘 1~9。")
                self.log()
        except Exception:  # noqa: BLE001
            # 回调里绝不能抛异常，否则会影响整个键盘监听
            pass

    # ---------------------------------------------------------- 其它回调

    def _ptt_down(self, _event):
        self.ptt_pressed.set()

    def _ptt_up(self, _event):
        self.ptt_pressed.clear()
        if self._on_release is not None:
            try:
                self._on_release()
            except Exception:  # noqa: BLE001
                pass

    def _toggle(self):
        if self._on_toggle is not None:
            try:
                self._on_toggle()
            except Exception:  # noqa: BLE001
                pass

    def _quit(self):
        self.quit_requested.set()

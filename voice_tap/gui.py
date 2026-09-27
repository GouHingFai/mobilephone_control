#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gui.py —— 置顶浮窗

**这里只摆控件、连线和刷新，不放任何业务逻辑。**

理由：Tkinter 的界面没法在单元测试里跑（要有显示器）。所以逻辑一律放到
ui_state.py 和 main.py 的函数里 —— 那边可以用普通测试完整覆盖；这里保持薄，
薄到「看一眼就知道没写错」的程度。

本模块**只在 --gui（或配置里开了界面）时才会被 import** —— 顶层 import tkinter，
没装 Tkinter 的机器不该因为一个界面而起不来（main.py 里整段兜住了）。
"""

from __future__ import annotations

import time
import tkinter as tk
from tkinter import ttk


def _intent_command(on_intent, name):
    """
    点一下按钮 = 把这个意图名交出去。**界面只认意图名，不认别的。**

    用工厂函数（而不是在循环里写 `lambda: ...`）是为了把名字钉进闭包，
    免得所有按钮都捕获到循环结束时的那一个值。
    """
    return lambda: on_intent(name)


class AppWindow:

    def __init__(self, root, collect_state, on_intent, refresh_ms=150, topmost=True,
                 on_closed=None, should_close=None):
        self.root = root
        self.collect_state = collect_state
        self.on_intent = on_intent
        self.refresh_ms = refresh_ms
        self.on_closed = on_closed
        self.should_close = should_close
        self._buttons = {}

        root.title("声控手机助手")
        root.attributes("-topmost", bool(topmost))
        root.minsize(340, 380)
        self._build()
        self.refresh()
        self._tick()

    def current_geometry(self):
        """当前窗口位置与大小 (x, y, 宽, 高)"""
        self.root.update_idletasks()
        return (self.root.winfo_x(), self.root.winfo_y(),
                self.root.winfo_width(), self.root.winfo_height())

    def close(self):
        """
        关窗前的收尾：先把窗口位置交出去存好，再销毁窗口。

        **窗口 X、键盘上的退出键、界面上的退出按钮，三条路都汇到这里** ——
        都得存位置，否则那一次的位置就白丢了。
        """
        if self.on_closed is not None:
            try:
                self.on_closed(self.current_geometry())
            except Exception:  # noqa: BLE001
                # 存位置失败不该拦着退出 —— 大不了下次用回默认位置
                pass
        self.root.destroy()

    # -------------------------------------------------- 摆控件

    def _build(self):
        # **这里的按钮、文字、意图名、快捷键、布局，全来自 collect_state 的数据。**
        # 本文件里搜不到任何按钮标签、意图名、快捷键的字面量 —— 也就没有
        # 「两边没一起改」这种病（上回入队格式改了就栽在这上面：界面每个按钮
        # 都点了没反应，而 300+ 条测试全绿，因为这里要 import tkinter、测不了）。
        state = self.collect_state()
        pad = {"padx": 6, "pady": 3}

        box = ttk.LabelFrame(self.root, text="控制")
        box.pack(fill="x", **pad)
        # 每行一个 Frame；行里的按钮用 grid 摆成**等宽列**（uniform）并 sticky="ew"。
        #
        # 这样布局只取决于窗口宽度，跟按钮里的字多长无关。于是既不会一行塞太多
        # （塞不下），也不会出现某个按钮被挤没。
        #
        # width 只是列宽的一个下限（真正的宽度由上面的等分决定），调小它不影响
        # 显示，只让「最窄列」更宽松。
        for row_buttons in state["controls"]:
            row = ttk.Frame(box)
            row.pack(fill="x")
            for col in range(len(row_buttons)):
                row.columnconfigure(col, weight=1, uniform="toggle")
            for col, spec in enumerate(row_buttons):
                button = ttk.Button(
                    row, text=spec["text"], width=8,
                    command=_intent_command(self.on_intent, spec["intent"]))
                button.grid(row=0, column=col, sticky="ew", padx=6, pady=3)
                self._buttons[spec["intent"]] = button

        # 底部一排：靠左、按自然宽度摆（不参与上面的等宽网格）。
        row = ttk.Frame(self.root)
        row.pack(fill="x", **pad)
        for spec in state["actions"]:
            button = ttk.Button(
                row, text=spec["text"],
                command=_intent_command(self.on_intent, spec["intent"]))
            button.pack(side="left", **pad)
            self._buttons[spec["intent"]] = button

        ttk.Label(self.root, text="程序读到的屏幕").pack(anchor="w", **pad)
        self._screen_box = self._make_text(height=10)
        ttk.Label(self.root, text="我的输入").pack(anchor="w", **pad)
        self._input_box = self._make_text(height=7)

    def _make_text(self, height):
        box = tk.Text(self.root, height=height, wrap="word",
                      font=("Consolas", 10), state="disabled")
        box.pack(fill="both", expand=True, padx=6, pady=(0, 3))
        return box

    # -------------------------------------------------- 刷新

    def _tick(self):
        # 键盘上的退出键和界面上的退出按钮都只是把退出请求置了个位；
        # 主线程正卡在 mainloop() 里，没人叫停它窗口就干留着、进程也吊着。
        # 所以每次刷新前问一句「要不要关」，要关就走和窗口 X 相同的那条收尾路。
        if self.should_close is not None and self.should_close():
            self.close()
            return
        try:
            self.refresh()
        finally:
            self.root.after(self.refresh_ms, self._tick)

    def refresh(self):
        state = self.collect_state()
        self._render_buttons(state)
        self._set_text(self._screen_box, self._render_screen(state["screen"]))
        self._set_text(self._input_box, self._render_inputs(state["inputs"]))

    def _render_buttons(self, state):
        # 文字是 collect_state 拼好的（含快捷键后缀、开/关、当前模式、当前语言），
        # 这里只负责贴上去 —— 不含任何判断。
        for row_buttons in state["controls"]:
            for spec in row_buttons:
                self._apply_button(spec)
        for spec in state["actions"]:
            self._apply_button(spec)

    def _apply_button(self, spec):
        button = self._buttons.get(spec["intent"])
        if button is not None:
            button.config(text=spec["text"])

    @staticmethod
    def _render_screen(view):
        if view is None:
            return "（尚未读到）"
        lines = []
        if view.prompt:
            lines.append(f"题干：{view.prompt}")
        for opt in view.options:
            lines.append(f"  {opt.index}. {opt.text}")
        if not view.options and view.reason:
            lines.append(f"（{view.reason}）")
        age = "" if view.age_seconds is None else f"，{view.age_seconds:.1f} 秒前读的"
        lines.append(f"[来源：{view.source or '—'}{age}]")
        return "\n".join(lines)

    @staticmethod
    def _render_inputs(events):
        if not events:
            return "（还没有）"
        out = []
        for event in events:
            when = time.strftime("%H:%M:%S", time.localtime(event.at)) if event.at else ""
            detail = f"（{event.detail}）" if event.detail else ""
            out.append(f"{when} [{event.kind}] {event.label}{detail} → {event.outcome or '—'}")
        return "\n".join(out)

    @staticmethod
    def _set_text(widget, text):
        widget.config(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", text)
        widget.config(state="disabled")


def run(collect_state, on_intent, refresh_ms=150, topmost=True,
        geometry=None, on_closed=None, should_close=None, on_window_ready=None):
    """
    开窗并进入 Tk 事件循环。**必须在主线程调用。**

    on_closed 会在窗口关闭时收到当前几何位置（(x, y, 宽, 高)）。

    should_close 是个无参可调用对象：界面每次刷新时问它一次，一旦返回真值
    就把窗口关掉。键盘上的退出键、点界面上的退出按钮都只是把退出请求置位，
    **不靠这个轮询的话没人去 destroy 根窗口**，mainloop 就永远不返回、
    进程也结束不了。三条退出路（键盘／界面按钮／窗口 X）最终都汇到 close()。

    on_window_ready 在窗口**已经建好、就差进事件循环**那一瞬间被调一次。
    给 main 用来启动「后台听声音」那条线程：窗口建不出来时会在它之前就抛异常，
    于是那条线程压根不会启动 —— 退回命令行时就不会有两条循环在抢。
    """
    root = tk.Tk()
    if geometry:
        root.geometry(f"{geometry[2]}x{geometry[3]}+{geometry[0]}+{geometry[1]}")
    window = AppWindow(root, collect_state, on_intent,
                       refresh_ms=refresh_ms, topmost=topmost,
                       on_closed=on_closed, should_close=should_close)

    root.protocol("WM_DELETE_WINDOW", window.close)
    if on_window_ready is not None:
        on_window_ready()
    root.mainloop()

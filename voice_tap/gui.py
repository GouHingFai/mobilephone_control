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


# 界面上的开关按钮：名字（就是 main.ctx["intents"] 里的键）+ 中文标签。
# 点一下就是把这个名字交给 on_intent —— 走的是与热键完全相同的那套回调。
TOGGLE_LABELS = (
    ("toggle_voice", "语音"),
    ("toggle_mode", "模式"),
    ("toggle_numpad", "小键盘"),
    ("toggle_prefetch", "点击后预读"),
    ("toggle_voice_next", "语音说下一题"),
)


class AppWindow:

    def __init__(self, root, collect_state, on_intent, refresh_ms=150, topmost=True,
                 on_closed=None, should_close=None):
        self.root = root
        self.collect_state = collect_state
        self.on_intent = on_intent
        self.refresh_ms = refresh_ms
        self.on_closed = on_closed
        self.should_close = should_close
        self._labels = dict(TOGGLE_LABELS)
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

        **窗口 X 和 ESC/界面上的「退出」都走这一条路** —— 两条路都得存位置，
        否则按 ESC 退出时那次的位置就白丢了。
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
        pad = {"padx": 6, "pady": 3}

        box = ttk.LabelFrame(self.root, text="控制")
        box.pack(fill="x", **pad)
        for name, _label in TOGGLE_LABELS:
            button = ttk.Button(box, text=name, width=15,
                                command=lambda n=name: self.on_intent(n))
            button.pack(side="left", **pad)
            self._buttons[name] = button

        row = ttk.Frame(self.root)
        row.pack(fill="x", **pad)
        ttk.Button(row, text="强制重新读屏",
                   command=lambda: self.on_intent("force_read")).pack(side="left", **pad)
        ttk.Button(row, text="退出",
                   command=lambda: self.on_intent("quit")).pack(side="left", **pad)

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
        # ESC 和界面上的「退出」都只是把 quit_requested 置了个位；
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
        self._render_toggles(state["toggles"])
        self._set_text(self._screen_box, self._render_screen(state["screen"]))
        self._set_text(self._input_box, self._render_inputs(state["inputs"]))

    def _render_toggles(self, toggles):
        on = {
            "toggle_voice": toggles["voice"],
            "toggle_mode": toggles["mode"] == "hotkey",
            "toggle_numpad": toggles["numpad"],
            "toggle_prefetch": toggles["prefetch"],
            "toggle_voice_next": toggles["voice_next"],
        }
        self._buttons["toggle_mode"].config(
            text="按住说话" if on["toggle_mode"] else "常驻监听")
        for name, value in on.items():
            if name == "toggle_mode":
                continue
            self._buttons[name].config(
                text=f"{self._labels[name]}：{'开' if value else '关'}")

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
    就把窗口关掉。按 ESC、点界面上的「退出」都只是把退出请求置位，
    **不靠这个轮询的话没人去 destroy 根窗口**，mainloop 就永远不返回、
    进程也结束不了。三条退出路（ESC／退出按钮／窗口 X）最终都汇到 close()。

    on_window_ready 在窗口**已经建好、就差进事件循环**那一瞬间被调一次。
    给 main 用来启动「后台听语音」那条线程：窗口建不出来时会在它之前就抛异常，
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

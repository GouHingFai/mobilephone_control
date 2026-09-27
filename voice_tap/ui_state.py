#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ui_state.py —— 界面与主逻辑之间的共享状态

设计原则：**逻辑全在这里，界面只负责画。**

界面（gui.py）跑在 Tkinter 的主线程，主逻辑（听语音、处理按键）跑在别的线程。
两边唯一的交汇点就是这个对象：主逻辑往上写（现在读到哪一屏、刚听到什么、
点成没成），界面定时来读。所以这里必须线程安全，读出来的永远是一份完整快照。

它顺带把「界面按钮」和「主逻辑」解耦：按钮只往意图队列塞一个名字，
真正执行由动作工作线程去做 —— 这样按钮不会因为「监听线程正阻塞着等说话」而没反应。

（本模块刻意不 import tkinter：它能被普通单元测试完整覆盖。）
"""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field


@dataclass
class OptionView:
    """界面要显示的一个选项：序号 + 文字（**不含坐标** —— 用户明确不要）"""
    index: int
    text: str


@dataclass
class ScreenView:
    """界面要显示的「程序手里那一屏」"""
    prompt: str = ""
    options: list = field(default_factory=list)     # list[OptionView]
    source: str = ""            # "预读" / "当场读屏" / ""
    age_seconds: float | None = None
    page: str = ""              # quiz / detail / other
    ok: bool = False
    reason: str = ""


@dataclass
class InputEvent:
    """一条「我的输入」记录：按了什么键 / 说了什么话，以及结果"""
    kind: str = ""          # speech / numpad / next / force_read
    label: str = ""         # 识别出的文字 / "3" / "0" / "."
    detail: str = ""        # 置信度、耗时等的附加说明
    outcome: str = ""       # "点了第 4 个" / "已忽略：界面已翻页" / "没匹配上"
    at: float = 0.0


class UiState:

    def __init__(self, keep_inputs=8):
        self._lock = threading.Lock()
        self._screen = None
        self._inputs = deque(maxlen=keep_inputs)
        self._intents = []

    # -------------------------------------------------- 主逻辑 → 界面

    def set_screen(self, view):
        with self._lock:
            self._screen = view

    def current_screen(self):
        with self._lock:
            return self._screen

    def record_input(self, event):
        # 时间戳在拿锁之前补：补时间戳与入队是两件事，不必占着锁做
        if not event.at:
            event.at = time.time()
        with self._lock:
            self._inputs.append(event)

    def recent_inputs(self, limit=5):
        """最近的输入，**最新的在前**"""
        with self._lock:
            items = list(self._inputs)
        if limit <= 0:
            # 注意 limit=0 时 items[-0:] 等于 items[0:]（返回全部），所以单独挡一下
            return []
        return items[-limit:][::-1]

    # -------------------------------------------------- 界面 → 主逻辑

    def post_intent(self, name):
        with self._lock:
            self._intents.append(name)

    def take_intents(self):
        with self._lock:
            items, self._intents = self._intents, []
            return items

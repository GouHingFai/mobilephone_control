#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
voice_gate.py —— 语音开关与「点击后的静音期」

## 为什么需要它

真机日志里有一段现象很难解释：用户明明在按小键盘操作，识别结果却总是
「上一题刚答过的那个词」—— `'Brooke.'` `'Benevolent'` `'Convey'` `'sinistral'`。

后来用户点破了：**点完选项之后，手机会把那个单词的读音播出来。**

于是整件事就顺了：

    点选项 → 手机喇叭念单词（约 1～1.2 秒）→ 麦克风收进去
           → 程序以为你在说话 → 送去识别 → 得到刚答过的那个词
           → 而这时界面早翻过去了 → 什么都匹配不上

**程序一直在识别手机，不是识别人。**

## 怎么解决

点完一个选项之后的一段时间内，干脆不监听语音 —— 那段时间里麦克风收到的基本
都是手机在念单词。等静音期过了再开始听，那时候你说的才是真的回答。

静音期长度在 config.yaml 的 `voice.mute_after_click_ms`，默认 2500 毫秒
（单词读音 1～1.2 秒 + 点击到开始播放的延迟 + 一点余量）。

另外按 F7 可以整体开关语音，环境吵或者只想用键盘时用得上。
"""

import threading
import time


class VoiceGate:
    """管两件事：点击后的静音期，以及语音总开关"""

    def __init__(self, cfg, log=print):
        self.cfg = cfg
        self.log = log
        self.enabled = bool(cfg.enabled)
        self._until = 0.0
        self._lock = threading.Lock()
        self._reported = False

    # ---------------------------------------------------------- 静音期

    def suppress(self, seconds=None):
        """
        进入静音期。点击之后调用。

        取「当前的截止时间」和「新的截止时间」里更晚的那个 ——
        连点几下时不能把静音期缩短。
        """
        if seconds is None:
            seconds = self.cfg.mute_after_click_ms / 1000.0
        if seconds <= 0:
            return
        with self._lock:
            self._until = max(self._until, time.monotonic() + seconds)
            self._reported = False

    def remaining(self):
        """静音期还剩多少秒（0 表示没在静音）"""
        if not self.enabled:
            return 0.0
        with self._lock:
            return max(0.0, self._until - time.monotonic())

    def wait_until_open(self, stop_event=None, poll=0.05):
        """
        如果还在静音期就等着，返回等了多少秒。

        返回之后调用方可以放心去监听语音 —— 这时候手机已经念完了。
        """
        started = time.monotonic()
        while True:
            remain = self.remaining()
            if remain <= 0:
                break
            if stop_event is not None and stop_event.is_set():
                break
            time.sleep(min(remain, poll))

        waited = time.monotonic() - started
        if waited > 0.05 and not self._reported:
            self._reported = True
            self.log(f"       （点击后静音 {waited:.1f} 秒 —— 手机在念单词读音，"
                     "免得被当成你在说话）")
        return waited

    # ---------------------------------------------------------- 总开关

    def toggle(self):
        self.enabled = not self.enabled
        self.log()
        if self.enabled:
            self.log("  >>> 语音已开启")
        else:
            self.log("  >>> 语音已关闭（只认小键盘）")
        return self.enabled

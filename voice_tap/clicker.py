#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
clicker.py —— 点击执行

两件事：把坐标点下去，以及别点太快。

- **防连点**：一句话可能触发重复识别，加上界面切换的瞬间容易误触，
  所以点击后一段时间内直接丢弃新指令。
- **preview 模式**：不真点，而是在截图上把将要点的位置画个红圈存下来。
  这是远程调试的主要手段 —— 开发者看不到手机，但能看这张图。
"""

import threading
import time
from pathlib import Path

from .adb import AdbError


class Clicker:

    def __init__(self, adb, click_cfg, log=print, debug_dir=None):
        self.adb = adb
        self.cfg = click_cfg
        self.log = log
        self.debug_dir = Path(debug_dir) if debug_dir else None
        self._last_click_at = 0.0
        self._preview_seq = 0
        # 语音线程和小键盘线程都会调用 click()，防连点的「检查 + 记时间」
        # 必须是原子的，否则两边会同时通过检查、连点两下
        self._lock = threading.Lock()

    def click(self, node, preview=False, key=None):
        """
        点 node。返回 True 表示确实点了（或 preview 下确实标了）。

        `key` 不为 None 表示「这是用户的一次明确按键动作」。

        **按键动作不受时间限制，一律执行。** 因为按住不放造成的重复
        已经在 hotkey 那一层用按下/抬起状态挡掉了，这里再按时间拦一遍
        只会误伤：按 3 发现按错、马上按 2 改过来是完全正常的操作，
        原来就是被这一层静默丢掉的（日志里那句「[跳过] 距上次点击只有 693 毫秒」）。

        key 为 None（语音路径）仍保留时间判断。那边防的是同一句话被
        重复处理；不过实测语音整条流水线本身就要 2 秒以上，
        两次点击天然相隔很远，这个判断几乎不会触发，留着纯粹是保险。
        """
        with self._lock:
            now = time.monotonic()
            if key is None:
                gap_ms = (now - self._last_click_at) * 1000
                if self._last_click_at and gap_ms < self.cfg.debounce_ms:
                    self.log(f"      >>> [已跳过] 距上次点击只有 {gap_ms:.0f} 毫秒，"
                             "判定为同一句话被重复处理")
                    return False
            self._last_click_at = now

        if preview:
            self._save_preview(node)
            return True

        try:
            self.adb.tap(node.x, node.y)
        except AdbError as exc:
            self.log(f"      [!!] {exc}")
            return False

        # 点完之后给界面一点反应时间，避免下一次识别在切换动画中触发
        time.sleep(self.cfg.settle_ms / 1000.0)
        return True

    # ---------------------------------------------------------- preview

    def _save_preview(self, node):
        """
        截一张图，在目标位置画个红圈，存到 debug 目录。
        这样开发者能远程看到「程序到底打算点哪里」。
        """
        if self.debug_dir is None:
            self.log(f"      [preview] 将要点击 {node.text!r} @ ({node.x},{node.y})")
            return

        try:
            from PIL import Image, ImageDraw
            import io
        except ImportError:
            self.log(f"      [preview] 未安装 pillow，跳过画圈。将要点击 {node.text!r} @ ({node.x},{node.y})")
            return

        png = self.adb.screencap()
        if not png:
            self.log(f"      [preview] 截屏失败，只记录坐标：{node.text!r} @ ({node.x},{node.y})")
            return

        try:
            self.debug_dir.mkdir(parents=True, exist_ok=True)
            image = Image.open(io.BytesIO(png)).convert("RGB")
            draw = ImageDraw.Draw(image)

            radius = 46
            left, top = node.x - radius, node.y - radius
            right, bottom = node.x + radius, node.y + radius
            for width in range(5):
                draw.ellipse((left - width, top - width, right + width, bottom + width),
                             outline=(255, 0, 0))
            # 十字准星，方便看清圆心到底落在哪
            draw.line((node.x - radius - 20, node.y, node.x + radius + 20, node.y),
                      fill=(255, 0, 0), width=3)
            draw.line((node.x, node.y - radius - 20, node.x, node.y + radius + 20),
                      fill=(255, 0, 0), width=3)

            self._preview_seq += 1
            safe_name = "".join(ch for ch in node.text if ch.isalnum() or ch in "._-")[:24] or "target"
            out = self.debug_dir / f"preview_{self._preview_seq:03d}_{safe_name}.png"
            image.save(out)
            self.log(f"      [preview] 目标 {node.text!r} @ ({node.x},{node.y})，已画圈存图：{out.name}")
        except Exception as exc:  # noqa: BLE001
            self.log(f"      [preview] 画圈失败（{type(exc).__name__}: {exc}），只记录坐标："
                     f"{node.text!r} @ ({node.x},{node.y})")

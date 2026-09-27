#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
adb.py —— 对 adb 命令行的封装

只做三件事：抓界面、截屏、点击。所有调用都带超时，不会把主程序卡死。

关于抓界面用 uiautomator dump 而不是别的方式：这是唯一能同时拿到
「文字」和「精确坐标」的官方途径。实测在 GRE3000 上稳定可用。
"""

import glob
import os
import re
import subprocess
import time
from pathlib import Path


class AdbError(RuntimeError):
    """adb 层面的错误，消息已经是给人看的中文"""


# 从 dumpsys window 的输出里抠出当前前台应用包名
_FOCUS_PATTERNS = (
    re.compile(r"mCurrentFocus=Window\{[^}]*?\s+([A-Za-z0-9_.]+)/"),
    re.compile(r"mFocusedApp=.*?\s+([A-Za-z0-9_.]+)/"),
)


# scrcpy 发行版一定自带 adb.exe，这是最可能的来源
ADB_CANDIDATES = [
    r"H:\scrcpy-win64-v4.1\adb.exe",
    r"H:\scrcpy-win64-*\adb.exe",
    r"C:\platform-tools\adb.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Android\Sdk\platform-tools\adb.exe"),
    os.path.expandvars(r"%USERPROFILE%\platform-tools\adb.exe"),
]


class Adb:
    """adb 命令封装"""

    def __init__(self, path=None, remote_xml="/sdcard/voice_tap.xml", timeout=20):
        self.path = path or self.find()
        if not self.path:
            raise AdbError(
                "找不到 adb.exe。请用 --adb 指定完整路径，"
                r"例如 --adb \"H:\scrcpy-win64-v4.1\adb.exe\""
            )
        self.remote_xml = remote_xml
        self.timeout = timeout
        # 上一次成功读屏拿到的 XML 大小。异常小或缺失说明读到的不对劲，
        # 记下来供上层打日志。
        self.last_dump_bytes = 0

    # ---------------------------------------------------------- 内部

    @staticmethod
    def find(explicit=None):
        """按优先级找出可用的 adb.exe，找不到返回 None"""
        if explicit and Path(explicit).is_file():
            return explicit

        env_adb = os.environ.get("ADB")
        if env_adb and Path(env_adb).is_file():
            return env_adb

        for pattern in ADB_CANDIDATES:
            for hit in sorted(glob.glob(pattern)):
                if Path(hit).is_file():
                    return hit

        import shutil
        return shutil.which("adb")

    def _flags(self):
        # 避免每次调用 adb 都弹一个黑窗口
        if os.name == "nt":
            return getattr(subprocess, "CREATE_NO_WINDOW", 0)
        return 0

    def run(self, args, timeout=None, binary=False):
        """
        执行一条 adb 命令。
        返回 (returncode, stdout, stderr)；binary=True 时 stdout 是 bytes。
        """
        cmd = [self.path] + list(args)
        timeout = timeout or self.timeout
        try:
            proc = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=timeout,
                creationflags=self._flags(),
            )
        except subprocess.TimeoutExpired:
            return -999, (b"" if binary else ""), f"adb 命令超时（{timeout} 秒）: {' '.join(args[1:])}"
        except FileNotFoundError:
            return -998, (b"" if binary else ""), f"找不到可执行文件: {self.path}"
        except Exception as exc:  # noqa: BLE001
            return -997, (b"" if binary else ""), f"{type(exc).__name__}: {exc}"

        if binary:
            return proc.returncode, proc.stdout, proc.stderr.decode("utf-8", errors="replace")
        return (
            proc.returncode,
            proc.stdout.decode("utf-8", errors="replace"),
            proc.stderr.decode("utf-8", errors="replace"),
        )

    # ---------------------------------------------------------- 公开接口

    def device_serial(self):
        """返回已连接设备序列号；没有可用设备就抛 AdbError"""
        rc, out, err = self.run(["devices"], timeout=30)
        if rc != 0:
            raise AdbError(f"adb devices 执行失败：{err.strip() or out.strip()}")

        lines = [ln.strip() for ln in out.splitlines()[1:] if ln.strip()]
        if not lines:
            raise AdbError(
                "没有检测到任何安卓设备。请检查：\n"
                "      1. 手机用数据线连着电脑，且是「传输文件」模式\n"
                "      2. 开发者选项里打开了「USB 调试」\n"
                "      3. 手机上弹出的授权框点了「允许」\n"
                "      4. scrcpy 能正常投屏的话，adb 一定是通的，重点看上面的报错"
            )

        for line in lines:
            parts = line.split()
            if len(parts) >= 2 and parts[1] == "device":
                return parts[0]

        states = ", ".join(ln for ln in lines)
        raise AdbError(
            f"设备连接状态异常（{states}）。常见是 unauthorized 或 offline：\n"
            "      拔插数据线，在手机上重新确认授权；或执行 adb kill-server 后重试"
        )

    def device_info(self):
        """拿设备型号、安卓版本、屏幕分辨率等，用于日志"""
        info = {}
        for label, prop in (
            ("型号", "ro.product.model"),
            ("品牌", "ro.product.brand"),
            ("Android", "ro.build.version.release"),
        ):
            rc, out, _ = self.run(["shell", "getprop", prop])
            info[label] = out.strip() if rc == 0 else "?"

        rc, out, _ = self.run(["shell", "wm", "size"])
        info["分辨率"] = out.strip().replace("Physical size:", "").strip() if rc == 0 else "?"
        return info

    def dump_ui(self, retries=3, retry_wait=0.4):
        """
        抓当前界面的无障碍树，返回 XML 字符串。

        这份 XML 里每个控件都同时带着文字和精确坐标（bounds），
        坐标是系统报的，不是算出来的 —— 这是整个方案准确性的来源。

        界面在动画中时 dump 会报 "could not get idle state"，
        这是这个方案最常见的失败模式，所以必须重试。

        性能上刻意用**一条命令**完成：dump 到文件后立刻 cat 回来。
        分成两步（dump 一次、cat 一次）要多一次 adb 往返，在 Windows 上
        每次往返都是一次进程创建，白花一两百毫秒。

        **但这里踩过一个坑，值得写下来**：合并成一条命令时，我把 dump 的输出
        重定向进了 /dev/null，于是**没法判断 dump 到底成功没有**。
        如果 dump 失败（界面在动画时会报 "could not get idle state"），
        文件根本没更新，而 cat 会把**上一次的旧文件**读回来 ——
        旧文件里当然也有 `<hierarchy`，于是我们把过期界面当成了当前界面，
        一声不响。实测里那些「255 毫秒就读完」的可疑记录就是这么来的。

        现在的做法：**先删掉文件**。这样 dump 一失败，cat 就没东西可读，
        我们立刻知道这次读屏无效并重试 —— 宁可慢一点重试，也不能拿旧数据冒充。
        """
        last_note = ""

        for attempt in range(1, retries + 1):
            # 一条命令搞定。**先 rm**：dump 失败时文件不存在，cat 自然读不到东西，
            # 就不会把上一次的旧文件当成这次的结果。
            rc, out, err = self.run(
                ["shell", f"rm -f {self.remote_xml}; "
                          f"uiautomator dump {self.remote_xml} >/dev/null 2>&1; "
                          f"cat {self.remote_xml} 2>/dev/null"],
                timeout=30,
            )
            if rc == 0 and "<hierarchy" in out:
                self.last_dump_bytes = len(out)
                return out

            last_note = (out or "") + (err or "") or "没有返回任何内容"

            # 合并写法失败时，退回两步式再试一次 —— 至少能拿到更具体的报错
            rc2, out2, err2 = self.run(
                ["shell", "uiautomator", "dump", self.remote_xml], timeout=30)
            note2 = (out2 or "") + (err2 or "")
            if note2.strip():
                last_note = note2
            if rc2 == 0 and "ERROR" not in note2.upper():
                rc3, xml, _ = self.run(["exec-out", "cat", self.remote_xml], timeout=30)
                if rc3 == 0 and "<hierarchy" in xml:
                    return xml

            if attempt < retries:
                time.sleep(retry_wait)

        raise AdbError(
            "读取界面失败（无障碍树抓不到）。\n"
            f"      最后一次输出：{last_note.strip()[:200]}\n"
            "      常见原因：手机没解锁、屏幕是黑的、或者界面正在动画中"
        )

    def screencap(self):
        """截屏，返回 PNG 的 bytes；失败返回 None"""
        rc, data, err = self.run(["exec-out", "screencap", "-p"], timeout=30, binary=True)
        if rc == 0 and data[:8] == b"\x89PNG\r\n\x1a\n":
            return data
        return None

    def tap(self, x, y):
        """在 (x, y) 点一下。坐标就是无障碍树里给出的那一套，不需要换算。"""
        rc, out, err = self.run(["shell", "input", "tap", str(int(x)), str(int(y))], timeout=15)
        if rc != 0:
            raise AdbError(f"点击失败（{x},{y}）：{err.strip() or out.strip()}")

    def foreground_package(self):
        """
        快速取当前前台应用的包名。

        比 uiautomator dump 轻得多 —— 不启动手机上的 JVM、也不用等界面空闲，
        所以适合放在「每次按键都要过一遍」的快速通道上做护栏。

        取不到就返回 None。调用方必须退回完整的界面读取，绝不能猜。
        """
        for cmd in (["shell", "dumpsys", "window", "displays"],
                    ["shell", "dumpsys", "window"]):
            rc, out, _err = self.run(cmd, timeout=12)
            if rc != 0 or not out:
                continue
            for pattern in _FOCUS_PATTERNS:
                hit = pattern.search(out)
                if hit:
                    return hit.group(1)
        return None

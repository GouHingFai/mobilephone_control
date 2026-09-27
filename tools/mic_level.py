#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
mic_level.py —— 麦克风实时电平表

同时打开所有输入设备，实时显示每路的音量。
你对着麦克风说话，哪一行的柱子动，哪个就是你要用的麦克风。

比翻 Windows 设置看音量条省事：一次能看到全部设备，不用逐个点进去试。

用法：
    python tools/mic_level.py            默认跑 30 秒
    python tools/mic_level.py -t 60      跑 60 秒
    python tools/mic_level.py --list     只列设备，不测
"""

import argparse
import ctypes
import os
import sys
import threading
import time

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

BAR_WIDTH = 22
FULL_SCALE = 0.15   # RMS 到这个值算满格


def enable_ansi():
    """让 Windows 控制台支持 ANSI 转义序列。开了就能原地刷新，画面不闪。"""
    if os.name != "nt":
        return True
    try:
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
        mode = ctypes.c_uint32()
        if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            return False
        # ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
        return bool(kernel32.SetConsoleMode(handle, mode.value | 0x0004))
    except Exception:
        return False


USE_ANSI = enable_ansi()


def clear_screen():
    if USE_ANSI:
        sys.stdout.write("\033[2J\033[H")
    else:
        os.system("cls" if os.name == "nt" else "clear")
    sys.stdout.flush()


def bar(rms):
    """把 RMS 画成一条柱子。开平方是为了让小声也看得见变化。"""
    if rms <= 0:
        return " " * BAR_WIDTH
    norm = min(1.0, (rms / FULL_SCALE) ** 0.5)
    filled = int(round(norm * BAR_WIDTH))
    return "#" * filled + " " * (BAR_WIDTH - filled)


def main():
    ap = argparse.ArgumentParser(description="麦克风实时电平表")
    ap.add_argument("-t", "--seconds", type=float, default=30.0, help="监测时长（秒）")
    ap.add_argument("--list", action="store_true", help="只列设备，不测电平")
    args = ap.parse_args()

    try:
        import numpy as np
        import sounddevice as sd
    except ImportError as exc:
        print(f"[!!] 缺少依赖 {exc.name}，先跑 setup.bat")
        return 1

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import audio_io as aio

    devices = aio.list_input_devices()
    if not devices:
        print("[!!] 一个输入设备都没有。检查麦克风是否插好。")
        return 1

    if args.list:
        print()
        for idx, name, api, sr, ch in devices:
            tag = "   <<< 疑似虚拟设备" if aio.is_probably_virtual(name) else ""
            print(f"  [{idx}] {name}{tag}")
            print(f"        主机API={api}  默认采样率={sr}  输入通道={ch}")
        print()
        return 0

    # 每一路一个 stream，回调里更新电平
    levels = {}
    peaks = {}
    errors = {}
    streams = []
    lock = threading.Lock()
    name_by_idx = {d[0]: d[1] for d in devices}
    virtual_by_idx = {d[0]: aio.is_probably_virtual(d[1]) for d in devices}

    for idx, name, _api, _sr, _ch in devices:
        levels[idx] = 0.0
        peaks[idx] = 0.0

        samplerate, _ = aio.pick_samplerate(idx)

        def make_callback(i):
            def callback(indata, frames, time_info, status):
                rms = float(np.sqrt(np.mean(indata.astype("float64") ** 2)))
                with lock:
                    levels[i] = rms
                    if rms > peaks[i]:
                        peaks[i] = rms
            return callback

        try:
            st = sd.InputStream(
                samplerate=samplerate,
                channels=1,
                dtype="float32",
                device=idx,
                callback=make_callback(idx),
            )
            st.start()
            streams.append(st)
        except Exception as exc:  # noqa: BLE001
            errors[idx] = f"{type(exc).__name__}: {exc}"[:70]

    if not streams:
        print()
        print("[!!] 所有输入设备都打不开。这是 Windows 音频层的问题。")
        for idx, msg in errors.items():
            print(f"      [{idx}] {msg}")
        return 1

    print()
    print("  麦克风实时电平表")
    print("  >>> 现在对着麦克风说话。哪一行的柱子动，哪个就是你要用的麦克风。")
    print(f"  >>> 监测 {args.seconds:.0f} 秒，按 Ctrl+C 提前结束。")
    time.sleep(2.0)

    start = time.time()
    try:
        while time.time() - start < args.seconds:
            clear_screen()
            elapsed = time.time() - start
            print()
            print("  麦克风实时电平表")
            print("  >>> 对着麦克风说话，哪一行的柱子动，哪个就是你的麦克风")
            print(f"  >>> 已监测 {elapsed:.0f} / {args.seconds:.0f} 秒　（Ctrl+C 结束）")
            print()
            print(f"  {'设备':<42}{'当前电平':<26}{'峰值':>8}")
            print("  " + "-" * 76)

            with lock:
                snapshot = [(i, levels[i], peaks[i]) for i in levels]

            for idx, name, _api, _sr, _ch in devices:
                short = name[:38]
                if idx in errors:
                    print(f"  [{idx}] {short:<38} 打不开：{errors[idx][:30]}")
                    continue
                rms, pk = next(((r, p) for i, r, p in snapshot if i == idx), (0.0, 0.0))
                tag = " <<虚拟>>" if aio.is_probably_virtual(name) else ""
                print(f"  [{idx}] {short:<38} |{bar(rms)}| {rms:>7.4f}{tag}")

            print()
            print("  <<虚拟>> 的是虚拟声卡，录不到你的声音，别选它")

            # 找出当前电平最高的真实设备，给个明确结论
            live = [(i, r) for i, r, _p in snapshot
                    if i not in errors and r > 0.01 and not virtual_by_idx.get(i, False)]
            print()
            if live:
                best = max(live, key=lambda x: x[1])
                print(f"  >>> 检测到声音，最大的一路是设备 [{best[0]}]")
            else:
                print("  >>> 暂时没检测到明显声音")

            time.sleep(0.35)
    except KeyboardInterrupt:
        pass

    clear_screen()
    print()
    print("  ============ 最终结果 ============")
    print()

    report = ["麦克风电平测试 —— 最终结果", ""]
    report.append("设备清单：")
    for idx, name, api, sr, ch in devices:
        tag = "  <<虚拟>>" if aio.is_probably_virtual(name) else ""
        report.append(f"  [{idx}] {name}{tag}  (hostapi={api}, 默认采样率={sr}, 通道={ch})")
    report.append("")
    report.append("各路峰值：")

    real_moving = []
    for idx, name, _api, _sr, _ch in devices:
        virtual = aio.is_probably_virtual(name)
        if idx in errors:
            line = f"  [{idx}] {name}  打不开：{errors[idx]}"
            print("  " + line)
            report.append(line)
            continue

        pk = peaks.get(idx, 0.0)
        mark = "  <<虚拟>>" if virtual else ""
        if pk > 0.02:
            verdict = "  <-- 有声音"
            if not virtual:
                real_moving.append(idx)
        elif pk > 0.003:
            verdict = "  <-- 有微弱声音"
        else:
            verdict = "  <-- 几乎没声音"

        line = f"  [{idx}] {name}  峰值={pk:.4f}{mark}{verdict}"
        print("  " + line)
        report.append(line)

    print()
    report.append("")
    if real_moving:
        print(f"  >> 能录到你说话的真实设备：{real_moving}")
        print(f"  >> 建议在 config.yaml 里把 audio.input_device 设为 {real_moving[0]}")
        report.append(f"结论：能录到你说话的真实设备：{real_moving}")
        report.append(f"建议：config.yaml -> audio.input_device = {real_moving[0]}")
    elif peaks and any(p > 0.02 for p in peaks.values()):
        print("  >> 只有虚拟设备检测到声音，真实麦克风没反应。")
        report.append("结论：只有虚拟设备检测到声音，真实麦克风没反应。")
        for tip in [
            "设置 → 隐私和安全性 → 麦克风 → 打开「允许桌面应用访问麦克风」",
            "完全退出 ToDesk 等其他可能占用麦克风的程序",
            "USB 麦克风拔了重插，或换一个 USB 口",
            "声音设置 → 麦克风 → 属性 → 高级 → 取消「允许应用程序独占控制该设备」",
        ]:
            print(f"        - {tip}")
            report.append(f"  - {tip}")
    else:
        print("  >> 所有设备都没检测到声音。麦克风可能被静音、被禁用，或没插好。")
        report.append("结论：所有设备都没检测到声音。麦克风可能被静音、被禁用，或没插好。")
    print()

    # 结论落盘，方便事后排查（画面是实时刷新的，所以只存最终结果）
    try:
        log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "debug", "mic_level_log.txt")
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        with open(log_path, "w", encoding="utf-8") as fh:
            fh.write("\n".join(report) + "\n")
        print(f"  结论已存到: debug{os.sep}mic_level_log.txt")
        print()
    except Exception:
        pass

    for st in streams:
        try:
            st.abort()
            st.close()
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n  已中断。\n")
        sys.exit(130)

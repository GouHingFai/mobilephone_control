#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
mic_test.py —— 麦克风专项测试

probe.py 的麦克风标定卡住时，用这个脚本快速定位。
它只做一件事：把「能不能从麦克风拿到音频」这件事查清楚。

每一步都有超时，绝不会像 sd.wait() 那样无限等待。

用法：
    python tools/mic_test.py           测默认输入设备
    python tools/mic_test.py --all     把所有输入设备都试一遍
"""

import argparse
import sys
import time
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

OK = "[OK]"
BAD = "[!!]"
INFO = "[**]"
SKIP = "[--]"

_LOG_HANDLE = None


def set_log(path):
    """把输出同步写一份到文件，方便事后排查"""
    global _LOG_HANDLE
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        _LOG_HANDLE = open(path, "w", encoding="utf-8", buffering=1)
    except Exception:
        _LOG_HANDLE = None


def say(msg=""):
    print(msg, flush=True)
    if _LOG_HANDLE is not None:
        try:
            _LOG_HANDLE.write(str(msg) + "\n")
            _LOG_HANDLE.flush()
        except Exception:
            pass


def section(title):
    say()
    say("=" * 64)
    say("  " + title)
    say("=" * 64)


WINDOWS_TIPS = [
    "设置 → 隐私和安全性 → 麦克风 → 确认「允许桌面应用访问麦克风」是打开的",
    "设置 → 系统 → 声音 → 输入 → 确认选中的是你在用的麦克风，且音量不是 0",
    "关掉可能独占麦克风的程序（腾讯会议、钉钉、语音输入法、OBS 等）",
    "声音设置 → 麦克风 → 属性 → 高级 → 取消勾选「允许应用程序独占控制该设备」",
    "USB 麦克风换一个 USB 接口再试（前置面板接口常常供电不足）",
]


def main():
    ap = argparse.ArgumentParser(description="麦克风专项测试")
    ap.add_argument("--all", action="store_true", help="把所有输入设备都试一遍")
    ap.add_argument("--device", type=int, help="只测指定序号的设备")
    ap.add_argument("--seconds", type=float, default=1.5, help="每次试录的秒数")
    args = ap.parse_args()

    set_log(Path(__file__).resolve().parent.parent / "debug" / "mic_test_log.txt")

    say()
    say("  麦克风专项测试")
    say()

    try:
        import numpy  # noqa: F401
        import sounddevice  # noqa: F401
    except ImportError as exc:
        say(f"{BAD} 缺少依赖 {exc.name}，先跑 setup.bat 装好依赖")
        return 1

    import audio_io as aio

    # ---------------- 阶段 1：设备清单
    section("阶段 1 / 3   系统里的输入设备")

    try:
        devices = aio.list_input_devices()
    except Exception as exc:  # noqa: BLE001
        say(f"{BAD} 枚举音频设备失败: {type(exc).__name__}: {exc}")
        say("      这通常意味着 Windows 音频服务异常，或者 sounddevice 装坏了。")
        return 1

    if not devices:
        say(f"{BAD} 一个输入设备都没有。")
        say("      检查麦克风是否插好，以及 Windows 是否识别到了它。")
        return 1

    for idx, name, api, sr, ch in devices:
        tag = "   <<< 疑似虚拟设备，录不到你的声音" if aio.is_probably_virtual(name) else ""
        say(f"      [{idx}] {name}{tag}")
        say(f"          主机API={api}  默认采样率={sr}  输入通道={ch}")

    default_idx = aio.default_input_device()
    say()
    if default_idx is None:
        say(f"{BAD} 系统没有设置默认输入设备。")
        default_idx = devices[0][0]
        say(f"      先拿第一个设备 [{default_idx}] 来测。")
    else:
        say(f"{OK} 系统默认输入设备 = [{default_idx}] {aio.describe_device(default_idx)}")

    # ---------------- 阶段 2：逐个测试
    section("阶段 2 / 3   实际试录（每步都有超时保护）")

    if args.device is not None:
        targets = [args.device]
    elif args.all:
        targets = [d[0] for d in devices]
    else:
        targets = [default_idx]

    results = []
    for idx in targets:
        say()
        say(f"{INFO} 测试设备 [{idx}] {aio.describe_device(idx)}")

        # 采样率探测（非阻塞）
        ok16, err16 = aio.check_samplerate(idx, 16000)
        if ok16:
            say(f"      {OK} 支持 16000 Hz（Whisper 需要的采样率）")
            use_sr = 16000
        else:
            sr, _ = aio.pick_samplerate(idx)
            say(f"      {INFO} 不支持 16000 Hz，改用设备默认的 {sr} Hz 采集后重采样")
            say(f"           原因: {err16[:100]}")
            use_sr = sr

        say(f"      正在试录 {args.seconds:.1f} 秒，请保持安静 ...")
        t0 = time.time()
        ok, msg, rms = aio.quick_test(device=idx, samplerate=use_sr, seconds=args.seconds)
        elapsed = time.time() - t0

        if ok:
            say(f"      {OK} 成功（耗时 {elapsed:.1f} 秒）—— {msg}")
            results.append((idx, True, msg, rms))
        else:
            say(f"      {BAD} 失败（耗时 {elapsed:.1f} 秒）")
            say(f"           {msg}")
            results.append((idx, False, msg, 0.0))

    # ---------------- 阶段 3：结论
    section("阶段 3 / 3   结论")

    good = [r for r in results if r[1]]
    bad = [r for r in results if not r[1]]

    if good:
        say(f"{OK} 有 {len(good)} 个设备能正常录音：")
        for idx, _ok, msg, rms in good:
            say(f"      [{idx}] RMS={rms:.5f}  {msg}")
        say()
        best = good[0]
        say(f"  >> 建议在 config.yaml 里把 input_device 设成 {best[0]}")
        if bad:
            say()
            say(f"  另外 {len(bad)} 个设备失败，属于那些设备的自身问题，不影响使用：")
            for idx, _ok, msg, _ in bad:
                say(f"      [{idx}] {msg[:90]}")
        say()
        say("  下一步：把 config.yaml 的 input_device 设成上面建议的序号，")
        say("  然后重新跑 probe.bat 做标定。")
        return 0

    say(f"{BAD} 所有测试的设备都失败了。")
    say()
    say("  这不是代码问题，是 Windows 音频这一层的问题。按顺序排查：")
    say()
    for i, tip in enumerate(WINDOWS_TIPS, 1):
        say(f"      {i}. {tip}")
    say()
    say("  详细报错（贴给开发者时请带上这一段）：")
    for idx, _ok, msg, _ in bad:
        say(f"      [{idx}] {msg}")
    say()
    return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        say()
        say("  已中断。")
        sys.exit(130)

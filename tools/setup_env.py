#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
setup_env.py —— 安装 voice_tap 所需的全部依赖

用法：
    python tools/setup_env.py              用清华镜像安装（国内推荐，快很多）
    python tools/setup_env.py --no-mirror  用 PyPI 官方源
    python tools/setup_env.py --check      只检查现状，不安装任何东西

设计考虑：
  - 逐包安装，一个失败不影响后面的，最后统一报告
  - 装完逐个真实 import 验证，而不是只看 pip 说成功
  - 优先用国内镜像，否则 faster-whisper 那几个包会慢到让人以为卡死
"""

import argparse
import os
import platform
import shutil
import subprocess
import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

OK = "[OK]"
BAD = "[!!]"
INFO = "[**]"
SKIP = "[--]"

MIRROR = "https://pypi.tuna.tsinghua.edu.cn/simple"

# (pip 包名, import 名, 中文说明, 装起来大不大)
PACKAGES = [
    ("numpy",        "numpy",         "数值计算（其他包的基础）",   False),
    ("sounddevice",  "sounddevice",   "麦克风采集",                 False),
    ("pyyaml",       "yaml",          "读取 config.yaml",           False),
    ("pypinyin",     "pypinyin",      "拼音匹配（同音字容错）",     False),
    ("pillow",       "PIL",           "preview 模式画红圈",         False),
    ("keyboard",     "keyboard",      "全局热键 F8 / F9",           False),
    ("faster-whisper", "faster_whisper", "语音识别引擎（离线）",     True),
]


def say(msg=""):
    print(msg, flush=True)


def section(title):
    say()
    say("=" * 62)
    say("  " + title)
    say("=" * 62)


def run(cmd, timeout=900):
    """执行命令，返回 (returncode, 合并后的输出文本)"""
    # 自检：命令行里混进非字符串是低级但致命的错误（曾经真的发生过，
    # 把一个布尔值当成 pip 的镜像地址传了进去），这里直接拦下来并说清楚
    for i, a in enumerate(cmd):
        if not isinstance(a, str):
            return -997, (
                f"内部错误：命令第 {i} 个参数不是字符串，"
                f"而是 {type(a).__name__}（{a!r}）。完整命令：{cmd!r}"
            )

    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    try:
        p = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
            creationflags=creationflags,
        )
    except subprocess.TimeoutExpired:
        return -999, f"超时（{timeout} 秒）"
    except Exception as exc:  # noqa: BLE001
        return -998, f"{type(exc).__name__}: {exc}"
    return p.returncode, p.stdout.decode("utf-8", errors="replace")


def can_import(module_name):
    try:
        __import__(module_name)
        return True
    except ImportError:
        return False


# ---------------------------------------------------------------- 阶段一

def stage_overview():
    section("阶段 1 / 3   环境概览")
    info = {}

    py_ver = sys.version.split()[0]
    bits = 64 if sys.maxsize > 2 ** 32 else 32
    say(f"{OK} Python {py_ver}（{bits} 位）")
    say(f"      解释器位置: {sys.executable}")
    say(f"      系统: {platform.system()} {platform.release()}")
    info["python"] = py_ver

    major, minor = sys.version_info[:2]
    if (major, minor) < (3, 9):
        say(f"{BAD} Python 版本过低。本项目要求 3.9 或更高。")
        say("      请到 https://www.python.org/downloads/ 装个新版")
        info["blocked"] = True
        return info

    if (major, minor) >= (3, 13):
        say(f"{INFO} 你的 Python 是 {major}.{minor}。")
        say("      faster-whisper 依赖的 ctranslate2 对最新版 Python 的支持常常滞后。")
        say("      如果下面它装失败了，就是版本太新 —— 装个 Python 3.11 或 3.12 就好。")

    if bits == 32:
        say(f"{BAD} 检测到 32 位 Python。faster-whisper 需要 64 位，必定装不上。")
        info["blocked"] = True

    rc, out = run([sys.executable, "-m", "pip", "--version"], timeout=120)
    if rc == 0:
        say(f"{OK} pip: {out.strip().splitlines()[0]}")
    else:
        say(f"{BAD} pip 不可用: {out.strip()[:200]}")
        say("      试试: python -m ensurepip --upgrade")
        info["blocked"] = True

    # 机器上可能装了多个 Python，列出来，方便在版本不兼容时切换
    if os.name == "nt":
        rc, out = run(["py", "--list"], timeout=60)
        if rc == 0 and out.strip():
            others = [ln.strip() for ln in out.splitlines() if ln.strip()]
            say(f"{INFO} 这台机器上 py 启动器能看到的 Python：")
            for ln in others:
                say(f"      {ln}")
        else:
            say(f"{INFO} 未检测到 py 启动器（只装了单个 Python 时会这样，正常）")

    # 磁盘空间：依赖装在 Python 所在盘，Whisper 模型默认缓存到用户目录
    seen = set()
    for label, target in (("Python 安装盘", sys.prefix), ("用户目录", os.path.expanduser("~"))):
        try:
            drive = os.path.splitdrive(os.path.abspath(target))[0] or os.path.abspath(os.sep)
        except Exception:
            continue
        if drive in seen:
            continue
        seen.add(drive)
        try:
            usage = shutil.disk_usage(drive)
            free_gb = usage.free / (1024 ** 3)
            say(f"{OK} 可用磁盘空间（{label} {drive}）: {free_gb:.1f} GB")
            if free_gb < 4:
                say(f"{BAD} 空间偏紧。依赖加模型大约要 2 GB，建议先清理一下。")
        except Exception:
            pass

    say()
    say("  当前依赖状态：")
    info["installed"] = []
    info["missing"] = []
    for pkg, module, desc, _big in PACKAGES:
        if can_import(module):
            say(f"      {OK} {pkg:<16} {desc}")
            info["installed"].append(pkg)
        else:
            say(f"      {BAD} {pkg:<16} 缺失 —— {desc}")
            info["missing"].append(pkg)

    return info


# ---------------------------------------------------------------- 阶段二

def stage_install(info, use_mirror):
    section("阶段 2 / 3   安装依赖")

    if info.get("blocked"):
        say(f"{SKIP} 环境有阻塞问题，跳过安装。先解决上面标 [!!] 的问题。")
        return {}

    if not info["missing"]:
        say(f"{OK} 依赖都齐了，不用装。")
        return {}

    say(f"  需要安装 {len(info['missing'])} 个包。")
    if use_mirror:
        say(f"  使用镜像源: {MIRROR}")
    else:
        say("  使用 PyPI 官方源（国内可能很慢）")
    say()

    results = {}

    # pip 自己先升个级，老 pip 解析新包容易出问题
    say(f"{INFO} 先升级 pip ...")
    cmd = [sys.executable, "-m", "pip", "install", "--upgrade", "pip"]
    if use_mirror:
        cmd += ["-i", MIRROR]
    rc, out = run(cmd, timeout=300)
    say(f"      {'升级完成' if rc == 0 else '升级失败，继续用现有版本（一般没关系）'}")

    # 预检：faster-whisper 依赖若干带 C/Rust 扩展的底层库，
    # 在很新的 Python 上经常还没有预编译包。先干跑一次（不下载不安装），
    # 要么当场确认没问题，要么在浪费时间之前就告诉我们得换 Python 版本。
    preflight_ok = True
    if "faster-whisper" in info["missing"]:
        say()
        ver = f"{sys.version_info.major}.{sys.version_info.minor}"
        say(f"{INFO} 预检 faster-whisper 是否有适配 Python {ver} 的预编译包 ...")
        cmd = [sys.executable, "-m", "pip", "install", "--dry-run", "faster-whisper"]
        if use_mirror:
            cmd += ["-i", MIRROR]
        rc, out = run(cmd, timeout=300)
        if rc == 0:
            say(f"{OK} 预检通过，有可用的包，继续安装")
        else:
            preflight_ok = False
            say(f"{BAD} 预检失败 —— faster-whisper 装不上。")
            lines = [l for l in out.strip().splitlines() if l.strip()]
            for line in lines[-6:]:
                say("      " + line.strip()[:150])
            say()
            say(f"      这是最典型的情况：Python {ver} 太新，底层库还没出对应版本的预编译包。")
            say("      解决办法是装一个 Python 3.12（兼容性最好），然后用它来跑：")
            say("          ① 到 https://www.python.org/downloads/release/python-3129/ 下载安装")
            say("          ② 然后运行:  py -3.12 tools\\setup_env.py")
            say()
            say("      其余几个包不受影响，会照常安装。")

    say()
    for pkg, module, desc, big in PACKAGES:
        if pkg not in info["missing"]:
            continue

        if pkg == "faster-whisper" and not preflight_ok:
            say()
            say(f"{SKIP} 跳过 {pkg} —— 预检已确认装不上，原因和解决办法见上面")
            results[pkg] = "fail"
            continue

        say()
        if big:
            say(f"{INFO} 正在安装 {pkg} —— {desc}")
            say("      这个包比较大（含识别引擎），慢一点是正常的，别关窗口")
        else:
            say(f"{INFO} 正在安装 {pkg} —— {desc}")

        cmd = [sys.executable, "-m", "pip", "install", pkg]
        if use_mirror:
            cmd += ["-i", MIRROR]

        t0 = time.time()
        rc, out = run(cmd, timeout=900)
        elapsed = time.time() - t0

        if rc == 0 and can_import(module):
            say(f"{OK} {pkg} 安装成功（{elapsed:.0f} 秒）")
            results[pkg] = "ok"
        else:
            say(f"{BAD} {pkg} 安装失败（{elapsed:.0f} 秒，退出码 {rc}）")
            lines = [l for l in out.strip().splitlines() if l.strip()]
            for line in lines[-8:]:
                say("      " + line.strip()[:150])
            results[pkg] = "fail"

            if "No matching distribution" in out or "Could not find a version" in out:
                say()
                ver = f"{sys.version_info.major}.{sys.version_info.minor}"
                say(f"      ^ 没有适配 Python {ver} 的预编译版本。")
                say(f"        {pkg} 依赖带 C/Rust 扩展的底层库，新出的 Python 往往要等几个月才有 wheel。")
                say("        最省事的办法：装一个 Python 3.12，然后指定用它来跑本脚本：")
                say("            py -3.12 tools\\setup_env.py")
            if "Read timed out" in out or "Connection" in out or "timed out" in out:
                say()
                say("      ^ 这是网络问题。可以换 --no-mirror 试试官方源，或者反向操作。")

    return results


# ---------------------------------------------------------------- 阶段三

def stage_verify(results):
    section("阶段 3 / 3   验证")

    ok_list, fail_list = [], []
    for pkg, module, desc, _big in PACKAGES:
        if can_import(module):
            ok_list.append(pkg)
        else:
            fail_list.append(pkg)

    say(f"  可用 {len(ok_list)} / {len(PACKAGES)}")
    say()

    for pkg, module, desc, _big in PACKAGES:
        mark = OK if pkg in ok_list else BAD
        say(f"      {mark} {pkg:<16} {desc}")

    say()
    if not fail_list:
        say(f"{OK} 全部就绪。")
        say()
        say("  下一步：再跑一次探测脚本，这次把麦克风标定做完")
        say("      双击 setup 旁边那个 probe.bat")
        say("      或者直接: python tools\\probe.py --skip-screen")
        say("      （--skip-screen 是因为界面数据我们已经拿到了，不用重复测）")
    else:
        say(f"{BAD} 还差这些: {', '.join(fail_list)}")
        say()
        if "faster-whisper" in fail_list:
            say("  faster-whisper 装不上时，优先怀疑 Python 版本。")
            say("  请把上面的报错贴给开发者，或者直接装个 Python 3.11 再跑一次本脚本。")
        say()
        say("  可以单独重试某个包，例如：")
        say(f"      python -m pip install {fail_list[0]} -i {MIRROR}")

    say()
    return fail_list


def main():
    ap = argparse.ArgumentParser(description="安装 voice_tap 依赖")
    ap.add_argument("--no-mirror", action="store_true", help="用 PyPI 官方源")
    ap.add_argument("--check", action="store_true", help="只检查，不安装")
    args = ap.parse_args()

    say()
    say("  voice_tap —— 依赖安装")
    say()

    info = stage_overview()

    if args.check:
        section("结束")
        say("  这是 --check 模式，没有安装任何东西。")
        say("  去掉 --check 再跑一次即可真正安装。")
        return 0

    results = stage_install(info, use_mirror=not args.no_mirror)
    fail = stage_verify(results)

    say()
    say("  安装流程结束。")
    say()
    return 1 if fail else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        say()
        say("  已中断。已装好的包不会丢，可以重跑本脚本继续。")
        sys.exit(130)

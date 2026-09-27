#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
probe.py —— 声控手机助手（voice_tap）环境探测脚本

在写主程序之前，先用真实数据验证三件事：

  1. adb 能不能连上手机
  2. 【生死线】GRE3000 的界面能不能被无障碍树（uiautomator）读到
     如果读不到，整套"定位文字并点击"的方案就要改成 OCR 优先，设计得推翻重来
  3. 麦克风的实际噪声水平，用来标定静音检测阈值

用法：
    python tools/probe.py                跑 环境 + 界面 + 麦克风标定
    python tools/probe.py --asr          额外跑语音识别自检（会下载约 480MB 模型）
    python tools/probe.py --adb "D:\\x\\adb.exe"
    python tools/probe.py --outdir "D:\\somewhere"

所有结果写入 debug/probe_<时间戳>/ 目录。其中 SUMMARY.md 是给开发者看的摘要，
把这个文件连同 ui_dump.xml 一起发出去，就能确证后续方案。
"""

import argparse
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------- 控制台输出

# Windows 中文控制台默认是 GBK，打印 UTF-8 会乱码甚至抛异常
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

OK = "[OK]"
BAD = "[!!]"
SKIP = "[--]"
INFO = "[**]"

# 麦克风全军覆没时的排查清单（这是 Windows 音频层的问题，不是代码问题）
MIC_TIPS = [
    "设置 → 隐私和安全性 → 麦克风 → 确认「允许桌面应用访问麦克风」是打开的",
    "设置 → 系统 → 声音 → 输入 → 确认选中的是你在用的麦克风，且音量不是 0",
    "关掉可能独占麦克风的程序（腾讯会议、钉钉、语音输入法、OBS 等）",
    "声音设置 → 麦克风 → 属性 → 高级 → 取消勾选「允许应用程序独占控制该设备」",
    "USB 麦克风换一个 USB 接口再试（前置面板接口常常供电不足）",
]

_LOG_HANDLE = None


def set_log(path):
    """把控制台输出同步写一份到文件，这样即使窗口被关掉也能找回现场"""
    global _LOG_HANDLE
    try:
        _LOG_HANDLE = open(path, "w", encoding="utf-8", buffering=1)
    except Exception:
        _LOG_HANDLE = None


def say(msg=""):
    """同时打印到控制台并写入日志文件"""
    print(msg, flush=True)
    if _LOG_HANDLE is not None:
        try:
            _LOG_HANDLE.write(str(msg) + "\n")
            _LOG_HANDLE.flush()
        except Exception:
            pass


def section(title):
    say()
    say("=" * 62)
    say("  " + title)
    say("=" * 62)


def show_cmd_failure(rc, out, err, hint=""):
    say(f"{BAD} 命令退出码 = {rc}")
    tail = (err or out or "").strip().splitlines()
    for line in tail[-6:]:
        say("      " + line.strip())
    if hint:
        say("      " + hint)


# ---------------------------------------------------------------- adb 定位

# scrcpy 发行版一定自带 adb.exe，这是最可能的来源
ADB_HINTS = [
    r"H:\scrcpy-win64-v4.1\adb.exe",
    r"H:\scrcpy-win64-*\adb.exe",
    r"C:\platform-tools\adb.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Android\Sdk\platform-tools\adb.exe"),
    os.path.expandvars(r"%USERPROFILE%\platform-tools\adb.exe"),
]


def find_adb(explicit=None):
    """按优先级找出可用的 adb.exe，返回路径或 None"""
    tried = []

    if explicit:
        tried.append(explicit)
        if Path(explicit).is_file():
            return explicit

    env_adb = os.environ.get("ADB")
    if env_adb:
        tried.append(env_adb)
        if Path(env_adb).is_file():
            return env_adb

    for hint in ADB_HINTS:
        for path in sorted(glob.glob(hint)):
            tried.append(path)
            if Path(path).is_file():
                return path

    found = shutil.which("adb")
    if found:
        return found

    say(f"{BAD} 没找到 adb.exe，找过这些位置：")
    for t in tried:
        say("      " + t)
    say("      PATH 里也没有 adb")
    say("      可以用 --adb \"完整路径\" 手动指定")
    return None


def run_adb(adb, args, timeout=20):
    """执行一条 adb 命令，返回 (returncode, stdout_text, stderr_text)"""
    cmd = [adb] + args
    creationflags = 0
    if os.name == "nt":
        # 避免每次调用都闪出一个黑窗口
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        p = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            creationflags=creationflags,
        )
    except subprocess.TimeoutExpired:
        return -999, "", f"命令超时（{timeout}s）: {' '.join(args)}"
    except FileNotFoundError:
        return -998, "", f"找不到可执行文件: {adb}"
    except Exception as exc:  # noqa: BLE001
        return -997, "", f"{type(exc).__name__}: {exc}"

    out = p.stdout.decode("utf-8", errors="replace")
    err = p.stderr.decode("utf-8", errors="replace")
    return p.returncode, out, err


def run_adb_bin(adb, args, timeout=20):
    """执行 adb 命令并返回原始 bytes（给 screencap 用）"""
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    try:
        p = subprocess.run(
            [adb] + args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            creationflags=creationflags,
        )
    except Exception as exc:  # noqa: BLE001
        return None, f"{type(exc).__name__}: {exc}"
    return p.stdout, p.stderr.decode("utf-8", errors="replace")


# 麦克风标定阶段实测选出来的设备序号，供语音识别阶段复用。
# 不能想当然地用「系统默认设备」—— 实测下来默认设备恰恰可能是坏的那个。
_PREFERRED_AUDIO_DEVICE = None

# 命令行 --device 强制指定的输入设备；指定了就不再自动挑
_FORCE_DEVICE = None


def _resolve_audio_device(log=say):
    """返回一个确认可用的输入设备序号；全局已选过就直接复用。"""
    global _PREFERRED_AUDIO_DEVICE
    if _PREFERRED_AUDIO_DEVICE is not None:
        return _PREFERRED_AUDIO_DEVICE

    import audio_io as aio
    if _FORCE_DEVICE is not None:
        _PREFERRED_AUDIO_DEVICE = _FORCE_DEVICE
        return _FORCE_DEVICE

    log(f"{INFO} 正在实测输入设备，找一个真正能录到音频的 ...")
    device, _sr = aio.pick_working_device(log=log)
    _PREFERRED_AUDIO_DEVICE = device
    return device


def load_config_device():
    """从 config.yaml 读 audio.input_device。读不到就返回 None（走自动挑选）。"""
    path = Path(__file__).resolve().parent.parent / "config.yaml"
    if not path.is_file():
        return None
    try:
        import yaml
        with open(path, encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
        value = (data.get("audio") or {}).get("input_device")
        return int(value) if value is not None else None
    except Exception as exc:  # noqa: BLE001
        say(f"{SKIP} 读 config.yaml 失败（{type(exc).__name__}: {exc}），改用自动挑选设备")
        return None


# ---------------------------------------------------------------- 阶段一：环境

def stage_env(adb, outdir):
    section("阶段 1 / 4   环境自检")
    result = {}

    say(f"{OK} Python {sys.version.split()[0]}  ({sys.executable})")
    result["python"] = sys.version.split()[0]

    if sys.version_info < (3, 9):
        say(f"{BAD} Python 版本过低，本项目要求 3.9 或更高")

    deps = [
        ("faster_whisper", "faster-whisper", "语音识别（必需）"),
        ("sounddevice", "sounddevice", "麦克风采集（必需）"),
        ("numpy", "numpy", "数值计算（必需）"),
        ("keyboard", "keyboard", "全局热键（热键模式必需）"),
        ("yaml", "pyyaml", "读取 config.yaml（必需）"),
        ("PIL", "pillow", "preview 画红圈（调试用）"),
    ]
    say()
    say("  依赖检查：")
    installed, missing = [], []
    for module, pkg, desc in deps:
        try:
            __import__(module)
            say(f"      {OK} {pkg:<16} {desc}")
            installed.append(pkg)
        except ImportError:
            say(f"      {BAD} {pkg:<16} 未安装 —— {desc}")
            missing.append(pkg)
    result["installed_packages"] = installed
    result["missing_packages"] = missing

    if missing:
        say()
        say("  装齐依赖（复制粘贴到命令行）：")
        say(f"      python -m pip install {' '.join(missing)}")

    say()
    say(f"{OK} 找到 adb: {adb}")
    result["adb_path"] = adb

    rc, out, err = run_adb(adb, ["version"])
    if rc == 0:
        first = out.strip().splitlines()[0] if out.strip() else "?"
        say(f"      {first}")
        result["adb_version"] = first
    else:
        show_cmd_failure(rc, out, err, "adb 本身能启动吗？试试直接双击运行它")

    # 设备连接
    say()
    rc, out, err = run_adb(adb, ["devices", "-l"], timeout=30)
    if rc != 0:
        show_cmd_failure(rc, out, err)
        result["devices"] = []
        return result

    devices = []
    for line in out.splitlines()[1:]:
        line = line.strip()
        if not line or line.startswith("*"):
            continue
        parts = line.split()
        if len(parts) >= 2:
            devices.append({"serial": parts[0], "state": parts[1], "raw": line})

    result["devices"] = devices

    if not devices:
        say(f"{BAD} 没检测到任何设备。请检查：")
        say("      1. 手机用数据线连着电脑，且是「传输文件 / MTP」模式（不是「仅充电」）")
        say("      2. 开发者选项里打开了「USB 调试」")
        say("      3. 手机上弹出的「允许 USB 调试」授权框点了「允许」")
        say("      4. 如果 scrcpy 能正常投屏，那 adb 一定是通的，重点看上面的报错")
        return result

    online = [d for d in devices if d["state"] == "device"]
    if not online:
        say(f"{BAD} 检测到设备但状态不是 device（常见是 unauthorized / offline）：")
        for d in devices:
            say("      " + d["raw"])
        say("      解决办法：拔插数据线，在手机上重新确认授权；或执行 adb kill-server 后重试")
        return result

    say(f"{OK} 已连接设备 {online[0]['serial']}")

    props = {
        "型号": "ro.product.model",
        "品牌": "ro.product.brand",
        "Android 版本": "ro.build.version.release",
        "SDK": "ro.build.version.sdk",
    }
    result["device"] = {}
    for label, prop in props.items():
        rc, out, err = run_adb(adb, ["shell", "getprop", prop])
        val = out.strip() if rc == 0 else "?"
        result["device"][label] = val
        say(f"      {label}: {val}")

    rc, out, _ = run_adb(adb, ["shell", "wm", "size"])
    size = out.strip().replace("Physical size:", "").strip() if rc == 0 else "?"
    result["screen_size_raw"] = size
    say(f"      屏幕分辨率: {size}")

    rc, out, _ = run_adb(adb, ["shell", "wm", "density"])
    density = out.strip().replace("Physical density:", "").strip() if rc == 0 else "?"
    result["screen_density_raw"] = density
    say(f"      屏幕密度: {density}")

    return result


# ---------------------------------------------------------------- XML 解析

BOUNDS_RE = re.compile(r"\[(-?\d+),(-?\d+)\]\[(-?\d+),(-?\d+)\]")


def parse_bounds(text):
    """把 "[x1,y1][x2,y2]" 解析成 (x1, y1, x2, y2)，失败返回 None"""
    if not text:
        return None
    m = BOUNDS_RE.search(text)
    if not m:
        return None
    return tuple(int(g) for g in m.groups())


def node_center(bounds):
    if not bounds:
        return None
    x1, y1, x2, y2 = bounds
    return ((x1 + x2) // 2, (y1 + y2) // 2)


def build_parent_map(root):
    parents = {}
    stack = [root]
    while stack:
        cur = stack.pop()
        for child in list(cur):
            parents[id(child)] = cur
            stack.append(child)
    return parents


def find_clickable_ancestor(node, parents):
    """
    从 node 自身开始向上找最近的可点击祖先。
    返回 (可点击节点, 上溯层数)；找不到返回 (None, -1)。
    层数 0 表示节点自己就可点击。
    """
    cur = node
    hops = 0
    while cur is not None:
        if cur.get("clickable") == "true":
            return cur, hops
        cur = parents.get(id(cur))
        hops += 1
    return None, -1


def point_in_bounds(point, bounds):
    """判断一个点是否落在 bounds 矩形内（含边界）"""
    if not point or not bounds:
        return False
    x, y = point
    x1, y1, x2, y2 = bounds
    return x1 <= x <= x2 and y1 <= y <= y2


def resolve_click_target(text_bounds, anc_bounds):
    """
    决定到底该点哪里。

    优先用文字节点自己的中心 —— 只要它落在可点击祖先的范围内就很精确。
    只有文字中心不在可点范围内（少见）才退而用祖先中心。
    这样避免了「大容器套小图标」时点到容器正中间（离图标很远）的问题。
    """
    text_center = node_center(text_bounds)
    anc_center = node_center(anc_bounds)

    if text_center and anc_bounds and point_in_bounds(text_center, anc_bounds):
        return text_center
    if anc_center:
        return anc_center
    return text_center


def make_entry(node, depth, parents):
    """把一个 XML 节点整理成结构化字典"""
    text = (node.get("text") or "").strip()
    desc = (node.get("content-desc") or "").strip()
    bounds = parse_bounds(node.get("bounds"))

    entry = {
        "depth": depth,
        "text": text,
        "content_desc": desc,
        "class": node.get("class", ""),
        "resource_id": node.get("resource-id", ""),
        "package": node.get("package", ""),
        "bounds": bounds,
        "center": node_center(bounds),
        "clickable_self": node.get("clickable") == "true",
        "clickable": node.get("clickable"),
        "enabled": node.get("enabled"),
        "scrollable": node.get("scrollable"),
        "focusable": node.get("focusable"),
    }

    if text or desc:
        anc, hops = find_clickable_ancestor(node, parents)
        anc_bounds = parse_bounds(anc.get("bounds")) if anc is not None else None
        entry["click_ancestor_hops"] = hops if anc is not None else -1
        entry["click_ancestor_bounds"] = anc_bounds
        entry["click_ancestor_center"] = node_center(anc_bounds)
        entry["click_ancestor_class"] = anc.get("class", "") if anc is not None else ""
        entry["click_ancestor_resid"] = anc.get("resource-id", "") if anc is not None else ""
        # 这才是最终该点的坐标
        entry["click_target_center"] = resolve_click_target(bounds, anc_bounds) if anc is not None else node_center(bounds)
    else:
        entry["click_ancestor_hops"] = None
        entry["click_target_center"] = None

    return entry


def collect_nodes(root):
    """把整棵树按文档顺序摊平成结构化列表，每个节点带上「实际点击目标」信息"""
    parents = build_parent_map(root)
    nodes = []

    def visit(cur, depth):
        for child in list(cur):
            nodes.append(make_entry(child, depth, parents))
            visit(child, depth + 1)

    visit(root, 0)
    return nodes


# ---------------------------------------------------------------- 阶段二：界面

def stage_screen(adb, outdir):
    section("阶段 2 / 4   界面读取能力（这是整套方案的生死线）")
    result = {"dump_ok": False, "nodes": []}

    xml_path = outdir / "ui_dump.xml"
    png_path = outdir / "screen.png"

    # --- 截屏（独立于 dump，先做，失败了也不影响）
    say("正在截屏 ...")
    raw, err = run_adb_bin(adb, ["exec-out", "screencap", "-p"], timeout=30)
    if raw and raw[:8] == b"\x89PNG\r\n\x1a\n":
        png_path.write_bytes(raw)
        say(f"{OK} 截图已保存: {png_path.name}  ({len(raw) // 1024} KB)")
        result["screenshot"] = str(png_path)
    else:
        say(f"{BAD} 截屏失败: {err or '返回内容不是 PNG'}")
        result["screenshot"] = None

    # --- uiautomator dump，失败自动重试
    say()
    say("正在读取无障碍树 (uiautomator dump) ...")
    remote = "/sdcard/voice_tap_probe.xml"
    xml_text = ""
    last_note = ""
    for attempt in range(1, 4):
        rc, out, err = run_adb(adb, ["shell", "uiautomator", "dump", remote], timeout=30)
        last_note = ((out or "") + (err or "")).strip()

        if rc == 0 and "ERROR" not in last_note.upper():
            # 优先用 exec-out cat 直接拿回内容，少一次往返
            rc2, out2, _ = run_adb(adb, ["exec-out", "cat", remote], timeout=30)
            if "<hierarchy" in (out2 or ""):
                xml_text = out2
                break
            # 退一步用 pull
            run_adb(adb, ["pull", remote, str(xml_path)], timeout=30)
            if xml_path.is_file():
                xml_text = xml_path.read_text(encoding="utf-8", errors="replace")
                if "<hierarchy" in xml_text:
                    break

        say(f"      第 {attempt} 次尝试未成功: {last_note[:120]}")
        if attempt < 3:
            say("      界面可能在动画中，等 0.4 秒重试 ...")
            time.sleep(0.4)

    if "<hierarchy" not in xml_text:
        say(f"{BAD} 读不到无障碍树。最后一次输出：")
        say("      " + last_note[:300])
        say("      可能原因：手机没解锁、屏幕是黑的、或该界面禁止无障碍读取。")
        say("      请把手机解锁并停留在 GRE3000 的答题界面上，再重跑一次。")
        return result

    xml_path.write_text(xml_text, encoding="utf-8")
    say(f"{OK} 无障碍树已保存: {xml_path.name}  ({len(xml_text) // 1024} KB)")
    result["dump_ok"] = True

    # --- 解析
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        say(f"{BAD} XML 解析失败: {exc}")
        return result

    result["rotation"] = root.get("rotation")

    def root_attr(name):
        """<hierarchy> 本身通常没有这些属性，往下找第一个有值的节点"""
        v = root.get(name)
        if v:
            return v
        for n in root.iter():
            v = n.get(name)
            if v:
                return v
        return ""

    result["root_package"] = root_attr("package")

    root_bounds = parse_bounds(root.get("bounds"))
    if root_bounds is None:
        for child in list(root):
            root_bounds = parse_bounds(child.get("bounds"))
            if root_bounds:
                break
    result["root_bounds"] = root_bounds

    nodes = collect_nodes(root)
    result["nodes"] = nodes
    (outdir / "nodes.json").write_text(
        json.dumps(nodes, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    with_text = [n for n in nodes if n["text"]]
    with_desc = [n for n in nodes if n["content_desc"]]
    clickable_text = [n for n in with_text if n.get("click_ancestor_hops", -1) >= 0]

    say()
    say(f"      前台 App 包名: {result['root_package'] or '(读不到)'}")
    say(f"      节点总数: {len(nodes)}")
    say(f"      带 text 的节点: {len(with_text)}")
    say(f"      带 content-desc 的节点: {len(with_desc)}")
    say(f"      能追溯到可点击目标的文字节点: {len(clickable_text)}")

    # --- 判定
    #
    # 重要教训（2026-09-26 实测得出）：
    # 不要拿 clickable 标记当必要条件。很多 App（尤其 RecyclerView 列表）不设这个标记，
    # 点击由容器统一处理，但 adb input tap 注入的是真实触摸事件，照样有效。
    # 真正的判据是「能读到多少带坐标的文字节点」。
    say()
    if len(with_text) >= 3:
        say(f"{OK} 判定：无障碍树可用。可以用「精确坐标点击」方案，快且准。")
        result["verdict"] = "uiautomator_ok"
        if len(clickable_text) < 3:
            say("      注意：可点击节点很少，但这不代表不能用 —— 见下方说明。")
    elif len(with_text) >= 1:
        say(f"{BAD} 判定：只读到 {len(with_text)} 个文字节点，太少了。")
        say("      界面大概率是自绘的（Flutter / Canvas / 游戏引擎），文字信息不完整。")
        say("      需要看下面的节点清单，或考虑改用 OCR 方案。")
        result["verdict"] = "few_text_maybe_ocr"
    else:
        say(f"{BAD} 判定：无障碍树是空的，这是自绘界面。")
        say("      结论：「精确坐标点击」方案不成立，必须改成 OCR 识别截图。")
        result["verdict"] = "empty_need_ocr"

    if result["verdict"] == "uiautomator_ok" and len(clickable_text) < 3:
        say()
        say(f"{INFO} 关于「可点击节点只有 {len(clickable_text)} 个」这件事：")
        say("      clickable 标记只影响无障碍工具，不影响真实触摸事件。")
        say("      很多 App 的列表项不设这个标记，点击由容器（如 RecyclerView）统一处理，")
        say("      但 `adb shell input tap x y` 注入的是真实触摸，照样能点中。")
        say("      判断能否点击，看的是文字有没有坐标，不是看 clickable。")

    # --- 文字节点清单（含上溯信息）
    say()
    say("  ---- 全部文字节点（按屏幕从上到下）----")
    if not with_text and not with_desc:
        say("      （一个都没有）")

    ordered = sorted(
        with_text + [n for n in with_desc if n not in with_text],
        key=lambda n: (n["center"][1] if n["center"] else 10**9),
    )
    for n in ordered:
        label = n["text"] or f"<desc:{n['content_desc']}>"
        cy = n["center"][1] if n["center"] else -1
        hops = n.get("click_ancestor_hops", -1)
        if hops == 0:
            mark = "可点(自身)"
        elif hops > 0:
            mark = f"可点(上溯{hops}层)"
        else:
            mark = "不可点"
        target = n.get("click_target_center")
        tgt = f" -> 点({target[0]},{target[1]})" if target else ""
        say(f"      y={cy:<6} {mark:<14} {label[:44]!r}{tgt}")

    # --- 下半屏的可点击项（大概率就是选择题选项）
    height = root_bounds[3] - root_bounds[1] if root_bounds else 0
    if height:
        lower = [n for n in ordered if n["center"] and n["center"][1] > height * 0.4
                 and n.get("click_ancestor_hops", -1) >= 0]
        say()
        say(f"  ---- 下半屏可点击文字（屏幕高 {height}，很可能是选项）----")
        if not lower:
            say("      （没有）")
        for n in lower:
            target = n.get("click_target_center")
            tgt = f" -> 点({target[0]},{target[1]})" if target else ""
            say(f"      {(n['text'] or n['content_desc'])[:40]!r}{tgt}")

    # --- 一个可点击节点的完整信息，方便写解析器
    if clickable_text:
        sample = clickable_text[len(clickable_text) // 2]
        say()
        say("  ---- 抽一个可点击文字节点的完整字段（开发者用来写解析器）----")
        for key in (
            "text", "content_desc", "class", "resource_id", "package",
            "bounds", "center", "clickable_self", "click_ancestor_hops",
            "click_ancestor_class", "click_ancestor_resid",
            "click_ancestor_bounds", "click_target_center",
        ):
            say(f"      {key} = {sample.get(key)!r}")

    # --- 层级结构预览
    say()
    say("  ---- 界面层级速览（缩进表示嵌套，只显示有文字的节点）----")
    shown = 0
    for n in nodes:
        if not (n["text"] or n["content_desc"]):
            continue
        if shown >= 40:
            say("      ...（省略）")
            break
        indent = "  " * min(n["depth"], 12)
        label = n["text"] or f"<desc:{n['content_desc']}>"
        say(f"      {indent}{label[:36]}")
        shown += 1

    return result


# ---------------------------------------------------------------- 阶段三：麦克风

def stage_mic(outdir):
    global _PREFERRED_AUDIO_DEVICE

    section("阶段 3 / 4   麦克风标定（用来定静音检测阈值）")
    result = {"ok": False}

    try:
        import numpy as np
        import audio_io as aio
    except ImportError as exc:
        say(f"{SKIP} 跳过：缺少依赖 {exc.name}")
        say("      装好后再跑：python -m pip install sounddevice numpy")
        return result

    # 设备选择：先验证指定的那个，不通就退回自动挑选
    device = None
    sr = None

    if _FORCE_DEVICE is not None:
        candidate = _FORCE_DEVICE
        cand_sr, _ = aio.pick_samplerate(candidate)
        say(f"{INFO} 使用指定设备 [{candidate}]：{aio.describe_device(candidate)}")
        ok, msg, _rms = aio.quick_test(device=candidate, samplerate=cand_sr, seconds=0.6)
        if ok:
            say(f"{OK} 该设备实测可以录到音频，采样率 {cand_sr} Hz")
            device, sr = candidate, cand_sr
        else:
            say(f"{BAD} 指定设备实测不通：{msg}")
            say(f"{INFO} 退回自动挑选 —— 可能它被拔了、被禁用了，或者序号变了")

    if device is None:
        say(f"{INFO} 正在实测各个输入设备，找一个真正能录到音频的 ...")
        try:
            device, sr = aio.pick_working_device(log=say)
        except Exception as exc:  # noqa: BLE001
            say(f"{BAD} 枚举音频设备失败: {type(exc).__name__}: {exc}")
            say("      检查 Windows 设置 → 隐私和安全性 → 麦克风，是否允许桌面应用使用麦克风")
            return result

    if device is None:
        say()
        say(f"{BAD} 所有输入设备都录不到音频。")
        say("      这不是代码问题，是 Windows 音频这一层的问题。按顺序排查：")
        say()
        for i, tip in enumerate(MIC_TIPS, 1):
            say(f"      {i}. {tip}")
        say()
        say("      或者跑更详细的诊断：python tools\\mic_test.py --all")
        return result

    say(f"{OK} 选用设备 [{device}]，采样率 {sr} Hz")
    if sr == aio.TARGET_SR:
        say("      该设备原生支持 16000 Hz，不需要重采样")
    else:
        say("      该设备不支持 16000 Hz，采集后会重采样（对识别精度影响很小）")
    _PREFERRED_AUDIO_DEVICE = device
    result["device_index"] = device
    result["capture_samplerate"] = sr

    def grab(seconds):
        data, actual = aio.record(seconds, device=device, samplerate=sr)
        return aio.resample_to_16k(data, actual)

    # --- 底噪
    say()
    say("  请保持安静，测量环境底噪（2 秒）...")
    try:
        noise = grab(2.0)
    except Exception as exc:  # noqa: BLE001
        say(f"{BAD} 录音失败：{exc}")
        say()
        say("  这大概率不是代码问题，是音频设备这一层的问题。")
        say("  先跑这个专项测试把所有设备都试一遍：")
        say("      python tools\\mic_test.py --all")
        return result

    noise_rms = float(np.sqrt(np.mean(noise.astype("float64") ** 2)))
    say(f"{OK} 环境底噪 RMS = {noise_rms:.5f}")

    # --- 语音
    say()
    say("  现在请说一个词，中文或英文都行（说完停一下）")
    say("      建议说个中文词，比如「清晰」或「简单」—— 那才是实际使用场景")
    for i in range(3, 0, -1):
        say(f"      {i} ...")
        time.sleep(1)
    say("      开始说！")
    try:
        speech = grab(3.0)
    except Exception as exc:  # noqa: BLE001
        say(f"{BAD} 录音失败：{exc}")
        return result

    # 按 10ms 一帧算 RMS
    frame_len = int(0.01 * len(speech) / 3.0) or 160
    frames = [speech[i:i + frame_len] for i in range(0, len(speech) - frame_len, frame_len)]
    rms_per_frame = (
        np.array([float(np.sqrt(np.mean(f.astype("float64") ** 2))) for f in frames])
        if frames else np.array([0.0])
    )

    peak = float(rms_per_frame.max())
    p90 = float(np.percentile(rms_per_frame, 90))
    say(f"{OK} 语音最大帧 RMS = {peak:.5f}")
    say(f"      语音 90 分位 RMS = {p90:.5f}")

    # 阈值定在「底噪」和「语音」之间、偏向底噪一侧。
    #
    # 不用「底噪的固定倍数」是因为：底噪一旦测虚（例如录到的其实是系统播放声），
    # 倍数法会给出一个比人声还高的荒谬阈值，最后什么都不触发。
    span = max(p90 - noise_rms, 0.0)
    suggested = noise_rms + 0.35 * span
    suggested = max(suggested, noise_rms * 1.8, 0.004)   # 不能低于底噪太多
    suggested = min(suggested, max(peak * 0.7, 0.004))   # 也不能高过语音峰值

    # 底噪高得反常通常意味着设备选错了
    if noise_rms > 0.05:
        say()
        say(f"{BAD} 底噪高得反常（{noise_rms:.4f}）。安静房间里应该在 0.001~0.01 量级。")
        say("      很可能录到的不是你的麦克风，而是电脑正在播放的声音。")
        say("      检查是不是选到了虚拟声卡（ToDesk / 立体声混音 / VoiceMeeter 之类）。")

    say()
    say(f"  >> 建议 vad_threshold = {suggested:.4f}")
    say(f"     （底噪 {noise_rms:.4f} ／ 语音 90 分位 {p90:.4f} ／ 峰值 {peak:.4f}）")
    if peak < noise_rms * 1.5:
        say(f"{BAD} 语音比底噪高不了多少，说明这一整段根本没录到你说话。")
        say("      麦克风可能被别的程序独占、被静音、或选错了设备。")
    else:
        margin = peak / suggested if suggested > 0 else 0
        say(f"      语音峰值是阈值的 {margin:.1f} 倍，"
            f"{'余量充足' if margin > 3 else '余量偏小，可能需要调高麦克风音量'}")

    result.update({
        "ok": True,
        "noise_rms": round(noise_rms, 5),
        "speech_peak_rms": round(peak, 5),
        "speech_p90_rms": round(p90, 5),
        "suggested_threshold": round(suggested, 4),
    })
    (outdir / "mic_raw.json").write_text(
        json.dumps({"noise": noise.tolist()[:16000], "speech": speech.tolist()[:48000]}),
        encoding="utf-8",
    )
    return result


# ---------------------------------------------------------------- 阶段四：语音识别

def stage_asr(outdir):
    section("阶段 4 / 4   语音识别自检（会下载模型，首次较慢）")
    result = {"ok": False}

    try:
        import numpy as np  # noqa: F401
        import audio_io as aio
        from faster_whisper import WhisperModel
    except ImportError as exc:
        say(f"{SKIP} 跳过：缺少依赖 {exc.name}")
        say("      装好后用 --asr 再跑：python -m pip install faster-whisper sounddevice numpy")
        return result

    # 国内必须走镜像，否则 HuggingFace 下载会卡死
    os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
    say(f"{INFO} 模型下载源 HF_ENDPOINT = {os.environ['HF_ENDPOINT']}")

    model_size = "small"
    say(f"正在加载 Whisper 模型 '{model_size}' ...")
    say("      首次运行需要下载约 480MB，请耐心等待（走国内镜像，正常几分钟）")
    t0 = time.time()
    try:
        model = WhisperModel(model_size, device="cpu", compute_type="int8")
    except Exception as exc:  # noqa: BLE001
        say(f"{BAD} 模型加载失败: {type(exc).__name__}: {exc}")
        say("      若是下载超时，检查网络；也可以先手动把模型放到缓存目录")
        return result
    say(f"{OK} 模型加载完成，耗时 {time.time() - t0:.1f} 秒")
    result["model"] = model_size
    result["load_seconds"] = round(time.time() - t0, 1)

    # 先确定用哪个麦克风，再让用户开口 —— 免得倒计时都结束了还在试设备
    device = _resolve_audio_device()
    if device is None:
        say(f"{BAD} 没有可用的输入设备，跳过语音识别自检。")
        say("      先跑 python tools\\mic_test.py --all 排查。")
        return result

    say()
    say("  请说一个词，中文或英文都行，5 秒后自动停止 ...")
    say("      同样建议说中文，比如「清晰」或「简单」，用来检验中文识别准不准")
    for i in range(3, 0, -1):
        say(f"      {i} ...")
        time.sleep(1)
    say("      开始！")
    try:
        raw, actual_sr = aio.record(5.0, device=device, timeout_pad=6.0)
    except Exception as exc:  # noqa: BLE001
        say(f"{BAD} 录音失败：{exc}")
        say("      先跑 python tools\\mic_test.py --all 排查音频设备问题。")
        return result

    audio = aio.resample_to_16k(raw, actual_sr)
    t0 = time.time()
    try:
        segments, info = model.transcribe(audio, beam_size=5, vad_filter=True)
        segs = list(segments)
    except Exception as exc:  # noqa: BLE001
        say(f"{BAD} 识别失败: {type(exc).__name__}: {exc}")
        return result
    elapsed = time.time() - t0

    text = "".join(s.text for s in segs).strip()
    logprobs = [getattr(s, "avg_logprob", 0.0) for s in segs]
    avg_lp = sum(logprobs) / len(logprobs) if logprobs else 0.0

    say()
    say(f"{OK} 识别结果: {text!r}")
    say(f"      语言判定: {info.language} (概率 {info.language_probability:.2f})")
    say(f"      平均对数概率: {avg_lp:.3f}"
        + ("  <- 偏低，可能听错了" if avg_lp < -1.0 else ""))
    say(f"      识别耗时: {elapsed:.2f} 秒（5 秒音频）")

    result.update({
        "ok": True,
        "text": text,
        "language": info.language,
        "avg_logprob": round(avg_lp, 3),
        "transcribe_seconds": round(elapsed, 2),
    })
    return result


# ---------------------------------------------------------------- 主流程

def write_summary(outdir, env, screen, mic, asr):
    section("汇总")

    lines = []
    lines.append("# 声控手机助手 —— 探测结果摘要")
    lines.append("")
    lines.append(f"生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("")

    lines.append("## 一句话结论")
    verdict = (screen or {}).get("verdict", "unknown")
    verdict_text = {
        "uiautomator_ok": "无障碍树可用 —— 「精确坐标点击」方案成立，按原设计做。",
        "few_text_maybe_ocr": "只读到很少的文字节点 —— 界面可能自绘，需要看节点清单再定，可能要走 OCR。",
        "empty_need_ocr": "无障碍树是空的（自绘界面）—— 方案必须改成 OCR 优先。",
        "unknown": "界面读取失败，没有拿到结论。请看下面的报错。",
    }.get(verdict, verdict)
    lines.append(verdict_text)
    lines.append("")

    lines.append("## 环境")
    if env:
        lines.append(f"- adb：`{env.get('adb_path')}`")
        if env.get("adb_version"):
            lines.append(f"- adb 版本：{env['adb_version']}")
        dev = env.get("device") or {}
        for k, v in dev.items():
            lines.append(f"- {k}：{v}")
        lines.append(f"- 屏幕分辨率：{env.get('screen_size_raw')}")
        lines.append(f"- 屏幕密度：{env.get('screen_density_raw')}")
        if env.get("missing_packages"):
            lines.append(f"- **缺少依赖**：{', '.join(env['missing_packages'])}")
        else:
            lines.append("- 依赖：已全部安装")

    lines.append("")
    lines.append("## 界面读取")
    if screen and screen.get("dump_ok"):
        nodes = screen.get("nodes") or []
        with_text = [n for n in nodes if n["text"]]
        clickable_text = [n for n in with_text if n.get("click_ancestor_hops", -1) >= 0]
        lines.append(f"- 前台 App 包名：`{screen.get('root_package')}`")
        lines.append(f"- 节点总数：{len(nodes)}")
        lines.append(f"- 带 text 的节点：{len(with_text)}")
        lines.append(f"- 能追溯到可点击目标的文字节点：{len(clickable_text)}")
        lines.append("")
        lines.append("> 注：「可点击」统计仅供参考。`clickable` 标记只影响无障碍工具，"
                     "不影响真实触摸 —— 很多 App 的列表项不设这个标记，"
                     "但 `adb shell input tap` 注入的真实触摸照样有效。"
                     "判断能否点击要看文字有没有坐标，不是看这个标记。")
        lines.append("")
        lines.append("### 屏幕上的文字节点（从上到下）")
        lines.append("")
        lines.append("| y 坐标 | 可点击性 | 文字 | 实际点击坐标 |")
        lines.append("|---|---|---|---|")
        ordered = sorted(with_text, key=lambda n: (n["center"][1] if n["center"] else 10**9))
        for n in ordered[:60]:
            hops = n.get("click_ancestor_hops", -1)
            clickability = "自身可点" if hops == 0 else (f"上溯{hops}层" if hops > 0 else "不可点")
            target = n.get("click_target_center")
            tgt = f"({target[0]}, {target[1]})" if target else "—"
            text = (n["text"] or "").replace("|", "\\|")[:40]
            cy = n["center"][1] if n["center"] else "?"
            lines.append(f"| {cy} | {clickability} | `{text}` | {tgt} |")
    else:
        lines.append("未能读取无障碍树。")

    lines.append("")
    lines.append("## 麦克风")
    if mic and mic.get("ok"):
        dev_idx = mic.get("device_index")
        lines.append(f"- 输入设备序号：{dev_idx}")
        lines.append(f"- 采集采样率：{mic.get('capture_samplerate')} Hz")
        lines.append(f"- 环境底噪 RMS：{mic.get('noise_rms')}")
        lines.append(f"- 语音峰值 RMS：{mic.get('speech_peak_rms')}")
        lines.append(f"- 语音 90 分位 RMS：{mic.get('speech_p90_rms')}")
        lines.append(f"- **建议 vad_threshold：{mic.get('suggested_threshold')}**")
    else:
        lines.append("未测（依赖缺失或录音失败）。")

    lines.append("")
    lines.append("## 语音识别")
    if asr and asr.get("ok"):
        lines.append(f"- 模型：{asr.get('model')}")
        lines.append(f"- 识别结果：`{asr.get('text')}`")
        lines.append(f"- 语言判定：{asr.get('language')}")
        lines.append(f"- 平均对数概率：{asr.get('avg_logprob')}")
        lines.append(f"- 5 秒音频识别耗时：{asr.get('transcribe_seconds')} 秒")
    else:
        lines.append("未测（未加 --asr 参数，或依赖缺失）。")

    lines.append("")
    lines.append("## 附带文件")
    lines.append("- `ui_dump.xml` —— 无障碍树原始数据（**最有价值，出问题时优先发这个**）")
    lines.append("- `nodes.json` —— 解析后的节点结构")
    lines.append("- `screen.png` —— 当时的屏幕截图")
    lines.append("- `mic_raw.json` —— 麦克风原始波形（可选）")

    text = "\n".join(lines)
    (outdir / "SUMMARY.md").write_text(text, encoding="utf-8")

    say()
    say(f"{OK} 结果目录: {outdir}")
    say(f"{OK} 摘要文件: {outdir / 'SUMMARY.md'}")
    say()
    say("  请把 SUMMARY.md 和 ui_dump.xml 这两个文件发回给开发者。")
    say("  这两个文件决定了主程序该怎么写。")


def main():
    ap = argparse.ArgumentParser(
        description="声控手机助手 —— 环境探测脚本",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--adb", help="adb.exe 的完整路径（自动探测失败时用）")
    ap.add_argument("--outdir", help="结果输出目录，默认 debug/probe_<时间戳>")
    ap.add_argument("--asr", action="store_true", help="额外跑语音识别自检（会下载模型）")
    ap.add_argument("--skip-mic", action="store_true", help="跳过麦克风标定")
    ap.add_argument("--skip-screen", action="store_true", help="跳过界面读取")
    ap.add_argument("--device", type=int, help="强制使用指定序号的输入设备（先用 mic_test.py 查序号）")
    args = ap.parse_args()

    global _FORCE_DEVICE

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    if args.outdir:
        outdir = Path(args.outdir)
    else:
        outdir = Path(__file__).resolve().parent.parent / "debug" / f"probe_{stamp}"
    outdir.mkdir(parents=True, exist_ok=True)
    set_log(outdir / "console.log")

    # 输入设备优先级：命令行 --device > config.yaml > 自动挑选
    _FORCE_DEVICE = args.device
    if _FORCE_DEVICE is None:
        _FORCE_DEVICE = load_config_device()
        if _FORCE_DEVICE is not None:
            say(f"{INFO} 按 config.yaml 指定，使用输入设备 [{_FORCE_DEVICE}]")

    say()
    say("  声控手机助手 —— 环境探测")
    say("  在开始之前，请确保：")
    say("    1. 手机已解锁，并停留在 GRE3000 的答题界面上")
    say("    2. scrcpy 已经能正常投屏（说明 adb 是通的）")
    say()

    adb = find_adb(args.adb)

    env = screen = mic = asr = None

    if adb:
        env = stage_env(adb, outdir)
    else:
        section("阶段 1 / 4   环境自检")
        say(f"{BAD} 没有 adb，后续阶段无法进行。")
        say("      请用 --adb \"完整路径\" 指定，例如：")
        say('      python tools\\probe.py --adb "H:\\scrcpy-win64-v4.1\\adb.exe"')

    device_ready = bool(env and any(d["state"] == "device" for d in env.get("devices", [])))

    if adb and device_ready and not args.skip_screen:
        screen = stage_screen(adb, outdir)
    elif not args.skip_screen:
        section("阶段 2 / 4   界面读取")
        say(f"{SKIP} 跳过：手机没连上。")

    if not args.skip_mic:
        mic = stage_mic(outdir)

    if args.asr:
        asr = stage_asr(outdir)
    else:
        section("阶段 4 / 4   语音识别自检")
        say(f"{SKIP} 跳过：没加 --asr 参数（会下载约 480MB 模型）")
        say("      想测就运行：python tools\\probe.py --asr")

    write_summary(outdir, env, screen, mic, asr)

    say()
    say("  探测结束。")
    say()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n  已中断。\n")
        sys.exit(130)

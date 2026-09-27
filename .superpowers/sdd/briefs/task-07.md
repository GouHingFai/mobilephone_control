# 任务简报：任务 7（gui.py 与 run_gui.bat）

## 项目是什么

`voice_tap`：Windows 上的声控工具。用户用 scrcpy 投屏安卓手机玩 GRE3000 背单词，
开口说选项、或按小键盘数字，程序读屏后自动点对应选项。**代码与注释全中文，
你写的注释、日志、提交信息也用中文。**

用户要一个**置顶浮窗**浮在 scrcpy 上面，显示三块内容：
①各项开关并能点它开/关 ②程序手里那一屏的选项（核对读屏对不对）③识别出的语音与按下的小键盘键。

## 关键约束

## Global Constraints

- **测试命令**：`python -m unittest discover -s tests`（**没有 pytest**，别用 `-m pytest`）。沙箱里跑需要先 `pip install pypinyin --break-system-packages`，否则 3 个拼音测试会因为缺库而失败（那是环境问题）。
- **项目已启用 git**（2026-09-27 建立基线，初始提交“chore: 建立版本控制基线”）。每个任务做完执行 `git add -A && git commit -m "..."`。
  仓库里已配好 `core.autocrlf=false` 与 `.gitattributes`（**强制 `.bat` 保持 CRLF**）——**不要改动这两样，把行尾转换打开会把 `.bat` 改坏**。沙箱里 git 需要删除权限，已开。
- **每个任务开始前先在项目根目录跑一次** `python3 -m unittest discover -s tests` **确认起点是绿的**。
- **各任务末尾的「期望」一律写成「比开跑前多 N 个」，不要用绝对数** —— 用例总数会随任务累积，
  绝对数一写就过时。请以你自己跑第 1 条命令时输出的那个数为基准去加。
- **跑测试前先清一次字节码缓存**：`rm -rf tests/__pycache__ voice_tap/__pycache__`。
  本仓库里 `.py` 和 `.pyc` 常在同一秒落盘，改动若不改变字节数（比如交换两行），
  Python 会复用旧字节码、读到错的版本 —— 做「故意改坏看测试红不红」这类实验时尤其会中招。
- **不带 `--gui` 时，行为必须与现在完全一致** —— **唯一有意的例外**是任务 5 让「按 ESC / 关窗口」
  能立刻打断正在等待的监听（原来要等你说完这句才退，这是设计文档 §3.4 明说要修的老毛病）。
  除此之外任何行为差异都算 bug。任务 4/5/6 是重构，每步都要跑全套测试兜底。
- **所有用户可见输出走 `main.say()`**（同时打印并落盘到 `debug/run_*.log`），不要用裸 `print()`。
- **`.bat` 文件必须纯 ASCII + CRLF 行尾**，中文提示一律放在 Python 里（用 Write 工具写出来的是 LF，需要以二进制方式写并显式替换成 `\r\n`）。
- **界面不显示坐标**（用户明确要求）；坐标只进日志。
- **界面逻辑一律放 `ui_state.py` 与 `main.py` 的函数里**；`gui.py` 只摆控件、连线、刷新。
- **坐标/尺寸一律用整数**；`config.yaml` 里 `window: [x, y, w, h]`。
- 兼容 Python 3.9：新增模块顶部加 `from __future__ import annotations`（`config.py` 已有）。
- **各任务末尾写的「期望 N 个全过」是按计划里逐条测试相加算出来的**（基线 222）。差一两个不用慌；
  **差得多就说明漏加了测试**，回去对着该任务里的测试清单数一遍。

## 文件结构

| 文件 | 动作 | 职责 |
|---|---|---|
| `voice_tap/matcher.py` | 改 | 新增 `NEXT_PHRASES` + `detect_control()`（纯函数） |
| `voice_tap/config.py` | 改 | 新增 `GuiConfig`、`VoiceConfig.next_command`、`load_config` 解析 |
| `config.yaml` | 改 | 新增 `gui:` 段、`voice.next_command` |
| `voice_tap/ui_state.py` | **新建** | 线程安全的状态黑板 + 意图队列（纯 Python，可完整单测） |
| `voice_tap/gui.py` | **新建** | Tkinter 窗口：摆控件、连线、每 150ms 刷新 |
| `voice_tap/main.py` | 改 | `ScreenPrefetcher.identity()`；抽 `run_voice_loop`；统一动作队列；`collect_state`/`handle_intent`；动作时戳；语音「下一题」接线；结果回报 |
| `run_gui.bat` | **新建** | 带 `--gui` 启动 |
| `tests/test_matcher.py` | 改 | `detect_control()` 测试 |
| `tests/test_config.py` | 改 | `gui.*`、`voice.next_command` 测试 |
| `tests/test_ui_state.py` | **新建** | `UiState` 测试 |
| `tests/test_pipeline.py` | 改 | 动作时戳、语音「下一题」端到端测试 |
| `tests/test_inventory.py` | 改 | 更新基线数字 + 新增必备类 |
| `README.md` | 改 | 补界面说明；修掉「已经能说下一题」的不实描述与过时数字 |

## 你这次要做的事

## 任务 7：`gui.py` 与 `run_gui.bat`

**Files**
- Create: `voice_tap/gui.py`、`run_gui.bat`
- Modify: `voice_tap/main.py`
- Test: 语法校验 + 全套测试（界面本身没法在沙箱里自动测，见下）

**Interfaces**
- Produces:
  - `gui.AppWindow(root, collect_state, on_intent, refresh_ms=150, topmost=True)`
  - `gui.run(collect_state, on_intent, refresh_ms=150, topmost=True, geometry=None, on_closed=None)`
  - `main._load_window_geometry(path, fallback)` / `main._save_window_geometry(path, geometry)`

- [ ] **步骤 1：写 `voice_tap/gui.py`**

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gui.py —— 置顶浮窗

**这里只摆控件、连线和刷新，不放任何业务逻辑。**

理由：Tkinter 的界面没法在单元测试里跑（要有显示器）。所以逻辑一律放到
ui_state.py 和 main.py 的函数里 —— 那边可以用普通测试完整覆盖；这里保持薄，
薄到「看一眼就知道没写错」的程度。
"""

from __future__ import annotations

import time
import tkinter as tk
from tkinter import ttk


TOGGLE_LABELS = (
    ("toggle_voice", "语音"),
    ("toggle_mode", "模式"),
    ("toggle_numpad", "小键盘"),
    ("toggle_prefetch", "点击后预读"),
    ("toggle_voice_next", "语音说下一题"),
)


class AppWindow:

    def __init__(self, root, collect_state, on_intent, refresh_ms=150, topmost=True):
        self.root = root
        self.collect_state = collect_state
        self.on_intent = on_intent
        self.refresh_ms = refresh_ms
        self._labels = dict(TOGGLE_LABELS)
        self._buttons = {}

        root.title("声控手机助手")
        root.attributes("-topmost", bool(topmost))
        root.minsize(340, 380)
        self._build()
        self.refresh()
        self._tick()

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
        geometry=None, on_closed=None):
    """
    开窗并进入 Tk 事件循环。**必须在主线程调用。**

    on_closed 会在窗口关闭时收到当前几何位置（(x, y, 宽, 高)）。
    """
    root = tk.Tk()
    if geometry:
        root.geometry(f"{geometry[2]}x{geometry[3]}+{geometry[0]}+{geometry[1]}")
    window = AppWindow(root, collect_state, on_intent,
                       refresh_ms=refresh_ms, topmost=topmost)

    def _on_close():
        if on_closed is not None:
            try:
                on_closed(window.current_geometry())
            except Exception:  # noqa: BLE001
                pass
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", _on_close)
    root.mainloop()
```

并在 `AppWindow` 里补一个取几何位置的方法：

```python
    def current_geometry(self):
        """当前窗口位置与大小 (x, y, 宽, 高)"""
        self.root.update_idletasks()
        return (self.root.winfo_x(), self.root.winfo_y(),
                self.root.winfo_width(), self.root.winfo_height())
```

- [ ] **步骤 2：先在沙箱里做语法校验**（没有显示器，跑不了真窗口）

```
python -c "compile(open('voice_tap/gui.py', encoding='utf-8').read(), 'gui.py', 'exec'); print('OK')"
python -c "import ast,sys; ast.parse(open('voice_tap/gui.py', encoding='utf-8').read()); print('AST OK')"
```

期望：两行都打印 OK。**不要在这里 `import tkinter`**，沙箱里可能没有；用 `compile()` 只查语法。

- [ ] **步骤 3：`main()` 加 `--gui` 分支**

在参数解析处加：

```python
    parser.add_argument("--gui", action="store_true", help="同时打开置顶浮窗")
```

在 `voice_tap/main.py` 里加两个小工具：

```python
def _load_window_geometry(path, fallback):
    """
    读上次记下的窗口位置与大小。

    **刻意不写回 config.yaml** —— pyyaml 回写会把那份精心写的注释全抹掉。
    所以窗口位置单独存在这个文件里。
    """
    try:
        parts = Path(path).read_text(encoding="utf-8").split()
        if len(parts) >= 4:
            return tuple(int(p) for p in parts[:4])
    except Exception:  # noqa: BLE001
        pass
    return fallback


def _save_window_geometry(path, geometry):
    try:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(" ".join(str(v) for v in geometry), encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
```

在 `main()` 里 `ctx["voice_gate"] = VoiceGate(...)` 之后建界面状态：

```python
    # --- 界面（可选）
    use_gui = args.gui or cfg.gui.enabled
    ctx["ui"] = UiState() if use_gui else None
```

然后把主循环那段换成（**保持不带 `--gui` 时完全走老路**）：

```python
    if use_gui:
        from . import gui
        window_file = debug_dir / "gui_window.txt"
        # 界面必须占主线程，所以听语音挪到后台线程去
        loop_thread = threading.Thread(
            target=run_voice_loop,
            args=(ctx, hotkeys, recognizer),
            kwargs={"wake_event": wake_event},
            daemon=True, name="voice-loop",
        )
        loop_thread.start()
        try:
            gui.run(
                collect_state=lambda: collect_state(ctx),
                on_intent=lambda name: numpad_queue.put(("intent", name, None)),
                refresh_ms=cfg.gui.refresh_ms,
                topmost=cfg.gui.topmost,
                geometry=_load_window_geometry(window_file, cfg.gui.window),
                on_closed=lambda geom: (
                    _save_window_geometry(window_file, geom),
                    hotkeys.quit_requested.set(),
                ),
            )
        finally:
            hotkeys.quit_requested.set()
            loop_thread.join(timeout=3)
            worker_stop.set()
            hotkeys.stop()
            recognizer.close()
        say()
        say("  已退出。")
        return 0

    try:
        run_voice_loop(ctx, hotkeys, recognizer, once=args.once, wake_event=wake_event)
    except KeyboardInterrupt:
        ...
```

**注意**：`debug_dir` 这个变量在 `main()` 里已经有了（`ctx` 构造处上面），直接复用。

- [ ] **步骤 4：写 `run_gui.bat`**

内容就三行（**纯 ASCII + CRLF**，直接转交给 `run.bat`，不重复那一套启动逻辑）：

```bat
@echo off
REM Launch voice_tap with the always-on-top window. ASCII only, CRLF endings.
call "%~dp0run.bat" --gui %*
```

写的时候必须写成 CRLF。写完用下面这条确认（应输出 `CRLF`）：

```
python -c "d=open('run_gui.bat','rb').read(); print('CRLF' if b'\r\n' in d else 'LF -- 必须改成 CRLF')"
```

- [ ] **步骤 5：跑全套测试 + 语法校验**

```
python -m unittest discover -s tests
python -c "compile(open('voice_tap/main.py', encoding='utf-8').read(), 'main.py', 'exec'); print('OK')"
```

期望：用例数与开跑前**完全相同**（这一步只加界面，不改任何测试）。

- [ ] **步骤 6（用户侧手工冒烟，必须做）**

沙箱里没有显示器，界面只能由用户来验。请用户执行：

```
python -m voice_tap.main --gui --dump
```

（`--dump` 只抓一次屏就退出，界面会开一下就关；只要能开出来、能看到三块区域即可。）
然后正常跑 `run_gui.bat`，确认：

1. 窗口浮在 scrcpy 上面，能拖动；
2. 每个开关点一下，窗口里的字立刻变，控制台也打印对应的一行；
3. 按小键盘 1~9 时，「我的输入」里出现对应的记录；
4. 关掉窗口后程序确实退出了（不再是「按了还得等」）。

---

## ⚠️ 这个任务有个特殊之处：界面本身你验不了

开发环境是 Linux 沙箱，**没有显示器、也连不到用户的手机**。所以：

- `gui.py` 的**语法**可以用 `compile()` 校验，但**开不出真窗口**。
- 因此铁律是：**`gui.py` 必须极薄** —— 只摆控件、连线、刷新，**一行业务逻辑都不许放**。
  所有逻辑已经在任务 3/6 里放进了 `ui_state.py` 和 `main.py`（那些都能单测）。
  你往 `gui.py` 里塞逻辑，就等于把代码丢进一个测不到的黑洞。
- `run_gui.bat` 写完后**必须**验证是 CRLF（下面给命令）。LF 行尾会让 cmd.exe 直接中止脚本、窗口一闪而过。

## 环境提示

- 项目根目录：bash 是 `/sessions/pensive-confident-cerf/mnt/声控手机项目`；文件工具是 `H:\声控手机项目\...`。
- **跑测试前先清字节码缓存**：`rm -rf tests/__pycache__ voice_tap/__pycache__`
- 跑测试：`python3 -m unittest discover -s tests`（**没有 pytest**；沙箱缺 `pypinyin` 就先
  `pip install pypinyin --break-system-packages`）。
- **不要**碰 `.gitattributes` / `core.autocrlf`；**不要**用 Write 工具直接写 `.bat`
  （那会写成 LF），要用二进制方式写并显式替换成 `\r\n`。
- **不要**在沙箱里 `import tkinter`（可能没装）—— 用 `compile()` 查语法就够了。

## 跨任务提醒

- `collect_state(ctx)` 是界面数据的唯一来源，`UiState.post_intent(name)` 是界面按钮的出口。
- 界面的每个按钮都必须**复用已有的那套函数**（`ctx["intents"]` 表里的），不要另写一套 ——
  否则会出现「界面显示开着、实际没开」的分裂。
- 窗口位置**刻意不写回 config.yaml**（pyyaml 回写会抹掉那份逐行注释），改存 `debug/gui_window.txt`。

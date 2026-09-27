# 任务简报：任务 6（collect_state + 把结果回报给界面）

## 项目是什么

`voice_tap`：Windows 上的声控工具。用户用 scrcpy 投屏安卓手机玩 GRE3000 背单词，
开口说选项、或按小键盘数字，程序读屏后自动点对应选项。**代码与注释全中文，
你写的注释、日志、提交信息也用中文。**

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

## 任务 6：`collect_state` + 把结果回报给界面

**Files**
- Modify: `voice_tap/main.py`
- Test: `tests/test_pipeline.py`

**Interfaces**
- Produces:
  - `main.collect_state(ctx) -> dict` —— 纯读，返回 `{"toggles": {...}, "screen": ScreenView|None, "inputs": [InputEvent]}`
  - `main.publish_screen(ctx, snap, source, age=None) -> None`
  - `main.note_input(ctx, kind, label, detail="", outcome="") -> None`

- [ ] **步骤 1：先写测试**

```python
class TestCollectState(unittest.TestCase):
    """
    界面要显示的东西都从这儿来。**纯读**，所以能单测。

    开关的真相源是那些活对象，这里现读 —— 不另存一份，
    否则会出现「界面显示开着、实际没开」的分裂。
    """

    def _ctx(self):
        cfg = Config()
        gate = StubVoiceGate()
        hotkeys = StubHotkeys()
        hotkeys.numpad_enabled = True
        return {
            "cfg": cfg,
            "mode": "listen",
            "voice_gate": gate,
            "hotkeys": hotkeys,
            "ui": UiState(),
        }

    def test_reports_live_toggles(self):
        ctx = self._ctx()
        state = app.collect_state(ctx)
        self.assertTrue(state["toggles"]["voice"])
        self.assertEqual(state["toggles"]["mode"], "listen")
        self.assertTrue(state["toggles"]["numpad"])
        self.assertTrue(state["toggles"]["prefetch"])
        self.assertTrue(state["toggles"]["voice_next"])

    def test_reflects_changes_immediately(self):
        ctx = self._ctx()
        ctx["cfg"].prefetch.after_click = False
        self.assertFalse(app.collect_state(ctx)["toggles"]["prefetch"])

    def test_without_ui_returns_empty(self):
        ctx = self._ctx()
        del ctx["ui"]
        state = app.collect_state(ctx)
        self.assertIsNone(state["screen"])
        self.assertEqual(state["inputs"], [])


class TestPublishScreen(unittest.TestCase):

    def test_publishes_options_without_coordinates(self):
        ctx = {"ui": UiState()}
        snap = screen.read_screen(GRE_XML)

        app.publish_screen(ctx, snap, "预读", age=1.2)

        view = ctx["ui"].current_screen()
        self.assertEqual(view.prompt, "degrade")
        self.assertEqual([o.index for o in view.options], [1, 2, 3, 4, 5])
        self.assertEqual(view.options[0].text, "adj. 清晰易懂的")
        self.assertFalse(hasattr(view.options[0], "y"), "界面不显示坐标")
        self.assertEqual(view.source, "预读")
        self.assertAlmostEqual(view.age_seconds, 1.2)

    def test_noop_without_ui(self):
        app.publish_screen({"ui": None}, screen.read_screen(GRE_XML), "预读")


class TestNoteInput(unittest.TestCase):

    def test_records(self):
        ctx = {"ui": UiState()}
        app.note_input(ctx, "numpad", "3", outcome="点了第 3 个")
        events = ctx["ui"].recent_inputs()
        self.assertEqual(events[0].label, "3")
        self.assertEqual(events[0].outcome, "点了第 3 个")

    def test_noop_without_ui(self):
        app.note_input({"ui": None}, "numpad", "3")
```

`tests/test_pipeline.py` 顶部补一行 `from voice_tap.ui_state import UiState`。

- [ ] **步骤 2：跑测试，确认失败**

```
python -m unittest tests.test_pipeline.TestCollectState tests.test_pipeline.TestPublishScreen tests.test_pipeline.TestNoteInput -v
```

- [ ] **步骤 3：实现这三个函数**

在 `voice_tap/main.py` 里 `handle_intent` 之后加（并在文件顶部 `from .voice_gate import VoiceGate` 附近补
`from .ui_state import InputEvent, OptionView, ScreenView`）：

```python
def collect_state(ctx):
    """
    拼一份「界面要显示的东西」。**只读，不改任何状态** —— 所以能单测。

    开关一律现读活对象（voice_gate / hotkeys / mode / 配置），不另存一份。
    """
    ui = ctx.get("ui")
    return {
        "toggles": {
            "voice": ctx["voice_gate"].enabled,
            "mode": ctx["mode"],
            "numpad": ctx["hotkeys"].numpad_enabled,
            "prefetch": ctx["cfg"].prefetch.after_click,
            "voice_next": ctx["cfg"].voice.next_command,
        },
        "screen": ui.current_screen() if ui else None,
        "inputs": ui.recent_inputs() if ui else [],
    }


def publish_screen(ctx, snap, source, age=None):
    """把「程序手里那一屏」交给界面显示（**不带坐标**）"""
    ui = ctx.get("ui")
    if ui is None:
        return
    ui.set_screen(ScreenView(
        prompt=snap.prompt,
        options=[OptionView(i, n.text) for i, n in enumerate(snap.options, 1)],
        source=source,
        age_seconds=age,
        page=snap.page,
        ok=snap.ok,
        reason=snap.reason,
    ))


def note_input(ctx, kind, label, detail="", outcome=""):
    """记一条「我的输入」给界面看（没开界面时是空操作）"""
    ui = ctx.get("ui")
    if ui is None:
        return
    ui.record_input(InputEvent(kind=kind, label=label, detail=detail, outcome=outcome))
```

- [ ] **步骤 4：接到各个出口上**

在 `grab_screen()` 的两条返回路径前各加一次发布（**这是界面第二块的数据来源**）：

```python
    if use_prefetch:
        cached = prefetcher.take_or_wait()
        if cached is not None:
            snap, age = cached
            source = f"预读，{age:.1f} 秒前读好的（没读屏）"
            publish_screen(ctx, snap, "预读", age)      # ← 新增
            return snap, source
```

```python
    snap = screen.read_screen(xml)
    prefetcher.note(snap, read_at=read_start)
    say(...)
    publish_screen(ctx, snap, "当场读屏")               # ← 新增
    return snap, f"当场读屏 {read_ms:.0f} 毫秒（{len(xml) // 1024} KB）"
```

在 `do_click()` 里记结果（**界面第三块的数据来源**）。先从现成的 `key` 参数推出「这是一次什么输入」，
别另造一套标记：

```python
def _input_kind_and_label(key, description):
    """
    从 do_click 的 key 推出「这是一次什么输入」，给界面第三块用。

    三条路径本来就通过 key 区分了自己（小键盘传 ("numpad", 几号)、
    下一题传 ("next",)、语音传 None），不必再往 ctx 里塞额外标记。
    """
    if key and key[0] == "numpad":
        return "numpad", str(key[1])
    if key and key[0] == "next":
        return "next", "0"
    return "speech", description
```

然后 `do_click` 里：

```python
    kind, label = _input_kind_and_label(key, description)
    if not (clicked and not ctx["preview"]):
        if not clicked:
            note_input(ctx, kind, label, outcome="已跳过（防连点）")
        return clicked
    note_input(ctx, kind, label, outcome=f"点了 {description}")
```

在动作时戳被拦下的那个分支加：

```python
        note_input(ctx, "numpad", str(number), outcome="已忽略：界面在按键之后翻页了")
```

在语音路径加（`handle_speech` 开头，紧挨着 `say(f"[听到] ...")` 之后）：

```python
    note_input(ctx, "speech", text,
               detail=f"置信度 {logprob:.2f}", outcome="（见下）")
```

- [ ] **步骤 5：跑全套，全绿**

```
python -m unittest discover -s tests
```

期望：比开跑前多 7 个（CollectState 3 + PublishScreen 2 + NoteInput 2）。

---

## 环境提示

- 项目根目录：bash 是 `/sessions/pensive-confident-cerf/mnt/声控手机项目`；文件工具是 `H:\声控手机项目\...`。
- **跑测试前先清字节码缓存**：`rm -rf tests/__pycache__ voice_tap/__pycache__`
  （本仓库 `.py` 与 `.pyc` 常同秒落盘，改动若不改变文件字节数，Python 会复用旧字节码读到错版本。
  做「改坏看红不红」的实验时尤其必须。）
- 跑测试：`python3 -m unittest discover -s tests`（**没有 pytest**；沙箱缺 `pypinyin` 就先
  `pip install pypinyin --break-system-packages`）。
- **不要**碰 `.gitattributes` / `core.autocrlf`，**不要**改 `.bat` 文件。

## 这一步在给界面铺数据

`collect_state(ctx)` 是**界面三块内容的唯一数据来源**：开关状态（现读活对象，不另存副本）、
当前那一屏（`screen`）、我的输入记录（`inputs`）。它必须是**纯读**、不改任何状态 —— 所以能单测。

`publish_screen` / `note_input` 负责在程序跑的时候往 `UiState` 里写；**没开界面时它们是空操作**
（`ctx["ui"]` 为 None），所以不带 `--gui` 时行为完全不变。

## 跨任务提醒

- 动作分派唯一入口 `dispatch_action(action, ctx)`；别动 `numpad_worker` 的循环体。
- `UiState` 的线程安全没有测试能证明。**它有一条调用方约定**（写在类 docstring 里）：
  `ScreenView` 和它里面的 `options` 构造好之后**不许再改**，要更新就新建一个再 `set_screen`。
  `publish_screen` 必须遵守这条 —— 每次新建 `ScreenView`，别去改已有对象。
- 本任务的 `_input_kind_and_label` 从现成的 `key` 参数推「这是哪次输入」，别另造标记往 ctx 里塞。

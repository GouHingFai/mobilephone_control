# 任务简报：任务 5（统一动作队列 + 唤醒监听）

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
- **不带 `--gui` 时，行为必须与现在完全一致。** 任务 4/5/6 是重构，靠现有的 222 个测试兜底；每步都要跑全套。
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

## 任务 5：统一动作队列 + 唤醒监听

**Files**
- Modify: `voice_tap/main.py`
- Test: `tests/test_pipeline.py`

**Interfaces**
- Produces:
  - `main.handle_intent(name, ctx, wake_event=None) -> None`
  - `main._toggle_flag(ctx, section, key, label) -> None`
  - `main._AnyEvent(*events)` —— 只实现 `is_set()`，冒充一个 Event 传给监听
  - 动作队列新增 `("intent", name, None)` 与 `("quit", None, None)`
  - `ctx["hotkeys"]`、`ctx["intents"]` 两个新键

- [ ] **步骤 0（必须先做）：给主循环补一层驱动测试**

**为什么先做**：任务 4 的审查**实测**发现，`TestRunVoiceLoop` 那条用例对循环体**零约束** ——
把 `run_voice_loop` 的循环体整段删空、只留 `return`，它照样绿（quit 已置位，`while` 根本不进）。
也就是说现在「全绿」并不代表循环体是对的。而这一步马上要改这个函数（加 `wake_event`、
把 `stop_event` 传下去），**行为基线只有在改动之前建立才有价值** —— 改完再补，
等于把改后的行为固化成「期望」。所以先补，再动。

用假 Recognizer + 假 HotkeyManager 驱动，**不起真线程、不碰真音频**。先加这个桩：

```python
class StubRecognizerLoop:
    """只记录被怎么调用的假识别器 —— 用来驱动主循环的各条分支"""

    last_timing = {}

    def __init__(self, utterances=None):
        self.utterances = list(utterances or [])
        self.calls = []          # [("listen_once", kwargs) | ("listen_pressed", kwargs)]

    def listen_once(self, **kwargs):
        self.calls.append(("listen_once", kwargs))
        return self.utterances.pop(0) if self.utterances else None

    def listen_pressed(self, held_event, **kwargs):
        self.calls.append(("listen_pressed", kwargs))
        return self.utterances.pop(0) if self.utterances else None
```

然后加测试类 `TestRunVoiceLoopBranches`，覆盖这些分支：

| 用例 | 怎么驱动 | 断言什么 |
|---|---|---|
| listen 模式走 `listen_once` | `mode="listen"`，喂一句 `("清晰", -0.4)`，`once=True` | 真的点了（`fake.taps` 有 1 条）；`listen_once` 收到的 kwargs 里有 `hint_snapshot` 与 `on_speech_start` |
| 语音关掉时短路 | `voice_gate.enabled = False` | `listen_once` **一次都没被调** |
| hotkey 模式走 `listen_pressed` | `mode="hotkey"`，`ptt_pressed` 先置位，喂一句 | 调的是 `listen_pressed`，且第一个实参就是那个 `ptt_pressed` |
| 识别返回 None | 喂 `None` | 循环继续、**没有点击** |
| 空文字串被跳过 | 喂 `("   ", -0.4)` | **没有点击** |
| `AdbError` 兜底不崩 | 让取屏那步抛 `AdbError`（把 `ctx["adb"]` 换成会抛的桩） | 循环不崩、返回正常 |
| `once=True` 跑完一句就退 | 喂一句 | 函数**真的返回了**（没卡在循环里） |

**写完必须先跑一遍确认它们能红**：临时把 `run_voice_loop` 的某个分支改坏
（比如删掉 `voice_gate.enabled` 那个短路），确认有对应用例变红，再改回来。
**这一步是关键** —— 任务 4 那条用例就是因为没做这个，才成了摆设（审查者的原话：
「254 绿是假安全感」）。

- [ ] **步骤 1：先写测试**

在 `tests/test_pipeline.py` 末尾加：

```python
class TestHandleIntent(unittest.TestCase):
    """
    界面按钮走这里。**调的必须是和热键完全相同的函数** ——
    不写第二套逻辑，否则会出现「界面显示开着、实际没开」这种分裂。
    """

    def _ctx(self):
        cfg = Config()
        calls = []
        ctx = {
            "cfg": cfg,
            "intents": {
                "toggle_voice": lambda: calls.append("voice"),
                "toggle_mode": lambda: calls.append("mode"),
            },
        }
        return ctx, calls

    def test_dispatches_to_the_same_function(self):
        ctx, calls = self._ctx()
        app.handle_intent("toggle_voice", ctx)
        self.assertEqual(calls, ["voice"])

    def test_unknown_intent_is_ignored(self):
        ctx, calls = self._ctx()
        app.handle_intent("乱写的名字", ctx)
        self.assertEqual(calls, [])

    def test_wakes_the_listener_afterwards(self):
        ctx, _calls = self._ctx()
        wake = threading.Event()

        app.handle_intent("toggle_voice", ctx, wake_event=wake)

        self.assertTrue(wake.is_set(), "执行完要唤醒监听线程，开关才会立刻生效")


class TestToggleFlag(unittest.TestCase):
    """界面上那两个没有对应热键的开关（预读、语音下一题）"""

    def test_flips_and_flips_back(self):
        ctx = {"cfg": Config()}

        app._toggle_flag(ctx, "prefetch", "after_click", "点击后预读")
        self.assertFalse(ctx["cfg"].prefetch.after_click)

        app._toggle_flag(ctx, "prefetch", "after_click", "点击后预读")
        self.assertTrue(ctx["cfg"].prefetch.after_click)

    def test_works_on_voice_next(self):
        ctx = {"cfg": Config()}
        app._toggle_flag(ctx, "voice", "next_command", "语音说「下一题」")
        self.assertFalse(ctx["cfg"].voice.next_command)


class TestAnyEvent(unittest.TestCase):

    def test_true_if_any_set(self):
        a, b = threading.Event(), threading.Event()
        any_event = app._AnyEvent(a, b)
        self.assertFalse(any_event.is_set())
        b.set()
        self.assertTrue(any_event.is_set())
```

- [ ] **步骤 2：跑测试，确认失败**

```
python -m unittest tests.test_pipeline.TestHandleIntent tests.test_pipeline.TestToggleFlag tests.test_pipeline.TestAnyEvent -v
```

期望：`AttributeError`（`handle_intent` / `_toggle_flag` / `_AnyEvent` 都还没有）。

- [ ] **步骤 3：实现这三个**

在 `voice_tap/main.py` 里 `probe_startup_screen` 之后加：

```python
class _AnyEvent:
    """
    把「任意一个事件被置位」伪装成**单个** Event，喂给监听函数。

    `listen_until_silence()` 只接受一个 stop_event，但我们有两个中断源：
    退出请求、以及「开关变了、快回来看一眼」。它内部只调 `is_set()`，
    所以这么一个小壳子就够了，不必去改音频层。
    """

    def __init__(self, *events):
        self._events = events

    def is_set(self):
        return any(e.is_set() for e in self._events)


def _toggle_flag(ctx, section, key, label):
    """翻一下配置里的某个布尔开关，并打一行日志。界面上那两个开关走这里。"""
    obj = getattr(ctx["cfg"], section)
    setattr(obj, key, not getattr(obj, key))
    say(f"  >>> {label}：{'开' if getattr(obj, key) else '关'}")


def handle_intent(name, ctx, wake_event=None):
    """
    执行一个来自界面的意图。

    真正的动作都在 `ctx["intents"]` 那张表里，而那张表里放的就是热键回调
    本身 —— 所以「界面点」和「按热键」走的是同一份代码。

    执行完唤醒一下监听线程：它多半正阻塞在「等你说话」上，
    不叫醒它，切模式／开关语音就要等到你下次开口才生效。
    """
    action = ctx.get("intents", {}).get(name)
    if action is None:
        return
    try:
        action()
    finally:
        if wake_event is not None:
            wake_event.set()
```

- [ ] **步骤 4：在 `main()` 里建好 `ctx["hotkeys"]` / `ctx["intents"]` / `wake_event`**

这段**不能一次贴完**，因为它引用的 `toggle_mode` / `voice_toggle` 是在 `hotkeys` 之后才定义的。
分两处放：

**(a) 在 `hotkeys = HotkeyManager(...)` 之后立刻加**（工作线程要用，必须在它启动前存在）：

```python
    ctx["hotkeys"] = hotkeys
    wake_event = threading.Event()
    ctx["wake_event"] = wake_event
```

**(b) 在 `def voice_toggle(): ...` 之后、`hotkeys.start(...)` 之前加**：

```python
    ctx["intents"] = {
        "toggle_voice": voice_toggle,
        "toggle_mode": toggle_mode,
        "toggle_numpad": lambda: hotkeys.set_numpad(not hotkeys.numpad_enabled),
        "toggle_prefetch": lambda: _toggle_flag(ctx, "prefetch", "after_click", "点击后预读"),
        "toggle_voice_next": lambda: _toggle_flag(ctx, "voice", "next_command", "语音说「下一题」"),
        "force_read": lambda: handle_force_read(ctx),
        "quit": lambda: hotkeys.quit_requested.set(),
    }
```

**顺序上必须注意两点**：`wake_event` 要在 `numpad_worker` 那个线程**启动之前**建好
（线程里会闭包引用它）；`ctx["intents"]` 要在 `toggle_mode` / `voice_toggle` **定义之后**才能建
（它引用这两个函数）。

- [ ] **步骤 5：让 `dispatch_action` 接住 `intent` / `quit`**

**注意**：动作分派现在**已经**统一在模块级函数 `dispatch_action(action, ctx)` 里了
（任务 1 的修复把它抽出来的）。所以改它 —— **不要**再去改 `numpad_worker` 的循环体，
那个循环体已经简化成「取一条 → `dispatch_action`」。

在 `dispatch_action` 的 `if/elif` 链里加两个分支（`wake_event` 从 `ctx["wake_event"]` 取，
不必给函数加参数）：

```python
    if kind == "numpad":
        handle_numpad(value, ctx, stamp=stamp)
    elif kind == "next":
        handle_next(ctx)
    elif kind == "force_read":
        handle_force_read(ctx)
    elif kind == "intent":
        handle_intent(value, ctx, ctx.get("wake_event"))
    elif kind == "quit":
        ctx["hotkeys"].quit_requested.set()
```

`handle_intent` 本身在步骤 3 里定义。

- [ ] **步骤 6：给监听传上中断条件**

把 `run_voice_loop` 的签名改成 `def run_voice_loop(ctx, hotkeys, recognizer, once=False, wake_event=None):`，
并把 listen 分支改成：

```python
            ctx["voice_gate"].wait_until_open(hotkeys.quit_requested)
            if wake_event is not None:
                wake_event.clear()   # 进监听前清零，否则会立刻又被打断、变成空转
            stop = _AnyEvent(hotkeys.quit_requested, wake_event) if wake_event else hotkeys.quit_requested
            utterance = recognizer.listen_once(
                on_speech_start=ctx["prefetcher"].trigger_on_speech,
                hint_snapshot=ctx["prefetcher"].peek(),
                stop_event=stop,
            )
```

- [ ] **步骤 7：跑全套，全绿**

```
python -m unittest discover -s tests
```

期望：比开跑前多 13 个（步骤 0 的循环分支 7 + HandleIntent 3 + ToggleFlag 2 + AnyEvent 1）。**重点确认不带 `--gui` 时行为没变** —— 这一步只加了能力，没改老路径。

---

## 环境提示

- 项目根目录：bash 是 `/sessions/pensive-confident-cerf/mnt/声控手机项目`；文件工具是 `H:\声控手机项目\...`。
- **跑测试前先清字节码缓存**：`rm -rf tests/__pycache__ voice_tap/__pycache__`
  （本仓库 `.py` 与 `.pyc` 常同秒落盘，改动若不改变文件字节数，Python 会复用旧字节码读到错版本。
  **做「改坏看测试红不红」的实验时，这一条是必须的**，否则你会读到错的版本、得出错的结论。）
- 跑测试：`python3 -m unittest discover -s tests`（**没有 pytest**；沙箱缺 `pypinyin` 就先
  `pip install pypinyin --break-system-packages`）。
- **不要**碰 `.gitattributes` / `core.autocrlf`，**不要**改 `.bat` 文件。

## 这个任务的重点与顺序

**步骤 0 必须先做、而且必须做扎实。** 它给主循环补一层驱动测试。之所以要补，是因为
审查者**实测**证明：现在那条 `TestRunVoiceLoop` 对循环体**零约束** —— 把循环体整段删空
只留 `return`，它照样绿。所以「全绿」目前是假安全感。

**顺序上不能颠倒**：先补测试并确认它们能红（靠故意改坏某个分支），**再**动 `run_voice_loop`
去加 `wake_event`。改完再补测试，等于把改动后的行为固化成「期望」，就白补了。

## 跨任务提醒

- **动作分派的唯一入口是模块级函数 `dispatch_action(action, ctx)`**（任务 1 的修复抽出来的）。
  本任务给它加 `"intent"` / `"quit"` 两个分支时**改它**，**不要**去动 `numpad_worker` 的循环体
  —— 那个循环体已经简化成「取一条 → `dispatch_action`」。
- `matcher.py` 没有 `from __future__ import annotations`，**别**在那儿写 `X | None` 注解。
- `UiState` 的线程安全没有测试能证明（那条并发用例只是冒烟），依据是类 docstring 里的三条不变量。

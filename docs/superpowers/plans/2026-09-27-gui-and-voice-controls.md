# 可视化界面与语音「下一题」实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给现有的命令行声控程序加一个置顶浮窗（显示开关、当前读到的那一屏、以及我的输入），补上语音说「下一题」，并修掉「连按两下同一个键会点到新题上」的 bug。

**Architecture:** 界面用 Tkinter 占主线程，把「听语音 → 识别 → 点击」抽成 `run_voice_loop()` 跑在后台线程。界面与主逻辑之间只通过一个加锁的 `UiState` 交换数据；界面按钮不直接改状态，而是往一个**统一的动作队列**里塞「意图」，由动作工作线程（现有的 `numpad_worker` 扩展而来）执行 —— 这样按钮不会被「监听线程正阻塞着等说话」拖住。按键动作带「当时的屏幕指纹」，执行前核对，屏幕变了就不点。

**Tech Stack:** Python 3.9+（`from __future__ import annotations`）、Tkinter（标准库，零依赖）、`unittest`（本项目不用 pytest）。

设计文档：`docs/superpowers/specs/2026-09-27-gui-and-voice-controls-design.md`

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

**任务顺序**：1 → 2 是**小而独立**的（修 bug + 语音下一题），做完就可以先用起来；3 → 8 是界面。若只想先要前者，做完任务 2 即可停。

---

## 任务 1：动作时戳 —— 修「连按两下同一个键点到新题上」

**Files**
- Modify: `voice_tap/main.py`
- Test: `tests/test_pipeline.py`

**Interfaces**
- Consumes: `ScreenPrefetcher.signature(snap)`（已存在，静态方法）、`ScreenPrefetcher.note()`（已存在）
- Produces:
  - `ScreenPrefetcher.identity() -> tuple | None` —— 最近见过那一屏的指纹，没有任何数据时 `None`
  - `handle_numpad(number, ctx, stamp=None)` —— 新增第三个参数
  - 动作队列条目格式统一成 `(kind: str, value, stamp)`，`kind ∈ {"numpad", "next", "force_read"}`

- [ ] **步骤 1：先写失败的测试**

在 `tests/test_pipeline.py` 顶部（`GRE_XML` 相关定义之后）补一份第二题的夹具：

```python
SECOND_XML = (FIXTURES / "gre_prototype.xml").read_text(encoding="utf-8")
```

在文件末尾（`TestStartupProbe` 之后、`if __name__` 之前）加：

```python
class TestActionStamp(unittest.TestCase):
    """
    按键动作要带「按键那一刻的屏幕」的戳；执行前核对，屏幕变了就不点。

    由来（真机上实测到的 bug）：在第一题上连按两下 `1`，
    第一下点完立刻作废缓存并启动后台预读；第二下还在队列里排队，
    等它被处理时预读已经读回了**第二题**，于是照着第二题点了第 1 个。
    根子是：**第一题时做的动作，被用到了第二题上。**
    """

    def _setup(self, xml=GRE_XML):
        cfg = Config()
        cfg.prefetch.after_click = False     # 别让后台预读来搅乱
        cfg.click.settle_ms = 0
        fake = FakeAdb(xml)
        pref = app.ScreenPrefetcher(fake, cfg, log=lambda *_: None)
        pref.note(screen.read_screen(xml))
        ctx = {
            "adb": fake,
            "cfg": cfg,
            "preview": False,
            "recognizer": StubRecognizer(),
            "prefetcher": pref,
            "voice_gate": StubVoiceGate(),
            "clicker": Clicker(fake, cfg.click, log=lambda *_: None),
        }
        return ctx, fake, pref

    def test_identity_is_none_before_any_read(self):
        fake = FakeAdb(GRE_XML)
        pref = app.ScreenPrefetcher(fake, Config(), log=lambda *_: None)
        self.assertIsNone(pref.identity(), "还没读到过任何界面时不该有指纹")

    def test_identity_reflects_last_seen_screen(self):
        _ctx, _fake, pref = self._setup()
        expected = app.ScreenPrefetcher.signature(screen.read_screen(GRE_XML))
        self.assertEqual(pref.identity(), expected)

    def test_dropped_when_screen_changed_since_press(self):
        """按键时是第一题，轮到执行时已经翻到第二题 —— 必须不点"""
        ctx, fake, pref = self._setup()
        stamp = pref.identity()                     # 按键那一刻：第一题
        pref.note(screen.read_screen(SECOND_XML))   # 界面翻了页
        fake.xml = SECOND_XML

        app.handle_numpad(1, ctx, stamp=stamp)

        self.assertEqual(fake.taps, [], "界面已经变了，这一下不能点")

    def test_runs_when_screen_unchanged(self):
        """界面没翻（比如那一下没生效）—— 照常点，这正是「按错键马上改」要的"""
        ctx, fake, pref = self._setup()
        stamp = pref.identity()

        app.handle_numpad(1, ctx, stamp=stamp)

        self.assertEqual(len(fake.taps), 1)

    def test_runs_when_no_stamp_given(self):
        """没盖戳（比如语音路径）时不做拦截"""
        ctx, fake, _pref = self._setup()

        app.handle_numpad(1, ctx)

        self.assertEqual(len(fake.taps), 1)
```

- [ ] **步骤 2：跑测试，确认它按预期失败**

```
python -m unittest tests.test_pipeline.TestActionStamp -v
```

期望：报 `AttributeError: 'ScreenPrefetcher' object has no attribute 'identity'`（以及 `handle_numpad() got an unexpected keyword argument 'stamp'`）。

- [ ] **步骤 3：给 `ScreenPrefetcher` 加 `identity()`**

在 `voice_tap/main.py` 的 `ScreenPrefetcher` 里，紧挨着现有的 `miss_reason()` 之后加：

```python
    def identity(self):
        """
        最近见过那一屏的指纹；还没读到过任何界面时返回 None。

        用途是给按键动作盖章：按下的那一刻记下「当时屏幕长什么样」，
        真正执行前再比一次 —— 不一样，就说明中间翻了页，这一下不能点。
        （参见 handle_numpad 的 stamp 参数与 tests 里的 TestActionStamp。）
        """
        with self._lock:
            if self._last_seen is None:
                return None
            return self.signature(self._last_seen)
```

- [ ] **步骤 4：`handle_numpad` 加 `stamp` 参数并核对**

把 `handle_numpad` 的签名改成 `def handle_numpad(number, ctx, stamp=None):`，
并在 `snap, source = grab_screen(ctx)` 之后、`if not snap.ok:` 之前插入：

```python
    # 核对「动作时戳」：这一下是在哪一屏按的？现在要点的又是哪一屏？
    # 不一样就说明中间翻了页 —— 那这一下绝不能点（会点到新题目上）。
    if stamp is not None and ScreenPrefetcher.signature(snap) != stamp:
        say("[小键盘] 这一下已忽略：界面在按键之后翻页了（不点，免得点到新题上）")
        return
```

同时更新 `handle_numpad` 的 docstring，补一句这个参数的来历。

- [ ] **步骤 5：动作队列改带戳，并让工作线程解开**

在 `main()` 里，把热键接线改成：

```python
        on_option=lambda n: numpad_queue.put(("numpad", n, ctx["prefetcher"].identity())),
        on_next=lambda: numpad_queue.put(("next", None, ctx["prefetcher"].identity())),
        on_force_read=lambda: numpad_queue.put(("force_read", None, None)),
```

再把 `numpad_worker` 的循环体改成：

```python
    def numpad_worker():
        while not worker_stop.is_set():
            try:
                action = numpad_queue.get(timeout=0.2)
            except queue.Empty:
                continue
            try:
                kind, value, stamp = action
            except (TypeError, ValueError):
                continue
            try:
                if kind == "force_read":
                    handle_force_read(ctx)
                elif kind == "next":
                    handle_next(ctx)
                else:
                    handle_numpad(value, ctx, stamp=stamp)
            except AdbError as exc:
                say(f"[!!] {exc}")
            except Exception:  # noqa: BLE001
                say("[!!] 处理小键盘操作时出错：")
                log_exception()
```

**注意**：小键盘回调那三处入队都已经在上面那三个 lambda 里改掉了。`numpad_worker` 里**原来**按 `number == "."` / `number == 0` 判断的那几行要一并删掉，改成按 `kind` 分派（下面这段就是替换后的完整循环体）。

- [ ] **步骤 6：跑测试，全绿**

```
python -m unittest tests.test_pipeline.TestActionStamp -v
python -m unittest discover -s tests
```

期望：新测试全过；全套 227 个（222 + 5）全过。

---

## 任务 2：语音说「下一题」

**Files**
- Modify: `voice_tap/matcher.py`、`voice_tap/config.py`、`config.yaml`、`voice_tap/main.py`
- Test: `tests/test_matcher.py`、`tests/test_config.py`、`tests/test_pipeline.py`

**Interfaces**
- Produces:
  - `matcher.NEXT_PHRASES: tuple[str, ...]`
  - `matcher.detect_control(text)` —— 目前只会返回 `"next"` 或 `None`
    （**注意**：`matcher.py` 没有 `from __future__ import annotations`，所以**不要写 `-> str | None` 注解**，
    那个写法在 Python 3.9 会直接报错。照步骤 3 给的代码片段写无注解版本。）
  - `VoiceConfig.next_command: bool = True`
  - `handle_next(ctx, source="小键盘 0")` —— 新增 `source` 参数

- [ ] **步骤 1：先写失败的测试（matcher）**

在 `tests/test_matcher.py` 末尾加：

```python
class TestDetectControl(unittest.TestCase):
    """
    控制语：说这些话不是要选某个选项，而是要程序做一件事（目前只有「下一题」）。

    它必须**优先于**选项匹配 —— 否则「下一题」会被拿去和选项比对，永远匹配不上。
    """

    def test_next_phrases(self):
        for spoken in ("下一题", "下一词", "下一个", "继续", "next", "说下一题", "下一题吧"):
            with self.subTest(spoken=spoken):
                self.assertEqual(matcher.detect_control(spoken), "next")

    def test_not_control(self):
        for spoken in ("清晰", "proliferate", "1", "", "extol"):
            with self.subTest(spoken=spoken):
                self.assertIsNone(matcher.detect_control(spoken))
```

- [ ] **步骤 2：跑测试，确认失败**

```
python -m unittest tests.test_matcher.TestDetectControl -v
```

期望：`AttributeError: module 'voice_tap.matcher' has no attribute 'detect_control'`。

- [ ] **步骤 3：实现 `detect_control`**

在 `voice_tap/matcher.py` 的 `parse_ordinal` 之后加：

```python
# 控制语：说这些话不是要选某个选项，而是要程序做一件事。
# 目前只有「下一题」一种 —— 答错进详情页后用它继续。
#
# 判定用「包含」而不是「相等」：ASR 常在前后带上零碎字词
# （「说下一题」「下一题吧」），只要里面出现了这个词，就是那个意思。
NEXT_PHRASES = (
    "下一题", "下一词", "下一首", "下一个", "下一组", "下一关",
    "继续", "next",
)


def detect_control(text):
    """
    看一眼识别出的文字里有没有控制语。

    返回 "next" 表示「去点下一题」，没有则返回 None。
    必须**优先于**选项匹配调用 —— 否则「下一题」会被拿去和选项比对。
    """
    key = normalize(text)
    if not key:
        return None
    for phrase in NEXT_PHRASES:
        if normalize(phrase) in key:
            return "next"
    return None
```

- [ ] **步骤 4：配置项 `voice.next_command`**

`voice_tap/config.py` 的 `VoiceConfig` 里加：

```python
    # 允许说「下一题」翻页（答错进详情页后用它继续）。
    #
    # 注意这是**直给**：说了就点固定坐标，不读屏校验 ——
    # 因此在答题页上误说也会点下去。这是用户明确选择的取舍。
    next_command: bool = True
```

`load_config` 里 `VoiceConfig(...)` 的构造加一行：

```python
        next_command=_pick(v, "next_command", VoiceConfig.next_command, _to_bool, n, "voice"),
```

`config.yaml` 的 `voice:` 段末尾加：

```yaml
  # 允许说「下一题」来翻页（答错进详情页后用它继续）。
  #
  # 注意：这是「直给」——说了就点固定坐标，不读屏校验。
  # 所以在答题页上误说「下一题」也会点下去。这是有意选的取舍。
  next_command: true
```

在 `tests/test_config.py` 末尾加：

```python
class TestVoiceNextCommand(unittest.TestCase):

    def test_code_default_is_on(self):
        self.assertTrue(cfgmod.VoiceConfig.next_command)

    def test_shipped_config_is_on(self):
        real = Path(__file__).resolve().parent.parent / "config.yaml"
        self.assertTrue(cfgmod.load_config(real).voice.next_command)

    def test_parsed_off(self):
        cfg = load_yaml("voice:\n  next_command: 关\n")
        self.assertFalse(cfg.voice.next_command)
```

- [ ] **步骤 5：接线到 `handle_speech`，并给 `handle_next` 加 `source`**

`handle_next` 签名改为 `def handle_next(ctx, source="小键盘 0"):`，
把函数体里第一行 `say("[小键盘] 0 → 下一题")` 改成 `say(f"[{source}] 下一题")`。

在 `handle_speech` 里，**在 `try: snap, source = grab_screen(ctx)` 之前**插入：

```python
    # 控制语优先，而且要排在取屏幕之前 —— 因为「下一题」走固定坐标，
    # 根本不需要读屏。说了就点，这是用户选的「直给」方式。
    if ctx["cfg"].voice.next_command and matcher.detect_control(text) == "next":
        handle_next(ctx, source="语音")
        return
```

- [ ] **步骤 6：端到端测试**

在 `tests/test_pipeline.py` 末尾加：

```python
class TestVoiceNextCommand(unittest.TestCase):
    """说「下一题」= 点下一题（直给：不读屏校验）"""

    def _ctx(self, xml):
        ctx, fake = make_ctx(xml)
        ctx["cfg"].hotkey.fixed_next_position = (909, 2476)
        return ctx, fake

    def test_saying_next_clicks_the_button(self):
        ctx, fake = self._ctx(DETAIL_XML)

        app.handle_speech("下一题", -0.4, ctx)

        self.assertEqual(fake.taps, [(909, 2476)])
        self.assertEqual(fake.dump_calls, 0, "固定坐标不该读屏")

    def test_works_on_quiz_page_too(self):
        """直给：答题页上说了照样点（用户明确接受这个取舍）"""
        ctx, fake = self._ctx(GRE_XML)

        app.handle_speech("下一题", -0.4, ctx)

        self.assertEqual(fake.taps, [(909, 2476)])

    def test_disabled_by_config(self):
        ctx, fake = self._ctx(DETAIL_XML)
        ctx["cfg"].voice.next_command = False

        app.handle_speech("下一题", -0.4, ctx)

        self.assertEqual(fake.taps, [], "关掉之后不该点；应落回普通匹配并提示详情页")
```

- [ ] **步骤 7：跑全套，全绿**

```
python -m unittest discover -s tests
```

期望：比开跑前多 8 个（matcher 2 + config 3 + pipeline 3）。

---

## 任务 3：`ui_state.py` —— 线程安全的状态黑板

**Files**
- Create: `voice_tap/ui_state.py`
- Test: `tests/test_ui_state.py`

**Interfaces**
- Produces:
  - `OptionView(index: int, text: str)`
  - `ScreenView(prompt, options, source, age_seconds, page, ok, reason)`
  - `InputEvent(kind, label, detail, outcome, at)`
  - `UiState(keep_inputs=8)`，方法：`set_screen` / `current_screen` / `record_input` / `recent_inputs(limit=5)` / `post_intent(name)` / `take_intents()`

- [ ] **步骤 1：先写失败的测试**

新建 `tests/test_ui_state.py`：

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_ui_state.py —— 界面与主逻辑之间的共享状态

这东西的难点只有一个：**它被多个线程同时读写**（主逻辑在写、界面在定时读）。
所以测试的重点是「并发下读到的永远是一份完整的数据」，以及队列行为正确。
"""

import threading
import unittest

from voice_tap.ui_state import InputEvent, OptionView, ScreenView, UiState


class TestScreen(unittest.TestCase):

    def test_none_before_set(self):
        self.assertIsNone(UiState().current_screen())

    def test_roundtrip(self):
        state = UiState()
        view = ScreenView(prompt="degrade",
                          options=[OptionView(1, "adj. 清晰易懂的")],
                          source="预读", age_seconds=1.5, page="quiz", ok=True)
        state.set_screen(view)
        self.assertIs(state.current_screen(), view)


class TestInputs(unittest.TestCase):

    def test_newest_first(self):
        state = UiState()
        state.record_input(InputEvent(kind="numpad", label="1"))
        state.record_input(InputEvent(kind="numpad", label="2"))

        got = state.recent_inputs()
        self.assertEqual([e.label for e in got], ["2", "1"])

    def test_capped(self):
        state = UiState(keep_inputs=3)
        for i in range(10):
            state.record_input(InputEvent(kind="numpad", label=str(i)))

        got = state.recent_inputs(limit=100)
        self.assertEqual(len(got), 3, "只保留最近 3 条")
        self.assertEqual([e.label for e in got], ["9", "8", "7"])

    def test_timestamp_filled(self):
        event = InputEvent(kind="speech", label="extol")
        UiState().record_input(event)
        self.assertGreater(event.at, 0, "没给时间戳时应该自己补上")


class TestIntents(unittest.TestCase):

    def test_post_and_take(self):
        state = UiState()
        state.post_intent("toggle_voice")
        state.post_intent("set_mode")

        self.assertEqual(state.take_intents(), ["toggle_voice", "set_mode"])
        self.assertEqual(state.take_intents(), [], "取过就没了")

    def test_concurrent_access_does_not_crash(self):
        """
        多线程同时读写，不崩、不卡死、读到的是一份完整的界面数据。

        **说清楚这条测试不是什么**（审查实测后如实标注）：它**抓不住竞态**。
        这个模块的线程安全来自「一把锁 + 整体换引用」，而 `set_screen` 换的是
        对象引用、在 CPython 下本就是原子的，所以把锁整个拿掉，这条测试照样全绿
        （实测 160 次无反例）。它是一条**冒烟测试**：能挡住「读到半截」「死锁」
        「current_screen 恒返回 None」这类明显回归，**不能**当作锁的护栏。
        别把它的绿色当成「并发正确性已验证」。
        """
        state = UiState(keep_inputs=50)
        stop = threading.Event()

        def writer(tag):
            i = 0
            while not stop.is_set():
                state.record_input(InputEvent(kind="numpad", label=f"{tag}-{i}"))
                state.set_screen(ScreenView(prompt=f"{tag}-{i}"))
                i += 1

        def reader():
            while not stop.is_set():
                state.current_screen()
                state.recent_inputs()
                state.take_intents()

        threads = [threading.Thread(target=writer, args=("a",)),
                   threading.Thread(target=writer, args=("b",)),
                   threading.Thread(target=reader)]
        for t in threads:
            t.start()
        time.sleep(0.3)
        stop.set()
        for t in threads:
            t.join(timeout=2)

        self.assertFalse(any(t.is_alive() for t in threads), "不该卡死")
        view = state.current_screen()
        self.assertTrue(view.prompt.startswith(("a-", "b-")))


if __name__ == "__main__":
    unittest.main(verbosity=2)
```

- [ ] **步骤 2：跑测试，确认失败**

```
python -m unittest tests.test_ui_state -v
```

期望：`ModuleNotFoundError: No module named 'voice_tap.ui_state'`。

- [ ] **步骤 3：实现 `voice_tap/ui_state.py`**

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ui_state.py —— 界面与主逻辑之间的共享状态

设计原则：**逻辑全在这里，界面只负责画。**

界面（gui.py）跑在 Tkinter 的主线程，主逻辑（听语音、处理按键）跑在别的线程。
两边唯一的交汇点就是这个对象：主逻辑往上写（现在读到哪一屏、刚听到什么、
点成没成），界面定时来读。所以这里必须线程安全，读出来的永远是一份完整快照。

它顺带把「界面按钮」和「主逻辑」解耦：按钮只往意图队列塞一个名字，
真正执行由动作工作线程去做 —— 这样按钮不会因为「监听线程正阻塞着等说话」而没反应。

（本模块刻意不 import tkinter：它能被普通单元测试完整覆盖。）
"""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field


@dataclass
class OptionView:
    """界面要显示的一个选项：序号 + 文字（**不含坐标** —— 用户明确不要）"""
    index: int
    text: str


@dataclass
class ScreenView:
    """界面要显示的「程序手里那一屏」"""
    prompt: str = ""
    options: list = field(default_factory=list)     # list[OptionView]
    source: str = ""            # "预读" / "当场读屏" / ""
    age_seconds: float | None = None
    page: str = ""              # quiz / detail / other
    ok: bool = False
    reason: str = ""


@dataclass
class InputEvent:
    """一条「我的输入」记录：按了什么键 / 说了什么话，以及结果"""
    kind: str = ""          # speech / numpad / next / force_read
    label: str = ""         # 识别出的文字 / "3" / "0" / "."
    detail: str = ""        # 置信度、耗时等的附加说明
    outcome: str = ""       # "点了第 4 个" / "已忽略：界面已翻页" / "没匹配上"
    at: float = 0.0


class UiState:
    """界面与主逻辑共享的状态黑板（线程安全）。

    线程安全靠三条不变量，缺一不可 —— 这才是这一层安全性的依据：

      1. **一把锁保护全部字段**。`_screen` / `_inputs` / `_intents` 共用 `self._lock`，
         每个读写路径都在锁里，没有哪条绕过它。
      2. **写入是整体换引用**。`set_screen` 换掉的是整个 `ScreenView` 对象，
         界面读到的永远是完整的一份，不会出现「新 prompt 配旧 options」的半截状态。
         `take_intents` 同理：整体取走、整体换一个新的 list，不做原地增删。
      3. **调用方的约定**：`ScreenView` 以及它里面的 `options` 是**裸对象**，
         构造好之后**不许再改**。谁要更新就新建一个再 `set_screen`。
         违反了这条，第 2 条的保证就没了 —— 类型系统管不住这种共享可变，
         只能靠这条约定。

    注意：「线程安全」这件事**没有测试能证明**（见 tests/test_ui_state.py 里那条
    冒烟测试的说明）。上面三条不变量就是全部依据，改动这一层时必须逐条对照。
    """

    def __init__(self, keep_inputs=8):
        self._lock = threading.Lock()
        self._screen = None
        self._inputs = deque(maxlen=keep_inputs)
        self._intents = []

    # -------------------------------------------------- 主逻辑 → 界面

    def set_screen(self, view):
        with self._lock:
            self._screen = view

    def current_screen(self):
        with self._lock:
            return self._screen

    def record_input(self, event):
        if not event.at:
            event.at = time.time()
        with self._lock:
            self._inputs.append(event)

    def recent_inputs(self, limit=5):
        """最近的输入，**最新的在前**"""
        if limit <= 0:
            # 没有这一句的话，limit=0 时 items[-0:] 会返回**全部**而不是空 ——
            # 切片对 0 的处理和直觉相反，是个安静的错行为。
            return []
        with self._lock:
            items = list(self._inputs)
        return items[-limit:][::-1]

    # -------------------------------------------------- 界面 → 主逻辑

    def post_intent(self, name):
        with self._lock:
            self._intents.append(name)

    def take_intents(self):
        with self._lock:
            items, self._intents = self._intents, []
            return items
```

- [ ] **步骤 4：跑测试，全绿**

```
python -m unittest tests.test_ui_state -v
```

期望：`TestScreen`(2) + `TestInputs`(3) + `TestIntents`(2) = 比开跑前多 7 个。

---

## 任务 4：抽出 `run_voice_loop`（纯重构，行为不变）

**Files**
- Modify: `voice_tap/main.py`
- Test: `tests/test_pipeline.py`

**Interfaces**
- Produces: `run_voice_loop(ctx, hotkeys, recognizer, once=False)` —— 把 `main()` 里那段 while 循环原样搬出来

- [ ] **步骤 1：先写测试**

`tests/test_pipeline.py` 顶部补 `import threading`，并在末尾加：

```python
class StubHotkeys:
    """最小可用的热键替身：主循环只需要这两个事件"""

    def __init__(self):
        self.quit_requested = threading.Event()
        self.ptt_pressed = threading.Event()


class TestRunVoiceLoop(unittest.TestCase):
    """
    主循环必须能被单独调用 —— 界面要占主线程，它得能挪到后台线程去。
    这一步是**纯重构**，行为必须和以前一模一样。
    """

    def test_returns_at_once_when_quit_already_requested(self):
        hotkeys = StubHotkeys()
        hotkeys.quit_requested.set()
        ctx = {"mode": "listen", "voice_gate": StubVoiceGate()}

        class MustNotBeCalled:
            def listen_once(self, **kwargs):
                raise AssertionError("已经请求退出了，不该再去监听")

        app.run_voice_loop(ctx, hotkeys, MustNotBeCalled(), once=False)
```

- [ ] **步骤 2：跑测试，确认失败**

```
python -m unittest tests.test_pipeline.TestRunVoiceLoop -v
```

期望：`AttributeError: module 'voice_tap.main' has no attribute 'run_voice_loop'`。

- [ ] **步骤 3：实现 `run_voice_loop`**

在 `voice_tap/main.py` 里 `report_unusable_screen` 之后加：

```python
def run_voice_loop(ctx, hotkeys, recognizer, once=False):
    """
    主循环：听 → 识别 → 点击。

    抽成独立函数，是为了让界面能占主线程（Tkinter 的硬性要求）。
    不带 --gui 时它仍旧跑在主线程，行为与以前完全一致。
    """
    while not hotkeys.quit_requested.is_set():
        if ctx["mode"] == "listen":
            if not ctx["voice_gate"].enabled:
                # 语音关着（按了 F7）—— 不用监听，省得白忙
                time.sleep(0.1)
                continue
            ctx["voice_gate"].wait_until_open(hotkeys.quit_requested)
            utterance = recognizer.listen_once(
                on_speech_start=ctx["prefetcher"].trigger_on_speech,
                hint_snapshot=ctx["prefetcher"].peek(),
            )
        else:
            # 等按下 F8；没按下就继续空转
            if not hotkeys.ptt_pressed.wait(0.2):
                continue
            utterance = recognizer.listen_pressed(
                hotkeys.ptt_pressed,
                hint_snapshot=ctx["prefetcher"].peek(),
            )

        if utterance is None:
            continue

        text, logprob = utterance
        if not text.strip():
            continue

        try:
            handle_speech(text, logprob, ctx)
        except AdbError as exc:
            say(f"[!!] {exc}")

        if once:
            say()
            say("  --once 模式，跑完一句就退出。")
            break
```

- [ ] **步骤 4：`main()` 里改成调用它**

把 `main()` 里那段 `try: while not hotkeys.quit_requested.is_set(): ...` 整个循环体删掉，换成：

```python
    try:
        run_voice_loop(ctx, hotkeys, recognizer, once=args.once)
    except KeyboardInterrupt:
        say()
        say("  收到中断，正在退出 ...")
    finally:
        worker_stop.set()
        hotkeys.stop()
        recognizer.close()
```

（`finally` 里那三行的顺序和内容保持原样，不要动。）

- [ ] **步骤 5：跑全套，全绿**

```
python -m unittest discover -s tests
```

期望：比开跑前多 1 个。**这一步不许有任何行为变化** —— 如果有测试挂了，说明搬家时漏了东西，回去看，不要改测试。

---

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

## 任务 7：`gui.py` 与 `run_gui.bat`

**Files**
- Create: `voice_tap/gui.py`、`run_gui.bat`
- Modify: `voice_tap/main.py`、`voice_tap/config.py`、`config.yaml`
- Test: 语法校验 + 全套测试（界面本身没法在沙箱里自动测，见下）

**Interfaces**
- Produces:
  - `gui.AppWindow(root, collect_state, on_intent, refresh_ms=150, topmost=True, on_closed=None, should_close=None)`
  - `gui.run(collect_state, on_intent, refresh_ms=150, topmost=True, geometry=None, on_closed=None, should_close=None)`
  - `main._load_window_geometry(path, fallback)` / `main._save_window_geometry(path, geometry)`

> **⚠ 步骤 0 是必需的（原计划漏写，2026-09-27 补记）**
> 本任务**必须**同时给 `voice_tap/config.py` 加 `GuiConfig`、给 `config.yaml` 加 `gui:` 段。
> 少了它，`main()` 里那句 `use_gui = args.gui or cfg.gui.enabled` 会在
> **不带 `--gui` 的正常路径**上直接抛 `AttributeError: 'Config' object has no
> attribute 'gui'` —— 程序连起都起不来，不只是界面的事。
> 所以这不是「顺手加的」，是本任务的前置条件；原计划把它漏在任务分工之外了。

- [ ] **步骤 0：`config.py` 加 `GuiConfig`、`config.yaml` 加 `gui:` 段（必需）**

在 `voice_tap/config.py` 里新增一个 `GuiConfig` 数据类（字段：`enabled=False`、
`window=(x, y, w, h)`、`topmost=True`、`refresh_ms=150`），挂进 `Config`，
并在 `load_config()` 里解析 `config.yaml` 的 `gui:` 段。`config.yaml` 相应加 `gui:` 段
（`enabled` 默认 `false`，`window` 给一组默认坐标）。

**为什么非做不可**：`main()` 里读 `cfg.gui.enabled` 来决定开不开界面，这个读取发生在
**所有启动路径**上（包括完全不带 `--gui` 的那种）。`Config` 上要是没有 `gui` 这个字段，
正常启动就会在这里 `AttributeError` 崩掉 —— 与界面无关的用户也会受影响。
配套测试加在 `tests/test_config.py`（`gui.*` 的解析与默认值）。

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

    def __init__(self, root, collect_state, on_intent, refresh_ms=150, topmost=True,
                 on_closed=None, should_close=None):
        self.root = root
        self.collect_state = collect_state
        self.on_intent = on_intent
        self.refresh_ms = refresh_ms
        self.on_closed = on_closed
        self.should_close = should_close
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
        # ESC 和界面上的「退出」都只是把 quit_requested 置了个位；
        # 主线程正卡在 mainloop() 里，没人叫停它窗口就干留着、进程也吊着。
        # 所以每次刷新前问一句「要不要关」，要关就走和窗口 X 相同的那条收尾路。
        if self.should_close is not None and self.should_close():
            self.close()
            return
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
        geometry=None, on_closed=None, should_close=None):
    """
    开窗并进入 Tk 事件循环。**必须在主线程调用。**

    on_closed 会在窗口关闭时收到当前几何位置（(x, y, 宽, 高)）。

    should_close 是个无参可调用对象：界面每次刷新时问它一次，一旦返回真值
    就把窗口关掉。按 ESC、点界面上的「退出」都只是把退出请求置位，
    **不靠这个轮询的话没人去 destroy 根窗口**，mainloop 就永远不返回、
    进程也结束不了。三条退出路（ESC／退出按钮／窗口 X）最终都汇到 close()。
    """
    root = tk.Tk()
    if geometry:
        root.geometry(f"{geometry[2]}x{geometry[3]}+{geometry[0]}+{geometry[1]}")
    window = AppWindow(root, collect_state, on_intent,
                       refresh_ms=refresh_ms, topmost=topmost,
                       on_closed=on_closed, should_close=should_close)

    root.protocol("WM_DELETE_WINDOW", window.close)
    root.mainloop()
```

并在 `AppWindow` 里补一个取几何位置的方法，**以及关窗收尾方法 `close()`**
（窗口 X 与 ESC 都走它，两条路都要把窗口位置存下来）：

```python
    def current_geometry(self):
        """当前窗口位置与大小 (x, y, 宽, 高)"""
        self.root.update_idletasks()
        return (self.root.winfo_x(), self.root.winfo_y(),
                self.root.winfo_width(), self.root.winfo_height())

    def close(self):
        """
        关窗前的收尾：先把窗口位置交出去存好，再销毁窗口。

        **窗口 X 和 ESC/界面上的「退出」都走这一条路** —— 两条路都得存位置，
        否则按 ESC 退出时那次的位置就白丢了。
        """
        if self.on_closed is not None:
            try:
                self.on_closed(self.current_geometry())
            except Exception:  # noqa: BLE001
                # 存位置失败不该拦着退出 —— 大不了下次用回默认位置
                pass
        self.root.destroy()
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
                # 按 ESC / 点界面上的「退出」都只是置位 quit_requested；
                # 真正把窗口关掉、让 mainloop 返回，靠界面轮询这个回调。
                should_close=lambda: hotkeys.quit_requested.is_set(),
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

- [ ] **步骤 3b：让「退出请求」真能关掉窗口（任务 5 与任务 7 之间的接缝）**

这一段是**原计划两头都没写**的地方，必须补上，否则三条退出路里前两条是坏的：

    ESC（热键回调）────┐
    界面上的「退出」按钮 ─┤→ 只把 hotkeys.quit_requested 置位
    窗口 X ───────────┘   └→ 走 run() 的 close() → root.destroy()

「界面上的退出」按钮是这样一路走到的：点按钮 → `numpad_queue.put(("intent","quit",None))`
→ `numpad_worker` → `dispatch_action` 的 `quit` 分支 → `ctx["intents"]["quit"]()`
→ `hotkeys.quit_requested.set()`（见任务 5 的步骤 4／5）。
所以 ESC 和「退出」按钮**最终都只是置了个位**，而主线程这时正卡在 Tk 的
`mainloop()` 里 —— **没有任何东西去 `destroy()` 根窗口**，于是语音循环停了，
窗口却留着、进程也吊着。这违背设计文档 §1.4「关窗口能立刻退出」的承诺。

接缝的做法（就是上面步骤 1 里 `gui.run` 的参数 `should_close`）：

- `gui.run(..., should_close=...)` / `AppWindow.__init__(..., should_close=None)`；
- `AppWindow._tick()` 每轮先问一次 `should_close()`，返回真值就调用 `close()`
  （先 `on_closed(当前几何)` 存位置，再 `root.destroy()`）并**不再排下一次刷新**；
- `main()` 里传 `should_close=lambda: hotkeys.quit_requested.is_set()`。

于是三条退出路（ESC / 按钮 / 窗口 X）**全都收敛到同一个收尾**：窗口关掉、
`mainloop()` 返回、`main()` 的 `finally` 收尾（`hotkeys.stop()` / `recognizer.close()` 等）。
注意关窗前一定要走 `on_closed(...)`，否则按 ESC 退出时窗口位置就丢了。

- [ ] **步骤 3c：给窗口几何那两个工具函数补测试**

`_load_window_geometry` / `_save_window_geometry` 是模块级函数、能单测，但原计划一个测试都没写。
在 `tests/test_pipeline.py` 加一个 `TestWindowGeometry`，钉住：

- 存了再读，拿回来是同一组四个整数；
- 文件不存在 → 返回 fallback；
- 内容坏掉（比如写了 `"乱写的"`，或四个词但都不是整数）→ 返回 fallback 且**不抛异常**；
- 存的时候父目录不存在也能建出来。

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

期望：比开跑前多 5 个（`tests/test_pipeline.py` 新增的 `TestWindowGeometry`）。
`gui.py`／`main.py` 只改接线，不新增用例。

- [ ] **步骤 6（用户侧手工冒烟，必须做）**

沙箱里没有显示器，界面只能由用户来验。请用户执行（二选一，都会**真正开窗**）：

```
run_gui.bat
```

或

```
python -m voice_tap.main --gui
```

> **别用 `--gui --dump`**：`--dump` 在 `main()` 里**先于界面装配就 `return` 了**
> （那一段在 `if args.dump:` 处直接返回，界面要用的模块全在它之后才装配），
> 窗口根本不会开 —— 原计划把它当冒烟命令是错的（2026-09-27 更正）。

确认：

1. 窗口浮在 scrcpy 上面，能拖动；
2. 每个开关点一下，窗口里的字立刻变，控制台也打印对应的一行；
3. 按小键盘 1~9 时，「我的输入」里出现对应的记录；
4. **按 ESC 能关掉窗口、进程也结束**（不再是「按了还得等」）；
5. **点界面上的「退出」按钮同样能关掉窗口、进程结束**；
6. 关掉窗口后重新起一次，窗口停在**上次关窗时的位置**（说明关闭路径存下了几何）。

---

## 任务 8：README 与测试清单

**Files**
- Modify: `README.md`、`tests/test_inventory.py`

- [ ] **步骤 1：把每个测试文件的实际用例数读出来**

```
python -c "
import unittest, importlib
for m in ['tests.test_audio','tests.test_config','tests.test_hotkey','tests.test_matcher','tests.test_pipeline','tests.test_prefetch','tests.test_screen','tests.test_voice_gate','tests.test_ui_state']:
    mod = importlib.import_module(m)
    print(f'{m:28s}', unittest.TestLoader().loadTestsFromModule(mod).countTestCases())
"
```

- [ ] **步骤 2：更新 `tests/test_inventory.py`**

把上面读出的数字写进 `BASELINE_COUNTS`（新增一行 `"tests.test_ui_state": N`），
并把本期新增的关键测试类加进 `REQUIRED_CLASSES`：

```python
    "tests.test_pipeline": [
        ...
        "TestActionStamp",          # 按键动作的时戳（屏幕翻了就不点）
        "TestVoiceNextCommand",     # 说「下一题」= 点下一题
        "TestRunVoiceLoop",         # 主循环能被抽出来单独跑
        "TestHandleIntent",         # 界面按钮调的就是热键那套函数
        "TestCollectState",         # 界面显示的数据来源
    ],
    "tests.test_ui_state": [
        "TestIntents",              # 意图队列
    ],
    "tests.test_matcher": [
        ...
        "TestDetectControl",        # 控制语识别
    ],
```

**切记**：`BASELINE_COUNTS` 的数字只增不减。这里是在**增加**，安全。

- [ ] **步骤 3：更新 `README.md`**

具体四处：

1. **「怎么用」那节**补一段界面用法（`run_gui.bat`、三块区域分别是什么、窗口可拖动）。
2. **`--gui` 参数**加到「命令行参数」清单里。
3. **「文件说明」**里补 `run_gui.bat`、`voice_tap/ui_state.py`、`voice_tap/gui.py`。
4. **「跑测试」**里的 `162 个测试`改成第 1 步实际读出来的总数（并补一句界面部分不可自动测）。

另外核一句**不实描述**：README 现在写着「屏幕上任何可点击的文字都能声控……比如说『下一题』」。
**任务 2 做完之后这句话就成真的了** —— 不要删，改成点明它是通过固定坐标实现的：

> 说「下一题」会直接点「下一题」按钮（走的是固定坐标，不读屏校验），答错进详情页后用它继续。

- [ ] **步骤 4：跑全套 + 清单检查**

```
python -m unittest discover -s tests
python -m unittest tests.test_inventory -v
```

期望：全绿；`test_no_module_lost_cases` 与 `test_critical_behaviours_still_covered` 都过。

---

## 自查

**规格覆盖**：设计文档 1.2 的三个诉求分别落在任务 1（修 bug）、任务 2（语音下一题）、
任务 3–7（界面）；1.4 的「关窗口能立刻退出」落在任务 5 步骤 6；「开关立刻生效」落在任务 5；
「不显示坐标」由任务 6 的 `TestPublishScreen` 钉住。2.1 的七个控件在任务 5 的 `intents` 表里齐全。

**类型一致性**：`ScreenView/OptionView/InputEvent` 三处（任务 3 定义、任务 6 使用）字段名一致；
`identity()`/`stamp` 在任务 1 内自洽；`run_voice_loop` 的签名在任务 4 建立、任务 5 加 `wake_event`、
任务 7 传参，一致。

**与设计文档的一处偏差（有意）**：设计文档 §5 说窗口位置「关窗口时写回 config.yaml」。
计划改成写 `debug/gui_window.txt` —— 因为用 pyyaml 回写会把 `config.yaml` 里那份
逐行注释全抹掉，得不偿失。`config.yaml` 里的 `gui.window` 只作为首次启动的默认值。
**实施完成后应把这一条同步回设计文档。**

**未覆盖 / 已知缺口**：`gui.py` 的控件摆放与渲染无法自动测试（需要显示器），
只能靠任务 7 步骤 6 的人工冒烟；这是设计文档 §7 已声明的取舍。

## 执行方式

计划已就绪。两种跑法：

1. **子代理逐任务（推荐）** —— 每个任务派一个干净的 subagent 去做，做完我来审，再进下一个。
   上下文不会被前一个任务污染，出问题也容易定位。
2. **本会话内逐任务** —— 我在这个会话里按顺序做，到检查点停下来给你看。

**一个提醒**：任务 7 的界面部分**我在这边没法验**（沙箱里没有显示器、也连不到你的手机），
只能靠你按步骤 6 手工跑一遍。前六个任务都是在沙箱里能自动验证的。



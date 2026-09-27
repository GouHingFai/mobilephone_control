# 任务简报：任务 3（ui_state.py —— 线程安全的状态黑板）

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

    def test_thread_safety(self):
        """多线程狂写、同时狂读，不能出错，读到的也得是完整的一份"""
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
        threading.Event().wait(0.3)
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

## 环境提示

- 项目根目录：bash 是 `/sessions/pensive-confident-cerf/mnt/声控手机项目`；文件工具是 `H:\声控手机项目\...`。
- **跑测试前先清字节码缓存**：`rm -rf tests/__pycache__ voice_tap/__pycache__`
  （本仓库 `.py` 与 `.pyc` 常同秒落盘，改动若不改变文件字节数，Python 会复用旧字节码读到错版本）。
- 跑测试：`python3 -m unittest discover -s tests`（**没有 pytest**；沙箱缺 `pypinyin` 就先
  `pip install pypinyin --break-system-packages`）。
- **不要**碰 `.gitattributes` / `core.autocrlf`，**不要**改 `.bat` 文件。
- 这是**纯新增**：`voice_tap/ui_state.py` 是新文件，不影响任何现有代码路径。别去改别的模块。
- 参考：设计文档 §4.1 讲了这一层的职责与接口。

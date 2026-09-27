# 任务 3 报告：`ui_state.py` —— 线程安全的状态黑板

## 状态

**DONE**

起点 **246** 全绿（清缓存后实测）→ 终点 **253** 全绿，新增 **7** 个用例，
与简报期望的「比开跑前多 7 个」**完全一致**。

7 个新用例先确认过因正确原因失败（`ModuleNotFoundError`），再写实现跑通；
另外用三次「故意改坏」的变异实验确认这些用例真的在测东西（见下）。

## 做了什么

纯新增两个文件，**未改动任何现有模块**（`git status` 佐证：除我新增的两个文件外，
只有一份别的流程留下的 `progress.md` 改动，见「偏离计划」）。

### `voice_tap/ui_state.py`（新建，125 行）

顶层含 `from __future__ import annotations`（3.9 兼容，让 `float | None` 这类注解
以字符串形式存在、不在导入时求值）。**刻意不 import tkinter** —— 这正是它能被普通
单测完整覆盖的原因。四样东西：

- `OptionView(index: int, text: str)` —— 界面要显示的一个选项，序号 + 文字，**不含坐标**。
- `ScreenView(prompt, options, source, age_seconds, page, ok, reason)` —— 界面要显示的
  「程序手里那一屏」，字段默认值与简报一致，`options` 用 `field(default_factory=list)`。
- `InputEvent(kind, label, detail, outcome, at)` —— 一条「我的输入」记录。
- `UiState(keep_inputs=8)` —— 状态黑板本体，一把 `threading.Lock` 守两样东西：
  - 主逻辑 → 界面：`set_screen` / `current_screen` / `record_input` / `recent_inputs(limit=5)`
  - 界面 → 主逻辑：`post_intent` / `take_intents`

线程安全的做法：读操作**先在锁内取一份快照（`list(...)` / 整体替换引用），再在锁外返回**。
`set_screen` 换的是整个对象引用（不是原地改字段），所以界面读到的一定是完整的一屏、
不会读到「新 prompt 配旧 options」的撕裂状态 —— 这正是测试 `test_thread_safety` 要锁的东西。

`record_input` 的时间戳补写在**拿锁之前**：补时间戳与入队是两件无关的事，没必要占着锁做。

### `tests/test_ui_state.py`（新建，100 行）

与简报的测试代码**逐字一致**，分三组：
- `TestScreen`（2）：未 set 时 `current_screen()` 为 `None`；set 后往返是**同一对象**（`assertIs`）。
- `TestInputs`（3）：最新在前；`keep_inputs` 上限裁剪；没给时间戳时自动补且 `> 0`。
- `TestIntents`（2）：投递/取出且「取过就没了」；两写一读三线程跑 0.3 秒不卡死、不死锁、
  且最后读到的 `prompt` 是完整的（以 `a-`/`b-` 开头）。

## 测试结果

### 1. 起点是绿的（清缓存后）

```
$ rm -rf tests/__pycache__ voice_tap/__pycache__
$ python3 -m unittest discover -s tests
Ran 246 tests in 10.324s

OK
```

### 2. 失败的测试确实因为正确的原因失败

写完全部 7 个测试、**尚未写实现**时：

```
$ python3 -m unittest tests.test_ui_state -v
ERROR: test_ui_state (unittest.loader._FailedTest)
ImportError: Failed to import test module: test_ui_state
Traceback (most recent call last):
  ...
  File ".../tests/test_ui_state.py", line 13, in <module>
    from voice_tap.ui_state import InputEvent, OptionView, ScreenView, UiState
ModuleNotFoundError: No module named 'voice_tap.ui_state'

Ran 1 test in 0.000s
FAILED (errors=1)
```

是 `ModuleNotFoundError`（模块不存在），不是语法错、不是别的导入错 —— 与简报步骤 2 的期望一致。

### 3. 实现后新用例全绿

```
$ python3 -m unittest tests.test_ui_state -v
test_capped ... ok
test_newest_first ... ok
test_timestamp_filled ... ok
test_post_and_take ... ok
test_thread_safety ... ok
test_none_before_set ... ok
test_roundtrip ... ok

Ran 7 tests in 0.323s
OK
```

### 4. 最终全套

```
$ rm -rf tests/__pycache__ voice_tap/__pycache__
$ python3 -m unittest discover -s tests
Ran 253 tests in 10.676s

OK
```

**246 + 7 = 253**，对上了。

### 5. 变异实验（确认测试不是摆设）

为了证明这 7 个用例真的在测东西、不是「怎么实现都绿」，逐一把实现改坏、跑测试、
再还原（每次改完都清字节码缓存，避免本仓库 `.py`/`.pyc` 同秒落盘的缓存陷阱）：

| 变异 | 预期 | 实际 |
|---|---|---|
| `recent_inputs` 不反转（返回 `items[-limit:]`） | 挂 | `FAILED (failures=2)` |
| `current_screen` 永远 `return None` | 挂 | `FAILED (failures=1, errors=1)` |
| `take_intents` 不消费（不清空队列） | 挂 | `FAILED (errors=1)` |
| 还原后 | 绿 | `OK` |

`diff` 确认还原后文件与改坏前**零差异**，全套 253 仍绿。

## 提交哈希

- **`3f364f7`** —— `feat: ui_state —— 界面与主逻辑之间的线程安全状态黑板`
  （`3f364f7b4cf49c288bfd0a159a3df4f829a8eb67`）
- 提交内容：`create voice_tap/ui_state.py`、`create tests/test_ui_state.py`
  （另含一份**非我改动**的 `progress.md`，见下）。

## 偏离计划的地方

1. **`recent_inputs` 多了一行 `limit <= 0` 的守卫**（简报片段里没有）。
   原因：简报片段的 `items[-limit:][::-1]` 在 `limit=0` 时 `items[-0:]` 等价于
   `items[0:]`，会**返回全部**而不是空 —— 一个潜在的错行为。当前测试没覆盖
   `limit=0`，所以加不加都绿；我选择加一行让它语义正确，并把原因写在注释里。
   这不改变任何被测试的行为，属于修掉计划片段里的一个小瑕疵，非接口变更。

2. **`git add -A` 顺带提交了 `.superpowers/sdd/progress.md`**。
   那份文件的改动**不是我做的** —— 我开工前它就已是 modified 状态（是上一道流程
   把任务 2 标为完成、任务 3 标为「进行中」的台账更新）。简报明确要求按
   `git add -A && git commit` 提交，我照做了，于是它一并进了这次提交。特此说明，
   以免后面的人误以为是我改的台账。

除上述两点外，**代码与测试均与简报逐字一致**，未改任何现有模块，
未碰 `.gitattributes` / `core.autocrlf` / 任何 `.bat`。

## 疑虑

1. **`record_input` 补时间戳在锁外**。多线程下两个线程各补各的时间戳互不影响
   （每个 `InputEvent` 是各自独立的对象），所以是安全的。只是若将来有人改成
   在锁内复用同一个 event 对象，得留意这里。当前无碍。

2. **`ScreenView.options` 的类型是裸 `list`**（简报如此）。界面若拿到一份
   「半构造」的 options 列表不受保护 —— 但按约定主逻辑是**构造好整个 ScreenView
   再 set_screen**，不原地改已 set 进去的列表，所以这份「不变式」目前靠约定而非
   类型系统保证。后续任务 6 的 `collect_state` 写这个对象时，请遵守「构造完整个对象
   再 set」的约定；否则 `test_thread_safety` 那种并发场景可能出现撕裂读。
   这是设计层面的提醒，不是本次的缺陷。

3. 界面（`gui.py`，任务 7）如何消费 `take_intents()` 尚未在这里体现 ——
   本模块只保证队列语义正确，不保证「谁在什么时机调用它」。留给任务 5/6/7。

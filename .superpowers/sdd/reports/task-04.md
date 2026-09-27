# 任务 4 报告：抽出 `run_voice_loop`（纯重构，行为不变）

## 状态

**DONE**

（253 个老测试一个没改地全绿；我对搬前搬后的循环体做了逐行比对，确认是纯搬家。）

## 做了什么

1. **写测试（先红后绿）**
   - `tests/test_pipeline.py` 顶部加 `import threading`（`threading` 的插入位置在 `import re` 之后、
     `import unittest` 之前，保持字母序）。
   - 文件末尾（`if __name__ == "__main__":` 之前）加 `StubHotkeys` 与 `TestRunVoiceLoop`，
     与简报里的代码**逐字一致**。

2. **确认失败是因为正确的原因**
   ```
   $ python3 -m unittest tests.test_pipeline.TestRunVoiceLoop -v
   ...
   ERROR: test_returns_at_once_when_quit_already_requested (tests.test_pipeline.TestRunVoiceLoop)
   AttributeError: module 'voice_tap.main' has no attribute 'run_voice_loop'
   Ran 1 test in 0.003s
   FAILED (errors=1)
   ```
   正是简报期望的那句 `AttributeError`。

3. **实现 `run_voice_loop`**
   - 在 `voice_tap/main.py` 的 `report_unusable_screen` 之后新增模块级函数
     `run_voice_loop(ctx, hotkeys, recognizer, once=False)`，函数体就是原 `main()` 里那段 while，
     **原样照抄、只减去 4 个空格缩进**。

4. **`main()` 里换成调用**
   - 删掉 `try:` 里整段 while，换成 `run_voice_loop(ctx, hotkeys, recognizer, once=args.once)`。
   - `except KeyboardInterrupt` 与 `finally` 三行（`worker_stop.set()` / `hotkeys.stop()` /
     `recognizer.close()`）**内容和顺序一字未动**（已用脚本比对确认）。

## 测试结果

**「失败确实失败」的证据**（写实现之前）：

```
ERROR: test_returns_at_once_when_quit_already_requested
AttributeError: module 'voice_tap.main' has no attribute 'run_voice_loop'
Ran 1 test in 0.003s
FAILED (errors=1)
```

**开跑前基线**：253 全过（`Ran 253 tests ... OK`）
**收尾全套**（已清 `tests/__pycache__` 与 `voice_tap/__pycache__`）：

```
Ran 254 tests in 10.653s
OK
```

**254 = 253 + 1**，与简报「比开跑前多 1 个」完全一致。

**老测试一个都没改** —— `git diff tests/test_pipeline.py` 是「27 行新增、0 行删除」的纯追加，
只在文件头加了一行 import、文件尾加了两个类，没有任何既有测试被触碰。

## 特别说明：我怎么确认「行为没变」的

**光跑测试不够，所以除了 254 绿，我另外做了机械的逐行比对。**

我担心的是那种「测试恰好看不见」的搬运错误 —— 漏个 `continue`、交换两行、
忘记传 `hint_snapshot`、把 `else` 写丢。这类错误现有测试未必抓得住（见下面「疑虑」）。
所以我把旧文件从 git 里取出来，用脚本做了两件事：

1. **循环体逐行比对**：从 `git show HEAD:voice_tap/main.py` 取出旧 `main()` 里
   `try:` 到 `except KeyboardInterrupt:` 之间的 `while` 体，与新版 `run_voice_loop` 里
   `while` 起的函数体，各自去掉公共缩进后逐行比。

   结果：**36 行里只有 1 行不同 —— `if args.once:` 变成了 `if once:`**。
   这正是本任务**唯一**该有的语义改动（把 `args.once` 改成了形参 `once`）。
   其余每一行（两个模式分支、`voice_gate.enabled` 短路、`wait_until_open`、
   `listen_once` 的 `on_speech_start`/`hint_snapshot` 两个实参、`ptt_pressed.wait(0.2)`、
   `listen_pressed` 的 `hint_snapshot`、`utterance is None` 与 `text.strip()` 两道 continue、
   `try/except AdbError`、`--once` 的 `say()`+`say()`+`break`）**逐字节相同**。

2. **`finally` 三行比对**：脚本提取旧、新两版的 `finally:` 块，`repr()` 出来完全一致：
   ```
   '        worker_stop.set()\n        hotkeys.stop()\n        recognizer.close()\n'
   ```

3. **调用点**：`git diff` 显示 `main()` 里只把整段 while 换成一行
   `run_voice_loop(ctx, hotkeys, recognizer, once=args.once)`，`except` / `finally` 原样保留。

也就是说：**「行为没变」这句话，我不只是靠测试绿，我是把旧循环体和新循环体摆在一起
一行行比过、确认只有 `args.once → once` 这一处差异的。**

一处（对读者有影响但不改变行为的）细节要写明：新函数放在 `report_unusable_screen` 之后、
`handle_speech` **之前**，所以函数体里引用的 `handle_speech` 在定义处尚未存在。
这在 Python 里没问题（名字在调用时才解析，模块加载完就有了），但读代码的人会先看到
调用再看到定义 —— 简报指定的就是这个位置，我照做了。

## 提交哈希

```
b9651aa  refactor: 把主循环抽成 run_voice_loop（为界面腾出主线程）
```

## 偏离计划的地方及原因

**一处，且不是代码上的：`git add -A` 带进了三个不是我写的文件。**

按简报要求执行 `git add -A && git commit`，于是这次提交除了我改的两个文件外，
还扫进了**在我开工之前就已经是脏的**四份文档/台账：

| 文件 | 谁改的 | 内容 |
|---|---|---|
| `.superpowers/sdd/briefs/task-04.md` | 派活的编排者 | 就是我手上这份任务简报（未跟踪的新文件） |
| `.superpowers/sdd/reports/task-03-fix.md` | 任务 3 的流程 | 任务 3 的修复报告（未跟踪的新文件） |
| `.superpowers/sdd/progress.md` | 编排者 | 台账：任务 3 标完成、任务 4 标「进行中」 |
| `docs/superpowers/plans/….md` | 任务 3 | 计划里 `UiState` 的 docstring（任务 3 审查的产物） |

我**没有编辑**这四个文件里的任何一个字节，只是 `git add -A` 把它们一起提交了。
之所以没有单独挑文件提交：简报的全局约束与任务末尾都**明确要求** `git add -A`，
我按字面执行；此处照实说明，供你判断要不要把这部分拆出去。

**其余无偏离**：函数名、签名 `run_voice_loop(ctx, hotkeys, recognizer, once=False)`、
放置位置、`main()` 的改法、新增用例数、`finally` 三行 —— 全部与简报逐条相符。
`dispatch_action` / `numpad_worker` 未动；`.bat`、`.gitattributes`、`core.autocrlf` 未动。

## 疑虑

1. **测试对主循环的覆盖其实很薄 —— 这是我最想请你注意的一点。**
   新加的这条用例只验证了「`quit_requested` 已置位 ⇒ 立刻返回、连 `listen_once` 都不碰」，
   也就是**只有循环的入口条件**被测试覆盖。循环体里真正有肉的分支
   —— `voice_gate.enabled` 为假时的 `sleep(0.1)` 短路、`wait_until_open`、
   `listen_once` 的实参、`else`（按住说话）分支的 `ptt_pressed.wait(0.2)` 与 `listen_pressed`、
   `utterance is None` / 空文本两道 `continue`、`handle_speech` 抛 `AdbError` 的兜底、
   以及 `once=True` 的收尾 —— **现有 254 个测试里没有任何一个真的跑过它们**
   （我 grep 过：`listen_once` / `listen_pressed` / `ptt_pressed` 在测试代码里
   除了我新写的桩，一处都没用到）。

   所以这次「行为没变」的保证，**主要来自我那条逐行比对，而不是来自测试**。
   如果你希望这条重构由测试兜底（而不只是靠人眼 diff），那得另开任务给主循环补一层
   假 `Recognizer` + 假 `HotkeyManager` 的驱动测试 —— 现有这套测试结构下补不上。
   我没有擅自扩大范围去做，但把它记在这里。

2. **`run_voice_loop` 排在 `handle_speech` 之前**（简报指定位置），前向引用对 Python 无害，
   但将来若有人把 `handle_speech` 误删或改名，报错会在**运行时**而不是导入时暴露。

3. **后续任务的接口提醒**：简报说任务 5 会给 `run_voice_loop` 加 `wake_event` 参数。
   当前签名把 `once` 放在末尾且带默认值，加参数时请注意别插到 `once` 前面 ——
   本任务里 `main()` 是**按关键字**（`once=args.once`）传的，所以插参数不会静默错位；
   但如果将来有调用方改成按位置传，就会踩到。

4. **字节码缓存**：本仓库 `.py` / `.pyc` 常同秒落盘，而这次改动恰好在 `main.py` 里
   做了「删 36 行、加 46 行」的净增，理论上不至于撞上旧字节码复用；但我每次跑测试前
   都清了 `tests/__pycache__` 与 `voice_tap/__pycache__`，结论可信。

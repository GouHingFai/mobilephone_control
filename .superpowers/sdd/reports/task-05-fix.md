# 任务 5 修复报告：唤醒事件的 clear 挪到循环开头

## 状态

**DONE** —— 缺陷已修、回归测试已补（并验证过「旧位置红、新位置绿」）、两处诚实性小修已做、全套 268 用例全绿。

- 修复提交：`53b45b8d76a28530e842d3593196cae2ef9d69b1`
- 修改文件：`voice_tap/main.py`、`tests/test_pipeline.py`、`tests/test_inventory.py`
  （同一次提交里还带上了任务 5 计划文档的一句澄清，以及审查报告本身 —— 属 `git add -A` 的既有工作树内容）

---

## 改了什么

### 1. `voice_tap/main.py` —— `clear()` 挪到 `while` 循环体最开头

原因（审查发现的 Important／潜伏）：原代码里

```python
ctx["voice_gate"].wait_until_open(hotkeys.quit_requested)
if wake_event is not None:
    wake_event.clear()      # ← 旧位置：在 wait_until_open 之后
stop = _AnyEvent(...) if wake_event else hotkeys.quit_requested
```

`clear()` 落在 `wait_until_open` **之后**。`wait_until_open` 覆盖的正是点击后的静音期（约 2.5 秒）。
用户若在这段时间里点了界面开关，`handle_intent` 置位的 `wake_event` 会被紧跟着的 `clear()` 抹掉，
于是 `stop.is_set()` 报 `False`，监听带着**过期状态**（旧的模式／语音开关）老老实实阻塞进去 ——
一次唤醒被静默吞掉，用户明明点了开关，却要等到下次开口才生效。

现在把 `clear()` 放在 `while` 体最开头（模式判断、`wait_until_open`、构建 `stop` 之前）：

```python
while not hotkeys.quit_requested.is_set():
    # 先把上一轮留下的陈旧唤醒丢掉 —— 必须在循环**最开头**做。
    # （详细的「为什么不能放在 wait_until_open 之后」见代码注释）
    if wake_event is not None:
        wake_event.clear()

    if ctx["mode"] == "listen":
        ...
        ctx["voice_gate"].wait_until_open(hotkeys.quit_requested)
        stop = (_AnyEvent(hotkeys.quit_requested, wake_event) ...)
```

语义变成：只丢「上一轮」的陈旧唤醒；**进等待之后**新到的那一次能活到构建 `stop` 的那一刻，
监听立刻返回、回到顶部重新判断。注释已在代码里写清「为什么 clear 必须在循环开头而不是进监听前」。

`handle_intent` / `dispatch_action` / `numpad_worker` / `main()` 的 try/except/finally 均未改动。

### 2. 回归测试（`tests/test_pipeline.py`）

- 新增 `WakeDuringGate(StubVoiceGate)`：`wait_until_open()` 一被调用就把 `wake_event` 置位，
  精确模拟「静音期里用户点了开关」。
- 给 `StubRecognizerLoop` 加了 `record_stop=False` 开关（**默认关**）：开启后 `listen_once` 会记下
  进监听那一刻 `stop_event.is_set()` 的取值。默认关是必须的 —— `stop_event` 有时是
  `QuitAfterNCalls`，调一次 `is_set()` 就多算一圈，会打乱别的用例对圈数的断言
  （第一版没做成 opt-in，直接让 `test_none_utterance...` 与 `test_blank_text...` 从 2 圈变 3 圈而变红）。
- 新增用例 `TestRunVoiceLoopBranches.test_wake_arriving_during_gate_wait_is_not_swallowed`：
  用假识别器 + 假热键驱动一轮循环（`once=True` 收尾，**不起真线程、不碰真音频**），
  断言 `recognizer.stop_states == [True]` —— 即「唤醒没被丢掉，监听立刻收到中断」。

### 3. 两处诚实性小修

- `tests/test_pipeline.py` 的 `test_adb_error_is_absorbed_and_loop_survives`：docstring 原来暗示它覆盖了循环那层兜底，
  已改为如实说明 —— 这条钉的是**结果**「异常不会掀翻循环」，不是循环里那个 `except AdbError` 分支本身
  （审查实测：删任意一层都还绿，两层同删才红；且主循环那层目前不可达）。**没有**为「真覆盖到分支」加桩。
- `tests/test_inventory.py` 的 `REQUIRED_CLASSES["tests.test_pipeline"]` 补上四个类：
  `TestRunVoiceLoopBranches`、`TestHandleIntent`、`TestToggleFlag`、`TestAnyEvent`。
  原因：此前整类删掉仍高于基线（不会报警），而 test_inventory 的立意正是防这个。

---

## 两次实验的结果（旧位置红 → 新位置绿）

用 `git stash push -- voice_tap/main.py` 把 `main.py` 临时退回到旧位置，跑**最终版**测试代码，再 `git stash pop` 恢复。
两步之间都先 `rm -rf tests/__pycache__ voice_tap/__pycache__`。

**① 旧位置（`clear()` 在 `wait_until_open` 之后）—— 红：**

```
FAIL: test_wake_arriving_during_gate_wait_is_not_swallowed (test_pipeline.TestRunVoiceLoopBranches)
AssertionError: Lists differ: [False] != [True]
First differing element 0:
False
True
 - [False]
 + [True] : 静音期里到达的唤醒被吞了 —— 进监听时 stop_event 没报置位，监听会带着过期状态阻塞进去。
           clear() 必须在循环开头，不能放在 wait_until_open 之后。
Ran 1 test in 0.450s
FAILED (failures=1)
```

旧位置下跑**全套**：`Ran 268 tests ... FAILED (failures=1)` —— 唯一失败的就是这条新用例。
**其余 267 条全绿**，正面证明了这个缺陷此前是「潜伏」的（没有任何现存测试能逮到它）。

**② 新位置（`clear()` 在循环开头）—— 绿：**

```
Ran 1 test in 0.444s
OK
```

新位置下跑整套：

```
Ran 268 tests in 11.951s
OK
```

---

## 最终用例数

- 起点：267 全过。
- 现在：**268 全过**（`python3 -m unittest discover -s tests`），新增的正是那条唤醒回归用例。
- `tests.test_pipeline` 用例数：77（仍高于基线 59）。
- `test_inventory` 的三个检查（用例数基线、关键类存在、可收集）全部通过。

## 提交

- `53b45b8d76a28530e842d3593196cae2ef9d69b1` —— `fix: 唤醒事件的 clear 挪到循环开头（审查发现的丢失窗口）`

## 疑虑 / 备注

1. **报告单独成一次提交**（`docs:`）而非并进 fix 提交：本仓库的既有惯例是报告走 `docs:` 提交（HEAD 就是
   `docs: 任务 5 报告…`）。这样报告里引用的 fix 提交哈希才是准确、指得上的。若更希望合并成一次提交，可 squash。
2. **`test_pipeline` 的用例数基线（`BASELINE_COUNTS`）未上调**：本任务只要求补 `REQUIRED_CLASSES`。
   现在基线 59、实际 77，余量很大 —— 若日后想更紧地防「悄悄变少」，可把基线提到 77，但那超出本任务范围，未动。
3. **唤醒机制仍未被 `main()` 接线**（`main()` 目前还不传 `wake_event`）—— 这是任务 7 的事。
   本条修复保证的是：一旦接上线，机制就是对的。
4. **审查另外提到的几处未动**（均被判为不修或超出范围）：`stop_event=stop` 无独立测试、
   `dispatch_action` 的 intent/quit 分支零覆盖、`intents` 表无测试。按指令只做了本任务列出的三件事。

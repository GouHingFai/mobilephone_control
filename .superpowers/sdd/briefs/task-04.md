# 任务简报：任务 4（抽出 run_voice_loop —— 纯重构，行为不变）

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

## 环境提示

- 项目根目录：bash 是 `/sessions/pensive-confident-cerf/mnt/声控手机项目`；文件工具是 `H:\声控手机项目\...`。
- **跑测试前先清字节码缓存**：`rm -rf tests/__pycache__ voice_tap/__pycache__`
  （本仓库 `.py` 与 `.pyc` 常同秒落盘，改动若不改变文件字节数，Python 会复用旧字节码读到错版本）。
- 跑测试：`python3 -m unittest discover -s tests`（**没有 pytest**；沙箱缺 `pypinyin` 就先
  `pip install pypinyin --break-system-packages`）。
- **不要**碰 `.gitattributes` / `core.autocrlf`，**不要**改 `.bat` 文件。

## 这个任务的性质：纯搬家，行为一点都不能变

把 `main()` 里那段 while 主循环原样搬成模块级函数 `run_voice_loop`，
好在带界面时把它丢到后台线程去跑（Tkinter 要求主线程）。

**这是纯重构**：搬完之后，不带 `--gui` 时程序行为必须和现在**完全一致**。
判断标准就是那 253 个现有测试 —— **它们必须一个不改地全绿**。
如果有测试挂了，说明搬家时漏了东西（漏了某个分支、改了顺序、忘了传参），
**回去看代码，不要改测试**。

`main()` 里 `try / except KeyboardInterrupt / finally` 那一层（`finally` 里
`worker_stop.set()` / `hotkeys.stop()` / `recognizer.close()` 三行）保持原样，
只是把中间的 while 循环换成一次 `run_voice_loop(...)` 调用。

## 跨任务提醒

- 动作分派唯一入口是 `dispatch_action(action, ctx)`（模块级，任务 1 的修复抽出来的），
  它属于小键盘工作线程，**和主循环无关**，本任务不要动它。
- 后面任务 5 会给 `run_voice_loop` 加一个 `wake_event` 参数，所以签名设计得便于扩展。

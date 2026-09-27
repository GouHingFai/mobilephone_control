# 任务简报：任务 8（README 与测试清单）

## 项目是什么

`voice_tap`：Windows 上的声控工具。用户用 scrcpy 投屏安卓手机玩 GRE3000 背单词，
开口说选项、或按小键盘数字，程序读屏后自动点对应选项。**代码与注释全中文，
你写的注释、提交信息也用中文。** 本轮刚给它加了置顶浮窗界面与语音「下一题」。

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


## 本任务还要一并收的尾巴（来自前几轮审查，务必做完）

### A. 补一条测试，覆盖 `_input_kind_and_label` 的 `next` 分支

任务 6 的审查**实测**：把 `main.py` 里 `_input_kind_and_label` 的「`("next",)` → `kind="next"`」
那一支改成 `speech`，**307 条仍全绿** —— 也就是说小键盘 `0` / 语音「下一题」那条点击
在界面「我的输入」里会被标成 `speech`，而没有任何测试会发现。

请补一条：调 `handle_next(ctx)`（ctx 带一个真 `UiState`），断言 `recent_inputs()` 里的条目
`kind == "next"`、`label == "0"`。**先确认它在修好之前是红的**（你可以先把那支改成 speech 试试）。

### B. 测试清单按实际数字补全

- `BASELINE_COUNTS` 里每个文件的数字，改成**实际读出来的**（不只 `test_pipeline`；
  本轮往 `test_config`、`test_ui_state`、`test_matcher` 都加过用例）。
- `REQUIRED_CLASSES` 补齐本轮新增的关键类：`TestDetectControl`、`TestVoiceNextCommand`、
  `TestCollectState`、`TestUiStateWiring`、`TestUiWiringWithoutUi`、
  `tests.test_ui_state` 的 `TestIntents`、`TestWindowGeometry`。
  （已有的 `TestActionStamp`/`TestActionWiring`/`TestRunVoiceLoopBranches`/`TestHandleIntent`/
  `TestToggleFlag`/`TestAnyEvent` 应已在里面，核对一下。）
- **然后验证清单真的在起作用**：临时把某个 `REQUIRED_CLASSES` 里列着的类删掉（或改名），
  跑 `tests.test_inventory`，确认它会红；再还原。

### C. README 的三处

除下面计划正文里写的那三处，**再加一处**：把「已知限制」或「出问题时」那节补一条 ——
**界面打开后如果关不掉**（真机上万一 Tk 行为不符预期），可以先按窗口的 X，
或者直接用 `run.bat`（不带界面）跑。


## 环境提示

- 项目根目录：bash 是 `/sessions/pensive-confident-cerf/mnt/声控手机项目`；文件工具是 `H:\声控手机项目\...`。
- **跑测试前先清字节码缓存**：`rm -rf tests/__pycache__ voice_tap/__pycache__`
  （本仓库 `.py` 与 `.pyc` 常同秒落盘，改动若不改变文件字节数，Python 会复用旧字节码读到错版本。
  做「改坏看红不红」的实验时尤其必须。）
- 跑测试：`python3 -m unittest discover -s tests`（**没有 pytest**；沙箱缺 `pypinyin` 就先
  `pip install pypinyin --break-system-packages`）。
- 别 `import tkinter`（沙箱多半没装）。
- **不要**碰 `.gitattributes` / `core.autocrlf` / `.bat` 文件。

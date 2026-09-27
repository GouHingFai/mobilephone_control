# 任务 8 报告：README 与测试清单

## 状态

**DONE**

（三块都做完了、且都验证过：测试清单按**实际读出的**数字补全并证明它会红；
补上 `_input_kind_and_label` 的 `next` 分支覆盖并做了「先红后绿」；
README 四处 + 尾巴 C 一处改完。全套 **308 全绿**，提交 `7066c3c`。

有一处**有意偏离简报**（README 的诚实性修正，见「偏离」第 1 条）与一处**清单外残留**
（设计文档未同步，见「疑虑」第 1 条）。这两条都不会让交付物出问题，故仍判 DONE。）

## 做了什么

### 块一：补测试清单（`tests/test_inventory.py`）

步骤 1 实际读出的用例数（`python3 -c ...` 逐模块读，清过字节码缓存）：

| 文件 | 实际 | 原基线 | 新基线 |
|---|---|---|---|
| `tests.test_audio` | 19 | 19 | 19 |
| `tests.test_config` | 34 | 34 | 34 |
| `tests.test_hotkey` | 25 | 25 | 25 |
| `tests.test_matcher` | 53 | **51** | **53** |
| `tests.test_pipeline` | **103** | **59** | **103** |
| `tests.test_prefetch` | 26 | 26 | 26 |
| `tests.test_screen` | 27 | 27 | 27 |
| `tests.test_ui_state` | 7 | （缺） | **7（新增一行）** |
| `tests.test_voice_gate` | 11 | 11 | 11 |
| （`tests.test_inventory` 自身） | 3 | — | — |

`test_pipeline` 的 103 = 我新加那条测试**之前**的 102 + 1。
（注：`progress.md` 写的是「实际 101」，我实测是 102 —— 台账那个数已经旧了一位，
见「疑虑」第 4 条。）

`REQUIRED_CLASSES` 新增（尾巴 B + 计划 step 2）：

- `tests.test_pipeline`：`TestVoiceNextCommand`、`TestCollectState`、`TestUiStateWiring`、
  `TestUiWiringWithoutUi`、`TestRunVoiceLoop`
- `tests.test_matcher`：`TestDetectControl`
- `tests.test_ui_state`：`TestIntents`（**新增整个模块条目**）
- 核对已有的：`TestActionStamp`／`TestActionWiring`／`TestRunVoiceLoopBranches`／
  `TestHandleIntent`／`TestToggleFlag`／`TestAnyEvent`／`TestWindowGeometry` 都已在表里。

`TestRunVoiceLoop` **不在尾巴 B 的清单里**，但计划正文 step 2 明确列了它，且它是本轮
（任务 4）新增的关键行为（「主循环能被抽出来单独跑」），所以我按**只增不减**加了进去 —— 见「偏离」第 2 条。

同时改了那段已经过时的注释（原文写「整类删掉时剩余用例数仍高于基线（72→65 > 59）」——
基线拉到 103 之后这个前提不成立了，留着就是假话），改成如实说明：这一批是按**名字**钉住的，
即便被人改名换成等量无关测试、总数对得上，也会红。

### 块二：补一条漏掉的测试覆盖（尾巴 A）

加在 `tests/test_pipeline.py` 的 `TestNextButton` 里（`handle_next` 的自然归属）：

```python
def test_next_click_is_recorded_as_next_not_speech(self):
    ctx, fake = make_ctx(DETAIL_XML, ui=UiState())
    ctx["cfg"].click.settle_ms = 0
    ctx["cfg"].hotkey.fixed_next_position = (909, 2476)
    app.handle_next(ctx)
    self.assertEqual(len(fake.taps), 1, "先确认这一下真的点了")
    events = ctx["ui"].recent_inputs()
    self.assertEqual(events[0].kind, "next", ...)
    self.assertEqual(events[0].label, "0")
```

`voice_tap/main.py` 一行没动（`git diff` 空；`git log -1 -- voice_tap/main.py` 仍是上一个提交）。

### 块三：README（计划 4 处 + 尾巴 C 1 处）

1. **「怎么用」**：新增一段界面用法 —— `run_gui.bat`、三块区域（控制／程序读到的屏幕／我的输入）、
   窗口可拖动且会记住位置。
2. **「命令行参数」**：加了 `--gui` 一行。
3. **「文件说明」**：加了 `run_gui.bat`、`voice_tap/ui_state.py`、`voice_tap/gui.py`；
   `tests/` 的 `162 个` → `308 个`。
4. **「跑测试」**：`162 个测试` → `308 个测试`；新增「界面状态」一条覆盖项；
   补一句 `gui.py` 不可自动测及为什么。原文「覆盖七块」与实际列了 8 条不符（又添了第 9 条），
   改成「覆盖这些方面」——见「偏离」第 3 条。
5. **尾巴 C**：「出问题时」表加一行「界面（浮窗）关不掉」——先按窗口 X，都不行就用 `run.bat`。

另外**核掉了那句不实描述**（见「偏离」第 1 条）。

## 验证结果

### 尾巴 A：先红后绿（字节码缓存每次清过）

把 `main.py` 里 `_input_kind_and_label` 的 `("next",)` 那一支**临时改成 `speech`**：

```
FAIL: test_next_click_is_recorded_as_next_not_speech
AssertionError: 'speech' != 'next'
- speech
+ next
 : 这一下是「下一题」，不能标成别的种类
Ran 1 test ... FAILED (failures=1)
```

**改回** `next` 之后：`TestNextButton` 6 条全过，且 `git diff voice_tap/main.py` 为空
（说明我确实只做了「改坏 → 改回」的临时实验，`main.py` 与改前逐字节相同）。

### 尾巴 B：清单真的会红（两次独立实验，各自证明一半）

**实验一 —— 证明 `REQUIRED_CLASSES` 独立于「用例数」在起作用**：
把 `TestCollectState` 改名成 `TestCollectStateRenamed`（**用例数一个不变**，只是名字没了）：

```
AssertionError: Lists differ: ['tests.test_pipeline 里找不到 TestCollectState'] != []
Ran 3 tests ... FAILED (failures=1)
```

**只有** `test_critical_behaviours_still_covered` 红了（failures=1），
`test_no_module_lost_cases`（数数那条）**仍是绿的** —— 正是要证明的那一点。

**实验二 —— 证明拉紧后的基线能抓「少一个用例」**：
把新加那条测试的方法名临时改成 `zz_test_...`（不被收集，103 → 102）：

```
AssertionError: ['tests.test_pipeline 少了 1 个用例（现在 102，基线 103）'] != []
FAILED (failures=1)
```

两次实验都已还原；`git diff --stat tests/test_pipeline.py` 只剩 `+21`（就是新增那条测试）。

### 最终全套

```
$ rm -rf tests/__pycache__ voice_tap/__pycache__
$ python3 -m unittest discover -s tests
Ran 308 tests in 12.0s

OK
```

`python3 -m unittest tests.test_inventory -v`：3 条全过
（`test_no_module_lost_cases` 与 `test_critical_behaviours_still_covered` 都在）。

## 提交

```
7066c3c7c5e017032c8177c46a91c05bf8c87305
docs: README 与测试清单收尾
3 files changed, 69 insertions(+), 12 deletions(-)
```

（`README.md` / `tests/test_inventory.py` / `tests/test_pipeline.py` 三个文件。
提交信息用的是简报里指定的那句；严格说它含一条新测试，`docs:` 前缀略微不准，
但简报指定了原文，我照用，在此说明。）

未触碰 `.gitattributes` / `core.autocrlf` / 任何 `.bat`；未 `import tkinter`。

## 偏离计划的地方及原因

1. **README 那句「不实描述」我改得比简报要求的多（有意）**。
   简报说「不要删，改成点明它是通过固定坐标实现的」，并给了替换句。
   但原文的整句是：「屏幕上任何**可点击的文字**都能声控，不只是选项。比如说
   「下一题」「继续」「返回」，只要这些字确实显示在屏幕上，就能点。」——这句里
   **不止「下一题」一处不实**：
   - `screen.py:256` 只把 `resource-id` 是 `ID_OPTION` 的节点收进 `snap.options`，
     `handle_speech` 只拿 `snap.options` 去 `matcher.match`。所以**除选项外没有「念文字就能点」**这条路。
   - 「返回」不在 `matcher.NEXT_PHRASES` 里，说它**根本不会**触发任何点击。
   - 「只要这些字确实显示在屏幕上，就能点」这个**机制描述是反的** ——「下一题」走的是固定坐标，
     跟字在不在屏幕上无关。
   硬性约束说「README 里凡是……**行为描述**，都要和代码实际一致」，且本项目有前科。
   照简报字面留着「任何可点击的文字」「返回」，等于再造一次这种不一致。所以我把整句重写为：
   说「下一题／下一词／下一个／继续／next」= 点「下一题」（**走的是固定坐标，不读屏校验**），
   并**明确点出「这不是念出屏幕上的字」**、别的按钮文字（举例「返回」）暂不支持。
   简报给的替换句原样用在了「下一题」那半句上。保留了「继续」是因为它**确实是**控制语
   （在 `NEXT_PHRASES` 里）。
2. **`REQUIRED_CLASSES` 多加了 `TestRunVoiceLoop`**：计划正文 step 2 列了它，尾巴 B 的清单没列。
   它是本轮任务 4 新增的关键行为，加进去符合「只增不减」，无害。若认为多余，删掉一行即可。
3. **「覆盖七块」改成「覆盖这些方面」**：那一节本来列了 8 条却说「七块」，本就不符。
   我新增「界面状态」一条后变成 9 条，与其写一个同样脆弱的数字，不如去掉数词。
   README 里真正改掉的**数字**只有 `162` → `308`（两处）。
4. 新那条测试放在已有的 `TestNextButton` 里，没另立类（简报未指定位置；`TestNextButton`
   就是「小键盘 0 = 下一题」的归属）。

## 疑虑

1. **【清单外残留，需计划方决定】设计文档没同步**。简报「自查」小节写着
   「实施完成后应把这一条同步回设计文档」—— 指窗口位置**不写回 `config.yaml`、
   改写 `debug/gui_window.txt`** 这处有意偏差。设计文档里两处仍是从前的说法：
   - `docs/superpowers/specs/2026-09-27-gui-and-voice-controls-design.md:275`（§4.2）：
     「几何位置从 `gui.window` 读，关闭时写回配置。」
   - 同文件 `:325`（§5 的 yaml 片段）：「关窗口时会把当前值写回这里。」
   我**没有改**，理由：本任务的「三块」+ 尾巴 A/B/C 都未包含它，`progress.md` 的
   「任务 8 的待办」4 条里也没有它 —— 看起来是计划方（你）的实施后收尾，不是实现者的任务。
   若你要的是一并做掉，改起来就两处、纯文档，我可以再补一个提交。
2. **README 新句里「不读屏校验」有前提**：只有当 `hotkey.fixed_next_position` 有值（随包
   `config.yaml` 是 `[909, 2476]`）时才成立；若用户把它设成 `null`，`handle_next` 会改为读屏找按钮。
   同页下方「关于『下一题』」已经把 `null` 那条路写清楚了，所以我没有给新句加限定语
   （那句是简报指定的原文）。若你觉得该加，我改。
3. **「308」的口径**：这是 `python -m unittest discover -s tests` **实际打印**的数
   （含 `test_inventory` 自己的 3 条）。9 个「内容」测试文件相加是 305。
   我选 308，因为那是用户跑这条命令会看到的数，最可核对。
4. **台账数字漂了一位**：`progress.md` 写「现在 test_pipeline 实际 101」，
   我实测（清缓存后）是 **102**（加我这条之前）。不影响本次结果（我以自己实测为准），
   仅提醒台账该更。（`progress.md` 归你维护，我没动。）
5. **界面本体仍未验**：`progress.md` 里任务 7 标着「沙箱验不了，需用户人工冒烟」。
   我这边同样没有显示器、连不到手机，所以 README 里新增的界面用法（三块区域、
   拖窗、记位置）是**照 `gui.py`／`config.yaml` 的代码写出来的**，不是上机看出来的。
   措辞我按代码能支撑的范围写（没有写「界面工作正常」这类我验不了的判断）。
6. README 里其它我没动、但顺带核过的点：小键盘按键表、`fixed_next_position` 的默认值、
   「预读」的原理段，都与代码相符。

# 任务 5 报告：文档与测试清单收尾

## 状态：DONE

提交 `ed03eb1`（`docs: 本轮改动同步进 README／设计文档／测试清单`）。
**332 个用例全绿**；`tests/test_inventory.py` 的每一处基线都**贴着实测值**（没有一个富余）。
「清单真会红」实验按预期红、已还原。

只改文档与两处注释，**没有动任何测试断言、没有碰 `.gitattributes` / `core.autocrlf` / `.bat`**。

---

## 起点

```
rm -rf tests/__pycache__ voice_tap/__pycache__
python3 -m unittest discover -s tests
→ Ran 332 tests … OK
```

与父任务给的一致（无需 `pip install pypinyin`，沙箱里已有；全程没有 import tkinter，
`gui.py` 只做 `compile()` 语法校验）。

---

## 一、`tests/test_inventory.py`

### 1.1 基线数字（按实际读出来的写，逐条注明理由）

| 文件 | 原基线 | 新基线 | 为什么 |
|---|---|---|---|
| `tests.test_config` | 34 | **36** | 任务 3：`voice.next_command`（默认 true）并入 `voice.commands` 并改成**默认关**。用例从 `TestVoiceNextCommand`（3 条）换成 `TestVoiceCommandsSwitch`（5 条），净 **+2**。 |
| `tests.test_matcher` | 53 | **57** | 任务 3：`voice.commands` 关掉「说序号」这条路、退回文字匹配，`TestOrdinalCanBeDisabled` **+4**。 |
| `tests.test_pipeline` | 120 | **120（不变）** | 任务 4 已把 104→120 写准，实测仍是 120。 |
| 其余 7 个文件 | — | 不变 | `test_audio` 19、`test_hotkey` 25、`test_prefetch` 27、`test_screen` 27、`test_ui_state` 7、`test_voice_gate` 11，全部与实测相符。 |

> **这是本任务找到的一处真问题**：`test_config` 与 `test_matcher` 的基线**前几轮就落后于实际值了**
> （任务 3 加了用例却没同步基线）。数字低于实际不报错，所以一直没被发现 —— 但基线贴着实际值
> 才是它的意义所在（整类被删时才会掉到基线以下）。现已补齐，理由都写在该文件里。

### 1.2 `REQUIRED_CLASSES`

- **新增**（本轮新加的关键类）：
  - `tests.test_pipeline` / `TestUnwiredIntents` —— 界面会发、意图表里却没有的名字要当场喊出来。
    这是本轮「界面按钮静默死掉」那次事故的护栏。整类删掉时用例数会掉到基线以下，但**改成等量的
    无关测试就发现不了**，所以按名字钉住。
  - `tests.test_matcher` / `TestOrdinalCanBeDisabled` —— `voice.commands` 关掉后序号说法退回文字匹配。
  - `tests.test_config` / `TestVoiceCommandsSwitch` —— **新建了 `tests.test_config` 这一条模块项**
    （原先该模块不在 `REQUIRED_CLASSES` 里）。本轮唯一改了默认值的开关就在这个类里，
    且它必须保证老键 `next_command` 彻底消失（不能留一个能改回来的影子）。
- **改名同步**：`TestToggleFlag` 的注释「界面上的预读／语音下一题开关」→「预读／语音选择开关」
  （任务 3/4 已把标签改成「语音选择」）。
- **`TestActionStamp` 无需再删**：任务 1 已删除，实测全仓已无此名（本任务确认）。

---

## 二、其它文档改动（逐条）

### 2.1 `config.yaml`
- `asr.language` 注释补上：填 `en` 也支持；并写明**可在界面上点「识别语言」循环切换（自动→中文→英文）**。
- （核对）`prefetch.click_max_attempts` 已不存在（实测 `hasattr(cfg.prefetch,'click_max_attempts') == False`）；
  `voice.commands: false` 已是现状。这两项在任务 1–4 就改完了，本任务只做核对。

### 2.2 `README.md`
- 「怎么用 · 说法二（说序号）」补一段：**说法二默认关**，要开就在界面点「语音选择」或改 `voice.commands`；
  说选项里的词（说法一）不受影响。
- 热键表补 `F7` 一行（原来表里漏了它，而界面按钮上就印着「语音 F7」）；
  并补一句「记不住键？开界面时每个控件旁都标着快捷键」。
- 「固定控制语」段落补：与「说序号」共用一个开关 `voice.commands`、默认关、为什么关（真机日志）、怎么打开。
- 「控制区」描述从「**五个开关**（…语音说下一题）」改成「**六个控件**（…语音选择、识别语言）」，
  并写明**每个控件旁标出快捷键、键名取自配置、无按键的不标**。
- 配置表：`prefetch.click_delay_ms` 行补「预读**最多读两次**」；新增 `voice.commands` 行（默认关 + 怎么开）。
- 新增小节 **「关于语音控制语」**（为什么默认关、开着管哪两件事、怎么打开）。
- 「关于预读」段把「第 1 次／第 2 次／第 3 次」整套说法改掉：改为**日志实际会打的那几行**，
  并补「**最多读两次**」；另加一段**诚实的代价说明**（翻页晚于两次读屏时，第二次读到的仍是旧屏会被收下）。
- 「关于『下一题』」补：小键盘 `0` 不受 `voice.commands` 影响，语音说「下一题」要开着它。
- 排错表 4 行更新：说序号／说「下一题」需先开 `voice.commands`；「说了但没点」先查开关。
- 数字：`tests/` 文件说明与「跑测试」段的 **308 → 332**；覆盖清单补「界面控件（数据驱动 + 未接线护栏）」
  与「最多两次」，并把匹配引擎那条补上「序号退回文字匹配」。

### 2.3 `docs/原理与实现.md`
- §2.3 匹配阶梯流程图后补一段：**第 ① 级（说序号）与「说下一题」归 `voice.commands` 管、默认关**（附理由）。
- §四 ③ 读屏那段：把「预读没做成（读屏太慢、或者界面本来没翻页）」改成
  「两次读屏都失败、或结果过期」——**「界面本来没翻页」不再是一次落空**了。
- §四「怎么调点击后等多久才读」：日志示例去掉「第 1 次」；解释改成实际会打的行；
  加「**最多读两次**」；流程图把「等太短 → 白读一次」改成「只好再读一次确认」；
  并删掉「等待时间只影响效率，不影响正确性」这句**已经不再成立**的话（见上文代价说明）。
- §6.4 / §七 两处「直接说序号」补「需先打开 `voice.commands`」。
- 附录文件图：`TEST` 节点 **141 → 332**；补 `ui_state.py` / `gui.py` 两个节点与它们的状态/意图连线。
- 三处日志示例 `[预读] 第 1 次读到新界面` → `[预读] 读到新界面`（与 `main.py` 实际打印一致）。

### 2.4 `docs/superpowers/specs/2026-09-27-gui-and-voice-controls-design.md`
- 抬头加一行 **「2026-09-28 后续变更」**（动作时戳取消 / 并入 `voice.commands` 且默认关 / 预读最多两次 /
  控件数据驱动并标快捷键），并声明「正文保留原样作记录，与这四处冲突以变更说明为准」。
- **§2.2** 末尾加「2026-09-28 调整：并入 `voice.commands` 开关，且默认关」，写明老键删除、默认值翻转、
  依据的真机日志片段、主力路径不受影响、界面控件名与意图名。
- **§2.3** 末尾加「**2026-09-28 取消**」，写明真机日志里的 **9 次误伤、其中 7 次不同键**，
  以及「要防的那个 bug 一次都没出现」，并列出被删掉的三处实现与消失的 outcome 出路。
- 顺手修掉同文档里其它过时描述（均加日期标注，不抹掉原文）：
  §3.3 队列示例的 `stamp`（→ 二元组）、§3.5 文件清单的 `next_command`、§4.1 `InputEvent.outcome`
  示例串、§4.4 两处 `cfg.voice.next_command`、§4.5 加「整体取消」横幅、§5 配置片段加「本段不成立」注。

### 2.5 `tests/test_prefetch.py`（仅 docstring）
`test_logs_include_timing` 的 docstring 去掉了「第几次」，改成「读到新界面、还是又读一次确认了」，
并注明「预读最多两次，没有第 3、4 次」。**该用例的断言一字未动。**

### 2.6 `voice_tap/ui_state.py`（仅注释）
`InputEvent.outcome` 的示例串 `"已忽略：界面已翻页"` **已删除**（那条出路不存在了），
换成实际会产生的四种：`点了第 4 个` / `已跳过（防连点）` / `没匹配上：…` / `已拒绝：…`，
并注明原因（动作时戳已取消）。**代码逻辑未动。**

---

## 三、「清单真会红」实验结果

按父任务要求做的是**改名**（不是删除），因为要顺带证明「光靠数字发现不了」：

```
sed -i 's/^class TestUnwiredIntents(unittest.TestCase):/class TestRenamedForExperiment(unittest.TestCase):/' tests/test_pipeline.py
rm -rf tests/__pycache__ voice_tap/__pycache__
python3 -m unittest tests.test_inventory
```

结果：

```
Ran 3 tests … FAILED (failures=1)
- ['tests.test_pipeline 里找不到 TestUnwiredIntents']
+ [] : 关键行为的测试不见了：
      tests.test_pipeline 里找不到 TestUnwiredIntents
```

**关键点：3 条用例里只有 1 条红** —— `test_no_module_lost_cases`（数数那条）**照常绿**，
因为改名不改用例数（120 不变）。这正好说明「基线数字」与「必备类名字」是两道**互补**的护栏，
少了后者就抓不住「类被换成等量无关测试」这种情况。

已用备份还原，还原后 `grep -c 'class TestUnwiredIntents'` == 1、`git status` 干净、
全套复跑 332 全绿。

---

## 四、最终数字

- 全套：**Ran 332 tests … OK**（每次实验前都清过 `__pycache__`）
- 逐文件实测 = 基线，**零富余**：
  `test_audio 19 / test_config 36 / test_hotkey 25 / test_matcher 57 / test_pipeline 120 /
  test_prefetch 27 / test_screen 27 / test_ui_state 7 / test_voice_gate 11`（合计 332）
- `REQUIRED_CLASSES` 9 个模块共 45 个类，**缺 0 个**
- 提交：`ed03eb1cce4dd686568c15892ec46d5683a11e18`

---

## 五、我顺手改掉的、不在清单里的过时描述

1. **`test_inventory.py` 里两条落后于实际的基线**（`test_config` 34→36、`test_matcher` 53→57）。
   这是清单本身失效，比文档过期更值得报。
2. **`README.md` 热键表漏了 `F7`** —— 而任务 4 刚在界面按钮上印了「语音 F7」，两处对不上。
3. **`docs/原理与实现.md` §四 ③** 「或者界面本来没翻页才会当场读」——重构后「没翻页」不再导致落空。
4. **同文件「所以等待时间只影响效率，不影响正确性」** —— 改成最多两次后不再成立，已改写。
5. **同文件附录文件图缺 `ui_state.py` / `gui.py`**，且测试数字停在 141（两轮前的数字）。
6. **`README.md` 的「控制区」还写「五个开关…语音说下一题」** —— 现在是六个控件、且叫「语音选择」。
7. **设计文档 §3.3 的队列三元组、§4.1 的 outcome 示例串、§4.4/§5/§3.5 的 `next_command`** ——
   都是会被人照抄的实现细节，已加日期标注修正。
8. **`README.md` 里「它不会读错」这句**（预读段）—— 改成最多两次后**不再是绝对保证**
   （翻页晚于两次读屏时会收下旧屏）。改写成「不会拿『还没翻页』的界面当翻好的用」，
   并补一段代价说明。这条是本轮最需要留意的措辞诚实性问题，请重点看。

> 我**没有**动 `docs/superpowers/plans/` 下的任何计划文件（含 09-28 那份姊妹计划，
> 「连按两下同一个键仍会点两次」按简报要求保留）—— 它们是当日的历史记录。

---

## 疑虑

1. **「语音选择」这个标签有歧义**（任务 4 报告里也提过）：它翻的是 `voice.commands`，
   同时管「说序号」和「说下一题」，字面上却像「选语音输入设备」。我在 README 里用一整节
   「关于语音控制语」把它的含义讲透了，但**按钮文字本身没改**（改标签要动 `main.py` 与
   一批断言，超出本任务范围）。建议真机上让用户看一眼确认措辞。
2. **`README.md` 那段「代价说明」是我新写的**，依据是任务 2 审查报告第 3 条（两次读屏后仍收下旧屏
   的窗口）与 `main.py` 的实际分支。措辞我尽量保守，但**这条行为在沙箱里没法真机验证**。
3. **真机收益依旧没量**：预读最多两次、动作时戳取消这两项，都要靠下一份真机日志确认
   （尤其是恢复「按了就有反应」之后有没有新的误点）。
4. **`TestVoiceNextCommand`（test_pipeline 里的类名）保留了旧名字**：它测的是「说『下一题』= 点下一题」
   这条行为，行为没变，只是开关改名了。我在 `REQUIRED_CLASSES` 里保留了它。若评审觉得叫
   `TestVoiceCommands` 更准，改名要同步改 `test_inventory.py`，属可选清理。
5. `voice_tap/ui_state.py` 的注释现在是三行，比原来长；如果嫌啰嗦可以压成一行，但不改也不影响。

# 任务 3 报告：语音控制开关 + 识别语言可选（逻辑层）

## 状态：DONE_WITH_CONCERNS

主交付完成、**320 个用例真全绿**、7 处「改坏看红不红」全部按预期变红并已还原。
定这个状态不是因为有没做完的活，而是因为**照计划原文做会直接报错**，我在三处
必要地偏离了简报（尤其 `collect_state`），另外「识别语言」那一半**不需要写代码**
（配置项早就接好了）。下面逐条说清，别当成「偷偷改计划」。

---

## 做了什么

### 1. 语音控制开关（说序号 + 说下一题 合并成一个，默认关）

| 文件 | 改动 |
|---|---|
| `voice_tap/config.py` | `VoiceConfig.next_command: bool = True` → **`commands: bool = False`**（注释写明它管哪两样、为什么默认关、**说单词选选项不受它管**）；`load_config` 那行跟着换成读 `"commands"` |
| `config.yaml` | `voice.next_command: true` → **`commands: false`** + 注释（含真机日志依据、默认关的理由、不受它管的范围） |
| `voice_tap/matcher.py` | `match(spoken, options, cfg=None, allow_ordinal=True)` —— 新增第 4 个参数；`if allow_ordinal:` 把原来的序号段整个套住（关掉时**整个跳过**，连 `ordinal_out_of_range` 都不记，直接落回文字匹配） |
| `voice_tap/main.py` | `handle_speech`：控制语那道门 `voice.next_command` → **`voice.commands`**；`matcher.match(...)` 补 **`allow_ordinal=ctx["cfg"].voice.commands`** |

「说单词选选项」那条路一行没动，开关关着时照常工作（有专门用例钉住）。

### 2. 「识别语言可选」——**逻辑层无需改动，已确认接好**

这一半我查完发现**配置项本来就存在且已端到端接通**，所以没有可写的实现：

- `AsrConfig.language: str | None = None`（`config.py`）已有；
- `config.yaml` 的 `asr.language: null`（注释已写「填 zh 强制中文」）已有；
- `asr.py:183` 已经在用它：`language = self.asr_cfg.language`，为 `None` 时才
  `screen.guess_language(...)` 从屏幕猜 —— 也就是**填 `"en"` 就锁定英文**，
  正是用户要的「锁定语言」。

所以任务 3 里没有新增/修改任何语言相关代码。界面上怎么切（`None→zh→en` 轮转）
是任务 4（`cycle_language` 意图 + 新控件），我按分工没碰。

---

## 测试结果

### 起点基线

简报 Global Constraints 写「起始基线 **311** 个测试全绿」，**实际是 310**。
逐文件核对：`test_config 34 + test_matcher 53 + test_pipeline 104 + test_prefetch 27
+ test_screen 27 + test_ui_state 7 + test_voice_gate 11 + test_audio 19 + test_hotkey 25
= 307`，加 `test_inventory` 自身的 3 条 = **310**。简报那个 311 是错的（多算了 1）。
起点实测：`Ran 310 tests ... OK`。

### 先写测试、确认「因为正确的原因红」

写完测试、清缓存后跑，红的 14 条**全部是预期原因**：

- `test_config.TestVoiceCommandsSwitch` 5 条：`VoiceConfig.commands` 不存在（AttributeError）；
  `test_old_key_is_gone` 因为 `next_command` 还在而断言失败。
- `test_matcher.TestOrdinalCanBeDisabled` 4 条：`match()` 不认 `allow_ordinal`（TypeError）。
- `test_pipeline`：`test_disabled_by_config`（控制语那道门还没改，仍点了下一题）、
  `test_ordinal_disabled_by_config`（接线还没传 `allow_ordinal`，说了「3」照点）、
  `TestToggleFlag.test_works_on_voice_commands`（`next_command` 字段没了，AttributeError）、
  `TestCollectState.test_voice_commands_toggle_defaults_off`。

（`test_ordinal_clicks_when_enabled`、`test_saying_word_still_clicks_when_commands_off`
这两条在当时是绿的 —— 它们守的是「别关过头」，起点本来就该绿，正常。）

### 「改坏看红不红」（7 项，全部红 + 已还原）

改坏用备份/还原脚本做，每次都先 `rm -rf tests/__pycache__ voice_tap/__pycache__`：

| # | 改坏的地方 | 跑的目标用例 | 结果 |
|---|---|---|---|
| M1 | `matcher.py` 的 `if allow_ordinal:` → `if True:` | `TestOrdinalCanBeDisabled`（4 条） | **4 红** |
| M2 | `main.py` 控制语门去掉 `voice.commands and`（永远放行） | `test_disabled_by_config` | **红** |
| M3 | `main.py` 接线 `allow_ordinal=...commands` → 写死 `True` | `test_ordinal_disabled_by_config` | **红** |
| M4 | `config.py` 默认值 `commands: bool = False` → `True` | `test_default_is_off` | **红** |
| M5 | `config.yaml` 出厂值 `commands: false` → `true` | `test_shipped_config_is_off` | **红** |
| M6 | `config.py` 读取键名 `"commands"` → `"command"`（写错键） | `test_parsed_on` | **红** |
| M7 | `main.py` `collect_state` 的 `"voice_next": ...commands` → 写死 `True` | `test_voice_commands_toggle_defaults_off` | **红** |

还原后 grep 确认 7 处改坏内容无残留，再跑全套仍 320 OK。

### 最终用例数

**320 全绿，`Ran 320 tests in 13.5s OK`**（起点 310，净增 10）：

| 文件 | 起点 | 现在 | 说明 |
|---|---|---|---|
| `test_matcher` | 53 | **57** | 新增 `TestOrdinalCanBeDisabled` 4 条 |
| `test_config` | 34 | **36** | `TestVoiceNextCommand`(3) 改写成 `TestVoiceCommandsSwitch`(5)，净 +2 |
| `test_pipeline` | 104 | **108** | 新增 4 条（序号关/开两条、说单词不受影响一条、collect_state 默认值一条） |

基线数字（`test_inventory.BASELINE_COUNTS`）是「只增不减」的**下限**，现在实际值都高于基线，
所以无需改动；按分工**留给任务 5** 去按实际数字更新并注明理由。

### 提交

`6337c82  feat: 语音序号/下一题合并成一个开关（默认关）；识别语言可选`

---

## 偏离计划的地方及原因

简报说「发现的计划问题照实说」，下面每一条都是**不改就会报错或会误导用户**：

1. **`collect_state` 我改了（简报说「也先别改」）——但只改了一个来源字段。**
   `main.py` 的 `collect_state` 直接读 `ctx["cfg"].voice.next_command`。
   字段一删，这里**必然 AttributeError**（`TestCollectState` 也会跟着炸），
   与总要求「别留下会报错的引用」直接冲突。
   **最小改法**：只把来源换成 `ctx["cfg"].voice.commands`，
   **键名仍叫 `"voice_next"`** —— 因为 `gui.py` 认的就是这个键名，
   而按分工我不能碰 `gui.py`。改名（→ `voice_commands`）连同 `gui.py` 一起放任务 4。

2. **简报漏算了一条受影响的既有测试。**
   `tests/test_pipeline.py::TestUiStateWiring::test_unmatched_ordinal_says_what_actually_went_wrong`
   说「第七个」（超范围序号），断言文案里要有「5 个选项」。开关默认关之后序号那条路
   整个不走，`ordinal_out_of_range` 恒为 0，文案变成笼统的「屏幕上没有这个词」→ **该用例变红**。
   我在该用例里显式打开 `ctx["cfg"].voice.commands = True`（并注明原因）——
   它验的是「开着时」的报错文案。这就是上一轮说过的「简报漏算测试」，这次又发生了一次。

3. **简报给的测试片段本身跑不起来。**
   简报写 `Node(text="alpha", x=1, y=1)`，但 `screen.Node` 的 `clickable` 是
   **无默认值的必填字段**，照抄会 TypeError。matcher 只需要 `.text`，我用
   `test_matcher.py` 里现成的 `FakeNode(text, y)` 助手（与全文件风格一致）。

4. **简报说「给 `TestVoiceNextCommand` 加一条：开关关着时，说『下一题』不点」——
   这条**本来就有**（`test_disabled_by_config`，任务 2 加的）。**
   我只是把它从旧字段 `.next_command` 改成 `.commands`，没有重复造一条同名测试。
   作为补偿，我加了两条**真正新增**的用例：`test_ordinal_disabled_by_config`
   和 `test_ordinal_clicks_when_enabled` —— 它们钉的是本次真正的接线点
   `allow_ordinal=ctx["cfg"].voice.commands`（只改 matcher 忘了传参就抓得住，见 M3）。

5. **顺手改了启动提示语（计划里没写）。**
   `main.py` 就绪段原来无条件打印「也可以直接说序号：『1』『第二个』…」。
   开关默认关之后，**这句话就变成教用户做一件不生效的事**。
   我把它改成跟着 `cfg.voice.commands` 走：开着才提示序号/下一题；关着就说明
   「默认关着、想用去界面或 config.yaml 打开」。这是本次改动的直接后果，
   不改就是主动误导。**如果评审认为这该留给任务 5，请指出，我改回去。**

6. **意图名与界面键名暂时保留旧名（`toggle_voice_next` / `voice_next`）。**
   它们现在翻的/显示的是合并后的 `voice.commands`。改名要连 `gui.py` 一起动，
   属任务 4。我在两处都写了注释交代，避免下一个人误以为是漏改。

---

## 疑虑

1. **任务 4 的接缝（最要紧的一条）。** 任务 4 会把 `collect_state` 的键改成
   `voice_commands`，并引入意图 `toggle_voice_commands`。请务必**同一提交里**
   把 `gui.py` 的 `toggles["voice_next"]`（gui.py:157）和按钮表里的
   `("toggle_voice_next", "语音说下一题")`（gui.py:30）一起改掉 ——
   键名或意图名只改一边，界面会 KeyError 或按钮点了没反应，
   而 `collect_state` 的键来自 `main.py`、按钮名来自 `gui.py`，两边**没有测试**同时覆盖。
   我这边为了不弄坏界面，故意把这两个名字都留着没动。

2. **`identify language` 那一半，任务 3 实质是「空转」。** 计划把它列在任务 3 的
   依据里，但配置项与识别侧接线早就在（任务 2 之前就有），所以任务 3 只交付了
   「检查确认」。**如果期望任务 3 里出现语言相关的代码/测试，那是对计划的理解问题，
   不是漏做** —— 我没凭空造一个用不上的开关。

3. **`mute_after_click_ms` 与语音控制无关，未被本改动影响**；`0`（小键盘）那条路
   也不受 `voice.commands` 管（`handle_numpad` 直接按选项序号点，不经过 matcher）——
   用户说的「说序号」是**语音**序号，两者不要混淆。这一点计划没说，我按现状保留。

4. **`config.yaml` 里 `commands: false` 这一处，任务 5 也列了同样的改动**
   （r2-task-05 步骤 2）。我已改好，任务 5 执行时应该会看到已经是 `commands: false`，
   别以为是漏了。

5. 沙箱里 `--gui` 无法真跑（没显示器、没 tkinter）。`gui.py` 我只做了
   `compile()` 语法校验，**没有验证过真实窗口**；`collect_state` 的键名兼容性
   是靠读代码确认的（`voice_next` 未改名 → `gui.py:157` 不会 KeyError）。

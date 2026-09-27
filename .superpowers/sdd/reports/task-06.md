# 任务 6 报告：`collect_state` + 把结果回报给界面

## 状态：DONE_WITH_CONCERNS

> 代码与测试全绿、7 条新用例都是真护栏（已用「改坏看红不红」逐条证明）。
> 之所以不是纯 DONE：本任务步骤 4 的**「接线」全程无测试覆盖** —— 我把
> `grab_screen` / `do_click` / `handle_numpad` / `handle_speech` 里的
> `publish_screen` / `note_input` 调用点整个删掉，275 条测试**一条都不红**。
> 详见下面「疑虑 1」与「改坏实验 C/D」。

---

## 做了什么

### `tests/test_pipeline.py`

- 顶部加 `from voice_tap.ui_state import UiState`。
- 文件末尾（`TestAnyEvent` 之后、`if __name__` 之前）新增三个测试类，
  **用例与简报逐字一致**：`TestCollectState`（3）、`TestPublishScreen`（2）、`TestNoteInput`（2）。

### `voice_tap/main.py`

- 顶部补 `from .ui_state import InputEvent, OptionView, ScreenView`（放在 `hotkey` 与 `voice_gate` 之间，保持字母序）。
- `handle_intent` 之后新增 4 个模块级函数：`collect_state` / `publish_screen` / `note_input`
  / `_input_kind_and_label`。
- `grab_screen` 的两条返回路径各加一次 `publish_screen`（预读路径带 `age`，当场读屏路径不带）。
- `do_click`：加 `kind, label = _input_kind_and_label(key, description)`；
  早退分支里 `if not clicked: note_input(..., outcome="已跳过（防连点）")`；
  真点下去之后 `note_input(..., outcome=f"点了 {description}")`。
- `handle_numpad` 的时戳拦截分支加 `note_input(ctx, "numpad", str(number), outcome="已忽略：界面在按键之后翻页了")`。
- `handle_speech` 开头（紧挨 `say(f"[听到] ...")` 之后）加
  `note_input(ctx, "speech", text, detail=f"置信度 {logprob:.2f}", outcome="（见下）")`。

### 「不带 `--gui` 行为不变」的论证

`main.py` 里 **没有任何地方设置 `ctx["ui"]`**（`grep 'ctx\["ui"\]' voice_tap/main.py` 为 0 命中；
`main()` 造的 ctx 只有 adb / cfg / preview / recognizer / prefetcher / mode / clicker /
voice_gate / hotkeys / wake_event / intents）。所以三个新函数在真实运行路径上一律走
`ctx.get("ui") is None` → 干净的空操作；`collect_state` 目前还无人调用（等 `gui.py`）。
新增调用点除写 `UiState` 外没有别的副作用。

---

## 测试结果

起点（按指令先跑）：

```
$ rm -rf tests/__pycache__ voice_tap/__pycache__
$ python3 -m unittest discover -s tests
Ran 268 tests in 11.975s
OK
```

**先写测试、确认它因正确原因失败**（把实现版本换回 `HEAD~1` 的 `main.py` 后跑这 7 条）：

```
$ python3 -m unittest tests.test_pipeline.TestCollectState \
      tests.test_pipeline.TestPublishScreen tests.test_pipeline.TestNoteInput
AttributeError: module 'voice_tap.main' has no attribute 'collect_state'
AttributeError: module 'voice_tap.main' has no attribute 'note_input'
AttributeError: module 'voice_tap.main' has no attribute 'publish_screen'
Ran 7 tests in 0.005s
FAILED (errors=7)
```

7 条全部因「函数还不存在」而错 —— 是正确的原因，不是测试自己写错。

实现后同样 7 条：`Ran 7 tests ... OK`。

**最终全套**：

```
$ python3 -m unittest discover -s tests
Ran 275 tests in 11.943s
OK
```

275 = 268 + 7，正好是简报期望的「比开跑前多 7 个」。

---

## 「改坏看红不红」实验

每次实验前都 `rm -rf tests/__pycache__ voice_tap/__pycache__`（本仓库 `.py`/`.pyc` 常同秒落盘）。
改动前先 `cp voice_tap/main.py /tmp/main_backup.py`，改完从备份还原，最后 `grep 改坏` 确认为空。

### 实验 A（简报点名）：让 `publish_screen` 不设 `source`

去掉 `ScreenView(...)` 里的 `source=source,` 一行。

- **红了**：`TestPublishScreen.test_publishes_options_without_coordinates`
  → `AssertionError: '' != '预读'  + 预读`（`FAILED (failures=1)`）
- 还原：`cp /tmp/main_backup.py voice_tap/main.py`

### 实验 B（简报点名）：让 `note_input` 不记 `outcome`

把 `InputEvent(kind=..., label=..., detail=..., outcome=outcome)` 改成不传 `outcome`。

- **红了**：`TestNoteInput.test_records`
  → `AssertionError: '' != '点了第 3 个'  + 点了第 3 个`（`FAILED (failures=1)`）
- 还原同上。

> 小结：这两个函数**本身**确实是真护栏。

### 实验 C（我自己加做）：断掉 `publish_screen` 的接线

把 `grab_screen` 里两处 `publish_screen(...)` 调用（预读路径 + 当场读屏路径）**整行删掉**。

- 结果：**`Ran 275 tests ... OK`，一条都不红。**
- 结论：`publish_screen` 的调用点零覆盖。

### 实验 D（我自己加做）：断掉 `note_input` 的接线

把 4 处调用 —— `do_click`（「已跳过」+「点了 X」）、`handle_numpad`（时戳拦截）、
`handle_speech`（听到）—— 全部换成同缩进的 `None  # 改坏`。

- 结果：**`Ran 275 tests ... OK`，一条都不红。**
- 结论：`note_input` 的调用点零覆盖。

> **实验 D 的第一次尝试是失败的假实验，值得记一笔**：我第一次用朴素的删行来做，
> 结果把 `do_click` 里 `if not clicked:` 的块体掏空了，`main.py` 直接
> `IndentationError`，`test_inventory` 的「文件可否收集」用例把它抓了出来
> （`Ran 167 tests ... FAILED`）。那次被测到的是**语法错**，不是行为变化 ——
> 不能算数。第二次改成「把调用换成 `None`、保持语法合法」才是干净的实验，
> 于是 275 条全绿。这也正说明：删行式的「改坏」会顺带制造无关的红，容易自欺。

---

## 提交哈希

```
d09b5b1  feat: collect_state 与结果回报（界面的数据来源）
```

---

## 偏离计划的地方

- **代码与测试零偏离**：所有代码、注释、测试用例都照简照抄。
- 一处补充说明（非偏离）：简报的 `do_click` 片段写在「然后 `do_click` 里」，
  里面含 `kind, label = _input_kind_and_label(key, description)` 这一行；
  我按完整片段补上了，位置在 `if not (clicked and not ctx["preview"]):` 之前。
- **提交范围说明**：照指令用 `git add -A`，于是工作区里两处**非本任务**的既有改动
  （`.superpowers/sdd/progress.md` 的 t5 收尾、`docs/superpowers/plans/2026-09-27-gui-and-voice-controls.md`
  里 `_input_kind_and_label` 那处计划修订）以及新建的简报 `briefs/task-06.md` 一并进了
  这次 feat 提交。这与上一任务的 feat 提交（039b680 也含 `progress.md`）惯例一致，仅此说明。
- 我给 `do_click` 的早退分支、`handle_speech` 的 `note_input` 各补了一行说明性注释（无行为影响）。

---

## 疑虑

### 1（重要）接线零覆盖 —— 步骤 4 是本任务唯一没被测试守住的部分

实验 C/D 已经证明：`grab_screen` / `do_click` / `handle_numpad` / `handle_speech` 里
那几个 `publish_screen` / `note_input` 调用，**整条删掉测试也不会有任何反应**。
换句话说：新加的 7 条测试守住了三个函数，但没守住「它们真的被接到出口上」。

这不是吹毛求疵 —— 项目台账自己写着「**四轮审查各自抓出过一次『测试看着像护栏、
其实抓不住东西』**」，而 t1 遇到的正是同一情形（「接线（盖戳→入队→解包）零覆盖 →
已补 `TestActionWiring`」）。

**我这次没有补**，只因为简报明确写「期望：比开跑前多 7 个」并逐字给了 7 条用例，
擅自加会改掉这个约定值；而且台账里 t1 的处置方式是**另开 fix**。留给审查定夺。
若要补，建议的最小一组（都能让实验 C/D 变红）：

- 带 `"ui": UiState()` 的 ctx 跑一次 `handle_speech("清晰", -0.4, ctx)`，
  断言 `ctx["ui"].current_screen().prompt == "degrade"`、`recent_inputs()` 里能看到这次输入；
- 跑一次 `handle_numpad(3, ctx, stamp=...)`，断言 inputs 出现 `outcome="点了 小键盘第 3 个"`；
- 跑一次**会被时戳拦下**的 `handle_numpad`，断言出现 `outcome="已忽略：界面在按键之后翻页了"`；
- 跑一次 `handle_speech("清晰", ...)` 触发 `grab_screen` 的当场读屏路径，断言 screen 被发布。

### 2 `handle_speech` 那条 `outcome="（见下）"` 会悬空

这条记的是「听到了什么」，结果指望后面 `do_click` 补上。但**匹配失败时
`do_click` 根本不会被调用** —— `handle_speech` 在 `if not result.ok:` 分支就直接 `return` 了。
于是界面上会永久留下一条「清晰 → （见下）」，而下面并没有「下」。
语音路径说「下一题」同理，会留下 speech + next 两条记录（有重复感）。

这是简报指定的写法，我照做了，但它在界面上会显得没头没尾。
建议后续把这条的 `outcome` 改成能自洽的说法（例如在匹配失败分支补一条
`note_input(..., outcome="没匹配上")`，或把这里改成「听到了什么」不再暗示下方有内容）。

### 3 次要：preview 模式下不记任何输入

`do_click` 在 `preview=True` 且 `clicked=True` 时直接早退、不记。按
`Clicker.click` 的语义，preview 下 `clicked` 为 True（「标了圈」），
所以界面第三块在 preview 下永远是空的。我判断这符合「显示真实点击结果」的意图，
但如果你希望 preview 也能看到操作流水，这里要另说。仅记录，未改。

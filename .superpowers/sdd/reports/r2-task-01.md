# 第二轮 · 任务 1 报告：去掉动作时戳（按键一律生效）

## 状态：DONE_WITH_CONCERNS

代码与测试全部改完，**306 个用例全绿**，两个「改坏看红不红」实验都跑了，工作区干净、已提交。

之所以不是纯 DONE：**简报漏算了一个依赖时戳的测试**（见「偏离计划」第 1 条）——
它不在 `TestActionStamp` 里，而在 `TestUiStateWiring` 里。我做了判断：把那条测试**改成守新行为**而不是删掉，
从而用例数正好是简报期望的「少 5 个」。这个判断需要复核。
另外发现一处本轮改动造成的过时注释（`voice_tap/ui_state.py:51`），按「只改简报列出的文件」的约束没动它。

---

## 做了什么

**提交：`9506a28`**　`fix: 去掉动作时戳 —— 按键一律生效（真机日志证明它误伤 9 次）`
（3 个文件：`voice_tap/main.py`、`tests/test_pipeline.py`、`tests/test_inventory.py`；+119 / −191）

### 1. `voice_tap/main.py`

- 删掉 `ScreenPrefetcher.identity()`（整个方法，原紧挨 `miss_reason()` 之后）。
- `handle_numpad(number, ctx)` —— 去掉 `stamp` 参数；删掉那段
  `if stamp is not None and ScreenPrefetcher.signature(snap) != stamp:` 核对块
  （连同它写「已忽略」记录的那两句）；docstring 里讲 `stamp` 的整段删掉，补上一句
  「按键一律生效，不吞。2026-09-28 之前这里还会核对一个『动作时戳』……理由与数据见
  tests/test_pipeline.py 里那段注释」。
- `make_action_putters` —— 三个回调入队改成二元组：`("numpad", n)` / `("next", None)` / `("force_read", None)`。
  `prefetcher` 参数按简报 Interfaces **保留**（现已无人使用，docstring 里写明「保留只是为了签名稳定」）。
- `dispatch_action` —— 解包改 `kind, value = action`；分派分支、「认不出的 kind 一律当没看见」都不变。
- 顺手改了两处随之过时的注释：模块级流水线示意图去掉「盖戳」、`main()` 里「盖戳 → 入队」那一句。

### 2. `tests/test_pipeline.py`

- `TestActionStamp` 整类删除（**5 个用例**），**在原地留下简报给的那段理由注释**（逐字照抄）。
- `TestActionWiring` **11 个用例全部保留**，全部改成二元组世界、去掉所有跟戳有关的断言：
  - 三个入队断言 → `[("numpad", 3)]` / `[("next", None)]` / `[("force_read", None)]`；
  - `test_stamp_is_taken_at_press_not_at_execution` → `test_number_is_captured_at_press_not_at_execution`
    （守「号码在按下那一刻就定格进队列」）；
  - `test_stamp_is_none_before_any_screen_read` → `test_putters_do_not_need_the_prefetcher`
    （传 `None` 也照样入队 —— 守「按键回调不再依赖预读器」，若有人把时戳加回来这条会红）；
  - `test_dispatch_does_not_swallow_the_stamp` → `test_dispatch_passes_the_value_through`
    （按 2 必须落在第 2 个选项的坐标上 —— 守「第二个元素不被吞、不被串」）；
  - `test_malformed_action_is_ignored_silently` 的坏样本表更新：`("numpad", 1)` 现在**是合法的**，移出坏样本；
    把 `("numpad", 1, None)`（上一版的三元组）**加进**坏样本；另补一个 `"ab"`（长度 2 的字符串）。
- 另外改写了 1 条（见「偏离计划」第 1 条）。

### 3. `tests/test_inventory.py`

- `BASELINE_COUNTS["tests.test_pipeline"]`：**106 → 101**，并在数字旁注明理由（照抄简报给的两行注释）。
  `101` 是**实测值**（不是照简报样例里的 98 抄的）：`unittest` 收集 `tests.test_pipeline` 得到 101 个用例。
- `REQUIRED_CLASSES["tests.test_pipeline"]` 去掉 `"TestActionStamp"`，
  并把 `"TestActionWiring"` 的旁注从「盖戳 → 入队 → 解包分派」改成「入队 → 解包分派」。

---

## 测试结果

命令：`rm -rf tests/__pycache__ voice_tap/__pycache__ && python3 -m unittest discover -s tests`

| 阶段 | 结果 |
|---|---|
| 开跑前基线 | **311 全过**（提交 `5dbe5f8` 之后） |
| 删完 `TestActionStamp`、改完清单后（main.py 还没动） | **306 全过**（`TestActionWiring` 仍绿，符合简报步骤 2 的预期） |
| 全部改完 | **306 全过** |
| 提交后复核（清缓存重跑） | **306 全过** |

- `tests.test_pipeline` 收集数：**101**，与基线一致。
- `voice_tap/gui.py`：`compile()` 语法校验通过（没有 `import tkinter`）。
- 开跑前先 `pip install pypinyin --break-system-packages` **没用到**（沙箱里已有 `pypinyin`）。

### 「改坏看红不红」实验

**实验 A（简报步骤 4 要求）：入队改成三元组**

把 `make_action_putters.on_option` 的入队改成 `("numpad", n, "花")`，其余一律不动，清缓存跑全套：

```
FAIL: test_number_is_captured_at_press_not_at_execution (test_pipeline.TestActionWiring)
FAIL: test_on_option_puts_the_number (test_pipeline.TestActionWiring)
FAIL: test_putters_do_not_need_the_prefetcher (test_pipeline.TestActionWiring)
----------------------------------------------------------------------
Ran 306 tests in 12.917s
FAILED (failures=3)
```

→ **3 个用例变红，全在 `TestActionWiring`**（比简报说的「有对应用例变红」多，因为三条用例都盯着
`on_option` 的入队结果）。改回二元组后恢复 306 全绿。

**实验 B（我自己给自己新加的护栏做的）：把时戳拦截整条加回去**

新写的 `test_press_still_clicks_after_the_screen_turned` 声称守「翻页后按键照常生效」。
为确认它不是条假护栏（本项目审查抓到过 6 次假护栏），我临时把旧功能整条复原：

- `on_option` 在按下那一刻用 `prefetcher.peek()` 取指纹，入队三元组；
- `dispatch_action` 解包三元组、把 `stamp` 回传给 `handle_numpad`；
- `handle_numpad` 收到 `stamp` 后与当前屏幕比对，不一样就 `return`。

只跑这一条用例：

```
[小键盘] 1
[sabotage] 已忽略
FAIL: test_press_still_clicks_after_the_screen_turned
AssertionError: 0 != 1 : 翻页之后轮到执行，这一下也要生效，不能吞
Ran 1 test in 0.003s
FAILED (failures=1)
```

→ **确实变红**（这一下被吞掉，0 次点击 —— 正是真机日志里的那个病）。
随后把临时改动**全部撤回**，`grep -r sabotage voice_tap/ tests/` 无残留（只剩清掉的旧 `.pyc`），
清缓存重跑全套恢复 **306 全绿**。

### 依据核对（我独立复核了简报引用的真机数据）

简报说「日志里 9 次『已忽略』中有 7 次用户按的是**不同的键**」。我没有直接照抄，写了个小脚本解析
`debug/run_20260927_234859.log`（737 行 ✅ 与简报一致），逐条比对「被吞的键」与「上一次成功点到的序号」：

```
共 9 次已忽略 ✅；其中与「上一次成功点的序号」不同的有 7 次 ✅
（剩下 2 次是用户按了同一个键两下：被吞一次、再按一次才生效）
```

例：行 186 上一次成功点是**第 4 个**、被吞的键是 **1**（= 简报里的「点第 4 个之后按 1」）；
行 372 同样是「点第 4 个之后按 1」。日志里点完选项会**自动翻到下一题**，
所以「点第 4 个之后按 1」正是用户在答下一题 —— 简报对「误伤」的定性成立，我照抄进注释。

---

## 最终用例数与基线理由

- 全套：**311 → 306**，比开跑前**少 5 个**，与简报步骤 5 的期望一致。
- 基线 `"tests.test_pipeline": **101**`（原 106）。理由已写在 `tests/test_inventory.py` 数字旁：
  > 2026-09-28：删掉 TestActionStamp 的 5 个用例 —— 动作时戳按用户要求取消，
  > 理由见 tests/test_pipeline.py 里那段注释。
- 101 是实测（清缓存后 `unittest` 收集所得），与基线吻合，`TestInventory` 全绿。

---

## 偏离计划的地方及原因

1. **简报漏了一个依赖时戳的测试：`test_stamp_rejected_press_leaves_an_ignored_record`。**
   它不在 `TestActionStamp` 里，而在 `TestUiStateWiring`（界面「我的输入」那一段，原 `tests/test_pipeline.py:1629`），
   同样用 `pref.identity()` + `handle_numpad(..., stamp=...)`，断言「被时戳拦下要记成『已忽略』」。
   简报步骤 1 只写「删 `TestActionStamp`（5 个）」，步骤 5 期望「少 5 个」——
   按字面理解，这条要么改完全套报错、要么被一并删掉（那就是**少 6 个**）。

   **我的处理**：把它**改成守新行为**而不是删掉 ——
   `test_press_still_clicks_after_the_screen_turned`：走**真接线**（按下 → 入队 → 翻页 → 出队执行），
   断言这一下**照点**（1 次点击）、界面如实记成「点了第 1 个」、并且**不再出现「已忽略」**。
   理由：
   (a) 用例数维持「少 5 个」，与简报期望吻合；
   (b) 取消时戳是本任务的核心，若把这条直接删掉，整个测试集里就**没有任何东西**能挡住
   「有人再把『跟屏幕比一比、不一样就吞掉』加回来」—— 这条正好补上（实验 B 已证明它会红）。

   **如果复核认为该条应当直接删掉**：把基线从 `101` 改成 `100`，并把清单里那两行理由的
   「5 个用例」改成「6 个」即可，别处不用动。

2. **`make_action_putters(queue, prefetcher)` 的 `prefetcher` 参数保留但已无人使用。**
   这是照简报的 Interfaces 原文保留的（简报明确写 `make_action_putters(queue, prefetcher)`）。
   我在 docstring 里写明「保留只是为了签名稳定」，并加了一条测试守着（传 `None` 也照常工作）。
   若更希望「不留无用参数」，那是接口层面的取舍，应由简报/计划定，我没擅自改签名
   （一改，`main()` 的调用点、以及这条新测试都要跟着动）。

3. **没动 `voice_tap/ui_state.py`**（见「疑虑」第 1 条）。简报的 Files 只列了
   `main.py` + 两个测试文件，我严格照办，没有扩大范围。

---

## 疑虑

1. **`voice_tap/ui_state.py:51` 的注释因本轮改动而过时**：
   ```python
   outcome: str = ""       # "点了第 4 个" / "已忽略：界面已翻页" / "没匹配上"
   ```
   其中 `"已忽略：界面已翻页"` 这个取值**再也不会产生**了。
   它不在简报列出的文件里，所以我没动；建议交给「任务 5：文档与测试清单收尾」一并处理，
   或明确授权我改（一行注释的事）。

2. **沙箱跑不了真机、也没有 `import tkinter`**，验证靠单测 + `compile()`。
   不 `--gui` 的行为除本改动外没有变化：diff 只有 3 个文件，改动全部落在
   「按键入队 / 解包分派 / `handle_numpad`」这一条线上，其余调用点（语音、界面、预读、热键）未动。

3. **语音路径不受影响**：它本就不经过 `make_action_putters`/`dispatch_action`
   （`handle_speech` 直接调 `do_click`），去掉 `stamp` 对它零影响 ——
   `TestVoiceMutedAfterClick`、`TestKeyPressesAreNeverTimeBlocked` 等仍全绿。

4. **`TestActionWiring` 的类 docstring 与用例名跟旧版已全面对不上**（都围绕「戳」写的），
   我把它们重写成了围绕「二元组接线」的说法。若审查更偏好「名字逐字保持原样只改断言」，
   这属于风格取舍，可以再调。

5. 本轮**没有**碰 `.gitattributes` / `core.autocrlf` / 任何 `.bat`；提交是 `git add -A` 一条，
   含 3 个文件，未混入其他任务的改动。

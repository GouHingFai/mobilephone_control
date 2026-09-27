# 报告：补上动作队列接线的测试覆盖（审查发现 · 任务 1 收尾）

## 状态

**DONE**

（唯一一处需要你知道的取舍：「认不出来的 kind」现在被忽略，而不是像原来那样
落到 `handle_numpad` 分支 —— 见文末「疑虑 1」。生产路径上不可观测，但确实是行为差异。）

---

## 改了什么

### 1. `voice_tap/main.py`：把接线抽成两个模块级函数

**新增 `make_action_putters(queue, prefetcher)`**（放在 `ScreenPrefetcher` 之后）

返回一个字典，键就是热键管理器要的回调名，免得靠位置记顺序：

| 键 | 入队内容 |
|---|---|
| `on_option(n)` | `("numpad", n, prefetcher.identity())` |
| `on_next()` | `("next", None, prefetcher.identity())` |
| `on_force_read()` | `("force_read", None, None)` |

**盖戳的时机**封装在回调体里：回调跑在按键那一刻，`identity()` 取到的就是
「按下时屏幕上是什么」。这一条有专门的测试钉住（见下）。

**新增 `dispatch_action(action, ctx)`**

结构是 `try: kind, value, stamp = action` + 一条 `if/elif` 分派链：

- 格式不对（不是长度 3 的可解包对象）→ `except (TypeError, ValueError): return`，不抛异常、不写日志
- `"numpad"` → `handle_numpad(value, ctx, stamp=stamp)`
- `"next"` → `handle_next(ctx)`
- `"force_read"` → `handle_force_read(ctx)`
- 其它 kind → 什么都不做（见「疑虑 1」）

写成显式 `elif` 链而不是 `else` 兜底，是为了任务 5 往里加 `"intent"` / `"quit"`
时是「加一行」而不是「改一处危险的分支」——`else` 兜底一旦漏掉新 kind，
会把它当成「点一下」扔出去。

**改 `main()`**

- `numpad_worker` 的循环体简化成「取一条 → `dispatch_action(action, ctx)`」；
  外面那层 `except AdbError` / `except Exception`（写日志、`log_exception`）
  原样保留 —— 那是工作线程的兜底，没动。
- `hotkeys.start(...)` 原来那三个 lambda 换成 `make_action_putters(...)` 的产物。
  注意 putters 必须在 `hotkeys.start` **之前**建好，因为回调随时可能被触发。

### 2. `tests/test_pipeline.py`：新增 `TestActionWiring`（11 个用例）

按简报推荐的「断言可观察后果」写法，**没有 monkeypatch 任何模块级处理函数**，
全部走真实路径：

- **盖戳（5 条）**：用假队列 `RecordingQueue`（只记 `put` 的内容）+ 真的
  `ScreenPrefetcher`（先 `note()` 一屏），断言三个回调入队的元组逐字正确。
  另加两条关键的：戳必须在**按下那一刻**取（按完再翻页不该改戳）；
  还没读到过界面时戳就是 `None`。
- **解包分派（4 条）**：`dispatch_action(("numpad", 1, None), ctx)` 断言
  `fake.taps` 真的点在了第 1 个选项的行内；`("next", ...)` 断言点到了
  `(600, 2180)`；`("force_read", ...)` 断言 `fake.dump_calls == 1` 且没点。
  还有一条关键的：**分派时不能把戳吞掉** —— 构造「按键后翻页」的场景，
  断言这一下不点（若 `dispatch_action` 忘了传 `stamp`，这条立刻红）。
- **坏格式不崩（2 条）**：`3` / `None` / `("numpad",)` / `("numpad", 1)` /
  `("numpad", 1, None, 2)` / `()` / `"numpad"` / `"abc"` / `"abcdef"` 九种输入
  都不抛异常、也不产生点击；再加一条未知 kind 被忽略。

### 3. `tests/test_inventory.py`：基线 43 → 54

test_pipeline 的用例数基线按该文件自己的约定（「数字只增不减」）上调到 54，
这样**新加的 11 个用例也受清单机制保护**，将来被误删会被 `test_inventory` 揪出来。
不调基线的话新测试反而是「无保护」的。

---

## 测试结果

### 起点与终点都是全绿

- 起点（重构前）：`Ran 227 tests ... OK`
- 终点（重构后）：`Ran 238 tests ... OK`（227 + 新增 11）
- 现有 227 个测试**一个没动、全部继续绿**。这是纯重构 + 补测试。

### 关键证据：新测试在重构前根本测不到这些行为

`git show HEAD~1:voice_tap/main.py | grep -c "def \(make_action_putters\|dispatch_action\)"`
→ **0**。这两个函数在重构前不存在，接线藏在 `main()` 的三个 lambda 和一个闭包里，
外部调不到 —— 所以「重构前跑新测试会不会红」这个问题本身没法直接回答：
那 11 个用例根本无从写起。

于是换了个更硬的等价证据：**把接线按几种典型的改坏方式改坏，看新测试红不红。**
（每次只改一处，跑完立刻从备份还原；备份与还原都用 `diff` 核对过。）

| 故意改坏的地方 | 结果 |
|---|---|
| `on_option` 忘记盖戳：`queue.put(("numpad", n))`（两元组入队） | **FAILED (failures=2, errors=1)**，红的 3 条全在 `TestActionWiring`：<br>`test_on_option_puts_number_with_the_stamp`、<br>`test_stamp_is_taken_at_press_not_at_execution`、<br>`test_stamp_is_none_before_any_screen_read` |
| `dispatch_action` 丢戳：`handle_numpad(value, ctx)`（不传 `stamp=`） | **FAILED (failures=1)**，红的正是 `test_dispatch_does_not_swallow_the_stamp` |
| 分派写反：`"next"` 分支调 `handle_force_read`、`"force_read"` 分支调 `handle_next` | **FAILED (failures=1)**，红的正是 `test_dispatch_next_clicks_the_next_button` |

三次破坏里，**原有 227 个测试全都保持绿色**（总数始终是 238，红的只在
`TestActionWiring`）—— 这正好反向印证了审查的担心：没有这批新测试，
这些坏法谁都发现不了。三种坏法都对应真机上的那个老毛病（「连按两下点到新题」）。

还原后 `diff /tmp/main_backup.py voice_tap/main.py` 一致，最终全套 `Ran 238 tests ... OK`。

---

## 提交

```
3ba4c8ce253c483ac793560286a5bc4f616485d2
test: 补上动作队列接线的覆盖（审查发现）
```

改动文件（7 个）：`voice_tap/main.py`、`tests/test_pipeline.py`、
`tests/test_inventory.py`，外加上一轮留在工作区、随 `git add -A` 一并纳入的
`.superpowers/sdd/` 简报 / 报告 / 审查 diff（4 个）。

`.gitattributes` / `core.autocrlf` / `.bat` 一律没碰（`git diff` 里无这些文件的改动）。

---

## 疑虑

### 1. 「认不出来的 kind」现在被忽略，原来是落到点选项分支（唯一的行为差异）

原 `numpad_worker` 写的是 `if force_read ... elif next ... **else: handle_numpad(...)`**。
也就是说：任何既不是 `"next"` 也不是 `"force_read"` 的 kind，都会被当成
「点第 value 个选项」执行。

我改成了显式 `elif kind == "numpad"`，未知 kind **什么都不做**。

- **生产路径上不可观测**：全项目只有这三处 `put(...)`，队列里永远不会出现第四种 kind。
  所以这不是「真机上行为变了」，而是「这个新函数对未知输入的选择」。
- **为什么选「忽略」**：简报明说任务 5 要往里加 `"intent"` 和 `"quit"`。
  若保留 `else` 兜底，任务 5 改到一半（比如 `"quit"` 还没接上）时，
  一个 `("quit", None, None)` 会被当成「点第 None 个选项」——
  而 `handle_numpad(None, ...)` 里的比较运算会直接抛 `TypeError`，
  虽被线程兜底接住，但语义已经错了。宁可什么都不做，也不能乱点。
- **如果你更想严格保持逐字一致**，我可以把它改回 `else:` 兜底 —— 一行的事，
  但我建议不要，理由如上。这条也是本报告里**唯一**需要你拍板的地方。

### 2. 新测试偏「白盒」了一点点，但没碰 monkeypatch

`test_stamp_is_taken_at_press_not_at_execution` 里为了让「按完才翻页」可控，
直接给真 `ScreenPrefetcher` 的 `note()` 喂了第二屏（`SECOND_XML`）。
这是用真对象的公开方法造场景，不是打桩，应该没问题；但如果你觉得
「让真 prefetcher 翻页」的手法不够干净，可以提，我改成走更外层一点。

### 3. 顺手改了 `test_inventory.py` 的基线，简报没要求

简报只列了四件事，没提交清单文件。我改它是因为该文件自己写着「数字只增不减，
要改就得来这里显式改」——不调的话新加的 11 个用例不受清单保护，
将来被误删同样会「静悄悄地丢」。这个改动是**加保护**、不是减，且被单独写进了提交说明里。
如果你希望这类「计划外但顺理成章」的改动也先报备再动，告诉我。

### 4. 一点没验到的

`hotkeys.start` 传进去的到底是哪三个回调、以及 `numpad_worker` 线程有没有真的
把 `dispatch_action` 接上 —— 这两处仍在 `main()` 的闭包 / 线程里，
**单测覆盖不到**（要覆盖得真起一个 HotkeyManager 和线程）。
本次只保证「回调体本身」和「分派函数本身」正确，以及它们之间的格式约定
被测试钉死了。接线最外面那层（谁调谁）仍是靠读代码保证的 —— 这是本任务的
剩余边界，如实记在这里。

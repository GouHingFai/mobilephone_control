# 任务 1 代码审查报告：动作时戳

审查对象：提交 `0d09a85`　fix: 动作时戳 —— 连按两下同一个键不再点到新题上
审查依据：`briefs/task-01.md`、`review/task-01.diff`、真实文件（`voice_tap/main.py`、`tests/test_pipeline.py`）、设计文档 §4.5。
审查方式：读真实文件 + 全局 grep `numpad_queue`/`handle_numpad`/`identity` + 跑全套 + **回退实验**。

---

## 1. 结论

# 通过

规格要求的每一步都落地了，且**核心护栏是真的**：我把 `handle_numpad` 里的时戳核对
临时改成恒假（等价于回退本修复），新测试里的
`test_dropped_when_screen_changed_since_press` **立刻变红**（`FAILED (failures=1)`，
`[(606, 811)] != []`），改回来后 227 个用例全绿、工作区干净。所以这不是假护栏。

发现的问题都是 Minor 或「计划本身的取舍」，没有必须返工的缺陷。详见第 3、4 节。

**验证证据**

```
$ python3 -m unittest discover -s tests      # 提交状态（工作区干净）
Ran 227 tests in 9.044s
OK

$ # 实验：把 if stamp is not None and ... 改成 if False and ... 后
$ python3 -m unittest tests.test_pipeline.TestActionStamp -v
FAIL: test_dropped_when_screen_changed_since_press
AssertionError: Lists differ: [(606, 811)] != []  : 界面已经变了，这一下不能点
Ran 5 tests ... FAILED (failures=1)
```

---

## 2. 规格符合度（逐步对照）

| 简报步骤 | 做了什么 | 对照结果 |
|---|---|---|
| 步骤 1：加 `SECOND_XML` + `TestActionStamp`（5 例） | `tests/test_pipeline.py:29` 加 `SECOND_XML`；`:765-829` 加 `TestActionStamp` | ✅ 与简报给的片段逐字一致 |
| 步骤 2：先看到失败 | 报告记录 `AttributeError: ... no attribute 'identity'` | ✅ 理由正确（`identity` 尚不存在），非语法错 |
| 步骤 3：`ScreenPrefetcher.identity()` | `main.py:213-224`，紧挨 `miss_reason()`（`:196-211`）之后 | ✅ 位置、持锁、`None` 语义均与简报一致 |
| 步骤 4：`handle_numpad(number, ctx, stamp=None)` + 核对块 | 签名 `main.py:509`；核对块 `main.py:541-545`，位于 `grab_screen` 之后、`if not snap.ok:`（`:547`）之前；docstring 补了 `stamp` 来历（`:524-530`） | ✅ 插入位置、文案与简报一字不差 |
| 步骤 5：队列条目 `(kind, value, stamp)` + worker 按 kind 分派 | 三个 lambda `main.py:860-862`；worker `main.py:821-842`；旧 `number == "."` / `number == 0` 分支已删 | ✅ 完全按简报那段循环体替换 |
| 步骤 6：全绿 | `Ran 227 tests ... OK` | ✅ 与期望 227（222+5）一致 |

**做了简报没要求的事？** 代码层面没有。唯一「多出来」的是 `git add -A` 顺带把两处**与代码无关的既有改动**
（`docs/superpowers/plans/...md` 的 +3/-1、`.superpowers/` 新目录）带进了同一个提交 —— 这一点报告里
「偏离计划」第 1 条已如实交代，且简报的命令就是 `git add -A && git commit`，属照做，不算问题。
已核对 `git show --stat`：改动仅 `.superpowers/`、计划文档、`tests/test_pipeline.py`、`voice_tap/main.py`，
**没有碰任何 `.bat`，`core.autocrlf` 仍为 `false`**。

**遗漏的 `numpad_queue.put(...)` 调用点？** 没有。全局搜索 `numpad_queue`：生产代码里只有
`main.py:818`（建队列）、`:824`（worker 取）、`:860-862`（三处入队），全部已迁移成本任务的新格式；
测试里没有任何地方直接往 `numpad_queue` 塞东西（`test_hotkey.py` 用的是它自己的 `received.append`，
不经队列）。所以旧格式没有残留的写入点。

---

## 3. 测试是否真的有效

### 3.1 回退修复后会不会红 —— **会红，判断依据是实测**

我实际做了这个实验（未提交）：把 `main.py:543` 的
`if stamp is not None and ScreenPrefetcher.signature(snap) != stamp:`
临时改成 `if False and ...`（等价于删掉这段核对），然后：

```
FAIL: test_dropped_when_screen_changed_since_press
AssertionError: Lists differ: [(606, 811)] != [] : 界面已经变了，这一下不能点
Ran 5 tests ... FAILED (failures=1)
```

失败原因正是要抓的 bug：测试用 `stamp` 记下第一题、再把 `_last_seen` 换成第二题，
没有核对时 `handle_numpad` 就照着第二题点了第 1 个（`(606, 811)` 正是选项一的中心）。
**结论：`test_dropped_when_screen_changed_since_press` 是真护栏，能独立抓住「回退修复」。**
其余 4 个用例在回退后仍通过（它们是正例/回归护栏，本就不该因回退而红，见下）。

### 3.2 有没有恒真的用例

逐个核过，**没有恒真的**，但有一个用例的定位要说清：

- `test_runs_when_no_stamp_given`（`:823-829`）**无法察觉「回退修复」**（回退后照样绿）。
  但它并非恒真：它钉住的是「`stamp is None` 时不得拦截」——若有人把条件写成
  `if ScreenPrefetcher.signature(snap) != stamp:`（漏掉 `stamp is not None` 判断），
  这里 `None != 签名` 会误拦，该用例立刻红。所以它是有效的**反向护栏**，只是定位不是「抓 bug」。
- `test_runs_when_screen_unchanged`（`:814-821`）同理，是防「误拦」的正例。
- `test_identity_is_none_before_any_read` / `test_identity_reflects_last_seen_screen` 都依赖
  `_last_seen` 的真实取值，非恒真。

### 3.3 `_setup` 有没有把要验证的行为绕过去 —— **绕过了「带戳」这一半**

`_setup`（`:775-791`）**绕过了队列与 worker 的接线**：它不经热键回调、不经 `numpad_queue`、
不经 `numpad_worker`，而是手工 `pref.note(...)` 造出「翻页」状态，再把 `stamp=` 直接喂给
`handle_numpad`。也就是说：

- 它**没有**绕过 `handle_numpad` 内部的核对逻辑 —— 那一半被测得很实（见 3.1）。
- 它**确实**绕过了「热键回调用 `identity()` 盖章 → 队列三元组 → worker 解包并按 kind 分派」
  这条接线。而这条接线**整个仓库里没有任何测试覆盖**（已 grep 确认：没有测试碰到
  `numpad_worker`、三个 lambda、或队列三元组格式）。

后果：如果有人把迁移写错——例如 `on_option=lambda n: numpad_queue.put(n)`（忘了盖章）、
或 worker 解包写反——**测试仍然全绿**，而真机上「连按两下点到新题」的 bug 原样复现。
`TestActionStamp` 的类 docstring 说「按键动作要**带**戳；执行前核对」，但只验证了「核对」，
没验证「带」。这是一处真实的覆盖缺口。（成因在计划：简报步骤 1 只列了这 5 个用例，
没要求测接线。实现者按简报做，不算违约。）建议后续任务补一个走 `numpad_worker` 的端到端用例。

---

## 4. 发现的问题

### 4.1【Minor】`kind == "next"` 路径不参与时戳核对，stamp 白盖

位置：`voice_tap/main.py:861`（入队时盖了 `identity()`）→ `main.py:834-835`
（`handle_next(ctx)` 丢弃 stamp）。

- 现状：`("next", None, identity())` 里的戳被盖章后**从未被使用**（死数据）。
  连按两下小键盘 `0`，第二下不经过任何核对。配了 `fixed_next_position` 时会直接点固定坐标。
- 为什么**不**算实现者的错/不算返工项：设计文档 §6 已经把它写成**明确记录在案的已知残留风险**——
  「小键盘 0（以及语音「下一题」）……连按两下 0 仍会点两次……本期按用户要求保持『直给』」。
  简报 Interfaces 也只圈定了 `handle_numpad` 的核对。实现者在其报告「疑虑 1」里主动复述了这一点。
- 建议：无必改。若后续想堵，让 `handle_next` 也接收并核对 `stamp`；至少在交接时把
  「`next` 项盖了戳但没人用」记进设计文档的另一处，避免后人误以为它已受保护。

### 4.2【Minor】核对块在 `if not snap.ok` 之前，会让「不在答题界面」说成「翻页了」

位置：`voice_tap/main.py:541-545`（核对）先于 `:547`（`snap.ok`）。

- 若小键盘路径带戳、且当前停在 QQ 等非目标界面，指纹必然不同 → 先命中核对块，
  输出「界面在按键之后翻页了」，而真正原因可能是「你根本不在 GRE3000」。日志有误导性。
- 影响很小（两种情况下都正确地不点，只是措辞不准），语音路径（stamp=None）不受影响。
- 建议（可选）：把核对块挪到 `if not snap.ok:` 之后，或把两种情形分开措辞。

### 4.3【Minor / 属设计取舍】时戳可能误伤「程序认知落后于真机」的合法按键

位置：`handle_numpad` 核对 + `identity()` 取 `_last_seen`。

- 场景：用户用鼠标在 scrcpy 里手动翻页，程序的 `_last_seen` 仍是旧屏（且缓存恰好落空走了当场读屏）。
  改前：当场读回新屏 → 正常点中；改后：`stamp`（旧屏）≠ `snap`（新屏）→ **丢弃这一下**。
  即修复引入了一个「本来能点、现在不点」的新丢弃口。
- 判断：这是设计 §4.5 明说的**保守取向**（「两者不同则作废」；宁可漏点不可错点），
  且有 `.` 强制读屏键可即时纠偏，用户再按一次即可。实现者报告「疑虑 2」也记录了它。
- 建议：不改。仅提示使用者：手动动过屏幕后先按 `.` 同步一次。

### 4.4【Minor】worker 解包失败静默 `continue`，不落日志

位置：`voice_tap/main.py:827-830`。

- 旧格式条目（或将来格式不符）会在这里被无声丢弃，连 `say()` 都没有。与项目
  「不吞异常 / 用户可见输出走 `say()`」的一贯风格略有出入。
- 但这段是**简报逐字给定的代码**，实现者遵从了。当前也无旧格式写入点，实际触发不了。
- 建议（可选）：`except (TypeError, ValueError): say("[小键盘] 忽略了一条格式不对的队列条目"); continue`。

### 4.5【Minor / 文档】progress.md 仍标任务 1「进行中」

位置：`.superpowers/sdd/progress.md` 表格第 1 行（状态「进行中」、提交 `—`）。
这是编排方的台账，按报告说法不在实现者任务范围内，只是提醒交接时更新（提交已是 `0d09a85`）。

---

## 5. 代码质量

- **风格一致**：新增注释、`say()` 文案、docstring 全是中文，与既有风格一致（`identity()`
  的 docstring 与 `miss_reason()` 同一笔调）；无裸 `print()`；无吞异常（除 4.4 那处简报给定的
  `continue`）。
- **锁正确**：`identity()`（`main.py:213-224`）持 `self._lock` 读取 `_last_seen` 后调用
  静态 `signature()`，无重入、无死锁；与 `take()`/`peek()`/`invalidate()` 的加锁方式一致。
  `invalidate()` 刻意不动 `_last_seen`，正是本修复依赖的语义（点完之后 `identity()` 仍返回
  「你刚才看着的那一屏」），二者自洽。
- **无新竞态**：stamp 在回调线程盖、在 worker 线程核对，两处都只经锁读写 `_last_seen` / 本地快照。
- **老路径无回归**：`handle_numpad` 第三参数可选，语音/既有测试的 `handle_numpad(n, ctx)`
  调用不受影响；`handle_next` / `handle_force_read` 未被改动；不带 `--gui` 行为不变。
  全套 227（含原 222）通过即为证据。
- **无状态不一致**：`grab_screen` 的兜底分支会 `note()` 刷新 `_last_seen`，但核对用的是
  **按键时刻**的 stamp，不会被它顶掉；逻辑正确。

---

## 6. 我没能验证到的部分

1. **真机端到端**：本次只在假 adb（`FakeAdb`）上验证，没在真机上复现「连按两下点到新题」的
   原始时序。修复的语义正确性来自对 `ScreenPrefetcher`（`note`/`take`/`invalidate`/预读线程）
   的静态推演 + 单元测试，真机时序（预读耗时与按键间隔的竞争）未经实测。
2. **队列接线的运行时行为**：`numpad_worker` + 三个 lambda 的组合**没有测试覆盖**（见 3.3），
   我只做了静态阅读与 grep，确认三处入队都已迁移、worker 按 kind 分派；
   没有实际跑起 `main()` 走热键路径（需要 keyboard 库与真机交互）。
3. **`screen.read_screen` 的指纹稳定性**：我确认了两份夹具的题干/选项文字确实不同
   （`degrade` vs `prototype`），故签名必不同；但没有逐一验证真实采集的各题 dump 之间
   是否可能出现「题干+选项完全相同」的碰撞（理论上极低，交由设计层判断）。

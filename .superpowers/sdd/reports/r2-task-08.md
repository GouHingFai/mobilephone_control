# r2 任务 8 报告：预读读到的屏幕立刻显示（界面 + 控制台）

## 状态

**DONE**

（要改的四条全改完，五条测试全绿；「改坏看红」做了三次、逐个复原；
全套 **341 → 353 全过**；提交 `见下`。

**没能验证的仍然是同一件事：真 Tk 窗口、真机 adb、麦克风 —— 沙箱都没有。**
控制台那一路我用一个内存里的仿真把改前/改后的输出做了 diff（见「实跑证据」），
界面那一路只到 `UiState` 这一层，`gui.py` 把 `ScreenView` 画出来那一步没跑过。）

## 改了什么

| 文件 | 动作 | 内容 |
|---|---|---|
| `voice_tap/main.py` | 改 | `ScreenPrefetcher.__init__` 加 `on_screen=None`；`note()` / `note_if_current()` 加 `source=""`，存下之后按「内容变没变」决定播；新增 `_emit()`（唯一的播报出口）；四处 `note()` 调用点补上 `source`；`grab_screen` 去掉重复的 `publish_screen`；新增 `make_screen_publisher()`；`main()` 把回调接上 |
| `tests/test_prefetch.py` | 改 | `make_prefetcher` 支持 `on_screen`；新增 `TestBroadcastScreen`（7 条） |
| `tests/test_pipeline.py` | 改 | `StubPrefetcher` 跟上新语义（`source` / `on_screen`）；`make_ctx` 挂真接线；新增 `make_prefetch_ctx` / `wait_for` / `CountingUiState`；新增 `TestScreenPublisher`（2 条）、`TestForceRead` 加 1 条、`TestUiStateWiring` 加 1 条、新增 `TestPrefetchedScreenReachesTheUiWithNoExtraKey`（1 条） |
| `tests/test_inventory.py` | 改 | `test_pipeline` 基线 123 → 128、`test_prefetch` 33 → 40（都注明理由）；`REQUIRED_CLASSES` 加 `TestBroadcastScreen` / `TestPrefetchedScreenReachesTheUiWithNoExtraKey` / `TestScreenPublisher` |

`config.yaml` / `gui.py` / `.gitattributes` / `.bat` / 文档 **一行没动**（文档按简报要求留最后）。

### 播报的规矩（`_store_locked` 里定，锁内）

两个条件都满足才播，两条都在**同一把锁**里判定：

1. **调用方要求播**（`source` 非空，默认 `""` = 不播）。所以 `note()` 的老调用方
   和测试里的桩不传 `source` 时行为一字未变。
2. **内容跟上一次播出去的**不同（比 `signature()`）。「还是旧界面 → 再读一次确认」
   那条路会把同一屏存两次，不去重控制台就打两遍。

真正调回调挪到**出了锁之后**（`_emit()`）：回调要碰界面、要打印，占着预读器的锁
做这些会把 `take()` 一起堵住，预读线程和按键线程就互相等了。

`invalidate()` **不动** `_published_signature`（也不动 `_signature` / `_last_seen`）：
它记的是「界面上现在摆着哪一屏」，跟缓存作不作废是两件事。点击之后翻页没发生、
读回来还是同一屏时，正是靠它做到「不播」。

### `on_screen(snap, source, age)` 多带了 `age`（简报允许，说明理由）

简报说「形如 `on_screen(snap, source)`」，并允许我多加一个参数或改调
`peek_with_age()`。**我选了多加 `age`**，理由：

- `age` 在预读器里是现成的（`time.monotonic() - read_at`，`read_at` 就是刚存下的
  那一份的时间基准），多传一个参数是零成本；
- 走 `peek_with_age()` 要**再拿一次锁**，而且 `_emit` 是在出了锁之后调的 ——
  这中间万一另一个线程存了更新的屏，`peek_with_age()` 给出的年龄就会配上界面里
  显示的那一屏**不是同一份**（界面写着「3 秒前的屏」其实是别人刚读的）。多传一个
  参数就没有这个缝。

### 控制台那行

实际打的是 `[屏幕] （预读）` / `[屏幕] （当场读屏）` / `[屏幕] （强制读屏）` /
`[屏幕] （启动时读到的）` —— **直接用 `source`**。简报的例子写的是「（预读到的）」，
但来源串按简报的表是「预读」；我不想再维护一张「来源 → 显示名」的映射表
（多一张表就多一个会走样的地方，本项目在「名字对不上」上栽过两次）。
要改成「预读到的」是一行的事。

## 测试结果

```
$ rm -rf tests/__pycache__ voice_tap/__pycache__
$ python3 -m unittest discover -s tests
Ran 353 tests in 14.503s
OK
```

- **起点 341，终点 353，净 +12**（`test_prefetch` +7、`test_pipeline` +5）。
- 逐文件实际值（与基线核对过，全部相等）：

  | 文件 | 实际 | 基线 |
  |---|---|---|
  | test_audio | 19 | 19 |
  | test_config | 36 | 36 |
  | test_hotkey | 25 | 25 |
  | test_inventory | 3 | — |
  | test_matcher | 57 | 57 |
  | **test_pipeline** | **128** | **123 → 128** |
  | **test_prefetch** | **40** | **33 → 40** |
  | test_screen | 27 | 27 |
  | test_ui_state | 7 | 7 |
  | test_voice_gate | 11 | 11 |

### 先红后绿

测试先写，`main.py` 没动之前跑 `tests.test_prefetch tests.test_pipeline`：

```
Ran 167 tests in 0.512s
FAILED (errors=126)
AttributeError: module 'voice_tap.main' has no attribute 'make_screen_publisher'
```

（126 个 error 全是这一句 —— `make_ctx` 在桩上挂真接线时报的。这正是「接线不存在」的
红灯形式。）改完之后同样两条命令全绿。

### 改坏看红（三次，每次都从备份还原，最后 `git status` 干净）

| # | 改坏什么 | 结果 |
|---|---|---|
| 1 | `_emit()` 里那次回调调用去掉（等于简报说的「把 note() 里那次回调调用去掉」） | **6 红**：`TestForceRead.test_broadcasts_the_fresh_screen_to_the_ui` **FAIL**（`unexpectedly None : 强制读屏之后界面要拿到刚读到的那一屏`）、`TestPrefetchedScreenReachesTheUiWithNoExtraKey` **ERROR** —— 第 3、4 条如期变红；`TestBroadcastScreen` 4 条也一起红（`实际播了 []`） |
| 2 | 把 `grab_screen` 里那句重复的 `publish_screen` 加回去 | `test_grab_screen_publishes_the_fresh_read_only_once` FAIL：`AssertionError: 2 != 1 : 同一屏只该播一遍` |
| 3 | 拿掉 `handle_force_read` 的 `source="强制读屏"` | `test_broadcasts_the_fresh_screen_to_the_ui` FAIL（界面永远是空的） |

第 1 条我把回调调用收进了**单一出口** `_emit()`（`note()` 和 `note_if_current()` 都汇到它），
所以「去掉播报」只有一个地方可改、一改两条路一起失效。简报里说的是「note() 里那次
回调调用」—— 预读那条路实际走的是 `note_if_current()`，若不收成一处，只改 `note()`
的话第 4 条不会红。这一点是我按简报的**意图**（第 3、4 条都要红）调整的实现细节。

## 实跑证据（内存仿真，不需要手机/界面）

用一个假 adb + 真 `ScreenPrefetcher` + 真 `make_screen_publisher`，跑一遍
「启动读一屏 → 按一次 1（缓存命中）→ 等预读 → 按一次 .」，**不带 ui**（模拟不带 `--gui`），
把控制台输出存下来做 diff。两次唯一的差别就是「挂不挂播报回调」，所以 diff 就是本次改动
对控制台的全部影响：

```
===== 改之前 =====
[小键盘] 1
[屏幕] 题干：degrade
[屏幕] 选项：adj. 清晰易懂的 / …
       （界面来源：预读，0.0 秒前读好的（没读屏））
[匹配] 小键盘第 1 个 → 点击坐标 (606, 811)
[点击] 完成
       [预读] 读到新界面，距点击 2 毫秒（本次读屏 0 毫秒）
[小键盘] . → 强制重新读屏
[屏幕] 题干：prototype
[屏幕] 选项：adj. 狂怒的 / …
       （强制读屏 0 毫秒（12 KB））

===== 改之后（只列出多出来的行）=====
+ [屏幕] （启动时读到的）
+ [屏幕] 题干：degrade
+ [屏幕] 选项：adj. 清晰易懂的 / …
…
+ [屏幕] （预读）                 ← 点击之后、**还没按任何键**，新题就自己打出来了
+ [屏幕] 题干：prototype
+ [屏幕] 选项：adj. 狂怒的 / …
```

**这就是用户要的东西**：点击之后那几秒里控制台已经把新题（prototype）打出来了，
而改之前要等到他按「.」或下一次按键才看得到。顺带还验证了去重：最后那次
**强制读屏没有重复打** —— 因为这一屏（prototype）刚刚已经播过了。

「当场读屏」兜底那条路我也单独跑过（缓存空 + peek 也是 None）：控制台多 3 行。

## 提交哈希

```
见 `git log -1`
```

## 我**没能**验证什么（这一节请务必当真）

1. **真 Tk 窗口：仍然一次都没跑过。** 沙箱是 Linux、无显示器、没装 tkinter。
   本次改的界面那一路只验证到 `UiState.set_screen()` 收到了正确的 `ScreenView`
   （题干/选项/来源/年龄），**`gui.py` 把这一份画到浮窗上那一步没执行过**。
2. **真机 adb / scrcpy / 麦克风 / 小键盘**：依旧没跑。`--gui` 与不带 `--gui` 两条
   启动路径的真实行为没验过。
3. **`main()` 里那一行接线**（`ScreenPrefetcher(..., on_screen=make_screen_publisher(ctx))`）
   **没有测试盖住**：`main()` 起不来（要 adb / 麦克风），跟 `ScreenPrefetcher(adb, cfg, log=say)`
   原来那一行一样没有用例。我测到的是（a）`make_screen_publisher` 本身、（b）预读器
   真会调回调、（c）`StubPrefetcher(on_screen=...)` 这条等价接线。**唯一没被自动测住的
   就是「main() 有没有把参数传进去」这 1 行。**
4. **多线程下播报的时序**没在真机上观察过（回调跑在预读后台线程，和界面刷新线程、
   按键工作线程并发）。`UiState` 是线程安全的（这是它唯一的卖点，另有 7 条用例），
   `say()` 只是 `print`，但「界面正在重画时来一次 set_screen」的真实表现没看过。
5. **`age` 的显示语义**：预读那条路 `read_at` 取的是**读屏开始**的时刻，所以界面上
   那个「几秒前读到的」约等于一次读屏的耗时（真机约 2.4 秒）。这个是老语义（
   `take()` 的 age 一直这么算），我没改，也没在真机上看过好不好理解。

## 疑虑（含「简报与代码对不上的地方」，照实说）

1. **简报说 `note()` 有四处调用点，实际有**五**处。** 漏掉的是
   `trigger_on_speech()`（开口时预读）里那句 `self.note(snap, read_at=read_start)`。
   我**没有**给它加 `source` —— 简报的来源表里没有它，加了就是超出简报。
   影响很小：`prefetch.on_speech` 默认是关的；真开了这个开关、又想在界面第二块看到
   那一屏的话，**加一句 `source="预读"` 就行**（我在代码里留了注释说明）。
   要我现在就加，说一声。
2. **简报说「控制台多打两行」，实际每次播报是 3 行**（1 行来源标记 + `show_screen` 的
   题干/选项两行）。上面那份仿真里，一次完整按键流程共多 **6 行**（启动 3 + 点击后预读 3）。
   我认为这仍是简报的本意（「那两行正是用户要的」指的是 `show_screen` 那两行），
   但数字对不上，写清楚。
3. **「当场读屏」和「强制读屏」这两条路上，同一屏会在控制台打两遍**：
   `note()` 播一遍（新加的），调用方自己紧跟的 `show_screen(snap)` 再打一遍
   （`handle_numpad` / `handle_force_read` 里原有的）。仿真实测「当场读屏」那条路
   共 10 行（改前 7 行）。
   简报只说了去掉 `grab_screen` 里重复的 `publish_screen`（那是**喂界面**的重复），
   没提这个**打控制台**的重复。我**没动** `handle_numpad` / `handle_force_read` 里
   原有的 `show_screen`，因为：它们还管着「用缓存」那一档和语音那条路 ——
   那一档不经过 `note()`，删了那两条路就一句屏幕内容都不打了。
   想消掉重复的话，办法是让 `handle_force_read` 不再自己 `show_screen`
   （代价：连续按两次「.」而屏幕没变时，控制台只剩一行「（强制读屏 12 毫秒）」、
   看不到内容）。**这是取舍，你定。**
4. **`--gui` 下「启动那一屏」进不了界面。** `ctx["ui"] = UiState()` 是在预读器**之后**
   才建的（在「准备界面读取」那一段之后），所以启动那次播报只有控制台看得到，
   界面第二块要等第一次点击/强制读屏才有内容。**这不是本次引入的回归**（改之前界面
   同样是从空开始的），但「启动时读到的」这个来源实际上只有控制台看得见。
   要补是在 `ctx["ui"]` 建好之后补一次「只喂界面」的 `publish_screen`（约 4 行）。
   我没做 —— 简报没要求，且那条路要碰 `--gui` 起不来时的收尾逻辑。
5. **`_published_signature` 只由 `note()` / `note_if_current()` 的播报更新。**
   `grab_screen`「用缓存」那一档是**直接**调 `publish_screen` 的（简报明确要求保留），
   它不更新这个指纹。后果：启动探测失败（`_published_signature` 一直是 `None`）、
   且之后某次点击**翻页没发生**时，同一屏会在控制台多打一遍。
   真机上启动探测几乎总会成功（它一成功就把指纹定下来了），所以实际影响很小。
6. **`source` 的取值直接进了控制台文案**，我没做中英/长短统一。四个值分别是
   「预读」「当场读屏」「强制读屏」「启动时读到的」—— 长短不一，看着略不齐
   （简报给的例子是「预读到的」）。要统一改名（比如全用「预读到的」）是改四处字符串。

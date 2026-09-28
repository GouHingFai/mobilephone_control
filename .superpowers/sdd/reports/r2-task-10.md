# r2 任务 10 报告：预读每一轮收工前都兑现重启请求；强制读屏不再重复打屏

## 状态

**DONE**

（三处都按简报做了：缝一、缝二、`handle_force_read` 的重复打屏。
三条新用例先红后绿，每条都单独做过一次「改坏看红」并复原；
全套 **357 → 360 全过**；`test_inventory.py` 基线按实际更新并注明理由；
提交哈希见下。

**仍然没验证的**：真机 adb、真 Tk 窗口、麦克风 —— 沙箱里都没有（老样子）。
本次改的两处都不碰界面布局、不碰 `gui.py`、不碰 `.bat` / `.gitattributes`，
但「真机上连点两下的手感」和「控制台最终长什么样」只有上机才算数。）

## 改了什么

| 文件 | 动作 | 内容 |
|---|---|---|
| `voice_tap/main.py` | 改 | 缝一/缝二：`work()` 收工前改成「**每一轮结束时都看一眼 `_restart`**」，判据从「这一轮自己报了被作废」换成「**代数真的换了**」；并把**释放 `_busy` 挪进同一把锁**（原来 `return` 出 `with` 之后才由 `finally` 释放，中间有个缝）。`_prefetch_round` 的返回值只剩日志用途，注释同步。去重：删掉 `handle_force_read` 里那句重复的 `show_screen(snap)` |
| `tests/test_prefetch.py` | 改 | 加模块级 `make_cfg`（`make_prefetcher` / `make_blocking_prefetcher` 共用，去掉三份重复的参数表）；加 `make_quiz_xml` + `THIRD_XML`（要**第三屏**才分得清「重跑那一轮读到了什么」）；加 `FailsOnceAdb`（第一次 `dump_ui()` 抛异常，抛之前先做掉一次点击）、`ClickRightAfterStoringPrefetcher`（存下结果之后立刻做掉一次点击）；新增 `TestRestartIsHonouredHoweverTheRoundEnds`（2 条） |
| `tests/test_pipeline.py` | 改 | 在 `TestSameScreenIsPrintedOnlyOnce` 里加 `test_force_read_prints_the_screen_once`（1 条） |
| `tests/test_inventory.py` | 改 | `test_pipeline` 130 → 131、`test_prefetch` 42 → 44，都注明理由；`REQUIRED_CLASSES["tests.test_prefetch"]` 加 `TestRestartIsHonouredHoweverTheRoundEnds` |

`config.yaml` / `gui.py` / `.gitattributes` / `core.autocrlf` / `.bat` / 文档 **一行没动**。

### 缝一：结果已存下、收工前来了一次点击

**根因**（上一轮报告的「疑虑 2」自己点出来的，这次照着堵）：`work()` 的兑现条件是

```
if invalidated and self._restart:   # invalidated = _prefetch_round 的返回值
```

`_prefetch_round` 只在 `note_if_current` **因为换代而拒收**时才返回 `True`。
所以「结果**已经成功存下**（`store` 返回 `True`）之后才来的点击」这一轮返回的是
`False` —— 标记被无视、直接收工。可那次点击的 `invalidate()` 已经把缓存清掉了，
于是「缓存空、也没人在读」，症状跟上一轮修的那个一模一样。

**做法**：判据从「这一轮自己报没报被作废」换成「**代数真的换了**」：

```
while True:
    self._prefetch_round(gen, sig, delay, retry)
    with self._lock:
        if self._restart and self._generation != gen:   # 有人提请求 + 代数真换了
            self._restart = False
            gen = self._generation      # 按当前代数重跑
            sig = self._signature       # 按当前指纹重跑
            continue
        self._busy = False              # 收工：释放 _busy 与这次检查同锁
        self._restart = False
        return
```

- 「代数变没变」正好覆盖缝一：点击那条路一定先 `invalidate()` 换代、再
  `trigger_after_click()`，所以**只要有请求在，代数就一定换过**。
- 生产代码里 `trigger_after_click()` **只被 `do_click` 调**（`invalidate()` 之后紧跟着，
  `main.py:1113/1120`），所以两种判据在生产里等价；差别只出现在「没有换代的
  单独一次 `trigger_after_click()`」——那正是 `test_does_not_run_twice_concurrently`
  钉住的情形（见下方「疑虑 1」）。
- 顺带补上「检查与释放 `_busy` 同锁」：原来 `return` 出了 `with` 之后才由 `finally`
  释放，中间那个缝里来的点击会看到 `_busy` 还立着、把请求记成标记，而这边已经
  决定收工 —— 又是一次丢失。现在这两件事在同一把锁里做完。

### 缝二：读屏失败那一轮同样兑现

`_prefetch_round` 里两处「读屏失败」都是 `except → return False`，所以旧判据同样
把 `_restart` 无视掉。换判据后自动被覆盖（期间点击照样换代），不需要额外代码。

### 顺手：`handle_force_read` 不再重复打屏

删掉 `handle_force_read` 里那句 `show_screen(snap)`。上面 `note(source="强制读屏")`
已经把这一屏播出去（界面 + 控制台那几行），再打一遍就是用户说的
「之前展示了预读的，为什么又要展示一次」。保留 `say("（强制读屏 N 毫秒（M KB））")`
（说的是这次读屏花了多久，不是重复内容）；`report_unusable_screen` 里的
`show_screen` **保留**（出错路径，用户正要看清屏上有什么）。

## 测试先红后绿的证据

### 先红（实现之前，三条都红、且红在点上）

```
FAIL: test_a_click_between_storing_and_finishing_still_gets_a_round
AssertionError: unexpectedly None : 存下结果之后来的那次点击不能被丢掉 ——
  旧写法这里是空的：这一轮没被作废，标记就被无视了，而缓存刚被 invalidate 清掉

FAIL: test_a_click_around_a_failed_read_still_gets_a_round
AssertionError: unexpectedly None : 读屏失败那一次之后来的点击不能被丢掉
  （会再跑一轮并成功）

FAIL: test_force_read_prints_the_screen_once
AssertionError: 2 != 1 : 同一屏的题干只该打一次（播报那一次），强制读屏不许再打一遍：
[小键盘] . → 强制重新读屏
[屏幕] （强制读屏）
[屏幕] 题干：degrade
[屏幕] 选项：adj. 清晰易懂的 / adj. 阴郁的，闷闷不乐的 / ...
[屏幕] 题干：degrade            ← 同一屏第二遍
[屏幕] 选项：adj. 清晰易懂的 / adj. 阴郁的，闷闷不乐的 / ...
       （强制读屏 0 毫秒（12 KB））
```

### 后绿

```
Ran 360 tests in 14.6s
OK
```

### 改坏看红（三条各做一次，每次都复原）

| # | 改坏什么 | 结果 |
|---|---|---|
| 1 | 把收工判据改回上一版 `invalidated and self._restart`（即「只在自己被作废时才看标记」） | 缝一的用例 **FAIL**：`unexpectedly None : 存下结果之后来的那次点击不能被丢掉……`；缝二的用例 **FAIL**：`unexpectedly None : 读屏失败那一次之后来的点击不能被丢掉（会再跑一轮并成功）`。同一次运行里 `TestDoubleClickDoesNotDropThePrefetch` 两条与 `TestTriggerAfterClick` 六条**仍绿** |
| 2 | 去掉「代数真的换了」这个判据（`if self._restart:` 一律重跑） | `test_does_not_run_twice_concurrently` **FAIL**：`AssertionError: 2 != 1`（同一对请求下多读了一轮）。见「疑虑 1」 |
| 3 | 把 `show_screen(snap)` 加回 `handle_force_read` | `test_force_read_prints_the_screen_once` **FAIL**（`2 != 1`，整段控制台输出里题干打了两遍）；同文件其余 6 条（含 `TestForceRead` 的界面播报那条）**仍绿** |

复原后 `git status` 只剩预期的 4 个文件改动，全套 360 全绿。

## 最终用例数

- 起点：**357 全过**
- 终点：**360 全过**（`test_prefetch` 42 → 44、`test_pipeline` 130 → 131）
- 基线实测值：`tests.test_prefetch` = 44、`tests.test_pipeline` = 131，与写进
  `BASELINE_COUNTS` 的数字**逐个对得上**（不是「贴着上限」）

## 提交哈希

```
9193a5cbca47b8ac4f1632f08e2e0d3c4a0a2d2f  fix: 预读的每一轮收工前都兑现重启请求；强制读屏不再重复打屏
```

（哈希这一行由随后的 `docs:` 提交补上 —— 一条 `git commit` 没法把这次提交自己的
哈希写进它带来的文件里。与仓库既有惯例一致：任务 9 也是「先 fix、后 docs」。）

## 我**没能**验证什么（务请当真）

1. **真机 adb / 真 Tk 窗口 / 麦克风：依旧没跑。** 三处改动的真机表现
   （连点两下的响应、控制台最终输出）没有上机验过。
2. **「检查与释放 `_busy` 同锁」那半句没有针对性用例。** 那是个几微秒的竞态缝，
   靠假 adb 造不出来（造得出来就不叫竞态了）。所以这条只有代码审查，
   没有任何用例能证明「缝真的焊上了」。改动本身是安全的（`finally` 里那次
   兜底还在，重复置 `False` 无害）。
3. **`main()` 那条接线**（`ScreenPrefetcher(..., on_screen=make_screen_publisher(ctx))`）
   仍然没有用例盖住 —— 跟任务 8 / 9 报告里说的是同一处（要起 adb/麦克风才行）。
4. **重跑的耗时在真机上什么样**：沙箱里 `dump_ui` 是假的（0 毫秒）。真机一次读屏
   ≈2.4 秒，缝一/缝二这两种情形下「重跑」会把预读推迟到「第一轮跑完 + 又一次读屏」。
   延迟本身**不是本次引入的**（上一轮的重跑机制就是这样），但这两个缝被堵上之后
   **多跑一轮的机会变多了**，所以真机上的总延迟我没有实测。
5. **`adb.dump_ui()` 内部重试**（`retries=3, retry_wait=0.4`）会把这轮的时间拉长，
   期间来的点击能不能被可靠兑现，只在假 adb 上验过。

## 疑虑（含「简报与代码对不上的地方」，照实说）

1. **简报里「置着就清掉它、再跑一轮」这句要按字面做，会把
   `test_does_not_run_twice_concurrently` 弄红 —— 所以我没有按字面做。**

   简报同一段又说「注意别改坏 `test_does_not_run_twice_concurrently`」，
   这两条要求**互相矛盾**：
   - 字面做法（`if self._restart:` 无条件重跑）：**实测** `AssertionError: 2 != 1`
     （见改坏实验 2）。那个用例调了两次 `trigger_after_click()` 而**中间没有
     `invalidate()`**，无条件重跑就会多读一轮。
   - 我采用的判据（`self._restart and self._generation != gen`）两个缝都堵上，
     且该用例**照旧绿**。

   佐证：这个判据**正是上一轮报告「疑虑 2」自己开的方子** ——
   「判据从『这一轮返回作废』改成『**代数真的换了**』（`gen != self._generation`
   且 `_restart`）即可，一行的事，且不破坏『没有换代时不重跑』
   （`test_does_not_run_twice_concurrently` 照样绿）」。而且那个用例自己的
   docstring 写的判据就是「**没有换代**时标记不会被兑现」。
   简报「每轮结束时都要检查一次 `_restart`、别只在自己被作废时才检查」这条
   **我照做了**：检查确实每轮都做，只是兑现还要代数是新的。
   **若你要的就是字面上的「无条件重跑」，请说一声**：改一行、再把那个用例的
   `calls == 1` 换成「只有一个 dump 在跑（`max_concurrent == 1`）」即可 ——
   但那是改一个你叮嘱过别弄红的用例。

2. **简报说「把 `app.say` 换掉收集输出」—— 那样拦不到要数的那句话，我改用了
   `mock.patch("builtins.print")`。**

   `show_screen` 的 `log=say` 与 `make_screen_publisher` 的 `log=say` 都是
   **函数定义时**就绑好的默认参数，事后替换 `app.say` 拦不到它们；
   而「题干」正是 `show_screen` 打的。拦不到就数了个寂寞。
   同文件 `TestSameScreenIsPrintedOnlyOnce` 那两条早就踩过这个坑，注释里写着为什么
   改用拦 `print`（所有输出都经 `say()` → `print()`，拦一处就全收齐）。
   我照那条路走，注释里也写明了理由。

3. **`handle_force_read` 出错那条路的屏仍然会打两遍 —— 按简报保留的，但值得知道。**
   `note(source="强制读屏")` 在 `if not snap.ok` **之前**执行，所以「不在答题界面 /
   没有选项」时，播报打一遍、`report_unusable_screen` 里的 `show_screen` 再打一遍。
   简报明说那处**保留**（用户正要看清屏上有什么），所以没动。
   代价是同一屏在出错路径上仍是两遍 —— 是取舍不是遗漏。

4. **`trigger_on_speech()`（开口时预读，默认关）仍然不认 `_restart`。**
   它跟点击后预读共用 `_busy`，但它的 `finally` 只放开 `_busy`、不看标记。
   这是上一轮报告「疑虑 3」的原样，**不是本次引入的回归**，而且 `on_speech`
   默认关、真机碰不到。要彻底修得让语音那条路也认 `_restart`（或统一读代数），
   超出本次「补两个缝」的范围，没动。

5. **「同一屏不重复播报」那层去重（`_published_signature`）一行没碰。**
   删掉 `handle_force_read` 里那句 `show_screen` 之后，仍依赖 `note()` 的播报来显示
   这一屏；如果这一屏**内容跟上次播过的完全一样**（`_published_signature` 相同），
   控制台就只剩「（强制读屏 N 毫秒）」那一行、看不到题干选项。
   跟任务 9 给 `handle_numpad` / `handle_speech` 做的取舍完全一致
   （用户点名要的「同一屏别打两遍」），这里如实记一笔。
6. **测试文件里顺手做了一点重构**：`make_cfg` 抽出来给三个构造器共用、
   `make_prefetcher` / `make_blocking_prefetcher` 的参数表不再各写一份
   （原来三份一模一样的 dict）。是纯搬移，行为没变（全套 360 绿）。
   若不想要这点附带改动，可以只留新用例、把搬移退回去。

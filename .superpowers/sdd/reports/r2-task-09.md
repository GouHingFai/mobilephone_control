# r2 任务 9 报告：连点不再丢掉预读；同一屏不再打两遍

## 状态

**DONE**

（两处缺陷都按简报做了；四条新用例先红后绿各做过一次「改坏看红」、逐个复原；
全套 **353 → 357 全过**；`test_inventory.py` 基线按实际更新并注明理由；
提交哈希见下。

**仍然没验证的**：真机 adb、真 Tk 窗口、麦克风 —— 沙箱里都没有（老样子）。
本次改的两处都不碰界面布局、不碰 `gui.py`，但「真机上连点两下的手感」和
「控制台最终长什么样」只有上机才算数。）

## 改了什么

| 文件 | 动作 | 内容 |
|---|---|---|
| `voice_tap/main.py` | 改 | 缺陷一：`__init__` 加 `_restart` 标记；`trigger_after_click` 在 `_busy` 时**不再丢弃**请求，改为置标记；把「一轮预读」抽成新方法 `_prefetch_round`，`work` 在同一线程里循环「发现作废→有标记→按当前代数与指纹重跑」。缺陷二：删掉 `handle_numpad` / `handle_speech` 里那两句重复的 `show_screen(snap)` |
| `tests/test_prefetch.py` | 改 | `BlockingAdb` 加 `max_concurrent`（同时进入 `dump_ui` 的线程数峰值）；把两个类共用的阻塞预读器构造抽成模块级 `make_blocking_prefetcher`；新增 `TestDoubleClickDoesNotDropThePrefetch`（2 条）；修正 `test_does_not_run_twice_concurrently` 的过时注释（行为未变，它仍绿） |
| `tests/test_pipeline.py` | 改 | 新增 `TestSameScreenIsPrintedOnlyOnce`（2 条：按键那条路 / 语音那条路各一条） |
| `tests/test_inventory.py` | 改 | `test_pipeline` 128 → 130、`test_prefetch` 40 → 42，都注明理由 |

`config.yaml` / `gui.py` / `.gitattributes` / `core.autocrlf` / `.bat` / 文档 **一行没动**。

### 缺陷一：连点两下不再丢掉预读

**根因**（简报给的真机日志复核属实）：`trigger_after_click()` 开头那句
`if self._busy: return` 把「已有预读在跑时又来的一次点击」**整个丢掉**，
既不排队也不重来。于是两下过去一次预读都不剩：第一下的结果因换代作废，
第二下的请求被丢，缓存空、也没人在读。

**做法**：加一个「重启请求」标记 `_restart`。

- `trigger_after_click()` 发现 `_busy` 时**不丢弃**，只把 `_restart` 置上
  （点击那条路一定先调过 `invalidate()`，所以它天然落在「新的一代」上）。
- 把原来 `work` 里那一整轮逻辑抽成 `_prefetch_round(generation, before, delay, retry)`：
  跑完返回 `True` = **这一轮的活已经作废**（`note_if_current` 返回 False），
  返回 `False` = 正常收工（读到新屏/两次一样收下/读屏失败放弃）。
- `work` 改成**同一线程内循环**：

  ```
  while True:
      invalidated = self._prefetch_round(gen, sig, delay, retry)
      if invalidated and self._restart:      # 作废了，而且有人要求重启
          self._restart = False
          gen = self._generation             # 按当前代数重跑
          sig = self._signature              # 按当前指纹重跑
          continue
      return                                 # 否则收工（finally 里放开 _busy）
  ```

- 关键点：**不另起线程**。两个 `uiautomator dump` 同时对同一台手机下命令，
  实测把单次读屏从 2.4 秒拖到 8.5 秒（`take_or_wait` 的注释里写着）——
  所以用「标记 + 同一线程循环」：请求不丢、始终只有一个 dump 在跑、
  最后一次点击一定有一次针对它的预读。
- 重跑时指纹取**重跑那一刻**的 `_signature`（不是第一轮开始时的），
  这样「翻页检测」按的是最新基准。

两处 `return False`（读屏失败）刻意**不算**「作废」：读失败没有可重跑的意义，
返回 `True` 会让它在有标记时空转一轮。

### 缺陷二：同一屏只打一次

**要的行为**：每一屏只打一次，打在「程序刚知道它」的那一刻（也就是播报那一次）。

`grep` 过一遍 `show_screen(`，一共四处调用点：

| 位置 | 处理 | 理由 |
|---|---|---|
| `make_screen_publisher.on_screen`（第 1048 行附近） | **保留** | 它就是**播报本身** —— 删了整个「读到了就说」就废了 |
| `report_unusable_screen`（错误路径） | **保留**（简报点名） | 出错时用户正要看到底屏上有什么，重复也值 |
| `handle_speech` | **删** | 简报点名；同一屏在播报时已打过 |
| `handle_numpad` | **删** | 简报点名；同上 |
| `handle_force_read`（`.` 强制读屏） | **保留** | 见「疑虑 1」—— 简报没点名，我没多删，但把它当计划问题单独报出 |

「（界面来源：预读，3.9 秒前读好的（没读屏））」那一行**原样保留**：
它是 `say(f"       （界面来源：{source}）")`，说的是**这一下用的是哪一份、多旧**，
不是重复屏幕内容（简报点名要保留）。

`_published_signature` 那层去重**没动**：`note()` / `note_if_current()` → `_store_locked`
里的判定一字未改（`TestBroadcastScreen` 七条全绿）。

## 测试结果

```
$ rm -rf tests/__pycache__ voice_tap/__pycache__
$ python3 -m unittest discover -s tests
Ran 357 tests in 14.555s
OK
```

（连跑 4 次都是 `OK`，没有飘。）

- **起点 353，终点 357，净 +4**（`test_prefetch` +2、`test_pipeline` +2）。
- 逐文件实际值（与基线核对过，全部相等）：

  | 文件 | 实际 | 基线 |
  |---|---|---|
  | test_audio | 19 | 19 |
  | test_config | 36 | 36 |
  | test_hotkey | 25 | 25 |
  | test_inventory | 3 | — |
  | test_matcher | 57 | 57 |
  | **test_pipeline** | **130** | **128 → 130** |
  | **test_prefetch** | **42** | **40 → 42** |
  | test_screen | 27 | 27 |
  | test_ui_state | 7 | 7 |
  | test_voice_gate | 11 | 11 |

### 新用例都是什么

`tests/test_prefetch.py::TestDoubleClickDoesNotDropThePrefetch`（2 条，都用 `BlockingAdb`
把「预读卡在第二次读上」这一刻钉死，不靠 sleep）：

1. `test_second_click_reruns_and_caches_the_screen_read_after_it` —— **主证据**。
   第一下启动预读 → 卡在第二次读上 → 第二下（`invalidate` + `trigger_after_click`）
   → 放行 → 等收工。断言：**缓存里是「第二下之后才读到的那一屏」（prototype）**、
   `dump_ui` 共 3 次（第一轮两次 + 按新代数重跑一次）、**`max_concurrent == 1`**
   （始终只有一个 dump 在跑）。
2. `test_second_click_is_remembered_not_silently_dropped` —— 断言第二次
   `trigger_after_click()` 之后 `_restart` 被置上（**没有静默什么都不做**），
   且放行后这个请求**真的兑现**（缓存里是第二下之后那一屏），兑现后标记清掉。

`tests/test_pipeline.py::TestSameScreenIsPrintedOnlyOnce`（2 条，走真接线：
真 `ScreenPrefetcher` + `make_screen_publisher`，把整段控制台输出收下来数题干次数）：

1. `test_prefetched_screen_is_printed_once_when_used_by_numpad`
2. `test_prefetched_screen_is_printed_once_when_used_by_speech`

两条都断言 **那一屏的题干只出现一次**，且「（界面来源：预读…」那行还在。
**为什么拦 `builtins.print` 而不是换掉 `app.say`**（简报原话是「把 `app.say` 换掉」）：
`make_screen_publisher` 和 `show_screen` 的 `log=say` 是**函数定义时**就绑好的默认参数，
事后替换 `app.say` **拦不到预读播报那条线** —— 而那正是要数的那一路。所有输出都经
`say()` → `print()`，拦 `print` 一处全收齐（测试文件里 `TestScreenPublisher` 也是这么做的）。

### 先红后绿（改坏看红，两次针对性实验，每次都复原）

| # | 改坏什么 | 结果 |
|---|---|---|
| 1 | `trigger_after_click` 的 `_busy` 分支改回**直接 `return`**（丢掉请求） | 缺陷一的 2 条**全红**、缺陷二的 2 条仍绿：`test_second_click_reruns…` **FAIL** `unexpectedly None : 连点两下之后缓存里必须有东西 —— 旧写法这里是空的：第一下的结果作废了，第二下的请求又被丢掉`（**正是真机日志那个症状**）；`test_second_click_is_remembered…` **FAIL** `False is not true : 第二次请求要留下「重启」标记，不能静默丢掉` |
| 2 | 把 `show_screen(snap)` **加回** `handle_numpad` 与 `handle_speech` | 缺陷二的 2 条**全红**、缺陷一的 2 条仍绿：两条都 `AssertionError: 2 != 1`，控制台输出里「`[屏幕] 题干：degrade`」**确实打了两遍**（第二条用例的失败信息里整段输出可见） |

复原后 `git status` 只剩预期的 4 个文件改动，全套 357 全绿。

## 提交哈希

```
<见下：本条 fix 提交>
```

（本报告另起一个 `docs:` 提交写这一行，与仓库既有「先 fix 再 docs 报告」的惯例一致。）

## 我**没能**验证什么（务请当真）

1. **真机 adb / 真 Tk 窗口 / 麦克风：依旧没跑。** 本次两处改动的真机手感
   （连点两下的响应、控制台最终输出）没有上机验过。
2. **`main()` 那条接线**（`ScreenPrefetcher(..., on_screen=make_screen_publisher(ctx))`）
   仍然没有用例盖住 —— 跟任务 8 报告里说的是同一处（要起 adb/麦克风才行）。
3. **重跑的耗时在真机上什么样**：沙箱里 `dump_ui` 是假的（0 毫秒）。真机一次读屏
   ≈2.4 秒，连点时「重跑」会把最后一次点击的预读推迟到「第一轮跑完 + 又一次读屏」，
   也就是最多约 5 秒。**这个延迟我没有实测**，也没有上机确认用户能不能接受。
4. **`max_concurrent == 1` 只在 `BlockingAdb` 这个自造桩上验过**；真机上有没有
   别的东西（`adb.dump_ui` 内部重试）另起读屏，没看过。

## 疑虑（含「简报与代码对不上的地方」，照实说）

1. **`handle_force_read`（`.` 强制读屏）那处 `show_screen` 简报没点名，我按「别多删」
   保留了 —— 但它其实也是同一类重复：** 它在同一函数里先 `note(source="强制读屏")`
   （→ 播报打一遍），紧接着 `show_screen(snap)` 再打一遍。**屏幕内容变了时控制台就是
   同一屏两遍**（任务 8 报告的「疑虑 3」已经把它列成「纯观感问题」）。
   简报只列了 `handle_numpad` / `handle_speech` 两处，我**没有多删**它。
   按「每一屏只打一次」的原则，它也该删；代价是：连续按两次「.」而屏幕没变时，
   控制台只剩一行「（强制读屏 12 毫秒）」、看不到内容（因为去重过、这一屏上一次已播过）。
   **要不要删，你定** —— 删它是删一行；我倾向删（跟这次的原则一致），
   但简报没授权，就没动。
2. **缺陷一的两种窄缝里，请求仍可能被丢（我按简报的做法实现，如实报告）：**

   - **收尾那一瞬**：正在跑的那轮**已经成功存下**结果、但还没跑到 `busy=False` 时，
     用户点了第二下（`invalidate` 换代 + `trigger_after_click` 置 `_restart`）。
     这时这一轮返回的是 `False`（正常收工），`work` 就把 `_restart` 清掉收工了 ——
     第二下的请求没兑现。这个窗口是「存下之后到放开 `_busy`」之间的几微秒，
     真机上几乎不可能撞上；真撞上了，下一次点击会重新触发预读，影响只是
     「两下之间那一小段没有预读」，不会点错。
   - **读屏失败那一轮**：这一轮 `dump_ui` 抛异常（返回 `False`），期间用户点了第二下 ——
     它没有机会核对代数，所以被判成「正常收工」，`_restart` 被清掉。这个窗口是
     「读屏失败（含 `adb.dump_ui` 内部重试）的那一段时间」，比上一条宽一些。
   - 简报给的做法是「一旦发现自己这代的活已经作废（`note_if_current` 返回 False）…检查标记」，
     我**严格照做**了，所以上面两种情形都漏在网外。若想补上，判据从
     「这一轮返回作废」改成「**代数真的换了**」（`gen != self._generation` 且 `_restart`）
     即可，一行的事，且不破坏「没有换代时不重跑」（`test_does_not_run_twice_concurrently`
     照样绿）。**这一处是否要改，请定。**
3. **`trigger_on_speech()`（开口时预读，默认关）与 `trigger_after_click()` 共用 `_busy`。**
   若语音预读正在跑时用户按了键，`_restart` 会被置上，但语音那一轮不读这个标记，
   所以这次请求要等到**下一次点击**才开始（`trigger_on_speech` 的 `finally` 只放开
   `_busy`、不清 `_restart`，所以标记不会丢）。这跟改之前一样（以前也是直接丢），
   **不是本次引入的回归**；而且 `on_speech` 默认关，真机碰不到。
   要彻底修，得让 `trigger_on_speech` 也认 `_restart`（或干脆读 `_generation`）。
4. **「（界面来源：上一次读到的…）」那一档，控制台可能一行屏幕内容都没有。**
   按键走 `grab_screen` 的「缓存空 → 用 `peek` 旧屏」那一档时，如果那一屏当初是
   经「不播报」的路径（`trigger_on_speech` 的 `note()`，默认关）存进来的，
   去掉 `handle_numpad` 的 `show_screen` 之后，控制台就只剩下来源说明、没有题干选项。
   真机上这一档出现的前提是「缓存空 + 预读没读完」，且缓存里那份最后一次都是
   播过的（启动探测 / 预读 / 当场读屏都带 `source`），**所以实际影响很小**；
   写清楚以免日后有人拿它当 bug 查。
5. **改动的量比「两处小修」预期的略大**：为了让「重跑」复用一轮的逻辑，
   我把 `trigger_after_click` 里那一整轮抽成了 `_prefetch_round`，`work` 变成循环。
   这是必要的（否则要复制一整轮逻辑），但意味着 `trigger_after_click` 的
   **函数体几乎重写**—— 评审时值得逐行看一遍，别只看 diff 的行数。

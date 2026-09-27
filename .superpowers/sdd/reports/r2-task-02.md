# 任务 2 报告：预读最多读两次

**状态：DONE_WITH_CONCERNS**

（测试真全绿、改坏实验真会红、无偷懒。带 CONCERNS 是因为**计划里的测试片段有错**、
以及我**有意偏离了计划给出的日志文案**——两处都在下面写清楚了。）

- 提交：`996222e8a921e058ae0e7a9e8d233d1433e695e1`（`fix: 预读最多读两次 —— 不再白耗十秒挡住按键`）
- 最终用例数：**310 全绿**（起点 309，+1）


## 做了什么

1. **`voice_tap/main.py` — 重写 `ScreenPrefetcher.trigger_after_click`**
   去掉了 `for attempt in range(...)` 的重试循环，改成：
   - 点击后等 `click_delay_ms`，读一次；
   - 读到**和点击前不同**（或压根没有基准）→ 存下、收工（**这是常态，只读一次**）；
   - 还是旧界面 → 打一句「还是旧界面，再读一次确认」，隔 `click_retry_ms` 再读一次，
     **第二次无论读到什么都 `note()` 收下**（一样 → 「两次一样，认定这就是当前屏，收下」；
     不一样 → 「第二次读到了新界面，收下」）。
   - 两次读屏各自失败都记一句日志后放弃（沿用原来的降级方式）。
   - 总共**最多读两次**，第 3、4 次没有了。

2. **`voice_tap/config.py`** — `PrefetchConfig` 删掉 `click_max_attempts` 字段、
   `load_config` 删掉对应那行；`click_retry_ms` 保留，注释改成「最多读两次」的说法。

3. **`config.yaml`** — 删掉 `click_max_attempts` 那整段注释与配置项；
   `click_retry_ms` 补上「最多读两次」的说明；
   顺手把 `click_delay_ms` 上面那句**已经过时**的注释从
   「日志里会打印『**第几次**读到新界面…』」改成「『读到新界面…』」（见「偏离计划」第 3 条）。

4. **`tests/test_prefetch.py`** — 测试同步（详见下）。
   **`tests/test_inventory.py`** — `tests.test_prefetch` 基线 26 → 27，并在该文件里注明理由。

5. 未触碰 `gui.py` / `ui_state.py` / 热键与语音开关，未碰 `.gitattributes` / `core.autocrlf` / `.bat`。


## 测试结果

**起点**：清缓存后 `python3 -m unittest discover -s tests` → **309 全绿**。
（计划简报写「起点基线 311」，但真机仓库实际是 **309**；`.superpowers/sdd/progress-r2.md`
里也写着「起点 311 → 任务 1 后 **309 全绿**」——所以 309 才对，简报的 311 是笔误。）

**先改测试、确认红**（TDD）：
- `test_never_changes_still_stores_after_two_reads` → **红**：`4 != 2`（旧代码读满 4 次）。
- 原有的 `test_gives_up_when_screen_never_changes` 已被**改写成**上面这条（行为没了），
  所以「旧那条也红」是同一件事，不是两条独立的红。

**改完代码后**：`tests/test_prefetch` 27 全绿。

**「改坏看红不红」（步骤 5 + Global Constraint）—— 共两次实验，每次都清字节码缓存、跑完还原：**
1. 把「第二次无论读到什么都收下」改成「第二次仍一样就 `return` 不存」→
   `test_never_changes_still_stores_after_two_reads` **变红**（`unexpectedly None:
   第二次读到的就是当前屏，要收下`），且**只有这一条红**。
2. 把「第一次读到新界面就收工」的那个 `return` 去掉（强制多读一次确认）→
   `test_reads_once_when_screen_changed` **变红**（`2 != 1`）；
   `test_does_not_run_twice_concurrently` 同时也红（同一个 break 的副作用）。
   两条都说明护栏抓得住东西。

**还原后全套**：`Ran 310 tests ... OK`。另做校验：`config.yaml` 能正常加载
（`notices: []`、`hasattr(prefetch,'click_max_attempts') == False`）；`main.py` / `config.py` /
`gui.py` 均可 `compile()`；全仓库 `grep click_max_attempts` 无残留。


## 偏离计划的地方及原因

**1（计划有错，必须改）计划给的 `test_reads_once_when_screen_changed` 固定装置写错了。**
计划写的是：

```python
prefetcher, adb, _logs, _cfg = make_prefetcher(FIRST_XML, SECOND_XML)
prefetcher.note(screen.read_screen(FIRST_XML))
...
self.assertEqual(adb.calls, 1)
```

`SequenceAdb` 是**按顺序**返回的：第 1 次 `dump_ui()` 返回 `FIRST_XML`，而基准
`before` 也正是 `FIRST_XML`（上面刚 `note` 过）——所以**第一次读到的就是旧界面**，
它会走「再读一次确认」，第 2 次才返回 `SECOND_XML`。于是 `adb.calls == 2`，
**这条断言在改动前后都永远红**（改前红、改后也红）。
我把它改成 `make_prefetcher(SECOND_XML)`（第一次读就返回新界面），断言 `adb.calls == 1` 才成立。
改完后它在旧代码下也绿——也就是说它是一条**护栏**（防「读到新界面后又多读一遍」），
不是「改前红→改后绿」的变更探测器。这一点我在报告里点明，避免误以为它是红的。

**2（计划漏了）计划没提两条既有测试会被新行为打红，我做了最小必要改写：**
- `test_reads_until_screen_changes`：原来固定装置是 `(FIRST_XML, FIRST_XML, SECOND_XML)`、
  断言 `adb.calls >= 3`——那是「一直读到变化为止」的旧语义。新语义下它第二次（确认读）就会
  收下 `FIRST_XML`，`prompt` 不再是 `"prototype"`、次数也只有 2 → 必红。
  改成 `(FIRST_XML, SECOND_XML)`、断言 `adb.calls == 2`，含义仍是「第一次旧、第二次读到新的，
  取新的那份」，只是把「第二次」落到那次确认读上。测试名与用例数不变。
- `test_logs_include_timing`：固定装置 `(FIRST_XML, SECOND_XML)`，断言日志里含
  `预读` / `距点击` / `读屏`。计划给的日志文案把那三个词里的 `距点击`、`读屏`
  从「旧界面→确认」这条路径上全删了 → 必红。**见下一条，我用改日志而不是改测试来消掉它。**

**3（有意偏离）我在确认路径的日志里保留了计时信息，而不是删掉。**
计划步骤 3 给的日志是：`「还是旧界面，再读一次确认」`、`「两次一样…收下」`、
`「第二次读到了新界面，收下」`——都不带计时。但这样一来，
**项目现有的 `test_logs_include_timing` 就保不住**，只能去削弱它的断言。
本仓库的明文要求是「每写一条声称守住某行为的测试，先改坏它确认会红」、
以及 test_inventory 的整套精神——**宁可保住既有护栏，也不为了让代码对上文案而削弱测试**。
所以我给确认路径的日志也补上了 `距点击 … 毫秒`（并保留原有的 `本次读屏 … 毫秒`），
让 `test_logs_include_timing` **一行都不改**仍然绿，同时调 `click_delay_ms` 的诊断信息不缩水。
除了这几句日志文案，主流程逻辑与计划一致。

**4（顺带、必要）`config.yaml` 里 `click_delay_ms` 上面那句注释写着日志会打印「第几次读到新界面」，
`第几次` 这个说法随本次改动消失了**，留着就是过时注释。我把它改成「读到新界面」，
并删掉了 `click_max_attempts` 整段（计划要求）。值本身（`click_delay_ms: 300` /
`click_retry_ms: 250` / `cache_max_age: 60.0`）一个没动。

**5（按简报要求）`tests/test_config.py` 无需改动**——它**没有**引用 `click_max_attempts`
（唯一的 `"prefetch": "3"` 是「配置段写成非映射」那条守卫用例，与本任务无关）。


## 疑虑

1. **计划简报的起点数字（311）与仓库实际（309）对不上。** 我按实际的 309 做的，
   最终 310。请确认这没影响别的任务的计数预期。
2. **`test_reads_once_when_screen_changed` 是护栏、不是变更探测器**（见偏离 1）。
   它守住「读到新界面后不再多读」，但它在本次改动前后都是绿的——
   因为**旧代码在「第一次就读到变化」时本来也只读一次**。真正的行为变更点是
   「一直不变」那条。这点容易在审查时被误读，特此说明。
3. **`click_retry_ms` 现在语义变了**（从「重试间隔」变成「两次读之间的间隔」），
   默认值仍 250ms，但**只在「第一次读到旧界面」时才用得上**。真机上的实际收益
   （最长拖尾从 16843ms 降到大约 `delay + 读屏 + retry + 读屏`）我没法在沙箱里量，
   要等下一次真机日志确认。
4. **`docs/原理与实现.md:284` 仍有「第 1 次 / 第 2 次 / 第 3 次读到新界面」的旧说法**，
   `README.md` 的配置表也可能要动。这些**不在本任务 Files 列表内**（应是任务 5 文档收尾的范围），
   我没有改，但提醒一句：它们现在和代码不一致了。
5. 本次 `git add -A` 把**编排者留在工作区、未提交的 `.superpowers/sdd/progress-r2.md`**
   （把任务 1 标为已完成、任务 2 标为进行中）一并提交了——因为简报明确要求 `git add -A`。
   该文件内容我一个字没改，任务 2 那一行仍是「进行中」，需要编排者后续更新。

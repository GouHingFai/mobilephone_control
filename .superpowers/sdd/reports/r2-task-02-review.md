# 任务 2 审查报告

**结论：通过**

（每次实验先清缓存；工作区已还原干净，310 全过。）

1. 上限正确、有测试钉住。①「第二次也收下」改回「仍一样就 return 不存」→
   `test_never_changes_still_stores_after_two_reads` 红（精确改法下仅此条红）；
   ②去掉「读到新界面」的 return → `test_reads_once_when_screen_changed` 红（2!=1），
   连带 `test_does_not_run_twice_concurrently` 红，与报告一致。

2. 非「永远两次」：常态路径有 return，被 `adb.calls==1` 钉住，实验②可证。

3. 收下旧屏的「过期坐标」窗口真实但小、属用户接受的取舍：翻页晚于两次读屏覆盖
   （≈delay+2×读屏≈5 秒）时两次都读旧屏→存旧屏→下次按键拿旧坐标而屏已翻。
   旧「放弃不存」更保守（下次必当场读），但那正是用户要消除的阻塞。建议不修，待真机日志。

4. 偏离判断均对。计划原夹具 `(FIRST_XML,SECOND_XML)`+`note(FIRST_XML)` 实测在新旧代码下
   都红（2!=1／超时），改用 `(SECOND_XML)` 正确。`test_logs_include_timing` 未改一字仍绿
   （给确认路径补了计时），不削弱护栏，取舍对。`test_reads_until_screen_changes` 由
   `>=3` 改 `==2` 是行为真变（4→2 即本任务），断言更严非放宽。简报 311 系笔误，实测
   `5c87f35` 为 309。

5. 删干净：代码/配置/测试无 `click_max_attempts` 残留；`click_retry_ms` 语义两处注释已写清。

**问题**：Minor——`docs/原理与实现.md`、`README.md` 仍写「第 1/2/3 次读到新界面」，
`test_prefetch.py:337` docstring 仍写「第几次」（仅文案），均超出本任务 Files，留任务 5。
流程——`996222e` 一并提交了编排者的 `progress-r2.md`。无 Critical/Important。

**未验证**：真机实际收益（拖尾降到 delay+2×读屏+retry）沙箱量不了。

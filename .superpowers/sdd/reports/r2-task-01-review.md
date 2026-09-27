# r2-task-01 审查报告（去动作时戳 + 修回归）

**结论：通过**

1. **删干净**：`ScreenPrefetcher.identity()`、`handle_numpad` 的 `stamp`、队列第三个元素皆已删。
   全仓搜 `stamp`/`identity` 只剩无关同名（日志文件名 `main.py:1068`、音频 `test_identity`、`probe.py` 时间戳）与解释性注释。
   删除理由留在 `tests/test_pipeline.py:848` 注释块与 `main.py:364`、`814`。✓

2. **一律生效**：把「按下屏 ≠ 执行屏就吞」临时加回 `main.py` 后，
   `test_press_still_clicks_after_the_screen_turned` **确实变红**（`0 != 1`）；还原后 309 全绿、工作区干净。✓

3. **回归堵住**：`make_action_putters` 返回四个回调（`main.py:385-390`），
   `main()` 内联入队 lambda 已删（`1304` 用 `putters["on_intent"]`）。
   把 `on_intent` 改回三元组 → `test_on_intent_puts_two_tuple` 与
   `..._really_runs_the_intent` **两条同时红**（一条抓格式、一条抓意图没被执行）。
   拿掉解包失败处的 `say()` → `test_undecomposable_action_warns` **变红**；
   `test_unknown_kind_is_ignored` 不动 —— 认不出的 kind 仍静默，没被这次修复带跑。✓

4. **同类问题**：全仓仅四处 `queue.put`，都在 `make_action_putters`；`dispatch_action` 五个分派分支
   —— 没有第二条「格式对不上就无声消失」的路。`handle_intent` 对未知名字静默 return，
   属既有设计且有 `test_unknown_intent_is_ignored` 钉住；GUI 发出的 7 个意图名与
   `ctx["intents"]` 的键逐一相符。✓

5. **测试清单**：`test_inventory.py:41-46` 基线 106→104，注明「删 5 补 3」的理由，`REQUIRED_CLASSES`
   已去掉 `TestActionStamp`。✓

**问题**：无 Critical / Important。
Minor：`voice_tap/ui_state.py:51` 的 `outcome` 注释仍以「已忽略：界面已翻页」为示例 ——
该出路已被删除、不再有任何代码产生它，建议把这半句删掉，免得将来误导。

**未验证**：未带 `--gui` 真机跑（沙箱无 tkinter，只读了源码）；未逐条复核日志「9 次里 7 次不同键」，
但已确认日志中恰有 9 条「已忽略」，且每次被吞后用户紧接着重按同一个键、随即成功。

# 任务 1 复评报告

**结论：通过** —— 上一轮那个 Important 覆盖缺口已真正关闭。

## 1. 缺口关掉了吗：关了，是真护栏

我亲手改坏接线实测（每次先清 `__pycache__`，避免旧字节码干扰）：

| 坏法 | 结果 |
|---|---|
| `on_option` 去戳（两元组） | 红 3 条（`..._puts_number_with_the_stamp`、`..._taken_at_press_not_at_execution`、`..._none_before_any_screen_read`） |
| `dispatch_action` 吞戳 | 红 `..._does_not_swallow_the_stamp` |
| `next`/`force_read` 分派写反 | 红 `..._next_clicks_the_next_button` |
| `on_next` 去戳 | 红 `..._next_puts_next_with_the_stamp` |
| `force_read` 加戳 | 红 `..._force_read_has_no_stamp` |
| 恢复 `else` 兜底 | 红 `..._unknown_kind_is_ignored` |

六种坏法 `TestActionWiring` 全变红、原 227 条不受影响。还原后 `git status` 干净、238 全过。**接线缺口已关，不是假护栏。**

## 2. 「未知 kind 忽略」的取舍：判为对

原 `else: handle_numpad(value,…)` 会把不认识的条目当成「点一下」；`("quit",None,None)` 这类更会让 `handle_numpad(None,…)` 直接抛 TypeError——违背「宁可不点、不可乱点」。忽略更安全，也为任务 5 加分支留余地。唯一代价：将来往 putters 加了新 kind 却漏了 elif，会**静默无操作**（不抛、不记日志）。建议在 return 前补一句 `say`，让漏接看得见；非必改。

## 3. main() 重构：无回归

`ctx["prefetcher"]`(864) → `putters`(917) → `hotkeys.start`(919) 顺序正确（回调随时可能触发，putters 必须先建好）；worker(895) 仅调 `dispatch_action`，外层 `AdbError`/兜底异常未动；`numpad_queue` 只剩「建 / 取 / 交给 putters」三处，旧内联 lambda 无残留。

## 4. 恒真用例：无

11 条逐条经上面 S1–S6 反证，均能因实现变坏而变红。

## 发现的问题

- **Minor** `tests/test_inventory.py:33`：`test_pipeline` 基线 54，实际 59 —— 漏计任务 1 加的 `TestActionStamp` 5 条（自 `0d09a85` 起就没纳入基线，本次未顺手补）。后果：删 ≤5 条不触发清单。建议改为 59。
- **提示（非代码缺陷）**：本仓库 `main.py` 与其 `.pyc` 常同秒，若被改坏的行字节数不变（如 S3 交换两行），`git checkout` 还原后 Python 会复用**旧字节码**，实验读到错版本。做破坏实验前务必清 `__pycache__` —— 我就踩到过，澄清后结论不变。

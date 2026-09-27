# 任务 3 审查：ui_state.py

**结论：有必须修的问题**（1 项 Important；模块实现本身正确，253 全绿）

**1 规格符合度：通过。** 与 brief Interfaces 逐条一致；确为纯新增（3f364f7 只含 2 个新文件 + 台账 progress.md，后者是全局约束 `git add -A` 带进来的），未改任何现有模块，未碰 .bat / .gitattributes。测试文件与简报逐字一致（脚本比对 True）。唯一多出的是第 4 条守卫。

**2 并发测试抓不住竞态【Important】。** 实验：把 `threading.Lock` 换成空 context manager（等价全体不加锁），跑 `tests/test_ui_state`，**40 次 + 120 次全绿，从未红**。原因：writer 只调 `record_input`/`set_screen`，而 `set_screen` 换的是整个对象引用（GIL 下原子），永远读到完整一屏；reader 取意图时队列为空、无竞争。故其断言（不卡死、快照完整）在没有锁时恒成立，**防不住它声称要防的东西**。我又写了高竞争探针（2 投递 + 8 消费、`setswitchinterval=1e-6/1e-7`、查重复投递），有锁 / 无锁均抓不到不一致 —— 此设计下这把锁的必要性几乎行为不可测。判定 Important 而非 Critical：模块实现正确、无功能缺陷；但**它比没有测试更危险**，因为名字与 docstring 承诺的正是本模块存在的理由，任务 8 还要把它钉进 `REQUIRED_CLASSES`，等于把「未验证」包装成「已验证」。建议：把 docstring / 名改成诚实的冒烟声明，或添一条真正由竞争驱动的断言。

**3 接口自洽：通过。** 与设计 §4.1 一致；任务 4/5/6 所需的 `set_screen`（publish_screen 用）、`current_screen`/`recent_inputs`（collect_state 用）、`post_intent`/`take_intents` 均在。两点注解：`InputEvent.kind`/`label` 设计里无默认，实现给了 `""`（超集，无害）；计划实际接线走的是 numpad_queue 动作队列，`post_intent`/`take_intents` 后续可能用不上 —— 非本次缺陷，提醒任务 5/7 留意。

**4 limit<=0 守卫：说法正确。** 实测 `items[-0:]==items[0:]`（返回全部而非空）。测试只传 limit=5/100，守卫不改变任何被测行为。

**5 恒真用例：无。** 实现者三处变异我全部复现：不反转→failures=2；current_screen 恒 None→1F1E；take_intents 不消费→1F。报告属实。`test_thread_safety` 非恒真（能抓「current_screen 返回 None」），但抓不住锁。

**未验证：** 无 GIL 的解释器（如 PyPy）下锁是否真必要；gui/main 的实际接线（属任务 4–7）。

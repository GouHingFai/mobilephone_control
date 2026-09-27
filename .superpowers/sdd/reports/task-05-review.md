# 任务 5 审查：统一动作队列 + 唤醒监听

**结论：通过**（1 处唤醒时序缺陷，建议随任务 7 修，非本任务必须现在修）

**1. 7 条是真护栏**：抽查 11 个变异（每次全量 267）—— 语音短路/once/None/空串/ptt 实参/on_speech_start/hint_snapshot 删掉均恰好变红，非摆设。但步骤 6 的 `stop_event=stop`、`wake_event.clear()` 删掉仍 267 全绿：那个有意行为改变零覆盖。

**2. AdbError 不必现在修**：实测单删任一层 except 都 267 全绿（报告只查到内层），同删才红；loop 层还不可达（下游 adb 被 clicker 自吞或在吞异常线程里），单钉它是测桩。改措辞即可（Minor）。

**3. 行为改变：取舍对**（计划 24-25 行已列为唯一例外）。副作用：ESC 按在说话中途会返回半句、仍识别甚至点下再退（audio_io.py:411）。非回归，记录即可。

**4. `_AnyEvent` 可靠**（audio_io.py:394 是唯一消费点，只调 is_set()）。但 clear() 位置有缺陷：它在 wait_until_open 之后，唤醒若落在点击后静音期(≈2.5s)内会被丢弃，随后带旧 mode 阻塞（实测入口 is_set()=False）。不空转。建议挪到 while 体顶部；wake 未接线，暂不可达。

**5. 非 --gui 无回归**（putters 仍只产 numpad/next/force_read）。但 dispatch_action 的 intent/quit 分支零覆盖（删 wake、quit 改 pass 都全绿）。

**问题**：Important(潜伏) main.py:590-593 clear 位置；Minor 步骤 6 两行无测试、1227 行 docstring 夸大、test_inventory 未登记 TestRunVoiceLoopBranches（删整类不掉基线）、intents 表无测试。

**没验证**：真线程/真音频端到端（仅桩+推演）；GUI 未接；按住说话的唤醒（仅读码）。

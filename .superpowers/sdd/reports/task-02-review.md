# 任务 2 复评（语音「下一题」）

## 结论：通过

**① 规格**：brief 步骤 1–7 逐条对上，新增 8 用例（matcher 2 / config 3 / pipeline 3），
238→246 与预期一致，无超范围改动。`detect_control` 用无注解签名是照步骤 3 片段
（Interfaces 的 `-> str | None` 在 3.9 确实会报错）。提交里混入的 3 个编排文件系
`git add -A` 带入，报告已披露、内容为任务 5 指令同步，非实现者所改。

**② 护栏（做了实验）**：摘掉 `handle_speech` 控制语分支 → 端到端 3 条红 2 条；
再去掉 `next_command` 判断 → 第 3 条红。`detect_control` 改成反向包含、改成恒真 →
`TestDetectControl` 2 条都红，无恒真用例。实验后已还原，工作区干净，246 全过。

**③ 三个疑点**
- 「包含」：风险真实但小，**不改** —— 设计 §2.2 原文即「识别出的文字里**包含**控制语」，
  改成整句相等会打红 brief 自己的「说下一题」「下一题吧」。223 条真机 `[听到]` 无一条误吞，
  抽样的真机选项里没有「继续/next」。记 Minor。
- 无注解的理由属实：只有 `config.py`/`screen.py` 有 future import，注释即为此；
  `parse_ordinal` 同样无注解，风格一致。
- 属实：实测 `next_command=False` 时详情页与答题页都 `taps=[]`（会读屏但不点），落回原流程。

**④ 回归**：`dispatch_action` 仍传默认「小键盘 0」，`key=("next",)` 未动，`TestNextButton` 全过。

**问题**（均 Minor，无 Critical/Important）
- 「下一首/下一组/下一关」无用例覆盖（brief 未要求，报告已披露）。
- 两个新类未登记进 `test_inventory.REQUIRED_CLASSES`；计划里属任务 8，判断正确。
- 语音翻页时 `on_speech_start` 的预读已先跑一次，「不读屏」仅指前台不阻塞。

**未验证**：真机误说「下一题」的实际后果（直给无护栏）只做了离线推演；任务 3+ 不在本次范围。

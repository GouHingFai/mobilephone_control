# 进度台账

计划：docs/superpowers/plans/2026-09-27-gui-and-voice-controls.md
起点 222 → t1 238 → t2 246 → t3 253 → t4 254 → t5 **268 全绿**

| # | 任务 | 状态 | 提交 | 备注 |
|---|---|---|---|---|
| 1 | 动作时戳（修连按 bug） | **完成** | 0d09a85 / 3ba4c8c / 0095616 / 4d9c41b | 审查+复评通过 |
| 2 | 语音说「下一题」 | **完成** | 88e0772 / bca9b02 / 3607617 | 审查通过（全 Minor） |
| 3 | ui_state.py 状态黑板 | **完成** | 3f364f7 / 1aa5879 | 并发用例是假护栏 → 已改诚实 |
| 4 | 抽出 run_voice_loop（纯重构） | **完成** | b9651aa / 334854a | 逐行 diff 实证只有 args.once→once |
| 5 | 统一动作队列 + 唤醒监听 | **完成** | 039b680 / b05d64c / 53b45b8 / ed535bd | 审查揪出 clear() 位置错致唤醒丢失，已修并留回归测试 |
| 6 | collect_state + 结果回报 | 进行中 | — | 期望 +7 |
| 7 | gui.py 与 run_gui.bat | 待办 | — | 期望 +0；需用户人工冒烟 |
| 8 | README 与测试清单 | 待办 | — | 基线数字 + REQUIRED_CLASSES |

## 审查反复揭示的同一件事（很重要）

**四轮审查各自抓出过一次「测试看着像护栏、其实抓不住东西」**：
- t1：接线（盖戳→入队→解包）零覆盖 → 已补 TestActionWiring
- t3：并发用例拿掉锁仍全绿 → 已改成诚实的冒烟测试
- t4：主循环用例删空循环体仍绿 → t5 步骤 0 补了驱动测试（7 条，逐条验证能红）
- t5：`wake_event.clear()` 位置错致唤醒丢失（潜伏）→ 已修 + 回归测试

**结论**：这个项目里「测试全绿」≠「这段行为被验证过」。
每写一条声称守住某行为的测试，都要问一遍：**把它守的那段代码改坏，它会红吗？**

## 跨任务提醒

- 动作分派唯一入口 `dispatch_action(action, ctx)`。
- 跑测试前清 `__pycache__`；做「改坏看红不红」实验时尤其必须。
- 任务 8：基线数字按实际读出的写（现 test_pipeline 实际 77 vs 基线 59，偏低）；
  REQUIRED_CLASSES 已有 TestActionStamp/Wiring、TestRunVoiceLoopBranches/HandleIntent/ToggleFlag/AnyEvent，
  还需补 TestDetectControl、TestVoiceNextCommand、TestCollectState 等。

## 已知残留（设计文档 §6 明说、用户接受）

小键盘 `0` 与语音「下一题」走固定坐标、不读屏，连按两下仍会点两次；`handle_next` 不参与时戳核对。
另有审查记录的一处低概率副作用：按 ESC 时若正在说话，那半句仍会被识别并可能点击（然后退出）。

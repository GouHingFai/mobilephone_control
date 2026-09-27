# 进度台账

计划：docs/superpowers/plans/2026-09-27-gui-and-voice-controls.md
起点 222 → t1 238 → t2 246 → t3 253 → t4 254 → t5 268 → t6 **288 全绿**

| # | 任务 | 状态 | 提交 | 备注 |
|---|---|---|---|---|
| 1 | 动作时戳（修连按 bug） | **完成** | 0d09a85 / 3ba4c8c / 0095616 / 4d9c41b | 审查+复评通过 |
| 2 | 语音说「下一题」 | **完成** | 88e0772 / bca9b02 / 3607617 | 审查通过 |
| 3 | ui_state.py 状态黑板 | **完成** | 3f364f7 / 1aa5879 | 并发用例原为假护栏 → 已改诚实 |
| 4 | 抽出 run_voice_loop（纯重构） | **完成** | b9651aa / 334854a | 逐行 diff 实证行为不变 |
| 5 | 统一动作队列 + 唤醒监听 | **完成** | 039b680 / b05d64c / 53b45b8 / ed535bd | clear() 位置错致唤醒丢失 → 已修 |
| 6 | collect_state + 结果回报 | **完成** | d09b5b1 / 03c59b3 / 9bcf47d / 26be586 | 接线零覆盖 → 补 13 条接线测试，全部验证能红 |
| 7 | gui.py 与 run_gui.bat | 进行中 | — | 期望 +0；**沙箱验不了，需用户人工冒烟** |
| 8 | README 与测试清单 | 待办 | — | 见下面的待办清单 |

## 任务 8 的待办（一并收）

1. `tests/test_inventory.py` 基线数字按**实际读出的**写（现在 test_pipeline 实际 101 vs 基线 59，偏低）。
2. `REQUIRED_CLASSES` 补齐：TestDetectControl、TestVoiceNextCommand、TestCollectState、
   TestUiStateWiring、TestUiWiringWithoutUi、`tests.test_ui_state` 的 TestIntents。
3. **补一条测试覆盖 `_input_kind_and_label` 的 `next` 分支**（审查实测：把它改成 speech，288 条仍全绿）。
4. README：加界面用法 + `--gui` + 文件清单（run_gui.bat / ui_state.py / gui.py）+ 测试数字；
   并把「已经能说下一题」那句改成点明它走固定坐标。

## 审查反复揭示的同一件事（很重要）

**五轮审查各自抓出过一次「测试看着像护栏、其实抓不住东西」**：
t1 接线零覆盖 / t3 并发用例拿掉锁仍绿 / t4 主循环用例删空循环体仍绿 /
t5 clear() 位置错致唤醒丢失 / t6 接线零覆盖 + next 分支零覆盖。

**结论**：这个项目里「测试全绿」≠「这段行为被验证过」。
每写一条声称守住某行为的测试，都要问：**把它守的那段代码改坏，它会红吗？**

## 已知残留（设计文档 §6 明说、用户接受）

小键盘 `0` 与语音「下一题」走固定坐标、不读屏，连按两下仍会点两次；`handle_next` 不参与时戳核对。
按 ESC 时若正在说话，那半句仍会被识别并可能点击（然后退出）。

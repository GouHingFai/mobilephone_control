# 进度台账

计划：docs/superpowers/plans/2026-09-27-gui-and-voice-controls.md
起点 222 → 任务1 后 238 → 任务2 后 246 → 任务3 后 **253 全绿**

| # | 任务 | 状态 | 提交 | 备注 |
|---|---|---|---|---|
| 1 | 动作时戳（修连按 bug） | **完成** | 0d09a85 / 3ba4c8c / 0095616 / 4d9c41b | 审查+复评通过 |
| 2 | 语音说「下一题」 | **完成** | 88e0772 / bca9b02 / 3607617 | 审查通过（全 Minor） |
| 3 | ui_state.py 状态黑板 | **完成** | 3f364f7 / 1aa5879 | 审查揪出「并发测试是假护栏」，已改成诚实冒烟测试 |
| 4 | 抽出 run_voice_loop（纯重构） | 进行中 | — | 期望 +1；行为不许变 |
| 5 | 统一动作队列 + 唤醒监听 | 待办 | — | 期望 +6 |
| 6 | collect_state + 结果回报 | 待办 | — | 期望 +7 |
| 7 | gui.py 与 run_gui.bat | 待办 | — | 期望 +0；需用户人工冒烟 |
| 8 | README 与测试清单 | 待办 | — | 补 REQUIRED_CLASSES |

## 跨任务提醒

- **动作分派唯一入口 `dispatch_action(action, ctx)`**（模块级）。任务 5 加 `"intent"`/`"quit"`
  分支时改它，不要动 `numpad_worker` 循环体。
- `matcher.py` 没有 `from __future__ import annotations`，**别**在那儿写 `X | None` 注解。
- **跑测试前清 `__pycache__`**；做「改坏看红不红」实验时尤其必须。
- **`UiState` 的线程安全没有测试能证明**（`test_concurrent_access_does_not_crash` 只是冒烟，
  抓不住锁）。安全性依据是类 docstring 里那三条不变量，改这一层必须逐条对照。
- 任务 8 需补 `REQUIRED_CLASSES`：TestActionStamp/TestActionWiring/TestDetectControl/
  TestVoiceNextCommand/TestRunVoiceLoop/TestHandleIntent/TestCollectState，并新增
  `tests.test_ui_state` 的 TestIntents；基线数字按实际读出的数写。

## 已知残留（设计文档 §6 明说、用户接受）

小键盘 `0` 与语音「下一题」走固定坐标、不读屏，连按两下仍会点两次；`handle_next` 不参与时戳核对。

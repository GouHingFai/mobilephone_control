# 任务 6 审查（collect_state + 结果回报，含补漏）

## 结论：通过

## 五条核查

**1 规格符合度**：逐行确认 `collect_state` 纯读（只读 voice_gate/hotkeys/mode/cfg 与 UiState，无任何写或缓存）；ui 缺失时它回 `screen=None`/`inputs=[]`，`publish_screen`/`note_input` 早退。三点均成立，且各有用例钉住。

**2 那 13 条接线测试是真护栏**：我独立做了 10 个「改坏→清缓存→跑全套→还原」实验，结果与补漏报告**逐条吻合**：E1a/E1b/E2a/E2b/E3/E5 各**恰好红 1 条**且正是对应那条；E4 红 3、E6 红 2、E7 红 49、E8 红 50。13 条里**没有一条**是「删掉接线仍然绿」的摆设。还原后 288 全绿、`git status` 干净、`main.py` 与 HEAD 一致。

**3 outcome 修复正确**：开头留空、未匹配分支补记，逻辑自洽，不再有「见下」悬空。`AdbError` 与「屏幕不可用」两个早退分支只留一条空 outcome 记录 —— **该取舍可接受**（空 outcome 只显示「听到了什么」，不误导，仅比补一句「屏幕不可用」少点交代）。

**4 无 --gui 行为不变**：`ctx["ui"]` 在 `main.py` 里只出现在这三个函数的 `ctx.get("ui")`，生产路径不设 ui。E7/E8 证明空操作守卫是承重的（去掉即大面积红）。

**5 `_input_kind_and_label` 推导正确**：三条路径实传 numpad=`("numpad", index)`、next=`("next",)`、speech=`None`，映射无误。

## 发现的问题

- **Minor**｜`voice_tap/main.py:586`（`_input_kind_and_label`）：「next」分支**零覆盖** —— 实测把它改错（→speech）后 288 仍全绿（我做的 F1 实验）。numpad 分支有 `test_numpad_click_leaves_an_input_record` 守，speech 分支无断言。建议补一条：跑一次 `handle_next`，断言 inputs 里 `kind=="next"`。非阻塞。
- **Minor**｜读屏失败／屏幕不可用早退不留结果（见第 3 条）。记录即可。

## 未验证

- 真机与 tkinter 集成（`gui.py` 尚未存在）、多线程下界面表现；preview 模式下界面第三块仍为空（报告已记录，属显示层）。
- diff 范围 `b05d64c..HEAD` 还含任务 5 的修复（`53b45b8`），本次只审了任务 6 的两批。

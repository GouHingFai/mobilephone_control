# 任务 7 审查报告（d0dda15+aaff841、ca6ec0c+8d688e3）

## 结论：有必须修的问题（1 处，1 行可修；其余 5 项通过）

## 核查结论

1. **gui.py 薄 ✓**：不 import ctx/config/queue/main，自身不存状态，只收注入的回调；
   新增仅 `_tick` 里 3 行 `should_close` 轮询（允许的那一小段）。`_render_*` 是展示映射
   （简报原文）。唯一旁枝：这些映射函数因模块顶层 import tkinter 而测不到，但那是简报的设计。
2. **退出 ✓**：三路（ESC／「退出」／窗口 X）都汇到 `close()` → `on_closed(几何)` + `destroy()`；
   `_tick` 关窗后 `return`、**不再排 `after`**，所以无重复 destroy、无销毁后刷新；ESC 也存位置。
   轮询是 `is_set()`、按 refresh_ms 节拍，非忙等。
3. **GuiConfig 键级解析 ✓**：临时坏 yaml 实测 —— window 非 4 个／非整数／字符串／null、
   enabled/topmost/refresh_ms 坏值，**一律退默认 + notice**。
4. **不带 --gui ✓**：从前 `ctx` 根本没有 `"ui"` 键（`.get`→None），现显式 None，等价；
   `--dump` 两行 notice 仅在 gui 时打；`--gui` 分支在 `--dump/--calibrate` 早退**之后**，老路未动、不多读屏。
5. **run_gui.bat ✓**：纯 ASCII + CRLF（实测字节 `...\r\ncall "%~dp0run.bat" --gui %*\r\n`），
   `git ls-files --eol` 与另三个 .bat 一致；`%~dp0` 绝对路径、run.bat 自 cd，`%*` 透传正常。
6. **测试 ✓ 真护栏**：删掉 `_load_window_geometry` 读文件那几段 → 5 中**红 2**（往返、父目录），
   还原后工作区干净、**293 全过**。

## 问题

- **Important｜`voice_tap/config.py:400-403`**：`gui:` 整段写成**非映射**（`gui: 3` / `gui: true` /
  `gui: [1,2]`）时 `gt.get("window")` 抛 `AttributeError`，`load_config` 崩，**连不带 `--gui` 也起不来** —— 撞「绝不能把程序拦在门外」。
  注：`hotkey: 3` 有一模一样的**既有**毛病，实现者是照惯例抄的。建议 `gt = data.get("gui")`
  后加一句 `if not isinstance(gt, dict): gt = {}`。
- **Minor｜`config.py:255-272`**：缺 `window` 键被当成坏值，凡 config.yaml 无 `gui:` 段就多一条**假** notice
  「gui.window 不是四个数（None）」；`_pick` / `_to_position` 不这样。
- **Minor｜`config.py:405`**：`refresh_ms` 无下限校验，`0`/负值 → `after(0)` 忙循环。
- **Minor｜测试**：`gui.*` 解析**零覆盖**（计划步骤 0 明说要加、任务 8 未排）；
  `TestWindowGeometry` 未进 `REQUIRED_CLASSES`，且 `test_pipeline` 基线 59 远低于现值（102），
  **整类删掉不会触发清单**。
- **Minor（待真窗）｜`gui.py:80-93`**：五个 `width=15` 按钮横排，360px 宽的窗口很可能被裁到屏幕外；
  冒烟时请确认五个开关都点得到。

## 没验证到的部分

真窗口／真机一次都没跑：Tk 实渲染、`after` 回调里**同步 destroy** 是否报 `invalid command name`、
ESC 关窗时延（≤refresh_ms）、几何恢复、中文与字体布局。另：`--gui` 下 `tk.Tk()` **自身**失败
（非 import 失败）未被兜住，会直接崩 —— 现有 fallback 只盖 import 异常。

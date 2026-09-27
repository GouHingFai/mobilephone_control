# 任务 3 修复报告：把并发测试改成诚实的冒烟测试

## 状态：DONE

253 个用例全过（`Ran 253 tests ... OK`），用例总数与修复前一致，未增删任何断言。

## 改了什么

只改了两处「名字与注释」，无任何行为改动。

### 1. `tests/test_ui_state.py` —— 让那条测试说实话
- 方法名 `test_thread_safety` → `test_concurrent_access_does_not_crash`。
- docstring 重写，如实分清「能挡住」与「抓不住」：
  - 能挡住（明显回归）：读到半截、死锁（join 超时）、`current_screen` 恒返回 None 这类接线错；
  - 抓不住（竞态）：本模块的安全性来自「一把锁 + 整体换引用」，而 `set_screen` 换的是对象引用，
    CPython 下换引用本就原子 —— **把 `ui_state.py` 的锁整个拿掉，这条测试照样全绿**
    （审查者实测 160 次无反例：40 + 120）；
  - 明确写下：**别把它的绿色当成「并发正确性已验证」**。
- `threading.Event().wait(0.3)` → `time.sleep(0.3)`；文件顶部补 `import time`
  （原来只 import 了 `threading`，`threading` 仍被线程构造使用，没删）。

### 2. `voice_tap/ui_state.py` —— 把真正的不变量落到代码里
`UiState` 类原本没有 docstring，补上一段，把安全性依据从「某条测试的名字」搬回代码：
- **一把锁保护全部字段**：`_screen` / `_inputs` / `_intents` 共用 `self._lock`，无路径绕过；
- **写入是整体换引用**：`set_screen` 换掉整个 `ScreenView`，界面读到的永远是完整一份，不会「新 prompt 配旧 options」；`take_intents` 同理整体取走再整体换新 list；
- **调用方的约定**：`ScreenView` 及其 `options` 是裸对象，构造后不许再改，要更新就新建再 `set_screen` —— 违反则第 2 条保证失效（类型系统管不住共享可变）；
- 末尾指向那条冒烟测试的 docstring，避免以后有人误读。

### 未改（刻意）
- 没动 `tests/test_inventory.py`：grep 确认仓库里对 `test_thread_safety` 的引用只存在于 `tests/test_ui_state.py` 自身（以及 `.superpowers/` 下的简报/报告等非代码文本）。inventory 是按**类名**检查的，且 `test_ui_state` 根本不在 `BASELINE_COUNTS` / `REQUIRED_CLASSES` 里，所以无需改动。
- 没有任何断言被修改、新增或删除；用例总数仍是 253。
- 没碰 `.gitattributes` / `core.autocrlf` / `.bat` / 其他模块。
- 按指示没有为了「更像在测并发」加探针。

## 测试结果

```
$ rm -rf tests/__pycache__ voice_tap/__pycache__
$ python3 -m unittest discover -s tests 2>&1 | tail -3

Ran 253 tests in 10.655s

OK
```

沙箱已有 `pypinyin`，无需安装。无 pytest（按约定用 unittest）。

## 提交

- 哈希：`1aa58796d1a726791d282fdf704ab6e00748f309`
- 信息：`test: 把并发测试改成诚实的冒烟测试（审查发现它抓不住锁）`

## 疑虑

1. **`git add -A` 顺带提交了别的既有改动**。按简报原样执行 `git add -A && git commit`，因此这次提交除我改的 2 个文件外，还带进了当时工作区里已存在、由前序任务留下未提交的内容：
   - `.superpowers/sdd/reports/task-03.md`（新增，前序实现者写的报告）
   - `.superpowers/sdd/reports/task-03-review.md`（新增，审查报告）
   - `.superpowers/sdd/plans/2026-09-27-gui-and-voice-controls.md`（+19/-6 的修改，非本次任务所改）

   共 5 文件、226 插入 / 6 删除。简报明确要求用 `git add -A`，且审查报告里也提到『台账 progress.md 是全局约束 `git add -A` 带进来的』，故判断这是本仓库既有约定、非失误；但**把前序任务未提交的计划改动一并封装进了这条提交**，如需保持提交主题单一，可能要拆。

2. **这条修复只是「诚实」，不是「更严」**。审查已证实：本设计在这一层构造不出稳定竞态，故改后仍无用例真正验证那把锁。锁的必要性要等更高层（任务 4–7 的 gui/main 实际接线）或非 GIL 解释器下才可能被测到 —— 与审查报告的『未验证』一致。

3. 该测试仍在 `tests/test_ui_state.py`，而 `test_ui_state` 模块未列入 `test_inventory.py` 的基线；若后续任务要把它钉进 `REQUIRED_CLASSES`，请注意钉的是**类名**（`TestScreen` / `TestInputs` / `TestIntents`），不是这条方法名。

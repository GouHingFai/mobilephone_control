# 任务简报：去掉动作时戳（按键一律生效）


## 环境提示

- 项目根目录：bash 是 `/sessions/pensive-confident-cerf/mnt/声控手机项目`；文件工具是 `H:\声控手机项目\...`。
- **跑测试前先清字节码缓存**：`rm -rf tests/__pycache__ voice_tap/__pycache__`
  （本仓库 `.py` 与 `.pyc` 常同秒落盘，改动若不改变文件字节数，Python 会复用旧字节码 ——
  做「改坏看红不红」的实验时尤其必须，否则会得出错的结论。）
- 跑测试：`python3 -m unittest discover -s tests`（**没有 pytest**；沙箱缺 `pypinyin` 就先
  `pip install pypinyin --break-system-packages`）。
- **不要 `import tkinter`**（沙箱多半没装）；`gui.py` 用 `compile()` 查语法就行。
- **不要**碰 `.gitattributes` / `core.autocrlf` / `.bat` 文件。

## 一句话背景

`voice_tap`：Windows 上的声控工具，用户用 scrcpy 投屏安卓手机玩 GRE3000 背单词，
开口说选项、或按小键盘数字，程序读屏后自动点对应选项。**代码与注释全中文，
你写的注释、测试、提交信息也用中文。**

**这一轮的依据是真机日志** `debug/run_20260927_234859.log`（737 行），
计划里每条改动都引用了日志里的具体现象 —— **别凭感觉改**。


## 关键约束

## Global Constraints

- **测试命令**：`python3 -m unittest discover -s tests`（**没有 pytest**）。
- **跑测试前先清字节码缓存**：`rm -rf tests/__pycache__ voice_tap/__pycache__`。本仓库 `.py` 与 `.pyc` 常同秒落盘，改动若不改变文件字节数，Python 会复用旧字节码 —— 做「改坏看红不红」这类实验时会读出错误结论。
- 沙箱缺 `pypinyin` 就先 `pip install pypinyin --break-system-packages`。
- **不要 `import tkinter`**（沙箱多半没装）；`gui.py` 用 `compile()` 查语法。
- **不带 `--gui` 时行为除本计划明说的改动外不能变。**
- 不要碰 `.gitattributes` / `core.autocrlf` / `.bat`。
- **每写一条声称守住某行为的测试，先把它守的那段代码改坏一次，确认它真的会红。** 本项目的审查已经抓到过 6 次「测试看着像护栏、其实抓不住东西」，这是硬要求。
- 提交信息用中文。改测试基线数字时**必须在该文件里注明理由**（`test_inventory.py` 自己就是这么要求的）。
- 起始基线：**311 个测试全绿**（提交 `5dbe5f8` 之后）。

---

## 任务 1：去掉「动作时戳」—— 按键一律生效

**依据（日志实证，见 `run_20260927_234859.log`）**：这条时戳是 2026-09-27 为修「连按两下同一个键点到新题上」加的，
但它**误伤了 9 次正常按键**。日志里 9 次「已忽略」中有 7 次用户按的是**不同的键**（点第 4 个之后按 1），
也就是在答下一题 —— 完全正当。根因：时戳取的是「**程序最近见过的那一屏**」，
而那一刻程序自己已经落后（缓存作废、预读刚放弃），它手里的旧屏 ≠ 用户眼前的屏。
**它比的不是「屏幕变了没有」，而是「程序自己有没有跟上」。** 设计错误，用户已决定去掉。

**Files**
- Modify: `voice_tap/main.py`
- Test: `tests/test_pipeline.py`、`tests/test_inventory.py`

**Interfaces**
- `handle_numpad(number, ctx)` —— 去掉 `stamp` 参数
- `make_action_putters(queue, prefetcher)` → 三个回调，入队格式改为 **二元组**：`("numpad", n)` / `("next", None)` / `("force_read", None)`
- `dispatch_action(action, ctx)` —— 解包二元组
- 删除 `ScreenPrefetcher.identity()`

- [ ] **步骤 1：先删掉会失败的测试，并留下理由**

`tests/test_pipeline.py` 里的 `TestActionStamp` 整类删掉（5 个用例）。**在删除的位置留一段注释**：

```python
# 这里曾经有一个 TestActionStamp（动作时戳）—— 2026-09-28 整类删除。
#
# 它守的是「按键之后界面翻了页，这一下就别点了」。但真机日志
# （debug/run_20260927_234859.log）显示它误伤严重：9 次「已忽略」里 7 次
# 用户按的是**不同的键**，是在答下一题。根因是时戳取「程序最近见过的那一屏」，
# 而那一刻程序自己已经落后，旧屏 ≠ 用户眼前的屏 ——
# 它比的不是「屏幕变了没有」，而是「程序自己有没有跟上」。
#
# 用户明确要求：按键一律生效，不要吞。（他自评「误触概率很小」。）
# 若将来「连按两下同一个键点到新题」真的复现，再考虑加「只挡同一个键的短时重复」那道轻拦。
```

`tests/test_inventory.py`：`BASELINE_COUNTS["tests.test_pipeline"]` 减去 5，
**并在数字旁注明理由**（照抄下面这行）：

```python
    # 2026-09-28：删掉 TestActionStamp 的 5 个用例 —— 动作时戳按用户要求取消，
    # 理由见 tests/test_pipeline.py 里那段注释。
    "tests.test_pipeline": 98,
```

（`98` 这个数按你实际读出来的写，别照抄。）

`REQUIRED_CLASSES["tests.test_pipeline"]` 里去掉 `"TestActionStamp"`。

- [ ] **步骤 2：跑测试，确认只有基线相关的失败**

```
python3 -m unittest discover -s tests 2>&1 | tail -5
```

此时 `TestActionWiring` 应该还是绿的（它测的是接线，不是时戳）。若有别的红，先弄清原因。

- [ ] **步骤 3：改 `voice_tap/main.py`**

1. `ScreenPrefetcher.identity()` 整个方法删掉。
2. `handle_numpad` 签名改回 `def handle_numpad(number, ctx):`，删掉函数体里那段
   `if stamp is not None and ScreenPrefetcher.signature(snap) != stamp:` 的核对块，
   并把 docstring 里讲 `stamp` 的那几句删掉、补一句「2026-09-28 取消时戳，理由见 tests 里的注释」。
3. `make_action_putters` 里三个回调入队改成二元组（`on_force_read` 也不再需要第三个元素）。
4. `dispatch_action` 解包改成 `kind, value = action`，分派逻辑不变。

- [ ] **步骤 4：`TestActionWiring` 跟着改**

它现在的用例断言三元组（带戳）。改成二元组，并**去掉所有跟戳有关的断言**。
**然后做「改坏看红不红」**：把 `on_option` 的入队改成 `("numpad", n, "花")`（三元组），
确认有对应用例变红，再改回来。

- [ ] **步骤 5：跑全套**

期望：比开跑前**少 5 个**（删了 `TestActionStamp` 的 5 条），其余全绿。

---

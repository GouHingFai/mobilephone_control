# 任务 2 报告：语音说「下一题」（直给：说了就点）

## 状态

**DONE**

全套 **246** 个用例通过（开跑前 238 + 新增 8），与简报期望的「多 8 个」一致。
新增的 8 个用例（matcher 2 + config 3 + pipeline 3）全部先确认过失败/无效，
再写实现跑通。

## 做了什么

按简报的 7 个步骤逐条实现，改动如下（不含 `git add -A` 顺带提交的既有改动，
见「偏离计划」）。

### `voice_tap/matcher.py`（+27 行）

在 `parse_ordinal()` 之后、`Candidate` 定义之前新增：
- `NEXT_PHRASES` 元组，与简报逐字一致（含 `"下一首" "下一组" "下一关"` 这三个
  简报测试未覆盖但接口里列出的词）。
- `detect_control(text)`：先 `normalize()`，空串返回 `None`；
  再逐个 phrase 做 `normalize(phrase) in key` 的**包含**判定，命中返回 `"next"`。
  即「说下一题」「下一题吧」这类带零碎字词的说法也能命中。

> 注：`matcher.py` 没有 `from __future__ import annotations`，因此按简报
> 步骤 3 的代码片段写成了无类型注解的 `def detect_control(text):`，
> 没有采用 Interfaces 小节里 `-> str | None` 的写法（那个写法在 3.9 上会报错）。
> 简报片段与 Interfaces 描述本身不一致，我以片段为准。

### `voice_tap/config.py`（+7 行）

- `VoiceConfig` 新增 `next_command: bool = True`，注释写明这是「直给」取舍。
- `load_config()` 里 `VoiceConfig(...)` 构造加一行
  `next_command=_pick(v, "next_command", VoiceConfig.next_command, _to_bool, n, "voice")`。

### `config.yaml`（+6 行）

`voice:` 段末尾（`enabled: true` 之后、`click:` 段之前）新增
`next_command: true` 及说明注释。行尾仍是 LF，`yaml.safe_load` 解析正常。

### `voice_tap/main.py`（+10 / -1 行）

- `handle_next` 签名由 `def handle_next(ctx):` 改为
  `def handle_next(ctx, source="小键盘 0"):`，函数体首行
  `say("[小键盘] 0 → 下一题")` 改为 `say(f"[{source}] 下一题")`。
- `handle_speech` 里，在置信度提示之后、`try: snap, source = grab_screen(ctx)`
  之前插入控制语优先分支：
  ```python
  if ctx["cfg"].voice.next_command and matcher.detect_control(text) == "next":
      handle_next(ctx, source="语音")
      return
  ```
  放在取屏之前是有意的：走固定坐标时根本不读屏。

### `tests/test_matcher.py`（+18 行）

末尾新增 `TestDetectControl`（2 个用例），与简报逐字一致。

### `tests/test_config.py`（+14 行）

末尾新增 `TestVoiceNextCommand`（3 个用例），与简报逐字一致。

### `tests/test_pipeline.py`（+33 行）

末尾新增 `TestVoiceNextCommand`（3 个用例），与简报逐字一致。

## 测试结果

### 起点是绿的

```
$ rm -rf tests/__pycache__ voice_tap/__pycache__
$ python3 -m unittest discover -s tests 2>&1 | tail -3
Ran 238 tests in 9.726s
OK
```

（沙箱已装 `pypinyin`，3 个拼音用例正常通过，不是环境性失败。）

### 失败的测试确实失败 —— 证据 1：matcher（写实现之前）

```
$ python3 -m unittest tests.test_matcher.TestDetectControl -v
...
AttributeError: module 'voice_tap.matcher' has no attribute 'detect_control'
...
Ran 2 tests in 0.004s
FAILED (errors=12)
```

失败原因是 `detect_control` 尚不存在（`errors=12` 是 2 个用例里 5+7=12 个
`subTest` 各自抛错），正是简报预期的原因，不是语法错、不是 import 错。
写完实现后该模块 2 个用例全过。

### 失败的测试确实失败 —— 证据 2：pipeline 接线（做「故意改坏」实验）

pipeline 的 3 个用例是在实现写完之后补的，为了确认它们**不是空转**，
我把 `handle_speech` 里那段接线临时摘掉，再跑一次（摘掉后已用备份原样恢复）：

```
$ python3 -m unittest tests.test_pipeline.TestVoiceNextCommand -v
...
Second list contains 1 additional elements.
First extra element 0:
(909, 2476)

- []
+ [(909, 2476)]

Ran 3 tests in 0.146s
FAILED (failures=2)
```

`test_saying_next_clicks_the_button` 与 `test_works_on_quiz_page_too` 如期变红
（期望 `[(909, 2476)]`，实际 `[]`）。第 3 个 `test_disabled_by_config` 断言的就是
「不点」，所以摘掉接线它照样过 —— 这条是**护栏**而非该特性的正向验证，
这一点简报的用例设计本身如此，符合预期。

### 最终结果

```
$ rm -rf tests/__pycache__ voice_tap/__pycache__
$ python3 -m unittest discover -s tests 2>&1 | tail -3
Ran 246 tests in 10.314s
OK
```

238 → 246，**多 8 个**，与简报期望一致。
（简报 Global Constraints 里写的「基线 222」是任务 1 之前的旧数，已过时；
简报也明确要求用「比开跑前多 N 个」来核对，我就是这么核的。）

### 人工过一遍三条路径的日志

```
--- 语音说「下一题」（详情页）---
[听到] '下一题'   置信度 -0.40
[语音] 下一题
       [固定位置] 用配置坐标 (909, 2476)，耗时 0 毫秒（未做界面校验）
[匹配] 「下一题」（固定位置） → 点击坐标 (909, 2476)
[点击] 完成
点击: [(909, 2476)]  读屏次数: 0        ← 确实没读屏

--- 小键盘 0（默认 source）---
[小键盘 0] 下一题                        ← 老路径文案没变
...

--- 关掉开关后说「下一题」---
[听到] '下一题'   置信度 -0.40
       [注意] 没有可用的预读结果（还没有预读结果），当场读了一次（0 毫秒）
[屏幕] 当前是答题后的详情页（没有选项），可以点「下一题」继续
...
点击: []                                 ← 落回普通流程，不点
```

## 提交哈希

```
88e0772 feat: 语音说「下一题」（直给：说了就点）      ← 功能改动（本任务的主体）
```

本报告自身的提交紧随其后、提交信息为 `docs: 任务 2 报告（语音「下一题」）`
（它无法在自己的正文里写出自己的哈希 —— 哈希会因此再变一次。
查它的办法：`git log --oneline -- .superpowers/sdd/reports/task-02.md`）。

`git config core.autocrlf` 仍为 `false`，`.gitattributes` 未被改动，
功能提交里没有任何 `.bat` 文件。

## 偏离计划的地方

1. **`tests/test_inventory.py` 没有改。**
   简报的「文件结构」表里列了它（更新基线数字 + 新增必备类），但
   **任务 2 自己的 Files 小节并没有它**，计划正文里 `tests/test_inventory.py`
   只在**任务 8**（README 与测试清单）才被 Modify。我据此判断任务 2 不动它。
   实际影响为零：`BASELINE_COUNTS` 是**下限**，test_config 17→20、
   test_matcher 51→53、test_pipeline 59→62 都仍高于基线，`test_inventory`
   照常通过。
   **但**：新增的两个类（`TestDetectControl`、`TestVoiceNextCommand`）没有登记
   进 `REQUIRED_CLASSES`。按 `test_inventory.py` 自己的立意（防止关键行为的
   测试被静默删掉），这两条或许该进去 —— 建议任务 8 一并补上。

2. **代码与简报片段有出入的一处**：`detect_control` 我用的是无注解签名
   （见上文 matcher.py 那节的说明）。这是为了让 3.9 能跑，不是随意改动。

3. **`git add -A` 顺带提交了编排方的既有改动**（与任务 1 报告里同一情况）。
   本次提交还包含 `docs/superpowers/plans/2026-09-27-gui-and-voice-controls.md`
   （+49/-38 左右）、`.superpowers/sdd/progress.md`（重写）和新增的
   `.superpowers/sdd/briefs/task-02.md`。这三处在我开工之前的 `git status` 里
   就已经是「已修改 / 未跟踪」状态，**不是我改的**，我也没有编辑它们。
   简报明确指定提交命令为 `git add -A && git commit`，我照做了。
   提交统计因此显示 10 files changed，而真正属于本任务的是其中 7 个文件。

除此之外，步骤 1–7 的代码、插入位置、文案都与简报给的片段逐字一致。

## 疑虑

1. **「直给」的代价这次扩大了入口**：语音这条新路径和「配了 fixed_next_position
   的小键盘 0」一样，**完全不做前台应用护栏**。也就是说手机停在 QQ 上、
   或停在答题页上，只要开口说了「下一题」（或 ASR 把它听成「下一题」），
   程序就会往 (909, 2476) 点下去。这是用户明确选择并接受的取舍
   （设计文档 §2.2、简报开头都这么写），不是 bug。
   之所以还是列出来：`handle_next` 的**读屏**分支是有前台护栏的，
   而固定坐标分支没有 —— 同一个函数的两条路径安全性不同，
   将来若有人以为「handle_next 有护栏」会误判。这条在任务 1 报告里已被提过一次
   （那是针对 numpad 0 路径），语音只是让它更容易触发。

2. **控制语走的是「包含」判定，理论上可能误吞正常选项文字**。
   比如屏幕上真有选项文字含「继续」或英文含 `next` 时，说那个词会被
   当成翻页指令而不是选它。GRE3000 的词表里出现 `next`／`继续` 的概率极低，
   `NEXT_PHRASES` 里也没有「清晰」这类高频词，测试的 `test_not_control`
   已钉住常见词不受影响。仅作记录，不建议现在改。

3. **用户没配 `fixed_next_position` 时，「语音说下一题」仍会读屏**。
   因为 `handle_next` 在没有固定坐标时的兜底就是读屏找按钮。
   这不会点错（读屏分支有前台护栏），只是慢约 2.4 秒，
   与「直给」的体感不一致。用户实际已配固定坐标（本项目的用法就是配好），
   所以不影响现状；若哪天想统一，可以在没配坐标时提示用户补配。

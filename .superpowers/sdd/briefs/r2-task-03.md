# 任务简报：语音控制开关 + 识别语言可选（逻辑层）


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

## 任务 3：语音控制开关 + 识别语言可选（逻辑层）

**依据**
- **语音开关**：日志里出现过一次 `[听到] '第一个'`（`语言 en`）—— **是环境杂音或手机自己念的**，
  结果按序号点了一下。序号（「1」「第二个」）和「下一题/继续」这类词太容易被误触发。
  用户要求：加一个开关管这两样，**默认关**。（用户原话：「1 和 2 功能同一个开关，属于选项的语音选择」。）
  **说单词来选选项那条路不受此开关管**（那是用户语音的主力用法，他列的三项里没有它）。
- **识别语言**：日志里 19 次开口有 4 次明明是英文却被判成中文（`category`、`Connection` 都打了 `语言 zh`）。
  用户现在主要玩「按英文释义选英文单词」那一档，希望可以锁定语言。

**Files**
- Modify: `voice_tap/config.py`、`config.yaml`、`voice_tap/matcher.py`、`voice_tap/main.py`
- Test: `tests/test_config.py`、`tests/test_matcher.py`、`tests/test_pipeline.py`

**Interfaces**
- `VoiceConfig.commands: bool = False`（管「说序号」与「说下一题」）；**删除 `VoiceConfig.next_command`**（并入它）
- `matcher.match(spoken, options, cfg=None, allow_ordinal=True)` —— 新增第四个参数
- `handle_speech` 里的控制语分支改用 `cfg.voice.commands`

- [ ] **步骤 1：写测试**

`tests/test_matcher.py`：

```python
class TestOrdinalCanBeDisabled(unittest.TestCase):
    """说序号这条路可以被关掉（用户要求默认关 —— 杂音说出「第一个」会误点）"""

    def test_ordinal_works_by_default(self):
        options = [Node(text="alpha", x=1, y=1), Node(text="beta", x=1, y=2)]
        result = matcher.match("1", options)
        self.assertTrue(result.by_ordinal)

    def test_ordinal_off_falls_through_to_text(self):
        options = [Node(text="alpha", x=1, y=1), Node(text="beta", x=1, y=2)]
        result = matcher.match("1", options, allow_ordinal=False)
        self.assertFalse(result.by_ordinal, "关掉之后不该再按序号命中")
        self.assertFalse(result.ok, "屏幕上没有「1」这个词，应当匹配不上（而不是乱点）")
```

（`Node` 从 `voice_tap.screen` 导入；文件顶部补 import。）

`tests/test_config.py`：

```python
class TestVoiceCommandsSwitch(unittest.TestCase):
    """说序号 / 说「下一题」的总开关，默认关"""

    def test_default_is_off(self):
        self.assertFalse(cfgmod.VoiceConfig.commands)

    def test_shipped_config_is_off(self):
        real = Path(__file__).resolve().parent.parent / "config.yaml"
        self.assertFalse(cfgmod.load_config(real).voice.commands)

    def test_parsed_on(self):
        cfg = load_yaml("voice:\n  commands: 开\n")
        self.assertTrue(cfg.voice.commands)
```

并把原来的 `TestVoiceNextCommand` 改成断言新开关（`next_command` 已并入它）。

`tests/test_pipeline.py`：给现有的 `TestVoiceNextCommand` 加一条 —— **开关关着时，说「下一题」不点**
（`ctx["cfg"].voice.commands = False`）。

- [ ] **步骤 2：跑，确认红**

- [ ] **步骤 3：实现**

- `config.py`：`VoiceConfig` 里 `next_command` 换成 `commands: bool = False`，`load_config` 那行跟着改。
- `config.yaml`：`voice:` 段里把 `next_command: true` 换成 `commands: false` + 注释（写明它管「说序号」和「说下一题」，
  **说单词选选项不受它管**，以及为什么默认关：杂音误触发）。
- `matcher.py`：`match(...)` 加 `allow_ordinal=True`；`if ordinal is not None:` 那一段外面套 `if allow_ordinal:`。
- `main.py` 的 `handle_speech`：
  - 控制语分支的条件 `ctx["cfg"].voice.next_command` → `ctx["cfg"].voice.commands`
  - 调 `matcher.match(...)` 时传 `allow_ordinal=ctx["cfg"].voice.commands`

- [ ] **步骤 4：跑全套 + 「改坏看红不红」**

---

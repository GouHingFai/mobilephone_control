# 任务简报：界面标注快捷键 + 两个新控件


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

## 任务 4：界面上标注快捷键，并加两个新控件

**要求（用户原话）**：「界面设计，还是得把对应功能的快捷键一并列上去（如果没有快捷键的就不用列）」。

**Files**
- Modify: `voice_tap/gui.py`、`voice_tap/main.py`（`collect_state`）
- Test: `tests/test_pipeline.py`

**Interfaces**
- `collect_state(ctx)` 的 `toggles` 里**新增两个键**：`language`（当前 `cfg.asr.language`，None/`"zh"`/`"en"`）
  和把开关状态一并给出；并**新增 `hotkeys`** 一项：从 `cfg.hotkey` 取到的按键名，供界面标注
- 新增意图名：`"toggle_voice_commands"`（切 `cfg.voice.commands`）、`"cycle_language"`（在 自动/zh/en 之间轮转）

- [ ] **步骤 1：先写测试（`collect_state` 是可测的，界面不是）**

`tests/test_pipeline.py` 的 `TestCollectState` 里加：

```python
    def test_reports_hotkeys_for_the_gui_to_show(self):
        """界面要在每个开关旁边标出快捷键 —— 数据从配置里来，不写死在 gui.py"""
        ctx = self._ctx()
        state = app.collect_state(ctx)
        self.assertEqual(state["hotkeys"]["voice"], "f7")
        self.assertEqual(state["hotkeys"]["mode"], "f9")
        self.assertEqual(state["hotkeys"]["numpad"], "f10")
        self.assertEqual(state["hotkeys"]["quit"], "esc")

    def test_reports_voice_commands_and_language(self):
        ctx = self._ctx()
        state = app.collect_state(ctx)
        self.assertIn("voice_commands", state["toggles"])
        self.assertIsNone(state["toggles"]["language"])
```

再加两条意图的测试（放进 `TestHandleIntent`）：切 `toggle_voice_commands` 会翻转 `cfg.voice.commands`；
`cycle_language` 走 `None → "zh" → "en" → None`。

- [ ] **步骤 2：跑，确认红**

- [ ] **步骤 3：实现**

- `main.py`：
  - `collect_state` 的 `toggles` 里加 `"voice_commands": ctx["cfg"].voice.commands` 和 `"language": ctx["cfg"].asr.language`；
    新增 `"hotkeys": {"voice": cfg.hotkey.toggle_voice, "mode": cfg.hotkey.toggle_mode, "numpad": cfg.hotkey.toggle_numpad, "quit": "esc"}`。
  - `ctx["intents"]` 里加 `"toggle_voice_commands"`（用现成的 `_toggle_flag(ctx, "voice", "commands", "语音说序号/下一题")`）
    和 `"cycle_language"`（小函数：`None → "zh" → "en" → None`，每次打一行日志说明当前是什么）。
- `gui.py`：
  - 按钮文字带上快捷键：`f"{label} {hotkey.upper()}"`（**hotkey 从 `collect_state` 给的来**，别写死；
    没有对应快捷键的（点击后预读、语音选择）就不加后缀）。
  - 模式那个按钮特殊：它显示的是当前模式，文字形如 `常驻监听 F9` / `按住说话 F9`。
  - 新增两个控件，**放在第二行**（第一行是原来那三个）：`语音选择`（无快捷键）、`识别语言：自动`（无快捷键）。
  - 语言那个按钮点一下轮转：`识别语言：自动` → `识别语言：中文` → `识别语言：英文`。
  - **`gui.py` 仍然必须极薄** —— 这里全是「把 collect_state 的数据拼成文字」和「把点击变成意图名」，
    不含任何判断逻辑（轮转的规则在 `main.py` 的 `cycle_language` 里）。

- [ ] **步骤 4：语法校验 + 跑全套**

```
python3 -c "compile(open('voice_tap/gui.py',encoding='utf-8').read(),'gui.py','exec'); print('OK')"
python3 -m unittest discover -s tests 2>&1 | tail -3
```

**别声称你验过界面** —— 沙箱没有显示器。把「我没能验证真窗口」如实写进报告。

---

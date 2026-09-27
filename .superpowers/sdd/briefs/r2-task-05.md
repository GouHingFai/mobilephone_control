# 任务简报：文档与测试清单收尾


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

## 任务 5：文档与测试清单收尾

- [ ] **步骤 1：`tests/test_inventory.py`**
  - `BASELINE_COUNTS` 按实际读出的数字更新（**每个改动都要在旁注明理由**）。
  - `REQUIRED_CLASSES` 补上本轮新增的关键类，并去掉已删除的 `TestActionStamp`。
- [ ] **步骤 2：`config.yaml`**
  - 删掉 `prefetch.click_max_attempts`；
  - `voice.next_command` 换成 `voice.commands: false`；
  - `asr.language` 的注释里补一句「也可以在界面上循环切换」。
- [ ] **步骤 3：`README.md`**
  - 「怎么用」里补：按小键盘时界面上会在每个开关旁标出快捷键；
  - 「配置」表格里 `prefetch.click_delay_ms` 附近补一条说明「预读最多读两次」；把已删除的配置项去掉；
  - 补一条「语音说序号 / 说下一题 默认关」以及怎么在界面上打开。
- [ ] **步骤 4：设计文档**
  - `docs/superpowers/specs/2026-09-27-gui-and-voice-controls-design.md` 的 §2.3（动作时戳）
    加一段「2026-09-28 取消」并写明理由；§2.2（语音下一题）补「并入 `voice.commands` 开关，默认关」。
  - 本文档同目录的姊妹计划里那句「连按两下同一个键仍会点两次」属已知残留，不用改。
- [ ] **步骤 5：跑全套 + 验证清单真的在起作用**

删掉一个 `REQUIRED_CLASSES` 里列着的类，确认 `tests.test_inventory` 会红，再还原。

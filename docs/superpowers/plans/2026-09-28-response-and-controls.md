# 响应与开关调整 实施计划（2026-09-28）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 按真机日志暴露出的问题，改掉「按键被吞」、砍掉预读的无用重试、给语音控制加开关、让识别语言可选，并在界面上标出快捷键。

**Architecture:** 不改架构。只动三处：动作队列不再带戳（按键一律生效）、`ScreenPrefetcher.trigger_after_click` 从「最多 4 次重试」改成「最多 2 次确认」、新增两个配置开关并接到界面。

**Tech Stack:** 同上（Python 3.9+、Tkinter、unittest）。

依据：真机日志 `debug/run_20260927_234859.log`（737 行）。**每条改动都对应日志里的实证**，别凭感觉改。

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

## 任务 2：预读最多读两次

**依据（日志实证）**：现在的 `trigger_after_click` 会重试最多 4 次，前提是「点完 App 就会翻页」。
但日志里**点完不翻页出现了 5 次**，于是每次白读 4 次：

```
[匹配] 小键盘第 2 个 → 点击坐标 (606, 999)
[点击] 完成
       [预读] 第 1 次还是旧界面 …（每次读屏约 2.4 秒）
       [预读] 第 4 次还是旧界面，距点击 10592 毫秒，再等等
       [预读] 试了 4 次都没读到变化，放弃
```

一次会话里「试了 4 次放弃」发生 5 次，最长拖到 **16843 毫秒**（第 4 次读屏本身跑了 8566 毫秒）。
这段期间用户的按键进不来。用户的原话：

> 发现读屏和上次一样后，再读一次就行，如果还是一样的话就说明确实没有变，而且一般第二次就不一样了。

**Files**
- Modify: `voice_tap/main.py`、`voice_tap/config.py`、`config.yaml`
- Test: `tests/test_prefetch.py`

**Interfaces**
- `PrefetchConfig.click_retry_ms` 保留（两次读之间的间隔）；**删除 `click_max_attempts`**（不再有第 3、4 次）

- [ ] **步骤 1：先改测试**

`tests/test_prefetch.py` 里现有 `test_gives_up_when_screen_never_changes` 断言「试满次数再放弃」，
**这个行为要没了**，改写成：

```python
    def test_never_changes_still_stores_after_two_reads(self):
        """
        界面一直没变（比如点完根本不翻页）—— 读两次就收下，不无限重试。

        用户的原话：连续两次读到的内容一样，就说明这就是当前屏幕。
        而现在的「读到的还和点击前一样就再读一次」，最多 4 次、白耗十秒，
        期间他的按键全被挡住。
        """
        prefetcher, adb, logs, _cfg = make_prefetcher(FIRST_XML, click_retry_ms=1)

        prefetcher.note(screen.read_screen(FIRST_XML))
        prefetcher.invalidate()
        prefetcher.trigger_after_click()
        self.assertTrue(wait_idle(prefetcher))

        self.assertEqual(adb.calls, 2, "最多读两次，不该有第 3、4 次")
        self.assertIsNotNone(prefetcher.take(), "第二次读到的就是当前屏，要收下")
        self.assertTrue(any("两次" in line or "确认" in line for line in logs))
```

再加一条：**读到新界面时只读一次**（不确认第二遍）：

```python
    def test_reads_once_when_screen_changed(self):
        prefetcher, adb, _logs, _cfg = make_prefetcher(FIRST_XML, SECOND_XML)

        prefetcher.note(screen.read_screen(FIRST_XML))
        prefetcher.invalidate()
        prefetcher.trigger_after_click()
        self.assertTrue(wait_idle(prefetcher))

        self.assertEqual(adb.calls, 1, "第一次就读到新界面就不该再读")
```

- [ ] **步骤 2：跑，确认新的那条红、旧的（`test_gives_up_...`）红**

- [ ] **步骤 3：改 `trigger_after_click`**

```python
        def work():
            delay = self.cfg.click_delay_ms / 1000.0
            retry = self.cfg.click_retry_ms / 1000.0
            started = time.monotonic()
            try:
                time.sleep(delay)
                read_start = time.monotonic()
                try:
                    snap = screen.read_screen(self.adb.dump_ui())
                except Exception as exc:  # noqa: BLE001
                    self.log(f"       [预读] 读屏失败（{type(exc).__name__}），放弃")
                    return

                if before is None or self.signature(snap) != before:
                    self.note(snap, read_at=read_start)
                    self.log(f"       [预读] 读到新界面，"
                             f"距点击 {(time.monotonic() - started) * 1000:.0f} 毫秒")
                    return

                # 和点击前一样：再读一次确认。
                #
                # **只确认一次，不再有第 3、4 次。** 理由（用户提出、日志支持）：
                # 连续两次读到同一屏，就说明这就是当前屏幕 —— 继续读不会读到别的，
                # 只会白耗时间（每次读屏约 2.4 秒），而这段时间用户的按键全被挡住。
                # 真机日志里有 5 次白读满 4 遍，最长拖了 16.8 秒。
                self.log("       [预读] 还是旧界面，再读一次确认")
                time.sleep(retry)
                read_start = time.monotonic()
                try:
                    snap = screen.read_screen(self.adb.dump_ui())
                except Exception as exc:  # noqa: BLE001
                    self.log(f"       [预读] 第二次读屏失败（{type(exc).__name__}），放弃")
                    return

                # 第二次无论读到什么，都收下 —— 它反映的就是当下这一屏。
                self.note(snap, read_at=read_start)
                if self.signature(snap) == before:
                    self.log("       [预读] 两次一样，认定这就是当前屏，收下")
                else:
                    self.log("       [预读] 第二次读到了新界面，收下")
            finally:
                with self._lock:
                    self._busy = False
```

- [ ] **步骤 4：删掉 `click_max_attempts`**

`config.py` 的 `PrefetchConfig` 去掉这个字段、`load_config` 里去掉那行；`config.yaml` 里整段注释删掉。
`tests/test_config.py` 若引用了它，一并改。

- [ ] **步骤 5：跑全套 + 「改坏看红不红」**

把「第二次也收下」改成「第二次仍一样就 return 不存」，确认 `test_never_changes_still_stores_after_two_reads` 变红，再改回来。

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

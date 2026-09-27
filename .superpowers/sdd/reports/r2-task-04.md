# 任务 4 报告：界面标注快捷键 + 两个新控件（数据驱动改造）

## 状态：DONE

主交付完成，**332 个用例真全绿**，4 处「改坏看红不红」全部按预期变红并已还原。
提交 `4f9e072`。

**有一件事我没能验证：真窗口。** 沙箱没有显示器，我只能做语法校验（`compile()`）
和数据层测试。界面在真 Tk 里长什么样、按钮文字变长后会不会挤 —— 我没看过。
详见文末「我明确没验证什么」。定 DONE 而不是 DONE_WITH_CONCERNS，是因为
「没验真窗口」是本轮任务明说的固有边界（简报原话：「别声称你验过界面」），
不是我这边的缺口。

---

## 做了什么

### 1. 结构性改造：把「按钮该显示什么」收成**单一来源**

改造前，这件事的知识在两处：`collect_state` 决定**有哪些键**，`gui.py` 里硬写着
**键名 + 中文标签**（旧的 `TOGGLE_LABELS` / `TOGGLE_ROWS`、`_render_toggles` 里那张
`{"toggle_voice": toggles["voice"], ...}` 映射）。上一轮就是这里栽的：入队格式从三元组
改成二元组，`gui.py` 那边的键名没跟上，**界面上每个按钮都点了没反应，而 300+ 条测试全绿**
（`gui.py` 要 import tkinter，沙箱测不了，没有用例能同时盖住两边）。

现在：

> `collect_state` 给出**每一行有哪些按钮**、每个按钮的**完整文字**（含快捷键后缀）
> 和对应的**意图名**；`gui.py` 只照着数据摆控件、点一下把意图名交出去。

返回的数据形状（`voice_tap/main.py` `collect_state`）：

```python
{
  "controls": [                              # 两行，等宽网格
    [ {"intent": "toggle_voice",     "text": "语音 F7：开",   "on": True},
      {"intent": "toggle_mode",      "text": "常驻监听 F9",   "on": False},
      {"intent": "toggle_numpad",    "text": "小键盘 F10：关", "on": False} ],
    [ {"intent": "toggle_prefetch",  "text": "点击后预读：开", "on": True},
      {"intent": "toggle_voice_commands", "text": "语音选择：关", "on": False},
      {"intent": "cycle_language",   "text": "识别语言：自动", "on": None} ],
  ],
  "actions": [                               # 底部一排，靠左
    {"intent": "force_read", "text": "强制重新读屏", "on": None},
    {"intent": "quit",       "text": "退出 ESC",    "on": None},
  ],
  "screen": ..., "inputs": ...,
}
```

- **按钮文字全在 `main.py` 拼好**，快捷键名从 `cfg.hotkey` 现取（`f"语音 {hotkey.toggle_voice.upper()}：…"`），
  **没写死**；`ESC` 是唯一一个字面量键名（`cfg.hotkey` 里没有它 —— ESC 由热键管理器单独处理）。
- **没有对应快捷键的就不加后缀**：点击后预读、语音选择、识别语言。
- **布局（几行、每行几个）来自 `controls` 的长度**，不是写死在 `gui.py` 里。
- `gui.py` 里现在**搜不到任何按钮标签、意图名、快捷键**（实测见下）。

### 2. 快捷键标注（用户要求）

| 按钮 | 文字 |
|---|---|
| 语音 | `语音 F7：开` / `语音 F7：关` |
| 模式 | `常驻监听 F9` / `按住说话 F9`（显示**当前模式**，不是开/关） |
| 小键盘 | `小键盘 F10：开` / `小键盘 F10：关` |
| 点击后预读 | `点击后预读：开` / `…：关` |
| 语音选择 | `语音选择：开` / `…：关` |
| 识别语言 | `识别语言：自动` / `：中文` / `：英文` |
| 强制重新读屏 | `强制重新读屏`（见「偏离」第 3 条） |
| 退出 | `退出 ESC` |

### 3. 两个新控件

- **语音选择**（开关）→ 意图 `toggle_voice_commands`，翻 `cfg.voice.commands`。
- **识别语言**（循环）→ 意图 `cycle_language`，走 `None → "zh" → "en" → None`，
  每次打一行日志。**轮转规则在 `main.py` 的 `cycle_language()` 里，界面不碰。**

### 4. 顺手接上的护栏（超出简报，但正是本任务的题眼）

- `control_intents(ctx)`：把「与热键无关」的三个意图抽成模块级函数，`main()` 展开进
  `ctx["intents"]`。这样**测试能拿到真接线**，不必在测试里把同一段 lambda 再抄一遍
  （抄一遍就只测了抄的那份，测不到 `main()` 里那张表 —— 那正是「点了没反应」的成因）。
- `unwired_intents(state, intents)`：算出「界面会发、但意图表里没有」的意图名，
  `main()` 启动时打一句警告。界面按钮的全部行为就是「把意图名交出去」，
  表里没有 = 这个按钮是死的，而且是**静默**死的。这个函数把静默变成出声。

### 5. 改名（简报要求）

`toggle_voice_next` → **`toggle_voice_commands`**；`collect_state` 的 `toggles` 整块
**换成了 `controls`**（不再两边都留）。实测 `grep 'toggle_voice_next\|voice_next' voice_tap/main.py`
无命中。

### 改动的文件

| 文件 | 改动 |
|---|---|
| `voice_tap/main.py` | 新增 `_LANGUAGE_CYCLE`/`_LANGUAGE_NAMES`/`_language_label`/`cycle_language`/`control_intents`/`unwired_intents`；重写 `collect_state`（`toggles` → `controls`+`actions`）；意图表改名 + 展开 `control_intents` + 加启动护栏 |
| `voice_tap/gui.py` | 删掉 `TOGGLE_LABELS`/`TOGGLE_ROWS`/`_labels`/`_render_toggles`；`_build` 改成照数据摆；新增 `_intent_command`/`_render_buttons`/`_apply_button` |
| `tests/test_pipeline.py` | 重写 `TestCollectState`；新增 `TestUnwiredIntents`；`TestHandleIntent` 加两条真接线；加工具函数 `buttons_by_intent` |
| `tests/test_inventory.py` | `tests.test_pipeline` 基线 104 → 120（含理由注释） |

---

## 测试结果

### 起点基线

`rm -rf tests/__pycache__ voice_tap/__pycache__ && python3 -m unittest discover -s tests`
→ **Ran 320 tests … OK**（与父任务说的 320 一致；简报里写的「311」是更早的数字）。

### TDD：先红

写完测试、未改实现时：**Ran 332 tests … FAILED (errors=15)** —— 15 条全部是我新加/
改写、指向尚不存在的 `controls`/`actions`/`control_intents`/`unwired_intents` 的用例。
确认红之后才开始实现。

### 「改坏看红不红」（每处都清过字节码缓存）

| # | 把哪儿改坏 | 变红的用例 | 结果 |
|---|---|---|---|
| M1 | `collect_state` 里语音按钮文字去掉 `{hotkey...}`（不再带 F7） | `test_buttons_carry_their_hotkey_in_the_text` + `test_hotkeys_come_from_config_not_hardcoded` | **红 ×2** |
| M2 | 语言按钮文字写死成 `"识别语言：自动"`（不再跟 `cfg.asr.language`） | `test_language_button_text_follows_the_current_language` | **红** |
| M3 | 第一行多塞一个按钮（破坏 `[3, 3]` 布局） | `test_controls_are_two_rows_of_three` | **红** |
| M4 | 把 `collect_state` 的意图名改回 `toggle_voice_next`（模拟「界面名没跟上表」） | `test_every_button_knows_its_intent` + 3 条按名取按钮的用例 | **红 ×4** |

四处全部还原，还原后复跑 332 全绿。

**另外做了一次真 `ctx` 演练**（不进测试套，只为看护栏真的会响）：
把真实 `collect_state` 的输出喂给 `unwired_intents`，意图表齐全 → `[]`；
故意拿掉 `toggle_voice_commands` 一项 → `['toggle_voice_commands']`。

> 过程瑕疵：第一次做 M1 的自动化脚本我**自己把替换串的结尾引号漏了**，
> 结果改出一个语法错误（跑出来是 import 失败，不是我要看的断言红）。
> 已换掉那段脚本、改用 Edit 逐处改，上表是重做后的结果。

### 最终

```
Ran 332 tests in 13.5s
OK
```

**332 = 320 + 12**（新增：`TestCollectState` 净增 7 条、`TestHandleIntent` 2 条、
`TestUnwiredIntents` 3 条），与 `test_inventory.py` 的新基线 120（`test_pipeline`）吻合。

### 其它校验

- `compile(open('voice_tap/gui.py',encoding='utf-8').read(),'gui.py','exec')` → **OK**（不 import tkinter）。
- `import voice_tap.main` 后 `'tkinter' in sys.modules` → **False**（不带 `--gui` 仍不碰界面）。
- `python -m voice_tap.main --help` → 正常。
- `gui.py` 字面量扫描：`语音/小键盘/下一题/预读/识别语言/toggle_/force_read/quit/F7/F8/F9/F10/ESC`
  **全部 0 命中**；只剩注释里的普通中文词「退出/模式/语言」（不是按钮标签，也不是用来查表的）。

---

## 我明确没验证什么

1. **真窗口（Tk）**：布局是不是真的两行三列、`controls`/`actions` 的摆法看着对不对、
   `refresh()` 里 `button.config(text=...)` 把文字换上去会不会有抖动 —— **一律没看过**。
   沙箱无显示器，`gui.py` 只做了语法校验，渲染路径**一行都没执行过**。
2. **按钮文字变长后的实际宽度**。原来的标签是 `语音说下一题：开` 这种，现在 `点击后预读：开`
   是 7 个汉字，加 `width=8` 只是列宽下限、真实宽度由 `uniform` 等分决定。360px 窗口下三列
   每列约 110px，7 汉字按 14px/字约 98px —— 理论够，但**没有实测**。如果真机上挤了，
   改 `_build` 里的 `width` 或在 `main.py` 里缩短标签即可，不涉及结构。
3. **`cycle_language` 改了之后下一句识别是否真用新语言**。这依赖 `asr.py` 每句现读
   `cfg.asr.language`（任务 3 已确认），我没跑过真识别。

---

## 偏离计划的地方及原因

1. **用 `controls`+`actions` 取代简报建议的「`toggles` 加两个键 + 另加 `hotkeys` 一项」。**
   父任务明确允许换成 `controls`（「别两边都留」），我照做了。**没有另存 `hotkeys` 一份** ——
   `gui.py` 只需要最终文字，另存一份就是第二个来源，正是要消掉的东西。快捷键因此体现在
   按钮文字里（测试也按这个断言）。若后续有人需要「裸键名」，从 `cfg.hotkey` 取即可。
2. **底部的「强制重新读屏 / 退出」也搬进了数据**（`actions`）。不搬的话 `gui.py` 里仍留着
   写死的标签，与「不许再出现任何硬写的按钮标签」直接冲突。顺带给退出标了 `ESC` ——
   用户原话的例子里就有「退出 ESC」。
3. **「强制重新读屏」没加后缀**。它的键是小键盘 `.`，不在 `cfg.hotkey` 里，用户列举的例子
   （语音/模式/小键盘/退出）也没有它，所以按「没有快捷键的就不用列」处理。若认为该写
   「强制重新读屏（小键盘 .）」，改 `collect_state` 一行即可。
4. **新增 `control_intents` / `unwired_intents` 两个模块级函数**，简报只提到 `cycle_language`。
   多出来的两个是「让测试拿到真接线」「让意图名对不上时出声」的护栏，属于父任务点名的
   「变成结构上不可能出错」范围，不是自作主张加功能。
5. **文字格式 `语音 F7：开`（键名在状态前）**，简报只给了模式按钮的样例、没规定这个顺序。
   可调。

---

## 疑虑

1. **`on` 字段目前界面不用**。文字里已经含「开/关」，`gui.py` 只读 `text` 和 `intent`；
   `on` 留着是给将来的视觉提示用（比如配色）。父任务把 `on` 列进了建议形状，我就留着了，
   但**它现在是「有断言、没消费」的数据**。若评审认为这是死数据，去掉不影响界面。
2. **`unwired_intents` 的护栏只在 `main()` 启动时跑一次**，且**没有测试能覆盖 `main()` 里
   那张真表**（`ctx["intents"]` 在 `main()` 内构造）。我覆盖的是这个纯函数本身（合成数据）
   + `control_intents` 的真接线。剩下的 `toggle_voice/toggle_mode/toggle_numpad/force_read/quit`
   五条仍是「写名字」的，理论上仍可能和 `collect_state` 对不上 —— 区别是**现在会被当场喊出来**，
   不再是静默装死。要彻底消灭它，得把整张表也抽成可测函数（`toggle_mode`/`voice_toggle`
   是 `main()` 里依赖 `hotkeys` 的闭包，抽出来要动到热键注册那条线，超出本轮范围）。
3. **「语音选择」这个标签措辞**是我起的（它翻的仍是合并后的 `voice.commands`，
   管「说序号」+「说下一题」两样）。原来叫「语音说下一题」。用户要的是「语音选择」，
   但一个字面上叫「语音选择」的开关，实际会同时打开「说序号」和「说下一题」——
   若用户以为是「选语音输入设备」就误解了。**建议让用户看一眼确认。**

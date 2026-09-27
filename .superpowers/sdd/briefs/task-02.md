# 任务简报：任务 2（语音说「下一题」）

## 项目是什么

`voice_tap`：Windows 上的声控工具。用户用 scrcpy 投屏安卓手机玩 GRE3000 背单词，
开口说选项、或按小键盘数字，程序读屏后自动点对应选项。**代码与注释全中文，
你写的注释、日志、提交信息也用中文。**

## 关键约束

## Global Constraints

- **测试命令**：`python -m unittest discover -s tests`（**没有 pytest**，别用 `-m pytest`）。沙箱里跑需要先 `pip install pypinyin --break-system-packages`，否则 3 个拼音测试会因为缺库而失败（那是环境问题）。
- **项目已启用 git**（2026-09-27 建立基线，初始提交“chore: 建立版本控制基线”）。每个任务做完执行 `git add -A && git commit -m "..."`。
  仓库里已配好 `core.autocrlf=false` 与 `.gitattributes`（**强制 `.bat` 保持 CRLF**）——**不要改动这两样，把行尾转换打开会把 `.bat` 改坏**。沙箱里 git 需要删除权限，已开。
- **每个任务开始前先在项目根目录跑一次** `python3 -m unittest discover -s tests` **确认起点是绿的**。
- **各任务末尾的「期望」一律写成「比开跑前多 N 个」，不要用绝对数** —— 用例总数会随任务累积，
  绝对数一写就过时。请以你自己跑第 1 条命令时输出的那个数为基准去加。
- **跑测试前先清一次字节码缓存**：`rm -rf tests/__pycache__ voice_tap/__pycache__`。
  本仓库里 `.py` 和 `.pyc` 常在同一秒落盘，改动若不改变字节数（比如交换两行），
  Python 会复用旧字节码、读到错的版本 —— 做「故意改坏看测试红不红」这类实验时尤其会中招。
- **不带 `--gui` 时，行为必须与现在完全一致。** 任务 4/5/6 是重构，靠现有的 222 个测试兜底；每步都要跑全套。
- **所有用户可见输出走 `main.say()`**（同时打印并落盘到 `debug/run_*.log`），不要用裸 `print()`。
- **`.bat` 文件必须纯 ASCII + CRLF 行尾**，中文提示一律放在 Python 里（用 Write 工具写出来的是 LF，需要以二进制方式写并显式替换成 `\r\n`）。
- **界面不显示坐标**（用户明确要求）；坐标只进日志。
- **界面逻辑一律放 `ui_state.py` 与 `main.py` 的函数里**；`gui.py` 只摆控件、连线、刷新。
- **坐标/尺寸一律用整数**；`config.yaml` 里 `window: [x, y, w, h]`。
- 兼容 Python 3.9：新增模块顶部加 `from __future__ import annotations`（`config.py` 已有）。
- **各任务末尾写的「期望 N 个全过」是按计划里逐条测试相加算出来的**（基线 222）。差一两个不用慌；
  **差得多就说明漏加了测试**，回去对着该任务里的测试清单数一遍。

## 文件结构

| 文件 | 动作 | 职责 |
|---|---|---|
| `voice_tap/matcher.py` | 改 | 新增 `NEXT_PHRASES` + `detect_control()`（纯函数） |
| `voice_tap/config.py` | 改 | 新增 `GuiConfig`、`VoiceConfig.next_command`、`load_config` 解析 |
| `config.yaml` | 改 | 新增 `gui:` 段、`voice.next_command` |
| `voice_tap/ui_state.py` | **新建** | 线程安全的状态黑板 + 意图队列（纯 Python，可完整单测） |
| `voice_tap/gui.py` | **新建** | Tkinter 窗口：摆控件、连线、每 150ms 刷新 |
| `voice_tap/main.py` | 改 | `ScreenPrefetcher.identity()`；抽 `run_voice_loop`；统一动作队列；`collect_state`/`handle_intent`；动作时戳；语音「下一题」接线；结果回报 |
| `run_gui.bat` | **新建** | 带 `--gui` 启动 |
| `tests/test_matcher.py` | 改 | `detect_control()` 测试 |
| `tests/test_config.py` | 改 | `gui.*`、`voice.next_command` 测试 |
| `tests/test_ui_state.py` | **新建** | `UiState` 测试 |
| `tests/test_pipeline.py` | 改 | 动作时戳、语音「下一题」端到端测试 |
| `tests/test_inventory.py` | 改 | 更新基线数字 + 新增必备类 |
| `README.md` | 改 | 补界面说明；修掉「已经能说下一题」的不实描述与过时数字 |

**任务顺序**：1 → 2 是**小而独立**的（修 bug + 语音下一题），做完就可以先用起来；3 → 8 是界面。若只想先要前者，做完任务 2 即可停。

## 你这次要做的事

## 任务 2：语音说「下一题」

**Files**
- Modify: `voice_tap/matcher.py`、`voice_tap/config.py`、`config.yaml`、`voice_tap/main.py`
- Test: `tests/test_matcher.py`、`tests/test_config.py`、`tests/test_pipeline.py`

**Interfaces**
- Produces:
  - `matcher.NEXT_PHRASES: tuple[str, ...]`
  - `matcher.detect_control(text: str) -> str | None` —— 目前只会返回 `"next"` 或 `None`
  - `VoiceConfig.next_command: bool = True`
  - `handle_next(ctx, source="小键盘 0")` —— 新增 `source` 参数

- [ ] **步骤 1：先写失败的测试（matcher）**

在 `tests/test_matcher.py` 末尾加：

```python
class TestDetectControl(unittest.TestCase):
    """
    控制语：说这些话不是要选某个选项，而是要程序做一件事（目前只有「下一题」）。

    它必须**优先于**选项匹配 —— 否则「下一题」会被拿去和选项比对，永远匹配不上。
    """

    def test_next_phrases(self):
        for spoken in ("下一题", "下一词", "下一个", "继续", "next", "说下一题", "下一题吧"):
            with self.subTest(spoken=spoken):
                self.assertEqual(matcher.detect_control(spoken), "next")

    def test_not_control(self):
        for spoken in ("清晰", "proliferate", "1", "", "extol"):
            with self.subTest(spoken=spoken):
                self.assertIsNone(matcher.detect_control(spoken))
```

- [ ] **步骤 2：跑测试，确认失败**

```
python -m unittest tests.test_matcher.TestDetectControl -v
```

期望：`AttributeError: module 'voice_tap.matcher' has no attribute 'detect_control'`。

- [ ] **步骤 3：实现 `detect_control`**

在 `voice_tap/matcher.py` 的 `parse_ordinal` 之后加：

```python
# 控制语：说这些话不是要选某个选项，而是要程序做一件事。
# 目前只有「下一题」一种 —— 答错进详情页后用它继续。
#
# 判定用「包含」而不是「相等」：ASR 常在前后带上零碎字词
# （「说下一题」「下一题吧」），只要里面出现了这个词，就是那个意思。
NEXT_PHRASES = (
    "下一题", "下一词", "下一首", "下一个", "下一组", "下一关",
    "继续", "next",
)


def detect_control(text):
    """
    看一眼识别出的文字里有没有控制语。

    返回 "next" 表示「去点下一题」，没有则返回 None。
    必须**优先于**选项匹配调用 —— 否则「下一题」会被拿去和选项比对。
    """
    key = normalize(text)
    if not key:
        return None
    for phrase in NEXT_PHRASES:
        if normalize(phrase) in key:
            return "next"
    return None
```

- [ ] **步骤 4：配置项 `voice.next_command`**

`voice_tap/config.py` 的 `VoiceConfig` 里加：

```python
    # 允许说「下一题」翻页（答错进详情页后用它继续）。
    #
    # 注意这是**直给**：说了就点固定坐标，不读屏校验 ——
    # 因此在答题页上误说也会点下去。这是用户明确选择的取舍。
    next_command: bool = True
```

`load_config` 里 `VoiceConfig(...)` 的构造加一行：

```python
        next_command=_pick(v, "next_command", VoiceConfig.next_command, _to_bool, n, "voice"),
```

`config.yaml` 的 `voice:` 段末尾加：

```yaml
  # 允许说「下一题」来翻页（答错进详情页后用它继续）。
  #
  # 注意：这是「直给」——说了就点固定坐标，不读屏校验。
  # 所以在答题页上误说「下一题」也会点下去。这是有意选的取舍。
  next_command: true
```

在 `tests/test_config.py` 末尾加：

```python
class TestVoiceNextCommand(unittest.TestCase):

    def test_code_default_is_on(self):
        self.assertTrue(cfgmod.VoiceConfig.next_command)

    def test_shipped_config_is_on(self):
        real = Path(__file__).resolve().parent.parent / "config.yaml"
        self.assertTrue(cfgmod.load_config(real).voice.next_command)

    def test_parsed_off(self):
        cfg = load_yaml("voice:\n  next_command: 关\n")
        self.assertFalse(cfg.voice.next_command)
```

- [ ] **步骤 5：接线到 `handle_speech`，并给 `handle_next` 加 `source`**

`handle_next` 签名改为 `def handle_next(ctx, source="小键盘 0"):`，
把函数体里第一行 `say("[小键盘] 0 → 下一题")` 改成 `say(f"[{source}] 下一题")`。

在 `handle_speech` 里，**在 `try: snap, source = grab_screen(ctx)` 之前**插入：

```python
    # 控制语优先，而且要排在取屏幕之前 —— 因为「下一题」走固定坐标，
    # 根本不需要读屏。说了就点，这是用户选的「直给」方式。
    if ctx["cfg"].voice.next_command and matcher.detect_control(text) == "next":
        handle_next(ctx, source="语音")
        return
```

- [ ] **步骤 6：端到端测试**

在 `tests/test_pipeline.py` 末尾加：

```python
class TestVoiceNextCommand(unittest.TestCase):
    """说「下一题」= 点下一题（直给：不读屏校验）"""

    def _ctx(self, xml):
        ctx, fake = make_ctx(xml)
        ctx["cfg"].hotkey.fixed_next_position = (909, 2476)
        return ctx, fake

    def test_saying_next_clicks_the_button(self):
        ctx, fake = self._ctx(DETAIL_XML)

        app.handle_speech("下一题", -0.4, ctx)

        self.assertEqual(fake.taps, [(909, 2476)])
        self.assertEqual(fake.dump_calls, 0, "固定坐标不该读屏")

    def test_works_on_quiz_page_too(self):
        """直给：答题页上说了照样点（用户明确接受这个取舍）"""
        ctx, fake = self._ctx(GRE_XML)

        app.handle_speech("下一题", -0.4, ctx)

        self.assertEqual(fake.taps, [(909, 2476)])

    def test_disabled_by_config(self):
        ctx, fake = self._ctx(DETAIL_XML)
        ctx["cfg"].voice.next_command = False

        app.handle_speech("下一题", -0.4, ctx)

        self.assertEqual(fake.taps, [], "关掉之后不该点；应落回普通匹配并提示详情页")
```

- [ ] **步骤 7：跑全套，全绿**

```
python -m unittest discover -s tests
```

期望：比开跑前多 8 个（matcher 2 + config 3 + pipeline 3）。

---

## 环境提示

- 项目根目录：bash 是 `/sessions/pensive-confident-cerf/mnt/声控手机项目`；文件工具是 `H:\声控手机项目\...`。
- **跑测试前先清字节码缓存**：`rm -rf tests/__pycache__ voice_tap/__pycache__`
  （本仓库 `.py` 与 `.pyc` 常同秒落盘，改动若不改变文件字节数，Python 会复用旧字节码读到错版本）。
- 跑测试：`python3 -m unittest discover -s tests`（**没有 pytest**；沙箱缺 `pypinyin` 就先
  `pip install pypinyin --break-system-packages`）。
- **不要**碰 `.gitattributes` / `core.autocrlf`，**不要**改 `.bat` 文件。
- 参考：设计文档 §2.2「语音『下一题』」讲了为什么选「直给」（说了就点，不读屏校验）。

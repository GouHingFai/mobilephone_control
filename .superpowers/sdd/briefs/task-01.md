# 任务简报：任务 1（动作时戳 —— 修「连按两下同一个键点到新题上」）

## 项目是什么

`voice_tap`：一个 Windows 上的声控工具。用户用 scrcpy 投屏安卓手机玩 GRE3000 背单词，
开口说选项、或用小键盘按数字，程序读屏（uiautomator dump）后自动点对应选项。
代码和注释全是中文。**说话对用户是中文，所以你写注释、日志、提交信息都用中文。**

## 关键约束

## Global Constraints

- **测试命令**：`python -m unittest discover -s tests`（**没有 pytest**，别用 `-m pytest`）。沙箱里跑需要先 `pip install pypinyin --break-system-packages`，否则 3 个拼音测试会因为缺库而失败（那是环境问题）。
- **项目已启用 git**（2026-09-27 建立基线，初始提交“chore: 建立版本控制基线”）。每个任务做完执行 `git add -A && git commit -m "..."`。
  仓库里已配好 `core.autocrlf=false` 与 `.gitattributes`（**强制 `.bat` 保持 CRLF**）——**不要改动这两样，把行尾转换打开会把 `.bat` 改坏**。沙箱里 git 需要删除权限，已开。
- **每个任务开始前先在项目根目录跑一次** `python3 -m unittest discover -s tests` **确认起点是绿的**（基线 222 个用例）。
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

## 你这次要做的事

## 任务 1：动作时戳 —— 修「连按两下同一个键点到新题上」

**Files**
- Modify: `voice_tap/main.py`
- Test: `tests/test_pipeline.py`

**Interfaces**
- Consumes: `ScreenPrefetcher.signature(snap)`（已存在，静态方法）、`ScreenPrefetcher.note()`（已存在）
- Produces:
  - `ScreenPrefetcher.identity() -> tuple | None` —— 最近见过那一屏的指纹，没有任何数据时 `None`
  - `handle_numpad(number, ctx, stamp=None)` —— 新增第三个参数
  - 动作队列条目格式统一成 `(kind: str, value, stamp)`，`kind ∈ {"numpad", "next", "force_read"}`

- [ ] **步骤 1：先写失败的测试**

在 `tests/test_pipeline.py` 顶部（`GRE_XML` 相关定义之后）补一份第二题的夹具：

```python
SECOND_XML = (FIXTURES / "gre_prototype.xml").read_text(encoding="utf-8")
```

在文件末尾（`TestStartupProbe` 之后、`if __name__` 之前）加：

```python
class TestActionStamp(unittest.TestCase):
    """
    按键动作要带「按键那一刻的屏幕」的戳；执行前核对，屏幕变了就不点。

    由来（真机上实测到的 bug）：在第一题上连按两下 `1`，
    第一下点完立刻作废缓存并启动后台预读；第二下还在队列里排队，
    等它被处理时预读已经读回了**第二题**，于是照着第二题点了第 1 个。
    根子是：**第一题时做的动作，被用到了第二题上。**
    """

    def _setup(self, xml=GRE_XML):
        cfg = Config()
        cfg.prefetch.after_click = False     # 别让后台预读来搅乱
        cfg.click.settle_ms = 0
        fake = FakeAdb(xml)
        pref = app.ScreenPrefetcher(fake, cfg, log=lambda *_: None)
        pref.note(screen.read_screen(xml))
        ctx = {
            "adb": fake,
            "cfg": cfg,
            "preview": False,
            "recognizer": StubRecognizer(),
            "prefetcher": pref,
            "voice_gate": StubVoiceGate(),
            "clicker": Clicker(fake, cfg.click, log=lambda *_: None),
        }
        return ctx, fake, pref

    def test_identity_is_none_before_any_read(self):
        fake = FakeAdb(GRE_XML)
        pref = app.ScreenPrefetcher(fake, Config(), log=lambda *_: None)
        self.assertIsNone(pref.identity(), "还没读到过任何界面时不该有指纹")

    def test_identity_reflects_last_seen_screen(self):
        _ctx, _fake, pref = self._setup()
        expected = app.ScreenPrefetcher.signature(screen.read_screen(GRE_XML))
        self.assertEqual(pref.identity(), expected)

    def test_dropped_when_screen_changed_since_press(self):
        """按键时是第一题，轮到执行时已经翻到第二题 —— 必须不点"""
        ctx, fake, pref = self._setup()
        stamp = pref.identity()                     # 按键那一刻：第一题
        pref.note(screen.read_screen(SECOND_XML))   # 界面翻了页
        fake.xml = SECOND_XML

        app.handle_numpad(1, ctx, stamp=stamp)

        self.assertEqual(fake.taps, [], "界面已经变了，这一下不能点")

    def test_runs_when_screen_unchanged(self):
        """界面没翻（比如那一下没生效）—— 照常点，这正是「按错键马上改」要的"""
        ctx, fake, pref = self._setup()
        stamp = pref.identity()

        app.handle_numpad(1, ctx, stamp=stamp)

        self.assertEqual(len(fake.taps), 1)

    def test_runs_when_no_stamp_given(self):
        """没盖戳（比如语音路径）时不做拦截"""
        ctx, fake, _pref = self._setup()

        app.handle_numpad(1, ctx)

        self.assertEqual(len(fake.taps), 1)
```

- [ ] **步骤 2：跑测试，确认它按预期失败**

```
python -m unittest tests.test_pipeline.TestActionStamp -v
```

期望：报 `AttributeError: 'ScreenPrefetcher' object has no attribute 'identity'`（以及 `handle_numpad() got an unexpected keyword argument 'stamp'`）。

- [ ] **步骤 3：给 `ScreenPrefetcher` 加 `identity()`**

在 `voice_tap/main.py` 的 `ScreenPrefetcher` 里，紧挨着现有的 `miss_reason()` 之后加：

```python
    def identity(self):
        """
        最近见过那一屏的指纹；还没读到过任何界面时返回 None。

        用途是给按键动作盖章：按下的那一刻记下「当时屏幕长什么样」，
        真正执行前再比一次 —— 不一样，就说明中间翻了页，这一下不能点。
        （参见 handle_numpad 的 stamp 参数与 tests 里的 TestActionStamp。）
        """
        with self._lock:
            if self._last_seen is None:
                return None
            return self.signature(self._last_seen)
```

- [ ] **步骤 4：`handle_numpad` 加 `stamp` 参数并核对**

把 `handle_numpad` 的签名改成 `def handle_numpad(number, ctx, stamp=None):`，
并在 `snap, source = grab_screen(ctx)` 之后、`if not snap.ok:` 之前插入：

```python
    # 核对「动作时戳」：这一下是在哪一屏按的？现在要点的又是哪一屏？
    # 不一样就说明中间翻了页 —— 那这一下绝不能点（会点到新题目上）。
    if stamp is not None and ScreenPrefetcher.signature(snap) != stamp:
        say("[小键盘] 这一下已忽略：界面在按键之后翻页了（不点，免得点到新题上）")
        return
```

同时更新 `handle_numpad` 的 docstring，补一句这个参数的来历。

- [ ] **步骤 5：动作队列改带戳，并让工作线程解开**

在 `main()` 里，把热键接线改成：

```python
        on_option=lambda n: numpad_queue.put(("numpad", n, ctx["prefetcher"].identity())),
        on_next=lambda: numpad_queue.put(("next", None, ctx["prefetcher"].identity())),
        on_force_read=lambda: numpad_queue.put(("force_read", None, None)),
```

再把 `numpad_worker` 的循环体改成：

```python
    def numpad_worker():
        while not worker_stop.is_set():
            try:
                action = numpad_queue.get(timeout=0.2)
            except queue.Empty:
                continue
            try:
                kind, value, stamp = action
            except (TypeError, ValueError):
                continue
            try:
                if kind == "force_read":
                    handle_force_read(ctx)
                elif kind == "next":
                    handle_next(ctx)
                else:
                    handle_numpad(value, ctx, stamp=stamp)
            except AdbError as exc:
                say(f"[!!] {exc}")
            except Exception:  # noqa: BLE001
                say("[!!] 处理小键盘操作时出错：")
                log_exception()
```

**注意**：小键盘回调那三处入队都已经在上面那三个 lambda 里改掉了。`numpad_worker` 里**原来**按 `number == "."` / `number == 0` 判断的那几行要一并删掉，改成按 `kind` 分派（下面这段就是替换后的完整循环体）。

- [ ] **步骤 6：跑测试，全绿**

```
python -m unittest tests.test_pipeline.TestActionStamp -v
python -m unittest discover -s tests
```

期望：新测试全过；全套 227 个（222 + 5）全过。

---

## 环境提示

- 项目根目录：`/sessions/pensive-confident-cerf/mnt/声控手机项目`（在 bash 里用这个路径；
  文件工具用 Windows 路径 `H:\声控手机项目\...`）。
- 跑测试：`cd /sessions/pensive-confident-cerf/mnt/声控手机项目 && python3 -m unittest discover -s tests`
  （**没有 pytest**）。沙箱里若报缺 pypinyin，先 `pip install pypinyin --break-system-packages`。
- **不要**碰 `.gitattributes` / `core.autocrlf`；**不要**改 `run.bat` 等 `.bat` 文件的行尾。
- 参考：设计文档 `docs/superpowers/specs/2026-09-27-gui-and-voice-controls-design.md`
  的 §2.3「动作时戳」讲了这条规则为什么这么定。

# 任务 7 修复报告（第二批）：配置段写歪不能拦门；界面不可用时退回纯命令行

## 状态

**DONE**

（五件事都做完了：**新增 14 个用例，全套 293 → 307 全过**；四处「故意改坏看它变红」
逐个验过并复原；`gui.py` / `main.py` 语法通过；**「界面起不来 → 退回命令行」用假 gui 模块
在内存里真跑了 5 种情形**（见下），不必有 tkinter。
**真 Tk 窗口仍然一次都没跑过** —— 沙箱没显示器、没装 tkinter，这一点没有变，
见「我**没能**验证什么」。）

## 改了什么

| 文件 | 动作 | 内容 |
|---|---|---|
| `voice_tap/config.py` | 改 | 新增 `_section()`：**每一个**顶层段统一兜住非映射值；新增 `MIN_GUI_REFRESH_MS = 30` 与 `_to_refresh_ms()`；`gui.window` 缺键时改为静默取默认 |
| `voice_tap/main.py` | 改 | 界面启动**整段**包进 `try`；任何异常 → `say()` 一句中文提示 → 退回纯命令行老路 |
| `voice_tap/gui.py` | 改 | `run()` 多一个 `on_window_ready` 回调（**+3 行**），窗口建好后才让 main 启动后台监听 |
| `tests/test_config.py` | 改 | 新增 `TestNonMappingSections`（2 个）+ `TestGuiConfig`（12 个） |
| `tests/test_inventory.py` | 改 | `REQUIRED_CLASSES["tests.test_pipeline"]` 加 `TestWindowGeometry`；`tests.test_config` 基线 17 → 34 |
| `config.yaml` | 改 | `gui.refresh_ms` 的注释加一句「比 30 小按 30 算」 |

`_pick` 对「键不存在」的静默行为**一个字都没动**（新测试 `test_missing_section_leaves_no_false_notice`
把它钉住了）。

### 1【Important】非映射的配置段

不是只修 `gui`。写测试时把**九个顶层段**挨个写成非映射值，用 HEAD 的 `config.py` 实测：

| 段写法 | 修复前 | 修复后 |
|---|---|---|
| `hotkey: 3` | **崩**：`AttributeError: 'int' object has no attribute 'get'` | 不崩，整段退默认 + 一句提示 |
| `gui: 3` | **崩**：同上 | 同上 |
| `audio: 3` | 不崩，但**静默吞掉**整段（一句提示都没有） | 不崩，退默认 + 提示 |
| `asr: []` | 同上 | 同上 |
| `match: true` | 同上 | 同上 |
| `click: "x"` | 同上 | 同上 |
| `voice: []` | 同上 | 同上 |
| `run: true` | 同上 | 同上 |
| `prefetch: 3` | 同上 | 同上 |

只有 `hotkey` / `gui` 会崩（它们俩在 `_pick` 之外还手写了 `.get(...)`：
`h.get("fixed_next_position")` 与 `gt.get("window")`）。**其余七个段是「不崩但白写」** ——
用户把一整段配置写歪，程序一声不吭全用默认值跑，这也违背「退回默认值**并留一句提示**」。
所以九个段一起修：统一走 `_section()`。

### 2【Minor】没写 `gui:` 段时的假提示

HEAD 实测：`hotkey: {}` 这份 yaml 会冒出一条

    config.yaml 的 gui.window 不是四个数（None），改用默认值 (40, 120, 360, 520)

修法：`window` 只在**键真的在段里**时才走 `_to_window`，缺键直接静默取默认 ——
和 `_pick` 一个脾气。修复后同一份 yaml 的 `notices` 是 `[]`。
（显式写 `window: null` 仍然算坏值、仍然报提示 —— 那是「写了但写错」，该报。）

### 3【Minor】`refresh_ms` 下限

`MIN_GUI_REFRESH_MS = 30`，小于它一律抬上来并留提示；非数字照旧退默认 150。
实测：`gui: refresh_ms: 0` → 修复前 `0`（`root.after(0, ...)` 忙循环），修复后 `30`。

### 4【Minor】`gui.*` 的测试

`TestGuiConfig` 12 个：`enabled` / `topmost` / `refresh_ms` / `window` 各覆盖
「正常解析」与「坏值退默认 + 有提示」，外加默认值、缺段不报假提示、`refresh_ms` 下限。

### 5【设计文档 §6 承诺过、但没实现】界面用不了时退回纯命令行

原先只兜住了 `from . import gui` 的 ImportError，`tk.Tk()` 自己失败会直接把程序带崩。

改法：**界面启动整段**包进 `try/except`；界面这一趟要么「跑完」、要么「压根起不来」，
用 `window_up` 区分：

- `window_up = False` → 打提示、退纯命令行，落下去走 `run_voice_loop` 那条老路；
- `window_up = True` → 正常收尾（`quit_requested.set()` → 关监听线程 → `hotkeys.stop()` /
  `recognizer.close()`）后 `return 0`。

一个必要的细节：**后台监听线程改成「窗口建好之后」才启动**（`gui.run()` 新增的
`on_window_ready` 回调）。原先线程在 `gui.run()` 之前就起来了，一旦 `tk.Tk()` 当场抛异常，
退回命令行后就会有**两条循环同时抢着点**。挪到窗口建好之后，「界面起不来」时压根没有孤儿线程。

### 实跑证据（假 gui 模块，不需要 tkinter）

沙箱没有 tkinter，所以在内存里伪造了一个 `voice_tap.gui` 模块，把 `main(["--once", "--gui"])`
真的跑起来（`Adb` / `Recognizer` / `HotkeyManager` / `probe_startup_screen` 都换成桩，
`run_voice_loop` 换成记账用的桩，记录**是哪条线程**跑的）：

| 情形 | 结局 | 主循环调用 | 「退回纯命令行」提示 |
|---|---|---|---|
| A 界面起不来（`tk.Tk()` 抛 RuntimeError） | 返回 0，**没崩** | `['MainThread']`（=走了老路） | 有 |
| B 窗口起来之后 `mainloop` 才倒 | 返回 0，**没崩** | `['voice-loop', 'MainThread']`（先叫停后台，再走老路） | 有 |
| C 窗口正常关掉 | 返回 0 | `['voice-loop']`（不走老路） | 无（不该有） |
| D 不带 `--gui`，且配置里 `gui.enabled` 为假 | 返回 0 | `['MainThread']`，**`gui.run` 一次都没被调** | 无 |
| E 配置里 `gui.enabled: true`，界面起不来 | 返回 0，**没崩** | `['MainThread']` | 有 |

C 还确认了 `hotkeys.stop()` 被调到、且退出后**没有残留的 `voice-loop` 线程**。

## 测试结果

```
$ rm -rf tests/__pycache__ voice_tap/__pycache__
$ python3 -m unittest discover -s tests
Ran 307 tests in 11.996s
OK
```

- **新增用例：14 个**（`TestNonMappingSections` 2 + `TestGuiConfig` 12）。
- **最终全套：307 个全过**（起点 293 + 14 = 307，一个不多一个不少）。
- `tests.test_config` 实测 34 个，基线已改成 34（原来是 17 —— 本身就是个低了三格的旧数字）。

**先红后绿**：写完测试、还没动 `config.py` 时跑 `tests.test_config`：

```
FAILED (failures=8, errors=6)
  ERROR ... (section='hotkey', value='3')      ← AttributeError，程序起不来
  ERROR ... (section='gui', value='3')         ← 同上
  ERROR test_refresh_ms_has_a_floor            ← MIN_GUI_REFRESH_MS 还不存在
  FAIL  test_each_bad_section_leaves_a_notice  ← audio/asr/match/click/voice/run/prefetch 七个段静默吞掉
  FAIL  test_missing_section_leaves_no_false_notice  ← 没写 gui 段却报假提示
```

**四次「故意改坏看它变红」**（每次都从备份还原，最后工作区干净）：

| 改坏什么 | 结果 |
|---|---|
| `_section()` 退回成 `data.get(key) or {}` | 14 个红（failures=7, errors=4） |
| `window` 改回 `gt.get("window")` | 1 个红（`test_missing_section_leaves_no_false_notice`） |
| 关掉 `refresh_ms` 下限 | 5 个红（`test_refresh_ms_has_a_floor` 的 5 个 subTest） |
| 把 `TestWindowGeometry` 改个名 | `tests.test_inventory` 报「tests.test_pipeline 里找不到 TestWindowGeometry」 |

## 提交哈希

```
1c7cdaf  fix: 配置段写歪不能把程序拦在门外；界面不可用时退回纯命令行
```

（本报告另起一个 `docs:` 提交，与仓库既有「先 fix 再 docs 报告」的惯例一致。）

## 我**没能**验证什么（这一节请务必当真）

1. **真 Tk 窗口：仍然一次都没跑过。** 沙箱是 Linux、无显示器、没装 tkinter。
   `gui.run()` / `mainloop()` / `AppWindow` 在真 Tk 下没执行过；这次新加的
   `on_window_ready()` 调用点也一样。
2. **第 5 项的验证用的是假 gui 模块**，不是真 Tk。真 Tk 下 `tk.Tk()` 失败时到底抛
   `TclError` 还是别的，我没有实测过（代码里兜的是 `except Exception`，两者都盖得住，
   但「真的会抛」这一点只有真机才算数）。
3. **Ctrl+C 打断界面**那一条（`finally` 里 `window_up` 为真时的收尾）没实跑。
4. `refresh_ms` 下限取 **30 毫秒是否合适**（对 CPU 的占用、拖窗口的手感）没量过 ——
   30 只是「明显不是忙循环」的量级判断。
5. **真机整条链路**（adb / scrcpy / 麦克风 / 小键盘 / 真窗口布局）依旧没跑。

## 疑虑

1. **第 5 项做的比简报字面要多一点**：为了让「退命令行」时不会出现两条监听循环，
   我把后台监听线程的启动时机挪进了 `gui.run()` 的 `on_window_ready` 回调，
   于是 `gui.run()` 多了一个参数（`gui.py` **+3 行**，仍然很薄，没有业务逻辑）。
   如果你更希望 `gui.py` 一个字都不动，替代方案是：不再管孤儿线程，改成
   「窗口起来之后 `gui.run` 才倒」时直接 `raise`（而不是退命令行）——
   代价是不完全符合简报的「任何异常都退回老路」。我选了现在这种。
2. **`tests.test_config` 的基线我动了（17 → 34）**。简报只点名了
   `REQUIRED_CLASSES` 加 `TestWindowGeometry`。理由：审查自己也提了
   「基线远低于现值 → 整类删掉发现不了」，而这次正好往这个文件塞了 14 个用例
   （新类删掉后剩 20 ≥ 旧基线 17，照样绿灯）。要回退是一行的事。
3. **极端情形下仍可能残留一条监听线程**：`window_up` 为真、`gui.run` 才抛异常时，
   我按简报的「任何异常都退回老路」处理 —— 先 `quit_requested.set()` + `join(timeout=3)`
   再复位。若 `join` 超时（比如那条线程正卡在一次 adb 操作里），理论上会残留一条线程，
   和后来的老路抢着点。真 Tk 里 `mainloop` 抛异常几乎不会发生，但我如实列出。
4. **异常退命令行时我把 `ctx["ui"]` 置回了 None**：界面都已经没了，界面状态留着没人看、
   只是白占内存。但如果将来要做「界面重开」，这里得重新想。
5. **提交里带上了 `task-07-review.md`**：简报给的命令是 `git add -A && git commit`，
   而那份审查报告当时还是未跟踪状态（上一轮提交没带上），于是被一并提交了。
   如果你希望审查报告单独一个 `docs:` 提交，我可以拆开。

# 任务 7 报告：`gui.py` 与 `run_gui.bat`

## 状态

**DONE_WITH_CONCERNS**

（代码按简报写完了，能验的三条都验了：**288 用例一个不多一个不少**、两个 `.py` 语法通过、
`run_gui.bat` 确认 CRLF。**界面本身我验不了** —— 沙箱没有显示器、也连不到手机，
所以我不敢说「界面工作正常」，只能说「语法通过、用例数不变、逻辑都在能单测的那两层里」。

之所以标 CONCERNS 而不是 DONE，是因为**简报里少了一步**：step 3 的代码引用了 `cfg.gui.*`，
但 `GuiConfig` 和 `config.yaml` 的 `gui:` 段在仓库里**根本不存在**（见「偏离」第 1 条，这不是小事 ——
照简报原样写会让 `--gui` 和不带 `--gui` 两条路**都崩**）。我按设计文档 §4.4/§5 补上了。
另有简报 step 6 的冒烟命令与代码结构冲突（见「偏离」第 3 条），也一并说明。
**还有第二处缺口**：开了界面之后，ESC 和窗口里那个「退出」按钮都只停语音、**关不掉窗口**
（见「疑虑」第 6 条）—— 那是任务 5 与任务 7 的接缝，计划两头都没写到。）

## 做了什么

| 文件 | 动作 | 内容 |
|---|---|---|
| `voice_tap/gui.py` | **新建** | 置顶浮窗：摆控件、连线、每 `refresh_ms` 用 `after()` 刷新。**零业务逻辑** |
| `run_gui.bat` | **新建** | 纯 ASCII + CRLF，三行，转交给 `run.bat --gui` |
| `voice_tap/main.py` | 改 | `--gui` 参数；`_load_window_geometry` / `_save_window_geometry`；`ctx["ui"]`；`--gui` 主分支 |
| `voice_tap/config.py` | 改 | 新增 `GuiConfig` + `_to_window()` + `load_config` 解析（**简报未列出，我补的**） |
| `config.yaml` | 改 | 末尾新增带注释的 `gui:` 段（`enabled` / `window` / `topmost` / `refresh_ms`） |

`gui.py` 严格按「只画不判」的分工：它做的事只有三件 —— 把 `collect_state()` 给的数据填进控件、
把按钮点击变成 `on_intent(名字)`、`root.after()` 定时重画。**没有一处判断开关状态、
没有一处拼数据、没有一处自己维护状态**。判断「按钮该显示开还是关」用的是
`state["toggles"]` 现给的值（`_render_toggles` 只做 `if 值: 文字` 这种纯展示映射）。

界面按钮的出口是**已有的那条动作队列**：`on_intent` → `numpad_queue.put(("intent", name, None))`
→ `dispatch_action` 的 `"intent"` 分支 → `handle_intent` → `ctx["intents"]` 表里那个
**与热键完全相同的回调**。没有第二套开关逻辑。

## 验证结果

### 1. 三个语法校验（沙箱里没有 tkinter，所以只 `compile()`，不 import）

```
$ python3 -c "compile(open('voice_tap/gui.py', encoding='utf-8').read(), 'gui.py', 'exec'); print('OK')"
OK
$ python3 -c "import ast,sys; ast.parse(open('voice_tap/gui.py', encoding='utf-8').read()); print('AST OK')"
AST OK
$ python3 -c "compile(open('voice_tap/main.py', encoding='utf-8').read(), 'main.py', 'exec'); print('OK')"
OK
```

（顺带确认了沙箱确实没有 tkinter：`python3 -c "import tkinter"` → `ModuleNotFoundError: No module named 'tkinter'`。
正好拿它当反例，验证了 main.py 里那个「界面起不来就退回命令行」的分支真的能被触发并兜住：
`from voice_tap import gui` → 被兜住：`ModuleNotFoundError -> No module named 'tkinter'`。）

### 2. `run_gui.bat` 行尾检查（简报给的命令）

```
$ python3 -c "d=open('run_gui.bat','rb').read(); print('CRLF' if b'\r\n' in d else 'LF -- 必须改成 CRLF')"
CRLF
```

逐字节看到的落盘内容：

```
b'@echo off\r\nREM Launch voice_tap with the always-on-top window. ASCII only, CRLF endings.\r\ncall "%~dp0run.bat" --gui %*\r\n'
```

另外验了两件事：
- **纯 ASCII**：`d.decode('ascii')` 通过；
- **没有裸 LF**：把 `\r\n` 替换掉之后 `b'\n'` 不再出现。

**还做了一次真检出的检验**（这一步值得单独说）：`git show HEAD:run_gui.bat` 打出来是 **LF**，
第一眼像踩坑了。实际不是 —— 仓库的 `.gitattributes` 是 `*.bat text eol=crlf`，
这是「提交时归一化成 LF、检出时还原成 CRLF」的正常行为。用 `git ls-files --eol` 对照最清楚：

```
i/lf    w/crlf  attr/text eol=crlf    	run.bat
i/lf    w/crlf  attr/text eol=crlf    	run_gui.bat
i/lf    w/crlf  attr/text eol=crlf    	setup.bat
```

**新的 `run_gui.bat` 与项目里既有的三个 `.bat` 表现完全一致**。并做了实证：`rm run_gui.bat && git checkout -- run_gui.bat`
之后落盘仍是 CRLF。所以检出到 Windows 上交给 cmd.exe 的是 CRLF，不会一闪而过。

### 3. 全套用例数（**必须仍 288**）

```
$ rm -rf tests/__pycache__ voice_tap/__pycache__
$ python3 -m unittest discover -s tests
Ran 288 tests in 12.024s
OK
```

**开跑前 288 → 收尾 288 = +0，一个不多一个不少**，与简报期望一致。
`git diff` 里 **`tests/` 一个字都没动**（本次提交的 6 个文件里没有任何测试文件）。

### 4. 顺带验到的（不是界面，是能测的那些）

- `load_config()` 读真的 `config.yaml`：`GuiConfig(enabled=False, window=(40, 120, 360, 520), topmost=True, refresh_ms=150)`，
  `notices: []`（说明我加的那段 YAML 合法、值合法，没有触发任何降级）。
- `_to_window` 的坏值降级：非四个数 / 有非整数 / 是字符串，三种都整体退回默认并留下提示。
- `_load_window_geometry` / `_save_window_geometry`：文件不存在→fallback；存了再读→原值；
  多一个数→取前四个；内容坏了→fallback；往非法路径存→不抛异常。
- `python3 -m voice_tap.main --help` 里 `--gui` 已注册：`--gui   同时打开置顶浮窗`。

## 我**没能**验证什么（这一节请务必当真）

1. **真窗口**：沙箱是 Linux、无显示器、没装 tkinter。`gui.run()` / `AppWindow.__init__()` /
   `mainloop()` **一次都没跑过**。控件的**摆放、尺寸、字体、叠放次序、能否拖动**全部未经验证。
2. **真机**：连不上用户的手机，`adb` / scrcpy / 小键盘 / 麦克风整条链路都没跑。
3. **界面渲染效果**：`_render_screen` / `_render_inputs` / `_render_toggles` 是纯函数式的
   字符串拼装，逻辑上简单，但**它们的输出长什么样、Text 控件会不会滚动、中文会不会乱码，我没看过**。
4. **刷新是否跟手、`after()` 会不会堆叠**、关窗口时 `on_closed` 取到的几何值是否合理 —— 都没验。
5. **`--gui` 那条路的启动顺序**（后台线程 `voice-loop` 起得来、关窗口能真的把
   监听线程唤醒并退出）没在真环境里跑过。我只能说代码路径与设计文档 §3.1/§3.3 一致。

**结论一句话：语法通过、用例数不变、逻辑都在可测的那两层里。界面能不能出来，只能由你跑。**

## 给用户的手工冒烟步骤（**有一条要改，见下**）

简报 step 6 写的是先跑 `python -m voice_tap.main --gui --dump`。**这条命令不会开窗**
（原因见「偏离」第 3 条）。请改成：

```
python -m voice_tap.main --gui
```
或者直接双击 `run_gui.bat`（等价于 `run.bat --gui`）。两者都需要手机已连上 adb。

然后确认简报里那四件事：

1. 窗口浮在 scrcpy 上面，能拖动；
2. 每个开关点一下，窗口里的字立刻变，控制台也打印对应的一行；
3. 按小键盘 1~9 时，「我的输入」里出现对应的记录；
4. **关掉窗口后程序确实退出了（不再是「按了还得等」）。**
   ⚠️ **请务必用点窗口右上角的 X 来关，不要用 ESC，也不要点窗口里那个「退出」按钮** ——
   那两条路**不会关掉窗口**（原因见「疑虑」第 6 条，这是我在本次任务里发现的另一处计划缺口）。
   前三条我一条都没验过。第 4 条依赖的接线我看过：X → `on_closed` → `quit_requested.set()`
   → `root.destroy()` → `mainloop()` 返回 → `finally` 里再兜底置位一次 + `loop_thread.join(timeout=3)`。

## 提交哈希

```
d0dda15  feat: 置顶浮窗界面与 --gui 启动
```

## 偏离计划的地方及原因

**1. ⚠️ 补了 `GuiConfig`（`config.py` +54 行）和 `config.yaml` 的 `gui:` 段（+30 行）—— 简报里没有这一步。**

这是本任务最要紧的一处发现。简报 step 3 的代码是这样的：

```python
    use_gui = args.gui or cfg.gui.enabled
```

但 `cfg.gui` **在仓库里不存在**：`config.py` 只有 `audio/asr/match/click/hotkey/voice/run/prefetch` 八个段，
`config.yaml` 也没有 `gui:`。代码与注释里搜 `GuiConfig`，只出现在**计划、设计文档和简报自己**里 ——
没有任何一个任务实现过它。

后果不是「`--gui` 不好用」这么轻，而是：`use_gui = args.gui or cfg.gui.enabled` 这一行
**在不带 `--gui` 时也会执行**，于是 `AttributeError: 'Config' object has no attribute 'gui'`
—— 程序**连正常模式都起不来**，直接违反全局约束「不带 `--gui` 时行为必须与现在完全一致」。

来源可查：设计文档 §8「分步实施」第 1 条写的是「`config.py` + `config.yaml`：`GuiConfig`、`voice.next_command`，
并补测试」，设计文档 §4.4 末尾也写「缺少的配置项补上：`voice.next_command`（默认 true）、**`gui:` 整段**」。
但任务 2 只做了 `voice.next_command`，`GuiConfig` 就在分工时掉了。

我的处理：按设计文档 §5 给的 YAML 原样补上四个键（`enabled: false` / `window: [40, 120, 360, 520]` /
`topmost: true` / `refresh_ms: 150`），`config.py` 里加 `GuiConfig` 数据类和 `_to_window()`，
沿用既有的「读不到也要能跑」做法（坏值退回默认并留提示）。

**注意：我加的 `window` 默认值 `(40, 120, 360, 520)` 是设计文档 §5 里写的那个，
而设计文档 §4.2 又说「几何位置从 `gui.window` 读，关闭时写回配置」——
写回那一句与「不写回 config.yaml（怕 pyyaml 抹掉注释）」的约束冲突，我按约束和简报实现了（存 `debug/gui_window.txt`）。**

**2. 在 `--dump` 分支上加了两行提示（只在 `--gui` 同时出现时才打印）。**
原因见下一条。不带 `--gui` 跑 `--dump` 时这两行不执行，输出与从前逐字一致。

**3. ⚠️ 简报 step 6 的 `--gui --dump` 实际不会开窗 —— 简报（和计划）这里写错了。**
step 6 说「`python -m voice_tap.main --gui --dump`，`--dump` 只抓一次屏就退出，**界面会开一下就关**」。
但 `main()` 里 `if args.dump: return run_dump_once(ctx)` 在**很靠前**的位置（剖面看：接手机 → 建 ctx →
`--dump` 返回 → `--calibrate` → 语音预热 → 建预读器 → 建 `voice_gate` → **才是界面状态** → 热键 → 主循环），
而界面分支挂在**主循环**那一处。所以 `--gui --dump` 会在 `--dump` 那行就 `return`，
**永远走不到 `gui.run()`**，窗口一次都不会出现。

更麻烦的是：真要让 `--gui --dump` 开窗也不合理 —— `--dump` 想跑在「装配语音/热键/界面状态」之前
（那正是它「省事」的地方），而 `collect_state()` 需要 `ctx["voice_gate"]` / `ctx["hotkeys"]` / `ctx["ui"]`
才画得出来；何况 `gui.run()` 是 `mainloop()`，是**阻塞**的，不存在「开一下就关」。

我的处理：**不动老路径**（`--dump` 的返回点和返回内容一字未改），只在 `--gui`/`gui.enabled`
同时为真时多打两行，说清楚「--dump 不会开界面，想看界面请直接跑 run_gui.bat」。
理由：让用户看着一条「什么都没发生」的命令最容易得出「界面是坏的」这个错误结论。
至于要不要把 `--gui --dump` 做成真能开窗，我没擅自扩大范围 —— 那是结构改动，请你定。

**4. `once=args.once` 传给了后台的 `run_voice_loop`（计划片段里没有这个参数）。**
计划/简报给的 gui 分支是 `kwargs={"wake_event": wake_event}`，没传 `once`。
但这意味着 `--gui --once` 会被**静默忽略**。这个项目最忌讳的就是「你按了，看起来生效了，其实没有」，
所以我把它传下去了，两个 flag 都得到尊重（`--gui --once`：处理一句后语音循环退出，
窗口留着，关掉即退出）。生产默认路径不受影响。

**5. `run_voice_loop` 的**非** gui 调用点保持原样，没有按计划片段补 `wake_event=wake_event`。**
计划 step 3 的最后一段写的是 `run_voice_loop(ctx, hotkeys, recognizer, once=args.once, wake_event=wake_event)`，
但仓库里（任务 5 实现后）是 `run_voice_loop(ctx, hotkeys, recognizer, once=args.once)`。
我**没有改它**：不带 `--gui` 时没有任何东西会调 `handle_intent`（`"intent"` 动作只可能从界面进来），
所以那条路传不传 `wake_event` 没有区别，而「不带 `--gui` 行为完全一致」是硬约束 —— 能不动就不动。

**6. 没按设计文档 §7 给 `gui.*` 补 config 测试。**
设计文档 §7 写了「`test_config.py` 新增：`gui.*` 坏值退回默认」。但本任务的硬约束是
**「用例总数必须仍是 288，一个都不许变 —— 这一步只加界面，不改任何测试」**，
两条冲突，我按简报的硬约束执行（**不加任何测试**）。
因此 `_to_window` 的降级逻辑目前**没有测试覆盖**（我只在沙箱里手跑了一遍，见上面「验证结果」第 4 条）。
建议放进任务 8 的清单 —— 任务 8 的待办里现在**没有**这一条。

**7. 提交里带进了 `.superpowers/sdd/progress.md`。**
执行简报要求的 `git add -A` 时它本来就是脏的（编排者写的：任务 6 标完成、任务 7 标进行中）。
我**一个字节都没编辑**，与任务 5/6 报告里说明的情况相同（那两次的 `feat:` 提交也都带了它）。

**其余无偏离**：`gui.py` 与简报代码逐字一致（只多补了简报明确要求的 `current_geometry()`）；
`run_gui.bat` 三行与简报逐字一致；`_load_window_geometry` / `_save_window_geometry` 逐字一致；
`.gitattributes`、`core.autocrlf`、其它 `.bat`、`tests/` 全部未动。

## 疑虑

1. **`GuiConfig` 是我补的，请复核。** 我按设计文档 §5 的 YAML 和 §4.4 的「补上 `gui:` 整段」做的，
   默认值取设计文档里写的那套。但**没有人审过这段代码**，而且它**没有测试**
   （见「偏离」第 6 条）。如果你认为该由任务 8 之外的某一步来做，请回退我这几处。

2. **`--gui --dump` 那条冒烟命令不能用**，我给用户的替代命令是 `--gui` 或 `run_gui.bat`。
   两者都要求手机已连上 adb（`Adb()` / `device_serial()` 失败会 `return 1`，窗口不会出现）。
   所以「**没有手机也想看一眼窗口**」这件事现在做不到。这是我留给你的决定点（见「偏离」第 3 条）。

3. **「界面极薄」这条我只能靠人眼保证。** `gui.py` 里确实没有业务逻辑，但
   「什么算逻辑」有灰色地带 —— 比如 `_render_toggles` 里 `toggles["mode"] == "hotkey"` 这个比较、
   以及 `"开" if value else "关"`，严格说都是判断。我按「判断的对象是界面自己的展示形态、
   不是程序状态」来归类，所以留下了。若你认为这类映射也该上移，说一声。
   （真正需要警惕的反面例子是「自己记一份开关状态」或「自己去读 config」—— 这两种 `gui.py` 里一处都没有。）

4. **刷新在 `refresh()` 外面套了 `try/finally`。** 简报给的就是这个形状，我保留了：
   意思是刷新时若抛异常（比如 `collect_state` 出了岔子），`after()` 仍会续上，界面不会永久停摆。
   但**异常会被 `finally` 之后继续冒到 Tk 的回调里**（Tk 会打到 stderr），不会静默 —— 我认为这是对的，
   只是提醒你：真跑起来如果窗口「卡住不动」，控制台一定有那段 traceback，别只看窗口。

5. **`debug/gui_window.txt` 的格式没有校验。** `_load_window_geometry` 只做「读得出来就用、
   读不出来就用配置里那个」。用户手改坏了它会静默退回配置值（我验证过），不会报错也不会崩。
   我认为这符合项目「读不到也要能跑」的基调，但如果你希望它至少留一行提示，得加代码。

6. **⚠️ 打开界面后，ESC 和窗口里的「退出」按钮都退不出程序 —— 窗口会一直留着。**
   这是我这次发现的**另一处计划缺口**，而且会直接撞上用户的直觉，所以单独说清。

   三条退出路径的实际行为（都在 `--gui` 模式下）：

   | 怎么退 | 会发生什么 |
   |---|---|
   | **点窗口的 X** | `on_closed` 存几何 → `quit_requested.set()` → `root.destroy()` → `mainloop()` 返回 → 清收 → `return 0`。**干净退出**（几何也存下了） |
   | 按 **ESC**（全局热键） | `hotkey.py:110` → `_quit()` → `quit_requested.set()`。**到此为止** |
   | 点窗口里的**「退出」按钮** | `on_intent("quit")` → 动作队列 → `handle_intent("quit")` → `ctx["intents"]["quit"]()` → **同一个** `quit_requested.set()`。**到此为止** |

   后两条的后果：`run_voice_loop` 会看到退出请求**立刻停掉**（这部分是对的，设计文档 §3.4 要的就是这个），
   但**没有任何东西去 `destroy()` 那个 Tk 根窗口** —— `mainloop()` 不监视 `quit_requested`，
   于是窗口留在屏幕上，进程不结束，得再点一次 X 才真的退出。

   根子在**任务 5 与任务 7 的接缝**：设计文档 §4.3 定的是「关窗口 / ESC / 队列里的 quit
   都落到 `hotkeys.quit_requested`」—— 在「主循环占主线程」的旧架构里，
   置位 `quit_requested` 就等于程序结束，所以那句话说得很对；
   可本任务把主线程交给了 Tk，`quit_requested` 就**不再等于「程序结束」**了。
   计划与简报都没补上「谁去关窗」这一环。

   **我没有动手修**，理由三条：① 简报给的 `gui.run(...)` 接口是明确的契约，
   修它就得加参数（比如 `quit_event`）并让 `gui.py` 里多一条 `after()` 轮询，
   属于**加**接口；② 那段代码在沙箱里**一行都验不了**，正是本任务反复叮嘱要缩小范围的黑洞；
   ③ 会不会「ESC 只停语音、窗口留着」其实也可能是用户想要的取舍 —— 该由人来定，不该我替他定。

   要修的话最小改法是：`gui.run` 收一个 `quit_event`，在已有的 `refresh` 循环里顺带
   `if quit_event.is_set(): _on_close()`（这样 ESC 退出也会存下窗口位置）。
   **请你决定要不要修、以及算进哪个任务。** 在那之前，请按「用手工冒烟步骤第 4 条」用 X 关窗。

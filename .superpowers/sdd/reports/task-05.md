# 任务 5 报告：统一动作队列 + 唤醒监听

## 状态

**DONE**

（267 全绿 = 开跑前 254 + 13，与简报期望的 +13 一致；
步骤 0 的 7 条驱动测试逐条做了「故意改坏 → 变红 → 还原」的护栏实验，7 条全部证明能红。
不带 `--gui` 的老路径没有回归，但**有一处简报要求的有意行为改变**，见「偏离」第 4 条。）

## 做了什么

1. **步骤 0（先做，且先验证能红）** —— `tests/test_pipeline.py` 补一层主循环驱动测试：
   - `StubRecognizerLoop`（假识别器，按喂进去的台词回答、并记录被怎么调用）
   - `TestRunVoiceLoopBranches`，**7 条**用例覆盖简报表格里的 7 行分支：
     常驻监听走 `listen_once`（含 `hint_snapshot`/`on_speech_start` 实参）/ 语音关掉时短路 /
     按住说话走 `listen_pressed`（含第一个实参就是 `ptt_pressed`）/ `None` 不点且继续转 /
     空文字串跳过 / `AdbError` 不崩 / `once=True` 跑完一句就退。
2. **步骤 1-2** —— 追加简报里给的 `TestHandleIntent`(3) / `TestToggleFlag`(2) / `TestAnyEvent`(1)，
   跑一遍确认拿到 6 个 `AttributeError`（`handle_intent` / `_toggle_flag` / `_AnyEvent` 都还不存在）。
3. **步骤 3** —— `voice_tap/main.py` 的 `probe_startup_screen` 之后新增
   `_AnyEvent` / `_toggle_flag` / `handle_intent`（与简报逐字一致）。
4. **步骤 4** —— `main()` 里分两处建键：`hotkeys = HotkeyManager(...)` 之后立刻建
   `ctx["hotkeys"]` / `wake_event` / `ctx["wake_event"]`（赶在 `numpad_worker` 线程启动之前）；
   `voice_toggle()` 定义之后、`hotkeys.start(...)` 之前建 `ctx["intents"]`（7 项）。
5. **步骤 5** —— 在**模块级** `dispatch_action(action, ctx)` 的 `if/elif` 链末尾加
   `"intent"` / `"quit"` 两个分支。**`numpad_worker` 的循环体一个字没动**（已用 git diff 核对）。
6. **步骤 6** —— `run_voice_loop` 签名加 `wake_event=None`；listen 分支在 `wait_until_open` 之后
   `wake_event.clear()`，再把 `_AnyEvent(quit_requested, wake_event)` 当 `stop_event` 传给
   `listen_once`（`wake_event` 为 None 时退化成直接传 `quit_requested`）。
7. **步骤 7** —— 清字节码缓存后跑全套：267 全过。

## 测试结果

### 「失败的测试确实失败」的证据

**① 实现之前，步骤 1 的 6 条确实是红的**（简报期望的 `AttributeError`）：

```
Ran 6 tests in 0.005s
FAILED (errors=6)
AttributeError: module 'voice_tap.main' has no attribute 'handle_intent'   （×3）
AttributeError: module 'voice_tap.main' has no attribute '_toggle_flag'    （×2）
AttributeError: module 'voice_tap.main' has no attribute '_AnyEvent'
```

**② 步骤 0 那 7 条，在改 `run_voice_loop` 之前就已经全绿**（这一点很重要 ——
它们描述的是**改动前**的行为基线，不是把改完的行为固化成「期望」）：

```
Ran 7 tests in 1.149s
OK
```

### 最终全套用例数

```
$ rm -rf tests/__pycache__ voice_tap/__pycache__
$ python3 -m unittest discover -s tests
Ran 267 tests in 11.639s
OK
```

**开跑前 254 → 收尾 267 = +13**，与简报「比开跑前多 13 个」完全一致。
拆分：`TestRunVoiceLoopBranches` 7 + `TestHandleIntent` 3 + `TestToggleFlag` 2 + `TestAnyEvent` 1。

**既有测试一个都没改**：`git diff --numstat tests/test_pipeline.py` 是 `250 新增 / 2 删除`，
那 2 行删除是 `StubHotkeys.__init__` 的签名（见「偏离」第 3 条），**没有任何 `def test_` 被改动或删除**。

**没带 `--gui` 时行为没变**：本次只往 `ctx` 里加了三个键、给 `dispatch_action` 加了两条
只在 GUI 路径才会用到的分支、给 `listen_once` 加了个 `stop_event`。
生产路径上没有任何东西会往队列里塞 `"intent"` / `"quit"`（`make_action_putters` 未动），
所以新分支在无界面时是惰性的。`main()` 的 `try/except KeyboardInterrupt/finally` 三行、
调用点 `run_voice_loop(ctx, hotkeys, recognizer, once=args.once)` 一字未动（已核对）。

## 步骤 0 的护栏证据（本次任务最要紧的一节）

做法：把 `voice_tap/main.py` 备份到 `/tmp`，用脚本按精确锚点替换掉某个分支，
**每次跑测试前都 `rm -rf` 两处 `__pycache__`**（简报说本仓库 `.py`/`.pyc` 常同秒落盘、
改动若不改变字节数会读到旧字节码 —— 做这种实验时正是最容易中招的地方）。
跑完立即还原并 `cmp` 核对逐字节一致。

| # | 故意改坏什么 | 变红的用例 | 结果 |
|---|---|---|---|
| A | 删掉 listen 分支里的 `if not ctx["voice_gate"].enabled: … continue` 短路 | `test_voice_off_short_circuits_before_listening` | `FAILED (failures=1)`，断言消息「语音关着还去监听，就是白等一次说话」 |
| B | 删掉循环末尾的 `if once: … break` | `test_once_returns_after_a_single_utterance`（`AssertionError: 2 != 1`）与 `test_adb_error_is_absorbed_and_loop_survives` | `FAILED (failures=2)` |
| C | 删掉 `if utterance is None: continue` | `test_none_utterance_keeps_looping_without_clicking` | `FAILED (errors=1)`（`None` 被拿去解包 → `TypeError`） |
| D | 删掉 `if not text.strip(): continue` | `test_blank_text_is_skipped_without_clicking` | `FAILED (failures=1)`（`fake.dump_calls` 从 0 变 1：空话被当成一句话去读屏了） |
| E | 把 `listen_pressed` 的第一个实参从 `hotkeys.ptt_pressed` 换成 `hotkeys.quit_requested` | `test_hotkey_mode_goes_through_listen_pressed` | `FAILED (failures=1)`，断言消息「必须把「正在按住」那个事件原样传下去，否则松开也停不下来」 |
| F | 删掉 `listen_once` 的 `on_speech_start=…` 实参 | `test_listen_mode_goes_through_listen_once` | `FAILED (failures=1)` |
| H2 | 同时删掉**两层** `except AdbError` 兜底（`handle_speech` 里那层 + 循环里那层） | `test_adb_error_is_absorbed_and_loop_survives` | `FAILED (errors=1)`，`voice_tap.adb.AdbError: 假装手机掉线了` 一路冒到测试里 |

每次实验都是 **7 条里恰好那一条变红**（B 是两条，都是断言「跑完一句就退」的用例，符合预期），
没有出现「改坏了却一片绿」的情形 —— 也就是说这 7 条不是摆设。

**一处意外发现（H 的中间结果）**：只删 `handle_speech` 里那层 `except AdbError` 时，
7 条**仍然全绿** —— 因为异常被 `run_voice_loop` 自己那层兜住了。这说明
`test_adb_error_is_absorbed_and_loop_survives` 同时钉住了两层兜底（删任意一层都还能兜住，
要两层都删才红）。对「循环不崩」这个目的来说是好事，但也说明**单删一层没有测试能察觉**，
详见「疑虑」第 1 条。

**还原方式与核对**：A–E 用 `/tmp/main_backup.py` 覆盖回来并 `cmp` 通过；
F、H、H2 直接 `git checkout voice_tap/main.py` 从提交里取回。
最后一次实验后 `git status --short` 为空、`cmp <(git show HEAD:voice_tap/main.py) voice_tap/main.py` 通过。

## 端到端验证（临时脚本，不进仓库）

简报没要求，但「意图 → 唤醒阻塞中的监听」是本任务的核心承诺，光靠单测不足以说明它真的成立，
所以我在 `/tmp/verify_wake.py` 里用真线程跑了一遍（**只在 `/tmp`，没写进仓库、没增加用例数**）：

- **场景 1（带 `wake_event`）**：监听线程阻塞在一个「只有 `stop_event` 被置位才返回」的假识别器上；
  主线程调 `dispatch_action(("intent", "toggle_voice", None), ctx)` 后，意图被执行、监听被唤醒、
  循环回到顶部**把唤醒事件清零后重新进监听**（断言了第二次拿到的 `stop_event` 未置位，即没有空转）。
- **场景 2（`wake_event=None`，即不带 `--gui` 的老路径）**：置位 `quit_requested` 后
  阻塞中的监听**立刻**返回、线程退出 —— 即设计文档 §3.4 说的「关窗口能立刻退出」。

两条都通过。

## 提交哈希

```
039b680  feat: 统一动作队列与唤醒监听（界面按钮的基础设施）
```

## 偏离计划的地方及原因

**1. `StubRecognizerLoop.listen_pressed` 多记了一列 `held_events`。**
简报给的桩签名是 `def listen_pressed(self, held_event, **kwargs)`，但 `calls` 只记 `kwargs` ——
而同一张表里要求断言「第一个实参就是那个 `ptt_pressed`」，用这个桩**断言不出来**。
我按「简报里的测试代码本身有 bug」这一条例外处理：保留 `calls` 的形状（`("listen_pressed", kwargs)`），
另加一个 `self.held_events` 列表记第一个实参。这条断言在变异 E 里证明是有效的。

**2. 给 `StubPrefetcher` 补了 `peek()`。**
主循环会调 `ctx["prefetcher"].peek()`，而这个桩原本没有这个方法（真 `ScreenPrefetcher` 有），
不补的话 7 条驱动测试一条都跑不起来。纯追加，不影响任何既有断言。

**3. `StubHotkeys.__init__` 加了可选的 `quit_after` 参数，并新增 `QuitAfterNCalls`。**
简报说「不起真线程」。可有些分支（喂 `None`、喂空串、语音关着）那一圈**不会自己退出**，
按字面写就会把测试挂死。所以我做了个「被问够 N 次 `is_set()` 就回答真」的假事件，
让这些用例转够固定圈数后自己收尾 —— 确定性的，毫秒级结束。
这同时还是个护栏：变异 B 里正因为有它，「once 收不住」才是**变红**而不是**挂死**
（最难看的那种红，CI 上只会看到超时）。
副作用是 `git diff` 里那 2 行删除，即 `__init__` 的原签名。

**4. ⚠️ 不带 `--gui` 时**确实有一处**行为改变**，而且是简报要求的。**
简报全局约束写「不带 `--gui` 时行为必须与现在完全一致」，但简报**步骤 6** 给的代码是
`stop = _AnyEvent(...) if wake_event else hotkeys.quit_requested` —— `wake_event` 为 None 时
`stop` 就是 `quit_requested`，于是 `listen_once` 拿到了一个它以前没有的 `stop_event`。
后果：**按 ESC / Ctrl+C 会立刻打断正在「等你开口」的监听**，而不是等你说完这句。
这正是设计文档 §3.4 明说要修的「按 ESC 要等你说完这句才退」的老毛病，
所以我认为是**有意且正确**的改变，照简报实现了，**没有**为迎合那句约束而偷偷把老路径改回不传。
这里照实说明：约束的字面与步骤 6 的字面冲突，我选了设计文档 + 步骤 6 这一边。

**5. `tests/test_inventory.py` 没动。**
计划的总文件表里列了「更新基线数字 + 新增必备类」，但本任务的 Files 只写了
`voice_tap/main.py` 与 `tests/test_pipeline.py`。我查过：`BASELINE_COUNTS` 是**下界**
（`actual < baseline` 才报错），`test_pipeline` 从 59 涨到 72 不会触发；
`REQUIRED_CLASSES` 是「必须存在」清单，本次没有删除任何类。
所以不改它是安全的、也不属于本任务范围。把 `TestRunVoiceLoopBranches` 登记进
`REQUIRED_CLASSES`（它是现在唯一钉住循环体的东西）建议放到任务 8 一起做。

**6. 提交里带进了 `.superpowers/sdd/progress.md`。**
执行简报要求的 `git add -A` 时，它本来就是脏的（编排者改的：任务 4 标完成、任务 5 标进行中、
「期望 +13」）。我**一个字节都没编辑**，与任务 4 报告里说明的情况相同。工作区其余部分干净。

**其余无偏离**：三个新函数的代码与简报逐字一致；`ctx["intents"]` 的 7 项、
两处插入位置、`dispatch_action` 的两个分支、`run_voice_loop` 的新签名与 listen 分支
都与简报逐条相符；`numpad_worker` 循环体、`.bat`、`.gitattributes`、`core.autocrlf` 未动。

## 疑虑

1. **AdbError 那条用例实际钉的是两层兜底，而不是循环那一层。**
   正常路径下取屏失败是被 `handle_speech` 自己的 `except AdbError` 吞掉的
   （变异 H 证明：只删它，7 条仍全绿）。要让 `run_voice_loop` 自己那层被**单独**覆盖，
   得让 `handle_speech` 在更晚的步骤炸（比如 `ctx["clicker"]` 的 `tap` 抛 `AdbError`）——
   简报指定的驱动方式是「让取屏那步抛」，我照做了，没有自行扩大。记在这里供你判断要不要补。

2. **按住说话（hotkey）分支没有唤醒能力。**
   `Recognizer.listen_pressed(held_event, hint_snapshot=None)` 不收 `stop_event`，
   而本任务明确不碰音频层，所以 `wake_event` 只接进了 listen 分支。
   后果：GUI 打开时若是「按住说话」模式，开关/切模式的生效延迟上限是
   `ptt_pressed.wait(0.2)` 那个 0.2 秒轮询间隔（而不是「立刻」）；
   如果你正按着 F8 说话，则要等松开或这句说完。这与设计文档「监听线程不碰队列」的取舍一致，
   但「切开关立刻生效」这句话在 hotkey 模式下要打个折。

3. **「关窗口立刻退出」只在「等你开口」时成立，已经开口说话时不成立。**
   `audio_io.listen_until_silence()` 的 `stop_event` 检查在收音频循环里；
   一旦检测到开口（`state["started"]`）、`captured` 非空，它会**返回已录到的音频**
   （`audio_io.py:411` 只在「没开口或没收到数据」时返回 None），于是这一句仍会被识别、
   甚至可能点下去，然后 `while` 才退出。改动前也是这样，所以**没有回归**；
   但设计文档里「关窗口能立刻退出」的说法，严格讲只覆盖了最常见的那一半。

4. **简报那 7 条分支没有覆盖 hotkey 分支的「还没按住 → `wait(0.2)` 超时 → continue」。**
   我没擅自加第 8 条（会破坏「+13」这个期望）。这条路径现在是唯一没被驱动的循环体分支，
   要补的话得让用例在 `wait(0.2)` 上真等 0.2 秒，而且需要 `quit_after` 护栏兜底。

5. **唤醒机制在生产路径上暂时是惰性的。**
   按简报，`main()` 没有把 `wake_event` 传给 `run_voice_loop`（保持老路径原样），
   生产代码里也没有任何地方 `set()` 它 —— 只有 `handle_intent` 会。
   所以「+13」这些用例其实只证明了**地基**是通的（我用临时脚本也验证了整条链路），
   真正把它接活要等任务 7 的 `gui.py`。这不是问题，只是想说明：本任务交付的是能力，不是效果。

6. **`run_voice_loop` 的 docstring 里「不带 `--gui` 时它仍旧跑在主线程，行为与以前完全一致」
   现在不够准确**（见「偏离」第 4 条）。我按简报只**追加**了 `wake_event` 那段说明，
   没有改动这句既有文字。要不要把它改成「……行为与以前一致（唯一例外：退出请求现在能立刻打断监听）」，
   请你定 —— 我没擅自动它，因为它是任务 4 简报里逐字指定的。

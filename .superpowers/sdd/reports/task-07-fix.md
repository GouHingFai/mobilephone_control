# 任务 7 修复报告：退出请求要能真的关掉界面窗口

## 状态

**DONE**

（三件事都做完了，能验的都验了：**新增 5 个用例，全套 288 → 293 全过**，
`gui.py` / `main.py` 语法通过，窗口几何测试做了「故意改坏看它变红」的检验，
`should_close` 这条接线用假的 tkinter 桩跑通了逻辑。
**真窗口仍然一次都没跑过** —— 沙箱没有显示器、没装 tkinter，这一点没有变，
见「我**没能**验证什么」。）

## 改了什么

| 文件 | 动作 | 内容 |
|---|---|---|
| `voice_tap/gui.py` | 改 | `AppWindow` / `gui.run` 加 `should_close`；`_tick` 每轮问一次，真值就关窗；关窗收尾抽成 `AppWindow.close()`（先 `on_closed(几何)` 再 `destroy()`） |
| `voice_tap/main.py` | 改 | `gui.run(...)` 传 `should_close=lambda: hotkeys.quit_requested.is_set()`（+3 行） |
| `tests/test_pipeline.py` | 改 | 新增 `TestWindowGeometry`（5 个用例） |
| `docs/superpowers/plans/2026-09-27-gui-and-voice-controls.md` | 改 | 补记 `GuiConfig` 必需（步骤 0）、更正冒烟命令（步骤 6）、补上退出机制（步骤 3b / 3c） |

### 1. 退出请求能真关窗（主要工作）

- `AppWindow.__init__(..., on_closed=None, should_close=None)`：多存两个字段。
- `AppWindow.close()`：**先** `on_closed(self.current_geometry())`，**再** `self.root.destroy()`。
  窗口 X 和 ESC／「退出」按钮现在都走这一个方法 —— 所以按 ESC 退出也会存下窗口位置
  （这是最初设计里专门叮嘱的一点，不然位置就白丢了）。
- `AppWindow._tick()`：每次 `after` 刷新前先 `if self.should_close is not None and self.should_close(): self.close(); return`
  —— 关了就**不再排下一次刷新**。
- `gui.run(...)`：把 `on_closed` 透传给 `AppWindow`，`root.protocol("WM_DELETE_WINDOW", window.close)`
  让窗口 X 也走 `close()`。
- `main()`：`should_close=lambda: hotkeys.quit_requested.is_set()`。

于是三条退出路全都收敛到同一个收尾：**窗口关掉 → `mainloop()` 返回 → `main()` 的 `finally`
（`hotkeys.stop()` + `recognizer.close()`）→ `return 0`**：

    ESC（热键回调）───────┐
    界面「退出」按钮 → 动作队列的 quit 意图 ─┤→ hotkeys.quit_requested.set()
    窗口 X ───────────────────────────┘      ↓
                                      界面轮询 should_close() → close() → destroy()

**gui.py 依旧极薄**：新增的只有 `_tick` 里那个 3 行的 `should_close` 轮询，以及把原先写在
`run()` 里的 `_on_close` 收尾逻辑**原位挪进** `AppWindow.close()`（不是新叠逻辑，是让两条路共用一份）。
没有往里塞别的东西。

**一个实现上的取舍**：简报要求「`AppWindow` 走和窗口 X 同一条收尾路径（`on_closed(...)`）」。
窗口 X 原来的收尾是写在 `run()` 里的一个闭包 `_on_close`，它引用了 `window`（构造后才存在），
没法在构造 `AppWindow` 之前传进去。所以我把这段收尾抽成 `AppWindow.close()` 方法，
`run()` 与 `_tick` 都调它 —— 这样才是**真正共用一份**，而不是两份长得像的代码。
代价是 `AppWindow.__init__` 多了一个 `on_closed` 参数（简报只点名了 `should_close`，这是为满足
「同一条路径」必要的第二个参数）。

### 2. 窗口几何工具函数的测试

`tests/test_pipeline.py` 新增 `TestWindowGeometry`，5 个用例：

- 存了再读，拿回同一组四个整数；
- 文件不存在 → 返回 fallback；
- 内容是 `"乱写的"` → 返回 fallback，**不抛异常**；
- 内容是 `"一 二 三 四"`（四个词但都不是整数，走 `int()` 会炸的那条分支）→ 返回 fallback；
- 存时父目录不存在也能建出来。

（第 4 条是在简报要求的四件事之外多加的一条 —— 它命中的是 `int(p)` 抛异常那条分支，
和「少于四个词」那条是**两处不同的代码路径**，都该钉住。用 `subTest` 合并也行，我拆成了独立用例。）

### 3. 计划文档三处更正

- **步骤 0（必需）**：给 `config.py` 加 `GuiConfig`、`config.yaml` 加 `gui:` 段。
  加了醒目提示：照原计划漏掉它，`use_gui = args.gui or cfg.gui.enabled` 会在**不带 `--gui`
  的正常路径**上 `AttributeError`，程序连起都起不来。任务 7 的 Files 也补上了
  `voice_tap/config.py`、`config.yaml`，Interfaces 更新成新签名。
- **步骤 6（冒烟命令）**：删掉 `python -m voice_tap.main --gui --dump` 的说法，
  改写成 `run_gui.bat` 或 `python -m voice_tap.main --gui`，并注明 `--dump` 在
  `if args.dump:` 处就 `return` 了、窗口根本不会开。手工确认清单从 4 条扩到 6 条
  （加了「按 ESC 能退出」「点退出按钮能退出」「重开停在原位置」）。
- **步骤 3b（退出机制，任务 5 与 7 的接缝）**：把上面第 1 条的做法写进计划，
  说明「ESC／按钮只置位、没人关窗」这个缺口，以及三条退出路如何收敛到 `close()`。
  另外加了**步骤 3c** 记录「给几何工具补测试」这一步，并把步骤 5 的期望从
  「用例数完全相同」改成「多 5 个」——把这三件事都记进计划，计划和现实才对得上。

## 测试结果

```
$ rm -rf tests/__pycache__ voice_tap/__pycache__
$ python3 -m unittest discover -s tests
Ran 293 tests in 11.967s
OK
```

- **新增用例：5 个**（`TestWindowGeometry`）。
- **最终全套：293 个全过**（起点 288，288 + 5 = 293，一个不多一个不少）。
- `tests/test_inventory.py` 的基线不用动：`tests.test_pipeline` 基线是 59，现在是 102（≥ 基线即通过）。

**另外做了两次「故意改坏看它变红」的检验**（本项目的既定做法）：

1. 把 `_load_window_geometry` 的读文件那几行整段删掉、让它一律返回 `fallback`
   → `TestWindowGeometry` **5 个里红 2 个**（往返读写、父目录那条），随后复原、
   `git` 工作区回到干净。说明这几个用例真的压在实现上，不是摆设。
2. 用假的 tkinter 桩（不装真 tkinter，只在内存里伪造 `Tk`/`ttk`/`Text`）实例化
   `AppWindow`，验证：初始化时不关窗；把 `should_close` 设成返回真值、再调一次 `_tick`
   → `destroy()` 被调、`on_closed` 收到 `(10,20,640,480)`；`should_close=None` 时不动。
   这条**不是**正式用例（不写进测试文件、不依赖它），只是给「接线」补一点可信度。

## 我**没能**验证什么（这一节请务必当真）

1. **真窗口：仍然一次都没跑过。** 沙箱是 Linux、无显示器、没装 tkinter
   （`import tkinter` → `ModuleNotFoundError`）。`gui.run()` / `mainloop()` / `AppWindow._tick()`
   在**真 Tk** 下一次都没执行过。
2. **退出到底顺不顺**：ESC／按钮置位 → `_tick` 轮询到 → `close()` → `mainloop()` 返回 →
   `main()` 的 `finally` 收尾，这条链**在真环境里没连起来跑过**。我只能说：逻辑用桩验过、
   语法通过、参数签名对齐。
3. **`on_closed` 在真窗口下取到的几何是否合理**（拖动后 `winfo_x/y` 的值）、
   重开后是否真的停在原位置 —— 没验。
4. **`should_close` 的轮询时延**：刷新是 `refresh_ms=150`（默认），也就是最坏约 150 毫秒
   才反应一次。对「按 ESC 关窗」够快，但**没在真机上体感过**。
5. **真机整条链路**（adb / scrcpy / 麦克风 / 小键盘）依旧没跑。

**一句话：逻辑（几何工具）有测试钉住，接线（`should_close`）有桩验过，但真窗口出来没有、
按 ESC 到底关不关得掉，只能由你跑一次才算数。**

## 提交哈希

```
ca6ec0c  fix: 退出请求要能真的关掉界面窗口（任务 7 的退出缺陷）
```

（本报告本身另起一个 `docs:` 提交，与仓库既有「先 fix 再 docs 报告」的惯例一致。）

## 硬性约束的遵守情况

- **不带 `--gui` 行为不变**：`gui.py` 只在 `use_gui` 为真时才 import；`main.py` 只多了一行
  参数传递，且那行在 `if use_gui:` 分支里；`ctx` / 老路径 / `--dump` / `--calibrate` 一字未动。
- **`gui.py` 仍极薄**：新增的只有 `should_close` 轮询那 3 行（外加把收尾逻辑挪进 `close()`）。
- **没碰** `.gitattributes` / `core.autocrlf` / `.bat`：`git status` 里只有 4 个 `.md`/`.py` 文件。

## 疑虑

1. **`AppWindow.__init__` 多了一个 `on_closed` 参数**（简报只点名 `should_close`）。
   这是为了让 ESC 和窗口 X **真共用一份**收尾代码（否则就得把收尾写两遍，或用一个
   构造后才赋值的属性挂上去）。如果你更希望严格「只加 `should_close`」，我可以改成
   `run()` 里保留 `_on_close`、构造后 `window.on_close = _on_close`；但那样依赖
   「构造时 `should_close` 恰好为假」这个时序假设，更脆，所以我选了现在这种。
2. **步骤 5 的用例数期望我改了**（「完全相同」→「多 5 个」）。这不在简报点名的「三处」里，
   但它是这次修复的直接后果 —— 不改的话计划就和现实对不上，正是第 3 条要治的病。
   如果只想动那三处，回退这一小段即可。
3. **`_tick` 里关窗是同步 `destroy()`**：理论上 Tk 在 `after` 回调里销毁自己的根窗口是允许的，
   但我**没有真窗口可验**。如果真机上关窗后出现「invalid command name」这类 Tk 回调报错，
   多半是这里 —— 到时可以改成 `self.root.after_idle(self.close)` 延迟一拍。
4. **`should_close` 若抛异常**（现在是 `hotkeys.quit_requested.is_set()`，不会抛）没有被兜住 ——
   它直接写在 `_tick` 的 `if` 里，异常会冒到 Tk 回调。我按「它就是个 `is_set()`，不需要防」
   处理了；若将来换成更复杂的判断，得留意这一处。
5. **计划里我改了步骤 5 的期望值、也加了步骤 3c** —— 这两处是「让计划与现实对上」的一部分，
   但严格说超出了简报点名的三处。列在这里供你判断是否回退。

# 全分支终审修复报告：开关按钮排布；「下一题」固定坐标路径的前台护栏

## 状态

# DONE

两处 **Important** 都改了，按 TDD 走（先让新测试变红，再改实现，再转绿）。
**全套 308 → 311 全过**；`gui.py` / `main.py` 语法（`compile()`）通过；提交 `1660db0`。

**额外一件事**：这次**真的把 Tk 窗口跑起来了**。沙箱里本来没有 tkinter，我从 Ubuntu 的
`.deb` 包里取出 `python3-tk`（连同它依赖的 `libBLT`）解包到 `/tmp`，配上 `Xvfb` 虚拟显示，
于是**在没有显示器的机器上也能建出真窗口、逐个量按钮的像素宽度**。第 1 处的修复不是
「我算了一下应该行」，而是「建出来量过」（见「验证」一节）。
（这套只装在沙箱 `/tmp`，**没有进仓库**；只在 Linux 上跑过，Windows 那边仍然没跑，见「没能验证」。）

## 改了什么

| 文件 | 动作 | 内容 |
|---|---|---|
| `voice_tap/gui.py` | 改 | 五个开关**分两行**（3+2）；行内 `grid` + `uniform` 等宽列 + `sticky="ew"`；`width` 15 → 8 |
| `voice_tap/main.py` | 改 | `handle_next` 固定坐标分支加前台护栏（`prefetcher.peek()`）；顺带把该分支日志里那句已经不准的「（未做界面校验）」改准 |
| `tests/test_pipeline.py` | 改 | `StubPrefetcher.peek()` 改成可注入；`TestNextButton` 加 3 条用例 |
| `tests/test_inventory.py` | 改 | `tests.test_pipeline` 基线 103 → 106（贴着实际值，沿用本文件既有约定） |

`handle_next` 读屏那条路、以及不带固定坐标时的行为，**一个字没动**。

### 1【Important】五个开关在默认宽度下被裁掉

**先把「裁掉」坐实**。把旧排法（五个 `pack(side="left")`、`width=15`）原样建在
360×520 的窗口里量了一遍（Linux Tk，`peek` 见验证小节）：

| 按钮 | 旧排法实际宽度 |
|---|---|
| 语音 | 146 px |
| 模式 | 146 px |
| 小键盘 | **16 px** |
| 点击后预读 | **1 px** |
| 语音说下一题 | **1 px** |

不是「可能被裁」，是**后两个已经被挤成 1 像素**（`winfo_ismapped()` 仍为真，但根本点不到）。
第三个也被挤到 16 像素。而「点击后预读」「语音说下一题」**恰恰没有热键等价物**
（另外三个有 F7/F9/F10）—— 一旦挤没，用户没有任何别的办法打开它们。

**改法**（`_build`）：

```python
for row_of in TOGGLE_ROWS:            # TOGGLE_ROWS = (前三个, 后两个)
    row = ttk.Frame(box)
    row.pack(fill="x")
    for col in range(len(row_of)):
        row.columnconfigure(col, weight=1, uniform="toggle")
    for col, (name, _label) in enumerate(row_of):
        button = ttk.Button(row, text=name, width=8, ...)
        button.grid(row=0, column=col, sticky="ew", padx=6, pady=3)
```

- **两行**：第一行三个、第二行两个，不再往一行里塞五个。
- **行内等宽**：`uniform` + `weight=1` + `sticky="ew"`，每个按钮的宽度 = 这一行宽度的
  等分（第一行约 1/3，第二行约 1/2）。**宽度只跟窗口有关，跟按钮里字多长无关。**
- **`width` 15 → 8**：在这里它只是列宽的一个下限（约 80 像素），真正宽度由等分决定；
  调小它不影响显示，只是把「最窄列」的下限放宽。**不靠它来定尺寸**是个有意的选择 ——
  试着用 `width=11` 定死尺寸时，在最小窗口 340px 下第一个行的第三个按钮被挤到 68px、
  比标签还窄（见验证小节的对比），所以最终没用固定宽度定尺寸。

改动只碰 `_build` 里这一小段和新增的模块级常量 `TOGGLE_ROWS`，界面其它部分没动。

### 2【Important】「下一题」的固定坐标路径缺前台护栏

设计文档 §6.1（`docs/superpowers/specs/2026-09-26-voice-tap-gre3000-design.md:477`）规定
**每次点击前必须校验前台应用**。读屏那条路（`main.py:892` 一带）有，**固定坐标那条路没有**。
后果比设计设想的更宽：手机停在**别的 App**（微信/QQ）上，说一句「继续」或「next」
也会朝 `(909, 2476)` 点下去。

**改法**（`handle_next` 的 `if cfg.fixed_next_position is not None:` 分支，`main.py:855`）：

```python
peeked = ctx["prefetcher"].peek()          # 零读屏成本
if peeked is not None and peeked.foreground_package != screen.GRE_PACKAGE:
    detected = peeked.foreground_package or "未知应用"
    say(f"       [固定位置] 当前检测到的是 {detected}，不在 GRE3000，"
        f"这一下不点（本应点 {x}, {y}）")
    note_input(ctx, "next", "0", outcome=f"已拒绝：当前不在 GRE3000（{detected}）")
    return
```

三种情形，与要求一一对应：

| `peek()` 返回 | 行为 |
|---|---|
| `None`（还没有任何界面数据，比如刚启动） | **照常点** —— 没有依据就不拦，不把正常路径挡死 |
| 前台 **不是** `screen.GRE_PACKAGE` | **拒绝点击** + 一句中文提示（并记进界面「我的输入」） |
| 前台**是** `GRE3000` | 照常点 |

**为什么只做「前台应用对不对」这半道，不做 §6.1 的第二条（≥2 个 `tv_question` 节点）**：
「下一题」按钮长在**详情页**上（答完题的释义页），那里**本来就没有** `tv_question`
选项节点 —— 硬套第二条会把这条路唯一的正常用法也一并挡死。前台包名这一层已经拦住了
「停在别的 App 上误点」这个真正危险的情况。这段理由原样写进了代码注释。

**局限（也写进注释了）**：`peek()` 是「最近见过的」，**不保证是此刻的**。刚切走 App、
还没来得及读到新屏时，这道护栏可能看不出来。这是它「零读屏成本」的代价，是有意取舍。

顺带修了一处**已经变成假话的日志**：该分支原来打印「（未做界面校验）」，
现在改成「（未读屏，只核对了最近见过的一屏前台应用）」。

## 测试的先红后绿

**先写测试（红）** —— 只加了测试、还没动 `main.py` 时：

```
$ python3 -m unittest tests.test_pipeline.TestNextButton -v
FAIL: test_fixed_position_blocked_when_peeked_screen_is_other_app (TestNextButton)
固定坐标这条路也要有前台护栏（设计文档 §6.1）。
AssertionError: Lists differ: [(909, 2476)] != []
- [(909, 2476)]
+ [] : 前台不在 GRE3000 时固定坐标也不能点
Ran 9 tests ... FAILED (failures=1)
```

红线**恰好**是那条护栏用例。另外两条新用例（`None` → 照常点、GRE → 照常点）
在没有护栏时**就是绿的** —— 这是有意的：它们钉的是「两道正确放行」，用来证明护栏
没有把正常路径误挡（只测「拒绝」的话，把 `handle_next` 整个 return 掉也能全绿）。

**再改实现（绿）**：

```
$ python3 -m unittest tests.test_pipeline.TestNextButton -v
Ran 9 tests in 1.809s
OK
```

（其间还看到 `test_wrong_app_does_not_click` 打出的读屏路提示
「当前不在 GRE3000（检测到的是 com.tencent.mobileqq）」，说明两条路现在口径一致。）

## 用例数

**308 → 311**（新增 3 条，全在 `TestNextButton`）。
`tests/test_inventory.py` 里 `tests.test_pipeline` 的基线顺手从 103 提到 106 ——
这个文件自己的约定是「基线贴着实际值，免得整类被删时总数还对得上」，加了用例就得抬基线。

命令与结果（先清了字节码缓存）：

```
$ rm -rf tests/__pycache__ voice_tap/__pycache__
$ python3 -m unittest discover -s tests 2>&1 | tail -3
Ran 311 tests in 12.590s
OK
```

## 做了什么验证（真窗口）

`tests/` 里没有任何 tkinter 用的东西（也不该有 —— 测试要能在没 Tk 的机器上跑）。
所以第 1 处的验证是**另写的一次性脚本**，不进仓库：

1. 沙箱装不到 `python3-tk`（无 root），于是
   `apt-get download python3-tk` + `tk8.6-blt2.5` 两个 `.deb`，`dpkg-deb -x` 解包到 `/tmp`，
   `PYTHONPATH` 指到解出来的 `tkinter` 与 `_tkinter.so`、`LD_LIBRARY_PATH` 指到 `libBLT`。
2. 用 `xvfb-run` 起虚拟显示，**建真窗口**，调 `_render_toggles()` 把按钮刷成真实
   显示的长标签（「语音说下一题：开」等），再逐个 `winfo_width()` / `winfo_ismapped()`，
   并用字体量出每段文字的像素宽度比对。

**量「真的 `gui.py`」（不是复刻的那段）**：

| 窗口 | 语音 | 模式 | 小键盘 | 点击后预读 | 语音说下一题 | 结论 |
|---|---|---|---|---|---|---|
| 360×520 | 102 px | 103 px | 103 px | 160 px | 160 px | 全部可见、放得下 |
| 340×380（minsize） | 96 px | 96 px | 96 px | 150 px | 150 px | 全部可见、放得下 |

最长标签「语音说下一题：开」在最小窗口下是 112 px，按钮 150 px，余量 ~1.34 倍；
`winfo_ismapped()` 五个全为真；五个按钮分属**恰好 2 个**不同的行 Frame。

**排法对比**（都在 340×380 下量，看哪种最稳）：

| 排法 | 结果 |
|---|---|
| 旧：一行五个 `width=15` | 后两个 1 px（重演 bug） |
| 中间稿：两行 + `width=11` + `expand/fill` | **小键盘被挤到 68 px < 标签 70 px（裁字）** ← 所以没用它 |
| 最终：两行 + `grid` 等宽列 + `width=8` | 96 / 96 / 96 / 150 / 150，全部放得下 ✅ |

还做了字体放大压力测试：字体 ×1.2 仍全部放得下；×1.4（约 13pt，远超默认）起
两个长标签才开始吃紧 —— 这个量级已超出本程序的默认字体与最小窗口设定。

另外，截图确认过（`import` 抓的 PNG 里确有内容，非空白窗口），但**没能用眼睛看**：
这个会话里 Read 工具打不开图片（PNG/JPEG 都报 `Unsupported Image`），
所以只能拿程序数「深色像素」确认窗口确实渲染了东西。抓的图已删，没留在仓库或输出目录。

## 我**没能**验证什么

- **Windows 上的真窗口 / 真实的 Segoe UI 字体。** 沙箱是 Linux Tk，默认字体不是
  Segoe UI，这里 1 个「字符宽」≈ 9.7 px（Windows 上通常更窄）。所以上表那些像素数
  **不能照搬到 Windows**。能搬过去的是**结构性结论**：两行、行内等宽、列宽由窗口决定
  而非由字体/文字决定 —— 这条与字体无关。至于「Windows 上 340px 窗口里 96px 够不够放
  70px 的中文标签」，按余量 ~1.34 倍判断是够的，但**这一条是推断，不是实测**。
- **真机 / 真手机**：本次改动不涉及 adb 与手机，未连接真机验证（一贯如此）。
- **护栏在「刚切走 App、新屏还没读到」时的表现**：按设计它看不出来（不读屏）。这是
  有意取舍，但我**没有在真机上复现这个时序**去确认它的实际影响面。

## 疑虑

1. **`peek()` 的可信度**：护栏用的是「最近见过的一屏」，不是「此刻」。它挡得住
   「一直停在别的 App 上」（这正是危险的大头），但挡不住「刚切走、程序还没读到新屏」
   那零点几秒。若要把这一层也补上，就得走读屏 —— 那这条路就不再「零成本」了，
   与当初选固定坐标提速的目的冲突。目前的取舍写进了代码注释。
2. **等宽列依赖「窗口 ≥ minsize 340」**。用户拖不到更窄（`minsize` 挡着）；但**将来若
   有人调小 `minsize`，两行也可能再挤** —— 那种改动请顺手跑一遍上面那个量按钮的脚本。
3. **`StubPrefetcher.peek()` 改成返回可注入字段**（默认仍 `None`）。默认行为没变，
   `test_prefetch.py` 里测的是真的 `ScreenPrefetcher`，不受影响；全套 311 条为证。
4. **测试清单基线抬到了 106**。若审查认为不该动这个数字，去掉那 3 行注释、把 106 改回
   103 即可（用例仍是 311，只是 3 条新用例不再受「数量守门」保护）。
5. 本次提交 `git add -A` 把审查方留下的 `.superpowers/sdd/reports/final-review.md`
   一并收进了 `1660db0`（它此前是 untracked）—— 与仓库把审查报告入库的惯例一致，
   但**如果不想要它，请告诉我**。

## 提交

```
1660db081bb00a76ed8e66e4089723641030261f
fix: 开关按钮两行排布；下一题的固定坐标路径补前台护栏
（5 files changed, 139 insertions(+), 9 deletions(-)）
```

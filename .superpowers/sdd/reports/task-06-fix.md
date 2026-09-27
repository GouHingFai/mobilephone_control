# 任务 6 修复报告：补上界面数据接线的覆盖 + 把「（见下）」改成诚实的样子

## 状态：DONE

> 288 条全绿（起点 275 + 新增 13）。**每一条新用例都逐条做过「改坏看红不红」实验**，
> 结果见下面「改坏实验」一节：删掉/改错对应那处接线，变红的就是（且只是）为它写的那条。
> 一处小毛病（界面上永久留着「见下」）按简报改成诚实的样子。
> 唯一需要说明的是 E7/E8 不是「恰好一条」——它不是单点接线而是全局空操作守卫，
> 详见「疑虑 1」。

---

## 1. 改了什么

### `voice_tap/main.py`（4 行实质改动 + 注释）

**毛病**：`handle_speech` 开头记的那条输入，`outcome` 写的是 `"（见下）"` ——
意思是「结果在下面」。但**匹配失败时 `do_click` 根本不会被调用**
（读屏失败、走「下一题」这些分支也不会），于是界面上会永久留着一条
没有下文的「见下」，比什么都不说更误导。

改法（**没有**去实现「事后更新已有条目」那套 —— `UiState` 的约定是构造好就不再改）：

- **开头那条记录的 `outcome` 留空**（只显示「听到了什么」）：
  `note_input(ctx, "speech", text, detail=f"置信度 {logprob:.2f}")`
- **在「没匹配上」分支里补记一条带明确结果的**：
  - 普通没匹配上 → `outcome="没匹配上：屏幕上没有这个词"`
  - 序号超范围 → `outcome=f"没匹配上：你说了第 N 个，屏幕上只有 M 个选项"`

  简报给的是单一示例串，我把它用作默认分支；序号那支单独说清 ——
  否则用户说了「第七个」而屏幕上只有 5 个时写「屏幕上没有这个词」就是假话。
  这属于同一分支内的诚实性处理，没有扩大范围。

### `tests/test_pipeline.py`

- `make_ctx(xml, preview=False, ui=None)` 加了一个可选参数：**默认不往 ctx 里塞 `"ui"` 键**
  （模拟不带 `--gui` 启动），要测接线时传真的 `UiState()`。既有 275 条的 ctx 一字不变。
- 末尾新增两个测试类、13 条用例：
  - `TestUiStateWiring`（9 条）：逐个钉住 6 处接线点。
  - `TestUiWiringWithoutUi`（4 条）：`ctx` 里没有 `ui` / `ui` 为 `None` 时的空操作。

---

## 2. 改坏实验（本次交付的核心证据）

做法：把 `main.py` 里**对应的那处接线**删掉 / 改错 → 清 `__pycache__` → 跑全套 →
记下变红的用例 → 还原。每一步都清字节码缓存，避免读到旧 `.pyc`。
脚本 `/tmp/bt/break_check.py`（沙箱内，未入库）。

| # | 把哪处接线改坏 | 变红条数 | 变红的用例 |
|---|---|---|---|
| **E1a** | 删掉 `grab_screen` 里**【预读】那处** `publish_screen` | **1** | `test_grab_screen_hands_the_prefetched_screen_to_the_ui` |
| **E1b** | 删掉 `grab_screen` 里**【当场读屏】那处** `publish_screen` | **1** | `test_grab_screen_hands_the_fresh_read_screen_to_the_ui` |
| **E1c** | 两处**都删**（简报点名的实验） | **2** | 上面两条 |
| **E2a** | 删掉 `do_click` 里 **「点了 …」**那处 `note_input` | **1** | `test_numpad_click_leaves_an_input_record` |
| **E2b** | 把 `do_click` 里 **「已跳过（防连点）」** 那条 `if` 体换成 `pass` | **1** | `test_debounced_click_is_recorded_as_skipped` |
| **E3** | 删掉 `handle_numpad` 里 **「已忽略 …」**那处 `note_input` | **1** | `test_stamp_rejected_press_leaves_an_ignored_record` |
| **E4** | 删掉 `handle_speech` **开头**那处 `note_input` | **3** | `test_speech_records_what_was_heard`、`test_heard_record_does_not_promise_a_followup`、`test_unmatched_speech_records_a_clear_outcome` |
| **E5** | 把开头那条 `outcome` **改回 `"（见下）"`**（把本次修复回退） | **1** | `test_heard_record_does_not_promise_a_followup` |
| **E6** | 删掉 **「没匹配上」分支里**的两处 `note_input` | **2** | `test_unmatched_speech_records_a_clear_outcome`、`test_unmatched_ordinal_says_what_actually_went_wrong` |
| **E7** | 去掉 `publish_screen` 的 `if ui is None: return` 空操作 | **49** | 含 `test_grab_screen_is_harmless_without_ui`、`test_speech_path_still_clicks_without_ui`、`test_numpad_path_still_clicks_without_ui`、`test_explicit_none_ui_is_also_safe` 及全部 no-ui 用例（见疑虑 1） |
| **E8** | 去掉 `note_input` 的 `if ui is None: return` 空操作 | **50** | 同上量级（见疑虑 1） |
| — | 全部还原后复核 | **0** | `Ran 288 tests ... OK` |

几点说明：

- **E1a/E1b/E2a/E2b/E3/E5 都是「恰好一条」** —— 这才是「这条测试的失败确实是
  因为这一处接线没了」的硬证据。
- **E4 是 3 条**：三条断言都建立在「开头那条记录存在」之上，所以删掉它三条一起红，
  是诚实的（我没有为了凑「恰好一条」去把其中两条的断言改弱）。
- **E6 是 2 条**：同一个分支的两个子情形各一条断言，符合预期。
- **E2b 的一个坑**（前一次尝试是无效实验，记录在此）：那条 `note_input` 是
  `if not clicked:` 的**唯一语句**，直接整行删掉会 `SyntaxError`，
  于是整个 `test_pipeline` / `test_prefetch` 收集失败、报出 5 条
  「收集不到」的假红。把 `if` 体换成 `pass` 才是这次要看的东西 ——
  这一步也说明**清缓存**和**确认报错原因**同样重要。

---

## 3. 用例数

| | 用例数 |
|---|---|
| 起点（HEAD，任务 6 提交） | 275 |
| 本任务新增 | **13** |
| 最终 | **288** |

```
$ rm -rf tests/__pycache__ voice_tap/__pycache__
$ python3 -m unittest discover -s tests 2>&1 | tail -3
Ran 288 tests in 11.961s

OK
```

新增 13 条 = `TestUiStateWiring` 9 条 + `TestUiWiringWithoutUi` 4 条。

---

## 4. 未动的东西（硬性约束）

- **不带 `--gui` 行为不变**：`main.py` 里没有任何地方设置 `ctx["ui"]`；
  `publish_screen` / `note_input` 仍以 `ctx.get("ui") is None` 当空操作
  （两条守卫都在，E7/E8 证明了它们被需要）。
- 没动 `dispatch_action` / `numpad_worker` / `main()` 的 `try/except/finally` /
  `.gitattributes` / `.bat`。
- **`UiState` 的约定**：没有改任何已构造的 `ScreenView` / `options`；
  实现里也没有「事后更新条目」。
- **没有动 `tests/test_inventory.py`**，基线数字保持 59（它是「只增不减」的下界，
  288 不减所以不需要改）；也没有把新类加进 `REQUIRED_CLASSES`（那是任务 8 的事）。

---

## 5. 提交

| | |
|---|---|
| 代码提交 | `9bcf47d`（`9bcf47d4741896d6861a73416b2cc546b865e7ab`） |
| 信息 | `test: 补上界面数据接线的覆盖（连线删掉必须变红）` |
| 内容 | `voice_tap/main.py`、`tests/test_pipeline.py` |

（本报告另作为一条 `docs:` 提交入库，与任务 1–6 的报告一致。）

---

## 6. 疑虑

1. **E7/E8 不是「恰好一条」，而是 ~50 条。**
   这不是缺陷，是性质不同：`if ui is None: return` 不是某一处接线，而是
   全局空操作守卫 —— 去掉它，所有不传 `ui` 的用例都会炸（AttributeError）。
   也就是说「不带 `--gui` 行为不变」这条护栏是**宽覆盖**；
   真正为它精确负责的是 `TestUiWiringWithoutUi` 的 4 条用例
   （它们确实因此变红）。如果想让它也「恰好一条红」，单点守卫的写法做不到，
   除非把每条 no-ui 用例都包 `assertRaises` —— 那反而更差。故保持现状。

2. **「听到了什么」与「没匹配上」在界面上是两条独立记录**，不是一条被更新
   （`recent_inputs` 最新的在前，所以界面上会先看到「没匹配上」、再看到
   「听到了 清晰」）。这是遵守 `UiState`「构造好就不改」约定的必然结果，
   也是简报明确要求的方向。如果日后觉得界面上两条太啰嗦，
   那是 `gui.py` 的显示层问题，不该回头去突破 `UiState` 约定。

3. **读屏失败（`not snap.ok`）与 `AdbError` 两个早退分支没有补记 outcome。**
   简报只点名了「没匹配上」分支，我就没顺手加（避免扩大范围）。
   代价可接受：开头那条现在 `outcome` 为空，这些分支在界面上就是
   「只显示听到了什么」，**不会**出现「没有下文」的误导 —— 毛病已经消除。
   若希望这两条也各有明确交代，可以在任务 8 或后续任务里补。

4. **`test_unmatched_ordinal_says_what_actually_went_wrong` 依赖夹具是 5 个选项**
   （断言里写死了 `"5 个选项"`）。夹具换掉时这条要跟着改 —— 与仓库里既有的
   `TestScreenSnapshotUsedByMatcher`（断言 `len(snap.options) == 5`）是同一类耦合，
   并非本任务新引入的风险。

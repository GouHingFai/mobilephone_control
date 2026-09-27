# 任务 1 报告：动作时戳 —— 修「连按两下同一个键点到新题上」

## 状态

**DONE**

全套 227 个用例通过（基线 222 + 新增 5），与简报期望数一致。

## 做了什么

改动三个文件（外加一处与代码无关的既有改动，见「偏离计划」）：

### `voice_tap/main.py`

1. **`ScreenPrefetcher.identity()`（新增，紧挨 `miss_reason()` 之后）**
   返回最近见过那一屏的指纹（`signature(self._last_seen)`）；还没读到过任何界面
   （`_last_seen is None`）时返回 `None`。全程持 `self._lock`。

2. **`handle_numpad(number, ctx, stamp=None)`（签名加第三个参数）**
   在 `grab_screen(ctx)` 之后、`if not snap.ok:` 之前插入时戳核对：
   ```python
   if stamp is not None and ScreenPrefetcher.signature(snap) != stamp:
       say("[小键盘] 这一下已忽略：界面在按键之后翻页了（不点，免得点到新题上）")
       return
   ```
   不点任何坐标，直接返回。docstring 里补上了 `stamp` 的来历。

3. **动作队列条目统一成 `(kind, value, stamp)`**（`main()` 内）
   - 三个热键回调改成：
     ```python
     on_option=lambda n: numpad_queue.put(("numpad", n, ctx["prefetcher"].identity())),
     on_next=lambda: numpad_queue.put(("next", None, ctx["prefetcher"].identity())),
     on_force_read=lambda: numpad_queue.put(("force_read", None, None)),
     ```
     入队时用 `ctx["prefetcher"].identity()` 盖上「按键那一刻」的戳。
   - `numpad_worker` 循环体：解开三元组 `kind, value, stamp = action`
     （解不开就 `continue`，防御旧格式残留），再按 `kind` 分派到
     `handle_force_read` / `handle_next` / `handle_numpad(value, ctx, stamp=stamp)`。
     原来按 `number == "."` / `number == 0` 判断的那几行已删除。

### `tests/test_pipeline.py`

- 顶部 `GRE_XML` 之后新增第二题夹具：
  `SECOND_XML = (FIXTURES / "gre_prototype.xml").read_text(encoding="utf-8")`。
  已核实 `gre_prototype.xml`（题干 `prototype`）与 `gre_degrade.xml`（题干 `degrade`）
  的题干与选项文字都不同，指纹必定不同。
- 文件末尾（`TestStartupProbe` 之后、`if __name__` 之前）新增
  `TestActionStamp`（5 个用例）：`identity()` 空/非空、翻页后必须不点、
  界面没翻照常点、没盖戳不拦截。

## 测试结果

### 失败的测试确实失败（写实现之前）

`python3 -m unittest tests.test_pipeline.TestActionStamp -v` → `FAILED (errors=4)`：

```
ERROR: test_dropped_when_screen_changed_since_press ...
AttributeError: 'ScreenPrefetcher' object has no attribute 'identity'

ERROR: test_identity_is_none_before_any_read ...
AttributeError: 'ScreenPrefetcher' object has no attribute 'identity'

ERROR: test_identity_reflects_last_seen_screen ...
AttributeError: 'ScreenPrefetcher' object has no attribute 'identity'

ERROR: test_runs_when_screen_unchanged ...
AttributeError: 'ScreenPrefetcher' object has no attribute 'identity'
```

失败原因是 `identity()` 尚不存在，正是简报预期的原因（不是语法错）。

### 最终结果

```
$ python3 -m unittest discover -s tests
Ran 227 tests in 9.025s
OK
```

新增 5 个用例全过；全套 227 个全过（222 + 5，与简报期望一致）。
提交后从干净工作区再跑一遍，仍是 227 OK。

## 提交哈希

```
0d09a85 fix: 动作时戳 —— 连按两下同一个键不再点到新题上
```

`git config core.autocrlf` 仍为 `false`，`.gitattributes` 未被改动。

## 偏离计划的地方

1. **`git add -A` 顺带提交了两处非本任务的既有改动。**
   `docs/superpowers/plans/2026-09-27-gui-and-voice-controls.md`（+3/-1）
   和 `.superpowers/`（新目录，含本任务简报与 progress.md）在我开始工作前
   就已经是「已修改/未跟踪」状态 —— 前者是把计划里的「本项目不是 git 仓库」
   那段改成「已启用 git」（正是我这份简报 Global Constraints 里引用的文字），
   属于环境搭建时的改动，不是我改的。简报明确指定提交命令为
   `git add -A && git commit`，我照做了，因此它们进了同一个提交。
   **我没有修改这两个文件的内容。**

2. **`test_runs_when_no_stamp_given` 在写实现之前就是通过的（不是失败）。**
   简报步骤 2 期望看到两个错：`no attribute 'identity'` 和
   `unexpected keyword argument 'stamp'`。实际只出现了前者 —— 因为 4 个用例
   都在调用 `identity()` 时就先抛错了，`stamp=` 关键字那条根本没走到。
   第 5 个用例（不传 stamp）本来就能跑，所以它是回归护栏、不是新失败。
   这不影响结论：有实现前的失败证据，且 `stamp` 参数确实由后续用例覆盖到。
   简报步骤 2 的期望描述略有出入，测试代码本身没有 bug。

其余每一步的代码（`identity()` 实现、`handle_numpad` 的插入位置与文案、
worker 循环体、三个 lambda）与简报给的片段逐字一致。

## 疑虑

1. **`kind == "next"` 的动作不参与时戳核对。** worker 里
   `handle_next(ctx)` 没有接收 stamp（与简报给的最后一段循环体一致），
   所以「下一题」（小键盘 0）这条路径理论上仍有「第一屏按的、第二屏才执行」
   的可能。不过 `handle_next` 若不配 `fixed_next_position`，会当场读屏并只认
   `foreground_package == GRE_PACKAGE` 下的「下一题」按钮，翻到答题页时找不到
   按钮、不会点，风险较低；只有配了 `fixed_next_position`（直接点固定坐标、
   不做任何界面校验）时才真正无保护。简报只圈定了 numpad 路径，我按简报做了。
   **如果这个盲区也要堵，建议后续任务里让 `handle_next` 同样接收并核对 stamp。**

2. **入队时立即取 `identity()` 的时序** —— 回调线程里 `identity()` 读的是
   `_last_seen`（最近见过的界面）。这正是「按键那一刻的屏幕」，语义正确；
   但如果按键与上一次读屏之间用户已经手动翻了页而程序还没读到，
   戳会和实际屏幕不符，导致这一下被误判为「翻页了」而丢弃。
   按简报的设计这是有意的保守取向（宁可漏点、不可错点），且用户看到没反应
   会再按一次。仅作记录。

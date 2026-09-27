# 修复简报：补上动作队列接线的测试覆盖

## 背景

任务 1（动作时戳）已经实现并通过审查，但审查发现一个 **Important** 问题：

新增的 `TestActionStamp`（在 `tests/test_pipeline.py`）只验证了 `handle_numpad` 里
**「核对时戳」**那一半。而**「盖戳 → 入队 → 解包分派」**这条接线**完全没有测试覆盖** ——
它分别写在 `main()` 里的三个 lambda 和 `numpad_worker` 这个闭包函数里，外部没法直接调。

**风险**：谁要是把 `numpad_queue.put(n)` 忘改成三元组、或者把解包写反，
**227 个测试照样全绿，而真机上的「连按两下点到新题」原样复现**。
这正是这个项目反复栽过的那类坑：「测试全绿，但真实路径已经坏了」。

## 你要做的

把这段接线从 `main()` 里**抽成模块级函数**，让它可测。

### 1. 新增 `make_action_putters(queue, prefetcher)`

放在 `voice_tap/main.py` 里（`ScreenPrefetcher` 类定义之后即可）。
返回一个三元组或字典，装着三个可调用对象，对应热键要的回调：

```python
def make_action_putters(queue, prefetcher):
    """
    造三个「把动作塞进队列」的回调，供热键注册使用。

    **盖戳的时机就在这儿**：回调跑在按键那一刻，所以这时候取 `prefetcher.identity()`，
    拿到的就是「按下时屏幕上是什么」。这个戳一路带到工作线程，执行前用来核对。
    """
```

三个回调的入队格式：

| 回调 | 入队内容 |
|---|---|
| `on_option(n)` | `("numpad", n, prefetcher.identity())` |
| `on_next()` | `("next", None, prefetcher.identity())` |
| `on_force_read()` | `("force_read", None, None)` —— 强制读屏跟界面无关，不盖戳 |

### 2. 新增 `dispatch_action(action, ctx)`

模块级，负责解包并按 `kind` 分派：

```python
def dispatch_action(action, ctx):
    """
    执行一个动作队列条目。解包 `(kind, value, stamp)` 后按 kind 分派。

    做成独立函数（而不是塞在工作线程的闭包里），是为了能单测 ——
    这段「格式对不对、有没有分派错」是最容易悄悄坏掉的地方。
    """
```

分派规则：
- 格式不对（不是长度 3 的可解包对象）→ 直接忽略，**不要抛异常**（也不要写日志刷屏）
- `("force_read", ...)` → `handle_force_read(ctx)`
- `("next", ...)` → `handle_next(ctx)`
- `("numpad", n, stamp)` → `handle_numpad(n, ctx, stamp=stamp)`

**写成一个清晰的 kind 分派结构**（比如 if/elif 链，或一张表态 + 兜底），
因为**任务 5 之后还会往里加 `"intent"` 和 `"quit"` 两个分支**，别写死、别搞成难扩展的形状。

### 3. `main()` 里改用这两个函数

- 把 `hotkeys.start(...)` 里原来那三个 lambda，换成 `make_action_putters(numpad_queue, ctx["prefetcher"])` 的产物。
- 把 `numpad_worker` 的循环体简化成：取一条 → `dispatch_action(action, ctx)`，
  外面的 `try/except AdbError` 与 `except Exception` 保持原样（那是线程兜底，别删）。

### 4. 补测试

在 `tests/test_pipeline.py` 末尾新增 `TestActionWiring`：

- **盖戳**：三个回调各自入队的格式与戳都对。用一个假的 queue（有 `put` 方法、把它记下来）
  和一个真的 `ScreenPrefetcher`（先 `note()` 一屏），断言
  `("numpad", 3, <那一屏的 signature>)`、`("next", None, <同>)`、`("force_read", None, None)`。
- **解包分派**：三个 kind 各自路由到正确的处理函数。做法建议：用一个 `ctx`，
  把 `handle_numpad` / `handle_next` / `handle_force_read` 换成桩 ——
  但**注意**，它们是模块级函数，直接替换会有污染风险。**更稳的做法**是走真实路径：
  构造 `make_ctx(GRE_XML)` 那样的 ctx，直接 `dispatch_action(("numpad", 1, None), ctx)`
  然后断言 `fake.taps` 真的点了一次；`dispatch_action(("force_read", None, None), ctx)`
  断言 `fake.dump_calls == 1` 且没点。**优先用这种「断言可观察后果」的写法，别去 monkeypatch。**
- **坏格式不崩**：`dispatch_action(3, ctx)`、`dispatch_action(("numpad",), ctx)`、
  `dispatch_action(None, ctx)` 三种都不抛异常、也不产生点击。

## 硬性约束

- **行为不许变**：现有 227 个测试必须继续全绿。这是纯重构 + 补测试。
- 中文注释与日志；所有用户可见输出走 `main.say()`。
- 不要碰 `.gitattributes` / `core.autocrlf`；不要改 `.bat`。
- 跑测试：`cd /sessions/pensive-confident-cerf/mnt/声控手机项目 && python3 -m unittest discover -s tests`
  （**没有 pytest**；沙箱缺 `pypinyin` 就 `pip install pypinyin --break-system-packages`）
- 提交：`git add -A && git commit -m "test: 补上动作队列接线的覆盖（审查发现）"`

## 写报告

写到 `H:\声控手机项目\.superpowers\sdd\reports\task-01-fix.md`，包含：
**状态**（DONE / DONE_WITH_CONCERNS / BLOCKED）、改了什么、测试结果（先贴「新测试在重构前会失败吗」的证据）、提交哈希、疑虑。

# 任务 7 报告：按键不再等读屏 —— 用最近读到那一屏的坐标立刻点

## 状态：DONE_WITH_CONCERNS

简报里写的东西**全部做完、全部验证过**，341 用例全绿（起点 334）。
报 CONCERNS 是三个「要让人看见」的点，不是没做完：

1. **计划问题**：简报说「用 `prefetcher.peek()`……把那一屏是多少秒前读到的也打出来」，
   但 `peek()` 只返回快照、**不带年龄**，拿不到秒数。我加了 `peek_with_age()`
   （见下面第 1.1 节），这是为满足简报要求必须做的一处新增。
2. **简报没提到的一个洞**：`handle_next` 那条路用旧屏时，「下一题」按钮**可能不在上面**，
   于是这一下会变成「什么都不点」（见第 4.1 节）。数字键没有这个问题。
3. **这个改动重新引入了「用旧坐标点新题」的风险**（用户明确选的取舍）。
   它在什么条件下会出错，逐条写在下面第 4.2 节。

提交 `e3cd495`（`feat: 按键不再等读屏 —— 用最近读到那一屏的坐标立刻点`）。
只改了 `voice_tap/main.py`、`tests/test_pipeline.py`、`tests/test_prefetch.py`、
`tests/test_inventory.py` 四个文件；**没动界面、文档、`.gitattributes` / `core.autocrlf` / `.bat`**。

---

## 起点

```
rm -rf tests/__pycache__ voice_tap/__pycache__
python3 -m unittest discover -s tests
→ Ran 334 tests in 13.546s … OK
```

与父任务给的一致。沙箱已有 `pypinyin`；全程没有 import tkinter。

---

## 一、改了什么

### 1.1 `ScreenPrefetcher`：新增 `peek_with_age()`（唯一超出简报字面的新增）

简报要求按键那条路「用最近读到的那一屏」并把「那一屏是多少秒前读到的」打出来。
`peek()` 只有快照，所以加了：

```python
def peek_with_age(self):
    with self._lock:
        if self._last_seen is None:
            return None
        return self._last_seen, time.monotonic() - self._last_seen_at
```

**年龄必须另记一个 `_last_seen_at`，不能拿缓存那一份的 `_at`。** 原因是一个真实的坑：
`invalidate()`（点击时必调）会把 `_at` **清零**，而 `_last_seen` 是**故意留着不动**的
（翻页判断、识别上下文、「下一题」的前台护栏都靠它）。两者在那一刻已经不是一回事 ——
拿清零后的 `_at` 算年龄，`time.monotonic()` 是从开机算起的，日志会喊出
「那一屏是 43000 秒前读到的」这种假话。所以 `_store_locked()` 里多写一个字段：

```python
self._last_seen = snap
self._last_seen_at = read_at      # ← 新增，与 _at 分开：作废只清 _at
```

`peek()` 本身一字未改（语音识别、「下一题」固定坐标的前台护栏还在用它）。
**年龄没有上限** —— 超过 `cache_max_age` 的旧屏照样交出来，只如实报岁数；
这是用户明确要的「不做时间保险」，用 `TestPeekWithAge.test_no_age_limit_by_design`
钉住，免得将来被当成 bug「修」掉。

### 1.2 `grab_screen`：加 `allow_stale=False` 参数

三档顺序（`allow_stale=True` 时）：

| 情形 | 行为 |
|---|---|
| 缓存里有界面 | **照旧用缓存**（`take()`；这是常态） |
| 缓存空 | **不等预读**，用 `peek_with_age()` 的坐标，来源标「上一次读到的」，日志打出秒数 |
| `peek_with_age()` 也是 None | 才老老实实当场读一次（原兜底逻辑不变） |

`allow_stale=False`（默认）走的是**原封不动的** `take_or_wait()` —— 语音那条路行为一字未变。

取舍、代价、用户的两条理由（误触 → 点在已答过那道题上等于没反应；不是误触 → 他
已经看到新屏，而选项位置很稳）、以及「刻意不做时间保险」都写进了 `grab_screen` 的
docstring（第 574-611 行），包括那句关键的区分：

> 这正是设计文档曾经推翻过的「坐标复用」，但两者不是一回事：当初推翻它，是因为那是
> 不读屏直接点、**根本不知道屏幕长什么样**；**这里用的是最近一次真实读到的坐标**，
> 只是不等到最新那一次。

日志长这样（下面第 3.5 节有真跑出来的原样输出）：

```
       [注意] 预读还没读完，这一下不等了 —— 用上一次读到那一屏的坐标（那一屏是 1.2 秒前读到的）
       （界面来源：上一次读到的（1.2 秒前，没读屏、也没等预读））
```

界面第二块（`publish_screen`）也如实标成「上一次读到的」并带上年龄 ——
不然界面上看起来跟预读命中一模一样，用户不知道这次冒了险。

**`take_or_wait` 一个字没删**（语音路径还在用）。

### 1.3 调用点

| 位置 | 改成 |
|---|---|
| `handle_numpad` | `grab_screen(ctx, allow_stale=True)` |
| `handle_next`（非固定坐标那条支路） | `grab_screen(ctx, allow_stale=True)` |
| `handle_speech` | **原样** `grab_screen(ctx)`（→ `allow_stale=False`） |

顺带把三处**过时的注释/说明**改了（它们现在说的是假话）：
`ScreenPrefetcher` 的类 docstring 原本写「按数字键时不会重新读屏……只有预读没做成时
才兜底当场读一次」；`handle_numpad` 的 docstring 原本写「只有没预读成时才当场读一次兜底」；
`invalidate()` 的 docstring 补了一句「`_last_seen` 连同 `_last_seen_at` 都不动，而 `_at` 清」。

---

## 二、测试（`tests/test_pipeline.py`，新增 `TestKeyPressUsesLastSeenScreen` 三条）

新加的夹具 `SHIFTED_OPTION_XML`：第一个选项文字和 `GRE_XML` **一模一样**
（都是「adj. 清晰易懂的」），但整排挪到屏幕下半部分（y≈2005 而非 811）。
专门用来分辨**这一下点的是哪一份界面的坐标** —— 光断言「读没读屏」分不出来。

| # | 用例 | 钉住什么 |
|---|---|---|
| 1 | `test_numpad_clicks_with_last_seen_screen_without_reading` | **本改动的主证据**：缓存空 + `peek` 有内容 → `dump_calls == 0`，且点在第 3 个选项坐标上 |
| 2 | `test_numpad_reads_when_nothing_was_ever_seen` | `peek` 也是 None → `dump_calls >= 1`，照常点 |
| 3 | `test_speech_path_is_unchanged` | 语音仍然当场读屏、**不用 peek 的坐标**（用错就会点到 y≈2005） |

### 2.1 先红后绿（三条各自的真实结果，逐字贴）

**红 #1（改 main.py 之前）** —— 主证据：

```
$ python3 -m unittest tests.test_pipeline.TestKeyPressUsesLastSeenScreen
FAIL: test_numpad_clicks_with_last_seen_screen_without_reading
  File "tests/test_pipeline.py", line 854, in test_numpad_clicks_with_last_seen_screen_without_reading
    self.assertEqual(fake.dump_calls, 0,
AssertionError: 1 != 0 : 按键路径不该等预读、更不该当场读屏 —— 一次屏都不该读

Ran 3 tests in 1.068s
FAILED (failures=1)
```

**老实交代**：这一条红了，另外两条**改之前就是绿的**（第 2 条：改前也是当场读一次；
第 3 条：改前也走当场读屏）。它们本来就是「钉住没变的那两档」的护栏，
性质上不可能先红 —— 简报说「三条的先红后绿证据」，实际能红的只有第 1 条。
第 3 条虽不能先红，但它是**能红的**：把语音那处的 `allow_stale` 传成 `True`
（见下「改坏实验 2」），它当场就红。

**红 #2（`test_prefetch.py` 的 4 条）** —— `peek_with_age` 还不存在：

```
$ python3 -m unittest tests.test_prefetch.TestPeekWithAge
AttributeError: 'ScreenPrefetcher' object has no attribute 'peek_with_age'
...
Ran 4 tests in 0.005s
FAILED (errors=4)
```

**绿**（实现之后，全套）：

```
$ rm -rf tests/__pycache__ voice_tap/__pycache__
$ python3 -m unittest discover -s tests
Ran 341 tests in 14.484s
OK
```

### 2.2 改坏看红

**实验 1（简报指定的那个）**：把 `grab_screen` 里第 2 档（用 peek 那条）拿掉 ——
即把 `last = prefetcher.peek_with_age()` 换成 `last = None`：

```
Ran 3 tests in 1.074s
FAILED (failures=1)          ← 只有第 1 条红，第 2、3 条照样绿
AssertionError: 1 != 0 : 按键路径不该等预读、更不该当场读屏 —— 一次屏都不该读
```

改了之后 `md5sum voice_tap/main.py` 从 `8636813864392bc300262f02a1e1bb30`
变成别的值；还原备份后 md5 **仍是 `8636813864392bc300262f02a1e1bb30`**，
再跑全套 `Ran 341 tests … OK`。

**实验 2（多做的一次）**：把 `handle_speech` 的调用也传上 `allow_stale=True`
（模拟「顺手把语音路径也改了」这个错误）：

```
FAIL: test_speech_path_is_unchanged
  File "tests/test_pipeline.py", line 890, in test_speech_path_is_unchanged
    self.assertGreaterEqual(fake.dump_calls, 1,
AssertionError: 0 not greater than or equal to 1 : 语音这条路没改：缓存空就当场读屏，不等也不复用旧坐标

Ran 3 tests in 1.055s
FAILED (failures=1)
```

第 3 条红了（而且只有它红）。说明它虽不能「先红」，却真的能把
「语音路径被一起改掉」这件事拦住 —— 它是有牙齿的，不是摆设。
两次改坏之后都从 `/tmp` 的备份还原，`md5sum voice_tap/main.py` 都回到
`8636813864392bc300262f02a1e1bb30`，全套再跑一次 `Ran 341 tests … OK`。

---

## 三、最终数字

| 项 | 值 |
|---|---|
| 用例数 | **341 全绿**（起点 334，本任务 +7） |
| `tests.test_pipeline` 基线 | 120 → **123**（+3，`TestKeyPressUsesLastSeenScreen`） |
| `tests.test_prefetch` 基线 | 29 → **33**（+4，`TestPeekWithAge`） |
| `REQUIRED_CLASSES` | `tests.test_pipeline` 加 `TestKeyPressUsesLastSeenScreen` |
| 提交 | `e3cd495` |
| 改动文件 | 4 个（见文首） |

基线理由都写进了 `tests/test_inventory.py` 的注释里。两条基线**都贴着实际值**
（脚本核对过：9 个测试文件全部「实际 == 基线」）。

`REQUIRED_CLASSES` 里加名字的理由（也写进了注释）：这个改动是**本轮唯一重新引入
「用旧坐标点新题」风险的决定**，那一整类就是这道风险的记录 —— 删掉它，改动本身
就没有任何用例能拦住回归了。

### 3.5 真跑一遍看日志（真 `ScreenPrefetcher`，不是桩）

拿真类跑一次用户的场景（先读一屏 → 1.2 秒后作废缓存、预读正在读 → 第二下按键进来）：

```
[小键盘] 3
       [注意] 预读还没读完，这一下不等了 —— 用上一次读到那一屏的坐标（那一屏是 1.2 秒前读到的）
[屏幕] 题干：degrade
[屏幕] 选项：adj. 清晰易懂的 / adj. 阴郁的，闷闷不乐的 / …
       （界面来源：上一次读到的（1.2 秒前，没读屏、也没等预读））
[匹配] 小键盘第 3 个 → 点击坐标 (606, 1187)
--- 这一下按键读屏次数： 0   点的坐标： (606, 1187)
```

读屏 0 次；年龄如实是 `1.2` 秒（不是「开机以来」那么大的数 —— 证明 `_last_seen_at`
那个新字段确实是必要的，同时也说明 `_at` 那条路走不得）。

---

## 四、疑虑

### 4.1 `handle_next` 用旧屏时可能什么都不点（简报没提到）

「下一题」按钮**只长在详情页上**。所以按 0 的那一刻，如果手里那一屏还是答题页
（预读刚在跑），`snap.next_button` 是 None，代码会走「当前界面上没找到「下一题」按钮」
那条提示、**不点任何东西**。改之前这条路是等的（最多 8 秒），等到了就能点。

- 影响面：**出厂 `config.yaml` 里 `fixed_next_position: [909, 2476]` 是有值的**，
  真机上 `handle_next` 走的是固定坐标那条短路、根本不会走到 `grab_screen`。
  只有当用户按配置注释把那一行改回 `null` 时才会碰到。
- 届时的表现：按一下 0 没反应，日志里明写「没找到下一题按钮」，等预读读完（约 2.4 秒）
  再按一下就行 —— 是**可见、可恢复**的一下，不是静默点错。
- 我没有自作主张加「旧屏里没按钮就补读一次」：那超出简报范围，而且会引入一次
  读屏（正是用户不要的）。**要不要补，请定。**

### 4.2 用旧坐标点新题：什么条件下会出错（简报要求如实写）

安全的情形（用户的两条理由都成立时）：**两屏都是答题页、选项个数一样**。
实测选项严格等距 188 像素，题干变长时整排最多挪 43 像素，而行高 150、
中心到行边还有 75 像素。以下是我认为**可能真的出错**的条件，按危险程度排：

1. **手里那屏是答题页、眼前是详情页**（最危险的一种）。
   经过：点了一个选项 → App 翻到详情页 → 用户没有按 0、而是**又按了一个数字键**，
   且这一下发生在预读读完详情页之前（约 2.4 秒窗口内）。
   后果：拿着答题页第 N 个选项的坐标，点在**详情页**上那个位置 ——
   可能是释义文字、也可能是页面上的某个按钮/图标（收藏、发音、解释之类），
   **点了、不报错、但不是你要的**。这正是本项目最忌讳的静默点错。
   反方向是安全的：手里那屏若是详情页，`snap.ok` 为 False（详情页没有选项），
   程序会拒绝点击并提示「当前是答题后的详情页」。
2. **选项个数从 5 变 4 / 题干长度变化很大**时，整排位置不同。
   大多数情况下仍落在目标行内（差 43px < 75px）；但**若某一行的文字换行占了两行**
   （校准时会打印「**不等距** —— 有选项换行占了两行」），行高就不再是 150，
   相邻中心间距可能小于 75 像素 —— 这时用旧坐标有机会落到相邻选项上。
   **这条我没有真机数据，是推算出来的，请当成未验证的边界。**
3. **没有时间上限**：只要 `_last_seen` 还在（哪怕 60 秒前读的），按键就用它。
   如果用户用 scrcpy 手动翻了好几页、又没有按 `.` 强制读屏，程序手里的屏会很旧。
   这是用户明确要的「一律不等」，但**「旧」没有天花板，值得他自己确认能不能接受**。
4. **`numpad_reverse` 打开时**（倒序映射），点错的反差会被放大 —— 不过它本来就
   只改「第几个」的映射，与新旧坐标无关，这里只是提醒。

**没变的取舍**：语音那条路（`allow_stale=False`）仍然等 `take_or_wait`，
上面这些条件对它一律不适用。

### 4.3 界面这一层仍然没在真窗口上验过

`publish_screen(ctx, snap, "上一次读到的", age)` 会让界面第二块显示**旧题的文字**、
并如实标出来源。这条路径沙箱里测不了（要 import tkinter），**必须上机看一眼**
那一行标签是不是能让人一眼明白「这次用的是旧屏」。

### 4.4 已知残留（不是本任务引入的）

`trigger_on_speech()`（默认关）仍然没有代数护栏 —— 与任务 6 处理的
`trigger_after_click` 是同一类隐患（结果写回时可能盖掉更新的屏）。
本任务没碰它，顺着 `_last_seen_at` 一起改会更安全，但那超出简报范围。

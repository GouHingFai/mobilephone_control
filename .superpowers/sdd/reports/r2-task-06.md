# 任务 6 报告：按键不必再等预读的「确认」那一次读

## 状态：DONE

提交 `a14c26c`（`feat: 按键不必再等预读的确认那一次（用第一次读的结果就走）`）。
**334 个用例全绿**（起点 332，本任务 +2）。
两条测试都做了「改坏看红」：各自把对应的那一半改坏，**只有自己红、另一条照样绿**，已还原并复核 md5。

`tests/test_inventory.py` 的 `tests.test_prefetch` 基线 **27 → 29**，贴着实测值，理由写在该文件里。
只改了 `voice_tap/main.py`、`tests/test_prefetch.py`、`tests/test_inventory.py` 三个文件；
**没动界面、语音开关、文档、`.gitattributes` / `core.autocrlf` / `.bat`**。

---

## 起点

```
rm -rf tests/__pycache__ voice_tap/__pycache__
python3 -m unittest discover -s tests
→ Ran 332 tests … OK
```

与父任务给的一致。沙箱已有 `pypinyin`，无需安装；全程没有 import tkinter。

---

## 一、两处改动（`voice_tap/main.py`，都在 `ScreenPrefetcher` 里）

### 1.1 「先存第一份」—— 本轮的正题

`trigger_after_click()` 里，「读到还是和点击前一样」这条分支，原来是**不存**、直接去读第二次。
现在改成 **先 `store()` 这一份，再去读第二次确认**：

```python
# 和点击前一样：**先把这一份收下来**，再去读第二次确认。
# ……连续两次读到同一屏，就说明这就是当前屏幕（用户的原话），
# **所以第一份本来就是有效数据**——没有理由压着不给等在这次预读上的按键用。
if not store(snap, read_start):
    return
self.log("       [预读] 还是旧界面，先收下这一份，再读一次确认…")
```

于是**等在预读上的按键立刻能用上第一次读到的结果走人**，不必再陪预读跑完「确认」那一次读
（最长约 5 秒）。物理下限压到「最多等一次读屏」≈2.4 秒，正是本轮的目标。
第二次读到什么，照旧覆盖成什么。

### 1.2 「代数」护栏 —— 必须一起处理的副作用

按键一旦抢走第一份，它会立刻点击 → `do_click` → `invalidate()`（作废缓存）；
而预读的第二次读还在路上。它返回时带的是**点击前那一屏**，若不拦就写回缓存，
**下一次按键就会拿着过期坐标去点** —— 正是本项目最忌讳的「静默点错」。

修法（`__init__` 里加了 `self._generation = 0`）：

| 位置 | 改动 |
|---|---|
| `invalidate()` | `self._generation += 1`（**作废即换代**） |
| `trigger_after_click()` 开头 | `generation = self._generation`（记下这次预读是哪一代开始的） |
| 每次收结果之前 | `note_if_current(snap, generation, read_at)` 核对代数；变了就作废并打日志「期间又点了一下，这次预读作废（结果反映的是点击前那一屏，不收）」，然后收工 |

理由已写进注释：**一次预读的结果只对「它开始时的那一代」有效。**
靠一个只增不减的整数钉住时序关系，比时间戳可靠。

**两处超出简报字面、但更稳的细节（照实列出）：**

1. **核对与写入放在同一把锁里。** 简报说「每次 `note()` 之前核对代数」；我实现成
   `note_if_current()` 内部**先核对、后写入、全程持锁**。否则「核对完、还没写、
   又被 `invalidate` 换代」这个缝隙里旧屏还是会被写回去，护栏等于白加。
   为此把 `note()` 的写入部分抽成 `_store_locked()`（`note()` 自己只是加锁后调它，
   **语义一字未变**，时间戳护栏照旧）。
2. **作废即收工。** 第一次读就发现换代时直接 `return`，不再往下读第二次 ——
   读回来也一样不作数，白耗 2.4 秒。这也正是简报里「然后收工」的意思。

---

## 二、两条测试的「先红后绿」证据（`tests/test_prefetch.py`）

新增 `BlockingAdb`：**第一次 `dump_ui()` 立刻返回，第二次阻塞在 `threading.Event` 上**，
由测试决定什么时候放行 —— 时序是钉死的，不靠 sleep 碰运气。
（`release.wait(timeout=5.0)` 只是防写错测试时挂死整个套件的兜底。）

### 2.1 写实现之前（两条都红）

```
$ python3 -m unittest tests.test_prefetch.TestFirstReadIsUsableWhileConfirming
FAIL: test_first_read_is_usable_while_confirming
AssertionError: unexpectedly None : 第一次读到的就是当前屏，不该压着不给等着的按键用

FAIL: test_confirm_read_is_discarded_if_a_click_happened
AssertionError: (ScreenSnapshot(… prompt='prototype' …), 0.0076) is not None :
                换代之后第二次读到的旧屏绝不许写回缓存

Ran 2 tests … FAILED (failures=2)
```

第一条红在「`take()` 拿不到东西」（旧代码不存第一份）；第二条红在「旧屏被写回来了」。

### 2.2 改坏看红（对最终代码做，各自只有自己红）

**实验 1 —— 去掉「先存第一份」，这一支退回「不存 → 再读」：**

```
Ran 2 tests … FAILED (failures=1)
  FAIL: test_first_read_is_usable_while_confirming      ← 正是我们要它红的那条
   ok : test_confirm_read_is_discarded_if_a_click_happened
```

**实验 2 —— 去掉代数核对（`store()` 直接写缓存）：**

```
Ran 2 tests … FAILED (failures=1)
  FAIL: test_confirm_read_is_discarded_if_a_click_happened   ← 正是我们要它红的那条
   ok : test_first_read_is_usable_while_confirming
```

两次实验互不串台 —— 说明两条测试各自钉住了**不同的那一半**，没有一条是白搭的。
实验后已用备份还原，`md5sum` 与实验前一致（`deb997fe1aeba08a9a7b22ac857fad54`），
随后全套 334 条复跑仍全绿。

### 2.3 结果

```
$ rm -rf tests/__pycache__ voice_tap/__pycache__
$ python3 -m unittest discover -s tests
Ran 334 tests in 13.55s
OK
```

`tests.test_prefetch`：27 → **29** 条。全套：332 → **334** 条。

---

## 三、`tests/test_inventory.py`

`tests.test_prefetch` 基线 **27 → 29**，并注明理由（新类 `TestFirstReadIsUsableWhileConfirming`
两条 + 为什么用 `BlockingAdb`）。

顺手核对了**每一个**文件的基线 vs 实测值，只有 `test_prefetch` 一处需要动：

| 文件 | 基线 | 实测 |
|---|---|---|
| `tests.test_audio` | 19 | 19 |
| `tests.test_config` | 36 | 36 |
| `tests.test_hotkey` | 25 | 25 |
| `tests.test_matcher` | 57 | 57 |
| `tests.test_pipeline` | 120 | 120 |
| **`tests.test_prefetch`** | **27 → 29** | **29** |
| `tests.test_screen` | 27 | 27 |
| `tests.test_ui_state` | 7 | 7 |
| `tests.test_voice_gate` | 11 | 11 |

---

## 四、行为影响面

- `ScreenPrefetcher` 之外**一行未动**；`note()` 的语义（含时间戳护栏）一字未变，
  只是把写入抽成了 `_store_locked()`。
- 不带 `--gui` 时的行为，除本改动描述的这两点外没有变化。
- **新行为只影响「同一屏被连读两次」这条路径**：第一份先落缓存 → 等着的按键能立刻取用；
  若期间发生点击，则两次读到的结果都可能被作废（换代）。
  常态（翻页成功，只读一次）与「关掉点击后预读」两条路完全没变，都有既有测试兜着。

---

## 五、疑虑（照实说）

1. **`trigger_on_speech()` 没有加代数核对。**
   它有同一类风险：预读返回时若已换代，结果可能把点击前的屏写回缓存。
   但它**默认关着**（`config.yaml`），且简报把改动范围明确限定在 `trigger_after_click()`，
   所以我**没有动它** —— 属于「同类隐患、但不在本次范围」，如实提出来供决定。
   若要收口，改法与本次同构，一行 `self.note_if_current(…)` 即可。

2. **「作废即收工」会白丢一次预读。**
   若第一次读期间发生换代，这次预读直接收工、缓存留在空的状态；而那次点击触发的
   `trigger_after_click` 因为 `_busy` 被挡掉，**不会有新的预读接手** ——
   于是下一次按键只能走「当场读屏」兜底（**正确，但慢约 2.4 秒**）。
   简报要求「作废…然后收工」，所以按此实现；若想更快，可考虑换代后**重锚代数继续读**，
   但那要额外论证「第二次读确实反映点击后的新屏」，超出本次范围，故未做。

3. **`git add -A` 把上一轮遗留的未跟踪文件带进了本次提交。**
   `.superpowers/sdd/reports/r2-final-review.md`（第二轮全分支终审）在我开始前就是
   未跟踪状态。简报明确要求 `git add -A`，我照办了，特此说明，免得看起来像夹带。
   它正是本任务的动因（其中第 4 条「预读重试只做一半」就是本次要补的那一半）。

4. **`REQUIRED_CLASSES` 没有按名字钉住新测试类。**
   简报只要求「基线数字跟着实际更新」，所以我只改了数字。
   数量基线能挡住「整类被删」（29 → 27 < 29），但挡不住「换成等量的无关测试」。
   本项目对「静默点错」这类最忌讳的失败有按名字钉住的惯例（见 `test_inventory.py`
   里 `TestUnwiredIntents` 那段注释），要不要把
   `TestFirstReadIsUsableWhileConfirming` 也钉进去，留给评审定。

5. **未在真机上跑过。** 本任务是沙箱内的 TDD 改动，全部结论来自测试；
   `BlockingAdb` 模拟的是「单次读屏很慢」这一真机现象，真实耗时（约 2.4 秒/次）仍需上机复核。

# 任务简报：预读最多读两次


## 环境提示

- 项目根目录：bash 是 `/sessions/pensive-confident-cerf/mnt/声控手机项目`；文件工具是 `H:\声控手机项目\...`。
- **跑测试前先清字节码缓存**：`rm -rf tests/__pycache__ voice_tap/__pycache__`
  （本仓库 `.py` 与 `.pyc` 常同秒落盘，改动若不改变文件字节数，Python 会复用旧字节码 ——
  做「改坏看红不红」的实验时尤其必须，否则会得出错的结论。）
- 跑测试：`python3 -m unittest discover -s tests`（**没有 pytest**；沙箱缺 `pypinyin` 就先
  `pip install pypinyin --break-system-packages`）。
- **不要 `import tkinter`**（沙箱多半没装）；`gui.py` 用 `compile()` 查语法就行。
- **不要**碰 `.gitattributes` / `core.autocrlf` / `.bat` 文件。

## 一句话背景

`voice_tap`：Windows 上的声控工具，用户用 scrcpy 投屏安卓手机玩 GRE3000 背单词，
开口说选项、或按小键盘数字，程序读屏后自动点对应选项。**代码与注释全中文，
你写的注释、测试、提交信息也用中文。**

**这一轮的依据是真机日志** `debug/run_20260927_234859.log`（737 行），
计划里每条改动都引用了日志里的具体现象 —— **别凭感觉改**。


## 关键约束

## Global Constraints

- **测试命令**：`python3 -m unittest discover -s tests`（**没有 pytest**）。
- **跑测试前先清字节码缓存**：`rm -rf tests/__pycache__ voice_tap/__pycache__`。本仓库 `.py` 与 `.pyc` 常同秒落盘，改动若不改变文件字节数，Python 会复用旧字节码 —— 做「改坏看红不红」这类实验时会读出错误结论。
- 沙箱缺 `pypinyin` 就先 `pip install pypinyin --break-system-packages`。
- **不要 `import tkinter`**（沙箱多半没装）；`gui.py` 用 `compile()` 查语法。
- **不带 `--gui` 时行为除本计划明说的改动外不能变。**
- 不要碰 `.gitattributes` / `core.autocrlf` / `.bat`。
- **每写一条声称守住某行为的测试，先把它守的那段代码改坏一次，确认它真的会红。** 本项目的审查已经抓到过 6 次「测试看着像护栏、其实抓不住东西」，这是硬要求。
- 提交信息用中文。改测试基线数字时**必须在该文件里注明理由**（`test_inventory.py` 自己就是这么要求的）。
- 起始基线：**311 个测试全绿**（提交 `5dbe5f8` 之后）。

---

## 任务 2：预读最多读两次

**依据（日志实证）**：现在的 `trigger_after_click` 会重试最多 4 次，前提是「点完 App 就会翻页」。
但日志里**点完不翻页出现了 5 次**，于是每次白读 4 次：

```
[匹配] 小键盘第 2 个 → 点击坐标 (606, 999)
[点击] 完成
       [预读] 第 1 次还是旧界面 …（每次读屏约 2.4 秒）
       [预读] 第 4 次还是旧界面，距点击 10592 毫秒，再等等
       [预读] 试了 4 次都没读到变化，放弃
```

一次会话里「试了 4 次放弃」发生 5 次，最长拖到 **16843 毫秒**（第 4 次读屏本身跑了 8566 毫秒）。
这段期间用户的按键进不来。用户的原话：

> 发现读屏和上次一样后，再读一次就行，如果还是一样的话就说明确实没有变，而且一般第二次就不一样了。

**Files**
- Modify: `voice_tap/main.py`、`voice_tap/config.py`、`config.yaml`
- Test: `tests/test_prefetch.py`

**Interfaces**
- `PrefetchConfig.click_retry_ms` 保留（两次读之间的间隔）；**删除 `click_max_attempts`**（不再有第 3、4 次）

- [ ] **步骤 1：先改测试**

`tests/test_prefetch.py` 里现有 `test_gives_up_when_screen_never_changes` 断言「试满次数再放弃」，
**这个行为要没了**，改写成：

```python
    def test_never_changes_still_stores_after_two_reads(self):
        """
        界面一直没变（比如点完根本不翻页）—— 读两次就收下，不无限重试。

        用户的原话：连续两次读到的内容一样，就说明这就是当前屏幕。
        而现在的「读到的还和点击前一样就再读一次」，最多 4 次、白耗十秒，
        期间他的按键全被挡住。
        """
        prefetcher, adb, logs, _cfg = make_prefetcher(FIRST_XML, click_retry_ms=1)

        prefetcher.note(screen.read_screen(FIRST_XML))
        prefetcher.invalidate()
        prefetcher.trigger_after_click()
        self.assertTrue(wait_idle(prefetcher))

        self.assertEqual(adb.calls, 2, "最多读两次，不该有第 3、4 次")
        self.assertIsNotNone(prefetcher.take(), "第二次读到的就是当前屏，要收下")
        self.assertTrue(any("两次" in line or "确认" in line for line in logs))
```

再加一条：**读到新界面时只读一次**（不确认第二遍）：

```python
    def test_reads_once_when_screen_changed(self):
        prefetcher, adb, _logs, _cfg = make_prefetcher(FIRST_XML, SECOND_XML)

        prefetcher.note(screen.read_screen(FIRST_XML))
        prefetcher.invalidate()
        prefetcher.trigger_after_click()
        self.assertTrue(wait_idle(prefetcher))

        self.assertEqual(adb.calls, 1, "第一次就读到新界面就不该再读")
```

- [ ] **步骤 2：跑，确认新的那条红、旧的（`test_gives_up_...`）红**

- [ ] **步骤 3：改 `trigger_after_click`**

```python
        def work():
            delay = self.cfg.click_delay_ms / 1000.0
            retry = self.cfg.click_retry_ms / 1000.0
            started = time.monotonic()
            try:
                time.sleep(delay)
                read_start = time.monotonic()
                try:
                    snap = screen.read_screen(self.adb.dump_ui())
                except Exception as exc:  # noqa: BLE001
                    self.log(f"       [预读] 读屏失败（{type(exc).__name__}），放弃")
                    return

                if before is None or self.signature(snap) != before:
                    self.note(snap, read_at=read_start)
                    self.log(f"       [预读] 读到新界面，"
                             f"距点击 {(time.monotonic() - started) * 1000:.0f} 毫秒")
                    return

                # 和点击前一样：再读一次确认。
                #
                # **只确认一次，不再有第 3、4 次。** 理由（用户提出、日志支持）：
                # 连续两次读到同一屏，就说明这就是当前屏幕 —— 继续读不会读到别的，
                # 只会白耗时间（每次读屏约 2.4 秒），而这段时间用户的按键全被挡住。
                # 真机日志里有 5 次白读满 4 遍，最长拖了 16.8 秒。
                self.log("       [预读] 还是旧界面，再读一次确认")
                time.sleep(retry)
                read_start = time.monotonic()
                try:
                    snap = screen.read_screen(self.adb.dump_ui())
                except Exception as exc:  # noqa: BLE001
                    self.log(f"       [预读] 第二次读屏失败（{type(exc).__name__}），放弃")
                    return

                # 第二次无论读到什么，都收下 —— 它反映的就是当下这一屏。
                self.note(snap, read_at=read_start)
                if self.signature(snap) == before:
                    self.log("       [预读] 两次一样，认定这就是当前屏，收下")
                else:
                    self.log("       [预读] 第二次读到了新界面，收下")
            finally:
                with self._lock:
                    self._busy = False
```

- [ ] **步骤 4：删掉 `click_max_attempts`**

`config.py` 的 `PrefetchConfig` 去掉这个字段、`load_config` 里去掉那行；`config.yaml` 里整段注释删掉。
`tests/test_config.py` 若引用了它，一并改。

- [ ] **步骤 5：跑全套 + 「改坏看红不红」**

把「第二次也收下」改成「第二次仍一样就 return 不存」，确认 `test_never_changes_still_stores_after_two_reads` 变红，再改回来。

---

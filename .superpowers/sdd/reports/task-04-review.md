# 任务 4 审查报告：抽出 run_voice_loop

**结论：通过。** 纯重构成立，行为未变；254 全绿；工作区干净。

**1. 行为不变 —— 站得住。**
①`git diff b9651aa^..b9651aa -- tests/`：27 增 0 删，纯追加（无 `-` 行）。
②我独立提取旧 `main()` 的 while 体（main.py 958-993）与新 `run_voice_loop` 体（533-568），去缩进后逐行 diff：各 36 行，**唯一差异 `if args.once:` → `if once:`**（正是该改的那一处），其余逐字节相同——含 voice_gate 短路、两处实参（trigger_on_speech / peek）、`wait(0.2)`、`utterance is None` 与空文本两道 continue、AdbError 兜底、once 收尾。
③清缓存复跑：`Ran 254 tests ... OK`。

**2. 新用例 TestRunVoiceLoop 不是真护栏。**
实验：把 `run_voice_loop` 循环体整段删空、只留 `return`，清缓存后 `TestRunVoiceLoop ... ok` **仍绿**——因 quit 已置位，`while` 根本不进，删空与否都返回。它只守入口条件，**对循环体零约束**。已 `git checkout` 还原，工作区干净、254 全过。

**3. 覆盖缺口 —— 建议任务 5 改代码前补驱动测试。**
依据：(a) 实测证明现有唯一用例对循环体零约束，今天循环体各分支（voice_gate 短路 / else 按住说话 / 两处实参 / AdbError / once 收尾）**无一被跑过**，254 绿是假安全感；(b) 本重构恰好造出理想接缝（独立函数＋显式 ctx/hotkeys/recognizer 参数），假 Recognizer＋假 HotkeyManager 此刻最便宜；(c) 任务 5 就要改这个函数（wake_event、下传 stop_event）、任务 7 还要挪到后台线程——**行为基线只在改动前才有价值**，任务 5 之后再补等于把改动后的行为固化成「期望」。建议作为任务 5 的第 0 步（改代码前）落地。`main()` 装配层无测试属历史现状，不归本任务。

**4. finally 未动。** 独立提取 `worker_stop.set()` / `hotkeys.stop()` / `recognizer.close()` 三行，旧新 `repr` 逐行一致、顺序相同；`try/except KeyboardInterrupt/finally` 结构原样。

**发现的问题：无阻断性问题。** 提示（非缺陷）：勿据新用例宣称「主循环有测试」。

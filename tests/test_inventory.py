#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_inventory.py —— 测试清单检查

**由来**：有一次我用正则批量删除测试类，正则的结束条件写得太宽
（`(?=\\nif __name__)`），把后面两个类一起吞掉了 —— 其中包括「下一题」
的全部测试。当时套件**仍然是全绿的**，只是少了 25 个用例，我完全没察觉。

一个「全部通过但偷偷变少」的测试套件，比失败的套件更危险：
失败会告诉你出了问题，而悄悄变少只是安静地失去了保护。

所以这里钉住几条底线：

  1. 每个测试文件的用例数不得低于已知基线（要改就得来这里显式改，改动会被看见）
  2. 几个关键行为必须有对应的测试类 —— 它们是安全性的最后防线
  3. 所有测试文件都必须能被正常收集

如果这个文件报错，先别急着调数字，先确认**是不是又有测试被误删了**。
"""

import importlib
import unittest


# 各测试文件的用例数基线。
# 数字只增不减 —— 低于基线说明有测试消失了，要么找回来，要么在这里写下理由。
BASELINE_COUNTS = {
    "tests.test_audio": 19,
    # 17 → 34：补上 gui.* 解析与「配置段写歪不能把程序拦在门外」两批用例
    # （TestGuiConfig / TestNonMappingSections）。基线贴着实际值，
    # 免得整类被删掉时用例数还高于基线、单靠数字发现不了。
    # 2026-09-28（任务 3）：34 → 36 —— `voice.next_command`（原来默认 true）并入
    # `voice.commands` 并改成**默认关**。老类 `TestVoiceNextCommand`（3 条：
    # 默认开、随附配置是开、显式写关）换成 `TestVoiceCommandsSwitch`（5 条：
    # 默认关、随附的 config.yaml 是关、显式写开能解析、显式写关不能解析歪、
    # 老键 next_command 已从数据类里消失）。净 +2。
    "tests.test_config": 36,
    "tests.test_hotkey": 25,
    # 51 → 53：补上控制语识别的 TestDetectControl（说「下一题」走哪条路）
    # 2026-09-28（任务 3）：53 → 57 —— `voice.commands` 关掉时「说序号」这条路
    # 要停用并退回文字匹配，而「说单词选选项」那条路不受它管。
    # TestOrdinalCanBeDisabled 四条钉住这件事（默认照常、关掉后序号说法落空、
    # 文字匹配不受影响、中文序号也一并挡住）。
    "tests.test_matcher": 57,
    # 59 → 103：界面与语音「下一题」那一期加进来的用例（UiState 接线、
    # 动作时戳、意图/唤醒、窗口几何……）。基线贴着实际值。
    # 103 → 106：「下一题」固定坐标路径的前台护栏（peek 返回别的 App / None /
    # GRE3000 三种情形）三条用例。
    # 2026-09-28：删掉 TestActionStamp 的 5 个用例 —— 动作时戳按用户要求取消，
    # 理由见 tests/test_pipeline.py 里那段注释。
    # 101 → 104：补上界面按钮接线的三条护栏 —— on_intent 入队是二元组、
    # 入队条目走真接线能真执行意图、解不开的条目要出声。就是防这次的 bug：
    # 入队三元组没跟上二元组改动，界面每个按钮都点了没反应。
    # 2026-09-28（任务 4）：104 → 120 —— 控件改成由 collect_state 数据驱动
    # （按钮文字/意图名/快捷键/布局全在 main.py 算，gui.py 只照着摆）后补的 12 条：
    # 按钮文字含快捷键、快捷键取自 cfg.hotkey、没快捷键的控件不带后缀、
    # 识别语言文字跟着当前语言变、两行三列的布局、每个按钮都带意图名，
    # 以及 cycle_language / toggle_voice_commands 两条真接线和 unwired_intents 三条。
    # 2026-09-28（任务 7）：120 → 123 —— 按键不再等预读（用最近读到那一屏的坐标立刻点）。
    # 新增 TestKeyPressUsesLastSeenScreen 三条：
    #   「缓存空时按键一次屏都不读、直接用最近读到那一屏第 3 个选项的坐标点」
    #   「一次都没读到过时才当场读一次」（这一档行为未变，是护栏）
    #   「语音那条路没被改：缓存空仍然当场读屏，不用 peek 的旧坐标」
    # 第一条是这次改动的主证据（改之前 dump_calls == 1，改之后 == 0）。
    # 2026-09-28（任务 8）：123 → 128 —— 预读读到的屏要**播出去**（用户实测：
    # 界面和控制台只显示点击前那一屏，永远慢一拍）。新增五条：
    #   TestForceRead.test_broadcasts_the_fresh_screen_to_the_ui（强制读屏 → 来源「强制读屏」）
    #   TestScreenPublisher 两条（播给界面 + 控制台那行来源；没开界面时照打）
    #   TestUiStateWiring.test_grab_screen_publishes_the_fresh_read_only_once
    #     （当场读屏那条路只能播一遍 —— 播报搬进 note() 之后，原来那句
    #      publish_screen 必须去掉；两处都留着界面看着一样，只有次数分得出来）
    #   TestPrefetchedScreenReachesTheUiWithNoExtraKey 一条（**主证据**：
    #     只按一次键、之后不再有任何输入，界面里那一屏自己变成新题）
    # 2026-09-28（r2 任务 9）：128 → 130 —— 同一屏不再打两遍（用户实测：
    # 「之前展示了预读的，为什么我点击后又要展示一次预读」）。动作路径上那两句
    # 重复的 show_screen（handle_numpad / handle_speech）去掉之后，用
    # TestSameScreenIsPrintedOnlyOnce 两条钉住「那一屏的题干只出现一次」：
    #   按键那条路（handle_numpad）与语音那条路（handle_speech）各一条。
    #   两条都走**真接线**（真 ScreenPrefetcher + make_screen_publisher），
    #   把整段控制台输出收下来数一数；把 show_screen 加回去计数就变 2。
    "tests.test_pipeline": 130,
    # 26 → 27：预读改成「最多读两次」（见 test_prefetch.py）。原有的
    # 「试满次数再放弃」改写成「一直没变也收下」（1 条），另加「读到新界面只读一次」（1 条），
    # 共 +1。
    # 2026-09-28（任务 6）：27 → 29 —— 按键不必再等预读的「确认」那一次读。
    # 新增 TestFirstReadIsUsableWhileConfirming 两条：
    #   「预读卡在第二次读上时，第一次读到的就能被 take 走」
    #   「第二次读还在路上时若发生了点击（换代），这一份必须作废、不许写回缓存」
    # 两条都靠测试里的 BlockingAdb（第二次 dump_ui 阻塞在 Event 上）把时序钉死，
    # 不靠 sleep 碰运气。净 +2。
    # 2026-09-28（任务 7）：29 → 33 —— 新增 peek_with_age()（带年龄的「最近见过那一屏」），
    # 落成 TestPeekWithAge 四条：从没读到过返回 None、年龄按那一屏读到的时刻算、
    # **作废缓存后年龄仍从那一屏读到的时刻算**（invalidate 会把 `_at` 清零而
    # `_last_seen_at` 不清，混用会喊出「开机以来」那么大的数）、以及
    # 「超过 cache_max_age 也照样交出来」——最后这条钉的是用户明确要的
    # 「不做时间保险、一律不等」，是取舍不是遗漏。净 +4。
    # 2026-09-28（任务 8）：33 → 40 —— `ScreenPrefetcher` 新增 `on_screen` 回调：
    # note() 每存下一份新屏就播给界面和控制台。落成 TestBroadcastScreen 七条：
    #   不传回调 = 老行为（照旧只存不播）、note() 不传 source 就不播、
    #   **预读读到新界面会自己播出去（主证据，来源「预读」）**、
    #   同一屏不播两遍（「还是旧界面 → 再读一次确认」那条路会把同一屏存两次）、
    #   已经摆在界面上的一屏不再播（翻页没发生时控制台不被刷第二遍）、
    #   内容变了才播、被丢弃的旧读屏不许播（理由同「不许写回缓存」）。
    # 2026-09-28（r2 任务 9）：40 → 42 —— 连点两下时不再丢掉后来的预读请求
    # （用户真机日志：两下过去一次预读都不剩，缓存空、也没人在读）。加
    # TestDoubleClickDoesNotDropThePrefetch 两条：
    #   「第二下之后按新代数重跑，缓存里是第二下之后读到的那一屏，且始终只有一个
    #    dump 在跑」（**主证据**，用 BlockingAdb 把「卡在第二次读上」这一刻钉死）
    #   「第二次 trigger_after_click() 要留下重启标记、并且真的兑现，不能静默丢掉」
    # 旧代码下第一条断言「缓存里必须有东西」就红（缓存是空的）。
    "tests.test_prefetch": 42,
    "tests.test_screen": 27,
    # 7：UiState（线程安全状态黑板）—— 界面与主逻辑唯一的交汇点
    "tests.test_ui_state": 7,
    "tests.test_voice_gate": 11,
}


# 关键行为必须有测试。挑的都是「出问题会造成点错或不能点」的那些。
REQUIRED_CLASSES = {
    "tests.test_pipeline": [
        "TestSafetyGuard",                 # 不该点的时候绝不点
        "TestKeyPressesAreNeverTimeBlocked",  # 按键动作不受时间限制
        "TestNextButton",                  # 答错后能翻回下一题
        "TestPrefetchIsTriggeredAfterClick",
        "TestCachedScreenIsUsed",          # 预读的界面要被真正用上
        # 2026-09-28（任务 8）：预读读到的屏要**自己**出现在界面上（不用再按键）——
        # 这是用户实测那个「永远慢一拍」的缺陷本身。删掉它，这条线就没有用例拦得住了。
        "TestPrefetchedScreenReachesTheUiWithNoExtraKey",
        "TestScreenPublisher",             # 播给界面 + 控制台（接线只此一处）
        # 2026-09-28（任务 7）：按键「不等预读、直接用最近读到那一屏的坐标」是本轮
        # 唯一重新引入「用旧坐标点新题」风险的决定（用户明确选的取舍）。这一整类
        # 就是那道风险的记录：删掉它，改动本身就没有任何用例能拦住回归了。
        "TestKeyPressUsesLastSeenScreen",  # 按键不等预读；语音那条路的取舍不变
        "TestStartupProbe",                # 启动那一屏要被缓存（省掉第一次读屏）
        "TestActionWiring",                # 入队 → 解包分派这条接线
        "TestForceRead",                   # 小键盘 . 强制重新读屏
        "TestVoiceMutedAfterClick",        # 点完不监听（手机在念单词）
        "TestLogging",
        # 下面这一批钉的是界面那几块拼图与主循环本身。它们都不是「多一个点错的
        # 风险」那种防线，而是「界面到底有没有接上、开关能不能真的生效」——
        # 删掉任何一个，真机上都会表现成「界面永远空着 / 按钮没反应」，
        # 而普通用例往往照样全绿。所以这里按**名字**把它们钉住：
        # 即便有人改名换成一个等量的无关测试、总数对得上，这一条也会红。
        "TestRunVoiceLoop",                # 主循环能被抽出来单独跑（界面要占主线程）
        "TestRunVoiceLoopBranches",        # 主循环循环体的各条分支
        "TestHandleIntent",                # 界面按钮与热键走同一份代码
        "TestToggleFlag",                  # 界面上的预读／语音选择开关
        "TestAnyEvent",                    # 退出请求与唤醒合成一个中断源
        "TestVoiceNextCommand",            # 说「下一题」= 点下一题
        "TestCollectState",                # 界面显示的数据来源
        # 2026-09-28（任务 4）：界面按钮的全部行为就是「把意图名交出去」，
        # 表里没有 = 这个按钮静默死掉（真机上表现为「点了没反应」，而测试全绿）。
        # 这条函数把静默变成出声，是本轮那次事故的护栏，按名字钉住：
        "TestUnwiredIntents",              # 界面会发、意图表里却没有的名字要当场喊出来
        "TestUiStateWiring",               # 主流程有没有真的把数据交给界面
        "TestUiWiringWithoutUi",           # 没开界面时一切照旧
        "TestWindowGeometry",              # 窗口几何的存／读／坏值兜底
    ],
    "tests.test_screen": [
        "TestForegroundGuard",             # 前台应用护栏
        "TestDetailPage",                  # 详情页识别
        "TestClickPointResolution",        # 点哪里
        "TestLanguageAndHint",             # 用屏幕内容辅助识别
    ],
    "tests.test_matcher": [
        "TestOrdinalMatch",                # 说序号
        "TestStemMatch",                   # 英语词形（原形 vs 变形）
        "TestAmbiguity",                   # 多候选怎么取舍
        "TestNoMatch",                     # 匹配不上就不点
        "TestDetectControl",               # 控制语识别（「下一题」走直给那条路）
        # 2026-09-28（任务 3）：`voice.commands` 关掉「说序号」这条路，是本轮
        # 按真机日志做的安全决定（环境杂音念出「第一个」就点了）。整类删掉时
        # 用例数会掉到基线以下，但**改成等量的无关测试**就发现不了 —— 所以钉名字。
        "TestOrdinalCanBeDisabled",        # 关掉后序号说法退回文字匹配
    ],
    "tests.test_config": [
        # 2026-09-28（任务 3）：本轮唯一改了默认值的开关就在这里。它管着
        # 「说序号」「说下一题」两类过于短促、易误触发的说法，默认关是用户的
        # 明确要求；老键 next_command 必须彻底消失，不能留个能改回来的影子。
        "TestVoiceCommandsSwitch",         # voice.commands 默认关、老键已删除
    ],
    "tests.test_ui_state": [
        "TestIntents",                     # 界面 → 主逻辑的意图队列
    ],
    "tests.test_prefetch": [
        "TestInvalidateKeepsSignature",    # 作废缓存不能连指纹一起清掉
        "TestTriggerAfterClick",           # 翻页检测
        "TestPeek",                        # 识别要用的「最近见过的界面」
        "TestMissReason",                  # 落空要能说清「没有」还是「过期了」
        # 2026-09-28（任务 8）：预读读到的新屏要**播出去**（界面 + 控制台）——
        # 用户实测「只有点击后才显示上一屏，永远慢一拍」就是这个没接上。
        # 整类删掉时用例数会掉到基线以下，但**改成等量的无关测试**就发现不了，
        # 所以按名字钉住。
        "TestBroadcastScreen",             # 存下一份新屏就播；同一屏不播两遍
    ],
    "tests.test_voice_gate": [
        "TestSuppress",                    # 静音期
        "TestWaitUntilOpen",               # 等待与退出
        "TestToggle",                      # 语音总开关
    ],
    "tests.test_audio": [
        "TestListenUntilSilence",          # 静音切句
    ],
    "tests.test_hotkey": [
        "TestNumpadFiltering",             # 只认小键盘，主键盘放过
        "TestAutoRepeatSuppression",       # 按住不放不重复触发
        "TestForceReadKey",                # 小键盘 . 触发强制读屏
        "TestVoiceToggleKey",              # F7 开关语音
    ],
}


def count_test_cases(module_name):
    """数一数某个测试文件里有多少个用例"""
    module = importlib.import_module(module_name)
    suite = unittest.TestLoader().loadTestsFromModule(module)
    return suite.countTestCases()


class TestInventory(unittest.TestCase):

    def test_no_module_lost_cases(self):
        """用例数不能低于基线 —— 低了就说明有测试被删掉了"""
        problems = []
        for module_name, baseline in sorted(BASELINE_COUNTS.items()):
            try:
                actual = count_test_cases(module_name)
            except Exception as exc:  # noqa: BLE001
                problems.append(f"{module_name} 收集失败：{type(exc).__name__}: {exc}")
                continue
            if actual < baseline:
                problems.append(
                    f"{module_name} 少了 {baseline - actual} 个用例（现在 {actual}，基线 {baseline}）")

        self.assertEqual(
            problems, [],
            "有测试消失了：\n      " + "\n      ".join(problems) +
            "\n      先确认是不是被误删了；确实要减，就在 test_inventory.py 里改基线并注明理由")

    def test_critical_behaviours_still_covered(self):
        """几个关键行为必须有测试类顶着"""
        problems = []
        for module_name, class_names in sorted(REQUIRED_CLASSES.items()):
            try:
                module = importlib.import_module(module_name)
            except Exception as exc:  # noqa: BLE001
                problems.append(f"{module_name} 导入失败：{exc}")
                continue
            for class_name in class_names:
                if not hasattr(module, class_name):
                    problems.append(f"{module_name} 里找不到 {class_name}")

        self.assertEqual(
            problems, [],
            "关键行为的测试不见了：\n      " + "\n      ".join(problems))

    def test_all_test_files_are_collectable(self):
        """每个列在基线里的文件都要能被正常收集，不能因为语法错就悄悄消失"""
        for module_name in sorted(BASELINE_COUNTS):
            with self.subTest(module=module_name):
                self.assertGreater(count_test_cases(module_name), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)

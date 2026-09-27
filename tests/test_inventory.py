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
    "tests.test_config": 17,
    "tests.test_hotkey": 25,
    "tests.test_matcher": 51,
    "tests.test_pipeline": 54,
    "tests.test_prefetch": 26,
    "tests.test_screen": 27,
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
        "TestStartupProbe",                # 启动那一屏要被缓存（省掉第一次读屏）
        "TestForceRead",                   # 小键盘 . 强制重新读屏
        "TestVoiceMutedAfterClick",        # 点完不监听（手机在念单词）
        "TestLogging",
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
    ],
    "tests.test_prefetch": [
        "TestInvalidateKeepsSignature",    # 作废缓存不能连指纹一起清掉
        "TestTriggerAfterClick",           # 翻页检测
        "TestPeek",                        # 识别要用的「最近见过的界面」
        "TestMissReason",                  # 落空要能说清「没有」还是「过期了」
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

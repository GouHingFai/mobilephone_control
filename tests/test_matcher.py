#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_matcher.py —— 匹配引擎测试

匹配引擎是整个项目唯一能完全靠测试锁死正确性的模块（它不依赖手机、不依赖麦克风），
所以这里覆盖得比较密：三级匹配、多候选消歧、最小长度门槛、各种脏输入。
"""

import unittest
from pathlib import Path

from voice_tap import matcher, screen
from voice_tap.config import MatchConfig

FIXTURES = Path(__file__).resolve().parent / "fixtures"


class FakeNode:
    """只需要 .text 和 .y 就能参与匹配"""

    def __init__(self, text, y=0):
        self.text = text
        self.y = y
        self.x = 100
        self.resource_id = screen.ID_OPTION

    def __repr__(self):
        return f"<{self.text}>"


def options(*texts):
    return [FakeNode(t, y=i * 100) for i, t in enumerate(texts)]


def real_options(fixture):
    xml = (FIXTURES / fixture).read_text(encoding="utf-8")
    return screen.read_screen(xml).options


CFG = MatchConfig()


class TestNormalize(unittest.TestCase):

    def test_strips_punctuation_and_case(self):
        self.assertEqual(matcher.normalize("adj. 清晰易懂的"), "adj清晰易懂的")
        self.assertEqual(matcher.normalize("ADJ. 清晰易懂的"), "adj清晰易懂的")
        self.assertEqual(matcher.normalize("  Apple  "), "apple")

    def test_chinese_punctuation(self):
        # 顿号、逗号、括号都该被丢掉
        self.assertEqual(matcher.normalize("简单、朴素"), "简单朴素")
        self.assertEqual(matcher.normalize("降低，恶化，贬低"), "降低恶化贬低")

    def test_fullwidth_to_halfwidth(self):
        self.assertEqual(matcher.normalize("ＡＢＣ"), "abc")
        self.assertEqual(matcher.normalize("１２３"), "123")

    def test_empty(self):
        self.assertEqual(matcher.normalize(""), "")
        self.assertEqual(matcher.normalize(None), "")
        self.assertEqual(matcher.normalize("，。！？"), "")


class TestPinyin(unittest.TestCase):

    def test_basic(self):
        self.assertEqual(matcher.to_pinyin("清晰"), "qingxi")

    def test_homophones_collapse(self):
        """同音字必须映射到同一个拼音 —— 这是拼音容错能成立的前提"""
        self.assertEqual(matcher.to_pinyin("骄奢淫逸"), matcher.to_pinyin("骄奢淫意"))

    def test_keeps_latin(self):
        self.assertEqual(matcher.to_pinyin("apple"), "apple")


class TestEditDistance(unittest.TestCase):

    def test_basic(self):
        self.assertEqual(matcher.edit_distance("apple", "apple"), 0)
        self.assertEqual(matcher.edit_distance("apple", "aple"), 1)
        # apple 五次替换成 orange，再插一个 s —— 共 6 步
        self.assertEqual(matcher.edit_distance("apple", "oranges"), 6)

    def test_ceiling_early_exit(self):
        self.assertGreater(matcher.edit_distance("apple", "xxxxxxxx", 1), 1)

    def test_window_distance_ignores_long_prefix(self):
        """
        选项比用户说的长很多时，滑动窗口才能反映「其中一段像不像」。
        直接整串比会被前缀拉开距离，那样模糊匹配就永远触发不了。
        """
        # 「清晰易懂的」 vs 「adj清晰易懂的」：整串距离是 3，但窗口距离是 0~1
        self.assertLessEqual(matcher.best_window_distance(
            "清晰易懂的", "adj清晰易懂的", 2), 2)
        self.assertEqual(matcher.edit_distance("清晰易懂的", "adj清晰易懂的"), 3)


class TestSubstringMatch(unittest.TestCase):
    """主力路径：用户只说选项里的一小部分"""

    def test_real_gre_options(self):
        opts = real_options("gre_degrade.xml")

        result = matcher.match("清晰", opts, CFG)
        self.assertTrue(result.ok)
        self.assertEqual(result.node.text, "adj. 清晰易懂的")
        self.assertEqual(result.level, matcher.LEVEL_SUBSTRING)

    def test_user_example_jian_dan(self):
        """用户原话：选项是「简单、朴素」，说「简单」就该点它"""
        opts = options("简单、朴素", "复杂的", "昂贵的", "危险的")
        result = matcher.match("简单", opts, CFG)
        self.assertTrue(result.ok)
        self.assertEqual(result.node.text, "简单、朴素")

    def test_says_the_second_part_too(self):
        """说「朴素」同样该命中"""
        opts = options("简单、朴素", "复杂的")
        result = matcher.match("朴素", opts, CFG)
        self.assertEqual(result.node.text, "简单、朴素")

    def test_english_substring(self):
        opts = real_options("gre_prototype.xml")
        result = matcher.match("狂怒", opts, CFG)
        self.assertEqual(result.node.text, "adj. 狂怒的")

    def test_case_and_punctuation_insensitive(self):
        opts = options("adj. 清晰易懂的")
        result = matcher.match("ADJ清晰易懂的", opts, CFG)
        self.assertTrue(result.ok)


class TestMinLengthGuard(unittest.TestCase):
    """最小长度门槛：避免一个「的」字把四个选项全匹配上"""

    def test_single_char_is_rejected(self):
        opts = options("adj. 清晰易懂的", "adj. 阴郁的", "v. 降低的")
        result = matcher.match("的", opts, CFG)
        self.assertFalse(result.ok, "单个字不该匹配")

    def test_two_chars_is_allowed(self):
        opts = options("adj. 清晰易懂的", "v. 降低的")
        result = matcher.match("清晰", opts, CFG)
        self.assertTrue(result.ok)


class TestPinyinMatch(unittest.TestCase):

    def test_homophone_rescue(self):
        """
        ASR 把「骄奢淫逸」听成「骄奢淫意」时，字形对不上但读音一致，
        拼音这一级应该把它救回来。
        """
        opts = real_options("gre_degrade.xml")
        result = matcher.match("骄奢淫意", opts, CFG)

        self.assertTrue(result.ok, "同音字应当被拼音匹配救回")
        self.assertEqual(result.node.text, "adj. 骄奢淫逸的，耽于感官享受的")
        self.assertEqual(result.level, matcher.LEVEL_PINYIN)

    def test_pinyin_level_is_what_catches_homophones(self):
        """
        关掉拼音后，同音字不该再走「拼音命中」这一级。
        （可能被模糊匹配兜住 —— 那是另一层保险，但级别必须不同。）
        """
        cfg = MatchConfig(pinyin_enabled=False)
        opts = real_options("gre_degrade.xml")
        result = matcher.match("骄奢淫意", opts, cfg)
        self.assertNotEqual(result.level, matcher.LEVEL_PINYIN,
                            "拼音关掉后不该再出现拼音命中")

    def test_both_layers_off_means_no_match(self):
        """拼音和模糊都关掉，同音字就真的匹配不上了"""
        cfg = MatchConfig(pinyin_enabled=False, fuzzy_enabled=False)
        opts = real_options("gre_degrade.xml")
        result = matcher.match("骄奢淫意", opts, cfg)
        self.assertFalse(result.ok, "两层保险都关掉后应该匹配不上")


class TestContainsReverseMatch(unittest.TestCase):
    """用户把整个选项念了一遍，前面还带「我选」之类"""

    def test_spoken_contains_option(self):
        opts = options("adj. 狂怒的", "不记得了", "n. 原型，样品")
        result = matcher.match("我选不记得了", opts, CFG)
        self.assertTrue(result.ok)
        self.assertEqual(result.node.text, "不记得了")


class TestFuzzyMatch(unittest.TestCase):

    def test_one_letter_typo(self):
        opts = options("split", "graze", "intimidate", "divulge")
        result = matcher.match("spllit", opts, CFG)
        self.assertTrue(result.ok, "听错一个字母应当被模糊匹配救回")
        self.assertEqual(result.node.text, "split")

    def test_fuzzy_can_be_disabled(self):
        cfg = MatchConfig(fuzzy_enabled=False, pinyin_enabled=False)
        opts = options("split", "graze")
        result = matcher.match("spllit", opts, cfg)
        self.assertFalse(result.ok)


class TestNoMatch(unittest.TestCase):

    def test_completely_unrelated(self):
        opts = real_options("gre_degrade.xml")
        result = matcher.match("香蕉苹果橘子", opts, CFG)
        self.assertFalse(result.ok)
        self.assertEqual(result.level, 0)

    def test_empty_speech(self):
        opts = real_options("gre_degrade.xml")
        self.assertFalse(matcher.match("", opts, CFG).ok)
        self.assertFalse(matcher.match("，。", opts, CFG).ok)

    def test_empty_options(self):
        self.assertFalse(matcher.match("清晰", [], CFG).ok)


class TestAmbiguity(unittest.TestCase):

    def test_multiple_candidates_flags_ambiguous(self):
        """「adj」同时出现在三个选项里，应该标记为歧义但依然给出一个选择"""
        opts = real_options("gre_degrade.xml")
        result = matcher.match("adj", opts, CFG)

        self.assertTrue(result.ok)
        self.assertTrue(result.ambiguous)
        self.assertEqual(len(result.candidates), 3)

    def test_unique_match_is_not_ambiguous(self):
        opts = real_options("gre_degrade.xml")
        result = matcher.match("清晰", opts, CFG)
        self.assertFalse(result.ambiguous)
        self.assertEqual(len(result.candidates), 1)

    def test_exact_beats_substring(self):
        """
        说「简单」时，一个选项恰好就是「简单」，另一个是「简单、朴素」。
        精确匹配优先级更高，直接命中前者，不该报歧义。
        """
        opts = options("简单、朴素", "简单")
        result = matcher.match("简单", opts, CFG)
        self.assertTrue(result.ok)
        self.assertFalse(result.ambiguous)
        self.assertEqual(result.level, matcher.LEVEL_EXACT)
        self.assertEqual(result.node.text, "简单")

    def test_higher_coverage_wins(self):
        """
        同为子串命中时，取匹配最"专一"的：说的词占选项比例越高越可信。
        「简单」占「简单朴素」的 1/2，占「很简单」的 2/3 —— 应该选后者。
        """
        opts = options("简单朴素", "很简单")
        result = matcher.match("简单", opts, CFG)
        self.assertTrue(result.ok)
        self.assertTrue(result.ambiguous)
        self.assertEqual(result.node.text, "很简单")

    def test_tie_breaks_by_screen_order(self):
        opts = options("简单朴素", "简单明了")
        result = matcher.match("简单", opts, CFG)
        self.assertTrue(result.ambiguous)
        self.assertEqual(result.node.text, "简单朴素", "平手时取屏幕上靠前的")


class TestOrdinalMatch(unittest.TestCase):
    """
    说序号：生僻词 ASR 容易听错，但「1、2、3」几乎不可能听错。
    遇到拼不出来的选项，直接说序号最稳。
    """

    def test_bare_digit(self):
        opts = real_options("gre_degrade.xml")
        result = matcher.match("3", opts, CFG)

        self.assertTrue(result.ok)
        self.assertEqual(result.level, matcher.LEVEL_ORDINAL)
        self.assertTrue(result.by_ordinal)
        self.assertEqual(result.ordinal_index, 3)
        self.assertEqual(result.node.text, "adj. 骄奢淫逸的，耽于感官享受的")

    def test_chinese_numeral(self):
        opts = real_options("gre_degrade.xml")
        self.assertEqual(matcher.match("二", opts, CFG).node.text, "adj. 阴郁的，闷闷不乐的")

    def test_with_measure_word(self):
        opts = real_options("gre_degrade.xml")
        self.assertEqual(matcher.match("第一个", opts, CFG).node.text, "adj. 清晰易懂的")

    def test_with_verb_prefix(self):
        opts = real_options("gre_degrade.xml")
        result = matcher.match("我选第五个", opts, CFG)
        self.assertEqual(result.ordinal_index, 5)
        self.assertEqual(result.node.text, "不记得了")

    def test_the_last_one(self):
        opts = real_options("gre_degrade.xml")
        result = matcher.match("最后一个", opts, CFG)
        self.assertTrue(result.by_ordinal)
        self.assertEqual(result.node.text, "不记得了")

    def test_click_coordinates_follow_the_ordinal(self):
        """说几号就点第几行 —— 坐标必须落在对应那一行里"""
        opts = real_options("gre_degrade.xml")
        rows = {
            1: (736, 886),
            2: (924, 1074),
            3: (1112, 1262),
            4: (1300, 1450),
            5: (1488, 1638),
        }
        for number, (low, high) in rows.items():
            with self.subTest(number=number):
                result = matcher.match(str(number), opts, CFG)
                self.assertTrue(result.ok, f"说 {number} 应该能匹配")
                self.assertTrue(low <= result.node.y <= high,
                                f"说 {number} 点到了 y={result.node.y}，不在 [{low},{high}] 行内")

    def test_out_of_range_is_reported(self):
        """只有 5 个选项时说 9，不该瞎点，并且要能报出「你说了第 9 个」"""
        opts = real_options("gre_degrade.xml")
        result = matcher.match("9", opts, CFG)

        self.assertFalse(result.ok)
        self.assertEqual(result.ordinal_out_of_range, 9)

    def test_out_of_range_falls_back_to_text(self):
        """
        序号超出范围时不该直接放弃 —— 万一选项文字里真有个数字，
        应该继续按文字去匹配。
        """
        opts = options("9号", "别的", "又一")
        result = matcher.match("9", opts, CFG)

        self.assertTrue(result.ok, "超出序号范围后应该落回文字匹配")
        self.assertEqual(result.node.text, "9号")
        self.assertEqual(result.level, matcher.LEVEL_SUBSTRING)

    def test_ordinal_takes_priority_over_text(self):
        """
        说「1」时，即使某个选项的文字里含「1」，也按序号来 ——
        序号是最明确的意图，不该被文字匹配抢走。
        """
        opts = options("第1个选项", "别的选项")
        result = matcher.match("1", opts, CFG)

        self.assertTrue(result.by_ordinal)
        self.assertEqual(result.node.text, "第1个选项")

    def test_non_ordinal_speech_is_unaffected(self):
        """普通的词不该被误判成序号"""
        opts = real_options("gre_degrade.xml")
        result = matcher.match("清晰", opts, CFG)
        self.assertFalse(result.by_ordinal)
        self.assertEqual(result.level, matcher.LEVEL_SUBSTRING)

    def test_parse_ordinal_rejects_words(self):
        for word in ("清晰", "apple", "", "，。", "选项", "第", "个"):
            with self.subTest(word=word):
                self.assertIsNone(matcher.parse_ordinal(word), f"{word!r} 不该被当成序号")

    def test_parse_ordinal_accepts_common_forms(self):
        cases = {
            "1": 1, "一": 1, "第一个": 1, "第1个": 1, "选三": 3, "我选2": 2,
            "第五个": 5, "十": 10, "选项2": 2, "第 4 个": 4,
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(matcher.parse_ordinal(text), expected)

    def test_last_ordinal_forms(self):
        for text in ("最后一个", "最后", "最末一个"):
            with self.subTest(text=text):
                self.assertEqual(matcher.parse_ordinal(text), matcher.ORDINAL_LAST)


class TestStemMatch(unittest.TestCase):
    """
    英语词形匹配。这一级是看了真机日志才加的。

    用户说 qualify，识别成 "Qualified"；说 retrieve，识别成 "retrieving"。
    而屏幕上的选项是词典原形。原来的子串/包含两级都处理不了 ——
    qualify 不是 qualified 的子串（y 变成了 ied），retrieve 不是 retrieving 的子串
    （e 变成了 i）。结果就是"明明听对了却匹配不上"。
    """

    def test_real_failures_from_the_log(self):
        qualifying = options("hallow", "qualify", "requisite", "rouse", "不记得了")
        for spoken in ("Qualified", "qualified.", "Qualified."):
            with self.subTest(spoken=spoken):
                result = matcher.match(spoken, qualifying, CFG)
                self.assertTrue(result.ok, f"{spoken!r} 应该命中 qualify")
                self.assertEqual(result.node.text, "qualify")

        retrieving = options("contiguous", "extremist", "philanthropy", "retrieve", "不记得了")
        for spoken in ("retrieving", "retrieved."):
            with self.subTest(spoken=spoken):
                result = matcher.match(spoken, retrieving, CFG)
                self.assertTrue(result.ok, f"{spoken!r} 应该命中 retrieve")
                self.assertEqual(result.node.text, "retrieve")

    def test_stem_is_more_trustworthy_than_fuzzy(self):
        """词形命中应该排在模糊匹配前面 —— 它更可信"""
        opts = options("qualify", "hallow")
        result = matcher.match("qualified", opts, CFG)
        self.assertEqual(result.level, matcher.LEVEL_STEM)

    def test_genuine_mishearing_still_fails(self):
        """真的是听错就还是匹配不上，不能靠这一级硬凑"""
        opts = options("contiguous", "extremist", "philanthropy", "retrieve", "不记得了")
        result = matcher.match("Retreat.", opts, CFG)
        self.assertFalse(result.ok, "retreat 和 retrieve 是两个词，不该硬匹配")

    def test_does_not_mangle_short_words(self):
        """很短的词不能被砍成两三字母后到处乱撞"""
        self.assertEqual(matcher.stem_candidates("as"), {"as"})
        self.assertEqual(matcher.stem_candidates("bed"), {"bed"})
        self.assertEqual(matcher.stem_candidates("bus"), {"bus"})

    def test_does_not_touch_chinese(self):
        """中文原样返回，不会误伤"""
        self.assertEqual(matcher.stem_candidates("简单"), {"简单"})
        opts = options("简朴", "复杂")
        self.assertFalse(matcher.match("简单", opts, CFG).ok)


class TestRealScreenEndToEnd(unittest.TestCase):
    """从真实 XML 一路走到匹配结果"""

    def test_degrade_question_flow(self):
        xml = (FIXTURES / "gre_degrade.xml").read_text(encoding="utf-8")
        snap = screen.read_screen(xml)

        self.assertTrue(snap.ok)
        self.assertEqual(snap.prompt, "degrade")

        # 用户想说「清晰易懂的」，只说「清晰」
        result = matcher.match("清晰", snap.options, CFG)
        self.assertTrue(result.ok)
        self.assertEqual(result.node.text, "adj. 清晰易懂的")

        # 点击坐标应该就是那一行的中心
        self.assertTrue(0 < result.node.x < 1212)
        self.assertTrue(700 < result.node.y < 900, f"y={result.node.y} 应落在第一个选项行")

    def test_prototype_question_flow(self):
        xml = (FIXTURES / "gre_prototype.xml").read_text(encoding="utf-8")
        snap = screen.read_screen(xml)

        result = matcher.match("猛咬", snap.options, CFG)
        self.assertTrue(result.ok)
        self.assertEqual(result.node.text, "v. 猛咬")


if __name__ == "__main__":
    unittest.main(verbosity=2)

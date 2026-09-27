#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_screen.py —— 无障碍树解析测试

夹具是两次真实抓取的 GRE3000 界面 dump：
    gre_degrade.xml    题干 degrade，选项是中文释义（题型：据词选中义）
    gre_prototype.xml  题干 prototype，选项是中文释义

用真实数据测，而不是我凭空造的 XML —— 那样只能验证我自己的假设。
"""

import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from voice_tap import screen

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def load(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


# 一个「前台不是 GRE3000」的假界面，用来测护栏
OTHER_APP_XML = """<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
<hierarchy rotation="0">
  <node index="0" text="" class="android.widget.FrameLayout" package="com.tencent.mobileqq"
        clickable="false" bounds="[0,0][1212,2512]">
    <node index="0" text="消息" class="android.widget.TextView" package="com.tencent.mobileqq"
          content-desc="" clickable="true" bounds="[0,2440][200,2512]" />
    <node index="1" text="联系人" class="android.widget.TextView" package="com.tencent.mobileqq"
          content-desc="" clickable="true" bounds="[400,2440][600,2512]" />
  </node>
</hierarchy>
"""

# 包名对，但当前不是答题页（只有一个 tv_question）
NO_OPTIONS_XML = """<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
<hierarchy rotation="0">
  <node index="0" text="" class="android.widget.FrameLayout" package="com.enhance.greapp"
        clickable="false" bounds="[0,0][1212,2512]">
    <node index="0" text="背单词" resource-id="com.enhance.greapp:id/tv_word"
          class="android.widget.TextView" package="com.enhance.greapp"
          clickable="false" bounds="[100,500][1100,700]" />
  </node>
</hierarchy>
"""


class TestRealDumps(unittest.TestCase):
    """用真实抓取的界面数据验证解析"""

    def test_degrade_screen_parses(self):
        snap = screen.read_screen(load("gre_degrade.xml"))

        self.assertTrue(snap.ok, f"应当判定为可点击界面，实际原因: {snap.reason}")
        self.assertEqual(snap.foreground_package, "com.enhance.greapp")
        self.assertEqual(snap.prompt, "degrade")
        self.assertEqual(len(snap.options), 5)
        self.assertEqual(
            [n.text for n in snap.options],
            ["adj. 清晰易懂的", "adj. 阴郁的，闷闷不乐的",
             "adj. 骄奢淫逸的，耽于感官享受的", "v. 降低，恶化，贬低", "不记得了"],
        )

    def test_prototype_screen_parses(self):
        snap = screen.read_screen(load("gre_prototype.xml"))

        self.assertTrue(snap.ok)
        self.assertEqual(snap.prompt, "prototype")
        self.assertEqual(
            [n.text for n in snap.options],
            ["adj. 狂怒的", "n. 原型，样品", "v. 收获，得到", "v. 猛咬", "不记得了"],
        )

    def test_prompt_never_appears_in_options(self):
        """
        这是最关键的一条：题干节点绝不能混进候选项。

        如果题干混进去了，用户说 "degrade" 时可能点到题干而不是选项。
        靠 resource-id 排除，不靠位置或文字内容去猜。
        """
        for name in ("gre_degrade.xml", "gre_prototype.xml"):
            with self.subTest(fixture=name):
                snap = screen.read_screen(load(name))
                prompt_key = screen_gre_prompt(snap)
                option_texts = snap.option_texts()
                self.assertNotIn(prompt_key, option_texts)
                # 题干文字也不该出现在任何一个选项的 resource_id 里
                for node in snap.options:
                    self.assertEqual(node.resource_id, screen.ID_OPTION)

    def test_option_coordinates_are_inside_their_rows(self):
        """每个选项的点击坐标必须落在它自己那行的范围内"""
        snap = screen.read_screen(load("gre_degrade.xml"))
        for node in snap.options:
            self.assertIsNotNone(node.bounds)
            x1, y1, x2, y2 = node.bounds
            self.assertTrue(x1 <= node.x <= x2,
                            f"{node.text} 的 x={node.x} 不在行范围 [{x1},{x2}]")
            self.assertTrue(y1 <= node.y <= y2,
                            f"{node.text} 的 y={node.y} 不在行范围 [{y1},{y2}]")

    def test_options_sorted_top_to_bottom(self):
        """选项按屏幕上到下排好序，「第一个选项」这个说法才有确定含义"""
        snap = screen.read_screen(load("gre_degrade.xml"))
        ys = [n.y for n in snap.options]
        self.assertEqual(ys, sorted(ys))

    def test_click_coordinates_are_plausible(self):
        """坐标应该落在屏幕范围内（这一台是 1212x2616）"""
        snap = screen.read_screen(load("gre_degrade.xml"))
        for node in snap.options:
            self.assertTrue(0 <= node.x <= 1212, f"{node.text} x={node.x} 越界")
            self.assertTrue(0 <= node.y <= 2616, f"{node.text} y={node.y} 越界")


class TestForegroundGuard(unittest.TestCase):
    """前台应用护栏 —— 防止在别的 App 上乱点"""

    def test_other_app_is_rejected(self):
        snap = screen.read_screen(OTHER_APP_XML)
        self.assertFalse(snap.ok)
        self.assertEqual(snap.foreground_package, "com.tencent.mobileqq")
        self.assertIn("不在 GRE3000", snap.reason)
        self.assertEqual(snap.options, [])

    def test_other_app_still_lists_text_for_diagnostics(self):
        """被拒绝时也要把屏幕上的文字列出来，方便用户判断发生了什么"""
        snap = screen.read_screen(OTHER_APP_XML)
        self.assertIn("消息", [n.text for n in snap.all_text_nodes])
        self.assertIn("联系人", [n.text for n in snap.all_text_nodes])

    def test_correct_app_but_not_quiz_screen_is_rejected(self):
        snap = screen.read_screen(NO_OPTIONS_XML)
        self.assertFalse(snap.ok)
        self.assertIn("只有 0 个选项", snap.reason)

    def test_guard_can_be_disabled_for_diagnostics(self):
        """诊断模式下允许不校验前台应用"""
        snap = screen.read_screen(OTHER_APP_XML, expected_package=None)
        # 没有 tv_question，仍然不算可点击界面，但不该因为包名被拒
        self.assertNotIn("不在 GRE3000", snap.reason)
        self.assertEqual(snap.foreground_package, "com.tencent.mobileqq")


# 答完题之后的详情页：没有选项，但有一个「下一题」按钮
DETAIL_XML = """<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
<hierarchy rotation="0">
  <node index="0" text="" class="android.widget.FrameLayout" package="com.enhance.greapp"
        clickable="false" bounds="[0,0][1212,2512]">
    <node index="0" text="degrade" resource-id="com.enhance.greapp:id/tv_word"
          class="android.widget.TextView" package="com.enhance.greapp"
          clickable="false" bounds="[50,300][1162,500]" />
    <node index="1" text="v. 降低，恶化，贬低" class="android.widget.TextView"
          package="com.enhance.greapp" clickable="false" bounds="[50,600][1162,800]" />
    <node index="2" text="" class="android.widget.RelativeLayout"
          package="com.enhance.greapp" clickable="true" bounds="[100,2100][1112,2260]">
      <node index="0" text="下一题" class="android.widget.TextView"
            package="com.enhance.greapp" clickable="false" bounds="[500,2140][700,2220]" />
    </node>
  </node>
</hierarchy>
"""


class TestDetailPage(unittest.TestCase):
    """
    答错或点「不记得了」之后会进详情页，需要点「下一题」才能继续。

    详情页没有 tv_question，所以不能拿它当答题页 —— 但也**不该当成错误**，
    它有自己该做的事。
    """

    def test_recognised_as_detail_page(self):
        snap = screen.read_screen(DETAIL_XML)

        self.assertFalse(snap.ok, "详情页没有选项，不能当作答题页")
        self.assertEqual(snap.page, screen.PAGE_DETAIL)

    def test_finds_next_button(self):
        snap = screen.read_screen(DETAIL_XML)

        self.assertIsNotNone(snap.next_button, "应该找到「下一题」按钮")
        self.assertEqual(snap.next_button.text, "下一题")
        # 按钮文字中心：([500,2140][700,2220]) -> (600, 2180)
        self.assertEqual((snap.next_button.x, snap.next_button.y), (600, 2180))

    def test_no_options_on_detail_page(self):
        snap = screen.read_screen(DETAIL_XML)
        self.assertEqual(snap.options, [])

    def test_next_button_text_matching(self):
        for text in ("下一题", "下一词", "继续", "下一个", "下一组", "下一关", "Next"):
            with self.subTest(text=text):
                self.assertTrue(screen.is_next_button_text(text))
        for text in ("上一题", "提交", "取消", "释义", ""):
            with self.subTest(text=text):
                self.assertFalse(screen.is_next_button_text(text))

    def test_prefers_lowest_clickable_candidate(self):
        """页面上有多个像按钮的文字时，取最靠下的那个"""
        xml = """<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
        <hierarchy rotation="0">
          <node index="0" text="" class="android.widget.FrameLayout" package="com.enhance.greapp"
                clickable="false" bounds="[0,0][1212,2512]">
            <node index="0" text="继续" class="android.widget.TextView"
                  package="com.enhance.greapp" clickable="false" bounds="[100,200][300,300]" />
            <node index="1" text="下一题" class="android.widget.TextView"
                  package="com.enhance.greapp" clickable="true" bounds="[400,2200][800,2320]" />
          </node>
        </hierarchy>
        """
        snap = screen.read_screen(xml)
        self.assertIsNotNone(snap.next_button)
        self.assertEqual(snap.next_button.text, "下一题")

    def test_quiz_page_also_reports_next_button_if_present(self):
        """有些答题页底部也有下一题按钮，不该因此被判成详情页"""
        snap = screen.read_screen(load("gre_degrade.xml"))
        self.assertTrue(snap.ok)
        self.assertEqual(snap.page, screen.PAGE_QUIZ)


class TestLanguageAndHint(unittest.TestCase):
    """
    用屏幕内容辅助识别。

    实测发现：模型在只有半秒的短音频上，语言判断经常出错
    （把英文判成法语、意大利语），一判错整句就全错。
    而"屏幕上摆着哪几个候选词"是我们已经拿到手的、确定的信息。
    """

    def test_chinese_options_mean_chinese(self):
        snap = screen.read_screen(load("gre_degrade.xml"))
        self.assertEqual(screen.guess_language(snap), "zh")

    def test_english_options_mean_english(self):
        xml = """<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
        <hierarchy rotation="0">
          <node index="0" text="" class="android.widget.FrameLayout" package="com.enhance.greapp"
                clickable="false" bounds="[0,0][1212,2512]">
            <node index="0" text="to be like" resource-id="com.enhance.greapp:id/tv_word"
                  class="android.widget.TextView" package="com.enhance.greapp"
                  clickable="false" bounds="[50,435][1162,623]" />
            <node index="1" text="resemble" resource-id="com.enhance.greapp:id/tv_question"
                  class="android.widget.TextView" package="com.enhance.greapp"
                  clickable="false" bounds="[50,736][1162,886]" />
            <node index="2" text="feign" resource-id="com.enhance.greapp:id/tv_question"
                  class="android.widget.TextView" package="com.enhance.greapp"
                  clickable="false" bounds="[50,924][1162,1074]" />
          </node>
        </hierarchy>
        """
        snap = screen.read_screen(xml)
        self.assertEqual(screen.guess_language(snap), "en")

    def test_no_options_means_no_opinion(self):
        snap = screen.read_screen(DETAIL_XML)
        self.assertIsNone(screen.guess_language(snap),
                          "没有选项就不该瞎猜语言")

    def test_option_hint_lists_the_options(self):
        snap = screen.read_screen(load("gre_prototype.xml"))
        hint = screen.option_hint(snap)
        self.assertIsNotNone(hint)
        for text in snap.option_texts():
            self.assertIn(text, hint)

    def test_option_hint_is_none_without_options(self):
        snap = screen.read_screen(DETAIL_XML)
        self.assertIsNone(screen.option_hint(snap))


class TestEdgeCases(unittest.TestCase):

    def test_malformed_xml(self):
        snap = screen.read_screen("<hierarchy><node")
        self.assertFalse(snap.ok)
        self.assertIn("解析失败", snap.reason)

    def test_empty_screen(self):
        snap = screen.read_screen(
            "<?xml version='1.0'?><hierarchy rotation='0'>"
            "<node text='' class='x' package='com.enhance.greapp' bounds='[0,0][1,1]'/>"
            "</hierarchy>"
        )
        self.assertFalse(snap.ok)
        self.assertEqual(snap.options, [])

    def test_bounds_parsing(self):
        self.assertEqual(screen.parse_bounds("[50,435][1162,623]"), (50, 435, 1162, 623))
        self.assertEqual(screen.parse_bounds("[-10,-20][30,40]"), (-10, -20, 30, 40))
        self.assertIsNone(screen.parse_bounds(""))
        self.assertIsNone(screen.parse_bounds("[1,2][3,4,5]"))


class TestClickPointResolution(unittest.TestCase):
    """点哪里 —— 文字中心优先，祖先中心兜底"""

    def test_uses_text_center_when_inside_clickable_ancestor(self):
        # 选项整行可点：文字中心落在行内，应该点文字中心（更精确）
        point = screen.resolve_click_point((100, 950, 400, 1030), (60, 900, 1020, 1080))
        self.assertEqual(point, (250, 990))

    def test_falls_back_to_ancestor_center_when_text_outside(self):
        """
        大容器套小图标的情况：文字（图标）中心跑出可点范围，
        这时用祖先中心，避免点到容器正中离目标很远
        """
        point = screen.resolve_click_point((10, 10, 40, 40), (900, 900, 1100, 1100))
        self.assertEqual(point, (1000, 1000))

    def test_uses_text_center_when_no_ancestor(self):
        point = screen.resolve_click_point((100, 200, 300, 400), None)
        self.assertEqual(point, (200, 300))


def screen_gre_prompt(snap):
    """辅助：从快照里拿题干文字"""
    return snap.prompt


if __name__ == "__main__":
    unittest.main(verbosity=2)

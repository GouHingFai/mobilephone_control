#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_config.py —— 配置读取测试

配置模块的原则是「读不到也要能跑」：任何一个键写错、写漏、写歪，
都必须退回默认值并留下提示，绝不能把程序拦在门外。
这里重点验两件事：坐标解析，以及配置写歪了也不会把程序拦死。
"""

import tempfile
import unittest
from pathlib import Path

from voice_tap import config as cfgmod


def load_yaml(text):
    """把一段 YAML 写进临时文件再读进来"""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "config.yaml"
        path.write_text(text, encoding="utf-8")
        return cfgmod.load_config(path)


class TestPositionParsing(unittest.TestCase):

    def test_list_of_lists(self):
        got = cfgmod._to_positions([[606, 811], [606, 999]])
        self.assertEqual(got, [(606, 811), (606, 999)])

    def test_list_of_strings(self):
        got = cfgmod._to_positions(["606,811", "606, 999"])
        self.assertEqual(got, [(606, 811), (606, 999)])

    def test_mixed_forms(self):
        got = cfgmod._to_positions([[606, 811], "606,999"])
        self.assertEqual(got, [(606, 811), (606, 999)])

    def test_bad_entries_are_skipped_not_fatal(self):
        """一行写错不该让整份配置失效 —— 跳过它，保住其它坐标"""
        got = cfgmod._to_positions([[606, 811], "乱写的", [1, 2, 3], ["a", "b"], [606, 999]])
        self.assertEqual(got, [(606, 811), (606, 999)])

    def test_empty_and_none(self):
        self.assertEqual(cfgmod._to_positions(None), [])
        self.assertEqual(cfgmod._to_positions([]), [])

    def test_single_position(self):
        self.assertEqual(cfgmod._to_position([500, 2400]), (500, 2400))
        self.assertIsNone(cfgmod._to_position(None))
        self.assertIsNone(cfgmod._to_position(["坏的"]))


class TestNextButtonPosition(unittest.TestCase):
    """「下一题」按钮的固定坐标（这个是保留的）"""

    def test_parsed(self):
        cfg = load_yaml("""
hotkey:
  fixed_next_position: [600, 2180]
""")
        self.assertEqual(cfg.hotkey.fixed_next_position, (600, 2180))

    def test_defaults_to_none(self):
        cfg = load_yaml("hotkey: {}")
        self.assertIsNone(cfg.hotkey.fixed_next_position)

    def test_bad_value_falls_back_to_none(self):
        cfg = load_yaml("""
hotkey:
  fixed_next_position: 乱写的
""")
        self.assertIsNone(cfg.hotkey.fixed_next_position)


class TestRobustness(unittest.TestCase):
    """配置写歪了也不能让程序起不来"""

    def test_missing_file(self):
        cfg = cfgmod.load_config(Path("/nonexistent/nope.yaml"))
        self.assertEqual(cfg.hotkey.toggle_numpad, "f10")
        self.assertTrue(cfg.notices)

    def test_empty_file(self):
        cfg = load_yaml("")
        self.assertEqual(cfg.audio.input_device, None)
        self.assertEqual(cfg.asr.model, "small")

    def test_garbage_yaml(self):
        cfg = load_yaml("这不是: [合法的: yaml")
        self.assertTrue(cfg.notices, "解析失败应该留下提示")

    def test_wrong_types(self):
        cfg = load_yaml("""
audio:
  vad_threshold: 不是数字
  input_device: 也不是
hotkey:
  numpad_enabled: 说不清
""")
        self.assertEqual(cfg.audio.vad_threshold, cfgmod.AudioConfig.vad_threshold)
        self.assertEqual(cfg.audio.input_device, cfgmod.AudioConfig.input_device)
        self.assertEqual(cfg.hotkey.numpad_enabled, cfgmod.HotkeyConfig.numpad_enabled)
        self.assertGreaterEqual(len(cfg.notices), 3, "每个坏值都该有一条提示")

    def test_bool_words(self):
        cfg = load_yaml("""
hotkey:
  numpad_enabled: 开
  numpad_reverse: 关
""")
        self.assertTrue(cfg.hotkey.numpad_enabled)
        self.assertFalse(cfg.hotkey.numpad_reverse)

    def test_hotkey_defaults(self):
        cfg = load_yaml("hotkey: {}")
        self.assertEqual(cfg.hotkey.toggle_numpad, "f10")
        self.assertTrue(hasattr(cfg.hotkey, "fixed_next_position"))


class TestVoiceMuteDuration(unittest.TestCase):
    """
    点击后静音期的时长。

    由来：点完选项之后**手机会把那个单词的读音播出来**，麦克风收进去，
    程序会误以为是用户在说话。所以点完之后短暂不监听语音。
    一个单词读音约 1～1.2 秒，加上点击到开始播放的延迟，2 秒够用。

    用户 2026-09-27 特意要求从 2.5 秒缩到 2 秒（更快能说下一句）。
    这个是**有意钉住的**：以后真要再调，改这里并注明理由即可。
    """

    def test_code_default_is_two_seconds(self):
        self.assertEqual(cfgmod.VoiceConfig.mute_after_click_ms, 2000)

    def test_shipped_config_is_two_seconds(self):
        """项目里那份 config.yaml 会覆盖默认值 —— 它也得是 2 秒"""
        real = Path(__file__).resolve().parent.parent / "config.yaml"
        cfg = cfgmod.load_config(real)
        self.assertEqual(
            cfg.voice.mute_after_click_ms, 2000,
            "config.yaml 里的 mute_after_click_ms 不是 2000；"
            "若是你有意改的，请同步改这个测试并注明理由")


class TestVoiceCommandsSwitch(unittest.TestCase):
    """
    说序号 / 说「下一题」的总开关，**默认关**。

    2026-09-28：`next_command`（原来默认 true）并入本开关，并且默认改成关。
    依据真机日志：环境杂音或手机自己念出「第一个」，程序按序号点了一下。
    序号（「1」「第二个」）和「下一题／继续」这类说法太容易误触发。

    注意：**说单词来选选项那条路不受这个开关管** —— 那是用户语音的主力用法。
    """

    def test_default_is_off(self):
        self.assertFalse(cfgmod.VoiceConfig.commands)

    def test_shipped_config_is_off(self):
        real = Path(__file__).resolve().parent.parent / "config.yaml"
        self.assertFalse(cfgmod.load_config(real).voice.commands)

    def test_parsed_on(self):
        cfg = load_yaml("voice:\n  commands: 开\n")
        self.assertTrue(cfg.voice.commands)

    def test_parsed_off(self):
        """显式写关也要认（默认就是关，但配置里写死一个关值不能被解析歪）"""
        cfg = load_yaml("voice:\n  commands: 关\n")
        self.assertFalse(cfg.voice.commands)

    def test_old_key_is_gone(self):
        """`next_command` 已并入 `commands`，留着是残留引用"""
        self.assertFalse(hasattr(cfgmod.VoiceConfig, "next_command"))


class TestNonMappingSections(unittest.TestCase):
    """
    一整个配置段写成**非映射值**：`gui: 3` / `hotkey: 3` 这种手滑写法。

    这是本项目最要命的一类错：`data.get("gui")` 拿到的不是字典，
    后面一个 `.get(...)` 就抛 AttributeError，`load_config` 当场崩 ——
    **连不带 `--gui` 的正常路径都起不来**，正好撞上「绝不能把程序拦在门外」那条根本原则。

    这里不是只盯 gui：**每一个**顶层段都写成非映射值试一遍。
    谁也不该因为一行 YAML 写歪就把整个程序拦在门外。
    """

    # 段名 → 写进 YAML 的字面量。数字、空列表、布尔、字符串、非空列表都覆盖到，
    # 因为「假值」（`[]`、`false`）和「真值」（`3`、`"x"`）会走进不同的代码分支。
    BAD_SECTIONS = {
        "audio": "3",
        "asr": "[]",
        "match": "true",
        "click": '"x"',
        "hotkey": "3",
        "voice": "[]",
        "run": "true",
        "prefetch": "3",
        "gui": "3",
    }

    def test_does_not_raise_and_falls_back_to_defaults(self):
        """不抛异常，且该段整体退回默认值"""
        for name, literal in self.BAD_SECTIONS.items():
            with self.subTest(section=name, value=literal):
                cfg = load_yaml(f"{name}: {literal}\n")
                self.assertEqual(
                    getattr(cfg, name), getattr(cfgmod.Config(), name),
                    f"{name} 写成非映射值后没有退回默认值")

    def test_each_bad_section_leaves_a_notice(self):
        """退默认值还不够 —— 得留一句提示，否则用户不知道自己那一整段白写了"""
        for name, literal in self.BAD_SECTIONS.items():
            with self.subTest(section=name, value=literal):
                cfg = load_yaml(f"{name}: {literal}\n")
                self.assertTrue(
                    any(name in notice for notice in cfg.notices),
                    f"{name} 整段写歪了却没有留下提示：{cfg.notices}")


class TestGuiConfig(unittest.TestCase):
    """置顶浮窗（gui 段）的解析。计划步骤 0 明说要补，之前一直零覆盖。"""

    def test_defaults(self):
        cfg = load_yaml("")
        self.assertFalse(cfg.gui.enabled)
        self.assertEqual(cfg.gui.window, (40, 120, 360, 520))
        self.assertTrue(cfg.gui.topmost)
        self.assertEqual(cfg.gui.refresh_ms, 150)

    # -------------------------------------------------- enabled / topmost

    def test_enabled_parsed(self):
        self.assertTrue(load_yaml("gui:\n  enabled: 开\n").gui.enabled)
        self.assertFalse(load_yaml("gui:\n  enabled: 关\n").gui.enabled)
        self.assertTrue(load_yaml("gui:\n  enabled: true\n").gui.enabled)

    def test_enabled_bad_value_falls_back(self):
        cfg = load_yaml("gui:\n  enabled: 说不清\n")
        self.assertEqual(cfg.gui.enabled, cfgmod.GuiConfig.enabled)
        self.assertTrue(any("enabled" in notice for notice in cfg.notices))

    def test_topmost_parsed(self):
        self.assertFalse(load_yaml("gui:\n  topmost: false\n").gui.topmost)
        self.assertTrue(load_yaml("gui:\n  topmost: true\n").gui.topmost)

    def test_topmost_bad_value_falls_back(self):
        cfg = load_yaml("gui:\n  topmost: 说不清\n")
        self.assertEqual(cfg.gui.topmost, cfgmod.GuiConfig.topmost)
        self.assertTrue(any("topmost" in notice for notice in cfg.notices))

    # -------------------------------------------------- window

    def test_window_parsed(self):
        cfg = load_yaml("gui:\n  window: [10, 20, 300, 400]\n")
        self.assertEqual(cfg.gui.window, (10, 20, 300, 400))
        self.assertEqual(cfg.notices, [], "正常值不该留提示")

    def test_window_bad_values_fall_back_whole(self):
        """半截的窗口位置没有意义 —— 整体退回默认，不是逐个补"""
        for bad in ("[1, 2, 3]", "[1, 2, 3, 'x']", '"乱写的"', "null"):
            with self.subTest(value=bad):
                cfg = load_yaml(f"gui:\n  window: {bad}\n")
                self.assertEqual(cfg.gui.window, cfgmod.GuiConfig.window)
                self.assertTrue(any("window" in notice for notice in cfg.notices),
                                f"window 写成 {bad} 却没留提示：{cfg.notices}")

    def test_missing_section_leaves_no_false_notice(self):
        """
        没写 `gui:` 段时**不该**冒出提示。

        以前 `_to_window(gt.get("window"), ...)` 在段不存在时收到 None，
        被当成「窗口值不合法」记了一条 **假** 提示 —— 而其实只是没写这一段。
        `_pick` 对「键不存在」是静默的，这里也得一样。
        """
        cfg = load_yaml("hotkey: {}\n")
        self.assertEqual(cfg.notices, [], f"没写 gui 段却报了提示：{cfg.notices}")

    # -------------------------------------------------- refresh_ms

    def test_refresh_ms_parsed(self):
        self.assertEqual(load_yaml("gui:\n  refresh_ms: 500\n").gui.refresh_ms, 500)

    def test_refresh_ms_bad_value_falls_back(self):
        cfg = load_yaml("gui:\n  refresh_ms: 很快\n")
        self.assertEqual(cfg.gui.refresh_ms, cfgmod.GuiConfig.refresh_ms)
        self.assertTrue(any("refresh_ms" in notice for notice in cfg.notices))

    def test_refresh_ms_has_a_floor(self):
        """
        0 或负数会让 `root.after(0, ...)` 变成**忙循环** —— 界面把主线程占死。
        小于下限就按下限算（坏值非数字照旧退默认，见上一条）。
        """
        floor = cfgmod.MIN_GUI_REFRESH_MS
        for bad in ("0", "-1", "-1000", "1", "29"):
            with self.subTest(value=bad):
                cfg = load_yaml(f"gui:\n  refresh_ms: {bad}\n")
                self.assertEqual(cfg.gui.refresh_ms, floor,
                                 f"refresh_ms 写成 {bad} 没有抬到下限")
                self.assertTrue(any("refresh_ms" in notice for notice in cfg.notices),
                                f"refresh_ms 写成 {bad} 却没留提示：{cfg.notices}")

    def test_refresh_ms_at_or_above_the_floor_is_kept(self):
        floor = cfgmod.MIN_GUI_REFRESH_MS
        self.assertEqual(load_yaml(f"gui:\n  refresh_ms: {floor}\n").gui.refresh_ms, floor)
        self.assertEqual(load_yaml("gui:\n  refresh_ms: 150\n").gui.refresh_ms, 150)


if __name__ == "__main__":
    unittest.main(verbosity=2)

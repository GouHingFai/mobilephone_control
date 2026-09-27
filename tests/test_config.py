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


class TestVoiceNextCommand(unittest.TestCase):

    def test_code_default_is_on(self):
        self.assertTrue(cfgmod.VoiceConfig.next_command)

    def test_shipped_config_is_on(self):
        real = Path(__file__).resolve().parent.parent / "config.yaml"
        self.assertTrue(cfgmod.load_config(real).voice.next_command)

    def test_parsed_off(self):
        cfg = load_yaml("voice:\n  next_command: 关\n")
        self.assertFalse(cfg.voice.next_command)


if __name__ == "__main__":
    unittest.main(verbosity=2)

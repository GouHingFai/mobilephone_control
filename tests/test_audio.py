#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_audio.py —— 音频采集链路测试（用假的音频设备）

为什么要专门测这一块：

音频采集是开发者唯一无法在真机上验证的部分（这台开发机没有麦克风），
而它已经出过两次问题：
  1. sd.rec() + sd.wait() 在用户的 USB 麦克风上永久卡死
  2. 回调里存的是一维数组，收尾却照抄了处理二维数组的 [:, 0]，一开口就 IndexError

所以这里用一个假的 sounddevice 顶替真硬件，把「按脚本送音频块」这件事做完整，
把 VAD 切句、预滚缓冲、按上限截断、数组形状这些都验证一遍。
"""

import sys
import threading
import types
import unittest

import numpy as np

from voice_tap import audio_io


# ---------------------------------------------------------------- 假的音频设备

class CallbackStop(Exception):
    pass


class FakeStream:
    """
    按脚本投递音频块。

    script 是一个「振幅」列表，每个元素对应一个块；0 表示静音。
    start() 会同步把所有块喂给回调，模拟设备连续送数据。
    """

    last_kwargs = {}

    def __init__(self, script, on_finish=None, **kwargs):
        self.script = script
        self.on_finish = on_finish
        self.blocksize = int(kwargs.get("blocksize") or int(0.02 * kwargs["samplerate"]))
        self.samplerate = int(kwargs["samplerate"])
        self.callback = kwargs["callback"]
        FakeStream.last_kwargs = kwargs
        self.delivered = 0
        self.aborted = False

    def start(self):
        rng = np.random.default_rng(12345)
        for amplitude in self.script:
            if self.aborted:
                break
            block = (rng.standard_normal(self.blocksize) * amplitude).astype("float32")
            block = block.reshape(-1, 1)          # 真设备给的是二维 (frames, channels)
            try:
                self.callback(block, self.blocksize, None, None)
            except CallbackStop:
                break
            self.delivered += 1
        if self.on_finish is not None:
            self.on_finish()

    def abort(self):
        self.aborted = True

    def close(self):
        pass


def install_fake_sd(script, on_finish=None):
    """给 audio_io 装上假音频后端"""
    fake = types.ModuleType("sounddevice")
    fake.CallbackStop = CallbackStop
    fake.InputStream = lambda **kw: FakeStream(script, on_finish, **kw)
    fake.query_devices = lambda dev=None: {
        "name": "Fake Mic", "max_input_channels": 1,
        "default_samplerate": 16000.0, "hostapi": 0,
    }
    fake.query_hostapis = lambda: [{"name": "Fake"}]
    fake.default = types.SimpleNamespace(device=(0, 0))
    fake.check_input_settings = lambda **kw: None
    original = audio_io.sd
    audio_io.sd = fake
    return original


def restore_sd(original):
    audio_io.sd = original


# 20 毫秒一块，16kHz 就是 320 个采样点
BLOCK_SECONDS = 0.02

def blocks(seconds):
    return max(1, int(seconds / BLOCK_SECONDS))


class TestListenUntilSilence(unittest.TestCase):

    def tearDown(self):
        audio_io.sd = self._original

    def _run(self, script, **kwargs):
        self._original = audio_io.sd
        install_fake_sd(script)
        options = dict(
            vad_threshold=0.02,
            silence_duration=0.2,
            max_utterance=5.0,
            pre_roll=0.1,
            device=0,
            samplerate=16000,
            start_timeout=0.5,
        )
        options.update(kwargs)
        return audio_io.listen_until_silence(**options)

    def test_silence_then_speech_then_silence(self):
        """正常的「安静 → 说话 → 安静」应该被切出一段音频"""
        script = [0.0] * blocks(0.2) + [0.1] * blocks(0.4) + [0.0] * blocks(0.4)
        result = self._run(script)

        self.assertIsNotNone(result, "应该切出一段语音")
        data, samplerate = result

        # ---- 关键回归：必须是一维数组 ----
        # 这里曾经写成 np.concatenate(...)[:, 0]，对一维数组取 [:, 0] 会直接抛
        # IndexError，程序一开口就崩。这条断言就是防止它再犯。
        self.assertEqual(data.ndim, 1, f"音频必须是一维数组，实际是 {data.ndim} 维")
        self.assertEqual(data.dtype, np.float32)
        self.assertGreater(data.size, 0)

        # 语音段落应该真的在里面（振幅 0.1）
        self.assertGreater(float(np.abs(data).max()), 0.05,
                           "切出来的音频里应该包含那段语音")

    def test_all_silence_returns_none(self):
        """一直没人说话，应该返回 None 而不是空数组"""
        script = [0.0] * blocks(1.0)
        self.assertIsNone(self._run(script, start_timeout=0.3))

    def test_speech_never_starts_is_none(self):
        """只有极轻微的底噪，不该被当成说话"""
        script = [0.005] * blocks(1.0)
        self.assertIsNone(self._run(script, vad_threshold=0.02, start_timeout=0.3))

    def test_on_speech_start_fired_once(self):
        """检测到开口时应该回调一次，用来触发界面预抓取"""
        calls = []
        script = [0.0] * blocks(0.2) + [0.1] * blocks(0.3) + [0.0] * blocks(0.4)
        self._run(script, on_speech_start=lambda: calls.append(1))
        self.assertEqual(len(calls), 1, "开口回调应该恰好触发一次")

    def test_max_utterance_caps_length(self):
        """一直说个不停时，必须被单句上限截断，不能无限增长"""
        script = [0.1] * blocks(3.0)          # 3 秒持续语音
        result = self._run(script, max_utterance=0.5, silence_duration=10.0)

        self.assertIsNotNone(result)
        data, _ = result
        # 上限 0.5 秒，允许预滚和一些余量，但不该接近 3 秒
        self.assertLess(data.size, int(1.5 * 16000),
                        f"应该被上限截断，实际拿到 {data.size / 16000:.2f} 秒")

    def test_pre_roll_keeps_word_onset(self):
        """开口瞬间之前的缓冲要保留，否则会把词的起头切掉"""
        script = [0.0] * blocks(0.3) + [0.1] * blocks(0.2) + [0.0] * blocks(0.4)
        result = self._run(script, pre_roll=0.2)
        data, _ = result

        speech_seconds = data.size / 16000
        # 语音本身 0.2 秒，加上预滚应该明显更长
        self.assertGreater(speech_seconds, 0.25,
                           f"预滚没生效，只拿到 {speech_seconds:.2f} 秒")

    def test_stop_event_breaks_out(self):
        """停止信号能让监听立刻结束（按住说话模式靠它收尾）"""
        self._original = audio_io.sd
        stop = threading.Event()

        def finish():
            pass

        install_fake_sd([0.1] * blocks(3.0), on_finish=finish)
        # 一边监听一边不停置停止位
        stop.set()
        result = audio_io.listen_until_silence(
            vad_threshold=0.02, silence_duration=10.0, max_utterance=5.0,
            device=0, samplerate=16000, stop_event=stop,
        )
        # 因为一开口就收到了停止信号，可能返回 None 或一段音频，总之必须立刻返回不卡住
        self.assertTrue(result is None or result[0].ndim == 1)


class TestRecordWhile(unittest.TestCase):
    """按住说话模式"""

    def tearDown(self):
        audio_io.sd = self._original

    def _run(self, script, hold_seconds=0.5, **kwargs):
        self._original = audio_io.sd
        held = threading.Event()
        held.set()

        def release():
            held.clear()          # 模拟松手

        install_fake_sd(script, on_finish=release)
        options = dict(device=0, samplerate=16000, max_seconds=5.0)
        options.update(kwargs)
        return audio_io.record_while(held, **options)

    def test_returns_1d_float32(self):
        """同样是那个一维数组的回归测试"""
        result = self._run([0.1] * blocks(0.4))

        self.assertIsNotNone(result)
        data, samplerate = result
        self.assertEqual(data.ndim, 1, "音频必须是一维数组")
        self.assertEqual(data.dtype, np.float32)
        self.assertEqual(samplerate, 16000)

    def test_too_short_returns_none(self):
        """按了一下就松，太短了应当丢弃"""
        result = self._run([0.1] * 2, min_seconds=0.5)
        self.assertIsNone(result, "按得太短应该返回 None")


class TestResampleTo16k(unittest.TestCase):

    def test_shapes_and_lengths(self):
        for source_rate in (16000, 44100, 48000, 8000):
            with self.subTest(sr=source_rate):
                n = int(source_rate * 0.5)
                signal = np.random.randn(n).astype("float32") * 0.1
                out = audio_io.resample_to_16k(signal, source_rate)
                self.assertEqual(out.ndim, 1)
                self.assertAlmostEqual(out.size / 16000, 0.5, delta=0.02)

    def test_identity_when_already_16k(self):
        signal = np.random.randn(16000).astype("float32")
        out = audio_io.resample_to_16k(signal, 16000)
        self.assertEqual(out.size, signal.size)


class TestTrimSilence(unittest.TestCase):

    def test_trims_both_ends(self):
        silence = np.zeros(8000, dtype="float32")
        speech = np.random.randn(16000).astype("float32") * 0.1
        data = np.concatenate([silence, speech, silence])
        out = audio_io.trim_silence(data, threshold=0.02)
        self.assertLess(out.size, data.size, "首尾静音应该被裁掉")
        self.assertGreater(out.size, 15000, "中间的语音应该保留")

    def test_all_silence_returns_unchanged(self):
        data = np.zeros(8000, dtype="float32")
        out = audio_io.trim_silence(data, threshold=0.02)
        self.assertEqual(out.size, data.size)

    def test_empty_input(self):
        out = audio_io.trim_silence(np.array([], dtype="float32"), threshold=0.02)
        self.assertEqual(out.size, 0)


class TestRecognizerFinish(unittest.TestCase):
    """
    音频预处理 → 送进识别模型 这一段。

    这里不打桩在 audio_io 上，而是用一个假的 Whisper 模型，
    验证从「一段采集到的音频」到「(文字, 置信度)」的完整转换。
    """

    def setUp(self):
        from voice_tap.asr import Recognizer
        from voice_tap.config import AsrConfig, AudioConfig

        self.recognizer = Recognizer(AsrConfig(), AudioConfig(), log=lambda *_: None)
        self._original_sd = audio_io.sd

    def tearDown(self):
        audio_io.sd = self._original_sd

    def _fake_model(self, text):
        captured = {}

        class FakeSegment:
            def __init__(self):
                self.text = text
                self.avg_logprob = -0.42

        class FakeModel:
            def transcribe(self, audio, language=None, initial_prompt=None,
                           beam_size=1, vad_filter=True):
                captured["samples"] = len(audio)
                captured["language"] = language
                captured["initial_prompt"] = initial_prompt
                captured["beam_size"] = beam_size
                captured["vad_filter"] = vad_filter
                info = types.SimpleNamespace(language="zh", language_probability=0.98)
                return [FakeSegment()], info

        return FakeModel(), captured

    def test_audio_becomes_text(self):
        model, captured = self._fake_model(" 清晰 ")
        self.recognizer._model = model

        # 44.1kHz 的一维音频，模拟设备原生采样率
        signal = (np.random.randn(44100).astype("float32") * 0.1).reshape(-1)

        text, logprob = self.recognizer._finish((signal, 44100))

        self.assertEqual(text, "清晰", "识别结果应该去掉首尾空白")
        self.assertAlmostEqual(logprob, -0.42, places=2)
        # 送进模型的必须是 16kHz
        self.assertAlmostEqual(captured["samples"] / 16000, 1.0, delta=0.05)
        self.assertEqual(captured["beam_size"], 1, "应该用贪心解码（快）")
        self.assertIn("audio_seconds", self.recognizer.last_timing)

    def test_screen_hint_sets_language_and_prompt(self):
        """
        屏幕上的选项要用来辅助识别，这是实测后加的关键一招：

          1. 看一眼选项是中文还是英文，直接告诉模型 —— 不让它自己猜。
             实测里模型在半秒的短音频上把英文判成过法语、意大利语，一判错整句全错。
          2. 把 5 个选项当提示词喂进去 —— 模型本来要在一整本词典里找，
             而屏幕上就摆着候选词。
        """
        from pathlib import Path
        from voice_tap import screen as screen_mod

        xml = (Path(__file__).resolve().parent / "fixtures" /
               "gre_degrade.xml").read_text(encoding="utf-8")
        snap = screen_mod.read_screen(xml)          # 中文选项

        model, captured = self._fake_model("清晰")
        self.recognizer._model = model

        signal = (np.random.randn(44100).astype("float32") * 0.1).reshape(-1)
        self.recognizer._finish((signal, 44100), hint_snapshot=snap)

        self.assertEqual(captured["language"], "zh", "应该按屏幕内容判成中文")
        self.assertIsNotNone(captured["initial_prompt"], "应该把选项当提示词")
        self.assertIn("清晰易懂的", captured["initial_prompt"])

    def test_hint_can_be_turned_off(self):
        """关掉这个开关时，不该往模型里塞任何提示"""
        from pathlib import Path
        from voice_tap import screen as screen_mod

        xml = (Path(__file__).resolve().parent / "fixtures" /
               "gre_degrade.xml").read_text(encoding="utf-8")
        snap = screen_mod.read_screen(xml)

        self.recognizer.asr_cfg.use_screen_hint = False
        model, captured = self._fake_model("清晰")
        self.recognizer._model = model

        signal = (np.random.randn(44100).astype("float32") * 0.1).reshape(-1)
        self.recognizer._finish((signal, 44100), hint_snapshot=snap)

        self.assertIsNone(captured["language"])
        self.assertIsNone(captured["initial_prompt"])

    def test_no_hint_still_works(self):
        """没有屏幕信息时（比如第一句），照常识别，不能崩"""
        model, captured = self._fake_model("hello")
        self.recognizer._model = model

        signal = (np.random.randn(44100).astype("float32") * 0.1).reshape(-1)
        result = self.recognizer._finish((signal, 44100), hint_snapshot=None)

        self.assertIsNotNone(result)
        self.assertIsNone(captured["initial_prompt"])

    def test_too_short_audio_is_dropped(self):
        """极短的音频不该浪费一次识别"""
        model, captured = self._fake_model("嗯")
        self.recognizer._model = model

        signal = np.zeros(800, dtype="float32")    # 0.05 秒
        result = self.recognizer._finish((signal, 16000))

        self.assertIsNone(result, "太短的音频应当直接丢弃")
        self.assertNotIn("samples", captured, "不该调用识别模型")


if __name__ == "__main__":
    unittest.main(verbosity=2)

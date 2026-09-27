#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
asr.py —— 麦克风采集 + 静音切句 + Whisper 识别

对外只有两个动作：
    warmup()        把模型加载好（首次会下载，之后有缓存）
    listen_once()   等你说一句，返回 (文字, 置信度)；没人说话返回 None

设计要点：

* **离线**。模型跑在本地 CPU 上，不联网、不上传录音。
* **模型下载走国内镜像**。不设 HF_ENDPOINT 的话，HuggingFace 直连在国内会一直卡住。
* **送进模型前裁掉首尾静音**。识别耗时和音频长度正相关，裁掉静音能明显变快。
* **贪心解码**（beam_size=1）。短词识别用不上 beam search，但快好几倍。
"""

import os
import time

from . import audio_io as aio


class AsrError(RuntimeError):
    """识别层的错误，消息已经是可以直接给用户看的中文"""


class Recognizer:
    """麦克风 + Whisper 的组合"""

    def __init__(self, asr_cfg, audio_cfg, log=print):
        self.asr_cfg = asr_cfg
        self.audio_cfg = audio_cfg
        self.log = log
        self._model = None
        self._device = None
        self._samplerate = None
        # 每次识别后填上，供上层打印耗时
        self.last_timing = {}

    # ---------------------------------------------------------- 模型

    def warmup(self):
        """把模型加载好。首次会下载约 480MB，之后读缓存只要几秒。"""
        if self._model is not None:
            return

        # 国内必须走镜像，否则下载会卡死
        os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise AsrError(
                "没有安装 faster-whisper。请先运行 setup.bat 装依赖。"
            ) from exc

        name = self.asr_cfg.model
        self.log(f"      正在加载识别模型 '{name}' ...")
        self.log(f"      模型下载源 HF_ENDPOINT = {os.environ.get('HF_ENDPOINT')}")
        started = time.time()
        try:
            self._model = WhisperModel(name, device="cpu", compute_type="int8")
        except Exception as exc:  # noqa: BLE001
            raise AsrError(
                f"加载模型失败：{type(exc).__name__}: {exc}\n"
                "      如果是下载超时，检查网络；模型缓存在用户目录的 .cache/huggingface 下"
            ) from exc
        self.log(f"      模型就绪，耗时 {time.time() - started:.1f} 秒")

    # ---------------------------------------------------------- 设备

    def _ensure_device(self):
        """确定用哪个麦克风，只做一次。"""
        if self._device is not None:
            return self._device

        want = self.audio_cfg.input_device
        if want is not None:
            ok, msg, _rms = aio.quick_test(device=want, samplerate=self.audio_cfg.samplerate,
                                           seconds=0.5)
            if ok:
                self._device = want
                self._samplerate, _ = aio.pick_samplerate(want)
                self.log(f"      使用麦克风 [{want}]：{aio.describe_device(want)}")
                return self._device
            self.log(f"      config.yaml 指定的麦克风 [{want}] 不可用（{msg}），改用自动挑选")

        self.log("      正在挑选可用的麦克风 ...")
        device, samplerate = aio.pick_working_device(log=self.log)
        if device is None:
            raise AsrError(
                "找不到能录音的麦克风。请先运行 mic_level.bat 排查：\n"
                "      设置 → 隐私和安全性 → 麦克风 → 允许桌面应用访问麦克风"
            )
        if aio.device_is_virtual(device):
            self.log("      [!!] 警告：只能用虚拟声卡，录到的可能不是你的声音")

        self._device = device
        self._samplerate = samplerate
        return device

    # ---------------------------------------------------------- 监听

    def listen_once(self, start_timeout=None, stop_event=None, on_speech_start=None,
                    hint_snapshot=None):
        """
        等你说一句话。

        返回 (文字, 平均对数概率)；在 start_timeout 秒内一直没开口则返回 None。
        """
        self.warmup()
        device = self._ensure_device()
        samplerate = self._samplerate

        captured = aio.listen_until_silence(
            vad_threshold=self.audio_cfg.vad_threshold,
            silence_duration=self.audio_cfg.silence_duration,
            max_utterance=self.audio_cfg.max_utterance,
            device=device,
            samplerate=samplerate,
            start_timeout=start_timeout,
            stop_event=stop_event,
            on_speech_start=on_speech_start,
        )

        if captured is None:
            return None

        return self._finish(captured, hint_snapshot)

    def listen_pressed(self, held_event, hint_snapshot=None):
        """
        按住说话模式：按住期间一直录，松手就送去识别。

        和常驻监听的区别只在收尾方式 —— 那边靠静音检测自动切句，
        这边靠松手。用户按住就是在说，松开就是「说完了」。
        """
        self.warmup()
        device = self._ensure_device()

        captured = aio.record_while(
            held_event,
            max_seconds=max(20.0, self.audio_cfg.max_utterance),
            device=device,
            samplerate=self._samplerate,
        )
        if captured is None:
            return None

        return self._finish(captured, hint_snapshot)

    def _finish(self, captured, hint_snapshot=None):
        """采集结果 → 重采样 → 裁静音 → 识别。两种监听模式共用。"""
        data, actual_sr = captured
        data = aio.resample_to_16k(data, actual_sr)

        if self.asr_cfg.trim_silence:
            data = aio.trim_silence(data, self.audio_cfg.vad_threshold)

        duration = data.size / aio.TARGET_SR
        if duration < 0.15:
            # 太短了，多半是咳嗽或碰到桌子
            return None

        return self._transcribe(data, duration, hint_snapshot)

    def _transcribe(self, audio, duration, hint_snapshot=None):
        """
        把音频送去识别。

        hint_snapshot 是「最近见过的手机屏幕」。它有两个用处，都是实测后加的：

        1. **判断语言**。你只会说选项里的词，所以看一眼选项是中文还是英文，
           就知道该按哪种语言识别 —— 比让模型自己猜靠谱得多。
           实测中模型在半秒的短音频上把英文判成过法语、意大利语，一判错整句全错。

        2. **当提示词**。模型本来要在一整本词典里找出你说了哪个词，
           而屏幕上就摆着 5 个候选。告诉它「大概是这几个之一」，准确率会明显不一样。
        """
        from . import screen

        language = self.asr_cfg.language
        prompt = None
        if hint_snapshot is not None and self.asr_cfg.use_screen_hint:
            if language is None:
                language = screen.guess_language(hint_snapshot)
            prompt = screen.option_hint(hint_snapshot)

        started = time.time()
        try:
            segments, info = self._model.transcribe(
                audio,
                language=language,
                initial_prompt=prompt,
                beam_size=self.asr_cfg.beam_size,
                vad_filter=self.asr_cfg.vad_filter,
            )
            segments = list(segments)
        except Exception as exc:  # noqa: BLE001
            raise AsrError(f"识别失败：{type(exc).__name__}: {exc}") from exc

        elapsed = time.time() - started
        text = "".join(s.text for s in segments).strip()

        logprobs = [getattr(s, "avg_logprob", 0.0) for s in segments]
        avg_logprob = sum(logprobs) / len(logprobs) if logprobs else 0.0

        # 把耗时信息拼在文字里交给上层打印，避免这里再依赖日志格式
        self.last_timing = {
            "audio_seconds": round(duration, 2),
            "transcribe_seconds": round(elapsed, 2),
            "language": getattr(info, "language", "?"),
            "language_from_screen": language is not None and self.asr_cfg.language is None,
            "prompt_used": prompt is not None,
            "language_probability": round(getattr(info, "language_probability", 0.0), 2),
        }
        return text, avg_logprob

    def close(self):
        self._model = None

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
audio_io.py —— 兼容层

真正的实现在 voice_tap/audio_io.py。
留这个文件是为了让 tools/ 下面的探测脚本（probe / mic_test / mic_level）
保持原样就能用，不必关心包结构。

新代码请直接 `from voice_tap import audio_io`。
"""

import sys
from pathlib import Path

# 把项目根目录加进来，才能 import voice_tap
_ROOT = str(Path(__file__).resolve().parent.parent)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from voice_tap.audio_io import *          # noqa: F401,F403
from voice_tap.audio_io import (           # noqa: F401
    TARGET_SR, DEFAULT_TIMEOUT_PAD, INFO_MARK, VIRTUAL_HINTS,
    is_probably_virtual, list_input_devices, describe_device,
    default_input_device, check_samplerate, pick_samplerate,
    resample_to_16k, record, quick_test, pick_working_device,
    device_name, device_is_virtual,
    listen_until_silence, trim_silence, record_while, BLOCK_SECONDS, ONSET_BLOCKS,
)

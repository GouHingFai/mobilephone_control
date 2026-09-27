#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
audio_io.py —— 麦克风采集的公共实现

为什么单独抽出来：

1. sounddevice 的 `sd.rec()` + `sd.wait()` 在某些 Windows 音频设备上会**永久卡住**，
   而且不抛异常、不给提示。USB 麦克风、设备不支持的采样率、被其他程序独占，
   都会触发。这里改成「回调式采集 + 硬超时」，最坏情况等几秒就报错退出。

2. 不再写死 16000 Hz。先问设备支不支持（check_input_settings 不会阻塞），
   不支持就用设备自己的默认采样率采集，再重采样到 16000（Whisper 要的格式）。
"""

import threading

import numpy as np

try:
    import sounddevice as sd
except Exception as _exc:  # noqa: BLE001
    # 音频库坏了或不在了，也不该让整个程序起不来 ——
    # 比如 --dump 模式只用 adb，根本不需要麦克风。
    # 这里装一个替身，等真正用到音频时才抛出清楚的错误。
    class _MissingSoundDevice:
        def __getattr__(self, name):
            raise RuntimeError(
                "音频库 sounddevice 不可用，请先运行 setup.bat 安装依赖。\n"
                f"      原始错误：{_exc}"
            )

    sd = _MissingSoundDevice()


TARGET_SR = 16000          # Whisper 要求的采样率
DEFAULT_TIMEOUT_PAD = 4.0  # 录音时长的额外宽限，超过就判定卡死

INFO_MARK = "[**]"         # 给调用方传进来的 log 函数用的提示前缀

# 名字里带这些词的，多半是虚拟声卡 / 环回设备 / 系统聚合设备，
# 它们能"成功"打开并返回数据，但录到的不是你的声音 —— 这是最坑的一类。
# 实测教训：ToDesk 虚拟声卡会被误选，然后整条链路都拿到垃圾数据。
VIRTUAL_HINTS = (
    "virtual", "虚拟", "sound mapper", "voicemeeter", "vb-audio", "cable",
    "loopback", "stereo mix", "立体声混音", "wave out", "todesk",
    "向日葵", "obs", "nvidia broadcast", "steam streaming", "line in",
)


def is_probably_virtual(name):
    """按设备名猜它是不是虚拟 / 环回设备"""
    low = str(name).lower()
    return any(hint in low for hint in VIRTUAL_HINTS)


def list_input_devices():
    """列出所有输入设备 -> [(序号, 名称, 主机API, 默认采样率, 输入通道数)]"""
    devices = sd.query_devices()
    apis = sd.query_hostapis()
    result = []
    for i, d in enumerate(devices):
        if int(d.get("max_input_channels", 0)) > 0:
            api_name = apis[int(d["hostapi"])]["name"]
            result.append((
                i,
                str(d["name"]),
                api_name,
                int(d["default_samplerate"]),
                int(d["max_input_channels"]),
            ))
    return result


def describe_device(index):
    """返回某个设备的可读描述"""
    try:
        d = sd.query_devices(index)
        apis = sd.query_hostapis()
        return (f"{d['name']} (hostapi={apis[int(d['hostapi'])]['name']}, "
                f"默认采样率={int(d['default_samplerate'])}, "
                f"输入通道={int(d['max_input_channels'])})")
    except Exception as exc:  # noqa: BLE001
        return f"<读不到设备 {index} 的信息: {exc}>"


def default_input_device():
    """返回默认输入设备序号，取不到返回 None"""
    try:
        dev = sd.default.device[0]
        return None if dev is None or dev < 0 else int(dev)
    except Exception:
        return None


def check_samplerate(device, samplerate):
    """
    问设备支不支持某个采样率。这是非阻塞的查询，不会卡住。
    返回 (是否支持, 错误信息)。
    """
    try:
        sd.check_input_settings(
            device=device, samplerate=samplerate, channels=1, dtype="float32"
        )
        return True, ""
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}"


def pick_samplerate(device, preferred=TARGET_SR):
    """
    挑一个能用的采样率。优先 preferred（16k），不支持就退回设备默认采样率。
    返回 (采样率, 是否就是首选值)。
    """
    ok, _ = check_samplerate(device, preferred)
    if ok:
        return preferred, True
    try:
        sr = int(sd.query_devices(device)["default_samplerate"])
    except Exception:
        sr = 48000
    return sr, False


def resample_to_16k(data, src_sr):
    """
    把任意采样率的单声道音频变成 16kHz。
    整数倍降采样走「分块取平均」（相当于一个简易抗混叠低通），
    非整数倍走线性插值 —— 对语音识别来说够用。
    """
    data = np.asarray(data, dtype="float32").reshape(-1)
    if src_sr == TARGET_SR or data.size == 0:
        return data

    if src_sr % TARGET_SR == 0:
        factor = src_sr // TARGET_SR
        usable = (data.size // factor) * factor
        if usable == 0:
            return data
        return data[:usable].reshape(-1, factor).mean(axis=1).astype("float32")

    n_out = max(1, int(data.size * TARGET_SR / src_sr))
    idx = np.linspace(0, data.size - 1, n_out)
    return np.interp(idx, np.arange(data.size), data).astype("float32")


def record(seconds, device=None, samplerate=None, timeout_pad=DEFAULT_TIMEOUT_PAD):
    """
    录一段单声道音频。返回 (data_float32, 实际采样率)。

    超时会抛 TimeoutError —— 这是本模块存在的意义，绝不会无限等待。
    """
    if samplerate is None:
        samplerate, _ = pick_samplerate(device)

    target_frames = int(seconds * samplerate)
    chunks = []
    received = [0]
    done = threading.Event()
    status_msgs = []

    def callback(indata, frames, time_info, status):
        if status:
            status_msgs.append(str(status))
        chunks.append(indata.copy())
        received[0] += frames
        if received[0] >= target_frames:
            done.set()
            raise sd.CallbackStop()

    stream = sd.InputStream(
        samplerate=samplerate,
        channels=1,
        dtype="float32",
        device=device,
        callback=callback,
    )

    started = False
    try:
        stream.start()
        started = True
        if not done.wait(timeout=seconds + timeout_pad):
            detail = f"（设备报告：{status_msgs[-1]}）" if status_msgs else ""
            raise TimeoutError(
                f"{seconds + timeout_pad:.0f} 秒内一个音频块都没收到{detail}。"
                "设备可能被别的程序独占，或者这个采样率它处理不了。"
            )
    finally:
        if started:
            try:
                stream.abort()
            except Exception:
                pass
        try:
            stream.close()
        except Exception:
            pass

    if not chunks:
        raise RuntimeError("采集流打开了，但一个音频块都没收到")

    data = np.concatenate(chunks, axis=0)[:, 0]
    return data[:target_frames].astype("float32"), samplerate


def quick_test(device=None, samplerate=None, seconds=1.0):
    """
    开一小段流，验证能不能真的收到数据。
    返回 (是否成功, 说明文字, rms)
    """
    try:
        data, sr = record(seconds, device=device, samplerate=samplerate)
        rms = float(np.sqrt(np.mean(data.astype("float64") ** 2))) if data.size else 0.0
        return True, f"收到 {data.size} 个采样点，采样率 {sr}，RMS={rms:.5f}", rms
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}", 0.0


def device_name(index):
    try:
        return str(sd.query_devices(index)["name"])
    except Exception:
        return ""


def device_is_virtual(index):
    """设备名看起来像虚拟声卡吗"""
    return is_probably_virtual(device_name(index))


def pick_working_device(prefer=None, test_seconds=0.6, log=None):
    """
    找一个"真的能录到音频"的输入设备。

    先试 prefer（默认就是系统的默认输入设备），不行再挨个试其他设备。
    USB 麦克风常常是「系统默认那个反而不能用」，所以这个兜底很有必要。

    **优先挑真实麦克风，虚拟声卡排在最后。** 虚拟声卡（ToDesk / VoiceMeeter /
    立体声混音这类）能假装打开成功，但录到的不是人声，会把整条链路带偏。

    返回 (设备序号, 采样率)；全都失败返回 (None, None)。
    """
    devices = list_input_devices()
    if not devices:
        return None, None

    default_idx = default_input_device()

    # 尝试顺序：指定的 -> 系统默认 -> 其余的
    order = []
    if prefer is not None:
        order.append(prefer)
    if default_idx is not None:
        order.append(default_idx)
    order.extend(idx for idx, *_ in devices)

    # 去重，同时把「真实设备」排在「虚拟设备」前面
    seen = set()
    unique = []
    for idx in order:
        if idx in seen:
            continue
        seen.add(idx)
        unique.append(idx)

    real_devices = [i for i in unique if not device_is_virtual(i)]
    virtual_devices = [i for i in unique if device_is_virtual(i)]

    for idx in real_devices + virtual_devices:
        samplerate, _ = pick_samplerate(idx)
        ok, msg, _rms = quick_test(device=idx, samplerate=samplerate, seconds=test_seconds)

        if log is not None:
            tag = "（虚拟设备）" if device_is_virtual(idx) else ""
            status = "可用" if ok else "不可用"
            extra = f"（{samplerate} Hz）" if ok else f"  ← {msg}"
            log(f"      设备 [{idx}] {describe_device(idx)} -> {status}{tag}{extra}")

        if ok:
            if device_is_virtual(idx) and real_devices:
                # 真实设备明明存在却没测通，这里不该轮到虚拟设备
                log(f"      {INFO_MARK} 注意：真实麦克风都没测通，只能退回虚拟设备。")
                log("           虚拟设备录到的不是你的声音，识别结果会不可用。")
            return idx, samplerate

    return None, None


# ---------------------------------------------------------------- 流式监听

BLOCK_SECONDS = 0.02      # 每块 20 毫秒
ONSET_BLOCKS = 2          # 连续这么多块超阈值才算「开口」，滤掉瞬时杂音


def listen_until_silence(
    vad_threshold=0.02,
    silence_duration=0.4,
    max_utterance=6.0,
    pre_roll=0.3,
    start_timeout=None,
    device=None,
    samplerate=None,
    on_speech_start=None,
    stop_event=None,
):
    """
    等你说一句话，自动切句。

    工作方式：
      - 安静时持续缓冲最近 pre_roll 秒的音频（这样不会把词的起头切掉）
      - 连续 ONSET_BLOCKS 块音量超阈值 → 判定开口，把缓冲一起纳入
      - 之后持续收音，直到静音超过 silence_duration
      - 单句最长 max_utterance 秒，超时强制切

    返回 (音频float32, 采样率)；如果 start_timeout 秒内一直没人说话，返回 None。
    """
    import collections
    import time

    if samplerate is None:
        samplerate, _ = pick_samplerate(device)

    blocksize = max(1, int(BLOCK_SECONDS * samplerate))
    preroll_blocks = max(1, int(pre_roll / BLOCK_SECONDS))
    silence_blocks = max(1, int(silence_duration / BLOCK_SECONDS))
    max_blocks = max(1, int(max_utterance / BLOCK_SECONDS))

    ring = collections.deque(maxlen=preroll_blocks)
    captured = []
    done = threading.Event()
    state = {
        "started": False,
        "onset": 0,
        "silence": 0,
        "blocks_after_start": 0,
        "stopped": False,
    }

    def callback(indata, frames, time_info, status):
        mono = indata[:, 0]
        rms = float(np.sqrt(np.mean(mono.astype("float64") ** 2)))

        if not state["started"]:
            ring.append(mono.copy())
            if rms >= vad_threshold:
                state["onset"] += 1
                if state["onset"] >= ONSET_BLOCKS:
                    state["started"] = True
                    captured.extend(list(ring))
                    ring.clear()
                    if on_speech_start is not None:
                        try:
                            on_speech_start()
                        except Exception:
                            pass
            else:
                state["onset"] = 0
            return

        captured.append(mono.copy())
        state["blocks_after_start"] += 1

        if rms < vad_threshold:
            state["silence"] += 1
            if state["silence"] >= silence_blocks:
                state["stopped"] = True
                done.set()
                raise sd.CallbackStop()
        else:
            state["silence"] = 0

        if state["blocks_after_start"] >= max_blocks:
            state["stopped"] = True
            done.set()
            raise sd.CallbackStop()

    stream = sd.InputStream(
        samplerate=samplerate,
        channels=1,
        dtype="float32",
        device=device,
        blocksize=blocksize,
        callback=callback,
    )

    started = False
    deadline = None if start_timeout is None else time.time() + start_timeout

    try:
        stream.start()
        started = True
        while not done.is_set():
            if stop_event is not None and stop_event.is_set():
                break
            if deadline is not None and not state["started"]:
                if time.time() >= deadline:
                    break
            done.wait(0.05)
    finally:
        if started:
            try:
                stream.abort()
            except Exception:
                pass
        try:
            stream.close()
        except Exception:
            pass

    if not state["started"] or not captured:
        return None

    # captured 里存的已经是取过声道的一维数组，直接拼即可 ——
    # 不要再写 [:, 0]，那是对二维数组才成立的写法（曾经照抄 record() 的收尾代码，
    # 结果这里抛 IndexError，程序一开口就崩）
    data = np.concatenate(captured, axis=0).astype("float32").reshape(-1)
    return data, samplerate


def record_while(held_event, max_seconds=20.0, device=None, samplerate=None, min_seconds=0.2):
    """
    「按住说话」：held_event 为真期间一直录，一旦置假就停。

    和 listen_until_silence 的区别在于**收尾方式**：
    那边靠检测静音自动切句，这边靠松手。热键模式用这个，
    因为用户按住的时候就是在说，松开就是「我说完了」，不需要 VAD 去猜。

    返回 (音频, 采样率)；按得太短（少于 min_seconds）返回 None。
    """
    import time

    if samplerate is None:
        samplerate, _ = pick_samplerate(device)

    blocksize = max(1, int(BLOCK_SECONDS * samplerate))
    max_blocks = max(1, int(max_seconds / BLOCK_SECONDS))

    captured = []
    done = threading.Event()
    counter = {"blocks": 0}

    def callback(indata, frames, time_info, status):
        captured.append(indata[:, 0].copy())
        counter["blocks"] += 1
        if counter["blocks"] >= max_blocks:
            done.set()
            raise sd.CallbackStop()

    stream = sd.InputStream(
        samplerate=samplerate,
        channels=1,
        dtype="float32",
        device=device,
        blocksize=blocksize,
        callback=callback,
    )

    started = False
    try:
        stream.start()
        started = True
        # 只要还按着（或还没到上限）就继续收
        while held_event.is_set() and not done.is_set():
            done.wait(0.03)
    finally:
        if started:
            try:
                stream.abort()
            except Exception:
                pass
        try:
            stream.close()
        except Exception:
            pass

    if not captured:
        return None

    # 同 listen_until_silence：这里存的是一维数组，不需要再取声道
    data = np.concatenate(captured, axis=0).astype("float32").reshape(-1)
    if data.size < int(min_seconds * samplerate):
        return None
    return data, samplerate


def trim_silence(data, threshold, frame=160):
    """
    把首尾的静音裁掉。送进 Whisper 的音频短了，识别就快。
    只裁首尾，中间的停顿保留（中间停顿可能是词的一部分）。
    """
    if data is None or data.size == 0:
        return data
    data = np.asarray(data, dtype="float32").reshape(-1)

    rms_per_frame = []
    for start in range(0, data.size - frame + 1, frame):
        chunk = data[start:start + frame].astype("float64")
        rms_per_frame.append(float(np.sqrt(np.mean(chunk ** 2))))
    if not rms_per_frame:
        return data

    voiced = [i for i, r in enumerate(rms_per_frame) if r >= threshold]
    if not voiced:
        return data

    first = max(0, voiced[0] - 2) * frame            # 往前留一点，别切掉起音
    last = min(len(rms_per_frame), voiced[-1] + 3) * frame
    return data[first:last]

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""

config.py —— 读取 config.yaml

设计原则：**配置读不到也要能跑。**
任何一个键缺失或整个文件不存在，都退回默认值，只在日志里提一句，
绝不让一个打错的 YAML 缩进把程序拦在门外。
"""
from __future__ import annotations  # 让 int | None 这类写法在 Python 3.9 上也能用

from dataclasses import dataclass, field
from pathlib import Path


DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.yaml"


@dataclass
class AudioConfig:
    # None 表示「自动挑选可用设备」；config.yaml 里填 1 就是强制用设备 1
    input_device: int | None = None
    samplerate: int | None = None
    vad_threshold: float = 0.0246
    silence_duration: float = 0.4
    max_utterance: float = 6.0


@dataclass
class AsrConfig:
    model: str = "small"
    language: str | None = None
    min_confidence: float = -1.0
    # 贪心解码比 beam search 快好几倍，短词识别精度几乎不损失
    beam_size: int = 1
    # 送进模型前把首尾静音裁掉。
    #
    # 实测后改成默认关：识别耗时是**固定的**（和音频长短几乎无关，见 3.2 秒那次测量），
    # 所以裁掉静音并不能省时间，却减少了模型可用的上下文，反而更容易听错。
    trim_silence: bool = False

    # 让模型再做一次静音过滤。
    # 我们自己已经做过一遍了，这层可能是重复劳动 —— 留成开关方便对比。
    vad_filter: bool = True

    # 用手机屏幕上的选项来辅助识别：判断该按中文还是英文、并把选项当提示词喂给模型。
    # 实测发现这一条对准确率影响很大。
    use_screen_hint: bool = True


@dataclass
class MatchConfig:
    fuzzy_enabled: bool = True
    max_distance: int = 1
    pinyin_enabled: bool = True
    min_substring_length: int = 2


@dataclass
class ClickConfig:
    # 语音路径的防连点（毫秒）。几乎不会触发 —— 语音整条流水线本身
    # 就要 2 秒以上，两次点击天然相隔很远。留着纯粹是保险。
    #
    # 注意：**按键动作不受这个限制**。按住不放造成的重复是在 hotkey
    # 那一层用「按下/抬起」状态挡的，不靠计时。
    debounce_ms: int = 400

    settle_ms: int = 300


@dataclass
class HotkeyConfig:
    push_to_talk: str = "f8"
    toggle_mode: str = "f9"
    toggle_numpad: str = "f10"
    # 开关语音（F7）。点完选项后手机会念单词，如果干扰太严重可以临时关掉
    toggle_voice: str = "f7"
    # 小键盘模式。默认关：虽然只截小键盘、不碰主键盘，
    # 但「按个数字就点一下」这件事还是让用户自己决定什么时候开。
    numpad_enabled: bool = False
    # 反过来对应：小键盘 1 对应最后一个选项
    numpad_reverse: bool = False
    # 「下一题」按钮坐标。答错或点「不记得了」之后会进详情页，靠它继续。
    # 留空（默认）则每次读屏去找按钮；填了就固定用它，不读屏。
    fixed_next_position: tuple | None = None


@dataclass
class VoiceConfig:
    """
    语音开关与静音期。

    为什么需要「静音期」：点完一个选项之后，**手机会把那个单词的读音播出来**，
    麦克风会把它收进去。程序会误以为你在说话，送去识别，得到的就是刚答过那个词
    （实测日志里那些 'Brooke.' 'Benevolent' 'Convey' 全是手机念的，不是用户说的）。

    然后等用户真正开口时，界面早翻过去了，什么都匹配不上。
    """

    # 点击之后多长时间内不监听语音（毫秒）。
    # 一个单词的读音约 1～1.2 秒，加上点击到开始播放的延迟，取 2 秒。
    # 调小 → 你能更快开始说下一句；调大 → 更不容易被手机的声音带偏。
    mute_after_click_ms: int = 2000

    # 启动时语音是否开启（运行中按 F7 可以随时开关）
    enabled: bool = True


@dataclass
class RunConfig:
    default_mode: str = "listen"
    preview: bool = False
    sound: bool = False


@dataclass
class PrefetchConfig:
    """
    预读界面：在后台提前把界面读好，等你需要时立刻能用。

    两个时机，各自独立开关：
      - 检测到你开口时（说话那一两秒正好够读一次）
      - 点击之后（趁界面翻页的空档）
    """

    # 开口时预读。先默认关掉，用来对比「点击后预读」单独能带来多少收益。
    on_speech: bool = False

    # 点击后预读
    after_click: bool = True

    # 点击后先等多久再读（毫秒）。
    # 太早读到的是翻页前的界面 —— 那是最危险的情况（拿旧坐标点新题）。
    click_delay_ms: int = 300

    # 读到还是旧界面时，隔多久再读一次（毫秒）
    click_retry_ms: int = 250

    # 最多尝试几次
    click_max_attempts: int = 4

    # 预读结果最多能用多久（秒）。
    # 放太久有风险：如果你用鼠标自己翻了页，缓存里就是过期界面。
    # 超时就退回当场读屏（慢一点，但一定是当前的）。
    cache_max_age: float = 8.0


@dataclass
class Config:
    audio: AudioConfig = field(default_factory=AudioConfig)
    asr: AsrConfig = field(default_factory=AsrConfig)
    match: MatchConfig = field(default_factory=MatchConfig)
    click: ClickConfig = field(default_factory=ClickConfig)
    hotkey: HotkeyConfig = field(default_factory=HotkeyConfig)
    voice: VoiceConfig = field(default_factory=VoiceConfig)
    run: RunConfig = field(default_factory=RunConfig)
    prefetch: PrefetchConfig = field(default_factory=PrefetchConfig)
    # 加载过程中的提示信息，交给调用方打印（模块本身不直接输出）
    notices: list = field(default_factory=list)


TRUE_WORDS = {"true", "yes", "on", "1", "是", "开", "打开", "启用"}
FALSE_WORDS = {"false", "no", "off", "0", "否", "关", "关闭", "禁用"}


def _to_bool(value):
    """比内置 bool() 靠谱：能正确理解 'false' 'no' '关' 这类写法"""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    text = str(value).strip().lower()
    if text in TRUE_WORDS:
        return True
    if text in FALSE_WORDS:
        return False
    raise ValueError(f"看不懂的布尔值 {value!r}")


def _to_positions(value):
    """
    把坐标转成 [(x, y), ...]。

    接受三种写法：
        [606, 811]                  单个坐标（扁平写法）
        [[606, 811], [606, 999]]    坐标列表
        ["606,811", "606,999"]      字符串写法

    解析不出来的项直接跳过 —— 宁可少一个坐标，也不要因为一行写错就整个配置失效。
    """
    if not value:
        return []
    if not isinstance(value, (list, tuple)):
        value = [value]

    # 扁平写法 [x, y]：整份就是一个坐标。
    # 没有这一条的话，[600, 2180] 会被当成「两个元素」逐个解析，结果两个都解析不出来，
    # 最后返回空 —— 配置看着填了，实际静默失效。
    if len(value) == 2 and all(isinstance(v, (int, float)) and not isinstance(v, bool)
                               for v in value):
        return [(int(value[0]), int(value[1]))]

    out = []
    for item in value:
        try:
            if isinstance(item, str):
                x_text, y_text = item.split(",")
                out.append((int(x_text.strip()), int(y_text.strip())))
            elif isinstance(item, (list, tuple)) and len(item) == 2:
                out.append((int(item[0]), int(item[1])))
        except (TypeError, ValueError):
            continue
    return out


def _to_position(value):
    """单个坐标 [x, y]；解析不出来就返回 None"""
    positions = _to_positions(value)
    return positions[0] if positions else None


def _pick(section: dict, key: str, default, caster, notices, where: str):
    """
    从一个分组里取一个键。任何异常都退回默认值，绝不让配置问题挡住程序启动。
    """
    if not isinstance(section, dict) or key not in section:
        return default

    raw = section[key]

    if raw is None:
        # 显式写成 null：可空字段保持 None（例如 input_device: null 表示自动挑选），
        # 不可空字段则视为无效，退回默认值
        if default is None:
            return None
        notices.append(f"config.yaml 的 {where}.{key} 是 null，但该字段不能为空，改用默认值 {default!r}")
        return default

    try:
        return caster(raw)
    except (TypeError, ValueError):
        notices.append(f"config.yaml 的 {where}.{key} 值不合法（{raw!r}），改用默认值 {default!r}")
        return default


def load_config(path=None) -> Config:
    """
    读取配置文件。任何问题都降级为默认值，并记在 cfg.notices 里。
    """
    cfg = Config()
    path = Path(path) if path else DEFAULT_CONFIG_PATH

    if not path.is_file():
        cfg.notices.append(f"没找到 {path}，全部使用默认值")
        return cfg

    try:
        import yaml
    except ImportError:
        cfg.notices.append("没装 pyyaml，无法读取 config.yaml，全部使用默认值")
        return cfg

    try:
        with open(path, encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
    except Exception as exc:  # noqa: BLE001
        cfg.notices.append(f"读取 {path} 失败（{type(exc).__name__}: {exc}），全部使用默认值")
        return cfg

    if not isinstance(data, dict):
        cfg.notices.append(f"{path} 的内容不是一个字典，全部使用默认值")
        return cfg

    n = cfg.notices

    a = data.get("audio") or {}
    cfg.audio = AudioConfig(
        input_device=_pick(a, "input_device", AudioConfig.input_device, int, n, "audio"),
        samplerate=_pick(a, "samplerate", AudioConfig.samplerate, int, n, "audio"),
        vad_threshold=_pick(a, "vad_threshold", AudioConfig.vad_threshold, float, n, "audio"),
        silence_duration=_pick(a, "silence_duration", AudioConfig.silence_duration, float, n, "audio"),
        max_utterance=_pick(a, "max_utterance", AudioConfig.max_utterance, float, n, "audio"),
    )

    s = data.get("asr") or {}
    cfg.asr = AsrConfig(
        model=_pick(s, "model", AsrConfig.model, str, n, "asr"),
        language=_pick(s, "language", AsrConfig.language, str, n, "asr"),
        min_confidence=_pick(s, "min_confidence", AsrConfig.min_confidence, float, n, "asr"),
        beam_size=_pick(s, "beam_size", AsrConfig.beam_size, int, n, "asr"),
        trim_silence=_pick(s, "trim_silence", AsrConfig.trim_silence, _to_bool, n, "asr"),
        vad_filter=_pick(s, "vad_filter", AsrConfig.vad_filter, _to_bool, n, "asr"),
        use_screen_hint=_pick(s, "use_screen_hint", AsrConfig.use_screen_hint, _to_bool, n, "asr"),
    )

    m = data.get("match") or {}
    cfg.match = MatchConfig(
        fuzzy_enabled=_pick(m, "fuzzy_enabled", MatchConfig.fuzzy_enabled, _to_bool, n, "match"),
        max_distance=_pick(m, "max_distance", MatchConfig.max_distance, int, n, "match"),
        pinyin_enabled=_pick(m, "pinyin_enabled", MatchConfig.pinyin_enabled, _to_bool, n, "match"),
        min_substring_length=_pick(m, "min_substring_length", MatchConfig.min_substring_length, int, n, "match"),
    )

    c = data.get("click") or {}
    cfg.click = ClickConfig(
        debounce_ms=_pick(c, "debounce_ms", ClickConfig.debounce_ms, int, n, "click"),
        settle_ms=_pick(c, "settle_ms", ClickConfig.settle_ms, int, n, "click"),
    )

    h = data.get("hotkey") or {}
    cfg.hotkey = HotkeyConfig(
        push_to_talk=_pick(h, "push_to_talk", HotkeyConfig.push_to_talk, str, n, "hotkey"),
        toggle_mode=_pick(h, "toggle_mode", HotkeyConfig.toggle_mode, str, n, "hotkey"),
        toggle_numpad=_pick(h, "toggle_numpad", HotkeyConfig.toggle_numpad, str, n, "hotkey"),
        toggle_voice=_pick(h, "toggle_voice", HotkeyConfig.toggle_voice, str, n, "hotkey"),
        numpad_enabled=_pick(h, "numpad_enabled", HotkeyConfig.numpad_enabled, _to_bool, n, "hotkey"),
        numpad_reverse=_pick(h, "numpad_reverse", HotkeyConfig.numpad_reverse, _to_bool, n, "hotkey"),
        fixed_next_position=_to_position(h.get("fixed_next_position")),
    )

    v = data.get("voice") or {}
    cfg.voice = VoiceConfig(
        mute_after_click_ms=_pick(v, "mute_after_click_ms", VoiceConfig.mute_after_click_ms,
                                  int, n, "voice"),
        enabled=_pick(v, "enabled", VoiceConfig.enabled, _to_bool, n, "voice"),
    )

    r = data.get("run") or {}
    cfg.run = RunConfig(
        default_mode=_pick(r, "default_mode", RunConfig.default_mode, str, n, "run"),
        preview=_pick(r, "preview", RunConfig.preview, _to_bool, n, "run"),
        sound=_pick(r, "sound", RunConfig.sound, _to_bool, n, "run"),
    )

    pf = data.get("prefetch") or {}
    cfg.prefetch = PrefetchConfig(
        on_speech=_pick(pf, "on_speech", PrefetchConfig.on_speech, _to_bool, n, "prefetch"),
        after_click=_pick(pf, "after_click", PrefetchConfig.after_click, _to_bool, n, "prefetch"),
        click_delay_ms=_pick(pf, "click_delay_ms", PrefetchConfig.click_delay_ms, int, n, "prefetch"),
        click_retry_ms=_pick(pf, "click_retry_ms", PrefetchConfig.click_retry_ms, int, n, "prefetch"),
        click_max_attempts=_pick(pf, "click_max_attempts", PrefetchConfig.click_max_attempts,
                                 int, n, "prefetch"),
        cache_max_age=_pick(pf, "cache_max_age", PrefetchConfig.cache_max_age, float, n, "prefetch"),
    )

    if cfg.run.default_mode not in ("listen", "hotkey"):
        n.append(f"run.default_mode 只能是 listen 或 hotkey，收到 {cfg.run.default_mode!r}，改用 listen")
        cfg.run.default_mode = "listen"

    return cfg

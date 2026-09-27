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

    # 允许说「下一题」翻页（答错进详情页后用它继续）。
    #
    # 注意这是**直给**：说了就点固定坐标，不读屏校验 ——
    # 因此在答题页上误说也会点下去。这是用户明确选择的取舍。
    next_command: bool = True


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

    # 读到还是旧界面时，隔多久再读一次（毫秒）。
    # 注意现在总共**最多读两次**：第一次读到新界面就收工，还是旧界面就隔这么久
    # 再读一次确认（第二次无论读到什么都收下）。不再有第 3、4 次。
    click_retry_ms: int = 250

    # 预读结果最多能用多久（秒）。
    # 放太久有风险：如果你用鼠标自己翻了页，缓存里就是过期界面。
    # 超时就退回当场读屏（慢一点，但一定是当前的）。
    cache_max_age: float = 8.0


@dataclass
class GuiConfig:
    """
    置顶浮窗（gui.py）。

    默认**不自动开**：界面要占主线程、还依赖 Tkinter，不是每台机器都合适。
    命令行加 `--gui` 可以临时打开，不必改这里。
    """

    # 启动时是否自动开界面
    enabled: bool = False

    # 窗口位置与大小 [x, y, 宽, 高]。
    #
    # 注意：**关窗口时的当前位置不写回这里** —— pyyaml 回写会把这份逐行手写的
    # 注释全抹掉。它单独存在 debug/gui_window.txt 里（见 main._save_window_geometry）。
    window: tuple = (40, 120, 360, 520)

    # 是否始终浮在最上层（scrcpy 就在下面）
    topmost: bool = True

    # 界面刷新间隔（毫秒）
    refresh_ms: int = 150


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
    gui: GuiConfig = field(default_factory=GuiConfig)
    # 加载过程中的提示信息，交给调用方打印（模块本身不直接输出）
    notices: list = field(default_factory=list)


TRUE_WORDS = {"true", "yes", "on", "1", "是", "开", "打开", "启用"}
FALSE_WORDS = {"false", "no", "off", "0", "否", "关", "关闭", "禁用"}

# 界面刷新间隔的下限（毫秒）。
# `root.after(0, ...)` 是**忙循环**：每次刷新完立刻又排一次，主线程被界面占死，
# 听语音那条线程也跟着挨饿。所以比这个数还小的值一律抬上来。
MIN_GUI_REFRESH_MS = 30


def _section(data: dict, key: str, notices) -> dict:
    """
    取一个顶层配置段（audio / asr / … / gui）。

    段的值**必须是映射**。YAML 里手滑写成 `gui: 3` / `hotkey: 3` / `match: true`
    这种非映射值，后面随手的 `.get(...)` 就会抛 AttributeError，
    整个 `load_config` 当场崩 —— **连不带 `--gui` 的正常路径都起不来**。
    这与本模块的根本原则直接冲突，所以在这里统一兜住：退回空字典（该段全部用默认值），
    并留一句提示 —— 不然用户那一整段配置白写了都不知道。

    键不存在（或显式 null）时保持**静默**，和 `_pick` 一贯的行为一致。
    """
    value = data.get(key)
    if value is None:
        return {}
    if not isinstance(value, dict):
        notices.append(f"config.yaml 的 {key} 段不是一个配置段（{value!r}），"
                       f"该段全部使用默认值")
        return {}
    return value


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


def _to_window(value, default, notices):
    """
    把 `gui.window` 解析成 (x, y, 宽, 高) 四个整数；不合法就整体退回默认值。

    为什么要「整体退回」而不是逐个数补默认：**半截的窗口位置没有意义** ——
    缺一个数、或者里面混进了文字，拼出来的窗口会跑到屏幕外面去，
    还不如干脆用默认位置。这是「读不到也要能跑」那条原则的延续。
    """
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        notices.append(f"config.yaml 的 gui.window 不是四个数（{value!r}），"
                       f"改用默认值 {default!r}")
        return default
    try:
        return tuple(int(v) for v in value)
    except (TypeError, ValueError):
        notices.append(f"config.yaml 的 gui.window 里有非整数（{value!r}），"
                       f"改用默认值 {default!r}")
        return default


def _to_refresh_ms(value, notices):
    """
    界面刷新间隔（毫秒）。太小会变成忙循环，一律抬到下限。

    非数字的坏值在 `_pick` 那层就已经退默认值了，到不了这里 ——
    这里只管「是数字但小得离谱」（0、负数、个位数）。
    """
    if value < MIN_GUI_REFRESH_MS:
        notices.append(f"config.yaml 的 gui.refresh_ms 太小（{value}），"
                       f"刷新会变成忙循环，改用 {MIN_GUI_REFRESH_MS}")
        return MIN_GUI_REFRESH_MS
    return value


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

    a = _section(data, "audio", n)
    cfg.audio = AudioConfig(
        input_device=_pick(a, "input_device", AudioConfig.input_device, int, n, "audio"),
        samplerate=_pick(a, "samplerate", AudioConfig.samplerate, int, n, "audio"),
        vad_threshold=_pick(a, "vad_threshold", AudioConfig.vad_threshold, float, n, "audio"),
        silence_duration=_pick(a, "silence_duration", AudioConfig.silence_duration, float, n, "audio"),
        max_utterance=_pick(a, "max_utterance", AudioConfig.max_utterance, float, n, "audio"),
    )

    s = _section(data, "asr", n)
    cfg.asr = AsrConfig(
        model=_pick(s, "model", AsrConfig.model, str, n, "asr"),
        language=_pick(s, "language", AsrConfig.language, str, n, "asr"),
        min_confidence=_pick(s, "min_confidence", AsrConfig.min_confidence, float, n, "asr"),
        beam_size=_pick(s, "beam_size", AsrConfig.beam_size, int, n, "asr"),
        trim_silence=_pick(s, "trim_silence", AsrConfig.trim_silence, _to_bool, n, "asr"),
        vad_filter=_pick(s, "vad_filter", AsrConfig.vad_filter, _to_bool, n, "asr"),
        use_screen_hint=_pick(s, "use_screen_hint", AsrConfig.use_screen_hint, _to_bool, n, "asr"),
    )

    m = _section(data, "match", n)
    cfg.match = MatchConfig(
        fuzzy_enabled=_pick(m, "fuzzy_enabled", MatchConfig.fuzzy_enabled, _to_bool, n, "match"),
        max_distance=_pick(m, "max_distance", MatchConfig.max_distance, int, n, "match"),
        pinyin_enabled=_pick(m, "pinyin_enabled", MatchConfig.pinyin_enabled, _to_bool, n, "match"),
        min_substring_length=_pick(m, "min_substring_length", MatchConfig.min_substring_length, int, n, "match"),
    )

    c = _section(data, "click", n)
    cfg.click = ClickConfig(
        debounce_ms=_pick(c, "debounce_ms", ClickConfig.debounce_ms, int, n, "click"),
        settle_ms=_pick(c, "settle_ms", ClickConfig.settle_ms, int, n, "click"),
    )

    h = _section(data, "hotkey", n)
    cfg.hotkey = HotkeyConfig(
        push_to_talk=_pick(h, "push_to_talk", HotkeyConfig.push_to_talk, str, n, "hotkey"),
        toggle_mode=_pick(h, "toggle_mode", HotkeyConfig.toggle_mode, str, n, "hotkey"),
        toggle_numpad=_pick(h, "toggle_numpad", HotkeyConfig.toggle_numpad, str, n, "hotkey"),
        toggle_voice=_pick(h, "toggle_voice", HotkeyConfig.toggle_voice, str, n, "hotkey"),
        numpad_enabled=_pick(h, "numpad_enabled", HotkeyConfig.numpad_enabled, _to_bool, n, "hotkey"),
        numpad_reverse=_pick(h, "numpad_reverse", HotkeyConfig.numpad_reverse, _to_bool, n, "hotkey"),
        fixed_next_position=_to_position(h.get("fixed_next_position")),
    )

    v = _section(data, "voice", n)
    cfg.voice = VoiceConfig(
        mute_after_click_ms=_pick(v, "mute_after_click_ms", VoiceConfig.mute_after_click_ms,
                                  int, n, "voice"),
        enabled=_pick(v, "enabled", VoiceConfig.enabled, _to_bool, n, "voice"),
        next_command=_pick(v, "next_command", VoiceConfig.next_command, _to_bool, n, "voice"),
    )

    r = _section(data, "run", n)
    cfg.run = RunConfig(
        default_mode=_pick(r, "default_mode", RunConfig.default_mode, str, n, "run"),
        preview=_pick(r, "preview", RunConfig.preview, _to_bool, n, "run"),
        sound=_pick(r, "sound", RunConfig.sound, _to_bool, n, "run"),
    )

    pf = _section(data, "prefetch", n)
    cfg.prefetch = PrefetchConfig(
        on_speech=_pick(pf, "on_speech", PrefetchConfig.on_speech, _to_bool, n, "prefetch"),
        after_click=_pick(pf, "after_click", PrefetchConfig.after_click, _to_bool, n, "prefetch"),
        click_delay_ms=_pick(pf, "click_delay_ms", PrefetchConfig.click_delay_ms, int, n, "prefetch"),
        click_retry_ms=_pick(pf, "click_retry_ms", PrefetchConfig.click_retry_ms, int, n, "prefetch"),
        cache_max_age=_pick(pf, "cache_max_age", PrefetchConfig.cache_max_age, float, n, "prefetch"),
    )

    gt = _section(data, "gui", n)
    cfg.gui = GuiConfig(
        enabled=_pick(gt, "enabled", GuiConfig.enabled, _to_bool, n, "gui"),
        # 键不存在时静默用默认值（和 _pick 一样）。以前是 `gt.get("window")`，
        # 段不存在时拿到 None，被 _to_window 当成坏值白报一条「window 不是四个数」。
        window=(_to_window(gt["window"], GuiConfig.window, n)
                if "window" in gt else GuiConfig.window),
        topmost=_pick(gt, "topmost", GuiConfig.topmost, _to_bool, n, "gui"),
        refresh_ms=_to_refresh_ms(
            _pick(gt, "refresh_ms", GuiConfig.refresh_ms, int, n, "gui"), n),
    )

    if cfg.run.default_mode not in ("listen", "hotkey"):
        n.append(f"run.default_mode 只能是 listen 或 hotkey，收到 {cfg.run.default_mode!r}，改用 listen")
        cfg.run.default_mode = "listen"

    return cfg

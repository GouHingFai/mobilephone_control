#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
matcher.py —— 把「听到的话」匹配到「屏幕上的选项」

匹配策略是三级降级，从最可信到最宽松：

    1. 精确        归一化后完全相等
    2. 子串        「你说的词」出现在选项文字里 —— 这是主力
                   例如说「简单」命中「简单、朴素」
    3. 拼音子串    字形对不上但读音对得上，例如「骄奢淫逸」听成「骄奢淫意」
    4. 模糊        编辑距离兜底，容忍听错一两个字母

用户的实际用法是「只说选项里的一小部分」，所以第 2 级承担了绝大多数工作，
而且因为说的词短，ASR 反而更不容易听错 —— 这比要求说完整更可靠。

本模块全是纯函数，没有副作用，正确性由单元测试保证。
"""

import re
from dataclasses import dataclass, field


# 全角字符到半角的偏移
_FULLWIDTH_OFFSET = 0xFEE0


def to_halfwidth(text: str) -> str:
    """全角转半角（ＡＢＣ → ABC，１ → 1）"""
    out = []
    for ch in text:
        code = ord(ch)
        if code == 0x3000:              # 全角空格
            out.append(" ")
        elif 0xFF01 <= code <= 0xFF5E:  # 全角标点、字母、数字
            out.append(chr(code - _FULLWIDTH_OFFSET))
        else:
            out.append(ch)
    return "".join(out)


# 归一化时丢弃的字符：标点、空白、各种分隔符
# 保留：拉丁字母、数字、中日韩汉字
_KEEP_RE = re.compile(r"[^0-9a-z一-鿿]+")


def normalize(text: str) -> str:
    """
    归一化成可比较的形式：
    全角转半角 → 转小写 → 丢掉所有标点和空白。

    这样「adj. 清晰易懂的」和「ADJ 清晰易懂的」会得到同一个键，
    用户说的「清晰易懂的」也能作为子串命中。
    """
    if not text:
        return ""
    return _KEEP_RE.sub("", to_halfwidth(str(text)).lower())


def to_pinyin(text: str) -> str:
    """把文字转成无声调拼音连写。没装 pypinyin 就返回空串。"""
    key = normalize(text)
    if not key:
        return ""
    try:
        from pypinyin import lazy_pinyin
    except ImportError:
        return ""
    try:
        return "".join(lazy_pinyin(key))
    except Exception:  # noqa: BLE001
        return ""


def edit_distance(a: str, b: str, ceiling: int = 99) -> int:
    """
    Levenshtein 距离。超过 ceiling 就提前返回 ceiling+1（省算力）。
    """
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    if abs(len(a) - len(b)) > ceiling:
        return ceiling + 1

    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        current = [i]
        row_min = i
        for j, cb in enumerate(b, 1):
            cost = 0 if ca == cb else 1
            value = min(
                previous[j] + 1,        # 删除
                current[j - 1] + 1,     # 插入
                previous[j - 1] + cost, # 替换
            )
            current.append(value)
            if value < row_min:
                row_min = value
        if row_min > ceiling:
            return ceiling + 1
        previous = current
    return previous[-1]


def best_window_distance(needle: str, haystack: str, ceiling: int = 2) -> int:
    """
    在 haystack 里滑动一个长度接近 needle 的窗口，返回最小编辑距离。

    为什么不直接算整串距离：选项往往比用户说的长得多
    （「adj. 清晰易懂的」vs「清晰易懂的」），整串比会被前缀拉开距离，
    滑动窗口才反映「其中某一段像不像」。
    """
    n = len(needle)
    if n == 0 or not haystack:
        return ceiling + 1
    if haystack == needle:
        return 0

    best = ceiling + 1
    max_start = max(1, len(haystack) - n + 1)
    for start in range(max_start):
        for window_len in (n, n - 1, n + 1):
            if window_len <= 0:
                continue
            window = haystack[start:start + window_len]
            if len(window) < max(1, n - 1):
                continue
            distance = edit_distance(needle, window, ceiling)
            if distance < best:
                best = distance
                if best == 0:
                    return 0
    return best


# 匹配级别，数字越小越可信。
# 0 专门留给「没匹配上」，所以下面都从 1 开始编 —— 否则 level==0 会有两种含义。
LEVEL_NONE = 0
LEVEL_ORDINAL = 1       # 说序号（"1" / "第一个"），最明确
LEVEL_EXACT = 2
LEVEL_SUBSTRING = 3
LEVEL_CONTAINS = 4      # 反过来：选项是你说的话的一部分
LEVEL_STEM = 5          # 英语词形：原形 vs 变形
LEVEL_PINYIN = 6
LEVEL_FUZZY = 7

LEVEL_NAMES = {
    LEVEL_ORDINAL: "序号命中",
    LEVEL_EXACT: "精确命中",
    LEVEL_SUBSTRING: "子串命中",
    LEVEL_CONTAINS: "包含命中",
    LEVEL_STEM: "词形命中",
    LEVEL_PINYIN: "拼音命中",
    LEVEL_FUZZY: "模糊命中",
}

# 英文常见后缀。
#
# 为什么需要这一级：语音识别经常把词典原形听成变形 —— 实测里用户说 qualify，
# 识别成 "Qualified"；说 retrieve，识别成 "retrieving"。而屏幕上的选项
# 都是词典原形。原来的子串/包含两级都处理不了（qualify 根本不是 qualified 的子串，
# 因为 y 变成了 ied），于是明明听对了却匹配不上。
_EN_SUFFIXES = (
    "ically", "ation", "ition", "ingly", "edly",
    "ing", "ed", "es", "s", "ly", "er", "est", "ness", "ment",
    "tion", "sion", "ive", "ity", "ize", "ise", "ful", "less", "ally", "al",
)


def stem_candidates(word):
    """
    列出一个英文单词的几种可能词干。

    只做很粗的处理，目的很单一：容忍语音识别把原形听成变形。
    qualify / qualified / qualifying 应该被归到同一组。

    还处理两种常见拼写变化：
      - y ↔ i：qualified 去掉 ed 得到 qualifi，再补回 y 才是 qualify
      - 加 e：retrieving 去掉 ing 得到 retriev，补回 e 才是 retrieve

    词干至少要有 3 个字母，避免 short 这样的词被砍成两三个字母后到处乱撞。
    """
    out = {word}
    for suffix in _EN_SUFFIXES:
        if not (word.endswith(suffix) and len(word) - len(suffix) >= 3):
            continue
        base = word[: -len(suffix)]
        out.add(base)
        out.add(base + "e")
        if base.endswith("i"):
            out.add(base[:-1] + "y")
        if len(base) > 2 and base[-1] == base[-2]:
            out.add(base[:-1])
    return out

# 序号里「最后一个」的表示
ORDINAL_LAST = -1

# 中文数字。只支持到十，选择题不会更多了。
_CN_NUMERALS = {
    "一": 1, "两": 2, "二": 2, "三": 3, "四": 4, "五": 5,
    "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
}

# 说序号时可能带上的动词 / 量词，解析前先剥掉
_ORDINAL_PREFIXES = ("我选第", "我选", "我要选", "我要", "选择", "选第", "选", "挑", "要", "点")
_ORDINAL_TOKENS = ("第", "个", "选项", "项", "条", "号")


def parse_ordinal(spoken):
    """
    把「1」「一」「第一个」「选三」「最后一个」这类说法解析成选项序号。

    返回 1 开始的序号，或 ORDINAL_LAST 表示「最后一个」，或 None 表示这不是序号说法。

    这个功能的意义：生僻词 ASR 容易听错，但「1、2、3」几乎不可能听错。
    遇到拼不出来的选项，直接说序号最稳。
    """
    key = normalize(spoken)
    if not key:
        return None

    # 「最后一个」要先判，因为下面的剥词会把「个」去掉
    if key in ("最后一个", "最后", "最末一个", "最末"):
        return ORDINAL_LAST

    for prefix in _ORDINAL_PREFIXES:
        if key.startswith(prefix):
            key = key[len(prefix):]
            break

    for token in _ORDINAL_TOKENS:
        key = key.replace(token, "")

    if not key:
        return None

    if key.isdigit():
        value = int(key)
        return value if 1 <= value <= 99 else None

    if key in _CN_NUMERALS:
        return _CN_NUMERALS[key]

    return None


# 控制语：说这些话不是要选某个选项，而是要程序做一件事。
# 目前只有「下一题」一种 —— 答错进详情页后用它继续。
#
# 判定用「包含」而不是「相等」：ASR 常在前后带上零碎字词
# （「说下一题」「下一题吧」），只要里面出现了这个词，就是那个意思。
NEXT_PHRASES = (
    "下一题", "下一词", "下一首", "下一个", "下一组", "下一关",
    "继续", "next",
)


def detect_control(text):
    """
    看一眼识别出的文字里有没有控制语。

    返回 "next" 表示「去点下一题」，没有则返回 None。
    必须**优先于**选项匹配调用 —— 否则「下一题」会被拿去和选项比对。
    """
    key = normalize(text)
    if not key:
        return None
    for phrase in NEXT_PHRASES:
        if normalize(phrase) in key:
            return "next"
    return None


@dataclass
class Candidate:
    node: object
    level: int
    score: float          # 越大越"专一"，用于多候选取舍


@dataclass
class MatchResult:
    node: object = None
    level: int = LEVEL_NONE
    candidates: list = field(default_factory=list)
    spoken: str = ""
    ambiguous: bool = False
    # 序号相关的附加信息
    by_ordinal: bool = False
    ordinal_index: int = 0            # 命中时是几号（1 开始）
    ordinal_out_of_range: int = 0     # 说了序号但超出选项数量时记在这里

    @property
    def level_name(self):
        return LEVEL_NAMES.get(self.level, "未匹配")

    @property
    def ok(self):
        return self.node is not None


def _coverage(spoken_key: str, option_key: str) -> float:
    """
    你说的话占选项文字的比例。比例越高，说明这个匹配越"专一"。
    说「的」命中「清晰易懂的」覆盖率高得离谱其实是假的，但那种情况会被
    最小长度门槛先挡掉。
    """
    if not option_key:
        return 0.0
    return len(spoken_key) / len(option_key)


def match(spoken: str, options, cfg=None, allow_ordinal: bool = True) -> MatchResult:
    """
    把 spoken 匹配到 options 里的某一项。

    options 是 screen.Node 的列表（只要有 .text 属性即可）。
    cfg 需要 match.MinSubstring 相关字段，传 None 用默认值。

    allow_ordinal=False 时**不走「说序号」那条路**（「1」「第二个」不再按
    序号命中，会照常落回下面的文字匹配）。这是给 `voice.commands` 开关用的：
    序号说法太容易被环境杂音误触发（真机日志里有过一次杂音说「第一个」就点了一下）。
    **默认 True，老调用方的行为不变。**
    """
    result = MatchResult(spoken=spoken)

    min_len = getattr(cfg, "min_substring_length", 2) if cfg else 2
    fuzzy_on = getattr(cfg, "fuzzy_enabled", True) if cfg else True
    pinyin_on = getattr(cfg, "pinyin_enabled", True) if cfg else True
    max_distance = getattr(cfg, "max_distance", 1) if cfg else 1

    spoken_key = normalize(spoken)
    if not spoken_key:
        return result

    spoken_pinyin = to_pinyin(spoken_key) if pinyin_on else ""

    # 长度门槛：防止「的」这种超短片段同时命中一大片选项。
    #
    # 但纯数字要例外 —— 数字是个具体记号，不是常见字，而且选项里出现数字
    # 往往就是它的本意（「第 3 项」之类）。没有这个例外的话，
    # 「说了超出范围的序号，落回文字匹配」这条退路就走不通了。
    spoken_len_ok = len(spoken_key) >= min_len or spoken_key.isdigit()

    # 预先把选项归一化好，避免重复计算
    prepared = []
    for node in options:
        text = getattr(node, "text", "") or ""
        key = normalize(text)
        if not key:
            continue
        prepared.append({
            "node": node,
            "text": text,
            "key": key,
            "pinyin": to_pinyin(key) if pinyin_on else "",
        })

    if not prepared:
        return result

    # --- 序号优先。
    # 「1」「第一个」是最明确的意图，比任何文字匹配都可信，所以放在最前面。
    # 但如果说的序号超出了选项数量，就落下去继续试文字匹配
    # （万一选项文字里真有个数字），最后再把「超出范围」这件事报给上层。
    #
    # 整段由 allow_ordinal 控制：关掉时**整个跳过**（连「超出范围」都不记），
    # 直接落回下面的文字匹配 —— 也就是「1」被当成普通文字处理。
    if allow_ordinal:
        ordinal = parse_ordinal(spoken)
        if ordinal is not None:
            index = len(prepared) if ordinal == ORDINAL_LAST else ordinal
            if 1 <= index <= len(prepared):
                node = prepared[index - 1]["node"]
                result.node = node
                result.level = LEVEL_ORDINAL
                result.candidates = [node]
                result.by_ordinal = True
                result.ordinal_index = index
                return result
            result.ordinal_out_of_range = ordinal

    buckets = {level: [] for level in
               (LEVEL_EXACT, LEVEL_SUBSTRING, LEVEL_CONTAINS,
                LEVEL_STEM, LEVEL_PINYIN, LEVEL_FUZZY)}
    spoken_stems = stem_candidates(spoken_key)

    for item in prepared:
        key = item["key"]

        # --- 1 精确
        if key == spoken_key:
            buckets[LEVEL_EXACT].append(Candidate(item["node"], LEVEL_EXACT, 1.0))
            continue

        # --- 2 选项里包含你说的话（主力路径）
        if spoken_len_ok and spoken_key in key:
            buckets[LEVEL_SUBSTRING].append(
                Candidate(item["node"], LEVEL_SUBSTRING, _coverage(spoken_key, key)))
            continue

        # --- 3 你说的话里包含整个选项
        #     用户有时会把选项完整念一遍，前面还带"我选…"之类
        if len(key) >= min_len and key in spoken_key:
            buckets[LEVEL_CONTAINS].append(
                Candidate(item["node"], LEVEL_CONTAINS, _coverage(key, spoken_key)))
            continue

        # --- 3.5 英语词形（原形 vs 变形）
        if spoken_len_ok and spoken_stems & stem_candidates(key):
            buckets[LEVEL_STEM].append(
                Candidate(item["node"], LEVEL_STEM, _coverage(spoken_key, key)))
            continue

        # --- 4 拼音子串（同音字容错）
        if pinyin_on and spoken_len_ok and spoken_pinyin and item["pinyin"]:
            if spoken_pinyin in item["pinyin"]:
                buckets[LEVEL_PINYIN].append(
                    Candidate(item["node"], LEVEL_PINYIN, _coverage(spoken_pinyin, item["pinyin"])))
                continue

        # --- 5 模糊（编辑距离）
        if fuzzy_on and spoken_len_ok and len(spoken_key) >= 3:
            distance = best_window_distance(spoken_key, key, max_distance)
            if distance <= max_distance:
                # 距离越小、选项越短越可信
                score = (max_distance + 1 - distance) / max(len(key), 1)
                buckets[LEVEL_FUZZY].append(Candidate(item["node"], LEVEL_FUZZY, score))
                continue

    # 按级别从可信到宽松取第一个非空的分组
    for level in (LEVEL_EXACT, LEVEL_SUBSTRING, LEVEL_CONTAINS,
                  LEVEL_STEM, LEVEL_PINYIN, LEVEL_FUZZY):
        items = buckets[level]
        if not items:
            continue

        # 同一级别里多个候选：取最"专一"的；再平手就取屏幕顺序靠前的
        items.sort(key=lambda c: (-c.score, c.node.y))
        best = items[0]

        result.node = best.node
        result.level = level
        result.candidates = [c.node for c in items]
        result.ambiguous = len(items) > 1
        return result

    result.candidates = []
    return result

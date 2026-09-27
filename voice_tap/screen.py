#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""

screen.py —— 把无障碍树 XML 变成「屏幕上有哪些可点的文字」

核心是一个针对 GRE3000 的提取器，依据是实测得到的、跨多次运行稳定的结构：

    tv_word         题干（可能是英文单词，也可能是一段英文释义）
    tv_question     每一个选项（4 个释义/单词 + 一个「不记得了」）
    tv_title        进度，如 "101 / 200"
    tv_question_type 题型标签，如 "阅读：据词选中义"

两个关键设计：

1. **候选项只取 tv_question，绝不包含 tv_word。** 题干里出现的词可能和某个选项
   完全相同（英文释义里含选项单词是常见的），靠 resource-id 一排除，这个坑就没了。

2. **前台应用护栏。** 只有确认当前在 GRE3000 答题界面时才允许点击。
   声控工具是"盲点"的 —— 用户看不见程序看到了什么。如果手机停在 QQ 上，
   把会话列表当成选项去点，后果不可预期。这道校验成本极低，但能杜绝一整类事故。
"""
from __future__ import annotations  # 让 int | None 这类写法在 Python 3.9 上也能用

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

# GRE3000 的标识（实测得出，多次运行完全一致）
GRE_PACKAGE = "com.enhance.greapp"
ID_PROMPT = "com.enhance.greapp:id/tv_word"
ID_OPTION = "com.enhance.greapp:id/tv_question"

# 至少要有这么多选项，才认为确实停在答题界面
MIN_OPTIONS = 2

# 答错或点「不记得了」之后会进详情页，需要点这个按钮才能继续。
#
# 2026-09-26 实测确认：GRE3000 上这个按钮的文字就是「下一题」，坐标 (909, 2476)。
# 其余的写法是留给其它页面/其它 App 的保险 —— 文字匹配比 resource-id 稳，
# 因为那个 id 至今没实测到。
NEXT_BUTTON_TEXTS = (
    "下一题", "下一词", "下一个", "下一组", "下一关",
    "继续", "继续学习", "下一个单词", "next",
)

# 页面类型
PAGE_QUIZ = "quiz"       # 答题页：有题干和选项
PAGE_DETAIL = "detail"   # 详情页：答完题后看释义的那一屏
PAGE_OTHER = "other"     # GRE3000 的其他页面，或者根本不是 GRE3000

BOUNDS_RE = re.compile(r"\[(-?\d+),(-?\d+)\]\[(-?\d+),(-?\d+)\]")


@dataclass
class Node:
    """屏幕上的一段文字，以及该点哪里才能点中它"""
    text: str
    x: int
    y: int
    clickable: bool                       # 自身或祖先可点击
    resource_id: str = ""
    class_name: str = ""
    bounds: tuple | None = None
    ancestor_hops: int = -1               # -1 表示回溯不到可点击祖先
    source: str = "uiautomator"

    def __str__(self):
        return f"{self.text!r}@({self.x},{self.y})"


@dataclass
class ScreenSnapshot:
    """一次抓屏的完整结果"""
    foreground_package: str = ""
    prompt: str = ""                      # 题干原文，仅供展示，不参与匹配
    options: list = field(default_factory=list)     # 候选选项（Node 列表）
    all_text_nodes: list = field(default_factory=list)   # 屏幕上所有文字，报错时列给用户看
    ok: bool = False                      # 是否处于「可以安全点击选项」的界面
    reason: str = ""                      # ok 为 False 时说明原因
    page: str = PAGE_OTHER                # quiz / detail / other
    next_button: object = None            # 详情页上的「下一题」按钮（Node）

    def option_texts(self):
        return [n.text for n in self.options]


def parse_bounds(text):
    """把 "[x1,y1][x2,y2]" 解析成 (x1, y1, x2, y2)"""
    if not text:
        return None
    m = BOUNDS_RE.search(text)
    return tuple(int(g) for g in m.groups()) if m else None


def center_of(bounds):
    if not bounds:
        return None
    x1, y1, x2, y2 = bounds
    return ((x1 + x2) // 2, (y1 + y2) // 2)


def point_in(point, bounds):
    if not point or not bounds:
        return False
    x, y = point
    x1, y1, x2, y2 = bounds
    return x1 <= x <= x2 and y1 <= y <= y2


def build_parent_map(root):
    parents = {}
    stack = [root]
    while stack:
        cur = stack.pop()
        for child in list(cur):
            parents[id(child)] = cur
            stack.append(child)
    return parents


def find_clickable_ancestor(node, parents):
    """向上找最近的可点击祖先，返回 (节点, 上溯层数)；找不到返回 (None, -1)"""
    cur, hops = node, 0
    while cur is not None:
        if cur.get("clickable") == "true":
            return cur, hops
        cur = parents.get(id(cur))
        hops += 1
    return None, -1


def resolve_click_point(text_bounds, ancestor_bounds):
    """
    决定点哪里。

    优先用文字自己的中心 —— 只要它落在可点击祖先范围内就足够精确。
    只有文字中心不在可点范围内（少见）才退回祖先中心，
    避免「大容器套小图标」时点到容器正中、离目标很远。
    """
    text_center = center_of(text_bounds)
    ancestor_center = center_of(ancestor_bounds)

    if text_center and ancestor_bounds and point_in(text_center, ancestor_bounds):
        return text_center
    if ancestor_center:
        return ancestor_center
    return text_center


def collect_text_nodes(root):
    """按文档顺序摊平所有带文字的节点，每个都附带「该点哪里」"""
    parents = build_parent_map(root)
    result = []

    def visit(cur):
        for child in list(cur):
            text = (child.get("text") or "").strip()
            desc = (child.get("content-desc") or "").strip()
            label = text or desc

            if label:
                bounds = parse_bounds(child.get("bounds"))
                anc, hops = find_clickable_ancestor(child, parents)
                anc_bounds = parse_bounds(anc.get("bounds")) if anc is not None else None
                point = (resolve_click_point(bounds, anc_bounds)
                         if anc is not None else center_of(bounds))

                if point:
                    result.append(Node(
                        text=label,
                        x=point[0],
                        y=point[1],
                        clickable=anc is not None,
                        resource_id=child.get("resource-id", ""),
                        class_name=child.get("class", ""),
                        bounds=bounds,
                        ancestor_hops=hops if anc is not None else -1,
                    ))
            visit(child)

    visit(root)
    return result


def foreground_package(root):
    """
    取前台应用包名。
    <hierarchy> 本身没有 package 属性，往下找第一个有值的节点。
    """
    value = root.get("package")
    if value:
        return value
    for node in root.iter():
        value = node.get("package")
        if value:
            return value
    return ""


def _plain(text):
    """去掉空白并转小写，用来比对按钮文字"""
    return re.sub(r"\s+", "", str(text or "")).lower()


def is_next_button_text(text):
    """这段文字看起来像不像「下一题」按钮"""
    key = _plain(text)
    if not key:
        return False
    return any(_plain(t) in key for t in NEXT_BUTTON_TEXTS)


def find_next_button(nodes):
    """
    在屏幕上的文字里找「下一题」这类按钮。

    优先取可点击的，其次取最靠下的（这个按钮一般在页面底部）。
    找不到返回 None —— 调用方应该放弃，而不是猜一个位置。
    """
    hits = [n for n in nodes if is_next_button_text(n.text)]
    if not hits:
        return None
    hits.sort(key=lambda n: (not n.clickable, -n.y))
    return hits[0]


def read_screen(xml_text, expected_package=GRE_PACKAGE):
    """
    解析无障碍树，返回 ScreenSnapshot。

    expected_package 传 None 表示不校验前台应用（仅用于诊断/预览）。
    """
    snapshot = ScreenSnapshot()

    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        snapshot.reason = f"无障碍树 XML 解析失败：{exc}"
        return snapshot

    snapshot.foreground_package = foreground_package(root)
    snapshot.all_text_nodes = collect_text_nodes(root)

    # --- 护栏一：前台应用对不对
    if expected_package and snapshot.foreground_package != expected_package:
        snapshot.page = PAGE_OTHER
        snapshot.reason = (
            f"当前不在 GRE3000 答题界面（检测到的是 {snapshot.foreground_package or '未知应用'}），"
            "请先把手机切回 GRE3000"
        )
        return snapshot

    # --- 提取题干与选项
    prompt_nodes = [n for n in snapshot.all_text_nodes if n.resource_id == ID_PROMPT]
    option_nodes = [n for n in snapshot.all_text_nodes if n.resource_id == ID_OPTION]

    if prompt_nodes:
        # 题干可能有多个节点（长释义会拆行），拼起来
        snapshot.prompt = " ".join(n.text for n in prompt_nodes)

    # 按屏幕从上到下排序，保证「第一个选项」的语义稳定
    option_nodes.sort(key=lambda n: n.y)
    snapshot.options = option_nodes

    # --- 护栏二：确实有选项
    if len(option_nodes) < MIN_OPTIONS:
        # 没有选项不一定是出错 —— 答完题会进详情页，那里有「下一题」按钮
        snapshot.next_button = find_next_button(snapshot.all_text_nodes)
        if snapshot.next_button is not None:
            snapshot.page = PAGE_DETAIL
            snapshot.reason = "当前是答题后的详情页（没有选项），可以点「下一题」继续"
        else:
            snapshot.page = PAGE_OTHER
            snapshot.reason = (
                f"GRE3000 是打开的，但当前界面上只有 {len(option_nodes)} 个选项，"
                "也没有找到「下一题」按钮，可能停在首页或成绩页"
            )
        return snapshot

    snapshot.page = PAGE_QUIZ
    snapshot.next_button = find_next_button(snapshot.all_text_nodes)
    snapshot.ok = True
    return snapshot

def guess_language(snapshot):
    """
    从屏幕内容猜用户可能说的是哪种语言。

    原理：用户说的是**选项里的词**。所以看一眼选项是什么文字，
    就知道该按中文还是英文去识别 —— 比让模型自己猜靠谱得多。

    背景：实测发现识别模型在只有半秒的短音频上，语言判断经常出错
    （把英文判成法语、意大利语），一判错整句就全错。而屏幕上的文字
    是我们已经拿到手的、确定的信息。

    返回 'zh' / 'en' / None（判不出来就让模型自己决定）。
    """
    texts = [n.text for n in getattr(snapshot, "options", [])]
    if not texts:
        return None

    cjk = sum(1 for t in texts for ch in t if "\u4e00" <= ch <= "\u9fff")
    latin = sum(1 for t in texts for ch in t if ch.isascii() and ch.isalpha())

    if cjk == 0 and latin == 0:
        return None
    if cjk > latin:
        return "zh"
    if latin > cjk:
        return "en"
    return None


def option_hint(snapshot, limit=8):
    """
    把选项拼成一句短提示，喂给识别模型当上下文。

    这是整个识别环节里最有效的一招：模型本来要在一整本词典里找出你说了哪个词，
    而屏幕上就摆着 5 个候选。告诉它「大概是这几个之一」，准确率会明显不一样。

    返回短横线分隔的选项文字；没有选项返回 None。
    """
    texts = [n.text.strip() for n in getattr(snapshot, "options", []) if n.text.strip()]
    if not texts:
        return None
    picked = texts[:limit]
    return "、".join(picked) if any("\u4e00" <= ch <= "\u9fff" for t in picked for ch in t) \
        else ", ".join(picked)

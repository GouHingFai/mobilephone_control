#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
main.py —— 声控手机助手主程序

把各个模块装配起来，跑一个「听 → 看 → 匹配 → 点」的循环。

两种模式：
    listen   常驻监听。检测到你说话就自动切句、识别、点击。适合连打。
    hotkey   按住 F8 说话，松开就点。适合环境吵或者怕误触。
运行中按 F9 随时切换。

调试手段：
    --dump     只抓一次屏幕并打印解析结果，不识别也不点击
    --once     只说一句就退出
    --preview  不真点，把要点的位置画红圈存图
"""

import argparse
import queue
import sys
import threading
import time
import traceback
from pathlib import Path

from . import matcher, screen
from .adb import Adb, AdbError
from .asr import AsrError, Recognizer
from .clicker import Clicker
from .config import load_config
from .hotkey import HotkeyManager
from .voice_gate import VoiceGate

# 所有输出同时写一份到文件。
# 主程序是长时间运行、实时刷屏的，窗口一关就什么都没了 ——
# 出问题时能翻日志是排查的前提。probe.py 一直是这么做的，主程序也该如此。
_LOG_HANDLE = None


def open_log(path):
    global _LOG_HANDLE
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        _LOG_HANDLE = open(path, "w", encoding="utf-8", buffering=1)
    except Exception:  # noqa: BLE001
        _LOG_HANDLE = None
    return _LOG_HANDLE


def say(msg=""):
    print(msg, flush=True)
    if _LOG_HANDLE is not None:
        try:
            _LOG_HANDLE.write(str(msg) + "\n")
            _LOG_HANDLE.flush()
        except Exception:  # noqa: BLE001
            pass


def log_exception():
    """把未捕获的异常也写进日志，否则窗口一关就查不到原因了"""
    text = traceback.format_exc()
    print(text, flush=True)
    if _LOG_HANDLE is not None:
        try:
            _LOG_HANDLE.write(text + "\n")
            _LOG_HANDLE.flush()
        except Exception:  # noqa: BLE001
            pass


def section(title):
    say()
    say("=" * 66)
    say("  " + title)
    say("=" * 66)


# ---------------------------------------------------------------- 界面预抓取

class ScreenPrefetcher:
    """
    在后台提前把界面读好，等你需要时立刻就能用。

    两个触发时机，各自独立开关（见 config.yaml）：

    **点击之后**（开着 —— 这是提速的核心）
        点下去之后 App 会翻页。翻页那一小段时间程序是空闲的，正好拿来读界面。
        读到之后：
          - 答对了 → 缓存里就是下一题的选项，你开口时直接用
          - 答错了 → 缓存里是详情页，你按「下一题」时直接用

    **检测到你开口时**（关着）
        说话要花一两秒，也能拿来读界面。但如果读屏比说话还慢，这次预读就白做了。

    关于「翻页有没有发生」的判断 —— 这是本模块最要紧的地方：

        不能等一个固定时间就认为翻好了。读得太早拿到的还是上一题的界面，
        然后就会**拿着旧坐标去点新题目** —— 点了、不报错、但点的是错的地方。
        这正是之前那套「固定坐标」方案栽的跟头。

        所以这里读一次就拿指纹和点击前比一次：不一样了才算数；一样就再等等再读。
        每次读屏的耗时都记进日志，方便调等待时长。

    工作方式（点击后预读开着时）：

        按数字键 → 用上一次预读好的坐标点 → 点完立刻读下一屏 → 下次直接可用

    **按数字键时不会重新读屏**。用户通过 scrcpy 看着屏幕操作，界面状态他自己清楚，
    不需要程序每次再确认一遍。只有预读没做成时才兜底当场读一次（日志会明说）。

    如果你自己用鼠标动了界面，按小键盘的「.」强制重新读一次。
    """

    def __init__(self, adb, cfg, log=say):
        self.adb = adb
        self.cfg = cfg.prefetch
        self.log = log
        self._lock = threading.Lock()
        self._snapshot = None       # 缓存的界面
        self._at = 0.0              # 它是什么时候读到的
        self._signature = None      # 最近一次见过的界面指纹（用来判断翻页）
        self._last_seen = None      # 最近见过的界面（不消费，给识别当上下文用）
        self._busy = False
        self._miss = "还没有预读结果"  # 上次 take 落空的原因

    # ---------------------------------------------------------- 指纹

    @staticmethod
    def signature(snap):
        """
        给一份界面算个指纹。

        用「前台应用 + 题干 + 所有选项文字」三样东西拼起来 ——
        只要翻了页，这三样里至少有一个会变。
        """
        return (
            snap.foreground_package,
            snap.prompt,
            tuple(n.text for n in snap.options),
        )

    # ---------------------------------------------------------- 缓存

    def note(self, snap, read_at=None):
        """
        记下一次读屏的结果：既当缓存，也更新指纹。

        `read_at` 是这次读屏**开始**的时刻，不是调用本函数的时刻 ——
        界面反映的是那一刻（或稍后）的样子。这个区别很关键：
        一次很慢的后台读，返回时调用时刻反而更晚，如果拿调用时刻比较，
        它会覆盖掉中间读到的更新数据。**要按开始读的时刻比，才不会拿旧的盖新的。**
        """
        read_at = time.monotonic() if read_at is None else read_at
        with self._lock:
            if self._at and read_at < self._at:
                return          # 这次读得比手上这份还早，丢弃
            self._snapshot = snap
            self._at = read_at
            self._signature = self.signature(snap)
            self._last_seen = snap

    def take(self):
        """
        取缓存的界面。返回 (快照, 距读到的秒数)；没有可用的返回 None。

        **取用但不删除** —— 这一点是踩坑之后改的。

        原来写的是「取走即清空」，怕的是同一份数据被反复用、过期了还在用。
        但那个担心是多余的：过期已经有三道机制管着（cache_max_age、
        点击后的 invalidate、前台应用护栏）。而「取走即清空」的唯一实际效果是：

            用语音答 → 听错 → 没匹配上 → **那次取用把有效数据烧掉了**
                     → 重说一遍 → 缓存空了 → 只能当场读屏（白等 2.4 秒）

        而重说的时候**恰恰最需要**这份数据 —— 界面根本没变过，
        因为压根没有点击发生。所以现在改成不清空，让同一份界面能被子
        反复使用，直到它真的过期、或者被点击作废。
        """
        with self._lock:
            if self._snapshot is None:
                # **不要在这里改 _miss。** 它记着「这份缓存是怎么没的」——
                # 可能仍是「还没有预读结果」，也可能是 invalidate() 留下的
                # 「刚点击过，缓存已作废」，或上一次过期时写下的「过期了」。
                # 用一句笼统的「还没有」把它盖掉，就正好丢掉了我们要查的线索。
                return None
            age = time.monotonic() - self._at
            if age > self.cfg.cache_max_age:
                self._snapshot = None
                self._miss = (f"预读结果过期了：{age:.1f} 秒前读的，"
                              f"超过上限 {self.cfg.cache_max_age:.0f} 秒")
                return None
            return self._snapshot, age

    def miss_reason(self):
        """
        上一次 take 为什么没取到东西。

        加这个是为了查一个孤例：日志里有过一次「刚预读成功，紧接着就说没有缓存」，
        但 24 次里只出现 1 次。光看日志分不清是「压根没有」还是「过期了」，
        所以让 take 把原因记下来，由调用方打出去。

        可能的说法有三种，都由 take()/invalidate() 在缓存变空的当下写下，
        不会被后来的 take 改写：
            「还没有预读结果」   —— 压根没预读过（或一直没成功）
            「预读结果过期了…」   —— 读到了，但超过 cache_max_age
            「刚点击过，缓存已作废…」—— 点击后主动作废，新的一屏还在读
        """
        with self._lock:
            return self._miss

    def identity(self):
        """
        最近见过那一屏的指纹；还没读到过任何界面时返回 None。

        用途是给按键动作盖章：按下的那一刻记下「当时屏幕长什么样」，
        真正执行前再比一次 —— 不一样，就说明中间翻了页，这一下不能点。
        （参见 handle_numpad 的 stamp 参数与 tests 里的 TestActionStamp。）
        """
        with self._lock:
            if self._last_seen is None:
                return None
            return self.signature(self._last_seen)

    def take_or_wait(self, timeout=8.0):
        """
        取缓存；如果正好有一次预读在跑，**先等它跑完再取**。

        为什么要等而不是直接自己读一次：不等的话就会出现两个 `uiautomator dump`
        同时对同一台手机下命令 —— 实测里单次读屏耗时因此从稳定的 2.4 秒
        涨到过 8.5 秒。等它跑完只花不到一秒，比两边都变慢划算得多。
        """
        deadline = time.monotonic() + timeout
        while True:
            got = self.take()
            if got is not None:
                return got
            with self._lock:
                busy = self._busy
            if not busy or time.monotonic() >= deadline:
                return None
            time.sleep(0.05)

    def invalidate(self):
        """
        作废缓存。

        注意**不动指纹** —— 点击之后马上要拿它和读到的界面比对，
        判断翻页到底发生没有。指纹就是"点击之前长什么样"。
        也**不动 _last_seen** —— 它是"最近见过的界面"，给识别当上下文用，
        翻页判断和识别提示都靠它。
        """
        with self._lock:
            self._snapshot = None
            self._at = 0.0
            self._miss = "刚点击过，缓存已作废（界面要翻页了）"

    def peek(self):
        """
        看一眼最近见过的界面，**不消费**。

        语音识别要用它做两件事：
          1. 从选项文字判断该按中文还是英文识别
          2. 把选项当作提示词喂给识别模型
        这两个都是"知道了会准很多"的信息，而屏幕上的文字是我们手里现成的。
        """
        with self._lock:
            return self._last_seen

    # ---------------------------------------------------------- 触发

    def trigger_on_speech(self):
        """检测到你开口时预读。默认关着，可以在 config.yaml 里打开。"""
        if not self.cfg.on_speech:
            return

        with self._lock:
            if self._busy:
                return
            self._busy = True

        def work():
            read_start = time.monotonic()
            try:
                snap = screen.read_screen(self.adb.dump_ui())
                self.note(snap, read_at=read_start)
            except Exception:  # noqa: BLE001
                pass
            finally:
                with self._lock:
                    self._busy = False

        threading.Thread(target=work, daemon=True, name="prefetch-on-speech").start()

    def trigger_after_click(self):
        """点击之后预读，直到读到和点击前不一样的界面为止"""
        if not self.cfg.after_click:
            return

        with self._lock:
            if self._busy:
                return
            self._busy = True
            before = self._signature

        def work():
            attempts = max(1, self.cfg.click_max_attempts)
            delay = self.cfg.click_delay_ms / 1000.0
            retry = self.cfg.click_retry_ms / 1000.0
            started = time.monotonic()
            note = ""
            try:
                for attempt in range(1, attempts + 1):
                    time.sleep(delay if attempt == 1 else retry)

                    read_start = time.monotonic()
                    try:
                        snap = screen.read_screen(self.adb.dump_ui())
                    except Exception as exc:  # noqa: BLE001
                        note = f"读屏失败（{type(exc).__name__}）"
                        continue
                    read_ms = (time.monotonic() - read_start) * 1000
                    elapsed = (time.monotonic() - started) * 1000

                    if before is None or self.signature(snap) != before:
                        self.note(snap, read_at=read_start)
                        self.log(f"       [预读] 第 {attempt} 次读到新界面，"
                                 f"距点击 {elapsed:.0f} 毫秒（本次读屏 {read_ms:.0f} 毫秒）")
                        return

                    self.log(f"       [预读] 第 {attempt} 次还是旧界面，"
                             f"距点击 {elapsed:.0f} 毫秒（本次读屏 {read_ms:.0f} 毫秒），再等等")

                self.log(f"       [预读] 试了 {attempts} 次都没读到变化，放弃"
                         + (f"（{note}）" if note else ""))
            finally:
                with self._lock:
                    self._busy = False

        threading.Thread(target=work, daemon=True, name="prefetch-after-click").start()


# ---------------------------------------------------------------- 动作队列接线
#
# 「按下一个键」到「真的执行这个动作」中间隔着一条流水线：
#
#     热键回调（按键那一刻）→ 盖戳 → 入队 → 工作线程解包 → 分派 → 处理函数
#
# 这条线以前是写在 main() 的三个 lambda 和一个闭包里的，外部调不到 ——
# 于是谁把 `("numpad", n, 戳)` 写成两元组、或者把解包写反，测试也照绿，
# 而真机上就是那个「连按两下点到新题」的老毛病。抽成模块级函数就是为了能钉住它。


def make_action_putters(queue, prefetcher):
    """
    造三个「把动作塞进队列」的回调，供热键注册使用。

    **盖戳的时机就在这儿**：回调跑在按键那一刻，所以这时候取 `prefetcher.identity()`，
    拿到的就是「按下时屏幕上是什么」。这个戳一路带到工作线程，执行前用来核对。

    返回一个字典（键就是热键管理器要的回调名），免得靠位置记顺序：

        on_option(n)     —— 点第 n 个选项，带戳
        on_next()        —— 点「下一题」，带戳
        on_force_read()  —— 强制读屏，**不带戳**（它跟界面无关，只是重新同步）
    """
    def on_option(n):
        queue.put(("numpad", n, prefetcher.identity()))

    def on_next():
        queue.put(("next", None, prefetcher.identity()))

    def on_force_read():
        # 强制读屏的目的就是把程序手里那份旧界面丢掉重读，
        # 所以它跟「按下时是哪一屏」无关，不盖章。
        queue.put(("force_read", None, None))

    return {
        "on_option": on_option,
        "on_next": on_next,
        "on_force_read": on_force_read,
    }


def dispatch_action(action, ctx):
    """
    执行一个动作队列条目。解包 `(kind, value, stamp)` 后按 kind 分派。

    做成独立函数（而不是塞在工作线程的闭包里），是为了能单测 ——
    这段「格式对不对、有没有分派错」是最容易悄悄坏掉的地方。

    分派表就写在下面这几行。将来加新动作（比如语音意图、退出），
    在这儿加一个 elif 即可；**认不出来的 kind 一律当没看见** ——
    宁可什么都不做，也不能把不认识的东西当成「点一下」扔出去。
    """
    try:
        kind, value, stamp = action
    except (TypeError, ValueError):
        # 格式不对（不是长度 3 的可解包对象）：直接忽略，不抛异常。
        # 这是工作线程的最后一道关口 —— 半截元组、None、一个数字之类的东西
        # 不该把线程掀翻，更不该冒出一个「点一下」的副作用。
        return

    if kind == "numpad":
        handle_numpad(value, ctx, stamp=stamp)
    elif kind == "next":
        handle_next(ctx)
    elif kind == "force_read":
        handle_force_read(ctx)
    elif kind == "intent":
        # 界面按钮的动作。唤醒事件从 ctx 里取，不必给本函数加参数。
        handle_intent(value, ctx, ctx.get("wake_event"))
    elif kind == "quit":
        ctx["hotkeys"].quit_requested.set()


# ---------------------------------------------------------------- 主流程

def show_screen(snap, log=say):
    """把当前屏幕状态打印出来，出错时尤其有用"""
    if snap.prompt:
        log(f"[屏幕] 题干：{snap.prompt}")
    if snap.options:
        log(f"[屏幕] 选项：{' / '.join(snap.option_texts())}")
    else:
        texts = [n.text for n in snap.all_text_nodes][:20]
        if texts:
            log(f"[屏幕] 当前屏幕上的文字（前 20 个）：{' / '.join(texts)}")


def grab_screen(ctx, use_prefetch=True):
    """
    取当前屏幕并解析。返回 (快照, 来源说明)。

    来源说明会打进日志 —— 调试优化时得能一眼看出这次到底读没读屏。
    """
    prefetcher = ctx["prefetcher"]

    if use_prefetch:
        cached = prefetcher.take_or_wait()
        if cached is not None:
            snap, age = cached
            return snap, f"预读，{age:.1f} 秒前读好的（没读屏）"

    # 走到这里说明没有可用的预读结果（预读没做成 / 超时了 / 这是第一次操作）。
    # 只能当场读一次 —— 但这是**兜底**，正常流程不该走到这里。
    read_start = time.monotonic()
    xml = ctx["adb"].dump_ui()
    read_ms = (time.monotonic() - read_start) * 1000
    snap = screen.read_screen(xml)
    prefetcher.note(snap, read_at=read_start)
    say(f"       [注意] 没有可用的预读结果（{prefetcher.miss_reason()}），"
        f"当场读了一次（{read_ms:.0f} 毫秒）")
    return snap, f"当场读屏 {read_ms:.0f} 毫秒（{len(xml) // 1024} KB）"


def probe_startup_screen(adb, prefetcher, log=say):
    """
    启动时读一次界面，并**把它存进预读缓存**。

    读这一次有两个用处：打个招呼（告诉你现在是不是停在答题界面），
    以及把这一屏交给预读器 —— 否则你启动后的**第一次操作**（第一句语音、
    第一个数字键）会因为缓存是空的而当场读屏，白等约 2.4 秒。
    这是每开一次程序都会碰到的空窗，所以值得特意存一下。

    存下来还顺带补上一个漏洞：把这一屏当基准，「第一次点击之后的翻页检测」
    才有东西可比。否则第一次点击没有基准，读到什么都无法判断新旧 —
    可能把点击**前**的界面当成翻页结果。

    读屏失败不致命 —— 返回 None，程序照常起来，只是第一次操作会当场读一次。
    """
    try:
        read_start = time.monotonic()
        xml = adb.dump_ui()
    except AdbError as exc:
        log(f"  [注意] {exc}")
        return None

    snap = screen.read_screen(xml)
    prefetcher.note(snap, read_at=read_start)
    return snap


class _AnyEvent:
    """
    把「任意一个事件被置位」伪装成**单个** Event，喂给监听函数。

    `listen_until_silence()` 只接受一个 stop_event，但我们有两个中断源：
    退出请求、以及「开关变了、快回来看一眼」。它内部只调 `is_set()`，
    所以这么一个小壳子就够了，不必去改音频层。
    """

    def __init__(self, *events):
        self._events = events

    def is_set(self):
        return any(e.is_set() for e in self._events)


def _toggle_flag(ctx, section, key, label):
    """翻一下配置里的某个布尔开关，并打一行日志。界面上那两个开关走这里。"""
    obj = getattr(ctx["cfg"], section)
    setattr(obj, key, not getattr(obj, key))
    say(f"  >>> {label}：{'开' if getattr(obj, key) else '关'}")


def handle_intent(name, ctx, wake_event=None):
    """
    执行一个来自界面的意图。

    真正的动作都在 `ctx["intents"]` 那张表里，而那张表里放的就是热键回调
    本身 —— 所以「界面点」和「按热键」走的是同一份代码。

    执行完唤醒一下监听线程：它多半正阻塞在「等你说话」上，
    不叫醒它，切模式／开关语音就要等到你下次开口才生效。
    """
    action = ctx.get("intents", {}).get(name)
    if action is None:
        return
    try:
        action()
    finally:
        if wake_event is not None:
            wake_event.set()


def do_click(node, ctx, description, key=None):
    """
    所有点击的唯一出口：打日志 → 点 → 作废缓存 → 后台预读下一屏。

    **作废和预读只在真的点下去之后才做。** 被防连点挡掉、或者 preview 模式下
    没有真的点，界面根本没翻，手里那份界面数据还是准的 —— 作废它纯属白干，
    只会让下一次操作多读一次屏。

    key 标识「这次点击是哪个动作」，交给防连点判断。
    小键盘传 ("numpad", 几号)，语音传 None。
    """
    say(f"[匹配] {description} → 点击坐标 ({node.x}, {node.y})")

    clicked = ctx["clicker"].click(node, preview=ctx["preview"], key=key)
    if clicked:
        if not ctx["preview"]:
            say("[点击] 完成")
    else:
        say("[点击] 已跳过")

    if not (clicked and not ctx["preview"]):
        # 这一下没有真的点下去（被防连点挡了，或者 preview 模式）。
        # **界面不会翻，手里那份界面数据仍然是有效的**，作废它只会让下一次
        # 操作白白多读一次屏（约 2.4 秒）。所以这里什么都不做。
        return clicked

    # 点下去那一瞬 App 就要翻页了，手里的界面数据立刻作废，
    # 免得下一句话拿着上一题的选项去匹配。
    ctx["prefetcher"].invalidate()

    # 进入静音期：接下来这一两秒手机会把刚答的单词念出来，
    # 麦克风收到的是它，不是你 —— 别让程序把它当成你在说话。
    ctx["voice_gate"].suppress()

    # 趁翻页的空档，后台把新界面读好 —— 下次要用时就不必等了
    ctx["prefetcher"].trigger_after_click()

    return clicked


def report_unusable_screen(snap):
    """屏幕不能点的时候，把原因和现状说清楚"""
    say(f"[屏幕] {snap.reason}")
    show_screen(snap)


def run_voice_loop(ctx, hotkeys, recognizer, once=False, wake_event=None):
    """
    主循环：听 → 识别 → 点击。

    抽成独立函数，是为了让界面能占主线程（Tkinter 的硬性要求）。
    不带 --gui 时它仍旧跑在主线程，行为与以前完全一致。

    `wake_event` 是界面那边用来「叫醒」它的：监听线程大部分时间阻塞在
    「等你说话」上，界面点了开关得能让它立刻回来看一眼（见 handle_intent）。
    """
    while not hotkeys.quit_requested.is_set():
        if ctx["mode"] == "listen":
            if not ctx["voice_gate"].enabled:
                # 语音关着（按了 F7）—— 不用监听，省得白忙
                time.sleep(0.1)
                continue
            ctx["voice_gate"].wait_until_open(hotkeys.quit_requested)
            if wake_event is not None:
                # 进监听前清零 —— 否则上一次留下的置位会立刻把这次等待打断，变成空转
                wake_event.clear()
            # 两个中断源合成一个：退出请求、以及「开关变了、快回来看一眼」。
            # 音频层每 50 毫秒查一次 is_set()，所以关窗口也能立刻退出。
            stop = (_AnyEvent(hotkeys.quit_requested, wake_event)
                    if wake_event is not None else hotkeys.quit_requested)
            utterance = recognizer.listen_once(
                on_speech_start=ctx["prefetcher"].trigger_on_speech,
                hint_snapshot=ctx["prefetcher"].peek(),
                stop_event=stop,
            )
        else:
            # 等按下 F8；没按下就继续空转
            if not hotkeys.ptt_pressed.wait(0.2):
                continue
            utterance = recognizer.listen_pressed(
                hotkeys.ptt_pressed,
                hint_snapshot=ctx["prefetcher"].peek(),
            )

        if utterance is None:
            continue

        text, logprob = utterance
        if not text.strip():
            continue

        try:
            handle_speech(text, logprob, ctx)
        except AdbError as exc:
            say(f"[!!] {exc}")

        if once:
            say()
            say("  --once 模式，跑完一句就退出。")
            break


def handle_speech(text, logprob, ctx):
    """一句话的完整处理：抓屏 → 匹配 → 点击"""
    say(f"[听到] {text!r}   置信度 {logprob:.2f}")

    timing = ctx["recognizer"].last_timing
    if timing:
        say(f"       （音频 {timing.get('audio_seconds')} 秒，识别耗时 "
            f"{timing.get('transcribe_seconds')} 秒，语言 {timing.get('language')}）")

    if ctx["cfg"].asr.min_confidence < 0 and logprob < ctx["cfg"].asr.min_confidence:
        say("       [注意] 置信度偏低，识别结果可能是错的")

    # 控制语优先，而且要排在取屏幕之前 —— 因为「下一题」走固定坐标，
    # 根本不需要读屏。说了就点，这是用户选的「直给」方式。
    if ctx["cfg"].voice.next_command and matcher.detect_control(text) == "next":
        handle_next(ctx, source="语音")
        return

    try:
        snap, source = grab_screen(ctx)
    except AdbError as exc:
        say(f"[屏幕] {exc}")
        return

    if not snap.ok:
        report_unusable_screen(snap)
        return

    show_screen(snap)
    say(f"       （界面来源：{source}）")

    result = matcher.match(text, snap.options, ctx["cfg"].match)

    if not result.ok:
        if result.ordinal_out_of_range:
            say(f"[匹配] 你说了第 {result.ordinal_out_of_range} 个，"
                f"但屏幕上只有 {len(snap.options)} 个选项")
        say(f"[匹配] 没找到 {text!r}")
        say(f"       屏幕上是这些选项：{' / '.join(snap.option_texts())}")
        say("       （要么是听错了，要么这个词屏幕上确实没有 —— "
            "重说一遍，或者直接说序号，比如「1」「第二个」）")
        return

    if result.by_ordinal:
        description = f"序号命中：第 {result.ordinal_index} 个"
    else:
        description = f"{result.level_name}：{result.node.text!r}"

    if result.ambiguous:
        others = [n.text for n in result.candidates if n is not result.node]
        say(f"       [注意] 有 {len(result.candidates)} 个选项都匹配上了，取了最专一的一个。"
            f"其它候选：{' / '.join(others)}")

    do_click(result.node, ctx, description)


def handle_numpad(number, ctx, stamp=None):
    """
    小键盘按下数字：点第 number 个选项。

    用**屏幕上真实报出的坐标**去点 —— 不做任何坐标推算。

    这条「不推算坐标」是踩坑之后定下来的。曾经做过两种方案：
    用缓存坐标、用配置好的固定坐标，都跳过了读屏。但选项位置会随题干
    长短整体偏移（实测同一个选项见过 1375 和 1418 两个位置，差 43 像素，
    而行高只有 150），复用旧坐标会**静默点错** —— 点了、没报错、但不是你要的。

    提速的正解不是「跳过读屏」，而是**把读屏提前做**：点完立刻在后台把下一屏
    读好（见 ScreenPrefetcher），按键时直接用那份结果 —— 坐标依然是系统报的
    当前值，一点没「猜」。只有没预读成时才当场读一次兜底（日志会明说）。

    `stamp`（动作时戳，可为 None）是**按下按键那一刻**的屏幕指纹，由调用方
    （热键回调）从 ScreenPrefetcher.identity() 取来。这个参数是为了修一个
    真机上实测到的 bug：在第一题上连按两下 `1`，第一下点完立刻作废缓存并启动
    后台预读；第二下还在队列里排队，等它被处理时预读已经读回了**第二题**，
    于是照着第二题点了第 1 个 —— 根子是「第一题时做的动作被用到了第二题上」。
    真正执行前拿 stamp 跟当前屏幕比一次，不一样就不点。语音路径不盖戳
    （stamp 为 None），此时不做拦截。
    """
    say(f"[小键盘] {number}")
    started = time.monotonic()

    try:
        snap, source = grab_screen(ctx)
    except AdbError as exc:
        say(f"[屏幕] {exc}")
        return

    # 核对「动作时戳」：这一下是在哪一屏按的？现在要点的又是哪一屏？
    # 不一样就说明中间翻了页 —— 那这一下绝不能点（会点到新题目上）。
    if stamp is not None and ScreenPrefetcher.signature(snap) != stamp:
        say("[小键盘] 这一下已忽略：界面在按键之后翻页了（不点，免得点到新题上）")
        return

    if not snap.ok:
        report_unusable_screen(snap)
        return

    count = len(snap.options)
    index = count - number + 1 if ctx["cfg"].hotkey.numpad_reverse else number

    if not (1 <= index <= count):
        say(f"[小键盘] 按了 {number}，但当前只有 {count} 个选项")
        say(f"         屏幕上是这些选项：{' / '.join(snap.option_texts())}")
        return

    show_screen(snap)
    say(f"       （界面来源：{source}）")
    do_click(snap.options[index - 1], ctx, f"小键盘第 {index} 个", key=("numpad", index))


def handle_next(ctx, source="小键盘 0"):
    """
    点「下一题」。

    答错、或者点了「不记得了」之后，GRE3000 会翻到词汇详情页，
    得点一下「下一题」才能继续答题。小键盘 0 绑的就是它。

    配置里给了 fixed_next_position 就直接点那个坐标；
    没给就读屏去找——找按钮比找选项宽松得多，代价是一次读屏。
    """
    say(f"[{source}] 下一题")
    started = time.monotonic()
    cfg = ctx["cfg"].hotkey

    if cfg.fixed_next_position is not None:
        x, y = cfg.fixed_next_position
        node = screen.Node(text="下一题（固定位置）", x=x, y=y, clickable=True)
        say(f"       [固定位置] 用配置坐标 ({x}, {y})，耗时 "
            f"{(time.monotonic() - started) * 1000:.0f} 毫秒（未做界面校验）")
        do_click(node, ctx, "「下一题」（固定位置）", key=("next",))
        return

    try:
        snap, source = grab_screen(ctx)
    except AdbError as exc:
        say(f"[屏幕] {exc}")
        return

    if snap.foreground_package != screen.GRE_PACKAGE:
        say(f"[屏幕] 当前不在 GRE3000（检测到的是 "
            f"{snap.foreground_package or '未知应用'}），请先切回去")
        return

    if snap.next_button is None:
        say("[屏幕] 当前界面上没找到「下一题」按钮")
        texts = [n.text for n in snap.all_text_nodes][:25]
        if texts:
            say(f"       屏幕上的文字：{' / '.join(texts)}")
        say("       如果按钮文字不在这里面，把它发给我，我加进识别列表")
        return

    say(f"       （界面来源：{source}）")
    do_click(snap.next_button, ctx, f"「{snap.next_button.text}」", key=("next",))


def handle_force_read(ctx):
    """
    小键盘「.」：强制重新读一次界面。

    什么时候需要它：你自己用鼠标动了手机（翻了页、点开了别的界面），
    而程序手里的还是上一次读到的样子 —— 按一下这个键，强制同步一次。

    正常答题用不上：程序**点完会自动预读下一屏**，按键时直接用那份结果，
    界面一直跟着走，不存在"拿着旧界面点新题"的问题。
    这个键是给你手动纠偏用的 —— 你自己用鼠标翻过页、程序手里那份对不上了，
    按一下强制同步。
    """
    say("[小键盘] . → 强制重新读屏")

    ctx["prefetcher"].invalidate()          # 先丢掉手里那份，免得又用回旧的
    started = time.monotonic()
    try:
        xml = ctx["adb"].dump_ui()
    except AdbError as exc:
        say(f"[屏幕] {exc}")
        return
    read_ms = (time.monotonic() - started) * 1000

    snap = screen.read_screen(xml)
    ctx["prefetcher"].note(snap)            # 存下来，接下来的数字键可以立刻用

    if not snap.ok:
        report_unusable_screen(snap)
        return

    show_screen(snap)
    say(f"       （强制读屏 {read_ms:.0f} 毫秒（{len(xml) // 1024} KB））")


def run_calibrate(ctx):
    """
    --calibrate：读一次屏，把当前界面的东西量出来。

    主要用途是标定「下一题」按钮的坐标 —— 它在详情页上，位置是固定的。
    顺带把选项坐标也列出来，方便对照「题干长短不同时位置漂了多少」。

    刻意不校验前台应用（标定时可能停在任何页面上），但会打印出来供核对。
    """
    section("界面标定（只测量，不点击）")

    try:
        xml = ctx["adb"].dump_ui()
    except AdbError as exc:
        say(f"[!!] {exc}")
        return 1

    snap = screen.read_screen(xml, expected_package=None)

    say(f"  前台应用　：{snap.foreground_package}")
    say(f"  页面类型　：{snap.page}")
    if snap.prompt:
        say(f"  题干字符数：{len(snap.prompt)}")
        prompt = snap.prompt if len(snap.prompt) <= 70 else snap.prompt[:70] + "..."
        say(f"  题干　　　：{prompt}")
    say()

    exit_code = 0

    # --- 选项坐标（现在只作为参考信息，不再用于固定点击）
    if snap.options:
        say(f"  选项坐标（共 {len(snap.options)} 个）：")
        for i, node in enumerate(snap.options, 1):
            say(f"      {i}. ({node.x:>4}, {node.y:>4})   {node.text[:44]!r}")
        ys = [n.y for n in snap.options]
        gaps = [ys[i + 1] - ys[i] for i in range(len(ys) - 1)]
        if gaps:
            say(f"      相邻间距：{gaps}")
            say(f"      {'等距' if len(set(gaps)) == 1 else '**不等距** —— 有选项换行占了两行'}")
        say()
        say("      这些坐标仅供参考：换个题干长度它们就会整体漂移，")
        say("      所以选项不走固定坐标，每次都用读屏拿到的实时值。")
    else:
        say("  这个界面上没有选项（不是答题页）。")

    # --- 下一题按钮：这个是真正要标定的
    say()
    if snap.next_button is not None:
        say(f"  「下一题」按钮：{snap.next_button.text!r} @ "
            f"({snap.next_button.x}, {snap.next_button.y})")
        say()
        say("  想让它固定用这个坐标（更快），把这行粘进 config.yaml：")
        say(f"      fixed_next_position: [{snap.next_button.x}, {snap.next_button.y}]")
        say("  不填也行 —— 程序会每次读屏去找它，更稳。")
    else:
        exit_code = 1
        say("  没有找到「下一题」按钮。")
        say()
        say("  如果你现在就停在答错后的详情页上，说明按钮文字不在识别列表里。")
        say("  请把下面这段整个发回给开发者：")
        say()
        for node in snap.all_text_nodes[:40]:
            say(f"      {node.text!r}  @({node.x},{node.y})")

    say()
    return exit_code


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="声控手机助手 —— 说出选项文字，自动点它",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--config", help="配置文件路径，默认用项目根目录的 config.yaml")
    parser.add_argument("--adb", help="adb.exe 路径")
    parser.add_argument("--device", type=int, help="强制指定麦克风序号")
    parser.add_argument("--mode", choices=["listen", "hotkey"], help="启动时的模式")
    parser.add_argument("--preview", action="store_true", help="不真点，只把位置画圈存图")
    parser.add_argument("--once", action="store_true", help="只说一句就退出（调试用）")
    parser.add_argument("--dump", action="store_true", help="只抓一次屏幕并打印，不识别不点击")
    parser.add_argument("--calibrate", action="store_true",
                        help="量出当前界面的选项坐标和「下一题」按钮坐标，生成配置片段")
    args = parser.parse_args(argv)

    # 先开日志，越早越好 —— 这样连启动阶段的报错也能留下记录
    project_root = Path(__file__).resolve().parent.parent
    stamp = time.strftime("%Y%m%d_%H%M%S")
    log_path = project_root / "debug" / f"run_{stamp}.log"
    open_log(log_path)

    say()
    say("  声控手机助手 —— 说选项，自动点")
    say(f"  日志文件：{log_path}")
    say()

    # --- 配置
    cfg = load_config(args.config)
    for notice in cfg.notices:
        say(f"  [配置] {notice}")

    if args.device is not None:
        cfg.audio.input_device = args.device

    mode = args.mode or cfg.run.default_mode
    preview = args.preview or cfg.run.preview

    # --- 设备
    section("连接手机")
    try:
        adb = Adb(args.adb)
    except AdbError as exc:
        say(f"[!!] {exc}")
        return 1

    say(f"  adb: {adb.path}")
    try:
        serial = adb.device_serial()
    except AdbError as exc:
        say(f"[!!] {exc}")
        return 1

    info = adb.device_info()
    say(f"  [OK] 已连接 {serial}　{info.get('品牌','')} {info.get('型号','')}　"
        f"Android {info.get('Android','?')}　{info.get('分辨率','?')}")

    debug_dir = Path(__file__).resolve().parent.parent / "debug"
    ctx = {
        "adb": adb,
        "cfg": cfg,
        "preview": preview,
    }

    # --- 只做屏幕解析检查
    if args.dump:
        return run_dump_once(ctx)

    # --- 只做坐标标定
    if args.calibrate:
        return run_calibrate(ctx)

    # --- 语音识别
    section("准备语音识别")
    recognizer = Recognizer(cfg.asr, cfg.audio, log=say)
    ctx["recognizer"] = recognizer
    try:
        recognizer.warmup()
    except AsrError as exc:
        say(f"[!!] {exc}")
        return 1

    # --- 监视界面
    section("准备界面读取")
    # 预读器要先建好：下面读到的这一屏要顺手存进它的缓存，
    # 否则启动后的第一次操作会因为没有缓存而当场读屏（白等约 2.4 秒）。
    ctx["prefetcher"] = ScreenPrefetcher(adb, cfg, log=say)
    startup_snap = probe_startup_screen(adb, ctx["prefetcher"], log=say)
    if startup_snap is not None:
        if startup_snap.ok:
            say(f"  [OK] 当前正在 GRE3000 答题界面，识别到 {len(startup_snap.options)} 个选项")
        else:
            say(f"  [注意] {startup_snap.reason}")
            say("         程序会继续运行，但只有切到答题界面后才会点击")

    # --- 先备好点击与语音模块。热键回调随时可能用到它们，必须先于热键注册存在。
    ctx["mode"] = mode
    ctx["clicker"] = Clicker(adb, cfg.click, log=say, debug_dir=debug_dir)
    ctx["voice_gate"] = VoiceGate(cfg.voice, log=say)

    # --- 热键
    section("准备热键")
    hotkeys = HotkeyManager(cfg.hotkey, log=say)
    # 工作线程要用它们（分发 "intent" 时会读 ctx["hotkeys"] / ctx["wake_event"]），
    # 所以必须赶在 numpad_worker 那个线程启动之前建好。
    ctx["hotkeys"] = hotkeys
    wake_event = threading.Event()
    ctx["wake_event"] = wake_event

    # 小键盘走独立工作线程，不放在主循环里。
    # 因为常驻监听模式下主循环会一直阻塞在「等你说话」上，
    # 那时候按小键盘就没有任何反应了。
    numpad_queue = queue.Queue()
    worker_stop = threading.Event()

    def numpad_worker():
        while not worker_stop.is_set():
            try:
                action = numpad_queue.get(timeout=0.2)
            except queue.Empty:
                continue
            try:
                dispatch_action(action, ctx)
            except AdbError as exc:
                say(f"[!!] {exc}")
            except Exception:  # noqa: BLE001
                say("[!!] 处理小键盘操作时出错：")
                log_exception()


    def toggle_mode():
        if ctx["mode"] == "listen" and not hotkeys.available:
            say()
            say("  [注意] 全局热键不可用，没法切到「按住说话」模式")
            say("         多半是没装 keyboard 库，或者缺少权限。常驻监听照常可用。")
            return
        ctx["mode"] = "hotkey" if ctx["mode"] == "listen" else "listen"
        say()
        say(f"  >>> 已切换到「{'按住说话' if ctx['mode'] == 'hotkey' else '常驻监听'}」模式")

    def voice_toggle():
        ctx["voice_gate"].toggle()

    # 界面要用的意图表。**表里放的就是上面这些热键回调本身** ——
    # 于是「界面点一下」和「按一下热键」走的是同一份代码，不会出现
    # 「界面显示开着、实际没开」这种分裂。
    #
    # 注意：这张表得建在 toggle_mode / voice_toggle **定义之后**，
    # 因为它引用的就是这两个函数。
    ctx["intents"] = {
        "toggle_voice": voice_toggle,
        "toggle_mode": toggle_mode,
        "toggle_numpad": lambda: hotkeys.set_numpad(not hotkeys.numpad_enabled),
        "toggle_prefetch": lambda: _toggle_flag(ctx, "prefetch", "after_click", "点击后预读"),
        "toggle_voice_next": lambda: _toggle_flag(ctx, "voice", "next_command", "语音说「下一题」"),
        "force_read": lambda: handle_force_read(ctx),
        "quit": lambda: hotkeys.quit_requested.set(),
    }

    # 三个按键回调：盖戳 → 入队。盖戳的时机（按键那一刻）封装在 make_action_putters 里。
    putters = make_action_putters(numpad_queue, ctx["prefetcher"])

    if not hotkeys.start(
        on_toggle=toggle_mode,
        on_option=putters["on_option"],
        on_next=putters["on_next"],
        on_force_read=putters["on_force_read"],
        on_toggle_voice=voice_toggle,
    ) and mode == "hotkey":
        say("      [注意] 热键不可用，先用常驻监听模式跑")
        mode = "listen"

    threading.Thread(target=numpad_worker, daemon=True, name="numpad").start()

    section("就绪")
    say(f"  当前模式　　：{'按住说话' if mode == 'hotkey' else '常驻监听'}")
    say(f"  小键盘　　　：{'开启' if hotkeys.numpad_enabled else '关闭'}")
    if preview:
        say("  [preview] 只画圈存图，不会真的点击")
    say()
    if mode == "listen":
        say("  说出选项里的词（说一部分就行），说完稍微停一下即可。")
    else:
        say(f"  按住 {cfg.hotkey.push_to_talk.upper()} 说出选项里的词，松开即点。")
    say("  也可以直接说序号：「1」「第二个」「最后一个」—— 生僻词听不准时用这个最稳。")
    if hotkeys.numpad_enabled:
        say("  小键盘 1~9 点对应选项，0 点「下一题」，. 强制重新读屏（NumLock 要开着）。")
    say()
    say(f"  {cfg.hotkey.toggle_mode.upper()} 切换模式　"
        f"{cfg.hotkey.toggle_numpad.upper()} 开关小键盘　"
        f"{cfg.hotkey.toggle_voice.upper()} 开关语音　ESC 或 Ctrl+C 退出")
    say()

    # --- 主循环
    try:
        run_voice_loop(ctx, hotkeys, recognizer, once=args.once)
    except KeyboardInterrupt:
        say()
        say("  收到中断，正在退出 ...")
    finally:
        worker_stop.set()
        hotkeys.stop()
        recognizer.close()

    say()
    say("  已退出。")
    say()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        say()
        say("  已中断。")
        sys.exit(130)
    except SystemExit:
        raise
    except Exception:  # noqa: BLE001
        say()
        say("  [!!] 程序异常退出，下面是详细信息：")
        say()
        log_exception()
        say()
        say("  请把上面这段（以及整个窗口的内容）发回给开发者。")
        say()
        sys.exit(1)

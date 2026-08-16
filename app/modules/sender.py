"""发送模块：进入消息页 → 定位好友会话 → 发送 "[续火花]" 文字（抖音会自动转为火花表情）。

注意：抖音网页版消息页的"搜索"是全局 AI 搜索（搜视频/用户/全网），不是联系人搜索，
因此默认只依赖"会话列表直接点击"定位好友（要求与对方有过私信记录）。
若网页版存在独立联系人搜索入口，可在 config.yaml 打开 search_friend 并按 diag 结果微调。
"""
import random
import time

from playwright.sync_api import BrowserContext, Page

from modules.logger import get_logger

# ---------- 页面元素定位（网页版改版时优先调整这里，可用 scripts/run_diag.bat 探查） ----------
MSG_TAB_TEXT = "消息"
# 聊天输入框：优先 contenteditable / role=textbox（聊天框），不用 input（那是搜索框）
INPUT_SELECTORS = [
    '[contenteditable="true"]',
    '[contenteditable="plaintext-only"]',
    '[role="textbox"]',
    "textarea",
]
MESSAGE_PAGE_URL = None  # 该 URL 兜底不可靠（曾导致页面跳走），已弃用，仅保留占位
CONTACT_SEARCH_HINTS = ["联系人", "搜索好友", "找人", "搜索聊天"]

_CLICK_TIMEOUT = 15000
# 本次进程是否已成功进入过消息页（首次加载慢，需等 6 秒；之后重载快，3 秒即可）
_ENTERED_MESSAGES = False


def _in_message_page(page: Page) -> bool:
    """判断当前是否停留在消息页。
    只认 URL 路径特征或会话列表结构，不用 textarea（评论区也有，会误判）。"""
    url = page.url.lower()
    if any(k in url for k in ("message", "/im", "chat", "user/self")):
        return True
    for sel in ['[class*="conversation"]', '[class*="chat-list"]', '[class*="session"]']:
        try:
            if page.locator(sel).first.count():
                return True
        except Exception:  # noqa: BLE001
            continue
    return False


def _dump_page_signals(page: Page) -> None:
    """输出页面诊断信息，定位为什么无法进入/识别消息页。"""
    logger = get_logger()
    try:
        url = page.url
        title = page.title()
    except Exception:  # noqa: BLE001
        url, title = "?", "?"
    logger.warning(f"[诊断] 当前 URL: {url}")
    logger.warning(f"[诊断] 页面标题: {title}")
    hits = []
    for name, sel in [
        ("url含message", None),
        ("conversation", '[class*="conversation"]'),
        ("chat-list", '[class*="chat-list"]'),
        ("session", '[class*="session"]'),
        ("textarea", "textarea"),
    ]:
        if name == "url含message":
            if "message" in url.lower():
                hits.append(name)
            continue
        try:
            if page.locator(sel).first.count():
                hits.append(name)
        except Exception:  # noqa: BLE001
            continue
    logger.warning(f"[诊断] 消息页特征命中: {hits or '无'}")
    texts = []
    els = page.locator("button, a, [role=button], nav span, nav div")
    for i in range(min(els.count(), 40)):
        try:
            el = els.nth(i)
            if el.is_visible():
                t = (el.inner_text() or "").strip().replace("\n", " ")[:30]
                if t and t not in texts:
                    texts.append(t)
        except Exception:  # noqa: BLE001
            continue
    logger.warning(f"[诊断] 页面可见导航/按钮文本: {texts[:25]}")


def _find_msg_entry(page: Page):
    """定位右上角'消息'入口：全页匹配第一个可见的"消息"文本（就是右上角铃铛入口）。"""
    logger = get_logger()
    els = page.get_by_text(MSG_TAB_TEXT, exact=True)
    for i in range(min(els.count(), 8)):
        el = els.nth(i)
        try:
            if el.is_visible():
                return el
        except Exception:  # noqa: BLE001
            continue
    return None


def _rand_delay(cfg: dict) -> None:
    """拟人化随机延迟。"""
    d = cfg["delays"]
    time.sleep(random.uniform(d["min"], d["max"]))


def _chat_input(page: Page):
    """返回聊天输入框元素（可见的），找不到返回 None。
    关键：聊天输入框在页面底部，取"最靠底部的可见输入框"，
    避免匹配到搜索框/评论框等其他输入元素。"""
    candidates = []
    for sel in INPUT_SELECTORS:
        els = page.locator(sel)
        n = els.count()
        for i in range(min(n, 8)):
            try:
                el = els.nth(i)
                if not el.is_visible():
                    continue
                box = el.bounding_box()
                if box:
                    candidates.append((box["y"] + box["height"], el))
            except Exception:  # noqa: BLE001
                continue
    if not candidates:
        return None
    candidates.sort(key=lambda t: t[0], reverse=True)
    return candidates[0][1]


def _chat_open(page: Page) -> bool:
    return _chat_input(page) is not None


def _conversation_visible(page: Page, cfg: dict) -> bool:
    """消息页会话列表是否出现：config 中任一好友文本可见即认为已进入消息页。"""
    friends = cfg.get("friends") or []
    for name in friends[:3]:
        try:
            els = page.get_by_text(name, exact=False)
            if els.count():
                for i in range(min(els.count(), 3)):
                    if els.nth(i).is_visible():
                        return True
        except Exception:  # noqa: BLE001
            continue
    return False


def goto_messages(page: Page, cfg: dict) -> bool:
    """进入消息页：点击右上角'消息'入口。

    关键策略（卡顿场景）：
    1. 点击前等待页面完全加载（networkidle + 3 秒缓冲），避免点击太快失效；
    2. 点击后拉长时间等待消息页渲染（7 秒）；
    3. 用"会话列表出现（好友文本可见）"验证是否真的进入，失败重试最多 3 次。
    注意：点击后 URL 可能仍是 /jingxuan（SPA 切换内容不更新 URL），不做 URL 判定。
    """
    logger = get_logger()
    global _ENTERED_MESSAGES
    # 首次进入消息页加载慢（等 6 秒）；同进程内后续重载快（3 秒）
    wait_after_click = 6000 if not _ENTERED_MESSAGES else 3000
    for attempt in range(1, 4):
        page.goto("https://www.douyin.com/", wait_until="domcontentloaded", timeout=60000)
        # 重载首页后等 3 秒（SPA 渲染、事件绑定），不搞长等待
        page.wait_for_timeout(3000)

        target = _find_msg_entry(page)
        if target is None:
            logger.warning(f"第 {attempt} 次：未找到右上角'消息'入口，输出诊断信息")
            _dump_page_signals(page)
            continue
        try:
            target.click(timeout=_CLICK_TIMEOUT)
            logger.info(f"已点击右上角'消息'入口（第 {attempt} 次）")
        except Exception as e:  # noqa: BLE001
            logger.warning(f"第 {attempt} 次点击消息入口异常：{type(e).__name__} {str(e)[:120]}")

        # 点击消息后等待消息页渲染：首次 6 秒，后续 3 秒
        page.wait_for_timeout(wait_after_click)
        if _conversation_visible(page, cfg):
            _ENTERED_MESSAGES = True
            logger.info("已进入消息页（会话列表出现）")
            return True
        logger.warning(f"第 {attempt} 次点击后未检测到会话列表，重新加载重试")

    logger.error("进入消息页失败（已重试 3 次，详见上方日志）")
    return False


def _open_conversation(page: Page, friend: str, cfg: dict) -> bool:
    """在消息页打开与好友的会话。
    策略1：会话列表直接点击好友昵称（默认且推荐，要求有私信记录）。
    策略2：联系人搜索（config 开启 search_friend 才尝试，且检测到联系人搜索入口才用）。"""
    logger = get_logger()
    # text= 为子串匹配：兼容会话列表里"昵称 + 时间"等组合显示；
    # 关键：等待好友文本出现（会话列表异步渲染，可能需数秒），而非即时检查
    item = page.locator(f"text={friend}").first
    try:
        # 进入消息页后会话列表已渲染，好友应很快可见；8 秒足够，超时则快速重试
        item.wait_for(state="visible", timeout=8000)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"等待会话列表中的 {friend} 出现超时（8s）：{type(e).__name__}")
        _dump_page_signals(page)  # 诊断：当前是否真的在消息页、列表长什么样
    else:
        try:
            item.scroll_into_view_if_needed(timeout=8000)
            item.click(timeout=_CLICK_TIMEOUT)
            logger.info(f"已点击会话项：{friend}")
            # 点击后轮询等待聊天输入框出现（最多 6 秒），而非固定等待
            for _ in range(12):
                if _chat_open(page):
                    logger.info(f"已在会话列表中找到并打开：{friend}")
                    return True
                page.wait_for_timeout(500)
            logger.warning(f"点击了 {friend} 但未出现聊天输入框（可能点到非会话元素）")
        except Exception as e:  # noqa: BLE001
            logger.warning(f"点击 {friend} 异常：{type(e).__name__} {str(e)[:150]}")

    if cfg.get("search_friend", False):
        logger.info(f"尝试联系人搜索：{friend}")
        if _try_search(page, friend):
            return True

    logger.warning(
        f"无法定位好友会话：{friend}。请确认：1) 与对方有私信记录（会话列表可见）；"
        f"2) config.yaml 中的昵称与对方抖音昵称一致。"
    )
    return False


def _try_search(page: Page, friend: str) -> bool:
    """尝试联系人搜索。若检测到是 AI 搜索则退出并返回 False。"""
    logger = get_logger()
    btn = page.locator('[class*="search"], [aria-label*="搜索"]').first
    if not btn.count():
        return False
    try:
        btn.click(timeout=_CLICK_TIMEOUT)
        page.wait_for_timeout(1500)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"点击搜索按钮失败：{type(e).__name__}")
        return False

    box = page.locator('[contenteditable="true"], [role="textbox"], textarea, input').first
    if not box.count():
        return False
    ph = (box.get_attribute("placeholder") or "").strip()
    # AI 搜索检测：placeholder 不含联系人特征即视为 AI 搜索，放弃并退出
    if not any(h in ph for h in CONTACT_SEARCH_HINTS):
        logger.info(f"检测到非联系人搜索（placeholder={ph!r}），放弃搜索兜底并退出")
        page.keyboard.press("Escape")
        page.wait_for_timeout(800)
        return False
    try:
        box.fill(friend)
        page.wait_for_timeout(1500)
        result = page.get_by_text(friend, exact=True).first
        if result.count():
            result.click(timeout=_CLICK_TIMEOUT)
            page.wait_for_timeout(2500)
            if _chat_open(page):
                logger.info(f"已通过联系人搜索打开会话：{friend}")
                return True
    except Exception as e:  # noqa: BLE001
        logger.warning(f"联系人搜索异常：{type(e).__name__}")
    return False


def _send_button(page: Page):
    """返回可见的发送按钮元素，找不到返回 None。"""
    for sel in ['[class*="send"]', '[aria-label*="发送"]', 'svg[aria-label*="发送"]']:
        el = page.locator(sel).first
        try:
            if el.count() and el.is_visible():
                return el
        except Exception:  # noqa: BLE001
            continue
    return None


def _chat_window_text(page: Page, box) -> str:
    """取聊天窗口（输入框向上取文本最多的祖先容器）的可见文本。
    发送前后对比此文本是否变化，即可判断消息是否真的上屏。
    不依赖猜测的 class 名，而是基于输入框所在的容器推导。"""
    try:
        return box.evaluate(
            """e => {
                let n = e;
                let best = '';
                for (let k = 0; k < 6 && n; k++, n = n.parentElement) {
                    const t = n.innerText || '';
                    if (t.length > best.length) best = t;
                }
                return best;
            }"""
        )
    except Exception:  # noqa: BLE001
        return None


def _send_text(page: Page, text: str) -> bool:
    """在聊天输入框输入文字并发送。
    成功判断采用双信号（任一成立即成功）：
      信号1：聊天窗口文本发生变化（消息真的上屏了——最可靠，不猜 class）；
      信号2：输入框被清空或消失（发送成功后抖音会清空/重建输入框）。
    输入采用逐字键入（press_sequentially），触发真实输入事件，适配 React 受控输入框。"""
    logger = get_logger()
    box = _chat_input(page)
    if not box:
        logger.warning("未找到聊天输入框")
        return False

    def box_state() -> str:
        """返回输入框当前状态：'empty' / 'has-text' / 'gone'（不可见或已从 DOM 移除）。
        优先读发送时定位到的 box（原引用）；元素被重建时重新定位底部输入框。"""
        try:
            v = box.evaluate(
                "e => (e.value !== undefined && e.value !== null) ? e.value : (e.innerText || '')"
            )
            return "empty" if not str(v).strip() else "has-text"
        except Exception:  # noqa: BLE001
            # 原元素 detached（发送后抖音重建输入框），重新定位再读
            b = _chat_input(page)
            if b is None:
                return "gone"
            try:
                v = b.evaluate(
                    "e => (e.value !== undefined && e.value !== null) ? e.value : (e.innerText || '')"
                )
                return "empty" if not str(v).strip() else "has-text"
            except Exception:  # noqa: BLE001
                return "gone"

    win_before = _chat_window_text(page, box)

    def is_sent() -> tuple:
        """返回 (是否成功, 信号来源)。"""
        try:
            win_now = _chat_window_text(page, box)
            if win_before is not None and win_now is not None and win_now != win_before:
                return True, "聊天窗口文本变化"
        except Exception:  # noqa: BLE001
            pass
        bs = box_state()
        if bs in ("empty", "gone"):
            return True, f"输入框{bs}"
        return False, bs

    try:
        box.click(timeout=_CLICK_TIMEOUT)
        page.wait_for_timeout(300)
        # 逐字键入（触发真实 input 事件，React 受控输入框也生效；比 fill 可靠且更拟人）
        box.press_sequentially(text, delay=100)
        page.wait_for_timeout(500)
        logger.info(f"已输入发送内容：{text}")

        # 方式1：回车发送，轮询等待成功信号（最多 8 秒）
        page.keyboard.press("Enter")
        sent, src = False, ""
        for _ in range(16):
            page.wait_for_timeout(500)
            sent, src = is_sent()
            if sent:
                break

        # 方式2：回车无效则点发送按钮
        if not sent:
            logger.info("回车后未检测到发送成功，尝试点击发送按钮")
            btn = _send_button(page)
            if btn:
                try:
                    btn.click(timeout=_CLICK_TIMEOUT)
                except Exception as e:  # noqa: BLE001
                    logger.warning(f"点击发送按钮异常：{type(e).__name__} {str(e)[:100]}")
            for _ in range(16):
                page.wait_for_timeout(500)
                sent, src = is_sent()
                if sent:
                    break

        if sent:
            page.wait_for_timeout(2000)  # 让消息完整上屏再退出
            logger.info(f"已确认发送成功（信号：{src}）")
            return True
        logger.warning(f"发送后未检测到成功信号（输入框状态={box_state()}），消息可能未发出")
        return False
    except Exception as e:  # noqa: BLE001
        logger.warning(f"发送文字异常：{type(e).__name__} {str(e)[:120]}")
        return False


def send_to_friend(context: BrowserContext, page: Page, friend: str, cfg: dict) -> bool:
    """给单个好友发送消息，成功返回 True（含重试）。"""
    logger = get_logger()
    retry = cfg["retry"]
    # 发送内容：优先 message.text（如 "[续火花吧]"），兼容旧配置 fallback_text
    text = cfg["message"].get("text") or cfg["message"].get("fallback_text", "[续火花吧]")
    for attempt in range(1, retry["max_attempts"] + 1):
        try:
            if not _open_conversation(page, friend, cfg):
                # 找不到好友：强制刷新页面（清除状态异常）→ 重新进入消息页 → 再试
                logger.warning(f"第 {attempt} 次尝试：未找到 {friend}，刷新页面并重新进入消息页重试")
                try:
                    page.reload(wait_until="domcontentloaded", timeout=60000)
                    page.wait_for_timeout(2000)
                except Exception as e:  # noqa: BLE001
                    logger.warning(f"刷新页面异常（继续重定向）：{type(e).__name__}")
                goto_messages(page, cfg)
                _rand_delay(cfg)
                continue

            if _send_text(page, text):
                logger.info(f"✔ 成功给 {friend} 发送：{text}")
                return True
            logger.warning(f"第 {attempt} 次尝试给 {friend} 发送失败")
        except Exception as e:  # noqa: BLE001 - 重试前统一记录
            logger.warning(f"第 {attempt} 次尝试给 {friend} 发送异常：{e}")
        time.sleep(retry["interval_sec"])
    return False

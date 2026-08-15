"""诊断脚本：探查抖音网页版消息页的真实 DOM 结构，输出到 diag_output.txt。
用途：修复 sender.py 中的页面元素定位（消息入口、会话列表、聊天输入框、表情按钮、搜索框）。
运行：conda run -n dy_spark python diag.py  或  scripts\\run_diag.bat
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import yaml

from modules.logger import init_logger
from modules.login import ensure_logged_in, launch

APP_DIR = os.path.dirname(os.path.abspath(__file__))
OUT_PATH = os.path.join(APP_DIR, "diag_output.txt")

FRIEND = ""  # 用 config.yaml 的第一个好友来定位会话


def main() -> int:
    cfg = yaml.safe_load(open(os.path.join(APP_DIR, "config.yaml"), encoding="utf-8"))
    global FRIEND
    if cfg.get("friends"):
        FRIEND = cfg["friends"][0]

    init_logger(cfg["log"]["dir"], cfg["log"]["keep_days"])
    p, context = launch(cfg["browser"]["profile_dir"], cfg["browser"]["headless"])

    lines = []
    out_f = open(OUT_PATH, "w", encoding="utf-8")

    def log(*a) -> None:
        line = " ".join(str(x) for x in a)
        print(line)
        lines.append(line)
        out_f.write(line + "\n")
        out_f.flush()

    def dump_inputs(page, tag: str) -> None:
        """列出页面上所有输入类元素。"""
        for sel in ["input", "textarea", "[contenteditable]", "[role=textbox]"]:
            els = page.locator(sel)
            n = els.count()
            log(f"--- {tag} :: {sel} 共 {n} 个")
            for i in range(min(n, 12)):
                try:
                    el = els.nth(i)
                    ph = (el.get_attribute("placeholder") or "")[:40]
                    aria = (el.get_attribute("aria-label") or "")[:40]
                    cls = (el.get_attribute("class") or "")[:70]
                    tag2 = el.evaluate("e => e.tagName")
                    vis = el.is_visible()
                    log(f"    [{i}] <{tag2}> visible={vis} placeholder={ph!r} aria={aria!r} class={cls}")
                except Exception as e:  # noqa: BLE001
                    log(f"    [{i}] 读取失败: {type(e).__name__}")

    def dump_buttons(page, tag: str, limit: int = 50) -> None:
        """列出页面上主要可点击元素的可见文本。"""
        els = page.locator("button, a, [role=button], [class*=button], [class*=tab]")
        texts = []
        for i in range(min(els.count(), limit)):
            try:
                el = els.nth(i)
                if not el.is_visible():
                    continue
                t = (el.inner_text() or "").strip().replace("\n", " ")[:40]
                cls = (el.get_attribute("class") or "")[:50]
                if t:
                    texts.append(f"{t!r} class={cls}")
            except Exception:  # noqa: BLE001
                pass
        log(f"--- {tag} :: 可点击元素文本:")
        for t in texts[:40]:
            log("    ", t)

    try:
        if not ensure_logged_in(context, cfg["browser"]["login_timeout_sec"]):
            log("登录失败，无法探查。请确认已扫码登录。")
            return 1

        page = context.new_page()

        # ---------- 第 1 步：主页找"消息"入口 ----------
        page.goto("https://www.douyin.com/", wait_until="domcontentloaded")
        page.wait_for_timeout(3000)
        log("=== 第1步 主页 URL:", page.url)
        dump_buttons(page, "主页")

        msg = page.get_by_text("消息", exact=True).first
        log("=== 主页找到'消息'文本元素数:", msg.count())
        if msg.count():
            try:
                msg.click(timeout=8000)
                page.wait_for_timeout(3500)
                log("=== 已点击'消息'，当前 URL:", page.url)
            except Exception as e:  # noqa: BLE001
                log("=== 点击'消息'失败:", type(e).__name__, str(e)[:200])

        # ---------- 第 2 步：消息页结构 ----------
        log("")
        log("=== 第2步 消息页输入框结构")
        dump_inputs(page, "消息页")
        log("=== 消息页按钮/链接")
        dump_buttons(page, "消息页")

        # 会话列表样本：含好友昵称的元素
        if FRIEND:
            log(f"=== 查找会话列表中的好友 [{FRIEND}]:")
            hits = page.get_by_text(FRIEND, exact=True)
            log("    精确匹配元素数:", hits.count())
            for i in range(min(hits.count(), 6)):
                try:
                    el = hits.nth(i)
                    cls = (el.get_attribute("class") or "")[:80]
                    # 输出其祖链 class，帮助定位会话项容器
                    chain = el.evaluate(
                        """e => {
                            const out = [];
                            let n = e;
                            for (let k = 0; k < 5 && n; k++, n = n.parentElement) {
                                out.push(n.tagName + '.' + (n.className || '').toString().slice(0, 60));
                            }
                            return out;
                        }"""
                    )
                    log(f"    [{i}] 元素 class={cls!r} 祖先链: {' < '.join(chain)}")
                except Exception as e:  # noqa: BLE001
                    log(f"    [{i}] 读取失败: {type(e).__name__}")

        # 打开第一个会话（若有），探查聊天输入框
        first_item = page.locator('[class*="conversation"], [class*="chat-list"] li, [class*="session"]').first
        log("=== 会话列表项候选元素数:", page.locator('[class*="conversation"]').count(),
            "/", page.locator("li").count())
        if first_item.count():
            try:
                first_item.click(timeout=8000)
                page.wait_for_timeout(3000)
                log("=== 第3步 已打开第一个会话，URL:", page.url)
                dump_inputs(page, "聊天窗口")
                dump_buttons(page, "聊天窗口", 60)
            except Exception as e:  # noqa: BLE001
                log("=== 打开会话失败:", type(e).__name__, str(e)[:200])

        # ---------- 第 3 步：探查"搜索"按钮行为（是否 AI 搜索） ----------
        log("")
        log("=== 第3步 搜索按钮探查")
        for sel in ['[class*="search"]', 'svg[aria-label*="搜索"]', '[aria-label*="搜索"]']:
            el = page.locator(sel).first
            if el.count():
                log(f"    找到搜索候选: {sel} visible={el.is_visible()}")
                try:
                    el.click(timeout=8000)
                    page.wait_for_timeout(2000)
                    dump_inputs(page, "点击搜索后")
                    break
                except Exception as e:  # noqa: BLE001
                    log(f"    点击搜索失败: {type(e).__name__}")

        log("")
        log("=== 探查完成，结果已保存到 diag_output.txt")
        return 0
    finally:
        out_f.close()
        context.close()
        p.stop()


if __name__ == "__main__":
    sys.exit(main())

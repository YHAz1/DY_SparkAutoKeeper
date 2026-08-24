"""登录模块：启动浏览器（持久化登录态）、检测登录态、扫码登录等待。"""
import os
import sys
import time
from typing import Tuple

# 打包运行时：让 Playwright 使用包内自带的浏览器
if getattr(sys, "frozen", False):
    os.environ.setdefault(
        "PLAYWRIGHT_BROWSERS_PATH",
        os.path.join(getattr(sys, "_MEIPASS", ""), "ms-playwright"),
    )

from playwright.sync_api import BrowserContext, sync_playwright

from modules.logger import get_logger

# DouYin 登录态核心 cookie（网页版登录后存在 sessionid 即视为已登录）
_SESSION_COOKIE = "sessionid"


def _is_logged_in(context: BrowserContext) -> bool:
    for c in context.cookies():
        if c.get("name") == _SESSION_COOKIE and c.get("value"):
            return True
    return False


def launch(profile_dir: str, gpu: bool = True) -> Tuple[object, BrowserContext]:
    """启动浏览器（持久化 profile，含登录 cookie）。返回 (playwright, context)。
    固定有头模式：无头模式在部分环境下易崩溃且风控更高，已移除该选项。
    gpu=False 时禁用 GPU 渲染（纯软件渲染更慢但完全不占显卡，适合显卡正跑模型时）。"""
    logger = get_logger()
    args = ["--disable-blink-features=AutomationControlled"]
    if not gpu:
        args.append("--disable-gpu")
    p = sync_playwright().start()
    context = p.chromium.launch_persistent_context(
        user_data_dir=profile_dir,
        headless=False,
        args=args,
        locale="zh-CN",
    )
    logger.info(f"浏览器已启动（gpu={'开' if gpu else '关'}, profile={profile_dir}）")
    return p, context


def _mark_logged_in() -> None:
    """登录成功后写确认标记（GUI 状态徽章据此显示已登录/未登录）。"""
    try:
        if getattr(sys, "frozen", False):
            base = os.path.dirname(sys.executable)
        else:
            base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        d = os.path.join(base, "data")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, ".session_ok"), "w", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S"))
    except Exception:  # noqa: BLE001
        pass


def ensure_logged_in(context: BrowserContext, timeout_sec: int = 180) -> bool:
    """确保已登录。未登录时打开 DouYin 主页，提示用户在浏览器窗口中扫码，轮询等待。
    返回是否登录成功。"""
    logger = get_logger()
    page = context.new_page()
    try:
        if _is_logged_in(context):
            logger.info("检测到已有登录态（sessionid），无需重新登录")
            _mark_logged_in()
            return True

        page.goto("https://www.douyin.com/", wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(3000)
        if _is_logged_in(context):
            logger.info("登录态检测通过")
            _mark_logged_in()
            return True

        logger.info("未检测到登录态，请在弹出的浏览器窗口中扫码登录 DouYin…")
        deadline = time.time() + timeout_sec
        while time.time() < deadline:
            page.wait_for_timeout(2000)
            if _is_logged_in(context):
                logger.info("扫码登录成功")
                _mark_logged_in()
                return True
        logger.error(f"等待登录超时（{timeout_sec}s），请重新运行本程序并完成扫码")
        return False
    finally:
        page.close()

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
# 定义与"不开浏览器的登录态探测"共用，避免两处常量各写一份
from modules.session_probe import SESSION_COOKIE as _SESSION_COOKIE  # noqa: E402
from modules.session_probe import probe_saved_login  # noqa: E402,F401  对外便捷导出


def _is_logged_in(context: BrowserContext) -> bool:
    for c in context.cookies():
        if c.get("name") == _SESSION_COOKIE and c.get("value"):
            return True
    return False


def _kill_stale_browser(profile_dir: str) -> None:
    """强杀占用本程序 profile 的残留浏览器/驱动进程。
    按命令行中的 profile 路径精确匹配，不会误杀用户自己开的 Chrome。"""
    try:
        import subprocess

        safe = str(profile_dir).replace("'", "''")
        ps = (
            "Get-CimInstance Win32_Process | Where-Object { "
            f"$_.CommandLine -like '*{safe}*' -and "
            "($_.Name -eq 'chrome.exe' -or $_.Name -eq 'headless_shell.exe' -or $_.Name -eq 'node.exe') } | "
            "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
        )
        subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps],
            capture_output=True, timeout=30,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000),
        )
    except Exception:  # noqa: BLE001 - 清理失败不阻塞主流程
        pass


def _clear_stale_locks(profile_dir: str) -> None:
    """清理强制结束残留的 Chromium 单例锁文件。

    浏览器被强杀时 SingletonLock / SingletonCookie / SingletonSocket 会留在
    profile 里；下次启动若读到一个"已被占用"的锁，Chromium 可能放弃原 profile
    另起一个（表现为"明明登录过却要重新扫码"）。这里在启动前主动清掉。"""
    for name in ("SingletonLock", "SingletonCookie", "SingletonSocket"):
        try:
            p = os.path.join(profile_dir or "", name)
            if p and os.path.exists(p):
                os.remove(p)
        except OSError:
            pass


# gpu=False（省资源模式）时的全套软件渲染参数：不碰显卡的任何加速路径
_SOFTWARE_RENDER_ARGS = [
    "--disable-gpu",
    "--disable-gpu-compositing",
    "--disable-accelerated-2d-canvas",
    "--disable-accelerated-video-decode",
    "--disable-accelerated-video-encode",
]


def launch(profile_dir: str, gpu: bool = True) -> Tuple[object, BrowserContext]:
    """启动浏览器（持久化 profile，含登录 cookie）。返回 (playwright, context)。
    固定有头模式：无头模式在部分环境下易崩溃且风控更高，已移除该选项。
    gpu=False：全套软件渲染参数，完全不碰显卡（页面渲染走 CPU，稍慢但发送任务不受影响）。

    启动失败的分级自愈（越往后越激进，**隔离 profile 是最后手段**）：
      ① 清理占用 profile 的残留进程后重试；
      ② 清理强杀残留的单例锁文件后重试（锁文件会让 Chromium 另起新 profile，
         表现就是"更新一次就要重新扫码登录一次"）；
      ③ 把旧 profile 隔离为 profile.corrupt-时间戳（可手动找回），用全新 profile
         启动——避免 profile 真的损坏后软件永远无法登录。
    隔离前会先把 cookie 库复制到 profile.corrupt-时间戳 同名目录，便于人工找回。"""
    logger = get_logger()
    args = ["--disable-blink-features=AutomationControlled"]
    if not gpu:
        args += _SOFTWARE_RENDER_ARGS
    p = sync_playwright().start()
    last_err: Exception = RuntimeError("browser launch failed")
    for attempt in (1, 2, 3, 4):
        try:
            context = p.chromium.launch_persistent_context(
                user_data_dir=profile_dir,
                headless=False,
                args=args,
                locale="zh-CN",
            )
            logger.info(f"浏览器已启动（gpu={'开' if gpu else '关'}, profile={profile_dir}）")
            return p, context
        except Exception as e:  # noqa: BLE001
            last_err = e
            logger.warning(f"浏览器启动失败（第 {attempt} 次）：{e}")
            if attempt == 1:
                _kill_stale_browser(profile_dir)
            elif attempt == 2:
                _clear_stale_locks(profile_dir)
                time.sleep(1)
            elif attempt == 3 and profile_dir and os.path.isdir(profile_dir):
                quarantine = profile_dir.rstrip("/\\") + ".corrupt-" + time.strftime("%Y%m%d-%H%M%S")
                try:
                    os.rename(profile_dir, quarantine)
                    logger.warning(
                        f"登录配置疑似损坏，已隔离到 {quarantine}；"
                        "本次将用全新配置启动，需重新扫码登录一次（旧登录态可从该目录找回）")
                except OSError as re_err:
                    logger.warning(f"隔离旧 profile 失败：{re_err}")
    p.stop()
    raise last_err


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

        try:
            page.goto("https://www.douyin.com/", wait_until="domcontentloaded", timeout=60000)
        except Exception as e:  # noqa: BLE001 - 主页偶发加载失败，重试一次
            logger.warning(f"打开 DouYin 主页异常，重试一次：{type(e).__name__}")
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

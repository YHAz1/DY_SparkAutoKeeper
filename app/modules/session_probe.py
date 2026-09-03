"""本地登录态探测：直接读浏览器 cookie 库，不启动浏览器。

单独成模块的原因：login.py 在模块级 import playwright（较重，首次导入要 1-3 秒），
而这个探测只需要 stdlib。面板启动校准、更新前后自检都要用它，放在轻量模块里
可以做到毫秒级返回，也不会为了"看一眼登录没登录"就把浏览器拉起来。

重要性：以往"每次更新都要重新登录一次"的根因，就是启动浏览器检查登录态 →
偶发启动失败 → login.launch 的分级自愈把 profile 隔离成 profile.corrupt-* →
登录态丢失。只读探测从根上切断了这条链路。
"""
import datetime
import os

# DouYin 网页版登录后存在的会话 cookie
SESSION_COOKIE = "sessionid"

# Chromium Cookie 库在 profile 里的可能位置（版本/迁移状态不同会有差异）
_COOKIE_DB_RELS = (
    os.path.join("Default", "Network", "Cookies"),
    os.path.join("Default", "Cookies"),
    "Cookies",
)

# Chromium 时间戳基准：1601-01-01 UTC，库里存的是微秒
_CHROME_EPOCH = datetime.datetime(1601, 1, 1, tzinfo=datetime.timezone.utc)


def cookie_db_path(profile_dir: str) -> str:
    """返回 profile 里存在的 cookie 库路径；不存在则返回空串。"""
    for rel in _COOKIE_DB_RELS:
        p = os.path.join(profile_dir or "", rel)
        try:
            if os.path.isfile(p) and os.path.getsize(p) > 0:
                return p
        except OSError:
            continue
    return ""


def probe_saved_login(profile_dir: str) -> "bool | None":
    """读本地 cookie 库判断 DouYin 是否仍处于登录态。

    返回：
      True  = 库里有未过期的 douyin sessionid（不需要重新扫码）
      False = 库存在，但没有有效登录 cookie（需要重新登录）
      None  = 库不存在或读不了（首次使用 / 库损坏），无法判断

    读法：先把库复制一份再打开——浏览器正在写库时直接连会撞锁。
    """
    src = cookie_db_path(profile_dir)
    if not src:
        return None

    tmp = os.path.join(
        os.environ.get("TEMP") or os.path.dirname(src),
        f"_sparkak_ck_{os.getpid()}.sqlite",
    )
    rows = []
    try:
        import shutil
        import sqlite3

        shutil.copy2(src, tmp)
        con = sqlite3.connect(tmp)
        try:
            rows = con.execute(
                "SELECT host_key, expires_utc FROM cookies WHERE name = ?",
                (SESSION_COOKIE,),
            ).fetchall()
        except Exception:  # noqa: BLE001 - 表结构变化/库损坏：按"读不到"处理
            rows = []
        finally:
            con.close()
    except Exception:  # noqa: BLE001 - sqlite 不可用（极简打包环境）：静默降级
        return None
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass

    if not rows:
        return False
    now_us = int((datetime.datetime.now(datetime.timezone.utc)
                  - _CHROME_EPOCH).total_seconds() * 1_000_000)
    for host, expires in rows:
        if "douyin" not in str(host or "").lower():
            continue
        try:
            exp = int(expires or 0)
        except (TypeError, ValueError):
            exp = 0
        # expires_utc = 0 是会话 cookie：只要还在库里就当作有效
        if exp == 0 or exp > now_us:
            return True
    return False

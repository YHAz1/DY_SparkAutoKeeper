"""远程通知模块（企业微信群机器人 webhook）+ 网络连通性等待。

设计要点：
- 网络层沿用自更新模块的方案：使用系统自带 curl.exe 子进程，
  彻底绕开 PyInstaller+conda 打包后 _ssl DLL 依赖损坏的问题。
- 连通性探测：任一探测地址收到 HTTP 响应（curl 退出码 0）即视为联网，
  无论状态码；douyin 优先（发送目标本身），baidu 作通用联网参考。
- webhook 消息为企业微信 text 格式；钉钉群机器人的文本消息格式相同，
  因此粘贴钉钉 webhook 也能收到提醒（@所有人能力除外）。
- JSON 报文经临时文件传给 curl（--data-binary @file），规避
  Windows 命令行对中文/引号/换行的转义问题。
"""
import json
import os
import subprocess
import tempfile
import time

_CREATE_NO_WINDOW = 0x08000000

# 连通性探测地址：优先探测目标站点本身，其次通用站点作联网参考
_PROBE_URLS = ("https://www.douyin.com", "https://www.baidu.com")


def _curl_path() -> str:
    root = os.environ.get("SystemRoot", r"C:\Windows")
    return os.path.join(root, "System32", "curl.exe")


def _curl_run(args: list, timeout: int = 30):
    """执行 curl，返回 (returncode, stdout_bytes, stderr_text)。"""
    cmd = [_curl_path(), "-sS", "--ssl-no-revoke", *args]
    r = subprocess.run(
        cmd, capture_output=True, timeout=timeout,
        creationflags=_CREATE_NO_WINDOW,
    )
    return r.returncode, r.stdout, r.stderr.decode("utf-8", errors="replace")


def is_online(timeout: int = 8) -> bool:
    """当前是否联网：任一探测地址有响应即为 True。"""
    if not os.path.exists(_curl_path()):
        return True  # 无 curl 的异常环境不阻塞发送，交给后续流程自然报错
    for url in _PROBE_URLS:
        try:
            rc, _, _ = _curl_run(
                ["-o", "NUL", "-m", str(timeout), url], timeout=timeout + 5)
        except Exception:  # noqa: BLE001
            rc = -1
        if rc == 0:
            return True
    return False


def wait_for_network(log=None, timeout_min: float = 5, poll_sec: int = 15) -> bool:
    """等待网络可用（睡眠唤醒后 Wi-Fi 重连可能需要几分钟）。

    立即在线直接返回 True；否则每 poll_sec 秒探测一次，
    直到恢复（True）或超过 timeout_min 分钟（False）。"""
    timeout_min = max(0.0, float(timeout_min))
    if is_online():
        return True
    if log is not None:
        log.info(f"网络未连接，最多等待 {timeout_min:g} 分钟（睡眠唤醒后重连可能较慢）")
    deadline = time.time() + timeout_min * 60
    last_note = time.time()
    while True:
        remain = deadline - time.time()
        if remain <= 0:
            break
        time.sleep(min(poll_sec, max(1, remain)))
        if is_online():
            if log is not None:
                log.info("网络已恢复，继续执行")
            return True
        if log is not None and time.time() - last_note >= 60:
            log.info("网络仍未连接，继续等待…")
            last_note = time.time()
    if is_online():
        return True
    if log is not None:
        log.warning(f"等待 {timeout_min:g} 分钟后网络仍不可用")
    return False


def send_webhook(url: str, content: str, mention_all: bool = False,
                 log=None, timeout: int = 20) -> bool:
    """POST 文本消息到群机器人 webhook。返回 True 表示机器人确认接收（errcode==0）。

    企业微信机器人地址形如 https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=…
    （企业微信群 → 右键 → 添加群机器人 → 查看，复制 Webhook 地址）。"""
    url = str(url or "").strip()
    if not url.lower().startswith(("http://", "https://")):
        if log is not None:
            log.warning("webhook 地址未配置或不合法，跳过远程提醒")
        return False
    text = {"content": str(content)}
    if mention_all:
        text["mentioned_list"] = ["@all"]
    payload = {"msgtype": "text", "text": text}

    fd, tmp = tempfile.mkstemp(suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
        args = [
            "-m", str(timeout),
            "-H", "Content-Type: application/json",
            "--data-binary", f"@{tmp}",
            url,
        ]
        for attempt in (1, 2):
            try:
                rc, body, err = _curl_run(args, timeout=timeout + 10)
            except Exception as e:  # noqa: BLE001
                rc, body, err = -1, b"", str(e)
            errcode, errmsg = None, ""
            try:
                resp = json.loads(body.decode("utf-8", errors="replace"))
                errcode = resp.get("errcode")
                errmsg = str(resp.get("errmsg", ""))
            except Exception:  # noqa: BLE001
                pass
            if rc == 0 and errcode == 0:
                return True
            if errcode not in (None, 0):
                # 机器人明确拒绝（如 key 无效、被限流），重试无意义
                if log is not None:
                    log.warning(f"webhook 返回错误 errcode={errcode} errmsg={errmsg}")
                return False
            if log is not None:
                log.warning(f"webhook 推送失败（第 {attempt}/2 次）rc={rc} {err[:80]}")
            if attempt == 1:
                time.sleep(3)
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass
    return False


def _names(friends: list, limit: int = 30) -> str:
    fs = [str(f) for f in friends][:limit]
    s = "、".join(fs)
    if len(friends) > limit:
        s += f" 等 {len(friends)} 位"
    return s


def build_fail_text(failed: list) -> str:
    return ("⚠️ 续火花 · 发送失败\n"
            f"以下好友今日未发送成功：{_names(failed)}\n"
            f"时间：{time.strftime('%H:%M')}（已自动重试仍失败）\n"
            "请尽快打开软件手动补发，避免火花中断。")


def build_remind_text(failed: list) -> str:
    return ("⚠️ 续火花 · 晚间检查：今日仍未发送成功！\n"
            f"好友：{_names(failed)}\n"
            f"时间：{time.strftime('%H:%M')}（晚间自动补发也未成功）\n"
            "请立即手动处理，避免火花中断！")


def build_resend_ok_text(friends: list) -> str:
    return (f"✅ 续火花 · 已自动补发成功\n好友：{_names(friends)}\n"
            f"时间：{time.strftime('%H:%M')}（晚间提醒任务自动完成）")


def build_recover_text(friends: list) -> str:
    return (f"✅ 续火花 · 补发成功\n好友：{_names(friends)}\n"
            f"时间：{time.strftime('%H:%M')}（网络恢复后系统自动触发完成）")

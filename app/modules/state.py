"""状态模块：记录每个好友最近一次成功发送的时间，用于"每日一次"防重与补发判断。"""
import datetime
import json
import os
import sys
from typing import Dict, Optional


def _app_dir() -> str:
    """程序数据目录：打包后为 exe 所在目录，开发时为脚本目录。"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


STATE_FILE = os.path.join(_app_dir(), "data", "state.json")


def _load() -> Dict[str, str]:
    if not os.path.exists(STATE_FILE):
        return {}
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _save(state: Dict[str, str]) -> None:
    """原子写入：先写临时文件再替换，避免写入中途崩溃导致 JSON 损坏
    （损坏会让下次启动误判"所有人都没发过"，从而重复发送）。"""
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    os.replace(tmp, STATE_FILE)


def last_sent_time(friend: str) -> Optional[str]:
    """返回该好友最近一次成功发送时间（'YYYY-MM-DD HH:MM:SS'），从未发送过则返回 None。"""
    return _load().get(friend)


def sent_today(friend: str) -> bool:
    """今天是否已经给该好友发送过。"""
    last = last_sent_time(friend)
    if not last:
        return False
    day = last[:10]
    return day == datetime.date.today().isoformat()


def mark_sent(friend: str) -> None:
    """记录该好友本次发送成功的时间。"""
    state = _load()
    state[friend] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    _save(state)


def need_send(friend: str) -> bool:
    """是否需要发送：今天没发过即为需要（天然覆盖开机补发：昨天错过，今天照发）。"""
    return not sent_today(friend)

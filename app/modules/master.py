"""总开关（暂停/恢复）与单好友冻结：配置归一化、状态判定、自动恢复。

数据落在 config.yaml 的两处（都是可选字段，老配置缺失时按默认值补齐）：

    master:
      enabled: true          # 总开关：false 表示暂停
      pause_until: ''        # 定时暂停：暂停到哪一天（含当天），过期自动恢复
      permanent: false       # 永久暂停：只能由用户手动打开总开关
    frozen_friends: []       # 冻结的好友备注：仍留在好友列表，但不发送

语义约定：
- 暂停 N 天 = 从今天起连续 N 天不发送，第 N+1 天自动恢复
  （即 pause_until = 今天 + (N-1) 天；N=1 表示只停今天）。
- 自动恢复在运行期判定：读到 pause_until 已过期就置回 enabled=True 并清空
  暂停字段，由调用方（main.py）负责把变更写回 config.yaml。
- 冻结只影响"发给谁"，不影响好友列表本身：冻结的备注仍在列表里、可一键解冻。
"""
import datetime

DEFAULT_MASTER = {"enabled": True, "pause_until": "", "permanent": False}

# 多日暂停的允许范围（防止手滑填 999 天把自己坑了）
MIN_PAUSE_DAYS = 1
MAX_PAUSE_DAYS = 365

_FROZEN_KEY = "frozen_friends"


# ---------------- 归一化 ----------------

def _today() -> datetime.date:
    return datetime.date.today()


def _parse_date(raw) -> "datetime.date | None":
    """把 'YYYY-MM-DD' 解析成 date；非法/空返回 None。"""
    s = str(raw or "").strip()
    if not s:
        return None
    try:
        return datetime.date.fromisoformat(s[:10])
    except ValueError:
        return None


def normalize(cfg: dict) -> dict:
    """补齐/修正 master 与 frozen_friends 字段（就地修改并返回同一 dict）。

    容错点：手改 config 可能把 enabled 写成字符串、把 pause_until 写成非法日期、
    frozen_friends 写成字符串而非列表——这里一律拉回合法形态。"""
    if not isinstance(cfg, dict):
        return cfg
    m = cfg.get("master")
    if not isinstance(m, dict):
        m = dict(DEFAULT_MASTER)
    enabled = m.get("enabled", True)
    m["enabled"] = str(enabled).strip().lower() not in ("false", "0", "no", "off", "")
    m["permanent"] = bool(m.get("permanent", False))
    pu = _parse_date(m.get("pause_until"))
    m["pause_until"] = pu.isoformat() if pu else ""
    # 永久暂停优先：两者同时出现时以永久为准，避免"到期自动恢复"推翻用户本意
    if m["permanent"]:
        m["pause_until"] = ""
    cfg["master"] = m

    frozen = cfg.get(_FROZEN_KEY)
    if isinstance(frozen, str):
        frozen = [frozen] if frozen.strip() else []
    if not isinstance(frozen, list):
        frozen = []
    # 去重保序 + 去空白
    cfg[_FROZEN_KEY] = list(dict.fromkeys(
        str(x).strip() for x in frozen if str(x).strip()))
    return cfg


# ---------------- 查询 ----------------

def is_paused(cfg: dict, today: "datetime.date | None" = None) -> bool:
    """当前是否处于暂停（含永久暂停与尚未到期的定时暂停）。"""
    m = (cfg or {}).get("master") or {}
    if m.get("enabled", True):
        return False
    if m.get("permanent"):
        return True
    until = _parse_date(m.get("pause_until"))
    if until is None:
        # 既非永久也没有合法截止日：视作永久暂停，避免"永远停着又永不恢复"的歧义
        return True
    return (today or _today()) <= until


def resume_date(cfg: dict) -> "datetime.date | None":
    """定时暂停的恢复日期（暂停期的最后一天），永久暂停/未暂停返回 None。"""
    m = (cfg or {}).get("master") or {}
    if m.get("enabled", True) or m.get("permanent"):
        return None
    return _parse_date(m.get("pause_until"))


def remaining_days(cfg: dict, today: "datetime.date | None" = None) -> int:
    """定时暂停还剩几天（含今天）；非定时暂停返回 0。"""
    until = resume_date(cfg)
    if until is None:
        return 0
    return max(0, (until - (today or _today())).days + 1)


def status_text(cfg: dict, today: "datetime.date | None" = None) -> str:
    """给界面用的中文状态文案。

    开启态不提"每天几点自动发送"——定时任务是否注册由任务徽章表达，
    总开关只如实反映"发/不发"，避免未注册任务时出现误导性描述。"""
    today = today or _today()
    if not is_paused(cfg, today):
        return "已开启"
    m = (cfg or {}).get("master") or {}
    if m.get("permanent"):
        return "已永久关闭 · 打开总开关后恢复"
    left = remaining_days(cfg, today)
    until = resume_date(cfg)
    if until is None:
        return "已关闭 · 打开总开关后恢复"
    when = until + datetime.timedelta(days=1)
    if left <= 1:
        return f"已暂停 1 天 · 明天（{when:%m-%d}）自动恢复"
    return f"已暂停 {left} 天 · {when:%m-%d} 自动恢复"


# ---------------- 变更 ----------------

def resolve(cfg: dict, today: "datetime.date | None" = None) -> tuple:
    """运行期入口：判定是否暂停，顺带处理到期自动恢复。

    返回 (paused, changed)：
    - paused=True  → 调用方应跳过本次发送
    - changed=True → cfg 已被自动恢复改写，调用方需把配置写回磁盘
    """
    normalize(cfg)
    m = cfg["master"]
    today = today or _today()
    # 注意：不能先用 is_paused 判断——暂停期已过时必须走到下面的自动恢复分支
    if m.get("enabled", True):
        return False, False
    if m.get("permanent"):
        return True, False
    until = _parse_date(m.get("pause_until"))
    if until is None:
        return True, False
    if today <= until:
        return True, False
    # 暂停期已过：自动恢复
    resume(cfg)
    return False, True


def pause_days(cfg: dict, days: int, today: "datetime.date | None" = None) -> str:
    """暂停 N 天（含今天）。返回截止日 'YYYY-MM-DD'。"""
    normalize(cfg)
    try:
        n = int(days)
    except (TypeError, ValueError):
        n = 1
    n = max(MIN_PAUSE_DAYS, min(MAX_PAUSE_DAYS, n))
    until = (today or _today()) + datetime.timedelta(days=n - 1)
    cfg["master"]["enabled"] = False
    cfg["master"]["permanent"] = False
    cfg["master"]["pause_until"] = until.isoformat()
    return until.isoformat()


def pause_forever(cfg: dict) -> None:
    """永久暂停，直到用户手动打开总开关。"""
    normalize(cfg)
    cfg["master"]["enabled"] = False
    cfg["master"]["permanent"] = True
    cfg["master"]["pause_until"] = ""


def resume(cfg: dict) -> None:
    """立即恢复（打开总开关）。"""
    normalize(cfg)
    cfg["master"]["enabled"] = True
    cfg["master"]["permanent"] = False
    cfg["master"]["pause_until"] = ""


# ---------------- 好友冻结 ----------------

def frozen_set(cfg: dict) -> set:
    normalize(cfg)
    return set(cfg.get(_FROZEN_KEY) or [])


def is_frozen(cfg: dict, name: str) -> bool:
    return str(name).strip() in frozen_set(cfg)


def set_frozen(cfg: dict, name: str, frozen: bool) -> bool:
    """设置某好友的冻结状态，返回设置后的状态。"""
    normalize(cfg)
    name = str(name).strip()
    if not name:
        return False
    cur = set(cfg[_FROZEN_KEY])
    if frozen:
        cur.add(name)
    else:
        cur.discard(name)
    # 冻结名单刻意"宽松保留"：不在好友列表里的名字也不清掉（test_master 锁定此行为）。
    # 原因：①手改 config 时可以先写 frozen_friends 再补 friends，顺序无关；
    # ②GUI 编辑好友列表的中间状态不会把已冻结的人悄悄解冻。
    # 代价：删掉的好友若日后重名添加，会带着旧的冻结状态回来——但面板徽章可见、可解冻。
    friends = [str(f).strip() for f in (cfg.get("friends") or [])]
    cfg[_FROZEN_KEY] = [f for f in friends if f in cur] + \
                       [f for f in cur if f not in friends]
    return frozen


def toggle_freeze(cfg: dict, name: str) -> bool:
    """切换冻结状态，返回切换后是否处于冻结。"""
    return set_frozen(cfg, name, not is_frozen(cfg, name))


def active_friends(cfg: dict) -> list:
    """今天应当发送的好友（已排除冻结项）。"""
    frozen = frozen_set(cfg)
    return [f for f in (cfg.get("friends") or []) if str(f).strip() not in frozen]


def split_friends(cfg: dict) -> tuple:
    """返回 (可发送好友列表, 冻结好友列表)。"""
    frozen = frozen_set(cfg)
    act, froz = [], []
    for f in (cfg.get("friends") or []):
        s = str(f).strip()
        (froz if s in frozen else act).append(s)
    return act, froz

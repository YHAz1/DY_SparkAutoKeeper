"""自动续火花 · 设置面板（PyQt5）

独立于任务运行：关闭此窗口不影响已注册的定时任务/开机自启。
功能：好友管理、发送设置、高级设置、自启任务管理、手动运行、实时日志。
风格：暖白 + 杏橙，圆角卡片，微软雅黑。
"""
import os
import re
import subprocess
import sys
import threading
import datetime
import json
import time

from PyQt5.QtCore import Qt, QTimer, QUrl
from PyQt5.QtGui import QFont, QDesktopServices
from PyQt5.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressDialog,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

import yaml

from modules import updater as upd


def _app_dir() -> str:
    """程序数据目录：打包后为 exe 所在目录，开发时为脚本目录。"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


APP_DIR = _app_dir()
CONFIG_PATH = os.path.join(APP_DIR, "config.yaml")
LOG_PATH = os.path.join(APP_DIR, "logs", "app.log")
SESSION_MARK = os.path.join(APP_DIR, "data", ".session_ok")
TASK_NAME = "DYSparkAutoKeeper"
PS_SCRIPT = os.path.join(APP_DIR, "scripts", "register_task.ps1")
VERSION = "1.3.0"

# 隐藏子进程控制台窗口（防止 schtasks/powershell 等闪现黑框）
CREATE_NO_WINDOW = 0x08000000

USAGE_TEXT = """【使用说明】
1. 首次使用：点击「立即运行一次」，在弹出的浏览器中扫码登录你的账号；登录态保存在本机，之后自动复用
2. 好友列表：填入你对该好友的备注（需与对方有私信记录，会话列表可见）
3. 发送设置：每日发送时间（HH:MM，如 09:00）；发送内容默认 [续火花吧]，输入后自动转为火花表情
4. 点击「注册自启任务」：开机登录自动检查（完成即退出 / 未到点等待 / 错过补发），每日定时发送
5. 运行日志：实时查看每次发送结果（app/logs/app.log）

【数据与存储】
1. 登录态（含登录凭证）仅保存在本机 data/profile 目录，仅用于本程序自动登录
2. 好友备注、发送时间、发送内容保存在本机 config.yaml
3. 发送记录保存在 data/state.json，运行日志保存在 logs/ 目录
4. 所有数据仅存储于你的电脑本地，本程序不向任何服务器或第三方上传"""

DISCLAIMER_TEXT = """【免责声明】
1. 本工具仅供个人学习与娱乐交流使用，请勿用于商业用途或任何违法违规用途
2. 本工具为第三方自动化工具，与平台官方无任何关联，非官方产品
3. 自动化操作可能违反平台用户协议及社区规范，存在账号被限制、封禁的风险
4. 请遵守平台规则，合理低频使用；使用本工具产生的一切后果由使用者自行承担
5. 登录态含账号凭证，请勿将 data/profile 目录分享给他人，以免账号信息泄露
6. 本工具仅限开发者授权的人使用，禁止未经授权外传、复制或转赠
7. 使用过程中如有问题，可向开发者反馈；开发者不对本工具的稳定性、可用性负责，也不对任何直接或间接损失承担责任
8. 使用本工具即表示已阅读并同意以上全部条款"""

QSS = """
QWidget { font-family: "Microsoft YaHei"; font-size: 18px; color: #4A4238; }
QMainWindow, #MainRoot { background: #FDF9F4; }
QFrame#Card { background: #FFFFFF; border-radius: 14px; border: 1px solid #F2E8DC; }
QLabel#CardTitle { font-size: 22px; font-weight: bold; color: #B06A3B; }
QLabel#Hint { color: #A69A8A; font-size: 15px; }
QPushButton {
    background: #E8935A; color: #FFFFFF; border: none; border-radius: 10px;
    padding: 14px 30px; font-size: 18px;
}
QPushButton:hover { background: #D97F43; }
QPushButton:pressed { background: #C96E35; }
QPushButton:disabled { background: #EBD3BC; color: #FFFFFF; }
QPushButton#Ghost {
    background: #FFFFFF; color: #B06A3B; border: 1px solid #E5C9B0;
}
QPushButton#Ghost:hover { background: #FBF1E7; }
QPushButton#Danger { background: #E7B8A8; }
QPushButton#Danger:hover { background: #DD9C88; }
QLineEdit {
    background: #FFFDF9; border: 1px solid #E5D9CC; border-radius: 8px;
    padding: 12px 16px; selection-background-color: #F3C9A4; font-size: 18px;
}
QLineEdit:focus { border: 1px solid #E8935A; }
QListWidget {
    background: #FFFDF9; border: 1px solid #E5D9CC; border-radius: 9px;
    padding: 6px; font-size: 18px;
}
QListWidget::item { padding: 10px 12px; border-radius: 6px; }
QListWidget::item:selected { background: #F8E3D0; color: #7A4A22; }
QPlainTextEdit {
    background: #FFFDF9; border: 1px solid #E5D9CC; border-radius: 9px;
    font-family: "Consolas"; font-size: 15px; color: #4A4238;
}
QSpinBox {
    background: #FFFDF9; border: 1px solid #E5D9CC; border-radius: 7px;
    padding: 9px 14px; font-size: 18px;
}
QCheckBox { spacing: 10px; font-size: 18px; }
QCheckBox::indicator {
    width: 20px; height: 20px; border-radius: 5px;
    border: 1px solid #E5C9B0; background: #FFFDF9;
}
QCheckBox::indicator:checked { background: #E8935A; border-color: #E8935A; }
QToolButton#FoldBtn { background: transparent; color: #B06A3B; border: none; font-weight: bold; font-size: 18px; }
QToolButton#FoldBtn:hover { color: #D97F43; }
QScrollArea { background: transparent; border: none; }
QScrollArea > QWidget > QWidget { background: transparent; }
QScrollBar:vertical { background: transparent; width: 10px; }
QScrollBar::handle:vertical { background: #E5D9CC; border-radius: 5px; min-height: 24px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QLabel#BadgeGreen { color: #FFFFFF; background: #7FB77F; border-radius: 11px; padding: 7px 20px; font-size: 16px; }
QLabel#BadgeRed { color: #FFFFFF; background: #D98A8A; border-radius: 11px; padding: 7px 20px; font-size: 16px; }
QLabel#BadgeCheck { color: #FFFFFF; background: #E0A24E; border-radius: 11px; padding: 7px 20px; font-size: 16px; }
QLabel#GuideCard { background: #FFF4E2; color: #8A5A28; border: 1px solid #EFDCBB; border-radius: 10px; padding: 12px 16px; font-size: 16px; }
QLabel#UpdateCard { background: #FDEBC8; color: #7A4A12; border: 2px solid #E0A24E; border-radius: 10px; padding: 14px 18px; font-size: 17px; font-weight: bold; }
QLabel#AboutText { color: #B5A99B; font-size: 14px; }
"""


# ---------------- 工具函数 ----------------

def load_config() -> dict:
    default = {
        "send_time": "09:00",
        "friends": [],
        "message": {"text": "[续火花吧]", "search_friend": False},
        "randomize_time": False,
        "delays": {"min": 1.5, "max": 3.5},
        "retry": {"max_attempts": 3, "interval_sec": 10},
        "browser": {"gpu": True, "profile_dir": "data/profile", "login_timeout_sec": 180},
        "log": {"dir": "logs", "keep_days": 30},
    }
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, encoding="utf-8") as f:
                cfg = yaml.safe_load(f) or {}
            for k, v in default.items():
                if k not in cfg:
                    cfg[k] = v
            if not isinstance(cfg.get("message"), dict):
                cfg["message"] = dict(default["message"])
            for k, v in default["message"].items():
                cfg["message"].setdefault(k, v)
            return cfg
        except Exception:
            pass
    return default


def save_config(cfg: dict) -> bool:
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            yaml.safe_dump(cfg, f, allow_unicode=True, sort_keys=False)
        return True
    except OSError:
        return False


def task_exists() -> bool:
    r = subprocess.run(
        ["schtasks", "/Query", "/TN", TASK_NAME],
        capture_output=True, creationflags=CREATE_NO_WINDOW,
    )
    return r.returncode == 0


def get_env_python() -> str:
    try:
        r = subprocess.run(["conda", "info", "--base"], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=30,
                           creationflags=CREATE_NO_WINDOW)
        base = (r.stdout or "").strip().splitlines()
        if base:
            p = os.path.join(base[0], "envs", "dy_spark", "python.exe")
            if os.path.exists(p):
                return p
    except Exception:
        pass
    return sys.executable


def tail_log(path: str, n: int = 200) -> str:
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - 24576))
            data = f.read().decode("utf-8", errors="replace")
        return "\n".join(data.splitlines()[-n:])
    except Exception:
        return ""


# ---------------- 卡片组件 ----------------

class Card(QFrame):
    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(16, 12, 16, 14)
        self._layout.setSpacing(8)
        if title:
            lbl = QLabel(title)
            lbl.setObjectName("CardTitle")
            self._layout.addWidget(lbl)

    def body(self) -> QVBoxLayout:
        return self._layout


class NoticeDialog(QDialog):
    """打开时的公告：使用说明 + 完整免责声明（每次打开弹出，无关闭叉，同意/不同意退出）。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("DY_SparkAutoKeeper")
        # 去掉右上角关闭叉，只能通过按钮选择
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowCloseButtonHint)
        self.resize(660, 700)
        self.setMinimumSize(600, 640)
        self.setStyleSheet(QSS)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 16, 18, 16)
        lay.setSpacing(10)
        title = QLabel("欢迎使用 · 自动续火花")
        title.setObjectName("CardTitle")
        lay.addWidget(title)
        body = QPlainTextEdit()
        body.setReadOnly(True)
        body.setFont(QFont("Microsoft YaHei", 21))
        body.setLineWrapMode(QPlainTextEdit.WidgetWidth)
        body.setPlainText(USAGE_TEXT + "\n\n" + DISCLAIMER_TEXT)
        body.setMinimumHeight(430)
        lay.addWidget(body, 1)
        row = QHBoxLayout()
        btn_no = QPushButton("不同意，退出")
        btn_no.setObjectName("Danger")
        btn_no.setMinimumHeight(46)
        btn_no.clicked.connect(self.reject)
        row.addWidget(btn_no)
        btn_ok = QPushButton("我已阅读并同意")
        btn_ok.setMinimumHeight(46)
        btn_ok.clicked.connect(self.accept)
        row.addWidget(btn_ok)
        lay.addLayout(row)


# ---------------- 主窗口 ----------------

class SparkGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("DY_SparkAutoKeeper")
        self.resize(1100, 1240)
        self.setMinimumSize(980, 1100)
        self.setStyleSheet(QSS)

        self.cfg = load_config()
        self._running = False

        self._build_ui()
        self._load_config_to_ui()

        # 定时刷新：日志 2 秒、任务状态 8 秒（降低频率减少卡顿）
        self._last_log_text = ""
        self.timer_log = QTimer(self)
        self.timer_log.timeout.connect(self._refresh_log)
        self.timer_log.start(2000)
        self.timer_task = QTimer(self)
        self.timer_task.timeout.connect(self._refresh_task_state)
        self.timer_task.start(8000)
        self._refresh_log()
        # 老用户升级场景：有配置但无登录标记 → 后台静默校准（期间徽章显示检测动效）
        # 先于首次 _refresh_task_state 调用，避免徽章先闪"未登录"再变检测中
        self._login_checking = False
        self._maybe_check_login_async()
        self._refresh_task_state()

        # 自更新状态：_remote_version/_remote_done 由后台线程写入，UI 定时轮询
        self._updating = False
        self._remote_version = None
        self._remote_done = False
        self._startup_update_check()

    # ---------- 界面构建 ----------

    def _build_ui(self):
        root = QWidget()
        root.setObjectName("MainRoot")
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(18, 16, 18, 14)
        outer.setSpacing(12)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        container = QWidget()
        container.setObjectName("ScrollContainer")
        self.main_layout = QVBoxLayout(container)
        self.main_layout.setContentsMargins(0, 0, 6, 0)
        self.main_layout.setSpacing(12)
        scroll.setWidget(container)
        outer.addWidget(scroll, 1)

        self._build_status_card()
        self._build_friends_card()
        self._build_send_card()
        self._build_advanced_card()
        self._build_task_card()
        self._build_log_card()

        self.main_layout.addStretch(1)
        # 版本号与免责声明：固定页脚，不随内容滚动
        self._build_about(outer)

    def _card(self, title: str, stretch: int = 0) -> Card:
        c = Card(title)
        self.main_layout.addWidget(c, stretch)
        return c

    def _build_status_card(self):
        c = self._card("")
        row = QHBoxLayout()
        self.badge_task = QLabel("任务未注册")
        self.badge_task.setObjectName("BadgeRed")
        self.badge_task.setAlignment(Qt.AlignCenter)
        row.addWidget(self.badge_task)
        self.badge_today = QLabel("今日未发送")
        self.badge_today.setObjectName("BadgeRed")
        self.badge_today.setAlignment(Qt.AlignCenter)
        row.addWidget(self.badge_today)
        self.badge_login = QLabel("未登录")
        self.badge_login.setObjectName("BadgeRed")
        self.badge_login.setAlignment(Qt.AlignCenter)
        self.badge_login.setToolTip("登录状态来自最近一次成功登录的记录；点「立即运行一次」可扫码登录")
        row.addWidget(self.badge_login)
        row.addStretch(1)
        self.lbl_last = QLabel("上次运行：—")
        self.lbl_last.setObjectName("Hint")
        row.addWidget(self.lbl_last)
        c.body().addLayout(row)

        # 新手引导条：从未成功登录过时显示，登录成功后自动消失
        self.guide = QLabel(
            "🧭 新手引导：① 点「立即运行一次」扫码登录  →  ② 添加好友备注  →  "
            "③ 设定每日发送时间  →  ④ 点「注册自启任务」。登录成功后本提示自动消失。"
        )
        self.guide.setObjectName("GuideCard")
        self.guide.setWordWrap(True)
        self.guide.setAlignment(Qt.AlignCenter)
        c.body().addWidget(self.guide)

    def _build_friends_card(self):
        c = self._card("好友昵称列表")
        self.list_friends = QListWidget()
        self.list_friends.setMinimumHeight(200)
        c.body().addWidget(self.list_friends)
        row = QHBoxLayout()
        self.edit_friend = QLineEdit()
        self.edit_friend.setPlaceholderText("填入你对该好友的备注（需与对方有私信记录）")
        self.edit_friend.returnPressed.connect(self._add_friend)
        row.addWidget(self.edit_friend, 1)
        btn_add = QPushButton("添加")
        btn_add.clicked.connect(self._add_friend)
        row.addWidget(btn_add)
        btn_del = QPushButton("删除选中")
        btn_del.setObjectName("Ghost")
        btn_del.clicked.connect(self._del_friend)
        row.addWidget(btn_del)
        c.body().addLayout(row)

    def _build_send_card(self):
        c = self._card("发送设置")
        grid = QVBoxLayout()
        grid.setSpacing(8)

        row1 = QHBoxLayout()
        row1.addWidget(QLabel("每日发送时间"))
        self.edit_time = QLineEdit()
        self.edit_time.setPlaceholderText("如 09:00")
        self.edit_time.setFixedWidth(110)
        row1.addWidget(self.edit_time)
        btn_rand = QPushButton("随机")
        btn_rand.setObjectName("Ghost")
        btn_rand.clicked.connect(self._random_time)
        row1.addWidget(btn_rand)
        row1.addStretch(1)
        grid.addLayout(row1)
        hint1 = QLabel("格式：HH:MM（24 小时制，如 09:00 / 23:30）。「随机」在 9:00-22:00 区间随机生成。保存后需重新注册自启任务生效。\n支持自动纠正：9：5、9点5、930 等写法会自动转为 09:05 / 09:30。")
        hint1.setObjectName("Hint")
        hint1.setWordWrap(True)
        grid.addWidget(hint1)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel("发送内容"))
        self.edit_text = QLineEdit()
        self.edit_text.setPlaceholderText("[续火花吧]")
        row2.addWidget(self.edit_text, 1)
        grid.addLayout(row2)
        hint2 = QLabel("输入 [续火花吧] 会自动转为火花表情。")
        hint2.setObjectName("Hint")
        grid.addWidget(hint2)
        c.body().addLayout(grid)

    def _build_advanced_card(self):
        c = self._card("高级设置")
        btn_fold = QToolButton()
        btn_fold.setObjectName("FoldBtn")
        btn_fold.setText("展开设置  ▾")
        btn_fold.setCheckable(True)
        btn_fold.setChecked(False)
        c.body().addWidget(btn_fold)

        inner = QWidget()
        v = QVBoxLayout(inner)
        v.setContentsMargins(0, 4, 0, 0)
        v.setSpacing(8)

        row_d = QHBoxLayout()
        row_d.addWidget(QLabel("拟人延迟（秒）"))
        self.spin_dmin = QSpinBox()
        self.spin_dmin.setRange(0, 30)
        self.spin_dmin.setSuffix(" ~")
        self.spin_dmax = QSpinBox()
        self.spin_dmax.setRange(0, 60)
        self.spin_dmax.setSuffix(" 秒")
        row_d.addWidget(self.spin_dmin)
        row_d.addWidget(self.spin_dmax)
        row_d.addStretch(1)
        v.addLayout(row_d)

        row_r = QHBoxLayout()
        row_r.addWidget(QLabel("重试次数"))
        self.spin_retry = QSpinBox()
        self.spin_retry.setRange(1, 10)
        row_r.addWidget(self.spin_retry)
        row_r.addStretch(1)
        v.addLayout(row_r)

        self.chk_gpu = QCheckBox("启用 GPU 渲染（流畅；显卡跑模型时可关闭）")
        v.addWidget(self.chk_gpu)
        self.chk_random = QCheckBox("每日任务后自动随机明日发送时间（9:00-22:00）并更新定时任务")
        v.addWidget(self.chk_random)
        hint_r = QLabel("勾选后：每天任务执行完自动随机生成明天的发送时间并更新自启任务（删除自启任务则不再自动更新）。\n不勾选：固定使用上方设置的发送时间。")
        hint_r.setObjectName("Hint")
        hint_r.setWordWrap(True)
        v.addWidget(hint_r)

        c.body().addWidget(inner)
        inner.setVisible(False)
        btn_fold.toggled.connect(lambda on: (inner.setVisible(on),
                                             btn_fold.setText("收起设置  ▴" if on else "展开设置  ▾")))

    def _build_task_card(self):
        c = self._card("开机自启 + 定时任务")
        row = QHBoxLayout()
        btn_reg = QPushButton("注册自启任务")
        btn_reg.clicked.connect(self._register_task)
        row.addWidget(btn_reg)
        btn_unreg = QPushButton("删除任务")
        btn_unreg.setObjectName("Danger")
        btn_unreg.clicked.connect(self._unregister_task)
        row.addWidget(btn_unreg)
        btn_run = QPushButton("立即运行一次")
        btn_run.setObjectName("Ghost")
        btn_run.clicked.connect(self._run_once)
        row.addWidget(btn_run)
        c.body().addLayout(row)
        hint = QLabel("注册后：开机登录自动检查（完成即退出 / 未到点等待 / 错过补发）+ 每日定时兜底。")
        hint.setObjectName("Hint")
        hint.setWordWrap(True)
        c.body().addWidget(hint)

    def _build_log_card(self):
        c = self._card("运行日志", stretch=1)
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(500)
        self.log_view.setMinimumHeight(200)
        c.body().addWidget(self.log_view, 1)
        row = QHBoxLayout()
        btn_refresh = QPushButton("刷新")
        btn_refresh.setObjectName("Ghost")
        btn_refresh.clicked.connect(self._refresh_log)
        row.addWidget(btn_refresh)
        btn_clear = QPushButton("清空显示")
        btn_clear.setObjectName("Ghost")
        btn_clear.clicked.connect(self.log_view.clear)
        row.addWidget(btn_clear)
        row.addStretch(1)
        lbl = QLabel(f"自动刷新 · {LOG_PATH}")
        lbl.setObjectName("Hint")
        row.addWidget(lbl)
        c.body().addLayout(row)

    def _build_about(self, outer: QVBoxLayout):
        """固定页脚：版本号 + 检查更新 + 免责声明（始终可见），右下角署名。"""
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet("color: #F0E6DA;")
        outer.addWidget(line)

        # 更新横幅：发现新版本时出现，点击立即更新
        self.lbl_update = QLabel("")
        self.lbl_update.setObjectName("UpdateCard")
        self.lbl_update.setWordWrap(True)
        self.lbl_update.setAlignment(Qt.AlignCenter)
        self.lbl_update.setCursor(Qt.PointingHandCursor)
        self.lbl_update.setVisible(False)
        self.lbl_update.mousePressEvent = lambda e: self._start_update_flow()
        outer.addWidget(self.lbl_update)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        lbl = QLabel(
            f"v{VERSION} · 自动续火花\n"
            "免责声明：本工具仅供个人学习与娱乐交流使用，请遵守平台规则。"
            "使用本工具存在账号风控风险，由此产生的一切后果由使用者自行承担。"
        )
        lbl.setObjectName("AboutText")
        lbl.setWordWrap(True)
        row.addWidget(lbl, 1)
        self.btn_check_update = QPushButton("检查更新")
        self.btn_check_update.setObjectName("Ghost")
        self.btn_check_update.setToolTip("检测 GitHub 上的最新版本；发现新版可一键下载并自动应用")
        self.btn_check_update.clicked.connect(self._manual_check_update)
        row.addWidget(self.btn_check_update)
        owner = QLabel("YHAz")
        owner.setStyleSheet("color: rgba(160, 150, 140, 120); font-size: 14px; background: transparent;")
        owner.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        row.addWidget(owner)
        outer.addLayout(row)

    # ---------- 配置读写 ----------

    def _load_config_to_ui(self):
        self.edit_time.setText(str(self.cfg.get("send_time", "09:00")))
        self.edit_text.setText(self.cfg["message"].get("text", "[续火花]"))
        self.list_friends.clear()
        for name in self.cfg.get("friends", []):
            self.list_friends.addItem(name)
        d = self.cfg.get("delays", {})
        self.spin_dmin.setValue(int(d.get("min", 1.5)))
        self.spin_dmax.setValue(int(d.get("max", 3.5)))
        self.spin_retry.setValue(int(self.cfg.get("retry", {}).get("max_attempts", 3)))
        self.chk_gpu.setChecked(bool(self.cfg.get("browser", {}).get("gpu", True)))
        self.chk_random.setChecked(bool(self.cfg.get("randomize_time", False)))

    def _collect_config(self) -> dict:
        """从界面收集配置（不做写盘）。"""
        cfg = self.cfg
        cfg["send_time"] = self.edit_time.text().strip()
        cfg["friends"] = [self.list_friends.item(i).text() for i in range(self.list_friends.count())]
        cfg["message"]["text"] = self.edit_text.text().strip() or "[续火花吧]"
        cfg["delays"]["min"] = float(self.spin_dmin.value())
        cfg["delays"]["max"] = float(self.spin_dmax.value())
        cfg["retry"]["max_attempts"] = int(self.spin_retry.value())
        cfg["browser"]["gpu"] = bool(self.chk_gpu.isChecked())
        cfg["randomize_time"] = bool(self.chk_random.isChecked())
        return cfg

    def _random_time(self):
        """在 9:00-22:00 区间随机生成发送时间并填入输入框。"""
        import random

        total = random.randint(9 * 60, 22 * 60)  # 9:00 ~ 22:00（含）
        self.edit_time.setText(f"{total // 60:02d}:{total % 60:02d}")

    def _normalize_time(self, raw) -> str:
        """时间输入自动纠错，返回标准 HH:MM；无法识别返回空串。
        支持：全角字符（０９：３０→09:30）、中文冒号/点/时（9点30→09:30）、
        缺前导零（9:5→09:05）、无冒号写法（930→09:30、9→09:00）、末尾"分"。"""
        import unicodedata

        s = unicodedata.normalize("NFKC", str(raw)).strip()
        s = re.sub(r"\s+", "", s)
        s = re.sub(r"[点时]", ":", s)
        s = re.sub(r"[：﹕;；,，。．.]", ":", s)
        s = re.sub(r"(?:分钟|分)$", "", s)
        if not s:
            return ""
        if re.fullmatch(r"\d{1,2}", s):  # 只有小时：9 -> 09:00
            h = int(s)
            return f"{h:02d}:00" if h <= 23 else ""
        if re.fullmatch(r"\d{3,4}", s):  # HMM/HHMM：930 -> 09:30
            d = s.zfill(4)
            h, m = int(d[:2]), int(d[2:])
            return f"{h:02d}:{m:02d}" if h <= 23 and m <= 59 else ""
        parts = s.split(":")
        if len(parts) == 2 and all(p.isdigit() and len(p) <= 2 for p in parts):
            h, m = int(parts[0]), int(parts[1])
            return f"{h:02d}:{m:02d}" if h <= 23 and m <= 59 else ""
        return ""

    def _save_ui_config(self) -> bool:
        """校验并保存配置（发送时间先做自动纠错）。"""
        norm = self._normalize_time(self.edit_time.text())
        if not norm:
            QMessageBox.warning(
                self,
                "时间格式错误",
                f"无法识别的时间输入:{self.edit_time.text().strip()!r}\n"
                "小时 0-23、分钟 0-59,例如 09:00。\n"
                "支持自动纠正:中文冒号(9:30)、缺前导零(9:5)、无冒号(930)、"
                "只填小时(21)等常见写法。",
            )
            return False
        self.edit_time.setText(norm)  # 回填纠正后的标准格式
        self._collect_config()
        if save_config(self.cfg):
            return True
        QMessageBox.warning(self, "保存失败", "无法写入 config.yaml")
        return False

    # ---------- 自更新 ----------

    _UPDATE_MARK = os.path.join(APP_DIR, "data", "update_check.json")

    def _startup_update_check(self):
        """启动静默检测：每天最多一次，不弹任何提示；发现新版仅点亮页脚横幅。"""
        try:
            last = ""
            if os.path.exists(self._UPDATE_MARK):
                with open(self._UPDATE_MARK, encoding="utf-8") as f:
                    last = (json.load(f) or {}).get("last", "")
            if last == datetime.date.today().isoformat():
                return
        except Exception:  # noqa: BLE001
            pass
        threading.Thread(target=self._check_update_worker, args=(False,), daemon=True).start()

    def _check_update_worker(self, manual: bool):
        """后台线程：拉取远端版本号，结果写入 _remote_version/_remote_done。"""
        ver = upd.fetch_remote_version()
        if ver:
            self._remote_version = ver
            try:
                os.makedirs(os.path.dirname(self._UPDATE_MARK), exist_ok=True)
                with open(self._UPDATE_MARK, "w", encoding="utf-8") as f:
                    json.dump({"last": datetime.date.today().isoformat()}, f)
            except Exception:  # noqa: BLE001
                pass
        self._remote_done = True
        if manual:
            self._manual_pending = manual

    def _begin_wait_remote(self):
        self.btn_check_update.setText("检测中…")
        self.btn_check_update.setEnabled(False)
        self._remote_done = False
        self._wait_deadline = time.time() + 25
        self.timer_uwait = QTimer(self)
        self.timer_uwait.timeout.connect(self._poll_remote)
        self.timer_uwait.start(300)

    def _poll_remote(self):
        if not self._remote_done and time.time() < getattr(self, "_wait_deadline", 0):
            return
        t = getattr(self, "timer_uwait", None)
        if t is not None:
            t.stop()
        self.btn_check_update.setText("检查更新")
        self.btn_check_update.setEnabled(True)
        ver = self._remote_version
        timed_out = not self._remote_done
        if ver and upd.is_newer(ver, VERSION):
            self.lbl_update.setText(
                f"🆕 发现新版本 v{ver}（当前 v{VERSION}）· 点击此处立即下载并自动更新"
            )
            self.lbl_update.setVisible(True)
            return
        if getattr(self, "_manual_pending", False):
            self._manual_pending = False
            if timed_out or not ver:
                QMessageBox.warning(self, "检查更新失败",
                                    "无法连接版本服务器（GitHub）。\n"
                                    "可稍后重试，或到 Releases 页面手动下载：\n"
                                    f"https://github.com/{upd.REPO}/releases")
            else:
                QMessageBox.information(self, "检查更新", f"当前已是最新版本 v{VERSION}")

    def _manual_check_update(self):
        if self._updating or self._running or getattr(self, "_login_checking", False):
            QMessageBox.information(self, "请稍候", "当前有任务或检测正在进行，稍后再试。")
            return
        threading.Thread(target=self._check_update_worker, args=(True,), daemon=True).start()
        self._manual_pending = True
        self._begin_wait_remote()

    def _start_update_flow(self):
        """点击更新横幅：确认 → 后台下载（进度条）→ 校验 → 快照用户文件 → 生成脚本并退出应用。"""
        ver = self._remote_version
        if not ver or self._updating:
            return
        if self._running:
            QMessageBox.warning(self, "正在执行任务",
                                "发送任务进行中，无法更新。\n请等待任务结束后再试。")
            return
        ret = QMessageBox.question(
            self, "应用更新",
            f"将下载 v{ver} 更新包（约 384MB），完成后会自动：\n"
            "  · 关闭本程序与浏览器\n"
            "  · 覆盖安装新版本（好友/时间/登录态/记录全部保留）\n"
            "  · 自动重新启动程序\n\n"
            "现在开始吗？（请确保网络可访问 GitHub 或其镜像）",
            QMessageBox.Yes | QMessageBox.No,
        )
        if ret != QMessageBox.Yes:
            return

        self._updating = True
        self.lbl_update.setVisible(False)
        dest_dir = os.path.join(APP_DIR, "_update_tmp")
        dest = os.path.join(dest_dir, f"DY_SparkAutoKeeper_v{ver}_win64.zip")
        state = {"done": 0, "total": 0, "cancel": False}

        dlg = QProgressDialog("正在连接下载源…", "取消", 0, 1, self)
        dlg.setWindowTitle("软件自更新")
        dlg.setWindowModality(Qt.NonModal)
        dlg.setMinimumDuration(0)
        dlg.setAutoClose(False)
        dlg.resize(420, 90)

        urls = upd.asset_urls(ver)

        def worker():
            def on_progress(done, total):
                state["done"], state["total"] = done, total
                return not state["cancel"]

            ok = False
            try:
                ok = upd.download(urls, dest, progress=on_progress) is not None
            except InterruptedError:
                ok = False
            state["finished"] = True
            state["ok"] = ok

        threading.Thread(target=worker, daemon=True).start()

        def poll():
            total = state.get("total") or 0
            done = state.get("done") or 0
            if state.get("finished"):
                poll_t.stop()
                dlg.cancel()
                self._after_download(ver, dest, state.get("ok", False))
                return
            if total > 0:
                if dlg.maximum() != total:
                    dlg.setRange(0, total)
                dlg.setValue(min(done, total))
                dlg.setLabelText(f"正在下载更新包… {done / 1048576:.0f} / {total / 1048576:.0f} MB")
            else:
                dlg.setRange(0, 0)  # 忙碌指示
            if state["cancel"]:
                dlg.cancel()

        poll_t = QTimer(self)
        poll_t.timeout.connect(poll)
        # 取消按钮 → 设置取消标志（worker 检测后中止）
        dlg.canceled.connect(lambda: state.__setitem__("cancel", True))
        poll_t.start(200)

    def _after_download(self, ver: str, dest: str, ok: bool):
        if not ok:
            self._updating = False
            ret = QMessageBox.warning(
                self, "下载失败",
                "所有下载源均失败或已取消。\n打开浏览器手动下载？",
                QMessageBox.Yes | QMessageBox.No,
            )
            if ret == QMessageBox.Yes:
                QDesktopServices.openUrl(QUrl(f"https://github.com/{upd.REPO}/releases"))
            return
        if not upd.verify_zip(dest):
            self._updating = False
            try:
                os.remove(dest)
            except OSError:
                pass
            QMessageBox.warning(self, "更新包损坏", "下载的更新包校验未通过，已删除。\n请重试「检查更新」。")
            return
        upd.backup_user_files(APP_DIR)
        ps1 = upd.write_apply_script(APP_DIR, dest, restart=True)
        QMessageBox.information(
            self, "准备完成",
            "更新包已就绪并通过校验。\n点击确定后将关闭程序并自动应用更新（随后自动重启）。",
        )
        upd.launch_apply(ps1)
        self.close()

    # ---------- 事件 ----------

    def _maybe_check_login_async(self):
        """老用户升级校准：已有 config.yaml 但缺登录标记时，后台读一次本地 cookie
        确认登录态并补写标记。检测期间徽章显示转圈"检测登录"动效。
        新用户（无 config.yaml）不触发——他们本来就没登录过，直接落定未登录。
        静默执行：失败一律忽略并按当前标记落定；若正在运行任务则跳过（避免争抢浏览器 profile）。"""
        if os.path.exists(SESSION_MARK) or self._login_checking or self._running:
            self._settle_login_badge()
            return
        if not os.path.exists(CONFIG_PATH):
            self._settle_login_badge()
            return
        self._login_checking = True
        self._start_login_spinner()

        def worker():
            try:
                from modules.login import launch, _is_logged_in, _mark_logged_in

                prof = self.cfg.get("browser", {}).get("profile_dir", "data/profile")
                if not os.path.isabs(prof):
                    prof = os.path.join(APP_DIR, prof)
                p, context = launch(prof, bool(self.cfg.get("browser", {}).get("gpu", True)))
                try:
                    if _is_logged_in(context):
                        _mark_logged_in()
                finally:
                    context.close()
                    p.stop()
            except Exception:  # noqa: BLE001 - 静默失败：按当前标记落定，后续任务运行会自动校正
                pass
            finally:
                self._login_checking = False
                self._settle_login_badge()

        threading.Thread(target=worker, daemon=True).start()

    # ---- 登录徽章动效 ----

    _SPIN_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

    def _start_login_spinner(self):
        """徽章进入检测中状态：琥珀色 + 转圈帧动画。"""
        self._spin_idx = 0
        self.badge_login.setObjectName("BadgeCheck")
        self.badge_login.setToolTip("正在读取本地登录态…")
        self.timer_spin = QTimer(self)
        self.timer_spin.timeout.connect(self._spin_login_tick)
        self.timer_spin.start(120)
        self._spin_login_tick()

    def _spin_login_tick(self):
        frame = self._SPIN_FRAMES[self._spin_idx % len(self._SPIN_FRAMES)]
        self._spin_idx += 1
        self.badge_login.setText(f"{frame} 检测登录")
        self._restyle(self.badge_login)

    def _stop_login_spinner(self):
        t = getattr(self, "timer_spin", None)
        if t is not None:
            t.stop()

    def _settle_login_badge(self):
        """检测结束（或无需检测）：按标记落定为已登录/未登录。"""
        self._stop_login_spinner()
        logged = os.path.exists(SESSION_MARK)
        self.badge_login.setObjectName("BadgeGreen" if logged else "BadgeRed")
        if logged:
            try:
                with open(SESSION_MARK, encoding="utf-8") as f:
                    ts = f.read().strip()
                self.badge_login.setToolTip(f"已登录（确认于 {ts}）")
            except Exception:  # noqa: BLE001
                self.badge_login.setToolTip("已登录")
        else:
            self.badge_login.setToolTip("尚未检测到登录记录；点「立即运行一次」扫码登录")
        self.badge_login.setText("已登录" if logged else "未登录")
        self._restyle(self.badge_login)
        # 新手引导条：确认已登录后消失
        self.guide.setVisible(not logged)

    def _add_friend(self):
        name = self.edit_friend.text().strip()
        if not name:
            return
        existing = [self.list_friends.item(i).text() for i in range(self.list_friends.count())]
        if name not in existing:
            self.list_friends.addItem(name)
            self.list_friends.scrollToBottom()  # 自动滚动到最新添加的好友
        self.edit_friend.clear()
        self._save_friends_now()
        self._refresh_task_state()

    def _del_friend(self):
        row = self.list_friends.currentRow()
        if row >= 0:
            self.list_friends.takeItem(row)
            self._save_friends_now()
            self._refresh_task_state()

    def _save_friends_now(self):
        """好友增删后实时写入 config.yaml（不等待保存/发送）"""
        self.cfg["friends"] = [self.list_friends.item(i).text() for i in range(self.list_friends.count())]
        try:
            save_config(self.cfg)
        except Exception:
            pass

    def _register_task(self):
        if not self._save_ui_config():
            return
        if not self.cfg.get("friends"):
            QMessageBox.warning(self, "还没有添加好友",
                                "请先在「好友昵称列表」中添加至少一位好友，再注册定时任务。")
            return
        t = self.cfg["send_time"]
        try:
            r = subprocess.run(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                 "-File", PS_SCRIPT, "-Time", t],
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=90,
                creationflags=CREATE_NO_WINDOW,
            )
        except Exception as e:
            QMessageBox.critical(self, "注册失败", str(e))
            return
        ok = r.returncode == 0
        QMessageBox.information(
            self,
            "注册成功" if ok else "注册失败",
            (f"已注册开机自启 + 每日 {t} 定时任务（错过自动补发）" if ok
             else (r.stderr or r.stdout or "未知错误")[:400]),
        )
        self._refresh_task_state()

    def _unregister_task(self):
        if not task_exists():
            self._refresh_task_state()
            return
        if not QMessageBox.question(self, "确认", "确定删除自启 + 定时任务吗？（不影响手动运行）",
                                    QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes:
            return
        subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
             "-File", PS_SCRIPT, "-Unregister"],
            capture_output=True, timeout=90, creationflags=CREATE_NO_WINDOW,
        )
        self._refresh_task_state()

    def _run_once(self):
        if self._running:
            return
        if not self._save_ui_config():
            return
        self._running = True
        threading.Thread(target=self._run_once_worker, daemon=True).start()

    def _run_once_worker(self):
        # 打包版：运行自身（app.exe --run，windowed 无控制台）
        # 开发版：conda python main.py（CREATE_NO_WINDOW 隐藏黑框）
        CREATE_NO_WINDOW = 0x08000000
        if getattr(sys, "frozen", False):
            cmd = [sys.executable, "--run"]
        else:
            cmd = [get_env_python(), os.path.join(APP_DIR, "main.py")]
        try:
            subprocess.run(cmd, cwd=APP_DIR, timeout=1800, creationflags=CREATE_NO_WINDOW)
        except Exception as e:
            import traceback

            traceback.print_exc()
        finally:
            self._running = False
            self._refresh_task_state()

    # ---------- 刷新 ----------

    @staticmethod
    def _restyle(widget):
        """强制重新应用 QSS（动态改 objectName 后必须 unpolish/polish 才生效）。"""
        widget.style().unpolish(widget)
        widget.style().polish(widget)
        widget.update()

    def _refresh_task_state(self):
        registered = task_exists()
        self.badge_task.setText("定时任务已注册" if registered else "任务未注册")
        self.badge_task.setObjectName("BadgeGreen" if registered else "BadgeRed")
        # 今日进度：实时从界面列表读取当前好友（增删后立即反映）
        friends = [self.list_friends.item(i).text() for i in range(self.list_friends.count())]
        done = 0
        today = datetime.date.today().isoformat()
        st_path = os.path.join(APP_DIR, "data", "state.json")
        if os.path.exists(st_path):
            try:
                with open(st_path, encoding="utf-8") as f:
                    st = json.load(f) or {}  # state.json 是 JSON，勿用 yaml 解析
                done = sum(1 for name in friends if (st.get(name) or "")[:10] == today)
            except Exception:
                pass
        self.badge_today.setText(f"今日 {done}/{len(friends)}" if friends else "未配置好友")
        self.badge_today.setObjectName("BadgeGreen" if friends and done == len(friends) else "BadgeRed")
        self._restyle(self.badge_task)
        self._restyle(self.badge_today)
        # 登录状态：检测进行中保持转圈动效；否则按标记落定显示
        if not getattr(self, "_login_checking", False):
            self._settle_login_badge()

    def _refresh_log(self):
        text = tail_log(LOG_PATH)
        if not text:
            return
        if text == self._last_log_text:
            return
        self._last_log_text = text
        self.log_view.setPlainText(text)
        sb = self.log_view.verticalScrollBar()
        sb.setValue(sb.maximum())

    def closeEvent(self, event):
        # 关闭窗口仅退出界面，不影响已注册任务
        self.timer_log.stop()
        self.timer_task.stop()
        event.accept()


# 单实例共享内存句柄（保持引用，防止被 GC 回收导致锁失效）
_SHARED_MEM = None


def main():
    # 仅最小化控制台窗口（黑框缩到任务栏），GUI 主窗口正常显示
    try:
        import ctypes

        hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        if hwnd:
            ctypes.windll.user32.ShowWindow(hwnd, 6)  # SW_MINIMIZE
    except Exception:
        pass

    app = QApplication(sys.argv)
    app.setFont(QFont("Microsoft YaHei", 14))

    # 单实例：必须在 QApplication 创建之后（QSharedMemory 依赖 QCoreApplication）
    # 重复启动时激活已有窗口并退出，不允许多开
    from PyQt5.QtCore import QSharedMemory

    global _SHARED_MEM
    try:
        _SHARED_MEM = QSharedMemory("DY_SparkAutoKeeper_singleton")
        if not _SHARED_MEM.create(1):
            try:
                import ctypes

                hwnd = ctypes.windll.user32.FindWindowW(None, "DY_SparkAutoKeeper")
                if hwnd:
                    ctypes.windll.user32.ShowWindow(hwnd, 9)  # SW_RESTORE
                    ctypes.windll.user32.SetForegroundWindow(hwnd)
            except Exception:
                pass
            sys.exit(0)
    except Exception:
        # 单实例检测异常时保守退出，避免多开
        sys.exit(0)

    win = SparkGUI()
    win.show()
    # 公告每天首次进入显示一次：标记文件记录"今天已看过"，当天不再弹，次日首次进入再弹
    notice_file = os.path.join(APP_DIR, "data", "notice_agreed.txt")
    today = datetime.date.today().isoformat()
    show_notice = True
    try:
        with open(notice_file, encoding="utf-8") as f:
            show_notice = f.read().strip() != today
    except Exception:
        show_notice = True
    if show_notice:
        dlg = NoticeDialog(win)
        if dlg.exec_() != QDialog.Accepted:
            sys.exit(0)
        try:
            os.makedirs(os.path.dirname(notice_file), exist_ok=True)
            with open(notice_file, "w", encoding="utf-8") as f:
                f.write(today)
        except Exception:
            pass
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()

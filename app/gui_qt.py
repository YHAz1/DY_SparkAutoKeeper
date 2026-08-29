"""自动续火花 · 设置面板（PyQt5）

独立于任务运行：关闭此窗口不影响已注册的定时任务/开机自启。
功能：好友管理、发送设置、高级设置、自启任务管理、手动运行、实时日志。
风格：暖白 + 杏橙，圆角卡片，微软雅黑。
"""
import os
import re
import subprocess
import sys
import tempfile
import threading
import datetime
import json
import time

from PyQt5.QtCore import Qt, QTimer, QUrl
from PyQt5.QtGui import QFont, QDesktopServices, QColor
from PyQt5.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFrame,
    QGraphicsDropShadowEffect,
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
from version import VERSION

# 隐藏子进程控制台窗口（防止 schtasks/powershell 等闪现黑框）
CREATE_NO_WINDOW = 0x08000000

USAGE_TEXT = """【使用说明】
1. 首次使用：未登录时点状态区的「扫码登录」按钮，在弹出的浏览器中扫码登录你的账号；登录态保存在本机，之后自动复用
2. 好友列表：填入你对该好友的备注（需与对方有私信记录，会话列表可见）
3. 发送设置：每日发送时间（HH:MM，如 09:00）；发送内容默认 [续火花吧]，输入后自动转为火花表情
4. 点击「注册自启任务」：开机登录自动检查（完成即退出 / 未到点等待 / 错过补发），每日定时发送
5. 远程提醒（可选）：在「远程提醒」卡片粘贴企业微信群机器人 Webhook 地址；每晚检查若当天未发送
   成功，先自动补发一次，仍失败则在群里推送提醒（发送失败也会立即推送）
6. 运行日志：实时查看每次发送结果（app/logs/app.log）

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
QWidget { font-family: "Microsoft YaHei UI", "Microsoft YaHei"; font-size: 17px; color: #4A4238; }
QMainWindow, #MainRoot { background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #FDFBF7, stop:1 #F5EEE3); }
QFrame#Card { background: #FFFFFF; border-radius: 16px; border: 1px solid #F1E7D9; }
QLabel#CardTitle { font-size: 20px; font-weight: 600; color: #A9602E; }
QLabel#Hint { color: #A89B8B; font-size: 15px; }
QPushButton {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #F19A5D, stop:1 #E07F3C);
    color: #FFFFFF; border: none; border-radius: 11px;
    padding: 12px 28px; font-size: 17px; font-weight: 600;
}
QPushButton:hover { background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #E88F4F, stop:1 #D67433); }
QPushButton:pressed { background: #C9672C; }
QPushButton:disabled { background: #EBD5BE; color: #FFFFFF; }
QPushButton#Ghost {
    background: #FFFFFF; color: #B06A3B; border: 1px solid #E8CDB2; font-weight: normal;
}
QPushButton#Ghost:hover { background: #FBF2E7; }
QPushButton#Danger { background: #E2937A; }
QPushButton#Danger:hover { background: #D97F62; }
QLineEdit {
    background: #FFFEFB; border: 1px solid #EBDFD0; border-radius: 9px;
    padding: 10px 14px; selection-background-color: #F3C9A4; font-size: 17px;
}
QLineEdit:focus { border: 1px solid #E8935A; background: #FFF9F1; }
QListWidget {
    background: #FFFEFB; border: 1px solid #EBDFD0; border-radius: 10px;
    padding: 6px; font-size: 17px;
}
QListWidget::item { padding: 9px 12px; border-radius: 7px; margin: 1px 0; }
QListWidget::item:hover { background: #FBF4EA; }
QListWidget::item:selected { background: #F7E4CF; color: #7A4A22; }
QPlainTextEdit {
    background: #FFFDF9; border: 1px solid #EFE5D6; border-radius: 10px;
    font-family: "Consolas"; font-size: 15px; color: #6B5D4F;
}
QSpinBox {
    background: #FFFEFB; border: 1px solid #EBDFD0; border-radius: 8px;
    padding: 8px 12px; font-size: 17px;
}
QCheckBox { spacing: 9px; font-size: 17px; }
QCheckBox::indicator {
    width: 19px; height: 19px; border-radius: 6px;
    border: 1px solid #DFC4A6; background: #FFFEFB;
}
QCheckBox::indicator:hover { border-color: #E8935A; }
QCheckBox::indicator:checked {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #F19A5D, stop:1 #E07F3C);
    border-color: #E07F3C;
}
QToolButton#FoldBtn { background: transparent; color: #B0764A; border: none; font-weight: 600; font-size: 16px; }
QScrollArea { background: transparent; border: none; }
QScrollArea > QWidget > QWidget { background: transparent; }
QScrollBar:vertical { background: transparent; width: 9px; margin: 2px 0; }
QScrollBar::handle:vertical { background: #E4D7C5; border-radius: 4px; min-height: 28px; }
QScrollBar::handle:vertical:hover { background: #D7C6B0; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
QLabel#BadgeGreen { color: #FFFFFF; background: #74AC74; border-radius: 12px; padding: 7px 19px; font-size: 16px; font-weight: 600; }
QLabel#BadgeRed { color: #FFFFFF; background: #D67F76; border-radius: 12px; padding: 7px 19px; font-size: 16px; font-weight: 600; }
QLabel#BadgeCheck { color: #FFFFFF; background: #DE9A44; border-radius: 12px; padding: 7px 19px; font-size: 16px; font-weight: 600; }
QLabel#GuideCard { background: #FFF6E6; color: #8A5A28; border: 1px solid #F0DDC0; border-radius: 11px; padding: 11px 14px; font-size: 15px; }
QLabel#UpdateCard { background: #FDF0D5; color: #7A4A12; border: 1px solid #E5B04C; border-radius: 11px; padding: 13px 16px; font-size: 16px; font-weight: 600; }
QLabel#AboutText { color: #B7AA9B; font-size: 13px; }
QToolTip { background: #FFF9F1; color: #7A6A58; border: 1px solid #E8D3B8; padding: 6px 8px; font-size: 14px; }
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
        "notify": {
            "webhook_url": "",
            "remind_time": "22:30",
            "auto_resend": True,
            "notify_on_fail": True,
            "mention_all": True,
        },
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
        self._layout.setContentsMargins(18, 14, 18, 15)
        self._layout.setSpacing(8)
        if title:
            # 标题前的小装饰条：给分区一点视觉锚点
            lbl = QLabel(f"<span style='color:#E8935A;'>▎</span>&nbsp;{title}")
            lbl.setObjectName("CardTitle")
            self._layout.addWidget(lbl)
        # 柔和暖色投影：让白卡片从渐变底上轻微"浮起"
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(24)
        shadow.setOffset(0, 5)
        shadow.setColor(QColor(186, 148, 100, 36))
        self.setGraphicsEffect(shadow)

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
        body.setFont(QFont("Microsoft YaHei UI", 16))
        # 内联样式覆盖全局 QSS 的等宽字体，公告正文用正文字体更协调
        body.setStyleSheet(
            "QPlainTextEdit { background:#FFFFFF; border:1px solid #F0E6D8; "
            "font-family:'Microsoft YaHei UI'; font-size:17px; color:#5A4F42; }")
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
        upd.init_debug_log(os.path.join(APP_DIR, "data", "update_debug.log"))
        self._updating = False
        self._remote_version = None
        self._remote_done = False
        self._check_gen = 0
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
        self._build_notify_card()
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
        self.badge_login = QLabel("未登录")
        self.badge_login.setObjectName("BadgeRed")
        self.badge_login.setAlignment(Qt.AlignCenter)
        self.badge_login.setToolTip("登录状态来自最近一次成功登录的记录；未登录时可点旁边「扫码登录」按钮")
        row.addWidget(self.badge_login)
        self.badge_task = QLabel("任务未注册")
        self.badge_task.setObjectName("BadgeRed")
        self.badge_task.setAlignment(Qt.AlignCenter)
        row.addWidget(self.badge_task)
        self.badge_today = QLabel("今日未发送")
        self.badge_today.setObjectName("BadgeRed")
        self.badge_today.setAlignment(Qt.AlignCenter)
        row.addWidget(self.badge_today)
        # 未登录时显示的专用登录按钮（只执行扫码登录，成功后自动消失）
        self.btn_login = QPushButton("扫码登录")
        self.btn_login.setObjectName("Ghost")
        self.btn_login.setToolTip("只执行登录：弹出浏览器扫码，成功后此按钮自动消失")
        self.btn_login.clicked.connect(self._run_login_once)
        self.btn_login.setVisible(False)
        row.addWidget(self.btn_login)
        row.addStretch(1)
        self.lbl_last = QLabel("上次运行：—")
        self.lbl_last.setObjectName("Hint")
        row.addWidget(self.lbl_last)
        c.body().addLayout(row)

        # 新手引导条：从未成功登录过时显示，登录成功后自动消失
        self.guide = QLabel(
            "🧭 新手引导：① 点「扫码登录」完成登录  →  ② 添加好友备注  →  "
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

    def _build_notify_card(self):
        c = self._card("远程提醒（企业微信群机器人）")
        v = c.body()

        row = QHBoxLayout()
        row.addWidget(QLabel("每晚检查时间"))
        self.edit_remind_time = QLineEdit()
        self.edit_remind_time.setPlaceholderText("如 22:30")
        self.edit_remind_time.setFixedWidth(110)
        row.addWidget(self.edit_remind_time)
        row.addStretch(1)
        v.addLayout(row)

        self.edit_webhook = QLineEdit()
        self.edit_webhook.setPlaceholderText(
            "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=…（留空=不推送）")
        v.addWidget(self.edit_webhook)

        self.chk_auto_resend = QCheckBox("晚间检查时先自动补发一次（当天错过也能抢救）")
        self.chk_auto_resend.setChecked(True)
        v.addWidget(self.chk_auto_resend)
        self.chk_notify_fail = QCheckBox("当天发送最终失败时立即推送通知")
        self.chk_notify_fail.setChecked(True)
        v.addWidget(self.chk_notify_fail)
        self.chk_mention_all = QCheckBox("提醒消息在群里 @所有人")
        self.chk_mention_all.setChecked(True)
        v.addWidget(self.chk_mention_all)

        hint_n = QLabel(
            "获取方式：企业微信群 → 右键群 → 添加群机器人 → 查看机器人 → 复制 Webhook 地址。\n"
            "逻辑：每晚「检查时间」若今天还没发送成功 → 先自动补发，仍失败才推送群提醒；"
            "发送任务最终失败时也会立即推送。检查时间要晚于发送时间最大可能值"
            "（随机区间上限 22:00，建议 22:00 以后，默认 22:30）。保存后需重新注册自启任务生效。")
        hint_n.setObjectName("Hint")
        hint_n.setWordWrap(True)
        v.addWidget(hint_n)

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
        hint = QLabel("注册后：开机登录自动检查（完成即退出 / 未到点等待 / 错过补发）+ 每日定时兜底"
                      "+ 每晚提醒检查（未发成功先自动补发，再推企业微信群提醒，见「远程提醒」卡片）。")
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
        n = self.cfg.get("notify", {})
        self.edit_remind_time.setText(str(n.get("remind_time", "22:30")))
        self.edit_webhook.setText(str(n.get("webhook_url", "") or ""))
        self.chk_auto_resend.setChecked(bool(n.get("auto_resend", True)))
        self.chk_notify_fail.setChecked(bool(n.get("notify_on_fail", True)))
        self.chk_mention_all.setChecked(bool(n.get("mention_all", True)))

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
        cfg["notify"] = {
            "webhook_url": self.edit_webhook.text().strip(),
            "remind_time": self.edit_remind_time.text().strip() or "22:30",
            "auto_resend": bool(self.chk_auto_resend.isChecked()),
            "notify_on_fail": bool(self.chk_notify_fail.isChecked()),
            "mention_all": bool(self.chk_mention_all.isChecked()),
        }
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
        rnorm = self._normalize_time(self.edit_remind_time.text())
        if not rnorm:
            QMessageBox.warning(
                self,
                "提醒时间格式错误",
                f"无法识别的提醒时间输入:{self.edit_remind_time.text().strip()!r}\n"
                "小时 0-23、分钟 0-59，例如 22:30。\n"
                "提醒时间应晚于发送时间最大可能值（随机区间上限 22:00）。",
            )
            return False
        self.edit_remind_time.setText(rnorm)
        webhook = self.edit_webhook.text().strip()
        if webhook and not webhook.lower().startswith(("http://", "https://")):
            QMessageBox.warning(
                self, "Webhook 地址不合法",
                "Webhook 地址应以 https:// 开头。\n"
                "企业微信机器人地址形如：\n"
                "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=…")
            return False
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
        self._check_gen += 1; threading.Thread(target=self._check_update_worker, args=(self._check_gen,), daemon=True).start()


    def _check_update_worker(self, gen: int):
        """后台线程：拉取远端版本号。gen 为本次检测代号，
        期间用户再次触发检测会使代号递增，旧线程结果作废不写入。"""
        ver = upd.fetch_remote_version()
        if gen != getattr(self, "_check_gen", 0):
            return
        if ver:
            self._remote_version = ver
            try:
                os.makedirs(os.path.dirname(self._UPDATE_MARK), exist_ok=True)
                with open(self._UPDATE_MARK, "w", encoding="utf-8") as f:
                    json.dump({"last": datetime.date.today().isoformat()}, f)
            except Exception:  # noqa: BLE001
                pass
        self._remote_done = True

    def _begin_wait_remote(self):
        self.btn_check_update.setText("检测中…")
        self.btn_check_update.setEnabled(False)
        self._wait_deadline = time.time() + 45
        self.timer_uwait = QTimer(self)
        self.timer_uwait.timeout.connect(self._poll_remote)
        self.timer_uwait.start(300)

    def _poll_remote(self):
        if not self._remote_done and time.time() < getattr(self, "_wait_deadline", 0):
            return
        t = getattr(self, "timer_uwait", None)
        if t is not None:
            t.stop()
        # 超时未完成且未重试过 → 静默自动重试一次（网络抖动容错）
        if not self._remote_done and not getattr(self, "_retried", False) \
                and not self._updating and not self._running:
            self._retried = True
            threading.Thread(target=self._check_update_worker,
                             args=(getattr(self, "_check_gen", 0),), daemon=True).start()
            self._wait_deadline = time.time() + 45
            return
        self._retried = False
        self.btn_check_update.setText("检查更新")
        self.btn_check_update.setEnabled(True)
        ver = self._remote_version
        timed_out = not self._remote_done
        if ver and upd.is_newer(ver, VERSION):
            self.lbl_update.setText(
                f"发现新版本 v{ver}（当前 v{VERSION}）· 点击此处立即下载并自动更新")
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
        self._check_gen = getattr(self, "_check_gen", 0) + 1
        gen = self._check_gen
        self._remote_version = None
        self._remote_done = False
        self._retried = False
        self._manual_pending = True
        threading.Thread(target=self._check_update_worker, args=(gen,), daemon=True).start()
        self._begin_wait_remote()

    # 下载源：(模式, 显示名)。mode 为 "auto"/"proxy"/镜像前缀
    _UPDATE_SOURCES = [
        ("auto", "自动（推荐：镜像优先，慢速自动换源）"),
        ("proxy", "系统代理（直连 GitHub 并走系统代理）"),
        ("https://gh.dpik.top/", "镜像 gh.dpik.top"),
        ("https://gh-proxy.com/", "镜像 gh-proxy.com"),
        ("https://cdn.gh-proxy.com/", "镜像 cdn.gh-proxy.com"),
    ]
    _UPDATE_SOURCE_MARK = os.path.join(APP_DIR, "data", "update_source.json")

    def _pick_update_source(self) -> "str | None":
        """下载源选择对话框，记住上次选择；取消返回 None。"""
        dlg = QDialog(self)
        dlg.setWindowTitle("选择下载源")
        lay = QVBoxLayout(dlg)
        lay.setSpacing(10)
        tip = QLabel("下载慢可随时取消，换一个源重试。\n"
                     "「自动」模式：镜像优先，速度过低会自动切换下一个源，无需手动干预。")
        tip.setObjectName("Hint")
        tip.setWordWrap(True)
        lay.addWidget(tip)
        combo = QComboBox()
        last = "auto"
        try:
            with open(self._UPDATE_SOURCE_MARK, encoding="utf-8") as f:
                last = (json.load(f) or {}).get("last", "auto")
        except Exception:  # noqa: BLE001
            pass
        for i, (mode, label) in enumerate(self._UPDATE_SOURCES):
            combo.addItem(label, mode)
            if mode == last:
                combo.setCurrentIndex(i)
        lay.addWidget(combo)
        row = QHBoxLayout()
        btn_cancel = QPushButton("取消")
        btn_cancel.setObjectName("Ghost")
        btn_ok = QPushButton("下一步")
        row.addStretch(1)
        row.addWidget(btn_cancel)
        row.addWidget(btn_ok)
        lay.addLayout(row)
        btn_ok.clicked.connect(dlg.accept)
        btn_cancel.clicked.connect(dlg.reject)
        if dlg.exec_() != QDialog.Accepted:
            return None
        return combo.currentData()

    def _update_candidates(self, ver: str, mode: str) -> "list | None":
        """按所选模式构造 [(url, proxy), ...] 下载候选。
        mode 为镜像前缀时返回该镜像单候选；系统代理未开启返回 None 由调用方回退自动。"""
        direct = upd.direct_url(ver)
        if mode == "auto":
            cands = [(m + direct, None) for m in (
                "https://gh.dpik.top/", "https://gh-proxy.com/", "https://cdn.gh-proxy.com/")]
            sp = upd.system_proxy()
            if sp:
                cands.append((direct, sp))
            cands.append((direct, None))
            cands.append(("https://ghfast.top/" + direct, None))
            return cands
        if mode == "proxy":
            sp = upd.system_proxy()
            if not sp:
                QMessageBox.information(
                    self, "未检测到系统代理",
                    "系统当前未开启代理（Windows 设置 → 网络和 Internet → 代理）。\n已自动切换为「自动」模式。")
                return self._update_candidates(ver, "auto")
            return [(direct, sp)]
        return [(mode + direct, None)]

    def _start_update_flow(self, mode: "str | None" = None):
        """点击更新横幅：选源 → 确认 → 后台下载（进度条）→ 校验 → 快照用户文件 → 脚本接力更新。"""
        ver = self._remote_version
        if not ver or self._updating:
            return
        if self._running:
            QMessageBox.warning(self, "正在执行任务",
                                "发送任务进行中，无法更新。\n请等待任务结束后再试。")
            return
        if mode is None:
            mode = self._pick_update_source()
            if mode is None:
                return
        ret = QMessageBox.question(
            self, "应用更新",
            f"将下载 v{ver} 更新包（约 384MB），完成后会自动：\n"
            "  · 关闭本程序与浏览器\n"
            "  · 覆盖安装新版本（好友/时间/登录态/记录全部保留）\n"
            "  · 自动重新启动程序\n\n"
            "现在开始吗？（下载慢可随时取消并更换下载源）",
            QMessageBox.Yes | QMessageBox.No,
        )
        if ret != QMessageBox.Yes:
            return

        try:
            os.makedirs(os.path.dirname(self._UPDATE_SOURCE_MARK), exist_ok=True)
            with open(self._UPDATE_SOURCE_MARK, "w", encoding="utf-8") as f:
                json.dump({"last": mode}, f)
        except Exception:  # noqa: BLE001
            pass

        self._updating = True
        self.lbl_update.setVisible(False)
        dest_dir = os.path.join(tempfile.gettempdir(), "DY_SparkAutoKeeper_update")
        dest = os.path.join(dest_dir, f"DY_SparkAutoKeeper_v{ver}_win64.zip")
        state = {"done": 0, "total": 0, "cancel": False}

        dlg = QProgressDialog("正在连接下载源…", "取消", 0, 1, self)
        dlg.setWindowTitle("软件自更新")
        dlg.setWindowModality(Qt.NonModal)
        dlg.setMinimumDuration(0)
        dlg.setAutoClose(False)
        dlg.resize(420, 90)

        candidates = self._update_candidates(ver, mode)

        def worker():
            def on_progress(done, total):
                state["done"], state["total"] = done, total
                return not state["cancel"]

            ok = False
            try:
                ok = upd.download(candidates, dest, progress=on_progress,
                                  auto_switch=(mode == "auto")) is not None
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
            box = QMessageBox(self)
            box.setWindowTitle("下载失败")
            box.setText("下载失败或已取消。\n可以换一个下载源重试，或到发布页手动下载。")
            btn_retry = box.addButton("换个源重试", QMessageBox.YesRole)
            btn_web = box.addButton("打开下载页", QMessageBox.NoRole)
            box.addButton("取消", QMessageBox.RejectRole)
            box.exec_()
            clicked = box.clickedButton()
            if clicked is btn_retry:
                self._start_update_flow()
            elif clicked is btn_web:
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
            self.badge_login.setToolTip("尚未检测到登录记录；点上方「扫码登录」按钮登录")
        self.badge_login.setText("已登录" if logged else "未登录")
        self._restyle(self.badge_login)
        # 未登录时露出「扫码登录」按钮；已登录（或检测中）隐藏
        if hasattr(self, "btn_login"):
            self.btn_login.setVisible(not logged)
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
        rt = self.cfg.get("notify", {}).get("remind_time", "22:30")
        try:
            r = subprocess.run(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                 "-File", PS_SCRIPT, "-Time", t, "-RemindTime", rt],
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
            (f"已注册开机自启 + 每日 {t} 定时任务（错过自动补发）\n"
             f"每晚 {rt} 提醒检查：未发送成功先自动补发，仍失败推送企业微信提醒" if ok
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

    def _run_login_once(self):
        """「扫码登录」按钮：只执行登录任务（--login），成功后按钮自动消失。"""
        if getattr(self, "_login_running", False) or self._running:
            return
        self._login_running = True
        self.btn_login.setText("登录中…")
        self.btn_login.setEnabled(False)
        threading.Thread(target=self._run_login_worker, daemon=True).start()

    def _run_login_worker(self):
        CREATE_NO_WINDOW = 0x08000000
        if getattr(sys, "frozen", False):
            cmd = [sys.executable, "--login"]
        else:
            cmd = [get_env_python(), os.path.join(APP_DIR, "main.py"), "--login"]
        try:
            # 上限 7 分钟：浏览器启动 + 等网络 + 180s 扫码窗口
            subprocess.run(cmd, cwd=APP_DIR, timeout=420, creationflags=CREATE_NO_WINDOW)
        except Exception:
            import traceback

            traceback.print_exc()
        finally:
            self._login_running = False
            self.btn_login.setText("扫码登录")
            self.btn_login.setEnabled(True)
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
            # 上限 60 分钟：网络等待 + 发送 + 失败重试窗口都算在内
            subprocess.run(cmd, cwd=APP_DIR, timeout=3600, creationflags=CREATE_NO_WINDOW)
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
    app.setFont(QFont("Microsoft YaHei UI", 10))

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

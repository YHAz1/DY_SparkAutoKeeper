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

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QFont
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
    QPushButton,
    QScrollArea,
    QSpinBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

import yaml


def _app_dir() -> str:
    """程序数据目录：打包后为 exe 所在目录，开发时为脚本目录。"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


APP_DIR = _app_dir()
CONFIG_PATH = os.path.join(APP_DIR, "config.yaml")
LOG_PATH = os.path.join(APP_DIR, "logs", "app.log")
TASK_NAME = "DYSparkAutoKeeper"
PS_SCRIPT = os.path.join(APP_DIR, "scripts", "register_task.ps1")
VERSION = "1.0.1"

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
QLabel#AboutText { color: #B5A99B; font-size: 14px; }
"""


# ---------------- 工具函数 ----------------

def load_config() -> dict:
    default = {
        "send_time": "09:00",
        "friends": [],
        "message": {"text": "[续火花吧]", "search_friend": False},
        "delays": {"min": 1.5, "max": 3.5},
        "retry": {"max_attempts": 3, "interval_sec": 10},
        "browser": {"headless": False, "gpu": True, "profile_dir": "data/profile", "login_timeout_sec": 180},
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
        self._refresh_task_state()
        self._refresh_log()

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
        row.addStretch(1)
        self.lbl_last = QLabel("上次运行：—")
        self.lbl_last.setObjectName("Hint")
        row.addWidget(self.lbl_last)
        c.body().addLayout(row)

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
        row1.addStretch(1)
        grid.addLayout(row1)
        hint1 = QLabel("格式：HH:MM（24 小时制，如 09:00 / 23:30）。保存后需重新注册自启任务生效。")
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
        self.chk_headless = QCheckBox("无头模式（隐藏浏览器窗口；不推荐，风控更高）")
        v.addWidget(self.chk_headless)

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
        """固定页脚：版本号 + 免责声明（始终可见），右下角署名。"""
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet("color: #F0E6DA;")
        outer.addWidget(line)
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
        self.chk_headless.setChecked(bool(self.cfg.get("browser", {}).get("headless", False)))

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
        cfg["browser"]["headless"] = bool(self.chk_headless.isChecked())
        return cfg

    def _save_ui_config(self) -> bool:
        """校验并保存配置。"""
        t = self.edit_time.text().strip()
        if not re.fullmatch(r"([01]?\d|2[0-3]):[0-5]\d", t):
            QMessageBox.warning(self, "时间格式错误", "发送时间格式应为 HH:MM，例如 09:00")
            return False
        self._collect_config()
        if save_config(self.cfg):
            return True
        QMessageBox.warning(self, "保存失败", "无法写入 config.yaml")
        return False

    # ---------- 事件 ----------

    def _add_friend(self):
        name = self.edit_friend.text().strip()
        if not name:
            return
        existing = [self.list_friends.item(i).text() for i in range(self.list_friends.count())]
        if name not in existing:
            self.list_friends.addItem(name)
        self.edit_friend.clear()
        self._refresh_task_state()

    def _del_friend(self):
        row = self.list_friends.currentRow()
        if row >= 0:
            self.list_friends.takeItem(row)
            self._refresh_task_state()

    def _register_task(self):
        if not self._save_ui_config():
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
            subprocess.run(cmd, cwd=APP_DIR, timeout=900, creationflags=CREATE_NO_WINDOW)
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
                    st = yaml.safe_load(f) or {}
                done = sum(1 for name in friends if (st.get(name) or "")[:10] == today)
            except Exception:
                pass
        self.badge_today.setText(f"今日 {done}/{len(friends)}" if friends else "未配置好友")
        self.badge_today.setObjectName("BadgeGreen" if friends and done == len(friends) else "BadgeRed")
        self._restyle(self.badge_task)
        self._restyle(self.badge_today)

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

    # 单实例：重复启动时激活已有窗口并退出，不允许多开
    from PyQt5.QtCore import QSharedMemory

    global _SHARED_MEM
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

    app = QApplication(sys.argv)
    app.setFont(QFont("Microsoft YaHei", 14))
    win = SparkGUI()
    win.show()
    # 打开时弹公告（使用说明 + 免责声明）：同意进入，不同意则退出
    dlg = NoticeDialog(win)
    if dlg.exec_() != QDialog.Accepted:
        sys.exit(0)
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()

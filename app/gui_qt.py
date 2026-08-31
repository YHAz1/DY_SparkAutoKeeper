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

from PyQt5.QtCore import Qt, QTimer, QUrl, pyqtSignal, QVariantAnimation, QRectF
from PyQt5.QtGui import (QFont, QDesktopServices, QColor, QIcon, QFontMetrics, QPainter, QPainterPath,
                         QConicalGradient, QPen)
from PyQt5.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFrame,
    QGridLayout,
    QGraphicsDropShadowEffect,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
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


def _app_icon() -> QIcon:
    """应用火花图标：PNG 优先（不依赖 qico 插件），ico 兜底。
    覆盖开发目录、打包 _internal 与 _MEIPASS 三处位置。"""
    base = [APP_DIR, os.path.join(APP_DIR, "_internal")]
    if getattr(sys, "_MEIPASS", ""):
        base.append(sys._MEIPASS)
    for name in ("SparkAK.png", "SparkAK.ico"):
        for d in base:
            _p = os.path.join(d, name)
            if os.path.exists(_p):
                return QIcon(_p)
    return QIcon()

USAGE_TEXT = """【使用说明】
1. 首次使用：未登录时点状态区的「扫码登录」按钮，在弹出的浏览器中扫码登录你的账号；登录态保存在本机，之后自动复用
2. 好友列表：填入你对该好友的备注（需与对方有私信记录，会话列表可见）
3. 发送设置：每日发送时间（HH:MM，如 09:00）；发送内容默认 [续火花吧]，输入后自动转为火花表情
4. 点击「注册自启任务」：开机登录自动检查（完成即退出 / 未到点等待 / 错过补发），每日定时发送
5. 远程提醒（可选）：在「远程提醒」卡片粘贴企业微信群机器人 Webhook 地址；发送成功、失败或晚间
   补发都会按开关推送到群里。点「推送设置」可指定要 @ 的群成员（已取消 @所有人）
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
QWidget { font-family: "Microsoft YaHei UI", "Microsoft YaHei"; font-size: 18px; color: #453D33; }
QMainWindow, #MainRoot { background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #FBF8F2, stop:1 #F2EBDF); }
#Header { background: #FFFDF9; border-bottom: 1px solid #EFE4D4; }
QScrollArea { background: transparent; border: none; }
QScrollArea > QWidget > QWidget { background: transparent; }
QLabel#AppTitle { font-size: 20px; font-weight: 700; color: #6B5843; }
QLabel#AppVer { font-size: 13px; color: #B9AC9C; }
QFrame#Card { background: #FFFFFF; border-radius: 12px; border: 1px solid #EFE6D8; }
QLabel#CardTitle { font-size: 17px; font-weight: 600; color: #9A7B54; }
QLabel#Hint { color: #A89B8B; font-size: 15px; }
QPushButton {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #F19A5D, stop:1 #E07F3C);
    color: #FFFFFF; border: none; border-radius: 9px;
    padding: 10px 22px; font-size: 17px; font-weight: 600;
}
QPushButton:hover { background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #E88F4F, stop:1 #D67433); }
QPushButton:pressed { background: #C9672C; }
QPushButton:disabled { background: #EBD5BE; color: #FFFFFF; }
QPushButton#Ghost {
    background: #FFFFFF; color: #A9682F; border: 1px solid #E4C8A8; font-weight: 600;
}
QPushButton#Ghost:hover { background: #FBF2E7; }
QPushButton#Danger { background: #E2937A; }
QPushButton#Danger:hover { background: #D97F62; }
QProgressBar#DlBar {
    background: #F0E4D4; border: none; border-radius: 7px;
}
QProgressBar#DlBar::chunk {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #F19A5D, stop:1 #E07F3C);
    border-radius: 7px;
}
QLineEdit {
    background: #FFFEFB; border: 1px solid #E7DACA; border-radius: 8px;
    padding: 8px 12px; selection-background-color: #F3C9A4; font-size: 18px;
}
QLineEdit:focus { border: 1px solid #E8935A; background: #FFF9F1; }
QListWidget {
    background: #FFFEFB; border: 1px solid #E7DACA; border-radius: 8px;
    padding: 6px; font-size: 18px;
}
QListWidget::item { padding: 7px 10px; border-radius: 6px; }
QListWidget::item:hover { background: #FBF4EA; }
QListWidget::item:selected { background: #F7E4CF; color: #7A4A22; }
QPlainTextEdit {
    background: #FFFEFB; border: 1px solid #EDE3D3; border-radius: 8px;
    font-family: "Consolas"; font-size: 15px; color: #6B5D4F;
}
QSpinBox {
    background: #FFFEFB; border: 1px solid #E7DACA; border-radius: 7px;
    padding: 8px 12px; font-size: 18px;
}
QCheckBox { spacing: 8px; font-size: 18px; }
QCheckBox::indicator {
    width: 18px; height: 18px; border-radius: 5px;
    border: 1px solid #DFC4A6; background: #FFFEFB;
}
QCheckBox::indicator:hover { border-color: #E8935A; }
QCheckBox::indicator:checked {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #F19A5D, stop:1 #E07F3C);
    border-color: #E07F3C;
}
QToolButton#FoldBtn { background: transparent; color: #A9682F; border: none; font-weight: 600; font-size: 16px; }
QToolButton#TestBtn { background: #FFF6E9; color: #A9682F; border: 1px solid #F0DDC0; border-radius: 8px; padding: 4px 6px; font-size: 14px; font-weight: 600; }
QToolButton#TestBtn:hover { background: #FBEBD5; border-color: #E8935A; }
QToolButton#TestBtn:disabled { color: #BCAE9B; background: #FAF6F0; border-color: #EDE3D5; }
QLabel#BadgeGreen { color: #FFFFFF; background: #74AC74; border-radius: 12px; padding: 6px 16px; font-size: 15px; font-weight: 600; }
QLabel#BadgeRed { color: #FFFFFF; background: #D67F76; border-radius: 12px; padding: 6px 16px; font-size: 15px; font-weight: 600; }
QLabel#BadgeCheck { color: #FFFFFF; background: #DE9A44; border-radius: 12px; padding: 6px 16px; font-size: 15px; font-weight: 600; }
QLabel#GuideCard { background: #FFF6E6; color: #8A5A28; border: 1px solid #F0DDC0; border-radius: 9px; padding: 11px 14px; font-size: 16px; }
QLabel#UpdateCard { background: #FDF0D5; color: #7A4A12; border: 1px solid #E5B04C; border-radius: 9px; padding: 12px 14px; font-size: 16px; font-weight: 600; }
QLabel#AboutText { color: #A99C8C; font-size: 16px; }
QToolTip { background: #FFF9F1; color: #7A6A58; border: 1px solid #E8D3B8; padding: 6px 8px; font-size: 15px; }
QScrollBar:vertical { background: transparent; width: 8px; margin: 2px 0; }
QScrollBar::handle:vertical { background: #E4D7C5; border-radius: 4px; min-height: 24px; }
QScrollBar::handle:vertical:hover { background: #D7C6B0; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
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
            "notify_on_success": True,
            "mention_names": "",
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


class Toast(QFrame):
    """右下角提示小卡：白底主题风，一道橙光沿边框匀速跑一圈后淡出消失。"""

    _instance = None

    @classmethod
    def show_toast(cls, parent, text: str, kind: str = "info", lap_ms: int = 1900):
        if cls._instance is not None:
            try:
                cls._instance.close()
            except Exception:  # noqa: BLE001
                pass
        t = cls(parent, text, kind, lap_ms)
        cls._instance = t
        return t

    def __init__(self, parent, text: str, kind: str, lap_ms: int):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self._angle = 0.0
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 8, 16, 8)
        icon = {"ok": "✅ ", "warn": "⚠️ ", "info": "💡 "}.get(kind, "")
        self.lbl = QLabel(icon + text)
        self.lbl.setWordWrap(True)
        self.lbl.setStyleSheet("color: #3E362C; font-size: 17px; background: transparent;")
        lay.addWidget(self.lbl)
        text_w = QFontMetrics(self.lbl.font()).horizontalAdvance(self.lbl.text())
        self.setFixedWidth(max(230, min(760, text_w + 46)))  # 单行宽度自适应，超长自然折行
        self.adjustSize()
        # 与「检查更新」按钮等高、放在其左侧；无锚点时回退右下角
        anchor = getattr(parent, "btn_check_update", None)
        if anchor is not None:
            pos = anchor.mapTo(parent, anchor.rect().topLeft())
            bh = anchor.height()
            self.move(max(12, pos.x() - self.width() - 10),        # 右边缘贴按钮左侧 10px
                      pos.y() + (bh - self.height()) // 2)          # 垂直居中对齐按钮（单行≈等高）
        else:
            pw, ph = parent.width(), parent.height()
            self.move(max(12, pw - self.width() - 26), max(12, ph - self.height() - 58))
        self.show()
        self.raise_()
        # 单圈慢转：QVariantAnimation 帧间平滑插值，转完自动淡出消失
        lap = QVariantAnimation(self)
        lap.setStartValue(0.0)
        lap.setEndValue(360.0)
        lap.setDuration(max(600, int(lap_ms)))
        lap.valueChanged.connect(self._on_lap)
        lap.finished.connect(self._fade)
        lap.start()
        self._lap = lap
        self._anim = None  # 淡出动画引用，防 GC

    def _on_lap(self, v):
        self._angle = float(v)
        self.update()

    def _fade(self):
        eff = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(eff)
        anim = QVariantAnimation(self)
        anim.setStartValue(1.0)
        anim.setEndValue(0.0)
        anim.setDuration(300)
        anim.valueChanged.connect(eff.setOpacity)
        anim.finished.connect(self.close)
        anim.start()
        self._anim = anim  # 保引用防 GC

    def paintEvent(self, e):
        pa = QPainter(self)
        pa.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(3, 3, -3, -3)
        path = QPainterPath()
        path.addRoundedRect(r, 12, 12)
        # 白底主题色卡片 + 细边
        pa.fillPath(path, QColor(255, 255, 255, 248))
        pa.setPen(QPen(QColor(238, 224, 204, 255), 1))
        pa.drawPath(path)
        # 一道橙光沿边框跑（锥形渐变亮弧随角度旋转）
        g = QConicalGradient(self.rect().center(), -self._angle)
        g.setColorAt(0.00, QColor(232, 147, 90, 0))
        g.setColorAt(0.70, QColor(232, 147, 90, 0))
        g.setColorAt(0.84, QColor(255, 190, 130, 190))
        g.setColorAt(0.92, QColor(224, 127, 60, 255))
        g.setColorAt(1.00, QColor(232, 147, 90, 0))
        pa.setPen(QPen(g, 3))
        pa.drawPath(path)
        pa.end()


# ---------------- 主窗口 ----------------

class SparkGUI(QMainWindow):
    # 跨线程 UI 更新：工作线程只 emit 信号，槽在主线程执行（Qt 跨线程自动排队）
    sig_refresh_task = pyqtSignal()
    sig_login_settle = pyqtSignal()
    sig_login_reset = pyqtSignal()
    sig_update_found = pyqtSignal()
    sig_test_push_done = pyqtSignal(bool)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("DY_SparkAutoKeeper")  # 标题不可改：单实例激活依赖窗口名查找
        _app_icon() and self.setWindowIcon(_app_icon())
        self.setFixedSize(1400, 950)  # 固定尺寸（宽多高少）：不允许最大化/拉伸，保证版式始终协调
        self.setStyleSheet(QSS)

        self.cfg = load_config()
        self._running = False

        self.sig_refresh_task.connect(self._refresh_task_state)
        self.sig_login_settle.connect(self._settle_login_badge)
        self.sig_login_reset.connect(self._on_login_worker_done)
        self.sig_update_found.connect(self._on_update_found)
        self.sig_test_push_done.connect(self._on_test_push_done)

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
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # 顶栏：品牌 + 状态徽章（平铺，非卡片）
        outer.addWidget(self._build_header())

        # 新手引导条：未登录时显示在顶栏正下方
        guide_wrap = QWidget()
        gw = QHBoxLayout(guide_wrap)
        gw.setContentsMargins(18, 10, 18, 0)
        self.guide = QLabel(
            "🧭 新手引导：① 点右上「扫码登录」完成登录  →  ② 添加好友备注  →  "
            "③ 设定每日发送时间  →  ④ 点「注册自启任务」。登录成功后本提示自动消失。"
        )
        self.guide.setObjectName("GuideCard")
        self.guide.setWordWrap(True)
        self.guide.setAlignment(Qt.AlignCenter)
        gw.addWidget(self.guide)
        outer.addWidget(guide_wrap)
        self.guide.setVisible(False)

        # 双栏内容：左＝好友 + 日志；右＝设置组
        body = QWidget()
        bl = QHBoxLayout(body)
        bl.setContentsMargins(18, 12, 18, 12)
        bl.setSpacing(14)

        # 滚动安全网：窗口过矮时内容滚动而非被压缩截断
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        col_l = QVBoxLayout()
        col_l.setSpacing(14)
        col_r = QVBoxLayout()
        col_r.setSpacing(14)

        self._build_friends_card(col_l)
        self._build_log_card(col_l)
        self._build_send_card(col_r)
        self._build_notify_card(col_r)
        self._build_task_card(col_r)
        self._build_advanced_card(col_r)
        col_r.addStretch(1)

        bl.addLayout(col_l, 11)
        bl.addLayout(col_r, 9)
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)

        # 页脚：更新横幅 + 版本/免责声明
        self._build_about(outer)

    def _card(self, title: str, col: QVBoxLayout, stretch: int = 0) -> Card:
        c = Card(title)
        col.addWidget(c, stretch)
        return c

    def _badge(self, text: str, tip: str = "") -> QLabel:
        b = QLabel(text)
        b.setObjectName("BadgeRed")
        b.setAlignment(Qt.AlignCenter)
        if tip:
            b.setToolTip(tip)
        return b

    def _build_header(self) -> QWidget:
        h = QWidget()
        h.setObjectName("Header")
        lay = QHBoxLayout(h)
        lay.setContentsMargins(18, 11, 18, 11)
        lay.setSpacing(8)
        title = QLabel("自动续火花")
        title.setObjectName("AppTitle")
        lay.addWidget(title)
        ver = QLabel(f"v{VERSION}")
        ver.setObjectName("AppVer")
        lay.addWidget(ver)
        lay.addStretch(1)
        self.badge_login = self._badge("未登录", "登录状态来自最近一次成功登录的记录")
        lay.addWidget(self.badge_login)
        self.badge_task = self._badge("任务未注册")
        lay.addWidget(self.badge_task)
        self.badge_today = self._badge("今日未发送")
        lay.addWidget(self.badge_today)
        # 未登录时显示的专用登录按钮（只执行扫码登录，成功后自动消失）
        self.btn_login = QPushButton("扫码登录")
        self.btn_login.setObjectName("Ghost")
        self.btn_login.setToolTip("只执行登录：弹出浏览器扫码，成功后此按钮自动消失")
        self.btn_login.clicked.connect(self._run_login_once)
        self.btn_login.setVisible(False)
        lay.addWidget(self.btn_login)
        self.lbl_last = QLabel("上次运行：—")
        self.lbl_last.setObjectName("Hint")
        lay.addWidget(self.lbl_last)
        return h

    def _build_friends_card(self, col: QVBoxLayout):
        c = self._card("好友列表", col)
        self.list_friends = QListWidget()
        self.list_friends.setMinimumHeight(150)
        c.body().addWidget(self.list_friends, 1)
        row = QHBoxLayout()
        row.setSpacing(8)
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

    def _build_send_card(self, col: QVBoxLayout):
        c = self._card("发送设置", col)
        grid = QGridLayout()
        grid.setVerticalSpacing(8)
        grid.setHorizontalSpacing(10)

        lbl_t = QLabel("发送时间")
        lbl_t.setMinimumWidth(56)
        grid.addWidget(lbl_t, 0, 0)
        self.edit_time = QLineEdit()
        self.edit_time.setPlaceholderText("如 09:00")
        self.edit_time.setFixedWidth(100)
        grid.addWidget(self.edit_time, 0, 1)
        btn_rand = QPushButton("随机")
        btn_rand.setObjectName("Ghost")
        btn_rand.clicked.connect(self._random_time)
        grid.addWidget(btn_rand, 0, 2)
        grid.setColumnStretch(1, 1)

        lbl_x = QLabel("发送内容")
        lbl_x.setMinimumWidth(56)
        grid.addWidget(lbl_x, 1, 0)
        self.edit_text = QLineEdit()
        self.edit_text.setPlaceholderText("[续火花吧]")
        grid.addWidget(self.edit_text, 1, 1, 1, 2)
        c.body().addLayout(grid)

        hint1 = QLabel("支持自动纠错：9点5 / 930 → 09:05 / 09:30；「随机」在 9:00-22:00 取值。改动后需重新注册任务生效。")
        hint1.setObjectName("Hint")
        hint1.setWordWrap(True)
        c.body().addWidget(hint1)

    def _build_advanced_card(self, col: QVBoxLayout):
        c = self._card("高级设置", col)
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
        row_r.addWidget(QLabel("发送重试次数"))
        self.spin_retry = QSpinBox()
        self.spin_retry.setRange(1, 10)
        row_r.addWidget(self.spin_retry)
        row_r.addStretch(1)
        v.addLayout(row_r)

        self.chk_gpu = QCheckBox("启用 GPU 渲染（流畅；显卡跑模型时可关闭）")
        v.addWidget(self.chk_gpu)
        self.chk_random = QCheckBox("每日任务后自动随机明日发送时间并更新定时任务")
        v.addWidget(self.chk_random)
        hint_r = QLabel("负载避让：发送前自动检查 CPU / 显卡占用，高负载先等待复查，降下来才运行"
                        "（load_gate 配置可调）。关闭 GPU 时浏览器走纯 CPU 软件渲染，完全不碰显卡。")
        hint_r.setObjectName("Hint")
        hint_r.setWordWrap(True)
        v.addWidget(hint_r)

        c.body().addWidget(inner)
        inner.setVisible(False)
        btn_fold.toggled.connect(lambda on: (inner.setVisible(on),
                                             btn_fold.setText("收起设置  ▴" if on else "展开设置  ▾")))

    def _build_notify_card(self, col: QVBoxLayout):
        c = self._card("远程提醒 · 企业微信群机器人", col)
        v = c.body()

        row = QHBoxLayout()
        row.setSpacing(10)
        lbl = QLabel("每晚检查")
        lbl.setMinimumWidth(56)
        row.addWidget(lbl)
        self.edit_remind_time = QLineEdit()
        self.edit_remind_time.setPlaceholderText("如 22:30")
        self.edit_remind_time.setFixedWidth(100)
        row.addWidget(self.edit_remind_time)
        row.addStretch(1)
        v.addLayout(row)

        # Webhook 输入框 + 极小的「测试」标签（同一行，不额外占高度）
        row_w = QHBoxLayout()
        row_w.setSpacing(8)
        self.edit_webhook = QLineEdit()
        self.edit_webhook.setPlaceholderText("https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=…（留空=不推送）")
        row_w.addWidget(self.edit_webhook, 1)
        self.btn_test_push = QToolButton()
        self.btn_test_push.setObjectName("TestBtn")
        self.btn_test_push.setText("测试")
        self.btn_test_push.setFixedWidth(58)
        self.btn_test_push.setToolTip("向该群推一条测试消息，验证 Webhook 与 @成员 是否可用")
        self.btn_test_push.clicked.connect(self._test_push)
        row_w.addWidget(self.btn_test_push)
        v.addLayout(row_w)

        self.chk_auto_resend = QCheckBox("晚间检查时先自动补发一次（当天错过也能抢救）")
        self.chk_auto_resend.setChecked(True)
        v.addWidget(self.chk_auto_resend)

        self.chk_notify_fail = QCheckBox("当天发送最终失败时立即推送通知")
        self.chk_notify_fail.setChecked(True)
        v.addWidget(self.chk_notify_fail)

        # 「推送设置」折叠按钮独占一行：顶替原「@所有人」复选框行，收起时卡片高度与 v1.4.4 完全一致
        btn_fold = QToolButton()
        btn_fold.setObjectName("FoldBtn")
        btn_fold.setText("推送设置  ▾")
        btn_fold.setCheckable(True)
        btn_fold.setChecked(False)
        # 关键：行高动态绑定到复选框实际高度，保证左右两栏底边严丝合缝（差 1px 也会被看出来）
        btn_fold.setMinimumHeight(self.chk_notify_fail.sizeHint().height())
        v.addWidget(btn_fold)

        # 折叠区：成功推送开关 + @成员昵称（仅在展开时占高度）
        inner = QWidget()
        vi = QVBoxLayout(inner)
        vi.setContentsMargins(0, 2, 0, 0)
        vi.setSpacing(8)
        self.chk_notify_success = QCheckBox("每日发送全部成功时也推送通知")
        self.chk_notify_success.setChecked(True)
        vi.addWidget(self.chk_notify_success)

        row_m = QHBoxLayout()
        row_m.setSpacing(8)
        lbl_m = QLabel("群内昵称")
        lbl_m.setMinimumWidth(56)
        row_m.addWidget(lbl_m)
        self.edit_mention = QLineEdit()
        self.edit_mention.setPlaceholderText("你在群里的名字，如：张三（多人用顿号分隔）")
        row_m.addWidget(self.edit_mention, 1)
        vi.addLayout(row_m)

        hint_m = QLabel("推送时 @ 这里填的成员；留空则不 @ 任何人。"
                        "已取消 @所有人，避免打扰群里其他成员。")
        hint_m.setObjectName("Hint")
        hint_m.setWordWrap(True)
        vi.addWidget(hint_m)

        v.addWidget(inner)
        inner.setVisible(False)
        btn_fold.toggled.connect(lambda on: (inner.setVisible(on),
                                             btn_fold.setText("推送设置  ▴" if on else "推送设置  ▾")))

        hint_n = QLabel(
            "获取：企业微信群 → 右键群 → 添加群机器人 → 复制 Webhook 地址。"
            "每晚检查未发送成功先自动补发、仍失败推群提醒；需重新注册任务生效。")
        hint_n.setObjectName("Hint")
        hint_n.setWordWrap(True)
        v.addWidget(hint_n)

    def _build_task_card(self, col: QVBoxLayout):
        c = self._card("定时任务", col)
        row = QHBoxLayout()
        row.setSpacing(8)
        btn_reg = QPushButton("注册自启任务")
        btn_reg.clicked.connect(self._register_task)
        row.addWidget(btn_reg, 1)
        btn_run = QPushButton("立即运行一次")
        btn_run.setObjectName("Ghost")
        btn_run.clicked.connect(self._run_once)
        row.addWidget(btn_run, 1)
        btn_unreg = QPushButton("删除任务")
        btn_unreg.setObjectName("Danger")
        btn_unreg.clicked.connect(self._unregister_task)
        row.addWidget(btn_unreg, 1)
        c.body().addLayout(row)
        hint = QLabel("注册后：开机登录自动检查 + 每日定时兜底 + 每晚提醒检查（未发成功先自动补发，再推企业微信群提醒）。")
        hint.setObjectName("Hint")
        hint.setWordWrap(True)
        c.body().addWidget(hint)

    def _build_log_card(self, col: QVBoxLayout):
        c = self._card("运行日志", col, stretch=1)
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(500)
        self.log_view.setMinimumHeight(140)
        c.body().addWidget(self.log_view, 1)
        row = QHBoxLayout()
        row.setSpacing(8)
        btn_refresh = QPushButton("刷新")
        btn_refresh.setObjectName("Ghost")
        btn_refresh.clicked.connect(self._refresh_log)
        row.addWidget(btn_refresh)
        btn_clear = QPushButton("清空显示")
        btn_clear.setObjectName("Ghost")
        btn_clear.clicked.connect(self.log_view.clear)
        row.addWidget(btn_clear)
        row.addStretch(1)
        lbl = QLabel("自动刷新 · logs/app.log")
        lbl.setObjectName("Hint")
        row.addWidget(lbl)
        c.body().addLayout(row)

    def _build_about(self, outer: QVBoxLayout):
        """页脚：更新横幅 + 版本/免责声明/检查更新/署名。"""
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet("color: #EFE4D4;")
        outer.addWidget(line)

        row = QHBoxLayout()
        row.setContentsMargins(18, 8, 18, 10)
        row.setSpacing(10)
        lbl = QLabel(
            f"自动续火花 v{VERSION} · 仅供个人学习与娱乐交流，请遵守平台规则；"
            "使用产生的一切后果由使用者自行承担。"
        )
        lbl.setObjectName("AboutText")
        lbl.setWordWrap(True)
        row.addWidget(lbl, 1)
        self.btn_check_update = QPushButton("检查更新")
        self.btn_check_update.setObjectName("Ghost")
        self.btn_check_update.setToolTip("检测 GitHub 上的最新版本；发现新版可一键下载并自动应用")
        self.btn_check_update.clicked.connect(self._manual_check_update)
        row.addWidget(self.btn_check_update)

        # 页脚内联下载进度（下载时不弹前台窗）
        self.dl_box = QWidget()
        dl = QHBoxLayout(self.dl_box)
        dl.setContentsMargins(0, 0, 0, 0)
        dl.setSpacing(8)
        self.dl_bar = QProgressBar()
        self.dl_bar.setObjectName("DlBar")
        self.dl_bar.setFixedWidth(230)
        self.dl_bar.setFixedHeight(14)
        self.dl_bar.setTextVisible(False)
        self.dl_bar.setRange(0, 100)
        self.dl_lbl = QLabel("准备下载…")
        self.dl_lbl.setObjectName("Hint")
        btn_dl_cancel = QPushButton("取消")
        btn_dl_cancel.setObjectName("Ghost")
        btn_dl_cancel.setFixedHeight(30)
        btn_dl_cancel.clicked.connect(self._dl_cancel)
        dl.addWidget(self.dl_bar)
        dl.addWidget(self.dl_lbl)
        dl.addWidget(btn_dl_cancel)
        self.dl_box.setVisible(False)
        row.addWidget(self.dl_box)
        owner = QLabel("YHAz")
        owner.setStyleSheet("color: rgba(160, 150, 140, 110); font-size: 12px; background: transparent;")
        row.addWidget(owner)
        outer.addLayout(row)

    # ---------- 配置读写 ----------

    def _load_config_to_ui(self):
        self.edit_time.setText(str(self.cfg.get("send_time", "09:00")))
        self.edit_text.setText(self.cfg["message"].get("text", "[续火花吧]"))
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
        self.chk_notify_success.setChecked(bool(n.get("notify_on_success", True)))
        self.edit_mention.setText(str(n.get("mention_names", "") or ""))

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
            "notify_on_success": bool(self.chk_notify_success.isChecked()),
            "mention_names": self.edit_mention.text().strip(),
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

    # ---------- 远程提醒 · 推送测试 ----------

    def _test_push(self):
        """「测试」小标签：向配置的群推一条测试消息（用成功通知的正式文案）。"""
        if getattr(self, "_test_push_running", False):
            return
        webhook = self.edit_webhook.text().strip()
        if not webhook.lower().startswith(("http://", "https://")):
            QMessageBox.warning(
                self, "无法测试",
                "请先填写有效的 Webhook 地址（以 https:// 开头）。")
            return
        self._test_push_running = True
        self.btn_test_push.setEnabled(False)
        self.btn_test_push.setText("发送中")
        threading.Thread(target=self._test_push_worker,
                         args=(webhook,), daemon=True).start()

    def _test_push_worker(self, webhook: str):
        ok = False
        try:
            from modules import notify

            names = notify.parse_mentions(self.edit_mention.text())
            ok = notify.send_webhook(
                webhook,
                notify.build_success_text(
                    self.cfg.get("friends", []),
                    self.edit_time.text().strip() or "09:00",
                    datetime.datetime.now().strftime("%H:%M"),
                    names),
                mentions=names)
        except Exception:
            import traceback

            traceback.print_exc()
        self.sig_test_push_done.emit(bool(ok))

    def _on_test_push_done(self, ok: bool):
        """主线程槽：按钮就地显示结果，2.5 秒后复原，不弹窗、不占额外位置。"""
        self._test_push_running = False
        self.btn_test_push.setText("✓ 已发送" if ok else "✗ 失败")
        QTimer.singleShot(2500, self._reset_test_push_btn)

    def _reset_test_push_btn(self):
        self.btn_test_push.setText("测试")
        self.btn_test_push.setEnabled(True)

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
            if upd.is_newer(ver, VERSION):
                self.sig_update_found.emit()
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

    def _on_update_found(self):
        """后台静默检测发现新版本（主线程槽）：按钮变色 + 光效提示。"""
        ver = self._remote_version
        if not ver or not upd.is_newer(ver, VERSION) or self._updating:
            return
        self.btn_check_update.setText(f"下载新版本 v{ver}")
        self.btn_check_update.setObjectName("Primary")
        self._restyle(self.btn_check_update)
        Toast.show_toast(self, f"发现新版本 v{ver}（当前 v{VERSION}）：点「下载新版本」开始更新", "ok")

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
        self.btn_check_update.setEnabled(True)
        ver = self._remote_version
        timed_out = not self._remote_done
        if ver and upd.is_newer(ver, VERSION):
            self.btn_check_update.setText(f"下载新版本 v{ver}")
            self.btn_check_update.setObjectName("Primary")
            self._restyle(self.btn_check_update)
            Toast.show_toast(self, f"发现新版本 v{ver}（当前 v{VERSION}）：点「下载新版本」开始更新", "ok")
            return
        if getattr(self, "_manual_pending", False):
            self._manual_pending = False
            self.btn_check_update.setText("检查更新")  # 恢复按钮文案（检测中 -> 就绪）
            if timed_out or not ver:
                Toast.show_toast(self, "检查更新失败：无法连接版本服务器（GitHub），请稍后重试", "warn")
            else:
                Toast.show_toast(self, f"已是最新版本 v{VERSION}，无需更新", "info")

    def _manual_check_update(self):
        if getattr(self, "_updating", False) or self._running or getattr(self, "_login_running", False) \
                or getattr(self, "_login_checking", False):
            Toast.show_toast(self, "当前有任务或检测正在进行，稍后再试", "warn")
            return
        # 已检测到新版本：按钮此时就是"下载新版本"
        if self._remote_version and upd.is_newer(self._remote_version, VERSION):
            self._start_update_flow()
            return
        self._check_gen = getattr(self, "_check_gen", 0) + 1
        gen = self._check_gen
        self._remote_version = None
        self._remote_done = False
        self._retried = False
        self._manual_pending = True
        threading.Thread(target=self._check_update_worker, args=(gen,), daemon=True).start()
        self._begin_wait_remote()

    def _start_update_flow(self, mode: "str | None" = None):
        """下载新版本：选源 → 页脚进度条下载 → 校验 → 自动应用并重启。"""
        ver = self._remote_version
        if not ver or getattr(self, "_updating", False):
            return
        if self._running or getattr(self, "_login_running", False):
            Toast.show_toast(self, "发送任务进行中，无法更新。请等待任务结束后再试", "warn")
            return
        if mode is None:
            mode = self._pick_update_source()
            if mode is None:
                return

        try:
            os.makedirs(os.path.dirname(self._UPDATE_SOURCE_MARK), exist_ok=True)
            with open(self._UPDATE_SOURCE_MARK, "w", encoding="utf-8") as f:
                json.dump({"last": mode}, f)
        except Exception:  # noqa: BLE001
            pass

        self._updating = True
        dest_dir = os.path.join(tempfile.gettempdir(), "DY_SparkAutoKeeper_update")
        dest = os.path.join(dest_dir, f"DY_SparkAutoKeeper_v{ver}_win64.zip")
        state = {"done": 0, "total": 0, "cancel": False, "finished": False,
                 "ok": False, "t0": time.time(), "d0": 0, "spd": 0.0}
        self._dl_state = state

        # 页脚内联进度：隐藏检查按钮，显示进度条
        self.btn_check_update.setVisible(False)
        self.dl_bar.setRange(0, 100)
        self.dl_bar.setValue(0)
        self.dl_lbl.setText("连接下载源…")
        self.dl_box.setVisible(True)

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
        self._dl_timer = QTimer(self)
        self._dl_timer.timeout.connect(lambda: self._poll_download(ver, dest, state))
        self._dl_timer.start(200)

    def _dl_cancel(self):
        st = getattr(self, "_dl_state", None)
        if st is not None:
            st["cancel"] = True
        self.dl_lbl.setText("正在取消…")

    def _poll_download(self, ver: str, dest: str, state: dict):
        total = state["total"] or 0
        done = state["done"] or 0
        now = time.time()
        dt = now - state["t0"]
        if dt >= 1 and done > state["d0"]:
            state["spd"] = (done - state["d0"]) / dt
            state["t0"], state["d0"] = now, done
        if total > 0:
            self.dl_bar.setValue(min(100, int(done * 100 / total)))
            sp = f" · {state['spd'] / 1048576:.1f}MB/s" if state["spd"] > 0 else ""
            self.dl_lbl.setText(f"{done / 1048576:.0f} / {total / 1048576:.0f} MB{sp}")
        else:
            self.dl_bar.setRange(0, 0)
            self.dl_lbl.setText(f"已下载 {done / 1048576:.0f} MB")
        if not state["finished"]:
            return
        self._dl_timer.stop()
        self._updating = False
        self.dl_box.setVisible(False)
        self.btn_check_update.setVisible(True)
        if state["ok"]:
            self._apply_update(ver, dest)
        else:
            self.btn_check_update.setText("下载新版本")
            self.btn_check_update.setObjectName("Primary")
            self._restyle(self.btn_check_update)
            if state["cancel"]:
                Toast.show_toast(self, "下载已取消：点「下载新版本」可换一个源重试", "warn")
            else:
                Toast.show_toast(self, "下载失败：所有下载源均失败。点「下载新版本」换源重试，"
                                       "或到 GitHub Releases 页面手动下载", "warn")

    def _apply_update(self, ver: str, dest: str):
        """校验 → 快照 → 生成接力脚本 → 短暂提示后自动应用并重启。"""
        if not upd.verify_zip(dest):
            try:
                os.remove(dest)
            except OSError:
                pass
            Toast.show_toast(self, "更新包校验未通过，已自动删除。请点「下载新版本」重新下载", "warn")
            self._updating = False
            return
        self._updating = True
        self.btn_check_update.setEnabled(False)
        upd.backup_user_files(APP_DIR)
        ps1 = upd.write_apply_script(APP_DIR, dest, restart=True)
        Toast.show_toast(self, "更新包校验通过：程序即将关闭并自动安装新版本，随后自动重启", "ok")
        QTimer.singleShot(2400, lambda: (upd.launch_apply(ps1), self.close()))

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
        try:
            from modules import runlock

            _cal_lock = runlock.acquire_lock(os.path.join(APP_DIR, "data", "run.lock"))
        except Exception:  # noqa: BLE001
            _cal_lock = None
        if _cal_lock is None:
            # 定时发送任务正在运行：绝不争抢浏览器，直接按当前标记落定
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
                if _cal_lock is not None:
                    try:
                        from modules import runlock

                        runlock.release_lock(_cal_lock)
                    except Exception:  # noqa: BLE001
                        pass
                self._login_checking = False
                self.sig_login_settle.emit()

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

    def _on_login_worker_done(self):
        """登录子进程结束（主线程槽）：复位按钮并刷新徽章。"""
        self._login_running = False
        self.btn_login.setText("扫码登录")
        self.btn_login.setEnabled(True)
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
            self.sig_login_reset.emit()

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
            self.sig_refresh_task.emit()

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
        # 上次运行：优先取发送任务的记录（last_run.json），否则取最近一次成功发送时间
        last_txt = ""
        try:
            lr_path = os.path.join(APP_DIR, "data", "last_run.json")
            if os.path.exists(lr_path):
                with open(lr_path, encoding="utf-8") as f:
                    lr = json.load(f) or {}
                if lr.get("updated"):
                    if lr.get("date") == today:
                        last_txt = f"今天 {lr['updated']}"
                    else:
                        last_txt = f"{lr.get('date')} {lr['updated']}"
        except Exception:  # noqa: BLE001
            pass
        if not last_txt and st:
            try:
                newest = max(str(v) for v in st.values() if v)
                last_txt = ("今天 " + newest[11:]) if newest[:10] == today else newest
            except Exception:  # noqa: BLE001
                pass
        self.lbl_last.setText(f"上次运行：{last_txt or '—'}")
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


def _install_excepthook():
    """界面回调里未捕获的异常默认会触发 PyQt5 qFatal 直接闪退；
    换成记录到 data/gui_crash.log，程序保持存活。"""

    def hook(etype, val, tb):
        import traceback

        try:
            os.makedirs(os.path.join(APP_DIR, "data"), exist_ok=True)
            with open(os.path.join(APP_DIR, "data", "gui_crash.log"), "a", encoding="utf-8") as f:
                f.write(time.strftime("%Y-%m-%d %H:%M:%S") + chr(10))
                traceback.print_exception(etype, val, tb, file=f)
        except Exception:  # noqa: BLE001
            pass

    sys.excepthook = hook
    try:
        import threading

        threading.excepthook = lambda a: hook(a.exc_type, a.exc_value, a.exc_traceback)
    except Exception:  # noqa: BLE001
        pass


def main():
    _install_excepthook()
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
    _icon = _app_icon()
    if not _icon.isNull():
        app.setWindowIcon(_icon)

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

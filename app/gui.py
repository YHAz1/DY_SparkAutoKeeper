"""抖音自动续火花 · 轻量配置面板（tkinter，Python 内置，零额外依赖）。"""
import os
import re
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import messagebox, scrolledtext, ttk

import yaml

APP_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(APP_DIR, "config.yaml")
LOG_PATH = os.path.join(APP_DIR, "logs", "app.log")
TASK_NAME = "DYSparkAutoKeeper"
PS_SCRIPT = os.path.join(APP_DIR, "scripts", "register_task.ps1")

# 高分屏 DPI 感知，提升清晰度
try:
    import ctypes

    ctypes.windll.shcore.SetProcessDpiAwareness(1)
except Exception:
    pass

DEFAULT_CFG = {
    "send_time": "09:00",
    "friends": [],
    "message": {"text": "[续火花]", "search_friend": False},
    "delays": {"min": 1.5, "max": 3.5},
    "retry": {"max_attempts": 3, "interval_sec": 10},
    "browser": {"headless": False, "gpu": True, "profile_dir": "data/profile", "login_timeout_sec": 180},
    "log": {"dir": "logs", "keep_days": 30},
}


def get_env_python() -> str:
    """返回 dy_spark 环境的 python.exe 路径（找不到则回退当前解释器）。"""
    try:
        r = subprocess.run(
            ["conda", "info", "--base"], capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=30,
        )
        base = (r.stdout or "").strip().splitlines()
        if base:
            p = os.path.join(base[0], "envs", "dy_spark", "python.exe")
            if os.path.exists(p):
                return p
    except Exception:
        pass
    return sys.executable


def task_exists() -> bool:
    r = subprocess.run(["schtasks", "/Query", "/TN", TASK_NAME], capture_output=True)
    return r.returncode == 0


def _tail(path: str, n: int = 200) -> list:
    """读取文件末尾若干行（按字节截取，避免大文件全读）。"""
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - 32768))
            data = f.read().decode("utf-8", errors="replace")
        return data.splitlines()[-n:]
    except Exception:
        return []


class App:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        root.title("抖音自动续火花 · 配置面板")
        root.geometry("540x680")
        root.minsize(500, 620)

        self.cfg = self._load_cfg()
        self.running = False
        self._task_state_text = ""

        self._build()
        self._refresh_task_state()
        self._refresh_log()
        root.after(2000, self._periodic)

    # ---------- 配置读写 ----------
    def _load_cfg(self) -> dict:
        if os.path.exists(CONFIG_PATH):
            try:
                with open(CONFIG_PATH, encoding="utf-8") as f:
                    cfg = yaml.safe_load(f) or {}
                # 合并默认值，防止缺字段
                for k, v in DEFAULT_CFG.items():
                    if k not in cfg:
                        cfg[k] = v
                if not isinstance(cfg.get("message"), dict):
                    cfg["message"] = dict(DEFAULT_CFG["message"])
                for k, v in DEFAULT_CFG["message"].items():
                    cfg["message"].setdefault(k, v)
                return cfg
            except Exception:
                pass
        return dict(DEFAULT_CFG)

    def _save_cfg(self) -> bool:
        time_ok = re.fullmatch(r"([01]?\d|2[0-3]):[0-5]\d", self.time_var.get().strip())
        if not time_ok:
            messagebox.showerror("配置错误", "发送时间格式应为 HH:MM，例如 09:00")
            return False
        self.cfg["send_time"] = self.time_var.get().strip()
        self.cfg["friends"] = list(self.friends_list.get(0, tk.END))
        self.cfg["message"]["text"] = self.text_var.get().strip() or "[续火花]"
        try:
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                yaml.safe_dump(self.cfg, f, allow_unicode=True, sort_keys=False)
            return True
        except OSError as e:
            messagebox.showerror("保存失败", str(e))
            return False

    # ---------- 界面 ----------
    def _build(self) -> None:
        pad = {"padx": 10, "pady": 6}

        # 好友管理
        fr_friends = ttk.LabelFrame(self.root, text="好友昵称列表（消息页可搜索）")
        fr_friends.pack(fill="x", **pad)
        box = tk.Frame(fr_friends)
        box.pack(fill="x", padx=8, pady=6)
        self.friends_list = tk.Listbox(box, height=5)
        self.friends_list.pack(side="left", fill="both", expand=True)
        for name in self.cfg["friends"]:
            self.friends_list.insert(tk.END, name)
        sb = ttk.Scrollbar(box, orient="vertical", command=self.friends_list.yview)
        sb.pack(side="left", fill="y")
        self.friends_list.configure(yscrollcommand=sb.set)
        col = tk.Frame(box)
        col.pack(side="left", padx=(8, 0))
        ttk.Button(col, text="添加 ↓", command=self._add_friend).pack(fill="x")
        ttk.Button(col, text="删除选中", command=self._del_friend).pack(fill="x", pady=(4, 0))
        row = tk.Frame(fr_friends)
        row.pack(fill="x", padx=8, pady=(0, 8))
        ttk.Label(row, text="新好友昵称:").pack(side="left")
        self.friend_entry = ttk.Entry(row)
        self.friend_entry.pack(side="left", fill="x", expand=True, padx=(6, 0))
        self.friend_entry.bind("<Return>", lambda _e: self._add_friend())

        # 发送设置
        fr_send = ttk.LabelFrame(self.root, text="发送设置")
        fr_send.pack(fill="x", **pad)
        row1 = tk.Frame(fr_send)
        row1.pack(fill="x", padx=8, pady=6)
        ttk.Label(row1, text="每日发送时间:").pack(side="left")
        self.time_var = tk.StringVar(value=self.cfg.get("send_time", "09:00"))
        ttk.Entry(row1, textvariable=self.time_var, width=8).pack(side="left", padx=(6, 0))
        ttk.Label(row1, text="（24 小时制，自动注册到开机自启任务）").pack(side="left", padx=10)
        row2 = tk.Frame(fr_send)
        row2.pack(fill="x", padx=8, pady=(0, 8))
        ttk.Label(row2, text="发送内容:").pack(side="left")
        self.text_var = tk.StringVar(value=self.cfg["message"].get("text", "[续火花]"))
        ttk.Entry(row2, textvariable=self.text_var, width=24).pack(side="left", padx=(6, 0))
        ttk.Label(row2, text="（抖音输入 [续火花] 会自动转为火花表情）").pack(side="left", padx=8)

        # 操作按钮
        fr_ops = ttk.Frame(self.root)
        fr_ops.pack(fill="x", **pad)
        ttk.Button(fr_ops, text="💾 保存配置", command=self._save).pack(side="left")
        self.run_btn = ttk.Button(fr_ops, text="▶ 立即运行一次", command=self._run_once)
        self.run_btn.pack(side="left", padx=6)
        ttk.Button(fr_ops, text="⏰ 注册开机自启任务", command=self._register_task).pack(side="left", padx=6)
        ttk.Button(fr_ops, text="🗑 删除定时任务", command=self._unregister_task).pack(side="left", padx=6)

        # 任务状态
        self.state_lbl = ttk.Label(self.root, text="", foreground="#1a7f37")
        self.state_lbl.pack(anchor="w", padx=12)

        # 日志
        fr_log = ttk.LabelFrame(self.root, text="运行日志（app/logs/app.log）")
        fr_log.pack(fill="both", expand=True, **pad)
        self.log_box = scrolledtext.ScrolledText(fr_log, height=12, state="disabled", font=("Consolas", 9))
        self.log_box.pack(fill="both", expand=True, padx=8, pady=8)

    # ---------- 事件 ----------
    def _add_friend(self) -> None:
        name = self.friend_entry.get().strip()
        if not name:
            return
        existing = list(self.friends_list.get(0, tk.END))
        if name not in existing:
            self.friends_list.insert(tk.END, name)
        self.friend_entry.delete(0, tk.END)

    def _del_friend(self) -> None:
        sel = self.friends_list.curselection()
        if sel:
            self.friends_list.delete(sel[0])

    def _save(self) -> None:
        if self._save_cfg():
            messagebox.showinfo("已保存", f"配置已保存到 config.yaml\n好友 {len(self.cfg['friends'])} 个，每日 {self.cfg['send_time']} 发送")

    def _run_once(self) -> None:
        if self.running:
            return
        if not self._save_cfg():
            return
        self.running = True
        self.run_btn.configure(state="disabled", text="运行中…")
        threading.Thread(target=self._run_once_worker, daemon=True).start()

    def _run_once_worker(self) -> None:
        python = get_env_python()
        try:
            subprocess.run(
                [python, os.path.join(APP_DIR, "main.py")],
                cwd=APP_DIR, timeout=600,
            )
        except Exception as e:
            messagebox.showerror("运行失败", str(e))
        finally:
            self.running = False
            self.root.after(0, lambda: self.run_btn.configure(state="normal", text="▶ 立即运行一次"))

    def _register_task(self) -> None:
        if not self._save_cfg():
            return
        t = self.cfg["send_time"]
        try:
            r = subprocess.run(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                 "-File", PS_SCRIPT, "-Time", t],
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
            )
        except Exception as e:
            messagebox.showerror("注册失败", str(e))
            return
        if r.returncode == 0:
            messagebox.showinfo("注册成功", f"已注册开机自启任务：每日 {t} 自动续火花\n（休眠时自动唤醒，错过自动补发）")
        else:
            messagebox.showerror("注册失败", (r.stderr or r.stdout or "").strip()[:400])
        self._refresh_task_state()

    def _unregister_task(self) -> None:
        if not task_exists():
            self._refresh_task_state()
            return
        if not messagebox.askyesno("确认", "确定删除定时任务吗？（不影响手动运行）"):
            return
        subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
             "-File", PS_SCRIPT, "-Unregister"],
            capture_output=True, timeout=60,
        )
        self._refresh_task_state()

    # ---------- 周期刷新 ----------
    def _periodic(self) -> None:
        self._refresh_task_state()
        self._refresh_log()
        self.root.after(2000, self._periodic)

    def _refresh_task_state(self) -> None:
        state = "已注册" if task_exists() else "未注册"
        text = f"定时任务状态：{state}（每日 {self.cfg.get('send_time', '09:00')} 自动发送，非运行时段零占用）"
        if text != self._task_state_text:
            self._task_state_text = text
            self.state_lbl.configure(text=text, foreground="#1a7f37" if "已注册" in state else "#c0392b")

    def _refresh_log(self) -> None:
        lines = _tail(LOG_PATH)
        if not lines:
            return
        text = "\n".join(lines) + "\n"
        if self.log_box.get("1.0", "end-1c") == text.strip():
            return
        self.log_box.configure(state="normal")
        self.log_box.delete("1.0", "end")
        self.log_box.insert("1.0", text)
        self.log_box.see("end")
        self.log_box.configure(state="disabled")


def main() -> None:
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()

"""主流程：开机自启/每日定时触发，自动检查并发送续火花消息。

调度逻辑（符合"开机自启 + 智能判断"需求）：
1. 加进程锁，防止多个实例并发（开机触发 + 每日定时触发可能同时到）
2. 计算今天未发送的好友；若全部完成 → 直接退出
3. 若未到发送时间 → 等待到点后再发送
4. 若已过发送时间 → 立即补发
"""
import datetime
import os
import random
import subprocess
import sys
import time

import yaml

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from modules import sender, state
from modules.logger import init_logger, get_logger
from modules.login import ensure_logged_in, launch


def _app_dir() -> str:
    """程序数据目录：打包后为 exe 所在目录，开发时为脚本目录。"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


APP_DIR = _app_dir()
LOCK_PATH = os.path.join(APP_DIR, "data", "run.lock")


def load_config(path: str = "") -> dict:
    """加载配置；默认基于 APP_DIR 的绝对路径，不依赖启动时的工作目录。"""
    if not path:
        path = os.path.join(APP_DIR, "config.yaml")
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _resolve_paths(cfg: dict) -> dict:
    """把配置中的相对路径（logs、profile）解析为基于 APP_DIR 的绝对路径，
    保证从任意工作目录（VBS/任务计划程序/手动）启动都正确。"""
    log_dir = cfg["log"].get("dir", "logs")
    cfg["log"]["dir"] = os.path.join(APP_DIR, log_dir) if not os.path.isabs(log_dir) else log_dir
    prof = cfg["browser"].get("profile_dir", "data/profile")
    cfg["browser"]["profile_dir"] = os.path.join(APP_DIR, prof) if not os.path.isabs(prof) else prof
    return cfg


def _acquire_lock():
    """获取运行锁（Windows 文件锁）。返回文件对象表示成功，None 表示已有实例在运行。"""
    try:
        import msvcrt

        os.makedirs(os.path.dirname(LOCK_PATH), exist_ok=True)
        f = open(LOCK_PATH, "a+")
        msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
        return f
    except OSError:
        return None


def _release_lock(f) -> None:
    try:
        import msvcrt

        f.seek(0)
        msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
    except OSError:
        pass
    f.close()


def _parse_send_time(send_time: str) -> tuple:
    """解析 'HH:MM'，非法时回退 09:00。"""
    try:
        hh, mm = map(int, str(send_time).split(":"))
        if 0 <= hh <= 23 and 0 <= mm <= 59:
            return hh, mm
    except (ValueError, AttributeError):
        pass
    return 9, 0


def _send_all(cfg: dict, log) -> int:
    """执行发送流程。返回退出码。"""
    friends = cfg["friends"]
    todo = [f for f in friends if state.need_send(f)]
    if not todo:
        log.info("今天所有好友均已发送，无需操作")
        return 0

    log.info(f"本次需要发送的好友：{todo}")
    p, context = launch(
        cfg["browser"]["profile_dir"],
        cfg["browser"]["headless"],
        cfg["browser"].get("gpu", True),
    )
    try:
        if not ensure_logged_in(context, cfg["browser"]["login_timeout_sec"]):
            log.error("登录未完成，终止本次任务")
            return 1

        page = context.new_page()
        success = 0
        for friend in todo:
            try:
                # 标准化：每个好友发送前都重新进入消息页（从会话列表视图开始），
                # 避免上一个好友的聊天窗口残留导致下一个好友定位失败
                if not sender.goto_messages(page, cfg):
                    log.warning(f"处理 {friend} 前进入消息页失败，重试一次")
                    page.wait_for_timeout(2000)
                    if not sender.goto_messages(page, cfg):
                        log.error(f"进入消息页失败，跳过好友 {friend}")
                        continue
                if sender.send_to_friend(context, page, friend, cfg):
                    state.mark_sent(friend)
                    success += 1
                else:
                    log.error(f"给 {friend} 发送失败（已重试 {cfg['retry']['max_attempts']} 次）")
            except Exception as e:  # noqa: BLE001 - 单个好友失败不影响后续
                log.error(f"给 {friend} 发送异常：{e}")
        page.close()

        log.info(f"本次任务结束：成功 {success}/{len(todo)}")
        return 0 if success == len(todo) else 1
    finally:
        context.close()
        p.stop()


def _task_exists() -> bool:
    """自启定时任务是否仍存在（用户可能已删除）。"""
    try:
        r = subprocess.run(
            ["schtasks", "/Query", "/TN", "DYSparkAutoKeeper"],
            capture_output=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000),
        )
        return r.returncode == 0
    except Exception:
        return False


def _randomize_next_day(cfg: dict, log) -> None:
    """每日任务执行结束后：随机明日发送时间（9:00-22:00）并自动更新自启任务。
    若用户已删除自启任务则跳过（不自动重建）。"""
    if not _task_exists():
        log.info("自启任务已被删除，跳过明日时间随机化")
        return
    total = random.randint(9 * 60, 22 * 60)
    new_time = f"{total // 60:02d}:{total % 60:02d}"
    # 只更新 send_time（重新读 config，避免把绝对路径写回）
    cfg_path = os.path.join(APP_DIR, "config.yaml")
    try:
        with open(cfg_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        data["send_time"] = new_time
        with open(cfg_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False)
    except Exception as e:  # noqa: BLE001
        log.warning(f"写入明日发送时间失败：{e}")
    # 重新注册自启任务（更新每日触发时间）
    ps = os.path.join(APP_DIR, "scripts", "register_task.ps1")
    if os.path.exists(ps):
        try:
            subprocess.run(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                 "-File", ps, "-Time", new_time],
                capture_output=True, timeout=90,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000),
            )
            log.info(f"已随机明日发送时间：{new_time}，并更新自启任务")
        except Exception as e:  # noqa: BLE001
            log.warning(f"更新自启任务失败：{e}")
    else:
        log.warning("未找到 register_task.ps1，仅更新 config 中的时间")


def main() -> int:
    cfg = load_config()
    cfg = _resolve_paths(cfg)
    log = init_logger(cfg["log"]["dir"], cfg["log"]["keep_days"])

    friends = cfg["friends"]
    # 防御：过滤空/纯空白好友名（手动编辑 config.yaml 可能引入），避免发送时误匹配
    cfg["friends"] = [str(f).strip() for f in (friends or []) if str(f).strip()]
    friends = cfg["friends"]
    if not friends:
        log.error("config.yaml 中 friends 为空，请先配置好友昵称")
        return 1

    # 进程锁：开机触发与每日定时触发可能并发，只允许一个实例执行
    lock = _acquire_lock()
    if lock is None:
        log.info("检测到已有实例在运行，本次退出")
        return 0
    try:
        # ---- 智能调度 ----
        skipped = [f for f in friends if not state.need_send(f)]
        if skipped:
            log.info(f"以下好友今天已发送过，跳过：{skipped}")
        todo = [f for f in friends if state.need_send(f)]
        if not todo:
            log.info("今天所有好友均已发送，无需操作")
            return 0

        send_time = str(cfg.get("send_time", "09:00"))
        hh, mm = _parse_send_time(send_time)
        now = datetime.datetime.now()
        target = now.replace(hour=hh, minute=mm, second=0, microsecond=0)

        if now < target:
            wait_sec = int((target - now).total_seconds())
            log.info(
                f"还有 {len(todo)} 个好友未发送；当前 {now:%H:%M} 未到发送时间 {send_time}，"
                f"等待 {wait_sec} 秒后发送"
            )
            waited = 0
            while waited < wait_sec:
                time.sleep(min(30, wait_sec - waited))
                waited += 30
                # 等待期间若今天已完成（其他实例发送了）→ 退出
                if not [f for f in friends if state.need_send(f)]:
                    log.info("等待期间检测到今天已完成，退出")
                    return 0
            log.info(f"已到发送时间 {send_time}，开始发送")
        else:
            log.info(f"当前 {now:%H:%M} 已过发送时间 {send_time}，立即补发")

        result = _send_all(cfg, log)
        # 可选：每日任务执行结束后随机明日时间并自动更新自启（默认关闭=固定时间）
        if cfg.get("randomize_time", False):
            _randomize_next_day(cfg, log)
        else:
            log.info("未开启自动随机时间（randomize_time=false），明日沿用固定发送时间")
        return result
    finally:
        _release_lock(lock)


if __name__ == "__main__":
    sys.exit(main())

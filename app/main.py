"""主流程：开机自启/每日定时触发，自动检查并发送续火花消息。

调度逻辑（符合"开机自启 + 智能判断"需求）：
1. 加进程锁，防止多个实例并发（开机触发 + 每日定时触发可能同时到）
2. 计算今天未发送的好友；若全部完成 → 直接退出
3. 若未到发送时间 → 等待到点后再发送
4. 若已过发送时间 → 立即补发
5. 发送前等待网络可用（睡眠唤醒后 Wi-Fi 重连慢的场景）；单轮失败立即推送
   企业微信提醒。失败后不靠进程内轮询重试：register_task.ps1 为主任务订阅了
   Windows"网络已连接"事件（NetworkProfile/Operational 10000），网络一恢复
   系统就会自动拉起本程序补发（今天已发则秒退）；晚间提醒任务（--remind）再兜底。
6. --remind：晚间提醒任务（计划程序每日触发）。今日仍未发送成功 →
   先自动补发一次，仍失败则推送企业微信群机器人提醒到群里。
   提醒时间应晚于随机时间区间上限（随机区间 9:00-22:00，默认提醒 22:30）。
"""
import datetime
import json
import os
import random
import subprocess
import sys
import time

import yaml

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from version import VERSION
from modules import sender, state, notify
from modules.logger import init_logger, get_logger
from modules.login import ensure_logged_in, launch


def _app_dir() -> str:
    """程序数据目录：打包后为 exe 所在目录，开发时为脚本目录。"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


APP_DIR = _app_dir()
LOCK_PATH = os.path.join(APP_DIR, "data", "run.lock")
SESSION_MARK = os.path.join(APP_DIR, "data", ".session_ok")
RUN_FILE = os.path.join(APP_DIR, "data", "last_run.json")

# 晚间提醒任务的时间闸门：计划发送时间过后再等这么久才算"确定没发出去"，
# 避免提醒任务比发送任务先醒、误报"未发送"
_REMIND_GRACE_SEC = 10 * 60
# 提醒任务等待计划时间到来的上限（防止用户把提醒时间设得过早导致长时间挂起）
_REMIND_MAX_WAIT_SEC = 60 * 60


def _session_mark() -> str:
    """登录确认标记文件路径（login 模块在登录成功后写入，GUI 据此显示状态）。"""
    return SESSION_MARK


def _clear_session_mark(log=None) -> None:
    """清除可能已过期的登录标记：登录实际失败时调用，
    让 GUI 徽章如实显示「未登录」并露出「扫码登录」按钮。"""
    try:
        if os.path.exists(SESSION_MARK):
            os.remove(SESSION_MARK)
            if log is not None:
                log.info("已清除登录标记（.session_ok），面板将显示未登录")
    except OSError:
        pass


_DEFAULT_CONFIG = {
    "send_time": "09:00",
    "friends": [],
    "message": {"text": "[续火花吧]", "search_friend": False},
    "randomize_time": False,
    "delays": {"min": 1.0, "max": 3.0},
    "retry": {"max_attempts": 3, "interval_sec": 10},
    "network": {"wait_timeout_min": 5},
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


def load_config(path: str = "") -> dict:
    """加载配置；默认基于 APP_DIR 的绝对路径，不依赖启动时的工作目录。
    配置文件不存在时返回内置默认值（分发包不含 config.yaml，首次保存时才生成）。"""
    if not path:
        path = os.path.join(APP_DIR, "config.yaml")
    try:
        with open(path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
    except FileNotFoundError:
        return dict(_DEFAULT_CONFIG)
    for k, v in _DEFAULT_CONFIG.items():
        cfg.setdefault(k, v)
    return cfg


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


def _load_run_mark() -> dict:
    try:
        with open(RUN_FILE, encoding="utf-8") as f:
            return json.load(f) or {}
    except (OSError, ValueError):
        return {}


def _record_run(planned: str = None, failed=None, log=None) -> None:
    """记录本轮计划/结果到 data/last_run.json。

    用途：晚间提醒任务需要知道"今天的计划发送时间"（randomize_time 开启时，
    任务跑完后 config.yaml 里的 send_time 已变成明天的，不能再用），
    以及最终有哪些好友失败。"""
    data = _load_run_mark()
    today = datetime.date.today().isoformat()
    if data.get("date") != today:
        data = {"date": today}
    if planned:
        data["planned"] = planned
    if failed is not None:
        data["failed"] = list(failed)
        data["updated"] = datetime.datetime.now().strftime("%H:%M:%S")
    try:
        os.makedirs(os.path.dirname(RUN_FILE), exist_ok=True)
        tmp = RUN_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, RUN_FILE)
    except OSError as e:
        if log is not None:
            log.warning(f"写入 last_run.json 失败：{e}")


def _planned_today() -> str:
    """今天的计划发送时间 'HH:MM'；今天没跑过任务返回空串。"""
    data = _load_run_mark()
    if data.get("date") == datetime.date.today().isoformat():
        return str(data.get("planned") or "")
    return ""


def _parse_send_time(send_time: str) -> tuple:
    """解析 'HH:MM'，非法时回退 09:00。"""
    try:
        hh, mm = map(int, str(send_time).split(":"))
        if 0 <= hh <= 23 and 0 <= mm <= 59:
            return hh, mm
    except (ValueError, AttributeError):
        pass
    return 9, 0


def _run_login_phase(cfg: dict, log) -> int:
    """纯登录流程（--login，GUI「扫码登录」按钮调用）：只负责扫码登录并写登录标记，
    不触发任何发送。返回退出码：0=登录成功。"""
    lock = _acquire_lock()
    if lock is None:
        log.info("检测到发送任务正在运行，请稍后再点「扫码登录」")
        return 1
    try:
        wait_min = float(cfg.get("network", {}).get("wait_timeout_min", 5))
        if not notify.wait_for_network(log, wait_min):
            log.error("网络不可用，无法登录")
            _clear_session_mark(log)
            return 1
        try:
            p, context = launch(
                cfg["browser"]["profile_dir"], cfg["browser"].get("gpu", True))
        except Exception as e:  # noqa: BLE001
            log.error(f"浏览器启动失败：{e}")
            _clear_session_mark(log)
            return 1
        try:
            if ensure_logged_in(context, int(cfg["browser"].get("login_timeout_sec", 180))):
                log.info("登录成功 ✔ 请回到面板添加好友并点「注册自启任务」")
                return 0
            log.error("登录未完成（等待扫码超时）")
            _clear_session_mark(log)
            return 1
        finally:
            context.close()
            p.stop()
    finally:
        _release_lock(lock)


def _send_all(cfg: dict, log, only=None) -> list:
    """执行发送流程：对 only（默认全部好友）中今天未发送的好友发送。

    发送前先等网络可用（睡眠唤醒后 Wi-Fi 重连慢是漏发主因）。
    返回本轮仍失败的好友列表（成功者已写入 state.json）。"""
    base = list(only) if only is not None else list(cfg["friends"])
    todo = [f for f in base if state.need_send(f)]
    if not todo:
        log.info("本轮没有需要发送的好友")
        return []

    wait_min = float(cfg.get("network", {}).get("wait_timeout_min", 5))
    if not notify.wait_for_network(log, wait_min):
        log.error(f"网络在 {wait_min:g} 分钟等待期内仍未恢复，本轮放弃")
        return todo

    log.info(f"本次需要发送的好友：{todo}")
    p, context = launch(
        cfg["browser"]["profile_dir"],
        cfg["browser"].get("gpu", True),
    )
    try:
        if not ensure_logged_in(context, cfg["browser"]["login_timeout_sec"]):
            log.error("登录未完成，终止本次任务")
            _clear_session_mark(log)
            return todo

        page = context.new_page()
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
                else:
                    log.error(f"给 {friend} 发送失败（已重试 {cfg['retry']['max_attempts']} 次）")
            except Exception as e:  # noqa: BLE001 - 单个好友失败不影响后续
                log.error(f"给 {friend} 发送异常：{e}")
        page.close()

        failed = [f for f in todo if state.need_send(f)]
        log.info(f"本轮任务结束：成功 {len(todo) - len(failed)}/{len(todo)}")
        return failed
    finally:
        context.close()
        p.stop()


def _send_all_safe(cfg: dict, log, only=None) -> list:
    """_send_all 的兜底包装：浏览器/环境崩溃不应中断外层重试循环。"""
    try:
        return _send_all(cfg, log, only)
    except Exception as e:  # noqa: BLE001
        log.error(f"本轮发送过程异常：{e}")
        base = list(only) if only is not None else list(cfg["friends"])
        return [f for f in base if state.need_send(f)]


def _run_send_phase(cfg: dict, log) -> int:
    """发送阶段：网络等待 → 发送一轮 → 失败立即推送提醒。

    不做进程内轮询重试：失败退出后，Windows 的"网络已连接"事件触发器
    （register_task.ps1 订阅 NetworkProfile/Operational 10000）会在网络恢复的
    瞬间重新拉起本程序补发，晚间提醒任务（--remind）再兜底一次。
    返回退出码：0=全部成功，1=仍有好友失败。"""
    todo_now = [f for f in cfg["friends"] if state.need_send(f)]
    if not todo_now:
        log.info("今天所有好友均已发送，无需操作")
        return 0
    # 读取今天此前的失败记录：若是联网事件触发的一次恢复性补发，成功后要推"已恢复"
    mark = _load_run_mark()
    prev_failed = (list(mark.get("failed") or [])
                   if mark.get("date") == datetime.date.today().isoformat() else [])
    # 记录今天的计划发送时间（晚间提醒任务据此判断"是否确实错过了"）
    _record_run(planned=str(cfg.get("send_time", "09:00")), log=log)

    failed = _send_all_safe(cfg, log, None)
    _record_run(failed=failed, log=log)

    ncfg = cfg.get("notify", {})
    webhook = str(ncfg.get("webhook_url") or "")
    if failed:
        if ncfg.get("notify_on_fail", True) and webhook:
            ok = notify.send_webhook(
                ncfg["webhook_url"], notify.build_fail_text(failed),
                mention_all=bool(ncfg.get("mention_all", True)), log=log)
            log.info("失败通知已推送到群" if ok else "失败通知推送失败")
        else:
            log.warning(f"今日发送失败：{failed}；网络恢复时将由联网事件自动补发")
        return 1
    if prev_failed and webhook:
        recovered = [f for f in prev_failed if not state.need_send(f)] or prev_failed
        ok = notify.send_webhook(webhook, notify.build_recover_text(recovered), log=log)
        log.info("补发成功通知已推送到群" if ok else "补发成功通知推送失败")
    return 0


def _run_remind_phase(cfg: dict, log) -> int:
    """晚间提醒任务（--remind，由计划程序每日触发）。

    今日仍有好友未发送 → 等计划时间+宽限期过后：
    ① 先自动补发一次（网络早恢复了的话直接抢救成功）；
    ② 仍失败则推送企业微信群机器人提醒。"""
    friends = cfg["friends"]
    if not friends:
        log.info("未配置好友，提醒任务无需执行")
        return 0
    todo = [f for f in friends if state.need_send(f)]
    if not todo:
        log.info("今天所有好友均已发送，提醒任务退出")
        return 0

    # 时间闸门：计划时间 + 宽限期未到 → 等一会再查（随机时间可能比提醒时间晚）
    planned = _planned_today()
    if planned:
        hh, mm = _parse_send_time(planned)
        now = datetime.datetime.now()
        target = (now.replace(hour=hh, minute=mm, second=0, microsecond=0)
                  + datetime.timedelta(seconds=_REMIND_GRACE_SEC))
        if now < target:
            wait_sec = min(int((target - now).total_seconds()), _REMIND_MAX_WAIT_SEC)
            log.info(f"今日计划发送时间 {planned} 的宽限期未到，等待 {wait_sec} 秒后再检查")
            waited = 0
            while waited < wait_sec:
                time.sleep(min(30, wait_sec - waited))
                waited += 30
                if not [f for f in friends if state.need_send(f)]:
                    log.info("等待期间检测到今天已完成，提醒任务退出")
                    return 0
            todo = [f for f in friends if state.need_send(f)]
            if not todo:
                return 0
    else:
        log.info("今天没有任务运行记录（计划时间未知），直接进入提醒检查")

    lock = _acquire_lock()
    if lock is None:
        log.info("检测到发送任务正在运行，提醒任务退出（结果由该任务负责通知）")
        return 0
    try:
        todo = [f for f in friends if state.need_send(f)]
        if not todo:
            log.info("今天所有好友均已发送，提醒任务退出")
            return 0
        ncfg = cfg.get("notify", {})
        webhook = str(ncfg.get("webhook_url") or "")
        if ncfg.get("auto_resend", True):
            log.info(f"今日 {len(todo)} 位好友未发送成功，开始自动补发：{todo}")
            failed = _send_all_safe(cfg, log, todo)
            _record_run(failed=failed, log=log)
            if not failed:
                log.info("晚间自动补发成功")
                if webhook:
                    notify.send_webhook(webhook, notify.build_resend_ok_text(todo), log=log)
                return 0
            todo = failed
        if webhook:
            ok = notify.send_webhook(
                webhook, notify.build_remind_text(todo),
                mention_all=bool(ncfg.get("mention_all", True)), log=log)
            log.info("晚间提醒已推送到群" if ok else "晚间提醒推送失败")
        else:
            log.warning(f"今日仍未发送成功：{todo}；未配置 webhook，无法远程提醒")
        return 1
    finally:
        _release_lock(lock)


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
    # 重新注册自启任务（更新每日触发时间；提醒任务沿用配置里的时间）
    ps = os.path.join(APP_DIR, "scripts", "register_task.ps1")
    if os.path.exists(ps):
        try:
            remind_time = str(cfg.get("notify", {}).get("remind_time", "22:30") or "")
            subprocess.run(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                 "-File", ps, "-Time", new_time, "-RemindTime", remind_time],
                capture_output=True, timeout=90,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000),
            )
            log.info(f"已随机明日发送时间：{new_time}，并更新自启任务")
        except Exception as e:  # noqa: BLE001
            log.warning(f"更新自启任务失败：{e}")
    else:
        log.warning("未找到 register_task.ps1，仅更新 config 中的时间")


def main(mode: str = "run") -> int:
    cfg = load_config()
    cfg = _resolve_paths(cfg)
    log = init_logger(cfg["log"]["dir"], cfg["log"]["keep_days"])
    log.info(f"DY_SparkAutoKeeper v{VERSION} 启动（mode={mode}）")

    # 防御：过滤空/纯空白好友名（手动编辑 config.yaml 可能引入），避免发送时误匹配
    cfg["friends"] = [str(f).strip() for f in (cfg.get("friends") or []) if str(f).strip()]

    if mode == "remind":
        return _run_remind_phase(cfg, log)
    if mode == "login":
        return _run_login_phase(cfg, log)

    friends = cfg["friends"]
    if not friends:
        log.info("尚未配置好友：本次运行将只进行登录检查/扫码登录")

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
            if friends:
                log.info("今天所有好友均已发送，无需操作")
                return 0
            if os.path.exists(_session_mark()):
                log.info("已登录但尚未配置好友，无需发送；请在面板添加好友后点「注册自启任务」")
                return 0
            log.info("首次使用：将打开浏览器等待扫码登录（完成后即可在面板配置好友与时间）")
            # 继续往下走"仅登录"流程

        # 未到发送时间的等待逻辑只对真实发送任务生效；首次登录不受发送时间限制
        if todo:
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

        # ---- 仅登录流程（首次使用、未配置好友时）----
        if not todo:
            p, context = launch(cfg["browser"]["profile_dir"], cfg["browser"].get("gpu", True))
            try:
                if not ensure_logged_in(context, cfg["browser"]["login_timeout_sec"]):
                    log.error("登录未完成，终止本次任务")
                    _clear_session_mark(log)
                    return 1
                log.info("登录态已就绪 ✔ 请回到面板：① 添加好友备注 → ② 设定发送时间 → ③ 点「注册自启任务」")
                return 0
            finally:
                context.close()
                p.stop()

        result = _run_send_phase(cfg, log)
        # 可选：每日任务执行结束后随机明日时间并自动更新自启（默认关闭=固定时间）
        if cfg.get("randomize_time", False):
            _randomize_next_day(cfg, log)
        else:
            log.info("未开启自动随机时间（randomize_time=false），明日沿用固定发送时间")
        return result
    finally:
        _release_lock(lock)


if __name__ == "__main__":
    _argv = [a.lower() for a in sys.argv[1:]]
    if "--login" in _argv:
        _mode = "login"
    elif "--remind" in _argv:
        _mode = "remind"
    else:
        _mode = "run"
    sys.exit(main(_mode))

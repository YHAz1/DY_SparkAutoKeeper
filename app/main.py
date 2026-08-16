"""主流程：每日定时给指定好友发送续火花消息（由 Windows 任务计划程序触发）。"""
import os
import sys

import yaml

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from modules import sender, state
from modules.logger import init_logger, get_logger
from modules.login import ensure_logged_in, launch


def load_config(path: str = "config.yaml") -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def main() -> int:
    cfg = load_config()
    log = init_logger(cfg["log"]["dir"], cfg["log"]["keep_days"])

    friends = cfg["friends"]
    if not friends:
        log.error("config.yaml 中 friends 为空，请先配置好友昵称")
        return 1

    todo = [f for f in friends if state.need_send(f)]
    skipped = [f for f in friends if not state.need_send(f)]
    if skipped:
        log.info(f"以下好友今天已发送过，跳过：{skipped}")
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
                if not sender.goto_messages(page):
                    log.warning(f"处理 {friend} 前进入消息页失败，重试一次")
                    page.wait_for_timeout(2000)
                    if not sender.goto_messages(page):
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


if __name__ == "__main__":
    sys.exit(main())

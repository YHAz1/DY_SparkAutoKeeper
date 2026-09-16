"""统一入口（打包用）：
- 无参数 / --gui：打开设置面板（PyQt5）
- --run：执行自动任务（定时任务 / 开机自启调用，等同 main.py）
- --now：手动「立即运行一次」（面板按钮调用；忽略发送时间闸门，立即发送）
- --remind：晚间提醒检查（提醒定时任务调用：未发送成功先补发，再推企业微信提醒）
- --login：仅扫码登录（面板「扫码登录」按钮调用，不触发发送）

注意：新增命令行模式参数时，**必须**登记到下面的 _MODE_FLAGS；
否则打包版会因未识别而走进 else 分支误开一个 GUI 窗口
（面板已有单实例守卫，表现就是"点了没反应"）。
"""
import os
import sys

# 模式参数 -> main.main(mode=...) 的映射。
# gui_qt 面板 / 计划任务传进来的每个 --flag 都必须在这里登记。
_MODE_FLAGS = {
    "--run": "run",
    "--now": "now",
    "--remind": "remind",
    "--login": "login",
}


def main() -> int:
    here = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, here)
    args = [a.lower() for a in sys.argv[1:]]
    mode = next((_MODE_FLAGS[a] for a in args if a in _MODE_FLAGS), None)
    if mode:
        import main as core

        sys.exit(core.main(mode=mode))
        return 0
    import gui_qt

    gui_qt.main()
    return 0


if __name__ == "__main__":
    main()

"""统一入口（打包用）：
- 无参数 / --gui：打开设置面板（PyQt5）
- --run：执行自动任务（定时任务 / 开机自启调用，等同 main.py）
- --remind：晚间提醒检查（提醒定时任务调用：未发送成功先补发，再推企业微信提醒）
- --login：仅扫码登录（面板「扫码登录」按钮调用，不触发发送）
"""
import os
import sys


def main() -> int:
    here = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, here)
    args = [a.lower() for a in sys.argv[1:]]
    if "--run" in args or "--remind" in args or "--login" in args:
        import main as core

        if "--login" in args:
            mode = "login"
        elif "--remind" in args:
            mode = "remind"
        else:
            mode = "run"
        sys.exit(core.main(mode=mode))
        return 0
    import gui_qt

    gui_qt.main()
    return 0


if __name__ == "__main__":
    main()

"""统一入口（打包用）：
- 无参数 / --gui：打开设置面板（PyQt5）
- --run：执行自动任务（定时任务 / 开机自启调用，等同 main.py）
"""
import os
import sys


def main() -> int:
    here = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, here)
    args = [a.lower() for a in sys.argv[1:]]
    if "--run" in args:
        import main as core

        sys.exit(core.main())
        return 0
    import gui_qt

    gui_qt.main()
    return 0


if __name__ == "__main__":
    main()

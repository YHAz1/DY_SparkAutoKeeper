"""进程运行锁：msvcrt 文件锁，进程退出由 OS 自动释放（无陈旧锁问题）。"""
import os

import msvcrt


def acquire_lock(lock_path: str):
    """尝试获取文件锁。成功返回文件句柄（持有期间保持锁定），
    已有实例持锁返回 None。"""
    try:
        os.makedirs(os.path.dirname(lock_path), exist_ok=True)
        f = open(lock_path, "a+")
        msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
        return f
    except OSError:
        return None


def release_lock(f) -> None:
    try:
        import msvcrt

        f.seek(0)
        msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
    except OSError:
        pass
    f.close()

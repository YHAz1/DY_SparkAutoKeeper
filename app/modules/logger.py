"""日志模块：控制台 + 按天滚动文件。"""
import logging
import os
from logging.handlers import TimedRotatingFileHandler

_LOG = None


def get_logger() -> logging.Logger:
    """获取全局 logger（首次调用时初始化）。"""
    global _LOG
    if _LOG is None:
        raise RuntimeError("logger 未初始化，请先调用 init_logger()")
    return _LOG


def init_logger(log_dir: str, keep_days: int = 30) -> logging.Logger:
    """初始化日志。返回全局 logger。"""
    global _LOG
    os.makedirs(log_dir, exist_ok=True)

    logger = logging.getLogger("dy_spark")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    if logger.handlers:
        return logger

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    )

    console = logging.StreamHandler()
    console.setFormatter(fmt)
    logger.addHandler(console)

    file_handler = TimedRotatingFileHandler(
        os.path.join(log_dir, "app.log"),
        when="midnight",
        backupCount=keep_days,
        encoding="utf-8",
    )
    file_handler.setFormatter(fmt)
    logger.addHandler(file_handler)

    _LOG = logger
    return logger

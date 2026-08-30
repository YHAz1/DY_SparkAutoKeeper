"""运行前负载闸门：CPU/显卡高占用时等待并定期复查，降下来才放行浏览器。

设计：
- CPU 占用：Win32_Processor.LoadPercentage 两次采样取平均（消瞬时抖动）。
- GPU 占用：nvidia-smi（NVIDIA）；不可用时返回 None，闸门自动只看 CPU。
- 等待上限：超过 max_wait_min 分钟仍高负载则照常执行——
  当天火花保活优先于资源避让（错过一天 = 火花断了）。
- 全部阈值/开关在 config.yaml 的 load_gate 段配置。
"""
import os
import shutil
import subprocess
import time

_CREATE_NO_WINDOW = 0x08000000


def _ps_run(ps: str, timeout: int = 25) -> str:
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps],
            capture_output=True, timeout=timeout,
            creationflags=_CREATE_NO_WINDOW,
        )
        return r.stdout.decode("utf-8", errors="replace").strip()
    except Exception:  # noqa: BLE001
        return ""


def cpu_usage() -> "float | None":
    """CPU 总占用百分比（两次采样平均）；获取失败返回 None。"""
    vals = []
    for i in range(2):
        out = _ps_run("($c = Get-CimInstance Win32_Processor | Measure-Object "
                      "-Property LoadPercentage -Average).Average")
        try:
            vals.append(float(out.splitlines()[-1]))
        except Exception:  # noqa: BLE001
            vals = []
        if len(vals) < 2 and i == 0:
            time.sleep(1.5)
    return sum(vals) / len(vals) if vals else None


def _nvidia_smi() -> "str | None":
    exe = shutil.which("nvidia-smi")
    if exe:
        return exe
    for cand in (r"C:\Windows\System32\nvidia-smi.exe",
                 r"C:\Program Files\NVIDIA Corporation\NVSMI\nvidia-smi.exe"):
        if os.path.exists(cand):
            return cand
    return None


def gpu_usage() -> "float | None":
    """GPU 占用百分比（取多卡最大值）；无 NVIDIA 工具时返回 None。"""
    exe = _nvidia_smi()
    if not exe:
        return None
    try:
        r = subprocess.run(
            [exe, "--query-gpu=utilization.gpu", "--format=csv,noheader,nounits"],
            capture_output=True, timeout=15,
            creationflags=_CREATE_NO_WINDOW,
        )
        vals = [float(x) for x in r.stdout.decode(errors="replace").splitlines() if x.strip()]
        return max(vals) if vals else None
    except Exception:  # noqa: BLE001
        return None


def wait_for_idle(cfg: dict, log=None) -> None:
    """负载闸门（load_gate.enabled=false 可整体关闭）。
    CPU 或 GPU 超过阈值 → 每隔 interval_min 分钟复查；
    累计等待超过 max_wait_min 分钟仍高负载 → 照常执行（保火花优先）。"""
    g = cfg.get("load_gate") or {}
    if not g.get("enabled", True):
        return
    cpu_max = float(g.get("cpu_max", 80))
    gpu_max = float(g.get("gpu_max", 80))
    interval_min = max(1.0, float(g.get("interval_min", 5)))
    max_wait_min = max(0.0, float(g.get("max_wait_min", 120)))
    interval = interval_min * 60
    deadline = time.time() + max_wait_min * 60

    while True:
        cpu = cpu_usage()
        gpu = gpu_usage()
        busy = []
        if cpu is not None and cpu > cpu_max:
            busy.append(f"CPU {cpu:.0f}%（阈值 {cpu_max:.0f}%）")
        if gpu is not None and gpu > gpu_max:
            busy.append(f"GPU {gpu:.0f}%（阈值 {gpu_max:.0f}%）")
        if not busy:
            if log is not None:
                c = f"{cpu:.0f}%" if cpu is not None else "未知"
                gr = f"{gpu:.0f}%" if gpu is not None else "未检测到"
                log.info(f"系统负载正常（CPU {c} / GPU {gr}），继续执行")
            return
        if time.time() >= deadline:
            if log is not None:
                log.warning(
                    f"高负载避让已达上限（{max_wait_min:g} 分钟，当前 {'、'.join(busy)}），"
                    "为保当天火花照常执行发送")
            return
        if log is not None:
            log.info(f"检测到高负载：{'、'.join(busy)}；{interval_min:g} 分钟后重新检查…")
        time.sleep(interval)

"""软件内自更新模块：版本检测、资产下载、完整性校验、生成升级脚本并拉起。

设计要点：
- 版本源按序尝试：jsDelivr → raw.githubusercontent → GitHub API（各源独立超时），
  任一成功即返回；全部失败返回 None（调用方静默放弃）。仓库根维护纯文本 VERSION 文件。
- 资产命名规律固定：DY_SparkAutoKeeper_v{ver}_win64.zip，无需解析 release 元数据。
- 下载候选 = 直连 + ghproxy 系镜像前缀逐个尝试；urllib 自动读取 Windows 注册表系统代理。
- 完整性校验：zip 必含 app/app.exe 且首字节为 MZ（快速校验，不解压全量）。
- 应用更新采用外部 PowerShell 脚本接力：等程序退出 → 旧 app.exe/_internal 改名留作回滚
  → Expand-Archive 覆盖解压（zip 顶层即 app/，天然对位安装目录）→ 清理 → 可选重启。
  数据目录（data/、config.yaml、logs/）不在包内，全程零接触。
"""
import json
import os
import re
import subprocess
import urllib.request
import zipfile

REPO = "YHAz1/DY_SparkAutoKeeper"

_VERSION_SOURCES = [
    "https://cdn.jsdelivr.net/gh/{repo}@main/VERSION",
    "https://raw.githubusercontent.com/{repo}/main/VERSION",
]
_API_LATEST = f"https://api.github.com/repos/{REPO}/releases/latest"

_ASSET_TEMPLATE = "DY_SparkAutoKeeper_v{ver}_win64.zip"
_MIRROR_PREFIXES = [
    "",  # 直连优先
    "https://mirror.ghproxy.com/",
    "https://gh-proxy.com/",
    "https://ghfast.top/",
]

_UA = {"User-Agent": "DY_SparkAutoKeeper-updater"}


def parse_ver(text: str) -> tuple:
    """'v1.3.0' / '1.3.0' / ' v1.3.0 \\n' → (1, 3, 0)；无法解析返回 ()。"""
    m = re.search(r"(\d+)\.(\d+)\.(\d+)", str(text or ""))
    if not m:
        return ()
    return tuple(int(x) for x in m.groups())


def is_newer(remote: str, local: str) -> bool:
    r, l = parse_ver(remote), parse_ver(local)
    return bool(r) and bool(l) and r > l


def _http_get(url: str, timeout: int = 6):
    req = urllib.request.Request(url, headers=_UA)
    return urllib.request.urlopen(req, timeout=timeout)


def fetch_remote_version(timeout: int = 6, extra_sources: list = None) -> "str | None":
    """按序尝试各版本源，返回形如 '1.3.0' 的版本号；全部失败返回 None。
    extra_sources：测试用本地源（如 http://127.0.0.1:PORT/VERSION），排在最前。"""
    sources = list(extra_sources or [])
    sources += [s.format(repo=REPO) for s in _VERSION_SOURCES]
    sources.append(_API_LATEST)
    for src in sources:
        try:
            with _http_get(src, timeout=timeout) as resp:
                body = resp.read().decode("utf-8", errors="replace").strip()
            if "api.github.com" in src:
                tag = (json.loads(body) or {}).get("tag_name", "") or ""
                mm = re.search(r"\d+\.\d+\.\d+", tag)
                return mm.group(0) if mm else None
            ver = body.splitlines()[0].strip() if body else ""
            if parse_ver(ver):
                mm = re.search(r"(\d+\.\d+\.\d+)", ver)
                return mm.group(1) if mm else None
        except Exception:  # noqa: BLE001 - 单源失败换下一个
            continue
    return None


def asset_urls(version: str, prefixes: list = None) -> list:
    """给定版本号，返回按优先级排列的下载地址列表。"""
    name = _ASSET_TEMPLATE.format(ver=version)
    direct = f"https://github.com/{REPO}/releases/download/v{version}/{name}"
    prefixes = _MIRROR_PREFIXES if prefixes is None else prefixes
    seen, out = set(), []
    for p in prefixes:
        u = p + direct
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


def download(urls: list, dest_path: str, progress=None, chunk: int = 65536,
             connect_timeout: int = 20) -> "str | None":
    """依次尝试 urls 下载到 dest_path。progress(done, total)->bool，
    返回 False 表示用户请求取消（中止全部尝试）。成功返回 dest_path，失败返回 None。"""
    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
    for url in urls:
        tmp = dest_path + ".part"
        try:
            req = urllib.request.Request(url, headers=_UA)
            with urllib.request.urlopen(req, timeout=connect_timeout) as resp, open(tmp, "wb") as f:
                total = int(resp.headers.get("Content-Length") or 0)
                done = 0
                while True:
                    block = resp.read(chunk)
                    if not block:
                        break
                    f.write(block)
                    done += len(block)
                    if progress is not None and progress(done, total) is False:
                        raise InterruptedError("用户取消下载")
            if total and done < total * 0.98:  # 异常截断视为失败换下一源
                continue
            os.replace(tmp, dest_path)
            return dest_path
        except InterruptedError:
            try:
                os.remove(tmp)
            except OSError:
                pass
            raise
        except Exception:  # noqa: BLE001 - 本源失败换下一个
            continue
        finally:
            if os.path.exists(tmp) and not os.path.exists(dest_path):
                try:
                    os.remove(tmp)
                except OSError:
                    pass
    return None


def verify_zip(path: str) -> bool:
    """快速完整性校验：能打开中央目录、包含 app/app.exe 且首两字节为 MZ。"""
    try:
        with zipfile.ZipFile(path) as z:
            names = z.namelist()
            if "app/app.exe" not in names:
                return False
            with z.open("app/app.exe") as f:
                head = f.read(2)
            return head == b"MZ"
    except Exception:  # noqa: BLE001
        return False


def backup_user_files(install_dir: str) -> "str | None":
    """应用更新前快照小型用户文件到 data/_pre_update_backup/（data 目录升级全程零接触，
    快照可长期保留作为恢复保险；_update_tmp 会在升级完成后被脚本清理，故不放这里）。"""
    import shutil

    bdir = os.path.join(install_dir, "data", "_pre_update_backup")
    try:
        os.makedirs(bdir, exist_ok=True)
        candidates = [
            os.path.join(install_dir, "config.yaml"),
            os.path.join(install_dir, "data", "state.json"),
            os.path.join(install_dir, "data", ".session_ok"),
        ]
        for c in candidates:
            if os.path.exists(c):
                shutil.copy2(c, os.path.join(bdir, os.path.basename(c)))
        return bdir
    except Exception:  # noqa: BLE001
        return None


def write_apply_script(install_dir: str, zip_path: str, restart: bool = True) -> str:
    """生成升级接力脚本（UTF-8 BOM 的 PowerShell，兼容中文路径）。
    流程：等程序退出 → 旧执行体改名留作回滚点 → 覆盖解压 → 成功清理 / 失败回滚 → 可选重启。"""
    parent = os.path.dirname(install_dir)
    ps_path = os.path.join(install_dir, "_update_tmp", "apply_update.ps1")

    def q(p: str) -> str:
        return p.replace('"', '`"')

    script = f'''$ErrorActionPreference = "Stop"
$zip  = "{q(zip_path)}"
$dest = "{q(parent)}"
$app  = "{q(install_dir)}"
Start-Sleep -Seconds 2
Rename-Item -LiteralPath (Join-Path $app "app.exe") -NewName "app.exe.bak" -ErrorAction SilentlyContinue
Rename-Item -LiteralPath (Join-Path $app "_internal") -NewName "_internal.bak" -ErrorAction SilentlyContinue
try {{
    Expand-Archive -Force -Path $zip -DestinationPath $dest
}} catch {{
    if (Test-Path (Join-Path $app "app.exe.bak")) {{
        if (Test-Path (Join-Path $app "app.exe")) {{ Remove-Item (Join-Path $app "app.exe") -Recurse -Force -ErrorAction SilentlyContinue }}
        Rename-Item -LiteralPath (Join-Path $app "app.exe.bak") -NewName "app.exe"
    }}
    if (Test-Path (Join-Path $app "_internal.bak")) {{
        if (Test-Path (Join-Path $app "_internal")) {{ Remove-Item (Join-Path $app "_internal") -Recurse -Force -ErrorAction SilentlyContinue }}
        Rename-Item -LiteralPath (Join-Path $app "_internal.bak") -NewName "_internal"
    }}
    exit 1
}}
Remove-Item -LiteralPath (Join-Path $app "app.exe.bak") -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath (Join-Path $app "_internal.bak") -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath $zip -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath (Join-Path $app "_update_tmp") -Recurse -Force -ErrorAction SilentlyContinue
if ("{'true' if restart else 'false'}" -eq "true") {{ Start-Process -FilePath (Join-Path $app "app.exe") }}
'''
    os.makedirs(os.path.dirname(ps_path), exist_ok=True)
    with open(ps_path, "w", encoding="utf-8-sig") as f:
        f.write(script)
    return ps_path


def launch_apply(ps1_path: str) -> None:
    """脱离当前进程拉起升级脚本（父进程随后自行退出）。"""
    subprocess.Popen(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
         "-WindowStyle", "Hidden", "-File", ps1_path],
        creationflags=0x08000000,  # CREATE_NO_WINDOW
        close_fds=True,
    )

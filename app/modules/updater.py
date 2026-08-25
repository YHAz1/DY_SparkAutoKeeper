"""软件内自更新模块：版本检测、资产下载、完整性校验、生成升级脚本并拉起。

设计要点：
- 网络层使用系统自带 curl.exe（Win10 1803+ 内置），彻底绕开 PyInstaller+conda
  打包后 _ssl DLL 依赖损坏的问题（"unknown url type: https" / "DLL load failed"）。
- 版本源按序尝试：GitHub API → jsDelivr → raw（各源独立超时）；仓库根维护 VERSION 文件。
- 资产命名规律固定：DY_SparkAutoKeeper_v{ver}_win64.zip。
- 下载候选 = 直连 + ghproxy 系镜像前缀逐个尝试；curl 自动遵循系统代理环境变量。
- 完整性校验：zip 必含 app/app.exe 且首字节为 MZ（快速校验，不解压全量）。
- 应用更新采用外部 PowerShell 脚本接力：等程序退出 → 旧 app.exe/_internal 改名留作回滚
  → tar/Expand-Archive 覆盖解压（zip 顶层即 app/，天然对位安装目录）→ 清理 → 可选重启。
  数据目录（data/、config.yaml、logs/）不在包内，全程零接触。
"""
import json
import os
import re
import subprocess

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

_DEBUG_LOG = None  # 由 init_debug_log 注入路径


def init_debug_log(path: str) -> None:
    """启用检测调试日志（GUI 启动时调用，写入安装目录 data/update_debug.log）。"""
    global _DEBUG_LOG
    _DEBUG_LOG = path


def _dbg(msg: str) -> None:
    if not _DEBUG_LOG:
        return
    try:
        import time as _t

        os.makedirs(os.path.dirname(_DEBUG_LOG), exist_ok=True)
        if os.path.exists(_DEBUG_LOG) and os.path.getsize(_DEBUG_LOG) > 262144:
            os.remove(_DEBUG_LOG)
        with open(_DEBUG_LOG, "a", encoding="utf-8") as f:
            f.write(f"{_t.strftime('%Y-%m-%d %H:%M:%S')} {msg}\n")
    except Exception:  # noqa: BLE001
        pass


def _curl_path() -> str:
    root = os.environ.get("SystemRoot", r"C:\Windows")
    return os.path.join(root, "System32", "curl.exe")


def _curl_available() -> bool:
    return os.path.exists(_curl_path())


def _curl_run(args: list, timeout: int = 30):
    """执行 curl，返回 (returncode, stdout_bytes, stderr_text)。"""
    cmd = [_curl_path(), "-sS", "--ssl-no-revoke", *args]
    r = subprocess.run(cmd, capture_output=True, timeout=timeout)
    return r.returncode, r.stdout, r.stderr.decode("utf-8", errors="replace")


def parse_ver(text: str) -> tuple:
    """'v1.3.0' / '1.3.0' / ' v1.3.0\\n' → (1, 3, 0)；无法解析返回 ()。"""
    m = re.search(r"(\d+)\.(\d+)\.(\d+)", str(text or ""))
    if not m:
        return ()
    return tuple(int(x) for x in m.groups())


def is_newer(remote: str, local: str) -> bool:
    r, l = parse_ver(remote), parse_ver(local)
    return bool(r) and bool(l) and r > l


def fetch_remote_version(timeout: int = 10, extra_sources: list = None) -> "str | None":
    """按序尝试各版本源（curl 子进程，双协议兜底 --ssl-no-revoke/默认），
    返回形如 '1.3.0' 的版本号；全部失败返回 None。"""
    if not _curl_available():
        _dbg("curl.exe 不可用")
        return None
    sources = list(extra_sources or [])
    sources.append(_API_LATEST)
    sources += [s.format(repo=REPO) for s in _VERSION_SOURCES]
    _dbg(f"fetch 开始，候选 {len(sources)} 个")
    for src in sources:
        for tls in (["--ssl-no-revoke"], []):
            try:
                rc, body, err = _curl_run(["-m", str(timeout), src] + tls, timeout=timeout + 5)
                if rc != 0:
                    _dbg(f"GET FAIL {src} rc={rc} {err[:70]} (tls={bool(tls)})")
                    continue
                body = body.decode("utf-8", errors="replace").strip()
                if "api.github.com" in src:
                    tag = (json.loads(body) or {}).get("tag_name", "") or ""
                    mm = re.search(r"\d+\.\d+\.\d+", tag)
                    if mm:
                        _dbg(f"命中 API: {mm.group(0)}")
                        return mm.group(0)
                    continue
                ver = body.splitlines()[0].strip() if body else ""
                mm = re.search(r"(\d+\.\d+\.\d+)", ver)
                if mm:
                    _dbg(f"命中文件源: {mm.group(1)}")
                    return mm.group(1)
            except Exception as e:  # noqa: BLE001
                _dbg(f"GET EXC {src} {type(e).__name__}:{str(e)[:60]}")
                continue
    _dbg("全部候选源失败")
    return None


def asset_urls(version: str, prefixes: list = None) -> list:
    """给定版本号，返回按优先级排列的下载地址列表。"""
    name = _ASSET_TEMPLATE.format(ver=version)
    direct = f"https://github.com/{REPO}/releases/download/v{version}/{name}"
    prefixes = _MIRROR_PREFIXES if prefixes is None else prefixes
    seen, out = set(), []
    for p in prefixes:
        url = p + direct
        if url not in seen:
            seen.add(url)
            out.append(url)
    return out


def _content_length(url: str, timeout: int = 15) -> int:
    try:
        rc, body, err = _curl_run(["-sIL", "-m", str(timeout), url], timeout=timeout + 5)
        if rc != 0:
            return 0
        text = body.decode("utf-8", errors="replace")
        lengths = re.findall(r"(?i)content-length:\s*(\d+)", text)
        return int(lengths[-1]) if lengths else 0
    except Exception:  # noqa: BLE001
        return 0


def download(urls: list, dest_path: str, progress=None,
             connect_timeout: int = 20) -> "str | None":
    """依次尝试 urls（curl -L 下载）到 dest_path。
    progress(done, total)->bool，返回 False 表示用户请求取消。
    成功返回 dest_path；全部失败返回 None。"""
    if not _curl_available():
        return None
    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
    for url in urls:
        part = dest_path + ".part"
        total = _content_length(url, connect_timeout)
        _dbg(f"DL 开始 {url} total={total}")
        try:
            proc = subprocess.Popen(
                [_curl_path(), "-sS", "--ssl-no-revoke", "-L", "-o", part, url],
                creationflags=0x08000000,  # CREATE_NO_WINDOW
            )
            import time as _t

            while proc.poll() is None:
                _t.sleep(0.3)
                done = os.path.getsize(part) if os.path.exists(part) else 0
                if progress is not None and progress(done, total) is False:
                    proc.kill()
                    try:
                        os.remove(part)
                    except OSError:
                        pass
                    raise InterruptedError("用户取消下载")
            rc = proc.returncode
            if rc == 0 and os.path.exists(part) and os.path.getsize(part) > 0:
                os.replace(part, dest_path)
                _dbg(f"DL OK {os.path.getsize(dest_path)}B")
                return dest_path
            _dbg(f"DL FAIL rc={rc}")
        except InterruptedError:
            raise
        except Exception as e:  # noqa: BLE001
            _dbg(f"DL EXC {type(e).__name__}:{str(e)[:80]}")
        finally:
            if os.path.exists(part) and not os.path.exists(dest_path):
                try:
                    os.remove(part)
                except OSError:
                    pass
    return None


def verify_zip(path: str) -> bool:
    """快速完整性校验：能打开中央目录、包含 app/app.exe 且首两字节为 MZ。"""
    try:
        import zipfile

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
    快照可长期保留作为恢复保险）。"""
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
    """生成升级接力脚本（UTF-8 BOM 的 PowerShell，兼容中文路径），保存在 zip 同目录。
    流程：等程序退出 → 旧执行体改名留作回滚点 → 覆盖解压 → 成功清理 / 失败回滚 → 可选重启。
    注意：脚本与 zip 必须放在安装目录之外（如系统临时目录），避免"运行中删除自身所在目录"。"""
    parent = os.path.dirname(install_dir)
    ps_path = os.path.join(os.path.dirname(zip_path), "apply_update.ps1")

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
    # tar.exe（Win10 1803+ 内置）优先：对深层嵌套长路径更可靠
    & "$env:SystemRoot\\System32\\tar.exe" -xf $zip -C $dest
    if ($LASTEXITCODE -ne 0) {{ throw "tar exit $LASTEXITCODE" }}
}} catch {{
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
}}
Remove-Item -LiteralPath (Join-Path $app "app.exe.bak") -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath (Join-Path $app "_internal.bak") -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath $zip -Force -ErrorAction SilentlyContinue
if ("{'true' if restart else 'false'}" -eq "true") {{ Start-Process -FilePath (Join-Path $app "app.exe") }}
Remove-Item -LiteralPath "{q(ps_path)}" -Force -ErrorAction SilentlyContinue
exit 0
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

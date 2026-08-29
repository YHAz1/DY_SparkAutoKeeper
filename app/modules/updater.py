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
    "",  # 直连
    "https://gh.dpik.top/",
    "https://gh-proxy.com/",
    "https://cdn.gh-proxy.com/",
    "https://ghfast.top/",
]


def system_proxy() -> "str | None":
    """读取系统代理（WinINET 注册表设置，即"设置→网络→代理"里的那项）。
    返回形如 http://127.0.0.1:26361 的地址；未开启返回 None。"""
    try:
        import winreg

        k = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Internet Settings")
        enable, _ = winreg.QueryValueEx(k, "ProxyEnable")
        server, _ = winreg.QueryValueEx(k, "ProxyServer")
        winreg.CloseKey(k)
        if not enable or not server:
            return None
        server = _normalize_proxy_server(str(server))
        if server and not server.startswith("http"):
            server = "http://" + server
        return server or None
    except Exception:  # noqa: BLE001
        return None


def _normalize_proxy_server(server: str) -> str:
    """ProxyServer 可能是 '127.0.0.1:8080' 或 'http=...;https=...' 两种格式，
    统一取出 host:port。仅做字符串处理，便于单测。"""
    server = (server or "").strip()
    if not server:
        return ""
    if ";" in server or "=" in server:
        pick = ""
        for part in server.split(";"):
            if "=" in part:
                scheme, _, val = part.partition("=")
                if scheme.lower() in ("https", "http") and val:
                    pick = val
                    break
            elif part.strip():
                pick = part.strip()
        server = pick
    return server


def direct_url(version: str) -> str:
    """不带镜像前缀的 GitHub 直连下载地址。"""
    name = _ASSET_TEMPLATE.format(ver=version)
    return f"https://github.com/{REPO}/releases/download/v{version}/{name}"


def asset_urls(version: str, prefixes: list = None) -> list:
    """给定版本号，返回按优先级排列的下载地址列表（不带代理信息）。"""
    direct = direct_url(version)
    prefixes = _MIRROR_PREFIXES if prefixes is None else prefixes
    seen, out = set(), []
    for p in prefixes:
        p = p if (not p or p.endswith("/")) else p + "/"
        url = p + direct
        if url not in seen:
            seen.add(url)
            out.append(url)
    return out

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
    # 兜底：全部直连失败且系统代理开启时，走系统代理再试一轮 API 源
    sp = system_proxy()
    if sp:
        _dbg(f"直连全部失败，尝试系统代理 {sp}")
        try:
            rc, body, err = _curl_run(
                ["-m", str(timeout), "-x", sp, _API_LATEST], timeout=timeout + 5)
            if rc == 0:
                tag = (json.loads(body.decode("utf-8", errors="replace")) or {}).get("tag_name", "")
                mm = re.search(r"\d+\.\d+\.\d+", tag or "")
                if mm:
                    _dbg(f"命中 API(系统代理): {mm.group(0)}")
                    return mm.group(0)
        except Exception as e:  # noqa: BLE001
            _dbg(f"GET EXC(proxy) {type(e).__name__}:{str(e)[:60]}")
    _dbg("全部候选源失败")
    return None


def _content_length(url: str, timeout: int = 15, proxy: "str | None" = None) -> int:
    try:
        args = ["-sIL", "-m", str(timeout)]
        if proxy:
            args += ["-x", proxy]
        args.append(url)
        rc, body, err = _curl_run(args, timeout=timeout + 5)
        if rc != 0:
            return 0
        text = body.decode("utf-8", errors="replace")
        lengths = re.findall(r"(?i)content-length:\s*(\d+)", text)
        return int(lengths[-1]) if lengths else 0
    except Exception:  # noqa: BLE001
        return 0


def download(candidates: list, dest_path: str, progress=None,
             connect_timeout: int = 20, auto_switch: bool = True,
             min_speed_kb: int = 100, grace_sec: int = 20) -> "str | None":
    """依次尝试各下载候选（元素为 url 或 (url, proxy) 元组，proxy 为 None 表示直连）
    下载到 dest_path。progress(done, total)->bool，返回 False 表示用户请求取消。

    auto_switch=True（自动模式）时带速度看护：每过 grace_sec 秒统计一次窗口速度，
    低于 min_speed_kb 就果断掐掉当前候选、换下一个（"慢就取消选其他的"的自动版）；
    手动指定单个源时调用方应传 auto_switch=False，尊重用户选择。
    成功返回 dest_path；全部失败返回 None。"""
    norm = []
    for c in candidates or []:
        url, proxy = c if isinstance(c, tuple) else (c, None)
        if url and url not in [u for u, _ in norm]:
            norm.append((url, proxy))
    if not norm:
        return None
    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
    for url, proxy in norm:
        part = dest_path + ".part"
        total = _content_length(url if not proxy else url, connect_timeout, proxy)
        _dbg(f"DL 开始 {url} proxy={bool(proxy)} total={total}")
        try:
            cmd = [_curl_path(), "-sS", "--ssl-no-revoke", "-f", "-L",
                   "-o", part, "-w", "%{http_code}"]
            if proxy:
                cmd[1:1] = ["-x", proxy]
            cmd.append(url)
            proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE,
                creationflags=0x08000000,  # CREATE_NO_WINDOW
            )
            import time as _t

            t_ref, d_ref = _t.monotonic(), 0
            aborted_slow = False
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
                if auto_switch:
                    now = _t.monotonic()
                    span = now - t_ref
                    if span >= grace_sec:
                        speed = (done - d_ref) / span
                        if speed < min_speed_kb * 1024:
                            _dbg(f"DL 慢速 {speed / 1024:.0f}KB/s < {min_speed_kb}KB/s，切换下一候选")
                            proc.kill()
                            aborted_slow = True
                            break
                        t_ref, d_ref = now, done
            if aborted_slow:
                try:
                    os.remove(part)
                except OSError:
                    pass
                continue
            rc = proc.returncode
            http_code = ""
            try:
                http_code = (proc.stdout.read() or b"").decode("ascii", errors="replace").strip()
            except Exception:  # noqa: BLE001
                pass
            if rc == 0 and http_code in ("200", "206") and \
                    os.path.exists(part) and os.path.getsize(part) > 0:
                os.replace(part, dest_path)
                _dbg(f"DL OK {os.path.getsize(dest_path)}B")
                return dest_path
            _dbg(f"DL FAIL rc={rc} http={http_code}")
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
    流程：等程序完全退出（最多 30s）→ 清理本程序残留的浏览器/驱动进程（释放 _internal
    与 profile 占用，这是旧版"更新后登录态异常"的主因）→ 旧 app.exe/_internal 改名留作
    回滚点 → 覆盖解压 → 校验关键文件齐全（不完整自动回滚）→ 清理 → 可选重启。
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
# 1) 等待主程序完全退出（最多 30 秒），避免文件占用导致"半更新"
$deadline = (Get-Date).AddSeconds(30)
while ((Get-Date) -lt $deadline) {{
    $busy = Get-CimInstance Win32_Process -Filter "Name='app.exe'" |
        Where-Object {{ $_.ExecutablePath -like "$app*" }}
    if (-not $busy) {{ break }}
    Start-Sleep -Milliseconds 500
}}
# 2) 清理本程序残留的浏览器/驱动进程（按安装路径精确匹配，不影响用户自己的 Chrome）
Get-CimInstance Win32_Process |
    Where-Object {{ $_.CommandLine -like "*$app*" -and
                    ($_.Name -eq 'chrome.exe' -or $_.Name -eq 'headless_shell.exe' -or $_.Name -eq 'node.exe') }} |
    ForEach-Object {{ Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }}
Start-Sleep -Milliseconds 500

function Rollback {{
    if (Test-Path (Join-Path $app "app.exe.bak")) {{
        if (Test-Path (Join-Path $app "app.exe")) {{ Remove-Item (Join-Path $app "app.exe") -Recurse -Force -ErrorAction SilentlyContinue }}
        Rename-Item -LiteralPath (Join-Path $app "app.exe.bak") -NewName "app.exe" -ErrorAction SilentlyContinue
    }}
    if (Test-Path (Join-Path $app "_internal.bak")) {{
        if (Test-Path (Join-Path $app "_internal")) {{ Remove-Item (Join-Path $app "_internal") -Recurse -Force -ErrorAction SilentlyContinue }}
        Rename-Item -LiteralPath (Join-Path $app "_internal.bak") -NewName "_internal" -ErrorAction SilentlyContinue
    }}
}}

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
        Rollback
        exit 1
    }}
}}
# 3) 校验关键文件齐全（不完整说明解压被占用打断），不完整则回滚到旧版
if (-not (Test-Path (Join-Path $app "app.exe")) -or
    -not (Test-Path (Join-Path $app "_internal\\ms-playwright"))) {{
    Rollback
    exit 1
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

"""免 UAC 启动：为「权限管理里手动添加的软件」各建一个「最高权限」计划任务。

## 为什么需要它
Windows 的 UAC 提示跑在**安全桌面**上，只有微软签名的 UIAccess 程序才能与之交互 ——
普通程序**无法**代点「是」。所以「帮用户自动点 UAC」在技术上做不到，能做的只有
**绕开提示**：让进程从一开始就以提升后的权限启动。

## 做法
给每个软件建一个**没有触发器**的计划任务，主体指向该 exe 的绝对路径，主体等级
`Highest`（= 勾选「使用最高权限运行」）。之后用 `Start-ScheduledTask` / `schtasks /run`
点名启动它 —— 进程由**任务计划服务**（以 SYSTEM 身份）代为创建，**这条路径不经过 UAC**。

## 两个实践要点（踩过坑）
1. **提权进程的输出拿不到**：`Start-Process -Verb RunAs` 给的是另一个（隐藏的）控制台，
   `[Console]::Error.WriteLine` 写的东西不会回到我们这里，只剩一个「退出码 1」。
   所以内层脚本把结果（成功 / 真实报错 + 诊断）**写进一个临时结果文件**，外层读出来打印。
2. **不要只依赖 `schtasks.exe`**：它可能被企业策略 / 沙箱工具列入程序黑名单，
   那样「任务其实建好了、但查询失败」会被误报成设置失败。查询与启动都以
   PowerShell 的 `Get-ScheduledTask` / `Start-ScheduledTask` 兜底。
"""
import base64
import datetime
import hashlib
import os
import subprocess
import tempfile
import uuid
from pathlib import Path

# 任务名前缀：批量清理、肉眼识别都用它
TASK_PREFIX = "IgnotusLaunch_"

# 用户取消 UAC 时 Start-Process -Verb RunAs 抛异常，我们用这个退出码回传
_ERR_CANCELLED = 1223

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

# 诊断日志：提权那一步的真实报错都追加到这里（pythonw 启动没有控制台，只能落文件）
LOG_PATH = Path(__file__).resolve().parent.parent / "launch_task.log"


def available() -> bool:
    """本功能只在 Windows 上可用（任务计划 + PowerShell）。"""
    return os.name == "nt"


# ---------- 任务名 ----------

def task_name(exe_path: str) -> str:
    """由 exe 绝对路径推出**稳定**的任务名（大小写不敏感）。

    纯 ASCII 十六进制，避开中文路径在命令行下的编码坑；
    同一路径永远得到同一个名字 —— `ensure_task` 因此是幂等的。
    """
    raw = str(exe_path or "").strip()
    try:
        raw = os.path.abspath(raw)
    except (OSError, ValueError):
        pass
    key = os.path.normcase(raw).encode("utf-8", "replace")
    return TASK_PREFIX + hashlib.sha1(key).hexdigest()[:12]


def _ps_sq(value: str) -> str:
    """PowerShell 单引号字符串字面量（内部的 `'` 要写两遍）。"""
    return "'" + str(value).replace("'", "''") + "'"


def _indent(text: str, spaces: int = 4) -> str:
    """把脚本体缩进一层，塞进内层模板的 try 块里。"""
    pad = " " * spaces
    return "".join(pad + ln if ln.strip() else ln for ln in text.splitlines(True))


def _append_log(text: str) -> None:
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"[{datetime.datetime.now():%Y-%m-%d %H:%M:%S}] {text}\n")
    except OSError:
        pass


# ---------- 脚本模板（用占位符替换，避开 f-string 里成堆的花括号转义）----------

_INNER_TEMPLATE = """$ErrorActionPreference = 'Stop'
$__log = <<LOG>>
try {
<<BODY>>
    $__res = 'OK'
    if ($__how) { $__res = 'OK via ' + $__how }
    Set-Content -LiteralPath $__log -Value $__res -Encoding UTF8
    exit 0
} catch {
    $__diag = 'PS ' + $PSVersionTable.PSVersion.ToString() `
        + '; Register-ScheduledTask=' + [int][bool](Get-Command Register-ScheduledTask -ErrorAction SilentlyContinue) `
        + '; schtasks=' + [int][bool](Get-Command schtasks.exe -ErrorAction SilentlyContinue) `
        + '; user=' + $env:USERDOMAIN + '\\' + $env:USERNAME
    Set-Content -LiteralPath $__log -Value ('失败：' + $_.Exception.Message + ' ｜ ' + $__diag) -Encoding UTF8
    exit 1
}
"""

_OUTER_TEMPLATE = """$ErrorActionPreference = 'Stop'
$__log = <<LOG>>
try {
    $p = Start-Process -FilePath powershell.exe -Verb RunAs -Wait -PassThru -WindowStyle Hidden -ArgumentList '-NoProfile','-NonInteractive','-EncodedCommand','<<TOKEN>>'
    $__code = 0
    if ($null -ne $p.ExitCode) { $__code = $p.ExitCode }
    if (Test-Path -LiteralPath $__log) { Get-Content -LiteralPath $__log -Raw | Write-Output }
    exit $__code
} catch {
    exit <<CANCELLED>>
}
"""

# 建任务：Register-ScheduledTask 为主（取对象、无 XML、**不传 -Trigger = 无触发器**），
# 失败再退到 schtasks /create（`/st 00:00` 用当天日期 ⇒ 避开各语言区域的日期格式坑；
# 触发时刻已过 ⇒ 不会被自动触发，只等被点名）。
#
# 主体账号写 `USERDOMAIN\USERNAME` 为主、**当前用户 SID 为备**：微软账户（MSA）登录时
# 名字经常无法映射成 SID（`Register-ScheduledTask` 报「账户名与安全 ID 之间无映射」），
# SID 则一定解析得到。两条都失败才回退 schtasks —— 错误信息全部带出去给用户看。
_BODY_CREATE = """$exe = <<EXE>>
$wd = <<WD>>
$name = <<NAME>>
$user = "$env:USERDOMAIN\\$env:USERNAME"
$sid = ''
try { $sid = [System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value } catch { $sid = '' }
$action = New-ScheduledTaskAction -Execute $exe -WorkingDirectory $wd
$settings = $null
try {
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances Parallel -StartWhenAvailable
} catch { $settings = $null }
$users = @($user)
if ($sid -ne '' -and $sid -ne $user) { $users += $sid }
$__err = @()
$__how = ''
foreach ($u in $users) {
    try {
        $principal = New-ScheduledTaskPrincipal -UserId $u -LogonType Interactive -RunLevel Highest
        if ($null -ne $settings) {
            Register-ScheduledTask -TaskName $name -Action $action -Principal $principal -Settings $settings -Force | Out-Null
        } else {
            Register-ScheduledTask -TaskName $name -Action $action -Principal $principal -Force | Out-Null
        }
        $__how = 'Register-ScheduledTask'
        break
    } catch {
        $__err += ($u + ': ' + $_.Exception.Message)
    }
}
if (-not $__how) {
    $null = & schtasks.exe /create /tn $name /tr ('"' + $exe + '"') /rl HIGHEST /ru $user /it /sc ONCE /st 00:00 /f 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw ('Register-ScheduledTask 失败（' + ($__err -join ' | ') + '）；schtasks 回退也失败（退出码 ' + $LASTEXITCODE + '）')
    }
    $__how = 'schtasks'
}
"""

_BODY_DELETE = """$name = <<NAME>>
$t = Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
if ($null -ne $t) { $t | Unregister-ScheduledTask -Confirm:$false }
$__how = 'Unregister-ScheduledTask'
"""

_BODY_CLEANUP = """$t = Get-ScheduledTask -TaskName <<PATTERN>> -ErrorAction SilentlyContinue
if ($null -ne $t) { $t | Unregister-ScheduledTask -Confirm:$false }
$__how = 'Unregister-ScheduledTask'
"""

# 查询 / 启动：不需要管理员，直接跑（schtasks 被安全策略拦下时的兜底）
_QUERY_SCRIPT = """$t = Get-ScheduledTask -TaskName <<NAME>> -ErrorAction SilentlyContinue
if ($null -ne $t) { exit 0 } else { exit 1 }
"""

_START_SCRIPT = """try { Start-ScheduledTask -TaskName <<NAME>> -ErrorAction Stop; exit 0 } catch { exit 1 }
"""


# ---------- 进程调用 ----------

def _b64(script: str) -> str:
    """PowerShell -EncodedCommand 要求 UTF-16LE + Base64。

    用编码而不是临时文件：中文路径 / 引号都不用转义，也不在磁盘留脚本。
    """
    return base64.b64encode(script.encode("utf-16-le")).decode("ascii")


def _dec(raw) -> str:
    if not raw:
        return ""
    if isinstance(raw, bytes):
        for enc in ("utf-8", "gbk"):
            try:
                raw = raw.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        else:
            raw = raw.decode("utf-8", "replace")
    # 去掉 BOM / NUL（`Set-Content -Encoding UTF8` 在 PS 5.1 下会写 BOM）
    return raw.replace("\ufeff", "").replace("\x00", "").strip()


def _run_ps_raw(script: str, timeout: int = 120):
    """跑一段 PowerShell，返回 (退出码, stdout, stderr)；异常统一给 -1。"""
    try:
        r = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-EncodedCommand", _b64(script)],
            capture_output=True, timeout=timeout, creationflags=_NO_WINDOW,
        )
    except subprocess.TimeoutExpired:
        return -1, "", "操作超时"
    except Exception as e:  # noqa: BLE001
        return -1, "", str(e)
    return int(r.returncode), _dec(r.stdout), _dec(r.stderr)


def _schtasks(args) -> int:
    """调用 schtasks（不需要管理员），返回退出码；异常统一给 -1。

    注意：某些企业策略 / 沙箱会把 `schtasks.exe` 列入程序黑名单，那时这里恒为 -1 ——
    所以调用方必须有 PowerShell cmdlet 兜底。
    """
    try:
        r = subprocess.run(
            ["schtasks"] + list(args), capture_output=True, timeout=25,
            creationflags=_NO_WINDOW,
        )
        return int(r.returncode)
    except Exception:  # noqa: BLE001
        return -1


def _run_elevated(body: str, timeout: int = 120):
    """以管理员身份跑一段 PowerShell —— **会弹一次 UAC 授权框**。

    返回 (是否成功, 说明)。说明取自内层写出的**结果文件**（含真实报错 + 诊断信息），
    失败时同时追加到 `launch_task.log`。
    """
    log_file = Path(tempfile.gettempdir()) / f"ignotus_uac_{uuid.uuid4().hex}.txt"
    inner = (_INNER_TEMPLATE
             .replace("<<LOG>>", _ps_sq(str(log_file)))
             .replace("<<BODY>>", _indent(body)))
    outer = (_OUTER_TEMPLATE
             .replace("<<LOG>>", _ps_sq(str(log_file)))
             .replace("<<TOKEN>>", _b64(inner))
             .replace("<<CANCELLED>>", str(_ERR_CANCELLED)))

    rc, out, err = _run_ps_raw(outer, timeout)
    # **优先读结果文件**：内层用 `Set-Content -Encoding UTF8` 落盘，编码确定；
    # 而外层 stdout 在 PS 5.1 下按控制台 OEM 代码页（中文机 = GBK）输出，中文报错
    # 经 `_dec` 猜测解码容易花屏。文件在，就用文件。
    detail = ""
    try:
        if log_file.exists():
            detail = _dec(log_file.read_bytes())
    except OSError:
        detail = ""
    if not detail:
        detail = out
    try:
        log_file.unlink()
    except OSError:
        pass

    if rc == 0 and detail.startswith("OK"):
        _append_log(f"提权成功：{detail}")
        return True, detail
    if rc == _ERR_CANCELLED:
        _append_log("提权被用户取消（UAC 点了「否」）")
        return False, "已取消管理员授权"
    _append_log(f"提权失败 rc={rc}\n--- body ---\n{body}\n--- out ---\n{out}\n--- err ---\n{err}")
    return False, detail or err or f"退出码 {rc}"


# ---------- 脚本文本（诊断 / 测试用；也是真正被执行的实体）----------

def create_script(exe_path: str) -> str:
    """「建任务」这一步实际执行的 PowerShell 主体（`_BODY_CREATE` 填空后的成品）。

    不含外层 `Start-Process -Verb RunAs` 包装 —— 外层只负责提权与回传结果。
    """
    exe = str(Path(exe_path))
    return (_BODY_CREATE
            .replace("<<EXE>>", _ps_sq(exe))
            .replace("<<WD>>", _ps_sq(str(Path(exe).parent)))
            .replace("<<NAME>>", _ps_sq(task_name(exe))))


def delete_script(name_or_exe: str) -> str:
    """「删任务」脚本主体。参数可以是任务名，也可以是 exe 路径。"""
    raw = str(name_or_exe or "")
    name = raw if raw.startswith(TASK_PREFIX) else task_name(raw)
    return _BODY_DELETE.replace("<<NAME>>", _ps_sq(name))


def cleanup_script() -> str:
    """「批量清理所有 IgnotusLaunch_* 任务」脚本主体。"""
    return _BODY_CLEANUP.replace("<<PATTERN>>", _ps_sq(TASK_PREFIX + "*"))


# ---------- 对外接口 ----------

def _task_via(verb: str, exe_path: str, fallback_script: str) -> bool:
    """查 / 跑任务走同一条路：先 `schtasks <verb>`，被安全策略拦下时退回 PowerShell cmdlet。

    两条路都要有：某些企业策略 / 沙箱会把 `schtasks.exe` 列黑，只走它会把「已建好」
    误判成失败（查询）或点了不启动（运行）。
    """
    if not available():
        return False
    name = task_name(exe_path)
    if _schtasks([verb, "/tn", name]) == 0:
        return True
    return _run_ps_raw(fallback_script.replace("<<NAME>>", _ps_sq(name)), 30)[0] == 0


def has_task(exe_path: str) -> bool:
    """该 exe 是否已经建好免 UAC 任务（不需要管理员权限即可查询）。"""
    return _task_via("/query", exe_path, _QUERY_SCRIPT)


def run_task(exe_path: str) -> bool:
    """点名启动任务 —— 这条路**不弹 UAC**，也不需要管理员权限。"""
    return _task_via("/run", exe_path, _START_SCRIPT)


def ensure_task(exe_path: str):
    """确保存在免 UAC 任务；已存在则直接返回成功（幂等）。

    返回 (是否成功, 说明)。失败时说明可直接展示给用户（含真实报错）。
    """
    if not available():
        return False, "当前系统不支持"
    exe = str(exe_path or "").strip()
    if not exe:
        return False, "没有可执行文件路径"
    if not Path(exe).exists():
        return False, f"找不到文件「{exe}」"
    if has_task(exe):
        return True, "已存在"
    ok, info = _run_elevated(create_script(exe))
    if not ok:
        return False, info
    if not has_task(exe):
        return False, "授权已完成，但查不到计划任务（详见项目目录下的 launch_task.log）"
    return True, info


def remove_task(exe_path: str):
    """删除该 exe 的免 UAC 任务（需要一次管理员授权）。任务本就不存在则直接成功。"""
    if not available():
        return False, "当前系统不支持"
    if not has_task(exe_path):
        return True, "本就没有"
    return _run_elevated(delete_script(exe_path))


def remove_all_tasks():
    """一次性清掉所有 `IgnotusLaunch_*` 任务（需要一次管理员授权）。"""
    if not available():
        return False, "当前系统不支持"
    return _run_elevated(cleanup_script())

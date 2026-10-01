"""冒烟测试：开机自启（注册表启动项 + 启动路径自愈 + 静默启动进托盘）。

跑法（在项目根目录）：
    .venv\\Scripts\\python.exe tests\\smoke_autostart.py

说明：
- 前半部分是纯逻辑断言，**只读注册表**（涉及写入的分支一律换成假函数）。
- 后半部分是本套件的重点：真实跑 `app.main.main()`，用一个子进程跑一种启动形态
  （QApplication 一个进程只能建一个，所以「自启启动」与「普通启动」必须分开跑）。
  子进程由 `tests/boot_probe.py` 承担，会预置 asr/tts 替身、替换托盘，也不写注册表。
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# ★★单跑也默认走「无声后端」（开关在 `app/patpat.py` 顶部）。本套的第 3 节会起子进程真跑
#   `main()`（`boot_probe.py`），子进程**继承这里的环境** ⇒ 一并静音。
#   2026-09-30 机器被 GPT-SoVITS 抢满 CPU 时，本套与 `smoke_pet` 各自 300s 超时被强杀。
os.environ.setdefault("IGNOTUS_NO_AUDIO", "1")
BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
try:  # 控制台重定向时保证中文输出可读
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

fails = []
total = [0]


def check(name, ok, detail=""):
    total[0] += 1
    print(("OK   " if ok else "FAIL ") + name + (f"   [{detail}]" if detail and not ok else ""))
    if not ok:
        fails.append(name)


from app import autostart  # noqa: E402

# ========== 1. 命令行与自启标记 ==========
print("== 1. 启动命令行 ==")
cmd = autostart.launch_command()
check("启动命令含 run.py", "run.py" in cmd, cmd)
check("启动命令带 --autostart 标记", cmd.endswith(autostart.AUTOSTART_FLAG), cmd)
check("命令行为纯 ASCII（注册表里可读）", cmd.isascii(), cmd)
check("路径用引号包裹（含空格也安全）", cmd.startswith('"') and cmd.count('"') >= 2, cmd)
if (Path(sys.executable).with_name("pythonw.exe")).exists():
    check("存在 pythonw.exe 时优先用它（避免黑窗）", "pythonw" in cmd, cmd)

check("is_autostart_launch 认得出标记", autostart.is_autostart_launch(["run.py", "--autostart"]) is True)
check("普通启动不算自启", autostart.is_autostart_launch(["run.py"]) is False)
check("空 argv 不算自启", autostart.is_autostart_launch([]) is False)
check("标记位置无关", autostart.is_autostart_launch(["--autostart", "run.py"]) is True)

# ========== 2. refresh_command 自愈（全用假函数，不碰注册表）==========
print("== 2. 启动项路径自愈 ==")
_real = (autostart.current_command, autostart.enable)
try:
    autostart.current_command = lambda: ""
    check("未开启自启：不改写也不顺手打开", autostart.refresh_command() == (False, ""))

    autostart.current_command = lambda: autostart.launch_command()
    check("命令行已经是最新：不动它", autostart.refresh_command() == (False, ""))

    # 仅大小写 / 分隔符差异看着不同、其实是同一条命令 → 不该反复改写注册表
    autostart.current_command = lambda: autostart.launch_command().replace("\\", "/").upper()
    check("仅大小写 / 分隔符不同：不算过时", autostart.refresh_command() == (False, ""))

    # 项目被移动 / 改名：注册表里是旧绝对路径 → 改写
    wrote = {}

    def _fake_enable():
        wrote["cmd"] = autostart.launch_command()
        return True, "已设置开机自启。"

    autostart.enable = _fake_enable

    autostart.current_command = lambda: '"C:\\old\\pythonw.exe" "C:\\old\\run.py"'
    changed, want = autostart.refresh_command()
    check("项目移动（注册表里是旧绝对路径）→ 就地改写",
          changed is True and want == autostart.launch_command(), f"{changed} {want}")
    check("改写写入的正是当前命令行", wrote.get("cmd") == autostart.launch_command(),
          str(wrote.get("cmd")))

    # 旧版本写入的命令（没有 --autostart 标记）同样判为过时
    autostart.current_command = lambda: f'"{sys.executable}" "{BASE / "run.py"}"'
    changed_old, want_old = autostart.refresh_command()
    check("旧版本命令（缺 --autostart）也判为过时并改写",
          changed_old is True and want_old.endswith(autostart.AUTOSTART_FLAG),
          f"{changed_old} {want_old}")

    # 写注册表失败：必须如实上报，不能谎报已修复
    autostart.current_command = lambda: '"C:\\old\\run.py"'
    autostart.enable = lambda: (False, "设置失败：模拟")
    changed2, msg2 = autostart.refresh_command()
    check("改写失败：不谎报成功且带上原因",
          changed2 is False and "失败" in msg2, f"{changed2} {msg2}")
finally:
    (autostart.current_command, autostart.enable) = _real
check("假函数已复原（注册表状态可读）", isinstance(autostart.is_enabled(), bool))


# ========== 3. 真实启动：自启静默进托盘 / 普通启动照常显示 ==========
print("== 3. 真实跑 main() 的启动形态 ==")
tmp_dir = Path(tempfile.mkdtemp(prefix="ignotus_boot_smoke_"))
PROBE = BASE / "tests" / "boot_probe.py"

# ★子进程硬超时：**必须**有。探针会真跑一次 `main()`，而这里实测出现过 300s 挂住
#   （2026-09-30：机器被 GPT-SoVITS 抢满 CPU 时）。没有它的话本套会被一路拖到
#   `run_all` 的 300s 硬超时强杀 —— **看不出是哪一个探针挂的**，也没有诊断信息。
#   3 × 75s 最坏 225s，仍在 `run_all` 的兜底之内。
PROBE_TIMEOUT = 75


def run_probe(silent: bool, stale: bool = False) -> dict:
    out = tmp_dir / f"boot_{int(silent)}_{int(stale)}.json"
    tag = ("自启" if silent else "普通") + ("+过时" if stale else "")
    env = os.environ.copy()                 # 必须整份继承：缺 TEMP/SYSTEMROOT 会让子进程踩坑
    env.pop("PYTHONPATH", None)
    env["BOOT_PROBE_OUT"] = str(out)
    env["BOOT_PROBE_SILENT"] = "1" if silent else "0"
    env["BOOT_PROBE_STALE"] = "1" if stale else "0"
    try:
        r = subprocess.run([sys.executable, str(PROBE)], cwd=str(BASE), env=env,
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=PROBE_TIMEOUT)
    except subprocess.TimeoutExpired as e:
        # 清进程树：`sys.executable` 是 venv 垫片，它还会再起一个真 python 子进程
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(e.pid)], capture_output=True)
        got = e.stdout or ""
        if isinstance(got, bytes):
            got = got.decode("utf-8", "replace")
        return {"_error": f"[{tag}] 探针 {PROBE_TIMEOUT}s 未返回（**挂起**，已强杀进程树）"
                          f"\n已收到的输出尾（看最后一行停在哪一步）：\n{got[-600:]}"}
    if not out.exists():
        return {"_error": f"[{tag}] rc={r.returncode}\n{r.stderr[-800:]}"}
    return json.loads(out.read_text(encoding="utf-8"))


# --- 3a. 开机自启启动：不显示主界面、桌宠在桌面且休眠 ---
sil = run_probe(silent=True)
if "_error" in sil:
    check("自启启动探针跑通", False, sil["_error"])
else:
    check("自启启动探针跑通", sil["rc"] == 0, str(sil["rc"]))
    check("自启启动：**不显示主界面**", sil["win_visible_at_start"] is False)
    check("自启启动：桌宠显示在桌面上", sil["pet_visible_at_start"] is True)
    check("自启启动：桌宠处于休眠（idle）", sil["pet_state_at_start"] == "idle",
          sil["pet_state_at_start"])
    check("自启启动：停在聊天页（点托盘即可用）", sil["page_index"] == 0, str(sil["page_index"]))
    check("自启启动：有「已开机自启」提示",
          any("已开机自启" in m for m in sil["messages"]), str(sil["messages"]))
    check("自启启动：点托盘能把主界面叫回来", sil["win_visible_after_tray_click"] is True)
    check("自启启动：叫回来的是完整主界面（尺寸正常）",
          sil["window_size_after_tray_click"] == [820, 540],
          str(sil["window_size_after_tray_click"]))
    check("自启启动：叫回来后左栏是角色区（不是空白）",
          sil["left_is_role_page_after_tray_click"] is True)
    check("自启启动：叫回来后桌宠仍在待机", sil["pet_state_after_tray_click"] == "idle",
          sil["pet_state_after_tray_click"])

# --- 3b. 普通启动：行为不变（照常显示主界面）---
nrm = run_probe(silent=False)
if "_error" in nrm:
    check("普通启动探针跑通", False, nrm["_error"])
else:
    check("普通启动探针跑通", nrm["rc"] == 0, str(nrm["rc"]))
    check("普通启动：照常显示主界面（没被自启逻辑误伤）", nrm["win_visible_at_start"] is True)
    check("普通启动：桌宠也显示", nrm["pet_visible_at_start"] is True)
    check("普通启动：无「已开机自启」提示",
          not any("已开机自启" in m for m in nrm["messages"]), str(nrm["messages"]))

# --- 3c. 启动项过时：启动时自动改写并告知 ---
heal = run_probe(silent=False, stale=True)
if "_error" in heal:
    check("过时启动项探针跑通", False, heal["_error"])
else:
    check("过时启动项探针跑通", heal["rc"] == 0, str(heal["rc"]))
    check("启动时自动改写失效的启动项并提示",
          any("启动路径已自动更新" in m for m in heal["messages"]), str(heal["messages"]))
    check("提示里给出了新的启动命令（含 run.py）",
          any("启动路径已自动更新" in m and "run.py" in m for m in heal["messages"]),
          str(heal["messages"]))
    check("过时自愈不弹主界面以外的窗口（普通启动仍显示主界面）",
          heal["win_visible_at_start"] is True)

print()
print(f"共 {total[0]} 项断言，失败 {len(fails)} 项")
print("FAILED: " + ", ".join(fails) if fails else "ALL_OK")
sys.exit(1 if fails else 0)

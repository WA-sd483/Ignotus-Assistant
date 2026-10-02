"""跑全部冒烟测试并汇总（新增 smoke_pipeline 后统一入口）。

**编码**：本脚本会把失败套件的原始输出打到控制台，而该控制台在中文 Windows 上默认是 **GBK**，而本脚本内部、父子进程之间都得认 UTF-8，否则会出现「子进程用 GBK 写、父进程按 UTF-8 读」的 UnicodeDecodeError，
把一个好好的套件误判成 `(无输出)`（实测踩过：smoke_permissions）。
所以：自己 reconfigure，并把 `PYTHONIOENCODING=utf-8` 传给子进程（子进程自己也应该写 reconfigure，
这里是为“以后新加的套件忘了写”兜底）。读子进程输出时再加 `errors="replace"`，宁可乱码也不能把汇总跑崩。
★**每一处**起子进程的地方都要给（不只套件，**超时兜底里的 `taskkill` 也算** —— 它在中文 Windows 上吐 GBK）。
"""
import os
import subprocess
import sys
from pathlib import Path

try:  # 控制台重定向 / GBK 控制台下保证中文与 − 这类字符能打出去
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

# 子进程的标准输出 / 错误统一走 UTF-8（与上面的解码口径一致）
# ★★`IGNOTUS_NO_AUDIO=1`：强制「无声后端」（开关在 `app/patpat.py` 顶部）。
#   本机 QtMultimedia 的 FFmpeg 后端在「**刚 play 就 stop**」时会**偶发挂死**
#   ⇒ `smoke_pet`（卡在 `_patpat_stop()`，卡点之后约 2200 行永远跑不到）与
#     `smoke_autostart`（子进程跑真 `main()`）会挂到 300s 硬超时。
#   ★关掉它**不改任何被测行为**（`play()` 在 `_ensure()` **之前**就写好 `last_played`），
#     只是不初始化原生后端那一步（细则见 TECH-GOTCHAS「六」）。
#   ★要跑**真**后端：`IGNOTUS_NO_AUDIO=0 .venv/Scripts/python.exe tests/run_all.py`。
CHILD_ENV = dict(os.environ, PYTHONIOENCODING="utf-8",
                 IGNOTUS_NO_AUDIO=os.environ.get("IGNOTUS_NO_AUDIO", "1"))

ROOT = Path(__file__).resolve().parent.parent
PY = str(ROOT / ".venv" / "Scripts" / "python.exe")
SUITES = ["smoke_settings", "smoke_permissions", "smoke_api", "smoke_tts",
          "smoke_autostart", "smoke_pipeline", "smoke_pet", "smoke_sleep",
          "reply_probe", "smoke_health"]

# 单套件硬超时。**必须**有：smoke_pet 里有一处已知的时序赛跑（脚本里写着「单跑绿、全量跑红」），
# 偶发会让那一套**卡死**（本文件实测踩过两次：跑到 smoke_pet 就再也不往下走）。
# 没有兜底的话整个 run_all 会无限挂住 —— 而且在脚本自动化的场景里没人能发现。
# 超时后**必须** `taskkill /T` 清进程树：`.venv/Scripts/python.exe` 是个**垫片**，
# 它还会再起一个真 python 子进程，只 kill 垫片会留下孤儿。
SUITE_TIMEOUT = 300

print(f"[env] IGNOTUS_NO_AUDIO={CHILD_ENV['IGNOTUS_NO_AUDIO']}"
      + ("（无声后端；原生音频后端偶发挂死，见 TECH-GOTCHAS「六」）"
         if CHILD_ENV["IGNOTUS_NO_AUDIO"] == "1" else "（★真音频后端，可能偶发挂起）"))

tot = 0
bad = []
flaky = []


def run_suite(name):
    """跑一套件，返回 `(ok, 项数, out, err, 失败原因)`（成功时原因为空串）。"""
    p = subprocess.Popen([PY, str(ROOT / "tests" / f"{name}.py")],
                         cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                         text=True, encoding="utf-8", errors="replace", env=CHILD_ENV)
    try:
        out, err = p.communicate(timeout=SUITE_TIMEOUT)
    except subprocess.TimeoutExpired:
        # ★`taskkill` 在中文 Windows 上吐的是 **GBK**，这里也必须给 `errors="replace"` ——
        # 漏了它，超时兜底那一瞬间的读取线程会抛 UnicodeDecodeError（实测踩过：整段
        # traceback 打在 FAIL 行之前，把「已收掉的输出尾」冲得看不出重点）。
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(p.pid)],
                       capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
        try:
            out, err = p.communicate(timeout=15)
        except Exception:  # noqa: BLE001
            out, err = "", ""
        return False, _count(out), out, err, f"超时 {SUITE_TIMEOUT}s（已强杀进程树）"
    n = _count(out)
    ok = "ALL_OK" in (out or "")
    return ok, n, out, err, "" if ok else "有失败断言"


def _count(out) -> int:
    """从输出里取「共 N 项」的 N（取不到 → 0）。"""
    tail = [ln for ln in (out or "").splitlines() if ln.startswith("共 ")]
    for part in (tail[-1] if tail else "").replace("，", " ").split():
        if part.isdigit():
            return int(part)
    return 0


for name in SUITES:
    ok, n, out, err, why = run_suite(name)
    if ok:
        tot += n
        print(f"OK  {name:22s} {n} 项")
        continue
    # ★★已知偶发（`_patpat_stop()` 的原生音频后端 / 高负载） ⇒ **按规矩自动重跑一次**。
    #   项目口径本来就是「见到 300s 超时先重跑一次再下结论」—— 这里替人跑掉那一步，
    #   但**绝不静默**：重跑才过的会单独列出来，让人知道本轮有过抖动。
    print(f"RETRY {name:21s}（{why}）—— 按规矩重跑一次")
    ok2, n2, out2, err2, why2 = run_suite(name)
    if ok2:
        flaky.append(name)
        tot += n2
        print(f"OK  {name:22s} {n2} 项【重跑才过：第一次 {why}】")
        continue
    bad.append(name)
    print(f"FAIL {name:22s}（第一次 {why} / 重跑 {why2}）")
    print((out2 or "")[-2000:])
    print((err2 or "")[-2000:])

print()
print(f"合计 {tot} 项，失败套数 {len(bad)}")
if flaky:
    print(f"⚠️ 偶发（重跑才过，不计失败）：{', '.join(flaky)}"
          f" —— 根因与处置见 TECH-GOTCHAS「六」")
print("ALL_OK" if not bad else "FAILED: " + ", ".join(bad))
sys.exit(1 if bad else 0)

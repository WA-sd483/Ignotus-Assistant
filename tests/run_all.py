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
CHILD_ENV = dict(os.environ, PYTHONIOENCODING="utf-8")

ROOT = Path(__file__).resolve().parent.parent
PY = str(ROOT / ".venv" / "Scripts" / "python.exe")
SUITES = ["smoke_settings", "smoke_permissions", "smoke_api", "smoke_tts",
          "smoke_autostart", "smoke_pipeline", "smoke_pet", "smoke_sleep",
          "reply_probe"]

# 单套件硬超时。**必须**有：smoke_pet 里有一处已知的时序赛跑（脚本里写着「单跑绿、全量跑红」），
# 偶发会让那一套**卡死**（本文件实测踩过两次：跑到 smoke_pet 就再也不往下走）。
# 没有兜底的话整个 run_all 会无限挂住 —— 而且在脚本自动化的场景里没人能发现。
# 超时后**必须** `taskkill /T` 清进程树：`.venv/Scripts/python.exe` 是个**垫片**，
# 它还会再起一个真 python 子进程，只 kill 垫片会留下孤儿。
SUITE_TIMEOUT = 300

tot = 0
bad = []
for name in SUITES:
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
        print(f"FAIL {name:22s} (超时 {SUITE_TIMEOUT}s —— 已强杀进程树)")
        print("⚠️ 该套件超时（疑似偶发挂起；见 smoke_pet 里「单跑绿、全量跑红」那条时序赛跑）。")
        print("   已收掉的输出尾 2000 字：")
        print((out or "")[-2000:])
        print((err or "")[-2000:])
        bad.append(name)
        continue
    tail = [ln for ln in (out or "").splitlines() if ln.startswith("共 ")]
    line = tail[-1] if tail else "(无输出)"
    n = 0
    for part in line.replace("，", " ").split():
        if part.isdigit():
            n = int(part)
            break
    tot += n
    ok = "ALL_OK" in (out or "")
    print(f"{'OK  ' if ok else 'FAIL'} {name:22s} {line}")
    if not ok:
        bad.append(name)
        print((out or "")[-2000:])
        print((err or "")[-2000:])

print()
print(f"合计 {tot} 项，失败套数 {len(bad)}")
print("ALL_OK" if not bad else "FAILED: " + ", ".join(bad))
sys.exit(1 if bad else 0)

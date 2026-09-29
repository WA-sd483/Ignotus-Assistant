"""DeepSeek 用量与余额 —— 第二款气泡「第一类内容」的数据源（二十三改，2026-09-21）。

三件事，全是**只读**（不发新请求、不额外耗 token）：

1. **今日 token 用量**：DeepSeek **没有**「今日用量」接口，只能自己累计 ——
   把每次 `chat.completions` 响应里**本来就会返回**的 `usage.total_tokens` 加起来。
   累计落盘到 `stats.json`，**跨天自动清零**（用户 2026-09-21 拍板：该做法不额外耗 token，采用）。
2. **剩余余额**：`GET {base_url}/user/balance`（与对话同一个 base_url，Bearer 鉴权）。
   ★这是**计费查询**接口、不是 `chat.completions` ⇒ 同样不耗 token。
3. **高峰 / 空闲时段**：纯时间函数 `peak_state()`。

⚠️ 官方 2026 峰谷口径（2026-08-17 生效；08-23 起周末全天按低谷）：
   工作日**北京时间 09:00–12:00 / 14:00–18:00 = 高峰**，其余（含夜间、周末）= **空闲**；
   空闲价 = 高峰价的一半。★**法定节假日**官方也算空闲，但本地没有日历数据 ⇒ 这里**只识别周末**，
   节假日当天会被算成高峰（已在 docs/02 §20 记明）。

本模块**不 import `app.ai`**（那会把 openai SDK 拖进来）：端点解析自己来，口径与
`ai.resolve_endpoint` 一致（留空即 DeepSeek 官方默认）。
"""
import datetime
import json
import threading
import urllib.request
from pathlib import Path

from .config import BASE_DIR, DEFAULT_BASE_URL

# 累计文件：与 config.json 同一个目录（IgnotusAssistant/）。
# ★冒烟测试一律**注入自己的 path**，不碰这个真文件。
STATS_PATH = BASE_DIR / "stats.json"

# 高峰窗口（**分钟**为单位，本地时间）：工作日 09:00–12:00 与 14:00–18:00。
PEAK_WINDOWS = ((9 * 60, 12 * 60), (14 * 60, 18 * 60))
WEEKEND_FREE = True          # 周六 / 周日全天按空闲（官方 2026-08-23 起的规则）

BALANCE_TIMEOUT = 6          # 秒：余额查询的超时（后台线程里跑，短一点，失败就下次再说）
BALANCE_TTL = 60             # 秒：余额缓存有效期（连点时不必反复打网络）

_LOCK = threading.Lock()
_BAL_LOCK = threading.Lock()
_bal_cache = {"at": None, "key": "", "value": None}
# 今日总量的内存缓存（键 = 文件路径 + 日期）；由 `record_tokens()` 刷新，见 `today_tokens()`。
_tok_cache = {"key": None, "tokens": 0}


# ==================== 今日 token 累计（落盘 + 跨天清零） ====================


def today_str(now=None) -> str:
    """本地日期 `YYYY-MM-DD`（累计文件按它判「是不是今天」）。"""
    return (now or datetime.datetime.now()).strftime("%Y-%m-%d")


def _read(path: Path) -> dict:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001
        # 文件不存在 / 坏了 / 权限不对 —— 一律当「今天还没有数据」，绝不把调用方带崩。
        return {}


def _write(path: Path, data: dict) -> None:
    try:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:  # noqa: BLE001
        # 写不进去（只读盘 / 被占用）不该影响聊天本身 —— 这次只是没记住。
        pass


def load_stats(*, path=None, now=None) -> dict:
    """读累计；**跨天自动清零**（返回的 date 已经是今天）。只读盘、不写盘。"""
    today = today_str(now)
    data = _read(Path(path) if path else STATS_PATH)
    if str(data.get("date", "")) != today:
        return {"date": today, "tokens": 0}
    try:
        tokens = max(0, int(data.get("tokens", 0)))
    except (TypeError, ValueError):
        tokens = 0
    return {"date": today, "tokens": tokens}


def today_tokens(*, path=None, now=None) -> int:
    """今天累计用了多少 token。

    ★带**内存缓存**（键 = 文件路径 + 日期）：读盘只发生在「第一次问」和「换天」时。
    这个函数会被「单击贴图」那条热路径调到（`PetWindow._thinking_content()`），
    而 Windows 上 `read_text()` + 异常构造要 1~2ms —— 那点时间正好压在
    `PATPAT_F1_MS`(50ms) 的预算里，实测会把它挤爆（§20c 的步进断言会红）。
    `record_tokens()` 写完会顺手刷新缓存，所以缓存永不过期。
    """
    p = Path(path) if path else STATS_PATH
    key = (str(p), today_str(now))
    with _LOCK:
        if _tok_cache["key"] == key:
            return int(_tok_cache["tokens"])
        tokens = int(load_stats(path=p, now=now)["tokens"])
        _tok_cache["key"] = key
        _tok_cache["tokens"] = tokens
        return tokens


def record_tokens(n, *, path=None, now=None) -> int:
    """把一次对话的 `usage.total_tokens` 累加进今天；返回累计后的今日总量。

    ★只读**已经返回**的用量字段，不发任何请求 ⇒ 不额外耗 token（用户口径的前提）。
    非正整数 / 脏值一律忽略（宁可少记一次，也不能把累计写坏）。
    """
    try:
        n = int(n)
    except (TypeError, ValueError):
        return today_tokens(path=path, now=now)
    if n <= 0:
        return today_tokens(path=path, now=now)
    p = Path(path) if path else STATS_PATH
    with _LOCK:
        data = load_stats(path=p, now=now)
        data["tokens"] = int(data["tokens"]) + n
        _write(p, data)
        # 顺手刷新缓存：省掉下一次 `today_tokens()` 的读盘（见它那里的说明）。
        _tok_cache["key"] = (str(p), str(data["date"]))
        _tok_cache["tokens"] = int(data["tokens"])
        return int(data["tokens"])


# ==================== 高峰 / 空闲（纯时间函数） ====================


def _next_peak_after(date, *, hour=9):
    """从 `date` 当天起（含当天）第一个**工作日**的 `hour:00`。"""
    d = date
    while d.weekday() >= 5:          # 5=周六 / 6=周日
        d += datetime.timedelta(days=1)
    return datetime.datetime.combine(d, datetime.time(hour, 0))


def peak_state(now=None):
    """当前是高峰还是空闲，以及离**下一次切换**还有多少秒 → `("peak"|"idle", 秒)`。

    规则（官方 2026）：工作日 09:00–12:00 / 14:00–18:00 = 高峰，其余（含夜间、周末）= 空闲。
    ★倒计时的小时数**不封顶**：周五 18:00 之后要一路倒到下周一 09:00（约 63 小时）。
    """
    now = now or datetime.datetime.now()
    secs = now.hour * 3600 + now.minute * 60 + now.second

    if WEEKEND_FREE and now.weekday() >= 5:
        target = _next_peak_after(now.date() + datetime.timedelta(days=1))
        return ("idle", max(0, int((target - now).total_seconds())))

    for start, end in PEAK_WINDOWS:
        if start * 60 <= secs < end * 60:
            return ("peak", int(end * 60 - secs))
    # 空闲：先试今天还没到的高峰起点，都没有就看下一个工作日 09:00
    for start, _end in PEAK_WINDOWS:
        if secs < start * 60:
            return ("idle", int(start * 60 - secs))
    target = _next_peak_after(now.date() + datetime.timedelta(days=1))
    return ("idle", max(0, int((target - now).total_seconds())))


# ==================== 余额查询（GET /user/balance） ====================


def endpoint_of(api):
    """`(api_key, base_url)`；口径与 `ai.resolve_endpoint` 一致（留空即官方默认）。"""
    if isinstance(api, dict):
        key = str(api.get("api_key", "") or "")
        base = str(api.get("base_url", "") or "").strip() or DEFAULT_BASE_URL
        return key, base.rstrip("/")
    return str(api or ""), DEFAULT_BASE_URL


def is_deepseek(api) -> bool:
    """当前 API 是不是 DeepSeek —— 第一类内容「仅在使用的 api 为 deepseek 时显示」的判据。

    ★空 / `None` 一律 **False**：没配 API 不代表「默认就是 deepseek」，那种情况下
    第一类内容（余额等）没有归属的账号，不该显示。
    """
    if not api:
        return False
    _key, base = endpoint_of(api)
    return "deepseek" in base.lower()


def fetch_balance(api, *, timeout=BALANCE_TIMEOUT):
    """`GET {base}/user/balance`；返回原始 JSON dict，失败一律 `None`（不抛）。"""
    key, base = endpoint_of(api)
    if not key:
        return None
    req = urllib.request.Request(
        base + "/user/balance",
        headers={"Authorization": "Bearer " + key, "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (固定 https 端点)
            return json.loads(resp.read().decode("utf-8", "replace"))
    except Exception:  # noqa: BLE001
        # 断网 / key 不对 / 超时 —— 这一句就显示占位符，别影响其它两句。
        return None


def balance_cny(payload):
    """从返回值里取 **CNY** 那条的 `total_balance`（官方是**字符串**）→ float；取不到 `None`。"""
    if not isinstance(payload, dict):
        return None
    infos = payload.get("balance_infos")
    if not isinstance(infos, list) or not infos:
        return None
    pick = None
    for info in infos:
        if isinstance(info, dict) and str(info.get("currency", "")).upper() == "CNY":
            pick = info
            break
    if pick is None:
        pick = infos[0] if isinstance(infos[0], dict) else None
    if pick is None:
        return None
    try:
        return float(pick.get("total_balance"))
    except (TypeError, ValueError):
        return None


def cached_balance(api, *, ttl=BALANCE_TTL, now=None):
    """缓存里的余额（同一个端点才复用）；没有 / 过期 ⇒ `None`（**不发请求**）。"""
    key, base = endpoint_of(api)
    t = now or datetime.datetime.now()
    with _BAL_LOCK:
        if _bal_cache["key"] != base or _bal_cache["at"] is None:
            return None
        if (t - _bal_cache["at"]).total_seconds() > ttl:
            return None
        return _bal_cache["value"]


def refresh_balance(api, *, ttl=BALANCE_TTL, force=False, now=None):
    """取余额：**缓存没过期就直接用缓存**，否则打一次网络并写回缓存；失败保留旧缓存值。"""
    key, base = endpoint_of(api)
    t = now or datetime.datetime.now()
    if not force:
        hit = cached_balance(api, ttl=ttl, now=t)
        if hit is not None:
            return hit
    value = balance_cny(fetch_balance(api))
    with _BAL_LOCK:
        if value is None and _bal_cache["key"] == base and _bal_cache["value"] is not None:
            # 这次没拿到（断网等）→ **别把上次的好数据抹掉**，只把时间往前推一推。
            _bal_cache["at"] = t
            return _bal_cache["value"]
        _bal_cache["key"] = base
        _bal_cache["at"] = t
        _bal_cache["value"] = value
    return value


def prefetch_balance(api, *, force=False):
    """后台线程拉一次余额（**不阻塞 UI**）；返回线程对象，缓存还新鲜时返回 `None`。

    调用点两处：①启动时 `force=True` 预取一次，用户点开气泡前就绪；②每次单击气泡时
    不带 `force` —— 缓存（`BALANCE_TTL` 60s）还没过期就**连线程都不开**，所以连点也不会
    反复打网络。
    """
    if not api:
        return None
    if not force and cached_balance(api) is not None:
        return None

    def _work():
        try:
            refresh_balance(api, force=force)
        except Exception:  # noqa: BLE001
            pass                  # 后台线程里任何异常都不许冒出去

    th = threading.Thread(target=_work, name="balance-prefetch", daemon=True)
    th.start()
    return th

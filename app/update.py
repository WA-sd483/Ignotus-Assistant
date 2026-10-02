"""「检查更新」的内核：版本比较（**纯**）+ 查 GitHub Releases（**唯一联网处**）。

★设计口径
------------------------------------------------
    * **版本比较是纯函数**（`parse_version` / `is_newer`）⇒ 可离线断言，
      不需要网络、也不需要真的打个 release 出来。
    * **联网只有一处**（`check_latest`），而且 HTTP 取回那一步做成**可注入**
      （`fetch=` 参数）⇒ 测试喂一段假 JSON 就能覆盖「有新版本 / 已是最新 /
      仓库还没有 release / 网络挂了」四条分支，**测试里一个字节都不出网**。
    * 返回值一律是**字符串**（本项目的铁律：跨线程只传 str/int）——
      弹窗那边起线程跑它、用 QTimer 取结果，不需要任何 Qt 对象跨线程。
"""
import json
import urllib.error
import urllib.request

# 仓库（与 README 里的 Releases 链接一处口径；git remote 也是它）
REPO = "WA-sd483/Ignotus-Assistant"
RELEASES_PAGE = "https://github.com/%s/releases" % REPO
API_LATEST = "https://api.github.com/repos/%s/releases/latest" % REPO

# `check_latest` 的四态。★用常量而不是裸字符串：调用方（弹窗）要按它分流。
STATE_UPDATE = "update"    # 有新版本
STATE_LATEST = "latest"    # 已是最新
STATE_NONE = "none"        # 仓库里还没有发布过任何 release
STATE_ERROR = "error"      # 网络 / 解析失败

# GitHub API 要求带 UA，不带会被 403（这条不写会让人以为是「没发布过」）
_UA = "IgnotusAssistant-UpdateCheck"


def parse_version(text) -> tuple:
    """把 `'v1.2.3'` / `'1.2.3-beta'` 解析成可比较的整数元组。

    ★只取**每一段开头的连续数字**，遇到第一段取不出数字就**停下**：
      `'1.2.3-beta'` → `(1, 2, 3)`；`'v2.0'` → `(2, 0)`。
      预发布标记（`-beta` / `-rc1`）刻意**不参与比较** —— 本项目没有稳定的
      预发布命名法，硬比较只会把「1.2.3-beta 比 1.2.3 新还是旧」变成一个
      需要产品决策的问题，而这里只是个「有没有新版」的提示。
    ★解析不出来（`''` / `'abc'` / `None`）返回**空元组**，由调用方判成「不是更新」。
    """
    raw = str(text or "").strip()
    if raw[:1] in ("v", "V"):
        raw = raw[1:]
    parts = []
    for seg in raw.split("."):
        digits = ""
        for ch in seg.strip():
            if ch.isdigit():
                digits += ch
            else:
                break
        if not digits:
            break
        parts.append(int(digits))
    return tuple(parts)


def is_newer(latest, current) -> bool:
    """`latest` 是否比 `current` 新。

    ★**补零对齐后比较**：`(1, 2)` 与 `(1, 2, 0)` 视为相等（`v1.2` 和 `v1.2.0` 是同一版）。
    ★任一边解析不出来 ⇒ 一律 `False`（宁可漏报，也不能误报「有更新」把人骗去下载）。
    """
    a, b = parse_version(latest), parse_version(current)
    if not a or not b:
        return False
    n = max(len(a), len(b))
    a = a + (0,) * (n - len(a))
    b = b + (0,) * (n - len(b))
    return a > b


def _http_get(url: str, timeout: float) -> str:
    """默认的 HTTP 取回：返回响应体文本。**唯一真的出网的一行。**

    ★带 `User-Agent`：GitHub 的 API 对无 UA 的请求直接 403，而 `urllib` 的默认
      UA 是 `Python-urllib/3.x` —— 实测会被拦，这行不能省。
    """
    req = urllib.request.Request(url, headers={"User-Agent": _UA,
                                               "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (固定 https)
        return resp.read().decode("utf-8", errors="replace")


def check_latest(current, *, fetch=None, timeout: float = 6.0) -> tuple:
    """查最新发布。返回 `(state, detail, url)`（三个都是字符串）。

    四态见上面的 `STATE_*`：
      * `STATE_UPDATE` ⇒ detail = 新版本号，url = 该 release 页面
      * `STATE_LATEST` ⇒ detail = 当前版本号
      * `STATE_NONE`   ⇒ 仓库还没发布过（HTTP 404）—— **不是错误**，是新仓库的正常状态
      * `STATE_ERROR`  ⇒ 网络 / 解析失败，detail 里带一句人话的原因

    ★`fetch(url, timeout) -> str` 可注入（测试不联网）；默认走 `_http_get`。
    ★**任何异常都不许漏出去**：这个函数是在后台线程里跑的，异常会让线程静默死掉
      （本项目最怕的一种）⇒ 全部收成 `STATE_ERROR`。
    """
    fetch = fetch or _http_get
    try:
        raw = fetch(API_LATEST, timeout)
    except urllib.error.HTTPError as e:
        # 404 = 这个仓库还没有任何 release（新仓库的正常状态，别报成「检查失败」）
        if getattr(e, "code", None) == 404:
            return STATE_NONE, "仓库还没有发布版本。", RELEASES_PAGE
        return STATE_ERROR, "检查更新失败（HTTP %s）。" % getattr(e, "code", "?"), RELEASES_PAGE
    except Exception:  # noqa: BLE001  网络超时 / DNS / 代理…
        return STATE_ERROR, "检查更新失败：连不上网络（可稍后再试）。", RELEASES_PAGE

    try:
        data = json.loads(raw)
        tag = str(data.get("tag_name") or data.get("name") or "")
        page = str(data.get("html_url") or RELEASES_PAGE)
    except Exception:  # noqa: BLE001  返回体不是 JSON（代理页 / 限流页）
        return STATE_ERROR, "检查更新失败：返回内容看不懂（可能被代理拦截）。", RELEASES_PAGE

    if not parse_version(tag):
        return STATE_NONE, "仓库还没有发布版本。", RELEASES_PAGE
    if is_newer(tag, current):
        return STATE_UPDATE, tag, page
    return STATE_LATEST, str(current), page

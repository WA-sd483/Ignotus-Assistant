"""patpat 模式：左键抚摸角色贴图时，在贴图**之上**叠一只「手」（抬起 → 下压 → 抬起）+ 一段摸摸音效，
贴图**自己也会被压一下**（十九改 / 二十改）。

用户口径（2026-09-20）：
- 开关放进「通用设置 → 模式切换」与「右键角色贴图菜单」两处，**与其他模式不冲突**（可直接打开）；
- 开 / 关各弹一条提示（文案「patpat模式启动」/「patpat模式关闭」，落点 = 贴图上方那条状态气泡）；
- 开着时**左键点击**贴图：按顺序播 `抬起` → `下压` → `抬起`（三帧 **50 / 150 / 100 ms**，
  合 300ms，二十改），同时随机播 `voices/patpat/` 里的一段；
- **连点 = 截断重播**（二十改明确成硬承诺）：掐掉上一轮的两个定时器 + 形变 + 那只手 +
  **正在播的音效**，再从头来一轮（帧序号回 0、形变回原形、音效 `stop()` → `setPosition(0)` 重新起）；
- **单击时角色贴图自己也形变** —— 站姿 高 −35px、宽两侧各 +12px；**节能态单独一套**
  （高 −20px、宽每侧 +8px）。基准恒为**底边不动**，只在「下压」那一帧压，进出各 80ms 平滑；
  上层那只手**不参与形变**，位置只跟着贴图下沉、横向不动；
- 叠加图的显示尺寸**与角色同口径**缩放（用角色那一个缩放系数）；
- 位置：普通态 = 叠加图**左上角**与贴图左上角重合；节能态 = 叠加图**左下角**落在贴图
  「自下往上 3/8」的高度处（横向仍与贴图左边对齐）；
- 音效**原声**播放 —— 不跟音量滑块、静音模式也不影响它（用户口径「总是原声」）；
  素材自带的前导静音**保留**（不剪素材、画面也不等声音）。
- ★（二十二改）**两套音效、一次点击只响一套**：模式**开着**播 `voices/patpat/`（上面这条），
  模式**关着**播 `voices/normal_pet/`（`bibu.mp3`）—— 由 `app/pet.py` 各拿一个 `PatPatSound`
  实例分头管，**互不影响、相互独立**。本模块的 `PatPatSound` / `patpat_sounds()` 本来就
  **与目录无关**（吃任意目录），所以两套**共用同一份实现**，不另写播放器。
  ⚠️ 模式开着但**缺手图**时**两套都不播**（用户口径），所以选音效那条分支得用
  `elif not self._patpat`，**不能**用 `else`（见 `app/pet.py::_patpat_play`）。

⚠️ 叠加图**必须画在角色之上**，而它是**独立顶层窗**（与 `_PetBubble` / `_PetToast` 同款），
不是 `PetWindow` 的子控件：节能态下叠加图会**高出贴图窗口的顶边**（爱丽丝 150×100 的扁平贴图
+ 150×113 的手 ⇒ 顶边在 −50px），做子控件会被父窗直接裁掉。

本模块只放**常量 + 纯函数 + 音效播放器**（全都能离屏断言）；
叠加窗与窗口侧的状态机在 `app/pet.py`（`_PatPatOverlay` / `PetWindow`）。
"""
import random
from pathlib import Path

try:  # QtMultimedia 缺失时**不炸 import**：宠物照常跑，只是抚摸没声音
    from PySide6.QtCore import QUrl
    from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer

    _HAS_QTMM = True
except Exception:  # noqa: BLE001
    _HAS_QTMM = False

# ---- 素材位置 ----
# 角色目录（`pet/alice`）**旁边**就是 `pet/patpat` —— 与角色无关，所有角色共用同一套手。
PATPAT_DIR_NAME = "patpat"
# 两张图的文件名标记（真机：`摸摸_抬起.png` / `摸摸_下压.png`）。**按标记找，不按排序找**：
# 依赖 `sorted()` 的话「下压」会排在「抬起」前面（下 U+4E0B < 抬 U+62AC），顺序就反了。
PATPAT_LIFT_MARK = "抬起"
PATPAT_PRESS_MARK = "下压"
_IMAGE_EXTS = (".png", ".jpg", ".jpeg")
_AUDIO_EXTS = (".mp3", ".wav", ".m4a", ".ogg")

# ---- 时长（2026-09-20 二十改：三帧，与**新素材**对齐）----
# 用户口径「贴图替换顺序为 抬起-下压-抬起，每张图维持时间待定」+ 实测新音频后拍板 **50 / 150 / 100**。
# 实测（用 ffmpeg 解码成 f32le 后量包络，-40dBFS 判起振）：
#   pat_0：总长 480ms、起振 **77.5ms**、有效声音到 **194.1ms**、峰值 106.6ms / -6.66dBFS；
#   pat_1：总长 432ms、起振 **71.1ms**、有效声音到 **151.6ms**、峰值  96.1ms / -9.02dBFS；
#   两段尾部各有 ~280ms 静音（20ms 一格的 RMS 显示主要能量集中在 60~160ms）。
# ⚠️ 上一版素材 150/177ms 才起振，所以当时「下压」帧从 130ms 起就够；**这一版早到 71ms** ⇒
#    帧1 必须缩到 50ms，让「下压」帧（50 → 200ms）把两段的**起振点与整段有效声音**都盖住。
#    （仍不剪素材、画面也不等声音：尾部那 ~280ms 静音照原声放完，而手早在那之前就收回来了。）
PATPAT_F1_MS = 50           # 帧1 抬起（必须 < 最短的前导静音 71.1ms）
PATPAT_F2_MS = 150          # 帧2 下压（50 → 200ms，盖住两段的起振与整段有效声音）
PATPAT_F3_MS = 100          # 帧3 抬起（第 1 张图再放一次）
PATPAT_TOTAL_MS = PATPAT_F1_MS + PATPAT_F2_MS + PATPAT_F3_MS   # 300ms → 到点收手
# 三帧分别是**第几张图**（只有 2 张素材，所以第 3 帧是第 0 张再放一次）。
PATPAT_SEQ = (0, 1, 0)
# 左键「点击」与「拖动」的分界（曼哈顿位移，px）：超过它就算拖动（只挪位置、不摸）。
PATPAT_CLICK_SLOP = 6

# ---- 角色贴图形变（十九改；二十改**加大**并**分两套**）----
# 用户口径：单点时角色贴图**自己也压一下**。基准边恒为**底边不动** —— 顶边下沉多少，那只手就跟着下沉多少；
# 只在「下压」那一帧压、抬起帧弹回；进出各 80ms 平滑（两套共用）。
# ★二十改：站姿形变**加大**到 高 35px / 每侧 12px；而**节能态**是扁平贴图（150×100），照同一量压会只剩 65px、
# 矮掉 35%，比站姿那 14% 夸张得多 ⇒ 用户给节能态**单独**定了 高 20px / 每侧 8px。
PATPAT_SQUASH_H = 35            # 站姿：高度压多少
PATPAT_SQUASH_PER_SIDE = 12     # 站姿：宽度**每侧**拉伸多少
PATPAT_SQUASH_W = PATPAT_SQUASH_PER_SIDE * 2   # 站姿：宽度合计拉伸 24
# 节能态（扁平贴图）单独一套 —— 用户口径「节能态高度形变 20px、横向向两侧均拉伸 8px」。
PATPAT_SQUASH_H_PS = 20
PATPAT_SQUASH_PER_SIDE_PS = 8
PATPAT_SQUASH_W_PS = PATPAT_SQUASH_PER_SIDE_PS * 2   # 节能态：合计 +16
PATPAT_SQUASH_MS = 80           # 进入 / 退出各 80ms

# 节能态叠加图的落点：左下角像素位于贴图「自下往上 3/8」的高度处（用户口径「约八分之三」）。
PATPAT_PS_BOTTOM_RATIO = 3 / 8


def _round(v) -> int:
    """四舍五入到整数。

    ⚠️ 不用内建 `round()`：它对本项目这批数会走**银行家舍入**（`round(112.5) == 112`），
    而这里要的是「.5 一律向上」（摸摸图 225×0.5 = 112.5 → 113）。
    """
    return int(v + 0.5)


# FFmpeg 的 `AV_LOG_ERROR`：只留真正的错误，warning / info 一律丢掉。
_AV_LOG_ERROR = 16
_LOG_SILENCED = False


def silence_ffmpeg_logs():
    """把 Qt Multimedia / FFmpeg 那几行**信息日志**关掉（默认开着，抚摸一次刷一屏）。

    用户反馈终端里刷的就是这些（**不是报错**，是 FFmpeg 报自己解析到的音频信息）：

        qt.multimedia.ffmpeg: Using Qt multimedia with FFmpeg version 7.1.5 LGPL ...
        [mp3 @ ...] Estimating duration from bitrate, this may be inaccurate
        Input #0, mp3, from 'voices/patpat/pat_1.mp3':
        Stream #0:0: Audio: mp3 (mp3float), 48000 Hz, stereo, fltp, 192 kb/s

    ★**两条一起才盖得干净**（2026-09-20 真机实测：只做第 1 条还剩 `[mp3 @ ...]` 那一行）：

    1. `QLoggingCategory` 关掉 `qt.multimedia.*` 类别 —— 盖掉 Qt 自己打的、**带类别前缀**的那几行；
    2. 把 FFmpeg 自己的日志级别压到 **`AV_LOG_ERROR`(16)** —— 第 3~5 行是 **libavformat 的 mp3
       解复用器**直接经 `av_log` 打到 stderr 的（**不带类别前缀**，Qt 的日志规则管不到），
       只能调级别。
       ⚠️ 用 `ERROR` 而**不是** `QUIET`：真的解码 / 设备错误照样打出来，只丢 warning / info。

    ⚠️ 必须在**第一个 `QMediaPlayer` 构造之前**调用（插件启动横幅就是那一刻打的）；
       `avutil` 按 PySide6 包里那份 `avutil-*.dll` 找，跟着版本升级也能找到（Qt 静态链接 /
       没有该 dll 时静默跳过，只是回到「吵一点」而已）。幂等，多调几次无所谓。
    """
    global _LOG_SILENCED
    if _LOG_SILENCED:
        return
    _LOG_SILENCED = True
    try:
        from PySide6.QtCore import QLoggingCategory

        QLoggingCategory.setFilterRules("qt.multimedia.*=false")
    except Exception:  # noqa: BLE001 —— 静音失败不影响功能
        pass
    try:  # noqa: SIM105
        import ctypes
        from pathlib import Path

        import PySide6

        pyside_dir = Path(PySide6.__file__).resolve().parent
        for dll in sorted(pyside_dir.glob("avutil-*.dll")):
            ctypes.CDLL(str(dll)).av_log_set_level(_AV_LOG_ERROR)
            break
    except Exception:  # noqa: BLE001 —— 找不到 avutil / 非 Windows：放弃静音，不影响播放
        pass


def patpat_size(nat_w: int, nat_h: int, scale: float):
    """叠加图的显示尺寸：与角色**同一个缩放系数**等比缩放（用户口径「与角色一样比例缩放」）。

    爱丽丝（原 300×500 → 显示 150×250，系数 0.5）：300×225 → **150×113**；
    艾莲（原 256×256 → 显示 250×250，系数 0.9766）：→ **293×220**。
    """
    return (max(1, _round(nat_w * scale)), max(1, _round(nat_h * scale)))


def patpat_pos(sprite, ov_w: int, ov_h: int, *, power_save: bool = False):
    """叠加图窗口的**左上角**（屏幕坐标）。

    - 普通态：**左上角像素与角色贴图左上角重合**（用户口径）；
    - 节能态：**左下角像素**落在「贴图自下往上 `PATPAT_PS_BOTTOM_RATIO`（3/8）」的高度上，
      横向仍与贴图左边对齐。此时叠加图会比扁平贴图**高出一截**（故窗口顶边是负的）——
      这正是它必须是独立顶层窗、不能做子控件的原因。
    """
    if not power_save:
        return (sprite.x(), sprite.y())
    bottom = sprite.y() + sprite.height() - _round(sprite.height() * PATPAT_PS_BOTTOM_RATIO)
    return (sprite.x(), bottom - ov_h)


def _squash_amounts(power_save: bool):
    """按形态取 `(高度压多少, 宽度合计拉伸多少)`。

    站姿与节能态是**两套**量（二十改）：节能态那只扁平贴图只有 100px 高，
    照站姿的 35px 压会矮掉 35%（站姿那套才 14%），所以用户给它单独定了 20px / 每侧 8px。
    """
    if power_save:
        return (PATPAT_SQUASH_H_PS, PATPAT_SQUASH_W_PS)
    return (PATPAT_SQUASH_H, PATPAT_SQUASH_W)


def patpat_squash_size(w: int, h: int, progress, *, power_save: bool = False):
    """角色贴图**形变后**的尺寸：高度压 `H`、宽度向两侧各加 `per_side`（见 `_squash_amounts`）。

    `progress`：0.0 = 原形、1.0 = 压到底（中间值 = 平滑过渡的中间帧）。
    实算（爱丽丝站姿 150×250）：压到底 → **174×215**；
    节能态（扁平 150×100）：压到底 → **166×80**。

    ⚠️ 用本模块的 `_round`（「.5 向上」）而不是内建 `round`：窗口尺寸、手的下沉量两处
    必须**同一套取整口径**，否则手会比贴图多/少 1px。
    """
    h_amt, w_amt = _squash_amounts(power_save)
    p = max(0.0, min(1.0, float(progress)))
    return (max(1, w + _round(w_amt * p)), max(1, h - _round(h_amt * p)))


def patpat_squash_drop(progress, *, power_save: bool = False) -> int:
    """形变时贴图**顶边下沉**了多少 px（= 那只手要跟着往下挪的量）。

    基准边是底边（不动），所以顶边下沉量就等于高度被压掉的量。
    """
    h_amt, _ = _squash_amounts(power_save)
    p = max(0.0, min(1.0, float(progress)))
    return _round(h_amt * p)


def _images_in(d: Path) -> list:
    if d is None or not d.exists():
        return []
    out = []
    for ext in _IMAGE_EXTS:
        out += sorted(d.glob(f"*{ext}"))
    return out


def patpat_frames(pet_dir):
    """角色目录 `pet_dir`（如 `pet/alice`）旁边的 `patpat/` 里的两张手图。

    返回 `(抬起 Path, 下压 Path)`；缺任何一张都返回 `None`（此时抚摸只当没这回事）。
    """
    d = Path(pet_dir).parent / PATPAT_DIR_NAME
    lift = press = None
    for f in _images_in(d):
        if lift is None and PATPAT_LIFT_MARK in f.stem:
            lift = f
        elif press is None and PATPAT_PRESS_MARK in f.stem:
            press = f
    return (lift, press) if (lift is not None and press is not None) else None


def patpat_sounds(sound_dir) -> list:
    """`voices/patpat/` 下的音频（按文件名排序，保证「随机」的结果可复现 / 可断言）。"""
    d = Path(sound_dir) if sound_dir else None
    if d is None or not d.exists():
        return []
    out = []
    for ext in _AUDIO_EXTS:
        out += sorted(d.glob(f"*{ext}"))
    return sorted(out)


class PatPatSound:
    """一次性音效：**给一个目录、随机挑一段、原声（100%）播一次**，不循环。

    ★（二十二改）**与目录无关、两套共用**：patpat 模式用 `voices/patpat/`、非模式单击用
    `voices/normal_pet/` —— 各建一个实例（各连自己的目录）即可，**互不读写对方素材**。
    类名保留了 `PatPatSound`（它出身于 patpat 那一路），但现在就是个「目录无关的一次性 mp3 播放器」。

    为什么不用 `tts.play_wav`：那条路只吃 **wav**（`wave` 模块读头 + `sounddevice` 推流），
    而 patpat / normal_pet 的素材都是 **mp3**。本机 Qt 6 自带 FFmpeg 后端，`QMediaPlayer`
    直接能播，**零新增依赖**（实测 240ms、无 error）。

    ⚠️ 播放器**懒建**：`QMediaPlayer` 首次构造要 ~0.27s（后端初始化），
    不能放在 `PetWindow.__init__` 里拖慢启动。
    """

    def __init__(self, sound_dir=None):
        self._dir = Path(sound_dir) if sound_dir else None
        self._cache = None          # 目录里的音频列表（只扫一次）
        self._player = None
        self._out = None
        self._failed = False        # 后端不可用（或无 QtMultimedia）→ 之后不再重试
        self._last = None           # 最近一次**真的播出去**的那一段（冒烟测试用）

    # ---- 素材 ----
    def set_dir(self, sound_dir):
        self._dir = Path(sound_dir) if sound_dir else None
        self._cache = None

    def sounds(self) -> list:
        if self._cache is None:
            self._cache = patpat_sounds(self._dir)
        return self._cache

    def pick(self):
        """随机挑一段（没有素材 → `None`）。"""
        items = self.sounds()
        return random.choice(items) if items else None

    @property
    def last_played(self):
        """最近一次播出去的那一段（没播过 → `None`）。"""
        return self._last

    def is_available(self) -> bool:
        """后端能不能用（没素材 / 没 QtMultimedia / 建播放器失败 → False）。"""
        return bool(self.sounds()) and _HAS_QTMM and not self._failed

    # ---- 播放 ----
    def _ensure(self) -> bool:
        if self._player is not None:
            return True
        if self._failed or not _HAS_QTMM:
            return False
        # ⚠️ 必须排在 `QMediaPlayer()` **之前**：FFmpeg 后端的启动横幅与 mp3 解复用的那几行
        # 就是那一刻开始打的（见 `silence_ffmpeg_logs()`）。
        silence_ffmpeg_logs()
        try:
            self._player = QMediaPlayer()
            self._out = QAudioOutput()
            # **原声**：用户口径「总是原声」—— 不读音量滑块、也不看静音模式。
            self._out.setVolume(1.0)
            self._player.setAudioOutput(self._out)
        except Exception:  # noqa: BLE001
            self._failed = True
            self._player = None
            return False
        return True

    def play(self):
        """随机播一段，返回选中的那段路径（没有素材 / 后端不可用 → `None`，安静地什么都不做）。

        连点会**重播**：先 `stop()` 再 `setPosition(0)`（实测：播到 `EndOfMedia` 之后
        直接 `play()` 不一定重头开始，必须先归零）。
        """
        p = self.pick()
        if p is None:
            return None
        self._last = p
        if not self._ensure():
            return p
        try:
            self._player.stop()
            self._player.setSource(QUrl.fromLocalFile(str(p)))
            self._player.setPosition(0)
            self._player.play()
        except Exception:  # noqa: BLE001
            self._failed = True
        return p

    def stop(self):
        """停下当前这一段（关掉模式 / 退出程序时）。"""
        if self._player is None:
            return
        try:
            self._player.stop()
        except Exception:  # noqa: BLE001
            pass

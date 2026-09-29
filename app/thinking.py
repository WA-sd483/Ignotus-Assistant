"""思考气泡（**第二款气泡**）：非 patpat 模式单击贴图时，在贴图**旁边**依次淡入一叠「思考泡泡」。

用户口径（2026-09-21）：

- **非 patpat 模式**单击贴图 → 除了贴图形变 + 播 `voices/normal_pet/`，还要**按顺序**依次淡入
  三帧 `thinking_0.png` / `thinking_1.png` / `thinking_2.png`，**每帧淡入 100ms**；
- 三帧是**层层叠加**（0 亮完保留、再叠 1、再叠 2），不是逐个替换；
- ★ `thinking_fin.png` **不播放** —— 它只用来**定三帧的相对位置**（本模块的
  `THINKING_CANVAS` / `THINKING_OFFSETS` 就是照着它量出来的），拍板原话「仅播放三帧，
  thinking_fin 仅是用于参考三帧的相对位置」；
- 三帧全亮后**停留 1.5s**，然后淡出；
- 位置与**第一款气泡（桌宠聊天气泡 `_PetBubble`）完全同一套规则**：锚点走 `bubble_anchor(...)`、
  朝向优先「左侧 + 尾巴朝下」，左侧空间不足翻右侧、上方空间不足翻下方；
- ★翻过去时**整张画布连同三帧一起镜像**（尾点跑到另一侧）—— 用户口径「整体镜像」。

**二十三改（2026-09-21）：气泡里放文字 + 跟着贴图等比缩放 + 文字自己淡入淡出。**

- **缩放**：用户口径「我说的按贴图一样的缩放指的是贴图在文件夹内的原图尺寸为 300×500，
  但实际贴图在桌面的显示尺寸是按一定比例缩放后再显示的，所以我要求新添加的第二款聊天气泡
  也要按相同的比例进行尺寸的缩小后显示」⇒ **比例 = 贴图显示宽 ÷ 贴图原图宽**
  （爱丽丝 300×500 → 显示 150×250 ⇒ **0.5×**：画布 248×228 → **124×114**，文字一起缩）。
  ★站姿与节能态**用同一个比例**（节能图 300×200、显示宽仍是 150 ⇒ 也是 0.5×），
  所以两种形态下气泡**尺寸相同**。见 `thinking_scale`。
- **内容**：每次单击随机出 **一句**。池子 = 第一类（deepseek 才进）+ 角色台词；
  ★第一类**拆成 2 句**（余额 / 峰谷倒计时）—— 所以爱丽丝（台词 2 句）的池子是 **4 句**、
  非 deepseek 时只剩 **2 句**。
  ★★**2026-09-27（用户要求）**：用户报「今日 token 用量显示不准确」⇒ 拍板「**直接将这项显示内容
  去掉，其他内容保留**」⇒ 原第一类里的「今日 Token 用量」那一句**整项删除**：
  `token_line()` / `THINKING_KIND_TOKENS` / `_fmt_tokens()` 一并删掉，`thinking_pool()` 的
  `tokens=` 形参也去掉（连 `PetWindow._thinking_content()` 的取数一起）。
  ⚠️ **底层累计照旧保留**（`ai.py` 的用量出口仍接 `stats.record_tokens`、`stats.json` 仍落盘）——
  删的只是**显示**，不是统计。
- **文字不镜像**：画布（三帧）整体镜像，**文字只跟着换位置、字本身不翻**
  （`thinking_text_rect` 用的是与 `thinking_frame_rect` **同一套** `p → 尺寸 − p`）。
- **文字纯不透明度通道**（用户口径「气泡存在淡入淡出动画，但文字显示没有淡入淡出，需要为
  文字加上淡入淡出效果」）：
  - 淡入 = **三帧全亮后立即** 100ms（`THINKING_TEXT_FADE_MS`，用户口径「淡入在气泡完全
    显示后 100ms 淡入」）；
  - 淡出 = **跟着气泡一起**（文字不透明度与整条气泡的相乘 ⇒ 不用单独排一段动画）；
  - 连点换句 = 旧字**直接消失**、新字 100ms 淡入，★**这 100ms 计入那 2s 的换句间隔**
    （换句定时器仍是整 2s 周期，不因这 100ms 顺延）。见 `app/pet.py::_ThinkingOverlay`。
- **连点**：连点期间**不重放三帧淡入**，只在原地每 `THINKING_SWITCH_MS`(2s) 换一句；
  切换次数**只由时间决定**（`thinking_switch_delay` 就是这条口径的纯函数），与点击次数无关；
  停手后回到普通「停 1.5s → 淡出」，而 1.5s + 淡入 300 + 淡出 200 正好 = **2s**
  （= `THINKING_LIFE_MS` = 连点窗口 = 换句节拍，见 `THINKING_HOLD_MS` 处的推导）。
  见 `app/pet.py::_ThinkingOverlay.play/_mash`。

⚠️ 与那只手（`_PatPatOverlay`）同样必须是**独立顶层窗**：气泡会伸出贴图窗口的边界
（自尾尖往左最多 220px、往上最多 219px），做子控件会被父窗直接裁掉。

本模块只放**常量 + 纯函数**（全都能离屏断言）；叠加窗与状态机在 `app/pet.py`
（`_ThinkingOverlay` / `PetWindow`）。
"""
from pathlib import Path

# ---- 素材 ----
# 三帧**按顺序**（= 播放顺序），文件名是死的（用户直接放在 `assets/icon/` 下）。
# ★这里**没有** `thinking_fin` —— 它只用来量位置，不参与播放。
THINKING_FRAME_FILES = ("thinking_0.png", "thinking_1.png", "thinking_2.png")
THINKING_REF_FILE = "thinking_fin.png"      # 参考图（只用于量位置，不播放）
_IMAGE_EXTS = (".png", ".jpg", ".jpeg")

# ---- 画布与三帧落点（2026-09-21 照 `thinking_fin.png` 量出来）----
# 四张图是**同一张画布的不同图层**：`thinking_fin` 是全集，三帧各是它的一个部件。
# 量法：把 fin 做连通域拆分，得到三个部件的内容 bbox，再与各帧自身的内容 bbox 对齐
# （三处**尺寸完全相等**，可确认是同一套图层）：
#   fin 部件 ① 小圆点 26×17 @ (194,202) ← thinking_0 内容 26×17
#   fin 部件 ② 中圆点 29×19 @ (161,172) ← thinking_1 内容 29×19
#   fin 部件 ③ 大椭圆 224×149 @ ( 12,  9) ← thinking_2 内容 224×149
# ⇒ 各帧「画布左上角」落在 fin 画布里的位置 = 部件原点 − 自身内容 bbox 原点。
# ⚠️ 换了素材必须重新量（`tests/smoke_pet.py` 会用 PIL 从真实 PNG 重算一遍并核对，
#    对不上就是红的）。
THINKING_CANVAS = (248, 228)                # = `thinking_fin.png` 的尺寸
THINKING_OFFSETS = ((186, 193), (156, 166), (5, -1))
# 基准朝向（左 + 尾朝下）下「**尾巴尖**」（最外侧那个小圆点的外沿）在画布里的位置。
# 它就是贴在贴图边上的那一点 —— 与聊天气泡的锚点 A 对齐（`bubble_anchor`）。
# 小圆点内容 bbox 在 fin 里是 (194,202)-(220,219) ⇒ 外沿 = (220, 219)。
THINKING_TAIL_TIP = (220, 219)

# ---- 时序 ----
THINKING_FADE_MS = 100      # **每帧**淡入时长（用户口径「每个淡入时长 100ms」）
# **文字**自己的淡入时长（二十三改·二轮）：三帧**全亮之后立即**起，只淡入不单独淡出
# （淡出走「与气泡一起」那条：文字不透明度乘上整条气泡的不透明度即可）。
# ★连点换句时这 100ms **算在那 2s 里**（换句定时器周期仍是整 `THINKING_SWITCH_MS`）。
THINKING_TEXT_FADE_MS = 100
THINKING_HOLD_MS = 1500     # 三帧全亮之后停留多久（★★2026-09-29 由 1000 改成 1500 —— 见下）
THINKING_OUT_MS = 200       # 整体淡出时长（与聊天气泡的 `BUBBLE_FADE_MS` 同值，观感一致）
# 三帧淡入这一段的总时长（整条淡入动画的驱动时长，**线性**推进）。
THINKING_IN_TOTAL_MS = THINKING_FADE_MS * len(THINKING_FRAME_FILES)
# ★★**一轮气泡的完整寿命** = 淡入 + 停留 + 淡出（= 从「单击」到「窗口真的隐藏」）。
#   2026-09-29 用户口径：「**气泡的显示时长与连点时一次内容显示时长设为一致**」
#   ⇒ 它必须 == `THINKING_SWITCH_MS`（连点时一句内容停留 2s）== `THINKING_MASH_MS`（连点窗口）。
#   三个 2s 对齐之后，还白捡一条性质：**气泡一旦消失，距上一次点击必然已 > 连点窗口**
#   ⇒ 「气泡消失后再点」天然就是**新一轮**（必定重新抽句）—— 见 `_ThinkingOverlay.play()`。
#   ★所以 `THINKING_HOLD_MS` 不是随手填的：1500 = 2000 − 300 − 200。改淡入 / 淡出要**一起改它**。
THINKING_LIFE_MS = THINKING_IN_TOTAL_MS + THINKING_HOLD_MS + THINKING_OUT_MS

# ---- 连点（二十三改）----
# 用户口径「若出现连点的情况则连点过程中每两秒随机切换内容，此时的切换次数仅由时间决定
# 而非连点次数」⇒ 2s 是**时间网格**，点击只把气泡续命、不重置网格，也不重放三帧淡入。
THINKING_SWITCH_MS = 2000
# 「连点」的判定窗口：**相邻两次单击**的间隔不超过它就算连点
# （★判据看的是「距**上一次**单击」，`_mash_origin` 每次点击都续期，见 `_ThinkingOverlay.play()`）。
# ★2026-09-22 用户口径「把 1.5s 改为两秒」⇒ 直接定 **2000**。
#   原先按「一轮气泡的完整寿命」算：淡入 300 + 停留 1000 + 淡出 200 = 1500ms。
#   现在它与换句节拍 `THINKING_SWITCH_MS` 同值（都是 2s）。
# ★★2026-09-29：**一轮寿命也改成了 2s**（`THINKING_LIFE_MS`，见上）⇒ 三个 2s 完全对齐。
#   ★但**窗口相等不等于判据够用**：「距上一次点击 ≤ 2s」在**气泡已经收掉**的那一段
#   （新一轮 1.5s / 续命后 1.7s 起，到窗口 2s 满 —— 即那 **0.3~0.5s**）仍会成立 ——
#   若只看时间，那一下会被当成「连点续命」而不重新抽句 ⇒ 用户看到的就是
#   「**气泡没了，再点还是上一条**」（2026-09-29 报的）。
#   ⇒ `play()` 里必须**同时**要求 `is_shown()`（见那边的说明）。
THINKING_MASH_MS = 2000

# ---- 缩放（二十三改·二轮改口径）----
# ★比例 = **贴图在屏显示宽 ÷ 贴图原图宽**（不是「显示高 ÷ 某个基准高度」）。
#   爱丽丝：原图 300×500、在屏 150×250 ⇒ 150/300 = **0.5**；节能图 300×200、在屏宽仍是 150
#   ⇒ 同样 **0.5**（⇒ 两种形态下气泡尺寸一致）。
# ⚠️ 本模块**不** import `app.pet`（免得循环依赖）：比例由 `PetWindow` 算好、
#   经 `_ThinkingOverlay.set_scale_provider()` 注入 —— 这里只负责「拿比例算尺寸」。

# ---- 内容（二十三改；★2026-09-27 去掉「今日 Token 用量」）----
# 池子的「第一类内容」。每一类**各自**是独立候选，不是把几行合成一块。
# ★`THINKING_KIND_TOKENS = "tokens"` **已删** —— 随「今日 Token 用量」整项下线（见模块 docstring）。
THINKING_KIND_BALANCE = "balance"
THINKING_KIND_PERIOD = "period"

# 角色台词（第二类）：**按角色分表**。用户 2026-09-21 拍板「艾莲台词暂不显示，之后再做补充」
# ⇒ `ellen` 留空；换角色只换这张表，池子组装逻辑不用动（池子大小 = 3 + 台词数）。
THINKING_ROLE_LINES = {
    "alice": ("光啊——！！", "邦邦卡邦"),
    "ellen": (),
}
# 表里没有的角色用这一组（**空** = 该角色没有台词，池子里只有第一类）。
THINKING_FALLBACK_LINES = ()

# 取不到数时的占位（★仍然**照常进池子** —— 保证「deepseek 时池子恒为 4 句」这条口径稳定，
# 不会因为一次请求失败就把某一句悄悄抽掉）。
THINKING_UNKNOWN = "—"

# ---- 文字（二十三改；二轮把字号调大）----
# 配色依据：气泡本体是**近白底**（采样 `assets/icon/thinking_2.png` 主色 = (248,248,248)，
# 描边 ≈ #084078）⇒ 深蓝系最协调、对比也够。
# 标签行用 design.md 的「深蓝 #2F74BF」，数值行再深一档、与描边同色（主信息更醒目）。
THINKING_TEXT_FONT = "Microsoft YaHei UI"
# 字号（**基准画布 px**，绘制时乘缩放系数）。二轮用户口径「气泡内显示的文字字体大小可以适当
# 增大」+「要保证文字尺寸能完整在气泡内显示」⇒ 从 12/16 提到 20/26（数值行**恒大于**标签行，
# 用户口径「可以将数值的那一行设置的比上一行字体更大」）。
# ★这两个数字是**量出来的**，不是拍的（真机字体 msyh.ttc 实测；★2026-09-27 复量过一次）：
#   标签 20px：「当前为高峰时段」= 140px（最宽标签；★原最宽的「今日 Token 用量」148px 已随该项删除）
#   数值 26px：「光啊——！！」    = 160px（最宽台词）、行盒高 33；「167:59:59」= 117px
#   ⇒ 两行块 25 + 2 + 33 = 60，最宽一行 160 ⇒ 文字块宽仍取 164（见下；★最宽行是台词，不是标签）
#   （上一轮记的是 147/161/32/119，本次复量 148/160/33/117 —— 字体度量差 1px 属正常；
#     `tests/smoke_pet.py` §23h 是**动态量**的，不吃这几个数。）
THINKING_LABEL_PX = 20
THINKING_VALUE_PX = 26
THINKING_LABEL_COLOR = "#2F74BF"
THINKING_VALUE_COLOR = "#084078"
# 文字块（**基准画布坐标**）。落在 `thinking_fin` 那个大椭圆（实测实体 bbox
# `(12,9)-(235,157)`，中心 `(123.5, 83.0)`）里，取 **164×92 @ (42,37)** ⇒ 块心 `(124, 83)`，
# 与椭圆同心；宽 164 ≥ 最宽一行 161（留 3px），四角 + 逐行左右端点已用真实 alpha 掩膜验过
# 全在实体内（`tests/smoke_pet.py` §23h 会拿 PIL 重算一遍）。
THINKING_TEXT_RECT = (42, 37, 164, 92)
THINKING_LINE_GAP = 2           # 标签行与数值行之间的额外行距

# ---- 让位 ----
# 迟滞 / 平移动画时长**与聊天气泡同口径**（用户口径「有左侧/上侧空间不足时往右侧/下侧显示的
# 功能」≈ 第一款气泡那一套；`tests/smoke_pet.py` 有断言钉住「与 `BUBBLE_FLIP_*` 相等」）。
THINKING_FLIP_HYST = 20     # px：已经在右侧 / 下方时，要重新多出这么多才翻回去
THINKING_FLIP_MS = 500      # 翻转 = **平移**（与聊天气泡同款，不是重建）

SIDE_LEFT = "left"
SIDE_RIGHT = "right"
FACE_DOWN = "down"
FACE_UP = "up"


def _round(v) -> int:
    """四舍五入到整数（「.5 一律向上」）。

    ⚠️ 不用内建 `round()` —— 它对 `.5` 走**银行家舍入**；本模块与 `app/patpat.py`
    用同一套取整口径，免得两边差 1px。
    """
    return int(v + 0.5)


def thinking_frames(icons_dir):
    """三帧的路径（**顺序 = 播放顺序**）；缺任何一张就返回 `[]`。

    缺素材时这一击**只当没这回事**（形变与音效照旧）—— 与「缺手图就不叠手」同一口径。
    """
    d = Path(icons_dir) if icons_dir else None
    if d is None or not d.exists():
        return []
    out = [d / name for name in THINKING_FRAME_FILES]
    return out if all(p.exists() for p in out) else []


def thinking_frame_opacity(progress, index, *, fade_ms=THINKING_FADE_MS,
                           count=len(THINKING_FRAME_FILES)):
    """整条淡入动画推进到 `progress`(0..1) 时，第 `index` 帧的不透明度。

    三帧**依次**起淡（每帧晚 `fade_ms` 开始），各用 `fade_ms` **线性**爬到 1：
    第 0 帧占 `[0, 1) × fade_ms`、第 1 帧 `[1, 2) × fade_ms`、第 2 帧 `[2, 3) × fade_ms`，
    所以整条动画的时长 = `count × fade_ms`（= `THINKING_IN_TOTAL_MS`）。

    ⚠️ 驱动动画必须是**线性**的：带 easing 的话每帧实际淡入时长就不是 100ms 了
    （用户口径是「**每个**淡入时长 100ms」）。
    """
    if index < 0 or index >= count:
        return 0.0
    t = max(0.0, min(1.0, float(progress))) * fade_ms * count
    return max(0.0, min(1.0, (t - index * fade_ms) / float(fade_ms)))


def thinking_tail_tip(side=SIDE_LEFT, face=FACE_DOWN, *, canvas=THINKING_CANVAS):
    """当前朝向下，「尾巴尖」在画布里的位置（镜像后再取）。"""
    w, h = canvas
    tx, ty = THINKING_TAIL_TIP
    if side == SIDE_RIGHT:
        tx = w - tx
    if face == FACE_UP:
        ty = h - ty
    return (tx, ty)


def thinking_frame_rect(index, side=SIDE_LEFT, face=FACE_DOWN, *, sizes,
                        offsets=THINKING_OFFSETS, canvas=THINKING_CANVAS):
    """第 `index` 帧在当前朝向下该画在**画布内**的 `(x, y, w, h)`。

    ★「翻到另一侧时几张图的相对位置也要有对应变化」就是这里：镜像 = 把每个点 `p` 映到
    `尺寸 − p`，于是整帧的左上角也反过来算（`x → W − x − w`）。
    `sizes` 是各帧**实际**像素尺寸（`(w, h)` 列表），由调用方从 QPixmap 取。
    """
    w, h = canvas
    fw, fh = sizes[index]
    dx, dy = offsets[index]
    if side == SIDE_RIGHT:
        dx = w - dx - fw
    if face == FACE_UP:
        dy = h - dy - fh
    return (dx, dy, fw, fh)


def thinking_pos(anchor, side=SIDE_LEFT, face=FACE_DOWN, *, canvas=THINKING_CANVAS, scale=1.0):
    """气泡窗口**左上角**该在哪（屏幕坐标）。

    `anchor` = 聊天气泡那个锚点 A（`app/pet.py::bubble_anchor`，**由调用方算好传进来** ——
    本模块不 import `app.pet`，免得循环依赖）。式子是「锚点 − 尾尖在画布里的位置」：
    尾巴尖与 A 重合 ⇒ 气泡就从她身边往外展开，与第一款气泡同一个贴合点。

    `scale` = 二十三改的等比缩放（`thinking_scale`）：窗口比基准画布小了一圈时，尾尖到左上
    角的距离也要跟着缩，否则「尾巴尖贴住锚点」这条会散 —— 所以这里减的是 `尾尖 × scale`。
    """
    tx, ty = thinking_tail_tip(side, face, canvas=canvas)
    s = float(scale) if scale else 1.0
    return (int(anchor[0]) - _round(tx * s), int(anchor[1]) - _round(ty * s))


def thinking_side(avail, anchor_x, cur=SIDE_LEFT, *, span=None, hyst=THINKING_FLIP_HYST,
                  scale=1.0):
    """气泡该待在贴图的哪一侧：**左边放得下就用左边**，否则让到右边。

    与 `app/pet.py::bubble_side` 同一口径（含迟滞）：已经在右侧时，左侧要多出 `hyst` 才回去 ——
    贴边来回拖不会来回翻。两侧都放不下（屏幕太窄 / 贴图贴着右边）时**保持左侧**：
    往右让只是把气泡推出屏幕，不如不动。

    `scale` = 二十三改的等比缩放：气泡整体变小后，需要的横向空间也跟着小（判据按缩后的尾尖宽）。
    """
    s = float(scale) if scale else 1.0
    sx = _round((THINKING_TAIL_TIP[0] if span is None else span[0]) * s)
    need = sx + (hyst if cur == SIDE_RIGHT else 0)
    if (int(anchor_x) - avail.x()) >= need:
        return SIDE_LEFT
    room = avail.x() + avail.width() - int(anchor_x)
    return SIDE_RIGHT if room >= sx else SIDE_LEFT


def thinking_face(avail, anchor_y, cur=FACE_DOWN, *, span=None, hyst=THINKING_FLIP_HYST,
                  scale=1.0):
    """尾巴朝哪边：**锚点上方放得下就朝下**（气泡挂在她上边），否则朝上（挂到下边）。

    `anchor_y` 一律传**面朝下那个锚点**的 y（= `bubble_anchor(..., face=FACE_DOWN)` 的 y）——
    与 `bubble_face` 同口径：问的永远是「如果朝下，上方够不够」。
    `scale` 同 `thinking_side`。
    """
    s = float(scale) if scale else 1.0
    sy = _round((THINKING_TAIL_TIP[1] if span is None else span[1]) * s)
    need = sy + (hyst if cur == FACE_UP else 0)
    if (int(anchor_y) - avail.y()) >= need:
        return FACE_DOWN
    below = avail.y() + avail.height() - int(anchor_y)
    return FACE_UP if below >= sy else FACE_DOWN


# ==================== 二十三改：缩放 / 文字 / 内容（全是纯函数） ====================


def thinking_scale(ratio):
    """气泡的等比缩放系数 = **贴图在屏显示宽 ÷ 贴图原图宽**（爱丽丝 150/300 = **0.5**）。

    用户口径（2026-09-21 二轮）原文：「贴图在文件夹内的原图尺寸为 300×500，但实际贴图在桌面的
    显示尺寸是按一定比例缩放后再显示的，所以我要求新添加的第二款聊天气泡也要按相同的比例进行
    尺寸的缩小后显示，否则会显得整体不协调」。

    ★这个比例由 `app/pet.py::PetWindow._thinking_ratio()` 算好注入（本模块不反向 import pet.py），
    这里只做**兜底**：取不到 / 非正数 ⇒ 退化回 1.0（绝不返回 0 —— 那会让窗口变成 0×0、气泡整个消失）。
    """
    try:
        r = float(ratio)
    except (TypeError, ValueError):
        return 1.0
    if r <= 0:
        return 1.0
    return r


def thinking_canvas_size(scale=1.0, *, canvas=THINKING_CANVAS):
    """缩放后气泡窗口该多大（取整口径与 `_round` 一致，避免两边差 1px）。"""
    s = float(scale) if scale else 1.0
    return (_round(canvas[0] * s), _round(canvas[1] * s))


def thinking_switch_delay(elapsed_ms, *, period=THINKING_SWITCH_MS):
    """连点期间「离下一个 2s 切换点还有多久」（毫秒）。

    ★这条就是用户口径「**切换次数仅由时间决定而非连点次数**」的落地：切换点钉在一条
    `0, period, 2×period, …` 的**时间网格**上（原点 = 这一轮第一次单击），点击只把气泡续命，
    不重置网格 —— 所以连点 3 次和连点 10 次，在同一时刻看到的都是同一句。
    """
    p = int(period) if period else THINKING_SWITCH_MS
    if p <= 0:
        return THINKING_SWITCH_MS
    e = int(elapsed_ms) if elapsed_ms and elapsed_ms > 0 else 0
    return p - (e % p)


def thinking_text_rect(side=SIDE_LEFT, face=FACE_DOWN, *, rect=THINKING_TEXT_RECT,
                       canvas=THINKING_CANVAS):
    """文字块在当前朝向下该落在画布里的 `(x, y, w, h)`。

    ★与 `thinking_frame_rect` **同一套镜像**（`p → 尺寸 − p`）：翻到右侧 / 下方时文字块跟着
    挪到镜像后的位置，**但字本身不翻** —— 所以绘制时这一步只用来定位，文字照常正向画
    （见 `app/pet.py::_ThinkingOverlay.paintEvent`）。
    """
    x, y, w, h = rect
    W, H = canvas
    if side == SIDE_RIGHT:
        x = W - x - w
    if face == FACE_UP:
        y = H - y - h
    return (x, y, w, h)


def thinking_role_lines(role_key):
    """某角色的台词（第二类内容）；表里没有该角色 / 台词留空 ⇒ 返回 `()`。"""
    return tuple(THINKING_ROLE_LINES.get(str(role_key or ""), THINKING_FALLBACK_LINES))


def _fmt_money(v):
    """余额：`12.34元`（保留两位）；取不到 ⇒ `—`。"""
    if v is None:
        return THINKING_UNKNOWN
    try:
        return "%.2f元" % float(v)
    except (TypeError, ValueError):
        return THINKING_UNKNOWN


# ★`_fmt_tokens()`（今日 token 千分位格式化）**已删** —— 随「今日 Token 用量」整项下线（2026-09-27）。


def _fmt_hms(secs):
    """倒计时：`HH:MM:SS`（小时**不封顶** —— 周末全天空闲，最长要倒到周一 09:00）。"""
    if secs is None:
        return THINKING_UNKNOWN
    try:
        n = max(0, int(secs))
    except (TypeError, ValueError):
        return THINKING_UNKNOWN
    return "%02d:%02d:%02d" % (n // 3600, (n % 3600) // 60, n % 60)


def balance_line(balance):
    """第一类·余额那一句 → `("剩余余额", "12.34元")`。"""
    return (THINKING_KIND_BALANCE, "剩余余额", _fmt_money(balance))


# ★`token_line(tokens)` **已删** —— 随「今日 Token 用量」整项下线（2026-09-27 用户要求）。


def period_line(state, seconds_left):
    """第一类·峰谷那两句 → 标签随状态变，数值 = 距下一次切换的倒计时。"""
    label = "当前为空闲时段" if state == "idle" else "当前为高峰时段"
    return (THINKING_KIND_PERIOD, label, _fmt_hms(seconds_left))


def thinking_pool(*, deepseek, balance=None, state=None,
                  seconds_left=None, role_key=""):
    """本轮可随机的内容池：`[(kind, 标签, 数值), …]`。

    - **第一类**（余额 / 峰谷倒计时）**只在 `deepseek=True` 时进池子**
      （用户口径「仅在使用的 api 为 deepseek 模型时会显示」）；
    - **第二类** = 角色台词（一句一个候选，数值为空串）；
    - 顺序固定（第一类 2 句在前、台词在后）⇒ 池子大小 = `2 + 台词数`，
      爱丽丝 = **4 句**、非 deepseek 的爱丽丝 = **2 句**。
    - ★★**`tokens=` 形参已删**（2026-09-27）：「今日 Token 用量」整项下线（用户报显示不准，
      拍板「直接把这项显示内容去掉，其他内容保留」）⇒ 调用方**不要再传** `tokens`，
      传了会 `TypeError` —— 这是**故意**留成显式失败，别加 `**kw` 把它兜掉。
    """
    out = []
    if deepseek:
        out.append(balance_line(balance))
        out.append(period_line(state, seconds_left))
    for text in thinking_role_lines(role_key):
        out.append(("line", str(text), ""))
    return out


def pick_content(pool, rng=None, avoid=None):
    """从池子里抽一句，★**尽量不抽到 `avoid`**（= 上一次显示的那一句）；池子空 ⇒ `None`。

    ★★2026-09-29（用户口径）：原实现是**纯均匀随机**，池子只有 2 条时（无 API ⇒ 第一类
    「余额 / 峰谷」整类不进池子，就剩爱丽丝那两句台词）**连点重复概率 50%** ——
    用户报「出现重复显示的概率极大」。用户原话：

    > 若内容共为 A、B、C 条，点击桌宠显示了 A 内容，在连续点击的情况下 A 内容持续时间到达
    > 规定的最大值时，进行切换，切换时 A 排除到随机的队列之外（**仅将上一次显示的内容排除到
    > 随机的队列外**），以此确保连续点击时能定时显示不同内容物。

    ⇒ 只做「**排除紧邻的上一条**」，**不是**维护「已看过」的洗牌队列：三条时 A → {B,C} 抽、
    抽到 B 后 → {A,C} 抽，A/B 短期来回是**允许**的（用户要的就是这一条规则，别自行升级成洗牌）。

    边界（逐条都要显式守住，否则就是新一轮 bug）：
    - 池子空 ⇒ `None`（调用方据此不画字，不抛）；
    - **排除完没得抽**（池子只有 1 条，或 `avoid` 恰好是唯一那条的重复项）⇒ **退回原池子**照抽。
      ⚠️**绝不返回 `None`** —— 池子非空却拿不到内容，表象是「点了半天气泡里没字」，比重复更难查；
    - `avoid` 不在池子里（换角色 / deepseek 开关切换 ⇒ 池子变了 / 余额数值变了）⇒ 等价于不排除；
    - `avoid=None`（本窗第一次抽）⇒ 等价于不排除。

    比较用 `!=` 的**值比较**（池子里是 `(kind, 标签, 数值)` 三元组）：台词逐字相同才算「同一条」；
    余额 / 峰谷倒计时**数值一变就是新内容**，此时不排除正是想要的（它本来就该刷新）。
    """
    items = list(pool or ())
    if not items:
        return None
    r = rng
    if r is None:
        import random as _random
        r = _random
    if avoid is not None and len(items) > 1:
        cand = [it for it in items if it != avoid]
        if cand:                       # ★排除后为空 ⇒ 不改 items（退回原池子），绝不返回 None
            items = cand
    return items[int(r.randrange(len(items)))]

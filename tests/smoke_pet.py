# -*- coding: utf-8 -*-
"""冒烟测试：桌宠的**节能形态**（压扁待机 + 0.6s 变形动画）。

用户要的行为：
  - `pet/<角色>/idle/` 里放的 `角色名_节能.png` 是**节能形态专用图**，
    必须**不进普通帧循环**（否则会跟站姿交替闪烁）；
  - 站姿显示 150×250；节能形态**宽度不变、高度按它自己的比例** → 150×100；
  - 进入节能：高度 250→100 **且**不透明度 100%→30% 同时进行，到 30% 换图，
    再从 30% 升回 100%；整体 0.6s；**底边不动**（原地压扁，不是往上缩）；
  - 退出节能是反向的（先淡到 30% 换回站姿，再一边拉高一边淡回）；
  - 节能期间**保持静态**：切状态（聆听/思考/说话）都不换贴图、不播帧动画；
  - 该角色没有节能图时进不去（保持原样）。

跑法（在项目根目录）：
    .venv\\Scripts\\python.exe tests\\smoke_pet.py
"""
import ast
import inspect
import math
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
try:  # 控制台重定向时保证中文输出可读
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

fails = []
total = [0]


def check(name, ok, detail=""):
    total[0] += 1
    print(("  OK   " if ok else "  FAIL ") + name + (f"  <{detail}>" if detail else ""))
    if not ok:
        fails.append(name)


from PySide6.QtCore import QEasingCurve, QEvent, QPointF, QRect, Qt  # noqa: E402
from PySide6.QtGui import (  # noqa: E402
    QColor, QFont, QImage, QMouseEvent, QPainter, QPainterPath, QPixmap, QTextDocument,
    QTransform,
)
import shiboken6  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication, QGraphicsDropShadowEffect, QGraphicsOpacityEffect, QWidget,
)

from app import pet as petmod  # noqa: E402
from app.pet import POWER_SAVE_MS, POWER_SAVE_SWAP_OPACITY, PetWindow  # noqa: E402

qapp = QApplication.instance() or QApplication(sys.argv)

BASE = Path(__file__).resolve().parent.parent
ALICE = BASE / "pet" / "alice"
ELLEN = BASE / "pet" / "ellen"

# 原图像素尺寸（断言里用得上）：站姿 300×500、节能图 300×200
STANCE_PM_H = 500
PS_PM_H = 200


def new_pet(pet_dir=ALICE, at=(600, 400)):
    w = PetWindow(pet_dir)
    w.move(*at)
    w.show()
    qapp.processEvents()
    return w


print("== 1. 节能贴图不参与普通帧循环 ==")
pet = new_pet()
for st in petmod.STATES:
    files = pet._files_in(st)
    check(f"{st} 的帧列表不含节能专用图",
          all(petmod.POWER_SAVE_MARK not in f.stem for f in files),
          str([f.name for f in files]))
check("idle 只剩站姿 1 帧（300×500）",
      len(pet._frames_for("idle")) == 1
      and pet._frames_for("idle")[0].height() == STANCE_PM_H,
      str(len(pet._frames_for("idle"))))

print("== 2. 两种形态的显示尺寸 ==")
check("站姿基准 = 150×250（高度钉 DISPLAY_HEIGHT、宽度按比例）",
      (pet._normal_w, pet._normal_h) == (150, 250),
      f"{pet._normal_w}×{pet._normal_h}")
check("节能基准 = 150×100（**宽度不变**、高度按节能图自身比例 300×200）",
      pet._power_save_size() == (150, 100), str(pet._power_save_size()))
check("启动时就是站姿尺寸",
      (pet.width(), pet.height()) == (150, 250), f"{pet.width()}×{pet.height()}")

print("== 3. 进入节能：逐帧检查压扁 + 变淡 + 换图 ==")
ps_pm = pet._power_save_pixmap()
check("能取到并加载节能贴图", ps_pm is not None and not ps_pm.isNull())
bottom0 = pet.y() + pet.height()
check("进入节能：真的发生了切换", pet.set_power_save(True) is True)
anim = pet._ps_anim
check("动画已启动、时长 = POWER_SAVE_MS（0.6s）",
      anim is not None and anim.duration() == POWER_SAVE_MS,
      f"{anim.duration() if anim else None}")
anim.stop()   # 停掉真实推进，改成手动逐帧驱动 —— 断言才确定（真动画另在第 8 节验）

snap = {}


def drive(p):
    pet._ps_apply(p)
    snap[p] = (pet.height(), round(pet._label_effect.opacity(), 3),
               pet._label.pixmap().height() if not pet._label.pixmap().isNull() else -1,
               pet.y() + pet.height())


drive(0.0)
check("p=0：还站姿原样（高 250、不透明 1.0、图 300×500）",
      snap[0.0][:3] == (250, 1.0, STANCE_PM_H), str(snap[0.0]))
drive(0.25)
check("p=0.25：高度压到 175、不透明度降到 0.65（两件事同时进行）",
      snap[0.25][:2] == (175, 0.65), str(snap[0.25]))
drive(0.5)
check("p=0.5：高度正好压到 100、不透明度正好 0.30（此刻还没换图）",
      snap[0.5][:3] == (100, POWER_SAVE_SWAP_OPACITY, STANCE_PM_H), str(snap[0.5]))
drive(0.51)
check("p>0.5：已换成节能图（300×200），不透明度仍从 0.30 起",
      snap[0.51][2] == PS_PM_H and snap[0.51][1] > POWER_SAVE_SWAP_OPACITY,
      str(snap[0.51]))
drive(0.75)
check("p=0.75：高度保持 100、不透明度升到 0.65",
      snap[0.75][:2] == (100, 0.65), str(snap[0.75]))
drive(1.0)
pet._ps_finished()
check("p=1：节能形态完全显形（高 100、不透明 1.0、图 300×200）",
      snap[1.0][:3] == (100, 1.0, PS_PM_H), str(snap[1.0]))
check("全程**底边不动**（原地压扁，不是往上缩）",
      all(v[3] == bottom0 for v in snap.values()),
      str({k: v[3] for k, v in snap.items()}))
check("动画基准尺寸切到节能形态", (pet._base_w, pet._base_h) == (150, 100))
check("进入后 is_power_save() 为真", pet.is_power_save())

print("== 4. 节能期间保持静态（切状态也不换图、不动画）==")
check("节能期间帧定时器已停", not pet._timer.isActive())
pet.set_state("speaking")
check("切到 speaking：贴图仍是节能图（没被说话帧顶掉）",
      pet._label.pixmap().height() == PS_PM_H, str(pet._label.pixmap().height()))
check("切到 speaking：不启动帧动画", not pet._timer.isActive())
check("切到 speaking：状态与帧列表已记住（退出时能恢复）",
      pet._state == "speaking" and len(pet._play_frames) > 1,
      f"{pet._state} n={len(pet._play_frames)}")
check("切到 speaking：窗口尺寸仍是节能形态", (pet.width(), pet.height()) == (150, 100))

print("== 5. 退出节能：反向动画（先淡、换回、再拉高）==")
bottom1 = pet.y() + pet.height()
check("退出节能：真的发生了切换", pet.set_power_save(False) is True)
check("退出：动画已启动", pet._ps_anim is not None)
pet._ps_anim.stop()
out = []


def drive_out(p):
    pet._ps_apply(p)
    out.append((pet.height(), round(pet._label_effect.opacity(), 3),
                pet._label.pixmap().height(), pet.y() + pet.height()))


drive_out(0.0)
check("退出 p=0：仍是节能形态原样（高 100、不透明 1.0）",
      out[0][:3] == (100, 1.0, PS_PM_H), str(out[0]))
drive_out(0.5)
check("退出 p=0.5：高度不变、不透明度正好 0.30（还没换图）",
      out[1][:3] == (100, POWER_SAVE_SWAP_OPACITY, PS_PM_H), str(out[1]))
drive_out(0.51)
check("退出 p>0.5：已换回站姿图（300×500）",
      out[2][2] == STANCE_PM_H, str(out[2]))
drive_out(1.0)
pet._ps_finished()
check("退出 p=1：回到站姿（高 250、不透明 1.0、图 300×500）",
      out[3][:3] == (250, 1.0, STANCE_PM_H), str(out[3]))
check("退出全程底边不动", all(v[3] == bottom1 for v in out), str([v[3] for v in out]))
check("退出后基准尺寸回到站姿", (pet._base_w, pet._base_h) == (150, 250))
check("退出后 is_power_save() 为假", not pet.is_power_save())
check("退出后帧动画恢复（说话态的那套帧开始播）", pet._timer.isActive())

print("== 6. 切换回调：只在真的变的时候回调一次 ==")
calls = []
pet.set_on_power_save(calls.append)
check("重复设成同一状态 → 不切换、不回调",
      pet.set_power_save(False, animate=False) is False and calls == [], str(calls))
check("进入（无动画）→ 回调一次 True，且直接落到终态",
      pet.set_power_save(True, animate=False) is True and calls == [True]
      and (pet._base_w, pet._base_h) == (150, 100)
      and pet._label.pixmap().height() == PS_PM_H,
      str(calls))
check("退出（无动画）→ 回调一次 False，尺寸复位",
      pet.set_power_save(False, animate=False) is True and calls == [True, False]
      and (pet._base_w, pet._base_h) == (150, 250),
      str(calls))

print("== 7. 没有节能贴图的角色 ==")
pet2 = new_pet(ELLEN, at=(900, 400))
check("Ellen 没有节能贴图（`_power_save_pixmap()` 为 None）",
      pet2._power_save_pixmap() is None)
check("Ellen 进不了节能：返回 False、状态不变",
      pet2.set_power_save(True) is False and not pet2.is_power_save())
check("Ellen 的 idle 帧照常可用（2 帧）", len(pet2._frames_for("idle")) == 2)

print("== 8. 真动画确实会自己跑完（600ms，走真事件循环）==")
pet3 = new_pet(ALICE, at=(300, 200))
bottom_before = pet3.y() + pet3.height()
t0 = time.time()
check("进入节能（带动画）", pet3.set_power_save(True) is True)
while pet3._ps_anim is not None and (time.time() - t0) < 3.0:
    qapp.processEvents()
    time.sleep(0.01)
dt = time.time() - t0
check("动画自行结束（不是一直挂着）", pet3._ps_anim is None, f"{dt:.2f}s")
check("耗时落在合理区间（0.6s ± 余量）", 0.3 <= dt <= 2.0, f"{dt:.2f}s")
check("结束后：节能态 + 尺寸 150×100 + 不透明度 1.0",
      pet3.is_power_save() and (pet3.width(), pet3.height()) == (150, 100)
      and pet3._label_effect.opacity() == 1.0,
      f"{pet3.width()}×{pet3.height()} op={pet3._label_effect.opacity()}")
check("结束后底边与开始时一致（真动画路径也钉住了底边）",
      pet3.y() + pet3.height() == bottom_before,
      f"{pet3.y() + pet3.height()} vs {bottom_before}")

print("== 9. 聊天气泡：位置与形状（纯算式） ==")
pet4 = new_pet(ALICE, at=(700, 300))
r4 = pet4._sprite_rect()
check("贴图屏幕矩形 = 窗口矩形（150×250，左上 = 窗口左上）",
      (r4.x(), r4.y(), r4.width(), r4.height()) == (700, 300, 150, 250), str(r4))
A_DL = petmod.bubble_anchor(700, 300, 150, 250)
check("锚点：横向 = 贴图左边 −5px（尾巴尖与贴图间隔 5px）", A_DL[0] == 695, str(A_DL))
check("锚点：纵向 = 贴图底边往上 5/7（150×250 → 距贴图顶 71px = y371）",
      A_DL[1] == 300 + 250 - round(250 * 5 / 7) == 371, str(A_DL))
check("文字可用宽 = 120 − 2×(2 + 8) = 100", petmod.bubble_text_width() == 100,
      str(petmod.bubble_text_width()))
check("本体高 = 文字块高 + 2×(2 边框 + 8 内边距)",
      petmod.bubble_body_h(0) == 20 and petmod.bubble_body_h(15) == 35,
      f"{petmod.bubble_body_h(0)}/{petmod.bubble_body_h(15)}")
check("常量口径：120 宽 / **2px 边框** / 圆角 **3**（本体 + 尾巴）/ 尾巴 15 / 间隔 4（尾朝下）·5（尾朝上）"
      " / 距贴图 5 / 锚点 5-7 · 2-7",
      (petmod.BUBBLE_W, petmod.BUBBLE_BORDER, petmod.BUBBLE_RADIUS, petmod.BUBBLE_TAIL_LEG,
       petmod.BUBBLE_TAIL_GAP, petmod.BUBBLE_TAIL_GAP_UP, petmod.BUBBLE_GAP_X,
       round(petmod.BUBBLE_ANCHOR_RATIO, 6), round(petmod.BUBBLE_FLIP_RATIO, 6))
      == (120, 2, 3, 15, 4, 5, 5, round(5 / 7, 6), round(2 / 7, 6)), "常量被改动了")
check("配色：边框 #0C447C / 底 #E6F1FB / 文字 #334155",
      (petmod.BUBBLE_COLOR_BORDER, petmod.BUBBLE_COLOR_FILL, petmod.BUBBLE_COLOR_TEXT)
      == ("#0C447C", "#E6F1FB", "#334155"), "配色被改动了")
check("弹出 / 淡出 / 翻转时长 = 300 / 200 / 500 ms",
      (petmod.BUBBLE_POP_MS, petmod.BUBBLE_FADE_MS, petmod.BUBBLE_FLIP_MS) == (300, 200, 500),
      f"{petmod.BUBBLE_POP_MS}/{petmod.BUBBLE_FADE_MS}/{petmod.BUBBLE_FLIP_MS}")

print("== 9b. 尾巴的两条直角边 a / b 与气泡边框的关系（4 种朝向各核一遍） ==")
SP = (700, 300, 150, 250)
SP_L, SP_R = SP[0], SP[0] + SP[2]
for _side in (petmod.SIDE_LEFT, petmod.SIDE_RIGHT):
    for _face in (petmod.FACE_DOWN, petmod.FACE_UP):
        _name = ("气泡在左" if _side == petmod.SIDE_LEFT else "气泡在右") + \
                ("·尾朝下" if _face == petmod.FACE_DOWN else "·尾朝上")
        _A = petmod.bubble_anchor(*SP, side=_side, face=_face)
        _bx, _by, _bw, _bh = petmod.bubble_body_rect(_A, 120, 35, side=_side, face=_face)
        _tl = petmod.bubble_tail(_A, side=_side, face=_face)
        _sx = -1 if _side == petmod.SIDE_LEFT else 1
        _down = _face == petmod.FACE_DOWN
        check(f"[{_name}] 顶点恒为 (A, a 的远端, b 的上端)：A 在下、b 的上端在 A 正上方 15px",
              _tl[0] == _A and _tl[2] == (_A[0], _A[1] - 15)
              and _tl[1] == (_A[0] + 15 * _sx, _A[1] - (15 if _down else 0)), str(_tl))
        _ds = sorted([math.dist(_tl[0], _tl[1]), math.dist(_tl[0], _tl[2]),
                      math.dist(_tl[1], _tl[2])])
        check(f"[{_name}] 三边 = 15 / 15 / 15√2（等腰直角三角形，直角边恒 15px）",
              abs(_ds[0] - 15) < 1e-6 and abs(_ds[1] - 15) < 1e-6
              and abs(_ds[2] - 15 * math.sqrt(2)) < 1e-6, str([round(d, 3) for d in _ds]))
        check(f"[{_name}] 锚点横向 = 贴图{'左' if _side == petmod.SIDE_LEFT else '右'}边 ±5px",
              _A[0] == (SP_L - 5 if _side == petmod.SIDE_LEFT else SP_R + 5), str(_A))
        check(f"[{_name}] b（竖直腿 A↔顶点2）与气泡{'右' if _side == petmod.SIDE_LEFT else '左'}边框**共线**",
              _tl[0][0] == _tl[2][0] == (_bx + _bw if _side == petmod.SIDE_LEFT else _bx),
              f"边框={_bx + _bw if _side == petmod.SIDE_LEFT else _bx} b={_tl[0][0]}")
        _corner = _tl[2] if _down else _tl[0]        # 直角顶点 = a 与 b 的交点
        _near = _by + _bh + petmod.BUBBLE_TAIL_GAP if _down else _by - petmod.BUBBLE_TAIL_GAP_UP
        check(f"[{_name}] 直角顶点 = a 与 b 的交点，并且**紧贴**那条横边框"
              f"（面朝下在它下方 4px / 面朝上在它上方 5px）", _corner == (_A[0], _near), str(_corner))
        check(f"[{_name}] 本体横向：贴着锚点那条边，往{'左' if _side == petmod.SIDE_LEFT else '右'}展开固定 120px",
              _bw == 120 and (_bx + _bw == _A[0] if _side == petmod.SIDE_LEFT else _bx == _A[0]),
              f"body={(_bx, _by, _bw, _bh)}")
        if _down:
            check(f"[{_name}] a（水平腿）∥ 下边框，且 **a 本身**就在下边框下方 4px",
                  _tl[0][1] - _tl[1][1] == 15 and _tl[1][1] == _by + _bh + petmod.BUBBLE_TAIL_GAP,
                  f"a.y={_tl[1][1]} 下边框={_by + _bh}")
            check(f"[{_name}] 尾巴尖 = A（在气泡下边框下方 19px = 直角边 15 + 间隔 4）",
                  _A[1] == _by + _bh + petmod.BUBBLE_TAIL_LEG + petmod.BUBBLE_TAIL_GAP, str(_A))
            check(f"[{_name}] 锚点纵向 = 贴图底边往上 5/7",
                  _A[1] == SP[1] + SP[3] - round(SP[3] * 5 / 7), str(_A))
        else:
            check(f"[{_name}] a（水平腿 A↔顶点1）∥ 上边框，且在上边框**上方** 5px",
                  _tl[0][1] == _tl[1][1] and _A[1] == _by - petmod.BUBBLE_TAIL_GAP_UP,
                  f"a.y={_A[1]} 上边框={_by}")
            check(f"[{_name}] 锚点纵向 = 贴图底边往上 2/7（= 5/7 的镜像）",
                  _A[1] == SP[1] + SP[3] - round(SP[3] * 2 / 7), str(_A))

print("== 10. 弹出动画：三件套取值 + 控件要装得下全程 ==")
check("p=0：逆时针 15°、缩放 0.30、不透明度 0",
      petmod.bubble_pop_state(0.0) == (-15.0, 0.30, 0.0), str(petmod.bubble_pop_state(0.0)))
check("p=1：0°、缩放 1.00、不透明度 1",
      petmod.bubble_pop_state(1.0) == (0.0, 1.0, 1.0), str(petmod.bubble_pop_state(1.0)))
check("p=0.5：旋转与缩放同步走到中途（−7.5° / 0.65 / 0.5）",
      tuple(round(v, 6) for v in petmod.bubble_pop_state(0.5)) == (-7.5, 0.65, 0.5),
      str(petmod.bubble_pop_state(0.5)))
check("起始旋转角 = 15°（用户第二次改版：45° → 15°）",
      petmod.BUBBLE_POP_ANGLE == 15.0, str(petmod.BUBBLE_POP_ANGLE))
check("p 越界会被钳制到 0~1",
      petmod.bubble_pop_state(-1) == petmod.bubble_pop_state(0.0)
      and petmod.bubble_pop_state(9) == petmod.bubble_pop_state(1.0))
_cx0, _cy0, _cx1, _cy1 = petmod.bubble_content_box(120, 200)
_box = petmod.bubble_pop_bbox(120, 200)
check("并集包围盒按**全程**采样：装得下终态内容（本体 + 尾巴）",
      _box.left() <= _cx0 and _box.top() <= _cy0
      and _box.right() >= _cx1 and _box.bottom() >= _cy1,
      f"{_box} vs {(_cx0, _cy0, _cx1, _cy1)}")
check("并集包围盒比终态更宽更高（旋转途中会把包围盒的角顶出去）",
      _box.width() > 120 and _box.height() > 200 + 19, str(_box))

print("== 11. 气泡的显示 / 跟随 / 文字 ==")
b = pet4._bubble
check("还没叫它时不显示（不透明度 0）", not b.is_shown() and b.pop_pose[2] == 0.0, str(b.pop_pose))
check("空文本不显示（返回 False）", pet4.show_bubble("   ") is False and not b.is_shown())
check("show_bubble 真的把它叫出来了", pet4.show_bubble("你好呀") is True)
check("起始帧就是 p=0 的姿态（全透明起步，再淡入）",
      b.pop_pose == petmod.bubble_pop_state(0.0), str(b.pop_pose))
b._set_frame(*petmod.bubble_pop_state(1.0))          # 跳过动画，直接看终态
check("终态：可见（is_bubble_visible 为真）", pet4.is_bubble_visible() and b.is_shown())
check("气泡文字 = 传进去的那句话", b.text == "你好呀", b.text)
check("本体宽固定 120", b._body_w == 120, str(b._body_w))
check("短句一行：本体高 = 35（离屏行高 15 + 2×(2+8)）", b.body_height == 35, str(b.body_height))
check("本体高 = ceil(文字块高) + 20（量高用的就是画出来那份文档）",
      b.body_height == math.ceil(b._doc.documentLayout().documentSize().height()) + 20,
      f"{b.body_height} vs doc={b._doc.documentLayout().documentSize().height()}")
_short_h = b.body_height
pet4.show_bubble("今天天气不错，很适合出门走走。不过午后可能有阵雨，记得带把伞。")
b._set_frame(*petmod.bubble_pop_state(1.0))
check("换成长句 → 气泡变高（高度随文字量变化）", b.body_height > _short_h,
      f"{_short_h} -> {b.body_height}")
check("文字颜色显式写进字符格式（深色调色板下不会画成白字）",
      b._char_color() == "#334155", b._char_color())
_bimg = b.grab().toImage()


def _bpx(xa, ya):
    """按「锚点坐标系」取像素 —— 与 _body_rect / _text_rect 同一套坐标。"""
    return _bimg.pixelColor(round(xa + b.anchor_point.x()),
                            round(ya + b.anchor_point.y())).name().upper()


_brc = b._body_rect.center().x()
check("真机上画出来的边框色 = #0C447C（取上边框正中）",
      _bpx(_brc, b._body_rect.top() + 1) == "#0C447C",
      _bpx(_brc, b._body_rect.top() + 1))
check("边框真的只有 2px：上边框内侧 3px 处已经是底色（4px 边框时这里仍是深蓝）",
      _bpx(_brc, b._body_rect.top() + 3) == "#E6F1FB",
      _bpx(_brc, b._body_rect.top() + 3))
check("真机上画出来的底色 = #E6F1FB（取文字上方那条内边距带）",
      _bpx(_brc, b._body_rect.top() + 10) == "#E6F1FB",
      _bpx(_brc, b._body_rect.top() + 10))
_ink = set()
_tr = b._text_rect
for _yy in range(round(_tr.top()), round(_tr.bottom())):
    for _xx in range(round(_tr.left()), round(_tr.right())):
        _c = _bimg.pixelColor(round(_xx + b.anchor_point.x()),
                              round(_yy + b.anchor_point.y()))
        if _c.alpha() > 0:
            _ink.add((_c.red(), _c.green(), _c.blue()))
check("真机上画出来的文字色 = #334155（文字区里存在这个纯色）",
      (51, 65, 85) in _ink, str(sorted(_ink, key=sum)[:3]))
check("尾巴顶点 = (A, a 远端, b 上端)：面朝下时 (0,0) / (−15,−15) / (0,−15)（三改：倒过来朝贴图）",
      [(round(p.x()), round(p.y())) for p in b._tail] == [(0, 0), (-15, -15), (0, -15)],
      str([(p.x(), p.y()) for p in b._tail]))
_kinds = [b._tail_path.elementAt(i).type for i in range(b._tail_path.elementCount())]
check("尾巴是**圆角**路径：三段直线 + 三段三次贝塞尔（三个角都按 BUBBLE_RADIUS 倒角）",
      _kinds.count(QPainterPath.ElementType.CurveToElement) == 3, str(len(_kinds)))
_tbr = b._tail_path.boundingRect()
check("倒角只往里收：路径包围盒不超出那个 15×15 方框，尾巴尖 A 那个角被切掉了",
      _tbr.x() >= -15 - 1e-6 and _tbr.y() >= -15 - 1e-6
      and _tbr.right() <= 1e-6 and _tbr.bottom() > -6,
      f"{_tbr}")
check("尾巴也要有「底」：内部是淡蓝 #E6F1FB（二改是实心深蓝）", _bpx(-5, -13) == "#E6F1FB",
      _bpx(-5, -13))
check("尾巴的描边与**本体同色**：a 边正中（离下边框 4px 那条）是 #0C447C",
      _bpx(-5, -15) == "#0C447C", _bpx(-5, -15))
check("尾巴的圆角把 A 那个尖角切掉了：A 偏里 2px 处已经没有墨（实心三角时是深蓝）",
      _bimg.pixelColor(round(-1 + b.anchor_point.x()),
                       round(-2 + b.anchor_point.y())).alpha() == 0,
      str(_bimg.pixelColor(round(-1 + b.anchor_point.x()),
                           round(-2 + b.anchor_point.y())).alpha()))
check("本体圆角 = 3px：左上角那两格（往里 1 / 3 px）**就在深蓝边框上**"
      "（12px 圆角时这两个点整个是空的）",
      _bpx(b._body_rect.x() + 1, b._body_rect.y() + 3) == "#0C447C"
      and _bpx(b._body_rect.x() + 3, b._body_rect.y() + 1) == "#0C447C",
      f"{_bpx(b._body_rect.x() + 1, b._body_rect.y() + 3)}/"
      f"{_bpx(b._body_rect.x() + 3, b._body_rect.y() + 1)}")
check("锚点落在控件内（尾巴尖不会被自己的窗口裁掉）",
      0 <= b.anchor_point.x() < b.width() and 0 <= b.anchor_point.y() < b.height(),
      f"anchor={b.anchor_point} size={b.width()}x{b.height()}")
_bad = []
for _i in range(21):
    _ang, _sc, _ = petmod.bubble_pop_state(_i / 20)
    _tr2 = QTransform()
    _tr2.rotate(_ang)
    _tr2.scale(_sc, _sc)
    _x0, _y0, _x1, _y1 = petmod.bubble_content_box(b._body_w, b._body_h)
    for (_x, _y) in ((_x0, _y0), (_x1, _y0), (_x0, _y1), (_x1, _y1)):
        _q = _tr2.map(QPointF(_x, _y))
        _px, _py = b.anchor_point.x() + _q.x(), b.anchor_point.y() + _q.y()
        if not (-0.5 <= _px <= b.width() + 0.5 and -0.5 <= _py <= b.height() + 0.5):
            _bad.append((_i, round(_px, 1), round(_py, 1)))
check("动画全程的内容都在控件内（不会被自己的窗口裁掉）", not _bad, str(_bad[:3]))
check("气泡整体在贴图左侧、且几乎贴到贴图（尾巴尖距贴图 5px）",
      b.x() + b.width() <= r4.x() and 695 <= b.x() + b.width() <= 700,
      f"bubble 右边 {b.x() + b.width()} vs 贴图左边 {r4.x()}")
check("尾巴尖正好落在算出来的锚点上（贴图左边 −5、距贴图顶 71）",
      (b.x() + round(b.anchor_point.x()), b.y() + round(b.anchor_point.y())) == (695, 371),
      f"{b.x() + round(b.anchor_point.x())},{b.y() + round(b.anchor_point.y())}")
_bx, _by = b.x(), b.y()
pet4.move(560, 180)
qapp.processEvents()
check("桌宠移动 → 气泡同步跟着走（偏移量一致）",
      (b.x() - _bx, b.y() - _by) == (-140, -120), f"{b.x() - _bx},{b.y() - _by}")
check("挪完之后尾巴尖仍钉在贴图左边 −5 / 5-7 高处",
      (b.x() + round(b.anchor_point.x()), b.y() + round(b.anchor_point.y())) == (555, 251),
      f"{b.x() + round(b.anchor_point.x())},{b.y() + round(b.anchor_point.y())}")
pet4.set_power_save(True, animate=False)
qapp.processEvents()
_r5 = pet4._sprite_rect()
check("节能变形（贴图变矮）后锚点重算 —— 用的是 _label 当前 geometry，不是 _base_h",
      _r5.height() == 100
      and b.y() + round(b.anchor_point.y()) == _r5.y() + 100 - round(100 * 5 / 7),
      f"label={_r5} bubble_anchor_y={b.y() + round(b.anchor_point.y())}")
pet4.set_power_save(False, animate=False)
qapp.processEvents()

print("== 12. 弹出动画真能自己跑完（300ms，走真事件循环） ==")
pet5 = new_pet(ALICE, at=(200, 200))
check("叫出气泡", pet5.show_bubble("你好") is True)
b5 = pet5._bubble
check("弹出动画已启动、时长 = 300ms、缓动 = OutCubic",
      b5._pop_anim is not None and b5._pop_anim.duration() == petmod.BUBBLE_POP_MS
      and b5._pop_anim.easingCurve().type() == QEasingCurve.OutCubic,
      f"{b5._pop_anim.duration() if b5._pop_anim else None}")
_t0 = time.time()
while b5._pop_anim is not None and (time.time() - _t0) < 3.0:
    qapp.processEvents()
    time.sleep(0.01)
_dt = time.time() - _t0
check("动画自行结束（不是一直挂着）", b5._pop_anim is None, f"{_dt:.2f}s")
check("耗时落在合理区间（0.3s ± 余量）", 0.2 <= _dt <= 2.0, f"{_dt:.2f}s")
check("结束后落到 p=1 的姿态（0° / 1.00 / 不透明）",
      b5.pop_pose == (0.0, 1.0, 1.0), str(b5.pop_pose))

print("== 13. 淡出：只掉不透明度，归零后隐藏 ==")
pet5.hide_bubble()
_fade = b5._fade_anim
check("淡出动画已启动、时长 = 200ms、线性",
      _fade is not None and _fade.duration() == petmod.BUBBLE_FADE_MS
      and _fade.easingCurve().type() == QEasingCurve.Linear,
      f"{_fade.duration() if _fade else None}")
check("淡出只动不透明度（角度 0 / 缩放 1 全程不变）", b5.pop_pose[:2] == (0.0, 1.0), str(b5.pop_pose))
b5._set_frame(0.0, 1.0, 0.4)
check("淡到一半仍算「显示中」", b5.is_shown() and pet5.is_bubble_visible())
b5._on_fade_done()
check("归零 hide() 之后不再可见", not b5.is_shown() and not b5.isVisible())
check("没显示时再叫 hide_bubble 是空操作（不报错、姿态复位）",
      pet5.hide_bubble() is None and b5.pop_pose == (0.0, 1.0, 0.0), str(b5.pop_pose))
pet5.show_bubble("又说了一句")
check("重新叫出来：从 p=0 重放弹出动画（不叠两个气泡）",
      b5.pop_pose == petmod.bubble_pop_state(0.0) and b5._pop_anim is not None, str(b5.pop_pose))
b5._pop_anim.stop()
b5._pop_anim = None
pet5.close()
qapp.processEvents()
check("关桌宠会把气泡一起关掉（独立顶层窗不会自己跟着走）", not b5.isVisible())

print("== 14. 翻转：贴图贴边时气泡让位（纯算式：空间判定 + 20px 迟滞） ==")
AV = QRect(0, 0, 800, 800)     # 纯算式部分固定一块屏幕，断言才是确定的


class _Spr:
    """只给 bubble_side / bubble_face 用的贴图替身（它们只读 x/y/宽/高）。"""

    def __init__(self, x, y, w, h):
        self._r = QRect(x, y, w, h)

    def x(self):
        return self._r.x()

    def y(self):
        return self._r.y()

    def width(self):
        return self._r.width()

    def height(self):
        return self._r.height()


check("左侧放得下 120px → 待在左边",
      petmod.bubble_side(_Spr(700, 300, 150, 250), AV) == petmod.SIDE_LEFT)
check("左侧只剩 119px（< 气泡宽）→ 让到贴图右侧",
      petmod.bubble_side(_Spr(119, 300, 150, 250), AV) == petmod.SIDE_RIGHT)
check("迟滞：已经在右侧时，左侧要重新多出 20px（=140px）才让得回去",
      petmod.bubble_side(_Spr(139, 300, 150, 250), AV, petmod.SIDE_RIGHT) == petmod.SIDE_RIGHT
      and petmod.bubble_side(_Spr(140, 300, 150, 250), AV, petmod.SIDE_RIGHT) == petmod.SIDE_LEFT)
check("迟滞防抖：同一个位置（左侧剩 130px）来、回两个方向都不换边",
      petmod.bubble_side(_Spr(130, 300, 150, 250), AV, petmod.SIDE_LEFT) == petmod.SIDE_LEFT
      and petmod.bubble_side(_Spr(130, 300, 150, 250), AV, petmod.SIDE_RIGHT) == petmod.SIDE_RIGHT)
check("两边都放不下（屏幕比贴图还窄）→ 保持左侧，不把气泡推出屏幕",
      petmod.bubble_side(_Spr(0, 300, 150, 250), QRect(0, 0, 120, 800)) == petmod.SIDE_LEFT)
check("锚点上方放得下（19 + 文字块高）→ 尾朝下",
      petmod.bubble_face(_Spr(700, 300, 150, 250), AV, 35) == petmod.FACE_DOWN)
check("上方不够（锚点上方只剩 51px < 54）→ 尾朝上、气泡挂到 2/7 高度",
      petmod.bubble_face(_Spr(700, -20, 150, 250), AV, 35) == petmod.FACE_UP)
check("上下迟滞：已朝上时，上方要 74px（=54+20）才翻回朝下",
      petmod.bubble_face(_Spr(700, -17, 150, 250), AV, 35, petmod.FACE_UP) == petmod.FACE_UP
      and petmod.bubble_face(_Spr(700, 3, 150, 250), AV, 35, petmod.FACE_UP) == petmod.FACE_DOWN)

print("== 14b. 翻转是**平移**（500ms）：拖到左边缘让到右侧，拖回来再让回左侧 ==")
pet6 = new_pet(ALICE, at=(700, 300))
b6 = pet6._bubble
pet6.show_bubble("把桌宠拖到屏幕边上试试")
b6._stop_anims()
b6._set_frame(*petmod.bubble_pop_state(1.0))
qapp.processEvents()
av6 = pet6._avail_rect()
check("气泡的可用区 = 桌宠所在屏幕的可用区域（不是硬编码）",
      (av6.x(), av6.y(), av6.width(), av6.height())
      == (qapp.primaryScreen().availableGeometry().x(),
          qapp.primaryScreen().availableGeometry().y(),
          qapp.primaryScreen().availableGeometry().width(),
          qapp.primaryScreen().availableGeometry().height()), str(av6))
check("一开始：气泡在贴图左侧", b6.side == petmod.SIDE_LEFT, str(b6.side))
_pos0 = (b6.x(), b6.y())
pet6.move(av6.x() + 10, 300)                 # 左侧只剩 10px
qapp.processEvents()
check("贴图贴到屏幕左边缘 → 立刻改判到右侧", b6.side == petmod.SIDE_RIGHT, str(b6.side))
check("翻转是 500ms OutCubic 的平移动画",
      b6._flip_anim is not None and b6._flip_anim.duration() == petmod.BUBBLE_FLIP_MS
      and b6._flip_anim.easingCurve().type() == QEasingCurve.OutCubic,
      f"{b6._flip_anim.duration() if b6._flip_anim else None}")
check("翻转**不重放弹出动画、不变淡**（是平移，不是重建气泡）",
      b6._pop_anim is None and b6._fade_anim is None and b6.pop_pose == (0.0, 1.0, 1.0),
      str(b6.pop_pose))
b6._flip_anim.stop()
b6._on_flip_value(0.5)
_mid = (b6.x(), b6.y())
b6._on_flip_value(1.0)
_end = (b6.x(), b6.y())
b6._flip_anim = None
check("翻转途中确实在移动：中点与两端都不同（是平移，不是瞬移）",
      _mid != _pos0 and _mid != _end, f"{_pos0} -> {_mid} -> {_end}")
_s6 = pet6._sprite_rect()
_A6 = b6.x() + round(b6.anchor_point.x())
check("落位后气泡在贴图**右侧**（让位成功）",
      _A6 == _s6.x() + _s6.width() + petmod.BUBBLE_GAP_X,
      f"A={_A6} 贴图右边={_s6.x() + _s6.width()}")
check("落位后 b 与气泡**左边框**共线、a ∥ 下边框且 a 本身就在下边框下方 4px",
      abs(b6._body_rect.x()) < 1e-6
      and abs(b6._tail.at(0).x()) < 1e-6 and abs(b6._tail.at(2).x()) < 1e-6
      and abs(b6._body_rect.bottom() + petmod.BUBBLE_TAIL_GAP - b6._tail.at(1).y()) < 1e-6
      and abs(b6._body_rect.bottom() + petmod.BUBBLE_TAIL_GAP - b6._tail.at(2).y()) < 1e-6
      and abs(b6._tail.at(1).y() - b6._tail.at(2).y()) < 1e-6,
      f"body={b6._body_rect} tail={[(p.x(), p.y()) for p in b6._tail]}")
pet6.move(700, 300)
qapp.processEvents()
check("拖回原位 → 又让回左侧（同样是 500ms 平移）",
      b6.side == petmod.SIDE_LEFT and b6._flip_anim is not None, str(b6.side))
check("让位全程是纯平移：气泡不旋转、不缩放、不淡",
      b6.pop_pose == (0.0, 1.0, 1.0), str(b6.pop_pose))
b6._flip_anim.stop()
b6._on_flip_value(1.0)
b6._flip_anim = None
check("让回左侧后落回**原来的位置**（来回拖不会越走越偏）",
      (b6.x(), b6.y()) == _pos0, f"{(b6.x(), b6.y())} vs {_pos0}")
check("让回左侧后 b 又与气泡**右边框**共线、尾巴尖仍在贴图左边 −5px",
      abs(b6._body_rect.x() + b6._body_rect.width()) < 1e-6
      and abs(b6._tail.at(0).x() - b6._tail.at(2).x()) < 1e-6
      and abs(b6._tail.at(0).x() - (b6._body_rect.x() + b6._body_rect.width())) < 1e-6
      and b6.x() + round(b6.anchor_point.x()) == pet6._sprite_rect().x() - petmod.BUBBLE_GAP_X,
      f"A={b6.x() + round(b6.anchor_point.x())}")

print("== 14c. 上下翻转：贴图顶上去了 → 气泡挂到 2/7 高度（尾朝上） ==")
pet6.move(700, -20)
qapp.processEvents()
check("贴图顶出屏幕上沿 → 尾朝上", b6.face == petmod.FACE_UP, str(b6.face))
check("上下翻转也是 500ms 平移动画",
      b6._flip_anim is not None and b6._flip_anim.duration() == petmod.BUBBLE_FLIP_MS)
b6._flip_anim.stop()
b6._on_flip_value(1.0)
b6._flip_anim = None
_s7 = pet6._sprite_rect()
check("落位后锚点高度 = 贴图底边往上 2/7（150×250 贴图 → 距贴图顶 179px）",
      b6.y() + round(b6.anchor_point.y()) == _s7.y() + _s7.height() - round(_s7.height() * 2 / 7)
      and b6.y() + round(b6.anchor_point.y()) == _s7.y() + 179,
      f"A.y={b6.y() + round(b6.anchor_point.y())} 贴图={_s7}")
check("尾朝上时 a 就在上边框**上方** 5px；b 仍与气泡右边框共线",
      abs(b6._body_rect.top() - petmod.BUBBLE_TAIL_GAP_UP - b6._tail.at(0).y()) < 1e-6
      and abs(b6._body_rect.top() - petmod.BUBBLE_TAIL_GAP_UP - b6._tail.at(1).y()) < 1e-6
      and abs(b6._tail.at(0).y() - b6._tail.at(1).y()) < 1e-6
      and abs(b6._tail.at(0).x() - b6._tail.at(2).x()) < 1e-6
      and abs(b6._body_rect.x() + b6._body_rect.width()) < 1e-6,
      f"body={b6._body_rect} tail={[(p.x(), p.y()) for p in b6._tail]}")
check("尾朝上时气泡挂在锚点**下方**（不再顶到屏幕上方）",
      b6._body_rect.top() > 0, str(b6._body_rect))
pet6.move(700, 300)
qapp.processEvents()
check("贴图降回来 → 尾朝下（让回 5/7 高度）", b6.face == petmod.FACE_DOWN, str(b6.face))
if b6._flip_anim is not None:
    b6._flip_anim.stop()
    b6._on_flip_value(1.0)
    b6._flip_anim = None
check("回到 5/7 后位置与最初完全一致", (b6.x(), b6.y()) == _pos0, f"{(b6.x(), b6.y())} vs {_pos0}")
pet6.close()
qapp.processEvents()

print("== 15. 「显示聊天气泡」检验开关：把气泡钉住，方便核对样式"
      "（★2026-09-28 菜单项已下架，只剩 API / 回调）==")
pet7 = new_pet(ALICE, at=(700, 300))
_b7 = pet7._bubble


def _settle(w):
    """跳过弹出 / 翻转动画，把姿态与位置按到终态 —— 断言才确定。

    ⚠️ 顺序有讲究：`_stop_anims()` 只停「还挂在属性上」的动画。必须**先停**（此时 `_pop_anim`
    还在），再按终态 —— 反过来先调 `_on_pop_done()` 的话，那个 300ms 的动画对象**还活着**，
    下一帧 `processEvents()` 会把姿态又拖回中途（单跑不复现、并到 `run_all` 里才炸的那种）。
    """
    b = w._bubble
    b._stop_anims()
    b._on_flip_value(1.0)      # 翻转按到终态（delta 已被 _stop_anims 清零 → 直接落位）
    b._on_pop_done()


def _menu_acts(w):
    """构造右键弹窗取回逐行状态（`_build_menu` 只构造不弹 → 测试不会被模态卡住）。

    2026-09-19 八改：容器从 `QMenu` 换成自绘的 `_MenuPopup` —— 逐行取回改成走 `rows()` /
    `row_text()`；四元组的形状（文字 / 可勾选 / 已勾选 / 是否分隔线）保持不变，下面的断言不用动。
    音量条那一行的 `row_text()` 是空串（与原 `QWidgetAction.text()` 的表现一致）。
    """
    m = w._build_menu()
    acts = [(m.row_text(i), bool(r.get("checkable")), bool(r.get("checked")),
             r["kind"] == "sep")
            for i, r in enumerate(m.rows())]
    m.deleteLater()
    return acts


def _menu_row(w, text):
    """按文字取回弹窗里那一行（浅拷贝；调用方拿 `row["trigger"]()` 点它）。"""
    m = w._build_menu()
    row = None
    for i, r in enumerate(m.rows()):
        if m.row_text(i) == text:
            row = dict(r)
            break
    m.deleteLater()
    assert row is not None, text
    return row


check("_build_menu() 返回自绘弹窗 `_MenuPopup`（只构造、不 exec，弹窗可被测试逐行检查）",
      isinstance(pet7._build_menu(), petmod._MenuPopup))

_acts = _menu_acts(pet7)
check("菜单项顺序：**音量条** / 切换 / 节能模式 / patpat模式 / 桌宠固定 / 主界面 / 设置 / 退出"
      "（2026-09-19 音量条置顶；它是自绘弹窗里的 volume 行，row_text() 为空串；"
      "2026-09-20 十七改在「节能模式」下面插了同样属于「模式」的「patpat模式」；"
      "2026-09-22 又在它下面插了「桌宠固定」—— 同属「模式 / 行为」类开关）",
      [t for (t, _c, _k, sep) in _acts if not sep]
      == ["", "切换", "节能模式", "patpat模式", "桌宠固定", "主界面", "设置", "退出"],
      str([t for (t, _c, _k, sep) in _acts if not sep]))
check("两条分隔线：音量条之后一条、切换子菜单之后一条",
      [i for i, a in enumerate(_acts) if a[3]] == [1, 3], str(_acts))
# ★2026-09-28：菜单项**下架**（用户口径：软件实际使用不需要它，仅用来核对气泡显示 / 样式）——
#   所以这里反过来锁「菜单里没有这一行」，而开关本身（API / 回调）照旧可用，见下面的用例。
check("★菜单里**没有**「显示聊天气泡」（下架；关掉的是入口，不是功能）",
      "显示聊天气泡" not in [t for (t, _c, _k, sep) in _acts]
      and pet7.is_bubble_preview() is False,
      str([t for (t, _c, _k, sep) in _acts if not sep]))

# ---- 桌宠固定（2026-09-22）：右键菜单那一项**回调**必须接在 `toggle_locked` 上 ----
# ★上面那条只核了「行序 / 文字」，**接错回调照样绿**（反向验证 F4 就是把 `on_trigger` 换成
#   `toggle_patpat`，811 项断言**一项不红** ⇒ 差点漏过去）。这里补上「回调身份」这一层。
# ★用 `__func__` 比**函数对象**，不比字符串：本文件注释里也有 `toggle_locked` 这个词。
_lk_row = _menu_row(pet7, "桌宠固定")
check("★右键菜单「桌宠固定」是勾选项、勾选态跟 `is_locked()` 一致、**回调接在 `toggle_locked` 上**",
      _lk_row["checkable"] is True
      and _lk_row["checked"] == pet7.is_locked()
      and getattr(_lk_row["trigger"], "__func__", None) is petmod.PetWindow.toggle_locked,
      str((_lk_row["checkable"], _lk_row["checked"], _lk_row["trigger"])))
_lk_before = pet7.is_locked()
_lk_row["trigger"]()                       # 真的点一下那一行
check("★点右键菜单「桌宠固定」→ 锁定状态真的翻转（不是接了个空回调）",
      pet7.is_locked() is (not _lk_before), f"{_lk_before} -> {pet7.is_locked()}")
pet7.set_locked(_lk_before)                # 还原，别影响下面 pet7 的用例

_src_main = (BASE / "app" / "main.py").read_text(encoding="utf-8")
check("main.py 里备好了预览文本（故意写长，折行才看得出高度变化）",
      "BUBBLE_PREVIEW_TEXT" in _src_main and "气泡预览" in _src_main)
check("main.py 两个分支都接上了：开 → 预览气泡；关 → 照旧收起",
      "def on_bubble_preview" in _src_main
      and "pet.show_bubble(BUBBLE_PREVIEW_TEXT)" in _src_main
      and "pet.set_on_bubble_preview(on_bubble_preview)" in _src_main
      and _src_main.index("def on_bubble_preview") < _src_main.index("pet.set_on_bubble_preview"),
      "回调先定义、后注册")


# ---- 桌宠固定（2026-09-22）在 main.py 的三处接线（★**AST 查**，不查字符串）----
# ★要核的不是「出现过 `.get("lock_pet", ...)` 这个写法」，而是**默认值到底是不是 True**
#   （用户口径「默认打开固定，使桌宠不会被拖动」）—— 字符串版只能证明写法在，把 `True` 改成
#   `False` **纹丝不动**（反向验证 F6 就是这么绕过去的，811 项一项不红）。AST 才会红。
def _main_lock_wiring():
    """返回 (『lock_pet』默认取 True?, 调了 set_locked?, 注册了 set_on_lock?, 注册了 set_pet_lock_cb?)。

    ⚠️**别**从 `set_locked()` 的实参往下钻：真实写法是
    `pet.set_locked(bool(cfg.get("general", {}).get("lock_pet", True)))` —— 实参被 `bool(...)`
    **包了一层**，`node.args[0].func.attr` 拿到的是 `bool` 而不是 `get` ⇒ 断言会**在好代码上红**
    （实测踩过：基线 815 项 / 1 失败）。直接找**那次 `.get("lock_pet", <常量>)` 调用**本身，
    与有没有 `bool()` 包裹、与注册顺序都无关。
    """
    default_true = has_call = has_on_lock = has_cb = False
    for node in ast.walk(ast.parse(_src_main)):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        attr = node.func.attr
        if attr == "get" and len(node.args) >= 2:
            if (isinstance(node.args[0], ast.Constant) and node.args[0].value == "lock_pet"
                    and isinstance(node.args[1], ast.Constant) and node.args[1].value is True):
                default_true = True
        elif attr == "set_locked" and node.args:
            has_call = True
        elif attr == "set_on_lock":
            has_on_lock = True
        elif attr == "set_pet_lock_cb":
            has_cb = True
    return default_true, has_call, has_on_lock, has_cb


_mw = _main_lock_wiring()
check("★main.py 把「桌宠固定」接上了：初始值 `lock_pet` 默认 **True**（真机启动就固定）"
      "+ `set_locked` / `set_on_lock` / `set_pet_lock_cb` 三处接线齐全（AST 查默认值，注释骗不了它）",
      _mw == (True, True, True, True), str(_mw))

_calls = []


def _preview_cb(on):
    _calls.append(on)
    if on:
        pet7.show_bubble("预览文字：这是一句故意写长一点的预览，用来核对圆角、边框粗细和高度变化。")
    else:
        pet7.hide_bubble()


pet7.set_on_bubble_preview(_preview_cb)
pet7.set_bubble_preview(True)
_settle(pet7)
qapp.processEvents()
check("开：旗标置位 + 回调恰好收到一次 True（main.py 就是靠它把气泡叫出来的）",
      pet7.is_bubble_preview() and _calls == [True], str(_calls))
check("气泡真的出来了，文字就是那句预览",
      _b7.is_shown() and "预览文字" in _b7.text, _b7.text)
_h_on = _b7.body_height
check("预览长句会折行 → 本体比单行（35）高（高度仍随文字量变化）", _h_on > 35, str(_h_on))
check("★重新构造的菜单里**没有**这一行（下架），但旗标确实是开着",
      pet7.is_bubble_preview()
      and "显示聊天气泡" not in [a[0] for a in _menu_acts(pet7)])

for _ in range(3):
    pet7.hide_bubble()
qapp.processEvents()
check("main.py 的 6 个自动收起点全调 hide_bubble：开着时一律空操作（不动、也不淡出）",
      _b7.is_shown() and _b7._fade_anim is None, str(_b7._fade_anim))
check("空操作之后形态没被打扰（仍是到位姿态）",
      _b7.pop_pose == (0.0, 1.0, 1.0), str(_b7.pop_pose))

pet7.show_bubble("真正的回复来了：气泡应该换成它，并且继续挂着不消失。")
_settle(pet7)
check("检验期间来真回复：文字换成新的、气泡不消失",
      "真正的回复" in _b7.text and _b7.is_shown(), _b7.text)
pet7.hide_bubble()
qapp.processEvents()
check("对话结束（hide_bubble）也被拦住 —— 这正是「方便检验」的关键",
      _b7.is_shown(), str(_b7.is_shown()))

pet7.set_bubble_preview(False)
check("关：旗标清零 + 回调收到 False（先置位、后回调，这一下必须能真收起来）",
      not pet7.is_bubble_preview() and _calls == [True, False], str(_calls))
check("关掉的这一刻立刻开始淡出", _b7._fade_anim is not None)
_b7._on_fade_done()
qapp.processEvents()
check("淡完就真的不显示了", not _b7.is_shown())
pet7.show_bubble("x")
_settle(pet7)
pet7.hide_bubble()
check("关掉之后自动收起恢复生效（不再被拦住）", _b7._fade_anim is not None)
_b7._on_fade_done()
qapp.processEvents()

pet7.toggle_bubble_preview()      # 原来挂在菜单那一行上的就是这个 toggle（下架后直接调）
_settle(pet7)
check("调 `toggle_bubble_preview()` = 开（菜单项当初接的就是这个函数）",
      pet7.is_bubble_preview() and _b7.is_shown(), str(pet7.is_bubble_preview()))
check("开关是运行期状态：没被写进 config.json（重启即关，不落盘）",
      "bubble_preview" not in (BASE / "config.json").read_text(encoding="utf-8"))
pet7.set_bubble_preview(False)
_b7._on_fade_done()
qapp.processEvents()
check("关掉后旗标干净（收尾）", not pet7.is_bubble_preview())
pet7.close()
qapp.processEvents()

print("== 16. 长回复分段显示（四改：段间只淡文字，淡出 / 淡入各 200ms）==")

# 一段真·长回复：够切好几段，而且有句读（能验「不让下一段以标点开头」）
CN_LONG = ("今天天气不错，很适合出门走走。不过午后可能有阵雨，记得带把伞。"
           "你昨天说的那本书我看完了，第三章节写得特别好，尤其是那段关于旅行的描写，"
           "让我想起我们去年夏天在海边待的那几天。要不要这周末一起去图书馆？"
           "顺便把那件外套还给你，它一直挂在我衣柜里占地方。")


def _page_h(txt):
    """用气泡**同一套** doc 量一段的高（口径与 app/pet.py 一致：同字号、同宽度、margin 0）。"""
    doc = QTextDocument()
    doc.setDocumentMargin(0)
    font = QFont("Microsoft YaHei UI")
    font.setPixelSize(petmod.BUBBLE_FONT_PX)
    doc.setDefaultFont(font)
    doc.setTextWidth(petmod.bubble_text_width())
    doc.setPlainText(txt)
    return int(math.ceil(doc.documentLayout().documentSize().height()))


check("上限常量 = 96px（≈5~6 行；行高按字体实测，所以口径写 px）",
      petmod.BUBBLE_MAX_TEXT_H == 96, str(petmod.BUBBLE_MAX_TEXT_H))
check("段间淡字 = 各 200ms（用户口径 0.2s）", petmod.BUBBLE_TEXT_FADE_MS == 200,
      str(petmod.BUBBLE_TEXT_FADE_MS))
check("短回复不切段（1 段，整句原样）", petmod.bubble_pages("你好呀") == ["你好呀"])
check("空 / 全空白文本 → 空列表（PetWindow.show_bubble 本来就挡掉了）",
      petmod.bubble_pages("") == [] and petmod.bubble_pages("  \n ") == [])
_pages = petmod.bubble_pages(CN_LONG)
check(f"长回复切成多段（{len(CN_LONG)} 字 → {len(_pages)} 段）", len(_pages) >= 3, str(len(_pages)))
check("每段都量得下（正文块高 ≤ BUBBLE_MAX_TEXT_H）",
      all(_page_h(p) <= petmod.BUBBLE_MAX_TEXT_H for p in _pages),
      str([_page_h(p) for p in _pages]))
check("「要不要切」看量出来的高，不看字数（全文量得下 ⇔ 只有一段）",
      (len(_pages) == 1) == (_page_h(CN_LONG) <= petmod.BUBBLE_MAX_TEXT_H)
      and _page_h(CN_LONG) > petmod.BUBBLE_MAX_TEXT_H, str(_page_h(CN_LONG)))
check("切完拼起来 = 原文，一个字都不丢", "".join(_pages) == CN_LONG,
      f"{len(''.join(_pages))} vs {len(CN_LONG)}")
check("没有一段以标点开头（不会出现「，让我想起…」这种段首）",
      not [p for p in _pages[1:] if p[0] in petmod._PAGE_BREAK_CHARS],
      str([p[:6] for p in _pages[1:]]))
check("尾段不碎（不足 12 字就把最后两段对半分）", len(_pages[-1]) >= 12, str(len(_pages[-1])))
check("切分不会死循环 / 不会切出空段（每段 ≥ 1 字、段数 ≤ 字数）",
      all(len(p) >= 1 for p in _pages) and len(_pages) <= len(CN_LONG))
check("带空格 / 换行的文本也不丢东西（各段是原文的切片，连空格都在原地）",
      "".join(petmod.bubble_pages("hello world 一起 走 test\n第二行")) == "hello world 一起 走 test\n第二行")
check("单段停留 = max(1.2s, 220ms × 字数)，与说话态同一条标定",
      petmod.bubble_page_dwell_ms("你好呀") == 1200
      and petmod.bubble_page_dwell_ms("字" * 40) == 8800,
      f"{petmod.bubble_page_dwell_ms('你好呀')} / {petmod.bubble_page_dwell_ms('字' * 40)}")
_src_pipeline = (BASE / "app" / "pipeline.py").read_text(encoding="utf-8")
check("停留时长与 pipeline.silent_hold_seconds 同源（0.22 s/字、下限 1.2s）",
      "_SILENT_PER_CHAR = 0.22" in _src_pipeline and "_SILENT_MIN = 1.2" in _src_pipeline
      and petmod.BUBBLE_PAGE_PER_CHAR_MS == 220 and petmod.BUBBLE_PAGE_MIN_MS == 1200)

_src_main8 = (BASE / "app" / "main.py").read_text(encoding="utf-8")
_ast_main = ast.parse(_src_main8)
_prev = [n for n in _ast_main.body if isinstance(n, ast.Assign)
         and getattr(n.targets[0], "id", "") == "BUBBLE_PREVIEW_TEXT"]
_prev_txt = _prev[0].value.value if _prev and isinstance(_prev[0].value, ast.Constant) else ""
check("main.py 的预览文本够切两段以上（开一下就能看全套分段过渡）",
      len(petmod.bubble_pages(_prev_txt)) >= 2, f"{len(_prev_txt)} 字 → {len(petmod.bubble_pages(_prev_txt))} 段")

pet8 = new_pet(ALICE, at=(600, 300))
b8 = pet8._bubble
check("长回复：气泡只摆出第一段", pet8.show_bubble(CN_LONG) is True
      and b8.page_count == len(_pages) and b8.page_index == 0 and b8.page_text == _pages[0],
      f"{b8.page_count} 段 / 第 {b8.page_index} 段")
check("整轮全文仍挂在气泡上（text 给全文，page_text 给当前段）", b8.text == CN_LONG)
check("本体高 = 第一段量出来的高 + 20（高度仍随文字量变化，只是有了上限）",
      b8.body_height == _page_h(_pages[0]) + 20, f"{b8.body_height} vs {_page_h(_pages[0]) + 20}")
check("多段回复排了段定时器，间隔 = 本段的停留时长", b8._page_timer is not None
      and b8._page_timer.interval() == petmod.bubble_page_dwell_ms(_pages[0]),
      str(b8._page_timer.interval() if b8._page_timer else None))
check("段定时器是**单次**触发（到点只换一次段，不是周期心跳）",
      b8._page_timer.isSingleShot() if b8._page_timer else False)
check("起始文字全不透明", b8.text_opacity == 1.0, str(b8.text_opacity))

b8._stop_anims()          # 弹出动画按到终态（顺带把段定时器停掉，下面手动驱动才确定）
b8._on_pop_done()
check("_stop_anims 把段定时器也停了（收气泡 / 换新回复要能立刻掐掉它）", b8._page_timer is None)


def _ink_stats(widget, anchor, rect):
    """文字区的墨：最深的一个像素 + 出现过的纯色集合（按锚点坐标取，真机 / 离屏都适用）。"""
    img = widget.grab().toImage().convertToFormat(QImage.Format_RGBA8888)
    dpr = img.devicePixelRatio() or 1.0
    best, seen = None, set()
    for yy in range(round(rect.top()), round(rect.bottom())):
        for xx in range(round(rect.left()), round(rect.right())):
            c = img.pixelColor(round((anchor.x() + xx) * dpr), round((anchor.y() + yy) * dpr))
            if c.alpha() > 0:
                seen.add((c.red(), c.green(), c.blue()))
                if best is None or (c.red() + c.green() + c.blue()) < sum(best[:3]):
                    best = (c.red(), c.green(), c.blue(), c.alpha())
    return best, seen, img, dpr


def _px_at(img, dpr, anchor, xa, ya):
    c = img.pixelColor(round((anchor.x() + xa) * dpr), round((anchor.y() + ya) * dpr))
    return (c.red(), c.green(), c.blue(), c.alpha())


_ink0, _seen0, _img0, _dpr0 = _ink_stats(b8, b8.anchor_point, b8._text_rect)
_edge0 = _px_at(_img0, _dpr0, b8.anchor_point, b8._body_rect.x() + 1, b8._body_rect.y() + 3)
check("全不透明时文字区里存在纯色 #334155", (51, 65, 85) in _seen0, str(sorted(_seen0)[:3]))

b8._next_page()
check("到点先起「把这段文字淡掉」：200ms 线性",
      b8._page_anim is not None and b8._page_anim.duration() == petmod.BUBBLE_TEXT_FADE_MS
      and b8._page_anim.easingCurve().type() == QEasingCurve.Linear,
      str(b8._page_anim.duration() if b8._page_anim else None))
b8._page_anim.setCurrentTime(100)          # 手动推到一半（真动画另有一段端到端）
_ink1, _seen1, _img1, _dpr1 = _ink_stats(b8, b8.anchor_point, b8._text_rect)
check("文字淡到一半：最深的墨也变浅了（整段一起淡，不是只淡掉一半的字）",
      sum(_ink1[:3]) > sum(_ink0[:3]), f"{_ink0} → {_ink1}")
check("淡到一半时纯色 #334155 已经不存在", (51, 65, 85) not in _seen1, str(sorted(_seen1)[:3]))
check("**边框一点没淡**：分段换字只动文字，本体与尾巴不动",
      _px_at(_img1, _dpr1, b8.anchor_point, b8._body_rect.x() + 1, b8._body_rect.y() + 3) == _edge0,
      f"{_edge0}")
check("整条气泡的不透明度也没动（那个是「这一轮结束」才用的）", b8.pop_pose[2] == 1.0,
      str(b8.pop_pose))

_h8_before = b8.body_height
b8._page_anim.stop()
b8._page_anim = None
b8._on_text_out_done()
check("文字淡没了的这一刻换段：段号 +1、doc 里换成下一段",
      b8.page_index == 1 and b8.page_text == _pages[1], f"{b8.page_index}: {b8.page_text[:8]}")
check("换段时本体高按新段重算（= 新段量出来的高 + 20）",
      b8.body_height == _page_h(_pages[1]) + 20, f"{_h8_before} → {b8.body_height}")
_r8 = pet8._sprite_rect()
check("换段后尾巴尖仍钉在算出来的锚点上（改高度不改锚点）",
      (b8.x() + round(b8.anchor_point.x()), b8.y() + round(b8.anchor_point.y()))
      == petmod.bubble_anchor(_r8.x(), _r8.y(), _r8.width(), _r8.height()),
      f"{(b8.x() + round(b8.anchor_point.x()), b8.y() + round(b8.anchor_point.y()))}")
check("换完接着「把新段淡进来」：同样 200ms 线性",
      b8._page_anim is not None and b8._page_anim.duration() == petmod.BUBBLE_TEXT_FADE_MS
      and b8._page_anim is not None)
b8._page_anim.stop()
b8._page_anim = None
b8._on_text_in_done()
check("淡入完：文字回到全不透明", b8.text_opacity == 1.0, str(b8.text_opacity))
check("还有下一段 → 又排上定时器（间隔 = 新段的停留）", b8._page_timer is not None
      and b8._page_timer.interval() == petmod.bubble_page_dwell_ms(_pages[1]))

# 端到端：把停留压到 30ms，让真事件循环把「定时器 → 淡出 → 换字 → 淡入」整条链跑一遍
b8._page_timer.stop()
b8._page_timer.setInterval(30)
b8._page_timer.start()
_t8 = time.time()
while b8.page_index < 2 and (time.time() - _t8) < 5.0:
    qapp.processEvents()
    time.sleep(0.005)
check("真事件循环里会自己一段段往下翻（到点 → 淡出 → 换字 → 淡入 → 再排定时器）",
      b8.page_index >= 2, f"{b8.page_index} 段 / {time.time() - _t8:.2f}s")
if b8._page_timer is not None:          # 等淡入之前先掐掉下一段定时器：等待期间不许它再开一次淡出
    b8._page_timer.stop()
_t8b = time.time()
while b8.text_opacity < 1.0 and b8._page_anim is not None and (time.time() - _t8b) < 3.0:
    qapp.processEvents()
    time.sleep(0.005)
check("换段那一刻文字是全透明的，随后自己淡回来（不是一直停在全透明）",
      b8.text_opacity == 1.0, str(b8.text_opacity))

b8._stop_anims()
check("stop 之后回到静止态：文字全不透明（新一轮从干净状态开始）",
      b8.text_opacity == 1.0 and b8._page_timer is None)
while b8.page_index < b8.page_count - 1:
    b8._on_text_out_done()
    if b8._page_anim is not None:
        b8._page_anim.stop()
        b8._page_anim = None
b8._on_text_in_done()
check("最后一段：不排下一段的定时器（留在桌上等这一轮结束）", b8._page_timer is None,
      str(b8.page_index))
check("本体高恒 = 当前那段量出来的高 + 20（换到哪一段就跟到哪一段）",
      b8.body_height == _page_h(b8.page_text) + 20,
      f"{b8.body_height} vs {_page_h(b8.page_text) + 20}")

pet8.show_bubble("你好呀")
check("短回复（1 段）：不排定时器、不淡字 —— 与四改前逐位一致",
      b8.page_count == 1 and b8._page_timer is None and b8.text_opacity == 1.0)
check("换成矮段：本体高跟着收（长 110 → 短 35，不是一直按最高那档撑着）",
      b8.body_height == _page_h("你好呀") + 20
      and b8.body_height < _page_h(_pages[0]) + 20, str(b8.body_height))
b8._text_op = 0.35                       # 假装上一轮停在半途
pet8.show_bubble(CN_LONG)
check("新一轮：从第一段、全不透明开始（不继承上一轮停在半途的淡字）",
      b8.page_index == 0 and b8.text_opacity == 1.0 and b8.page_count == len(_pages))
pet8.hide_bubble()
check("整条淡出照样工作（那是「这一轮结束」，与分段淡字互不干扰）", b8._fade_anim is not None)
b8._on_fade_done()
qapp.processEvents()
check("整条淡出归零后不再显示", not b8.is_shown())
pet8.close()
qapp.processEvents()

print("== 17. 状态提示气泡：贴图正上方（高钉死 30 / 宽随文字 / 深蓝边 + 淡蓝底）==")
pet9 = new_pet(ALICE, at=(600, 300))
_t9 = pet9._toast

# ---- 17a. 几何（纯算式）----
check("本体宽 = 文字自然宽 + 2×(边框 + 内边距) —— 「略宽于文本」就是这么来的",
      petmod.toast_body_w("待机中") == petmod.toast_text_w("待机中")
      + 2 * (petmod.TOAST_BORDER + petmod.TOAST_PAD_X), str(petmod.toast_body_w("待机中")))
check("边框 / 圆角复用聊天气泡那一套：深蓝 2px + 3px 圆角",
      (petmod.TOAST_BORDER, petmod.TOAST_RADIUS) == (petmod.BUBBLE_BORDER, petmod.BUBBLE_RADIUS) == (2, 3))
check("弹出 / 收起都是 500ms；自下而上 5px、缩放 50%~100%（三件套的档位）",
      (petmod.TOAST_POP_MS, petmod.TOAST_POP_DY, petmod.TOAST_MIN_SCALE) == (500, 5, 0.5))
check("提示窗比本体**上下各高 5px**（弹出先落在下方 5px、收起再往上走 5px，两边都得留白）",
      _t9._win_h == petmod.TOAST_H + 2 * petmod.TOAST_POP_DY == 40, str(_t9._win_h))
check("本体高恒定 30（略高于一行文字）、距贴图 5px",
      (petmod.TOAST_H, petmod.TOAST_GAP) == (30, 5))
_r9 = pet9._sprite_rect()
_x9, _y9, _w9g, _h9g = petmod.toast_rect(_r9, 100)
check("横向**以贴图中心线居中**", _x9 == _r9.x() + (_r9.width() - 100) // 2, str(_x9))
check("纵向贴在贴图**正上方**：本体下沿 = 贴图顶边 − 5px",
      _y9 + petmod.TOAST_H == _r9.y() - petmod.TOAST_GAP,
      f"{_y9 + petmod.TOAST_H} vs {_r9.y() - petmod.TOAST_GAP}")
check("高不随文字量变：拿超长文本去量也还是 30",
      petmod.toast_rect(_r9, petmod.toast_body_w("已进入静音模式" * 3))[3] == 30)
check("宽随文字量变（休眠中 < 已进入静音模式）",
      petmod.toast_body_w("休眠中") < petmod.toast_body_w("已进入静音模式"))
check("**与聊天气泡恰好相反**：这个不是钉死 120（宽是量出来再算的）",
      petmod.toast_body_w("休眠中") != petmod.BUBBLE_W)

# ---- 17b. 「待机中」常驻 + 点动画（1s 一个点，加到 3 个清空重来）----
pet9.set_state_toast("待机中", dots=True)
_t9._on_show_done()
qapp.processEvents()
check("常驻状态挂上：「待机中」+ 0 个点", _t9.shown_text == "待机中" and _t9.dots_n == 0)
check("弹出动画跑完 = 全不透明且在显示", pet9.is_toast_visible() and _t9.opacity == 1.0)
check("宽度按**最长那条**算（含 3 个点）：点动画期间宽度不抖",
      _t9.body_w == petmod.toast_body_w("待机中" + "." * petmod.TOAST_DOT_MAX), str(_t9.body_w))
check("点定时器每 1s 一步",
      _t9._dots_timer.isActive() and _t9._dots_timer.interval() == petmod.TOAST_DOT_MS == 1000)
check("「待机中」是**常驻**：它不排停留计时（状态不变就一直挂着，这是唯一走常驻的一条）",
      _t9._hold_timer is None and _t9._hold_pending is False and _t9._hold_text == "")
_bw9 = _t9.body_w
_t9._on_dot()
check("第 1 步：待机中.", _t9.shown_text == "待机中." and _t9.dots_n == 1)
_t9._on_dot()
_t9._on_dot()
check("加到 3 个：待机中...", _t9.shown_text == "待机中..." and _t9.dots_n == 3)
check("这 3 步里宽度一次都没变（只重画、不重排）", _t9.body_w == _bw9)
_t9._on_dot()
check("第 4 步清空重来（不是停在「...」）", _t9.shown_text == "待机中" and _t9.dots_n == 0)
check("清空那一步也占满 1 秒（一轮 4 步 = 4s）",
      petmod.TOAST_DOT_MS * (petmod.TOAST_DOT_MAX + 1) == 4000)

# ---- 17c. 事件型提示：盖在状态上，到点淡出后**自动露出**底下的状态 ----
pet9.flash_toast("已唤醒")
qapp.processEvents()
check("事件提示**盖住**常驻状态（这一帧画出来的是「已唤醒」）",
      _t9.shown_text == "已唤醒" and pet9.toast_flash_text == "已唤醒")
check("宽度按事件那条算", _t9.body_w == petmod.toast_body_w("已唤醒"))
check("已经在显示时改文本 **不重放弹出**（点动画每秒都会走到这里，重放会抽搐）",
      _t9._anim is None and _t9.opacity == 1.0)
check("事件是**瞬态**：停留计时已起表，间隔 = TOAST_HOLD_MS（2000ms）",
      _t9._hold_timer is not None and _t9._hold_timer.interval() == petmod.TOAST_HOLD_MS == 2000
      and _t9._hold_text == "已唤醒")
_t9._on_hold_done()
qapp.processEvents()
check("到点：flash 清掉、**自动露出**底下的「待机中」（不需要排队、也不需要第二个定时器）",
      _t9.flash_text == "" and _t9.shown_text.startswith("待机中"), str(_t9.shown_text))
check("露出后宽度回到状态那条（仍按含 3 个点算）", _t9.body_w == _bw9)
check("露出的是常驻状态 -> 停留计时**没有再排**（它要一直挂着）",
      _t9._hold_timer is None and _t9._hold_pending is False and _t9._hold_text == "")

# ---- 17c2. 「停留 2s」从**淡入结束那一刻**起算（不是 flash() 发起那一刻）----
pet9.clear_state_toast()
_t9._on_hide_done()
qapp.processEvents()
check("先清干净：底下没有状态了、整条收起", not pet9.is_toast_visible() and _t9.shown_text == "")
pet9.flash_toast("已进入静音模式")
qapp.processEvents()
check("闪一下：淡入动画还在跑，**停留计时挂着没起表**（不能从发起那一刻就算）",
      _t9._anim is not None and _t9._hold_timer is None and _t9._hold_pending is True)
_t9._on_show_done()
check("淡入结束 -> **此刻**才起表，间隔 = 2000ms",
      _t9._hold_timer is not None and _t9._hold_timer.interval() == petmod.TOAST_HOLD_MS == 2000
      and _t9._hold_pending is False)
_bw_fade = _t9.body_w
_t9._on_hold_done()
check("到点：事件清掉、底下没状态 -> 整条淡出（反向三件套，0.5s）",
      _t9.flash_text == "" and _t9.shown_text == "" and _t9._anim is not None)
check("淡出期间**继续画原来那条** —— 正文清空后 `paintEvent` 若直接 return，画面上就是「啪」地消失、根本没淡出（真机报过）",
      _t9._paint_text() == "已进入静音模式")
check("淡出期间**几何冻结**：宽仍是原来那条的宽（按空文本重算会掉到二十几像素，再缩 50% 就什么也看不见）",
      _t9.body_w == _bw_fade, f"{_t9.body_w} vs {_bw_fade}")


def _fade_span(op, dy, sc):
    """按淡出某一档摆好，数一下**画出来的**宽度（真像素）。

    先 `_stop_anim()`：淡出动画还在自己跑，手工摆的那一帧会被它下一步覆盖掉（量出来就是乱七八糟的中间值）。
    """
    _t9._stop_anim()
    _t9._set_frame(op, dy, sc)
    qapp.processEvents()
    _im = _t9.grab().toImage().convertToFormat(QImage.Format_RGBA8888)
    _xs = [x for y in range(_im.height()) for x in range(_im.width())
           if _im.pixelColor(x, y).alpha() > 0]
    return (max(_xs) - min(_xs) + 1) if _xs else 0


_span_full = _fade_span(1.0, 0.0, 1.0)
_span_mid = _fade_span(0.5, -2.5, 0.75)
_span_low = _fade_span(0.25, -3.75, 0.625)
check("淡出中途**画得出来**（不是一段空窗）",
      _span_full > 0 and _span_mid > 0 and _span_low > 0, f"{_span_full}/{_span_mid}/{_span_low}")
check("由大到小：画出来的宽度一路收窄（100% -> ~75% -> ~62.5%）",
      _span_full > _span_mid > _span_low
      and abs(_span_mid / _span_full - 0.75) < 0.05
      and abs(_span_low / _span_full - 0.625) < 0.05,
      f"{_span_full} -> {_span_mid} -> {_span_low}")
check("淡出终点（50% + 不透明度 0）：一点墨都没有 = 最后完全消失",
      _fade_span(0.0, -5.0, 0.5) == 0)
_t9._set_frame(1.0, 0.0, 1.0)
_t9._on_hide_done()
qapp.processEvents()
check("淡完把「最后画过的那条」丢掉（下一次弹出不会漏出旧文字）", _t9._fade_text == "")
check("淡出归零后整条收起（这一轮完整走完：淡入 0.5s -> 停留 2s -> 淡出 0.5s）",
      not pet9.is_toast_visible())

# ---- 17d. 其它状态与收尾 ----
pet9.set_state_toast("休眠中")
qapp.processEvents()
check("换成「休眠中」：不带点 → 点定时器停下",
      _t9.shown_text == "休眠中" and not _t9._dots_timer.isActive())
check("「休眠中」也是**瞬态**：停留计时挂起（淡入结束后起表，2s 后自己淡出）",
      _t9._hold_pending is True and _t9._hold_text == "休眠中")
check("宽度跟着文本换（休眠中 ≠ 待机中...）",
      _t9.body_w == petmod.toast_body_w("休眠中") and _t9.body_w != _bw9)
pet9.clear_state_toast()
_t9._on_hide_done()
qapp.processEvents()
check("clear_state_toast()：淡出归零后整条收起",
      not pet9.is_toast_visible() and _t9.shown_text == "")
pet9.set_state_toast("待机中", dots=True)
_t9._on_show_done()
pet9.flash_toast("已唤醒")
pet9.clear_state_toast()
qapp.processEvents()
check("事件还盖着的时候收掉常驻状态：这一帧画的仍是事件那条",
      _t9.shown_text == "已唤醒" and pet9.toast_state_text == "")
_t9._on_hold_done()
_t9._on_hide_done()
qapp.processEvents()
check("事件结束后底下已经没有状态可露 → 整条收起", not pet9.is_toast_visible())

# ---- 17e. 跟随贴图：挪位 / 节能变形都重算 ----
pet9.set_state_toast("待机中", dots=True)
_t9._on_show_done()
pet9.move(300, 400)
qapp.processEvents()
_r9b = pet9._sprite_rect()
check("贴图挪了：气泡跟到新位置的**正上方居中**（窗口比本体高出的那 5px 留白要算进去）",
      (_t9.x(), _t9.y() + petmod.TOAST_POP_DY) == petmod.toast_rect(_r9b, _t9.body_w)[:2],
      f"{(_t9.x(), _t9.y() + petmod.TOAST_POP_DY)} vs {petmod.toast_rect(_r9b, _t9.body_w)[:2]}")
_y9b = _t9.y()
pet9.set_power_save(True, animate=False)
qapp.processEvents()
_r9c = pet9._sprite_rect()
check("节能形态压扁（贴图顶边往下走）后同样重算，不是停在旧高度",
      _t9.y() == _r9c.y() - petmod.TOAST_GAP - petmod.TOAST_H - petmod.TOAST_POP_DY and _t9.y() != _y9b,
      f"{_y9b} -> {_t9.y()}")
pet9.set_power_save(False, animate=False)
qapp.processEvents()

# ---- 17f. 真机像素：边框 / 底色 / 文字色 / 边框厚度 / 圆角 ----
pet9.move(600, 300)
pet9.set_state_toast("休眠中")
qapp.processEvents()
_t9.stop_all()                        # 逐帧验像素期间别让 2s 停留到点、把文字收走
_img9 = _t9.grab().toImage().convertToFormat(QImage.Format_RGBA8888)
_dpr9 = _img9.devicePixelRatio() or 1.0


def _tpx(xa, ya):
    """按**本体坐标**取样：本体画在窗口 y = TOAST_POP_DY 处，得加上那段留白。"""
    c = _img9.pixelColor(round(xa * _dpr9), round((ya + petmod.TOAST_POP_DY) * _dpr9))
    return (c.red(), c.green(), c.blue(), c.alpha())


_w9 = _t9.body_w
_seen9 = set()
for _yy in range(int(petmod.TOAST_H)):
    for _xx in range(_w9):
        _c9 = _tpx(_xx, _yy)
        if _c9[3] > 0:
            _seen9.add(_c9[:3])
check("边框色 = #0C447C（取上边框正中）", _tpx(_w9 // 2, 1)[:3] == (12, 68, 124), str(_tpx(_w9 // 2, 1)))
check("底色 = #E6F1FB", (230, 241, 251) in _seen9, str(sorted(_seen9)[:4]))
check("文字色 = #334155（与正文同色）", (51, 65, 85) in _seen9, str(sorted(_seen9)[:4]))
check("边框真的只有 2px：内侧 3px 处已经是底色（4px 边框时这里还是深蓝）",
      _tpx(_w9 // 2, 3)[:3] == (230, 241, 251), str(_tpx(_w9 // 2, 3)))
_tys9 = [yy for yy in range(int(petmod.TOAST_H)) for xx in range(_w9) if _tpx(xx, yy)[:3] == (51, 65, 85)]
check("文字上下都留了余量（高 30 略高于文字，不是贴着边框画）",
      min(_tys9) > 2 * petmod.TOAST_BORDER and max(_tys9) < petmod.TOAST_H - 2 * petmod.TOAST_BORDER,
      f"{min(_tys9)}~{max(_tys9)} / {petmod.TOAST_H}")
_opaque9 = next(yy for yy in range(10) if _tpx(0, yy)[3] == 255)
check("左上角是**圆角**（半径 3）：角上被切掉、约 4px 处才实色（半径 0 会从 0 就实、半径再大要更靠下）",
      _tpx(0, 0)[3] == 0 and 3 <= _opaque9 <= 5, f"corner={_tpx(0, 0)} first_opaque_y={_opaque9}")

# ---- 17g. 弹出 / 收起三件套：自下而上 5px + 50%<->100% 缩放 + 淡入淡出 ----
check("弹出起点 = 全透明 + 下方 5px + 50% 大小；终点 = 到位态（不透明 / 无位移 / 原尺寸）",
      _t9._pop_frame(0.0) == (0.0, 5.0, 0.5) and _t9._pop_frame(1.0) == (1.0, 0.0, 1.0),
      f"{_t9._pop_frame(0.0)} / {_t9._pop_frame(1.0)}")
check("收起起点 = 到位态；终点 = 全透明 + **再往上** 5px + 50% 大小（弹出倒着走）",
      _t9._out_frame(1.0) == (1.0, 0.0, 1.0) and _t9._out_frame(0.0) == (0.0, -5.0, 0.5),
      f"{_t9._out_frame(1.0)} / {_t9._out_frame(0.0)}")
check("缩放档位：50% -> 100% 线性（0.5 处 = 0.75）", abs(_t9._scale_for(0.5) - 0.75) < 1e-9)
_pops = [_t9._pop_frame(i / 20.0) for i in range(21)]      # 按播放顺序：v 0 -> 1
check("弹出中途三件套都单调：不透明度↑、位移趋于 0、尺寸↑",
      all(_pops[i][0] < _pops[i + 1][0] and _pops[i][1] > _pops[i + 1][1] and _pops[i][2] < _pops[i + 1][2]
          for i in range(20)))
_outs = [_t9._out_frame(1.0 - i / 20.0) for i in range(21)]  # 按播放顺序：v 1 -> 0
check("收起中途三件套都反向单调：不透明度↓、继续**往上**走、尺寸↓",
      all(_outs[i][0] > _outs[i + 1][0] and _outs[i][1] > _outs[i + 1][1] and _outs[i][2] > _outs[i + 1][2]
          for i in range(20)))


def _alpha_span(img_q, dpr):
    """整窗扫描：第一行 / 最后一行有实像素的 y（逻辑像素）。"""
    top = bot = None
    for yg in range(img_q.height()):
        for xg in range(img_q.width()):
            if img_q.pixelColor(xg, yg).alpha() > 0:
                if top is None:
                    top = yg / dpr
                bot = yg / dpr
                break
    return top, bot


_t9._set_frame(1.0, 0.0, 1.0)
qapp.processEvents()
_img_f = _t9.grab().toImage().convertToFormat(QImage.Format_RGBA8888)
_dpr_f = _img_f.devicePixelRatio() or 1.0
_top_f, _bot_f = _alpha_span(_img_f, _dpr_f)
check("【对照】全尺寸：本体占据窗口里 y=5~35 那一段（正是 TOAST_POP_DY 的留白之后）",
      abs(_top_f - petmod.TOAST_POP_DY) <= 1 and abs(_bot_f - (petmod.TOAST_POP_DY + petmod.TOAST_H)) <= 1,
      f"{_top_f}~{_bot_f}")
_t9._set_frame(1.0, 0.0, petmod.TOAST_MIN_SCALE)
qapp.processEvents()
_img_h = _t9.grab().toImage().convertToFormat(QImage.Format_RGBA8888)
_dpr_h = _img_h.devicePixelRatio() or 1.0
_top_h, _bot_h = _alpha_span(_img_h, _dpr_h)
check("50%：顶端往下收了一半高（5 -> 20）",
      abs(_top_h - (petmod.TOAST_POP_DY + petmod.TOAST_H / 2)) <= 1, f"top={_top_h}")
check("50%：**下沿一动不动**（缩放原点 = 本体下边中点，不是中心也不是上边）",
      abs(_bot_h - _bot_f) <= 1, f"{_bot_h} vs {_bot_f}")
_t9._set_frame(1.0, 0.0, 1.0)
qapp.processEvents()

# ---- 17h. 收尾 ----
pet9.flash_toast("已进入静音模式")
pet9.set_state_toast("待机中", dots=True)
_t9.stop_all()
check("stop_all()：动画 + 停留计时 + 点定时器全停（退出流程 / 收摊用）",
      _t9._anim is None and _t9._hold_timer is None and _t9._hold_pending is False
      and not _t9._dots_timer.isActive())
check("提示窗不吃鼠标（点击透传，不挡桌面操作）",
      bool(_t9.windowFlags() & Qt.WindowTransparentForInput) and _t9.testAttribute(Qt.WA_TranslucentBackground))
check("PetWindow 的对外接口齐了（两类文本 + 只读状态）",
      all(hasattr(pet9, n) for n in ("set_state_toast", "clear_state_toast", "flash_toast",
                                     "is_toast_visible", "toast_text", "toast_state_text",
                                     "toast_flash_text", "toast_dots")))
_t9.show()
pet9.close()
qapp.processEvents()
check("关桌宠时提示窗跟着关（它是独立顶层窗，不带走就会在桌上留个孤儿）", not _t9.isVisible())

# ---- 17i. 真事件循环：淡入 0.5s -> 停留 2s -> 淡出 0.5s（一整条链自己跑完）----
pet10 = new_pet(ALICE, at=(600, 300))
_t10 = pet10._toast
_t10.stop_all()
pet10.clear_state_toast()
_t10._on_hide_done()
qapp.processEvents()
pet10.flash_toast("已唤醒")
_t0 = time.monotonic()
_t_full = _t_hide = _t_gone = None
while time.monotonic() - _t0 < 5.0:
    qapp.processEvents()
    _el = time.monotonic() - _t0
    if _t_full is None and _t10.is_shown() and _t10.opacity >= 1.0:
        _t_full = _el
    if _t_full is not None and _t_hide is None and _t10._anim_kind == "hide":
        _t_hide = _el
    if _t_hide is not None and not _t10.is_shown():
        _t_gone = _el
        break
    time.sleep(0.01)
check("真事件循环：淡入约 0.5s 到全不透明",
      _t_full is not None and 0.35 <= _t_full <= 0.8, str(_t_full))
check("「停留 2s」是**从淡入结束那一刻**起算的（不是从 flash() 发起）",
      _t_hide is not None and 1.8 <= (_t_hide - _t_full) <= 2.3,
      f"{_t_full} -> {_t_hide}")
check("到点后淡出约 0.5s（反向三件套：掉不透明度 + 缩小 + 继续往上）",
      _t_gone is not None and 0.35 <= (_t_gone - _t_hide) <= 0.8, f"{_t_hide} -> {_t_gone}")
check("整条链 ≈ 3s（0.5 + 2 + 0.5）", _t_gone is not None and 2.7 <= _t_gone <= 3.4, str(_t_gone))
check("跑完就收干净：动画 / 停留计时都停了", _t10._anim is None and _t10._hold_timer is None)
pet10.close()
qapp.processEvents()

# ---- 17j. 上方放不下 → 让到贴图**下方** 5px（0.5s 平移；两边都放不下时仍待上方）----
check("让位常量：平移 500ms（与聊天气泡翻转同一条口径）、迟滞 20px",
      (petmod.TOAST_FLIP_MS, petmod.TOAST_FLIP_HYST) == (500, 20),
      f"{petmod.TOAST_FLIP_MS}/{petmod.TOAST_FLIP_HYST}")
check("上方够高（贴图 y=300）→ 仍待在贴图正上方",
      petmod.toast_above(_Spr(600, 300, 150, 250), AV, 30) is True)
check("上方**刚刚够**（y=40 = 本体 30 + 间隔 5 + 弹出留白 5）→ 仍待上方",
      petmod.toast_above(_Spr(600, 40, 150, 250), AV, 30) is True)
check("上方不够（贴图顶到屏幕上沿 y=0）→ 让到贴图**下方**",
      petmod.toast_above(_Spr(600, 0, 150, 250), AV, 30) is False)
check("迟滞：已经在下方时，上方要重新多出 20px（y=60）才让得回去",
      petmod.toast_above(_Spr(600, 59, 150, 250), AV, 30, False) is False
      and petmod.toast_above(_Spr(600, 60, 150, 250), AV, 30, False) is True)
check("迟滞防抖：同一个位置（上方刚好 40px）来、回两个方向都不换边",
      petmod.toast_above(_Spr(600, 40, 150, 250), AV, 30, True) is True
      and petmod.toast_above(_Spr(600, 40, 150, 250), AV, 30, False) is False)
check("上下都放不下（可用区比贴图还矮）→ 保持上方，不把提示推出屏幕",
      petmod.toast_above(_Spr(600, 20, 150, 250), QRect(0, 0, 800, 300), 30) is True)

pet11 = new_pet(ALICE, at=(600, 300))
_t11 = pet11._toast
pet11.set_state_toast("待机中", dots=True)
_t11._on_show_done()
_t11.stop_all()                       # 采样期间别让点定时器跳相位 / 让位动画打断
qapp.processEvents()
_s11 = pet11._sprite_rect()
check("一开始上方放得下：提示在贴图**正上方**（本体下沿 = 贴图顶边 − 5px）",
      _t11.above is True
      and _t11.y() + petmod.TOAST_POP_DY + petmod.TOAST_H == _s11.y() - petmod.TOAST_GAP,
      f"above={_t11.above} y={_t11.y()} sprite={_s11}")
pet11.move(_s11.x(), 0)                # 贴图顶到屏幕上沿：上方只剩 0px
qapp.processEvents()
check("贴图顶到屏幕上沿 → 改判到**下方**", _t11.above is False, str(_t11.above))
check("让位是 500ms OutCubic 的平移动画（与聊天气泡翻转同一个值）",
      _t11._flip_anim is not None
      and _t11._flip_anim.duration() == petmod.TOAST_FLIP_MS
      and _t11._flip_anim.easingCurve().type() == QEasingCurve.OutCubic,
      str(_t11._flip_anim.duration() if _t11._flip_anim else None))
check("让位**不重放弹出、不变淡**（是平移，不是重建提示）",
      _t11._anim is None and _t11.opacity == 1.0 and _t11.scale == 1.0,
      f"anim={_t11._anim} opacity={_t11.opacity} scale={_t11.scale}")
_t11._flip_anim.stop()
_t11._on_flip_value(0.5)
_mid11 = (_t11.x(), _t11.y())
_t11._on_flip_value(1.0)
_end11 = (_t11.x(), _t11.y())
_t11._flip_anim = None
check("让位途中确实在移动：中点与终点不同（是平移，不是瞬移）",
      _mid11 != _end11, f"{_mid11} -> {_end11}")
_s11 = pet11._sprite_rect()
check("落位后提示挂在贴图**下方**：本体上沿 = 贴图底边 + 5px（上下互为镜像）",
      _t11.y() + petmod.TOAST_POP_DY == _s11.y() + _s11.height() + petmod.TOAST_GAP,
      f"{_t11.y() + petmod.TOAST_POP_DY} vs {_s11.y() + _s11.height() + petmod.TOAST_GAP}")
check("让位期间横向照旧**以贴图中心线居中**",
      _t11.x() + _t11.width() // 2 == _s11.x() + _s11.width() // 2,
      f"{_t11.x() + _t11.width() // 2} vs {_s11.x() + _s11.width() // 2}")
pet11.move(600, 300)                   # 拖回来：上方重新够高
qapp.processEvents()
check("拖回来（上方重新够高）→ 又让回上方（同样是 500ms 平移）",
      _t11.above is True and _t11._flip_anim is not None, str(_t11.above))
_t11._flip_anim.stop()
_t11._on_flip_value(1.0)
_t11._flip_anim = None
_s11 = pet11._sprite_rect()
check("让回上方后落回**原来的高度**（来回拖不会越走越偏）",
      _t11.y() + petmod.TOAST_POP_DY + petmod.TOAST_H == _s11.y() - petmod.TOAST_GAP,
      f"y={_t11.y()} sprite={_s11}")
pet11.close()
qapp.processEvents()

print("== 18. 音量条搬进右键菜单（2026-09-19：单击贴图不再弹出）==")
pet18 = new_pet(ALICE, at=(700, 300))

# ---- 18a. 单击贴图不再弹音量条 ----
check("PetWindow 不再持有常驻音量条控件（_slider_box / _volume_slider / _mute_btn 全没了）",
      not any(hasattr(pet18, _n) for _n in ("_slider_box", "_volume_slider", "_mute_btn")))
check("旧的「弹出去」那套常量也删干净了（SLIDER_GAP / SLIDER_H / SLIDER_ANIM_DY / _slider_shown）",
      not any(hasattr(petmod, _n) for _n in ("SLIDER_GAP", "SLIDER_H", "SLIDER_BOTTOM",
                                             "SLIDER_ANIM_DY"))
      and not hasattr(pet18, "_slider_shown"))
_size_before = (pet18.width(), pet18.height())
QTest.mouseClick(pet18, Qt.LeftButton)          # 真·按下-释放，中间没有位移
qapp.processEvents()
check("单击之后窗口尺寸**一点没变**（不再为音量条让出 10+22+6px 的高度）",
      (pet18.width(), pet18.height()) == _size_before == (pet18._base_w, pet18._base_h),
      f"{(pet18.width(), pet18.height())} vs {_size_before}")
check("单击不再是「切换音量条显示」：源码里没有 _toggle_volume / _set_slider_visible / "
      "_animate_slider_in",
      all(_n not in (BASE / "app" / "pet.py").read_text(encoding="utf-8")
          for _n in ("_toggle_volume", "_set_slider_visible", "_animate_slider_in")))

# ---- 18b. 弹窗第一行就是音量条（宽度 = MENU_CONTENT_W；无边框；行高 = 菜单项高）----
# ⚠️ 十六改前这里写的是「贴图宽 − 5px」—— 那时宽度跟 `_base_w` 走，切角色会变（见 18f）。现在钉成常量。
_m18 = pet18._build_menu()
_size18 = _m18.sizeHint()
_rows18 = _m18.rows()
check("弹窗第一行就是音量条（自绘弹窗里的 kind == volume；控件是真的子控件，能拖能点）",
      _rows18[0]["kind"] == "volume" and _m18.bar() is not None
      and _m18.bar().parent() is _m18,
      str(_rows18[0]["kind"]))
_bar18 = _m18.bar()
check("音量条排在「切换」之前（用户要求：置于最顶端）",
      [_rows18[i]["kind"] for i in (0, 1)] == ["volume", "sep"]
      and [_m18.row_text(i) for i in range(len(_rows18))][2] == "切换")
check("音量条宽度 = MENU_CONTENT_W（145，十六改起与角色无关，不再跟 _base_w 走）",
      _bar18.width() == petmod.MENU_CONTENT_W == 145,
      f"{_bar18.width()} vs {petmod.MENU_CONTENT_W}")
check("弹窗宽度按音量条适配（= 音量条宽 + 两侧内边距 4px + 两侧边框 1px = 155）",
      _size18.width()
      == _bar18.width() + 2 * (petmod.VOL_MENU_PAD + petmod.MENU_BORDER_W)
      == 155,
      f"{_size18.width()} vs "
      f"{_bar18.width() + 2 * (petmod.VOL_MENU_PAD + petmod.MENU_BORDER_W)}")
check("**不要边框**：旧的 #volBox（白底 #FFFFFF + 1px #7DD3FC 边 + 圆角 8px）整层壳去掉",
      _bar18.styleSheet() == "" and _bar18.objectName() == ""
      and not _bar18.testAttribute(Qt.WA_StyledBackground),
      f"qss={_bar18.styleSheet()!r} obj={_bar18.objectName()!r}")
check("音量条那一行的行高 = 菜单项行高 MENU_ITEM_H（与「切换」行等高）",
      _bar18.height() == _m18.row_rect(2).height() == petmod.MENU_ITEM_H,
      f"{_bar18.height()} / {_m18.row_rect(2).height()} / {petmod.MENU_ITEM_H}")
check("滑块几何：起点 26、右留 8、铺满整行（高 28）",
      (_bar18.slider.x(), _bar18.slider.y(), _bar18.slider.height())
      == (26, 0, petmod.MENU_ITEM_H)
      and _bar18.slider.width() == petmod.MENU_CONTENT_W - 34,
      str(_bar18.slider.geometry()))
check("喇叭图标在左（3px 内缩、在 28px 的行里垂直居中 → y = 4）",
      (_bar18.icon.x(), _bar18.icon.y())
      == (petmod.VOL_BAR_ICON_X, (petmod.MENU_ITEM_H - 20) // 2),
      f"({_bar18.icon.x()}, {_bar18.icon.y()})")
check("⚠️ 八改：弹窗**不挂任何 effect**、也不动 `windowOpacity`（淡入 / 淡出全靠 painter —— "
      "分层窗口每帧改这两样都会闪）；⚠️ 十四改：没有缩放了，`_progress` 已删除",
      _m18.graphicsEffect() is None and _m18.windowOpacity() == 1.0
      and _m18._opacity == 1.0 and not hasattr(_m18, "_progress"),
      f"eff={_m18.graphicsEffect()} win={_m18.windowOpacity()} op={_m18._opacity}")
check("⚠️ 八改删掉阴影 effect 的两条理由（都实测过）：① 它本来就没画出来 —— boundingRect 比窗口大，"
      "真机上脏矩形越界会让 `UpdateLayeredWindowIndirect` 报「参数错误」，抓屏「带 / 不带」亮度一模一样（185.3）；"
      "② 它**会随机闪** —— 冻结动画后连测两轮：带阴影亮度乱蹦到 42~60（桌面基准 35.2），去掉就平滑（39.9→35.4→…）",
      not isinstance(_m18.graphicsEffect(), QGraphicsDropShadowEffect)
      and not isinstance(_m18.graphicsEffect(), QGraphicsOpacityEffect))
_m18.deleteLater()

pet18.set_volume(0.75)
_m18b = pet18._build_menu()
_bar18b = _m18b.bar()
check("音量条按**当前**音量初始化（不是写死 50）：0.75 → 75", _bar18b.slider.value() == 75,
      str(_bar18b.slider.value()))

# ---- 18c. 两处音量条 / 回调：值只有一个出口 ----
_seen18 = []
pet18.set_on_volume(lambda v: _seen18.append(("vol", round(v, 2))))
pet18.set_on_mute(lambda m: _seen18.append(("mute", m)))
_bar18b.slider.setValue(30)
check("拖动菜单里的音量条 → 回调主程序（0.0~1.0，不是 0~100）",
      _seen18 == [("vol", 0.3)] and pet18._volume == 0.3, str(_seen18))
check("拖动之后静音自动解除（与旧实现同一条规则）", pet18._muted is False)
QTest.mouseClick(_bar18b.icon, Qt.LeftButton)     # 真·点一下喇叭图标
check("点喇叭 → 静音：回调一次、滑块**位置不动**、配色转灰",
      _seen18[-1] == ("mute", True) and pet18._muted is True
      and _bar18b.slider.value() == 30 and _bar18b.slider.is_muted(), str(_seen18))
_bar18b.slider.setValue(60)
check("静音时拖滑块 → 先自动解除静音、再报音量（两个回调都在，顺序：mute 在前）",
      _seen18[-2:] == [("mute", False), ("vol", 0.6)] and pet18._muted is False, str(_seen18))

# ---- 18d. 反向同步（通用设置那一行 / 语音改了音量）----
pet18.set_volume(0.42)
check("set_volume() 同步菜单里那条音量条（不回调、防回环）",
      _bar18b.slider.value() == 42 and _seen18[-1] == ("vol", 0.6), str(_seen18[-3:]))
pet18.set_volume(0.9, muted=True)
check("set_volume(v, muted=True) 连静音态一起同步过去",
      _bar18b.slider.value() == 90 and pet18._muted is True and _bar18b.slider.is_muted())

# ---- 18e. 音量条被销毁后不能碰野指针 ----
# 正常路径是 `_menu()` 的 finally 把 `_bar` 清掉；但万一菜单被别处销毁（`deleteLater` 只是排队，
# 这里用 shiboken 直接删掉 C++ 对象来复现「控件真没了」），`_live_bar()` 必须有 RuntimeError 兜底。
_m18b.deleteLater()
qapp.processEvents()
_dead18 = QWidget()
shiboken6.Shiboken.delete(_dead18)      # 真·删掉 C++ 对象
pet18._bar = _dead18
try:
    pet18.set_volume(0.2)
    _ok18 = True
except RuntimeError:
    _ok18 = False
check("音量条被销毁后再 set_volume 不炸（_live_bar 捕获 RuntimeError 并清掉引用）",
      _ok18 and pet18._volume == 0.2 and pet18._bar is None,
      f"ok={_ok18} bar={pet18._bar}")
check("清过引用之后 _live_bar() 一直是 None（不会再摸 C++ 对象）", pet18._live_bar() is None)

# ---- 18f. 菜单尺寸与角色无关（2026-09-19 十六改）----
# 用户报：切到艾莲时右键菜单的宽度变了。根因：菜单宽原本 = `_base_w − MENU_NARROW`，而 `_base_w`
# 是 `_normal_size()` 按**贴图宽高比**推出来的显示宽（高度统一钉 DISPLAY_HEIGHT=250）——
# 爱丽丝 300×500 → 150（菜单 155），艾莲 256×256 → 250（菜单 **255**）。
# 用户口径：「将菜单尺寸统一成当前右键爱丽丝贴图弹出的菜单」⇒ 一律按 `MENU_CONTENT_W`。
_mA18 = pet18._build_menu()
pet18f = new_pet(ELLEN, at=(500, 300))
_mE18 = pet18f._build_menu()
check("（前提）确实换到艾莲了：它的贴图在屏显示宽和爱丽丝**不同**（256×256 → 250，不是 150）",
      (pet18f._base_w, pet18f._base_h) == (250, 250) and pet18._base_w == 150,
      f"ellen={pet18f._base_w}x{pet18f._base_h} alice={pet18._base_w}")
check("★ 艾莲的菜单宽度 = 爱丽丝的（155）—— 不再随贴图宽变宽",
      _mE18.sizeHint().width() == _mA18.sizeHint().width() == 155,
      f"{_mE18.sizeHint().width()} vs {_mA18.sizeHint().width()}")
check("★ 艾莲的音量条宽度 = 爱丽丝的（145 = `MENU_CONTENT_W`）",
      _mE18.bar().width() == _mA18.bar().width() == petmod.MENU_CONTENT_W == 145,
      f"{_mE18.bar().width()} vs {_mA18.bar().width()}")
check("滑块几何也逐字相等（起点 26 / 右留 8 / 铺满整行 ⇒ 宽 = 内容宽 − 34）",
      _mE18.bar().slider.geometry() == _mA18.bar().slider.geometry()
      and _mE18.bar().slider.width() == petmod.MENU_CONTENT_W - 34,
      f"{_mE18.bar().slider.geometry()} vs {_mA18.bar().slider.geometry()}")
check("高度也一致（一级菜单的行文案是固定的 ⇒ 行数 / 行高都不随角色变）",
      _mE18.sizeHint().height() == _mA18.sizeHint().height(),
      f"{_mE18.sizeHint().height()} vs {_mA18.sizeHint().height()}")
check("行表也不随角色变（同一份行文案、同一个 kind 序列）",
      [_mE18.row_text(i) for i in range(len(_mE18.rows()))]
      == [_mA18.row_text(i) for i in range(len(_mA18.rows()))]
      and [r["kind"] for r in _mE18.rows()] == [r["kind"] for r in _mA18.rows()])
check("常量：基准宽 `MENU_REF_W` = 150（爱丽丝那一档）、内容宽 = 150 − 5 = 145、"
      "`MENU_NARROW` 仍是 5",
      (petmod.MENU_REF_W, petmod.MENU_CONTENT_W, petmod.MENU_NARROW) == (150, 145, 5),
      str((petmod.MENU_REF_W, petmod.MENU_CONTENT_W, petmod.MENU_NARROW)))
# ⚠️ 结构层（反向）：`_build_menu()` 里**不许再出现 `self._base_w`** —— 写回去菜单立刻又跟角色跑。
# 走 AST 的 `Attribute` 结点（不是扫源码串）：`_build_menu` 的 docstring 里正提了 `self._base_w`
# 这个旧写法，扫串会误伤。
_tree18 = ast.parse((BASE / "app" / "pet.py").read_text(encoding="utf-8"))
_pw18 = next(n for n in _tree18.body if isinstance(n, ast.ClassDef) and n.name == "PetWindow")
_bm18 = next(n for n in _pw18.body
             if isinstance(n, ast.FunctionDef) and n.name == "_build_menu")
_bm18_self = {n.attr for n in ast.walk(_bm18)
              if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name)
              and n.value.id == "self"}
_bm18_names = {n.id for n in ast.walk(_bm18) if isinstance(n, ast.Name)}
check("⚠️ 十六改（结构层反向）：`_build_menu()` 里不再出现 `self._base_w`、且确实用了 "
      "`MENU_CONTENT_W`（把「贴图宽 − MENU_NARROW」写回去这一条立刻红）",
      "_base_w" not in _bm18_self and "MENU_CONTENT_W" in _bm18_names,
      str(sorted(_bm18_self)))
_mA18.deleteLater()
_mE18.deleteLater()
pet18f.close()
qapp.processEvents()

pet18.close()
qapp.processEvents()

print("== 19. 右键弹窗：位置算法 + 自绘弹出 +「切换」二级弹窗（2026-09-19 八改）==")
from PySide6.QtCore import QEvent, QPoint, QSize, QTimer, QVariantAnimation  # noqa: E402
from PySide6.QtGui import QColor, QMouseEvent  # noqa: E402

pet19 = new_pet(ALICE, at=(300, 300))
pet19.set_roles([("爱丽丝", "alice"), ("Ellen", "ellen")])
pet19.set_current_role("alice")


def _pump(seconds):
    """跑 `seconds` 秒真事件循环（动画得靠它推进）。"""
    t0 = time.time()
    while time.time() - t0 < seconds:
        qapp.processEvents()
        time.sleep(0.01)


def _pump_until(pred, limit=1.5):
    """推进事件循环直到 `pred()` 成立（或超时），返回最终是否成立。

    ⚠️★**别再用「拍脑袋 pump 固定秒数」去卡动画时刻**：Qt 定时器只在事件循环里点火，
    实测 `PATPAT_F1_MS=130` 那一下最晚到过 ~175ms（慢一拍 + 动画自己第一个 tick 的延迟），
    于是 `_pump(0.24)` 这种写法**时好时坏**（本轮第一版就这么挂了 6 项）。
    正确姿势：**等到状态到了再看值** —— 到达条件用这个辅助，具体数值照旧精确断言
    （超时了也返回 False，值断言会照样红，不会把 bug 放过去）。
    """
    t0 = time.time()
    while time.time() - t0 < limit:
        if pred():
            return True
        qapp.processEvents()
        time.sleep(0.01)
    return bool(pred())


check("常量：弹窗**淡出** 0.3s（十二改；一级与二级共用这一个常量）",
      petmod.MENU_FADE_MS == 300, str(petmod.MENU_FADE_MS))
check("⚠️ 十四改：一级弹窗淡入**只动不透明度**、时长 = `MENU_POP_MS`(300)（十二改定的那 0.3s）；"
      "**八改～十三改那套缩放全删干净** —— `MENU_POP_SCALE` / `MENU_POP_BASE` / `_progress` / "
      "`_scaling` / `_pop_base_color` / `_apply_anim` 一个都不许剩；"
      "**更早的两段式（十改）也仍然不许回来**（`MENU_CONTENT_MS` / `MENU_POP_DY` / `MENU_SLIDE` 常量、"
      "`_content` 通道、`_start_content` / `_on_content_*` 方法）",
      petmod.MENU_POP_MS == 300
      and not hasattr(petmod, "MENU_POP_SCALE")
      and not hasattr(petmod, "MENU_POP_BASE")
      and not hasattr(petmod, "MENU_CONTENT_MS")
      and not hasattr(petmod, "MENU_POP_DY") and not hasattr(petmod, "MENU_SLIDE")
      and not hasattr(petmod._MenuPopup, "_pop_base_color")
      and not hasattr(petmod._MenuPopup, "_apply_anim")
      and not hasattr(petmod._MenuPopup, "_start_content")
      and not hasattr(petmod._MenuPopup, "_on_content_frame")
      and not hasattr(petmod._MenuPopup, "_on_content_done"),
      str((getattr(petmod, "MENU_POP_MS", None), getattr(petmod, "MENU_POP_SCALE", None),
           getattr(petmod, "MENU_POP_BASE", None), getattr(petmod, "MENU_CONTENT_MS", None))))
check("常量：弹窗压住贴图 8px、二级弹窗弹出淡入 **0.3s**、离开宽限 **0s（立刻淡出）**"
      "（十三改；十二改时是 0.5s、再原 1.0s）",
      (petmod.MENU_GAP, petmod.MENU_NARROW, petmod.SUBMENU_FADE_MS,
       petmod.SUBMENU_GRACE_MS) == (8, 5, 300, 0),
      str((petmod.MENU_GAP, petmod.MENU_NARROW,
           petmod.SUBMENU_FADE_MS, petmod.SUBMENU_GRACE_MS)))
# ⚠️ 十四改：淡入的**底**就是抓来的真桌面 —— 用户口径「右键淡入（仅不透明度提高）」要的正是
# `α×菜单 + (1−α)×真桌面`，所以 `paintEvent` 必须：① 把 `_backdrop`（真桌面）**不透明地**铺满、
# ② 再用 `setOpacity(self._opacity)` 叠面板。这跟淡出是**同一条路**（十四改把 `_closing` 分支删了），
# 十二改那层「先白后深」的 `MENU_POP_BASE` 底层随之彻底去掉（它本来就是「没抓到桌面」时的补丁）。
_src_paint14 = inspect.getsource(petmod._MenuPopup.paintEvent)
_src_content14 = inspect.getsource(petmod._MenuPopup._paint_content)
check("⚠️ 十四改（结构层）：`paintEvent` **不分淡入 / 淡出** —— 只有一条路：铺真桌面底（`_backdrop`）"
      "+ `setOpacity(self._opacity)` 叠面板（`_opacity` 是唯一动画通道）",
      "_backdrop" in _src_paint14 and "setOpacity(self._opacity)" in _src_paint14
      and "_closing" not in _src_paint14,
      f"backdrop={'_backdrop' in _src_paint14} op={'setOpacity(self._opacity)' in _src_paint14} "
      f"closing={'_closing' in _src_paint14}")
check("⚠️ 十四改（结构层）：`paintEvent` 里**真桌面底先铺（不透明）、`setOpacity` 后设** —— "
      "顺序反了的话底图会跟着一起淡，淡入起点就会露出窗口底色（深色）闪一下黑；"
      "「按进度重算面板 / 底色」那套痕迹由下面的 AST 反向断言兜（注释里提旧实现不算）",
      _src_paint14.find("drawPixmap") != -1
      and _src_paint14.find("drawPixmap") < _src_paint14.find("setOpacity"),
      f"drawPixmap@{_src_paint14.find('drawPixmap')} "
      f"setOpacity@{_src_paint14.find('setOpacity')}")
check("⚠️ 十二改仍有效：动画期间 `render()` 音量条**只画子控件**（`RenderFlag.DrawChildren`）—— "
      "默认的 `DrawWindowBackground` 会按窗口调色板刷 `#1e1e1e`，音量条那行就成了**黑底**",
      "DrawChildren" in _src_content14)

# ---- 19a-0. 旧的 QMenu 那套整体删除（八改：换自绘弹窗 `_MenuPopup`）----
_src19 = (BASE / "app" / "pet.py").read_text(encoding="utf-8")


def _names_used(src):
    """AST 扫一遍：源码里真正**用到**的名字（注释 / 字符串里的不算）。"""
    out = set()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Name):
            out.add(node.id)
        elif isinstance(node, ast.ImportFrom):
            out.update(_a.asname or _a.name for _a in node.names)
        elif isinstance(node, ast.Import):
            out.update((_a.asname or _a.name).split(".")[0] for _a in node.names)
    return out


check("⚠️ 八改：`QMenu` 那套（`_MainMenu` / `_SubMenu` / `menu_skin` / `menu_qss` / "
      "`menu_size_of`）整段删除，换成自绘的 `_MenuPopup`",
      not any(hasattr(petmod, _n) for _n in
              ("_MainMenu", "_SubMenu", "menu_skin", "menu_qss", "menu_size_of")))
check("源码里不再**用到** `QMenu`（import / 实例化都没有了，只剩注释里提旧实现）",
      "QMenu" not in _names_used(_src19))
check("⚠️ 快照替身窗那套也**整体删除**（`_MenuPop` / `menu_shot` / `shadowed_shot` / "
      "`pop_rect` / `pop_window_rect` / `shadow_pad` / `_pop_corner`）",
      not any(hasattr(petmod, _n) for _n in
              ("_MenuPop", "menu_shot", "shadowed_shot", "pop_rect", "pop_window_rect",
               "shadow_pad", "_pop_corner")))
# ⚠️ 十四改（结构层，反向）：源码里**不再用到**任何缩放通道的名字 —— 注释 / docstring 里提旧实现不算，
# 所以这条是「连代码里都找不到了」的硬断言（谁把 `_apply_anim()` 那套找回来，这一条立刻红）。
_scale_names = {"MENU_POP_SCALE", "MENU_POP_BASE", "_progress", "_scaling",
                "_pop_base_color", "_apply_anim", "scale_in"}
check("⚠️ 十四改（结构层反向）：`app/pet.py` 里**不再用到**任何缩放通道的名字"
      "（`MENU_POP_SCALE` / `MENU_POP_BASE` / `_progress` / `_scaling` / `_pop_base_color` / "
      "`_apply_anim` / `scale_in`）",
      not (_names_used(_src19) & _scale_names),
      str(sorted(_names_used(_src19) & _scale_names)))
check("⚠️ 十四改：`_MenuPopup` 有三个新入口 —— `reopen_at`（PetWindow 装的回调）、"
      "`repop()`（按新位置重弹）、`_repop_at()`（右键落点 → 重弹）",
      all(hasattr(petmod._MenuPopup, _n) for _n in ("repop", "_repop_at"))
      and hasattr(petmod._MenuPopup(), "reopen_at"))

_raw19 = petmod._MenuPopup()
check("弹窗是**自绘的顶层弹窗**：`Qt.Popup` + 分层透明（`WA_TranslucentBackground` —— "
      "圆角外的像素真透明）",
      bool(_raw19.windowFlags() & Qt.Popup)
      and _raw19.testAttribute(Qt.WA_TranslucentBackground))
check("弹窗**不挂任何 effect**、也不动 `windowOpacity`（缩放 / 淡入全靠 painter —— "
      "分层窗口每帧改这两样都会闪）",
      _raw19.graphicsEffect() is None and _raw19.windowOpacity() == 1.0,
      f"eff={_raw19.graphicsEffect()} win={_raw19.windowOpacity()}")
_raw19.deleteLater()

_m19 = pet19._build_menu()
_size19 = _m19.sizeHint()
_pad19 = petmod.VOL_MENU_PAD + petmod.MENU_BORDER_W            # 5
_item_h19 = _m19.fontMetrics().height() + 2 * petmod.MENU_ITEM_PAD_Y
_sep_h19 = 2 * petmod.MENU_SEP_Y + 1                           # 9
check("`_build_menu()` 造的是 `_MenuPopup`（面板 / 菜单项 / 勾选 / 小尖 / 分隔线全在 paintEvent 里画）",
      isinstance(_m19, petmod._MenuPopup), type(_m19).__name__)
check("弹窗尺寸是自己排的：宽 = 音量条宽 145 + 2×(内边距 4 + 边框 1) = 155；"
      "高 = 内边距 + 音量条行 28 + 2 条分隔线 + 7 个菜单项（「显示聊天气泡」已下架）",
      _size19.width() == 155
      and _size19.height() == 2 * _pad19 + petmod.MENU_ITEM_H + 2 * _sep_h19 + 7 * _item_h19,
      f"{_size19} item_h={_item_h19}")
check("⚠️ 行高按**本机字体**现算（离屏是小字体、真机 9pt 微软雅黑 → 高度不同），"
      "所以只钉结构、不把 242 这类真机数字写死",
      _item_h19 == _m19.fontMetrics().height() + 16 and _pad19 == 5, str(_item_h19))

_rects19 = [_m19.row_rect(i) for i in range(len(_m19.rows()))]
check("逐行矩形：x / 宽一致（= 内边距 5 / 内容宽 145），y 首尾相接，"
      "最后一行下沿 + 内边距 = 面板高",
      all(r.x() == _pad19 and r.width() == _size19.width() - 2 * _pad19 for r in _rects19)
      and all(_rects19[i].y() == (_pad19 if i == 0 else _rects19[i - 1].bottom() + 1)
              for i in range(len(_rects19)))
      and _rects19[-1].bottom() + 1 + _pad19 == _size19.height(),
      str(_rects19))
check("逐行高：音量条 28 / 分隔线 9 / 菜单项 = 字体行高 + 16（七项等高，含「切换」）",
      [r.height() for r in _rects19]
      == [petmod.MENU_ITEM_H, _sep_h19, _item_h19, _sep_h19] + [_item_h19] * 6,
      str([r.height() for r in _rects19]))
check("行序：音量条 / 分隔线 / 切换 / 分隔线 / 节能模式 / patpat模式 / 桌宠固定 / 主界面 / 设置 / 退出",
      [_m19.row_text(i) for i in range(len(_m19.rows()))]
      == ["", "", "切换", "", "节能模式", "patpat模式", "桌宠固定", "主界面", "设置", "退出"],
      str([_m19.row_text(i) for i in range(len(_m19.rows()))]))

_avail19 = QRect(0, 0, 1920, 1080)
_sprite19 = QRect(900, 500, 150, 250)
_r19a, _side19a = petmod.menu_rect(_sprite19, _avail19, QPoint(950, 700), _size19)
check("默认贴右侧：菜单左边 = 贴图右边 − 8px，底边 = 鼠标点击的 y",
      (_r19a.x(), _r19a.y() + _r19a.height(), _side19a)
      == (900 + 150 - petmod.MENU_GAP, 700, "right"),
      f"{_r19a} {_side19a}")
_r19b, _side19b = petmod.menu_rect(QRect(1700, 500, 150, 250), _avail19, QPoint(1750, 700), _size19)
check("右侧放不下 → 改贴左侧：菜单右边 = 贴图左边 **+8px**（两侧对称，都压住贴图 8px）",
      (_r19b.x() + _r19b.width(), _r19b.y() + _r19b.height(), _side19b)
      == (1700 + petmod.MENU_GAP, 700, "left"),
      f"{_r19b} {_side19b}")
check("两侧对称：贴右时的重叠量 = 贴左时的重叠量（都是 8px）",
      ((900 + 150) - _r19a.x()) == (_r19b.x() + _r19b.width()) - 1700 == petmod.MENU_GAP,
      f"{((900 + 150) - _r19a.x())} / {(_r19b.x() + _r19b.width()) - 1700}")
_r19c, _ = petmod.menu_rect(_sprite19, _avail19, QPoint(950, 100), _size19)
check("上方放不下 → 菜单上边紧贴屏幕顶端（可用区 top）",
      _r19c.y() == _avail19.y() and _r19c.x() == 900 + 150 - petmod.MENU_GAP, str(_r19c))
_r19d, _ = petmod.menu_rect(QRect(900, 1000, 150, 250), _avail19, QPoint(950, 1080), _size19)
check("下方空间不足**不另判**：底部照样 = 点击 y（菜单往上长，本来就够不到屏幕底边）",
      _r19d.y() + _r19d.height() == 1080, str(_r19d))
_r19e, _ = petmod.menu_rect(QRect(20, 500, 150, 250), QRect(0, 0, 200, 1080), QPoint(40, 700), _size19)
check("两边都放不下 → 夹回可用区（不让整张菜单跑到屏幕外）",
      _r19e.x() == 0 and _r19e.x() + _r19e.width() <= 200, str(_r19e))

# ---- 19b. `_menu()` 的调用契约（探针弹窗：`pop_up` / `run` 打桩，不开事件循环）----
_calls19 = []
_probes19 = []


class _ProbeMenu19(petmod._MenuPopup):
    """探针弹窗：`pop_up()` / `run()` 只记下参数就返回，不上屏、不开事件循环。"""

    def __init__(self):
        super().__init__()
        _probes19.append(self)

    def sizeHint(self):
        return _size19

    def pop_up(self, rect, side="right"):
        _calls19.append((QRect(rect), side, pet19._menu_open))

    def run(self):
        return None


_rect_call19 = []
_menu_rect19 = petmod.menu_rect


def _spy_rect19(*a, **k):                   # 顺便记一次「位置确实是 menu_rect() 算的」
    _rect_call19.append(a)
    return _menu_rect19(*a, **k)


pet19._build_menu = lambda: _ProbeMenu19()
petmod.menu_rect = _spy_rect19
_t019 = time.time()
pet19._menu(QPoint(20, 20))
_dt19 = time.time() - _t019
petmod.menu_rect = _menu_rect19
del pet19._build_menu

_exp19, _side19exp = _menu_rect19(pet19._sprite_rect(), pet19._avail_rect(),
                                  pet19.mapToGlobal(QPoint(20, 20)), _size19)
check("`_menu()` 只调一次 `pop_up()`：位置 = `menu_rect()` 算出来的终态**本身**，"
      "并把 `side` 一起传下去（贴右侧时左边 = 贴图右边 − 8px）",
      len(_calls19) == 1 and _calls19[0][0] == _exp19 and _calls19[0][1] == _side19exp,
      f"{_calls19} expect={_exp19} {_side19exp}")
check("弹窗**直接上屏**：`_menu()` 立刻返回，动画在弹窗自己的事件循环里播（用户口径「直接弹出」）",
      _dt19 < 0.2, f"{_dt19:.3f}s")
check("`pop_up()` 拿到的尺寸 = `sizeHint()`（不再先 grab 快照 / resize 成别的尺寸）",
      bool(_calls19) and _calls19[0][0].size() == _size19,
      str(_calls19[0][0].size()) if _calls19 else "no call")
check("`pop_up()` 那一刻 `_menu_open` 已经是真（防重入的依据就在这儿）",
      bool(_calls19) and _calls19[0][2] is True, str(_calls19))
check("位置算法仍走 `menu_rect()`（没有被绕过），且算出来的弹窗整个落在可用区内",
      len(_rect_call19) == 1
      and _exp19.left() >= pet19._avail_rect().left()
      and _exp19.right() <= pet19._avail_rect().right(),
      f"{_exp19} avail={pet19._avail_rect()}")
check("`_menu_open` 跑完复位（不会第二次右键就被吞掉）", pet19._menu_open is False)
check("⚠️ 十四改：`_menu()` 给弹窗装上了 `reopen_at` 回调（菜单开着时右键重开的入口就挂在这儿）",
      bool(_probes19) and callable(_probes19[0].reopen_at),
      f"reopen_at={getattr(_probes19[0], 'reopen_at', None) if _probes19 else None}")

# ---- 19b-2. 十四改：重复弹出 —— `_reopen_menu()` 按**新点击点**重算位置再 `repop()` ----
_mr20_calls = []
_repop20_args = []


class _ProbeRepop20(petmod._MenuPopup):
    """只记 `repop()` 的参数（不真上屏）。"""

    def sizeHint(self):
        return _size19

    def repop(self, rect, side="right"):
        _repop20_args.append((QRect(rect), side))


_mr20_orig = petmod.menu_rect


def _spy_rect20(*a, **k):
    _mr20_calls.append(a)
    return _mr20_orig(*a, **k)


_pr20 = _ProbeRepop20()
petmod.menu_rect = _spy_rect20
pet19._reopen_menu(_pr20, QPoint(950, 700))
petmod.menu_rect = _mr20_orig
_pr20.deleteLater()
_exp20, _side20 = _mr20_orig(pet19._sprite_rect(), pet19._avail_rect(), QPoint(950, 700), _size19)
check("⚠️ 十四改：`PetWindow._reopen_menu()` 按**新的点击点**用 `menu_rect()` 重算位置再 `repop()` ——"
      "用户口径「重复弹出」= 挪到新点击位置重弹，而不是原地开关（与第一次弹出同一套规则）",
      len(_mr20_calls) == 1 and _repop20_args == [(_exp20, _side20)],
      f"menu_rect_calls={len(_mr20_calls)} repop={_repop20_args} exp={(_exp20, _side20)}")
check("⚠️ 十四改（结构层）：`PetWindow._menu()` 里写着把 `reopen_at` 装到弹窗上",
      "reopen_at" in inspect.getsource(petmod.PetWindow._menu))

# ---- 19c. 弹出动画（真窗口：**只有不透明度** 0 → 1；十四改把缩放整条路删了）----
def _new_menu19():
    m = petmod._MenuPopup()
    for _n in ("甲", "乙", "丙"):
        m.add_item(_n)
    return m


def _paint_op(menu, opacity):
    """把面板按给定不透明度画进一张**透明**离屏图（走真 `paintEvent` 后半段那条路）。

    十四改起没有缩放了，这里不再需要「按进度算变换」—— 只验 `setOpacity` 这一个通道：
    α=0 应当**什么都不画**（全透明）、α=1 铺满整窗、α=0.5 是同样的形状但整体半透明。
    """
    size = menu.sizeHint()
    img = QImage(size.width(), size.height(), QImage.Format_ARGB32_Premultiplied)
    img.fill(0)
    p = QPainter(img)
    p.setOpacity(opacity)
    menu._paint_panel(p)
    menu._paint_content(p)
    p.end()
    return img


def _bbox(img, thresh=40):
    """有内容（alpha 够高）的像素包围盒；空图给 None。"""
    left, top, right, bottom = img.width(), img.height(), -1, -1
    for y in range(img.height()):
        for x in range(img.width()):
            if img.pixelColor(x, y).alpha() > thresh:
                left, right = min(left, x), max(right, x)
                top, bottom = min(top, y), max(bottom, y)
    return None if right < 0 else (left, top, right, bottom)


_m19g = _new_menu19()
_size19g = _m19g.sizeHint()
_a1 = _bbox(_paint_op(_m19g, 1.0))
check("终态：面板**正好铺满整扇窗**（十改：窗口 == 面板，没有动画余量）",
      _a1 == (0, 0, _size19g.width() - 1, _size19g.height() - 1), str(_a1))
_a0 = _bbox(_paint_op(_m19g, 0.0))
check("⚠️ 十四改：淡入起点 α=0 —— 面板**完全不画**（透明离屏图上没有任何不透明像素）："
      "这就是「仅不透明度提高」的字面意思（不再有「缩到 50% 的那一块」）",
      _a0 is None, str(_a0))
_img05 = _paint_op(_m19g, 0.5)
_a05 = _bbox(_img05)
check("中间帧 α=0.5：包围盒**与终态一模一样大**（十四改不缩放了，只是整体变淡）、"
      "中心像素 alpha ≈ 128（真·半透明，不是「小一号」）",
      _a05 == _a1
      and abs(_img05.pixelColor(_size19g.width() // 2, _size19g.height() // 2).alpha() - 128) <= 8,
      f"a0={_a0} a05={_a05} a1={_a1} "
      f"mid={_img05.pixelColor(_size19g.width() // 2, _size19g.height() // 2).alpha()}")

_m19c = _new_menu19()
_size19c = _m19c.sizeHint()
_tgt19c = QRect(400, 300, _size19c.width(), _size19c.height())
_m19c.pop_up(_tgt19c, "right")
check("弹出起点：`_opacity == 0`（十四改起**没有缩放** —— `_progress` / `_scaling` 已删除、"
      "`_content` 这条十改的并行通道也仍然不存在）、面板尺寸本身**不动**",
      _m19c._opacity == 0.0 and _m19c._panel_size == _size19c
      and not hasattr(_m19c, "_progress") and not hasattr(_m19c, "_scaling")
      and not hasattr(_m19c, "_content"),
      f"op={_m19c._opacity} p={getattr(_m19c, '_progress', None)} "
      f"s={getattr(_m19c, '_scaling', None)} c={getattr(_m19c, '_content', None)}")
check("⚠️ 窗口几何**从头到尾不动**（十四改连缩放都没了）—— 这是「不再闪」的关键；"
      "窗口尺寸 == 面板 == sizeHint",
      _m19c.geometry() == QRect(_tgt19c.x(), _tgt19c.y(), _size19c.width(), _size19c.height())
      and _m19c.size() == _size19c,
      f"{_m19c.geometry()} size={_m19c.size()}")
check("弹出动画参数：0.0 → 1.0、时长 = `MENU_POP_MS`(300)、缓动 = **OutQuad**"
      "（十一改定的缓动；十四改只是把动画的量从「大小」换成「不透明度」）",
      _m19c._anim is not None and _m19c._anim.duration() == petmod.MENU_POP_MS
      and (_m19c._anim.startValue(), _m19c._anim.endValue()) == (0.0, 1.0)
      and _m19c._anim.easingCurve().type() == QEasingCurve.OutQuad,
      str((_m19c._anim.duration() if _m19c._anim else None,
           _m19c._anim.easingCurve().type() if _m19c._anim else None)))
_samples19 = []
for _ in range(4):
    _pump(0.05)
    _samples19.append(_m19c._opacity)
check("弹出中：不透明度**单调不降**、且真的在 0~1 之间推进（十四改唯一在动的东西）",
      0.0 < _samples19[0] <= _samples19[-1] <= 1.0
      and all(_samples19[i] <= _samples19[i + 1] + 1e-9 for i in range(len(_samples19) - 1)),
      f"{_samples19}")
check("⚠️ 八改：淡入全程窗口纹丝不动（六改前每帧 `move()` 正是残留闪烁的来源）",
      _m19c.pos() == _tgt19c.topLeft(), f"pos={_m19c.pos()}")
# 等这一整段弹出（0.3s）跑完
_t0 = time.time()
while _m19c._animating() and time.time() - _t0 < 1.5:
    _pump(0.02)
_pump(0.3)
check("0.3s 后：完全不透明、动画收尾（`_animating()` 翻假）、位置仍在终态；"
      "⚠️ 十一改：**没有第二段** —— 这一份 `_anim` 就是整段弹出（0.3s，不是 0.4 + 0.2）",
      _m19c._opacity == 1.0 and not _m19c._animating() and _m19c.pos() == _tgt19c.topLeft(),
      f"op={_m19c._opacity} pos={_m19c.pos()}")
_m19c.deleteLater()

# ⚠️ 十一改回归：整段弹出的**真实耗时**就是 `MENU_POP_MS`（两段式那版是 0.6s）。
# 这里卡 `MENU_POP_MS + 60ms` 的粗判 —— 只要有人把第二段加回来，这条会立刻红。
_m19t = _new_menu19()
_size19t = _m19t.sizeHint()
_t19t0 = time.time()
_m19t.pop_up(QRect(300, 300, _size19t.width(), _size19t.height()), "right")
while _m19t._animating() and time.time() - _t19t0 < 2.0:
    _pump(0.01)
_dt19t = time.time() - _t19t0
check("⚠️ 十一改回归：弹出**一整段**就是 `MENU_POP_MS`(300ms) —— 不再是 0.4 + 0.2 = 0.6s",
      _dt19t < petmod.MENU_POP_MS / 1000.0 + 0.06, f"{_dt19t:.3f}s")
_m19t.close_animated()
_pump(0.8)
_m19t.deleteLater()

# ⚠️ 十改回归（真机截图才发现，十一改继续有效）：动画收尾时 `_animating()` 翻假，而 `_sync_children()`
# 只在动画的**帧**里被调 —— 少了「收尾再调一次」，音量条会一直停在动画期间的 `hide()` 状态，
# 而且 `paintEvent` 也不再 `render()` 它 → 菜单弹完，最顶上那条音量条是**空白**的。
_m19v = petmod._MenuPopup(145)
_vbar19 = petmod._VolumeBar(145, 0.5, None, None)
_m19v.add_volume(_vbar19)
_m19v.add_separator()
_m19v.add_item("甲")
_size19v = _m19v.sizeHint()
_m19v.pop_up(QRect(300, 300, _size19v.width(), _size19v.height()), "right")
_pump(0.05)
check("弹出中：音量条是**藏起来**的（改由 `paintEvent` 里 `render()` 画进同一套变换）",
      _m19v._animating() and not _vbar19.isVisible(),
      f"animating={_m19v._animating()} vis={_vbar19.isVisible()}")
_t0 = time.time()
while _m19v._animating() and time.time() - _t0 < 1.5:
    _pump(0.02)
_pump(0.15)
check("⚠️ 动画收尾 → 音量条**必须显示回来**（`_on_in_done()` 里再 `_sync_children()` 一次）",
      not _m19v._animating() and _vbar19.isVisible(),
      f"animating={_m19v._animating()} vis={_vbar19.isVisible()}")


def _calls_in_func(src, func_name, callee, class_name=None):
    """AST：源码里 `func_name` 这个函数体里有没有调 `… . callee()`。

    ⚠️ `class_name` 给了就**限定在那个类里**找（不给 = 全文件按方法名裸找第一个同名的）。
    `pet.py` 里同名方法不止一处：第二款气泡的 `_ThinkingOverlay._on_in_done` 与音量条收尾的
    `_MenuPopup._on_in_done` 同名，且前者**排在前面** —— 裸按名字找会先撞上它，
    于是「音量条那一支到底有没有调 `_sync_children`」永远查错人（本文件 3360 行同款坑）。
    """
    tree = ast.parse(src)
    roots = ([n for n in ast.walk(tree)
              if isinstance(n, ast.ClassDef) and n.name == class_name]
             if class_name else [tree])
    for root in roots:
        for node in ast.walk(root):
            if isinstance(node, ast.FunctionDef) and node.name == func_name:
                return any(isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                           and n.func.attr == callee for n in ast.walk(node))
    return False


# ⚠️ 结构层（必补）：上面那条行为断言**抓不到「把这一下删掉」** —— 合成一段后末帧恰好到 1.0 时
# `_on_in_frame` 也会把控件放出来（临时改回实测过：删掉仍然 ALL_OK）。它真正兜的是「末帧不是恰好
# 1.0」和「动画被提前停掉」，只有结构层能钉住。
check("⚠️ 结构层：`_on_in_done()` 存在、且函数体里**必须调 `_sync_children()`**"
      "（兜底：末帧不是恰好 1.0 / 动画被提前停 → 否则音量条停在空白）",
      _calls_in_func((BASE / "app" / "pet.py").read_text(encoding="utf-8"),
                     "_on_in_done", "_sync_children", "_MenuPopup"),
      "no _sync_children call")
_m19v.close_animated()
_pump(0.8)
_m19v.deleteLater()

_hit19c = []
_m19k = petmod._MenuPopup()
for _n in ("甲", "乙", "丙"):
    _m19k.add_item(_n, on_trigger=lambda n=_n: _hit19c.append(n))
_m19k.pop_up(QRect(400, 300, _size19c.width(), _size19c.height()), "right")
_pump(0.7)
QTest.mouseClick(_m19k, Qt.LeftButton, Qt.NoModifier, _m19k.row_rect(1).center())
_pump(0.12)
check("点中某一行：回调**已触发**，弹窗不立刻消失，而是先淡出（`_opacity` 掉到 1 以下）",
      _hit19c == ["乙"] and _m19k.isVisible() and _m19k._opacity < 1.0 and _m19k._closing,
      f"hit={_hit19c} visible={_m19k.isVisible()} op={_m19k._opacity:.2f}")
_pump(0.8)
check("淡出跑完 → 弹窗真的关掉（`isVisible()` 为假）", not _m19k.isVisible())
_m19k.deleteLater()

_m19k2 = _new_menu19()
_m19k2.pop_up(QRect(200, 200, _size19c.width(), _size19c.height()), "right")
_pump(0.7)
QTest.keyClick(_m19k2, Qt.Key_Escape)
_pump(0.12)
check("按 Esc：也不立刻关，先淡出（仍可见 + `_opacity` 在降）",
      _m19k2.isVisible() and _m19k2._opacity < 1.0, f"op={_m19k2._opacity:.2f}")
_pump(0.8)
check("Esc 那次淡出跑完 → 关掉", not _m19k2.isVisible())
_m19k2.deleteLater()

_m19k3 = _new_menu19()
_m19k3.pop_up(QRect(120, 120, _size19c.width(), _size19c.height()), "right")
_pump(0.7)
_m19k3.mousePressEvent(QMouseEvent(QEvent.MouseButtonPress, QPointF(-8.0, -8.0),
                                   QPointF(-8.0, -8.0), Qt.LeftButton, Qt.LeftButton,
                                   Qt.NoModifier))
_pump(0.12)
check("点弹窗外面（十改起窗口 == 面板，「面板外」就是「窗口外」）：Qt 默认会**立刻** hide，"
      "这里被拦下先淡出（否则 0.5s 淡出根本没机会播）",
      _m19k3.isVisible() and _m19k3._opacity < 1.0, f"op={_m19k3._opacity:.2f}")
_pump(0.8)
check("点外面的淡出跑完 → 关掉", not _m19k3.isVisible())
_m19k3.deleteLater()

# ---- 19c-2. 真像素：白底 / 1px 黑边 / 圆角 3px / 悬停浅蓝深蓝 / 分隔线色（样式照原菜单）----
_m19p = petmod._MenuPopup()
_m19p.add_separator()
_m19p.add_item("甲")
_size19p = _m19p.sizeHint()
_m19p._apply_mask()                      # region 是「按当前这一帧的面板形状」算的，静止态也要先算一次
_img19p = _m19p.grab().toImage()
_dpr19p = _img19p.devicePixelRatio() or 1.0


def _cp(img, x, y, dpr=1.0):
    return img.pixelColor(int(round(x * dpr)), int(round(y * dpr)))


def _near(c, hexrgb, tol=20):
    t = QColor(hexrgb)
    return (abs(c.red() - t.red()) <= tol and abs(c.green() - t.green()) <= tol
            and abs(c.blue() - t.blue()) <= tol)


def _row_has(img, row, hexrgb, tol, dpr):
    """某一行里存在这个颜色的像素（文字那种抗锯齿的，用「存在」判定最稳）。"""
    for y in range(row.top(), row.bottom() + 1):
        for x in range(row.left(), row.right() + 1):
            if _near(_cp(img, x, y, dpr), hexrgb, tol):
                return True
    return False


_mid19p = _size19p.height() // 2
check("面板底色 = #FFFFFF（白底，与原菜单一致）",
      _near(_cp(_img19p, _size19p.width() - 12, _m19p.row_rect(1).center().y(), _dpr19p),
            "#FFFFFF"),
      str(_cp(_img19p, _size19p.width() - 12, _m19p.row_rect(1).center().y(),
              _dpr19p).name()))
check("边框 = 1px 黑（#000000，照原菜单）",
      _near(_cp(_img19p, 0, _mid19p, _dpr19p), "#000000", 60),
      str([_cp(_img19p, x, _mid19p, _dpr19p).name() for x in (0, 1, 2)]))
_mask19p = _m19p.mask()
check("圆角 3px：**窗口 region** 角外不算本窗（mask 里没有 (0,0)）、往里 2px 算；"
      "像素上四角也不再是黑的（= 菜单底色 —— 十改把整窗刷成背景色，圆角由 region 裁）",
      not _mask19p.contains(QPoint(0, 0)) and _mask19p.contains(QPoint(2, 2))
      and all(_near(_cp(_img19p, x, y, _dpr19p), "#FFFFFF") for x, y in
              ((0, 0), (_size19p.width() - 1, 0),
               (0, _size19p.height() - 1), (_size19p.width() - 1, _size19p.height() - 1))),
      f"corner={_cp(_img19p, 0, 0, _dpr19p).name()} in={_cp(_img19p, 2, 2, _dpr19p).name()}")
check("普通行文字色 = #334155（正文色）",
      _row_has(_img19p, _m19p.row_rect(1), "#334155", 40, _dpr19p))
check("分隔线 = #CBD5E1（1px，左右内缩 6px、上下留白 4px）",
      _row_has(_img19p, _m19p.row_rect(0), "#CBD5E1", 20, _dpr19p))

_m19p._hover = 1                      # 悬停在「甲」那一行
_img19h = _m19p.grab().toImage()
check("悬停行：底色 = #E6F1FB（浅蓝底）",
      _near(_cp(_img19h, _size19p.width() - 12, _m19p.row_rect(1).center().y(), _dpr19p),
            "#E6F1FB"),
      str(_cp(_img19h, _size19p.width() - 12, _m19p.row_rect(1).center().y(),
              _dpr19p).name()))
check("悬停行文字色 = #0C447C（深蓝字）",
      _row_has(_img19h, _m19p.row_rect(1), "#0C447C", 40, _dpr19p))
check("悬停只在悬停那一行：别的行（这里没有）不受影响 —— 底色判定取的是行内右侧空白处，"
      "不会把文字的颜色误认成底色",
      not _row_has(_img19p, _m19p.row_rect(1), "#E6F1FB", 20, _dpr19p))
_m19p.deleteLater()

# ---- 19c-3. ⚠️ 十四改：淡入的「底」= **不透明铺满的真桌面**，面板再按 α 叠上去 ----
# 离屏抓不到真桌面（`grabWindow` 返回空），所以用一块**纯色替身底图**把合成钉死：
# ① 面板圆角之外（region 会裁掉、但 grab 看得见）应当读到**纯底色**，不是窗口底色；
# ② α=0.5 时面板内 = `0.5×菜单白 + 0.5×底色` = 粉 —— 这正是 `α×菜单 + (1−α)×真桌面`。
_m19bk = petmod._MenuPopup()
_m19bk.add_item("甲")
_size19bk = _m19bk.sizeHint()
_m19bk._backdrop = QPixmap(_size19bk)          # 替身底图：纯红（离屏抓不到真桌面，用纯色钉合成）
_m19bk._backdrop.fill(QColor("#FF0000"))
_bkx = _size19bk.width() - 12                  # 面板右侧的空白处：不会被文字干扰
_bky = _m19bk.row_rect(0).center().y()


def _grab_at(menu, opacity):
    """把 `menu` 冻在给定 α 上 grab，读「面板内空白处」那一个像素。"""
    menu._opacity = opacity
    img = menu.grab().toImage()
    dpr = img.devicePixelRatio() or 1.0
    return img.pixelColor(int(round(_bkx * dpr)), int(round(_bky * dpr)))


check("⚠️ 十四改：α=1 时面板内是**纯菜单白**（底图被面板完全盖住，不往外透）",
      _near(_grab_at(_m19bk, 1.0), "#FFFFFF"), str(_grab_at(_m19bk, 1.0).name()))
check("⚠️ 十四改：α=0 时面板内读到的是**底图色**（纯红）—— 底图**不跟着 `_opacity` 淡**，"
      "所以淡入起点看到的就是「弹窗下面那张桌面」（这就是用户要的「纯不透明度提高」）",
      _near(_grab_at(_m19bk, 0.0), "#FF0000", 10), str(_grab_at(_m19bk, 0.0).name()))
check("⚠️ 十四改：α=0.5 时面板内 = `0.5×菜单白 + 0.5×底图红` = **粉** —— 这就是"
      "「`α×菜单 + (1−α)×真桌面`」那条合成（不是白、也不是红）",
      _near(_grab_at(_m19bk, 0.5), "#FF8080", 26), str(_grab_at(_m19bk, 0.5).name()))
_m19bk.deleteLater()

# ---- 19d.「切换」二级弹窗：长驻 + 同款边框 / 颜色 + 边框紧贴 + 宽限 0（立刻淡出，十三改）----
_m19b = pet19._build_menu()
_size19b = _m19b.sizeHint()
_sub19 = pet19._switch_menu
check("二级弹窗与一级弹窗是**同一个类**（`_MenuPopup`）→ 边框、颜色、字号天生一致",
      isinstance(_sub19, petmod._MenuPopup) and isinstance(_m19b, petmod._MenuPopup))
check("二级弹窗是**长驻一份**（再开一次弹窗还是同一只）—— 淡入淡出 / 宽限计时才挂得住",
      pet19._build_menu() is not None and pet19._switch_menu is _sub19)
check("每次开弹窗重填角色项（当前角色勾上）",
      [_sub19.row_text(i) for i in range(len(_sub19.rows()))] == ["爱丽丝", "Ellen"]
      and [r["checked"] for r in _sub19.rows()] == [True, False],
      str([(_sub19.row_text(i), _sub19.rows()[i]["checked"])
           for i in range(len(_sub19.rows()))]))
check("「切换」那一行挂着二级弹窗（`_sub_row` 指向它，鼠标停上去就展开）",
      _m19b.rows()[_m19b._sub_row]["submenu"] is _sub19, str(_m19b._sub_row))

_m19b.pop_up(QRect(300, 300, _size19b.width(), _size19b.height()), "right")
_pump(0.1)
# 真鼠标路径：鼠标停到「切换」行 → `mouseMoveEvent` 自己把二级弹窗叫出来
_sub19.hide_now()
_hover_pt = _m19b.row_rect(_m19b._sub_row).center()
_m19b.mouseMoveEvent(QMouseEvent(QEvent.Type.MouseMove, QPointF(_hover_pt), QPointF(_hover_pt),
                                 Qt.NoButton, Qt.NoButton, Qt.NoModifier))
check("鼠标移到「切换」行（真 `mouseMoveEvent` 路径）→ 二级弹窗**自己**展开"
      "（hover 展开）",
      _sub19.isVisible(), f"vis={_sub19.isVisible()}")
check("⚠️ 十四改：二级弹窗与一级**同一条路** —— 只做不透明度（起点 `_opacity == 0`）；"
      "`_progress` / `_scaling` 已删除（缩放整条路都没了）",
      _sub19._opacity == 0.0
      and not hasattr(_sub19, "_progress") and not hasattr(_sub19, "_scaling"),
      f"op={_sub19._opacity} p={getattr(_sub19, '_progress', None)}")
_f19, _s19 = _m19b.frameGeometry(), _sub19.frameGeometry()
check("二级弹窗**紧贴**一级弹窗边框（gap = 0，边框挨边框不留缝）",
      _s19.x() == _f19.x() + _f19.width(),
      f"main={_f19} sub={_s19} gap={_s19.x() - (_f19.x() + _f19.width())}")
check("二级弹窗纵向对齐「切换」那一行（行顶 / 夹回可用区）",
      _s19.y() == _f19.y() + _m19b.row_rect(_m19b._sub_row).y(),
      f"sub.y={_s19.y()} row.y={_m19b.row_rect(_m19b._sub_row).y()} main.y={_f19.y()}")
# ⚠️ 十三改：宽限已是 **0** —— 只要 `_poll` 还活着，`_pump` 里第一拍（100ms）二级弹窗就开始淡出了。
# 所以凡是「只想验某个静态状态 / 只想验淡入跑完」的地方，都要先 `_poll.stop()` 把宽限计时孤立掉；
# 宽限本身由下面专门那一大段（`_check_submenu` / 三条事件路径）测。
_m19b._poll.stop()
_pump(0.45)
check("0.3s（`SUBMENU_FADE_MS`）后：二级弹窗完全不透明、动画收尾（`_animating()` 翻假）、"
      "这一份动画时长就是 `SUBMENU_FADE_MS`（一级 / 二级同一条不透明度通道）",
      _sub19._opacity == 1.0 and not _sub19._animating()
      and _sub19._anim is not None
      and _sub19._anim.duration() == petmod.SUBMENU_FADE_MS,
      f"op={_sub19._opacity} animating={_sub19._animating()} "
      f"dur={_sub19._anim.duration() if _sub19._anim else None}")


# ---- 19b-2. 窗口 region（mask）：面板圆角外不许露「不透明黑」（九改；十改起窗口已无余量）----
check("`MENU_MASK_PAD == 0`（十改）：窗口 == 面板，region 就按面板形状裁；"
      "整窗已刷成菜单底色，不再需要外扩那 1px 去挡黑边",
      petmod.MENU_MASK_PAD == 0, str(petmod.MENU_MASK_PAD))
check("`_MenuPopup` 有逐帧 `_apply_mask()`：Popup 在 Windows 上**不是分层窗口**，"
      "只能靠 region 把「没画到的地儿」从窗口里切掉，否则露窗口初始底色 = 不透明黑",
      hasattr(petmod._MenuPopup, "_apply_mask")
      and "region" in (petmod._MenuPopup._apply_mask.__doc__ or ""),
      "no _apply_mask")
_mask19 = _m19b.mask()
check("一级弹窗终态：mask 非空，且**底边正好停在面板底**（十改后窗口 == 面板，圆角外仍被裁掉）",
      bool(_mask19 and not _mask19.isEmpty())
      and abs(_mask19.boundingRect().bottom()
              - (_size19b.height() + petmod.MENU_MASK_PAD - 1)) <= 2
      and abs(_mask19.boundingRect().top() + petmod.MENU_MASK_PAD) <= 2,
      str(_mask19.boundingRect()) if _mask19 else "None")
# ⚠️ 十四改：没有缩放了 —— region 不再逐帧变，恒等于**面板圆角矩形本身**（`pop_up()` 里算一次）。
# 八改～十三改那套「按当前缩放算 region、底边钉住、锚边跟 side 走」连根删除：十三改修的那个
# 「region 只缩高度、右侧漏底色竖条」的 bug 从根上没了（不再有 scale 这个概念）。
# 缓存键也随之简化：只跟 (面板宽, 面板高, MENU_MASK_PAD) 有关，跟 side / 进度无关。
_pw19, _ph19 = _m19b._panel_size.width(), _m19b._panel_size.height()
_mask19_rect = _m19b.mask().boundingRect()
check("⚠️ 十四改：region == **整个面板**（宽高都到 100%、贴左上角），不再有「只缩一个轴」的残留",
      abs(_mask19_rect.width() - _pw19) <= 2 and abs(_mask19_rect.height() - _ph19) <= 2
      and abs(_mask19_rect.left()) <= 2 and abs(_mask19_rect.top()) <= 2
      and abs(_mask19_rect.bottom() - (_ph19 - 1)) <= 2,
      f"region={_mask19_rect} panel=({_pw19},{_ph19})")
_m19b._side = "left"
_m19b._mask_key = None
_m19b._apply_mask()
_mask19_left_rect = _m19b.mask().boundingRect()
check("⚠️ 十四改：换 `side` **不改变** region（没有缩放，也就没有「锚边」概念了）",
      _mask19_left_rect == _mask19_rect, f"{_mask19_left_rect} vs {_mask19_rect}")
_m19b._side = "right"
_m19b._mask_key = None
_m19b._apply_mask()
check("二级弹窗同样带 mask（紧贴一级弹窗，两窗之间不该有黑缝）",
      bool(_sub19.mask() and not _sub19.mask().isEmpty()), "empty")
# 一级弹窗靠近屏幕右缘 → 右边放不下，二级弹窗改贴左边，**同样是 gap = 0**
_sub19.hide_now()
_m19b.pop_up(QRect(600, 300, _size19b.width(), _size19b.height()), "right")
_pump(0.05)
_m19b._show_submenu()
_m19b._poll.stop()          # ⚠️ 十三改：宽限已是 **0**，别让宽限计时把这次展示提前关掉
_s19b, _f19b = _sub19.frameGeometry(), _m19b.frameGeometry()
check("一级弹窗右边放不下 → 二级弹窗改贴**左边**，照样 gap = 0（并且仍纵向对齐「切换」行）",
      _s19b.x() + _s19b.width() == _f19b.x()
      and _s19b.y() == _f19b.y() + _m19b.row_rect(_m19b._sub_row).y(),
      f"main={_f19b} sub={_s19b} gap={_f19b.x() - (_s19b.x() + _s19b.width())}")
_pump(0.4)


class _FakeCursor19:
    """替身鼠标：`_tick()` 里那句 `QCursor.pos()` 换成我们说在哪就在哪。"""

    _p = QPoint(0, 0)

    @staticmethod
    def pos():
        return _FakeCursor19._p


_real_cursor19 = petmod.QCursor
petmod.QCursor = _FakeCursor19
# ⚠️ 十三改：宽限从 0.5s 改成 **0**（一离开就淡出）—— 这里不再算「第几拍」，改成钉两件事：
# ① 定时器那一路**第一拍就成立**；② 事件路径（`mouseMoveEvent` / `leaveEvent`）**不经过定时器**
# 也能当场关掉（用户口径是「立刻」，不能等 `_poll` 那 100ms）。
_check_sub19 = petmod._MenuPopup._check_submenu
check("⚠️ 十三改：宽限逻辑只有一处 —— `_tick()` 只是 `_check_submenu(tick=True)` 的定时器包装",
      hasattr(petmod._MenuPopup, "_check_submenu")
      and "_check_submenu" in inspect.getsource(petmod._MenuPopup._tick),
      "no _check_submenu")
check("⚠️ 十三改：两条**事件路径**都在（`mouseMoveEvent` 里当场核 + `leaveEvent` 里当场核）——"
      "这是「立刻」二字落在代码里的地方，被删掉就又变成「等 100ms 那一拍」",
      "_check_submenu" in inspect.getsource(petmod._MenuPopup.mouseMoveEvent)
      and "_check_submenu" in inspect.getsource(petmod._MenuPopup.leaveEvent),
      "event path missing")
_FakeCursor19._p = QPoint(5000, 5000)          # 远在天边：两边都不在
_m19b._out_ms = 0
_m19b._poll.stop()
_m19b._tick()
check(f"⚠️ 十三改：宽限 0 —— 定时器**第一拍**（{petmod._MenuPopup.TICK_MS}ms）鼠标两边都不在"
      "就开始淡出（不再有 0.5s 的维持期）",
      _sub19._closing, f"closing={_sub19._closing} out={_m19b._out_ms}")
_FakeCursor19._p = (_m19b._panel_global_rect().topLeft()
                    + _m19b.row_rect(_m19b._sub_row).center())
_m19b._tick()
check("淡出途中把鼠标移回「切换」行 → **撤销**这次淡出（不关），计时也清零",
      not _sub19._closing and _m19b._out_ms == 0 and _sub19.isVisible(),
      f"closing={_sub19._closing} out={_m19b._out_ms} vis={_sub19.isVisible()}")
_FakeCursor19._p = _m19b._panel_global_rect().topLeft() + _m19b.row_rect(0).center()
_m19b._tick()
check("⚠️ 九改：鼠标停在**别的行**（音量行）不算「回到菜单」→ 宽限 0 下**一拍就关**"
      "（旧的整窗 `frameGeometry()` 判据会把底下那 20px 透明余量也算成「在里面」，"
      "计时老被清零 → 看着就像「移开了也不会自动关」）",
      _sub19._closing, f"closing={_sub19._closing} out={_m19b._out_ms}")
_FakeCursor19._p = (_m19b._panel_global_rect().topLeft()
                    + _m19b.row_rect(_m19b._sub_row).center())
_m19b._tick()
check("再移回「切换」行 → 又撤销（`cancel_close()` 是真的能救回来）",
      not _sub19._closing and _sub19.isVisible(), str(_sub19._closing))
# 事件路径②：**不调用 `_tick()`**，只发一个「鼠标挪到别的行」的 mouseMoveEvent
_FakeCursor19._p = QPoint(5000, 5000)
_m19b._poll.stop()
_m19b.mouseMoveEvent(QMouseEvent(QEvent.MouseMove,
                                  QPointF(_m19b.row_rect(0).center()),
                                  QPointF(5000.0, 5000.0),
                                  Qt.NoButton, Qt.NoButton, Qt.NoModifier))
check("⚠️ 十三改：一级弹窗 `mouseMoveEvent` 里光标已不在「切换」行 → **当场**核一次、立刻淡出"
      "（一次事件就够，不用等 `_poll` 那 100ms）",
      _sub19._closing, f"closing={_sub19._closing} out={_m19b._out_ms}")
_FakeCursor19._p = (_m19b._panel_global_rect().topLeft()
                    + _m19b.row_rect(_m19b._sub_row).center())
_m19b.mouseMoveEvent(QMouseEvent(QEvent.MouseMove,
                                  QPointF(_m19b.row_rect(_m19b._sub_row).center()),
                                  QPointF(5000.0, 5000.0),
                                  Qt.NoButton, Qt.NoButton, Qt.NoModifier))
check("移回「切换」行 → 又撤销（这条走 `_show_submenu()`，不会误关）",
      not _sub19._closing and _sub19.isVisible(), str(_sub19._closing))
# 事件路径③：光标离开**二级弹窗自己** → 它回头叫一级核一次
_FakeCursor19._p = QPoint(5000, 5000)
_sub19._poll.stop()
_sub19.leaveEvent(QEvent(QEvent.Leave))
check("⚠️ 十三改：**二级弹窗自己的 `leaveEvent`** 也会立刻核一次（`_owner` 回头叫一级）——"
      "光标不在任一边内 → 当场开始淡出",
      _sub19._closing, f"closing={_sub19._closing}")
_FakeCursor19._p = (_m19b._panel_global_rect().topLeft()
                    + _m19b.row_rect(_m19b._sub_row).center())
_m19b._poll.stop()
_m19b.leaveEvent(QEvent(QEvent.Leave))
check("⚠️ 十三改：**一级弹窗自己的 `leaveEvent`** 同样当场核 —— 但光标还在「切换」行上时"
      "`_sub_hit()` 仍为真 → **不**误关（这就是「移出窗口就关、移向二级弹窗不关」的分界）",
      not _sub19._closing and _sub19.isVisible(), str(_sub19._closing))
_FakeCursor19._p = QPoint(5000, 5000)
_m19b._poll.stop()
_m19b.leaveEvent(QEvent(QEvent.Leave))
check(f"⚠️ 十三改：一级弹窗 `leaveEvent` + 光标两边都不在 → 立刻开始淡出（不等 "
      f"{petmod._MenuPopup.TICK_MS}ms 的那一拍）",
      _sub19._closing, str(_sub19._closing))
petmod.QCursor = _real_cursor19
_pump(0.8)
check("淡出跑完 → 二级弹窗自己藏起来（不透明度回到 0）",
      not _sub19.isVisible() and _sub19._opacity == 0.0,
      f"visible={_sub19.isVisible()} op={_sub19._opacity}")
check("⚠️ 九改：淡出跑完 `_closing` **复位**（不复位的话这一只淡出过一次就再也弹不出来，"
      "点它也会被当成「正在关」）",
      not _sub19._closing, str(_sub19._closing))

# ---- 19d-2. 二级弹窗里选中 → 回调 + 一级弹窗一起关 ----
_switch19 = []
pet19.set_on_switch(lambda k: _switch19.append(k))
_m19f = pet19._build_menu()
_m19f.pop_up(QRect(600, 300, _m19f.sizeHint().width(), _m19f.sizeHint().height()), "right")
_pump(0.7)
_sub19f = pet19._switch_menu
_m19f._show_submenu()
_pump(0.7)
# ⚠️ 这里故意用**爱丽丝**（index 0）而不是艾莲：`_activate()` 是**底层**入口，它**不查 `enabled`**
# （禁用闸在 `mouseReleaseEvent` / `_forward_press` 那两条**鼠标**路径上）—— 拿艾莲（2026-09-28 起
# 不可切换）来演「选中 → 回调」，会让人误读成「切艾莲是通的」。禁用那条在下面 19d-3 另行断言。
_sub19f._activate(0)                            # 真点击走的就是这条
_pump(0.8)
check("二级弹窗里选中：回调收到角色 key（真·切换），且**一级弹窗跟着一起关**",
      _switch19 == ["alice"] and not _sub19f.isVisible() and not _m19f.isVisible(),
      f"{_switch19} sub={_sub19f.isVisible()} main={_m19f.isVisible()}")

# ---- 19d-3. ★角色的「可切换性」：艾莲暂不可切换（2026-09-28 用户拍板；docs/02 §24）----
# 用户口径：「角色切换（**主界面左侧头像下的切换** + **右键桌宠的切换**）里的艾莲切换成**不可点击**的状态，
#            暂时**仅可使用爱丽丝**」。★艾莲**仍在列表里**（不删不藏），只是灰掉 + 点不动。
from app import config as cfgmod31  # noqa: E402
check("★★真值：`config.SWITCHABLE_ROLES == ('alice',)` —— ★钉**绝对值**"
      "（只核「两处都传了 enabled=」会被「把元组加回 ellen」绕过：两处照传、测试照绿）",
      cfgmod31.SWITCHABLE_ROLES == ("alice",), repr(cfgmod31.SWITCHABLE_ROLES))

_pet31 = new_pet(ALICE, at=(360, 360))
_pet31.set_roles([("爱丽丝", "alice"), ("Ellen", "ellen")])
_pet31.set_current_role("alice")
_calls31 = []
_pet31.set_on_switch(lambda k: _calls31.append(k))
_sub31 = _pet31._build_menu().submenu()
_sub31.sizeHint()                      # 触发 _relayout，行 rect 才算得出来
_r31 = {_sub31.row_text(i): _sub31.rows()[i] for i in range(len(_sub31.rows()))}
check("★★「切换」二级：**艾莲那行 `enabled is False`**（灰掉）、**爱丽丝那行 `enabled is True`**（正对照）"
      "；且**两行都还在**（不是删掉 / 隐藏）",
      set(_r31) == {"爱丽丝", "Ellen"}
      and _r31["Ellen"]["enabled"] is False and _r31["爱丽丝"]["enabled"] is True,
      str({k: v["enabled"] for k, v in _r31.items()}))


def _click_row31(widget, row):         # noqa: E306
    """在 `widget` 上给 `row` 的 rect 中心合成一次真正的左键 press + release。"""
    _c = row["rect"].center()
    for _t in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonRelease):
        qapp.sendEvent(widget, QMouseEvent(_t, QPointF(_c), QPointF(_c),
                                           Qt.LeftButton, Qt.LeftButton, Qt.NoModifier))


# ★**不是只核 `enabled` 字段**（那只是「表象」）—— 真点一下：艾莲那行不许换来任何东西。
_calls31.clear()
_click_row31(_sub31, _r31["Ellen"])
check("★★真点一下**艾莲**：`_on_switch` **一次都没收到**（点不动，不是「事件没送到」）",
      _calls31 == [], repr(_calls31))
# ★正对照：同一条合成路径点爱丽丝**必须真的换** ⇒ 证明上面那次「没收到」是**拦住了**、不是事件丢了。
_calls31.clear()
_click_row31(_sub31, _r31["爱丽丝"])
check("★正对照：真点一下**爱丽丝**：回调**真的收到 `alice`**", _calls31 == ["alice"], repr(_calls31))
_pet31.close()

# ---- 19e. `_menu()` 整条路（真弹窗上屏 → 动画跑完 → 关掉后清引用）----
_guard = QTimer()
_guard.setInterval(120)
_seen19 = []


def _sweep():
    for _w in QApplication.topLevelWidgets():
        if isinstance(_w, petmod._MenuPopup) and _w.isVisible() and _w._loop is not None:
            _seen19.append((QSize(_w.size()), QSize(_w.sizeHint()), QSize(_w._panel_size)))
            _w.close_animated()
            _guard.stop()


_guard.timeout.connect(_sweep)
_guard.start()
QTimer.singleShot(8000, _guard.stop)     # 兜底：无论如何都不把测试挂死
_del19 = []
_real_del19 = petmod._MenuPopup.deleteLater


def _spy_del19(_self):                   # 记一笔「弹窗被排队回收了」
    _del19.append(_self)
    _real_del19(_self)


petmod._MenuPopup.deleteLater = _spy_del19
_t0 = time.time()
pet19._menu(QPoint(20, 20))
_dt19e = time.time() - _t0
petmod._MenuPopup.deleteLater = _real_del19
check("_menu() 走完整条路（真弹窗上屏 → 动画跑完自己关 → 回来后清掉 _bar / _menu_open）",
      pet19._menu_open is False and pet19._bar is None and 0.05 < _dt19e < 1.5,
      f"{_dt19e:.2f}s open={pet19._menu_open} bar={pet19._bar}")
check("⚠️ 上屏的弹窗**第一帧就是终态尺寸**：窗口 == 面板 == sizeHint"
      "（十改起不再多 20px；不是缩小版、也不是 158×30 的小方块）",
      bool(_seen19) and _seen19[0][0] == _size19
      and _seen19[0][2] == _seen19[0][1] == _size19,
      str(_seen19))
check("不再有替身窗残留：`PetWindow` 上没有 `_pop` 这个属性（快照窗那套删干净了）",
      not hasattr(pet19, "_pop"))
check("弹窗用完全部回收：`_menu()` 结束时对它调了 `deleteLater()`（连音量条一起；"
      "不然它是带 parent 的，每次右键都留下一个隐藏子窗）",
      len(_del19) == 1 and _del19[0] is not pet19._switch_menu,
      f"n={len(_del19)}")
pet19._menu_open = True                  # 假装「弹窗正开着」
_t0 = time.time()
pet19._menu(QPoint(20, 20))
_dt19f = time.time() - _t0
check("弹窗还开着时再右键 → 立刻忽略（防重入，不会叠出第二张弹窗）",
      _dt19f < 0.2 and pet19._menu_open is True and pet19._bar is None,
      f"{_dt19f:.2f}s open={pet19._menu_open}")
# ---- 19f. 「一次单击关掉整套菜单」：把弹窗装成应用级事件过滤器（九改）----
def _press19(global_xy, button=Qt.LeftButton):
    """造一个「鼠标按下」：`eventFilter` 只看 `globalPosition()` 与 `button()`。

    ⚠️ 十四改起 `button()` 也是判据（右键 = 重复弹出、左键在菜单外 = 淡出、其它 = 吃掉不动），
    所以这个 helper 要能造非左键的事件。
    """
    if isinstance(global_xy, (tuple, list)):
        p = QPointF(global_xy[0], global_xy[1])
    else:
        p = QPointF(global_xy.x(), global_xy.y())
    return QMouseEvent(QEvent.Type.MouseButtonPress, QPointF(0, 0), p,
                       button, button, Qt.NoModifier)


class _FakeApp19:
    """替身 `QApplication`：只记「谁被装成过滤器了」。"""

    def __init__(self):
        self.installed = []
        self.removed = []

    def installEventFilter(self, o):
        self.installed.append(o)

    def removeEventFilter(self, o):
        self.removed.append(o)


_fake_app19 = _FakeApp19()
_real_qa19 = petmod.QApplication


class _QA19:
    @staticmethod
    def instance():
        return _fake_app19


petmod.QApplication = _QA19
_seen19f = []
_guard2 = QTimer()
_guard2.setInterval(120)


def _sweep19f():
    for _w in _real_qa19.topLevelWidgets():
        if isinstance(_w, petmod._MenuPopup) and _w.isVisible() and _w._loop is not None:
            _seen19f.append(_w)
            _w.close_animated()
            _guard2.stop()


_guard2.timeout.connect(_sweep19f)
_guard2.start()
QTimer.singleShot(8000, _guard2.stop)
pet19._menu_open = False              # 上一节留了 True（防重入那次），这里要真弹一张
pet19._menu(QPoint(20, 20))
_guard2.stop()
petmod.QApplication = _real_qa19
check("开菜单时把弹窗装成 `QApplication` 的事件过滤器，关掉后又拆掉（不漏挂）",
      len(_fake_app19.installed) == 1
      and isinstance(_fake_app19.installed[0], petmod._MenuPopup)
      and _fake_app19.removed == _fake_app19.installed,
      f"installed={len(_fake_app19.installed)} removed={len(_fake_app19.removed)}")

_m19g = pet19._build_menu()
_m19g.pop_up(QRect(400, 400, _m19g.sizeHint().width(), _m19g.sizeHint().height()), "right")
_pump(0.7)
_sub19g = pet19._switch_menu
_m19g._show_submenu()
# ⚠️ 十三改：宽限 **0** —— 离屏测试里真光标并不在「切换」行上，`_poll` 一起拍就会把二级关掉。
# 本节只验「点哪儿算点在菜单上」，所以把宽限计时停掉，让二级停在开着的样子。
_m19g._poll.stop()
_pump(0.7)
check("二级弹窗开着时点外面的**第一下**：`eventFilter` 返回 True（把这一下吃掉，"
      "不再交给 Qt 的 popup 逻辑 —— 那套既不播淡出、又要把第一下吞掉）",
      _m19g.eventFilter(_m19g, _press19((5, 5))) is True)
_pump(0.8)
check("外面的**一次**单击 → 一级 + 二级**一起**关掉（不用再点第二次）",
      not _m19g.isVisible() and not _sub19g.isVisible(),
      f"main={_m19g.isVisible()} sub={_sub19g.isVisible()}")
_m19g.pop_up(QRect(400, 400, _m19g.sizeHint().width(), _m19g.sizeHint().height()), "right")
_pump(0.7)
_m19g._show_submenu()
_m19g._poll.stop()                    # 同上：别让宽限计时把二级提前关掉
_pump(0.7)
check("点在二级弹窗**面板**上：不拦（返回 False，交给二级自己走 hover / 选中）",
      _m19g.eventFilter(_m19g, _press19(_sub19g._panel_global_rect().center())) is False)
check("判据是**面板**矩形：面板下沿再往下 5px 已经不算「点在菜单上」"
      "（十改后窗口 == 面板，所以这就是屏幕上的下沿之外）",
      not _m19g._panel_hit(_m19g._panel_global_rect().bottomLeft() + QPoint(0, 5)))
# ⚠️ **十七改改掉了这条契约的一半**：原先是「点在一级弹窗面板上一律不拦（返回 False）」。
# 现在**二级占着鼠标**那一半归 `eventFilter` 自己转发（见 19h）—— 所以这一档只剩
# 「二级**没开**时仍是老契约」。先收掉二级再验（收掉 = 一级重新拿到真事件）。
_m19g._hide_submenu(animated=False)
_pump(0.5)
check("二级**没开**时点一级面板：仍不拦（返回 False）—— 十七改只动了「二级占着鼠标」那一档",
      _m19g.eventFilter(_m19g, _press19(_m19g._panel_global_rect().center())) is False)

# ---- 19f-2. 十四改：**右键重复弹出**（不是切换关掉）、**左键**才关、其它键吃掉不动 ----
_repop_calls19 = []
_m19g.reopen_at = lambda gp: _repop_calls19.append(QPoint(gp))
check("⚠️ 十四改：菜单开着时**右键**（菜单外）→ `eventFilter` 返回 True（吃掉这一下）并触发重复弹出"
      "（`reopen_at` 收到新的屏幕落点）—— 用户口径「重复按右键则重复弹出而非起到切换状态的作用」",
      _m19g.eventFilter(_m19g, _press19((8, 9), Qt.RightButton)) is True
      and _repop_calls19 == [QPoint(8, 9)],
      f"calls={_repop_calls19}")
check("⚠️ 十四改：右键落在**菜单里**（面板内）也是重复弹出 —— 不做「点在菜单上就不管」的特判",
      _m19g.eventFilter(_m19g, _press19(_m19g._panel_global_rect().center(),
                                       Qt.RightButton)) is True
      and len(_repop_calls19) == 2,
      str(_repop_calls19))
check("⚠️ 十四改：右键那两下**没有**把菜单关掉（`_closing` 仍为假、仍可见）—— 不是切换语义",
      not _m19g._closing and _m19g.isVisible(), f"closing={_m19g._closing}")
# 直接验 `_repop_at()` 在**没装** `reopen_at` 时退化成「原地重新淡入」（几何不动、不关）
_m19g.reopen_at = None
_m19g._opacity = 1.0
_geo19_before = QRect(_m19g.geometry())
_m19g._repop_at(QPoint(1000, 1000))
check("⚠️ 十四改：`_repop_at()` 在没装 `reopen_at` 时退化成「原地重新淡入」"
      "（几何不动、不透明度回到 0 再升、不关）",
      _m19g.geometry() == _geo19_before and _m19g._opacity < 1.0 and not _m19g._closing,
      f"geo={_m19g.geometry()} op={_m19g._opacity} closing={_m19g._closing}")
_pump(0.5)
check("⚠️ 十四改：`eventFilter` 只对**左键**判「点在外面才关」—— 非左键（这里用中键）落在外面是"
      "「吃掉但不动」，菜单仍在（别让 Qt 的 popup 逻辑把它 hide 掉）",
      _m19g.eventFilter(_m19g, _press19((8, 9), Qt.MiddleButton)) is True
      and _m19g.isVisible() and not _m19g._closing,
      f"vis={_m19g.isVisible()} closing={_m19g._closing}")
_m19g.close_animated()
_pump(0.8)
check("19f 收尾：整套都关掉了，而且 `_closing` 也复位了（能再弹第二次）",
      not _m19g.isVisible() and not _m19g._closing and not _sub19g.isVisible())
pet19._menu_open = False

# ---- 19h. 十七改：二级占着鼠标时，一级的 hover 与点击由**我们自己**接管 ----
# 根因（2026-09-20 量到，见 devlog 第十七轮）：一级与二级**都是 `Qt.Popup`**，而 Qt **只把鼠标
# 投给「活动 popup」** —— 二级一 `show()`，`activePopupWidget()` 就从一级切到二级
# （★淡出那 300ms 全程也算，实测），一级从此收不到真的 mouseMoveEvent / press / release
# ⇒ 用户实感「二级在的时候，一级既不高亮、点了也不生效」。修法两条：
# ① 16ms 的 `_hover_poll` 自算 hover；② `eventFilter` 转发一级面板上的左键（按下即生效 + 关整套）。
_SRC19 = (BASE / "app" / "pet.py").read_text(encoding="utf-8")


def _poll_calls_in_func(src, func_name, poll_name):
    """AST：`func_name` 函数体里对 `self.<poll_name>` 起了哪些调用（返回方法名集合）。

    比 `_calls_in_func` 严一档：它只认「调了 `_xxx()`」这个属性名，钉不住**是谁**调的 ——
    而十七改的关键恰恰是「`_hover_poll` 自己在起落」，所以这里必须看**接收者**是不是它。
    """
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.FunctionDef) and node.name == func_name:
            return {n.func.attr for n in ast.walk(node)
                    if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                    and isinstance(n.func.value, ast.Attribute)
                    and n.func.value.attr == poll_name}
    return set()


check("⚠️ 十七改（结构层）：新增 hover 节拍常量 `HOVER_MS` = 16（≈一帧）",
      petmod._MenuPopup.HOVER_MS == 16, str(petmod._MenuPopup.HOVER_MS))
check("⚠️ 十七改（结构层）：`_sub_owns_mouse()` 的判据是**活动 popup 换人**"
      "（`…activePopupWidget()`）—— 它同时是**自限开关**：Qt 若改回真投递就自动失效，不会双动作",
      _calls_in_func(_SRC19, "_sub_owns_mouse", "activePopupWidget")
      and _calls_in_func(_SRC19, "_sub_owns_mouse", "isVisible"))
check("⚠️ 十七改（结构层）：`_hover_tick()` 里**必须**先问 `_sub_owns_mouse()`"
      "（少了它就会和真的 `mouseMoveEvent` 抢 `_hover`）",
      _calls_in_func(_SRC19, "_hover_tick", "_sub_owns_mouse"))
check("⚠️ 十七改（结构层）：`eventFilter()` 的转发分支**必须**由 `_sub_owns_mouse()` 把关，"
      "并交给 `_forward_press()`",
      _calls_in_func(_SRC19, "eventFilter", "_sub_owns_mouse")
      and _calls_in_func(_SRC19, "eventFilter", "_forward_press"))
check("⚠️ 十七改（结构层）：`_show_submenu()` 里要起 `_hover_poll`、`_hide_submenu()` 里要停它"
      "（跟着二级的生死走）",
      "start" in _poll_calls_in_func(_SRC19, "_show_submenu", "_hover_poll")
      and "stop" in _poll_calls_in_func(_SRC19, "_hide_submenu", "_hover_poll"),
      f"start={_poll_calls_in_func(_SRC19, '_show_submenu', '_hover_poll')} "
      f"stop={_poll_calls_in_func(_SRC19, '_hide_submenu', '_hover_poll')}")

_m19h = pet19._build_menu()
_m19h.pop_up(QRect(400, 400, _m19h.sizeHint().width(), _m19h.sizeHint().height()), "right")
_pump(0.7)
_sub19h = pet19._switch_menu
check("⚠️ 十七改：二级**没开**时 `_sub_owns_mouse()` 为假（一级正常收真事件，不接管）",
      _m19h._sub_owns_mouse() is False)
_m19h._show_submenu()
_m19h._poll.stop()                    # 十三改：宽限 0，不停掉计时 `_pump` 第一拍就把二级关了
_pump(0.7)
check("⚠️ 十七改：二级一开，`activePopupWidget()` 就不再是一级（这就是量到的根因）",
      petmod.QApplication.activePopupWidget() is not _m19h and _sub19h.isVisible(),
      f"active={type(petmod.QApplication.activePopupWidget()).__name__}")
check("⚠️ 十七改：此时 `_sub_owns_mouse()` 为真 —— 一级的输入交给自算那一路",
      _m19h._sub_owns_mouse() is True)
check("⚠️ 十七改：二级一开，hover 表就起来了（`_hover_poll` 在跑、节拍 16ms）",
      _m19h._hover_poll.isActive() and _m19h._hover_poll.interval() == 16,
      f"active={_m19h._hover_poll.isActive()} itv={_m19h._hover_poll.interval()}")


class _Cursor19:
    """替身 `QCursor`：`_hover_tick()` 只看 `QCursor.pos()`，所以不必真挪鼠标。"""

    p = QPoint(0, 0)

    @staticmethod
    def pos():
        return QPoint(_Cursor19.p)


_real_cursor19 = petmod.QCursor
petmod.QCursor = _Cursor19
try:
    _row_h19 = 8                              # 「设置」那一行（行序见 `_build_menu`；2026-09-20
    #                                           十七改在「节能模式」下面插了「patpat模式」→ 7 → 8）
    _Cursor19.p = _m19h.mapToGlobal(_m19h.row_rect(_row_h19).center())
    _m19h._hover = -1
    _m19h._hover_tick()
    check(f"⚠️ 十七改：光标在一级第 {_row_h19} 行上 → `_hover_tick()` 把它算成 hover 行"
          "（一级收不到真 `mouseMoveEvent`，这条表是 hover 的唯一来源）",
          _m19h._hover == _row_h19, f"hover={_m19h._hover}")
    _Cursor19.p = _sub19h._panel_global_rect().center()
    _m19h._hover_tick()
    check("⚠️ 十七改：光标移到**二级**面板上 → hover 归 -1（一级不该还亮着某一行）",
          _m19h._hover == -1, f"hover={_m19h._hover}")
    _m19h._hover = -1
    _m19h._hover_tick()
    _m19h._hover_tick()
    check("⚠️ 十七改：连叫两次、命中行没变 → `_hover` 保持不变（行没变就不重绘）",
          _m19h._hover == -1, f"hover={_m19h._hover}")

    # 点击转发：**按下即生效** + 关掉整套
    _fired19 = []
    _m19h._rows[_row_h19]["trigger"] = lambda: _fired19.append("设置")
    check("⚠️ 十七改：二级占着鼠标时点一级项 → `eventFilter` 返回 True"
          "（自己转发，不让 Qt 把这下拿去关二级）",
          _m19h.eventFilter(_m19h, _press19(
              _m19h.mapToGlobal(_m19h.row_rect(_row_h19).center()))) is True)
    # ★配对标记必须**紧接着按下**查：这一档是「按下即生效」，转发那一下当场就 `close_all()` 了，
    #   往后一旦 `_pump` 到淡出收尾，`_finish_close()` 会把标记复位 —— 第一版就是在这里挂的。
    check("⚠️ 十七改：转发过按下之后 `_swallow_release` 置位（要把配对的那次抬起也吃掉）",
          _m19h._swallow_release is True, f"swallow={_m19h._swallow_release}")
    _rel19 = QMouseEvent(QEvent.Type.MouseButtonRelease, QPointF(0, 0), QPointF(0, 0),
                         Qt.LeftButton, Qt.NoButton, Qt.NoModifier)
    check("⚠️ 十七改：配对的那次**左键抬起**被吃掉（返回 True）并复位标记",
          _m19h.eventFilter(_m19h, _rel19) is True and _m19h._swallow_release is False,
          f"swallow={_m19h._swallow_release}")
    check("⚠️ 十七改：标记复位后再来一次抬起就**不**吃了（返回 False）—— 只吃我们转发过按下的"
          "那一次，否则会把用户在二级上正常选角色的抬起也吞掉",
          _m19h.eventFilter(_m19h, _rel19) is False)
    _pump(0.8)
    check("⚠️ 十七改：**按下即生效** —— 那一项的回调当场触发，且整套菜单一起关掉（用户口径）",
          _fired19 == ["设置"] and not _m19h.isVisible() and not _sub19h.isVisible(),
          f"fired={_fired19} main={_m19h.isVisible()} sub={_sub19h.isVisible()}")
finally:
    petmod.QCursor = _real_cursor19

# ---- 19h-2. 转发路径的边界：音量条放行、切换行保持、禁用项什么都不做、还权后自限 ----
_m19h.pop_up(QRect(400, 400, _m19h.sizeHint().width(), _m19h.sizeHint().height()), "right")
_pump(0.7)
_m19h._show_submenu()
_m19h._poll.stop()
_pump(0.7)
check("⚠️ 十七改：一级的**音量条**那一行点下去要**放行**（返回 False）—— 它是真子控件"
      "（滑块要能拖、喇叭要能点），接管了就得自己回灌 move/release，反而把「拖音量」弄坏",
      _m19h.eventFilter(_m19h, _press19(
          _m19h.mapToGlobal(_m19h.row_rect(0).center()))) is False)
check("⚠️ 十七改：放行之后二级仍在（这一档我们没动过）",
      _m19h.isVisible() and _sub19h.isVisible(), f"vis={_sub19h.isVisible()}")
check("⚠️ 十七改：点「切换」那一行 → 吃掉这一下但**不关**（二级本来就该开着）",
      _m19h.eventFilter(_m19h, _press19(
          _m19h.mapToGlobal(_m19h.row_rect(2).center()))) is True
      and _m19h.isVisible() and _sub19h.isVisible() and not _m19h._closing,
      f"vis={_m19h.isVisible()} sub={_sub19h.isVisible()} closing={_m19h._closing}")
_m19h._poll.stop()
check("⚠️ 十七改：点在**二级**面板上的按下仍然放行（返回 False），且**不**置 `_swallow_release`",
      _m19h.eventFilter(_m19h, _press19(_sub19h._panel_global_rect().center())) is False
      and _m19h._swallow_release is False,
      f"swallow={_m19h._swallow_release}")
_m19h._rows[4]["enabled"] = False              # 假装「节能模式」被禁用（艾莲那种情形）
check("⚠️ 十七改：点**禁用的项** → 吃掉这一下、不触发、也不关（与二级没开时逐字一致）",
      _m19h.eventFilter(_m19h, _press19(
          _m19h.mapToGlobal(_m19h.row_rect(4).center()))) is True
      and _m19h.isVisible() and not _m19h._closing,
      f"vis={_m19h.isVisible()} closing={_m19h._closing}")
_m19h._rows[4]["enabled"] = True
# 二级一收 → 还权给一级 → hover 表自己停（自限）
_m19h._hide_submenu(animated=False)
_pump(0.5)
check("⚠️ 十七改：二级收掉后 `_sub_owns_mouse()` 归假、hover 表**自己停**"
      "（自限：不与真的 `mouseMoveEvent` 抢）",
      _m19h._sub_owns_mouse() is False and not _m19h._hover_poll.isActive(),
      f"own={_m19h._sub_owns_mouse()} active={_m19h._hover_poll.isActive()}")
_m19h._hover_tick()
check("⚠️ 十七改：还权之后再叫 `_hover_tick()` 是空操作（表仍是停的、不会复活）",
      not _m19h._hover_poll.isActive())
_m19h.close_animated()
_pump(0.8)
check("19h 收尾：整套关掉、`_closing` 复位、hover 表停了、抬起标记也清了",
      not _m19h.isVisible() and not _m19h._closing and not _m19h._hover_poll.isActive()
      and not _sub19h.isVisible() and _m19h._swallow_release is False)
pet19._menu_open = False

pet19.close()
qapp.processEvents()

print("== 20. patpat 模式：左键抚摸（抬起 50 → 下压 150 → 抬起 100ms）+ 贴图形变（站姿 35/12、节能态 20/8）+ 连点截断重播 + **两套独立音效**（2026-09-20 十八 / 十九 / 二十 / 二十一 / 二十二改）==")
from app import config as cfgmod20  # noqa: E402
from app import patpat as ppmod  # noqa: E402

# ---- 20a. 常量与纯几何（不依赖窗口，先把「口径」钉死）----
check("常量：三帧 50 / 150 / 100（合 300ms）、帧序 (0,1,0)、点击-拖动分界 6px、节能态落点比例 3/8",
      (ppmod.PATPAT_F1_MS, ppmod.PATPAT_F2_MS, ppmod.PATPAT_F3_MS, ppmod.PATPAT_TOTAL_MS,
       ppmod.PATPAT_SEQ, ppmod.PATPAT_CLICK_SLOP,
       ppmod.PATPAT_PS_BOTTOM_RATIO) == (50, 150, 100, 300, (0, 1, 0), 6, 0.375),
      str((ppmod.PATPAT_F1_MS, ppmod.PATPAT_F2_MS, ppmod.PATPAT_F3_MS, ppmod.PATPAT_TOTAL_MS,
           ppmod.PATPAT_SEQ, ppmod.PATPAT_CLICK_SLOP, ppmod.PATPAT_PS_BOTTOM_RATIO)))
check("常量：一轮总时长 = 三帧之和（不是另写一个数 —— 改帧时长不会跟总数对不上）",
      ppmod.PATPAT_TOTAL_MS == ppmod.PATPAT_F1_MS + ppmod.PATPAT_F2_MS + ppmod.PATPAT_F3_MS)
# ⚠️ 下面两个数字来自**素材实测**（ffmpeg 解码成 f32le 后量包络，-40dBFS 判起振）：
# pat_0 起振 77.5ms / 有效到 194.1ms；pat_1 起振 71.1ms / 有效到 151.6ms。
# **换素材必须重量、并回头改这里（以及帧时长常量）** —— 二十改就是因为新素材起振从 150/177ms 提前到 71/78ms，
# 才把帧1 从 130ms 缩到 50ms。
_ONSET20 = (77.5, 71.1)
_END20 = (194.1, 151.6)
check("「下压」那一帧（50 → 200ms）把两段音频的**起振点（77.5 / 71.1ms）**都盖在里面，"
      "且帧1 短于最短的那段前导静音（否则声音会在「抬起」帧就响）",
      ppmod.PATPAT_F1_MS < min(_ONSET20)
      and all(ppmod.PATPAT_F1_MS < o < ppmod.PATPAT_F1_MS + ppmod.PATPAT_F2_MS for o in _ONSET20),
      str((ppmod.PATPAT_F1_MS, _ONSET20)))
check("「下压」那一帧还把两段的**有效声音结尾（194.1 / 151.6ms）**也盖在里面 ——"
      "否则会出现「手已经抬起来了、声音还在响」",
      all(e < ppmod.PATPAT_F1_MS + ppmod.PATPAT_F2_MS for e in _END20),
      str([(e, ppmod.PATPAT_F1_MS + ppmod.PATPAT_F2_MS) for e in _END20]))
check("形变常量（站姿，二十改**加大**）：高 −35px、宽**每侧** +12px（合计 24）、进出各 80ms",
      (ppmod.PATPAT_SQUASH_H, ppmod.PATPAT_SQUASH_PER_SIDE, ppmod.PATPAT_SQUASH_W,
       ppmod.PATPAT_SQUASH_MS) == (35, 12, 24, 80),
      str((ppmod.PATPAT_SQUASH_H, ppmod.PATPAT_SQUASH_PER_SIDE, ppmod.PATPAT_SQUASH_W,
           ppmod.PATPAT_SQUASH_MS)))
check("★形变常量（**节能态单独一套**，二十改）：高 −20px、宽**每侧** +8px（合计 16）——"
      "节能态那张扁平贴图只有 100px 高，照站姿的 35px 压会矮掉 35%（站姿那套才 14%），所以单独定量",
      (ppmod.PATPAT_SQUASH_H_PS, ppmod.PATPAT_SQUASH_PER_SIDE_PS, ppmod.PATPAT_SQUASH_W_PS)
      == (20, 8, 16),
      str((ppmod.PATPAT_SQUASH_H_PS, ppmod.PATPAT_SQUASH_PER_SIDE_PS, ppmod.PATPAT_SQUASH_W_PS)))
check("形变纯几何（站姿）：0.0 = 原形（150×250）、1.0 = 压到底（高 −35 宽 +24 → 174×215）、"
      "0.5 = 中间态（162×232）",
      ppmod.patpat_squash_size(150, 250, 0.0) == (150, 250)
      and ppmod.patpat_squash_size(150, 250, 1.0) == (174, 215)
      and ppmod.patpat_squash_size(150, 250, 0.5) == (162, 232),
      str([ppmod.patpat_squash_size(150, 250, p) for p in (0.0, 0.5, 1.0)]))
check("★形变纯几何（节能态）：同一张扁平贴图 150×100 → 166×80（高 −20 宽 +16）——"
      "**两套量由 `power_save` 参数选**，不是照着尺寸猜的（不传就该是站姿那套 174×65）",
      ppmod.patpat_squash_size(150, 100, 1.0, power_save=True) == (166, 80)
      and ppmod.patpat_squash_size(150, 100, 1.0, power_save=False) == (174, 65),
      str([ppmod.patpat_squash_size(150, 100, 1.0, power_save=ps) for ps in (True, False)]))
check("形变下沉量（站姿，= 那只手要跟着往下挪多少）：0 → 0px、0.5 → 18px、1.0 → 35px；"
      "**基准边是底边**所以顶边下沉量 = 高度被压掉的量",
      (ppmod.patpat_squash_drop(0.0), ppmod.patpat_squash_drop(0.5),
       ppmod.patpat_squash_drop(1.0)) == (0, 18, 35),
      str([ppmod.patpat_squash_drop(p) for p in (0.0, 0.5, 1.0)]))
check("★形变下沉量（节能态）：压到底 → 20px、半程 → 10px（与它那套 20px 高度形变自洽）",
      ppmod.patpat_squash_drop(1.0, power_save=True) == 20
      and ppmod.patpat_squash_drop(0.5, power_save=True) == 10
      and ppmod.patpat_squash_drop(1.0, power_save=False) == 35,
      str([ppmod.patpat_squash_drop(1.0, power_save=ps) for ps in (True, False)]))
check("形变进度会被夹到 [0,1]（动画端点给 1.0000001 之类也不会算出个超标的尺寸）",
      ppmod.patpat_squash_size(150, 250, 1.7) == ppmod.patpat_squash_size(150, 250, 1.0)
      and ppmod.patpat_squash_size(150, 250, -0.3) == ppmod.patpat_squash_size(150, 250, 0.0))
check("形变也不会把尺寸算成 0（极矮贴图压到底 → 高度兜底 1）",
      ppmod.patpat_squash_size(4, 8, 1.0) == (28, 1), str(ppmod.patpat_squash_size(4, 8, 1.0)))
check("取整是「.5 一律向上」（112.5→113）—— 不是内建 round 的银行家舍入（那会得到 112）",
      ppmod._round(112.5) == 113 and round(112.5) == 112, str(ppmod._round(112.5)))
check("叠加图显示尺寸与角色**同一个缩放系数**：爱丽丝 ×0.5 → 原图 300×225 的手显示 150×113",
      ppmod.patpat_size(300, 225, 0.5) == (150, 113), str(ppmod.patpat_size(300, 225, 0.5)))
check("艾莲 ×(250/256) → 293×220（同一套口径换角色也成立，不是写死爱丽丝那一档）",
      ppmod.patpat_size(300, 225, 250 / 256) == (293, 220),
      str(ppmod.patpat_size(300, 225, 250 / 256)))
check("退化尺寸不会缩成 0（最小 1×1）",
      ppmod.patpat_size(1, 1, 0.1) == (1, 1), str(ppmod.patpat_size(1, 1, 0.1)))

_frames20 = ppmod.patpat_frames(ALICE)
check("找得到「抬起」「下压」两张图，且**抬起在前** —— 按文件名标记找、不靠 sorted 排序"
      "（「下压」的「下」U+4E0B 排在「抬」U+62AC 之前，靠排序会反）",
      _frames20 is not None and "抬起" in _frames20[0].stem and "下压" in _frames20[1].stem,
      str([p.name for p in (_frames20 or ())]))
check("另一个角色目录（艾莲）拿到的是**同一套**手（pet/patpat 与角色无关，所有角色共用）",
      [p.name for p in (ppmod.patpat_frames(ELLEN) or ())]
      == [p.name for p in (_frames20 or ())])
check("角色目录旁边没有 patpat/ 时返回 None（缺图 = 没这回事，不抛异常）",
      ppmod.patpat_frames(BASE / "voices") is None)
check("摸摸音效：voices/patpat 下两段 mp3（播放时随机挑其中一段）",
      [p.name for p in ppmod.patpat_sounds(BASE / "voices" / "patpat")]
      == ["pat_0.mp3", "pat_1.mp3"])

check("普通态：叠加图**左上角**与贴图左上角重合（画布口径 —— 两张同尺寸，显示时不会跳）",
      ppmod.patpat_pos(QRect(100, 200, 150, 250), 150, 113, power_save=False) == (100, 200),
      str(ppmod.patpat_pos(QRect(100, 200, 150, 250), 150, 113, power_save=False)))
_pspos20 = ppmod.patpat_pos(QRect(100, 200, 150, 100), 150, 113, power_save=True)
check("节能态：叠加图**左下角**落在贴图「自下往上 3/8」处"
      "（200+100−round(100×3/8)=262 → 顶边 262−113=149）",
      _pspos20 == (100, 149), str(_pspos20))
check("节能态那只手会**高出贴图窗口顶边**（顶边 149 < 贴图顶边 200）——"
      "所以它必须是独立顶层窗，做子控件会被父窗直接裁掉",
      _pspos20[1] < 200, str(_pspos20))

# ---- 20b. 窗口侧：缩放系数取自角色贴图、开关与回调 ----
pet20 = new_pet(ALICE, at=(300, 300))
pet20.set_patpat_sound_dir(BASE / "voices" / "patpat")
# ★二十二改：第二套音效（非模式单击）—— 与上面那套**各自独立**，两个目录分别注入。
pet20.set_normal_pet_sound_dir(BASE / "voices" / "normal_pet")
check("缩放系数 = 角色贴图自己那一个（爱丽丝 150÷300 = 0.5）",
      abs(pet20._patpat_scale() - 0.5) < 1e-6, str(pet20._patpat_scale()))
check("叠加图显示尺寸 = 150×113（与角色同系数，而不是原图 300×225）",
      pet20._patpat_size() == (150, 113), str(pet20._patpat_size()))
check("两张手图都加载到了（只算到一张就当成没素材 —— 那样「抬起 → 下压」无从谈起）",
      len(pet20._patpat_pixmaps()) == 2, str(len(pet20._patpat_pixmaps())))

_calls20 = []
pet20.set_on_patpat(lambda on: _calls20.append(bool(on)))
check("初始是关的、还没放过手（帧序号 -1）",
      pet20.is_patpat() is False and pet20.patpat_overlay_index() == -1)
check("打开：返回 True（真的发生了切换）", pet20.set_patpat(True) is True)
check("再打开一次：返回 False、**不回调**（没有真切换 → 提示不会重复弹）",
      pet20.set_patpat(True) is False and _calls20 == [True], str(_calls20))
check("toggle 反转（右键菜单那一行点的是它），回调收到 False",
      pet20.toggle_patpat() is True and pet20.is_patpat() is False
      and _calls20 == [True, False], str(_calls20))

# 素材门禁：**不做** —— 缺图也允许打开（用户口径「可直接打开」，与节能模式那一行刻意不同）
# ★二十一改：缺图**不再等于「点下去没反应」** —— 贴图照常形变，只是不叠手、不出声。
pet20._patpat_scanned = True
pet20._patpat_frames = ()
pet20.set_patpat(True)
check("没有手图时开关**照样能打开**（刻意不做素材门禁）", pet20.is_patpat() is True)
_miss20 = pet20._sprite_rect()
_miss_ret20 = pet20._patpat_play()          # ⚠️ 只调一次：调第二次会把这一轮截断重播
check("★缺图 + 模式开着点一下：`_patpat_play()` 返回 False（**没叠手**）、那只手不在屏幕上，"
      "但这一轮**照样起了表**（走到第 1 步 / 两个定时器都在跑）",
      _miss_ret20 is False and pet20.is_patpat_playing() is False
      and pet20.patpat_step() == 1
      and pet20._patpat_swap_timer.isActive() and pet20._patpat_end_timer.isActive(),
      f"ret={_miss_ret20} shown={pet20.is_patpat_playing()} step={pet20.patpat_step()}")
check("★★（二十二改）缺手图这一档**两套音效都不播**：`_patpat_audio.last_played` 与 "
      "`_normal_pet_audio.last_played` 都还是 None（模式**开着**但缺手图 ⇒ **不拿 normal_pet 顶班**）",
      pet20._patpat_audio.last_played is None
      and pet20._normal_pet_audio.last_played is None,
      f"pp={pet20._patpat_audio.last_played} np={pet20._normal_pet_audio.last_played}")
_pump_until(lambda: pet20.patpat_squash_progress() >= 1.0)
check("★缺图也能压出形变：150×250 → 174×215（与有手时**一模一样**）",
      (pet20._sprite_rect().width(), pet20._sprite_rect().height()) == (174, 215),
      str(pet20._sprite_rect()))
_pump_until(lambda: pet20.patpat_step() == 0)
check("★收尾后逐像素还原（缺图那一档也不例外）",
      pet20._sprite_rect() == _miss20 and pet20.patpat_squash_progress() == 0.0,
      f"{pet20._sprite_rect()} vs {_miss20}")
pet20._patpat_scanned = False          # 还原：后面还要用那两张真图
pet20._patpat_frames = ()
pet20.set_patpat(False)

# ---- 20c. 左键「点一下」贴图：抬起 0.3s → 下压 0.3s → 收起 + 随机音效 ----
# ⚠️ 这一步**不能**钉死 `patpat_step() == 1`：这一次点击是 `_normal_pet_audio` 的**首次播放**，
#    要现开音频设备（实测几十~上百 ms，机器一忙就超 `PATPAT_F1_MS`=50ms），于是断言跑的时候
#    定时器已经推进到第 2 步 —— 与「形变照跑」这条口径无关的**时序赛跑**（本文件实测：
#    单跑绿、全量跑红）。⇒ 只钉「走进了 patpat 流水线、而且手上没出现」。
#    ★「必须经过第 1 步（抬起）」这条由上面 2819 那条钉着（那一次缺手图 ⇒ **不播声** ⇒
#      没有设备初始化 ⇒ 确定性的 `step == 1`），覆盖没丢。
QTest.mouseClick(pet20, Qt.LeftButton)         # 真·按下-释放，中间没有位移
qapp.processEvents()
check("★（二十一改）模式**关着**时点贴图：那只手不出现，但**形变照跑**"
      "（不再是二十改那版的「什么也不发生」—— 那道模式守卫已按用户口径删除）",
      pet20.is_patpat_playing() is False and pet20.patpat_overlay_index() == -1
      and pet20.patpat_step() in (1, 2) and pet20._patpat_swap_timer.isActive(),
      f"shown={pet20.is_patpat_playing()} step={pet20.patpat_step()}")
# ★★等「收尾**跑完**」再断言：`patpat_step() == 0` 只是收尾**起步**，形变还原还要
#    跑完 SQUASH_MS=80ms 的动画（机器一忙就跑得慢）⇒ 只等 step 会**偶发假红**（实测：
#    同一条断言 4 次单跑里红 1 次）。`_pump_until` 超时只返回 False、值断言照旧求值，
#    所以「形变不还原」的真 bug 仍会被抓住，强度不变。
_pump_until(lambda: pet20.patpat_step() == 0 and pet20.patpat_squash_progress() == 0.0)
check("…而且它自己会收干净（形变还原 / 基准清掉 / 两个定时器都停）",
      pet20.patpat_squash_progress() == 0.0 and pet20._patpat_sq_base is None
      and not pet20._patpat_swap_timer.isActive() and not pet20._patpat_end_timer.isActive())
check("★★（二十二改）模式**关着**点贴图 → 响的是 **normal_pet 那一套**（`bibu.mp3`），"
      "而 patpat 那一套**一次没响**（`last_played` 仍 None）—— 「只播一套」",
      pet20._normal_pet_audio.last_played is not None
      and pet20._normal_pet_audio.last_played.name == "bibu.mp3"
      and pet20._patpat_audio.last_played is None,
      f"np={pet20._normal_pet_audio.last_played} pp={pet20._patpat_audio.last_played}")

pet20.set_patpat(True)
_sprite20 = pet20._sprite_rect()
QTest.mouseClick(pet20, Qt.LeftButton)
qapp.processEvents()
check("模式开着时点一下 → 立刻显示「抬起」（第 0 帧）、走到第 1 步",
      pet20.is_patpat_playing() is True and pet20.patpat_overlay_index() == 0
      and pet20.patpat_step() == 1,
      f"shown={pet20.is_patpat_playing()} idx={pet20.patpat_overlay_index()} "
      f"step={pet20.patpat_step()}")
_ov20 = pet20._patpat_ov
check("那只手是**独立顶层窗** + 鼠标穿透 + 置顶（三个缺一不可：节能态会高出贴图顶边 → 子控件被裁；"
      "整块盖在贴图上 → 不穿透就把「摸她」这一下吃了）",
      _ov20.isWindow()
      and bool(_ov20.windowFlags() & Qt.WindowTransparentForInput)
      and bool(_ov20.windowFlags() & Qt.WindowStaysOnTopHint),
      str(_ov20.windowFlags()))
check("显示尺寸 = 150×113（与角色同系数缩放后的）",
      (_ov20.width(), _ov20.height()) == (150, 113), f"{_ov20.width()}×{_ov20.height()}")
check("普通态：左上角与贴图左上角重合（屏幕坐标）",
      _ov20.pos() == _sprite20.topLeft(), f"{_ov20.pos()} vs {_sprite20.topLeft()}")
check("音效随机挑了其中一段播出去（原声：音量条与静音模式都不影响它）",
      pet20._patpat_audio.last_played is not None
      and pet20._patpat_audio.last_played.name in ("pat_0.mp3", "pat_1.mp3"),
      str(pet20._patpat_audio.last_played))
check("刚点下时**贴图还没变形**（形变只在「下压」那一帧才开始，不在点下那一刻）",
      pet20.patpat_squash_progress() == 0.0 and pet20._sprite_rect() == _sprite20,
      f"sq={pet20.patpat_squash_progress()} sprite={pet20._sprite_rect()}")

# ---- 20c-2. 到「下压」帧：**贴图自己也压扁**（十九改；二十改加大到 35/每侧12）----
_pump_until(lambda: pet20.patpat_squash_progress() >= 1.0)
check("50ms 到点 → 换成「下压」（第 1 帧）、走到第 2 步，那只手还在",
      pet20.is_patpat_playing() is True and pet20.patpat_overlay_index() == 1
      and pet20.patpat_step() == 2,
      f"shown={pet20.is_patpat_playing()} idx={pet20.patpat_overlay_index()} "
      f"step={pet20.patpat_step()}")
_sq20 = pet20._sprite_rect()
check("形变**已经到位**（80ms 过渡跑完）→ 进度 = 1.0",
      abs(pet20.patpat_squash_progress() - 1.0) < 1e-6,
      str(pet20.patpat_squash_progress()))
check("形变后贴图 = 174×215（原 150×250：高 −35、宽两侧各 +12 ⇒ 宽 +24）",
      (_sq20.width(), _sq20.height()) == (174, 215), f"{_sq20.width()}×{_sq20.height()}")
check("★**底边不动**（「下压 35px」不是往上缩）：形变后底边 == 形变前底边",
      _sq20.y() + _sq20.height() == _sprite20.y() + _sprite20.height(),
      f"{_sq20.y() + _sq20.height()} vs {_sprite20.y() + _sprite20.height()}")
check("顶边**下沉 35px**、左右各外扩 12px（水平中心不动 —— 是「向两侧」拉伸而不是只往一边长）",
      (_sq20.y() - _sprite20.y(), _sprite20.x() - _sq20.x()) == (35, 12)
      and (_sq20.x() + _sq20.width() // 2) == (_sprite20.x() + _sprite20.width() // 2),
      f"top+{_sq20.y() - _sprite20.y()} left-{_sprite20.x() - _sq20.x()}")
check("★那只手**不参与形变**（尺寸仍 150×113），**横向不动**、只跟着下沉 35px",
      (_ov20.width(), _ov20.height()) == (150, 113)
      and _ov20.x() == _sprite20.x()
      and _ov20.y() == _sprite20.y() + 35,
      f"ov={_ov20.pos()} {_ov20.width()}×{_ov20.height()} base_top={_sprite20.y()}")

# ---- 20c-3. 第 3 帧 + 收手：形变必须**精确还原** ----
_ok20 = _pump_until(lambda: pet20.patpat_step() == 3)
check("再过 150ms（第 3 帧）→ 回到「抬起」（帧序号 0）—— 第 3 帧还是第 1 张图、走到第 3 步",
      _ok20 and pet20.patpat_overlay_index() == 0 and pet20.is_patpat_playing() is True,
      f"reached={_ok20} idx={pet20.patpat_overlay_index()} "
      f"shown={pet20.is_patpat_playing()} step={pet20.patpat_step()}")
_pump_until(lambda: not pet20.is_patpat_playing())
check("300ms 到点 → 收起那只手", pet20.is_patpat_playing() is False,
      f"shown={pet20.is_patpat_playing()}")
check("★贴图几何**逐像素还原**（不是「大概回去」）—— 与点击前完全相同",
      pet20._sprite_rect() == _sprite20, f"{pet20._sprite_rect()} vs {_sprite20}")
check("形变进度归零、基准几何与动画句柄都清掉了（不留残迹）",
      pet20.patpat_squash_progress() == 0.0 and pet20._patpat_sq_base is None
      and pet20._patpat_sq_anim is None,
      f"sq={pet20.patpat_squash_progress()} base={pet20._patpat_sq_base} "
      f"anim={pet20._patpat_sq_anim}")

# ---- 20d. 拖动**不算**抚摸（否则每次挪完位置松手都会摸一下）----
def _petev20(kind, global_pt, button=Qt.LeftButton, buttons=Qt.LeftButton):
    """造一个桌宠的鼠标事件：`mouse*Event` 只看 `globalPosition()` / `button()` / `buttons()`。"""
    return QMouseEvent(kind, QPointF(0, 0), QPointF(global_pt.x(), global_pt.y()),
                       button, buttons, Qt.NoModifier)


pet20.set_patpat(True)
_c20 = pet20._sprite_rect().center()
pet20.mousePressEvent(_petev20(QEvent.Type.MouseButtonPress, _c20))
check("按下先记起点（`_press_pos`），此刻还没判成拖动", pet20._press_moved is False)
pet20.mouseMoveEvent(_petev20(QEvent.Type.MouseMove, _c20 + QPoint(40, 0),
                              Qt.NoButton, Qt.LeftButton))
check("位移 40px > 分界 6px → 记成「拖动」", pet20._press_moved is True)
pet20.mouseReleaseEvent(_petev20(QEvent.Type.MouseButtonRelease, _c20 + QPoint(40, 0),
                                 Qt.LeftButton, Qt.NoButton))
qapp.processEvents()
check("拖动松手**不**摸（拖动过的不算点击）", pet20.is_patpat_playing() is False)
check("这一路确实是拖动：窗口跟着挪了 40px",
      pet20._sprite_rect() == _sprite20.translated(40, 0),
      f"{pet20._sprite_rect()} vs {_sprite20.translated(40, 0)}")

# ---- 20d-2. 桌宠固定（2026-09-22）：锁住时**拖不动**，但「点击」判据与抚摸照旧 ----
# 用户口径：① 通用设置「桌宠调整」里一个滑块、**默认打开固定**；② 右键菜单里也能开关。
#   ★只锁「拖动」—— 单击抚摸 / 思考气泡不受影响。
check("cfg 默认 `lock_pet=True`（用户口径「默认打开固定，使桌宠不会被拖动」）",
      cfgmod20.DEFAULT_CONFIG["general"]["lock_pet"] is True,
      str(cfgmod20.DEFAULT_CONFIG["general"].get("lock_pet")))
check("★`lock_pet` **不是**纯运行时状态（它要落盘：用户口径「记住选择」）—— 别混进那两张名单",
      "lock_pet" not in cfgmod20._RUNTIME_ONLY_GENERAL,
      str(cfgmod20._RUNTIME_ONLY_GENERAL))

_at20 = pet20._sprite_rect()
pet20.set_locked(True)
check("「桌宠固定」开着时 `is_locked()` 为真", pet20.is_locked() is True)
_c20b = _at20.center()
pet20.mousePressEvent(_petev20(QEvent.Type.MouseButtonPress, _c20b))
pet20.mouseMoveEvent(_petev20(QEvent.Type.MouseMove, _c20b + QPoint(40, 0),
                              Qt.NoButton, Qt.LeftButton))
check("★★固定时按住拖 40px → 窗口**一动不动**",
      pet20._sprite_rect() == _at20,
      f"{pet20._sprite_rect()} vs {_at20}")
check("★★固定时**仍照常判定**「这一次是拖动」（位移判据没被 early-return 掉）"
      "—— 否则松手会被当成「点击」，在锁定的贴图上拖一下就会莫名其妙摸一下头",
      pet20._press_moved is True)
pet20.mouseReleaseEvent(_petev20(QEvent.Type.MouseButtonRelease, _c20b + QPoint(40, 0),
                                 Qt.LeftButton, Qt.NoButton))
qapp.processEvents()
check("★固定时「按住拖一下再松手」→ **不**抚摸", pet20.is_patpat_playing() is False)

# 固定只掐「挪」：原地按一下松手**仍然算点击**（抚摸照旧）
pet20.mousePressEvent(_petev20(QEvent.Type.MouseButtonPress, _c20b))
check("★固定时按下仍记了起点（`_press_pos` 有值）—— 锁没有把点击判据一起掐掉",
      pet20._press_pos is not None)
pet20.mouseReleaseEvent(_petev20(QEvent.Type.MouseButtonRelease, _c20b,
                                 Qt.LeftButton, Qt.NoButton))
qapp.processEvents()
check("★固定**不影响点击**：原地按一下松手 → 照常抚摸（手叠上了）",
      pet20.is_patpat_playing() is True)
pet20._patpat_stop()
qapp.processEvents()

pet20.set_locked(False)
check("关掉「桌宠固定」后 `is_locked()` 为假", pet20.is_locked() is False)
_c20c = _at20.center()
pet20.mousePressEvent(_petev20(QEvent.Type.MouseButtonPress, _c20c))
pet20.mouseMoveEvent(_petev20(QEvent.Type.MouseMove, _c20c + QPoint(25, 0),
                              Qt.NoButton, Qt.LeftButton))
check("★关掉固定后又能拖了（窗口跟着挪 25px）",
      pet20._sprite_rect() == _at20.translated(25, 0),
      f"{pet20._sprite_rect()} vs {_at20.translated(25, 0)}")
pet20.mouseReleaseEvent(_petev20(QEvent.Type.MouseButtonRelease, _c20c + QPoint(25, 0),
                                 Qt.LeftButton, Qt.NoButton))
qapp.processEvents()

check("★`set_locked()` 只在**真的发生变化**时返回 True（两个入口都靠它决定要不要弹提示）",
      pet20.set_locked(False) is False and pet20.set_locked(True) is True)
pet20.set_locked(False)

# ★结构层：被锁的**只有 `mouseMoveEvent` 里那句 `self.move(...)`** —— 用 AST 查「它被
#   `_locked` 守卫包着」，**不要**用字符串（本方法的注释里就写着 `_locked`，字符串会被注释骗绿）。
#   （这里自己 parse：`_method_node()` 定义在文件更靠后的位置，此刻还用不了。）
_fn_mm20 = None
for _cls20 in ast.parse(_SRC19).body:
    if isinstance(_cls20, ast.ClassDef) and _cls20.name == "PetWindow":
        for _m20 in _cls20.body:
            if isinstance(_m20, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                    and _m20.name == "mouseMoveEvent":
                _fn_mm20 = _m20
        break
check("结构：找得到 `PetWindow.mouseMoveEvent`（找不到就说明类/方法改名了，下面那条会失真）",
      _fn_mm20 is not None)
_guard20 = False
_guarded_move20 = False
for _n20 in (ast.walk(_fn_mm20) if _fn_mm20 is not None else ()):
    if isinstance(_n20, ast.If) and any(
            isinstance(_x20, ast.Attribute) and _x20.attr == "_locked"
            for _x20 in ast.walk(_n20.test)):
        _guard20 = True
        if any(isinstance(_c20x, ast.Call) and isinstance(_c20x.func, ast.Attribute)
               and _c20x.func.attr == "move" for _c20x in ast.walk(_n20)):
            _guarded_move20 = True
check("★★结构：`PetWindow.mouseMoveEvent` 里有一个 `if not self._locked:` 守卫**包着 `self.move(...)`**"
      "（AST 查，不用字符串 —— 注释里也有 `_locked`）",
      _guard20 and _guarded_move20, f"guard={_guard20} guarded_move={_guarded_move20}")
check("★结构：`mouseReleaseEvent` 仍然**无条件**算点击（锁不许把 `clicked` 判据一起掐掉）",
      "clicked = self._press_pos is not None and not self._press_moved"
      in inspect.getsource(petmod.PetWindow.mouseReleaseEvent))

# ---- 20e. 连点 = **截断重播**（二十改明确成硬承诺）----
# 用户口径：快速多次点击时，要**截断前一次的动画及音频**，并从**头**开始新的一轮。
pet20.move(300, 300)
qapp.processEvents()
pet20.set_patpat(True)
_rest20 = pet20._sprite_rect()
# 把音效的 stop/play 记下来 —— 「先掐掉上一段、再从头播」这件事只有**顺序**能证明
# （`_calls_name` 那种「有没有调」的断言看不出顺序，先 play 再 stop 也能过）。
_audio_calls20 = []
_orig_stop20, _orig_play20 = pet20._patpat_audio.stop, pet20._patpat_audio.play
pet20._patpat_audio.stop = lambda: (_audio_calls20.append("stop"), _orig_stop20())[1]
pet20._patpat_audio.play = lambda: (_audio_calls20.append("play"), _orig_play20())[1]
try:
    QTest.mouseClick(pet20, Qt.LeftButton)
    check("第一下点下去：音效**先 stop 再 play**（不叠上一段，也不接着上一段的位置往下播）",
          _audio_calls20 == ["stop", "play"], str(_audio_calls20))
    _pump_until(lambda: pet20.patpat_squash_progress() >= 1.0)
    check("第一下已经走到「下压」、贴图正被压着（174×215）",
          pet20.patpat_overlay_index() == 1 and pet20.patpat_squash_progress() == 1.0
          and (pet20._sprite_rect().width(), pet20._sprite_rect().height()) == (174, 215),
          f"idx={pet20.patpat_overlay_index()} sq={pet20.patpat_squash_progress()} "
          f"{pet20._sprite_rect()}")
    _end_left20 = pet20._patpat_end_timer.remainingTime()
    _audio_calls20.clear()
    QTest.mouseClick(pet20, Qt.LeftButton)
    qapp.processEvents()
    check("再点一下 → **截断前一轮、从头来**：回到「抬起」第 0 帧 / 第 1 步，两个定时器都在跑",
          pet20.is_patpat_playing() is True and pet20.patpat_overlay_index() == 0
          and pet20.patpat_step() == 1
          and pet20._patpat_swap_timer.isActive() and pet20._patpat_end_timer.isActive(),
          f"idx={pet20.patpat_overlay_index()} step={pet20.patpat_step()} "
          f"swap={pet20._patpat_swap_timer.isActive()} end={pet20._patpat_end_timer.isActive()}")
    check("★收手定时器是**重新起表**的（剩余时间被推回满格 300ms，而不是接着上一轮往下数）",
          pet20._patpat_end_timer.remainingTime() >= _end_left20 + 80
          and pet20._patpat_end_timer.remainingTime() <= petmod.PATPAT_TOTAL_MS + 20,
          f"{pet20._patpat_end_timer.remainingTime()} vs 上一轮剩余 {_end_left20}")
    check("★**音频也被截断**：第二下同样是「先 stop 掉上一段、再 play 新的一段」",
          _audio_calls20 == ["stop", "play"], str(_audio_calls20))
    check("★连点要把形变**当场还原**再重播（否则第二轮是从一个被压扁的贴图上开始的）",
          pet20.patpat_squash_progress() == 0.0 and pet20._sprite_rect() == _rest20,
          f"sq={pet20.patpat_squash_progress()} sprite={pet20._sprite_rect()} vs {_rest20}")
    _pump_until(lambda: not pet20.is_patpat_playing())
    check("第二轮也按时收干净（没留下多余的手 / 还在跑的定时器 / 没还原的形变）",
          pet20.is_patpat_playing() is False
          and not pet20._patpat_swap_timer.isActive() and not pet20._patpat_end_timer.isActive()
          and pet20.patpat_squash_progress() == 0.0 and pet20._sprite_rect() == _rest20)
    # 第三下：上一轮**已经自然收手之后**再点，同样必须从头来（不能受上一轮残留影响）
    _audio_calls20.clear()
    QTest.mouseClick(pet20, Qt.LeftButton)
    qapp.processEvents()
    check("★上一轮**已经收手**后再点：照样从头来（帧 0 / 第 1 步 / 音效先 stop 再 play）",
          pet20.patpat_overlay_index() == 0 and pet20.patpat_step() == 1
          and _audio_calls20 == ["stop", "play"],
          f"idx={pet20.patpat_overlay_index()} step={pet20.patpat_step()} {_audio_calls20}")
    _pump_until(lambda: not pet20.is_patpat_playing())
finally:
    pet20._patpat_audio.stop = _orig_stop20
    pet20._patpat_audio.play = _orig_play20
check("还原探针：音效对象上不再挂着测试用的替身（后面的用例别被它带偏）",
      pet20._patpat_audio.stop == _orig_stop20 and pet20._patpat_audio.play == _orig_play20)

# ---- 20f. 与其它模式**互不冲突**（用户口径「可直接打开」）----
pet20.set_volume(0.2, muted=True)              # 静音模式开着（patpat 此刻也是开着的）
check("静音模式不影响 patpat：模式仍开着（既不挡开、也不看静音态）",
      pet20._muted is True and pet20.is_patpat() is True)
QTest.mouseClick(pet20, Qt.LeftButton)
qapp.processEvents()
check("静音模式下点贴图照样摸得动，音效也照播（**原声**，不跟音量滑块、也不因静音而不出声）",
      pet20.is_patpat_playing() is True and pet20.patpat_overlay_index() == 0)
_pump_until(lambda: not pet20.is_patpat_playing())

pet20.set_power_save(True, animate=False)      # 节能态（贴图被压扁）
qapp.processEvents()
check("节能态下 patpat 照样能开（两个模式共用同一只贴图）",
      pet20._power_save is True and pet20.is_patpat() is True)
_r20 = pet20._sprite_rect()
QTest.mouseClick(pet20, Qt.LeftButton)
qapp.processEvents()
_exp20 = ppmod.patpat_pos(_r20, 150, 113, power_save=True)
check("节能态落点：叠加图**左下角** = 贴图「自下往上 3/8」处（横向仍与贴图左边对齐）",
      pet20._patpat_ov.pos() == QPoint(_exp20[0], _exp20[1]),
      f"{pet20._patpat_ov.pos()} vs {_exp20}")
check("节能态那只手确实**高出贴图顶边**（y 比贴图顶边更小）—— 顶层窗的意义就在这儿",
      pet20._patpat_ov.y() < _r20.y(),
      f"ov_y={pet20._patpat_ov.y()} sprite_y={_r20.y()}")
check("节能态那只手的显示尺寸**不跟着压扁**（仍按站姿系数 150×113）——"
      "用户给节能态单独指定了落点，说明手的大小是不变的",
      (pet20._patpat_ov.width(), pet20._patpat_ov.height()) == (150, 113),
      f"{pet20._patpat_ov.width()}×{pet20._patpat_ov.height()}")
_pump_until(lambda: pet20.patpat_squash_progress() >= 1.0)
check("★节能态下**贴图自己照样形变**，但走的是**节能态那一套量**（150×100 → 166×80：高 −20、每侧 +8）"
      "—— 不是站姿那套 35/12（那会算成 174×65，矮掉 35%）",
      (pet20._sprite_rect().width(), pet20._sprite_rect().height()) == (166, 80)
      and (pet20._patpat_ov.width(), pet20._patpat_ov.height()) == (150, 113),
      f"{pet20._sprite_rect()} ov={pet20._patpat_ov.width()}×{pet20._patpat_ov.height()}")
check("★节能态形变中那只手**横向仍不动**、纵向 = 3/8 落点再下沉 **20px**（节能态那套的下沉量，不是 35）"
      "（用「无形变矩形」算落点这条口径在节能态同样成立）",
      pet20._patpat_ov.x() == _r20.x() and pet20._patpat_ov.y() == _exp20[1] + 20,
      f"ov={pet20._patpat_ov.pos()} x={_r20.x()} y={_exp20[1]}+20")
_pump_until(lambda: not pet20.is_patpat_playing())
pet20.set_power_save(False, animate=False)
pet20.set_volume(0.5, muted=False)
pet20.set_patpat(False)
qapp.processEvents()
check("收尾：三个模式各自关掉；patpat 关掉后那只手也收干净了",
      pet20._power_save is False and pet20._muted is False and pet20.is_patpat() is False
      and pet20.is_patpat_playing() is False)

# ---- 20f-2. 形变与节能变形**互斥**（两者都改窗口几何，同时跑会互相覆盖）----
pet20.set_patpat(True)
_pet20_base = pet20._sprite_rect()
QTest.mouseClick(pet20, Qt.LeftButton)
_pump_until(lambda: pet20.patpat_squash_progress() >= 1.0)
check("前提：此刻贴图确实被压着（174×215）",
      pet20.patpat_squash_progress() == 1.0
      and (pet20._sprite_rect().width(), pet20._sprite_rect().height()) == (174, 215),
      f"sq={pet20.patpat_squash_progress()} {pet20._sprite_rect()}")
_pw20 = pet20.set_power_save(True, animate=False)
qapp.processEvents()
check("★切节能态会**先把 patpat 收干净**（手收了、形变逐像素还原、基准也清了）——"
      "不这么做两套几何会打架，留下一张永久被压扁或尺寸对不上的贴图",
      _pw20 is True and pet20.is_patpat_playing() is False
      and pet20.patpat_squash_progress() == 0.0 and pet20._patpat_sq_base is None,
      f"pw={_pw20} shown={pet20.is_patpat_playing()} sq={pet20.patpat_squash_progress()}")
check("收干净之后才切形态：节能态尺寸是按**未形变**的基准算的（150×100，不是 174×215 的残留）",
      pet20._power_save is True
      and (pet20._sprite_rect().width(), pet20._sprite_rect().height()) == (150, 100),
      f"{pet20._sprite_rect()}")
check("退出节能态后回到站姿 150×250、**底边不动**（形变那笔账一分没多记）",
      pet20.set_power_save(False, animate=False) is True
      and (pet20._sprite_rect().width(), pet20._sprite_rect().height()) == (150, 250)
      and pet20._sprite_rect().y() + 250 == _pet20_base.y() + _pet20_base.height(),
      f"{pet20._sprite_rect()} vs {_pet20_base}")
pet20.set_patpat(False)
qapp.processEvents()

# ---- 20g. 右键菜单多一行「patpat模式」（勾选态反映当前状态）----
_acts20 = _menu_acts(pet20)
_names20 = [t for (t, _c, _k, sep) in _acts20 if not sep]
check("菜单里多了「patpat模式」，紧跟在「节能模式」后面（两个都属于「模式」，排在一起）",
      "patpat模式" in _names20
      and _names20.index("patpat模式") == _names20.index("节能模式") + 1,
      str(_names20))
_row20 = [a for a in _acts20 if a[0] == "patpat模式"][0]
check("「patpat模式」是可勾选项、未勾选时 checked 为假（与 is_patpat() 一致）",
      _row20[1] is True and _row20[2] is False and pet20.is_patpat() is False, str(_row20))
check("它**没有**素材门禁（不像节能模式那样带 enabled=False）—— 用户口径「可直接打开」",
      _menu_row(pet20, "patpat模式")["enabled"] is True,
      str(_menu_row(pet20, "patpat模式").get("enabled")))
pet20.set_patpat(True)
check("开着时菜单那一行是勾上的（状态只有一份，菜单只是反映它）",
      [a for a in _menu_acts(pet20) if a[0] == "patpat模式"][0][2] is True)
pet20.set_patpat(False)
_menu_row(pet20, "patpat模式")["trigger"]()
check("点菜单那一行 → 真的把模式打开了（走的是 toggle_patpat）", pet20.is_patpat() is True)
pet20.set_patpat(False)

# ---- 20i. ★二十一改：**不开模式**单击 → 只有形变（没有那只手、也没有声音）----
# 用户口径：「在不打开 patpat 模式时也能通过单击角色贴图让贴图形变，但**暂时无声**」
#           +「形变量与时序与模式开着时完全一致」。
pet20.set_patpat(False)
pet20.set_power_save(False, animate=False)
pet20.set_volume(0.5, muted=False)
pet20._patpat_stop()                        # 把之前几节可能残留的一轮收干净
qapp.processEvents()
# 音效探针：把 stop / play 换成会记账的替身 —— 「一声不出」要用「压根没调过 play」来证明
# ⚠️ 另外给 `show_at` 也挂一个计数器：它是「那只手被摆上屏幕」的**唯一入口**，
#    比 `patpat_overlay_index() == -1` 准 —— 帧序号是**历史遗留**（`hide_now()` 不复位它），
#    前面几节跑过之后它早就是 0 了。
_audio21 = []
_audio21np = []                             # ★二十二改：第二套（normal_pet）单独记一份
_shown21 = []
_orig21_stop, _orig21_play = pet20._patpat_audio.stop, pet20._patpat_audio.play
_orig21_np_stop, _orig21_np_play = pet20._normal_pet_audio.stop, pet20._normal_pet_audio.play
_orig21_show = pet20._patpat_ov.show_at
pet20._patpat_audio.stop = lambda: (_audio21.append("stop"), _orig21_stop())[1]
pet20._patpat_audio.play = lambda: (_audio21.append("play"), _orig21_play())[1]
pet20._normal_pet_audio.stop = lambda: (_audio21np.append("stop"), _orig21_np_stop())[1]
pet20._normal_pet_audio.play = lambda: (_audio21np.append("play"), _orig21_np_play())[1]
pet20._patpat_ov.show_at = lambda *a, **k: (_shown21.append(a), _orig21_show(*a, **k))[1]
pet20._patpat_audio._last = None            # 清掉之前几节留下的痕迹
pet20._normal_pet_audio._last = None        # ★二十二改：这一套也要清（要证明它**响了**）
try:
    _before21 = pet20._sprite_rect()
    QTest.mouseClick(pet20, Qt.LeftButton)
    qapp.processEvents()
    check("★不开模式单击：那只手**从头到尾没出现过** —— `show_at()` 一次都没被调、"
          "`is_patpat_playing()` 恒 False",
          _shown21 == [] and pet20.is_patpat_playing() is False,
          f"show_at_calls={len(_shown21)} shown={pet20.is_patpat_playing()}")
    check("★但它**真的在跑**这一轮（走到第 1 步、两个定时器都在跑）",
          pet20.patpat_step() == 1 and pet20._patpat_swap_timer.isActive()
          and pet20._patpat_end_timer.isActive(),
          f"step={pet20.patpat_step()}")
    _pump_until(lambda: pet20.patpat_squash_progress() >= 1.0)
    _sq21 = pet20._sprite_rect()
    check("★形变与模式开着时**逐项相同**：150×250 → 174×215、底边不动、顶边下沉 35px、"
          "左边界左移 12px、水平中心不动",
          (_sq21.width(), _sq21.height()) == (174, 215)
          and _sq21.y() + _sq21.height() == _before21.y() + _before21.height()
          and (_sq21.y() - _before21.y(), _before21.x() - _sq21.x()) == (35, 12)
          and (_sq21.x() + _sq21.width() // 2) == (_before21.x() + _before21.width() // 2),
          f"{_sq21} vs {_before21}")
    check("★（二十二改）**patpat 那一套一声不出**：它的 `play()` 一次都没被调过（`_audio21` 里只有 stop）、"
          "`last_played` 仍是 None —— 与下面那条（normal_pet **响了**）合起来才是「只响一套」",
          "play" not in _audio21 and pet20._patpat_audio.last_played is None,
          str(_audio21))
    check("★★（二十二改）而 **normal_pet 那一套真的响了**：这轮 `play()` 调过一次、"
          "`last_played.name == bibu.mp3`（模式关着 ⇒ 只响它）",
          _audio21np.count("play") == 1
          and pet20._normal_pet_audio.last_played is not None
          and pet20._normal_pet_audio.last_played.name == "bibu.mp3",
          f"np_calls={_audio21np} np_last={pet20._normal_pet_audio.last_played}")
    _pump_until(lambda: pet20.patpat_step() == 0)
    check("★到点收干净：贴图几何**逐像素还原**、进度归零、基准与动画句柄都清掉、定时器都停",
          pet20._sprite_rect() == _before21
          and pet20.patpat_squash_progress() == 0.0
          and pet20._patpat_sq_base is None and pet20._patpat_sq_anim is None
          and not pet20._patpat_swap_timer.isActive()
          and not pet20._patpat_end_timer.isActive(),
          f"{pet20._sprite_rect()} vs {_before21}")
    # 连点照样截断（形变不会叠起来、也不会残留半途几何）
    QTest.mouseClick(pet20, Qt.LeftButton)
    qapp.processEvents()
    _pump_until(lambda: pet20.patpat_squash_progress() >= 1.0)
    QTest.mouseClick(pet20, Qt.LeftButton)
    qapp.processEvents()
    check("★不开模式连点：同样**截断重播**（回到第 1 步、形变当场还原成 0 再重新压）",
          pet20.patpat_step() == 1 and pet20.patpat_squash_progress() == 0.0
          and pet20._sprite_rect() == _before21,
          f"step={pet20.patpat_step()} sq={pet20.patpat_squash_progress()}")
    check("★★（二十二改）连点两下 → normal_pet 那套严格按 `stop→play` 走了三轮"
          "（每次点击**从头重播**：第二下的 stop 截断了第一下）—— 只完整播最后一段",
          _audio21np == ["stop", "play", "stop", "play", "stop", "play"],
          str(_audio21np))
    _pump_until(lambda: pet20.patpat_step() == 0)
    check("…连点收尾后也干净", pet20._sprite_rect() == _before21
          and pet20.patpat_squash_progress() == 0.0)
    # 拖动仍然不算（否则每次挪完位置松手都会压一下）
    _c21 = pet20._sprite_rect().center()
    pet20.mousePressEvent(_petev20(QEvent.Type.MouseButtonPress, _c21))
    pet20.mouseMoveEvent(_petev20(QEvent.Type.MouseMove, _c21 + QPoint(40, 0),
                                  Qt.NoButton, Qt.LeftButton))
    pet20.mouseReleaseEvent(_petev20(QEvent.Type.MouseButtonRelease, _c21 + QPoint(40, 0),
                                     Qt.LeftButton, Qt.NoButton))
    qapp.processEvents()
    check("★不开模式时**拖动仍不算**：没形变、也没起表（松手不该压一下）",
          pet20.patpat_step() == 0 and pet20.patpat_squash_progress() == 0.0
          and not pet20._patpat_swap_timer.isActive()
          and not pet20._patpat_end_timer.isActive())
    pet20.move(300, 300)
    qapp.processEvents()
finally:
    pet20._patpat_audio.stop = _orig21_stop
    pet20._patpat_audio.play = _orig21_play
    pet20._normal_pet_audio.stop = _orig21_np_stop
    pet20._normal_pet_audio.play = _orig21_np_play
    pet20._patpat_ov.show_at = _orig21_show
check("还原探针：音效对象（**两套**）/ 叠加窗上不再挂着测试替身",
      pet20._patpat_audio.stop == _orig21_stop and pet20._patpat_audio.play == _orig21_play
      and pet20._normal_pet_audio.stop == _orig21_np_stop
      and pet20._normal_pet_audio.play == _orig21_np_play
      and pet20._patpat_ov.show_at == _orig21_show)

# 不开模式 + **节能态**：形变必须走节能态那一套量（20 / 每侧 8）
pet20.set_power_save(True, animate=False)
qapp.processEvents()
_pb21 = pet20._sprite_rect()
QTest.mouseClick(pet20, Qt.LeftButton)
qapp.processEvents()
_pump_until(lambda: pet20.patpat_squash_progress() >= 1.0)
check("★不开模式 + 节能态：走的是节能态那一套量（150×100 → 166×80），不是站姿的 174×65；"
      "那只手照样不出现",
      (pet20._sprite_rect().width(), pet20._sprite_rect().height()) == (166, 80)
      and pet20.is_patpat_playing() is False,
      str(pet20._sprite_rect()))
_pump_until(lambda: pet20.patpat_step() == 0)
check("…并且照样逐像素还原（节能态缺手也不能留残迹）",
      pet20._sprite_rect() == _pb21 and pet20.patpat_squash_progress() == 0.0
      and pet20.is_patpat_playing() is False,
      f"{pet20._sprite_rect()} vs {_pb21}")
pet20.set_power_save(False, animate=False)
qapp.processEvents()

# ---- 20j. ★★二十二改：两套音效（patpat / normal_pet）相互独立、一次点击只响一套 ----
# 用户口径：「单击贴图形变时同步播 normal_pet 里的音频」+「patpat 模式的音频与 normal_pet 的
#           音频**互不影响，相互独立**」⇒ 只播一套 / 不动时间线 / 缺手图不播 / 连点截断只完整播最后一段。
print("== 20j. 两套音效（patpat / normal_pet）相互独立：一次点击只响一套、互不影响 ==")
_pet22 = new_pet(ALICE, at=(300, 300))
_pet22.set_patpat_sound_dir(BASE / "voices" / "patpat")
_pet22.set_normal_pet_sound_dir(BASE / "voices" / "normal_pet")

check("★两个播放器是**两个独立实例**（各自一份 `_cache` / `_player`）—— 不是共用一份",
      _pet22._patpat_audio is not _pet22._normal_pet_audio)
check("★两套列出的素材**各是各的**：patpat → `pat_0/pat_1`、normal_pet → `bibu`",
      [p.name for p in _pet22._patpat_audio.sounds()] == ["pat_0.mp3", "pat_1.mp3"]
      and [p.name for p in _pet22._normal_pet_audio.sounds()] == ["bibu.mp3"],
      f"pp={[p.name for p in _pet22._patpat_audio.sounds()]} "
      f"np={[p.name for p in _pet22._normal_pet_audio.sounds()]}")
# ★相互独立：给一套换目录，**不影响**另一套已缓存的素材（两份 `_cache` 各管各的）
_before_pp22 = [p.name for p in _pet22._patpat_audio.sounds()]
_pet22.set_normal_pet_sound_dir(BASE / "voices" / "patpat")   # 把 normal_pet 临时指去 patpat 目录
check("★给一套 `set_dir()` 不会动到另一套的 `sounds()`（两份 `_cache` 互不干扰）",
      [p.name for p in _pet22._patpat_audio.sounds()] == _before_pp22,
      str([p.name for p in _pet22._patpat_audio.sounds()]))
_pet22.set_normal_pet_sound_dir(BASE / "voices" / "normal_pet")   # 还原

# 两个替身同时盯住两套的 stop / play 顺序
_c22pp, _c22np = [], []
_o22pp = (_pet22._patpat_audio.stop, _pet22._patpat_audio.play)
_o22np = (_pet22._normal_pet_audio.stop, _pet22._normal_pet_audio.play)
_pet22._patpat_audio.stop = lambda: (_c22pp.append("stop"), _o22pp[0]())[1]
_pet22._patpat_audio.play = lambda: (_c22pp.append("play"), _o22pp[1]())[1]
_pet22._normal_pet_audio.stop = lambda: (_c22np.append("stop"), _o22np[0]())[1]
_pet22._normal_pet_audio.play = lambda: (_c22np.append("play"), _o22np[1]())[1]
try:
    _pet22._patpat_audio._last = None
    _pet22._normal_pet_audio._last = None
    # ① 模式**关着** → 只响 normal_pet
    QTest.mouseClick(_pet22, Qt.LeftButton)
    qapp.processEvents()
    check("★★模式**关着**点一下 → **normal_pet 响了**（`stop→play`、`last_played == bibu.mp3`），"
          "**patpat 一次没响**（调用表里没有 play、`last_played` 仍 None）",
          _c22np == ["stop", "play"] and _c22pp == ["stop"]
          and _pet22._normal_pet_audio.last_played is not None
          and _pet22._normal_pet_audio.last_played.name == "bibu.mp3"
          and _pet22._patpat_audio.last_played is None,
          f"np={_c22np} pp={_c22pp} np_last={_pet22._normal_pet_audio.last_played}")
    _pump_until(lambda: _pet22.patpat_step() == 0)

    # ② 模式**开着**（有手图）→ 只响 patpat（与 ① 互为镜像）
    _pet22.set_patpat(True)
    qapp.processEvents()
    _c22pp.clear()
    _c22np.clear()                       # 清掉 set_patpat 那一趟 stop
    _pet22._patpat_audio._last = None
    _pet22._normal_pet_audio._last = None
    QTest.mouseClick(_pet22, Qt.LeftButton)
    qapp.processEvents()
    check("★★模式**开着**（有手图）点一下 → **patpat 响了**（`stop→play`、`last_played` 落在两段之一），"
          "**normal_pet 一次没响**（调用表里没有 play、`last_played` 仍 None）—— 与 ① 互为镜像",
          _c22pp == ["stop", "play"] and _c22np == ["stop"]
          and _pet22._patpat_audio.last_played is not None
          and _pet22._patpat_audio.last_played.name in ("pat_0.mp3", "pat_1.mp3")
          and _pet22._normal_pet_audio.last_played is None,
          f"pp={_c22pp} np={_c22np} pp_last={_pet22._patpat_audio.last_played}")
    _pump_until(lambda: _pet22.patpat_step() == 0)

    # ③ 模式**开着但缺手图** → 两套都不响（不互相顶班）
    _pet22._patpat_scanned = True
    _pet22._patpat_frames = ()
    _pet22._patpat_audio._last = None
    _pet22._normal_pet_audio._last = None
    _c22pp.clear()
    _c22np.clear()
    _pet22._patpat_play()
    qapp.processEvents()
    check("★★模式**开着但缺手图**点一下 → **两套都没响**（两张调用表里都没有 play、"
          "两个 `last_played` 都 None）—— 「缺手图不播」+「两套不互相顶班」",
          _c22pp == ["stop"] and _c22np == ["stop"]
          and _pet22._patpat_audio.last_played is None
          and _pet22._normal_pet_audio.last_played is None,
          f"pp={_c22pp} np={_c22np}")
    _pump_until(lambda: _pet22.patpat_step() == 0)
    _pet22._patpat_scanned = False        # 还原：以后还要用真图
    _pet22._patpat_frames = ()
    _pet22.set_patpat(False)
    qapp.processEvents()
finally:
    _pet22._patpat_audio.stop, _pet22._patpat_audio.play = _o22pp
    _pet22._normal_pet_audio.stop, _pet22._normal_pet_audio.play = _o22np
check("还原探针：两套音效都不再挂着测试替身",
      _pet22._patpat_audio.stop == _o22pp[0] and _pet22._patpat_audio.play == _o22pp[1]
      and _pet22._normal_pet_audio.stop == _o22np[0]
      and _pet22._normal_pet_audio.play == _o22np[1])
_pet22.close()
qapp.processEvents()

# ---- 20h. 结构层：位置公式与接线都钉住（防以后「就地写死」）----
_SRC20 = (BASE / "app" / "pet.py").read_text(encoding="utf-8")
_SRC_PP20 = (BASE / "app" / "patpat.py").read_text(encoding="utf-8")
_src_gui20 = (BASE / "app" / "gui.py").read_text(encoding="utf-8")
_src_main20 = (BASE / "app" / "main.py").read_text(encoding="utf-8")


def _func_calls_attr(src, func_name, attr):
    """AST：**模块级函数** `func_name` 里有没有调 `.attr(...)`。

    ⚠️ 用 AST 而不是 `inspect.getsource()` 里 `in` 一下：`getsource` **把 docstring 也算进去**，
    于是「函数只留了文档、实现被删掉」也能通过（本轮静音那条正好写在 docstring 里举了例子）。
    """
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.FunctionDef) and node.name == func_name:
            for n in ast.walk(node):
                if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                        and n.func.attr == attr):
                    return True
    return False


def _func_strings(src, func_name):
    """AST：**模块级函数** `func_name` 里出现的字符串常量（**docstring 不算**）。"""
    out = []
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.FunctionDef) and node.name == func_name:
            body = list(node.body)
            if (body and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)):
                body = body[1:]                      # 去掉 docstring
            for stmt in body:
                for n in ast.walk(stmt):
                    if isinstance(n, ast.Constant) and isinstance(n.value, str):
                        out.append(n.value)
    return out


def _method_node(src, class_name, method_name):
    """AST：定位 `class_name.method_name` 那个函数节点。

    ⚠️ 必须**限定在类里**找：`pet.py` 里有 4 个同名 `mouseReleaseEvent`
    （`_VolumeIcon` / `_MenuPopup` / `PetWindow` …），上面的 `_calls_in_func()` 按函数名裸找，
    BFS 会先撞上 `_VolumeIcon` 那一个 —— 于是「PetWindow 里点没点 `_patpat_play`」永远查不到。
    """
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for fn in node.body:
                if isinstance(fn, ast.FunctionDef) and fn.name == method_name:
                    return fn
    return None


def _calls_name(src, class_name, method_name, callee):
    """AST：`class_name.method_name` 里有没有调 `callee` —— **属性调用与裸函数调用都算**。

    `pet.py` 里两种写法并存：`self._patpat_scaled(...)`（`ast.Attribute`）与
    `patpat_pos(...)`（模块级函数，`ast.Name`）。只认 Attribute 的 helper 会把后者漏掉。
    """
    fn = _method_node(src, class_name, method_name)
    if fn is None:
        return False
    for n in ast.walk(fn):
        if isinstance(n, ast.Call):
            f = n.func
            if isinstance(f, ast.Attribute) and f.attr == callee:
                return True
            if isinstance(f, ast.Name) and f.id == callee:
                return True
    return False


def _uses_name(src, class_name, method_name, ident):
    """AST：`class.method` 里有没有**出现**这个名字（常量 / 下标 / 属性都算，不要求是调用）。

    `pms[PATPAT_SEQ[0]]` 是 `Subscript(Name("PATPAT_SEQ"), …)` —— **不是 `Call`**，
    所以 `_calls_name()` 查不到「用没用 `PATPAT_SEQ`」这件事，得用这个。
    """
    fn = _method_node(src, class_name, method_name)
    if fn is None:
        return False
    for n in ast.walk(fn):
        if isinstance(n, ast.Name) and n.id == ident:
            return True
        if isinstance(n, ast.Attribute) and n.attr == ident:
            return True
    return False


def _method_call_order(src, class_name, method_name):
    """AST：`class.method` 里**按源码顺序**列出被调用到的名字（属性调用取 `attr`、裸函数调用取 `id`）。

    用来钉「**顺序**契约」——`_calls_name()` 只回答「有没有调」，而
    `play()` 里先 `play()` 再 `setPosition(0)` 也照样能过，但那一设就白设了、连点不会从头播。
    ⚠️ `ast.walk` 是 BFS、**不保证源码顺序**，所以按 `lineno` 排一遍；同一行的多个调用保持原序（稳定排序）。
    """
    fn = _method_node(src, class_name, method_name)
    if fn is None:
        return []
    seen = []
    for n in ast.walk(fn):
        if isinstance(n, ast.Call):
            f = n.func
            if isinstance(f, ast.Attribute):
                seen.append((n.lineno, f.attr))
            elif isinstance(f, ast.Name):
                seen.append((n.lineno, f.id))
    return [name for _ln, name in sorted(seen, key=lambda t: t[0])]


def _calls_at_top_level(src, class_name, method_name, attr):
    """AST：`class.method` 的**函数体顶层语句**里有没有出现 `.attr(...)`。

    钉的是「**无条件执行**」—— 放进 `if` / `try` 里就不算（那样它只在某些分支下才跑）。
    ★二十一改用它钉 `_patpat_play`：两个定时器必须**无条件起表**，
    否则「不开模式单击就没形变」这条需求会悄悄复发（形变是靠这两个表推的）。
    ⚠️ 遇到 `If/Try/With/For/While` 跳过**整条**语句 —— 那是条件执行。
    """
    fn = _method_node(src, class_name, method_name)
    if fn is None:
        return False
    body = list(fn.body)
    if (body and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)):
        body = body[1:]                       # 去掉 docstring
    skip = (ast.If, ast.Try, ast.With, ast.For, ast.While, ast.AsyncWith, ast.AsyncFor)
    for stmt in body:
        if isinstance(stmt, skip):
            continue
        for n in ast.walk(stmt):
            if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                    and n.func.attr == attr):
                return True
    return False


def _early_return_on(src, class_name, method_name, ident):
    """AST：`class.method` 里有没有「**以 `ident` 为条件**的提前返回」（`if …ident…: return`）。

    ★二十一改用它钉「那道模式守卫**被设计性删除**了」：`_patpat_play` 里不许再有
    `if not self._patpat: return …` —— 有它，不开模式就一点形变都没有。
    """
    fn = _method_node(src, class_name, method_name)
    if fn is None:
        return False
    for n in ast.walk(fn):
        if not isinstance(n, ast.If):
            continue
        has_ident = any((isinstance(x, ast.Attribute) and x.attr == ident)
                        or (isinstance(x, ast.Name) and x.id == ident)
                        for x in ast.walk(n.test))
        has_ret = any(isinstance(x, ast.Return) for x in ast.walk(n))
        if has_ident and has_ret:
            return True
    return False


def _count_calls(src, class_name, method_name, callee):
    """AST：`class.method` 里 `callee(...)`（裸函数调用）出现了几次。"""
    fn = _method_node(src, class_name, method_name)
    if fn is None:
        return 0
    return sum(1 for n in ast.walk(fn)
               if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
               and n.func.id == callee)


def _elif_guards_normal_pet(src, class_name, method_name):
    """AST：`class.method` 里那条「选 normal_pet」的分支必须是 **`elif not self._patpat`**。

    即：某个 `if`（带 `elif`）的 **elif 分支**里调了 `_normal_pet_audio.play()`，
    而且该 elif 的 **test 里带 `_patpat`**。
    ★二十二改用它钉「**必须用 `elif not self._patpat` 而不是 `else`**」—— 用 `else` 的话
    「模式**开着**但缺手图」会错误地播 normal_pet（违反用户口径「缺手图时不播」）。
    """
    fn = _method_node(src, class_name, method_name)
    if fn is None:
        return False
    for n in ast.walk(fn):
        if not isinstance(n, ast.If) or not n.orelse:
            continue
        for sub in n.orelse:
            if not isinstance(sub, ast.If):        # 不是 elif（是 else）→ 跳过
                continue
            test_has = any((isinstance(x, ast.Attribute) and x.attr == "_patpat")
                           or (isinstance(x, ast.Name) and x.id == "_patpat")
                           for x in ast.walk(sub.test))
            body_np = any(isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)
                          and c.func.attr == "play"
                          and isinstance(c.func.value, ast.Attribute)
                          and c.func.value.attr == "_normal_pet_audio"
                          for c in ast.walk(sub))
            if test_has and body_np:
                return True
    return False


check("结构层：`PetWindow._patpat_play()` 用的是 `patpat_pos()` / `_patpat_scaled()`"
      "（不是把 150×113 或某个坐标写死），且起表前先 `_patpat_stop()` 清干净上一轮",
      _calls_name(_SRC20, "PetWindow", "_patpat_play", "patpat_pos")
      and _calls_name(_SRC20, "PetWindow", "_patpat_play", "_patpat_scaled")
      and _calls_name(_SRC20, "PetWindow", "_patpat_play", "_patpat_stop"),
      f"pos={_calls_name(_SRC20, 'PetWindow', '_patpat_play', 'patpat_pos')} "
      f"scaled={_calls_name(_SRC20, 'PetWindow', '_patpat_play', '_patpat_scaled')}")
check("结构层：`PetWindow.mouseReleaseEvent()` 里点了 `_patpat_play()`（左键点击 → 抚摸的接口）"
      " —— ⚠️ 这条只有**限定到 `PetWindow`** 才查得准（同名方法有 4 个）",
      _calls_name(_SRC20, "PetWindow", "mouseReleaseEvent", "_patpat_play"))
check("结构层：贴图动了要带着那只手一起走（`PetWindow._sync_bubble()` → `_patpat_follow()`）",
      _calls_name(_SRC20, "PetWindow", "_sync_bubble", "_patpat_follow"))
check("结构层：`PetWindow.closeEvent()` 里要收手（顶层窗不会跟着桌宠一起关）",
      _calls_name(_SRC20, "PetWindow", "closeEvent", "_patpat_stop"))
check("结构层：`PetWindow.set_pet_dir()`（换角色）里要收手并作废手图缓存（别留上一个角色的）",
      _calls_name(_SRC20, "PetWindow", "set_pet_dir", "_patpat_stop"))
check("结构层：`PetWindow.set_patpat()` 关掉时要 `_patpat_stop()`（别留一只手在屏幕上）",
      _calls_name(_SRC20, "PetWindow", "set_patpat", "_patpat_stop"))
check("结构层：`_patpat_play` / `_patpat_swap` 都按 `PATPAT_SEQ` 取帧"
      "（不再写死 `pms[0]` / `pms[1]` 那种两帧写法）—— 三帧时序是数据驱动的，改帧序只动常量",
      _uses_name(_SRC20, "PetWindow", "_patpat_play", "PATPAT_SEQ")
      and _uses_name(_SRC20, "PetWindow", "_patpat_swap", "PATPAT_SEQ"))
check("结构层：`_patpat_swap` 要**同时**换帧和推形变 —— 切到「下压」把形变推上去、"
      "切回「抬起」把形变弹回来（`_patpat_step` 记第几步，才能一轮里响两次）",
      _calls_name(_SRC20, "PetWindow", "_patpat_swap", "_patpat_squash_to")
      and _uses_name(_SRC20, "PetWindow", "_patpat_swap", "_patpat_step"))
# ★★ 二十一改新增的两条「反向」结构断言（专门防「不开模式形变被吞掉」复发）
check("★★结构层（二十一改，反向）：`_patpat_swap` 里**不许出现 `is_shown`**"
      " —— 形变与「那只手在不在」必须解耦。二十改那版开头是 "
      "`if len(pms) < 2 or size is None or not self._patpat_ov.is_shown(): return`，"
      "改成「模式关着也要形变」之后，它会把形变**一起吞掉**；"
      "那道守卫如今只留在只管换帧的 `_patpat_frame()` 里",
      not _uses_name(_SRC20, "PetWindow", "_patpat_swap", "is_shown")
      and _uses_name(_SRC20, "PetWindow", "_patpat_frame", "is_shown"),
      f"swap_has_is_shown={_uses_name(_SRC20, 'PetWindow', '_patpat_swap', 'is_shown')} "
      f"frame_has_is_shown={_uses_name(_SRC20, 'PetWindow', '_patpat_frame', 'is_shown')}")
check("★★结构层（二十一改，反向）：`_patpat_play` 里**不许再有「模式守卫」**"
      "（`if not self._patpat: return …` 那种提前返回）—— 模式只管「叠不叠手 / 出不出声」，"
      "形变与它无关；有这道门就等于把「不开模式也要形变」整条需求吞掉",
      not _early_return_on(_SRC20, "PetWindow", "_patpat_play", "_patpat"))
check("★★结构层（二十一改）：`_patpat_play` 的两个定时器必须在**函数体顶层**无条件起表"
      " —— 被 `if` 包起来就只在某些分支下才跑（形变靠它们推，包起来就没形变了）；"
      "`_patpat_stop()` 也一样要在顶层（连点截断是硬契约）",
      _calls_at_top_level(_SRC20, "PetWindow", "_patpat_play", "start")
      and _calls_at_top_level(_SRC20, "PetWindow", "_patpat_play", "_patpat_stop"),
      f"start_at_top={_calls_at_top_level(_SRC20, 'PetWindow', '_patpat_play', 'start')} "
      f"stop_at_top={_calls_at_top_level(_SRC20, 'PetWindow', '_patpat_play', '_patpat_stop')}")
check("★结构层（二十一改）：`_patpat_play` 里换帧 / 定位 / 播音效三步都在，"
      "但形变只由 `_patpat_swap` 推（两档共用一条时间线）",
      _calls_name(_SRC20, "PetWindow", "_patpat_play", "_patpat_scaled")
      and _calls_name(_SRC20, "PetWindow", "_patpat_play", "patpat_pos")
      and _uses_name(_SRC20, "PetWindow", "_patpat_play", "_patpat_audio")
      and _calls_name(_SRC20, "PetWindow", "_patpat_swap", "_patpat_squash_to"),
      f"scaled={_calls_name(_SRC20, 'PetWindow', '_patpat_play', '_patpat_scaled')} "
      f"pos={_calls_name(_SRC20, 'PetWindow', '_patpat_play', 'patpat_pos')} "
      f"audio={_uses_name(_SRC20, 'PetWindow', '_patpat_play', '_patpat_audio')}")
# ★★ 二十二改新增的四条结构契约（两套音效：选哪套 / 停哪套 / 建几个 / 注入几个）
check("★★结构层（二十二改）：`_patpat_play` 里**同时**用两套音效"
      "（`_patpat_audio` = 模式开、`_normal_pet_audio` = 模式关，选音效两支都在）",
      _uses_name(_SRC20, "PetWindow", "_patpat_play", "_patpat_audio")
      and _uses_name(_SRC20, "PetWindow", "_patpat_play", "_normal_pet_audio"),
      f"pp={_uses_name(_SRC20, 'PetWindow', '_patpat_play', '_patpat_audio')} "
      f"np={_uses_name(_SRC20, 'PetWindow', '_patpat_play', '_normal_pet_audio')}")
check("★★结构层（二十二改）：`_patpat_stop` 里**同时**停两套"
      "（停下时把声音全收干净 —— 任何时刻最多一套在响）",
      _uses_name(_SRC20, "PetWindow", "_patpat_stop", "_patpat_audio")
      and _uses_name(_SRC20, "PetWindow", "_patpat_stop", "_normal_pet_audio"),
      f"pp={_uses_name(_SRC20, 'PetWindow', '_patpat_stop', '_patpat_audio')} "
      f"np={_uses_name(_SRC20, 'PetWindow', '_patpat_stop', '_normal_pet_audio')}")
check("★★结构层（二十二改）：`PetWindow.__init__` 里**建两个 `PatPatSound()`**"
      "（两个独立实例；只建一个就共用播放器，「相互独立」名存实亡）",
      _count_calls(_SRC20, "PetWindow", "__init__", "PatPatSound") >= 2,
      f"count={_count_calls(_SRC20, 'PetWindow', '__init__', 'PatPatSound')}")
check("★★结构层（二十二改）：`app/main.py` 里**两个音效目录都注入**"
      "（`set_patpat_sound_dir` + `set_normal_pet_sound_dir` + `\"normal_pet\"` 字面量；"
      "少一个那一套就永远没声音）",
      "set_patpat_sound_dir(" in _src_main20
      and "set_normal_pet_sound_dir(" in _src_main20
      and '"normal_pet"' in _src_main20)
check("★★结构层（二十二改，反向）：`_patpat_play` 选 normal_pet 那条必须是 "
      "**`elif not self._patpat`**、**不能是 `else`** —— 用 `else` 会让「模式**开着**但缺手图」"
      "错误地播 normal_pet（违反用户口径「缺手图时不播 / 两套不互相顶班」）",
      _elif_guards_normal_pet(_SRC20, "PetWindow", "_patpat_play"))
check("★改名层（二十一改）：目录名常量就是 `patpat`（路径拼接只此一处）；"
      "`app/pet.py` / `app/patpat.py` / `app/main.py` 里**没有 petpet 残留**",
      ppmod.PATPAT_DIR_NAME == "patpat"
      and not any("petpet" in (BASE / "app" / f).read_text(encoding="utf-8").lower()
                  for f in ("pet.py", "patpat.py", "main.py", "config.py", "gui.py")),
      f"dir={ppmod.PATPAT_DIR_NAME!r}")
check("结构层：形变尺寸必须走纯几何 `patpat_squash_size()`（不许就地写死 174 / 215 或 ±35 / ±12），"
      "手的下沉量走 `patpat_squash_drop()`",
      _calls_name(_SRC20, "PetWindow", "_patpat_apply_squash", "patpat_squash_size")
      and _uses_name(_SRC20, "PetWindow", "_patpat_follow", "patpat_squash_drop"))
check("★结构层（二十改）：两套形变量**按形态选** —— `_patpat_apply_squash` 与 `_patpat_follow` "
      "都必须把 `self._power_save` 传下去。不传就会一直用站姿那套 35/12，"
      "节能态那张扁平贴图会被压掉 35%（只剩 65px）—— 而行为断言只在**两条路都跑到**时才抓得到，"
      "这条结构层是它的保险",
      _uses_name(_SRC20, "PetWindow", "_patpat_apply_squash", "_power_save")
      and _uses_name(_SRC20, "PetWindow", "_patpat_follow", "_power_save"),
      f"apply={_uses_name(_SRC20, 'PetWindow', '_patpat_apply_squash', '_power_save')} "
      f"follow={_uses_name(_SRC20, 'PetWindow', '_patpat_follow', '_power_save')}")
check("结构层：`_patpat_stop()` 里必须还原形变（连点 / 关模式 / 换角色 / 关窗四条路共用它）",
      _calls_name(_SRC20, "PetWindow", "_patpat_stop", "_patpat_squash_restore"))
check("结构层：`_patpat_hide()`（到点收手）也**兜底**还原一次"
      " —— 万一把帧时长调得比形变还短，也不会留下压扁的贴图",
      _calls_name(_SRC20, "PetWindow", "_patpat_hide", "_patpat_squash_restore"))
check("结构层：`set_power_save()` 在切形态**之前**先 `_patpat_stop()`（两套几何互斥）",
      _calls_name(_SRC20, "PetWindow", "set_power_save", "_patpat_stop"))
check("结构层（反向）：形变期间给手定位**必须**用存下来的「无形变矩形」`_patpat_sq_base`"
      " —— `_patpat_follow` 里不许直接拿 `self._sprite_rect()` 的 x 去算（那样手会跟着左边界横移"
      " 12px（节能态 8px），违背用户口径「横向不要有其他改变」）",
      "_patpat_sq_base" in inspect.getsource(petmod.PetWindow._patpat_follow))
check("★结构层（二十改）：`_patpat_stop()`（连点 / 关模式 / 换角色 / 关窗四条路共用）里必须**动到音效对象**"
      " —— 「连点截断上一轮音频」靠的就是它；只收手不掐音频，上一段会继续响到放完",
      _uses_name(_SRC20, "PetWindow", "_patpat_stop", "_patpat_audio"))
_order20b = _method_call_order(_SRC_PP20, "PatPatSound", "play")
_want20b = ["stop", "setSource", "setPosition", "play"]
check("★结构层（二十改）：`PatPatSound.play()` 里那条**顺序**必须是 "
      "`stop()` → `setSource()` → `setPosition(0)` → `play()` —— 「有没有调」用 `_calls_name` 就够，"
      "但顺序错了照样坏（先 `play()` 再 `setPosition(0)`，那一设就白设、连点不会从头播）",
      [x for x in _order20b if x in _want20b] == _want20b,
      f"order={_order20b}")
_src_ensure20 = inspect.getsource(ppmod.PatPatSound._ensure)
# ⚠️ 比位置**必须先把注释行剔掉**：`_ensure` 的注释里同时提到了这两个名字，
# 不剔的话 `index()` 会命中注释、顺序判断直接失效（本轮第一版就这么误报了一项）。
_src_ensure_code20 = "\n".join(l for l in _src_ensure20.splitlines()
                               if not l.strip().startswith("#"))
check("终端静音：`silence_ffmpeg_logs()` 两条一起上（Qt 日志类别 `qt.multimedia.*=false` + "
      "FFmpeg 级别 `av_log_set_level`），**且必须排在 `QMediaPlayer()` 构造之前** ——"
      "少一条那行 `Estimating duration from bitrate` 就会从 stderr 漏出来（真机实测过）；"
      "⚠️ 断言走 AST，不能只 `in getsource()`（docstring 里也写着这两个词，实现删了照样过）",
      callable(getattr(ppmod, "silence_ffmpeg_logs", None))
      and _func_calls_attr(_SRC_PP20, "silence_ffmpeg_logs", "setFilterRules")
      and _func_calls_attr(_SRC_PP20, "silence_ffmpeg_logs", "av_log_set_level")
      and _func_calls_attr(_SRC_PP20, "silence_ffmpeg_logs", "CDLL")
      and any("qt.multimedia" in s
              for s in _func_strings(_SRC_PP20, "silence_ffmpeg_logs"))
      and "silence_ffmpeg_logs()" in _src_ensure_code20
      and _src_ensure_code20.index("silence_ffmpeg_logs()")
      < _src_ensure_code20.index("QMediaPlayer()"),
      f"call_in_code={'silence_ffmpeg_logs()' in _src_ensure_code20}")
check("终端静音是**幂等**的（多调几次不重复干活、也不抛）—— 播放器懒建时也会再调一遍",
      ppmod.silence_ffmpeg_logs() is None and ppmod._LOG_SILENCED is True)
check("结构层（反向）：叠加窗的 `paintEvent` 只画这一帧，**不许**碰阴影 / 不透明度效果"
      "（十六改那两条在弹窗上踩过的坑：`QGraphicsDropShadowEffect` 会让分层窗闪烁、"
      "`QGraphicsOpacityEffect` 会变不透明黑块）",
      "QGraphicsDropShadowEffect" not in inspect.getsource(petmod._PatPatOverlay)
      and "QGraphicsOpacityEffect" not in inspect.getsource(petmod._PatPatOverlay))
check("接线：设置页开关的落地点是 `notify_patpat_mode`，主程序用 `set_patpat_mode_cb` / "
      "`set_on_patpat` 两头驱动桌宠（模式状态在桌宠那边）",
      "self._win.notify_patpat_mode(on)" in _src_gui20
      and "win.set_patpat_mode_cb(" in _src_main20
      and "pet.set_on_patpat(" in _src_main20)
check("提示文案就在主程序里（「patpat模式启动」/「patpat模式关闭」）—— 两个入口都汇到这一处",
      '"patpat模式启动"' in _src_main20 and '"patpat模式关闭"' in _src_main20)
check("摸摸音效目录由主程序注入（`voices/patpat`）—— pet.py 不认识项目根",
      "pet.set_patpat_sound_dir(" in _src_main20 and '"patpat"' in _src_main20)
check("配置层：★`_RUNTIME_ONLY_GENERAL` 里**只剩 patpat_mode**（纯运行时的唯一一个）"
      "—— 2026-09-29 静音模式已改成**落盘偏好**（用户要求「重开保留开关状态」），"
      "所以 mute_mode 必须**不在**这张名单里；行为断言在 smoke_settings 里用临时 config 跑",
      tuple(getattr(cfgmod20, "_RUNTIME_ONLY_GENERAL", ())) == ("patpat_mode",),
      str(getattr(cfgmod20, "_RUNTIME_ONLY_GENERAL", None)))

pet20.close()
qapp.processEvents()

# ---- 21. ★★置顶「入带」看门狗（2026-09-21 实测：`WS_EX_TOPMOST` 位在、带不在）----
# 用户报：**开机自启**后给「打开xxx」，角色被随后打开的浏览器窗口盖住；同进程的气泡 / 状态提示
# 却正常显示。登录期记录器 + `GetWindow(GW_HWNDPREV)` 权威 z 链取证：桌宠的 `WS_EX_TOPMOST` 位
# **全程为真**，但第一个可见外来窗（Edge）**非置顶**却排在它上面 —— 它其实是个普通窗口。
print("== 21. 置顶「入带」看门狗：判据 / 修法 / 不许顶到自己的手上面 ==")

_petmod_src21 = inspect.getsource(petmod)

# 21a. 纯判据：四种上方窗口各核一遍（这是整个修复的地基，必须先钉死）
_band = petmod._band_verdict
check("★判据·到顶（上方没有可见窗口）→ **没掉带**（比所有窗口都高）",
      _band(None) is False and _band(0) is False)
check("★判据·上方是**非置顶**外来窗（Edge 那种）→ **掉了**（本 bug 的现场）",
      _band((0x1234, 0)) is True)
check("★判据·上方是**置顶**外来窗（任务栏 / 输入法候选 / SAO Utils）→ **没掉**",
      _band((0x1234, petmod.WS_EX_TOPMOST)) is False)
check("★判据·上方是**我们自己的手 / 气泡**（`WS_EX_TOOLWINDOW`）→ **没掉**"
      "（它在贴图上面是设计，不是异常）",
      _band((0x1234, petmod.WS_EX_TOOLWINDOW)) is False
      and _band((0x1234, petmod.WS_EX_TOOLWINDOW | petmod.WS_EX_TOPMOST)) is False)
check("★判据·上游把「非置顶」和「自己人」两档的位置写反了也要能看出来："
      "带 TOPMOST 的**外来**窗 ≠ 掉带，不带 TOPMOST 的**外来**窗 = 掉带",
      _band((1, petmod.WS_EX_TOPMOST)) is False and _band((1, 0)) is True)

# 21b. 修法：必须真的调 SetWindowPos(HWND_TOPMOST)，且**只在判据成立时**才调
_sep_src = inspect.getsource(petmod.PetWindow._ensure_topmost_band)
_src_swp_call = inspect.getsource(petmod._win_set_topmost)
check("★修法：走 `SetWindowPos` + `HWND_TOPMOST`（不是只 `raise_()` —— raise 改不了「带」）",
      "SetWindowPos" in _src_swp_call and "HWND_TOPMOST" in _src_swp_call)
check("★★修法：`SetWindowPos` 里**每次现取 `_u32`**（`_u32.SetWindowPos(...)`）——"
      "**不许**把它绑成模块级引用：绑了之后换掉 `_u32`（测试注入 / 重新初始化）会被静默忽略，"
      "断言会拿到「0 次调用」的假绿（2026-09-21 实测踩过）",
      "_u32.SetWindowPos(" in _src_swp_call
      and "= _u32.SetWindowPos" not in _petmod_src21)
check("修法：`_ensure_topmost_band` 里**先判据、后动手**"
      "（`topmost_out_of_band` 必须在 `_win_set_topmost` 之前）—— "
      "无条件推置顶会把贴图顶到**自己的手 / 气泡上面**，把设计顶反",
      "topmost_out_of_band" in _sep_src
      and _sep_src.index("topmost_out_of_band") < _sep_src.index("_win_set_topmost"))
check("修法：带上 `SWP_NOACTIVATE`（不抢焦点 —— 她本来就不抢）与 `NOMOVE | NOSIZE`"
      "（只改层级，不动几何）",
      "SWP_NOACTIVATE" in _src_swp_call and "SWP_NOMOVE" in _src_swp_call
      and "SWP_NOSIZE" in _src_swp_call)
# ★行为层（比结构层硬）：不是 `force` 时，**必须**先问判据 —— 判据说「没掉带」就一次都不许碰
# `SetWindowPos`。少了这道门就变成「每 1.5s 无条件把贴图推到最顶」，
# 会把贴图顶到**自己的手 / 气泡上面**（「手盖在贴图之上」是设计）。
#
# ⚠️ 写法要点（两轮反向验证才试对，2026-09-21）：
#   ① 用**注入的 `petmod._u32` 替身**，让判据稳定说「在带」（`GetWindowLongW` 恒回 TOPMOST、
#      `GetWindow` 到顶）—— 否则判据会去问真的桌面（离屏拿不到真结果、行为随机）；
#   ② 离屏下 `_HAS_WIN32` 是假 ⇒ 必须像刚才那两条 `_first_window_above` 断言一样
#      **临时把 `_u32` 注入进去**（`hasattr` 判断、用完 `del`），这条路才跑得起来；
#   ③ 断言必须**成对**：只查「没掉带时没调」会假绿（函数可以压根没走到），
#      必须配一条「同一次注入下 `force=True` 确实调到了」当对照。
_had_u32_22 = hasattr(petmod, "_u32")
_orig_u32_22 = getattr(petmod, "_u32", None)
_orig_hadwin_22 = petmod._HAS_WIN32


class _RecSWP:
    """`SetWindowPos` 的记账替身：只记调用、返回 True（当成成功）。"""

    def __init__(self):
        self.calls = []

    def __call__(self, *a, **k):
        self.calls.append(a)
        return True


class _FakeU32Band:
    """`_u32` 的替身：`SetWindowPos` 记账；判据侧一律回「在带」。

    ⚠️ 必须是**普通对象**（属性访问），不能用 `dict`：实现里取的是 `_u32.SetWindowPos`
    （属性），`dict` 只有下标 `['SetWindowPos']` ⇒ 每次 `AttributeError` 被 `except` 吞成
    `False`，断言会拿到「0 次调用」的假绿（2026-09-21 实测踩过）。

    ⚠️⚠️ **必须把 `_first_window_above` 这一路用到的方法配齐**（`GetWindow` +
       `IsWindowVisible`）：实现里 `IsWindowVisible` 也是从 `_u32` 上取的，
       替身漏了它 ⇒ `AttributeError` 同样被 `except` 吞成 `False` ⇒ 判据把这个可见的上方窗
       当成「隐藏窗」跳掉、一路跳到顶返回 `None` ⇒ 判据反向地说「没掉带」，
       于是「真掉落带」那条断言永远绿不了（2026-09-21 实测踩过**第三次**）。
    """

    def __init__(self, rec):
        self.SetWindowPos = rec
        self.GetWindowLongW = lambda h, i: petmod.WS_EX_TOPMOST   # 上方窗都算「置顶」
        self.GetWindow = lambda h, w: 0                          # 往上直接到顶
        self.IsWindowVisible = lambda h: True                    # ★配齐：上方窗算可见


try:
    _rec22 = _RecSWP()
    petmod._u32 = _FakeU32Band(_rec22)
    petmod._HAS_WIN32 = True                # 绕过「平台有没有 Windll」那道守卫，把判据+动作整条跑通
    _pet22 = new_pet(ALICE, at=(300, 300))
    _pet22._top_band_timer.stop()            # 停掉真表，免得它自己来插一脚
    _rec22.calls.clear()                     # 丢掉 showEvent 那次 force
    _pet22._ensure_topmost_band()            # force=False，判据说「没掉带」
    check("★行为：判据说「**没掉带**」时 `_ensure_topmost_band()` **一次都不碰** `SetWindowPos`"
          "（否则每 1.5s 无条件推顶 ⇒ 贴图会顶到自己的手上面，把「手在最上」的设计顶反）",
          _rec22.calls == [], f"调了 {len(_rec22.calls)} 次")
    _pet22._ensure_topmost_band(force=True)  # ★配对对照
    check("★★配对对照：同一次注入下 `force=True` 时**确实调到了** `SetWindowPos`"
          "（证明上面那条「没调」是真被判据挡下，不是函数压根没跑到）",
          len(_rec22.calls) == 1, f"调了 {len(_rec22.calls)} 次")
    # ★★再钉一条：**真掉落带**时必须动作（否则看门狗形同虚设）
    _rec22.calls.clear()
    _band_fake = _FakeU32Band(_rec22)
    _band_fake.GetWindow = lambda h, w: 0x9999          # 上方有个可见窗
    _band_fake.GetWindowLongW = lambda h, i: 0          # 且它**非置顶** ⇒ 掉带
    petmod._u32 = _band_fake
    _pet22._ensure_topmost_band()
    check("★★行为：**真掉落带**（上方有个非置顶外来窗）时 `_ensure_topmost_band()` "
          "**必须调到** `SetWindowPos`（看门狗存在的意义就在这一支）",
          len(_rec22.calls) == 1, f"调了 {len(_rec22.calls)} 次")
    _pet22.close()
    qapp.processEvents()
finally:
    petmod._HAS_WIN32 = _orig_hadwin_22
    if _had_u32_22:
        petmod._u32 = _orig_u32_22
    else:
        del petmod._u32

# 21c. ⚠️⚠️ ctypes 签名：不声明 argtypes 时 64 位下 `-1` 会被当 c_int 传 ⇒ SetWindowPos 静默 False
# ⚠️ 离屏下没有 `_u32`（`_HAS_WIN32` 为假）⇒ 走 **AST 源码**这条通用路，别直接 getattr 模块属性。
check("★★源码里**显式声明了** `SetWindowPos` 的 `argtypes`"
      "（64 位下 HWND 是 8 字节指针；不声明时 `hWndInsertAfter=-1` 按 c_int 传成 0xFFFFFFFF "
      "⇒ 静默返回 False、窗口一动不动，实测踩过）",
      "SetWindowPos.argtypes" in _petmod_src21)
_ast21 = ast.parse(_petmod_src21)
_ok_argv21 = False
for _n in ast.walk(_ast21):
    if not isinstance(_n, ast.Assign):
        continue
    _tg = _n.targets[0]
    if not (isinstance(_tg, ast.Attribute) and _tg.attr == "argtypes"):
        continue
    if not (isinstance(_tg.value, ast.Attribute) and _tg.value.attr == "SetWindowPos"):
        continue
    if isinstance(_n.value, ast.List) and len(_n.value.elts) == 7:
        _ok_argv21 = True
check("…并且那个 argtypes 挂在 `SetWindowPos` 上（不是别的函数），且长度是 7（hWnd/after/x/y/w/h/flags）",
      _ok_argv21,
      str([ast.unparse(n.targets[0]) for n in ast.walk(_ast21)
           if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Attribute)
           and n.targets[0].attr == "argtypes"]))

# 21c-2. ★★ 拼写层：`ctypes` 里那个加载器叫 **`windll`（全小写）**，**没有 `Windll`**。
# 2026-09-21 一度写成 `ctypes.Windll` ⇒ `_HAS_WIN32` **恒为 False**（真机也 False）⇒
# 整套看门狗**一个字节都没执行**。而「离屏 False、真机也 False」把这件事**完全掩盖**了
# （当时还以为只是离屏没有）。⇒ 必须把「拼写」本身钉成断言。
#
# ⚠️ 只看整份源码会**误伤注释**（文件里正有一段注释在讲「别写成 Windll」）。
# 所以判据必须落在**代码 token**上：把注释与字符串剥掉再查（`ast` + `tokenize` 双重手段）。
_ast_w21 = ast.parse(_petmod_src21)
# ① 正向：AST 里必须**真的存在** `ctypes.windll` 这个属性访问
_has_lower = False
# ② 反向：**任何形态**的 `Windll` 都不许出现 —— 既包括属性访问 `ctypes.Windll`，
#    也包括 `hasattr(ctypes, "Windll")` 这种**字符串字面量**形态
#    （★实测踩过：只查属性访问会漏掉后者，反向验证 G 例就因此只红 1 项、蒙混过关）。
_has_upper = False
for _n in ast.walk(_ast_w21):
    if isinstance(_n, ast.Attribute) and _n.attr == "windll":
        _has_lower = True
    if isinstance(_n, ast.Attribute) and _n.attr == "Windll":
        _has_upper = True
    if isinstance(_n, ast.Constant) and isinstance(_n.value, str) and _n.value == "Windll":
        _has_upper = True
check("★★代码（AST，不含注释）里用的是 `ctypes.windll`（**全小写**）—— 写成 `Windll` 会让 "
      "`_HAS_WIN32` 恒为假、整套置顶看门狗静默空转（实测踩过：离屏与真机「都 False」互相掩护）",
      _has_lower)
check("★★反向：代码（AST，不含注释）里**不许**出现 `Windll` 这个拼写 —— "
      "**属性形态**（`ctypes.Windll`）与**字符串字面量形态**（`hasattr(ctypes, \"Windll\")`）都算",
      not _has_upper)
check("★平台开关形态：`_HAS_WIN32` 由 **`sys.platform == 'win32'` + `hasattr(ctypes, 'windll')**"
      " 两项共同决定（只查 `hasattr` 会在名字拼错时静默为假）",
      any(isinstance(_n, ast.Assign)
          and any(isinstance(t, ast.Name) and t.id == "_HAS_WIN32" for t in _n.targets)
          and "win32" in ast.unparse(_n.value)
          and "windll" in ast.unparse(_n.value)
          for _n in ast.walk(_ast_w21)))

# 21d. 接线：showEvent 起表并兜底；patpat 亮手时调快；两处 stop 都调回常规
_src_show21 = inspect.getsource(petmod.PetWindow.showEvent)
check("★接线：`showEvent` 里**先兜一次**（force）再 `start()` 看门狗表 —— "
      "登录自启那条路正是「show 了但没入带」",
      "ensure_topmost_band" in _src_show21
      and "start" in _src_show21
      and _src_show21.index("ensure_topmost_band") < _src_show21.index("start"))
_src_play21 = inspect.getsource(petmod.PetWindow._patpat_play)
check("★接线：亮手那段把看门狗**调快**（手压着贴图时掉带窗口一冒头就得抢回）",
      "PETS_TOP_BAND_PS_MS" in _src_play21 or "_top_band_timer" in _src_play21)
check("★接线：收手（`_patpat_hide`）与掐断（`_patpat_stop`）都把节奏**调回常规**"
      "（不许留在 400ms 把 CPU 白烧）",
      "PETS_TOP_BAND_MS" in inspect.getsource(petmod.PetWindow._patpat_hide)
      and "PETS_TOP_BAND_MS" in inspect.getsource(petmod.PetWindow._patpat_stop))
check("★接线：关窗（`closeEvent`）先把看门狗 `stop()`（别再去抢一个正被销毁的窗口的置顶）",
      "stop" in inspect.getsource(petmod.PetWindow.closeEvent))
check("★`main.py` 在 `pet.show()` 之后补一次 `ensure_topmost_band()`（开机自启那条路）",
      "pet.ensure_topmost_band()" in _src_main20)

# 21e. 反向：判据里**不许**出现「查 WS_EX_TOPMOST 位就收工」那套（那位查不出本 bug）
check("★反向：判据**不许**只查 `WS_EX_TOPMOST` 位就下结论（那位全程为真 ⇒ 永远报「正常」）——"
      "必须走 z 链（`GetWindow` + `GW_HWNDPREV`）",
      "GW_HWNDPREV" in inspect.getsource(petmod._first_window_above)
      and "GetWindow" in inspect.getsource(petmod._first_window_above))
# ★行为层：判据必须**真的跳过隐藏窗**。隐藏窗（`Default IME` / `_q_titlebar` / message window）
# 的 z 位置是**残留**的、不代表视觉层级；不跳过就会**拿一个藏起来的窗口当判据** ⇒ 判据随机失真。
# 用一个「第一个可见 → 隐藏」的上方序列钉住：判据必须停在「可见」那一个上。
class _FakeU32:
    """一个**可编程**的假 user32：`GetWindow` 按脚本吐句柄，`IsWindowVisible` 按「可见表」判。

    用来把 `_first_window_above` 的「**跳过隐藏窗**」这条钉成**行为断言**（不是结构断言）：
    z 链上游是「隐藏的 message window → 可见的置顶窗」时，必须越过隐藏那个、返回可见那个。
    """
    def __init__(self, seq, visible):
        self.seq = list(seq)              # GetWindow 依次返回的句柄（0 = 到顶）
        self.visible = set(visible)

    def GetWindow(self, hwnd, what):
        return self.seq.pop(0) if self.seq else 0

    def IsWindowVisible(self, h):
        return int(h) in self.visible


_had_u32_21 = hasattr(petmod, "_u32")
_orig_u32_21 = getattr(petmod, "_u32", None)
try:
    # 场景：往上先碰到一个**隐藏**的 message window(0xAA)，再往上才是**可见**的 0xBB
    petmod._u32 = _FakeU32([0xAA, 0xBB], visible=[0xBB])
    _got21 = petmod._first_window_above(0x1000)
    check("★行为：`_first_window_above` **跳过隐藏窗**（隐藏窗的 z 位置是残留的、不代表视觉层级）"
          "—— 先撞到隐藏的 0xAA 时，必须继续往上返回可见的 0xBB",
          _got21 == 0xBB, hex(_got21 or 0))
    petmod._u32 = _FakeU32([0xAA, 0xAB], visible=[])   # 上面全是隐藏窗
    check("★行为：…上面**全是隐藏窗**时返回 `None`（不许把隐藏窗当结论）",
          petmod._first_window_above(0x1000) is None)
finally:
    if _had_u32_21:
        petmod._u32 = _orig_u32_21
    else:
        del petmod._u32

# 21f. 行为层：离屏下 `_HAS_WIN32` 为假时，整套**空转**、绝不抛
_pet21 = new_pet(ALICE, at=(500, 300))
check("行为：`ensure_topmost_band()` 离屏（无 Windll）下返回 False 且**不抛**",
      _pet21.ensure_topmost_band() is False)
check("行为：看门狗表被 `showEvent` 起过（离屏也照起，只是回调空转）"
      "—— 但 `_HAS_WIN32` 为假时不该真的去调 Win32",
      isinstance(_pet21._top_band_timer.interval(), int)
      and _pet21._top_band_timer.interval() == petmod.PETS_TOP_BAND_MS)
_pet21.close()
qapp.processEvents()

# ============================================================================
# 22. 思考气泡（**第二款气泡**，2026-09-21）
# ============================================================================
# 规格：非 patpat 模式单击贴图 → 除形变 + `voices/normal_pet/`，旁边**依次淡入**三帧
#       `assets/icon/thinking_0/1/2.png`（各 100ms）→ 停留 1s → 淡出；位置与**聊天气泡同一套**
#       （左/上放不下 → 右/下），★翻过去时**整张画布镜像**。
# ★★ `thinking_fin.png` **不播放** —— 只用来定三帧的相对位置（用户拍板原话）。
print()
print("== 22. 思考气泡：三帧落点 / 逐帧淡入 / 镜像让位 / 只非 patpat 模式弹 ==")
from app import thinking as thinkmod  # noqa: E402

_think_src = inspect.getsource(petmod)

# ---- 22a. 素材与常量：**用真实 PNG 重算一遍**（换了素材这里就会红）----
_PIL_OK = True
try:
    from PIL import Image
except Exception:  # noqa: BLE001
    _PIL_OK = False

_ASSETS = petmod.ICONS
_fin_p = _ASSETS / thinkmod.THINKING_REF_FILE
check("★素材：`assets/icon/` 下三帧 `thinking_0/1/2.png` **都在**（缺一张就整套不弹）",
      len(thinkmod.thinking_frames(_ASSETS)) == 3,
      str([p.name for p in thinkmod.thinking_frames(_ASSETS)]))
check("★素材：参考图 `thinking_fin.png` 在（只用来量位置，不播放）", _fin_p.exists())
check("★`thinking_fin` **不在**播放清单里（用户口径「仅播放三帧」）",
      thinkmod.THINKING_REF_FILE not in thinkmod.THINKING_FRAME_FILES
      and all("fin" not in n for n in thinkmod.THINKING_FRAME_FILES))
check("★素材：目录不存在 / 缺文件时 `thinking_frames()` 返回 `[]`（不抛）",
      thinkmod.thinking_frames(BASE / "没有这个目录") == []
      and thinkmod.thinking_frames(None) == [])

if _PIL_OK:
    def _alpha_bbox(path):
        im = Image.open(str(path)).convert("RGBA")
        return im.size, im.getchannel("A").getbbox()

    def _components(path):
        """连通域（4 邻域）内容 bbox，按面积降序。"""
        im = Image.open(str(path)).convert("RGBA")
        w, h = im.size
        al = im.getchannel("A").load()
        seen = [[False] * w for _ in range(h)]
        out = []
        for y0 in range(h):
            for x0 in range(w):
                if seen[y0][x0] or al[x0, y0] == 0:
                    continue
                stack, seen[y0][x0], pts = [(x0, y0)], True, []
                while stack:
                    x, y = stack.pop()
                    pts.append((x, y))
                    for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                        if 0 <= nx < w and 0 <= ny < h and not seen[ny][nx] and al[nx, ny] > 0:
                            seen[ny][nx] = True
                            stack.append((nx, ny))
                xs = [p[0] for p in pts]
                ys = [p[1] for p in pts]
                out.append((len(pts), min(xs), min(ys), max(xs) + 1, max(ys) + 1))
        out.sort(reverse=True)
        return out

    _fin_size, _fin_bb = _alpha_bbox(_fin_p)
    check("★画布：`THINKING_CANVAS` == `thinking_fin.png` 的**实际尺寸**"
          "（fin 是画布基准；三帧的落点都相对它）",
          tuple(thinkmod.THINKING_CANVAS) == _fin_size,
          "%s vs %s" % (thinkmod.THINKING_CANVAS, _fin_size))

    _comps = _components(_fin_p)
    check("★fin 恰好有**三块**内容（大椭圆 + 中圆点 + 小圆点）—— 与三帧一一对应",
          len(_comps) == 3, str([(c[0], c[1:]) for c in _comps]))

    _frame_info = []
    for _i, _name in enumerate(thinkmod.THINKING_FRAME_FILES):
        _sz, _bb = _alpha_bbox(_ASSETS / _name)
        _frame_info.append((_name, _sz, _bb))

    _f_sizes = sorted((b[2] - b[0], b[3] - b[1]) for _, _, b in _frame_info)
    _c_sizes = sorted((c[3] - c[1], c[4] - c[2]) for c in _comps)
    check("★★素材：三帧的**内容尺寸**与 fin 三块内容的尺寸**逐一相等**"
          "（这正是「它们就是同一套图层」的判据，也是落点的推导依据）",
          _f_sizes == _c_sizes, "%s vs %s" % (_f_sizes, _c_sizes))

    _comp_boxes = {(c[1], c[2], c[3], c[4]) for c in _comps}
    _landed = []
    for _i, (_name, _sz, _bb) in enumerate(_frame_info):
        _dx, _dy = thinkmod.THINKING_OFFSETS[_i]
        _landed.append((_bb[0] + _dx, _bb[1] + _dy, _bb[2] + _dx, _bb[3] + _dy))
    check("★★落点：每帧按 `THINKING_OFFSETS` 摆上去之后，**内容 bbox 正好落在 fin 的某一块上**"
          "（不是「差不多」，是**完全对齐**）",
          all(box in _comp_boxes for box in _landed),
          str(_landed))
    _tip_pt = (_landed[0][2], _landed[0][3])
    check("★尾尖：`THINKING_TAIL_TIP` == **第 0 帧**（最外侧小圆点）内容 bbox 的右下角"
          "—— 它就是贴着贴图的那一点，要和锚点重合",
          tuple(thinkmod.THINKING_TAIL_TIP) == _tip_pt,
          "%s vs %s" % (thinkmod.THINKING_TAIL_TIP, _tip_pt))
    check("★画布：三帧落点 + fin 内容 bbox 的关系自洽（第 2 帧大椭圆 = fin 最大那块）",
          list(_landed[2]) == list(_comps[0][1:]), "%s vs %s" % (_landed[2], _comps[0][1:]))
    _union = (min(b[0] for b in _landed), min(b[1] for b in _landed),
              max(b[2] for b in _landed), max(b[3] for b in _landed))
    check("★画布：三帧内容并集的 bbox == fin 内容 bbox（整张图就是这三块拼起来的）",
          _union == _fin_bb, "%s vs %s" % (_union, _fin_bb))

# ---- 22b. 时序常量 ----
check("★时序：每帧淡入 100ms（用户口径「每个淡入时长 100ms」）",
      thinkmod.THINKING_FADE_MS == 100, str(thinkmod.THINKING_FADE_MS))
check("★时序：三帧淡入合计 = 3 × 100 = 300ms（依次错开的驱动时长）",
      thinkmod.THINKING_IN_TOTAL_MS == 300
      and thinkmod.THINKING_IN_TOTAL_MS == thinkmod.THINKING_FADE_MS * 3,
      str(thinkmod.THINKING_IN_TOTAL_MS))
check("★时序：三帧全亮后停留 **1.5s** —— ★★2026-09-29 由 1s 加长：用户口径「**气泡的显示时长**"
      "与连点时一次内容显示时长设为一致」⇒ `1500 = 2000（= 连点节拍/窗口）− 淡入 300 − 淡出 200`",
      thinkmod.THINKING_HOLD_MS == 1500, str(thinkmod.THINKING_HOLD_MS))
check("★★时序：**一轮寿命 == 连点窗口 == 换句节拍（三个 2s 对齐）** ——"
      "★这条钉的是**推导口径**、不是数值复述：三者只有相等，「气泡消失后再点」才不会掉进"
      "「时间上仍算连点、气泡却已经没了」的两难区间（2026-09-29 用户报的「再点还是上一条」就长在那）",
      thinkmod.THINKING_LIFE_MS
      == thinkmod.THINKING_IN_TOTAL_MS + thinkmod.THINKING_HOLD_MS + thinkmod.THINKING_OUT_MS
      and thinkmod.THINKING_LIFE_MS == thinkmod.THINKING_MASH_MS
      and thinkmod.THINKING_LIFE_MS == thinkmod.THINKING_SWITCH_MS,
      "life %s / mash %s / switch %s" % (thinkmod.THINKING_LIFE_MS,
                                         thinkmod.THINKING_MASH_MS,
                                         thinkmod.THINKING_SWITCH_MS))
check("★时序：淡出与聊天气泡同值（`BUBBLE_FADE_MS`）—— 观感一致",
      thinkmod.THINKING_OUT_MS == petmod.BUBBLE_FADE_MS,
      "%s vs %s" % (thinkmod.THINKING_OUT_MS, petmod.BUBBLE_FADE_MS))
check("★时序：连点判定窗口 `THINKING_MASH_MS` = **2000ms**（用户口径「把 1.5s 改为两秒」）—— 23 段的"
      "「续命」断言**由这个窗口推导**（= 窗口 × 0.75），窗口被改回去不但语义错、偏移还会落到窗口外让"
      "那条断言**实效成假绿** ⇒ 数值本身必须在这里单独钉死",
      thinkmod.THINKING_MASH_MS == 2000, str(thinkmod.THINKING_MASH_MS))
check("★让位：迟滞 / 平移动画时长**与聊天气泡同值**（用户口径「与第一款一样」）",
      thinkmod.THINKING_FLIP_HYST == petmod.BUBBLE_FLIP_HYST
      and thinkmod.THINKING_FLIP_MS == petmod.BUBBLE_FLIP_MS,
      "hyst %s/%s  ms %s/%s" % (thinkmod.THINKING_FLIP_HYST, petmod.BUBBLE_FLIP_HYST,
                                thinkmod.THINKING_FLIP_MS, petmod.BUBBLE_FLIP_MS))

# ---- 22c. 逐帧淡入曲线（**纯函数**：三帧依次起淡，各线性爬 100ms）----
# ⚠️ `1/3` / `2/3` 在二进制里除不尽：`(1/3) * 300 / 100 = 0.9999999999999999`，
#   逐项裸 `== [1.0, 0.0, 0.0]` 会**假红**（值本身是对的，只差 1.1e-16）。所以量到 9 位再比。
def _curve(progress):
    return [round(thinkmod.thinking_frame_opacity(progress, i), 9) for i in range(3)]


check("★淡入曲线：progress=0 → 三帧全 0", _curve(0.0) == [0.0, 0.0, 0.0])
check("★淡入曲线：progress=1/3 → 只有第 0 帧满了（第 1 帧**刚好**开始）",
      _curve(1 / 3) == [1.0, 0.0, 0.0])
check("★淡入曲线：progress=2/3 → 第 0、1 帧满、第 2 帧刚开始（**层层叠加**，不是替换）",
      _curve(2 / 3) == [1.0, 1.0, 0.0])
check("★淡入曲线：progress=1 → 三帧全满", _curve(1.0) == [1.0, 1.0, 1.0])
check("★淡入曲线：**线性**（progress=1/6 → 第 0 帧正好 0.5；带 easing 就不是 100ms 了）",
      abs(thinkmod.thinking_frame_opacity(1 / 6, 0) - 0.5) < 1e-9,
      str(thinkmod.thinking_frame_opacity(1 / 6, 0)))
check("★淡入曲线：越界 index 返回 0（不抛）",
      thinkmod.thinking_frame_opacity(1.0, -1) == 0.0
      and thinkmod.thinking_frame_opacity(1.0, 3) == 0.0)
check("★淡入曲线：progress 越界会被夹紧（不出现 >1 或 <0 的不透明度）",
      thinkmod.thinking_frame_opacity(5.0, 0) == 1.0
      and thinkmod.thinking_frame_opacity(-5.0, 2) == 0.0)

# ---- 22d. 尾尖 / 帧矩形：**整体镜像**（用户口径「对应变化」= 镜像）----
_W, _H = thinkmod.THINKING_CANVAS
_off = thinkmod.THINKING_OFFSETS
_szs = [(42, 36), (38, 30), (240, 165)]     # 与真实 PNG 一致（22a 已核过尺寸关系）


def _tip(side, face):
    return thinkmod.thinking_tail_tip(side, face)


def _rect(i, side, face):
    return thinkmod.thinking_frame_rect(i, side, face, sizes=_szs)


check("★尾尖：左+下 → (220, 219)；左+上 → y 镜像成 9；右+下 → x 镜像成 28；右+上 → (28, 9)",
      _tip("left", "down") == (220, 219) and _tip("left", "up") == (220, _H - 219)
      and _tip("right", "down") == (_W - 220, 219)
      and _tip("right", "up") == (_W - 220, _H - 219),
      "%s %s %s %s" % (_tip("left", "down"), _tip("left", "up"),
                       _tip("right", "down"), _tip("right", "up")))
check("★帧矩形（左+下）= 常量里那三个落点（基准朝向就是量出来的那一套）",
      [_rect(i, "left", "down") for i in range(3)]
      == [(186, 193, 42, 36), (156, 166, 38, 30), (5, -1, 240, 165)],
      str([_rect(i, "left", "down") for i in range(3)]))
check("★★镜像口径：翻到右侧 = 每帧 `x → W − x − w`（整个画布左右翻，三帧跟着反过去）",
      [_rect(i, "right", "down") for i in range(3)]
      == [(_W - _off[i][0] - _szs[i][0], _off[i][1], _szs[i][0], _szs[i][1]) for i in range(3)],
      str([_rect(i, "right", "down") for i in range(3)]))
check("★★镜像口径：翻到下方 = 每帧 `y → H − y − h`（整个画布上下翻）",
      [_rect(i, "left", "up") for i in range(3)]
      == [(_off[i][0], _H - _off[i][1] - _szs[i][1], _szs[i][0], _szs[i][1]) for i in range(3)],
      str([_rect(i, "left", "up") for i in range(3)]))
check("★★镜像口径：右下 = 两个轴都翻（不是只翻一个）",
      [_rect(i, "right", "up") for i in range(3)]
      == [(_W - _off[i][0] - _szs[i][0], _H - _off[i][1] - _szs[i][1],
           _szs[i][0], _szs[i][1]) for i in range(3)],
      str([_rect(i, "right", "up") for i in range(3)]))

# ---- 22e. 落点 = 锚点 − 尾尖（与聊天气泡**同一个贴合点**）----
check("★位置：`thinking_pos` = 锚点 − 尾尖（尾巴尖与聊天气泡的锚点 A 重合）",
      thinkmod.thinking_pos((500, 300), "left", "down") == (280, 81)
      and thinkmod.thinking_pos((500, 300), "right", "down") == (472, 81)
      and thinkmod.thinking_pos((500, 300), "left", "up") == (280, 291),
      str(thinkmod.thinking_pos((500, 300), "left", "down")))
check("★位置：画布比可见内容大一圈 ⇒ 窗口左上角是**负坐标**（这就是它必须是独立顶层窗的原因）",
      thinkmod.thinking_pos((0, 0), "left", "down")[0] < 0
      and thinkmod.thinking_pos((0, 0), "left", "down")[1] < 0)
_pet_a = new_pet(ALICE, at=(700, 500))
_anchor_down = petmod.bubble_anchor(_pet_a._sprite_rect().x(), _pet_a._sprite_rect().y(),
                                    _pet_a._sprite_rect().width(),
                                    _pet_a._sprite_rect().height(),
                                    side="left", face="down")
check("★★位置：`_thinking_anchor_of` 用的就是**聊天气泡那一个** `bubble_anchor`"
      "（「整体位置与第一款一样」—— 构造上就成立，不是另抄一份 5/7）",
      tuple(_pet_a._thinking_anchor_of("left", "down")) == tuple(_anchor_down),
      "%s vs %s" % (_pet_a._thinking_anchor_of("left", "down"), _anchor_down))
_pet_a.close()

# ---- 22f. 让位（左/上放不下 → 右/下）：四档 + 迟滞 + 兜底 ----
_scr = QRect(0, 0, 1000, 800)
check("★让位·横向：锚点左边**够 220px** → 保持左侧",
      thinkmod.thinking_side(_scr, 300, "left") == "left")
check("★让位·横向：左边不够、右边够 → 翻到**右侧**",
      thinkmod.thinking_side(_scr, 100, "left") == "right")
check("★让位·横向：**两边都不够** → 保持左侧（往右让只是把气泡推出屏幕，不如不动）",
      thinkmod.thinking_side(QRect(0, 0, 200, 800), 100, "left") == "left")
check("★让位·横向·迟滞：已经在右侧时，左侧要**多出 20px** 才回去（贴边来回拖不来回翻）",
      thinkmod.thinking_side(_scr, 220, "left") == "left"
      and thinkmod.thinking_side(_scr, 220, "right") == "right"
      and thinkmod.thinking_side(_scr, 240, "right") == "left")
check("★让位·纵向：锚点上方**够 219px** → 尾巴朝下（气泡挂在上边）",
      thinkmod.thinking_face(_scr, 400, "down") == "down")
check("★让位·纵向：上方不够、下方够 → 翻到**下方**（尾巴朝上）",
      thinkmod.thinking_face(_scr, 100, "down") == "up")
check("★让位·纵向·迟滞：已经在下方时，上方要多出 20px 才回去",
      thinkmod.thinking_face(_scr, 220, "down") == "down"
      and thinkmod.thinking_face(_scr, 220, "up") == "up"
      and thinkmod.thinking_face(_scr, 240, "up") == "down")
check("★让位：两个方向的判据都只看「左 / 上够不够」（与 `bubble_face` 同口径："
      "问的永远是「如果朝下，上方够不够」，而不是拿当前朝向的锚点去问）",
      "FACE_DOWN" in inspect.getsource(thinkmod.thinking_face)
      and "FACE_UP" in inspect.getsource(thinkmod.thinking_face))

# ---- 22g. 行为层：非 patpat 单击才弹 / patpat 模式不弹 / 缺素材不弹 ----
_pet22 = new_pet(ALICE, at=(600, 400))
check("行为：初始没弹（要单击才叫出来）", not _pet22.is_thinking_shown())
check("行为：三帧被懒加载出来（`assets/icon/` 下都在）", len(_pet22._thinking_pixmaps()) == 3,
      str(len(_pet22._thinking_pixmaps())))

_pet22._patpat = True
check("★★行为：**patpat 模式开着**时单击 → `_thinking_play()` 返回 False、**不弹**"
      "（用户口径「在**非 patpat 模式**时单击」；那一支由那只手负责，两者不叠）",
      _pet22._thinking_play() is False and not _pet22.is_thinking_shown())
_pet22._patpat = False
check("★行为：**非 patpat 模式**单击 → `_thinking_play()` 返回 True 且窗口显示出来",
      _pet22._thinking_play() is True and _pet22.is_thinking_shown())
check("★行为：刚弹出来时三帧都还没亮（不透明度全 0，随后才逐帧爬）",
      _pet22.thinking_frame_opacities() == [0.0, 0.0, 0.0],
      str(_pet22.thinking_frame_opacities()))

# ★★ 位置自洽：窗口实际落点 == `thinking_pos(锚点, 当前朝向, scale)`
# ⚠️ 二十三改·二轮起必须带 `scale=`：气泡缩到 0.5 倍后，尾尖到左上角的距离也跟着缩，
#    不带 scale 就差了整整一个「缩放后尾尖」，位置自洽这条会假红。
_ov22 = _pet22._thinking_ov
_ax, _ay = _pet22._thinking_anchor_of(_ov22.side(), _ov22.face())
_exp_pos = thinkmod.thinking_pos((_ax, _ay), _ov22.side(), _ov22.face(),
                                 scale=_ov22.scale())
check("★★行为：窗口**实际落点** == `thinking_pos(锚点, 当前朝向, scale)`"
      "（位置公式与真机摆位是同一条，不是各算各的）",
      (_ov22.x(), _ov22.y()) == _exp_pos,
      "%s vs %s" % ((_ov22.x(), _ov22.y()), _exp_pos))
check("★行为：画布尺寸 == `thinking_canvas_size(scale)`（= 基准画布 × 贴图缩放比例）",
      (_ov22.width(), _ov22.height()) == thinkmod.thinking_canvas_size(_ov22.scale()),
      str(((_ov22.width(), _ov22.height()), _ov22.scale())))

# 逐帧淡入真的在推进
check("★★行为：等一拍之后第 0 帧先亮起来（**逐帧**，不是三帧一起）",
      _pump_until(lambda: _pet22.thinking_frame_opacities()[0] > 0.0, 1.0))
check("★★行为：最终三帧全亮（`_on_in_done` 把三帧钉到 1.0）",
      _pump_until(lambda: _pet22.thinking_frame_opacities() == [1.0, 1.0, 1.0], 1.0),
      str(_pet22.thinking_frame_opacities()))

# ---- 23 改：连点**不再**截断重播（原地续命 + 每 2s 换句）----
_pet22._thinking_play()
check("★★行为（二十三改）：**连点不重放三帧**（帧保持全亮、不会被打回 0 再重来）——"
      "用户口径「连点过程中每两秒随机切换内容」",
      _pet22.thinking_frame_opacities() == [1.0, 1.0, 1.0]
      and _pet22.is_thinking_shown(),
      str(_pet22.thinking_frame_opacities()))

# 停留 1s 后整体淡出 → 自动收
check("★★行为：停留后**整体淡出**（整体不透明度掉到 1 以下）",
      _pump_until(lambda: _pet22.thinking_opacity() < 1.0, 3.0),
      str(_pet22.thinking_opacity()))
check("★★行为：淡完之后**自己收掉**（不会永久留在桌面上）",
      _pump_until(lambda: not _pet22.is_thinking_shown(), 2.0))
check("★行为：收掉之后整体不透明度回到 1.0（下一轮从干净状态开始）",
      _pet22.thinking_opacity() == 1.0)

# ---- 23 改：`_patpat_stop()` **不再**收气泡（它每次单击都会走，收了就打断连点）----
# 真正要收的四个出口（关模式 / 换角色 / 切节能 / 关窗）各自显式调 `_thinking_dismiss()`。
_pet22._thinking_play()
_pump_until(lambda: _pet22.thinking_frame_opacities() == [1.0, 1.0, 1.0], 1.0)
_pet22._patpat_stop()
check("★★行为（二十三改）：`_patpat_stop()` **不收**思考气泡（每次单击都会经过它 —— "
      "在那儿收掉就等于连点被打断）", _pet22.is_thinking_shown())
_pet22._thinking_dismiss()
check("★行为：真正的出口 `_thinking_dismiss()` 能把它收掉（安全网没丢）",
      not _pet22.is_thinking_shown())

# 缺素材 → 不弹（但也不抛）
_keep22 = _pet22._thinking_pm
_pet22._thinking_pm = []
check("★行为：**缺素材**时 `_thinking_play()` 返回 False 且不抛（只当没这回事）",
      _pet22._thinking_play() is False)
_pet22._thinking_pm = _keep22

# ---- 22h. 位置跟随：贴图动了气泡跟着走 ----
_pet22._thinking_play()
_pump_until(lambda: _pet22.is_thinking_shown(), 0.5)
_before = (_pet22._thinking_ov.x(), _pet22._thinking_ov.y())
_pet22.move(_pet22.x() - 40, _pet22.y() - 30)
qapp.processEvents()
_after = (_pet22._thinking_ov.x(), _pet22._thinking_ov.y())
check("★行为：贴图挪了 → 思考气泡跟着挪（`_sync_bubble` 里接了 `_thinking_follow`）",
      _after != _before, "%s -> %s" % (_before, _after))
_pet22.close()
qapp.processEvents()

# ---- 22i. 结构层（AST / 源码）----
# ⚠️ **别用 `src.index("_patpat_play")` 比先后** —— `mouseReleaseEvent` 的**注释里**也出现过
#    `_patpat_play()`（「没有位移的『点击』走 `_patpat_play()`」那一句），`index()` 会命中注释、
#    于是「把两句调换顺序」也照样绿（反向验证 B 例实测：0 红，纯摆设）。⇒ 用 **AST 按行号**取真实调用顺序。
def _call_order22(src, class_name, method_name, names):
    """AST：`class.method` 里 `self.<name>()` 那几次调用的**源码先后顺序**。"""
    fn = _method_node(src, class_name, method_name)
    if fn is None:
        return None
    hits = []
    for n in ast.walk(fn):
        if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                and isinstance(n.func.value, ast.Name) and n.func.value.id == "self"
                and n.func.attr in names):
            hits.append((n.lineno, n.func.attr))
    return [nm for _, nm in sorted(hits)]


def _self_calls22(src, class_name, method_name):
    """AST：`class.method` 里**真实发生**的 `self.<name>()` 调用名（★不看注释、不看字符串）。

    返回形如 `["_patpat_stop", "_thinking_ov.hide_now", …]`；属性链取 `属性.方法` 两段，
    这样「到底调了思考气泡的哪个方法」也一眼看得出。
    """
    fn = _method_node(src, class_name, method_name)
    out = []
    if fn is None:
        return out
    for n in ast.walk(fn):
        if not (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)):
            continue
        v = n.func.value
        if isinstance(v, ast.Name) and v.id == "self":
            out.append(n.func.attr)
        elif (isinstance(v, ast.Attribute) and isinstance(v.value, ast.Name)
              and v.value.id == "self"):
            out.append("%s.%s" % (v.attr, n.func.attr))
    return out


def _startswith_thinking(calls):
    """从 `_self_calls22` 的结果里挑出「碰思考气泡」的那几个（`_thinking_*` / `_thinking_ov.*`）。"""
    return [c for c in calls if c.startswith("_thinking")]


_ord22 = _call_order22(_SRC19, "PetWindow", "mouseReleaseEvent",
                       ("_patpat_play", "_thinking_play"))
check("★★接线：`mouseReleaseEvent` 里 `self._thinking_play()` 排在 `self._patpat_play()` **之后**"
      "（形变与音效先在，气泡随后 —— 顺序反了的话 `_patpat_play` 第一句 `_patpat_stop()` "
      "会立刻把刚弹出的气泡收掉）",
      _ord22 == ["_patpat_play", "_thinking_play"], str(_ord22))
_tp22 = inspect.getsource(petmod.PetWindow._thinking_play)
check("★★结构：`_thinking_play()` 的**第一道守卫**就是「patpat 模式开着 → 不弹」",
      "_patpat" in _tp22.split("\n")[0] or "if self._patpat" in _tp22,
      _tp22.strip().split("\n")[0][:60])
check("★★结构（二十三改）：`_patpat_stop()` 里**没有**任何 `_thinking*` 的**真实调用** —— "
      "它每次单击都会走，收了就把连点打断。★走 AST 查调用（新注释里正解释这件事，"
      "纯字符串匹配会被自己的注释骗绿）",
      not any(_startswith_thinking(_self_calls22(_SRC19, "PetWindow", "_patpat_stop"))),
      str(_self_calls22(_SRC19, "PetWindow", "_patpat_stop")))
for _exit_m in ("set_patpat", "set_pet_dir", "set_power_save"):
    check("★结构：出口 `%s()` 显式调 `_thinking_dismiss()`（收气泡的四处之一）" % _exit_m,
          _calls_name(_SRC19, "PetWindow", _exit_m, "_thinking_dismiss"),
          str(_self_calls22(_SRC19, "PetWindow", _exit_m)))
check("★结构：`_thinking_dismiss()` 就是 `_thinking_ov.hide_now()`",
      _calls_name(_SRC19, "PetWindow", "_thinking_dismiss", "hide_now"))
check("★结构：`closeEvent` 里 `hide_now()` + `close()` 都做了（独立顶层窗不跟着父窗关）",
      "_thinking_ov.hide_now()" in inspect.getsource(petmod.PetWindow.closeEvent)
      and "_thinking_ov.close()" in inspect.getsource(petmod.PetWindow.closeEvent))
check("★结构：`_sync_bubble()` 里接了 `_thinking_follow()`（拖动时跟着走）",
      "_thinking_follow" in inspect.getsource(petmod.PetWindow._sync_bubble))
_paint22 = inspect.getsource(petmod._ThinkingOverlay.paintEvent)
_ov_src22 = inspect.getsource(petmod._ThinkingOverlay)


def _constructs(src, names):
    """AST：源码里有没有**真的构造 / 调用**这几个名字（`Name(...)` 或 `obj.Name(...)`）。

    ⚠️ 只认 `ast.Call`：类文档里写着「**不挂** `QGraphicsOpacityEffect`」是**自述**，
    纯字符串匹配会把那句注释放成「挂了」——本文件正好踩过（见 3360 行同款教训）。
    """
    hits = []
    for n in ast.walk(ast.parse(src)):
        if isinstance(n, ast.Call):
            f = n.func
            nm = (f.id if isinstance(f, ast.Name)
                  else f.attr if isinstance(f, ast.Attribute) else "")
            if nm in names:
                hits.append(nm)
    return hits


check("★★结构：镜像在**绘制链**上做（`translate` + `scale(-1, 1)`），不是「重算一遍帧位置再画」"
      "—— 保证「整张画布镜像」只有一处真值",
      "translate" in _paint22 and "scale" in _paint22
      and ("-1.0, 1.0" in _paint22 or "-1, 1" in _paint22))
check("★结构：淡入淡出只走 `paintEvent` 的 `setOpacity`，**不构造** `QGraphicsOpacityEffect` / "
      "**不调** `setWindowOpacity`（与 `_PetBubble` 同一条绘制链；挂了 effect 会和镜像变换打架）",
      "setOpacity" in _paint22
      and not _constructs(_ov_src22, ("QGraphicsOpacityEffect", "setWindowOpacity")),
      str(_constructs(_ov_src22, ("QGraphicsOpacityEffect", "setWindowOpacity"))))
check("★结构：驱动动画用 **`QEasingCurve.Linear`**（带 easing 的话每帧就不是精确 100ms 了）",
      "QEasingCurve.Linear" in _ov_src22)
check("★结构：叠加窗三个属性都在（透明底 / 不吃点击 / 不抢焦点）—— 与那只手同款",
      "WindowTransparentForInput" in _ov_src22
      and "WA_TranslucentBackground" in _ov_src22
      and "WA_ShowWithoutActivating" in _ov_src22)
check("★结构：`_ThinkingOverlay` 在 `PetWindow.__init__` 里被建出来，锚点回调 = `_thinking_anchor_of`",
      "_ThinkingOverlay(anchor_of=self._thinking_anchor_of)" in _think_src)
_mk_src22 = inspect.getsource(petmod.PetWindow._thinking_pixmaps)
check("★结构：`thinking_fin` **不参与**播放（`_thinking_pixmaps` 走 `thinking_frames()` —— "
      "它只吐 `THINKING_FRAME_FILES` 那三帧，`THINKING_REF_FILE` 根本不进素材清单）",
      "thinking_frames(" in _mk_src22 and "THINKING_REF_FILE" not in _mk_src22
      and "_thinking_pixmaps" in _think_src)
# ⚠️ 这条行为层抓不到：驱动动画走到 progress=1.0 时曲线本来就给出三帧全 1.0，`_on_in_done` 那一下是**兜底**
#    （末帧万一不是恰好 1.0 / 动画被提前 `_stop_all()` 掉）。与音量条 `_sync_children()` 同款 —— 只能结构层钉。
_src_in_done22 = inspect.getsource(petmod._ThinkingOverlay._on_in_done)
check("★★结构：`_on_in_done()` 里**把三帧钉到 1.0**（`self._ops = [1.0] * …`）—— 兜底：末帧万一不是"
      "恰好 1.0 / 动画被提前停（行为层抓不到，同音量条 `_sync_children()` 那条，别删）",
      "self._ops = [1.0] * len(self._frames)" in _src_in_done22,
      _src_in_done22.strip().split("\n")[0][:80])

# ---- 22j. 渲染层：三帧叠加 == 真实 `thinking_fin.png`（四个朝向 IoU）----
if _PIL_OK:
    import numpy as _np
    _pms22 = [QPixmap(str(_ASSETS / n)) for n in thinkmod.THINKING_FRAME_FILES]
    _ov_r = petmod._ThinkingOverlay(anchor_of=lambda s, f: (0, 0))
    _ov_r.set_frames(_pms22)

    def _render22(side, face):
        _ov_r._side, _ov_r._face = side, face
        _ov_r._ops = [1.0] * 3
        _ov_r._opacity = 1.0
        im = QImage(_ov_r.width(), _ov_r.height(), QImage.Format_ARGB32)
        im.fill(Qt.transparent)
        _ov_r.render(im)
        im = im.convertToFormat(QImage.Format_RGBA8888)
        arr = _np.frombuffer(im.constBits(), dtype=_np.uint8).reshape(
            im.height(), im.bytesPerLine() // 4, 4)
        return arr[:, :im.width(), :].copy()

    _fin_arr = _np.array(Image.open(str(_fin_p)).convert("RGBA"))
    _ious = []
    for _s in ("left", "right"):
        for _f in ("down", "up"):
            _rr = _render22(_s, _f)
            _ee = _np.flip(_fin_arr, axis=1) if _s == "right" else _fin_arr
            _ee = _np.flip(_ee, axis=0) if _f == "up" else _ee
            _ra, _ea = _rr[:, :, 3] > 0, _ee[:, :, 3] > 0
            _u = int((_ra | _ea).sum())
            _ious.append(int((_ra & _ea).sum()) / _u if _u else 1.0)
    check("★★渲染：三帧**层层叠加**画出来的结果 == 真实 `thinking_fin.png`"
          "（四个朝向的 alpha IoU 都 ≥ 0.97 ⇒ 落点对、镜像也对）",
          all(v >= 0.97 for v in _ious),
          str([round(v, 4) for v in _ious]))
    _ov_r.close()

# ============================================================================
# 23. 思考气泡 · 二十三改：跟着贴图等比缩放 + 放文字（第一类/第二类）+ 连点每 2s 换句
# ============================================================================
# 用户口径（2026-09-21）原文要点：
#   ① 气泡大小「和角色贴图一样宽高按比例修改」⇒ **二轮明确口径**：贴图原图 300×500、桌面
#      显示 150×250 ⇒ 气泡按**同一个比例**（显示宽 ÷ 原图宽 = 0.5）缩小；
#   ② 第一类 = 余额 / 峰谷倒计时（★2026-09-27 起：「今日 token 用量」已按用户要求**整项去掉**，
#      用户原话「今日 token 用量的显示不准确，直接将这项显示内容去掉，其他内容保留」），
#      **只在 API 是 deepseek 时显示**；
#   ③ 第二类 = 角色台词；第一类 2 句 + 台词 2 句 ⇒ 池子 4 句，每次单击随机 1 句；
#   ④ 连点期间**每两秒**随机切换内容，切换次数**只由时间决定**（不是点击次数）；
#   ⑤ 停手后回到普通「停 1s → 淡出」；
#   ⑥ **二轮**：字体适当增大（且数值行 > 标签行）；文字**自己**淡入淡出 —— 三帧全亮后立即
#      100ms 淡入、淡出跟着气泡、连点换句 = 旧字瞬灭 + 新字 100ms 淡入（这 100ms 计入那 2s）。
print()
print("== 23. 思考气泡（二十三改）：等比缩放 / 内容池 / 文字不镜像 / 连点 2s 换句 ==")
import datetime  # noqa: E402
from app import stats as statmod  # noqa: E402

# ---- 23a. 缩放：纯函数（★二轮口径：比例 = 贴图**显示宽 ÷ 原图宽**）----
check("★★缩放（二轮）：爱丽丝的比例 **0.5**（原图 300×500 → 在屏 150×250）⇒ 气泡画布"
      "缩到 **124×114**（248×228 × 0.5）—— 用户口径「也要按相同的比例进行尺寸的缩小后显示」",
      abs(thinkmod.thinking_scale(0.5) - 0.5) < 1e-9
      and thinkmod.thinking_canvas_size(thinkmod.thinking_scale(0.5)) == (124, 114),
      str(thinkmod.thinking_canvas_size(thinkmod.thinking_scale(0.5))))
check("★缩放：比例 1.0 ⇒ 画布仍是 `THINKING_CANVAS`（248×228，文字一起缩）",
      thinkmod.thinking_scale(1.0) == 1.0
      and thinkmod.thinking_canvas_size(thinkmod.thinking_scale(1.0)) == tuple(thinkmod.THINKING_CANVAS),
      str(thinkmod.thinking_canvas_size(thinkmod.thinking_scale(1.0))))
check("★缩放：比例取不到 / 非正数 ⇒ **退化回 1.0**（绝不返回 0 —— 那会让窗口变 0×0、整条气泡消失）",
      thinkmod.thinking_scale(0) == 1.0 and thinkmod.thinking_scale(None) == 1.0
      and thinkmod.thinking_scale("x") == 1.0 and thinkmod.thinking_scale(-5) == 1.0)
check("★缩放：`thinking_pos` 减的是**缩放后**的尾尖（0.5× 时 220×219 → 110×110）",
      thinkmod.thinking_pos((500, 300), "left", "down", scale=0.5) == (390, 190)
      and thinkmod.thinking_pos((500, 300), "left", "down", scale=0.4) == (412, 212),
      str(thinkmod.thinking_pos((500, 300), "left", "down", scale=0.5)))


def _imports_pet23(src):
    """AST：`src` 里有没有 import 到 `pet` 模块（★不看注释 / 字符串）。"""
    for n in ast.walk(ast.parse(src)):
        if isinstance(n, ast.ImportFrom) and (n.module or "").split(".")[-1] == "pet":
            return True
        if isinstance(n, ast.Import):
            for al in n.names:
                if al.name.split(".")[-1] == "pet":
                    return True
    return False


def _roll_avoid23(src):
    """AST：`_ThinkingOverlay._roll_content()` 那次 `pick_content(...)` 的 `avoid=` **最终指向
    `self._content`**（直接传 / 经一个本地别名中转，两种写法都认）。

    ★为什么不能只查「有 `avoid=` 这个关键字」：传成 `None`、或传成别的变量，就**退化成没有排除**
      —— 而**行为层抓不到**（池子 4 条时几乎不重复，只有池子剩 2 条时才现形）。
    ★为什么钉「指向 `self._content`」而不是某个形参名：`_stop_all()` **从不碰** `_content`
      ⇒ 连点链路上它一直是「上一次显示的那一句」；换成别的字段就丢了这个语义。
    """
    fn = _method_node(src, "_ThinkingOverlay", "_roll_content")
    if fn is None:
        return False

    def _direct(node):
        return any(isinstance(s, ast.Attribute) and s.attr == "_content"
                   and isinstance(s.value, ast.Name) and s.value.id == "self"
                   for s in ast.walk(node))

    alias = {t.id for n in ast.walk(fn)
             if isinstance(n, ast.Assign) and _direct(n.value)
             for t in n.targets if isinstance(t, ast.Name)}

    def _is_prev(node):
        return _direct(node) or any(
            isinstance(s, ast.Name) and s.id in alias for s in ast.walk(node))

    for n in ast.walk(fn):
        if not isinstance(n, ast.Call):
            continue
        f = n.func
        nm = (f.attr if isinstance(f, ast.Attribute)
              else f.id if isinstance(f, ast.Name) else None)
        if nm != "pick_content":
            continue
        for k in n.keywords:
            if k.arg == "avoid" and _is_prev(k.value):
                return True
    return False


check("★★结构（二轮）：`app/thinking.py` **不** import `app.pet`（不反向依赖 ⇒ 比例只能由"
      "`PetWindow` 经 `set_scale_provider()` 注入；★旧口径那个写死的 `THINKING_REF_HEIGHT` 已删）",
      not _imports_pet23((BASE / "app" / "thinking.py").read_text(encoding="utf-8"))
      and not hasattr(thinkmod, "THINKING_REF_HEIGHT"))


def _mash_parts23(src):
    """AST：`_ThinkingOverlay.play()` 里赋给局部变量 `mash` 的那个表达式**用了哪些条件**。

    返回 `set`，元素是「`self.<attr>` 的属性名」+「大写的模块常量名」——
    也就是 `mash = (A and B and C and D)` 里的 `A/B/C/D` 各自认领的东西。

    ★为什么非要 AST：`play()` 的 docstring 与旁边注释里**逐字**解释着这条判据
      （「必须同时看时间与 `is_shown()`」），拿字符串搜 `is_shown` 会被**自己的注释**骗绿。
    """
    fn = _method_node(src, "_ThinkingOverlay", "play")
    if fn is None:
        return None
    expr = None
    for n in ast.walk(fn):
        if (isinstance(n, ast.Assign) and len(n.targets) == 1
                and isinstance(n.targets[0], ast.Name) and n.targets[0].id == "mash"):
            expr = n.value
    if expr is None:
        return None
    out = set()
    for n in ast.walk(expr):
        if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.value.id == "self":
            out.add(n.attr)
        elif isinstance(n, ast.Name) and n.id.isupper():
            out.add(n.id)
    return out


check("★★结构：`play()` 的「连点」判据里**必须同时**含 `self.is_shown()` ——"
      "★2026-09-29：只有「距上次点击 ≤ 2s」时，气泡收掉后那 300ms 里点一下仍会被当成连点 ⇒"
      "**不重新抽句**（真机实测「甲 → 甲」）。这条用 AST 取 `mash = (...)` 那个表达式的真实条件，"
      "类 docstring / 注释里正逐字解释这件事，字符串搜会被自己骗绿",
      _mash_parts23(_SRC19) == {"_mash_origin", "has_frames", "is_shown", "THINKING_MASH_MS"},
      str(_mash_parts23(_SRC19)))

# ---- 23b. 内容池：第一类 2 句 + 台词（★按角色分表）----
# ★2026-09-27：用户报「今日 token 用量显示不准确」⇒ 拍板「直接将这项显示内容去掉，其他内容保留」
#   ⇒ 第一类 3 句 → **2 句**（余额 / 峰谷），「今日 Token」那句连同它的常量与格式化函数**一起删掉**。
_pool_ds = thinkmod.thinking_pool(deepseek=True, balance=12.3456,
                                  state="peak", seconds_left=3661, role_key="alice")
_pool_no = thinkmod.thinking_pool(deepseek=False, balance=12.3456,
                                  state="peak", seconds_left=3661, role_key="alice")
check("★★内容池：deepseek + 爱丽丝 = **4 句**（第一类 2 句 + 台词 2 句）",
      len(_pool_ds) == 4, str([p[1] for p in _pool_ds]))
check("★★内容池：**非 deepseek 时第一类整类不进池子**（只剩 2 句台词）——"
      "用户口径「仅在使用的 api 为 deepseek 模型时会显示」",
      len(_pool_no) == 2 and all(p[0] == "line" for p in _pool_no),
      str([p[1] for p in _pool_no]))
check("★★内容池：第一类是**拆成 2 句**的（余额 / 峰谷各 1 句，不是合成一块）——"
      "★「今日 Token」那句已于 2026-09-27 按用户要求**整项删除**",
      [p[0] for p in _pool_ds[:2]] == ["balance", "period"],
      str([p[0] for p in _pool_ds]))
check("★★内容池：**标签集合里没有「今日 Token 用量」**，且其余三项**一个都不能少**"
      "（★用集合相等，不是「不含」—— 防止哪天把余额或峰谷连带删了还判绿）",
      {p[1] for p in _pool_ds} == {"剩余余额", "当前为高峰时段", "光啊——！！", "邦邦卡邦"},
      str(sorted({p[1] for p in _pool_ds})))
check("★★内容池：**整项删除契约** —— `thinking_pool()` 签名里没有 `tokens`，且 "
      "`token_line` / `THINKING_KIND_TOKENS` / `_fmt_tokens` **都不存在**"
      "（★防将来有人把它加回来：用户口径是「**去掉**」，不是「换个算法算准」）",
      "tokens" not in inspect.signature(thinkmod.thinking_pool).parameters
      and not hasattr(thinkmod, "token_line")
      and not hasattr(thinkmod, "THINKING_KIND_TOKENS")
      and not hasattr(thinkmod, "_fmt_tokens"),
      str(sorted(inspect.signature(thinkmod.thinking_pool).parameters)))
_src_pet23 = (BASE / "app" / "pet.py").read_text(encoding="utf-8")
check("★★结构：`PetWindow._thinking_content()` 里**不再调** `stats.today_tokens()`"
      "（★「去掉显示」得连**取数**一起摘干净 —— 留着就是每次单击白读一次；"
      "AST 限定在 `PetWindow` 类里找，`pet.py` 里同名方法很多）",
      not _calls_name(_src_pet23, "PetWindow", "_thinking_content", "today_tokens"))
check("★内容池：数值格式 —— 余额 `12.35元`（两位）、峰谷倒计时 `01:01:01`",
      _pool_ds[0][2] == "12.35元" and _pool_ds[1][2] == "01:01:01",
      str([p[2] for p in _pool_ds[:2]]))
check("★内容池：峰谷标签随状态变（高峰 / 空闲）",
      _pool_ds[1][1] == "当前为高峰时段"
      and thinkmod.period_line("idle", 60)[1] == "当前为空闲时段",
      str([_pool_ds[1][1], thinkmod.period_line("idle", 60)[1]]))
check("★★内容池：取不到数时**占位但仍进池子** —— 池子大小不因一次请求失败而变（口径要稳）",
      len(thinkmod.thinking_pool(deepseek=True, role_key="alice")) == 4
      and thinkmod.balance_line(None)[2] == thinkmod.THINKING_UNKNOWN
      and thinkmod.period_line(None, None)[2] == thinkmod.THINKING_UNKNOWN,
      str(thinkmod.balance_line(None)))
check("★内容池：爱丽丝台词 == 用户给的两句；**艾莲留空**（用户拍板「暂不显示，之后再做补充」）"
      "⇒ 池子只有第一类 2 句",
      thinkmod.thinking_role_lines("alice") == ("光啊——！！", "邦邦卡邦")
      and thinkmod.thinking_role_lines("ellen") == ()
      and len(thinkmod.thinking_pool(deepseek=True, role_key="ellen")) == 2,
      str(thinkmod.thinking_role_lines("alice")))
check("★内容池：未知角色 ⇒ 空台词（不回退成爱丽丝那两句 —— 口癖不能串角色）",
      thinkmod.thinking_role_lines("没这个角色") == ()
      and thinkmod.thinking_role_lines(None) == ())
check("★抽签：空池子 ⇒ `None`（不抛）；非空 ⇒ 抽到的**一定在池子里**",
      thinkmod.pick_content([]) is None and thinkmod.pick_content(None) is None
      and all(thinkmod.pick_content(_pool_ds) in _pool_ds for _ in range(50)))

# ---- 23b-2. ★★2026-09-29 新增：抽签**排除上一条**（用户口径「仅把上一次显示的内容排除」）----
# 起因：无 API ⇒ 第一类「余额 / 峰谷」整类不进池子、只剩爱丽丝那 2 句台词（= `_pool_no`），
#   纯均匀随机下**连点重复概率 50%** —— 用户报「出现重复显示的概率极大」。
# ★这一段的「正对照」那条不能省：少了它，把 `pick_content` 写成 `return items[0]` 也全绿。
check("★★抽签：**排除上一条** —— 池子 ≥2 条时，`avoid=池子里某一条` **再也抽不到它**"
      "（用户口径「切换时把上一次显示的内容排除到随机的队列之外」）",
      all(thinkmod.pick_content(_pool_no, avoid=x) != x
          for x in _pool_no for _ in range(40)),
      str([p[1] for p in _pool_no]))

_seq29, _cur29 = [], None
for _i29 in range(100):                      # ★模拟连点 100 次：每次都把上一次那一句当 avoid
    _cur29 = thinkmod.pick_content(_pool_no, avoid=_cur29)
    _seq29.append(_cur29[1])
check("★★抽签：**连点 100 次相邻永不重复**（无 API ⇒ 池子 2 条 ⇒ 严格交替），"
      "且**两条都出现过**（不是只出其中一条）",
      all(_seq29[i] != _seq29[i + 1] for i in range(len(_seq29) - 1))
      and set(_seq29) == {p[1] for p in _pool_no},
      "".join(s[0] for s in _seq29))

_one29 = [thinkmod.balance_line(1.0)]
check("★★抽签：**池子只有 1 条时不能被排除成空** —— `avoid` 就是它自己，仍须返回它"
      "（★绝不返回 `None`：池子非空却拿不到内容 ⇒ 表象是「点了半天气泡里没字」，比重复更难查）",
      thinkmod.pick_content(_one29, avoid=_one29[0]) == _one29[0])

check("★抽签：`avoid` **不在池子里**（换角色 / deepseek 开关切换 ⇒ 池子变了）"
      "⇒ 等价于不排除，照常抽得到、不抛",
      all(thinkmod.pick_content(_pool_no, avoid=("line", "不存在的台词", "")) in _pool_no
          for _ in range(40)))

_seen29 = {thinkmod.pick_content(_pool_no)[1] for _ in range(80)}
check("★★抽签（**正对照**）：`avoid=None` 时**两条都出现过** —— 证明上面那条「恒交替」"
      "不是靠「永远返回第一条」蒙过去的（★少了这条，写成 `return items[0]` 也全绿）",
      _seen29 == {p[1] for p in _pool_no}, str(sorted(_seen29)))

check("★★接线（AST）：`_ThinkingOverlay._roll_content()` 那次 `pick_content(...)` **真的带了 "
      "`avoid=` 且最终指向 `self._content`**（★只核「调了 pick_content」没用 —— 不传 avoid 时"
      "行为层照样绿；只核「有 avoid= 这几个字」也没用 —— 传 `None` 同样绿）",
      _roll_avoid23(_src_pet23))

# ---- 23c. 峰谷：纯时间函数（官方 2026 口径）----
_MON_930 = datetime.datetime(2026, 9, 21, 9, 30)     # 周一
_MON_1200 = datetime.datetime(2026, 9, 21, 12, 0)
_MON_1430 = datetime.datetime(2026, 9, 21, 14, 30)
_MON_2000 = datetime.datetime(2026, 9, 21, 20, 0)
_SAT_1000 = datetime.datetime(2026, 9, 19, 10, 0)    # 周六
check("★★峰谷：工作日 9–12 / 14–18 = **高峰**（官方 2026 口径）",
      statmod.peak_state(_MON_930)[0] == "peak" and statmod.peak_state(_MON_1430)[0] == "peak",
      str([statmod.peak_state(_MON_930)[0], statmod.peak_state(_MON_1430)[0]]))
check("★★峰谷：其余（午休 / 夜间 / **周末全天**）= 空闲",
      statmod.peak_state(_MON_1200)[0] == "idle"
      and statmod.peak_state(_MON_2000)[0] == "idle"
      and statmod.peak_state(_SAT_1000)[0] == "idle",
      str([statmod.peak_state(_MON_1200)[0], statmod.peak_state(_MON_2000)[0],
           statmod.peak_state(_SAT_1000)[0]]))
check("★★峰谷：倒计时 = 到**下一次切换点**（9:30 → 02:30:00；20:00 → 次日 09:00 = 13:00:00）",
      statmod.peak_state(_MON_930)[1] == 2 * 3600 + 30 * 60
      and statmod.peak_state(_MON_2000)[1] == 13 * 3600,
      str([statmod.peak_state(_MON_930)[1], statmod.peak_state(_MON_2000)[1]]))
check("★峰谷：倒计时小时数**不封顶**（周六 10:00 → 周一 09:00 = 47 小时）",
      statmod.peak_state(_SAT_1000)[1] == 47 * 3600,
      str(statmod.peak_state(_SAT_1000)[1]))
check("★峰谷：判 deepseek 端点（第一类内容显示与否的判据）；空 API 一律 False",
      statmod.is_deepseek({"base_url": "https://api.deepseek.com"}) is True
      and statmod.is_deepseek({"base_url": "https://api.moonshot.cn/v1"}) is False
      and statmod.is_deepseek(None) is False and statmod.is_deepseek("") is False)
_bals = {"is_available": True, "balance_infos": [
    {"currency": "USD", "total_balance": "1.00"},
    {"currency": "CNY", "total_balance": "110.00"}]}
check("★余额：从 `/user/balance` 的返回里取 **CNY** 那条（官方是字符串）",
      statmod.balance_cny(_bals) == 110.0 and statmod.balance_cny({}) is None
      and statmod.balance_cny(None) is None)
import tempfile as _tmp23  # noqa: E402
import os as _os23  # noqa: E402
_f23 = _os23.path.join(_tmp23.mkdtemp(), "stats.json")
# ★★这里原本把「第二天」**硬编码**成 `datetime.datetime(2026, 9, 22, 0, 2)`，而前三条断言又
#   故意不传 `now`（走墙上时钟）⇒「跨天清零」的实际判据变成了「**真实的今天就 ≠ 2026-09-22**」。
#   一旦真实日期走到 2026-09-22（反向验证恰好跑到第 18 例 P2 时跨的零点），
#   `now=2026-09-22 00:01` 就不再是「新的一天」，变成**同日累加** 200+50=250 ≠ 50 ⇒ 两条同时
#   **永久性假红**（而且看着像产品 bug —— 实际是测试自己过期了）。
#   ⇒ 铁律：凡「今天 / 明天」的判据，`now` **一律显式注入**，且「第二天」由 `timedelta` 相对
#   算出；**绝不写死日期**、也**绝不把 `now` 留空**去问墙上时钟（下面两条 check 一个 `now=` 都不许省）。
_D23 = datetime.datetime(2026, 9, 21, 20, 0, 0)          # 第一天（固定值，纯粹为了可复算）
_D23_NEXT = _D23 + datetime.timedelta(days=1)            # 第二天 = 第一天 + 1 天
check("★★累计：token 累加落盘 + **跨天自动清零**（★测试一律注入自己的路径，不碰真 `stats.json`）",
      statmod.record_tokens(120, path=_f23, now=_D23) == 120
      and statmod.record_tokens(80, path=_f23, now=_D23) == 200
      and statmod.today_tokens(path=_f23, now=_D23) == 200
      and statmod.record_tokens(50, path=_f23, now=_D23_NEXT) == 50
      and statmod.today_tokens(path=_f23, now=_D23_NEXT) == 50,
      "第一天 %s / 第二天 %s" % (_D23.date(), _D23_NEXT.date()))
check("★累计：脏值（非整数 / 负数 / None）一律忽略，绝不把累计写坏",
      statmod.record_tokens("x", path=_f23, now=_D23_NEXT) == 50
      and statmod.record_tokens(-5, path=_f23, now=_D23_NEXT) == 50
      and statmod.record_tokens(None, path=_f23, now=_D23_NEXT) == 50)

# ---- 23d. 文本块：位置跟着镜像，**字本身不翻** ----
check("★文字：基准朝向下的文字块 == `THINKING_TEXT_RECT`",
      thinkmod.thinking_text_rect("left", "down") == tuple(thinkmod.THINKING_TEXT_RECT),
      str(thinkmod.thinking_text_rect("left", "down")))
check("★★文字：翻到下方时文字块**跟着镜像**（与三帧同一套 `p → 尺寸 − p`）",
      thinkmod.thinking_text_rect("left", "up")[1]
      == thinkmod.THINKING_CANVAS[1] - thinkmod.THINKING_TEXT_RECT[1] - thinkmod.THINKING_TEXT_RECT[3],
      str(thinkmod.thinking_text_rect("left", "up")))
check("★文字：文字块落在气泡大椭圆内部（不会画到椭圆外面去）",
      thinkmod.THINKING_TEXT_RECT[0] >= 12 + 8
      and thinkmod.THINKING_TEXT_RECT[1] >= 9 + 8
      and thinkmod.THINKING_TEXT_RECT[0] + thinkmod.THINKING_TEXT_RECT[2] <= 236 - 8
      and thinkmod.THINKING_TEXT_RECT[1] + thinkmod.THINKING_TEXT_RECT[3] <= 158 + 8,
      str(thinkmod.THINKING_TEXT_RECT))
# ★★这条是**补**的（原缺 ⇒ 反向验证 R3 例成为「不可观测的等价变异体」）：
#   文字是 `AlignHCenter|AlignVCenter` 画在 box 里的 ⇒ 把矩形从 164×92@(42,37) 放大到
#   192×104@(28,30)，**块心只从 (124,83) 挪到 (124,82)**、墨迹落点与换行位置全不变，
#   于是「最宽一行 ≤ 块宽」更宽松、「真机字形出界 0 px」照旧 ⇒ 行为层**一条都红不了**。
#   ⇒ 「量出来的紧致矩形」只能在这一层钉死（与字号 `(20, 26)` 同款钉法）：
#   宽 164 = 最宽一行 161 + 3px 余量；高 92 = 单行块 59 + 一行余量（留给台词换行）。
#   改这两个数就应当红 —— 不许「反正居中、看不出来」地随手放大。
check("★文字（二轮）：文字块就是**量出来的紧致矩形** `(42, 37, 164, 92)`（宽 164 = 最宽一行 161 + 3px、"
      "高 92 = 单行块 59 + 一行余量）—— 与字号 `(20, 26)` 同款钉法：这些数字都是量出来的，"
      "不许随手放大缩小（★放大到 192×104 时文字居中、墨迹几乎不动，行为层抓不到，只能在这一层钉）",
      thinkmod.THINKING_TEXT_RECT == (42, 37, 164, 92),
      str(thinkmod.THINKING_TEXT_RECT))


def _attr_calls23(src, class_name, method_name):
    """AST：`class.method` 里**真实发生**的 `x.y(...)` 调用 → `{("x.y"): [行号, …]}`。

    ★用 AST 按行号比先后，**不用 `src.index()`** —— 注释里也会出现同一个词，那样断言成摆设。
    """
    fn = _method_node(src, class_name, method_name)
    out = {}
    if fn is None:
        return out
    for n in ast.walk(fn):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute):
            v = n.func.value
            if isinstance(v, ast.Name):
                out.setdefault("%s.%s" % (v.id, n.func.attr), []).append(n.lineno)
    return out


_lc_paint23 = _attr_calls23(_SRC19, "_ThinkingOverlay", "paintEvent")
_lc_pct23 = _attr_calls23(_SRC19, "_ThinkingOverlay", "_paint_content")


def _translate_args23(src, class_name, method_name):
    """AST：`class.method` 里每次 `x.translate(...)` 的**实参节点列表**。

    ★查实参**节点本身**、不查字符串 —— 纯字符串查 `"/ s"` 会被注释里的「镜像轴用 `窗口宽 / s`」
    骗绿（本文件踩过同款：`src.index()` 命中注释）。
    """
    fn = _method_node(src, class_name, method_name)
    out = []
    for n in ast.walk(fn) if fn is not None else ():
        if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                and n.func.attr == "translate"):
            out.append(list(n.args))
    return out


def _is_div23(node):
    """`<…> / s` 这种**带除法**的表达式。"""
    return isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div)


def _is_self_size23(node):
    """**裸的** `self.width()` / `self.height()`（没被除法换算回基准画布的那种）。"""
    return (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and node.func.attr in ("width", "height")
            and isinstance(node.func.value, ast.Name) and node.func.value.id == "self")


check("★★结构：`paintEvent` 里文字画在 `p.restore()` **之后**（镜像只作用于三帧那一段）",
      "self._paint_content" in _lc_paint23 and "p.restore" in _lc_paint23
      and max(_lc_paint23["p.restore"]) < min(_lc_paint23["self._paint_content"]),
      str(_lc_paint23))
_axes23 = _translate_args23(_SRC19, "_ThinkingOverlay", "paintEvent")
check("★★结构：两条镜像轴都换算回**基准画布**（`p.translate(窗口宽 / s, 0)` + "
      "`p.translate(0, 窗口高 / s)`）",
      len(_axes23) == 2
      and any(_is_div23(a[0]) for a in _axes23 if len(a) >= 1)
      and any(_is_div23(a[1]) for a in _axes23 if len(a) >= 2),
      str(_axes23))
check("★★结构：`translate` 的实参里**不许**出现裸 `self.width()` / `self.height()`"
      "—— 那已经是**缩放后**的像素，在 `p.scale(s,s)` 之下会把画布翻到 2× 的地方、缩放态整个错位。"
      "★这条是**补**的：原来只查「有一次 translate 带除法」，而 `self.height() / s` 那条会把"
      "`self.width()` 的坏写法一起掩护过去 ⇒ 反向验证 **N9 例 0 红、断言纯属摆设**",
      not any(_is_self_size23(arg) for a in _axes23 for arg in a),
      str(_axes23))
check("★★结构：`_paint_content()` 里**没有任何** `translate` / `scale` 调用 ⇒ 文字不镜像",
      not any(k.endswith(".translate") or k.endswith(".scale") for k in _lc_pct23),
      str(_lc_pct23))

# ---- 23e. 行为层：缩放 / 内容池 / 连点节拍 ----
_pet23 = new_pet(ALICE, at=(600, 400))
# ★角色必须是「爱丽丝」：台词按角色分表，`_current_key` 没设过就一句台词都没有（池子会是空的）。
_pet23.set_current_role("alice")
_ov23 = _pet23._thinking_ov
# ⚠️ 测试期间把「后台刷余额」换成空操作：真跑会去连网络（测试要求**不联网**）。
_keep_pf23 = petmod.stats.prefetch_balance
petmod.stats.prefetch_balance = lambda *a, **k: None
_keep_api23 = _pet23._thinking_api
check("★行为：`PetWindow` 默认拿不到 API ⇒ 内容池只有台词（不会凭空显示余额）",
      len(_pet23._thinking_content()) == 2, str(_pet23._thinking_content()))
_pet23._thinking_api = lambda: {"name": "AR1S", "api_key": "sk-x",
                                "base_url": "https://api.deepseek.com"}
check("★★行为：当前 API 是 deepseek ⇒ 内容池 4 句（第一类回来了）",
      len(_pet23._thinking_content()) == 4, str([p[1] for p in _pet23._thinking_content()]))
_pet23._thinking_api = lambda: {"name": "K", "api_key": "sk-x",
                                "base_url": "https://api.moonshot.cn/v1"}
check("★★行为：换成非 deepseek 的 API ⇒ 内容池只剩 2 句（第一类整类消失）",
      len(_pet23._thinking_content()) == 2, str([p[1] for p in _pet23._thinking_content()]))
_pet23._thinking_api = _keep_api23

_pet23._thinking_play()
check("★★行为（二轮）：单击之后窗口尺寸 = 按「**贴图显示宽 ÷ 原图宽**」算出来的缩放尺寸"
      "（爱丽丝 150/300 = 0.5 ⇒ 124×114）",
      (_ov23.width(), _ov23.height()) == (124, 114)
      and abs(_ov23.scale() - 0.5) < 1e-9,
      str(((_ov23.width(), _ov23.height()), _ov23.scale())))
check("★★行为：窗口**实际落点** == `thinking_pos(锚点, 朝向, scale)`（缩放后的尾尖也算进去了）",
      (_ov23.x(), _ov23.y()) == thinkmod.thinking_pos(
          _pet23._thinking_anchor_of(_ov23.side(), _ov23.face()),
          _ov23.side(), _ov23.face(), scale=_ov23.scale()),
      str((_ov23.x(), _ov23.y())))
check("★行为：换句定时器在跑（一轮气泡期间它一直挂着）", _ov23.switch_running())
check("★行为：已经抽到了一句内容（`content()` 的标签与数值都在池子里）",
      _ov23.content() is not None and _ov23.content() in _pet23._thinking_content(),
      str(_ov23.content()))

# ★比例本身：由 PetWindow 从**真实素材**算（站姿/节能态同值 0.5；换角色则各按自己的图）
check("★★行为（二轮）：`_thinking_ratio()` = 显示宽 ÷ 原图宽 = 150/300 = **0.5**"
      "（走的是 `_normal_size()` 的**标称**显示宽，不是拍贴图时会乱跳的实时几何）",
      _pet23._sprite_natural_w() == 300 and _pet23._sprite_display_w() == 150
      and abs(_pet23._thinking_ratio() - 0.5) < 1e-9,
      "%s / %s" % (_pet23._sprite_natural_w(), _pet23._sprite_display_w()))
_keep_ps23 = _pet23._power_save
_pet23._power_save = True
check("★★行为（二轮）：**节能态也是 0.5**（节能图原图 300×200、在屏宽仍是 150）⇒ 两种形态下"
      "气泡尺寸**相同**",
      _pet23._sprite_natural_w() == 300 and _pet23._sprite_display_w() == 150
      and abs(_pet23._thinking_ratio() - 0.5) < 1e-9,
      "%s / %s" % (_pet23._sprite_natural_w(), _pet23._sprite_display_w()))
_pet23._power_save = _keep_ps23

# 纯行为层：比例变小 ⇒ 气泡跟着缩（直接喂比例，不经过素材）
_ov23.set_sprite_scale(0.25)
check("★★行为（二轮）：比例变小 ⇒ 气泡跟着缩（0.25 ⇒ 62×57）",
      (_ov23.width(), _ov23.height()) == (62, 57) and abs(_ov23.scale() - 0.25) < 1e-9,
      str(((_ov23.width(), _ov23.height()), _ov23.scale())))
_ov23.set_sprite_scale(0.5)
check("★行为（二轮）：比例回到 0.5 ⇒ 尺寸回到 124×114",
      (_ov23.width(), _ov23.height()) == (124, 114)
      and abs(_ov23.scale() - 0.5) < 1e-9)

# ★换角色 ⇒ 比例**各按自己的贴图**（不是写死的 0.5）：艾莲 256×256 → 显示 250×250
_pet_el23 = new_pet(ELLEN, at=(600, 400))
check("★★行为（二轮）：换角色比例跟着换 —— 艾莲原图 256×256、显示 250×250 ⇒ 250/256"
      "（★这条钉住「比例不是常数、也不是拿站姿高度当基准」）",
      _pet_el23._sprite_natural_w() == 256 and _pet_el23._sprite_display_w() == 250
      and abs(_pet_el23._thinking_ratio() - 250.0 / 256.0) < 1e-9,
      "%s / %s" % (_pet_el23._sprite_natural_w(), _pet_el23._sprite_display_w()))
_pet_el23.close()
qapp.processEvents()

# ---- 23f. 连点：**不重放**、**不重置节拍**、换句只由时间决定 ----
_rolls23 = {"n": 0}


def _cyc23():
    """单元素池 + 每次递增 ⇒ 抽一次变一个值，能精确数出「抽了几次」。"""
    _rolls23["n"] += 1
    return [("line", "L%d" % _rolls23["n"], "")]


_keep_prov23 = _ov23._content_of
_ov23.set_content_provider(_cyc23)
_ov23.hide_now()
# ★抹掉「上一轮起点」= 模拟「距上一轮已经过了很久」⇒ 这一下算**新一轮**（不是连点）。
#   不这么做的话，同一个 tick 里接着调 `_thinking_play()` 会被时间判成连点，抽签就不会发生。
_ov23._mash_origin = None
_pet23._thinking_play()
_pump_until(lambda: _pet23.thinking_frame_opacities() == [1.0, 1.0, 1.0], 1.0)
_n23 = _rolls23["n"]
_pet23._thinking_play()          # 连点（同一拍之内 ⇒ 时间上算连点）
check("★★行为（二十三改）：连点**不重放三帧**（帧没被打回 0）",
      _pet23.thinking_frame_opacities() == [1.0, 1.0, 1.0],
      str(_pet23.thinking_frame_opacities()))
check("★★行为：连点那一下**不换句**（抽签次数不变）—— 换句只由时间决定，与点击次数无关",
      _rolls23["n"] == _n23, "%d -> %d" % (_n23, _rolls23["n"]))
check("★★行为：连点**不重置**换句节拍（定时器还在跑，相位没被点击打断）",
      _ov23.switch_running())
_ov23._on_switch_tick()          # 时间到了（这里直接催一拍，免得真等 2s）
check("★★行为：到了节点才换句（抽签 +1，内容跟着换）",
      _rolls23["n"] == _n23 + 1 and _ov23.content() == ("line", "L%d" % (_n23 + 1), ""),
      str((_rolls23["n"], _ov23.content())))
check("★★行为：连点期间**停留计时被续上**（`_hold_timer` 在跑 ⇒ 停手 1s 后才收）",
      _ov23._hold_timer.isActive())
# ★★「连点」必须按**距上一次点击**判，不能按「距这一轮**第一次**点击」判（用户口径）。
#   否则连点持续超过 `THINKING_MASH_MS` 之后再点一下就会被当成**新一轮** ⇒ `show_bubble()`
#   ⇒ `_ops` 归零 + 三帧重新 0→1 淡入 ⇒ 肉眼就是「**气泡消失再淡入**」（用户报的正是这个现象）。
#   ★用户口径原文：「只需文字消失再淡入，**气泡保持显示状态**；气泡淡出的判断条件**仅为鼠标停止
#   点击后的计时**」⇒ 判据只看**两次点击的间隔**，与「这一轮开始多久」无关。
#   这里用「手动把 `_mash_origin` 往前推 `_push23`」模拟「距上一次点击已过 `_push23`」，不真等 2s。
#   ★偏移量**由窗口推导**（= 窗口 × 0.75），别写死：这条断言要有鉴别力，必须**同时**满足
#     「相邻两次的间隔都落在窗口内」+「距**第一次**已经超出窗口」⇒ 偏移只能落在 (窗口/2, 窗口)。
#     窗口从 1500ms 改成 2000ms（2026-09-22）时，写死 1.0s 会让偏移落在窗口外 → 断言失效成假绿。
_push23 = thinkmod.THINKING_MASH_MS / 1000.0 * 0.75
_ov23._mash_origin = None
_pet23._thinking_play()                       # 第 1 次点击（新一轮）
_pump_until(lambda: _pet23.thinking_frame_opacities() == [1.0, 1.0, 1.0], 1.0)
_n23c = _rolls23["n"]
_ov23._mash_origin -= _push23                 # 「距第 1 次点击已过 _push23」
_pet23._thinking_play()                       # 第 2 次点击（间隔 _push23 ⇒ 连点）
_ov23._mash_origin -= _push23                 # 「距第 2 次点击又过 _push23」（但距第 1 次已 2×_push23）
_pet23._thinking_play()                       # 第 3 次点击（间隔仍 _push23 ⇒ **仍该算连点**）
check("★★行为（续）：连点**续命** —— 只要「距上一次点击」还在 `THINKING_MASH_MS` 内就算连点，"
      "气泡**不重播**（三帧不打回 0）；★判据**不看**「距这一轮第一次点击」已经多久",
      _pet23.thinking_frame_opacities() == [1.0, 1.0, 1.0],
      str(_pet23.thinking_frame_opacities()))
check("★★行为（续）：续命的连点那一下也**不换句**（抽签次数不变）—— 换句仍只由时间决定",
      _rolls23["n"] == _n23c, "%d -> %d" % (_n23c, _rolls23["n"]))
# ---- 23f-2. ★★2026-09-29 新增：叠加窗**取词真的排除上一条**（**行为层**）----
# ★为什么非要这一条：只钉 AST 的话，「把 `avoid=` 去掉」只会让**结构层**红 ——
#   而结构层挡不住「传了 `avoid` 但下游不用它」。两条一起才闭合（`rev32` N1 红行为层 / N2 红结构层）。
_ov23.set_content_provider(lambda: [("line", "甲", ""), ("line", "乙", "")])
_ov23._content = None
_chain29 = []
for _i29b in range(24):
    _ov23._roll_content()
    _chain29.append(_ov23.content()[1])
check("★★行为：叠加窗**连抽 24 次相邻永不重复**（池子 2 条 ⇒ 严格交替），且两条都出现过 —— "
      "证明 `_roll_content()` 真把「上一次那一句」当排除项用掉了，不只是写在源码里",
      all(_chain29[i] != _chain29[i + 1] for i in range(len(_chain29) - 1))
      and set(_chain29) == {"甲", "乙"},
      "".join(_chain29))
_ov23.set_content_provider(_keep_prov23)

# ---- 23f-3. ★★2026-09-29 新增：**气泡消失后再点**必须算新一轮 + 取词排除上一条 ----
# ★用户原话：「连点时的显示效果已经没有问题，**单击**时的效果需优化：气泡的显示时长与连点时
#   一次内容显示时长设为一致，且**气泡消失后再次点击也和连点时一样，随机内容要排除掉上一条
#   显示过的**」。
# ★改前真机实测（`_sc29c_bubble.py`，8 项红）：单击的寿命只有 **1500ms**（停留 1s），而连点
#   窗口是 **2000ms** ⇒ 气泡在 1.7s 就收干净了、窗口却到 2s 才满 —— 中间那 300ms 里点一下
#   **按时间仍算连点** ⇒ 走 `_mash()`、**一次都不抽签** ⇒ 内容 `甲 → 甲`（= 用户看到的「重复」）。
#   ⇒ 两处一起改才闭合：① `THINKING_HOLD_MS` 1000→1500（寿命并到 2s，见 §22b）；
#     ② `play()` 的判据补 `is_shown()`（结构层那条在 §23b 段旁边）。
_rolls23b = {"n": 0}


def _prov23b():
    """池子恒 2 条 + **数抽签次数**（「抽了几次」是判「新一轮 / 连点」最直接的观测量）。"""
    _rolls23b["n"] += 1
    return [("line", "甲", ""), ("line", "乙", "")]


_ov23.set_content_provider(_prov23b)


def _gone23():
    """把气泡推到「真机上寿命走完」那一刻的终态（`_on_out_done()` 就是它的生产代码）。"""
    _ov23._on_out_done()


_ov23.hide_now()
_ov23._mash_origin = None
_pet23._thinking_play()                                    # 第 1 次点击：新一轮
_pump_until(lambda: _pet23.thinking_frame_opacities() == [1.0, 1.0, 1.0], 1.0)
_line23a = _ov23.content()[1]
_gone23()
check("★★行为（单击）：前置 —— 气泡真的收干净了（不可见）",
      not _pet23.is_thinking_shown())
# ★把「距上一次点击」**刻意**压在 1.8s：既在连点窗口（2s）**之内**、气泡又已经消失 ——
#   这正是改前唯一会分叉的区间，也是反向验证 N1 的靶心（去掉 `is_shown()` 这条必红）。
_ov23._mash_origin = time.monotonic() - 1.8
_pet23._thinking_play()
_line23b = _ov23.content()[1]
check("★★行为（单击）：气泡**收掉之后**再点 ⇒ **算新一轮**（三帧重新 0→1 淡入 + **重新抽句**）——"
      "用户口径「气泡消失后再次点击也和连点时一样（要排除上一条）」",
      _pet23.thinking_frame_opacities() == [0.0, 0.0, 0.0]
      and _rolls23b["n"] == 2 and _line23b != _line23a,
      "%s → %s  ops=%s  rolls=%d" % (_line23a, _line23b,
                                     _pet23.thinking_frame_opacities(), _rolls23b["n"]))
_pump_until(lambda: _pet23.thinking_frame_opacities() == [1.0, 1.0, 1.0], 1.0)
_gone23()
_ov23._mash_origin = time.monotonic() - 1.8
_pet23._thinking_play()
_line23c = _ov23.content()[1]
check("★★行为（单击）：再来一次 ⇒ 池子 2 条时**严格交替**（甲乙甲 / 乙甲乙）——"
      "「随机内容排除掉上一条」由此闭合",
      _line23a == _line23c and _line23a != _line23b,
      "".join((_line23a, _line23b, _line23c)))
# ★反向守卫：不许把判据收成「一律新一轮」—— 气泡**还显示着**时点击必须仍是连点。
_pump_until(lambda: _pet23.thinking_frame_opacities() == [1.0, 1.0, 1.0], 1.0)
_r_before23 = _rolls23b["n"]
_ov23._mash_origin = time.monotonic() - 1.8
_pet23._thinking_play()
check("★★行为（单击·反向）：气泡**还显示着**时点击 ⇒ 仍是**连点续命**（不抽句、三帧不打回 0）"
      "—— ★少了这条，把判据写成「一律新一轮」也全绿",
      _rolls23b["n"] == _r_before23
      and _pet23.thinking_frame_opacities() == [1.0, 1.0, 1.0],
      "rolls %d→%d  %s" % (_r_before23, _rolls23b["n"],
                           _pet23.thinking_frame_opacities()))
# ★淡出中点击：在途淡出必须被 `_mash()` 掐掉（留着的话它的收尾 `_on_out_done()` 到点会
#   `hide()` ⇒ **点完反而没了**）。★这条同时也是 §20.15「N2」的反向靶心。
_ov23.hide_now()
_ov23._mash_origin = None
_pet23._thinking_play()
_fade23 = _pump_until(lambda: _ov23._out_anim is not None, 3.0)
_ov23._mash_origin = time.monotonic() - 0.1
_pet23._thinking_play()
check("★★行为（单击）：**淡出中**点一下 ⇒ 在途淡出被掐掉、气泡留得住（不「点完就没了」）",
      _fade23 and _ov23._out_anim is None and _pet23.is_thinking_shown(),
      "fade_started=%s out_anim=%s shown=%s" % (_fade23, _ov23._out_anim,
                                                _pet23.is_thinking_shown()))
_ov23.set_content_provider(_keep_prov23)
check("★★结构：`_mash()` 里**一个字节都不碰**换句定时器（切换只由时间决定）—— ★AST 查真实调用，"
      "新注释里正解释这件事，纯字符串会被自己的注释骗绿",
      not any(c.startswith("_switch_timer")
              for c in _self_calls22(_SRC19, "_ThinkingOverlay", "_mash")),
      str(_self_calls22(_SRC19, "_ThinkingOverlay", "_mash")))
check("★★结构：`_stop_all()` 里**也**没停换句定时器（连点路径会经过它）",
      not any(c.startswith("_switch_timer")
              for c in _self_calls22(_SRC19, "_ThinkingOverlay", "_stop_all")),
      str(_self_calls22(_SRC19, "_ThinkingOverlay", "_stop_all")))
_switch_single23 = False
_fn_init23 = _method_node(_SRC19, "_ThinkingOverlay", "__init__")
for _n23b in (ast.walk(_fn_init23) if _fn_init23 is not None else ()):
    if (isinstance(_n23b, ast.Call) and isinstance(_n23b.func, ast.Attribute)
            and _n23b.func.attr == "setSingleShot"
            and isinstance(_n23b.func.value, ast.Attribute)
            and _n23b.func.value.attr == "_switch_timer"):
        _switch_single23 = True
check("★★结构：换句定时器是**循环**表（`_switch_timer.setSingleShot(True)` 一处都没有）"
      "—— 单发就得每次重排，节拍会被点击扰动",
      not _switch_single23)
_ov23.hide_now()
_ov23._on_switch_tick()
check("★行为：气泡收掉之后换句定时器**自己停表**（不空转）", not _ov23.switch_running())

# ---- 23h. ★二轮：字号增大 + 文字**自己**的淡入淡出 ----
# 用户口径（2026-09-21 二轮）原文要点：
#   ① 「气泡内显示的文字字体大小可以适当增大」、「要保证文字尺寸能完整在气泡内显示」、
#      「一些换行显示数值的情况，可以将数值的那一行设置的比上一行字体更大」；
#   ② 「气泡存在淡入淡出动画，但文字显示没有淡入淡出，需要为文字加上淡入淡出效果，
#      淡入在气泡完全显示后 100ms 淡入，淡出则与气泡一起淡出」；
#   ③ 「连点超过两秒…时的文字切换也要加入效果，替换前的文字直接消失，替换后的文字 100ms
#      淡入（这 100ms 也算入 2s 的文字替换时间）」。


def _events23(src, cls, meth, wanted):
    """AST：`cls.meth` 里「关注点」按**真实行号**排出的先后顺序。

    命中条件 = `self.<name> = …`（赋值目标）或 `self.<name>(…)`（调用）。
    ★只看 AST ⇒ 注释 / 字符串里写了什么都不算（本文件被自己的注释骗绿过好几次）。
    """
    fn = _method_node(src, cls, meth)
    hits = []
    for n in ast.walk(fn) if fn is not None else ():
        if (isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name)
                and n.value.id == "self" and n.attr in wanted):
            hits.append((n.lineno, n.attr))
    return [a for _, a in sorted(hits, key=lambda t: (t[0], t[1]))]


def _opacity_mult23(src, cls, meth, recv, attr):
    """AST：`recv.<attr>(<乘法表达式>)` 里那个乘法的两侧属性名（没有 ⇒ `None`）。"""
    fn = _method_node(src, cls, meth)
    for n in ast.walk(fn) if fn is not None else ():
        if not (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                and n.func.attr == attr and isinstance(n.func.value, ast.Name)
                and n.func.value.id == recv and len(n.args) == 1):
            continue
        a = n.args[0]
        if isinstance(a, ast.BinOp) and isinstance(a.op, ast.Mult):
            return {x.attr for x in ast.walk(a)
                    if isinstance(x, ast.Attribute) and isinstance(x.value, ast.Name)
                    and x.value.id == "self"}
    return None


check("★★时序（二轮）：文字淡入时长 == `THINKING_TEXT_FADE_MS` = **100ms**、"
      "且 `_fade_text_in()` 用的就是它（用户口径「淡入在气泡完全显示后 100ms 淡入」）",
      thinkmod.THINKING_TEXT_FADE_MS == 100
      and "THINKING_TEXT_FADE_MS" in inspect.getsource(petmod._ThinkingOverlay._fade_text_in),
      str(thinkmod.THINKING_TEXT_FADE_MS))
check("★★结构（二轮）：`_on_in_done()`（三帧**全亮**）里按顺序 `_ops` 兜底 → 起文字淡入 → "
      "`_hold_timer`（★AST 按行号比先后；纯字符串会被注释骗绿）",
      _events23(_SRC19, "_ThinkingOverlay", "_on_in_done",
                ("_ops", "_fade_text_in", "_hold_timer"))
      == ["_ops", "_fade_text_in", "_hold_timer"],
      str(_events23(_SRC19, "_ThinkingOverlay", "_on_in_done",
                    ("_ops", "_fade_text_in", "_hold_timer"))))
check("★★结构（二轮）：`_on_switch_tick()` 的顺序 = 掐在途文字动画 → **旧字瞬灭**"
      "（`self._text_op = 0.0`）→ 抽新句 → **新字淡入**",
      _events23(_SRC19, "_ThinkingOverlay", "_on_switch_tick",
                ("_stop_text_anim", "_text_op", "_roll_content", "_fade_text_in"))
      == ["_stop_text_anim", "_text_op", "_roll_content", "_fade_text_in"],
      str(_events23(_SRC19, "_ThinkingOverlay", "_on_switch_tick",
                    ("_stop_text_anim", "_text_op", "_roll_content", "_fade_text_in"))))
check("★结构（二轮）：`_stop_all()` 也把文字归零（三帧都还没亮，字不该先露出来）",
      _events23(_SRC19, "_ThinkingOverlay", "_stop_all",
                ("_stop_text_anim", "_ops", "_opacity", "_text_op"))
      == ["_stop_text_anim", "_ops", "_opacity", "_text_op"],
      str(_events23(_SRC19, "_ThinkingOverlay", "_stop_all",
                    ("_stop_text_anim", "_ops", "_opacity", "_text_op"))))
check("★★结构（二轮）：`_paint_content()` 的 `p.setOpacity(…)` 实参是**乘法**"
      "（`self._opacity * self._text_op`）—— 「文字自己淡入、淡出跟气泡一起」的**全部**实现，"
      "不许再多一段文字淡出动画（会与气泡错拍）",
      _opacity_mult23(_SRC19, "_ThinkingOverlay", "_paint_content", "p", "setOpacity")
      == {"_opacity", "_text_op"},
      str(_opacity_mult23(_SRC19, "_ThinkingOverlay", "_paint_content", "p", "setOpacity")))
check("★★结构（二轮）：文字**没有**独立的淡出通道（`_fade_text_out` / `_on_text_out_done` "
      "一个都没有）—— 淡出走乘法那条",
      not hasattr(petmod._ThinkingOverlay, "_fade_text_out")
      and not hasattr(petmod._ThinkingOverlay, "_on_text_out_done"))
check("★★结构（二轮）：文字动画**不挂** `QGraphicsOpacityEffect` / `setWindowOpacity`"
      "（与气泡本体同一条绘制链，不然 `grab()` 抓不到真机像素）。"
      "★走 AST 只认**真实调用** —— 类文档里正写着「不挂 `setWindowOpacity`」这句自述，"
      "纯字符串匹配会把它自己判成「挂了」（假红）",
      not _constructs(inspect.getsource(petmod._ThinkingOverlay),
                      ("QGraphicsOpacityEffect", "setWindowOpacity")),
      str(_constructs(inspect.getsource(petmod._ThinkingOverlay),
                      ("QGraphicsOpacityEffect", "setWindowOpacity"))))
check("★★结构（二轮）：`_mash()`（连点）**掐掉在途的三帧淡入** —— 不掐的话它 16ms 后会把"
      "刚置好的全亮又写回半亮（肉眼「闪一下」）",
      "_stop_all" not in _self_calls22(_SRC19, "_ThinkingOverlay", "_mash")
      and "self._in_anim.stop()" in inspect.getsource(petmod._ThinkingOverlay._mash))
check("★结构（二轮）：`set_scale_provider` 由 `PetWindow.__init__` 注入（比例 = `_thinking_ratio`）",
      "_thinking_ov.set_scale_provider(self._thinking_ratio)" in _think_src
      and "set_scale_provider" in _think_src)

# 行为层：文字的不透明度自己走一遍
_ov23.hide_now()
_ov23._mash_origin = None                    # 强制「新一轮」
_pet23._thinking_play()
check("★★行为（二轮）：刚弹出来时**字还看不见**（`_text_op == 0`）—— 三帧都还没亮，字不该先露",
      _pet23.thinking_text_opacity() == 0.0
      and not _pet23.thinking_text_fading(),
      str((_pet23.thinking_text_opacity(), _pet23.thinking_text_fading())))
_pump_until(lambda: _pet23.thinking_frame_opacities() == [1.0, 1.0, 1.0], 1.0)
check("★★行为（二轮）：三帧**全亮**那一刻文字的淡入**立刻**起来（用户口径「气泡完全显示后」）",
      _pet23.thinking_text_fading() or _pet23.thinking_text_opacity() == 1.0,
      str((_pet23.thinking_text_fading(), _pet23.thinking_text_opacity())))
_pump_until(lambda: _pet23.thinking_text_opacity() >= 1.0, 0.8)
check("★★行为（二轮）：100ms 之后文字全亮（`_text_op == 1.0`）",
      _pet23.thinking_text_opacity() == 1.0, str(_pet23.thinking_text_opacity()))
_ov23._on_switch_tick()                      # 连点换句那一下
check("★★行为（二轮）：换句瞬间 **旧字直接消失**（`_text_op` 打回 0）+ 新字淡入在跑",
      _pet23.thinking_text_opacity() == 0.0 and _pet23.thinking_text_fading(),
      str((_pet23.thinking_text_opacity(), _pet23.thinking_text_fading())))
_pump_until(lambda: _pet23.thinking_text_opacity() >= 1.0, 0.8)
check("★行为（二轮）：换句的新字 100ms 后也全亮",
      _pet23.thinking_text_opacity() == 1.0, str(_pet23.thinking_text_opacity()))
_ov23.set_sprite_scale(0.5)

# ---- 字号 + 文字块：真机字体量出来的（这里是**重量一遍**，不是照抄常量）----
_labels23 = sorted({p[1] for p in list(thinkmod.thinking_pool(
    deepseek=True, balance=1.0, state="peak", seconds_left=1, role_key="alice"))
    + list(thinkmod.thinking_pool(
        deepseek=True, balance=1.0, state="idle", seconds_left=1, role_key="alice"))
    if p[2]})
_values23 = sorted({p[2] for p in list(thinkmod.thinking_pool(
    deepseek=True, balance=1234.5678, state="peak",
    seconds_left=167 * 3600 + 59 * 60 + 59, role_key="alice"))
    + list(thinkmod.thinking_pool(
        deepseek=True, balance=0.0, state="idle", seconds_left=0, role_key="alice"))
    if p[2]}
    | {p[1] for p in thinkmod.thinking_pool(
        deepseek=True, balance=1.0, state="idle", seconds_left=1, role_key="alice")
        if not p[2]})
check("★字号（二轮）：数值行字号**严格大于**标签行（用户口径「数值的那一行设置的比上一行"
      "字体更大」），且两档都从原来的 12/16 **调大了**",
      thinkmod.THINKING_VALUE_PX > thinkmod.THINKING_LABEL_PX
      and (thinkmod.THINKING_LABEL_PX, thinkmod.THINKING_VALUE_PX) == (20, 26),
      "%s / %s" % (thinkmod.THINKING_LABEL_PX, thinkmod.THINKING_VALUE_PX))

_FONT23 = "C:/Windows/Fonts/msyh.ttc"
_font_ok23 = os.path.exists(_FONT23)
if _font_ok23:
    # 离屏 Qt 自带字体目录是空的（`Qt no longer ships fonts`）⇒ 不注册连 ASCII 都是豆腐块。
    from PySide6.QtGui import QFontDatabase, QFontMetrics  # noqa: E402
    QFontDatabase.addApplicationFont(_FONT23)

    def _widest23(px, texts):
        f = QFont(thinkmod.THINKING_TEXT_FONT)
        f.setPixelSize(px)
        fm = QFontMetrics(f)
        return max([fm.horizontalAdvance(t) for t in texts] or [0]), fm.height()

    _wl23, _hl23 = _widest23(thinkmod.THINKING_LABEL_PX, _labels23)
    _wv23, _hv23 = _widest23(thinkmod.THINKING_VALUE_PX, _values23)
    _tx23, _ty23, _tw23, _th23 = thinkmod.THINKING_TEXT_RECT
    check("★★文字（二轮）：**最宽的那一行**也完整落进文字块（真机字体 msyh 量宽度：标签 ≤ 块宽、"
          "数值/台词 ≤ 块宽；两行块总高 ≤ 块高）—— 用户口径「要保证文字尺寸能完整在气泡内显示」",
          _wl23 <= _tw23 and _wv23 <= _tw23
          and (_hl23 + thinkmod.THINKING_LINE_GAP + _hv23) <= _th23,
          "label %d / value %d / 块宽 %d；块高 %d 需 %.0f"
          % (_wl23, _wv23, _tw23, _th23, _hl23 + thinkmod.THINKING_LINE_GAP + _hv23))

    # ★真机字形落点：把文字**真画一遍**（已注册真机字体 ⇒ 离屏也有字形），逐像素查它有没有出气泡。
    _ov23._content = ("balance", "剩余余额", "1234.57元")
    _ov23.set_sprite_scale(0.5)
    _s23 = _ov23.scale() or 1.0

    def _paint_ink23(op, top):
        """按给定的两个不透明度把这一句画到透明图里，返回 `(ys, xs, alpha 总和)`（窗口坐标）。"""
        _ov23._opacity, _ov23._text_op = op, top
        im = QImage(_ov23.width(), _ov23.height(), QImage.Format_ARGB32)
        im.fill(Qt.transparent)
        pp = QPainter(im)
        _ov23._paint_content(pp, _s23)
        pp.end()
        im = im.convertToFormat(QImage.Format_RGBA8888)
        al = _np.frombuffer(im.constBits(), dtype=_np.uint8).reshape(
            im.height(), im.bytesPerLine() // 4, 4)[:, :im.width(), :][:, :, 3]
        ys, xs = _np.where(al > 0)
        return ys, xs, int(al.sum())

    _ys23, _xs23, _sum_full23 = _paint_ink23(1.0, 1.0)
    _mask23 = _np.array(Image.open(str(_fin_p)).convert("RGBA"))[:, :, 3] > 8
    _cy23 = _np.clip(_np.round(_ys23 / _s23).astype(int), 0, _mask23.shape[0] - 1)
    _cx23 = _np.clip(_np.round(_xs23 / _s23).astype(int), 0, _mask23.shape[1] - 1)
    _out23 = int((~_mask23[_cy23, _cx23]).sum())
    check("★★文字（二轮）：**真机字形真画一遍**，墨迹**逐个像素**都在气泡大椭圆内"
          "（★离屏已注册 msyh，所以这是真字形、不是豆腐块）—— 用户口径「完整在气泡内显示」",
          len(_xs23) > 0 and _out23 == 0,
          "墨迹 %d px，出界 %d px" % (len(_xs23), _out23))
    _, _, _sum_half23 = _paint_ink23(0.5, 1.0)
    _, _, _sum_zero23 = _paint_ink23(1.0, 0.0)
    check("★★行为（二轮）：整条气泡的 `_opacity` 减半 ⇒ 文字墨迹的 alpha 总和**也减半**"
          "（用户口径「淡出则与气泡一起淡出」—— 靠相乘，不是另排一段动画）；"
          "`_text_op = 0` 时**一个像素都不画**",
          0.4 * _sum_full23 <= _sum_half23 <= 0.6 * _sum_full23 and _sum_zero23 == 0,
          "full %d / half %d / zero %d" % (_sum_full23, _sum_half23, _sum_zero23))
    _ov23._opacity, _ov23._text_op = 1.0, 1.0

# ---- 23g. 结构层：接线（api provider / usage 出口 / 出口收气泡）----
check("★结构：`PetWindow` 在 `__init__` 里把内容池回调注入叠加窗",
      "_thinking_ov.set_content_provider(self._thinking_content)" in _think_src)
check("★结构：`_thinking_play()` 走 `play()`（新一轮 / 连点的分岔在叠加窗里按**时间**判，"
      "不是在这里看 `isVisible()`）",
      "_thinking_ov.play(" in inspect.getsource(petmod.PetWindow._thinking_play)
      and "thinking_play" in _think_src)
_ai_src23 = (BASE / "app" / "ai.py").read_text(encoding="utf-8")


def _module_assign23(src, name):
    """AST：模块顶层 `name = <值>` 那次赋值的**值节点**（没有 ⇒ `None`）。

    ★查真实赋值、不看字符串 —— 注释里写「默认 None」这类话骗不到它。
    """
    for node in ast.parse(src).body:
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id == name:
                    return node.value
    return None


def _returns_nested_key23(src, func_name, outer, inner):
    """AST：模块级函数 `func_name` 里有没有 `return {<outer>: {<inner>: …}}`。"""
    for node in ast.parse(src).body:
        if isinstance(node, ast.FunctionDef) and node.name == func_name:
            for n in ast.walk(node):
                if not (isinstance(n, ast.Return) and isinstance(n.value, ast.Dict)):
                    continue
                for k, v in zip(n.value.keys, n.value.values):
                    if not (isinstance(k, ast.Constant) and k.value == outer
                            and isinstance(v, ast.Dict)):
                        continue
                    for kk in v.keys:
                        if isinstance(kk, ast.Constant) and kk.value == inner:
                            return True
    return False


_usink23 = _module_assign23(_ai_src23, "_USAGE_SINK")
check("★★结构：`ai.py` 的流式请求对 deepseek 端点**真的返回**"
      "`{\"stream_options\": {\"include_usage\": True}}`（★AST 查 return 的结构 —— "
      "注释里也写着 include_usage，纯字符串会被骗绿）—— 只改响应形状，**不额外耗 token**",
      _returns_nested_key23(_ai_src23, "_usage_kwargs", "stream_options", "include_usage"))
check("★★结构：`ai.py` 的用量出口**默认 None**（★AST 查真实赋值：`_USAGE_SINK = None`，"
      "注释里那句「默认 None」骗不到）⇒ 冒烟测试与其它调用方零副作用",
      isinstance(_usink23, ast.Constant) and _usink23.value is None
      and "def set_usage_sink(" in _ai_src23
      and "_report_usage(_usage_of(resp))" in _ai_src23)
_main_src23 = (BASE / "app" / "main.py").read_text(encoding="utf-8")
check("★结构：`main.py` 把用量出口接到本地累计（`stats.record_tokens`），并注入 API 取值回调",
      "set_usage_sink(stats.record_tokens)" in _main_src23
      and "set_thinking_api_provider" in _main_src23
      and "prefetch_balance" in _main_src23)
try:
    _default_ok23 = isinstance(statmod.today_tokens(), int)
except Exception:  # noqa: BLE001
    _default_ok23 = False
check("★累计：默认路径（项目根 `stats.json`）读得到、不抛 —— ★测试全程**只读不写**这个文件",
      _default_ok23)
petmod.stats.prefetch_balance = _keep_pf23
_pet23.close()
qapp.processEvents()

print()
print(f"共 {total[0]} 项断言，失败 {len(fails)} 项")
print("FAILED: " + ", ".join(fails) if fails else "ALL_OK")
sys.exit(1 if fails else 0)

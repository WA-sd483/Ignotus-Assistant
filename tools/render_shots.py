"""渲染主界面各状态为 PNG，用于人工核对视觉（不依赖真机操作，跑完生成截图到 docs/screenshots/）。

用法（项目根目录）：
    .venv\\Scripts\\python.exe tools\\render_shots.py

说明：会真的创建一个主窗口并跑真实事件循环，动画落到终态后截图；
不会写 config.json（save_config 被拦截）。做 UI 改动后跑一遍，再对照 design.md 核对。
"""
import sys
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from PySide6.QtCore import QEvent, QEventLoop, QPoint, QRect, QTimer  # noqa: E402
from PySide6.QtGui import QImage  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel, QPushButton  # noqa: E402

from app import gui  # noqa: E402
from app.config import DEFAULT_BASE_URL, DEFAULT_MODEL, load_config  # noqa: E402

OUT_DIR = BASE / "docs" / "screenshots"
WIN_W, WIN_H = 860, 560

gui.save_config = lambda cfg: None  # 不写回真实 config.json

app = QApplication.instance() or QApplication([])
win = gui.MainWindow(load_config())
win.resize(WIN_W, WIN_H)
win.show()
app.processEvents()


def settle(ms=700):
    """跑真实事件循环，让底色渐变 / 位移动画跑完。"""
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()
    app.processEvents()


def shoot(name, index=None):
    if index is None:
        win._select_nav(0)          # 聊天态（左栏角色区）
    else:
        win._show_settings_page(index)
    settle()
    path = OUT_DIR / f"{name}.png"
    img = win.grab()
    img.save(str(path))
    print(
        f"saved {path.name:22s} page={win._right_stack.currentIndex()} "
        f"settings_mode={win._settings_mode} left_bg={win.grab().toImage().pixelColor(20, 400).name()}"
    )


def grab_after(ms):
    """跑 ms 毫秒事件循环后抓图（用于抓动画中途帧）。"""
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()
    return win.grab()


def shoot_mid_frame(name="settings-slide-mid", delay=90):
    """抓一张「进入设置区」的动画中途帧：左栏底色应已是浅蓝（不是白闪），
    左栏内容应处于向左偏移的位置（横向位移未走完），右栏页面应处于向上偏移的位置
    （纵向位移未走完）。"""
    win._select_nav(0)
    settle()
    win._select_nav(2)
    img = grab_after(delay)
    path = OUT_DIR / f"{name}.png"
    img.save(str(path))
    cur_right = win._right_stack.currentWidget()
    print(f"saved {path.name:22s} left_x={win._left_settings_page.geometry().x()} "
          f"right_y={cur_right.geometry().y()} "
          f"left_bg={img.toImage().pixelColor(20, 400).name()}")


def shoot_manage(name, page):
    """管理区（管理 API / 管理唤醒词）：左栏换成一模一样的浅蓝管理导航，
    角色头像 / 名字 / 状态 / 编辑 / 切换角色按钮都**不出现**（整页被隐去）。

    核对点：左栏底色 = #C7E1FB、管理导航选中项与右栏页一致、角色区整页 isHidden。
    """
    win._select_nav(1)
    if page != win.PAGE_API:
        win._show_manage_page(page)
    settle()
    path = OUT_DIR / f"{name}.png"
    img = win.grab()
    img.save(str(path))
    print(f"saved {path.name:22s} page={win._right_stack.currentIndex()} "
          f"left_mode={win._left_mode} role_hidden={win._left_role_page.isHidden()} "
          f"nav={[(b.text(), b.isChecked()) for _i, b in win._manage_nav_btns]} "
          f"left_bg={img.toImage().pixelColor(20, 400).name()}")


def shoot_api_dialogs():
    """API 表单弹窗（添加 / 编辑）的卡片图 —— 应与确认弹窗同一张皮肤。

    核对点：**没有系统标题栏**、卡片 16px 圆角 + 淡蓝边框、取消（灰边）与确认（蓝底）
    两款按钮分明、输入框圆角 15px 且不会把卡片撑过 360px。用 `dlg.grab()` 单独抓
    （`win.grab()` 不含子对话框）。

    ★2026-10-02（`rev50`）：「接口地址 / 模型名」改成了**可编辑下拉** —— 图里那两行现在是
    胶囊下拉框（右侧圆箭头），且地址那行的显示文本是「服务商名 · 地址」。**这里必须跟
    `_add_api` / `_edit_row` 传同一套 fields**（第 6 项 = 候选项），否则截出来的图跟真弹窗
    长得不一样（截图的意义就没了）。另外多出两张展开态的图，看两家候选项。
    """
    win._show_manage_page(win.PAGE_API)
    settle()
    _addr = gui.providers.address_items()
    cases = [
        ("manage-api-add-dialog", "添加 API", [
            ("name", "AI 名称：", "例如：爱丽丝", "", False),
            ("api_key", "API Key：", "sk-...", "", True),
            ("base_url", "接口地址：", "", DEFAULT_BASE_URL, False, _addr),
            ("model", "模型名：", "", DEFAULT_MODEL, False, []),
        ]),
        ("manage-api-edit-dialog", "编辑 API", [
            ("name", "AI 名称：", "例如：爱丽丝", "AR1S", False),
            ("base_url", "接口地址：", "", "https://api.deepseek.com", False, _addr),
            ("model", "模型名：", "", "deepseek-flash", False, []),
        ]),
    ]
    for name, title, fields in cases:
        dlg = gui.ApiFormDialog(title, fields, win)
        dlg.show()
        settle(400)
        path = OUT_DIR / f"{name}.png"
        dlg.grab().save(str(path))
        print(f"saved {path.name:30s} size={dlg.width()}x{dlg.height()} "
              f"edits={len(dlg.edits)} pwd={dlg.edits.get('api_key').echoMode() if 'api_key' in dlg.edits else '-'}")
        dlg.close()
        settle(120)

    # 两张展开态：地址那 6 家 / 切到 Kimi 后的模型清单（用户口径「下拉条里显示几个模型」）
    dlg = gui.ApiFormDialog("添加 API", cases[0][2], win)
    dlg.show()
    settle(400)
    for name, attr, pick in (("manage-api-add-address-list", "base_url", None),
                             ("manage-api-add-model-list", "model",
                              "Kimi · https://api.moonshot.cn/v1")):
        if pick:
            _b = dlg.edits["base_url"]
            _b.setCurrentIndex(_b.findText(pick))     # 先切到 Kimi ⇒ 模型清单跟着换
            settle(160)
        _c = dlg.edits[attr]
        _c.showPopup()
        settle(240)
        _view = _c.view().window()
        path = OUT_DIR / f"{name}.png"
        _view.grab().save(str(path))
        print(f"saved {path.name:30s} size={_view.width()}x{_view.height()}")
        _c.hidePopup()
        settle(120)
    dlg.close()


def shoot_preset():
    """设定卡（管理区第三页）+ 「查看」弹窗（2026-09-30 新增；同日第二批加到两张预设）。

    核对点：
    - 左栏管理导航**三项**、末项「设定卡」选中（浅蓝底整列 + 蓝底白字）；
    - 右栏标题「设定卡」、分组「预设」、**两张卡**（wiki 版 / 局内聊天记录统计版）：
      卡片 = **实心圆单选（只有当前生效的那份是选中态）+ 预设命名 + 右端蓝底白字「查看」**；
      ★**整张卡点得动 = 切换**（2026-09-30 晚）；细则 `docs/02` §25.10 / §25.17。
    - ★**hover 终态另出一张 `manage-preset-hover.png`**（2026-09-30 晚·第五批）：**挑一张未选中的卡**
      置成 hover —— 底色 200ms 白 → 淡蓝 `#E6F1FB`、描边保持 `#CBD5E1`，与「管理 API」/「管理唤醒词」
      的卡片同一条（用户口径「参照管理 api 和管理唤醒词里的卡片效果」）。
      出这张的目的：**证明淡蓝底上那颗实心圆单选（灰圈 / 蓝实心圆）依然看得清** ——
      这正是早先「只染描边、不敢填底色」的顾虑，现在用图钉死。默认态仍在 `manage-preset.png`。
      ★**别写死第几张**：本机 config 里「当前选中的是哪张」会随用户点击漂移 ⇒ 用
      `next(c for c in cards if not c._dot.isChecked())` 现挑（全选中时退化成最后一张）。
    - 弹窗：窗口 = 卡片 = **540×460**（2026-09-30 定稿；那圈 12px 透明边随「点弹窗外关闭」一起删了）、
      五项各有一个 `presetFieldBox` 文本框、右侧给滚动条留通道、底部一颗「关闭」。
      ★**唯一的关法就是那颗「关闭」**（用户拍板）—— 弹窗上不再有应用级过滤器 / `paintEvent` /
      `mousePressEvent` 那三层，`OUTER` 常量也删了（细则 `docs/02` §25.6）。
    ★两张预设**各出一张**弹窗图（`-dialog` / `-dialog-chatlog`）—— 它们是两份不同的人设文件，
      只出一张会让「第二张指向同一个文件」这种错看不出来。
    `win.grab()` 抓不到 `PresetViewDialog`（独立顶层窗），必须单独 `grab()`。
    """
    win._select_nav(1)
    win._show_manage_page(win.PAGE_PRESET)
    settle()
    path = OUT_DIR / "manage-preset.png"
    win.grab().save(str(path))
    panel = win._preset_panel
    cards = panel._body.findChildren(gui._PresetCard)
    print(f"saved {path.name:22s} page={win._right_stack.currentIndex()} "
          f"nav={[(b.text(), b.isChecked()) for _i, b in win._manage_nav_btns]} "
          f"preset={panel.current_name()!r} "
          f"cards={[(c._name_text, c._dot.isChecked()) for c in cards]} "
          f"left_bg={win.grab().toImage().pixelColor(20, 400).name()}")

    # ★2026-09-30 晚（第五批）：预设卡 hover 终态 —— 与「管理 API」/「管理唤醒词」的卡片同一条
    #   （底色 200ms 白 → 淡蓝；描边不动）。静态页面图抓不到 hover ⇒ 单独把**一张未选中的卡**
    #   置成 hover 抓一张，一眼就能对照「淡蓝底上圆点的灰圈 / 描边都还看得清」。
    #   ★优先挑**未选中**那张（本机 config 的当前预设可能是任意一张，写死下标会随环境漂移）；
    #    全都选中（只有一张卡）时退化成最后一张。
    if cards:
        target = next((c for c in cards if not c._dot.isChecked()), cards[-1])
        force_hover(target)
        settle(200)
        path_h = OUT_DIR / "manage-preset-hover.png"
        win.grab().save(str(path_h))
        print(f"saved {path_h.name:28s} hovered={target._name_text!r} "
              f"checked={target._dot.isChecked()} hover={target._hover} "
              f"is_white={'rgb(255,255,255)' in target.styleSheet()} "
              f"is_hover_blue={'rgb(230,241,255)' in target.styleSheet()} "
              f"border_static={'border:1px solid #CBD5E1' in target.styleSheet()}")

    # 「查看」弹窗：每张预设各抓一张（按面板同一条口径装好五行，再单独抓弹窗自己）
    presets = [p for p in panel._presets() if isinstance(p, dict)]
    if not presets:
        print("  ⚠️ 当前角色没有预设 —— 跳过弹窗截图")
        return
    for idx, item in enumerate(presets):
        # ★2026-09-30 晚：人设载体改成「全文」后，取值走 `resolve_persona_text`、
        #   解析走 `persona_sections_from_text(text)`（**不再**拼 BASE 路径读文件）—— 见 docs/02 §25.17。
        #   与 `PresetPanel._on_view` 同一条口径（两处必须一致，否则截图与真弹窗会漂移）。
        fields = gui.persona_sections_from_text(gui.resolve_persona_text(item.get("persona")))
        rows = [(title, fields.get(key) or gui.PRESET_EMPTY)
                for key, title, _head in gui._PRESET_FIELDS]
        rows.append(("回复语言", gui.preset_language_name()))
        dlg = gui.PresetViewDialog(win, str(item.get("name") or ""), rows)
        dlg.show()
        settle(400)
        name = ("manage-preset-dialog.png" if idx == 0
                else "manage-preset-dialog-chatlog.png")
        path = OUT_DIR / name
        dlg.grab().save(str(path))
        boxes = dlg.findChildren(gui.QFrame, "presetFieldBox")
        print(f"saved {name:30s} window={dlg.width()}x{dlg.height()} "
              f"card={dlg._card.width()}x{dlg._card.height()} "
              f"fields={len(boxes)} box_h={[b.height() for b in boxes]}")
        dlg.close()
        settle(120)


def shoot_danger_countdown():
    """危险操作倒计时弹窗（关机 / 重启…）：**屏幕正中央**的 200×150 卡片（窗口 200×165）。

    核对点：白底 + **16px 圆角** + `1px #E6F1FB` 边框（与添加 / 编辑 / 删除三款弹窗同一条皮肤）、
    标题（13px 深蓝）+ 大号秒数（34px 主蓝）+ 一行**两个按钮**（左「立刻关机」蓝底白字 /
    右「取消」白底灰边）、无系统标题栏；第二张是**取消态**（整体转红 + 两个按钮消失）。
    `win.grab()` 抓不到它（`Qt.Tool` 独立顶层窗），单独 `grab()`；居中另打印**卡片**几何中心的实测值。
    """
    win.show_danger_countdown("关机", 12)
    settle(700)                        # 等入场动画（50%->100% + 自下而上 15px / 0.5s）落位
    dlg = win._danger_dlg
    path = OUT_DIR / "danger-countdown.png"
    dlg.grab().save(str(path))
    geo = dlg.screen().availableGeometry() if dlg.screen() is not None else QRect()
    # 卡片本体在窗口**顶部**（多出来的 15px 全在下方，给弹出位移用）-> 卡片中心 = 窗口 y + 卡片高/2
    cx, cy = dlg.x() + dlg.SIZE[0] / 2, dlg.y() + dlg.SIZE[1] / 2
    center_ok = (cx == geo.x() + geo.width() / 2 and cy == geo.y() + geo.height() / 2)
    run_r, cancel_r = dlg.buttons
    print(f"saved {path.name:26s} size={dlg.width()}x{dlg.height()} dpr={dlg.devicePixelRatioF()} "
          f"title={dlg.title_text} num={dlg.number_text} buttons={len(dlg.buttons)} "
          f"run_btn={run_r.width():.0f}x{run_r.height():.0f} center_ok={center_ok} "
          f"pos={dlg.pos()} screen={geo.width()}x{geo.height()}")
    win.cancel_danger_countdown()      # 取消态：整体转红 + 两个按钮消失（保持 1.5s 再淡出）
    settle(300)
    path2 = OUT_DIR / "danger-countdown-cancelled.png"
    dlg.grab().save(str(path2))
    print(f"saved {path2.name:26s} title={dlg.title_text} num={dlg.number_text!r} "
          f"cancelled={dlg.cancelled} buttons={len(dlg.buttons)}")
    win.hide_danger_countdown()
    settle(900)                        # 红色态自己淡出（1.5s + 0.5s）跑完


def shoot_general_autostart_on():
    """通用设置的「开机自启 = 开启」态（文档用）：临时让 autostart 报告已启用。

    本机若真开着自启，这张图与 `settings-general.png` 会一样；关着时它用来记录
    「蓝轨道滑块拨到开」的样子。**绝不写注册表**（说明小字 2026-09-18 起全删，行里只剩标题）。
    """
    from app import autostart as _as

    real = (_as.is_enabled, _as.current_command)
    gen = win._settings_panels["general"]
    try:
        _as.is_enabled = lambda: True
        # 直接报出本机真实的启动命令行（含 --autostart），不用手写占位串
        _as.current_command = lambda: _as.launch_command()
        win._show_settings_page(win._settings_index["general"])
        gen.refresh()
        settle()
        path = OUT_DIR / "settings-general-autostart-on.png"
        win.grab().save(str(path))
        row = gen._autostart_row
        print(f"saved {path.name:34s} switch={'on' if row.is_enabled() else 'off'} "
              f"checked={row._switch.isChecked()} hint={row._hint_text!r} "
              f"hint_visible={row._hint.isVisible()}")
    finally:
        _as.is_enabled, _as.current_command = real
        gen.refresh()
        settle()


def shoot_general_pet_row():
    """通用设置的「桌宠调整」分组：滚到底，让两行都完整入镜。

    2026-09-19 起这个分组是「音量」（左「音量」二字 + 右 `[−] ──── [+]`）在上、
    「重置角色位置」在下 —— 后者在页面最下方，默认视图（`settings-general.png`）里只露出一截，
    所以单独出一张。两行的控件都是常驻的（不像权限页那种 hover 才淡入），滚到就能看全。
    """
    gen = win._settings_panels["general"]
    win._show_settings_page(win._settings_index["general"])
    settle()
    gen.refresh()
    sb = gen._scroll.verticalScrollBar()
    sb.setValue(sb.maximum())
    settle(300)
    path = OUT_DIR / "settings-general-pet.png"
    win.grab().save(str(path))
    row = getattr(gen, "_reset_pos_row", None)
    vol = getattr(gen, "_volume_row", None)
    print(f"saved {path.name:24s} scroll={sb.value()}/{sb.maximum()} "
          f"vol={vol._slider.value() if vol is not None else None} "
          f"bar={vol._slider.width() if vol is not None else None}px "
          f"row_y={row.y() if row is not None else None} "
          f"btn={row._button.text() if row is not None else None}")


def force_hover(row):
    """把某一行置成 hover 终态（截图用：删除按钮 / 滑块在 hover 时才淡入）。"""
    row._hover_anim.stop()
    row._apply_bg(1.0)
    return row


def shoot_permissions_rename():
    """权限页：自定义软件行（蓝「重命名」+ 红「删除」）的 hover 终态。

    临时造一条「从磁盘添加的软件」（exe 是假路径，只做展示、绝不会被执行），
    让「重命名」按钮出现在面板里；再单独抓一张删除确认弹窗的卡片图。
    截完把权限复原，不影响后续截图。
    """
    from app import tools as _t

    perm = win._settings_panels["permissions"]
    win._show_settings_page(win._settings_index["permissions"])
    settle()
    try:
        _t.apply_permissions({
            "allowed_apps": ["记事本", "WeaselSetup"],
            "custom_apps": {"WeaselSetup": "D:/Games/WeaselSetup.exe"},
        })
        perm._materialize()
        perm._rebuild()
        settle(300)
        groups = perm._body.findChildren(gui._CollapsibleGroup)
        apps_group = groups[1]                      # 目录 / 软件 / 操作类型 / 禁止词
        # 只留「可启动软件」展开，其余收起 —— 截图本体要干净
        for _i, _g in enumerate(groups):
            _g.set_collapsed(_i != 1, animate=False)
        settle(300)
        rows = [apps_group.body_lay.itemAt(i).widget()
                for i in range(apps_group.body_lay.count())]
        rows = [r for r in rows if isinstance(r, gui._PermRow)]
        target = next((r for r in rows if r._btn_extra is not None), None)
        if target is not None:
            # 滚到软件分组（否则「重命名」那一行还在可视区之下）；留 100px 余量，
            # 上面那组折叠态的卡片就不会被切一半
            sb = perm._scroll.verticalScrollBar()
            group_y = apps_group.mapTo(perm._body, QPoint(0, 0)).y()
            sb.setValue(max(0, min(group_y - 100, sb.maximum())))
            settle(300)
            force_hover(target)
            settle(200)
            path = OUT_DIR / "settings-permissions-rename.png"
            win.grab().save(str(path))
            print(f"saved {path.name:34s} rows={len(rows)} "
                  f"extra={target._btn_extra.text()!r} "
                  f"opacity=({round(target._btn_extra_effect.opacity(), 2)}, "
                  f"{round(target._btn_effect.opacity(), 2)}) "
                  f"scroll={sb.value()}/{sb.maximum()}")

        # 「免 UAC」**开启确认窗**（用户要求「必须点确认才能开启」，且**不再有悬停气泡**）：
        # 单独抓一次（`win.grab()` 不含子对话框）
        if target is not None and target._switch is not None:
            _uac_msg = (
                "开启后，打开「WeaselSetup」不再弹出 UAC 授权框。\n\n"
                "需要一次管理员授权，之后一直有效。"
            )
            dlg = gui.ConfirmDialog(win, _uac_msg, "确认", "取消")
            dlg.show()
            settle(400)
            path = OUT_DIR / "settings-permissions-uac-confirm.png"
            dlg.grab().save(str(path))
            print(f"saved {path.name:34s} size={dlg.width()}x{dlg.height()}")
            dlg.close()
            settle(150)

        # 删除确认弹窗：单独抓弹窗自己的卡片（`win.grab()` 不含子对话框）
        dlg = gui.ConfirmDialog(win, "确定要删除软件「WeaselSetup」吗？此操作不可撤销。")
        dlg.show()
        settle(400)
        path = OUT_DIR / "settings-permissions-delete-confirm.png"
        dlg.grab().save(str(path))
        print(f"saved {path.name:34s} size={dlg.width()}x{dlg.height()}")
        dlg.close()
        settle(150)
    finally:
        _t.apply_permissions({})
        perm._materialize()
        perm._rebuild()
        settle(200)


def shoot_chat_reply():
    """一条完整回复的模样（文档用）：问一句 + 一个助理气泡。

    核对点：一条回复就是**一个**气泡、里面是**完整中文**（整段合成方案下，文字与声音
    同刻出现、不再逐段回填），且界面**只有中文**（日语只进语音）。截完清空，
    不污染聊天记录。
    """
    win._select_nav(0)
    settle()
    cv = win._chat_view
    key = win._current_role_key
    name = (win.cfg["roles"].get(key) or {}).get("name", "")
    cv.clear()
    cv.add_bubble("user", "你", "今天适合做点什么？")
    bubble = cv.add_bubble(
        "assistant", name,
        "今天天气不错，很适合出门走走。不过午后可能有阵雨，记得带把伞。",
        role_key=key,
    )
    settle(500)
    path = OUT_DIR / "chat-reply.png"
    win.grab().save(str(path))
    rows = cv._rows_lay.count() - 1  # 去掉末尾 stretch
    print(f"saved {path.name:22s} rows={rows} bubble_h={bubble.height()} "
          f"label_h={bubble._lbl.height()}")
    # 复原：清空气泡 + 不落聊天记录，后续截图不受影响
    cv.clear()
    win._chat_history[key] = []
    settle(200)


def shoot_pet_bubble():
    """桌宠聊天气泡（**主界面不在聊天界面时**出现 —— 关着 / 停在管理·设置页）：
    一张「气泡 + 桌宠」合影 + 一张动画采样条。

    核对点：本体固定 120px 宽 / **圆角 3px** / **2px** 深蓝边 `#0C447C` / 淡蓝底 `#E6F1FB` / 文字 `#334155` /
    贴着一个等腰直角三角形尾巴（直角边 15、**三个角同样 3px 圆角**，样式与本体同款：2px 描边 + 淡蓝底；
    **a 与下 / 上边框平行且离它 4 / 5px、b 与右 / 左边框共线**）；
    锚点 A（弹出动画的旋转轴）钉在**贴图左边 −5px、贴图 5/7 高度**处；弹出以 A 为轴「逆时针 15° → 0° + 缩放 0.30 → 1 + 淡入」，
    淡出只掉不透明度；贴图贴边时气泡**平移**让位（左 / 右、上 / 下，500ms）。

    桌宠与气泡是**两个独立的顶层窗**，`win.grab()` 都抓不到，所以各自 grab 再按屏幕相对位置
    用 PIL 拼起来（与 `preview_power_save.py` 同一套做法）。
    """
    from PIL import Image, ImageDraw, ImageFont

    from app import pet as petmod

    def to_pil(pm):
        # QImage 的内存是 BGRA（小端）：直接按 RGBA 读会**红蓝互换**（#0C447C 会画成棕色）。
        # 先转 RGBA8888 再读；它每像素 4 字节、没有行填充，constBits() 可以整块读。
        img = pm.toImage().convertToFormat(QImage.Format_RGBA8888)
        return Image.frombytes("RGBA", (img.width(), img.height()), bytes(img.constBits()))

    def font(size):
        for name in ("msyh.ttc", "msyhbd.ttc", "simhei.ttf", "arial.ttf"):
            try:
                return ImageFont.truetype(name, size)
            except OSError:
                continue
        return ImageFont.load_default()

    BG = (247, 250, 252)
    INK = (51, 65, 85)
    MARK = (220, 38, 38)

    pet = petmod.PetWindow(BASE / "pet" / "alice")
    pet.move(760, 320)
    pet.show()
    settle(300)
    pet.show_bubble("今天天气不错，很适合出门走走。不过午后可能有阵雨，记得带把伞。")
    bubble = pet._bubble
    bubble._pop_anim.stop()          # 逐帧采样，不要真动画
    bubble._pop_anim = None

    # ---- ① 气泡 + 桌宠（真实相对位置、动画终态） ----
    bubble._set_frame(*petmod.bubble_pop_state(1.0))
    app.processEvents()
    bub_img, pet_img = to_pil(bubble.grab()), to_pil(pet.grab())
    dx, dy = pet.x() - bubble.x(), pet.y() - bubble.y()
    pad = 16
    W = max(bubble.width(), dx + pet.width()) + 2 * pad
    # 说明文字：**手写成短行**，别指望自动量宽 —— PIL 量出来的是「加载的那套字体」，
    # 而画的时候缺字会回退到另一套字体，两者宽度对不上（本行就是踩过之后改的）。
    f13 = font(13)
    cap_lines = [
        "红叉 = 锚点 A（旋转轴）",
        "＝ 尾巴尖：贴图左边 −5px、",
        "贴图 5/7 高度处。",
        "尾巴 a ∥ 下边框、离它 4px；",
        "b 与右边框共线；",
        "三个角 3px 圆角，样式与本体同款",
        "（2px 描边 + 淡蓝底）。",
        f"本体 {bubble._body_w}×{bubble.body_height}（宽固定、高随文字量）。",
    ]
    cap = 6 + 17 * len(cap_lines)
    H = max(bubble.height(), dy + pet.height()) + 2 * pad + cap
    canvas = Image.new("RGB", (W, H), BG)
    canvas.paste(pet_img, (dx + pad, dy + pad), pet_img)
    canvas.paste(bub_img, (pad, pad), bub_img)
    d = ImageDraw.Draw(canvas)
    ax = bubble.x() + round(bubble.anchor_point.x()) - bubble.x() + pad
    ay = bubble.y() + round(bubble.anchor_point.y()) - bubble.y() + pad
    d.line([ax - 7, ay, ax + 7, ay], fill=MARK, width=1)     # 锚点 = 尾巴尖 = 动画的旋转轴
    d.line([ax, ay - 7, ax, ay + 7], fill=MARK, width=1)
    for _i, _line in enumerate(cap_lines):
        d.text((pad, H - cap + 4 + _i * 17), _line, font=f13, fill=INK)
    canvas.save(str(OUT_DIR / "pet-bubble.png"))
    print(f"saved pet-bubble.png      {canvas.size} bubble_win={bubble.width()}x{bubble.height()} "
          f"body={bubble._body_w}x{bubble.body_height} pet=({pet.x()},{pet.y()}) "
          f"anchor=({ax - pad},{ay - pad}) opacity={bubble.pop_pose[2]:.2f}")

    # ---- ② 弹出 / 淡出逐帧采样（锚点在控件里的位置固定 → 直接对比旋转与缩放） ----
    # (标签, 进度 p, 绘制不透明度, 动画真实不透明度)
    # 前四帧的绘制值强制 1.00 —— 真实值淡得看不清形状；标签里的 a 显示的是**动画真实值**。
    frames = [("p=0.25", 0.25, 1.0, 0.25), ("p=0.50", 0.5, 1.0, 0.50), ("p=0.75", 0.75, 1.0, 0.75),
              ("p=1.00  终态", 1.0, 1.0, 1.0), ("淡出 opacity=0.5", 1.0, 0.5, 0.50)]
    shots = []
    for label, p, draw_a, true_a in frames:
        angle, scale, _ = petmod.bubble_pop_state(p)
        bubble._set_frame(angle, scale, draw_a)
        app.processEvents()
        shots.append((label, to_pil(bubble.grab()), angle, scale, true_a, draw_a))
    pw, ph = bubble.width() + 18, bubble.height() + 40
    strip = Image.new("RGB", (len(shots) * pw + 18, ph + 44), BG)
    ds = ImageDraw.Draw(strip)
    f1, f2 = font(13), font(12)
    for i, (label, img, angle, scale, true_a, draw_a) in enumerate(shots):
        x0 = 9 + i * pw
        strip.paste(img, (x0 + 9, 30), img)
        mx, my = x0 + 9 + round(bubble.anchor_point.x()), 30 + round(bubble.anchor_point.y())
        ds.line([mx - 5, my, mx + 5, my], fill=MARK, width=1)
        ds.line([mx, my - 5, mx, my + 5], fill=MARK, width=1)
        star = "*" if abs(true_a - draw_a) >= 0.005 else ""   # * = 为看清形状强制按 1.00 绘制
        ds.text((x0 + 9, 6), label, font=f1, fill=INK)
        ds.text((x0 + 9, 20), f"{angle:+.0f}deg  x{scale:.2f}  a={true_a:.2f}{star}", font=f2,
                fill=(100, 116, 139))
    ds.text((9, ph + 12),
            "以红叉（尾巴尖）为轴：逆时针 15° + 缩放 0.30 + 全透明 → 0° + 1.00 + 不透明；"
            "淡出只掉不透明度，不反向旋转、不缩小。",
            font=f2, fill=(148, 163, 184))
    ds.text((9, ph + 28),
            "a = 动画真实不透明度；* = 该帧为看清形状按 1.00 绘制"
            "（真实曲线过 OutCubic 缓动，弹入很快）。",
            font=f2, fill=(148, 163, 184))
    strip.save(str(OUT_DIR / "pet-bubble-pop.png"))
    print(f"saved pet-bubble-pop.png  {strip.size} frames={len(shots)} "
          f"poses={[tuple(round(v, 2) for v in petmod.bubble_pop_state(p)) for _l, p, _d, _o in frames]}")

    # ---- ③ 翻转：贴图贴边时气泡让位（平移 500ms；这里直接看落位终态） ----
    def flip_panel(pet_xy):
        """把桌宠摆到指定位置，跳过平移动画，拼一张「贴图 + 气泡」合影。"""
        pet.move(*pet_xy)
        app.processEvents()
        bubble._stop_anims()
        bubble._on_flip_done()            # 直接落位到目标点（不等 500ms）
        app.processEvents()
        b_img, p_img = to_pil(bubble.grab()), to_pil(pet.grab())
        items = ((b_img, bubble.x(), bubble.y()), (p_img, pet.x(), pet.y()))
        x0 = min(it[1] for it in items)
        y0 = min(it[2] for it in items)
        x1 = max(it[1] + it[0].width for it in items)
        y1 = max(it[2] + it[0].height for it in items)
        cw, ch = x1 - x0 + 2 * pad, y1 - y0 + 2 * pad
        cv = Image.new("RGB", (cw, ch), BG)
        for img, wx, wy in items:
            cv.paste(img, (wx - x0 + pad, wy - y0 + pad), img)
        dc = ImageDraw.Draw(cv)
        mx = bubble.x() + round(bubble.anchor_point.x()) - x0 + pad
        my = bubble.y() + round(bubble.anchor_point.y()) - y0 + pad
        dc.line([mx - 7, my, mx + 7, my], fill=MARK, width=1)
        dc.line([mx, my - 7, mx, my + 7], fill=MARK, width=1)
        return cv, (bubble.side, bubble.face)

    panels = [
        ("① 贴图贴到屏幕左边：左侧不足 120px → 气泡平移让到右侧"
         "（b 改与左边框共线）", (40, 320)),
        ("② 贴图顶出屏幕上沿：锚点上方装不下 → 挂到贴图 2/7 高度"
         "（尾巴朝上：a 在上边框上方 5px）", (760, -20)),
        ("③ 拖回原位：空间重新够了 → 平移回左侧 5/7 高度，位置与初始完全一致",
         (760, 320)),
    ]
    fps = [flip_panel(xy) for _cap, xy in panels]
    # 单元格宽度要同时装得下图与说明（说明比图宽时按说明算，否则会压到隔壁那格上）
    _meas = ImageDraw.Draw(Image.new("RGB", (1, 1)))

    def _wrap(text, fnt, width):
        lines, cur = [], ""
        for ch in text:
            if _meas.textlength(cur + ch, font=fnt) <= width:
                cur += ch
            else:
                lines.append(cur)
                cur = ch
        if cur:
            lines.append(cur)
        return lines

    CELL = max([max(im.width for im, _st in fps)] + [300])
    caps = [_wrap(cap, f2, CELL) for cap, _xy in panels]
    cap_h = max(len(ls) for ls in caps) * 17 + 6
    fh = max(im.height for im, _st in fps) + 30 + cap_h + 30
    fw = CELL + 18
    fstrip = Image.new("RGB", (len(fps) * fw + 18, fh), BG)
    df = ImageDraw.Draw(fstrip)
    for i, (im, st) in enumerate(fps):
        x0 = 9 + i * fw
        df.text((x0, 6), f"side={st[0]}  face={st[1]}", font=f1, fill=INK)
        fstrip.paste(im, (x0, 30))
        for k, line in enumerate(caps[i]):
            df.text((x0, 36 + max(im.height for im, _st in fps) + k * 17), line,
                    font=f2, fill=INK)
    df.text((9, fh - 24),
            "让位是平移（500ms OutCubic）：不重放弹出动画、不缩放、不旋转、不改不透明度；"
            "左右 / 上下各 20px 迟滞，贴边来回拖不会来回翻。", font=f2, fill=(148, 163, 184))
    fstrip.save(str(OUT_DIR / "pet-bubble-flip.png"))
    print(f"saved pet-bubble-flip.png  {fstrip.size} panels={len(fps)} states={[st for _im, st in fps]}")

    bubble.close()
    pet.close()
    settle(120)


def shoot_pet_bubble_pages():
    """长回复**分段显示**（四改）：把「第一段 / 淡出中 / 第二段 / 最后一段」四个时刻拼成一条。

    核对点：单段正文块高 ≤ 96px（真机行高 17px → 5 行、离屏回退字体 15px → 6 行）；
    段间**只淡文字**（淡出 / 淡入各 200ms）—— ② 那张里文字明显变浅，**边框与尾巴一点没淡**；
    换段时本体高按新段重算（④ 比 ① 矮）；各段都是原文的切片，拼起来一字不差。
    """
    from PIL import Image, ImageDraw

    from app import pet as petmod

    def to_pil(pm):
        img = pm.toImage().convertToFormat(QImage.Format_RGBA8888)
        return Image.frombytes("RGBA", (img.width(), img.height()), bytes(img.constBits()))

    def font(size):
        from PIL import ImageFont
        for name in ("msyh.ttc", "msyhbd.ttc", "simhei.ttf", "arial.ttf"):
            try:
                return ImageFont.truetype(name, size)
            except OSError:
                continue
        return ImageFont.load_default()

    BG = (247, 250, 252)
    INK = (51, 65, 85)
    GREY = (148, 163, 184)

    LONG = ("今天天气不错，很适合出门走走。不过午后可能有阵雨，记得带把伞。"
            "你昨天说的那本书我看完了，第三章节写得特别好，尤其是那段关于旅行的描写，"
            "让我想起我们去年夏天在海边待的那几天。要不要这周末一起去图书馆？"
            "顺便把那件外套还给你，它一直挂在我衣柜里占地方。")

    pet = petmod.PetWindow(BASE / "pet" / "alice")
    pet.move(760, 320)
    pet.show()
    settle(300)
    pet.show_bubble(LONG)
    bubble = pet._bubble
    bubble._stop_anims()             # 逐帧采样，不要真动画（段定时器也一并停掉）
    bubble._on_pop_done()

    def advance_to(k):
        while bubble.page_index < k:
            bubble._on_text_out_done()
            if bubble._page_anim is not None:
                bubble._page_anim.stop()
                bubble._page_anim = None

    shots = []
    bubble._set_text_op(1.0)
    app.processEvents()
    shots.append(("① 第一段", to_pil(bubble.grab()), bubble.page_index))
    bubble._set_text_op(0.5)         # 淡出推到一半：只淡文字
    app.processEvents()
    shots.append(("② 淡出中：只淡文字", to_pil(bubble.grab()), None))
    bubble._set_text_op(0.0)
    advance_to(1)
    bubble._set_text_op(1.0)
    app.processEvents()
    shots.append(("③ 第二段", to_pil(bubble.grab()), bubble.page_index))
    advance_to(bubble.page_count - 1)
    bubble._set_text_op(1.0)
    app.processEvents()
    shots.append(("④ 最后一段", to_pil(bubble.grab()), bubble.page_index))

    pages = list(bubble._pages)
    last_i = len(pages) - 1
    dwell = petmod.bubble_page_dwell_ms
    caps = [
        [f"{len(pages[0])} 字，停 {dwell(pages[0]) / 1000:.1f}s"],
        ["文字 50% 不透明度；", "本体与尾巴仍是 100%"],
        [f"{len(pages[1])} 字，停 {dwell(pages[1]) / 1000:.1f}s", "换段时本体高重算"],
        [f"{len(pages[last_i])} 字，停 {dwell(pages[last_i]) / 1000:.1f}s", "留在桌上，直到这一轮结束"],
    ]
    pw = max(im.width for _l, im, _k in shots) + 18
    img_h = max(im.height for _l, im, _k in shots)
    cap_h = 20 + 17 * max(len(c) for c in caps)
    ph = img_h + cap_h
    f13, f12 = font(13), font(12)
    strip = Image.new("RGB", (len(shots) * pw + 18, ph + 58), BG)
    ds = ImageDraw.Draw(strip)
    ds.text((9, 6), f"长回复分段显示（四改）：切了 {len(pages)} 段，段长 {[len(p) for p in pages]}，"
                    f"单段正文块高 ≤ {petmod.BUBBLE_MAX_TEXT_H}px", font=f13, fill=INK)
    for i, (label, im, _k) in enumerate(shots):
        x0 = 9 + i * pw
        ds.text((x0, 26), label, font=f12, fill=INK)
        strip.paste(im, (x0, 46), im)
        for k, line in enumerate(caps[i]):
            ds.text((x0, 46 + img_h + 4 + k * 17), line, font=f12, fill=INK)
        if i == 0:                    # 只标第一张的锚点，免得四张都画红叉
            mx = x0 + round(bubble.anchor_point.x())
            my = 46 + round(bubble.anchor_point.y())
            ds.line([mx - 5, my, mx + 5, my], fill=(220, 38, 38), width=1)
            ds.line([mx, my - 5, mx, my + 5], fill=(220, 38, 38), width=1)
    ds.text((9, ph + 32), "段间 = 本段淡出 200ms → 换字（此刻改高度）→ 下一段淡入 200ms，只淡文字；"
                          "每段停留 max(1.2s, 0.22s × 字数)，与说话态同一条标定。",
            font=f12, fill=GREY)
    strip.save(str(OUT_DIR / "pet-bubble-pages.png"))
    print(f"saved pet-bubble-pages.png {strip.size} pages={len(pages)} "
          f"段长={[len(p) for p in pages]} 末段本体={bubble._body_w}x{bubble.body_height}")

    bubble.close()
    pet.close()
    settle(120)


def shoot_pet_menu():
    """桌宠右键弹窗（`_build_menu()` 非模态弹出后 grab）：核对弹窗皮肤、音量条与菜单项。

    2026-09-19 八改：容器从 `QMenu` 换成**自绘弹窗** `_MenuPopup`（`QMenu` 缩放不了，只能整窗
    改不透明度）。样式逐项照原菜单：
    白底 + 1px 黑边 + 圆角 3px、行内边距 8×14、hover 浅蓝底深蓝字、分隔线 #CBD5E1、勾选、小尖。
    最顶端一条音量条（行高 = 菜单项高 28px、宽 = `MENU_CONTENT_W` = 145px）
    → 弹窗 **155×242**（真机 9pt 字号）；「切换」二级弹窗**边框紧贴**一级弹窗（gap = 0）。
    2026-09-19 十六改：宽度**不再跟贴图走**（原来两处都写 `_base_w − MENU_NARROW`，而 `_base_w` 是按
    贴图宽高比推的）—— 现在由 `MENU_REF_W`/`MENU_CONTENT_W` 钉死，**换成方形贴图的角色
    （艾莲 256×256 → 250）也还是 155px**。所以本图对任何角色都该是同一张。

    2026-09-19 十改：窗口尺寸**就是面板尺寸**（不再多留 20px 动画余量），整窗刷成菜单背景色。
    2026-09-19 十二改：时长 0.5s → **0.3s**（弹出 / 淡出 / 二级淡入都是 0.3s，宽限 0.5s）。
    2026-09-19 十三改：二级宽限 **0s**（一离开「切换」行就立刻淡出）+ region 两轴跟面板缩放。
    2026-09-19 十四改：**彻底去掉缩放** —— 一级 / 二级都只做不透明度（淡入的底 = 抓来的真桌面）。
    ⚠️ 宽限 0 之后，截二级弹窗**必须先 `menu._poll.stop()`** —— 真光标不在「切换」行上，
    `settle()` 里第一拍就把二级关掉了，`grab()` 抓到的是空窗（十二改时这里就已经踩过一次：
    宽限 0.5s < `settle(800ms)`，抓到的二级弹窗其实只剩 **alpha 0.15**，一直到十三改才发现）。
    这里只需 ≥ 0.3s 就够落位，下面两处 `settle` 取 **800ms**（留足余量，顺便确认终态没变化）。

    弹窗是**独立顶层窗**、真机上手点时走 `pop_up()` + `run()`（模态阻塞）—— 那样截不了图，
    所以这里只 `pop_up()`（等动画跑到终态）再 `grab()`。截图前把检验开关**勾上**，
    正好把「勾选项已勾选」的样子一起留档（design.md 4.10）。
    """
    from app import pet as petmod

    pet = petmod.PetWindow(BASE / "pet" / "alice")
    pet.move(700, 300)
    pet.show()
    settle(400)
    # ★2026-09-28：菜单项「显示聊天气泡」已下架 ⇒ 截图里不再有那一行；这里保留开关状态，
    #   等菜单项解注恢复时，截图即回到「勾选项已勾选」的样子（没接回调，不会真冒气泡）。
    pet.set_bubble_preview(True)
    # 角色表要自己填（真机上是 main.py 填的）：不填的话「切换」二级弹窗是空的（10×10）
    pet.set_roles([("爱丽丝", "alice"), ("Ellen", "ellen")])
    pet.set_current_role("alice")
    menu = pet._build_menu()
    size = menu.sizeHint()
    menu.pop_up(QRect(pet.mapToGlobal(QPoint(12, 24)), size), "right")
    settle(800)                            # 等弹出动画跑完（0.3s：只做不透明度，不缩放）
    path = OUT_DIR / "pet-menu.png"
    menu.grab().save(str(path))
    bar = menu.bar()
    print(f"saved {path.name:22s} size={size.width()}x{size.height()} "
          f"volbar={bar.width() if bar is not None else None}px "
          f"slider={bar.slider.geometry().getRect() if bar is not None else None} "
          f"items={[menu.row_text(i) for i in range(len(menu.rows()))]} "
          f"checked={[r.get('checked') for r in menu.rows() if r.get('checkable')]}")
    sub = menu.submenu()
    menu._show_submenu()
    # ⚠️ 十三改：二级弹窗的**离开宽限已经是 0**（鼠标一离开「切换」行就立刻淡出）。这里是静态截图，
    # 真光标并不在那一行上 —— 不停掉宽限计时的话，`settle()` 里第一拍（100ms）就把二级关掉了，
    # `sub.grab()` 抓到的是**已经藏起来的空窗**（实测文件从 2886 B 掉到 368 B）。
    menu._poll.stop()
    settle(800)                            # 二级弹窗：只淡入（0.3s，不缩放，十四改起与一级同一条路）
    sub_path = OUT_DIR / "pet-submenu.png"
    sub.grab().save(str(sub_path))
    _mf, _sf = menu.frameGeometry(), sub.frameGeometry()
    print(f"saved {sub_path.name:22s} size={sub.sizeHint().width()}x{sub.sizeHint().height()} "
          f"gap={_sf.x() - (_mf.x() + _mf.width())}")
    menu.close_animated()
    settle(700)
    pet.set_bubble_preview(False)
    pet.close()
    app.processEvents()


def shoot_pet_toast():
    """桌宠状态提示气泡（贴图**正上方**）：核对样式 / 位置（居中 + 距贴图 5px）/ 四种文案。

    与 shoot_pet_bubble 同一套做法：提示与桌宠是**两个独立顶层窗**，`win.grab()` 抓不到，
    各自 grab 再按屏幕相对位置用 PIL 拼起来。

    ★ **抓下来的图是设备像素，窗口坐标是逻辑像素**（真机 125% 缩放 → dpr 1.25 / 150% → 1.5）：
    偏移与裁剪都必须按 dpr 换算。踩过两次：① 按逻辑宽裁本体 → 只裁到左半边；② 按逻辑偏移贴图
    → 气泡相对贴图被压缩，视觉上直接压在她脑袋上（「距贴图 5px」就假了）。
    """
    from PIL import Image, ImageDraw, ImageFont

    from app import pet as petmod

    def to_pil(pm):
        # QImage 的内存是 BGRA（小端）：直接按 RGBA 读会红蓝互换（#0C447C 会画成棕色）。先转 RGBA8888。
        img = pm.toImage().convertToFormat(QImage.Format_RGBA8888)
        return Image.frombytes("RGBA", (img.width(), img.height()), bytes(img.constBits()))

    def font(size):
        for name in ("msyh.ttc", "msyhbd.ttc", "simhei.ttf", "arial.ttf"):
            try:
                return ImageFont.truetype(name, size)
            except OSError:
                continue
        return ImageFont.load_default()

    BG = (247, 250, 252)
    INK = (51, 65, 85)
    MARK = (220, 38, 38)

    pet = petmod.PetWindow(BASE / "pet" / "alice")
    pet.move(700, 420)
    pet.show()
    settle(300)
    toast = pet._toast
    body_h = int(petmod.TOAST_H)
    S = float(pet.devicePixelRatioF() or 1.0)

    def grab_body():
        """抓当前这一帧的提示**本体**：按 dpr 裁掉窗口比本体高出来的留白，宽度整幅保留。

        本体画在窗口 y = TOAST_POP_DY（上下各留 5px 供弹出 / 收起的位移用），
        所以裁剪要从 `TOAST_POP_DY` 起、到 `TOAST_POP_DY + body_h` 止。
        """
        img = to_pil(toast.grab())
        return img.crop((0, round(petmod.TOAST_POP_DY * S), img.width,
                         round((petmod.TOAST_POP_DY + body_h) * S)))

    def snap():
        toast._on_show_done()
        toast._stop_hold()             # 逐帧截图：别让「停留 2s」到点把文字收走
        app.processEvents()
        return grab_body()

    # ---- ① 「待机中...」+ 桌宠：真实相对位置（核对居中 + 5px）----
    pet.set_state_toast("待机中", dots=True)
    toast.stop_all()                       # 逐帧采样，不要真动画 / 点定时器
    for _ in range(petmod.TOAST_DOT_MAX):
        toast._on_dot()
    toast.stop_all()
    scene_toast = snap()
    sprite = pet._sprite_rect()
    # 桌宠窗**比贴图大**（真机上贴图居中在窗口里）→ 只取贴图那一块，否则拼出来的图里
    # 贴图会比几何位置低一大截，「距贴图 5px」看着就不对了。
    pet_img = to_pil(pet.grab())
    gx, gy = sprite.x() - pet.x(), sprite.y() - pet.y()
    pet_img = pet_img.crop((round(gx * S), round(gy * S),
                            round((gx + sprite.width()) * S), round((gy + sprite.height()) * S)))
    gap_ok = (toast.y() + petmod.TOAST_POP_DY + body_h == sprite.y() - petmod.TOAST_GAP)
    centered = (toast.x() + toast.width() // 2 == sprite.x() + sprite.width() // 2)
    left, top = min(sprite.x(), toast.x()), min(sprite.y(), toast.y())
    right = max(sprite.x() + sprite.width(), toast.x() + toast.width())
    bottom = sprite.y() + sprite.height()
    pd, _to = 14, lambda v: round(v * S)   # 逻辑 → 画布（设备）像素
    scene = Image.new("RGBA", (_to(right - left) + 2 * pd, _to(bottom - top) + 2 * pd), BG + (255,))
    scene.alpha_composite(pet_img, (_to(sprite.x() - left) + pd, _to(sprite.y() - top) + pd))
    scene.alpha_composite(scene_toast,
                          (_to(toast.x() - left) + pd,
                           _to(toast.y() - top + petmod.TOAST_POP_DY) + pd))
    d = ImageDraw.Draw(scene)
    bx0 = _to(toast.x() - left) + pd
    by1 = _to(toast.y() - top + petmod.TOAST_POP_DY + body_h) + pd - 1
    sy0 = _to(sprite.y() - top) + pd
    d.rectangle([bx0 + 2, by1, bx0 + scene_toast.width - 3, max(sy0 - 1, by1 + 2)], outline=MARK)
    # 贴图**顶边**再画一条红线：站姿图顶部留了 62/500 的空像素，光看头发会以为间隙比 5px 大不少
    d.line([(_to(sprite.x() - left) + pd, sy0),
            (_to(sprite.x() - left + sprite.width()) + pd, sy0)], fill=MARK, width=1)
    d.text((bx0 + scene_toast.width + 4, by1 - 5), f"{petmod.TOAST_GAP}px", fill=MARK, font=font(12))

    blocks = [(scene, ["红框 = 气泡下沿距贴图顶边 5px（下面那条红线 = 贴图顶边）；",
                       "气泡横向以贴图中心线居中；本体固定高 30px、宽随文字量变；",
                       "贴图 = 图片盒：站姿图顶上留了空像素，所以视觉上会比 5px 松。"])]

    # ---- ② 另外两种常驻 / 一闪文案（同款样式）----
    pet.set_state_toast("休眠中")
    toast.stop_all()
    blocks.append((snap(), ["休眠中（瞬态）：说了「休息吧」或唤醒超时，",
                            "报一下，2s 后自己淡出。"]))
    pet.set_state_toast("待机中", dots=True)
    toast.stop_all()
    for text, caps in (
        ("已唤醒", ["已唤醒（淡入 0.5s → 停留 2s → 淡出 0.5s）：",
                    "唤醒那一下，淡出后露出底下的「待机中…」。"]),
        ("已进入静音模式", ["已进入静音模式（同样 0.5s / 2s / 0.5s）：",
                            "进 / 出静音模式各弹一句。"]),
        ("已进入节能模式", ["已进入节能模式（同样 0.5s / 2s / 0.5s）：",
                            "进 / 出节能模式各弹一句 —— 2026-09-18 起只要这一句。"]),
    ):
        pet.flash_toast(text)
        blocks.append((snap(), caps))

    # ---- ④ 淡出采样：不透明度 + 由大到小 + 往上 5px（整窗抓，位移才看得见）----
    pet.set_state_toast("休眠中")
    toast._on_show_done()
    toast._stop_hold()
    fade_frames = []
    for _v in (1.0, 0.75, 0.5, 0.25):
        toast._set_frame(_v, -petmod.TOAST_POP_DY * (1.0 - _v),
                         petmod.TOAST_MIN_SCALE + (1.0 - petmod.TOAST_MIN_SCALE) * _v)
        app.processEvents()
        fade_frames.append(to_pil(toast.grab()))
    _gap = 12
    strip = Image.new("RGBA",
                      (sum(f.width for f in fade_frames) + _gap * (len(fade_frames) - 1),
                       max(f.height for f in fade_frames)), BG + (255,))
    _x = 0
    for f in fade_frames:
        strip.alpha_composite(f, (_x, 0))
        _x += f.width + _gap
    blocks.append((strip, ["淡出（0.5s）：不透明度 1→0、由大到小（100%→50%）、整条再往上 5px ——",
                           "四帧依次是 100% / 75% / 50% / 25%，最后一帧几乎看不见了。"]))

    # ---- ⑤ 让位：贴图顶到屏幕上沿 → 提示平移到贴图**下方** 5px（0.5s 平移）----
    pet.set_state_toast("待机中", dots=True)
    toast._on_hold_done()                                 # 把上一块留下的事件层收掉，这一格才画得出「待机中…」
    for _ in range(petmod.TOAST_DOT_MAX):
        toast._on_dot()
    toast.stop_all()
    toast._on_show_done()
    _av = pet._avail_rect()
    _sp = pet._sprite_rect()
    pet.move(pet.x(), _av.y() - (_sp.y() - pet.y()))   # 贴图**顶边**贴屏幕上沿：上方只剩 0px
    app.processEvents()
    toast.stop_all()
    toast._on_flip_done()                              # 让位动画的落点（截图不做动画）
    app.processEvents()
    scene_toast_b = snap()
    sprite_b = pet._sprite_rect()
    pet_img_b = to_pil(pet.grab())
    gx_b, gy_b = sprite_b.x() - pet.x(), sprite_b.y() - pet.y()
    pet_img_b = pet_img_b.crop((round(gx_b * S), round(gy_b * S),
                                round((gx_b + sprite_b.width()) * S), round((gy_b + sprite_b.height()) * S)))
    below_ok = (toast.above is False
                and toast.y() + petmod.TOAST_POP_DY == sprite_b.y() + sprite_b.height() + petmod.TOAST_GAP)
    left_b, top_b = min(sprite_b.x(), toast.x()), min(sprite_b.y(), toast.y())
    right_b = max(sprite_b.x() + sprite_b.width(), toast.x() + toast.width())
    bottom_b = max(sprite_b.y() + sprite_b.height(), toast.y() + toast.height())
    scene_b = Image.new("RGBA", (_to(right_b - left_b) + 2 * pd, _to(bottom_b - top_b) + 2 * pd), BG + (255,))
    scene_b.alpha_composite(pet_img_b, (_to(sprite_b.x() - left_b) + pd, _to(sprite_b.y() - top_b) + pd))
    scene_b.alpha_composite(scene_toast_b,
                            (_to(toast.x() - left_b) + pd,
                             _to(toast.y() - top_b + petmod.TOAST_POP_DY) + pd))
    d_b = ImageDraw.Draw(scene_b)
    bx0_b = _to(toast.x() - left_b) + pd
    by0_b = _to(toast.y() - top_b + petmod.TOAST_POP_DY) + pd
    sy1 = _to(sprite_b.y() + sprite_b.height() - top_b) + pd + 1
    d_b.rectangle([bx0_b + 2, min(sy1 + 1, by0_b - 1), bx0_b + scene_toast_b.width - 3, by0_b], outline=MARK)
    d_b.line([(_to(sprite_b.x() - left_b) + pd, sy1),
              (_to(sprite_b.x() + sprite_b.width() - left_b) + pd, sy1)], fill=MARK, width=1)
    d_b.text((bx0_b + scene_toast_b.width + 4, by0_b - 5), f"{petmod.TOAST_GAP}px", fill=MARK, font=font(12))
    blocks.append((scene_b, ["让位：贴图顶到屏幕上沿（上方放不下）时，提示平移到贴图下方 5px（0.5s 平移，不重放弹出）；",
                             "红框 = 气泡上沿距贴图底边 5px（红线 = 贴图底边），横向仍以贴图中心线居中。"]))
    pet.move(700, 420)
    app.processEvents()

    # ---- ③ 竖排拼图 + 手写短注 ----
    # 说明文字**手写成短行**：PIL 量的宽是「加载的那套字体」，画的时候缺字会回退到另一套，
    # 两者对不上（见 devlog §二十 §5）。宽度再取一个够大的下限，宁可右边多一块空白也不要裁字。
    f13 = font(13)
    pad = 16
    W = max(max(img.width for img, _ in blocks), 470) + 2 * pad
    heights = [img.height + 8 + 17 * len(caps) + 12 for img, caps in blocks]
    canvas = Image.new("RGBA", (W, sum(heights) + 2 * pad), BG + (255,))
    d = ImageDraw.Draw(canvas)
    y = pad
    for (img, caps), hh in zip(blocks, heights):
        canvas.alpha_composite(img, (pad, y))
        ty = y + img.height + 8
        for line in caps:
            d.text((pad, ty), line, fill=INK, font=f13)
            ty += 17
        y += hh
    path = OUT_DIR / "pet-toast.png"
    canvas.convert("RGB").save(str(path))
    print(f"saved {path.name:22s} size={canvas.width}x{canvas.height} dpr={S} toast_h={body_h} "
          f"gap={petmod.TOAST_GAP} gap_ok={gap_ok} centered={centered} flip_below_ok={below_ok} "
          f"w(待机中...)={petmod.toast_body_w('待机中...')} w(休眠中)={petmod.toast_body_w('休眠中')} "
          f"w(已进入静音模式)={petmod.toast_body_w('已进入静音模式')} "
          f"w(已进入节能模式)={petmod.toast_body_w('已进入节能模式')}")
    pet.close()
    app.processEvents()


def shoot_pet_patpat():
    """patpat 模式：左键摸贴图时贴在角色**之上**的那只手（`_PatPatOverlay`）+ 角色贴图自己的形变。
    核对六件事（**二十一改**口径）：
    ① 普通态：手的**左上角**与贴图左上角重合；
    ② **下压帧**（站姿）：贴图自己也压扁（高 −35、宽两侧各 +12、**底边不动**），
       手只跟着下沉、横向不动；
    ③ 三帧：抬起 → 下压 → 抬起（**50 / 150 / 100 ms**，第 3 帧还是第 1 张图）；
    ④ 节能态：手的**左下角**落在贴图「自下往上 3/8」处，且此刻手会**高出贴图窗口的顶边**
    —— 这正是它必须是独立顶层窗、不能做子控件的原因（同理 `WindowTransparentForInput` 不能少）；
    ⑤ **下压帧**（节能态）：形变走的是**它自己那一套量**（高 −20、宽每侧 +8 → 150×100 变 166×80），
       不是站姿的 35/12（那会算成 174×65、矮掉 35%）；
    ⑥ ★**二十一改**：**不开 patpat 模式**单击 → 贴图**照样压出上面那一格的效果**，
       但**画面里没有那只手、也一声不出**（「模式」这一档只管「手 + 声」）。

    ⚠️ 那只手与桌宠是两个**独立顶层窗**（`Qt.Tool` + `WindowTransparentForInput`），
    `pet.grab()` 抓不到它 —— 各自 grab 再按屏幕相对位置用 PIL 拼（与 `shoot_pet_toast` 同一套做法）。
    ⚠️ 抓下来的图是**设备像素**（真机 125% / 150% 缩放 → dpr 1.25 / 1.5），
    偏移与裁剪都得按 dpr 换算，否则手相对贴图会被压缩。
    """
    from PIL import Image, ImageDraw, ImageFont

    from app import pet as petmod
    from app import patpat as ppmod       # 几何常量都在这里（pet.py 只 re-export 了其中一部分）

    def to_pil(pm):
        # QImage 内存是 BGRA：先转 RGBA8888 再读，否则红蓝互换
        img = pm.toImage().convertToFormat(QImage.Format_RGBA8888)
        return Image.frombytes("RGBA", (img.width(), img.height()), bytes(img.constBits()))

    def font(size):
        for name in ("msyh.ttc", "msyhbd.ttc", "simhei.ttf", "arial.ttf"):
            try:
                return ImageFont.truetype(name, size)
            except OSError:
                continue
        return ImageFont.load_default()

    BG = (247, 250, 252)
    INK = (51, 65, 85)
    MARK = (220, 38, 38)

    pet = petmod.PetWindow(BASE / "pet" / "alice")
    pet.move(700, 420)
    pet.show()
    settle(300)
    pet.set_patpat_sound_dir(BASE / "voices" / "patpat")
    # ★二十二改：非模式单击播的是**另一套**（`voices/normal_pet/bibu.mp3`）—— 两套各自独立。
    pet.set_normal_pet_sound_dir(BASE / "voices" / "normal_pet")
    pet.set_patpat(True)
    S = float(pet.devicePixelRatioF() or 1.0)
    pd = 14
    _to = lambda v: round(v * S)          # 逻辑 → 画布（设备）像素

    def scene():
        """抓「贴图 + 那只手」拼成一张画布（带 3/8 基准线与贴图左上角十字）。"""
        pet._patpat_stop()
        pet._patpat_play()
        app.processEvents()
        ov = pet._patpat_ov
        ov_img = to_pil(ov.grab())
        sprite = pet._sprite_rect()
        pet_img = to_pil(pet.grab())
        gx, gy = sprite.x() - pet.x(), sprite.y() - pet.y()
        pet_img = pet_img.crop((_to(gx), _to(gy),
                                _to(gx + sprite.width()), _to(gy + sprite.height())))
        ovr = QRect(ov.x(), ov.y(), ov.width(), ov.height())
        left, top = min(sprite.x(), ovr.x()), min(sprite.y(), ovr.y())
        right = max(sprite.x() + sprite.width(), ovr.x() + ovr.width())
        bottom = max(sprite.y() + sprite.height(), ovr.y() + ovr.height())
        im = Image.new("RGBA", (_to(right - left) + 2 * pd, _to(bottom - top) + 2 * pd),
                       BG + (255,))
        im.alpha_composite(pet_img, (_to(sprite.x() - left) + pd, _to(sprite.y() - top) + pd))
        im.alpha_composite(ov_img, (_to(ovr.x() - left) + pd, _to(ovr.y() - top) + pd))
        d = ImageDraw.Draw(im)
        sx = _to(sprite.x() - left) + pd
        sy = _to(sprite.y() - top) + pd
        d.line([(sx - 6, sy), (sx + 6, sy)], fill=MARK, width=1)      # 贴图左上角像素
        d.line([(sx, sy - 6), (sx, sy + 6)], fill=MARK, width=1)
        by = _to(sprite.y() + sprite.height()
                 - round(sprite.height() * ppmod.PATPAT_PS_BOTTOM_RATIO) - top) + pd
        d.line([(sx - 10, by), (sx + _to(sprite.width()) + 6, by)], fill=MARK, width=1)
        d.text((sx + 4, by - 15), "3/8", fill=MARK, font=font(12))
        return im, ovr, sprite

    def scene_squashed():
        """抓「**压扁后**的贴图 + 那只手」（此刻是「下压」帧、形变已到位）。

        红色矩形画的是**形变前**的贴图轮廓，好一眼看出「高 −H、宽每侧 +per_side、底边不动」
        （H / per_side 按**当前形态**取：站姿 35/12、节能态 20/8）。
        """
        pet._patpat_stop()
        pet._patpat_play()
        # ⚠️ 不能只 `settle(...)` 就抓：定时器比名义时刻晚一拍（smoke_pet 已经踩过一次），
        # 形变可能还差几 px 没到位、红线与贴图就对不上。这里**等真实进度到位**再抓。
        # 上限 0.8s 远小于「下压」帧的结束之后也无所谓 —— 只要还在帧内，
        # 形变就恒为 1.0；一到 1.0 立刻退出，不会越过帧边界。
        _deadline = time.time() + 0.8
        while pet.patpat_squash_progress() < 0.999 and time.time() < _deadline:
            app.processEvents()
            time.sleep(0.01)
        app.processEvents()
        ov = pet._patpat_ov
        ov_img = to_pil(ov.grab())
        sprite = pet._sprite_rect()
        pet_img = to_pil(pet.grab())
        base = pet._patpat_sq_base
        ovr = QRect(ov.x(), ov.y(), ov.width(), ov.height())
        xs = [sprite.x(), ovr.x()] + ([base[0]] if base else [])
        ys = [sprite.y(), ovr.y()] + ([base[1]] if base else [])
        x2 = [sprite.x() + sprite.width(), ovr.x() + ovr.width()] \
            + ([base[0] + base[2]] if base else [])
        y2 = [sprite.y() + sprite.height(), ovr.y() + ovr.height()] \
            + ([base[1] + base[3]] if base else [])
        left, top, right, bottom = min(xs), min(ys), max(x2), max(y2)
        im = Image.new("RGBA", (_to(right - left) + 2 * pd, _to(bottom - top) + 2 * pd),
                       BG + (255,))
        im.alpha_composite(pet_img, (_to(sprite.x() - left) + pd, _to(sprite.y() - top) + pd))
        im.alpha_composite(ov_img, (_to(ovr.x() - left) + pd, _to(ovr.y() - top) + pd))
        d = ImageDraw.Draw(im)
        if base:
            bx = _to(base[0] - left) + pd
            by = _to(base[1] - top) + pd
            d.rectangle([bx, by, bx + _to(base[2]) - 1, by + _to(base[3]) - 1], outline=MARK)
        return im, ovr, sprite, base

    def scene_nomode_squashed():
        """抓「**不开 patpat 模式**时单击」的形变（二十一改；二十二改补音效）。

        与 `scene_squashed()` 的唯一区别：**画面里没有那只手** —— 所以这里只 grab 桌宠窗口
        （不再拼叠加图），并顺手核一下「手没出来 + 只响 normal_pet 那一套」这两件事。
        """
        pet.set_patpat(False)
        app.processEvents()
        pet._patpat_stop()
        # ⚠️★必须先清掉「最近一次播过什么」——`_last` 是**跨场景留痕**的字段，上一格
        # `scene_squashed()` 是**开着模式**跑的（它真的播了 patpat 音效），不清就会把上一格的文件名
        # 印在本格说明里。**凡打印「最近一次 X」的字段，都要先证明它在这一段之前被清过**
        # （与「跟随位移的数字要跟未位移的自己比」同一族教训）。
        # ★二十二改：**两套都要清** —— 这一格要同时证明「normal_pet 响了」+「patpat 没响」。
        pet._patpat_audio._last = None
        pet._normal_pet_audio._last = None
        _ret = pet._patpat_play()          # 模式关着 → 返回 False（没有叠手）
        _deadline = time.time() + 0.8
        while pet.patpat_squash_progress() < 0.999 and time.time() < _deadline:
            app.processEvents()
            time.sleep(0.01)
        app.processEvents()
        # 抓「最近一次真的播出去的那一段」：非模式该是 bibu.mp3、而 patpat 那套该是 None。
        _np_audio = pet._normal_pet_audio.last_played
        _pp_audio = pet._patpat_audio.last_played
        sprite = pet._sprite_rect()
        pet_img = to_pil(pet.grab())
        gx, gy = sprite.x() - pet.x(), sprite.y() - pet.y()
        pet_img = pet_img.crop((_to(gx), _to(gy),
                                _to(gx + sprite.width()), _to(gy + sprite.height())))
        base = pet._patpat_sq_base
        xs = [sprite.x()] + ([base[0]] if base else [])
        ys = [sprite.y()] + ([base[1]] if base else [])
        x2 = [sprite.x() + sprite.width()] + ([base[0] + base[2]] if base else [])
        y2 = [sprite.y() + sprite.height()] + ([base[1] + base[3]] if base else [])
        left, top, right, bottom = min(xs), min(ys), max(x2), max(y2)
        im = Image.new("RGBA", (_to(right - left) + 2 * pd, _to(bottom - top) + 2 * pd),
                       BG + (255,))
        im.alpha_composite(pet_img, (_to(sprite.x() - left) + pd, _to(sprite.y() - top) + pd))
        d = ImageDraw.Draw(im)
        if base:
            bx = _to(base[0] - left) + pd
            by = _to(base[1] - top) + pd
            d.rectangle([bx, by, bx + _to(base[2]) - 1, by + _to(base[3]) - 1], outline=MARK)
        return im, sprite, base, _ret, _np_audio, _pp_audio

    blocks = []

    # ---- ① 普通态：左上角重合（帧1「抬起」，此刻还没形变）----
    img_n, ovr_n, _sp_n = scene()
    blocks.append((img_n, [
        "普通态：那只手的左上角与贴图左上角重合（十字 = 贴图左上角像素；画布口径，两张同尺寸）。",
        f"手 = 原图 300×225 × 角色系数 {round(pet._patpat_scale(), 4)} → 抓下来 "
        f"{ovr_n.width()}×{ovr_n.height()}（逻辑像素；与角色贴图同一个缩放系数）。",
    ]))

    # ---- ② 下压帧（站姿）：角色贴图自己也压扁（底边不动 / 高 −35 / 宽两侧各 +12）----
    img_q, ovr_q, spr_q, base_q = scene_squashed()
    if base_q:
        _bx, _by, _bw, _bh = base_q
    else:
        _bx, _by, _bw, _bh = spr_q.x(), spr_q.y(), spr_q.width(), spr_q.height()
    blocks.append((img_q, [
        "下压帧（站姿）：贴图自己也压一下（红线 = 形变前的贴图轮廓）—— 高 −35px、"
        "宽两侧各 +12px，底边不动（原地压矮）。",
        f"形变后贴图 {spr_q.width()}×{spr_q.height()}（形变前 {_bw}×{_bh}）；"
        f"顶边下沉 {spr_q.y() - _by}px、左边界左移 {_bx - spr_q.x()}px。",
        f"那只手不参与形变（仍 {ovr_q.width()}×{ovr_q.height()}）：横向不动、"
        f"纵向跟着下沉 {ovr_q.y() - _by}px（= 贴图顶边下沉量 → 与贴图的相对位置不变）。",
    ]))

    # ---- ③ 三帧：抬起 → 下压 → 抬起 ----
    pet._patpat_stop()
    pet._patpat_play()
    app.processEvents()
    f1 = to_pil(pet._patpat_ov.grab())

    def _wait_frame(idx, step, limit=1.0):
        """等到**真的**切到第 `idx` 帧 / 第 `step` 步再抓。

        ⚠️ 不能用固定 `settle()`：定时器比名义时刻晚一拍，而二十改后「下压」帧只有 **150ms** 宽
        （名义时刻 ±25ms 就出界、抓成第 3 帧），比十九改那 250ms 窄得多。等真实状态最稳。
        """
        _t = time.time() + limit
        while time.time() < _t:
            if pet.patpat_overlay_index() == idx and pet.patpat_step() == step:
                break
            app.processEvents()
            time.sleep(0.005)
        app.processEvents()
        return pet.patpat_overlay_index() == idx and pet.patpat_step() == step

    _f2ok = _wait_frame(1, 2)                     # 「下压」帧
    f2 = to_pil(pet._patpat_ov.grab())
    _f3ok = _wait_frame(0, 3)                     # 第 3 帧（又是「抬起」那张）
    f3 = to_pil(pet._patpat_ov.grab())
    if not (_f2ok and _f3ok):
        print(f"   ⚠️ 三帧抓拍没等到位：f2={_f2ok} f3={_f3ok}")
    _gap = 12
    strip = Image.new("RGBA", (f1.width + f2.width + f3.width + 2 * _gap,
                               max(f1.height, f2.height, f3.height)), BG + (255,))
    strip.alpha_composite(f1, (0, 0))
    strip.alpha_composite(f2, (f1.width + _gap, 0))
    strip.alpha_composite(f3, (f1.width + f2.width + 2 * _gap, 0))
    blocks.append((strip, [
        f"三帧：抬起（0…{ppmod.PATPAT_F1_MS}ms）→ 下压（…{ppmod.PATPAT_F1_MS + ppmod.PATPAT_F2_MS}ms）"
        f"→ 抬起（…{ppmod.PATPAT_TOTAL_MS}ms）—— 第 3 帧还是第 1 张图。",
        "两张素材同尺寸 → 换帧时窗口几何不动，只有画面换（第 3 帧又回到抬起，不会跳）。",
    ]))
    pet._patpat_stop()

    # ---- ④ 节能态：左下角落在 3/8，且高出贴图顶边 ----
    pet.set_power_save(True, animate=False)
    settle(300)
    img_p, ovr_p, spr_p = scene()
    blocks.append((img_p, [
        "节能态：手的左下角落在贴图「自下往上 3/8」处（红线 = 3/8 基准线），横向仍与贴图左边对齐。",
        f"此刻手高出贴图窗口顶边 {spr_p.y() - ovr_p.y()}px —— 做子控件会被父窗直接裁掉，"
        "所以它必须是独立顶层窗。",
        f"手的大小不跟着贴图压扁（仍 {ovr_p.width()}×{ovr_p.height()}，按站姿系数算）——"
        "用户给节能态单独指定了落点，说明手的大小不变。",
    ]))

    # ---- ⑤ 下压帧（节能态）：形变走**它自己那一套量**（20/8，不是站姿的 35/12）----
    img_pq, ovr_pq, spr_pq, base_pq = scene_squashed()
    if base_pq:
        _pbx, _pby, _pbw, _pbh = base_pq
    else:
        _pbx, _pby, _pbw, _pbh = spr_pq.x(), spr_pq.y(), spr_pq.width(), spr_pq.height()
    # ⚠️ 手的「下沉量」必须跟**没下沉时那只手的窗口顶边**比 —— 不是跟「贴图 3/8 基准线」比！
    # 节能态落点是**左下角**对齐（顶边 = 基准线 − 手高 113），拿基准线去减会多算出 113px
    # （本轮第一版就印出了「再下沉 -93px」）。同一条教训十九改已踩过一次（那时是「两者都下沉 ⇒ 差为 0」）。
    _psq_top0 = ppmod.patpat_pos(QRect(_pbx, _pby, _pbw, _pbh),
                                 ovr_pq.width(), ovr_pq.height(), power_save=True)[1]
    blocks.append((img_pq, [
        "下压帧（节能态）：扁平贴图也压，但压的是节能态那一套量 —— 高 −20px、宽每侧 +8px。",
        f"形变后贴图 {spr_pq.width()}×{spr_pq.height()}（形变前 {_pbw}×{_pbh}）；"
        f"顶边下沉 {spr_pq.y() - _pby}px、左边界左移 {_pbx - spr_pq.x()}px（红线 = 形变前轮廓）。",
        "照站姿那套 35/12 会算成 174×65 —— 100px 高的贴图矮掉 35%，比站姿的 14% 夸张得多。",
        f"那只手照样不参与形变（仍 {ovr_pq.width()}×{ovr_pq.height()}）、横向不动。",
        f"纵向 = 3/8 落点再下沉 {ovr_pq.y() - _psq_top0}px"
        " —— 节能态那套的下沉量是 20px，不是站姿的 35px。",
    ]))
    pet.set_power_save(False, animate=False)
    settle(200)

    # ---- ⑥ 二十一改 / 二十二改：**不开模式**单击 → 只有形变（没有那只手，但会响 normal_pet 那一套）----
    img_nm, spr_nm, base_nm, _nm_ret, _nm_np, _nm_pp = scene_nomode_squashed()
    if base_nm:
        _nbx, _nby, _nbw, _nbh = base_nm
    else:
        _nbx, _nby, _nbw, _nbh = spr_nm.x(), spr_nm.y(), spr_nm.width(), spr_nm.height()
    blocks.append((img_nm, [
        "不开 patpat 模式时单击：贴图照样压一下（红线 = 形变前的轮廓）—— 画面里没有那只手，"
        "但会同步播 voices/normal_pet/ 那一套（与 patpat 那套互相独立）。",
        f"形变后贴图 {spr_nm.width()}×{spr_nm.height()}（形变前 {_nbw}×{_nbh}）；"
        f"顶边下沉 {spr_nm.y() - _nby}px、左边界左移 {_nbx - spr_nm.x()}px、底边不动。",
        "与上面「下压帧（站姿）」那一格逐项相同（高 −35、宽每侧 +12）——"
        "几种情形共用同一条时间线，差别只有「手」和「出哪一套声」。",
        f"这一轮 _patpat_play() 返回 {_nm_ret}（False = 没叠手）；normal_pet 那套播了 "
        f"{_nm_np.name if _nm_np else None}、patpat 那套 = {_nm_pp}"
        f"（两套开抓前都清空过，所以 patpat 那套 None = 这一格它一次没响）。",
    ]))
    pet.set_patpat(False)
    app.processEvents()

    f13 = font(13)
    pad = 16
    # ⚠️ 宽度下限要**按最长那行说明**取，不能只看图片宽：说明文字比图宽时会被右边裁掉
    # （与 shoot_pet_toast 同一条教训：宁可右边多一块空白，也不要裁字）。
    W = max(max(img.width for img, _ in blocks), 780) + 2 * pad
    heights = [img.height + 8 + 17 * len(caps) + 12 for img, caps in blocks]
    canvas = Image.new("RGBA", (W, sum(heights) + 2 * pad), BG + (255,))
    d = ImageDraw.Draw(canvas)
    y = pad
    for (img, caps), hh in zip(blocks, heights):
        canvas.alpha_composite(img, (pad, y))
        ty = y + img.height + 8
        for line in caps:
            d.text((pad, ty), line, fill=INK, font=f13)
            ty += 17
        y += hh
    path = OUT_DIR / "pet-patpat.png"
    canvas.convert("RGB").save(str(path))
    print(f"saved {path.name:22s} size={canvas.width}x{canvas.height} dpr={S} "
          f"normal_ov={ovr_n.width()}x{ovr_n.height()} ps_ov={ovr_p.width()}x{ovr_p.height()} "
          f"ps_raise={spr_p.y() - ovr_p.y()} scale={round(pet._patpat_scale(), 4)} "
          f"frames={ppmod.PATPAT_F1_MS}/{ppmod.PATPAT_F2_MS}/{ppmod.PATPAT_F3_MS} "
          f"squash={spr_q.width()}x{spr_q.height()}(was {_bw}x{_bh}) "
          f"sq_drop={spr_q.y() - _by} ov_dx={ovr_q.x() - ovr_n.x()} "
          f"ps_squash={spr_pq.width()}x{spr_pq.height()}(was {_pbw}x{_pbh}) "
          f"ps_drop={spr_pq.y() - _pby} "
          f"nomode={spr_nm.width()}x{spr_nm.height()}(was {_nbw}x{_nbh}) "
          f"nomode_ret={_nm_ret} nomode_np={_nm_np.name if _nm_np else None} nomode_pp={_nm_pp}")
    pet.close()
    app.processEvents()


def shoot_general_model_row():
    """通用设置的「语音模型」分组（2026-09-22）：下载行 + 安装位置行 + **被锁死的静音滑块**。

    ★本机真装着模型（`D:\\GPT-SoVITS`）⇒ 静音滑块**不会**锁死、下载行显示「已下载」，
      拍不到本期最关键的那一屏。所以临时让 `voice_model` 报「未下载」再拍一张 ——
      只改内存里的两个函数，**不动任何文件、不写 config**。
    """
    from app import voice_model as _vm

    gen = win._settings_panels["general"]
    real = (_vm.is_installed, _vm.model_dir)
    _prev_mute = gen.cfg.get("general", {}).get("mute_mode")
    try:
        _vm.is_installed = lambda c: False
        _vm.model_dir = lambda c: None
        win._show_settings_page(win._settings_index["general"])
        gen.refresh()
        settle()
        # 把「启动」组留在视野上方一点 ⇒ 下载行 / 安装位置行 / 锁死的静音滑块同时入镜
        sb = gen._scroll.verticalScrollBar()
        y = gen._model_row.mapTo(gen._body, QPoint(0, 0)).y()
        sb.setValue(max(0, min(y - 108, sb.maximum())))
        settle(300)
        path = OUT_DIR / "settings-general-model-locked.png"
        win.grab().save(str(path))
        mr, dr, mu = gen._model_row, gen._model_dir_row, gen._mute_row
        print(f"saved {path.name:34s} state={mr.state_text()!r} "
              f"下载={mr._download_btn.isEnabled()} 卸载={mr._uninstall_btn.isEnabled()} "
              f"path={dr.shown_text()!r} locked={mu.is_locked()} 静音={mu.is_enabled()} "
              f"scroll={sb.value()}/{sb.maximum()}")
    finally:
        _vm.is_installed, _vm.model_dir = real
        gen.cfg.setdefault("general", {})["mute_mode"] = _prev_mute
        gen.refresh()
        settle()


def shoot_general_model_downloading():
    """二期（2026-09-22 夜）：**下载中**那一屏 —— 状态 `下载中　42%`、按钮变「取消」、
    下方小灰字是当前阶段。

    ★**不会真的下载**：patch 掉 `voice_download.snapshot` 让它报「下载中」，
      **不起线程、不联网、不写任何文件**，拍完立刻还原。
    """
    from app import voice_download as _vd

    gen = win._settings_panels["general"]
    real_snap = _vd.snapshot
    fake = {"running": True, "done": False, "error": "", "cancelled": False,
            "phase": "model", "percent": 42,
            "message": "正在下载音色克隆模型（3/5）：s2G2333k.pth", "skipped": "", "root": ""}
    try:
        _vd.snapshot = lambda: dict(fake)
        win._show_settings_page(win._settings_index["general"])
        gen.refresh()
        settle()
        sb = gen._scroll.verticalScrollBar()
        y = gen._model_row.mapTo(gen._body, QPoint(0, 0)).y()
        sb.setValue(max(0, min(y - 108, sb.maximum())))
        settle(300)
        path = OUT_DIR / "settings-general-model-downloading.png"
        win.grab().save(str(path))
        mr = gen._model_row
        print(f"saved {path.name:34s} state={mr.state_text()!r} "
              f"下载={mr._download_btn.text()}/{mr._download_btn.isEnabled()} "
              f"卸载={mr._uninstall_btn.isEnabled()} hint={mr._hint_text!r} "
              f"locked={gen._mute_row.is_locked()}")
    finally:
        _vd.snapshot = real_snap
        gen._dl_timer.stop()
        gen.refresh()
        settle()


def shoot_general_model_confirm():
    """点「下载」时弹的那次确认（2026-09-27 用户要求）：文案**两行** ——
    第一行「合成语音时将大幅减缓AI回复速度」、第二行「是否下载？」。

    ★这里走的是**真代码路径**（`gen._download_model()`），弹的是 `ConfirmDialog` **实物**，
      只是把它的 `confirm` 换成「show 出来截一张、然后按『取消』返回 False」的桩
      —— 真 `confirm()` 是**模态 `exec()`**，会把截图脚本卡在那里不返回。
    ★**不会真下载**：`voice_download.start` 也换成桩（记下调用），而且因为确认框返回 False，
      按代码逻辑它本来就到不了 `start()` —— 打印 `start_calls` 正好顺带在真机上验一次
      「点取消 ⇒ 一个字都没开始」（与 `smoke_settings` 里那条断言同一个口径）。
    """
    from app import voice_download as _vd

    gen = win._settings_panels["general"]
    real_confirm = gui.ConfirmDialog.confirm
    real_start = _vd.start
    holder, start_calls = {}, []

    def _capture(parent, message, *a, **k):
        dlg = gui.ConfirmDialog(parent, message, *a, **k)
        dlg.show()
        settle(400)
        path = OUT_DIR / "settings-general-model-download-confirm.png"
        dlg.grab().save(str(path))
        holder["msg"] = message
        # ★顺带量一次「第一行会不会被自动折掉」：卡片 360px 宽、左右各 24px 内边距 + 1px 边框
        #   ⇒ 文案区可用 ≈310px。`adv <= label.width()` 才说明**换行是文案里的 `\n` 指定的**，
        #   不是 QLabel 自己折出来的（后者会让两行变成三行、看着像文案写错了）。
        first = message.split("\n")[0]
        lbl = dlg.findChildren(QLabel)[0]
        adv = lbl.fontMetrics().horizontalAdvance(first)
        print(f"saved {path.name:34s} size={dlg.width()}x{dlg.height()} "
              f"lines={message.count(chr(10)) + 1} msg={message!r}")
        print(f"      第一行宽 {adv}px / 文案区 {lbl.width()}px ⇒ "
              f"{'放得下（换行来自文案的 \\n）' if adv <= lbl.width() else '★放不下，会被自动折行'}")
        dlg.close()
        settle(150)
        return False                      # 用户点的是「取消」

    def _fake_start(*a, **k):
        start_calls.append(k)
        return False, "（截图用桩，不会真下载）"

    try:
        gui.ConfirmDialog.confirm = staticmethod(_capture)
        _vd.start = _fake_start
        win._show_settings_page(win._settings_index["general"])
        gen.refresh()
        settle()
        gen._download_model()
        print(f"confirm msg 落点 OK={bool(holder.get('msg'))} "
              f"voice_download.start 调用次数={len(start_calls)}（必须为 0）")
    finally:
        gui.ConfirmDialog.confirm = real_confirm
        _vd.start = real_start
        gen.refresh()
        settle()


def shoot_general_model_uninstall():
    """点「卸载」时弹的**三选一**弹窗（`ChoiceDialog`，2026-09-27 新增）：
    `取消` / `仅模型卸载` / `全部卸载`，卡片加宽到 **440px**。

    ★与 `shoot_general_model_confirm` 同一套路：走**真代码路径**（`gen._uninstall_model()`），
      弹的是 `ChoiceDialog` **实物**，只把它的 `choose` 换成「show → 截一张 → 按『取消』返回 None」
      的桩 —— 真 `choose()` 是模态 `exec()`，会把截图脚本卡住不返回。
    ★**一个字都不会删**：`voice_model.uninstall` 换成记录用的桩；而且确认返回的是 `None`
      （取消），按代码逻辑本来就到不了 `uninstall()`。打印 `uninstall_calls` 顺带在真机上验一次
      「点取消 ⇒ 一个字都没删」（与 `smoke_settings` §5h 那条断言同口径）。
    ★`model_dir` 也要换成桩：本机 2026-09-27 已把模型卸载，真探测会返回 `None` ⇒
      `_uninstall_model` 会在弹窗前就早退（那样截不到弹窗）。
    """
    from app import voice_download as _vd
    from app import voice_model as _vm

    gen = win._settings_panels["general"]
    real_choose = gui.ChoiceDialog.choose
    real_uninstall = _vm.uninstall
    real_model_dir = _vm.model_dir
    real_running = _vd.is_running
    holder, uninstall_calls = {}, []

    def _capture(parent, message, choices, cancel_text="取消"):
        dlg = gui.ChoiceDialog(parent, message, choices, cancel_text)
        dlg.show()
        settle(400)
        path = OUT_DIR / "settings-general-model-uninstall-3way.png"
        dlg.grab().save(str(path))
        holder["msg"] = message
        holder["choices"] = choices
        lbl = dlg.findChildren(QLabel)[0]
        btns = dlg.findChildren(QPushButton)
        print(f"saved {path.name:36s} size={dlg.width()}x{dlg.height()} "
              f"lines={message.count(chr(10)) + 1} buttons={[b.text() for b in btns]}")
        print(f"      文案区 {lbl.width()}px（卡片 {gui.ChoiceDialog.CARD_W}px - 24×2 - "
              f"1×2）／按钮 {[b.objectName() for b in btns]}")
        dlg.close()
        settle(150)
        return None                       # 用户点的是「取消」

    def _fake_uninstall(cfg, mode):
        uninstall_calls.append(mode)
        return True

    try:
        gui.ChoiceDialog.choose = staticmethod(_capture)
        _vm.uninstall = _fake_uninstall
        _vm.model_dir = lambda cfg: Path(r"D:\fake\GPT_SoVITS\pretrained_models")
        _vd.is_running = lambda: False
        win._show_settings_page(win._settings_index["general"])
        gen.refresh()
        settle()
        gen._uninstall_model()
        print(f"uninstall msg 落点 OK={bool(holder.get('msg'))} "
              f"keys={[c[0] for c in holder.get('choices', [])]} "
              f"voice_model.uninstall 调用次数={len(uninstall_calls)}（必须为 0）")
    finally:
        gui.ChoiceDialog.choose = real_choose
        _vm.uninstall = real_uninstall
        _vm.model_dir = real_model_dir
        _vd.is_running = real_running
        gen.refresh()
        settle()


def shoot_general_model_confirm_full():
    """同一颗 `[下载]` 按钮，在**全量**情形下的确认框（**三行**，中间那行报总体积）。

    ★为什么单独来一屏：本机 `D:\\GPT-SoVITS` 是一份**可用安装** ⇒ `is_full_install()` 为假
      ⇒ `_download_model` 走的是**两行**那一版（`shoot_general_model_confirm` 拍的就是它）。
      全量那版只能在「代码体 / venv 不在」的机器上自然出现，所以这里把 `is_full_install`
      换成桩强制成 True，好让两个分支都有一张可人工核对的图。
    ★换桩只影响「要不要多问一行」，不影响任何下载行为（`voice_download.start` 同样是桩）。
    """
    from app import voice_download as _vd

    gen = win._settings_panels["general"]
    real_confirm = gui.ConfirmDialog.confirm
    real_start = _vd.start
    real_full = _vd.is_full_install
    holder, start_calls = {}, []

    def _capture(parent, message, *a, **k):
        dlg = gui.ConfirmDialog(parent, message, *a, **k)
        dlg.show()
        settle(400)
        path = OUT_DIR / "settings-general-model-download-confirm-full.png"
        dlg.grab().save(str(path))
        holder["msg"] = message
        first = message.split("\n")[0]
        lbl = dlg.findChildren(QLabel)[0]
        adv = lbl.fontMetrics().horizontalAdvance(first)
        print(f"saved {path.name:44s} size={dlg.width()}x{dlg.height()} "
              f"lines={message.count(chr(10)) + 1} msg={message!r}")
        print(f"      第一行宽 {adv}px / 文案区 {lbl.width()}px ⇒ "
              f"{'放得下（换行来自文案的 \\n）' if adv <= lbl.width() else '★放不下，会被自动折行'}")
        dlg.close()
        settle(150)
        return False

    def _fake_start(*a, **k):
        start_calls.append(k)
        return False, "（截图用桩，不会真下载）"

    try:
        gui.ConfirmDialog.confirm = staticmethod(_capture)
        _vd.is_full_install = lambda cfg=None, root=None: True
        _vd.start = _fake_start
        win._show_settings_page(win._settings_index["general"])
        gen.refresh()
        settle()
        gen._download_model()
        print(f"full confirm msg 落点 OK={bool(holder.get('msg'))} "
              f"voice_download.start 调用次数={len(start_calls)}（必须为 0）")
    finally:
        gui.ConfirmDialog.confirm = real_confirm
        _vd.is_full_install = real_full
        _vd.start = real_start
        gen.refresh()
        settle()


def shoot_notice():
    """启动提示区（**浮层**，2026-10-02）：摆着的样子 + 关掉之后的样子。

    核对点：① 它挂在标题栏正下方、**不进布局** —— 关掉它时下方界面一个像素都不许动；
    ② 底边有一条柔和阴影（没有影子就看不出"浮在上层"）；
    ③ ✕ / 倒计时那一列与前后的行对齐。

    ★它平时**只在启动时**出现一次（`main.py` 里调 `show_startup_notices`），
      所以别的截图里根本看不到它 —— 想看它就得像这里一样手动摆一次。
    """
    win.set_health_facts_provider(lambda: {"tts_installed": True, "asr_ok": True})
    win.refresh_health()
    win.show_startup_notices()
    settle()
    y0 = win._chat_view.mapTo(win, QPoint(0, 0)).y()
    h0 = win._chat_view.height()
    path = OUT_DIR / "notice-overlay.png"
    win.grab().save(str(path))
    # ★浮层判据：它**不在**主窗口的布局里（`{...}` 里的表达式不能跨两个字符串字面量写，
    #   所以先算好再 f-string）
    in_layout = any(win.layout().itemAt(i).widget() is win._notice_area
                    for i in range(win.layout().count()))
    print(f"saved {path.name:22s} rows={sorted(win._notice_on)} "
          f"geom={win._notice_area.geometry()} "
          f"shadow={win._notice_area.graphicsEffect() is not None} in_layout={in_layout}")
    # 关掉（白名单那条的 ✕ + 语音那条的 ✕）⇒ 再抓一张：底下那半屏必须纹丝不动
    win._perm_row[4].click()
    win._voice_row[4].click()
    settle(300)
    win.grab().save(str(OUT_DIR / "notice-overlay-dismissed.png"))
    y1 = win._chat_view.mapTo(win, QPoint(0, 0)).y()
    h1 = win._chat_view.height()
    print(f"saved notice-overlay-dismissed.png 内容位移 dy={y1 - y0} dh={h1 - h0}（都必须是 0）")


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    shoot("main-chat")
    shoot_chat_reply()
    shoot_manage("manage-api", win.PAGE_API)
    shoot_manage("manage-wake", win.PAGE_WAKE)
    shoot_preset()
    shoot_api_dialogs()
    shoot_danger_countdown()
    shoot("settings-general", win._settings_index["general"])
    shoot_general_autostart_on()
    shoot_general_pet_row()
    shoot_general_model_row()
    shoot_general_model_downloading()
    shoot_general_model_confirm()
    shoot_general_model_confirm_full()
    shoot_general_model_uninstall()
    # ★2026-09-28：这张图里的目录行来自**本机 config.json** 的显式 `allowed_dirs`（7 条），
    #   **不是**内置默认 —— 内置默认已清空（`tools.DEFAULT_ALLOWED_DIRS = ()`，见 docs/02 §8.9）。
    #   所以「默认目录为空」不会让这两张图变成空分组。⚠️但万一哪天本机配置也清空了，
    #   下面 `if rows:` 会静默跳过 hover、截出一张没有核对价值的图 ⇒ 那时要在这里显式造演示数据
    #   （`_t.apply_permissions({"allowed_dirs": [...]}) + _perm._rebuild()`）。
    shoot("settings-permissions", win._settings_index["permissions"])

    perm = win._settings_panels["permissions"]
    win._show_settings_page(win._settings_index["permissions"])
    settle()
    groups = perm._body.findChildren(gui._CollapsibleGroup)
    print("collapsed:", [(g.is_collapsed(), g.height(), g._head.height()) for g in groups])

    # 展开「可操作目录/文件夹」并 hover 一行：核对卡片边框被拉长、行间无缝、hover 色块
    # 与末行底部圆角，以及删除按钮只在 hover 行出现
    groups[0].set_collapsed(False, animate=False)
    settle(300)
    rows = [groups[0].body_lay.itemAt(i).widget() for i in range(groups[0].body_lay.count())]
    rows = [r for r in rows if isinstance(r, gui._PermRow)]
    if rows:
        force_hover(rows[min(1, len(rows) - 1)])
    settle(300)
    path = OUT_DIR / "settings-permissions-expanded.png"
    win.grab().save(str(path))
    print(f"saved {path.name:22s} card_h={groups[0]._card.height()} rows={len(rows)} "
          f"ys={[r.y() for r in rows]} round_bottom={[r._round_bottom for r in rows]}")

    # 权限页下半部分：展开全部分组后滚到「可操作类型」区，核对圆形滑块的开 / 关外观
    for g in groups:
        g.set_collapsed(False, animate=False)
    settle(300)

    trows = perm._body.findChildren(gui._PermToggleRow)
    sb = perm._scroll.verticalScrollBar()
    # 滑块行现在挂在分组的内容区里，pos() 是相对父级的 → 先映射到 _body 再算滚动位置
    first_y = trows[0].mapTo(perm._body, QPoint(0, 0)).y() if trows else 0
    sb.setValue(max(0, min(first_y - 30, sb.maximum())))
    settle(300)
    if trows:
        force_hover(trows[0])
    settle(200)
    path = OUT_DIR / "settings-permissions-switches.png"
    win.grab().save(str(path))
    print(f"saved {path.name:22s} rows={len(trows)} scroll={sb.value()}/{sb.maximum()} "
          f"states={[r._btn.isChecked() for r in trows]} "
          f"opacity={[round(r._btn._opacity, 2) for r in trows]}")

    # 「回到顶部」按钮：此刻已滚到中部 → 标题行里应当已经出现（淡入到位）
    top_btn = perm._top_btn
    path = OUT_DIR / "settings-permissions-scrolltop.png"
    win.grab().save(str(path))
    print(f"saved {path.name:22s} shown={top_btn.is_shown()} visible={top_btn.isVisible()} "
          f"x={top_btn.x()} reset_x={perm._reset_btn.x()} scroll={sb.value()}/{sb.maximum()}")
    sb.setValue(0)
    settle(300)
    print(f"  滚回顶部后 → shown={top_btn.is_shown()} visible={top_btn.isVisible()}")

    shoot_permissions_rename()
    # ★提示区放在**最后**：它会把「这次运行已经关掉了」记下来（`_perm_dismissed`），
    #   放前面会影响后面那些图的提示区状态。
    shoot_notice()
    shoot_mid_frame()
    shoot_pet_bubble()
    shoot_pet_bubble_pages()
    shoot_pet_menu()
    shoot_pet_patpat()
    shoot_pet_toast()
    # 回到角色区，确认左栏能恢复白底
    win._select_nav(0)
    settle()
    print("back_to_role:", win._left_stack.currentWidget() is win._left_role_page,
          "left_bg=", win.grab().toImage().pixelColor(20, 400).name())
    win.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

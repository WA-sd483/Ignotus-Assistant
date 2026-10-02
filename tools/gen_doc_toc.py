# -*- coding: utf-8 -*-
"""重新生成大文档的「目录」与 `docs/README.md` 索引页（**不动正文一个字**）。

背景（2026-10-02，用户第七点）：`docs/02`（6287 行）与 `design.md`（1492 行）太长、
翻不动。要求「拆目录 + 索引页，且不改内容顺序、不改变含义」 ⇒ 本脚本**只在标题块之后
插入/替换一个 `## 目录` 段**，正文其余部分逐字节不动；`docs/README.md` 重写为总索引。

★幂等可重跑：已有 `## 目录` 段就**整段替换**（加了新章节后重跑即可，不会重复插入）。
★锚点算法照 GitHub（`a-b-c`：转小写 → 去标点/保留 `\\w-_空格` → 空格转 `-`，重名补 `-1`）。
  这是**唯一**两处目录共用的算法 —— README 与文档内目录不会对不上。

用法（在项目根跑）：
    .venv/Scripts/python.exe tools/gen_doc_toc.py
"""
import re
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent          # IgnotusAssistant/
DOCS = BASE / "docs"

# 要加目录的文档（相对项目根）。顺序即 README 里的展示顺序。
TOC_DOCS = ["docs/02-技术方案.md", "design.md"]

HEAD_RE = re.compile(r"^(#{2,3})\s+(.*)$")
STRIP_RE = re.compile(r"[^\w\- ]", re.UNICODE)
TOC_TITLE = "## 目录"


def gh_anchor(text: str) -> str:
    """GitHub 锚点算法。"""
    return STRIP_RE.sub("", text.strip().lower()).replace(" ", "-")


def _scan_headings(lines):
    """按出现顺序返回 (level, text, anchor)。`## 目录` 段自身被跳过。"""
    out, seen = [], {}
    for ln in lines:
        m = HEAD_RE.match(ln)
        if not m:
            continue
        lvl, text = len(m.group(1)), m.group(2).strip()
        if text.startswith("目录"):
            continue
        a = gh_anchor(text)
        n = seen.get(a, 0)
        seen[a] = n + 1
        if n:
            a = "%s-%d" % (a, n)
        out.append((lvl, text, a))
    return out


def _toc_block(headings) -> list:
    block = [TOC_TITLE, "",
             "> 点章节名直达。本目录由 `tools/gen_doc_toc.py` 按标题生成，**不影响正文顺序**。", ""]
    for lvl, text, a in headings:
        block.append("%s- [%s](#%s)" % ("" if lvl == 2 else "  ", text, a))
    block.append("")
    return block


def rebuild_toc(rel_path: str) -> None:
    path = BASE / rel_path
    lines = path.read_text(encoding="utf-8").split("\n")

    # ① 先摘掉旧的 `## 目录` 段（从它到下一个 `## ` 之前），再扫标题
    if any(ln.strip() == TOC_TITLE for ln in lines):
        start = next(i for i, ln in enumerate(lines) if ln.strip() == TOC_TITLE)
        end = start + 1
        while end < len(lines) and not lines[end].startswith("## "):
            end += 1
        lines = lines[:start] + lines[end:]

    headings = _scan_headings(lines)

    # ② 插到第一个 `## ` 之前（即 H1 + 引言之后）
    insert_at = next((i for i, ln in enumerate(lines) if ln.startswith("## ")), None)
    if insert_at is None:
        print("[warn] %s：找不到二级标题，跳过" % rel_path)
        return
    lines = lines[:insert_at] + _toc_block(headings) + lines[insert_at:]
    path.write_text("\n".join(lines), encoding="utf-8")
    print("[ok] %s：目录 %d 条" % (rel_path, len(headings)))


def chapters(fname: str):
    return [(t, a) for lvl, t, a in _scan_headings(
        (DOCS / fname).read_text(encoding="utf-8").split("\n")) if lvl == 2]


def rewrite_readme() -> None:
    lines = []
    A = lines.append
    A("# Ignotus Assistant — 项目文档（索引页）")
    A("")
    A("> **总索引。** 想找什么先从这里进。")
    A("> ★改 UI 前必读 [`design.md`](../design.md)（唯一视觉标准）；改行为看 `02` 对应章节；")
    A("> 收尾 / 跑测试 / 环境坑以 [`04 §0`](./04-开发执行步骤.md) 为唯一真值。")
    A("")
    A("> ★本文件由 `tools/gen_doc_toc.py` 生成（与 `docs/02` / `design.md` 顶部目录同一套锚点算法）。")
    A("")
    A("## 按目的找入口")
    A("")
    A("| 我想… | 去哪 |")
    A("|---|---|")
    A("| 改界面 / 组件样式 | [`design.md`](../design.md)（唯一视觉标准，含目录） |")
    A("| 查「某功能怎么实现的」 | [`02-技术方案.md`](./02-技术方案.md) —— 按 § 号查 |")
    A("| 看「要做什么、边界在哪」 | [`01-需求规格说明书.md`](./01-需求规格说明书.md) |")
    A("| 收尾 / 跑测试 / 环境前置 | [`04-开发执行步骤.md`](./04-开发执行步骤.md) |")
    A("| 看已完成 / 尚未实现 | [`05-已完成功能.md`](./05-已完成功能.md) |")
    A("| 翻某天的流水 | [`../devlog/`](../devlog/)（`YYYY-MM-DD.md`，一天一个） |")
    A("| 项目长期记忆 / 细则 | `MEMORY.md`（索引）+ `TECH-GOTCHAS.md`（细则），在 `new-proj/.workbuddy/memory/` |")
    A("")
    A("## 标准文档")
    A("")
    A("| 文件 | 一句话 | 状态 |")
    A("|---|---|---|")
    A("| [`01-需求规格说明书.md`](./01-需求规格说明书.md) | 完整需求清单：功能、角色、桌宠、安全边界 | 活文档 |")
    A("| [`02-技术方案.md`](./02-技术方案.md) | 技术栈、系统架构、**每个功能怎么实现的（主体）** | 活文档 |")
    A("| [`03-设计规范.md`](./03-设计规范.md) | 配色 / 桌宠贴图 / 命名（**简约版**） | 活文档 |")
    A("| [`04-开发执行步骤.md`](./04-开发执行步骤.md) | 分阶段路线图 + **每次改动的收尾闭环** | 活文档 |")
    A("| [`05-已完成功能.md`](./05-已完成功能.md) | **已完成功能冻结快照**（平时不动，仅明确指令下更新） | 冻结 |")
    A("| [`../design.md`](../design.md) | UI 组件样式明细（**§4 最常用**） | 活文档（★改 UI 前必读） |")
    A("")
    for fname, title in [("01-需求规格说明书.md", "01 · 需求规格说明书"),
                         ("04-开发执行步骤.md", "04 · 开发执行步骤"),
                         ("05-已完成功能.md", "05 · 已完成功能")]:
        A("### %s —— 章节直达" % title)
        A("")
        for text, a in chapters(fname):
            A("- [%s](./%s#%s)" % (text, fname, a))
        A("")
    ch02 = chapters("02-技术方案.md")
    A("### 02 · 技术方案 —— 章节直达（%d 章）" % len(ch02))
    A("")
    A("> 每章内部还有 `§x.y` 小节，见该文档**顶部的完整目录**。")
    A("")
    for text, a in ch02:
        A("- [%s](./02-技术方案.md#%s)" % (text, a))
    A("")
    A("### design.md —— 章节直达")
    A("")
    A("- [1. 配色](../design.md#1-配色) · [2. 字体](../design.md#2-字体) · [3. 间距](../design.md#3-间距)")
    A("- [4. 组件样式](../design.md#4-组件样式)（4.1~4.21，UI 改动**最常看**）")
    A("- [5. 动画规则](../design.md#5-动画规则) · [6. 关键约定](../design.md#6-关键约定实现注意)")
    A("")
    A("## 开发日志")
    A("")
    A("- 路径：`../devlog/YYYY-MM-DD.md`（每天开发结束后追加「已完成 / 待办 / 问题」）")
    A("")
    A("## 计划总览")
    A("")
    A("- 路径：`C:\\Users\\xyz13\\.workbuddy\\plans\\radiant-vortex-darwin.md`")
    A("")
    (DOCS / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("[ok] docs/README.md：索引页 %d 行" % (len(lines) + 1))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    for rel in TOC_DOCS:
        rebuild_toc(rel)
    rewrite_readme()

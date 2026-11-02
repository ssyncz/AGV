# -*- coding: utf-8 -*-
"""Build the scheduling/path-planning report DOCX from the Markdown source."""
from __future__ import annotations

import os
import re
import shutil
import tempfile
from pathlib import Path

from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(r"D:\python\AGV")
SOURCE = ROOT / "docs" / "report" / "调度与路径规划.md"
OUT_DIR = Path(r"D:\学习资料\制造系统感知分析与决策")
OUT_DOCX = OUT_DIR / "AGV智能调度系统_调度与路径规划.docx"
TEMP_DIR = Path(tempfile.gettempdir()) / "agv_scheduling_report_build"
TEMP_DIR.mkdir(parents=True, exist_ok=True)

CONTENT_WIDTH_CM = 16.6
BODY_FONT = "宋体"
HEAD_FONT = "微软雅黑"
LATIN_FONT = "Times New Roman"
CODE_FONT = "Consolas"
DARK_BLUE = RGBColor(31, 78, 121)
MID_BLUE = RGBColor(46, 116, 181)
GRAY = RGBColor(95, 95, 95)
LIGHT_GRAY = "F2F2F2"
TABLE_HEADER = "1F4E79"
TABLE_ALT = "F3F7FB"

FORMULAS = [
    "G = (V, E, W)",
    "π = (i_1, i_2, …, i_n)",
    "D(π) = d(s, p_i1) + d(p_i1, q_i1)\n+ Σ_(k=2..n) [d(q_i(k-1), p_ik) + d(p_ik, q_ik)]",
    "J = C_max + w_a N_AGV + w_w W + w_d D + w_p Σ_i priority_i C_i",
    "dist[v] = min(dist[v], dist[u] + w(u,v))",
    "O((V + E) log V)",
    "f(v) = g(v) + h(v)",
    "(mask, last)",
    "dp[mask ∪ {k}][k] = min_(last∈mask) (dp[mask][last] + c(last,k))",
    "c(last,k) = d(q_last, p_k) + d(p_k, q_k)",
    "O(n² 2ⁿ)",
    "O(n 2ⁿ)",
]

FIGURES_BEFORE = {
    "2.2 一次任务的路径构成": [
        (ROOT / "docs" / "教材配图" / "fig-01-map.png", "图 1  仓库地图与道路拓扑", 16.0)
    ],
    "3.6 算法选择与理由": [
        (ROOT / "docs" / "教材配图" / "fig-02-dijkstra.png", "图 2  CHARGE 到 HOME1 的最短路径与距离场", 16.0)
    ],
    "4.2 状态压缩动态规划": [
        (ROOT / "docs" / "教材配图" / "fig-04-order.png", "图 3  同一批任务采用不同顺序时的总里程差异", 16.0)
    ],
    "4.3 启发式算法：最近邻 + 2-opt": [
        (ROOT / "docs" / "教材配图" / "fig-05-dp.png", "图 4  穷举法与状态压缩动态规划的运算量对比", 16.0)
    ],
    "4.8 局限": [
        (ROOT / "docs" / "教材配图" / "ui-02b-dispatch-single-result.png", "图 5  单台 AGV 多任务调度运行界面", 15.0)
    ],
    "5.3 时间窗避碰": [
        (ROOT / "docs" / "教材配图" / "fig-06-vns.png", "图 6  多台 AGV 联合调度流程（图中 VNS 为变邻域搜索的通用写法，代码实现为 VND）", 9.6)
    ],
    "6.1 核心代码": [
        (ROOT / "docs" / "教材配图" / "fig-03-arch.png", "图 7  系统总体架构", 15.0)
    ],
}


def set_east_asia_font(run, latin: str, east_asia: str) -> None:
    run.font.name = latin
    rpr = run._element.get_or_add_rPr()
    rfonts = rpr.rFonts
    if rfonts is None:
        rfonts = OxmlElement("w:rFonts")
        rpr.insert(0, rfonts)
    rfonts.set(qn("w:ascii"), latin)
    rfonts.set(qn("w:hAnsi"), latin)
    rfonts.set(qn("w:eastAsia"), east_asia)


def set_run(run, size: float = 10.5, bold: bool = False, color=None, italic: bool = False,
            latin: str = LATIN_FONT, east_asia: str = BODY_FONT) -> None:
    run.font.size = Pt(size)
    run.bold = bold
    run.italic = italic
    if color is not None:
        run.font.color.rgb = color
    set_east_asia_font(run, latin, east_asia)


def remove_paragraph_borders(paragraph) -> None:
    p_pr = paragraph._p.get_or_add_pPr()
    for border in list(p_pr.findall(qn("w:pBdr"))):
        p_pr.remove(border)


def remove_style_borders(style) -> None:
    p_pr = style._element.find(qn("w:pPr"))
    if p_pr is None:
        return
    for border in list(p_pr.findall(qn("w:pBdr"))):
        p_pr.remove(border)

def shade_cell(cell, fill: str) -> None:
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = tc_pr.find(qn("w:shd"))
    if shd is None:
        shd = OxmlElement("w:shd")
        tc_pr.append(shd)
    shd.set(qn("w:fill"), fill)


def shade_paragraph(paragraph, fill: str) -> None:
    p_pr = paragraph._p.get_or_add_pPr()
    shd = p_pr.find(qn("w:shd"))
    if shd is None:
        shd = OxmlElement("w:shd")
        p_pr.append(shd)
    shd.set(qn("w:fill"), fill)


def set_cell_margins(cell, top=60, start=70, bottom=60, end=70) -> None:
    tc = cell._tc
    tc_pr = tc.get_or_add_tcPr()
    tc_mar = tc_pr.first_child_found_in("w:tcMar")
    if tc_mar is None:
        tc_mar = OxmlElement("w:tcMar")
        tc_pr.append(tc_mar)
    for m, value in (("top", top), ("start", start), ("bottom", bottom), ("end", end)):
        node = tc_mar.find(qn(f"w:{m}"))
        if node is None:
            node = OxmlElement(f"w:{m}")
            tc_mar.append(node)
        node.set(qn("w:w"), str(value))
        node.set(qn("w:type"), "dxa")


def set_repeat_table_header(row) -> None:
    tr_pr = row._tr.get_or_add_trPr()
    tbl_header = OxmlElement("w:tblHeader")
    tbl_header.set(qn("w:val"), "true")
    tr_pr.append(tbl_header)


def prevent_row_split(row) -> None:
    tr_pr = row._tr.get_or_add_trPr()
    cant_split = OxmlElement("w:cantSplit")
    tr_pr.append(cant_split)


def set_paragraph_left_border(paragraph, color: str = "A6A6A6") -> None:
    p_pr = paragraph._p.get_or_add_pPr()
    p_bdr = p_pr.find(qn("w:pBdr"))
    if p_bdr is None:
        p_bdr = OxmlElement("w:pBdr")
        p_pr.append(p_bdr)
    left = OxmlElement("w:left")
    left.set(qn("w:val"), "single")
    left.set(qn("w:sz"), "12")
    left.set(qn("w:space"), "8")
    left.set(qn("w:color"), color)
    p_bdr.append(left)


def add_page_field(paragraph, instruction: str) -> None:
    run = paragraph.add_run()
    fld_begin = OxmlElement("w:fldChar")
    fld_begin.set(qn("w:fldCharType"), "begin")
    instr = OxmlElement("w:instrText")
    instr.set(qn("xml:space"), "preserve")
    instr.text = f" {instruction} "
    fld_sep = OxmlElement("w:fldChar")
    fld_sep.set(qn("w:fldCharType"), "separate")
    fld_end = OxmlElement("w:fldChar")
    fld_end.set(qn("w:fldCharType"), "end")
    run._r.append(fld_begin)
    run._r.append(instr)
    run._r.append(fld_sep)
    run._r.append(fld_end)
    set_run(run, size=9, color=GRAY)


def add_alt_text(inline_shape, title: str, description: str) -> None:
    doc_pr = inline_shape._inline.docPr
    doc_pr.set("title", title)
    doc_pr.set("descr", description)


def clean_inline_math(text: str) -> str:
    def normalize(expr: str) -> str:
        expr = expr.strip()
        replacements = {
            r"\le": "≤", r"\geq": "≥", r"\ge": "≥", r"\times": "×",
            r"\ldots": "…", r"\cup": "∪", r"\in": "∈", r"\sum": "Σ",
            r"\log": "log", r"\max": "max", r"\min": "min",
            r"\left": "", r"\right": "", r"\,": "", r"\;": "", r"\ ": " ",
            r"\{": "{", r"\}": "}",
        }
        for old, new in replacements.items():
            expr = expr.replace(old, new)
        expr = re.sub(r"\\mathrm\{([^{}]+)\}", r"\1", expr)
        expr = re.sub(r"\\text\{([^{}]+)\}", r"\1", expr)
        expr = expr.replace("^2", "²").replace("^n", "ⁿ")
        expr = expr.replace("\\", "")
        return re.sub(r"\s+", " ", expr).strip()

    return re.sub(r"\\\((.*?)\\\)", lambda m: normalize(m.group(1)), text)


def parse_inline_runs(paragraph, text: str, *, size: float = 10.5, bold: bool = False,
                      color=None, italic: bool = False) -> None:
    text = clean_inline_math(text)
    parts = re.split(r"(\*\*.*?\*\*|`[^`]+`)", text)
    for part in parts:
        if not part:
            continue
        if part.startswith("**") and part.endswith("**"):
            run = paragraph.add_run(part[2:-2])
            set_run(run, size=size, bold=True, color=color, italic=italic)
        elif part.startswith("`") and part.endswith("`"):
            run = paragraph.add_run(part[1:-1])
            set_run(run, size=max(8.0, size - 0.8), color=RGBColor(120, 45, 35),
                    italic=False, latin=CODE_FONT, east_asia=CODE_FONT)
            run.font.highlight_color = None
        else:
            run = paragraph.add_run(part)
            set_run(run, size=size, bold=bold, color=color, italic=italic)


def configure_styles(doc: Document) -> None:
    styles = doc.styles
    normal = styles["Normal"]
    normal.font.name = LATIN_FONT
    normal.font.size = Pt(10.5)
    normal._element.rPr.rFonts.set(qn("w:eastAsia"), BODY_FONT)
    normal.paragraph_format.line_spacing = 1.5
    normal.paragraph_format.space_after = Pt(3)
    normal.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY

    title = styles["Title"]
    title.font.name = HEAD_FONT
    title.font.size = Pt(26)
    title.font.bold = True
    title.font.color.rgb = RGBColor(0, 0, 0)
    title._element.rPr.rFonts.set(qn("w:eastAsia"), HEAD_FONT)
    title.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.CENTER
    title.paragraph_format.space_before = Pt(0)
    title.paragraph_format.space_after = Pt(12)
    remove_style_borders(title)

    subtitle = styles["Subtitle"]
    subtitle.font.name = HEAD_FONT
    subtitle.font.size = Pt(14)
    subtitle.font.color.rgb = GRAY
    subtitle._element.rPr.rFonts.set(qn("w:eastAsia"), HEAD_FONT)
    subtitle.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.CENTER

    heading_specs = {
        "Heading 1": (16, DARK_BLUE, 14, 7),
        "Heading 2": (13.5, DARK_BLUE, 10, 5),
        "Heading 3": (11.5, RGBColor(0, 0, 0), 8, 4),
        "Heading 4": (10.5, RGBColor(0, 0, 0), 6, 3),
    }
    for style_name, (size, color, before, after) in heading_specs.items():
        style = styles[style_name]
        style.font.name = HEAD_FONT
        style.font.size = Pt(size)
        style.font.bold = True
        style.font.color.rgb = color
        style._element.rPr.rFonts.set(qn("w:eastAsia"), HEAD_FONT)
        style.paragraph_format.space_before = Pt(before)
        style.paragraph_format.space_after = Pt(after)
        style.paragraph_format.keep_with_next = True

    for style_name in ("List Bullet", "List Number"):
        style = styles[style_name]
        style.font.name = LATIN_FONT
        style.font.size = Pt(10.5)
        style._element.rPr.rFonts.set(qn("w:eastAsia"), BODY_FONT)
        style.paragraph_format.space_after = Pt(2)
        style.paragraph_format.line_spacing = 1.35

    caption = styles["Caption"]
    caption.font.name = BODY_FONT
    caption.font.size = Pt(9)
    caption.font.color.rgb = GRAY
    caption._element.rPr.rFonts.set(qn("w:eastAsia"), BODY_FONT)
    caption.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.CENTER
    caption.paragraph_format.space_before = Pt(3)
    caption.paragraph_format.space_after = Pt(6)


def setup_section(doc: Document) -> None:
    section = doc.sections[0]
    section.page_width = Cm(21.0)
    section.page_height = Cm(29.7)
    section.top_margin = Cm(2.0)
    section.bottom_margin = Cm(2.0)
    section.left_margin = Cm(2.2)
    section.right_margin = Cm(2.2)
    section.header_distance = Cm(1.0)
    section.footer_distance = Cm(1.0)
    section.different_first_page_header_footer = True

    header = section.header
    p = header.paragraphs[0]
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run("AGV智能调度系统  |  调度与路径规划")
    set_run(run, size=8.5, color=GRAY, latin=HEAD_FONT, east_asia=HEAD_FONT)

    footer = section.footer
    p = footer.paragraphs[0]
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run("第 ")
    set_run(run, size=9, color=GRAY)
    add_page_field(p, "PAGE")
    run = p.add_run(" 页 / 共 ")
    set_run(run, size=9, color=GRAY)
    add_page_field(p, "NUMPAGES")
    run = p.add_run(" 页")
    set_run(run, size=9, color=GRAY)


def add_label_heading(doc: Document, text: str) -> None:
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.LEFT
    p.paragraph_format.space_before = Pt(8)
    p.paragraph_format.space_after = Pt(8)
    run = p.add_run(text)
    set_run(run, size=16, bold=True, color=DARK_BLUE, latin=HEAD_FONT, east_asia=HEAD_FONT)


def add_cover(doc: Document) -> None:
    for _ in range(4):
        doc.add_paragraph("")
    p = doc.add_paragraph(style="Title")
    remove_paragraph_borders(p)
    p.add_run("AGV智能调度系统调度与路径规划")
    p = doc.add_paragraph(style="Subtitle")
    p.add_run("课程总结大报告分册")
    for _ in range(3):
        doc.add_paragraph("")

    info = [
        ("课程", "制造系统感知分析与决策"),
        ("项目", "AGV 智能调度系统"),
        ("报告范围", "任务 1、任务 2、任务 3"),
        ("实验日期", "2026 年 10 月 26 日"),
        ("证据版本", "30d0a3d9"),
    ]
    table = doc.add_table(rows=len(info), cols=2)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False
    table.style = "Table Grid"
    for idx, (key, value) in enumerate(info):
        row = table.rows[idx]
        prevent_row_split(row)
        left, right = row.cells
        left.width = Cm(4.0)
        right.width = Cm(11.4)
        shade_cell(left, "E8EEF5")
        for cell in (left, right):
            set_cell_margins(cell, top=90, bottom=90)
            cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
        lp = left.paragraphs[0]
        lp.alignment = WD_ALIGN_PARAGRAPH.CENTER
        r = lp.add_run(key)
        set_run(r, size=10.5, bold=True, latin=HEAD_FONT, east_asia=HEAD_FONT)
        rp = right.paragraphs[0]
        rp.alignment = WD_ALIGN_PARAGRAPH.LEFT
        r = rp.add_run(value)
        set_run(r, size=10.5)

    for _ in range(6):
        doc.add_paragraph("")
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = p.add_run("2026 年 10 月")
    set_run(r, size=11, color=GRAY, latin=HEAD_FONT, east_asia=HEAD_FONT)
    doc.add_page_break()


def add_abstract(doc: Document) -> None:
    add_label_heading(doc, "摘要")
    paragraphs = [
        "本分册报告 AGV 智能调度系统中的路径规划、单台 AGV 多任务顺序优化和多台 AGV 联合调度。报告不局限于功能说明，而是按照“问题定义、候选算法、实验设置、结果分析、选型理由、局限与改进”的统一结构评价每个算法。",
        "实验使用项目真实地图、任务模板和调度服务实现。路径规划在 76 个节点和 103 条道路的地图上比较 BFS、Dijkstra 与 A*；单台 AGV 在 4 至 14 个任务规模上比较输入顺序、暴力枚举、状态压缩 DP 和最近邻加 2-opt；多台 AGV 在真实仓库场景和 15 个 Solomon 风格合成算例上比较基线贪心、最优插入和插入加 VND。",
        "结果表明，Dijkstra 的绝对耗时已达到微秒级，路径缓存比更换路径算法带来更明显的工程收益；单台 AGV 调度中，DP 在 10 个任务时平均约 5.61 ms，NN+2-opt 相对精确解的平均差距为 2.93% 至 10.35%；当前 6 任务 4 AGV 场景中，makespan 从 149.64 s 降到 131.71 s，综合目标改进 6.44%，其中最优插入贡献 6.17%，VND 在插入解上仅再改进约 0.29%。",
        "报告同时说明了节点时间窗、综合目标权重、时间预算和随机种子等实验条件，并明确当前方法不能保证多车全局最优，也未严格建模边冲突与死锁。",
    ]
    for text in paragraphs:
        p = doc.add_paragraph()
        p.paragraph_format.first_line_indent = Cm(0.74)
        parse_inline_runs(p, text)
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(8)
    r = p.add_run("关键词：")
    set_run(r, size=10.5, bold=True)
    r = p.add_run("AGV 调度；路径规划；Dijkstra；动态规划；变邻域下降；多目标优化")
    set_run(r, size=10.5)
    doc.add_page_break()


def add_toc_page(doc: Document) -> None:
    add_label_heading(doc, "目录")
    p = doc.add_paragraph("[[TOC]]")
    p.paragraph_format.space_after = Pt(0)
    doc.add_page_break()


def add_heading(doc: Document, text: str, level: int, *, page_break: bool = False) -> None:
    if page_break:
        doc.add_page_break()
    p = doc.add_paragraph(style=f"Heading {level}")
    parse_inline_runs(p, text, size={1: 16, 2: 13.5, 3: 11.5, 4: 10.5}[level], bold=True,
                      color=DARK_BLUE if level <= 2 else RGBColor(0, 0, 0))
    p.paragraph_format.keep_with_next = True


def add_body_paragraph(doc: Document, text: str) -> None:
    p = doc.add_paragraph()
    p.paragraph_format.first_line_indent = Cm(0.74)
    p.paragraph_format.line_spacing = 1.5
    p.paragraph_format.space_after = Pt(3)
    p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    parse_inline_runs(p, text)


def add_list_item(doc: Document, marker: str, text: str) -> None:
    p = doc.add_paragraph()
    p.paragraph_format.left_indent = Cm(0.78)
    p.paragraph_format.first_line_indent = Cm(-0.48)
    p.paragraph_format.line_spacing = 1.35
    p.paragraph_format.space_after = Pt(2)
    p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    r = p.add_run(marker + " ")
    set_run(r, size=10.5, bold=marker not in ("•",))
    parse_inline_runs(p, text)


def add_quote(doc: Document, text: str) -> None:
    p = doc.add_paragraph()
    p.paragraph_format.left_indent = Cm(0.75)
    p.paragraph_format.right_indent = Cm(0.5)
    p.paragraph_format.space_before = Pt(4)
    p.paragraph_format.space_after = Pt(5)
    p.paragraph_format.line_spacing = 1.35
    p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    shade_paragraph(p, "F2F5F8")
    set_paragraph_left_border(p, "7F9DB9")
    parse_inline_runs(p, text, size=10.2, italic=True, color=RGBColor(55, 55, 55))


def add_code_block(doc: Document, lines: list[str]) -> None:
    if not lines:
        return
    table = doc.add_table(rows=1, cols=1)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False
    cell = table.cell(0, 0)
    cell.width = Cm(CONTENT_WIDTH_CM)
    shade_cell(cell, "F3F4F6")
    set_cell_margins(cell, top=90, start=120, bottom=90, end=120)
    p = cell.paragraphs[0]
    p.paragraph_format.space_after = Pt(0)
    p.paragraph_format.line_spacing = 1.0
    p.alignment = WD_ALIGN_PARAGRAPH.LEFT
    p_pr = p._p.get_or_add_pPr()
    jc = p_pr.find(qn("w:jc"))
    if jc is None:
        jc = OxmlElement("w:jc")
        p_pr.append(jc)
    jc.set(qn("w:val"), "left")
    for idx, line in enumerate(lines):
        if idx:
            p.add_run().add_break()
        r = p.add_run(line)
        set_run(r, size=8.5, latin=CODE_FONT, east_asia=CODE_FONT)
    doc.add_paragraph().paragraph_format.space_after = Pt(0)


def add_figure(doc: Document, path: Path, caption: str, width_cm: float) -> None:
    if not path.exists():
        return
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.keep_with_next = True
    p.paragraph_format.space_before = Pt(6)
    p.paragraph_format.space_after = Pt(2)
    run = p.add_run()
    shape = run.add_picture(str(path), width=Cm(width_cm))
    add_alt_text(shape, caption, caption)
    cap = doc.add_paragraph(style="Caption")
    cap.paragraph_format.keep_together = True
    r = cap.add_run(caption)
    set_run(r, size=9, color=GRAY)


def make_formula_images() -> list[Path]:
    font_path = Path(r"C:\Windows\Fonts\cambria.ttc")
    font = ImageFont.truetype(str(font_path), 56, index=0)
    outputs = []
    for idx, formula in enumerate(FORMULAS, start=1):
        lines = formula.splitlines()
        probe = Image.new("RGBA", (10, 10), (255, 255, 255, 0))
        draw = ImageDraw.Draw(probe)
        bboxes = [draw.textbbox((0, 0), line, font=font) for line in lines]
        line_h = max((b[3] - b[1]) for b in bboxes)
        line_gap = 18
        width = max((b[2] - b[0]) for b in bboxes) + 80
        height = line_h * len(lines) + line_gap * (len(lines) - 1) + 60
        image = Image.new("RGBA", (max(width, 200), max(height, 100)), (255, 255, 255, 0))
        draw = ImageDraw.Draw(image)
        y = 30
        for line in lines:
            bbox = draw.textbbox((0, 0), line, font=font)
            x = (image.width - (bbox[2] - bbox[0])) // 2
            draw.text((x, y), line, font=font, fill=(0, 0, 0, 255))
            y += line_h + line_gap
        path = TEMP_DIR / f"equation_{idx:02d}.png"
        image.save(path)
        outputs.append(path)
    return outputs


def add_equation(doc: Document, image_path: Path, index: int) -> None:
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(4)
    p.paragraph_format.space_after = Pt(6)
    run = p.add_run()
    with Image.open(image_path) as img:
        ratio = img.height / img.width
    formula_text = FORMULAS[index - 1]
    length = len(formula_text.replace("\n", " "))
    if "\n" in formula_text:
        width_cm = 12.5
    elif length <= 8:
        width_cm = 4.5
    elif length <= 16:
        width_cm = 6.0
    elif length <= 30:
        width_cm = 8.0
    elif length <= 50:
        width_cm = 10.0
    else:
        width_cm = 12.5
    if ratio > 0.35:
        width_cm = min(width_cm, 4.5 / ratio)
    shape = run.add_picture(str(image_path), width=Cm(width_cm))
    add_alt_text(shape, f"公式 {index}", FORMULAS[index - 1])


def is_table_separator(line: str) -> bool:
    cells = [c.strip() for c in line.strip().strip("|").split("|")]
    return bool(cells) and all(re.fullmatch(r":?-{3,}:?", c) for c in cells)


def is_special_start(line: str) -> bool:
    s = line.strip()
    return (
        not s or s == "---" or s.startswith("#") or s.startswith("|") or
        s.startswith("```") or s.startswith(">") or s == "$$" or
        re.match(r"^\d+\.\s+", s) is not None or s.startswith("- ")
    )


def parse_table(lines: list[str], start: int) -> tuple[list[list[str]], int]:
    rows = []
    i = start
    while i < len(lines) and lines[i].strip().startswith("|"):
        raw = lines[i].strip()
        if not is_table_separator(raw):
            cells = [c.strip() for c in raw.strip("|").split("|")]
            rows.append(cells)
        i += 1
    return rows, i


def add_markdown_table(doc: Document, rows: list[list[str]]) -> None:
    if not rows:
        return
    cols = max(len(r) for r in rows)
    rows = [r + [""] * (cols - len(r)) for r in rows]
    table = doc.add_table(rows=len(rows), cols=cols)
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = True

    lengths = [max(len(clean_inline_math(row[c])) for row in rows) for c in range(cols)]
    weights = [max(5.0, min(float(length), 24.0)) for length in lengths]
    total = sum(weights)
    widths = [CONTENT_WIDTH_CM * w / total for w in weights]

    font_size = 8.2 if cols >= 7 else (8.7 if cols >= 5 else 9.2)
    for r_idx, row_data in enumerate(rows):
        row = table.rows[r_idx]
        prevent_row_split(row)
        if r_idx == 0:
            set_repeat_table_header(row)
        for c_idx, text in enumerate(row_data):
            cell = row.cells[c_idx]
            cell.width = Cm(widths[c_idx])
            set_cell_margins(cell, top=45, bottom=45, start=55, end=55)
            cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
            if r_idx == 0:
                shade_cell(cell, TABLE_HEADER)
            elif r_idx % 2 == 0:
                shade_cell(cell, TABLE_ALT)
            p = cell.paragraphs[0]
            p.paragraph_format.space_after = Pt(0)
            p.paragraph_format.line_spacing = 1.0
            p.paragraph_format.first_line_indent = Cm(0)
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER if r_idx == 0 else WD_ALIGN_PARAGRAPH.LEFT
            parse_inline_runs(
                p, text, size=font_size, bold=(r_idx == 0),
                color=RGBColor(255, 255, 255) if r_idx == 0 else None,
            )
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(0)
    p.paragraph_format.line_spacing = 1.0


def parse_markdown(doc: Document, text: str) -> None:
    all_lines = text.splitlines()
    start = next((i for i, line in enumerate(all_lines) if line.startswith("## 1. ")), 0)
    lines = all_lines[start:]
    equation_images = make_formula_images()
    equation_index = 0
    i = 0
    first_h1_seen = False
    chapter_break_titles = {
        "3. 路径规划算法评价", "4. 单 AGV 多任务顺序优化",
        "5. 多 AGV 联合调度", "6. 软件实现与系统集成",
        "7. 综合讨论", "8. 实验可复现性", "9. 后续改进",
        "参考文献",
    }

    while i < len(lines):
        raw = lines[i]
        s = raw.strip()
        if not s or s == "---":
            i += 1
            continue

        if s.startswith("```"):
            lang = s[3:].strip().lower()
            block = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                block.append(lines[i].rstrip())
                i += 1
            i += 1
            if lang != "mermaid":
                add_code_block(doc, block)
            continue

        if s == "$$":
            i += 1
            equation_lines = []
            while i < len(lines) and lines[i].strip() != "$$":
                equation_lines.append(lines[i].strip())
                i += 1
            i += 1
            equation_index += 1
            if equation_index <= len(equation_images):
                add_equation(doc, equation_images[equation_index - 1], equation_index)
            continue

        if s.startswith("#"):
            level = len(s) - len(s.lstrip("#"))
            title = s[level:].strip()
            if title in FIGURES_BEFORE:
                for path, caption, width in FIGURES_BEFORE[title]:
                    add_figure(doc, path, caption, width)
            page_break = (
                level == 2 and title in chapter_break_titles and
                title != "1. 问题定义与评价目标" and first_h1_seen
            )
            add_heading(doc, title, min(level - 1, 4), page_break=page_break)
            if level == 2:
                first_h1_seen = True
            i += 1
            continue

        if s.startswith("|") and i + 1 < len(lines) and is_table_separator(lines[i + 1].strip()):
            rows, i = parse_table(lines, i)
            add_markdown_table(doc, rows)
            continue

        if s.startswith(">"):
            add_quote(doc, s.lstrip(">").strip())
            i += 1
            continue

        m = re.match(r"^(\d+)\.\s+(.*)$", s)
        if m:
            add_list_item(doc, m.group(1) + ".", m.group(2))
            i += 1
            continue
        if s.startswith("- "):
            add_list_item(doc, "•", s[2:].strip())
            i += 1
            continue

        para = [s]
        i += 1
        while i < len(lines) and not is_special_start(lines[i]):
            para.append(lines[i].strip())
            i += 1
        add_body_paragraph(doc, "".join(para))


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    if TEMP_DIR.exists():
        shutil.rmtree(TEMP_DIR)
    TEMP_DIR.mkdir(parents=True, exist_ok=True)

    source_text = SOURCE.read_text(encoding="utf-8")
    doc = Document()
    configure_styles(doc)
    setup_section(doc)
    add_cover(doc)
    add_abstract(doc)
    add_toc_page(doc)
    parse_markdown(doc, source_text)

    props = doc.core_properties
    props.title = "AGV智能调度系统调度与路径规划"
    props.subject = "制造系统感知分析与决策课程总结大报告分册"
    props.keywords = "AGV调度, 路径规划, Dijkstra, 动态规划, 变邻域下降"
    props.comments = "由课程项目实验数据生成"

    doc.save(OUT_DOCX)
    print(OUT_DOCX)


if __name__ == "__main__":
    main()

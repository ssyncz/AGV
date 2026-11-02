# -*- coding: utf-8 -*-
"""Build the BIT thesis-template version of the scheduling report."""
from __future__ import annotations

import json
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
from docx.shared import Cm, Pt
from lxml import etree

ROOT = Path(r"D:\python\AGV")
TEMPLATE = Path(r"D:\学习资料\制造系统感知分析与决策\北京理工大学本科生毕业设计（论文）模板（2023年12月）.docx")
SOURCE = ROOT / "docs" / "report" / "调度与路径规划_论文模板版.md"
TEMP_DIR = Path(tempfile.gettempdir()) / "agv_thesis_template_build"
OUT_DOCX = TEMP_DIR / "AGV智能调度系统_调度与路径规划_模板版.docx"
OMML_PATH = ROOT / "docs" / "report" / "evidence" / "formulas_omml.json"
FINAL_DOCX = Path(r"D:\学习资料\制造系统感知分析与决策\AGV智能调度系统_调度与路径规划.docx")

TITLE_CN = "AGV智能调度系统调度与路径规划"
TITLE_EN = "Scheduling and Path Planning of an AGV Intelligent Dispatching System"
DATE_CN = "2026 年 10 月 26 日"
HEADER_TEXT = "北京理工大学本科生毕业设计（论文）"

CHINESE_ABSTRACT = [
    "本文研究 AGV 智能调度系统中的路径规划、单台车辆任务排序和多台车辆联合调度。系统将仓库抽象为带权图，以 Dijkstra 算法计算任意两点之间的最短路径，并通过路径缓存减少重复查询。单台 AGV 在 10 个任务以内采用状态压缩动态规划求精确顺序，更大规模采用最近邻与 2-opt 构造近似解。多台 AGV 调度先通过最优插入生成初始方案，再用变邻域下降调整任务分配、车内顺序和避碰等待。",
    "实验使用项目实际地图、任务模板和调度服务实现。在当前 76 节点地图上，Dijkstra 平均单次查询约 0.020 ms，路径缓存带来约 201.58 倍加速。单台 AGV 的 DP 在 10 个任务时平均约 5.61 ms，最近邻与 2-opt 相对精确解的平均差距为 2.93% 至 10.35%。当前 6 任务 4 AGV 场景的 makespan 从 149.64 s 降到 131.71 s，综合目标改进 6.44%。其中最优插入贡献 6.17%，VND 在插入解基础上继续改进约 0.29%。",
    "实验同时反映了多目标权重、节点级避碰和启发式最优性方面的限制。本文给出的实验协议、原始数据和复现命令可用于后续扩大算例规模，并比较更多调度算法。",
]
CHINESE_KEYWORDS = "关键词：AGV 调度；路径规划；Dijkstra；动态规划；变邻域下降；多目标优化"
ENGLISH_ABSTRACT = [
    "This report studies path planning, single-vehicle task sequencing, and multi-vehicle scheduling in an AGV intelligent dispatching system. The warehouse is modeled as a weighted graph. Dijkstra's algorithm computes the shortest path between any two nodes, and a route cache reduces repeated queries. For a single AGV, a bitmask dynamic program returns the exact task order when no more than ten tasks are assigned; nearest-neighbor construction with 2-opt is used for larger instances. For multiple AGVs, best insertion builds an initial schedule, and variable neighborhood descent then adjusts task assignment, vehicle order, and collision-avoidance waiting.",
    "Experiments use the project's actual map, task templates, and scheduling services. On the current 76-node map, the average Dijkstra query takes about 0.020 ms, and caching accelerates repeated queries by about 201.58 times. The DP takes about 5.61 ms for ten tasks, while the average gap between the exact solution and nearest-neighbor plus 2-opt ranges from 2.93% to 10.35%. In the current six-task, four-AGV case, makespan falls from 149.64 s to 131.71 s, and the composite objective improves by 6.44%. Best insertion contributes 6.17%; VND adds about 0.29% beyond the insertion solution.",
    "The results also show the limits of manually weighted objectives and node-level collision avoidance. The experimental protocol, raw data, and reproduction commands provide a basis for larger instances and further algorithm comparisons.",
]
ENGLISH_KEYWORDS = "Key Words: AGV scheduling; path planning; Dijkstra; dynamic programming; variable neighborhood descent; multi-objective optimization"

FORMULAS = [
    "G = (V, E, W)", "π = (i_1, i_2, …, i_n)",
    "D(π) = d(s, p_i1) + d(p_i1, q_i1)\n+ Σ_(k=2..n) [d(q_i(k-1), p_ik) + d(p_ik, q_ik)]",
    "J = C_max + w_a N_AGV + w_w W + w_d D + w_p Σ_i priority_i C_i",
    "dist[v] = min(dist[v], dist[u] + w(u,v))", "O((V + E) log V)",
    "f(v) = g(v) + h(v)", "(mask, last)",
    "dp[mask ∪ {k}][k] = min_(last∈mask) (dp[mask][last] + c(last,k))",
    "c(last,k) = d(q_last, p_k) + d(p_k, q_k)", "O(n² 2ⁿ)", "O(n 2ⁿ)",
]

FIGURES_BEFORE = {
    "2.2 一次任务的路径构成": [(ROOT / "docs" / "教材配图" / "fig-01-map.png", "仓库地图与道路拓扑", 15.2)],
    "3.6 算法选择与理由": [(ROOT / "docs" / "教材配图" / "fig-02-dijkstra.png", "CHARGE 到 HOME1 的最短路径与距离场", 15.2)],
    "4.2 状态压缩动态规划": [(ROOT / "docs" / "教材配图" / "fig-04-order.png", "同一批任务采用不同顺序时的总里程差异", 15.2)],
    "4.3 启发式算法：最近邻 + 2-opt": [(ROOT / "docs" / "教材配图" / "fig-05-dp.png", "穷举法与状态压缩动态规划的运算量对比", 15.2)],
    "4.8 局限": [(ROOT / "docs" / "教材配图" / "ui-02b-dispatch-single-result.png", "单台 AGV 多任务调度运行界面", 14.0)],
    "5.3 时间窗避碰": [(ROOT / "docs" / "教材配图" / "fig-06-vns.png", "多台 AGV 联合调度流程（图中 VNS 为变邻域搜索的通用写法，代码实现为 VND）", 9.2)],
    "6.1 核心代码": [(ROOT / "docs" / "教材配图" / "fig-03-arch.png", "系统总体架构", 14.0)],
}

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
NS = {"w": W_NS, "mc": "http://schemas.openxmlformats.org/markup-compatibility/2006"}

def clear_paragraph(p) -> None:
    for r in list(p.runs):
        p._p.remove(r._r)


def append_run(p, text: str, *, font: str | None = None, size: float | None = None,
               bold: bool | None = None):
    r = p.add_run(text)
    if font:
        r.font.name = font
        r._element.get_or_add_rPr().rFonts.set(qn("w:eastAsia"), font)
    if size:
        r.font.size = Pt(size)
    if bold is not None:
        r.bold = bold
    return r


def replace_para_text(p, text: str) -> None:
    clear_paragraph(p)
    append_run(p, text)


def remove_textbox_drawings(container) -> None:
    root = container.element if hasattr(container, "element") else container
    for drawing in list(root.xpath(".//*[local-name()='drawing'][.//*[local-name()='txbxContent']]")):
        parent = drawing.getparent()
        if parent is not None:
            parent.remove(drawing)
    for alt in list(root.xpath(".//*[local-name()='AlternateContent'][.//*[local-name()='txbxContent']]")):
        parent = alt.getparent()
        if parent is not None:
            parent.remove(alt)
    for pict in list(root.xpath(".//*[local-name()='pict'][.//*[local-name()='txbxContent']]")):
        parent = pict.getparent()
        if parent is not None:
            parent.remove(pict)


def remove_all_callouts(doc: Document) -> None:
    remove_textbox_drawings(doc.element.body)
    for section in doc.sections:
        for part in (section.header, section.footer, section.first_page_header, section.first_page_footer):
            try:
                remove_textbox_drawings(part)
            except Exception:
                pass


def set_page_number_format(section, fmt: str, start: int = 1) -> None:
    sect_pr = section._sectPr
    pg_num = sect_pr.find(qn("w:pgNumType"))
    if pg_num is None:
        pg_num = OxmlElement("w:pgNumType")
        sect_pr.append(pg_num)
    pg_num.set(qn("w:fmt"), fmt)
    pg_num.set(qn("w:start"), str(start))


def set_header_footer(doc: Document, section, *, fmt: str, start: int = 1) -> None:
    section.header.is_linked_to_previous = False
    section.footer.is_linked_to_previous = False
    hp = section.header.paragraphs[0]
    clear_paragraph(hp)
    try:
        hp.style = doc.styles["05-页眉格式"]
    except KeyError:
        pass
    hp.alignment = WD_ALIGN_PARAGRAPH.CENTER
    append_run(hp, HEADER_TEXT, font="宋体", size=9)
    fp = section.footer.paragraphs[0]
    clear_paragraph(fp)
    try:
        fp.style = doc.styles["06-页脚"]
    except KeyError:
        pass
    fp.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = fp.add_run()
    begin = OxmlElement("w:fldChar")
    begin.set(qn("w:fldCharType"), "begin")
    instr = OxmlElement("w:instrText")
    instr.set(qn("xml:space"), "preserve")
    instr.text = " PAGE "
    sep = OxmlElement("w:fldChar")
    sep.set(qn("w:fldCharType"), "separate")
    end = OxmlElement("w:fldChar")
    end.set(qn("w:fldCharType"), "end")
    r._r.append(begin)
    r._r.append(instr)
    r._r.append(sep)
    r._r.append(end)
    r.font.name = "宋体"
    r.font.size = Pt(9)
    set_page_number_format(section, fmt, start)


def set_outline_level(p, level: int = 0) -> None:
    p_pr = p._p.get_or_add_pPr()
    outline = p_pr.find(qn("w:outlineLvl"))
    if outline is None:
        outline = OxmlElement("w:outlineLvl")
        p_pr.append(outline)
    outline.set(qn("w:val"), str(level))


def add_plain(doc: Document, text: str, style: str):
    p = doc.add_paragraph(style=style)
    append_run(p, text)
    return p


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


def add_runs_from_markdown(p, text: str, *, base_size: float | None = None) -> None:
    text = clean_inline_math(text)
    parts = re.split(r"(`[^`]+`)", text)
    for part in parts:
        if not part:
            continue
        if part.startswith("`") and part.endswith("`"):
            append_run(p, part[1:-1], font="Consolas", size=(base_size - 0.8 if base_size else 9.0))
        else:
            append_run(p, part, size=base_size)


def add_body_paragraph(doc: Document, text: str) -> None:
    p = doc.add_paragraph(style="01-正文")
    add_runs_from_markdown(p, text, base_size=12)


def add_list_item(doc: Document, marker: str, text: str) -> None:
    p = doc.add_paragraph(style="01-正文")
    p.paragraph_format.first_line_indent = Cm(-0.6)
    p.paragraph_format.left_indent = Cm(0.72)
    add_runs_from_markdown(p, f"{marker} {text}", base_size=12)


def add_code_block(doc: Document, lines: list[str]) -> None:
    for line in lines:
        p = doc.add_paragraph(style="01-正文")
        p.paragraph_format.first_line_indent = Cm(0)
        p.paragraph_format.left_indent = Cm(0)
        p.paragraph_format.space_before = Pt(0)
        p.paragraph_format.space_after = Pt(0)
        p.alignment = WD_ALIGN_PARAGRAPH.LEFT
        p_pr = p._p.get_or_add_pPr()
        jc = p_pr.find(qn("w:jc"))
        if jc is None:
            jc = OxmlElement("w:jc")
            p_pr.append(jc)
        jc.set(qn("w:val"), "left")
        r = p.add_run(line)
        r.font.name = "Consolas"
        r._element.get_or_add_rPr().rFonts.set(qn("w:eastAsia"), "Consolas")
        r.font.size = Pt(9)

def load_omml_formulas() -> list[dict]:
    return json.loads(OMML_PATH.read_text(encoding="utf-8"))


def set_no_borders(table) -> None:
    tbl_pr = table._tbl.tblPr
    borders = tbl_pr.first_child_found_in("w:tblBorders")
    if borders is None:
        borders = OxmlElement("w:tblBorders")
        tbl_pr.append(borders)
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        node = borders.find(qn(f"w:{edge}"))
        if node is None:
            node = OxmlElement(f"w:{edge}")
            borders.append(node)
        node.set(qn("w:val"), "nil")


def add_equation(doc: Document, number: str, formula_index: int, formulas: list[dict]) -> None:
    table = doc.add_table(rows=1, cols=2)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False
    set_no_borders(table)
    left, right = table.rows[0].cells
    left.width = Cm(14.8)
    right.width = Cm(1.4)
    right.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
    omml_lines = formulas[formula_index - 1]["omml"]
    for idx, omml_xml in enumerate(omml_lines):
        p = left.paragraphs[0] if idx == 0 else left.add_paragraph()
        try:
            p.style = doc.styles["08-公式"]
        except KeyError:
            pass
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.first_line_indent = Cm(0)
        p.paragraph_format.space_before = Pt(0)
        p.paragraph_format.space_after = Pt(0)
        p._p.append(etree.fromstring(omml_xml.encode("utf-8")))
    rp = right.paragraphs[0]
    rp.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    rp.paragraph_format.first_line_indent = Cm(0)
    append_run(rp, f"({number})", size=10.5, font="Times New Roman")
    doc.add_paragraph()


def add_figure(doc: Document, path: Path, caption: str, width_cm: float) -> None:
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.first_line_indent = Cm(0)
    p.add_run().add_picture(str(path), width=Cm(width_cm))
    cap = doc.add_paragraph(style="07-图题&表题")
    append_run(cap, caption)
    doc.add_paragraph()


def is_table_separator(line: str) -> bool:
    cells = [c.strip() for c in line.strip().strip("|").split("|")]
    return bool(cells) and all(re.fullmatch(r":?-{3,}:?", c) for c in cells)


def parse_table(lines: list[str], start: int):
    rows = []
    i = start
    while i < len(lines) and lines[i].strip().startswith("|"):
        raw = lines[i].strip()
        if not is_table_separator(raw):
            rows.append([c.strip() for c in raw.strip("|").split("|")])
        i += 1
    return rows, i


def set_repeat_header(row) -> None:
    tr_pr = row._tr.get_or_add_trPr()
    node = OxmlElement("w:tblHeader")
    node.set(qn("w:val"), "true")
    tr_pr.append(node)


def prevent_row_split(row) -> None:
    row._tr.get_or_add_trPr().append(OxmlElement("w:cantSplit"))



def caption_title(text: str) -> str:
    return re.sub(r"^(?:\d+(?:\.\d+)*|附录[A-Z])\s*", "", text).strip()

def add_table(doc: Document, rows: list[list[str]], caption: str) -> None:
    if not rows:
        return
    cap = doc.add_paragraph(style="07-图题&表题")
    append_run(cap, caption)
    cols = max(len(r) for r in rows)
    rows = [r + [""] * (cols - len(r)) for r in rows]
    table = doc.add_table(rows=len(rows), cols=cols)
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = True
    lengths = [max(len(clean_inline_math(row[c])) for row in rows) for c in range(cols)]
    weights = [max(5.0, min(float(v), 24.0)) for v in lengths]
    total = sum(weights)
    widths = [16.0 * w / total for w in weights]
    cell_size = 8.2 if cols >= 7 else (8.8 if cols >= 4 else 9.4)
    for ri, data in enumerate(rows):
        row = table.rows[ri]
        prevent_row_split(row)
        if ri == 0:
            set_repeat_header(row)
        for ci, text in enumerate(data):
            cell = row.cells[ci]
            cell.width = Cm(widths[ci])
            cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
            p = cell.paragraphs[0]
            p.style = doc.styles["07-表格内文字"]
            p.paragraph_format.first_line_indent = Cm(0)
            p.paragraph_format.space_before = Pt(0)
            p.paragraph_format.space_after = Pt(0)
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            add_runs_from_markdown(p, text, base_size=cell_size)
            if ri == 0:
                for run in p.runs:
                    run.bold = True
    doc.add_paragraph()


def add_heading(doc: Document, text: str, style: str, *, page_break: bool = False):
    if page_break:
        doc.add_page_break()
    p = doc.add_paragraph(style=style)
    append_run(p, text)
    return p

def build_front_matter(doc: Document, section) -> None:
    set_header_footer(doc, section, fmt="upperRoman", start=1)
    add_heading(doc, TITLE_CN, "18-中文摘要标题")
    p = add_heading(doc, "摘　要", "18-中文摘要标题")
    set_outline_level(p, 0)
    for text in CHINESE_ABSTRACT:
        add_body_paragraph(doc, text)
    add_plain(doc, CHINESE_KEYWORDS, "19-中文摘要关键词")
    doc.add_page_break()

    add_heading(doc, TITLE_EN, "20-英文摘要标题")
    p = add_heading(doc, "Abstract", "20-英文摘要标题")
    set_outline_level(p, 0)
    for text in ENGLISH_ABSTRACT:
        p = doc.add_paragraph(style="22-英文摘要正文")
        append_run(p, text, font="Times New Roman", size=12)
    add_plain(doc, ENGLISH_KEYWORDS, "21-英文摘要关键词")
    doc.add_page_break()

    add_heading(doc, "目　录", "23-目录标题")
    tp = doc.add_paragraph("[[TOC]]")
    tp.paragraph_format.first_line_indent = Cm(0)


def build_body(doc: Document, section) -> None:
    set_header_footer(doc, section, fmt="decimal", start=1)
    lines = SOURCE.read_text(encoding="utf-8").splitlines()
    formulas = load_omml_formulas()
    formula_index = 0
    current_chapter = "0"
    table_no = 0
    figure_no = 0
    equation_no = 0
    current_heading = ""
    first_chapter = True
    i = 0

    while i < len(lines):
        s = lines[i].strip()
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
            while i < len(lines) and lines[i].strip() != "$$":
                i += 1
            i += 1
            formula_index += 1
            equation_no += 1
            if formula_index <= len(formulas):
                add_equation(doc, f"{current_chapter}-{equation_no}", formula_index, formulas)
            continue

        if s.startswith("#"):
            level = len(s) - len(s.lstrip("#"))
            title = s[level:].strip()
            if title in FIGURES_BEFORE:
                for path, caption, width in FIGURES_BEFORE[title]:
                    figure_no += 1
                    add_figure(doc, path, f"图{current_chapter}-{figure_no} {caption}", width)
            current_heading = title
            if level == 2:
                m = re.match(r"第(\d+)章", title)
                if m:
                    current_chapter = m.group(1)
                    add_heading(doc, title, "02-一级标题", page_break=not first_chapter)
                    first_chapter = False
                elif title.startswith("结"):
                    current_chapter = "0"
                    add_heading(doc, title, "09-结论&参考文献&附录&致谢标题", page_break=True)
                elif title.startswith("附"):
                    current_chapter = "A"
                    add_heading(doc, title, "09-结论&参考文献&附录&致谢标题", page_break=True)
                else:
                    add_heading(doc, title, "02-一级标题", page_break=True)
                table_no = 0
                figure_no = 0
                equation_no = 0
            elif level == 3:
                style = "04-三级标题" if current_chapter == "A" else "03-二级标题"
                add_heading(doc, title, style)
            else:
                add_heading(doc, title, "04-三级标题")
            i += 1
            continue

        if s.startswith("|") and i + 1 < len(lines) and is_table_separator(lines[i + 1].strip()):
            rows, i = parse_table(lines, i)
            table_no += 1
            add_table(doc, rows, f"表{current_chapter}-{table_no} {caption_title(current_heading)}")
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
        if s.startswith(">"):
            s = s.lstrip(">").strip()
        add_body_paragraph(doc, s)
        i += 1

def main() -> None:
    if TEMP_DIR.exists():
        shutil.rmtree(TEMP_DIR)
    TEMP_DIR.mkdir(parents=True, exist_ok=True)

    doc = Document(TEMPLATE)
    remove_all_callouts(doc)

    for p in doc.paragraphs:
        if p.style.name == "11-论文封面中文标题":
            replace_para_text(p, TITLE_CN)
        elif p.style.name == "07-图题&表题" and "Beijing Institute of Technology" in p.text:
            replace_para_text(p, TITLE_EN)
        elif p.style.name == "14-封面日期格式":
            replace_para_text(p, DATE_CN)

    body = doc.element.body
    cover_break = doc.sections[0]._sectPr.getparent().getparent()
    children = list(body)
    cover_index = children.index(cover_break)
    final_sect = body.find(qn("w:sectPr"))
    final_index = children.index(final_sect)
    for child in children[cover_index + 1:final_index]:
        body.remove(child)

    front_section = doc.sections[1]
    build_front_matter(doc, front_section)

    body_section = doc.add_section(WD_SECTION.NEW_PAGE)
    build_body(doc, body_section)

    doc.core_properties.title = TITLE_CN
    doc.core_properties.subject = "制造系统感知分析与决策课程论文报告"
    doc.core_properties.keywords = "AGV调度; 路径规划; Dijkstra; 动态规划; 变邻域下降"
    doc.save(OUT_DOCX)
    print(OUT_DOCX)


if __name__ == "__main__":
    main()

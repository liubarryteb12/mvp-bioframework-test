#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""export_manuscript.py — WP-9 三格式导出（云端执行）
产物（export/ 目录）:
  manuscript_编辑版.docx   = docx-A 纯文本 + [图 N位置] 占位符（给编辑改）
  manuscript_排版核对版.docx = docx-B 纯图片 + 图注（给排版核对）
  manuscript_gse31210.pdf  = pdf 文图合一（投稿/审阅）
  docA.txt / docB.txt / docP.txt = 三版本的文本层（export_guard 输入）
  export_report.json       = 守卫台账
一致性由同一内容源构造保证：图注串、参考文献节在三版本逐字节相同。
"""
import io, os, re, sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# 稿件定位：优先脚本同目录（云端仓库 analysis/ 布局），回落 本地 稿件/ 目录
MD = os.environ.get("MD_PATH") or next(
    p for p in [os.path.join(os.path.dirname(os.path.abspath(__file__)), "manuscript_gse31210.md"),
                os.path.join(BASE, "稿件", "manuscript_gse31210.md")]
    if os.path.exists(p))
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "export")
os.makedirs(OUT, exist_ok=True)
FIGDIR = os.environ.get("FIG_DIR", os.path.join(BASE, "figures"))
FIGS = {n: os.path.join(FIGDIR, f"0{n}_{k}.jpg")   # 300dpi jpg（四格式之一），docx/pdf 内嵌用
        for n, k in {1: "deg_volcano", 2: "enrichment_dotplot",
                     3: "survival_km_risk", 4: "performance_roc_cv"}.items()}

# ---------- 解析 md ----------
sections, cur = {}, None
for line in open(MD, encoding="utf-8"):
    line = line.rstrip("\n")
    m = re.match(r"^##\s+(.*)$", line)
    if m:
        cur = m.group(1).strip(); sections[cur] = []
    elif cur is not None:
        sections[cur].append(line)
paras = {k: [p.strip() for p in "\n".join(v).split("\n\n") if p.strip()]
         for k, v in sections.items()}

title = paras["标题"][0]
refs_block = "参考文献\n" + "\n".join(paras["参考文献"])
decl_block = "\n\n".join(paras["声明"])
captions = {}
for p in paras["图注"]:
    m = re.match(r"^图\s*(\d+)\s*[：:]\s*(.*)$", p, re.S)
    if m:
        captions[int(m.group(1))] = p.strip()
assert set(captions) == {1, 2, 3, 4}, f"图注解析异常: {sorted(captions)}"

# ---------- BMC 式版式要素（参照 07.参考文献 Wen 2022 / BMC Cancer 版式） ----------
# 摘要拆块：P1 首句（框架叙事：主发现前置）+ 背景/方法/结果/结论 子标题段
abs_text = paras["摘要"][0]
_abs_parts = re.split(r"(背景：|方法：|结果：|结论：)", abs_text)
P1 = _abs_parts[0].strip()
abs_blocks, _cur = [], None
for seg in _abs_parts[1:]:
    if seg in ("背景：", "方法：", "结果：", "结论："):
        _cur = seg.rstrip("：")
    elif _cur:
        abs_blocks.append((_cur, seg.strip()))
KEYWORDS = "关键词：肺腺癌；转录组风险评分；无复发生存；特征选择泄露；GEO"
TITLE_PAGE = [title, "作者信息（投稿前补全）", "单位，城市，国家", "通讯作者：姓名，邮箱"]
DECL_SUBS = [(p.split("：", 1)[0], p) for p in paras["声明"] if "：" in p]

# ---------- 结构序自检（正文排版规范 v1.0 · S3 机器可检条） ----------
order = [k for k in sections
         if k in ("标题", "摘要", "引言", "方法", "结果", "讨论", "结论", "声明", "参考文献")]
if "结论" not in order:
    STRUCT = "S1（默认序：结论由摘要'结论'段+讨论末段承载，BMC/Wen 口径）"
elif order.index("结论") > order.index("讨论"):
    STRUCT = "S2-a（结论独立节，讨论之后）"
else:
    STRUCT = "S2-c（结论前置，投稿前须核对期刊 Guide for Authors）"
_EXPECT = ["标题", "摘要", "引言", "方法", "结果", "讨论", "声明", "参考文献"]
if order != _EXPECT:
    raise SystemExit(f"结构序不符 S1：实际 {order}，期望 {_EXPECT}")
print(f"[结构序自检] {order} → {STRUCT}")

body_order = ["引言", "方法", "结果", "讨论"]   # 摘要单独按 BMC 式子标题渲染
citing = {}
for sec in body_order:
    for p in paras[sec]:
        for m in re.finditer(r"图\s*(\d+)", p):
            citing.setdefault(int(m.group(1)), (sec, p))

# ---------- 三份文本层 ----------
def with_captions():
    """正文，引用段落后紧跟图注段（T9.4 邻接）。"""
    out = []
    for sec in body_order:
        out.append(f"{sec}\n")
        for p in paras[sec]:
            out.append(p)
            for n, (s2, p2) in citing.items():
                if s2 == sec and p2 == p and n in captions:
                    out.append(captions[n])
    return out


abstract_lines = [P1] + [f"{k}：{v}" for k, v in abs_blocks] + [KEYWORDS]
body_lines = with_captions()
docA = "\n\n".join(TITLE_PAGE + ["摘要"] + abstract_lines + body_lines +
                   ["[图 1位置]", "[图 2位置]", "[图 3位置]", "[图 4位置]",
                    "声明"] + [p for _, p in DECL_SUBS] + [refs_block])
docB = "\n\n".join([captions[n] for n in sorted(captions)] + [refs_block])
# 教训：docB 文本层不放裸"图 N"行——守卫正则的 \s 可跨行吞并，"图 N\n图 N：图注"会粘成
# 双行图注导致 T9.3 逐字匹配失败；图注行本身含图号，图号集合不受影响。
docP = "\n\n".join(TITLE_PAGE + ["摘要"] + abstract_lines + body_lines +
                   ["声明"] + [p for _, p in DECL_SUBS] + [refs_block])
# 去掉文本层中的裸节名行（docA/docP 中节名与段落合流的处理已隐含）
for name, txt in (("docA", docA), ("docB", docB), ("docP", docP)):
    open(os.path.join(OUT, f"{name}.txt"), "w", encoding="utf-8").write(txt)

# ---------- 真 docx：编辑版（A，BMC 式版式） ----------
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Inches, Pt


def add_abstract_doc(doc):
    doc.add_heading("摘要", level=2)
    doc.add_paragraph(P1)
    for k, v in abs_blocks:
        p = doc.add_paragraph(); r = p.add_run(k); r.bold = True
        doc.add_paragraph(v)
    doc.add_paragraph(KEYWORDS)


def add_declarations_doc(doc):
    doc.add_heading("声明（Declarations）", level=2)
    for k, p in DECL_SUBS:
        pp = doc.add_paragraph(); r = pp.add_run(k); r.bold = True
        doc.add_paragraph(p)


def add_refs_doc(doc):
    doc.add_heading("参考文献", level=2)
    for p in paras["参考文献"]:
        doc.add_paragraph(p)


docA_real = Document()
docA_real.add_heading(title, 0)
for p in TITLE_PAGE[1:]:
    docA_real.add_paragraph(p)
add_abstract_doc(docA_real)
for sec in body_order:
    docA_real.add_heading(sec, level=2)
    for p in paras[sec]:
        docA_real.add_paragraph(p)
    for n, (s2, p2) in citing.items():
        if s2 == sec:
            docA_real.add_paragraph(captions[n])
for n in sorted(captions):
    docA_real.add_paragraph(f"[图 {n}位置]")
add_declarations_doc(docA_real)
add_refs_doc(docA_real)
docA_real.save(os.path.join(OUT, "manuscript_编辑版.docx"))

# ---------- 图件嵌入尺寸（排版纠错：只缩不放大，保 300dpi 有效分辨率） ----------
# 教训：曾硬编码 6.3in 宽，3.6–3.9in 的原图被放大 1.6–1.7 倍，有效 dpi 跌破 300（违反作图规范）
from PIL import Image as PILImage


def fig_width_in(n, max_in=6.3):
    with open(FIGS[n], "rb") as f:
        im = PILImage.open(io.BytesIO(f.read()))
    return min(im.size[0] / 300.0, max_in)   # 300dpi 自然尺寸；超宽才缩


# ---------- 真 docx：排版核对版（B，纯图片+图注） ----------
docB_real = Document()
docB_real.add_heading(title + " · 排版核对版", 0)
for n in sorted(captions):
    pic_p = docB_real.add_paragraph()
    pic_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    pic_p.paragraph_format.keep_with_next = True   # 图与图注绑定，防跨页错位
    pic_p.add_run().add_picture(FIGS[n], width=Inches(fig_width_in(n)))
    cap_p = docB_real.add_paragraph()
    cap_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = cap_p.add_run(f"图 {n}"); r.bold = True
    cap_p.add_run("：" + captions[n].split("：", 1)[1])
docB_real.add_heading("参考文献", level=2)
for p in paras["参考文献"]:
    docB_real.add_paragraph(p)
docB_real.save(os.path.join(OUT, "manuscript_排版核对版.docx"))

# ---------- 真 docx：完整版（BMC 式全稿：正文+图随文嵌+图注+声明+参考文献，一份装全） ----------
docC = Document()
docC.add_heading(title, 0)
for p in TITLE_PAGE[1:]:
    docC.add_paragraph(p)
add_abstract_doc(docC)
for sec in body_order:
    docC.add_heading(sec, level=2)
    for p in paras[sec]:
        docC.add_paragraph(p)
        for n, (s2, p2) in citing.items():
            if s2 == sec and p2 == p:
                pic_p = docC.add_paragraph()
                pic_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
                pic_p.paragraph_format.keep_with_next = True
                pic_p.add_run().add_picture(FIGS[n], width=Inches(fig_width_in(n)))
                cap_p = docC.add_paragraph()
                cap_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
                r = cap_p.add_run(f"图 {n}"); r.bold = True
                cap_p.add_run("：" + captions[n].split("：", 1)[1])
add_declarations_doc(docC)
add_refs_doc(docC)
docC.save(os.path.join(OUT, "manuscript_完整版.docx"))
print("完整版 docx 已生成")

# ---------- PDF：SCI 预印本排版引擎（内化自 09.SCI文章排版参考 的规范） ----------
import typeset_engine as TE

figtitles = {}
for p in paras["图题"]:
    m = re.match(r"^图\s*(\d+)\s*[：:]\s*(.*)$", p)
    if m:
        figtitles[int(m.group(1))] = m.group(2).strip()
abs_html = P1 + "<br/>" + "<br/>".join(f"<b>{k}：</b>{v}" for k, v in abs_blocks)
from reportlab.lib.units import inch as _inch
figs_payload = [{"id": f"图 {n}", "title": figtitles.get(n, ""),
                 "legend": captions[n].split("：", 1)[1],
                 "path": FIGS[n],
                 "width": min(fig_width_in(n), 5.0) * _inch}   # 自然尺寸，只缩不放大
                for n in sorted(captions)]
TE.compile_manuscript_pdf(
    os.path.join(OUT, "manuscript_gse31210.pdf"),
    {"title": title,
     "authors": "作者信息（投稿前补全） · 单位，城市，国家 · 通讯作者：姓名，邮箱",
     "running_header": f"PREPRINT MANUSCRIPT DRAFT  |  {title}",
     "abstract": abs_html, "keywords": KEYWORDS.split("：", 1)[1],
     "sections": [{"heading": f"{i}. {sec}",
                   "paragraphs": paras[sec],
                   **({"figures": [f for f in figs_payload]} if sec == "结果" else {})}
                  for i, sec in enumerate(body_order, 1)],
     "declarations": DECL_SUBS,
     "references": paras["参考文献"]})

print("导出完成 →", OUT)
for f in sorted(os.listdir(OUT)):
    print("  ", f, os.path.getsize(os.path.join(OUT, f)), "B")

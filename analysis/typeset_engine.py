#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""typeset_engine.py — SCI 预印本 PDF 排版引擎（内化自 09.SCI文章排版参考/01 的规范与模板）

规范来源：09.SCI文章排版参考/01/SCI预印本PDF排版规范与复用指南.md
  A4 / 54pt 四边距 / 双程页码（Page X of Y）/ 层级字色（#0f172a/#0072B2/#334155）/
  图注绑定 KeepTogether / 参考文献悬挂缩进 / 三线表斑马纹
本内化版增补：① 字体注册（多候选探测 + **真嵌入** + CJK 覆盖实测；**禁止**回落 base-14）；
  ② 页眉可配置；③ 声明（Declarations）节；④ 正文双端对齐；⑤ 构建后 PDF 自检。

字体纪律（run 34796985194 实证）：云端曾因 `fonts-noto-cjk` 装在编译之后 → 引擎静默回落
base-14 Helvetica → **中文正文被整段丢弃**（PDF 中文字符数 = 0）。现改为：候选逐个探测并
嵌入；无 CJK 覆盖而稿件含中文时**直接抛错**；构建后再自检"字体全嵌入 + 中文字符数达标"。
"""
import os, re
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import inch
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Image as RLImage,
                                Table, TableStyle, PageBreak, KeepTogether, HRFlowable)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont, TTFError
from PIL import Image

HEADER_TEXT = "PREPRINT MANUSCRIPT DRAFT"


def _mpl_ttf(name):
    """matplotlib 自带 TTF 路径（保证存在，作最后兜底；无 CJK 覆盖）。"""
    try:
        import matplotlib
        return os.path.join(matplotlib.get_data_path(), "fonts", "ttf", name)
    except Exception:
        return ""


# 候选字体（优先级从上到下）：CJK 覆盖优先，逐个探测**存在性**再注册；全部失败即抛错。
# 反面教训（run 34796985194）：原实现只探一个 Noto 路径，探不到就静默回落 base-14
# Helvetica —— base-14 既不嵌入、也无 CJK，导致中文正文被整段丢弃（PDF 中文字符数=0）。
_FONT_CANDIDATES = [
    ("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
     "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc", 0),
    ("/usr/share/fonts/opentype/noto/NotoSansCJKsc-Regular.otf",
     "/usr/share/fonts/opentype/noto/NotoSansCJKsc-Bold.otf", None),
    ("/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
     "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc", 0),
    ("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
     "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc", 0),
    ("/usr/share/fonts/truetype/arphic/uming.ttc",
     "/usr/share/fonts/truetype/arphic/uming.ttc", 0),
    # Windows（本机预检）
    ("C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/msyhbd.ttc", 0),
    ("C:/Windows/Fonts/simsun.ttc", "C:/Windows/Fonts/simhei.ttf", 0),
    # macOS
    ("/System/Library/Fonts/PingFang.ttc", "/System/Library/Fonts/PingFang.ttc", 0),
    # 兜底：DejaVu（嵌入 OK、无 CJK —— 含中文的稿件会在构建后被自检拦下）
    (_mpl_ttf("DejaVuSans.ttf"), _mpl_ttf("DejaVuSans-Bold.ttf"), None),
]


def _has_cjk(text):
    import re
    return bool(re.search(r"[\u4e00-\u9fff]", text or ""))


def _cjk_covered(path, index):
    """真实探测字体是否覆盖中文（渲染"中"字看掩膜是否非空），不靠文件名猜。"""
    try:
        from PIL import ImageFont
        f = ImageFont.truetype(path, 14, index=index or 0)
        mask = f.getmask("中")
        return bool(mask.getbbox())
    except Exception:
        return False


def register_fonts():
    """返回 (font, font_bold, cjk_ok)：逐个探测候选并**真嵌入**（TrueType/Type0）。

    契约：**禁止**回落 base-14（Helvetica）——它不嵌入且无 CJK，会静默丢中文；
    候选全部不可用时**抛错**，让云端 job 失败而不是产出残缺 PDF。
    """
    for reg, bold, ttc_index in _FONT_CANDIDATES:
        if not reg or not os.path.exists(reg):
            continue
        try:
            if ttc_index is not None:                   # .ttc 字体集合需指定子字体
                pdfmetrics.registerFont(TTFont("DOC", reg, subfontIndex=ttc_index))
                pdfmetrics.registerFont(TTFont("DOC-Bold", bold if os.path.exists(bold) else reg,
                                               subfontIndex=ttc_index))
            else:
                pdfmetrics.registerFont(TTFont("DOC", reg))
                pdfmetrics.registerFont(TTFont("DOC-Bold", bold if os.path.exists(bold) else reg))
            cjk_ok = _cjk_covered(reg, ttc_index)
            # 注册字体族：让 <b>/<i> 标记映射到**已嵌入**字体，
            # 否则 ReportLab 会把粗体回落到 base-14 Helvetica-Bold（不嵌入 → 期刊不合规）
            pdfmetrics.registerFontFamily("DOC", normal="DOC", bold="DOC-Bold",
                                          italic="DOC", boldItalic="DOC-Bold")
            # ReportLab 画布初始字体默认是 base-14 Helvetica → 全局覆盖，避免它出现在
            # 页面资源里（否则"字体全嵌入"这条期刊硬要求过不了）
            from reportlab import rl_config
            rl_config.canvas_basefontname = "DOC"
            print(f"[排版] 字体已嵌入：{os.path.basename(reg)}（CJK 覆盖={'是' if cjk_ok else '否'}）")
            return "DOC", "DOC-Bold", cjk_ok
        except (TTFError, OSError, ValueError) as ex:
            print(f"[排版] 字体注册失败（{reg}）：{ex}")
    raise RuntimeError(
        "未找到可嵌入的 TTF 字体：请安装 fonts-noto-cjk（Linux）/ 提供 CJK 字体路径；"
        "禁止回落 base-14（会丢中文且不嵌入）")


FONT, FONTB, FONT_CJK = register_fonts()


class NumberedCanvas(canvas.Canvas):
    """双程画布：动态总页数 Page X of Y；第 2 页起画页眉（规范 §二）。"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setFont(FONT, 10)          # 初始字体也用嵌入字体（默认是 base-14 Helvetica）
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_header_footer(num_pages)
            super().showPage()
        super().save()

    def draw_header_footer(self, page_count):
        self.saveState()
        self.setFont(FONT, 8)
        self.setFillColor(colors.HexColor("#64748b"))
        page_w, page_h = A4
        margin = 54
        if self._pageNumber > 1:
            self.drawString(margin, page_h - 36, HEADER_TEXT)
            self.setStrokeColor(colors.HexColor("#cbd5e1"))
            self.setLineWidth(0.5)
            self.line(margin, page_h - 42, page_w - margin, page_h - 42)
        self.drawRightString(page_w - margin, 36, f"Page {self._pageNumber} of {page_count}")
        self.drawString(margin, 36, "Confidential Manuscript Draft · Typeset with ReportLab Engine")
        self.setStrokeColor(colors.HexColor("#cbd5e1"))
        self.setLineWidth(0.5)
        self.line(margin, 46, page_w - margin, 46)
        self.restoreState()


def get_image_flowable(image_path, target_width=5.0 * inch):
    """等比缩放宽高（规范 §4.1：不拉伸变形）。"""
    if not os.path.exists(image_path):
        return Spacer(1, 10)
    im = Image.open(image_path)
    aspect = im.height / im.width
    return RLImage(image_path, width=target_width, height=target_width * aspect)


def setup_typography_styles():
    styles = getSampleStyleSheet()
    return {
        'DocTitle': ParagraphStyle('DocTitle', parent=styles['Normal'], fontName=FONTB,
                                   fontSize=15, leading=20, textColor=colors.HexColor('#0f172a'),
                                   alignment=1, spaceAfter=10),
        'DocAuthors': ParagraphStyle('DocAuthors', parent=styles['Normal'], fontName=FONT,
                                     fontSize=9, leading=13, textColor=colors.HexColor('#334155'),
                                     alignment=1, spaceAfter=12),
        'SectionH1': ParagraphStyle('SectionH1', parent=styles['Normal'], fontName=FONTB,
                                    fontSize=11.5, leading=15, textColor=colors.HexColor('#0f172a'),
                                    spaceBefore=14, spaceAfter=6, keepWithNext=True),
        'SectionH2': ParagraphStyle('SectionH2', parent=styles['Normal'], fontName=FONTB,
                                    fontSize=10, leading=13.5, textColor=colors.HexColor('#0072B2'),
                                    spaceBefore=10, spaceAfter=4, keepWithNext=True),
        'Body': ParagraphStyle('Body', parent=styles['Normal'], fontName=FONT,
                               fontSize=9, leading=13.5, textColor=colors.HexColor('#1e293b'),
                               alignment=4, spaceAfter=6),
        'Abstract': ParagraphStyle('Abstract', parent=styles['Normal'], fontName=FONT,
                                   fontSize=8.5, leading=12.5, textColor=colors.HexColor('#334155'),
                                   alignment=4, spaceAfter=8),
        'FigureLegend': ParagraphStyle('FigureLegend', parent=styles['Normal'], fontName=FONT,
                                       fontSize=7.8, leading=11, textColor=colors.HexColor('#475569'),
                                       spaceBefore=3, spaceAfter=10),
        'Reference': ParagraphStyle('Reference', parent=styles['Normal'], fontName=FONT,
                                    fontSize=7.5, leading=10.5, textColor=colors.HexColor('#334155'),
                                    leftIndent=14, firstLineIndent=-14, spaceAfter=3),
    }


def verify_pdf(path, expect_cjk=True, min_cjk=50):
    """构建后自检（防"字体回落 → 中文被丢"复发）：

    ① 字体须全为**嵌入型**（TrueType/Type0/CIDFontType*）——多数期刊硬性要求；
    ② 若期望中文，正文中文字符数须达标（回落 base-14 时会掉到 0）。
    任一不满足即抛错，让 job 失败，不产出"看起来成功"的残缺 PDF。
    """
    try:
        import pypdf
    except ImportError:
        print("[排版] 自检跳过：pypdf 未安装")
        return
    rd = pypdf.PdfReader(path)
    txt = "".join((p.extract_text() or "") for p in rd.pages)
    n_cjk = len(re.findall(r"[\u4e00-\u9fff]", txt))
    subs = {(str(f.get_object().get("/Subtype")), str(f.get_object().get("/BaseFont")))
            for p in rd.pages for f in (p.get("/Resources", {}).get("/Font") or {}).values()}
    bad = [s for s in subs if s[0] not in ("/TrueType", "/Type0", "/CIDFontType2", "/CIDFontType0")]
    print(f"[排版] 自检：{len(rd.pages)} 页 | 中文字符 {n_cjk} | 字体 {sorted(subs)}")
    if bad:
        raise RuntimeError(f"PDF 含未嵌入字体（期刊多要求嵌入）：{bad}")
    if expect_cjk and n_cjk < min_cjk:
        raise RuntimeError(f"PDF 中文正文缺失（仅 {n_cjk} 个中文字符）→ 字体回落所致")


def compile_manuscript_pdf(output_pdf_path, manuscript_data):
    """编译学术 PDF（规范 §四；增补声明节与可配置页眉）。"""
    global HEADER_TEXT
    HEADER_TEXT = manuscript_data.get("running_header", HEADER_TEXT)
    doc = SimpleDocTemplate(output_pdf_path, pagesize=A4, leftMargin=54, rightMargin=54,
                            topMargin=54, bottomMargin=54,
                            title=manuscript_data.get("title", ""),
                            author=manuscript_data.get("authors", ""))
    st = setup_typography_styles()
    story = [Paragraph(manuscript_data['title'], st['DocTitle']),
             Paragraph(manuscript_data['authors'], st['DocAuthors']),
             HRFlowable(width="100%", thickness=1, color=colors.HexColor('#cbd5e1'),
                        spaceBefore=2, spaceAfter=10),
             Paragraph("<b>摘要 Abstract</b>", st['SectionH2']),
             Paragraph(manuscript_data['abstract'], st['Abstract']),
             Paragraph(f"<b>关键词 Keywords：</b> {manuscript_data['keywords']}", st['Abstract']),
             HRFlowable(width="100%", thickness=0.8, color=colors.HexColor('#cbd5e1'),
                        spaceBefore=6, spaceAfter=10)]
    for sec in manuscript_data['sections']:
        story.append(Paragraph(sec['heading'], st['SectionH1']))
        for para in sec.get('paragraphs', []):
            story.append(Paragraph(para, st['Body']))
        if 'table' in sec:
            t_def = sec['table']
            t_flowable = Table(t_def['data'], colWidths=t_def.get('col_widths'))
            t_flowable.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#f1f5f9')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.HexColor('#0f172a')),
                ('FONTNAME', (0, 0), (-1, 0), FONTB),
                ('FONTNAME', (0, 1), (-1, -1), FONT),
                ('FONTSIZE', (0, 0), (-1, -1), 7),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
                ('TOPPADDING', (0, 0), (-1, -1), 3),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#cbd5e1')),
                ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f8fafc')])]))
            story.append(KeepTogether([Spacer(1, 4),
                                       Paragraph(f"<b>{t_def['caption']}</b>", st['SectionH2']),
                                       t_flowable, Spacer(1, 8)]))
        for fig in sec.get('figures', []):
            story.append(KeepTogether([Spacer(1, 4),
                                       get_image_flowable(fig['path'], fig.get('width', 5.0 * inch)),
                                       Paragraph(f"<b>{fig['id']}. {fig['title']}.</b> {fig['legend']}",
                                                 st['FigureLegend'])]))
        if sec.get('page_break_after'):
            story.append(PageBreak())
    story.append(Paragraph("声明 Declarations", st['SectionH1']))
    for k, v in manuscript_data.get('declarations', []):
        story.append(Paragraph(f"<b>{k}</b>", st['SectionH2']))
        story.append(Paragraph(v, st['Body']))
    story.append(Paragraph("参考文献 References", st['SectionH1']))
    for ref in manuscript_data.get('references', []):
        story.append(Paragraph(ref, st['Reference']))
    # 前置守卫：稿件含中文但注册字体无 CJK 覆盖 → 立即失败（不产出"中文被丢"的残缺 PDF）
    _need_cjk = _has_cjk(str(manuscript_data))
    if _need_cjk and not FONT_CJK:
        raise RuntimeError("稿件含中文，但当前注册字体无 CJK 覆盖：请安装 fonts-noto-cjk 后重跑")
    doc.build(story, canvasmaker=NumberedCanvas)
    print(f"成功编译 PDF：{output_pdf_path}")
    verify_pdf(output_pdf_path, expect_cjk=_need_cjk)

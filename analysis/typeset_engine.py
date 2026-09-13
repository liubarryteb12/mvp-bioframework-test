#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""typeset_engine.py — SCI 预印本 PDF 排版引擎（内化自 09.SCI文章排版参考/01 的规范与模板）

规范来源：09.SCI文章排版参考/01/SCI预印本PDF排版规范与复用指南.md
  A4 / 54pt 四边距 / 双程页码（Page X of Y）/ 层级字色（#0f172a/#0072B2/#334155）/
  图注绑定 KeepTogether / 参考文献悬挂缩进 / 三线表斑马纹
本内化版增补：① NotoSansCJK 字体注册（中文排印 + 真嵌入）；② 页眉可配置；
  ③ 声明（Declarations）节；④ 正文双端对齐。
"""
import os
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import inch
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Image as RLImage,
                                Table, TableStyle, PageBreak, KeepTogether, HRFlowable)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from PIL import Image

HEADER_TEXT = "PREPRINT MANUSCRIPT DRAFT"


def register_fonts():
    """返回 (font, font_bold)。优先 NotoSansCJK（云 runner 已装 fonts-noto-cjk），回落 Helvetica。"""
    reg = "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"
    bold = "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"
    if os.path.exists(reg):
        try:
            pdfmetrics.registerFont(TTFont("CJK", reg, subfontIndex=0))
            pdfmetrics.registerFont(TTFont("CJK-Bold", bold if os.path.exists(bold) else reg,
                                           subfontIndex=0 if os.path.exists(bold) else 2))
            return "CJK", "CJK-Bold"
        except Exception as ex:
            print("CJK 注册失败，回落 Helvetica：", ex)
    return "Helvetica", "Helvetica-Bold"


FONT, FONTB = register_fonts()


class NumberedCanvas(canvas.Canvas):
    """双程画布：动态总页数 Page X of Y；第 2 页起画页眉（规范 §二）。"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
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
    doc.build(story, canvasmaker=NumberedCanvas)
    print(f"成功编译 PDF：{output_pdf_path}")

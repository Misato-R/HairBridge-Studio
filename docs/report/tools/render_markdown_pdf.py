"""Render the delivery Markdown directly to PDF using ReportLab.

Usage: python render_markdown_pdf.py [report.md] [report.pdf]
Requires reportlab, pillow, and installed Calibri/Microsoft YaHei fonts.
The Markdown is the text source; Word is neither read nor launched.
"""
from pathlib import Path
from html import escape
import re
import sys

from PIL import Image as PILImage
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    BaseDocTemplate, Frame, PageTemplate, Paragraph, Spacer, Image,
    Table, TableStyle, KeepTogether, PageBreak,
)

ROOT = Path(__file__).resolve().parents[1]
default_source = ROOT / 'HairBridge_Studio_A2_Report.md'
if not default_source.is_file():
    default_source = ROOT / 'final/HairBridge_Studio_A2_Report.md'
SOURCE = Path(sys.argv[1]) if len(sys.argv) > 1 else default_source
OUTPUT = Path(sys.argv[2]) if len(sys.argv) > 2 else SOURCE.with_suffix('.pdf')
for name, filename in [('Calibri', 'calibri.ttf'), ('Calibri-Bold', 'calibrib.ttf'), ('Calibri-Italic', 'calibrii.ttf'), ('Calibri-BoldItalic', 'calibriz.ttf')]:
    pdfmetrics.registerFont(TTFont(name, str(Path('C:/Windows/Fonts') / filename)))
pdfmetrics.registerFontFamily('Calibri', normal='Calibri', bold='Calibri-Bold', italic='Calibri-Italic', boldItalic='Calibri-BoldItalic')
pdfmetrics.registerFont(TTFont('CJK', 'C:/Windows/Fonts/msyh.ttc', subfontIndex=0))

STYLES = {
    'body': ParagraphStyle('body', fontName='Calibri', fontSize=10.5, leading=12.1, spaceAfter=6, allowWidows=0, allowOrphans=0),
    'title': ParagraphStyle('title', fontName='Calibri-Bold', fontSize=24, leading=28, spaceAfter=4, keepWithNext=True),
    'h1': ParagraphStyle('h1', fontName='Calibri-Bold', fontSize=13, leading=15, spaceBefore=8, spaceAfter=4, keepWithNext=True),
    'h2': ParagraphStyle('h2', fontName='Calibri-Bold', fontSize=10.7, leading=13, spaceBefore=7, spaceAfter=4, keepWithNext=True),
    'caption': ParagraphStyle('caption', fontName='Calibri', fontSize=8.7, leading=10, spaceAfter=7),
    'meta': ParagraphStyle('meta', fontName='Calibri', fontSize=8.5, leading=10, spaceAfter=4),
    'ref': ParagraphStyle('ref', fontName='Calibri', fontSize=9.2, leading=11.1, spaceAfter=8, leftIndent=14, firstLineIndent=-14),
    'cell': ParagraphStyle('cell', fontName='Calibri', fontSize=9.2, leading=10.5),
    'linklist': ParagraphStyle('linklist', fontName='Calibri', fontSize=9, leading=10.7, spaceAfter=3, leftIndent=8, firstLineIndent=-8),
}

def inline(text):
    pattern = r'\[([^\]]+)\]\(([^)]+)\)|\*\*([^*]+)\*\*|\*([^*]+)\*|`([^`]+)`'
    result, at = [], 0
    for m in re.finditer(pattern, text):
        result.append(escape(text[at:m.start()]))
        if m.group(1):
            label, url = escape(m.group(1)), m.group(2)
            if re.match(r'https?://', url):
                result.append('<a href="' + escape(url, quote=True) + '" color="#315579">' + label + '</a>')
            else:
                result.append(label + ' (in source bundle)')
        elif m.group(3):
            result.append('<b>' + escape(m.group(3)) + '</b>')
        elif m.group(4):
            result.append('<i>' + escape(m.group(4)) + '</i>')
        else:
            result.append(escape(m.group(5)))
        at = m.end()
    result.append(escape(text[at:]))
    result = ''.join(result)
    return re.sub(r'[\u3400-\u9fff]+', lambda m: '<font name="CJK">' + m.group(0) + '</font>', result)

WIDTH = 174 * mm

def picture(filename):
    path = (SOURCE.parent / filename).resolve()
    assert path.is_file(), path
    with PILImage.open(path) as img:
        w, h = img.size
    # Measured reconstruction has a table and the remaining rationale below it.
    width = (166 if 'figure1_' in filename else 174) * mm
    return Image(str(path), width=width, height=width * h / w, hAlign='CENTER')

def footer(canvas, doc):
    canvas.saveState()
    canvas.setFont('Calibri', 8)
    canvas.setFillColor(colors.HexColor('#52565c'))
    canvas.drawCentredString(A4[0] / 2, 8 * mm, str(doc.page))
    canvas.restoreState()

doc = BaseDocTemplate(str(OUTPUT), pagesize=A4, leftMargin=18*mm, rightMargin=18*mm, topMargin=18*mm, bottomMargin=18*mm,
                      title='HairBridge Studio A2 Project Report', author='LU WENXUAN')
frame = Frame(18*mm, 18*mm, WIDTH, 261*mm, leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
doc.addPageTemplates(PageTemplate(id='report', frames=frame, onPage=footer))
text = SOURCE.read_text(encoding='utf-8')
chunks = [p.strip() for p in re.split(r'\n\s*\n', text.strip()) if p.strip()]
story = []
in_refs = False
index = 0
while index < len(chunks):
    chunk = chunks[index]
    if chunk == '<div class="page-break"></div>':
        story.append(PageBreak())
    elif chunk.startswith('### '):
        # Keep each figure heading, image, and short caption together.
        title = Paragraph(inline(chunk[4:]), STYLES['h2'])
        assert chunks[index+1].startswith('!['), chunk
        img = re.fullmatch(r'!\[.*?\]\((.+)\)', chunks[index+1]).group(1)
        group = [title, picture(img), Spacer(1, 3)]
        index += 1
        if index+1 < len(chunks) and not re.match(r'[#<|!]', chunks[index+1]):
            index += 1
            group.append(Paragraph(inline(chunks[index]), STYLES['caption']))
        story.append(KeepTogether(group))
    elif chunk.startswith('## '):
        in_refs = chunk[3:] == 'References and tool credits'
        story.append(Paragraph(inline(chunk[3:]), STYLES['h1']))
    elif chunk.startswith('# '):
        story.append(Paragraph(inline(chunk[2:]), STYLES['title']))
    elif chunk.startswith('|'):
        rows = [[v.strip() for v in line.strip().strip('|').split('|')] for line in chunk.splitlines()]
        rows = [row for row in rows if not all(re.fullmatch(r'[-: ]+', value) for value in row)]
        rows = [[Paragraph(inline(('**' + val + '**') if n == 0 else val), STYLES['cell']) for val in row] for n, row in enumerate(rows)]
        table = Table(rows, colWidths=[137*mm, 37*mm], hAlign='CENTER')
        table.setStyle(TableStyle([
            ('GRID', (0,0), (-1,-1), 0.4, colors.HexColor('#d9d9d9')),
            ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#e7ecf2')),
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
            ('TOPPADDING',(0,0),(-1,-1),4), ('BOTTOMPADDING',(0,0),(-1,-1),4),
        ]))
        story.extend([table, Spacer(1,4)])
    elif chunk.startswith('- '):
        for line in chunk.splitlines():
            story.append(Paragraph(inline(line.removeprefix('- ')), STYLES['linklist']))
    elif chunk.startswith('**Word count:**'):
        story.append(Paragraph(inline(chunk), STYLES['meta']))
    elif in_refs:
        story.append(KeepTogether([Paragraph(inline(chunk), STYLES['ref'])]))
    else:
        style = 'caption' if story and isinstance(story[-1], Spacer) else 'body'
        story.append(Paragraph(inline(chunk.replace('\n', ' ')), STYLES[style]))
    index += 1
doc.build(story)
print(OUTPUT)

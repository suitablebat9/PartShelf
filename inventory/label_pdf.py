"""Physical-size label PDFs. Preview and batch export use exactly this renderer."""
import io
import re
import threading
import pypdfium2 as pdfium
from decimal import Decimal, InvalidOperation

import qrcode
from reportlab.pdfgen.canvas import Canvas
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.lib.utils import ImageReader
from reportlab.graphics.barcode.code128 import Code128

FONTS = {'sans-serif': 'Helvetica', 'serif': 'Times-Roman', 'monospace': 'Courier'}
FIELDS = ('name', 'name_id', 'code', 'stock', 'unit', 'size', 'resistance', 'capacitance', 'voltage', 'tolerance', 'supplier', 'category', 'location', 'tags')


def settings(values):
    def numeric(key, default, low, high):
        try:
            n = Decimal(str(values.get(key, default)))
            if not n.is_finite() or not low <= n <= high:
                raise ValueError()
            return float(n)
        except (ValueError, InvalidOperation):
            raise ValueError(f'{key.title()} must be between {low} and {high}.')
    mode, font = values.get('mode', 'qr'), values.get('font', 'sans-serif')
    if mode not in ('qr', 'barcode', 'none') or font not in FONTS:
        raise ValueError('Invalid label code or font option.')
    copies = numeric('copies', '1', 1, 100)
    if not copies.is_integer():
        raise ValueError('Copies must be a whole number.')
    text = values.get('text', '{name}\n{name_id}').replace('\r\n', '\n').replace('\r', '\n')
    if len(text) > 1000:
        raise ValueError('Label text must be 1,000 characters or fewer.')
    options = dict(width=numeric('width', '3.5', .5, 12), height=numeric('height', '1.5', .5, 12), size=numeric('size', '14', 6, 72), mode=mode, font=font, copies=int(copies), text=text)
    for side in ('top', 'bottom', 'left', 'right'):
        options['margin_' + side] = numeric('margin_' + side, '0.08', 0, 12)
    if options['width'] - options['margin_left'] - options['margin_right'] < .2 or options['height'] - options['margin_top'] - options['margin_bottom'] < .2:
        raise ValueError('Margins must leave at least 0.2 inches of usable width and height.')
    return options


def label_text(item, template):
    return re.sub(r'\{(' + '|'.join(FIELDS) + r')\}', lambda match: str(item.get(match.group(1)) or ''), template)


def wrap(text, font, size, width):
    lines = []
    for paragraph in text.split('\n'):
        line = ''
        for char in paragraph:
            if line and stringWidth(line + char, font, size) > width:
                # Prefer a word boundary; split long identifiers when necessary.
                split = line.rfind(' ')
                if split > 0:
                    lines.append(line[:split])
                    line = line[split + 1:] + char
                else:
                    lines.append(line)
                    line = char
            else:
                line += char
        lines.append(line)
    return lines


def render_pdf(items, options):
    if not items:
        raise ValueError('Select at least one component.')
    if len(items) * options['copies'] > 1000:
        raise ValueError('Export up to 1,000 labels at a time; reduce copies or select fewer components.')
    width, height = options['width']*72, options['height']*72
    out = io.BytesIO()
    canvas = Canvas(out, pagesize=(width, height), pageCompression=1)
    canvas.setTitle('Partshelf labels')
    left, right, top, bottom = (options['margin_' + side]*72 for side in ('left', 'right', 'top', 'bottom'))
    area_w, area_h = width-left-right, height-top-bottom
    gap = min(6, area_w*.06, area_h*.06)
    font = FONTS[options['font']]
    for item in items:
        text = label_text(item, options['text'])
        # Keep unsupported glyphs visible as an actionable error, never missing boxes.
        for char in text:
            if not (ord(char) < 256 or char in 'Ωωµμ±×÷−–—°ΔαβγπΣ∞≤≥'):
                raise ValueError(f"The PDF fonts do not support {char!r} in {item['name']}. Edit the label text to use Latin or common electrical symbols.")
        for _ in range(options['copies']):
            tx, ty, tw, th = left, bottom, area_w, area_h
            if options['mode'] == 'qr':
                size = min(area_h, area_w * (.42 if text else 1))
                image = qrcode.make(item['code'], border=0 if not any((left, right, top, bottom)) else 4).convert('RGB')
                x = left if text else left+(area_w-size)/2
                canvas.drawImage(ImageReader(image), x, bottom+(area_h-size)/2, size, size)
                if text:
                    tx = left+size+gap
                    tw = width-right-tx
            elif options['mode'] == 'barcode':
                if not item['code'] or any(ord(c) < 32 or ord(c) > 126 for c in item['code']):
                    raise ValueError(f"{item['name']}: Code 128 needs printable ASCII. Choose QR or change its identifier.")
                code_h = area_h * (.52 if text else 1)
                code = Code128(item['code'], barWidth=.7, barHeight=code_h, humanReadable=False, quiet=bool(left or right))
                scale = area_w/code.width
                if .7*scale < .35:
                    raise ValueError(f"{item['name']}: this barcode is too dense for the label. Increase label width or use QR.")
                canvas.saveState()
                canvas.translate(left+(area_w-code.width*scale)/2, height-top-code_h)
                canvas.scale(scale, 1)
                code.drawOn(canvas, 0, 0)
                canvas.restoreState()
                if text:
                    th = area_h-code_h-gap
            if text:
                size = options['size']
                while size >= 4:
                    lines = wrap(text, font, size, tw)
                    if len(lines)*size*1.2 <= th and all(stringWidth(line, font, size) <= tw for line in lines):
                        break
                    size -= .5
                if size < 4:
                    raise ValueError(f"{item['name']}: text cannot fit legibly. Shorten the text or increase label size.")
                canvas.setFont(font, size)
                y = ty + (th+len(lines)*size*1.2)/2-size
                for line in lines:
                    canvas.drawCentredString(tx+tw/2, y, line)
                    y -= size*1.2
            canvas.showPage()
    canvas.save()
    out.seek(0)
    return out


_preview_lock = threading.Lock()


def preview_png(pdf):
    """Rasterize the actual PDF so preview works without a browser PDF plugin."""
    with _preview_lock, pdfium.PdfDocument(pdf.getvalue()) as document:
        page = document[0]
        try:
            bitmap = page.render(scale=min(3, 1200 / max(page.get_size())))
            try:
                output = io.BytesIO()
                bitmap.to_pil().save(output, format='PNG')
                return output.getvalue()
            finally:
                bitmap.close()
        finally:
            page.close()

"""
Markdown → PDF (DiagVoice belge stili).

  # Sade (eski raporlar):
  python scripts/md_to_pdf.py docs/TOGG_API.md out.pdf --header "DiagVoice — TOGG Analiz API'si"

  # Kurumsal: kapak sayfası, içindekiler, logolu üst bilgi, DiagVoice renkleri
  python scripts/md_to_pdf.py docs/TOGG_API.md docs/DiagVoice_TOGG_API_v1.5.pdf --brand \
      --header "TOGG Entegrasyon Kılavuzu" --version 1.5 --date "25 Kasım 2026" \
      --audience "TOGG" --logo app/public/logo.jpg

Desteklenen: # / ## / ### başlıklar, paragraflar, "- " listeler, | tablolar |, ``` kod blokları ```,
> alıntı, satır içi `kod` ve **kalın**.
"""
from __future__ import annotations

import argparse
import html
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "loadtest" / "report"))

import build_report as br  # noqa: E402
from reportlab.lib import colors  # noqa: E402
from reportlab.lib.pagesizes import A4  # noqa: E402
from reportlab.lib.styles import ParagraphStyle  # noqa: E402
from reportlab.lib.units import cm  # noqa: E402
from reportlab.pdfbase import pdfmetrics  # noqa: E402
from reportlab.pdfbase.ttfonts import TTFont  # noqa: E402
from reportlab.platypus import (  # noqa: E402
    BaseDocTemplate,
    CondPageBreak,
    Frame,
    KeepTogether,
    NextPageTemplate,
    PageBreak,
    PageTemplate,
    Paragraph,
    Preformatted,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)
from reportlab.platypus.tableofcontents import TableOfContents  # noqa: E402

CODE_BG = colors.HexColor("#F4F6F9")
QUOTE_BG = colors.HexColor("#FFF7E6")

# DiagVoice marka renkleri (logodaki mor)
BRAND = colors.HexColor("#8A2B8C")
BRAND_DARK = colors.HexColor("#4A1350")
BRAND_LIGHT = colors.HexColor("#F6EEF7")
BRAND_RULE = colors.HexColor("#E3CFE5")
INK = colors.HexColor("#1F1A24")
MUTED = colors.HexColor("#6B6472")

W, H = A4
CONTENT_W = 16.4 * cm


def inline(t: str) -> str:
    t = html.escape(t, quote=False)
    t = re.sub(r"`([^`]+)`", r'<font face="Mono" color="#5A1D5E">\1</font>', t)
    t = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", t)
    return t


class _H1(Paragraph):
    """İçindekilere girecek bölüm başlığı."""


def parse(src: Path, S: dict, *, head_color, rule, light, skip_first_h1: bool) -> list:
    code_style = ParagraphStyle("code", fontName="Mono", fontSize=8.2, leading=10.4, textColor=colors.HexColor("#1D2733"))
    cell = ParagraphStyle("cellm", parent=S["cell"], fontSize=8.8, leading=11.2)
    lines = src.read_text(encoding="utf-8").splitlines()
    story: list = []
    i = 0
    pending: list = []  # başlık / giriş cümlesi: bir sonraki blokla aynı sayfada tutulur (iç içe KeepTogether yok)
    first_h1 = True
    seen_sub = False

    def add(flow):
        if pending:
            story.append(KeepTogether([*pending, flow]))
            pending.clear()
        else:
            story.append(flow)

    def flush():
        story.extend(pending)
        pending.clear()

    while i < len(lines):
        ln = lines[i]
        if ln.startswith("```"):
            buf = []
            i += 1
            while i < len(lines) and not lines[i].startswith("```"):
                buf.append(lines[i])
                i += 1
            t = Table([[Preformatted("\n".join(buf), code_style)]], colWidths=[CONTENT_W])
            t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), CODE_BG), ("BOX", (0, 0), (-1, -1), 0.4, rule),
                                   ("LEFTPADDING", (0, 0), (-1, -1), 8), ("TOPPADDING", (0, 0), (-1, -1), 6),
                                   ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))
            add(t)
            story.append(Spacer(1, 6))
            i += 1
            continue
        if ln.startswith("|"):
            rows = []
            while i < len(lines) and lines[i].startswith("|"):
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                if not all(re.fullmatch(r":?-{2,}:?", c) for c in cells):
                    rows.append(cells)
                i += 1
            ncol = len(rows[0])
            hdr = [Paragraph(inline(c), S["cellb"]) for c in rows[0]]
            body = [[Paragraph(inline(c), cell) for c in r] for r in rows[1:]]
            lens = [max(len(r[k]) if k < len(r) else 0 for r in rows) for k in range(ncol)]
            lens = [min(max(L, 6), 60) for L in lens]
            # Sütun, içindeki en uzun bölünemez parça (ör. `analyze:togg`) sığacak kadar geniş olsun
            longest = [max((len(w) for r in rows if k < len(r) for w in re.sub(r"[`*]", "", r[k]).split()), default=0)
                       for k in range(ncol)]
            lens = [max(L, int(w * 1.6) + 2) for L, w in zip(lens, longest)]
            tot = sum(lens)
            t = Table([hdr] + body, colWidths=[CONTENT_W * L / tot for L in lens], repeatRows=1, hAlign="LEFT")
            ts = [("BACKGROUND", (0, 0), (-1, 0), head_color), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                  ("LINEBELOW", (0, 0), (-1, -1), 0.4, rule), ("TOPPADDING", (0, 0), (-1, -1), 4),
                  ("BOTTOMPADDING", (0, 0), (-1, -1), 4), ("LEFTPADDING", (0, 0), (-1, -1), 5)]
            for r in range(2, len(rows), 2):
                ts.append(("BACKGROUND", (0, r), (-1, r), light))
            t.setStyle(TableStyle(ts))
            add(t)
            story.append(Spacer(1, 6))
            continue
        if ln.startswith("# "):
            if first_h1:
                first_h1 = False
                if not skip_first_h1:
                    story += [Spacer(1, 0.6 * cm), Paragraph(inline(ln[2:]), S["title"])]
            else:
                flush()
                pending.append(_H1(inline(ln[2:]), S["h1"]))
            i += 1
            continue
        if ln.startswith("## "):
            flush()
            story.append(CondPageBreak(6 * cm))
            pending.append(_H1(inline(ln[3:]), S["h1"]))
            i += 1
            continue
        if ln.startswith("### "):
            pending.append(Paragraph(inline(ln[4:]), S["h2"]))
            i += 1
            continue
        if ln.startswith("- "):
            items = []
            while i < len(lines) and lines[i].startswith("- "):
                items.append(Paragraph(inline(lines[i][2:]), S["bullet"], bulletText="•"))
                i += 1
            for k, it in enumerate(items):
                add(it) if k == 0 else story.append(it)
            story.append(Spacer(1, 3))
            continue
        if ln.startswith("> "):
            t = Table([[Paragraph(inline(ln[2:]), S["body"])]], colWidths=[CONTENT_W])
            t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), QUOTE_BG),
                                   ("LINEBEFORE", (0, 0), (0, -1), 2.5, colors.HexColor("#C58B1A")),
                                   ("LEFTPADDING", (0, 0), (-1, -1), 9), ("TOPPADDING", (0, 0), (-1, -1), 6),
                                   ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
            add(t)
            story.append(Spacer(1, 6))
            i += 1
            continue
        if not ln.strip():
            i += 1
            continue
        buf = [ln]
        i += 1
        while i < len(lines) and lines[i].strip() and not re.match(r"^(#|- |\||```|> )", lines[i]):
            buf.append(lines[i])
            i += 1
        text = " ".join(buf)
        if skip_first_h1 and not seen_sub and not story:
            seen_sub = True  # "Sürüm x · tarih" satırı kapakta gösterilir
            continue
        para = Paragraph(inline(text), S["subtitle"] if len(story) <= 2 and not skip_first_h1 else S["body"])
        if text.rstrip().endswith(":") or (pending and len(text) < 160):
            # "Örnek:" gibi giriş cümleleri ve başlığın hemen altındaki kısa cümle sonraki blokla aynı sayfada kalsın
            pending.append(para)
        else:
            add(para)
    flush()
    return story


def _fonts():
    br.register_fonts()
    br.styles()
    pdfmetrics.registerFont(TTFont("Mono", "C:/Windows/Fonts/consola.ttf"))
    return br.STY


# --------------------------------------------------------------------------------------------- sade
def build_plain(src: Path, out: Path, header: str, date: str):
    S = _fonts()
    story = parse(src, S, head_color=br.NAVY, rule=br.RULE, light=br.LIGHT, skip_first_h1=False)

    def on_page(canvas, doc):
        canvas.saveState()
        canvas.setStrokeColor(br.RULE)
        canvas.setLineWidth(0.5)
        canvas.line(2 * cm, H - 1.5 * cm, W - 2 * cm, H - 1.5 * cm)
        canvas.setFont("Body", 8.5)
        canvas.setFillColor(br.GREY)
        canvas.drawString(2 * cm, H - 1.3 * cm, header)
        canvas.line(2 * cm, 1.5 * cm, W - 2 * cm, 1.5 * cm)
        canvas.drawString(2 * cm, 1.05 * cm, date)
        canvas.drawRightString(W - 2 * cm, 1.05 * cm, f"Sayfa {doc.page}")
        canvas.restoreState()

    doc = SimpleDocTemplate(str(out), pagesize=A4, leftMargin=2 * cm, rightMargin=2 * cm, topMargin=2.1 * cm,
                            bottomMargin=2 * cm, title=header, author="DiagVoice")
    doc.build(story, onFirstPage=on_page, onLaterPages=on_page)
    print(f"yazıldı: {out}")


# --------------------------------------------------------------------------------------------- kurumsal
class BrandDoc(BaseDocTemplate):
    def afterFlowable(self, flowable):
        if isinstance(flowable, _H1):
            text = flowable.getPlainText()
            key = f"h{self.seq.nextf('heading')}"
            self.canv.bookmarkPage(key)
            self.canv.addOutlineEntry(text, key, level=0)
            self.notify("TOCEntry", (0, text, self.page, key))


def build_brand(src: Path, out: Path, *, title: str, header: str, version: str, date: str, audience: str, logo: Path):
    S = _fonts()
    for k in ("title", "h1", "h2"):
        S[k].textColor = BRAND_DARK
    S["h1"].fontSize, S["h1"].leading = 16, 20
    S["body"].textColor = INK
    S["bullet"].textColor = INK

    first = src.read_text(encoding="utf-8").splitlines()[0]
    doc_title = title or first.lstrip("# ").strip()

    story: list = [NextPageTemplate("toc"), PageBreak()]
    toc = TableOfContents()
    toc.levelStyles = [ParagraphStyle("toc0", fontName="Body", fontSize=11.5, leading=20, textColor=INK,
                                      leftIndent=0, rightIndent=1 * cm)]
    toc.dotsMinLevel = 0
    story += [Paragraph("İçindekiler", S["h1"]), Spacer(1, 6), toc, NextPageTemplate("body"), PageBreak()]
    story += parse(src, S, head_color=BRAND_DARK, rule=BRAND_RULE, light=BRAND_LIGHT, skip_first_h1=True)

    def cover(canvas, doc):
        canvas.saveState()
        # üst mor blok
        canvas.setFillColor(BRAND_DARK)
        canvas.rect(0, H - 11 * cm, W, 11 * cm, stroke=0, fill=1)
        canvas.setFillColor(BRAND)
        canvas.rect(0, H - 11.35 * cm, W, 0.35 * cm, stroke=0, fill=1)
        # ses dalgası süsü
        canvas.setStrokeColor(colors.Color(1, 1, 1, alpha=0.12))
        canvas.setLineWidth(3)
        import math
        for k in range(46):
            x = W - 9.5 * cm + k * 0.2 * cm
            amp = (0.4 + 0.6 * abs(math.sin(k * 0.55)) * abs(math.cos(k * 0.17))) * 2.6 * cm
            canvas.line(x, H - 5.6 * cm - amp / 2, x, H - 5.6 * cm + amp / 2)
        # logo kartı
        canvas.setFillColor(colors.white)
        canvas.roundRect(2 * cm, H - 4.6 * cm, 2.6 * cm, 2.6 * cm, 0.3 * cm, stroke=0, fill=1)
        canvas.drawImage(str(logo), 2.25 * cm, H - 4.35 * cm, 2.1 * cm, 2.1 * cm, preserveAspectRatio=True, mask="auto")
        canvas.setFillColor(colors.white)
        canvas.setFont("Body-Bold", 15)
        canvas.drawString(5.1 * cm, H - 3.05 * cm, "DiagVoice")
        canvas.setFont("Body", 10)
        canvas.setFillColor(colors.Color(1, 1, 1, alpha=0.75))
        canvas.drawString(5.1 * cm, H - 3.6 * cm, "Ses tabanlı duygu ve sağlık analizi")
        # başlık
        canvas.setFillColor(colors.white)
        canvas.setFont("Body-Bold", 30)
        canvas.drawString(2 * cm, H - 7.4 * cm, header)
        canvas.setFont("Body", 14)
        canvas.setFillColor(colors.Color(1, 1, 1, alpha=0.85))
        canvas.drawString(2 * cm, H - 8.4 * cm, doc_title)
        # meta kutusu
        y = H - 14.2 * cm
        meta = [("Sürüm", version), ("Tarih", date), ("Hazırlayan", "DiagVoice Mühendislik Ekibi"),
                ("Hazırlanan", audience), ("API adresi", "https://aiapi.diagvoice.com")]
        canvas.setFillColor(BRAND_LIGHT)
        canvas.roundRect(2 * cm, y - len(meta) * 0.85 * cm - 0.3 * cm, CONTENT_W, len(meta) * 0.85 * cm + 0.9 * cm,
                         0.25 * cm, stroke=0, fill=1)
        canvas.setFillColor(BRAND)
        canvas.rect(2 * cm, y - len(meta) * 0.85 * cm - 0.3 * cm, 0.18 * cm, len(meta) * 0.85 * cm + 0.9 * cm, stroke=0, fill=1)
        for k, (a, b) in enumerate(meta):
            yy = y - k * 0.85 * cm
            canvas.setFont("Body", 10)
            canvas.setFillColor(MUTED)
            canvas.drawString(2.8 * cm, yy, a)
            canvas.setFont("Body-Bold", 11)
            canvas.setFillColor(INK)
            canvas.drawString(6.5 * cm, yy, b)
        # gizlilik notu
        canvas.setFont("Body-Bold", 9.5)
        canvas.setFillColor(BRAND_DARK)
        canvas.drawString(2 * cm, 3.4 * cm, "GİZLİ — MÜŞTERİYE ÖZEL")
        canvas.setFont("Body", 9)
        canvas.setFillColor(MUTED)
        canvas.drawString(2 * cm, 2.9 * cm, f"Bu belge {audience} ile paylaşılmak üzere DiagVoice tarafından hazırlanmıştır.")
        canvas.drawString(2 * cm, 2.45 * cm, "İzin alınmadan üçüncü kişilerle paylaşılamaz.")
        canvas.setStrokeColor(BRAND_RULE)
        canvas.setLineWidth(0.6)
        canvas.line(2 * cm, 1.8 * cm, W - 2 * cm, 1.8 * cm)
        canvas.setFont("Body", 8.5)
        canvas.drawString(2 * cm, 1.3 * cm, "© 2026 DiagVoice · diagvoice.com")
        canvas.restoreState()

    def page(canvas, doc):
        canvas.saveState()
        canvas.setFillColor(BRAND)
        canvas.rect(0, H - 0.25 * cm, W, 0.25 * cm, stroke=0, fill=1)
        canvas.drawImage(str(logo), 2 * cm, H - 1.55 * cm, 0.8 * cm, 0.8 * cm, preserveAspectRatio=True, mask="auto")
        canvas.setFont("Body-Bold", 9)
        canvas.setFillColor(BRAND_DARK)
        canvas.drawString(3.0 * cm, H - 1.1 * cm, "DiagVoice")
        canvas.setFont("Body", 9)
        canvas.setFillColor(MUTED)
        canvas.drawRightString(W - 2 * cm, H - 1.1 * cm, f"{header} · Sürüm {version}")
        canvas.setStrokeColor(BRAND_RULE)
        canvas.setLineWidth(0.6)
        canvas.line(2 * cm, H - 1.75 * cm, W - 2 * cm, H - 1.75 * cm)
        canvas.line(2 * cm, 1.5 * cm, W - 2 * cm, 1.5 * cm)
        canvas.setFont("Body", 8)
        canvas.drawString(2 * cm, 1.05 * cm, f"Gizli — {audience} için hazırlanmıştır · © 2026 DiagVoice")
        canvas.drawRightString(W - 2 * cm, 1.05 * cm, f"{doc.page}")
        canvas.restoreState()

    frame = Frame(2 * cm, 2 * cm, W - 4 * cm, H - 4.2 * cm, id="f", leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
    doc = BrandDoc(str(out), pagesize=A4, title=f"DiagVoice — {header} {version}", author="DiagVoice",
                   subject=doc_title, creator="DiagVoice")
    doc.addPageTemplates([PageTemplate("cover", frames=[frame], onPage=cover),
                          PageTemplate("toc", frames=[frame], onPage=page),
                          PageTemplate("body", frames=[frame], onPage=page)])
    doc.multiBuild(story)
    print(f"yazıldı: {out}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("src", type=Path)
    ap.add_argument("out", type=Path)
    ap.add_argument("--header", default="DiagVoice")
    ap.add_argument("--date", default="")
    ap.add_argument("--brand", action="store_true", help="kapak + içindekiler + DiagVoice renkleri")
    ap.add_argument("--title", default="", help="kapak alt başlığı (varsayılan: belgenin ilk # başlığı)")
    ap.add_argument("--version", default="")
    ap.add_argument("--audience", default="Müşteri")
    ap.add_argument("--logo", type=Path, default=Path(__file__).resolve().parents[1] / "app" / "public" / "logo.jpg")
    a = ap.parse_args()
    if a.brand:
        build_brand(a.src, a.out, title=a.title, header=a.header, version=a.version, date=a.date,
                    audience=a.audience, logo=a.logo)
    else:
        build_plain(a.src, a.out, a.header, a.date)

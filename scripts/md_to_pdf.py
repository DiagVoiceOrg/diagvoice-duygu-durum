"""
Basit Markdown → PDF (DiagVoice belge stili).

  python scripts/md_to_pdf.py docs/TOGG_API.md docs/DiagVoice_TOGG_API_v1.0.pdf --header "DiagVoice — TOGG Analiz API'si"

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
from reportlab.platypus import CondPageBreak, KeepTogether, Paragraph, Preformatted, SimpleDocTemplate, Spacer, Table, TableStyle  # noqa: E402

CODE_BG = colors.HexColor("#F4F6F9")
QUOTE_BG = colors.HexColor("#FFF7E6")


def inline(t: str) -> str:
    t = html.escape(t, quote=False)
    t = re.sub(r"`([^`]+)`", r'<font face="Mono" color="#24425F">\1</font>', t)
    t = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", t)
    return t


def build(src: Path, out: Path, header: str, date: str):
    br.register_fonts()
    br.styles()
    pdfmetrics.registerFont(TTFont("Mono", "C:/Windows/Fonts/consola.ttf"))
    S = br.STY
    code_style = ParagraphStyle("code", fontName="Mono", fontSize=8.2, leading=10.4, textColor=colors.HexColor("#1D2733"))
    cell = ParagraphStyle("cellm", parent=S["cell"], fontSize=8.8, leading=11.2)

    lines = src.read_text(encoding="utf-8").splitlines()
    story = []
    i = 0
    pending_heading = None

    def add(flow):
        nonlocal pending_heading
        if pending_heading is not None:
            story.append(KeepTogether([pending_heading, flow]))
            pending_heading = None
        else:
            story.append(flow)

    first_h1 = True
    while i < len(lines):
        ln = lines[i]
        if ln.startswith("```"):
            buf = []
            i += 1
            while i < len(lines) and not lines[i].startswith("```"):
                buf.append(lines[i])
                i += 1
            pre = Preformatted("\n".join(buf), code_style)
            t = Table([[pre]], colWidths=[16.4 * cm])
            t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), CODE_BG), ("BOX", (0, 0), (-1, -1), 0.4, br.RULE),
                                   ("LEFTPADDING", (0, 0), (-1, -1), 8), ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))
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
            # Sütun genişliği: içerik uzunluğuna göre
            lens = [max(len(r[k]) if k < len(r) else 0 for r in rows) for k in range(ncol)]
            lens = [min(max(L, 6), 60) for L in lens]
            tot = sum(lens)
            widths = [16.4 * cm * L / tot for L in lens]
            t = Table([hdr] + body, colWidths=widths, repeatRows=1, hAlign="LEFT")
            ts = [("BACKGROUND", (0, 0), (-1, 0), br.NAVY), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                  ("LINEBELOW", (0, 0), (-1, -1), 0.4, br.RULE), ("TOPPADDING", (0, 0), (-1, -1), 4),
                  ("BOTTOMPADDING", (0, 0), (-1, -1), 4), ("LEFTPADDING", (0, 0), (-1, -1), 5)]
            for r in range(2, len(rows), 2):
                ts.append(("BACKGROUND", (0, r), (-1, r), br.LIGHT))
            t.setStyle(TableStyle(ts))
            add(t)
            story.append(Spacer(1, 6))
            continue
        if ln.startswith("# "):
            if first_h1:
                story += [Spacer(1, 0.6 * cm), Paragraph(inline(ln[2:]), S["title"])]
                first_h1 = False
            else:
                pending_heading = Paragraph(inline(ln[2:]), S["h1"])
            i += 1
            continue
        if ln.startswith("## "):
            # Sayfa sonunda yer azsa bölümü yeni sayfadan başlat (başlık + giriş + tablo ayrılmasın)
            story.append(CondPageBreak(6 * cm))
            pending_heading = Paragraph(inline(ln[3:]), S["h1"])
            i += 1
            continue
        if ln.startswith("### "):
            h = Paragraph(inline(ln[4:]), S["h2"])
            pending_heading = KeepTogether([pending_heading, h]) if pending_heading is not None else h
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
            p = Paragraph(inline(ln[2:]), S["body"])
            t = Table([[p]], colWidths=[16.4 * cm])
            t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), QUOTE_BG), ("LINEBEFORE", (0, 0), (0, -1), 2.5, colors.HexColor("#C58B1A")),
                                   ("LEFTPADDING", (0, 0), (-1, -1), 9), ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
            add(t)
            story.append(Spacer(1, 6))
            i += 1
            continue
        if not ln.strip():
            i += 1
            continue
        # paragraf (ardışık satırlar)
        buf = [ln]
        i += 1
        while i < len(lines) and lines[i].strip() and not re.match(r"^(#|- |\||```|> )", lines[i]):
            buf.append(lines[i])
            i += 1
        text = " ".join(buf)
        style = S["subtitle"] if len(story) <= 2 else S["body"]
        add(Paragraph(inline(text), style))

    def on_page(canvas, doc):
        canvas.saveState()
        w, h = A4
        canvas.setStrokeColor(br.RULE)
        canvas.setLineWidth(0.5)
        canvas.line(2 * cm, h - 1.5 * cm, w - 2 * cm, h - 1.5 * cm)
        canvas.setFont("Body", 8.5)
        canvas.setFillColor(br.GREY)
        canvas.drawString(2 * cm, h - 1.3 * cm, header)
        canvas.line(2 * cm, 1.5 * cm, w - 2 * cm, 1.5 * cm)
        canvas.drawString(2 * cm, 1.05 * cm, date)
        canvas.drawRightString(w - 2 * cm, 1.05 * cm, f"Sayfa {doc.page}")
        canvas.restoreState()

    doc = SimpleDocTemplate(str(out), pagesize=A4, leftMargin=2 * cm, rightMargin=2 * cm, topMargin=2.1 * cm,
                            bottomMargin=2 * cm, title=header, author="DiagVoice")
    doc.build(story, onFirstPage=on_page, onLaterPages=on_page)
    print(f"yazıldı: {out}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("src", type=Path)
    ap.add_argument("out", type=Path)
    ap.add_argument("--header", default="DiagVoice")
    ap.add_argument("--date", default="")
    a = ap.parse_args()
    build(a.src, a.out, a.header, a.date)

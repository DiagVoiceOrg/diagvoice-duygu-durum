"""
DiagVoice yük testi raporu (PDF).

  python loadtest/report/build_report.py --metrics <sunucu metrik CSV> --out docs/DiagVoice_Yuk_Testi_Raporu_2026-11-10.pdf

Girdi: loadtest/results/<koşu>/<kademe>.json (k6 özetleri) + sunucu izleme CSV'si.
"""
from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime, timedelta
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from reportlab.lib import colors  # noqa: E402
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY  # noqa: E402
from reportlab.lib.pagesizes import A4  # noqa: E402
from reportlab.lib.styles import ParagraphStyle  # noqa: E402
from reportlab.lib.units import cm  # noqa: E402
from reportlab.pdfbase import pdfmetrics  # noqa: E402
from reportlab.pdfbase.ttfonts import TTFont  # noqa: E402
from reportlab.platypus import (  # noqa: E402
    Image,
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "loadtest" / "results"
TMP = ROOT / "loadtest" / "results" / "_report_assets"

# --- Koşular (UTC) -------------------------------------------------------------
RUNS = {
    "cf_single": "20261110T141138Z",  # fused_1, Cloudflare üzerinden
    "cf_fused": "20261110T141234Z",  # fused_10..1000, Cloudflare üzerinden
    "direct_text_root": "20261110T144026Z",  # text + root, doğrudan origin
    "direct_fused": "20261110T150323Z",  # fused_100 + 1000, doğrudan origin
}

# Kademe başlangıç saatleri (UTC) — run.log'dan
STAGE_START = {
    ("cf_single", "fused_1"): "14:11:46",
    ("cf_fused", "fused_10"): "14:12:43",
    ("cf_fused", "fused_25"): "14:17:02",
    ("cf_fused", "fused_50"): "14:21:37",
    ("cf_fused", "fused_100"): "14:26:44",
    ("cf_fused", "fused_100_burst"): "14:30:02",
    ("cf_fused", "fused_1000_burst"): "14:33:20",
    ("direct_text_root", "text_1"): "14:41:09",
    ("direct_text_root", "text_10"): "14:42:18",
    ("direct_text_root", "text_100"): "14:46:26",
    ("direct_text_root", "text_1000_burst"): "14:50:35",
    ("direct_text_root", "root_1000_burst"): "14:51:54",
    ("direct_text_root", "root_5000_burst"): "14:53:05",
}

LABEL = {
    "fused_1": "1 istek",
    "fused_10": "10 kullanıcı (3 dk)",
    "fused_25": "25 kullanıcı (3 dk)",
    "fused_50": "50 kullanıcı (3 dk)",
    "fused_100": "100 kullanıcı (3 dk)",
    "fused_100_burst": "100 istek aynı anda",
    "fused_1000_burst": "1.000 istek aynı anda",
    "text_1": "1 istek",
    "text_10": "10 kullanıcı (3 dk)",
    "text_100": "100 kullanıcı (3 dk)",
    "text_1000_burst": "1.000 istek aynı anda",
    "root_1000_burst": "1.000 istek aynı anda",
    "root_5000_burst": "5.000 istek aynı anda",
}

NAVY = colors.HexColor("#1F3A5F")
GREY = colors.HexColor("#5A6270")
LIGHT = colors.HexColor("#EEF2F7")
RULE = colors.HexColor("#C9D1DC")
C_CPU = "#C0504D"
C_GPU = "#1F3A5F"


# --- Veri ----------------------------------------------------------------------
def load_stage(run_key: str, stage: str) -> dict | None:
    p = RESULTS / RUNS[run_key] / f"{stage}.json"
    if not p.is_file():
        return None
    d = json.loads(p.read_text(encoding="utf-8"))
    m = d["metrics"]

    def cnt(k):
        return int(m[k]["values"]["count"]) if k in m else 0

    def dur(k, q):
        v = m.get(k, {}).get("values", {})
        x = v.get(q)
        return None if x is None else x / 1000.0

    reqs = m.get("http_reqs", {}).get("values", {})
    st = d.get("state", {})
    return {
        "stage": stage,
        "n": cnt("http_reqs"),
        "rps": reqs.get("rate", 0.0),
        "ok": cnt("status_2xx"),
        "c4": cnt("status_4xx"),
        "c5": cnt("status_5xx"),
        "net": cnt("status_network_error"),
        "med": dur("http_req_duration", "med"),
        "p95": dur("http_req_duration", "p(95)"),
        "max": dur("http_req_duration", "max"),
        "ok_med": dur("ok_duration", "med"),
        "ok_p95": dur("ok_duration", "p(95)"),
        "test_s": (st.get("testRunDurationMs") or 0) / 1000.0,
        "aborted": False,
    }


def load_metrics(path: Path) -> list[dict]:
    rows = []
    with path.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            try:
                rows.append(
                    {
                        "t": datetime.strptime(r["ts_utc"][:19], "%Y-%m-%dT%H:%M:%S"),
                        "gpu": float(r["gpu_util_pct"]),
                        "vram": float(r["vram_used_mib"]),
                        "cpu": float(r["cpu_pct"]),
                        "load1": float(r["load_1"]),
                        "avail": float(r["mem_available_mib"]),
                    }
                )
            except (KeyError, ValueError):
                continue
    return rows


def window(rows, start: datetime, end: datetime) -> dict | None:
    s = [r for r in rows if start <= r["t"] < end]
    if not s:
        return None
    return {
        "gpu_avg": sum(r["gpu"] for r in s) / len(s),
        "cpu_avg": sum(r["cpu"] for r in s) / len(s),
        "load_max": max(r["load1"] for r in s),
        "avail_min": min(r["avail"] for r in s) / 1024,
        "vram_max": max(r["vram"] for r in s) / 1024,
    }


# --- Biçim ---------------------------------------------------------------------
def fs(x, unit="s"):
    if x is None:
        return "–"
    if unit == "s":
        return (f"{x:.2f}".replace(".", ",") + " sn") if x < 10 else f"{x:.0f} sn"
    return str(x)


def tr_int(n: int) -> str:
    return f"{n:,}".replace(",", ".")


def pct(a, b):
    return "–" if not b else f"%{100 * a / b:.0f}".replace(".", ",")


def register_fonts():
    fdir = Path("C:/Windows/Fonts")
    pdfmetrics.registerFont(TTFont("Body", str(fdir / "calibri.ttf")))
    pdfmetrics.registerFont(TTFont("Body-Bold", str(fdir / "calibrib.ttf")))
    pdfmetrics.registerFont(TTFont("Body-Italic", str(fdir / "calibrii.ttf")))
    pdfmetrics.registerFont(TTFont("Body-BoldItalic", str(fdir / "calibriz.ttf")))
    from reportlab.pdfbase.pdfmetrics import registerFontFamily

    registerFontFamily("Body", normal="Body", bold="Body-Bold", italic="Body-Italic", boldItalic="Body-BoldItalic")
    plt.rcParams["font.family"] = "Calibri"


STY = {}


def styles():
    STY["title"] = ParagraphStyle("title", fontName="Body-Bold", fontSize=22, leading=27, textColor=NAVY, spaceAfter=6)
    STY["subtitle"] = ParagraphStyle("subtitle", fontName="Body", fontSize=12.5, leading=16, textColor=GREY)
    STY["h1"] = ParagraphStyle("h1", fontName="Body-Bold", fontSize=15, leading=19, textColor=NAVY, spaceBefore=14, spaceAfter=6)
    STY["h2"] = ParagraphStyle("h2", fontName="Body-Bold", fontSize=12, leading=15, textColor=NAVY, spaceBefore=10, spaceAfter=4)
    STY["body"] = ParagraphStyle("body", fontName="Body", fontSize=10.5, leading=14.5, alignment=TA_JUSTIFY, spaceAfter=6)
    STY["bullet"] = ParagraphStyle("bullet", parent=STY["body"], leftIndent=14, bulletIndent=3, spaceAfter=3)
    STY["small"] = ParagraphStyle("small", fontName="Body", fontSize=8.5, leading=11, textColor=GREY)
    STY["caption"] = ParagraphStyle("caption", fontName="Body-Italic", fontSize=9, leading=12, textColor=GREY, alignment=TA_CENTER, spaceBefore=3, spaceAfter=10)
    STY["cell"] = ParagraphStyle("cell", fontName="Body", fontSize=9, leading=11.5)
    STY["cellb"] = ParagraphStyle("cellb", fontName="Body-Bold", fontSize=9, leading=11.5, textColor=colors.white)
    STY["meta"] = ParagraphStyle("meta", fontName="Body", fontSize=10, leading=14)


def P(text, s="body"):
    return Paragraph(text, STY[s])


def bullets(items):
    return [Paragraph(t, STY["bullet"], bulletText="•") for t in items]


def table(header, rows, widths, align_right_from=1, zebra=True):
    data = [[Paragraph(h, STY["cellb"]) for h in header]]
    for r in rows:
        data.append([c if not isinstance(c, str) else Paragraph(c, STY["cell"]) for c in r])
    t = Table(data, colWidths=widths, repeatRows=1, hAlign="LEFT")
    ts = [
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LINEBELOW", (0, 0), (-1, -1), 0.4, RULE),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
    ]
    if zebra:
        for i in range(1, len(data)):
            if i % 2 == 0:
                ts.append(("BACKGROUND", (0, i), (-1, i), LIGHT))
    t.setStyle(TableStyle(ts))
    return t


def k6_rows(results, keys):
    out = []
    for k in keys:
        r = results.get(k)
        if not r:
            continue
        out.append(
            [
                LABEL.get(r["stage"], r["stage"]),
                tr_int(r["n"]),
                f"{tr_int(r['ok'])} ({pct(r['ok'], r['n'])})",
                tr_int(r["c5"]),
                tr_int(r["net"]),
                fs(r["med"]),
                fs(r["p95"]),
                fs(r["max"]),
                f"{r['rps']:.2f}".replace(".", ","),
            ]
        )
    return out


K6_HEADER = ["Kademe", "İstek", "Başarılı (2xx)", "5xx", "Bağlantı hatası", "Medyan", "p95", "En uzun", "İstek/sn"]
K6_W = [3.6 * cm, 1.4 * cm, 2.3 * cm, 1.1 * cm, 1.8 * cm, 1.6 * cm, 1.5 * cm, 1.6 * cm, 1.5 * cm]


# --- Grafikler ------------------------------------------------------------------
def chart_fused_latency(cf):
    keys = ["fused_1", "fused_10", "fused_25", "fused_50"]
    xs = [1, 10, 25, 50]
    med = [cf[k]["ok_med"] for k in keys]
    p95 = [cf[k]["ok_p95"] for k in keys]
    fig, ax = plt.subplots(figsize=(7.2, 3.2), dpi=200)
    ax.plot(xs, med, marker="o", color=C_GPU, label="Medyan")
    ax.plot(xs, p95, marker="s", color=C_CPU, label="p95")
    ax.axhline(100, color="#888", ls="--", lw=1)
    ax.text(50, 103, "Cloudflare zaman aşımı (100 sn)", fontsize=8.5, color="#555", ha="right")
    for x, y in zip(xs, med):
        ax.annotate(f"{y:.0f} sn" if y >= 10 else f"{y:.1f} sn", (x, y), textcoords="offset points", xytext=(6, -12), fontsize=8.5, color=C_GPU)
    ax.set_xlabel("Eşzamanlı kullanıcı")
    ax.set_ylabel("Yanıt süresi (sn)")
    ax.set_ylim(0, 130)
    ax.grid(alpha=0.25)
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(frameon=False, loc="center left", bbox_to_anchor=(0.02, 0.55))
    fig.tight_layout()
    p = TMP / "fused_latency.png"
    fig.savefig(p)
    plt.close(fig)
    return p


def chart_cpu_gpu(stage_res):
    labels = [s[0] for s in stage_res]
    cpu = [s[1]["cpu_avg"] for s in stage_res]
    gpu = [s[1]["gpu_avg"] for s in stage_res]
    fig, ax = plt.subplots(figsize=(7.2, 3.3), dpi=200)
    import numpy as np

    x = np.arange(len(labels))
    w = 0.38
    ax.bar(x - w / 2, cpu, w, color=C_CPU, label="CPU (ort. %)")
    ax.bar(x + w / 2, gpu, w, color=C_GPU, label="GPU (ort. %)")
    ax.set_xticks(x, labels, rotation=25, ha="right", fontsize=8.5)
    ax.set_ylim(0, 105)
    ax.set_ylabel("Kullanım (%)")
    ax.grid(axis="y", alpha=0.25)
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(frameon=False, ncol=2, loc="upper right")
    fig.tight_layout()
    p = TMP / "cpu_gpu.png"
    fig.savefig(p)
    plt.close(fig)
    return p


def chart_timeline(rows, marks):
    t0 = rows[0]["t"]
    # Kayıtlar arasındaki boşlukta çizgi birleşmesin
    gapped = []
    for i, r in enumerate(rows):
        if i and (r["t"] - rows[i - 1]["t"]).total_seconds() > 30:
            gapped.append({"t": rows[i - 1]["t"] + timedelta(seconds=1), "cpu": float("nan"), "gpu": float("nan"), "avail": float("nan")})
        gapped.append(r)
    rows = gapped
    xs = [(r["t"] - t0).total_seconds() / 60 for r in rows]

    def smooth(v, k=15):
        out, acc = [], []
        for x in v:
            if x != x:  # NaN: boşluk
                out.append(x)
                acc = []
                continue
            acc.append(x)
            if len(acc) > k:
                acc.pop(0)
            out.append(sum(acc) / len(acc))
        return out

    fig, ax = plt.subplots(figsize=(7.2, 3.3), dpi=200)
    ax.plot(xs, smooth([r["cpu"] for r in rows]), color=C_CPU, lw=1.2, label="CPU %")
    ax.plot(xs, smooth([r["gpu"] for r in rows]), color=C_GPU, lw=1.2, label="GPU %")
    ax2 = ax.twinx()
    ax2.plot(xs, [r["avail"] / 1024 for r in rows], color="#6A8E3F", lw=1.1, ls="--", label="Boş RAM (GB)")
    ax2.set_ylabel("Boş RAM (GB)", color="#6A8E3F")
    ax2.set_ylim(0, 8)
    for label, start in marks:
        m = (start - t0).total_seconds() / 60
        ax.axvline(m, color="#bbb", lw=0.7)
        ax.text(m + 0.25, 103, label, fontsize=6.3, rotation=90, va="bottom", color="#555")
    ax.set_xlabel(f"Dakika ({t0:%H:%M} UTC'den itibaren)")
    ax.set_ylabel("Kullanım (%)  (15 sn ortalama)")
    ax.set_ylim(0, 102)
    ax.spines[["top"]].set_visible(False)
    h1, l1 = ax.get_legend_handles_labels()
    h2, l2 = ax2.get_legend_handles_labels()
    ax.legend(h1 + h2, l1 + l2, frameon=False, loc="upper center", bbox_to_anchor=(0.5, -0.2), ncol=3, fontsize=8)
    fig.tight_layout()
    p = TMP / "timeline.png"
    fig.savefig(p)
    plt.close(fig)
    return p


# --- Sayfa şablonu --------------------------------------------------------------
def on_page(canvas, doc):
    canvas.saveState()
    w, h = A4
    canvas.setStrokeColor(RULE)
    canvas.setLineWidth(0.5)
    canvas.line(2 * cm, h - 1.5 * cm, w - 2 * cm, h - 1.5 * cm)
    canvas.setFont("Body", 8.5)
    canvas.setFillColor(GREY)
    canvas.drawString(2 * cm, h - 1.3 * cm, "DiagVoice — API Yük Testi Raporu")
    canvas.drawRightString(w - 2 * cm, h - 1.3 * cm, "Gizli — Şirket içi")
    canvas.line(2 * cm, 1.5 * cm, w - 2 * cm, 1.5 * cm)
    canvas.drawString(2 * cm, 1.05 * cm, "10 Kasım 2026")
    canvas.drawRightString(w - 2 * cm, 1.05 * cm, f"Sayfa {doc.page}")
    canvas.restoreState()


# --- Rapor ----------------------------------------------------------------------
def build(metrics_csvs: list[Path], out: Path):
    register_fonts()
    styles()
    TMP.mkdir(parents=True, exist_ok=True)

    cf = {}
    for s in ["fused_1"]:
        cf[s] = load_stage("cf_single", s)
    for s in ["fused_10", "fused_25", "fused_50", "fused_100", "fused_100_burst", "fused_1000_burst"]:
        cf[s] = load_stage("cf_fused", s)
    tr = {s: load_stage("direct_text_root", s) for s in ["text_1", "text_10", "text_100", "text_1000_burst", "root_1000_burst", "root_5000_burst"]}
    dfu = {s: load_stage("direct_fused", s) for s in ["fused_100", "fused_1000_burst"]}
    dfu = {k: v for k, v in dfu.items() if v}

    rows = sorted((r for p in metrics_csvs for r in load_metrics(p)), key=lambda r: r["t"])
    day = rows[0]["t"].date()
    T = lambda hms: datetime.combine(day, datetime.strptime(hms, "%H:%M:%S").time())  # noqa: E731

    res_windows = [
        ("Boşta", T("14:05:05"), T("14:11:40")),
        ("fused 10", T("14:12:43"), T("14:15:50")),
        ("fused 25", T("14:17:02"), T("14:20:30")),
        ("fused 50", T("14:21:37"), T("14:25:45")),
        ("fused 100", T("14:26:44"), T("14:29:00")),
        ("fused 100 aynı anda", T("14:30:02"), T("14:32:15")),
        ("fused 1.000 aynı anda", T("14:33:20"), T("14:36:00")),
        ("İptal sonrası (7 dk)", T("14:34:00"), T("14:41:00")),
        ("text 10", T("14:42:18"), T("14:45:20")),
        ("text 100", T("14:46:26"), T("14:49:30")),
        ("GET / 1.000", T("14:51:54"), T("14:52:10")),
        ("GET / 5.000", T("14:53:05"), T("14:53:40")),
        ("fused 100 (doğrudan)", T("15:06:51"), T("15:12:10")),
        ("fused 1.000 aynı anda (doğrudan)", T("15:13:16"), T("15:14:00")),
        ("İptal sonrası (doğrudan, 6 dk)", T("15:14:00"), T("15:19:40")),
    ]
    res = [(n, window(rows, a, b)) for n, a, b in res_windows]
    res = [(n, w) for n, w in res if w]

    p_lat = chart_fused_latency(cf)
    p_cg = chart_cpu_gpu([r for r in res if not r[0].startswith(("Boşta", "GET", "İptal"))])
    marks = [
        ("fused 10", T("14:12:43")), ("25", T("14:17:02")), ("50", T("14:21:37")), ("100", T("14:26:44")),
        ("100 an.", T("14:30:02")), ("1.000 an.", T("14:33:20")), ("text 10", T("14:42:18")),
        ("text 100", T("14:46:26")), ("GET /", T("14:51:54")),
        ("fused 100 (doğr.)", T("15:06:51")), ("1.000 an. (doğr.)", T("15:13:16")),
    ]
    p_tl = chart_timeline(rows, marks)

    thr = [cf[k]["rps"] for k in ["fused_10", "fused_25", "fused_50"]]
    thr_avg = sum(thr) / len(thr)

    doc = SimpleDocTemplate(
        str(out), pagesize=A4, leftMargin=2 * cm, rightMargin=2 * cm, topMargin=2.1 * cm, bottomMargin=2 * cm,
        title="DiagVoice API Yük Testi Raporu", author="DiagVoice", subject="Yük testi — 10 Kasım 2026",
    )
    S = []

    # Kapak bilgisi
    S += [Spacer(1, 1.2 * cm), P("API Yük Testi Raporu", "title"), P("DiagVoice ses ve metin analizi servisi — mevcut sistem", "subtitle"), Spacer(1, 0.6 * cm)]
    meta = [
        ["Test tarihi", "10 Kasım 2026, 14:11–15:15 UTC (17:11–18:15 TSİ)"],
        ["Hedef sistem", "aiapi.diagvoice.com (AWS g4dn.xlarge, tek sunucu)"],
        ["Kod sürümü", "feat/prod-hardening, commit ee61b56"],
        ["Araç", "Grafana k6 2.3.0; sunucu tarafında 1 sn aralıklı kaynak izleme"],
        ["Kapsam", "/analyze-fused, /analyze-text-sentiment, GET /"],
        ["Belge durumu", "Sürüm 1.0 — Şirket içi"],
    ]
    mt = Table([[P(f"<b>{a}</b>", "meta"), P(b, "meta")] for a, b in meta], colWidths=[3.6 * cm, 12.8 * cm], hAlign="LEFT")
    mt.setStyle(TableStyle([("LINEBELOW", (0, 0), (-1, -1), 0.4, RULE), ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]))
    S += [mt, Spacer(1, 0.8 * cm)]

    # 1. Yönetici özeti
    S += [P("1. Yönetici özeti", "h1")]
    S += [P(
        "Bu test, DiagVoice API'sinin bugünkü haliyle (rate limit, istek kuyruğu ve yatay ölçekleme olmadan) artan yük "
        "altındaki davranışını ölçmek amacıyla yapılmıştır. Sonuçlar, yol haritasındaki kimlik doğrulama/rate limit (F1), "
        "model servislerinin ayrıştırılması (F2) ve kuyruk sistemi (F4) çalışmalarına girdi olarak kullanılacaktır."
    )]
    S += bullets([
        f"<b>Ses analizi kapasitesi saniyede yaklaşık {thr_avg:.2f} istektir</b>".replace(".", ",") + f" (saatte ~{tr_int(round(thr_avg * 3600, -2))}). "
        + "Bu sınıra 10 eşzamanlı kullanıcıda ulaşılmakta; daha fazla kullanıcı throughput'u artırmamakta, yalnızca bekleme süresini uzatmaktadır.",
        "<b>Darboğaz GPU değil, CPU'dur.</b> Ses analizi yükü altında CPU ortalama %77–92 doluluktayken GPU ortalama %23–34 kullanılmaktadır. "
        "4 vCPU'lu g4dn.xlarge'da ses çözme ve akustik özellik çıkarma işlemleri CPU'yu doyurmaktadır.",
        "<b>Cloudflare'in 100 saniyelik zaman aşımı gerçek kullanıcılar için kritik bir risktir.</b> 100 eşzamanlı kullanıcıda bekleme süresi "
        "100 saniyeyi aşmakta ve istekler sunucu yanıt vermeden 5xx ile sonlanmaktadır. Cloudflare atlandığında aynı yükte isteklerin tamamı başarılı olmuş, ancak bekleme 4–5 dakikaya çıkmıştır.",
        "<b>1.000 ani ses analizi isteğinde sistem kuyruklamak yerine hızlı hata vermektedir:</b> isteklerin bir kısmı ilk saniyede reddedilmiş, bir kısmı "
        "15 saniyede 5xx ile, bir kısmı ise 20 saniye içinde muhtemelen eksik model sonuçlarıyla 200 olarak dönmüştür.",
        "<b>Metin analizi rahattır:</b> saniyede ~90 istek, 100 eşzamanlı kullanıcıda dahi hatasız.",
        "<b>Ani 1.000+ bağlantıda bağlantıların %16–21'i ilk saniyede reddedilmektedir</b>; sunucu CPU'su bu sırada %14'ün altındadır, "
        "yani sınır işlem gücünde değil bağlantı kabul katmanındadır.",
        "<b>Sunucu hiçbir kademede çökmemiş</b>, her kademeden sonra en geç 20 saniye içinde sağlıklı yanıt vermeye dönmüştür.",
        "<b>İstemci bağlantısı koptuğunda sunucu işi iptal etmemektedir:</b> 1.000 isteklik kademe durdurulduktan sonra sunucu yaklaşık "
        "7 dakika boyunca sahipsiz istekleri işlemeye devam etmiştir.",
    ])

    # 2. Kapsam ve yöntem
    S += [P("2. Kapsam ve yöntem", "h1")]
    S += [KeepTogether([P("2.1 Test edilen uç noktalar", "h2"), table(
        ["Uç nokta", "İçerik", "Neyi temsil ediyor"],
        [
            ["POST /analyze-fused", "Ses dosyası (m4a, 150 KB): STT + duygu + sağlık modelleri", "Gerçek kullanım; en ağır iş"],
            ["POST /analyze-text-sentiment", "Kısa Türkçe metin, tek BERT modeli (GPU)", "Hafif model çağrısı"],
            ["GET /", "Servis bilgisi; model çalıştırmaz", "Karşılama katmanı: nginx, uvicorn, audit kaydı"],
        ],
        [4.2 * cm, 6.6 * cm, 5.6 * cm],
    )])]
    S += [P("2.2 Yük modeli", "h2")]
    S += bullets([
        "<b>Sürekli yük:</b> N sanal kullanıcı 3 dakika boyunca, her biri bir önceki yanıtı aldıktan hemen sonra yeni istek gönderir.",
        "<b>Ani yük (\"aynı anda\"):</b> N istek aynı anda başlatılır, her kullanıcı tek istek gönderir.",
        "Her kademede hata oranı 30 saniye sonra %50'yi aşarsa kademe otomatik durdurulmuştur. Kademeler arasında 60 saniye beklenmiş ve "
        "sunucunun sağlıklı yanıt vermesi şartı aranmıştır.",
        "Yük, tek bir istemci makineden (Windows, ev internet bağlantısı) üretilmiştir.",
    ])
    S += [P("2.3 Ağ yolu", "h2")]
    S += [P(
        "Test sırasında <b>aiapi.diagvoice.com</b> alan adının Cloudflare proxy'si arkasında olduğu tespit edilmiştir. Ses analizi kademeleri "
        "önce Cloudflare üzerinden çalıştırılmış; Cloudflare'in kendi sınırlarının sonuçları maskelediği görülünce metin ve GET / kademeleri "
        "ile ses analizinin yüksek kademeleri <b>doğrudan sunucuya</b> (aynı alan adı ve TLS sertifikası, Cloudflare atlanarak) tekrarlanmıştır."
    )]

    # 3. Sonuçlar
    S += [P("3. Sonuçlar", "h1"), P("3.1 Ses analizi — /analyze-fused (Cloudflare üzerinden)", "h2")]
    S += [table(K6_HEADER, k6_rows(cf, ["fused_1", "fused_10", "fused_25", "fused_50", "fused_100", "fused_100_burst", "fused_1000_burst"]), K6_W)]
    S += [P(
        "100 kullanıcı ve üzeri kademeler hata oranı eşiği nedeniyle erken durdurulmuştur. 1.000 isteklik kademede tabloda yalnızca durdurma anına "
        "kadar tamamlanan istekler yer almaktadır. ~127 saniyede kesilen 5xx yanıtlar Cloudflare zaman aşımına (HTTP 524) karşılık gelmektedir.",
        "small",
    ), Spacer(1, 6)]
    S += [KeepTogether([Image(str(p_lat), width=16.4 * cm, height=7.3 * cm), P("Şekil 1 — Eşzamanlı kullanıcı sayısına göre ses analizi yanıt süresi (başarılı istekler)", "caption")])]
    S += [P(
        "Throughput 10, 25 ve 50 kullanıcıda sırasıyla " + ", ".join(f"{x:.2f}".replace(".", ",") for x in thr[:2]) + f" ve {thr[2]:.2f}".replace(".", ",") + " istek/sn ile sabit kalmıştır. "
        + "Yanıt süresi eşzamanlılıkla doğrusal artmaktadır (Little yasası: 50 kullanıcı / 0,56 istek/sn ≈ 89 sn; ölçülen medyan 80 sn). "
        "Bu, isteklerin sunucuda sıra beklediğini ve ek kullanıcıların kapasiteyi artırmadığını göstermektedir."
    )]

    if dfu:
        S += [KeepTogether([P("3.2 Ses analizi — /analyze-fused (doğrudan sunucu)", "h2"), table(K6_HEADER, k6_rows(dfu, ["fused_100", "fused_1000_burst"]), K6_W)])]
        S += [P(
            "Cloudflare atlandığında 100 kullanıcılı kademede isteklerin tamamı başarıyla tamamlanmış, ancak medyan bekleme 4,5 dakikaya çıkmıştır. "
            "Kademe başladığında sunucu önceki koşudan kalan istekleri hâlâ işlediği için throughput (0,32 istek/sn) ilk ölçümün altında kalmıştır. "
            "1.000 isteklik kademede ilk saniyede 175 bağlantı reddedilmiş; ardından 86 istek ortalama 15 saniyede 5xx ile, 102 istek ise 20 saniye "
            "içinde 200 ile dönmüştür. Sunucunun kapasitesi düşünüldüğünde bu hızlı 200 yanıtlarının bazı modellerin hata alanıyla döndüğü kısmi "
            "sonuçlar olması kuvvetle muhtemeldir (yanıt gövdeleri bu testte kaydedilmemiştir). Kademe, hata oranı eşiği nedeniyle 32. saniyede durdurulmuştur.",
            "small",
        )]

    n = "3.3" if dfu else "3.2"
    _h33 = P(f"{n} Metin analizi ve karşılama katmanı (doğrudan sunucu)", "h2")
    trows = k6_rows(tr, ["text_1", "text_10", "text_100", "text_1000_burst"])
    rrows = k6_rows(tr, ["root_1000_burst", "root_5000_burst"])
    trows = [["<b>/analyze-text-sentiment</b>"] + [""] * 8] + trows + [["<b>GET /</b>"] + [""] * 8] + rrows
    t = table(K6_HEADER, trows, K6_W)
    t.setStyle(TableStyle([("SPAN", (0, 1), (-1, 1)), ("SPAN", (0, 6), (-1, 6)), ("BACKGROUND", (0, 1), (-1, 1), colors.HexColor("#DCE3EC")), ("BACKGROUND", (0, 6), (-1, 6), colors.HexColor("#DCE3EC"))]))
    S += [KeepTogether([_h33, t]), Spacer(1, 4)]
    S += [P(
        "Bağlantı hataları istemci tarafında \"bağlantı uzak sunucu tarafından kapatıldı\" ve \"EOF\" olarak görülmüş, tamamı kademenin ilk 1–2 "
        "saniyesinde oluşmuştur. Sunucuya ulaşan isteklerin hiçbiri 5xx ile sonuçlanmamıştır.",
        "small",
    )]

    n = "3.4" if dfu else "3.3"
    S += [KeepTogether([P(f"{n} Sunucu kaynak kullanımı", "h2"), table(
        ["Dönem", "CPU ort.", "GPU ort.", "Load (en yüksek, 4 vCPU)", "Boş RAM (en düşük)", "VRAM (en yüksek)"],
        [[n_, f"%{w['cpu_avg']:.0f}", f"%{w['gpu_avg']:.0f}", f"{w['load_max']:.1f}".replace(".", ","),
          f"{w['avail_min']:.1f} GB".replace(".", ","), f"{w['vram_max']:.1f} / 15 GB".replace(".", ",")] for n_, w in res],
        [5.4 * cm, 1.6 * cm, 1.6 * cm, 3.0 * cm, 2.5 * cm, 2.3 * cm],
    )])]
    S += [Spacer(1, 6), KeepTogether([Image(str(p_tl), width=15.0 * cm, height=6.9 * cm), P("Şekil 2 — Test boyunca sunucu CPU, GPU ve boş RAM değişimi (dikey çizgiler kademe başlangıçlarıdır)", "caption")])]
    S += [KeepTogether([Image(str(p_cg), width=15.0 * cm, height=6.9 * cm), P("Şekil 3 — Kademelere göre ortalama CPU ve GPU kullanımı", "caption")])]

    # 4. Bulgular
    S += [P("4. Bulgular ve değerlendirme", "h1")]
    findings = [
        ("Yüksek", "Ses analizinin darboğazı CPU",
         "Ses analizi yükünde CPU %77–92, sistem yükü (load) 4 çekirdek için 6–11 seviyesindeyken GPU ortalama %23–34 kullanılmıştır. Ses çözme "
         "(ffmpeg), librosa/openSMILE/Praat ile akustik özellik çıkarma ve benchmark modeli CPU'da çalışmaktadır. GPU'yu büyütmek kapasiteyi "
         "artırmaz; 8 vCPU'lu g4dn.2xlarge (aynı T4 GPU) kapasiteyi kabaca iki katına çıkarabilir."),
        ("Yüksek", "Cloudflare zaman aşımı (100 sn)",
         "Sıradaki bekleme 100 saniyeyi aştığında Cloudflare isteği sonlandırmaktadır. Mevcut kapasiteyle bu durum ~55 eşzamanlı ses analizi isteğinde "
         "başlar. Aynı yük Cloudflare atlanarak uygulandığında isteklerin tamamı başarılı olmuştur; yani bu hatalar sunucudan değil, Cloudflare "
         "sınırından kaynaklanmaktadır. nginx'te tanımlı 900 saniyelik zaman aşımı Cloudflare arkasında geçerli değildir."),
        ("Yüksek", "Aşırı yükte koruma yok",
         "Rate limit veya kabul kontrolü olmadığından fazla istek reddedilmek yerine sıraya girmekte ve tüm kullanıcıların bekleme süresini uzatmaktadır. "
         "Tek bir istemcinin yoğun trafiği diğer müşterileri (ör. TOGG) doğrudan etkilemektedir."),
        ("Yüksek", "Ani yükte hızlı hata ve olası kısmi yanıtlar",
         "1.000 ani ses analizi isteğinde (doğrudan sunucu) istekler kuyrukta beklemek yerine 15–20 saniye içinde 5xx ya da 200 ile dönmüştür. "
         "fusion servisinin iç servislere açtığı bağlantı havuzu 64 ile sınırlıdır; aşımda iç çağrıların hata verip ana yanıtın eksik model "
         "sonuçlarıyla 200 dönmesi beklenen davranıştır. İstemci 200 aldığı halde eksik sonuç alıyor olabilir; yanıt gövdeleriyle doğrulanmalıdır."),
        ("Orta", "Kopan istekler iptal edilmiyor",
         "1.000 isteklik kademe 14:33:52'de durdurulduktan sonra sunucu 14:41'e kadar %60–100 CPU ile çalışmaya devam etmiştir. Aynı durum "
         "doğrudan sunucu koşusunda da tekrarlanmıştır (15:13:48'de durdurma, 15:19:38'e kadar yük). Yanıtı bekleyen kimse olmayan işler "
         "kapasite tüketmekte ve sonraki kullanıcıları bekletmektedir."),
        ("Orta", "Ani bağlantılarda kabul katmanı sınırı",
         "1.000 ve 5.000 ani bağlantıda bağlantıların %16–21'i ilk saniyede reddedilmiştir; sunucu CPU'su %14'ün altındadır. Olası nedenler nginx "
         "listen backlog (varsayılan 511) ve worker_connections sınırıdır. Tek istemci makinenin ağ sınırları da katkıda bulunmuş olabilir; "
         "nginx hata günlüğü ile doğrulanmalıdır."),
        ("Orta", "Bellek geri dönmüyor",
         "Boş RAM test başında 7,3 GB iken 3,5 GB'a düşmüş ve yük bittikten sonra toparlanmamıştır. Sızıntı ya da model/önbellek büyümesi olabilir; "
         "uzun süreli yükte bellek yetersizliği riski vardır. Servis bazında bellek ölçümü yapılmalıdır."),
        ("Bilgi", "GPU belleği yeterli",
         "VRAM en fazla 10,3 / 15 GB kullanılmış, hiçbir kademede GPU bellek hatası oluşmamıştır."),
        ("Bilgi", "Kararlılık",
         "Hiçbir kademede servis çökmesi yaşanmamış; sunucu her kademeden sonra en geç 20 saniye içinde sağlıklı yanıt vermiştir."),
    ]
    sev_col = {"Yüksek": colors.HexColor("#B03A2E"), "Orta": colors.HexColor("#C58B1A"), "Bilgi": colors.HexColor("#4F6D8F")}
    frows = []
    for i, (sev, title, txt) in enumerate(findings, 1):
        frows.append([P(f"B{i}", "cell"), Paragraph(f'<font color="{sev_col[sev].hexval().replace("0x", "#")}"><b>{sev}</b></font>', STY["cell"]), P(f"<b>{title}</b><br/>{txt}", "cell")])
    S += [table(["No", "Önem", "Bulgu"], frows, [1.0 * cm, 1.6 * cm, 13.8 * cm], zebra=True)]

    # 5. Öneriler
    S += [P("5. Öneriler", "h1")]
    S += [table(
        ["Öncelik", "Öneri", "İlgili bulgu", "Yol haritası"],
        [
            ["1", "API anahtarı bazlı rate limit ve eşzamanlı ses analizi sınırı; sınır aşımında hemen 429 yanıtı", "B2, B3, B4", "F1"],
            ["2", "Ses analizi için asenkron iş API'si (iş gönder → sonucu sorgula); Cloudflare zaman aşımını ortadan kaldırır", "B2, B5", "F4"],
            ["3", "Kopan/zaman aşımına uğrayan istekleri iptal eden kuyruk (Redis + worker)", "B5", "F4"],
            ["4", "CPU yoğun özellik çıkarmayı ayrı CPU worker'a taşımak; kısa vadede g4dn.2xlarge değerlendirmesi", "B1", "F2 / F3"],
            ["5", "nginx: listen backlog, worker_connections ve somaxconn ayarlarının artırılması", "B6", "F3"],
            ["6", "Kısmi sonuçlarda 200 yerine açık hata durumu (ör. 503 + eksik modeller listesi) ya da yanıtta \"partial\" bayrağı", "B4", "F1"],
            ["7", "Servis bazında bellek izleme ve sızıntı analizi", "B7", "—"],
        ],
        [1.5 * cm, 9.6 * cm, 2.3 * cm, 3.0 * cm],
    )]

    # 6. Kısıtlar
    S += [P("6. Kısıtlar", "h1")]
    S += bullets([
        "Yük tek bir istemciden (16 GB RAM'li Windows makine, ev internet bağlantısı) üretilmiştir. Bu nedenle 10.000, 25.000 ve 50.000 eşzamanlı "
        "bağlantı kademeleri çalıştırılmamıştır; bu kademeler için ayrı bir Linux yük makinesi gerekmektedir.",
        "Ani bağlantı kademelerindeki reddedilmelerin ne kadarının sunucudan, ne kadarının istemci ağından kaynaklandığı sunucu günlükleriyle "
        "henüz doğrulanmamıştır.",
        "Test, canlı sistem üzerinde yapılmıştır; aynı saatlerde gelen gerçek trafik sonuçlara az miktarda karışmış olabilir.",
        "Tüm ses isteklerinde aynı 150 KB'lık örnek kayıt kullanılmıştır; daha uzun kayıtlar süreleri orantılı olarak artıracaktır.",
        "Sunucu kaynak verileri iki ayrı kayıttan birleştirilmiştir; 14:55–15:03 UTC aralığında kayıt yoktur (Şekil 2'deki boşluk).",
    ])

    doc.build(S, onFirstPage=on_page, onLaterPages=on_page)
    print(f"yazıldı: {out}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--metrics", required=True, type=Path, nargs="+")
    ap.add_argument("--out", type=Path, default=ROOT / "docs" / "DiagVoice_Yuk_Testi_Raporu_2026-11-10.pdf")
    a = ap.parse_args()
    build(a.metrics, a.out)

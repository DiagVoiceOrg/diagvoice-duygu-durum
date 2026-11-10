"""
TOGG analiz akışı (/togg-analyze) performans raporu (PDF).

  python loadtest/report/build_togg_report.py --metrics <sunucu metrik CSV> \
      --run loadtest/results/20261110T153428Z --out docs/DiagVoice_TOGG_Performans_Raporu_2026-11-10.pdf
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import build_report as br  # noqa: E402
from build_report import P, STY, bullets, fs, load_metrics, pct, table, tr_int, window  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
from reportlab.lib import colors  # noqa: E402
from reportlab.lib.pagesizes import A4  # noqa: E402
from reportlab.lib.styles import ParagraphStyle  # noqa: E402
from reportlab.lib.units import cm  # noqa: E402
from reportlab.platypus import Image, KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle  # noqa: E402

ROOT = br.ROOT
TMP = br.TMP
NAVY, GREY, RULE, LIGHT = br.NAVY, br.GREY, br.RULE, br.LIGHT

STAGES = [
    ("togg_1", "1 istek", "15:34:35"),
    ("togg_1_seq", "Tek kullanıcı, art arda (3 dk)", "15:35:43"),
    ("togg_10", "10 kullanıcı (3 dk)", "15:39:51"),
    ("togg_25", "25 kullanıcı (3 dk)", "15:44:00"),
    ("togg_50", "50 kullanıcı (3 dk)", "15:48:12"),
    ("togg_100", "100 kullanıcı (3 dk)", "15:52:26"),
    ("togg_100_burst", "100 istek aynı anda", "15:56:50"),
    ("togg_1000_burst", "1.000 istek aynı anda", "15:58:16"),
    ("togg_5000_burst", "5.000 istek aynı anda", "15:59:56"),
]
LABEL = {k: v for k, v, _ in STAGES}

# /analyze-fused karşılaştırması (aynı gün, aynı sunucu; ilk rapordan)
FUSED_SINGLE_S = 3.34
FUSED_RPS = 0.57
NET_RTT_MS = 54  # istemci → sunucu TCP bağlantı süresi (ölçüm, 5 tekrar ortalaması)


def num(x, d=2):
    return f"{x:.{d}f}".replace(".", ",")


def load(run_dir: Path, stage: str) -> dict | None:
    p = run_dir / f"{stage}.json"
    if not p.is_file():
        return None
    d = json.loads(p.read_text(encoding="utf-8"))
    m = d["metrics"]

    def cnt(k):
        return int(m[k]["values"]["count"]) if k in m else 0

    v = m["http_req_duration"]["values"]
    ok = m.get("ok_duration", {}).get("values", {})
    return {
        "stage": stage,
        "n": cnt("http_reqs"),
        "rps": m["http_reqs"]["values"]["rate"],
        "ok": cnt("status_2xx"),
        "partial": cnt("status_partial"),
        "c5": cnt("status_5xx"),
        "net": cnt("status_network_error"),
        **{q: (v.get(q) or 0) / 1000 for q in ["min", "med", "p(90)", "p(95)", "p(99)", "max"]},
        "ok_med": (ok.get("med") or 0) / 1000 if ok else None,
        "ok_p95": (ok.get("p(95)") or 0) / 1000 if ok else None,
    }


def full_ok(r):
    return r["ok"] - r["partial"]


# --- Grafikler ------------------------------------------------------------------
def chart_scaling(res):
    keys = ["togg_1_seq", "togg_10", "togg_25", "togg_50", "togg_100"]
    xs = [1, 10, 25, 50, 100]
    med = [res[k]["med"] for k in keys]
    p95 = [res[k]["p(95)"] for k in keys]
    rps = [res[k]["rps"] for k in keys]
    fig, ax = plt.subplots(figsize=(7.2, 3.3), dpi=200)
    ax.plot(xs, med, marker="o", color=br.C_GPU, label="Yanıt süresi — medyan")
    ax.plot(xs, p95, marker="s", color="#7C93B2", ls="--", label="Yanıt süresi — p95")
    for x, y in zip(xs, med):
        ax.annotate(f"{num(y, 2 if y < 1 else 1)} sn", (x, y), textcoords="offset points", xytext=(5, 7), fontsize=8, color=br.C_GPU)
    ax.set_xlabel("Eşzamanlı kullanıcı (araç)")
    ax.set_ylabel("Yanıt süresi (sn)")
    ax.set_ylim(0, 22)
    ax.grid(alpha=0.25)
    ax.spines[["top"]].set_visible(False)
    ax2 = ax.twinx()
    ax2.bar(xs, rps, width=4, color=br.C_CPU, alpha=0.25, label="Throughput (istek/sn)")
    ax2.set_ylabel("Throughput (istek/sn)", color="#9A3D3A")
    ax2.set_ylim(0, 8)
    h1, l1 = ax.get_legend_handles_labels()
    h2, l2 = ax2.get_legend_handles_labels()
    ax.legend(h1 + h2, l1 + l2, frameon=False, loc="upper left", fontsize=8)
    fig.tight_layout()
    p = TMP / "togg_scaling.png"
    fig.savefig(p)
    plt.close(fig)
    return p


def chart_single(r):
    qs = [("min", "En iyi"), ("med", "Medyan"), ("p(90)", "p90"), ("p(95)", "p95"), ("p(99)", "p99"), ("max", "En kötü")]
    vals = [r[q] * 1000 for q, _ in qs]
    fig, ax = plt.subplots(figsize=(7.2, 2.6), dpi=200)
    bars = ax.barh([l for _, l in qs][::-1], vals[::-1], color=[br.C_GPU] * 5 + ["#7C93B2"])
    for b, v in zip(bars, vals[::-1]):
        ax.text(v + 6, b.get_y() + b.get_height() / 2, f"{v:.0f} ms", va="center", fontsize=8.5)
    ax.axvline(NET_RTT_MS, color="#999", ls=":", lw=1)
    ax.text(NET_RTT_MS + 4, 5.45, f"ağ gidiş-dönüş ~{NET_RTT_MS} ms", fontsize=7.5, color="#666")
    ax.set_xlim(0, 560)
    ax.set_xlabel("Uçtan uca yanıt süresi (ms) — ağ ve 150 KB yükleme dahil")
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(axis="x", alpha=0.25)
    fig.tight_layout()
    p = TMP / "togg_single.png"
    fig.savefig(p)
    plt.close(fig)
    return p


def chart_resources(win):
    import numpy as np

    labels = [n for n, _ in win]
    cpu = [w["cpu_avg"] for _, w in win]
    gpu = [w["gpu_avg"] for _, w in win]
    x = np.arange(len(labels))
    w_ = 0.38
    fig, ax = plt.subplots(figsize=(7.2, 3.0), dpi=200)
    ax.bar(x - w_ / 2, cpu, w_, color=br.C_CPU, label="CPU (ort. %)")
    ax.bar(x + w_ / 2, gpu, w_, color=br.C_GPU, label="GPU (ort. %)")
    ax.axhline(100, color="#999", lw=0.8, ls=":")
    ax.set_xticks(x, labels, fontsize=8.5)
    ax.set_ylim(0, 105)
    ax.set_ylabel("Kullanım (%)")
    ax.grid(axis="y", alpha=0.25)
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(frameon=False, ncol=2, loc="upper left")
    fig.tight_layout()
    p = TMP / "togg_resources.png"
    fig.savefig(p)
    plt.close(fig)
    return p


# --- Sayfa ----------------------------------------------------------------------
def on_page(canvas, doc):
    canvas.saveState()
    w, h = A4
    canvas.setStrokeColor(RULE)
    canvas.setLineWidth(0.5)
    canvas.line(2 * cm, h - 1.5 * cm, w - 2 * cm, h - 1.5 * cm)
    canvas.setFont("Body", 8.5)
    canvas.setFillColor(GREY)
    canvas.drawString(2 * cm, h - 1.3 * cm, "DiagVoice — TOGG Analiz Akışı Performans Raporu")
    canvas.drawRightString(w - 2 * cm, h - 1.3 * cm, "Gizli — Şirket içi")
    canvas.line(2 * cm, 1.5 * cm, w - 2 * cm, 1.5 * cm)
    canvas.drawString(2 * cm, 1.05 * cm, "10 Kasım 2026")
    canvas.drawRightString(w - 2 * cm, 1.05 * cm, f"Sayfa {doc.page}")
    canvas.restoreState()


def kpi_tiles(items):
    val = ParagraphStyle("kv", fontName="Body-Bold", fontSize=19, leading=22, textColor=NAVY)
    lab = ParagraphStyle("kl", fontName="Body", fontSize=8.5, leading=10.5, textColor=GREY)
    cells = [[Paragraph(v, val), Spacer(1, 2), Paragraph(l, lab)] for v, l in items]
    t = Table([cells], colWidths=[16.4 * cm / len(items)] * len(items))
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), LIGHT),
        ("LINEBEFORE", (1, 0), (-1, -1), 2, colors.white),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 8), ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
        ("LEFTPADDING", (0, 0), (-1, -1), 9),
    ]))
    return t


def build(metrics: Path, run_dir: Path, out: Path):
    br.register_fonts()
    br.styles()
    TMP.mkdir(parents=True, exist_ok=True)

    res = {k: load(run_dir, k) for k, _, _ in STAGES}
    res = {k: v for k, v in res.items() if v}
    rows = load_metrics(metrics)
    day = rows[0]["t"].date()
    T = lambda hms: datetime.combine(day, datetime.strptime(hms, "%H:%M:%S").time())  # noqa: E731

    W = [
        ("Boşta", "15:34:05", "15:34:34"),
        ("Tek kullanıcı", "15:35:43", "15:38:43"),
        ("10 kullanıcı", "15:39:51", "15:42:51"),
        ("25 kullanıcı", "15:44:00", "15:47:00"),
        ("50 kullanıcı", "15:48:12", "15:51:12"),
        ("100 kullanıcı", "15:52:26", "15:55:26"),
    ]
    win = [(n, window(rows, T(a), T(b))) for n, a, b in W]
    win = [(n, w) for n, w in win if w]
    wd = dict(win)
    pw = {}
    for n, a, b in W:
        s = [r for r in rows if T(a) <= r["t"] < T(b)]
        pw[n] = sum(r.get("power", 0) for r in s) / len(s) if s and "power" in s[0] else None

    single = res["togg_1_seq"]
    sat_rps = max(res[k]["rps"] for k in ["togg_10", "togg_25", "togg_50", "togg_100"])
    su = wd.get("Tek kullanıcı")
    gpu_s_per_req = su["gpu_avg"] / 100 / single["rps"] if su else None
    cpu_cs_per_req = su["cpu_avg"] / 100 * 4 / single["rps"] if su else None

    p_single = chart_single(single)
    p_scale = chart_scaling(res)
    p_res = chart_resources(win)

    doc = SimpleDocTemplate(
        str(out), pagesize=A4, leftMargin=2 * cm, rightMargin=2 * cm, topMargin=2.1 * cm, bottomMargin=2 * cm,
        title="DiagVoice TOGG Analiz Akışı Performans Raporu", author="DiagVoice", subject="/togg-analyze — 10 Kasım 2026",
    )
    S = []

    # Başlık
    S += [Spacer(1, 0.8 * cm), P("TOGG Analiz Akışı Performans Raporu", "title"),
          P("Ses emosyonu ve WURSS — /togg-analyze uç noktası", "subtitle"), Spacer(1, 0.5 * cm)]
    meta = [
        ["Test tarihi", "10 Kasım 2026, 15:34–16:01 UTC (18:34–19:01 TSİ)"],
        ["Test edilen akış", "POST /togg-analyze — 2 model, paralel çalışma"],
        ["Ölçüm ortamı", "AWS g4dn.xlarge: 4 vCPU, 16 GB RAM, NVIDIA T4 (16 GB); doğrudan sunucu bağlantısı"],
        ["Kod sürümü", "feat/prod-hardening, commit 3c255ad"],
        ["Araç", "Grafana k6 2.3.0; sunucuda 1 sn aralıklı CPU/GPU/RAM/güç kaydı"],
        ["Belge durumu", "Sürüm 1.0 — Şirket içi"],
    ]
    mt = Table([[P(f"<b>{a}</b>", "meta"), P(b, "meta")] for a, b in meta], colWidths=[3.6 * cm, 12.8 * cm], hAlign="LEFT")
    mt.setStyle(TableStyle([("LINEBELOW", (0, 0), (-1, -1), 0.4, RULE), ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
    S += [mt, Spacer(1, 0.6 * cm)]

    # 1. Özet
    S += [P("1. Yönetici özeti", "h1")]
    S += [kpi_tiles([
        (f"{single['med'] * 1000:.0f} ms", "Tek kullanıcı medyan yanıt süresi (ağ dahil)"),
        (f"{single['p(95)'] * 1000:.0f} ms", f"p95 — {tr_int(single['n'])} istekte"),
        ("~760 MB", "İki modelin toplam boyutu"),
        (f"{num(sat_rps, 1)} /sn", "Tek sunucuda en yüksek analiz hızı"),
    ]), Spacer(1, 8)]
    S += bullets([
        f"<b>Tek kullanıcı senaryosunda</b> (araç içi kullanım) analiz sonucu uçtan uca <b>{single['med'] * 1000:.0f} ms</b>'de dönmektedir; "
        f"3 dakika boyunca art arda gönderilen {tr_int(single['n'])} isteğin tamamı eksiksiz sonuçlanmış, en kötü yanıt {single['max'] * 1000:.0f} ms olmuştur. "
        "Ölçüm ağ gidiş-dönüşü ve ses dosyası yüklemesini içerir; sunucu tarafı işlem süresi bunun altındadır.",
        f"<b>Akış hafiftir:</b> iki base boyutlu ses modeli (WavLM ve Wav2Vec2, toplam ~760 MB) kullanılır, konuşma tanıma (STT) yoktur. "
        f"Tüm modelleri çalıştıran genel analize göre <b>{FUSED_SINGLE_S / single['med']:.0f} kat daha hızlıdır</b>.",
        (f"<b>Analiz başına donanım maliyeti düşüktür:</b> yaklaşık <b>{num(gpu_s_per_req)} GPU-saniye</b> ve <b>{num(cpu_cs_per_req, 1)} CPU çekirdek-saniye</b>."
         if gpu_s_per_req else "Analiz başına donanım maliyeti düşüktür."),
        f"<b>Tek sunucu 100 eşzamanlı kullanıcıya kadar hatasız</b> çalışmıştır (toplam {tr_int(sum(res[k]['n'] for k in ['togg_10','togg_25','togg_50','togg_100']))} istek, "
        f"sıfır hata). En yüksek hız saniyede ~{num(sat_rps, 1)} analizdir (saatte ~{tr_int(int(round(sat_rps * 3600, -2)))}).",
        "<b>Donanım tam yükte bile doymamaktadır</b> (CPU ~%60, GPU ~%39). Kapasite sınırı donanımdan değil, servislerin istekleri sırayla "
        "işlemesinden kaynaklanmaktadır; aynı donanımda artırılabilir.",
        "<b>Sınır:</b> 1.000 ve üzeri <i>aynı anda</i> gelen istekte sistem hata vermeye başlamakta, bir kısım yanıt modellerden biri eksik "
        "olarak dönmektedir. Bu durum bulut senaryosuna aittir; araç içi tek kullanıcı kullanımını etkilemez.",
    ])

    # 2. Kapsam
    S += [P("2. Amaç ve kapsam", "h1")]
    S += [P(
        "Bu çalışmanın amacı, TOGG araç senaryosunda kullanılan analiz akışının performansını ölçmek ve modellerin kısıtlı donanıma "
        "(gömülü/araç içi sistemler) taşınabilirliğine dair veri üretmektir. Araç içi kullanımda tek bir kullanıcı vardır; bu nedenle "
        "birincil metrik <b>tek kullanıcı yanıt süresi</b>, ikincil metrik ise aynı akışın bulut üzerinden birden fazla araca hizmet "
        "verdiği senaryoda <b>sunucu kapasitesidir</b>."
    )]
    S += [KeepTogether([P("2.1 Akıştaki modeller", "h2"), table(
        ["Görev", "Model", "Mimari", "Boyut"],
        [
            ["Ses emosyonu", "voice_to_sentiment (wavlm_v6_multicrop_ema)", "WavLM Base Plus + dikkat havuzlama, 4 sınıf", "381 MB"],
            ["WURSS (sağlık sinyali)", "disease_service (usye)", "Wav2Vec2 Base, ses sınıflandırma (sağlıklı / hasta)", "378 MB"],
        ],
        [3.2 * cm, 5.0 * cm, 6.1 * cm, 2.1 * cm],
    )])]
    S += [P(
        "İki model aynı ses kaydı üzerinde <b>paralel</b> çalışır; yanıt her iki modelin sonucunu içerir. Boyutlar disk üzerindeki ağırlık "
        "dosyalarıdır (FP32). Akışta konuşma tanıma (Whisper vb.) bulunmamaktadır.",
        "small",
    )]
    S += [P("2.2 Yöntem", "h2")]
    S += bullets([
        "Her istekte aynı 150 KB'lık Türkçe ses kaydı (m4a) gönderilmiştir.",
        "<b>Tek kullanıcı:</b> 1 sanal kullanıcı, 3 dakika boyunca bir önceki yanıtı aldıktan hemen sonra yeni istek gönderir.",
        "<b>Eşzamanlı kullanıcı:</b> N kullanıcı 3 dakika boyunca aynı şekilde istek gönderir. <b>Ani yük:</b> N istek aynı anda başlatılır.",
        "Her yanıtın içeriği kontrol edilmiştir: HTTP 200 dönüp modellerden birinin sonucu boş olan yanıtlar <b>kısmi</b> olarak ayrıca sayılmıştır.",
        f"İstekler CDN (Cloudflare) atlanarak doğrudan sunucuya gönderilmiştir. İstemci–sunucu ağ gidiş-dönüşü ~{NET_RTT_MS} ms'dir.",
        "Hata oranı 30 saniye sonra %50'yi aşan kademe otomatik durdurulmuştur.",
    ])

    # 3. Sonuçlar
    S += [P("3. Sonuçlar", "h1"), P("3.1 Tek kullanıcı yanıt süresi (araç senaryosu)", "h2")]
    S += [KeepTogether([Image(str(p_single), width=16.4 * cm, height=5.9 * cm),
                        P(f"Şekil 1 — Tek kullanıcı, {tr_int(single['n'])} ardışık istek: yanıt süresi dağılımı", "caption")])]
    S += [P(
        f"Yanıt süreleri dar bir aralıkta toplanmaktadır: isteklerin %90'ı {single['p(90)'] * 1000:.0f} ms, %99'u {single['p(99)'] * 1000:.0f} ms "
        f"içinde tamamlanmıştır. Tek istekte ölçülen {res['togg_1']['med'] * 1000:.0f} ms, yeni bağlantı kurulumunu (TCP + TLS) içerdiği için "
        "ardışık isteklerden yüksektir. Hiçbir istekte hata veya eksik sonuç oluşmamıştır."
    )]

    S += [P("3.2 Eşzamanlı kullanıcı ve sunucu kapasitesi (bulut senaryosu)", "h2")]
    hdr = ["Kademe", "İstek", "Tam sonuç", "Kısmi", "5xx", "Bağlantı hatası", "Medyan", "p95", "İstek/sn"]
    trows = []
    for k, _, _ in STAGES:
        r = res.get(k)
        if not r:
            continue
        trows.append([
            LABEL[k], tr_int(r["n"]), f"{tr_int(full_ok(r))} ({pct(full_ok(r), r['n'])})", tr_int(r["partial"]), tr_int(r["c5"]),
            tr_int(r["net"]), fs(r["med"]) if r["med"] else "–", fs(r["p(95)"]), num(r["rps"]),
        ])
    S += [table(hdr, trows, [4.0 * cm, 1.3 * cm, 2.4 * cm, 1.1 * cm, 1.1 * cm, 1.7 * cm, 1.5 * cm, 1.5 * cm, 1.8 * cm])]
    S += [P(
        "1.000 ve 5.000 isteklik kademeler hata oranı eşiği nedeniyle ~30 saniyede durdurulmuştur; tabloda durdurma anına kadar gönderilen "
        "istekler yer almaktadır.",
        "small",
    ), Spacer(1, 4)]
    S += [KeepTogether([Image(str(p_scale), width=16.4 * cm, height=7.5 * cm),
                        P("Şekil 2 — Eşzamanlı kullanıcı sayısına göre yanıt süresi ve throughput", "caption")])]
    S += [P(
        f"Throughput 10 kullanıcıda saniyede {num(res['togg_10']['rps'], 1)} analize ulaşıp sabit kalmaktadır. Bu noktadan sonra yanıt süresi "
        "kullanıcı sayısıyla doğrusal artar (100 kullanıcıda medyan "
        f"{num(res['togg_100']['med'], 0)} sn). 10 eşzamanlı kullanıcıya kadar yanıt süresi 2 saniyenin altındadır."
    )]

    # 3.3 Kaynak
    S += [P("3.3 Sunucu kaynak kullanımı", "h2")]
    S += [table(
        ["Dönem", "CPU ort.", "GPU ort.", "Load (en yüksek, 4 vCPU)", "Boş RAM (en düşük)", "VRAM (en yüksek)"],
        [[n, f"%{w['cpu_avg']:.0f}", f"%{w['gpu_avg']:.0f}", num(w["load_max"], 1), f"{num(w['avail_min'], 1)} GB", f"{num(w['vram_max'], 1)} / 15 GB"] for n, w in win],
        [3.8 * cm, 1.9 * cm, 1.9 * cm, 3.6 * cm, 2.7 * cm, 2.5 * cm],
    ), Spacer(1, 6)]
    S += [KeepTogether([Image(str(p_res), width=16.4 * cm, height=6.8 * cm),
                        P("Şekil 3 — Yük kademelerine göre ortalama CPU ve GPU kullanımı", "caption")])]
    if gpu_s_per_req:
        S += [KeepTogether([P("Analiz başına donanım maliyeti", "h2"), table(
            ["Kaynak", "Analiz başına", "Hesaplama"],
            [
                ["GPU zamanı (T4)", f"~{num(gpu_s_per_req)} sn", f"Tek kullanıcıda ort. GPU %{su['gpu_avg']:.0f} ÷ {num(single['rps'], 1)} analiz/sn"],
                ["CPU zamanı", f"~{num(cpu_cs_per_req, 1)} çekirdek-sn", f"Ort. CPU %{su['cpu_avg']:.0f} × 4 vCPU ÷ {num(single['rps'], 1)} analiz/sn"],
                ["Model ağırlıkları", "~760 MB", "İki modelin disk boyutu (FP32)"],
            ],
            [3.6 * cm, 3.2 * cm, 9.6 * cm],
        )])]
        S += [P(
            "Bu değerler sunucudaki tüm servislerin toplam kullanımından türetilmiş üst sınır tahminleridir; GPU belleği (VRAM) sunucuda "
            "yüklü olan diğer modelleri de içerdiğinden akışa ait bellek ayrıca ölçülmelidir.",
            "small",
        )]

    # 4. Değerlendirme
    S += [P("4. Gömülü / araç içi kullanım için değerlendirme", "h1")]
    S += [P("4.1 Ölçümlerin desteklediği", "h2")]
    S += bullets([
        f"Akış tek kullanıcıda <b>{single['med'] * 1000:.0f} ms</b> gibi etkileşimli kullanıma uygun bir sürede ve çok düşük sapmayla "
        f"(p99 {single['p(99)'] * 1000:.0f} ms) yanıt vermektedir.",
        "Modeller base boyutludur (~95 milyon parametre/model) ve toplam ağırlık ~760 MB'tır; bu ölçek, güncel araç ve gömülü "
        "yapay zekâ platformlarının bellek bütçesine sığabilecek düzeydedir.",
        "Analiz başına GPU ve CPU maliyeti düşüktür; sunucu tam yükte dahi doymamıştır.",
        "Akış kararlıdır: tek kullanıcı ve 100 kullanıcıya kadar olan tüm kademelerde sıfır hata ve sıfır eksik sonuç.",
    ])
    S += [P("4.2 Henüz ölçülmeyen", "h2")]
    S += bullets([
        "Ölçümler veri merkezi sınıfı bir GPU (NVIDIA T4) üzerinde yapılmıştır. Araç donanımındaki gerçek yanıt süresi, hedef platformda "
        "(ör. NVIDIA Jetson Orin veya araç SoC'si) ayrı bir ölçümle doğrulanmalıdır.",
        "Akışa ait bellek (RAM/VRAM) tek başına ölçülmemiştir; sunucuda diğer modeller de yüklüdür.",
        "Uzun süreli çalışmada bellek davranışı: sunucunun boş RAM'i gün boyunca azalmış ve yük bittikten sonra geri gelmemiştir. "
        "Saatlerce açık kalacak bir araç sistemi için bu davranış servis bazında incelenmelidir.",
        "Model sıkıştırma (FP16/INT8 nicemleme, ONNX/TensorRT) uygulanmamıştır; bu teknikler gömülü platformda süre ve belleği ayrıca düşürebilir.",
    ])

    # 5. Öneriler
    S += [KeepTogether([P("5. Sonraki adımlar", "h1"), table(
        ["No", "Adım", "Amaç"],
        [
            ["1", "Akışı yalnızca bu iki modelle, kısıtlı kaynaklı bir konteynerde (ör. 4 çekirdek, 8 GB, yalnız CPU) ölçmek", "Gömülü donanım öncesi hızlı tahmin"],
            ["2", "Hedef platformda (ör. Jetson Orin) uçtan uca süre, bellek ve güç ölçümü", "Sunum için doğrulanmış araç içi sayılar"],
            ["3", "FP16/INT8 nicemleme ve ONNX/TensorRT dönüşümü", "Süre ve belleği düşürmek"],
            ["4", "2–3 saatlik tek kullanıcı dayanıklılık testi, servis bazında bellek izleme", "Uzun süreli kararlılık"],
            ["5", "Bulut tarafı: servislerde birden fazla worker / istek gruplama; eşzamanlılık sınırı ve rate limit", "Kapasite ve aşırı yük koruması"],
            ["6", "Kısmi sonuçta açık hata durumu (200 yerine 503 veya yanıtta \"partial\" bayrağı)", "Eksik sonucun fark edilmesi"],
        ],
        [1.0 * cm, 10.2 * cm, 5.2 * cm],
    )])]

    # 6. Kısıtlar
    S += [P("6. Kısıtlar", "h1")]
    S += bullets([
        "Yük tek bir istemciden (Windows, ev internet bağlantısı) üretilmiştir; 10.000 ve üzeri eşzamanlı istek kademeleri çalıştırılmamıştır.",
        "Ani yük kademelerindeki bağlantı hatalarının bir kısmı istemci ağından kaynaklanıyor olabilir.",
        "Test, canlı sistem üzerinde yapılmıştır. TOGG yanıtlarında kullanılan skor çeşitlendirme (diversify) katmanı açıktır; bu katman "
        "süreyi değil, yalnızca skor değerlerini etkiler.",
        "Tüm isteklerde aynı kısa ses kaydı kullanılmıştır; daha uzun kayıtlarda süreler artacaktır.",
    ])
    S += [Spacer(1, 6), P(
        f"Karşılaştırma: aynı gün aynı sunucuda ölçülen genel analiz (/analyze-fused; konuşma tanıma dahil tüm modeller) tek istekte "
        f"{num(FUSED_SINGLE_S)} sn, en yüksek hızda saniyede {num(FUSED_RPS)} analiz yapmıştır. Ayrıntılar: DiagVoice API Yük Testi Raporu (10 Kasım 2026).",
        "small",
    )]

    doc.build(S, onFirstPage=on_page, onLaterPages=on_page)
    print(f"yazıldı: {out}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--metrics", required=True, type=Path)
    ap.add_argument("--run", type=Path, default=ROOT / "loadtest" / "results" / "20261110T153428Z")
    ap.add_argument("--out", type=Path, default=ROOT / "docs" / "DiagVoice_TOGG_Performans_Raporu_2026-11-10.pdf")
    a = ap.parse_args()
    build(a.metrics, a.run, a.out)

"""
Fontevia Ankara 90 Günlük Su Göstergesi — Analiz & Grafik Modülü
================================================================

7 türetilmiş gösterge hesaplar ve 4 standart grafik üretir.

Kullanım:
    python analyze.py                     # grafikler output/ klasörüne
    python analyze.py --days 90           # analiz penceresi
    python analyze.py --out my_charts/    # çıktı klasörü
    python analyze.py --summary           # sadece metin özet, grafik yok
"""

import argparse
import csv
import json
import logging
import os
from datetime import date, timedelta
from pathlib import Path

import matplotlib
matplotlib.use("Agg")  # headless (sunucu) ortamı için
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import matplotlib.ticker as mticker
import numpy as np

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

# ---------------------------------------------------------------------------
# Sabitler ve stil
# ---------------------------------------------------------------------------

DATA_DIR = Path(__file__).parent / "data"
CSV_PATH = DATA_DIR / "aski_ankara_daily.csv"
OUTPUT_DIR = Path(__file__).parent / "output"

# Renk paleti (Fontevia marka renklerine uyarlanabilir)
COLORS = {
    "aktif_su":     "#1565C0",   # koyu mavi
    "gelen":        "#2E7D32",   # yeşil
    "sehir":        "#B71C1C",   # kırmızı
    "denge":        "#6A1B9A",   # mor
    "camlidere":    "#0277BD",
    "kurtbogazi":   "#00838F",
    "egerekkaya":   "#558B2F",
    "akyar":        "#EF6C00",
    "kesikkopru":   "#6D4C41",
    "grid":         "#E0E0E0",
    "bg":           "#FAFAFA",
}

MILYON = 1_000_000  # m³ → milyon m³ dönüşümü


# ---------------------------------------------------------------------------
# Veri yükleme
# ---------------------------------------------------------------------------

def load_data(days: int = 90) -> list[dict]:
    """CSV'den son N günlük veri seti döndür."""
    if not CSV_PATH.exists():
        raise FileNotFoundError(f"CSV bulunamadı: {CSV_PATH}")

    cutoff = date.today() - timedelta(days=days)
    rows = []

    with CSV_PATH.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                d = date.fromisoformat(row["tarih"])
                if d >= cutoff:
                    rows.append({**row, "_date": d})
            except (ValueError, KeyError):
                continue

    rows.sort(key=lambda r: r["_date"])
    log.info("%d günlük veri yüklendi (son %d gün)", len(rows), days)
    return rows


def to_float(val) -> float | None:
    """CSV'deki string değeri float'a güvenli çevir."""
    try:
        v = float(val)
        return v if v > 0 else None
    except (ValueError, TypeError):
        return None


def extract_series(rows: list[dict], key: str, scale: float = 1.0) -> tuple[list, list]:
    """Tarihleri ve değerleri çıkar, boş kayıtları atla."""
    dates, vals = [], []
    for r in rows:
        v = to_float(r.get(key))
        if v is not None:
            dates.append(r["_date"])
            vals.append(v / scale)
    return dates, vals


def moving_average(vals: list[float], window: int = 7) -> list[float | None]:
    """Basit hareketli ortalama (eksik değerlerde None)."""
    result = []
    for i in range(len(vals)):
        window_vals = [v for v in vals[max(0, i - window + 1):i + 1] if v is not None]
        result.append(np.mean(window_vals) if window_vals else None)
    return result


# ---------------------------------------------------------------------------
# Gösterge hesapları
# ---------------------------------------------------------------------------

def compute_indicators(rows: list[dict]) -> dict:
    """
    7 temel göstergeyi hesapla.
    Tüm değerler m³ cinsinden saklanır (gösterimde milyon m³'e çevrilir).
    """
    if not rows:
        return {}

    def num(r, k):
        return to_float(r.get(k))

    latest = rows[-1]
    today = latest["_date"]

    # 1. Aktif rezerv (bugün)
    S_t = num(latest, "aktif_su_m3")

    # 2. 90 günlük rezerv değişimi
    oldest = rows[0]
    S_t90 = num(oldest, "aktif_su_m3")
    delta_90 = (S_t - S_t90) if (S_t and S_t90) else None

    # 3. 90 günlük toplam giriş
    giris_vals = [num(r, "barajlara_gelen_m3_gun") for r in rows]
    giris_vals = [v for v in giris_vals if v]
    q_in_90 = sum(giris_vals) if giris_vals else None

    # 4. 90 günlük kentsel su arzı
    sehir_vals = [num(r, "sehre_verilen_m3_gun") for r in rows]
    sehir_vals_clean = [v for v in sehir_vals if v]
    q_city_90 = sum(sehir_vals_clean) if sehir_vals_clean else None

    # 5. Giriş / kullanım oranı
    r90 = (q_in_90 / q_city_90) if (q_in_90 and q_city_90) else None

    # 6. 30 günlük ortalama talebe göre teorik rezerv (gün)
    rows_30 = rows[-30:] if len(rows) >= 30 else rows
    sehir_30 = [num(r, "sehre_verilen_m3_gun") for r in rows_30]
    sehir_30 = [v for v in sehir_30 if v]
    q_city_30_avg = np.mean(sehir_30) if sehir_30 else None
    teorik_gun = (S_t / q_city_30_avg) if (S_t and q_city_30_avg) else None

    # 7. Geçen yıl aynı gün farkı
    gecen_yil = num(latest, "gecen_yil_aktif_su_m3")
    yillik_fark = (S_t - gecen_yil) if (S_t and gecen_yil) else None

    # 8. Kümülatif denge (her gün için giriş - çıkış farkının kümülatif toplamı)
    cumulative = []
    running = 0.0
    cum_dates = []
    for r in rows:
        g = num(r, "barajlara_gelen_m3_gun") or 0
        s = num(r, "sehre_verilen_m3_gun") or 0
        if g or s:
            running += (g - s)
            cumulative.append(running)
            cum_dates.append(r["_date"])

    return {
        "tarih": today.isoformat(),
        "veri_gunu": len(rows),
        # Göstergeler
        "aktif_rezerv_m3": S_t,
        "aktif_rezerv_milyon_m3": S_t / MILYON if S_t else None,
        "delta_90_m3": delta_90,
        "delta_90_milyon_m3": delta_90 / MILYON if delta_90 else None,
        "q_in_90_m3": q_in_90,
        "q_city_90_m3": q_city_90,
        "r90": r90,
        "teorik_gun": teorik_gun,
        "yillik_fark_m3": yillik_fark,
        "yillik_fark_milyon_m3": yillik_fark / MILYON if yillik_fark else None,
        "gecen_yil_aktif_su_m3": gecen_yil,
        # Seriler (grafik için)
        "_cumulative": cumulative,
        "_cum_dates": cum_dates,
        "_latest": latest,
    }


# ---------------------------------------------------------------------------
# Grafik 1: Aktif Kullanılabilir Su (90 gün)
# ---------------------------------------------------------------------------

def plot_aktif_su(rows: list[dict], indicators: dict, out_dir: Path) -> Path:
    dates, vals = extract_series(rows, "aktif_su_m3", scale=MILYON)
    if not dates:
        log.warning("Grafik 1: Veri yok")
        return None

    fig, ax = plt.subplots(figsize=(12, 5))
    fig.patch.set_facecolor(COLORS["bg"])
    ax.set_facecolor(COLORS["bg"])

    ax.plot(dates, vals, color=COLORS["aktif_su"], linewidth=2.5, label="Aktif Kullanılabilir Su")
    ax.fill_between(dates, vals, alpha=0.12, color=COLORS["aktif_su"])

    # Değişim annotasyonları
    ind = indicators
    if ind.get("delta_90_milyon_m3") is not None:
        d90 = ind["delta_90_milyon_m3"]
        sign = "+" if d90 >= 0 else ""
        ax.annotate(
            f"90 gün: {sign}{d90:.1f} M m³",
            xy=(dates[-1], vals[-1]),
            xytext=(-15, 20),
            textcoords="offset points",
            fontsize=9, color=COLORS["aktif_su"],
            arrowprops=dict(arrowstyle="->", color=COLORS["aktif_su"]),
        )

    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d %b"))
    ax.xaxis.set_major_locator(mdates.WeekdayLocator(byweekday=0))
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{x:.0f}"))
    ax.set_xlabel("Tarih", fontsize=10)
    ax.set_ylabel("Aktif Kullanılabilir Su (Milyon m³)", fontsize=10)
    ax.set_title("Ankara Aktif Su Rezervi — Son 90 Gün", fontsize=13, fontweight="bold", pad=12)
    ax.grid(axis="y", color=COLORS["grid"], linewidth=0.8)
    ax.legend(fontsize=9)
    ax.tick_params(axis="x", rotation=30)

    # Son değer etiketi
    if vals:
        ax.text(dates[-1], vals[-1], f" {vals[-1]:.1f}", fontsize=9,
                va="center", color=COLORS["aktif_su"], fontweight="bold")

    _add_footer(ax)
    plt.tight_layout()
    path = out_dir / "01_aktif_su_90gun.png"
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    log.info("Grafik 1 kaydedildi: %s", path)
    return path


# ---------------------------------------------------------------------------
# Grafik 2: Giriş ve Şehir Su Arzı (7 günlük MA)
# ---------------------------------------------------------------------------

def plot_giris_arz(rows: list[dict], out_dir: Path) -> Path:
    g_dates, g_vals = extract_series(rows, "barajlara_gelen_m3_gun", scale=MILYON)
    s_dates, s_vals = extract_series(rows, "sehre_verilen_m3_gun", scale=MILYON)

    if not g_vals and not s_vals:
        log.warning("Grafik 2: Veri yok")
        return None

    fig, ax = plt.subplots(figsize=(12, 5))
    fig.patch.set_facecolor(COLORS["bg"])
    ax.set_facecolor(COLORS["bg"])

    # Ham veri (şeffaf)
    if g_vals:
        ax.bar(g_dates, g_vals, color=COLORS["gelen"], alpha=0.2, width=0.8, label="Günlük Giriş")
    if s_vals:
        ax.bar(s_dates, s_vals, color=COLORS["sehir"], alpha=0.2, width=0.8, label="Günlük Şehir Arzı")

    # 7 günlük hareketli ortalama (ana çizgi)
    if g_vals and len(g_vals) >= 3:
        g_ma = moving_average(g_vals, window=7)
        valid_g = [(d, v) for d, v in zip(g_dates, g_ma) if v is not None]
        if valid_g:
            gd, gv = zip(*valid_g)
            ax.plot(gd, gv, color=COLORS["gelen"], linewidth=2.5, label="7 Günlük Ort. Giriş")

    if s_vals and len(s_vals) >= 3:
        s_ma = moving_average(s_vals, window=7)
        valid_s = [(d, v) for d, v in zip(s_dates, s_ma) if v is not None]
        if valid_s:
            sd, sv = zip(*valid_s)
            ax.plot(sd, sv, color=COLORS["sehir"], linewidth=2.5,
                    linestyle="--", label="7 Günlük Ort. Şehir Arzı")

    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d %b"))
    ax.xaxis.set_major_locator(mdates.WeekdayLocator(byweekday=0))
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{x:.2f}"))
    ax.set_xlabel("Tarih", fontsize=10)
    ax.set_ylabel("Milyon m³/gün", fontsize=10)
    ax.set_title("Baraj Girişi ve Şehir Su Arzı — Son 90 Gün (7 Günlük Ort.)",
                 fontsize=13, fontweight="bold", pad=12)
    ax.grid(axis="y", color=COLORS["grid"], linewidth=0.8)
    ax.legend(fontsize=9)
    ax.tick_params(axis="x", rotation=30)
    _add_footer(ax)
    plt.tight_layout()

    path = out_dir / "02_giris_arz_90gun.png"
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    log.info("Grafik 2 kaydedildi: %s", path)
    return path


# ---------------------------------------------------------------------------
# Grafik 3: Kümülatif İşletme Dengesi
# ---------------------------------------------------------------------------

def plot_kumülatif_denge(indicators: dict, out_dir: Path) -> Path:
    cum_dates = indicators.get("_cum_dates", [])
    cumulative = indicators.get("_cumulative", [])

    if not cum_dates:
        log.warning("Grafik 3: Veri yok")
        return None

    cum_milyon = [v / MILYON for v in cumulative]

    fig, ax = plt.subplots(figsize=(12, 5))
    fig.patch.set_facecolor(COLORS["bg"])
    ax.set_facecolor(COLORS["bg"])

    colors_bar = [COLORS["gelen"] if v >= 0 else COLORS["sehir"] for v in cum_milyon]
    ax.bar(cum_dates, cum_milyon, color=colors_bar, alpha=0.75, width=0.8)
    ax.axhline(0, color="#555", linewidth=1.2, linestyle="-")

    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d %b"))
    ax.xaxis.set_major_locator(mdates.WeekdayLocator(byweekday=0))
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{x:+.1f}"))
    ax.set_xlabel("Tarih", fontsize=10)
    ax.set_ylabel("Kümülatif Giriş − Çıkış (Milyon m³)", fontsize=10)
    ax.set_title(
        "Basitleştirilmiş İşletme Dengesi — Son 90 Gün\n"
        "⚠ Gerçek rezervuar kütle dengesi değildir; yalnızca operasyonel baskı göstergesidir",
        fontsize=11, fontweight="bold", pad=12
    )
    ax.grid(axis="y", color=COLORS["grid"], linewidth=0.8)
    ax.tick_params(axis="x", rotation=30)
    _add_footer(ax)
    plt.tight_layout()

    path = out_dir / "03_kumülatif_denge_90gun.png"
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    log.info("Grafik 3 kaydedildi: %s", path)
    return path


# ---------------------------------------------------------------------------
# Grafik 4: Baraj Bazında Doluluk (Çubuk)
# ---------------------------------------------------------------------------

BARAJ_LABELS = {
    "camlidere":  "Çamlıdere",
    "kurtbogazi": "Kurtboğazı",
    "egerekkaya": "Eğrekkaya",
    "akyar":      "Akyar",
    "kesikkopru": "Kesikköprü",
    "palas":      "Palas",
    "cubuk1":     "Çubuk 1",
    "cubuk2":     "Çubuk 2",
}

BARAJ_COLORS = [
    COLORS["camlidere"], COLORS["kurtbogazi"], COLORS["egerekkaya"],
    COLORS["akyar"], COLORS["kesikkopru"], "#78909C", "#90A4AE", "#B0BEC5",
]


def plot_baraj_durumu(indicators: dict, out_dir: Path) -> Path:
    latest = indicators.get("_latest", {})
    if not latest:
        log.warning("Grafik 4: Veri yok")
        return None

    names, pcts, m3s = [], [], []
    for key, label in BARAJ_LABELS.items():
        pct = to_float(latest.get(f"{key}_pct"))
        m3 = to_float(latest.get(f"{key}_m3"))
        if pct is not None:
            names.append(label)
            pcts.append(pct)
            m3s.append(m3 / MILYON if m3 else 0)

    if not names:
        log.warning("Grafik 4: Baraj verisi bulunamadı")
        return None

    fig, ax = plt.subplots(figsize=(12, 5))
    fig.patch.set_facecolor(COLORS["bg"])
    ax.set_facecolor(COLORS["bg"])

    x = np.arange(len(names))
    bar_colors = BARAJ_COLORS[:len(names)]

    bars = ax.bar(x, pcts, color=bar_colors, alpha=0.85, width=0.55, edgecolor="white")

    # Değer etiketleri
    for bar, pct, m3 in zip(bars, pcts, m3s):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height() + 0.8,
            f"%{pct:.1f}\n({m3:.0f} M m³)",
            ha="center", va="bottom", fontsize=8.5, fontweight="bold"
        )

    ax.set_xticks(x)
    ax.set_xticklabels(names, fontsize=10)
    ax.set_ylim(0, 115)
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"%{v:.0f}"))
    ax.set_ylabel("Doluluk Oranı (%)", fontsize=10)
    ax.set_title(
        f"Baraj Bazında Doluluk — {latest.get('tarih', '')}",
        fontsize=13, fontweight="bold", pad=12
    )
    ax.grid(axis="y", color=COLORS["grid"], linewidth=0.8)
    ax.axhline(100, color="#555", linewidth=0.8, linestyle="--")
    _add_footer(ax)
    plt.tight_layout()

    path = out_dir / "04_baraj_durumu.png"
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    log.info("Grafik 4 kaydedildi: %s", path)
    return path


# ---------------------------------------------------------------------------
# Metin özeti (LinkedIn paylaşımı için taslak)
# ---------------------------------------------------------------------------

def generate_summary(indicators: dict) -> str:
    """Haftalık LinkedIn paylaşımı için metin özeti üret."""
    ind = indicators
    lines = [
        "━━━ ANKARA SU GÖSTERGESİ | Son 90 Gün ━━━",
        "",
    ]

    if ind.get("aktif_rezerv_milyon_m3"):
        aktif_doluluk = to_float(ind.get("_latest", {}).get("aktif_doluluk_pct"))
        lines.append(f"📦 Aktif Rezerv: {ind['aktif_rezerv_milyon_m3']:.1f} M m³"
                     + (f" (%{aktif_doluluk:.1f})" if aktif_doluluk else ""))

    if ind.get("delta_90_milyon_m3") is not None:
        d = ind["delta_90_milyon_m3"]
        emoji = "📈" if d >= 0 else "📉"
        sign = "+" if d >= 0 else ""
        lines.append(f"{emoji} 90 Günlük Rezerv Değişimi: {sign}{d:.1f} M m³")

    rows_30 = ind.get("veri_gunu", 0)
    if ind.get("q_in_90_m3") and ind.get("veri_gunu", 0) >= 7:
        avg_in = ind["q_in_90_m3"] / MILYON / ind["veri_gunu"]
        lines.append(f"💧 Ort. Günlük Baraj Girişi: {avg_in:.3f} M m³/gün")

    if ind.get("q_city_90_m3") and ind.get("veri_gunu", 0) >= 7:
        avg_city = ind["q_city_90_m3"] / MILYON / ind["veri_gunu"]
        lines.append(f"🏙️ Ort. Günlük Şehir Arzı:  {avg_city:.3f} M m³/gün")

    if ind.get("r90") is not None:
        r = ind["r90"]
        durum = "✅ Giriş > Kullanım" if r >= 1 else "⚠️ Sistem rezerv tüketiyor"
        lines.append(f"⚖️ Giriş/Kullanım Oranı: {r:.2f}  →  {durum}")

    if ind.get("yillik_fark_milyon_m3") is not None:
        yf = ind["yillik_fark_milyon_m3"]
        sign = "+" if yf >= 0 else ""
        lines.append(f"📅 Geçen Yıla Göre Fark: {sign}{yf:.1f} M m³")

    if ind.get("teorik_gun") is not None:
        lines.append(
            f"\n⏱️ Teorik karşılık (30 gün ort. talep, değişmez varsayımıyla): ~{ind['teorik_gun']:.0f} gün"
        )
        lines.append("   ⚠ Bu değer kesinlikle 'X gün suyu kaldı' anlamına gelmez.")

    lines += [
        "",
        f"Veri kaynağı: ASKİ ({ind.get('tarih', '')})",
        "Gösterge: Fontevia Ankara 90 Günlük Su İzleme Sistemi",
    ]

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Yardımcı
# ---------------------------------------------------------------------------

def _add_footer(ax) -> None:
    ax.figure.text(
        0.99, 0.01,
        "Kaynak: ASKİ | Fontevia Ankara Su Göstergesi",
        ha="right", va="bottom", fontsize=7, color="#888",
        transform=ax.figure.transFigure,
    )


# ---------------------------------------------------------------------------
# Ana akış
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Ankara 90 Günlük Su Göstergesi — Analiz")
    parser.add_argument("--days", type=int, default=90, help="Analiz penceresi (gün)")
    parser.add_argument("--out", default=str(OUTPUT_DIR), help="Çıktı klasörü")
    parser.add_argument("--summary", action="store_true", help="Sadece metin özeti")
    args = parser.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    rows = load_data(days=args.days)
    if not rows:
        log.error("Yeterli veri yok. Önce aski_scraper.py çalıştırın.")
        return

    indicators = compute_indicators(rows)

    # JSON özet kaydet
    summary_data = {k: v for k, v in indicators.items() if not k.startswith("_")}
    summary_path = out_dir / "indicators.json"
    with summary_path.open("w", encoding="utf-8") as f:
        json.dump(summary_data, f, ensure_ascii=False, indent=2, default=str)
    log.info("Göstergeler kaydedildi: %s", summary_path)

    # Metin özeti
    text_summary = generate_summary(indicators)
    summary_txt_path = out_dir / "linkedin_draft.txt"
    summary_txt_path.write_text(text_summary, encoding="utf-8")
    log.info("LinkedIn taslağı kaydedildi: %s", summary_txt_path)
    print("\n" + text_summary + "\n")

    if args.summary:
        return

    # Grafikler
    plt.rcParams.update({
        "font.family": "DejaVu Sans",
        "axes.spines.top": False,
        "axes.spines.right": False,
    })

    plot_aktif_su(rows, indicators, out_dir)
    plot_giris_arz(rows, out_dir)
    plot_kumülatif_denge(indicators, out_dir)
    plot_baraj_durumu(indicators, out_dir)

    log.info("Tüm grafikler %s klasörüne kaydedildi.", out_dir)


if __name__ == "__main__":
    main()

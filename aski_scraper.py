"""
ASKİ Baraj Doluluk Scraper
Fontevia Ankara 90 Günlük Su Göstergesi v1.0

Her gün https://www.aski.gov.tr/TR/Baraj.aspx adresinden veri çeker,
data/aski_ankara_daily.csv dosyasına idempotent olarak ekler.
Ham HTML arşivini data/archive/ klasörüne kaydeder.

Kullanım:
    python aski_scraper.py
    python aski_scraper.py --date 2026-08-23   # belirli tarih (test için)
    python aski_scraper.py --dry-run            # sadece göster, kaydetme
"""

import re
import sys
import csv
import json
import argparse
import logging
import os
from datetime import date, datetime
from pathlib import Path

import requests
from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# Yapılandırma
# ---------------------------------------------------------------------------

URL = "https://www.aski.gov.tr/TR/Baraj.aspx"
DATA_DIR = Path(__file__).parent / "data"
ARCHIVE_DIR = DATA_DIR / "archive"
CSV_PATH = DATA_DIR / "aski_ankara_daily.csv"

CSV_FIELDNAMES = [
    "tarih",
    "toplam_depolama_m3",
    "aktif_su_m3",
    "toplam_doluluk_pct",
    "aktif_doluluk_pct",
    "sehre_verilen_m3_gun",
    "barajlara_gelen_m3_gun",
    # Baraj bazında hacim (m³)
    "camlidere_m3",
    "kurtbogazi_m3",
    "egerekkaya_m3",
    "akyar_m3",
    "kesikkopru_m3",
    "palas_m3",
    "cubuk1_m3",
    "cubuk2_m3",
    "ivedik_m3",
    # Baraj bazında doluluk (%)
    "camlidere_pct",
    "kurtbogazi_pct",
    "egerekkaya_pct",
    "akyar_pct",
    "kesikkopru_pct",
    "palas_pct",
    "cubuk1_pct",
    "cubuk2_pct",
    "ivedik_pct",
    # Geçen yıl karşılaştırma
    "gecen_yil_aktif_su_m3",
    "gecen_yil_tarihi",
    # Meta
    "kaynak_url",
    "cekme_zamani",
]

# Bilinen baraj adı → sütun prefix eşleştirmesi (alt string arama)
BARAJ_MAP = {
    "çamlıdere": "camlidere",
    "camlidere": "camlidere",
    "kurtboğazı": "kurtbogazi",
    "kurtbogazi": "kurtbogazi",
    "eğrekkaya": "egerekkaya",
    "egerekkaya": "egerekkaya",
    "akyar": "akyar",
    "kesikköprü": "kesikkopru",
    "kesikkopru": "kesikkopru",
    "palas": "palas",
    "çubuk 1": "cubuk1",
    "çubuk1": "cubuk1",
    "çubuk 2": "cubuk2",
    "çubuk2": "cubuk2",
    "ivedik": "ivedik",
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "tr-TR,tr;q=0.9,en;q=0.8",
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Yardımcı fonksiyonlar
# ---------------------------------------------------------------------------

def parse_tr_number(text: str) -> float | None:
    """
    Türkçe sayı biçimini float'a çevirir.
    "1.108.276.000" → 1108276000.0
    "35,30"         → 35.30
    "%35,30"        → 35.30
    """
    if not text:
        return None
    text = text.strip().replace("%", "").replace("\xa0", " ").strip()
    # Nokta binlik ayraç, virgül ondalık ayraç
    # Eğer nokta var ve virgül de varsa: nokta=binlik, virgül=ondalık
    if "." in text and "," in text:
        text = text.replace(".", "").replace(",", ".")
    elif "," in text:
        # Sadece virgül: ondalık
        text = text.replace(",", ".")
    elif "." in text:
        # Sadece nokta: eğer son gruplar 3 haneliyse binlik ayraç
        parts = text.split(".")
        if all(len(p) == 3 for p in parts[1:]):
            text = text.replace(".", "")
        # Aksi halde ondalık nokta olarak bırak
    try:
        return float(text)
    except ValueError:
        return None


def extract_numbers(text: str) -> list[float]:
    """Metin içindeki tüm Türk biçimli sayıları çıkar."""
    pattern = r"[\d]{1,3}(?:\.[\d]{3})*(?:,[\d]+)?"
    matches = re.findall(pattern, text)
    results = []
    for m in matches:
        v = parse_tr_number(m)
        if v is not None:
            results.append(v)
    return results


def fetch_page(url: str, timeout: int = 30) -> str:
    """ASKİ sayfasını indir, HTML döndür."""
    log.info("Sayfa çekiliyor: %s", url)
    resp = requests.get(url, headers=HEADERS, timeout=timeout)
    resp.raise_for_status()
    resp.encoding = resp.apparent_encoding or "utf-8"
    return resp.text


def archive_html(html: str, tarih: date) -> None:
    """Ham HTML'i tarihe göre arşivle."""
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    path = ARCHIVE_DIR / f"baraj_{tarih.isoformat()}.html"
    path.write_text(html, encoding="utf-8")
    log.info("HTML arşivlendi: %s", path)


# ---------------------------------------------------------------------------
# HTML ayrıştırma
# ---------------------------------------------------------------------------

def parse_baraj_page(html: str) -> dict:
    """
    ASKİ /TR/Baraj.aspx sayfasından veri çıkar.
    Birden fazla ayrıştırma stratejisi kullanır.
    """
    soup = BeautifulSoup(html, "html.parser")
    data = {}

    # --- Strateji 1: Tüm tabloları tara ---
    tables = soup.find_all("table")
    log.info("Toplam tablo sayısı: %d", len(tables))

    for table in tables:
        rows = table.find_all("tr")
        for row in rows:
            cells = [td.get_text(strip=True) for td in row.find_all(["td", "th"])]
            if len(cells) < 2:
                continue
            row_text = " ".join(cells).lower()

            # Özet satırları
            _parse_summary_row(cells, row_text, data)
            # Baraj satırları
            _parse_dam_row(cells, row_text, data)

    # --- Strateji 2: Sayfanın tüm metninden regex ile ana değerleri çek ---
    full_text = soup.get_text(separator="\n")
    _parse_full_text(full_text, data)

    # --- Strateji 3: Span/div içindeki büyük sayıları ara ---
    _parse_highlighted_values(soup, data)

    log.info("Ayrıştırılan alanlar: %s", list(data.keys()))
    return data


def _parse_summary_row(cells: list[str], row_text: str, data: dict) -> None:
    """Özet satırlarından ana metrikleri çıkar."""
    nums = []
    for c in cells[1:]:
        v = parse_tr_number(c)
        if v is not None:
            nums.append(v)

    if not nums:
        return

    first_val = nums[0]

    # Toplam hacim / su miktarı tespiti (büyük değerler: milyonlarca m³)
    if any(k in row_text for k in ["toplam depolama", "toplam hacim", "su miktarı"]):
        if "aktif" not in row_text and first_val > 1e8:
            if "toplam_depolama_m3" not in data:
                data["toplam_depolama_m3"] = first_val
            log.debug("toplam_depolama_m3: %s", first_val)

    if "aktif kullanılabilir" in row_text or "aktif su" in row_text:
        if "aktif_su_m3" not in data and first_val > 1e7:
            data["aktif_su_m3"] = first_val
        if len(nums) >= 2 and "aktif_doluluk_pct" not in data:
            data["aktif_doluluk_pct"] = nums[1]

    if "aktif doluluk" in row_text and "aktif_doluluk_pct" not in data:
        data["aktif_doluluk_pct"] = first_val

    if "toplam doluluk" in row_text and "toplam_doluluk_pct" not in data:
        data["toplam_doluluk_pct"] = first_val

    if any(k in row_text for k in ["şehre verilen", "sehre verilen", "dağıtılan"]):
        if "sehre_verilen_m3_gun" not in data:
            data["sehre_verilen_m3_gun"] = first_val

    if any(k in row_text for k in ["barajlara gelen", "gelen su", "toplam giriş"]):
        if "barajlara_gelen_m3_gun" not in data:
            data["barajlara_gelen_m3_gun"] = first_val


def _parse_dam_row(cells: list[str], row_text: str, data: dict) -> None:
    """Baraj tablosu satırlarından baraj bazında veri çıkar."""
    if not cells:
        return

    baraj_key = None
    for name_tr, key in BARAJ_MAP.items():
        if name_tr in row_text:
            baraj_key = key
            break

    if baraj_key is None:
        return

    # Satırdaki sayıları topla (baraj adı hücresindeki sayıları atla)
    nums = []
    for c in cells:
        # Baraj adı içeren hücreyi atla
        if any(name in c.lower() for name in BARAJ_MAP):
            continue
        v = parse_tr_number(c)
        if v is not None:
            nums.append(v)

    # Beklenen format: [toplam_hacim, su_miktari, yuzde]
    # veya [su_miktari, yuzde] (özet satırlarda)
    if len(nums) >= 2:
        # Büyük sayı → m³, küçük sayı (< 101) → yüzde
        big_vals = [n for n in nums if n > 1000]
        pct_vals = [n for n in nums if 0 <= n <= 100]

        m3_key = f"{baraj_key}_m3"
        pct_key = f"{baraj_key}_pct"

        if big_vals and m3_key not in data:
            # İkinci büyük değer genellikle mevcut su miktarı (birincisi kapasite)
            data[m3_key] = big_vals[-1] if len(big_vals) > 1 else big_vals[0]
        if pct_vals and pct_key not in data:
            data[pct_key] = pct_vals[-1]

        log.debug("Baraj %s: m3=%s pct=%s", baraj_key, data.get(m3_key), data.get(pct_key))


def _parse_full_text(full_text: str, data: dict) -> None:
    """
    Sayfa tam metninden kritik değerleri regex ile çek.
    Tablo ayrıştırma başarısız olursa yedek strateji.
    """
    lines = full_text.split("\n")

    for i, line in enumerate(lines):
        line_l = line.lower().strip()
        if not line_l:
            continue

        # Şehre verilen su (1-3 milyon m³/gün aralığı)
        if any(k in line_l for k in ["şehre verilen", "sehre verilen"]):
            for j in range(max(0, i-2), min(len(lines), i+4)):
                nums = extract_numbers(lines[j])
                for n in nums:
                    if 500_000 < n < 5_000_000 and "sehre_verilen_m3_gun" not in data:
                        data["sehre_verilen_m3_gun"] = n
                        break

        # Barajlara gelen su (genellikle yüz binler m³/gün)
        if any(k in line_l for k in ["barajlara gelen", "gelen su"]):
            for j in range(max(0, i-2), min(len(lines), i+4)):
                nums = extract_numbers(lines[j])
                for n in nums:
                    if 10_000 < n < 2_000_000 and "barajlara_gelen_m3_gun" not in data:
                        data["barajlara_gelen_m3_gun"] = n
                        break

        # Aktif doluluk yüzdesi
        if "aktif doluluk" in line_l and "aktif_doluluk_pct" not in data:
            nums = extract_numbers(line)
            if not nums:
                nums = extract_numbers(lines[i+1]) if i+1 < len(lines) else []
            for n in nums:
                if 0 < n <= 100:
                    data["aktif_doluluk_pct"] = n
                    break

        # Geçen yıl karşılaştırması: tarih formatı arama
        year_match = re.search(r"(\d{2}\.\d{2}\.\d{4})", line)
        if year_match and i > 0:
            try:
                d = datetime.strptime(year_match.group(1), "%d.%m.%Y").date()
                if d.year == date.today().year - 1:
                    nums = extract_numbers(line)
                    if not nums:
                        nums = extract_numbers(lines[i+1]) if i+1 < len(lines) else []
                    for n in nums:
                        if n > 1e7 and "gecen_yil_aktif_su_m3" not in data:
                            data["gecen_yil_aktif_su_m3"] = n
                            data["gecen_yil_tarihi"] = d.isoformat()
                            break
            except ValueError:
                pass


def _parse_highlighted_values(soup: BeautifulSoup, data: dict) -> None:
    """
    Büyük/öne çıkan HTML elementlerindeki sayıları çek.
    ASKİ sayfasında bazı değerler div/span içinde ayrıca gösteriliyor.
    """
    # Aktif doluluk yüzdesi genellikle büyük font ile gösterilir
    for tag in soup.find_all(["span", "div", "h2", "h3", "h4", "strong", "b"]):
        text = tag.get_text(strip=True)
        text_l = text.lower()

        if "aktif doluluk" in text_l or "aktif doluluk oranı" in text_l:
            nums = extract_numbers(text)
            for n in nums:
                if 0 < n <= 100 and "aktif_doluluk_pct" not in data:
                    data["aktif_doluluk_pct"] = n

        # "% 35,30" gibi yalnız yüzde değerleri (büyük gösterim)
        pct_match = re.search(r"%\s*([\d,]+)", text)
        if pct_match:
            v = parse_tr_number(pct_match.group(1))
            if v and 0 < v <= 100:
                parent_text = (tag.parent.get_text(strip=True) if tag.parent else "").lower()
                if "aktif" in parent_text and "aktif_doluluk_pct" not in data:
                    data["aktif_doluluk_pct"] = v


# ---------------------------------------------------------------------------
# CSV işlemleri
# ---------------------------------------------------------------------------

def load_existing_dates() -> set[str]:
    """CSV'deki mevcut tarihleri oku."""
    if not CSV_PATH.exists():
        return set()
    with CSV_PATH.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        return {row["tarih"] for row in reader if "tarih" in row}


def append_to_csv(row: dict) -> None:
    """CSV'ye yeni satır ekle (yoksa oluştur)."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    file_exists = CSV_PATH.exists()

    with CSV_PATH.open("a", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDNAMES, extrasaction="ignore")
        if not file_exists:
            writer.writeheader()
            log.info("CSV oluşturuldu: %s", CSV_PATH)
        writer.writerow(row)
        log.info("CSV'ye yazıldı: %s", row["tarih"])


# ---------------------------------------------------------------------------
# Ana akış
# ---------------------------------------------------------------------------

def build_row(data: dict, tarih: date) -> dict:
    """Ayrıştırılan veriyi CSV satırına dönüştür."""
    row = {f: "" for f in CSV_FIELDNAMES}
    row.update(
        tarih=tarih.isoformat(),
        kaynak_url=URL,
        cekme_zamani=datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    # Sayısal alanları doldur
    for key, val in data.items():
        if key in CSV_FIELDNAMES and val is not None:
            row[key] = val
    return row


def run(tarih: date, dry_run: bool = False) -> dict:
    """
    Tek günlük veri çekme ve kaydetme iş akışı.
    Returns: CSV satırı dict'i
    """
    # İdempotent kontrol
    existing = load_existing_dates()
    if tarih.isoformat() in existing:
        log.info("Bu tarih zaten kayıtlı, atlanıyor: %s", tarih.isoformat())
        return {}

    # Veri çek
    html = fetch_page(URL)
    archive_html(html, tarih)

    # Ayrıştır
    data = parse_baraj_page(html)

    # Satır oluştur
    row = build_row(data, tarih)

    if dry_run:
        log.info("DRY-RUN — satır gösteriliyor:\n%s", json.dumps(row, ensure_ascii=False, indent=2))
        return row

    append_to_csv(row)
    return row


def main():
    parser = argparse.ArgumentParser(description="ASKİ günlük baraj verisi çekici")
    parser.add_argument(
        "--date",
        default=None,
        help="Hedef tarih YYYY-MM-DD formatında (varsayılan: bugün)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Veriyi kaydetmeden göster",
    )
    args = parser.parse_args()

    tarih = date.fromisoformat(args.date) if args.date else date.today()
    log.info("Hedef tarih: %s", tarih.isoformat())

    result = run(tarih, dry_run=args.dry_run)

    if not result:
        log.warning("Veri alınamadı veya zaten mevcut.")
        sys.exit(0)

    log.info("Tamamlandı. Çekilen alan sayısı: %d", sum(1 for v in result.values() if v != ""))


if __name__ == "__main__":
    main()

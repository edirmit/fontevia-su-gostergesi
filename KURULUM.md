# Fontevia Ankara 90 Günlük Su Göstergesi — Kurulum Rehberi

## Genel Bakış

```
ASKİ (aski.gov.tr)
     │  her gün 07:00
     ▼
aski_scraper.py  ──► data/aski_ankara_daily.csv
                 ──► data/archive/baraj_YYYY-MM-DD.html
                          │  her Pazartesi
                          ▼
                    analyze.py  ──► output/01_aktif_su_90gun.png
                                ──► output/02_giris_arz_90gun.png
                                ──► output/03_kumülatif_denge_90gun.png
                                ──► output/04_baraj_durumu.png
                                ──► output/linkedin_draft.txt
                                ──► output/indicators.json
```

## 1. GitHub Reposu Oluştur

```bash
# Yeni bir private veya public repo oluştur:
# GitHub.com → New repository → "fontevia-su-gostergesi"

git clone https://github.com/KULLANICI_ADI/fontevia-su-gostergesi.git
cd fontevia-su-gostergesi
```

Bu klasördeki tüm dosyaları klonlanan repoya kopyala:
```
aski_scraper.py
analyze.py
requirements.txt
.gitignore
.github/workflows/daily.yml
```

```bash
git add .
git commit -m "ilk kurulum: Fontevia ASKİ Su Göstergesi v1.0"
git push origin main
```

## 2. GitHub Actions İzinleri

Repo → Settings → Actions → General → Workflow permissions:
**"Read and write permissions"** seçili olmalı.

Bu izin olmadan bot CSV'yi commit edemez.

## 3. İlk Manuel Çalıştırma (Test)

GitHub → Actions → "ASKİ Günlük Veri Toplama" → Run workflow

`dry_run: true` ile çalıştır, logları kontrol et.
Veri başarıyla ayrıştırıldıysa `dry_run: false` ile tekrar çalıştır.

## 4. Otomatik Program

Workflow zaten ayarlı:
- **Her gün 07:00 İstanbul** → `aski_scraper.py` çalışır → CSV'ye ekler
- **Her Pazartesi 08:00 İstanbul** → `analyze.py` çalışır → Grafikler güncellenir

## 5. Yerel Test

```bash
cd fontevia-su-gostergesi
pip install -r requirements.txt

# Veri çek (bugün)
python aski_scraper.py

# Veri çek (test / geçmiş tarih)
python aski_scraper.py --date 2026-08-23 --dry-run

# Analiz çalıştır
python analyze.py

# Sadece metin özeti
python analyze.py --summary
```

## 6. CSV Şeması

| Alan | Birim | Açıklama |
|---|---|---|
| tarih | YYYY-MM-DD | Ölçüm tarihi |
| toplam_depolama_m3 | m³ | Tüm barajların toplam su hacmi |
| aktif_su_m3 | m³ | İşletme için kullanılabilir aktif hacim |
| toplam_doluluk_pct | % | Toplam doluluk oranı |
| aktif_doluluk_pct | % | Aktif hacim doluluk oranı |
| sehre_verilen_m3_gun | m³/gün | Günlük şehir su arzı |
| barajlara_gelen_m3_gun | m³/gün | Günlük baraj girişi |
| camlidere_m3 | m³ | Çamlıdere Barajı mevcut su hacmi |
| camlidere_pct | % | Çamlıdere doluluk oranı |
| kurtbogazi_m3 | m³ | Kurtboğazı Barajı |
| … | … | Diğer barajlar aynı yapıda |
| gecen_yil_aktif_su_m3 | m³ | Geçen yıl aynı gün aktif hacim |
| gecen_yil_tarihi | YYYY-MM-DD | Karşılaştırma tarihi |

## 7. Türetilmiş Göstergeler (analyze.py çıktısı)

| Gösterge | Formül | Yorum |
|---|---|---|
| Aktif Rezerv | S_t | Bugünkü işletme hacmi |
| 90 Günlük Δ | S_t − S_{t−90} | Negatif = sistem rezerv tüketiyor |
| Toplam Giriş (90g) | Σ Q_in | Barajlara toplam giriş |
| Toplam Arz (90g) | Σ Q_şehir | Şehre toplam verilen su |
| Giriş/Kullanım R₉₀ | Σ Q_in / Σ Q_şehir | < 1 kritik sinyal |
| Teorik Gün | S_t / Q̄_şehir_30g | **"X gün suyu kaldı" değildir!** |
| Yıllık Fark | S_t − S_{t,geçen_yıl} | Gerçek su güvenliği trendi |

## 8. Önemli Uyarılar

**Teorik gün sayısı**: "Ankara'nın X gün suyu kaldı" şeklinde kesinlikle yayımlanmamalı.
Doğru ifade: *"Mevcut aktif depolama, son dönem talebi değişmez kabul edildiğinde
yaklaşık X günlük teorik tüketime eşdeğerdir."*

**İşletme dengesi**: Grafik 3 gerçek bir rezervuar kütle dengesi değildir.
Buharlaşma, yeraltı suyu, barajlar arası transferler hesaba katılmamıştır.

## 9. Sorun Giderme

**Scraper veri bulamıyor**: ASKİ sayfa yapısı değişmiş olabilir.
`data/archive/` klasöründeki en son HTML dosyasını kontrol et.
`aski_scraper.py` içindeki `BARAJ_MAP` ve ayrıştırma mantığını HTML yapısına göre güncelle.

**GitHub Actions commit yapamıyor**: Repo ayarlarından "Read and write permissions" kontrolü.

**Grafikler boş**: `data/aski_ankara_daily.csv` en az 7 satır gerektiriyor.
İlk hafta grafik üretilmez.

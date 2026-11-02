# photo-archive-organizer

[English](README.md)

Harici disklere ve bilgisayara dağılmış aile fotoğraf ve video arşivlerini
güvenle düzenleyen bir [Claude Code](https://claude.com/claude-code) skill'i.
**Fotoğraflarınıza hiç bakmadan** çalışır.

Gerçek bir aile arşivi düzenlenirken geliştirildi: birkaç NTFS disk, eski telefon
ve bilgisayar yedekleri, yedeklerin yedekleri, döndürülmüş ve WhatsApp kopyaları,
RAW+JPEG çiftleri, bozuk JPEG'ler, iki kişinin karışmış dosyaları. Yaptığı her
işlem kayda geçer ve geri alınabilir.

## Neler yapar

| Claude'a deyin ki… | Ne olur |
|---|---|
| "Yedekte olup arşivde olmayanları ayrı klasöre çıkar." | İçerik karşılaştırması (SHA-256, adlar önemsiz), olmayanlar klasör yapısıyla ayrılır, sayım eşitliği kontrol edilir |
| "Yıl ay düzenine sok." | `Foto/YYYY/YYYY-AA/YYYYMMDD_SSDDss_ab12.jpg`, tarihsiz/ekran görüntüsü/belge ayrımı, elle verilmiş adlar korunur, yan dosyalar eşini izler |
| "Benzerleri ayıkla." | Aynı görüntü verisi, aynı çekim anı, döndürmeyi tanıyan Vision benzerliği, JPEG eşi olan RAW |
| "Arşive kat." | Aynı göreli yerlere taşır, üzerine yazmaz, aynı dosyaları raporlar |
| "Bazı JPEG'ler açılmıyor." | Açılma kontrolü, sağlam görüntü verisinden başlık onarımı |
| "İki yedeğim aynı mı?" | Yol/boyut ya da tam hash karşılaştırması |
| "Bu fotoğraflar kimin?" | Kamera modeli × yıl × klasör raporu, sahibini siz söylersiniz |

## Güvenlik ilkeleri

- **Mahremiyet:** kararlar hash, EXIF ve cihaz üzerindeki Vision sayılarıyla verilir.
  Fotoğraflar asla gösterilmez, yüklenmez, tarif edilmez.
- **Önce plan, sonra uygulama:** değişiklik yapan her komut önce okunabilir bir plan yazar.
- **Sessiz silme yok:** fazla kopyalar `Cop/`, sürümler `Benzerler/` klasörüne gider;
  çöpe atmak sizin onayınızla, her eşi yeniden doğrulayarak ve Finder çöpüne yapılır.
- **Kayıt:** her taşıma/ad değişikliği hash ve nedeniyle `Kayitlar/Islem-Kaydi.csv` dosyasına yazılır.
- **Sayım:** her karşılaştırmada `toplam = var + yok + atlanan` kontrol edilir.
- **Diskler arası:** kopyala + doğrula; kaynağı siz kaldırana kadar yerinde kalır.

## Gereksinimler

- macOS (Linux/Windows'ta karşılaştırma/düzenleme/birleştirme çalışır; Vision
  benzerliği, açılma kontrolü ve Finder çöpü yalnızca macOS'ta)
- Python 3.8+ (macOS'ta hazır gelir)
- [exiftool](https://exiftool.org)
- Vision özellikleri için Xcode komut satırı araçları (`xcode-select --install`)

## Kurulum

```bash
git clone https://github.com/oelbas/photo-archive-organizer ~/.claude/skills/photo-archive-organizer
sh ~/.claude/skills/photo-archive-organizer/tools/vision/build.sh      # isteğe bağlı, macOS
mkdir -p ~/.config/photo-archive-organizer
cp ~/.claude/skills/photo-archive-organizer/config.example.json ~/.config/photo-archive-organizer/config.json
```
Ayar dosyasında `"language": "tr"` yapın, korunacak albümleri ve cihaz sahiplerini
yazın. Sonra Claude Code'a fotoğraflarınızla ilgili ne istediğinizi söyleyin.

## Klasör düzeni (`"language": "tr"`)

```
Anna/
  Foto/2017/2017-12/20171215_133054_c517.jpg
  Foto/2017/Ekran Goruntuleri/…
  Foto/2017/Tarihsiz/2017_07b4a3.jpg
  Foto/Tarihsiz/tarihsiz_e60e4e.jpg
  Video/2011/2011-12/20111221_132538_3f3d.mod (+ .moi)
  Data/CV.pdf
  Kayitlar/Islem-Kaydi.csv
```

## Testler

```bash
python3 -m unittest discover tests -v
```
Testler sahte görüntüler üretir (gerçek fotoğraf kullanılmaz).

## Sınırlamalar

- Çok küçük görüntülerde (< 500 piksel) Vision benzerliği güvenilir değildir; bu
  eşleşmeler yalnızca listelenir.
- Tarihsiz ve döndürülmüş kopyalar her zaman yakalanamayabilir.
- QuickTime `CreateDate` video tarihleri belirsizdir (UTC mi yerel mi);
  ayrıntı `references/standard.md` dosyasında.

## Lisans

MIT — [LICENSE](LICENSE).

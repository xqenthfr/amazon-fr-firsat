# Amazon.fr Fırsat Avcısı

Amazon Fransa'daki olası fiyat hatalarını ve olağan dışı indirimleri bulup Telegram'dan haber veren program.

> **Önemli:** Program "kesin fiyat hatası" demez. Sonuçlar "Olası fiyat hatası", "Yüksek öncelikli fırsat",
> "Olağan dışı fiyat" diye sınıflandırılır. Satın almadan önce fiyatı, satıcıyı ve varyantı Amazon sayfasında
> kendiniz kontrol edin. Amazon fiyat hatası olan siparişleri iptal edebilir.

---

## 1. Veri kaynakları: gerçekte ne yapabiliyor?

Amazon'un tüm kataloğunu ücretsiz ve anlık taramak **mümkün değil**. Amazon sitesini otomatik kazımak kullanım
koşullarına aykırıdır ve CAPTCHA ile engellenir; bu program bunu **yapmaz**.

| Kaynak | Ücret | Kapsam | Fiyat geçmişi | Durum |
|---|---|---|---|---|
| **Dealabs RSS** (Fransa'nın en büyük fırsat topluluğu) | Ücretsiz | Sadece topluluğun paylaştığı Amazon fırsatları (günde onlarca). "Erreur de prix" grubu dahil | Yok (program kendi kayıtlarını zamanla biriktirir) | **Varsayılan açık** |
| **Keepa API** | Ücretli, en düşük plan yaklaşık **49 €/ay** (20 token/dk) | Amazon.fr'de son 12 saatte fiyatı değişen **tüm** ürünler | 30/90/180 gün, en düşük, stok | **Varsayılan kapalı**, sizin onayınızla açılır |
| Amazon PA-API / Creators API | Ücretsiz ama satış şartı var | Ürün bilgisi | Yok | Kullanılmadı (aşağıya bakın) |

- **Dealabs:** robots.txt `/rss` yoluna izin veriyor. Yönlendirme bağlantılarına (`/visit/`) dokunulmaz. RSS'te
  genellikle ASIN yok. Bu yüzden mesajdaki ürün bağlantısı Dealabs'ın yönlendirmesidir
  (`dealabs.com/visit/threadmain/<ilan no>`): tıklayınca doğrudan Amazon ürün sayfası açılır. Program bu adresi
  kendisi açmaz, sadece mesaja koyar. Yanında Dealabs ilanının bağlantısı da verilir.
  Satıcı, kargo ve stok bilgisi RSS'te yok → mesajda "eksik veri" olarak yazılır.
- **Keepa:** Belgelere göre: fırsat sorgusu 5 token (150 ürüne kadar), ürün sorgusu 1 token/ürün, kullanılmayan
  tokenlar 60 dakikada silinir, ücretsiz API planı yok. Fiyatlar Keepa panelinde değişebilir; abone olmadan önce
  [keepa.com/api](https://keepa.com/api) sayfasında kontrol edin.
- **Amazon PA-API 5.0** Amazon'un kendi belgelerine göre 2026'da kapatılıp "Creators API"ye taşındı. Erişim için Amazon
  ortaklık hesabı ve son 180 günde satış şartı var; fiyat geçmişi de vermiyor. Bu yüzden bu sürümde yok.

### Keepa token hesabı (açarsanız)
Varsayılan ayarlar: tarama başına 1 fırsat sayfası (5 token) + 10 ürün ayrıntısı (10 token) = **15 token**.
15 dakikada bir taramada günde 96 tarama × 15 = **1.440 token/gün**. 20 token/dk plan günde 28.800 token üretir;
yani en küçük plan rahat yeter, hatta tarama başına daha fazla ürün incelenebilir. Program ayrıca **günlük
bütçe** (varsayılan 5.000) uygular, token bittiğinde (HTTP 429) dolana kadar istek atmaz.

---

## 2. Gerekli hesaplar

1. **Telegram hesabı** (ücretsiz) — zorunlu.
2. **GitHub hesabı** (ücretsiz) — sadece bilgisayarınız kapalıyken çalışmasını istiyorsanız.
3. **Keepa API aboneliği** (ücretli) — isteğe bağlı. Şu an gerekmez.

---

## 3. Kurulum (Windows) — adım adım

**Adım 1 – Python.** Bu bilgisayara Python 3.12 kuruldu. Başka bir bilgisayarda: PowerShell'e
`winget install Python.Python.3.12 --scope user` yazın. Kurulumdan sonra pencereyi kapatıp yeniden açın.

**Adım 2 – Kurulum betiği.** `amazon-fr-firsat` klasöründe **`kurulum.bat`** dosyasına çift tıklayın. Bu betik:
Python'u kontrol eder, `.env` dosyasını oluşturur ve tüm testleri çalıştırır. "Tum testler gecti" yazmalı.

**Adım 3 – Telegram botu** (aşağıdaki bölüm 4). Bu adım bitmeden bildirim gelmez.

**Adım 4 – Başlatma.** **`baslat.bat`** dosyasına çift tıklayın, menüden:
- `11` → Telegram test mesajı (ilk bildiriminiz)
- `1` → bir kez tara
- `2` → sürekli tara (pencere açık kaldığı sürece çalışır; Ctrl+C durdurur)

---

## 4. Telegram botu kurulumu (BotFather)

1. Telegram'da arama kutusuna **@BotFather** yazın (yanında mavi onay işareti olan).
2. **Başlat**'a basın, sonra `/newbot` yazın.
3. Bota bir görünen ad verin (ör. `Fırsat Avcım`).
4. Bir kullanıcı adı verin; `bot` ile bitmeli (ör. `firsat_avcim_2026_bot`).
5. BotFather size `123456789:AAH...` gibi bir **jeton (token)** verir. Bunu kimseyle paylaşmayın.
6. `amazon-fr-firsat` klasöründeki `.env` dosyasını **Not Defteri** ile açın, `TELEGRAM_BOT_TOKEN=` satırının
   sonuna jetonu yapıştırın ve kaydedin.
7. Telegram'da yeni botunuzu açın, **Başlat**'a basın ve `merhaba` yazın.
8. `baslat.bat` → menüde `12` (Telegram sohbet kimliğini bul). Ekranda `TELEGRAM_CHAT_ID=...` görünür.
9. O satırı `.env` dosyasındaki `TELEGRAM_CHAT_ID=` satırına yazın, kaydedin.
10. Programı kapatıp açın, menüde `11` → Telegram'da "bağlantı testi" mesajı gelmeli. **İlk bildiriminiz budur.**

İlk gerçek fırsat bildirimi, eşik puanını (varsayılan 60) geçen bir ilan çıktığında gelir. Bu birkaç saat sürebilir.
Hiç fırsat yoksa da her gün bir **günlük rapor** mesajı gelir.

---

## 5. Puanlama (0–100)

| Bileşen | En fazla | Açıklama |
|---|---|---|
| Ortalamaya göre indirim | 45 | 90 günlük (yoksa 180/30 günlük) ortalamaya göre; %70 indirim = tam puan |
| Bilinen en düşük fiyatın altında | 20 | En düşük fiyatın %60'ı veya altıysa tam puan |
| Nadirlik | 15 | Bu fiyat hiç görülmediyse +15; geçmişin %30'undan fazlasında görüldüyse **−15** |
| Ani düşüş | 10 | Önceki fiyata göre %50+ düşüş |
| Satıcı | 10 | Amazon 10, Amazon gönderimli satıcı 6, diğer satıcı 2 |
| İlgi alanı | 5 | Elektronik, ekran kartı, Dyson, Ninja vb. |

Düşüren durumlar: kullanılmış ürün −10, stok yok −30 (tavan 40), kargo fiyata eklenir, kupon düşülür.

**Prime:** Menüde `13` ile açılıp kapanır (varsayılan açık). Açıkken Amazon'un sattığı ve Amazon'un gönderdiği
(FBA) ürünlerde kargo 0 € sayılır. Pazar yeri satıcısının kendi gönderdiği üründe Prime geçerli değildir; kargo
fiyata eklenir. Satıcı bilinmiyorsa (çoğu Dealabs ilanı) kargo "eksik veri" sayılmaz, yerine uyarı yazılır.

**Veri eksikse sahte güven yok:** Fiyat geçmişi hiç yoksa puan en fazla **70**, güven "düşük". Geçmiş 30 günden
kısaysa en fazla **85**. Kullanılmış ürün yeni ürün geçmişiyle karşılaştırılıyorsa en fazla **74**, güven "düşük".
Eksik alanlar (kargo, satıcı, stok, geçmiş...) her mesajda ayrıca yazılır.

Dealabs ilanlarında geçmiş olmadığı için puan topluluk sinyalinden gelir: "erreur de prix" grubunda paylaşılan
ilan 55–65 puan alır ve "Olası fiyat hatası (topluluk bildirimi, doğrulanmadı)" etiketiyle gönderilir.
"Olası fiyat hatası" etiketinin doğrulanmış hali için gerçek fiyat geçmişi (Keepa) gerekir.

**Tarama mantığı (Dealabs):** 5 dakikada bir "nouveaux", "erreur de prix" ve "tendance" akışları okunur. Ayrıca 13
kategori akışından (informatique, cartes-graphiques, dyson, jeux-video…) her turda sırayla 2'si okunur. "nouveaux"
listesinde iki tur arasında boşluk varsa (ilan kaçmış olabilir) tüm kategori akışları okunur ve uyarı kaydedilir.
Başlığında/açıklamasında "erreur de prix", "bug de prix" geçen ilanlar ayrıca işaretlenir.

**Takip kelimeleri** (menü `14`): Dyson, Ninja, RTX, PS5… içeren ürünler daha düşük puanda (varsayılan 40) da bildirilir.

**Tekrar bildirim:** Aynı ürün (ASIN ya da başlık) bir kez bildirilir. Fiyat son bildirimden en az %10
(ayarlanabilir) daha düşerse yeniden bildirilir. Program yeniden başlasa da bu kayıt korunur.

---

## 6. Menü

| No | İşlev |
|---|---|
| 1 / 2 | Tek tarama / sürekli tarama |
| 3 | Tarama aralığı (dakika) |
| 4 | Minimum fırsat puanı |
| 5 | Kategorileri aç/kapat (ekran kartı, bilgisayar, oyun, elektronik, ev aletleri, mutfak/ev, diğer) |
| 6 / 7 | Son fırsatlar / bildirim geçmişi (gönderildi / bekliyor) |
| 8 | Keepa token tahmini ve gerçek kullanım |
| 9 | Günlük rapor ve hatalar |
| 10 | Kaynakları aç/kapat (Keepa için "EVET" yazmanız gerekir) |
| 11 / 12 | Telegram testi / sohbet kimliğini bulma |

Ayarlar `veri/ayarlar.json`, tüm kayıtlar `veri/firsatlar.db` (SQLite), günlük `veri/firsat.log` dosyasındadır.
Çekirdek (`scanner.py`) menüden bağımsızdır; ileride bir web paneli aynı fonksiyonları kullanabilir.

**Hata yönetimi:** İnternet kesilirse her istek 3 kez (2 sn, 4 sn bekleyerek) denenir; olmazsa hata kaydedilir ve
bir sonraki turda tekrar denenir. Telegram'a ulaşılamazsa bildirim kaybolmaz, "bekliyor" kalır ve sonra gönderilir
(24 saatten eskiyse artık gönderilmez). Keepa tokenları biterse bekleme süresi kaydedilir; program yeniden başlasa
da o süre dolmadan istek atılmaz. API anahtarları günlüğe yazılmaz.

---

## 7. Bilgisayar kapalıyken 7/24 çalıştırma

| Seçenek | Ücret | Kısıtlar |
|---|---|---|
| **Kendi bilgisayarınız** (`baslat.bat` → 2) | 0 € | Bilgisayar açık ve uyanık olmalı |
| **GitHub Actions** (hazır: `.github/workflows/tarama.yml`) | 0 € | Zamanlama 5–15 dk gecikebilir. **Gizli (private) depoda ayda 2.000 dakika** sınırı: 30 dk'da bir tarama ≈ 1.440 dk/ay (sınırın altında). Açık (public) depoda dakika sınırı yok ama 60 gün depoda hiçbir değişiklik olmazsa zamanlama durur. Veritabanı "cache" ile korunur; 7 gün kullanılmazsa silinir |
| **Oracle Cloud Always Free** sanal sunucu | 0 € | Gerçek 7/24. Kayıtta kredi kartı doğrulaması ister; kurulum daha teknik |
| PythonAnywhere ücretsiz | 0 € | Günde 1 zamanlanmış görev ve sadece izinli sitelere erişim → bu iş için uygun değil |
| Render / Railway ücretsiz | 0 € | Uyku modu, aylık saat sınırı → sürekli izleme için uygun değil |
| Raspberry Pi | ~60–80 € tek sefer, elektrik ~1 €/ay | Evde 7/24 çalışır |

**GitHub Actions kurulumu:** GitHub'da yeni bir depo açın (tercihen **Private**), bu klasörü yükleyin
(`.env` ve `veri/` yüklenmez, `.gitignore` engeller). Depo → Settings → Secrets and variables → Actions →
`TELEGRAM_BOT_TOKEN` ve `TELEGRAM_CHAT_ID` ekleyin. Actions sekmesinden "firsat-taramasi" → "Run workflow" ile
deneyin. Not: GitHub'da menü olmadığı için varsayılan ayarlar kullanılır (Keepa kapalı).

---

## 8. Gerçekçi aylık maliyet

| Kurulum | Aylık |
|---|---|
| Dealabs + Telegram + kendi bilgisayarınız veya GitHub Actions | **0 €** |
| + Keepa en küçük API planı | yaklaşık **49 €** (Keepa panelinde doğrulayın) |

---

## 9. Testler

`kurulum.bat` testleri otomatik çalıştırır. Elle: `python -m unittest discover -s tests -t . -v`

Testler **sentetik verilerle** çalışır (gerçek Amazon verisi değildir) ve ağa çıkmaz:
1. 150 € → 45 € düşüş: puan ≥ 90, "Olası fiyat hatası"
2. Sık sık 45 €'ya satılan ürün: puan < 50, "sık görülüyor" uyarısı
3. Kullanılmış ürünün yeni fiyat geçmişiyle karşılaştırılması: puan ≤ 74, güven düşük, uyarı
4. Yüksek kargo: kargo fiyata eklenir, puan düşer
5. Eksik fiyat geçmişi: puan ≤ 70, güven düşük, eksik veri listelenir
6. Aynı fırsat tekrar bildirilmez (program yeniden başlasa da); %10+ düşüşte yeniden bildirilir
7. Bağlantı kesilmesi: 3 deneme, çökme yok, Telegram bildirimi kaybolmaz
8. Token tükenmesi: 429 sonrası istek atılmaz, bekleme yeniden başlatmada da hatırlanır, günlük bütçe uygulanır

Ayrıca Dealabs RSS ayrıştırma, Keepa yanıt çevirme ve Telegram mesaj içeriği test edilir.
**Keepa istemcisi gerçek bir Keepa anahtarıyla denenmedi**; Keepa belgelerine göre yazıldı ve sahte yanıtlarla test edildi.

---

## 10. Dosyalar

| Dosya | Görevi |
|---|---|
| `main.py` | Başlangıç noktası ve terminal menüsü |
| `config.py` | Ayarlar, kategoriler, `.env` okuma |
| `price_analyzer.py` | Fiyat analizi ve puanlama |
| `data_sources.py` | Dealabs RSS ve Keepa istemcileri, tekrar deneme |
| `telegram_bot.py` | Telegram mesajı oluşturma ve gönderme |
| `scanner.py` | Tarama döngüsü, tekrar bildirim engeli, günlük rapor |
| `storage.py` | SQLite veritabanı (kaldığı yerden devam) |
| `tests/` | Testler |
| `kurulum.bat`, `baslat.bat` | Kurulum ve başlatma |
| `.env.example` | Gizli bilgi şablonu |

Ek Python paketi yoktur; yalnızca Python'un kendi kütüphanesi kullanılır.

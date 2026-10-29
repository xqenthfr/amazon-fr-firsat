"""Fiyat analizi ve 0–100 fırsat puanı.

İlkeler:
- Sadece indirim yüzdesine güvenilmez: geçmiş en düşük fiyat, bu fiyatın ne kadar sık
  görüldüğü, ani düşüş, satıcı, ürün durumu, stok ve kargo birlikte değerlendirilir.
- Veri eksikse puan yapay olarak yükseltilmez: üst sınır (tavan) uygulanır, güven düşer
  ve eksik alanlar açıkça listelenir.
- Hiçbir sonuç "kesin fiyat hatası" demez. En güçlü etiket "Olası fiyat hatası"dır.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from config import DEGERLI_KELIMELER, KATEGORILER

DURUM_YENI = "new"
DURUM_KULLANILMIS = "used"
DURUM_BILINMIYOR = "unknown"

SATICI_AMAZON = "amazon"
SATICI_FBA = "third_party_fba"
SATICI_PAZARYERI = "third_party"
SATICI_BILINMIYOR = "unknown"

SATICI_ADLARI = {
    SATICI_AMAZON: "Amazon",
    SATICI_FBA: "Pazar yeri satıcısı (Amazon gönderimli)",
    SATICI_PAZARYERI: "Pazar yeri satıcısı",
    SATICI_BILINMIYOR: "Bilinmiyor",
}
DURUM_ADLARI = {DURUM_YENI: "Yeni", DURUM_KULLANILMIS: "Kullanılmış", DURUM_BILINMIYOR: "Bilinmiyor"}

# Puan bileşenlerinin üst sınırları (toplam 100)
P_INDIRIM = 45
P_DIP = 20
P_NADIRLIK = 15
P_ANI_DUSUS = 10
P_SATICI = 10

TAVAN_GECMIS_YOK = 70     # geçmiş fiyat hiç yoksa
TAVAN_GECMIS_KISA = 85    # 30 günden kısa ya da çok az veri noktası
TAVAN_STOK_YOK = 40


@dataclass
class FiyatGecmisi:
    """Bir ürünün geçmiş fiyat özeti. Hangi duruma (yeni/kullanılmış) ait olduğu önemlidir."""
    durum: str = DURUM_YENI
    ort30: float | None = None
    ort90: float | None = None
    ort180: float | None = None
    en_dusuk: float | None = None     # bilinen en düşük (tüm geçmiş)
    en_yuksek: float | None = None
    kapsanan_gun: float | None = None
    nokta_sayisi: int | None = None
    onceki_fiyat: float | None = None  # son düşüşten hemen önceki fiyat
    noktalar: list[tuple[datetime, float]] = field(default_factory=list)

    @classmethod
    def noktalardan(cls, noktalar: list[tuple[datetime, float]], simdi: datetime | None = None,
                    durum: str = DURUM_YENI) -> "FiyatGecmisi":
        """Ham (zaman, fiyat) listesinden özet hesaplar. Son nokta 'güncel' sayılmaz."""
        noktalar = sorted((z, f) for z, f in noktalar if f is not None and f > 0)
        simdi = simdi or datetime.now(timezone.utc)
        if not noktalar:
            return cls(durum=durum)

        def ortalama(gun: int) -> float | None:
            sinir = simdi - timedelta(days=gun)
            secili = [f for z, f in noktalar if z >= sinir]
            return round(sum(secili) / len(secili), 2) if secili else None

        fiyatlar = [f for _, f in noktalar]
        return cls(
            durum=durum,
            ort30=ortalama(30),
            ort90=ortalama(90),
            ort180=ortalama(180),
            en_dusuk=min(fiyatlar),
            en_yuksek=max(fiyatlar),
            kapsanan_gun=(simdi - noktalar[0][0]).total_seconds() / 86400,
            nokta_sayisi=len(noktalar),
            onceki_fiyat=fiyatlar[-1],
            noktalar=noktalar,
        )

    def referans(self) -> tuple[float | None, str]:
        for deger, ad in ((self.ort90, "90 günlük ortalama"), (self.ort180, "180 günlük ortalama"),
                          (self.ort30, "30 günlük ortalama")):
            if deger:
                return deger, ad
        return None, ""

    def bu_fiyat_veya_altinda_oran(self, fiyat: float) -> float | None:
        """Geçmiş noktaların ne kadarı bu fiyatın %5 üstüne kadar (yani 'aynı fiyat' civarı)?"""
        if not self.noktalar:
            return None
        esik = fiyat * 1.05
        return sum(1 for _, f in self.noktalar if f <= esik) / len(self.noktalar)


@dataclass
class Teklif:
    kaynak: str
    urun_anahtari: str            # ASIN veya kaynak içi kimlik
    baslik: str
    fiyat: float | None
    bag: str                      # ürün bağlantısı (Amazon.fr veya arama)
    kontrol_zamani: datetime
    asin: str | None = None
    kargo: float | None = None    # None = bilinmiyor
    kupon: float | None = None    # EUR cinsinden kupon indirimi
    durum: str = DURUM_BILINMIYOR
    satici: str = SATICI_BILINMIYOR
    stokta: bool | None = None
    kategori: str = ""            # kaynağın verdiği kategori adı
    liste_fiyati: float | None = None
    gecmis: FiyatGecmisi | None = None
    sinyaller: list[str] = field(default_factory=list)
    notlar: list[str] = field(default_factory=list)  # varyant/paket uyarıları vb.
    ek_bag: str | None = None     # ör. Dealabs ilan sayfası
    kargo_prime_varsayim: bool = False  # kargo bilinmiyor ama Prime ile muhtemelen ücretsiz

    def etkin_fiyat(self) -> float | None:
        if self.fiyat is None:
            return None
        return round(self.fiyat + (self.kargo or 0) - (self.kupon or 0), 2)


@dataclass
class Analiz:
    puan: int
    oncelik: str
    etiket: str
    guven: str
    etkin_fiyat: float | None
    referans_fiyat: float | None
    referans_adi: str
    indirim_yuzde: float | None
    kategori_grubu: str
    nedenler: list[str] = field(default_factory=list)
    uyarilar: list[str] = field(default_factory=list)
    eksikler: list[str] = field(default_factory=list)


def oncelik_adi(puan: int) -> str:
    if puan >= 90:
        return "Çok yüksek öncelik"
    if puan >= 75:
        return "Yüksek öncelik"
    if puan >= 50:
        return "İncelenmeye değer"
    return "Düşük öncelik"


def kategori_grubu_bul(kategori: str, baslik: str) -> str:
    metin = f" {kategori} {baslik} ".lower()
    for anahtar, tanim in KATEGORILER.items():
        if any(k in metin for k in tanim["kelimeler"]):
            return anahtar
    return "diger"


def prime_uygula(t: Teklif) -> None:
    """Prime üyeliği: Amazon'un sattığı veya Amazon'un gönderdiği (FBA) ürünlerde kargo ücretsizdir.
    Pazar yeri satıcısının kendi gönderdiği üründe Prime geçmez; kargo olduğu gibi kalır."""
    if t.satici in (SATICI_AMAZON, SATICI_FBA):
        t.kargo = 0.0
    elif t.satici == SATICI_BILINMIYOR and t.kargo is None:
        t.notlar.append("Prime ile kargo büyük olasılıkla ücretsiz; satıcı Amazon/Amazon gönderimli "
                        "değilse kargo çıkabilir")
        t.kargo_prime_varsayim = True


def _sinirla(deger: float, alt: float = 0.0, ust: float = 1.0) -> float:
    return max(alt, min(ust, deger))


def analiz_et(t: Teklif) -> Analiz:
    nedenler: list[str] = []
    uyarilar: list[str] = list(t.notlar)
    eksikler: list[str] = []
    grup = kategori_grubu_bul(t.kategori, t.baslik)

    etkin = t.etkin_fiyat()
    if etkin is None or etkin <= 0:
        return Analiz(0, oncelik_adi(0), "Değerlendirilemedi", "yok", None, None, "", None, grup,
                      [], uyarilar, ["güncel fiyat"])

    if t.kargo is None:
        if not t.kargo_prime_varsayim:
            eksikler.append("kargo ücreti")
    elif t.fiyat and t.kargo > max(5.0, t.fiyat * 0.15):
        uyarilar.append(f"Kargo yüksek: {t.kargo:.2f} € (fiyata eklendi)")
    if t.kupon:
        nedenler.append(f"Kupon {t.kupon:.2f} € düşüldü")
    if t.durum == DURUM_BILINMIYOR:
        eksikler.append("ürün durumu (yeni/kullanılmış)")
    if t.satici == SATICI_BILINMIYOR:
        eksikler.append("satıcı")
    if t.stokta is None:
        eksikler.append("stok durumu")

    g = t.gecmis
    referans, referans_adi = (g.referans() if g else (None, ""))
    gecmis_var = bool(g and (referans or g.en_dusuk))
    indirim = None
    puan = 0.0

    # Geçmiş başka durumdaki ürüne aitse (ör. kullanılmış ürün, yeni ürün geçmişiyle) güvenme.
    durum_uyumsuz = bool(g and t.durum != DURUM_BILINMIYOR and g.durum != t.durum)
    if durum_uyumsuz:
        uyarilar.append(f"{DURUM_ADLARI.get(t.durum)} ürün, {DURUM_ADLARI.get(g.durum).lower()} "
                        "ürün fiyat geçmişiyle karşılaştırılıyor; indirim abartılı görünebilir")

    if gecmis_var:
        # A) referansa göre indirim
        if referans:
            indirim = round((1 - etkin / referans) * 100, 1)
            katsayi = 0.35 if durum_uyumsuz else 1.0
            puan += _sinirla((indirim / 100 - 0.10) / 0.60) * P_INDIRIM * katsayi
            if indirim >= 10:
                nedenler.append(f"{referans_adi} ({referans:.2f} €) göre %{indirim:.0f} ucuz")
        else:
            eksikler.append("ortalama fiyat")
        # B) bilinen en düşük fiyata göre
        if g.en_dusuk:
            oran = etkin / g.en_dusuk
            if oran <= 0.6:
                puan += P_DIP
                nedenler.append(f"Bilinen en düşük fiyatın ({g.en_dusuk:.2f} €) çok altında")
            elif oran <= 0.8:
                puan += P_DIP * 0.75
                nedenler.append(f"Bilinen en düşük fiyatın ({g.en_dusuk:.2f} €) belirgin altında")
            elif oran <= 0.95:
                puan += P_DIP * 0.5
                nedenler.append("Yeni dip fiyat")
            elif oran <= 1.05:
                puan += P_DIP * 0.2
        else:
            eksikler.append("geçmiş en düşük fiyat")
        # C) nadirlik: bu fiyat ne sıklıkla görülmüş?
        siklik = g.bu_fiyat_veya_altinda_oran(etkin)
        if siklik is None:
            eksikler.append("fiyat sıklığı (ham geçmiş)")
        elif siklik == 0:
            puan += P_NADIRLIK
            nedenler.append("Bu fiyat geçmişte hiç görülmemiş")
        elif siklik < 0.05:
            puan += P_NADIRLIK * 0.66
        elif siklik < 0.20:
            puan += P_NADIRLIK * 0.33
        elif siklik >= 0.30:
            puan -= P_NADIRLIK
            uyarilar.append(f"Bu fiyat sık görülüyor (geçmişin %{siklik * 100:.0f}'inde)")
        # D) ani düşüş
        if g.onceki_fiyat:
            dusus = 1 - etkin / g.onceki_fiyat
            if dusus >= 0.5:
                puan += P_ANI_DUSUS
                nedenler.append(f"Ani düşüş: {g.onceki_fiyat:.2f} € → {etkin:.2f} €")
            elif dusus >= 0.3:
                puan += P_ANI_DUSUS * 0.6
            elif dusus >= 0.15:
                puan += P_ANI_DUSUS * 0.3
        # E) satıcı
        puan += {SATICI_AMAZON: P_SATICI, SATICI_FBA: P_SATICI * 0.6,
                 SATICI_PAZARYERI: P_SATICI * 0.2}.get(t.satici, 0)
    else:
        eksikler.append("fiyat geçmişi")
        # Geçmiş yoksa sadece zayıf sinyaller: topluluk etiketi, liste fiyatı, ilgi alanı.
        if "erreur_de_prix" in t.sinyaller:
            puan += 55
            nedenler.append("Dealabs topluluğu 'erreur de prix' (fiyat hatası) grubunda paylaştı")
        elif "baslik_hata" in t.sinyaller:
            puan += 45
            nedenler.append("İlan sahibi fiyat hatası olabileceğini yazmış")
        if "tendance" in t.sinyaller:
            puan += 25
            nedenler.append("Dealabs'ta popüler (tendance)")
        if t.liste_fiyati and t.liste_fiyati > etkin:
            indirim = round((1 - etkin / t.liste_fiyati) * 100, 1)
            referans, referans_adi = t.liste_fiyati, "liste fiyatı (satıcı beyanı)"
            puan += _sinirla((indirim / 100 - 0.2) / 0.6) * 25
            uyarilar.append("İndirim yalnızca liste fiyatına göre; liste fiyatları şişirilmiş olabilir")
        if t.satici == SATICI_AMAZON:
            puan += 5

    baslik_k = t.baslik.lower()
    if grup != "diger" or any(k in baslik_k for k in DEGERLI_KELIMELER):
        puan += 5

    if t.durum == DURUM_KULLANILMIS:
        puan -= 10
    if t.stokta is False:
        puan -= 30
        uyarilar.append("Stokta yok görünüyor")

    # Veri kalitesine göre tavan ve güven
    if not gecmis_var:
        tavan, guven = TAVAN_GECMIS_YOK, "düşük"
    elif (g.kapsanan_gun is not None and g.kapsanan_gun < 30) or (g.nokta_sayisi is not None and g.nokta_sayisi < 5):
        tavan, guven = TAVAN_GECMIS_KISA, "orta"
        uyarilar.append("Fiyat geçmişi kısa; karşılaştırma sınırlı")
    else:
        tavan = 100
        guven = "yüksek" if len(eksikler) <= 1 else "orta"
    if durum_uyumsuz:
        tavan = min(tavan, 74)
        guven = "düşük"
    if t.stokta is False:
        tavan = min(tavan, TAVAN_STOK_YOK)

    puan_i = int(round(_sinirla(puan, 0, tavan)))

    # Etiket: kesinlik iddiası yok.
    if (gecmis_var and not durum_uyumsuz and puan_i >= 90 and indirim is not None and indirim >= 60
            and g.en_dusuk and etkin < g.en_dusuk * 0.8 and guven != "düşük"):
        etiket = "Olası fiyat hatası"
    elif (not gecmis_var and puan_i >= 50
          and ("erreur_de_prix" in t.sinyaller or "baslik_hata" in t.sinyaller)):
        etiket = "Olası fiyat hatası (topluluk bildirimi, doğrulanmadı)"
    elif puan_i >= 75:
        etiket = "Yüksek öncelikli fırsat"
    elif puan_i >= 50 and (indirim or 0) >= 30:
        etiket = "Olağan dışı fiyat"
    elif puan_i >= 50:
        etiket = "İncelenmeye değer"
    else:
        etiket = "Düşük öncelik"

    return Analiz(puan_i, oncelik_adi(puan_i), etiket, guven, etkin, referans, referans_adi,
                  indirim, grup, nedenler, uyarilar, eksikler)

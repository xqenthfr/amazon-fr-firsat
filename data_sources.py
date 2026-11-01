"""Veri kaynakları.

1. DealabsKaynagi (ÜCRETSİZ): Fransa'nın en büyük fırsat topluluğu Dealabs'ın herkese açık
   RSS akışları. Sadece Amazon satıcılı ilanlar alınır. Kapsam: topluluğun paylaştığı fırsatlar
   (tüm katalog değil). Fiyat geçmişi vermez; geçmişi kendimiz zamanla biriktiririz.
   robots.txt /rss yoluna izin verir; /visit/ (yönlendirme) yasaktır, ona dokunulmaz.

2. KeepaKaynagi (ÜCRETLİ, varsayılan KAPALI): Amazon.fr fiyat geçmişi ve fırsat tarayıcısı.
   Tüm Amazon.fr kataloğunda son 12 saatte fiyatı değişen ürünleri sorgulayabilir.
   Her istek token harcar; günlük bütçe ve token durumu sürekli izlenir.

Amazon sitesine doğrudan istek atılmaz (kazıma yok, CAPTCHA aşma yok).
"""
from __future__ import annotations

import gzip
import html
import json
import re
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

from price_analyzer import (DURUM_KULLANILMIS, DURUM_YENI, SATICI_AMAZON, SATICI_BILINMIYOR,
                            SATICI_FBA, SATICI_PAZARYERI, FiyatGecmisi, Teklif)

KULLANICI_AJANI = "amazon-fr-firsat/1.0 (kisisel fiyat izleme; RSS okuyucu)"


class KaynakHatasi(Exception):
    """Ağ/servis hatası. Tarama durmaz; hata kaydedilir, sonraki turda tekrar denenir."""


class TokenBitti(KaynakHatasi):
    def __init__(self, mesaj: str, bekleme_saniye: float):
        super().__init__(mesaj)
        self.bekleme_saniye = bekleme_saniye


def gizle(metin: str, *gizliler: str) -> str:
    for g in gizliler:
        if g:
            metin = metin.replace(g, "***")
    return re.sub(r"(key=)[^&\s]+", r"\1***", metin)


def http_getir(url: str, zaman_asimi: float = 20, deneme: int = 3, bekleme: float = 2.0,
               uyku=time.sleep, acici=None) -> tuple[int, bytes]:
    """GET isteği; geçici hatalarda üstel bekleme ile tekrar dener.

    Dönüş: (durum_kodu, gövde). 4xx yanıtlar (429 dahil) tekrar denenmeden döndürülür,
    çünkü onları çağıran taraf yorumlar (örn. Keepa 429 = token bitti).
    """
    acici = acici or urllib.request.urlopen
    son_hata: Exception | None = None
    for i in range(deneme):
        try:
            istek = urllib.request.Request(url, headers={"User-Agent": KULLANICI_AJANI,
                                                         "Accept-Encoding": "gzip"})
            with acici(istek, timeout=zaman_asimi) as yanit:
                govde = yanit.read()
                if yanit.headers.get("Content-Encoding") == "gzip":
                    govde = gzip.decompress(govde)
                return yanit.status, govde
        except urllib.error.HTTPError as e:
            if 400 <= e.code < 500:
                govde = e.read() or b""
                if e.headers and e.headers.get("Content-Encoding") == "gzip":
                    try:
                        govde = gzip.decompress(govde)
                    except OSError:
                        pass
                return e.code, govde
            son_hata = e
        except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError, OSError) as e:
            son_hata = e
        if i < deneme - 1:
            uyku(bekleme * (2 ** i))
    raise KaynakHatasi(f"Bağlantı kurulamadı ({deneme} deneme): {type(son_hata).__name__}: {son_hata}")


# ---------------------------------------------------------------- Dealabs

PEPPER_NS = "{http://www.pepper.com/rss}"


def eur_oku(metin: str | None) -> float | None:
    """'1 299,99€' veya '19.99 €' -> 1299.99"""
    if not metin:
        return None
    m = re.search(r"(\d[\d\s.  ]*(?:,\d{1,2})?)\s*€", metin) or \
        re.search(r"(\d[\d\s.  ]*(?:,\d{1,2})?)", metin)
    if not m:
        return None
    sayi = re.sub(r"[\s  ]", "", m.group(1))
    if "," in sayi:
        sayi = sayi.replace(".", "").replace(",", ".")
    elif sayi.count(".") == 1 and len(sayi.split(".")[1]) == 3:
        sayi = sayi.replace(".", "")  # 1.299 -> binlik ayırıcı
    try:
        return float(sayi)
    except ValueError:
        return None


def baslik_anahtari(baslik: str) -> str:
    """Aynı ürünün farklı ilanlarını eşleştirmek için kaba anahtar (ASIN yoksa)."""
    t = html.unescape(baslik).lower()
    t = re.sub(r"\d+[.,]?\d*\s*€", " ", t)               # fiyatları çıkar
    t = re.sub(r"\(.*?\)|\[.*?\]", " ", t)               # parantez içi notlar
    t = re.sub(r"[^a-z0-9àâçéèêëîïôûùüÿñæœ]+", " ", t)
    kelimeler = [k for k in t.split() if len(k) > 1][:10]
    return "baslik:" + " ".join(kelimeler)


# İlan sahibinin başlıkta/açıklamada fiyat hatası şüphesi belirtmesi
HATA_KELIMELERI = re.compile(r"erreur de prix|erreur prix|bug de prix|prix bugg?é|prix bug|price error")

DERECE_DESENI = re.compile(r"^\s*(-?\d{1,5})°\s*-\s*")

ASIN_DESENI = re.compile(r"amazon\.fr/(?:[^\s\"'<>]*/)?(?:dp|gp/product)/([A-Z0-9]{10})")


# Liste sayfalarındaki ilan kartı verisi (data-vue3 özniteliği, HTML kaçışlı JSON)
VUE_DESENI = re.compile(r"data-vue3='([^']*)'")
# RSS akış adı -> liste sayfası yolu (robots.txt bu yollara izin veriyor; sadece sorgu parametreleri yasak)
SAYFA_YOLLARI = {"tendance": "hot"}


class DealabsKaynagi:
    ad = "dealabs"
    TABAN = "https://www.dealabs.com/rss/"
    SAYFA_TABAN = "https://www.dealabs.com/"

    def __init__(self, akislar: list[str], sadece_amazon: bool = True, getir=http_getir,
                 max_yas_saat: float = 48, yedek_akislar: list[str] | None = None,
                 yedek_her_tarama: int = 2, depo=None, sayfa_kullan: bool = True):
        self.akislar = akislar
        self.sadece_amazon = sadece_amazon
        self.getir = getir
        self.max_yas_saat = max_yas_saat  # eski ilanlar büyük olasılıkla bitmiştir
        self.yedek_akislar = yedek_akislar or []
        self.yedek_her_tarama = yedek_her_tarama
        self.depo = depo
        self.bosluk_var = False
        self.sayfa_kullan = sayfa_kullan
        self.sayfa_uyarilari: list[str] = []
        self._sayfa_tarihleri: list[datetime] = []

    def _durum(self, anahtar, varsayilan=None):
        return self.depo.durum_al(anahtar, varsayilan) if self.depo else varsayilan

    def _durum_yaz(self, anahtar, deger) -> None:
        if self.depo:
            self.depo.durum_yaz(anahtar, deger)

    @staticmethod
    def _tarihler(xml_bayt: bytes) -> list[datetime]:
        tarihler = []
        for m in re.finditer(rb"<pubDate>([^<]+)</pubDate>", xml_bayt):
            try:
                tarihler.append(parsedate_to_datetime(m.group(1).decode()).astimezone(timezone.utc))
            except (TypeError, ValueError):
                pass
        return tarihler

    def _bosluk_kontrol(self, tarihler: list[datetime]) -> None:
        """'nouveaux' listesindeki en eski ilan, önceki turda gördüğümüz en yeni ilandan daha
        yeniyse aradaki ilanları kaçırmış olabiliriz -> tüm yedek akışlar okunur."""
        if not tarihler:
            return
        onceki = self._durum("dealabs_son_ilan")
        if onceki and min(tarihler) > datetime.fromisoformat(onceki):
            self.bosluk_var = True
        self._durum_yaz("dealabs_son_ilan", max(tarihler).isoformat())

    def _yedekler(self) -> list[str]:
        """Bu turda okunacak yedek akışlar: boşluk varsa hepsi, yoksa sırayla birkaç tanesi."""
        if not self.yedek_akislar:
            return []
        if self.bosluk_var:
            return list(self.yedek_akislar)
        sira = int(self._durum("dealabs_yedek_sira", 0))
        n = min(self.yedek_her_tarama, len(self.yedek_akislar))
        self._durum_yaz("dealabs_yedek_sira", (sira + n) % len(self.yedek_akislar))
        return [self.yedek_akislar[(sira + i) % len(self.yedek_akislar)] for i in range(n)]

    def _akisi_getir(self, akis: str, sayfa: bool = True) -> list[Teklif]:
        """Önce liste sayfası (normal fiyat, kargo, derece içerir), olmazsa RSS."""
        if self.sayfa_kullan and sayfa:
            try:
                kod, govde = self.getir(self.SAYFA_TABAN + SAYFA_YOLLARI.get(akis, akis))
                if kod == 200:
                    teklifler = self.ayristir_sayfa(govde, akis)
                    if teklifler is not None:
                        if akis == "nouveaux":
                            self._bosluk_kontrol(self._sayfa_tarihleri)
                        return teklifler
            except KaynakHatasi:
                pass
            self.sayfa_uyarilari.append(f"Dealabs sayfası '{akis}' okunamadı, RSS kullanıldı")
        kod, govde = self.getir(self.TABAN + akis)
        if kod != 200:
            raise KaynakHatasi(f"Dealabs akışı '{akis}' HTTP {kod} döndü")
        if akis == "nouveaux":
            self._bosluk_kontrol(self._tarihler(govde))
        return self.ayristir(govde, akis)

    def _akisi_oku(self, akis: str, sonuc: dict[str, Teklif], sayfa: bool = True) -> None:
        for t in self._akisi_getir(akis, sayfa):
            if t.urun_anahtari in sonuc:  # aynı ilan birden çok akışta: bilgileri birleştir
                eski = sonuc[t.urun_anahtari]
                eski.sinyaller = sorted(set(eski.sinyaller + t.sinyaller))
                if t.derece is not None and (eski.derece is None or t.derece > eski.derece):
                    eski.derece = t.derece
                if eski.normal_fiyat_beyan is None:
                    eski.normal_fiyat_beyan = t.normal_fiyat_beyan
                if eski.kargo is None:
                    eski.kargo = t.kargo
            else:
                sonuc[t.urun_anahtari] = t

    def teklifleri_al(self) -> list[Teklif]:
        sonuc: dict[str, Teklif] = {}
        hatalar = []
        self.bosluk_var = False
        self.sayfa_uyarilari = []
        # Önce ana akışlar (boşluk kontrolü burada yapılır), sonra yedekler
        for akis in self.akislar:
            try:
                self._akisi_oku(akis, sonuc)
            except KaynakHatasi as e:
                hatalar.append(str(e))
        # Kategori sayfaları beğeniye göre sıralı (en yeniler görünmez), bu yüzden yedekler RSS'ten
        for akis in self._yedekler():
            if akis in self.akislar:
                continue
            try:
                self._akisi_oku(akis, sonuc, sayfa=False)
            except KaynakHatasi as e:
                hatalar.append(str(e))
        if hatalar and not sonuc:
            raise KaynakHatasi("; ".join(hatalar))
        self.son_hatalar = hatalar + self.sayfa_uyarilari
        return list(sonuc.values())

    def ayristir(self, xml_bayt: bytes, akis: str = "") -> list[Teklif]:
        """RSS akışını ayrıştırır (yedek yol: liste sayfası okunamazsa)."""
        try:
            kok = ET.fromstring(xml_bayt)
        except ET.ParseError as e:
            raise KaynakHatasi(f"Dealabs RSS okunamadı: {e}") from e
        teklifler = []
        for item in kok.iter("item"):
            satici_el = item.find(PEPPER_NS + "merchant")
            magaza = (satici_el.get("name") if satici_el is not None else "") or ""
            if self.sadece_amazon and "amazon" not in magaza.lower():
                continue
            baslik = html.unescape((item.findtext("title") or "").strip())
            # 'tendance' akışında başlık "129° - Ürün adı" biçiminde: dereceyi ayır
            dm = DERECE_DESENI.match(baslik)
            derece = int(dm.group(1)) if dm else None
            if dm:
                baslik = baslik[dm.end():]
            try:
                zaman = parsedate_to_datetime(item.findtext("pubDate") or "").astimezone(timezone.utc)
            except (TypeError, ValueError):
                zaman = datetime.now(timezone.utc)
            bag = (item.findtext("link") or "").strip()
            t = self._teklif_yap(
                ilan_no=bag.rstrip("/").rsplit("-", 1)[-1], baslik=baslik,
                aciklama=item.findtext("description") or "",
                fiyat=eur_oku(satici_el.get("price") if satici_el is not None else None),
                ilan_bag=bag, zaman=zaman, kategori=item.findtext("category") or "", akis=akis,
                derece=derece)
            if t:
                teklifler.append(t)
        return teklifler

    def ayristir_sayfa(self, html_bayt: bytes, akis: str = "") -> list[Teklif] | None:
        """Dealabs liste sayfasındaki ilan kartlarının verisini okur. Bu veri RSS'ten zengindir:
        ilanı paylaşanın yazdığı normal fiyat, kargo, derece ve mağaza adresi (amazon.fr mi?).
        Hiç ilan kartı bulunamazsa None döner (sayfa düzeni değişmiş olabilir -> RSS'e düşülür)."""
        metin = html_bayt.decode("utf-8", "replace")
        teklifler: list[Teklif] = []
        tarihler: list[datetime] = []
        bulundu = False
        for m in VUE_DESENI.finditer(metin):
            try:
                veri = json.loads(html.unescape(m.group(1)))
            except ValueError:
                continue
            if veri.get("name") != "ThreadMainListItemNormalizer":
                continue
            th = (veri.get("props") or {}).get("thread") or {}
            if th.get("type") != "Deal" or not th.get("threadId"):
                continue
            bulundu = True
            zaman = (datetime.fromtimestamp(th["publishedAt"], tz=timezone.utc)
                     if isinstance(th.get("publishedAt"), (int, float)) and th["publishedAt"] > 0
                     else datetime.now(timezone.utc))
            tarihler.append(zaman)
            if th.get("isExpired") or th.get("status") not in (None, "Activated"):
                continue
            magaza = ((th.get("merchant") or {}).get("merchantName") or "").lower()
            alan = (th.get("linkHost") or "").lower()
            if self.sadece_amazon:
                if alan and "amazon." in alan and not alan.endswith("amazon.fr"):
                    continue  # amazon.de / .it / .es ilanları
                if "amazon" not in magaza and not alan.endswith("amazon.fr"):
                    continue
            kargo_v = th.get("shipping") or {}
            kargo = 0.0 if kargo_v.get("isFree") else (
                float(kargo_v["price"]) if isinstance(kargo_v.get("price"), (int, float)) and kargo_v["price"] > 0
                else None)
            fiyat = th.get("price") if isinstance(th.get("price"), (int, float)) and th["price"] > 0 else None
            normal = th.get("nextBestPrice")
            t = self._teklif_yap(
                ilan_no=str(th["threadId"]), baslik=html.unescape(th.get("title") or ""), aciklama="",
                fiyat=float(fiyat) if fiyat else None,
                ilan_bag=f"https://www.dealabs.com/bons-plans/{th.get('titleSlug', '')}-{th['threadId']}",
                zaman=zaman, kategori=((th.get("mainGroup") or {}).get("threadGroupName") or ""), akis=akis,
                derece=int(th["temperature"]) if isinstance(th.get("temperature"), (int, float)) else None,
                kargo=kargo,
                normal_fiyat=float(normal) if isinstance(normal, (int, float)) and normal > 0 else None,
                kupon_kodu=th.get("voucherCode") or "")
            if t:
                teklifler.append(t)
        self._sayfa_tarihleri = tarihler
        return teklifler if bulundu else None

    def _teklif_yap(self, ilan_no: str, baslik: str, aciklama: str, fiyat: float | None, ilan_bag: str,
                    zaman: datetime, kategori: str, akis: str, derece: int | None,
                    kargo: float | None = None, normal_fiyat: float | None = None,
                    kupon_kodu: str = "") -> Teklif | None:
        if self.max_yas_saat and zaman < datetime.now(timezone.utc) - timedelta(hours=self.max_yas_saat):
            return None
        m = ASIN_DESENI.search(aciklama)
        asin = m.group(1) if m else None
        b_kucuk = baslik.lower()
        if "vendeur tiers" in b_kucuk or "marketplace" in b_kucuk:
            satici = SATICI_PAZARYERI
        elif "vendu par amazon" in b_kucuk or "expédié et vendu par amazon" in aciklama.lower():
            satici = SATICI_AMAZON
        else:
            satici = SATICI_BILINMIYOR  # 'Amazon' mağazası, satıcının Amazon olduğu anlamına gelmez
        durum = DURUM_KULLANILMIS if re.search(r"reconditionn|occasion|seconde main|warehouse",
                                               b_kucuk) else DURUM_YENI
        notlar = []
        if re.search(r"\blot de\b|\bx\d\b|\bpack\b|\bbundle\b", b_kucuk):
            notlar.append("Paket/lot ilanı olabilir; birim fiyatı kontrol edin")
        if kupon_kodu:
            notlar.append(f"Fiyat için kod gerekli: {kupon_kodu}")
        elif "coupon" in b_kucuk or "code promo" in b_kucuk or "via " in b_kucuk:
            notlar.append("Fiyat kupon/kod/koşul içerebilir (ilanı okuyun)")
        if asin:
            amazon_bag = f"https://www.amazon.fr/dp/{asin}"
        elif ilan_no.isdigit():
            # Dealabs'ın "Voir le deal" yönlendirmesi: tıklayınca doğrudan Amazon ürün sayfası açılır.
            # Program bu adresi kendisi ZİYARET ETMEZ (robots.txt /visit/ yolunu botlara kapatıyor);
            # sadece mesaja koyar, tıklayan kişi sizsiniz.
            amazon_bag = f"https://www.dealabs.com/visit/threadmain/{ilan_no}"
        else:
            amazon_bag = "https://www.amazon.fr/s?k=" + urllib.parse.quote_plus(baslik[:120])
            notlar.append("ASIN bilinmiyor: bağlantı Amazon.fr araması; doğru ürün/varyantı kontrol edin")
        sinyal = {"groupe/erreur-de-prix": "erreur_de_prix", "tendance": "tendance"}.get(akis)
        return Teklif(
            kaynak=self.ad,
            urun_anahtari=f"dealabs:{ilan_no}",
            baslik=baslik,
            fiyat=fiyat,
            bag=amazon_bag,
            kontrol_zamani=zaman,
            asin=asin,
            kargo=kargo,
            durum=durum,
            satici=satici,
            stokta=None,
            kategori=kategori,
            sinyaller=[s for s in [sinyal] if s] + (
                ["baslik_hata"] if HATA_KELIMELERI.search(f"{b_kucuk} {aciklama.lower()}") else []),
            notlar=notlar,
            ek_bag=ilan_bag,
            derece=derece,
            normal_fiyat_beyan=normal_fiyat,
        )


# ---------------------------------------------------------------- Keepa

KEEPA_TABAN = "https://api.keepa.com/"
KEEPA_ZAMAN_FARKI = 21564000  # Keepa dakikası -> Unix dakikası


def keepa_zaman(dakika: int) -> datetime:
    return datetime.fromtimestamp((dakika + KEEPA_ZAMAN_FARKI) * 60, tz=timezone.utc)


def _sent(deger) -> float | None:
    """Keepa fiyatları euro sent cinsindendir; -1/-2 = veri yok."""
    if deger is None or not isinstance(deger, (int, float)) or deger < 0:
        return None
    return round(deger / 100, 2)


def _dizi(d, i):
    try:
        return d[i]
    except (IndexError, TypeError, KeyError):
        return None


class KeepaKaynagi:
    """Keepa API istemcisi. Her yanıttaki token bilgisi depoya yazılır."""
    ad = "keepa"
    FIRSAT_MALIYETI = 5   # her /deal sayfası (150 fırsata kadar)
    URUN_MALIYETI = 1     # her ürün (stats/history ek ücretsiz)

    def __init__(self, anahtar: str, depo, ayar: dict, getir=http_getir):
        self.anahtar = anahtar
        self.depo = depo
        self.ayar = ayar
        self.getir = getir

    # -- düşük seviye
    def _istek(self, yol: str, parametreler: dict, tahmini_maliyet: int) -> dict:
        butce = int(self.ayar.get("gunluk_token_butcesi", 0))
        if butce and self.depo.bugun_harcanan_token() + tahmini_maliyet > butce:
            raise TokenBitti(f"Günlük Keepa token bütçesi ({butce}) doldu", self._gun_sonuna_saniye())
        bekle_kadar = self.depo.durum_al("keepa_bekle_kadar")
        if bekle_kadar and datetime.fromisoformat(bekle_kadar) > datetime.now(timezone.utc):
            kalan = (datetime.fromisoformat(bekle_kadar) - datetime.now(timezone.utc)).total_seconds()
            raise TokenBitti("Keepa tokenları dolana kadar bekleniyor", kalan)

        url = KEEPA_TABAN + yol + "?" + urllib.parse.urlencode({"key": self.anahtar, **parametreler})
        try:
            kod, govde = self.getir(url)
        except KaynakHatasi as e:
            raise KaynakHatasi(gizle(str(e), self.anahtar)) from None
        try:
            veri = json.loads(govde.decode("utf-8") or "{}")
        except ValueError:
            veri = {}
        self.depo.api_kaydet("keepa", yol, veri.get("tokensConsumed"), veri.get("tokensLeft"))

        if kod == 429 or (veri.get("tokensLeft") is not None and veri["tokensLeft"] < 0 and kod != 200):
            bekle = max(60.0, (veri.get("refillIn") or 60000) / 1000)
            self._bekle_yaz(bekle)
            raise TokenBitti(f"Keepa tokenları tükendi (kalan: {veri.get('tokensLeft')})", bekle)
        if kod != 200:
            hata = veri.get("error") or {}
            raise KaynakHatasi(gizle(f"Keepa HTTP {kod}: {hata.get('type', '')} {hata.get('message', '')}",
                                     self.anahtar))
        if veri.get("tokensLeft") is not None and veri["tokensLeft"] <= 0:
            self._bekle_yaz(max(60.0, (veri.get("refillIn") or 60000) / 1000))
        return veri

    def _bekle_yaz(self, saniye: float) -> None:
        self.depo.durum_yaz("keepa_bekle_kadar",
                            (datetime.now(timezone.utc) + timedelta(seconds=saniye)).isoformat())

    @staticmethod
    def _gun_sonuna_saniye() -> float:
        simdi = datetime.now(timezone.utc)
        yarin = (simdi + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        return (yarin - simdi).total_seconds()

    # -- tarama
    def teklifleri_al(self) -> list[Teklif]:
        adaylar: dict[str, dict] = {}
        sayfa_sayisi = int(self.ayar.get("tarama_basina_firsat_sayfasi", 1))
        fiyat_turleri = self.ayar.get("fiyat_turleri", [0])
        # Kaldığı yerden devam: fiyat türleri ve sayfalar sırayla dolaşılır.
        imlec = self.depo.durum_al("keepa_imlec", {"tur_sira": 0, "sayfa": 0})
        for _ in range(sayfa_sayisi):
            tur = fiyat_turleri[imlec["tur_sira"] % len(fiyat_turleri)]
            dr = self.firsatlar(tur, imlec["sayfa"])
            for d in dr:
                adaylar.setdefault(d["asin"], d)
            if len(dr) < 150 or imlec["sayfa"] >= 4:
                imlec = {"tur_sira": imlec["tur_sira"] + 1, "sayfa": 0}
            else:
                imlec["sayfa"] += 1
            self.depo.durum_yaz("keepa_imlec", imlec)

        # En büyük düşüşleri ürün geçmişiyle ayrıntılı incele (1 token / ürün)
        sirali = sorted(adaylar.values(), key=lambda d: d.get("_dusus", 0), reverse=True)
        limit = int(self.ayar.get("tarama_basina_urun_sorgusu", 10))
        asinler = [d["asin"] for d in sirali[:limit]]
        return self.urunler(asinler) if asinler else []

    def firsatlar(self, fiyat_turu: int, sayfa: int = 0) -> list[dict]:
        secim = {
            "page": sayfa, "domainId": 4, "priceTypes": [fiyat_turu], "dateRange": 0,
            "deltaPercentRange": [max(10, int(self.ayar.get("min_dusus_yuzde", 40))), 100],
            "currentRange": [int(self.ayar.get("min_fiyat_eur", 15) * 100),
                             int(self.ayar.get("max_fiyat_eur", 5000) * 100)],
            "isRangeEnabled": True, "isFilterEnabled": False, "hasReviews": False,
            "filterErotic": True, "singleVariation": True, "sortType": 4,
        }
        veri = self._istek("deal", {"selection": json.dumps(secim, separators=(",", ":"))},
                           self.FIRSAT_MALIYETI)
        sonuc = []
        for d in (veri.get("deals") or {}).get("dr") or []:
            if not d.get("asin"):
                continue
            yuzde = _dizi(_dizi(d.get("deltaPercent"), 0), fiyat_turu) or 0
            d["_dusus"] = yuzde
            sonuc.append(d)
        return sonuc

    def urunler(self, asinler: list[str]) -> list[Teklif]:
        veri = self._istek("product", {"domain": 4, "asin": ",".join(asinler), "stats": 180,
                                       "history": 1, "days": 180},
                           self.URUN_MALIYETI * len(asinler))
        return [t for t in (self.urunu_cevir(p) for p in veri.get("products") or []) if t]

    @staticmethod
    def urunu_cevir(p: dict) -> Teklif | None:
        asin = p.get("asin")
        stats = p.get("stats") or {}
        guncel = stats.get("current") or []
        amazon = _sent(_dizi(guncel, 0))
        yeni = _sent(_dizi(guncel, 1))
        kullanilmis = _sent(_dizi(guncel, 2))
        if amazon is None and yeni is None and kullanilmis is None:
            return None

        notlar: list[str] = []
        kargo = None
        if amazon is not None and (yeni is None or amazon <= yeni):
            fiyat, tur, durum, satici = amazon, 0, DURUM_YENI, SATICI_AMAZON
            kargo = 0.0 if fiyat >= 35 else None  # Amazon.fr ücretsiz kargo eşiği; altında belirsiz
        elif yeni is not None:
            fiyat, tur, durum = yeni, 1, DURUM_YENI
            fba = _sent(_dizi(guncel, 10))
            satici = SATICI_FBA if fba is not None and abs(fba - yeni) < 0.01 else SATICI_PAZARYERI
            fbm_kargolu = _dizi(guncel, 7)
            if satici == SATICI_PAZARYERI and fbm_kargolu and fbm_kargolu > 0:
                kargo = max(0.0, round(fbm_kargolu / 100 - yeni, 2))
        else:
            fiyat, tur, durum, satici = kullanilmis, 2, DURUM_KULLANILMIS, SATICI_PAZARYERI
            notlar.append("Sadece kullanılmış teklif var")

        # Ham geçmiş: csv[tur] = [zaman, fiyat, zaman, fiyat, ...]
        csv = p.get("csv") or []
        ham = _dizi(csv, tur) or []
        noktalar = []
        for i in range(0, len(ham) - 1, 2):
            f = _sent(ham[i + 1])
            if f is not None:
                noktalar.append((keepa_zaman(ham[i]), f))
        # Son nokta güncel fiyatın kendisidir; geçmişe katma
        if noktalar and abs(noktalar[-1][1] - fiyat) < 0.01:
            noktalar = noktalar[:-1]
        gecmis = FiyatGecmisi.noktalardan(noktalar, durum=durum) if noktalar else FiyatGecmisi(durum=durum)
        # Keepa'nın kendi istatistikleri varsa onları tercih et (daha uzun dönem)
        gecmis.ort30 = _sent(_dizi(stats.get("avg30"), tur)) or gecmis.ort30
        gecmis.ort90 = _sent(_dizi(stats.get("avg90"), tur)) or gecmis.ort90
        gecmis.ort180 = _sent(_dizi(stats.get("avg180"), tur)) or gecmis.ort180
        en_dusuk = _dizi(_dizi(stats.get("min"), tur), 1)
        if _sent(en_dusuk) is not None and (gecmis.en_dusuk is None or _sent(en_dusuk) < gecmis.en_dusuk):
            # Güncel fiyat zaten yeni dip ise Keepa 'min' onu da içerebilir; o zaman kendi hesabımız kalsın
            if abs(_sent(en_dusuk) - fiyat) > 0.01:
                gecmis.en_dusuk = _sent(en_dusuk)

        stok_yuzde = _dizi(stats.get("outOfStockPercentage30"), tur)
        stokta = True  # güncel fiyat var = satılık teklif var
        if stok_yuzde is not None and stok_yuzde >= 90:
            notlar.append("Son 30 günde çoğunlukla stok dışı")

        kupon = None
        kupon_veri = p.get("coupon")
        if isinstance(kupon_veri, list) and kupon_veri and isinstance(kupon_veri[0], int) and kupon_veri[0]:
            k = kupon_veri[0]
            kupon = round(k / 100, 2) if k > 0 else round(fiyat * (-k) / 100, 2)
            notlar.append("Kupon bilgisi Keepa'da eski olabilir (pahalı 'offers' sorgusu kullanılmıyor)")

        if p.get("variationCSV") or p.get("parentAsin"):
            notlar.append("Ürünün varyantları var; fiyat seçilen varyanta özgü olabilir")
        liste = _sent(_dizi(guncel, 4))
        kategori = ""
        agac = p.get("categoryTree") or []
        if agac:
            kategori = " / ".join(c.get("name", "") for c in agac[:2])

        return Teklif(
            kaynak="keepa",
            urun_anahtari=asin,
            asin=asin,
            baslik=html.unescape(p.get("title") or asin),
            fiyat=fiyat,
            kargo=kargo,
            kupon=kupon,
            durum=durum,
            satici=satici,
            stokta=stokta,
            kategori=kategori,
            liste_fiyati=liste,
            gecmis=gecmis,
            bag=f"https://www.amazon.fr/dp/{asin}",
            kontrol_zamani=keepa_zaman(p["lastUpdate"]) if p.get("lastUpdate") else datetime.now(timezone.utc),
            notlar=notlar,
        )

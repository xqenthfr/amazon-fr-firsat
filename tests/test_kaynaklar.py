"""Veri kaynağı ayrıştırıcıları ve Telegram mesajı (sentetik veri, ağ yok)."""
from __future__ import annotations

import json
import unittest

from tests.yardimci import gecmis_uret, teklif

from data_sources import (DealabsKaynagi, KaynakHatasi, KeepaKaynagi, baslik_anahtari, eur_oku,
                          gizle)
from price_analyzer import SATICI_AMAZON, SATICI_BILINMIYOR, SATICI_FBA, analiz_et
from telegram_bot import TelegramBot, mesaj_olustur

ORNEK_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss xmlns:pepper="http://www.pepper.com/rss" version="2.0"><channel>
<item><category><![CDATA[High-Tech]]></category><pepper:merchant name="Amazon" price="1 099,99€"/>
<title><![CDATA[Carte graphique RTX TEST 9999 (Vendeur tiers)]]></title>
<description><![CDATA[<strong>1 099,99€ - Amazon</strong> https://www.amazon.fr/dp/B0TEST1234?tag=x]]></description>
<link>https://www.dealabs.com/bons-plans/carte-graphique-rtx-test-1111111</link>
<pubDate>Thu, 29 Oct 2026 21:05:59 +0100</pubDate></item>
<item><category><![CDATA[Mode]]></category><pepper:merchant name="Kiabi" price="9,99€"/>
<title><![CDATA[T-shirt]]></title><link>https://www.dealabs.com/bons-plans/t-shirt-2222222</link>
<pubDate>Thu, 29 Oct 2026 21:00:00 +0100</pubDate></item>
<item><category><![CDATA[Électroménager]]></category><pepper:merchant name="Amazon" price="45€"/>
<title><![CDATA[Friteuse Ninja TEST lot de 2]]></title><description><![CDATA[x]]></description>
<link>https://www.dealabs.com/bons-plans/friteuse-ninja-3333333</link>
<pubDate>Thu, 29 Oct 2026 20:00:00 +0100</pubDate></item>
</channel></rss>""".encode("utf-8")


def ornek_sayfa() -> bytes:
    """Dealabs liste sayfasını taklit eden sentetik HTML (gerçek veri değil)."""
    import html as h
    import time
    simdi = int(time.time())

    def kart(no, magaza, alan, fiyat, normal, suresi_doldu=False, derece=12.5):
        veri = {"name": "ThreadMainListItemNormalizer", "props": {"thread": {
            "threadId": str(no), "titleSlug": f"urun-{no}", "title": f"Aspirateur Dyson TEST {no} l'original",
            "status": "Activated", "isExpired": suresi_doldu, "temperature": derece, "type": "Deal",
            "publishedAt": simdi - 600, "voucherCode": "ABC10" if no == 900001 else "", "linkHost": alan,
            "merchant": {"merchantName": magaza}, "mainGroup": {"threadGroupName": "Électroménager"},
            "price": fiyat, "nextBestPrice": normal, "shipping": {"isFree": True, "price": 0}}}}
        return f"<div class=\"js-vue3\" data-vue3='{h.escape(json.dumps(veri), quote=True)}'></div>"

    return ("<html><body>" + kart(900001, "Amazon", "www.amazon.fr", 40, 100, derece=345.7)
            + kart(900002, "Amazon", "www.amazon.de", 30, 90)
            + kart(900003, "Amazon", "www.amazon.fr", 20, 80, suresi_doldu=True)
            + kart(900004, "Fnac", "www.fnac.com", 10, 50)
            + "<div data-vue3='{\"name\":\"Baska\"}'></div></body></html>").encode("utf-8")


class Dealabs(unittest.TestCase):
    def test_ayristirma(self):
        tek = DealabsKaynagi(["groupe/erreur-de-prix"], max_yas_saat=0).ayristir(ORNEK_RSS, "groupe/erreur-de-prix")
        self.assertEqual(len(tek), 2)  # Kiabi elendi
        gpu, ninja = tek
        self.assertEqual(gpu.fiyat, 1099.99)
        self.assertEqual(gpu.asin, "B0TEST1234")
        self.assertEqual(gpu.bag, "https://www.amazon.fr/dp/B0TEST1234")
        self.assertEqual(gpu.satici, "third_party")
        self.assertEqual(gpu.sinyaller, ["erreur_de_prix"])
        self.assertEqual(ninja.fiyat, 45.0)
        self.assertEqual(ninja.satici, SATICI_BILINMIYOR)
        # ASIN yok: Dealabs yönlendirmesi doğrudan ürün sayfasına gider
        self.assertEqual(ninja.bag, "https://www.dealabs.com/visit/threadmain/3333333")
        self.assertTrue(any("Paket" in n for n in ninja.notlar))

    def test_yonlendirme_ziyaret_edilmez(self):
        """Program /visit/ adresine asla istek atmamalı (robots.txt)."""
        istenen = []

        def getir(url):
            istenen.append(url)
            return 200, ORNEK_RSS
        DealabsKaynagi(["nouveaux"], getir=getir, max_yas_saat=0, sayfa_kullan=False).teklifleri_al()
        self.assertEqual(istenen, ["https://www.dealabs.com/rss/nouveaux"])

    def test_ilan_no_yoksa_arama_baglantisi(self):
        rss = ORNEK_RSS.replace(b"friteuse-ninja-3333333", b"friteuse-ninja")
        ninja = DealabsKaynagi([], max_yas_saat=0).ayristir(rss)[1]
        self.assertTrue(ninja.bag.startswith("https://www.amazon.fr/s?k="))
        self.assertTrue(any("ASIN bilinmiyor" in n for n in ninja.notlar))

    def test_eski_ilanlar_elenir(self):
        # 2020 tarihli ilanlar 48 saatten eski olduğundan elenmeli
        eski = ORNEK_RSS.replace(b"2026", b"2020")
        self.assertEqual(DealabsKaynagi([], max_yas_saat=48).ayristir(eski), [])

    def test_yedek_akislar_sirayla_okunur(self):
        from storage import Depo
        depo = Depo(":memory:")
        istenen = []

        def getir(url):
            istenen.append(url.rsplit("/rss/", 1)[1])
            return 200, ORNEK_RSS
        k = DealabsKaynagi(["nouveaux"], getir=getir, max_yas_saat=0, depo=depo, sayfa_kullan=False,
                           yedek_akislar=["a", "b", "c"], yedek_her_tarama=2)
        k.teklifleri_al()
        k.teklifleri_al()
        self.assertEqual(istenen, ["nouveaux", "a", "b", "nouveaux", "c", "a"])
        self.assertFalse(k.bosluk_var)

    def test_bosluk_varsa_tum_yedekler(self):
        from storage import Depo
        depo = Depo(":memory:")
        # Önceki turda görülen en yeni ilan, şimdiki listenin en eskisinden çok önce
        depo.durum_yaz("dealabs_son_ilan", "2026-10-28T00:00:00+00:00")
        istenen = []

        def getir(url):
            istenen.append(url.rsplit("/rss/", 1)[1])
            return 200, ORNEK_RSS
        k = DealabsKaynagi(["nouveaux"], getir=getir, max_yas_saat=0, depo=depo, sayfa_kullan=False,
                           yedek_akislar=["a", "b", "c"], yedek_her_tarama=1)
        k.teklifleri_al()
        self.assertTrue(k.bosluk_var)
        self.assertEqual(istenen, ["nouveaux", "a", "b", "c"])

    def test_baslikta_hata_sinyali(self):
        rss = ORNEK_RSS.replace(b"Friteuse Ninja TEST lot de 2", b"Friteuse Ninja TEST (erreur de prix ?)")
        ninja = DealabsKaynagi([], max_yas_saat=0).ayristir(rss, "nouveaux")[1]
        self.assertIn("baslik_hata", ninja.sinyaller)
        a = analiz_et(ninja)
        self.assertIn("doğrulanmadı", a.etiket)
        self.assertLessEqual(a.puan, 70)

    def test_derece_ayiklama_ve_birlesme(self):
        sicak = ORNEK_RSS.replace(b"[CDATA[Friteuse Ninja", b"[CDATA[412\xc2\xb0 - Friteuse Ninja")

        def getir(url):
            return 200, (sicak if url.endswith("tendance") else ORNEK_RSS)
        tek = DealabsKaynagi(["nouveaux", "tendance"], getir=getir, max_yas_saat=0, sayfa_kullan=False).teklifleri_al()
        ninja = [t for t in tek if "Ninja" in t.baslik][0]
        self.assertEqual(ninja.derece, 412)
        self.assertTrue(ninja.baslik.startswith("Friteuse Ninja"))
        self.assertIn("tendance", ninja.sinyaller)

    def test_liste_sayfasi(self):
        sayfa = ornek_sayfa()
        tek = DealabsKaynagi([], max_yas_saat=48).ayristir_sayfa(sayfa, "nouveaux")
        self.assertEqual([t.urun_anahtari for t in tek], ["dealabs:900001"])  # .de, süresi dolmuş, Fnac elendi
        t = tek[0]
        self.assertEqual((t.fiyat, t.normal_fiyat_beyan, t.kargo, t.derece), (40.0, 100.0, 0.0, 345))
        self.assertEqual(t.bag, "https://www.dealabs.com/visit/threadmain/900001")
        self.assertTrue(any("ABC10" in n for n in t.notlar))
        a = analiz_et(t)
        self.assertEqual(a.indirim_yuzde, 60.0)
        self.assertLessEqual(a.puan, 70)

    def test_sayfa_bozuksa_rss_kullanilir(self):
        def getir(url):
            if "/rss/" in url:
                return 200, ORNEK_RSS
            return 200, b"<html>yeni tasarim</html>"
        k = DealabsKaynagi(["nouveaux"], getir=getir, max_yas_saat=0)
        self.assertEqual(len(k.teklifleri_al()), 2)
        self.assertTrue(any("RSS kullanıldı" in h for h in k.son_hatalar))

    def test_sayfa_varsa_rss_istenmez(self):
        istenen = []

        def getir(url):
            istenen.append(url)
            return 200, ornek_sayfa()
        DealabsKaynagi(["nouveaux", "tendance"], getir=getir).teklifleri_al()
        self.assertEqual(istenen, ["https://www.dealabs.com/nouveaux", "https://www.dealabs.com/hot"])

    def test_yedekler_rssten_okunur(self):
        istenen = []

        def getir(url):
            istenen.append(url)
            return 200, (ORNEK_RSS if "/rss/" in url else ornek_sayfa())
        DealabsKaynagi(["nouveaux"], getir=getir, yedek_akislar=["groupe/dyson"]).teklifleri_al()
        self.assertEqual(istenen, ["https://www.dealabs.com/nouveaux", "https://www.dealabs.com/rss/groupe/dyson"])

    def test_bozuk_xml(self):
        with self.assertRaises(KaynakHatasi):
            DealabsKaynagi([]).ayristir(b"<rss><item>")

    def test_akis_hatasi_digerini_engellemez(self):
        def getir(url):
            if url.endswith("tendance"):
                return 503, b""
            return 200, ORNEK_RSS
        k = DealabsKaynagi(["nouveaux", "tendance"], getir=getir, max_yas_saat=0, sayfa_kullan=False)
        self.assertEqual(len(k.teklifleri_al()), 2)
        self.assertEqual(len(k.son_hatalar), 1)

    def test_eur_oku(self):
        self.assertEqual(eur_oku("1 299,99€"), 1299.99)
        self.assertEqual(eur_oku("19.99 €"), 19.99)
        self.assertEqual(eur_oku("1.299€"), 1299.0)
        self.assertEqual(eur_oku("45€"), 45.0)
        self.assertIsNone(eur_oku("gratuit"))

    def test_baslik_anahtari(self):
        self.assertEqual(baslik_anahtari("Friteuse Ninja AF300 - 99,99€ (via coupon)"),
                         baslik_anahtari("friteuse ninja af300 – 89,99 €"))


def keepa_urunu(fiyat_sent=4500, gecmis_sent=15000, amazon=True):
    # 180 gün boyunca günde bir nokta, Keepa dakika biçiminde
    son = 7_400_000
    csv0 = []
    for i in range(180):
        csv0 += [son - (180 - i) * 1440, gecmis_sent]
    csv0 += [son, fiyat_sent]
    guncel = [-1] * 20
    if amazon:
        guncel[0] = fiyat_sent
    guncel[1] = fiyat_sent if not amazon else fiyat_sent + 100
    guncel[10] = guncel[1]
    return {
        "asin": "B0TEST5678", "title": "Aspirateur Dyson TEST", "lastUpdate": son,
        "categoryTree": [{"catId": 1, "name": "Cuisine et Maison"}, {"catId": 2, "name": "Aspirateurs"}],
        "csv": [csv0 if amazon else None, csv0],
        "stats": {"current": guncel, "avg30": [gecmis_sent] * 20, "avg90": [gecmis_sent] * 20,
                  "avg180": [gecmis_sent] * 20, "min": [[son - 99999, gecmis_sent - 500]] * 20,
                  "outOfStockPercentage30": [0] * 20},
    }


class Keepa(unittest.TestCase):
    def test_urun_cevirme(self):
        t = KeepaKaynagi.urunu_cevir(keepa_urunu())
        self.assertEqual(t.fiyat, 45.0)
        self.assertEqual(t.satici, SATICI_AMAZON)
        self.assertEqual(t.bag, "https://www.amazon.fr/dp/B0TEST5678")
        self.assertEqual(t.gecmis.ort90, 150.0)
        self.assertEqual(t.gecmis.en_dusuk, 145.0)
        a = analiz_et(t)
        self.assertGreaterEqual(a.puan, 90)

    def test_pazar_yeri_fba(self):
        t = KeepaKaynagi.urunu_cevir(keepa_urunu(amazon=False))
        self.assertEqual(t.satici, SATICI_FBA)

    def test_fiyat_yoksa_atla(self):
        p = keepa_urunu()
        p["stats"]["current"] = [-1] * 20
        self.assertIsNone(KeepaKaynagi.urunu_cevir(p))

    def test_tam_akis_ve_token_kaydi(self):
        from storage import Depo
        import config
        depo = Depo(":memory:")
        yanitlar = [
            (200, json.dumps({"tokensLeft": 95, "tokensConsumed": 5,
                              "deals": {"dr": [{"asin": "B0TEST5678", "deltaPercent": [[70] * 20]}]}}).encode()),
            (200, json.dumps({"tokensLeft": 94, "tokensConsumed": 1, "products": [keepa_urunu()]}).encode()),
        ]
        urller = []

        def getir(url):
            urller.append(url)
            return yanitlar.pop(0)

        k = KeepaKaynagi("ANAHTAR123", depo, dict(config.VARSAYILAN_AYARLAR["keepa"]), getir=getir)
        sonuc = k.teklifleri_al()
        self.assertEqual(len(sonuc), 1)
        self.assertIn("domain=4", urller[1])
        self.assertIn("%22domainId%22%3A4", urller[0])
        self.assertEqual(depo.bugun_harcanan_token(), 6)
        self.assertEqual(depo.durum_al("keepa_imlec"), {"tur_sira": 1, "sayfa": 0})


class Telegram(unittest.TestCase):
    def test_mesaj_icerigi(self):
        t = teklif(45, gecmis_uret([150] * 180), baslik="Dyson <V15> & TEST")
        m = mesaj_olustur(t, analiz_et(t))
        for parca in ["Dyson &lt;V15&gt; &amp; TEST", "45,00 €", "150,00 €", "İndirim: %70", "puan <b>",
                      "Satıcı: Amazon", "Durum: Yeni", "Kontrol:", "https://www.amazon.fr/dp/TEST000001",
                      "Neden dikkat çekti"]:
            self.assertIn(parca, m)

    def test_eksik_veri_mesajda(self):
        t = teklif(45, None, kargo=None)
        m = mesaj_olustur(t, analiz_et(t))
        self.assertIn("veri yok", m)
        self.assertIn("Eksik veri", m)

    def test_gonderim_ve_gizleme(self):
        istekler = []

        def getir(url):
            istekler.append(url)
            return 401, json.dumps({"ok": False, "description": "Unauthorized"}).encode()

        bot = TelegramBot("123:GIZLI", "42", getir=getir)
        with self.assertRaises(KaynakHatasi) as c:
            bot.gonder("x")
        self.assertNotIn("GIZLI", str(c.exception))

    def test_hiz_siniri(self):
        yanitlar = [(429, json.dumps({"ok": False, "parameters": {"retry_after": 3}}).encode()),
                    (200, json.dumps({"ok": True}).encode())]
        uykular = []
        bot = TelegramBot("t", "1", getir=lambda u: yanitlar.pop(0), uyku=uykular.append)
        bot.gonder("x")
        self.assertEqual(uykular, [3])

    def test_gizle(self):
        self.assertEqual(gizle("https://api.keepa.com/deal?key=abc&x=1"), "https://api.keepa.com/deal?key=***&x=1")


if __name__ == "__main__":
    unittest.main()

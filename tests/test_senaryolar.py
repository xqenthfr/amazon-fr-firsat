"""İstenen 8 senaryo, sentetik verilerle. Hiçbiri gerçek ağa çıkmaz."""
from __future__ import annotations

import json
import unittest
import urllib.error
from datetime import datetime, timedelta, timezone

from tests.yardimci import SahteBot, SahteKaynak, gecmis_uret, teklif

import config
from data_sources import KaynakHatasi, KeepaKaynagi, TokenBitti, http_getir
from price_analyzer import DURUM_KULLANILMIS, SATICI_PAZARYERI, FiyatGecmisi, analiz_et, prime_uygula
from scanner import Tarayici
from storage import Depo


def ayarlar(**ek):
    a = config.ayarlari_yukle(dosya=config.PROJE_KLASORU / "olmayan_dosya.json")
    a.update(ek)
    return a


class S1_BuyukDusus(unittest.TestCase):
    """1. 150 € civarında satılan ürün 45 €'ya düşüyor."""

    def test_150den_45e(self):
        g = gecmis_uret([150, 149, 152, 148, 150] * 36)  # 180 gün ~150 €
        a = analiz_et(teklif(45, g))
        self.assertGreaterEqual(a.puan, 90, a)
        self.assertEqual(a.oncelik, "Çok yüksek öncelik")
        self.assertEqual(a.etiket, "Olası fiyat hatası")
        self.assertEqual(a.guven, "yüksek")
        self.assertAlmostEqual(a.indirim_yuzde, 70, delta=1)
        self.assertEqual(a.eksikler, [])


class S2_SikGorulenFiyat(unittest.TestCase):
    """2. Zaten sık sık 45 €'ya satılan ürün: yüksek puan almamalı."""

    def test_sik_45(self):
        g = gecmis_uret([45, 45, 60, 45, 75, 45, 45, 60] * 22)  # zamanın yarısından fazlası 45 €
        a = analiz_et(teklif(45, g))
        self.assertLess(a.puan, 50, a)
        self.assertTrue(any("sık görülüyor" in u for u in a.uyarilar))
        self.assertNotIn("fiyat hatası", a.etiket.lower())


class S3_KullanilmisUrun(unittest.TestCase):
    """3. Kullanılmış ürün, yeni ürün fiyat geçmişiyle karşılaştırılıyor."""

    def test_kullanilmis_yeni_karsilastirma(self):
        g_yeni = gecmis_uret([150] * 180)
        yeni = analiz_et(teklif(45, g_yeni))
        kullanilmis = analiz_et(teklif(45, g_yeni, durum=DURUM_KULLANILMIS, satici=SATICI_PAZARYERI))
        self.assertLess(kullanilmis.puan, 75, kullanilmis)
        self.assertLess(kullanilmis.puan, yeni.puan - 25)
        self.assertEqual(kullanilmis.guven, "düşük")
        self.assertTrue(any("karşılaştırılıyor" in u for u in kullanilmis.uyarilar))
        self.assertNotIn("fiyat hatası", kullanilmis.etiket.lower())

    def test_kullanilmis_kendi_gecmisiyle(self):
        """Kullanılmış geçmişiyle karşılaştırılırsa uyumsuzluk uyarısı çıkmamalı."""
        g = gecmis_uret([100] * 180, durum=DURUM_KULLANILMIS)
        a = analiz_et(teklif(45, g, durum=DURUM_KULLANILMIS))
        self.assertFalse(any("karşılaştırılıyor" in u for u in a.uyarilar))


class S4_YuksekKargo(unittest.TestCase):
    """4. Ürün ucuz ama kargo pahalı: etkin fiyat kargo dahil hesaplanmalı."""

    def test_kargo(self):
        g = gecmis_uret([150] * 180)
        kargosuz = analiz_et(teklif(45, g))
        kargolu = analiz_et(teklif(45, g, kargo=80.0, satici=SATICI_PAZARYERI))
        self.assertEqual(kargolu.etkin_fiyat, 125.0)
        self.assertLess(kargolu.puan, 50, kargolu)
        self.assertLess(kargolu.puan, kargosuz.puan)
        self.assertTrue(any("Kargo yüksek" in u for u in kargolu.uyarilar))

    def test_kargo_bilinmiyor(self):
        a = analiz_et(teklif(45, gecmis_uret([150] * 180), kargo=None))
        self.assertIn("kargo ücreti", a.eksikler)

    def test_prime_amazon_ve_fba_kargosuz(self):
        for satici in ("amazon", "third_party_fba"):
            t = teklif(45, gecmis_uret([150] * 180), kargo=None, satici=satici)
            prime_uygula(t)
            self.assertEqual(t.kargo, 0.0)
            self.assertNotIn("kargo ücreti", analiz_et(t).eksikler)

    def test_prime_pazar_yeri_kargosu_kalir(self):
        """Prime, satıcının kendi gönderdiği üründe geçmez: yüksek kargo yine fiyata eklenir."""
        t = teklif(45, gecmis_uret([150] * 180), kargo=80.0, satici=SATICI_PAZARYERI)
        prime_uygula(t)
        self.assertEqual(analiz_et(t).etkin_fiyat, 125.0)

    def test_prime_satici_bilinmiyor(self):
        t = teklif(45, None, kargo=None, satici="unknown")
        prime_uygula(t)
        a = analiz_et(t)
        self.assertIsNone(t.kargo)
        self.assertNotIn("kargo ücreti", a.eksikler)
        self.assertTrue(any("Prime" in u for u in a.uyarilar))


class S5_EksikGecmis(unittest.TestCase):
    """5. Fiyat geçmişi yok: sahte güven üretilmemeli."""

    def test_gecmis_yok(self):
        a = analiz_et(teklif(45, None))
        self.assertLessEqual(a.puan, 70)
        self.assertEqual(a.guven, "düşük")
        self.assertIn("fiyat geçmişi", a.eksikler)
        self.assertIsNone(a.indirim_yuzde)

    def test_gecmis_yok_ama_topluluk_hata_bildirdi(self):
        a = analiz_et(teklif(45, None, sinyaller=["erreur_de_prix"]))
        self.assertLessEqual(a.puan, 70)
        self.assertIn("doğrulanmadı", a.etiket)
        self.assertEqual(a.guven, "düşük")

    def test_kisa_gecmis_tavan(self):
        a = analiz_et(teklif(45, gecmis_uret([150] * 5)))
        self.assertLessEqual(a.puan, 85)
        self.assertEqual(a.guven, "orta")

    def test_fiyat_yok(self):
        a = analiz_et(teklif(None, None))
        self.assertEqual(a.puan, 0)
        self.assertIn("güncel fiyat", a.eksikler)


class S6_TekrarBildirim(unittest.TestCase):
    """6. Aynı fırsat tekrar bildirilmemeli; fiyat ciddi düşerse yeniden bildirilmeli."""

    def setUp(self):
        self.depo = Depo(":memory:")
        self.bot = SahteBot()

    def _tara(self, fiyat):
        kaynak = SahteKaynak([teklif(fiyat, gecmis_uret([150] * 180))])
        return Tarayici(ayarlar(), self.depo, [kaynak], self.bot).tara()

    def test_tekrar_yok(self):
        self.assertEqual(self._tara(45)["gonderilen"], 1)
        self.assertEqual(self._tara(45)["gonderilen"], 0)
        self.assertEqual(self._tara(44)["gonderilen"], 0)   # %2 düşüş: önemsiz
        self.assertEqual(self._tara(39)["gonderilen"], 1)   # %13 düşüş: yeniden bildir
        self.assertEqual(len(self.bot.gonderilen), 2)

    def test_yeniden_baslatma_sonrasi_da_tekrar_yok(self, ):
        import tempfile, os
        with tempfile.TemporaryDirectory() as d:
            yol = os.path.join(d, "t.db")
            depo = Depo(yol)
            Tarayici(ayarlar(), depo, [SahteKaynak([teklif(45, gecmis_uret([150] * 180))])], self.bot).tara()
            depo.kapat()
            depo = Depo(yol)  # program yeniden başladı
            s = Tarayici(ayarlar(), depo, [SahteKaynak([teklif(45, gecmis_uret([150] * 180))])], self.bot).tara()
            depo.kapat()
            self.assertEqual(s["gonderilen"], 0)
            self.assertEqual(len(self.bot.gonderilen), 1)


class DereceSinyali(unittest.TestCase):
    """Dealabs derecesi: çok beğenilen fırsat bildirilir ama fiyat hatası denmez, tavan 70."""

    def test_derece_esikleri(self):
        def puan(derece, **ek):
            return analiz_et(teklif(45, None, derece=derece, sinyaller=["tendance"],
                                    kontrol_zamani=datetime.now(timezone.utc) - timedelta(hours=24), **ek))
        dusuk, orta, yuksek, cok = puan(80), puan(220), puan(350), puan(900)
        self.assertLess(dusuk.puan, 60)
        self.assertLess(dusuk.puan, orta.puan)
        self.assertLess(orta.puan, yuksek.puan)
        self.assertGreaterEqual(yuksek.puan, 60)     # 300°+ bildirilir
        self.assertLessEqual(cok.puan, 70)           # geçmiş yok: tavan
        self.assertIn("Popüler fırsat", yuksek.etiket)
        self.assertNotIn("hatası", yuksek.etiket)
        self.assertEqual(yuksek.guven, "düşük")

    def test_hizli_isinma_bonusu(self):
        yavas = analiz_et(teklif(45, None, derece=200, kontrol_zamani=datetime.now(timezone.utc) - timedelta(hours=20)))
        hizli = analiz_et(teklif(45, None, derece=200, kontrol_zamani=datetime.now(timezone.utc) - timedelta(hours=1)))
        self.assertEqual(hizli.puan, yavas.puan + 5)


class BildirimKurali(unittest.TestCase):
    """Varsayılan kural: her fiyat hatası şüphesi + en az %50 indirim. Diğerleri bildirilmez."""

    def _tara(self, teklifler):
        bot = SahteBot()
        Tarayici(ayarlar(), Depo(":memory:"), [SahteKaynak(teklifler)], bot).tara()
        return bot.gonderilen

    def test_her_fiyat_hatasi_bildirilir(self):
        # Puanı düşük olsa bile (geçmiş yok, beyan yok) fiyat hatası şüphesi bildirilir
        g = self._tara([teklif(45, None, sinyaller=["baslik_hata"], asin="H1", baslik="Tapis (TEST)",
                               kategori="Sport")])
        self.assertEqual(len(g), 1)
        self.assertIn("Fiyat hatası şüphesi", g[0])

    def test_yuzde_elli_esigi(self):
        g = self._tara([
            teklif(49, None, normal_fiyat_beyan=100.0, asin="A51"),   # %51 -> bildirilir
            teklif(55, None, normal_fiyat_beyan=100.0, asin="A45"),   # %45 -> bildirilmez
            teklif(45, None, derece=900, asin="POP"),                 # çok popüler ama indirim bilinmiyor
        ])
        self.assertEqual(len(g), 1)
        self.assertIn("%51", g[0])

    def test_gecmisle_yuzde_elli(self):
        g = self._tara([teklif(45, gecmis_uret([150] * 180), asin="K1"),     # %70
                        teklif(100, gecmis_uret([150] * 180), asin="K2")])   # %33
        self.assertEqual(len(g), 1)


class TakipKelimeleri(unittest.TestCase):
    """Takip listesindeki ürünler daha düşük puanda da bildirilir; diğerleri bildirilmez."""

    def test_takip_esigi(self):
        depo = Depo(":memory:")
        bot = SahteBot()
        takipli = teklif(45, None, baslik="Aspirateur Dyson V8 (TEST)", sinyaller=["tendance"], asin="A1")
        diger = teklif(45, None, baslik="Tapis de yoga (TEST)", kategori="Sport", sinyaller=["tendance"], asin="A2")
        s = Tarayici(ayarlar(bildirim_kurali="puan", min_puan=60, takip_min_puan=30), depo,
                     [SahteKaynak([takipli, diger])], bot).tara()
        self.assertEqual(s["gonderilen"], 1)
        self.assertIn("Dyson", bot.gonderilen[0])
        self.assertIn("Takip listenizdeki", bot.gonderilen[0])


class S7_BaglantiKesildi(unittest.TestCase):
    """7. İnternet/API bağlantısı kesik: program çökmemeli, tekrar denemeli, sonra devam etmeli."""

    def test_http_tekrar_dener_sonra_hata(self):
        cagri = []

        def kopuk(istek, timeout):
            cagri.append(1)
            raise urllib.error.URLError("ağ yok")

        uykular = []
        with self.assertRaises(KaynakHatasi):
            http_getir("https://ornek.test/x", acici=kopuk, uyku=uykular.append, deneme=3)
        self.assertEqual(len(cagri), 3)
        self.assertEqual(uykular, [2.0, 4.0])  # üstel bekleme

    def test_tarama_cokmez_diger_kaynak_calisir(self):
        depo = Depo(":memory:")
        bot = SahteBot()
        bozuk = SahteKaynak(hata=KaynakHatasi("Bağlantı kurulamadı"))
        saglam = SahteKaynak([teklif(45, gecmis_uret([150] * 180))])
        s = Tarayici(ayarlar(), depo, [bozuk, saglam], bot).tara()
        self.assertEqual(s["hata"], 1)
        self.assertEqual(s["gonderilen"], 1)
        self.assertEqual(depo.gunluk_rapor()["hatalar"][0]["kaynak"], "sahte")

    def test_telegram_kopuk_bildirim_kaybolmaz(self):
        depo = Depo(":memory:")
        kopuk_bot = SahteBot(hata=KaynakHatasi("Telegram'a ulaşılamadı"))
        kaynak = SahteKaynak([teklif(45, gecmis_uret([150] * 180))])
        s = Tarayici(ayarlar(), depo, [kaynak], kopuk_bot).tara()
        self.assertEqual((s["yeni_bildirim"], s["gonderilen"]), (1, 0))
        self.assertEqual(len(depo.bekleyen_bildirimler()), 1)
        # Bağlantı geri geldi: bekleyen bildirim gönderilir, ikinci kez kuyruğa girmez
        iyi_bot = SahteBot()
        s = Tarayici(ayarlar(), depo, [kaynak], iyi_bot).tara()
        self.assertEqual((s["yeni_bildirim"], s["gonderilen"]), (0, 1))
        self.assertEqual(len(iyi_bot.gonderilen), 1)
        self.assertEqual(len(depo.bekleyen_bildirimler()), 0)


class S8_TokenBitti(unittest.TestCase):
    """8. Keepa tokenları tükendi: istek atmayı bırakmalı, bekleme süresini hatırlamalı."""

    def _keepa(self, depo, yanitlar, **ayar):
        cagrilar = []

        def getir(url):
            cagrilar.append(url)
            return yanitlar.pop(0)

        a = dict(config.VARSAYILAN_AYARLAR["keepa"], **ayar)
        return KeepaKaynagi("GIZLI_TEST_ANAHTARI", depo, a, getir=getir), cagrilar

    def test_429_sonrasi_bekler(self):
        depo = Depo(":memory:")
        govde = json.dumps({"tokensLeft": -12, "refillIn": 45000, "refillRate": 20, "tokensConsumed": 0}).encode()
        keepa, cagrilar = self._keepa(depo, [(429, govde)])
        with self.assertRaises(TokenBitti) as c:
            keepa.firsatlar(0)
        self.assertGreaterEqual(c.exception.bekleme_saniye, 60)
        self.assertNotIn("GIZLI_TEST_ANAHTARI", str(c.exception))
        # İkinci çağrı ağa hiç çıkmadan reddedilir (token boşa harcanmaz)
        with self.assertRaises(TokenBitti):
            keepa.firsatlar(0)
        self.assertEqual(len(cagrilar), 1)
        # Program yeniden başlasa bile bekleme hatırlanır
        keepa2, cagrilar2 = self._keepa(depo, [])
        with self.assertRaises(TokenBitti):
            keepa2.firsatlar(0)
        self.assertEqual(cagrilar2, [])

    def test_gunluk_butce(self):
        depo = Depo(":memory:")
        depo.api_kaydet("keepa", "deal", 98, 500)
        keepa, cagrilar = self._keepa(depo, [], gunluk_token_butcesi=100)
        with self.assertRaises(TokenBitti):
            keepa.firsatlar(0)  # 98 + 5 > 100
        self.assertEqual(cagrilar, [])

    def test_tarama_token_bitince_cokmez(self):
        depo = Depo(":memory:")
        govde = json.dumps({"tokensLeft": -1, "refillIn": 30000}).encode()
        keepa, _ = self._keepa(depo, [(429, govde)])
        s = Tarayici(ayarlar(), depo, [keepa], SahteBot()).tara()
        self.assertEqual(s["hata"], 1)
        self.assertIn("token", depo.gunluk_rapor()["hatalar"][0]["ornek"].lower())


if __name__ == "__main__":
    unittest.main()

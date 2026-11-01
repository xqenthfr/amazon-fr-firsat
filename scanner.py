"""Tarama motoru: kaynaklardan teklifleri al -> analiz et -> tekrarları ele -> bildir -> kaydet.

Arayüzden bağımsızdır; terminal menüsü de ileride bir web paneli de bu sınıfı kullanabilir.
"""
from __future__ import annotations

import logging
import time
from dataclasses import asdict
from datetime import datetime, timedelta, timezone

import config
from data_sources import DealabsKaynagi, KaynakHatasi, KeepaKaynagi, TokenBitti, baslik_anahtari
from price_analyzer import FiyatGecmisi, Teklif, analiz_et, prime_uygula
from storage import Depo, simdi, zaman_oku
from telegram_bot import TelegramBot, mesaj_olustur

gunluk = logging.getLogger("firsat")


def kaynaklari_kur(ayarlar: dict, depo: Depo) -> list:
    kaynaklar = []
    if ayarlar["kaynaklar"].get("dealabs"):
        d = ayarlar["dealabs"]
        kaynaklar.append(DealabsKaynagi(d["akislar"], d.get("sadece_amazon", True),
                                        max_yas_saat=d.get("max_ilan_yasi_saat", 48),
                                        yedek_akislar=d.get("yedek_akislar", []),
                                        yedek_her_tarama=d.get("yedek_her_tarama", 2), depo=depo))
    if ayarlar["kaynaklar"].get("keepa"):
        anahtar = config.gizli("KEEPA_API_KEY")
        if anahtar:
            kaynaklar.append(KeepaKaynagi(anahtar, depo, ayarlar["keepa"]))
        else:
            gunluk.warning("Keepa açık ama KEEPA_API_KEY tanımlı değil; Keepa atlandı")
    return kaynaklar


def bot_kur() -> TelegramBot | None:
    if config.telegram_ayarli():
        return TelegramBot(config.gizli("TELEGRAM_BOT_TOKEN"), config.gizli("TELEGRAM_CHAT_ID"))
    return None


class Tarayici:
    def __init__(self, ayarlar: dict, depo: Depo, kaynaklar: list, bot: TelegramBot | None):
        self.ayarlar = ayarlar
        self.depo = depo
        self.kaynaklar = kaynaklar
        self.bot = bot

    # -- tekrar bildirim kuralı
    def bildirilmeli(self, urun: str, etkin_fiyat: float) -> bool:
        son = self.depo.son_bildirim(urun)
        if son is None:
            return True
        esik = 1 - self.ayarlar["tekrar_bildirim_dusus_yuzde"] / 100
        return etkin_fiyat <= son["fiyat"] * esik

    def esigi_geciyor(self, t: Teklif, a) -> bool:
        """Bu teklif bildirilecek kadar önemli mi? Kural ayarlardan seçilir."""
        if self.ayarlar.get("bildirim_kurali", "puan") == "hata_veya_indirim":
            if "erreur_de_prix" in t.sinyaller or "baslik_hata" in t.sinyaller:
                a.nedenler.insert(0, "Fiyat hatası şüphesi (her biri bildirilir)")
                return True
            min_indirim = float(self.ayarlar.get("min_indirim_yuzde", 50))
            if a.indirim_yuzde is not None and a.indirim_yuzde >= min_indirim and a.guven != "yok":
                a.nedenler.insert(0, f"İndirim %{a.indirim_yuzde:.0f} (eşik %{min_indirim:.0f})")
                return True
            return False
        min_puan = int(self.ayarlar["min_puan"])
        takipte = any(k in t.baslik.lower() for k in self.ayarlar.get("takip_kelimeleri", []))
        esik = min(min_puan, int(self.ayarlar.get("takip_min_puan", min_puan))) if takipte else min_puan
        if a.puan < esik:
            return False
        if takipte and a.puan < min_puan:
            a.nedenler.append("Takip listenizdeki bir ürün")
        return True

    @staticmethod
    def tekil_anahtar(t: Teklif) -> str:
        """Aynı ürünü farklı ilanlarda/kaynaklarda tanımak için: ASIN varsa ASIN, yoksa başlık."""
        return f"asin:{t.asin}" if t.asin else baslik_anahtari(t.baslik)

    def _yerel_gecmis(self, t: Teklif) -> None:
        """Kaynak geçmiş vermiyorsa kendi biriktirdiğimiz gözlemleri kullan."""
        if t.gecmis is not None:
            return
        anahtar = self.tekil_anahtar(t)
        noktalar = [(z, f) for z, f in self.depo.gozlemler(anahtar) if z < t.kontrol_zamani - timedelta(minutes=1)]
        if len(noktalar) >= 2:
            t.gecmis = FiyatGecmisi.noktalardan(noktalar, durum=t.durum)
            t.notlar.append("Geçmiş, bu programın kendi kayıtlarından (az veri, fırsat anlarına ağırlıklı)")

    def _gozlem_kaydet(self, t: Teklif) -> None:
        if t.fiyat is None:
            return
        self.depo.gozlem_ekle(self.tekil_anahtar(t), t.kaynak, t.etkin_fiyat(), t.durum, t.kontrol_zamani)

    def bekleyenleri_gonder(self) -> int:
        if not self.bot:
            return 0
        gonderilen = 0
        for b in self.depo.bekleyen_bildirimler():
            try:
                self.bot.gonder(b["mesaj"])
                self.depo.bildirim_gonderildi(b["id"])
                gonderilen += 1
            except KaynakHatasi as e:
                self.depo.bildirim_basarisiz(b["id"])
                self.depo.hata_ekle("telegram", str(e))
                gunluk.warning("Telegram gönderilemedi, sonra tekrar denenecek: %s", e)
                break  # bağlantı yoksa diğerlerini de zorlamayalım
        return gonderilen

    def gunluk_rapor_gerekirse(self) -> None:
        if not (self.bot and self.ayarlar.get("gunluk_rapor_telegram")):
            return
        bugun = simdi().date().isoformat()
        son = self.depo.durum_al("son_rapor_gunu")
        if son == bugun:
            return
        if son is None:  # ilk çalışma: rapor yok, sadece işaretle
            self.depo.durum_yaz("son_rapor_gunu", bugun)
            return
        r = self.depo.gunluk_rapor(simdi() - timedelta(days=1))
        hata_metni = ", ".join(f"{h['kaynak']}: {h['n']}" for h in r["hatalar"]) or "yok"
        metin = (f"📋 <b>Günlük rapor ({r['gun']})</b>\nTarama: {r['tarama']} · İncelenen teklif: "
                 f"{r['incelenen']}\nFırsat (eşik üstü): {r['firsat']} · Bildirim: {r['bildirim']}\n"
                 f"Keepa token: {r['keepa_token']}\nHatalar: {hata_metni}")
        self.depo.bildirim_ekle(f"rapor:{r['gun']}", 0, 0, "Günlük rapor", metin)
        self.depo.durum_yaz("son_rapor_gunu", bugun)

    def tara(self) -> dict:
        tarama_id = self.depo.tarama_basla()
        incelenen = firsat = bildirim = hata = 0
        acik_kategoriler = {k for k, v in self.ayarlar["kategoriler"].items() if v}
        min_puan = int(self.ayarlar["min_puan"])
        bulunanlar = []

        for kaynak in self.kaynaklar:
            try:
                teklifler = kaynak.teklifleri_al()
                for e in getattr(kaynak, "son_hatalar", []) or []:
                    hata += 1
                    self.depo.hata_ekle(kaynak.ad, e)
            except TokenBitti as e:
                hata += 1
                self.depo.hata_ekle(kaynak.ad, f"{e} (yaklaşık {int(e.bekleme_saniye // 60)} dk sonra)")
                gunluk.warning("%s: %s", kaynak.ad, e)
                continue
            except KaynakHatasi as e:
                hata += 1
                self.depo.hata_ekle(kaynak.ad, str(e))
                gunluk.warning("%s kaynağına ulaşılamadı: %s", kaynak.ad, e)
                continue

            for t in teklifler:
                incelenen += 1
                self._yerel_gecmis(t)
                if self.ayarlar.get("prime_uyesi"):
                    prime_uygula(t)
                a = analiz_et(t)
                self._gozlem_kaydet(t)
                if a.kategori_grubu not in acik_kategoriler:
                    continue
                if a.etkin_fiyat is None or not self.esigi_geciyor(t, a):
                    continue
                firsat += 1
                anahtar = self.tekil_anahtar(t)
                ayrinti = {"analiz": asdict(a), "satici": t.satici, "durum": t.durum,
                           "kategori": t.kategori, "ek_bag": t.ek_bag, "kaynak_kimligi": t.urun_anahtari}
                bulunanlar.append((t, a))
                if self.bildirilmeli(anahtar, a.etkin_fiyat):
                    self.depo.firsat_ekle(anahtar, t.kaynak, t.baslik, a.etkin_fiyat, a.puan,
                                          a.etiket, a.guven, t.bag, ayrinti)
                    self.depo.bildirim_ekle(anahtar, a.etkin_fiyat, a.puan, t.baslik,
                                            mesaj_olustur(t, a))
                    bildirim += 1

        self.gunluk_rapor_gerekirse()
        gonderilen = self.bekleyenleri_gonder()
        for k in self.kaynaklar:
            if getattr(k, "bosluk_var", False):
                self.depo.hata_ekle(k.ad, "Uyarı: iki tarama arasında ilan kaçmış olabilir; "
                                          "tüm yedek akışlar okundu (tarama aralığını kısaltmayı düşünün)")
        self.depo.tarama_bitir(tarama_id, incelenen, firsat, bildirim, hata)
        self.depo.durum_yaz("son_tarama", simdi().isoformat())
        return {"incelenen": incelenen, "firsat": firsat, "yeni_bildirim": bildirim,
                "gonderilen": gonderilen, "hata": hata, "bulunanlar": bulunanlar}

    def surekli_calis(self, dur=lambda: False, uyku=time.sleep) -> None:
        """Ctrl+C ile durdurulana kadar belirli aralıklarla tarar. Yeniden başlatılınca,
        son taramadan bu yana aralık dolmadıysa kalan süreyi bekler (kaldığı yerden devam)."""
        while not dur():
            aralik = int(self.ayarlar["tarama_araligi_dakika"]) * 60
            son = self.depo.durum_al("son_tarama")
            if son:
                gecen = (simdi() - zaman_oku(son)).total_seconds()
                if gecen < aralik:
                    bekle = aralik - gecen
                    gunluk.info("Sonraki tarama %d sn sonra", bekle)
                    uyku(bekle)
                    continue
            try:
                s = self.tara()
                gunluk.info("Tarama bitti: %s", {k: v for k, v in s.items() if k != "bulunanlar"})
                print(f"[{datetime.now():%H:%M}] incelenen {s['incelenen']}, fırsat {s['firsat']}, "
                      f"yeni bildirim {s['yeni_bildirim']}, gönderilen {s['gonderilen']}, hata {s['hata']}")
            except Exception as e:  # noqa: BLE001 - döngü asla çökmemeli
                self.depo.hata_ekle("tarayici", f"Beklenmeyen hata: {type(e).__name__}: {e}")
                gunluk.exception("Beklenmeyen hata")
                self.depo.durum_yaz("son_tarama", simdi().isoformat())


def keepa_tahmini(ayar: dict, tarama_araligi_dakika: int) -> dict:
    """Seçili ayarlarla Keepa'nın günde kaç token harcayacağını tahmin eder."""
    tarama_gun = 24 * 60 / max(1, tarama_araligi_dakika)
    tarama_basina = (ayar["tarama_basina_firsat_sayfasi"] * KeepaKaynagi.FIRSAT_MALIYETI
                     + ayar["tarama_basina_urun_sorgusu"] * KeepaKaynagi.URUN_MALIYETI)
    gunluk_ihtiyac = int(tarama_gun * tarama_basina)
    plan_gunluk = ayar["plan_dakikada_token"] * 60 * 24
    return {"tarama_basina": tarama_basina, "gunluk_tarama": round(tarama_gun, 1),
            "gunluk_ihtiyac": gunluk_ihtiyac, "plan_gunluk_kapasite": plan_gunluk,
            "butce": ayar["gunluk_token_butcesi"],
            "gercek_gunluk": min(gunluk_ihtiyac, ayar["gunluk_token_butcesi"] or gunluk_ihtiyac, plan_gunluk)}

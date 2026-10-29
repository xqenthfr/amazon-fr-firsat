"""Amazon.fr fırsat avcısı — giriş noktası ve terminal menüsü.

Kullanım:
  python main.py              -> menü
  python main.py --bir-kez    -> tek tarama (zamanlayıcı / GitHub Actions için)
  python main.py --surekli    -> Ctrl+C'ye kadar düzenli tarama
  python main.py --telegram-test
  python main.py --sohbet-bul -> TELEGRAM_CHAT_ID değerini bulmaya yardım eder
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from logging.handlers import RotatingFileHandler

import config
from data_sources import KaynakHatasi, gizle
from scanner import Tarayici, bot_kur, kaynaklari_kur, keepa_tahmini
from storage import Depo


class GizliFiltre(logging.Filter):
    """Günlüğe API anahtarı veya bot jetonu yazılmasın."""
    def filter(self, kayit: logging.LogRecord) -> bool:
        kayit.msg = gizle(kayit.getMessage(), config.gizli("KEEPA_API_KEY"), config.gizli("TELEGRAM_BOT_TOKEN"))
        kayit.args = ()
        return True


def gunlugu_kur() -> None:
    config.VERI_KLASORU.mkdir(parents=True, exist_ok=True)
    isleyici = RotatingFileHandler(config.GUNLUK_DOSYASI, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    isleyici.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    isleyici.addFilter(GizliFiltre())
    kok = logging.getLogger("firsat")
    kok.setLevel(logging.INFO)
    kok.addHandler(isleyici)


def _sor(metin: str) -> str:
    try:
        return input(metin).strip().lstrip("﻿")
    except EOFError:
        return "0"


def _sayi_sor(metin: str, alt: int, ust: int) -> int | None:
    deger = _sor(metin)
    if deger.isdigit() and alt <= int(deger) <= ust:
        return int(deger)
    print(f"  Geçersiz. {alt}–{ust} arasında bir sayı girin.")
    return None


def tarayici_olustur(ayarlar: dict, depo: Depo) -> Tarayici:
    return Tarayici(ayarlar, depo, kaynaklari_kur(ayarlar, depo), bot_kur())


def ozet_yaz(s: dict) -> None:
    print(f"\n  İncelenen teklif: {s['incelenen']}  ·  Eşik üstü: {s['firsat']}  ·  "
          f"Yeni bildirim: {s['yeni_bildirim']}  ·  Gönderilen: {s['gonderilen']}  ·  Hata: {s['hata']}")
    for t, a in sorted(s["bulunanlar"], key=lambda x: -x[1].puan)[:10]:
        print(f"   {a.puan:3d}  {a.etkin_fiyat:>9.2f} €  {a.etiket[:28]:28s}  {t.baslik[:60]}")
    if not config.telegram_ayarli():
        print("  (Telegram ayarlı değil: bildirimler kuyrukta bekliyor. README'deki adımlara bakın.)")


def menu(ayarlar: dict, depo: Depo) -> None:
    while True:
        k = ayarlar["kaynaklar"]
        print("\n=== Amazon.fr Fırsat Avcısı ===")
        print(f"Kaynaklar: Dealabs {'AÇIK' if k['dealabs'] else 'kapalı'} · Keepa {'AÇIK' if k['keepa'] else 'kapalı'}"
              f"  |  Aralık: {ayarlar['tarama_araligi_dakika']} dk  |  Min puan: {ayarlar['min_puan']}"
              f"  |  Telegram: {'hazır' if config.telegram_ayarli() else 'AYARLANMADI'}")
        print(" 1) Şimdi bir kez tara          2) Sürekli taramayı başlat (Ctrl+C durdurur)")
        print(" 3) Tarama aralığı              4) Minimum fırsat puanı")
        print(" 5) Kategorileri aç/kapat       6) Son bulunan fırsatlar")
        print(" 7) Bildirim geçmişi            8) API kullanımı ve tahmin")
        print(" 9) Günlük rapor ve hatalar    10) Veri kaynaklarını aç/kapat")
        print("11) Telegram test mesajı       12) Telegram sohbet kimliğini bul")
        print(f"13) Prime üyeliği: {'VAR (Amazon/FBA kargosu ücretsiz)' if ayarlar.get('prime_uyesi') else 'yok'}")
        print(f"14) Takip kelimeleri (eşik {ayarlar.get('takip_min_puan')}): "
              f"{', '.join(ayarlar.get('takip_kelimeleri', []))[:60]}")
        print(" 0) Çıkış")
        secim = _sor("Seçiminiz: ")
        if secim == "0":
            return
        elif secim == "1":
            print("Taranıyor...")
            ozet_yaz(tarayici_olustur(ayarlar, depo).tara())
        elif secim == "2":
            print("Sürekli tarama başladı. Durdurmak için Ctrl+C.")
            try:
                tarayici_olustur(ayarlar, depo).surekli_calis()
            except KeyboardInterrupt:
                print("\nDurduruldu.")
        elif secim == "3":
            d = _sayi_sor("Kaç dakikada bir taransın? (5–1440): ", 5, 1440)
            if d:
                ayarlar["tarama_araligi_dakika"] = d
                config.ayarlari_kaydet(ayarlar)
        elif secim == "4":
            d = _sayi_sor("Minimum puan (0–100, önerilen 60): ", 0, 100)
            if d is not None:
                ayarlar["min_puan"] = d
                config.ayarlari_kaydet(ayarlar)
        elif secim == "5":
            anahtarlar = list(config.KATEGORILER)
            for i, a in enumerate(anahtarlar, 1):
                print(f"  {i}) [{'x' if ayarlar['kategoriler'].get(a, True) else ' '}] {config.KATEGORILER[a]['ad']}")
            d = _sayi_sor("Değiştirmek istediğiniz numara: ", 1, len(anahtarlar))
            if d:
                a = anahtarlar[d - 1]
                ayarlar["kategoriler"][a] = not ayarlar["kategoriler"].get(a, True)
                config.ayarlari_kaydet(ayarlar)
        elif secim == "6":
            for r in depo.son_firsatlar(20):
                print(f"  {r['zaman'][:16]}  {r['puan']:3d}  {r['fiyat'] or 0:>9.2f} €  {r['etiket'][:26]:26s} "
                      f"{r['baslik'][:55]}\n      {r['bag']}")
        elif secim == "7":
            for r in depo.bildirim_gecmisi(20):
                print(f"  {r['zaman'][:16]}  {r['durum']:10s}  {r['fiyat']:>9.2f} €  puan {r['puan']:3d}  {r['baslik'][:60]}")
        elif secim == "8":
            t = keepa_tahmini(ayarlar["keepa"], ayarlar["tarama_araligi_dakika"])
            print(f"  Keepa tahmini: tarama başına {t['tarama_basina']} token, günde {t['gunluk_tarama']} tarama"
                  f" → {t['gunluk_ihtiyac']} token/gün ihtiyaç.")
            print(f"  Plan kapasitesi: {t['plan_gunluk_kapasite']} token/gün "
                  f"({ayarlar['keepa']['plan_dakikada_token']}/dk) · Günlük bütçe: {t['butce']}")
            print(f"  Bugün harcanan Keepa token: {depo.bugun_harcanan_token()}")
            for r in depo.api_ozeti():
                print(f"   {r['gun']}  {r['kaynak']}: {r['istek']} istek, {r['token']} token, en az kalan {r['en_az_kalan']}")
            print("  Dealabs ve Telegram ücretsizdir; token harcamaz.")
        elif secim == "9":
            r = depo.gunluk_rapor()
            print(json.dumps(r, ensure_ascii=False, indent=2))
        elif secim == "10":
            print("  1) Dealabs (ücretsiz)   2) Keepa (ÜCRETLİ abonelik gerektirir)")
            d = _sayi_sor("Hangisi: ", 1, 2)
            if d == 1:
                k["dealabs"] = not k["dealabs"]
            elif d == 2:
                if not k["keepa"]:
                    print("  Keepa ücretli bir servistir (en düşük plan yaklaşık 49 €/ay, fiyatı keepa.com/api'de"
                          " doğrulayın).\n  Açmak için .env içinde KEEPA_API_KEY tanımlı olmalı.")
                    if _sor("  Keepa'yı açmak için EVET yazın: ") == "EVET":
                        k["keepa"] = True
                else:
                    k["keepa"] = False
            config.ayarlari_kaydet(ayarlar)
        elif secim == "11":
            telegram_test()
        elif secim == "12":
            sohbet_bul()
        elif secim == "13":
            ayarlar["prime_uyesi"] = not ayarlar.get("prime_uyesi")
            config.ayarlari_kaydet(ayarlar)
        elif secim == "14":
            print("  Şu anki liste: " + ", ".join(ayarlar.get("takip_kelimeleri", [])))
            yeni = _sor("  Yeni liste (virgülle ayırın, boş bırakırsanız değişmez): ")
            if yeni:
                ayarlar["takip_kelimeleri"] = [k.strip().lower() for k in yeni.split(",") if k.strip()]
            d = _sayi_sor(f"  Takip ürünleri için en düşük puan (şu an {ayarlar.get('takip_min_puan')}): ", 0, 100)
            if d is not None:
                ayarlar["takip_min_puan"] = d
            config.ayarlari_kaydet(ayarlar)


def telegram_test() -> None:
    bot = bot_kur()
    if not bot:
        print("TELEGRAM_BOT_TOKEN ve TELEGRAM_CHAT_ID .env dosyasında tanımlı değil.")
        return
    try:
        bot.gonder("✅ Amazon.fr Fırsat Avcısı bağlantı testi. Bu mesajı görüyorsanız bildirimler çalışıyor.")
        print("Test mesajı gönderildi. Telegram'ı kontrol edin.")
    except KaynakHatasi as e:
        print(f"Gönderilemedi: {e}")


def sohbet_bul() -> None:
    from telegram_bot import TelegramBot
    token = config.gizli("TELEGRAM_BOT_TOKEN")
    if not token:
        print("Önce .env dosyasına TELEGRAM_BOT_TOKEN yazın.")
        return
    try:
        sohbetler = TelegramBot(token, "").sohbetleri_bul()
    except (KaynakHatasi, ValueError) as e:
        print(f"Okunamadı: {e}")
        return
    if not sohbetler:
        print("Hiç mesaj bulunamadı. Telegram'da botunuza 'merhaba' yazın ve tekrar deneyin.")
    for s in sohbetler:
        print(f"  TELEGRAM_CHAT_ID={s['id']}   ({s['tur']}: {s['ad']})")


def ana() -> int:
    for akis in (sys.stdout, sys.stderr):
        try:
            akis.reconfigure(encoding="utf-8")
        except (AttributeError, OSError):
            pass
    p = argparse.ArgumentParser(description="Amazon.fr olası fiyat hatası ve fırsat izleyici")
    p.add_argument("--bir-kez", action="store_true", help="tek tarama yap ve çık")
    p.add_argument("--surekli", action="store_true", help="düzenli tarama")
    p.add_argument("--telegram-test", action="store_true")
    p.add_argument("--sohbet-bul", action="store_true")
    arg = p.parse_args()

    config.env_yukle()
    gunlugu_kur()
    ayarlar = config.ayarlari_yukle()
    if not config.AYAR_DOSYASI.exists():
        config.ayarlari_kaydet(ayarlar)
    depo = Depo(config.VERITABANI)
    try:
        if arg.telegram_test:
            telegram_test()
        elif arg.sohbet_bul:
            sohbet_bul()
        elif arg.bir_kez:
            s = tarayici_olustur(ayarlar, depo).tara()
            ozet_yaz(s)
        elif arg.surekli:
            try:
                tarayici_olustur(ayarlar, depo).surekli_calis()
            except KeyboardInterrupt:
                print("\nDurduruldu.")
        else:
            menu(ayarlar, depo)
    finally:
        depo.kapat()
    return 0


if __name__ == "__main__":
    sys.exit(ana())

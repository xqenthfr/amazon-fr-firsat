"""Ayarlar.

İki tür ayar var:
1. Gizli bilgiler (.env dosyası veya ortam değişkenleri): Telegram jetonu, Keepa anahtarı.
   Bunlar asla koda veya ayarlar.json'a yazılmaz.
2. Kullanıcı ayarları (veri/ayarlar.json): tarama aralığı, minimum puan, kategoriler...
   Terminal menüsünden değiştirilebilir.
"""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path

PROJE_KLASORU = Path(__file__).resolve().parent
VERI_KLASORU = Path(os.environ.get("FIRSAT_VERI_KLASORU", PROJE_KLASORU / "veri"))
AYAR_DOSYASI = VERI_KLASORU / "ayarlar.json"
VERITABANI = VERI_KLASORU / "firsatlar.db"
GUNLUK_DOSYASI = VERI_KLASORU / "firsat.log"

KEEPA_FR_DOMAIN = 4  # Keepa'da amazon.fr'nin kimliği

# Kategori grupları. Eşleştirme hem Amazon/Dealabs kategori adına hem ürün başlığına
# bakar (Fransızca anahtar kelimeler, küçük harf). İlk eşleşen grup kullanılır.
KATEGORILER: dict[str, dict] = {
    "ekran_karti": {
        "ad": "Ekran kartları",
        "kelimeler": ["carte graphique", "rtx ", "geforce", "radeon", "rx 7", "rx 9", "arc b5"],
    },
    "bilgisayar": {
        "ad": "Bilgisayar ve parçaları",
        "kelimeler": ["informatique", "ordinateur", "pc portable", "pc gamer", "macbook", "ssd",
                      "processeur", "ryzen", "intel core", "écran pc", "moniteur", "carte mère",
                      "mémoire ram", "disque dur", "laptop", "imprimante"],
    },
    "oyun": {
        "ad": "Oyun ve konsollar",
        "kelimeler": ["jeux vidéo", "jeu vidéo", "consoles", "console", "playstation", "ps5",
                      "xbox", "nintendo", "switch 2", "manette", "gaming", "steam deck"],
    },
    "elektronik": {
        "ad": "Elektronik (TV, ses, telefon, foto)",
        "kelimeler": ["high-tech", "électronique", "téléviseur", "tv ", "oled", "barre de son",
                      "casque", "écouteurs", "enceinte", "smartphone", "iphone", "galaxy",
                      "tablette", "ipad", "appareil photo", "montre connectée", "photo"],
    },
    "ev_aletleri": {
        "ad": "Ev aletleri (Ninja, Dyson vb.)",
        "kelimeler": ["électroménager", "ninja", "dyson", "aspirateur", "friteuse", "air fryer",
                      "airfryer", "robot cuiseur", "thermomix", "cafetière", "machine à café",
                      "expresso", "lave-linge", "lave-vaisselle", "réfrigérateur", "micro-ondes",
                      "blender", "sèche-cheveux", "airwrap", "nettoyeur"],
    },
    "mutfak_ev": {
        "ad": "Mutfak, ev ve bahçe",
        "kelimeler": ["cuisine", "maison", "habitat", "jardin", "bricolage", "outil", "meuble",
                      "luminaire", "literie"],
    },
    "diger": {
        "ad": "Diğer tüm kategoriler",
        "kelimeler": [],
    },
}

# Değerli marka/ürün kelimeleri: puana küçük bir "ilgi" katkısı yapar (fiyat kanıtı değildir).
DEGERLI_KELIMELER = ["dyson", "ninja", "rtx", "macbook", "iphone", "ipad", "ps5", "playstation 5",
                     "xbox series", "switch 2", "oled", "airpods", "galaxy s", "lego", "roborock",
                     "de'longhi", "delonghi", "kitchenaid", "thermomix", "garmin", "sony", "bose"]

VARSAYILAN_AYARLAR: dict = {
    "tarama_araligi_dakika": 5,
    "min_puan": 60,
    # Bu kelimeleri içeren ürünlerde daha düşük puan da bildirilir (ilgi listesi)
    "takip_kelimeleri": ["dyson", "ninja", "rtx", "radeon", "ps5", "playstation 5", "xbox series",
                         "switch 2", "macbook", "iphone", "ipad", "oled", "airpods", "roborock"],
    "takip_min_puan": 40,
    "tekrar_bildirim_dusus_yuzde": 10,
    "gunluk_rapor_telegram": True,
    "prime_uyesi": True,  # Amazon/FBA ürünlerinde kargo 0 sayılır
    "kategoriler": {k: True for k in KATEGORILER},
    "kaynaklar": {
        "dealabs": True,
        "keepa": False,  # Ücretli. Kullanıcı açıkça açmadan çalışmaz.
    },
    "dealabs": {
        "akislar": ["nouveaux", "groupe/erreur-de-prix", "tendance"],
        # Yedek kategori akışları: her turda sırayla birkaçı, 'nouveaux'da boşluk varsa hepsi okunur.
        # (Adresler 30.10.2026'da denendi, hepsi çalışıyordu.)
        "yedek_akislar": ["groupe/informatique", "groupe/cartes-graphiques", "groupe/high-tech",
                          "groupe/jeux-video", "groupe/consoles", "groupe/electromenager",
                          "groupe/dyson", "groupe/aspirateurs", "groupe/friteuses",
                          "groupe/televiseurs", "groupe/smartphones", "groupe/apple", "groupe/ssd"],
        "yedek_her_tarama": 2,
        "sadece_amazon": True,
        "max_ilan_yasi_saat": 48,
    },
    "keepa": {
        "plan_dakikada_token": 20,
        "gunluk_token_butcesi": 5000,
        "tarama_basina_firsat_sayfasi": 1,
        "tarama_basina_urun_sorgusu": 10,
        "min_dusus_yuzde": 40,
        "fiyat_turleri": [0, 1],  # 0 = Amazon'un kendi fiyatı, 1 = yeni (pazar yeri)
        "min_fiyat_eur": 15,
        "max_fiyat_eur": 5000,
    },
}


def _derin_birlestir(taban: dict, ust: dict) -> dict:
    sonuc = copy.deepcopy(taban)
    for anahtar, deger in ust.items():
        if isinstance(deger, dict) and isinstance(sonuc.get(anahtar), dict):
            sonuc[anahtar] = _derin_birlestir(sonuc[anahtar], deger)
        else:
            sonuc[anahtar] = deger
    return sonuc


def ayarlari_yukle(dosya: Path | None = None) -> dict:
    dosya = dosya or AYAR_DOSYASI
    if dosya.exists():
        try:
            kayitli = json.loads(dosya.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            kayitli = {}
        return _derin_birlestir(VARSAYILAN_AYARLAR, kayitli)
    return copy.deepcopy(VARSAYILAN_AYARLAR)


def ayarlari_kaydet(ayarlar: dict, dosya: Path | None = None) -> None:
    dosya = dosya or AYAR_DOSYASI
    dosya.parent.mkdir(parents=True, exist_ok=True)
    gecici = dosya.with_suffix(".tmp")
    gecici.write_text(json.dumps(ayarlar, ensure_ascii=False, indent=2), encoding="utf-8")
    gecici.replace(dosya)  # yarım yazılmış dosya kalmasın


def env_yukle(dosya: Path | None = None) -> None:
    """Basit .env okuyucu (ek paket gerektirmez). Zaten tanımlı ortam değişkenini ezmez."""
    dosya = dosya or (PROJE_KLASORU / ".env")
    if not dosya.exists():
        return
    for satir in dosya.read_text(encoding="utf-8-sig").splitlines():
        satir = satir.strip()
        if not satir or satir.startswith("#") or "=" not in satir:
            continue
        anahtar, deger = satir.split("=", 1)
        anahtar = anahtar.strip()
        deger = deger.strip().strip('"').strip("'")
        if anahtar and anahtar not in os.environ:
            os.environ[anahtar] = deger


def gizli(ad: str) -> str:
    return os.environ.get(ad, "").strip()


def telegram_ayarli() -> bool:
    return bool(gizli("TELEGRAM_BOT_TOKEN") and gizli("TELEGRAM_CHAT_ID"))

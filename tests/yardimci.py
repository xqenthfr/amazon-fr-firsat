"""Testler için sentetik veri üreticileri. Gerçek Amazon verisi DEĞİLDİR."""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from price_analyzer import (DURUM_YENI, SATICI_AMAZON, FiyatGecmisi, Teklif)  # noqa: E402

SIMDI = datetime(2026, 10, 29, 12, 0, tzinfo=timezone.utc)


def gecmis_uret(fiyatlar_gunluk: list[float], durum: str = DURUM_YENI) -> FiyatGecmisi:
    """Listedeki her fiyat bir gün; son eleman dün."""
    n = len(fiyatlar_gunluk)
    noktalar = [(SIMDI - timedelta(days=n - i), f) for i, f in enumerate(fiyatlar_gunluk)]
    return FiyatGecmisi.noktalardan(noktalar, simdi=SIMDI, durum=durum)


def teklif(fiyat: float, gecmis: FiyatGecmisi | None = None, **ek) -> Teklif:
    varsayilan = dict(kaynak="test", urun_anahtari=ek.pop("anahtar", "TEST000001"),
                      baslik="Aspirateur Dyson V15 Detect (TEST)", fiyat=fiyat,
                      bag="https://www.amazon.fr/dp/TEST000001", kontrol_zamani=SIMDI,
                      asin=ek.pop("asin", "TEST000001"), kargo=0.0, durum=DURUM_YENI,
                      satici=SATICI_AMAZON, stokta=True, kategori="Électroménager", gecmis=gecmis)
    varsayilan.update(ek)
    return Teklif(**varsayilan)


class SahteKaynak:
    """Önceden belirlenmiş teklifleri veya hatayı döndüren kaynak."""
    ad = "sahte"

    def __init__(self, teklifler=None, hata: Exception | None = None):
        self.teklifler = teklifler or []
        self.hata = hata
        self.cagri = 0

    def teklifleri_al(self):
        self.cagri += 1
        if self.hata:
            raise self.hata
        return list(self.teklifler)


class SahteBot:
    def __init__(self, hata: Exception | None = None):
        self.gonderilen: list[str] = []
        self.hata = hata

    def gonder(self, metin: str) -> None:
        if self.hata:
            raise self.hata
        self.gonderilen.append(metin)

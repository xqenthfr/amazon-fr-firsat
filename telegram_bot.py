"""Telegram Bot API ile bildirim (ek paket yok, sadece urllib)."""
from __future__ import annotations

import html
import json
import time
import urllib.parse
from datetime import timezone, timedelta

from data_sources import KaynakHatasi, gizle, http_getir
from price_analyzer import DURUM_ADLARI, SATICI_ADLARI, Analiz, Teklif

API = "https://api.telegram.org/bot{token}/{yontem}"
try:  # Windows'ta saat dilimi verisi olmayabilir; o zaman kaba bir yaklaşım kullanılır
    from zoneinfo import ZoneInfo
    PARIS = ZoneInfo("Europe/Paris")
except Exception:  # noqa: BLE001
    PARIS = timezone(timedelta(hours=1))


def _e(metin) -> str:
    return html.escape(str(metin), quote=False)


def _eur(deger) -> str:
    return f"{deger:.2f} €".replace(".", ",") if deger is not None else "bilinmiyor"


def mesaj_olustur(t: Teklif, a: Analiz) -> str:
    g = t.gecmis
    satirlar = [f"<b>{_e(a.etiket)}</b> — puan <b>{a.puan}/100</b> ({_e(a.oncelik)}, güven: {_e(a.guven)})",
                "", f"<b>{_e(t.baslik[:200])}</b>", ""]
    fiyat_satiri = f"💶 Güncel: <b>{_eur(t.fiyat)}</b>"
    if t.kargo:
        fiyat_satiri += f" + kargo {_eur(t.kargo)}"
    elif t.kargo == 0:
        fiyat_satiri += " (kargo ücretsiz)"
    if t.kupon:
        fiyat_satiri += f" − kupon {_eur(t.kupon)}"
    if a.etkin_fiyat is not None and a.etkin_fiyat != t.fiyat:
        fiyat_satiri += f" = {_eur(a.etkin_fiyat)}"
    satirlar.append(fiyat_satiri)
    if g and (g.ort30 or g.ort90 or g.ort180):
        satirlar.append(f"📊 Ortalama: 30g {_eur(g.ort30)} · 90g {_eur(g.ort90)} · 180g {_eur(g.ort180)}")
    if g and g.en_dusuk:
        satirlar.append(f"📉 Aralık: {_eur(g.en_dusuk)} – {_eur(g.en_yuksek)}")
    if a.indirim_yuzde is not None:
        satirlar.append(f"🔻 İndirim: %{a.indirim_yuzde:.0f} ({_e(a.referans_adi)})")
    elif not (g and g.en_dusuk):
        satirlar.append("📊 Fiyat geçmişi: <i>veri yok</i>")
    satirlar.append(f"🏪 Satıcı: {_e(SATICI_ADLARI.get(t.satici, t.satici))} · "
                    f"Durum: {_e(DURUM_ADLARI.get(t.durum, t.durum))} · "
                    f"Stok: {'var' if t.stokta else ('yok' if t.stokta is False else 'bilinmiyor')}")
    satirlar.append(f"🕒 Kontrol: {t.kontrol_zamani.astimezone(PARIS).strftime('%d.%m.%Y %H:%M')} "
                    f"(Paris, kaynak: {_e(t.kaynak)})")
    if a.nedenler:
        satirlar.append("")
        satirlar.append("<b>Neden dikkat çekti:</b> " + _e("; ".join(a.nedenler[:4])))
    if a.uyarilar:
        satirlar.append("⚠️ " + _e("; ".join(a.uyarilar[:4])))
    if a.eksikler:
        satirlar.append("❔ Eksik veri: " + _e(", ".join(a.eksikler)))
    satirlar.append("")
    if "dealabs.com/visit/" in t.bag:
        satirlar.append(f'🔗 <a href="{_e(t.bag)}">Ürünü Amazon.fr\'de aç</a> (Dealabs üzerinden yönlendirir)')
    else:
        satirlar.append(f'🔗 <a href="{_e(t.bag)}">Amazon.fr\'de aç</a>')
    if t.ek_bag:
        satirlar.append(f'💬 <a href="{_e(t.ek_bag)}">Dealabs ilanı</a>')
    satirlar.append("<i>Fiyat hatası kesin değildir; satın almadan önce sayfadaki fiyatı, satıcıyı ve "
                    "varyantı kontrol edin.</i>")
    return "\n".join(satirlar)


class TelegramBot:
    def __init__(self, token: str, sohbet_id: str, getir=http_getir, uyku=time.sleep):
        self.token = token
        self.sohbet_id = sohbet_id
        self.getir = getir
        self.uyku = uyku

    def _url(self, yontem: str, parametreler: dict) -> str:
        return API.format(token=self.token, yontem=yontem) + "?" + urllib.parse.urlencode(parametreler)

    def gonder(self, metin: str) -> None:
        """Başarısızsa KaynakHatasi fırlatır (çağıran bildirimi 'bekliyor' bırakır)."""
        parametreler = {"chat_id": self.sohbet_id, "text": metin[:4000], "parse_mode": "HTML",
                        "disable_web_page_preview": "true"}
        for _ in range(3):
            try:
                kod, govde = self.getir(self._url("sendMessage", parametreler))
            except KaynakHatasi as e:
                raise KaynakHatasi(gizle(str(e), self.token)) from None
            try:
                veri = json.loads(govde.decode("utf-8"))
            except ValueError:
                veri = {}
            if kod == 200 and veri.get("ok"):
                return
            if kod == 429:  # Telegram hız sınırı
                self.uyku(min(60, (veri.get("parameters") or {}).get("retry_after", 5)))
                continue
            raise KaynakHatasi(gizle(f"Telegram HTTP {kod}: {veri.get('description', '')}", self.token))
        raise KaynakHatasi("Telegram hız sınırı aşıldı")

    def sohbetleri_bul(self) -> list[dict]:
        """Bota mesaj atan sohbetleri listeler (TELEGRAM_CHAT_ID'yi bulmak için)."""
        kod, govde = self.getir(self._url("getUpdates", {"limit": 50}))
        veri = json.loads(govde.decode("utf-8") or "{}")
        if not veri.get("ok"):
            raise KaynakHatasi(f"Telegram HTTP {kod}: {veri.get('description', '')}")
        sohbetler = {}
        for g in veri.get("result", []):
            mesaj = g.get("message") or g.get("channel_post") or {}
            s = mesaj.get("chat") or {}
            if s.get("id") is not None:
                sohbetler[s["id"]] = {"id": s["id"], "ad": s.get("first_name") or s.get("title") or "",
                                      "tur": s.get("type")}
        return list(sohbetler.values())

"""SQLite tabanlı kalıcı depolama (Python ile birlikte gelir, ek paket yok).

Program kapanıp açıldığında kaldığı yerden devam edebilmesi için her şey burada tutulur:
gözlenen fiyatlar, bulunan fırsatlar, gönderilen/bekleyen bildirimler, API kullanımı,
hatalar ve tarama durumu.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

SEMA = """
CREATE TABLE IF NOT EXISTS gozlemler (
    id INTEGER PRIMARY KEY,
    urun_anahtari TEXT NOT NULL,
    kaynak TEXT NOT NULL,
    fiyat REAL NOT NULL,
    durum TEXT NOT NULL,
    zaman TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_gozlem_urun ON gozlemler(urun_anahtari, zaman);

CREATE TABLE IF NOT EXISTS firsatlar (
    id INTEGER PRIMARY KEY,
    urun_anahtari TEXT NOT NULL,
    kaynak TEXT NOT NULL,
    baslik TEXT NOT NULL,
    fiyat REAL,
    puan INTEGER NOT NULL,
    etiket TEXT NOT NULL,
    guven TEXT NOT NULL,
    bag TEXT,
    ayrinti TEXT,
    zaman TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS bildirimler (
    id INTEGER PRIMARY KEY,
    urun_anahtari TEXT NOT NULL,
    fiyat REAL NOT NULL,
    puan INTEGER NOT NULL,
    baslik TEXT NOT NULL,
    mesaj TEXT NOT NULL,
    durum TEXT NOT NULL,          -- 'gonderildi' | 'bekliyor'
    deneme INTEGER NOT NULL DEFAULT 0,
    zaman TEXT NOT NULL,
    gonderim_zamani TEXT
);
CREATE INDEX IF NOT EXISTS ix_bildirim_urun ON bildirimler(urun_anahtari);

CREATE TABLE IF NOT EXISTS api_kullanimi (
    id INTEGER PRIMARY KEY,
    kaynak TEXT NOT NULL,
    istek TEXT NOT NULL,
    token_harcanan INTEGER,
    token_kalan INTEGER,
    zaman TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS taramalar (
    id INTEGER PRIMARY KEY,
    baslangic TEXT NOT NULL,
    bitis TEXT,
    incelenen INTEGER DEFAULT 0,
    firsat INTEGER DEFAULT 0,
    bildirim INTEGER DEFAULT 0,
    hata INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS hatalar (
    id INTEGER PRIMARY KEY,
    kaynak TEXT NOT NULL,
    mesaj TEXT NOT NULL,
    zaman TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS durum (
    anahtar TEXT PRIMARY KEY,
    deger TEXT NOT NULL
);
"""


def simdi() -> datetime:
    return datetime.now(timezone.utc)


def _z(zaman: datetime | None = None) -> str:
    return (zaman or simdi()).isoformat(timespec="seconds")


def zaman_oku(metin: str) -> datetime:
    z = datetime.fromisoformat(metin)
    return z if z.tzinfo else z.replace(tzinfo=timezone.utc)


class Depo:
    def __init__(self, yol: Path | str):
        if str(yol) != ":memory:":
            Path(yol).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(yol))
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SEMA)
        self.db.commit()

    def kapat(self) -> None:
        self.db.close()

    # --- durum (kaldığı yerden devam) ---
    def durum_al(self, anahtar: str, varsayilan=None):
        satir = self.db.execute("SELECT deger FROM durum WHERE anahtar=?", (anahtar,)).fetchone()
        return json.loads(satir["deger"]) if satir else varsayilan

    def durum_yaz(self, anahtar: str, deger) -> None:
        self.db.execute("INSERT INTO durum(anahtar, deger) VALUES(?, ?) "
                        "ON CONFLICT(anahtar) DO UPDATE SET deger=excluded.deger",
                        (anahtar, json.dumps(deger)))
        self.db.commit()

    # --- fiyat gözlemleri (kendi küçük fiyat geçmişimiz) ---
    def gozlem_ekle(self, urun: str, kaynak: str, fiyat: float, durum: str,
                    zaman: datetime | None = None) -> None:
        zaman = zaman or simdi()
        son = self.db.execute("SELECT fiyat, zaman FROM gozlemler WHERE urun_anahtari=? "
                              "ORDER BY zaman DESC LIMIT 1", (urun,)).fetchone()
        # Aynı fiyatı 6 saat içinde tekrar yazma (veritabanı şişmesin)
        if son and abs(son["fiyat"] - fiyat) < 0.01 and zaman - zaman_oku(son["zaman"]) < timedelta(hours=6):
            return
        self.db.execute("INSERT INTO gozlemler(urun_anahtari, kaynak, fiyat, durum, zaman) "
                        "VALUES(?,?,?,?,?)", (urun, kaynak, fiyat, durum, _z(zaman)))
        self.db.commit()

    def gozlemler(self, urun: str, gun: int = 180) -> list[tuple[datetime, float]]:
        sinir = _z(simdi() - timedelta(days=gun))
        satirlar = self.db.execute("SELECT zaman, fiyat FROM gozlemler WHERE urun_anahtari=? "
                                   "AND zaman>=? ORDER BY zaman", (urun, sinir)).fetchall()
        return [(zaman_oku(s["zaman"]), s["fiyat"]) for s in satirlar]

    # --- fırsatlar ---
    def firsat_ekle(self, urun: str, kaynak: str, baslik: str, fiyat: float | None, puan: int,
                    etiket: str, guven: str, bag: str, ayrinti: dict) -> None:
        self.db.execute("INSERT INTO firsatlar(urun_anahtari, kaynak, baslik, fiyat, puan, etiket, "
                        "guven, bag, ayrinti, zaman) VALUES(?,?,?,?,?,?,?,?,?,?)",
                        (urun, kaynak, baslik, fiyat, puan, etiket, guven, bag,
                         json.dumps(ayrinti, ensure_ascii=False), _z()))
        self.db.commit()

    def son_firsatlar(self, adet: int = 20) -> list[sqlite3.Row]:
        return self.db.execute("SELECT * FROM firsatlar ORDER BY id DESC LIMIT ?", (adet,)).fetchall()

    # --- bildirimler ---
    def son_bildirim(self, urun: str) -> sqlite3.Row | None:
        return self.db.execute("SELECT * FROM bildirimler WHERE urun_anahtari=? "
                               "ORDER BY id DESC LIMIT 1", (urun,)).fetchone()

    def bildirim_ekle(self, urun: str, fiyat: float, puan: int, baslik: str, mesaj: str) -> int:
        imlec = self.db.execute("INSERT INTO bildirimler(urun_anahtari, fiyat, puan, baslik, mesaj, "
                                "durum, zaman) VALUES(?,?,?,?,?, 'bekliyor', ?)",
                                (urun, fiyat, puan, baslik, mesaj, _z()))
        self.db.commit()
        return imlec.lastrowid

    def bildirim_gonderildi(self, bildirim_id: int) -> None:
        self.db.execute("UPDATE bildirimler SET durum='gonderildi', gonderim_zamani=?, "
                        "deneme=deneme+1 WHERE id=?", (_z(), bildirim_id))
        self.db.commit()

    def bildirim_basarisiz(self, bildirim_id: int) -> None:
        self.db.execute("UPDATE bildirimler SET deneme=deneme+1 WHERE id=?", (bildirim_id,))
        self.db.commit()

    def bekleyen_bildirimler(self, max_deneme: int = 20, en_eski_saat: int = 24) -> list[sqlite3.Row]:
        """24 saatten eski bekleyen bildirimler artık gönderilmez (fırsat muhtemelen bitmiştir)."""
        sinir = _z(simdi() - timedelta(hours=en_eski_saat))
        return self.db.execute("SELECT * FROM bildirimler WHERE durum='bekliyor' AND deneme<? "
                               "AND zaman>=? ORDER BY id", (max_deneme, sinir)).fetchall()

    def bildirim_gecmisi(self, adet: int = 20) -> list[sqlite3.Row]:
        return self.db.execute("SELECT * FROM bildirimler ORDER BY id DESC LIMIT ?", (adet,)).fetchall()

    # --- API kullanımı ---
    def api_kaydet(self, kaynak: str, istek: str, harcanan: int | None, kalan: int | None) -> None:
        self.db.execute("INSERT INTO api_kullanimi(kaynak, istek, token_harcanan, token_kalan, zaman) "
                        "VALUES(?,?,?,?,?)", (kaynak, istek, harcanan, kalan, _z()))
        self.db.commit()

    def bugun_harcanan_token(self, kaynak: str = "keepa") -> int:
        bas = _z(simdi().replace(hour=0, minute=0, second=0, microsecond=0))
        satir = self.db.execute("SELECT COALESCE(SUM(token_harcanan),0) t FROM api_kullanimi "
                                "WHERE kaynak=? AND zaman>=?", (kaynak, bas)).fetchone()
        return int(satir["t"])

    def api_ozeti(self, gun: int = 7) -> list[sqlite3.Row]:
        sinir = _z(simdi() - timedelta(days=gun))
        return self.db.execute("SELECT substr(zaman,1,10) gun, kaynak, COUNT(*) istek, "
                               "COALESCE(SUM(token_harcanan),0) token, MIN(token_kalan) en_az_kalan "
                               "FROM api_kullanimi WHERE zaman>=? GROUP BY gun, kaynak ORDER BY gun DESC",
                               (sinir,)).fetchall()

    # --- taramalar ve hatalar ---
    def tarama_basla(self) -> int:
        imlec = self.db.execute("INSERT INTO taramalar(baslangic) VALUES(?)", (_z(),))
        self.db.commit()
        return imlec.lastrowid

    def tarama_bitir(self, tarama_id: int, incelenen: int, firsat: int, bildirim: int, hata: int) -> None:
        self.db.execute("UPDATE taramalar SET bitis=?, incelenen=?, firsat=?, bildirim=?, hata=? "
                        "WHERE id=?", (_z(), incelenen, firsat, bildirim, hata, tarama_id))
        self.db.commit()

    def hata_ekle(self, kaynak: str, mesaj: str) -> None:
        self.db.execute("INSERT INTO hatalar(kaynak, mesaj, zaman) VALUES(?,?,?)",
                        (kaynak, mesaj[:1000], _z()))
        self.db.commit()

    def gunluk_rapor(self, gun: datetime | None = None) -> dict:
        gun = (gun or simdi()).astimezone(timezone.utc)
        bas = gun.replace(hour=0, minute=0, second=0, microsecond=0)
        bit = bas + timedelta(days=1)
        a, b = _z(bas), _z(bit)
        tek = lambda sql: self.db.execute(sql, (a, b)).fetchone()  # noqa: E731
        t = tek("SELECT COUNT(*) n, COALESCE(SUM(incelenen),0) inc, COALESCE(SUM(firsat),0) f, "
                "COALESCE(SUM(bildirim),0) bil FROM taramalar WHERE baslangic>=? AND baslangic<?")
        h = self.db.execute("SELECT kaynak, COUNT(*) n, MAX(mesaj) ornek FROM hatalar "
                            "WHERE zaman>=? AND zaman<? GROUP BY kaynak", (a, b)).fetchall()
        tok = tek("SELECT COALESCE(SUM(token_harcanan),0) t FROM api_kullanimi "
                  "WHERE kaynak='keepa' AND zaman>=? AND zaman<?")
        return {
            "gun": bas.date().isoformat(),
            "tarama": t["n"], "incelenen": t["inc"], "firsat": t["f"], "bildirim": t["bil"],
            "hatalar": [dict(x) for x in h],
            "keepa_token": tok["t"],
        }

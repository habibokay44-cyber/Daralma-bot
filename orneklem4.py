"""Örneklem 4 (07.11.2026): düzeltilmiş göstergenin (EMA kapısı çalışıyor) geçmişten rastgele 40 etiketi, butonlu grafik.
Amaç: yol haritası 1. adım (çizgi seçimi: `direnç X` cevapları) ve 3. adım (kurulum filtresi: alırdım/almazdım + notlar)
için veriyi hızlı toplamak. Bu örneklem kural TASARLAMAK için kullanılır; bulunan kural ayrı bir kör örneklemle ya da
canlı sinyallerle doğrulanır.
Seçim: BIST'ten rastgele 300 hisse (tohum 74), 2023-01 .. 2026-10 arası etiketler, hisse başına en fazla 1, daha önce
gösterilmemiş, rastgele 40 (tohum 74). Grafik etiketten 10 mum sonrasına kadar gösterilir (alış gününü seçebilmen için;
sonucu değil kurulumu değerlendir).
Çalıştırma: python orneklem4.py --telegram
"""
from __future__ import annotations

import json
import random
import sys

import pandas as pd

import kayit
from fd_core import Params, run
from grafik import gonder_butonlu
from scan import fetch_tv_all, get_tickers, telegram_send

MOD = "Örneklem4"
SONRA = 10


def main():
    rnd = random.Random(74)
    tick = get_tickers()
    syms = sorted(rnd.sample(tick, min(300, len(tick))))
    frames = fetch_tv_all(syms, n_bars=1100, budget=15 * 60)
    rows = kayit.load()
    gos = {kayit.key(r["hisse"], r["etiket_tarihi"]) for r in rows}
    aday = []
    for s, df in frames.items():
        try:
            ev = [e for e in run(df, Params()).events if e["type"] == "setup"
                  and pd.Timestamp("2023-01-01") <= e["date"] <= pd.Timestamp("2026-10-20")
                  and kayit.key(s, f"{e['date']:%Y-%m-%d}") not in gos]
        except Exception as ex:  # noqa: BLE001
            print(f"[uyarı] {s}: {ex}")
            continue
        if ev:
            aday.append((s, df, rnd.choice(ev)))
    rnd.shuffle(aday)
    secim = sorted(aday[:40], key=lambda x: x[2]["date"])
    print(f"{len(aday)} hissede aday, {len(secim)} seçildi")
    if "--telegram" not in sys.argv:
        return
    bug = f"{pd.Timestamp.now(tz='Europe/Istanbul'):%Y-%m-%d}"
    for s, df, e in secim:
        r = {c: "" for c in kayit.COLS}
        r.update(bildirim_tarihi=bug, hisse=s, etiket_tarihi=f"{e['date']:%Y-%m-%d}", mod=f"{MOD} {e['mode']}",
                 kapanis=f"{e['close']:.4g}", direnc=f"{e['line']:.4g}", iptal="iptal" if e.get("cancelled") else "")
        try:
            r.update(kayit.bayraklar(df, e))
        except Exception:  # noqa: BLE001
            pass
        gi = [x for x in run(df, Params()).events if x["type"] == "giris" and x.get("setup_date") == e["date"]]
        if gi:
            r["giris_tarihi"] = f"{gi[0]['date']:%Y-%m-%d}"
        rows.append(r)
    kayit.save(rows)    # grafiklerden önce: butonlar kaydı bulsun
    telegram_send(f"🧪 Örneklem 4: geçmişten rastgele {len(secim)} etiket geliyor (düzeltilmiş gösterge).\n"
                  "Her grafikte: ✅/⏳/❌ + stage. Çizgi yanlışsa 📐 ve grafiğe cevap: direnç 12,40 3\n"
                  "Başka günde alırdıysan cevap olarak tarih yaz (örn. 12.11). Almadıklarına kısa not.\n"
                  f"Grafik etiketten {SONRA} mum sonrasına kadar: sonucu değil, kurulumu ve çizgiyi değerlendir.")
    items = [(s, df.iloc[:min(len(df), e["t"] + SONRA + 1)], e) for s, df, e in secim]
    esle = {}
    for i in range(0, len(items), 30):
        esle.update(gonder_butonlu(items[i:i + 30]))
    ep = kayit.F.parent / "tg_mesaj.json"
    try:
        es = json.loads(ep.read_text())
    except Exception:  # noqa: BLE001
        es = {}
    es.update(esle)
    ep.write_text(json.dumps(dict(list(es.items())[-500:]), indent=0))
    print(f"{len(esle)} grafik gönderildi")


if __name__ == "__main__":
    main()

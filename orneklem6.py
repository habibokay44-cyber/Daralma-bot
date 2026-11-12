"""Örneklem 6 (13.11.2026): VERİ TOPLAMA (hipotez testi değil). Daralma modeli v2 için işaret biriktirmek; hedef toplam
400-500 daralma işareti, en az 150 'almazdım'. Azınlık 'almazdım' olduğu için havuz model v1 puanına göre ikiye bölünür:
24 alt yarı (almazdım adayı ağırlıklı) + 16 üst yarı, hisse başına 1, karışık sıra, hangisinin hangi grupta olduğu gizli.
Havuz: BIST'ten rastgele 300 hisse (tohum 97), 2023-01 .. 2026-09 daralma etiketleri, daha önce gösterilenler hariç.
Grafik ETİKET GÜNÜNDE biter. R (isaret_getiri çıkışı) gizli saklanır.
İşaret: ✅/⏳/❌ = İŞLEM kararı. Daralma var ama almazsan ❌ + not 'var'; daralma yoksa ❌ + not 'yok'.
Çalıştırma: python orneklem6.py --telegram
"""
from __future__ import annotations

import csv
import json
import random
import sys

import numpy as np
import pandas as pd

import kayit
from fd_core import Params, prepare, run
from grafik import gonder_butonlu
from isaret_getiri import sim
from model_daralma import FEATS, ST, fit, ozellik, topla
from scan import fetch_tv_all, get_tickers, telegram_send

MOD = "Örneklem6"


def main():
    T, xu = topla()
    X = T[FEATS].to_numpy(float).copy()
    X[~np.isfinite(X)] = np.nan
    med = np.nanmedian(X, 0)
    Xf = np.where(np.isnan(X), med, X)
    mu, sd = Xf.mean(0), Xf.std(0) + 1e-9
    w = fit(np.clip((Xf - mu) / sd, -3, 3), T.y.to_numpy(int))

    def puan(f):
        x = np.array([f[k] for k in FEATS], float)
        x[~np.isfinite(x)] = np.nan
        x = np.where(np.isnan(x), med, x)
        return float(w[0] + np.clip((x - mu) / sd, -3, 3) @ w[1:])

    rows = kayit.load()
    gos = {kayit.key(r["hisse"], r["etiket_tarihi"]) for r in rows}
    for f in ("orneklem.csv", "orneklem2.csv", "orneklem3.csv"):
        p = ST / f
        if p.exists():
            gos |= {kayit.key(r["hisse"], r["etiket_tarihi"]) for r in csv.DictReader(p.open(encoding="utf-8"))}
    rnd = random.Random(97)
    tick = get_tickers()
    frames = fetch_tv_all(sorted(rnd.sample(tick, min(300, len(tick)))), n_bars=1100, budget=15 * 60)
    havuz = []
    for s, df in frames.items():
        try:
            res = run(df, Params())
            S = prepare(df, Params())
            for e in res.events:
                t = int(e["t"]) if e["type"] == "setup" else -1
                if t < 130 or not (pd.Timestamp("2023-01-01") <= e["date"] <= pd.Timestamp("2026-09-30")):
                    continue
                if kayit.key(s, f"{e['date']:%Y-%m-%d}") in gos:
                    continue
                r = sim(df, t)
                if r is None:
                    continue
                havuz.append((s, df, e, puan(ozellik(df, t, S, xu, float(e["line"]))), r[0]))
        except Exception as ex:  # noqa: BLE001
            print(f"[uyarı] {s}: {ex}")
    q = float(np.quantile([h[3] for h in havuz], 0.50))
    rnd.shuffle(havuz)
    secim, say, var = [], dict(d=0, u=0), set()
    for s, df, e, p_, r in havuz:
        g = "d" if p_ < q else "u"
        if s in var or say[g] >= (24 if g == "d" else 16):
            continue
        var.add(s)
        say[g] += 1
        secim.append((s, df, e, g, p_, r))
    rnd.shuffle(secim)
    print(f"havuz {len(havuz)} etiket, eşik {q:.2f}, seçilen {len(secim)} (alt yarı {say['d']}, üst yarı {say['u']})")
    if "--telegram" not in sys.argv:
        return
    bug = f"{pd.Timestamp.now(tz='Europe/Istanbul'):%Y-%m-%d}"
    for s, df, e, g, p_, r in secim:
        row = {c: "" for c in kayit.COLS}
        row.update(bildirim_tarihi=bug, hisse=s, etiket_tarihi=f"{e['date']:%Y-%m-%d}", mod=f"{MOD} {e['mode']}",
                   kapanis=f"{e['close']:.4g}", direnc=f"{e['line']:.4g}", m1=f"{g}:{p_:.2f}", r20=f"{r:.3f}")
        rows.append(row)
    kayit.save(rows)
    telegram_send(f"🧠 Örneklem 6: {len(secim)} yeni kör grafik (gösterge daralma etiketleri). Grafik ETİKET GÜNÜNDE biter.\n"
                  "✅ / ⏳ / ❌ = işlem alır mıydın + stage. Daralma VAR ama almazsan ❌ ve cevap olarak 'var'; daralma YOKSA ❌ ve 'yok' yaz "
                  "(not yazmazsan da olur). 📐 çizgi yanlışsa.\n"
                  "Amaç: daralma modeli v2 için işaret biriktirmek (test değil). Acele yok, müsait olunca.")
    items = [(s, df.iloc[:e["t"] + 1], e) for s, df, e, g, p_, r in secim]
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

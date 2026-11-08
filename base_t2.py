"""Base T2 kör testi (08.11.2026). Base v0'ı DEĞİŞTİRMEZ; v0 sinyallerine gizli bir 'T2' bayrağı ekler.

Neden: Base v0 kör testinde 'almazdım' dediğin 15 grafiğin 11'inde notun "tek temas / belirgin direnç yok" idi
(kırılım mumunu temas saymıyorsun). v0'ın temas sayımı ardışık mumları ayrı temas sayıyordu.

KURAL T2 (şimdiden sabit, değiştirilmeyecek):
  v0 sinyali (kırılım günü u, direnç = u-10..u-1 en yüksek tepe) + u'dan önceki 20 mumda (u-20..u-1) dirence 0.3 ADR
  yakın tepeler AYRI temaslara bölünür: iki temas mumu arasında en az 3 mum (tepesi dirence yakın olmayan) varsa ayrı
  temas. Kırılım mumu (u) sayılmaz. T2 geçer = en az 2 ayrı temas.

ÖRNEKLEM: daha önce görmediğin hisseler/tarihler (BIST'ten rastgele 150 hisse, tohum 57; kayıttaki grafikler hariç),
  2023 sonrası v0 sinyalleri, hisse başına en fazla 2. 20 T2-geçen + 20 T2-elenen (karşılaştırma güçlü olsun diye),
  karışık sırayla. Grafiklerde hangisinin hangi grupta olduğu yazmaz (kör). Grafik sinyal gününde biter.
ÖNCEDEN YAZILMIŞ KABUL (ikisi birden):
  a) T2-geçenlerde 'alırdım' oranı >= %70
  b) T2-elenenlerde 'alırdım' oranı, geçenlerden en az 20 puan düşük
Bilgi (karar değil): aynı bayrak eski Base v0 kör testindeki 39 işaretli grafikte.
Çalıştırma: python base_t2.py --telegram
"""
from __future__ import annotations

import json
import random
import sys

import numpy as np
import pandas as pd

import kayit
from base_v0 import TOL, WT, sinyaller
from grafik import gonder_butonlu
from scan import fetch_tv_all, get_tickers, telegram_send

MOD = "BaseT2"
ARA, NMIN = 3, 2


def temas(df: pd.DataFrame, u: int, top: float) -> int:
    h = df["High"].to_numpy(float)
    l = df["Low"].to_numpy(float)
    A = (pd.Series(h / l).rolling(20).mean().to_numpy()[u - 1] - 1) * 100
    idx = [i for i in range(u - WT, u) if h[i] >= top * (1 - TOL * A / 100)]
    n, prev = 0, None
    for i in idx:
        if prev is None or i - prev - 1 >= ARA:
            n += 1
        prev = i
    return n


def pct(a, n):
    return f"%{a / n * 100:.0f} (n={n})" if n else "-"


def main():
    rows = kayit.load()
    var = {kayit.key(r["hisse"], r["etiket_tarihi"]) for r in rows}
    eski = [r for r in rows if r.get("mod") == "BaseV0" and r.get("isaret") in ("a", "g", "h")]
    rnd = random.Random(57)
    tick = get_tickers()
    syms = sorted(rnd.sample(tick, min(150, len(tick))))
    frames = fetch_tv_all(sorted(set(syms) | {r["hisse"] for r in eski}), n_bars=1000, budget=15 * 60)
    # bilgi: eski 39
    gi, ge = [], []
    for r in eski:
        df = frames.get(r["hisse"])
        if df is None or pd.Timestamp(r["etiket_tarihi"]) not in df.index:
            continue
        u = int(df.index.get_loc(pd.Timestamp(r["etiket_tarihi"])))
        top = float(df["High"].to_numpy(float)[u - 10:u].max())
        (gi if temas(df, u, top) >= NMIN else ge).append(r["isaret"])
    out = ["🧱 Base T2 kör testi (en az 2 AYRI temas, kırılım mumu sayılmaz)",
           f"Bilgi, eski v0 testi: T2 geçen alırdım {pct(gi.count('a'), len(gi))} · elenen alırdım {pct(ge.count('a'), len(ge))}"]
    # yeni örneklem
    gec, ele = [], []
    for s in syms:
        df = frames.get(s)
        if df is None:
            continue
        for e in sinyaller(df):
            if e["date"] < pd.Timestamp("2023-01-01") or kayit.key(s, f"{e['date']:%Y-%m-%d}") in var:
                continue
            n = temas(df, e["t"], e["line"])
            e = {**e, "mode": MOD}
            (gec if n >= NMIN else ele).append((s, df, e, n))
    secim = []
    for grup in (gec, ele):
        rnd.shuffle(grup)
        say, k = {}, 0
        for s, df, e, n in grup:
            if say.get(s, 0) >= 2 or sum(1 for x in secim if x[0] == s) >= 2:
                continue
            say[s] = say.get(s, 0) + 1
            secim.append((s, df.iloc[:e["t"] + 1], e, n))
            k += 1
            if k == 20:
                break
    rnd.shuffle(secim)
    out.append(f"Havuz: T2 geçen {len(gec)}, elenen {len(ele)} sinyal. Gönderilen {len(secim)} grafik "
               f"(geçen {sum(x[3] >= NMIN for x in secim)}, elenen {sum(x[3] < NMIN for x in secim)}; hangisi olduğu gizli).")
    out.append("Kabul: geçenlerde alırdım >= %70 VE elenenler en az 20 puan düşük. Butonlarla işaretle, notlar yine çok değerli.")
    txt = "\n".join(out)
    print(txt)
    if "--telegram" not in sys.argv:
        return
    telegram_send(txt)
    bug = f"{pd.Timestamp.now(tz='Europe/Istanbul'):%Y-%m-%d}"
    for s, df, e, n in secim:
        r = {c: "" for c in kayit.COLS}
        r.update(bildirim_tarihi=bug, hisse=s, etiket_tarihi=f"{e['date']:%Y-%m-%d}", mod=MOD, kapanis=f"{e['close']:.4g}",
                 direnc=f"{e['line']:.4g}", giris_tarihi=f"{e['date']:%Y-%m-%d}", t2=str(n))
        rows.append(r)
    kayit.save(rows)
    esle = {}
    items = [(s, df, e) for s, df, e, n in secim]
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

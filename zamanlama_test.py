"""Zamanlama testi: etiketten sonra 'olgunlaştı' sinyali, senin alış gününü yakalıyor mu? Hiçbir ayarı değiştirmez.

Veri: rastgele örneklemin (state/orneklem.csv) 40 etiketi için 05.11.2026'da verdiğin cevaplar
  a = o gün alırdım, g = başka günde alırdım (alış günüyle), h = almazdım.
ÖNCEDEN YAZILMIŞ KURALLAR (05.11.2026). Etiket aynen kalır; kural etiketten sonra ikinci bir sinyal üretir.
  'Kutu sağlam': etiketten bugüne tüm kapanışlar stop'un üstünde ve direncin altında
  (Düşen modda direnç her gün çizgi üzerinden hesaplanır).
  Z1: etiketten 3 işlem günü sonra, kutu sağlamsa
  Z2: etiketten 4 işlem günü sonra, kutu sağlamsa
  Z3: etiketten en az 2 gün sonra ilk gün ki: kutu sağlam, kapanış kutunun üst yarısında (stop..direnç),
      o günün mum aralığı son 5 mumun ortalamasından küçük (en fazla 15 gün beklenir)
EK (05.11.2026, sonuca bakmadan): GİRİŞ testi. Göstergenin kendi Giriş etiketi (etiketten sonraki ilk 'giris' olayı,
  en fazla 15 gün) senin alış gününün ±1 iş günü içinde mi? Başarı: 15 'g'den en az 9'u.
  Ayrıca her g için kutunun (stop..direnç) ilk bozulduğu gün ve yönü (yukarı = kapanış direnç üstünde, aşağı = stop altında).
BAŞARI: 15 'g' etiketinden (gecikmesi 12 iş gününden uzun olan 3'ü hariç) en az 9'unda sinyal senin alış gününün
  ±1 iş günü içinde. Bilgi: 'a' etiketlerinde gecikme, 'h' etiketlerinde sinyal çıkma oranı.
EK 2 (06.11.2026, sonuca bakmadan): GİRİŞ YENİLEME. Daralma sürdükçe Giriş bekleme süresi (8 mum) yeniden başlar.
  KABUL (ikisi birden): a) 'g' etiketlerinde alış gününü ±1 yakalayan Giriş sayısı mevcuttan FAZLA
  b) 'h' (almazdım) etiketlerinde Giriş sayısı en fazla 2 artar. Ayrıca kalibrasyonda: etiketler aynı kalmalı,
  geçmiş testte işlem başı R mevcuttan en fazla 0.05, PF en fazla 0.10 düşük olabilir.
Çalıştırma: python zamanlama_test.py --telegram
"""
from __future__ import annotations

import sys
import time

from dataclasses import replace

import numpy as np
import pandas as pd

from fd_core import Params, run
from scan import fetch_tv_all, telegram_send

# (hisse, etiket günü, cevap, alış günü)
ROWS = [
    ("TEHOL", "2026-05-05", "g", "2026-05-11"), ("ARFYE", "2026-05-08", "h", None), ("KRDMA", "2026-04-24", "g", "2026-04-29"),
    ("KRDMD", "2025-12-05", "g", "2025-12-11"), ("CEOEM", "2026-03-23", "h", None), ("CATES", "2026-04-22", "h", None),
    ("TCELL", "2026-08-18", "h", None), ("GMTAS", "2025-11-27", "g", "2026-01-07"), ("DZGYO", "2025-12-04", "g", "2025-12-05"),
    ("OYYAT", "2025-12-02", "h", None), ("TRCAS", "2025-12-04", "h", None), ("MAGEN", "2026-03-18", "g", "2026-03-31"),
    ("ADEL", "2026-08-21", "a", None), ("AKFGY", "2025-12-23", "h", None), ("TCKRC", "2026-02-25", "g", "2026-03-06"),
    ("SURGY", "2026-06-04", "g", "2026-06-05"), ("GLRMK", "2026-02-12", "h", None), ("ATLAS", "2026-01-22", "g", "2026-01-26"),
    ("DENGE", "2026-07-02", "h", None), ("DURDO", "2026-03-19", "h", None), ("AHSGY", "2026-04-27", "h", None),
    ("IEYHO", "2026-01-26", "a", None), ("MOBTL", "2026-05-04", "g", "2026-05-13"), ("KUTPO", "2025-12-31", "g", "2026-02-11"),
    ("SVGYO", "2026-06-03", "g", "2026-06-12"), ("BINBN", "2025-11-25", "a", None), ("MEDTR", "2025-12-09", "h", None),
    ("ASGYO", "2026-01-22", "h", None), ("DUNYH", "2026-04-20", "g", "2026-04-22"), ("TUREX", "2026-04-14", "a", None),
    ("KOCMT", "2025-12-03", "h", None), ("INDES", "2026-04-15", "g", "2026-04-24"), ("BSOKE", "2026-03-30", "g", "2026-04-22"),
    ("EBEBK", "2026-02-04", "h", None), ("ARDYZ", "2026-07-22", "a", None), ("LIDFA", "2026-03-13", "a", None),
    ("KTLEV", "2026-02-04", "g", "2026-02-09"), ("MHRGY", "2026-02-13", "a", None), ("ETILR", "2026-04-14", "g", "2026-04-16"),
    ("BIGEN", "2026-04-08", "g", "2026-04-14"),
]
MAXWAIT = 15


def line_at(h, e, u):
    t, ln = int(e["t"]), float(e["line"])
    if e["mode"] != "Düşen" or int(e.get("sp", 0)) < 2:
        return ln
    xa = t - int(e["sp"]) + 1
    sl = (ln - float(h[xa])) / (t - xa) if t != xa else 0.0
    return ln + sl * (u - t)


def signals(df, e):
    o, h, l, c = (df[k].to_numpy(float) for k in ("Open", "High", "Low", "Close"))
    t, stop = int(e["t"]), float(e["stop"])
    rng = h - l
    out = {"Z1": None, "Z2": None, "Z3": None}
    for u in range(t + 1, min(t + MAXWAIT + 1, len(c))):
        sag = all(stop <= c[k] <= line_at(h, e, k) for k in range(t + 1, u + 1))
        if not sag:
            break
        k = u - t
        if k == 3 and out["Z1"] is None:
            out["Z1"] = u
        if k == 4 and out["Z2"] is None:
            out["Z2"] = u
        R = line_at(h, e, u)
        if out["Z3"] is None and k >= 2 and c[u] >= stop + (R - stop) / 2 and rng[u] < rng[u - 5:u].mean():
            out["Z3"] = u
    return out


def first_break(df, e):
    h, c = df["High"].to_numpy(float), df["Close"].to_numpy(float)
    t, stop = int(e["t"]), float(e["stop"])
    for u in range(t + 1, min(t + MAXWAIT + 1, len(c))):
        if c[u] > line_at(h, e, u):
            return u - t, "↑"
        if c[u] < stop:
            return u - t, "↓"
    return None, ""


def main():
    syms = sorted({r[0] for r in ROWS})
    frames = fetch_tv_all(syms, n_bars=700, budget=10 * 60)
    for _ in range(2):
        miss = [s for s in syms if s not in frames]
        if not miss:
            break
        time.sleep(3)
        frames.update(fetch_tv_all(miss, n_bars=700, budget=3 * 60))
    P = Params()
    P2 = replace(Params(), girisYenile=True)   # 06.11.2026 deneme
    gir2 = dict(g_hit=0, g_n=0, gl=[], a=[], h=0, hn=0)
    res = {z: dict(g_hit=0, g_n=0, a_lag=[], h_fire=0, h_n=0, gl=[]) for z in ("Z1", "Z2", "Z3")}
    lags, eks, uzun = [], [], []
    gir = dict(g_hit=0, g_n=0, gl=[], a=[], h=0, hn=0)
    for sym, ld, ans, bd in ROWS:
        df = frames.get(sym)
        if df is None:
            eks.append(f"{sym}(veri)")
            continue
        L = pd.Timestamp(ld)
        ev = [e for e in run(df, P).events if e["type"] == "setup" and abs((e["date"] - L).days) <= 3]
        if not ev:
            eks.append(f"{sym}(etiket)")
            continue
        e = min(ev, key=lambda x: abs((x["date"] - L).days))
        t = int(e["t"])
        sg = signals(df, e)
        evs = run(df, P).events
        gi = [x for x in evs if x["type"] == "giris" and t < x["t"] <= t + MAXWAIT]
        gu = gi[0]["t"] if gi else None
        gi2 = [x for x in run(df, P2).events if x["type"] == "giris" and t < x["t"] <= t + MAXWAIT]
        gu2 = gi2[0]["t"] if gi2 else None
        bk, yon = first_break(df, e)
        if ans == "g":
            b = int(df.index.searchsorted(pd.Timestamp(bd)))
            lag = b - t
            lags.append((sym, lag))
            if lag > 12:
                uzun.append(f"{sym}({lag}g)")
                continue
        if ans == "g":
            gir["g_n"] += 1
            okg = gu is not None and abs(gu - b) <= 1
            gir["g_hit"] += okg
            gir["gl"].append(f"{sym}{'✓' if okg else '✗'}(giriş {'-' if gu is None else gu - t}/sen {lag}/kutu {'-' if bk is None else str(bk) + yon})")
        elif ans == "a":
            gir["a"].append(None if gu is None else gu - t)
        else:
            gir["hn"] += 1
            gir["h"] += gu is not None
        if ans == "g":
            gir2["g_n"] += 1
            ok2 = gu2 is not None and abs(gu2 - b) <= 1
            gir2["g_hit"] += ok2
            gir2["gl"].append(f"{sym}{'✓' if ok2 else '✗'}({'-' if gu2 is None else gu2 - t}/{lag})")
        elif ans == "a":
            gir2["a"].append(None if gu2 is None else gu2 - t)
        else:
            gir2["hn"] += 1
            gir2["h"] += gu2 is not None
        for z, u in sg.items():
            R = res[z]
            if ans == "g":
                R["g_n"] += 1
                ok = u is not None and abs(u - b) <= 1
                R["g_hit"] += ok
                R["gl"].append(f"{sym}{'✓' if ok else '✗'}({'-' if u is None else u - t}/{lag})")
            elif ans == "a":
                R["a_lag"].append(None if u is None else u - t)
            else:
                R["h_n"] += 1
                R["h_fire"] += u is not None
    out = ["⏱ Zamanlama testi (etiket aynı; 'olgunlaştı' sinyali senin alış gününü ±1 iş günü yakalıyor mu?)",
           "Gecikmeler (iş günü, etiket→senin alışın): " + ", ".join(f"{s} {g}" for s, g in lags)]
    if uzun:
        out.append("Ayrı kurulum sayılıp hariç (12 günden uzun): " + ", ".join(uzun))
    for z, R in res.items():
        ok = R["g_hit"] >= 9
        al = [x for x in R["a_lag"] if x is not None]
        out.append(f"\n• {z}: g yakalanan {R['g_hit']}/{R['g_n']} {'✅' if ok else '❌'} | "
                   f"a etiketlerinde sinyal {len(al)}/{len(R['a_lag'])} (gecikme {al}) | h etiketlerinde sinyal {R['h_fire']}/{R['h_n']}")
        out.append("   " + " ".join(R["gl"]) + "   (sinyal gecikmesi/senin gecikmen)")
    ga = [x for x in gir["a"] if x is not None]
    out.append(f"\n• GİRİŞ etiketi: g yakalanan {gir['g_hit']}/{gir['g_n']} {'✅' if gir['g_hit'] >= 9 else '❌'} | "
               f"a etiketlerinde giriş {len(ga)}/{len(gir['a'])} (gecikme {ga}) | h etiketlerinde giriş {gir['h']}/{gir['hn']}")
    out.append("   " + " ".join(gir["gl"]) + "   (giriş gecikmesi / senin gecikmen / kutunun ilk bozulduğu gün ve yönü)")
    ga2 = [x for x in gir2["a"] if x is not None]
    kab = gir2["g_hit"] > gir["g_hit"] and gir2["h"] - gir["h"] <= 2
    out.append(f"\n• GİRİŞ YENİLEMELİ (06.11 deneme): g yakalanan {gir2['g_hit']}/{gir2['g_n']} (mevcut {gir['g_hit']}) | "
               f"a etiketlerinde giriş {len(ga2)}/{len(gir2['a'])} (gecikme {ga2}) | h etiketlerinde giriş {gir2['h']}/{gir2['hn']} "
               f"(mevcut {gir['h']}) -> {'✅ KABUL' if kab else '❌ red'} (ölçüt: g daha fazla VE h en fazla +2)")
    out.append("   " + " ".join(gir2["gl"]) + "   (giriş gecikmesi / senin gecikmen)")
    if eks:
        out.append("Eşleşmeyen: " + ", ".join(eks))
    out.append("Başarı: en az 9 g yakalanan. Not: aynı örneklem; geçen kural ileri testte doğrulanacak.")
    txt = "\n".join(out)
    print(txt)
    if "--telegram" in sys.argv:
        telegram_send(txt[:3900])


if __name__ == "__main__":
    main()

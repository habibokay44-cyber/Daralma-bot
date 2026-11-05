"""Beş yeni kural adayı, 'işlem alırdım' hedefiyle. Hiçbir ayarı değiştirmez. Veri: rastgele örneklemin 40 etiketi ve
05.11.2026'daki cevapların (a = alırdım, g = başka günde alırdım, h = almazdım) ile alış günlerin (zamanlama_test.ROWS).

ÖNCEDEN YAZILMIŞ KURALLAR (05.11.2026). Kural sağlanırsa etiket 'elenir'. Hedef: h kötü, a+g iyi.
  G1  : kapanış, son 40 mumun en düşük dibi ile en yüksek tepesi arasının ALT yarısında
  W1  : haftalık kapanış (etiket gününe kadar) haftalık EMA10'un altında
  E50 : kapanış günlük EMA50'nin altında
  KUTU: etiket Kutu modunda
  KABUL (üçü birden): a) elenenlerde kötü oranı >= 2 x kalanlar  b) kötülerin >= %30'u  c) iyilerin <= %40'ı elenir
  K1 (zamanlama): etiketten sonraki 15 gün içinde ilk gün ki kapanış çizginin en az 0.3 ADR üstünde, mum aralığının
      üst 1/3'ünde kapanış ve hacim 20 günlük ortalamanın üstünde. BAŞARI: 15 g'den (12 günden uzun gecikmeler hariç)
      en az 11'inde senin alış günün ±1 iş günü içinde VE a etiketlerinde K1 gecikmesi en fazla 2 gün.
      (Karşılaştırma: göstergenin mevcut Giriş etiketi 10/15.)
Not: aynı 40 etiket daha önce kullanıldı; geçen kural gölge olarak kaydedilip ileri testte doğrulanacak.
Çalıştırma: python kural5_test.py --telegram
"""
from __future__ import annotations

import sys
import time

import numpy as np
import pandas as pd

from fd_core import Params, run
from scan import fetch_tv_all, telegram_send
from zamanlama_test import ROWS, line_at

MAXWAIT = 15


def ozellik(df, e):
    o, h, l, c, v = (df[k].to_numpy(float) for k in ("Open", "High", "Low", "Close", "Volume"))
    t = int(e["t"])
    H40, L40 = h[max(0, t - 39):t + 1].max(), l[max(0, t - 39):t + 1].min()
    g1 = (c[t] - L40) / (H40 - L40) < 0.5 if H40 > L40 else False
    d = df.iloc[:t + 1]
    wk = d["Close"].resample("W-FRI").last().dropna()
    w1 = bool(wk.iloc[-1] < wk.ewm(span=10, adjust=False).mean().iloc[-1]) if len(wk) >= 10 else False
    e50 = bool(c[t] < pd.Series(c).ewm(span=50, adjust=False).mean().iloc[t])
    kutu = e["mode"] == "Kutu"
    adr = (pd.Series(h / l).rolling(20).mean().to_numpy() - 1) * 100
    vavg = pd.Series(v).rolling(20).mean().to_numpy()
    k1 = None
    for u in range(t + 1, min(t + MAXWAIT + 1, len(c))):
        R = line_at(h, e, u)
        rng = h[u] - l[u]
        if (c[u] >= R + 0.3 * adr[u] / 100 * c[u] and rng > 0 and (c[u] - l[u]) / rng >= 2 / 3
                and v[u] > vavg[u - 1]):
            k1 = u
            break
    gi = [x for x in run(df, Params()).events if x["type"] == "giris" and t < x["t"] <= t + MAXWAIT]
    return dict(G1=g1, W1=w1, E50=e50, KUTU=kutu, k1=k1, giris=gi[0]["t"] if gi else None, t=t)


def judge(rows, key):
    bad = lambda r: r["ans"] == "h"  # noqa: E731
    el = [r for r in rows if r[key]]
    ka = [r for r in rows if not r[key]]
    nb = sum(1 for r in rows if bad(r))
    ng = len(rows) - nb
    if not el or not ka:
        return f"• {key}: elenen {len(el)}, kalan {len(ka)} -> ölçülemez"
    we, wk = sum(1 for r in el if bad(r)), sum(1 for r in ka if bad(r))
    re_, rk = we / len(el), wk / len(ka)
    a_ = (rk == 0 and re_ > 0) or (rk > 0 and re_ >= 2 * rk)
    b_, c_ = we >= 0.3 * nb, (len(el) - we) <= 0.4 * ng
    return (f"• {key}: elenen {len(el)} ({we} kötü) | kalanda iyi kurulum %{100 * (len(ka) - wk) / len(ka):.0f} "
            f"(önce %{100 * ng / len(rows):.0f}) | a{'✓' if a_ else '✗'} b{'✓' if b_ else '✗'} c{'✓' if c_ else '✗'} "
            f"-> {'✅ KABUL' if a_ and b_ and c_ else '❌ red'} | elenen iyiler: "
            + (", ".join(f"{r['sym']}({r['ans']})" for r in el if not bad(r)) or "-"))


def main():
    syms = sorted({r[0] for r in ROWS})
    frames = fetch_tv_all(syms, n_bars=700, budget=10 * 60)
    for _ in range(2):
        miss = [s for s in syms if s not in frames]
        if not miss:
            break
        time.sleep(3)
        frames.update(fetch_tv_all(miss, n_bars=700, budget=3 * 60))
    rows, eks = [], []
    for sym, ld, ans, bd in ROWS:
        df = frames.get(sym)
        if df is None:
            eks.append(f"{sym}(veri)")
            continue
        L = pd.Timestamp(ld)
        ev = [e for e in run(df, Params()).events if e["type"] == "setup" and abs((e["date"] - L).days) <= 3]
        if not ev:
            eks.append(f"{sym}(etiket)")
            continue
        e = min(ev, key=lambda x: abs((x["date"] - L).days))
        f = ozellik(df, e)
        f.update(sym=sym, ans=ans, buy=int(df.index.searchsorted(pd.Timestamp(bd))) if bd else None)
        rows.append(f)
    out = [f"🧩 Beş kural adayı ({len(rows)} etiket; iyi = alırdım + başka gün, kötü = almazdım)"]
    for k in ("G1", "W1", "E50", "KUTU"):
        out.append(judge(rows, k))
    gs = [r for r in rows if r["ans"] == "g" and r["buy"] is not None and r["buy"] - r["t"] <= 12]
    kh = sum(1 for r in gs if r["k1"] is not None and abs(r["k1"] - r["buy"]) <= 1)
    gh = sum(1 for r in gs if r["giris"] is not None and abs(r["giris"] - r["buy"]) <= 1)
    al = [None if r["k1"] is None else r["k1"] - r["t"] for r in rows if r["ans"] == "a"]
    ok = kh >= 11 and all(x is not None and x <= 2 for x in al)
    out.append(f"\n• K1 kırılım kalitesi: g yakalanan {kh}/{len(gs)} (mevcut Giriş {gh}/{len(gs)}) | "
               f"a etiketlerinde K1 gecikmesi {al} -> {'✅ KABUL' if ok else '❌ red'}")
    out.append("   " + " ".join(f"{r['sym']}(K1 {'-' if r['k1'] is None else r['k1'] - r['t']}/Giriş "
                                 f"{'-' if r['giris'] is None else r['giris'] - r['t']}/sen {r['buy'] - r['t']})" for r in gs))
    if eks:
        out.append("Eşleşmeyen: " + ", ".join(eks))
    out.append("Not: aynı 40 etiket; geçen kural gölge olarak kaydedilip ileri testte doğrulanacak.")
    txt = "\n".join(out)
    print(txt)
    if "--telegram" in sys.argv:
        telegram_send(txt[:3900])


if __name__ == "__main__":
    main()

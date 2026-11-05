"""Kaynak tanısı: aynı hissede Yahoo ve TradingView verisiyle göstergenin verdiği etiketleri yan yana koyar.
Pine (TradingView verisi) ile tarama (önce Yahoo) farklı etiket verdiğinde sebebi veri mi, kod mu, bunu ayırır.
Hiçbir ayarı değiştirmez. Çalıştırma: python kaynak_tani.py DZGYO BAYRK MAKIM --telegram
"""
from __future__ import annotations

import sys

import pandas as pd

from dataclasses import replace

from fd_core import Params, run

# Pine v55'te olmayan / farklı olan Python ayarları (05.11.2026 karşılaştırması)
PINE55 = dict(cancelClearsCooldown=False, shrinkMinD=0.5, dnBelowSlope=0.0)   # kullanıcının Pine'ı (FD v54, 05.11)
from scan import fetch_tv_all, fetch_yahoo, telegram_send

SON = 6


def ozet(df, ad, P=None):
    res = run(df, P or Params())
    n = len(df)
    ev = [e for e in res.events if e["t"] >= n - SON]
    s = [f"  {ad}: son mum {df.index[-1]:%d.%m} | olaylar: "
         + (", ".join(f"{e['date']:%d.%m} {e['type']}{'/' + e['mode'] if e.get('mode') else ''}"
                      + (' (iptal)' if e.get('cancelled') else '') for e in ev) or "yok")]
    for i in range(max(0, n - 3), n):
        s.append(f"    {df.index[i]:%d.%m} engel: {(res.diag.get(i) or '-')[:90]}")
    return s


def main():
    syms = [a.upper() for a in sys.argv[1:] if not a.startswith("--")] or ["DZGYO", "BAYRK", "MAKIM", "OZYSR", "DURDO"]
    tv = fetch_tv_all(syms, n_bars=500, budget=4 * 60, min_bars=30)
    uzun = fetch_tv_all(syms, n_bars=3000, budget=4 * 60, min_bars=30)   # Pine tüm geçmişi kullanır
    out = ["🔬 Kaynak tanısı: Yahoo vs TradingView (Pine TradingView verisini kullanır)"]
    for s in syms:
        out.append(f"\n{s}")
        y, t = fetch_yahoo(s, "2y"), tv.get(s)
        if y is None or t is None:
            out.append(f"  veri eksik: Yahoo {'var' if y is not None else 'YOK'}, TV {'var' if t is not None else 'YOK'}")
        if y is not None and t is not None:
            ort = y.index.intersection(t.index)[-SON:]
            fark = []
            for d in ort:
                f = max(abs(y.loc[d, k] / t.loc[d, k] - 1) * 100 for k in ("Open", "High", "Low", "Close"))
                if f > 0.05:
                    fark.append(f"{d:%d.%m} %{f:.2f}")
            eksik = [f"{d:%d.%m}" for d in t.index[-SON:] if d not in y.index]
            out.append("  mum farkı (OHLC, en büyük): " + (", ".join(fark) or "yok (aynı)")
                       + (f" | Yahoo'da olmayan gün: {', '.join(eksik)}" if eksik else ""))
        for df, ad in ((y, "Yahoo"), (t, "TV   ")):
            if df is not None and len(df) >= 120:
                out += ozet(df, ad)
        if s in uzun:
            out += ozet(uzun[s], f"TV {len(uzun[s])} mum (Pine gibi uzun geçmiş)")[:1]
        if t is not None and len(t) >= 120:
            for k, v in PINE55.items():   # her farkı tek tek: hangisi etiketi değiştiriyor
                out += [x for x in ozet(t, f"TV + {k}={v}", replace(Params(), **{k: v}))[:1]]
            out += ozet(t, "TV + senin Pine (v54) ayarlarının hepsi", replace(Params(), **PINE55))[:1]
    txt = "\n".join(out)
    print(txt)
    if "--telegram" in sys.argv:
        telegram_send(txt[:3900])


if __name__ == "__main__":
    main()

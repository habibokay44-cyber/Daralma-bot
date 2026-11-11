"""RS çizgisi (11.11.2026, kullanıcının kullandığı Jack Corsellis RS Line gibi): hisse kapanışı / XU100 kapanışı.
TANIM (önceden sabit): sinyal günü
  zirve    : RS çizgisi son 60 günün en yüksek değerinin en fazla %2 altında
  yükselen : RS çizgisi kendi EMA50'sinin üstünde VE EMA50 son 5 günde yükselmiş
  GÜÇLÜ    = zirve VEYA yükselen   (kullanıcı: "yeni zirve de yükselen eğim de olumlu, ikisi aynı şey")
"""
from __future__ import annotations

import pandas as pd


def olc(df: pd.DataFrame, xu_close: pd.Series, tarih) -> dict | None:
    x = xu_close.reindex(df.index).ffill()
    r = (df["Close"].astype(float) / x).dropna()
    r = r[r.index <= pd.Timestamp(tarih)]
    if len(r) < 60:
        return None
    e50 = r.ewm(span=50, adjust=False).mean()
    uzak = (r.iloc[-1] / r.iloc[-60:].max() - 1) * 100
    zirve = uzak >= -2.0
    yuk = bool(r.iloc[-1] > e50.iloc[-1] and e50.iloc[-1] > e50.iloc[-6])
    return dict(uzak=float(uzak), zirve=bool(zirve), yukselen=yuk, guclu=bool(zirve or yuk))


def satir(df, xu_close, tarih) -> str:
    o = olc(df, xu_close, tarih)
    if o is None:
        return ""
    d = "zirvede" if o["uzak"] >= -0.5 else f"60 gün zirvesine %{-o['uzak']:.1f} uzak"
    return f"RS (XU100'e göre): {d} · {'yükselen' if o['yukselen'] else 'yükselmiyor'} -> {'💪 GÜÇLÜ' if o['guclu'] else 'zayıf'}"


def kod(df, xu_close, tarih) -> str:
    o = olc(df, xu_close, tarih)
    return "" if o is None else f"{'G' if o['guclu'] else 'Z'}:{o['uzak']:.1f}"

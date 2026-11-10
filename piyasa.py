"""Piyasa genişliği / sağlığı (10.11.2026, kullanıcının baktığı şeyler): endeks değil, hisselerin geneli.
TANIM (önceden sabit, test sonucuna göre ayarlanmaz):
  tavan    : o gün %9.5 ve üstü kapanan hisse sayısı; tavan10 = son 10 günün ortalaması
  oran50   : kapanışı kendi EMA50'sinin üstünde olan hisselerin yüzdesi (kullanıcının karakter değişimi ölçüsü EMA50)
  hacim    : tüm hisselerin toplam TL hacmi / bu toplamın 50 günlük ortalaması
  İYİ = şu üçünden en az ikisi: tavan10 >= son 120 günün tavan10 medyanı · oran50 >= %50 · hacim >= 1.0
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def genislik(frames: dict) -> pd.DataFrame:
    C, V = {}, {}
    for s, df in frames.items():
        if len(df) < 60:
            continue
        C[s] = df["Close"].astype(float)
        V[s] = (df["Close"] * df["Volume"]).astype(float)
    C, V = pd.DataFrame(C).sort_index(), pd.DataFrame(V).sort_index()
    deg = C / C.shift(1) - 1
    e50 = C.ewm(span=50, adjust=False, min_periods=50).mean()
    G = pd.DataFrame(index=C.index)
    G["n"] = C.notna().sum(1)
    G["tavan"] = (deg >= 0.095).sum(1)
    G["tavan10"] = G["tavan"].rolling(10).mean()
    G["tavan_ref"] = G["tavan10"].rolling(120, min_periods=40).median()
    ust = (C > e50) & e50.notna()
    G["oran50"] = 100 * ust.sum(1) / e50.notna().sum(1).replace(0, np.nan)
    tv = V.sum(1, min_count=1)
    G["hacim"] = tv / tv.rolling(50, min_periods=20).mean()
    G["puan"] = (G["tavan10"] >= G["tavan_ref"]).astype(int) + (G["oran50"] >= 50).astype(int) + (G["hacim"] >= 1.0).astype(int)
    G["iyi"] = G["puan"] >= 2
    return G


def satir(G: pd.DataFrame) -> str:
    g = G.dropna(subset=["oran50"]).iloc[-1]
    return (f"🌡 Piyasa: {int(g['tavan'])} tavan (10 gün ort {g['tavan10']:.1f}) · hisselerin %{g['oran50']:.0f}'i EMA50 üstü · "
            f"hacim ortalamanın {g['hacim']:.2f} katı -> {'İYİ' if g['iyi'] else 'ZAYIF'} ({int(g['puan'])}/3)")

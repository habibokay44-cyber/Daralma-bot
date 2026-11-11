"""piyasa.py tanısı: son günlerin genişlik değerleri ve paydalar."""
import pandas as pd
import piyasa
from scan import fetch_tv_all, get_tickers

fr = fetch_tv_all(get_tickers(), n_bars=300, budget=15 * 60, min_bars=60)
G = piyasa.genislik(fr)
pd.set_option("display.width", 200)
print(G.tail(8).round(2).to_string())
C = pd.DataFrame({s: d["Close"] for s, d in fr.items()}).sort_index()
print("son tarihler:", C.index[-5:].tolist())
print("son gün veri olan hisse:", C.iloc[-1].notna().sum(), "/", C.shape[1])
e = C.ewm(span=50, adjust=False, min_periods=50).mean()
print("son gün e50 dolu:", e.iloc[-1].notna().sum(), "C>e50:", (C.iloc[-1] > e.iloc[-1]).sum())
deg = C.iloc[-1] / C.iloc[-2] - 1
print("son gün değişim medyan %", round(deg.median() * 100, 2), "tavan", (deg >= 0.095).sum())

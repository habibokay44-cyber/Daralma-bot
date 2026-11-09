"""Temettü / bölünme düzeltmesi tanısı (09.11.2026): TradingView 'splits' ve 'dividends' serilerini yan yana koyar.
Çalıştırma: python temettu_tani.py ALKLC MCARD
"""
from __future__ import annotations

import sys

import pandas as pd

import scan


def cek(sym, adj):
    from tvDatafeed import TvDatafeed
    scan.TEMETTU_DUZELT = False
    tv = TvDatafeed()
    if adj != "splits":
        asil = TvDatafeed._TvDatafeed__send_message

        def g(self, func, args):
            if func == "resolve_symbol":
                args = list(args)
                args[2] = args[2].replace('"adjustment":"splits"', f'"adjustment":"{adj}"')
            return asil(self, func, args)
        tv._TvDatafeed__send_message = g.__get__(tv)
    return scan._tv_df(tv, sym, 300)


for s in [a for a in sys.argv[1:]]:
    A = {a: cek(s, a) for a in ("splits", "dividends", "none")}
    print(f"\n{s}: " + ", ".join(f"{k} {len(v) if v is not None else 'YOK'}" for k, v in A.items()))
    if any(v is None for v in A.values()):
        continue
    d = pd.DataFrame({k: v["Close"] for k, v in A.items()}).dropna()
    d["div/spl"] = d["dividends"] / d["splits"]
    d["none/spl"] = d["none"] / d["splits"]
    ch = d[(d["div/spl"].diff().abs() > 1e-4) | (d["none/spl"].diff().abs() > 1e-4)]
    print(d.iloc[[0]].round(4).to_string())
    print("oranın değiştiği günler:")
    print(ch.round(4).to_string())
    print(d.tail(2).round(4).to_string())

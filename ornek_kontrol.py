"""Kullanıcının verdiği kırılım günlerinde gösterge (etiket + Giriş) ve Base v0 ne yapmış? Hiçbir ayarı değiştirmez.
Çalıştırma: python ornek_kontrol.py KONTR 2021-12-02 2022-04-19 ...  [--telegram]"""
from __future__ import annotations

import sys

import pandas as pd

from base_v0 import sinyaller
from fd_core import Params, run
from scan import fetch_tv_all, telegram_send


def main():
    a = [x for x in sys.argv[1:] if not x.startswith("--")]
    sym, tarihler = a[0].upper(), [pd.Timestamp(x) for x in a[1:]]
    df = fetch_tv_all([sym], n_bars=5000, budget=180, min_bars=30).get(sym)
    if df is None:
        print("veri yok")
        return
    ev = run(df, Params()).events
    v0 = sinyaller(df)
    out = [f"🔎 {sym} · {len(df)} mum ({df.index[0]:%d.%m.%Y}'den) · kullanıcının kırılım günleri"]
    for d in tarihler:
        yak = lambda x: abs((x - d).days) <= 7  # noqa: E731
        g = [e for e in ev if e["type"] == "giris" and yak(e["date"])]
        s = [e for e in ev if e["type"] == "setup" and -25 <= (e["date"] - d).days <= 3]
        b = [e for e in v0 if yak(e["date"])]
        out.append(f"\n{d:%d.%m.%Y}: Giriş {', '.join(f'{e['date']:%d.%m}' for e in g) or 'yok'} | etiket "
                   + (", ".join(f"{e['date']:%d.%m} {e['mode']} {e['line']:.4g}{' (iptal)' if e.get('cancelled') else ''}" for e in s) or "yok")
                   + f" | Base v0 {', '.join(f'{e['date']:%d.%m} ({e['line']:.4g})' for e in b) or 'yok'}")
    txt = "\n".join(out)
    print(txt)
    if "--telegram" in sys.argv:
        telegram_send(txt[:3900])


if __name__ == "__main__":
    main()

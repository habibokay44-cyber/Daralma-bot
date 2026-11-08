"""Küçük base (Stage 2 içinde 3-6 mumluk devam molası) örnekleri: gösterge ve Base v0 ne yapıyor? Hiçbir ayarı değiştirmez.
Örnekler kullanıcıdan (08.11.2026): BIGEN 22-28.04.2026, BIGEN 31.07-07.08.2026, ANELE 06-09.04.2026, MARTI 03-09.09.2026.
Çalıştırma: python kucuk_base.py --telegram
"""
from __future__ import annotations

import sys

import pandas as pd

from base_v0 import sinyaller
from fd_core import Params, run
from scan import fetch_tv_all, telegram_send

ORN = [("BIGEN", "2026-04-22", "2026-04-28"), ("BIGEN", "2026-07-31", "2026-08-07"),
       ("ANELE", "2026-04-06", "2026-04-09"), ("MARTI", "2026-09-03", "2026-09-09")]


def main():
    fr = fetch_tv_all(sorted({o[0] for o in ORN}), n_bars=800, budget=180, min_bars=30)
    out = ["🔹 Küçük base örnekleri: gösterge ve Base v0"]
    for s, a, b in ORN:
        df = fr.get(s)
        if df is None:
            out.append(f"\n{s}: veri yok")
            continue
        A, B = pd.Timestamp(a), pd.Timestamp(b)
        Z = B + pd.Timedelta(days=12)        # molanın sonrası: kırılım günleri
        ix = df.index[(df.index >= A) & (df.index <= B)]
        h = df["High"].to_numpy(float)
        i0, i1 = df.index.get_loc(ix[0]), df.index.get_loc(ix[-1])
        top = h[i0:i1 + 1].max()
        kir = next((df.index[k] for k in range(i1 + 1, len(df)) if df["Close"].iloc[k] > top), None)
        out.append(f"\n{s} {A:%d.%m}–{B:%d.%m}: {len(ix)} mum, mola tepesi {top:.4g}, ilk kapanış üstü "
                   + (f"{kir:%d.%m}" if kir is not None else "yok"))
        res = run(df, Params())
        ev = [e for e in res.events if A - pd.Timedelta(days=3) <= e["date"] <= Z]
        out.append("  gösterge: " + (", ".join(f"{e['date']:%d.%m} {e['type']}{'/' + e['mode'] if e.get('mode') else ''}"
                                               + (' (iptal)' if e.get('cancelled') else '') for e in ev) or "olay yok"))
        for k in range(i0, min(i1 + 4, len(df))):
            dg = res.diag.get(k)
            if dg:
                out.append(f"    {df.index[k]:%d.%m} engel: {dg[:70]}")
        v0 = [e for e in sinyaller(df) if A <= e["date"] <= Z]
        out.append("  Base v0: " + (", ".join(f"{e['date']:%d.%m} (direnç {e['line']:.4g})" for e in v0) or "sinyal yok"))
    txt = "\n".join(out)
    print(txt)
    if "--telegram" in sys.argv:
        telegram_send(txt[:3900])


if __name__ == "__main__":
    main()

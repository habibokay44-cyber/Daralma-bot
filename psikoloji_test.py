"""Psikolojik yük ölçüleri (10.11.2026): her çıkış yönteminde kayıp serileri ve düşüş süreleri. Karar testi değil, bilgi.
Ölçü: 5 işlemli portföy (senaryo D, mevcut sıra, %1 risk, 1.000.000 TL), iki dönem. Zarar = R < -0.05 (başa baş sayılmaz).
  art arda zarar : kapanış sırasına göre en uzun zarar serisi
  sualtı         : özsermayenin önceki zirvenin altında kaldığı en uzun süre (takvim günü) ve zirveye dönmeden biten dönem
  eksi ay        : aylık özsermaye değişimi eksi olan ayların oranı, en kötü ay
Çalıştırma: python psikoloji_test.py --telegram
"""
from __future__ import annotations

import sys

import numpy as np
import pandas as pd

from base_v0 import sinyaller as base_sinyaller
from fd_core import Params, run
from geriye_portfoy import simule
from scan import fetch_tv_all, get_tickers, telegram_send

KW = dict(mod="acilis", kayma=0.005, minhacim=1e7)
VAR = [("Iz10 (şimdiki)", None), ("+3R'de 1/4", (3.0, 0.25, "iz")), ("+2R'de 1/3", (2.0, 1 / 3, "iz")),
       ("+1R'de 1/2", (1.0, 0.5, "iz")), ("+1R'de 1/2, stop girişe çekilmez", (1.0, 0.5, "sabit"))]
DON = [("2023-24", pd.Timestamp("2023-01-02"), pd.Timestamp("2024-12-31")), ("2025-26", pd.Timestamp("2025-01-01"), pd.Timestamp("2100-01-01"))]


def seri(kap):
    R = [t["R"] for t in sorted(kap, key=lambda t: t["cikis_tarihi"])]
    en = cur = 0
    for r in R:
        cur = cur + 1 if r < -0.05 else 0
        en = max(en, cur)
    return en


def sualti(eg):
    tepe = eg.cummax()
    alt = eg < tepe * 0.999
    en, bas = 0, None
    for d, a in alt.items():
        if a and bas is None:
            bas = d
        if not a and bas is not None:
            en = max(en, (d - bas).days)
            bas = None
    acik = (eg.index[-1] - bas).days if bas is not None else 0
    return max(en, acik), acik


def main():
    frames = fetch_tv_all(get_tickers(), n_bars=1200, budget=25 * 60, min_bars=30)
    sig = []
    for s, df in frames.items():
        try:
            lo = df["Low"].to_numpy(float)
            if len(df) >= 120:
                sig += [dict(sym=s, kaynak="Giriş", tarih=e["date"], i=int(e["t"]), kapanis=e["close"], dip=e["sl"])
                        for e in run(df, Params()).events if e["type"] == "giris"]
            sig += [dict(sym=s, kaynak="Base", tarih=e["date"], i=int(e["t"]), kapanis=e["close"], dip=float(lo[e["t"]]))
                    for e in base_sinyaller(df)]
        except Exception as ex:  # noqa: BLE001
            print(f"[uyarı] {s}: {ex}")
    out = ["🧠 Psikolojik yük ölçüleri (5 işlem, %1 risk, 1.000.000 TL)",
           "yöntem: son değer · art arda en uzun zarar · en uzun sualtı (gün) · eksi ay oranı · en kötü ay"]
    for ad, d0, d1 in DON:
        fr = {k: v[v.index <= d1] for k, v in frames.items()}
        fr = {k: v for k, v in fr.items() if len(v) >= 30}
        sg = [x for x in sig if d0 <= x["tarih"] <= d1 and x["sym"] in fr]
        out.append(f"\n{ad}")
        for vad, k in VAR:
            kap, ac_, eg, _ = simule(fr, sg, d0, 1e6, ("Giriş", "Base"), kismi=k, **KW)
            ay = eg.resample("ME").last().pct_change().dropna()
            su, acik = sualti(eg)
            out.append(f"  {vad}: {eg.iloc[-1]:,.0f} · {seri(kap)} zarar üst üste · {su} gün"
                       f"{' (hâlâ sürüyor)' if acik and acik == su else ''} · eksi ay %{100 * (ay < 0).mean():.0f} · en kötü ay %{100 * ay.min():.0f}")
    txt = "\n".join(out)
    print(txt)
    if "--telegram" in sys.argv:
        telegram_send(txt[:3900])


if __name__ == "__main__":
    main()

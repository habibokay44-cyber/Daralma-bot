"""Düşen çizgi 'ara temas' kuralı testi (10.11.2026, kullanıcının kuralı). Varsayılanı DEĞİŞTİRMEZ.
KURAL C2 (dOnceTemas=2): düşen çizginin geçerli olması için, başlangıç tepesi HARİÇ, daralmadan (son 5 mum) ÖNCE en az 2 ayrı
dar-bant temas kümesi olmalı. Daralma mumları temas sayılabilir ama tek başına yetmez. (Kullanıcı: "tek ara temas saçma olur,
bir sürü yere çekilebilir; en az iki".)
ÖNCEDEN YAZILMIŞ KABUL (üçü birden):
  a) Örnekler: kullanıcının 'düşen çizgi yanlış' dediği 5 etiketten (ALKLC 18.06 / 31.07, OZATD 06.03 / 31.03, KLYPV 10.11) en az
     3'ünde yanlış düşen çizgi kalkar (etiket yatay olur ya da etiket hiç çıkmaz).
  b) Getiri ZARAR GÖRMEZ: Giriş sinyalleri, tek tek işlem, portföy-eşdeğeri R; iki dönemde de (2023-24, 2025-) ort. R >= şimdiki - 0.05.
  c) Kalibrasyonda doğru sayısı düşmez (calibrate.py ayrı çalışır).
Yan bilgi: 5 işlemli portföy benzetimi (TL), iki dönem.
Çalıştırma: python dt_test.py --telegram
"""
from __future__ import annotations

import sys
from dataclasses import replace

import numpy as np
import pandas as pd

from base_v0 import sinyaller as base_sinyaller
from fd_core import Params, run
from geriye_portfoy import simule
from rs_test import tek_Reff
from scan import fetch_tv_all, get_tickers, telegram_send

C2 = dict(dOnceTemas=2)
ORN = [("ALKLC", "2026-06-18"), ("ALKLC", "2026-07-31"), ("OZATD", "2026-03-06"), ("OZATD", "2026-03-31"), ("KLYPV", "2026-11-10")]
D1S, D2S = pd.Timestamp("2023-01-02"), pd.Timestamp("2025-01-01")


def main():
    out = ["📐 Düşen çizgi 'en az 2 ara temas' kuralı (C2) testi"]
    fr = fetch_tv_all(sorted({s for s, _ in ORN}), n_bars=1200, budget=120, min_bars=30)
    duz = 0
    for s, d in ORN:
        df = fr.get(s)
        if df is None:
            out.append(f"  {s} {d}: veri yok")
            continue
        D = pd.Timestamp(d)
        def ev(P):
            e = [x for x in run(df, P).events if x["type"] == "setup" and abs((x["date"] - D).days) <= 3]
            return e[0] if e else None
        e0, e1 = ev(Params()), ev(replace(Params(), **C2))
        f = lambda e: "etiket yok" if e is None else f"{e['date']:%d.%m} {e['mode']} {e['line']:.4g}"  # noqa: E731
        ok = e1 is None or e1["mode"] != "Düşen"
        duz += ok
        out.append(f"  {s} {d}: şimdi {f(e0)} -> C2 {f(e1)} {'✅' if ok else '❌'}")
    a = duz >= 3
    out.append(f"a) yanlış düşen çizgi kalktı: {duz}/5 (en az 3) {'✅' if a else '❌'}")
    frames = fetch_tv_all(get_tickers(), n_bars=1200, budget=25 * 60, min_bars=120)
    S, SIG = {}, {}
    for ad, P in (("ADAY", Params()), ("C2", replace(Params(), **C2))):
        S[ad], SIG[ad] = {}, []
        for s, df in frames.items():
            try:
                hac = (df["Close"] * df["Volume"]).rolling(20).mean().to_numpy()
                lo = df["Low"].to_numpy(float)
                for e in run(df, P).events:
                    if e["type"] != "giris" or e["date"] < D1S:
                        continue
                    i = int(e["t"])
                    SIG[ad].append(dict(sym=s, kaynak="Giriş", tarih=e["date"], i=i, kapanis=e["close"], dip=e["sl"]))
                    if hac[i] >= 1e7:
                        r = tek_Reff(df, i, e["sl"])
                        if r is not None:
                            S[ad][(s, e["date"])] = r
                if ad == "ADAY":
                    SIG.setdefault("BASE", [])
                    SIG["BASE"] += [dict(sym=s, kaynak="Base", tarih=e["date"], i=int(e["t"]), kapanis=e["close"], dip=float(lo[e["t"]]))
                                    for e in base_sinyaller(df) if e["date"] >= D1S]
            except Exception as ex:  # noqa: BLE001
                print(f"[uyarı] {s} {ad}: {ex}")
    don = lambda d, k: np.mean([r for (s, t), r in d.items() if (t < D2S) == (k == 1)])  # noqa: E731
    A, V = S["ADAY"], S["C2"]
    b = all(don(V, k) >= don(A, k) - 0.05 for k in (1, 2))
    at = [r for k, r in A.items() if k not in V]
    ek = [r for k, r in V.items() if k not in A]
    out.append(f"\nGetiri (Giriş, portföy-eşdeğeri R): şimdiki D1 {don(A, 1):+.2f} · D2 {don(A, 2):+.2f} ({len(A)} işlem) | "
               f"C2 D1 {don(V, 1):+.2f} · D2 {don(V, 2):+.2f} ({len(V)} işlem)")
    out.append(f"  C2'nin attığı {len(at)} ort {np.mean(at) if at else float('nan'):+.2f}R · eklediği {len(ek)} ort {np.mean(ek) if ek else float('nan'):+.2f}R")
    out.append(f"b) getiri zarar görmüyor (iki dönemde >= şimdiki - 0.05): {'✅' if b else '❌'}")
    out.append("\nYan bilgi, 5 işlemli portföy (Giriş + Base, senaryo D, 1.000.000 TL):")
    for ad in ("ADAY", "C2"):
        sat = []
        for d0, d1 in ((D1S, D2S - pd.Timedelta(days=1)), (D2S, pd.Timestamp("2100-01-01"))):
            f2 = {k: v[v.index <= d1] for k, v in frames.items()}
            sg = [x for x in SIG[ad] + SIG["BASE"] if d0 <= x["tarih"] <= d1]
            kap, ac_, eg, _ = simule(f2, sg, d0, 1e6, ("Giriş", "Base"), mod="acilis", kayma=0.005, minhacim=1e7)
            sat.append(f"{eg.iloc[-1]:,.0f} (düşüş %{(eg / eg.cummax() - 1).min() * 100:.0f})")
        out.append(f"  {ad}: D1 {sat[0]} | D2 {sat[1]}")
    out.append(f"\na ve b -> {'✅ (c: kalibrasyon ayrıca)' if a and b else '❌ red'}")
    txt = "\n".join(out)
    print(txt)
    if "--telegram" in sys.argv:
        telegram_send(txt[:3900])


if __name__ == "__main__":
    main()

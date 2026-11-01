"""Sağlamlık testi 2: düzeltilmiş kontrol, al-tut kıyası, uzun izler (Iz15/Iz20).

- Kontrol: etiketsiz kırılım mumları, ama risk% botun girişlerinin %5-%95 aralığıyla sınırlı (risk≈0 aykırıları yok).
  Kıyas yalnız o yarıda/tüm veride aynı çıkış kuralıyla yapılır. Medyan R de verilir (aykırılara dayanıklı).
- Al-tut: XU100 ve tüm hisselerin eşit ağırlıklı (günlük dengelenen) getirisi, bot girişlerinin kapsadığı dönemin iki yarısında.
- Sermaye simülasyonu: N=5/10, 1/N pozisyon, maliyet %0.3, Iz süre 60, 2R süre 30.
Çalıştırma: python bot_saglamlik2.py --telegram
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import replace

import numpy as np
import pandas as pd

from bot_saglamlik import BRK, COST, portfolio, xit
from fd_core import Params, run
from gecmis_tara import CAND
from scan import fetch_tv_all, get_tickers, telegram_send

VARS = {"2R": (0, 0, 30, 2.0), "Iz5": (5, 1.0, 60, 0), "Iz8": (8, 1.0, 60, 0), "Iz10": (10, 1.0, 60, 0),
        "Iz15": (15, 1.0, 60, 0), "Iz20": (20, 1.0, 60, 0)}


def fmt(a):
    a = np.asarray(a, float)
    if len(a) == 0:
        return "n0"
    g, ls = a[a > 0].sum(), -a[a < 0].sum()
    pf = g / ls if ls > 0 else float("inf")
    m = len(a) // 2
    return (f"n{len(a)} R{a.mean():+.2f}±{a.std() / np.sqrt(len(a)):.2f} med{np.median(a):+.2f} "
            f"({a[:m].mean():+.2f}/{a[m:].mean():+.2f}) PF{pf:.2f}")


def bh(ret: pd.Series, a, b):
    r = ret[(ret.index >= a) & (ret.index < b)].dropna()
    if r.empty:
        return "-"
    eq = (1 + r).cumprod()
    return f"%{(eq.iloc[-1] - 1) * 100:+.0f} (DD{(1 - eq / eq.cummax()).max() * 100:.0f})"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--telegram", action="store_true")
    args = ap.parse_args()
    frames = fetch_tv_all(get_tickers(), n_bars=1500, budget=30 * 60)
    try:
        xu = fetch_tv_all(["XU100"], n_bars=1500, budget=120).get("XU100")
    except SystemExit:
        xu = None
    bot = {v: [] for v in VARS}     # (date, R, entry, exit, retnet)
    risks = []
    for sym, df in frames.items():
        try:
            o, h, l, c = (df[k].to_numpy(float) for k in ("Open", "High", "Low", "Close"))
            n, idx = len(c), df.index
            res = run(df, replace(Params(), **CAND))
            for e in res.events:
                t = e["t"]
                if e["type"] != "giris" or t < 80 or t > n - 65:
                    continue
                risks.append((c[t] - l[t]) / c[t])
                for v, (tr, arm, hold, tpm) in VARS.items():
                    r = xit(o, h, l, c, t, tr, arm, hold, tpm)
                    if r is not None:
                        bot[v].append((idx[t], r[0], idx[t], idx[r[2]], r[1] - COST))
        except Exception as ex:  # noqa: BLE001
            print(f"[uyarı] {sym}: {ex}", file=sys.stderr)
    lo, hi = np.quantile(risks, [0.05, 0.95])
    ctl = {v: [] for v in VARS}
    for sym, df in frames.items():
        try:
            o, h, l, c = (df[k].to_numpy(float) for k in ("Open", "High", "Low", "Close"))
            n, idx = len(c), df.index
            hh = np.array([h[max(0, t - BRK):t].max() if t >= BRK else np.inf for t in range(n)])
            for t in range(80, n - 65, 2):
                if c[t] > hh[t] and lo <= (c[t] - l[t]) / c[t] <= hi:
                    for v, (tr, arm, hold, tpm) in VARS.items():
                        r = xit(o, h, l, c, t, tr, arm, hold, tpm)
                        if r is not None:
                            ctl[v].append((idx[t], r[0]))
        except Exception as ex:  # noqa: BLE001
            print(f"[uyarı] {sym}: {ex}", file=sys.stderr)
    out = [f"🧪 Sağlamlık 2 (brüt R; med=medyan; parantez ilk/ikinci yarı). Kontrol risk% aralığı {lo * 100:.1f}-{hi * 100:.1f}",
           "1) Bot girişleri:"]
    for v in VARS:
        out.append(f"  {v:5}: {fmt([x[1] for x in sorted(bot[v], key=lambda x: x[0])])}")
    out.append("2) Kontrol (etiketsiz kırılım, aynı risk aralığı):")
    for v in VARS:
        out.append(f"  {v:5}: {fmt([x[1] for x in sorted(ctl[v], key=lambda x: x[0])])}")
    dates = sorted(x[0] for x in bot["Iz5"])
    d0, mid, d1 = dates[0], dates[len(dates) // 2], max(x[3] for x in bot["Iz5"])
    rets = pd.DataFrame({s: df["Close"].astype(float).pct_change() for s, df in frames.items()}).sort_index()
    ew = rets.mean(axis=1)
    out.append(f"3) Al-tut (toplam, maxDD): dönem {d0:%d.%m.%y}-{mid:%d.%m.%y} / {mid:%d.%m.%y}-{d1:%d.%m.%y}")
    if xu is not None:
        xr = xu["Close"].astype(float).pct_change().sort_index()
        out.append(f"  XU100      : H1 {bh(xr, d0, mid)} | H2 {bh(xr, mid, d1)}")
    out.append(f"  Eşit ağırlık: H1 {bh(ew, d0, mid)} | H2 {bh(ew, mid, d1)}")
    out.append("4) Sermaye simülasyonu (maliyet %0.3): toplam%, maxDD, [H1 / H2]")
    for N in (5, 10):
        for v in VARS:
            trs = [(x[2], x[3], x[4]) for x in bot[v]]
            k, tot, dd = portfolio(trs, N)
            _, t1, d1_ = portfolio(trs, N, None, mid)
            _, t2, d2_ = portfolio(trs, N, mid, None)
            out.append(f"  N{N} {v:5}: işlem{k} %{tot:+.0f} DD{dd:.0f} | H1 %{t1:+.0f}(DD{d1_:.0f}) H2 %{t2:+.0f}(DD{d2_:.0f})")
    txt = "\n".join(out)
    print(txt)
    if args.telegram:
        parts, cur = [], ""
        for line in txt.split("\n"):
            if cur and len(cur) + len(line) + 1 > 3500:
                parts.append(cur)
                cur = ""
            cur = (cur + "\n" + line) if cur else line
        parts.append(cur)
        for p in parts:
            telegram_send(p[:3900])


if __name__ == "__main__":
    sys.exit(main())

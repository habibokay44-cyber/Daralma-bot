"""Trend takibi (iz süren stop) için SAĞLAMLIK testi.

1) Iz5'in komşu ayarları (iz mum sayısı 3/5/8/10, başlatma eşiği 0/0.5/1/1.5R, süre 40/60) botun girişlerinde.
   Plato (komşuların da iyi olması) yoksa Iz5 şanstır.
2) Aynı çıkışlar KONTROL kırılımlarında (etiketsiz, her 2. kırılım mumu): çıkış kuralı kırılımın kendisinin mi, botun mu işi?
3) Sermaye simülasyonu: aynı anda en fazla N pozisyon (N=5,10), her pozisyon sermayenin 1/N'i, işlem maliyeti gidiş-dönüş %0.3.
   Karşılaştırma: 2R sabit / Iz5 / Iz5 + genişlik filtresi (genişlik alt dilimde girme). Her yarı ayrı başlatılır.
Iz mantığı: hedef yok; fiyat girişin +arm*R üstünü görünce stop girişe (arm>0 ise) ve sonra son 'iz' mumun dibine çekilir, yalnız yukarı.
Brüt = maliyetsiz; 'net' = maliyetli (R cinsinden %0.3 / risk%).
Çalıştırma: python bot_saglamlik.py --telegram
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import replace

import numpy as np
import pandas as pd

from fd_core import Params, run
from gecmis_tara import CAND
from scan import fetch_tv_all, get_tickers, telegram_send

COST = 0.003
VARS = {                       # ad: (iz, arm, süre, sabit hedef R)
    "2R": (0, 0, 30, 2.0),
    "Iz5": (5, 1.0, 40, 0),
    "Iz3": (3, 1.0, 40, 0),
    "Iz8": (8, 1.0, 40, 0),
    "Iz10": (10, 1.0, 40, 0),
    "Iz5a.5": (5, 0.5, 40, 0),
    "Iz5a1.5": (5, 1.5, 40, 0),
    "Iz5a0": (5, 0.0, 40, 0),
    "Iz5s60": (5, 1.0, 60, 0),
}
CTL = ["2R", "Iz5", "Iz3", "Iz8"]
BRK = 6


def xit(o, h, l, c, t, trail, arm, hold, tpm):
    e, sl = c[t], l[t]
    R = e - sl
    if R <= 0:
        return None
    s = sl
    tp = e + tpm * R if tpm else 0
    armed = trail > 0 and arm == 0
    for k in range(t + 1, t + 1 + hold):
        x = None
        if o[k] <= s:
            x = o[k]
        elif tp and o[k] >= tp:
            x = o[k]
        elif l[k] <= s:
            x = s
        elif tp and h[k] >= tp:
            x = tp
        if x is not None:
            return (x - e) / R, x / e - 1, k, R / e
        if trail:
            if not armed and h[k] >= e + arm * R:
                armed = True
                if arm > 0:
                    s = max(s, e)
            if armed:
                s = max(s, float(l[max(t + 1, k - trail + 1):k + 1].min()))
    x = c[t + hold]
    return (x - e) / R, x / e - 1, t + hold, R / e


def fmt(a, with_halves=True):
    a = np.asarray(a, float)
    if len(a) == 0:
        return "n0"
    g, ls = a[a > 0].sum(), -a[a < 0].sum()
    pf = g / ls if ls > 0 else float("inf")
    se = a.std() / np.sqrt(len(a))
    m = len(a) // 2
    hv = f" ({a[:m].mean():+.2f}/{a[m:].mean():+.2f})" if with_halves else ""
    return f"n{len(a)} R{a.mean():+.2f}±{se:.2f}{hv} PF{pf:.2f}"


def portfolio(trs, N, start=None, end=None):
    """trs: (entry_date, exit_date, ret_net). Sermayenin 1/N'i pozisyon başına. Döner (işlem sayısı, toplam %, maxDD %)."""
    ev = sorted([t for t in trs if (start is None or t[0] >= start) and (end is None or t[0] < end)], key=lambda x: x[0])
    open_: list = []
    taken = []
    for ed, xd, r in ev:
        open_ = [p for p in open_ if p > ed]
        if len(open_) >= N:
            continue
        open_.append(xd)
        taken.append((xd, r))
    taken.sort(key=lambda x: x[0])
    eq, peak, dd = 1.0, 1.0, 0.0
    for _, r in taken:
        eq *= 1 + r / N
        peak = max(peak, eq)
        dd = max(dd, 1 - eq / peak)
    return len(taken), (eq - 1) * 100, dd * 100


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--telegram", action="store_true")
    args = ap.parse_args()
    frames = fetch_tv_all(get_tickers(), n_bars=1500, budget=30 * 60)
    flags = {}
    for sym, df in frames.items():
        cl = df["Close"].astype(float)
        ma = cl.rolling(50).mean()
        flags[sym] = (cl > ma).where(ma.notna())
    breadth = pd.DataFrame(flags).mean(axis=1, skipna=True).sort_index()
    bot = {v: [] for v in VARS}      # (date, R, netR, entry_date, exit_date, ret, breadth)
    ctl = {v: [] for v in CTL}
    for sym, df in frames.items():
        try:
            o, h, l, c = (df[k].to_numpy(float) for k in ("Open", "High", "Low", "Close"))
            n = len(c)
            idx = df.index
            res = run(df, replace(Params(), **CAND))
            for e in res.events:
                t = e["t"]
                if e["type"] != "giris" or t < 80 or t > n - 65:
                    continue
                b = float(breadth.asof(idx[t]))
                for v, (tr, arm, hold, tpm) in VARS.items():
                    r = xit(o, h, l, c, t, tr, arm, hold, tpm)
                    if r is None:
                        continue
                    bot[v].append((idx[t], r[0], r[0] - COST / r[3], idx[t], idx[r[2]], r[1] - COST, b))
            hh = np.array([h[max(0, t - BRK):t].max() if t >= BRK else np.inf for t in range(n)])
            for t in range(80, n - 65, 2):
                if c[t] > hh[t] and c[t] > l[t]:
                    for v in CTL:
                        tr, arm, hold, tpm = VARS[v]
                        r = xit(o, h, l, c, t, tr, arm, hold, tpm)
                        if r is not None:
                            ctl[v].append((idx[t], r[0]))
        except Exception as ex:  # noqa: BLE001
            print(f"[uyarı] {sym}: {ex}", file=sys.stderr)
    out = ["🧪 Sağlamlık testi (brüt R, parantez ilk/ikinci yarı)", "1) Bot girişleri, komşu ayarlar:"]
    for v in VARS:
        rows = sorted(bot[v], key=lambda x: x[0])
        a = [x[1] for x in rows]
        net = np.mean([x[2] for x in rows]) if rows else float("nan")
        out.append(f"  {v:8}: {fmt(a)} net{net:+.2f}")
    out.append("2) Aynı çıkış kontrol kırılımlarında (her 2. mum):")
    for v in CTL:
        a = [x[1] for x in sorted(ctl[v], key=lambda x: x[0])]
        out.append(f"  {v:8}: {fmt(a)}")
    allb = [x[6] for x in bot["Iz5"] if x[6] == x[6]]
    q1 = float(np.quantile(allb, 1 / 3))
    dates = sorted(x[0] for x in bot["Iz5"])
    mid = dates[len(dates) // 2]
    out.append(f"3) Sermaye simülasyonu (1/N pozisyon, maliyet %{COST * 100:.1f}); genişlik eşiği {q1:.2f}")
    for N in (5, 10):
        for nm, v, filt in (("2R sabit", "2R", False), ("Iz5", "Iz5", False), ("Iz5+genişlik", "Iz5", True)):
            trs = [(x[3], x[4], x[5]) for x in bot[v] if (not filt or x[6] >= q1)]
            k, tot, dd = portfolio(trs, N)
            k1, t1, d1 = portfolio(trs, N, None, mid)
            k2, t2, d2 = portfolio(trs, N, mid, None)
            out.append(f"  N{N} {nm:13}: işlem{k} toplam%{tot:+.0f} maxDD%{dd:.0f} | H1 %{t1:+.0f}(DD{d1:.0f}) H2 %{t2:+.0f}(DD{d2:.0f})")
    txt = "\n".join(out)
    print(txt)
    if args.telegram:
        telegram_send(txt[:3900])


if __name__ == "__main__":
    sys.exit(main())

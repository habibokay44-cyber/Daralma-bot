"""Botun GERÇEK giriş kuralıyla (kırılım mumu kapanışı, stop = o mumun dibi) ölçüm.

Bot grubu : botun 'giris' olayları (etiketli kurulumdan sonra çizgi kırılımı).
Kontrol   : etiketten bağımsız her kırılım mumu (kapanış, önceki 6 mumun tepesinin üstünde), aynı giriş/stop/hedef kuralı.
Risk farkı sonucu bozmasın diye (stop mumun dibi, risk % hedef/stop oranını belirler) sonuçlar risk %'sine göre 3 dilimde de verilir.
Hedef 2R ve 3R sabit, süre 30 mum (botla aynı), stop aynı mumda hedefle birlikte olursa stop. Brüt.
Çalıştırma: python bot_olcum2.py --telegram
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import replace

import numpy as np

from fd_core import Params, run, summarize
from gecmis_tara import CAND
from scan import fetch_tv_all, get_tickers, telegram_send

HOLD = 30
BRK = 6


def sim(o, h, l, c, t, tr):
    e, sl = c[t], l[t]
    risk = e - sl
    if risk <= 0:
        return None
    tp = e + tr * risk
    for k in range(t + 1, min(len(c), t + 1 + HOLD)):
        if o[k] <= sl:
            x = o[k]
        elif o[k] >= tp:
            x = o[k]
        elif l[k] <= sl:
            x = sl
        elif h[k] >= tp:
            x = tp
        elif k - t >= HOLD:
            x = c[k]
        else:
            continue
        return (x - e) / risk
    return (c[min(len(c) - 1, t + HOLD)] - e) / risk


def fmt(rs):
    a = np.asarray(rs, float)
    if len(a) == 0:
        return "n 0"
    g, ls = a[a > 0].sum(), -a[a < 0].sum()
    pf = g / ls if ls > 0 else float("inf")
    se = a.std() / np.sqrt(len(a))
    return f"n {len(a)} | kaz %{(a > 0).mean() * 100:.0f} | R {a.mean():+.2f}±{se:.2f} | PF {pf:.2f}"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--telegram", action="store_true")
    args = ap.parse_args()
    frames = fetch_tv_all(get_tickers(), n_bars=1500, budget=30 * 60)
    bot = {2: [], 3: []}
    botm = {"Düşen": {2: [], 3: []}, "Yatay": {2: [], 3: []}}
    ctl = {2: [], 3: []}
    brisk, crisk = [], []
    own = []
    for sym, df in frames.items():
        try:
            o, h, l, c = (df[k].to_numpy(float) for k in ("Open", "High", "Low", "Close"))
            n = len(c)
            res = run(df, replace(Params(), **CAND))
            own += res.trades
            for e in res.events:
                if e["type"] != "giris" or e["t"] < 80 or e["t"] > n - 32:
                    continue
                t = e["t"]
                rk = (c[t] - l[t]) / c[t] * 100
                r2, r3 = sim(o, h, l, c, t, 2), sim(o, h, l, c, t, 3)
                if r2 is None:
                    continue
                brisk.append(rk)
                bot[2].append((rk, r2))
                bot[3].append((rk, r3))
                botm[e["mode"]][2].append((rk, r2))
                botm[e["mode"]][3].append((rk, r3))
            hh = np.array([h[max(0, t - BRK):t].max() if t >= BRK else np.inf for t in range(n)])
            for t in range(80, n - 32):
                if c[t] > hh[t] and c[t] > l[t]:
                    r2, r3 = sim(o, h, l, c, t, 2), sim(o, h, l, c, t, 3)
                    if r2 is None:
                        continue
                    rk = (c[t] - l[t]) / c[t] * 100
                    ctl[2].append((rk, r2))
                    ctl[3].append((rk, r3))
        except Exception as ex:  # noqa: BLE001
            print(f"[uyarı] {sym}: {ex}", file=sys.stderr)
    q1, q2 = np.quantile(brisk, [1 / 3, 2 / 3]) if brisk else (0, 0)
    sl = lambda xs, lo, hi: [r for rk, r in xs if lo <= rk < hi]
    out = [f"📏 Botun gerçek giriş kuralı (brüt)  risk% dilimleri: <{q1:.1f}, {q1:.1f}-{q2:.1f}, >{q2:.1f}"]
    for tr in (2, 3):
        out.append(f"Hedef {tr}R:")
        out.append(f"  Bot girişi TÜMÜ: {fmt([r for _, r in bot[tr]])}")
        for m in ("Düşen", "Yatay"):
            out.append(f"  Bot {m:6}    : {fmt([r for _, r in botm[m][tr]])}")
        out.append(f"  Kontrol TÜMÜ   : {fmt([r for _, r in ctl[tr]])}")
        for nm, lo, hi in (("düşük", 0, q1), ("orta", q1, q2), ("yüksek", q2, 1e9)):
            out.append(f"  [{nm} risk] bot: {fmt(sl(bot[tr], lo, hi))}")
            out.append(f"  [{nm} risk] ktr: {fmt(sl(ctl[tr], lo, hi))}")
    st = summarize(own)
    out.append(f"Referans (botun kendi SMC hedefli işlemleri): n {st['n']} kaz %{st['winRate']:.0f} R{st['avgR']:+.2f} PF{st['profitFactor']:.2f}")
    txt = "\n".join(out)
    print(txt)
    if args.telegram:
        telegram_send(txt[:3900])


if __name__ == "__main__":
    sys.exit(main())

"""Senin çıkış yöntemin (EMA10'da yarısını sat, EMA21 altında tamamını çık) vs iz süren stop, bot girişlerinde.

Varsayımlar (yanlışsa söyle, değiştiririm):
 - 'EMA10'da sat' = kapanışın EMA10 altına inmesi. 'EMA21 altına inerse' = kapanışın EMA21 altına inmesi.
 - Sinyal kapanışta görülür, ertesi günün AÇILIŞINDA satılır (E...). 'k' ekli varyantlar aynı gün kapanışta satar (iyimser).
 - Giriş mumunun dibi (başlangıç stop) tüm EMA varyantlarında geçerli; kırılırsa gün içi o seviyede çıkılır (gap'te açılışta).
 - EMA sinyali, kapanış o EMA'nın üstüne en az bir kez çıkmadan geçerli sayılmaz (giriş anında fiyat EMA altındaysa anında atılmasın diye).
 - Süre sınırı 120 mum, bütçe gereği sonra kapanışta çıkış. Maliyet gidiş-dönüş %0.3 (tüm pozisyon).
Kıyas: Iz5, Iz10 (süre 120) ve sabit 2R (süre 30). Metrik: ağırlıklı R (yarı yarıya), medyan, yarı-yarıya bölünmüş dönemler, sermaye simülasyonu.
Çalıştırma: python bot_ema.py --telegram
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import replace

import numpy as np
import pandas as pd

from bot_saglamlik import COST, portfolio, xit
from fd_core import Params, run
from gecmis_tara import CAND
from scan import fetch_tv_all, get_tickers, telegram_send

HOLD = 120
# ad: (yarı satış EMA'sı, tam çıkış EMA'sı, işlem anı)
EMA_VARS = {
    "E10/21": (10, 21, "open"),
    "E10/21k": (10, 21, "close"),
    "E21": (0, 21, "open"),
    "E10": (0, 10, "open"),
}
OTHER = {"2R": (0, 0, 30, 2.0), "Iz5": (5, 1.0, HOLD, 0), "Iz10": (10, 1.0, HOLD, 0)}
ORDER = ["E10/21", "E10/21k", "E21", "E10", "Iz5", "Iz10", "2R"]


def xit_ema(o, h, l, c, e10, e21, t, half_ma, full_ma, when):
    e, sl = c[t], l[t]
    R = e - sl
    if R <= 0:
        return None
    n = len(c)
    open_half, open_rest = (0.5, 0.5) if half_ma else (0.0, 1.0)
    legs = []  # (frac, exit_px)
    arm10 = arm21 = False
    ema = {10: e10, 21: e21}

    def fin(k):
        R_ = sum(f * (x - e) / R for f, x in legs)
        r_ = sum(f * (x / e - 1) for f, x in legs)
        return R_, r_, k, R / e

    last = min(t + HOLD, n - 1)
    for k in range(t + 1, last + 1):
        if o[k] <= sl or l[k] <= sl:
            x = o[k] if o[k] <= sl else sl
            if open_half:
                legs.append((open_half, x))
            legs.append((open_rest, x))
            return fin(k)
        for m, arr in ema.items():
            if c[k] > arr[k]:
                if m == 10:
                    arm10 = True
                if m == 21:
                    arm21 = True
        sig_full = full_ma and ((full_ma == 10 and arm10 and c[k] < e10[k]) or (full_ma == 21 and arm21 and c[k] < e21[k]))
        sig_half = open_half and half_ma == 10 and arm10 and c[k] < e10[k]
        px = c[k] if (when == "close" or k + 1 > last) else o[k + 1]
        kk = k if (when == "close" or k + 1 > last) else k + 1
        if sig_full:
            if open_half:
                legs.append((open_half, px))
            legs.append((open_rest, px))
            return fin(kk)
        if sig_half and open_half:
            legs.append((open_half, px))
            open_half = 0.0
    x = c[last]
    if open_half:
        legs.append((open_half, x))
    legs.append((open_rest, x))
    return fin(last)


def fmt(a):
    a = np.asarray(a, float)
    if len(a) == 0:
        return "n0"
    g, ls = a[a > 0].sum(), -a[a < 0].sum()
    pf = g / ls if ls > 0 else float("inf")
    m = len(a) // 2
    return (f"R{a.mean():+.2f}±{a.std() / np.sqrt(len(a)):.2f} med{np.median(a):+.2f} "
            f"({a[:m].mean():+.2f}/{a[m:].mean():+.2f}) PF{pf:.2f} kaz%{(a > 0).mean() * 100:.0f}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--telegram", action="store_true")
    args = ap.parse_args()
    frames = fetch_tv_all(get_tickers(), n_bars=1500, budget=30 * 60)
    bot = {v: [] for v in ORDER}     # (entry_date, R, exit_date, retnet, gün)
    for sym, df in frames.items():
        try:
            o, h, l, c = (df[k].to_numpy(float) for k in ("Open", "High", "Low", "Close"))
            n, idx = len(c), df.index
            cs = df["Close"].astype(float)
            e10 = cs.ewm(span=10, adjust=False).mean().to_numpy()
            e21 = cs.ewm(span=21, adjust=False).mean().to_numpy()
            res = run(df, replace(Params(), **CAND))
            for e in res.events:
                t = e["t"]
                if e["type"] != "giris" or t < 80 or t > n - HOLD - 5:
                    continue
                for v in ORDER:
                    if v in EMA_VARS:
                        hm, fm, when = EMA_VARS[v]
                        r = xit_ema(o, h, l, c, e10, e21, t, hm, fm, when)
                    else:
                        tr, arm, hold, tpm = OTHER[v]
                        r = xit(o, h, l, c, t, tr, arm, hold, tpm)
                    if r is not None:
                        bot[v].append((idx[t], r[0], idx[r[2]], r[1] - COST, r[2] - t))
        except Exception as ex:  # noqa: BLE001
            print(f"[uyarı] {sym}: {ex}", file=sys.stderr)
    out = ["🧪 Senin EMA çıkışın vs iz stop (bot girişleri, brüt R; parantez ilk/ikinci yarı)"]
    for v in ORDER:
        rows = sorted(bot[v], key=lambda x: x[0])
        out.append(f"  {v:8}: n{len(rows)} {fmt([x[1] for x in rows])} gün~{np.mean([x[4] for x in rows]):.0f}")
    dates = sorted(x[0] for x in bot["Iz10"])
    mid = dates[len(dates) // 2]
    out.append("Sermaye simülasyonu (1/N pozisyon, maliyet %0.3): toplam%, maxDD, [H1 / H2]")
    for N in (5, 10):
        for v in ORDER:
            trs = [(x[0], x[2], x[3]) for x in bot[v]]
            k, tot, dd = portfolio(trs, N)
            _, t1, d1 = portfolio(trs, N, None, mid)
            _, t2, d2 = portfolio(trs, N, mid, None)
            out.append(f"  N{N} {v:8}: işlem{k} %{tot:+.0f} DD{dd:.0f} | H1 %{t1:+.0f}(DD{d1:.0f}) H2 %{t2:+.0f}(DD{d2:.0f})")
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

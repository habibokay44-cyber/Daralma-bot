"""EMA çıkışına başabaş stop eklemek ve yarım satışı +3R'ye taşımak (hibrit testler), bot girişlerinde.

Varyantlar (hepsi: başlangıç stop = giriş mumunun dibi; sinyal kapanışta, satış ertesi AÇILIŞTA; süre 120; maliyet %0.3):
  E10/21     : yarı EMA10 altı kapanışta, kalan EMA21 altı kapanışta (senin yöntemin, tabanda)
  E10/21+BE  : aynısı + fiyat girişin +1R üstünü görünce stop girişe çekilir
  E21        : hepsi EMA21 altında
  E21+BE     : + başabaş stop
  H3R/21     : yarı +3R'de sat (limit emir), kalan EMA21 altında
  H3R/21+BE  : + başabaş stop
  Iz10       : iz süren stop (kıyas)
EMA sinyali, kapanış o EMA'nın üstüne en az bir kez çıkmadan geçerli sayılmaz.
Çalıştırma: python bot_ema2.py --telegram
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import replace

import numpy as np

from bot_ema import HOLD, fmt
from bot_saglamlik import COST, portfolio, xit
from fd_core import Params, run
from gecmis_tara import CAND
from scan import fetch_tv_all, get_tickers, telegram_send

# ad: (yarı kuralı None/'ema10'/'r3', tam çıkış EMA'sı, başabaş)
VARS = {
    "E10/21": ("ema10", 21, False),
    "E10/21+BE": ("ema10", 21, True),
    "E21": (None, 21, False),
    "E21+BE": (None, 21, True),
    "H3R/21": ("r3", 21, False),
    "H3R/21+BE": ("r3", 21, True),
}
ORDER = list(VARS) + ["Iz10"]


def xit2(o, h, l, c, e10, e21, t, half, full_ma, be):
    e, sl = c[t], l[t]
    R = e - sl
    if R <= 0:
        return None
    n = len(c)
    last = min(t + HOLD, n - 1)
    hf, rest = (0.5, 0.5) if half else (0.0, 1.0)
    legs = []
    s = sl
    arm10 = arm21 = False
    tp3 = e + 3 * R

    def fin(k):
        return (sum(f * (x - e) / R for f, x in legs), sum(f * (x / e - 1) for f, x in legs), k, R / e)

    def close_all(x, k):
        if hf:
            legs.append((hf, x))
        legs.append((rest, x))
        return fin(k)

    for k in range(t + 1, last + 1):
        if o[k] <= s or l[k] <= s:
            return close_all(o[k] if o[k] <= s else s, k)
        if half == "r3" and hf and h[k] >= tp3:
            legs.append((hf, max(tp3, o[k]) if o[k] >= tp3 else tp3))
            hf = 0.0
        if be and h[k] >= e + R:
            s = max(s, e)
        if c[k] > e10[k]:
            arm10 = True
        if c[k] > e21[k]:
            arm21 = True
        px = o[k + 1] if k + 1 <= last else c[k]
        kk = k + 1 if k + 1 <= last else k
        if arm21 and c[k] < e21[k]:
            return close_all(px, kk)
        if half == "ema10" and hf and arm10 and c[k] < e10[k]:
            legs.append((hf, px))
            hf = 0.0
    return close_all(c[last], last)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--telegram", action="store_true")
    args = ap.parse_args()
    frames = fetch_tv_all(get_tickers(), n_bars=1500, budget=30 * 60)
    bot = {v: [] for v in ORDER}
    for sym, df in frames.items():
        try:
            o, h, l, c = (df[k].to_numpy(float) for k in ("Open", "High", "Low", "Close"))
            n, idx = len(c), df.index
            cs = df["Close"].astype(float)
            e10 = cs.ewm(span=10, adjust=False).mean().to_numpy()
            e21 = cs.ewm(span=21, adjust=False).mean().to_numpy()
            res = run(df, replace(Params(), **CAND))
            for ev in res.events:
                t = ev["t"]
                if ev["type"] != "giris" or t < 80 or t > n - HOLD - 5:
                    continue
                for v in ORDER:
                    if v == "Iz10":
                        r = xit(o, h, l, c, t, 10, 1.0, HOLD, 0)
                    else:
                        hf, fm, be = VARS[v]
                        r = xit2(o, h, l, c, e10, e21, t, hf, fm, be)
                    if r is not None:
                        bot[v].append((idx[t], r[0], idx[r[2]], r[1] - COST, r[2] - t))
        except Exception as ex:  # noqa: BLE001
            print(f"[uyarı] {sym}: {ex}", file=sys.stderr)
    out = ["🧪 EMA hibrit testleri (bot girişleri, brüt R; parantez ilk/ikinci yarı)"]
    for v in ORDER:
        rows = sorted(bot[v], key=lambda x: x[0])
        out.append(f"  {v:10}: n{len(rows)} {fmt([x[1] for x in rows])} gün~{np.mean([x[4] for x in rows]):.0f}")
    dates = sorted(x[0] for x in bot["Iz10"])
    mid = dates[len(dates) // 2]
    out.append("Sermaye simülasyonu (1/N pozisyon, maliyet %0.3): toplam%, maxDD, [H1 / H2]")
    for N in (5, 10):
        for v in ORDER:
            trs = [(x[0], x[2], x[3]) for x in bot[v]]
            k, tot, dd = portfolio(trs, N)
            _, t1, d1 = portfolio(trs, N, None, mid)
            _, t2, d2 = portfolio(trs, N, mid, None)
            out.append(f"  N{N} {v:10}: işlem{k} %{tot:+.0f} DD{dd:.0f} | H1 %{t1:+.0f}(DD{d1:.0f}) H2 %{t2:+.0f}(DD{d2:.0f})")
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

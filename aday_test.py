"""Etiketsiz aday pencerelerde (gecmis_tara.py) dirençten kırılım işlemi para kazandırır mı?

Kurallar (sonuçları görmeden sabitlendi, hepsi nedensel, ileriye bakmaz):
 - Giriş : pencere bitiminden sonraki 10 mum içinde ilk kapanışı pencere tepesinin (direnç) üstünde olan mum, giriş = o kapanış.
           Ondan önce kapanış pencere dibinin altına inerse işlem yok.
 - Stop  : pencere dibi (fitil dahil). Aynı mumda stop ve hedef birlikte olursa stop sayılır.
 - Hedef : 2R (ayrıca 3R). Süre: 20 mum sonra kapanışta çıkış.
 - Kontrol: aynı hisselerde her 10. mumda, filtre uygulamadan, aynı 6 mumluk pencere ve aynı kurallar.
 - Referans: botun kendi işlemleri (fd_core.summarize), kuralları farklı, sadece büyüklük karşılaştırması içindir.
Komisyon/kayma yok (brüt).
"""
from __future__ import annotations

import argparse
import sys
import time
from dataclasses import replace

import numpy as np
import pandas as pd

from fd_core import Params, run, summarize
from gecmis_tara import CAND, LOOK, W, candidates
from scan import fetch_tv_all, get_tickers, telegram_send

HOLD = 20


def trade(c, h, l, i, res_px, lo, target_r):
    """i = pencere son mumu. Döner: R ya da None."""
    n = len(c)
    j = None
    for k in range(i + 1, min(n, i + 1 + LOOK)):
        if c[k] < lo:
            return None
        if c[k] > res_px:
            j = k
            break
    if j is None:
        return None
    entry = c[j]
    risk = entry - lo
    if risk <= 0 or risk / entry > 0.25:
        return None
    tp = entry + target_r * risk
    for k in range(j + 1, min(n, j + 1 + HOLD)):
        if l[k] <= lo:
            return -1.0
        if h[k] >= tp:
            return float(target_r)
    k = min(n - 1, j + HOLD)
    if k <= j:
        return None
    return float((c[k] - entry) / risk)


def stats(rs: list[float]) -> str:
    if not rs:
        return "işlem yok"
    r = np.array(rs)
    gw, gl = r[r > 0].sum(), -r[r <= 0].sum()
    pf = gw / gl if gl > 0 else float("inf")
    return f"n {len(r)} | kazanma %{(r > 0).mean() * 100:.0f} | ort R {r.mean():+.2f} | PF {pf:.2f}"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--telegram", action="store_true")
    args = ap.parse_args()
    frames = fetch_tv_all(get_tickers(), n_bars=1500, budget=30 * 60)
    cand: dict[int, list] = {2: [], 3: []}
    ctrl: list[float] = []
    cand_dates: list[tuple] = []
    bot_tr: list = []
    for sym, df in frames.items():
        try:
            c = df["Close"].to_numpy(float)
            h = df["High"].to_numpy(float)
            l = df["Low"].to_numpy(float)
            for x in candidates(sym, df, skip_labeled=True, span=len(df)):
                for tr in (2, 3):
                    r = trade(c, h, l, x["i"], x["res"], x["lo"], tr)
                    if r is not None:
                        cand[tr].append(r)
                        if tr == 2:
                            cand_dates.append((x["b"], r))
            for i in range(80, len(df) - LOOK - HOLD, 10):
                r = trade(c, h, l, i, h[i - W + 1:i + 1].max(), l[i - W + 1:i + 1].min(), 2)
                if r is not None:
                    ctrl.append(r)
            bot_tr += run(df, replace(Params(), **CAND)).trades
        except Exception as e:  # noqa: BLE001
            print(f"[uyarı] {sym}: {e}", file=sys.stderr)
    cand_dates.sort()
    half = len(cand_dates) // 2
    bs = summarize(bot_tr)
    out = ["📈 Aday pencere işlem testi (brüt, komisyonsuz)",
           f"Aday pencereler, hedef 2R : {stats(cand[2])}",
           f"Aday pencereler, hedef 3R : {stats(cand[3])}",
           f"  eski yarı (2R)          : {stats([r for _, r in cand_dates[:half]])}",
           f"  yeni yarı (2R)          : {stats([r for _, r in cand_dates[half:]])}",
           f"Kontrol (filtresiz, 2R)    : {stats(ctrl)}",
           f"Botun kendi işlemleri      : n {bs['n']} | kazanma %{bs['winRate']:.0f} | ort R {bs['avgR']:+.2f} | PF {bs['profitFactor']:.2f} (kuralları farklı)",
           "Okuma: adaylar kontrolden belirgin iyi ve iki yarıda da pozitifse izleme listesi anlamlı."]
    txt = "\n".join(out)
    print(txt)
    if args.telegram:
        telegram_send(txt[:3900])


if __name__ == "__main__":
    sys.exit(main())

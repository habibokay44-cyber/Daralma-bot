"""Botun kendi etiketleri, aday pencereler ve filtresiz kontrol: AYNI işlem kuralıyla ölçülür.

Kural (aday_test.py ile aynı): etiket/pencere gününden sonraki 10 mum içinde, son 6 mumun tepesinin üstünde ilk kapanışta giriş;
önce son 6 mumun dibinin altında kapanış olursa işlem yok. Stop = son 6 mumun dibi, hedef 2R (ve 3R), süre 20 mum. Brüt.
Etiketler: iptal olmayanlar (bildirilenler), mod bazında ayrı.

Çalıştırma: python bot_olcum.py --telegram
"""
from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from dataclasses import replace

import numpy as np

from aday_test import stats, trade
from fd_core import Params, run
from gecmis_tara import CAND, W, candidates
from scan import fetch_tv_all, get_tickers, telegram_send


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--telegram", action="store_true")
    args = ap.parse_args()
    frames = fetch_tv_all(get_tickers(), n_bars=1500, budget=30 * 60)
    lab: dict[str, dict[int, list]] = defaultdict(lambda: {2: [], 3: []})
    cand = {2: [], 3: []}
    ctrl = {2: [], 3: []}
    for sym, df in frames.items():
        try:
            c = df["Close"].to_numpy(float)
            h = df["High"].to_numpy(float)
            l = df["Low"].to_numpy(float)
            res = run(df, replace(Params(), **CAND))
            for e in res.events:
                if e["type"] != "setup" or e.get("cancelled"):
                    continue
                t = e["t"]
                if t < 80 or t > len(df) - 32:
                    continue
                for tr in (2, 3):
                    r = trade(c, h, l, t, h[t - W + 1:t + 1].max(), l[t - W + 1:t + 1].min(), tr)
                    if r is not None:
                        lab[e["mode"]][tr].append(r)
                        lab["TÜMÜ"][tr].append(r)
            for x in candidates(sym, df, skip_labeled=True, span=len(df)):
                for tr in (2, 3):
                    r = trade(c, h, l, x["i"], x["res"], x["lo"], tr)
                    if r is not None:
                        cand[tr].append(r)
            for i in range(80, len(df) - 32, 10):
                for tr in (2, 3):
                    r = trade(c, h, l, i, h[i - W + 1:i + 1].max(), l[i - W + 1:i + 1].min(), tr)
                    if r is not None:
                        ctrl[tr].append(r)
        except Exception as e:  # noqa: BLE001
            print(f"[uyarı] {sym}: {e}", file=sys.stderr)
    out = ["📏 Aynı kuralla ölçüm (brüt, komisyonsuz)", "Hedef 2R:"]
    for k in ("TÜMÜ", "Düşen", "Yatay", "Kutu"):
        if k in lab:
            out.append(f"  Bot etiketi {k:6}: {stats(lab[k][2])}")
    out += [f"  Aday pencereler : {stats(cand[2])}", f"  Kontrol         : {stats(ctrl[2])}", "Hedef 3R:"]
    for k in ("TÜMÜ", "Düşen", "Yatay", "Kutu"):
        if k in lab:
            out.append(f"  Bot etiketi {k:6}: {stats(lab[k][3])}")
    out += [f"  Aday pencereler : {stats(cand[3])}", f"  Kontrol         : {stats(ctrl[3])}",
            "Okuma: bot etiketi kontrolden belirgin iyiyse etiketin kendisi değer katıyor."]
    txt = "\n".join(out)
    print(txt)
    if args.telegram:
        telegram_send(txt[:3900])


if __name__ == "__main__":
    sys.exit(main())

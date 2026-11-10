"""Yatay seviye tanısı (10.11.2026): son mumda Python'un yatay aday seviyeleri ve her birinin şartları. Hiçbir ayarı değiştirmez.
Çalıştırma: python yatay_tani.py SANKO --telegram"""
from __future__ import annotations

import sys

import numpy as np

from fd_core import Params, prepare, run
from scan import fetch_tv_all, telegram_send

P = Params()


def main():
    syms = [a.upper() for a in sys.argv[1:] if not a.startswith("--")]
    out = []
    for n_bars in (500, 1000):
        fr = fetch_tv_all(syms, n_bars=n_bars, budget=120, min_bars=30)
        for s, df in fr.items():
            S = prepare(df, P)
            res = run(df, P)
            h, c = df["High"].to_numpy(float), df["Close"].to_numpy(float)
            t = len(c) - 1
            ev = [e for e in res.events if e["type"] == "setup" and e["t"] >= t - 5]
            out.append(f"\n{s} · {n_bars} mum · son mum {df.index[t]:%d.%m} kapanış {c[t]:.4g} · ADR %{S.adr[t]:.2f}")
            for e in ev:
                out.append(f"  etiket {e['date']:%d.%m} {e['mode']} çizgi {e['line']:.4g} temas {e.get('touches')} dar-bant {e.get('dt')} | {e.get('hnear', '')[:80]}")
            out.append(f"  bodyTol {S.bodyTol[t]:.4g} wickAbs {S.wickAbs[t]:.4g} touchTol {S.touchTol[t]:.4g} rankTol {S.rankTol[t]:.4g}")
            for k in range(1, max(P.nC, P.lastTouchMax) + 10):
                L = float(S.srcT[t - k])
                maxI = min(P.lookback, t - 1)
                idx = t - np.arange(1, maxI + 1)
                bad = (S.bodyTop[idx] > L + S.bodyTol[t]) | (h[idx] > L + S.wickAbs[t])
                span = int(np.argmax(bad)) if bad.any() else maxI
                d = np.abs(S.srcT[idx[:span]] - L)
                isT = d <= S.touchTol[t]
                pos = np.flatnonzero(isT)
                lt = int(pos[0]) + 1 if len(pos) else -1
                ft = int(pos[-1]) + 1 if len(pos) else -1
                prev = np.concatenate(([False], isT[:-1]))
                cl = int(np.count_nonzero(isT & ~prev))
                tb = int((d <= S.rankTol[t]).sum())
                mxH = max(L, float(h[t - ft:t + 1].max())) if ft >= 0 else L
                ag = float(((L - c[t - P.nC + 1:t + 1]) / c[t - P.nC + 1:t + 1] * 100).sum()) / P.nC / S.adr[t]
                lg = (L - c[t]) / c[t] * 100 / S.adr[t]
                ov = (mxH - L) / c[t] * 100 / S.adr[t]
                ok = (span >= P.minSpanH and int(isT.sum()) >= P.minTouches and 0 <= lt <= P.lastTouchMax and ft - lt >= P.touchSpan
                      and ag <= P.nearADRH and 0 <= lg <= P.lastNearH and ov <= P.maxOv and cl >= P.minClusters and tb >= P.minTb)
                out.append(f"  k{k:2d} {df.index[t - k]:%d.%m} seviye {L:.4g}: taban {span} temas {int(isT.sum())} küme {cl} dar {tb} "
                           f"son {lt} ilk-son {ft - lt} ort {ag:.2f} son-uz {lg:.2f} w {ov:.2f} -> {'GEÇER' if ok else '-'}")
    txt = "\n".join(out)
    print(txt)
    if "--telegram" in sys.argv:
        telegram_send(txt[:3900])


if __name__ == "__main__":
    main()

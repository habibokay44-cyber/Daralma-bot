"""Kullanıcının grafikte işaretlediği pencereler: 'doğru daralma' (d) ile 'yanlış' (y) arasında
hangi ölçü ayırt edici? Hiçbir ayarı değiştirmez, sadece ölçüp Telegram'a yazar.

Çalıştırma: python ayirt_et.py --telegram
"""
from __future__ import annotations

import argparse
import sys
import time
from dataclasses import replace

import numpy as np
import pandas as pd

from fd_core import Params, run
from scan import fetch_tv_all, telegram_send

CAND = dict(minClD=2, emaBelowMax=0.5, useShort=False, rallyU=0.9, rallyDd=2.0, bodyFrac=0.17, allowFlat=True, minTb=3)

# (hisse, başlangıç, bitiş, d=1/y=0)  -- 31.10.2026 geçmiş taramasından kullanıcı etiketleri
D = [("AGYO", "2025-10-16", "2025-10-23"), ("AKFYE", "2025-10-21", "2025-10-28"), ("ALVES", "2026-03-13", "2026-03-23"),
     ("AVPGY", "2025-07-25", "2025-08-01"), ("BEGYO", "2025-02-12", "2025-02-19"), ("CCOLA", "2026-03-11", "2026-03-18"),
     ("DARDL", "2025-07-16", "2025-07-23"), ("DYOBY", "2025-02-21", "2025-02-28"), ("ENERY", "2025-10-17", "2025-10-24"),
     ("ENJSA", "2026-01-19", "2026-01-26"), ("EYGYO", "2026-01-07", "2026-01-14"), ("INTEM", "2026-03-13", "2026-03-23"),
     ("IZMDC", "2026-01-19", "2026-01-26"), ("KLMSN", "2024-10-30", "2024-11-06"), ("KTLEV", "2026-05-05", "2026-05-12"),
     ("MTRKS", "2025-08-04", "2025-08-11"), ("ONRYT", "2026-06-15", "2026-06-22"), ("PETKM", "2026-06-30", "2026-07-07"),
     # kullanıcının ekstra gösterdiği doğru daralmalar
     ("EGPRO", "2026-08-06", "2026-08-11"), ("ENERY", "2026-08-20", "2026-08-24"), ("ESCAR", "2026-04-07", "2026-04-09"), ("KTLEV", "2026-04-14", "2026-04-17"),
     ("MAGEN", "2025-12-01", "2025-12-05"), ("MAGEN", "2026-04-27", "2026-05-01"), ("ONRYT", "2025-07-16", "2025-07-18"),
     ("OZATD", "2024-12-26", "2024-12-30")]
Y = [("AGHOL", "2025-10-28", "2025-11-05"), ("AKFGY", "2026-02-06", "2026-02-13"), ("AKGRT", "2025-11-24", "2025-12-01"),
     ("AKSGY", "2025-10-22", "2025-10-30"), ("AKSGY", "2026-08-07", "2026-08-14"), ("ARCLK", "2024-12-25", "2025-01-02"),
     ("BINHO", "2026-07-30", "2026-08-06"), ("EGPRO", "2026-07-08", "2026-07-16"), ("ESCAR", "2026-06-10", "2026-06-17"),
     ("MAVI", "2024-11-07", "2024-11-14"), ("OZATD", "2025-01-09", "2025-01-16"), ("PINSU", "2025-06-16", "2025-06-23"),
     ("RAYSG", "2024-11-14", "2024-11-21"), ("SAHOL", "2025-03-06", "2025-03-13"), ("SEKFK", "2026-06-05", "2026-06-12"),
     ("ULAS", "2024-12-02", "2024-12-09"), ("ULUFA", "2026-09-01", "2026-09-08"), ("USAK", "2026-01-08", "2026-01-15"),
     ("YATAS", "2025-08-27", "2025-09-03")]
LAB = [(s, a, b, 1) for s, a, b in D] + [(s, a, b, 0) for s, a, b in Y]


def feats(df: pd.DataFrame, res, a: str, b: str) -> dict | None:
    S = res.S
    idx = np.where((df.index >= pd.Timestamp(a)) & (df.index <= pd.Timestamp(b)))[0]
    if len(idx) < 3:
        return None
    t = int(idx[-1])
    s = int(idx[0])
    if t < 65:
        return None
    o, h, l, c = (np.asarray(x, dtype=float) for x in (S.o, S.h, S.l, S.c))
    adr = float(S.adr[t])
    bt, bl = np.maximum(o, c), np.minimum(o, c)
    f: dict = {}

    def g(name, arr):
        v = float(arr[t])
        if v == v:
            f[name] = v
    for name in ("emaSlope", "emaDist", "dd40", "e50d", "tightVal", "shrinkVal", "closeBoxVal", "riseVal", "slopeVal",
                 "b7Val", "lcCnt", "boxBodyVal", "boxHLVal", "lowAge", "candRng", "bodyFr"):
        try:
            g(name, np.asarray(getattr(S, name), dtype=float))
        except Exception:  # noqa: BLE001
            pass
    f["adr"] = adr
    f["bb"] = (bt[s:t + 1].max() / bl[s:t + 1].min() - 1) * 100 / adr
    f["hb"] = (h[s:t + 1].max() / l[s:t + 1].min() - 1) * 100 / adr
    for k in (10, 20, 40, 60):
        f[f"rise{k}"] = (c[t] / c[t - k] - 1) * 100 / adr
    lo60, hi60 = l[t - 60:t + 1].min(), h[t - 60:t + 1].max()
    f["pos60"] = (c[t] - lo60) / (hi60 - lo60) if hi60 > lo60 else 0.5
    f["adrRatio"] = adr / float(S.adr[t - 40]) if float(S.adr[t - 40]) > 0 else np.nan
    f["upFrac"] = float((np.diff(c[s - 1:t + 1]) > 0).mean())
    f["nearHi"] = (h[s:t + 1].max() - c[t]) * 100 / c[t] / adr
    rg = np.maximum(h[s:t + 1] - l[s:t + 1], 1e-12)
    f["bodyRat"] = float(((bt - bl)[s:t + 1] / rg).mean())
    f["bigBefore"] = float(((h - l) / c * 100 / adr)[s - 10:s].max())      # pencereden önceki 10 mumda en büyük aralık
    f["touch"] = float((h[s:t + 1] >= h[s:t + 1].max() - 0.3 * adr * c[t] / 100).sum())
    f["len"] = float(t - s + 1)
    return f


def auc(x: np.ndarray, y: np.ndarray) -> float:
    pos, neg = x[y == 1], x[y == 0]
    if len(pos) == 0 or len(neg) == 0:
        return 0.5
    gt = (pos[:, None] > neg[None, :]).sum() + 0.5 * (pos[:, None] == neg[None, :]).sum()
    return float(gt / (len(pos) * len(neg)))


def analyze(rows: list[tuple[str, str, dict, int]]) -> str:
    names = sorted({k for _, _, f, _ in rows for k in f})
    y = np.array([r[3] for r in rows])
    res = []
    for k in names:
        x = np.array([r[2].get(k, np.nan) for r in rows], dtype=float)
        ok = ~np.isnan(x)
        if ok.sum() < 20 or len(set(y[ok])) < 2:
            continue
        a = auc(x[ok], y[ok])
        # en iyi tek eşik doğruluğu
        best = max(((((x[ok] > th) == (y[ok] == 1)) if a >= 0.5 else ((x[ok] <= th) == (y[ok] == 1))).mean(), th)
                   for th in np.unique(x[ok]))
        res.append((abs(a - 0.5), k, a, best[0], best[1], float(np.median(x[ok][y[ok] == 1])), float(np.median(x[ok][y[ok] == 0]))))
    res.sort(reverse=True)
    # şans seviyesi: etiketler karıştırılınca en iyi ölçünün ne kadar ayırt ettiği
    rng = np.random.default_rng(1)
    chance = []
    X = {k: np.array([r[2].get(k, np.nan) for r in rows], dtype=float) for k in names}
    for _ in range(200):
        yy = rng.permutation(y)
        m = 0.0
        for k, x in X.items():
            ok = ~np.isnan(x)
            if ok.sum() < 20 or len(set(yy[ok])) < 2:
                continue
            m = max(m, abs(auc(x[ok], yy[ok]) - 0.5))
        chance.append(m)
    ch = float(np.percentile(chance, 95))
    out = [f"En iyi ölçüler (AUC 0.5=ayırt etmez, 1.0=tam ayırır; {len(rows)} pencere, d={int(y.sum())} y={int((1 - y).sum())}).",
           f"Şans seviyesi: etiketler rastgele olsa bile en iyi ölçü |AUC-0.5| ≈ {ch:.2f}'e çıkar (%95). Bundan küçük olan gürültüdür."]
    for d, k, a, acc, th, md, my in res[:12]:
        mark = "✅" if d > ch else "·"
        out.append(f"{mark} {k}: AUC {a:.2f} | tek eşikle doğruluk %{acc * 100:.0f} (eşik {th:.2f}) | d medyan {md:.2f}, y medyan {my:.2f}")
    return "\n".join(out)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--telegram", action="store_true")
    args = ap.parse_args()
    syms = sorted({s for s, *_ in LAB})
    frames = fetch_tv_all(syms, n_bars=1800, budget=10 * 60)
    P = replace(Params(), **CAND)
    cache: dict = {}
    rows = []
    for s, a, b, lab in LAB:
        df = frames.get(s)
        if df is None:
            continue
        if s not in cache:
            cache[s] = run(df, P)
        f = feats(df, cache[s], a, b)
        if f:
            rows.append((s, a, f, lab))
    txt = analyze(rows)
    lines = [f"{'d' if lab else 'y'} {s} {a[5:]} bb{f['bb']:.2f} rise20 {f['rise20']:+.1f} rise60 {f['rise60']:+.1f} pos60 {f['pos60']:.2f} "
             f"e50 {f.get('e50d', float('nan')):+.1f} ema {f.get('emaSlope', float('nan')):+.1f}/{f.get('emaDist', float('nan')):+.1f} "
             f"dd{f.get('dd40', float('nan')):.1f} b7 {f.get('b7Val', float('nan')):.2f} k{f.get('closeBoxVal', float('nan')):.2f}"
             for s, a, f, lab in sorted(rows, key=lambda r: (-r[3], r[0]))]
    out = "📊 Ayırt edici ölçü analizi\n" + txt + "\n\nPencere başına ölçüler:\n" + "\n".join(lines)
    print(out)
    if args.telegram:
        parts, cur = [], ""
        for line in out.split("\n"):
            if cur and len(cur) + len(line) + 1 > 3500:
                parts.append(cur)
                cur = ""
            cur = (cur + "\n" + line) if cur else line
        if cur:
            parts.append(cur)
        for i, p in enumerate(parts, 1):
            telegram_send(f"({i}/{len(parts)})\n" + p[:3900])
            time.sleep(1)


if __name__ == "__main__":
    sys.exit(main())

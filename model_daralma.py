"""Daralma modeli v1 (09.11.2026): tek tek kural yerine, senin işaretlerinden öğrenen küçük model.
Neden: işaret-getiri testi -> daralma etiketlerinde 'alırdım' PF 3-4.7, 'almazdım' PF 0.65-0.70. Tek ölçüler ayırmadı;
birkaç zayıf ölçü birlikte ayırabilir. Hiçbir gösterge ayarını değiştirmez.

Veri   : daralma işaretleri (Base hariç): etiket_kayit (a, g = iyi; h = kötü) + orneklem 1-3 (d = iyi; y = kötü).
Model  : lojistik regresyon, L2 (lambda = 3.0 SABİT, ayar aranmaz), özellikler fold içinde standardize, ±3 SS kırpma.
Özellik: aşağıdaki 26 ölçü, sonuç görülmeden sabitlendi (FEATS). Hepsi işaret günü ve öncesinden hesaplanır.
Ölçüm  : hisseye göre gruplu 5 katlı çapraz doğrulama x 20 tekrar (aynı hisse hem öğrenme hem sınamada olmaz).
ÖNCEDEN YAZILMIŞ KABUL (1. aşama, üçü birden):
  a) çapraz doğrulama AUC >= 0.68
  b) etiket karıştırma testi (200 kez) p < 0.05
  c) model puanı üst yarısının ort. R'si alt yarısından yüksek (R: isaret_getiri ile aynı çıkış)
2. aşama (1 geçerse): yeni 40 kör grafik (20 yüksek puan + 20 düşük puan, gizli); kabul: yüksek puanlıda alırdım >= %65
  ve düşük puanlıdan en az 20 puan fazla. Ancak ondan sonra taramada kullanılır (önce sıralama / gölge olarak).
Çalıştırma: python model_daralma.py --telegram
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

import numpy as np
import pandas as pd

import kayit
from fd_core import Params, prepare
from isaret_getiri import sim
from scan import fetch_tv_all, telegram_send

ST = Path(__file__).resolve().parent / "state"
LAM, KAT, TEKRAR, PERM = 3.0, 5, 20, 200
S_FEATS = ["tightVal", "shrinkVal", "closeBoxVal", "bodyBox10", "lowDiff", "riseVal", "slopeVal", "candRng", "redSig",
           "emaSlope", "emaDist", "dd40", "e50d", "b7Val", "bodyFr", "lcCnt", "boxBodyVal", "boxHLVal"]
X_FEATS = ["e50egim", "konum40", "tepe120", "yukselis60", "haftalik", "hacim5_50", "rs60", "direncUzak"]
FEATS = S_FEATS + X_FEATS


def ozellik(df, t, S, xu, direnc):
    o, h, l, c, v = (df[k].to_numpy(float) for k in ("Open", "High", "Low", "Close", "Volume"))
    A = S.adr[t]
    f = {k: float(np.asarray(getattr(S, k), float)[t]) for k in S_FEATS}
    e50 = np.asarray(S.ema50, float)
    f["e50egim"] = (e50[t] / e50[t - 10] - 1) * 100 / A
    H40, L40 = h[t - 39:t + 1].max(), l[t - 39:t + 1].min()
    f["konum40"] = (c[t] - L40) / (H40 - L40) if H40 > L40 else 0.5
    f["tepe120"] = (h[max(0, t - 119):t + 1].max() / c[t] - 1) * 100 / A
    f["yukselis60"] = (c[t] / l[max(0, t - 59):t + 1].min() - 1) * 100 / A
    wk = df["Close"].iloc[:t + 1].resample("W-FRI").last().dropna()
    f["haftalik"] = (wk.iloc[-1] / wk.ewm(span=10, adjust=False).mean().iloc[-1] - 1) * 100 if len(wk) >= 10 else np.nan
    f["hacim5_50"] = v[t - 4:t + 1].mean() / v[t - 49:t + 1].mean() if v[t - 49:t + 1].mean() > 0 else np.nan
    f["rs60"] = np.nan
    if xu is not None and t >= 60:
        d0, d1 = df.index[t - 60], df.index[t]
        x = xu["Close"]
        if d0 in x.index and d1 in x.index:
            f["rs60"] = (c[t] / c[t - 60] - 1) * 100 - (x[d1] / x[d0] - 1) * 100
    f["direncUzak"] = (direnc / c[t] - 1) * 100 / A if direnc and direnc > 0 else np.nan
    return f


def fit(X, y):
    w = np.zeros(X.shape[1] + 1)
    Xb = np.c_[np.ones(len(X)), X]
    R = np.eye(len(w)) * LAM
    R[0, 0] = 0
    for _ in range(50):
        p = 1 / (1 + np.exp(-Xb @ w))
        g = Xb.T @ (p - y) + R @ w
        Hs = (Xb * (p * (1 - p))[:, None]).T @ Xb + R + 1e-8 * np.eye(len(w))
        d = np.linalg.solve(Hs, g)
        w -= d
        if np.abs(d).max() < 1e-7:
            break
    return w


def hazirla(Xtr, Xte):
    med = np.nanmedian(Xtr, 0)
    Xtr, Xte = np.where(np.isnan(Xtr), med, Xtr), np.where(np.isnan(Xte), med, Xte)
    mu, sd = Xtr.mean(0), Xtr.std(0) + 1e-9
    return np.clip((Xtr - mu) / sd, -3, 3), np.clip((Xte - mu) / sd, -3, 3)


def auc(s, y):
    a, b = s[y == 1], s[y == 0]
    return float(np.mean((a[:, None] > b[None, :]) + 0.5 * (a[:, None] == b[None, :])))


def cv(X, y, grp, rng, tekrar):
    oof = np.zeros(len(y))
    ug = np.unique(grp)
    for _ in range(tekrar):
        perm = rng.permutation(ug)
        fold = {g: i % KAT for i, g in enumerate(perm)}
        fi = np.array([fold[g] for g in grp])
        for k in range(KAT):
            tr, te = fi != k, fi == k
            if te.sum() == 0 or len(set(y[tr])) < 2:
                continue
            a, b = hazirla(X[tr], X[te])
            w = fit(a, y[tr])
            oof[te] += np.c_[np.ones(len(b)), b] @ w
    return oof / tekrar


def main():
    rows = []
    for r in kayit.load():
        i = (r.get("isaret") or "").strip().lower()
        if i in ("a", "g", "h") and not (r.get("mod") or "").startswith("Base"):
            rows.append((r["hisse"], r["etiket_tarihi"], 0 if i == "h" else 1, r.get("direnc")))
    for f in ("orneklem.csv", "orneklem2.csv", "orneklem3.csv"):
        p = ST / f
        if p.exists():
            for r in csv.DictReader(p.open(encoding="utf-8")):
                i = (r.get("isaret") or "").strip().lower()
                if i in ("d", "y"):
                    rows.append((r["hisse"], r["etiket_tarihi"], 1 if i == "d" else 0, r.get("direnc")))
    rows = list({(s, d): (s, d, y, dr) for s, d, y, dr in rows}.values())
    frames = fetch_tv_all(sorted({r[0] for r in rows}), n_bars=1500, budget=14 * 60, min_bars=30)
    xu = fetch_tv_all(["XU100"], n_bars=1500, budget=120, min_bars=30).get("XU100")
    D = []
    for s, d, y, dr in rows:
        df = frames.get(s)
        ts = pd.Timestamp(d)
        if df is None or ts not in df.index:
            continue
        t = int(df.index.get_loc(ts))
        if t < 130:
            continue
        try:
            dr_ = float(str(dr).replace(",", "."))
        except Exception:  # noqa: BLE001
            dr_ = np.nan
        f = ozellik(df, t, prepare(df, Params()), xu, dr_)
        x = sim(df, t)
        D.append(dict(hisse=s, tarih=d, y=y, R=x[0] if x else np.nan, **f))
    T = pd.DataFrame(D)
    X = T[FEATS].to_numpy(float)
    X[~np.isfinite(X)] = np.nan
    y, grp = T.y.to_numpy(int), T.hisse.to_numpy()
    rng = np.random.default_rng(56)
    oof = cv(X, y, grp, rng, TEKRAR)
    A = auc(oof, y)
    null = np.array([auc(cv(X, yp, grp, rng, 1), yp) for yp in (rng.permutation(y) for _ in range(PERM))])
    p = float((null >= A).mean())
    ust = oof >= np.median(oof)
    Rm = T.R.to_numpy(float)
    ru, ra = np.nanmean(Rm[ust]), np.nanmean(Rm[~ust])
    ok = A >= 0.68 and p < 0.05 and ru > ra
    out = [f"🧠 Daralma modeli v1: {len(T)} işaretli grafik (iyi {int(y.sum())}, kötü {int((1 - y).sum())}), {len(FEATS)} ölçü, RS verisi {'var' if xu is not None else 'YOK'}",
           f"a) çapraz doğrulama AUC {A:.2f} (eşik 0.68) {'✅' if A >= 0.68 else '❌'}",
           f"b) karıştırma testi: şans AUC ort {null.mean():.2f}, en yüksek %5'i {np.percentile(null, 95):.2f}; p = {p:.3f} {'✅' if p < 0.05 else '❌'}",
           f"c) puanı üst yarı: alırdım %{100 * y[ust].mean():.0f}, ort {ru:+.2f}R | alt yarı: alırdım %{100 * y[~ust].mean():.0f}, ort {ra:+.2f}R {'✅' if ru > ra else '❌'}",
           f"-> 1. aşama: {'✅ GEÇTİ (sıradaki: yeni 40 kör grafik)' if ok else '❌ geçmedi'}"]
    q = np.quantile(oof, [0.25, 0.5, 0.75])
    for ad, m in (("en yüksek çeyrek", oof >= q[2]), ("3. çeyrek", (oof >= q[1]) & (oof < q[2])), ("2. çeyrek", (oof >= q[0]) & (oof < q[1])), ("en düşük çeyrek", oof < q[0])):
        out.append(f"   {ad}: n={int(m.sum())} · alırdım %{100 * y[m].mean():.0f} · ort {np.nanmean(Rm[m]):+.2f}R")
    a, _ = hazirla(X, X)
    w = fit(a, y)[1:]
    sir = np.argsort(-np.abs(w))[:8]
    out.append("En etkili ölçüler (+ = büyükse alırdım artar): " + ", ".join(f"{FEATS[i]} {w[i]:+.2f}" for i in sir))
    T.assign(puan=oof).to_csv("model_daralma.csv", index=False)
    txt = "\n".join(out)
    print(txt)
    if "--telegram" in sys.argv:
        telegram_send(txt[:3900])


if __name__ == "__main__":
    main()

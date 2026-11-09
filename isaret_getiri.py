"""İşaret-getiri testi (09.11.2026): "alırdım" dediğin grafikler, "almazdım" dediklerinden sonra gerçekten daha mı iyi gitti?
Bugüne kadar bütün testler göstergeyi senin gözüne benzetmeye çalıştı; gözünün getiriye katkısı hiç ölçülmedi.
Hiçbir ayarı değiştirmez.

Veri: tüm kör işaretler (grafik işaret gününde bitiyordu): etiket_kayit.csv (a / g / h) + orneklem 1-3 (d / y).
  İYİ = a, d   ·   KÖTÜ = h, y   ·   g (başka gün alırdım) ayrı satır, b sayılmaz.
ÖNCEDEN YAZILMIŞ ÖLÇÜ (base_v0 T2 ile aynı çıkış, herkese aynı):
  alış = işaret günü kapanışı, stop = önceki 10 mumun en düşüğü; stop değerse çıkış (gap varsa açılış), değmezse
  20 mum sonra kapanış. R = (çıkış - alış) / (alış - stop). Sonrasında 20 mum olmayan grafikler sayılmaz.
ÖNCEDEN YAZILMIŞ KARAR:
  "Gözün değer katıyor"  = İYİ ort. R - KÖTÜ ort. R farkının %90 güven aralığı (bootstrap, 5000) sıfırın ÜSTÜNDE.
  "Fark yok"             = aralık sıfırı içeriyor.   Yan bilgi: kazanma oranı, PF, 20 mumluk getiri (ADR katı), gruplara göre.
Çalıştırma: python isaret_getiri.py --telegram
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

import numpy as np
import pandas as pd

import kayit
from scan import fetch_tv_all, telegram_send

W, GUN = 10, 20
ST = Path(__file__).resolve().parent / "state"


def sim(df, t):
    o, h, l, c = (df[k].to_numpy(float) for k in ("Open", "High", "Low", "Close"))
    if t + GUN >= len(c) or t < 25:
        return None
    entry, stop = c[t], l[t - W:t].min()
    if entry <= stop:
        return None
    A = (np.mean(h[t - 20:t] / l[t - 20:t]) - 1) * 100
    r = (c[t + GUN] - entry) / (entry - stop)
    for u in range(t + 1, t + GUN + 1):
        if l[u] <= stop:
            r = (min(o[u], stop) - entry) / (entry - stop)
            break
    return r, (c[t + GUN] / entry - 1) * 100 / A


def oz(R):
    R = np.asarray(R, float)
    if not len(R):
        return "n=0"
    pf = R[R > 0].sum() / -R[R <= 0].sum() if (R <= 0).any() and R[R <= 0].sum() < 0 else np.inf
    return f"n={len(R)} · ort {R.mean():+.2f}R · medyan {np.median(R):+.2f}R · kazanma %{100 * (R > 0).mean():.0f} · PF {pf:.2f}"


def fark(a, b, rng):
    a, b = np.asarray(a, float), np.asarray(b, float)
    if len(a) < 5 or len(b) < 5:
        return None
    d = [rng.choice(a, len(a)).mean() - rng.choice(b, len(b)).mean() for _ in range(5000)]
    return a.mean() - b.mean(), np.percentile(d, 5), np.percentile(d, 95)


def main():
    rows = []
    for r in kayit.load():
        i = (r.get("isaret") or "").strip().lower()
        m = r.get("mod") or ""
        grup = "Base" if m.startswith("Base") else "Daralma (Telegram grafiği, kesin kör)"
        if i in ("a", "g", "h"):
            rows.append((r["hisse"], r["etiket_tarihi"], grup, {"a": "iyi", "h": "kotu", "g": "g"}[i]))
    for f in ("orneklem.csv", "orneklem2.csv", "orneklem3.csv"):
        p = ST / f
        if p.exists():
            for r in csv.DictReader(p.open(encoding="utf-8")):
                i = (r.get("isaret") or "").strip().lower()
                if i in ("d", "y"):
                    rows.append((r["hisse"], r["etiket_tarihi"], "Daralma (eski örneklem 1-3, TradingView'de bakıldı)", "iyi" if i == "d" else "kotu"))
    rows = list({(s, d): (s, d, g, k) for s, d, g, k in rows}.values())
    frames = fetch_tv_all(sorted({r[0] for r in rows}), n_bars=1500, budget=14 * 60, min_bars=30)
    D, atla = [], 0
    for s, d, g, k in rows:
        df = frames.get(s)
        ts = pd.Timestamp(d)
        if df is None or ts not in df.index:
            atla += 1
            continue
        x = sim(df, int(df.index.get_loc(ts)))
        if x is None:
            atla += 1
            continue
        D.append(dict(hisse=s, tarih=d, grup=g, k=k, R=x[0], g20=x[1]))
    T = pd.DataFrame(D)
    rng = np.random.default_rng(56)
    out = [f"💰 İşaret-getiri testi: {len(T)} kör işaretli grafik ({atla} sayılmadı: veri yok ya da sonrası 20 mumdan kısa)",
           "Çıkış herkese aynı: alış işaret günü kapanışı, stop önceki 10 mumun dibi, en geç 20 mum sonra."]
    for ad, S in [("TÜMÜ", T)] + [(g, T[T.grup == g]) for g in sorted(T.grup.unique())]:
        iy, ko, gg = S[S.k == "iyi"], S[S.k == "kotu"], S[S.k == "g"]
        out.append(f"\n{ad}")
        out.append(f"  ✅ alırdım : {oz(iy.R)} · 20 mum {iy.g20.mean():+.2f} ADR" if len(iy) else "  ✅ alırdım : n=0")
        out.append(f"  ❌ almazdım: {oz(ko.R)} · 20 mum {ko.g20.mean():+.2f} ADR" if len(ko) else "  ❌ almazdım: n=0")
        if len(gg):
            out.append(f"  ⏳ başka gün: {oz(gg.R)}")
        f = fark(iy.R, ko.R, rng)
        if f:
            karar = "GÖZÜN DEĞER KATIYOR ✅" if f[1] > 0 else ("ters yönde ❗" if f[2] < 0 else "fark kanıtlanamadı (aralık sıfırı içeriyor)")
            out.append(f"  fark {f[0]:+.2f}R (%90 aralık {f[1]:+.2f} … {f[2]:+.2f}) -> {karar}")
    T.to_csv("isaret_getiri.csv", index=False)
    txt = "\n".join(out)
    print(txt)
    if "--telegram" in sys.argv:
        telegram_send(txt[:3900])


if __name__ == "__main__":
    main()

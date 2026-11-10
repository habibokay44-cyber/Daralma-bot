"""Sadeleştirme testi (10.11.2026): göstergedeki filtrelerden hangisi gerçekten işe yarıyor?
Her filtre TEK TEK kapatılır, şimdiki ayarla (hepsi açık) karşılaştırılır. Hiçbir ayarı değiştirmez; karar sonra birlikte.

Ölçü (varyant_test ile aynı): sadece Giriş sinyalleri, tek tek işlem, ertesi açılış +%0.5 alış, Iz10 kapanışla çıkış,
  20 günlük hacim >= 10 milyon TL. D1 = 2023-24, D2 = 2025-bugün.
'Engellenen' = filtre kapatılınca ortaya çıkan, filtre açıkken olmayan Giriş'ler (filtrenin durdurduğu işlemler).
ÖNCEDEN YAZILMIŞ SINIFLAMA (kalan = şimdiki ayarın Giriş'leri):
  İŞE YARIYOR = kalan - engellenen ort. R farkının %90 güven aralığı (bootstrap 4000) sıfırın ÜSTÜNDE
  ZARARLI     = aralık sıfırın ALTINDA (engelledikleri kalanlardan iyi) VE filtre kapalıyken iki dönemde de ort. R yüksek
  ETKİSİZ     = diğerleri (fark kanıtlanamıyor) · engellenen 30'dan azsa 'ölçülemez'
Kaldırma kararı ayrıca kalibrasyondaki doğru / yanlış örneklere de bakılarak verilir (bu test sadece getiriye bakar).
Çalıştırma: python sade_test.py 1 --telegram     (parti: 1, 2 ya da 3)
"""
from __future__ import annotations

import sys
from dataclasses import replace

import numpy as np
import pandas as pd

from fd_core import Params, run
from rs_test import tek_R
from scan import fetch_tv_all, get_tickers, telegram_send

PARTI = {
    1: [("d  dipler kontrolü", dict(useLows=False)), ("u  dirence yaklaşma", dict(useRise=False)),
        ("s  son kapanış eğimi", dict(useSlope=False)), ("c/p sinyal mumu şekli", dict(useCandle=False)),
        ("j  sıçrama", dict(useJump=False)), ("v  hacim üst sınırı", dict(useVolSig=False)),
        ("g  kırmızı mum", dict(useRedSig=False)), ("e  EMA21 trend kapısı", dict(useEmaTr=False))],
    2: [("T  40 mum tepesinden düşüş", dict(ddMax=0.0)), ("R  rallide etiket yok", dict(rallyU=0.0)),
        ("bf gövde/aralık", dict(bodyFrac=0.0)), ("b7 7 mum gövde aralığı", dict(b7Max=0.0)),
        ("lc art arda düşüş", dict(lcMax=0)), ("dn düşüşte min temas", dict(dnMinTb=0)),
        ("sp düşen çizgi min uzunluk", dict(dnMinSp=0)), ("rl düşen: sıkışma alt sınırı", dict(shrinkMinD=0.0))],
    3: [("eb düşen: EMA altı + eğim", dict(dnBelowSlope=-99.0)), ("H  yatayda düşüş engeli", dict(hDnBlock=False)),
        ("Y  yatay gövde kutusu", dict(yBodyMax=0.0)), ("KUTU modu", dict(useBox=False)),
        ("iptal: stop", dict(useStop=False)), ("iptal: kırmızı mum", dict(useRedKill=False)),
        ("iptal: düşüş", dict(useDrop=False)), ("Giriş: etiket kapanışı üstü", dict(useAboveLbl=False))],
}
D1S, D2S = pd.Timestamp("2023-01-02"), pd.Timestamp("2025-01-01")


def main():
    parti = int([a for a in sys.argv[1:] if not a.startswith("--")][0])
    VARS = PARTI[parti]
    frames = fetch_tv_all(get_tickers(), n_bars=1200, budget=25 * 60, min_bars=120)
    PS = [("ADAY", Params())] + [(ad, replace(Params(), **kw)) for ad, kw in VARS]
    S = {ad: {} for ad, _ in PS}
    for s, df in frames.items():
        hac = (df["Close"] * df["Volume"]).rolling(20).mean().to_numpy()
        for ad, P in PS:
            try:
                for e in run(df, P).events:
                    i = int(e["t"]) if e["type"] == "giris" else -1
                    if i >= 0 and e["date"] >= D1S and hac[i] >= 1e7:
                        r = tek_R(df, i, e["sl"])
                        if r is not None:
                            S[ad][(s, e["date"])] = r
            except Exception as ex:  # noqa: BLE001
                print(f"[uyarı] {s} {ad}: {ex}")
    rng = np.random.default_rng(56)
    A = S["ADAY"]
    a = np.array(list(A.values()))
    don = lambda d, k: np.mean([r for (s, t), r in d.items() if (t < D2S) == (k == 1)])  # noqa: E731
    out = [f"🧹 Sadeleştirme testi, parti {parti}/3 · {len(frames)} hisse · şimdiki ayar: {len(a)} Giriş, ort {a.mean():+.2f}R "
           f"(D1 {don(A, 1):+.2f} · D2 {don(A, 2):+.2f})",
           "filtre: engellediği n · ort R | kalan - engellenen (%90 aralık) | kapalıyken D1 · D2 -> sınıf"]
    for ad, _ in PS[1:]:
        V = S[ad]
        eng = np.array([r for k, r in V.items() if k not in A])
        kay = sum(1 for k in A if k not in V)
        if len(eng) < 30:
            out.append(f"• {ad}: engellediği {len(eng)} (yan etki: {kay} Giriş kayboluyor) -> ölçülemez (az)")
            continue
        d = [rng.choice(a, len(a)).mean() - rng.choice(eng, len(eng)).mean() for _ in range(4000)]
        lo, hi = np.percentile(d, 5), np.percentile(d, 95)
        iki = don(V, 1) > don(A, 1) and don(V, 2) > don(A, 2)
        sinif = "✅ İŞE YARIYOR" if lo > 0 else ("❗ ZARARLI" if hi < 0 and iki else "➖ etkisiz")
        out.append(f"• {ad}: {len(eng)} · {eng.mean():+.2f}R | {a.mean() - eng.mean():+.2f}R ({lo:+.2f} … {hi:+.2f}) | "
                   f"{don(V, 1):+.2f} · {don(V, 2):+.2f} -> {sinif}")
        # SAĞLAMLIK (10.11.2026, ilk turdan sonra eklendi): tek tük dev işlemler ortalamayı bozuyor (ör. +16.8R ortalama).
        # Aynı sınıflama, R üstten +10R ile kırpılarak; ayrıca medyan ve kazanma oranı.
        ak, ek = np.minimum(a, 10.0), np.minimum(eng, 10.0)
        dk = [rng.choice(ak, len(ak)).mean() - rng.choice(ek, len(ek)).mean() for _ in range(4000)]
        l2, h2 = np.percentile(dk, 5), np.percentile(dk, 95)
        s2 = "✅ işe yarıyor" if l2 > 0 else ("❗ zararlı" if h2 < 0 else "➖ etkisiz")
        out.append(f"    kırpılmış (+10R): engellenen {ek.mean():+.2f}R, kalan {ak.mean():+.2f}R, fark ({l2:+.2f} … {h2:+.2f}) -> {s2} · "
                   f"engellenen kazanma %{100 * (eng > 0).mean():.0f} (kalan %{100 * (a > 0).mean():.0f}) · medyan {np.median(eng):+.2f}R")
    txt = "\n".join(out)
    print(txt)
    if "--telegram" in sys.argv:
        telegram_send(txt[:3900])


if __name__ == "__main__":
    main()

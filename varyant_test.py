"""Varyant testi, iki dönem (09.11.2026): küçük örneklemde reddedilen GY1 ve V3, binlerce işlemle yeniden ölçülür.
  GY1 = Giriş için kapanış son 10 mumun gövde tepesini de geçmeli (girisYatayN=10)
  V3  = fitilin çizgiyi geçme payı 2.5 -> 0.5 ADR (wickADR=0.5)
İkisi de kalibrasyonda yanlış etiketi 14 -> 11'e indirmiş, 7-14 grafiklik ölçütü geçememişti (o ölçüt çok küçük örnekliydi).
Hiçbir ayarı değiştirmez. Sadece GİRİŞ sinyalleri (Base etkilenmez).

Ölçü: tek tek işlemler, yer sınırı yok (5 yerin şansı karışmasın): ertesi gün açılış +%0.5 alış, Iz10 kapanışla çıkış,
  sonraki açılış -%0.5 satış, 20 günlük hacim >= 10 milyon TL. Dönemler: D1 = 2023-24, D2 = 2025-bugün.
ÖNCEDEN YAZILMIŞ KABUL (her varyant için, ikisi birden):
  a) iki dönemde de varyantın Giriş sinyallerinin ort. R'si şimdiki ayardan yüksek
  b) tüm veride: varyantın sinyalleri (kalan + eklenen) ile varyantın ATTIĞI sinyaller arasındaki ort. R farkının
     %90 güven aralığı (bootstrap 5000) sıfırın üstünde  -> atılanlar gerçekten daha kötü
Yan bilgi: işlem sayısı, toplam R, kazanma oranı. Geçen varyant Python'a ve Pine'a eklenir.
Çalıştırma: python varyant_test.py --telegram
"""
from __future__ import annotations

import sys
from dataclasses import replace

import numpy as np
import pandas as pd

from fd_core import Params, run
from rs_test import tek_Reff
from scan import fetch_tv_all, get_tickers, telegram_send

# 10.11.2026: V3 artık varsayılan olduğu için karşılaştırma tabanı ESKİ ayar (wickADR 2.5); ölçü portföy-eşdeğeri R.
ESKI = dict(wickADR=2.5)
VARS = [("V3 (fitil payı 0.5)", dict(wickADR=0.5)), ("GY1 (eski ayar + Giriş yatay gövde tepesi)", dict(wickADR=2.5, girisYatayN=10))]
D1S, D2S = pd.Timestamp("2023-01-02"), pd.Timestamp("2025-01-01")


def oz(x):
    x = np.asarray(x, float)
    return f"n={len(x)} · ort {x.mean():+.2f}R · toplam {x.sum():+.0f}R · kazanma %{100 * (x > 0).mean():.0f}" if len(x) else "n=0"


def main():
    frames = fetch_tv_all(get_tickers(), n_bars=1200, budget=25 * 60, min_bars=120)
    PS = [("ADAY", replace(Params(), **ESKI))] + [(ad, replace(Params(), **kw)) for ad, kw in VARS]
    S = {ad: {} for ad, _ in PS}     # ad -> {(sym, tarih): R}
    for s, df in frames.items():
        hac = (df["Close"] * df["Volume"]).rolling(20).mean().to_numpy()
        for ad, P in PS:
            try:
                for e in run(df, P).events:
                    i = int(e["t"]) if e["type"] == "giris" else -1
                    if i >= 0 and e["date"] >= D1S and hac[i] >= 1e7:
                        r = tek_Reff(df, i, e["sl"])   # 10.11.2026: portföy-eşdeğeri R
                        if r is not None:
                            S[ad][(s, e["date"])] = r
            except Exception as ex:  # noqa: BLE001
                print(f"[uyarı] {s} {ad}: {ex}")
    rng = np.random.default_rng(56)
    A = S["ADAY"]
    don = lambda d, k: [r for (s, t), r in d.items() if (t < D2S) == (k == 1)]  # noqa: E731
    out = [f"⚖️ Varyant testi (iki dönem) · {len(frames)} hisse · sadece Giriş sinyalleri, tek tek işlem",
           f"Eski ayar (fitil payı 2.5): D1 {oz(don(A, 1))} | D2 {oz(don(A, 2))}"]
    for ad, _ in PS[1:]:
        V = S[ad]
        atilan = [r for k, r in A.items() if k not in V]
        eklenen = [r for k, r in V.items() if k not in A]
        a_ok = all(np.mean(don(V, k)) > np.mean(don(A, k)) for k in (1, 2))
        v, at = np.array(list(V.values())), np.array(atilan)
        if len(at) >= 5:
            d = [rng.choice(v, len(v)).mean() - rng.choice(at, len(at)).mean() for _ in range(5000)]
            lo, hi = np.percentile(d, 5), np.percentile(d, 95)
        else:
            lo = hi = np.nan
        b_ok = lo > 0
        out += [f"\n{ad}",
                f"  D1 {oz(don(V, 1))}",
                f"  D2 {oz(don(V, 2))}",
                f"  attığı sinyaller: {oz(atilan)} | eklediği: {oz(eklenen)}",
                f"  a) iki dönemde de ort. R yüksek {'✅' if a_ok else '❌'} · b) kalan - atılan farkı {v.mean() - (at.mean() if len(at) else np.nan):+.2f}R "
                f"(%90 aralık {lo:+.2f} … {hi:+.2f}) {'✅' if b_ok else '❌'} -> {'✅ KABUL' if a_ok and b_ok else '❌ red'}"]
    txt = "\n".join(out)
    print(txt)
    if "--telegram" in sys.argv:
        telegram_send(txt[:3900])


if __name__ == "__main__":
    main()

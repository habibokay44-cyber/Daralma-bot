"""RS güçlü testi (11.11.2026): RS çizgisi (hisse / XU100) güçlüyken gelen sinyaller daha mı çok kazandırıyor? Ayar değiştirmez.
RS güçlü tanımı rs.py'de (önceden sabit): sinyal günü RS çizgisi 60 gün zirvesinin en fazla %2 altında VEYA EMA50'sinin üstünde
ve EMA50 yükseliyor. (09.11'deki RS60 testi farklıydı: 60 günlük getiri farkıyla sıralama.)
Sinyaller: şimdiki Giriş + Base v0, hacim >= 10 milyon TL. Ölçü: tek tek işlem, portföy-eşdeğeri R (Iz10, ertesi açılış, %0.5 kayma).
ÖNCEDEN YAZILMIŞ KABUL (ikisi birden):
  a) iki dönemde de (2023-24, 2025-) RS güçlü sinyallerin ort. R'si zayıflardan yüksek
  b) tüm veride güçlü - zayıf farkının %90 güven aralığı (bootstrap 4000) sıfırın üstünde
Geçerse 2. adım (ayrı, önceden yazılı): portföyde 'RS güçlü önce' sıralaması / 'sadece RS güçlü' filtresi benzetimi.
Yan bilgi: Giriş ve Base ayrı; güçlü oranı; aynı testin portföy benzetimi.
Çalıştırma: python rs_guc_test.py --telegram
"""
from __future__ import annotations

import sys

import numpy as np
import pandas as pd

import rs
from base_v0 import sinyaller as base_sinyaller
from fd_core import Params, run
from geriye_portfoy import simule
from rs_test import tek_Reff
from scan import fetch_tv_all, get_tickers, telegram_send

D1S, D2S = pd.Timestamp("2023-01-02"), pd.Timestamp("2025-01-01")
KW = dict(mod="acilis", kayma=0.005, minhacim=1e7)


def main():
    frames = fetch_tv_all(get_tickers(), n_bars=1200, budget=25 * 60, min_bars=30)
    xu = fetch_tv_all(["XU100"], n_bars=1200, budget=120, min_bars=30).get("XU100")
    xc = xu["Close"].astype(float)
    T, sig = [], []
    for s, df in frames.items():
        try:
            hac = (df["Close"] * df["Volume"]).rolling(20).mean().to_numpy()
            lo = df["Low"].to_numpy(float)
            ev = []
            if len(df) >= 120:
                ev += [("Giriş", e, e["sl"]) for e in run(df, Params()).events if e["type"] == "giris"]
            ev += [("Base", e, float(lo[e["t"]])) for e in base_sinyaller(df)]
            for k, e, dip in ev:
                if e["date"] < D1S:
                    continue
                i = int(e["t"])
                o = rs.olc(df, xc, e["date"])
                if o is None:
                    continue
                sig.append(dict(sym=s, kaynak=k, tarih=e["date"], i=i, kapanis=e["close"], dip=dip, guclu=o["guclu"],
                                rsg=1.0 if o["guclu"] else 0.0))
                if hac[i] >= 1e7:
                    r = tek_Reff(df, i, dip)
                    if r is not None:
                        T.append(dict(k=k, d2=e["date"] >= D2S, g=o["guclu"], R=r))
        except Exception as ex:  # noqa: BLE001
            print(f"[uyarı] {s}: {ex}")
    T = pd.DataFrame(T)
    rng = np.random.default_rng(56)
    out = [f"💪 RS güçlü testi · {len(frames)} hisse · {len(T)} işlem (hacimli) · RS güçlü oranı %{100 * T.g.mean():.0f}"]
    a = True
    for ad, m in (("2023-24", ~T.d2), ("2025-26", T.d2)):
        G, Z = T[m & T.g].R, T[m & ~T.g].R
        a = a and G.mean() > Z.mean()
        out.append(f"  {ad}: güçlü n={len(G)} ort {G.mean():+.2f}R kazanma %{100 * (G > 0).mean():.0f} | zayıf n={len(Z)} ort {Z.mean():+.2f}R "
                   f"kazanma %{100 * (Z > 0).mean():.0f}")
    for kk in ("Giriş", "Base"):
        G, Z = T[(T.k == kk) & T.g].R, T[(T.k == kk) & ~T.g].R
        out.append(f"  {kk}: güçlü n={len(G)} ort {G.mean():+.2f}R | zayıf n={len(Z)} ort {Z.mean():+.2f}R")
    G, Z = T[T.g].R.to_numpy(), T[~T.g].R.to_numpy()
    d = [rng.choice(G, len(G)).mean() - rng.choice(Z, len(Z)).mean() for _ in range(4000)]
    lo_, hi_ = np.percentile(d, 5), np.percentile(d, 95)
    b = lo_ > 0
    out.append(f"a) iki dönemde güçlü > zayıf {'✅' if a else '❌'} · b) fark {G.mean() - Z.mean():+.2f}R ({lo_:+.2f} … {hi_:+.2f}) "
               f"{'✅' if b else '❌'} -> {'✅ KABUL' if a and b else '❌ red'}")
    out.append("\nYan bilgi, 5 işlemli portföy (1.000.000 TL, senaryo D): mevcut sıra | RS güçlü önce | sadece RS güçlü")
    for ad, d0, d1 in (("2023-24", D1S, D2S - pd.Timedelta(days=1)), ("2025-26", D2S, pd.Timestamp("2100-01-01"))):
        fr = {k: v[v.index <= d1] for k, v in frames.items()}
        sg = [x for x in sig if d0 <= x["tarih"] <= d1]
        v0 = simule(fr, sg, d0, 1e6, ("Giriş", "Base"), **KW)[2]
        v1 = simule(fr, sg, d0, 1e6, ("Giriş", "Base"), sira="alan:rsg", **KW)[2]
        v2 = simule(fr, [x for x in sg if x["guclu"]], d0, 1e6, ("Giriş", "Base"), **KW)[2]
        f = lambda e: f"{e.iloc[-1]:,.0f} (düşüş %{(e / e.cummax() - 1).min() * 100:.0f})"  # noqa: E731
        out.append(f"  {ad}: {f(v0)} | {f(v1)} | {f(v2)}")
    txt = "\n".join(out)
    print(txt)
    if "--telegram" in sys.argv:
        telegram_send(txt[:3900])


if __name__ == "__main__":
    main()

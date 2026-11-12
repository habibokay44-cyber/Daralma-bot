"""Vur-kaç testi (12.11.2026): RS ZAYIF + piyasa ZAYIF iken gelen sinyallerde kısa çıkış, şimdiki Iz10'dan iyi mi?
Kullanıcı bu tür momentumsuz daralmaları kısa vadeli (vur-kaç) işliyor. Hiçbir ayarı değiştirmez.
Alt küme S: sinyal günü rs.olc guclu=False VE piyasa.genislik iyi=False (tanımlar önceden sabit).
Sinyaller: şimdiki Giriş + Base v0, 20 günlük hacim >= 10 milyon TL, ertesi açılış +%0.5 alış, çıkış açılış -%0.5.
Ölçü: portföy-eşdeğeri R (EFF). D1 = 2023-24, D2 = 2025-.
ÇIKIŞ VARYANTLARI (hedef fiyat görülünce o fiyattan, gap ile üstte açarsa açılıştan satış):
  E0 = şimdiki Iz10 (+1R'de stop girişe, sonra 10 mum dibi)
  K1 = tamamı +1R'de sat · K2 = tamamı +2R'de sat · K3 = yarısı +1R'de, kalan Iz10 (kullanıcının kötü piyasa kuralı)
ÖNCEDEN YAZILMIŞ KABUL (S içinde, üçü birden; İKİ ÖLÇÜ kuralı: tek işlem + portföy):
  a) iki dönemde de ort. R > E0
  b) tüm S'de eşli fark (varyant - E0) %90 güven aralığı (bootstrap 4000) sıfırın üstünde
  c) 5 işlemli portföy (senaryo D; varyant SADECE S sinyallerine uygulanır, diğerleri Iz10): iki dönemde de son değer E0'dan yüksek
Yan bilgi: aynı varyantlar S dışındaki sinyallerde (özgüllük kontrolü), S'nin payı.
Çalıştırma: python vurkac_test.py --telegram
"""
from __future__ import annotations

import sys

import numpy as np
import pandas as pd

import piyasa
import rs
from base_v0 import sinyaller as base_sinyaller
from fd_core import Params, run
from geriye_portfoy import ARM, TRAIL, simule
from scan import fetch_tv_all, get_tickers, telegram_send

D1S, D2S = pd.Timestamp("2023-01-02"), pd.Timestamp("2025-01-01")
KW = dict(mod="acilis", kayma=0.005, minhacim=1e7)
VAR = [("E0 Iz10", None), ("K1 tamamı +1R", (1.0, 1.0, "iz")), ("K2 tamamı +2R", (2.0, 1.0, "iz")),
       ("K3 yarısı +1R, kalan iz", (1.0, 0.5, "iz"))]


def islem(o, h, l, c, i, dip, km):
    if i + 2 >= len(c):
        return None
    g = o[i + 1] * 1.005
    R = g - dip
    if R <= 0:
        return None
    s, armed, kal, top = dip, False, 1.0, 0.0
    for k in range(i + 1, len(c) - 1):
        if km and kal == 1.0 and h[k] >= g + km[0] * R:
            px = max(o[k], g + km[0] * R) * 0.995
            top += km[1] * (px - g)
            kal = 1.0 - km[1]
            if kal <= 1e-9:
                return top / R * EFF(R / g)
        if c[k] < s:
            return (top + kal * (o[k + 1] * 0.995 - g)) / R * EFF(R / g)
        if not armed and h[k] >= g + ARM * R:
            armed, s = True, max(s, g)
        if armed and k > i + 1:
            s = max(s, float(l[max(i + 2, k - TRAIL + 1):k + 1].min()))
    return (top + kal * (c[-1] - g)) / R * EFF(R / g)


def EFF(sp):
    return sp * min(1.0 / sp, 20.0)


def ci(d, rng):
    d = np.asarray(d, float)
    b = [rng.choice(d, len(d)).mean() for _ in range(4000)]
    return np.percentile(b, 5), np.percentile(b, 95)


def main():
    frames = fetch_tv_all(get_tickers(), n_bars=1200, budget=25 * 60, min_bars=30)
    xu = fetch_tv_all(["XU100"], n_bars=1200, budget=120, min_bars=30).get("XU100")
    if xu is None:
        raise SystemExit("XU100 verisi alınamadı")
    xc = xu["Close"].astype(float)
    G = piyasa.genislik(frames)
    T, sig = [], []
    for s, df in frames.items():
        try:
            o, h, l, c = (df[k].to_numpy(float) for k in ("Open", "High", "Low", "Close"))
            hac = (df["Close"] * df["Volume"]).rolling(20).mean().to_numpy()
            ev = []
            if len(df) >= 120:
                ev += [("Giriş", e, e["sl"]) for e in run(df, Params()).events if e["type"] == "giris"]
            ev += [("Base", e, float(l[e["t"]])) for e in base_sinyaller(df)]
            for kay, e, dip in ev:
                if e["date"] < D1S:
                    continue
                i = int(e["t"])
                orr = rs.olc(df, xc, e["date"])
                rz = orr is not None and not orr["guclu"]
                pz = e["date"] in G.index and not bool(G.loc[e["date"], "iyi"])
                S = rz and pz
                sig.append(dict(sym=s, kaynak=kay, tarih=e["date"], i=i, kapanis=e["close"], dip=dip, piyasa=not S))
                if not (hac[i] >= 1e7):
                    continue
                r = {ad: islem(o, h, l, c, i, dip, km) for ad, km in VAR}
                if any(v is None for v in r.values()):
                    continue
                T.append(dict(d2=e["date"] >= D2S, S=S, rz=rz, pz=pz, **r))
        except Exception as ex:  # noqa: BLE001
            print(f"[uyarı] {s}: {ex}")
    T = pd.DataFrame(T)
    rng = np.random.default_rng(56)
    e0 = VAR[0][0]
    S = T[T.S]
    out = [f"🏃 Vur-kaç testi · {len(frames)} hisse · {len(T)} işlem · S (RS zayıf + piyasa zayıf) = {len(S)} "
           f"(%{100 * T.S.mean():.0f}; D1 {int((~S.d2).sum())}, D2 {int(S.d2.sum())})",
           f"Yan: RS zayıf %{100 * T.rz.mean():.0f} · piyasa zayıf %{100 * T.pz.mean():.0f}",
           "\nPortföy hesaplanıyor (varyant sadece S'ye)…"]
    port = {}
    for ad, km in VAR:
        res = []
        for d0, d1 in ((D1S, D2S - pd.Timedelta(days=1)), (D2S, pd.Timestamp("2100-01-01"))):
            fr = {k: v[v.index <= d1] for k, v in frames.items()}
            fr = {k: v for k, v in fr.items() if len(v) >= 30}
            sg = [x for x in sig if d0 <= x["tarih"] <= d1 and x["sym"] in fr]
            eg = simule(fr, sg, d0, 1e6, ("Giriş", "Base"), kismi={True: None, False: km}, **KW)[2]
            res.append((eg.iloc[-1], (eg / eg.cummax() - 1).min()))
        port[ad] = res
    out[-1] = "\nS İÇİNDE (D1 ort R · D2 ort R | portföy D1 · D2 son değer, en büyük düşüş)"
    for ad, _ in VAR:
        z = [S[S.d2 == d][ad].mean() for d in (False, True)]
        p = port[ad]
        st = (f"• {ad}: {z[0]:+.2f}R · {z[1]:+.2f}R | {p[0][0]:,.0f} (%{p[0][1] * 100:.0f}) · {p[1][0]:,.0f} (%{p[1][1] * 100:.0f})")
        if ad != e0:
            a = all(S[S.d2 == d][ad].mean() > S[S.d2 == d][e0].mean() for d in (False, True))
            fark = S[ad] - S[e0]
            lo, hi = ci(fark, rng) if len(S) >= 5 else (np.nan, np.nan)
            b = lo > 0
            cc = all(port[ad][k][0] > port[e0][k][0] for k in (0, 1))
            st += (f"\n    a) iki dönem ort R {'✅' if a else '❌'} · b) eşli fark {fark.mean():+.2f}R ({lo:+.2f} … {hi:+.2f}) "
                   f"{'✅' if b else '❌'} · c) portföy iki dönem {'✅' if cc else '❌'} -> {'✅ KABUL' if a and b and cc else '❌ red'}")
        out.append(st)
    D = T[~T.S]
    out.append(f"\nYan bilgi, S DIŞI (n={len(D)}; D1 · D2 ort R):")
    for ad, _ in VAR:
        out.append(f"• {ad}: {D[~D.d2][ad].mean():+.2f}R · {D[D.d2][ad].mean():+.2f}R")
    txt = "\n".join(out)
    print(txt)
    if "--telegram" in sys.argv:
        for j in range(0, len(txt), 3800):
            telegram_send(txt[j:j + 3800])


if __name__ == "__main__":
    main()

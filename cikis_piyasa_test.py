"""Çıkış kuralı ve piyasa filtresi testi, iki dönem (10.11.2026). Hiçbir ayarı değiştirmez.
Sinyaller: şimdiki gösterge (V3 dahil) Giriş + Base v0, 20 günlük hacim >= 10 milyon TL, alış ertesi açılış +%0.5,
satış çıkış sinyalinden sonraki açılış -%0.5. Tek tek işlemler (yer sınırı yok). D1 = 2023-24, D2 = 2025-bugün.

A) ÇIKIŞ (aynı işlemler, sadece çıkış değişir; E0 = şimdiki Iz10: +1R görünce stop girişe, sonra son 10 mumun dibi)
   E1 = iz 20 mum · E2 = stop girişe +2R'de çekilir · E3 = +1R'den sonra kapanış EMA21 altına inince çık
   ÖNCEDEN YAZILMIŞ KABUL (üçü birden): iki dönemde de (a) işlem başı ort. R, E0'dan yüksek; (b) yer-gün başına R
   (toplam R / toplam elde tutma mumu; 5 yer kısıtlı olduğu için) E0'dan yüksek; (c) tüm veride eşli fark (aynı işlem,
   varyant - E0) ortalamasının %90 güven aralığı sıfırın üstünde.
B) PİYASA FİLTRESİ (sinyal günü XU100'e bakılır, şart sağlanmıyorsa işlem açılmaz)
   M1 = XU100 kapanış > EMA50 · M2 = kapanış > EMA20 · M3 = EMA20 > EMA50
   ÖNCEDEN YAZILMIŞ KABUL (ikisi birden): (a) iki dönemde de kalan işlemlerin ort. R'si hepsinden yüksek; (b) tüm veride
   kalan - atılan ort. R farkının %90 güven aralığı sıfırın üstünde.
   Yan bilgi: 5 işlemli portföy benzetiminde (senaryo D, mevcut sıra) son değer ve en büyük düşüş.
Çalıştırma: python cikis_piyasa_test.py --telegram
"""
from __future__ import annotations

import sys

import numpy as np
import pandas as pd

from base_v0 import sinyaller as base_sinyaller
from fd_core import Params, run
from geriye_portfoy import simule
from scan import fetch_tv_all, get_tickers, telegram_send

D1S, D2S = pd.Timestamp("2023-01-02"), pd.Timestamp("2025-01-01")
CIKIS = [("E0 şimdiki (iz 10, +1R)", dict(trail=10, arm=1.0, ema=False)), ("E1 iz 20 mum", dict(trail=20, arm=1.0, ema=False)),
         ("E2 stop girişe +2R'de", dict(trail=10, arm=2.0, ema=False)), ("E3 EMA21 altı kapanış", dict(trail=10, arm=1.0, ema=True))]
PIYASA = [("M1 XU100 > EMA50", "m1"), ("M2 XU100 > EMA20", "m2"), ("M3 EMA20 > EMA50", "m3")]


def islem(o, h, l, c, e21, i, dip, trail, arm, ema):
    if i + 2 >= len(c):
        return None
    g = o[i + 1] * 1.005
    R = g - dip
    if R <= 0:
        return None
    s, armed = dip, False
    for k in range(i + 1, len(c) - 1):
        if c[k] < s or (ema and armed and c[k] < e21[k]):
            return (o[k + 1] * 0.995 - g) / R, k - i
        if not armed and h[k] >= g + arm * R:
            armed, s = True, max(s, g)
        if armed and not ema and k > i + 1:
            s = max(s, float(l[max(i + 2, k - trail + 1):k + 1].min()))
    return (c[-1] - g) / R, len(c) - 1 - i


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
    x20, x50 = xc.ewm(span=20, adjust=False).mean(), xc.ewm(span=50, adjust=False).mean()
    M = pd.DataFrame(dict(m1=xc > x50, m2=xc > x20, m3=x20 > x50))
    T, sig = [], []
    for s, df in frames.items():
        try:
            o, h, l, c = (df[k].to_numpy(float) for k in ("Open", "High", "Low", "Close"))
            e21 = df["Close"].ewm(span=21, adjust=False).mean().to_numpy(float)
            hac = (df["Close"] * df["Volume"]).rolling(20).mean().to_numpy()
            ev = []
            if len(df) >= 120:
                ev += [("Giriş", e, e["sl"]) for e in run(df, Params()).events if e["type"] == "giris"]
            ev += [("Base", e, float(l[e["t"]])) for e in base_sinyaller(df)]
            for kay, e, dip in ev:
                i = int(e["t"])
                if e["date"] < D1S:
                    continue
                m = M.reindex([e["date"]]).iloc[0] if e["date"] in M.index else None
                mk = {k: (bool(m[k]) if m is not None else True) for k in ("m1", "m2", "m3")}
                sig.append(dict(sym=s, kaynak=kay, tarih=e["date"], i=i, kapanis=e["close"], dip=dip, **mk))
                if not (hac[i] >= 1e7):
                    continue
                r = {ad: islem(o, h, l, c, e21, i, dip, **kw) for ad, kw in CIKIS}
                if any(v is None for v in r.values()):
                    continue
                row = dict(d2=e["date"] >= D2S, **mk)
                for ad, v in r.items():
                    row[ad + "|R"], row[ad + "|n"] = v
                T.append(row)
        except Exception as ex:  # noqa: BLE001
            print(f"[uyarı] {s}: {ex}")
    T = pd.DataFrame(T)
    rng = np.random.default_rng(56)
    out = [f"🚪 Çıkış ve piyasa filtresi testi · {len(frames)} hisse · {len(T)} işlem (Giriş + Base), iki dönem",
           "\nA) ÇIKIŞ KURALI (dönem: işlem başı ort. R · yer-gün başına R x100 · ort. elde tutma mumu)"]
    e0 = CIKIS[0][0]
    oz = {}
    for ad, _ in CIKIS:
        oz[ad] = [(D[ad + "|R"].mean(), 100 * D[ad + "|R"].sum() / D[ad + "|n"].sum(), D[ad + "|n"].mean()) for D in (T[~T.d2], T[T.d2])]
    for ad, _ in CIKIS:
        z = oz[ad]
        st = f"• {ad}: D1 {z[0][0]:+.2f}R · {z[0][1]:+.2f} · {z[0][2]:.0f} mum | D2 {z[1][0]:+.2f}R · {z[1][1]:+.2f} · {z[1][2]:.0f} mum"
        if ad != e0:
            a = all(z[k][0] > oz[e0][k][0] for k in (0, 1))
            b = all(z[k][1] > oz[e0][k][1] for k in (0, 1))
            lo, hi = ci(T[ad + "|R"] - T[e0 + "|R"], rng)
            st += (f"\n    a) ort. R {'✅' if a else '❌'} · b) yer-gün verimi {'✅' if b else '❌'} · c) eşli fark "
                   f"{(T[ad + '|R'] - T[e0 + '|R']).mean():+.2f}R ({lo:+.2f} … {hi:+.2f}) {'✅' if lo > 0 else '❌'} -> "
                   f"{'✅ KABUL' if a and b and lo > 0 else '❌ red'}")
        out.append(st)
    out.append("\nB) PİYASA FİLTRESİ (çıkış = şimdiki E0)")
    R0 = e0 + "|R"
    out.append(f"• filtresiz: D1 n={int((~T.d2).sum())} ort {T[~T.d2][R0].mean():+.2f}R | D2 n={int(T.d2.sum())} ort {T[T.d2][R0].mean():+.2f}R")
    port = {}
    for ad, k in [("filtresiz", None)] + PIYASA:
        res = []
        for d0, d1 in ((D1S, D2S - pd.Timedelta(days=1)), (D2S, pd.Timestamp("2100-01-01"))):
            fr = {s: df[df.index <= d1] for s, df in frames.items()}
            fr = {s: v for s, v in fr.items() if len(v) >= 30}
            sg = [x for x in sig if d0 <= x["tarih"] <= d1 and x["sym"] in fr and (k is None or x[k])]
            kap, ac_, eg, at = simule(fr, sg, d0, 1_000_000.0, ("Giriş", "Base"), mod="acilis", kayma=0.005, minhacim=1e7)
            res.append((eg.iloc[-1], (eg / eg.cummax() - 1).min(), len(kap)))
        port[ad] = res
    for ad, k in PIYASA:
        K, A_ = T[T[k]], T[~T[k]]
        a = all(K[K.d2 == d][R0].mean() > T[T.d2 == d][R0].mean() for d in (False, True))
        if len(A_) >= 5 and len(K) >= 5:
            b_ = [rng.choice(K[R0].to_numpy(), len(K)).mean() - rng.choice(A_[R0].to_numpy(), len(A_)).mean() for _ in range(4000)]
            lo, hi = np.percentile(b_, 5), np.percentile(b_, 95)
        else:
            lo = hi = np.nan
        out.append(f"• {ad}: D1 n={int((~K.d2).sum())} ort {K[~K.d2][R0].mean():+.2f}R | D2 n={int(K.d2.sum())} ort {K[K.d2][R0].mean():+.2f}R"
                   f" | atılan n={len(A_)} ort {A_[R0].mean():+.2f}R"
                   f"\n    a) iki dönemde yüksek {'✅' if a else '❌'} · b) kalan - atılan {K[R0].mean() - A_[R0].mean():+.2f}R ({lo:+.2f} … {hi:+.2f}) "
                   f"{'✅' if lo > 0 else '❌'} -> {'✅ KABUL' if a and lo > 0 else '❌ red'}")
    out.append("\nYan bilgi, 5 işlemli portföy (1.000.000 TL; son değer · en büyük düşüş · işlem):")
    for ad, res in port.items():
        out.append(f"• {ad}: D1 {res[0][0]:,.0f} · %{res[0][1] * 100:.0f} · {res[0][2]} | D2 {res[1][0]:,.0f} · %{res[1][1] * 100:.0f} · {res[1][2]}")
    txt = "\n".join(out)
    print(txt)
    if "--telegram" in sys.argv:
        for j in range(0, len(txt), 3800):
            telegram_send(txt[j:j + 3800])


if __name__ == "__main__":
    main()

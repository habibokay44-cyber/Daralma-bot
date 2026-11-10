"""RS sıralama testi (09.11.2026): 5 yer doluyken / aynı gün çok sinyal varken hangisi alınmalı?
Strateji tanımın "Stage 2 + yüksek RS" ama RS bugüne kadar sıralamada kullanılmadı. Geriye dönük testte binlerce sinyal
yer olmadığı için atlanıyor ve sonuç seçime göre çok değişiyor. Hiçbir gösterge ayarını değiştirmez.

RS60  = hissenin son 60 mumluk getirisi - XU100'ün aynı 60 mumluk getirisi (sinyal günü, puan). ANA ADAY.
RS120 = aynısı 120 mum (yan bilgi).
Kural parametresizdir (ayar aranmaz). Sağlamlık için iki AYRI dönem: D1 = 02.01.2023-31.12.2024, D2 = 01.01.2025-bugün.
Koşullar: senaryo D (ertesi gün açılıştan alım, %0.5 kayma, 20 günlük hacim >= 10 milyon TL), 5 işlem, %1 risk, 1.000.000 TL.
ÖNCEDEN YAZILMIŞ KABUL (ikisi birden, RS60 için):
  a) Portföy: her iki dönemde RS60 sıralamasının son değeri, 40 rastgele seçimin ÜST ÇEYREĞİNDE (>= 75. yüzdelik).
  b) Tek tek işlemler (yer sınırı yok, bütün sinyaller): her iki dönemde RS60'ı en yüksek üçte birin ort. R'si en düşük
     üçte birden yüksek.
Geçerse: sanal portföyde aynı gün sinyaller RS60'a göre sıralanır (yer doluyken satış yok, sadece seçim sırası).
Çalıştırma: python rs_test.py --telegram
"""
from __future__ import annotations

import sys

import numpy as np
import pandas as pd

from base_v0 import sinyaller as base_sinyaller
from fd_core import Params, run
from geriye_portfoy import ARM, TRAIL, simule
from scan import fetch_tv_all, get_tickers, telegram_send

SERMAYE, NRAST = 1_000_000.0, 40
KW = dict(mod="acilis", kayma=0.005, minhacim=1e7)
DONEM = [("D1 2023-24", pd.Timestamp("2023-01-02"), pd.Timestamp("2024-12-31")),
         ("D2 2025-26", pd.Timestamp("2025-01-01"), pd.Timestamp("2100-01-01"))]


def tek_R(df, i, dip):
    """Tek işlem (yer sınırı yok): ertesi açılış x1.005 alış, Iz10 kapanışla, sonraki açılış x0.995 satış."""
    o, h, l, c = (df[k].to_numpy(float) for k in ("Open", "High", "Low", "Close"))
    if i + 2 >= len(c):
        return None
    g = o[i + 1] * 1.005
    R = g - dip
    if R <= 0:
        return None
    s, armed = dip, False
    for k in range(i + 1, len(c) - 1):
        if c[k] < s:
            return (o[k + 1] * 0.995 - g) / R
        if not armed and h[k] >= g + ARM * R:
            armed, s = True, max(s, g)
        if armed and k > i + 1:
            s = max(s, float(l[max(i + 2, k - TRAIL + 1):k + 1].min()))
    return (c[-1] - g) / R


def tek_Reff(df, i, dip):
    """PORTFÖY-EŞDEĞERİ R (10.11.2026 düzeltmesi). tek_R'de stop çok yakınsa (ör. %0.5) küçük bir yükseliş +20R gibi görünür;
    oysa portföyde işlem büyüklüğü özsermayenin 1/5'i ile sınırlı olduğundan o kazanç gerçekleşmez (ortalamayı birkaç sahte
    dev işlem belirliyordu: +10R'de kırpınca ortalama +1.12R'den +0.03R'ye düşüyor). Burada büyüklük sanal portföy gibi:
    min(%1 risk / stop mesafesi, özsermayenin %20'si). Sonuç yine %1 risk biriminde: R_eff = getiri x min(1/stop%, 20).
    Stop mesafesi >= %5 ise tek_R ile aynıdır."""
    r = tek_R(df, i, dip)
    if r is None:
        return None
    g = float(df["Open"].iloc[i + 1]) * 1.005
    sp = (g - dip) / g
    return r * sp * min(1.0 / sp, 20.0)


def main():
    frames = fetch_tv_all(get_tickers(), n_bars=1200, budget=25 * 60, min_bars=30)
    xu = fetch_tv_all(["XU100"], n_bars=1200, budget=120, min_bars=30).get("XU100")
    if xu is None:
        raise SystemExit("XU100 verisi alınamadı")
    xc = xu["Close"].astype(float)
    sig = []
    for s, df in frames.items():
        try:
            c = df["Close"].to_numpy(float)
            x = xc.reindex(df.index).ffill().to_numpy(float)
            lo = df["Low"].to_numpy(float)
            hac = (df["Close"] * df["Volume"]).rolling(20).mean().to_numpy()

            def rs(i, n):
                return (c[i] / c[i - n] - 1) * 100 - (x[i] / x[i - n] - 1) * 100 if i >= n and x[i - n] > 0 else np.nan
            ev = []
            if len(df) >= 120:
                ev += [("Giriş", e, e["sl"]) for e in run(df, Params()).events if e["type"] == "giris"]
            ev += [("Base", e, float(lo[e["t"]])) for e in base_sinyaller(df)]
            for k, e, dip in ev:
                i = int(e["t"])
                sig.append(dict(sym=s, kaynak=k, tarih=e["date"], i=i, kapanis=e["close"], dip=dip, rs60=rs(i, 60),
                                rs120=rs(i, 120), tekR=tek_R(df, i, dip), hacim=hac[i]))
        except Exception as ex:  # noqa: BLE001
            print(f"[uyarı] {s}: {ex}")
    out = [f"🏁 RS sıralama testi · {len(frames)} hisse · {len(sig)} sinyal · senaryo D, 5 işlem, %1 risk, {SERMAYE:,.0f} TL",
           "Kabul (RS60): iki dönemde de portföy rastgelenin üst çeyreğinde VE yüksek RS'li işlemler düşük RS'liden iyi."]
    gec_a, gec_b = [], []
    for ad, d0, d1 in DONEM:
        fr = {k: df[df.index <= d1] for k, df in frames.items()}
        fr = {k: v for k, v in fr.items() if len(v) >= 30}
        sg = [s for s in sig if d0 <= s["tarih"] <= d1 and s["sym"] in fr]
        son = {}
        for etiket, sira in (("RS60", "alan:rs60"), ("RS120", "alan:rs120"), ("eski kural (önce Giriş, kısa stop)", "kural")):
            kap, ac_, eg, at = simule(fr, sg, d0, SERMAYE, ("Giriş", "Base"), sira=sira, **KW)
            R = np.array([t["R"] for t in kap]) if kap else np.array([0.0])
            son[etiket] = (eg.iloc[-1], (eg / eg.cummax() - 1).min(), len(kap), R.mean())
        rast = np.sort([simule(fr, sg, d0, SERMAYE, ("Giriş", "Base"), sira=t, **KW)[2].iloc[-1] for t in range(NRAST)])
        out.append(f"\n{ad} · {len(sg)} sinyal")
        out.append(f"  rastgele {NRAST} deneme: en kötü {rast[0]:,.0f} · alt çeyrek {np.percentile(rast, 25):,.0f} · medyan "
                   f"{np.median(rast):,.0f} · üst çeyrek {np.percentile(rast, 75):,.0f} · en iyi {rast[-1]:,.0f}")
        for etiket, (v, dd, n, rm) in son.items():
            yz = (rast < v).mean() * 100
            out.append(f"  {etiket}: {v:,.0f} TL (rastgelelerin %{yz:.0f}'inden iyi) · düşüş %{dd * 100:.0f} · {n} işlem · ort {rm:+.2f}R")
        gec_a.append(son["RS60"][0] >= np.percentile(rast, 75))
        T = pd.DataFrame([s for s in sg if s["tekR"] is not None and s["rs60"] == s["rs60"] and s["hacim"] >= 1e7])
        q = T.rs60.quantile([1 / 3, 2 / 3]).to_numpy()
        g = [T[T.rs60 < q[0]], T[(T.rs60 >= q[0]) & (T.rs60 < q[1])], T[T.rs60 >= q[1]]]
        out.append("  tek tek işlemler (RS60 üçte birleri): " + " | ".join(
            f"{a} n={len(x)} ort {x.tekR.mean():+.2f}R kazanma %{100 * (x.tekR > 0).mean():.0f}" for a, x in zip(("düşük", "orta", "yüksek"), g)))
        gec_b.append(g[2].tekR.mean() > g[0].tekR.mean())
    ok = all(gec_a) and all(gec_b)
    out.append(f"\na) portföy üst çeyrek: D1 {'✅' if gec_a[0] else '❌'} D2 {'✅' if gec_a[1] else '❌'} · "
               f"b) yüksek RS > düşük RS: D1 {'✅' if gec_b[0] else '❌'} D2 {'✅' if gec_b[1] else '❌'} -> {'✅ KABUL' if ok else '❌ red'}")
    txt = "\n".join(out)
    print(txt)
    if "--telegram" in sys.argv:
        telegram_send(txt[:3900])


if __name__ == "__main__":
    main()

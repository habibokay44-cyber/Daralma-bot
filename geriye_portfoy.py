"""Geriye dönük portföy testi (07.11.2026): sanal portföyün kurallarını geçmiş sinyallere uygular, sonucu TL olarak verir.
Kurallar portfoy.py ile aynı: işlem başı özsermayenin %1 riski, en fazla 5 açık işlem, işlem başı en fazla özsermayenin 1/5'i,
alış sinyal günü kapanışı, stop sinyal mumunun dibi, Iz10 çıkışı KAPANIŞLA, komisyon her yönde %0.1, aynı hissede tek işlem.
Aynı gün 5'ten fazla sinyal varsa önce Giriş, sonra Base, kendi içinde stop mesafesi küçük olan önce.
UYARILAR: (1) gösterge ayarları bu geçmiş üzerinde seçildi (örnek içi, iyimser), (2) bugün borsada olan hisseler (kotasyondan
çıkanlar yok), (3) kapanıştan alım varsayımı ve kayma (slippage) yok, (4) sığ hisselerde bu büyüklükte işlem gerçekçi olmayabilir.
Çalıştırma: python geriye_portfoy.py [başlangıç YYYY-AA-GG] [sermaye] --telegram
"""
from __future__ import annotations

import math
import sys

import numpy as np
import pandas as pd

from base_v0 import sinyaller as base_sinyaller
from fd_core import Params, run
from scan import fetch_tv_all, get_tickers, telegram_send

RISK, MAXPOZ, KOM, ARM, TRAIL = 0.01, 5, 0.001, 1.0, 10


def simule(frames, sig, bas, sermaye, kaynaklar):
    sig = [s for s in sig if s["kaynak"] in kaynaklar and s["tarih"] >= bas]
    gunler = sorted({d for df in frames.values() for d in df.index if d >= bas})
    by_day = {}
    for s in sig:
        by_day.setdefault(s["tarih"], []).append(s)
    nakit, acik, kapali, egri, atlanan = sermaye, [], [], [], 0
    idx = {k: {d: i for i, d in enumerate(df.index)} for k, df in frames.items()}
    arr = {k: (df["High"].to_numpy(float), df["Low"].to_numpy(float), df["Close"].to_numpy(float),
               (df["Close"] * df["Volume"]).rolling(20).mean().to_numpy()) for k, df in frames.items()}
    for d in gunler:
        kalan = []
        for a in acik:
            i = idx[a["sym"]].get(d)
            if i is None or i <= a["i0"]:
                kalan.append(a)
                continue
            h, l, c, _ = arr[a["sym"]]
            a["son"] = c[i]
            if c[i] < a["stop"]:
                net = a["lot"] * c[i] * (1 - KOM)
                nakit += net
                kapali.append(dict(a, cikis=c[i], cikis_tarihi=d, kz=net - a["maliyet"], R=(c[i] - a["giris"]) / a["R"]))
                continue
            if not a["armed"] and h[i] >= a["giris"] + ARM * a["R"]:
                a["armed"] = True
                a["stop"] = max(a["stop"], a["giris"])
            if a["armed"]:
                a["stop"] = max(a["stop"], float(l[max(a["i0"] + 1, i - TRAIL + 1):i + 1].min()))
            kalan.append(a)
        acik = kalan
        ozs = nakit + sum(a["lot"] * a["son"] for a in acik)
        bugun = sorted(by_day.get(d, []), key=lambda s: (s["kaynak"] != "Giriş", (s["kapanis"] - s["dip"]) / s["kapanis"]))
        for s in bugun:
            if any(a["sym"] == s["sym"] for a in acik):
                continue
            if len(acik) >= MAXPOZ:
                atlanan += 1
                continue
            R = s["kapanis"] - s["dip"]
            if R <= 0:
                continue
            lot = math.floor(min(ozs * RISK / R, ozs / MAXPOZ / s["kapanis"], nakit / (s["kapanis"] * (1 + KOM))))
            if lot <= 0:
                atlanan += 1
                continue
            maliyet = lot * s["kapanis"] * (1 + KOM)
            nakit -= maliyet
            hacim = arr[s["sym"]][3][s["i"]]
            acik.append(dict(sym=s["sym"], kaynak=s["kaynak"], tarih=d, i0=s["i"], giris=s["kapanis"], R=R, stop=s["dip"],
                             lot=lot, maliyet=maliyet, son=s["kapanis"], armed=False,
                             hacim_pay=(maliyet / hacim) if hacim and hacim > 0 else np.nan))
        egri.append((d, nakit + sum(a["lot"] * a["son"] for a in acik)))
    return kapali, acik, pd.Series(dict(egri)), atlanan


def rapor(ad, kapali, acik, egri, atlanan, sermaye, xu):
    son = egri.iloc[-1]
    yil = (egri.index[-1] - egri.index[0]).days / 365.25
    cagr = (son / sermaye) ** (1 / yil) - 1 if yil > 0 else np.nan
    dd = (egri / egri.cummax() - 1).min()
    R = np.array([t["R"] for t in kapali]) if kapali else np.array([0.0])
    kaz = (R > 0).mean() if kapali else 0
    pf = R[R > 0].sum() / -R[R <= 0].sum() if (R <= 0).any() else np.inf
    K = np.array([t["kz"] for t in kapali]) if kapali else np.array([0.0])
    pft = K[K > 0].sum() / -K[K <= 0].sum() if (K <= 0).any() else np.inf
    sig = [t for t in kapali if t["hacim_pay"] == t["hacim_pay"] and t["hacim_pay"] > 0.05]
    out = [f"\n📈 {ad}: {sermaye:,.0f} → {son:,.0f} TL ({(son / sermaye - 1) * 100:+.0f}%) | yıllık %{cagr * 100:.0f} | "
           f"en büyük düşüş %{dd * 100:.0f}",
           f"   {len(kapali)} kapanan işlem · kazanma %{kaz * 100:.0f} · ort {R.mean():+.2f}R · PF {pf:.2f} · "
           f"açık {len(acik)} · yer olmadığı için alınamayan {atlanan}",
           f"   sığlık uyarısı: {len(sig)} işlemde pozisyon, hissenin günlük ortalama işlem hacminin %5'inden büyük"]
    yillik = egri.resample("YE").last()
    onceki = sermaye
    parcalar = []
    for d, v in yillik.items():
        x = ""
        if xu is not None:
            xs = xu[(xu.index.year == d.year) & (xu.index >= egri.index[0])]
            if len(xs):
                x = f" (XU100 %{(xs.iloc[-1] / xs.iloc[0] - 1) * 100:+.0f})"
        parcalar.append(f"{d.year} %{(v / onceki - 1) * 100:+.0f}{x}")
        onceki = v
    out.append("   yıllar: " + " | ".join(parcalar))
    return out


def main():
    a = [x for x in sys.argv[1:] if not x.startswith("--")]
    bas = pd.Timestamp(a[0]) if a else pd.Timestamp("2023-01-02")
    sermaye = float(a[1]) if len(a) > 1 else 1_000_000.0
    frames = fetch_tv_all(get_tickers(), n_bars=1200, budget=25 * 60, min_bars=30)
    xu = fetch_tv_all(["XU100"], n_bars=1200, budget=120, min_bars=30).get("XU100")
    xu = xu["Close"].astype(float) if xu is not None else None
    sig = []
    for s, df in frames.items():
        try:
            if len(df) >= 120:
                for e in run(df, Params()).events:
                    if e["type"] == "giris":
                        sig.append(dict(sym=s, kaynak="Giriş", tarih=e["date"], i=int(e["t"]), kapanis=e["close"], dip=e["sl"]))
            lo = df["Low"].to_numpy(float)
            for e in base_sinyaller(df):
                sig.append(dict(sym=s, kaynak="Base", tarih=e["date"], i=int(e["t"]), kapanis=e["close"], dip=float(lo[e["t"]])))
        except Exception as ex:  # noqa: BLE001
            print(f"[uyarı] {s}: {ex}")
    out = [f"💰 Geriye dönük portföy testi · {bas:%d.%m.%Y}'den bugüne · {len(frames)} hisse · başlangıç {sermaye:,.0f} TL",
           "Kurallar sanal portföyle aynı (%1 risk, en fazla 5 işlem, kapanışla Iz10, %0.1 komisyon)."]
    if xu is not None:
        xs = xu[xu.index >= bas]
        out.append(f"Karşılaştırma: aynı dönemde XU100 al-tut %{(xs.iloc[-1] / xs.iloc[0] - 1) * 100:+.0f}")
    for ad, k in (("Giriş + Base", ("Giriş", "Base")), ("Sadece Giriş", ("Giriş",)), ("Sadece Base", ("Base",))):
        kap, ac, eg, at = simule(frames, sig, bas, sermaye, k)
        out += rapor(ad, kap, ac, eg, at, sermaye, xu)
    out.append("\n⚠️ İyimser tarafta: gösterge ayarları bu geçmişte seçildi; kotasyondan çıkan hisseler yok; kayma ve "
               "kapanış seansı riski yok. Gerçek beklenti bunun altında olmalı; doğrulama sanal portföyde.")
    txt = "\n".join(out)
    print(txt)
    if "--telegram" in sys.argv:
        telegram_send(txt[:3900])


if __name__ == "__main__":
    main()

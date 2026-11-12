"""Geriye dönük portföy testi (07.11.2026): sanal portföyün kurallarını geçmiş sinyallere uygular, sonucu TL olarak verir.
Kurallar portfoy.py ile aynı: işlem başı özsermayenin %1 riski, en fazla 5 açık işlem, işlem başı en fazla özsermayenin 1/5'i,
alış sinyal günü kapanışı, stop sinyal mumunun dibi, Iz10 çıkışı KAPANIŞLA, komisyon her yönde %0.1, aynı hissede tek işlem.
Aynı gün 5'ten fazla sinyal varsa önce Giriş, sonra Base, kendi içinde stop mesafesi küçük olan önce.
UYARILAR: (1) gösterge ayarları bu geçmiş üzerinde seçildi (örnek içi, iyimser), (2) bugün borsada olan hisseler (kotasyondan
çıkanlar yok), (3) kapanıştan alım varsayımı ve kayma (slippage) yok, (4) sığ hisselerde bu büyüklükte işlem gerçekçi olmayabilir.
R = işlemin TL kâr/zararı / girişteki özsermayenin %1'i (planlanan risk birimi).
Çalıştırma: python geriye_portfoy.py [başlangıç YYYY-AA-GG] [sermaye] --telegram
"""
from __future__ import annotations

import math
import random
import sys

import numpy as np
import pandas as pd

from base_v0 import sinyaller as base_sinyaller
from fd_core import Params, run
from scan import fetch_tv_all, get_tickers, telegram_send

RISK, MAXPOZ, KOM, ARM, TRAIL = 0.01, 5, 0.001, 1.0, 10


def simule(frames, sig, bas, sermaye, kaynaklar, mod="kapanis", kayma=0.0, minhacim=0.0, sira="kural", maxpoz=MAXPOZ, risk=RISK,
           kismi=None):
    """mod: 'kapanis' = sinyal günü kapanışından al / stop günü kapanışından sat;
            'acilis'  = ertesi işlem günü açılışından al / stop kapanışından sonraki gün açılıştan sat.
    kayma: alışta fiyat x(1+kayma), satışta x(1-kayma). minhacim: 20 günlük ort. TL hacmi bunun altındaysa alınmaz.
    sira: 'kural' (önce Giriş, sonra kısa stop) ya da tamsayı tohum (yer yoksa rastgele seçim).
    kismi: dict {True: (..), False: (..)} ise sinyalin 'piyasa' alanına göre (XU100 iyi / kötü) seçilir.
    kismi: (kR, oran, tur) FREE ROLL / kısmi satış (10.11.2026): fiyat girişin kR katı R üstünü görünce lotun 'oran'ı o fiyattan
           satılır (gap ile üstte açarsa açılıştan). tur='iz': kalan şimdiki Iz10 ile (stop +1R'de girişe), tur='sabit': kalan
           için stop girişe ÇEKİLMEZ (free roll: kalan stop olursa toplam ~0), 10 mumluk dipten izlemeye yine +1R'de başlar."""
    alan = sira[5:] if isinstance(sira, str) and sira.startswith("alan:") else None   # 'alan:rs60' = o alana göre büyükten küçüğe
    rnd = None if (sira == "kural" or alan) else random.Random(sira)
    sig = [s for s in sig if s["kaynak"] in kaynaklar and s["tarih"] >= bas]
    gunler = sorted({d for df in frames.values() for d in df.index if d >= bas})
    by_day = {}
    for s in sig:
        by_day.setdefault(s["tarih"], []).append(s)
    nakit, acik, kapali, egri, atlanan = sermaye, [], [], [], 0
    bekleyen = []      # açılışta alınacaklar (mod='acilis')
    idx = {k: {d: i for i, d in enumerate(df.index)} for k, df in frames.items()}
    arr = {k: (df["Open"].to_numpy(float), df["High"].to_numpy(float), df["Low"].to_numpy(float), df["Close"].to_numpy(float),
               (df["Close"] * df["Volume"]).rolling(20).mean().to_numpy()) for k, df in frames.items()}

    def kapat(a, px, d):
        nonlocal nakit
        px = px * (1 - kayma)
        net = a["lot"] * px * (1 - KOM)
        nakit += net
        kz = net - a["maliyet"] + a.get("kz_k", 0.0)
        kapali.append(dict(a, cikis=px, cikis_tarihi=d, kz=kz, R=kz / a["risk_tl"]))

    def ac(s, px, i, d, ozs):
        nonlocal nakit, atlanan
        px = px * (1 + kayma)
        R = px - s["dip"]
        if R <= 0:
            return
        lot = math.floor(min(ozs * risk / R, ozs / maxpoz / px, nakit / (px * (1 + KOM))))
        if lot <= 0:
            atlanan += 1
            return
        maliyet = lot * px * (1 + KOM)
        nakit -= maliyet
        hacim = arr[s["sym"]][4][s["i"]]
        kz_ = kismi.get(bool(s.get("piyasa", True))) if isinstance(kismi, dict) else kismi
        acik.append(dict(sym=s["sym"], kaynak=s["kaynak"], tarih=d, i0=i, giris=px, R=R, stop=s["dip"], lot=lot, kismi=kz_,
                         maliyet=maliyet, son=px, armed=False, cik=False, risk_tl=ozs * risk,
                         hacim_pay=(maliyet / hacim) if hacim and hacim > 0 else np.nan))

    for d in gunler:
        ozs = nakit + sum(a["lot"] * a["son"] for a in acik)
        # 1) açılış işlemleri: dünkü stop sinyallerinin satışı, dünkü sinyallerin alışı
        kalan = []
        for a in acik:
            i = idx[a["sym"]].get(d)
            if a["cik"] and i is not None:
                kapat(a, arr[a["sym"]][0][i], d)
            else:
                kalan.append(a)
        acik = kalan
        yeni = []
        for s in bekleyen:
            i = idx[s["sym"]].get(d)
            if i is None:
                yeni.append(s)          # hissede bugün işlem yok, bir sonraki mumu bekle
                continue
            if len(acik) < maxpoz and not any(a["sym"] == s["sym"] for a in acik):
                ac(s, arr[s["sym"]][0][i], i, d, ozs)
            else:
                atlanan += 1
        bekleyen = yeni
        # 2) gün sonu: stop kontrolü (kapanışla) ve iz süren stop
        kalan = []
        for a in acik:
            i = idx[a["sym"]].get(d)
            if i is None or i < a["i0"] or (mod == "kapanis" and i == a["i0"]):
                kalan.append(a)
                continue
            o, h, l, c, _ = arr[a["sym"]]
            a["son"] = c[i]
            km = a.get("kismi")
            if km and not a.get("k_done") and h[i] >= a["giris"] + km[0] * a["R"]:
                kpx = max(o[i], a["giris"] + km[0] * a["R"]) * (1 - kayma)
                q = math.floor(a["lot"] * km[1])
                if q > 0:
                    knet = q * kpx * (1 - KOM)
                    nakit += knet
                    mal = a["maliyet"] * q / a["lot"]
                    a["kz_k"] = a.get("kz_k", 0.0) + knet - mal
                    a["maliyet"] -= mal
                    a["lot"] -= q
                a["k_done"] = True
                if a["lot"] <= 0:          # 12.11: oran=1.0 -> hedefte tamamı satıldı, yer boşalır
                    kapali.append(dict(a, cikis=kpx, cikis_tarihi=d, kz=a["kz_k"], R=a["kz_k"] / a["risk_tl"]))
                    continue
            if c[i] < a["stop"]:
                if mod == "kapanis":
                    kapat(a, c[i], d)
                    continue
                a["cik"] = True
            if not a["armed"] and h[i] >= a["giris"] + ARM * a["R"]:
                a["armed"] = True
                if not (a.get("kismi") and a["kismi"][2] == "sabit"):
                    a["stop"] = max(a["stop"], a["giris"])
            if a["armed"] and i > a["i0"]:
                a["stop"] = max(a["stop"], float(l[max(a["i0"] + 1, i - TRAIL + 1):i + 1].min()))
            kalan.append(a)
        acik = kalan
        # 3) bugünün sinyalleri
        ozs = nakit + sum(a["lot"] * a["son"] for a in acik)
        bugun = [s for s in by_day.get(d, []) if not (minhacim and not (arr[s["sym"]][4][s["i"]] >= minhacim))]
        if alan:
            bugun.sort(key=lambda s: -(s.get(alan) if s.get(alan) == s.get(alan) and s.get(alan) is not None else -1e9))
        elif rnd is None:
            bugun.sort(key=lambda s: (s["kaynak"] != "Giriş", (s["kapanis"] - s["dip"]) / s["kapanis"]))
        else:
            rnd.shuffle(bugun)
        for s in bugun:
            if any(a["sym"] == s["sym"] for a in acik) or any(b["sym"] == s["sym"] for b in bekleyen):
                continue
            if len(acik) + (len(bekleyen) if mod == "acilis" else 0) >= maxpoz:
                atlanan += 1
                continue
            if mod == "kapanis":
                ac(s, s["kapanis"], s["i"], d, ozs)
            else:
                bekleyen.append(s)
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
    xr = 0.0
    if xu is not None:
        xs = xu[xu.index >= bas]
        xr = xs.iloc[-1] / xs.iloc[0] - 1
        out.append(f"Karşılaştırma: aynı dönemde XU100 al-tut %{(xs.iloc[-1] / xs.iloc[0] - 1) * 100:+.0f}")
    GB = ("Giriş", "Base")
    if "--dagilim" in sys.argv:   # 07.11.2026: işlem sayısı / risk varyantları, her biri 20 rastgele seçimle
        out.append("\nSenaryo D (açılıştan, %0.5 kayma, hacim >= 10 milyon TL), yer yokken rastgele seçim, 20 deneme:")
        for mp, rk in ((5, 0.01), (10, 0.01), (10, 0.005), (15, 0.005)):
            sonlar, dds, nis = [], [], []
            for tohum in range(20):
                kap, ac_, eg, at = simule(frames, sig, bas, sermaye, GB, mod="acilis", kayma=0.005, minhacim=1e7,
                                          sira=tohum, maxpoz=mp, risk=rk)
                sonlar.append(eg.iloc[-1])
                dds.append((eg / eg.cummax() - 1).min())
                nis.append(len(kap))
            so = np.sort(sonlar)
            out.append(f"• {mp} işlem, işlem başı risk %{rk * 100:.1f} (pozisyon en çok 1/{mp}): son değer en kötü {so[0]:,.0f} · "
                       f"medyan {np.median(so):,.0f} · en iyi {so[-1]:,.0f} TL | en büyük düşüş ort %{np.mean(dds) * 100:.0f}, "
                       f"en kötü %{min(dds) * 100:.0f} | ~{np.mean(nis):.0f} işlem | 20 denemenin {sum(x > sermaye for x in so)}'ü artıda, "
                       f"{sum(x > sermaye * (1 + xr) for x in so)}'i XU100'ü geçti")
        txt = "\n".join(out)
        print(txt)
        if "--telegram" in sys.argv:
            telegram_send(txt[:3900])
        return
    for ad, k, kw in (("A) Giriş + Base · kapanıştan (önceki test)", GB, {}),
                      ("B) Giriş + Base · ertesi gün açılıştan", GB, dict(mod="acilis")),
                      ("C) B + %0.5 kayma", GB, dict(mod="acilis", kayma=0.005)),
                      ("D) C + 20 günlük ort. hacim >= 10 milyon TL", GB, dict(mod="acilis", kayma=0.005, minhacim=1e7)),
                      ("D) sadece Giriş", ("Giriş",), dict(mod="acilis", kayma=0.005, minhacim=1e7)),
                      ("D) sadece Base", ("Base",), dict(mod="acilis", kayma=0.005, minhacim=1e7))):
        kap, ac_, eg, at = simule(frames, sig, bas, sermaye, k, **kw)
        out += rapor(ad, kap, ac_, eg, at, sermaye, xu)
    sonlar, dds = [], []
    for tohum in range(20):
        kap, ac_, eg, at = simule(frames, sig, bas, sermaye, GB, mod="acilis", kayma=0.005, minhacim=1e7, sira=tohum)
        sonlar.append(eg.iloc[-1])
        dds.append((eg / eg.cummax() - 1).min())
    sonlar = np.sort(sonlar)
    out.append(f"\n🎲 D senaryosu, yer yokken RASTGELE seçimle 20 deneme: son değer en kötü {sonlar[0]:,.0f} · "
               f"medyan {np.median(sonlar):,.0f} · en iyi {sonlar[-1]:,.0f} TL | en büyük düşüş ortalaması %{np.mean(dds) * 100:.0f}"
               f" (en kötü %{min(dds) * 100:.0f})")
    out.append("\n⚠️ İyimser tarafta: gösterge ayarları bu geçmişte seçildi; kotasyondan çıkan hisseler yok; kayma ve "
               "kapanış seansı riski yok. Gerçek beklenti bunun altında olmalı; doğrulama sanal portföyde.")
    txt = "\n".join(out)
    print(txt)
    if "--telegram" in sys.argv:
        telegram_send(txt[:3900])


if __name__ == "__main__":
    main()

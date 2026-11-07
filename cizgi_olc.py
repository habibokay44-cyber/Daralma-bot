"""Çizgi ölçümü (07.11.2026): senin yazdığın direnç seviyeleri ile göstergenin çizgisi ve yeni 'ilk mum tepesi' çizgisi.
Hiçbir ayarı değiştirmez. Senin tarifin (Örneklem 4 notları): yatay direnç, base'in İLK MUMUNUN TEPESİNDEN başlar;
sonraki mumların GÖVDELERİ çizginin üstüne çıkmaz (sadece fitiller geçebilir); sonra fitiller çizgiye değer (temas).
Yeni çizgi adayları (etiket günü t, geriye en çok 60 mum, aday mum k'nin tepesi L):
  geçerli = k'dan t'ye tüm gövde tepeleri <= L ve kapanış[t] <= L
  A: geçerli en eski k, en az 1 temas (fitil L'ye 0.3 ADR yakın)     B: aynı, en az 2 temas
  C: geçerli k'lar içinde en çok temas alan (eşitse en eski)
ÖNCEDEN YAZILMIŞ: en düşük medyan hatalı aday seçilir; KABUL için yatay 8 örneğin (DOGUB PRKAB MERKO ENKAI PLTUR TTRAK
ECOGR PAHOL) en az 6'sında göstergenin bugünkü çizgisinden senin seviyene DAHA YAKIN olmalı. Hata = |seviye - senin| / ADR.
Düşen çizgi örnekleri (VKING, IHYAY) sadece bilgi.
Çalıştırma: python cizgi_olc.py --telegram
"""
from __future__ import annotations

import sys

import numpy as np
import pandas as pd

import kayit
from scan import fetch_tv_all, telegram_send

YATAY = ["DOGUB", "PRKAB", "MERKO", "ENKAI", "PLTUR", "TTRAK", "ECOGR", "PAHOL"]
GERI, TOL = 60, 0.3


def adaylar(df, t):
    o, h, c = (df[k].to_numpy(float) for k in ("Open", "High", "Close"))
    A = (pd.Series(df["High"] / df["Low"]).rolling(20).mean().to_numpy() - 1)[t] * 100
    bt = np.maximum(o, c)
    gec = []
    for k in range(t - 1, max(0, t - GERI) - 1, -1):
        L = h[k]
        if c[t] > L or bt[k + 1:t + 1].max(initial=-np.inf) > L:
            continue
        tem = int(np.sum(h[k + 1:t + 1] >= L * (1 - TOL * A / 100)))
        gec.append((k, L, tem))
    out = {}
    for ad, n in (("A", 1), ("B", 2)):
        g = [x for x in gec if x[2] >= n]
        out[ad] = min(g, key=lambda x: x[0]) if g else None
    out["C"] = max(gec, key=lambda x: (x[2], -x[0])) if gec else None
    return out, A


def main():
    rows = [r for r in kayit.load() if str(r.get("mod", "")).startswith("Örneklem4")]
    frames = fetch_tv_all(sorted({r["hisse"] for r in rows}), n_bars=1100, budget=10 * 60)
    out = ["📐 Çizgi ölçümü: senin seviyen · göstergenin çizgisi · yeni 'ilk mum tepesi' çizgileri (hata ADR cinsinden)"]
    hata = {k: [] for k in ("eski", "A", "B", "C")}
    yakin = {k: 0 for k in ("A", "B", "C")}
    sabit = {k: [] for k in ("A", "B", "C")}
    for r in rows:
        df = frames.get(r["hisse"])
        if df is None:
            continue
        t = int(df.index.searchsorted(pd.Timestamp(r["etiket_tarihi"])))
        ad_, A = adaylar(df, t)
        c = float(df["Close"].iloc[t])
        birim = A / 100 * c
        eski = float(r["direnc"])
        sen = r.get("direnc_sen") or ""
        if sen and sen != "yok":
            s = float(sen)
            e0 = abs(eski - s) / birim
            satir = f"{r['hisse']} {r['etiket_tarihi'][2:]}: sen {s:.4g} | gösterge {eski:.4g} ({e0:.1f})"
            for k in ("A", "B", "C"):
                x = ad_[k]
                if x is None:
                    satir += f" | {k} yok"
                    continue
                e = abs(x[1] - s) / birim
                satir += f" | {k} {x[1]:.4g} ({e:.1f}, {df.index[x[0]]:%d.%m} mumu, {x[2]} temas)"
                if r["hisse"] in YATAY:
                    hata[k].append(e)
                    yakin[k] += e < e0
            if r["hisse"] in YATAY:
                hata["eski"].append(e0)
            out.append(("" if r["hisse"] in YATAY else "(düşen, bilgi) ") + satir)
        elif r.get("cizgi") != "y":   # çizgisine itiraz etmediğin etiketler: yeni çizgi eskisine ne kadar yakın
            for k in ("A", "B", "C"):
                x = ad_[k]
                sabit[k].append(abs(x[1] - eski) / birim if x else np.nan)
    out.append("\nÖzet (yatay 8 örnek):")
    out.append(f"  gösterge medyan hata {np.median(hata['eski']):.2f} ADR")
    for k in ("A", "B", "C"):
        if hata[k]:
            sb = np.array(sabit[k], float)
            out.append(f"  {k}: medyan hata {np.median(hata[k]):.2f} ADR · göstergeden daha yakın {yakin[k]}/{len(hata[k])} "
                       f"{'✅' if yakin[k] >= 6 else '❌'} | itiraz etmediğin {len(sb)} etikette eski çizgiye 0.5 ADR yakın "
                       f"{int(np.nansum(sb <= 0.5))}, yeni çizgi yok {int(np.isnan(sb).sum())}")
    txt = "\n".join(out)
    print(txt)
    if "--telegram" in sys.argv:
        telegram_send(txt[:3900])


if __name__ == "__main__":
    main()

"""Iz20 doğrulama (10.11.2026): çıkış testinde (portföy-eşdeğeri R, tek tek işlem) 'iz 20 mum' üç ölçütü de geçti.
Canlıya almadan önce İKİNCİ, bağımsız ölçü: 5 yerli portföy benzetimi (TL; yer kısıtı ve işlem büyüklüğü gerçek).
Senaryo D (ertesi açılış, %0.5 kayma, hacim >= 10 milyon TL), 1.000.000 TL, D1 = 2023-24, D2 = 2025-bugün.
ÖNCEDEN YAZILMIŞ DOĞRULAMA (ikisi birden, iki dönemde de):
  a) mevcut sıralamayla Iz20'nin son değeri >= Iz10
  b) 40 rastgele seçimde Iz20'nin medyan son değeri >= Iz10'un medyanı
Yan bilgi: en büyük düşüş, işlem sayısı. Geçerse: sanal portföy, takip ve Pine'da iz süresi 10 -> 20.
Çalıştırma: python iz20_dogrula.py --telegram
"""
from __future__ import annotations

import sys

import numpy as np
import pandas as pd

import geriye_portfoy as gp
from base_v0 import sinyaller as base_sinyaller
from fd_core import Params, run
from scan import fetch_tv_all, get_tickers, telegram_send

KW = dict(mod="acilis", kayma=0.005, minhacim=1e7)
DON = [("D1 2023-24", pd.Timestamp("2023-01-02"), pd.Timestamp("2024-12-31")), ("D2 2025-26", pd.Timestamp("2025-01-01"), pd.Timestamp("2100-01-01"))]


def main():
    frames = fetch_tv_all(get_tickers(), n_bars=1200, budget=25 * 60, min_bars=30)
    sig = []
    for s, df in frames.items():
        try:
            lo = df["Low"].to_numpy(float)
            if len(df) >= 120:
                sig += [dict(sym=s, kaynak="Giriş", tarih=e["date"], i=int(e["t"]), kapanis=e["close"], dip=e["sl"])
                        for e in run(df, Params()).events if e["type"] == "giris"]
            sig += [dict(sym=s, kaynak="Base", tarih=e["date"], i=int(e["t"]), kapanis=e["close"], dip=float(lo[e["t"]]))
                    for e in base_sinyaller(df)]
        except Exception as ex:  # noqa: BLE001
            print(f"[uyarı] {s}: {ex}")
    out = [f"🔁 Iz20 doğrulama (portföy benzetimi, TL) · {len(frames)} hisse · {len(sig)} sinyal"]
    ok = True
    for ad, d0, d1 in DON:
        fr = {k: v[v.index <= d1] for k, v in frames.items()}
        fr = {k: v for k, v in fr.items() if len(v) >= 30}
        sg = [x for x in sig if d0 <= x["tarih"] <= d1 and x["sym"] in fr]
        res = {}
        for tr in (10, 20):
            gp.TRAIL = tr
            kap, ac_, eg, at = gp.simule(fr, sg, d0, 1e6, ("Giriş", "Base"), **KW)
            rast, dds = [], []
            for t in range(40):
                e2 = gp.simule(fr, sg, d0, 1e6, ("Giriş", "Base"), sira=t, **KW)[2]
                rast.append(e2.iloc[-1])
                dds.append((e2 / e2.cummax() - 1).min())
            res[tr] = (eg.iloc[-1], (eg / eg.cummax() - 1).min(), len(kap), np.median(rast), np.percentile(rast, 25), np.mean(dds))
        gp.TRAIL = 10
        a, b = res[20][0] >= res[10][0], res[20][3] >= res[10][3]
        ok = ok and a and b
        out.append(f"\n{ad}")
        for tr in (10, 20):
            v = res[tr]
            out.append(f"  Iz{tr}: mevcut sıra {v[0]:,.0f} TL (düşüş %{v[1] * 100:.0f}, {v[2]} işlem) · rastgele medyan {v[3]:,.0f} · "
                       f"alt çeyrek {v[4]:,.0f} · ort. düşüş %{v[5] * 100:.0f}")
        out.append(f"  a) mevcut sıra {'✅' if a else '❌'} · b) rastgele medyan {'✅' if b else '❌'}")
    out.append(f"\n-> {'✅ DOĞRULANDI: iz süresi 20 mum yapılabilir' if ok else '❌ doğrulanmadı: Iz10 kalır'}")
    txt = "\n".join(out)
    print(txt)
    if "--telegram" in sys.argv:
        telegram_send(txt[:3900])


if __name__ == "__main__":
    main()

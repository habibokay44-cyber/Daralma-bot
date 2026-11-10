"""Free roll 2: kullanıcının piyasaya göre değişen kısmi satışı (10.11.2026). Hiçbir ayarı değiştirmez.
Kullanıcı: "piyasa iyiyse +3R'de 1/4, normalde +2R'de 1/3, kötüyse +1R'de 1/2". Piyasa = sinyal günü XU100 kapanışı EMA50 üstünde mi.
  F4 = +3R'de 1/4 (her zaman) · F5 = piyasa iyi: +3R'de 1/4, kötü: +1R'de 1/2 · F6 = piyasa iyi: +2R'de 1/3, kötü: +1R'de 1/2
Kabul ölçütü ilk testle AYNI (aşağıda). İlk testteki E0 / F1-F3 de karşılaştırma için tekrar çalışır.
---- ilk test açıklaması ----
Free roll (riski sıfırlama, kısmi satış) testi (10.11.2026). Hiçbir ayarı değiştirmez.
Kullanıcının yöntemi: fiyat 2R'ye gelince 1/3, ya da 1R'ye gelince 1/2 satılır; kalan stop olsa bile toplam ~0 (risk sıfırlanır).
Varyantlar (hepsi aynı sinyaller: şimdiki Giriş + Base v0, senaryo D: ertesi açılış, %0.5 kayma, hacim >= 10 milyon TL):
  E0 = şimdiki Iz10 (kısmi satış yok; +1R'de stop girişe, sonra 10 mumun dibi)
  F1 = +1R'de 1/2 sat, kalan Iz10
  F2 = +2R'de 1/3 sat, kalan Iz10
  F3 = +1R'de 1/2 sat, kalan için stop girişe ÇEKİLMEZ (saf free roll), 10 mumun dibini izler
Ölçü: 5 işlemli portföy benzetimi (TL, mevcut sıra, %1 risk, 1.000.000 TL), iki dönem (2023-24, 2025-).
ÖNCEDEN YAZILMIŞ KABUL (bir varyant için):
  iki dönemde de son değer >= E0   VEYA   (iki dönemde de en büyük düşüş E0'dan küçük VE son değer >= E0'ın %90'ı)
Yan bilgi: kazanma oranı, başa baş ya da kârla kapanan işlem oranı (R >= 0), ort. R, 40 rastgele seçimin medyanı.
Çalıştırma: python freeroll_test.py --telegram
"""
from __future__ import annotations

import sys

import numpy as np
import pandas as pd

from base_v0 import sinyaller as base_sinyaller
from fd_core import Params, run
from geriye_portfoy import simule
from scan import fetch_tv_all, get_tickers, telegram_send

KW = dict(mod="acilis", kayma=0.005, minhacim=1e7)
VAR = [("E0 şimdiki Iz10", None), ("F1 +1R'de 1/2 sat", (1.0, 0.5, "iz")), ("F2 +2R'de 1/3 sat", (2.0, 1 / 3, "iz")),
       ("F3 +1R'de 1/2 sat, stop girişe çekilmez", (1.0, 0.5, "sabit")), ("F4 +3R'de 1/4 sat", (3.0, 0.25, "iz")),
       ("F5 piyasa iyi +3R 1/4, kötü +1R 1/2", {True: (3.0, 0.25, "iz"), False: (1.0, 0.5, "iz")}),
       ("F6 piyasa iyi +2R 1/3, kötü +1R 1/2", {True: (2.0, 1 / 3, "iz"), False: (1.0, 0.5, "iz")})]
DON = [("2023-24", pd.Timestamp("2023-01-02"), pd.Timestamp("2024-12-31")), ("2025-26", pd.Timestamp("2025-01-01"), pd.Timestamp("2100-01-01"))]


def main():
    frames = fetch_tv_all(get_tickers(), n_bars=1200, budget=25 * 60, min_bars=30)
    xu = fetch_tv_all(["XU100"], n_bars=1200, budget=120, min_bars=30).get("XU100")
    xc = xu["Close"].astype(float)
    iyi = xc > xc.ewm(span=50, adjust=False).mean()
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
    for x in sig:
        x["piyasa"] = bool(iyi.get(x["tarih"], True))
    out = [f"🎯 Free roll testi 2 (piyasaya göre) · piyasa iyi günlerde sinyal %{100 * np.mean([x['piyasa'] for x in sig]):.0f} · {len(frames)} hisse · {len(sig)} sinyal · 5 işlem, %1 risk, 1.000.000 TL, senaryo D"]
    res = {}
    for ad, d0, d1 in DON:
        fr = {k: v[v.index <= d1] for k, v in frames.items()}
        fr = {k: v for k, v in fr.items() if len(v) >= 30}
        sg = [x for x in sig if d0 <= x["tarih"] <= d1 and x["sym"] in fr]
        out.append(f"\n{ad}")
        for vad, k in VAR:
            kap, ac_, eg, _ = simule(fr, sg, d0, 1e6, ("Giriş", "Base"), kismi=k, **KW)
            R = np.array([t["R"] for t in kap]) if kap else np.array([0.0])
            rast = [simule(fr, sg, d0, 1e6, ("Giriş", "Base"), kismi=k, sira=t, **KW)[2].iloc[-1] for t in range(12)]
            dd = (eg / eg.cummax() - 1).min()
            res.setdefault(vad, []).append((eg.iloc[-1], dd))
            out.append(f"  {vad}: {eg.iloc[-1]:,.0f} TL · düşüş %{dd * 100:.0f} · {len(kap)} işlem · kazanma %{100 * (R > 0.05).mean():.0f} · "
                       f"zararsız (R >= -0.05) %{100 * (R >= -0.05).mean():.0f} · ort {R.mean():+.2f}R · rastgele medyan {np.median(rast):,.0f}")
    e0 = res[VAR[0][0]]
    out.append("")
    for vad, _ in VAR[1:]:
        v = res[vad]
        a = all(v[i][0] >= e0[i][0] for i in (0, 1))
        b = all(v[i][1] > e0[i][1] for i in (0, 1)) and all(v[i][0] >= 0.9 * e0[i][0] for i in (0, 1))
        out.append(f"{vad}: getiri iki dönemde >= E0 {'✅' if a else '❌'} · daha az düşüş ve getiri >= %90 {'✅' if b else '❌'} -> "
                   f"{'✅ KABUL' if a or b else '❌ red'}")
    txt = "\n".join(out)
    print(txt)
    if "--telegram" in sys.argv:
        telegram_send(txt[:3900])


if __name__ == "__main__":
    main()

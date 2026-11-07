"""Çizgi ayarları testi (07.11.2026), Örneklem 4 işaretleriyle. Hiçbir ayarı değiştirmez.
Örneklem 4'te Giriş gelen 22 etiketin 8'ine 'almazdım' dedin, 7'sinde sebep çizgi. Notlarındaki 3 kalıp ve karşılığı:
  V1 gövde toleransı 0: çizgi gövdelerin içinden geçmesin (bodyADR 0.1 -> 0, bodyADRD 0.05 -> 0)
  V2 yatay tercihi: geçerli yatay seviye varsa düşen çizgi yerine yatay (hPrefer 0 -> 3)
  V3 fitil taşma payı: fitiller çizgiyi en çok 0.5 ADR aşabilsin (wickADR 2.5 -> 0.5)
  V4 üçü birden
ÖNCEDEN YAZILMIŞ KABUL (hepsi):
  a) 'kötü Giriş' (Giriş geldi, almazdım, çizgi yanlış; 7 adet): en az 5'inde ya Giriş kalkar ya da çizgi %1'den fazla değişir
  b) 'iyi Giriş' (Giriş geldi, alırdım/başka gün; 14 adet): en az 12'sinde aynı Giriş (±2 mum) korunur
  c) kalibrasyonda doğru etiket sayısı düşmez (ayrı 'Kalibrasyon' çalışmasında)
Örneklem 4 bu kuralların kaynağı olduğu için geçen ayar ayrıca yeni örneklem ya da canlı sinyalle doğrulanır.
Çalıştırma: python cizgi_test.py --telegram
"""
from __future__ import annotations

import sys
from dataclasses import replace

import pandas as pd

import kayit
from fd_core import Params, run
from scan import fetch_tv_all, telegram_send

VARS = [("V1 gövde toleransı 0", dict(bodyADR=0.0, bodyADRD=0.0)),
        ("V2 yatay tercihi", dict(hPrefer=3)),
        ("V3 fitil taşma 0.5 ADR", dict(wickADR=0.5)),
        ("V4 üçü birden", dict(bodyADR=0.0, bodyADRD=0.0, hPrefer=3, wickADR=0.5))]


def bul(res, d, tol=3):
    ev = [e for e in res.events if e["type"] == "setup" and abs((e["date"] - d).days) <= tol]
    if not ev:
        return None, None
    e = min(ev, key=lambda x: abs((x["date"] - d).days))
    gi = [x for x in res.events if x["type"] == "giris" and x.get("setup_date") == e["date"]]
    return e, (gi[0] if gi else None)


def main():
    rows = [r for r in kayit.load() if str(r.get("mod", "")).startswith("Örneklem4") and r.get("isaret") in ("a", "g", "h")]
    frames = fetch_tv_all(sorted({r["hisse"] for r in rows}), n_bars=1100, budget=10 * 60)
    kotu = [r for r in rows if r.get("giris_tarihi") and r["isaret"] == "h" and r.get("cizgi") == "y"]
    iyi = [r for r in rows if r.get("giris_tarihi") and r["isaret"] in ("a", "g")]
    out = [f"📐 Çizgi ayarları testi (Örneklem 4: {len(kotu)} kötü Giriş, {len(iyi)} iyi Giriş)",
           "Kabul: kötülerin >= 5'inde Giriş kalkar ya da çizgi değişir VE iyilerin >= 12'si korunur (+ kalibrasyon)"]
    for ad, kw in VARS:
        P = replace(Params(), **kw)
        ko, ik, det = 0, 0, []
        for r in kotu + iyi:
            df = frames.get(r["hisse"])
            if df is None:
                continue
            d = pd.Timestamp(r["etiket_tarihi"])
            e0, g0 = bul(run(df, Params()), d, 0)
            e1, g1 = bul(run(df, P), d)
            if r in kotu:
                degis = (g1 is None) or e1 is None or (e0 is not None and abs(e1["line"] / e0["line"] - 1) > 0.01)
                ko += degis
                det.append(f"{r['hisse']}{'✓' if degis else '✗'}")
            else:
                kor = g0 is not None and g1 is not None and abs((g1["date"] - g0["date"]).days) <= 3
                ik += kor
                if not kor:
                    det.append(f"{r['hisse']}(iyi kayboldu)")
        ok = ko >= 5 and ik >= 12
        out.append(f"\n• {ad}: kötü {ko}/{len(kotu)} değişti/kalktı · iyi {ik}/{len(iyi)} korundu -> {'✅' if ok else '❌'}")
        out.append("   " + " ".join(det))
    txt = "\n".join(out)
    print(txt)
    if "--telegram" in sys.argv:
        telegram_send(txt[:3900])


if __name__ == "__main__":
    main()

"""Giriş yatay kırılım testi (07.11.2026), Örneklem 4 işaretleriyle. Hiçbir ayarı değiştirmez.
Çizgi ölçümü: göstergenin seviyesi senin seviyene zaten yakın (medyan 0.64 ADR); sorun çizginin ŞEKLİ (düşen / gövde içinden)
ve Giriş'in düşen çizgi kırılınca gelmesi, oysa sen yatay tepenin kırılmasını bekliyorsun (PRKAB notu).
  GY1: Giriş için kapanış, son 10 mumun en yüksek GÖVDE tepesini de geçmeli
  GY2: aynı, FİTİL tepesi
ÖNCEDEN YAZILMIŞ KABUL (hepsi):
  a) kötü Giriş (Giriş geldi, almazdım, çizgi yanlış; 7): en az 5'inde o Giriş (±3 gün) kalkar
  b) iyi Giriş (Giriş geldi, alırdım/başka gün; 14): en az 12'sinde Giriş ±3 gün içinde kalır
  c) kalibrasyonda doğru etiket sayısı düşmez (Giriş şartı etiketleri etkilememeli), PF düşmez
Bilgi: almazdım dediğin ama çizgi itirazı olmayan Giriş'ler (BYDNR) ve Giriş'in kaç gün kaydığı.
Çalıştırma: python giris_yatay_test.py --telegram
"""
from __future__ import annotations

import sys
from dataclasses import replace

import pandas as pd

import kayit
from fd_core import Params, run
from scan import fetch_tv_all, telegram_send

VARS = [("GY1 gövde tepesi (10 mum)", dict(girisYatayN=10)),
        ("GY2 fitil tepesi (10 mum)", dict(girisYatayN=10, girisYatayFitil=True))]


def giris(res, d):
    ev = [e for e in res.events if e["type"] == "setup" and e["date"] == d]
    if not ev:
        return None
    g = [x for x in res.events if x["type"] == "giris" and x.get("setup_date") == ev[0]["date"]]
    return g[0]["date"] if g else None


def main():
    rows = [r for r in kayit.load() if str(r.get("mod", "")).startswith("Örneklem4") and r.get("giris_tarihi")]
    frames = fetch_tv_all(sorted({r["hisse"] for r in rows}), n_bars=1100, budget=10 * 60)
    kotu = [r for r in rows if r["isaret"] == "h" and r.get("cizgi") == "y"]
    iyi = [r for r in rows if r["isaret"] in ("a", "g")]
    diger = [r for r in rows if r["isaret"] == "h" and r.get("cizgi") != "y"]
    out = [f"🚪 Giriş yatay kırılım testi (Örneklem 4: {len(kotu)} kötü, {len(iyi)} iyi Giriş)",
           "Kabul: kötülerin >= 5'i kalkar VE iyilerin >= 12'si kalır (+ kalibrasyon)"]
    for ad, kw in VARS:
        P = replace(Params(), **kw)
        ko = ik = 0
        det = []
        for r in kotu + iyi + diger:
            df = frames.get(r["hisse"])
            if df is None:
                continue
            d = pd.Timestamp(r["etiket_tarihi"])
            g0, g1 = giris(run(df, Params()), d), giris(run(df, P), d)
            kaldi = g0 is not None and g1 is not None and abs((g1 - g0).days) <= 3
            kay = "" if g1 is None or g0 is None or kaldi else f"→{g1:%d.%m}"
            if r in kotu:
                ko += not kaldi
                det.append(f"{r['hisse']}{'✓' if not kaldi else '✗'}{kay}")
            elif r in iyi:
                ik += kaldi
                if not kaldi:
                    det.append(f"{r['hisse']}(iyi {'kalktı' if g1 is None else 'kaydı ' + kay})")
            else:
                det.append(f"{r['hisse']}(h, çizgi itirazı yok: {'kalktı' if not kaldi else 'kaldı'})")
        ok = ko >= 5 and ik >= 12
        out.append(f"\n• {ad}: kötü {ko}/{len(kotu)} kalktı · iyi {ik}/{len(iyi)} kaldı -> {'✅' if ok else '❌'}")
        out.append("   " + " ".join(det))
    txt = "\n".join(out)
    print(txt)
    if "--telegram" in sys.argv:
        telegram_send(txt[:3900])


if __name__ == "__main__":
    main()

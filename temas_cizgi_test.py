"""(07.11.2026 ikinci deneme) TEMAS ÇİZGİSİ testi. İlk deneme: Giriş yatay kırılım testi (07.11.2026), Örneklem 4 işaretleriyle. Hiçbir ayarı değiştirmez.
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

# TEMAS ÇİZGİSİ (VKING / IHYAY notu): son N mumda en çok tepeye değen, gövdesi üstünde kapanmayan çizgi (eğim serbest).
# Giriş için kapanış bu çizginin de üstünde olmalı. Kabul ölçütü aynı + VKING temmuz başı Giriş kalır, IHYAY temmuz iğnesi kalkar.
VARS = [("TM1 en çok temas eden çizgi (150 mum)", dict(girisTemasN=150)),
        ("TM2 en çok temas eden çizgi (250 mum)", dict(girisTemasN=250))]
EK = ["VKING", "IHYAY"]


def giris(res, d):
    ev = [e for e in res.events if e["type"] == "setup" and e["date"] == d]
    if not ev:
        return None
    g = [x for x in res.events if x["type"] == "giris" and x.get("setup_date") == ev[0]["date"]]
    return g[0]["date"] if g else None


def main():
    rows = [r for r in kayit.load() if str(r.get("mod", "")).startswith("Örneklem4") and r.get("giris_tarihi")]
    frames = fetch_tv_all(sorted({r["hisse"] for r in rows} | set(EK)), n_bars=1100, budget=10 * 60)
    kotu = [r for r in rows if r["isaret"] == "h" and r.get("cizgi") == "y"]
    iyi = [r for r in rows if r["isaret"] in ("a", "g")]
    diger = [r for r in rows if r["isaret"] == "h" and r.get("cizgi") != "y"]
    out = [f"📏 Temas çizgisi testi kırılım testi (Örneklem 4: {len(kotu)} kötü, {len(iyi)} iyi Giriş)",
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
        for sym in EK:   # senin doğru çizdiğin iki grafik: haziran-temmuz 2026 Giriş'leri
            df = frames.get(sym)
            if df is None:
                out.append(f"   {sym}: veri yok")
                continue
            a, b = pd.Timestamp("2026-06-01"), pd.Timestamp("2026-07-31")
            def gl(res):
                return [e["date"] for e in res.events if e["type"] == "giris" and a <= e["date"] <= b]
            r1 = run(df, P)
            g1 = gl(r1)
            info = []
            for d in g1:
                t = int(df.index.get_loc(d))
                from fd_core import _temas_cizgi
                v, tc, i0, j0 = _temas_cizgi(r1.S, t, P)
                info.append(f"{d:%d.%m} (çizgi {v:.4g}, {tc} temas, {df.index[i0]:%d.%m.%y}'den)" if i0 >= 0 else f"{d:%d.%m} (çizgi yok)")
            out.append(f"   {sym}: şimdiki Giriş {', '.join(f'{d:%d.%m}' for d in gl(run(df, Params()))) or 'yok'}"
                       f" -> bu kural {', '.join(info) or 'yok'}")
    txt = "\n".join(out)
    print(txt)
    if "--telegram" in sys.argv:
        telegram_send(txt[:3900])


if __name__ == "__main__":
    main()

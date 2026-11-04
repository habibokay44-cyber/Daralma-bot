"""Order block (SMC) direnç testi: kör işaretlenmiş etiketlerde, etiketin direnci bir satış order block'una denk
geliyorsa isabet yükseliyor mu? Hiçbir ayarı değiştirmez. Tek dosya.

Veriler: state/orneklem.csv (eski gösterge, 39 etiket) ve state/orneklem3.csv (kümelenme kutusu, 39 kutu).
Seviye: orneklem.csv'de 'direnc', orneklem3.csv'de 'direnc' (kutu tepesi).

ÖNCEDEN YAZILMIŞ TANIM (05.11.2026):
  Satış order block'u: etiket gününden önceki 120 mum içinde (en geç 6 mum önce) bir YÜKSELEN mum (kapanış > açılış);
  ardından en fazla 5 mumda kapanış, o mumun tepesinden en az 3 ADR aşağı inmiş VE o mumdan önceki 10 mumun en düşük
  dibinin altına inmiş (yapı kırılımı). Bölge = o mumun dibi..tepesi.
  Bölge geçerli: düşüşten etiket gününe kadar hiçbir kapanış bölgenin tepesinin üstünde değil.
  Kural: seviye, bir geçerli bölgenin içinde ya da en fazla 0.5 ADR altında (en fazla 0.25 ADR üstünde).
ÖNCEDEN YAZILMIŞ ŞART: iki örneklem birlikte, kuralı sağlayan (tutulan) en az 12 etiket VE bunlarda isabet >= %65.
Not: bu örneklemler daha önce kullanıldı; geçen bir kural ileri testte doğrulanmadan göstergeye girmez.
Çalıştırma: python ob_test.py --telegram
"""
from __future__ import annotations

import csv
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

from scan import fetch_tv_all, telegram_send

HERE = Path(__file__).resolve().parent
SETS = [("Eski gösterge (orneklem.csv)", HERE / "state" / "orneklem.csv", 1, 5, 6),
        ("Kümelenme kutusu (orneklem3.csv)", HERE / "state" / "orneklem3.csv", 1, 5, 6)]
# (ad, dosya, hisse sütunu, seviye sütunu, işaret sütunu); tarih sütunu: orneklem 2, orneklem3 3
DATECOL = {"orneklem.csv": 2, "orneklem3.csv": 3}


def read(path, sc, lc, ic):
    out = []
    if not path.exists():
        return out
    with path.open(encoding="utf-8") as fh:
        rd = csv.reader(fh)
        next(rd, None)
        for r in rd:
            if len(r) > ic and r[ic].strip().lower() in ("d", "y"):
                try:
                    out.append(dict(sym=r[sc].strip(), date=pd.Timestamp(r[DATECOL[path.name]]),
                                    lvl=float(r[lc]), ok=r[ic].strip().lower() == "d"))
                except ValueError:
                    pass
    return out


def ob_zones(df, t):
    o, h, l, c = (df[k].to_numpy(float) for k in ("Open", "High", "Low", "Close"))
    adr = (pd.Series(h / l).rolling(20).mean().to_numpy() - 1) * 100
    zones = []
    for i in range(max(10, t - 120), t - 5):
        if not c[i] > o[i] or not adr[i] == adr[i]:
            continue
        w = c[i + 1:min(i + 6, t)]
        if len(w) == 0:
            continue
        drop = (h[i] - w.min()) / h[i] * 100
        if drop < 3 * adr[i] or not w.min() < l[i - 10:i].min():
            continue
        j = i + 1 + int(np.argmin(w))
        if (c[j:t + 1] > h[i]).any():
            continue
        zones.append((float(l[i]), float(h[i]), df.index[i]))
    return zones, float(adr[t])


def main():
    data = [(name, read(p, sc, lc, ic)) for name, p, sc, lc, ic in SETS]
    syms = sorted({r["sym"] for _, rows in data for r in rows})
    frames = fetch_tv_all(syms, n_bars=900, budget=10 * 60)
    for _ in range(2):
        miss = [s for s in syms if s not in frames]
        if not miss:
            break
        time.sleep(3)
        frames.update(fetch_tv_all(miss, n_bars=900, budget=3 * 60))
    out = ["🧱 Order block direnç testi (kör işaretli etiketler)"]
    tot_k = tot_kd = 0
    for name, rows in data:
        kept, drop, miss = [], [], []
        for r in rows:
            df = frames.get(r["sym"])
            if df is None:
                miss.append(r["sym"])
                continue
            t = int(df.index.searchsorted(r["date"]))
            if t >= len(df) or abs((df.index[t] - r["date"]).days) > 3:
                miss.append(f"{r['sym']}(tarih)")
                continue
            zs, a = ob_zones(df, t)
            px = r["lvl"]
            hit = [z for z in zs if z[0] - 0.5 * a / 100 * px <= px <= z[1] + 0.25 * a / 100 * px]
            (kept if hit else drop).append((r, hit[0] if hit else None))
        kd = sum(1 for r, _ in kept if r["ok"])
        dd = sum(1 for r, _ in drop if r["ok"])
        tot_k += len(kept)
        tot_kd += kd
        out.append(f"\n{name}:")
        out.append(f"  order block altında: {len(kept)} etiket, {kd} doğru (%{100 * kd / len(kept) if kept else 0:.0f})")
        out.append(f"  order block yok:     {len(drop)} etiket, {dd} doğru (%{100 * dd / len(drop) if drop else 0:.0f})")
        if kept:
            out.append("  tutulanlar: " + ", ".join(f"{r['sym']}({'d' if r['ok'] else 'y'}, OB {z[2]:%d.%m.%y})" for r, z in kept))
        if miss:
            out.append("  eşleşmeyen: " + ", ".join(miss))
    ok = tot_k >= 12 and tot_kd / tot_k >= 0.65 if tot_k else False
    out.append(f"\nToplam tutulan {tot_k}, isabet %{100 * tot_kd / tot_k if tot_k else 0:.0f}. "
               f"Şart (en az 12, ≥%65): {'✅ geçti, ileri testte doğrulanacak' if ok else '❌ geçmedi'}")
    txt = "\n".join(out)
    print(txt)
    if "--telegram" in sys.argv:
        telegram_send(txt[:3900])


if __name__ == "__main__":
    main()

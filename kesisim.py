"""Kesişim ölçümü: kutu örneklemindeki (state/orneklem2.csv) kutuların yanında ESKİ göstergenin etiketi var mı,
varsa isabet ne ve eski etiket kutunun açılmasından kaç gün sonra geliyor. Hiçbir ayarı değiştirmez.

ÖNCEDEN YAZILMIŞ KURAL (04.11.2026):
  Kutunun yaşadığı süre içinde ya da bittikten sonraki 3 gün içinde eski göstergenin canlı etiketi varsa 'ortak' sayılır.
  En az 10 ortak kutu VE ortaklarda isabet >= %75 ise birleşim kurulur
  (eski etiket aynen kalır, bildirime yeni dedektörün kutusu eklenir), sonra ileri testte doğrulanır.
Not: işaretlerken eski gösterge açıktı; bu ölçüm o yüzden kısmen taraflıdır.
Çalıştırma: python kesisim.py --telegram
"""
from __future__ import annotations

import csv
import sys
import time
from dataclasses import replace
from pathlib import Path

import pandas as pd

from calibrate import CAND
from fd_core import Params, run
from kutu_orneklem import P as KP_FROZEN
from kutu_yeni import detect
from scan import fetch_tv_all, telegram_send

F = Path(__file__).resolve().parent / "state" / "orneklem2.csv"
D = pd.Timedelta


def read2():
    out = []
    with F.open(encoding="utf-8") as fh:
        rd = csv.reader(fh)
        next(rd, None)
        for r in rd:
            if len(r) < 7:
                continue
            out.append(dict(sym=r[1].strip(), start=pd.Timestamp(r[2]), label=pd.Timestamp(r[3]), isr=r[6].strip().lower()))
    return out


def main():
    rows = [r for r in read2() if r["isr"] in ("d", "y")]
    syms = sorted({r["sym"] for r in rows})
    frames = fetch_tv_all(syms, n_bars=700, budget=10 * 60)
    for _ in range(2):
        miss = [s for s in syms if s not in frames]
        if not miss:
            break
        time.sleep(3)
        frames.update(fetch_tv_all(miss, n_bars=700, budget=3 * 60))
    Pold = replace(Params(), **CAND)
    ortak, yalniz, lags, eks = [], [], [], []
    for r in rows:
        df = frames.get(r["sym"])
        if df is None:
            eks.append(r["sym"])
            continue
        bx = [b for b in detect(df, KP_FROZEN) if b["label_d"] == r["label"]]
        if not bx:
            eks.append(f"{r['sym']}(kutu bulunamadı)")
            continue
        b = bx[0]
        last = df.index[min(b.get("break_t", b.get("stop_t", b["end_t"])), len(df) - 1)]
        old = [e for e in run(df, Pold).events if e["type"] == "setup" and not e.get("cancelled")
               and r["start"] <= e["date"] <= last + D(days=3)]
        if old:
            ortak.append(r)
            lags.append((old[0]["date"] - r["label"]).days)
        else:
            yalniz.append(r)

    def acc(lst):
        d = sum(1 for x in lst if x["isr"] == "d")
        return d, len(lst), (100 * d / len(lst) if lst else 0)

    od, on, op = acc(ortak)
    yd, yn, yp = acc(yalniz)
    ok = on >= 10 and op >= 75
    lg = sorted(lags)
    med = lg[len(lg) // 2] if lg else 0
    out = ["🔗 Kesişim ölçümü (kutu örneklemi, eski göstergeyle)",
           f"Yanında eski etiket OLAN kutular: {od}/{on} doğru (%{op:.0f})",
           f"Yanında eski etiket OLMAYAN kutular: {yd}/{yn} doğru (%{yp:.0f})",
           f"Eski etiket, kutunun açılmasından kaç takvim günü sonra: medyan {med}, hepsi {lg}",
           f"Ortak kutular: " + ", ".join(f"{x['sym']}({x['isr']})" for x in ortak),
           ("Eşleşmeyen: " + ", ".join(eks)) if eks else "",
           f"Kural (en az 10 ortak, isabet ≥%75): {'✅ birleşim kurulabilir, ileri testte doğrulanacak' if ok else '❌ tutmadı, konu kapanır'}",
           "Not: işaretlerken eski gösterge açıktı, bu ölçüm kısmen taraflı."]
    txt = "\n".join(x for x in out if x)
    print(txt)
    if "--telegram" in sys.argv:
        telegram_send(txt[:3900])


if __name__ == "__main__":
    main()

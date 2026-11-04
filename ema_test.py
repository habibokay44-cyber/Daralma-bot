"""EMA yönü ölçümü: rastgele örneklemde (state/orneklem.csv) eski göstergenin etiket gününde EMA10/EMA21 yönü
düşerken çıkan yanlış etiketleri ayırıyor mu? Hiçbir ayarı değiştirmez. Tek dosya, başka deneme dosyasına bağlı değil.

ÖNCEDEN YAZILMIŞ KURALLAR (04.11.2026). Kural tutuyorsa o etiket 'elenirdi':
  E1: EMA10 ya da EMA21, 5 mumda %0.5'ten fazla düşmüş
  E2: EMA10, 5 mumda yükselmemiş (<= %0)
KABUL (üçü birden): a) elenenlerde yanlış oranı >= 2 x kalanlar  b) yanlışların >= %30'u elenir  c) doğruların <= %40'ı elenir
Not: bu örneklem daha önce çok kez kullanıldı; geçen bir kural ancak ileri testte doğrulanırsa göstergeye girer.
Çalıştırma: python ema_test.py --telegram
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
from scan import fetch_tv_all, telegram_send

F = Path(__file__).resolve().parent / "state" / "orneklem.csv"


def marks():
    out = []
    with F.open(encoding="utf-8") as fh:
        rd = csv.reader(fh)
        next(rd, None)
        for r in rd:
            if len(r) >= 8 and r[6].strip().lower() in ("d", "y"):
                out.append(dict(sym=r[1].strip(), date=pd.Timestamp(r[2]), ok=r[6].strip().lower() == "d"))
    return out


def auc(pos, neg):
    if not pos or not neg:
        return float("nan")
    return sum((p > n) + 0.5 * (p == n) for p in pos for n in neg) / (len(pos) * len(neg))


def judge(rows, name, key):
    good = [r for r in rows if r["ok"]]
    bad = [r for r in rows if not r["ok"]]
    fl = [r for r in rows if r[key]]
    un = [r for r in rows if not r[key]]
    if not fl or not un:
        return f"• {name}: elenen {len(fl)}, kalan {len(un)} -> ölçülemez"
    wf = sum(1 for r in fl if not r["ok"])
    wu = sum(1 for r in un if not r["ok"])
    rf, ru = wf / len(fl), wu / len(un)
    a_ = (ru == 0 and rf > 0) or (ru > 0 and rf >= 2 * ru)
    pb, pg = wf / max(len(bad), 1), (len(fl) - wf) / max(len(good), 1)
    b_, c_ = pb >= 0.30, pg <= 0.40
    return (f"• {name}: elenen {len(fl)} (yanlış %{100 * rf:.0f}), kalan {len(un)} (yanlış %{100 * ru:.0f}) | "
            f"yanlışların %{100 * pb:.0f}'i, doğruların %{100 * pg:.0f}'i elenir | "
            f"a{'✓' if a_ else '✗'} b{'✓' if b_ else '✗'} c{'✓' if c_ else '✗'} -> {'✅ KABUL' if a_ and b_ and c_ else '❌ red'}")


def main():
    mk = marks()
    syms = sorted({m["sym"] for m in mk})
    frames = fetch_tv_all(syms, n_bars=700, budget=10 * 60)
    for _ in range(2):
        miss = [s for s in syms if s not in frames]
        if not miss:
            break
        time.sleep(3)
        frames.update(fetch_tv_all(miss, n_bars=700, budget=3 * 60))
    P = replace(Params(), **CAND)
    rows, eks = [], []
    for m in mk:
        df = frames.get(m["sym"])
        if df is None:
            eks.append(m["sym"])
            continue
        ev = [e for e in run(df, P).events if e["type"] == "setup" and not e.get("cancelled")
              and abs((e["date"] - m["date"]).days) <= 3]
        if not ev:
            eks.append(f"{m['sym']}(etiket yok)")
            continue
        t = min(ev, key=lambda e: abs((e["date"] - m["date"]).days))["t"]
        c = df["Close"]
        e10 = c.ewm(span=10, adjust=False).mean().to_numpy()
        e21 = c.ewm(span=21, adjust=False).mean().to_numpy()
        d10 = (e10[t] / e10[t - 5] - 1) * 100
        d21 = (e21[t] / e21[t - 5] - 1) * 100
        rows.append(dict(sym=m["sym"], ok=m["ok"], d10=d10, d21=d21,
                         E1=(d10 <= -0.5 or d21 <= -0.5), E2=(d10 <= 0)))
    good = [r for r in rows if r["ok"]]
    bad = [r for r in rows if not r["ok"]]
    out = [f"📈 EMA yönü ölçümü: {len(rows)} etiket (doğru {len(good)}, yanlış {len(bad)})",
           judge(rows, "E1 EMA10/21 %0.5'ten fazla düşmüş", "E1"),
           judge(rows, "E2 EMA10 yükselmemiş", "E2"),
           f"Bilgi AUC (yanlışta daha düşük EMA değişimi = >0.5): EMA10 {auc([-r['d10'] for r in bad], [-r['d10'] for r in good]):.2f}, "
           f"EMA21 {auc([-r['d21'] for r in bad], [-r['d21'] for r in good]):.2f}",
           "Yanlışlar: " + ", ".join(f"{r['sym']}(10:{r['d10']:+.1f} 21:{r['d21']:+.1f})" for r in bad),
           "Doğrular: " + ", ".join(f"{r['sym']}(10:{r['d10']:+.1f} 21:{r['d21']:+.1f})" for r in good)]
    if eks:
        out.append("Eşleşmeyen: " + ", ".join(eks))
    txt = "\n".join(out)
    print(txt)
    if "--telegram" in sys.argv:
        telegram_send(txt[:3900])


if __name__ == "__main__":
    main()

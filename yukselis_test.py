"""Önceki yükseliş testi ('bayrak direği'): daralmadan önce belirgin bir yükseliş olan etiketlerde isabet yüksek mi?
Hiçbir ayarı değiştirmez. Tek dosya. Kör işaretli veriler: state/orneklem.csv (eski gösterge) ve state/orneklem3.csv
(kümelenme kutusu). Seviye = 'direnc' sütunu (eski gösterge çizgisi / kutu tepesi).

ÖNCEDEN YAZILMIŞ TANIMLAR (05.11.2026). Etiket gününden geriye 40 mumun en düşük dibinden seviyeye yükseliş:
  Y1: en az %15
  Y2: en az 5 ADR (etiket günündeki ADR)
Yükseliş yoksa etiket 'elenirdi'.
KABUL (iki örneklem birlikte, üçü birden): a) elenenlerde yanlış oranı >= 2 x kalanlar
  b) yanlışların >= %30'u elenir  c) doğruların <= %40'ı elenir
Bilgi: senin 4 örneğin (KAPLM, DCTTR x2, ENTRA) bu tanımları sağlıyor mu.
Not: bu örneklemler daha önce kullanıldı; geçen kural ileri testte doğrulanmadan göstergeye girmez.
Çalıştırma: python yukselis_test.py --telegram
"""
from __future__ import annotations

import csv
import sys
import time
from pathlib import Path

import pandas as pd

from scan import fetch_tv_all, telegram_send

HERE = Path(__file__).resolve().parent
FILES = [(HERE / "state" / "orneklem.csv", 2), (HERE / "state" / "orneklem3.csv", 3)]  # (dosya, tarih sütunu)
ORNEK = [("KAPLM", "2026-03-30"), ("DCTTR", "2025-01-06"), ("DCTTR", "2025-03-28"), ("ENTRA", "2026-10-27")]
GERI = 40


def read():
    out = []
    for p, dc in FILES:
        if not p.exists():
            continue
        with p.open(encoding="utf-8") as fh:
            rd = csv.reader(fh)
            next(rd, None)
            for r in rd:
                if len(r) > 6 and r[6].strip().lower() in ("d", "y"):
                    try:
                        out.append(dict(src=p.name, sym=r[1].strip(), date=pd.Timestamp(r[dc]), lvl=float(r[5]),
                                        ok=r[6].strip().lower() == "d"))
                    except ValueError:
                        pass
    return out


def rise(df, date, lvl=None):
    t = int(df.index.searchsorted(pd.Timestamp(date)))
    if t >= len(df) or t < GERI:
        return None
    h, l = df["High"].to_numpy(float), df["Low"].to_numpy(float)
    adr = (pd.Series(h / l).rolling(20).mean().to_numpy() - 1) * 100
    lv = lvl if lvl is not None else h[max(0, t - 4):t + 1].max()
    lo = l[t - GERI:t + 1].min()
    pct = (lv / lo - 1) * 100
    return pct, pct / adr[t] if adr[t] == adr[t] and adr[t] > 0 else 0.0


def judge(rows, name, key):
    good = [r for r in rows if r["ok"]]
    bad = [r for r in rows if not r["ok"]]
    el = [r for r in rows if not r[key]]
    ka = [r for r in rows if r[key]]
    if not el or not ka:
        return f"• {name}: elenen {len(el)}, kalan {len(ka)} -> ölçülemez"
    we = sum(1 for r in el if not r["ok"])
    wk = sum(1 for r in ka if not r["ok"])
    re_, rk = we / len(el), wk / len(ka)
    a_ = (rk == 0 and re_ > 0) or (rk > 0 and re_ >= 2 * rk)
    pb, pg = we / max(len(bad), 1), (len(el) - we) / max(len(good), 1)
    b_, c_ = pb >= 0.30, pg <= 0.40
    kd = len(ka) - wk
    return (f"• {name}: kalan {len(ka)} (isabet %{100 * kd / len(ka):.0f}), elenen {len(el)} (isabet %{100 * (len(el) - we) / len(el):.0f}) | "
            f"yanlışların %{100 * pb:.0f}'i, doğruların %{100 * pg:.0f}'i elenir | "
            f"a{'✓' if a_ else '✗'} b{'✓' if b_ else '✗'} c{'✓' if c_ else '✗'} -> {'✅ KABUL' if a_ and b_ and c_ else '❌ red'}")


def main():
    rows = read()
    syms = sorted({r["sym"] for r in rows} | {s for s, _ in ORNEK})
    frames = fetch_tv_all(syms, n_bars=900, budget=10 * 60)
    for _ in range(2):
        miss = [s for s in syms if s not in frames]
        if not miss:
            break
        time.sleep(3)
        frames.update(fetch_tv_all(miss, n_bars=900, budget=3 * 60))
    use, eks = [], []
    for r in rows:
        df = frames.get(r["sym"])
        x = rise(df, r["date"], r["lvl"]) if df is not None else None
        if x is None:
            eks.append(r["sym"])
            continue
        r["pct"], r["adrx"] = x
        r["Y1"], r["Y2"] = x[0] >= 15, x[1] >= 5
        use.append(r)
    out = [f"📈 Önceki yükseliş testi: {len(use)} kör işaretli etiket (doğru {sum(r['ok'] for r in use)})",
           judge(use, "Y1 40 mumda ≥%15 yükseliş", "Y1"),
           judge(use, "Y2 40 mumda ≥5 ADR yükseliş", "Y2")]
    for src in ("orneklem.csv", "orneklem3.csv"):
        sub = [r for r in use if r["src"] == src]
        if sub:
            out.append(f"  bilgi {src}: " + judge(sub, "Y1", "Y1")[2:60] + " | " + judge(sub, "Y2", "Y2")[2:60])
    ex = []
    for s, d in ORNEK:
        df = frames.get(s)
        x = rise(df, d) if df is not None else None
        ex.append(f"{s} {d[5:]}: " + (f"%{x[0]:.0f} / {x[1]:.1f} ADR" if x else "veri yok"))
    out.append("Senin örneklerin (bilgi): " + "; ".join(ex))
    bad = [r for r in use if not r["ok"]]
    out.append("Yanlışlar (% / ADR): " + ", ".join(f"{r['sym']}({r['pct']:.0f}/{r['adrx']:.1f})" for r in bad))
    out.append("Doğrular (% / ADR): " + ", ".join(f"{r['sym']}({r['pct']:.0f}/{r['adrx']:.1f})" for r in use if r["ok"]))
    if eks:
        out.append("Eşleşmeyen: " + ", ".join(eks))
    txt = "\n".join(out)
    print(txt)
    if "--telegram" in sys.argv:
        for i in range(0, len(txt), 3500):
            telegram_send(txt[i:i + 3500])
            time.sleep(1)


if __name__ == "__main__":
    main()

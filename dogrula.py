"""Bağımsız doğrulama: kalibrasyonda umut veren ölçüleri rastgele örneklemde (state/orneklem.csv) sınar.
Hiçbir ayarı değiştirmez, sadece ölçüp Telegram'a yazar.

ÖNCEDEN YAZILMIŞ KURALLAR (03.11.2026, örneklem sonucu görüldü ama bu ölçüler örneklemde hiç hesaplanmadı):
  V1 lc >= 3   : son 5 adımda en az 3 kapanış bir öncekinin altında
  V2 kr >= 3   : son 5 mumun en az 3'ü kırmızı
  V3 gir <= -2 : kümeye düşüşle gelinmiş, (C[t-5]/C[t-15]-1)/ADR
KABUL (üçü birden): a) uyarılılarda yanlış oranı >= 2 x uyarısızlar
                    b) yanlışların >= %30'u uyarılı   c) doğruların <= %40'ı uyarılı
'b' (belirsiz) işaretliler sayılmaz. 'pine yok' notlu satırlar ayrıca hariç tutularak da raporlanır.
Çalıştırma: python dogrula.py --telegram
"""
from __future__ import annotations

import csv
import sys
import time
from dataclasses import replace
from pathlib import Path

import pandas as pd

import uyari_olc as U1
import uyari_olc2 as U2
from calibrate import CAND
from fd_core import Params, run
from scan import fetch_tv_all, telegram_send

F = Path(__file__).resolve().parent / "state" / "orneklem.csv"

RULES = {
    "V1 lc>=3": lambda f: f["lc"] >= 3,
    "V2 kr>=3": lambda f: f["kr"] >= 3,
    "V3 gir<=-2": lambda f: f["gir"] == f["gir"] and f["gir"] <= -2.0,
}
INFO = ["lc", "kr", "gir", "mx", "mb", "h7", "b7", "e50", "ed", "es", "dd", "adr", "rg", "vr", "bas", "kp"]


def read_marks():
    """Virgül hatalarına dayanıklı okuma: ilk 8 alan sabit, kalanı not."""
    out = []
    with F.open(encoding="utf-8") as fh:
        rd = csv.reader(fh)
        next(rd, None)
        for r in rd:
            if len(r) < 8:
                continue
            isr = r[6].strip().lower()
            czg = r[7].strip().lower()
            note = ",".join(r[8:]).lower()
            out.append(dict(no=r[0], sym=r[1].strip(), date=pd.Timestamp(r[2]), mode=r[3], isr=isr, czg=czg,
                            pine_yok="pine yok" in note))
    return out


def collect(frames, marks):
    P = replace(Params(), **CAND)
    rows, miss = [], []
    for m in marks:
        if m["isr"] not in ("d", "y"):
            continue
        df = frames.get(m["sym"])
        if df is None:
            miss.append(f"{m['sym']}(veri yok)")
            continue
        res = run(df, P)
        ev = [e for e in res.events if e["type"] == "setup" and not e.get("cancelled")
              and abs((e["date"] - m["date"]).days) <= 3]
        if not ev:
            miss.append(f"{m['sym']}(etiket bulunamadı)")
            continue
        e = min(ev, key=lambda x: abs((x["date"] - m["date"]).days))
        if e["t"] < 25:
            miss.append(f"{m['sym']}(kısa geçmiş)")
            continue
        f = U1.feats(df, res, e)
        f.update(U2.feats(df, res, e))
        f.update(ok=m["isr"] == "d", tag=m["sym"], mode=e["mode"], pine_yok=m["pine_yok"])
        rows.append(f)
    return rows, miss


def judge(rows, name, rule):
    good = [r for r in rows if r["ok"]]
    bad = [r for r in rows if not r["ok"]]
    fl = [r for r in rows if rule(r)]
    un = [r for r in rows if not rule(r)]
    if not fl or not un:
        return f"• {name}: uyarılı {len(fl)}, uyarısız {len(un)} -> ölçülemez"
    wf = sum(1 for r in fl if not r["ok"])
    wu = sum(1 for r in un if not r["ok"])
    rf, ru = wf / len(fl), wu / len(un)
    a_ = (ru == 0 and rf > 0) or (ru > 0 and rf >= 2 * ru)
    pb, pg = wf / max(len(bad), 1), (len(fl) - wf) / max(len(good), 1)
    b_, c_ = pb >= 0.30, pg <= 0.40
    return (f"• {name}: uyarılı {len(fl)} (yanlış %{100 * rf:.0f}), uyarısız {len(un)} (yanlış %{100 * ru:.0f}) | "
            f"yanlışların %{100 * pb:.0f}'i, doğruların %{100 * pg:.0f}'i uyarılı | "
            f"a{'✓' if a_ else '✗'} b{'✓' if b_ else '✗'} c{'✓' if c_ else '✗'} -> {'✅ KABUL' if a_ and b_ and c_ else '❌ red'}")


def report(rows, miss):
    good = [r for r in rows if r["ok"]]
    bad = [r for r in rows if not r["ok"]]
    out = [f"🔬 Bağımsız doğrulama (rastgele örneklem): {len(rows)} etiket (doğru {len(good)}, yanlış {len(bad)})"]
    if miss:
        out.append("Eşleşmeyen: " + ", ".join(miss))
    out.append("\nKurallar (önceden yazılı):")
    out += [judge(rows, n, r) for n, r in RULES.items()]
    py = [r for r in rows if not r["pine_yok"]]
    if len(py) < len(rows):
        out.append(f"\n'pine yok' satırları hariç ({len(py)} etiket):")
        out += [judge(py, n, r) for n, r in RULES.items()]
    out.append("\nModa göre isabet: " + " | ".join(
        f"{m} {sum(1 for r in rows if r['mode'] == m and r['ok'])}/{sum(1 for r in rows if r['mode'] == m)}"
        for m in sorted({r['mode'] for r in rows})))
    out.append(f"\nBilgi için AUC (yanlış-yüksek >0.5). {len(INFO)} ölçü bakıldı, 0.70 altını yok say:")
    aucs = []
    for k in INFO:
        pb = [r[k] for r in bad if r[k] == r[k]]
        pg = [r[k] for r in good if r[k] == r[k]]
        aucs.append((U1.auc(pb, pg), k))
    out.append(" ".join(f"{k} {v:.2f}" for v, k in sorted(aucs, reverse=True)))
    out.append("\nYanlışlar: " + ", ".join(f"{r['tag']}(lc{r['lc']} kr{r['kr']} gir{r['gir']:+.1f})" for r in bad))
    out.append("Doğrular: " + ", ".join(f"{r['tag']}(lc{r['lc']} kr{r['kr']} gir{r['gir']:+.1f})" for r in good))
    return "\n".join(out)


def main():
    if not F.exists():
        print("state/orneklem.csv yok")
        return
    marks = read_marks()
    syms = sorted({m["sym"] for m in marks})
    frames = fetch_tv_all(syms, n_bars=700, budget=10 * 60)
    for _ in range(2):
        miss = [s for s in syms if s not in frames]
        if not miss:
            break
        time.sleep(3)
        frames.update(fetch_tv_all(miss, n_bars=700, budget=3 * 60))
    txt = report(*collect(frames, marks))
    print(txt)
    if "--telegram" in sys.argv:
        for i in range(0, len(txt), 3500):
            telegram_send(txt[i:i + 3500])
            time.sleep(1)


if __name__ == "__main__":
    main()

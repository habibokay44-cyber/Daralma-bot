"""H1/H2 keşfi (aday seçimi, kanıt DEĞİL): rastgele örneklemde birkaç ayar varyantını dener.
Hiçbir ayarı değiştirmez, sadece ölçüp Telegram'a yazar.

H1 erken etiket: etiket daralma olgunlaşmadan çıkıyor (örneklemde 15 yanlışın 8'i).
   persist=2 : setup şartı 2 gün üst üste sağlanınca etiket
   nC=6, nC=7: sıkışma 5 yerine 6/7 mumda ölçülür
H2 çizgi seçimi: düşen yerine yatay çizgi beklenen etiketler (SVGYO, BINBN, BSOKE, ATLAS).
   hPrefer=2, hPrefer=99: yatay seviye geçerliyse yatayı tercih et

ÖNCEDEN YAZILMIŞ SEÇİM ÖLÇÜTÜ (03.11.2026):
 H1 varyantı aday olur: erken 8'den >= 4'ü düzelir (eski tarihte etiket yok, notta yazdığın doğru aralıkta etiket var)
                        VE 24 doğrudan en fazla 3'ü kaybolur (eski tarihin ±3 günü içinde etiket kalmaz).
 H2 varyantı aday olur: 4 yatay-beklenen etiketten >= 3'ü Yatay'a döner
                        VE çizgisi doğru (cizgi=d) Düşen etiketlerden en fazla 3'ü Yatay'a döner.
Aday çıkarsa ikinci aşama: o ayarla YENİ rastgele örneklem (farklı tohum), kör işaretleme.
Çalıştırma: python kesif.py --telegram
"""
from __future__ import annotations

import sys
import time
from dataclasses import replace

import pandas as pd

from calibrate import CAND
from dogrula import read_marks
from fd_core import Params, run
from scan import fetch_tv_all, telegram_send

# Notlarına göre etiketin olması gereken tarih aralığı (kutunun bittiği gün ±1)
ERKEN = {
    "TEHOL": ("2026-05-08", "2026-05-12"),
    "KRDMA": ("2026-04-27", "2026-04-29"),
    "KRDMD": ("2025-12-09", "2025-12-11"),
    "CEOEM": ("2026-03-24", "2026-03-26"),
    "MAGEN": ("2026-03-20", "2026-03-24"),
    "DURDO": ("2026-04-01", "2026-04-03"),
    "MEDTR": ("2025-12-12", "2025-12-16"),
    "BSOKE": ("2026-04-06", "2026-04-08"),
}
YATAY_BEKLENEN = {"SVGYO", "BINBN", "BSOKE", "ATLAS"}

VARIANTS = [
    ("şimdiki ayar", {}),
    ("H1 persist=2", dict(persist=2)),
    ("H1 nC=6", dict(nC=6)),
    ("H1 nC=7", dict(nC=7)),
    ("H2 hPrefer=2", dict(hPrefer=2)),
    ("H2 hPrefer=99", dict(hPrefer=99)),
]


def labels(df, kw):
    res = run(df, replace(Params(), **{**CAND, **kw}))
    return [e for e in res.events if e["type"] == "setup" and not e.get("cancelled")]


def near(evs, d, days):
    return [e for e in evs if abs((e["date"] - d).days) <= days]


def inwin(evs, a, b):
    return [e for e in evs if pd.Timestamp(a) <= e["date"] <= pd.Timestamp(b)]


def evaluate(frames, marks, name, kw):
    fix, fixl, lost, lostl, gone_w, sw_y, sw_bad, nlab, nbars = 0, [], 0, [], 0, 0, [], 0, 0
    seen = set()
    nE = sum(1 for m in marks if m["sym"] in ERKEN and m["isr"] == "y" and m["sym"] in frames)
    nD = sum(1 for m in marks if m["isr"] == "d" and m["sym"] in frames)
    nW = sum(1 for m in marks if m["isr"] == "y" and m["sym"] not in ERKEN and m["sym"] in frames)
    nY = sum(1 for m in marks if m["sym"] in YATAY_BEKLENEN and m["sym"] in frames)
    for m in marks:
        df = frames.get(m["sym"])
        if df is None:
            continue
        evs = labels(df, kw)
        if m["sym"] not in seen:
            seen.add(m["sym"])
            cut = m["date"] - pd.Timedelta(days=365)
            nlab += sum(1 for e in evs if e["date"] >= cut)
            nbars += int((df.index >= cut).sum())
        orig = near(evs, m["date"], 1)
        if m["sym"] in ERKEN and m["isr"] == "y":
            a, b = ERKEN[m["sym"]]
            if not orig and inwin(evs, a, b):
                fix += 1
                fixl.append(m["sym"])
        elif m["isr"] == "y" and not near(evs, m["date"], 3):
            gone_w += 1
        if m["isr"] == "d" and not near(evs, m["date"], 3):
            lost += 1
            lostl.append(m["sym"])
        nn = near(evs, m["date"], 3)
        if m["sym"] in YATAY_BEKLENEN and nn and nn[0]["mode"] == "Yatay":
            sw_y += 1
        if m["mode"] == "Düşen" and m["czg"] == "d" and nn and nn[0]["mode"] == "Yatay":
            sw_bad.append(m["sym"])
    dens = nlab / nbars * 1000 if nbars else 0.0
    if name.startswith("H1"):
        ok = fix >= 4 and lost <= 3
    elif name.startswith("H2"):
        ok = sw_y >= 3 and len(sw_bad) <= 3
    else:
        ok = None
    verdict = "" if ok is None else (" -> ✅ ADAY" if ok else " -> ❌ değil")
    return (f"• {name}: erken düzelen {fix}/{nE} ({', '.join(fixl) or '-'}) | doğru kaybolan {lost}/{nD} ({', '.join(lostl) or '-'}) | "
            f"diğer yanlışlardan kalkan {gone_w}/{nW} | yatay-beklenen Yatay'a dönen {sw_y}/{nY} | "
            f"çizgisi doğru Düşen'den Yatay'a dönen {len(sw_bad)} ({', '.join(sw_bad) or '-'}) | "
            f"etiket/1000 mum {dens:.1f}{verdict}")


def main():
    marks = read_marks()
    syms = sorted({m["sym"] for m in marks})
    frames = fetch_tv_all(syms, n_bars=700, budget=10 * 60)
    for _ in range(2):
        miss = [s for s in syms if s not in frames]
        if not miss:
            break
        time.sleep(3)
        frames.update(fetch_tv_all(miss, n_bars=700, budget=3 * 60))
    out = ["🔭 H1/H2 keşfi (aday seçimi, kanıt değil; 40 örneklem etiketi):"]
    for name, kw in VARIANTS:
        out.append(evaluate(frames, marks, name, kw))
    out.append("\nAday çıkarsa: o ayarla yeni rastgele örneklem üretip kör işaretleyeceğiz.")
    txt = "\n".join(out)
    print(txt)
    if "--telegram" in sys.argv:
        for i in range(0, len(txt), 3500):
            telegram_send(txt[i:i + 3500])
            time.sleep(1)


if __name__ == "__main__":
    main()

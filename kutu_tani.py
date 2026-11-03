"""Kaçan kutuların tanısı: senin verdiğin kutu günlerinde hangi kural ne kadar farkla tutmadı.
Hiçbir ayarı değiştirmez. Çıktıya bakıp tanımı SENİN kararınla değiştireceğiz.

1) Notlarında tarih verdiğin ve yakalanmayan kutular: senin aralığın üzerinde her kural.
2) Örneklemde doğru işaretli ama yanında kutu olmayan etiketler: etiket günü biten 3 mumluk kutu üzerinde.
Her satırda, o çevrede dedektörün açıp kapattığı kutular da yazılır (neden bozulduğu ile).
Çalıştırma: python kutu_tani.py --telegram
"""
from __future__ import annotations

import sys
import time
from collections import Counter

import pandas as pd

from dogrula import read_marks
from kutu_test import USER_BOX, alive, hits
from kutu_yeni import KP, detect, explain
from scan import fetch_tv_all, telegram_send

D = pd.Timedelta
KEYS = [("small", "küçük"), ("band", "bant"), ("slope", "yön"), ("ema10", "EMA10↑"), ("ema21", "EMA21↑"),
        ("res", "direnç"), ("floor", "taban")]


def line(sym, df, boxes, a, z):
    ex = explain(df, a, z)
    if ex is None:
        return f"{sym}: ölçülemedi", []
    fails = [k for k, _ in KEYS if not ex[k][0]]
    parts = [f"{nm}{'✓' if ex[k][0] else '✗'}" for k, nm in KEYS]
    det = [ex[k][1] for k in ("small", "band", "slope", "ema10", "ema21", "res") if not ex[k][0]]
    near = [b for b in boxes if alive(df, b)[1] >= pd.Timestamp(a) - D(days=20) and alive(df, b)[0] <= pd.Timestamp(z) + D(days=5)]
    nb = "; ".join(f"{b['start_d']:%d.%m}-{alive(df, b)[1]:%d.%m} {b['status']}{'/' + b['why'] if b.get('why') else ''}" for b in near[:3])
    txt = (f"{sym} {ex['s']:%d.%m}-{ex['t']:%d.%m} ({ex['n']} mum): " + " ".join(parts)
           + (f"\n   → {' | '.join(det)}" if det else "")
           + f"\n   mum oranları {ex['small'][2]}"
           + (f"\n   çevredeki kutular: {nb}" if nb else "\n   çevrede kutu yok"))
    return txt, fails


def main():
    marks = read_marks()
    want = {s for s in USER_BOX} | {m["sym"] for m in marks if m["isr"] == "d"}
    syms = sorted(want)
    frames = fetch_tv_all(syms, n_bars=700, budget=10 * 60)
    for _ in range(2):
        miss = [s for s in syms if s not in frames]
        if not miss:
            break
        time.sleep(3)
        frames.update(fetch_tv_all(miss, n_bars=700, budget=3 * 60))
    P = KP()
    B = {s: detect(df, P) for s, df in frames.items()}
    out = ["🩺 Kaçan kutuların tanısı (✗ = o kural tutmadı)", "", "1) Notlarında verdiğin kutular:"]
    cnt = Counter()
    for s, (a, z) in USER_BOX.items():
        df = frames.get(s)
        if df is None:
            continue
        if hits(df, B[s], pd.Timestamp(a), pd.Timestamp(z) + D(days=2)):
            continue
        txt, fails = line(s, df, B[s], a, z)
        cnt.update(fails)
        out.append(txt)
    out.append("\n2) Örneklemde doğru ama yanında kutu olmayan etiketler (etiket günü biten 3 mum):")
    for m in marks:
        if m["isr"] != "d" or m["sym"] in USER_BOX:
            continue
        df = frames.get(m["sym"])
        if df is None:
            continue
        if hits(df, B[m["sym"]], m["date"] - D(days=3), m["date"] + D(days=3)):
            continue
        txt, fails = line(m["sym"], df, B[m["sym"]], m["date"] - D(days=4), m["date"])
        cnt.update(fails)
        out.append(txt)
    out.append("\nToplam, hangi kural kaç kez tutmadı: " + ", ".join(f"{dict(KEYS)[k]} {v}" for k, v in cnt.most_common()))
    txt = "\n".join(out)
    print(txt)
    if "--telegram" in sys.argv:
        parts, cur = [], ""
        for ln in txt.split("\n"):
            if cur and len(cur) + len(ln) + 1 > 3500:
                parts.append(cur)
                cur = ""
            cur = (cur + "\n" + ln) if cur else ln
        if cur:
            parts.append(cur)
        for p in parts:
            telegram_send(p)
            time.sleep(1)


if __name__ == "__main__":
    main()

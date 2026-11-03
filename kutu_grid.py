"""Yakınlık denemesi: 3 yakınlık şartı x 2 bant (1.0/1.5 ADR) x EMA21 filtresi açık/kapalı = 12 satır. Hiçbir ayarı değiştirmez.

ÖNCEDEN YAZILMIŞ SEÇİM KURALI (04.11.2026):
  a) senin 13 kutundan en az 9'u yakalanır
  c) erken-dışı 7 yanlıştan en fazla 2'sinde kutu var
  d) yoğunluk 1000 mumda 15'ten az
  Birden fazla satır geçerse: örneklemde doğru etiketleri (b) en çok yakalayan seçilir.
  Hiçbiri geçmezse tanımı birlikte yeniden konuşuruz.
Bu seçim aynı 40'lık örneklemde yapılıyor, kanıt değil. Son karar yeni kör örneklemde.
Ek bilgi: kutu boyu (%) ve direnç kırılımında giriş yapılırsa stop mesafesi (dirençten tabana %), medyan.
Çalıştırma: python kutu_grid.py --telegram
"""
from __future__ import annotations

import sys
import time

import numpy as np
import pandas as pd

from dogrula import read_marks
from kutu_test import USER_BOX, hits
from kutu_yeni import KP, detect
from scan import fetch_tv_all, telegram_send

D = pd.Timedelta
PROX = [("stop≤%5", dict(MAX_STOP=5.0)), ("stop≤%7", dict(MAX_STOP=7.0)), ("dirence ≤1 ADR", dict(NEAR_ADR=1.0))]
GRID = [(pn, pk, band, pe) for pn, pk in PROX for band in (1.0, 1.5) for pe in (False, True)]


def score(frames, marks, P):
    B = {s: detect(df, P) for s, df in frames.items()}
    a = sum(1 for s, (x, z) in USER_BOX.items() if s in frames
            and hits(frames[s], B[s], pd.Timestamp(x), pd.Timestamp(z) + D(days=2)))
    b = bn = c = cn = 0
    cl = []
    for m in marks:
        df = frames.get(m["sym"])
        if df is None or m["isr"] not in ("d", "y"):
            continue
        h = hits(df, B[m["sym"]], m["date"] - D(days=3), m["date"] + D(days=3))
        if m["isr"] == "d":
            bn += 1
            b += bool(h)
        elif m["sym"] not in USER_BOX:
            cn += 1
            c += bool(h)
            if h:
                cl.append(m["sym"])
    nb = sum(len(df) for df in frames.values())
    nbox = sum(len(v) for v in B.values())
    hp, sp = [], []
    for s, v in B.items():
        df = frames[s]
        o, cc = df["Open"].to_numpy(float), df["Close"].to_numpy(float)
        for bx in v:
            seg = slice(bx["start"], bx["end_t"] + 1)
            hp.append((np.maximum(o[seg], cc[seg]).max() / np.minimum(o[seg], cc[seg]).min() - 1) * 100)
            sp.append((bx["R"] / bx["floor"] - 1) * 100)
    dens = nbox / nb * 1000 if nb else 0
    return dict(a=a, b=b, bn=bn, c=c, cn=cn, cl=cl, dens=dens,
                hp=float(np.median(hp)) if hp else 0, sp=float(np.median(sp)) if sp else 0,
                sp75=float(np.percentile(sp, 75)) if sp else 0)


def main():
    marks = read_marks()
    syms = sorted({m["sym"] for m in marks} | set(USER_BOX))
    frames = fetch_tv_all(syms, n_bars=700, budget=10 * 60)
    for _ in range(2):
        miss = [s for s in syms if s not in frames]
        if not miss:
            break
        time.sleep(3)
        frames.update(fetch_tv_all(miss, n_bars=700, budget=3 * 60))
    out = ["📐 Yakınlık + bant denemesi (a: senin 13 kutun, b: örneklem doğruları, c: 7 yanlış, d: yoğunluk)",
           "Seçim: a≥9, c≤2, d<15; birden fazlaysa en yüksek b.", ""]
    rows = []
    for pn, pk, band, pe in GRID:
        r = score(frames, marks, KP(BAND=band, PRICE_EMA=pe, **pk))
        ok = r["a"] >= 9 and r["c"] <= 2 and r["dens"] < 15
        rows.append((ok, r["b"], f"{pn}, bant {band} ADR, EMA21 filtresi {'açık' if pe else 'kapalı'}"))
        out.append(f"• {pn} | bant {band} | EMA21 {'açık' if pe else 'kapalı'}: a {r['a']}/13 | b {r['b']}/{r['bn']} | "
                   f"c {r['c']}/{r['cn']} {','.join(r['cl'])} | d {r['dens']:.1f} | kutu boyu %{r['hp']:.1f} | "
                   f"stop %{r['sp']:.1f} (4'te 1'i %{r['sp75']:.1f} üstü) {'✅' if ok else ''}")
    win = sorted([x for x in rows if x[0]], key=lambda x: -x[1])
    out.append("")
    out.append(f"Seçilen: {win[0][2]} -> yeni kör örnekleme geçilebilir"
               if win else "Hiçbir satır seçim kuralını geçmedi -> tanımı birlikte yeniden konuşalım")
    txt = "\n".join(out)
    print(txt)
    if "--telegram" in sys.argv:
        telegram_send(txt[:3900])


if __name__ == "__main__":
    main()

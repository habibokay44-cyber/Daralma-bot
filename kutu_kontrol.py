"""Senin 4 yeni örneğinde kontrol: kutu dedektörü (etiket 5. mumda) kümelenmeyi görüyor mu? Hiçbir ayarı değiştirmez.

Bu 4 örneğe AYAR YAPILMAYACAK; sadece dedektörün kümeyi görüp görmediğine bakılır.
ÖNCEDEN YAZILMIŞ GEÇİŞ (04.11.2026): 4 kümeden en az 3'ünde, kümeyle kesişen ve etiketi kümenin bitişinden
en geç 2 gün sonra çıkan bir kutu varsa -> yeni kör örnekleme (kutu_orneklem3.py) geçilir.
Tarihler senin ekran görüntülerinden tahmindir; yanlışsa aşağıdaki KUMELER satırını düzelt.
Çalıştırma: python kutu_kontrol.py --telegram
"""
from __future__ import annotations

import sys

import pandas as pd

from kutu_orneklem3 import P
from kutu_yeni import explain, detect
from scan import fetch_tv_all, telegram_send

# (hisse, küme başı, küme sonu)  -- ekran görüntülerinden tahmin
KUMELER = [
    ("PINSU", "2026-04-07", "2026-04-13"),
    ("KAPLM", "2026-03-25", "2026-04-02"),
    ("DCTTR", "2025-01-02", "2025-01-15"),
    ("DCTTR", "2026-03-27", "2026-04-02"),
]
D = pd.Timedelta
KEYS = [("small", "mum"), ("band", "bant"), ("slope", "yön"), ("ema10", "EMA10"), ("ema21", "EMA21"),
        ("res", "direnç"), ("floor", "taban")]


def main():
    frames = fetch_tv_all(sorted({k[0] for k in KUMELER}), n_bars=900, budget=5 * 60)
    out = ["🔍 Kutu dedektörü kontrolü (etiket 5. mumda), senin 4 yeni örneğin:"]
    ok = 0
    for sym, a, z in KUMELER:
        df = frames.get(sym)
        if df is None:
            out.append(f"{sym} {a}: veri yok")
            continue
        A, Z = pd.Timestamp(a), pd.Timestamp(z)
        bx = detect(df, P)
        near = []
        for b in bx:
            last = df.index[min(b.get("break_t", b.get("stop_t", b["end_t"])), len(df) - 1)]
            if b["start_d"] <= Z + D(days=2) and last >= A:
                near.append((b, last))
        hit = [x for x in near if x[0]["label_d"] <= Z + D(days=2)]
        ok += bool(hit)
        line = f"{'✓' if hit else '✗'} {sym} küme {A:%d.%m.%Y}–{Z:%d.%m.%Y}: "
        if near:
            line += "; ".join(f"kutu {b['start_d']:%d.%m}→etiket {b['label_d']:%d.%m}→{last:%d.%m} {b['status']}"
                              + (f"/{b['why']}" if b.get("why") else "") for b, last in near[:3])
        else:
            line += "kutu yok"
        ex = explain(df, A, Z, P)
        if ex:
            line += "\n   senin kümende kurallar: " + " ".join(f"{nm}{'✓' if ex[k][0] else '✗'}" for k, nm in KEYS)
            bad = [ex[k][1] for k in ("small", "band", "slope", "ema10", "ema21", "res") if not ex[k][0]]
            if bad:
                line += "\n   → " + " | ".join(bad)
        out.append(line)
    out.append(f"\nGeçiş (en az 3/4): {ok}/4 -> " + ("✅ kutu_orneklem3 çalıştırılabilir" if ok >= 3 else "❌ önce birlikte bakalım"))
    txt = "\n".join(out)
    print(txt)
    if "--telegram" in sys.argv:
        telegram_send(txt[:3900])


if __name__ == "__main__":
    main()

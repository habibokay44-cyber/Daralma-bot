"""Senin 4 örneğinde kontrol: kümelenme kutusu dedektörü (ana mum + içeride kalan mumlar) kümeyi görüyor mu?
Hiçbir ayarı değiştirmez. Bu 4 örneğe AYAR YAPILMAYACAK.

ÖNCEDEN YAZILMIŞ GEÇİŞ (04.11.2026): 4 kümeden en az 3'ünde, ana mumu senin küme başlangıcına ±3 gün yakın olan
ve etiketi küme bitişinden en geç 2 gün sonra çıkan bir kutu varsa -> yeni kör örnekleme (kutu_orneklem3.py) geçilir.
Tarihler ekran görüntülerinden tahmindir; yanlışsa KUMELER satırını düzelt.
Çalıştırma: python kutu_kontrol.py --telegram
"""
from __future__ import annotations

import sys

import numpy as np
import pandas as pd

from kutu_orneklem3 import P
from kutu_yeni import detect_kume, explain_kume
from scan import fetch_tv_all, telegram_send

# (hisse, küme başı = ana mum, küme sonu)  -- ekran görüntülerinden tahmin
KUMELER = [
    ("PINSU", "2026-04-07", "2026-04-13"),
    ("KAPLM", "2026-03-25", "2026-04-02"),
    ("DCTTR", "2025-01-02", "2025-01-15"),
    ("DCTTR", "2025-03-25", "2025-04-03"),  # senin düzeltmen
]
D = pd.Timedelta


def main():
    syms = sorted({k[0] for k in KUMELER})
    frames = fetch_tv_all(syms, n_bars=900, budget=5 * 60)
    out = ["🔍 Kümelenme kutusu kontrolü (ana mum + içeride kalan mumlar, etiket 4. mumda, 0.25 ADR pay):"]
    ok = 0
    for sym, a, z in KUMELER:
        df = frames.get(sym)
        if df is None:
            out.append(f"{sym} {a}: veri yok")
            continue
        A, Z = pd.Timestamp(a), pd.Timestamp(z)
        bx = [b for b in detect_kume(df, P) if abs((b["start_d"] - A).days) <= 3 or (b["start_d"] <= A and b["end_d"] >= A)]
        hit = [b for b in bx if b["label_d"] <= Z + D(days=2)]
        ok += bool(hit)
        line = f"{'✓' if hit else '✗'} {sym} küme {A:%d.%m.%Y}–{Z:%d.%m.%Y}: "
        line += ("; ".join(f"ana mum {b['start_d']:%d.%m} → etiket {b['label_d']:%d.%m} → {b['end_d']:%d.%m} {b['status']}"
                           + (f"/{b['why']}" if b.get("why") else "") + f" [taban {b['floor']:.2f} tepe {b['R']:.2f}, "
                           f"kutu %{(b['R'] / b['floor'] - 1) * 100:.1f}]" for b in bx[:2]) if bx else "kutu yok")
        if not hit:
            for k in range(-1, 2):  # tahmin ettiğim günün bir öncesi/sonrası da ana mum olsaydı
                line += f"\n   ana mum {k:+d} gün: " + explain_kume(df, A + D(days=k), P)
        out.append(line)
    # yoğunluk ve kutu boyu (bilgi)
    nb = sum(len(df) for df in frames.values())
    allb = [b for df in frames.values() for b in detect_kume(df, P)]
    hp = [(b["R"] / b["floor"] - 1) * 100 for b in allb]
    out.append(f"\nBilgi ({len(frames)} hisse): {len(allb) / nb * 1000 if nb else 0:.1f} etiket/1000 mum "
               f"(eski gösterge 8.1) | kutu boyu = stop mesafesi medyan %{np.median(hp) if hp else 0:.1f}")
    out.append(f"Geçiş (en az 3/4): {ok}/4 -> " + ("✅ kutu_orneklem3 çalıştırılabilir" if ok >= 3 else "❌ önce birlikte bakalım"))
    txt = "\n".join(out)
    print(txt)
    if "--telegram" in sys.argv:
        telegram_send(txt[:3900])


if __name__ == "__main__":
    main()

"""v4 ön kontrolü (kümelenme kutusu + en az 2 temaslı direnç). Hiçbir ayarı değiştirmez.

1) Senin 4 örneğin (PINSU çıkarıldı, ENTRA eklendi): v4 kümeyi görüyor mu?
   Geçiş: en az 3/4 (ana mum ±3 gün, etiket küme bitişinden en geç 2 gün sonra).
2) Dün işaretlediğin 40 kümelenme kutusu (state/orneklem3.csv): v4 hangilerini tutar, hangilerini eler?
   ÖNCEDEN YAZILMIŞ ŞART (05.11.2026): tutulan en az 15 kutu VE tutulanlarda isabet en az %65
   (kümelenme kutusunun kör isabeti %41 idi).
İkisi de geçerse yeni kör örnekleme değer; geçmezse konu kapanır.
Çalıştırma: python kutu_kontrol.py --telegram
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from kutu_yeni import KK, detect_kume, explain_kume
from scan import fetch_tv_all, telegram_send

P4 = KK()                 # v4: 2 temaslı direnç
P3 = KK(MIN_TOUCH=1)      # v3: dün sınanan kümelenme kutusu
KUMELER = [
    ("KAPLM", "2026-03-25", "2026-04-02"),
    ("DCTTR", "2025-01-02", "2025-01-15"),
    ("DCTTR", "2025-03-25", "2025-04-03"),
    ("ENTRA", "2026-10-21", "2026-11-03"),  # ekran görüntüsünden tahmin
]
F3 = Path(__file__).resolve().parent / "state" / "orneklem3.csv"
D = pd.Timedelta


def kontrol(frames):
    out, ok = ["1) Senin örneklerin (v4):"], 0
    for sym, a, z in KUMELER:
        df = frames.get(sym)
        if df is None:
            out.append(f"{sym} {a}: veri yok")
            continue
        A, Z = pd.Timestamp(a), pd.Timestamp(z)
        bx = [b for b in detect_kume(df, P4) if abs((b["start_d"] - A).days) <= 3 or (b["start_d"] <= A and b["end_d"] >= A)]
        hit = [b for b in bx if b["label_d"] <= Z + D(days=2)]
        ok += bool(hit)
        line = f"{'✓' if hit else '✗'} {sym} {A:%d.%m.%Y}–{Z:%d.%m.%Y}: "
        line += ("; ".join(f"ana mum {b['start_d']:%d.%m} → etiket {b['label_d']:%d.%m} → {b['end_d']:%d.%m} {b['status']} "
                           f"[{b['touches']} temas, kutu %{(b['R'] / b['floor'] - 1) * 100:.1f}]" for b in bx[:2]) if bx else "kutu yok")
        if not hit:
            for k in (-1, 0, 1):
                line += f"\n   ana mum {k:+d} gün: " + explain_kume(df, A + D(days=k), P4)
        out.append(line)
    out.append(f"   Geçiş (en az 3/4): {ok}/4 {'✅' if ok >= 3 else '❌'}")
    return out, ok >= 3


def dunku(frames):
    out = ["2) Dünkü 40 kümelenme kutusu, v4 ile:"]
    if not F3.exists():
        return out + ["   orneklem3.csv yok"], False
    rows = []
    with F3.open(encoding="utf-8") as fh:
        rd = csv.reader(fh)
        next(rd, None)
        for r in rd:
            if len(r) >= 7 and r[6].strip().lower() in ("d", "y"):
                rows.append((r[1].strip(), pd.Timestamp(r[2]), r[6].strip().lower() == "d"))
    kept, drop, miss = [], [], []
    for sym, start, okk in rows:
        df = frames.get(sym)
        if df is None:
            miss.append(sym)
            continue
        b4 = [b for b in detect_kume(df, P4) if b["start_d"] == start]
        (kept if b4 else drop).append((sym, okk, b4[0] if b4 else None))
    def acc(x):
        return sum(1 for _, o, _ in x if o), len(x)
    kd, kn = acc(kept)
    dd, dn = acc(drop)
    ok = kn >= 15 and kn and kd / kn >= 0.65
    out.append(f"   v4 tutar: {kn} kutu, {kd} doğru (%{100 * kd / kn if kn else 0:.0f})")
    out.append(f"   v4 eler: {dn} kutu, {dd} doğru (%{100 * dd / dn if dn else 0:.0f})")
    out.append("   tutulanlar: " + ", ".join(f"{s}({'d' if o else 'y'})" for s, o, _ in kept))
    if miss:
        out.append("   veri yok: " + ", ".join(miss))
    out.append(f"   Şart (en az 15 tutulan, isabet ≥%65): {'✅' if ok else '❌'}")
    return out, ok


def main():
    syms = {k[0] for k in KUMELER}
    if F3.exists():
        with F3.open(encoding="utf-8") as fh:
            rd = csv.reader(fh)
            next(rd, None)
            syms |= {r[1].strip() for r in rd if len(r) > 1}
    frames = fetch_tv_all(sorted(syms), n_bars=900, budget=10 * 60)
    o1, g1 = kontrol(frames)
    o2, g2 = dunku(frames)
    allb = [b for df in frames.values() for b in detect_kume(df, P4)]
    a3 = [b for df in frames.values() for b in detect_kume(df, P3)]
    nb = sum(len(df) for df in frames.values())
    info = (f"Bilgi ({len(frames)} hisse): v4 {len(allb) / nb * 1000 if nb else 0:.1f}, v3 {len(a3) / nb * 1000 if nb else 0:.1f} "
            f"etiket/1000 mum (eski gösterge 8.1)")
    txt = "\n".join(["🔍 v4 ön kontrolü (kümelenme kutusu + en az 2 temaslı direnç)"] + o1 + [""] + o2 + ["", info,
                     "Sonuç: " + ("✅ yeni kör örnekleme değer" if g1 and g2 else "❌ konu kapanır")])
    print(txt)
    if "--telegram" in sys.argv:
        telegram_send(txt[:3900])


if __name__ == "__main__":
    main()

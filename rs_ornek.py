"""Kullanıcının base / kaçan / doğru örneklerinde kırılım günü RS durumu (11.11.2026). Bilgi.
Çalıştırma: python rs_ornek.py --telegram"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

import pandas as pd

import rs
from scan import fetch_tv_all, telegram_send

ST = Path(__file__).resolve().parent / "state"


def main():
    orn = []
    for f, kol in (("kacan.csv", "tarih"), ("dogru_ornek.csv", "kirilim")):
        p = ST / f
        if p.exists():
            for r in csv.DictReader(p.open(encoding="utf-8")):
                if r.get(kol):
                    orn.append((r["hisse"], r[kol], f.split(".")[0], (r.get("not") or r.get("gosterge") or "")[:30]))
    orn = list({(s, d): (s, d, k, n) for s, d, k, n in orn}.values())
    fr = fetch_tv_all(sorted({o[0] for o in orn}), n_bars=1500, budget=8 * 60, min_bars=30)
    xu = fetch_tv_all(["XU100"], n_bars=1500, budget=120, min_bars=30).get("XU100")["Close"].astype(float)
    sat, g = [], 0
    for s, d, k, n in sorted(orn, key=lambda x: x[1]):
        df = fr.get(s)
        o = rs.olc(df, xu, d) if df is not None else None
        if o is None:
            sat.append(f"  {s} {d}: veri yok")
            continue
        g += o["guclu"]
        sat.append(f"  {s} {d}: {'💪' if o['guclu'] else '·'} zirveye %{-o['uzak']:.1f} · {'yükselen' if o['yukselen'] else '-'} | {n}")
    n_ = sum(1 for x in sat if "veri yok" not in x)
    txt = f"💪 Örneklerinde RS: {g}/{n_} güçlü (taramadaki tüm sinyallerde oran ~%57)\n" + "\n".join(sat)
    print(txt)
    if "--telegram" in sys.argv:
        telegram_send(txt[:3900])


if __name__ == "__main__":
    main()

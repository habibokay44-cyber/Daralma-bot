"""Grafik albümü testi: state/etiket_kayit.csv'deki son N etiketin grafiğini Telegram'a albüm olarak gönderir.
Taramayı ve kayıtları etkilemez. Çalıştırma: python grafik_test.py [N]   (varsayılan 5)
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

import pandas as pd

from fd_core import Params, run
from grafik import gonder_album
from scan import fetch_tv_all, telegram_send

F = Path(__file__).resolve().parent / "state" / "etiket_kayit.csv"


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 5
    if not F.exists():
        telegram_send("Grafik testi: etiket_kayit.csv yok.")
        return
    rows = list(csv.DictReader(F.open(encoding="utf-8")))[-n:]
    frames = fetch_tv_all(sorted({r["hisse"] for r in rows}), n_bars=500, budget=5 * 60)
    items, eks = [], []
    for r in rows:
        df = frames.get(r["hisse"])
        if df is None:
            eks.append(f"{r['hisse']}(veri yok)")
            continue
        d = pd.Timestamp(r["etiket_tarihi"])
        ev = [e for e in run(df, Params()).events if e["type"] == "setup" and e["date"] == d]
        if not ev:
            eks.append(f"{r['hisse']}(etiket bulunamadı)")
            continue
        items.append((r["hisse"], df, ev[0]))
    k = gonder_album(items) if items else 0
    print(f"{k} grafik gönderildi" + (f"; eşleşmeyen: {', '.join(eks)}" if eks else ""))
    if eks:
        telegram_send("Grafik testi, eşleşmeyen: " + ", ".join(eks))


if __name__ == "__main__":
    main()

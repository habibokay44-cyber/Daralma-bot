"""Grafik testi: state/etiket_kayit.csv'deki son N etiketin grafiğini Telegram'a BUTONLU olarak gönderir
(Alırdım / Başka gün / Almazdım / Çizgi yanlış). Butonlar "Isaretleri isle" ile kayda işlenir.
Taramayı etkilemez. Çalıştırma: python grafik_test.py [N]   (varsayılan 5)
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import pandas as pd

from fd_core import Params, run
from grafik import gonder_butonlu
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
    esle = gonder_butonlu(items) if items else {}
    ep = F.parent / "tg_mesaj.json"
    try:
        eski = json.loads(ep.read_text())
    except Exception:  # noqa: BLE001
        eski = {}
    eski.update(esle)
    ep.write_text(json.dumps(dict(list(eski.items())[-500:]), indent=0))
    print(f"{len(esle)} butonlu grafik gönderildi" + (f"; eşleşmeyen: {', '.join(eks)}" if eks else ""))
    if eks:
        telegram_send("Grafik testi, eşleşmeyen: " + ", ".join(eks))


if __name__ == "__main__":
    main()

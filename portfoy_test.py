"""Sanal portföy TEST mesajı: son günlerin gerçek Giriş/Base sinyalleriyle portföyü gün gün çalıştırır ve sonucu
Telegram'a 'TEST' başlığıyla gönderir. Asıl portföy kaydına (state/portfoy.json) DOKUNMAZ.
Çalıştırma: python portfoy_test.py [gün sayısı, varsayılan 10]
"""
from __future__ import annotations

import random
import sys
import tempfile
from pathlib import Path

import pandas as pd

import portfoy
from base_v0 import sinyaller as base_sinyaller
from fd_core import Params, run
from scan import fetch_tv_all, get_tickers, telegram_send


def main():
    gun = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 10
    portfoy.F = Path(tempfile.mkdtemp()) / "portfoy_test.json"
    tick = get_tickers()
    syms = sorted(set(random.Random(1).sample(tick, min(250, len(tick)))) | {"DGNMO", "OZYSR"})
    frames = fetch_tv_all(syms, n_bars=400, budget=8 * 60, min_bars=30)
    ref = pd.Series([df.index[-1] for df in frames.values()]).mode().iloc[0]
    gunler = [d for d in next(iter(frames.values())).index if d <= ref][-gun:]
    sig = []
    for s, df in frames.items():
        if df.index[-1] != ref:
            continue
        n = len(df)
        try:
            if n >= 120:
                for e in run(df, Params()).events:
                    if e["type"] == "giris" and e["date"] >= gunler[0]:
                        sig.append(dict(sym=s, kaynak="Giriş", tarih=f"{e['date']:%Y-%m-%d}", kapanis=e["close"], dip=e["sl"]))
            for e in base_sinyaller(df):
                if e["date"] >= gunler[0]:
                    sig.append(dict(sym=s, kaynak="Base", tarih=f"{e['date']:%Y-%m-%d}", kapanis=e["close"],
                                    dip=float(df["Low"].iloc[e["t"]])))
        except Exception as ex:  # noqa: BLE001
            print(f"[uyarı] {s}: {ex}")
    msg = ""
    for d in gunler:
        fr = {k: v[v.index <= d] for k, v in frames.items()}
        msg = portfoy.gunluk(fr, [x for x in sig if x["tarih"] == f"{d:%Y-%m-%d}"], d)
    txt = (f"🧪 TEST · sanal portföy son {gun} işlem günü, {len(frames)} hisseyle (gerçek kayda yazılmadı)\n"
           f"Bu dönemde {len(sig)} sinyal ({sum(x['kaynak'] == 'Giriş' for x in sig)} Giriş, "
           f"{sum(x['kaynak'] == 'Base' for x in sig)} Base)\n\n" + msg)
    print(txt)
    telegram_send(txt[:3900])


if __name__ == "__main__":
    main()

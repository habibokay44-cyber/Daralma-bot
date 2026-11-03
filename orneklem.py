"""Rastgele geçmiş örneklem: tüm BIST'in son 1 yıllık etiketlerinden rastgele 40 tane seçer.

Amaç: göstergenin gerçek isabetini haftalarca beklemeden ölçmek. Örnekler senin seçtiğin
değil rastgele olduğu için seçim yanlılığı yok.
Her etikete TradingView'de Bar Replay ile etiket gününe kadar bak (sonrasını görmeden),
state/orneklem.csv içinde 'isaret' (d/y/b) ve 'cizgi' (d/y) sütunlarını doldur.
Özet: python ileri_test.py state/orneklem.csv

Dosya zaten varsa üzerine YAZMAZ (işaretlerin silinmesin). Yeniden üretmek için --yeni.
Hiçbir ayarı değiştirmez.
Çalıştırma: python orneklem.py --telegram
"""
from __future__ import annotations

import csv
import random
import sys
import time
from dataclasses import replace
from pathlib import Path

import pandas as pd

from calibrate import CAND, EXAMPLES
from fd_core import Params, run
from scan import fetch_tv_all, get_tickers, link, telegram_send

N = 40                 # örneklem büyüklüğü
GUN = 365              # son kaç takvim günü
SON_BOS = 10           # son 10 mumdaki etiketler alınmaz (ileri teste kalsın)
SEED = 20261103        # sabit tohum: aynı veriyle aynı örneklem
OUT = Path(__file__).resolve().parent / "state" / "orneklem.csv"


def known(sym: str, d: pd.Timestamp) -> bool:
    """calibrate.py örneklerine ±10 gün yakın etiketleri at (zaten bildiğimiz durumlar)."""
    for s, a, b, _e, _n in EXAMPLES:
        if s == sym and pd.Timestamp(a) - pd.Timedelta(days=10) <= d <= pd.Timestamp(b) + pd.Timedelta(days=10):
            return True
    return False


def main() -> None:
    if OUT.exists() and "--yeni" not in sys.argv:
        msg = f"{OUT.name} zaten var, üzerine yazılmadı. Özet için: python ileri_test.py state/orneklem.csv"
        print(msg)
        if "--telegram" in sys.argv:
            telegram_send(msg)
        return
    tickers = get_tickers()
    frames = fetch_tv_all(tickers, n_bars=700)
    print(f"{len(frames)}/{len(tickers)} hisse verisi alındı")
    P = replace(Params(), **CAND)
    havuz = []
    for sym, df in frames.items():
        try:
            res = run(df, P)
        except Exception:  # noqa: BLE001
            continue
        son = df.index[-1]
        for e in res.events:
            if e["type"] != "setup" or e.get("cancelled"):
                continue
            if e["t"] > len(df) - 1 - SON_BOS or e["date"] < son - pd.Timedelta(days=GUN):
                continue
            if known(sym, e["date"]):
                continue
            havuz.append((sym, e))
    rnd = random.Random(SEED)
    rnd.shuffle(havuz)
    sec, gor = [], set()
    for sym, e in havuz:      # her hisseden en fazla 1 etiket
        if sym in gor:
            continue
        gor.add(sym)
        sec.append((sym, e))
        if len(sec) == N:
            break
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["no", "hisse", "etiket_tarihi", "mod", "kapanis", "direnc", "isaret", "cizgi", "not"])
        for i, (sym, e) in enumerate(sec, 1):
            w.writerow([i, sym, f"{e['date']:%Y-%m-%d}", e["mode"], f"{e['close']:.2f}", f"{e['line']:.2f}", "", "", ""])
    head = (f"🎲 Rastgele örneklem: havuzda {len(havuz)} etiket ({len({s for s, _ in havuz})} hisse), {len(sec)} seçildi.\n"
            f"Her birine Bar Replay ile etiket gününe kadar bak, state/orneklem.csv'ye isaret (d/y/b) ve cizgi (d/y) yaz.")
    lines = [f"{i}. {sym} {e['date']:%d.%m.%Y} {e['mode']} direnç {e['line']:.2f}\n{link(sym)}" for i, (sym, e) in enumerate(sec, 1)]
    txt = head + "\n\n" + "\n".join(lines)
    print(txt)
    if "--telegram" in sys.argv:
        parts, cur = [], head
        for ln in lines:
            if len(cur) + len(ln) + 1 > 3500:
                parts.append(cur)
                cur = ""
            cur = (cur + "\n" + ln) if cur else ln
        parts.append(cur)
        for p in parts:
            telegram_send(p)
            time.sleep(1)


if __name__ == "__main__":
    main()

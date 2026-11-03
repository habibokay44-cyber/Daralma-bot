"""Yaşayan kutu dedektörü için KÖR örneklem (son sınav). Hiçbir ayarı değiştirmez.

DONDURULMUŞ AYAR (04.11.2026, onayın): bant 1.0 ADR, EMA21 filtresi açık, stop (dirençten tabana) en fazla %7,
ayrıca: en az 3 mum, hiçbir mum önceki 10 mumun ortalamasının 1.5 katını geçmiyor, yön yukarı/yan,
direnç altında, EMA10/EMA21 düşmüyor (5 günde %0.5'ten fazla).
ÖNCEDEN YAZILMIŞ KARAR: işaretli kutularda isabet >= %75 ise Pine'a taşınır; değilse eski gösterge kalır.
(Eski göstergenin kör isabeti %62, n=39.)

Kör olsun diye kutunun nasıl bittiği (kırılım/bozulma) dosyada ve mesajda YOK.
Her kutu için: başlangıç günü, etiket günü (kutunun açıldığı gün), taban ve direnç.
TradingView'de Bar Replay ile etiket gününe git, sonrasını görme; taban ve dirence yatay çizgi çekebilirsin.
state/orneklem2.csv'de 'isaret' sütununa: d = gerçek daralma kutusu, y = değil, b = emin değilim.
Özet: python ileri_test.py state/orneklem2.csv

İlk örneklemdeki 40 hisse hariç (tanımı onlarla şekillendirdik). Dosya varsa üzerine YAZMAZ (--yeni ile zorla).
Çalıştırma: python kutu_orneklem.py --telegram
"""
from __future__ import annotations

import csv
import random
import sys
import time
from pathlib import Path

import pandas as pd

from kutu_yeni import KP, detect
from scan import fetch_tv_all, get_tickers, link, telegram_send

P = KP(BAND=1.0, PRICE_EMA=True, MAX_STOP=7.0)
N = 40
GUN = 365
SON_BOS = 10
SEED = 20261104
HERE = Path(__file__).resolve().parent
OUT = HERE / "state" / "orneklem2.csv"
ILK = HERE / "state" / "orneklem.csv"


def main() -> None:
    if OUT.exists() and "--yeni" not in sys.argv:
        msg = f"{OUT.name} zaten var, üzerine yazılmadı. Özet için: python ileri_test.py state/orneklem2.csv"
        print(msg)
        if "--telegram" in sys.argv:
            telegram_send(msg)
        return
    haric = set()
    if ILK.exists():
        with ILK.open(encoding="utf-8") as fh:
            rd = csv.reader(fh)
            next(rd, None)
            haric = {r[1].strip() for r in rd if len(r) > 1}
    tickers = [t for t in get_tickers() if t not in haric]
    frames = fetch_tv_all(tickers, n_bars=700)
    print(f"{len(frames)}/{len(tickers)} hisse verisi alındı (ilk örneklemden {len(haric)} hisse hariç)")
    havuz = []
    for sym, df in frames.items():
        try:
            boxes = detect(df, P)
        except Exception:  # noqa: BLE001
            continue
        son = df.index[-1]
        for b in boxes:
            if b["label_t"] > len(df) - 1 - SON_BOS or b["label_d"] < son - pd.Timedelta(days=GUN):
                continue
            havuz.append((sym, b))
    rnd = random.Random(SEED)
    rnd.shuffle(havuz)
    sec, gor = [], set()
    for sym, b in havuz:
        if sym in gor:
            continue
        gor.add(sym)
        sec.append((sym, b))
        if len(sec) == N:
            break
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["no", "hisse", "kutu_baslangic", "etiket_tarihi", "taban", "direnc", "isaret", "not"])
        for i, (sym, b) in enumerate(sec, 1):
            w.writerow([i, sym, f"{b['start_d']:%Y-%m-%d}", f"{b['label_d']:%Y-%m-%d}", f"{b['floor']:.2f}", f"{b['R']:.2f}", "", ""])
    head = (f"📦🎲 Kutu dedektörü kör örneklemi: havuzda {len(havuz)} kutu ({len({s for s, _ in havuz})} hisse), {len(sec)} seçildi.\n"
            f"Bar Replay ile ETİKET gününe git, sonrasını görme. Kutu: başlangıç→etiket günü, taban ve direnç seviyesi.\n"
            f"state/orneklem2.csv 'isaret' sütununa d / y / b yaz. Karar: isabet ≥ %75 ise Pine'a taşınır.")
    lines = [f"{i}. {sym} kutu {b['start_d']:%d.%m.%Y}→{b['label_d']:%d.%m.%Y} taban {b['floor']:.2f} direnç {b['R']:.2f}\n{link(sym)}"
             for i, (sym, b) in enumerate(sec, 1)]
    print(head + "\n\n" + "\n".join(lines))
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

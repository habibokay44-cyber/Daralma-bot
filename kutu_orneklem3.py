"""Kümelenme kutusu dedektörü için KÖR örneklem (son sınav). Hiçbir ayarı değiştirmez.

DONDURULMUŞ TANIM (04.11.2026, senin tarifin):
  Ana mum = kümenin ilk mumu; kutu = ana mumun dibi..tepesi. Sonraki mumların açılış ve kapanışı kutunun içinde
  (fitiller serbest). Kutunun tepesi direnç: üstünde kapanış kırılım, altında kapanış bozulma.
  Etiket 4. mumda (ana mum + 3 mum içeride); açılış/kapanış kutunun 0.25 ADR dışına kadar taşabilir. EMA10/EMA21 5 mumda %0.5'ten fazla düşmüyor; ana mumdan sonraki
  kapanışlar aşağı eğimli değil.
ÖNCEDEN YAZILMIŞ KARAR: işaretli kutularda isabet >= %75 ise Pine'a taşınır; değilse eski gösterge kalır.
(Eski göstergenin kör isabeti %62, ilk kutu dedektörünün %49.)

Kör olsun diye kutunun nasıl bittiği dosyada ve mesajda YOK. GÖSTERGEYİ KAPAT.
Her kutu için: ana mum günü, etiket günü, kutu tabanı ve tepesi (tepe = direnç).
Bar Replay ile etiket gününe git, sonrasını görme. state/orneklem3.csv 'isaret' sütununa d / y / b yaz.
Özet: python ileri_test.py state/orneklem3.csv
Önceki iki örneklemdeki hisseler hariç. Dosya varsa üzerine YAZMAZ (--yeni ile zorla).
Çalıştırma: python kutu_orneklem3.py --telegram
"""
from __future__ import annotations

import csv
import random
import sys
import time
from pathlib import Path

import pandas as pd

from kutu_yeni import KK, detect_kume
from scan import fetch_tv_all, get_tickers, link, telegram_send

P = KK()  # LABEL_N=4, TOL_ADR=0.25
N = 40
GUN = 365
SON_BOS = 10
SEED = 20261105
HERE = Path(__file__).resolve().parent
OUT = HERE / "state" / "orneklem3.csv"
ONCEKI = [HERE / "state" / "orneklem.csv", HERE / "state" / "orneklem2.csv"]


def main() -> None:
    if OUT.exists() and "--yeni" not in sys.argv:
        msg = f"{OUT.name} zaten var, üzerine yazılmadı. Özet için: python ileri_test.py state/orneklem3.csv"
        print(msg)
        if "--telegram" in sys.argv:
            telegram_send(msg)
        return
    haric = set()
    for f in ONCEKI:
        if f.exists():
            with f.open(encoding="utf-8") as fh:
                rd = csv.reader(fh)
                next(rd, None)
                haric |= {r[1].strip() for r in rd if len(r) > 1}
    tickers = [t for t in get_tickers() if t not in haric]
    frames = fetch_tv_all(tickers, n_bars=700)
    print(f"{len(frames)}/{len(tickers)} hisse verisi alındı (önceki iki örneklemden {len(haric)} hisse hariç)")
    havuz = []
    for sym, df in frames.items():
        try:
            boxes = detect_kume(df, P)
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
    head = (f"📦🎲 Kümelenme kutusu kör örneklemi (ana mum + içeride kalan mumlar, etiket 4. mumda): havuzda {len(havuz)} kutu ({len({s for s, _ in havuz})} hisse), {len(sec)} seçildi.\n"
            f"Göstergeyi KAPAT. Bar Replay ile ETİKET gününe git, sonrasını görme. Kutu: ana mum→etiket günü; taban ve tepe (tepe = direnç).\n"
            f"state/orneklem3.csv 'isaret' sütununa d / y / b yaz. Karar: isabet ≥ %75 ise Pine'a taşınır.")
    lines = [f"{i}. {sym} ana mum {b['start_d']:%d.%m.%Y}→etiket {b['label_d']:%d.%m.%Y} taban {b['floor']:.2f} tepe {b['R']:.2f}\n{link(sym)}"
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

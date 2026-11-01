"""Kör örnekleme: yeni iki Düşen kuralı gerçekten yanlış etiketleri mi ayıklıyor?

Son LAST mumdan rastgele 15 etiket seçer: 6 silinen, 6 kalan Düşen, 3 kalan Yatay/Kutu.
Liste karışık ve hangisinin hangi grup olduğu gizli gelir. D/Y yazdıktan SONRA anahtar mesajı açılır.
Çalıştırma: python kural_ornek.py --telegram
"""
from __future__ import annotations

import argparse
import random
import sys
import time
from dataclasses import replace

from fd_core import Params, run
from gecmis_tara import CAND
from scan import fetch_tv_all, get_tickers, link, telegram_send

TOL = 3
LAST = 150
SEED = 7
OLD = dict(shrinkMinD=0.0, dnBelowSlope=-99.0)   # kurallar kapalı
NEW = dict(shrinkMinD=0.50, dnBelowSlope=0.0)    # kurallar açık


def live(res) -> list[tuple[int, str]]:
    return [(e["t"], e["mode"]) for e in res.events if e["type"] == "setup" and not e.get("cancelled")]


def missing_in(a, b):
    bt = [t for t, _ in b]
    return [(t, m) for t, m in a if not any(abs(t - u) <= TOL for u in bt)]


def send(txt: str, tg: bool) -> None:
    print(txt)
    if not tg:
        return
    parts, cur = [], ""
    for line in txt.split("\n"):
        if cur and len(cur) + len(line) + 1 > 3500:
            parts.append(cur)
            cur = ""
        cur = (cur + "\n" + line) if cur else line
    parts.append(cur)
    for p in parts:
        telegram_send(p[:3900])
        time.sleep(1)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--telegram", action="store_true")
    args = ap.parse_args()
    frames = fetch_tv_all(get_tickers(), n_bars=1500, budget=30 * 60)
    removed, kept_d, kept_o = [], [], []
    for sym, df in frames.items():
        try:
            n = len(df)
            old = live(run(df, replace(Params(), **{**CAND, **OLD})))
            new = live(run(df, replace(Params(), **{**CAND, **NEW})))
            for t, m in missing_in(old, new):
                if n - 1 - t <= LAST:
                    removed.append((sym, df.index[t], m))
            for t, m in new:
                if n - 1 - t <= LAST:
                    (kept_d if m == "Düşen" else kept_o).append((sym, df.index[t], m))
        except Exception as ex:  # noqa: BLE001
            print(f"[uyarı] {sym}: {ex}", file=sys.stderr)
    rnd = random.Random(SEED)
    pick = [("SİLİNEN", x) for x in rnd.sample(removed, min(6, len(removed)))]
    pick += [("KALAN-Düşen", x) for x in rnd.sample(kept_d, min(6, len(kept_d)))]
    pick += [("KALAN-diğer", x) for x in rnd.sample(kept_o, min(3, len(kept_o)))]
    rnd.shuffle(pick)
    head = (f"🎲 Kör örnek ({len(pick)} etiket, son {LAST} mum). Havuz: silinen {len(removed)}, kalan Düşen {len(kept_d)}, kalan diğer {len(kept_o)}.\n"
            "Her biri için grafiği aç, o tarihteki etikete bak ve D (doğru daralma) / Y (yanlış) yaz. Grubu bilmeden karar ver; anahtar bir sonraki mesajda.")
    lines = [f"{i}. {s} {d:%d.%m.%Y}  {link(s)}" for i, (_, (s, d, _m)) in enumerate(pick, 1)]
    send(head + "\n\n" + "\n".join(lines), args.telegram)
    key = ["🔑 ANAHTAR (D/Y yazdıktan sonra aç):"]
    key += [f"{i}. {s} {d:%d.%m} → {g} ({m})" for i, (g, (s, d, m)) in enumerate(pick, 1)]
    send("\n".join(key), args.telegram)


if __name__ == "__main__":
    sys.exit(main())

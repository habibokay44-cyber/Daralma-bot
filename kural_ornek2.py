"""Kör örnekleme v2: geçmişin tamamından dönemlere ve modlara dağıtılmış etiket örneği.

Varsayılan: son 500 mum (~2 yıl), 30 etiket = 6 silinen (kural yüzünden giden) + 10 kalan Düşen + 8 kalan Yatay + 6 kalan Kutu.
Her grup içinde ~üç aylık dönemlere eşit dağıtılır. Daha önce D/Y verdiğin etiketler hariç tutulur.
Liste karışık ve grup gizli gelir; anahtar ikinci mesajda.
Çalıştırma: python kural_ornek2.py --telegram [--last 500] [--n 30] [--seed 11]
"""
from __future__ import annotations

import argparse
import random
import sys
import time
from dataclasses import replace

import pandas as pd

from fd_core import Params, run
from gecmis_tara import CAND
from scan import fetch_tv_all, get_tickers, link, telegram_send

TOL = 3
BUCKET = 63                                       # ~üç aylık dönem (iş günü)
OLD = dict(shrinkMinD=0.0, dnBelowSlope=-99.0)    # kurallar kapalı
NEW = dict(shrinkMinD=0.50, dnBelowSlope=0.0)     # kurallar açık

# Daha önce senin D/Y verdiğin etiketler (tekrar sorulmasın)
SEEN = [
    ("GARAN", "2026-10-12"), ("HALKB", "2026-10-02"), ("AKSEN", "2026-07-01"), ("HKTM", "2026-06-18"),
    ("KRDMD", "2026-06-11"), ("TCELL", "2026-08-12"), ("TGSAS", "2026-08-11"), ("TTRAK", "2026-07-13"),
    ("MACKO", "2026-05-15"), ("BASGZ", "2026-09-02"), ("SERNT", "2026-06-17"), ("ARASE", "2026-06-19"),
    ("AVHOL", "2026-05-06"), ("BANVT", "2026-08-18"), ("PAHOL", "2026-06-12"), ("PASEU", "2026-06-08"),
    ("AKSUE", "2026-06-29"), ("GARFA", "2026-06-11"), ("GENIL", "2026-07-21"), ("VKING", "2026-04-14"),
    ("BOBET", "2026-07-14"), ("MRSHL", "2026-06-15"),
]
SEEN = [(s, pd.Timestamp(d)) for s, d in SEEN]


def live(res) -> list[tuple[int, str]]:
    return [(e["t"], e["mode"]) for e in res.events if e["type"] == "setup" and not e.get("cancelled")]


def missing_in(a, b):
    bt = [t for t, _ in b]
    return [(t, m) for t, m in a if not any(abs(t - u) <= TOL for u in bt)]


def seen(sym, d) -> bool:
    return any(s == sym and abs((d - x).days) <= 4 for s, x in SEEN)


def spread(pool, k, rnd):
    """Havuzdan k eleman; yaş kovalarına (dönemlere) dağıtarak seç."""
    pool = list(pool)
    buckets: dict[int, list] = {}
    for it in pool:
        buckets.setdefault(it[3] // BUCKET, []).append(it)
    for b in buckets.values():
        rnd.shuffle(b)
    keys = list(buckets)
    out = []
    while len(out) < k and keys:
        rnd.shuffle(keys)
        for key in list(keys):
            if buckets[key]:
                out.append(buckets[key].pop())
                if len(out) >= k:
                    break
            if not buckets[key]:
                keys.remove(key)
    return out


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
    ap.add_argument("--last", type=int, default=500)
    ap.add_argument("--n", type=int, default=30)
    ap.add_argument("--seed", type=int, default=11)
    args = ap.parse_args()
    frames = fetch_tv_all(get_tickers(), n_bars=1500, budget=30 * 60)
    removed, kept = [], {"Düşen": [], "Yatay": [], "Kutu": []}
    for sym, df in frames.items():
        try:
            n = len(df)
            old = live(run(df, replace(Params(), **{**CAND, **OLD})))
            new = live(run(df, replace(Params(), **{**CAND, **NEW})))
            for t, m in missing_in(old, new):
                age = n - 1 - t
                if age <= args.last and not seen(sym, df.index[t]):
                    removed.append((sym, df.index[t], m, age))
            for t, m in new:
                age = n - 1 - t
                if age <= args.last and not seen(sym, df.index[t]) and m in kept:
                    kept[m].append((sym, df.index[t], m, age))
        except Exception as ex:  # noqa: BLE001
            print(f"[uyarı] {sym}: {ex}", file=sys.stderr)
    rnd = random.Random(args.seed)
    q_rem = round(args.n * 0.20)
    q = {"Düşen": round(args.n * 0.34), "Yatay": round(args.n * 0.26)}
    q["Kutu"] = args.n - q_rem - q["Düşen"] - q["Yatay"]
    pick = [("SİLİNEN", x) for x in spread(removed, q_rem, rnd)]
    used = set()
    for m in ("Düşen", "Yatay", "Kutu"):
        got = spread(kept[m], q[m], rnd)
        used.update(id(x) for x in got)
        pick += [(f"KALAN-{m}", x) for x in got]
    short = args.n - len(pick)
    if short > 0:  # bir grup yetmediyse kalan havuzlardan tamamla
        rest = [x for m in kept for x in kept[m] if id(x) not in used]
        pick += [("KALAN-ek", x) for x in spread(rest, short, rnd)]
    rnd.shuffle(pick)
    span = f"{args.last} mum"
    head = (f"🎲 Kör örnek v2 ({len(pick)} etiket, son {span}). Havuz: silinen {len(removed)}, kalan Düşen {len(kept['Düşen'])}, "
            f"Yatay {len(kept['Yatay'])}, Kutu {len(kept['Kutu'])}.\n"
            "Her biri için grafiği aç, o tarihteki etikete bak ve D (doğru daralma) / Y (yanlış) yaz; emin değilsen ?. "
            "Yanlışsa kısa nedenini de yaz (volatil / çizgi yanlış / erken / aşağı giderken / yanlış mod). Anahtar sonraki mesajda.")
    lines = [f"{i}. {s} {d:%d.%m.%Y}  {link(s)}" for i, (_, (s, d, _m, _a)) in enumerate(pick, 1)]
    send(head + "\n\n" + "\n".join(lines), args.telegram)
    key = ["🔑 ANAHTAR (D/Y yazdıktan sonra aç):"]
    key += [f"{i}. {s} {d:%Y-%m-%d} → {g} ({m})" for i, (g, (s, d, m, _a)) in enumerate(pick, 1)]
    send("\n".join(key), args.telegram)


if __name__ == "__main__":
    sys.exit(main())

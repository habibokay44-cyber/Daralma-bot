"""Yeni iki Düşen kuralının (shrinkMinD=0.50, dnBelowSlope=0.0) 'yan etkisini' gösterir.

Bilinen örnekler dışında bu kurallar hangi etiketleri siliyor / ekliyor? Senin gözünle bakman için liste çıkarır.
Silinen etiketlerin çoğu gerçekten yanlışsa kural iyi; çoğu doğru daralmaysa kural zararlı.
Karşılaştırma: ADAY ayar (CAND) ve CAND + iki kural. Etiket = iptal olmamış 'setup' olayı; eşleşme ±3 mum.
Çalıştırma: python kural_kontrol.py --telegram
"""
from __future__ import annotations

import argparse
import sys
import time
from dataclasses import replace

from fd_core import Params, run
from gecmis_tara import CAND
from scan import fetch_tv_all, get_tickers, link, telegram_send

TOL = 3
LAST = 150          # son kaç mumdaki farklar listelensin
MAXLIST = 45

NEW = dict(shrinkMinD=0.50, dnBelowSlope=0.0)
ONLY_R = dict(shrinkMinD=0.50)
ONLY_E = dict(dnBelowSlope=0.0)


def live(res) -> list[tuple[int, str]]:
    return [(e["t"], e["mode"]) for e in res.events if e["type"] == "setup" and not e.get("cancelled")]


def diff(a: list[tuple[int, str]], b: list[tuple[int, str]]) -> list[tuple[int, str]]:
    """a'da olup b'de ±TOL içinde karşılığı olmayanlar."""
    bt = [t for t, _ in b]
    return [(t, m) for t, m in a if not any(abs(t - u) <= TOL for u in bt)]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--telegram", action="store_true")
    args = ap.parse_args()
    frames = fetch_tv_all(get_tickers(), n_bars=1500, budget=30 * 60)
    base_n = new_n = 0
    removed_all, added_all = [], []
    for sym, df in frames.items():
        try:
            n = len(df)
            b = live(run(df, replace(Params(), **CAND)))
            w = live(run(df, replace(Params(), **{**CAND, **NEW})))
            r_ = live(run(df, replace(Params(), **{**CAND, **ONLY_R})))
            e_ = live(run(df, replace(Params(), **{**CAND, **ONLY_E})))
            base_n += len(b)
            new_n += len(w)
            rem = diff(b, w)
            add = diff(w, b)
            remR = {t for t, _ in diff(b, r_)}
            remE = {t for t, _ in diff(b, e_)}
            for t, m in rem:
                tag = ("r" if t in remR else "") + ("e" if t in remE else "")
                removed_all.append((df.index[t], sym, m, tag or "bileşik", n - 1 - t))
            for t, m in add:
                added_all.append((df.index[t], sym, m, n - 1 - t))
        except Exception as ex:  # noqa: BLE001
            print(f"[uyarı] {sym}: {ex}", file=sys.stderr)
    rec_rem = sorted([x for x in removed_all if x[4] <= LAST], key=lambda x: x[0], reverse=True)
    rec_add = sorted([x for x in added_all if x[3] <= LAST], key=lambda x: x[0], reverse=True)
    head = (f"🔎 Yeni kuralların yan etkisi (tüm geçmiş): etiket {base_n} → {new_n}; silinen {len(removed_all)}, eklenen {len(added_all)}.\n"
            f"Son {LAST} mumda silinen {len(rec_rem)}, eklenen {len(rec_add)}.\n"
            "Silinenlere bak: çoğu gerçekten YANLIŞ etiketse kural iyi, çoğu DOĞRU daralmaysa kural zararlı. (r = sıkışma oranı kuralı, e = EMA21 altı kuralı)")
    lines = ["SİLİNEN (son etiketler):"]
    lines += [f"• {s} {d:%d.%m.%Y} {m} [{tag}]  {link(s)}" for d, s, m, tag, _ in rec_rem[:MAXLIST]]
    if rec_add:
        lines += ["", "EKLENEN (kural yüzünden yeni çıkan):"]
        lines += [f"• {s} {d:%d.%m.%Y} {m}  {link(s)}" for d, s, m, _ in rec_add[:15]]
    txt = head + "\n\n" + "\n".join(lines)
    print(txt)
    if args.telegram:
        parts, cur = [], ""
        for line in txt.split("\n"):
            if cur and len(cur) + len(line) + 1 > 3500:
                parts.append(cur)
                cur = ""
            cur = (cur + "\n" + line) if cur else line
        parts.append(cur)
        for i, p in enumerate(parts, 1):
            telegram_send(f"({i}/{len(parts)})\n" + p[:3900])
            time.sleep(1)


if __name__ == "__main__":
    sys.exit(main())

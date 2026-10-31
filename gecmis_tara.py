"""Geçmişte 'direnç altı küçük mum kümesi' olup botun etiket koymadığı yerleri bulur.

Amaç: yeni örnek beklemeden, tüm hisselerin geçmişinden aday daralma pencereleri çıkarmak.
Sen grafikte bakıp "doğru / yanlış" dersin, ben bunları calibrate.py örneklerine eklerim.
Hiçbir ayarı değiştirmez, sadece liste üretir.

Çalıştırma: python gecmis_tara.py --telegram
"""
from __future__ import annotations

import argparse
import random
import sys
import time
from dataclasses import replace

import numpy as np
import pandas as pd

from fd_core import Params, run
from scan import fetch_tv_all, get_tickers, telegram_send, link

# calibrate.py ile aynı aday ayar
CAND = dict(minClD=2, emaBelowMax=0.5, useShort=False, rallyU=0.9, rallyDd=2.0, bodyFrac=0.17, allowFlat=True, minTb=3)

W = 6            # pencere (mum)
BB_MAX = 1.1     # gövde kutusu / ADR üst sınırı
HB_MAX = 2.0     # fitilli kutu / ADR üst sınırı
RNG_MAX = 2.0    # tek mum aralığı / ADR üst sınırı (volatil mum yok)
DOWN_MAX = 4     # penceredeki art arda düşen kapanış üst sınırı
NEAR = 0.4       # kapanış dirence en fazla bu kadar ADR uzakta
LOOK = 10        # kırılım aranan ileri mum sayısı
TOL = 4          # etiket yakınlık toleransı (mum)
SPAN = 500       # liste için son kaç mum taranır (örnek testinde tüm geçmiş)
GAP = 20         # aynı hissede iki aday arası en az mum


def candidates(sym: str, df: pd.DataFrame, skip_labeled: bool = True, span: int = SPAN) -> list[dict]:
    res = run(df, replace(Params(), **CAND))
    S = res.S
    n = res.n
    live = [e["t"] for e in res.events if e["type"] == "setup" and not e.get("cancelled")]
    o, h, l, c, adr = (np.asarray(x, dtype=float) for x in (S.o, S.h, S.l, S.c, S.adr))
    bt, bl = np.maximum(o, c), np.minimum(o, c)
    out: list[dict] = []
    last_i = -99
    for i in range(max(60, n - span), n):
        a = adr[i]
        if not (a == a) or a <= 0:
            continue
        s = i - W + 1
        hiB, loB = bt[s:i + 1].max(), bl[s:i + 1].min()
        hiH, loL = h[s:i + 1].max(), l[s:i + 1].min()
        if loB <= 0 or loL <= 0:
            continue
        bb = (hiB / loB - 1) * 100 / a
        hb = (hiH / loL - 1) * 100 / a
        if bb > BB_MAX or hb > HB_MAX:
            continue
        rng = ((h[s:i + 1] - l[s:i + 1]) / c[s:i + 1] * 100 / a).max()
        if rng > RNG_MAX:
            continue
        dn = run_down = 0
        for k in range(s + 1, i + 1):
            run_down = run_down + 1 if c[k] < c[k - 1] else 0
            dn = max(dn, run_down)
        if dn >= DOWN_MAX:
            continue
        if (hiH - c[i]) * 100 / c[i] / a > NEAR:     # kapanış dirençten uzak
            continue
        if skip_labeled and any(abs(t - j) <= TOL for t in live for j in range(s, i + 1)):
            continue                                  # bot zaten etiket koymuş
        if i - last_i < (GAP if skip_labeled else W):  # ardışık pencereleri tek aday say
            continue
        last_i = i
        nxt = c[i + 1:i + 1 + LOOK]
        brk = bool(len(nxt) and nxt.max() > hiH * (1 + 0.5 * a / 100))
        out.append(dict(sym=sym, a=df.index[s], b=df.index[i], bb=bb, hb=hb, res=hiH, brk=brk,
                        recent=(n - i) <= LOOK))
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--telegram", action="store_true")
    ap.add_argument("--n", type=int, default=40, help="listelenecek aday sayısı")
    args = ap.parse_args()

    tickers = get_tickers()
    frames = fetch_tv_all(tickers, n_bars=1500, budget=30 * 60)
    # kendi kendini sına: filtre bilinen örnekleri ne kadar yakalıyor (etiket şartı olmadan, tüm geçmiş)
    from calibrate import EXAMPLES
    tp = fp = npos = nneg = 0
    for sym, a, b, expect, _note in EXAMPLES:
        df = frames.get(sym)
        if df is None:
            continue
        ta, tb = pd.Timestamp(a) - pd.Timedelta(days=4), pd.Timestamp(b) + pd.Timedelta(days=4)
        try:
            hit = any(x["b"] >= ta and x["a"] <= tb for x in candidates(sym, df, skip_labeled=False, span=len(df)))
        except Exception:  # noqa: BLE001
            continue
        if expect:
            npos += 1
            tp += int(hit)
        else:
            nneg += 1
            fp += int(hit)
    selftest = f"Filtre sınaması: doğru örneklerin {tp}/{npos}'ini, yanlış örneklerin {fp}/{nneg}'ini aday sayıyor."
    print(selftest)
    allc: list[dict] = []
    for sym, df in frames.items():
        try:
            allc += candidates(sym, df)
        except Exception as e:  # noqa: BLE001
            print(f"[uyarı] {sym}: {e}", file=sys.stderr)
    # tamamlanmış adaylar (sonrası görülebilen); yeni olanlar kırılım bilinmediği için ayrı sayılır
    done = [x for x in allc if not x["recent"]]
    rnd = random.Random(7)
    yes = [x for x in done if x["brk"]]
    no = [x for x in done if not x["brk"]]
    rnd.shuffle(yes)
    rnd.shuffle(no)
    k = args.n
    pick = sorted(yes[: k * 2 // 3] + no[: k - k * 2 // 3], key=lambda x: (x["sym"], x["a"]))
    head = (f"🔎 Geçmiş tarama: {len(frames)} hisse, botun etiket koymadığı {len(allc)} aday pencere "
            f"({len(yes)} tanesinde sonradan kırılım var, {len(no)} tanesinde yok).\n"
            f"{selftest}\n"
            f"Rastgele {len(pick)} tanesi aşağıda. Grafikte bak, her biri için doğru/yanlış yaz.")
    lines = [f"• {x['sym']} {x['a']:%d.%m.%Y}–{x['b']:%d.%m.%Y} bb{x['bb']:.2f} hb{x['hb']:.2f} "
             f"direnç~{x['res']:.2f} kırılım:{'E' if x['brk'] else 'H'}  {link(x['sym'])}" for x in pick]
    out = head + "\n" + "\n".join(lines)
    print(out)
    if args.telegram:
        parts, cur = [], ""
        for line in out.split("\n"):
            if cur and len(cur) + len(line) + 1 > 3500:
                parts.append(cur)
                cur = ""
            cur = (cur + "\n" + line) if cur else line
        if cur:
            parts.append(cur)
        for i, p in enumerate(parts, 1):
            telegram_send(f"({i}/{len(parts)})\n" + p[:3900])
            time.sleep(1)


if __name__ == "__main__":
    sys.exit(main())

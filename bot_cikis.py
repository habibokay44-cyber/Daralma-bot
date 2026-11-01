"""Bot girişlerinde ÇIKIŞ kuralları ve PİYASA FİLTRESİ karşılaştırması (4-5 bin gerçek giriş üzerinde).

Giriş: botun 'giris' olayı (kapanış), stop = o mumun dibi (R birimi). Çıkış varyantları:
  2R, 3R        : sabit hedef, süre 30
  BE+3R         : +1R görülünce stop girişe çekilir, hedef 3R, süre 30
  Iz5           : +1R görülünce stop son 5 mumun dibini izler, hedef yok, süre 40
  Sure10        : 2R hedef, süre 10
  SMC           : botun kendi hedefi, süre 30
Piyasa filtresi (girişte, nedensel): genişlik = hisselerin kaçı SMA50 üstünde (3 dilim, dilimler girişlerin dağılımından),
ve XU100 kapanış > EMA50 (varsa).
Kabul ölçütü (sonuçtan önce): bir varyant/filtre ancak ortalama R'yi tabana göre ≥2 hata payı artırır VE yarı-yarıya bölünmüş
iki dönemin (H1/H2) ikisinde de tabandan iyiyse 'gerçek' sayılır. Brüt, komisyonsuz.
Çalıştırma: python bot_cikis.py --telegram
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import replace

import numpy as np
import pandas as pd

from fd_core import Params, run
from gecmis_tara import CAND
from scan import fetch_tv_all, get_tickers, telegram_send


def xit(o, h, l, c, t, tp, hold, be=False, trail=0):
    e, sl = c[t], l[t]
    R = e - sl
    if R <= 0:
        return None
    s = sl
    for k in range(t + 1, t + 1 + hold):
        if o[k] <= s:
            return (o[k] - e) / R
        if tp and o[k] >= tp:
            return (o[k] - e) / R
        if l[k] <= s:
            return (s - e) / R
        if tp and h[k] >= tp:
            return (tp - e) / R
        if (be or trail) and (s > sl or h[k] >= e + R):
            s = max(s, e)
            if trail:
                s = max(s, float(l[max(t + 1, k - trail + 1):k + 1].min()))
    return (c[t + hold] - e) / R


VARS = ["2R", "3R", "BE+3R", "Iz5", "Sure10", "SMC"]


def all_exits(o, h, l, c, t, smc):
    e, R = c[t], c[t] - l[t]
    return {
        "2R": xit(o, h, l, c, t, e + 2 * R, 30),
        "3R": xit(o, h, l, c, t, e + 3 * R, 30),
        "BE+3R": xit(o, h, l, c, t, e + 3 * R, 30, be=True),
        "Iz5": xit(o, h, l, c, t, 0, 40, trail=5),
        "Sure10": xit(o, h, l, c, t, e + 2 * R, 10),
        "SMC": xit(o, h, l, c, t, smc, 30),
    }


def fmt(rows, base=None):
    """rows: list of (date, R). Döner metin; base verilirse H1/H2 ve tabana göre fark da gösterilir."""
    if not rows:
        return "n 0"
    rows = sorted(rows, key=lambda x: x[0])
    a = np.array([r for _, r in rows], float)
    g, ls = a[a > 0].sum(), -a[a < 0].sum()
    pf = g / ls if ls > 0 else float("inf")
    se = a.std() / np.sqrt(len(a))
    m = len(a) // 2
    h1, h2 = a[:m].mean() if m else np.nan, a[m:].mean()
    return f"n{len(a)} R{a.mean():+.2f}±{se:.2f} ({h1:+.2f}/{h2:+.2f}) PF{pf:.2f} kaz%{(a > 0).mean() * 100:.0f}"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--telegram", action="store_true")
    args = ap.parse_args()
    frames = fetch_tv_all(get_tickers(), n_bars=1500, budget=30 * 60)
    try:
        xu = fetch_tv_all(["XU100"], n_bars=1500, budget=120).get("XU100")
    except SystemExit:
        xu = None
    flags = {}
    for sym, df in frames.items():
        cl = df["Close"].astype(float)
        flags[sym] = (cl > cl.rolling(50).mean()).where(cl.rolling(50).mean().notna())
    breadth = pd.DataFrame(flags).mean(axis=1, skipna=True).sort_index()
    xtrend = None
    if xu is not None:
        xc = xu["Close"].astype(float)
        xtrend = (xc > xc.ewm(span=50, adjust=False).mean()).sort_index()
    ev = []   # (date, breadth, xu_up, {var: R})
    for sym, df in frames.items():
        try:
            o, h, l, c = (df[k].to_numpy(float) for k in ("Open", "High", "Low", "Close"))
            n = len(c)
            res = run(df, replace(Params(), **CAND))
            for e in res.events:
                t = e["t"]
                if e["type"] != "giris" or t < 80 or t > n - 45:
                    continue
                d = df.index[t]
                r = all_exits(o, h, l, c, t, e["tp"])
                if any(v is None for v in r.values()):
                    continue
                b = breadth.asof(d)
                xt = None if xtrend is None else bool(xtrend.asof(d)) if d >= xtrend.index[0] else None
                ev.append((d, b, xt, r))
        except Exception as ex:  # noqa: BLE001
            print(f"[uyarı] {sym}: {ex}", file=sys.stderr)
    bs = np.array([b for _, b, _, _ in ev if b == b])
    q1, q2 = np.quantile(bs, [1 / 3, 2 / 3])
    out = [f"🚪 Çıkış ve piyasa filtresi (bot girişleri, brüt). Parantez: (ilk yarı/ikinci yarı)",
           f"Genişlik (SMA50 üstü hisse oranı) dilimleri: <{q1:.2f}, {q1:.2f}-{q2:.2f}, >{q2:.2f}"]
    segs = [("TÜMÜ", lambda b, x: True), ("geniş.düşük", lambda b, x: b == b and b < q1),
            ("geniş.orta", lambda b, x: b == b and q1 <= b < q2), ("geniş.yüksek", lambda b, x: b == b and b >= q2)]
    if xtrend is not None:
        segs += [("XU100>EMA50", lambda b, x: x is True), ("XU100<EMA50", lambda b, x: x is False)]
    for v in VARS:
        out.append(f"— {v}")
        for nm, f in segs:
            rows = [(d, r[v]) for d, b, x, r in ev if f(b, x)]
            out.append(f"  {nm:12}: {fmt(rows)}")
    txt = "\n".join(out)
    print(txt)
    if args.telegram:
        parts, cur = [], ""
        for line in txt.split("\n"):
            if cur and len(cur) + len(line) + 1 > 3500:
                parts.append(cur)
                cur = ""
            cur = (cur + "\n" + line) if cur else line
        parts.append(cur)
        for p in parts:
            telegram_send(p[:3900])


if __name__ == "__main__":
    sys.exit(main())

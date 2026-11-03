"""Uyarı notu ölçümü. Hiçbir ayarı değiştirmez, sadece ölçüp Telegram'a yazar.

Soru: ADAY etiketi çıkan örneklerde (doğru ve yanlış), önceden yazılmış 4 uyarı kuralı
yanlışları doğrulardan ayırıyor mu?

ÖNCEDEN YAZILMIŞ KURALLAR (sonuca bakmadan sabitlendi):
  U1 fitilli   : son 5 mumda en büyük mum aralığı (mx) >= 1.5 ADR
  U2 geniş     : son 7 mumun fitilli kutusu (h7) >= 2.0 ADR
  U3 çift altı : fiyat EMA21 altında (ed < 0) VE EMA50 altında (e50 < 0)
  U4 düşüş     : son 5 mumdan en az 3'ü kırmızı (kr >= 3)
KABUL ÖLÇÜTÜ (bir kural ancak üçü birden sağlanırsa uyarıya girer):
  a) uyarılılarda yanlış oranı, uyarısızlardakinin en az 2 katı
  b) yanlışların en az %30'u uyarılı
  c) doğruların en fazla %40'ı uyarılı
  d) örnekleri çift/tek sırayla ikiye bölünce (a) iki yarıda da sağlanır
Çalıştırma: python uyari_olc.py --telegram
"""
from __future__ import annotations

import sys
import time
from dataclasses import replace

import numpy as np
import pandas as pd

import calibrate as C
from fd_core import Params, run
from scan import fetch_tv_all, telegram_send

RULES = {
    "U1 fitilli (mx>=1.5)": lambda f: f["mx"] >= 1.5,
    "U2 geniş (h7>=2.0)": lambda f: f["h7"] >= 2.0,
    "U3 çift altı (ed<0 & e50<0)": lambda f: f["ed"] < 0 and f["e50"] < 0,
    "U4 düşüş (kr>=3)": lambda f: f["kr"] >= 3,
}
INFO = ["mx", "mb", "h7", "b7", "e50", "ed", "es", "dd", "kr", "lc", "adr", "rg"]


def feats(df, res, e):
    t = e["t"]
    S = res.S
    w0 = max(t - 4, 0)
    w7 = slice(max(t - 6, 0), t + 1)
    cs = list(df["Close"].iloc[max(t - 5, 0):t + 1])
    os_ = list(df["Open"].iloc[max(t - 4, 0):t + 1])
    f = dict(
        mx=float(max(S.candRng[w0:t + 1])),
        h7=float((S.h[w7].max() / S.l[w7].min() - 1) * 100 / S.adr[t]),
        b7=0.0,
        e50=float(e.get("e50", S.e50d[t])),
        ed=float(e.get("ed", S.emaDist[t])),
        es=float(e.get("es", S.emaSlope[t])),
        dd=float(e.get("dd", S.dd40[t])),
        kr=sum(1 for o, c in zip(os_, cs[-len(os_):]) if c < o),
        lc=sum(1 for i in range(1, len(cs)) if cs[i] < cs[i - 1]),
        adr=float(S.adr[t]),
        rg=float(S.tightVal[t] * S.adr[t]),
    )
    bt = np.maximum(S.o, S.c)[w7]
    bl = np.minimum(S.o, S.c)[w7]
    f["b7"] = float((bt.max() / bl.min() - 1) * 100 / S.adr[t])
    f["mb"] = max(abs(float(df["Close"].iloc[i]) - float(df["Open"].iloc[i])) / float(df["Close"].iloc[i]) * 100 / float(S.adr[t])
                  for i in range(w0, t + 1))
    return f


def auc(pos, neg):
    if not pos or not neg:
        return float("nan")
    s = 0.0
    for p in pos:
        for n in neg:
            s += 1.0 if p > n else 0.5 if p == n else 0.0
    return s / (len(pos) * len(neg))


def collect(frames):
    P = replace(Params(), **C.CAND)
    rows = []
    for k, (sym, a, b, expect, _note) in enumerate(C.EXAMPLES):
        df = frames.get(sym)
        if df is None:
            continue
        try:
            res = run(df, C.fitP(df, P))
        except Exception:  # noqa: BLE001
            continue
        ta, tb = pd.Timestamp(a), pd.Timestamp(b)
        tol = pd.Timedelta(days=4 if expect else 0)
        live = [e for e in res.events if e["type"] == "setup" and not e.get("cancelled") and ta - tol <= e["date"] <= tb + tol]
        if not live:
            continue
        e = live[0]
        f = feats(df, res, e)
        f.update(tag=f"{sym}{a[5:7]}{a[8:]}", ok=bool(expect), k=k)
        rows.append(f)
    return rows


def rate(rows, rule):
    fl = [r for r in rows if rule(r)]
    un = [r for r in rows if not rule(r)]
    wf = sum(1 for r in fl if not r["ok"])
    wu = sum(1 for r in un if not r["ok"])
    return fl, un, wf, wu


def report(rows):
    good = [r for r in rows if r["ok"]]
    bad = [r for r in rows if not r["ok"]]
    out = [f"🧪 Uyarı ölçümü: ADAY etiketli {len(rows)} örnek (doğru {len(good)}, yanlış {len(bad)}; taban oranı yanlış %{100 * len(bad) / max(len(rows), 1):.0f})\n"]
    out.append("Kurallar (önceden yazılı):")
    for name, rule in RULES.items():
        fl, un, wf, wu = rate(rows, rule)
        if not fl or not un:
            out.append(f"• {name}: uyarılı {len(fl)}, uyarısız {len(un)} -> ölçülemez")
            continue
        rf, ru = wf / len(fl), wu / len(un)
        a_ = ru == 0 and rf > 0 or (ru > 0 and rf >= 2 * ru)
        b_ = wf >= 0.3 * len(bad)
        c_ = (len(fl) - wf) <= 0.4 * len(good)
        halves = []
        for h in (0, 1):
            sub = [r for r in rows if r["k"] % 2 == h]
            f2, u2, w2f, w2u = rate(sub, rule)
            if f2 and u2:
                r1, r2 = w2f / len(f2), w2u / len(u2)
                halves.append(r2 == 0 and r1 > 0 or (r2 > 0 and r1 >= 2 * r2))
            else:
                halves.append(False)
        d_ = all(halves)
        verdict = "✅ KABUL" if (a_ and b_ and c_ and d_) else "❌ red"
        out.append(f"• {name}: uyarılı {len(fl)} (yanlış %{100 * rf:.0f}), uyarısız {len(un)} (yanlış %{100 * ru:.0f}) | "
                   f"yanlışların %{100 * wf / max(len(bad), 1):.0f}'i, doğruların %{100 * (len(fl) - wf) / max(len(good), 1):.0f}'i uyarılı | "
                   f"a{'✓' if a_ else '✗'} b{'✓' if b_ else '✗'} c{'✓' if c_ else '✗'} d{'✓' if d_ else '✗'} -> {verdict}")
    out.append("\nBilgi için AUC (0.5 = ayırt etmez; yanlış-yüksek ise >0.5). 12 ölçü bakıldı, çoklu karşılaştırma var, 0.65 altını yok say:")
    aucs = []
    for k in INFO:
        aucs.append((auc([r[k] for r in bad], [r[k] for r in good]), k))
    out.append(" ".join(f"{k} {v:.2f}" for v, k in sorted(aucs, reverse=True)))
    out.append("\nYanlışların değerleri:")
    for r in bad:
        out.append(f"  {r['tag']}: mx{r['mx']:.2f} h7 {r['h7']:.2f} ed{r['ed']:+.2f} e50{r['e50']:+.1f} kr{r['kr']}")
    return "\n".join(out)


def main():
    syms = sorted({e[0] for e in C.EXAMPLES})
    frames = fetch_tv_all(syms, n_bars=1800, budget=15 * 60)
    for _ in range(3):
        miss = [s for s in syms if s not in frames]
        if not miss:
            break
        time.sleep(3)
        frames.update(fetch_tv_all(miss, n_bars=1800, budget=5 * 60))
    txt = report(collect(frames))
    print(txt)
    if "--telegram" in sys.argv:
        for i in range(0, len(txt), 3500):
            telegram_send(txt[i:i + 3500])
            time.sleep(1)


if __name__ == "__main__":
    main()

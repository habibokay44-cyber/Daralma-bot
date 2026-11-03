"""Uyarı ölçümü 2: bizim daha önce denemediğimiz 5 fikir. Hiçbir ayarı değiştirmez, sadece ölçüp Telegram'a yazar.

ÖNCEDEN YAZILMIŞ KURALLAR (sonuca bakmadan sabitlendi, 03.11.2026):
  F1 hacim     : son 5 mum ort. hacim / önceki 20 mum ort. hacim >= 1.0  (hacim kurumamış)
  F2 baskı     : son 5 mumda tepesi çizginin 0.5 ADR yakınına gelen mum sayısı <= 1
  F3 giriş     : (C[t-5] / C[t-15] - 1) / ADR <= -2.0  (kümeye düşüşle gelinmiş)
  F4 kapanış   : son 5 mumda (C-L)/(H-L) ortalaması < 0.40  (alttan kapanış)
  Y5 onay      : etiketten sonraki 2 mumda dip, son 5 mumun dibini kırıyor  (etiket bozuldu)
KABUL (F1-F4): a) uyarılılarda yanlış oranı >= 2 x uyarısızlar  b) yanlışların >= %30'u uyarılı
               c) doğruların <= %40'ı uyarılı  d) çift/tek ikiye bölünce (a) iki yarıda da tutar
KABUL (Y5)   : a) ve d) aynı; b) bozulan yanlış >= %30  c) bozulan doğru <= %15
               e) doğruların <= %20'si o 2 günde zaten kırılım yapmış (gecikme girişi kaçırtmasın)
Çalıştırma: python uyari_olc2.py --telegram
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
from uyari_olc import auc


def line_at(df, e, k):
    """Etiket mumundan k mum önceki çizgi değeri. Düşen: çizgi başlangıç tepesinden eğim; diğerleri yatay."""
    t, ln = e["t"], float(e["line"])
    if e["mode"] != "Düşen" or int(e.get("sp", 0)) < 2:
        return ln
    xa = t - int(e["sp"]) + 1
    sl = (ln - float(df["High"].iloc[xa])) / (t - xa)
    return ln - sl * k


def feats(df, res, e):
    t = e["t"]
    adr = float(res.S.adr[t])
    H, L, Cl, V = (df[c].to_numpy(float) for c in ("High", "Low", "Close", "Volume"))
    f = {}
    v5, v20 = V[t - 4:t + 1].mean(), V[t - 24:t - 4].mean() if t >= 24 else np.nan
    f["vr"] = float(v5 / v20) if v20 and v20 == v20 and v20 > 0 else np.nan
    f["bas"] = sum(1 for k in range(5) if H[t - k] >= line_at(df, e, k) * (1 - 0.5 * adr / 100))
    f["gir"] = float((Cl[t - 5] / Cl[t - 15] - 1) * 100 / adr) if t >= 15 else np.nan
    pos = [(Cl[i] - L[i]) / (H[i] - L[i]) if H[i] > L[i] else 0.5 for i in range(t - 4, t + 1)]
    f["kp"] = float(np.mean(pos))
    if t + 2 < len(df):
        f["boz"] = bool(L[t + 1:t + 3].min() < L[t - 4:t + 1].min())
        f["erk"] = bool(max(Cl[t + 1] > line_at(df, e, -1), Cl[t + 2] > line_at(df, e, -2)))
    else:
        f["boz"] = f["erk"] = None
    if e["mode"] == "Düşen" and int(e.get("sp", 0)) >= 2:
        f["slok"] = line_at(df, e, 1) >= float(e["line"]) - 1e-9  # düşen çizgi geriye doğru yükselmeli
    else:
        f["slok"] = True
    return f


RULES = {
    "F1 hacim (vr>=1.0)": lambda f: f["vr"] == f["vr"] and f["vr"] >= 1.0,
    "F2 baskı (<=1 mum)": lambda f: f["bas"] <= 1,
    "F3 giriş (<=-2 ADR)": lambda f: f["gir"] == f["gir"] and f["gir"] <= -2.0,
    "F4 kapanış (<0.40)": lambda f: f["kp"] < 0.40,
    "Y5 onay (2 günde dip kırıldı)": lambda f: bool(f["boz"]),
}


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
        if not live or live[0]["t"] < 25:
            continue
        f = feats(df, res, live[0])
        f.update(tag=f"{sym}{a[5:7]}{a[8:]}", ok=bool(expect), k=k, mode=live[0]["mode"])
        rows.append(f)
    return rows


def split_ok(rows, rule):
    res = []
    for h in (0, 1):
        sub = [r for r in rows if r["k"] % 2 == h]
        fl = [r for r in sub if rule(r)]
        un = [r for r in sub if not rule(r)]
        if not fl or not un:
            res.append(False)
            continue
        rf = sum(1 for r in fl if not r["ok"]) / len(fl)
        ru = sum(1 for r in un if not r["ok"]) / len(un)
        res.append((ru == 0 and rf > 0) or (ru > 0 and rf >= 2 * ru))
    return all(res)


def report(rows):
    good = [r for r in rows if r["ok"]]
    bad = [r for r in rows if not r["ok"]]
    out = [f"🧪 Uyarı ölçümü 2: ADAY etiketli {len(rows)} örnek (doğru {len(good)}, yanlış {len(bad)})"]
    nslb = sum(1 for r in rows if not r["slok"])
    if nslb:
        out.append(f"ℹ️ {nslb} örnekte çizgi eğimi geri hesaplanamadı (F2 o örneklerde yaklaşık)")
    out.append("")
    for name, rule in RULES.items():
        rr = rows
        if name.startswith("Y5"):
            rr = [r for r in rows if r["boz"] is not None]
        g = [r for r in rr if r["ok"]]
        b = [r for r in rr if not r["ok"]]
        fl = [r for r in rr if rule(r)]
        un = [r for r in rr if not rule(r)]
        if not fl or not un:
            out.append(f"• {name}: uyarılı {len(fl)}, uyarısız {len(un)} -> ölçülemez")
            continue
        wf = sum(1 for r in fl if not r["ok"])
        wu = sum(1 for r in un if not r["ok"])
        rf, ru = wf / len(fl), wu / len(un)
        a_ = (ru == 0 and rf > 0) or (ru > 0 and rf >= 2 * ru)
        pb = wf / max(len(b), 1)
        pg = (len(fl) - wf) / max(len(g), 1)
        d_ = split_ok(rr, rule)
        if name.startswith("Y5"):
            b_, c_ = pb >= 0.30, pg <= 0.15
            erk = sum(1 for r in g if r["erk"]) / max(len(g), 1)
            e_ = erk <= 0.20
            ok_ = a_ and b_ and c_ and d_ and e_
            extra = f" e{'✓' if e_ else '✗'}(erken kırılım doğruların %{100 * erk:.0f}'i)"
        else:
            b_, c_ = pb >= 0.30, pg <= 0.40
            ok_ = a_ and b_ and c_ and d_
            extra = ""
        out.append(f"• {name}: uyarılı {len(fl)} (yanlış %{100 * rf:.0f}), uyarısız {len(un)} (yanlış %{100 * ru:.0f}) | "
                   f"yanlışların %{100 * pb:.0f}'i, doğruların %{100 * pg:.0f}'i uyarılı | "
                   f"a{'✓' if a_ else '✗'} b{'✓' if b_ else '✗'} c{'✓' if c_ else '✗'} d{'✓' if d_ else '✗'}{extra} -> "
                   f"{'✅ KABUL' if ok_ else '❌ red'}")
    out.append("\nBilgi için AUC (yanlış-yüksek >0.5; 4 ölçü, 0.65 altını yok say):")
    pairs = [("vr", 1), ("bas", -1), ("gir", -1), ("kp", -1)]
    txt = []
    for k, sgn in pairs:
        pb_ = [sgn * r[k] for r in bad if r[k] == r[k]]
        pg_ = [sgn * r[k] for r in good if r[k] == r[k]]
        txt.append(f"{k} {auc(pb_, pg_):.2f}")
    out.append(" ".join(txt) + "  (bas, gir, kp ters çevrildi: yüksek = yanlış yönü)")
    out.append("\nYanlışların değerleri:")
    for r in bad:
        out.append(f"  {r['tag']}: vr{r['vr']:.2f} bas{r['bas']} gir{r['gir']:+.1f} kp{r['kp']:.2f} boz{'+' if r['boz'] else '-'}")
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

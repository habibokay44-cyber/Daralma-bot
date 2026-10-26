#!/usr/bin/env python3
"""Kalibrasyon: senin doğru / yanlış örneklerin üzerinde göstergeyi çalıştırır.

Her örnek için verilen tarih penceresinde sinyal çıkıp çıkmadığını yazar. Çıkmadıysa
her mumun neden elendiğini (Pine'daki hata ayıklama harfleri) en yakın mumlar için gösterir.
Sonuç ekrana yazılır; --telegram ile Telegram'a da gider.

  python calibrate.py --telegram
"""
from __future__ import annotations

import argparse
import sys
import time
from dataclasses import replace

import pandas as pd

from fd_core import Params, run
from scan import fetch_tv_all, telegram_send

# (hisse, pencere başı, pencere sonu, doğru örnek mi?, not)
# Tarihler grafik görüntülerinden tahmindir; pencere yanlışsa "pencerede mum yok / fiyatlar şöyle" yazar.
EXAMPLES = [
    ("ANELE", "2026-09-08", "2026-09-18", True, "taban, küçük beyaz mum"),
    ("KLSYN", "2026-02-02", "2026-02-12", True, "kırmızı yay bölgesi"),
    ("RYSAS", "2025-04-24", "2025-05-09", True, "düşen çizgi altı daralma"),
    ("DCTTR", "2024-11-18", "2024-12-04", True, "yatay taban sonu"),
    ("DCTTR", "2024-12-26", "2025-01-17", True, "ikinci daralma"),
    ("DCTTR", "2025-04-24", "2025-05-09", True, "üçüncü daralma"),
    ("DOBUR", "2023-07-10", "2023-08-10", True, "EMA yukarı eğimli"),
    ("DOBUR", "2024-01-25", "2024-02-15", True, "ikinci doğru daralma"),
    ("DOBUR", "2023-09-25", "2023-10-15", False, "EMA düz/aşağı, çalışmayan daralma"),
    ("IEYHO", "2024-03-18", "2024-04-08", True, "direnç altı daralma"),
    ("LOGO", "2024-01-08", "2024-01-19", True, "düşen çizgi altı"),
    ("YAYLA", "2024-01-02", "2024-01-12", True, "düşen çizgi altı"),
    ("IDGYO", "2024-01-29", "2024-02-12", True, "ilk daralma"),
    ("IDGYO", "2024-03-08", "2024-03-22", True, "ikinci daralma"),
    ("BMSTL", "2024-10-21", "2024-11-11", True, "yatay direnç altı"),
    ("TKNSA", "2023-08-14", "2023-09-08", True, "yükselen üçgen"),
    ("JANTS", "2024-01-25", "2024-02-08", True, "giriş (a)"),
    ("ATAGY", "2024-01-22", "2024-02-05", True, "giriş 1"),
    ("TRCAS", "2025-05-26", "2025-06-02", True, "kırmızı ok bölgesi"),
    ("METEN", "2026-10-14", "2026-10-26", False, "düşüş trendinde V dönüşü"),
    ("BAHKM", "2026-10-05", "2026-10-23", False, "düşen siyah mumda etiket"),
]


def evaluate(sym: str, df: pd.DataFrame, a: str, b: str, expect: bool, note: str, P: Params) -> tuple[bool, str]:
    res = run(df, P)
    ta, tb = pd.Timestamp(a), pd.Timestamp(b)
    idx = [i for i, d in enumerate(df.index) if ta <= d <= tb]
    head = f"{sym} {ta:%d.%m.%Y}–{tb:%d.%m.%Y} ({'doğru örnek' if expect else 'YANLIŞ örnek'}: {note})"
    if not idx:
        return False, (f"⚠️ {head}\n  pencerede mum yok. Veri {df.index[0]:%d.%m.%Y}–{df.index[-1]:%d.%m.%Y}")
    lo = float(df["Close"].iloc[idx].min())
    hi = float(df["Close"].iloc[idx].max())
    px = f"kapanış {lo:.2f}–{hi:.2f}, {len(idx)} mum"
    sset = set(idx)
    setups = [e for e in res.events if e["type"] == "setup" and e["t"] in sset]
    live = [e for e in setups if not e.get("cancelled")]
    if expect:
        if live:
            det = ", ".join(f"{e['date']:%d.%m} {e['mode']} dt{e['dt']} v{e['v']:.1f} j{e['j']:.2f}" for e in live[:3])
            return True, f"✅ {head}\n  sinyal var: {det}  [{px}]"
        rows = []
        for i in idx:
            why = res.diag.get(i)
            if why is None:
                continue
            rows.append((len(why.split()), i, why))
        rows.sort()
        best = " | ".join(f"{df.index[i]:%d.%m} {w[:38]}" for _, i, w in rows[:4]) or "-"
        extra = (" (etiket çıkıp iptal oldu: " + ", ".join(f"{e['date']:%d.%m} {e.get('cancel_reason', '?')}" for e in setups[:3]) + ")") if setups else ""
        lo_d, hi_d = ta - pd.Timedelta(days=25), tb + pd.Timedelta(days=25)
        near = [e for e in res.events if e["type"] == "setup" and not e.get("cancelled") and lo_d <= e["date"] <= hi_d]
        nr = (" | pencere dışı yakın sinyal: " + ", ".join(f"{e['date']:%d.%m.%Y}" for e in near[:4])) if near else ""
        return False, f"❌ {head}\n  sinyal yok{extra} [{px}]{nr}\n  en yakın mumlar: {best}"
    if live:
        det = ", ".join(f"{e['date']:%d.%m} {e['mode']}" for e in live[:3])
        return False, f"⚠️ {head}\n  YANLIŞ sinyal çıkıyor: {det}  [{px}]"
    return True, f"✅ {head}\n  beklendiği gibi sinyal yok  [{px}]"


E1 = dict(emaSlopeMin=-1.5, emaBelowMax=1.5, jumpMax=0.9)
LOOSE = dict(E1, riseMaxD=1.5, riseMin=-1.0, slopeMinD=-0.8, slopeMaxD=1.2, riseMax=0.8, slopeMin=-0.5,
             slopeMax=0.9, maxCandle=1.3, minClosePos=0.0, shrink=1.0, closeBoxADR=1.5, minTcD=2, volMaxX=1.8)
VARIANTS = [
    ("mevcut", {}),
    ("EMA -1.5/-1.5 + sıçrama 0.9", E1),
    ("+ u üst 1.5, u alt -1.0", dict(E1, riseMaxD=1.5, riseMin=-1.0)),
    ("+ eğim s -0.8..1.2 (düşen)", dict(E1, slopeMinD=-0.8, slopeMaxD=1.2)),
    ("+ u ve s gevşek", dict(E1, riseMaxD=1.5, riseMin=-1.0, slopeMinD=-0.8, slopeMaxD=1.2)),
    ("+ yatay u/s gevşek", dict(E1, riseMax=0.8, riseMin=-1.0, slopeMin=-0.5, slopeMax=0.9)),
    ("+ mum c 1.3, p 0", dict(E1, maxCandle=1.3, minClosePos=0.0)),
    ("+ r 1.0, k 1.5", dict(E1, shrink=1.0, closeBoxADR=1.5)),
    ("+ dt 2", dict(E1, minTcD=2)),
    ("+ hacim 1.8", dict(E1, volMaxX=1.8)),
    ("hepsi gevşek", LOOSE),
    ("hepsi gevşek, EMA kapalı", dict(LOOSE, useEmaTr=False)),
]


def sweep(frames: dict) -> str:
    """Aynı veriyle birkaç eşik kombinasyonunu dener: kaç doğru örnek yakalandı, kaç yanlış örnekte sinyal çıktı."""
    rows = []
    for name, kw in VARIANTS:
        P = replace(Params(), **kw)
        hit = miss = bad = 0
        missed, badl = [], []
        cache: dict = {}
        for sym, a, b, expect, note in EXAMPLES:
            df = frames.get(sym)
            if df is None:
                continue
            if sym not in cache:
                cache[sym] = run(df, P)
            res = cache[sym]
            ta, tb = pd.Timestamp(a), pd.Timestamp(b)
            sset = {i for i, d in enumerate(df.index) if ta <= d <= tb}
            live = [e for e in res.events if e["type"] == "setup" and e["t"] in sset and not e.get("cancelled")]
            if expect:
                if live:
                    hit += 1
                else:
                    miss += 1
                    missed.append(f"{sym}{a[5:7]}{a[8:]}")
            elif live:
                bad += 1
                badl.append(f"{sym}{a[5:7]}{a[8:]}")
        rows.append(f"• {name}: doğru {hit}, kaçan {miss}, YANLIŞ sinyal {bad}" + (f" ({', '.join(badl)})" if badl else ""))
    return "🔬 Eşik denemesi:\n" + "\n".join(rows)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--telegram", action="store_true", help="sonucu Telegram'a da gönder")
    args = ap.parse_args()

    syms = sorted({e[0] for e in EXAMPLES})
    frames = fetch_tv_all(syms, n_bars=1800, budget=15 * 60)
    for _ in range(3):  # eksik kalanları tekrar dene
        miss = [s for s in syms if s not in frames]
        if not miss:
            break
        time.sleep(3)
        frames.update(fetch_tv_all(miss, n_bars=1800, budget=5 * 60))
    notfound = []
    for s_ in syms:
        if s_ not in frames:
            cand = ""
            try:
                from tvDatafeed import TvDatafeed
                r = TvDatafeed().search_symbol(s_[:4], "BIST") or []
                cand = ", ".join(f"{x.get('symbol')} ({str(x.get('description', ''))[:22]})" for x in r[:8])
            except Exception as e:  # noqa: BLE001
                cand = f"arama yapılamadı: {e}"
            notfound.append(f"🔎 {s_} bulunamadı. Benzer: {cand or '-'}")
    sweep_txt = sweep(frames) + ("\n" + "\n".join(notfound) if notfound else "")
    P = Params()
    lines, ok = [], 0
    for sym, a, b, expect, note in EXAMPLES:
        df = frames.get(sym)
        if df is None:
            lines.append(f"⚠️ {sym} {a}..{b}: veri alınamadı")
            continue
        good, txt = evaluate(sym, df, a, b, expect, note, P)
        ok += int(good)
        lines.append(txt)
    summary = f"🧪 Kalibrasyon: {ok}/{len(EXAMPLES)} örnek beklendiği gibi"
    out = summary + "\n\n" + sweep_txt + "\n\n" + "\n\n".join(lines)
    print(out)
    if args.telegram:
        telegram_send(out)


if __name__ == "__main__":
    sys.exit(main())

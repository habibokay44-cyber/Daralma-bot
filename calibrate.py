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

from fd_core import Params, run, summarize
from scan import fetch_tv_all, telegram_send

# (hisse, pencere başı, pencere sonu, doğru örnek mi?, not)
EXAMPLES = [
    ("ANELE", "2025-08-13", "2025-08-18", True, "taban, küçük beyaz mum"),
    ("KLSYN", "2026-02-02", "2026-02-12", True, "kırmızı yay bölgesi"),
    ("RYSAS", "2024-05-03", "2024-05-08", True, "düşen çizgi altı daralma"),
    ("DCTTR", "2025-01-02", "2025-01-15", True, "ikinci daralma"),
    ("DCTTR", "2025-04-24", "2025-05-05", True, "üçüncü daralma"),
    ("DOBUR", "2023-07-10", "2023-08-10", True, "EMA yukarı eğimli"),
    ("DOBUR", "2024-02-09", "2024-02-15", True, "ikinci doğru daralma"),
    ("DOBUR", "2023-09-25", "2023-10-15", False, "EMA düz/aşağı, çalışmayan daralma"),
    ("LOGO", "2024-01-08", "2024-01-19", True, "düşen çizgi altı"),
    ("YAYLA", "2024-01-02", "2024-01-12", True, "düşen çizgi altı"),
    ("IDGYO", "2024-02-06", "2024-02-09", True, "ilk daralma"),
    ("IDGYO", "2024-04-04", "2024-04-16", True, "ikinci daralma"),
    ("BMSTL", "2024-10-21", "2024-11-11", True, "yatay direnç altı"),
    ("TKNSA", "2023-08-14", "2023-09-08", True, "yükselen üçgen"),
    ("JANTS", "2024-02-02", "2024-02-08", True, "giriş (a)"),
    ("ATAGY", "2024-01-22", "2024-02-05", True, "giriş 1"),
    ("TRCAS", "2024-07-09", "2024-07-16", True, "kırmızı ok bölgesi"),
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
    tolD = pd.Timedelta(days=4)
    close_live = [e for e in res.events if e["type"] == "setup" and not e.get("cancelled")
                  and ta - tolD <= e["date"] <= tb + tolD]
    if expect:
        if live:
            det = ", ".join(f"{e['date']:%d.%m} {e['mode']} dt{e['dt']} v{e['v']:.1f} j{e['j']:.2f}" for e in live[:3])
            return True, f"✅ {head}\n  sinyal var: {det}  [{px}]"
        if close_live:
            det = ", ".join(f"{e['date']:%d.%m.%Y} {e['mode']}" for e in close_live[:3])
            return True, f"✅ (pencereye ±4 gün yakın) {head}\n  sinyal: {det}  [{px}]"
        rows = []
        for i in idx:
            why = res.diag.get(i)
            if why is None:
                continue
            rows.append((len(why.split()), i, why))
        rows.sort()
        best = " | ".join(f"{df.index[i]:%d.%m} {w[:150]}" for _, i, w in rows[:4]) or "-"
        extra = (" (etiket çıkıp iptal oldu: " + ", ".join(f"{e['date']:%d.%m} {e.get('cancel_reason', '?')}" for e in setups[:3]) + ")") if setups else ""
        lo_d, hi_d = ta - pd.Timedelta(days=25), tb + pd.Timedelta(days=25)
        near = []
        for e in res.events:
            if not (lo_d <= e["date"] <= hi_d):
                continue
            if e["type"] == "setup":
                st = "iptal" if e.get("cancelled") else ("giriş" if e.get("triggered") else "etiket")
                near.append(f"{e['date']:%d.%m.%Y} {e['mode']} {st}")
            elif e["type"] == "giris":
                near.append(f"{e['date']:%d.%m.%Y} GİRİŞ")
            elif e["type"] == "iptal":
                near.append(f"{e['date']:%d.%m.%Y} iptal({e.get('reason', '?')})")
        nr = ("\n  çevredeki olaylar (±25 gün): " + " | ".join(near[:8])) if near else ""
        return False, f"❌ {head}\n  sinyal yok{extra} [{px}]{nr}\n  en yakın mumlar: {best}"
    if live:
        det = ", ".join(f"{e['date']:%d.%m} {e['mode']}" for e in live[:3])
        return False, f"⚠️ {head}\n  YANLIŞ sinyal çıkıyor: {det}  [{px}]"
    return True, f"✅ {head}\n  beklendiği gibi sinyal yok  [{px}]"


COMPS = {
    "EMA": dict(emaSlopeMin=-1.5, emaBelowMax=1.5),
    "sıçrama0.9": dict(jumpMax=0.9),
    "u/s düşen": dict(riseMaxD=1.5, riseMin=-1.0, slopeMinD=-0.8, slopeMaxD=1.2),
    "u/s yatay": dict(riseMax=0.8, slopeMin=-0.5, slopeMax=0.9),
    "mum c1.3 p0": dict(maxCandle=1.3, minClosePos=0.0),
    "r1.0 k1.5": dict(shrink=1.0, closeBoxADR=1.5),
    "dt2": dict(minTcD=2),
    "hacim1.8": dict(volMaxX=1.8),
    "yatay 3/2/2": dict(minTouches=3, minClusters=2, minTb=2),
    "eğim4": dict(maxDesc=4.0),
}
VARIANTS = [
    ("mevcut", {}),
    ("eski iptal bekleme", dict(cancelClearsCooldown=False)),
    ("hepsi gevşek", {k: v for d in COMPS.values() for k, v in d.items()}),
]


def score(frames: dict, kw: dict) -> dict:
    """Bir ayar için: kaç doğru örnek yakalandı, hangi yanlışlar çıktı, etiket yoğunluğu, geriye dönük test."""
    P = replace(Params(), **kw)
    hit = 0
    missed, badl = [], []
    nlab = bars = 0
    trades: list = []
    for sym in sorted({e[0] for e in EXAMPLES}):
        df = frames.get(sym)
        if df is None:
            continue
        try:
            res = run(df, P)
        except Exception:  # noqa: BLE001
            continue
        bars += len(df)
        nlab += sum(1 for e in res.events if e["type"] == "setup" and not e.get("cancelled"))
        trades += res.trades
        for s2, a, b, expect, note in EXAMPLES:
            if s2 != sym:
                continue
            ta, tb = pd.Timestamp(a), pd.Timestamp(b)
            tolD = pd.Timedelta(days=4 if expect else 0)
            live = [e for e in res.events if e["type"] == "setup" and not e.get("cancelled")
                    and ta - tolD <= e["date"] <= tb + tolD]
            tag = f"{sym}{a[5:7]}{a[8:]}"
            if expect:
                if live:
                    hit += 1
                else:
                    missed.append(tag)
            elif live:
                badl.append(tag)
    st = summarize(trades)
    return dict(hit=hit, missed=missed, bad=badl, dens=(nlab / bars * 1000 if bars else 0.0), nlab=nlab, st=st)


def fmt(name: str, r: dict) -> str:
    st = r["st"]
    tr = (f" | işlem {st['n']} kazanma %{st['winRate']:.0f} R{st['avgR']:+.2f} PF{st['profitFactor']:.2f}"
          if st.get("n") else " | işlem 0")
    return (f"• {name}: doğru {r['hit']}/{r['hit'] + len(r['missed'])}, YANLIŞ {len(r['bad'])}"
            + (f" ({', '.join(r['bad'])})" if r["bad"] else "")
            + f" | etiket/1000 mum {r['dens']:.1f}{tr}\n    kaçan: {', '.join(r['missed']) or '-'}")


def merged(names: list[str]) -> dict:
    d: dict = {}
    for n in names:
        d.update(COMPS[n])
    return d


def sweep(frames: dict, budget: int = 40 * 60) -> str:
    """Geriye doğru eleme: hepsi gevşekken başla, doğru örnek sayısı düşmeyen ve yoğunluğu en çok azaltan gevşetmeyi çıkar."""
    t0 = time.time()
    rows = [fmt(n, score(frames, kw)) for n, kw in VARIANTS]
    active = list(COMPS)
    base = score(frames, merged(active))
    path = [f"başlangıç (hepsi gevşek): doğru {base['hit']}, yanlış {len(base['bad'])}, etiket/1000 {base['dens']:.1f}, kaçan: {', '.join(base['missed']) or '-'}"]
    while active and time.time() - t0 < budget:
        best = None
        for n in active:
            rest = [x for x in active if x != n]
            r = score(frames, merged(rest))
            if len(r["bad"]) > len(base["bad"]) or r["hit"] < base["hit"]:
                continue
            key = (r["hit"], -r["dens"])
            if best is None or key > best[0]:
                best = (key, n, rest, r)
        if best is None:
            break
        _, n, rest, r = best
        active, base = rest, r
        st = r["st"]
        pf = f" PF{st['profitFactor']:.2f} işlem {st['n']}" if st.get("n") else ""
        path.append(f"- {n} çıkarıldı: doğru {r['hit']}, yanlış {len(r['bad'])}, etiket/1000 {r['dens']:.1f}{pf}")
    contrib = []
    for n in active:
        if time.time() - t0 > budget + 600:
            break
        r = score(frames, merged([x for x in active if x != n]))
        contrib.append(f"  {n}: çıkarılırsa doğru {r['hit']} (şimdi {base['hit']}), kaçan: {', '.join(r['missed']) or '-'}, etiket/1000 {r['dens']:.1f}")
    rows.append(fmt("SEÇİLEN (" + " + ".join(active) + ")", base))
    rows.append("seçilen ayarlar: " + repr(merged(active)))
    return ("🔬 Eşik denemesi:\n" + "\n".join(rows) + "\n\n🧭 Geriye doğru eleme:\n" + "\n".join(path)
            + "\n\n🔎 Kalan gevşetmelerin katkısı:\n" + ("\n".join(contrib) or "  -"))


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
    # yeni halka arzlar: scan.py 120 mumdan kısa geçmişi eler, burada kısa olanı da al
    for s_ in syms:
        if s_ not in frames:
            try:
                from scan import _tv_df
                from tvDatafeed import TvDatafeed
                d_ = _tv_df(TvDatafeed(), s_, 1800)
                if d_ is not None and len(d_) >= 30:
                    frames[s_] = d_
                    print(f"[bilgi] {s_}: sadece {len(d_)} mum var (yeni halka arz)")
            except Exception as e:  # noqa: BLE001
                print(f"[uyarı] {s_}: {e}", file=sys.stderr)
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
        try:
            good, txt = evaluate(sym, df, a, b, expect, note, P)
        except Exception as e:  # noqa: BLE001
            lines.append(f"⚠️ {sym}: hesaplanamadı ({len(df)} mum): {e}")
            continue
        ok += int(good)
        lines.append(txt)
    summary = f"🧪 Kalibrasyon: {ok}/{len(EXAMPLES)} örnek beklendiği gibi"
    out = summary + "\n\n" + sweep_txt + "\n\n" + "\n\n".join(lines)
    print(out)
    if args.telegram:
        telegram_send(out)


if __name__ == "__main__":
    sys.exit(main())

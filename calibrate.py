#!/usr/bin/env python3
"""Kalibrasyon: senin doğru / yanlış örneklerin üzerinde göstergeyi çalıştırır.

Her örnek için verilen tarih penceresinde sinyal çıkıp çıkmadığını yazar. Çıkmadıysa
her mumun neden elendiğini (Pine'daki hata ayıklama harfleri) en yakın mumlar için gösterir.
Sonuç ekrana yazılır; --telegram ile Telegram'a da gider (uzunsa parçalanır).

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
    ("KONTR", "2020-11-24", "2020-11-30", True, "ilk daralma, turuncu düşen çizgi doğru"),
    ("KONTR", "2020-12-10", "2020-12-16", True, "ikinci daralma: MAVİ YATAY olmalı, düşen yanlış"),
    ("METEN", "2026-09-15", "2026-10-26", False, "METGUN Enerji: düşüş trendinde V dönüşü / daralma yok, direkt kırıyor"),
    ("BAHKM", "2026-10-05", "2026-10-23", False, "düşen siyah mumda etiket"),
    ("KRGYO", "2026-10-20", "2026-10-27", False, "sert çöküş sonrası sıçrama; çizgi sadece tepeden, direnç altı sıkışma yok"),
]


# bu pencerede çıkan etiket bu modda olmalı
MODE_REQ = {("DCTTR", "2025-01-02"): "Yatay", ("KONTR", "2020-12-10"): "Yatay", ("KONTR", "2020-11-24"): "Düşen"}


def fitP(df: pd.DataFrame, P: Params) -> Params:
    """Ayar aynen kullanılır."""
    return P


def mt(e: dict) -> str:
    """Etiket mumunun ölçüleri: sıkışma r/k/m, EMA21 eğim/uzaklık, 40 mum tepesinden düşüş, EMA50 uzaklık, son dip kaç mum önce."""
    return (f"[r{e.get('r', 0):.2f} k{e.get('k', 0):.2f} m{e.get('m', 0):.2f} ema{e.get('es', 0):+.2f}/{e.get('ed', 0):+.2f} tepe-{e.get('dd', 0):.1f} "
            f"e50{e.get('e50', 0):+.1f} dip{e.get('la', 0)}g sn{e.get('sn', 0):.1f}]")


def evaluate(sym: str, df: pd.DataFrame, a: str, b: str, expect: bool, note: str, P: Params) -> tuple[bool, str]:
    P = fitP(df, P)
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
        rq = MODE_REQ.get((sym, a))
        if live and rq and not any(e["mode"] == rq for e in live):
            det = ", ".join(f"{e['date']:%d.%m} {e['mode']} dt{e['dt']} cl{e.get('dcl', 0)} {mt(e)}" for e in live[:3])
            return False, f"❌ {head}\n  etiket var ama mod yanlış ({rq} olmalı): {det}  [{px}]"
        if live:
            det = ", ".join(f"{e['date']:%d.%m} {e['mode']} dt{e['dt']} cl{e.get('dcl', 0)} {mt(e)}" for e in live[:3])
            return True, f"✅ {head}\n  sinyal var: {det}  [{px}]"
        if close_live:
            det = ", ".join(f"{e['date']:%d.%m.%Y} {e['mode']} dt{e['dt']} cl{e.get('dcl', 0)} {mt(e)}" for e in close_live[:3])
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
    info = f"veri {len(df)} mum ({df.index[0]:%d.%m.%Y}–{df.index[-1]:%d.%m.%Y})"
    short = f"\n  ℹ️ geçmiş {len(df)} mum, ısınma {P.warmup}: kısa geçmişte test zayıf" if len(df) < P.warmup + 20 else ""
    if live:
        det = ", ".join(f"{e['date']:%d.%m} {e['mode']} dt{e['dt']} cl{e.get('dcl', 0)} {mt(e)}" for e in live[:6])
        return False, f"⚠️ {head}\n  YANLIŞ sinyal çıkıyor: {det}  [{px}; {info}]{short}"
    return True, f"✅ {head}\n  beklendiği gibi sinyal yok  [{px}; {info}]{short}"


# v48 (eski) varsayılanlar: yeni varsayılanlarla karşılaştırmak için
OLD = dict(emaSlopeMin=-0.2, emaBelowMax=0.5, riseMaxD=1.0, riseMin=-0.4, slopeMinD=-0.4, slopeMaxD=0.6,
           riseMax=0.4, slopeMin=-0.15, slopeMax=0.4, maxCandle=1.0, minClosePos=0.2, volMaxX=1.3,
           minTouches=4, minClusters=3, minTb=3, maxDesc=3.0, shrink=0.9, closeBoxADR=1.2, minTcD=3, jumpMax=0.6)
# yeni varsayılana giren gevşetmeler (anahtar -> eski değer geri döner)
ADOPTED = {
    "EMA": ("emaSlopeMin", "emaBelowMax"),
    "u/s düşen": ("riseMaxD", "riseMin", "slopeMinD", "slopeMaxD"),
    "u/s yatay": ("riseMax", "slopeMin", "slopeMax"),
    "mum c1.3 p0": ("maxCandle", "minClosePos"),
    "hacim1.8": ("volMaxX",),
    "yatay 3/2/2": ("minTouches", "minClusters", "minTb"),
    "eğim4": ("maxDesc",),
}
# denenip gerek görülmeyenler: yeni varsayılana ek olarak denenir
EXTRA = {
    "r1.0 k1.5": dict(shrink=1.0, closeBoxADR=1.5),
    "dt2": dict(minTcD=2),
    "sıçrama0.9": dict(jumpMax=0.9),
}
# v50: trend / sıkılaştırma varyantları
TIGHT = {
    "yatay tercih 2.0 (dönüşsüz)": dict(flatPrefer=2.0),
    "yatay tercih 2.5 (dönüşsüz)": dict(flatPrefer=2.5),
    "yatay tercih 2.0 + dönüş dt≥5": dict(flatPrefer=2.0, fallbackD=True, fbMinDt=5),
    "yatay tercih 2.0 + dönüş dt≥6": dict(flatPrefer=2.0, fallbackD=True, fbMinDt=6),
    "yatay tercih 2.0 + dönüş dt≥8": dict(flatPrefer=2.0, fallbackD=True, fbMinDt=8),
    "yatay tercih 2.5 + dönüş dt≥6": dict(flatPrefer=2.5, fallbackD=True, fbMinDt=6),
    "yatay tercih 3.0 + dönüş dt≥6": dict(flatPrefer=3.0, fallbackD=True, fbMinDt=6),
    "çizgi küme≥2": dict(minClD=2),
    "çizgi küme≥2 + yatay tercih 2.0 + dönüş dt≥6": dict(minClD=2, flatPrefer=2.0, fallbackD=True, fbMinDt=6),
    "ısınma 45": dict(warmup=45),
    "ısınma 70": dict(warmup=70),
}
VARIANTS = [
    ("YENİ varsayılan (v50)", {}),
    ("v49 (gevşek, trend filtresiz)", dict(emaSlopeMin=-1.5, emaBelowMax=1.5, ddMax=0.0)),
    ("ESKİ varsayılan (v48)", dict(OLD)),
    ("yeni, ama iptal sonrası eski bekleme", dict(cancelClearsCooldown=False)),
]
for _n, _keys in ADOPTED.items():
    VARIANTS.append((f"yeni, ama {_n} eski değerde", {k: OLD[k] for k in _keys}))
for _n, _kw in TIGHT.items():
    VARIANTS.append((f"SIKI {_n}", dict(_kw)))
for _n, _kw in EXTRA.items():
    VARIANTS.append((f"yeni + ek gevşetme {_n}", dict(_kw)))


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
            res = run(df, fitP(df, P))
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
                rq = MODE_REQ.get((sym, a))
                if live and rq and not any(e["mode"] == rq for e in live):
                    missed.append(tag + "(mod)")
                elif live:
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


def sweep(frames: dict) -> str:
    rows = [fmt(n, score(frames, kw)) for n, kw in VARIANTS]
    return "🔬 Eşik denemesi (her satır yeni varsayılandan bir şeyi değiştirir):\n" + "\n".join(rows)


def send_long(text: str) -> None:
    """Telegram 4096 karakter sınırı: boş satırlardan parçalara böl."""
    parts, cur = [], ""
    for blk in text.split("\n\n"):
        if cur and len(cur) + len(blk) + 2 > 3500:
            parts.append(cur)
            cur = ""
        cur = (cur + "\n\n" + blk) if cur else blk
    if cur:
        parts.append(cur)
    for i, p in enumerate(parts, 1):
        telegram_send(f"({i}/{len(parts)})\n" + p[:3900])
        time.sleep(1)


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
        send_long(out)


if __name__ == "__main__":
    sys.exit(main())

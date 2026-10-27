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
# Tarihler grafik görüntülerinden tahmindir; pencere yanlışsa "pencerede mum yok / fiyatlar şöyle" yazar.
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
    ("YAYLA", "2023-11-06", "2023-11-08", False, "7 Kasım: breakout mumunda etiket, daralma olamaz"),
    ("YAYLA", "2023-11-14", "2023-11-21", True, "doğru daralma (ok), çizgi ana tepeden"),
    ("IDGYO", "2024-02-06", "2024-02-09", True, "ilk daralma"),
    ("IDGYO", "2024-04-04", "2024-04-16", True, "ikinci daralma"),
    ("BMSTL", "2024-10-21", "2024-11-11", True, "yatay direnç altı"),
    ("TKNSA", "2023-08-14", "2023-09-08", True, "yükselen üçgen"),
    ("JANTS", "2024-02-02", "2024-02-08", True, "giriş (a)"),
    ("ATAGY", "2024-01-22", "2024-02-05", True, "giriş 1"),
    ("TRCAS", "2024-07-09", "2024-07-16", True, "kırmızı ok bölgesi"),
    ("KONTR", "2020-11-30", "2020-12-04", True, "ilk daralma, turuncu düşen çizgi doğru"),
    ("KONTR", "2020-12-18", "2020-12-24", True, "ikinci daralma: MAVİ YATAY olmalı"),
    ("METEN", "2026-09-15", "2026-10-26", False, "METGUN Enerji: düşüş trendinde V dönüşü"),
    ("BAHKM", "2026-10-05", "2026-10-23", False, "düşen siyah mumda etiket"),
    ("KRGYO", "2026-10-20", "2026-10-27", False, "sert çöküş sonrası sıçrama; çizgi sadece tepeden"),
    ("GMTAS", "2026-07-08", "2026-07-20", False, "temmuz: daralma yok, fiyat aşağı kayıyor"),
    ("GMTAS", "2026-08-01", "2026-08-10", False, "ağustos: çizgi doğru ama yatay savrulma, fitilli dojiler, daralma yok"),
    ("GMTAS", "2026-10-09", "2026-10-15", True, "ekim: doğru etiket (düşüşten toparlanıp çizgi altında daralma)"),
    ("BIGEN", "2026-08-03", "2026-08-11", True, "yeşil kutu: büyük beyaz mum sonrası küçük mumlar, direnç büyük mumun tepesi"),
    ("BIGEN", "2026-08-14", "2026-08-24", False, "turuncu çizgi uzak zirveden, fiyat sert yükselirken etiket, daralma yok"),
    ("KONTR", "2021-11-22", "2021-12-02", True, "yatay daralma ~2.19 altı: MAVİ YATAY olmalı (düşen çizgi yanlış)"),
    ("BAHKM", "2026-08-03", "2026-08-26", True, "ağustos: düşen çizgi altında bariz daralma, sonra yukarı kırılım (etiket olmalı)"),
    ("ATAKP", "2026-10-20", "2026-10-27", False, "kısa etiket: büyük beyaz mum sonrası daralma mumları henüz oluşmadı (1-2 küçük mum daha gerekli)"),
    ("AVHOL", "2026-06-01", "2026-10-27", False, "kısa etiket 11.08: sert yükseliş içinde, daralma yok"),
]


# bu pencerede çıkan etiket bu modda olmalı (DCTTR ocak: yatay çizgi, düşen değil)
MODE_REQ = {("DCTTR", "2025-01-02"): "Yatay", ("KONTR", "2020-12-18"): "Yatay", ("KONTR", "2020-11-30"): "Düşen", ("KONTR", "2021-11-22"): "Yatay"}

# aday varsayılan: fd_core varsayılanının üstüne uygulanır (benimsenirse fd_core ve Pine'a taşınır)
CAND = dict(minClD=2, emaBelowMax=0.5, useShort=False, rallyU=0.9, rallyDd=2.0, bodyFrac=0.18)




def fitP(df: pd.DataFrame, P: Params) -> Params:
    """Ayar aynen kullanılır."""
    return P


def mt(e: dict) -> str:
    """Etiket mumunun ölçüleri: sıkışma r/k/m, EMA21 eğim/uzaklık, tepeden düşüş, EMA50 uzaklık, son dip, çizgi eğimi, yaklaşma u, eğim s, mum c/p, gövde/aralık bf."""
    return (f"[{'KISA ' if e.get('short') else ''}r{e.get('r', 0):.2f} k{e.get('k', 0):.2f} m{e.get('m', 0):.2f} ema{e.get('es', 0):+.2f}/{e.get('ed', 0):+.2f} tepe-{e.get('dd', 0):.1f} "
            f"e50{e.get('e50', 0):+.1f} dip{e.get('la', 0)}g sn{e.get('sn', 0):.1f} u{e.get('u', 0):+.2f} s{e.get('s', 0):+.2f} c{e.get('c', 0):.2f} p{e.get('p', 0):.2f} bf{e.get('bf', 0):.2f}]")


def evaluate(sym: str, df: pd.DataFrame, a: str, b: str, expect: bool, note: str, P: Params) -> tuple[bool, str]:
    P = fitP(df, P)
    res = run(df, P)
    for e_ in res.events:  # etikete u/s/c/p/bf ölçülerini ekle (sadece gösterim için)
        if e_["type"] == "setup":
            t_ = e_["t"]
            e_["u"], e_["s"] = float(res.S.riseVal[t_]), float(res.S.slopeVal[t_])
            e_["c"], e_["p"] = float(res.S.candRng[t_]), float(res.S.closePos[t_])
            e_["bf"] = float(res.S.bodyFr[t_])
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
            det = ", ".join(f"{e['date']:%d.%m} {e['mode']} dt{e['dt']} cl{e.get('dcl', 0)} {mt(e)} {e.get('hnear', '')}" for e in live[:3])
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
        return False, f"⚠️ {head}\n  YANLIŞ sinyal çıkıyor: {det}  [{px}; {info}]"
    return True, f"✅ {head}\n  beklendiği gibi sinyal yok  [{px}; {info}]{short}"


# sıkılaştırma varyantları (hepsi CAND üstüne)
VARIANTS = [
    ("ADAY (hepsi açık)", {}),
    ("p en fazla 0.90", dict(maxClosePos=0.90)),
    ("p en fazla 0.85", dict(maxClosePos=0.85)),
    ("p en fazla 0.80", dict(maxClosePos=0.80)),
]



def score(frames: dict, kw: dict) -> dict:
    """Bir ayar için: kaç doğru örnek yakalandı, hangi yanlışlar çıktı, etiket yoğunluğu, geriye dönük test."""
    P = replace(Params(), **{**CAND, **kw})
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
    return "🔬 Eşik denemesi (her satır ADAY ayardan bir şeyi değiştirir):\n" + "\n".join(rows)


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
    P = replace(Params(), **CAND)
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

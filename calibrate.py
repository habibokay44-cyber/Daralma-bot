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

import numpy as np
import pandas as pd

from fd_core import Params, run, summarize
from scan import fetch_tv_all, telegram_send

# (hisse, pencere başı, pencere sonu, doğru örnek mi?, not)
# Tarihler grafik görüntülerinden tahmindir; pencere yanlışsa "pencerede mum yok / fiyatlar şöyle" yazar.
EXAMPLES = [
    ("ANELE", "2025-08-13", "2025-08-18", True, "taban, küçük beyaz mum"),
    ("ANELE", "2026-03-02", "2026-03-27", True, "mart: yeşil kutu: 20 mumluk taban, kırılım mumu hariç"),
    ("ANELE", "2025-07-07", "2025-07-10", False, "temmuz 2025: fiyat aşağı giderken kutu/etiket yanlış"),
    ("ANELE", "2025-07-16", "2025-07-18", True, "temmuz 2025: doğru daralma 16-18 Temmuz"),
    ("SANKO", "2026-04-24", "2026-04-29", False, "nisan 2026: daralma yok, yanlış etiket"),
    ("SANKO", "2026-10-22", "2026-10-27", False, "ekim 2026: mumlar çok volatil, daralma yok"),
    ("EMPAE", "2026-04-13", "2026-04-20", False, "daralma yok: fiyat aşağı akıyor, tek yeşil mum var; düşen çizgi etiketi yanlış"),
    ("EMPAE", "2026-04-23", "2026-05-08", True, "taban bölgesi (15 Nis-4 May): bu aralıkta etiket (Düşen veya kutu) kabul"),
    ("KLSYN", "2026-02-02", "2026-02-12", True, "kırmızı yay bölgesi"),
    ("RYSAS", "2024-05-03", "2024-05-08", True, "düşen çizgi altı daralma"),
    ("DCTTR", "2025-01-02", "2025-01-15", True, "ikinci daralma"),
    ("DCTTR", "2025-04-24", "2025-05-05", True, "üçüncü daralma"),
    ("DOBUR", "2023-07-10", "2023-08-10", True, "EMA yukarı eğimli"),
    ("DOBUR", "2024-02-09", "2024-02-13", True, "ikinci doğru daralma (9-13 Şubat yeşil kutu, uzun çizgi Aralık tepesinden)"),
    ("DOBUR", "2024-01-16", "2024-01-19", False, "ocak: kutu yanlış yerde, mumlar aşağı gelirken etiket (çizgi doğru)"),
    ("DOBUR", "2024-01-23", "2024-01-24", True, "ocak: doğru daralma kutusu 19-24 Ocak"),
    ("DOBUR", "2024-11-22", "2024-11-27", True, "kasım 2024: 20-27 Kasım yatay sıkışma, etiket hiç yok (kaçan)"),
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
    ("TUKAS", "2026-10-06", "2026-10-16", False, "etiket erken: mumlar aşağı giderken daralma yok, yatay çizgi yanlış (doğrusu ~2.03 tepelerinden)"),
    ("TUKAS", "2026-10-17", "2026-10-21", True, "doğru daralma: 15-20 Ekim yeşil kutu, ~2.03 yatay direnç altı"),
    ("TTKOM", "2026-09-28", "2026-10-06", False, "daralma yok: kutuda art arda 3 kırmızı mum, aşağı akış, kümelenme yok"),
    ("VKING", "2026-04-06", "2026-04-15", False, "ilk etiket: 7 ve 13 Nisan büyük mumları daralmayı bozuyor, çizgi yanlış"),
    ("VKING", "2026-04-27", "2026-05-08", False, "ikinci etiket: çizgi yanlış, daralma yok (doğru çizgi Mart tepesinden uzun noktalı çizgi)"),
    ("KARTN", "2026-05-08", "2026-05-14", False, "mayıs: çok volatil, büyük gövdeli al-sat mumlar, daralma değil"),
    ("KARTN", "2025-09-19", "2025-09-23", False, "eylül: düşen çizgi: temaslar peş peşe mumlarda (ilk ve ikinci temas yan yana), mesafeli değil"),
    ("HKTM", "2026-08-04", "2026-08-14", True, "yeşil kutu: düşüş sonrası taban, kırılım mumu hariç"),
    ("MARTI", "2026-08-04", "2026-08-26", True, "yeşil kutu: sert düşüş sonrası uzun yatay taban, sonra rally"),
    ("TERA", "2025-08-29", "2025-10-03", True, "noktalı düşen çizgi altında bariz daralma, sonra kırılım"),
    ("GSDDE", "2026-09-08", "2026-09-11", False, "eylül 2026: fiyat aşağı giderken daralma etiketi, çizgi uzak zirveden (kapanış ~13)"),
    ("GSDDE", "2026-01-05", "2026-01-08", False, "ocak: volatil mumlarda daralma etiketi, daralma yok"),
    ("GSDDE", "2025-09-26", "2025-09-30", False, "eylül 2025 sonu: düşüş içinde daralma etiketi (kapanış ~10.4)"),
    ("GSDDE", "2026-04-21", "2026-04-28", True, "bariz daralma: 10.87 direnci altında küçük mumlar, sonra kırılım (etiket çıkmıyor)"),
    ("BAHKM", "2026-08-17", "2026-08-24", True, "uzun düşen çizgi (19 Mart 2026 tepesinden) altında daralma, sonra kırılım"),
    ("MRGYO", "2025-05-08", "2025-05-13", True, "uzun düşen çizgi (4 Aralık 2024 tepesinden) altında daralma, sonra kırılım"),
    ("VKING", "2026-02-10", "2026-02-16", False, "şubat: çizgi peş peşe iki muma çizilmiş, daralma yok"),
    ("MRGYO", "2022-10-10", "2022-10-14", False, "ekim 2022: fiyat aşağı giderken etiket, çizgi yanlış"),
    ("MRGYO", "2022-10-17", "2022-10-18", True, "doğru daralma: 13-18 Ekim yeşil kutu, ~0.556 yatay direnç altı"),
]


# bu pencerede çıkan etiket bu modda olmalı (DCTTR ocak: yatay çizgi, düşen değil)
MODE_REQ = {("DCTTR", "2025-01-02"): "Yatay", ("KONTR", "2020-12-18"): "Yatay", ("KONTR", "2020-11-30"): "Düşen", ("KONTR", "2021-11-22"): "Yatay"}

# aday varsayılan: fd_core varsayılanının üstüne uygulanır (benimsenirse fd_core ve Pine'a taşınır)
CAND = dict(minClD=2, emaBelowMax=0.5, useShort=False, rallyU=0.9, rallyDd=2.0, bodyFrac=0.17, allowFlat=True, minTb=3)


def fitP(df: pd.DataFrame, P: Params) -> Params:
    """Ayar aynen kullanılır."""
    return P


def mt(e: dict) -> str:
    """Etiket mumunun ölçüleri: sıkışma r/k/m, EMA21 eğim/uzaklık, tepeden düşüş, EMA50 uzaklık, son dip, çizgi eğimi, yaklaşma u, eğim s, mum c/p, çizgi uzunluğu sp."""
    return (f"[{'KISA ' if e.get('short') else ''}r{e.get('r', 0):.2f} k{e.get('k', 0):.2f} m{e.get('m', 0):.2f} ema{e.get('es', 0):+.2f}/{e.get('ed', 0):+.2f} tepe-{e.get('dd', 0):.1f} "
            f"e50{e.get('e50', 0):+.1f} dip{e.get('la', 0)}g sn{e.get('sn', 0):.1f} u{e.get('u', 0):+.2f} s{e.get('s', 0):+.2f} c{e.get('c', 0):.2f} p{e.get('p', 0):.2f} bf{e.get('bf', 0):.2f} adr{e.get('adr', 0):.1f}% rg{e.get('rg', 0):.1f}% kr{e.get('kr', 0)} lc{e.get('lc', 0)} mx{e.get('mx', 0):.2f} mb{e.get('mb', 0):.2f} sp{e.get('sp', 0)} b7 {e.get('b7', 0):.2f}/{e.get('h7', 0):.2f}tp[{e.get('tpos', '')}]]")


LAST_BOX = ""


def box_line(df: pd.DataFrame, res, idx: list) -> str:
    """Kutu ölçümü: pencerede kutu gibi en sıkı gün için, son W mumun gövde kutusu (bb) ve fitilli kutusu (hb), ADR katı."""
    S = res.S
    bt = np.maximum(S.o, S.c)
    bl = np.minimum(S.o, S.c)
    parts = []
    for W in (7, 10, 15):
        hiB = pd.Series(bt).rolling(W).max().to_numpy()
        loB = pd.Series(bl).rolling(W).min().to_numpy()
        hiH = pd.Series(S.h).rolling(W).max().to_numpy()
        loL = pd.Series(S.l).rolling(W).min().to_numpy()
        bb = (hiB / loB - 1) * 100 / S.adr
        hb = (hiH / loL - 1) * 100 / S.adr
        ok = [i for i in idx if i >= W and bb[i] == bb[i]]
        if not ok:
            continue
        i = min(ok, key=lambda k: bb[k])
        parts.append(f"W{W} {df.index[i]:%d.%m} bb{bb[i]:.2f} hb{hb[i]:.2f}")
    if not parts:
        return ""
    i = idx[-1]
    ctx = f"son gün {df.index[i]:%d.%m}: ema{float(S.emaSlope[i]):+.2f}/{float(S.emaDist[i]):+.2f} tepe-{float(S.dd40[i]):.1f} e50{float(S.e50d[i]):+.1f}"
    return "  kutu ölçümü: " + " | ".join(parts) + " | " + ctx


# hata ayıklama: bu (hisse, başlangıç) örneklerinde pencere çevresi gün gün neden elendi/etiket çıktı gösterilir
DEBUG_WIN = {("SANKO", "2026-04-24"): ("2026-04-20", "2026-04-30"), ("SANKO", "2026-10-22"): ("2026-10-19", "2026-10-28")}

def evaluate(sym: str, df: pd.DataFrame, a: str, b: str, expect: bool, note: str, P: Params) -> tuple[bool, str]:
    ok_, msg_ = _evaluate(sym, df, a, b, expect, note, P)
    win_ = DEBUG_WIN.get((sym, a))
    if win_:
        P2 = fitP(df, P)
        r2 = run(df, P2)
        rows_ = []
        for i_, d_ in enumerate(df.index):
            if pd.Timestamp(win_[0]) <= d_ <= pd.Timestamp(win_[1]):
                w_ = r2.diag.get(i_)
                S_ = r2.S
                nums_ = (f"[k{S_.closeBoxVal[i_]:.2f} m{S_.tightVal[i_]:.2f} r{S_.shrinkVal[i_]:.2f} "
                         f"e{S_.emaSlope[i_]:.2f}/{S_.emaDist[i_]:.2f} adr{S_.adr[i_]:.2f} "
                         f"G{(float(df['Close'].iloc[i_]) - float(df['Open'].iloc[i_])) / float(df['Close'].iloc[i_]) * 100 / float(S_.adr[i_]):+.1f} "
                         f"H{(float(df['High'].iloc[i_]) / float(df['Low'].iloc[i_]) - 1) * 100 / float(S_.adr[i_]):.1f}]")
                rows_.append(f"{d_:%d.%m} {nums_} {(w_ or '-')[:90]}")
        evs_ = [f"{e['date']:%d.%m} {e['mode']} {'iptal:' + str(e.get('cancel_reason', '?')) if e.get('cancelled') else 'canlı'}"
                for e in r2.events if e["type"] == "setup" and pd.Timestamp(win_[0]) - pd.Timedelta(days=10) <= e["date"] <= pd.Timestamp(win_[1])]
        msg_ += "\n  🔎 etiketler: " + (", ".join(evs_) or "yok") + "\n  🔎 gün gün: " + " | ".join(rows_)
    return ok_, msg_


def _evaluate(sym: str, df: pd.DataFrame, a: str, b: str, expect: bool, note: str, P: Params) -> tuple[bool, str]:
    P = fitP(df, P)
    res = run(df, P)
    for e_ in res.events:  # etikete u/s/c/p ölçülerini ekle (sadece gösterim için)
        if e_["type"] == "setup":
            t_ = e_["t"]
            e_["u"], e_["s"] = float(res.S.riseVal[t_]), float(res.S.slopeVal[t_])
            e_["c"], e_["p"] = float(res.S.candRng[t_]), float(res.S.closePos[t_])
            e_["bf"] = float(res.S.bodyFr[t_])
            e_["adr"] = float(res.S.adr[t_])
            e_["rg"] = float(res.S.tightVal[t_] * res.S.adr[t_])
            cs_ = list(df["Close"].iloc[max(t_ - 5, 0):t_ + 1])
            os_ = list(df["Open"].iloc[max(t_ - 4, 0):t_ + 1])
            e_["kr"] = sum(1 for o_, c_ in zip(os_, cs_[-len(os_):]) if c_ < o_)
            e_["lc"] = sum(1 for i_ in range(1, len(cs_)) if cs_[i_] < cs_[i_ - 1])
            w0_ = max(t_ - 4, 0)
            e_["mx"] = float(max(res.S.candRng[w0_:t_ + 1]))
            w7_ = slice(max(t_ - 6, 0), t_ + 1)
            bt7_ = np.maximum(res.S.o, res.S.c)[w7_]
            bl7_ = np.minimum(res.S.o, res.S.c)[w7_]
            e_["b7"] = float((bt7_.max() / bl7_.min() - 1) * 100 / res.S.adr[t_])
            e_["h7"] = float((res.S.h[w7_].max() / res.S.l[w7_].min() - 1) * 100 / res.S.adr[t_])
            e_["mb"] = max(abs(float(df["Close"].iloc[i_]) - float(df["Open"].iloc[i_])) / float(df["Close"].iloc[i_]) * 100 / float(res.S.adr[t_]) for i_ in range(w0_, t_ + 1))
    global LAST_BOX
    ta, tb = pd.Timestamp(a), pd.Timestamp(b)
    idx = [i for i, d in enumerate(df.index) if ta <= d <= tb]
    LAST_BOX = box_line(df, res, idx) if idx else ""
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
                near.append(f"{e['date']:%d.%m.%Y} {e['mode']} {st} {mt(e)}")
            elif e["type"] == "giris":
                near.append(f"{e['date']:%d.%m.%Y} GİRİŞ")
            elif e["type"] == "iptal":
                near.append(f"{e['date']:%d.%m.%Y} iptal({e.get('reason', '?')})")
        nr = ("\n  çevredeki olaylar (±25 gün): " + " | ".join(near[:6])) if near else ""
        return False, f"❌ {head}\n  sinyal yok{extra} [{px}]{nr}\n  en yakın mumlar: {best}"
    info = f"veri {len(df)} mum ({df.index[0]:%d.%m.%Y}–{df.index[-1]:%d.%m.%Y})"
    short = f"\n  ℹ️ geçmiş {len(df)} mum, ısınma {P.warmup}: kısa geçmişte test zayıf" if len(df) < P.warmup + 20 else ""
    if live:
        det = ", ".join(f"{e['date']:%d.%m} {e['mode']} dt{e['dt']} cl{e.get('dcl', 0)} {mt(e)}" for e in live[:6])
        return False, f"⚠️ {head}\n  YANLIŞ sinyal çıkıyor: {det}  [{px}; {info}]"
    return True, f"✅ {head}\n  beklendiği gibi sinyal yok  [{px}; {info}]{short}"


# sıkılaştırma varyantları (hepsi CAND üstüne)
VARIANTS = [
    ("ADAY (şimdiki ayar)", {}),
    ("b7 kuralı kapalı", dict(b7Max=0)),
    ("art arda düşüş kuralı kapalı", dict(lcMax=0)),
    ("düşüş trendi temas şartı kapalı", dict(dnMinTb=0)),
    ("uzun çizgi (lookback 120)", dict(lookback=120)),
    ("kısa düşen çizgi şartı kapalı", dict(dnMinSp=0)),
    ("kısa düşen çizgi min 11 mum", dict(dnMinSp=11)),
    ("Yatay düşüş trendi engeli kapalı", dict(hDnBlock=False)),
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
        lines.append(txt + ("\n" + LAST_BOX if LAST_BOX else ""))
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

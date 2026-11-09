"""Tek hisse olay tanısı: bir tarih aralığında göstergenin etiket / Giriş / iptal olayları ve Giriş gelmediyse nedeni.
Giriş şartları (fd_core): etiketten sonraki 8 mum içinde kapanış çizginin üstüne çıkmalı VE etiket günü kapanışının
üstünde olmalı; bu sürede etiket iptal olursa (stop altı kapanış / büyük kırmızı mum / etiket kapanışından 0.5 ADR düşüş)
Giriş gelmez. Hiçbir ayarı değiştirmez.
Çalıştırma: python hisse_olay.py KTLEV 2026-06-15 2026-08-15 [--telegram]
"""
from __future__ import annotations

import sys

import pandas as pd

from fd_core import Params, run
from scan import fetch_tv_all, telegram_send


def main():
    a = [x for x in sys.argv[1:] if not x.startswith("--")]
    sym, bas, bit = a[0].upper(), pd.Timestamp(a[1]), pd.Timestamp(a[2])
    df = fetch_tv_all([sym], n_bars=1500, budget=120, min_bars=30).get(sym)
    if df is None:
        telegram_send(f"{sym}: veri yok")
        return
    P = Params()
    res = run(df, P)
    S, c = res.S, df["Close"].to_numpy(float)
    out = [f"🔎 {sym} olayları {bas:%d.%m.%Y}–{bit:%d.%m.%Y}"]
    for e in res.events:
        if not (bas <= e["date"] <= bit):
            continue
        if e["type"] == "setup":
            t = e["t"]
            out.append(f"\n🟠 {e['date']:%d.%m} etiket ({e['mode']}{', güçlü' if e.get('strong') else ', zayıf'}) kapanış {e['close']:.4g} "
                       f"çizgi {e['line']:.4g} stop {e['stop']:.4g}")
            if e.get("triggered"):
                out.append("   → Giriş geldi")
                continue
            if e.get("cancelled"):
                ct = e["cancel_t"]
                out.append(f"   → İPTAL {df.index[ct]:%d.%m} ({e.get('cancel_reason')}), Giriş gelmedi")
            # sonraki 8 mum: kapanış, çizgi seviyesi, etiket kapanışı karşılaştırması
            sl = 0.0 if e["mode"] != "Düşen" else None
            for k in range(t + 1, min(t + P.trigWin + 1, len(c))):
                ln = e["line"]
                not_ = []
                if c[k] <= ln:
                    not_.append("çizgi altında")
                if c[k] <= e["close"]:
                    not_.append("etiket kapanışı altında")
                out.append(f"   {df.index[k]:%d.%m} kapanış {c[k]:.4g}" + (f" ({', '.join(not_)})" if not_ else " (şartlar tamam)")
                           + (f" | engel: {res.diag.get(k, '')[:60]}" if res.diag.get(k) else ""))
                if e.get("cancelled") and k >= e["cancel_t"]:
                    break
            if not e.get("cancelled") and not e.get("triggered"):
                out.append(f"   → 8 mum içinde şartlar oluşmadı (süre doldu). Not: düşen çizgide çizgi her gün aşağı iner.")
        elif e["type"] == "giris":
            out.append(f"🟢 {e['date']:%d.%m} GİRİŞ {e['close']:.4g} (etiket {e['setup_date']:%d.%m})")
    # Base v0: aralıktaki sinyaller + son mumda şartlar
    from base_v0 import HMAX, TOL, W, WT, sinyaller
    v0 = [e for e in sinyaller(df) if bas <= e["date"] <= bit]
    out.append("\n🧱 Base v0: " + (", ".join(f"{e['date']:%d.%m} (direnç {e['line']:.4g})" for e in v0) or "sinyal yok"))
    hh, ll = df["High"].to_numpy(float), df["Low"].to_numpy(float)
    u = len(c) - 1
    A = (pd.Series(hh / ll).rolling(20).mean().to_numpy()[u - 1] - 1) * 100
    top, bot = hh[u - W:u].max(), ll[u - W:u].min()
    out.append(f"  son mum {df.index[u]:%d.%m}: kapanış {c[u]:.4g} | 10 mum tepesi {top:.4g} | base yüksekliği "
               f"{(top / bot - 1) * 100 / A:.1f} ADR (sınır {HMAX}) | 20 mumda tepeye yakın mum "
               f"{int((hh[u - WT:u] >= top * (1 - TOL * A / 100)).sum())} (en az 2) | 20 mumda daha yüksek tepe "
               f"{'VAR' if hh[u - WT:u].max() > top * (1 + TOL * A / 100) else 'yok'}")
    txt = "\n".join(out)
    print(txt)
    if "--telegram" in sys.argv:
        for i in range(0, len(txt), 3500):
            telegram_send(txt[i:i + 3500])


if __name__ == "__main__":
    main()

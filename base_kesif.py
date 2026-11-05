"""Base temas tanımı keşfi (05.11.2026). v1 ön kontrolü geçemedi (almazdım 8/15, alırdım 8/23 elendi: ayırt etmiyor).
Kullanıcı: "fitiller önemsiz, kapanış önemli". Burada ÖNCEDEN SABİTLENMİŞ 6 temas tanımı, v0'ın işaretli 39 grafiğinde
aynı ön kontrolle (İ1: almazdım'ların >= 10/15'i elenir VE alırdım'ların <= 6/24'ü elenir) karşılaştırılır.
Bir grafik, tanım o tarihin ±2 iş günü içinde sinyal vermiyorsa 'elendi' sayılır.
Hiçbir ayarı değiştirmez. Geçen olursa (birden çok geçerse en çok almazdım eleyen) yeni bir KÖR testle (%70) sınanır;
6 tanım denendiği için örnek içi sonuç tek başına kanıt değildir.

Tanımlar (hepsinde base = önceki 10 mum, yükseklik <= 3.3 ADR, 20 mumda daha yüksek tepe yok, ilk kırılım):
  F30  : fitil üstü, tolerans 0.3 ADR, en az 2 temas (= v0)
  F15K : fitil üstü, 0.15 ADR, yan yana temaslar tek, en az 2 küme, aralık >= 3 mum (= v1)
  G30K : gövde üstü (açılış/kapanıştan yüksek olan), 0.3 ADR, küme, aralık >= 3
  G15K : gövde üstü, 0.15 ADR, küme, aralık >= 3
  K30K : kapanış, 0.3 ADR, küme, aralık >= 3
  G30  : gövde üstü, 0.3 ADR, en az 2 temas (kümesiz)
Gövde/kapanış tanımlarında direnç = 10 mumun en yüksek gövde üstü/kapanışı; kırılım = kapanış bu direncin üstünde.
Çalıştırma: python base_kesif.py --telegram
"""
from __future__ import annotations

import sys

import numpy as np
import pandas as pd

import kayit
from base_v0 import ozet, sim
from scan import fetch_tv_all, get_tickers, telegram_send

TANIM = {
    "F30": ("fitil", 0.3, False), "F15K": ("fitil", 0.15, True), "G30K": ("govde", 0.3, True),
    "G15K": ("govde", 0.15, True), "K30K": ("kapanis", 0.3, True), "G30": ("govde", 0.3, False),
}
W, WT, HMAX, BEKLE = 10, 20, 3.3, 10


def sinyaller(df: pd.DataFrame, kaynak: str, tol: float, kume: bool) -> list[int]:
    o, h, l, c = (df[k].to_numpy(float) for k in ("Open", "High", "Low", "Close"))
    ust = {"fitil": h, "govde": np.maximum(o, c), "kapanis": c}[kaynak]
    adr = (pd.Series(h / l).rolling(20).mean().to_numpy() - 1) * 100
    out, son = [], -999
    for u in range(WT + 2, len(c)):
        A = adr[u - 1]
        if np.isnan(A) or A <= 0 or u - son <= BEKLE:
            continue
        top, bot = ust[u - W:u].max(), l[u - W:u].min()
        if not (c[u] > top >= c[u - 1]):
            continue
        if (top / bot - 1) * 100 / A > HMAX:
            continue
        uu = ust[u - WT:u]
        if uu.max() > top * (1 + 0.3 * A / 100):
            continue
        idx = np.where(uu >= top * (1 - tol * A / 100))[0]
        if kume:
            km = []
            for i in idx:
                if km and i - km[-1][-1] <= 2:
                    km[-1].append(i)
                else:
                    km.append([i])
            if len(km) < 2 or km[-1][0] - km[0][-1] < 3:
                continue
        elif len(idx) < 2:
            continue
        son = u
        out.append(u)
    return out


def main():
    rows = kayit.load()
    eski = [r for r in rows if r.get("mod") == "BaseV0" and (r.get("isaret") or "") in ("a", "g", "h")]
    import random
    evren = sorted(random.Random(56).sample(get_tickers(), 150))
    frames = fetch_tv_all(sorted(set(evren) | {r["hisse"] for r in eski}), n_bars=1000, budget=16 * 60)
    out = [f"🔎 Base temas tanımı keşfi ({len(eski)} işaretli v0 grafiği; İ1: almazdım >= 10/15 elenir, alırdım <= 6/24)"]
    sonuc = []
    for ad, (kay, tol, km) in TANIM.items():
        eh = ea = nh = na_ = 0
        el = []
        for r in eski:
            df = frames.get(r["hisse"])
            if df is None:
                continue
            t = int(df.index.searchsorted(pd.Timestamp(r["etiket_tarihi"])))
            var = any(abs(u - t) <= 2 for u in sinyaller(df, kay, tol, km))
            if r["isaret"] == "h":
                nh += 1
                eh += not var
            else:
                na_ += 1
                ea += not var
                if not var:
                    el.append(r["hisse"])
        bars, R = 0, []
        for s in evren:
            df = frames.get(s)
            if df is None:
                continue
            bars += len(df)
            R += [sim(df, u) for u in sinyaller(df, kay, tol, km)]
        txt, m = ozet(R)
        n = len([x for x in R if x is not None])
        gec = eh >= 10 and ea <= 6
        sonuc.append((gec, eh, ad))
        out.append(f"• {ad}: almazdım {eh}/{nh} elendi, alırdım {ea}/{na_} elendi -> {'✅' if gec else '❌'} | "
                   f"{n / bars * 1000 if bars else 0:.1f}/1000 mum | {txt}" + (f" | elenen alırdım: {', '.join(el)}" if el else ""))
    gecen = sorted([x for x in sonuc if x[0]], key=lambda x: -x[1])
    out.append(f"\nSeçilen: {gecen[0][2]} -> kör test (%70) hazırlanacak" if gecen else
               "\nHiçbiri geçmedi: temas tanımı tek başına ayırt etmiyor; senden direnç çizgisini işaretlemeni isteyeceğim.")
    txt = "\n".join(out)
    print(txt)
    if "--telegram" in sys.argv:
        telegram_send(txt[:3900])


if __name__ == "__main__":
    main()

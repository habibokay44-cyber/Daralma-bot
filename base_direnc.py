"""Senin direncin vs v0'ın direnci (05.11.2026). Hiçbir ayarı değiştirmez; v2 kuralını tasarlamak için ölçüm.
Her Base v0 grafiği için (direnc_sen yazılmış olanlar):
  biz   = v0'ın direnci (önceki 10 mumun en yüksek fitili)
  sen   = senin yazdığın direnç
  fark  = (sen / biz - 1), ADR cinsinden (+ ise senin çizgin daha yukarıda)
  kır   = sinyal günü kapanışı SENİN çizginin üstünde mi
  Temaslar senin çizginde: son 20/40/60 mumda fitili çizgiye 0.3 ADR yakın tepeler (yan yana olanlar tek sayılır),
  'g' ile aynı şey gövde üstüyle. Hangisi senin saydığın temas sayısına en yakın, onu arıyoruz.
  kutu  = senin çizginden geriye doğru, kapanışların hep çizginin altında kaldığı mum sayısı (base uzunluğu)
Çalıştırma: python base_direnc.py --telegram
"""
from __future__ import annotations

import sys
import time

import numpy as np
import pandas as pd

import kayit
from scan import fetch_tv_all, telegram_send


def kume_say(idx) -> int:
    n, son = 0, -99
    for i in idx:
        if i - son > 2:
            n += 1
        son = i
    return n


def olc(df, r):
    o, h, l, c = (df[k].to_numpy(float) for k in ("Open", "High", "Low", "Close"))
    u = int(df.index.searchsorted(pd.Timestamp(r["etiket_tarihi"])))
    adr = (pd.Series(h / l).rolling(20).mean().to_numpy() - 1) * 100
    A = adr[u - 1]
    biz = h[u - 10:u].max()
    d = dict(u=u, biz=biz, A=A, c=c[u])
    if r["direnc_sen"] == "yok":
        return d
    sen = float(r["direnc_sen"])
    d["sen"] = sen
    d["fark"] = (sen / biz - 1) * 100 / A
    d["kir"] = c[u] > sen
    d["once"] = c[u - 1] <= sen
    tol = sen * 0.3 * A / 100
    gu = np.maximum(o, c)
    for n in (20, 40, 60):
        a = max(0, u - n)
        d[f"f{n}"] = kume_say([i for i in range(a, u) if abs(h[i] - sen) <= tol])
        d[f"g{n}"] = kume_say([i for i in range(a, u) if abs(gu[i] - sen) <= tol])
    k = 0
    for i in range(u - 1, -1, -1):
        if c[i] > sen * (1 + 0.1 * A / 100):
            break
        k += 1
    d["kutu"] = k
    return d


def main():
    rows = [r for r in kayit.load() if r.get("mod") == "BaseV0" and (r.get("direnc_sen") or "")]
    frames = fetch_tv_all(sorted({r["hisse"] for r in rows}), n_bars=1000, budget=10 * 60)
    out = [f"📐 Senin direncin vs v0 ({len(rows)} grafik). fark: ADR cinsinden (+ senin çizgin yukarıda)"]
    grup = {"a": [], "h": []}
    for r in sorted(rows, key=lambda x: (x.get("isaret") != "h", x["etiket_tarihi"])):
        df = frames.get(r["hisse"])
        if df is None:
            out.append(f"{r['hisse']}: veri yok")
            continue
        d = olc(df, r)
        cev = "a" if r.get("isaret") in ("a", "g") else "h" if r.get("isaret") == "h" else "?"
        if cev in grup:
            grup[cev].append((r, d))
        bas = f"{cev} {r['hisse']} {r['etiket_tarihi'][2:]}: biz {d['biz']:.4g}"
        if "sen" not in d:
            out.append(bas + " | sen: YOK")
            continue
        out.append(bas + f" sen {d['sen']:.4g} ({r.get('temas_sen') or '?'} temas) fark {d['fark']:+.1f} | "
                   f"kapanış {'ÜSTÜNDE' if d['kir'] else 'altında'}{'' if d['once'] else ' (önceki gün de üstte)'} | "
                   f"fitil 20/40/60: {d['f20']}/{d['f40']}/{d['f60']} gövde {d['g20']}/{d['g40']}/{d['g60']} | kutu {d['kutu']}")
    out.append("\nÖzet (alırdım | almazdım):")
    for g in ("a", "h"):
        L = grup[g]
        yok = sum(1 for r, d in L if "sen" not in d)
        S = [d for r, d in L if "sen" in d]
        if not S:
            out.append(f"  {g}: {len(L)} grafik, direnç yok {yok}")
            continue
        med = lambda k: np.median([d[k] for d in S])  # noqa: E731
        ust = sum(1 for d in S if d["kir"])
        yakin = sum(1 for d in S if abs(d["fark"]) <= 0.5)
        out.append(f"  {g}: {len(L)} grafik | direnç yok {yok} | kapanış senin çizginin üstünde {ust}/{len(S)} | "
                   f"çizgiler 0.5 ADR içinde {yakin}/{len(S)} | medyan fark {med('fark'):+.1f} ADR | medyan kutu {med('kutu'):.0f} mum | "
                   f"medyan temas fitil 20/40/60 {med('f20'):.0f}/{med('f40'):.0f}/{med('f60'):.0f}")
    # senin temas sayına hangi ölçü en yakın
    S = [(r, d) for g in grup.values() for r, d in g if "sen" in d and (r.get("temas_sen") or "").isdigit()]
    if S:
        hata = {k: np.mean([abs(d[k] - int(r["temas_sen"])) for r, d in S]) for k in ("f20", "f40", "f60", "g20", "g40", "g60")}
        out.append("Senin temas sayına ortalama uzaklık (küçük = senin saydığına yakın): "
                   + ", ".join(f"{k} {v:.1f}" for k, v in sorted(hata.items(), key=lambda x: x[1])))
    txt = "\n".join(out)
    print(txt)
    if "--telegram" in sys.argv:
        for i in range(0, len(txt), 3500):
            telegram_send(txt[i:i + 3500])
            time.sleep(1)


if __name__ == "__main__":
    main()

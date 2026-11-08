"""Base ayırt ölçümü (08.11.2026): 'alırdım' ile 'almazdım / direnç yok' Base grafikleri ölçülebilir neyle ayrışıyor?
Sadece FİKİR ÜRETİR, kural koymaz. Çıkan aday kural önceden yazılıp yeni kör örneklemde test edilecek.
Veri: Base v0 kör (39) + Base T2 kör (40) işaretli grafikler. Hepsi v0 sinyali; u = kırılım günü, üst = u-10..u-1 en yüksek tepe.
Her ölçü ADR (20 günlük ortalama gün içi aralık %) cinsinden. AUC: 0.5 = ayırmıyor, 1.0 / 0.0 = tam ayırıyor
(> 0.5: alırdım grubunda daha büyük). 12 ölçü + 79 grafik: tek başına 0.65 altı AUC şans olabilir.
Çalıştırma: python base_ayirt.py --telegram
"""
from __future__ import annotations

import sys

import numpy as np
import pandas as pd

import kayit
from base_t2 import temas
from scan import fetch_tv_all, telegram_send


def olc(df: pd.DataFrame, u: int) -> dict:
    o, h, l, c = (df[k].to_numpy(float) for k in ("Open", "High", "Low", "Close"))
    A = (pd.Series(h / l).rolling(20).mean().to_numpy()[u - 1] - 1) * 100
    top, bot = h[u - 10:u].max(), l[u - 10:u].min()
    a = lambda x: x / top * 100 / A  # noqa: E731  fiyat farkı -> ADR
    tol = top * 0.3 * A / 100
    # seviyenin yaşı: geriye doğru, üstten 0.3 ADR'den yüksek tepe görene kadar kaç mumdur bu seviye altında
    k = u - 1
    while k > 0 and u - k < 250 and h[k] <= top + tol:
        k -= 1
    yas = u - 1 - k
    ilk = next((i for i in range(k + 1, u) if h[i] >= top - tol), u - 1)
    bt = np.maximum(o, c)
    e50 = pd.Series(c).ewm(span=50, adjust=False).mean().to_numpy()
    H120 = h[max(0, u - 120):u].max()
    L60 = l[max(0, u - 70):u - 10].min() if u > 20 else bot
    return {
        "base yüksekliği": a(top - bot),
        "temas (ayrı, 20 mum)": temas(df, u, top),
        "temas (ayrı, 40 mum)": _temas40(h, u, top, tol),
        "seviye yaşı (mum)": yas,
        "ilk temastan kırılıma (mum)": u - ilk,
        "tepeler dağınıklığı": a(top - np.median(h[u - 10:u])),
        "gövde tepeleri dirence uzaklık": a(top - np.median(bt[u - 10:u])),
        "üstteki eski tepe (120 mum)": a(H120 - top),
        "base öncesi yükseliş": a(top - L60),
        "kırılım mumu (kapanış-üst)": a(c[u] - top),
        "EMA50 uzaklığı": a(c[u] - e50[u]),
        "EMA50 eğimi (10 mum)": a(e50[u] - e50[u - 10]),
    }


def _temas40(h, u, top, tol):
    idx = [i for i in range(u - 40, u) if h[i] >= top - tol]
    n, p = 0, None
    for i in idx:
        if p is None or i - p - 1 >= 3:
            n += 1
        p = i
    return n


def auc(x, y):
    x, y = np.asarray(x, float), np.asarray(y, float)
    if not len(x) or not len(y):
        return np.nan
    return float(np.mean([(xi > yi) + 0.5 * (xi == yi) for xi in x for yi in y]))


def main():
    rows = [r for r in kayit.load() if r.get("mod") in ("BaseV0", "BaseT2") and r.get("isaret") in ("a", "g", "h")]
    frames = fetch_tv_all(sorted({r["hisse"] for r in rows}), n_bars=1500, budget=12 * 60)
    D = []
    for r in rows:
        df = frames.get(r["hisse"])
        d = pd.Timestamp(r["etiket_tarihi"])
        if df is None or d not in df.index:
            continue
        u = int(df.index.get_loc(d))
        if u < 130:
            continue
        m = olc(df, u)
        nt = (r.get("not") or "").lower()
        yok = (r.get("direnc_sen") or "").strip().lower() == "yok" or "direnç yok" in nt or "direnç net" in nt \
            or "belirgin direnç yok" in nt or "temas yok" in nt
        D.append(dict(hisse=r["hisse"], tarih=r["etiket_tarihi"], mod=r["mod"], iyi=r["isaret"] in ("a", "g"), yok=yok, **m))
    T = pd.DataFrame(D)
    iyi, kot = T[T.iyi], T[~T.iyi]
    out = [f"🔍 Base ayırt ölçümü: {len(T)} grafik (iyi {len(iyi)}, almazdım {len(kot)}; 'direnç yok' dediğin {int(T.yok.sum())})",
           "ölçü: iyi medyan | almazdım medyan | AUC (0.5 = ayırmıyor)"]
    sat = []
    for k in [c for c in T.columns if c not in ("hisse", "tarih", "mod", "iyi", "yok")]:
        A_ = auc(iyi[k], kot[k])
        sat.append((abs(A_ - 0.5), f"• {k}: {iyi[k].median():.2f} | {kot[k].median():.2f} | AUC {A_:.2f}"
                    + (" ◀" if abs(A_ - 0.5) >= 0.15 else "")))
    out += [s for _, s in sorted(sat, reverse=True)]
    # en iyi ölçü için eşik tablosu
    out.append("\nAyrıca 'direnç yok' dediklerin vs direnç gördüklerin:")
    Y, N = T[T.yok], T[~T.yok]
    sat = []
    for k in [c for c in T.columns if c not in ("hisse", "tarih", "mod", "iyi", "yok")]:
        A_ = auc(N[k], Y[k])
        sat.append((abs(A_ - 0.5), f"• {k}: direnç var {N[k].median():.2f} | yok {Y[k].median():.2f} | AUC {A_:.2f}"))
    out += [s for _, s in sorted(sat, reverse=True)[:6]]
    T.to_csv("base_ayirt.csv", index=False)
    txt = "\n".join(out)
    print(txt)
    print(T.round(2).to_string())
    if "--telegram" in sys.argv:
        telegram_send(txt[:3900])


if __name__ == "__main__":
    main()

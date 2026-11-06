"""Base kırılımı ölçümü: state/kacan.csv'de notunda 'base' ya da 'tepe' geçen örneklerin ölçüleri. Hiçbir ayarı değiştirmez.
Amaç: 'Base kırılımı' modunun eşiklerini SENİN örneklerinden ölçmek (önce ölç, sonra eşiği sabitle, sonra kör test).
Tarih = kırılımdan önceki son daralma günü (t).

Ölçüler (ADR = 20 günlük ortalama gün içi aralık %):
  Base (W = 10 ve 20 mum, t dahil): yük = base yüksekliği / ADR, tem = üst sınıra 0.3 ADR yakın tepe sayısı
  Daralma: d3/d5 = son 3/5 mumun ortalama aralığı / ADR, kc = son 5 mum aralığı / önceki 15 mum aralığı (küçülme)
           yer = son 3 kapanışın base içindeki konumu (0 = dip, 1 = üst)
  Kırılım: kır = kaç gün sonra kapanış 10 mumluk base üstünü geçti (10 gün içinde), sonra20 = sonraki 20 günde en yüksek %
  Büyük resim: dd250 = 250 günlük tepeden uzaklık %, poz250 = 250 günlük aralıkta konum (0 dip, 1 tepe),
               dus = son 120 günün tepesinden base dibine düşüş %, yuk = 250 günde dipten tepeye yükseliş %,
               s150 = kapanış/150 günlük ortalama - 1 (%), e150 = 150 günlük ortalamanın 20 günlük eğimi %
  Gösterge: t'nin ±10 günü içinde etiket/Giriş var mı
Çalıştırma: python base_olc.py --telegram
"""
from __future__ import annotations

import csv
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

from fd_core import Params, run
from scan import fetch_tv_all, telegram_send

F = Path(__file__).resolve().parent / "state" / "kacan.csv"


def grup(not_: str) -> str:
    n = not_.lower()
    return "tepe" if "tepe" in n else "base" if "base" in n else ""


def olc(df: pd.DataFrame, d: pd.Timestamp) -> dict:
    o, h, l, c = (df[k].to_numpy(float) for k in ("Open", "High", "Low", "Close"))
    t = int(df.index.searchsorted(d, side="right")) - 1
    adr = (pd.Series(h / l).rolling(20).mean().to_numpy() - 1) * 100
    A = adr[t]
    r = dict(t=t, gun=df.index[t])
    for W in (10, 20):
        top, bot = h[t - W + 1:t + 1].max(), l[t - W + 1:t + 1].min()
        r[f"yuk{W}"] = (top / bot - 1) * 100 / A
        r[f"tem{W}"] = int(np.sum(h[t - W + 1:t + 1] >= top * (1 - 0.3 * A / 100)))
    rng = (h - l) / c * 100
    r["d3"], r["d5"] = rng[t - 2:t + 1].mean() / A, rng[t - 4:t + 1].mean() / A
    r["kc"] = rng[t - 4:t + 1].mean() / rng[t - 19:t - 4].mean()
    top20, bot20 = h[t - 19:t + 1].max(), l[t - 19:t + 1].min()
    r["yer"] = (c[t - 2:t + 1].mean() - bot20) / (top20 - bot20) if top20 > bot20 else np.nan
    top10 = h[t - 9:t + 1].max()
    kir = next((u - t for u in range(t + 1, min(t + 11, len(c))) if c[u] > top10), None)
    r["kir"] = kir
    r["v0"] = v0_neden(df, t + kir) if kir else "v0: 10 gün içinde kırılım yok"
    r["sonra20"] = (h[t + 1:t + 21].max() / c[t] - 1) * 100 if t + 1 < len(c) else np.nan
    a = max(0, t - 249)
    H, L = h[a:t + 1].max(), l[a:t + 1].min()
    r["dd250"] = (c[t] / H - 1) * 100
    r["poz250"] = (c[t] - L) / (H - L) if H > L else np.nan
    r["dus"] = (bot20 / h[max(0, t - 119):t + 1].max() - 1) * 100
    hi = a + int(np.argmax(h[a:t + 1]))
    r["yuk"] = (H / l[a:hi + 1].min() - 1) * 100
    s150 = pd.Series(c).rolling(150).mean().to_numpy()
    r["s150"] = (c[t] / s150[t] - 1) * 100 if not np.isnan(s150[t]) else np.nan
    r["e150"] = (s150[t] / s150[t - 20] - 1) * 100 if t >= 170 else np.nan
    ev = [e for e in run(df, Params()).events if e["type"] in ("setup", "giris") and abs(e["t"] - t) <= 10]
    r["gos"] = ", ".join(f"{e['date']:%d.%m} {'Giriş' if e['type'] == 'giris' else e['mode']}" for e in ev) or "yok"
    return r


def v0_neden(df: pd.DataFrame, u: int) -> str:
    """Base v0 bu kırılım gününde neden sinyal vermedi (ya da verdi)."""
    from base_v0 import HMAX, NTEM, TOL, W, WT, sinyaller
    if any(abs(e["t"] - u) <= 1 for e in sinyaller(df)):
        return "v0 ✓ sinyal verdi"
    h, l, c = (df[k].to_numpy(float) for k in ("High", "Low", "Close"))
    A = (pd.Series(h / l).rolling(20).mean().to_numpy() - 1)[u - 1] * 100
    top, bot = h[u - W:u].max(), l[u - W:u].min()
    hh = h[u - WT:u]
    neden = []
    if not (c[u] > top >= c[u - 1]):
        neden.append(f"kırılım yok (kapanış {c[u]:.4g}, 10 mum tepe {top:.4g})")
    if (top / bot - 1) * 100 / A > HMAX:
        neden.append(f"base yüksek {(top / bot - 1) * 100 / A:.1f} ADR > {HMAX}")
    if hh.max() > top * (1 + TOL * A / 100):
        neden.append(f"20 mumda daha yüksek tepe {hh.max():.4g}")
    n = int(np.sum(hh >= top * (1 - TOL * A / 100)))
    if n < NTEM:
        neden.append(f"temas {n} < {NTEM}")
    return "v0 ✗ " + ("; ".join(neden) or "bekleme (son 10 mumda başka sinyal)")


def satir(sym, r):
    f = lambda x, n=1: "-" if x is None or (isinstance(x, float) and np.isnan(x)) else f"{x:.{n}f}"  # noqa: E731
    return (f"{sym} {r['gun']:%d.%m.%Y}: base10 yük{f(r['yuk10'])} tem{r['tem10']} | base20 yük{f(r['yuk20'])} tem{r['tem20']} | "
            f"d3 {f(r['d3'], 2)} d5 {f(r['d5'], 2)} kc{f(r['kc'], 2)} yer{f(r['yer'], 2)} | kır {r['kir'] if r['kir'] is not None else '-'} "
            f"sonra20 +{f(r['sonra20'], 0)}% | dd250 {f(r['dd250'], 0)}% poz250 {f(r['poz250'], 2)} düş {f(r['dus'], 0)}% "
            f"yük {f(r['yuk'], 0)}% s150 {f(r['s150'], 0)}% e150 {f(r['e150'], 1)}% | gösterge: {r['gos']} | {r['v0']}")


def main():
    if not F.exists():
        print("kacan.csv yok")
        return
    rows = []
    for x in csv.DictReader(F.open(encoding="utf-8")):  # aynı hisse+tarih iki kez yazıldıysa son kaydı al
        if grup(x.get("not", "")):
            k = (x["hisse"], x["tarih"])
            rows = [y for y in rows if (y["hisse"], y["tarih"]) != k] + [x]
    if not rows:
        telegram_send("Base ölçümü: kacan.csv'de 'base' ya da 'tepe' notlu örnek yok.")
        return
    syms = sorted({x["hisse"] for x in rows})
    frames = fetch_tv_all(syms, n_bars=1500, budget=8 * 60, min_bars=30)
    for _ in range(2):
        miss = [s for s in syms if s not in frames]
        if not miss:
            break
        time.sleep(3)
        frames.update(fetch_tv_all(miss, n_bars=1500, budget=3 * 60, min_bars=30))
    out, ozet = [f"📏 Base ölçümü ({len(rows)} örnek)"], {"base": [], "tepe": []}
    for g in ("base", "tepe"):
        out.append(f"\n— {g.upper()} —")
        for x in [x for x in rows if grup(x["not"]) == g]:
            df = frames.get(x["hisse"])
            if df is None:
                out.append(f"{x['hisse']} {x['tarih']}: veri yok")
                continue
            try:
                r = olc(df, pd.Timestamp(x["tarih"]))
            except Exception as ex:  # noqa: BLE001
                out.append(f"{x['hisse']} {x['tarih']}: ölçülemedi ({ex})")
                continue
            ozet[g].append(r)
            out.append(satir(x["hisse"], r) + (f" ({x['not']})" if x["not"].strip().lower() not in (g,) else ""))
    out.append("\nMedyanlar (base | tepe):")
    for k in ("yuk10", "tem10", "yuk20", "d3", "d5", "kc", "yer", "dd250", "poz250", "dus", "yuk", "s150", "e150"):
        m = [np.nanmedian([r[k] for r in ozet[g]]) if ozet[g] else np.nan for g in ("base", "tepe")]
        out.append(f"  {k}: {m[0]:.2f} | {m[1]:.2f}")
    txt = "\n".join(out)
    print(txt)
    if "--telegram" in sys.argv:
        for i in range(0, len(txt), 3500):
            telegram_send(txt[i:i + 3500])
            time.sleep(1)


if __name__ == "__main__":
    main()

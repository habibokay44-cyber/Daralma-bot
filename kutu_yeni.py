"""Yaşayan kutu dedektörü (taslak v1). Mevcut göstergeden (fd_core) bağımsızdır, hiçbir şeyi değiştirmez.

Tanım (senin tarifinden, 04.11.2026):
  1. En az MIN_N küçük mum. Küçük = mum aralığı, kutudan önceki REF_N mumun ortalama aralığının SMALL katından küçük.
  2. Yön yukarı ya da yan: kutudaki kapanışların eğimi >= SLOPE_MIN (ADR/mum) ve hiçbir kapanış kutu tabanının
     (ilk 3 mumun en düşük dibi) altında değil.
  3. Direnç altında: kutudan önce, kutunun tepesinin üstünde kalan ve o zamandan beri üstünde kapanış görmemiş
     en yakın tepe (pivot). Yakınlık önemli değil. Direnç yoksa (zirvede) kutu sayılmaz.
  4. EMA10 ve EMA21 yükseliyor (bugün > EMA_UP mum önce). PRICE_EMA=True ise ayrıca tüm kapanışlar EMA21
     üstünde ve son kapanış EMA10'un en fazla EMA10_TOL ADR altında (eski hal, karşılaştırma için).
  5. EMA50 şart değil, sadece bilgi.
Yaşayan kutu: şartlar ilk sağlandığında kutu açılır (etiket). Mumlar küçük kaldıkça kutu her gün uzar.
Biter: KIRILIM (kapanış direncin üstünde), YUKARI ÇIKIŞ (kutu tepesi üstünde kapanan büyük mum,
direnç altında) ya da BOZULMA (taban altı kapanış, büyük mum, EMA21 altı kapanış,
aşağı eğim, kutu fazla genişledi) ya da UZUN (MAX_N mum).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class KP:
    MIN_N: int = 3          # en az küçük mum
    REF_N: int = 10         # "küçük" için kutudan önceki kaç muma bakılır
    SMALL: float = 0.75     # mum aralığı <= SMALL x önceki ortalama
    BIG: float = 1.0        # kutu içinde aralığı > BIG x önceki ortalama olan mum kutuyu bozar
    BAND: float = 2.0       # kutudaki gövdelerin toplam bandı (ADR) en fazla
    SLOPE_MIN: float = -0.05  # kapanış eğimi (ADR/mum) en az
    EMA_UP: int = 5         # EMA yükseliyor: bugün > EMA_UP mum önce
    EMA10_TOL: float = 0.25   # son kapanış EMA10'un en fazla bu kadar ADR altında olabilir
    PRICE_EMA: bool = False   # True: kapanışlar EMA21 üstünde ve son kapanış EMA10 yakınında olmalı (eski hal)
    PV: int = 2             # tepe (pivot) için iki yanda kaç mum
    LOOK: int = 120         # direnç için geriye kaç mum
    MAX_N: int = 25         # kutu en fazla bu kadar mum yaşar


def _ema(x: np.ndarray, n: int) -> np.ndarray:
    return pd.Series(x).ewm(span=n, adjust=False).mean().to_numpy()


def _slope_adr(c: np.ndarray, adr_pct: float) -> float:
    """Kapanışların doğrusal eğimi, mum başına ADR cinsinden."""
    if len(c) < 2:
        return 0.0
    x = np.arange(len(c))
    sl = np.polyfit(x, c, 1)[0]
    return float(sl / c.mean() * 100 / adr_pct)


def detect(df: pd.DataFrame, P: KP | None = None) -> list[dict]:
    P = P or KP()
    o, h, l, c = (df[k].to_numpy(float) for k in ("Open", "High", "Low", "Close"))
    n = len(c)
    adr = (pd.Series(h / l).rolling(20).mean().to_numpy() - 1) * 100
    rng = (h - l) / c * 100
    e10, e21, e50 = _ema(c, 10), _ema(c, 21), _ema(c, 50)
    bt, bb = np.maximum(o, c), np.minimum(o, c)
    # pivot tepeler: i'de tepe, i+PV'de kesinleşir
    piv = [i for i in range(P.PV, n - P.PV) if h[i] == h[i - P.PV:i + P.PV + 1].max()]

    def resistance(s: int, top: float) -> float:
        """s'den önce kesinleşmiş, top'un üstünde, o zamandan beri üstünde kapanış olmamış en düşük tepe."""
        best = np.nan
        for i in piv:
            if i + P.PV >= s or i < s - P.LOOK:
                continue
            if h[i] <= top:
                continue
            if (c[i + 1:s] > h[i]).any():
                continue
            if not (best == best) or h[i] < best:
                best = h[i]
        return best

    def opens(t: int):
        s = t - P.MIN_N + 1
        if s - P.REF_N < 0 or t - P.EMA_UP < 0 or not (adr[t] == adr[t]) or adr[t] <= 0:
            return None
        ref = rng[s - P.REF_N:s].mean()
        if not (rng[s:t + 1] <= P.SMALL * ref).all():
            return None
        band = (bt[s:t + 1].max() / bb[s:t + 1].min() - 1) * 100 / adr[t]
        if band > P.BAND:
            return None
        if _slope_adr(c[s:t + 1], adr[t]) < P.SLOPE_MIN:
            return None
        if P.PRICE_EMA and not (c[s:t + 1] >= e21[s:t + 1]).all():
            return None
        if P.PRICE_EMA and (e10[t] - c[t]) / c[t] * 100 / adr[t] > P.EMA10_TOL:
            return None
        if not (e10[t] > e10[t - P.EMA_UP] and e21[t] > e21[t - P.EMA_UP]):
            return None
        R = resistance(s, h[s:t + 1].max())
        if not (R == R) or c[s:t + 1].max() >= R:
            return None
        return dict(s=s, ref=ref, floor=l[s:t + 1].min(), R=R)

    boxes: list[dict] = []
    t = 0
    while t < n:
        st = opens(t)
        if st is None:
            t += 1
            continue
        s, ref, floor, R = st["s"], st["ref"], st["floor"], st["R"]
        box = dict(start=s, label_t=t, end_t=t, R=float(R), floor=float(floor), status="canlı",
                   e50_ust=bool(c[t] >= e50[t]), ref=float(ref))
        u = t + 1
        while u < n:
            if c[u] > R:
                box["status"], box["break_t"] = "kırılım", u
                break
            why = None
            if c[u] < floor:
                why = "taban"
            elif rng[u] > P.BIG * ref and c[u] > bt[s:u].max():
                box["status"], box["break_t"] = "yukarı çıkış", u
                break
            elif rng[u] > P.BIG * ref:
                why = "büyük mum"
            elif P.PRICE_EMA and c[u] < e21[u]:
                why = "EMA21 altı"
            else:
                band = (bt[s:u + 1].max() / bb[s:u + 1].min() - 1) * 100 / adr[u]
                if band > P.BAND:
                    why = "genişledi"
                elif _slope_adr(c[s:u + 1], adr[u]) < P.SLOPE_MIN:
                    why = "aşağı eğim"
                elif u - s + 1 >= P.MAX_N:
                    why = "uzun"
            if why:
                box["status"], box["why"], box["stop_t"] = "bozuldu", why, u
                break
            box["end_t"] = u
            u += 1
        d = df.index
        box.update(start_d=d[s], label_d=d[t], end_d=d[box["end_t"]], n=box["end_t"] - s + 1)
        boxes.append(box)
        t = max(u, t + 1)
    return boxes


def explain(df: pd.DataFrame, a, z, P: KP | None = None) -> dict | None:
    """Senin verdiğin kutu [a, z] için her kuralı ayrı ayrı ölçer (detect'i değiştirmez).
    Kutu en az MIN_N mum olacak şekilde gerekirse geriye uzatılır."""
    P = P or KP()
    idx = df.index
    s = int(idx.searchsorted(pd.Timestamp(a)))
    t = int(idx.searchsorted(pd.Timestamp(z), side="right")) - 1
    if t < 0 or s >= len(idx):
        return None
    if t - s + 1 < P.MIN_N:
        s = t - P.MIN_N + 1
    if s - P.REF_N < 0 or t - P.EMA_UP < 0:
        return None
    o, h, l, c = (df[k].to_numpy(float) for k in ("Open", "High", "Low", "Close"))
    adr = (pd.Series(h / l).rolling(20).mean().to_numpy() - 1) * 100
    rng = (h - l) / c * 100
    e10, e21 = _ema(c, 10), _ema(c, 21)
    bt, bb = np.maximum(o, c), np.minimum(o, c)
    ref = rng[s - P.REF_N:s].mean()
    ratios = rng[s:t + 1] / ref
    band = (bt[s:t + 1].max() / bb[s:t + 1].min() - 1) * 100 / adr[t]
    slope = _slope_adr(c[s:t + 1], adr[t])
    e10u = (e10[t] / e10[t - P.EMA_UP] - 1) * 100
    e21u = (e21[t] / e21[t - P.EMA_UP] - 1) * 100
    top = h[s:t + 1].max()
    piv = [i for i in range(max(P.PV, s - P.LOOK), s - P.PV) if h[i] == h[i - P.PV:i + P.PV + 1].max()]
    above = [i for i in piv if h[i] > top]
    clean = [i for i in above if not (c[i + 1:s] > h[i]).any()]
    if clean:
        R = min(h[i] for i in clean)
        res = f"✓{R:.2f}" if c[s:t + 1].max() < R else f"✗kapanış dirençte({R:.2f})"
    elif above:
        res = "✗üstteki tepeler daha önce kapanışla aşılmış"
    else:
        res = "✗kutu üstünde tepe yok"
    floor_brk = bool((c[s + P.MIN_N:t + 1] < l[s:s + P.MIN_N].min()).any()) if t - s + 1 > P.MIN_N else False
    return dict(
        s=idx[s], t=idx[t], n=t - s + 1,
        small=(ratios.max() <= P.SMALL, f"en büyük mum {ratios.max():.2f}x (≤{P.SMALL})", [round(float(x), 2) for x in ratios]),
        band=(band <= P.BAND, f"bant {band:.2f} ADR (≤{P.BAND})"),
        slope=(slope >= P.SLOPE_MIN, f"eğim {slope:+.2f} (≥{P.SLOPE_MIN})"),
        ema10=(e10u > 0, f"EMA10 5 günde %{e10u:+.1f}"),
        ema21=(e21u > 0, f"EMA21 5 günde %{e21u:+.1f}"),
        res=(res.startswith("✓"), res),
        floor=(not floor_brk, "taban kırılmadı" if not floor_brk else "kutu içinde taban kırıldı"),
    )

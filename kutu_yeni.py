"""Yaşayan kutu dedektörü (taslak v1). Mevcut göstergeden (fd_core) bağımsızdır, hiçbir şeyi değiştirmez.

Tanım (senin tarifinden, 04.11.2026):
  1. En az MIN_N mum, gövdeleri BAND ADR'lik bantta toplanmış; hiçbir mum kutudan önceki REF_N mumun
     ortalama aralığının SMALL katını geçmiyor (S3: tek tek mum boyuna değil, dar banda bakılır).
  2. Yön yukarı ya da yan: kutudaki kapanışların eğimi >= SLOPE_MIN (ADR/mum) ve hiçbir kapanış kutu tabanının
     (ilk 3 mumun en düşük dibi) altında değil.
  3. Direnç altında: kutudan önce, kutunun tepesinin üstünde kalan ve o zamandan beri üstünde kapanış görmemiş
     en yakın tepe (pivot). Yakınlık önemli değil. Direnç yoksa (zirvede) kutu sayılmaz.
  4. EMA10 ve EMA21 yükseliyor ya da düz (EMA_UP mumda en fazla %EMA_DROP düşüş). PRICE_EMA=True ise ayrıca tüm kapanışlar EMA21
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
    SMALL: float = 1.5      # S3 (04.11 kararın): kutudaki hiçbir mum önceki ortalamanın SMALL katını geçmez; asıl şart BAND
    BIG: float = 1.5        # kutu içinde aralığı > BIG x önceki ortalama olan mum kutuyu bozar (yukarı kapanırsa 'yukarı çıkış')
    BAND: float = 2.0       # kutudaki gövdelerin toplam bandı (ADR) en fazla
    SLOPE_MIN: float = -0.05  # kapanış eğimi (ADR/mum) en az
    EMA_UP: int = 5         # EMA yönü EMA_UP mum öncesine göre ölçülür
    EMA_DROP: float = 0.5   # EMA bu sürede en fazla %EMA_DROP düşebilir (düz EMA kabul, 04.11 kararın)
    EMA10_TOL: float = 0.25   # son kapanış EMA10'un en fazla bu kadar ADR altında olabilir
    PRICE_EMA: bool = False   # True: kapanışlar EMA21 üstünde ve son kapanış EMA10 yakınında olmalı (eski hal)
    PV: int = 2             # tepe (pivot) için iki yanda kaç mum
    LOOK: int = 120         # direnç için geriye kaç mum
    MAX_N: int = 25         # kutu en fazla bu kadar mum yaşar
    LABEL_N: int = 3        # etiket, kutu bu kadar mum yaşayınca çıkar; daha kısa kutular etiket üretmez (04.11: 5)
    MAX_STOP: float = 0.0   # >0 ise: dirençten kutu tabanına mesafe en fazla % MAX_STOP (kırılımda girilirse stop)
    NEAR_ADR: float = 0.0   # >0 ise: kutu tepesi (en yüksek fitil) dirence en fazla NEAR_ADR ADR uzaklıkta


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
        if not ((e10[t] / e10[t - P.EMA_UP] - 1) * 100 > -P.EMA_DROP and (e21[t] / e21[t - P.EMA_UP] - 1) * 100 > -P.EMA_DROP):
            return None
        R = resistance(s, h[s:t + 1].max())
        if not (R == R) or c[s:t + 1].max() >= R:
            return None
        floor = l[s:t + 1].min()
        if P.MAX_STOP > 0 and (R / floor - 1) * 100 > P.MAX_STOP:
            return None
        if P.NEAR_ADR > 0 and (R / h[s:t + 1].max() - 1) * 100 / adr[t] > P.NEAR_ADR:
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
        box.update(open_t=t, start_d=d[s], end_d=d[box["end_t"]], n=box["end_t"] - s + 1)
        if P.LABEL_N > P.MIN_N:
            if box["n"] >= P.LABEL_N:
                box["label_t"] = s + P.LABEL_N - 1
                box["label_d"] = d[box["label_t"]]
                boxes.append(box)
        else:
            box["label_d"] = d[t]
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
        ema10=(e10u > -P.EMA_DROP, f"EMA10 5 günde %{e10u:+.1f}"),
        ema21=(e21u > -P.EMA_DROP, f"EMA21 5 günde %{e21u:+.1f}"),
        res=(res.startswith("✓"), res),
        floor=(not floor_brk, "taban kırılmadı" if not floor_brk else "kutu içinde taban kırıldı"),
    )


# ---------------------------------------------------------------------------------------------------------------
# Kümelenme kutusu (taslak v3, 04.11.2026, senin tarifin):
#   Ana mum: kümenin ilk mumu; kutu = ana mumun dibi..tepesi.
#   Sonraki mumların açılış ve kapanışı kutunun içinde kalır (fitiller serbest).
#   Kutunun tepesi direnç: üstünde kapanış = KIRILIM; altında kapanış = BOZULMA (taban).
#   Etiket: ana mum + (LABEL_N-1) mum içeride kalınca, LABEL_N. mumda (4). Kutu kırılana/bozulana kadar uzar.
#   Pay: açılış/kapanış kutunun en fazla TOL_ADR (0.25) ADR dışına taşarsa içeride sayılır.
#   v4 (05.11): kutu tepesi en az MIN_TOUCH (2) ayrı temaslı direnç olmalı; temaslar kutudan önceki LOOK mumdan
#   (son 'üstünde kapanış'tan sonra) ya da kutunun içinden gelebilir; iki temas arasında fiyat seviyenin en az
#   RETREAT_ADR (1.0) ADR altına inmiş olmalı (geri itilme). Etiket en az LABEL_N mum + MIN_TOUCH temasla.
#   Korunanlar: EMA10/EMA21 EMA_UP mumda %EMA_DROP'tan fazla düşmüyor; ana mumdan SONRAKİ kapanışların eğimi >= SLOPE_MIN.
# ---------------------------------------------------------------------------------------------------------------
@dataclass
class KK:
    LABEL_N: int = 4        # 04.11: ana mum + 3 mum içeride kalınca etiket
    TOL_ADR: float = 0.25   # 04.11: açılış/kapanış kutunun en fazla bu kadar ADR dışına taşarsa içeride sayılır
    MAX_N: int = 25
    EMA_UP: int = 5
    EMA_DROP: float = 0.5
    SLOPE_MIN: float = -0.05
    MIN_TOUCH: int = 2      # 05.11 (v4): kutu tepesi en az bu kadar ayrı temaslı direnç olmalı (ana mum dahil; 1 = kapalı)
    TOUCH_ADR: float = 0.3  # temas: mum tepesi (fitil dahil) kutu tepesine en fazla bu kadar ADR yakın (en fazla 3 katı üstünde)
    LOOK: int = 120         # geçmiş temaslar için geriye kaç mum
    RETREAT_ADR: float = 1.0  # yeni temas sayılması için önceki temastan sonra fiyat seviyenin en az bu kadar ADR altına inmiş olmalı


def _touch_state(h, l, c, R, s, tolT, tolC, look, retreat):
    """s'den önceki geçerli pencerede (son 'R üstünde kapanış'tan sonra) kaç ayrı temas var.
    Yeni temas sayılması için önceki temastan sonra bir dip R - retreat altına inmiş olmalı (seviyeden geri itilme).
    Döner: (temas sayısı, son temastan beri geri çekilme oldu mu)."""
    a0 = max(0, s - look)
    above = np.where(c[a0:s] > R + tolC)[0]
    start = a0 + int(above[-1]) + 1 if len(above) else a0
    ev, armed = 0, True
    for i in range(start, s):
        if armed and R - tolT <= h[i] <= R + 3 * tolT:
            ev += 1
            armed = False
        if l[i] <= R - retreat:
            armed = True
    return ev, armed


def _inside(o, c, L, H, u, tol=0.0):
    return L - tol <= o[u] <= H + tol and L - tol <= c[u] <= H + tol


def _tol(P, adr, c, u):
    a = adr[u] if adr[u] == adr[u] else 0.0
    return P.TOL_ADR * a / 100 * c[u]


def detect_kume(df: pd.DataFrame, P: KK | None = None) -> list[dict]:
    P = P or KK()
    o, h, l, c = (df[k].to_numpy(float) for k in ("Open", "High", "Low", "Close"))
    n = len(c)
    adr = (pd.Series(h / l).rolling(20).mean().to_numpy() - 1) * 100
    e10, e21 = _ema(c, 10), _ema(c, 21)
    d = df.index
    boxes: list[dict] = []
    s = max(20, P.EMA_UP)
    while s < n - 1:
        L, H = l[s], h[s]
        a_s = adr[s] if adr[s] == adr[s] else 0.0
        tolT = P.TOUCH_ADR * a_s / 100 * H
        ret = P.RETREAT_ADR * a_s / 100 * H
        ev, armed = _touch_state(h, l, c, H, s, tolT, P.TOL_ADR * a_s / 100 * H, P.LOOK, ret) if P.MIN_TOUCH > 1 else (0, True)
        if armed:
            ev += 1  # ana mumun tepesi bir temas
        armed = l[s] <= H - ret
        u = s + 1
        status, why, label_t = "canlı", "", None
        while u < n:
            tl = _tol(P, adr, c, u)
            if c[u] > H + tl:
                status = "kırılım"
                break
            if c[u] < L - tl:
                status, why = "bozuldu", "taban"
                break
            if not _inside(o, c, L, H, u, tl):
                status, why = "bozuldu", "açılış dışarıda"
                break
            if u - s + 1 >= P.MAX_N:
                status, why = "bozuldu", "uzun"
                break
            if armed and H - tolT <= h[u] <= H + 3 * tolT:
                ev += 1
                armed = False
            if l[u] <= H - ret:
                armed = True
            if label_t is None and u - s + 1 >= P.LABEL_N and (P.MIN_TOUCH <= 1 or ev >= P.MIN_TOUCH):
                ok_ema = ((e10[u] / e10[u - P.EMA_UP] - 1) * 100 > -P.EMA_DROP
                          and (e21[u] / e21[u - P.EMA_UP] - 1) * 100 > -P.EMA_DROP)
                ok_sl = adr[u] == adr[u] and adr[u] > 0 and _slope_adr(c[s + 1:u + 1], adr[u]) >= P.SLOPE_MIN
                if not (ok_ema and ok_sl):
                    status, why = "etiketsiz", ("EMA" if not ok_ema else "eğim")
                    break
                label_t = u
            u += 1
        end_t = u - 1
        if label_t is not None:
            b = dict(start=s, label_t=label_t, end_t=end_t, status=status, why=why, R=float(H), floor=float(L), touches=int(ev),
                     start_d=d[s], label_d=d[label_t], end_d=d[end_t], n=end_t - s + 1)
            if status == "kırılım":
                b["break_t"] = u
            elif status == "bozuldu":
                b["stop_t"] = u
            boxes.append(b)
            s = u  # aynı kümeden ikinci etiket yok
        else:
            s += 1  # bu ana mumla küme olmadı, sonraki mumu ana mum olarak dene
    return boxes


def explain_kume(df: pd.DataFrame, a, P: KK | None = None) -> str:
    """Verilen gün ana mum olsaydı: hangi mum kutudan çıktı, etiket gününde EMA/eğim ne durumda."""
    P = P or KK()
    o, h, l, c = (df[k].to_numpy(float) for k in ("Open", "High", "Low", "Close"))
    idx = df.index
    s = int(idx.searchsorted(pd.Timestamp(a)))
    if s >= len(c) - 1:
        return "ölçülemedi"
    L, H = l[s], h[s]
    adr = (pd.Series(h / l).rolling(20).mean().to_numpy() - 1) * 100
    parts = [f"ana mum {idx[s]:%d.%m} [{L:.2f}-{H:.2f}]"]
    u = s + 1
    while u < len(c) and u - s + 1 <= P.MAX_N:
        tl = _tol(P, adr, c, u)
        if not _inside(o, c, L, H, u, tl):
            yer = "üstte kapanış" if c[u] > H + tl else ("altta kapanış" if c[u] < L - tl else "açılış dışarıda")
            parts.append(f"{u - s + 1}. mum {idx[u]:%d.%m} dışarı ({yer}, kapanış {c[u]:.2f})")
            break
        u += 1
    else:
        parts.append("kutu uzun sürdü")
    inside_n = u - s
    parts.append(f"içeride {inside_n} mum")
    a_s = adr[s] if adr[s] == adr[s] else 0.0
    tolT = P.TOUCH_ADR * a_s / 100 * H
    ret = P.RETREAT_ADR * a_s / 100 * H
    ev, armed = _touch_state(h, l, c, H, s, tolT, P.TOL_ADR * a_s / 100 * H, P.LOOK, ret)
    if armed:
        ev += 1
    armed = l[s] <= H - ret
    for k in range(s + 1, u):
        if armed and H - tolT <= h[k] <= H + 3 * tolT:
            ev += 1
            armed = False
        if l[k] <= H - ret:
            armed = True
    parts.append(f"direnç temas {ev} (en az {P.MIN_TOUCH})")
    if inside_n >= P.LABEL_N:
        t = s + P.LABEL_N - 1
        e10, e21 = _ema(c, 10), _ema(c, 21)
        parts.append(f"etiket günü {idx[t]:%d.%m}: EMA10 %{(e10[t] / e10[t - P.EMA_UP] - 1) * 100:+.1f} "
                     f"EMA21 %{(e21[t] / e21[t - P.EMA_UP] - 1) * 100:+.1f} eğim(ana mum hariç) {_slope_adr(c[s + 1:t + 1], adr[t]):+.2f}")
    return " | ".join(parts)

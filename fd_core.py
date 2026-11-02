"""Fiyat Daralması v50- TradingView Pine göstergesinin Python portu.

Pine mantığı mum mum (durum makinesi olarak) birebir taşındı. Girdi: günlük OHLCV.
Çıktı: "Fiyat Daralması" (etiket) ve "Giriş" olayları + geriye dönük test işlemleri.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from types import SimpleNamespace

import numpy as np
import pandas as pd

NAN = float("nan")


def na(x) -> bool:
    return x is None or x != x


def nz(x, y=0.0):
    return y if na(x) else x


@dataclass
class Params:
    lookback: int = 120
    minSpan: int = 6
    minSpanH: int = 9
    pvL: int = 2
    pvR: int = 1
    nC: int = 5
    nS: int = 3
    useShort: bool = False
    tightS: float = 1.0
    shrinkS: float = 0.85
    bodyFrac: float = 0.17
    boxS: float = 1.0
    rallyU: float = 0.9             # rallide etiket yok: son 5 mum yükselişi (u) bundan büyük VE tepeye yakınsa (rallyDd) (0 = kapalı)
    rallyDd: float = 2.0            # 40 mumluk tepeden uzaklık (ADR katı) bundan küçükse rallide sayılır
    bodyADR: float = 0.1
    bodyADRD: float = 0.05          # düşen çizgi: gövdenin çizgiyi geçme toleransı (daha sıkı)
    maxViol: int = 0
    violPct: float = 5.0
    bodyPokeMax: float = 0.4
    useBelow: bool = True
    touchADR: float = 0.4
    rankADR: float = 0.2
    wickADR: float = 2.5
    maxOv: float = 0.8
    minTouches: int = 3
    minClusters: int = 2
    minTb: int = 3
    clMerge: int = 1
    tbCl: bool = False
    minTcD: int = 3                 # düşen çizgi: dar bantta (dt) min. temas
    hPrefer: int = 0                # yatay seviye de geçerliyse: yatay temas + hPrefer > düşen temas ise yatayı seç
    dMinWithH: int = 0              # geçerli yatay seviye varsa düşen çizgi en az bu kadar temaslı olmalı (yoksa yatay seçilir)
    flatPrefer: float = 0.0         # yatay seviye de varsa ve düşen çizgi eğimi (|sn|) bundan küçükse yatayı seç (0 = kapalı)
    fbMinDt: int = 0                # fallbackD sadece düşen çizgi en az bu kadar dar-bant temaslıysa (dt) devreye girer
    fallbackD: bool = False         # yatay seçilirse ama yatay (dar) u/s şartı tutmuyorsa ve düşen çizgi varsa düşene dön
    minClD: int = 2                 # düşen çizgi: bugünkü mum HARİÇ, ayrı temas kümesi (yan yana mumlar tek sayılır) min. (0 = kapalı)
    tightADR: float = 1.0
    shrink: float = 0.9
    closeBoxADR: float = 0.85
    useLows: bool = True
    lowTolADR: float = 0.5
    lowUpADR: float = 2.8
    useLowsH: bool = False
    lowUpH: float = 1.2
    useRise: bool = True
    riseMin: float = -1.0
    riseMax: float = 0.8
    riseMaxD: float = 1.5
    useClose: bool = False
    closeNearY: float = 1.0
    useSlope: bool = True
    slopeMin: float = -0.5
    slopeMax: float = 0.9
    slopeMinD: float = -0.37
    slopeMaxD: float = 1.2
    useCandle: bool = True
    maxCandle: float = 1.3
    minClosePos: float = 0.0
    maxClosePos: float = 0.85
    cpSmallRng: float = 0.0         # küçük mumda (aralık <= bu, ADR katı) kapanış-konumu üst sınırı uygulanmaz (0 = kapalı)
    useJump: bool = True
    jumpMax: float = 0.6            # sinyal mumu: önceki kapanışa göre değişim (ADR katı, max)
    useVolSig: bool = True
    volMaxX: float = 1.8            # sinyal mumu hacmi / 20 mum ort. hacim (max)
    useRedSig: bool = True
    sigRedMax: float = 0.3          # sinyal mumu: kırmızı gövde (ADR katı, max) - düşen mum daralma mumu olamaz
    useEmaTr: bool = True           # trend: EMA21 düşüyorsa / fiyat EMA21'in çok altındaysa daralma sayılmaz
    emaSlopeMin: float = -0.5       # EMA21'in 10 mumluk eğimi (ADR katı) min.
    emaBelowMax: float = 0.5        # kapanış EMA21'in en fazla bu kadar (ADR katı) altında olabilir
    ddMax: float = 5.0              # 40 mumluk tepeden düşüş (ADR katı) bundan büyükse daralma sayılmaz (0 = kapalı)
    shrinkMinD: float = 0.50       # Düşen modu: sıkışma oranı (r) bundan küçükse etiket yok (0 = kapalı)
    slopeMinG: float = -99.0        # Düşen/Yatay: yakın eğim (slopeVal) bundan küçükse etiket yok (-99 = kapalı)
    riseMinG: float = -99.0         # Düşen/Yatay: yükseliş (riseVal) bundan küçükse etiket yok (-99 = kapalı)
    dnBelowSlope: float = 0.0     # Düşen modu: kapanış EMA21 altında VE yakın eğim (s) bundan küçükse etiket yok (-99 = kapalı)
    useBox: bool = True          # KUTU modu: çizgi bulunamasa da uzun yatay taban kutusu (boxN mum) daralma sayılır
    boxN: int = 15                  # kutu: son kaç mum
    boxBody: float = 1.3            # kutu: gövde tepesi - gövde dibi aralığı (ADR katı, max)
    boxHL: float = 2.5              # kutu: fitilli en yüksek - en düşük aralığı (ADR katı, max)
    dnSlope: float = -0.4           # EMA21 eğimi bundan düşükse VE kapanış EMA21 altındaysa (düşüş trendi) ...
    dnMinTb: int = 5                # ... düşen çizgide dar bantta en az bu kadar temas gerekir (0 = kapalı)
    dnMinSp: int = 12               # Düşen çizgi ilk temastan etiket mumuna en az bu kadar mum uzunlukta olmalı (0 = kapalı)
    hDnBlock: bool = True
    yBodyMax: float = 2.0
    b7Max: float = 1.95             # son 7 mumun gövde aralığı (ADR katı) bundan büyükse etiket yok (volatil mumlar; 0 = kapalı)
    lcMax: int = 3                  # son 5 mumda bu kadardan fazla düşen kapanış varsa etiket yok (art arda düşüş; 0 = kapalı)
    restMode: bool = False          # DİNLENME modu (deneme): güçlü yükseliş trendinde direnç altı kısa dar dinlenme
    restE50: float = 2.0            # kapanış EMA50'nin en az bu kadar (ADR katı) üstünde
    restM: float = 1.3              # 5 mum ort. aralık / ADR en çok
    restK: float = 1.0              # 5 mum kapanış aralığı / ADR en çok
    restB7: float = 2.6             # son 7 mumun gövde aralığı (ADR katı) en çok
    restDd: float = 2.0             # 40 mumluk tepeden uzaklık (ADR katı) en çok
    restN: int = 5                  # direnç = son restN mumun gövde tepesi
    nearADR: float = 2.2
    lastNear: float = 1.8
    nearADRH: float = 1.2
    lastNearH: float = 1.0
    allowFlat: bool = True
    allowDesc: bool = True
    flatBand: float = 0.5
    flatUp: float = 0.1
    maxDesc: float = 4.0
    allowHoriz: bool = True
    modePref: str = "Otomatik"      # Otomatik / Düşen / Yatay
    levelSrc: str = "Fitil"         # Fitil / Gövde
    touchSpan: int = 4
    lastTouchMax: int = 5
    maxLineBack: int = 15
    holdBars: int = 8
    useTrend: bool = False
    cooldown: int = 8
    cancelBlock: int = 0
    cancelClearsCooldown: bool = True   # iptal olunca setup bekleme süresi (cooldown) sıfırlansın, sadece cancelBlock geçerli olsun
    trigWin: int = 8
    trigVol: float = 0.0
    useStop: bool = True
    stopBuf: float = 0.5
    useRedKill: bool = True
    redKillADR: float = 0.7
    useDrop: bool = True
    dropADR: float = 0.5
    useAboveLbl: bool = True        # Giriş: kapanış etiket kapanışının üstünde olsun
    strongShrink: float = 0.75
    strongBox: float = 0.9
    onlyStrong: bool = False
    tpMode: str = "SMC direnç"      # "SMC direnç" / "Sabit R"
    tpMult: float = 2.0
    smcL: int = 5
    smcR: int = 5
    smcLook: int = 250
    minRR: float = 1.0
    tpMaxR: float = 6.0
    smcBufADR: float = 0.1
    maxHold: int = 30
    warmup: int = 30                # bu muma kadar sadece pivotlar toplanır


# ---------------------------------------------------------------- yardımcılar
def _sma(x: np.ndarray, n: int) -> np.ndarray:
    return pd.Series(x).rolling(n).mean().to_numpy()


def _highest(x: np.ndarray, n: int) -> np.ndarray:
    return pd.Series(x).rolling(n).max().to_numpy()


def _lowest(x: np.ndarray, n: int) -> np.ndarray:
    return pd.Series(x).rolling(n).min().to_numpy()


def _shift(x: np.ndarray, k: int) -> np.ndarray:
    out = np.full(len(x), np.nan)
    if k < len(x):
        out[k:] = x[: len(x) - k]
    return out


def _ema(x: np.ndarray, n: int) -> np.ndarray:
    return pd.Series(x).ewm(span=n, adjust=False).mean().to_numpy()


def _pivot_high(high: np.ndarray, left: int, right: int) -> np.ndarray:
    """ta.pivothigh: sol taraf kesin küçük, sağ taraf küçük-eşit. Onay mumunda değer döner."""
    n = len(high)
    out = np.full(n, np.nan)
    for t in range(left + right, n):
        p = t - right
        hp = high[p]
        if hp > high[p - left:p].max() and hp >= high[p + 1:t + 1].max():
            out[t] = hp
    return out


def prepare(df: pd.DataFrame, P: Params) -> SimpleNamespace:
    o = df["Open"].to_numpy(float)
    h = df["High"].to_numpy(float)
    l = df["Low"].to_numpy(float)
    c = df["Close"].to_numpy(float)
    v = df["Volume"].to_numpy(float)
    S = SimpleNamespace(o=o, h=h, l=l, c=c, v=v)
    nC, nS = P.nC, P.nS

    S.adr = (_sma(h / l, 20) - 1) * 100
    S.ema50 = _ema(c, 50)
    S.ema21 = _ema(c, 21)
    S.emaSlope = (S.ema21 / _shift(S.ema21, 10) - 1) * 100 / S.adr
    S.emaDist = (c - S.ema21) / c * 100 / S.adr
    S.volAvg = _sma(v, 50)

    rngPct = (h - l) / c * 100
    recentRng = _sma(rngPct, nC)
    priorRng = _shift(_sma(rngPct, 15), nC)
    S.tightVal = recentRng / S.adr
    S.shrinkVal = recentRng / priorRng
    S.closeBoxVal = (_highest(c, nC) / _lowest(c, nC) - 1) * 100 / S.adr
    S.bodyBox10 = (_highest(np.maximum(o, c), 10) / _lowest(np.minimum(o, c), 10) - 1) * 100 / S.adr
    S.drop10 = (c / _shift(c, 10) - 1) * 100 / S.adr
    lowNow = _lowest(l, nC)
    lowPrev = _shift(_lowest(l, 10), nC)
    S.lowDiff = (lowNow - lowPrev) / c * 100 / S.adr
    if P.useLows:
        S.lowsOk = (S.lowDiff >= -P.lowTolADR) & (S.lowDiff <= P.lowUpADR)
    else:
        S.lowsOk = np.ones(len(c), bool)

    sma3 = _sma(c, 3)
    S.riseVal = (sma3 / _shift(sma3, nC) - 1) * 100 / S.adr
    if P.useRise:
        S.riseOkN = (S.riseVal >= P.riseMin) & (S.riseVal <= P.riseMax)
        S.riseOkW = (S.riseVal >= P.riseMin) & (S.riseVal <= P.riseMaxD)
    else:
        S.riseOkN = S.riseOkW = np.ones(len(c), bool)
    S.slopeVal = (sma3 / _shift(sma3, 3) - 1) * 100 / S.adr
    if P.useSlope:
        S.slopeOkN = (S.slopeVal >= P.slopeMin) & (S.slopeVal <= P.slopeMax)
        S.slopeOkW = (S.slopeVal >= P.slopeMinD) & (S.slopeVal <= P.slopeMaxD)
    else:
        S.slopeOkN = S.slopeOkW = np.ones(len(c), bool)

    S.candRng = (h - l) / c * 100 / S.adr
    with np.errstate(divide="ignore", invalid="ignore"):
        S.closePos = np.where(h > l, (c - l) / (h - l), 0.5)
    if P.useCandle:
        S.candOk = (S.candRng <= P.maxCandle) & (S.closePos >= P.minClosePos) & ((S.closePos <= P.maxClosePos) | (S.candRng <= P.cpSmallRng))
    else:
        S.candOk = np.ones(len(c), bool)
    with np.errstate(divide="ignore", invalid="ignore"):
        prevC = _shift(c, 1)
        S.jump = np.abs(c - prevC) / prevC * 100 / S.adr
        vsma = _sma(v, 20)
        S.volRatio = np.where(vsma > 0, v / vsma, np.nan)
    S.redSig = (o - c) / c * 100 / S.adr
    S.redOk = (S.redSig <= P.sigRedMax) if P.useRedSig else np.ones(len(c), bool)
    if P.useEmaTr:
        S.emaOk = (S.emaSlope >= P.emaSlopeMin) & (S.emaDist >= -P.emaBelowMax)
        S.emaOk = S.emaOk | np.isnan(S.emaSlope)
    else:
        S.emaOk = np.ones(len(c), bool)
    S.jumpOk = ((S.jump <= P.jumpMax) | np.isnan(S.jump)) if P.useJump else np.ones(len(c), bool)
    S.volOk = ((S.volRatio <= P.volMaxX) | np.isnan(S.volRatio)) if P.useVolSig else np.ones(len(c), bool)

    recentRngS = _sma(rngPct, nS)
    priorRngS = _shift(_sma(rngPct, 15), nS)
    S.tightValS = recentRngS / S.adr
    S.shrinkValS = recentRngS / priorRngS
    S.closeBoxValS = (_highest(c, nS) / _lowest(c, nS) - 1) * 100 / S.adr

    tightLong = (S.tightVal <= P.tightADR) & (S.shrinkVal <= P.shrink) & (S.closeBoxVal <= P.closeBoxADR)
    if P.useShort:
        tightShort = (S.tightValS <= P.tightS) & (S.shrinkValS <= P.shrinkS) & (S.closeBoxValS <= P.boxS)
    else:
        tightShort = np.zeros(len(c), bool)
    S.tightLong, S.tightShort = tightLong, tightShort
    rngAbs = np.where(h > l, h - l, np.nan)
    S.bodyFr = _sma(np.nan_to_num(np.abs(c - o) / rngAbs, nan=0.5), nC)   # son nC mumda gövde/aralık ortalaması
    S.tightCore = (tightLong | tightShort) & S.lowsOk & ((S.bodyFr >= P.bodyFrac) | np.isnan(S.bodyFr))
    S.tightOk = S.tightCore & S.riseOkW & S.slopeOkW
    S.strong = (tightLong & (S.shrinkVal <= P.strongShrink) & (S.closeBoxVal <= P.strongBox)) | tightShort
    S.dd40 = (_highest(c, 40) - c) / c * 100 / S.adr          # 40 mumluk tepeden uzaklık (ADR katı)
    S.rallyOk = ~((S.riseVal > P.rallyU) & (S.dd40 < P.rallyDd)) if P.rallyU > 0 else np.ones(len(c), bool)
    S.e50d = (c - S.ema50) / c * 100 / S.adr                  # EMA50'ye uzaklık (ADR katı)
    S.lowAge = pd.Series(l).rolling(40, min_periods=10).apply(lambda w: len(w) - 1 - int(np.argmin(w)), raw=True).to_numpy()
    S.entryTrendOk = (c > S.ema50) if P.useTrend else np.ones(len(c), bool)
    S.stopLvl = _lowest(l, nC)

    S.bodyTol = P.bodyADR * S.adr / 100 * c
    S.bodyTolD = P.bodyADRD * S.adr / 100 * c
    S.touchTol = P.touchADR * S.adr / 100 * c
    S.rankTol = P.rankADR * S.adr / 100 * c
    S.wickAbs = P.wickADR * S.adr / 100 * c
    S.bodyTop = np.maximum(o, c)
    S.srcT = S.bodyTop if P.levelSrc == "Gövde" else h

    # KUTU modu: son boxN mumun gövde kutusu (bb) ve fitilli kutusu (hb), ADR katı
    bTopN = _highest(S.bodyTop, P.boxN)
    bBotN = _lowest(np.minimum(o, c), P.boxN)
    S.boxBodyVal = (bTopN / bBotN - 1) * 100 / S.adr
    S.boxHLVal = (_highest(h, P.boxN) / _lowest(l, P.boxN) - 1) * 100 / S.adr
    S.boxTop = bTopN
    S.b7Val = (_highest(S.bodyTop, 7) / _lowest(np.minimum(o, c), 7) - 1) * 100 / S.adr
    S.b7Ok = (S.b7Val <= P.b7Max) if P.b7Max > 0 else np.ones(len(c), bool)
    dn_ = np.r_[0.0, (c[1:] < c[:-1]).astype(float)]
    S.lcCnt = np.convolve(dn_, np.ones(5))[:len(c)]
    S.lcOk = (S.lcCnt <= P.lcMax) if P.lcMax > 0 else np.ones(len(c), bool)
    S.boxOk = (P.useBox & (S.boxBodyVal <= P.boxBody) & (S.boxHLVal <= P.boxHL) & S.candOk & S.jumpOk & S.volOk & S.redOk)
    S.restTop = _highest(S.bodyTop, P.restN)
    S.restOk = (P.restMode & (S.e50d >= P.restE50) & (S.tightVal <= P.restM) & (S.closeBoxVal <= P.restK)
                & (S.b7Val <= P.restB7) & (S.dd40 <= P.restDd) & S.candOk & S.jumpOk & S.volOk & S.redOk)

    S.ph = _pivot_high(h, P.pvL, P.pvR)
    S.smcPh = _pivot_high(h, P.smcL, P.smcR)
    return S



# ---------------------------------------------------------------- ana motor
def run(df: pd.DataFrame, P: Params | None = None) -> SimpleNamespace:
    """Tüm geçmişi mum mum işler. events: etiket ve Giriş olayları, trades: test işlemleri."""
    P = P or Params()
    n = len(df)
    S = prepare(df, P)
    o, h, l, c, v = S.o, S.h, S.l, S.c, S.v
    dates = df.index
    nC = P.nC

    events: list[dict] = []
    trades: list[dict] = []
    diag: dict[int, str] = {}       # mum -> "neden sinyal yok" harfleri (Pine hata ayıklama ile aynı)

    # --- durum değişkenleri (Pine "var") ---
    pP: list[float] = []
    pX: list[int] = []
    sP: list[float] = []
    sX: list[int] = []

    hLock = NAN
    hLockX = NAN
    lastSetupBar = None
    lastBreakBar = None
    lastCancelBar = None
    lblLive = False
    dLockPA = NAN
    dLockSl = NAN
    dLockXA = None
    lblBar = None
    lblStop = NAN
    lblClose = NAN
    armed = False
    curSetupEv = None
    lnY = NAN
    lnSl = NAN
    lnBar = None

    tInTrade = False
    tEntry = tSL = tTP = tPlanR = NAN
    tBar = None
    tDate = None

    # --------- yatay seviye taraması ---------
    def f_hor(t: int, L: float):
        maxI = min(P.lookback, t - 1)
        if maxI < 1:
            return 0, 0, 0, -1, -1, NAN, NAN, NAN, 0
        idx = t - np.arange(1, maxI + 1)
        bad = (S.bodyTop[idx] > L + S.bodyTol[t]) | (h[idx] > L + S.wickAbs[t])
        span = int(np.argmax(bad)) if bad.any() else maxI
        tc = tb = cl = 0
        firstT = lastT = -1
        if span > 0:
            d = np.abs(S.srcT[idx[:span]] - L)
            isT = d <= S.touchTol[t]
            tc = int(isT.sum())
            if tc > 0:
                prev = np.concatenate(([False], isT[:-1]))
                cl = int(np.count_nonzero(isT & ~prev))
                pos = np.flatnonzero(isT)
                lastT = int(pos[0]) + 1
                firstT = int(pos[-1]) + 1
            mk = d <= S.rankTol[t]
            if P.tbCl:
                pv = np.concatenate(([False], mk[:-1]))
                tb = int(np.count_nonzero(mk & ~pv))
            else:
                tb = int(mk.sum())

        
        mxH = L
        if firstT >= 0:
            mxH = max(mxH, float(h[t - firstT:t + 1].max()))
        cl_ = c[t - nC + 1:t + 1]
        gs = float(((L - cl_) / cl_ * 100).sum())
        aG = gs / nC / S.adr[t]
        lG = (L - c[t]) / c[t] * 100 / S.adr[t]
        ov = (mxH - L) / c[t] * 100 / S.adr[t]
        return span, tc, tb, firstT, lastT, aG, lG, ov, cl

    def f_ok(sp, tc, ft, lt, aG, lG, ov, cl, tb) -> bool:
        return (P.allowHoriz and sp >= P.minSpanH and tc >= P.minTouches and lt >= 0
                and lt <= P.lastTouchMax and (ft - lt) >= P.touchSpan and aG <= P.nearADRH
                and lG <= P.lastNearH and lG >= 0 and ov <= P.maxOv
                and cl >= P.minClusters and tb >= P.minTb)

    def hor_best(t: int):
        r = dict(hL=NAN, hSpan=0, hTc=0, hTb=-1, hFirst=0, hLt=-1, hCl=0, hOv=NAN, near="")
        nearFail = None
        for k in range(1, max(nC, P.lastTouchMax) + 10):
            if k < t:
                cand = float(S.srcT[t - k])
                sp, tc, tb, ft, lt, ag, lg, ov, cl = f_hor(t, cand)
                fl = []
                if sp < P.minSpanH:
                    fl.append(f"sp{sp}")
                if tc < P.minTouches:
                    fl.append(f"tc{tc}")
                if lt < 0 or lt > P.lastTouchMax:
                    fl.append(f"lt{lt}")
                if (ft - lt) < P.touchSpan:
                    fl.append(f"rg{ft - lt}")
                if not (ag <= P.nearADRH):
                    fl.append(f"ag{ag:.1f}")
                if not (lg <= P.lastNearH and lg >= 0):
                    fl.append(f"lg{lg:.1f}")
                if not (ov <= P.maxOv):
                    fl.append(f"ov{ov:.1f}")
                if cl < P.minClusters:
                    fl.append(f"cl{cl}")
                if tb < P.minTb:
                    fl.append(f"tb{tb}")
                if nearFail is None or len(fl) < len(nearFail):
                    nearFail = fl
                if f_ok(sp, tc, ft, lt, ag, lg, ov, cl, tb) and (
                        tb > r["hTb"] or (tb == r["hTb"] and cand > nz(r["hL"], 0.0))):
                    r.update(hL=cand, hSpan=sp, hTc=tc, hTb=tb, hFirst=ft, hLt=lt, hCl=cl, hOv=ov)
        r["near"] = "H:" + ",".join(nearFail or ["-"])
        return r

    # --------- düşen çizgi taraması ---------
    def falling_best(t: int):
        pPt = list(pP)
        pXt = list(pX)
        if h[t] >= h[t - 1]:
            pPt.append(float(h[t]))
            pXt.append(t)
        best = dict(tc=0, tcT=-1, xA=0, pa=NAN, sl=0.0, ln=NAN, ag=NAN, lg=NAN, sn=NAN, ov=NAN, cl=0, info="")
        rejW = rejB = 0
        dInfo = ""
        dSc = -1
        m = len(pPt)
        adr_t, c_t = S.adr[t], c[t]
        for ia in range(0, m - 1):
            for ib in range(ia + 1, m):
                xA, xB = pXt[ia], pXt[ib]
                if not (xB - xA >= P.minSpan and t - xA <= P.lookback):
                    continue
                pa, pb = pPt[ia], pPt[ib]
                sl = (pb - pa) / (xB - xA)
                ii = np.arange(0, t - xA + 1)
                bars = t - ii
                lv = pb + sl * (t - ii - xB)
                hh = h[bars]
                if (hh > lv + S.wickAbs[t]).any():
                    rejW += 1
                    continue  # iğne çok taşıyor
                mxOv = max(0.0, float(((hh - lv) / c_t * 100 / adr_t).max()))
                bt = S.bodyTop[bars]
                mxBody = max(0.0, float(((bt - lv) / c_t * 100 / adr_t).max()))
                viol = int((bt > lv + S.bodyTolD[t]).sum())
                tc = int((hh >= lv - S.touchTol[t]).sum())
                isTb = np.abs(hh - lv) <= S.rankTol[t]
                tcT = int(isTb.sum())
                xb = isTb[1:]
                pos_ = np.flatnonzero(xb)
                clD = (1 + int(np.count_nonzero(np.diff(pos_) > P.clMerge))) if len(pos_) > 0 else 0
                lineLen = t - xA + 1
                violBad = viol > P.maxViol or (viol / lineLen * 100 > P.violPct) or mxBody > P.bodyPokeMax
                belowBad = False
                if P.useBelow:
                    for i in range(0, 5):
                        lvB = pb + sl * (t - i - xB)
                        if lvB < S.bodyTop[t - i] - S.bodyTolD[t]:
                            belowBad = True
                            break
                if violBad or belowBad:
                    rejB += 1
                    continue
                lnN = pb + sl * (t - xB)
                cl_ = c[t - nC + 1:t + 1]
                lvl_ = pb + sl * (t - np.arange(0, nC) - xB)  # i = 0..nC-1 -> c[t-i]
                gs = float(((lvl_ - c[t - np.arange(0, nC)]) / c[t - np.arange(0, nC)] * 100).sum())
                aG = gs / nC / adr_t
                lG = (lnN - c_t) / c_t * 100 / adr_t
                sN = sl * (xB - xA) / pa * 100 / adr_t
                cTouch = tc >= P.minTouches
                cType = (P.allowFlat and -P.flatBand <= sN <= P.flatUp) or (
                    P.allowDesc and sN < -P.flatBand and sN >= -P.maxDesc)
                cAvg = aG <= P.nearADR
                cLast = lG <= P.lastNear and lG >= 0
                score = int(cTouch) + int(cType) + int(cAvg) + int(cLast)
                if score > dSc:
                    dSc = score
                    flz = []
                    if not cTouch:
                        flz.append(f"t{tc}")
                    if not cType:
                        flz.append(f"sn{sN:.1f}")
                    if not cAvg:
                        flz.append(f"ag{aG:.1f}")
                    if not cLast:
                        flz.append(f"lg{lG:.1f}")
                    if mxOv > P.maxOv:
                        flz.append(f"w{mxOv:.1f}")
                    if tcT < P.minTcD:
                        flz.append(f"dt{tcT}")
                    if clD < P.minClD:
                        flz.append(f"cl{clD}")
                    dInfo = ",".join(flz) or "-"
                if score == 4 and mxOv <= P.maxOv and tcT >= P.minTcD and clD >= P.minClD:
                    if na(best["pa"]) or tcT > best["tcT"] or (tcT == best["tcT"] and pa > best["pa"]):
                        best.update(tc=tc, tcT=tcT, xA=xA, pa=pa, sl=sl, ln=lnN, ag=aG, lg=lG, sn=sN, ov=mxOv, cl=clD,
                                tps=[int(x_) for x_ in np.flatnonzero(isTb)])
        best["info"] = f"D:eleme iğne{rejW} gövde{rejB} " + (f"en iyi aday {dInfo}" if dSc >= 0 else "aday yok")
        return best

    # ================================================================ döngü
    for t in range(n):
        # --- pivotlar (Pine'da tüm mumlarda toplanır) ---
        if not na(S.ph[t]):
            pP.append(float(S.ph[t]))
            pX.append(t - P.pvR)
            if len(pP) > 20:
                pP.pop(0)
                pX.pop(0)

        # --- SMC swing tepeleri: alınmış / eski olanları sil, yenisini ekle ---
        if sP:
            keep = [i for i in range(len(sP)) if not (h[t] > sP[i] or t - sX[i] > P.smcLook)]
            sP = [sP[i] for i in keep]
            sX = [sX[i] for i in keep]
        if not na(S.smcPh[t]):
            sP.append(float(S.smcPh[t]))
            sX.append(t - P.smcR)
            if len(sP) > 60:
                sP.pop(0)
                sX.pop(0)

        if t < P.warmup:
            continue

        adr_t = S.adr[t]
        close_t = c[t]
        bodyTol_t = S.bodyTol[t]


        # --- aday çizgiler ---
        hz = hor_best(t) if S.tightCore[t] else dict(hL=NAN, hSpan=0, hTc=0, hTb=-1, hFirst=0, hLt=-1, hCl=0, hOv=NAN)
        fb = falling_best(t) if S.tightOk[t] else dict(tc=0, tcT=-1, xA=0, pa=NAN, sl=0.0, ln=NAN,
                                                       ag=NAN, lg=NAN, sn=NAN, ov=NAN)
        hL, hSpan, hTb, hFirst = hz["hL"], hz["hSpan"], hz["hTb"], hz["hFirst"]
        boxMode = False
        if P.useBox and bool(S.boxOk[t]):
            ddOk0 = (P.ddMax <= 0) or na(S.dd40[t]) or S.dd40[t] <= P.ddMax
            normalOk = ((hSpan > 0 or fb["tc"] > 0) and bool(S.tightCore[t]) and bool(S.emaOk[t])
                        and ddOk0 and bool(S.rallyOk[t]))
            if not normalOk:
                # çizgi yok ya da trend filtreleri engelliyor ama uzun yatay kutu var: direnç = kutunun gövde tepesi
                boxMode = True
                fb = dict(tc=0, tcT=-1, xA=0, pa=NAN, sl=0.0, ln=NAN, ag=NAN, lg=NAN, sn=NAN, ov=NAN, cl=0, info="")
                hz = dict(hz)
                hL, hSpan, hTb, hFirst = float(S.boxTop[t]), P.boxN, 0, P.boxN
                hz.update(hL=hL, hSpan=hSpan, hTb=0, hFirst=hFirst, hTc=0)
        restMode = False
        if P.restMode and (not boxMode) and bool(S.restOk[t]):
            ddOk1 = (P.ddMax <= 0) or na(S.dd40[t]) or S.dd40[t] <= P.ddMax
            normalOk1 = ((hSpan > 0 or fb["tc"] > 0) and bool(S.tightCore[t]) and bool(S.emaOk[t])
                         and ddOk1 and bool(S.rallyOk[t]))
            if not normalOk1:
                # normal çizgi yolu etiket üretemiyor: direnç = son restN mumun gövde tepesi (DİNLENME)
                boxMode = True
                restMode = True
                fb = dict(tc=0, tcT=-1, xA=0, pa=NAN, sl=0.0, ln=NAN, ag=NAN, lg=NAN, sn=NAN, ov=NAN, cl=0, info="")
                hz = dict(hz)
                hL, hSpan, hTb, hFirst = float(S.restTop[t]), P.restN, 0, P.restN
                hz.update(hL=hL, hSpan=hSpan, hTb=0, hFirst=hFirst, hTc=0)
        bestTc, bestTcT, bestXA = fb["tc"], fb["tcT"], fb["xA"]
        bestPA, bestSl, bestLn, bestSN = fb["pa"], fb["sl"], fb["ln"], fb["sn"]

        foundD = bestTc > 0
        foundH = hSpan > 0
        found = foundD or foundH
        flatD = foundD and abs(nz(bestSN)) <= P.flatBand

        # --- kilitler ve kırılımlar ---
        brokeOut = (not na(hLock)) and close_t > hLock + bodyTol_t
        if brokeOut:
            lastBreakBar = t
        stale = (not na(hLock)) and lastSetupBar is not None and t - lastSetupBar > P.holdBars
        if brokeOut or stale:
            hLock = NAN
            hLockX = NAN

        dLn = NAN
        if not na(dLockPA):
            dLn = dLockPA + dLockSl * (t - dLockXA)
        dBroke = (not na(dLn)) and close_t > dLn + bodyTol_t
        if dBroke:
            lastBreakBar = t
        dStale = (not na(dLn)) and lastSetupBar is not None and t - lastSetupBar > P.holdBars
        if dBroke or dStale:
            dLockPA = NAN
            dLockSl = NAN
            dLockXA = None
            dLn = NAN

        # --- mod seçimi ---
        if not na(hLock):
            useH = True
        elif not na(dLockPA):
            useH = False
        elif P.modePref == "Düşen":
            useH = foundH and not foundD
        elif P.modePref == "Yatay":
            useH = foundH
        else:
            useH = foundH and ((not foundD) or flatD or hTb + P.hPrefer > bestTcT or bestTcT < P.dMinWithH
                          or (P.flatPrefer > 0 and abs(nz(bestSN)) < P.flatPrefer))
            if useH and P.fallbackD and foundD and not flatD and bestTcT >= P.fbMinDt and not (bool(S.riseOkN[t]) and bool(S.slopeOkN[t])):
                useH = False

        riseOkSel = S.riseOkN[t] if useH else S.riseOkW[t]
        slopeOkSel = S.slopeOkN[t] if useH else S.slopeOkW[t]
        modeOk = bool(riseOkSel) and bool(slopeOkSel)

        lnForY = nz(hLock, hL) if useH else nz(dLn, bestLn)
        yVal = (lnForY - close_t) / close_t * 100 / adr_t
        yOk = (not P.useClose) or na(yVal) or yVal <= P.closeNearY
        dOkH = (not useH) or (not P.useLowsH) or S.lowDiff[t] <= P.lowUpH

        ddOk = (P.ddMax <= 0) or na(S.dd40[t]) or S.dd40[t] <= P.ddMax
        dnOk = (P.dnMinTb <= 0) or boxMode or useH or not (S.emaSlope[t] <= P.dnSlope and S.emaDist[t] < 0) or bestTcT >= P.dnMinTb
        spOk = (P.dnMinSp <= 0) or boxMode or useH or na(bestXA) or (t - int(bestXA) + 1) >= P.dnMinSp
        hdOk = (not P.hDnBlock) or boxMode or (not useH) or not (S.emaSlope[t] <= P.dnSlope and S.emaDist[t] < 0)
        ybOk = (P.yBodyMax <= 0) or boxMode or (not useH) or S.bodyBox10[t] <= P.yBodyMax
        shrOk = (P.shrinkMinD <= 0) or boxMode or useH or na(S.shrinkVal[t]) or S.shrinkVal[t] >= P.shrinkMinD
        ebOk = boxMode or useH or not (S.emaDist[t] < 0 and S.slopeVal[t] < P.dnBelowSlope)
        slG = boxMode or na(S.slopeVal[t]) or S.slopeVal[t] >= P.slopeMinG
        riG = boxMode or na(S.riseVal[t]) or S.riseVal[t] >= P.riseMinG
        setupRaw = (found and (bool(S.tightCore[t]) or boxMode) and modeOk and yOk and dOkH and bool(S.candOk[t])
                    and bool(S.jumpOk[t]) and bool(S.volOk[t]) and bool(S.redOk[t]) and (bool(S.emaOk[t]) or boxMode)
                    and (ddOk or boxMode) and (bool(S.rallyOk[t]) or boxMode) and (bool(S.b7Ok[t]) or restMode) and bool(S.lcOk[t]) and dnOk and spOk and hdOk and ybOk and shrOk and ebOk and slG and riG)
        blocked = ((lastBreakBar is not None and t - lastBreakBar <= P.cooldown)
                   or (lastCancelBar is not None and t - lastCancelBar <= P.cancelBlock)
                   or (lastSetupBar is not None and t - lastSetupBar <= P.cooldown and not lblLive))
        why = []
          
        if P.useBox:
            if boxMode:
                why.append("RS" if restMode else "K")
            elif not (S.boxBodyVal[t] <= P.boxBody and S.boxHLVal[t] <= P.boxHL):
                why.append(f"bx{S.boxBodyVal[t]:.2f}/{S.boxHLVal[t]:.2f}")        
        if not (S.tightLong[t] or S.tightShort[t]) and not boxMode:
            if S.tightVal[t] > P.tightADR:
                why.append("m")
            if S.shrinkVal[t] > P.shrink:
                why.append("r")
            if S.closeBoxVal[t] > P.closeBoxADR:
                why.append("k")
        if not S.lowsOk[t]:
            why.append(f"d{S.lowDiff[t]:.2f}")
        if not riseOkSel:
            why.append(f"u{S.riseVal[t]:.2f}")
        if not slopeOkSel:
            why.append(f"s{S.slopeVal[t]:.2f}")
        if not yOk:
            why.append(f"y{yVal:.2f}")
        if not dOkH:
            why.append("D")
        if not S.candOk[t]:
            why.append(f"c{S.candRng[t]:.2f}/p{S.closePos[t]:.2f}")
        if not S.jumpOk[t]:
            why.append(f"j{S.jump[t]:.2f}")
        if not S.volOk[t]:
            why.append(f"v{S.volRatio[t]:.2f}")
        if not S.redOk[t]:
            why.append(f"g{S.redSig[t]:.2f}")
        if not S.emaOk[t] and not boxMode:
            why.append(f"e{S.emaSlope[t]:.2f}/{S.emaDist[t]:.2f}")
        if not ddOk and not boxMode:
            why.append(f"T{S.dd40[t]:.1f}")
        if not S.rallyOk[t] and not boxMode:
            why.append("R")
        if not S.b7Ok[t]:
            why.append(f"b7_{S.b7Val[t]:.2f}")
        if not S.lcOk[t]:
            why.append(f"lc{int(S.lcCnt[t])}")
        if not dnOk:
            why.append(f"dn{bestTcT}")
        if not shrOk:
            why.append(f"rl{S.shrinkVal[t]:.2f}")
        if not ebOk:
            why.append("eb")
        if not spOk:
            why.append(f"sp{t - int(bestXA) + 1}")
        if not (np.isnan(S.bodyFr[t]) or S.bodyFr[t] >= P.bodyFrac) and not boxMode:
            why.append(f"bf{S.bodyFr[t]:.2f}")
        if not hdOk:
            why.append("H")
        if not ybOk:
            why.append("Y")
        if S.tightOk[t] and not found:
            why.append("L[" + fb.get("info", "") + " " + hz.get("near", "") + "]")
        strong = bool(S.strong[t])
        setup = setupRaw and (not brokeOut) and (not blocked) and ((not P.onlyStrong) or strong)

        if setupRaw and (blocked or brokeOut):
            _b = ""
            if lastBreakBar is not None and t - lastBreakBar <= P.cooldown:
                _b += "-kirilim"
            if lastSetupBar is not None and t - lastSetupBar <= P.cooldown and not lblLive:
                _b += "-setup"
            if brokeOut:
                _b += "-cikis"
            why.append("B" + _b)
        diag[t] = " ".join(why)

        if setup and useH and na(hLock):
            hLock = hL
            hLockX = t - min(hFirst, P.maxLineBack)
        if setup and (not useH) and na(dLockPA):
            dLockPA = bestPA
            dLockSl = bestSl
            dLockXA = bestXA
            dLn = bestLn

        selLn = nz(hLock, hL) if useH else nz(dLn, bestLn)
        selSl = 0.0 if useH else nz(dLockSl, bestSl)

        # --- iptal ve tetik ---
        stopInv = NAN if na(lblStop) else lblStop - P.stopBuf * adr_t / 100 * close_t
        redBody = (o[t] - close_t) / close_t * 100 / adr_t
        stopHit = P.useStop and (not na(stopInv)) and close_t < stopInv
        redHit = P.useRedKill and lblBar is not None and t > lblBar and redBody >= P.redKillADR
        dropHit = (P.useDrop and (not na(lblClose)) and lblBar is not None and t > lblBar
                   and (lblClose - close_t) / close_t * 100 / adr_t >= P.dropADR)
        invalid = armed and (stopHit or redHit or dropHit)

        if invalid:
            armed = False
            hLock = NAN
            hLockX = NAN
            dLockPA = NAN
            dLockSl = NAN
            dLockXA = None
            lastCancelBar = t
            lblLive = False
            if P.cancelClearsCooldown:
                lastSetupBar = None
            sd = curSetupEv["date"] if curSetupEv is not None else None
            if curSetupEv is not None:
                curSetupEv["cancelled"] = True
                curSetupEv["cancel_t"] = t
            reason = "stop" if stopHit else ("kırmızı mum" if redHit else "düşüş")
            if curSetupEv is not None:
                curSetupEv["cancel_reason"] = reason
            events.append(dict(type="iptal", t=t, date=dates[t], close=float(close_t), setup_date=sd, reason=reason))

        projNow = lnY + lnSl * (t - lnBar) if lnBar is not None else NAN
        inWin = armed and lblBar is not None and t > lblBar and t - lblBar <= P.trigWin
        trigger = (inWin and (not invalid) and close_t > projNow and bool(S.entryTrendOk[t])
                   and ((not P.useAboveLbl) or close_t > nz(lblClose, 0.0))
                   and (P.trigVol == 0 or v[t] > S.volAvg[t] * P.trigVol))
        if trigger:
            armed = False
            lastBreakBar = t
            if curSetupEv is not None:
                curSetupEv["triggered"] = True
        if armed and lblBar is not None and t - lblBar >= P.trigWin:
            armed = False

        # --- setup kaydı ---
        newSetup = setup and (not invalid) and (lastSetupBar is None or t - lastSetupBar > P.cooldown)
        if setup and not invalid:
            lastSetupBar = t
            lnY = selLn
            lnSl = selSl
            lnBar = t
            if newSetup:
                lblBar = t
                lblStop = float(S.stopLvl[t])
                lblClose = float(close_t)
                lblLive = True
                armed = True
        if newSetup:
            curSetupEv = dict(
                type="setup", t=t, date=dates[t], close=float(close_t),
                mode="Kutu" if boxMode else ("Yatay" if useH else "Düşen"), line=float(selLn), strong=strong,
                short=bool(S.tightShort[t] and not S.tightLong[t]),
                r=float(S.shrinkVal[t]), k=float(S.closeBoxVal[t]), m=float(S.tightVal[t]),
                touches=int(hz["hTc"] if useH else bestTc), dt=int(hTb if useH else bestTcT),
                dcl=int(0 if useH else fb.get("cl", 0)), sn=float(nz(bestSN, 0.0)),                   
                sp=int(0 if useH else (t - int(bestXA) + 1)),
                tpos=("" if useH else ",".join(str(x_) for x_ in fb.get("tps", [])[:10])), 
                hnear=str(hz.get("near", "")),
                es=float(nz(S.emaSlope[t], 0.0)), ed=float(nz(S.emaDist[t], 0.0)), dd=float(nz(S.dd40[t], 0.0)),
                e50=float(nz(S.e50d[t], 0.0)), la=int(nz(S.lowAge[t], 0)),
                v=float(nz(S.volRatio[t], 0.0)), j=float(nz(S.jump[t], 0.0)), adr=float(adr_t),
                stop=float(S.stopLvl[t]), cancelled=False, triggered=False,
            )
            events.append(curSetupEv)

        # --- Giriş: SL / TP ---
        entryRisk = close_t - l[t]
        entryTP = close_t + P.tpMult * entryRisk
        tpIsSmc = False
        if trigger and entryRisk > 0 and P.tpMode == "SMC direnç" and sP:
            smcBuf = P.smcBufADR * adr_t / 100 * close_t
            bestTP = NAN
            for lvl in sP:
                lvlTP = lvl - smcBuf
                if lvlTP - close_t >= P.minRR * entryRisk and (na(bestTP) or lvlTP < bestTP):
                    bestTP = lvlTP
            if not na(bestTP):
                entryTP = min(bestTP, close_t + P.tpMaxR * entryRisk) if P.tpMaxR > 0 else bestTP
                tpIsSmc = True
        entryRiskPct = entryRisk / close_t * 100
        entryTpPct = (entryTP / close_t - 1) * 100
        entryTpR = (entryTP - close_t) / entryRisk if entryRisk > 0 else NAN

        if trigger and entryRisk > 0:
            events.append(dict(
                type="giris", t=t, date=dates[t], close=float(close_t), sl=float(l[t]),
                tp=float(entryTP), riskPct=float(entryRiskPct), tpPct=float(entryTpPct),
                tpR=float(entryTpR), smc=tpIsSmc, line=float(nz(lnY, NAN)),
                mode="Yatay" if lnSl == 0 else "Düşen",
                setup_date=curSetupEv["date"] if curSetupEv is not None else None,
            ))

        # --- geriye dönük test ---
        if tInTrade and t > tBar:
            exitPx = NAN
            why = 0
            if o[t] <= tSL:
                exitPx, why = o[t], 2
            elif o[t] >= tTP:
                exitPx, why = o[t], 1
            elif l[t] <= tSL:
                exitPx, why = tSL, 2
            elif h[t] >= tTP:
                exitPx, why = tTP, 1
            elif t - tBar >= P.maxHold:
                exitPx, why = close_t, 3
            if not na(exitPx):
                rr = (exitPx - tEntry) / (tEntry - tSL)
                trades.append(dict(entry_date=tDate, exit_date=dates[t], entry=tEntry, exit=float(exitPx),
                                   sl=tSL, tp=tTP, planR=tPlanR, R=float(rr), why=why,
                                   ret=float((exitPx / tEntry - 1) * 100), bars=t - tBar))
                tInTrade = False

        if trigger and entryRisk > 0 and not tInTrade:
            tInTrade = True
            tEntry = float(close_t)
            tSL = float(l[t])
            tTP = float(entryTP)
            tPlanR = float(entryTpR)
            tBar = t
            tDate = dates[t]

    return SimpleNamespace(events=events, trades=trades, n=n, open_trade=tInTrade,
                           S=S, dates=dates, diag=diag)


def summarize(trades: list[dict]) -> dict:
    """Tablodaki satırların aynısı."""
    k = len(trades)
    if k == 0:
        return dict(n=0)
    R = np.array([t["R"] for t in trades])
    win = R > 0
    gWin = R[win].sum()
    gLoss = -R[~win].sum()
    plan = np.nanmean([t["planR"] for t in trades])
    return dict(
        n=k,
        winRate=float(win.mean() * 100),
        tp=sum(t["why"] == 1 for t in trades),
        sl=sum(t["why"] == 2 for t in trades),
        time=sum(t["why"] == 3 for t in trades),
        avgRet=float(np.mean([t["ret"] for t in trades])),
        avgR=float(R.mean()),
        profitFactor=float(gWin / gLoss) if gLoss > 0 else float("inf"),
        avgPlanR=float(plan),
        breakEven=float(100 / (1 + plan)),
    )

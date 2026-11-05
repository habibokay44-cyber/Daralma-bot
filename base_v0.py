"""Base kırılımı v0 (05.11.2026'da 7 base örneğinden sabitlendi; değiştirilmeyecek, ancak yeni sürüm açılır).

KURAL (sinyal günü u = kırılım günü):
  base   = u'dan önceki 10 mum (u-10 .. u-1); üst = en yüksek, alt = en düşük
  B1: base yüksekliği (üst / alt - 1) <= 3.3 ADR            (ADR: 20 günlük ortalama gün içi aralık %, u-1'de)
  B2: u'dan önceki 20 mumda üst sınıra 0.3 ADR yakın en az 2 tepe (temas) ve bu 20 mumda üstten 0.3 ADR'den
      daha yüksek tepe yok (direnç gerçekten base'in üstü)
  B3: kapanış[u] > üst ve kapanış[u-1] <= üst (ilk kırılım)
  Son 10 mumda başka v0 sinyali varsa yenisi verilmez. EMA şartı ve stage filtresi YOK.

ÖNCEDEN YAZILMIŞ TESTLER (05.11.2026):
  T1 yoğunluk: 1000 mumda en fazla 15 v0 sinyali.
  T2 getiri: aynı basit çıkış kuralıyla v0'ın ortalama R'si, göstergenin mevcut Giriş sinyallerinden düşük olmamalı.
     Çıkış kuralı (ikisi için aynı): alış = sinyal günü kapanışı, stop = sinyalden önceki 10 mumun en düşüğü,
     stop değerse çıkış (gap varsa açılış), değmezse 20 gün sonra kapanış. R = (çıkış - alış) / (alış - stop).
  T3 kör test: 2023 sonrası v0 sinyallerinden rastgele 40'ı (hisse başına en fazla 2, tohum 56) butonlu grafik
     olarak gönderilir; grafik sinyal gününde biter (sonrası görünmez). KABUL: işaretlenenlerin >= %50'si 'alırdım'.
  Hisse evreni: BIST listesinden rastgele 150 hisse (tohum 56), 1000 günlük veri.
Çalıştırma: python base_v0.py --telegram
"""
from __future__ import annotations

import json
import random
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

import kayit
from fd_core import Params, run
from grafik import gonder_butonlu
from scan import fetch_tv_all, get_tickers, telegram_send

MOD = "BaseV0"
W, WT, HMAX, TOL, NTEM, BEKLE, GUN = 10, 20, 3.3, 0.3, 2, 10, 20


def sinyaller(df: pd.DataFrame) -> list[dict]:
    h, l, c = (df[k].to_numpy(float) for k in ("High", "Low", "Close"))
    adr = (pd.Series(h / l).rolling(20).mean().to_numpy() - 1) * 100
    out, son = [], -999
    for u in range(max(WT, 21) + 1, len(c)):
        A = adr[u - 1]
        if np.isnan(A) or A <= 0 or u - son <= BEKLE:
            continue
        top, bot = h[u - W:u].max(), l[u - W:u].min()
        if not (c[u] > top >= c[u - 1]):
            continue
        if (top / bot - 1) * 100 / A > HMAX:
            continue
        hh = h[u - WT:u]
        if hh.max() > top * (1 + TOL * A / 100):  # 20 mumda base üstünden belirgin yüksek tepe varsa direnç bu değil
            continue
        if int(np.sum(hh >= top * (1 - TOL * A / 100))) < NTEM:
            continue
        son = u
        out.append(dict(type="giris", t=u, date=df.index[u], mode=MOD, line=float(top), close=float(c[u]),
                        stop=float(bot), sp=0))
    return out


def sim(df: pd.DataFrame, t: int):
    o, h, l, c = (df[k].to_numpy(float) for k in ("Open", "High", "Low", "Close"))
    if t + GUN >= len(c) or t < W:
        return None
    entry, stop = c[t], l[t - W:t].min()
    if entry <= stop:
        return None
    for u in range(t + 1, t + GUN + 1):
        if l[u] <= stop:
            return (min(o[u], stop) - entry) / (entry - stop)
    return (c[t + GUN] - entry) / (entry - stop)


def ozet(R):
    R = np.array([x for x in R if x is not None])
    if not len(R):
        return "işlem 0", np.nan
    pf = R[R > 0].sum() / -R[R <= 0].sum() if (R <= 0).any() else np.inf
    return f"işlem {len(R)} kazanma %{100 * (R > 0).mean():.0f} R{R.mean():+.2f} PF{pf:.2f}", R.mean()


def main():
    rnd = random.Random(56)
    tick = get_tickers()
    syms = sorted(rnd.sample(tick, min(150, len(tick))))
    frames = fetch_tv_all(syms, n_bars=1000, budget=14 * 60)
    bars, sig, Rv, Rg = 0, [], [], []
    for s, df in frames.items():
        try:
            v = sinyaller(df)
            gi = [e for e in run(df, Params()).events if e["type"] == "giris"]
        except Exception as ex:  # noqa: BLE001
            print(f"[uyarı] {s}: {ex}")
            continue
        bars += len(df)
        sig += [(s, df, e) for e in v]
        Rv += [sim(df, e["t"]) for e in v]
        Rg += [sim(df, int(e["t"])) for e in gi]
    dens = len(sig) / bars * 1000 if bars else 0
    tv, mv = ozet(Rv)
    tg, mg = ozet(Rg)
    out = [f"🧱 Base v0 testi ({len(frames)} hisse, {bars} mum)",
           f"• T1 yoğunluk: {dens:.1f} sinyal / 1000 mum (sınır 15) -> {'✅' if dens <= 15 else '❌'}",
           f"• T2 aynı çıkışla: v0 {tv} | mevcut Giriş {tg} -> {'✅' if mv >= mg else '❌'}"]
    # T3 kör örneklem
    aday = [x for x in sig if x[2]["date"] >= pd.Timestamp("2023-01-01")]
    rnd.shuffle(aday)
    secim, say = [], {}
    for s, df, e in aday:
        if say.get(s, 0) >= 2:
            continue
        say[s] = say.get(s, 0) + 1
        secim.append((s, df.iloc[:e["t"] + 1], e))
        if len(secim) == 40:
            break
    secim.sort(key=lambda x: x[2]["date"])
    out.append(f"• T3 kör test: {len(secim)} grafik geliyor (grafik sinyal gününde biter). Kabul: işaretlenenlerin >= %50'si ✅ Alırdım.")
    txt = "\n".join(out)
    print(txt)
    if "--telegram" not in sys.argv:
        return
    telegram_send(txt)
    rows = kayit.load()
    var = {kayit.key(r["hisse"], r["etiket_tarihi"]) for r in rows}
    bug = f"{pd.Timestamp.now(tz='Europe/Istanbul'):%Y-%m-%d}"
    for s, df, e in secim:
        k = kayit.key(s, f"{e['date']:%Y-%m-%d}")
        if k not in var:
            r = {c: "" for c in kayit.COLS}
            r.update(bildirim_tarihi=bug, hisse=s, etiket_tarihi=f"{e['date']:%Y-%m-%d}", mod=MOD,
                     kapanis=f"{e['close']:.4g}", direnc=f"{e['line']:.4g}", giris_tarihi=f"{e['date']:%Y-%m-%d}")
            rows.append(r)
    kayit.save(rows)
    esle = {}
    for i in range(0, len(secim), 30):
        esle.update(gonder_butonlu(secim[i:i + 30]))
    ep = kayit.F.parent / "tg_mesaj.json"
    try:
        eski = json.loads(ep.read_text())
    except Exception:  # noqa: BLE001
        eski = {}
    eski.update(esle)
    ep.write_text(json.dumps(dict(list(eski.items())[-500:]), indent=0))
    print(f"{len(esle)} grafik gönderildi")


if __name__ == "__main__":
    main()

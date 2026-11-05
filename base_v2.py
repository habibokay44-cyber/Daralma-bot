"""Base kırılımı v2 (05.11.2026). Direnç karşılaştırması: senin çizginle v0'ın çizgisi 22/28'de 0.5 ADR içinde
(çizginin YERİ doğru). Ayıran şey: 'direnç yok' dediğin 8 grafiğin 8'i almazdım; notların "tek temas, diğeri giriş mumu".
v0, kırılımdan hemen önceki mumu ikinci temas sayıyordu. v2 sadece bunu değiştirir.

KURAL (v0'dan farkı * ile):
  base = u'dan önceki 10 mum; üst = en yüksek fitil, alt = en düşük; yükseklik <= 3.3 ADR
  20 mumda üstten 0.3 ADR'den yüksek tepe yok
  B2*: temaslar SADECE u-20 .. u-3 arasında sayılır (kırılımdan önceki son 2 mum sayılmaz); fitili üst sınıra
       0.3 ADR yakın tepeler, yan yana ya da arasında 1 mum olanlar tek temas; en az 2 ayrı temas
  B3: kapanış[u] > üst ve kapanış[u-1] <= üst; son 10 mumda başka sinyal yok

ÖNCEDEN YAZILMIŞ TESTLER (05.11.2026; v1 ile aynı ölçütler):
  İ1 (örnek içi, v0'ın işaretli grafikleri): almazdım'ların >= 10/15'i elenir VE alırdım'ların <= 6/24'ü elenir
  T1 yoğunluk >= 3 / 1000 mum; T2 aynı çıkışla R (bilgi)
  İ2 kör test: İ1 geçerse 40 yeni grafik (daha önce gösterilmemiş, tohum 58). KABUL: >= %70 alırdım.
Çalıştırma: python base_v2.py --telegram
"""
from __future__ import annotations

import json
import random
import sys

import numpy as np
import pandas as pd

import kayit
from base_v0 import ozet, sim, sinyaller as sinyaller_v0
from grafik import gonder_butonlu
from scan import fetch_tv_all, get_tickers, telegram_send

MOD = "BaseV2"
W, WT, HMAX, TOL_UST, TOL_TEM, ARA, BEKLE = 10, 20, 3.3, 0.3, 0.3, 2, 10


def temas_kumeleri(idx: np.ndarray) -> list[list[int]]:
    km: list[list[int]] = []
    for i in idx:
        if km and i - km[-1][-1] <= ARA:
            km[-1].append(int(i))
        else:
            km.append([int(i)])
    return km


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
        if hh.max() > top * (1 + TOL_UST * A / 100):
            continue
        km = temas_kumeleri(np.where(hh[:-2] >= top * (1 - TOL_TEM * A / 100))[0])   # u-20 .. u-3
        if len(km) < 2:
            continue
        son = u
        out.append(dict(type="giris", t=u, date=df.index[u], mode=MOD, line=float(top), close=float(c[u]),
                        stop=float(bot), sp=0, temas=len(km)))
    return out


def main():
    rows = kayit.load()
    eski = [r for r in rows if r.get("mod") == "BaseV0" and (r.get("isaret") or "") in ("a", "g", "h")]
    gosterilen = {kayit.key(r["hisse"], r["etiket_tarihi"]) for r in rows if r.get("mod") in ("BaseV0", "BaseV1", "BaseV2", "Base")}
    rnd = random.Random(58)
    tick = get_tickers()
    evren = sorted(random.Random(56).sample(tick, min(150, len(tick))))
    syms = sorted(set(evren) | {r["hisse"] for r in eski})
    frames = fetch_tv_all(syms, n_bars=1000, budget=16 * 60)
    out = ["🧱 Base v2 testi (son 2 mum temas sayılmaz)"]
    # İ1 örnek içi
    ka = kh = na_ = nh = 0
    elenen = []
    for r in eski:
        df = frames.get(r["hisse"])
        if df is None:
            continue
        d = pd.Timestamp(r["etiket_tarihi"])
        var = any(e["date"] == d for e in sinyaller(df))
        if r["isaret"] == "h":
            nh += 1
            kh += var
        else:
            na_ += 1
            ka += var
            if not var:
                elenen.append(r["hisse"])
    el_h, el_a = nh - kh, na_ - ka
    i1 = el_h >= 10 and el_a <= 6
    out.append(f"• İ1 örnek içi: almazdım {nh} -> {el_h} elendi (en az 10) | alırdım {na_} -> {el_a} elendi (en fazla 6)"
               f" -> {'✅' if i1 else '❌'}" + (f" | elenen alırdımlar: {', '.join(elenen)}" if elenen else ""))
    # T1 / T2
    bars, sig, R1, R0 = 0, [], [], []
    for s in evren:
        df = frames.get(s)
        if df is None:
            continue
        bars += len(df)
        v1 = sinyaller(df)
        sig += [(s, df, e) for e in v1]
        R1 += [sim(df, e["t"]) for e in v1]
        R0 += [sim(df, e["t"]) for e in sinyaller_v0(df)]
    dens = len(sig) / bars * 1000 if bars else 0
    t1, m1 = ozet(R1)
    t0, m0 = ozet(R0)
    out.append(f"• T1 yoğunluk: {dens:.1f} / 1000 mum (en az 3) -> {'✅' if dens >= 3 else '❌'}")
    out.append(f"• T2 aynı çıkışla: v2 {t1} | v0 {t0}")
    secim = []
    if i1:
        aday = [x for x in sig if x[2]["date"] >= pd.Timestamp("2023-01-01")
                and kayit.key(x[0], f"{x[2]['date']:%Y-%m-%d}") not in gosterilen]
        rnd.shuffle(aday)
        say = {}
        for s, df, e in aday:
            if say.get(s, 0) >= 2:
                continue
            say[s] = say.get(s, 0) + 1
            secim.append((s, df.iloc[:e["t"] + 1], e))
            if len(secim) == 40:
                break
        secim.sort(key=lambda x: x[2]["date"])
        out.append(f"• İ2 kör test: {len(secim)} yeni grafik geliyor (grafik sinyal gününde biter). "
                   f"Kabul: işaretlenenlerin >= %70'i ✅ Alırdım.")
    else:
        out.append("• İ1 geçmediği için kör test gönderilmedi.")
    txt = "\n".join(out)
    print(txt)
    if "--telegram" not in sys.argv:
        return
    telegram_send(txt)
    if not secim:
        return
    bug = f"{pd.Timestamp.now(tz='Europe/Istanbul'):%Y-%m-%d}"
    for s, df, e in secim:
        r = {c: "" for c in kayit.COLS}
        r.update(bildirim_tarihi=bug, hisse=s, etiket_tarihi=f"{e['date']:%Y-%m-%d}", mod=MOD,
                 kapanis=f"{e['close']:.4g}", direnc=f"{e['line']:.4g}", giris_tarihi=f"{e['date']:%Y-%m-%d}")
        rows.append(r)
    kayit.save(rows)   # grafiklerden ÖNCE kaydet: butonlar her zaman kaydı bulsun
    esle = {}
    for i in range(0, len(secim), 30):
        esle.update(gonder_butonlu(secim[i:i + 30]))
    ep = kayit.F.parent / "tg_mesaj.json"
    try:
        es = json.loads(ep.read_text())
    except Exception:  # noqa: BLE001
        es = {}
    es.update(esle)
    ep.write_text(json.dumps(dict(list(es.items())[-500:]), indent=0))
    print(f"{len(esle)} grafik gönderildi")


if __name__ == "__main__":
    main()

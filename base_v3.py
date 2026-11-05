"""Base kırılımı v3 (05.11.2026) — bu örneklemde SON deneme. v2 almazdım'ların 13/15'ini eledi ama alırdım'ların
14/24'ünü de: kural temasları en yüksek fitile göre arıyordu, senin çizgin ise genelde 0.2-0.6 ADR aşağıda, en çok
değilen seviyede. v3 direnci böyle tanımlar.

KURAL:
  Direnç L*: u-20 .. u-3 arasındaki her tepe bir aday seviye; her aday için bu aralıkta fitili seviyeye 0.3 ADR yakın
       tepeler sayılır (yan yana ya da arasında 1 mum olanlar tek temas). En çok temas alan seviye L (eşitse yüksek olan).
       En az 2 ayrı temas gerekir. Kırılımdan önceki son 2 mum temas sayılmaz (v2'den).
  Üstte tepe yok*: u-20 .. u-1 arasında hiçbir fitil L'nin 0.5 ADR'den fazla üstünde değil.
  Base yüksekliği: L / (önceki 10 mumun en düşüğü) <= 3.3 ADR.
  Kırılım: kapanış[u] > L ve kapanış[u-1] <= L; son 10 mumda başka sinyal yok. Stop = önceki 10 mumun en düşüğü.

ÖNCEDEN YAZILMIŞ TESTLER (v1/v2 ile aynı):
  İ1 (örnek içi, v0'ın işaretli grafikleri; v3 çizgisi daha alçak olabileceği için tarih ±2 mum içinde eşleşir):
     almazdım'ların >= 10/15'i elenir VE alırdım'ların <= 6/24'ü elenir
  T1 yoğunluk >= 3 / 1000 mum; T2 aynı çıkışla R (bilgi)
  İ2 kör test: İ1 geçerse 40 yeni grafik (daha önce gösterilmemiş, tohum 59). KABUL: >= %70 alırdım.
  İ1 geçmezse bu 39 grafikle kural denemesi biter; canlı veri (60-80 yeni işaretli grafik) beklenir.
Çalıştırma: python base_v3.py --telegram
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

MOD = "BaseV3"
W, WT, HMAX, TOL_UST, TOL_TEM, ARA, BEKLE = 10, 20, 3.3, 0.5, 0.3, 2, 10


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
        if c[u] <= c[u - 1]:
            continue
        hh = h[u - WT:u - 2]                       # u-20 .. u-3
        en, L = 0, np.nan
        for cand in hh:
            n = len(temas_kumeleri(np.where(np.abs(hh - cand) <= cand * TOL_TEM * A / 100)[0]))
            if n > en or (n == en and cand > L):
                en, L = n, cand
        if en < 2 or not (c[u] > L >= c[u - 1]):
            continue
        if h[u - WT:u].max() > L * (1 + TOL_UST * A / 100):
            continue
        bot = l[u - W:u].min()
        if (L / bot - 1) * 100 / A > HMAX:
            continue
        son = u
        out.append(dict(type="giris", t=u, date=df.index[u], mode=MOD, line=float(L), close=float(c[u]),
                        stop=float(bot), sp=0, temas=en))
    return out


def main():
    rows = kayit.load()
    eski = [r for r in rows if r.get("mod") == "BaseV0" and (r.get("isaret") or "") in ("a", "g", "h")]
    gosterilen = {kayit.key(r["hisse"], r["etiket_tarihi"]) for r in rows if r.get("mod") in ("BaseV0", "BaseV1", "BaseV2", "BaseV3", "Base")}
    rnd = random.Random(59)
    tick = get_tickers()
    evren = sorted(random.Random(56).sample(tick, min(150, len(tick))))
    syms = sorted(set(evren) | {r["hisse"] for r in eski})
    frames = fetch_tv_all(syms, n_bars=1000, budget=16 * 60)
    out = ["🧱 Base v3 testi (direnç = en çok değilen seviye)"]
    # İ1 örnek içi
    ka = kh = na_ = nh = 0
    elenen = []
    for r in eski:
        df = frames.get(r["hisse"])
        if df is None:
            continue
        t0 = int(df.index.searchsorted(pd.Timestamp(r["etiket_tarihi"])))
        var = any(abs(e["t"] - t0) <= 2 for e in sinyaller(df))
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
    out.append(f"• T2 aynı çıkışla: v3 {t1} | v0 {t0}")
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

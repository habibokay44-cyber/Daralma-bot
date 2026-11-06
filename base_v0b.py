"""Base kırılımı v0b (06.11.2026). Kaçan ölçümü: senin 11 base örneğinden 7'sini v0'ın "son 20 mumda daha yüksek tepe"
şartı eliyordu (base sert düşüşün arkasından gelince 20 mumluk pencereye düşüşün yüksek mumları giriyor), BIOEN'i de
20 mumluk temas penceresi (eski temaslar dışarıda kalıyor).

KURAL (v0'dan tek fark: sabit 20 mum yerine BASE'İN KENDİ UZUNLUĞU):
  üst = kırılımdan önceki 10 mumun en yüksek fitili, alt = en düşüğü; yükseklik <= 3.3 ADR   (v0 ile aynı)
  base penceresi* = kırılımdan geriye, fitili üstün 0.3 ADR'den fazla üstüne çıkmayan mumlar (kesintisiz, en çok 60 mum)
  temas* = bu pencerede fitili üste 0.3 ADR yakın mum, en az 2                                  (v0: son 20 mum)
  kırılım: kapanış[u] > üst >= kapanış[u-1]; son 10 mumda başka sinyal yok                     (v0 ile aynı)
  v0'ın her sinyali v0b'de de vardır (v0b sadece ekler).

ÖNCEDEN YAZILMIŞ TESTLER (06.11.2026):
  K1 kaçan kontrolü: state/kacan.csv'deki 'base' notlu örneklerden (ölçülebilen) en az 6'sını yakalamalı
     (kaçan gününden sonraki 5 mum içinde sinyal). Örnekler bunlar olduğu için sadece ön kontrol.
  T1 yoğunluk: 1000 mumda en fazla 15 sinyal.
  K2 kör test: v0b'nin v0'a göre FAZLADAN verdiği sinyallerden rastgele 40 grafik (2023 sonrası, hisse başına en fazla 2,
     daha önce gösterilmemiş, tohum 60). KABUL: işaretlenenlerin >= %50'si alırdım. K1 geçmezse gönderilmez.
Çalıştırma: python base_v0b.py --telegram
"""
from __future__ import annotations

import csv
import json
import random
import sys
from pathlib import Path

import numpy as np
import pandas as pd

import kayit
from base_v0 import ozet, sim, sinyaller as sinyaller_v0
from grafik import gonder_butonlu
from scan import fetch_tv_all, get_tickers, telegram_send

MOD = "BaseV0b"
W, HMAX, TOL, NTEM, BEKLE, MAXB = 10, 3.3, 0.3, 2, 10, 60
KACAN = Path(__file__).resolve().parent / "state" / "kacan.csv"


def sinyaller(df: pd.DataFrame) -> list[dict]:
    h, l, c = (df[k].to_numpy(float) for k in ("High", "Low", "Close"))
    adr = (pd.Series(h / l).rolling(20).mean().to_numpy() - 1) * 100
    out, son = [], -999
    for u in range(22, len(c)):
        A = adr[u - 1]
        if np.isnan(A) or A <= 0 or u - son <= BEKLE:
            continue
        top, bot = h[u - W:u].max(), l[u - W:u].min()
        if not (c[u] > top >= c[u - 1]):
            continue
        if (top / bot - 1) * 100 / A > HMAX:
            continue
        ust = top * (1 + TOL * A / 100)
        b = u - 1
        while b - 1 >= max(0, u - MAXB) and h[b - 1] <= ust:
            b -= 1
        if int(np.sum(h[b:u] >= top * (1 - TOL * A / 100))) < NTEM:
            continue
        son = u
        out.append(dict(type="giris", t=u, date=df.index[u], mode=MOD, line=float(top), close=float(c[u]),
                        stop=float(bot), sp=0, base_uzunluk=u - b))
    return out


def main():
    rows = kayit.load()
    gosterilen = {kayit.key(r["hisse"], r["etiket_tarihi"]) for r in rows if str(r.get("mod", "")).startswith("Base")}
    kac = {}
    if KACAN.exists():
        for x in csv.DictReader(KACAN.open(encoding="utf-8")):
            n = (x.get("not") or "").lower()
            if "base" in n or "tepe" in n:
                kac[(x["hisse"], x["tarih"])] = "tepe" if "tepe" in n else "base"
    tick = get_tickers()
    evren = sorted(random.Random(56).sample(tick, min(250, len(tick))))
    frames = fetch_tv_all(sorted(set(evren) | {h for h, _ in kac}), n_bars=1000, budget=20 * 60, min_bars=30)
    out = ["🧱 Base v0b testi (temas ve 'daha yüksek tepe' penceresi = base'in kendi uzunluğu)"]
    yak, olc, satir = 0, 0, []
    for (s, d), g in sorted(kac.items()):
        df = frames.get(s)
        if df is None:
            satir.append(f"{s} veri yok")
            continue
        t0 = int(df.index.searchsorted(pd.Timestamp(d), side="right")) - 1
        v0 = any(0 < e["t"] - t0 <= 5 for e in sinyaller_v0(df))
        vb = any(0 < e["t"] - t0 <= 5 for e in sinyaller(df))
        if g == "base":
            olc += 1
            yak += vb
        satir.append(f"{s}{'(tepe)' if g == 'tepe' else ''} v0{'✓' if v0 else '✗'} v0b{'✓' if vb else '✗'}")
    k1 = yak >= 6
    out.append(f"• K1 kaçan: {yak}/{olc} base örneği yakalandı (en az 6) -> {'✅' if k1 else '❌'}\n   " + ", ".join(satir))
    bars, ekstra, Rb, R0 = 0, [], [], []
    for s in evren:
        df = frames.get(s)
        if df is None:
            continue
        bars += len(df)
        v0t = [e["t"] for e in sinyaller_v0(df)]
        vb = sinyaller(df)
        Rb += [sim(df, e["t"]) for e in vb]
        R0 += [sim(df, t) for t in v0t]
        ekstra += [(s, df, e) for e in vb if not any(abs(e["t"] - t) <= 1 for t in v0t)]
    nb = len([x for x in Rb if x is not None])
    dens = len(Rb) / bars * 1000 if bars else 0
    tb, _ = ozet(Rb)
    t0_, _ = ozet(R0)
    out.append(f"• T1 yoğunluk: {dens:.1f} / 1000 mum (en fazla 15) -> {'✅' if dens <= 15 else '❌'}")
    out.append(f"• aynı çıkışla (bilgi): v0b {tb} | v0 {t0_} | v0b'nin fazladan sinyali {len(ekstra)}")
    secim = []
    if k1 and dens <= 15:
        aday = [x for x in ekstra if x[2]["date"] >= pd.Timestamp("2023-01-01")
                and kayit.key(x[0], f"{x[2]['date']:%Y-%m-%d}") not in gosterilen]
        random.Random(60).shuffle(aday)
        say = {}
        for s, df, e in aday:
            if say.get(s, 0) >= 2:
                continue
            say[s] = say.get(s, 0) + 1
            secim.append((s, df.iloc[:e["t"] + 1], e))
            if len(secim) == 40:
                break
        secim.sort(key=lambda x: x[2]["date"])
        out.append(f"• K2 kör test: {len(secim)} grafik geliyor (v0'ın vermediği, v0b'nin fazladan verdiği sinyaller; "
                   f"grafik sinyal gününde biter). Kabul: >= %50 ✅ Alırdım.")
    else:
        out.append("• Ön şartlar geçmediği için kör test gönderilmedi.")
    txt = "\n".join(out)
    print(txt)
    if "--telegram" not in sys.argv:
        return
    telegram_send(txt[:3900])
    if not secim:
        return
    bug = f"{pd.Timestamp.now(tz='Europe/Istanbul'):%Y-%m-%d}"
    for s, df, e in secim:
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
        es = json.loads(ep.read_text())
    except Exception:  # noqa: BLE001
        es = {}
    es.update(esle)
    ep.write_text(json.dumps(dict(list(es.items())[-500:]), indent=0))
    print(f"{len(esle)} grafik gönderildi")


if __name__ == "__main__":
    main()

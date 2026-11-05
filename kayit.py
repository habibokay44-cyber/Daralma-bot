"""İleri test kaydı (state/etiket_kayit.csv) için ortak yardımcılar: sütunlar, okuma/yazma, v56 gölge bayrakları.

Sütunlar:
  bildirim_tarihi, hisse, etiket_tarihi, mod, kapanis, direnc, iptal,
  isaret   : senin cevabın. Butonlarla: a = alırdım, g = başka günde alırdım, h = almazdım.
             (Eski elle işaretler d / y / b da okunur.)
  cizgi    : y = çizgi yanlış (butonla), d = doğru
  not      : serbest not (Telegram'da grafiğe cevap yazınca buraya eklenir)
  e1       : 1 = EMA10 ya da EMA21 5 mumda %0.5'ten fazla düşmüş (etiket günü)
  y1       : 1 = son 40 mumun en düşük dibinden dirence yükseliş %15'ten az
  v56      : 'elenir' = e1 ve y1 birlikte (gölge; bildirimde gösterilmez)
  giris_tarihi : göstergenin bu etiket için verdiği Giriş günü (tarama yazar)
  alis_tarihi  : senin alış günün (a ise etiket günü; g ise Telegram'da cevap olarak yazdığın tarih)
  e50      : 1 = kapanış günlük EMA50 altında            (ANA KURAL, 05.11.2026'da önceden seçildi)
  g1       : 1 = kapanış son 40 mumun dip-tepe aralığının alt yarısında
  w1       : 1 = haftalık kapanış haftalık EMA10 altında
  direnc_sen, temas_sen : grafiğe "direnç 12,40 3" diye cevap yazınca: senin gördüğün direnç fiyatı ve temas sayısı
  b_v2, b_v3 : canlı Base sinyalinde v2 / v3 kuralı da (±2 mum) sinyal veriyor mu (1/0) — gölge, 05.11.2026
  stage    : senin büyük resim işaretin (butonla): 1 = Stage 1, 2 = Stage 2, 3 = tepe, 4 = düşüş
"""
from __future__ import annotations

import csv
from pathlib import Path

import numpy as np
import pandas as pd

F = Path(__file__).resolve().parent / "state" / "etiket_kayit.csv"
COLS = ["bildirim_tarihi", "hisse", "etiket_tarihi", "mod", "kapanis", "direnc", "iptal", "isaret", "cizgi", "not",
        "e1", "y1", "v56", "giris_tarihi", "alis_tarihi", "e50", "g1", "w1", "stage",
        "direnc_sen", "temas_sen", "b_v2", "b_v3"]


def key(sym: str, date: str) -> str:
    return f"{sym}|{date}"


def load() -> list[dict]:
    if not F.exists():
        return []
    with F.open(encoding="utf-8") as fh:
        rd = csv.reader(fh)
        head = next(rd, None) or []
        rows = []
        for r in rd:
            if not r:
                continue
            d = {c: "" for c in COLS}
            for i, c in enumerate(head[:len(r)]):
                d[c] = r[i]
            if len(r) > len(head) and "not" in head:  # nota yazılmış virgüller
                d["not"] = ",".join([d["not"]] + r[len(head):])
            rows.append(d)
    return rows


def save(rows: list[dict]) -> None:
    F.parent.mkdir(parents=True, exist_ok=True)
    with F.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(COLS)
        for d in rows:
            w.writerow([str(d.get(c, "")).replace("\n", " ") for c in COLS])


def bayraklar(df: pd.DataFrame, e: dict) -> dict:
    """v56 gölge bayrakları (05.11.2026'da sabitlendi)."""
    t = int(e["t"])
    c = df["Close"].astype(float)
    e10 = c.ewm(span=10, adjust=False).mean().to_numpy()
    e21 = c.ewm(span=21, adjust=False).mean().to_numpy()
    e1 = False
    if t >= 5:
        e1 = (e10[t] / e10[t - 5] - 1) * 100 <= -0.5 or (e21[t] / e21[t - 5] - 1) * 100 <= -0.5
    lo = float(np.min(df["Low"].to_numpy(float)[max(0, t - 40):t + 1]))
    y1 = (float(e["line"]) / lo - 1) * 100 < 15 if lo > 0 else False
    h = df["High"].to_numpy(float)
    l = df["Low"].to_numpy(float)
    cc = c.to_numpy()
    H40, L40 = h[max(0, t - 39):t + 1].max(), l[max(0, t - 39):t + 1].min()
    g1 = (cc[t] - L40) / (H40 - L40) < 0.5 if H40 > L40 else False
    e50 = cc[t] < c.ewm(span=50, adjust=False).mean().iloc[t]
    wk = c.iloc[:t + 1].resample("W-FRI").last().dropna()
    w1 = len(wk) >= 10 and wk.iloc[-1] < wk.ewm(span=10, adjust=False).mean().iloc[-1]
    b = lambda x: "1" if x else "0"  # noqa: E731
    return dict(e1=b(e1), y1=b(y1), v56="elenir" if (e1 and y1) else "geçer", e50=b(e50), g1=b(g1), w1=b(w1))

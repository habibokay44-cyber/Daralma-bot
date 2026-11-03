"""'Küçük mum' seçeneklerini gözle karşılaştırmak için grafik üretir ve Telegram'a resim olarak gönderir.
Hiçbir ayarı değiştirmez.

Her grafikte:
  - senin kutun gri gölgeli, üstünde her mumun oranı (kutudan önceki 10 mumun ortalama boyuna göre)
  - mavi kesikli çizgiler: kutu tabanından itibaren 2 ADR'lik bant (bant kuralı)
  - sağda dikey ölçek çubukları: önceki 10 mumun ortalama boyu, bunun 0.75 ve 1.1 katı,
    ve önceki 10 mumun en büyük 3'ünün ortalamasının 0.75 katı
  - altta üç seçeneğin bu kutu için sonucu
Seçenekler:
  S1: her mum <= 0.75 x (önceki 10 mumun EN BÜYÜK 3'ünün ortalaması)
  S2: her mum <= 1.1 x (önceki 10 mumun ortalaması)
  S3: mum boyuna bakma; gövdeler 2 ADR bantta ve hiçbir mum 1.5 x ortalamayı geçmiyor
Çalıştırma: python kutu_gorsel.py --telegram
"""
from __future__ import annotations

import io
import os
import sys
import time

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import requests  # noqa: E402

from dogrula import read_marks  # noqa: E402
from kutu_test import USER_BOX  # noqa: E402
from kutu_yeni import _ema  # noqa: E402
from scan import fetch_tv_all, telegram_send  # noqa: E402

# Gösterilecek kutular: notlarındaki aralıklar + örneklemde kaçan doğrulardan birkaçı (etiket günü biten 3 mum)
SHOW = ["KRDMD", "MEDTR", "KTLEV", "BSOKE", "KRDMA", "ARDYZ", "TRCAS", "BINBN", "KUTPO", "DZGYO"]


def options(rng, s, t, band):
    ref = rng[s - 10:s].mean()
    top3 = np.sort(rng[s - 10:s])[-3:].mean()
    r = rng[s:t + 1]
    return dict(
        ref=ref, top3=top3,
        S1=bool((r <= 0.75 * top3).all()),
        S2=bool((r <= 1.1 * ref).all()),
        S3=bool(band <= 2.0 and (r <= 1.5 * ref).all()),
    )


def chart(sym, df, a, z):
    idx = df.index
    s = int(idx.searchsorted(pd.Timestamp(a)))
    t = int(idx.searchsorted(pd.Timestamp(z), side="right")) - 1
    if t - s + 1 < 3:
        s = t - 2
    if s < 30:
        return None, None
    o, h, l, c = (df[k].to_numpy(float) for k in ("Open", "High", "Low", "Close"))
    adr = (pd.Series(h / l).rolling(20).mean().to_numpy() - 1) * 100
    rng = (h - l) / c * 100
    bt, bb = np.maximum(o, c), np.minimum(o, c)
    band = (bt[s:t + 1].max() / bb[s:t + 1].min() - 1) * 100 / adr[t]
    op = options(rng, s, t, band)
    e10, e21 = _ema(c, 10), _ema(c, 21)
    a0, a1 = max(0, s - 30), min(len(c), t + 9)
    x = np.arange(a0, a1)
    fig, ax = plt.subplots(figsize=(9, 5.2), dpi=110)
    for i in x:
        col = "#2e9e5b" if c[i] >= o[i] else "#d64545"
        ax.vlines(i, l[i], h[i], color=col, linewidth=1)
        ax.add_patch(plt.Rectangle((i - 0.35, bb[i]), 0.7, max(bt[i] - bb[i], 1e-9), color=col))
    ax.plot(x, e10[a0:a1], color="#e8a33d", linewidth=1.2, label="EMA10")
    ax.plot(x, e21[a0:a1], color="#3b6fd6", linewidth=1.2, label="EMA21")
    ax.axvspan(s - 0.5, t + 0.5, color="#888", alpha=0.18)
    base = bb[s:t + 1].min()
    top = base * (1 + 2.0 * adr[t] / 100)
    ax.hlines([base, top], s - 3, t + 3, colors="#3b6fd6", linestyles="--", linewidth=1)
    ax.text(t + 3.2, top, "2 ADR bant", color="#3b6fd6", fontsize=8, va="center")
    for i in range(s, t + 1):
        ax.text(i, h[i] * 1.004, f"{rng[i] / op['ref']:.2f}x", ha="center", va="bottom", fontsize=8)
    # ölçek çubukları (yüzde boy -> fiyat boyu, kutu tabanı fiyatında)
    xs = a1 + 0.5
    px = c[t]
    bars = [("ort", op["ref"], "#555"), ("0.75x ort", 0.75 * op["ref"], "#999"), ("1.1x ort", 1.1 * op["ref"], "#000"),
            ("S1: 0.75x\nbüyük 3", 0.75 * op["top3"], "#8a2be2")]
    for k, (nm, pct, col) in enumerate(bars):
        xx = xs + k * 1.6
        ax.vlines(xx, base, base + px * pct / 100, color=col, linewidth=4)
        ax.text(xx, base - px * 0.004, nm, rotation=90, ha="center", va="top", fontsize=7, color=col)
    ax.set_xlim(a0 - 1, xs + 4 * 1.6 + 1)
    ticks = list(range(a0, a1, 5))
    ax.set_xticks(ticks)
    ax.set_xticklabels([f"{idx[i]:%d.%m}" for i in ticks], fontsize=8)
    ax.legend(loc="upper left", fontsize=8)
    yes = lambda b: "✓ kutu" if b else "✗ kutu değil"  # noqa: E731
    ax.set_title(f"{sym}  senin kutun {idx[s]:%d.%m}–{idx[t]:%d.%m}  |  bant {band:.2f} ADR  |  "
                 f"S1 {yes(op['S1'])}   S2 {yes(op['S2'])}   S3 {yes(op['S3'])}", fontsize=9)
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png")
    plt.close(fig)
    return buf.getvalue(), op


def send_photo(png: bytes, caption: str) -> None:
    token, chat = os.environ.get("TELEGRAM_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    r = requests.post(f"https://api.telegram.org/bot{token}/sendPhoto", data={"chat_id": chat, "caption": caption[:1000]},
                      files={"photo": ("k.png", png, "image/png")}, timeout=60)
    if not r.ok:
        print(f"Telegram resim hatası: {r.status_code} {r.text}", file=sys.stderr)


def main():
    marks = {m["sym"]: m for m in read_marks()}
    wins = {}
    for s in SHOW:
        if s in USER_BOX:
            wins[s] = USER_BOX[s]
        elif s in marks:
            d = marks[s]["date"]
            wins[s] = (f"{d - pd.Timedelta(days=4):%Y-%m-%d}", f"{d:%Y-%m-%d}")
    frames = fetch_tv_all(list(wins), n_bars=300, budget=5 * 60)
    tg = "--telegram" in sys.argv
    out = ["🖼 'Küçük mum' seçenekleri: her grafikte senin kutun gri gölgeli.",
           "S1: her mum, önceki 10 mumun en büyük 3'ünün ortalamasının 0.75 katından küçük",
           "S2: her mum, önceki 10 mumun ortalamasının 1.1 katından küçük",
           "S3: mum boyuna bakma; gövdeler 2 ADR bantta, hiçbir mum ortalamanın 1.5 katını geçmiyor",
           "Sağdaki çubuklar bu boyları gösterir. Mumların üstündeki sayı: ortalamaya oranı."]
    if tg:
        telegram_send("\n".join(out))
    tally = {"S1": 0, "S2": 0, "S3": 0}
    n = 0
    for s, (a, z) in wins.items():
        df = frames.get(s)
        if df is None:
            continue
        png, op = chart(s, df, a, z)
        if png is None:
            continue
        n += 1
        for k in tally:
            tally[k] += op[k]
        cap = f"{s}: S1 {'✓' if op['S1'] else '✗'}  S2 {'✓' if op['S2'] else '✗'}  S3 {'✓' if op['S3'] else '✗'}"
        print(cap)
        if tg:
            send_photo(png, cap)
            time.sleep(1)
        else:
            open(f"kutu_{s}.png", "wb").write(png)
    summ = f"Bu {n} kutudan kutu sayılan: S1 {tally['S1']}, S2 {tally['S2']}, S3 {tally['S3']}"
    print(summ)
    if tg:
        telegram_send(summ + "\nHangi seçeneğin senin gözünle uyuştuğunu yaz; istersen 'hiçbiri, şu şekilde' de.")


if __name__ == "__main__":
    main()

"""Etiket grafikleri: akşam taramasındaki her yeni daralma etiketinin küçük grafiğini çizer ve Telegram'a gönderir
(gonder_butonlu: her etiket ayrı fotoğraf + Alırdım / Başka gün / Almazdım / Çizgi yanlış butonları; gonder_album: albüm). Göstergeyi değiştirmez; sadece görsel özet. Hata olursa tarama etkilenmez (scan.py yakalar).

Her grafikte: son ~60 mum, EMA10 (turkuaz), EMA21 (pembe), EMA50 (lacivert), direnç çizgisi (turuncu),
stop (sıkışma dibi, kırmızı kesikli), etiket mumu (turuncu üçgen).
"""
from __future__ import annotations

import io
import json
import os
import time

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import requests  # noqa: E402

GERI = 60      # etiketten önce kaç mum
MAX_RESIM = 30  # bir taramada en fazla kaç grafik


def _ema(x, n):
    return pd.Series(x).ewm(span=n, adjust=False).mean().to_numpy()


def cizim(sym: str, df: pd.DataFrame, e: dict) -> bytes:
    o, h, l, c = (df[k].to_numpy(float) for k in ("Open", "High", "Low", "Close"))
    n, t = len(c), int(e["t"])
    a0, a1 = max(0, t - GERI), n
    x = np.arange(a0, a1)
    fig, ax = plt.subplots(figsize=(8, 4.6), dpi=110)
    w = 0.6
    for i in x:
        up = c[i] >= o[i]
        col = "#26a269" if up else "#c01c28"
        ax.vlines(i, l[i], h[i], color=col, linewidth=0.9)
        ax.add_patch(plt.Rectangle((i - w / 2, min(o[i], c[i])), w, max(abs(c[i] - o[i]), (h[i] - l[i]) * 0.02),
                                   facecolor=col if not up else "white", edgecolor=col, linewidth=0.9))
    for n_, col in ((10, "#1fb5c4"), (21, "#d65ad1"), (50, "#24305e")):
        ax.plot(x, _ema(c, n_)[a0:a1], color=col, linewidth=1.1, label=f"EMA{n_}")
    ln = float(e["line"])
    if e["mode"] == "Düşen" and int(e.get("sp", 0)) >= 2:
        xa = t - int(e["sp"]) + 1
        pa = float(h[xa])
        sl = (ln - pa) / (t - xa) if t != xa else 0.0
        xs = np.array([max(xa, a0), a1 - 1])
        ax.plot(xs, ln + sl * (xs - t), color="#f08c00", linewidth=1.6)
    else:
        ax.hlines(ln, max(a0, t - 25), a1 - 1, colors="#f08c00", linewidth=1.6)
    if e.get("stop") is not None:
        ax.hlines(float(e["stop"]), t - 6, a1 - 1, colors="#c01c28", linestyles="--", linewidth=1)
    ax.plot([t], [h[t] * 1.012], marker="v", color="#f08c00", markersize=9)
    lo, hi = l[a0:a1].min(), h[a0:a1].max()
    pad = (hi - lo) * 0.06
    ax.set_ylim(lo - pad, hi + pad * 1.5)
    ax.set_xlim(a0 - 1, a1 + 1)
    ticks = list(range(a0, a1, 10))
    ax.set_xticks(ticks)
    ax.set_xticklabels([f"{df.index[i]:%d.%m}" for i in ticks], fontsize=8)
    ax.tick_params(axis="y", labelsize=8)
    ax.grid(alpha=0.15)
    ax.legend(loc="upper left", fontsize=7, frameon=False)
    dist = (ln / float(e["close"]) - 1) * 100
    ax.set_title(f"{sym} · {e['date']:%d.%m.%Y} · {e['mode']} · kapanış {e['close']:.2f} · direnç {ln:.2f} (+%{dist:.1f})",
                 fontsize=10)
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png")
    plt.close(fig)
    return buf.getvalue()


def _post(method: str, data: dict, files: dict) -> dict:
    token, chat = os.environ.get("TELEGRAM_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat:
        raise RuntimeError("TELEGRAM_TOKEN / TELEGRAM_CHAT_ID yok")
    r = requests.post(f"https://api.telegram.org/bot{token}/{method}", data={"chat_id": chat, **data}, files=files, timeout=90)
    if not r.ok:
        raise RuntimeError(f"Telegram {method} hatası: {r.status_code} {r.text[:200]}")
    try:
        return r.json()
    except Exception:  # noqa: BLE001
        return {}


BUTONLAR = [("✅ Alırdım", "a"), ("⏳ Başka gün", "g"), ("❌ Almazdım", "h")]


def klavye(sym: str, date) -> str:
    k = f"{sym}|{date:%Y%m%d}"
    return json.dumps({"inline_keyboard": [[{"text": t, "callback_data": f"i|{k}|{v}"} for t, v in BUTONLAR],
                                           [{"text": "📐 Çizgi yanlış", "callback_data": f"i|{k}|c"}]]}, ensure_ascii=False)


def gonder_butonlu(items: list[tuple[str, pd.DataFrame, dict]]) -> dict[str, str]:
    """Her etiket ayrı fotoğraf + cevap butonları. Döner: {mesaj_id: 'HISSE|YYYY-MM-DD'} (cevapları eşlemek için)."""
    esle: dict[str, str] = {}
    for sym, df, e in items[:MAX_RESIM]:
        try:
            png = cizim(sym, df, e)
        except Exception as ex:  # noqa: BLE001
            print(f"[uyarı] {sym} grafiği çizilemedi: {ex}")
            continue
        cap = (f"{sym} · {e['date']:%d.%m.%Y} · {e['mode']}\n"
               f"İşlem alır mıydın? 'Başka gün' dersen bu mesaja alış tarihini cevap olarak yaz (örn. 12.11).")
        res = _post("sendPhoto", {"caption": cap, "reply_markup": klavye(sym, e["date"])},
                    {"photo": ("0.png", png, "image/png")})
        mid = (res.get("result") or {}).get("message_id")
        if mid is not None:
            esle[str(mid)] = f"{sym}|{e['date']:%Y-%m-%d}"
        time.sleep(1)
    return esle


def gonder_album(items: list[tuple[str, pd.DataFrame, dict]]) -> int:
    """items: (hisse, df, etiket olayı). 10'arlı albümler halinde gönderir. Gönderilen resim sayısını döner."""
    imgs = []
    for sym, df, e in items[:MAX_RESIM]:
        try:
            imgs.append((cizim(sym, df, e), f"{sym} {e['date']:%d.%m} {e['mode']}"))
        except Exception as ex:  # noqa: BLE001
            print(f"[uyarı] {sym} grafiği çizilemedi: {ex}")
    for k in range(0, len(imgs), 10):
        part = imgs[k:k + 10]
        if len(part) == 1:
            _post("sendPhoto", {"caption": part[0][1]}, {"photo": ("0.png", part[0][0], "image/png")})
        else:
            media = [{"type": "photo", "media": f"attach://p{i}", "caption": cap} for i, (_, cap) in enumerate(part)]
            files = {f"p{i}": (f"{i}.png", png, "image/png") for i, (png, _) in enumerate(part)}
            _post("sendMediaGroup", {"media": json.dumps(media, ensure_ascii=False)}, files)
        time.sleep(1)
    return len(imgs)

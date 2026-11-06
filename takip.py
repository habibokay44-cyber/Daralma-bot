"""Akşam takibi: açık pozisyonların iz süren stop seviyesi + aday kırılım uyarısı + piyasa genişliği.

Çıkış kuralı (testte seçilen 'Iz10', 06.11.2026'dan itibaren KAPANIŞLA: gün kapanışı stopun altındaysa çık): stop = giriş mumunun dibi. Fiyat girişin +1R (R = giriş - stop) üstünü görünce
stop girişe çekilir; sonra son 10 mumun dibini izler, sadece yukarı. Hedef ve süre sınırı yok.
Bu bir öneridir, emir vermez; stopu aracı kurumunda sen güncellersin.

Pozisyonlar: repo ana klasöründeki pozisyonlar.txt, her satır:  HISSE  GIRIS_TARIHI(YYYY-AA-GG)  GIRIS_FIYATI
Örnek:  KRGYO 2026-10-29 12.34      (# ile başlayan satırlar yorumdur). Kapanan pozisyonu dosyadan sil.

Çalıştırma: python takip.py            (Telegram'a gönderir, mesaj yoksa göndermez)
            python takip.py --dry      (ekrana yazar)
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from gecmis_tara import candidates
from scan import fetch_tv_all, get_tickers, link, telegram_send

TRAIL = 10
ARM = 1.0
FILE = Path(__file__).parent / "pozisyonlar.txt"
BR_LOW, BR_HIGH = 0.49, 0.77     # testteki genişlik dilim sınırları


def read_positions() -> list[tuple[str, str, float]]:
    out = []
    try:
        lines = FILE.read_text(encoding="utf-8").splitlines()
    except Exception:  # noqa: BLE001
        return out
    for ln in lines:
        ln = ln.split("#")[0].strip()
        if not ln:
            continue
        p = ln.replace(",", ".").split()
        try:
            out.append((p[0].upper(), p[1], float(p[2])))
        except Exception:  # noqa: BLE001
            print(f"[uyarı] satır okunamadı: {ln}", file=sys.stderr)
    return out


def track(df: pd.DataFrame, date: str, price: float) -> dict:
    o, h, l, c = (df[k].to_numpy(float) for k in ("Open", "High", "Low", "Close"))
    n = len(c)
    pos = df.index.searchsorted(pd.Timestamp(date))
    if pos >= n:
        return dict(err="giriş tarihi veride yok")
    t = int(pos)
    if abs(df.index[t] - pd.Timestamp(date)) > pd.Timedelta(days=4):
        return dict(err="giriş tarihine yakın mum yok")
    sl = l[t]
    R = price - sl
    if R <= 0:
        return dict(err="giriş fiyatı giriş mumunun dibinin altında/eşit, kontrol et")
    s, armed = sl, False
    s_prev = s
    for k in range(t + 1, n):
        s_prev = s
        if c[k] < s:   # 06.11.2026: kapanış stopun altındaysa çıkış (gün içi değme çıkış değil)
            x = c[k]
            return dict(closed=True, k=k, date=df.index[k], exit=float(x), R=(x - price) / R, ago=n - 1 - k)
        if not armed and h[k] >= price + ARM * R:
            armed = True
            s = max(s, price)
        if armed:
            s = max(s, float(l[max(t + 1, k - TRAIL + 1):k + 1].min()))
    cs = df["Close"].astype(float)
    e10 = float(cs.ewm(span=10, adjust=False).mean().iloc[-1])
    e21 = float(cs.ewm(span=21, adjust=False).mean().iloc[-1])
    return dict(closed=False, e10=e10, e21=e21, t=t, last=float(c[-1]), ret=(c[-1] / price - 1) * 100, R=(c[-1] - price) / R,
                stop=float(s), prev=float(s_prev), armed=armed, sl0=float(sl), days=n - 1 - t)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    args = ap.parse_args()
    frames = fetch_tv_all(get_tickers(), n_bars=500)
    pos = read_positions()
    lines_pos = []
    for sym, d, px in pos:
        df = frames.get(sym)
        if df is None:
            lines_pos.append(f"• {sym}: veri yok")
            continue
        r = track(df, d, px)
        if "err" in r:
            lines_pos.append(f"• {sym}: {r['err']}")
        elif r["closed"]:
            if r["ago"] <= 3:
                lines_pos.append(f"• {sym}: ⛔ STOP çalıştı {r['date']:%d.%m} ~{r['exit']:.2f} (R {r['R']:+.2f}). Pozisyonu dosyadan sil.")
        else:
            up = r["stop"] > r["prev"] + 1e-9
            st = "iz sürüyor" if r["armed"] else "henüz +1R yok, stop = giriş mumunun dibi"
            mv = f" 🔼 stopu {r['stop']:.2f}'ye YÜKSELT" if up else ""
            ema = ""
            if r["last"] < r["e21"]:
                ema = " ⚠️ EMA21 altında kapandı (EMA kuralında TAM çıkış)"
            elif r["last"] < r["e10"]:
                ema = " ⚠️ EMA10 altında kapandı (EMA kuralında YARI sat)"
            lines_pos.append(f"• {sym}: {r['last']:.2f} ({r['ret']:+.1f}%, R {r['R']:+.2f}, {r['days']} gün) | Iz10 stop {r['stop']:.2f} ({st}){mv}"
                             f" | EMA10 {r['e10']:.2f} EMA21 {r['e21']:.2f}{ema}  {link(sym)}")
    alerts = []
    for sym, df in frames.items():
        try:
            n = len(df)
            c = df["Close"].to_numpy(float)
            for x in candidates(sym, df, skip_labeled=True, span=10):
                i = x["i"]
                if i > n - 2:
                    continue
                thr = x["res"] * (1 + 0.5 * x["adr"] / 100)
                if c[n - 1] > thr and (c[i + 1:n - 1] <= thr).all():
                    alerts.append(f"• {sym}: aday pencerenin direnci ~{x['res']:.2f} kapanışla kırıldı ({c[n - 1]:.2f})  {link(sym)}")
                    break
        except Exception as e:  # noqa: BLE001
            print(f"[uyarı] {sym}: {e}", file=sys.stderr)
    cl = pd.DataFrame({s: df["Close"].astype(float) for s, df in frames.items()}).sort_index()
    ma = cl.rolling(50).mean()
    ok = (cl > ma).where(ma.notna())
    cnt = ok.notna().sum(axis=1)
    ok = ok[cnt >= 0.8 * cnt.max()]
    br = float(ok.iloc[-1].mean())
    zone = "düşük bölge (testte işlem kalitesi daha düşük)" if br < BR_LOW else ("yüksek bölge" if br >= BR_HIGH else "orta bölge")
    last_day = ok.index[-1]
    parts = []
    if lines_pos:
        parts.append("📈 Pozisyonlar (iz stop: giriş mumunun dibi → +1R'de girişe → son 10 mumun dibi)\n" + "\n".join(lines_pos))
    if alerts:
        parts.append("🔔 Aday direnç kırılımı (bot etiketi yok, grafikte bak)\n" + "\n".join(alerts))
    if not parts and os.environ.get("GITHUB_EVENT_NAME") != "workflow_dispatch":
        print(f"Bugün gönderilecek bir şey yok. Genişlik {br:.2f}")
        return
    msg = f"🧭 Akşam takibi {last_day:%d.%m.%Y}\n\n" + "\n\n".join(parts) + f"\n\n🌡️ Piyasa genişliği (SMA50 üstü hisse): {br:.2f} ({int(cnt.loc[ok.index[-1]])} hisse) → {zone}"
    print(msg)
    if not args.dry:
        telegram_send(msg)


if __name__ == "__main__":
    sys.exit(main())

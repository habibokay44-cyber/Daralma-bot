"""Kaçan kurulumların tanısı: state/kacan.csv'deki her kurulum için göstergenin o günlerde etiketi hangi kapıda
engellediğini gösterir. Hiçbir ayarı değiştirmez. Kaçanları Telegram'dan "kaçan HISSE GG.AA" yazarak eklersin.
İstersen komut satırından da: python kacan_tani.py KRGYO 2026-10-30
Çalıştırma: python kacan_tani.py --telegram
"""
from __future__ import annotations

import csv
import re
import sys
import time
from collections import Counter
from pathlib import Path

import pandas as pd

from fd_core import Params, run
from scan import fetch_tv_all, telegram_send

F = Path(__file__).resolve().parent / "state" / "kacan.csv"
GERI, ILERI = 6, 2
ANLAM = {
    "m": "sıkışma aralığı geniş", "r": "mumlar küçülmüyor", "k": "kapanışlar dağınık", "d": "dipler alçalıyor",
    "u": "dirence yaklaşma yok", "s": "eğim uygun değil", "y": "kapanış çizgiye uzak", "D": "dip şartı",
    "c": "mum büyük / kapanış alt kısımda", "j": "sıçrama var", "v": "hacim", "g": "güçlü kırmızı mum",
    "e": "EMA21 eğimi/uzaklığı", "T": "tepeden çok uzak", "R": "ralli şartı", "b": "7 mumluk gövde kutusu geniş",
    "lc": "art arda düşen kapanış", "dn": "düşen çizgide temas az", "rl": "küçülme alt sınırı", "eb": "EMA altında eğim",
    "sp": "düşen çizgi kısa", "bf": "gövde oranı", "H": "yatay ama düşüşte", "Y": "yatay gövde kutusu geniş",
    "L": "çizgi bulunamadı", "O": "onay bekliyor", "B": "kırılım/etiket sonrası bekleme",
}
BILGI = {"bx", "K", "RS"}  # sadece bilgi (kutu modu ölçüsü), engel sayılmaz


def kodlar(why: str):
    out = []
    for tok in why.split():
        m = re.match(r"(lc|dn|rl|eb|sp|bf|bx|RS|b7_|[A-Za-z])", tok)
        if not m:
            continue
        k = m.group(1).rstrip("_")
        k = "b" if k == "b7" else k
        if k not in BILGI:
            out.append(k)
    return out


def main():
    rows = []
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if len(args) >= 2:
        rows.append(dict(hisse=args[0].upper(), tarih=args[1], not_=""))
    elif F.exists():
        rows = [dict(hisse=r["hisse"], tarih=r["tarih"], not_=r.get("not", "")) for r in csv.DictReader(F.open(encoding="utf-8"))]
    if not rows:
        print("Kaçan kurulum yok. Telegram'a 'kaçan HISSE GG.AA' yaz.")
        return
    frames = fetch_tv_all(sorted({r["hisse"] for r in rows}), n_bars=700, budget=8 * 60)
    out = [f"🔍 Kaçan kurulum tanısı ({len(rows)} kurulum). Her gün: o günü engelleyen kapılar."]
    say = Counter()
    for r in rows:
        df = frames.get(r["hisse"])
        if df is None:
            out.append(f"\n{r['hisse']} {r['tarih']}: veri yok")
            continue
        res = run(df, Params())
        d = pd.Timestamp(r["tarih"])
        t = int(df.index.searchsorted(d))
        ev = [e for e in res.events if e["type"] == "setup" and abs((e["date"] - d).days) <= 7]
        out.append(f"\n{r['hisse']} {d:%d.%m.%Y}" + (f" ({r['not_']})" if r["not_"] else "")
                   + (" — yakında etiket VAR: " + ", ".join(f"{e['date']:%d.%m} {e['mode']}" for e in ev) if ev else " — etiket yok"))
        gun = set()
        for i in range(max(0, t - GERI), min(len(df), t + ILERI + 1)):
            why = res.diag.get(i) or ""
            ks = kodlar(why)
            gun |= set(ks)
            out.append(f"  {df.index[i]:%d.%m}: {why[:110] or '-'}")
        say.update(gun)
    out.append("\nKurulum başına engelleyen kapılar (en sık):")
    out += [f"  {k} ({ANLAM.get(k, '?')}): {v}" for k, v in say.most_common(12)]
    txt = "\n".join(out)
    print(txt)
    if "--telegram" in sys.argv:
        for i in range(0, len(txt), 3500):
            telegram_send(txt[i:i + 3500])
            time.sleep(1)


if __name__ == "__main__":
    main()

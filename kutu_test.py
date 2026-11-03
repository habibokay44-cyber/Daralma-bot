"""Yaşayan kutu dedektörünü (kutu_yeni.py) senin notlarına ve örneklerine göre sınar. Hiçbir ayarı değiştirmez.

Bu bir ön kontroldür, kanıt değildir. Asıl sınav: yeni dedektörün kutularından rastgele örneklem, kör işaretleme.
Eşikler senin tarifinden geldi, bu sonuca bakılarak ayarlanmayacak. Sonuç kötüyse tanımı seninle konuşuruz.

ÖNCEDEN YAZILMIŞ GEÇİŞ ŞARTI (kör örnekleme geçmek için, 04.11.2026):
  a) notlarında tarih verdiğin 13 kutudan en az 7'si yakalanır
  b) örneklemde doğru işaretli etiketlerin en az yarısında ±3 gün içinde kutu var
  c) erken-dışı 7 yanlıştan en fazla 3'ünde ±3 gün içinde kutu var
  d) kutu yoğunluğu 1000 mumda 2 ile 15 arası
Çalıştırma: python kutu_test.py --telegram
"""
from __future__ import annotations

import sys
import time
from collections import Counter

import pandas as pd

from calibrate import EXAMPLES
from dogrula import read_marks
from kutu_yeni import KP, detect
from scan import fetch_tv_all, telegram_send

# Notlarında verdiğin kutu aralıkları (başlangıç, bitiş)
USER_BOX = {
    "TEHOL": ("2026-05-07", "2026-05-11"),
    "KRDMA": ("2026-04-24", "2026-04-28"),
    "KRDMD": ("2025-12-05", "2025-12-10"),
    "CEOEM": ("2026-03-23", "2026-03-25"),
    "MAGEN": ("2026-03-17", "2026-03-23"),
    "DURDO": ("2026-03-27", "2026-04-02"),
    "MEDTR": ("2025-12-11", "2025-12-15"),
    "BSOKE": ("2026-04-06", "2026-04-07"),
    "SURGY": ("2026-06-02", "2026-06-04"),
    "DUNYH": ("2026-04-17", "2026-04-21"),
    "KTLEV": ("2026-02-05", "2026-02-09"),
    "ETILR": ("2026-04-15", "2026-04-15"),
    "KOCMT": ("2025-12-01", "2025-12-03"),
}
D = pd.Timedelta


def alive(df, b):
    """Kutunun etiketten bitişe kadar yaşadığı tarih aralığı (kırılım/bozulma günü dahil)."""
    last = b.get("break_t", b.get("stop_t", b["end_t"]))
    return b["label_d"], df.index[min(last, len(df) - 1)]


def hits(df, boxes, a, z):
    return [b for b in boxes if alive(df, b)[0] <= z and alive(df, b)[1] >= a]


def section(frames, marks, P, title):
    B = {s: detect(df, P) for s, df in frames.items()}
    out = [title]

    # a) senin kutu aralıkların
    ok_a, rows_a = 0, []
    for s, (a, z) in USER_BOX.items():
        df = frames.get(s)
        if df is None:
            rows_a.append(f"{s}(veri yok)")
            continue
        h = hits(df, B[s], pd.Timestamp(a), pd.Timestamp(z) + D(days=2))
        ok_a += bool(h)
        rows_a.append(f"{s}{'✓' if h else '✗'}" + (f"[{h[0]['start_d']:%d.%m}-{alive(df, h[0])[1]:%d.%m} {h[0]['status']}]" if h else ""))
    out.append(f"a) senin kutu aralıkların: {ok_a}/{len(USER_BOX)} yakalandı")
    out.append("   " + " ".join(rows_a))

    # b, c) örneklem satırları
    d_ok = d_n = w_bad = w_n = 0
    wl = []
    for m in marks:
        df = frames.get(m["sym"])
        if df is None or m["isr"] not in ("d", "y"):
            continue
        h = hits(df, B[m["sym"]], m["date"] - D(days=3), m["date"] + D(days=3))
        if m["isr"] == "d":
            d_n += 1
            d_ok += bool(h)
        elif m["sym"] not in USER_BOX:
            w_n += 1
            w_bad += bool(h)
            wl.append(f"{m['sym']}{'⚠️' if h else '✓'}")
    out.append(f"b) örneklemde doğru etiketlerin yanında kutu: {d_ok}/{d_n}")
    out.append(f"c) erken-dışı yanlışların yanında kutu: {w_bad}/{w_n} (az iyi)  " + " ".join(wl))

    # d) yoğunluk ve kutu özellikleri
    nb = sum(len(df) for df in frames.values())
    nbox = sum(len(v) for v in B.values())
    dens = nbox / nb * 1000 if nb else 0
    st = Counter(b["status"] + ("/" + b["why"] if b.get("why") else "") for v in B.values() for b in v)
    ln = [b["n"] for v in B.values() for b in v]
    out.append(f"d) yoğunluk: {dens:.1f} kutu/1000 mum (eski etiket 8.1) | ort. kutu {sum(ln) / max(len(ln), 1):.1f} mum")
    out.append("   bitiş: " + ", ".join(f"{k} {v}" for k, v in st.most_common()))

    # kalibrasyon örnekleri (simetrik: pencereyle kesişen kutu)
    t_ok = t_n = f_bad = f_n = 0
    for s, a, z, exp, _n in EXAMPLES:
        df = frames.get(s)
        if df is None:
            continue
        h = hits(df, B[s], pd.Timestamp(a), pd.Timestamp(z))
        if exp:
            t_n += 1
            t_ok += bool(h)
        else:
            f_n += 1
            f_bad += bool(h)
    out.append(f"Bilgi, kalibrasyon örnekleri: doğru {t_ok}/{t_n} yakalandı, yanlış {f_bad}/{f_n} pencerede kutu var "
               f"(eski gösterge: 51/80 ve 14/52; taban/EMA altı örnekler tanım gereği dışarıda)")

    ga, gb, gc, gd = ok_a >= 7, d_ok * 2 >= d_n, w_bad <= 3, 2 <= dens <= 15
    out.append(f"Geçiş şartı: a{'✓' if ga else '✗'} b{'✓' if gb else '✗'} c{'✓' if gc else '✗'} d{'✓' if gd else '✗'} -> "
               + ("✅ kör örnekleme geç" if ga and gb and gc and gd else "❌ önce tanımı birlikte gözden geçirelim"))
    return out


def main():
    marks = read_marks()
    syms = sorted({m["sym"] for m in marks} | {e[0] for e in EXAMPLES} | set(USER_BOX))
    frames = fetch_tv_all(syms, n_bars=1800, budget=15 * 60)
    for _ in range(2):
        miss = [s for s in syms if s not in frames]
        if not miss:
            break
        time.sleep(3)
        frames.update(fetch_tv_all(miss, n_bars=1800, budget=5 * 60))
    out = ["📦 Yaşayan kutu ön kontrolü (taslak v1)", ""]
    out += section(frames, marks, KP(), "A) SENİN TANIMIN: sadece EMA10 ve EMA21 yükseliyor (geçiş şartı bunda)")
    out += [""] + section(frames, marks, KP(PRICE_EMA=True), "B) bilgi: fiyat da EMA21 üstünde, son kapanış EMA10 yakınında")
    txt = "\n".join(out)
    print(txt)
    if "--telegram" in sys.argv:
        for i in range(0, len(txt), 3500):
            telegram_send(txt[i:i + 3500])
            time.sleep(1)


if __name__ == "__main__":
    main()

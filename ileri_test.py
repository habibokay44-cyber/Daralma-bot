"""Kör ileri test özeti: state/etiket_kayit.csv içindeki 'isaret' sütununu sayar.
isaret: d = doğru, y = yanlış, b = belirsiz (boş = henüz bakılmadı)
Çalıştırma: python ileri_test.py [--telegram]
"""
from __future__ import annotations

import csv
import math
import sys
from pathlib import Path

F = Path(__file__).resolve().parent / "state" / "etiket_kayit.csv"


def main() -> None:
    if not F.exists():
        out = "Kayıt dosyası yok. Taramada yeni etiket çıkınca oluşur."
    else:
        rows = list(csv.DictReader(F.open(encoding="utf-8")))
        d = sum(1 for r in rows if r["isaret"].strip().lower() == "d")
        y = sum(1 for r in rows if r["isaret"].strip().lower() == "y")
        b = sum(1 for r in rows if r["isaret"].strip().lower() == "b")
        bos = len(rows) - d - y - b
        n = d + y
        out = f"🧪 Kör ileri test: {len(rows)} etiket | işaretli doğru {d}, yanlış {y}, belirsiz {b} | bakılmamış {bos}\n"
        if n:
            p = d / n
            se = math.sqrt(p * (1 - p) / n)
            out += f"İsabet %{100 * p:.0f} (n={n}, yaklaşık ±%{196 * se:.0f} güven aralığı)\n"
            out += "Karar için en az 30 işaretli etiket bekle.\n" if n < 30 else "n yeterli; örnek-içi oran (%78) ile karşılaştırılabilir.\n"
        yy = [f"{r['hisse']} {r['etiket_tarihi']}" for r in rows if r["isaret"].strip().lower() == "y"]
        if yy:
            out += "Yanlışlar: " + ", ".join(yy)
        pend = [f"{r['hisse']} {r['etiket_tarihi']}" for r in rows if not r["isaret"].strip()]
        if pend:
            out += "\nİşaret bekleyen: " + ", ".join(pend[:25])
    print(out)
    if "--telegram" in sys.argv:
        from scan import telegram_send
        telegram_send(out[:3900])


if __name__ == "__main__":
    main()

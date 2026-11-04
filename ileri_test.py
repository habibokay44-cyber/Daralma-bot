"""Kör test özeti: işaretlenmiş etiket dosyasını sayar.

Varsayılan dosya state/etiket_kayit.csv (ileri test). Örneklem için:
    python ileri_test.py state/orneklem.csv --telegram
isaret: d = doğru, y = yanlış, b = belirsiz (boş = henüz bakılmadı)
cizgi : d = çizgi doğru tepeden, y = çizgi yanlış (boş = bakılmadı)
"""
from __future__ import annotations

import csv
import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def pct(k: int, n: int) -> str:
    if not n:
        return "-"
    p = k / n
    return f"%{100 * p:.0f} (n={n}, ±%{196 * math.sqrt(p * (1 - p) / n):.0f})"


def summarize(path: Path) -> str:
    if not path.exists():
        return f"{path.name} yok. İleri testte ilk etiket çıkınca, örneklemde orneklem.py çalışınca oluşur."
    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    isr = [(r.get("isaret") or "").strip().lower() for r in rows]
    czg = [(r.get("cizgi") or "").strip().lower() for r in rows]
    d, y, b = isr.count("d"), isr.count("y"), isr.count("b")
    bos = len(rows) - d - y - b
    kutu = path.name in ("orneklem2.csv", "orneklem3.csv")
    baslik = ("Kümelenme kutusu örneklemi" if path.name == "orneklem3.csv" else "Kutu örneklemi") if kutu else ("Örneklem" if "orneklem" in path.name else "Kör ileri test")
    out = [f"🧪 {baslik}: {len(rows)} etiket | doğru {d}, yanlış {y}, belirsiz {b} | bakılmamış {bos}"]
    if d + y:
        out.append(f"Etiket isabeti {pct(d, d + y)}")
        both = sum(1 for i, c in zip(isr, czg) if i == "d" and c == "d")
        nc = sum(1 for i, c in zip(isr, czg) if i in ("d", "y") and c in ("d", "y"))
        if nc:
            out.append(f"Etiket VE çizgi doğru {pct(both, nc)}")
            lw = sum(1 for i, c in zip(isr, czg) if i == "d" and c == "y")
            out.append(f"Etiket doğru ama çizgi yanlış: {lw}")
        if kutu:
            out.append("Kutu dedektörü kör sınavı: karar eşiği %75 (eski gösterge kör %62, ilk kutu dedektörü %49). "
                       + ("Karar için en az 30 işaretli kutu bekle." if d + y < 30 else ("✅ eşik geçildi" if d / (d + y) >= 0.75 else "❌ eşik geçilmedi")))
        else:
            out.append("Karar için en az 30 işaretli etiket bekle." if d + y < 30 else "n yeterli; örnek-içi oran (%78) ile karşılaştırılabilir.")
    yy = [f"{r['hisse']} {r['etiket_tarihi']}" for r, i in zip(rows, isr) if i == "y"]
    if yy:
        out.append("Yanlışlar: " + ", ".join(yy))
    pend = [f"{r['hisse']} {r['etiket_tarihi']}" for r, i in zip(rows, isr) if not i]
    if pend:
        out.append("İşaret bekleyen: " + ", ".join(pend[:25]) + (" …" if len(pend) > 25 else ""))
    return "\n".join(out)


def main() -> None:
    files = [a for a in sys.argv[1:] if not a.startswith("--")]
    paths = [HERE / f for f in files] if files else [HERE / "state" / "etiket_kayit.csv"]
    out = "\n\n".join(summarize(p) for p in paths)
    print(out)
    if "--telegram" in sys.argv:
        from scan import telegram_send
        telegram_send(out[:3900])


if __name__ == "__main__":
    main()

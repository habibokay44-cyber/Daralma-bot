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


def _kural(rows, key, bad):
    """Önceden yazılı ölçüt: a) elenenlerde kötü oranı >= 2 x kalanlar b) kötülerin >= %30'u c) iyilerin <= %40'ı elenir."""
    el = [r for r in rows if key(r)]
    ka = [r for r in rows if not key(r)]
    nb = sum(1 for r in rows if bad(r))
    ng = len(rows) - nb
    if not el or not ka:
        return f"elenen {len(el)}, kalan {len(ka)} -> ölçülemez"
    we = sum(1 for r in el if bad(r))
    wk = sum(1 for r in ka if bad(r))
    re_, rk = we / len(el), wk / len(ka)
    a_ = (rk == 0 and re_ > 0) or (rk > 0 and re_ >= 2 * rk)
    b_, c_ = we >= 0.3 * nb, (len(el) - we) <= 0.4 * ng
    return (f"elenen {len(el)} ({we} kötü) | kalanda iyi kurulum %{100 * (len(ka) - wk) / len(ka):.0f} | "
            f"a{'✓' if a_ else '✗'} b{'✓' if b_ else '✗'} c{'✓' if c_ else '✗'} -> {'✅' if a_ and b_ and c_ else '❌'}")


def ileri(path: Path) -> str:
    """İleri test kaydı: buton cevapları (a/g/h) + eski elle işaretler (d/y/b) + v56 gölge ölçümü."""
    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    isr = [(r.get("isaret") or "").strip().lower() for r in rows]
    c = {k: isr.count(k) for k in ("a", "g", "h", "d", "y", "b")}
    bos = sum(1 for i in isr if not i)
    out = [f"🧪 Kör ileri test: {len(rows)} etiket | ✅ alırdım {c['a']}, ⏳ başka gün {c['g']}, ❌ almazdım {c['h']}"
           + (f" | eski işaret d{c['d']} y{c['y']} b{c['b']}" if c['d'] + c['y'] + c['b'] else "") + f" | bakılmamış {bos}"]
    iyi = [r for r, i in zip(rows, isr) if i in ("a", "g", "d")]
    kotu = [r for r, i in zip(rows, isr) if i in ("h", "y")]
    n = len(iyi) + len(kotu)
    if n:
        out.append(f"İyi kurulum oranı (alırdım + başka gün) {pct(len(iyi), n)}; o gün alırdım {pct(c['a'], c['a'] + c['g'] + c['h'])}")
    # v56 gölge: E1, Y1, E1 ve Y1 (05.11.2026'da sabitlendi)
    ol = [r for r in iyi + kotu if (r.get("e1") or "") in ("0", "1")]
    if ol:
        bad = lambda r: (r.get("isaret") or "").lower() in ("h", "y")  # noqa: E731
        out.append(f"v56 gölge ({len(ol)} işaretli etiket{', karar için 30 bekle' if len(ol) < 30 else ''}):")
        out.append("  E1 EMA düşüyor: " + _kural(ol, lambda r: r.get("e1") == "1", bad))
        out.append("  Y1 yükseliş <%15: " + _kural(ol, lambda r: r.get("y1") == "1", bad))
        out.append("  E1 ve Y1: " + _kural(ol, lambda r: r.get("e1") == "1" and r.get("y1") == "1", bad))
    # zamanlama: senin alış günün göstergenin Giriş günüyle ±1 iş günü içinde mi
    zr = [r for r in rows if r.get("alis_tarihi") and r.get("giris_tarihi")]
    if zr:
        import numpy as np
        hit = sum(1 for r in zr if abs(int(np.busday_count(r["giris_tarihi"], r["alis_tarihi"]))) <= 1)
        out.append(f"Zamanlama: alış günün Giriş etiketiyle ±1 gün içinde {pct(hit, len(zr))}")
    pend = [f"{r['hisse']} {r['etiket_tarihi']}" for r, i in zip(rows, isr) if not i]
    if pend:
        out.append("İşaret bekleyen: " + ", ".join(pend[:25]) + (" …" if len(pend) > 25 else ""))
    return "\n".join(out)


def summarize(path: Path) -> str:
    if path.exists() and path.name == "etiket_kayit.csv":
        return ileri(path)
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

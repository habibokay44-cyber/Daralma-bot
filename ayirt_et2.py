"""ayirt_et.py'nin genişletilmiş hali: eski 43 pencere + calibrate.py içindeki tüm örnekler (doğru/yanlış).
Hiçbir ayarı değiştirmez, sadece ölçüp Telegram'a yazar.
Çalıştırma: python ayirt_et2.py --telegram
"""
from __future__ import annotations

import sys

import ayirt_et as A
from calibrate import EXAMPLES


def build() -> list[tuple[str, str, str, int]]:
    lab = list(A.LAB)
    seen = {(s, a) for s, a, _b, _l in lab}
    for s, a, b, expect, _note in EXAMPLES:
        if (s, a) in seen:
            continue
        seen.add((s, a))
        lab.append((s, a, b, 1 if expect else 0))
    return lab


if __name__ == "__main__":
    A.LAB = build()
    print(f"Pencere sayısı: {len(A.LAB)} (d={sum(1 for *_, l in A.LAB if l)}, y={sum(1 for *_, l in A.LAB if not l)})", file=sys.stderr)
    sys.exit(A.main())

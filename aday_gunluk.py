"""Günlük 'olası daralma' izleme listesi.

Botun etiket koymadığı ama küçük mumların dirence yakın toplandığı hisseleri ayrı bir mesajla gönderir.
Ana etiketlere ve sinyallere dokunmaz. Güven düşüktür: geçmiş örneklemede adayların yaklaşık yarısı
senin gözünle gerçek daralma çıktı. Son karar sende, grafikte bak.

Çalıştırma: python aday_gunluk.py            (Telegram'a gönderir)
            python aday_gunluk.py --dry      (göndermez, ekrana yazar)
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

from gecmis_tara import candidates
from scan import fetch_tv_all, get_tickers, link, telegram_send

STATE = Path(__file__).parent / "state" / "aday_sent.json"
TOP = 15          # günde en fazla bu kadar aday
REPEAT_DAYS = 14  # aynı hisse için tekrar bildirim aralığı


def load() -> dict:
    try:
        return json.loads(STATE.read_text())
    except Exception:  # noqa: BLE001
        return {}


def save(st: dict) -> None:
    cut = (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d")
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps({k: v for k, v in st.items() if v >= cut}, indent=0, sort_keys=True))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    args = ap.parse_args()
    frames = fetch_tv_all(get_tickers(), n_bars=500)
    st = load()
    today = datetime.now()
    found = []
    for sym, df in frames.items():
        try:
            n = len(df)
            for x in candidates(sym, df, skip_labeled=True, span=1):
                if x["i"] != n - 1:          # pencere bugün bitmeli
                    continue
                last = st.get(sym)
                if last and (today - datetime.strptime(last, "%Y-%m-%d")).days < REPEAT_DAYS:
                    continue
                found.append(x)
        except Exception as e:  # noqa: BLE001
            print(f"[uyarı] {sym}: {e}", file=sys.stderr)
    found.sort(key=lambda x: x["bb"])
    found = found[:TOP]
    if not found:
        print("Bugün aday yok.")
        return
    lines = [f"• {x['sym']}  direnç~{x['res']:.2f}  gövde kutusu {x['bb']:.2f} ADR  {link(x['sym'])}" for x in found]
    msg = ("🟡 Olası daralma adayları (düşük güven, bot etiket koymadı)\n"
           f"{found[0]['b']:%d.%m.%Y} kapanışı: son 6 mumda küçük gövdeler dirence yakın. "
           "Geçmişte yaklaşık yarısı gerçek daralma çıktı, grafikte kendin bak.\n\n" + "\n".join(lines))
    print(msg)
    if not args.dry:
        telegram_send(msg)
        for x in found:
            st[x["sym"]] = today.strftime("%Y-%m-%d")
        save(st)


if __name__ == "__main__":
    sys.exit(main())

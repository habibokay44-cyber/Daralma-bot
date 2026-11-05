"""Telegram buton ve cevaplarını ileri test kaydına (state/etiket_kayit.csv) işler.

Grafiklerin altındaki butonlar: ✅ Alırdım (a) · ⏳ Başka gün (g) · ❌ Almazdım (h) · 📐 Çizgi yanlış.
Bir grafiğe cevap olarak tarih yazarsan (örn. 12.11) alış günün olarak kaydedilir ve işaret 'g' olur.
Tarih dışındaki yazı not alanına eklenir. Fikrini değiştirirsen başka bir butona basman yeterli.

Telegram mesajları bekletir; bu script 3 saatte bir (ve elle) çalışıp bekleyenleri işler.
Sadece TELEGRAM_CHAT_ID sohbetinden gelenler dikkate alınır.
Çalıştırma: python telegram_isle.py
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

import pandas as pd
import requests

import kayit

HERE = Path(__file__).resolve().parent
OFFSET = HERE / "state" / "tg_offset.json"
ESLE = HERE / "state" / "tg_mesaj.json"
AD = {"a": "✅ Alırdım", "g": "⏳ Başka gün", "h": "❌ Almazdım", "c": "📐 Çizgi yanlış"}


def api(method, **kw):
    token = os.environ["TELEGRAM_TOKEN"]
    r = requests.post(f"https://api.telegram.org/bot{token}/{method}", json=kw, timeout=60)
    js = r.json() if r.content else {}
    if not r.ok or not js.get("ok", False):
        raise RuntimeError(f"{method}: {r.status_code} {str(js)[:200]}")
    return js.get("result")


def jload(p, default):
    try:
        return json.loads(p.read_text())
    except Exception:  # noqa: BLE001
        return default


def tarih_bul(text: str, etiket: str):
    m = re.search(r"\b(\d{1,2})[./-](\d{1,2})(?:[./-](\d{2,4}))?\b", text)
    if not m:
        return None, text.strip()
    g, a = int(m.group(1)), int(m.group(2))
    et = pd.Timestamp(etiket)
    y = int(m.group(3)) if m.group(3) else et.year
    if y < 100:
        y += 2000
    try:
        d = pd.Timestamp(year=y, month=a, day=g)
    except ValueError:
        return None, text.strip()
    if not m.group(3) and d < et - pd.Timedelta(days=60):
        d = pd.Timestamp(year=y + 1, month=a, day=g)
    rest = (text[:m.start()] + text[m.end():]).strip()
    return d.strftime("%Y-%m-%d"), rest


def main() -> int:
    chat = str(os.environ.get("TELEGRAM_CHAT_ID", ""))
    off = jload(OFFSET, {}).get("offset")
    esle = jload(ESLE, {})
    kw = {"timeout": 0, "allowed_updates": ["callback_query", "message"]}
    if off:
        kw["offset"] = off
    ups = api("getUpdates", **kw) or []
    rows = kayit.load()
    idx = {kayit.key(r["hisse"], r["etiket_tarihi"]): r for r in rows}
    degisti, islenen = False, []
    for u in ups:
        off = u["update_id"] + 1
        cq = u.get("callback_query")
        if cq:
            msg = cq.get("message") or {}
            if str((msg.get("chat") or {}).get("id")) != chat or not str(cq.get("data", "")).startswith("i|"):
                continue
            _, sym, d8, act = cq["data"].split("|")
            k = kayit.key(sym, f"{d8[:4]}-{d8[4:6]}-{d8[6:]}")
            r = idx.get(k)
            if r is None:
                api("answerCallbackQuery", callback_query_id=cq["id"], text="Bu etiket kayıtta yok")
                continue
            if act == "c":
                r["cizgi"] = "y"
            else:
                r["isaret"] = act
                if act == "a":
                    r["alis_tarihi"] = r["etiket_tarihi"]
                elif act == "h":
                    r["alis_tarihi"] = ""
            degisti = True
            islenen.append(f"{sym} {AD[act]}")
            try:
                api("answerCallbackQuery", callback_query_id=cq["id"], text=f"Kaydedildi: {AD[act]}")
            except Exception:  # noqa: BLE001  (birkaç saniyeden eski basışlarda Telegram süresi dolar; zararsız)
                pass
            try:
                cap = (msg.get("caption") or "").split("\n✔")[0]
                durum = AD.get(r["isaret"], "") + (" · 📐 çizgi yanlış" if r["cizgi"] == "y" else "")
                api("editMessageCaption", chat_id=msg["chat"]["id"], message_id=msg["message_id"],
                    caption=f"{cap}\n✔ {durum}", reply_markup=msg.get("reply_markup"))
            except Exception as ex:  # noqa: BLE001
                print(f"[bilgi] açıklama güncellenemedi: {ex}")
            continue
        m = u.get("message")
        if m and str((m.get("chat") or {}).get("id")) == chat and m.get("reply_to_message") and m.get("text"):
            k = esle.get(str(m["reply_to_message"]["message_id"]))
            r = idx.get(k) if k else None
            if r is None:
                continue
            d, rest = tarih_bul(m["text"], r["etiket_tarihi"])
            if d:
                r["alis_tarihi"] = d
                if r["isaret"] in ("", "a"):
                    r["isaret"] = "g"
            if rest:
                r["not"] = (r["not"] + " - " if r["not"] else "") + rest.replace(",", " -")
            degisti = True
            islenen.append(f"{r['hisse']} alış {d or '-'}{' not' if rest else ''}")
            try:
                api("sendMessage", chat_id=m["chat"]["id"], reply_to_message_id=m["message_id"],
                    text=f"✔ Kaydedildi: {r['hisse']} {AD.get(r['isaret'], '')}" + (f" · alış {pd.Timestamp(d):%d.%m.%Y}" if d else ""))
            except Exception as ex:  # noqa: BLE001
                print(f"[bilgi] {ex}")
    if degisti:
        kayit.save(rows)
        try:
            api("sendMessage", chat_id=chat, text=f"✔ {len(islenen)} işaret kaydedildi: " + ", ".join(islenen)[:3500])
        except Exception as ex:  # noqa: BLE001
            print(f"[bilgi] özet mesajı gönderilemedi: {ex}")
    if off:
        OFFSET.parent.mkdir(parents=True, exist_ok=True)
        OFFSET.write_text(json.dumps({"offset": off}))
    print(f"{len(ups)} güncelleme, işlenen: {', '.join(islenen) or '-'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

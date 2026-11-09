"""Telegram buton ve cevaplarını ileri test kaydına (state/etiket_kayit.csv) işler.

Grafiklerin altındaki butonlar: ✅ Alırdım (a) · ⏳ Başka gün (g) · ❌ Almazdım (h) · 📐 Çizgi yanlış.
Bir grafiğe cevap olarak tarih yazarsan (örn. 12.11) alış günün olarak kaydedilir ve işaret 'g' olur.
Sistemin vermediği ama senin aldığın kurulumlar: bota "kaçan KRGYO 30.10" yaz (isteğe bağlı sonuna not)
-> state/kacan.csv'ye kaydedilir; kacan_tani.py hangi kapının engellediğini gösterir.
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
KACAN = HERE / "state" / "kacan.csv"
DIRENC_RE = re.compile(r"^\s*diren[çc]\s*:?\s*(yok|\d+(?:[.,]\d+)?)\s*(?:(\d{1,2})(?![\d.,/-])\s*(?:temas)?)?\s*(.*)$", re.I)
# 07.11.2026: temas sayısı sadece arkasından tarih gelmiyorsa okunur ("direnç 29,74 10.11.23 ..." -> temas yok, not tam)
KACAN_RE = re.compile(r"^\s*ka[çc]an\s+([A-Za-zÇĞİÖŞÜçğıöşü0-9]+)\s+(\d{1,2}[./-]\d{1,2}(?:[./-]\d{2,4})?)\s*(.*)$", re.I)


def kacan_kaydet(text: str):
    m = KACAN_RE.match(text)
    if not m:
        return None
    sym = m.group(1).upper().replace("İ", "I")
    bugun = pd.Timestamp.now(tz="Europe/Istanbul").tz_localize(None).normalize()
    d, _ = tarih_bul(m.group(2), f"{bugun:%Y-%m-%d}")
    if d and pd.Timestamp(d) > bugun + pd.Timedelta(days=5):
        d = f"{pd.Timestamp(d) - pd.DateOffset(years=1):%Y-%m-%d}"
    if not d:
        return None
    import csv
    yeni = not KACAN.exists()
    KACAN.parent.mkdir(parents=True, exist_ok=True)
    with KACAN.open("a", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        if yeni:
            w.writerow(["bildirim_tarihi", "hisse", "tarih", "not"])
        w.writerow([f"{bugun:%Y-%m-%d}", sym, d, m.group(3).replace(",", " -").strip()])
    return sym, d
STAGE = {"s1": "Stage 1", "s2": "Stage 2", "s3": "Tepe (3)", "s4": "Düşüş (4)"}
AD = {"a": "✅ Alırdım", "g": "⏳ Başka gün", "h": "❌ Almazdım", "c": "📐 Çizgi yanlış", **STAGE}


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
    if not m.group(3):   # yıl yazılmadıysa: etiket gününe en yakın yıl (09.11.2026: 24.08 -> 2027 hatası düzeltildi)
        aday = []
        for yy in (y - 1, y, y + 1):
            try:
                aday.append(pd.Timestamp(year=yy, month=a, day=g))
            except ValueError:
                pass
        d = min(aday, key=lambda x: abs((x - et).days))
    rest = (text[:m.start()] + text[m.end():]).strip()
    return d.strftime("%Y-%m-%d"), rest


def main() -> int:
    chat = str(os.environ.get("TELEGRAM_CHAT_ID", ""))
    off = jload(OFFSET, {}).get("offset")
    esle = jload(ESLE, {})
    kw = {"timeout": 0, "allowed_updates": ["callback_query", "message"]}
    if off:
        kw["offset"] = off
    ups = []
    for _ in range(20):  # Telegram tek seferde en fazla 100 güncelleme verir: hepsi gelene kadar devam
        part = api("getUpdates", **kw) or []
        ups += part
        if len(part) < 100:
            break
        kw["offset"] = part[-1]["update_id"] + 1
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
                # Kayıtta yoksa (ör. kayıt commit'i başarısız olduysa) satırı grafik açıklamasından kur: "HISSE · tarih · mod"
                parca = (msg.get("caption") or "").split("\n")[0].split(" · ")
                r = {c: "" for c in kayit.COLS}
                r.update(bildirim_tarihi=f"{pd.Timestamp.now(tz='Europe/Istanbul'):%Y-%m-%d}", hisse=sym,
                         etiket_tarihi=f"{d8[:4]}-{d8[4:6]}-{d8[6:]}", mod=parca[2].strip() if len(parca) >= 3 else "")
                if r["mod"] in ("BaseV0", "BaseV0b", "BaseV1", "BaseV2", "BaseV3", "Base", "BaseT2"):
                    r["giris_tarihi"] = r["etiket_tarihi"]
                rows.append(r)
                idx[k] = r
                print(f"[bilgi] {sym} {r['etiket_tarihi']} kayıtta yoktu, açıklamadan eklendi ({r['mod'] or 'mod?'})")
            if act == "c":
                r["cizgi"] = "y"
            elif act in STAGE:
                r["stage"] = act[1]
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
                durum = " · ".join(x for x in (AD.get(r["isaret"], ""), STAGE.get(f"s{r.get('stage', '')}", ""),
                                               "📐 çizgi yanlış" if r["cizgi"] == "y" else "") if x)
                api("editMessageCaption", chat_id=msg["chat"]["id"], message_id=msg["message_id"],
                    caption=f"{cap}\n✔ {durum}", reply_markup=msg.get("reply_markup"))
            except Exception as ex:  # noqa: BLE001
                print(f"[bilgi] açıklama güncellenemedi: {ex}")
            continue
        m = u.get("message")
        if m and str((m.get("chat") or {}).get("id")) == chat and m.get("text") and not m.get("reply_to_message"):
            # Bir mesajda birden çok satır olabilir: her "kaçan ..." satırı ayrı kaydedilir
            ok, red = [], []
            for line in m["text"].splitlines():
                if not line.strip():
                    continue
                kk = kacan_kaydet(line)
                if kk:
                    ok.append(kk)
                    islenen.append(f"kaçan {kk[0]} {kk[1]}")
                elif re.match(r"^\s*ka[çc]an\b", line, re.I):
                    red.append(line.strip()[:40])
            if ok or red:
                try:
                    api("sendMessage", chat_id=m["chat"]["id"], reply_to_message_id=m["message_id"],
                        text=("✔ Kaçan kaydedildi: " + ", ".join(f"{s} {pd.Timestamp(d):%d.%m.%Y}" for s, d in ok) if ok else "")
                        + ("\n⚠ Okunamadı (biçim: kaçan HISSE GG.AA.YYYY not): " + " | ".join(red) if red else ""))
                except Exception as ex:  # noqa: BLE001
                    print(f"[bilgi] {ex}")
            continue
        if m and str((m.get("chat") or {}).get("id")) == chat and m.get("reply_to_message") and m.get("text"):
            k = esle.get(str(m["reply_to_message"]["message_id"]))
            r = idx.get(k) if k else None
            if r is None:
                continue
            dm = DIRENC_RE.match(m["text"])
            if dm:  # "direnç 12,40 3 [not]" ya da "direnç yok": senin gördüğün direnç ve temas sayısı
                r["direnc_sen"] = dm.group(1).lower().replace(",", ".")
                r["temas_sen"] = dm.group(2) or ""
                if dm.group(3).strip():
                    r["not"] = (r["not"] + " - " if r["not"] else "") + dm.group(3).strip().replace(",", " -")
                degisti = True
                islenen.append(f"{r['hisse']} direnç {r['direnc_sen']}" + (f" ({r['temas_sen']} temas)" if r["temas_sen"] else ""))
                try:
                    api("sendMessage", chat_id=m["chat"]["id"], reply_to_message_id=m["message_id"],
                        text=f"✔ {r['hisse']}: direnç {r['direnc_sen']}" + (f", {r['temas_sen']} temas" if r["temas_sen"] else ""))
                except Exception as ex:  # noqa: BLE001
                    print(f"[bilgi] {ex}")
                continue
            # 07.11.2026: alış tarihi sadece cevap TARİHLE BAŞLIYORSA alınır (nottaki tarihler alış sayılmaz)
            # 09.11.2026: ve tarih etiket gününe 30 günden yakınsa VE cevapta "al" geçiyorsa ya da tarihten başka bir şey yoksa
            # ("24.08 tepesinden ... çizgi" gibi notlar alış sayılmaz)
            d, rest = None, m["text"].strip()
            if re.match(r"^\s*\d{1,2}[./-]\d{1,2}", m["text"]):
                d0, rest0 = tarih_bul(m["text"], r["etiket_tarihi"])
                if d0 and abs((pd.Timestamp(d0) - pd.Timestamp(r["etiket_tarihi"])).days) <= 30 and (
                        not rest0 or re.search(r"\b(alır|alış|alis|alir|al)\w*", rest0.lower()) and "almaz" not in rest0.lower()):
                    d, rest = d0, rest0
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
    if islenen:
        try:
            api("sendMessage", chat_id=chat, text=f"✔ {len(islenen)} kayıt işlendi: " + ", ".join(islenen)[:3500])
        except Exception as ex:  # noqa: BLE001
            print(f"[bilgi] özet mesajı gönderilemedi: {ex}")
    if off:
        OFFSET.parent.mkdir(parents=True, exist_ok=True)
        OFFSET.write_text(json.dumps({"offset": off}))
    print(f"{len(ups)} güncelleme, işlenen: {', '.join(islenen) or '-'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

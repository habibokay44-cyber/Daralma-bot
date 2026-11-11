"""Sanal portföy (06.11.2026): taramanın Giriş ve Base sinyalleriyle kâğıt üzerinde işlem. Gerçek emir vermez.

KURALLAR (önceden sabitlendi):
  Başlangıç   : 100.000 TL nakit, 07.11.2026'dan itibaren.
  Sinyaller   : ana göstergenin GİRİŞ sinyali ve Base kırılımı (v0). Sadece SİNYAL GÜNÜ taramada görülenler alınır
                (gecikmeli görülen sinyal 'geç' diye kaydedilir, alınmaz).
  Alış        : sinyal günü kapanış fiyatından. Komisyon her yönde %0.1.
  Stop        : sinyal mumunun dibi (Iz10, Pine ve takip.py ile aynı kural).
  Risk        : işlem başı özsermayenin en fazla %1'i (stop olursa kayıp ≈ %1).
  Büyüklük    : en fazla özsermayenin 1/5'i (100.000'de 20.000 TL), en fazla 5 açık işlem, aynı hissede tek işlem.
                Yer yoksa / nakit yetmezse sinyal 'atlandı' diye kaydedilir.
  Çıkış (Iz10, KAPANIŞLA - 06.11.2026): fiyat girişin +1R üstünü görünce stop girişe çekilir; sonra son 10 mumun dibini
                izler (sadece yukarı). Gün KAPANIŞI stopun altındaysa o kapanıştan çıkılır; gün içi stopa değmek çıkış değildir.
                Hedef ve süre sınırı yok. (Kapanışla çıkış, kaybın bazen -1R'yi aşması demektir; mesajda R olarak görünür.)
Durum dosyası: state/portfoy.json
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import pandas as pd

F = Path(__file__).resolve().parent / "state" / "portfoy.json"
BASLANGIC, RISK, MAXPOZ, KOM, ARM, TRAIL = 100_000.0, 0.01, 5, 0.001, 1.0, 10


def yukle(dosya: Path = F) -> dict:
    try:
        return json.loads(dosya.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return dict(nakit=BASLANGIC, acik=[], kapali=[], atlanan=[], baslangic="")


def kaydet(p: dict, dosya: Path = F) -> None:
    dosya.parent.mkdir(parents=True, exist_ok=True)
    dosya.write_text(json.dumps(p, ensure_ascii=False, indent=1), encoding="utf-8")


def iz(df: pd.DataFrame, giris_tarihi: str, giris: float, stop0: float) -> dict:
    """Iz10: girişten bugüne mum mum. Kapandıysa çıkış, değilse güncel stop."""
    o, h, l, c = (df[k].to_numpy(float) for k in ("Open", "High", "Low", "Close"))
    t = int(df.index.searchsorted(pd.Timestamp(giris_tarihi)))
    R = giris - stop0
    s, armed = stop0, False
    for k in range(t + 1, len(c)):
        if c[k] < s:   # KAPANIŞ stopun altındaysa o günün kapanışından çıkılır (gün içi değme çıkış değil)
            return dict(kapandi=True, tarih=f"{df.index[k]:%Y-%m-%d}", cikis=float(c[k]))
        if not armed and h[k] >= giris + ARM * R:
            armed = True
            s = max(s, giris)
        if armed:
            s = max(s, float(l[max(t + 1, k - TRAIL + 1):k + 1].min()))
    return dict(kapandi=False, stop=float(s), son=float(c[-1]), armed=armed)


def gunluk(frames: dict, sinyaller: list[dict], bugun: pd.Timestamp, dosya: Path = F, baslik: str = "Sanal portföy",
           gecmis_ok: bool = False) -> str:
    """sinyaller: dict(sym, kaynak ('Giriş'/'Base'), tarih 'YYYY-AA-GG', kapanis, dip). Mesaj metni döner.
    gecmis_ok: geçmiş tarihli sinyal de (o günün kapanışından) alınır; onaylı portföy için (onay sinyalden sonra gelir)."""
    p = yukle(dosya)
    if not p.get("baslangic"):
        p["baslangic"] = f"{bugun:%Y-%m-%d}"
    olay = []

    def guncelle():   # açık işlemleri giriş gününden bugüne izle (Iz10)
        kalan = []
        for a in p["acik"]:
            df = frames.get(a["sym"])
            if df is None:
                kalan.append(a)
                continue
            r = iz(df, a["tarih"], a["giris"], a["stop0"])
            if r["kapandi"]:
                net = a["lot"] * r["cikis"] * (1 - KOM)
                p["nakit"] += net
                kz = net - a["maliyet"]
                Rk = (r["cikis"] - a["giris"]) / (a["giris"] - a["stop0"])
                p["kapali"].append({**a, "cikis_tarihi": r["tarih"], "cikis": r["cikis"], "kz": round(kz, 2), "R": round(Rk, 2)})
                olay.append(f"🔴 SAT {a['sym']} ({a['kaynak']}) {a['lot']} lot @ {r['cikis']:.2f} | {kz:+,.0f} TL ({Rk:+.2f}R)")
            else:
                a.update(stop=r["stop"], son=r["son"], armed=r["armed"])
                kalan.append(a)
        p["acik"] = kalan

    guncelle()   # 1) açık işlemleri güncelle
    # 2) yeni sinyaller
    ozs = p["nakit"] + sum(a["lot"] * a.get("son", a["giris"]) for a in p["acik"])
    for s in sinyaller:
        kayit = dict(sym=s["sym"], kaynak=s["kaynak"], tarih=s["tarih"])
        if pd.Timestamp(s["tarih"]) != bugun and not gecmis_ok:
            p["atlanan"].append({**kayit, "neden": "geç görüldü"})
            continue
        if any(a["sym"] == s["sym"] for a in p["acik"]):
            p["atlanan"].append({**kayit, "neden": "zaten elde"})
            continue
        if len(p["acik"]) >= MAXPOZ:
            p["atlanan"].append({**kayit, "neden": "5 işlem dolu"})
            olay.append(f"⏸ {s['sym']} ({s['kaynak']}) alınmadı: 5 işlem dolu")
            continue
        giris, stop0 = float(s["kapanis"]), float(s["dip"])
        R = giris - stop0
        if R <= 0:
            p["atlanan"].append({**kayit, "neden": "stop girişte"})
            continue
        lot = math.floor(min(ozs * RISK / R, ozs / MAXPOZ / giris, p["nakit"] / (giris * (1 + KOM))))
        if lot <= 0:
            p["atlanan"].append({**kayit, "neden": "nakit yetmedi"})
            olay.append(f"⏸ {s['sym']} ({s['kaynak']}) alınmadı: nakit yetmedi")
            continue
        maliyet = lot * giris * (1 + KOM)
        p["nakit"] -= maliyet
        p["acik"].append(dict(sym=s["sym"], kaynak=s["kaynak"], tarih=s["tarih"], giris=giris, stop0=stop0, stop=stop0,
                              lot=lot, maliyet=round(maliyet, 2), son=giris, armed=False))
        olay.append(f"🟢 AL {s['sym']} ({s['kaynak']}) {lot} lot @ {giris:.2f} = {maliyet:,.0f} TL | stop {stop0:.2f} "
                    f"(-%{R / giris * 100:.1f}, risk {lot * R:,.0f} TL)")
    if gecmis_ok:
        guncelle()   # geçmiş tarihli alınanları bugüne kadar izle
    kaydet(p, dosya)
    # 3) özet
    deger = sum(a["lot"] * a.get("son", a["giris"]) for a in p["acik"])
    ozs = p["nakit"] + deger
    out = [f"💼 {baslik} · {bugun:%d.%m.%Y} · özsermaye {ozs:,.0f} TL ({(ozs / BASLANGIC - 1) * 100:+.2f}%) · "
           f"nakit {p['nakit']:,.0f} · açık {len(p['acik'])}/{MAXPOZ}"]
    out += olay
    for a in p["acik"]:
        out.append(f"  • {a['sym']} ({a['kaynak']}) {a['tarih'][8:10]}.{a['tarih'][5:7]} @ {a['giris']:.2f} → {a['son']:.2f} "
                   f"({(a['son'] / a['giris'] - 1) * 100:+.1f}%) | stop {a['stop']:.2f}{' 🔒' if a.get('armed') else ''}")
    for k in ("Giriş", "Base"):
        K = [x for x in p["kapali"] if x["kaynak"] == k]
        if K:
            kaz = sum(1 for x in K if x["kz"] > 0)
            out.append(f"  {k}: {len(K)} kapanan · kazanma %{kaz / len(K) * 100:.0f} · toplam {sum(x['kz'] for x in K):+,.0f} TL"
                       f" · ort {sum(x['R'] for x in K) / len(K):+.2f}R")
    at = [x for x in p["atlanan"] if x["neden"] in ("5 işlem dolu", "nakit yetmedi")]
    if at:
        out.append(f"  yer olmadığı için alınamayan: {len(at)}")
    return "\n".join(out)


# ------------------------------------------------------------------ onaylı gölge portföy (09.11.2026)
F2 = F.with_name("portfoy_onay.json")
FB = F.with_name("portfoy_onay_bekleyen.json")
BEKLE_GUN = 7


def gunluk_onayli(frames: dict, sinyaller: list[dict], bugun: pd.Timestamp) -> str:
    """Gölge portföy: aynı kurallar, ama sadece senin ✅ bastığın sinyaller.
    Neden: işaret-getiri testi (09.11.2026) daralmada 'alırdım' PF 3-4.7, 'almazdım' PF 0.65-0.70 buldu; canlıda da böyle mi?
    Onay sinyalden sonra geldiği için sinyal BEKLEYEN listesine girer; işaret gelince SİNYAL GÜNÜ kapanışından alınır
    (ana portföyle aynı fiyat -> adil karşılaştırma). Onay: Base sinyalinde 'a'; Giriş sinyalinde etiketin 'a' ya da 'g'
    (kurulum iyi, Giriş günü alınır). 'h' -> alınmaz. 7 gün içinde işaret gelmezse düşer."""
    import kayit
    try:
        bek = json.loads(FB.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        bek = []
    var = {(b["sym"], b["tarih"], b["kaynak"]) for b in bek}
    bek += [dict(s, kapanis=float(s["kapanis"]), dip=float(s["dip"])) for s in sinyaller
            if (s["sym"], s["tarih"], s["kaynak"]) not in var and pd.Timestamp(s["tarih"]) == bugun]
    rows = kayit.load()
    al, kalan, red = [], [], []
    for b in bek:
        if b["kaynak"] == "Base":
            r = [x for x in rows if x["hisse"] == b["sym"] and x["etiket_tarihi"] == b["tarih"] and x.get("mod") == "Base"]
            ok = {"a"}
        else:
            r = [x for x in rows if x["hisse"] == b["sym"] and not (x.get("mod") or "").startswith("Base")
                 and (x.get("giris_tarihi") == b["tarih"] or x["etiket_tarihi"] <= b["tarih"])]
            r = sorted(r, key=lambda x: x["etiket_tarihi"])[-1:]
            ok = {"a", "g"}
        i = (r[-1].get("isaret") or "").strip().lower() if r else ""
        if i in ok:
            al.append(b)
        elif i:
            red.append(b["sym"])
        elif (bugun - pd.Timestamp(b["tarih"])).days <= BEKLE_GUN:
            kalan.append(b)
    FB.write_text(json.dumps(kalan, ensure_ascii=False, indent=1), encoding="utf-8")
    txt = gunluk(frames, al, bugun, dosya=F2, baslik="Onaylı portföy (sadece ✅ dediklerin)", gecmis_ok=True)
    if red:
        txt += "\n  onaylamadığın için alınmayan: " + ", ".join(red)
    if kalan:
        txt += "\n  işaretini bekleyen: " + ", ".join(f"{b['sym']} {b['tarih'][8:10]}.{b['tarih'][5:7]}" for b in kalan)
    return txt


# ------------------------------------------------------------------ RS gölge portföy (11.11.2026)
F3 = F.with_name("portfoy_rs.json")


def gunluk_rs(frames: dict, sinyaller: list[dict], bugun: pd.Timestamp, xu_close) -> str:
    """Gölge portföy: aynı kurallar, sadece RS çizgisi GÜÇLÜ olan sinyaller (rs.py tanımı).
    Neden: RS güçlü testi (11.11.2026) tek tek işlemde kıl payı red, ama 'sadece RS güçlü' portföy iki dönemde de önde (yan bilgi).
    Karar canlıda: ana / onaylı / RS portföyleri yan yana. İlk çalıştırmada ana portföyün 09.11'den beri aldığı sinyaller de
    (RS güçlüyse) aynı fiyattan eklenir, böylece üçü aynı günden başlar."""
    import rs
    ilk = not F3.exists()
    adaylar = list(sinyaller)
    if ilk:
        ana = yukle()
        for a in ana.get("acik", []) + ana.get("kapali", []):
            adaylar.append(dict(sym=a["sym"], kaynak=a["kaynak"], tarih=a["tarih"], kapanis=a["giris"], dip=a["stop0"]))
    al, zayif = [], []
    for s in adaylar:
        df = frames.get(s["sym"])
        o = rs.olc(df, xu_close, s["tarih"]) if (df is not None and xu_close is not None) else None
        if o is not None and o["guclu"]:
            al.append(s)
        else:
            zayif.append(s["sym"])
    txt = gunluk(frames, al, bugun, dosya=F3, baslik="RS portföyü (sadece RS güçlü)", gecmis_ok=ilk)
    if zayif:
        txt += "\n  RS zayıf olduğu için alınmayan: " + ", ".join(zayif)
    return txt

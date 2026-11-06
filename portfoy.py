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
  Çıkış (Iz10): fiyat girişin +1R üstünü görünce stop girişe çekilir; sonra son 10 mumun dibini izler (sadece yukarı).
                Açılış stopun altındaysa açılıştan çıkılır. Hedef ve süre sınırı yok.
Durum dosyası: state/portfoy.json
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import pandas as pd

F = Path(__file__).resolve().parent / "state" / "portfoy.json"
BASLANGIC, RISK, MAXPOZ, KOM, ARM, TRAIL = 100_000.0, 0.01, 5, 0.001, 1.0, 10


def yukle() -> dict:
    try:
        return json.loads(F.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return dict(nakit=BASLANGIC, acik=[], kapali=[], atlanan=[], baslangic="")


def kaydet(p: dict) -> None:
    F.parent.mkdir(parents=True, exist_ok=True)
    F.write_text(json.dumps(p, ensure_ascii=False, indent=1), encoding="utf-8")


def iz(df: pd.DataFrame, giris_tarihi: str, giris: float, stop0: float) -> dict:
    """Iz10: girişten bugüne mum mum. Kapandıysa çıkış, değilse güncel stop."""
    o, h, l, c = (df[k].to_numpy(float) for k in ("Open", "High", "Low", "Close"))
    t = int(df.index.searchsorted(pd.Timestamp(giris_tarihi)))
    R = giris - stop0
    s, armed = stop0, False
    for k in range(t + 1, len(c)):
        if o[k] <= s or l[k] <= s:
            return dict(kapandi=True, tarih=f"{df.index[k]:%Y-%m-%d}", cikis=float(min(o[k], s)) if o[k] <= s else float(s))
        if not armed and h[k] >= giris + ARM * R:
            armed = True
            s = max(s, giris)
        if armed:
            s = max(s, float(l[max(t + 1, k - TRAIL + 1):k + 1].min()))
    return dict(kapandi=False, stop=float(s), son=float(c[-1]), armed=armed)


def gunluk(frames: dict, sinyaller: list[dict], bugun: pd.Timestamp) -> str:
    """sinyaller: dict(sym, kaynak ('Giriş'/'Base'), tarih 'YYYY-AA-GG', kapanis, dip). Mesaj metni döner."""
    p = yukle()
    if not p.get("baslangic"):
        p["baslangic"] = f"{bugun:%Y-%m-%d}"
    olay = []
    # 1) açık işlemleri güncelle
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
    # 2) yeni sinyaller
    ozs = p["nakit"] + sum(a["lot"] * a.get("son", a["giris"]) for a in p["acik"])
    for s in sinyaller:
        kayit = dict(sym=s["sym"], kaynak=s["kaynak"], tarih=s["tarih"])
        if pd.Timestamp(s["tarih"]) != bugun:
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
    kaydet(p)
    # 3) özet
    deger = sum(a["lot"] * a.get("son", a["giris"]) for a in p["acik"])
    ozs = p["nakit"] + deger
    out = [f"💼 Sanal portföy · {bugun:%d.%m.%Y} · özsermaye {ozs:,.0f} TL ({(ozs / BASLANGIC - 1) * 100:+.2f}%) · "
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

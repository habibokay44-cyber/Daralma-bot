#!/usr/bin/env python3
"""BIST tarayıcı: Fiyat Daralması / Giriş sinyallerini bulur ve Telegram'a gönderir.

Örnekler:
  python scan.py --dry-run                 # tüm BIST, Telegram'a göndermeden ekrana yaz
  python scan.py                           # tara ve Telegram'a gönder
  python scan.py --ticker THYAO --history  # tek hisse, tüm geçmiş sinyaller (TradingView ile karşılaştırmak için)
  python scan.py --csv thyao.csv --history # TradingView'dan indirilen CSV ile
  python scan.py --dry-run --backtest      # tüm BIST için geçmiş işlem istatistiği
  python scan.py --source tv               # veriyi zorla TradingView'dan al (yahoo / tv / auto)
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import random
import re
import sys
import time
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import requests

from fd_core import Params, run, summarize

HERE = Path(__file__).resolve().parent
STATE_FILE = HERE / "state" / "sent.json"
KAYIT_FILE = HERE / "state" / "etiket_kayit.csv"  # kör ileri test: her yeni etiket buraya yazılır, işareti sen doldurursun
FALLBACK_FILE = HERE / "tickers_fallback.txt"
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"}
TR_TZ = timezone(timedelta(hours=3))

_stat = {"ok": 0, "fail": 0}
_codes: dict = {}
DEADLINE = time.time() + 12 * 60
HOSTS = ["query1.finance.yahoo.com", "query2.finance.yahoo.com"]


# ------------------------------------------------------------------ hisse listesi
def get_tickers() -> list[str]:
    """TradingView tarayıcı uç noktasından BIST hisselerini al; olmazsa yedek listeyi kullan."""
    try:
        body = {
            "filter": [
                {"left": "type", "operation": "equal", "right": "stock"},
                {"left": "exchange", "operation": "equal", "right": "BIST"},
            ],
            "options": {"lang": "tr"},
            "columns": ["name", "type", "subtype"],
            "sort": {"sortBy": "name", "sortOrder": "asc"},
            "range": [0, 1500],
        }
        r = requests.post("https://scanner.tradingview.com/turkey/scan", json=body, headers=UA, timeout=30)
        r.raise_for_status()
        out = []
        for row in r.json().get("data", []):
            name = row["d"][0]
            sub = row["d"][2] if len(row["d"]) > 2 else None
            if re.fullmatch(r"[A-Z0-9]{3,6}", name or "") and sub in (None, "common", "preferred", ""):
                out.append(name)
        out = sorted(set(out))
        if len(out) > 100:
            return out
        print(f"[uyarı] TradingView listesi kısa geldi ({len(out)}), yedek liste kullanılıyor", file=sys.stderr)
    except Exception as e:  # noqa: BLE001
        print(f"[uyarı] hisse listesi alınamadı ({e}); yedek liste kullanılıyor", file=sys.stderr)
    return [s.strip().upper() for s in FALLBACK_FILE.read_text().split() if s.strip()]


# ------------------------------------------------------------------ veri: Yahoo
def fetch_yahoo(sym: str, rng: str = "2y", retries: int = 3) -> pd.DataFrame | None:
    for k in range(retries):
        # Yahoo tamamen engelliyorsa ya da süre dolduysa boşuna bekleme
        if time.time() > DEADLINE or (_stat["ok"] == 0 and _stat["fail"] >= 40):
            break
        url = f"https://{HOSTS[k % 2]}/v8/finance/chart/{sym}.IS"
        try:
            r = requests.get(url, params={"range": rng, "interval": "1d", "includePrePost": "false"},
                             headers=UA, timeout=15)
            _codes[r.status_code] = _codes.get(r.status_code, 0) + 1
            if r.status_code == 404:
                return None
            if r.status_code in (429, 403, 999):
                time.sleep(1.5 * (k + 1) + random.random())
                continue
            r.raise_for_status()
            res = r.json()["chart"]["result"]
            if not res:
                return None
            res = res[0]
            q = res["indicators"]["quote"][0]
            idx = pd.to_datetime(res["timestamp"], unit="s", utc=True).tz_convert("Europe/Istanbul").tz_localize(None).normalize()
            df = pd.DataFrame({"Open": q["open"], "High": q["high"], "Low": q["low"],
                               "Close": q["close"], "Volume": q["volume"]}, index=idx)
            df = df.dropna(subset=["Open", "High", "Low", "Close"])
            df["Volume"] = df["Volume"].fillna(0)
            df = df[~df.index.duplicated(keep="last")]
            _stat["ok"] += 1
            return df
        except Exception:  # noqa: BLE001
            time.sleep(0.5 + k)
    _stat["fail"] += 1
    return None


# ------------------------------------------------------------------ veri: TradingView (tvdatafeed)
TEMETTU_DUZELT = True   # 09.11.2026: Pine grafiğinde ADJ (temettü ayarlaması) açık -> Python da temettü düzeltilmiş veri
                        # kullanır (MCARD 06.11: ham veride T 5.3, düzeltilmişte 4.83 = Pine). tvdatafeed varsayılanı 'splits'.


def _tv_temettu_yama() -> None:
    """tvdatafeed'in resolve_symbol isteğindeki adjustment'ı 'splits' -> 'dividends' yapar (bölünme + temettü düzeltmesi)."""
    from tvDatafeed import TvDatafeed
    if not TEMETTU_DUZELT or getattr(TvDatafeed, "_temettu_yamali", False):
        return
    asil = TvDatafeed._TvDatafeed__send_message

    def gonder(self, func, args):
        if func == "resolve_symbol" and len(args) >= 3 and isinstance(args[2], str):
            args = list(args)
            args[2] = args[2].replace('"adjustment":"splits"', '"adjustment":"dividends"')
        return asil(self, func, args)

    TvDatafeed._TvDatafeed__send_message = gonder
    TvDatafeed._temettu_yamali = True


def _tv_df(tv, sym: str, n_bars: int) -> pd.DataFrame | None:
    from tvDatafeed import Interval
    _tv_temettu_yama()
    df = tv.get_hist(symbol=sym, exchange="BIST", interval=Interval.in_daily, n_bars=n_bars)
    if df is None or len(df) == 0:
        return None
    df = df.rename(columns=str.capitalize)
    df = df[["Open", "High", "Low", "Close", "Volume"]].astype(float)
    df.index = (pd.to_datetime(df.index) + pd.Timedelta(hours=3)).normalize()
    df = df[~df.index.duplicated(keep="last")].dropna(subset=["Open", "High", "Low", "Close"])
    return df


def fetch_tv_all(tickers: list[str], n_bars: int = 500, budget: int = 22 * 60, min_bars: int = 120) -> dict[str, pd.DataFrame]:
    try:
        from tvDatafeed import TvDatafeed
    except Exception as e:  # noqa: BLE001
        raise SystemExit(f"tvdatafeed kurulu değil ({e}). Workflow'da 'TradingView veri kütüphanesi' adımı olmalı.")
    _tv_temettu_yama()
    t0 = time.time()
    tv = TvDatafeed()
    out: dict[str, pd.DataFrame] = {}
    fail = 0
    for i, s in enumerate(tickers):
        if time.time() - t0 > budget:
            print("[uyarı] TradingView süre sınırı doldu, eldeki veriyle devam ediliyor", file=sys.stderr)
            break
        df = None
        for _ in range(2):
            try:
                df = _tv_df(tv, s, n_bars)
                if df is not None:
                    break
            except Exception as e:  # noqa: BLE001
                print(f"[uyarı] {s}: {e}", file=sys.stderr)
                time.sleep(1)
                try:
                    tv = TvDatafeed()
                except Exception:  # noqa: BLE001
                    pass
        if df is not None and len(df) >= min_bars:
            out[s] = df
        else:
            fail += 1
        if (i + 1) % 50 == 0:
            print(f"  TradingView: {i + 1}/{len(tickers)} hisse, {len(out)} başarılı ({time.time() - t0:.0f} sn)")
        if not out and fail >= 15:
            raise SystemExit("TradingView'dan da veri alınamadı (ilk 15 hisse başarısız). Sinyal gönderilmedi.")
    return out


MIN_BARS_YENI = 30   # 05.11.2026: yeni arzlar Base v0 için 30 mumdan itibaren taranır (ana gösterge yine 120+ ister)


def load_frames(tickers: list[str], args) -> dict[str, pd.DataFrame]:
    src = args.source
    if src == "auto" and TEMETTU_DUZELT:
        src = "tv"   # Yahoo ham (temettü düzeltmesiz) fiyat verir; Pine ile aynı olması için TradingView
        print("Veri kaynağı: tv (temettü düzeltilmiş, Pine ADJ ile aynı)")
    if src == "auto":
        probe = [s for s in ("THYAO", "GARAN", "ASELS") if s in tickers] or tickers[:3]
        ok = any(fetch_yahoo(s, args.range, retries=1) is not None for s in probe)
        src = "yahoo" if ok else "tv"
        print(f"Veri kaynağı: {src} (Yahoo sınaması {'başarılı' if ok else 'başarısız'})")
    frames: dict[str, pd.DataFrame] = {}
    if src == "yahoo":
        with ThreadPoolExecutor(max_workers=args.workers) as ex:
            futs = {ex.submit(fetch_yahoo, s, args.range): s for s in tickers}
            for f in as_completed(futs):
                df = f.result()
                if df is not None and len(df) >= MIN_BARS_YENI:
                    frames[futs[f]] = df
        print(f"Yahoo HTTP durumları: {_codes}")
    else:
        frames = fetch_tv_all(tickers, min_bars=MIN_BARS_YENI)
    return frames


def read_csv(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    cols = {c.lower(): c for c in df.columns}
    tcol = cols.get("time") or cols.get("date") or cols.get("tarih")
    if tcol is None:
        raise SystemExit("CSV'de time/date sütunu yok")
    t = df[tcol]
    if np.issubdtype(t.dtype, np.number):
        idx = pd.to_datetime(t, unit="s", utc=True).dt.tz_convert("Europe/Istanbul").dt.tz_localize(None).dt.normalize()
    else:
        idx = pd.to_datetime(t, utc=True, errors="coerce").dt.tz_convert("Europe/Istanbul").dt.tz_localize(None).dt.normalize()
    out = pd.DataFrame({
        "Open": df[cols["open"]].astype(float), "High": df[cols["high"]].astype(float),
        "Low": df[cols["low"]].astype(float), "Close": df[cols["close"]].astype(float),
        "Volume": df[cols["volume"]].astype(float) if "volume" in cols else 0.0,
    })
    out.index = pd.DatetimeIndex(idx)
    return out.dropna(subset=["Open", "High", "Low", "Close"])


# ------------------------------------------------------------------ analiz
def analyze(sym: str, df: pd.DataFrame, days: int, history: bool) -> dict:
    P = Params()
    res = run(df, P)
    n = res.n
    ev = []
    for e in res.events:
        if history:
            if e["type"] != "iptal":          # geçmiş listesinde iptal olanlar etikette işaretlenir
                ev.append(e)
            continue
        if e["t"] < n - days:
            continue
        # iptal olan daralma sinyali bildirilmez (grafikte etiketi silinir); iptal haberi ayrı gider
        if e["type"] == "setup" and e.get("cancelled"):
            continue
        ev.append(e)
    return dict(sym=sym, n=n, last_date=df.index[-1], last_close=float(df["Close"].iloc[-1]),
                events=ev, trades=res.trades, open_trade=res.open_trade)


def analyze_args(a):
    return analyze(*a)


# ------------------------------------------------------------------ mesajlar
def link(sym: str) -> str:
    return f"https://tr.tradingview.com/chart/?symbol=BIST%3A{sym}"


def fmt_event(sym: str, e: dict) -> str:
    d = e["date"].strftime("%d.%m.%Y")
    if e["type"] == "setup":
        dist = (e["line"] / e["close"] - 1) * 100
        tag = " | güçlü" if e["strong"] else ""
        tag += " | kısa" if e["short"] else ""
        tag += " | İPTAL EDİLDİ" if e.get("cancelled") else ""
        return (f"🟠 FİYAT DARALMASI · {sym} · {d}\n"
                f"Kapanış {e['close']:.2f} | {e['mode']} direnç {e['line']:.2f} (+%{dist:.1f}){tag}\n"
                f"Stop bölgesi (sıkışma dibi) {e['stop']:.2f}\n"
                f"r{e['r']:.2f} k{e['k']:.2f} m{e['m']:.2f} dt{e['dt']} v{e['v']:.1f} j{e['j']:.2f}\n{link(sym)}")
    if e["type"] == "iptal":
        sd = e["setup_date"].strftime("%d.%m.%Y") if e.get("setup_date") is not None else "?"
        return (f"❌ İPTAL · {sym} · {d}\n"
                f"{sd} tarihli daralma sinyali geçersiz oldu (sert düşüş / stop). Kapanış {e['close']:.2f}\n{link(sym)}")
    sd = e["setup_date"].strftime("%d.%m.%Y") if e.get("setup_date") is not None else "?"
    return (f"🟢 GİRİŞ · {sym} · {d}\n"
            f"Giriş {e['close']:.2f} | SL {e['sl']:.2f} (-%{e['riskPct']:.1f}) | "
            f"TP {e['tp']:.2f} (+%{e['tpPct']:.1f}, {e['tpR']:.1f}R{' SMC' if e['smc'] else ''})\n"
            f"Daralma sinyali: {sd}\n{link(sym)}")


def load_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text())
    except Exception:  # noqa: BLE001
        return {}


def save_state(st: dict) -> None:
    cutoff = (datetime.now() - timedelta(days=120)).strftime("%Y-%m-%d")
    st = {k: v for k, v in st.items() if v >= cutoff}
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(st, indent=0, sort_keys=True))


def telegram_send(text: str) -> None:
    token = os.environ.get("TELEGRAM_TOKEN")
    chat = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat:
        raise SystemExit("TELEGRAM_TOKEN ve TELEGRAM_CHAT_ID ortam değişkenleri gerekli")
    chunks, cur = [], ""
    for block in text.split("\n\n"):
        if len(cur) + len(block) + 2 > 3800:
            chunks.append(cur)
            cur = ""
        cur += ("\n\n" if cur else "") + block
    if cur:
        chunks.append(cur)
    for ch in chunks:
        r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                          json={"chat_id": chat, "text": ch, "disable_web_page_preview": True}, timeout=30)
        if not r.ok:
            raise SystemExit(f"Telegram hatası: {r.status_code} {r.text}")
        time.sleep(0.5)


def print_stats(trades: list[dict], title: str) -> None:
    s = summarize(trades)
    print(f"\n=== {title} ===")
    if s["n"] == 0:
        print("işlem yok")
        return
    pf = "∞" if s["profitFactor"] == float("inf") else f"{s['profitFactor']:.2f}"
    print(f"İşlem {s['n']} | Kazanma %{s['winRate']:.0f} (başa baş %{s['breakEven']:.0f}) | "
          f"TP/STOP/SÜRE {s['tp']}/{s['sl']}/{s['time']}")
    print(f"Ort. getiri %{s['avgRet']:.2f} | Ort. R {s['avgR']:.2f} | Profit factor {pf} | Ort. hedef {s['avgPlanR']:.2f}R")


# ------------------------------------------------------------------ ana
def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=2, help="son kaç mumdaki sinyaller bildirilsin (varsayılan 2)")
    ap.add_argument("--ticker", help="tek hisse (örn. THYAO)")
    ap.add_argument("--csv", help="TradingView CSV dosyası")
    ap.add_argument("--history", action="store_true", help="tüm geçmiş sinyalleri yaz (Telegram'a göndermez)")
    ap.add_argument("--dry-run", action="store_true", help="Telegram'a gönderme, ekrana yaz")
    ap.add_argument("--backtest", action="store_true", help="tüm hisselerin geçmiş işlem istatistiğini yaz")
    ap.add_argument("--limit", type=int, default=0, help="test için ilk N hisse")
    ap.add_argument("--workers", type=int, default=5, help="paralel veri indirme sayısı (Yahoo)")
    ap.add_argument("--source", default="auto", choices=["auto", "yahoo", "tv"], help="veri kaynağı")
    ap.add_argument("--min-turnover", type=float, default=0.0, help="son 20 mum ort. günlük işlem hacmi (TL) alt sınırı")
    ap.add_argument("--max-stale-days", type=int, default=6, help="son mum bundan eskiyse hisseyi atla")
    ap.add_argument("--heartbeat", action="store_true", help="sinyal olmasa da özet mesajı gönder")
    ap.add_argument("--range", default="2y", help="Yahoo veri aralığı (varsayılan 2y)")
    args = ap.parse_args()

    # ---- tek hisse / csv ----
    if args.csv:
        df = read_csv(args.csv)
        r = analyze(args.ticker or Path(args.csv).stem.upper(), df, args.days, True)
        for e in r["events"]:
            print(fmt_event(r["sym"], e), "\n")
        print_stats(r["trades"], f"{r['sym']} geçmiş test")
        return
    if args.ticker:
        sym = args.ticker.upper()
        df = None
        if args.source in ("auto", "yahoo"):
            df = fetch_yahoo(sym, args.range)
        if df is None and args.source in ("auto", "tv"):
            df = fetch_tv_all([sym]).get(sym)
        if df is None:
            raise SystemExit("veri alınamadı")
        r = analyze(sym, df, args.days, args.history)
        for e in r["events"]:
            print(fmt_event(r["sym"], e), "\n")
        print_stats(r["trades"], f"{r['sym']} geçmiş test")
        return

    # ---- tüm BIST ----
    t0 = time.time()
    tickers = get_tickers()
    if args.limit:
        tickers = tickers[: args.limit]
    print(f"{len(tickers)} hisse taranacak")

    frames = load_frames(tickers, args)
    print(f"{len(frames)} hisse için veri alındı ({time.time() - t0:.0f} sn)")
    if len(frames) < max(5, len(tickers) // 4):
        raise SystemExit("Çok az hisse için veri alınabildi. Sinyal gönderilmedi.")

    today = pd.Timestamp(datetime.now(TR_TZ).date())
    jobs = []
    taze = {}
    for s, df in frames.items():
        if (today - df.index[-1]).days > args.max_stale_days:
            continue
        if args.min_turnover > 0 and (df["Close"] * df["Volume"]).tail(20).mean() < args.min_turnover:
            continue
        taze[s] = df
        if len(df) >= 120:   # ana gösterge 120+ mum ister; daha kısa (yeni arz) hisseler sadece Base v0'da
            jobs.append((s, df, args.days, False))

    results = []
    with ProcessPoolExecutor(max_workers=os.cpu_count() or 2) as ex:
        for r in ex.map(analyze_args, jobs, chunksize=4):
            results.append(r)
    print(f"analiz bitti ({time.time() - t0:.0f} sn)")

    if args.backtest:
        allt = [t for r in results for t in r["trades"]]
        print_stats(allt, f"Tüm BIST geçmiş test ({len(results)} hisse)")
        by = sorted(((r["sym"], summarize(r["trades"])) for r in results if r["trades"]), key=lambda x: -x[1]["n"])
        print("\nEn çok işlem olan hisseler:")
        for s, st in by[:15]:
            print(f"  {s:7s} işlem {st['n']:3d}  kazanma %{st['winRate']:.0f}  ortR {st['avgR']:+.2f}")
        return

    # ---- sinyaller ----
    state = load_state()
    m_giris, m_setup, m_iptal = [], [], []
    yeni_kayit: list[dict] = []
    girisler: list[tuple] = []
    grafikler: list = []
    port_sig: list[dict] = []   # sanal portföy (portfoy.py) için yeni Giriş ve Base sinyalleri
    for r in results:
        sym = r["sym"]
        for e in r["events"]:
            dstr = e["date"].strftime("%Y-%m-%d")
            if e["type"] == "iptal":
                # sadece daha önce bildirdiğimiz bir daralma sinyali iptal olduysa haber ver
                sd = e.get("setup_date")
                sent_before = sd is not None and f"{sym}|setup|{sd:%Y-%m-%d}" in state
                key = f"{sym}|iptal|{dstr}"
                if sent_before and key not in state:
                    state[key] = dstr
                    m_iptal.append(fmt_event(sym, e))
                continue
            key = f"{sym}|{e['type']}|{dstr}"
            if key in state:
                continue
            state[key] = dstr
            (m_giris if e["type"] == "giris" else m_setup).append(fmt_event(sym, e))
            if e["type"] == "giris" and e.get("setup_date") is not None:
                girisler.append((sym, f"{e['setup_date']:%Y-%m-%d}", dstr))
            if e["type"] == "giris":
                port_sig.append(dict(sym=sym, kaynak="Giriş", tarih=dstr, kapanis=e["close"], dip=e["sl"]))
            if e["type"] == "setup":
                grafikler.append((sym, e))
                row = dict(bildirim_tarihi=datetime.now(TR_TZ).strftime("%Y-%m-%d"), hisse=sym, etiket_tarihi=dstr,
                           mod=e["mode"], kapanis=f"{e['close']:.2f}", direnc=f"{e['line']:.2f}",
                           iptal="iptal" if e.get("cancelled") else "")
                try:
                    from kayit import bayraklar
                    row.update(bayraklar(frames[sym], e))
                except Exception as ex:  # noqa: BLE001
                    print(f"[uyarı] {sym} v56 bayrakları hesaplanamadı: {ex}", file=sys.stderr)
                yeni_kayit.append(row)

    # ---- Base v0 (gölge/deneme, 05.11.2026 kör testi geçti: %62 alırdım) ----
    m_base, base_graf = [], []
    try:
        from base_v0 import sinyaller as base_sinyaller
        from base_v2 import sinyaller as v2_sinyaller
        from base_v3 import sinyaller as v3_sinyaller
        for s_, df_ in taze.items():
            for e_ in base_sinyaller(df_):
                if e_["t"] < len(df_) - args.days:
                    continue
                dstr = f"{e_['date']:%Y-%m-%d}"
                key = f"{s_}|basev0|{dstr}"
                if key in state:
                    continue
                state[key] = dstr
                e_ = {**e_, "mode": "Base"}
                yeni_arz = " · 🆕 yeni arz" if len(df_) < 120 else ""
                m_base.append(f"🧱 {s_} · {e_['date']:%d.%m.%Y} · kapanış {e_['close']:.2f} · base üstü {e_['line']:.2f}"
                              f" · base dibi {e_['stop']:.2f} (-%{(1 - e_['stop'] / e_['close']) * 100:.1f}){yeni_arz}")
                base_graf.append((s_, e_))
                port_sig.append(dict(sym=s_, kaynak="Base", tarih=dstr, kapanis=e_["close"],
                                     dip=float(df_["Low"].iloc[e_["t"]])))
                golge = {}
                for ad_, fn_ in (("b_v2", v2_sinyaller), ("b_v3", v3_sinyaller)):
                    try:
                        ofs = max(0, len(df_) - 60)   # son 60 mum yeterli; t'yi tam veriye göre kaydır
                        golge[ad_] = "1" if any(abs(x["t"] + ofs - e_["t"]) <= 2 for x in fn_(df_.iloc[ofs:])) else "0"
                    except Exception:  # noqa: BLE001
                        golge[ad_] = ""
                yeni_kayit.append(dict(bildirim_tarihi=datetime.now(TR_TZ).strftime("%Y-%m-%d"), hisse=s_, etiket_tarihi=dstr,
                                       mod="Base", kapanis=f"{e_['close']:.2f}", direnc=f"{e_['line']:.2f}", giris_tarihi=dstr,
                                       **golge))
    except Exception as ex:  # noqa: BLE001
        print(f"[uyarı] Base v0 taranamadı: {ex}", file=sys.stderr)

    last_dates = pd.Series([r["last_date"] for r in results])
    ref = last_dates.mode().iloc[0] if len(last_dates) else today
    head = (f"📊 BIST taraması · veri tarihi {ref:%d.%m.%Y} · {len(results)} hisse · "
            f"{len(m_setup)} daralma · {len(m_giris)} giriş · {len(m_iptal)} iptal")
    try:   # 10.11.2026: piyasa genişliği satırı (bilgi; hiçbir sinyali etkilemez)
        import piyasa
        head += "\n" + piyasa.satir(piyasa.genislik(frames))
    except Exception as ex:  # noqa: BLE001
        print(f"[uyarı] piyasa satırı: {ex}", file=sys.stderr)
    body = m_giris + m_setup + m_iptal
    if m_base:
        head += f" · {len(m_base)} base"
        body = body + ["🧱 Base kırılımı (deneme, ileri testte):\n" + "\n".join(m_base)]
    print(head)
    for m in body:
        print("\n" + m)

    if args.dry_run:
        print("\n(dry-run: Telegram'a gönderilmedi, durum dosyası güncellenmedi)")
        return
    if body or args.heartbeat:
        telegram_send(head + ("\n\n" + "\n\n".join(body) if body else "\n\nYeni sinyal yok."))
    if grafikler or base_graf:
        try:
            from grafik import gonder_butonlu
            esle = gonder_butonlu([(s_, frames[s_], e_) for s_, e_ in grafikler + base_graf if s_ in frames])
            ep = HERE / "state" / "tg_mesaj.json"
            try:
                eski = json.loads(ep.read_text())
            except Exception:  # noqa: BLE001
                eski = {}
            eski.update(esle)
            ep.parent.mkdir(parents=True, exist_ok=True)
            ep.write_text(json.dumps(dict(list(eski.items())[-500:]), indent=0))
            print(f"{len(esle)} butonlu etiket grafiği gönderildi")
        except Exception as ex:  # noqa: BLE001
            print(f"[uyarı] etiket grafikleri gönderilemedi: {ex}", file=sys.stderr)
    try:   # sanal portföy: açık işlemleri güncelle, bugünün sinyallerini al, özeti gönder
        import portfoy
        telegram_send(portfoy.gunluk(frames, port_sig, ref))
        try:   # 09.11.2026: gölge portföy, sadece ✅ onayladığın sinyaller
            telegram_send(portfoy.gunluk_onayli(frames, port_sig, ref))
        except Exception as ex:  # noqa: BLE001
            print(f"[uyarı] onaylı portföy güncellenemedi: {ex}", file=sys.stderr)
    except Exception as ex:  # noqa: BLE001
        print(f"[uyarı] sanal portföy güncellenemedi: {ex}", file=sys.stderr)
    import kayit
    if yeni_kayit or girisler or any(not (r.get("e1") and r.get("e50")) and r.get("mod") not in ("Base", "BaseV0") for r in kayit.load()):
        rows = kayit.load()
        var = {kayit.key(r["hisse"], r["etiket_tarihi"]) for r in rows}
        for r_ in yeni_kayit:
            if kayit.key(r_["hisse"], r_["etiket_tarihi"]) not in var:
                rows.append({**{c: "" for c in kayit.COLS}, **r_})
        idx = {kayit.key(r["hisse"], r["etiket_tarihi"]): r for r in rows}
        # bayrağı boş kalmış son 60 günün etiketleri için gölge bayraklarını sonradan hesapla
        sinir = (today - pd.Timedelta(days=60)).strftime("%Y-%m-%d")
        for r_ in rows:
            if ((r_.get("e1") and r_.get("e50")) or r_["etiket_tarihi"] < sinir or r_["hisse"] not in frames
                    or r_.get("mod") in ("Base", "BaseV0") or len(frames[r_["hisse"]]) < 120):
                continue
            try:
                from kayit import bayraklar
                df_ = frames[r_["hisse"]]
                ev_ = [x for x in run(df_, Params()).events if x["type"] == "setup" and f"{x['date']:%Y-%m-%d}" == r_["etiket_tarihi"]]
                if ev_:
                    r_.update(bayraklar(df_, ev_[0]))
            except Exception as ex:  # noqa: BLE001
                print(f"[uyarı] {r_['hisse']} bayrak sonradan hesaplanamadı: {ex}", file=sys.stderr)
        for s_, sd_, gd_ in girisler:
            r_ = idx.get(kayit.key(s_, sd_))
            if r_ is not None and not r_.get("giris_tarihi"):
                r_["giris_tarihi"] = gd_
        kayit.save(rows)
    save_state(state)


if __name__ == "__main__":
    main()

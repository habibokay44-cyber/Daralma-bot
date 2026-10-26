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
def _tv_df(tv, sym: str, n_bars: int) -> pd.DataFrame | None:
    from tvDatafeed import Interval
    df = tv.get_hist(symbol=sym, exchange="BIST", interval=Interval.in_daily, n_bars=n_bars)
    if df is None or len(df) == 0:
        return None
    df = df.rename(columns=str.capitalize)
    df = df[["Open", "High", "Low", "Close", "Volume"]].astype(float)
    df.index = (pd.to_datetime(df.index) + pd.Timedelta(hours=3)).normalize()
    df = df[~df.index.duplicated(keep="last")].dropna(subset=["Open", "High", "Low", "Close"])
    return df


def fetch_tv_all(tickers: list[str], n_bars: int = 500, budget: int = 22 * 60) -> dict[str, pd.DataFrame]:
    try:
        from tvDatafeed import TvDatafeed
    except Exception as e:  # noqa: BLE001
        raise SystemExit(f"tvdatafeed kurulu değil ({e}). Workflow'da 'TradingView veri kütüphanesi' adımı olmalı.")
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
        if df is not None and len(df) >= 120:
            out[s] = df
        else:
            fail += 1
        if (i + 1) % 50 == 0:
            print(f"  TradingView: {i + 1}/{len(tickers)} hisse, {len(out)} başarılı ({time.time() - t0:.0f} sn)")
        if not out and fail >= 15:
            raise SystemExit("TradingView'dan da veri alınamadı (ilk 15 hisse başarısız). Sinyal gönderilmedi.")
    return out


def load_frames(tickers: list[str], args) -> dict[str, pd.DataFrame]:
    src = args.source
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
                if df is not None and len(df) >= 120:
                    frames[futs[f]] = df
        print(f"Yahoo HTTP durumları: {_codes}")
    else:
        frames = fetch_tv_all(tickers)
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
    ev = [e for e in res.events if e["type"] in ("setup", "giris")] if history else \
         [e for e in res.events if e["type"] in ("setup", "giris") and e["t"] >= n - days]
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
        return (f"🟠 FİYAT DARALMASI · {sym} · {d}\n"
                f"Kapanış {e['close']:.2f} | {e['mode']} direnç {e['line']:.2f} (+%{dist:.1f}){tag}\n"
                f"Stop bölgesi (sıkışma dibi) {e['stop']:.2f}\n{link(sym)}")
    return (f"🟢 GİRİŞ · {sym} · {d}\n"
            f"Giriş {e['close']:.2f} | SL {e['sl']:.2f} (-%{e['riskPct']:.1f}) | "
            f"TP {e['tp']:.2f} (+%{e['tpPct']:.1f}, {e['tpR']:.1f}R{' SMC' if e['smc'] else ''})\n{link(sym)}")


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
    for s, df in frames.items():
        if (today - df.index[-1]).days > args.max_stale_days:
            continue
        if args.min_turnover > 0 and (df["Close"] * df["Volume"]).tail(20).mean() < args.min_turnover:
            continue
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
    new_msgs_giris, new_msgs_setup = [], []
    n_setup = n_giris = 0
    for r in results:
        for e in r["events"]:
            key = f"{r['sym']}|{e['type']}|{e['date']:%Y-%m-%d}"
            if key in state:
                continue
            state[key] = e["date"].strftime("%Y-%m-%d")
            if e["type"] == "giris":
                n_giris += 1
                new_msgs_giris.append(fmt_event(r["sym"], e))
            else:
                n_setup += 1
                new_msgs_setup.append(fmt_event(r["sym"], e))

    last_dates = pd.Series([r["last_date"] for r in results])
    ref = last_dates.mode().iloc[0] if len(last_dates) else today
    head = f"📊 BIST taraması · veri tarihi {ref:%d.%m.%Y} · {len(results)} hisse · {n_setup} daralma · {n_giris} giriş"
    body = new_msgs_giris + new_msgs_setup
    print(head)
    for m in body:
        print("\n" + m)

    if args.dry_run:
        print("\n(dry-run: Telegram'a gönderilmedi, durum dosyası güncellenmedi)")
        return
    if body or args.heartbeat:
        telegram_send(head + ("\n\n" + "\n\n".join(body) if body else "\n\nYeni sinyal yok."))
    save_state(state)


if __name__ == "__main__":
    main()

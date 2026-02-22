#!/usr/bin/env python3
"""
Market Dashboard — API Server
Deploy to Railway: https://railway.app
"""

from flask import Flask, jsonify, request
from flask_cors import CORS
import yfinance as yf
from datetime import datetime
import time
import os
import hashlib

app = Flask(__name__)
CORS(app, origins="*")

# ── Auth ──────────────────────────────────────────────────────
API_KEY = os.environ.get("DASHBOARD_API_KEY", "change-me-in-railway")

def check_auth():
    key = request.headers.get("X-API-Key") or request.args.get("key")
    return key == API_KEY

# ── Cache ─────────────────────────────────────────────────────
_cache = {}
_cache_ts = {}
CACHE_TTL = 300  # 5 minutes

def cached(key, fn):
    now = time.time()
    if key in _cache and now - _cache_ts.get(key, 0) < CACHE_TTL:
        return _cache[key]
    result = fn()
    _cache[key] = result
    _cache_ts[key] = now
    return result

# ── Tickers ───────────────────────────────────────────────────
INDEX_TICKERS = {
    "SPY": "S&P 500", "RSP": "S&P 500 EQ WT",
    "QQQ": "NASDAQ 100", "QQQE": "NASDAQ 100 EQ WT",
    "IWM": "RUSSELL 2000", "^VIX": "VOLATILITY", "BTC-USD": "BITCOIN",
}
SECTOR_TICKERS = {
    "RSPG": "Energy", "RSPN": "Industrials", "RSPU": "Utilities",
    "RSPH": "Health Care", "RSPR": "Real Estate", "RSPM": "Materials",
    "RSPS": "Cons Stpl", "RSPC": "Comm Svcs", "RSPD": "Cons Disc",
    "RSPT": "Technology", "RSPF": "Financials",
}
SCREENERS = {
    "ema_watch":   ["WSC","ALH","AESI","NVT","AR","VIK","NCLH","LRCX","ASO","VFC","FFIV","GAP","CAVA","STNE","BWXT","CAKE","REZI","VSCO","FLEX","BVN","WERN","APH","CALX","MGM","RUN","YPF","SMCI"],
    "healthy":     ["CIEN","LITE","AAOI","SNDK","WDC","ACMR","LRCX","TER","AMAT","GORO","TRX","IAG","IAUX","AU","BVN","SSRM","ALM","BORR","RIG","VAL","ASX","COHR","ATI","NESR","CSTM","CENX","VSAT","GLW","FSLY"],
    "momentum97":  ["CWBHF","NCI","HYMC","BATL","ATOM","CVSI","NAMM","PL","HLF","LPTH","ONDS","FSLY","ZIM","UMAC","CLMT","CGNX","TPH","KTOS","WORX","IRDM","RIME","RELY"],
    "gainers4":    ["RELY","HLF","COLD","OMC","MPT","AG","SSRM","EQX","SMCI","AAOI","LITE","PWR","BAK","XP","LINE","CDE","NGD","HLX","NG","PAAS","IAG","ARCO","SA","BTE","AGI","RIOT","CENX","CALX","DNN","NEXT"],
    "vol_gainers": ["RELY","HLF","COLD","OMC","MPT","SSRM","OII","ETSY","KRMN","KTOS","FUN","XP","XPRO","ARCO","CENX","FLR","EBAY","DASH","HLIT","IHS","SM","AKAM"],
    "eps_growth":  ["CIEN","LITE","MU","SNDK","WDC","TER","APH","VRT","AMSC","ECO","FTAI","MOD","FN","UI","CRDO","STNG","EQT","AS","BKV","CALX","CECO","SII","WT","NET"],
}

# ── Helpers ───────────────────────────────────────────────────
def calc_ema(series, period):
    return series.ewm(span=period, adjust=False).mean()

def batch_download(tickers, period="5d"):
    try:
        data = yf.download(list(tickers), period=period, auto_adjust=True, progress=False)
        return data["Close"] if "Close" in data else data
    except Exception:
        return None

# ── Middleware ────────────────────────────────────────────────
@app.before_request
def auth_middleware():
    if request.path in ["/", "/health"]:
        return
    if not check_auth():
        return jsonify({"error": "Unauthorized"}), 401

# ── Routes ────────────────────────────────────────────────────
@app.route("/")
def root():
    return jsonify({"status": "ok", "service": "Market Dashboard API"})

@app.route("/health")
def health():
    return jsonify({"status": "ok", "time": datetime.utcnow().isoformat()})

@app.route("/api/indices")
def api_indices():
    def fetch():
        tickers = list(INDEX_TICKERS.keys())
        data = batch_download(tickers)
        result = {}
        if data is None:
            return result
        for sym, name in INDEX_TICKERS.items():
            try:
                series = data[sym].dropna() if sym in data.columns else data.dropna()
                if len(series) < 2:
                    continue
                today = float(series.iloc[-1])
                prev  = float(series.iloc[-2])
                result[sym] = {
                    "name": name,
                    "price": round(today, 2),
                    "change_pct": round((today - prev) / prev * 100, 2),
                }
            except Exception:
                pass
        return result
    return jsonify(cached("indices", fetch))

@app.route("/api/performance")
def api_performance():
    def fetch():
        try:
            data = yf.download("SPY", period="2y", auto_adjust=True, progress=False)["Close"]
            price = float(data.iloc[-1])
            now   = datetime.now()
            ytd   = data[data.index.year == now.year]
            return {
                "ytd":  round((price / float(ytd.iloc[0]) - 1) * 100, 2) if len(ytd) else None,
                "1w":   round((price / float(data.iloc[-6])  - 1) * 100, 2) if len(data) > 5  else None,
                "1m":   round((price / float(data.iloc[-22]) - 1) * 100, 2) if len(data) > 21 else None,
                "1y":   round((price / float(data.iloc[-252])- 1) * 100, 2) if len(data) > 251 else None,
                "52wh": round((price / float(data.tail(252).max()) - 1) * 100, 2),
            }
        except Exception as e:
            return {"error": str(e)}
    return jsonify(cached("performance", fetch))

@app.route("/api/trend_status")
def api_trend_status():
    def fetch():
        result = {}
        for ticker in ["SPY", "RSP", "QQQ", "QQQE"]:
            try:
                data = yf.download(ticker, period="1y", auto_adjust=True, progress=False)["Close"]
                c = data.dropna()
                if len(c) < 60:
                    continue
                price  = float(c.iloc[-1])
                e9     = float(calc_ema(c, 9).iloc[-1])
                e21    = float(calc_ema(c, 21).iloc[-1])
                e50    = float(calc_ema(c, 50).iloc[-1])
                e200   = float(calc_ema(c, 200).iloc[-1])
                h52    = float(c.tail(252).max())
                e21_s  = calc_ema(c, 21)
                three  = all(float(c.iloc[-i]) > float(e21_s.iloc[-i]) for i in range(1, 4))
                result[ticker] = {
                    "9ema":       round((price-e9)  /e9  *100, 2),
                    "21ema_high": round((price-e21) /e21 *100, 2),
                    "21ema":      round((price-e21) /e21 *100, 2),
                    "21ema_low":  round((price-e21) /e21 *100, 2),
                    "3d_21ema":   three,
                    "50ema":      round((price-e50) /e50 *100, 2),
                    "200ema":     round((price-e200)/e200*100, 2),
                    "52w_high":   round((price-h52) /h52 *100, 2),
                }
            except Exception:
                pass
        return result
    return jsonify(cached("trend_status", fetch))

@app.route("/api/power_trend")
def api_power_trend():
    def fetch():
        try:
            c = yf.download("QQQ", period="1y", auto_adjust=True, progress=False)["Close"].dropna()
            sma20  = float(c.rolling(20).mean().iloc[-1])
            sma50  = float(c.rolling(50).mean().iloc[-1])
            sma200 = float(c.rolling(200).mean().iloc[-1])
            avg3   = float(c.tail(3).mean())
            return {
                "3d_20sma":  avg3 > sma20,
                "3d_50sma":  avg3 > sma50,
                "3d_200sma": avg3 > sma200,
                "20_50sma":  sma20 > sma50,
                "20_200sma": sma20 > sma200,
                "50_200sma": sma50 > sma200,
            }
        except Exception as e:
            return {"error": str(e)}
    return jsonify(cached("power_trend", fetch))

@app.route("/api/sectors")
def api_sectors():
    def fetch():
        syms = list(SECTOR_TICKERS.keys()) + ["SPY"]
        try:
            data = yf.download(syms, period="6mo", auto_adjust=True, progress=False)["Close"]
            spy  = data["SPY"].dropna()
            spy_d = float((spy.iloc[-1]/spy.iloc[-2]-1)*100)
            spy_w = float((spy.iloc[-1]/spy.iloc[-6]-1)*100) if len(spy)>5 else 0
            spy_m = float((spy.iloc[-1]/spy.iloc[-22]-1)*100) if len(spy)>21 else 0
            result = {}
            for sym, name in SECTOR_TICKERS.items():
                try:
                    s = data[sym].dropna()
                    p = float(s.iloc[-1])
                    d = float((s.iloc[-1]/s.iloc[-2]-1)*100)
                    w = float((s.iloc[-1]/s.iloc[-6]-1)*100) if len(s)>5 else 0
                    m = float((s.iloc[-1]/s.iloc[-22]-1)*100) if len(s)>21 else 0
                    h52 = float(s.tail(252).max())
                    rs  = int(min(100, max(0, 50+(m-spy_m)*3)))
                    result[sym] = {
                        "name": name, "price": round(p,2),
                        "day": round(d,2), "wk": round(w,2), "mth": round(m,2),
                        "rs_day": round(d-spy_d,2), "rs_wk": round(w-spy_w,2), "rs_mth": round(m-spy_m,2),
                        "high52": round((p/h52-1)*100,2), "rs": rs,
                    }
                except Exception:
                    pass
            return dict(sorted(result.items(), key=lambda x: x[1]["rs"], reverse=True))
        except Exception as e:
            return {"error": str(e)}
    return jsonify(cached("sectors", fetch))

@app.route("/api/factors")
def api_factors():
    def fetch():
        etfs = {"IVW":"Growth","IVE":"Value","HDV":"High Dividend","OEF":"Large-Cap",
                "IJH":"Mid-Cap","IJR":"Small-Cap","MTUM":"Momentum","IPO":"IPOs"}
        try:
            syms = list(etfs.keys()) + ["SPY"]
            data = yf.download(syms, period="1mo", auto_adjust=True, progress=False)["Close"]
            spy_mth = float((data["SPY"].iloc[-1]/data["SPY"].iloc[0]-1)*100)
            result = []
            for sym, label in etfs.items():
                try:
                    s = data[sym].dropna()
                    mth = float((s.iloc[-1]/s.iloc[0]-1)*100)
                    result.append({"label": label, "val": round(mth-spy_mth, 2)})
                except Exception:
                    result.append({"label": label, "val": 0.0})
            return result
        except Exception as e:
            return []
    return jsonify(cached("factors", fetch))

@app.route("/api/yields")
def api_yields():
    def fetch():
        try:
            data = yf.download(["^TNX","^IRX"], period="5d", auto_adjust=True, progress=False)["Close"]
            return {
                "10y": round(float(data["^TNX"].dropna().iloc[-1]), 2),
                "2y":  round(float(data["^IRX"].dropna().iloc[-1]), 2),
            }
        except Exception:
            return {}
    return jsonify(cached("yields", fetch))

@app.route("/api/screener/<name>")
def api_screener(name):
    if name not in SCREENERS:
        return jsonify({"error": "unknown"}), 404
    def fetch():
        tickers = SCREENERS[name]
        try:
            data = yf.download(tickers, period="2d", auto_adjust=True, progress=False)["Close"]
            result = []
            for sym in tickers:
                try:
                    s = data[sym].dropna() if sym in data.columns else None
                    if s is None or len(s) < 2:
                        continue
                    chg = float((s.iloc[-1]/s.iloc[-2]-1)*100)
                    result.append({"ticker": sym, "change_pct": round(chg,2)})
                except Exception:
                    pass
            return sorted(result, key=lambda x: x["change_pct"], reverse=True)
        except Exception:
            return [{"ticker": t, "change_pct": 0.0} for t in tickers]
    return jsonify(cached(f"screener_{name}", fetch))

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"Starting server on port {port}")
    app.run(host="0.0.0.0", port=port)

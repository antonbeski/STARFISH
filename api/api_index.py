#!/usr/bin/env python3
"""
STARFISH — Live Markets, AI Analysis & Sector Intelligence
Combined: Stock Charts + AI Trading Analysis + Sector News Aggregator
White-dominant, black-accent theme. Custom JPG logo embedded.
"""

import os, re, time, traceback, requests, random, json, threading, base64
import numpy as np
import pandas as pd
from collections import deque
from flask import Flask, request, jsonify, render_template_string
from io import StringIO
import concurrent.futures

try:
    import yfinance as yf
except ImportError:
    yf = None

try:
    import plotly.graph_objects as go
    import plotly.offline as pyo
    from plotly.subplots import make_subplots
except ImportError:
    go = pyo = make_subplots = None

try:
    import httpx
    from bs4 import BeautifulSoup
    from urllib.parse import quote_plus
except ImportError:
    httpx = BeautifulSoup = quote_plus = None

app = Flask(__name__)

# ── Logo (embedded base64 JPG) ───────────────────────────────────────────────
_LOGO_PATH = os.path.join(os.path.dirname(__file__), "..", "starfish_logo.jpg")
_LOGO_DATA_URI = ""
if os.path.exists(_LOGO_PATH):
    with open(_LOGO_PATH, "rb") as _f:
        _LOGO_DATA_URI = "data:image/jpeg;base64," + base64.b64encode(_f.read()).decode()

# ── OpenRouter AI config ─────────────────────────────────────────────────────
OPEN_ROUTER_API_KEY = os.environ.get("OPEN_ROUTER_API_KEY", "")

AI_MODELS = [
    {"id": "deepseek/deepseek-r1",              "key": "deepseek", "label": "DeepSeek R1",   "desc": "Chain-of-thought reasoning", "color": "#1a1a1a"},
    {"id": "meta-llama/llama-3.3-70b-instruct", "key": "llama",    "label": "Llama 3.3 70B", "desc": "Fast & balanced",            "color": "#333333"},
    {"id": "qwen/qwen3-coder",                   "key": "qwen",     "label": "Qwen3 Coder",   "desc": "Quantitative focus",         "color": "#555555"},
]
RL_RPM = 20
RL_RPD = 200

_rl_lock  = threading.Lock()
_rl_state = {m["key"]: {"rpm": deque(), "rpd": deque()} for m in AI_MODELS}

def _rl_clean(key):
    now = time.time()
    while _rl_state[key]["rpm"] and now - _rl_state[key]["rpm"][0] > 60:
        _rl_state[key]["rpm"].popleft()
    while _rl_state[key]["rpd"] and now - _rl_state[key]["rpd"][0] > 86400:
        _rl_state[key]["rpd"].popleft()

def rl_check(key):
    with _rl_lock:
        _rl_clean(key)
        ru = len(_rl_state[key]["rpm"])
        du = len(_rl_state[key]["rpd"])
    return {"rpm_used": ru, "rpm_max": RL_RPM, "rpd_used": du, "rpd_max": RL_RPD,
            "available": ru < RL_RPM and du < RL_RPD}

def rl_record(key):
    with _rl_lock:
        t = time.time()
        _rl_state[key]["rpm"].append(t)
        _rl_state[key]["rpd"].append(t)

def rl_next_rpm_reset(key):
    with _rl_lock:
        if not _rl_state[key]["rpm"]: return 0
        return max(0, int(60 - (time.time() - _rl_state[key]["rpm"][0])))

# ── YouTube live news ────────────────────────────────────────────────────────
NEWS_CHANNELS = [
    {"id": "cnbctv18",  "handle": "cnbctv18",  "label": "CNBC TV18",       "lang": "EN", "region": "India",  "video_id": "1_Ih0JYmkjI"},
    {"id": "bloomberg", "handle": "Bloomberg", "label": "Bloomberg Global", "lang": "EN", "region": "Global", "video_id": "iEpJwprxDdk"},
    {"id": "yahoofi",   "handle": "yahoofi",   "label": "Yahoo Finance",   "lang": "EN", "region": "Global", "video_id": "KQp-e_XQnDE"},
]
_YT_HDR = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36",
           "Accept-Language": "en-US,en;q=0.9", "Referer": "https://www.youtube.com/"}

def fetch_live_video_id(handle):
    for ch in NEWS_CHANNELS:
        if ch["handle"] == handle and ch.get("video_id"):
            return ch["video_id"], True
    def _get(u): return requests.get(u, headers=_YT_HDR, timeout=12, allow_redirects=True)
    vid, live = None, False
    try:
        r = _get(f"https://www.youtube.com/@{handle}/live"); text = r.text
        m = re.search(r'[?&]v=([A-Za-z0-9_-]{11})', r.url) or re.search(r'"videoId"\s*:\s*"([A-Za-z0-9_-]{11})"', text)
        if m and ('"isLive":true' in text or '"liveBroadcastContent":"live"' in text):
            vid, live = m.group(1), True
    except Exception: pass
    if not live:
        try:
            r2 = _get(f"https://www.youtube.com/@{handle}/videos")
            ids = list(dict.fromkeys(re.findall(r'"videoId"\s*:\s*"([A-Za-z0-9_-]{11})"', r2.text)))
            if ids: vid, live = ids[0], False
        except Exception: pass
    return vid, live

# ── Stock config ─────────────────────────────────────────────────────────────
POPULAR_STOCKS = [("AAPL","Apple"),("GOOGL","Google"),("MSFT","Microsoft"),("TSLA","Tesla"),
                  ("AMZN","Amazon"),("NVDA","NVIDIA"),("TCS.NS","TCS"),("RELIANCE.NS","Reliance")]
PERIODS = [("1mo","1 Month"),("3mo","3 Months"),("6mo","6 Months"),("1y","1 Year"),("2y","2 Years"),("5y","5 Years")]
VALID_PERIODS = {p[0] for p in PERIODS}
INDICATORS = [("sma","SMA"),("bb","Bollinger"),("rsi","RSI"),("macd","MACD"),("vol","Volume")]

# ── Yahoo Finance scraper ────────────────────────────────────────────────────
_CACHE = {"session": None, "crumb": None, "ts": 0}
_CACHE_TTL = 1800
_PERIOD_DAYS = {"1mo":31,"3mo":92,"6mo":183,"1y":366,"2y":731,"5y":1827}
_YF_BASES = ["https://query1.finance.yahoo.com","https://query2.finance.yahoo.com"]
_UA_POOL = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.6367.207 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
]

def _new_session(ua=None):
    s = requests.Session()
    s.headers.update({"User-Agent": ua or random.choice(_UA_POOL),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9", "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive", "Upgrade-Insecure-Requests": "1",
        "Sec-CH-UA": '"Chromium";v="124","Google Chrome";v="124","Not-A.Brand";v="99"',
        "Sec-CH-UA-Mobile": "?0", "Sec-CH-UA-Platform": '"Windows"',
        "Sec-Fetch-Dest": "document", "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none", "Sec-Fetch-User": "?1",
        "Cache-Control": "max-age=0", "DNT": "1"})
    return s

def _scrape_crumb(session, ticker):
    crumb = None
    for base in _YF_BASES:
        try:
            r = session.get(f"{base}/v1/test/getcrumb", timeout=8, headers={"Referer": "https://finance.yahoo.com/"})
            if r.status_code == 200 and r.text and len(r.text) < 50 and "<" not in r.text:
                return r.text.strip()
        except Exception: pass
    for url in [f"https://finance.yahoo.com/quote/{ticker}", "https://finance.yahoo.com/"]:
        try:
            html = session.get(url, timeout=15, allow_redirects=True).text
            for pat in [r'"crumb"\s*:\s*"([^"]{5,30})"',
                        r'CrumbStore\s*:\s*\{\s*crumb\s*:\s*"([^"]{5,30})"']:
                m = re.search(pat, html)
                if m: crumb = m.group(1).replace("\\u002F", "/"); break
            if crumb: break
        except Exception: continue
    if not crumb:
        for base in _YF_BASES:
            try:
                r = session.get(f"{base}/v1/test/getcrumb", timeout=8, headers={"Referer": "https://finance.yahoo.com/"})
                if r.status_code == 200 and r.text and len(r.text) < 50 and "<" not in r.text:
                    crumb = r.text.strip(); break
            except Exception: pass
    return crumb

def _get_auth(ticker, force=False):
    now = time.time()
    if not force and _CACHE["session"] and _CACHE["crumb"] and (now - _CACHE["ts"]) < _CACHE_TTL:
        return _CACHE["session"], _CACHE["crumb"]
    s = _new_session()
    for u in ["https://fc.yahoo.com", "https://finance.yahoo.com/"]:
        try: s.get(u, timeout=8, allow_redirects=True); break
        except Exception: pass
    c = _scrape_crumb(s, ticker)
    _CACHE.update({"session": s, "crumb": c, "ts": now})
    return s, c

def _parse_v8(j):
    try:
        res = j.get("chart", {}).get("result", [None])[0]
        if not res: return None
        ts = res.get("timestamp", [])
        if not ts: return None
        q = res["indicators"]["quote"][0]
        adj = res["indicators"].get("adjclose", [{}])
        cl = (adj[0].get("adjclose") if adj else None) or q.get("close")
        df = pd.DataFrame({"Open": q.get("open"), "High": q.get("high"),
                           "Low": q.get("low"), "Close": cl, "Volume": q.get("volume")},
                          index=pd.to_datetime(ts, unit="s", utc=True).normalize())
        df.index.name = "Date"
        df = df[df["Close"].notna()]
        return df if not df.empty else None
    except Exception: return None

def _fetch_v8(ticker, period, session, crumb):
    p = {"range": period, "interval": "1d", "includeAdjustedClose": "true", "events": "div,splits"}
    if crumb: p["crumb"] = crumb
    h = {"Referer": "https://finance.yahoo.com/", "Accept": "application/json,*/*",
         "Sec-Fetch-Dest": "empty", "Sec-Fetch-Mode": "cors", "Sec-Fetch-Site": "same-site"}
    for base in _YF_BASES:
        try:
            r = session.get(f"{base}/v8/finance/chart/{ticker}", params=p, headers=h, timeout=15)
            if r.status_code == 401: return None
            if r.status_code == 200:
                df = _parse_v8(r.json())
                if df is not None: return df
        except Exception: continue
    return None

def _fetch_v7(ticker, period, session, crumb):
    e, s2 = int(time.time()), int(time.time()) - _PERIOD_DAYS.get(period, 183) * 86400
    p = {"period1": s2, "period2": e, "interval": "1d", "events": "history", "includeAdjustedClose": "true"}
    if crumb: p["crumb"] = crumb
    h = {"Referer": "https://finance.yahoo.com/", "Accept": "text/csv,*/*",
         "Sec-Fetch-Dest": "empty", "Sec-Fetch-Mode": "cors", "Sec-Fetch-Site": "same-site"}
    for base in _YF_BASES:
        try:
            r = session.get(f"{base}/v7/finance/download/{ticker}", params=p, headers=h, timeout=15)
            if r.status_code != 200 or "Date" not in r.text: continue
            df = pd.read_csv(StringIO(r.text))
            df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
            df = df.dropna(subset=["Date"]).set_index("Date")
            df["Close"] = pd.to_numeric(df.get("Adj Close", df.get("Close", pd.Series())), errors="coerce")
            for col in ["Open","High","Low","Volume"]:
                if col in df.columns: df[col] = pd.to_numeric(df[col], errors="coerce")
            df = df[["Open","High","Low","Close","Volume"]].dropna(subset=["Close"])
            if not df.empty: return df
        except Exception: continue
    return None

def _fetch_lib(ticker, period, session):
    if yf is None: return None
    import io, contextlib
    buf = io.StringIO()
    for fn in [
        lambda: _flat(yf.Ticker(ticker, session=session).history(period=period, interval="1d", auto_adjust=True, actions=False, timeout=15)),
        lambda: _flat(yf.download(ticker, period=period, interval="1d", progress=False, auto_adjust=True, actions=False, timeout=15, session=session)),
    ]:
        try:
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                df = fn()
            if df is not None and not df.empty: return df
        except Exception: pass
    return None

def fetch_yfinance_data(ticker, period):
    last_err = None
    for attempt in range(2):
        try:
            session, crumb = _get_auth(ticker, force=(attempt == 1))
        except Exception as e: last_err = str(e); continue
        for fn in [lambda: _fetch_v8(ticker, period, session, crumb),
                   lambda: _fetch_v7(ticker, period, session, crumb)]:
            try:
                df = fn()
                if df is not None and not df.empty: return df, None
            except Exception as e: last_err = str(e)
        _CACHE.update({"session": None, "crumb": None}); time.sleep(0.4)
    try:
        session, _ = _get_auth(ticker, force=True)
        df = _fetch_lib(ticker, period, session)
        if df is not None and not df.empty: return df, None
    except Exception as e: last_err = str(e)
    hint = " (use .NS for NSE, e.g. TCS.NS)" if "." not in ticker else ""
    return None, f"Could not fetch '{ticker}'{hint}. {last_err or ''}"

def _flat(df):
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df

def _get_name(ticker):
    if yf is None: return ticker
    try:
        s, _ = _get_auth(ticker)
        t = yf.Ticker(ticker, session=s)
        return (t.fast_info.get("longName") or t.info.get("shortName") or "").strip() or ticker
    except Exception: return ticker

# ── Technical indicators ─────────────────────────────────────────────────────
def calc_sma(c, w):  return c.rolling(w).mean()
def calc_ema(c, w):  return c.ewm(span=w, adjust=False).mean()
def calc_bb(c, w=20, n=2):
    sma = calc_sma(c, w); std = c.rolling(w).std()
    return sma + n*std, sma, sma - n*std
def calc_rsi(c, w=14):
    d = c.diff(); g = d.clip(lower=0); l = -d.clip(upper=0)
    ag = g.ewm(com=w-1, min_periods=w).mean(); al = l.ewm(com=w-1, min_periods=w).mean()
    return 100 - 100/(1 + ag/al.replace(0, np.nan))
def calc_macd(c, f=12, s=26, sg=9):
    ml = calc_ema(c,f) - calc_ema(c,s); sl = ml.ewm(span=sg, adjust=False).mean()
    return ml, sl, ml-sl
def calc_atr(h, l, c, w=14):
    tr = pd.concat([h-l, (h-c.shift()).abs(), (l-c.shift()).abs()], axis=1).max(axis=1)
    return tr.ewm(com=w-1, min_periods=w).mean()

# ── AI analysis engine ───────────────────────────────────────────────────────
def _sf(v, d=4):
    try: x = float(v); return None if np.isnan(x) else round(x, d)
    except: return None

def build_analysis_payload(ticker, period, name, df):
    c = df["Close"].squeeze().dropna()
    h = df["High"].squeeze(); lo = df["Low"].squeeze()
    op = df["Open"].squeeze()
    vol = df["Volume"].squeeze() if "Volume" in df.columns else None
    n = len(c)
    cur = _sf(c.iloc[-1]); prev = _sf(c.iloc[-2]) if n > 1 else cur
    currency = "INR" if ticker.upper().endswith((".NS",".BO")) else "USD"
    hi52 = _sf(c.tail(252).max()); lo52 = _sf(c.tail(252).min())
    macd_d = {}
    if n >= 27:
        ml, sl, hl = calc_macd(c)
        macd_d = {"macd": _sf(ml.iloc[-1]), "signal": _sf(sl.iloc[-1]),
                  "histogram": _sf(hl.iloc[-1]), "hist_prev": _sf(hl.iloc[-2]) if n > 27 else None,
                  "crossover": "bullish" if (hl.iloc[-1] > 0 and hl.iloc[-2] < 0) else
                               "bearish" if (hl.iloc[-1] < 0 and hl.iloc[-2] > 0) else "none"}
    bb_d = {}
    if n >= 20:
        bbu, bbm, bbl = calc_bb(c)
        bb_d = {"upper": _sf(bbu.iloc[-1]), "mid": _sf(bbm.iloc[-1]), "lower": _sf(bbl.iloc[-1]),
                "percent_b": _sf((cur - _sf(bbl.iloc[-1])) / (_sf(bbu.iloc[-1]) - _sf(bbl.iloc[-1]))) if _sf(bbu.iloc[-1]) != _sf(bbl.iloc[-1]) else None,
                "bandwidth": _sf(((bbu.iloc[-1]-bbl.iloc[-1])/bbm.iloc[-1])*100)}
    sma20 = _sf(calc_sma(c,20).iloc[-1]) if n>=20 else None
    sma50 = _sf(calc_sma(c,50).iloc[-1]) if n>=50 else None
    sma200= _sf(calc_sma(c,200).iloc[-1]) if n>=200 else None
    rsi_v = _sf(calc_rsi(c).iloc[-1]) if n>=15 else None
    atr_v = _sf(calc_atr(h,lo,c).iloc[-1]) if n>=15 else None
    vol_d = {}
    if vol is not None:
        avg20 = _sf(vol.tail(20).mean()); cv = _sf(vol.iloc[-1])
        vol_d = {"latest": cv, "avg_20d": avg20, "ratio_vs_avg": _sf(cv/avg20) if avg20 else None}
    trend = []
    if sma20 and cur: trend.append("above_sma20" if cur>sma20 else "below_sma20")
    if sma50 and cur: trend.append("above_sma50" if cur>sma50 else "below_sma50")
    if sma200 and cur: trend.append("above_sma200" if cur>sma200 else "below_sma200")
    if sma20 and sma50: trend.append("golden_cross" if sma20>sma50 else "death_cross")
    recent = df.tail(30).copy(); recent.index = recent.index.astype(str)
    ohlcv = [{"date": d[:10], "open": _sf(r.get("Open")), "high": _sf(r.get("High")),
               "low": _sf(r.get("Low")), "close": _sf(r.get("Close")),
               "volume": int(r["Volume"]) if "Volume" in r and pd.notna(r["Volume"]) else None}
              for d, r in recent.iterrows()]
    return {
        "ticker": ticker, "name": name, "currency": currency, "period": period, "bars": n,
        "price": {"current": cur, "prev": prev, "change": _sf(cur-prev) if cur and prev else None,
                  "change_pct": _sf(((cur-prev)/prev)*100) if cur and prev else None,
                  "52w_high": hi52, "52w_low": lo52,
                  "pct_from_52h": _sf(((cur-hi52)/hi52)*100) if cur and hi52 else None},
        "ma": {"sma20": sma20, "sma50": sma50, "sma200": sma200,
               "ema9": _sf(calc_ema(c,9).iloc[-1]), "ema21": _sf(calc_ema(c,21).iloc[-1])},
        "bb": bb_d, "rsi": {"value": rsi_v, "last5": [_sf(v) for v in calc_rsi(c).tail(5).tolist()] if n>=20 else []},
        "macd": macd_d, "atr": {"value": atr_v, "pct": _sf((atr_v/cur)*100) if atr_v and cur else None},
        "volume": vol_d, "trend": trend, "ohlcv": ohlcv,
    }

def build_prompt(payload):
    p = payload; px = p["price"]; ma = p["ma"]; bb = p.get("bb",{}); rsi = p.get("rsi",{})
    macd = p.get("macd",{}); atr = p.get("atr",{}); vol = p.get("volume",{})
    f = lambda v,d=2: f"{v:.{d}f}" if v is not None else "N/A"
    up = lambda v: ("↑ Price above" if px["current"] and v and px["current"]>v else "↓ Price below") if v else "N/A"
    lines = [
        f"You are a senior quantitative stock analyst with deep knowledge of technical analysis, market microstructure, and fundamental analysis.",
        f"Analyse the following comprehensive data for **{p['name']} ({p['ticker']})** over the {p['period']} period.",
        "",
        "## PRICE SNAPSHOT",
        f"- Current: {p['currency']} {f(px['current'])}  |  Prev Close: {p['currency']} {f(px['prev'])}",
        f"- Change: {f(px['change'])} ({f(px['change_pct'])}%)",
        f"- 52W High: {p['currency']} {f(px['52w_high'])}  |  52W Low: {p['currency']} {f(px['52w_low'])}",
        f"- Distance from 52W High: {f(px['pct_from_52h'])}%",
        "",
        "## MOVING AVERAGES",
        f"- SMA 20:  {p['currency']} {f(ma['sma20'])}  ({up(ma['sma20'])} SMA20)",
        f"- SMA 50:  {p['currency']} {f(ma['sma50'])}  ({up(ma['sma50'])} SMA50)",
        f"- SMA 200: {p['currency']} {f(ma['sma200'])}  ({up(ma['sma200'])} SMA200)",
        f"- EMA 9:   {p['currency']} {f(ma['ema9'])}  |  EMA 21: {p['currency']} {f(ma['ema21'])}",
        f"- Trend signals: {', '.join(p['trend']) or 'none'}",
        "",
        "## BOLLINGER BANDS (20,2σ)",
        f"- Upper: {f(bb.get('upper'))}  Mid: {f(bb.get('mid'))}  Lower: {f(bb.get('lower'))}",
        f"- %B: {f(bb.get('percent_b'),3)} (>1=overbought, <0=oversold)  |  Bandwidth: {f(bb.get('bandwidth'))}%",
        "",
        "## RSI (14)",
        f"- Current: {f(rsi.get('value'))}  Zone: {'OVERBOUGHT' if rsi.get('value') and rsi['value']>70 else 'OVERSOLD' if rsi.get('value') and rsi['value']<30 else 'NEUTRAL'}",
        f"- Last 5: {', '.join(f(v) for v in rsi.get('last5',[]))}",
        "",
        "## MACD (12,26,9)",
        f"- MACD: {f(macd.get('macd'))}  Signal: {f(macd.get('signal'))}  Histogram: {f(macd.get('histogram'))} (prev: {f(macd.get('hist_prev'))})",
        f"- Crossover: {(macd.get('crossover') or 'none').upper()}",
        "",
        "## VOLATILITY & VOLUME",
        f"- ATR(14): {p['currency']} {f(atr.get('value'))} ({f(atr.get('pct'))}% of price)",
        f"- Latest Vol: {int(vol['latest']) if vol.get('latest') else 'N/A'}  |  20D Avg: {int(vol['avg_20d']) if vol.get('avg_20d') else 'N/A'}  |  Ratio: {f(vol.get('ratio_vs_avg'))}x",
        "",
        "## RECENT OHLCV (last 30 trading days)",
        "date,open,high,low,close,volume",
    ] + [f"{r['date']},{r['open']},{r['high']},{r['low']},{r['close']},{r['volume']}" for r in p["ohlcv"]] + [
        "",
        "---",
        "## INSTRUCTIONS",
        "Based on ALL data above plus your knowledge of current macro/sector/news context for this stock:",
        "",
        "Respond with a single valid JSON object. No markdown. No extra text. Exact structure:",
        '{"verdict":"BUY|SELL|HOLD","confidence":"Low|Medium|High","time_horizon":"Short|Mid|Long",',
        '"price_targets":{"entry":0.0,"stop_loss":0.0,"target_1":0.0,"target_2":0.0},',
        '"technical_analysis":"Detailed multi-paragraph technical breakdown. Which indicators agree/conflict. Key levels.",',
        '"news_and_macro":"What you know about recent news, earnings, macro environment, sector trends that affect this stock.",',
        '"risk_factors":"Key risks that could invalidate this trade call.",',
        '"action_plan":"Step-by-step concrete action for a trader right now. Entry timing, position sizing guidance, exit rules.",',
        '"summary":"One clear sentence with the core thesis."}',
    ]
    return "\n".join(lines)

def call_openrouter(model_id, prompt):
    if not OPEN_ROUTER_API_KEY:
        raise ValueError("OPEN_ROUTER_API_KEY environment variable is not set.")
    r = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={"Authorization": f"Bearer {OPEN_ROUTER_API_KEY}",
                 "Content-Type": "application/json",
                 "HTTP-Referer": "https://starfish.finance",
                 "X-Title": "Starfish Stock Analyzer"},
        json={"model": model_id, "messages": [{"role": "user", "content": prompt}],
              "temperature": 0.15, "max_tokens": 2048},
        timeout=90,
    )
    r.raise_for_status()
    content = r.json()["choices"][0]["message"]["content"].strip()
    content = re.sub(r"^```(?:json)?\s*", "", content)
    content = re.sub(r"\s*```$", "", content)
    m = re.search(r'\{.*\}', content, re.DOTALL)
    if m: content = m.group(0)
    return json.loads(content)

# ── Chart builder ─────────────────────────────────────────────────────────────
_C = {"bg":"rgba(255,255,255,0)","paper":"rgba(255,255,255,0)","grid":"rgba(0,0,0,0.06)","axis":"#999",
      "text":"#666","white":"#111","green":"#1a6b5a","red":"#c0392b",
      "sma20":"#c8860a","sma50":"#e67e22","sma200":"#2980b9",
      "bb_u":"rgba(30,80,180,0.6)","bb_l":"rgba(30,80,180,0.6)","bb_f":"rgba(30,80,180,0.04)",
      "rsi":"#6b3fa0","rsi_ob":"rgba(192,57,43,0.12)","rsi_os":"rgba(26,107,90,0.12)",
      "macd":"#2980b9","sig":"#c8860a","hp":"rgba(26,107,90,0.7)","hn":"rgba(192,57,43,0.7)",
      "vu":"rgba(26,107,90,0.4)","vd":"rgba(192,57,43,0.4)"}

def build_chart(ticker, period, chart_type, indicators):
    if go is None: return None, "plotly not installed"
    data, err = fetch_yfinance_data(ticker, period)
    if err: return None, f"Data error: {err}"
    if data is None or data.empty: return None, f"No data for '{ticker}'. Use .NS for NSE stocks."
    missing = {"Open","High","Low","Close"} - set(data.columns)
    if missing: return None, f"Missing: {missing}"
    data = data.dropna(subset=["Close"])
    if len(data) < 5: return None, "Not enough data points."
    cl = data["Close"].squeeze(); hi = data["High"].squeeze()
    lo = data["Low"].squeeze(); op = data["Open"].squeeze()
    vol = data["Volume"].squeeze() if "Volume" in data.columns else None
    dates = data.index; name = _get_name(ticker)
    currency = "INR" if ticker.upper().endswith((".NS",".BO")) else "USD"
    sv = "vol" in indicators and vol is not None
    sr = "rsi" in indicators; sm = "macd" in indicators
    rows = 1 + int(sv) + int(sr) + int(sm)
    rh = {1:[1.0],2:[0.65,0.35],3:[0.55,0.22,0.23],4:[0.50,0.17,0.17,0.16]}.get(rows,[0.5,0.17,0.17,0.16])
    titles = [f"{name} ({ticker.upper()})"]
    if sv: titles.append("Volume")
    if sr: titles.append("RSI (14)")
    if sm: titles.append("MACD (12, 26, 9)")
    fig = make_subplots(rows=rows, cols=1, shared_xaxes=True,
                        vertical_spacing=0.03, row_heights=rh, subplot_titles=titles)
    rv = 2 if sv else None; rr = (2+int(sv)) if sr else None; rm = (2+int(sv)+int(sr)) if sm else None
    if chart_type == "candlestick":
        fig.add_trace(go.Candlestick(x=dates,open=op,high=hi,low=lo,close=cl,name="Price",
            increasing_line_color=_C["green"],increasing_fillcolor="rgba(26,107,90,.12)",
            decreasing_line_color=_C["red"],decreasing_fillcolor="rgba(192,57,43,.12)",
            line=dict(width=1)), row=1,col=1)
    else:
        fig.add_trace(go.Scatter(x=dates,y=cl,mode="lines",name="Price",
            line=dict(color="#111",width=2),fill="tozeroy",fillcolor="rgba(0,0,0,.03)"),row=1,col=1)
    if "sma" in indicators:
        for w,color,lbl in [(20,_C["sma20"],"SMA 20"),(50,_C["sma50"],"SMA 50"),(200,_C["sma200"],"SMA 200")]:
            if len(cl) >= w:
                fig.add_trace(go.Scatter(x=dates,y=calc_sma(cl,w),mode="lines",name=lbl,
                    line=dict(color=color,width=1.2),opacity=0.85),row=1,col=1)
    if "bb" in indicators and len(cl) >= 20:
        bbu,bbm,bbl = calc_bb(cl)
        fig.add_trace(go.Scatter(x=dates,y=bbu,mode="lines",name="BB Upper",
            line=dict(color=_C["bb_u"],width=1,dash="dot")),row=1,col=1)
        fig.add_trace(go.Scatter(x=dates,y=bbl,mode="lines",name="BB Lower",
            line=dict(color=_C["bb_l"],width=1,dash="dot"),
            fill="tonexty",fillcolor=_C["bb_f"]),row=1,col=1)
    if sv and vol is not None:
        colors = [_C["vu"] if c>=o else _C["vd"] for c,o in zip(cl,op)]
        fig.add_trace(go.Bar(x=dates,y=vol,name="Volume",marker_color=colors,showlegend=False),row=rv,col=1)
    if sr and len(cl) >= 15:
        rv2 = calc_rsi(cl)
        fig.add_trace(go.Scatter(x=dates,y=rv2,mode="lines",name="RSI",
            line=dict(color=_C["rsi"],width=1.5),showlegend=False),row=rr,col=1)
        fig.add_hrect(y0=70,y1=100,row=rr,col=1,fillcolor=_C["rsi_ob"],line_width=0,layer="below")
        fig.add_hrect(y0=0,y1=30,row=rr,col=1,fillcolor=_C["rsi_os"],line_width=0,layer="below")
        for lvl,c in [(70,"rgba(192,57,43,.4)"),(30,"rgba(26,107,90,.4)"),(50,"rgba(0,0,0,.1)")]:
            fig.add_hline(y=lvl,row=rr,col=1,line=dict(color=c,width=0.8,dash="dash"))
    if sm and len(cl) >= 27:
        ml,sl,hl = calc_macd(cl)
        hc = [_C["hp"] if v>=0 else _C["hn"] for v in hl.fillna(0)]
        fig.add_trace(go.Bar(x=dates,y=hl,name="MACD Hist",marker_color=hc,showlegend=False),row=rm,col=1)
        fig.add_trace(go.Scatter(x=dates,y=ml,mode="lines",name="MACD",
            line=dict(color=_C["macd"],width=1.5),showlegend=False),row=rm,col=1)
        fig.add_trace(go.Scatter(x=dates,y=sl,mode="lines",name="Signal",
            line=dict(color=_C["sig"],width=1.5),showlegend=False),row=rm,col=1)
        fig.add_hline(y=0,row=rm,col=1,line=dict(color="rgba(0,0,0,.15)",width=0.8,dash="dash"))
    ax = dict(gridcolor=_C["grid"],color=_C["axis"],showline=False,zeroline=False,tickfont=dict(size=9,color=_C["text"]))
    fig.update_layout(
        height=420+120*(rows-1), plot_bgcolor=_C["bg"], paper_bgcolor=_C["paper"],
        font=dict(color=_C["text"],family="'DM Sans',sans-serif",size=11),
        legend=dict(orientation="h",yanchor="bottom",y=1.01,xanchor="left",x=0,
                    bgcolor="rgba(0,0,0,0)",font=dict(size=10,color=_C["text"])),
        hovermode="x unified", margin=dict(l=55,r=20,t=55,b=30),
        hoverlabel=dict(bgcolor="rgba(255,255,255,.97)",bordercolor="rgba(0,0,0,.12)",font=dict(color="#111")),
        xaxis_rangeslider_visible=False, dragmode="pan",
    )
    for i in range(1, rows+1):
        fig.update_layout(**{f"xaxis{'' if i==1 else i}": {**ax,"rangeslider":{"visible":False}}})
        fig.update_layout(**{f"yaxis{'' if i==1 else i}": {**ax}})
    if sr: fig.update_layout(**{f"yaxis{'' if rr==1 else rr}": {**ax,"range":[0,100]}})
    for ann in fig.layout.annotations: ann.font.color="#aaa"; ann.font.size=10
    return pyo.plot(fig,output_type="div",include_plotlyjs=False), None

# ── Sector intelligence ───────────────────────────────────────────────────────
SECTORS = {
    "communication-services": {
        "label": "Communication Services", "sub": "Telecom · Media · Internet", "key": "XLC",
        "keywords": ["telecom","media","streaming","internet","AT&T","Netflix","Meta","Alphabet","Disney","Comcast","Verizon"],
        "queries": ["communication services sector stocks","telecom media internet stocks news"],
    },
    "consumer-discretionary": {
        "label": "Consumer Discretionary", "sub": "Retail · Autos · Leisure", "key": "XLY",
        "keywords": ["retail","auto","leisure","Amazon","Tesla","Nike","McDonald's","Booking","Home Depot"],
        "queries": ["consumer discretionary sector stocks news","retail auto leisure stocks"],
    },
    "consumer-staples": {
        "label": "Consumer Staples", "sub": "Food · Beverages · Essentials", "key": "XLP",
        "keywords": ["food","beverage","household","Procter Gamble","Coca-Cola","PepsiCo","Walmart","Costco","Unilever"],
        "queries": ["consumer staples sector stocks news","food beverage essentials stocks"],
    },
    "energy": {
        "label": "Energy", "sub": "Oil · Gas · Renewables", "key": "XLE",
        "keywords": ["oil","gas","energy","renewable","ExxonMobil","Chevron","Shell","BP","ConocoPhillips","pipeline"],
        "queries": ["energy sector stocks oil gas news","oil gas renewables stocks"],
    },
    "financials": {
        "label": "Financials", "sub": "Banks · Insurance · Fintech", "key": "XLF",
        "keywords": ["bank","insurance","fintech","JPMorgan","Visa","Mastercard","Goldman Sachs","Wells Fargo","Berkshire"],
        "queries": ["financial sector stocks banks insurance news","banks fintech stocks news"],
    },
    "health-care": {
        "label": "Health Care", "sub": "Pharma · Biotech · Hospitals", "key": "XLV",
        "keywords": ["pharma","biotech","hospital","Pfizer","UnitedHealth","Johnson","Merck","Abbott","Moderna","drug"],
        "queries": ["healthcare sector stocks pharma biotech news","pharma biotech hospital stocks"],
    },
    "industrials": {
        "label": "Industrials", "sub": "Aerospace · Machinery · Logistics", "key": "XLI",
        "keywords": ["aerospace","defense","machinery","logistics","Boeing","Caterpillar","Honeywell","UPS","Raytheon"],
        "queries": ["industrials sector stocks aerospace machinery news","defense logistics industrial stocks"],
    },
    "information-technology": {
        "label": "Information Technology", "sub": "Software · Hardware · Semiconductors", "key": "XLK",
        "keywords": ["software","hardware","semiconductor","chip","Apple","Microsoft","Nvidia","Intel","AMD","cloud","AI"],
        "queries": ["technology sector stocks software semiconductor news","software hardware chip stocks"],
    },
    "materials": {
        "label": "Materials", "sub": "Chemicals · Metals · Mining", "key": "XLB",
        "keywords": ["chemical","metal","mining","gold","Dow","Rio Tinto","Freeport","Newmont","Linde","commodity"],
        "queries": ["materials sector stocks chemicals metals mining news","mining metals commodities stocks"],
    },
    "real-estate": {
        "label": "Real Estate", "sub": "Property · REITs", "key": "XLRE",
        "keywords": ["REIT","property","real estate","Prologis","American Tower","Simon Property","Crown Castle","Equinix"],
        "queries": ["real estate sector REIT stocks news","property REIT stocks news"],
    },
    "utilities": {
        "label": "Utilities", "sub": "Power · Water · Gas", "key": "XLU",
        "keywords": ["power","electric","water","gas utility","NextEra","Duke Energy","Southern Company","Dominion","grid"],
        "queries": ["utilities sector stocks power water news","electric gas utility stocks news"],
    },
}

SCRAPE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

def parse_relative_time(text):
    if not text: return ""
    text = text.strip()
    if re.match(r"\d{4}-\d{2}-\d{2}", text):
        try: return __import__('datetime').datetime.strptime(text[:10], "%Y-%m-%d").strftime("%b %d, %Y")
        except: return text
    return text[:60]

def _rss_scrape(url, source, sector_id, client):
    if BeautifulSoup is None: return []
    results = []
    try:
        r = client.get(url, timeout=8)
        soup = BeautifulSoup(r.text, "xml")
        keywords = [k.lower() for k in SECTORS[sector_id]["keywords"]]
        for item in soup.find_all("item"):
            title = item.find("title"); link = item.find("link"); pub_date = item.find("pubDate")
            if not title or not link: continue
            title_text = title.get_text(strip=True)
            if not any(kw in title_text.lower() for kw in keywords): continue
            href = link.get_text(strip=True)
            pub = pub_date.get_text(strip=True) if pub_date else ""
            try:
                from datetime import datetime as dt
                pub = dt.strptime(pub[:25], "%a, %d %b %Y %H:%M:%S").strftime("%b %d, %Y %H:%M")
            except: pub = pub[:30]
            results.append({"title": title_text, "url": href, "source": source, "published": pub, "sector": sector_id})
            if len(results) >= 8: break
    except: pass
    return results

def scrape_yahoo_finance(s, c): return _rss_scrape("https://finance.yahoo.com/news/rssindex","Yahoo Finance",s,c)
def scrape_cnbc(s, c): return _rss_scrape("https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=10000664","CNBC",s,c)
def scrape_marketwatch(s, c): return _rss_scrape("https://feeds.marketwatch.com/marketwatch/topstories/","MarketWatch",s,c)
def scrape_benzinga(s, c): return _rss_scrape("https://www.benzinga.com/feeds/news","Benzinga",s,c)
def scrape_ft(s, c): return _rss_scrape("https://www.ft.com/rss/home/us","Financial Times",s,c)
def scrape_wsj(s, c): return _rss_scrape("https://feeds.a.dj.com/rss/RSSMarketsMain.xml","Wall Street Journal",s,c)

def scrape_reuters(sector_id, client):
    if BeautifulSoup is None: return []
    results = []
    try:
        from urllib.parse import quote_plus as qp
        query = qp(SECTORS[sector_id]["queries"][0])
        r = client.get(f"https://www.reuters.com/search/news?blob={query}&sortBy=date&dateRange=pastMonth", timeout=8)
        soup = BeautifulSoup(r.text, "html.parser")
        for item in soup.select(".search-result-indiv, article")[:8]:
            a_tag = item.find("a", href=True)
            if not a_tag: continue
            title = a_tag.get_text(strip=True)
            href = a_tag["href"]
            if not href.startswith("http"): href = "https://www.reuters.com" + href
            time_tag = item.find("time")
            pub = time_tag.get("datetime", "") if time_tag else ""
            if title and len(title) > 20:
                results.append({"title": title, "url": href, "source": "Reuters", "published": parse_relative_time(pub), "sector": sector_id})
    except: pass
    return results

def scrape_seeking_alpha(sector_id, client):
    if BeautifulSoup is None: return []
    results = []
    try:
        etf = SECTORS[sector_id]["key"].lower()
        r = client.get(f"https://seekingalpha.com/symbol/{etf}/news", timeout=8)
        soup = BeautifulSoup(r.text, "html.parser")
        for art in soup.select("article, [data-test-id='post-list-item']")[:10]:
            a_tag = art.find("a", href=True)
            if not a_tag: continue
            title = a_tag.get_text(strip=True)
            href = a_tag["href"]
            if not href.startswith("http"): href = "https://seekingalpha.com" + href
            time_tag = art.find("time")
            pub = time_tag.get("datetime", "") if time_tag else ""
            if title and len(title) > 20:
                results.append({"title": title, "url": href, "source": "Seeking Alpha", "published": parse_relative_time(pub), "sector": sector_id})
    except: pass
    return results

def fetch_all_news(sector_id):
    if httpx is None: return []
    scrapers = [scrape_yahoo_finance, scrape_cnbc, scrape_marketwatch,
                scrape_benzinga, scrape_ft, scrape_wsj, scrape_reuters, scrape_seeking_alpha]
    all_results = []
    with httpx.Client(headers=SCRAPE_HEADERS, follow_redirects=True, timeout=10) as client:
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            for future in concurrent.futures.as_completed({executor.submit(fn, sector_id, client): fn for fn in scrapers}):
                try: all_results.extend(future.result())
                except: pass
    seen = set(); unique = []
    for item in all_results:
        key = re.sub(r"[^a-z0-9]", "", item["title"].lower())[:60]
        if key not in seen: seen.add(key); unique.append(item)
    unique.sort(key=lambda x: x.get("published", ""), reverse=True)
    return unique[:40]

# ── HTML Page ─────────────────────────────────────────────────────────────────
DEFAULT_INDICATORS = {"sma","vol"}

def render_page(ticker, period, chart_type, active_indicators, graph_html, error, logo_uri):
    chips = "".join(
        f'<span class="{"chip active" if s==ticker else "chip"}" onclick="setTicker(\'{s}\')">{s}</span>\n'
        for s,_ in POPULAR_STOCKS)
    popts = "".join(f'<option value="{v}" {"selected" if v==period else ""}>{lbl}</option>\n' for v,lbl in PERIODS)
    ct_c  = "selected" if chart_type=="candlestick" else ""
    ct_l  = "selected" if chart_type=="line" else ""
    ichips= "".join(
        f'<span class="{"ind-chip active" if k in active_indicators else "ind-chip"}" data-ind="{k}" onclick="toggleInd(this)">{lbl}</span>\n'
        for k,lbl in INDICATORS)
    content = (f'<div class="error-box">{error}</div>' if error else
               graph_html if graph_html else '<div class="empty-state">Enter a ticker above.</div>')
    ntabs = "".join(
        f'<button class="{"news-tab active" if i==0 else "news-tab"}" data-handle="{ch["handle"]}">'
        f'{ch["label"]} <span class="news-tag">{ch["region"]}</span><span class="news-tag">{ch["lang"]}</span></button>\n'
        for i,ch in enumerate(NEWS_CHANNELS))

    ai_cards = ""
    for m in AI_MODELS:
        rl = rl_check(m["key"])
        pm = int((rl["rpm_used"]/rl["rpm_max"])*100)
        pd_ = int((rl["rpd_used"]/rl["rpd_max"])*100)
        ex  = " exhausted" if not rl["available"] else ""
        ai_cards += f"""<div class="ai-model-card{ex}" data-model="{m['id']}" data-key="{m['key']}" data-color="{m['color']}" data-label="{m['label']}" onclick="selectModel(this)">
  <div class="ai-model-hdr"><span class="ai-dot" style="background:{m['color']}"></span><span class="ai-mname">{m['label']}</span>{"" if rl['available'] else '<span class="ai-rl-badge">Rate Limited</span>'}</div>
  <div class="ai-mdesc">{m['desc']}</div>
  <div class="ai-rl-bars">
    <div class="ai-rl-row"><span class="ai-rl-lbl">RPM</span><div class="ai-bar-wrap"><div class="ai-bar" id="bar-rpm-{m['key']}" style="width:{pm}%;background:{m['color']}33;border-right:2px solid {m['color']}"></div></div><span class="ai-rl-cnt" id="rpm-{m['key']}">{rl['rpm_used']}/{rl['rpm_max']}</span></div>
    <div class="ai-rl-row"><span class="ai-rl-lbl">RPD</span><div class="ai-bar-wrap"><div class="ai-bar" id="bar-rpd-{m['key']}" style="width:{pd_}%;background:{m['color']}22;border-right:2px solid {m['color']}77"></div></div><span class="ai-rl-cnt" id="rpd-{m['key']}">{rl['rpd_used']}/{rl['rpd_max']}</span></div>
  </div>
</div>"""

    # Sector tiles
    sector_tiles = ""
    for sid, sdata in SECTORS.items():
        sector_tiles += f'<button class="s-tile" onclick="selectAndFetch(\'{sid}\')"><span class="s-tile-key">{sdata["key"]}</span><span class="s-tile-name">{sdata["label"]}</span><span class="s-tile-sub">{sdata["sub"]}</span></button>\n'

    sector_options = "".join(
        f'<option value="{sid}">{sdata["label"]} · {sdata["key"]}</option>'
        for sid, sdata in SECTORS.items()
    )

    fh = NEWS_CHANNELS[0]["handle"]
    ai_js = json.dumps(list(active_indicators))
    models_js = json.dumps([{"id":m["id"],"key":m["key"],"label":m["label"],"color":m["color"]} for m in AI_MODELS])

    logo_img = f'<img src="{logo_uri}" alt="Starfish" class="logo-img"/>' if logo_uri else '<div class="logo-star"></div>'

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width,initial-scale=1.0"/>
  <title>STARFISH — Live Markets &amp; AI</title>
  <link rel="preconnect" href="https://fonts.googleapis.com"/>
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin/>
  <link href="https://fonts.googleapis.com/css2?family=Playfair+Display:ital,wght@0,700;0,800;0,900;1,700&family=Syne:wght@600;700;800&family=DM+Sans:opsz,wght@9..40,300;9..40,400;9..40,500;9..40,600&family=DM+Mono:wght@400;500&display=swap" rel="stylesheet"/>
  <script src="https://cdn.plot.ly/plotly-2.27.0.min.js"></script>
  <style>
    *,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
    :root{{
      --white:#ffffff;
      --off-white:#f8f7f4;
      --paper:#f2f0eb;
      --paper-dark:#e8e5de;
      --ink:#0f0e0b;
      --ink-soft:#1c1b18;
      --ink-mid:#3a3830;
      --ink-light:#6b6860;
      --ink-faint:#9e9b95;
      --ink-ghost:#c8c5be;
      --gold:#c8860a;
      --gold-light:#e8a020;
      --gold-dim:rgba(200,134,10,0.08);
      --gold-border:rgba(200,134,10,0.22);
      --teal:#1a6b5a;
      --teal-light:#248c75;
      --teal-dim:rgba(26,107,90,0.08);
      --teal-border:rgba(26,107,90,0.20);
      --border:rgba(15,14,11,0.08);
      --border-mid:rgba(15,14,11,0.13);
      --shadow-xs:0 1px 2px rgba(15,14,11,0.05);
      --shadow-sm:0 2px 8px rgba(15,14,11,0.07),0 1px 2px rgba(15,14,11,0.04);
      --shadow-md:0 4px 20px rgba(15,14,11,0.09),0 2px 6px rgba(15,14,11,0.05);
      --r:12px;--rs:8px;
    }}
    html{{-webkit-font-smoothing:antialiased}}
    body{{font-family:'DM Sans',sans-serif;background:var(--off-white);color:var(--ink);min-height:100vh;overflow-x:hidden}}
    body::before{{content:'';position:fixed;inset:0;pointer-events:none;z-index:0;
      background:radial-gradient(ellipse 80% 50% at 75% 0%,rgba(200,134,10,0.05) 0%,transparent 55%),
                 radial-gradient(ellipse 55% 45% at 0% 90%,rgba(26,107,90,0.04) 0%,transparent 50%);}}

    /* ── HEADER ── */
    header{{position:sticky;top:0;z-index:400;height:62px;display:flex;align-items:center;
            justify-content:space-between;padding:0 clamp(1rem,4vw,2.5rem);
            background:rgba(248,247,244,0.92);backdrop-filter:blur(20px) saturate(160%);
            border-bottom:1px solid var(--border-mid);box-shadow:var(--shadow-xs)}}
    .logo{{display:flex;align-items:center;gap:10px;text-decoration:none}}
    .logo-img{{width:34px;height:34px;object-fit:contain;border-radius:6px}}
    .logo-star{{width:28px;height:28px;background:var(--ink);flex-shrink:0;
      clip-path:polygon(50% 0%,61% 35%,98% 35%,68% 57%,79% 91%,50% 70%,21% 91%,32% 57%,2% 35%,39% 35%);}}
    .logo-text-group{{display:flex;flex-direction:column;gap:1px;line-height:1}}
    .logo-word{{font-family:'Syne',sans-serif;font-size:.9rem;font-weight:800;letter-spacing:.5px;text-transform:uppercase;color:var(--ink)}}
    .logo-word em{{color:var(--gold);font-style:normal}}
    .logo-tagline{{font-family:'DM Mono',monospace;font-size:.52rem;font-weight:500;letter-spacing:2px;text-transform:uppercase;color:var(--ink-faint)}}
    .subtitle{{font-size:.68rem;color:var(--ink-faint);letter-spacing:.06em;font-family:'DM Mono',monospace;text-transform:uppercase}}
    @media(max-width:640px){{.subtitle{{display:none}}}}
    .live-pill{{display:flex;align-items:center;gap:5px;font-family:'DM Mono',monospace;font-size:.6rem;font-weight:500;
               letter-spacing:1.5px;text-transform:uppercase;color:var(--teal);background:var(--teal-dim);
               border:1px solid var(--teal-border);padding:.22rem .7rem;border-radius:20px}}
    .live-pill::before{{content:'';width:5px;height:5px;border-radius:50%;background:var(--teal-light);animation:blink 1.3s ease-in-out infinite}}
    @keyframes blink{{0%,100%{{opacity:1}}50%{{opacity:.2}}}}

    /* ── TICKER TAPE ── */
    .ticker-tape{{position:relative;z-index:10;height:32px;overflow:hidden;display:flex;align-items:center;
               background:var(--ink);border-bottom:2px solid var(--gold)}}
    .ticker-tape::before,.ticker-tape::after{{content:'';position:absolute;top:0;bottom:0;width:80px;z-index:2}}
    .ticker-tape::before{{left:0;background:linear-gradient(90deg,var(--ink) 40%,transparent)}}
    .ticker-tape::after{{right:0;background:linear-gradient(-90deg,var(--ink) 40%,transparent)}}
    .ticker-badge{{position:absolute;left:0;height:100%;z-index:3;display:flex;align-items:center;padding:0 1rem;
                  background:var(--gold);white-space:nowrap;font-family:'Syne',sans-serif;font-size:.58rem;
                  font-weight:800;letter-spacing:2px;text-transform:uppercase;color:var(--ink)}}
    .ticker-track{{display:flex;padding-left:100px;animation:ticker-run 55s linear infinite;white-space:nowrap}}
    .ticker-track:hover{{animation-play-state:paused}}
    .t-item{{font-family:'DM Mono',monospace;font-size:.62rem;font-weight:400;letter-spacing:.8px;
             color:rgba(255,255,255,.4);padding:0 1.6rem}}
    .t-item strong{{color:rgba(255,255,255,.85);font-weight:500}}
    .t-sep{{color:var(--gold);opacity:.7}}
    @keyframes ticker-run{{from{{transform:translateX(100vw)}}to{{transform:translateX(-100%)}}}}

    /* ── NAV TABS ── */
    .nav-tabs{{position:relative;z-index:10;display:flex;background:var(--paper);border-bottom:1px solid var(--border-mid)}}
    .nav-tab{{flex:1;padding:.85rem 1rem;font-family:'Syne',sans-serif;font-size:.72rem;font-weight:700;
              letter-spacing:1.5px;text-transform:uppercase;color:var(--ink-faint);background:transparent;
              border:none;cursor:pointer;transition:all .18s;text-align:center;
              border-bottom:2px solid transparent;position:relative}}
    .nav-tab:hover{{color:var(--ink);background:var(--off-white)}}
    .nav-tab.active{{color:var(--ink);border-bottom-color:var(--ink);background:var(--white)}}
    @media(max-width:600px){{.nav-tab{{font-size:.6rem;padding:.7rem .5rem}}}}

    /* ── MAIN ── */
    .tab-panel{{display:none}}.tab-panel.active{{display:block}}
    main{{position:relative;z-index:1;max-width:1300px;margin:0 auto;padding:28px 20px 64px}}
    .glass{{background:var(--white);border:1px solid var(--border);border-radius:var(--r);box-shadow:var(--shadow-xs)}}
    .panel{{padding:26px 28px;margin-bottom:18px}}
    .panel-label{{font-size:.6rem;font-weight:700;letter-spacing:.18em;text-transform:uppercase;color:var(--ink-ghost);margin-bottom:18px}}
    form{{display:grid;grid-template-columns:1.5fr 1fr 1fr auto;gap:12px;align-items:end}}
    .fg label{{display:block;font-size:.68rem;font-weight:500;letter-spacing:.05em;color:var(--ink-light);margin-bottom:7px}}
    input,select{{width:100%;background:var(--off-white);border:1px solid var(--border-mid);border-radius:var(--rs);
                  color:var(--ink);padding:9px 13px;font-size:.875rem;font-family:inherit;outline:none;
                  transition:border-color .2s,background .2s,box-shadow .2s;appearance:none;-webkit-appearance:none}}
    input::placeholder{{color:var(--ink-ghost)}}
    input:focus,select:focus{{border-color:var(--ink-mid);background:var(--white);box-shadow:0 0 0 3px rgba(15,14,11,0.06)}}
    select{{cursor:pointer;background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='10' height='6' viewBox='0 0 10 6'%3E%3Cpath fill='%23999' d='M0 0l5 5 5-5z'/%3E%3C/svg%3E");background-repeat:no-repeat;background-position:right 13px center;padding-right:34px}}
    select option{{background:#fff;color:var(--ink)}}
    .btn{{background:var(--ink);color:var(--white);border:none;border-radius:var(--rs);padding:9px 24px;
          font-size:.78rem;font-weight:700;font-family:'Syne',sans-serif;cursor:pointer;white-space:nowrap;
          letter-spacing:.1em;text-transform:uppercase;transition:all .18s;height:40px}}
    .btn:hover{{background:var(--gold)}}.btn:active{{transform:scale(.97)}}
    .chips{{display:flex;flex-wrap:wrap;gap:6px;margin-top:20px;padding-top:18px;border-top:1px solid var(--border)}}
    .chip{{background:transparent;border:1px solid var(--border-mid);border-radius:100px;padding:4px 13px;
           font-size:.7rem;font-family:'DM Mono',monospace;cursor:pointer;color:var(--ink-light);
           letter-spacing:.05em;transition:all .15s;user-select:none}}
    .chip:hover{{border-color:var(--ink-mid);color:var(--ink);background:var(--off-white)}}
    .chip.active{{background:var(--ink);border-color:var(--ink);color:var(--white);font-weight:600}}
    .ind-row{{display:flex;flex-wrap:wrap;gap:6px;margin-top:14px;padding-top:14px;border-top:1px solid var(--border);align-items:center}}
    .ind-label{{font-size:.6rem;font-weight:700;letter-spacing:.14em;text-transform:uppercase;color:var(--ink-ghost);margin-right:4px}}
    .ind-chip{{background:transparent;border:1px solid var(--border-mid);border-radius:100px;padding:3px 12px;
               font-size:.68rem;font-family:'DM Mono',monospace;cursor:pointer;color:var(--ink-light);
               letter-spacing:.05em;transition:all .15s;user-select:none}}
    .ind-chip:hover{{border-color:var(--ink-mid);color:var(--ink);background:var(--off-white)}}
    .ind-chip.active{{background:var(--ink);border-color:var(--ink);color:var(--white);font-weight:600}}
    .chart-card{{padding:20px 16px 12px;min-height:460px;display:flex;align-items:flex-start;justify-content:center;overflow:hidden}}
    .chart-card>div{{width:100%}}
    .error-box{{border:1px solid var(--border-mid);border-left:3px solid var(--ink-mid);border-radius:var(--rs);padding:14px 18px;color:var(--ink-light);font-size:.875rem;background:var(--off-white);width:100%;line-height:1.6}}
    .empty-state{{color:var(--ink-ghost);font-size:.85rem;text-align:center;letter-spacing:.03em}}

    /* ── AI PANEL ── */
    .ai-panel{{padding:26px 28px;margin-top:18px}}
    .ai-models-grid{{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin-bottom:18px}}
    .ai-model-card{{background:var(--off-white);border:1px solid var(--border);border-radius:10px;
                    padding:14px;cursor:pointer;transition:all .18s;user-select:none}}
    .ai-model-card:hover:not(.exhausted){{border-color:var(--ink-mid);background:var(--paper)}}
    .ai-model-card.selected{{border-color:var(--ink);background:var(--paper);box-shadow:0 0 0 1px var(--ink)}}
    .ai-model-card.exhausted{{opacity:.4;cursor:not-allowed}}
    .ai-model-hdr{{display:flex;align-items:center;gap:7px;margin-bottom:3px}}
    .ai-dot{{width:6px;height:6px;border-radius:50%;flex-shrink:0}}
    .ai-mname{{font-size:.78rem;font-weight:700;color:var(--ink)}}
    .ai-mdesc{{font-size:.65rem;color:var(--ink-light);margin-bottom:10px}}
    .ai-rl-bars{{display:flex;flex-direction:column;gap:4px}}
    .ai-rl-row{{display:flex;align-items:center;gap:5px}}
    .ai-rl-lbl{{font-size:.56rem;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:var(--ink-ghost);width:26px}}
    .ai-bar-wrap{{flex:1;height:3px;background:var(--border-mid);border-radius:2px;overflow:hidden}}
    .ai-bar{{height:100%;border-radius:2px;transition:width .5s ease}}
    .ai-rl-cnt{{font-size:.56rem;font-family:'DM Mono',monospace;color:var(--ink-light);width:34px;text-align:right}}
    .ai-rl-badge{{font-size:.53rem;font-weight:700;letter-spacing:.07em;text-transform:uppercase;
                  padding:2px 6px;border-radius:100px;margin-left:auto;
                  background:rgba(200,134,10,.1);border:1px solid var(--gold-border);color:var(--gold)}}
    .ai-action-row{{display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin-bottom:18px}}
    .btn-ai{{background:var(--ink);border:none;border-radius:var(--rs);color:var(--white);
             padding:9px 26px;font-size:.78rem;font-weight:700;font-family:'Syne',sans-serif;cursor:pointer;
             letter-spacing:.1em;text-transform:uppercase;transition:all .18s}}
    .btn-ai:hover{{background:var(--gold)}}.btn-ai:active{{transform:scale(.97)}}
    .btn-ai:disabled{{opacity:.35;cursor:not-allowed;transform:none}}
    .ai-sel-label{{font-size:.7rem;color:var(--ink-light)}}
    .ai-timer{{font-size:.65rem;font-family:'DM Mono',monospace;color:var(--ink-faint);margin-left:auto}}
    .ai-result{{display:none;border:1px solid var(--border);border-radius:10px;overflow:hidden;margin-top:4px}}
    .ai-result.show{{display:block}}
    .ai-verdict-bar{{display:flex;align-items:center;gap:12px;padding:16px 20px;border-bottom:1px solid var(--border);flex-wrap:wrap}}
    .ai-badge{{font-size:.9rem;font-weight:700;letter-spacing:.12em;padding:7px 18px;border-radius:7px;text-transform:uppercase;flex-shrink:0}}
    .v-BUY{{background:var(--teal-dim);border:1px solid var(--teal-border);color:var(--teal)}}
    .v-SELL{{background:rgba(192,57,43,.08);border:1px solid rgba(192,57,43,.25);color:#c0392b}}
    .v-HOLD{{background:var(--gold-dim);border:1px solid var(--gold-border);color:var(--gold)}}
    .ai-vmeta{{display:flex;flex-direction:column;gap:3px;flex:1}}
    .ai-summary{{font-size:.82rem;color:var(--ink);line-height:1.5}}
    .ai-meta-row{{display:flex;gap:12px;flex-wrap:wrap}}
    .ai-mi{{font-size:.65rem;color:var(--ink-light)}}.ai-mi strong{{color:var(--ink-faint)}}
    .ai-model-tag{{display:inline-flex;align-items:center;gap:5px;font-size:.58rem;font-weight:600;
                   letter-spacing:.08em;text-transform:uppercase;padding:2px 8px;border-radius:100px;
                   border:1px solid var(--border-mid);color:var(--ink-light);background:var(--off-white);white-space:nowrap}}
    .ai-pts{{display:grid;grid-template-columns:repeat(4,1fr);gap:1px;background:var(--border);border-bottom:1px solid var(--border)}}
    .ai-pt{{background:var(--white);padding:13px 14px;text-align:center}}
    .ai-pt-lbl{{font-size:.56rem;font-weight:700;letter-spacing:.1em;text-transform:uppercase;color:var(--ink-ghost);margin-bottom:4px}}
    .ai-pt-val{{font-size:.9rem;font-weight:700;font-family:'DM Mono',monospace}}
    .pt-e{{color:var(--ink)}}.pt-sl{{color:#c0392b}}.pt-t1{{color:var(--teal)}}.pt-t2{{color:#2980b9}}
    .ai-secs{{padding:0}}
    .ai-sec{{padding:16px 20px;border-bottom:1px solid var(--border)}}
    .ai-sec:last-child{{border-bottom:none}}
    .ai-sec-hdr{{font-size:.56rem;font-weight:700;letter-spacing:.14em;text-transform:uppercase;
                 color:var(--ink-ghost);margin-bottom:9px}}
    .ai-sec-body{{font-size:.8rem;color:var(--ink-mid);line-height:1.8;white-space:pre-wrap;word-break:break-word}}
    .ai-loading{{display:flex;flex-direction:column;align-items:center;justify-content:center;padding:48px 24px;gap:12px}}
    .ai-spin{{width:24px;height:24px;border-radius:50%;border:2px solid var(--border-mid);
              border-top-color:var(--ink);animation:spin .7s linear infinite}}
    @keyframes spin{{to{{transform:rotate(360deg)}}}}
    .ai-load-txt{{font-size:.75rem;color:var(--ink-light);letter-spacing:.04em}}
    .ai-err{{padding:18px 20px;color:#c0392b;font-size:.8rem;line-height:1.6}}

    /* ── LIVE NEWS (YouTube) ── */
    .news-panel{{padding:26px 28px;margin-top:18px}}
    .news-live-dot{{display:inline-block;width:6px;height:6px;border-radius:50%;background:#c0392b;
                    margin-right:6px;animation:lp 1.4s ease-in-out infinite;vertical-align:middle}}
    @keyframes lp{{0%,100%{{opacity:1;transform:scale(1)}}50%{{opacity:.3;transform:scale(.6)}}}}
    .news-tabs{{display:flex;gap:7px;margin-bottom:18px;flex-wrap:wrap}}
    .news-tab{{background:transparent;border:1px solid var(--border-mid);border-radius:100px;padding:5px 16px;
               font-size:.7rem;font-family:'DM Mono',monospace;cursor:pointer;color:var(--ink-light);
               letter-spacing:.05em;transition:all .15s;user-select:none}}
    .news-tab:hover{{border-color:var(--ink-mid);color:var(--ink);background:var(--off-white)}}
    .news-tab.active{{background:var(--ink);border-color:var(--ink);color:var(--white);font-weight:600}}
    .news-tab.active .news-tag{{background:rgba(255,255,255,.15);color:rgba(255,255,255,.5)}}
    .news-iframe-wrap{{position:relative;width:100%;padding-top:56.25%;border-radius:var(--rs);overflow:hidden;background:var(--paper)}}
    .news-loading{{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;
                   color:var(--ink-light);font-size:.78rem;letter-spacing:.05em;flex-direction:column;gap:10px}}
    .news-spinner{{width:20px;height:20px;border-radius:50%;border:2px solid var(--border-mid);border-top-color:var(--ink);animation:spin .8s linear infinite}}
    .news-iframe-wrap iframe{{position:absolute;inset:0;width:100%;height:100%;border:none}}
    .news-tag{{font-size:.53rem;font-weight:600;letter-spacing:.08em;text-transform:uppercase;
               padding:1px 4px;border-radius:3px;background:var(--border);color:var(--ink-faint);margin-left:4px;vertical-align:middle}}
    .nsb{{display:inline-flex;align-items:center;gap:5px;font-size:.6rem;font-weight:700;
           letter-spacing:.1em;text-transform:uppercase;padding:3px 9px;border-radius:100px;white-space:nowrap}}
    .nsb.live{{background:rgba(192,57,43,.08);border:1px solid rgba(192,57,43,.25);color:#c0392b}}
    .nsb.live::before{{content:'';display:inline-block;width:5px;height:5px;border-radius:50%;background:#c0392b;animation:lp 1.4s ease-in-out infinite}}
    .nsb.latest{{background:var(--off-white);border:1px solid var(--border-mid);color:var(--ink-light)}}
    .nsb.error{{background:var(--gold-dim);border:1px solid var(--gold-border);color:var(--gold)}}

    /* ── SECTOR PANEL ── */
    .sector-panel{{padding:28px}}
    .sector-top{{display:flex;align-items:center;justify-content:space-between;gap:1rem;margin-bottom:22px;flex-wrap:wrap}}
    .select-compound{{display:flex;background:var(--white);border:1.5px solid var(--border-mid);border-radius:var(--rs);overflow:hidden;box-shadow:var(--shadow-xs);transition:border-color .2s}}
    .select-compound:focus-within{{border-color:var(--ink)}}
    .sel-prefix{{display:flex;align-items:center;padding:0 1rem;font-family:'DM Mono',monospace;font-size:.58rem;font-weight:500;letter-spacing:2px;text-transform:uppercase;color:var(--ink-faint);white-space:nowrap;border-right:1px solid var(--border);background:var(--off-white);flex-shrink:0}}
    @media(max-width:480px){{.sel-prefix{{display:none}}}}
    .sector-select{{flex:1;appearance:none;background:transparent;border:none;outline:none;padding:.85rem 2.5rem .85rem 1rem;font-family:'DM Sans',sans-serif;font-size:.9rem;font-weight:600;color:var(--ink);cursor:pointer;min-width:0;background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='11' height='7' viewBox='0 0 11 7'%3E%3Cpath d='M1 1l4.5 4.5L10 1' stroke='%23c8860a' stroke-width='2' fill='none' stroke-linecap='round' stroke-linejoin='round'/%3E%3C/svg%3E");background-repeat:no-repeat;background-position:right 1rem center}}
    .sector-select option{{background:#fff;color:var(--ink)}}
    .fetch-btn{{display:flex;align-items:center;gap:.5rem;padding:.85rem 1.5rem;flex-shrink:0;
                background:var(--ink);border:none;cursor:pointer;font-family:'Syne',sans-serif;font-size:.7rem;font-weight:700;letter-spacing:1.5px;text-transform:uppercase;color:var(--white);transition:all .18s;white-space:nowrap}}
    .fetch-btn:hover{{background:var(--gold)}}.fetch-btn:active{{transform:scale(.98)}}.fetch-btn:disabled{{opacity:.4;cursor:not-allowed}}
    .source-chips-row{{display:flex;align-items:center;flex-wrap:wrap;gap:.3rem}}
    .chips-label{{font-family:'DM Mono',monospace;font-size:.56rem;font-weight:500;letter-spacing:1.8px;text-transform:uppercase;color:var(--ink-ghost);margin-right:.3rem}}
    .src-chip{{font-family:'DM Mono',monospace;font-size:.56rem;font-weight:500;letter-spacing:.8px;text-transform:uppercase;color:var(--ink-light);background:var(--off-white);border:1px solid var(--border);padding:.15rem .55rem;border-radius:20px}}
    .sector-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(155px,1fr));gap:.65rem;margin-top:22px}}
    .s-tile{{background:var(--off-white);border:1px solid var(--border);border-radius:var(--rs);padding:1rem;
             cursor:pointer;text-align:left;color:inherit;box-shadow:var(--shadow-xs);
             transition:transform .15s,box-shadow .15s,border-color .15s;display:flex;flex-direction:column;gap:.25rem}}
    .s-tile:hover{{transform:translateY(-2px);box-shadow:var(--shadow-md);border-color:var(--gold-border)}}
    .s-tile-key{{font-family:'DM Mono',monospace;font-size:.6rem;font-weight:600;letter-spacing:1.5px;text-transform:uppercase;color:var(--gold);background:var(--gold-dim);border:1px solid var(--gold-border);padding:.12rem .45rem;border-radius:3px;display:inline-block;align-self:flex-start;margin-bottom:.2rem}}
    .s-tile-name{{font-family:'DM Sans',sans-serif;font-size:.78rem;font-weight:700;color:var(--ink);line-height:1.3}}
    .s-tile-sub{{font-family:'DM Sans',sans-serif;font-size:.65rem;color:var(--ink-faint);line-height:1.3}}
    .sector-res-header{{display:flex;align-items:flex-end;justify-content:space-between;gap:1rem;margin-bottom:1.25rem;padding-bottom:1rem;border-bottom:1.5px solid var(--border-mid);flex-wrap:wrap}}
    .res-title{{font-family:'Playfair Display',serif;font-size:clamp(1.2rem,3vw,1.8rem);font-weight:800;line-height:1.1;color:var(--ink)}}
    .res-title em{{font-style:italic;color:var(--gold)}}
    .res-eyebrow{{font-family:'DM Mono',monospace;font-size:.58rem;font-weight:500;letter-spacing:2px;text-transform:uppercase;color:var(--gold);margin-bottom:.25rem}}
    .res-count{{font-family:'DM Mono',monospace;font-size:.6rem;font-weight:500;letter-spacing:1.5px;text-transform:uppercase;color:var(--teal);background:var(--teal-dim);border:1px solid var(--teal-border);padding:.24rem .7rem;border-radius:20px}}
    .res-time{{font-family:'DM Mono',monospace;font-size:.58rem;font-weight:500;letter-spacing:1px;color:var(--ink-faint)}}
    .filter-row{{display:flex;flex-wrap:wrap;gap:.35rem;margin-bottom:1.5rem;align-items:center}}
    .filter-label{{font-family:'DM Mono',monospace;font-size:.56rem;font-weight:500;letter-spacing:1.8px;text-transform:uppercase;color:var(--ink-ghost);margin-right:.3rem}}
    .pill{{font-family:'DM Sans',sans-serif;font-size:.7rem;font-weight:600;padding:.28rem .8rem;
           border:1px solid var(--border-mid);border-radius:20px;background:var(--white);color:var(--ink-light);
           cursor:pointer;transition:all .14s;box-shadow:var(--shadow-xs)}}
    .pill:hover{{border-color:var(--gold-border);color:var(--gold);background:var(--gold-dim)}}
    .pill.active{{background:var(--ink);border-color:var(--ink);color:var(--white)}}
    .news-grid-sector{{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:.85rem}}
    @media(max-width:680px){{.news-grid-sector{{grid-template-columns:1fr}}}}
    @keyframes card-in{{from{{opacity:0;transform:translateY(10px)}}to{{opacity:1;transform:translateY(0)}}}}
    .scard{{background:var(--white);border:1px solid var(--border);border-radius:var(--rs);padding:1.2rem;
            display:flex;flex-direction:column;gap:.75rem;box-shadow:var(--shadow-xs);
            transition:transform .18s,box-shadow .18s,border-color .18s;position:relative;overflow:hidden;
            animation:card-in .35s ease both}}
    .scard::after{{content:'';position:absolute;top:0;left:0;width:100%;height:2px;background:linear-gradient(90deg,var(--gold),var(--teal));opacity:0;transition:opacity .2s}}
    .scard:hover{{transform:translateY(-3px);box-shadow:var(--shadow-md);border-color:var(--border-mid)}}.scard:hover::after{{opacity:1}}
    .scard-top{{display:flex;align-items:flex-start;justify-content:space-between;gap:.6rem}}
    .scard-src{{font-family:'DM Mono',monospace;font-size:.56rem;font-weight:500;letter-spacing:1.5px;text-transform:uppercase;color:var(--teal);background:var(--teal-dim);border:1px solid var(--teal-border);padding:.14rem .5rem;border-radius:3px;white-space:nowrap}}
    .scard-num{{font-family:'DM Mono',monospace;font-size:.62rem;font-weight:500;color:var(--ink-ghost);flex-shrink:0}}
    .scard-title{{font-family:'DM Sans',sans-serif;font-size:.88rem;font-weight:700;line-height:1.5;color:var(--ink)}}
    .scard-title a{{color:inherit;text-decoration:none;display:block;transition:color .14s}}.scard-title a:hover{{color:var(--gold)}}
    .scard-footer{{display:flex;align-items:center;justify-content:space-between;gap:.6rem;margin-top:auto;padding-top:.75rem;border-top:1px solid var(--border)}}
    .scard-date{{font-family:'DM Mono',monospace;font-size:.6rem;font-weight:400;color:var(--ink-ghost);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
    .scard-read{{font-family:'Syne',sans-serif;font-size:.62rem;font-weight:700;letter-spacing:1px;text-transform:uppercase;color:var(--ink-light);text-decoration:none;padding:.24rem .65rem;border:1px solid var(--border-mid);border-radius:4px;background:var(--off-white);transition:all .14s;white-space:nowrap;flex-shrink:0}}
    .scard-read:hover{{background:var(--ink);color:var(--white);border-color:var(--ink)}}
    .state{{display:flex;flex-direction:column;align-items:center;justify-content:center;padding:4rem 2rem;text-align:center;gap:1.1rem}}
    .state-icon{{width:50px;height:50px;border:1px solid var(--border-mid);border-radius:50%;display:flex;align-items:center;justify-content:center;background:var(--white)}}
    .state-icon svg{{width:20px;height:20px;stroke:var(--ink-faint);fill:none;stroke-width:1.5;stroke-linecap:round;stroke-linejoin:round}}
    .state-title{{font-family:'Playfair Display',serif;font-size:1.4rem;font-weight:800;color:var(--ink-mid)}}
    .state-sub{{font-family:'DM Sans',sans-serif;font-size:.85rem;color:var(--ink-faint);max-width:360px;line-height:1.6}}
    .spinner{{width:36px;height:36px;border:2.5px solid var(--border-mid);border-top-color:var(--gold);border-radius:50%;animation:spin .75s linear infinite}}
    .spin-label{{font-family:'DM Mono',monospace;font-size:.62rem;font-weight:500;letter-spacing:2.5px;text-transform:uppercase;color:var(--ink-faint)}}

    /* ── DISCLAIMER ── */
    .disclaimer-wrap{{max-width:1300px;margin:0 auto;padding:0 20px 32px}}
    .disclaimer-box{{display:flex;gap:12px;align-items:flex-start;background:var(--paper);border:1px solid var(--border);border-radius:var(--rs);padding:14px 20px}}
    .disclaimer-icon{{color:var(--ink-ghost);flex-shrink:0;margin-top:2px}}
    .disclaimer-body{{font-size:.66rem;color:var(--ink-ghost);line-height:1.8;letter-spacing:.01em}}
    .disclaimer-label{{display:inline-block;font-size:.54rem;font-weight:700;letter-spacing:.16em;text-transform:uppercase;color:var(--ink-faint);border:1px solid var(--border-mid);border-radius:3px;padding:1px 6px;background:var(--off-white);vertical-align:middle;position:relative;top:-1px;margin-right:7px}}

    /* ── FOOTER ── */
    .site-footer{{position:relative;z-index:1;text-align:center;padding:48px 20px 72px;border-top:1px solid var(--border-mid);background:var(--paper)}}
    .site-footer-sub{{font-family:'DM Mono',monospace;font-size:.6rem;font-weight:500;letter-spacing:.24em;text-transform:uppercase;color:var(--ink-ghost);margin-bottom:12px}}
    .site-footer-name{{font-family:'Playfair Display',serif;font-size:clamp(2.5rem,8vw,5rem);font-weight:900;letter-spacing:-.02em;text-transform:uppercase;color:var(--ink);line-height:1}}

    @media(max-width:860px){{form{{grid-template-columns:1fr 1fr;gap:10px}}.fg:first-child{{grid-column:span 2}}.btn{{grid-column:span 2;width:100%}}.ai-models-grid{{grid-template-columns:repeat(2,1fr)}}.ai-pts{{grid-template-columns:repeat(2,1fr)}}}}
    @media(max-width:600px){{main{{padding:18px 14px 48px}}.panel,.ai-panel,.news-panel{{padding:18px 16px}}.chart-card{{padding:14px 8px 8px;min-height:300px}}.sector-panel{{padding:18px 16px}}.ai-models-grid{{grid-template-columns:1fr}}}}
  </style>
</head>
<body>
<header>
  <a class="logo" href="/">
    {logo_img}
    <div class="logo-text-group">
      <span class="logo-word">Star<em>fish</em></span>
      <span class="logo-tagline">Live Markets &amp; AI</span>
    </div>
  </a>
  <span class="subtitle">Live Markets · AI Analysis · Sector Intelligence</span>
  <div><span class="live-pill">Live</span></div>
</header>

<div class="ticker-tape">
  <span class="ticker-badge">Markets</span>
  <div class="ticker-track">
    <span class="t-item"><strong>XLC</strong> Comm Services <span class="t-sep">&middot;</span></span>
    <span class="t-item"><strong>XLY</strong> Consumer Disc <span class="t-sep">&middot;</span></span>
    <span class="t-item"><strong>XLP</strong> Consumer Staples <span class="t-sep">&middot;</span></span>
    <span class="t-item"><strong>XLE</strong> Energy <span class="t-sep">&middot;</span></span>
    <span class="t-item"><strong>XLF</strong> Financials <span class="t-sep">&middot;</span></span>
    <span class="t-item"><strong>XLV</strong> Health Care <span class="t-sep">&middot;</span></span>
    <span class="t-item"><strong>XLI</strong> Industrials <span class="t-sep">&middot;</span></span>
    <span class="t-item"><strong>XLK</strong> Info Technology <span class="t-sep">&middot;</span></span>
    <span class="t-item"><strong>XLB</strong> Materials <span class="t-sep">&middot;</span></span>
    <span class="t-item"><strong>XLRE</strong> Real Estate <span class="t-sep">&middot;</span></span>
    <span class="t-item"><strong>XLU</strong> Utilities <span class="t-sep">&middot;</span></span>
    <span class="t-item">Reuters &middot; CNBC &middot; WSJ &middot; Yahoo Finance &middot; MarketWatch &middot; FT &middot; Benzinga &middot; Seeking Alpha <span class="t-sep">&middot;</span></span>
  </div>
</div>

<nav class="nav-tabs">
  <button class="nav-tab active" onclick="switchTab('tab-charts',this)">&#9685; Charts &amp; AI</button>
  <button class="nav-tab" onclick="switchTab('tab-sector',this)">&#9776; Sector Intelligence</button>
  <button class="nav-tab" onclick="switchTab('tab-live',this)">&#9632; Live News</button>
</nav>

<!-- ═══════ TAB: CHARTS & AI ═══════ -->
<div id="tab-charts" class="tab-panel active">
<main>

<div class="glass panel">
  <div class="panel-label">Stock Search</div>
  <form method="POST" action="/" id="main-form">
    <input type="hidden" name="indicators" id="inds-h" value="{','.join(active_indicators)}"/>
    <input type="hidden" name="active_tab" value="charts"/>
    <div class="fg">
      <label for="ticker">Ticker Symbol</label>
      <input id="ticker" name="ticker" type="text" value="{ticker}"
             placeholder="AAPL, GOOGL, TCS.NS" required autocomplete="off" autocapitalize="characters" spellcheck="false"/>
    </div>
    <div class="fg">
      <label for="period">Time Range</label>
      <select id="period" name="period">{popts}</select>
    </div>
    <div class="fg">
      <label for="chart_type">Chart Type</label>
      <select id="chart_type" name="chart_type">
        <option value="candlestick" {ct_c}>Candlestick</option>
        <option value="line" {ct_l}>Line</option>
      </select>
    </div>
    <button type="submit" class="btn">Load</button>
  </form>
  <div class="chips">{chips}</div>
  <div class="ind-row"><span class="ind-label">Indicators</span>{ichips}</div>
</div>

<div class="glass chart-card">{content}</div>

<div class="glass ai-panel">
  <div class="panel-label">AI Trading Analysis</div>
  <div class="ai-models-grid" id="ai-grid">{ai_cards}</div>
  <div class="ai-action-row">
    <button class="btn-ai" id="btn-ai" onclick="runAnalysis()" disabled>Analyse&nbsp;{ticker}</button>
    <span class="ai-sel-label" id="ai-sel-lbl"></span>
    <span class="ai-timer" id="ai-timer"></span>
  </div>
  <div class="ai-result" id="ai-result"></div>
</div>

</main>
</div>

<!-- ═══════ TAB: SECTOR INTELLIGENCE ═══════ -->
<div id="tab-sector" class="tab-panel">
<main>
<div class="glass sector-panel">
  <div class="panel-label">Sector Intelligence</div>
  <div class="sector-top">
    <div class="select-compound">
      <span class="sel-prefix">Sector</span>
      <select id="sector-sel" class="sector-select">
        <option value="">Select a GICS Sector —</option>
        {sector_options}
      </select>
      <button class="fetch-btn" id="fetchBtn" onclick="fetchSectorNews()">
        Fetch News <span style="margin-left:4px">&#8594;</span>
      </button>
    </div>
    <div class="source-chips-row">
      <span class="chips-label">Sources</span>
      <span class="src-chip">Reuters</span><span class="src-chip">CNBC</span>
      <span class="src-chip">WSJ</span><span class="src-chip">Yahoo Finance</span>
      <span class="src-chip">MarketWatch</span><span class="src-chip">FT</span>
      <span class="src-chip">Benzinga</span><span class="src-chip">Seeking Alpha</span>
    </div>
  </div>
  <div class="sector-grid" id="sector-tiles">{sector_tiles}</div>
  <div id="sector-output"></div>
</div>
</main>
</div>

<!-- ═══════ TAB: LIVE NEWS ═══════ -->
<div id="tab-live" class="tab-panel">
<main>
<div class="glass news-panel">
  <div class="panel-label"><span class="news-live-dot"></span>Live Financial News Streams</div>
  <div class="news-tabs" id="ntabs">{ntabs}</div>
  <div class="news-iframe-wrap">
    <div id="nload" class="news-loading"><div class="news-spinner"></div><span>Loading stream&hellip;</span></div>
    <iframe id="nframe" allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture" allowfullscreen style="display:none"></iframe>
  </div>
  <div style="margin-top:10px;display:flex;align-items:center;gap:10px;flex-wrap:wrap;">
    <span id="nbadge" class="nsb" style="display:none"></span>
  </div>
</div>
</main>
</div>

<!-- ── DISCLAIMER ── -->
<div class="disclaimer-wrap">
  <div class="disclaimer-box">
    <div class="disclaimer-icon">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
        <circle cx="12" cy="12" r="10" stroke="currentColor" stroke-width="1.5"/>
        <path d="M12 8v4M12 16h.01" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/>
      </svg>
    </div>
    <p class="disclaimer-body">
      <span class="disclaimer-label">Disclaimer</span>Financial information is sourced from Yahoo Finance and public data providers for informational and educational purposes only. AI analyses are powered by DeepSeek, Qwen, and Meta's Llama models via OpenRouter. This content is not intended as trading, investment, financial, tax, legal, or professional advice. Past performance does not predict future results. Always consult qualified professionals before making decisions. We disclaim all liability for losses from reliance on this information.
    </p>
  </div>
</div>

<!-- ── FOOTER ── -->
<footer class="site-footer">
  <div class="site-footer-sub">made by</div>
  <div class="site-footer-name">ANTON BESKI</div>
</footer>

<script>
var TICKER = {json.dumps(ticker)};
var PERIOD = {json.dumps(period)};
var MODELS = {models_js};
var allSectorArticles = [];

// ── Tab switching ──
function switchTab(id, btn) {{
  document.querySelectorAll('.tab-panel').forEach(p=>p.classList.remove('active'));
  document.querySelectorAll('.nav-tab').forEach(t=>t.classList.remove('active'));
  document.getElementById(id).classList.add('active');
  btn.classList.add('active');
  if(id==='tab-live' && !liveLoaded){{loadCh('{fh}');liveLoaded=true;}}
}}
var liveLoaded = false;

// ── Stock chips ──
function setTicker(s){{document.getElementById('ticker').value=s;document.getElementById('main-form').submit();}}

// ── Indicator toggles ──
var aInds = {ai_js};
function toggleInd(el){{
  var k=el.dataset.ind,i=aInds.indexOf(k);
  i===-1?(aInds.push(k),el.classList.add('active')):(aInds.splice(i,1),el.classList.remove('active'));
  document.getElementById('inds-h').value=aInds.join(',');
  document.getElementById('main-form').submit();
}}

// ── AI model selection ──
var selModelId=null,selModelKey=null,timerIv=null;
function selectModel(card){{
  if(card.classList.contains('exhausted'))return;
  document.querySelectorAll('.ai-model-card').forEach(c=>c.classList.remove('selected'));
  card.classList.add('selected');
  selModelId=card.dataset.model; selModelKey=card.dataset.key;
  document.getElementById('ai-sel-lbl').textContent='Model: '+card.dataset.label;
  document.getElementById('btn-ai').disabled=false;
  if(timerIv)clearInterval(timerIv);
  refreshRateLimits();
  timerIv=setInterval(refreshRateLimits,4000);
}}
function refreshRateLimits(){{
  fetch('/api/rate-limits').then(r=>r.json()).then(data=>{{
    MODELS.forEach(m=>{{
      var d=data[m.key]; if(!d)return;
      var rpmEl=document.getElementById('rpm-'+m.key);
      var rpdEl=document.getElementById('rpd-'+m.key);
      var barRpm=document.getElementById('bar-rpm-'+m.key);
      var barRpd=document.getElementById('bar-rpd-'+m.key);
      if(rpmEl)rpmEl.textContent=d.rpm_used+'/'+d.rpm_max;
      if(rpdEl)rpdEl.textContent=d.rpd_used+'/'+d.rpd_max;
      if(barRpm)barRpm.style.width=Math.round((d.rpm_used/d.rpm_max)*100)+'%';
      if(barRpd)barRpd.style.width=Math.round((d.rpd_used/d.rpd_max)*100)+'%';
    }});
    if(selModelKey&&data[selModelKey]){{
      var sd=data[selModelKey];
      var timerEl=document.getElementById('ai-timer');
      if(sd.rpm_used>=sd.rpm_max){{
        timerEl.textContent='RPM full — resets in '+sd.rpm_reset_secs+'s';
        document.getElementById('btn-ai').disabled=true;
      }}else{{
        timerEl.textContent='RPM: '+sd.rpm_used+'/'+sd.rpm_max+' used  ·  RPD: '+sd.rpd_used+'/'+sd.rpd_max+' used';
        document.getElementById('btn-ai').disabled=false;
      }}
    }}
  }}).catch(()=>{{}});
}}
function runAnalysis(){{
  if(!selModelId)return;
  var btn=document.getElementById('btn-ai');
  var res=document.getElementById('ai-result');
  btn.disabled=true; btn.textContent='Analysing…';
  res.className='ai-result show';
  res.innerHTML='<div class="ai-loading"><div class="ai-spin"></div><div class="ai-load-txt">Crunching '+TICKER+' data with AI… (20–40s)</div></div>';
  fetch('/api/ai-analysis',{{
    method:'POST', headers:{{'Content-Type':'application/json'}},
    body:JSON.stringify({{ticker:TICKER,period:PERIOD,model_id:selModelId}})
  }}).then(r=>r.json()).then(data=>{{
    btn.disabled=false; btn.textContent='Analyse '+TICKER;
    if(data.error){{res.innerHTML='<div class="ai-err">'+esc(data.error)+'</div>';return;}}
    renderResult(data); refreshRateLimits();
  }}).catch(err=>{{
    btn.disabled=false; btn.textContent='Analyse '+TICKER;
    res.innerHTML='<div class="ai-err">Network error: '+esc(String(err))+'</div>';
  }});
}}
function esc(s){{return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}}
function fn(v,d){{d=d||2;return(v==null)?'N/A':Number(v).toFixed(d);}}
function renderResult(data){{
  var r=data.analysis;
  var m=MODELS.find(x=>x.id===data.model_id)||{{}};
  var verdict=(r.verdict||'HOLD').toUpperCase();
  var pt=r.price_targets||{{}};
  var secs=[
    {{lbl:'Technical Analysis',key:'technical_analysis'}},
    {{lbl:'News & Macro Context',key:'news_and_macro'}},
    {{lbl:'Risk Factors',key:'risk_factors'}},
    {{lbl:"Trader's Action Plan",key:'action_plan'}},
  ];
  var secHtml=secs.map(s=>'<div class="ai-sec"><div class="ai-sec-hdr">'+s.lbl+'</div><div class="ai-sec-body">'+esc(r[s.key]||'No data.')+'</div></div>').join('');
  document.getElementById('ai-result').innerHTML=
    '<div class="ai-verdict-bar">'+
      '<div class="ai-badge v-'+verdict+'">'+verdict+'</div>'+
      '<div class="ai-vmeta"><div class="ai-summary">'+esc(r.summary||'')+'</div>'+
      '<div class="ai-meta-row"><span class="ai-mi"><strong>Confidence&nbsp;</strong>'+esc(r.confidence||'Medium')+'</span>'+
      '<span class="ai-mi"><strong>Horizon&nbsp;</strong>'+esc(r.time_horizon||'Mid')+'-term</span></div></div>'+
      '<span class="ai-model-tag"><span style="display:inline-block;width:5px;height:5px;border-radius:50%;background:'+(m.color||'#111')+';margin-right:4px"></span>'+esc(m.label||data.model_id)+'</span>'+
    '</div>'+
    '<div class="ai-pts">'+
      '<div class="ai-pt"><div class="ai-pt-lbl">Entry</div><div class="ai-pt-val pt-e">'+fn(pt.entry)+'</div></div>'+
      '<div class="ai-pt"><div class="ai-pt-lbl">Stop Loss</div><div class="ai-pt-val pt-sl">'+fn(pt.stop_loss)+'</div></div>'+
      '<div class="ai-pt"><div class="ai-pt-lbl">Target 1</div><div class="ai-pt-val pt-t1">'+fn(pt.target_1)+'</div></div>'+
      '<div class="ai-pt"><div class="ai-pt-lbl">Target 2</div><div class="ai-pt-val pt-t2">'+fn(pt.target_2)+'</div></div>'+
    '</div>'+
    '<div class="ai-secs">'+secHtml+'</div>';
}}

// ── Sector news ──
function selectAndFetch(id){{
  document.getElementById('sector-sel').value=id;
  document.getElementById('sector-tiles').style.display='none';
  fetchSectorNews();
}}
async function fetchSectorNews(){{
  var sector=document.getElementById('sector-sel').value;
  if(!sector){{document.getElementById('sector-sel').focus();return;}}
  var btn=document.getElementById('fetchBtn');
  btn.disabled=true; btn.innerHTML='<span style="display:inline-block;width:11px;height:11px;border:2px solid rgba(255,255,255,.3);border-top-color:#fff;border-radius:50%;animation:spin .6s linear infinite;vertical-align:middle;margin-right:5px"></span>Fetching';
  document.getElementById('sector-tiles').style.display='none';
  document.getElementById('sector-output').innerHTML='<div class="state"><div class="spinner"></div><div class="state-title">Scanning Sources</div><div class="state-sub">Pulling live data from Reuters, CNBC, WSJ, Yahoo Finance, MarketWatch, FT, Benzinga and Seeking Alpha simultaneously.</div><div class="spin-label">Please Wait</div></div>';
  try{{
    var resp=await fetch('/api/news?sector='+encodeURIComponent(sector));
    if(!resp.ok)throw new Error('Server responded with '+resp.status);
    var data=await resp.json();
    allSectorArticles=data.articles||[];
    renderSectorNews(allSectorArticles,data.sector_label,data.elapsed_seconds);
  }}catch(e){{
    document.getElementById('sector-output').innerHTML='<div class="state"><div class="state-icon"><svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg></div><div class="state-title">Request Failed</div><div class="state-sub">'+esc(e.message)+'. Please try again.</div></div>';
  }}finally{{
    btn.disabled=false; btn.innerHTML='Fetch News &#8594;';
  }}
}}
function renderSectorNews(articles,label,elapsed){{
  var sources=[...new Set(articles.map(a=>a.source))].sort();
  var header='<div class="sector-res-header"><div><div class="res-eyebrow">Live Results</div><div class="res-title">Latest: <em>'+esc(label||'')+'</em></div></div><div style="display:flex;align-items:center;gap:.6rem"><span class="res-count">'+articles.length+' Articles</span>'+(elapsed?'<span class="res-time">'+elapsed+'s</span>':'')+'</div></div>';
  var filters='<div class="filter-row"><span class="filter-label">Filter</span><button class="pill active" onclick="filterSector(\'all\',this)">All</button>'+sources.map(s=>'<button class="pill" onclick="filterSector('+JSON.stringify(s)+',this)">'+esc(s)+'</button>').join('')+'</div>';
  if(!articles.length){{
    document.getElementById('sector-output').innerHTML=header+filters+'<div class="state"><div class="state-title">No Articles Found</div><div class="state-sub">No matching articles at this time. Try a different sector.</div></div>';
    return;
  }}
  var cards=articles.map((a,i)=>{{
    var src=esc(a.source||''),title=esc(a.title||''),url=(a.url||'#').replace(/"/g,'%22'),date=esc(a.published||''),idx=String(i+1).padStart(2,'0'),delay=Math.min(i*.03,.7).toFixed(2);
    return '<div class="scard" data-source="'+src+'" style="animation-delay:'+delay+'s"><div class="scard-top"><span class="scard-src">'+src+'</span><span class="scard-num">'+idx+'</span></div><div class="scard-title"><a href="'+url+'" target="_blank" rel="noopener noreferrer">'+title+'</a></div><div class="scard-footer"><span class="scard-date">'+date+'</span><a class="scard-read" href="'+url+'" target="_blank" rel="noopener noreferrer">Read ›</a></div></div>';
  }}).join('');
  document.getElementById('sector-output').innerHTML=header+filters+'<div class="news-grid-sector">'+cards+'</div>';
}}
function filterSector(source,btn){{
  document.querySelectorAll('.pill').forEach(p=>p.classList.remove('active'));
  btn.classList.add('active');
  document.querySelectorAll('.scard').forEach(c=>{{c.style.display=(source==='all'||c.dataset.source===source)?'':'none';}});
}}
document.getElementById('sector-sel').addEventListener('change',function(){{if(this.value)fetchSectorNews();}});

// ── Live news (YouTube) ──
var nframe=document.getElementById('nframe'),nload=document.getElementById('nload'),
    nbadge=document.getElementById('nbadge'),curHandle=null;
function nSetLoad(m){{nframe.style.display='none';nload.innerHTML='<div class="news-spinner"></div><span>'+m+'</span>';nload.style.display='flex';nbadge.style.display='none';}}
function nSetErr(m){{nframe.style.display='none';nload.innerHTML='<span>'+m+'</span>';nload.style.display='flex';nbadge.className='nsb error';nbadge.textContent='Unavailable';nbadge.style.display='inline-flex';}}
function loadCh(h){{
  if(curHandle===h)return;
  curHandle=h; nSetLoad('Loading stream…'); nframe.src='about:blank';
  fetch('/api/live-id?handle='+encodeURIComponent(h))
    .then(r=>{{if(!r.ok)throw new Error('HTTP '+r.status);return r.json();}})
    .then(d=>{{
      if(h!==curHandle)return;
      if(d.error||!d.video_id){{nSetErr('Stream unavailable.');return;}}
      nframe.src='https://www.youtube.com/embed/'+d.video_id+'?autoplay=1&rel=0&modestbranding=1';
      nframe.style.display='block';nload.style.display='none';
      nbadge.style.display='inline-flex';
      nbadge.className=d.is_live?'nsb live':'nsb latest';
      nbadge.textContent=d.is_live?'LIVE':'Latest Video';
    }}).catch(()=>{{if(h!==curHandle)return;nSetErr('Could not load stream.');}});
}}
document.getElementById('ntabs').addEventListener('click',function(e){{
  var btn=e.target.closest('.news-tab');if(!btn)return;
  document.querySelectorAll('.news-tab').forEach(t=>t.classList.remove('active'));
  btn.classList.add('active');curHandle=null;loadCh(btn.dataset.handle);
}});
setInterval(refreshRateLimits,8000);
</script>
</body>
</html>"""

# ══════════════════════════════════════════════════════════════════════════════
# ROUTES
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/", methods=["GET","POST"])
def index():
    ticker     = (request.form.get("ticker","AAPL") or "AAPL").strip().upper()
    period     = request.form.get("period","6mo")
    chart_type = request.form.get("chart_type","candlestick")
    ind_raw    = request.form.get("indicators",",".join(DEFAULT_INDICATORS))
    if period not in VALID_PERIODS: period = "6mo"
    if chart_type not in ("candlestick","line"): chart_type = "candlestick"
    active = set(filter(None, ind_raw.split(","))) if ind_raw else DEFAULT_INDICATORS
    graph_html, error = build_chart(ticker, period, chart_type, active)
    return render_page(ticker, period, chart_type, active, graph_html, error, _LOGO_DATA_URI)

@app.route("/api/ai-analysis", methods=["POST"])
def api_ai_analysis():
    body     = request.get_json(force=True) or {}
    ticker   = (body.get("ticker","AAPL") or "AAPL").strip().upper()
    period   = body.get("period","6mo")
    model_id = (body.get("model_id") or "").strip()
    if not model_id: return jsonify({"error": "model_id required"}), 400
    model = next((m for m in AI_MODELS if m["id"] == model_id), None)
    if not model: return jsonify({"error": f"Unknown model: {model_id}"}), 400
    rl = rl_check(model["key"])
    if not rl["available"]:
        reset = rl_next_rpm_reset(model["key"])
        return jsonify({"error": f"Rate limit hit ({model['label']}): RPM {rl['rpm_used']}/{rl['rpm_max']}, RPD {rl['rpd_used']}/{rl['rpd_max']}. RPM resets in {reset}s."}), 429
    if period not in VALID_PERIODS: period = "6mo"
    df, err = fetch_yfinance_data(ticker, period)
    if err: return jsonify({"error": f"Data fetch failed: {err}"}), 502
    if df is None or df.empty: return jsonify({"error": f"No data for '{ticker}'."}), 404
    name = _get_name(ticker)
    try:
        payload = build_analysis_payload(ticker, period, name, df)
        prompt  = build_prompt(payload)
    except Exception as e:
        return jsonify({"error": f"Indicator error: {e}"}), 500
    try:
        analysis = call_openrouter(model_id, prompt)
        rl_record(model["key"])
    except requests.exceptions.HTTPError as e:
        code = e.response.status_code if e.response else 0
        if code == 429: return jsonify({"error": "OpenRouter rate limit. Wait a moment."}), 429
        return jsonify({"error": f"OpenRouter HTTP {code}: {e}"}), 502
    except json.JSONDecodeError as e:
        return jsonify({"error": f"Model returned invalid JSON: {e}"}), 502
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": f"AI error: {e}"}), 500
    return jsonify({"ticker": ticker, "period": period, "model_id": model_id, "analysis": analysis})

@app.route("/api/rate-limits")
def api_rate_limits():
    return jsonify({
        m["key"]: {**rl_check(m["key"]), "rpm_reset_secs": rl_next_rpm_reset(m["key"])}
        for m in AI_MODELS
    })

@app.route("/api/live-id")
def api_live_id():
    handle = request.args.get("handle","").strip()
    if not handle: return jsonify({"error": "missing handle"}), 400
    vid, live = fetch_live_video_id(handle)
    if vid: return jsonify({"video_id": vid, "is_live": live})
    return jsonify({"error": "not found"}), 404

@app.route("/api/news")
def api_news():
    sector_id = request.args.get("sector", "").strip()
    if sector_id not in SECTORS:
        return jsonify({"error": "Invalid sector", "articles": []}), 400
    t0 = time.time()
    articles = fetch_all_news(sector_id)
    elapsed = round(time.time() - t0, 2)
    return jsonify({
        "sector": sector_id,
        "sector_label": SECTORS[sector_id]["label"],
        "count": len(articles),
        "elapsed_seconds": elapsed,
        "articles": articles,
    })

@app.route("/debug")
def debug():
    out, color = [], "#333"
    try:
        df, err = fetch_yfinance_data("AAPL","5d")
        if err: out.append(f"Error: {err}"); color="#c0392b"
        elif df is not None: out.append(f"OK shape:{df.shape}"); out.append(df.tail().to_string())
        else: out.append("No data"); color="#c8860a"
    except Exception: out.append(traceback.format_exc()); color="#c0392b"
    body = "\n".join(out)
    return f"<pre style='background:#f8f7f4;color:{color};padding:24px;font-family:monospace;white-space:pre-wrap;border-left:3px solid {color}'>{body}</pre>"

@app.errorhandler(500)
def e500(e):
    return f"<pre style='background:#f8f7f4;color:#c0392b;padding:24px;font-family:monospace'>500\n\n{traceback.format_exc()}</pre>", 500

if __name__ == "__main__":
    print("=" * 60)
    print("  STARFISH — Live Markets, AI & Sector Intelligence")
    print("  http://127.0.0.1:5000")
    print("=" * 60)
    print()
    print("  pip install flask requests yfinance plotly pandas numpy")
    print("  pip install httpx beautifulsoup4 lxml")
    print()
    print("  export OPEN_ROUTER_API_KEY=your_key_here")
    print()
    app.run(debug=False, host="0.0.0.0", port=5000)

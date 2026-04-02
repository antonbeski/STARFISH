import os
import re
import time
import traceback
import requests
import random
import json
import threading
import base64
import numpy as np
import pandas as pd
from collections import deque
from flask import Flask, request, jsonify
import yfinance as yf
import plotly.graph_objects as go
import plotly.offline as pyo
from plotly.subplots import make_subplots
import httpx
from bs4 import BeautifulSoup
from datetime import datetime
import concurrent.futures

app = Flask(__name__)

# ── LOGO ASSET ───────────────────────────────────────────────────────────────
_LOGO_DATA_URI = ""
_LOGO_SEARCH_PATHS = [
    os.path.join(os.getcwd(), "starfish_logo.jpg"),
    os.path.join(os.getcwd(), "..", "starfish_logo.jpg"),
    os.path.join(os.path.dirname(__file__), "starfish_logo.jpg"),
    os.path.join(os.path.dirname(__file__), "..", "starfish_logo.jpg"),
]
for _p in _LOGO_SEARCH_PATHS:
    if os.path.exists(_p):
        try:
            with open(_p, "rb") as _f:
                _LOGO_DATA_URI = "data:image/jpeg;base64," + base64.b64encode(_f.read()).decode()
            break
        except: pass

# ── OpenRouter AI config ─────────────────────────────────────────────────────
OPEN_ROUTER_API_KEY = os.environ.get("OPEN_ROUTER_API_KEY", "")

AI_MODELS = [
    {"id": "deepseek/deepseek-r1",              "key": "deepseek", "label": "DeepSeek R1",   "desc": "Chain-of-thought reasoning", "color": "#111"},
    {"id": "meta-llama/llama-3.3-70b-instruct", "key": "llama",    "label": "Llama 3.3 70B", "desc": "Fast & balanced",            "color": "#111"},
    {"id": "qwen/qwen-2.5-coder-32b-instruct",  "key": "qwen",     "label": "Qwen 2.5 Coder","desc": "Quantitative focus",         "color": "#111"},
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
    {"id": "skynews",   "handle": "SkyNews",   "label": "Sky News",        "lang": "EN", "region": "UK",     "video_id": "9AuqewiXiGE"},
    {"id": "aljazeera", "handle": "AJE",       "label": "Al Jazeera",      "lang": "EN", "region": "Global", "video_id": "-uThR9Xn994"},
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
    except: pass
    if not live:
        try:
            r2 = _get(f"https://www.youtube.com/@{handle}/videos")
            ids = list(dict.fromkeys(re.findall(r'"videoId"\s*:\s*"([A-Za-z0-9_-]{11})"', r2.text)))
            if ids: vid, live = ids[0], False
        except: pass
    return vid, live

POPULAR_STOCKS = [("AAPL","Apple"), ("GOOGL","Google"), ("MSFT","Microsoft"), ("TSLA","Tesla"),
                  ("AMZN","Amazon"), ("NVDA","NVIDIA"), ("META","Meta")]
PERIODS = [("1mo","1 Month"), ("3mo","3 Months"), ("6mo","6 Months"), ("1y","1 Year"), ("2y","2 Years"), ("5y","5 Years")]
VALID_PERIODS = {p[0] for p in PERIODS}
INDICATORS = [("sma","SMA"), ("bb","Bollinger"), ("rsi","RSI"), ("macd","MACD"), ("vol","Volume")]

# ── Sector configuration ──────────────────────────────────────────────────────
SECTORS = {
    "communication-services": {"label": "Communication Services", "sub": "Telecom · Media · Internet", "key": "XLC", "keywords": ["telecom","media","streaming","meta","alphabet","disney"]},
    "consumer-discretionary": {"label": "Consumer Discretionary", "sub": "Retail · Autos · Leisure", "key": "XLY", "keywords": ["amazon","tesla","nike","retail","auto"]},
    "consumer-staples": {"label": "Consumer Staples", "sub": "Food · Beverages · Essentials", "key": "XLP", "keywords": ["walmart","costco","pepsi","coca-cola","staples"]},
    "energy": {"label": "Energy", "sub": "Oil · Gas · Renewables", "key": "XLE", "keywords": ["oil","gas","exxon","chevron","renewables"]},
    "financials": {"label": "Financials", "sub": "Banks · Insurance · Fintech", "key": "XLF", "keywords": ["bank","jpmorgan","visa","goldman","insurance"]},
    "health-care": {"label": "Health Care", "sub": "Pharma · Biotech · Hospitals", "key": "XLV", "keywords": ["pharma","biotech","pfizer","healthcare","moderna"]},
    "industrials": {"label": "Industrials", "sub": "Aerospace · Machinery · Logistics", "key": "XLI", "keywords": ["boeing","logistics","aerospace","machinery"]},
    "information-technology": {"label": "Information Technology", "sub": "Software · Hardware · Chips", "key": "XLK", "keywords": ["apple","microsoft","nvidia","software","semiconductor"]},
    "materials": {"label": "Materials", "sub": "Chemicals · Metals · Mining", "key": "XLB", "keywords": ["mining","metals","chemical","commodity"]},
    "real-estate": {"label": "Real Estate", "sub": "Property · REITs", "key": "XLRE", "keywords": ["reit","property","real estate"]},
    "utilities": {"label": "Utilities", "sub": "Power · Water · Gas", "key": "XLU", "keywords": ["power","utilities","electric","water"]},
}

# ── Scrapers ──────────────────────────────────────────────────────────────────
SCRAPE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

def parse_relative_time(text):
    if not text: return ""
    text = text.strip()
    if re.match(r"\d{4}-\d{2}-\d{2}", text):
        try: return datetime.strptime(text[:10], "%Y-%m-%d").strftime("%b %d, %Y")
        except: return text
    return text[:60]

def _rss_scrape(url, source, sector_id, client):
    results = []
    try:
        r = client.get(url, timeout=8)
        soup = BeautifulSoup(r.text, "xml")
        keywords = SECTORS[sector_id].get("keywords", [])
        for item in soup.find_all("item"):
            title = item.find("title"); link = item.find("link"); pub_date = item.find("pubDate")
            if not title or not link: continue
            title_text = title.get_text(strip=True)
            if keywords and not any(kw in title_text.lower() for kw in keywords): continue
            href = link.get_text(strip=True)
            pub = pub_date.get_text(strip=True) if pub_date else ""
            try:
                dt = datetime.strptime(pub[:25], "%a, %d %b %Y %H:%M:%S")
                pub = dt.strftime("%b %d, %Y %H:%M")
            except: pub = pub[:30]
            results.append({"title": title_text, "url": href, "source": source, "published": pub, "sector": sector_id})
            if len(results) >= 10: break
    except: pass
    return results

def scrape_yahoo_finance(s, c): return _rss_scrape("https://finance.yahoo.com/news/rssindex","Yahoo Finance",s,c)
def scrape_seeking_alpha(s, c): return _rss_scrape(f"https://seekingalpha.com/symbol/{SECTORS[s]['key']}/news.xml", "Seeking Alpha", s, c)
def scrape_cnbc(s, c): return _rss_scrape("https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=10000664","CNBC",s,c)
def scrape_benzinga(s, c): return _rss_scrape("https://www.benzinga.com/feeds/news","Benzinga",s,c)

def fetch_all_news(sector_id):
    scrapers = [scrape_yahoo_finance, scrape_cnbc, scrape_benzinga, scrape_seeking_alpha]
    all_results = []
    with httpx.Client(headers=SCRAPE_HEADERS, follow_redirects=True, timeout=10) as client:
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
            for future in concurrent.futures.as_completed({executor.submit(fn, sector_id, client): fn for fn in scrapers}):
                try: all_results.extend(future.result())
                except: pass
    seen = set(); unique = []
    for item in all_results:
        key = re.sub(r"[^a-z0-9]", "", item["title"].lower())[:60]
        if key not in seen: seen.add(key); unique.append(item)
    unique.sort(key=lambda x: x.get("published", ""), reverse=True)
    return unique[:40]

# ── Data Fetching ─────────────────────────────────────────────────────────────
def fetch_yfinance_data(ticker, period):
    try:
        tk = yf.Ticker(ticker)
        df = tk.history(period=period)
        if df.empty: return None, "No data found."
        return df, None
    except Exception as e: return None, str(e)

def _get_name(ticker):
    try: return yf.Ticker(ticker).info.get("shortName", ticker)
    except: return ticker

# ── Technical Indicators ──────────────────────────────────────────────────────
def calc_sma(c, w): return c.rolling(w).mean()
def calc_ema(c, w): return c.ewm(span=w, adjust=False).mean()
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

# ── AI Analysis Engine ───────────────────────────────────────────────────────
def _sf(v, d=4):
    try: x = float(v); return None if np.isnan(x) else round(x, d)
    except: return None

def build_analysis_payload(ticker, period, name, df):
    c = df["Close"].squeeze().dropna()
    h = df["High"].squeeze(); lo = df["Low"].squeeze()
    n = len(c)
    cur = _sf(c.iloc[-1]); prev = _sf(c.iloc[-2]) if n > 1 else cur
    hi52 = _sf(c.tail(252).max()); lo52 = _sf(c.tail(252).min())
    macd_d = {}
    if n >= 27:
        ml, sl, hl = calc_macd(c)
        macd_d = {"macd": _sf(ml.iloc[-1]), "signal": _sf(sl.iloc[-1]), "histogram": _sf(hl.iloc[-1])}
    bb_d = {}
    if n >= 20:
        bbu, bbm, bbl = calc_bb(c)
        bb_d = {"upper": _sf(bbu.iloc[-1]), "mid": _sf(bbm.iloc[-1]), "lower": _sf(bbl.iloc[-1])}
    return {
        "ticker": ticker, "name": name, "period": period,
        "price": {"current": cur, "prev": prev, "52w_high": hi52, "52w_low": lo52},
        "rsi": _sf(calc_rsi(c).iloc[-1]) if n>=15 else None,
        "macd": macd_d, "bb": bb_d,
        "ma": {"sma20": _sf(calc_sma(c,20).iloc[-1]) if n>=20 else None, "sma50": _sf(calc_sma(c,50).iloc[-1]) if n>=50 else None}
    }

def build_prompt(p):
    return f"Analyze {p['name']} ({p['ticker']}). Price: {p['price']['current']} (52W: {p['price']['52w_low']}-{p['price']['52w_high']}). RSI: {p['rsi']}. MACD: {p['macd']}. MA: {p['ma']}. Provide BUY/SELL/HOLD verdict, confidence, targets, and 4-6 sentences of technical rationale. Output strictly JSON: {{\"verdict\": \"...\", \"confidence\": \"...\", \"time_horizon\": \"...\", \"price_targets\": {{\"entry\":0,\"stop_loss\":0,\"target_1\":0,\"target_2\":0}}, \"technical_analysis\": \"...\", \"summary\": \"...\"}}"

def call_openrouter(model_id, prompt):
    if not OPEN_ROUTER_API_KEY: raise ValueError("API KEY missing")
    r = requests.post("https://openrouter.ai/api/v1/chat/completions",
        headers={"Authorization": f"Bearer {OPEN_ROUTER_API_KEY}", "Content-Type": "application/json"},
        json={"model": model_id, "messages": [{"role": "user", "content": prompt}], "temperature": 0.1}, timeout=60)
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"].strip()

# ── Chart Builder ─────────────────────────────────────────────────────────────
def build_chart(ticker, period, chart_type, indicators):
    data, err = fetch_yfinance_data(ticker, period)
    if err: return None, err
    cl = data["Close"]; hi = data["High"]; lo = data["Low"]; op = data["Open"]; vol = data.get("Volume")
    fig = make_subplots(rows=2 if "vol" in indicators else 1, cols=1, shared_xaxes=True, vertical_spacing=0.05, row_heights=[0.8, 0.2] if "vol" in indicators else [1])
    if chart_type == "candlestick":
        fig.add_trace(go.Candlestick(x=data.index, open=op, high=hi, low=lo, close=cl, name="Price", increasing_line_color="#000", decreasing_line_color="#666"), row=1, col=1)
    else:
        fig.add_trace(go.Scatter(x=data.index, y=cl, mode="lines", name="Price", line=dict(color="#000", width=2)), row=1, col=1)
    if "vol" in indicators and vol is not None:
        fig.add_trace(go.Bar(x=data.index, y=vol, name="Volume", marker_color="#aaa"), row=2, col=1)
    if "sma" in indicators:
        for w in [20, 50]:
            if len(cl) > w:
                fig.add_trace(go.Scatter(x=data.index, y=calc_sma(cl, w), mode="lines", name=f"SMA {w}", line=dict(width=1, dash="dot")), row=1, col=1)
    fig.update_layout(height=500, template="plotly_white", margin=dict(l=20,r=20,t=20,b=20), showlegend=False, xaxis_rangeslider_visible=False)
    return pyo.plot(fig, output_type="div", include_plotlyjs=False), None

# ── HTML Renderer ─────────────────────────────────────────────────────────────
def render_page(ticker, period, chart_type, active_indicators, graph_html, error, logo_uri):
    popts = "".join(f'<option value="{v}" {"selected" if v==period else ""}>{lbl}</option>' for v,lbl in PERIODS)
    chips = "".join(f'<span class="chip {"active" if s==ticker else ""}" onclick="setTicker(\'{s}\')">{s}</span>' for s,_ in POPULAR_STOCKS)
    ichips = "".join(f'<span class="ind-chip {"active" if k in active_indicators else ""}" data-ind="{k}" onclick="toggleInd(this)">{lbl}</span>' for k,lbl in INDICATORS)
    ntabs = "".join(f'<button class="news-tab" data-handle="{ch["handle"]}">{ch["label"]}</button>' for ch in NEWS_CHANNELS)
    sector_tiles = "".join(f'<button class="s-tile" onclick="selectAndFetch(\'{k}\')"><span class="s-tile-key">{v["key"]}</span><span class="s-tile-name">{v["label"]}</span></button>' for k,v in SECTORS.items())
    ai_cards_html = "".join(f'<div class="ai-model-card" data-model="{m["id"]}" onclick="selectModel(this)">{m["label"]}</div>' for m in AI_MODELS)
    
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
    <title>STARFISH</title>
    <link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;700&family=DM+Mono&family=Syne:wght@700;800&display=swap" rel="stylesheet">
    <script src="https://cdn.plot.ly/plotly-2.27.0.min.js"></script>
    <style>
        :root {{ --bg: #ffffff; --text: #000000; --paper: #f8f7f4; --border: #e5e5e5; --r: 12px; }}
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: 'DM Sans', sans-serif; background: var(--bg); color: var(--text); line-height: 1.6; }}
        header {{ display: flex; align-items: center; justify-content: space-between; padding: 1.5rem 2rem; border-bottom: 2px solid #000; sticky: top; background: #fff; z-index: 100; }}
        .logo-wrap {{ display: flex; align-items: center; gap: 1rem; }}
        .logo-text {{ font-family: 'Syne', sans-serif; font-size: 1.8rem; font-weight: 800; letter-spacing: -1px; }}
        .nav-tabs {{ display: flex; gap: 2rem; margin: 0 2rem; }}
        .nav-tab {{ background: none; border: none; font: inherit; cursor: pointer; opacity: 0.5; padding: 0.5rem 0; border-bottom: 2px solid transparent; transition: 0.2s; font-weight: 600; text-transform: uppercase; letter-spacing: 1px; font-size: 0.8rem; }}
        .nav-tab.active {{ opacity: 1; border-color: #000; }}
        
        main {{ max-width: 1200px; margin: 0 auto; padding: 2rem; }}
        .tab-panel {{ display: none; }} .tab-panel.active {{ display: block; }}
        
        .ticker-wrap {{ background: #000; color: #fff; padding: 0.5rem 0; overflow: hidden; white-space: nowrap; font-family: 'DM Mono'; font-size: 0.7rem; }}
        .ticker-scroll {{ display: inline-block; animation: tick 30s linear infinite; }}
        @keyframes tick {{ from {{ transform: translateX(100vw); }} to {{ transform: translateX(-100%); }} }}
        
        .panel {{ background: var(--paper); border: 2px solid #000; padding: 2rem; border-radius: var(--r); margin-bottom: 2rem; }}
        .grid {{ display: grid; grid-template-columns: 2fr 1fr; gap: 2rem; }}
        
        input, select {{ background: #fff; border: 2px solid #000; padding: 0.8rem; border-radius: 4px; font-family: inherit; width: 100%; }}
        .btn {{ background: #000; color: #fff; border: none; padding: 0.8rem 1.5rem; border-radius: 4px; cursor: pointer; font-weight: 700; text-transform: uppercase; letter-spacing: 1px; }}
        
        .chips {{ display: flex; flex-wrap: wrap; gap: 0.5rem; margin-top: 1rem; }}
        .chip {{ padding: 0.3rem 0.8rem; border: 1px solid #000; border-radius: 20px; font-size: 0.8rem; cursor: pointer; }}
        .chip.active {{ background: #000; color: #fff; }}
        .ind-chip {{ padding: 0.3rem 0.8rem; border: 1px solid #000; border-radius: 4px; font-size: 0.7rem; cursor: pointer; font-family: 'DM Mono'; text-transform: uppercase; }}
        .ind-chip.active {{ background: #eee; border-style: dashed; }}
        
        .chart-wrap {{ border: 2px solid #000; border-radius: var(--r); overflow: hidden; background: #fff; min-height: 400px; }}
        
        .s-grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 1rem; }}
        .s-tile {{ background: #fff; border: 2px solid #000; padding: 1.5rem; text-align: left; cursor: pointer; transition: 0.2s; }}
        .s-tile:hover {{ background: #000; color: #fff; }}
        .s-tile-key {{ display: block; font-family: 'DM Mono'; font-size: 0.7rem; opacity: 0.6; margin-bottom: 0.5rem; }}
        .s-tile-name {{ font-weight: 700; font-family: 'Syne'; }}
        
        .news-grid-sector {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 1rem; margin-top: 2rem; }}
        .scard {{ border: 1px solid #000; padding: 1.5rem; position: relative; background: #fff; }}
        .scard-src {{ display: block; font-size: 0.6rem; text-transform: uppercase; font-weight: 700; margin-bottom: 0.5rem; border-bottom: 1px solid #000; width: fit-content; }}
        .scard-title a {{ color: #000; text-decoration: none; font-weight: 700; font-family: 'Syne'; font-size: 1.1rem; }}
        .scard-date {{ font-size: 0.7rem; opacity: 0.5; margin-top: 1rem; display: block; font-family: 'DM Mono'; }}
        
        .ai-model-card {{ border: 2px solid #000; padding: 1rem; margin-bottom: 1rem; cursor: pointer; font-weight: 700; text-align: center; }}
        .ai-model-card.selected {{ background: #000; color: #fff; }}
        #ai-result {{ border: 2px solid #000; padding: 2rem; margin-top: 1rem; background: #fff; display: none; }}
        #ai-result.show {{ display: block; }}
        
        footer {{ text-align: center; padding: 6rem; border-top: 2px solid #000; margin-top: 4rem; background: var(--paper); }}
        .f-name {{ font-family: 'Syne'; font-size: 5rem; font-weight: 800; letter-spacing: -2px; }}
    </style>
</head>
<body>
    <div class="ticker-wrap"><div class="ticker-scroll">
        {' '.join(f'<span>{v["key"]} {v["label"]} • </span>' for v in SECTORS.values())} 
        ANALYSIS BY ANTON BESKI • LIVE MARKET DATA • ARTIFICIAL INTELLIGENCE TRADING SYSTEMS • 
    </div></div>
    <header>
        <div class="logo-wrap">
            <img src="{logo_uri}" height="40" style="filter:grayscale(1) contrast(150%)">
            <div class="logo-text">STARFISH</div>
        </div>
        <div class="nav-tabs">
            <button class="nav-tab active" onclick="switchTab('tab-stock', this)">Stocks</button>
            <button class="nav-tab" onclick="switchTab('tab-sector', this)">Sectors</button>
            <button class="nav-tab" onclick="switchTab('tab-live', this)">Live News</button>
        </div>
        <div style="font-family:'DM Mono'; font-size:0.7rem; font-weight:700;">PRO / TERMINAL v4</div>
    </header>
    <main>
        <div id="tab-stock" class="tab-panel active">
            <div class="panel">
                <form action="/" method="POST" id="main-form">
                    <div class="grid" style="grid-template-columns: 1.5fr 1fr 1fr auto; align-items: end;">
                        <div><label style="display:block; font-size:0.6rem; font-weight:700; margin-bottom:0.5rem; letter-spacing:1px;">TICKER ENTRY</label><input type="text" name="ticker" id="ticker" value="{ticker}"></div>
                        <div><label style="display:block; font-size:0.6rem; font-weight:700; margin-bottom:0.5rem; letter-spacing:1px;">TIMEFRAME</label><select name="period">{popts}</select></div>
                        <div><label style="display:block; font-size:0.6rem; font-weight:700; margin-bottom:0.5rem; letter-spacing:1px;">VIEWPORT</label><select name="chart_type"><option value="candlestick">Candlesticks</option><option value="line">Line Graph</option></select></div>
                        <button class="btn">Execute</button>
                    </div>
                    <div class="chips">{chips}</div>
                    <div class="chips" style="border-top:1px solid #000; padding-top:1rem; margin-top:1.5rem;">
                        <span style="font-size:0.6rem; font-weight:700; text-transform:uppercase; letter-spacing:1px; margin-right:1rem;">Visual Engines</span>
                        {ichips}
                    </div>
                    <input type="hidden" name="indicators" id="inds-h" value="{','.join(active_indicators)}">
                </form>
            </div>
            <div class="chart-wrap">{graph_html or f'<div style="padding:4rem; text-align:center;">{error or "Ready for prompt..."}</div>'}</div>
            <div class="panel" style="margin-top:2rem;">
                <h3 style="font-family:'Syne'; margin-bottom:1.5rem;">AI CO-PILOT ANALYSIS</h3>
                <div style="display:grid; grid-template-columns:1fr 1fr 1fr; gap:1rem; margin-bottom:1.5rem;">
                    {ai_cards_html}
                </div>
                <button class="btn" style="width:100%; border:2px solid #000;" id="btn-ai" onclick="runAnalysis()">Trigger Intelligence Sync</button>
                <div id="ai-result"></div>
            </div>
        </div>
        
        <div id="tab-sector" class="tab-panel">
            <div class="panel">
                <h3 style="font-family:'Syne';">SECTOR INTELLIGENCE</h3>
                <p style="margin-bottom:2rem; opacity:0.6; font-size:0.8rem;">Multisource scanning across GICS taxonomy.</p>
                <div class="s-grid">{sector_tiles}</div>
                <div id="sector-output"></div>
            </div>
        </div>
        
        <div id="tab-live" class="tab-panel">
            <div class="panel">
                <h3 style="font-family:'Syne';">GLOBAL NEWS TERMINAL</h3>
                <div class="chips" style="margin:2rem 0;">{ntabs}</div>
                <div id="nframe-wrap" style="position:relative; padding-top:56.25%; border:4px solid #000; background:#000;">
                    <iframe id="nframe" style="position:absolute; inset:0; width:100%; height:100%;" frameborder="0" allowfullscreen></iframe>
                </div>
            </div>
        </div>
    </main>
    <footer>
        <div style="font-size:0.7rem; letter-spacing:5px; opacity:0.5; margin-bottom:1rem; font-weight:700;">SYSTEM ARCHITECTURE BY</div>
        <div class="f-name">ANTON BESKI</div>
    </footer>
    <script>
        var TICKER = {json.dumps(ticker)};
        var activeInds = {json.dumps(list(active_indicators))};
        function switchTab(id, btn) {{
            document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
            document.querySelectorAll('.nav-tab').forEach(t => t.classList.remove('active'));
            document.getElementById(id).classList.add('active');
            btn.classList.add('active');
        }}
        function setTicker(s) {{ document.getElementById('ticker').value = s; document.getElementById('main-form').submit(); }}
        function toggleInd(el) {{
            var k = el.dataset.ind;
            var idx = activeInds.indexOf(k);
            if(idx > -1) activeInds.splice(idx, 1); else activeInds.push(k);
            document.getElementById('inds-h').value = activeInds.join(',');
            document.getElementById('main-form').submit();
        }}
        var selModelId = "";
        function selectModel(card) {{
            document.querySelectorAll('.ai-model-card').forEach(c => {{
                c.classList.remove('selected');
                c.style.background = ""; c.style.color = "";
            }});
            card.classList.add('selected');
            selModelId = card.dataset.model;
        }}
        function runAnalysis() {{
            if(!selModelId) {{ alert("Select model"); return; }}
            var res = document.getElementById('ai-result');
            res.innerHTML = "Syncing with AI core..."; res.classList.add('show');
            fetch('/api/ai-analysis', {{ method:'POST', body:JSON.stringify({{ticker:TICKER, model_id:selModelId}}) }})
            .then(r => r.json()).then(d => {{
                if(d.error) {{ res.innerHTML = d.error; return; }}
                var a = d.analysis;
                res.innerHTML = `<h2 style="font-family:'Syne'; border-bottom:4px solid #000; padding-bottom:1rem; margin-bottom:1.5rem;">${{a.verdict}}</h2>
                <p style="font-size:1.2rem; font-weight:700; margin-bottom:2rem;">${{a.summary}}</p>
                <div style="display:grid; grid-template-columns:1fr 1fr; gap:2rem;">
                    <div><h4 style="text-transform:uppercase; font-size:0.7rem; border-bottom:1px solid #000;">Technical Thesis</h4><p style="font-size:0.9rem; padding-top:1rem;">${{a.technical_analysis}}</p></div>
                    <div><h4 style="text-transform:uppercase; font-size:0.7rem; border-bottom:1px solid #000;">Strike Zone</h4>
                        <div style="padding-top:1rem; font-family:'DM Mono'; font-size:0.9rem;">
                            ENTRY: ${{a.price_targets.entry}}<br>TARGET: ${{a.price_targets.target_1}}<br>STOP: ${{a.price_targets.stop_loss}}
                        </div>
                    </div>
                </div>`;
            }});
        }}
        function selectAndFetch(k) {{
            document.getElementById('sector-output').innerHTML = '<div style="padding:2rem; font-family:\'DM Mono\';">SCANNIG GICS CORE...</div>';
            fetch('/api/news?sector='+k).then(r => r.json()).then(d => {{
                var html = `<div class="news-grid-sector">`;
                d.articles.forEach(a => {{
                    html += `<div class="scard"><span class="scard-src">${{a.source}}</span><div class="scard-title"><a href="${{a.url}}" target="_blank">${{a.title}}</a></div><span class="scard-date">${{a.published}}</span></div>`;
                }});
                html += `</div>`;
                document.getElementById('sector-output').innerHTML = html;
            }});
        }}
        document.querySelectorAll('.news-tab').forEach(btn => {{
            btn.onclick = function() {{
                fetch('/api/live-id?handle='+this.dataset.handle).then(r => r.json()).then(d => {{
                    document.getElementById('nframe').src = "https://www.youtube.com/embed/"+d.video_id+"?autoplay=1&modestbranding=1&rel=0";
                }});
            }}
        }});
    </script>
</body>
</html>"""

# ── Routes ───────────────────────────────────────────────────────────────────
@app.route("/", methods=["GET","POST"])
def index():
    ticker = (request.form.get("ticker", "AAPL") or "AAPL").strip().upper()
    period = request.form.get("period", "6mo")
    chart_type = request.form.get("chart_type", "candlestick")
    inds_raw = request.form.get("indicators", "sma,vol")
    active_indicators = set(filter(None, inds_raw.split(",")))
    graph_html, error = build_chart(ticker, period, chart_type, active_indicators)
    return render_page(ticker, period, chart_type, active_indicators, graph_html, error, _LOGO_DATA_URI)

@app.route("/api/ai-analysis", methods=["POST"])
def api_ai_analysis():
    body = request.get_json(force=True) or {}
    ticker = (body.get("ticker", "AAPL")).strip().upper()
    model_id = body.get("model_id")
    df, err = fetch_yfinance_data(ticker, "6mo")
    if err: return jsonify({"error": err}), 400
    name = _get_name(ticker)
    payload = build_analysis_payload(ticker, "6mo", name, df)
    prompt = build_prompt(payload)
    try:
        raw = call_openrouter(model_id, prompt)
        return jsonify({"ticker": ticker, "analysis": json.loads(raw)})
    except Exception as e: return jsonify({"error": str(e)}), 500

@app.route("/api/news")
def api_news():
    sector_id = request.args.get("sector", "").strip()
    if sector_id not in SECTORS: return jsonify({"articles": []})
    articles = fetch_all_news(sector_id)
    return jsonify({"articles": articles})

@app.route("/api/live-id")
def api_live_id():
    handle = request.args.get("handle", "").strip()
    vid, live = fetch_live_video_id(handle)
    return jsonify({"video_id": vid, "is_live": live})

if __name__ == "__main__":
    app.run(debug=True, port=int(os.environ.get("PORT", 5000)))

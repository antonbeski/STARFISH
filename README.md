<img width="1202" height="328" alt="Screenshot 2026-04-24 170405" src="https://github.com/user-attachments/assets/1901aa96-2494-4d01-b6fb-3f51217059a4" />
<img width="1202" height="328" alt="Screenshot 2026-04-24 170405" src="https://github.com/user-attachments/assets/835f190f-eaf1-408a-a4f6-d7ac70e47d6f" />
#  STARFISH — Market dynamics
<img width="100" height="100" alt="c9ca0d0ddf28146de5d730585650eee7" src="https://github.com/user-attachments/assets/6b34cfc1-986e-43ce-8105-8c3423338fe2" />


<div align="center">

![Python](https://img.shields.io/badge/Python-3.9%2B-3776AB?style=for-the-badge&logo=python&logoColor=white)
![Flask](https://img.shields.io/badge/Flask-2.x-000000?style=for-the-badge&logo=flask&logoColor=white)
![Plotly](https://img.shields.io/badge/Plotly-Interactive-3F4F75?style=for-the-badge&logo=plotly&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-green?style=for-the-badge)
![Status](https://img.shields.io/badge/Status-Active-brightgreen?style=for-the-badge)

**Stocks · AI Analysis · Sectors · Live News · Macro Data · Satellite Intelligence**

*A full-stack, single-file market intelligence dashboard with dark premium UI, multi-model AI analysis, real-time FRED macroeconomic data, Google Trends sentiment, live AIS vessel tracking, and satellite target mapping across 11 global sectors.*

[Features](#-features) · [Architecture](#-architecture) · [Installation](#-installation) · [Configuration](#-configuration) · [API Reference](#-api-reference) · [Screenshots](#-screenshots)

</div>

---

##  Overview

STARFISH is a self-contained Flask web application that aggregates financial market intelligence from over **10 live data sources** into a single, dark-themed dashboard. It supports US and Indian (NSE/BSE) equities, provides multi-model AI analysis via OpenRouter, and surfaces alternative data signals — from shipping traffic to satellite imagery targets — that institutional analysts rely on.

The entire platform ships as a **single Python file** (`index.py`), requiring no database, no frontend build step, and no external deployment pipeline. Spin it up locally in under two minutes.

---

##  Features

###  Interactive Charting Engine
- **Candlestick & Line charts** rendered via Plotly with a custom dark theme
- **5 overlay indicators**: SMA (20/50/200), Bollinger Bands, RSI (14), MACD (12/26/9), Volume bars
- **Time range selector**: 1M · 3M · 6M · 1Y · 2Y · 5Y
- Fully responsive, drag-to-pan, hover-unified tooltips
- **USD and INR currency detection** — appends `.NS` for NSE / `.BO` for BSE stocks
<img width="1202" height="328" alt="Screenshot 2026-04-24 170405" src="https://github.com/user-attachments/assets/8caec4c4-b0d8-4d58-89a4-56a2a8b517e1" />
<img width="1175" height="582" alt="Screenshot 2026-04-24 170433" src="https://github.com/user-attachments/assets/306b4438-4bf9-43ce-abe6-76546630a146" />

###  Multi-Model AI Analysis
Three LLMs available via [OpenRouter](https://openrouter.ai), selectable per analysis request:

| Model | Key | Strength |
|---|---|---|
| DeepSeek R1 | `deepseek/deepseek-r1` | Chain-of-thought reasoning |
| Llama 3.3 70B | `meta-llama/llama-3.3-70b-instruct` | Fast & balanced |
| Qwen3 Coder | `qwen/qwen3-coder` | Quantitative focus |

The AI prompt is constructed from **12 technical indicators**, OHLCV data, FRED macro, Google Trends, shipping context, and company fundamentals — giving each model a rich, structured financial brief.
<img width="1170" height="314" alt="Screenshot 2026-04-24 170455" src="https://github.com/user-attachments/assets/367a2c83-9b74-4e8b-ae01-9d00b349f8ee" />
<img width="1145" height="594" alt="Screenshot 2026-04-24 170823" src="https://github.com/user-attachments/assets/6cd35ac7-d4d3-4343-92f1-6ced164af853" />
<img width="1096" height="563" alt="Screenshot 2026-04-24 170852" src="https://github.com/user-attachments/assets/9bdce4a1-acc3-484c-a6cd-c8f741441e67" />
<img width="1092" height="153" alt="Screenshot 2026-04-24 170925" src="https://github.com/user-attachments/assets/49386133-689e-4061-851c-2f165837fd26" />

###  Real-Time Macro Data (FRED)
Pulls 9 key macroeconomic series from the St. Louis Fed public API:

| Series ID | Metric |
|---|---|
| `DFF` | Fed Funds Rate (%) |
| `CPIAUCSL` | CPI YoY (%) |
| `UNRATE` | Unemployment Rate (%) |
| `GDP` | Real GDP QoQ (%) |
| `T10Y2Y` | 10Y-2Y Yield Spread (bps) |
| `DTWEXBGS` | USD Trade-Weighted Index |
| `VIXCLS` | VIX Volatility Index |
| `BAMLH0A0HYM2` | High-Yield Credit Spread (%) |
| `MORTGAGE30US` | 30-Year Mortgage Rate (%) |

Results are cached with a 1-hour TTL and fetched concurrently using `ThreadPoolExecutor`.

###  Live News Aggregation
Multi-source financial RSS scraper fetching from **7 outlets** concurrently:
- Yahoo Finance, CNBC, MarketWatch, Benzinga, Financial Times, Wall Street Journal, Reuters, Seeking Alpha

News is filtered by **sector-specific keywords** across 11 GICS-aligned sectors.
<img width="1191" height="415" alt="Screenshot 2026-04-24 171100" src="https://github.com/user-attachments/assets/05966d7f-238c-4472-9ceb-4677106606bf" />

###  Shipping & Macro Context
- **Baltic Dry Index (BDI)** — scraped from public sources as a global trade proxy
- **AIS vessel tracking** — integrates `aisstream.io` WebSocket API for live ship positions
- **Major port monitoring**: Houston, Los Angeles, Rotterdam, Singapore, Shanghai
- `/vessels` page renders a full-screen Leaflet.js map with real-time AIS vessel overlays
  <img width="1157" height="620" alt="Screenshot 2026-04-24 172451" src="https://github.com/user-attachments/assets/3fcca1f8-b975-4083-b654-160642d00b71" />


###  Satellite Intelligence Layer
Each of the 11 sectors includes **30 curated latitude/longitude targets** of key global industrial sites — refineries, steel mills, auto plants, airports, ports — enabling overlay with commercial satellite imagery tools.

Sectors covered: Energy, Materials, Industrials, Consumer Discretionary, Consumer Staples, Health Care, Financials, IT, Communication Services, Real Estate, Utilities.
<img width="1110" height="609" alt="Screenshot 2026-04-24 171142" src="https://github.com/user-attachments/assets/c94f0001-815c-4bc9-a5a0-698b72555bb6" />


---

##  Architecture

```
STARFISH (index.py)
│
├── Flask App (app)
│   ├── GET/POST  /                     → Main dashboard page
│   ├── POST      /api/ai-analysis      → Multi-model AI analysis
│   ├── GET       /api/rate-limits      → Per-model rate limit status
│   ├── GET       /api/live-id          → YouTube live video ID lookup
│   ├── GET       /api/news             → Sector news aggregation
│   ├── GET       /api/macro            → FRED + Baltic Dry data
│   ├── GET       /api/trends           → Google Trends query
│   ├── GET       /api/satellite        → Sector satellite targets
│   ├── GET       /api/ais-key          → AIS stream key status
│   ├── GET       /vessels              → Live vessel tracking map
│   └── GET       /debug                → Data source health check
│
├── Data Layer
│   ├── fetch_yfinance_data()           → OHLCV via Yahoo Finance (v8/v7 fallback)
│   ├── fetch_all_macro()               → FRED macro series (concurrent)
│   ├── fetch_fred_series()             → Single FRED CSV fetch with cache
│   ├── fetch_all_news()                → Multi-source RSS aggregation
│   ├── fetch_google_trends()           → pytrends 3-month interest
│   ├── fetch_shipping_context()        → AIS + port context
│   ├── fetch_baltic_dry()              → BDI scraper
│   └── _get_fundamentals()             → yfinance ticker info
│
├── Technical Analysis (12 Indicators)
│   ├── calc_sma()                      → Simple Moving Average
│   ├── calc_ema()                      → Exponential Moving Average
│   ├── calc_bb()                       → Bollinger Bands (±2σ)
│   ├── calc_rsi()                      → Relative Strength Index
│   ├── calc_macd()                     → MACD + Signal + Histogram
│   ├── calc_atr()                      → Average True Range
│   ├── calc_obv()                      → On-Balance Volume
│   ├── calc_stoch()                    → Stochastic Oscillator %K/%D
│   ├── calc_williams_r()               → Williams %R
│   ├── calc_cmf()                      → Chaikin Money Flow
│   ├── calc_adx()                      → Average Directional Index
│   ├── calc_vwap()                     → Volume-Weighted Average Price
│   └── calc_ichimoku()                 → Ichimoku Cloud (Tenkan/Kijun/Span A&B)
│
├── AI Pipeline
│   ├── build_analysis_payload()        → Assemble structured data dict
│   ├── build_prompt()                  → Construct LLM prompt string
│   └── call_openrouter()               → HTTP POST to OpenRouter API
│
├── Chart Renderer
│   └── build_chart()                   → Plotly subplots (Price + Vol + RSI + MACD)
│
└── Rate Limiter
    ├── rl_check()                      → Sliding window availability check
    ├── rl_record()                     → Record a new request timestamp
    └── rl_next_rpm_reset()             → Seconds until oldest RPM slot expires
```

---

##  Installation

### Prerequisites
- Python 3.9+
- pip

### Quick Start

```bash
# 1. Clone the repository
git clone https://github.com/yourusername/starfish.git
cd starfish

# 2. Install dependencies
pip install flask requests numpy pandas yfinance plotly httpx beautifulsoup4 lxml pytrends fredapi

# 3. Set environment variables (see Configuration below)
export OPEN_ROUTER_API_KEY="your_openrouter_key"
export AISSTREAM_API_KEY="your_aisstream_key"   # optional

# 4. Run the server
python index.py
```

Open your browser at **http://127.0.0.1:5000**

### Docker (optional)

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY index.py .
RUN pip install flask requests numpy pandas yfinance plotly httpx beautifulsoup4 lxml pytrends fredapi
ENV OPEN_ROUTER_API_KEY=""
ENV AISSTREAM_API_KEY=""
EXPOSE 5000
CMD ["python", "index.py"]
```

```bash
docker build -t starfish .
docker run -p 5000:5000 \
  -e OPEN_ROUTER_API_KEY=your_key \
  -e AISSTREAM_API_KEY=your_key \
  starfish
```

---

##  Configuration

### Environment Variables

| Variable | Required | Description |
|---|---|---|
| `OPEN_ROUTER_API_KEY` | **Yes** (for AI) | Your [OpenRouter](https://openrouter.ai) API key |
| `AISSTREAM_API_KEY` | No | [AISStream.io](https://aisstream.io) key for live vessel tracking |

### Rate Limit Tuning

Edit these constants at the top of `index.py`:

```python
RL_RPM = 20    # Requests per minute per AI model
RL_RPD = 200   # Requests per day per AI model
```

### Cache TTLs

```python
_FRED_CACHE_TTL  = 3600   # 1 hour — FRED macro data
_TRENDS_CACHE_TTL = 1800  # 30 min — Google Trends
_AIS_CACHE_TTL   = 600    # 10 min — AIS shipping context
_CACHE_TTL       = 1800   # 30 min — Yahoo Finance session/crumb
```

---

##  API Reference

### `POST /api/ai-analysis`

Trigger a full AI market analysis for a ticker.

**Request body (JSON):**
```json
{
  "ticker":   "AAPL",
  "period":   "6mo",
  "model_id": "deepseek/deepseek-r1"
}
```

**Response:**
```json
{
  "ticker":       "AAPL",
  "period":       "6mo",
  "model_id":     "deepseek/deepseek-r1",
  "analysis":     "## Technical Analysis\n...",
  "data_sources": [
    "FRED Macro (9 series)",
    "Google Trends (3 keywords)",
    "Yahoo Fundamentals",
    "12 Technical Indicators",
    "30-Day OHLCV Chart",
    "Candlestick Pattern Analysis",
    "SPY Correlation"
  ]
}
```

**Error codes:** `400` bad input · `404` no data · `429` rate limited · `500` server error · `502` upstream error

---

### `GET /api/macro`

Returns live FRED macro indicators and Baltic Dry Index.

**Response:**
```json
{
  "macro": {
    "DFF": { "label": "Fed Funds Rate (%)", "value": 5.33, "date": "2025-04-01", "change": 0.0 }
  },
  "baltic_dry": { "value": 1420, "date": "2025-04-22", "source": "BDI" },
  "timestamp": "2025-04-22T10:30:00"
}
```

---

### `GET /api/news?sector=energy`

Fetch latest news articles for a sector. Valid sector IDs: `energy`, `materials`, `industrials`, `consumer-discretionary`, `consumer-staples`, `health-care`, `financials`, `information-technology`, `communication-services`, `real-estate`, `utilities`.

**Response:**
```json
{
  "sector":        "energy",
  "sector_label":  "Energy",
  "count":         24,
  "elapsed_seconds": 1.83,
  "articles": [
    {
      "title":   "Oil prices rise...",
      "source":  "Reuters",
      "url":     "https://...",
      "published": "2 hours ago"
    }
  ]
}
```

---

### `GET /api/satellite?sector=energy`

Returns 30 curated latitude/longitude targets for satellite imagery analysis.

**Response:**
```json
{
  "sector": "energy",
  "targets": [
    { "name": "Exxon Baytown Refinery", "tag": "REFINERY · US", "lat": 29.7355, "lon": -94.9774 }
  ]
}
```

---

### `GET /api/trends?q=NVDA`

Fetches 3-month Google Trends data for a search query.

---

### `GET /api/rate-limits`

Returns live rate limit counters for all AI models.

```json
{
  "deepseek": { "rpm_used": 3, "rpm_max": 20, "rpd_used": 47, "rpd_max": 200, "available": true, "rpm_reset_secs": 42 }
}
```

---

### `GET /api/live-id?handle=@handle`

Looks up the active YouTube live stream video ID for a given channel handle.

---

### `GET /vessels`

Full-page AIS vessel tracking map (requires `AISSTREAM_API_KEY`).

---

### `GET /debug`

Health check: tests Yahoo Finance data fetch and FRED macro series. Returns colored pre-formatted output.

---

##  Technical Indicators — Implementation Notes

| Indicator | Function | Formula Notes |
|---|---|---|
| SMA 20/50/200 | `calc_sma()` | `rolling(w).mean()` on Close |
| EMA | `calc_ema()` | `ewm(span=w, adjust=False).mean()` |
| Bollinger Bands | `calc_bb()` | SMA20 ± 2σ with fillcolor band |
| RSI (14) | `calc_rsi()` | Wilder smoothing via EWMA |
| MACD (12,26,9) | `calc_macd()` | EMA diff + signal + histogram |
| ATR (14) | `calc_atr()` | True Range: max(H-L, \|H-Cp\|, \|L-Cp\|) |
| OBV | `calc_obv()` | Cumulative volume signed by price direction |
| Stochastic %K/%D | `calc_stoch()` | Rolling high/low normalization |
| Williams %R | `calc_williams_r()` | Inverse stochastic |
| CMF (20) | `calc_cmf()` | MFV × Volume / Σ Volume |
| ADX (14) | `calc_adx()` | True directional movement via EWM |
| VWAP | `calc_vwap()` | Cumulative (H+L+C)/3 × V / Cum V |
| Ichimoku | `calc_ichimoku()` | Tenkan (9), Kijun (26), Senkou A & B |
| Support/Resistance | `calc_support_resistance()` | Rolling min/max window peaks |

---

##  Data Sources

| Source | Data | Method |
|---|---|---|
| [Yahoo Finance](https://finance.yahoo.com) | OHLCV, fundamentals | Custom HTTP scraper (v8/v7/library fallback) |
| [FRED — St. Louis Fed](https://fred.stlouisfed.org) | 9 macro series | Public CSV endpoint |
| [OpenRouter](https://openrouter.ai) | LLM inference | REST API |
| [Google Trends](https://trends.google.com) | Search interest | `pytrends` |
| [AISStream.io](https://aisstream.io) | Live vessel positions | WebSocket API |
| Yahoo Finance RSS | Financial news | RSS/XML scraping |
| CNBC, Reuters, FT, MW, Benzinga, WSJ | Financial news | RSS/XML scraping |
| BDI (Baltic Exchange) | Shipping index | Web scraping |

---

##  Dependencies

```
flask
requests
numpy
pandas
yfinance
plotly
httpx
beautifulsoup4
lxml
pytrends
fredapi
```

Install all at once:
```bash
pip install flask requests numpy pandas yfinance plotly httpx beautifulsoup4 lxml pytrends fredapi
```

---

##  Sectors & Satellite Targets

Each sector has 30 globally distributed satellite observation targets (10 US, 10 India, 10 Global):

| Sector ID | Label | ETF Proxy | Key Assets |
|---|---|---|---|
| `energy` | Energy | XLE | Refineries, LNG terminals, oil rigs |
| `materials` | Materials | XLB | Copper mines, steel mills, cement plants |
| `industrials` | Industrials | XLI | Aircraft factories, auto plants, ports |
| `consumer-discretionary` | Consumer Discretionary | XLY | Retail HQs, malls, auto dealers |
| `consumer-staples` | Consumer Staples | XLP | Grocery HQs, food factories, QSR chains |
| `health-care` | Health Care | XLV | Pharma HQs, hospitals, biotech campuses |
| `financials` | Financials | XLF | Bank HQs, exchanges, fintech offices |
| `information-technology` | Information Technology | XLK | Chip fabs, hyperscale data centers |
| `communication-services` | Communication Services | XLC | Broadcast towers, streaming campuses |
| `real-estate` | Real Estate | XLRE | REIT portfolios, data center REITs |
| `utilities` | Utilities | XLU | Power stations, water treatment, grid |

---

##  Security Notes

- The `OPEN_ROUTER_API_KEY` is read from environment variables and **never embedded in source code or HTML responses**
- The `AISSTREAM_API_KEY` is served only via the same-origin `/api/ais-key` endpoint, never injected into public HTML
- All external requests include a realistic `User-Agent` header pool to avoid bot detection
- Session and crumb caches are stored in-process memory only (no disk persistence)

---

##  Yahoo Finance Scraper Notes

Yahoo Finance periodically changes their authentication flow. STARFISH implements a **3-tier fallback**:

1. **v8 API** — `/v8/finance/chart/` with crumb authentication
2. **v7 API** — `/v7/finance/download/` CSV endpoint
3. **yfinance library** — official Python library as last resort

Crumbs are refreshed automatically when they expire (30-minute TTL), and the session rotates through a pool of 3 user agents.

---

##  Contributing

Contributions are welcome. Please:

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/my-feature`
3. Make changes in `index.py` (or split into modules if refactoring)
4. Test your changes: `python index.py` → verify `/debug` passes
5. Submit a pull request with a clear description

### Areas for Contribution
- Add more AI models to the `AI_MODELS` list
- Add additional FRED series to `FRED_SERIES`
- Expand sector news sources
- Add more satellite targets per sector
- WebSocket-based live price streaming
- Persistent caching (Redis / SQLite)

---

## 📄 License

This project is licensed under the MIT License. See `LICENSE` for details.

---

##  Acknowledgements

- [Yahoo Finance](https://finance.yahoo.com) for OHLCV data
- [FRED — Federal Reserve Bank of St. Louis](https://fred.stlouisfed.org) for macroeconomic series
- [OpenRouter](https://openrouter.ai) for multi-model LLM routing
- [Plotly](https://plotly.com) for interactive charting
- [AISStream.io](https://aisstream.io) for vessel tracking

---

<div align="center">

Built with ❤️ — *Stocks · AI Analysis · Sectors · Live News*

</div>

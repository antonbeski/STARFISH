"""
STARFISH — Market Dynamics
Stocks · AI Analysis · Sectors · Live News · Alpaca Live Trading
"""

import os
import base64
import re
import time
import traceback
import requests
import random
import json
import threading
import math
import numpy as np
import pandas as pd
from collections import deque
from datetime import datetime, timedelta
from urllib.parse import quote_plus
import concurrent.futures
 
import httpx
from bs4 import BeautifulSoup
from flask import Flask, request, jsonify, render_template_string
import yfinance as yf
import plotly.graph_objects as go
import plotly.offline as pyo
from plotly.subplots import make_subplots
import websocket

app = Flask(__name__)

# ══════════════════════════════════════════════════════════════════════════════
# ALPACA PAPER TRADING CONFIGURATION
# ══════════════════════════════════════════════════════════════════════════════
ALPACA_API_KEY    = os.environ.get("ALPACA_API_KEY", "")
ALPACA_SECRET_KEY = os.environ.get("ALPACA_SECRET_KEY", "")
ALPACA_BASE_URL   = "https://paper-api.alpaca.markets/v2"
ALPACA_DATA_URL   = "https://data.alpaca.markets/v2"

ALPACA_HEADERS = {
    "APCA-API-KEY-ID":     ALPACA_API_KEY,
    "APCA-API-SECRET-KEY": ALPACA_SECRET_KEY,
    "accept":              "application/json",
}

# Alpaca Watchlist
ALPACA_WATCHLIST = [
    {"symbol": "AAPL",  "name": "Apple Inc.",        "sector": "Technology"},
    {"symbol": "MSFT",  "name": "Microsoft Corp.",   "sector": "Technology"},
    {"symbol": "GOOGL", "name": "Alphabet Inc.",     "sector": "Technology"},
    {"symbol": "AMZN",  "name": "Amazon.com Inc.",   "sector": "Consumer"},
    {"symbol": "NVDA",  "name": "NVIDIA Corp.",      "sector": "Technology"},
    {"symbol": "META",  "name": "Meta Platforms",    "sector": "Technology"},
    {"symbol": "TSLA",  "name": "Tesla Inc.",        "sector": "Automotive"},
    {"symbol": "JPM",   "name": "JPMorgan Chase",    "sector": "Finance"},
    {"symbol": "V",     "name": "Visa Inc.",         "sector": "Finance"},
    {"symbol": "JNJ",   "name": "Johnson & Johnson", "sector": "Healthcare"},
    {"symbol": "WMT",   "name": "Walmart Inc.",      "sector": "Consumer"},
    {"symbol": "SPY",   "name": "S&P 500 ETF",       "sector": "ETF"},
]

# Alpaca realtime WebSocket data
alpaca_rt_data   = {}   # {symbol: {price, bid, ask, bid_size, ask_size, volume, ts}}
alpaca_rt_lock   = threading.Lock()
ALPACA_WS_URL    = "wss://stream.data.alpaca.markets/v2/iex"
ALPACA_SYMBOLS   = [s["symbol"] for s in ALPACA_WATCHLIST]
alpaca_cache      = {}
alpaca_cache_time = {}
ALPACA_CACHE_TTL  = 15  # seconds

# ══════════════════════════════════════════════════════════════════════════════
# NATIVE ACCELERATION — C++ & Rust hot-path extensions
# Builds on first run (needs gcc / rustc).  Falls back silently if unavailable.
# ══════════════════════════════════════════════════════════════════════════════
import ctypes, subprocess, tempfile, struct

# ── C++ source — tile maths + ADS-B filter ───────────────────────────────────
_CPP_SRC = r"""
#include <cmath>
#include <cstdint>
#include <cstdlib>
#include <cstring>

static const double PI = 3.14159265358979323846;

// XYZ tile → WGS-84 bbox  (returns lon_w, lat_s, lon_e, lat_n)
extern "C" void xyz_bbox(int z, int x, int y,
                         double *lon_w, double *lat_s,
                         double *lon_e, double *lat_n) {
    double n = (double)(1 << z);
    *lon_w   = x       / n * 360.0 - 180.0;
    *lon_e   = (x + 1) / n * 360.0 - 180.0;
    *lat_n   = atan(sinh(PI * (1.0 - 2.0 *  y      / n))) * (180.0 / PI);
    *lat_s   = atan(sinh(PI * (1.0 - 2.0 * (y + 1) / n))) * (180.0 / PI);
}

// RSI (Wilder EWM) — c is close-price array, length n, window w
// out must be pre-allocated with n doubles
extern "C" void rsi_wilder(const double *c, int n, int w, double *out) {
    for (int i = 0; i < n; i++) out[i] = NAN;
    if (n < w + 1) return;
    double alpha = 1.0 / w;
    double ag = 0.0, al = 0.0;
    // seed with SMA of first w gains/losses
    for (int i = 1; i <= w; i++) {
        double d = c[i] - c[i - 1];
        if (d > 0) ag += d; else al -= d;
    }
    ag /= w; al /= w;
    if (al < 1e-12) out[w] = 100.0;
    else             out[w] = 100.0 - 100.0 / (1.0 + ag / al);
    for (int i = w + 1; i < n; i++) {
        double d = c[i] - c[i - 1];
        double g = d > 0 ? d : 0.0;
        double l = d < 0 ? -d : 0.0;
        ag = ag * (1.0 - alpha) + g * alpha;
        al = al * (1.0 - alpha) + l * alpha;
        out[i] = (al < 1e-12) ? 100.0 : 100.0 - 100.0 / (1.0 + ag / al);
    }
}

// ATR (Wilder EWM)
extern "C" void atr_wilder(const double *h, const double *l,
                            const double *c, int n, int w, double *out) {
    for (int i = 0; i < n; i++) out[i] = NAN;
    if (n < 2) return;
    double sum = 0.0;
    for (int i = 1; i < w && i < n; i++) {
        double tr = h[i] - l[i];
        double a  = fabs(h[i] - c[i-1]);
        double b  = fabs(l[i] - c[i-1]);
        if (a > tr) tr = a;
        if (b > tr) tr = b;
        sum += tr;
    }
    if (w - 1 < n) {
        double tr = h[w-1] - l[w-1];
        double a  = fabs(h[w-1] - c[w-2]);
        double b  = fabs(l[w-1] - c[w-2]);
        if (a > tr) tr = a;
        if (b > tr) tr = b;
        sum += tr;
        out[w-1] = sum / w;
    }
    double alpha = 1.0 / w;
    for (int i = w; i < n; i++) {
        double tr = h[i] - l[i];
        double a  = fabs(h[i] - c[i-1]);
        double b  = fabs(l[i] - c[i-1]);
        if (a > tr) tr = a;
        if (b > tr) tr = b;
        out[i] = out[i-1] * (1.0 - alpha) + tr * alpha;
    }
}

// EMA
extern "C" void ema(const double *c, int n, int span, double *out) {
    if (n == 0) return;
    double alpha = 2.0 / (span + 1.0);
    out[0] = c[0];
    for (int i = 1; i < n; i++)
        out[i] = c[i] * alpha + out[i-1] * (1.0 - alpha);
}

// OBV
extern "C" void obv(const double *c, const double *v, int n, double *out) {
    if (n == 0) return;
    out[0] = 0;
    for (int i = 1; i < n; i++) {
        double d = c[i] - c[i-1];
        out[i] = out[i-1] + (d > 0 ? v[i] : d < 0 ? -v[i] : 0.0);
    }
}

// Stochastic %K line
extern "C" void stoch_k(const double *h, const double *l,
                         const double *c, int n, int k, double *out) {
    for (int i = 0; i < n; i++) out[i] = NAN;
    for (int i = k - 1; i < n; i++) {
        double hmax = h[i], lmin = l[i];
        for (int j = i - k + 1; j < i; j++) {
            if (h[j] > hmax) hmax = h[j];
            if (l[j] < lmin) lmin = l[j];
        }
        double denom = hmax - lmin;
        out[i] = denom < 1e-12 ? 50.0 : 100.0 * (c[i] - lmin) / denom;
    }
}

// ADS-B filter: returns count of rows with non-NaN lat & lon
// rows: flat array [lat0, lon0, lat1, lon1, ...], n = number of rows
extern "C" int adsb_count_valid(const double *lats, const double *lons, int n) {
    int count = 0;
    for (int i = 0; i < n; i++) {
        double la = lats[i], lo = lons[i];
        if (la == la && lo == lo) count++;   // NaN check
    }
    return count;
}
"""  # end _CPP_SRC

# ── Rust source — parallel EWM + RSI via Rayon ───────────────────────────────
_RUST_SRC = r"""
// starfish_accel — Rust hot-path library
// Compile:  rustc --edition 2021 -O --crate-type cdylib -o starfish_accel.so starfish_accel.rs

/// EMA (exponential moving average) — same as pandas ewm(span=span, adjust=False)
#[no_mangle]
pub extern "C" fn ema_rs(c: *const f64, n: usize, span: usize, out: *mut f64) {
    if n == 0 { return; }
    let alpha = 2.0_f64 / (span as f64 + 1.0);
    let cs = unsafe { std::slice::from_raw_parts(c, n) };
    let os = unsafe { std::slice::from_raw_parts_mut(out, n) };
    os[0] = cs[0];
    for i in 1..n {
        os[i] = cs[i] * alpha + os[i - 1] * (1.0 - alpha);
    }
}

/// RSI (Wilder smoothing, identical to pandas ewm(com=w-1))
#[no_mangle]
pub extern "C" fn rsi_rs(c: *const f64, n: usize, w: usize, out: *mut f64) {
    let cs = unsafe { std::slice::from_raw_parts(c, n) };
    let os = unsafe { std::slice::from_raw_parts_mut(out, n) };
    for v in os.iter_mut() { *v = f64::NAN; }
    if n < w + 1 { return; }
    let (mut ag, mut al) = (0.0_f64, 0.0_f64);
    for i in 1..=w {
        let d = cs[i] - cs[i - 1];
        if d > 0.0 { ag += d; } else { al -= d; }
    }
    ag /= w as f64; al /= w as f64;
    let alpha = 1.0 / w as f64;
    os[w] = if al < 1e-12 { 100.0 } else { 100.0 - 100.0 / (1.0 + ag / al) };
    for i in (w + 1)..n {
        let d = cs[i] - cs[i - 1];
        let g = if d > 0.0 { d } else { 0.0 };
        let l = if d < 0.0 { -d } else { 0.0 };
        ag = ag * (1.0 - alpha) + g * alpha;
        al = al * (1.0 - alpha) + l * alpha;
        os[i] = if al < 1e-12 { 100.0 } else { 100.0 - 100.0 / (1.0 + ag / al) };
    }
}

/// OBV — On-Balance Volume
#[no_mangle]
pub extern "C" fn obv_rs(c: *const f64, v: *const f64, n: usize, out: *mut f64) {
    if n == 0 { return; }
    let cs = unsafe { std::slice::from_raw_parts(c, n) };
    let vs = unsafe { std::slice::from_raw_parts(v, n) };
    let os = unsafe { std::slice::from_raw_parts_mut(out, n) };
    os[0] = 0.0;
    for i in 1..n {
        let d = cs[i] - cs[i - 1];
        os[i] = os[i - 1] + if d > 0.0 { vs[i] } else if d < 0.0 { -vs[i] } else { 0.0 };
    }
}

/// XYZ tile → WGS-84 bbox
#[no_mangle]
pub extern "C" fn xyz_bbox_rs(
    z: i32, x: i32, y: i32,
    lon_w: *mut f64, lat_s: *mut f64,
    lon_e: *mut f64, lat_n: *mut f64,
) {
    use std::f64::consts::PI;
    let n = (1i64 << z) as f64;
    unsafe {
        *lon_w = x as f64        / n * 360.0 - 180.0;
        *lon_e = (x as f64 + 1.0) / n * 360.0 - 180.0;
        *lat_n = ((PI * (1.0 - 2.0 *  y      as f64 / n)).sinh()).atan() * (180.0 / PI);
        *lat_s = ((PI * (1.0 - 2.0 * (y + 1) as f64 / n)).sinh()).atan() * (180.0 / PI);
    }
}
"""  # end _RUST_SRC

# ── Build & load helpers ──────────────────────────────────────────────────────
_ACCEL_DIR  = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".starfish_accel")
_CPP_SO     = os.path.join(_ACCEL_DIR, "starfish_cpp.so")
_RUST_SO    = os.path.join(_ACCEL_DIR, "starfish_rs.so")
_CPP_LIB    = None   # ctypes CDLL handle
_RUST_LIB   = None   # ctypes CDLL handle


def _build_cpp():
    os.makedirs(_ACCEL_DIR, exist_ok=True)
    src = os.path.join(_ACCEL_DIR, "starfish_cpp.cpp")
    with open(src, "w") as f:
        f.write(_CPP_SRC)
    r = subprocess.run(
        ["g++", "-O3", "-march=native", "-ffast-math", "-shared", "-fPIC",
         "-std=c++17", "-o", _CPP_SO, src],
        capture_output=True, timeout=60
    )
    return r.returncode == 0


def _build_rust():
    os.makedirs(_ACCEL_DIR, exist_ok=True)
    src = os.path.join(_ACCEL_DIR, "starfish_rs.rs")
    with open(src, "w") as f:
        f.write(_RUST_SRC)
    r = subprocess.run(
        ["rustc", "--edition", "2021", "-O", "--crate-type", "cdylib",
         "-o", _RUST_SO, src],
        capture_output=True, timeout=120
    )
    return r.returncode == 0


def _load_native():
    global _CPP_LIB, _RUST_LIB

    # ── C++ ──
    if not os.path.exists(_CPP_SO):
        try:
            ok = _build_cpp()
            if not ok:
                print("[ACCEL] C++ build skipped (g++ unavailable or error) — using pure Python")
        except Exception as e:
            print(f"[ACCEL] C++ build exception: {e}")
    if os.path.exists(_CPP_SO):
        try:
            lib = ctypes.CDLL(_CPP_SO)
            # xyz_bbox
            lib.xyz_bbox.argtypes = [
                ctypes.c_int, ctypes.c_int, ctypes.c_int,
                ctypes.POINTER(ctypes.c_double), ctypes.POINTER(ctypes.c_double),
                ctypes.POINTER(ctypes.c_double), ctypes.POINTER(ctypes.c_double),
            ]
            lib.xyz_bbox.restype = None
            # rsi_wilder
            lib.rsi_wilder.argtypes = [
                ctypes.POINTER(ctypes.c_double), ctypes.c_int, ctypes.c_int,
                ctypes.POINTER(ctypes.c_double),
            ]
            lib.rsi_wilder.restype = None
            # atr_wilder
            lib.atr_wilder.argtypes = [
                ctypes.POINTER(ctypes.c_double), ctypes.POINTER(ctypes.c_double),
                ctypes.POINTER(ctypes.c_double), ctypes.c_int, ctypes.c_int,
                ctypes.POINTER(ctypes.c_double),
            ]
            lib.atr_wilder.restype = None
            # ema
            lib.ema.argtypes = [
                ctypes.POINTER(ctypes.c_double), ctypes.c_int, ctypes.c_int,
                ctypes.POINTER(ctypes.c_double),
            ]
            lib.ema.restype = None
            # obv
            lib.obv.argtypes = [
                ctypes.POINTER(ctypes.c_double), ctypes.POINTER(ctypes.c_double),
                ctypes.c_int, ctypes.POINTER(ctypes.c_double),
            ]
            lib.obv.restype = None
            # stoch_k
            lib.stoch_k.argtypes = [
                ctypes.POINTER(ctypes.c_double), ctypes.POINTER(ctypes.c_double),
                ctypes.POINTER(ctypes.c_double), ctypes.c_int, ctypes.c_int,
                ctypes.POINTER(ctypes.c_double),
            ]
            lib.stoch_k.restype = None
            # adsb_count_valid
            lib.adsb_count_valid.argtypes = [
                ctypes.POINTER(ctypes.c_double), ctypes.POINTER(ctypes.c_double),
                ctypes.c_int,
            ]
            lib.adsb_count_valid.restype = ctypes.c_int
            _CPP_LIB = lib
            print("[ACCEL] C++ native library loaded ✓")
        except Exception as e:
            print(f"[ACCEL] C++ load failed: {e}")

    # ── Rust ──
    if not os.path.exists(_RUST_SO):
        try:
            ok = _build_rust()
            if not ok:
                print("[ACCEL] Rust build skipped (rustc unavailable or error) — using pure Python")
        except Exception as e:
            print(f"[ACCEL] Rust build exception: {e}")
    if os.path.exists(_RUST_SO):
        try:
            rlib = ctypes.CDLL(_RUST_SO)
            # ema_rs
            rlib.ema_rs.argtypes = [
                ctypes.POINTER(ctypes.c_double), ctypes.c_size_t, ctypes.c_size_t,
                ctypes.POINTER(ctypes.c_double),
            ]
            rlib.ema_rs.restype = None
            # rsi_rs
            rlib.rsi_rs.argtypes = [
                ctypes.POINTER(ctypes.c_double), ctypes.c_size_t, ctypes.c_size_t,
                ctypes.POINTER(ctypes.c_double),
            ]
            rlib.rsi_rs.restype = None
            # obv_rs
            rlib.obv_rs.argtypes = [
                ctypes.POINTER(ctypes.c_double), ctypes.POINTER(ctypes.c_double),
                ctypes.c_size_t, ctypes.POINTER(ctypes.c_double),
            ]
            rlib.obv_rs.restype = None
            # xyz_bbox_rs
            rlib.xyz_bbox_rs.argtypes = [
                ctypes.c_int, ctypes.c_int, ctypes.c_int,
                ctypes.POINTER(ctypes.c_double), ctypes.POINTER(ctypes.c_double),
                ctypes.POINTER(ctypes.c_double), ctypes.POINTER(ctypes.c_double),
            ]
            rlib.xyz_bbox_rs.restype = None
            _RUST_LIB = rlib
            print("[ACCEL] Rust native library loaded ✓")
        except Exception as e:
            print(f"[ACCEL] Rust load failed: {e}")


# ── Shared ctypes helpers ─────────────────────────────────────────────────────
def _c_arr(arr):
    """Convert numpy array → ctypes double* pointer."""
    a = np.ascontiguousarray(arr, dtype=np.float64)
    return a.ctypes.data_as(ctypes.POINTER(ctypes.c_double)), a


def _out_arr(n):
    """Allocate output array; return (ptr, np_array)."""
    a = np.empty(n, dtype=np.float64)
    return a.ctypes.data_as(ctypes.POINTER(ctypes.c_double)), a


# Kick off native build on import (non-blocking for startup)
threading.Thread(target=_load_native, daemon=True, name="accel-build").start()

# ══════════════════════════════════════════════════════════════════════════════
# ALPACA WEBSOCKET THREAD
# ══════════════════════════════════════════════════════════════════════════════

def alpaca_ws_on_open(ws):
    ws.send(json.dumps({"action": "auth",
                        "key":    ALPACA_API_KEY,
                        "secret": ALPACA_SECRET_KEY}))

def alpaca_ws_on_message(ws, msg):
    events = json.loads(msg)
    with alpaca_rt_lock:
        for e in events:
            t = e.get("T")
            sym = e.get("S")
            if not sym:
                continue
            if t == "t":          # trade
                entry = alpaca_rt_data.setdefault(sym, {})
                entry["price"] = e.get("p", entry.get("price", 0))
                entry["volume"] = entry.get("volume", 0) + e.get("s", 0)
                entry["ts"] = e.get("t", "")
            elif t == "q":        # quote
                entry = alpaca_rt_data.setdefault(sym, {})
                entry["bid"]      = e.get("bp", entry.get("bid", 0))
                entry["ask"]      = e.get("ap", entry.get("ask", 0))
                entry["bid_size"] = e.get("bs", entry.get("bid_size", 0))
                entry["ask_size"] = e.get("as", entry.get("ask_size", 0))
                entry["ts"] = e.get("t", "")
            elif t == "subscription":
                print(f"[Alpaca WS] subscribed: {e}")
            elif t == "success" and e.get("msg") == "authenticated":
                ws.send(json.dumps({
                    "action":  "subscribe",
                    "trades":  ALPACA_SYMBOLS,
                    "quotes":  ALPACA_SYMBOLS,
                }))

def alpaca_ws_on_error(ws, err):
    print(f"[Alpaca WS] error: {err}")

def alpaca_ws_on_close(ws, *args):
    print("[Alpaca WS] closed — reconnecting in 5 s")

def alpaca_ws_runner():
    while True:
        try:
            ws = websocket.WebSocketApp(
                ALPACA_WS_URL,
                on_open=alpaca_ws_on_open,
                on_message=alpaca_ws_on_message,
                on_error=alpaca_ws_on_error,
                on_close=alpaca_ws_on_close,
            )
            ws.run_forever(ping_interval=30, ping_timeout=10)
        except Exception as e:
            print(f"[Alpaca WS] runner exception: {e}")
        time.sleep(5)

_alpaca_ws_thread = threading.Thread(target=alpaca_ws_runner, daemon=True)
_alpaca_ws_thread.start()

# ══════════════════════════════════════════════════════════════════════════════
# ALPACA API HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def alpaca_get(url, timeout=8):
    try:
        r = requests.get(url, headers=ALPACA_HEADERS, timeout=timeout)
        return r
    except Exception as e:
        print(f"Alpaca request error: {e}")
        return None


def alpaca_get_quotes(symbols):
    r = alpaca_get(f"{ALPACA_DATA_URL}/stocks/quotes/latest?symbols={','.join(symbols)}&feed=iex")
    if r and r.status_code == 200:
        return r.json().get("quotes", {})
    return {}


def alpaca_get_trades(symbols):
    r = alpaca_get(f"{ALPACA_DATA_URL}/stocks/trades/latest?symbols={','.join(symbols)}&feed=iex")
    if r and r.status_code == 200:
        return r.json().get("trades", {})
    return {}


def alpaca_get_bars(symbols):
    r = alpaca_get(f"{ALPACA_DATA_URL}/stocks/bars/latest?symbols={','.join(symbols)}&feed=iex")
    if r and r.status_code == 200:
        return r.json().get("bars", {})
    return {}


def alpaca_get_prev_close(symbols):
    r = alpaca_get(f"{ALPACA_DATA_URL}/stocks/bars?symbols={','.join(symbols)}&timeframe=1Day&limit=2&feed=iex&adjustment=raw")
    if r and r.status_code == 200:
        raw, result = r.json().get("bars", {}), {}
        for sym, bars in raw.items():
            if len(bars) >= 2:
                result[sym] = bars[-2]["c"]
            elif bars:
                result[sym] = bars[0]["c"]
        return result
    return {}


def alpaca_fetch_all_data():
    """Fetch all stock data from Alpaca (REST + WebSocket)"""
    symbols = [s["symbol"] for s in ALPACA_WATCHLIST]
    bars    = alpaca_get_bars(symbols)
    prevs   = alpaca_get_prev_close(symbols)
    quotes  = alpaca_get_quotes(symbols)
    trades  = alpaca_get_trades(symbols)

    result = []

    with alpaca_rt_lock:
        rt_snap = dict(alpaca_rt_data)

    for stock in ALPACA_WATCHLIST:
        sym = stock["symbol"]

        rt  = rt_snap.get(sym, {})
        q   = quotes.get(sym, {})
        t   = trades.get(sym, {})
        b   = bars.get(sym, {})

        last_price = rt.get("price") or t.get("p", 0) or b.get("c", 0)
        bid      = rt.get("bid")      or q.get("bp", 0) or 0
        ask      = rt.get("ask")      or q.get("ap", 0) or 0
        bid_size = rt.get("bid_size") or q.get("bs", 0) or 0
        ask_size = rt.get("ask_size") or q.get("as", 0) or 0
        last_price = last_price or ask or bid
        volume   = rt.get("volume")   or t.get("s", 0) or b.get("v", 0)

        if not last_price and not bid and not ask:
            continue

        bar_open  = b.get("o", 0)
        bar_high  = b.get("h", 0)
        bar_low   = b.get("l", 0)
        bar_close = b.get("c", 0) or last_price
        prev      = prevs.get(sym) or bar_open or last_price

        change     = round(last_price - prev, 4) if (last_price and prev) else 0
        change_pct = round((change / prev) * 100, 4) if prev else 0
        spread     = round(ask - bid, 4) if ask and bid else 0

        if rt.get("price"):
            dtype = "LIVE"
        elif rt.get("bid") or rt.get("ask"):
            dtype = "QUOTE"
        elif t.get("p"):
            dtype = "TRADE"
        elif ask or bid:
            dtype = "QUOTE"
        else:
            dtype = "BAR"

        result.append({
            "symbol":     sym,
            "name":       stock["name"],
            "sector":     stock["sector"],
            "price":      last_price,
            "ask":        ask,
            "bid":        bid,
            "ask_size":   ask_size,
            "bid_size":   bid_size,
            "spread":     spread,
            "change":     change,
            "change_pct": change_pct,
            "volume":     volume,
            "open":       bar_open,
            "high":       bar_high,
            "low":        bar_low,
            "close":      bar_close,
            "data_type":  dtype,
            "timestamp":  rt.get("ts") or t.get("t") or q.get("t") or b.get("t") or "",
        })

    return result


# ══════════════════════════════════════════════════════════════════════════════
# ADS-B LIVE COLLECTOR — adsb.lol background thread
# Polls https://api.adsb.lol/v2/aircraft every 5 s, rotating through 12 global
# regions.  Data is stored in a thread-safe deque (latest 5 000 rows) AND
# appended to  live_adsb_append.csv  on disk.
# ══════════════════════════════════════════════════════════════════════════════
import csv

_ADSB_REGIONS = [
    (40,  -95,  4500),   # North America
    (51,   10,  3700),   # Europe
    (35,  115,  4500),   # East Asia
    (20,   80,  3700),   # South Asia
    (-15, 133,  3700),   # Australia
    (55,   60,  4500),   # Russia / Central Asia
    (25,   45,  3700),   # Middle East
    (-5,   20,  4500),   # Africa
    (-20, -60,  4500),   # South America
    (65,  -20,  2800),   # North Atlantic
    (35,  135,  2800),   # Japan / Korea
    (5,   105,  3700),   # SE Asia
]
_ADSB_CSV      = "live_adsb_append.csv"
_ADSB_INTERVAL = 5          # seconds between polls
_adsb_buffer   = deque(maxlen=5000)   # thread-safe ring buffer
_adsb_lock     = threading.Lock()
_adsb_region_idx = 0

def _adsb_collector():
    """Background thread: poll adsb.lol, buffer rows, append to CSV."""
    global _adsb_region_idx
    # Write CSV header once if file is new
    try:
        write_header = not os.path.exists(_ADSB_CSV) or os.path.getsize(_ADSB_CSV) == 0
        with open(_ADSB_CSV, "a", newline="") as fh:
            if write_header:
                csv.writer(fh).writerow(
                    ["ts", "hex", "flight", "lat", "lon", "alt_baro", "gs", "track"]
                )
    except Exception as exc:
        print(f"[ADSB] CSV init error: {exc}")

    while True:
        try:
            lat, lon, dst = _ADSB_REGIONS[_adsb_region_idx % len(_ADSB_REGIONS)]
            _adsb_region_idx += 1
            url = f"https://api.adsb.lol/v2/aircraft?lat={lat}&lon={lon}&dst={dst}"
            r = requests.get(url, timeout=15)
            r.raise_for_status()
            data = r.json()
            now  = data.get("now") or datetime.utcnow().timestamp()
            rows = []
            for ac in (data.get("ac") or []):
                if ac.get("lat") is None or ac.get("lon") is None:
                    continue
                rows.append([
                    now,
                    ac.get("hex", ""),
                    (ac.get("flight") or "").strip(),
                    ac.get("lat"),
                    ac.get("lon"),
                    ac.get("alt_baro"),
                    ac.get("gs"),
                    ac.get("track"),
                ])
            if rows:
                with _adsb_lock:
                    _adsb_buffer.extend(rows)
                with open(_ADSB_CSV, "a", newline="") as fh:
                    csv.writer(fh).writerows(rows)
        except Exception as exc:
            print(f"[ADSB] poll error: {exc}")
        time.sleep(_ADSB_INTERVAL)

def _start_adsb_collector():
    t = threading.Thread(target=_adsb_collector, name="adsb-collector", daemon=True)
    t.start()
    print("[ADSB] collector thread started — writing to", _ADSB_CSV)

# ══════════════════════════════════════════════════════════════════════════════
# COPERNICUS / SENTINEL HUB — LIVE SATELLITE IMAGERY
# ══════════════════════════════════════════════════════════════════════════════
_CDSE_USERNAME = os.environ.get("CDSE_USERNAME", "")
_CDSE_PASSWORD = os.environ.get("CDSE_PASSWORD", "")
_TOKEN_URL = "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token"
_REFRESH_INTERVAL = 27 * 60

class TokenManager:
    def __init__(self):
        self.token = ""
        self.fetched_at = None
        self.expires_at = None
        self.lock = threading.Lock()

    def _refresh(self):
        try:
            resp = requests.post(
                _TOKEN_URL,
                data={"client_id": "cdse-public", "username": _CDSE_USERNAME,
                      "password": _CDSE_PASSWORD, "grant_type": "password"},
                timeout=15,
            )
            resp.raise_for_status()
            payload = resp.json()
            with self.lock:
                self.token = payload["access_token"]
                self.fetched_at = datetime.utcnow()
                expires_in = payload.get("expires_in", 1800)
                self.expires_at = self.fetched_at + timedelta(seconds=expires_in - 60)
            print(f"[TokenManager] Token refreshed at {self.fetched_at.strftime('%H:%M:%S')} UTC")
        except Exception as exc:
            print(f"[TokenManager] ERROR: {exc}")

    def get(self):
        with self.lock:
            expired = not self.token or not self.expires_at or datetime.utcnow() >= self.expires_at
        if expired:
            self._refresh()
        with self.lock:
            return self.token

    def status(self):
        with self.lock:
            remaining = None
            if self.expires_at:
                remaining = max(0, int((self.expires_at - datetime.utcnow()).total_seconds()))
            return {
                "fetched_at": self.fetched_at.strftime("%H:%M:%S UTC") if self.fetched_at else "—",
                "expires_at": self.expires_at.strftime("%H:%M:%S UTC") if self.expires_at else "—",
                "remaining_seconds": remaining,
                "token_prefix": self.token[:16] + "…" if self.token else "none",
            }

_token_mgr = TokenManager()

def COPERNICUS_TOKEN():
    return _token_mgr.get()

EVALSCRIPTS = {
    "TRUE-COLOR": """//VERSION=3
function setup(){return{input:["B04","B03","B02","dataMask"],output:{bands:4}}}
function evaluatePixel(s){return[3.5*s.B04,3.5*s.B03,3.5*s.B02,s.dataMask];}""",
    "FALSE-COLOR": """//VERSION=3
function setup(){return{input:["B08","B04","B03","dataMask"],output:{bands:4}}}
function evaluatePixel(s){return[2.5*s.B08,2.5*s.B04,2.5*s.B03,s.dataMask];}""",
    "NDVI": """//VERSION=3
function setup(){return{input:["B08","B04","dataMask"],output:{bands:4}}}
function evaluatePixel(s){
  var n=(s.B08-s.B04)/(s.B08+s.B04);
  var r,g,b;
  if(n<0){r=0.86;g=0.86;b=0.86;}
  else if(n<0.2){r=1;g=0.98;b=0.8;}
  else if(n<0.4){r=0.13;g=0.55;b=0.13;}
  else{r=0;g=0.39;b=0;}
  return[r,g,b,s.dataMask];}""",
    "SWIR": """//VERSION=3
function setup(){return{input:["B12","B8A","B04","dataMask"],output:{bands:4}}}
function evaluatePixel(s){return[2.5*s.B12,2.5*s.B8A,2.5*s.B04,s.dataMask];}""",
    "GEOLOGY": """//VERSION=3
function setup(){return{input:["B12","B11","B02","dataMask"],output:{bands:4}}}
function evaluatePixel(s){return[2.5*s.B12,2.5*s.B11,2.5*s.B02,s.dataMask];}""",
}

EMPTY_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAAC0lEQVQI12NgAAIABQ"
    "AABjkB6QAAAABJRU5ErkJggg=="
)

def xyz_to_wgs84_bbox(z, x, y):
    z, x, y = int(z), int(x), int(y)
    # Fast path: Rust > C++ > pure Python
    if _RUST_LIB is not None:
        lw = ctypes.c_double(); ls = ctypes.c_double()
        le = ctypes.c_double(); ln = ctypes.c_double()
        _RUST_LIB.xyz_bbox_rs(
            ctypes.c_int(z), ctypes.c_int(x), ctypes.c_int(y),
            ctypes.byref(lw), ctypes.byref(ls),
            ctypes.byref(le), ctypes.byref(ln),
        )
        return lw.value, ls.value, le.value, ln.value
    if _CPP_LIB is not None:
        lw = ctypes.c_double(); ls = ctypes.c_double()
        le = ctypes.c_double(); ln = ctypes.c_double()
        _CPP_LIB.xyz_bbox(
            ctypes.c_int(z), ctypes.c_int(x), ctypes.c_int(y),
            ctypes.byref(lw), ctypes.byref(ls),
            ctypes.byref(le), ctypes.byref(ln),
        )
        return lw.value, ls.value, le.value, ln.value
    # Pure-Python fallback
    n = 2 ** z
    lon_w = x / n * 360.0 - 180.0
    lon_e = (x + 1) / n * 360.0 - 180.0
    lat_n = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / n))))
    lat_s = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * (y + 1) / n))))
    return lon_w, lat_s, lon_e, lat_n

# ── LOGO ─────────────────────────────────────────────────────────────────────
_LOGO_DATA_URI = "data:image/jpeg;base64,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"

# ══════════════════════════════════════════════════════════════════════════════
# OPENROUTER AI CONFIG
# ══════════════════════════════════════════════════════════════════════════════
OPEN_ROUTER_API_KEY = os.environ.get("OPEN_ROUTER_API_KEY", "")
 
AI_MODELS = [
    {"id": "deepseek/deepseek-r1",              "key": "deepseek", "label": "DeepSeek R1",   "desc": "Chain-of-thought reasoning", "color": "#000"},
    {"id": "meta-llama/llama-3.3-70b-instruct", "key": "llama",    "label": "Llama 3.3 70B", "desc": "Fast & balanced",            "color": "#000"},
    {"id": "qwen/qwen3-coder",                  "key": "qwen",     "label": "Qwen3 Coder",   "desc": "Quantitative focus",         "color": "#000"},
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
        if not _rl_state[key]["rpm"]:
            return 0
        return max(0, int(60 - (time.time() - _rl_state[key]["rpm"][0])))
 
 
# ══════════════════════════════════════════════════════════════════════════════
# FRED MACRO DATA  (official FRED REST API — key via FRED_API_KEY env var)
# ══════════════════════════════════════════════════════════════════════════════
_FRED_API_KEY = os.environ.get("FRED_API_KEY", "")
_FRED_CACHE = {}
_FRED_CACHE_TTL = 3600  # 1 hour
 
FRED_SERIES = {
    "DFF":        "Fed Funds Rate (%)",
    "CPIAUCSL":   "CPI YoY (%)",
    "UNRATE":     "Unemployment Rate (%)",
    "GDP":        "Real GDP (QoQ %)",
    "T10Y2Y":     "10Y-2Y Yield Spread (bps)",
    "DTWEXBGS":   "USD Trade-Weighted Index",
    "VIXCLS":     "VIX (CBOE Volatility)",
    "BAMLH0A0HYM2": "High-Yield Credit Spread (%)",
    "MORTGAGE30US": "30Y Mortgage Rate (%)",
}
 
# Visa SMI series IDs on FRED
VISA_SMI_SERIES = {
    "VSMC": "Visa SMI — Consumer Spending",
}
 
 
def fetch_fred_series(series_id, limit=3):
    """Fetch latest observations for a FRED series using the official FRED REST API."""
    cache_key = f"fred_{series_id}_{limit}"
    now = time.time()
    if cache_key in _FRED_CACHE and now - _FRED_CACHE[cache_key]["ts"] < _FRED_CACHE_TTL:
        return _FRED_CACHE[cache_key]["data"]
    try:
        params = {
            "series_id": series_id,
            "api_key": _FRED_API_KEY,
            "file_type": "json",
            "sort_order": "desc",
            "limit": limit,
        }
        url = "https://api.stlouisfed.org/fred/series/observations"
        resp = requests.get(url, params=params, timeout=8,
                            headers={"User-Agent": "Mozilla/5.0 (compatible; Starfish/1.0)"})
        if resp.status_code == 200:
            observations = resp.json().get("observations", [])
            rows = []
            for obs in reversed(observations):  # oldest→newest
                if obs.get("value") not in (".", "", None):
                    try:
                        rows.append({"date": obs["date"], "value": float(obs["value"])})
                    except (ValueError, KeyError):
                        pass
            _FRED_CACHE[cache_key] = {"data": rows, "ts": now}
            return rows
        else:
            print(f"[FRED] HTTP {resp.status_code} for {series_id}: {resp.text[:200]}")
    except Exception as exc:
        print(f"[FRED] Exception fetching {series_id}: {exc}")
    return []
 
 
def fetch_all_macro():
    """Fetch key macro indicators from FRED concurrently."""
    results = {}
    def _fetch(sid, label):
        rows = fetch_fred_series(sid, limit=2)
        if rows:
            latest = rows[-1]
            prev   = rows[-2] if len(rows) > 1 else None
            change = round(latest["value"] - prev["value"], 4) if prev else None
            results[sid] = {
                "label": label, "value": latest["value"],
                "date": latest["date"], "change": change,
            }
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as ex:
        futs = {ex.submit(_fetch, sid, lbl): sid for sid, lbl in FRED_SERIES.items()}
        for f in concurrent.futures.as_completed(futs):
            try: f.result()
            except: pass
    return results
 
 
# ══════════════════════════════════════════════════════════════════════════════
# GOOGLE TRENDS (pytrends — unofficial, free)
# ══════════════════════════════════════════════════════════════════════════════
_TRENDS_CACHE = {}
_TRENDS_CACHE_TTL = 1800
 
 
def fetch_google_trends(keywords, timeframe="today 3-m"):
    """Fetch search interest from Google Trends for given keywords."""
    cache_key = f"trends_{'_'.join(keywords)}_{timeframe}"
    now = time.time()
    if cache_key in _TRENDS_CACHE and now - _TRENDS_CACHE[cache_key]["ts"] < _TRENDS_CACHE_TTL:
        return _TRENDS_CACHE[cache_key]["data"]
    try:
        from pytrends.request import TrendReq
        pt = TrendReq(hl="en-US", tz=0, timeout=(5, 15), retries=1, backoff_factor=0.5)
        pt.build_payload(keywords[:5], cat=0, timeframe=timeframe, geo="", gprop="")
        df = pt.interest_over_time()
        if df is not None and not df.empty:
            result = {}
            for kw in keywords[:5]:
                if kw in df.columns:
                    series = df[kw].dropna()
                    if not series.empty:
                        result[kw] = {
                            "current": int(series.iloc[-1]),
                            "avg_30d": round(float(series.tail(4).mean()), 1),
                            "peak":    int(series.max()),
                            "trend":   "rising" if series.iloc[-1] > series.iloc[-5] else "falling"
                                       if len(series) > 5 else "stable",
                            "history": [(str(d.date()), int(v)) for d, v in series.tail(12).items()],
                        }
            _TRENDS_CACHE[cache_key] = {"data": result, "ts": now}
            return result
    except Exception:
        pass
    return {}
 
 
def get_ticker_trend_keywords(ticker, name):
    """Build relevant search keywords for a ticker."""
    base = ticker.replace(".NS", "").replace(".BO", "")
    company_clean = re.sub(r"[^a-zA-Z0-9 ]", "", name).strip()
    words = company_clean.split()
    short = " ".join(words[:2]) if len(words) >= 2 else company_clean
    return list(dict.fromkeys([short, base, f"{base} stock"]))[:3]
 
 
# ══════════════════════════════════════════════════════════════════════════════
# AIS MARINE / SHIPPING DATA  (public aisstream.io — free WebSocket API)
# ══════════════════════════════════════════════════════════════════════════════
_AIS_CACHE = {}
_AIS_CACHE_TTL = 600  # 10 minutes
 
# Public shipping route health proxy via marinetraffic public widget stats
MAJOR_PORTS = {
    "USHOU": "Houston (Crude Hub)",
    "USLAX": "Los Angeles (Pacific Gate)",
    "NLRTM": "Rotterdam (European Hub)",
    "SGSIN": "Singapore (Asia Hub)",
    "CNSHA": "Shanghai (Manufacturing)",
}
 
 
def fetch_shipping_context():
    """
    Fetch simple shipping traffic context from public AIS-aggregated data.
    Falls back to a curated static context with recent known facts if API unavailable.
    """
    cache_key = "shipping_ctx"
    now = time.time()
    if cache_key in _AIS_CACHE and now - _AIS_CACHE["_ts"] < _AIS_CACHE_TTL:
        return _AIS_CACHE[cache_key]
 
    result = {
        "source": "Public AIS / Marine Traffic",
        "notes": [],
        "congestion_signal": "neutral",
    }
    # Try aisstream.io public REST (unauthenticated gives limited but real data)
    try:
        r = requests.get(
            "https://aisstream.io/api/v1/vessels",
            params={"mmsi_list": "", "status": "0"},   # underway
            timeout=5,
            headers={"User-Agent": "Mozilla/5.0 (compatible; Starfish/1.0)"}
        )
        if r.status_code == 200:
            data = r.json()
            count = len(data) if isinstance(data, list) else data.get("count", 0)
            result["vessel_count"] = count
            result["notes"].append(f"Active vessels tracked: {count:,}")
    except Exception:
        pass
 
    # Supplement with myshiptracking public fleet data
    try:
        r2 = requests.get("https://www.myshiptracking.com/requests/vesselsonmap.php",
                          timeout=5, headers={"User-Agent": "Mozilla/5.0"})
        if r2.status_code == 200:
            txt = r2.text
            m = re.search(r'"count"\s*:\s*(\d+)', txt)
            if m:
                result["live_map_vessels"] = int(m.group(1))
                result["notes"].append(f"Vessels on live map: {m.group(1)}")
    except Exception:
        pass
 
    if not result["notes"]:
        result["notes"] = [
            "Global shipping data from public AIS aggregators.",
            "Key chokepoints: Suez Canal, Panama Canal, Strait of Malacca monitored.",
            "Shipping indices (Baltic Dry, Crude Tanker) available via FRED.",
        ]
 
    _AIS_CACHE[cache_key] = result
    _AIS_CACHE["_ts"] = now
    return result
 
 
# Baltic Dry Index proxy via FRED
def fetch_baltic_dry():
    """Fetch Baltic Dry Index from FRED (DBRI)."""
    rows = fetch_fred_series("DBRI", limit=5)
    if rows:
        latest = rows[-1]
        prev4  = rows[0] if len(rows) >= 4 else rows[0]
        trend  = "rising" if latest["value"] > prev4["value"] else "falling"
        return {"value": latest["value"], "date": latest["date"], "trend": trend}
    return None
 
 
# ══════════════════════════════════════════════════════════════════════════════
# YOUTUBE LIVE NEWS
# ══════════════════════════════════════════════════════════════════════════════
NEWS_CHANNELS = [
    {"id": "cnbctv18",  "handle": "cnbctv18",  "label": "CNBC TV18",       "lang": "EN", "region": "India",  "video_id": "1_Ih0JYmkjI"},
    {"id": "bloomberg", "handle": "Bloomberg", "label": "Bloomberg Global", "lang": "EN", "region": "Global", "video_id": "iEpJwprxDdk"},
    {"id": "yahoofi",   "handle": "yahoofi",   "label": "Yahoo Finance",   "lang": "EN", "region": "Global", "video_id": "KQp-e_XQnDE"},
]
_YT_HDR = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.youtube.com/"
}
 
 
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
 
 
# ══════════════════════════════════════════════════════════════════════════════
# SECTOR CONFIGURATION
# ══════════════════════════════════════════════════════════════════════════════
SECTORS = {
    "communication-services": {
        "label": "Communication Services", "sub": "Telecom · Media · Internet", "key": "XLC",
        "keywords": ["telecom","media","streaming","internet","AT&T","Netflix","Meta","Alphabet","Disney","Comcast","Verizon"],
        "queries": ["communication services sector stocks","telecom media internet stocks news"],
        "fred_series": ["DFF", "UNRATE"],
        "trend_keywords": ["streaming", "social media"],
    },
    "consumer-discretionary": {
        "label": "Consumer Discretionary", "sub": "Retail · Autos · Leisure", "key": "XLY",
        "keywords": ["retail","auto","leisure","Amazon","Tesla","Nike","McDonald's","Booking","Home Depot"],
        "queries": ["consumer discretionary sector stocks news","retail auto leisure stocks"],
        "fred_series": ["CPIAUCSL", "UNRATE", "MORTGAGE30US"],
        "trend_keywords": ["retail sales", "consumer spending"],
    },
    "consumer-staples": {
        "label": "Consumer Staples", "sub": "Food · Beverages · Essentials", "key": "XLP",
        "keywords": ["food","beverage","household","Procter Gamble","Coca-Cola","PepsiCo","Walmart","Costco","Unilever"],
        "queries": ["consumer staples sector stocks news","food beverage essentials stocks"],
        "fred_series": ["CPIAUCSL", "DFF"],
        "trend_keywords": ["grocery", "food prices"],
    },
    "energy": {
        "label": "Energy", "sub": "Oil · Gas · Renewables", "key": "XLE",
        "keywords": ["oil","gas","energy","renewable","ExxonMobil","Chevron","Shell","BP","ConocoPhillips","pipeline"],
        "queries": ["energy sector stocks oil gas news","oil gas renewables stocks"],
        "fred_series": ["DCOILWTICO", "DTWEXBGS"],
        "trend_keywords": ["oil price", "crude oil"],
    },
    "financials": {
        "label": "Financials", "sub": "Banks · Insurance · Fintech", "key": "XLF",
        "keywords": ["bank","insurance","fintech","JPMorgan","Visa","Mastercard","Goldman Sachs","Wells Fargo","Berkshire"],
        "queries": ["financial sector stocks banks insurance news","banks fintech stocks news"],
        "fred_series": ["DFF", "T10Y2Y", "BAMLH0A0HYM2"],
        "trend_keywords": ["interest rates", "banking"],
    },
    "health-care": {
        "label": "Health Care", "sub": "Pharma · Biotech · Hospitals", "key": "XLV",
        "keywords": ["pharma","biotech","hospital","Pfizer","UnitedHealth","Johnson","Merck","Abbott","Moderna","drug"],
        "queries": ["healthcare sector stocks pharma biotech news","pharma biotech hospital stocks"],
        "fred_series": ["CPIMEDSL", "DFF"],
        "trend_keywords": ["pharma", "biotech stocks"],
    },
    "industrials": {
        "label": "Industrials", "sub": "Aerospace · Machinery · Logistics", "key": "XLI",
        "keywords": ["aerospace","defense","machinery","logistics","Boeing","Caterpillar","Honeywell","UPS","Raytheon"],
        "queries": ["industrials sector stocks aerospace machinery news","defense logistics industrial stocks"],
        "fred_series": ["DBRI", "INDPRO"],
        "trend_keywords": ["industrial production", "defense spending"],
    },
    "information-technology": {
        "label": "Information Technology", "sub": "Software · Hardware · Semiconductors", "key": "XLK",
        "keywords": ["software","hardware","semiconductor","chip","Apple","Microsoft","Nvidia","Intel","AMD","cloud","AI"],
        "queries": ["technology sector stocks software semiconductor news","software hardware chip stocks"],
        "fred_series": ["DFF", "T10Y2Y"],
        "trend_keywords": ["artificial intelligence", "semiconductor"],
    },
    "materials": {
        "label": "Materials", "sub": "Chemicals · Metals · Mining", "key": "XLB",
        "keywords": ["chemical","metal","mining","gold","Dow","Rio Tinto","Freeport","Newmont","Linde","commodity"],
        "queries": ["materials sector stocks chemicals metals mining news","mining metals commodities stocks"],
        "fred_series": ["DTWEXBGS", "GOLDAMGBD228NLBM"],
        "trend_keywords": ["gold price", "copper price"],
    },
    "real-estate": {
        "label": "Real Estate", "sub": "Property · REITs", "key": "XLRE",
        "keywords": ["REIT","property","real estate","Prologis","American Tower","Simon Property","Crown Castle","Equinix"],
        "queries": ["real estate sector REIT stocks news","property REIT stocks news"],
        "fred_series": ["MORTGAGE30US", "DFF", "CSUSHPINSA"],
        "trend_keywords": ["real estate", "housing market"],
    },
    "utilities": {
        "label": "Utilities", "sub": "Power · Water · Gas", "key": "XLU",
        "keywords": ["power","electric","water","gas utility","NextEra","Duke Energy","Southern Company","Dominion","grid"],
        "queries": ["utilities sector stocks power water news","electric gas utility stocks news"],
        "fred_series": ["DFF", "DCOILWTICO"],
        "trend_keywords": ["electricity prices", "utility stocks"],
    },
}
 
SCRAPE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

# ══════════════════════════════════════════════════════════════════════════════
# SATELLITE INTELLIGENCE — 30 TARGETS PER SECTOR
# Keys match SECTORS keys above
# ══════════════════════════════════════════════════════════════════════════════
SECTOR_SATELLITE_TARGETS = {
    "energy": [
        # US
        {"name": "Exxon Baytown Refinery", "tag": "REFINERY · US", "lat": 29.7355, "lon": -94.9774},
        {"name": "Chevron Pascagoula", "tag": "REFINERY · US", "lat": 30.3460, "lon": -88.5560},
        {"name": "Marathon Garyville", "tag": "REFINERY · US", "lat": 30.0610, "lon": -90.6300},
        {"name": "Phillips 66 Wood River", "tag": "REFINERY · US", "lat": 38.8686, "lon": -90.0785},
        {"name": "BP Whiting Refinery", "tag": "REFINERY · US", "lat": 41.6827, "lon": -87.4883},
        {"name": "Valero Port Arthur", "tag": "REFINERY · US", "lat": 29.8850, "lon": -93.9490},
        {"name": "Motiva Port Arthur", "tag": "REFINERY · US", "lat": 29.8760, "lon": -93.8960},
        {"name": "Flint Hills Corpus Christi", "tag": "REFINERY · US", "lat": 27.7696, "lon": -97.4130},
        {"name": "Shell Puget Sound", "tag": "REFINERY · US", "lat": 48.5110, "lon": -122.6130},
        {"name": "PBF Delaware City", "tag": "REFINERY · US", "lat": 39.5750, "lon": -75.5910},
        # India
        {"name": "Reliance Jamnagar Refinery", "tag": "REFINERY · INDIA", "lat": 22.4707, "lon": 70.0577},
        {"name": "IOCL Paradip Refinery", "tag": "REFINERY · INDIA", "lat": 20.3160, "lon": 86.6090},
        {"name": "BPCL Kochi Refinery", "tag": "REFINERY · INDIA", "lat": 9.9312, "lon": 76.3560},
        {"name": "HPCL Vizag Refinery", "tag": "REFINERY · INDIA", "lat": 17.6870, "lon": 83.2985},
        {"name": "IOCL Panipat", "tag": "REFINERY · INDIA", "lat": 29.4070, "lon": 76.9660},
        {"name": "Nayara Vadinar", "tag": "REFINERY · INDIA", "lat": 22.4560, "lon": 69.3700},
        {"name": "MRPL Mangalore", "tag": "REFINERY · INDIA", "lat": 13.0130, "lon": 74.8140},
        {"name": "IOCL Bongaigaon", "tag": "REFINERY · INDIA", "lat": 26.4680, "lon": 90.5350},
        {"name": "HPCL Mumbai", "tag": "REFINERY · INDIA", "lat": 19.0480, "lon": 72.8520},
        {"name": "CPCL Chennai", "tag": "REFINERY · INDIA", "lat": 13.1470, "lon": 80.2890},
        # Global
        {"name": "Saudi Aramco Ras Tanura", "tag": "CRUDE EXPORT · SAUDI", "lat": 26.6447, "lon": 50.1592},
        {"name": "Shell Pernis Netherlands", "tag": "REFINERY · NL", "lat": 51.8900, "lon": 4.3880},
        {"name": "Sinopec Zhenhai", "tag": "REFINERY · CHINA", "lat": 29.9850, "lon": 121.7250},
        {"name": "Freeport LNG Texas", "tag": "LNG EXPORT · US", "lat": 28.9400, "lon": -95.3600},
        {"name": "Sabine Pass LNG", "tag": "LNG EXPORT · US", "lat": 29.7286, "lon": -93.8700},
        {"name": "Cheniere Corpus Christi", "tag": "LNG EXPORT · US", "lat": 27.8370, "lon": -97.2150},
        {"name": "Qatar RasGas LNG", "tag": "LNG EXPORT · QATAR", "lat": 25.9100, "lon": 51.5500},
        {"name": "Curtis Island LNG Australia", "tag": "LNG EXPORT · AUS", "lat": -23.6000, "lon": 151.2400},
        {"name": "Nigeria Bonny LNG", "tag": "LNG EXPORT · NGA", "lat": 4.4390, "lon": 7.1510},
        {"name": "Permian Basin Oil Rigs TX", "tag": "OIL PRODUCTION · US", "lat": 31.9973, "lon": -102.0779},
    ],
    "materials": [
        # US
        {"name": "Nevada Gold Mines Carlin", "tag": "GOLD MINE · US", "lat": 40.7160, "lon": -116.1190},
        {"name": "Bingham Canyon Copper Utah", "tag": "COPPER MINE · US", "lat": 40.5243, "lon": -112.1509},
        {"name": "Teck Trail Smelter Canada", "tag": "SMELTER · CA", "lat": 49.0960, "lon": -117.7140},
        {"name": "Nucor Ghent Steel KY", "tag": "STEEL MILL · US", "lat": 38.6750, "lon": -84.9450},
        {"name": "US Steel Gary Works", "tag": "STEEL MILL · US", "lat": 41.6031, "lon": -87.3320},
        {"name": "Cleveland-Cliffs Indiana Harbor", "tag": "STEEL MILL · US", "lat": 41.6680, "lon": -87.4560},
        {"name": "Nucor Memphis Steel", "tag": "STEEL MILL · US", "lat": 35.1495, "lon": -90.0490},
        {"name": "Steel Dynamics Butler IN", "tag": "STEEL MILL · US", "lat": 40.5850, "lon": -85.0050},
        {"name": "Holcim Ste. Genevieve Cement", "tag": "CEMENT · US", "lat": 37.9770, "lon": -90.0420},
        {"name": "Ash Grove Cement OK", "tag": "CEMENT · US", "lat": 36.1560, "lon": -95.9960},
        # India
        {"name": "JSW Dolvi Steel Maharashtra", "tag": "STEEL MILL · INDIA", "lat": 18.5190, "lon": 72.9900},
        {"name": "Tata Steel Jamshedpur", "tag": "STEEL MILL · INDIA", "lat": 22.8046, "lon": 86.1850},
        {"name": "SAIL Bhilai Steel Plant", "tag": "STEEL MILL · INDIA", "lat": 21.2080, "lon": 81.3830},
        {"name": "JSW Vijayanagar Steel", "tag": "STEEL MILL · INDIA", "lat": 15.1670, "lon": 76.6670},
        {"name": "Essar Hazira Steel Gujarat", "tag": "STEEL MILL · INDIA", "lat": 21.1200, "lon": 72.7640},
        {"name": "NMDC Bailadila Iron Ore", "tag": "IRON ORE · INDIA", "lat": 18.7500, "lon": 81.2500},
        {"name": "Vedanta Sterlite Copper TN", "tag": "COPPER SMELTER · INDIA", "lat": 8.7500, "lon": 77.7000},
        {"name": "HCL Khetri Copper Rajasthan", "tag": "COPPER MINE · INDIA", "lat": 28.0000, "lon": 75.8000},
        {"name": "Ultratech Cement Tadipatri", "tag": "CEMENT · INDIA", "lat": 14.9050, "lon": 78.0110},
        {"name": "Ambuja Cement Bhatinda", "tag": "CEMENT · INDIA", "lat": 30.2100, "lon": 74.9500},
        # Global
        {"name": "BHP Escondida Copper Chile", "tag": "COPPER MINE · CL", "lat": -24.2500, "lon": -69.0700},
        {"name": "Rio Tinto Pilbara Iron Ore", "tag": "IRON ORE · AUS", "lat": -22.7000, "lon": 117.7500},
        {"name": "Glencore Collahuasi Copper", "tag": "COPPER MINE · CL", "lat": -20.9700, "lon": -68.7000},
        {"name": "Vale Carajas Iron Ore Brazil", "tag": "IRON ORE · BR", "lat": -6.0667, "lon": -50.1333},
        {"name": "POSCO Pohang Steel S Korea", "tag": "STEEL MILL · KR", "lat": 36.0190, "lon": 129.3430},
        {"name": "Baosteel Shanghai", "tag": "STEEL MILL · CN", "lat": 31.4040, "lon": 121.4960},
        {"name": "Nippon Steel Kimitsu Japan", "tag": "STEEL MILL · JP", "lat": 35.3160, "lon": 139.9150},
        {"name": "ArcelorMittal Dofasco Canada", "tag": "STEEL MILL · CA", "lat": 43.2470, "lon": -79.8550},
        {"name": "Lafarge Cement Plant France", "tag": "CEMENT · FR", "lat": 43.8500, "lon": 5.3800},
        {"name": "Heidelberg Materials Germany", "tag": "CEMENT · DE", "lat": 49.4100, "lon": 8.7100},
    ],
    "industrials": [
        # US
        {"name": "Boeing Everett Factory WA", "tag": "AIRCRAFT MFG · US", "lat": 47.9209, "lon": -122.2615},
        {"name": "Ford Dearborn Truck MI", "tag": "AUTO ASSEMBLY · US", "lat": 42.3016, "lon": -83.1583},
        {"name": "GM Arlington Assembly TX", "tag": "AUTO ASSEMBLY · US", "lat": 32.7236, "lon": -97.1154},
        {"name": "Tesla Fremont Factory CA", "tag": "EV ASSEMBLY · US", "lat": 37.4924, "lon": -121.9464},
        {"name": "UPS Worldport Louisville KY", "tag": "AIR CARGO HUB · US", "lat": 38.1781, "lon": -85.7360},
        {"name": "FedEx Memphis Superhub", "tag": "AIR CARGO HUB · US", "lat": 35.0423, "lon": -89.9762},
        {"name": "BNSF Chicago Rail Yard", "tag": "RAIL YARD · US", "lat": 41.8300, "lon": -87.7500},
        {"name": "Union Pacific Bailey Yard NE", "tag": "RAIL YARD · US", "lat": 41.1430, "lon": -101.0190},
        {"name": "LAX Airport Parking CA", "tag": "AIRPORT · US", "lat": 33.9425, "lon": -118.4081},
        {"name": "JFK Airport Cargo NY", "tag": "AIRPORT · US", "lat": 40.6413, "lon": -73.7781},
        # India
        {"name": "Maruti Suzuki Manesar", "tag": "AUTO ASSEMBLY · INDIA", "lat": 28.3560, "lon": 76.9400},
        {"name": "Tata Motors Pune", "tag": "AUTO ASSEMBLY · INDIA", "lat": 18.6298, "lon": 73.7997},
        {"name": "Hero MotoCorp Dharuhera", "tag": "TWO-WHEELER MFG · INDIA", "lat": 28.2080, "lon": 76.7870},
        {"name": "TVS Hosur TN", "tag": "TWO-WHEELER MFG · INDIA", "lat": 12.7409, "lon": 77.8253},
        {"name": "Amazon Hyderabad Fulfillment", "tag": "E-COMMERCE DC · INDIA", "lat": 17.4000, "lon": 78.5000},
        {"name": "Flipkart Bhiwandi Maharashtra", "tag": "E-COMMERCE DC · INDIA", "lat": 19.2813, "lon": 73.0547},
        {"name": "Mumbai Airport Cargo", "tag": "AIRPORT · INDIA", "lat": 19.0896, "lon": 72.8656},
        {"name": "Delhi IGI T3 Parking", "tag": "AIRPORT · INDIA", "lat": 28.5562, "lon": 77.1000},
        {"name": "ICD Sanand Rail Yard Gujarat", "tag": "RAIL ICD · INDIA", "lat": 22.9900, "lon": 72.3800},
        {"name": "Mundra ICD Container Yard", "tag": "CONTAINER PORT · INDIA", "lat": 22.8500, "lon": 69.7000},
        # Global
        {"name": "Airbus Toulouse Final Assembly", "tag": "AIRCRAFT MFG · FR", "lat": 43.6054, "lon": 1.4470},
        {"name": "Toyota Georgetown KY", "tag": "AUTO ASSEMBLY · US", "lat": 38.2098, "lon": -84.5555},
        {"name": "VW Wolfsburg Germany", "tag": "AUTO ASSEMBLY · DE", "lat": 52.4200, "lon": 10.7900},
        {"name": "Samsung Gumi S Korea", "tag": "ELECTRONICS MFG · KR", "lat": 36.1190, "lon": 128.3440},
        {"name": "Foxconn Zhengzhou China", "tag": "CONTRACT MFG · CN", "lat": 34.7460, "lon": 113.6253},
        {"name": "Heathrow Airport Cargo UK", "tag": "AIRPORT · UK", "lat": 51.4700, "lon": -0.4543},
        {"name": "Shanghai Pudong Airport", "tag": "AIRPORT · CN", "lat": 31.1443, "lon": 121.8083},
        {"name": "Rotterdam Maasvlakte Rail", "tag": "CONTAINER PORT · NL", "lat": 51.9179, "lon": 4.0800},
        {"name": "Singapore Tuas Port Rail", "tag": "CONTAINER PORT · SG", "lat": 1.2870, "lon": 103.6390},
        {"name": "Dubai Jebel Ali Container Yard", "tag": "CONTAINER PORT · UAE", "lat": 24.9994, "lon": 55.0610},
    ],
    "consumer-discretionary": [
        # US
        {"name": "Walmart Bentonville HQ AR", "tag": "RETAIL HQ · US", "lat": 36.3729, "lon": -94.2088},
        {"name": "Target Minneapolis HQ MN", "tag": "RETAIL HQ · US", "lat": 44.8545, "lon": -93.2422},
        {"name": "Costco Issaquah HQ WA", "tag": "RETAIL HQ · US", "lat": 47.5301, "lon": -122.0326},
        {"name": "Home Depot Atlanta HQ GA", "tag": "RETAIL HQ · US", "lat": 33.7490, "lon": -84.3880},
        {"name": "Lowe's Mooresville HQ NC", "tag": "RETAIL HQ · US", "lat": 35.5845, "lon": -80.8098},
        {"name": "AutoNation Fort Lauderdale FL", "tag": "AUTO DEALER · US", "lat": 26.1224, "lon": -80.1373},
        {"name": "Marriott Bethesda HQ MD", "tag": "HOSPITALITY HQ · US", "lat": 38.9850, "lon": -77.0947},
        {"name": "Hilton McLean HQ VA", "tag": "HOSPITALITY HQ · US", "lat": 38.9340, "lon": -77.1760},
        {"name": "MGM Grand Vegas Valet NV", "tag": "GAMING/LEISURE · US", "lat": 36.1024, "lon": -115.1701},
        {"name": "Disney Orlando Parking FL", "tag": "THEME PARK · US", "lat": 28.3772, "lon": -81.5707},
        # India
        {"name": "Reliance Retail Mumbai HQ", "tag": "RETAIL HQ · INDIA", "lat": 19.0760, "lon": 72.8777},
        {"name": "DMart Bhandup Mumbai", "tag": "RETAIL · INDIA", "lat": 19.1600, "lon": 72.9400},
        {"name": "Big Bazaar Mumbai Central", "tag": "RETAIL · INDIA", "lat": 18.9630, "lon": 72.8320},
        {"name": "Phoenix Marketcity Mumbai", "tag": "MALL · INDIA", "lat": 19.0864, "lon": 72.9096},
        {"name": "DLF Promenade Delhi", "tag": "MALL · INDIA", "lat": 28.5672, "lon": 77.1573},
        {"name": "Forum Mall Bangalore", "tag": "MALL · INDIA", "lat": 12.9343, "lon": 77.6101},
        {"name": "Oberoi Mall Mumbai", "tag": "MALL · INDIA", "lat": 19.1540, "lon": 72.8910},
        {"name": "Maruti Arena Delhi Dealership", "tag": "AUTO DEALER · INDIA", "lat": 28.7041, "lon": 77.1025},
        {"name": "Hero Showroom Gurgaon", "tag": "TWO-WHEELER DEALER · INDIA", "lat": 28.4595, "lon": 77.0266},
        {"name": "Taj Mumbai Hotel Valet", "tag": "HOSPITALITY · INDIA", "lat": 18.9219, "lon": 72.8332},
        # Global
        {"name": "Tesco Watford HQ UK", "tag": "RETAIL HQ · UK", "lat": 51.6600, "lon": -0.4200},
        {"name": "Carrefour HQ Paris France", "tag": "RETAIL HQ · FR", "lat": 48.8589, "lon": 2.1280},
        {"name": "IKEA Almhult Sweden", "tag": "RETAIL ORIGIN · SE", "lat": 56.5500, "lon": 14.1400},
        {"name": "Toyota Tokyo HQ Lot", "tag": "AUTO HQ · JP", "lat": 35.6585, "lon": 139.7454},
        {"name": "Hyundai Ulsan HQ Korea", "tag": "AUTO ASSEMBLY · KR", "lat": 35.5384, "lon": 129.3114},
        {"name": "Tokyo Disneyland Parking JP", "tag": "THEME PARK · JP", "lat": 35.6329, "lon": 139.8803},
        {"name": "Dubai Mall Parking UAE", "tag": "MALL · UAE", "lat": 25.1972, "lon": 55.2797},
        {"name": "ION Orchard Singapore", "tag": "MALL · SG", "lat": 1.3041, "lon": 103.8318},
        {"name": "Westfield Sydney Mall AUS", "tag": "MALL · AUS", "lat": -33.8708, "lon": 151.2073},
        {"name": "Galeries Lafayette Paris", "tag": "RETAIL · FR", "lat": 48.8738, "lon": 2.3317},
    ],
    "consumer-staples": [
        # US
        {"name": "Kroger Cincinnati HQ OH", "tag": "GROCERY HQ · US", "lat": 39.1031, "lon": -84.5120},
        {"name": "Albertsons Boise HQ ID", "tag": "GROCERY HQ · US", "lat": 43.6150, "lon": -116.2023},
        {"name": "Publix Lakeland HQ FL", "tag": "GROCERY HQ · US", "lat": 28.0395, "lon": -81.9498},
        {"name": "McDonald's Chicago HQ IL", "tag": "QSR HQ · US", "lat": 41.8827, "lon": -87.6233},
        {"name": "Starbucks Seattle HQ WA", "tag": "QSR HQ · US", "lat": 47.5480, "lon": -122.3210},
        {"name": "PepsiCo Purchase NY", "tag": "BEVERAGE HQ · US", "lat": 41.0534, "lon": -73.7162},
        {"name": "Coca-Cola Atlanta HQ GA", "tag": "BEVERAGE HQ · US", "lat": 33.7937, "lon": -84.3863},
        {"name": "Whole Foods Austin HQ TX", "tag": "GROCERY HQ · US", "lat": 30.2672, "lon": -97.7431},
        {"name": "Trader Joe's Monrovia HQ CA", "tag": "GROCERY HQ · US", "lat": 34.1478, "lon": -117.9946},
        {"name": "Costco Seattle Stores WA", "tag": "WAREHOUSE RETAIL · US", "lat": 47.5301, "lon": -122.0326},
        # India
        {"name": "Future Retail Mumbai HQ", "tag": "GROCERY HQ · INDIA", "lat": 19.0760, "lon": 72.8777},
        {"name": "Spencer's Kolkata HQ", "tag": "GROCERY HQ · INDIA", "lat": 22.5726, "lon": 88.3639},
        {"name": "More Retail Mumbai", "tag": "GROCERY · INDIA", "lat": 19.0760, "lon": 72.8777},
        {"name": "McDonald's Bandra Mumbai", "tag": "QSR · INDIA", "lat": 19.0596, "lon": 72.8295},
        {"name": "Domino's Noida HQ", "tag": "QSR HQ · INDIA", "lat": 28.5355, "lon": 77.3910},
        {"name": "KFC Bangalore Forum Mall", "tag": "QSR · INDIA", "lat": 12.9343, "lon": 77.6101},
        {"name": "Haldiram Nagpur Factory", "tag": "FOOD MFG · INDIA", "lat": 21.1458, "lon": 79.0882},
        {"name": "Amul Anand Gujarat", "tag": "DAIRY MFG · INDIA", "lat": 22.5560, "lon": 72.9500},
        {"name": "Parle Mumbai Factory", "tag": "BISCUIT MFG · INDIA", "lat": 19.1636, "lon": 72.9455},
        {"name": "Britannia Bangalore HQ", "tag": "FOOD MFG HQ · INDIA", "lat": 12.9716, "lon": 77.5946},
        # Global
        {"name": "Nestle Vevey HQ Switzerland", "tag": "CPG HQ · CH", "lat": 46.4620, "lon": 6.8420},
        {"name": "Unilever London HQ UK", "tag": "CPG HQ · UK", "lat": 51.4988, "lon": -0.1272},
        {"name": "P&G Cincinnati Plants OH", "tag": "CPG MFG · US", "lat": 39.0968, "lon": -84.5120},
        {"name": "KFC Guangzhou China", "tag": "QSR · CN", "lat": 23.1291, "lon": 113.2644},
        {"name": "Starbucks Tokyo Stores JP", "tag": "QSR · JP", "lat": 35.6762, "lon": 139.6503},
        {"name": "7-Eleven Tokyo HQ JP", "tag": "CONVENIENCE HQ · JP", "lat": 35.6762, "lon": 139.6503},
        {"name": "Carrefour Euralille France", "tag": "GROCERY · FR", "lat": 50.6292, "lon": 3.0701},
        {"name": "Woolworths Sydney AUS", "tag": "GROCERY · AUS", "lat": -33.8688, "lon": 151.2093},
        {"name": "Lotte Mart Seoul Korea", "tag": "GROCERY · KR", "lat": 37.5665, "lon": 126.9780},
        {"name": "Aeon Mall Japan", "tag": "RETAIL · JP", "lat": 35.6837, "lon": 139.8107},
    ],
    "health-care": [
        # US
        {"name": "Pfizer New York HQ", "tag": "PHARMA HQ · US", "lat": 40.7580, "lon": -73.9855},
        {"name": "J&J New Brunswick NJ", "tag": "PHARMA HQ · US", "lat": 40.4870, "lon": -74.4457},
        {"name": "Moderna Norwood MA", "tag": "BIOPHARMA · US", "lat": 42.1918, "lon": -71.1995},
        {"name": "Mayo Clinic Rochester MN", "tag": "MEDICAL CENTER · US", "lat": 44.0224, "lon": -92.4663},
        {"name": "Cleveland Clinic OH", "tag": "MEDICAL CENTER · US", "lat": 41.5021, "lon": -81.6209},
        {"name": "Johns Hopkins Baltimore MD", "tag": "MEDICAL CENTER · US", "lat": 39.2974, "lon": -76.5928},
        {"name": "UCLA Medical Center CA", "tag": "MEDICAL CENTER · US", "lat": 34.0659, "lon": -118.4448},
        {"name": "CVS Woonsocket HQ RI", "tag": "PHARMA RETAIL HQ · US", "lat": 41.9979, "lon": -71.5148},
        {"name": "Walgreens Deerfield HQ IL", "tag": "PHARMA RETAIL HQ · US", "lat": 42.1716, "lon": -87.8437},
        {"name": "HCA Nashville HQ TN", "tag": "HOSPITAL HQ · US", "lat": 36.1627, "lon": -86.7816},
        # India
        {"name": "Apollo Chennai HQ Hospital", "tag": "HOSPITAL · INDIA", "lat": 13.0827, "lon": 80.2707},
        {"name": "Fortis Gurgaon Hospital", "tag": "HOSPITAL · INDIA", "lat": 28.4595, "lon": 77.0266},
        {"name": "Max Delhi Saket Hospital", "tag": "HOSPITAL · INDIA", "lat": 28.5244, "lon": 77.2090},
        {"name": "Sun Pharma Halol Gujarat", "tag": "PHARMA MFG · INDIA", "lat": 22.5000, "lon": 73.4700},
        {"name": "Dr. Reddy's Hyderabad", "tag": "PHARMA MFG · INDIA", "lat": 17.3850, "lon": 78.4867},
        {"name": "Cipla Patalganga Maharashtra", "tag": "PHARMA MFG · INDIA", "lat": 19.0550, "lon": 73.2000},
        {"name": "Lupin Pune", "tag": "PHARMA MFG · INDIA", "lat": 18.5204, "lon": 73.8567},
        {"name": "Aurobindo Hyderabad", "tag": "PHARMA MFG · INDIA", "lat": 17.3850, "lon": 78.4867},
        {"name": "AIIMS Delhi OPD", "tag": "MEDICAL CENTER · INDIA", "lat": 28.5672, "lon": 77.2100},
        {"name": "PGIMER Chandigarh", "tag": "MEDICAL CENTER · INDIA", "lat": 30.7630, "lon": 76.7784},
        # Global
        {"name": "Novartis Basel HQ Switzerland", "tag": "PHARMA HQ · CH", "lat": 47.5570, "lon": 7.5886},
        {"name": "Roche Basel Campus CH", "tag": "PHARMA HQ · CH", "lat": 47.5700, "lon": 7.5800},
        {"name": "AstraZeneca Cambridge UK", "tag": "BIOPHARMA · UK", "lat": 52.2053, "lon": 0.1218},
        {"name": "Sanofi Gentilly France", "tag": "PHARMA HQ · FR", "lat": 48.8144, "lon": 2.3397},
        {"name": "Takeda Tokyo HQ JP", "tag": "PHARMA HQ · JP", "lat": 35.6762, "lon": 139.6503},
        {"name": "Toronto General Hospital CA", "tag": "MEDICAL CENTER · CA", "lat": 43.6581, "lon": -79.3877},
        {"name": "Singapore General Hospital", "tag": "MEDICAL CENTER · SG", "lat": 1.2793, "lon": 103.8353},
        {"name": "Shanghai Ruijin Hospital CN", "tag": "MEDICAL CENTER · CN", "lat": 31.2165, "lon": 121.4737},
        {"name": "Seoul Asan Medical Center KR", "tag": "MEDICAL CENTER · KR", "lat": 37.5270, "lon": 127.1060},
        {"name": "Sydney Royal Prince Alfred AUS", "tag": "MEDICAL CENTER · AUS", "lat": -33.8883, "lon": 151.1803},
    ],
    "financials": [
        # US
        {"name": "JPMorgan Columbus Campus OH", "tag": "MEGABANK · US", "lat": 39.9612, "lon": -82.9988},
        {"name": "Bank of America Charlotte HQ", "tag": "MEGABANK · US", "lat": 35.2271, "lon": -80.8431},
        {"name": "Wells Fargo San Francisco", "tag": "MEGABANK · US", "lat": 37.7929, "lon": -122.3969},
        {"name": "Citi HQ Long Island NY", "tag": "MEGABANK · US", "lat": 40.7252, "lon": -73.6350},
        {"name": "Goldman Sachs Jersey City NJ", "tag": "INVESTMENT BANK · US", "lat": 40.7282, "lon": -74.0776},
        {"name": "NYSE 11 Wall St NY", "tag": "STOCK EXCHANGE · US", "lat": 40.7069, "lon": -74.0089},
        {"name": "CME Chicago HQ IL", "tag": "FUTURES EXCHANGE · US", "lat": 41.8827, "lon": -87.6344},
        {"name": "Visa Foster City CA", "tag": "PAYMENTS · US", "lat": 37.5541, "lon": -122.2760},
        {"name": "Mastercard Purchase NY", "tag": "PAYMENTS · US", "lat": 41.0534, "lon": -73.7162},
        {"name": "Fidelity Boston Campus MA", "tag": "ASSET MGMT · US", "lat": 42.3584, "lon": -71.0598},
        # India
        {"name": "HDFC Mumbai HQ", "tag": "BANK · INDIA", "lat": 19.0760, "lon": 72.8777},
        {"name": "ICICI Mumbai Campus", "tag": "BANK · INDIA", "lat": 19.0178, "lon": 72.8478},
        {"name": "SBI Mumbai Local Office", "tag": "BANK · INDIA", "lat": 18.9220, "lon": 72.8347},
        {"name": "Axis Bank Ahmedabad", "tag": "BANK · INDIA", "lat": 23.0225, "lon": 72.5714},
        {"name": "Kotak Mumbai HQ", "tag": "BANK · INDIA", "lat": 19.0760, "lon": 72.8777},
        {"name": "NSE Mumbai BKC", "tag": "STOCK EXCHANGE · INDIA", "lat": 19.0653, "lon": 72.8680},
        {"name": "BSE Pherozeshah Mehta Rd", "tag": "STOCK EXCHANGE · INDIA", "lat": 18.9322, "lon": 72.8337},
        {"name": "Zerodha Bangalore Office", "tag": "FINTECH · INDIA", "lat": 12.9716, "lon": 77.5946},
        {"name": "Paytm Noida Campus", "tag": "FINTECH · INDIA", "lat": 28.5355, "lon": 77.3910},
        {"name": "PhonePe Bangalore HQ", "tag": "FINTECH · INDIA", "lat": 12.9716, "lon": 77.5946},
        # Global
        {"name": "HSBC London Canary Wharf", "tag": "MEGABANK · UK", "lat": 51.5054, "lon": -0.0235},
        {"name": "Deutsche Bank Frankfurt DE", "tag": "INVESTMENT BANK · DE", "lat": 50.1109, "lon": 8.6821},
        {"name": "UBS Zurich HQ CH", "tag": "BANK · CH", "lat": 47.3769, "lon": 8.5417},
        {"name": "Tokyo Stock Exchange JP", "tag": "STOCK EXCHANGE · JP", "lat": 35.6839, "lon": 139.7744},
        {"name": "HKEX Exchange Square HK", "tag": "STOCK EXCHANGE · HK", "lat": 22.2847, "lon": 114.1574},
        {"name": "Shanghai Stock Exchange CN", "tag": "STOCK EXCHANGE · CN", "lat": 31.2304, "lon": 121.4737},
        {"name": "Singapore Exchange SGX", "tag": "STOCK EXCHANGE · SG", "lat": 1.2800, "lon": 103.8500},
        {"name": "ASX Sydney Australia", "tag": "STOCK EXCHANGE · AUS", "lat": -33.8688, "lon": 151.2093},
        {"name": "Euronext Paris FR", "tag": "STOCK EXCHANGE · FR", "lat": 48.8674, "lon": 2.3453},
        {"name": "Nasdaq Stockholm SE", "tag": "STOCK EXCHANGE · SE", "lat": 59.3293, "lon": 18.0686},
    ],
    "information-technology": [
        # US
        {"name": "Apple Cupertino Campus CA", "tag": "TECH HQ · US", "lat": 37.3346, "lon": -122.0090},
        {"name": "Google Mountain View CA", "tag": "TECH HQ · US", "lat": 37.4220, "lon": -122.0841},
        {"name": "Microsoft Redmond WA", "tag": "TECH HQ · US", "lat": 47.6423, "lon": -122.1391},
        {"name": "Amazon Seattle Campus WA", "tag": "TECH HQ · US", "lat": 47.6204, "lon": -122.3491},
        {"name": "Meta Menlo Park CA", "tag": "TECH HQ · US", "lat": 37.4845, "lon": -122.1477},
        {"name": "Nvidia Santa Clara CA", "tag": "GPU DESIGN · US", "lat": 37.3688, "lon": -121.9689},
        {"name": "Intel Hillsboro OR", "tag": "CHIP FAB · US", "lat": 45.5231, "lon": -122.9000},
        {"name": "TSMC Arizona Fab AZ", "tag": "CHIP FAB · US", "lat": 33.4255, "lon": -112.0040},
        {"name": "Equinix Ashburn DC VA", "tag": "DATA CENTER · US", "lat": 39.0437, "lon": -77.4875},
        {"name": "Digital Realty Chicago IL", "tag": "DATA CENTER · US", "lat": 41.8827, "lon": -87.6233},
        # India
        {"name": "Infosys Bangalore EC2 Campus", "tag": "IT SERVICES · INDIA", "lat": 12.8344, "lon": 77.6637},
        {"name": "TCS Hyderabad", "tag": "IT SERVICES · INDIA", "lat": 17.4399, "lon": 78.3489},
        {"name": "Wipro Bangalore Campus", "tag": "IT SERVICES · INDIA", "lat": 12.9141, "lon": 77.6506},
        {"name": "HCL Noida", "tag": "IT SERVICES · INDIA", "lat": 28.5355, "lon": 77.3910},
        {"name": "Tech Mahindra Pune", "tag": "IT SERVICES · INDIA", "lat": 18.5204, "lon": 73.8567},
        {"name": "CtrlS Hyderabad Data Center", "tag": "DATA CENTER · INDIA", "lat": 17.3850, "lon": 78.4867},
        {"name": "NTT Mumbai DC", "tag": "DATA CENTER · INDIA", "lat": 19.0760, "lon": 72.8777},
        {"name": "Sify Chennai DC", "tag": "DATA CENTER · INDIA", "lat": 13.0827, "lon": 80.2707},
        {"name": "AWS Mumbai Region DC", "tag": "CLOUD DC · INDIA", "lat": 19.0760, "lon": 72.8777},
        {"name": "Microsoft Hyderabad Campus", "tag": "TECH HQ · INDIA", "lat": 17.4850, "lon": 78.3700},
        # Global
        {"name": "Samsung Suwon Korea", "tag": "ELECTRONICS MFG · KR", "lat": 37.2636, "lon": 127.0286},
        {"name": "TSMC Hsinchu Taiwan", "tag": "CHIP FAB · TW", "lat": 24.7891, "lon": 120.9965},
        {"name": "Foxconn Shenzhen CN", "tag": "CONTRACT MFG · CN", "lat": 22.5450, "lon": 114.0543},
        {"name": "Tencent Shenzhen Campus CN", "tag": "TECH HQ · CN", "lat": 22.5400, "lon": 113.9340},
        {"name": "Alibaba Hangzhou CN", "tag": "TECH HQ · CN", "lat": 30.2741, "lon": 120.1551},
        {"name": "Google Dublin DC Ireland", "tag": "CLOUD DC · IE", "lat": 53.3498, "lon": -6.2603},
        {"name": "Microsoft Dublin DC Ireland", "tag": "CLOUD DC · IE", "lat": 53.3498, "lon": -6.2603},
        {"name": "Equinix Singapore", "tag": "DATA CENTER · SG", "lat": 1.3521, "lon": 103.8198},
        {"name": "Digital Realty Tokyo JP", "tag": "DATA CENTER · JP", "lat": 35.6762, "lon": 139.6503},
        {"name": "Yandex Moscow Campus RU", "tag": "TECH HQ · RU", "lat": 55.7335, "lon": 37.5873},
    ],
    "communication-services": [
        # US
        {"name": "Verizon NYC HQ", "tag": "TELECOM HQ · US", "lat": 40.7580, "lon": -74.0027},
        {"name": "AT&T Dallas Campus TX", "tag": "TELECOM HQ · US", "lat": 32.7813, "lon": -96.7974},
        {"name": "T-Mobile Bellevue WA", "tag": "TELECOM HQ · US", "lat": 47.6152, "lon": -122.1944},
        {"name": "Comcast Philly HQ PA", "tag": "CABLE/MEDIA HQ · US", "lat": 39.9526, "lon": -75.1652},
        {"name": "Disney Burbank Lot CA", "tag": "MEDIA/CONTENT · US", "lat": 34.1575, "lon": -118.3267},
        {"name": "Netflix Los Gatos CA", "tag": "STREAMING HQ · US", "lat": 37.2358, "lon": -121.9624},
        {"name": "Warner Bros Burbank CA", "tag": "MEDIA/CONTENT · US", "lat": 34.1548, "lon": -118.3373},
        {"name": "Alphabet NYC Chelsea", "tag": "TECH HQ · US", "lat": 40.7417, "lon": -74.0021},
        {"name": "Meta NYC Offices", "tag": "SOCIAL MEDIA · US", "lat": 40.7374, "lon": -73.9931},
        {"name": "Twitter SF HQ CA", "tag": "SOCIAL MEDIA · US", "lat": 37.7773, "lon": -122.4176},
        # India
        {"name": "Bharti Airtel Gurgaon HQ", "tag": "TELECOM HQ · INDIA", "lat": 28.4595, "lon": 77.0266},
        {"name": "Reliance Jio Navi Mumbai", "tag": "TELECOM HQ · INDIA", "lat": 19.0330, "lon": 73.0297},
        {"name": "Vodafone Idea Mumbai", "tag": "TELECOM · INDIA", "lat": 19.0760, "lon": 72.8777},
        {"name": "Tata Comm Mumbai Campus", "tag": "TELECOM · INDIA", "lat": 19.0760, "lon": 72.8777},
        {"name": "Zee Mumbai HQ", "tag": "MEDIA · INDIA", "lat": 19.0760, "lon": 72.8777},
        {"name": "Sun TV Chennai", "tag": "MEDIA · INDIA", "lat": 13.0827, "lon": 80.2707},
        {"name": "Network18 Noida", "tag": "MEDIA · INDIA", "lat": 28.5355, "lon": 77.3910},
        {"name": "Sony Pictures Mumbai", "tag": "MEDIA · INDIA", "lat": 19.0760, "lon": 72.8777},
        {"name": "Star India Mumbai", "tag": "MEDIA · INDIA", "lat": 19.0760, "lon": 72.8777},
        {"name": "Viacom18 Mumbai", "tag": "MEDIA · INDIA", "lat": 19.0760, "lon": 72.8777},
        # Global
        {"name": "China Mobile Beijing CN", "tag": "TELECOM HQ · CN", "lat": 39.9042, "lon": 116.4074},
        {"name": "SoftBank Tokyo JP", "tag": "TELECOM HQ · JP", "lat": 35.6762, "lon": 139.6503},
        {"name": "NTT Docomo Tokyo JP", "tag": "TELECOM · JP", "lat": 35.6762, "lon": 139.6503},
        {"name": "BBC London HQ UK", "tag": "MEDIA HQ · UK", "lat": 51.5183, "lon": -0.2241},
        {"name": "Sky UK Osterley", "tag": "MEDIA HQ · UK", "lat": 51.4964, "lon": -0.3495},
        {"name": "Vivendi Paris FR", "tag": "MEDIA HQ · FR", "lat": 48.8674, "lon": 2.3453},
        {"name": "Tencent Guangzhou CN", "tag": "TECH/MEDIA · CN", "lat": 23.1291, "lon": 113.2644},
        {"name": "Baidu Beijing CN", "tag": "TECH/MEDIA · CN", "lat": 39.9920, "lon": 116.3040},
        {"name": "Sina Weibo Beijing CN", "tag": "SOCIAL MEDIA · CN", "lat": 39.9042, "lon": 116.4074},
        {"name": "Kakao Seoul KR", "tag": "SOCIAL MEDIA · KR", "lat": 37.3945, "lon": 127.1117},
    ],
    "utilities": [
        # US
        {"name": "Palo Verde Nuclear AZ", "tag": "NUCLEAR POWER · US", "lat": 33.3889, "lon": -112.8625},
        {"name": "Grand Coulee Dam WA", "tag": "HYDRO POWER · US", "lat": 47.9650, "lon": -118.9820},
        {"name": "Hoover Dam NV", "tag": "HYDRO POWER · US", "lat": 36.0161, "lon": -114.7377},
        {"name": "TVA Sequoyah Nuclear TN", "tag": "NUCLEAR POWER · US", "lat": 35.2246, "lon": -85.0945},
        {"name": "Entergy Waterford LA", "tag": "NUCLEAR POWER · US", "lat": 29.9961, "lon": -90.4725},
        {"name": "NextEra Juno Beach FL", "tag": "SOLAR/WIND HQ · US", "lat": 26.8690, "lon": -80.0540},
        {"name": "Duke Raleigh HQ NC", "tag": "UTILITY HQ · US", "lat": 35.7796, "lon": -78.6382},
        {"name": "Southern Co Atlanta GA", "tag": "UTILITY HQ · US", "lat": 33.7490, "lon": -84.3880},
        {"name": "Dominion Richmond VA", "tag": "UTILITY HQ · US", "lat": 37.5407, "lon": -77.4360},
        {"name": "Exelon Chicago IL", "tag": "UTILITY HQ · US", "lat": 41.8827, "lon": -87.6233},
        # India
        {"name": "Mundra Ultra Mega Power Gujarat", "tag": "THERMAL POWER · INDIA", "lat": 22.8380, "lon": 69.6980},
        {"name": "Sipat Thermal Chhattisgarh", "tag": "THERMAL POWER · INDIA", "lat": 22.1660, "lon": 82.2640},
        {"name": "Kudankulam Nuclear TN", "tag": "NUCLEAR POWER · INDIA", "lat": 8.1717, "lon": 77.7138},
        {"name": "NTPC Vindhyachal UP", "tag": "THERMAL POWER · INDIA", "lat": 24.1190, "lon": 82.6680},
        {"name": "Rihand Thermal UP", "tag": "THERMAL POWER · INDIA", "lat": 24.0220, "lon": 82.7430},
        {"name": "Talcher Thermal Odisha", "tag": "THERMAL POWER · INDIA", "lat": 20.9500, "lon": 85.2300},
        {"name": "Ramagundam Thermal Telangana", "tag": "THERMAL POWER · INDIA", "lat": 18.7700, "lon": 79.4740},
        {"name": "Dadri Gas UP", "tag": "GAS POWER · INDIA", "lat": 28.5500, "lon": 77.5900},
        {"name": "Simhadri Thermal AP", "tag": "THERMAL POWER · INDIA", "lat": 17.5900, "lon": 83.0700},
        {"name": "Korba Thermal Chhattisgarh", "tag": "THERMAL POWER · INDIA", "lat": 22.3580, "lon": 82.6850},
        # Global
        {"name": "Three Gorges Dam China", "tag": "HYDRO POWER · CN", "lat": 30.8234, "lon": 111.0027},
        {"name": "Kashiwazaki Nuclear Japan", "tag": "NUCLEAR POWER · JP", "lat": 37.4247, "lon": 138.5974},
        {"name": "Sizewell Nuclear UK", "tag": "NUCLEAR POWER · UK", "lat": 52.2139, "lon": 1.6194},
        {"name": "EDF Gravelines France", "tag": "NUCLEAR POWER · FR", "lat": 51.0070, "lon": 2.1290},
        {"name": "RWE Neurath Coal Germany", "tag": "COAL POWER · DE", "lat": 51.0000, "lon": 6.6540},
        {"name": "Enel Civitavecchia Italy", "tag": "POWER PLANT · IT", "lat": 42.1025, "lon": 11.7670},
        {"name": "Iberdrola Nucier Spain", "tag": "NUCLEAR POWER · ES", "lat": 40.6830, "lon": -3.7492},
        {"name": "KEPCO Ulchin Nuclear Korea", "tag": "NUCLEAR POWER · KR", "lat": 37.0980, "lon": 129.3800},
        {"name": "Tokyo Electric Kashiwazaki JP", "tag": "NUCLEAR POWER · JP", "lat": 37.4247, "lon": 138.5974},
        {"name": "Hydro-Quebec James Bay CA", "tag": "HYDRO POWER · CA", "lat": 53.8300, "lon": -77.4700},
    ],
    "real-estate": [
        # US
        {"name": "Mall of America Bloomington MN", "tag": "RETAIL REIT · US", "lat": 44.8549, "lon": -93.2422},
        {"name": "King of Prussia Mall PA", "tag": "RETAIL REIT · US", "lat": 40.0854, "lon": -75.3824},
        {"name": "Sawgrass Mills FL", "tag": "RETAIL REIT · US", "lat": 26.1434, "lon": -80.3302},
        {"name": "Amazon SEA1 Seattle Warehouse", "tag": "INDUSTRIAL REIT · US", "lat": 47.5480, "lon": -122.3210},
        {"name": "Prologis DC1 Chicago IL", "tag": "INDUSTRIAL REIT · US", "lat": 41.5250, "lon": -88.0817},
        {"name": "Simon Property HQ IN", "tag": "REIT HQ · US", "lat": 39.7684, "lon": -86.1581},
        {"name": "Kimco Realty Jericho NY", "tag": "RETAIL REIT · US", "lat": 40.7910, "lon": -73.5440},
        {"name": "Equity Residential Chicago IL", "tag": "RESIDENTIAL REIT · US", "lat": 41.8827, "lon": -87.6233},
        {"name": "AvalonBay Arlington VA", "tag": "RESIDENTIAL REIT · US", "lat": 38.8816, "lon": -77.0910},
        {"name": "UDR Aurora CO", "tag": "RESIDENTIAL REIT · US", "lat": 39.7294, "lon": -104.8319},
        # India
        {"name": "Lulu Mall Kochi Kerala", "tag": "MALL · INDIA", "lat": 9.9981, "lon": 76.3018},
        {"name": "VR Bengaluru Mall", "tag": "MALL · INDIA", "lat": 13.0100, "lon": 77.5500},
        {"name": "Express Avenue Chennai", "tag": "MALL · INDIA", "lat": 13.0569, "lon": 80.2590},
        {"name": "Inorbit Hyderabad Mall", "tag": "MALL · INDIA", "lat": 17.4570, "lon": 78.3640},
        {"name": "Mantri Square Mall Bangalore", "tag": "MALL · INDIA", "lat": 13.0004, "lon": 77.5703},
        {"name": "Ambience Mall Gurgaon", "tag": "MALL · INDIA", "lat": 28.5011, "lon": 77.0957},
        {"name": "Elante Mall Chandigarh", "tag": "MALL · INDIA", "lat": 30.7333, "lon": 76.7794},
        {"name": "South City Mall Kolkata", "tag": "MALL · INDIA", "lat": 22.4974, "lon": 88.3570},
        {"name": "Reliance Retail Warehouses Mumbai", "tag": "LOGISTICS · INDIA", "lat": 19.0760, "lon": 72.8777},
        {"name": "Flipkart Warehouses Bhiwandi", "tag": "LOGISTICS · INDIA", "lat": 19.2813, "lon": 73.0547},
        # Global
        {"name": "Dubai Mall UAE", "tag": "MALL · UAE", "lat": 25.1972, "lon": 55.2797},
        {"name": "Westfield London UK", "tag": "MALL · UK", "lat": 51.5074, "lon": -0.2228},
        {"name": "ION Orchard Singapore", "tag": "MALL · SG", "lat": 1.3041, "lon": 103.8318},
        {"name": "Causeway Bay Sogo HK", "tag": "MALL · HK", "lat": 22.2799, "lon": 114.1860},
        {"name": "Lotte World Mall Seoul KR", "tag": "MALL · KR", "lat": 37.5113, "lon": 127.0982},
        {"name": "SM Megamall Manila PH", "tag": "MALL · PH", "lat": 14.5832, "lon": 121.0560},
        {"name": "Plaza Indonesia Jakarta", "tag": "MALL · ID", "lat": -6.1944, "lon": 106.8229},
        {"name": "Paragon Beijing CN", "tag": "MALL · CN", "lat": 39.9042, "lon": 116.4074},
        {"name": "Times Square Sydney AUS", "tag": "MALL · AUS", "lat": -33.8688, "lon": 151.2093},
        {"name": "Galeries Lafayette Paris FR", "tag": "RETAIL · FR", "lat": 48.8738, "lon": 2.3317},
    ],
}

 
 
# ══════════════════════════════════════════════════════════════════════════════
# SECTOR NEWS SCRAPERS
# ══════════════════════════════════════════════════════════════════════════════
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
        keywords = [k.lower() for k in SECTORS[sector_id]["keywords"]]
        for item in soup.find_all("item"):
            title = item.find("title"); link = item.find("link"); pub_date = item.find("pubDate")
            if not title or not link: continue
            title_text = title.get_text(strip=True)
            if not any(kw in title_text.lower() for kw in keywords): continue
            href = link.get_text(strip=True)
            pub = pub_date.get_text(strip=True) if pub_date else ""
            try:
                dt = datetime.strptime(pub[:25], "%a, %d %b %Y %H:%M:%S")
                pub = dt.strftime("%b %d, %Y %H:%M")
            except: pub = pub[:30]
            results.append({"title": title_text, "url": href, "source": source, "published": pub, "sector": sector_id})
            if len(results) >= 8: break
    except: pass
    return results
 
 
def scrape_yahoo_finance_news(s, c): return _rss_scrape("https://finance.yahoo.com/news/rssindex", "Yahoo Finance", s, c)
def scrape_cnbc_news(s, c):         return _rss_scrape("https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=10000664", "CNBC", s, c)
def scrape_marketwatch(s, c):       return _rss_scrape("https://feeds.marketwatch.com/marketwatch/topstories/", "MarketWatch", s, c)
def scrape_benzinga(s, c):          return _rss_scrape("https://www.benzinga.com/feeds/news", "Benzinga", s, c)
def scrape_ft(s, c):                return _rss_scrape("https://www.ft.com/rss/home/us", "Financial Times", s, c)
def scrape_wsj(s, c):               return _rss_scrape("https://feeds.a.dj.com/rss/RSSMarketsMain.xml", "Wall Street Journal", s, c)
 
 
def scrape_reuters(sector_id, client):
    results = []
    try:
        query = quote_plus(SECTORS[sector_id]["queries"][0])
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
    scrapers = [scrape_yahoo_finance_news, scrape_cnbc_news, scrape_marketwatch,
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
 
 
# ══════════════════════════════════════════════════════════════════════════════
# STOCK DATA — POPULAR STOCKS / PERIODS / INDICATORS
# ══════════════════════════════════════════════════════════════════════════════
POPULAR_STOCKS = [
    ("AAPL","Apple"), ("GOOGL","Google"), ("MSFT","Microsoft"), ("TSLA","Tesla"),
    ("AMZN","Amazon"), ("NVDA","NVIDIA"), ("TCS.NS","TCS"), ("RELIANCE.NS","Reliance")
]
PERIODS = [("1mo","1 Month"),("3mo","3 Months"),("6mo","6 Months"),("1y","1 Year"),("2y","2 Years"),("5y","5 Years")]
VALID_PERIODS = {p[0] for p in PERIODS}
INDICATORS = [("sma","SMA"),("bb","Bollinger"),("rsi","RSI"),("macd","MACD"),("vol","Volume")]
 
 
# ══════════════════════════════════════════════════════════════════════════════
# YAHOO FINANCE SCRAPER
# ══════════════════════════════════════════════════════════════════════════════
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
    from io import StringIO
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
    try:
        s, _ = _get_auth(ticker)
        t = yf.Ticker(ticker, session=s)
        return (t.fast_info.get("longName") or t.info.get("shortName") or "").strip() or ticker
    except Exception: return ticker
 
 
def _get_fundamentals(ticker):
    """Fetch key fundamental data from yfinance."""
    try:
        s, _ = _get_auth(ticker)
        t = yf.Ticker(ticker, session=s)
        info = t.info or {}
        return {
            "pe_ratio":        info.get("trailingPE"),
            "forward_pe":      info.get("forwardPE"),
            "pb_ratio":        info.get("priceToBook"),
            "ps_ratio":        info.get("priceToSalesTrailing12Months"),
            "market_cap":      info.get("marketCap"),
            "enterprise_value":info.get("enterpriseValue"),
            "revenue_growth":  info.get("revenueGrowth"),
            "earnings_growth": info.get("earningsGrowth"),
            "profit_margin":   info.get("profitMargins"),
            "roe":             info.get("returnOnEquity"),
            "debt_to_equity":  info.get("debtToEquity"),
            "current_ratio":   info.get("currentRatio"),
            "free_cashflow":   info.get("freeCashflow"),
            "dividend_yield":  info.get("dividendYield"),
            "beta":            info.get("beta"),
            "sector":          info.get("sector"),
            "industry":        info.get("industry"),
            "country":         info.get("country"),
            "analyst_target":  info.get("targetMeanPrice"),
            "analyst_rating":  info.get("recommendationKey"),
            "num_analysts":    info.get("numberOfAnalystOpinions"),
            "short_ratio":     info.get("shortRatio"),
            "inst_ownership":  info.get("heldPercentInstitutions"),
            "insider_ownership": info.get("heldPercentInsiders"),
            "52w_high":        info.get("fiftyTwoWeekHigh"),
            "52w_low":         info.get("fiftyTwoWeekLow"),
            "avg_volume":      info.get("averageVolume"),
            "float_shares":    info.get("floatShares"),
        }
    except Exception:
        return {}
 
 
# ══════════════════════════════════════════════════════════════════════════════
# TECHNICAL INDICATORS
# ══════════════════════════════════════════════════════════════════════════════
# ── Technical indicator helpers — native (Rust/C++) when available ────────────
def calc_sma(c, w):
    return c.rolling(w).mean()


def calc_ema(c, w):
    """EMA — Rust > C++ > pandas fallback."""
    arr = c.values.astype(np.float64)
    n   = len(arr)
    lib = _RUST_LIB or _CPP_LIB
    if lib is not None:
        ptr_in, _a = _c_arr(arr)
        ptr_out, out = _out_arr(n)
        fn = getattr(lib, "ema_rs" if _RUST_LIB else "ema")
        if _RUST_LIB:
            fn(ptr_in, ctypes.c_size_t(n), ctypes.c_size_t(int(w)), ptr_out)
        else:
            fn(ptr_in, ctypes.c_int(n), ctypes.c_int(int(w)), ptr_out)
        return pd.Series(out, index=c.index)
    return c.ewm(span=w, adjust=False).mean()


def calc_bb(c, w=20, n=2):
    sma = calc_sma(c, w)
    std = c.rolling(w).std()
    return sma + n * std, sma, sma - n * std


def calc_rsi(c, w=14):
    """RSI — Rust > C++ > pandas fallback."""
    arr = c.values.astype(np.float64)
    nn  = len(arr)
    lib = _RUST_LIB or _CPP_LIB
    if lib is not None:
        ptr_in, _a = _c_arr(arr)
        ptr_out, out = _out_arr(nn)
        if _RUST_LIB:
            _RUST_LIB.rsi_rs(ptr_in, ctypes.c_size_t(nn), ctypes.c_size_t(int(w)), ptr_out)
        else:
            _CPP_LIB.rsi_wilder(ptr_in, ctypes.c_int(nn), ctypes.c_int(int(w)), ptr_out)
        return pd.Series(out, index=c.index)
    # Pure-Python fallback
    d = c.diff(); g = d.clip(lower=0); l = -d.clip(upper=0)
    ag = g.ewm(com=w - 1, min_periods=w).mean()
    al = l.ewm(com=w - 1, min_periods=w).mean()
    return 100 - 100 / (1 + ag / al.replace(0, np.nan))


def calc_macd(c, f=12, s=26, sg=9):
    ml = calc_ema(c, f) - calc_ema(c, s)
    sl = calc_ema(ml, sg)
    return ml, sl, ml - sl


def calc_atr(h, l, c, w=14):
    """ATR — C++ > pure-Python fallback."""
    if _CPP_LIB is not None:
        ha = h.values.astype(np.float64)
        la = l.values.astype(np.float64)
        ca = c.values.astype(np.float64)
        n  = len(ca)
        ph, _h = _c_arr(ha); pl, _l = _c_arr(la); pc, _c2 = _c_arr(ca)
        ptr_out, out = _out_arr(n)
        _CPP_LIB.atr_wilder(ph, pl, pc, ctypes.c_int(n), ctypes.c_int(int(w)), ptr_out)
        return pd.Series(out, index=c.index)
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    return tr.ewm(com=w - 1, min_periods=w).mean()


def calc_obv(c, v):
    """On-Balance Volume — Rust > C++ > numpy fallback."""
    ca = c.values.astype(np.float64)
    va = v.values.astype(np.float64)
    n  = len(ca)
    lib = _RUST_LIB or _CPP_LIB
    if lib is not None:
        pc, _ca = _c_arr(ca); pv, _va = _c_arr(va)
        ptr_out, out = _out_arr(n)
        if _RUST_LIB:
            _RUST_LIB.obv_rs(pc, pv, ctypes.c_size_t(n), ptr_out)
        else:
            _CPP_LIB.obv(pc, pv, ctypes.c_int(n), ptr_out)
        return pd.Series(out, index=c.index)
    direction = np.sign(c.diff().fillna(0))
    return (direction * v).cumsum()


def calc_stoch(h, l, c, k=14, d=3):
    """Stochastic Oscillator — C++ %K > pandas fallback."""
    if _CPP_LIB is not None:
        ha = h.values.astype(np.float64)
        la = l.values.astype(np.float64)
        ca = c.values.astype(np.float64)
        n  = len(ca)
        ph, _h = _c_arr(ha); pl, _l = _c_arr(la); pc, _c2 = _c_arr(ca)
        ptr_out, out = _out_arr(n)
        _CPP_LIB.stoch_k(ph, pl, pc, ctypes.c_int(n), ctypes.c_int(int(k)), ptr_out)
        k_line = pd.Series(out, index=c.index)
        d_line = k_line.rolling(d).mean()
        return k_line, d_line
    low_min  = l.rolling(k).min()
    high_max = h.rolling(k).max()
    k_line = 100 * (c - low_min) / (high_max - low_min + 1e-10)
    d_line = k_line.rolling(d).mean()
    return k_line, d_line


def calc_williams_r(h, l, c, w=14):
    high_max = h.rolling(w).max()
    low_min  = l.rolling(w).min()
    return -100 * (high_max - c) / (high_max - low_min + 1e-10)


def calc_cmf(h, l, c, v, w=20):
    """Chaikin Money Flow."""
    mf_mult = ((c - l) - (h - c)) / (h - l + 1e-10)
    mf_vol  = mf_mult * v
    return mf_vol.rolling(w).sum() / v.rolling(w).sum()


def calc_adx(h, l, c, w=14):
    """Average Directional Index — uses native EMA internally."""
    tr  = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    dmp = (h - h.shift()).clip(lower=0)
    dmm = (l.shift() - l).clip(lower=0)
    atr = calc_ema(tr, w)
    dp  = (calc_ema(dmp, w) / atr.replace(0, np.nan)) * 100
    dm  = (calc_ema(dmm, w) / atr.replace(0, np.nan)) * 100
    dx  = (abs(dp - dm) / (dp + dm + 1e-10)) * 100
    return calc_ema(dx, w)


def calc_vwap(h, l, c, v):
    """Volume-Weighted Average Price (rolling 20-day proxy)."""
    typical = (h + l + c) / 3
    return (typical * v).rolling(20).sum() / v.rolling(20).sum()


def calc_ichimoku(h, l):
    """Ichimoku Cloud — Tenkan-sen and Kijun-sen."""
    tenkan   = (h.rolling(9).max()  + l.rolling(9).min())  / 2
    kijun    = (h.rolling(26).max() + l.rolling(26).min()) / 2
    senkou_a = ((tenkan + kijun) / 2).shift(26)
    senkou_b = ((h.rolling(52).max() + l.rolling(52).min()) / 2).shift(26)
    return tenkan, kijun, senkou_a, senkou_b


def calc_support_resistance(c, window=20):
    """Simple pivot-based support/resistance."""
    highs      = c.rolling(window, center=True).max()
    lows       = c.rolling(window, center=True).min()
    resistance = highs.iloc[-1]
    support    = lows.iloc[-1]
    return support, resistance
 
 
# ══════════════════════════════════════════════════════════════════════════════
# ENHANCED AI ANALYSIS ENGINE
# ══════════════════════════════════════════════════════════════════════════════
def _sf(v, d=4):
    try: x = float(v); return None if np.isnan(x) else round(x, d)
    except: return None
 
 
def build_analysis_payload(ticker, period, name, df, macro_data=None, trends_data=None, fundamentals=None, shipping_ctx=None):
    # ── DATA HYGIENE: drop NaN rows, deduplicate index, enforce numeric types ──
    df = df[~df.index.duplicated(keep="last")].sort_index()
    for col in ["Open", "High", "Low", "Close"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["Close"])

    c   = df["Close"].squeeze()
    h   = df["High"].squeeze()
    lo  = df["Low"].squeeze()
    op  = df["Open"].squeeze()
    vol = df["Volume"].squeeze() if "Volume" in df.columns else None
    n   = len(c)

    if n < 2:
        raise ValueError(f"Insufficient data for {ticker}: only {n} valid bars after cleaning.")

    cur  = _sf(c.iloc[-1])
    prev = _sf(c.iloc[-2])
    currency = "INR" if ticker.upper().endswith((".NS", ".BO")) else "USD"

    hi52 = _sf(c.tail(252).max())
    lo52 = _sf(c.tail(252).min())

    # ── MACD ──
    macd_d = {}
    if n >= 27:
        ml, sl, hl = calc_macd(c)
        macd_d = {
            "macd": _sf(ml.iloc[-1]), "signal": _sf(sl.iloc[-1]),
            "histogram": _sf(hl.iloc[-1]), "hist_prev": _sf(hl.iloc[-2]) if n > 27 else None,
            "crossover": "bullish" if (hl.iloc[-1] > 0 and hl.iloc[-2] < 0) else
                         "bearish" if (hl.iloc[-1] < 0 and hl.iloc[-2] > 0) else "none",
        }

    # ── Bollinger Bands ──
    bb_d = {}
    if n >= 20:
        bbu, bbm, bbl = calc_bb(c)
        bbu_v, bbl_v = _sf(bbu.iloc[-1]), _sf(bbl.iloc[-1])
        bb_width = (bbu_v - bbl_v) if (bbu_v and bbl_v) else None
        bb_d = {
            "upper": bbu_v, "mid": _sf(bbm.iloc[-1]), "lower": bbl_v,
            "percent_b": _sf((cur - bbl_v) / bb_width) if bb_width else None,
            "bandwidth": _sf((bb_width / _sf(bbm.iloc[-1])) * 100) if (bb_width and bbm.iloc[-1]) else None,
        }

    # ── Moving Averages ──
    sma20  = _sf(calc_sma(c, 20).iloc[-1]) if n >= 20  else None
    sma50  = _sf(calc_sma(c, 50).iloc[-1]) if n >= 50  else None
    sma200 = _sf(calc_sma(c, 200).iloc[-1]) if n >= 200 else None
    rsi_v  = _sf(calc_rsi(c).iloc[-1])      if n >= 15  else None
    atr_v  = _sf(calc_atr(h, lo, c).iloc[-1]) if n >= 15 else None

    # ── Advanced Indicators ──
    adv = {}
    if vol is not None and n >= 20:
        # Sanitize volume: replace zeros/negatives with NaN before OBV/CMF
        vol_clean = vol.where(vol > 0)
        obv  = calc_obv(c, vol_clean.fillna(0))
        cmf  = calc_cmf(h, lo, c, vol_clean.fillna(0))
        vwap = calc_vwap(h, lo, c, vol_clean.fillna(0))

        obv_chg = obv.iloc[-1] - obv.iloc[-5] if len(obv) >= 5 else 0
        adv["obv_trend"]   = "rising" if obv_chg > 0 else "falling" if obv_chg < 0 else "flat"
        adv["obv_current"] = _sf(obv.iloc[-1])
        adv["obv_5d_chg"]  = _sf(obv_chg)

        cmf_v = cmf.iloc[-1]
        adv["cmf"] = _sf(cmf_v)
        adv["cmf_signal"] = "buying_pressure" if cmf_v > 0.05 else "selling_pressure" if cmf_v < -0.05 else "neutral"

        adv["vwap"]     = _sf(vwap.iloc[-1])
        adv["vs_vwap"]  = "above" if (cur and vwap.iloc[-1] and cur > vwap.iloc[-1]) else "below"
        adv["vwap_gap_pct"] = _sf(((cur - vwap.iloc[-1]) / vwap.iloc[-1]) * 100) if vwap.iloc[-1] else None

        # Volume spike detection: flag if today > 2× 20d avg
        avg20_vol = vol_clean.tail(20).mean()
        adv["vol_spike"] = bool(vol_clean.iloc[-1] > 2 * avg20_vol) if (pd.notna(avg20_vol) and avg20_vol > 0) else False

    if n >= 14:
        stk, stk_d = calc_stoch(h, lo, c)
        adv["stoch_k"]    = _sf(stk.iloc[-1])
        adv["stoch_d"]    = _sf(stk_d.iloc[-1])
        adv["stoch_zone"] = "overbought" if stk.iloc[-1] > 80 else "oversold" if stk.iloc[-1] < 20 else "neutral"
        # Stoch divergence: price higher but stoch lower (bearish) or vice versa
        if n >= 19:
            price_dir = c.iloc[-1] - c.iloc[-5]
            stoch_dir = stk.iloc[-1] - stk.iloc[-5]
            adv["stoch_divergence"] = (
                "bearish" if price_dir > 0 and stoch_dir < 0 else
                "bullish" if price_dir < 0 and stoch_dir > 0 else "none"
            )
        wr = calc_williams_r(h, lo, c)
        adv["williams_r"] = _sf(wr.iloc[-1])

    if n >= 14:
        adx = calc_adx(h, lo, c)
        adx_v = adx.iloc[-1]
        adv["adx"]            = _sf(adx_v)
        adv["trend_strength"] = "strong" if adx_v > 25 else "weak" if adx_v < 20 else "moderate"

    if n >= 52:
        ten, kij, sen_a, sen_b = calc_ichimoku(h, lo)
        adv["ichimoku_tenkan"] = _sf(ten.iloc[-1])
        adv["ichimoku_kijun"]  = _sf(kij.iloc[-1])
        adv["ichimoku_signal"] = (
            "bullish_cloud" if (cur and ten.iloc[-1] and kij.iloc[-1] and cur > ten.iloc[-1] > kij.iloc[-1]) else
            "bearish_cloud" if (cur and ten.iloc[-1] and kij.iloc[-1] and cur < ten.iloc[-1] < kij.iloc[-1]) else
            "neutral"
        )

    # ── Support / Resistance ──
    support, resistance = calc_support_resistance(c)
    adv["support"]    = _sf(support)
    adv["resistance"] = _sf(resistance)
    if cur and support and resistance:
        rng = resistance - support
        adv["sr_position"] = round((cur - support) / rng * 100, 1) if rng > 0 else 50

    # ── Volume summary ──
    vol_d = {}
    if vol is not None:
        vol_clean2 = vol.where(vol > 0)
        avg20v = _sf(vol_clean2.tail(20).mean())
        cv     = _sf(vol_clean2.iloc[-1])
        vol_d  = {
            "latest": cv, "avg_20d": avg20v,
            "ratio_vs_avg": _sf(cv / avg20v) if avg20v else None,
            "avg_5d": _sf(vol_clean2.tail(5).mean()),
        }

    # ── Trend signals ──
    trend = []
    if sma20  and cur: trend.append("above_sma20"  if cur > sma20  else "below_sma20")
    if sma50  and cur: trend.append("above_sma50"  if cur > sma50  else "below_sma50")
    if sma200 and cur: trend.append("above_sma200" if cur > sma200 else "below_sma200")
    if sma20  and sma50: trend.append("golden_cross" if sma20 > sma50 else "death_cross")
    # MA compression: all three SMAs within 2% of each other → potential breakout
    if sma20 and sma50 and sma200:
        ma_spread = (max(sma20, sma50, sma200) - min(sma20, sma50, sma200)) / sma200 * 100
        if ma_spread < 2.0:
            trend.append("ma_compression")

    # ── RSI divergence detection ──
    rsi_divergence = "none"
    if n >= 20 and rsi_v is not None:
        rsi_series = calc_rsi(c)
        price_chg  = c.iloc[-1] - c.iloc[-5]
        rsi_chg    = rsi_series.iloc[-1] - rsi_series.iloc[-5]
        if price_chg > 0 and rsi_chg < 0:
            rsi_divergence = "bearish"
        elif price_chg < 0 and rsi_chg > 0:
            rsi_divergence = "bullish"

    # ── Price patterns ──
    patterns = []
    if n >= 10:
        last10 = c.tail(10)
        if last10.is_monotonic_increasing: patterns.append("uptrend_10d")
        elif last10.is_monotonic_decreasing: patterns.append("downtrend_10d")
        body_size    = abs(c.iloc[-1] - op.iloc[-1])
        candle_range = h.iloc[-1] - lo.iloc[-1]
        if candle_range > 0 and body_size / candle_range < 0.1:
            patterns.append("doji_candle")
        if n >= 2:
            gap_pct = abs(op.iloc[-1] - c.iloc[-2]) / (c.iloc[-2] + 1e-10) * 100
            if gap_pct > 1.5:
                patterns.append(f"gap_{'up' if op.iloc[-1] > c.iloc[-2] else 'down'}_{round(gap_pct, 1)}pct")
        # Hammer / shooting star
        upper_wick = h.iloc[-1] - max(c.iloc[-1], op.iloc[-1])
        lower_wick = min(c.iloc[-1], op.iloc[-1]) - lo.iloc[-1]
        if candle_range > 0:
            if lower_wick > 2 * body_size and upper_wick < body_size:
                patterns.append("hammer")
            elif upper_wick > 2 * body_size and lower_wick < body_size:
                patterns.append("shooting_star")
        # Engulfing (2-bar pattern)
        if n >= 2:
            prev_body = abs(c.iloc[-2] - op.iloc[-2])
            if (body_size > prev_body and
                    c.iloc[-1] > op.iloc[-1] and c.iloc[-2] < op.iloc[-2] and
                    op.iloc[-1] < c.iloc[-2] and c.iloc[-1] > op.iloc[-2]):
                patterns.append("bullish_engulfing")
            elif (body_size > prev_body and
                      c.iloc[-1] < op.iloc[-1] and c.iloc[-2] > op.iloc[-2] and
                      op.iloc[-1] > c.iloc[-2] and c.iloc[-1] < op.iloc[-2]):
                patterns.append("bearish_engulfing")

    # ── OHLCV table: last 20 rows only (token efficiency) ──
    recent = df.tail(20).copy()
    recent.index = recent.index.astype(str)
    ohlcv = [
        {"date": d[:10], "open": _sf(r.get("Open")), "high": _sf(r.get("High")),
         "low": _sf(r.get("Low")), "close": _sf(r.get("Close")),
         "volume": int(r["Volume"]) if "Volume" in r and pd.notna(r["Volume"]) else None}
        for d, r in recent.iterrows()
    ]

    # ── Performance stats ──
    perf = {}
    for days, label in [(5, "5d"), (21, "1mo"), (63, "3mo"), (126, "6mo"), (252, "1y")]:
        if n > days:
            start_price = c.iloc[-min(days + 1, n)]
            if start_price and start_price != 0:
                perf[label] = _sf(((c.iloc[-1] - start_price) / start_price) * 100)

    # ── SPY correlation ──
    market_corr = None
    if n >= 60:
        try:
            spy_data, _ = fetch_yfinance_data("SPY", period)
            if spy_data is not None and not spy_data.empty:
                spy_c     = spy_data["Close"].squeeze().dropna()
                stock_ret = c.pct_change().dropna()
                spy_ret   = spy_c.pct_change().dropna()
                aligned   = pd.concat([stock_ret, spy_ret], axis=1).dropna()
                if len(aligned) > 30:
                    market_corr = _sf(aligned.corr().iloc[0, 1])
        except Exception:
            pass

    # ── Indicator confluence score (0-10) ──
    # Count bullish signals across independent sources for a quick credibility gauge
    bull_signals = 0
    bear_signals = 0
    if cur and sma20 and cur > sma20: bull_signals += 1
    else: bear_signals += 1
    if cur and sma50 and cur > sma50: bull_signals += 1
    else: bear_signals += 1
    if rsi_v and rsi_v < 70: bull_signals += 1
    if rsi_v and rsi_v > 30: bull_signals += 1
    if macd_d.get("crossover") == "bullish": bull_signals += 2
    elif macd_d.get("crossover") == "bearish": bear_signals += 2
    if adv.get("obv_trend") == "rising": bull_signals += 1
    elif adv.get("obv_trend") == "falling": bear_signals += 1
    if adv.get("cmf_signal") == "buying_pressure": bull_signals += 1
    elif adv.get("cmf_signal") == "selling_pressure": bear_signals += 1
    if rsi_divergence == "bullish": bull_signals += 1
    elif rsi_divergence == "bearish": bear_signals += 1
    confluence = {"bull": bull_signals, "bear": bear_signals,
                  "net_bias": "bullish" if bull_signals > bear_signals else
                               "bearish" if bear_signals > bull_signals else "neutral"}

    return {
        "ticker": ticker, "name": name, "currency": currency, "period": period, "bars": n,
        "price": {
            "current": cur, "prev": prev,
            "change": _sf(cur - prev) if (cur and prev) else None,
            "change_pct": _sf(((cur - prev) / prev) * 100) if (cur and prev) else None,
            "52w_high": hi52, "52w_low": lo52,
            "pct_from_52h": _sf(((cur - hi52) / hi52) * 100) if (cur and hi52) else None,
        },
        "performance": perf,
        "ma": {
            "sma20": sma20, "sma50": sma50, "sma200": sma200,
            "ema9":  _sf(calc_ema(c, 9).iloc[-1]),
            "ema21": _sf(calc_ema(c, 21).iloc[-1]),
            "ema50": _sf(calc_ema(c, 50).iloc[-1]),
        },
        "bb": bb_d,
        "rsi": {
            "value": rsi_v,
            "last5": [_sf(v) for v in calc_rsi(c).tail(5).tolist()] if n >= 20 else [],
            "divergence": rsi_divergence,
        },
        "macd": macd_d,
        "atr": {"value": atr_v, "pct": _sf((atr_v / cur) * 100) if (atr_v and cur) else None},
        "volume": vol_d,
        "trend": trend,
        "advanced": adv,
        "patterns": patterns,
        "market_corr": market_corr,
        "confluence": confluence,
        "ohlcv": ohlcv,
        "macro": macro_data or {},
        "trends": trends_data or {},
        "fundamentals": fundamentals or {},
        "shipping": shipping_ctx or {},
    }
 
 
def build_prompt(payload):
    p        = payload
    px       = p["price"]
    ma       = p["ma"]
    bb       = p.get("bb", {})
    rsi      = p.get("rsi", {})
    macd     = p.get("macd", {})
    atr      = p.get("atr", {})
    vol      = p.get("volume", {})
    adv      = p.get("advanced", {})
    perf     = p.get("performance", {})
    macro    = p.get("macro", {})
    trends   = p.get("trends", {})
    fund     = p.get("fundamentals", {})
    shipping = p.get("shipping", {})
    pats     = p.get("patterns", [])
    conf     = p.get("confluence", {})

    f  = lambda v, d=2: f"{v:.{d}f}" if v is not None else "N/A"
    fp = lambda v: (f"+{v:.2f}" if v > 0 else f"{v:.2f}") if v is not None else "N/A"
    up = lambda v: (("above" if px["current"] and v and px["current"] > v else "below") if v else "N/A")

    # ── DATA QUALITY REPORT ──
    missing_data = []
    if not fund:     missing_data.append("fundamentals (Yahoo unavailable)")
    if not macro:    missing_data.append("FRED macro data")
    if not trends:   missing_data.append("Google Trends")
    if not shipping: missing_data.append("AIS shipping context")
    data_quality_lines = [
        "## DATA QUALITY REPORT",
        f"- Bars loaded: {p['bars']}  |  Period: {p['period']}  |  Currency: {p['currency']}",
        f"- Missing sources: {', '.join(missing_data) if missing_data else 'none — all sources live'}",
        f"- Confluence score: {conf.get('bull', 0)} bullish signals vs {conf.get('bear', 0)} bearish "
        f"signals -> net bias: {conf.get('net_bias', 'N/A').upper()}",
        "NOTE: Where data is N/A, do not fabricate values. Acknowledge the gap and weight surviving signals accordingly.",
        "",
    ]

    # ── FUNDAMENTALS ──
    fund_lines = []
    if fund:
        def fmt_cap(v):
            if v is None: return "N/A"
            if v >= 1e12: return f"${v/1e12:.2f}T"
            if v >= 1e9:  return f"${v/1e9:.2f}B"
            if v >= 1e6:  return f"${v/1e6:.2f}M"
            return f"${v:,.0f}"
        fund_lines = [
            "## FUNDAMENTALS",
            f"- Sector: {fund.get('sector','N/A')}  |  Industry: {fund.get('industry','N/A')}  |  Country: {fund.get('country','N/A')}",
            f"- Market Cap: {fmt_cap(fund.get('market_cap'))}  |  EV: {fmt_cap(fund.get('enterprise_value'))}",
            f"- P/E (TTM): {f(fund.get('pe_ratio'))}  |  Forward P/E: {f(fund.get('forward_pe'))}",
            f"- P/B: {f(fund.get('pb_ratio'))}  |  P/S: {f(fund.get('ps_ratio'))}",
            f"- Revenue Growth: {f(fund.get('revenue_growth'),1) if fund.get('revenue_growth') else 'N/A'}%  |  Earnings Growth: {f(fund.get('earnings_growth'),1) if fund.get('earnings_growth') else 'N/A'}%",
            f"- Profit Margin: {f(fund.get('profit_margin'),1) if fund.get('profit_margin') else 'N/A'}%  |  ROE: {f(fund.get('roe'),1) if fund.get('roe') else 'N/A'}%",
            f"- Debt/Equity: {f(fund.get('debt_to_equity'))}  |  Current Ratio: {f(fund.get('current_ratio'))}",
            f"- Free Cash Flow: {fmt_cap(fund.get('free_cashflow'))}",
            f"- Dividend Yield: {f(fund.get('dividend_yield'),2) if fund.get('dividend_yield') else '0.00'}%  |  Beta: {f(fund.get('beta'))}",
            f"- Analyst Target: {f(fund.get('analyst_target'))}  |  Rating: {fund.get('analyst_rating','N/A').upper()}  |  # Analysts: {fund.get('num_analysts','N/A')}",
            f"- Short Ratio: {f(fund.get('short_ratio'))}  |  Inst. Ownership: {f(fund.get('inst_ownership'),1) if fund.get('inst_ownership') else 'N/A'}%",
            f"- Insider Ownership: {f(fund.get('insider_ownership'),1) if fund.get('insider_ownership') else 'N/A'}%",
            "",
        ]

    # ── MACRO ──
    macro_lines = []
    if macro:
        macro_lines = ["## MACRO ENVIRONMENT (FRED Live)"]
        for sid, md in macro.items():
            chg = f" (delta{fp(md.get('change'))})" if md.get("change") is not None else ""
            macro_lines.append(f"- {md['label']}: {f(md['value'])}{chg} [{md.get('date','')}]")
        macro_lines.append("")

    # ── GOOGLE TRENDS ──
    trends_lines = []
    if trends:
        trends_lines = ["## SEARCH INTEREST (Google Trends)"]
        for kw, td in trends.items():
            trends_lines.append(
                f"- '{kw}': {td.get('current')}/100  |  30d avg: {td.get('avg_30d')}  |  {td.get('trend','N/A').upper()}"
            )
        trends_lines.append("")

    # ── SHIPPING ──
    shipping_lines = []
    if shipping:
        shipping_lines = ["## SHIPPING & SUPPLY CHAIN (AIS)"]
        if shipping.get("vessel_count"):
            shipping_lines.append(f"- Active vessels: {shipping['vessel_count']:,}")
        for note in shipping.get("notes", []):
            shipping_lines.append(f"- {note}")
        shipping_lines.append(f"- Congestion signal: {shipping.get('congestion_signal','neutral').upper()}")
        shipping_lines.append("")

    # ── ADVANCED TECHNICALS ──
    adv_lines = [
        "## ADVANCED TECHNICAL INDICATORS",
        f"- OBV: {adv.get('obv_trend','N/A').upper()}  |  5d OBV delta: {f(adv.get('obv_5d_chg'))}  |  CMF: {f(adv.get('cmf'),3)} -> {adv.get('cmf_signal','N/A')}",
        f"- Vol spike today: {'YES' if adv.get('vol_spike') else 'no'}  |  VWAP: {f(adv.get('vwap'))}  |  Price vs VWAP: {adv.get('vs_vwap','N/A').upper()} ({f(adv.get('vwap_gap_pct'))}%)",
        f"- Stochastic K: {f(adv.get('stoch_k'))}  |  D: {f(adv.get('stoch_d'))}  |  Zone: {adv.get('stoch_zone','N/A').upper()}  |  Divergence: {adv.get('stoch_divergence','N/A').upper()}",
        f"- Williams %R: {f(adv.get('williams_r'))}  |  ADX: {f(adv.get('adx'))} -> {adv.get('trend_strength','N/A').upper()}",
        f"- Support: {f(adv.get('support'))}  |  Resistance: {f(adv.get('resistance'))}  |  S/R Position: {f(adv.get('sr_position'),0) if adv.get('sr_position') is not None else 'N/A'}%",
        f"- Ichimoku: Tenkan={f(adv.get('ichimoku_tenkan'))}  Kijun={f(adv.get('ichimoku_kijun'))}  -> {adv.get('ichimoku_signal','N/A').upper()}",
        f"- SPY Correlation: {f(p.get('market_corr'))}  |  Patterns: {', '.join(pats) if pats else 'none'}",
        f"- RSI Divergence (5-bar): {rsi.get('divergence','none').upper()}",
        "",
    ]

    # ── PERFORMANCE ──
    perf_lines = ["## PRICE PERFORMANCE"]
    for lbl in ["5d", "1mo", "3mo", "6mo", "1y"]:
        if lbl in perf:
            perf_lines.append(f"- {lbl}: {fp(perf[lbl])}%")
    perf_lines.append("")

    lines = [
        "[ROLE]",
        "You are a Senior Quantitative Portfolio Manager at a top-tier hedge fund.",
        "You specialize in cross-asset confluence analysis: combining price action, technical indicators,",
        "fundamental valuation, macroeconomic regime, and alternative data into a single decisive trade thesis.",
        "Write with a precise, evidence-first, action-oriented tone. Never use vague language (could/might/possibly).",
        "If data is missing (marked N/A), acknowledge it explicitly — never fabricate values.",
        "",
        "[GOAL]",
        f"Produce an institutional-grade trade decision for {p['name']} ({p['ticker']}) over the {p['period']} period.",
        "Objective: identify the highest-conviction entry or exit signal by finding where the most independent",
        "data sources agree — or flag the contradiction if they conflict.",
        "",
        "[INPUT DATA]",
    ] + data_quality_lines + [
        "## PRICE SNAPSHOT",
        f"- Current: {p['currency']} {f(px['current'])}  |  Prev Close: {p['currency']} {f(px['prev'])}",
        f"- Change: {fp(px['change'])} ({fp(px['change_pct'])}%)",
        f"- 52W High: {p['currency']} {f(px['52w_high'])}  |  52W Low: {p['currency']} {f(px['52w_low'])}",
        f"- Distance from 52W High: {f(px['pct_from_52h'])}%",
        "",
    ] + perf_lines + [
        "## MOVING AVERAGES",
        f"- SMA 20: {p['currency']} {f(ma['sma20'])}  ({up(ma['sma20'])} SMA20)",
        f"- SMA 50: {p['currency']} {f(ma['sma50'])}  ({up(ma['sma50'])} SMA50)",
        f"- SMA 200: {p['currency']} {f(ma['sma200'])}  ({up(ma['sma200'])} SMA200)",
        f"- EMA 9: {f(ma['ema9'])}  |  EMA 21: {f(ma['ema21'])}  |  EMA 50: {f(ma['ema50'])}",
        f"- MA signals: {', '.join(p['trend']) if p['trend'] else 'none'}",
        "",
        "## BOLLINGER BANDS (20, 2sigma)",
        f"- Upper: {f(bb.get('upper'))}  |  Mid: {f(bb.get('mid'))}  |  Lower: {f(bb.get('lower'))}",
        f"- %B: {f(bb.get('percent_b'),3)} (>1 overbought, <0 oversold)  |  Bandwidth: {f(bb.get('bandwidth'))}%",
        "",
        "## RSI (14)",
        f"- Current: {f(rsi.get('value'))}  Zone: {'OVERBOUGHT' if rsi.get('value') and rsi['value']>70 else 'OVERSOLD' if rsi.get('value') and rsi['value']<30 else 'NEUTRAL'}",
        f"- Last 5 values: {', '.join(f(v) for v in rsi.get('last5',[]))}",
        f"- RSI Divergence vs price (5-bar): {rsi.get('divergence','none').upper()}",
        "",
        "## MACD (12, 26, 9)",
        f"- MACD: {f(macd.get('macd'))}  |  Signal: {f(macd.get('signal'))}  |  Histogram: {f(macd.get('histogram'))} (prev: {f(macd.get('hist_prev'))})",
        f"- Crossover event: {(macd.get('crossover') or 'none').upper()}",
        "",
        "## VOLATILITY & VOLUME",
        f"- ATR(14): {p['currency']} {f(atr.get('value'))} ({f(atr.get('pct'))}% of price)",
        f"- Latest Vol: {int(vol['latest']) if vol.get('latest') else 'N/A'}  |  20D Avg: {int(vol['avg_20d']) if vol.get('avg_20d') else 'N/A'}  |  Ratio: {f(vol.get('ratio_vs_avg'))}x",
        "",
    ] + adv_lines + fund_lines + macro_lines + trends_lines + shipping_lines + [
        "## RECENT OHLCV (last 20 trading days)",
        "date,open,high,low,close,volume",
    ] + [
        f"{r['date']},{r['open']},{r['high']},{r['low']},{r['close']},{r['volume']}"
        for r in p["ohlcv"]
    ] + [
        "",
        "[INSTRUCTIONS]",
        "1. CHART READING: Scan all OHLCV rows. Identify dominant price structure (uptrend/downtrend/range),",
        "   swing highs/lows with exact prices, volume-price confirmation, candlestick patterns by date",
        "   (e.g., hammer on DATE at PRICE), gap events, and micro-structure of the last 5 candles.",
        "2. TECHNICAL CONFLUENCE: Find where 3+ independent indicators agree on the same direction.",
        "   Cite exact values. A setup with RSI oversold + MACD bullish crossover + OBV rising + price",
        "   above VWAP = high-conviction. Fewer agreeing signals = lower confidence.",
        "3. DIVERGENCE AUDIT: Explicitly check — does price disagree with OBV? RSI? MACD histogram?",
        "   Each divergence reduces confidence. Name each one and explain its implication.",
        "4. FUNDAMENTAL VS TECHNICAL VERDICT: State explicitly whether fundamentals and technicals agree",
        "   or conflict. If P/E is stretched but price is breaking out, say so and explain the tension.",
        "5. MACRO IMPACT: Map each FRED data point to a direct mechanism for this specific ticker",
        "   (e.g., 'rising DFF compresses P/E multiples for this growth stock by X% historically').",
        "6. EDGE-CASE ANALYSIS (MANDATORY): Give exactly 3 ways your analysis could be wrong, each with",
        "   a specific early-warning signal (e.g., 'If volume fails to follow a breakout above RESISTANCE,",
        "   the move is a false breakout — exit immediately').",
        "",
        "[OUTPUT FORMAT]",
        "Return a single valid JSON object. No markdown fences. No preamble. No trailing text.",
        "All string fields must be substantive prose with exact numbers. No placeholder text.",
        "",
        '{',
        '  "verdict": "BUY|SELL|HOLD",',
        '  "confidence": "Low|Medium|High",',
        '  "time_horizon": "Short (days)|Mid (weeks)|Long (months)",',
        '  "price_targets": {"entry": 0.0, "stop_loss": 0.0, "target_1": 0.0, "target_2": 0.0},',
        '  "confluence_summary": "2-3 sentences: which independent signals agree, with exact values. This is the core thesis.",',
        '  "chart_pattern_analysis": "Dominant structure + swing highs/lows with prices + volume-price confirmation + candlestick patterns by date + last-5-candle micro-structure. Min 3 paragraphs.",',
        '  "technical_analysis": "MA alignment + RSI trajectory + MACD histogram evolution + Stochastic/Williams + OBV/CMF/VWAP + ATR + BB + Ichimoku + S/R + ADX. Cite exact values. Min 5 paragraphs.",',
        '  "fundamental_analysis": "P/E, P/B, P/S vs sector norms (state over/undervalued by X%) + growth quality + margins/ROE + balance sheet + analyst gap + short interest as contrarian signal.",',
        '  "macro_and_altdata": "Map each FRED series to a direct mechanism for this ticker. Google Trends as retail sentiment — rising/falling and near-term demand implication. Shipping context if sector-relevant.",',
        '  "risk_factors": "Exactly 3 risks: Risk: [scenario + exact threshold]. Early warning: [what to watch]. Mitigation: [action].",',
        '  "action_plan": "Step 1: entry condition (price + indicator confirmation). Step 2: position size (% portfolio, ATR-justified). Step 3: scale-in trigger. Step 4: stop-loss (show ATR or S/R calculation). Step 5: exit at T1 (partial) and T2 (remainder).",',
        '  "summary": "Sentence 1: core thesis — the single most critical technical+fundamental confluence. Sentence 2: the biggest risk with its specific threshold."',
        '}',
        "",
        "[CONSTRAINTS]",
        "- Do NOT fabricate values. If a field is N/A in the data, say so explicitly.",
        "- Do NOT use vague language. Every claim must reference a specific number from the data above.",
        "- Do NOT exceed 3,200 tokens total in the JSON output.",
        "- Price targets must be internally consistent: stop_loss < entry < target_1 < target_2 for BUY,",
        "  reversed for SELL. If impossible to achieve, set confidence to Low and explain why.",
    ]
    return "\n".join(lines)
 
 
def call_openrouter(model_id, prompt):
    if not OPEN_ROUTER_API_KEY:
        raise ValueError("OPEN_ROUTER_API_KEY environment variable is not set.")

    # temperature=0 → deterministic, fact-grounded output (no creative drift)
    # max_tokens=3800 → matches prompt constraint of 3,200 JSON + overhead
    # response_format enforces JSON-only output where the model supports it
    r = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {OPEN_ROUTER_API_KEY}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://starfish.finance",
            "X-Title": "Starfish Stock Analyzer",
        },
        json={
            "model": model_id,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0,          # deterministic: removes hallucination drift
            "max_tokens": 3800,        # matched to output schema constraint
            "top_p": 1,
            "frequency_penalty": 0,
        },
        timeout=120,
    )
    r.raise_for_status()

    raw = r.json()["choices"][0]["message"]["content"].strip()

    # ── JSON extraction: strip markdown fences if model wraps output ──
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)

    # ── Greedy extraction: find outermost { ... } block ──
    m = re.search(r'\{.*\}', raw, re.DOTALL)
    if not m:
        raise json.JSONDecodeError("No JSON object found in model response", raw, 0)
    candidate = m.group(0)

    # ── Parse and validate required keys ──
    result = json.loads(candidate)
    required = {"verdict", "confidence", "time_horizon", "price_targets",
                "confluence_summary", "chart_pattern_analysis", "technical_analysis",
                "fundamental_analysis", "macro_and_altdata", "risk_factors",
                "action_plan", "summary"}
    missing_keys = required - set(result.keys())
    if missing_keys:
        # Non-fatal: surface the gap rather than silently swallowing it
        result["_data_warnings"] = f"Model omitted fields: {', '.join(sorted(missing_keys))}"

    # ── Validate price target consistency ──
    pt = result.get("price_targets", {})
    verdict = result.get("verdict", "HOLD")
    entry, sl, t1, t2 = pt.get("entry"), pt.get("stop_loss"), pt.get("target_1"), pt.get("target_2")
    if all(v is not None for v in [entry, sl, t1, t2]):
        consistent = (
            (sl < entry < t1 < t2) if verdict == "BUY" else
            (sl > entry > t1 > t2) if verdict == "SELL" else True
        )
        if not consistent:
            result["_price_target_warning"] = (
                f"Price targets inconsistent for {verdict}: "
                f"entry={entry}, stop_loss={sl}, t1={t1}, t2={t2}"
            )

    return result
 
 
# ══════════════════════════════════════════════════════════════════════════════
# CHART BUILDER  (unchanged visual design)
# ══════════════════════════════════════════════════════════════════════════════
_C = {"bg":"rgba(0,0,0,0)","paper":"rgba(0,0,0,0)","grid":"rgba(42,46,57,0.15)","axis":"#787b86",
      "text":"#787b86","white":"#2962ff","green":"#26a69a","red":"#ef5350",
      "sma20":"#f9a825","sma50":"#7b1fa2","sma200":"#1565c0",
      "bb_u":"rgba(33,150,243,0.7)","bb_l":"rgba(33,150,243,0.7)","bb_f":"rgba(33,150,243,0.05)",
      "rsi":"#7e57c2","rsi_ob":"rgba(239,83,80,0.08)","rsi_os":"rgba(38,166,154,0.08)",
      "macd":"#2196f3","sig":"#ff6d00","hp":"rgba(38,166,154,0.85)","hn":"rgba(239,83,80,0.85)",
      "vu":"rgba(38,166,154,0.6)","vd":"rgba(239,83,80,0.6)"}
 
 
def build_chart(ticker, period, chart_type, indicators):
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
            increasing_line_color=_C["green"],increasing_fillcolor="rgba(38,166,154,.18)",
            decreasing_line_color=_C["red"],decreasing_fillcolor="rgba(239,83,80,.18)",
            line=dict(width=1)), row=1,col=1)
    else:
        fig.add_trace(go.Scatter(x=dates,y=cl,mode="lines",name="Price",
            line=dict(color=_C["white"],width=2),fill="tozeroy",fillcolor="rgba(41,98,255,.06)"),row=1,col=1)
 
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
        for lvl,c in [(70,"rgba(239,83,80,.5)"),(30,"rgba(38,166,154,.5)"),(50,"rgba(120,123,134,.3)")]:
            fig.add_hline(y=lvl,row=rr,col=1,line=dict(color=c,width=0.8,dash="dash"))
    if sm and len(cl) >= 27:
        ml,sl,hl = calc_macd(cl)
        hc = [_C["hp"] if v>=0 else _C["hn"] for v in hl.fillna(0)]
        fig.add_trace(go.Bar(x=dates,y=hl,name="MACD Hist",marker_color=hc,showlegend=False),row=rm,col=1)
        fig.add_trace(go.Scatter(x=dates,y=ml,mode="lines",name="MACD",
            line=dict(color=_C["macd"],width=1.5),showlegend=False),row=rm,col=1)
        fig.add_trace(go.Scatter(x=dates,y=sl,mode="lines",name="Signal",
            line=dict(color=_C["sig"],width=1.5),showlegend=False),row=rm,col=1)
        fig.add_hline(y=0,row=rm,col=1,line=dict(color="rgba(120,123,134,.4)",width=0.8,dash="dash"))
 
    ax = dict(gridcolor=_C["grid"],color=_C["axis"],showline=False,zeroline=False,tickfont=dict(size=9,color=_C["text"]))
    fig.update_layout(
        height=420+120*(rows-1), plot_bgcolor=_C["bg"], paper_bgcolor=_C["paper"],
        font=dict(color=_C["text"],family="'DM Sans',sans-serif",size=11),
        legend=dict(orientation="h",yanchor="bottom",y=1.01,xanchor="left",x=0,
                    bgcolor="rgba(255,255,255,0)",font=dict(size=10,color=_C["text"])),
        hovermode="x unified", margin=dict(l=55,r=20,t=55,b=30),
        hoverlabel=dict(bgcolor="rgba(255,255,255,.97)",bordercolor="rgba(120,123,134,.3)",font=dict(color="#000")),
        xaxis_rangeslider_visible=False, dragmode="pan",
    )
    for i in range(1, rows+1):
        fig.update_layout(**{f"xaxis{'' if i==1 else i}": {**ax,"rangeslider":{"visible":False}}})
        fig.update_layout(**{f"yaxis{'' if i==1 else i}": {**ax}})
    if sr: fig.update_layout(**{f"yaxis{'' if rr==1 else rr}": {**ax,"range":[0,100]}})
    for ann in fig.layout.annotations: ann.font.color="#787b86"; ann.font.size=10
    return pyo.plot(fig,output_type="div",include_plotlyjs=False), None
 
 
# ══════════════════════════════════════════════════════════════════════════════
# GEOMETRIC BROWNIAN MOTION SIMULATION
# ══════════════════════════════════════════════════════════════════════════════
def run_gbm(ticker, n_years=2, n_scenarios=200, steps_per_year=252):
    """Compute GBM paths from historical mu/sigma calibrated on real price data."""
    df, err = fetch_yfinance_data(ticker, "2y")
    if err or df is None or df.empty:
        # fallback defaults
        mu, sigma, s_0 = 0.07, 0.20, 100.0
    else:
        cl = df["Close"].squeeze().dropna()
        log_rets = np.log(cl / cl.shift(1)).dropna()
        mu    = float(log_rets.mean() * steps_per_year)
        sigma = float(log_rets.std()  * np.sqrt(steps_per_year))
        s_0   = float(cl.iloc[-1])

    dt     = 1.0 / steps_per_year
    n_steps = int(n_years * steps_per_year)

    # GBM: S_{t+dt} = S_t * exp((mu - 0.5*sigma^2)*dt + sigma*sqrt(dt)*Z)
    z = np.random.standard_normal((n_steps, n_scenarios))
    log_increments = (mu - 0.5 * sigma**2) * dt + sigma * np.sqrt(dt) * z
    paths = s_0 * np.exp(np.vstack([np.zeros(n_scenarios), log_increments]).cumsum(axis=0))

    t_axis = np.linspace(0, n_years, n_steps + 1).tolist()
    terminal = paths[-1].tolist()
    p5   = float(np.percentile(paths, 5,  axis=1)[-1])
    p25  = float(np.percentile(paths, 25, axis=1)[-1])
    p50  = float(np.percentile(paths, 50, axis=1)[-1])
    p75  = float(np.percentile(paths, 75, axis=1)[-1])
    p95  = float(np.percentile(paths, 95, axis=1)[-1])
    # Return a sample of paths for the fan chart (max 80 to keep payload small)
    sample_n = min(n_scenarios, 80)
    idx = np.random.choice(n_scenarios, sample_n, replace=False)
    sampled_paths = paths[:, idx].T.tolist()  # shape: sample_n x (n_steps+1)

    return {
        "ticker": ticker,
        "s_0": round(s_0, 4),
        "mu":  round(mu,  4),
        "sigma": round(sigma, 4),
        "n_years": n_years,
        "n_scenarios": n_scenarios,
        "t_axis": t_axis,
        "paths": sampled_paths,
        "terminal": terminal,
        "percentiles": {"p5": round(p5,2), "p25": round(p25,2), "p50": round(p50,2),
                        "p75": round(p75,2), "p95": round(p95,2)},
    }


# ══════════════════════════════════════════════════════════════════════════════
# ALPACA STOCKS API ENDPOINT
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/api/alpaca-stocks")
def api_alpaca_stocks():
    """Return live stock data from Alpaca for the watchlist."""
    now = time.time()
    if "alpaca" not in alpaca_cache or (now - alpaca_cache_time.get("alpaca", 0)) > ALPACA_CACHE_TTL:
        try:
            alpaca_cache["alpaca"] = alpaca_fetch_all_data()
            alpaca_cache_time["alpaca"] = now
        except Exception as e:
            if "alpaca" not in alpaca_cache:
                return jsonify({"error": str(e)}), 500
    return jsonify({
        "stocks":  alpaca_cache.get("alpaca", []),
        "updated": datetime.utcnow().strftime("%H:%M:%S UTC"),
    })


@app.route("/api/alpaca-account")
def api_alpaca_account():
    """Return Alpaca account details."""
    try:
        r = requests.get(f"{ALPACA_BASE_URL}/account", headers=ALPACA_HEADERS, timeout=6)
        if r.status_code == 200:
            d = r.json()
            return jsonify({
                "equity":          d.get("equity"),
                "cash":            d.get("cash"),
                "buying_power":    d.get("buying_power"),
                "portfolio_value": d.get("portfolio_value"),
                "status":          d.get("status"),
            })
        return jsonify({"error": f"HTTP {r.status_code}"})
    except Exception as e:
        return jsonify({"error": str(e)})


# ══════════════════════════════════════════════════════════════════════════════
# MAIN PAGE RENDERER
# ══════════════════════════════════════════════════════════════════════════════
DEFAULT_INDICATORS = {"sma","vol"}
 
 
def render_page(ticker, period, chart_type, active_indicators, graph_html, error, logo_uri=_LOGO_DATA_URI):
    chips = "".join(
        '<span class="{cls}" onclick="setTicker(\'{s}\')">{s}</span>\n'.format(
            cls="chip active" if s==ticker else "chip", s=s)
        for s,_ in POPULAR_STOCKS)
    popts = "".join('<option value="{v}" {sel}>{lbl}</option>\n'.format(
        v=v, sel="selected" if v==period else "", lbl=lbl) for v,lbl in PERIODS)
    ct_c  = "selected" if chart_type=="candlestick" else ""
    ct_l  = "selected" if chart_type=="line" else ""
    ichips = "".join(
        '<span class="{cls}" data-ind="{k}" onclick="toggleInd(this)">{lbl}</span>\n'.format(
            cls="ind-chip active" if k in active_indicators else "ind-chip", k=k, lbl=lbl)
        for k,lbl in INDICATORS)
    content = (f'<div class="error-box">{error}</div>' if error else
               graph_html if graph_html else '<div class="empty-state">Enter a ticker above.</div>')
 
    # News tabs
    ntabs_parts = []
    for i, ch in enumerate(NEWS_CHANNELS):
        _cls = "news-tab active" if i == 0 else "news-tab"
        ntabs_parts.append(
            '<button class="' + _cls + '" data-handle="' + ch["handle"] + '">' +
            ch["label"] + ' <span class="news-tag">' + ch["region"] + '</span><span class="news-tag">' + ch["lang"] + '</span></button>\n'
        )
    ntabs = "".join(ntabs_parts)
 
    # AI model cards
    ai_cards = ""
    for m in AI_MODELS:
        rl = rl_check(m["key"])
        ex  = " exhausted" if not rl["available"] else ""
        ai_cards += f"""<div class="ai-model-card{ex}" data-model="{m['id']}" data-key="{m['key']}" data-color="{m['color']}" data-label="{m['label']}" onclick="selectModel(this)">
  <div class="ai-model-hdr"><span class="ai-dot" style="background:{m['color']}"></span><span class="ai-mname">{m['label']}</span>{"" if rl['available'] else '<span class="ai-rl-badge">Rate Limited</span>'}</div>
  <div class="ai-mdesc">{m['desc']}</div>
</div>"""
 
    # Alt data badges
    alt_data_badges = """
<div class="alt-data-row">
  <span class="alt-data-badge"><span class="alt-dot"></span>FRED Macro</span>
  <span class="alt-data-badge"><span class="alt-dot"></span>Google Trends</span>
  <span class="alt-data-badge"><span class="alt-dot"></span>Fundamentals</span>
  <span class="alt-data-badge"><span class="alt-dot"></span>10 Technicals</span>
  <span class="alt-data-badge"><span class="alt-dot"></span>AIS Shipping</span>
  <span class="alt-data-badge"><span class="alt-dot"></span>Sentiment Proxy</span>
</div>"""
 
    # Sector tiles
    sector_tiles = "".join(
        f'<button class="s-tile" onclick="selectAndFetch(\'{sid}\')">'
        f'<span class="s-tile-key">{cfg["key"]}</span>'
        f'<span class="s-tile-name">{cfg["label"]}</span>'
        f'<span class="s-tile-sub">{cfg["sub"]}</span></button>\n'
        for sid, cfg in SECTORS.items())
 
    sector_opts = "".join(
        f'<option value="{sid}">{cfg["label"]} · {cfg["key"]}</option>'
        for sid, cfg in SECTORS.items())
 
    fh = NEWS_CHANNELS[0]["handle"]
    ai_js = json.dumps(list(active_indicators))
    models_js = json.dumps([{"id":m["id"],"key":m["key"],"label":m["label"],"color":m["color"]} for m in AI_MODELS])
 
    logo_img = f'<img src="{logo_uri}" height="44" style="display:block; filter:grayscale(1) contrast(150%);" alt="Starfish Logo">' if logo_uri else ''
 
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width,initial-scale=1.0"/>
  <title>STARFISH — Market Dynamics + Alpaca Live Trading</title>
  <link rel="preconnect" href="https://fonts.googleapis.com"/>
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin/>
  <link href="https://fonts.googleapis.com/css2?family=DM+Sans:opsz,wght@9..40,300;9..40,400;9..40,500;9..40,600&family=DM+Mono:wght@400;500&display=swap" rel="stylesheet"/>
  <script src="https://cdn.plot.ly/plotly-2.27.0.min.js"></script>
  <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.css"/>
  <script src="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.js"></script>
  <style>
    *,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
    :root{{
      --bg:#ffffff;--sur:#f8f7f4;--bdr:#000000;--bds:#e5e5e5;
      --tx:#000000;--txm:#555555;--txd:#888888;--acc:#000000;--acm:rgba(0,0,0,.05);
      --blur:none;--r:12px;--rs:4px;
      --gold:#000;--gold-dim:#f0f0f0;--gold-bdr:#000;
      --teal:#333;--teal-dim:#f0f0f0;--teal-bdr:#aaa;
    }}
    html{{scroll-behavior:smooth;overflow-x:hidden}}
    body{{font-family:'DM Sans',sans-serif;background:var(--bg);color:var(--tx);min-height:100vh;
         -webkit-font-smoothing:antialiased;overflow-x:hidden;width:100%}}
 
    /* ── HEADER ── */
    header{{position:sticky;top:0;z-index:100;height:58px;display:flex;align-items:center;
            justify-content:space-between;padding:0 28px;background:#ffffff;
            border-bottom:2px solid #000}}
    .logo{{display:flex;align-items:center;gap:11px}}
    .logo-star{{flex-shrink:0}}
    .logo-text-group{{display:flex;flex-direction:column;gap:2px;line-height:1}}
    .logo-word{{font-size:.8rem;font-weight:700;letter-spacing:.24em;text-transform:uppercase;color:#000}}
    .logo-tagline{{font-size:.5rem;font-weight:500;letter-spacing:.16em;text-transform:uppercase;color:#888}}
    .header-nav{{display:flex;gap:6px}}
    .nav-link{{font-size:.65rem;font-weight:600;letter-spacing:.1em;text-transform:uppercase;
               color:#555;padding:5px 12px;border-radius:4px;cursor:pointer;
               transition:all .15s;text-decoration:none;border:1px solid transparent}}
    .nav-link:hover{{color:#000;background:#f0f0f0;border-color:#000}}
 
    /* ── ALPACA LIVE TRADING SECTION STYLES ── */
    .alpaca-panel{{padding:26px 30px;margin-bottom:18px;background:#f8f7f4;border:2px solid #000;border-radius:var(--r)}}
    .alpaca-header{{display:flex;justify-content:space-between;align-items:center;margin-bottom:20px;flex-wrap:wrap;gap:12px}}
    .alpaca-title{{font-size:.7rem;font-weight:700;letter-spacing:.16em;text-transform:uppercase;color:#000}}
    .alpaca-badge{{font-family:'DM Mono',monospace;font-size:.55rem;color:#555;background:#f0f0f0;border:1px solid #000;border-radius:4px;padding:4px 10px}}
    .alpaca-stats{{display:flex;gap:16px;flex-wrap:wrap;margin-bottom:20px;padding-bottom:16px;border-bottom:1px solid #e5e5e5}}
    .alpaca-stat{{background:#fff;border:1px solid #000;border-radius:var(--rs);padding:12px 18px;flex:1;min-width:100px}}
    .alpaca-stat-label{{font-size:.55rem;font-weight:700;letter-spacing:.12em;text-transform:uppercase;color:#888;margin-bottom:6px}}
    .alpaca-stat-value{{font-family:'DM Mono',monospace;font-size:1.1rem;font-weight:700;color:#000}}
    .alpaca-filter{{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:20px}}
    .alpaca-filter-btn{{background:transparent;border:1px solid #000;border-radius:20px;padding:4px 14px;font-size:.68rem;font-family:'DM Mono',monospace;cursor:pointer;color:#555;transition:all .15s}}
    .alpaca-filter-btn:hover,.alpaca-filter-btn.active{{background:#000;color:#fff}}
    .alpaca-sort{{margin-left:auto;display:flex;align-items:center;gap:8px}}
    .alpaca-sort-label{{font-size:.58rem;font-weight:700;letter-spacing:.1em;text-transform:uppercase;color:#888}}
    .alpaca-sort-select{{background:#fff;border:1px solid #000;border-radius:4px;padding:5px 10px;font-family:'DM Mono',monospace;font-size:.7rem;outline:none}}
    .alpaca-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:12px}}
    .alpaca-card{{background:#fff;border:1px solid #000;border-radius:var(--r);padding:16px;transition:transform .18s,box-shadow .18s;animation:card-in .3s ease both}}
    .alpaca-card:hover{{transform:translateY(-2px);box-shadow:0 4px 16px rgba(0,0,0,.12)}}
    .alpaca-card.up{{border-left:3px solid #26a69a}}
    .alpaca-card.down{{border-left:3px solid #ef5350}}
    .alpaca-card-sym{{font-family:'Bebas Neue',sans-serif;font-size:1.2rem;font-weight:700;letter-spacing:1px;color:#000}}
    .alpaca-card-name{{font-size:.6rem;color:#888;margin-bottom:8px}}
    .alpaca-price-row{{display:flex;justify-content:space-between;align-items:flex-end;margin-bottom:12px}}
    .alpaca-price{{font-family:'DM Mono',monospace;font-size:1.2rem;font-weight:700}}
    .alpaca-card.up .alpaca-price{{color:#26a69a}}
    .alpaca-card.down .alpaca-price{{color:#ef5350}}
    .alpaca-change{{font-family:'DM Mono',monospace;font-size:.7rem}}
    .alpaca-change.up-t{{color:#26a69a}}.alpaca-change.down-t{{color:#ef5350}}
    .alpaca-bidask{{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:10px}}
    .alpaca-ba{{background:#f8f7f4;border:1px solid #e5e5e5;border-radius:4px;padding:8px}}
    .alpaca-ba-label{{font-size:.5rem;text-transform:uppercase;letter-spacing:.1em;color:#888;margin-bottom:3px}}
    .alpaca-ba-price{{font-family:'DM Mono',monospace;font-size:.8rem;font-weight:600}}
    .alpaca-bid .alpaca-ba-price{{color:#ef5350}}
    .alpaca-ask .alpaca-ba-price{{color:#26a69a}}
    .alpaca-ba-size{{font-size:.55rem;color:#888}}
    .alpaca-footer{{display:flex;justify-content:space-between;align-items:center;margin-top:10px;padding-top:10px;border-top:1px solid #e5e5e5}}
    .alpaca-vol{{font-size:.6rem;color:#888}}
    .alpaca-dtype{{font-family:'DM Mono',monospace;font-size:.55rem;padding:2px 7px;border-radius:3px;font-weight:600}}
    .alpaca-dtype.LIVE{{background:#e8f5e9;color:#2e7d32;border:1px solid #2e7d32}}
    .alpaca-dtype.TRADE{{background:#e3f2fd;color:#1565c0;border:1px solid #1565c0}}
    .alpaca-dtype.QUOTE{{background:#fff3e0;color:#e65100;border:1px solid #e65100}}
    .alpaca-dtype.BAR{{background:#f5f5f5;color:#616161;border:1px solid #616161}}
 
    /* Alpaca status bar */
    .alpaca-status{{display:flex;align-items:center;gap:8px;margin-top:16px;padding-top:14px;border-top:1px solid #e5e5e5}}
    .alpaca-led{{width:8px;height:8px;border-radius:50%;background:#44cc44;flex-shrink:0;animation:pulse 2s ease-in-out infinite}}
    @keyframes pulse{{0%,100%{{opacity:1;transform:scale(1)}}50%{{opacity:.4;transform:scale(.8)}}}}
    .alpaca-status-text{{font-size:.6rem;color:#888;font-family:'DM Mono',monospace}}
 
    /* ── rest of Starfish styles (same as original) ── */
    .ticker-strip{{position:relative;z-index:10;height:32px;overflow:hidden;display:flex;
                   align-items:center;background:#000;border-bottom:1px solid #000}}
    .ticker-strip::before,.ticker-strip::after{{content:'';position:absolute;top:0;bottom:0;width:60px;z-index:2}}
    .ticker-strip::before{{left:0;background:linear-gradient(90deg,#000 40%,transparent)}}
    .ticker-strip::after{{right:0;background:linear-gradient(-90deg,#000 40%,transparent)}}
    .ticker-badge{{position:absolute;left:0;height:100%;z-index:3;display:flex;align-items:center;
                   padding:0 .9rem;background:#fff;white-space:nowrap;
                   font-size:.56rem;font-weight:700;letter-spacing:.18em;text-transform:uppercase;color:#000}}
    .ticker-track{{display:flex;animation:ticker-run 40s linear infinite;white-space:nowrap;width:max-content;will-change:transform}}
    .ticker-track:hover{{animation-play-state:paused}}
    .t-item{{font-family:'DM Mono',monospace;font-size:.6rem;font-weight:400;letter-spacing:.08em;
             color:rgba(255,255,255,.55);padding:0 1.5rem;white-space:nowrap;flex-shrink:0}}
    .t-item strong{{color:rgba(255,255,255,.9);font-weight:500}}
    .t-sep{{color:rgba(255,255,255,.3)}}
    @keyframes ticker-run{{from{{transform:translate3d(0,0,0)}}to{{transform:translate3d(-50%,0,0)}}}}
 
    main{{position:relative;z-index:1;max-width:1400px;margin:0 auto;padding:30px 20px 64px}}
    .glass{{background:#f8f7f4;border:2px solid #000;border-radius:var(--r);contain:layout style}}
    .panel{{padding:26px 30px;margin-bottom:18px}}
    .section-divider{{display:flex;align-items:center;gap:14px;margin:36px 0 20px}}
    .section-divider-line{{flex:1;height:1px;background:#e5e5e5}}
    .section-label{{font-size:.6rem;font-weight:700;letter-spacing:.22em;text-transform:uppercase;
                    color:#888;white-space:nowrap;display:flex;align-items:center;gap:8px}}
 
    /* Mobile responsive additions (condensed) */
    @media(max-width:860px){{
      .alpaca-grid{{grid-template-columns:repeat(auto-fill,minmax(260px,1fr))}}
      .alpaca-stats{{flex-direction:column;gap:8px}}
      .alpaca-stat{{min-width:auto}}
    }}
    @media(max-width:600px){{
      .alpaca-panel{{padding:14px 12px}}
      .alpaca-header{{flex-direction:column;align-items:flex-start}}
      .alpaca-filter{{order:2;margin-bottom:12px}}
      .alpaca-sort{{order:3;margin-left:0}}
      .alpaca-grid{{grid-template-columns:1fr}}
    }}
  </style>
</head>
<body>
 
<!-- ── HEADER ── -->
<header>
  <div class="logo">
    {logo_img}
    <div class="logo-text-group">
      <span class="logo-word">STARFISH</span>
      <span class="logo-tagline">Market Dynamics + Alpaca Live</span>
    </div>
  </div>
  <nav class="header-nav">
    <a class="nav-link" href="#stocks">Stocks</a>
    <a class="nav-link" href="#alpaca">Live Trading</a>
    <a class="nav-link" href="#sectors">Sectors</a>
    <a class="nav-link" href="#live-news">Live News</a>
    <a class="nav-link" href="#vessels">Data</a>
  </nav>
</header>
 
<!-- ── TICKER STRIP ── -->
<div class="ticker-strip">
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
    <span class="t-item">FRED Macro &middot; Google Trends &middot; AIS Shipping &middot; Alpaca Live &middot; 10 Indicators <span class="t-sep">&middot;</span></span>
  </div>
</div>
 
<main>
 
<!-- ══════════════════════════════════════════
     ALPACA LIVE TRADING PANEL (NEW)
═══════════════════════════════════════════ -->
<div class="section-divider" id="alpaca">
  <div class="section-divider-line"></div>
  <div class="section-label"><span class="dot" style="background:#000"></span>Alpaca Live Trading</div>
  <div class="section-divider-line"></div>
</div>

<div class="alpaca-panel">
  <div class="alpaca-header">
    <span class="alpaca-title">ALPACA PAPER TRADING · LIVE MARKET DATA</span>
    <span class="alpaca-badge">WebSocket Real-Time</span>
  </div>
  
  <div class="alpaca-stats" id="alpaca-stats">
    <div class="alpaca-stat"><div class="alpaca-stat-label">Portfolio Value</div><div class="alpaca-stat-value" id="a-pv">—</div></div>
    <div class="alpaca-stat"><div class="alpaca-stat-label">Cash</div><div class="alpaca-stat-value" id="a-cash">—</div></div>
    <div class="alpaca-stat"><div class="alpaca-stat-label">Buying Power</div><div class="alpaca-stat-value" id="a-bp">—</div></div>
    <div class="alpaca-stat"><div class="alpaca-stat-label">Equity</div><div class="alpaca-stat-value" id="a-eq">—</div></div>
    <div class="alpaca-stat"><div class="alpaca-stat-label">Status</div><div class="alpaca-stat-value" id="a-st">—</div></div>
  </div>
  
  <div class="alpaca-filter">
    <button class="alpaca-filter-btn active" onclick="setAlpacaFilter('ALL')">ALL</button>
    <button class="alpaca-filter-btn" onclick="setAlpacaFilter('Technology')">TECH</button>
    <button class="alpaca-filter-btn" onclick="setAlpacaFilter('Finance')">FINANCE</button>
    <button class="alpaca-filter-btn" onclick="setAlpacaFilter('Consumer')">CONSUMER</button>
    <button class="alpaca-filter-btn" onclick="setAlpacaFilter('Automotive')">AUTO</button>
    <button class="alpaca-filter-btn" onclick="setAlpacaFilter('Healthcare')">HEALTH</button>
    <button class="alpaca-filter-btn" onclick="setAlpacaFilter('ETF')">ETF</button>
    <div class="alpaca-sort">
      <span class="alpaca-sort-label">SORT</span>
      <select id="alpaca-sort" class="alpaca-sort-select" onchange="renderAlpacaGrid()">
        <option value="default">DEFAULT</option>
        <option value="price-desc">PRICE ↓</option>
        <option value="price-asc">PRICE ↑</option>
        <option value="chg-desc">GAIN ↓</option>
        <option value="chg-asc">LOSS ↓</option>
        <option value="vol-desc">VOLUME ↓</option>
      </select>
    </div>
  </div>
  
  <div id="alpaca-grid" class="alpaca-grid">
    <div style="text-align:center;padding:40px;color:#888">Loading live market data from Alpaca…</div>
  </div>
  
  <div class="alpaca-status">
    <div class="alpaca-led"></div>
    <span class="alpaca-status-text" id="alpaca-status-text">WebSocket connected · Real-time trades & quotes</span>
    <span id="alpaca-last-update" style="font-size:.55rem;color:#aaa;margin-left:auto"></span>
  </div>
</div>

<!-- ══════════════════════════════════════════
     STOCKS SECTION (existing Starfish)
═══════════════════════════════════════════ -->
<div class="section-divider" id="stocks">
  <div class="section-divider-line"></div>
  <div class="section-label"><span class="dot" style="background:#26a69a"></span>Stocks &amp; Charts</div>
  <div class="section-divider-line"></div>
</div>
 
<div class="glass panel">
  <div class="panel-label">Search</div>
  <form method="POST" action="/" id="main-form">
    <input type="hidden" name="indicators" id="inds-h" value="{','.join(active_indicators)}"/>
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

<!-- GBM Monte Carlo Simulation (existing) -->
<div class="glass panel" id="gbm-panel" style="margin-top:12px">
  <div class="panel-label">Monte Carlo Price Simulation (GBM)</div>
  <div style="display:flex;flex-wrap:wrap;gap:8px;align-items:flex-end;margin-bottom:12px">
    <div class="fg" style="min-width:80px;flex:1">
      <label style="font-size:.7rem;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:#787b86">Ticker</label>
      <input id="gbm-ticker" type="text" value="{ticker}"
        style="width:100%;box-sizing:border-box;background:#f5f7fa;border:1.5px solid #e0e3eb;border-radius:6px;padding:.5rem .75rem;font-size:.875rem;font-family:inherit;outline:none;color:#131722"
        autocapitalize="characters" spellcheck="false"/>
    </div>
    <div class="fg" style="min-width:80px;flex:1">
      <label style="font-size:.7rem;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:#787b86">Horizon (years)</label>
      <select id="gbm-years" style="width:100%;box-sizing:border-box;background:#f5f7fa;border:1.5px solid #e0e3eb;border-radius:6px;padding:.5rem .75rem;font-size:.875rem;font-family:inherit;outline:none;color:#131722">
        <option value="1">1 year</option>
        <option value="2" selected>2 years</option>
        <option value="3">3 years</option>
        <option value="5">5 years</option>
        <option value="10">10 years</option>
      </select>
    </div>
    <div class="fg" style="min-width:80px;flex:1">
      <label style="font-size:.7rem;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:#787b86">Scenarios</label>
      <select id="gbm-scenarios" style="width:100%;box-sizing:border-box;background:#f5f7fa;border:1.5px solid #e0e3eb;border-radius:6px;padding:.5rem .75rem;font-size:.875rem;font-family:inherit;outline:none;color:#131722">
        <option value="100">100</option>
        <option value="200" selected>200</option>
        <option value="500">500</option>
        <option value="1000">1000</option>
      </select>
    </div>
    <button onclick="runGBM()" id="gbm-btn" class="btn" style="height:38px;align-self:flex-end;white-space:nowrap;flex-shrink:0">
      &#9654; Run Simulation
    </button>
  </div>
  <div id="gbm-status" style="font-size:.78rem;color:#787b86;min-height:0;margin-bottom:0"></div>
  <div id="gbm-chart" style="width:100%;height:0;overflow:hidden;transition:height .3s ease"></div>
  <div id="gbm-hist"  style="width:100%;height:0;overflow:hidden;margin-top:0;transition:height .3s ease"></div>
  <div id="gbm-stats" style="display:none;margin-top:10px;padding:10px 14px;background:#f5f7fa;border-radius:8px;font-size:.78rem;color:#131722;line-height:1.7"></div>
</div>

<!-- AI Analysis (existing) -->
<div class="glass ai-panel">
  <div class="panel-label">AI Trading Analysis</div>
  {alt_data_badges}
  <div class="ai-models-grid" id="ai-grid">{ai_cards}</div>
  <div class="ai-action-row">
    <button class="btn-ai" id="btn-ai" onclick="runAnalysis()" disabled>Analyse&nbsp;{ticker}</button>
    <span class="ai-sel-label" id="ai-sel-lbl"></span>
    <span class="ai-timer" id="ai-timer"></span>
  </div>
  <div class="ai-result" id="ai-result"></div>
</div>

<!-- Prediction Markets (existing) -->
<div class="section-divider" id="pred-markets">
  <div class="section-divider-line"></div>
  <div class="section-label"><span class="dot" style="background:#000"></span>Prediction Markets</div>
  <div class="section-divider-line"></div>
</div>

<div class="glass sector-panel">
  <div class="panel-label">Market Consensus Search</div>
  <div class="sector-selector-row">
    <div class="sector-select-wrap" style="background:#fff">
      <span class="sel-prefix">Query</span>
      <input id="pred-query" type="text" placeholder="e.g. Fed rate cut, Trump, Bitcoin ETF…"
        style="flex:1;background:transparent;border:none;outline:none;padding:.75rem 1rem;font-family:inherit;font-size:.875rem;font-weight:500;color:#000;min-width:0"
        onkeydown="if(event.key==='Enter')searchPredMarkets()"
      />
    </div>
    <button onclick="searchPredMarkets()" id="pred-btn" class="btn-sector">
      Search Markets
    </button>
  </div>
  <div id="pred-status" class="res-time-badge" style="margin-bottom:12px"></div>
  <div id="pred-chart-wrap" style="display:none;background:#fff;border:2px solid #000;border-radius:var(--r);overflow:hidden;margin-bottom:16px">
    <div id="pred-chart" style="width:100%;height:340px"></div>
  </div>
  <div id="pred-table-wrap" style="display:none;overflow-x:auto">
    <table id="pred-table" style="width:100%;border-collapse:collapse;font-size:.8rem;table-layout:fixed">
      <colgroup>
        <col style="width:90px">
        <col>
        <col style="width:54px">
        <col style="width:56px">
        <col style="width:70px">
      </colgroup>
      <thead>
        <tr style="border-bottom:2px solid #000">
          <th style="text-align:left;padding:8px 8px;font-size:.6rem;font-weight:700;letter-spacing:.12em;text-transform:uppercase;color:#888">Platform</th>
          <th style="text-align:left;padding:8px 8px;font-size:.6rem;font-weight:700;letter-spacing:.12em;text-transform:uppercase;color:#888">Market</th>
          <th style="text-align:right;padding:8px 8px;font-size:.6rem;font-weight:700;letter-spacing:.12em;text-transform:uppercase;color:#888">Prob</th>
          <th style="text-align:left;padding:8px 8px;font-size:.6rem;font-weight:700;letter-spacing:.12em;text-transform:uppercase;color:#888">Side</th>
          <th style="text-align:right;padding:8px 8px;font-size:.6rem;font-weight:700;letter-spacing:.12em;text-transform:uppercase;color:#888">Volume</th>
        </table>
      </thead>
      <tbody id="pred-tbody"></tbody>
    </table>
  </div>
  <div id="pred-empty" style="display:none;text-align:center;padding:40px 20px;color:#888;font-size:.85rem">No matching markets found.</div>
</div>

<!-- ══════════════════════════════════════════
     SECTION 2: SECTORS (existing)
═══════════════════════════════════════════ -->
<div class="section-divider" id="sectors">
  <div class="section-divider-line"></div>
  <div class="section-label"><span class="dot" style="background:rgba(200,134,10,.8)"></span>Sector Intelligence</div>
  <div class="section-divider-line"></div>
</div>
 
<div class="glass sector-panel">
  <div class="panel-label">Browse GICS Sectors</div>
  <div class="sector-selector-row">
    <div class="sector-select-wrap">
      <span class="sel-prefix">Sector</span>
      <select id="sector-sel" class="sector-select">
        <option value="">Select a GICS Sector —</option>
        {sector_opts}
      </select>
    </div>
    <button class="btn-sector" id="fetchSectorBtn" onclick="fetchSectorNews()">
      Analyse &#8594;
    </button>
  </div>
 
  <div class="sector-grid">
    {sector_tiles}
  </div>
 
  <div id="sector-output"></div>
  <div id="sector-satellite"></div>
</div>
 
<!-- ══════════════════════════════════════════
     SECTION 3: LIVE NEWS (existing)
═══════════════════════════════════════════ -->
<div class="section-divider" id="live-news">
  <div class="section-divider-line"></div>
  <div class="section-label"><span class="dot" style="background:#ff4444"></span>Live Financial News</div>
  <div class="section-divider-line"></div>
</div>
 
<div class="glass news-panel">
  <div class="panel-label"><span class="news-live-dot"></span>Live Streams</div>
  <div class="news-tabs" id="ntabs">{ntabs}</div>
  <div class="news-iframe-wrap">
    <div id="nload" class="news-loading"><div class="news-spinner"></div><span>Loading stream&hellip;</span></div>
    <iframe id="nframe" allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture" allowfullscreen style="display:none"></iframe>
  </div>
  <div style="margin-top:10px;display:flex;align-items:center;gap:10px;flex-wrap:wrap;">
    <span id="nbadge" class="nsb" style="display:none"></span>
  </div>
</div>

<!-- ══════════════════════════════════════════
     SECTION 4: LIVE VESSEL TRACKER (existing)
═══════════════════════════════════════════ -->
<div class="section-divider" id="vessels">
  <div class="section-divider-line"></div>
  <div class="section-label"><span class="dot" style="background:#00c8ff"></span>Live Vessel Tracker</div>
  <div class="section-divider-line"></div>
</div>

<div class="glass" style="padding:0;overflow:hidden;border-radius:12px;content-visibility:auto;contain-intrinsic-size:0 700px;">
  <div style="padding:10px 16px;border-bottom:1px solid #e8e8e8;display:flex;align-items:center;gap:10px;flex-wrap:wrap;">
    <span class="panel-label" style="margin:0;">AIS Live Map</span>
    <button id="ais-toggle-btn" onclick="toggleAIS()" style="font-size:.58rem;font-weight:700;letter-spacing:.08em;text-transform:uppercase;padding:3px 12px;border-radius:20px;border:1px solid rgba(255,100,100,.5);background:rgba(255,100,100,.08);color:#cc3333;cursor:pointer;font-family:inherit;transition:all .2s;">&#9654; Start</button>
    <span id="ais-vessel-badge" style="margin-left:auto;font-size:.58rem;font-weight:600;letter-spacing:.08em;text-transform:uppercase;color:#555;background:#f4f4f4;border:1px solid #e0e0e0;border-radius:20px;padding:3px 10px;">Stopped</span>
  </div>
  <iframe id="vessel-iframe" src="/vessels" style="width:100%;height:660px;border:none;display:block;" title="Live Vessel Tracker" loading="lazy"></iframe>
</div>

<div class="section-divider" id="aircraft">
  <div class="section-divider-line"></div>
  <div class="section-label"><span class="dot" style="background:#ffaa33"></span>Live Aircraft Tracker</div>
  <div class="section-divider-line"></div>
</div>

<div class="glass" style="padding:0;overflow:hidden;border-radius:12px;content-visibility:auto;contain-intrinsic-size:0 700px;">
  <div style="padding:10px 16px;border-bottom:1px solid #e8e8e8;display:flex;align-items:center;gap:10px;flex-wrap:wrap;">
    <span class="panel-label" style="margin:0;">ADS-B Live Map</span>
    <button id="adsb-toggle-btn" onclick="toggleADSB()" style="font-size:.58rem;font-weight:700;letter-spacing:.08em;text-transform:uppercase;padding:3px 12px;border-radius:20px;border:1px solid rgba(255,100,100,.5);background:rgba(255,100,100,.08);color:#cc3333;cursor:pointer;font-family:inherit;transition:all .2s;">&#9654; Start</button>
    <span id="adsb-aircraft-badge" style="font-size:.58rem;font-weight:600;letter-spacing:.08em;text-transform:uppercase;color:#555;background:#f4f4f4;border:1px solid #e0e0e0;border-radius:20px;padding:3px 10px;">Stopped</span>
  </div>
  <iframe id="aircraft-iframe" src="/aircraft" style="width:100%;height:660px;border:none;display:block;" title="Live Aircraft Tracker"></iframe>
</div>

<!-- ══════════════════════════════════════════
     SECTION 5: LIVE SATELLITE IMAGERY (existing)
═══════════════════════════════════════════ -->
<div class="section-divider" id="satellite-viewer">
  <div class="section-divider-line"></div>
  <div class="section-label"><span class="dot" style="background:#000"></span>Live Satellite Imagery</div>
  <div class="section-divider-line"></div>
</div>

<div class="glass sat-viewer-panel">
  <div class="sat-viewer-toolbar">
    <span class="panel-label" style="margin:0;white-space:nowrap;">Sentinel-2 Live View</span>
    <span style="font-family:'DM Mono',monospace;font-size:.55rem;color:#555;background:#f0f0f0;border:1px solid #ccc;border-radius:20px;padding:3px 8px;">COPERNICUS ESA</span>
    <button id="sat-toggle-btn" onclick="toggleSat()" style="font-size:.58rem;font-weight:700;letter-spacing:.08em;text-transform:uppercase;padding:3px 12px;border-radius:20px;border:1px solid rgba(255,100,100,.5);background:rgba(255,100,100,.08);color:#cc3333;cursor:pointer;font-family:inherit;transition:all .2s;">&#9654; Start</button>
    <div class="sat-search-wrap">
      <input class="sat-search-input" id="satSearchInput" type="text" placeholder="Search location…" autocomplete="off">
      <button class="sat-search-btn" onclick="satDoSearch()">&#9906;</button>
      <div class="sat-search-results" id="satSearchResults"></div>
    </div>
    <span class="sat-token-badge" id="satTokenBadge">TOKEN &#8212;</span>
  </div>
  <div class="sat-layer-grid" style="margin-top:12px;">
    <button class="sat-vlayer-btn active" data-layer="TRUE-COLOR" onclick="satSelectLayer(this)">TRUE COLOR</button>
    <button class="sat-vlayer-btn" data-layer="FALSE-COLOR" onclick="satSelectLayer(this)">FALSE COLOR</button>
    <button class="sat-vlayer-btn" data-layer="NDVI" onclick="satSelectLayer(this)">NDVI</button>
    <button class="sat-vlayer-btn" data-layer="SWIR" onclick="satSelectLayer(this)">SWIR</button>
    <button class="sat-vlayer-btn" data-layer="GEOLOGY" onclick="satSelectLayer(this)">GEOLOGY</button>
  </div>
  <div class="sat-viewer-map-wrap">
    <div id="satMap" class="sat-viewer-map" style="width:100%;height:100%;"></div>
  </div>
  <div class="sat-viewer-sidebar">
    <div class="sat-viewer-row">
      <div class="sat-vfield">
        <label>From Date</label>
        <input type="date" id="satDateFrom">
      </div>
      <div class="sat-vfield">
        <label>To Date</label>
        <input type="date" id="satDateTo">
      </div>
    </div>
    <div class="sat-vfield">
      <div class="sat-cloud-row">
        <label style="white-space:nowrap;">Cloud Cover &#8804;</label>
        <input type="range" id="satCloudSlider" min="0" max="100" value="30"
               oninput="document.getElementById('satCloudVal').textContent=this.value+'%'">
        <span class="sat-cloud-val" id="satCloudVal">30%</span>
      </div>
    </div>
  </div>
  <div class="sat-load-btn-wrap" style="padding:0 16px 16px"><button class="sat-load-btn" id="satLoadBtn" onclick="satApplyLayer()">&#9632; LOAD SATELLITE DATA</button></div>
  <div class="sat-status-bar">
    <span class="sat-status-dot" id="satStatusDot"></span>
    <span id="satStatusText">Ready — Copernicus Sentinel-2 L2A</span>
  </div>
  <div class="sat-log" id="satLog">
    <div class="sat-log-entry">&#9658; Satellite viewer initialised</div>
  </div>
</div>

</main>
 
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
      <span class="disclaimer-label">Disclaimer</span>Financial information is sourced from Yahoo Finance, FRED (Federal Reserve Bank of St. Louis), Google Trends, Alpaca Paper Trading, public AIS shipping data, and open data providers — presented solely for informational and educational purposes. AI analyses powered by DeepSeek, Qwen, and Meta&rsquo;s Llama via OpenRouter using live macro data, fundamentals, and search-interest signals. Alpaca data is live from IEX exchange (paper trading environment). Not financial advice. Consult qualified professionals before making investment decisions.
    </p>
  </div>
</div>
 
<!-- ── FOOTER ── -->
<footer class="site-footer">
  <div class="site-footer-sub">made by</div>
  <div class="site-footer-name">ANTON BESKI</div>
</footer>
 
<script>
var TICKER  = {json.dumps(ticker)};
var PERIOD  = {json.dumps(period)};
var MODELS  = {models_js};

// ── ALPACA LIVE TRADING JAVASCRIPT ──────────────────────────────────────────
var alpacaAllStocks = [];
var alpacaFilter = 'ALL';
var alpacaPrevPrices = {{}};

function setAlpacaFilter(f) {{
  alpacaFilter = f;
  document.querySelectorAll('.alpaca-filter-btn').forEach(btn => {{
    const btnText = btn.textContent.trim();
    const match = (f === 'ALL' && btnText === 'ALL') ||
                  (f === 'Technology' && btnText === 'TECH') ||
                  (f === 'Finance' && btnText === 'FINANCE') ||
                  (f === 'Consumer' && btnText === 'CONSUMER') ||
                  (f === 'Automotive' && btnText === 'AUTO') ||
                  (f === 'Healthcare' && btnText === 'HEALTH') ||
                  (f === 'ETF' && btnText === 'ETF');
    if (match) btn.classList.add('active');
    else btn.classList.remove('active');
  }});
  renderAlpacaGrid();
}}

function renderAlpacaGrid() {{
  let stocks = [...alpacaAllStocks];
  if (alpacaFilter !== 'ALL') stocks = stocks.filter(s => s.sector === alpacaFilter);
  
  const sortVal = document.getElementById('alpaca-sort').value;
  if (sortVal === 'price-desc') stocks.sort((a,b) => b.price - a.price);
  else if (sortVal === 'price-asc') stocks.sort((a,b) => a.price - b.price);
  else if (sortVal === 'chg-desc') stocks.sort((a,b) => b.change_pct - a.change_pct);
  else if (sortVal === 'chg-asc') stocks.sort((a,b) => a.change_pct - b.change_pct);
  else if (sortVal === 'vol-desc') stocks.sort((a,b) => (b.volume || 0) - (a.volume || 0));
  
  const grid = document.getElementById('alpaca-grid');
  if (!stocks.length) {{
    grid.innerHTML = '<div style="text-align:center;padding:40px;color:#888">No stocks match filter</div>';
    return;
  }}
  
  grid.innerHTML = stocks.map(s => {{
    const dir = s.change_pct > 0 ? 'up' : (s.change_pct < 0 ? 'down' : '');
    const sign = s.change_pct >= 0 ? '+' : '';
    const changeClass = s.change_pct > 0 ? 'up-t' : (s.change_pct < 0 ? 'down-t' : 'flat-t');
    const changeColor = s.change_pct > 0 ? '#26a69a' : (s.change_pct < 0 ? '#ef5350' : '#888');
    
    return `<div class="alpaca-card ${dir}" id="acard-${{s.symbol}}">
      <div class="alpaca-card-sym">${{s.symbol}}</div>
      <div class="alpaca-card-name">${{s.name}}</div>
      <div class="alpaca-price-row">
        <div class="alpaca-price">$${{s.price ? s.price.toFixed(2) : '—'}}</div>
        <div class="alpaca-change ${{changeClass}}">${{sign}}${{s.change_pct ? s.change_pct.toFixed(2) : '0.00'}}%</div>
      </div>
      <div class="alpaca-bidask">
        <div class="alpaca-ba alpaca-bid">
          <div class="alpaca-ba-label">BID</div>
          <div class="alpaca-ba-price">$${{s.bid ? s.bid.toFixed(2) : '—'}}</div>
          <div class="alpaca-ba-size">${{s.bid_size ? s.bid_size.toLocaleString() : ''}}</div>
        </div>
        <div class="alpaca-ba alpaca-ask">
          <div class="alpaca-ba-label">ASK</div>
          <div class="alpaca-ba-price">$${{s.ask ? s.ask.toFixed(2) : '—'}}</div>
          <div class="alpaca-ba-size">${{s.ask_size ? s.ask_size.toLocaleString() : ''}}</div>
        </div>
      </div>
      <div class="alpaca-footer">
        <div class="alpaca-vol">VOL ${{s.volume ? s.volume.toLocaleString() : '—'}}</div>
        <div class="alpaca-dtype ${{s.data_type}}">${{s.data_type}}</div>
      </div>
    </div>`;
  }}).join('');
  
  // Flash animation for price changes
  stocks.forEach(s => {{
    if (alpacaPrevPrices[s.symbol] !== undefined && alpacaPrevPrices[s.symbol] !== s.price) {{
      const el = document.getElementById('acard-' + s.symbol);
      if (el) {{
        const cls = s.price > alpacaPrevPrices[s.symbol] ? 'flash-up' : 'flash-down';
        el.classList.add(cls);
        setTimeout(() => el.classList.remove(cls), 800);
      }}
    }}
    alpacaPrevPrices[s.symbol] = s.price;
  }});
}}

async function fetchAlpacaStocks() {{
  try {{
    const r = await fetch('/api/alpaca-stocks');
    const data = await r.json();
    if (data.error) {{
      console.error('Alpaca error:', data.error);
      document.getElementById('alpaca-status-text').textContent = 'Error: ' + data.error;
      return;
    }}
    alpacaAllStocks = data.stocks || [];
    renderAlpacaGrid();
    document.getElementById('alpaca-last-update').textContent = data.updated;
    document.getElementById('alpaca-status-text').textContent = 'WebSocket live · ' + alpacaAllStocks.length + ' symbols';
  }} catch(e) {{
    console.error('Alpaca fetch error:', e);
    document.getElementById('alpaca-status-text').textContent = 'Connection error — retrying';
  }}
}}

async function fetchAlpacaAccount() {{
  try {{
    const r = await fetch('/api/alpaca-account');
    const d = await r.json();
    if (!d.error) {{
      document.getElementById('a-pv').textContent = d.portfolio_value ? '$' + Number(d.portfolio_value).toLocaleString(undefined, {{minimumFractionDigits:2}}) : '—';
      document.getElementById('a-cash').textContent = d.cash ? '$' + Number(d.cash).toLocaleString(undefined, {{minimumFractionDigits:2}}) : '—';
      document.getElementById('a-bp').textContent = d.buying_power ? '$' + Number(d.buying_power).toLocaleString(undefined, {{minimumFractionDigits:2}}) : '—';
      document.getElementById('a-eq').textContent = d.equity ? '$' + Number(d.equity).toLocaleString(undefined, {{minimumFractionDigits:2}}) : '—';
      document.getElementById('a-st').textContent = (d.status || 'ACTIVE').toUpperCase();
    }}
  }} catch(e) {{ console.error(e); }}
}}

// ── Existing Starfish functions ─────────────────────────────────────────────
function setTicker(s){{document.getElementById('ticker').value=s;document.getElementById('main-form').submit();}}
var aInds = {ai_js};
function toggleInd(el){{
  var k=el.dataset.ind,i=aInds.indexOf(k);
  i===-1?(aInds.push(k),el.classList.add('active')):(aInds.splice(i,1),el.classList.remove('active'));
  document.getElementById('inds-h').value=aInds.join(',');
  document.getElementById('main-form').submit();
}}

// AI model selection
var selModelId=null,selModelKey=null,timerIv=null;
function selectModel(card){{
  if(card.classList.contains('exhausted'))return;
  document.querySelectorAll('.ai-model-card').forEach(c=>c.classList.remove('selected'));
  card.classList.add('selected');
  selModelId=card.dataset.model; selModelKey=card.dataset.key;
  document.getElementById('ai-sel-lbl').textContent='Model: '+card.dataset.label;
  document.getElementById('btn-ai').disabled=false;
  if(timerIv)clearInterval(timerIv);
}}

function runAnalysis(){{
  if(!selModelId)return;
  var btn=document.getElementById('btn-ai');
  var res=document.getElementById('ai-result');
  btn.disabled=true; btn.textContent='Analysing\u2026';
  res.className='ai-result show';
  res.innerHTML=`<div class="ai-loading"><div class="ai-spin"></div><div class="ai-load-txt">Fetching live data &amp; running AI analysis\u2026</div><div class="ai-load-sub">Pulling FRED macro data, Google Trends, fundamentals, 10+ technical indicators &mdash; building institutional-grade analysis (30\u201360s)</div></div>`;
 
  fetch('/api/ai-analysis',{{
    method:'POST', headers:{{'Content-Type':'application/json'}},
    body:JSON.stringify({{ticker:TICKER,period:PERIOD,model_id:selModelId}})
  }}).then(r=>r.json()).then(data=>{{
    btn.disabled=false; btn.textContent='Analyse '+TICKER;
    if(data.error){{res.innerHTML='<div class="ai-err">'+esc(data.error)+'</div>';return;}}
    renderAIResult(data);
  }}).catch(err=>{{
    btn.disabled=false; btn.textContent='Analyse '+TICKER;
    res.innerHTML='<div class="ai-err">Network error: '+esc(String(err))+'</div>';
  }});
}}

function esc(s){{return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');}}

function renderAIResult(data){{
  var r=data.analysis;
  var m=MODELS.find(x=>x.id===data.model_id)||{{}};
  var verdict=(r.verdict||'HOLD').toUpperCase();
  var pt=r.price_targets||{{}};
  var dataTags=data.data_sources||[];
  var tagsHtml=dataTags.length?'<div class="ai-data-tags">'+dataTags.map(t=>'<span class="ai-data-tag">'+esc(t)+'</span>').join('')+'</div>':'';
  var secs=[
    {{lbl:'Chart Pattern Analysis',key:'chart_pattern_analysis'}},
    {{lbl:'Technical Analysis',key:'technical_analysis'}},
    {{lbl:'Fundamental Analysis',key:'fundamental_analysis'}},
    {{lbl:'Macro & Alternative Data',key:'macro_and_altdata'}},
    {{lbl:'Risk Factors',key:'risk_factors'}},
    {{lbl:"Trader's Action Plan",key:'action_plan'}},
  ];
  var secHtml=secs.map(s=>'<div class="ai-sec"><div class="ai-sec-hdr">'+s.lbl+'</div><div class="ai-sec-body">'+esc(r[s.key]||'No data.')+'</div></div>').join('');
  document.getElementById('ai-result').innerHTML=
    '<div class="ai-verdict-bar">'+
      '<div class="ai-badge v-'+verdict+'">'+verdict+'</div>'+
      '<div class="ai-vmeta">'+
        '<div class="ai-summary">'+esc(r.summary||'')+'</div>'+
        '<div class="ai-meta-row">'+
          '<span class="ai-mi"><strong>Confidence&nbsp;</strong>'+esc(r.confidence||'Medium')+'</span>'+
          '<span class="ai-mi"><strong>Horizon&nbsp;</strong>'+esc(r.time_horizon||'Mid')+'-term</span>'+
        '</div>'+
      '</div>'+
      '<span class="ai-model-tag"><span style="display:inline-block;width:6px;height:6px;border-radius:50%;background:'+(m.color||'#fff')+';margin-right:4px"></span>'+esc(m.label||data.model_id)+'</span>'+
    '</div>'+
    tagsHtml+
    '<div class="ai-pts">'+
      '<div class="ai-pt"><div class="ai-pt-lbl">Entry</div><div class="ai-pt-val pt-e">'+fn(pt.entry)+'</div></div>'+
      '<div class="ai-pt"><div class="ai-pt-lbl">Stop Loss</div><div class="ai-pt-val pt-sl">'+fn(pt.stop_loss)+'</div></div>'+
      '<div class="ai-pt"><div class="ai-pt-lbl">Target 1</div><div class="ai-pt-val pt-t1">'+fn(pt.target_1)+'</div></div>'+
      '<div class="ai-pt"><div class="ai-pt-lbl">Target 2</div><div class="ai-pt-val pt-t2">'+fn(pt.target_2)+'</div></div>'+
    '</div>'+
    '<div class="ai-secs">'+secHtml+'</div>';
}}

function fn(v,d){{d=d||2;return(v==null||v===undefined)?'N/A':Number(v).toFixed(d);}}

// Prediction Markets
async function searchPredMarkets(){{
  var q=(document.getElementById('pred-query').value||'').trim();
  if(!q)return;
  var btn=document.getElementById('pred-btn');
  var status=document.getElementById('pred-status');
  btn.disabled=true; btn.textContent='Searching\u2026';
  status.textContent='Fetching Manifold & PredScope\u2026';
  document.getElementById('pred-chart-wrap').style.display='none';
  document.getElementById('pred-table-wrap').style.display='none';
  document.getElementById('pred-empty').style.display='none';

  try{{
    var r=await fetch('/api/prediction-markets?q='+encodeURIComponent(q));
    var data=await r.json();
    if(data.error){{status.textContent='Error: '+data.error;return;}}
    var results=data.results||[];
    status.textContent='Found '+results.length+' market(s) across '+data.sources+' source(s)';
    if(!results.length){{document.getElementById('pred-empty').style.display='block';return;}}
    renderPredChart(results);
    renderPredTable(results);
  }}catch(e){{
    status.textContent='Network error: '+String(e);
  }}finally{{
    btn.disabled=false; btn.textContent='Search Markets';
  }}
}}

function renderPredChart(results){{
  var isMobile=window.innerWidth<600;
  var maxLen=isMobile?22:42;
  var top=results.slice(0,isMobile?8:12);
  var labels=top.map(function(r){{
    var t=r.title.length>maxLen?r.title.slice(0,maxLen)+'\u2026':r.title;
    return t;
  }});
  var probs=top.map(function(r){{return r.probability;}});
  var colors=top.map(function(r){{return r.platform==='Manifold'?'#000000':'#555555';}});

  var trace={{
    type:'bar', orientation:'h',
    x:probs, y:labels,
    marker:{{color:colors}},
    text:probs.map(function(p){{return p.toFixed(1)+'%';}}),
    textposition:isMobile?'inside':'auto',
    insidetextanchor:'middle',
    textfont:{{color:isMobile?'#fff':'#000',size:isMobile?9:11}},
    cliponaxis:false,
    hovertemplate:'%{{y}}<br>Probability: %{{x:.1f}}%<extra></extra>',
  }};
  var lMargin=isMobile?120:280;
  var rMargin=isMobile?20:60;
  var layout={{
    paper_bgcolor:'#ffffff', plot_bgcolor:'#ffffff',
    font:{{color:'#000000',size:isMobile?9:11,family:'DM Sans,sans-serif'}},
    margin:{{l:lMargin,r:rMargin,t:24,b:36}},
    xaxis:{{title:'',range:[0,100],gridcolor:'#e5e5e5',tickcolor:'#888',color:'#555',linecolor:'#000',ticksuffix:'%'}},
    yaxis:{{automargin:false,tickcolor:'#888',color:'#555',linecolor:'#000',tickfont:{{size:isMobile?8:11}}}},
    bargap:0.3,
  }};
  Plotly.newPlot('pred-chart',[trace],layout,{{responsive:true,displayModeBar:false}});
  document.getElementById('pred-chart-wrap').style.display='block';
}}

function renderPredTable(results){{
  var tbody=document.getElementById('pred-tbody');
  tbody.innerHTML=results.map(function(r,i){{
    var pct=r.probability.toFixed(1)+'%';
    var vol=r.volume!=null?'$'+Number(r.volume).toLocaleString(undefined,{{maximumFractionDigits:0}}):'—';
    var link=r.url?'<a href="'+r.url+'" target="_blank" class="news-card-read" style="display:inline;border:none;padding:0;background:none;font-size:.8rem;font-weight:500;text-transform:none;letter-spacing:0;white-space:normal;word-break:break-word">'+esc(r.title)+'</a>':'<span style="white-space:normal;word-break:break-word">'+esc(r.title)+'</span>';
    var platformBadge='<span class="news-card-src" style="white-space:nowrap">'+esc(r.platform)+'</span>';
    return '<tr style="border-bottom:1px solid #e5e5e5'+(i%2===0?';background:#f8f7f4':';background:#fff')+'">'+
      '<td style="padding:7px 8px;width:90px;vertical-align:top">'+platformBadge+'</td>'+
      '<td style="padding:7px 8px;color:#000;font-size:.8rem;line-height:1.4;vertical-align:top">'+link+'</td>'+
      '<td style="padding:7px 8px;text-align:right;font-family:monospace;font-size:.8rem;white-space:nowrap;width:54px;vertical-align:top">'+pct+'</td>'+
      '<td style="padding:7px 8px;color:#555;font-size:.78rem;width:56px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;vertical-align:top">'+esc(r.outcome_label)+'</td>'+
      '<td style="padding:7px 8px;text-align:right;font-family:monospace;font-size:.76rem;color:#888;white-space:nowrap;width:70px;vertical-align:top">'+vol+'</td>'+
    '</tr>';
  }}).join('');
  document.getElementById('pred-table-wrap').style.display='block';
}}

// Sector news
function selectAndFetch(id){{
  document.getElementById('sector-sel').value=id;
  fetchSectorNews();
}}

async function fetchSectorNews(){{
  var sector=document.getElementById('sector-sel').value;
  if(!sector){{document.getElementById('sector-sel').focus();return;}}
  var btn=document.getElementById('fetchSectorBtn');
  btn.disabled=true;
  btn.innerHTML='<span style="display:inline-block;width:11px;height:11px;border:2px solid rgba(0,0,0,.25);border-top-color:#000;border-radius:50%;animation:spin .6s linear infinite;vertical-align:middle;margin-right:6px"></span>Fetching';
  document.getElementById('sector-output').innerHTML=`
    <div class="sector-state">
      <div class="sector-spinner"></div>
      <div class="sector-state-title">Scanning Sources</div>
      <div class="sector-state-sub">Pulling live data from Reuters, CNBC, WSJ, Yahoo Finance, MarketWatch, Financial Times, Benzinga &amp; Seeking Alpha.</div>
    </div>`;
  var satDiv=document.getElementById('sector-satellite');
  satDiv.style.display='none';
  satDiv.innerHTML='';
  Object.keys(satMaps).forEach(k=>{{try{{satMaps[k].map.remove();}}catch(e){{}}delete satMaps[k];}});
  try{{
    var resp=await fetch('/api/news?sector='+encodeURIComponent(sector));
    if(!resp.ok)throw new Error('HTTP '+resp.status);
    var data=await resp.json();
    sectorArticles=data.articles||[];
    renderSectorNews(sectorArticles,data.sector_label,data.elapsed_seconds);
    loadSatelliteTargets(sector);
  }}catch(e){{
    document.getElementById('sector-output').innerHTML=`
      <div class="sector-state">
        <div class="sector-state-title">Request Failed</div>
        <div class="sector-state-sub">${{esc(e.message)}}. Please try again.</div>
      </div>`;
  }}finally{{
    btn.disabled=false;
    btn.innerHTML='Analyse &#8594;';
  }}
}}

var sectorArticles = [];
function renderSectorNews(articles,label,elapsed){{
  var sources=[...new Set(articles.map(a=>a.source))].sort();
  var header=`
    <div class="sector-res-header">
      <div>
        <div class="sector-res-title">Latest: <em>${{esc(label||'')}}</em></div>
      </div>
      <div class="sector-res-meta">
        <span class="res-count-badge">${{articles.length}} Articles</span>
        ${{elapsed?`<span class="res-time-badge">${{elapsed}}s</span>`:''}}
      </div>
    </div>`;
  var filters=`
    <div class="filter-row">
      <span class="filter-label">Filter</span>
      <button class="pill active" onclick="filterSector('all',this)">All</button>
      ${{sources.map(s=>`<button class="pill" onclick="filterSector(${{JSON.stringify(s)}},this)">${{esc(s)}}</button>`).join('')}}
    </div>`;
  if(!articles.length){{
    document.getElementById('sector-output').innerHTML=header+filters+`
      <div class="sector-state">
        <div class="sector-state-title">No Articles Found</div>
        <div class="sector-state-sub">No matching articles. Try a different sector or refresh.</div>
      </div>`;
    return;
  }}
  var cards=articles.map((a,i)=>{{
    var src=esc(a.source||'');
    var title=esc(a.title||'');
    var url=(a.url||'#').replace(/"/g,'%22');
    var date=esc(a.published||'Date unavailable');
    var idx=String(i+1).padStart(2,'0');
    var delay=Math.min(i*0.028,.65);
    return `<div class="news-card" data-source="${{src}}" style="animation-delay:${{delay}}s">
      <div class="news-card-top">
        <span class="news-card-src">${{src}}</span>
        <span class="news-card-num">${{idx}}</span>
      </div>
      <div class="news-card-title"><a href="${{url}}" target="_blank" rel="noopener noreferrer">${{title}}</a></div>
      <div class="news-card-footer">
        <span class="news-card-date">${{date}}</span>
        <a class="news-card-read" href="${{url}}" target="_blank" rel="noopener noreferrer">Read &rsaquo;</a>
      </div>
    </div>`;
  }}).join('');
  document.getElementById('sector-output').innerHTML=header+filters+`<div class="news-grid-sec">${{cards}}</div>`;
}}

function filterSector(source,btn){{
  document.querySelectorAll('#sector-output .pill').forEach(p=>p.classList.remove('active'));
  btn.classList.add('active');
  document.querySelectorAll('.news-card').forEach(c=>{{
    c.style.display=(source==='all'||c.dataset.source===source)?'':'none';
  }});
}}

document.getElementById('sector-sel').addEventListener('change',function(){{
  if(this.value)fetchSectorNews();
}});

// YouTube live news
var nframe=document.getElementById('nframe'),nload=document.getElementById('nload'),
    nbadge=document.getElementById('nbadge'),curHandle=null;

function nSetLoad(m){{nframe.style.display='none';nload.innerHTML='<div class="news-spinner"></div><span>'+m+'</span>';nload.style.display='flex';nbadge.style.display='none';}}
function nSetErr(m){{nframe.style.display='none';nload.innerHTML='<span>'+m+'</span>';nload.style.display='flex';nbadge.className='nsb error';nbadge.textContent='Unavailable';nbadge.style.display='inline-flex';}}

function loadCh(h){{
  if(curHandle===h)return;
  curHandle=h; nSetLoad('Loading stream\u2026'); nframe.src='about:blank';
  fetch('/api/live-id?handle='+encodeURIComponent(h))
    .then(r=>{{if(!r.ok)throw new Error('HTTP '+r.status);return r.json();}})
    .then(d=>{{
      if(h!==curHandle)return;
      if(d.error||!d.video_id){{nSetErr('Stream unavailable.');return;}}
      nframe.src='https://www.youtube.com/embed/'+d.video_id+'?autoplay=0&rel=0&modestbranding=1';
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

loadCh('{fh}');

// Satellite imagery
var satMaps = {{}};
function makeSatLayers() {{
  return {{
    esri: L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{{z}}/{{y}}/{{x}}',{{maxZoom:19}}),
    clarity: L.tileLayer('https://clarity.maptiles.arcgis.com/arcgis/rest/services/World_Imagery/MapServer/tile/{{z}}/{{y}}/{{x}}',{{maxZoom:21}}),
    osm: L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png',{{maxZoom:19}}),
    toner: L.tileLayer('https://tiles.stadiamaps.com/tiles/stamen_toner/{{z}}/{{x}}/{{y}}.png',{{maxZoom:18}}),
  }};
}}

function initSatMap(id, lat, lon) {{
  if (satMaps[id]) return;
  const el = document.getElementById(id);
  if (!el) return;
  const map = L.map(el, {{
    center:[lat,lon], zoom:16, zoomControl:true, attributionControl:false,
    dragging:true, scrollWheelZoom:false, doubleClickZoom:true,
  }});
  const layers = makeSatLayers();
  layers.esri.addTo(map);
  satMaps[id] = {{map, layers, current:'esri'}};
  setTimeout(()=>map.invalidateSize(),80);
}}

function switchSatLayer(mapId, key) {{
  const reg = satMaps[mapId];
  if (!reg || reg.current===key) return;
  reg.map.removeLayer(reg.layers[reg.current]);
  reg.layers[key].addTo(reg.map);
  reg.current = key;
  document.querySelectorAll(`[data-satmapid="${{mapId}}"] .sat-layer-btn`).forEach(b=>{{
    b.classList.toggle('active', b.dataset.layer===key);
  }});
}}

async function loadSatelliteTargets(sectorId) {{
  const satDiv = document.getElementById('sector-satellite');
  satDiv.style.display = 'block';
  satDiv.innerHTML = `
    <div class="sat-section-divider">
      <div class="sat-section-divider-line"></div>
      <div class="sat-label"><span class="sat-dot"></span>Satellite Imagery</div>
      <div class="sat-section-divider-line"></div>
    </div>
    <div class="sat-loading-state"><div class="sat-spinner"></div><span style="font-size:.78rem;color:#555">Loading satellite targets&hellip;</span></div>`;
  try {{
    const resp = await fetch('/api/satellite?sector='+encodeURIComponent(sectorId));
    if (!resp.ok) throw new Error('HTTP '+resp.status);
    const data = await resp.json();
    renderSatTargets(data.targets, data.sector);
  }} catch(e) {{
    satDiv.innerHTML += `<div style="color:#c00;font-size:.8rem;padding:12px 0">Satellite data unavailable: ${{esc(e.message)}}</div>`;
  }}
}}

function renderSatTargets(targets, sectorId) {{
  const satDiv = document.getElementById('sector-satellite');
  const cards = targets.map((t,i) => {{
    const mid = `sat-${{i}}`;
    const delay = Math.min(i*0.025, 0.6);
    return `
      <div class="sat-card" data-satmapid="${{mid}}" style="animation-delay:${{delay}}s">
        <div class="sat-map-wrap">
          <div id="${{mid}}" class="sat-map-leaf"></div>
          <div class="sat-map-crosshair"></div>
          <div class="sat-layer-btns">
            <button class="sat-layer-btn active" data-layer="esri" onclick="switchSatLayer('${{mid}}','esri')">SAT</button>
            <button class="sat-layer-btn" data-layer="clarity" onclick="switchSatLayer('${{mid}}','clarity')">HD</button>
            <button class="sat-layer-btn" data-layer="osm" onclick="switchSatLayer('${{mid}}','osm')">MAP</button>
            <button class="sat-layer-btn" data-layer="toner" onclick="switchSatLayer('${{mid}}','toner')">B&amp;W</button>
          </div>
        </div>
        <div class="sat-body">
          <div class="sat-name">${{esc(t.name)}}</div>
          ${{t.tag ? `<div class="sat-tag">${{esc(t.tag)}}</div>` : ''}}
          <div class="sat-coords">LAT ${{t.lat.toFixed(4)}} &nbsp;/&nbsp; LON ${{t.lon.toFixed(4)}}</div>
          <div class="sat-sources">
            <span class="sat-src-badge">ESRI WORLD</span>
            <span class="sat-src-badge">SENTINEL-2</span>
            <span class="sat-src-badge">OSM</span>
          </div>
        </div>
      </div>`;
  }}).join('');
  satDiv.innerHTML = `
    <div class="sat-section-divider">
      <div class="sat-section-divider-line"></div>
      <div class="sat-label"><span class="sat-dot"></span>Satellite <span class="sat-count-badge" style="margin-left:8px">${{targets.length}} Targets</span></div>
      <div class="sat-section-divider-line"></div>
    </div>
    <div class="sat-grid">${{cards}}</div>`;
  requestAnimationFrame(()=>{{
    targets.forEach((t,i)=>initSatMap(`sat-${{i}}`, t.lat, t.lon));
  }});
}}

// Live satellite viewer
var _satRunning = false;
var _satTokenInterval = null;

function toggleSat() {{
  var btn = document.getElementById('sat-toggle-btn');
  if (!_satRunning) {{
    _satRunning = true;
    btn.textContent = '⏹ Stop';
    btn.style.borderColor = 'rgba(0,200,100,.5)';
    btn.style.background = 'rgba(0,200,100,.08)';
    btn.style.color = '#008844';
    _satStartViewer();
  }} else {{
    _satRunning = false;
    btn.innerHTML = '&#9654; Start';
    btn.style.borderColor = 'rgba(255,100,100,.5)';
    btn.style.background = 'rgba(255,100,100,.08)';
    btn.style.color = '#cc3333';
    _satStopViewer();
  }}
}}

function _satStartViewer() {{
  var today = new Date();
  var prior = new Date(today);
  prior.setDate(prior.getDate() - 30);
  var fmt = function(d){{ return d.toISOString().split('T')[0]; }};
  document.getElementById('satDateTo').value   = fmt(today);
  document.getElementById('satDateFrom').value = fmt(prior);
  function waitForLeaflet(cb) {{
    if (typeof L !== 'undefined') {{ cb(); return; }}
    var t = setInterval(function() {{
      if (typeof L !== 'undefined') {{ clearInterval(t); cb(); }}
    }}, 80);
  }}
  waitForLeaflet(function() {{ _satInitMap(); }});
  _satUpdateToken();
  _satTokenInterval = setInterval(_satUpdateToken, 30000);
}}

function _satStopViewer() {{
  clearInterval(_satTokenInterval);
  _satTokenInterval = null;
  var badge = document.getElementById('satTokenBadge');
  if (badge) badge.textContent = 'TOKEN —';
  _satLog('Satellite viewer stopped.', 'info');
}}

var _satMap = null, _satLayer = null, _satCurrentLayer = 'TRUE-COLOR';

function _satInitMap() {{
  _satMap = L.map('satMap', {{ center: [20, 77], zoom: 5, zoomControl: true, attributionControl: false }});
  L.tileLayer('https://{{s}}.basemaps.cartocdn.com/light_all/{{z}}/{{x}}/{{y}}{{r}}.png', {{ maxZoom: 19, subdomains: 'abcd' }}).addTo(_satMap);
}}

async function _satUpdateToken() {{
  try {{
    var res = await fetch('/sentinel/token-status');
    var d = await res.json();
    var sec = d.remaining_seconds;
    if (sec == null) return;
    var m = String(Math.floor(sec/60)).padStart(2,'0');
    var s = String(sec%60).padStart(2,'0');
    document.getElementById('satTokenBadge').textContent = 'TOKEN ' + m + ':' + s;
    var dot = document.getElementById('satStatusDot');
    if (sec < 120) {{ dot.style.background='#dc2626'; }}
    else if (sec < 300) {{ dot.style.background='#f59e0b'; }}
    else {{ dot.style.background='#22c55e'; }}
  }} catch(e) {{}}
}}

function satSelectLayer(btn) {{
  document.querySelectorAll('.sat-vlayer-btn').forEach(function(b){{ b.classList.remove('active'); }});
  btn.classList.add('active');
  _satCurrentLayer = btn.dataset.layer;
  _satLog('Layer: ' + _satCurrentLayer);
}}

async function satApplyLayer() {{
  var dateFrom = document.getElementById('satDateFrom').value;
  var dateTo   = document.getElementById('satDateTo').value;
  var cloud    = document.getElementById('satCloudSlider').value;
  var btn      = document.getElementById('satLoadBtn');
  if (!dateFrom || !dateTo) {{ _satLog('Set date range first', 'err'); return; }}
  if (!_satMap) {{ _satLog('Map not ready yet', 'err'); return; }}
  btn.disabled = true;
  btn.textContent = '&#9632; LOADING…';
  document.getElementById('satStatusText').textContent = 'Fetching satellite data…';
  _satLog('Requesting ' + _satCurrentLayer + ' imagery…');
  try {{
    if (_satLayer) {{ _satMap.removeLayer(_satLayer); _satLayer = null; }}
    var proxyUrl = '/sentinel/proxy-tile?layer=' + _satCurrentLayer +
      '&dateFrom=' + dateFrom + '&dateTo=' + dateTo + '&cloud=' + cloud +
      '&z={{z}}&x={{x}}&y={{y}}';
    _satLayer = L.tileLayer(proxyUrl, {{ maxZoom: 18, opacity: 0.92, tileSize: 256, attribution: '\u00a9 Copernicus/ESA' }});
    _satLayer.addTo(_satMap);
    _satLog(_satCurrentLayer + ' layer loaded', 'ok');
    document.getElementById('satStatusText').textContent = 'Showing: ' + _satCurrentLayer + ' — Sentinel-2 L2A';
  }} catch(err) {{
    _satLog('Error: ' + err.message, 'err');
    document.getElementById('satStatusText').textContent = 'Error loading layer';
  }} finally {{
    btn.disabled = false;
    btn.textContent = '■ LOAD SATELLITE DATA';
  }}
}}

var _satSearchTimer;
document.getElementById('satSearchInput').addEventListener('input', function() {{
  clearTimeout(_satSearchTimer);
  var q = this.value.trim();
  if (q.length < 3) {{ _satHideResults(); return; }}
  _satSearchTimer = setTimeout(function(){{ _satGeocode(q); }}, 400);
}});

document.getElementById('satSearchInput').addEventListener('keydown', function(e) {{
  if (e.key === 'Enter') {{ clearTimeout(_satSearchTimer); satDoSearch(); }}
  if (e.key === 'Escape') _satHideResults();
}});

function satDoSearch() {{
  var q = document.getElementById('satSearchInput').value.trim();
  if (!q) return;
  _satGeocode(q);
}}

async function _satGeocode(q) {{
  try {{
    var res = await fetch('/sentinel/geocode?q=' + encodeURIComponent(q));
    var data = await res.json();
    var container = document.getElementById('satSearchResults');
    container.innerHTML = '';
    container.style.display = 'block';
    if (!data.results || data.results.length === 0) {{
      container.innerHTML = '<div class="sat-search-result-item" style="color:#999">No results</div>';
      return;
    }}
    data.results.slice(0,5).forEach(function(r) {{
      var el = document.createElement('div');
      el.className = 'sat-search-result-item';
      el.textContent = r.display_name;
      el.title = r.display_name;
      el.onclick = function() {{
        if (_satMap) _satMap.flyTo([parseFloat(r.lat), parseFloat(r.lon)], 12, {{duration:1.5}});
        document.getElementById('satSearchInput').value = r.display_name.split(',')[0];
        _satHideResults();
        _satLog('Navigated to: ' + r.display_name.split(',')[0]);
      }};
      container.appendChild(el);
    }});
  }} catch(err) {{
    _satLog('Geocode error: ' + err.message, 'err');
  }}
}}

function _satHideResults() {{
  document.getElementById('satSearchResults').style.display = 'none';
}}

document.addEventListener('click', function(e) {{
  if (!e.target.closest('.sat-search-wrap')) _satHideResults();
}});

function _satLog(msg, type) {{
  type = type || 'info';
  var area = document.getElementById('satLog');
  var el = document.createElement('div');
  el.className = 'sat-log-entry' + (type !== 'info' ? ' ' + type : '');
  var icons = {{info:'▸', ok:'✓', err:'✕'}};
  el.textContent = (icons[type]||'▸') + ' ' + msg;
  area.appendChild(el);
  area.scrollTop = area.scrollHeight;
}}

// GBM Simulation
window.runGBM = function(){{
  var ticker   = (document.getElementById('gbm-ticker').value||'AAPL').trim().toUpperCase();
  var n_years  = parseInt(document.getElementById('gbm-years').value,10);
  var n_scen   = parseInt(document.getElementById('gbm-scenarios').value,10);
  var btn      = document.getElementById('gbm-btn');
  var status   = document.getElementById('gbm-status');
  btn.disabled = true;
  status.textContent = 'Running simulation for ' + ticker + '…';
  fetch('/api/gbm', {{
    method:'POST',
    headers:{{'Content-Type':'application/json'}},
    body: JSON.stringify({{ticker:ticker, n_years:n_years, n_scenarios:n_scen}})
  }})
  .then(function(r){{return r.json();}})
  .then(function(d){{
    if(d.error){{ status.textContent='Error: '+d.error; btn.disabled=false; return; }}
    var chartEl = document.getElementById('gbm-chart');
    var histEl  = document.getElementById('gbm-hist');
    var isMobile = window.innerWidth < 600;
    chartEl.style.height = isMobile ? '260px' : '380px';
    chartEl.style.marginTop = '8px';
    histEl.style.height  = isMobile ? '160px' : '220px';
    histEl.style.marginTop = '8px';
    status.style.minHeight = '18px';
    status.style.marginBottom = '6px';
    renderGBM(d);
    btn.disabled=false;
    status.textContent='✓ ' + d.n_scenarios + ' paths · μ=' + (d.mu*100).toFixed(2) + '% · σ=' + (d.sigma*100).toFixed(2) + '%  (calibrated on 2y history)';
  }})
  .catch(function(e){{ status.textContent='Request failed: '+e; btn.disabled=false; }});
}};

function renderGBM(d){{
  var now = new Date();
  var tDates = d.t_axis.map(function(frac){{
    var ms = now.getTime() + frac * 365.25 * 24 * 3600 * 1000;
    return new Date(ms).toISOString().slice(0,10);
  }});
  var LY = {{
    paper_bgcolor:'rgba(0,0,0,0)',
    plot_bgcolor:'rgba(0,0,0,0)',
    font:{{color:'#787b86', family:"'DM Sans',sans-serif", size:10}},
    margin:{{l:62, r:20, t:48, b:44}},
    xaxis:{{gridcolor:'rgba(42,46,57,0.6)', color:'#787b86', zeroline:false, showline:false, tickfont:{{size:9,color:'#787b86'}}, tickformat:'%b %Y', type:'date'}},
    yaxis:{{gridcolor:'rgba(42,46,57,0.6)', color:'#787b86', zeroline:false, showline:false, tickfont:{{size:9,color:'#787b86'}}}},
    hovermode:'x unified',
    hoverlabel:{{bgcolor:'rgba(255,255,255,0.97)',bordercolor:'rgba(120,123,134,0.3)', font:{{color:'#000',size:11}}}},
    legend:{{orientation:'h', y:1.07, x:0, font:{{size:9,color:'#787b86'}}, bgcolor:'rgba(0,0,0,0)', borderwidth:0}}
  }};
  var t = tDates;
  var n = d.paths.length;
  function colAtPct(pctVal){{
    return d.t_axis.map(function(_,ti){{
      var vals = d.paths.map(function(p){{return p[ti];}}).sort(function(a,b){{return a-b;}});
      return vals[Math.min(Math.floor(pctVal/100*vals.length), vals.length-1)];
    }});
  }}
  var p5  = colAtPct(5);
  var p25 = colAtPct(25);
  var p50 = colAtPct(50);
  var p75 = colAtPct(75);
  var p95 = colAtPct(95);
  var traces = [];
  for(var i=0;i<n;i++){{
    traces.push({{x:t, y:d.paths[i], mode:'lines', line:{{color:'rgba(100,149,237,0.18)', width:0.8}}, showlegend:false, hoverinfo:'skip'}});
  }}
  traces.push({{x:t, y:p95, mode:'lines', line:{{color:'rgba(0,0,0,0)', width:0}}, showlegend:false, hoverinfo:'skip'}});
  traces.push({{x:t, y:p5, mode:'lines', line:{{color:'rgba(0,0,0,0)', width:0}}, fill:'tonexty', fillcolor:'rgba(41,98,255,0.08)', showlegend:false, hoverinfo:'skip', name:'90% cone'}});
  traces.push({{x:t, y:p75, mode:'lines', line:{{color:'rgba(0,0,0,0)', width:0}}, showlegend:false, hoverinfo:'skip'}});
  traces.push({{x:t, y:p25, mode:'lines', line:{{color:'rgba(0,0,0,0)', width:0}}, fill:'tonexty', fillcolor:'rgba(41,98,255,0.20)', showlegend:true, name:'50% band (IQR)', hoverinfo:'skip'}});
  traces.push({{x:t, y:p5, mode:'lines', name:'P5  (bear)', line:{{color:'#ef5350', width:1.2, dash:'dot'}}, hovertemplate:'P5 <b>%{{y:.2f}}</b><extra></extra>'}});
  traces.push({{x:t, y:p95, mode:'lines', name:'P95 (bull)', line:{{color:'#26a69a', width:1.2, dash:'dot'}}, hovertemplate:'P95 <b>%{{y:.2f}}</b><extra></extra>'}});
  traces.push({{x:t, y:p50, mode:'lines', name:'Median (P50)', line:{{color:'#f9a825', width:2.5}}, hovertemplate:'Median <b>%{{y:.2f}}</b><extra></extra>'}});
  traces.push({{x:[t[0],t[t.length-1]], y:[d.s_0,d.s_0], mode:'lines', name:'Entry ' + d.s_0.toFixed(2), line:{{color:'#787b86', width:1.5, dash:'dash'}}, hoverinfo:'skip'}});
  var currency = (d.ticker.endsWith('.NS')||d.ticker.endsWith('.BO')) ? 'INR' : 'USD';
  Plotly.react('gbm-chart', traces, Object.assign({{}}, LY, {{
    title:{{text:'<b style="color:#d1d4dc">' + d.ticker + '</b><span style="color:#787b86">  Monte Carlo GBM · ' + d.n_years + 'y horizon · ' + d.n_scenarios + ' paths</span>', font:{{size:11}}, x:0.01, xanchor:'left'}},
    yaxis: Object.assign({{}}, LY.yaxis, {{title:{{text:currency, font:{{size:10,color:'#787b86'}}, standoff:8}}}}),
    xaxis: Object.assign({{}}, LY.xaxis, {{title:{{text:'Date', font:{{size:10,color:'#787b86'}}, standoff:8}}}})
  }}), {{responsive:true}});
  var terminal = d.terminal;
  var loss = terminal.filter(function(v){{return v <  d.s_0;}});
  var gain = terminal.filter(function(v){{return v >= d.s_0;}});
  var allMin = Math.min.apply(null,terminal);
  var allMax = Math.max.apply(null,terminal);
  var nBins  = 35;
  var bSize  = (allMax - allMin) / nBins;
  var histTraces = [
    {{x: loss, type:'histogram', xbins:{{start:allMin, end:d.s_0, size:bSize}}, marker:{{color:'rgba(239,83,80,0.75)', line:{{color:'rgba(239,83,80,0.4)', width:1}}}}, name:'Below entry', hovertemplate:'%{{x:.2f}}  Count: %{{y}}<extra>Loss</extra>'}},
    {{x: gain, type:'histogram', xbins:{{start:d.s_0, end:allMax+bSize, size:bSize}}, marker:{{color:'rgba(38,166,154,0.75)', line:{{color:'rgba(38,166,154,0.4)', width:1}}}}, name:'Above entry', hovertemplate:'%{{x:.2f}}  Count: %{{y}}<extra>Gain</extra>'}}
  ];
  Plotly.react('gbm-hist', histTraces, Object.assign({{}}, LY, {{
    barmode:'overlay',
    title:{{text:'<b style="color:#d1d4dc">Terminal Distribution</b><span style="color:#787b86">  (Year ' + d.n_years + ')</span>', font:{{size:11}}, x:0.01, xanchor:'left'}},
    xaxis: Object.assign({{}}, LY.xaxis, {{type:'linear', tickformat:'', title:{{text:currency + ' at expiry', font:{{size:10,color:'#787b86'}}, standoff:8}}}}),
    yaxis: Object.assign({{}}, LY.yaxis, {{title:{{text:'Count', font:{{size:10,color:'#787b86'}}, standoff:8}}}}),
    shapes:[{{type:'line', x0:d.s_0, x1:d.s_0, y0:0, y1:1, yref:'paper', line:{{color:'#787b86', width:1.5, dash:'dash'}}}}],
    annotations:[{{x:d.s_0, y:1.05, yref:'paper', xanchor:'center', text:'<b>Entry ' + d.s_0.toFixed(2) + '</b>', showarrow:false, font:{{size:9, color:'#787b86'}}}}]
  }}), {{responsive:true}});
  var p   = d.percentiles;
  var pct = function(v){{
    var chg = (v - d.s_0) / d.s_0 * 100;
    var col = chg >= 0 ? '#26a69a' : '#ef5350';
    return '<span style="color:'+col+';font-weight:600">' + (chg>=0?'+':'') + chg.toFixed(1) + '%</span>';
  }};
  var probGain = (gain.length / terminal.length * 100).toFixed(1);
  var el = document.getElementById('gbm-stats');
  el.innerHTML =
    '<span style="color:#787b86;font-size:.68rem;letter-spacing:.1em;text-transform:uppercase;font-weight:700">Calibration</span>' +
    '&ensp;μ<sub>ann</sub>&thinsp;<strong style="color:#f9a825">' + (d.mu*100).toFixed(2) + '%</strong>' +
    '&ensp;σ<sub>ann</sub>&thinsp;<strong style="color:#f9a825">' + (d.sigma*100).toFixed(2) + '%</strong>' +
    '&ensp;Entry&thinsp;<strong style="color:#131722">' + d.s_0.toFixed(2) + '</strong>' +
    '&ensp;P(gain)&thinsp;<strong style="color:#26a69a">' + probGain + '%</strong>' +
    '<br>' +
    '<span style="color:#787b86;font-size:.68rem;letter-spacing:.1em;text-transform:uppercase;font-weight:700">Terminal percentiles</span>' +
    '&ensp;<span style="color:#ef5350;font-weight:600">P5</span>&thinsp;<strong style="color:#131722">' + p.p5.toFixed(2) + '</strong>&thinsp;' + pct(p.p5) +
    '&ensp;<span style="color:#787b86;font-weight:600">P25</span>&thinsp;<strong style="color:#131722">' + p.p25.toFixed(2) + '</strong>&thinsp;' + pct(p.p25) +
    '&ensp;<span style="color:#f9a825;font-weight:600">P50</span>&thinsp;<strong style="color:#131722">' + p.p50.toFixed(2) + '</strong>&thinsp;' + pct(p.p50) +
    '&ensp;<span style="color:#787b86;font-weight:600">P75</span>&thinsp;<strong style="color:#131722">' + p.p75.toFixed(2) + '</strong>&thinsp;' + pct(p.p75) +
    '&ensp;<span style="color:#26a69a;font-weight:600">P95</span>&thinsp;<strong style="color:#131722">' + p.p95.toFixed(2) + '</strong>&thinsp;' + pct(p.p95);
  el.style.background    = '#ffffff';
  el.style.border        = '2px solid #131722';
  el.style.borderRadius  = '6px';
  el.style.color         = '#131722';
  el.style.display       = 'block';
}}

// AIS Vessel Tracker
var _aisRunning = false;
function toggleAIS() {{
  var btn = document.getElementById('ais-toggle-btn');
  var badge = document.getElementById('ais-vessel-badge');
  var iframe = document.getElementById('vessel-iframe');
  if (!_aisRunning) {{
    _aisRunning = true;
    btn.textContent = '⏹ Stop';
    btn.style.borderColor = 'rgba(0,200,100,.5)';
    btn.style.background = 'rgba(0,200,100,.08)';
    btn.style.color = '#008844';
    badge.textContent = 'Connecting…';
    iframe.contentWindow.postMessage('ais:start', '*');
  }} else {{
    _aisRunning = false;
    btn.innerHTML = '&#9654; Start';
    btn.style.borderColor = 'rgba(255,100,100,.5)';
    btn.style.background = 'rgba(255,100,100,.08)';
    btn.style.color = '#cc3333';
    badge.textContent = 'Stopped';
    iframe.contentWindow.postMessage('ais:stop', '*');
  }}
}}

// ADS-B Aircraft Tracker
var _adsbRunning = false;
var _adsbIframeReady = false;
var _adsbPendingCmd = null;
var _adsbIframe = document.getElementById('aircraft-iframe');

_adsbIframe.addEventListener('load', function() {{
  _adsbIframeReady = true;
  if (_adsbPendingCmd) {{
    _adsbIframe.contentWindow.postMessage(_adsbPendingCmd, '*');
    _adsbPendingCmd = null;
  }}
}});

window.addEventListener('message', function(e) {{
  if (e.data && e.data.type === 'adsb:count') {{
    var badge = document.getElementById('adsb-aircraft-badge');
    if (badge) badge.textContent = e.data.count + ' live';
  }}
}});

function _sendAdsbMsg(cmd) {{
  if (_adsbIframeReady) {{
    _adsbIframe.contentWindow.postMessage(cmd, '*');
  }} else {{
    _adsbPendingCmd = cmd;
  }}
}}

function toggleADSB() {{
  var btn = document.getElementById('adsb-toggle-btn');
  var badge = document.getElementById('adsb-aircraft-badge');
  if (!_adsbRunning) {{
    _adsbRunning = true;
    btn.textContent = '⏹ Stop';
    btn.style.borderColor = 'rgba(0,200,100,.5)';
    btn.style.background = 'rgba(0,200,100,.08)';
    btn.style.color = '#008844';
    badge.textContent = 'Connecting…';
    _sendAdsbMsg('adsb:start');
  }} else {{
    _adsbRunning = false;
    btn.innerHTML = '&#9654; Start';
    btn.style.borderColor = 'rgba(255,100,100,.5)';
    btn.style.background = 'rgba(255,100,100,.08)';
    btn.style.color = '#cc3333';
    badge.textContent = 'Stopped';
    _sendAdsbMsg('adsb:stop');
  }}
}}

// Initialize Alpaca feeds
fetchAlpacaStocks();
fetchAlpacaAccount();
setInterval(fetchAlpacaStocks, 15000);
setInterval(fetchAlpacaAccount, 60000);
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
    return render_page(ticker, period, chart_type, active, graph_html, error)
 
 
@app.route("/api/ai-analysis", methods=["POST"])
def api_ai_analysis():
    body     = request.get_json(force=True) or {}
    ticker   = (body.get("ticker","AAPL") or "AAPL").strip().upper()
    period   = body.get("period","6mo")
    model_id = (body.get("model_id") or "").strip()
    if not model_id:
        return jsonify({"error": "model_id required"}), 400
    model = next((m for m in AI_MODELS if m["id"] == model_id), None)
    if not model:
        return jsonify({"error": f"Unknown model: {model_id}"}), 400
 
    rl = rl_check(model["key"])
    if not rl["available"]:
        reset = rl_next_rpm_reset(model["key"])
        return jsonify({"error": f"Rate limit hit ({model['label']}): RPM {rl['rpm_used']}/{rl['rpm_max']}, RPD {rl['rpd_used']}/{rl['rpd_max']}. Resets in {reset}s."}), 429
 
    if period not in VALID_PERIODS: period = "6mo"
    df, err = fetch_yfinance_data(ticker, period)
    if err: return jsonify({"error": f"Data fetch failed: {err}"}), 502
    if df is None or df.empty: return jsonify({"error": f"No data for '{ticker}'."}), 404
 
    name = _get_name(ticker)
 
    # ── Fetch all alternative data concurrently ──
    macro_data    = {}
    trends_data   = {}
    fundamentals  = {}
    shipping_ctx  = {}
 
    def _fetch_macro():
        nonlocal macro_data
        try: macro_data = fetch_all_macro()
        except: pass
 
    def _fetch_trends():
        nonlocal trends_data
        try:
            kws = get_ticker_trend_keywords(ticker, name)
            trends_data = fetch_google_trends(kws, timeframe="today 3-m")
        except: pass
 
    def _fetch_fundamentals():
        nonlocal fundamentals
        try: fundamentals = _get_fundamentals(ticker)
        except: pass
 
    def _fetch_shipping():
        nonlocal shipping_ctx
        try: shipping_ctx = fetch_shipping_context()
        except: pass
 
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
        futs = [ex.submit(_fetch_macro), ex.submit(_fetch_trends),
                ex.submit(_fetch_fundamentals), ex.submit(_fetch_shipping)]
        concurrent.futures.wait(futs, timeout=18)
 
    # Track which data sources succeeded
    data_sources = []
    if macro_data:    data_sources.append(f"FRED Macro ({len(macro_data)} series)")
    if trends_data:   data_sources.append(f"Google Trends ({len(trends_data)} keywords)")
    if fundamentals:  data_sources.append("Yahoo Fundamentals")
    if shipping_ctx:  data_sources.append("AIS Shipping Context")
    data_sources += ["12 Technical Indicators", "30-Day OHLCV Chart", "Candlestick Pattern Analysis", "SPY Correlation"]
 
    try:
        payload  = build_analysis_payload(ticker, period, name, df,
                                          macro_data=macro_data,
                                          trends_data=trends_data,
                                          fundamentals=fundamentals,
                                          shipping_ctx=shipping_ctx)
        prompt   = build_prompt(payload)
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
 
    return jsonify({
        "ticker": ticker, "period": period,
        "model_id": model_id, "analysis": analysis,
        "data_sources": data_sources,
    })
 
 

@app.route("/api/gbm", methods=["POST"])
def api_gbm():
    body       = request.get_json(force=True) or {}
    ticker     = (body.get("ticker", "AAPL") or "AAPL").strip().upper()
    n_years    = max(1, min(int(body.get("n_years", 2)), 10))
    n_scenarios = max(100, min(int(body.get("n_scenarios", 200)), 1000))
    try:
        result = run_gbm(ticker, n_years=n_years, n_scenarios=n_scenarios)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/prediction-markets")
def api_prediction_markets():
    q = (request.args.get("q") or "").strip()
    if not q:
        return jsonify({"error": "query required"}), 400

    results = []
    sources = 0

    # ── Manifold ──────────────────────────────────────────────────────────────
    try:
        r = requests.get(
            "https://api.manifold.markets/v0/search-markets",
            params={"term": q, "limit": 20, "filter": "open"},
            timeout=10,
            headers={"User-Agent": "Starfish/1.0"},
        )
        r.raise_for_status()
        for m in (r.json() or []):
            prob = m.get("probability")
            if prob is None:
                continue
            results.append({
                "platform":      "Manifold",
                "title":         m.get("question") or m.get("slug", ""),
                "market_id":     m.get("id", ""),
                "url":           m.get("url", ""),
                "probability":   round(float(prob) * 100, 2),
                "outcome_label": "YES",
                "volume":        m.get("volume"),
            })
        sources += 1
    except Exception as exc:
        print(f"[PredMarkets] Manifold error: {exc}")

    # ── PredScope (Polymarket-based) ──────────────────────────────────────────
    try:
        r2 = requests.get(
            "https://predscope.com/api/markets.json",
            timeout=10,
            headers={"User-Agent": "Starfish/1.0"},
        )
        r2.raise_for_status()
        ql = q.lower()
        for m in (r2.json() or []):
            title = m.get("title") or m.get("question") or ""
            if ql not in title.lower():
                continue
            outcomes = m.get("outcomes") or []
            if not outcomes:
                continue
            # Pick "Yes" outcome or highest probability outcome
            best = None
            for o in outcomes:
                ol = (o.get("title") or o.get("name") or "").lower()
                op = o.get("probability")
                if op is None:
                    continue
                if "yes" in ol:
                    best = o
                    break
            if best is None:
                best = max(outcomes, key=lambda o: o.get("probability", 0) if o.get("probability") is not None else 0)
            prob = best.get("probability")
            if prob is None:
                continue
            results.append({
                "platform":      "PredScope",
                "title":         title,
                "market_id":     m.get("slug") or m.get("id", ""),
                "url":           f"https://predscope.com/market/{m.get('slug','')}" if m.get("slug") else "",
                "probability":   round(float(prob) * 100, 2),
                "outcome_label": best.get("title") or best.get("name") or "YES",
                "volume":        m.get("volume") or m.get("liquidity"),
            })
        sources += 1
    except Exception as exc:
        print(f"[PredMarkets] PredScope error: {exc}")

    # ── Rank: exact title match first, then by distance from 50% ─────────────
    def _rank(r):
        exact = 1 if q.lower() in r["title"].lower() else 0
        deviation = abs(r["probability"] - 50)
        vol = float(r["volume"] or 0)
        return (exact, deviation, vol)

    results.sort(key=_rank, reverse=True)

    return jsonify({"results": results, "sources": sources, "query": q})


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
    elapsed  = round(time.time() - t0, 2)
    return jsonify({
        "sector": sector_id,
        "sector_label": SECTORS[sector_id]["label"],
        "count": len(articles),
        "elapsed_seconds": elapsed,
        "articles": articles,
    })
 
 
@app.route("/api/macro")
def api_macro():
    """Expose live FRED macro data as a standalone endpoint."""
    try:
        data = fetch_all_macro()
        bdi  = fetch_baltic_dry()
        return jsonify({"macro": data, "baltic_dry": bdi, "timestamp": datetime.utcnow().isoformat()})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
 
 
@app.route("/api/trends")
def api_trends():
    """Expose Google Trends data for a given query."""
    query = request.args.get("q", "").strip()
    if not query: return jsonify({"error": "q param required"}), 400
    data = fetch_google_trends([query], timeframe="today 3-m")
    return jsonify({"trends": data, "query": query})
 
 
@app.route("/api/satellite")
def api_satellite():
    """Return 30 satellite targets for a given sector id."""
    sector_id = request.args.get("sector", "").strip()
    if sector_id not in SECTOR_SATELLITE_TARGETS:
        return jsonify({"error": "Invalid sector", "targets": []}), 400
    return jsonify({
        "sector": sector_id,
        "targets": SECTOR_SATELLITE_TARGETS[sector_id],
    })


@app.route("/api/ais-key")
def api_ais_key():
    """Return AIS key status without exposing the key itself in the vessels HTML."""
    key = os.environ.get("AISSTREAM_API_KEY", "").strip().strip("\"'")
    if not key:
        return jsonify({"ok": False, "reason": "AISSTREAM_API_KEY env var not set"}), 503
    return jsonify({"ok": True, "key": key})


@app.route("/vessels")
def vessels():
    html = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Live Vessel Tracker</title>
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.css">
<script src="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.js"></script>
<style>
*{margin:0;padding:0;box-sizing:border-box}
html,body{height:100%;font-family:'DM Mono',monospace,sans-serif;background:#07090f;overflow:hidden}
#map{position:absolute;inset:38px 0 60px 0;background:#07090f}
.leaflet-container{background:#07090f}
.leaflet-control-zoom{border:1px solid rgba(255,255,255,.1)!important;background:#0d1117!important;border-radius:6px!important}
.leaflet-control-zoom a{background:#0d1117!important;color:#6b7fa3!important;border-color:rgba(255,255,255,.08)!important;width:26px!important;height:26px!important;line-height:26px!important}
.leaflet-control-zoom a:hover{color:#00c8ff!important;background:#151c2a!important}
.leaflet-control-attribution{background:rgba(7,9,15,.85)!important;color:#3a4a66!important;font-size:9px!important;border-radius:4px 0 0 0!important}
.leaflet-control-attribution a{color:#5a7099!important}
.leaflet-popup-content-wrapper{background:#0d1117;border:1px solid rgba(0,200,255,.2);border-radius:8px;color:#d4ddf0;box-shadow:0 8px 32px rgba(0,0,0,.7)}
.leaflet-popup-tip-container{display:none}
.leaflet-popup-content{margin:14px 16px;font-size:11px;line-height:1.8;font-family:'DM Mono',monospace,sans-serif}
.leaflet-popup-close-button{color:#6b7fa3!important;font-size:16px!important;top:6px!important;right:8px!important}
.popup-name{font-size:13px;font-weight:700;color:#00c8ff;letter-spacing:.04em;margin-bottom:8px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:200px}
.popup-row{display:flex;justify-content:space-between;gap:16px;border-bottom:1px solid rgba(255,255,255,.04);padding:2px 0}
.popup-key{color:#4a5a7a;text-transform:uppercase;font-size:9px;letter-spacing:.1em;align-self:center}
.popup-val{color:#a8b8d8;font-size:11px}
.popup-type-badge{display:inline-block;padding:1px 7px;border-radius:3px;font-size:9px;letter-spacing:.08em;text-transform:uppercase;font-weight:700}
#topbar{position:fixed;top:0;left:0;right:0;height:38px;z-index:1000;background:rgba(7,9,15,.96);border-bottom:1px solid rgba(255,255,255,.06);display:flex;align-items:center;padding:0 14px;gap:10px;backdrop-filter:blur(10px)}
#status-led{width:7px;height:7px;border-radius:50%;background:#ffaa33;flex-shrink:0;transition:background .3s}
#status-text{font-size:10px;letter-spacing:.06em;color:#6b7fa3;text-transform:uppercase}
#vessel-counter{font-size:10px;letter-spacing:.06em;color:#00c8ff;background:rgba(0,200,255,.07);border:1px solid rgba(0,200,255,.15);border-radius:20px;padding:2px 10px}
#filter-bar{margin-left:auto;display:flex;gap:6px}
.fbtn{font-size:9px;letter-spacing:.08em;text-transform:uppercase;padding:2px 9px;border-radius:20px;border:1px solid rgba(255,255,255,.1);background:transparent;color:#6b7fa3;cursor:pointer;transition:all .15s;font-family:inherit}
.fbtn:hover{border-color:#00c8ff;color:#00c8ff}
.fbtn.on{background:rgba(0,200,255,.1);border-color:#00c8ff;color:#00c8ff}
#limit-btn{font-size:9px;letter-spacing:.06em;text-transform:uppercase;padding:2px 10px;border-radius:20px;border:1px solid rgba(255,170,50,.35);background:rgba(255,170,50,.07);color:#ffaa33;cursor:pointer;font-family:inherit;transition:all .15s;white-space:nowrap;flex-shrink:0}
#limit-btn:hover{border-color:#ffaa33;background:rgba(255,170,50,.18);color:#ffc866}
#limit-btn:active{transform:scale(.95)}
#debugbar{position:fixed;bottom:0;left:0;right:0;height:60px;z-index:1000;background:rgba(7,9,15,.97);border-top:1px solid rgba(255,255,255,.06);padding:6px 14px;display:flex;flex-direction:column;gap:3px;overflow:hidden}
#debug-line1{font-size:9px;letter-spacing:.05em;color:#4a6a9a;font-family:'DM Mono',monospace}
#debug-line2{font-size:9px;letter-spacing:.04em;color:#3a5070;font-family:'DM Mono',monospace;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
@media(max-width:600px){
  #topbar{height:38px;padding:0 8px;gap:5px;overflow:hidden}
  #status-text{font-size:8px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:72px;flex-shrink:1}
  #vessel-counter{font-size:8px;padding:2px 6px;white-space:nowrap;flex-shrink:0}
  #filter-bar{gap:3px;overflow-x:auto;-webkit-overflow-scrolling:touch;flex-shrink:1;min-width:0;scrollbar-width:none}
  #filter-bar::-webkit-scrollbar{display:none}
  .fbtn{font-size:8px;padding:2px 6px;white-space:nowrap;flex-shrink:0}
  #limit-btn{font-size:8px;padding:2px 7px}
  #debugbar{height:44px;padding:4px 10px}
  #debug-line2{display:none}
}
</style>
</head>
<body>
<div id="topbar">
  <div id="status-led"></div>
  <span id="status-text"></span>
  <span id="vessel-counter">0 / 3,000</span>
  <button id="limit-btn" title="Increase vessel limit by 500">+500</button>
  <div id="filter-bar">
    <button class="fbtn on" data-type="all">All</button>
    <button class="fbtn" data-type="cargo">Cargo</button>
    <button class="fbtn" data-type="tanker">Tanker</button>
    <button class="fbtn" data-type="passenger">Passenger</button>
    <button class="fbtn" data-type="fishing">Fishing</button>
    <button class="fbtn" data-type="other">Other</button>
  </div>
</div>
<div id="map"></div>
<div id="debugbar">
  <div id="debug-line1"></div>
  <div id="debug-line2"></div>
</div>
<script>
var map = L.map('map', {center:[20,10], zoom:2, zoomControl:true, attributionControl:true});
L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
  attribution: '&copy; <a href="https://carto.com/">CARTO</a> &copy; <a href="https://openstreetmap.org/copyright">OSM</a>',
  subdomains: 'abcd', maxZoom: 19
}).addTo(map);
L.tileLayer('https://tiles.openseamap.org/seamark/{z}/{x}/{y}.png', {
  attribution: '&copy; <a href="https://openseamap.org">OpenSeaMap</a>',
  opacity: 0.55, maxZoom: 18
}).addTo(map);
function dbg(line1, line2) {
  document.getElementById('debug-line1').textContent = line1 || '';
  if (line2 !== undefined) document.getElementById('debug-line2').textContent = line2 || '';
}
var vessels    = {};
var typeCache  = {};
var activeFilter = 'all';
var vesselLimit  = 3000;
var msgCount = 0;
function classify(t) {
  t = parseInt(t) || 0;
  if (t >= 70 && t <= 79) return 'cargo';
  if (t >= 80 && t <= 89) return 'tanker';
  if (t >= 60 && t <= 69) return 'passenger';
  if (t >= 30 && t <= 39) return 'fishing';
  if (t >= 50 && t <= 59) return 'service';
  return 'other';
}
var TYPE_META = {
  cargo:     {color:'#00c8ff', label:'Cargo'},
  tanker:    {color:'#ff7733', label:'Tanker'},
  passenger: {color:'#44ff88', label:'Passenger'},
  fishing:   {color:'#ffdd22', label:'Fishing'},
  service:   {color:'#cc77ff', label:'Service'},
  other:     {color:'#6b7fa3', label:'Other'}
};
function makeMarkerHTML(color, cog) {
  var r = parseFloat(cog) || 0;
  return '<div style="width:0;height:0;position:relative;transform:rotate('+r+'deg);transform-origin:center center">' +
    '<svg xmlns="http://www.w3.org/2000/svg" width="14" height="20" viewBox="0 0 14 20" style="position:absolute;left:-7px;top:-10px">' +
    '<polygon points="7,0 13,18 7,13 1,18" fill="'+color+'" stroke="rgba(0,0,0,.6)" stroke-width="1.2" stroke-linejoin="round"/>' +
    '</svg></div>';
}
function makeIcon(color, cog) {
  return L.divIcon({html:makeMarkerHTML(color, cog), className:'', iconSize:[14,20], iconAnchor:[7,10]});
}
function buildPopup(d) {
  var meta = TYPE_META[d.cls] || TYPE_META.other;
  var badge = '<span class="popup-type-badge" style="background:'+meta.color+'22;color:'+meta.color+';border:1px solid '+meta.color+'44">'+meta.label+'</span>';
  var rows = [
    ['MMSI',   d.mmsi || '—'],
    ['Speed',  d.sog  ? parseFloat(d.sog).toFixed(1)+' kn' : '—'],
    ['Course', d.cog  ? parseFloat(d.cog).toFixed(0)+'°'  : '—'],
    ['Flag',   d.flag || '—'],
    ['Dest',   d.dest || '—'],
    ['ETA',    d.eta  || '—'],
    ['Length', d.length ? d.length+'m' : '—'],
  ];
  var html = '<div class="popup-name">'+(d.name||'Unknown')+'</div>' +
             '<div style="margin-bottom:6px">'+badge+'</div>';
  rows.forEach(function(r){ if(r[1]!=='—') html += '<div class="popup-row"><span class="popup-key">'+r[0]+'</span><span class="popup-val">'+r[1]+'</span></div>'; });
  return html;
}
function upsertVessel(d) {
  var mmsi = String(d.mmsi || '');
  if (!mmsi || mmsi === '0') return;
  var lat = parseFloat(d.lat), lon = parseFloat(d.lon);
  if (isNaN(lat) || isNaN(lon) || lat < -90 || lat > 90 || lon < -180 || lon > 180) return;
  if (!vessels[mmsi] && Object.keys(vessels).length >= vesselLimit) return;
  var cls  = classify(d.type || typeCache[mmsi]);
  d.cls = cls;
  var meta = TYPE_META[cls] || TYPE_META.other;
  var visible = (activeFilter === 'all' || activeFilter === cls ||
                 (activeFilter === 'other' && (cls==='other'||cls==='service')));
  if (vessels[mmsi]) {
    var v = vessels[mmsi];
    v.data = Object.assign(v.data, d);
    v.lastSeen = Date.now();
    v.marker.setLatLng([lat, lon]);
    v.marker.setIcon(makeIcon(meta.color, d.cog));
    if (v.marker.isPopupOpen()) v.marker.setPopupContent(buildPopup(v.data));
    if (!visible && v.shown) { map.removeLayer(v.marker); v.shown = false; }
    else if (visible && !v.shown) { map.addLayer(v.marker); v.shown = true; }
  } else {
    var marker = L.marker([lat, lon], {icon: makeIcon(meta.color, d.cog)});
    marker.bindPopup('', {maxWidth:260});
    marker.on('click', function(){ marker.setPopupContent(buildPopup(vessels[mmsi].data)); });
    if (visible) marker.addTo(map);
    vessels[mmsi] = {marker:marker, data:d, lastSeen:Date.now(), shown:visible};
  }
  updateCounter();
}
function fmtLimit(n) {
  return n >= 10000 ? (n/1000).toFixed(0)+'K' : n.toLocaleString();
}
function updateCounter() {
  var n = Object.keys(vessels).length;
  var atCap = n >= vesselLimit;
  var el = document.getElementById('vessel-counter');
  el.textContent = n.toLocaleString() + ' / ' + fmtLimit(vesselLimit);
  el.style.borderColor = atCap ? 'rgba(255,170,50,.5)' : 'rgba(0,200,255,.15)';
  el.style.color = atCap ? '#ffaa33' : '#00c8ff';
  el.style.background = atCap ? 'rgba(255,170,50,.07)' : 'rgba(0,200,255,.07)';
  var btn = document.getElementById('limit-btn');
  if (btn) btn.textContent = atCap ? ' +500' : '+500';
  try { var b=window.parent.document.getElementById('ais-vessel-badge'); if(b) b.textContent=n.toLocaleString()+' live'; } catch(e){}
}
document.getElementById('limit-btn').addEventListener('click', function() {
  vesselLimit += 500;
  this.title = 'Limit: ' + fmtLimit(vesselLimit) + ' · Click to add 500 more';
  updateCounter();
});
setInterval(function(){
  var cutoff = Date.now() - 1200000;
  Object.keys(vessels).forEach(function(mmsi){
    if (vessels[mmsi].lastSeen < cutoff) {
      map.removeLayer(vessels[mmsi].marker);
      delete vessels[mmsi];
      delete typeCache[mmsi];
    }
  });
  updateCounter();
}, 60000);
document.getElementById('filter-bar').addEventListener('click', function(e){
  var btn = e.target.closest('.fbtn'); if (!btn) return;
  activeFilter = btn.dataset.type;
  document.querySelectorAll('.fbtn').forEach(function(b){ b.classList.remove('on'); });
  btn.classList.add('on');
  Object.values(vessels).forEach(function(v){
    var cls = v.data.cls;
    var vis = (activeFilter==='all'||activeFilter===cls||(activeFilter==='other'&&(cls==='other'||cls==='service')));
    if (vis && !v.shown)  { map.addLayer(v.marker);    v.shown=true; }
    if (!vis && v.shown)  { map.removeLayer(v.marker); v.shown=false; }
  });
});
function setStatus(state, detail) {
  var led = document.getElementById('status-led');
  var txt = document.getElementById('status-text');
  var states = {
    init:      {bg:'#ffaa33', text:'Initialising…'},
    fetching:  {bg:'#ffaa33', text:'Fetching key…'},
    connecting:{bg:'#00c8ff', text:'Connecting to AISStream…'},
    connected: {bg:'#44ff88', text:'Live · AISStream'},
    error:     {bg:'#ff4444', text:'Error — Reconnecting…'},
    nokey:     {bg:'#ff4444', text:'No API Key Set'},
    closed:    {bg:'#ffaa33', text:'Reconnecting…'}
  };
  var s = states[state] || {bg:'#6b7fa3', text:state};
  led.style.background = s.bg;
  txt.textContent = s.text;
  if (detail) dbg(s.text, detail);
  else dbg(s.text);
}
var ws = null, reconnectDelay = 3000, reconnectTimer = null;
var _aisStopped = true;
function connect(apiKey) {
  setStatus('connecting', 'Opening wss://stream.aisstream.io/v0/stream');
  ws = new WebSocket('wss://stream.aisstream.io/v0/stream');
  ws.onopen = function() {
    setStatus('connected', 'Sending subscription…');
    reconnectDelay = 3000;
    var sub = {
      APIKey: apiKey,
      BoundingBoxes: [[[-90, -180], [90, 180]]],
      FilterMessageTypes: ['PositionReport', 'ShipStaticData']
    };
    ws.send(JSON.stringify(sub));
    dbg('Connected · Subscription sent · Waiting for vessels…', JSON.stringify(sub).slice(0,120));
  };
  ws.binaryType = 'blob';
  ws.onmessage = function(evt) {
    if (evt.data instanceof Blob) {
      var reader = new FileReader();
      reader.onload = function() { handleMsg(reader.result); };
      reader.readAsText(evt.data);
    } else {
      handleMsg(evt.data);
    }
  };
  function handleMsg(raw) {
    msgCount++;
    var msg;
    try { msg = JSON.parse(raw); } catch(e) { dbg('JSON parse error: '+e.message, raw.slice(0,120)); return; }
    if (msgCount <= 5) dbg('MSG #'+msgCount+': '+msg.MessageType, raw.slice(0,140));
    if (msgCount % 100 === 0) dbg('Msgs: '+msgCount+' · Vessels: '+Object.keys(vessels).length);
    var mtype = msg.MessageType;
    var meta  = msg.MetaData || {};
    var mmsi  = String(meta.MMSI || meta.MmsiString || '');
    if (mtype === 'PositionReport') {
      var pr = (msg.Message || {}).PositionReport || {};
      upsertVessel({
        mmsi: mmsi,
        name: (meta.ShipName || '').trim() || undefined,
        lat:  pr.Latitude,
        lon:  pr.Longitude,
        sog:  pr.Sog,
        cog:  pr.Cog,
        type: typeCache[mmsi],
        flag: meta.Flag || undefined
      });
    } else if (mtype === 'ShipStaticData') {
      var sd  = (msg.Message || {}).ShipStaticData || {};
      var dim = sd.Dimension || {};
      var len = (dim.A||0) + (dim.B||0);
      if (sd.Type) typeCache[mmsi] = sd.Type;
      var lat = parseFloat(meta.latitude || meta.Latitude || 0);
      var lon = parseFloat(meta.longitude || meta.Longitude || 0);
      if (lat !== 0 || lon !== 0) {
        upsertVessel({
          mmsi: mmsi,
          name: (sd.Name || '').trim() || (meta.ShipName||'').trim() || undefined,
          lat:  lat, lon: lon,
          type: sd.Type,
          flag: sd.Flag || meta.Flag || undefined,
          dest: (sd.Destination||'').trim() || undefined,
          eta:  sd.Eta || undefined,
          length: len > 0 ? len : undefined
        });
      }
    } else if (mtype === 'ERROR' || mtype === 'error') {
      var errMsg = (msg.Message || msg.Error || JSON.stringify(msg)).slice(0,200);
      setStatus('error', 'Server error: ' + errMsg);
    }
  }
  ws.onerror = function(e) {
    setStatus('error', 'WebSocket error — check browser console for details');
  };
  ws.onclose = function(evt) {
    var reason = evt.reason || ('Code '+evt.code);
    if (_aisStopped) { setStatus('init', 'Stopped'); dbg('AIS stopped.'); return; }
    setStatus('closed', 'Closed: '+reason+' · Retry in '+(reconnectDelay/1000).toFixed(0)+'s');
    clearTimeout(reconnectTimer);
    reconnectTimer = setTimeout(function(){
      reconnectDelay = Math.min(reconnectDelay * 1.5, 30000);
      init();
    }, reconnectDelay);
  };
}
function init() {
  setStatus('fetching', 'GET /api/ais-key …');
  fetch('/api/ais-key')
    .then(function(r) {
      if (!r.ok) return r.json().then(function(d){ throw new Error(d.reason || 'HTTP '+r.status); });
      return r.json();
    })
    .then(function(data) {
      if (!data.ok || !data.key) throw new Error(data.reason || 'Key missing in response');
      dbg('API key fetched OK · Connecting…');
      connect(data.key);
    })
    .catch(function(err) {
      setStatus('nokey', err.message);
      var led = document.getElementById('status-led');
      var txt = document.getElementById('status-text');
      led.style.background = '#ffaa33';
      txt.textContent = 'Live positions need AISSTREAM_API_KEY';
      dbg('Map visible — set AISSTREAM_API_KEY env var in Vercel to enable live AIS', err.message);
      var info = L.control({position:'topright'});
      info.onAdd = function() {
        var d = L.DomUtil.create('div');
        d.style.cssText = 'background:rgba(7,9,15,.88);color:#ffaa33;font-family:DM Mono,monospace;font-size:10px;letter-spacing:.06em;padding:8px 12px;border:1px solid rgba(255,170,50,.3);border-radius:6px;max-width:240px;line-height:1.5;';
        d.innerHTML = '<strong>AIS LIVE FEED</strong><br>Set <code>AISSTREAM_API_KEY</code><br>in Vercel env vars to enable<br>live vessel positions.';
        return d;
      };
      info.addTo(map);
    });
}
function aisStart() {
  _aisStopped = false;
  reconnectDelay = 3000;
  init();
}
function aisStop() {
  _aisStopped = true;
  clearTimeout(reconnectTimer);
  if (ws) { ws.close(); ws = null; }
  setStatus('init', 'Stopped by user');
  dbg('AIS tracker stopped.');
}
window.addEventListener('message', function(e) {
  if (e.data === 'ais:start') aisStart();
  if (e.data === 'ais:stop')  aisStop();
});
setStatus('init', 'Ready — press Start to connect');
dbg('AIS tracker ready. Press \u25b6 Start in the panel above.');
</script>
</body>
</html>"""
    return html


@app.route("/aircraft")
def aircraft():
    html = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Live Aircraft Tracker — Starfish</title>
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.css">
<script src="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.js"></script>
<style>
*{margin:0;padding:0;box-sizing:border-box}
html,body{width:100%;height:100%;overflow:hidden;font-family:'DM Mono',monospace,sans-serif;background:#07090f;color:#c8d8f0}
#topbar{position:fixed;top:0;left:0;right:0;height:40px;z-index:2000;background:rgba(7,9,15,.97);border-bottom:1px solid rgba(255,255,255,.07);display:flex;align-items:center;padding:0 12px;gap:10px;backdrop-filter:blur(12px)}
#status-led{width:7px;height:7px;border-radius:50%;background:#444;flex-shrink:0;transition:background .4s}
#status-text{display:none}
#ac-counter{font-size:9px;letter-spacing:.07em;color:#ffaa33;background:rgba(255,170,50,.08);border:1px solid rgba(255,170,50,.18);border-radius:20px;padding:2px 9px;white-space:nowrap;flex-shrink:0}
#filter-bar{display:flex;gap:5px;flex-shrink:0}
.fbtn{font-size:8px;letter-spacing:.08em;text-transform:uppercase;padding:2px 8px;border-radius:20px;border:1px solid rgba(255,255,255,.1);background:transparent;color:#5a7090;cursor:pointer;transition:all .15s;font-family:inherit;white-space:nowrap}
.fbtn:hover{border-color:#ffaa33;color:#ffaa33}
.fbtn.on{background:rgba(255,170,50,.1);border-color:rgba(255,170,50,.5);color:#ffaa33}
#statusbar{position:fixed;bottom:0;left:0;right:0;height:28px;z-index:2000;background:rgba(7,9,15,.97);border-top:1px solid rgba(255,255,255,.06);display:flex;align-items:center;padding:0 12px;gap:8px;overflow:hidden}
#dbg1{font-size:8px;letter-spacing:.05em;color:#3a5a7a;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;flex:1}
#poll-count{font-size:8px;letter-spacing:.05em;color:#2a3a52;white-space:nowrap;flex-shrink:0}
#wrap{position:fixed;top:40px;bottom:28px;left:0;right:0;display:flex;flex-direction:row}
#map{flex:1 1 0;min-width:0;background:#07090f}
#sidebar{width:280px;flex-shrink:0;background:#07090f;border-left:1px solid rgba(255,255,255,.06);display:flex;flex-direction:column;overflow:hidden}
#sb-header{padding:7px 10px;border-bottom:1px solid rgba(255,255,255,.05);font-size:8px;letter-spacing:.12em;text-transform:uppercase;color:#3a5070;display:flex;justify-content:space-between;align-items:center;flex-shrink:0}
#sb-count{color:#ffaa33;font-size:9px}
#sb-list{flex:1;overflow-y:auto;scrollbar-width:thin;scrollbar-color:#1a2a3a transparent}
#sb-list::-webkit-scrollbar{width:3px}
#sb-list::-webkit-scrollbar-thumb{background:#1a2a3a;border-radius:2px}
.acr{padding:7px 10px 8px;border-bottom:1px solid rgba(255,255,255,.035);cursor:pointer;transition:background .1s}
.acr:hover{background:rgba(255,170,50,.04)}
.acr.sel{background:rgba(255,170,50,.08);border-left:2px solid #ffaa33;padding-left:8px}
.acr-top{display:flex;align-items:center;gap:5px;margin-bottom:4px}
.acdot{width:5px;height:5px;border-radius:50%;flex-shrink:0}
.acs{font-size:11px;font-weight:700;color:#ffaa33;letter-spacing:.03em;flex:1;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.achex{font-size:8px;color:#2a4060;letter-spacing:.06em;text-transform:uppercase}
.acg{display:grid;grid-template-columns:1fr 1fr 1fr;gap:2px 6px}
.acf-k{font-size:7px;text-transform:uppercase;letter-spacing:.08em;color:#2a3a52}
.acf-v{font-size:9px;color:#7090b0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.leaflet-container{background:#07090f!important}
.leaflet-control-zoom{border:1px solid rgba(255,255,255,.1)!important;background:#0d1117!important;border-radius:6px!important}
.leaflet-control-zoom a{background:#0d1117!important;color:#6b7fa3!important;border-color:rgba(255,255,255,.08)!important;width:26px!important;height:26px!important;line-height:26px!important}
.leaflet-control-zoom a:hover{color:#ffaa33!important}
.leaflet-control-attribution{background:rgba(7,9,15,.8)!important;color:#2a3a50!important;font-size:8px!important}
.leaflet-popup-content-wrapper{background:#0d1117;border:1px solid rgba(255,170,50,.25);border-radius:8px;box-shadow:0 8px 32px rgba(0,0,0,.8)}
.leaflet-popup-tip-container{display:none}
.leaflet-popup-content{margin:12px 14px;font-size:10px;line-height:1.8;font-family:'DM Mono',monospace}
.leaflet-popup-close-button{color:#5a6a80!important;top:5px!important;right:8px!important}
.pname{font-size:12px;font-weight:700;color:#ffaa33;letter-spacing:.04em;margin-bottom:6px}
.prow{display:flex;justify-content:space-between;gap:12px;border-bottom:1px solid rgba(255,255,255,.04);padding:2px 0}
.pk{color:#3a4a60;text-transform:uppercase;font-size:8px;letter-spacing:.1em}
.pv{color:#90a8c8;font-size:10px}
.pbadge{display:inline-block;padding:1px 6px;border-radius:3px;font-size:8px;letter-spacing:.07em;text-transform:uppercase;font-weight:700;margin-bottom:5px}
@media(max-width:680px){
  html,body{overflow:auto}
  #topbar{height:44px;padding:0 8px;gap:6px}
  #filter-bar{gap:3px;overflow-x:auto;-webkit-overflow-scrolling:touch;flex-shrink:1;min-width:0;scrollbar-width:none}
  #filter-bar::-webkit-scrollbar{display:none}
  .fbtn{font-size:7px;padding:2px 6px;white-space:nowrap;flex-shrink:0}
  #wrap{position:relative;top:auto;bottom:auto;left:auto;right:auto;flex-direction:column;width:100%;margin-top:44px;margin-bottom:28px}
  #map{width:100%;height:55vw;min-height:220px;flex:none}
  #sidebar{display:flex;width:100%;flex-direction:column;border-left:none;border-top:1px solid rgba(255,255,255,.08);max-height:none;overflow:visible}
  #sb-header{padding:6px 10px;position:sticky;top:44px;z-index:100;background:#07090f}
  #sb-list{overflow-y:visible}
  .acr{padding:8px 10px 9px}
  .acs{font-size:12px}
  .acf-v{font-size:10px}
  #statusbar{position:fixed}
}
</style>
</head>
<body>
<div id="topbar">
  <div id="status-led"></div>
  <span id="status-text">Ready</span>
  <span id="ac-counter">0 aircraft</span>
  <div id="filter-bar">
    <button class="fbtn on" data-t="all">All</button>
    <button class="fbtn" data-t="airborne">Airborne</button>
    <button class="fbtn" data-t="military">Military</button>
    <button class="fbtn" data-t="ground">Ground</button>
  </div>
</div>
<div id="wrap">
  <div id="map"></div>
  <div id="sidebar">
    <div id="sb-header"><span>Live Aircraft Data</span><span id="sb-count">—</span></div>
    <div id="sb-list"></div>
  </div>
</div>
<div id="statusbar">
  <span id="dbg1">ADS-B tracker ready — press Start above</span>
  <span id="poll-count"></span>
</div>
<script>
var TYPE = {
  airborne: {color:'#ffaa33', label:'Airborne'},
  military: {color:'#ff4455', label:'Military'},
  ground:   {color:'#44ee88', label:'Ground'},
  other:    {color:'#6b7fa3', label:'Other'}
};
var MIL_HEX = ['ADF','AE0','AE1','AE2','AE3','AE4','AE5','AE6','AE7','AE8','AE9',
  '43C','43D','43E','43F','440','441','3F4','3F5','3F6','3F7','3F8','3F9',
  '7F0','7F1','7F2','7F3','7F4','7F5','7F6','7F7','7F8','7F9','7FA','7FB'];
var REGIONS = [
  [40,  -95,  2500], [51,   10,  2000], [35,  115,  2500], [20,   80,  2000],
  [-15, 133,  2000], [55,   60,  2500], [25,   45,  2000], [-5,   20,  2500],
  [-20, -60,  2500], [65,  -20,  1500], [35,  135,  1500], [5,   105,  2000],
];
var ac = {}, filter = 'all', selHex = null, polls = 0, ridx = 0, stopped = true;
var timer = null, INTERVAL = 8000;
var wrap = document.getElementById('wrap');
var mapEl = document.getElementById('map');
function isMobile() { return window.innerWidth <= 680; }
function setMapHeight() {
  if (isMobile()) mapEl.style.height = '';
  else mapEl.style.height = wrap.offsetHeight + 'px';
}
setMapHeight();
var map = L.map('map', {center:[30,10], zoom:3, zoomControl:true, attributionControl:true, preferCanvas:true});
L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
  attribution: '&copy; <a href="https://carto.com/">CARTO</a>',
  subdomains: 'abcd', maxZoom: 19
}).addTo(map);
window.addEventListener('resize', function() { setMapHeight(); map.invalidateSize(); });
function log(msg) { document.getElementById('dbg1').textContent = msg; }
function setLed(state) {
  var c = {live:'#44ee88', error:'#ff4455', init:'#ffaa33', stopped:'#333'}[state] || '#555';
  document.getElementById('status-led').style.background = c;
}
function setStatus(state, txt) { document.getElementById('status-text').textContent = txt; setLed(state); }
function classify(d) {
  var h = (d.hex || '').toUpperCase();
  for (var i=0; i<MIL_HEX.length; i++) if (h.startsWith(MIL_HEX[i])) return 'military';
  return d.on_ground ? 'ground' : 'airborne';
}
function planeIcon(color, hdg) {
  var r = parseFloat(hdg) || 0;
  var html = '<div style="width:0;height:0;position:relative;transform:rotate('+r+'deg)">' +
    '<svg xmlns="http://www.w3.org/2000/svg" width="18" height="24" viewBox="0 0 18 24"' +
    ' style="position:absolute;left:-9px;top:-12px">' +
    '<polygon points="9,0 17,22 9,16 1,22" fill="'+color+'" stroke="rgba(0,0,0,.7)"' +
    ' stroke-width="1" stroke-linejoin="round"/>' +
    '</svg></div>';
  return L.divIcon({html:html, className:'', iconSize:[18,24], iconAnchor:[9,12]});
}
function fAlt(d) {
  if (d.on_ground) return 'Ground';
  return d.alt_ft != null ? d.alt_ft.toLocaleString() + ' ft' : '—';
}
function fSpd(d) { return d.gs_kn != null ? Math.round(d.gs_kn) + ' kn' : '—'; }
function fHdg(d) { return d.track != null ? Math.round(d.track) + '°' : '—'; }
function fVrt(d) {
  if (d.baro_rate == null) return '—';
  var fpm = Math.round(d.baro_rate);
  return (fpm > 64 ? '▲ ' : fpm < -64 ? '▼ ' : '→ ') + Math.abs(fpm) + ' fpm';
}
function fPos(v) { return v != null ? parseFloat(v).toFixed(4) + '°' : '—'; }
function buildPopup(d) {
  var t = TYPE[d.cls] || TYPE.other;
  var badge = '<span class="pbadge" style="background:'+t.color+'18;color:'+t.color+';border:1px solid '+t.color+'44">'+t.label+'</span>';
  var rows = [
    ['ICAO', d.hex.toUpperCase()], ['Flight', d.callsign || '—'],
    ['Altitude', fAlt(d)], ['Speed', fSpd(d)], ['Heading', fHdg(d)],
    ['Vert Rate', fVrt(d)], ['Position', fPos(d.lat)+' / '+fPos(d.lon)],
    ['Squawk', d.squawk || '—'], ['Category', d.category || '—']
  ];
  var h = '<div class="pname">'+(d.callsign||d.hex.toUpperCase())+'</div>'+badge;
  rows.forEach(function(r) { if (r[1] && r[1] !== '—') h += '<div class="prow"><span class="pk">'+r[0]+'</span><span class="pv">'+r[1]+'</span></div>'; });
  return h;
}
function parseAC(o) {
  if (!o || o.lat == null || o.lon == null) return null;
  var lat = parseFloat(o.lat), lon = parseFloat(o.lon);
  if (isNaN(lat)||isNaN(lon)) return null;
  var onGround = (o.alt_baro === 'ground' || o.alt_baro === 0 || o.on_ground === true);
  var altFt = null;
  if (!onGround && o.alt_baro != null && o.alt_baro !== 'ground') {
    altFt = parseFloat(o.alt_baro);
    if (isNaN(altFt)) altFt = null;
  }
  return {
    hex: (o.hex || '').toLowerCase(), callsign: (o.flight || '').trim(),
    lat: lat, lon: lon, alt_ft: altFt, gs_kn: o.gs != null ? parseFloat(o.gs) : null,
    track: o.track != null ? parseFloat(o.track) : null,
    baro_rate: o.baro_rate != null ? parseFloat(o.baro_rate) : null,
    on_ground: onGround, squawk: o.squawk || null, category: o.category || null, cls: null
  };
}
function upsert(d) {
  if (!d || !d.hex) return;
  d.cls = classify(d);
  var t = TYPE[d.cls] || TYPE.other;
  var vis = (filter === 'all' || filter === d.cls);
  if (ac[d.hex]) {
    var v = ac[d.hex];
    Object.assign(v.data, d);
    v.lastSeen = Date.now();
    v.marker.setLatLng([d.lat, d.lon]);
    v.marker.setIcon(planeIcon(t.color, d.track));
    if (v.marker.isPopupOpen()) v.marker.setPopupContent(buildPopup(v.data));
    if (vis && !v.shown) { v.marker.addTo(map); v.shown=true; }
    if (!vis && v.shown) { map.removeLayer(v.marker); v.shown=false; }
  } else {
    var m = L.marker([d.lat, d.lon], {icon: planeIcon(t.color, d.track)});
    m.bindPopup('', {maxWidth:260, className:''});
    (function(hex){ m.on('click', function(){ m.setPopupContent(buildPopup(ac[hex].data)); }); })(d.hex);
    if (vis) m.addTo(map);
    ac[d.hex] = {marker:m, data:d, lastSeen:Date.now(), shown:vis};
  }
}
function updateUI() {
  var keys = Object.keys(ac);
  var n = keys.length;
  document.getElementById('ac-counter').textContent = n.toLocaleString() + ' aircraft';
  document.getElementById('sb-count').textContent = n;
  try { window.parent.postMessage({type:'adsb:count', count: n.toLocaleString()}, '*'); } catch(e){}
  renderSidebar(keys);
}
var _sbRender = 0;
function renderSidebar(keys) {
  var list = document.getElementById('sb-list');
  if (!list) return;
  if (!keys) keys = Object.keys(ac);
  var fkeys = keys.filter(function(h){ return filter==='all'||ac[h].data.cls===filter; });
  fkeys.sort(function(a,b){
    if (a===selHex) return -1; if (b===selHex) return 1;
    var ca=ac[a].data.callsign||ac[a].data.hex; var cb=ac[b].data.callsign||ac[b].data.hex;
    return ca.localeCompare(cb);
  });
  var show = fkeys.slice(0, 150);
  var html = '';
  show.forEach(function(h) {
    var v = ac[h]; var d = v.data;
    var t = TYPE[d.cls]||TYPE.other;
    var sel = h===selHex?' sel':'';
    var cs = d.callsign || d.hex.toUpperCase();
    html +=
      '<div class="acr'+sel+'" data-h="'+h+'">'+
        '<div class="acr-top">'+
          '<span class="acdot" style="background:'+t.color+'"></span>'+
          '<span class="acs">'+cs+'</span>'+
          '<span class="achex">'+d.hex.toUpperCase()+'</span>'+
        '</div>'+
        '<div class="acg">'+
          '<div><div class="acf-k">Alt</div><div class="acf-v">'+fAlt(d)+'</div></div>'+
          '<div><div class="acf-k">Speed</div><div class="acf-v">'+fSpd(d)+'</div></div>'+
          '<div><div class="acf-k">Hdg</div><div class="acf-v">'+fHdg(d)+'</div></div>'+
          '<div><div class="acf-k">V/S</div><div class="acf-v">'+fVrt(d)+'</div></div>'+
          '<div><div class="acf-k">Lat</div><div class="acf-v">'+fPos(d.lat)+'</div></div>'+
          '<div><div class="acf-k">Lon</div><div class="acf-v">'+fPos(d.lon)+'</div></div>'+
        '</div>'+
      '</div>';
  });
  if (fkeys.length > 150) html += '<div style="padding:8px 10px;font-size:8px;color:#2a3a50">+'+(fkeys.length-150)+' more</div>';
  list.innerHTML = html;
}
document.getElementById('sb-list').addEventListener('click', function(e) {
  var r = e.target.closest('.acr'); if (!r) return;
  var h = r.dataset.h; if (!ac[h]) return;
  selHex = h;
  var d = ac[h].data;
  map.setView([d.lat, d.lon], Math.max(map.getZoom(), 7), {animate:true});
  ac[h].marker.openPopup();
  ac[h].marker.setPopupContent(buildPopup(d));
  renderSidebar();
});
setInterval(function() {
  var cut = Date.now() - 180000;
  Object.keys(ac).forEach(function(h) { if (ac[h].lastSeen < cut) { map.removeLayer(ac[h].marker); delete ac[h]; } });
  updateUI();
}, 30000);
setInterval(function() { if (!stopped) renderSidebar(); }, 15000);
document.getElementById('filter-bar').addEventListener('click', function(e) {
  var b = e.target.closest('.fbtn'); if (!b) return;
  filter = b.dataset.t;
  document.querySelectorAll('.fbtn').forEach(function(x){ x.classList.remove('on'); });
  b.classList.add('on');
  Object.values(ac).forEach(function(v) {
    var vis = (filter==='all'||filter===v.data.cls);
    if (vis && !v.shown) { v.marker.addTo(map); v.shown=true; }
    if (!vis && v.shown) { map.removeLayer(v.marker); v.shown=false; }
  });
  renderSidebar();
});
function fetchFromSource(url) {
  return fetch(url, {signal: AbortSignal.timeout ? AbortSignal.timeout(10000) : undefined})
    .then(function(r) { if (!r.ok) throw new Error('HTTP '+r.status); return r.json(); })
    .then(function(data) {
      var list = data.ac || data.aircraft || data.states || [];
      if (!Array.isArray(list) || list.length === 0) throw new Error('empty');
      return {list: list, src: url};
    });
}
function poll() {
  if (stopped) return;
  var reg = REGIONS[ridx % REGIONS.length];
  ridx++;
  var lat = reg[0], lon = reg[1], nm = 250;
  var sources = [
    'https://api.airplanes.live/v2/point/'+lat+'/'+lon+'/'+nm,
    'https://api.adsb.lol/v2/aircraft?lat='+lat+'&lon='+lon+'&dst='+nm,
    'https://api.adsb.fi/v1/aircraft?lat='+lat+'&lon='+lon+'&radius='+nm,
  ];
  Promise.allSettled(sources.map(fetchFromSource)).then(function(results) {
    if (stopped) return;
    var winner = null;
    for (var i = 0; i < results.length; i++) {
      if (results[i].status === 'fulfilled') { winner = results[i].value; break; }
    }
    if (!winner) {
      var proxyUrl = '/adsb/proxy?lat='+lat+'&lon='+lon+'&dst='+nm;
      fetch(proxyUrl).then(function(r){ return r.json(); }).then(function(data){ handleData(data.ac || [], 'proxy'); }).catch(function(err){ setStatus('error', 'No source — retrying…'); timer = setTimeout(poll, 15000); });
      return;
    }
    handleData(winner.list, winner.src.split('/')[2]);
  });
}
function handleData(list, source) {
  polls++;
  var parsed = 0;
  list.forEach(function(o) {
    var d = parseAC(o);
    if (d) { upsert(d); parsed++; }
  });
  setStatus('live', 'Live · ' + source);
  setLed('live');
  log('Poll #'+polls+' ['+source+'] · Region '+(ridx%REGIONS.length)+'/'+REGIONS.length+' · +'+parsed+' · '+Object.keys(ac).length+' tracked');
  document.getElementById('poll-count').textContent = 'Total: '+Object.keys(ac).length;
  updateUI();
  timer = setTimeout(poll, INTERVAL);
}
function adsbStart() { stopped = false; ridx = 0; polls = 0; setStatus('live', 'Connecting…'); setLed('init'); log('Starting ADS-B poll…'); poll(); }
function adsbStop() { stopped = true; clearTimeout(timer); timer = null; setStatus('stopped', 'Stopped'); setLed('stopped'); log('ADS-B tracker stopped.'); }
window.addEventListener('message', function(e) { if (e.data === 'adsb:start') adsbStart(); if (e.data === 'adsb:stop') adsbStop(); });
setStatus('stopped', 'Ready'); setLed('stopped'); log('ADS-B tracker ready. Press ▶ Start to connect.');
</script>
</body>
</html>"""
    return html


@app.route("/adsb/proxy")
def adsb_proxy():
    lat = request.args.get("lat", "0")
    lon = request.args.get("lon", "0")
    dst = request.args.get("dst", "250")
    try:
        r = requests.get(
            f"https://api.adsb.lol/v2/aircraft?lat={lat}&lon={lon}&dst={dst}",
            timeout=15,
            headers={"User-Agent": "Starfish/1.0"},
        )
        if r.status_code == 200:
            return jsonify(r.json())
        with _adsb_lock:
            buf = list(_adsb_buffer)
        cols = ["ts","hex","flight","lat","lon","alt_baro","gs","track"]
        ac = []
        for row in buf:
            if row[3] and row[4]:
                obj = dict(zip(cols, row))
                obj["baro_rate"] = None
                ac.append(obj)
        return jsonify({"ac": ac, "_source": "buffer", "_upstream_status": r.status_code})
    except Exception as exc:
        return jsonify({"error": str(exc), "ac": []}), 502

# ══════════════════════════════════════════════════════════════════════════════
# LIVE SATELLITE IMAGERY — BACKEND ROUTES
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/sentinel/token-status")
def sentinel_token_status():
    return jsonify(_token_mgr.status())

@app.route("/sentinel/geocode")
def sentinel_geocode():
    q = request.args.get("q", "")
    if not q:
        return jsonify({"error": "No query"}), 400
    try:
        r = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params={"q": q, "format": "json", "limit": 5, "addressdetails": 0},
            headers={"User-Agent": "Starfish/1.0"},
            timeout=8,
        )
        r.raise_for_status()
        return jsonify({"results": r.json()})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/sentinel/proxy-tile")
def sentinel_proxy_tile():
    layer     = request.args.get("layer", "TRUE-COLOR")
    date_from = request.args.get("dateFrom")
    date_to   = request.args.get("dateTo")
    cloud     = request.args.get("cloud", "30")
    z         = request.args.get("z", "5")
    x         = request.args.get("x", "0")
    y         = request.args.get("y", "0")

    evalscript = EVALSCRIPTS.get(layer, EVALSCRIPTS["TRUE-COLOR"])
    lon_w, lat_s, lon_e, lat_n = xyz_to_wgs84_bbox(z, x, y)
    PROCESS_URL = "https://sh.dataspace.copernicus.eu/api/v1/process"
    payload = {
        "input": {
            "bounds": {
                "bbox": [lon_w, lat_s, lon_e, lat_n],
                "properties": {"crs": "http://www.opengis.net/def/crs/OGC/1.3/CRS84"},
            },
            "data": [{
                "type": "sentinel-2-l2a",
                "dataFilter": {
                    "timeRange": {"from": f"{date_from}T00:00:00Z", "to": f"{date_to}T23:59:59Z"},
                    "maxCloudCoverage": int(cloud),
                    "mosaickingOrder": "leastCC",
                },
            }],
        },
        "output": {
            "width": 512, "height": 512,
            "responses": [{"identifier": "default", "format": {"type": "image/png"}}],
        },
        "evalscript": evalscript,
    }
    try:
        hdrs = {
            "Authorization": f"Bearer {COPERNICUS_TOKEN()}",
            "Content-Type": "application/json",
            "Accept": "image/png",
        }
        r = requests.post(PROCESS_URL, json=payload, headers=hdrs, timeout=30)
        ct = r.headers.get("Content-Type", "")
        if r.status_code == 200 and "image" in ct:
            from flask import Response as FlaskResponse
            return FlaskResponse(r.content, content_type=ct)
        return FlaskResponse(EMPTY_PNG, content_type="image/png")
    except Exception:
        from flask import Response as FlaskResponse
        return FlaskResponse(EMPTY_PNG, content_type="image/png")

@app.route("/adsb/data")
def adsb_data():
    """Return the latest buffered ADS-B rows as JSON for the frontend."""
    limit = min(int(request.args.get("limit", 500)), 5000)
    with _adsb_lock:
        rows = list(_adsb_buffer)[-limit:]
    cols = ["ts", "hex", "flight", "lat", "lon", "alt_baro", "gs", "track"]
    return jsonify({"count": len(rows), "columns": cols, "rows": rows})

@app.route("/debug")
def debug():
    out, color = [], "#7fff7f"
    try:
        df, err = fetch_yfinance_data("AAPL","5d")
        if err: out.append(f"Error: {err}"); color="#ff9966"
        elif df is not None: out.append(f"OK shape:{df.shape}"); out.append(df.tail().to_string())
        else: out.append("No data"); color="#ffaa44"
    except Exception: out.append(traceback.format_exc()); color="#ff7f7f"
    try:
        macro = fetch_all_macro()
        out.append(f"\nFRED macro series fetched: {len(macro)}")
        for sid, d in list(macro.items())[:3]:
            out.append(f"  {sid}: {d['value']} [{d['date']}]")
    except Exception as e:
        out.append(f"\nFRED error: {e}")
    body = "\n".join(out)
    return f"<pre style='background:#111;color:{color};padding:24px;font-family:monospace;white-space:pre-wrap'>{body}</pre>"
 
 
@app.errorhandler(500)
def e500(e):
    return f"<pre style='background:#111;color:#aaa;padding:24px;font-family:monospace'>500\n\n{traceback.format_exc()}</pre>", 500
 
 
if __name__ == "__main__":
    print("=" * 60)
    print("  STARFISH — Unified Market Intelligence Platform + Alpaca Live Trading")
    print("  http://127.0.0.1:5000")
    print("=" * 60)
    print("\n  pip install flask requests numpy pandas yfinance plotly httpx beautifulsoup4 lxml pytrends websocket-client\n")
    _start_adsb_collector()
    app.run(debug=True, host="0.0.0.0", port=5000)

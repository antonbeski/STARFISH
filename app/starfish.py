"""
STARFISH — Market Dynamics
Stocks · AI Analysis · Sectors · News · US Equities
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

# ══════════════════════════════════════════════════════════════════════════════
# CRYPTO MARKET DATA CONFIGURATION
# ══════════════════════════════════════════════════════════════════════════════
COINGECKO_API_KEY  = os.environ.get("COINGECKO_API_KEY", "").strip()
COINGECKO_BASE_URL = os.environ.get(
    "COINGECKO_BASE_URL",
    "https://pro-api.coingecko.com/api/v3" if COINGECKO_API_KEY else "https://api.coingecko.com/api/v3",
).rstrip("/")
COINGECKO_HEADERS = {"accept": "application/json"}
if COINGECKO_API_KEY:
    COINGECKO_HEADERS["x-cg-pro-api-key"] = COINGECKO_API_KEY

DIA_BASE_URL = os.environ.get("DIA_BASE_URL", "https://api.diadata.org").rstrip("/")
DIA_HEADERS = {"accept": "application/json"}

CRYPTO_WATCHLIST = [
    {"symbol": "BTC",  "name": "Bitcoin",          "category": "Layer 1"},
    {"symbol": "ETH",  "name": "Ethereum",         "category": "Layer 1"},
    {"symbol": "SOL",  "name": "Solana",           "category": "Layer 1"},
    {"symbol": "BNB",  "name": "BNB",              "category": "Layer 1"},
    {"symbol": "XRP",  "name": "XRP",              "category": "Layer 1"},
    {"symbol": "ADA",  "name": "Cardano",          "category": "Layer 1"},
    {"symbol": "DOGE", "name": "Dogecoin",         "category": "Meme"},
    {"symbol": "TRX",  "name": "TRON",             "category": "Layer 1"},
    {"symbol": "AVAX", "name": "Avalanche",        "category": "Layer 1"},
    {"symbol": "LINK", "name": "Chainlink",        "category": "Oracle"},
    {"symbol": "DOT",  "name": "Polkadot",         "category": "Layer 0"},
    {"symbol": "MATIC","name": "Polygon",          "category": "Layer 2"},
    {"symbol": "ATOM", "name": "Cosmos",           "category": "Layer 0"},
    {"symbol": "LTC",  "name": "Litecoin",         "category": "Layer 1"},
    {"symbol": "BCH",  "name": "Bitcoin Cash",     "category": "Layer 1"},
    {"symbol": "UNI",  "name": "Uniswap",          "category": "DeFi"},
    {"symbol": "AAVE", "name": "Aave",             "category": "DeFi"},
    {"symbol": "SUI",  "name": "Sui",              "category": "Layer 1"},
    {"symbol": "APT",  "name": "Aptos",            "category": "Layer 1"},
    {"symbol": "SHIB", "name": "Shiba Inu",        "category": "Meme"},
    {"symbol": "PEPE", "name": "Pepe",             "category": "Meme"},
    {"symbol": "ARB",  "name": "Arbitrum",         "category": "Layer 2"},
    {"symbol": "OP",   "name": "Optimism",         "category": "Layer 2"},
    {"symbol": "INJ",  "name": "Injective",        "category": "DeFi"},
    {"symbol": "NEAR", "name": "NEAR Protocol",    "category": "Layer 1"},
    {"symbol": "FIL",  "name": "Filecoin",         "category": "Layer 1"},
    {"symbol": "HBAR", "name": "Hedera",           "category": "Layer 1"},
    {"symbol": "ETC",  "name": "Ethereum Classic", "category": "Layer 1"},
    {"symbol": "XLM",  "name": "Stellar",          "category": "Layer 1"},
    {"symbol": "ICP",  "name": "Internet Computer","category": "Layer 1"},
    {"symbol": "TON",  "name": "Toncoin",          "category": "Layer 1"},
]

alpaca_cache = {}
alpaca_cache_time = {}
ALPACA_CACHE_TTL  = 15  # seconds
CRYPTO_CACHE_TTL  = 10  # seconds

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



def _safe_float(value):
    try:
        if value is None or value == "":
            return None
        return float(value)
    except Exception:
        return None


def _safe_int(value):
    try:
        if value is None or value == "":
            return None
        return int(float(value))
    except Exception:
        return None


def _safe_json_get(url, headers=None, timeout=10):
    try:
        resp = requests.get(url, headers=headers, timeout=timeout)
        if resp.status_code != 200:
            print(f"[CRYPTO] HTTP {resp.status_code} for {url}")
            return None
        return resp.json()
    except Exception as exc:
        print(f"[CRYPTO] request error for {url}: {exc}")
        return None


def coingecko_fetch_crypto_data(symbols):
    """
    Fetch crypto quotes from CoinGecko using symbol-based lookup.
    The endpoint can return price, market cap, 24h volume, 24h change, and
    the last update timestamp when supported by the plan.
    """
    unique_symbols = [s.lower() for s in dict.fromkeys(symbols) if s]
    if not unique_symbols:
        return {}

    params = (
        f"symbols={quote_plus(','.join(unique_symbols))}"
        "&vs_currencies=usd"
        "&include_market_cap=true"
        "&include_24hr_vol=true"
        "&include_24hr_change=true"
        "&include_last_updated_at=true"
    )
    url = f"{COINGECKO_BASE_URL}/simple/price?{params}"
    data = _safe_json_get(url, headers=COINGECKO_HEADERS, timeout=12) or {}

    # normalize keys for safer lookup
    return {str(k).lower(): v for k, v in data.items() if isinstance(v, dict)}


def dia_fetch_crypto_data(symbols):
    """
    Fetch crypto quotes from DIA using the current public quotation endpoint.
    """
    unique_symbols = [s.upper() for s in dict.fromkeys(symbols) if s]
    if not unique_symbols:
        return {}

    result = {}

    def _fetch_one(symbol):
        url = f"{DIA_BASE_URL}/v1/quotation/{quote_plus(symbol)}"
        payload = _safe_json_get(url, headers=DIA_HEADERS, timeout=12)
        return symbol, payload

    max_workers = min(8, max(1, len(unique_symbols)))
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as ex:
        for symbol, payload in ex.map(_fetch_one, unique_symbols):
            if isinstance(payload, dict) and payload:
                result[symbol] = payload

    return result


def _parse_iso_ts(value):
    if not value:
        return None
    try:
        # support trailing Z and fractional seconds
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return None


def _fmt_ts(dt):
    if not dt:
        return ""
    try:
        return dt.astimezone().isoformat(timespec="seconds")
    except Exception:
        return dt.isoformat(timespec="seconds")


def _derive_prev_from_change(price, change_pct):
    if price is None or change_pct is None:
        return None
    try:
        denom = 1.0 + (float(change_pct) / 100.0)
        if abs(denom) < 1e-12:
            return None
        return float(price) / denom
    except Exception:
        return None


def alpaca_fetch_crypto_data():
    """Fetch live crypto data from CoinGecko for the crypto watchlist."""
    symbols = [coin["symbol"] for coin in CRYPTO_WATCHLIST]
    cg_data = coingecko_fetch_crypto_data(symbols)

    result = []

    for coin in CRYPTO_WATCHLIST:
        sym = coin["symbol"]
        sym_l = sym.lower()
        cg = cg_data.get(sym_l, {})

        cg_price = _safe_float(cg.get("usd"))
        cg_mcap = _safe_float(cg.get("usd_market_cap"))
        cg_vol = _safe_float(cg.get("usd_24h_vol"))
        cg_change_pct = _safe_float(cg.get("usd_24h_change"))
        cg_updated_at = cg.get("last_updated_at")
        cg_ts = datetime.utcfromtimestamp(cg_updated_at) if cg_updated_at else None

        if cg_price is None:
            continue

        prev_close = _derive_prev_from_change(cg_price, cg_change_pct)
        change = None
        if prev_close is not None:
            change = round(cg_price - prev_close, 8)

        result.append({
            "symbol": sym,
            "name": coin["name"],
            "category": coin["category"],
            "price": cg_price,
            "ask": None,
            "bid": None,
            "ask_size": None,
            "bid_size": None,
            "spread": None,
            "change": change if change is not None else 0,
            "change_pct": round(cg_change_pct, 4) if cg_change_pct is not None else 0,
            "volume": cg_vol,
            "market_cap": cg_mcap,
            "open": prev_close,
            "high": None,
            "low": None,
            "close": cg_price,
            "data_type": "CoinGecko",
            "timestamp": _fmt_ts(cg_ts),
            "source": "CoinGecko",
            "coingecko_price": cg_price,
            "coingecko_last_updated_at": int(cg_updated_at) if cg_updated_at else None,
        })

    return result


def get_alpaca_live_price(ticker):

    """
    Return the best available real-time price for a US-listed ticker.

    Priority order:
      1. Alpaca WebSocket (sub-second trade feed)  — data_type = "LIVE"
      2. Alpaca REST /stocks/trades/latest          — data_type = "TRADE"
      3. Alpaca REST /stocks/quotes/latest          — data_type = "QUOTE"
      4. Alpaca REST /stocks/bars/latest            — data_type = "BAR"
      5. yfinance fast_info                         — data_type = "YFIN"
      6. None  (non-US ticker or all sources failed)

    Returns a dict or None:
      {
        "price": float,
        "bid": float | None,
        "ask": float | None,
        "bid_size": int | None,
        "ask_size": int | None,
        "spread": float | None,
        "volume": int | None,
        "open": float | None,
        "high": float | None,
        "low": float | None,
        "data_type": str,
        "timestamp": str,
        "source": str,
      }
    """
    # Only US tickers are available on Alpaca / IEX feed
    sym = ticker.upper()
    if "." in sym:          # e.g. TCS.NS, RELIANCE.BO — skip
        return None

    # ── 1. WebSocket cache (sub-second freshness) ───────────────────────────
    with alpaca_rt_lock:
        rt = dict(alpaca_rt_data.get(sym, {}))

    if rt.get("price"):
        bid  = rt.get("bid")
        ask  = rt.get("ask")
        return {
            "price":    rt["price"],
            "bid":      bid,
            "ask":      ask,
            "bid_size": rt.get("bid_size"),
            "ask_size": rt.get("ask_size"),
            "spread":   round(ask - bid, 4) if (ask and bid) else None,
            "volume":   rt.get("volume"),
            "open":     None, "high": None, "low": None,
            "data_type": "LIVE",
            "timestamp": rt.get("ts", ""),
            "source":   "Alpaca WebSocket",
        }

    # ── 2–4. Alpaca REST (requires API key) ─────────────────────────────────
    if ALPACA_API_KEY:
        try:
            # Fetch all three endpoints in parallel for speed
            def _get_trade():
                r = alpaca_get(f"{ALPACA_DATA_URL}/stocks/trades/latest"
                               f"?symbols={sym}&feed=iex")
                return r.json().get("trades", {}).get(sym) if r and r.status_code == 200 else None

            def _get_quote():
                r = alpaca_get(f"{ALPACA_DATA_URL}/stocks/quotes/latest"
                               f"?symbols={sym}&feed=iex")
                return r.json().get("quotes", {}).get(sym) if r and r.status_code == 200 else None

            def _get_bar():
                r = alpaca_get(f"{ALPACA_DATA_URL}/stocks/bars/latest"
                               f"?symbols={sym}&feed=iex")
                return r.json().get("bars", {}).get(sym) if r and r.status_code == 200 else None

            with concurrent.futures.ThreadPoolExecutor(max_workers=3) as ex:
                ft, fq, fb = (ex.submit(_get_trade),
                              ex.submit(_get_quote),
                              ex.submit(_get_bar))
                trade = ft.result(timeout=6)
                quote = fq.result(timeout=6)
                bar   = fb.result(timeout=6)

            price    = (trade or {}).get("p") or (quote or {}).get("ap") or (bar or {}).get("c")
            bid      = (quote or {}).get("bp")
            ask      = (quote or {}).get("ap")
            b_size   = (quote or {}).get("bs")
            a_size   = (quote or {}).get("as")
            volume   = (trade or {}).get("s") or (bar or {}).get("v")
            ts       = ((trade or {}).get("t") or (quote or {}).get("t")
                        or (bar or {}).get("t") or "")

            if price:
                dtype = ("TRADE" if (trade or {}).get("p")
                         else "QUOTE" if ask
                         else "BAR")
                return {
                    "price":    float(price),
                    "bid":      float(bid)    if bid    else None,
                    "ask":      float(ask)    if ask    else None,
                    "bid_size": int(b_size)   if b_size else None,
                    "ask_size": int(a_size)   if a_size else None,
                    "spread":   round(float(ask) - float(bid), 4) if (ask and bid) else None,
                    "volume":   int(volume)   if volume else None,
                    "open":     float((bar or {}).get("o", 0)) or None,
                    "high":     float((bar or {}).get("h", 0)) or None,
                    "low":      float((bar or {}).get("l", 0)) or None,
                    "data_type": dtype,
                    "timestamp": ts,
                    "source":   f"Alpaca REST ({dtype})",
                }
        except Exception as _e:
            pass  # fall through to yfinance

    # ── 5. yfinance fast_info (15-min delayed for non-IEX) ──────────────────
    try:
        import yfinance as yf
        fi = yf.Ticker(sym).fast_info
        price = getattr(fi, "last_price", None) or getattr(fi, "regular_market_price", None)
        if price:
            return {
                "price":    float(price),
                "bid":      None, "ask": None,
                "bid_size": None, "ask_size": None, "spread": None,
                "volume":   getattr(fi, "three_month_average_volume", None),
                "open":     getattr(fi, "open", None),
                "high":     getattr(fi, "day_high", None),
                "low":      getattr(fi, "day_low", None),
                "data_type": "YFIN",
                "timestamp": "",
                "source":   "yfinance fast_info",
            }
    except Exception:
        pass

    return None


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
_LOGO_DATA_URI = "data:image/jpeg;base64,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zzzzzzzzzzzzzyxzzxzwzzzzzzzzybqrANLxzzyzzzxzxzzzzzzzzzzzzzzzzzzzzzzzzzzzzjSa4ojoiDjzzzzzzzzzzzzzzzzzzzzyjyjzzzzwDzzzyiiyR5jBhbrCjzyjzzxTxTzzzyjzzzzzzzzzzzzzzzzzzzzyigKqjBQj7qjjzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzjDx7AjTSwRZazzzzzzzzzzzzzzzzzzzzzjzzTzzzzzzzzyShTbxDzATSI5jTDzzzTzzzzTzjzzzzzzzzzzzzzzzzyzjyTQbrSDxyTzw6zxhzzzzzzzzzzzzzzzzzzzzjzzSzABwBSDa66ixzTxyihoaTQQhzRDRjjjTzzzzzzzzzyiSTwjBhK576rpgAxzzxzwxRbY65LJJhCxwjzzzzzzzzzyyiw6LIq75a5oQhiTzzzzwjigoJDaqJbLoYiCQTzzzzzzzwgA7K7STzjxTjRiTjzzzzzjzyySBDRyhR6LLpATzzzyzzywyypLoTxhySzwzzzzzzzzzzxwzwxwjwyQCS5JwzzzzzzzzzzTDwZJzigyxzzzzzzzzzzzzzzzxwTwyCJqCTTzzzzzzzzzzxxiJKoxDDTzzzzzzzzzzzzzzzzSDCRp6aTzzzzzzzzzzzzzzyQ6IziTRzzzzzzzzzzzzzzyRxxzgpIRxzzzzzzzzzzzzzzxRhwKpAQzzzzzzzzzzzzzyyDzR6bwBzzzzzzzzzzzyzzxzzzQzjzAzQDTzzzzzzzzzzySTBa7qjRzzzzzzyjzzzzzzzzzzzwjp5RzjTzzzzzzzzzzjjARIqxzzzzzzzzzzzzzzzzjTzzzgyxI6hxzzzzzzzzzzyywh5rTzzzzzzzzzzzzzzzzzzzzzzzADKa6RTzzzzzzzzzyhxw5SBTzzzzzzzzzzzzzzzzzzzzzwzyrLxjzzzzzzzzzzyhRRpZzzzzzzzzzzzzzzzzjzzzzzTzDB4ATzTzzzzzzzzzyhhh4rjDzzzzzzjzzzzzzzzzzzzzzzBQeoxzzzzwCjRTzzyyzzpZgzzzzzzzzzzzzzzzzzzzzzzzSgawQTTSwASTjAiBSDjzKpjTzzzzzzzzzzzzzzzzzzzzTxCzJTTDzjTgTZBQCjzTzBZaYTzTzzzzzzzzzzzyzzxzzzzyhLqDyDgDzIY6bZYBRCwSAr4jzzzzzzzzzzzzzzzzzzzzzhSY5hQjqb6LyAixy44AiDqpaTzzzzzzzzzzzzzzzyxzzzyyhYpxLwLTRhhyyygg7JJgpJ7QxzzzzzzzzzzzzzzzzzzzzgRdrYp4KTCSxzyzRiw5IoJu4xDzzzzzzzzzzzzzzzzzzzyhhC5yyzCRzzzzzzzxihAwJpYTzzzzzzzzzzzzzzzzzzzxzxABQDSTzzxzzzzzzzyzyARxgDxzzzzzzzzzzzzzzzzzzzzwzwzxzzzzzzzzzzzzzzwwywxzzzzzzzzzzzzzzzzzzzzzzzDzzzzzzzzzzzzzjzzzzjzzjzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzTzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzz/xAAUEQEAAAAAAAAAAAAAAAAAAACw/9oACAEDAQE/EARP/8QAFBEBAAAAAAAAAAAAAAAAAAAAsP/aAAgBAgEBPxAET//EAC0QAQEAAgICAQQCAQQCAwEAAAERACExQVFhcRAggZFAUKEwYLHB0eFw8PGQ/9oACAEBAAE/EP8A4E1FX2/Z3wjdd/dTprxzhon2d4I3Xf8A/AevA5XkfuINxb19nFQb3fH36thfX2FbQ83x9wTsOi4cb5+wqUG9/H3FKw6Lhxv7XjXOECx7P/z5usezx9C1vHX+wAFQnr7FAroMESmx+4BUJ6+wooL5+8BUJ6xQ5+nsLSuMpiJFeDI5CecWFkJNe8FCVBIriLAjsccWMB0+8UGDlXRg019gRULo+5AqA8v3oFQj2fYgQUF49/0wEAHOvsAEdj1gABoOvuBgA5+yBAzZfvAQAesQeS4lJgwYVd+8FWXVNnn1nU8Jmnq7rs8YYyxh5w+BAGDprPlxuROR4cACGg+xAgY0vX3AgBHp+52YAAAdH2KIoKcev7xKbI4rxrwI84kSFQ4xz4oNRXePIwzp+H+crqbq8Msudf8AoDXxhr4dBNY0V9eKlmNsLbcS3Imo1cv5xKERTZ4/2lKlTCvLjxvCUQpAxxPxUTZx8MFkyNDqecO38qVTHTzBA3hoyyicJiP3gqrw4oFWH+0ggPVtneG3iogeE7wAnSmJ8OOaQFIV6csJzRLVg6xVc2W2nT4xz8SU2LfLJ2qvQjsPOc6f00kd4a23PAnd5c874f8AcZMFip5Yf7QVHwZqnHqjplxOoFkKzrD3XUFfjKotFIN6YY49qdD2Y7SMKVM5sy7JERTo0GBuCm8M5GTBLeUTkxq/VlqHDrC6hoVnzMjEnJEpkTa7Wa/2gImuMMEUT+me8bgCquI6RwFWpcSypf5ty41Y2PyYErbUfKZuoCDUS8+s1/BPCRmg9ePcYxsD05TQ1JPH9oKDYnWEAsCfcZQVrdv2WFYk1kgWBN/cMhXd237DmqRun7bCVLq3vLtY8l5wfTWmhSc4X9BCG3t1muSkwr94zi9SHvcHC02qmS8AuPmyBc8kszYR68Mc8YtjYrd+CuUO1dIShzm/UJL2b34xXltKf8sRoEN25d7BF28/QQluG0rtdP3C6UHw4aPtdkwTCoefsNCt2N/cUmz0/wBoobfI1DN/ZSVmAliUDSn/AFl8dqNXuec2qMYBvnFbGGq7PWQtIQirzMu2Ne4E/wCMiVAVnPeBgK2NRh2KDciEN4e7vsoIGcTiMA93B3Jni33mwIrzB7w0VyQrgsoPkji/7LVSUhGww/LwGkxUyJHKu/8AOSSogbHdwWVQ6n4ZqtCdGm6wwzqCW4mCgoZNGmuMPeqCZRwYNISoQ3jfM93kO/Ti57tDxqn5xRKaoCORg8GHHOG7mDsPnEEjvACBD/ZRQWTTLMKAVjb5yvNhCta3i+GCVvHsEM5Wq25LIMBR0QcHRaln4NcBxm/5GuCwXm6/eM2JBH/1xxgw87mq30GrPzjGIhpUOZvN6auiN7o85DGkhT3HeETQmaE1XvrJseAC70S4o0nGD8YDRGmD+MSQBO/N8/1gFUU6+xQK6DEATY9/cAqE9fYoFdBgiU2P3AKhPX2BFBdF+lFfWBvGogHvBT9wtHD0uqCDeH3l85gL6nnB5VUZaSX1gFuCRdAnOG8/6E9sTrtUuuf/ADji98BiFrE+Fb/1gutdPbjDIS4AByk67RVJvHxrVO08fjK6P3mnyyAfwVBO/jEFSQabXC7wys1SYC9aqjiUGyOQeZ9wBUAdv3gChHs+xAgoLx7+4BUB7+1ACgvB5/gAFBXv7EEjscAANB19wCAD19iCR2OABDQfcAgA9fYMQMafSAvvDZngUTOHjwwwJ37Qj7feLMphi+54xyeQBAglwUxD6Kih0YUCIsTB8IVJZiLeDK9tKxvf6xU3Hhplc4uRXr95PIk0nsMY8LBihMVZtR0J484IeK6osv5xneQ0lOQ6wkMxC4D9YCBiQkSFoPF+4AgEen7wAAB0fYhRQU49fcAgE9/aoFBTh8f1mkR82GKUXYPQuN8HQv3kwiREsVWact/VIqfR3kBjCZEqxTe8bV8hoXpOcsnCWgk84K6CUj/jHpV2av5udg9LrEoRROEypR5Vc4GBbwU8ATt32Y44Rsx/BgQUwMv0mFkVcN8sZHBIgNJ7nHnDokYt7xI2pISuJ/shIsEUveDGurgGfMRIZtLQlFeT7xV6qBV+DJDw6BRMGhfvBW5vJCHEBsxgKgqqc4mhxEHwY8GbbNMMdEuKHhxUbUPTOXXFU3d4uXcQuybzagSBYnGQE4LR7yC2hTYO8KyQ8a/GdpylZhYHAtn4+hpRXZ/sZeVkQbreX0GtOrgYytVVXnGzyXKhJlPFs6085VSVMopf8ZyBt8g94JYk2hB8+8mBBS+slvuJgyOnvN4aQw940cG+FM7azIyyfECzHP4bHDgpRASRrBMukPRNLkWpJSSc+cdfLY25wiBI5Xj6AQAHR/sQPJmxBcTRECBoOPdFWts8YVBNNxM5POPjW0y+ZNYpbZlQFLM2UuZZ7prLfd/7dlydGIn4zlJjOjEVFHyOKqqqvblZLrOMVWrXOA+I6cG+QXImHzcmsMBiS1Ct9GbFGokLsdawYjVK+HJMFnoofowLgRFI16c+saRoGHlyrVNgH5/2IoFWGDTWejt34YBetPFPGG8R31hs+7yCEXHE23yeWLDnENBaYclZAhMqB2MTAl+c82PMpoXR4yms35xAF4xi0QujP0TOrvNWOksHZg85aii11l2zNYnejGophghI5DIPIdzjAuii/l3mguAXYuFAroM4C6Jp/qgj2qTn7CRcJMIRYE+4Qlbbt+wirh1hBHBr7hkWW7b9QCvnC2TyUfkwWyAlWE24QqNpW5r8Y2khqQ6TN3MAgeNDvHT7y1SjbcSz1kE4c7cGUrNCazl91rHKoyq5cmiuIoOkyMs1gVA5wKR5MuklXi5bcQDtyCIQkduHABoqzen/AMYF9B8vziHAlpHg1XH/AJSHTs4MFcBVHfG1w8LcE4echqGrU/vFGLwwX35+gS+8F6R8YEJ9rsmCNIeX7FBbsb+4pNnr7QQt4b/pLub+gqJ1BjrBK2E0X6QcrYxvh7yvNQWrPBgiILiKXjLMPQpfM8Y7M6wX9+cPs6AVDipxgx/i1rX+MNmyWPybnCPItmIAsPtxhRVeBy6I4lVauVkusGNMVSu1xlEnHmYtJdR04ORo6BwYxiF4Nf8AvJzw0/xyWKglvB1cFrtszvc4w10MSC89rjInNJ3OJivWwwH4uT+jPdPK6Po4UsYD8ecOV/FnFBOy4OP9yI8NxQ5+gjwjgtCG4axtOA8U6mWC1prSZMAXZuvXvA1MaA094HOrpCav45zd4ASxjnTeNaPCRw1/nAA/YUzjwpa8PWdSp6yK7T39I7J3m7KVq4tY+jjOw77njCem9lfLOMPYBuP/AHMMK7j394+Bg0hcc68YUzS9dqy5ALoEB+T3iNm1bxM3YK6Ji6aU2X6CPGKHLP7ELmlThDxhRt0Vlp4+h7ADTx+cugERteZk0ACMrzMnICbldb6yzrCNrzMn5eeR+M5u/hp4b1Ms4CRsfjOlVGSaGacefZO94bKpmneT0WwaN5DvifYju4LkjtaOPcwvkoF4lkuAdz9KB3zirzA4ZyS5tDkGquMOMZGqOaySsKwxIxyO0Z5+6P0TkJ84ayzpWGSnIHlx5YTwerx1h1qSgP4uJbgSrthN2JJVDZbjfZ4LOd3CZuRoAft8Z+POvc5mfGpagzems2jxjcxReWbwRCl0v3zVJHtHjIzo3Mv4zaRUOuu2ECwIMsclw3kPxizvjcjx6ykYz3kL7aTHmi4LH0L23+Ts4dFvX1u8daGr8Y3NOHDHLW5ZziAroO8B4ojw5zR8w8tmKBXHdyHWmzAJCnFrkaBN5HAHBGxN+P1nE0uuV8GKfDS8npw4Iaykau8Nw2t7Z0YU3KKkYFxpGR6g/vNbYs8PWVaPcFrSfjBsGB2LbcQWv30vx85FewxAd3eXBFrD5N4aYERwNzeFWvR8JLMMj0CaeiOGwNS3S5GMWjpOP+MRsEDfBLgy6uGxImMyVbXLlqWntiVRjiq15+wIChyPP02jQi9GCAnuhJ/3i4Q7ezAeKAT0lcoBmoKmDNgD4NmTXMQQRvvOK5QExDous1675wb4GH+GIekaDV/zcc4qO6GNaPKLBu4qEqpN+sLr2nOcAoS7Snzj22q6qpL5wEQK72/GK8TScl7wOjANIU7/AFgqFX6Bc2h1tacMjFqc4QNoo4qNhHYmLy1NnlWYADhLjxxVbJiUwoV94RpR2ZeH1jAvl4+7bRdyH+syEVpHvBZBIAQMb0rQ2XxiCRKOJWQggV5cWUFYKvWJTeIXsKCrdzCc9IBKcc4C9YCAesDLoCXWLZtoOnJ7wMWSXJOXFcmCQ3rHGWJ0DzilEaB/kYhKiQ8NvmYuMKQQPWPOoyKAtXIv42Ah2HzhOxTRkmDf7BBa8GTBiASI+MT4wAV23j4ad2mLP3keblSQ8GKFingOMBIqPk5wHUVW7k3hiNLKlmjHnERCmen3AskTg8/QoiUXXWJjFCjtlMaB8DBnDiV7v+cufgd0NuDeTyqV5yFcAFe2ciuQQ3xcIisYErswH8WBJzldAtBRDDNTUsB6LiuSSINO8X/EkdujrL4KQy79OTaSAG8P/DYNb6efeI4NpNe8OYLRb3dr3inQoi8Yk0yRqZOkwIV/GWZACY/nBAAgmNtYKFe8ic9wJgAQ0GbJTgC/Odp6gpgBAAdH8fk9HGBCwdD6awnHYQ/8YELiwA11ldbduw01iqaSUsH/AIzWEQht2c+M+IMcPzxSqpbjbjznPzoVJ1rJvhQU5nfjH8egg30chaZtxO8beQIh0052nMkdZd8cYCYFZrpuY1BJDIr84Y0y2ol9THTYLchNzHyggIBLwvvEGKAVKOuPeCXWpDh8S3HvilbPdvGMHAqb+5joCImz7msKALkXkx0HsIQn5xPEnHB8zG3fOR6UUpKf6gLwL9DYJLF49YK3aCtd2YnLJd27YBAsSoh1c6Hvf8q8YMBQeo3qTnDVP6wfS8YlhBuF7295yLZEn5GInRsyD1i4rA6gu+cQiZ3J3rme82xGhI947yaDr/il7xSwghfwwSYSNR/+25DKCM8Xl+MMoFLnWtzE6MDfKeMLuDG1Td8YiiFw4aa3ldhaetOPJh/1KKWR1jrBpgdXISBQJfD/ABmm8ygJd/4wA2PU84LGaJ78v4o0pg1G4rbDGKsegwBU41Y4inpI+P5ZvQ8NPhmhXYiDpMV/CN2L3i9NwwV9YuuJcDWdfb7Ad3Nl746vGWvoGFDa4PyLpCSucf5Y4lMji0S2oFvjBL+bVJ3jYNGwR6zaQiO4RU/WK2QGii+cTcLIhVW5GjS7hWsbNNQIx/xk3HQ5FSfvI3fJbW4bsYO1JvDM+6mu2J4jNEVwlySFfjjOcrc4WeY5DtxnT6UjSDf9BIvRMmgMT6RrQhlAm8rVciykxocEOBwwE5pwjj9Y6d6GpJ+sUEIJcD3gAvABLpcSivHy4/WNJ8/HowSbfalQhP1hJiwDdJt/WIaWBoRHNRPjCvWD3B9AJxPAMDZ5xoo6kFX/ALwCEFlR0mnFjblKU4mVjA0Rib9HoCTGnsRC8cYE0UUOj847DkUQpV/GNVQ4L5YjgnQkMwDPxDGmaymliUTDUKBoH1ilgKr1g0jUHDlBDz/DSD8XN+8LIqb4TJ6rTdrhuBl4mJP1hIzCcGnOCE3xoJomR8EAwEGjrAZxAuGubgB3RxyH54xp1kuoXn8YSucBtMrtFBeUL+MXc7dMe5lQtPGYS/8ACDGXD8Ljra9GJubFWe8P+Z3Yjv8AOSP5HQ5wGLAGsY4PeGL4yNn5yjae5l1w/OPiBvETO0tRZ6yuX3I2mAsQfCFlwjI1NV4x3kSB36MeXNOYFhK8ZASeZ/ps/wCh9HDMVCU9YY8W4IU/LAAgMvnFJGB2iYm0/RUmsflUcHOfkNt7kmI8ZRl3xg0IyNl94yw8NquT8YIw5VKXEWhNxoc4e8IPKcmQXA9vNecrVc5ihrN6oIwJhu9ia3ulwJN2YKV/nK4SxEJbjuxaT5YFG0PWpzgtcWjRCRziTeGBQSYN6ihBWnnOZQZvPBrBRskbPzhKvhFhkLgCocYCCCOkwgIOAIH8JsZzlugOwZ4FNni8fONZ6gs3Hj3j8IC/pnjHwmtA4dGs74JMCbhMq+AIW73Oc26QXQ65d4qzuG3DzxjxyVCr9mPXBwietYkKarxnFmJiLQ6l51iWKfFfiYF5Vkg/Wsc7Qk72wyHDCE/7yPDwG0xDOVW79K00GMvC94ritneByue7tglAcIxxa65VXEzBcg6fopbL8uVP4Ipwp8fReiR1dYd6AVHFaE5Vrns13YcX1S3cccPK65p78nWOJSo2OQww9Zg4n0aJO8CHmId3zgy84pPXnAZ0dS8yZvK3pisMPIEZONzG3Iu9e+MXFUNpHGsNIFRS+XWR2iwol5dawZuLymnc+MmtoTnPTDFZqqeUZ5z2JJRE14uSMZzF9uFCnmqNd/PGJuA0ULjXSBVB+cIIL5Lx/BWG8QKNHBNecduBTdZ9GWbOV2YqFSubgXGiym3OcYEg0jEpMUwB2DcdZ4qF2o8eMqJkApfGKtXmNreTBhQgC6BvBJKp+FxSdqk5PWI9XQWfNw5sKma7TDfpDjGa/G77NmAYJI4GQCXQEibe8nz3zinZhjpoU0dGHYjV+44vjODtQ0Z05Gv8RRBnRstrf26xxsGdOcYAkMucTqEN/D6aekE0c/6hs0N8n002AE0ZTV6g0339PAiCX6XsM5Lu7R8mbTrzSnQeM9n/AGa84CYZlYvCeMAIldQ/GN8hFMbw5VyhBRwmc4HQJcdZEKrjWEfgTr4xErEa1Dc+MAl1QUX56wBx0IAtmOV1gSH/AJY5d5ZhU84QUwSFjyztwYj0DZEswB8ToHe/WSpK55KOv1j8412wOMDn68w6TLmzaVF2/jDRMROsLH4bsuDC2lesN4WhwmIEF28f6QanbX7gC7OsHjAjlyYQrcZeCUQ1OMD9UqMmsvCVRb/GbagFrPEx2gBr4NOUmU2llaYOpTsFiHLkzEX4uO1xRLzxEzXiqar+ME3VCAoHBz3kwoh8rMQiCXWP2YTaNa6WavOBQeTWHsdSG+04wUKXgH+cRFyMx9HTQOEp15ZikonOTGl9m78YFZjNyGGIkFd/R5OACTlv+CgIsvP0QbJobxAHKzGfkGOf+/ZJOkK5NMSOT4uD+foeQAMDp4w0CJINHz9A0QWB/wCMIVvUND5yTNI7zxo5VIzZgHaMoEvvHfFaqO5k0rXiBbu+s1y9DnbjGTV/NsFr85rUdSFTmYdCXjGO34zcHVCBdk+MVEE5bcPNUdo7vH5w2F5gZkQww9YhTfD7jlUt1/quP9yx+MP+mTuNYJ+sFaPziOwd1LOjGpHCypyE5yCpJgbvg5uOAL3J87YZFqp1HF8Y9+bzRx2z5xcHy104KInJjdCdrgCJLz9FXlwZ/TjPoq8q4wqRda+jR2lHRcIkmhd4l96nK58OM0Hzi2IBKNdzrHuRqj0cX8YtZTcdWlJlnvNRW01g6qkphNQ6wdwlTp/OMRo5ouzxlVyZrGkATsP4qhwFV6MPjfhMZv6d75mMdHwhiLhrBVo/GAKCZtELfxiHWh99cYJCLCINlMTfYBBdTH1RA8gTq4i1QFPJcXtJzi/4wQawlI+/o2RRnJ5cmYXsHOd6xSh8lc8wnrI7A6v9BtiPi3X0ukoTt7xGwutR7+j0lPOIbFAKR6cZU7cZrrgDa6mMFTBEKNtwD14QkvUw63WWhjOsPGr5UvGDpSnJNN4ZXirUmLwJclW7f3iAVHRq6wmorYmUs/jIW4KioKzTgg6dE2+XFNFUFL+vjK2v1Qn5xCsUvZ1w7wsnq/IFK45aPRQWe0y5RAiqVDX4wzmwIVcKdLoaS4IJgiwtmRd2h0wtA37IWYko8mKIgY+MYuR/pkUfFxkh4v0LRnIwrrqFmjnD5lg94H5wwKb1mtwUAr8YTPc0ELrWdBw3GlNXN8Xl1JtH3mqKyUqdrjOqNbOvNxluQVqtnvCyJLQ4b1iKoQt184TTA1ZD1/q17IZvv7tmlot6+t3MQC0ByvjFUvk4mM1UMINS4oV4W1TjKueTCDw3BJwU4hEMtrdRI1zziOnIJu1kPGHefY/I3H9RIgeuBTKZ5G24QF0JUMPBg2uHjFrXBAlBD1iVRj/TJ2W4KcM+kuzOLjdIJNo8mNkKar5zl/0unNT0mFPnWMnpopq6C4IwENKTtcYsEK3ly6vQhdmssiiCI+JiMsAkjDnAKogVi7cR+Sq5M2cOi3r67UPI4Pu2wtpD+EQCRS6c95UQaSXbUvvEWNUjNMOFFOjarMUINMmvePAsUC0bt3nKGHpdz/OVB/jecYLcCFv0YCSoderrGWzQ3XjgQOd8fXGOic9/0XJc9fSHhmUiA9PPWHOJ1o0WM94usKam/wAYrcQpzWsKWt+DjdZecOXTSaR1c1ZqZJrynvBXMiE0n6xh3lq1BT4xmEPCO/VwkJxnL5tzz/KeMOMgbC/lcFDzhkgx41ZgJmAOO13jlmv/AC2ORzldl04KJz0m+8fPaShxzloTqpsKP6xPIjuqcqPfkSch5xWFb7ZfLYAJnvmaXERRImJBIHhmArAriRj/ADgVhtcRGOsEigw5+hhaBImvOGIFKsDtmIWRADblGegOzEAauEsswpGoDR9/4ziLQYAXTieg+OeXB9/pNwVxmWdTTWKRYHbTb7xYVC+wY/rAsWAuABKbdXrBSDP5tjSI7TvLIawB2ZXEISCw5cdDlYA2lf1gqdgLJ4feElhCog5N5oyTikIfnCgBCEniOTSqCxc4LIcRwNuR8lnRZ25dKUpjPyLXBLEcC8YlUY4qtWv85IKid4lKtXBCFjyeforMwr4OMa/7oCRxu+EfeaTR6l0G/wBY/N1hSIT9YP8Aqn42T/OKEBLmkXnNeVBknv3ll1MWqTtjrE2zwswYIAgNMJUaENmKgyX+gNhD2X6EPUkC/OO6aPE38uHuoARP+8cUY4IKN1hbxmEAwxQepaHHF4wa6dqVLv8AeAhsI4x6zesgi82tZYKxOUwx3ZZ++ACpzFmMSRwyXJDsT4fzOT+CYRAoXb4wghUunB8tN9999ZbnsYsMFSNzoNm8rs7c7U33vDUBu1l350ZnXMzhy0S08OBCcoKQ9cZTgKUQTnI85WVWOSUCWz3zgAQNYTtqsSvn+iDKaP8A0fQxSgckPWMYR0dzC69blGdZFrppJI6nHrJFrwBDa6w3rKfR4W4DO8BUHNv5w2LIUXfjxg8AaAwxDVw0TORzVnwOGhU6MRgROR/nBWGJGOcbmxQ+cZqkBVcNpoHofnEigqifh5xXIwUX78ZMAQsuujFyCpAp42OIQIKeb8XEI7aS6cORQ4XdPTipCSoalPnAimoc4u3Qia+Hr+HdoYx+fuGZdNp9iEVA2uIJKOz7FDn6cKYrrJcgT7cXChb0431BPGs2Y2/4hyX4wyDgHYJTFPSi9QC/4xGdiwhTf5xLSNRscH3pFAhMm9XWOE25xWpDTFgDUEMWjQG2bw05YYF6P5XgHziBBWIOzEYBWCGQPFdxPDhiCAKKechW0EupgfB4YXD/AJXz4W6wKHG+Et3kFpDgNtP3h1p5+NrnNrR51TCg21yDhvX/AJguDTWDVWMfsslD7VADgPP3XTA4+wA4+6bv2nr7lSxyhLmzK2FMEmAgBAwIkQEXWOJCBbc5uFCmipzbXNeQSKAjnQqJKDThyxcTA86wc5wTdk/85Gdip14N4L5rcBBe8IldjE0vWQ8hXm+cOcNC2ZRPH8cUHnBQ5jk8G2YJYAL8U84Z4udTjyF7pA62+sNqUTpeMqjpcLxvP/ASOmb4E5taTOJcvaPj4yqg6hXXvNYDwAa9YVBooomccSAmb9eoFPj7n39sPH3IPJf4pe8Q0uvhMqNL3MaS3AyzesLoslnXXvNXdkbI0PvC+jsTpEL1cUAj6YbDFCmUVF7TWOZqDX/zY3bcOj7xQA4CuDunBiZuXc/mkxVMDHqA5HnGPHa7+bkOuKG35w6glJSYD7QiD0Y8wNWnsvFxxBENTrBsw03RvT7w8pBdTu6zpO7bi9YQesctLmw0nd/qRkEjkwH6Tug5cE2eh3hOgRR1MEs+Y5Zxl6LoJDzkXrCOaG4knJ1WnsmbD0sHl5w/T9If9ZQE4H1Ti85JgY2OImh2CBjgAMTZ/HUBGbx3QCt1kezujt5wn8SxAPvCwEAQE+MeEVoGzZjsPOOSma5qhUiN2d4N089ama+vObzGHf5iweAK+rgkji8v6wrOMXmZWvXnDgwgQOjACEd73lSpHw+cBV2rQp0S5u5im8Id5VAgo0elmUYCEDsTR+MSM5SRnszXWPW4eucUGCiXRiytRZPw4xBIK1/joAlWYzqUZn6tF3ntjMJ5Awe4SmefjFwp1pP5zwowdieMnhywQKE25fqoo5nzkBSpTtbecJlyllydRbVhhtEIfyHLKGb7+7ZpaLevsVGLDjHFiU4evulVXTf1u5Mtrl8zNGQd6+J7MPs6RbnG8pWdDmzLJAqKu+MnHkBIpkQeUhI5tyvGMLfyxFVd1swKGxyav8zuH0x9T1cRxQu0pXAcxiVnuZJfCK2u1wpRFMrSH7wdbJEdcdHCRAl5wYhy5R3lPyOENxWkNfVAKb2dfduIvo+2dh8jr7tsLaQ/lgCQXgvOJyAKniYvGg6S94PdjJpCXDhRsh16MP2NaAr18ZujcKBcFVEkvqfGJhBRQZTEfGrAfOIUFTa8fx2UQHYMpiaZXY2GfOh418fGOoY4Abynea2MUh3rHYEBD/2zxPSCaQMYjADCrTjEVWHpmIjg2CUMUCrDBEo0/rhdcJMExwExbIQHDhwbCHJcXtesi47jT1hOMrz8RpHTvK9jLbNof8Yolo17TBoYW/dMQNisDEGIiPWCRQUOf44KgFXAiiROs9neHV4xFRe0AwwSwWwjxvET2LH0MWnhPIU05TaCahKXIvqHnwrNohqm6xA07DATKCV/rkEFBYd4igpLHrC6IT1Hn5xEy55I6xyAQQQePnFRo90qcTEWORm451lxRUKnLr84OHFHAYGt0tqV9YgaEdOOwZVKuAEFB59/xxREYmKSqr257VX/AMTGVsomA0mBtgHGbrJ+MXzi3hEcjzvDfq0kDWid4OpL3PxjVEJCozWEynzuCaSvMf2DKWXrOka7vEwjt+6Ty4weC405iX/3mqf/AKiYUHLfkP8A1hHnPues2vGPR16yY8m87Tvy8Z7hNfx4jpd5NeTWfufclzsenW+fWdl5Vvy5xMX56b87w/jDO5xcH4pHaOMj0rwyT1g/w0ft/YOwNIDkx2BhFcuAvgR7fPxjMl8wnHe3liReeOcU9hLLKHWV3TfIdELmnoURPkcA6JtVH4csQ9N/c6uAqBtcUqDkcAKChz6/jgqAVcCgkTkz3mmuv3hAtAVuEiYM4x7x6KXlBeTH+yatI8FwYtjhKhSGBG7xv44STW0m18Z4rxFMKJ0eX5fzxGHZtPsQFWBtwA2Ds+41VZr7OVkL4M4+oPzkHjSBkecK9UjyfGcxRya8OMqGIRs0dYwbdMie8VLqkt5/85w0vCQxuga+Zgo06x0qnK4IEFB5/jiiIxMSqrV7z24u2sCgMwpTzhy0CiEMv7NUBbzimhUDYrzhg7AtAI4fKwZujDJVDgVmAupU5bcg0AHkxAI6B9RBR0Pf3EaofaoGPD+WENfYBEYj04AQgHRl1h0CmLXgPCYxRIBsuy47WvUhxc+NY+qAXB6R7yVc01OXdxW37UDR3ilhTowabkIrC84kGN0iX7w4TyBfpCEXfcdYEG8gXAGOOnzhVQ6R/wB4AnR2+MSDG6RLiWQHCc/Q6Uut67wK0njX3AQaF24QQqXT5zse3/0c1rXewuRz4SZiZKmEyzVyGcUdKJH3jac8KoE94G0hAbrzgw7kFl8Y3QOQUw0IOAIZB6+s+59/bP59nCheHJOkC8uGQ+lHWaygeasXWU7zlpW3jNuwDXs4/OLKKJursmP43BuF4tqQPvIyxnn/AE+sggr4MCokTBkHPhrAgCroMSoDkcEigoc/6gk1EA7cUOHkecf0BYaO83uFJSb36x2kACjRtp5w6GjNwawH7OyUdDEJgUYG94F+cLa/rlnpJ4DI8hRkyG6M08f/ALlQ4IS1nGTWaS21p0Zx4nM4nV44yiQGq38+ca0pUjz84hJpIJ+sCOXVG6flMGNxnUr4+xUEjzT6LuAhNEwICCSTZOMcE0aQiUm3vAzUgPZ6cv8ALAwPgxThiQTu+2DmsDRRuzFn5sH6jBdWD6l26xQJ1kNkHUhmhFE2X6KxQITRMVkBZNl+qAJRuM6lW5742/8AZhtCACR7M6FaMPwYiIyt2c+ecPAofTdN5RQAzqj3ipAt11PMwTbQ480nrNGOkF51nEPhSmJCtv8AWiTQiYJMAQDKcJt5c4kMA9D3iy+K7S6MngeT4D/vCyR0cw+co1ioEh7yhzQDw9Y6uy1PymBWYjqKY4QhF2/RnFH4cYEACixfj6ejik7dPvB4VqRosrmqVEo0c5RQIdR+e8CnBLZVnvFKDDTZ+MJKgV6a5w96Ws6feE+LbqrxrO6j52d3eCQENuivOQ6wABbrWCx9Qjh1cdOI6j+VL1jLAKlDX0WGyOpd5IEq4zqKM1ng3xd/rAKZxYU8rih8kAfyYHlV2ytO+5jV5humITBmRYuKhN4AgSe9zKk4PzW4amevDMEqCB0f1yLaD8Omriabpwp/lkuqbYHHTvmYwr39DdN/LHM5iA8pHCXvmB+zATG5WUwOw4eWKQnl5f6MWxdl7MVHJUNxm8DFc3FMHedSCDGYs1037YpOdiclmPyZfKOXIpfYHrJH3R8GSbsE2vjH5CgEUwNGCw4+kn+iUkHBP7YiLsAvbvFXY6Nr8u8HBgSH87xZB8T/AKbgdu8krq7kz/rQtnPfr/N/nXc+09fcI8N+oFQSnJhhnEdBh+DqLcJH7C8TzhxdYQ1OMse9ibOnBDDpGtD/ANYJG65ppyay1hqJKJ3kApE5p6yYjT3cOcdGS5qwzL4x6SxswQCYhjcsxDj2YKBB073xixByPE50YeogMcb6waUAJAOsDLLKaWtmsg8QAaJdQMMsQFRo3hMY8FdpwSzD8IgLv1rBNorq4TliqiytEk5kw3sr0C5FMt931xnFEydol2e8IkjWcGOM1BDUlZho3wBSXFU8XBnRa+1xQPMxUeLniOecAhBt8MeMIOO9Rj5vrLsd8e8NJDUuzbkSkEImj38YJrcTQe8qR8NbOLk3HVPnBDnj7M/x4u/rQ5fuWG/tp5/gBMGxF+wARKOnAAIGg+4WGC36kcIi8zKvjH0mCbNAL+8S228K1L8TGs9TXYNd4l4iHADp1lcYge0P+8JNsCSTrzllvaIhdub5qgGrpzW2vvHxiGYUGMGmK6PxhkGglbmjFDA5vFWYMn+rBe8VG5kLPOGQg71zNYabmlIzcnOOToQMjG4v4wuaIdect+9Uip5zm6t2h0+MvTHnFeS45vdNqjnnAA1TuEu54xMPE4ie8Q1oHYl1HN1yaJAjJ+cfWtBAIHJ7zhbETE1u8ZN5tnntyT77k1rrKui1HBcdQNFRTxigpVxnkxQVwXDHYTNVFPGe2s7P1jrgAVAvnF2TFdMVmZEFC/8AjN7418yzWSbjZHrZ+8uQ4pNvEc33B7lwzrjJcx4zUOYvLiQzB22fVQFdj19xMFPtUBeB8fzkWIDvzjZA05A0YBl7HT9YPh6gZhU31l8RlQM3d4kv6gVOdriJE0mAxrgK6e/OcKaFiYkcqpVzsHazrD1zjSbe1wLnQCx+cZSpdTm4OlwkrPVwRma4JgKlAT5GHB0Lwdcu8nL2pj635yevkYWzQXi5sjJUh5m8PAXXpTZ+cZGvOBXV3lIk+lp4wswJpRmpvxiolA9GcXDRpQu6TXfjEVhwUaXVw8BVY1m7vDJ2boHPlrNkskcR742bE+cUkENDU3ZibJp9994zpsQx8YVUg4eWMW1NV5z5MJokHCYwWq5XOfKInyGFiIx36cYnYXy65ciemAflXAb7mAflMxO/NACbnJk3dyDdxwFBlI9f1lwMwKlAMLMnCxMS8pUoHO+s3Y4gdOsOVpJFOtuQFZoTY8Y3YQBRz9s3KrscGtmbsM7kzi4fkFvddEzccK0pmzX9lhlUTVzDwXrBFUUlm9axQknk1rWO+9IqfLzj3cVoEAPreOiy+XTxxjRU2gG+8qjQlOBK5eoRBpjVGbTpraYfO5ItcPrKbBi3qYQ8wRbPXOVY6IGv5wf8ENSYhPJU6nDihuqCrTjJLSjhHzgKIiYrZfHGH4eOoo9cYoQEAhvzjl1boK85EXgLBK4g++R0vDloDP58/M/bxtJxxm0WJyTsuVvrmR+XKcJKvMd4iUXcCvMyjbhHA8Yoyc6B9mLBtNJ4jicFlYj+8ITtfGYkGT8t/wBYFd4axfhDkBM+Z7dlVZIEogTBNBQKRQ4cHhz0VfK5pb5bbfP7w7WXlE+MkrrFQIXL1bB0ddZ13dljy/zh3sU8AC40PSF1ZvHg3K1JS4YRy/cN6yCp0fHkmFNikiAUn7wGS0ypNOC/B05e8FJ3z8HrLZDG5NMJ66v0YTqG5J3jnh9OmNjhYgIemBoC87mIJrwbHD/SQ8SYs1rPZ5MN0FfA+8gJoG/rFTyr9vD1lwRgAFPOEYSHgCP+sJMBTmlzhdCXWuCAud64OZ43e/OCfIWs/WKAYC4G5vKsibSoeMJEciwLZ+sOMMUkLjqJ6uxJ/wCcs1ysRikV0tGm8U4UGOmTn9YR+uOB5QgfD+iSJCocecahSk48fcgVOkfrFYI7abg/VPMwxYC6ry4xu3KNyJ8YwBFglnPGEgTCyLneTjYTJl5wdDFPb3l8x0v/AFjpdtlwDzZFiePjGxeMBB+THFgNmB4DG7zolRJic1HOrnnjN/HmD/I4x/BIEENEcTQIpSpK3jNIpSfm+co4jF43K0wUJwLiazKFi4KPhcUBhxg9EBAD2/R/jA6IfJgd3wIf84r8wr7TjL5jok0wHT1X+/vJum0RxzR0po14Hgxm7RC7c07wF1QOaqjed4N2EFSOtnOa2wSCJJYbyj4F5L5xigHAAz12lqzCe62FxWlil4PnCe7GPGQTjQovvHC+ESXzhpeTRPz5yyD6kquDJhVA4cmCiiDs8mcLrm6XEiQqHHnHVGlV1iACR5fH3NpR8f0erhwJo6JhCoemZPoRxUm8EibCA6wIW6IdmtOSM7kECl/xc5oHQrnVLghgkBHdrnAkveDv4wA5mIOA/wA4SqBp7PF51MH14wne2YvG+II6xSZKkZ2mAU5Kk/WCgZNM01m8KLJp8YfiZ6MCiOnTFkQR3PoAECH3AFQK4UBXbpkgQ8AmPDjRQ0wlLj0zCZbYylu9/OKBnwhYecGSBchJMEhoeFkeMCIwaRo7PFyd/kQ2584dzPXdJvOd46ANNcZzkogjuQudeKtOWq4vyaGfRzMvZooLfeWLFiierHXNOAPWGSmjjMXt7E3/AFiUwAW6fGMrS2RTF0l2kPBi2/SugNHi40Kd7A44wI3x6Tz6yUJaK0oV/eEyMNXjxkya7FFbGYG48VdmbwWwq183xMeHLVEp38ZqIPG3vRxm17FPdODWM9ilznPDHziul8mEVrClbOPjNofmroGjC2QOT4MM43ZqxI20Dt7foISr84l7T7bmlWPXxhPA3CfBlNgy1Xzg2jwvuuzBKe8T4MCVico2XX7w4a+p/jjcL8Jeu3NIaeIPbTFq/LLvqdYP9R+3iTFA2CjAdfvK5R10fObd98nxcRZTSwDFwpN9yrwM23hHg+SYukNMaTnzh5IK6xOc39ZVfgYStqOxO5iUTjJBVnb/AFROWYpPOCIikVYcazptOon7xMQgnzCTWP8AvgCU5dYbYg5G9aMMwMciovXrFZyYMo5dYhNFBiWt1l5MBWa1rFHvllnmZuZSqFTOMeo3gkLrjDdAkkRlTF/uBma76yNfaLbm+0duSlyk+BeNYCLgwmtP9JQFePpoVsXjrLPgXCVqSudMzR3GxA9uBHUSPOsVHRG2TzMhOh0aTjjB7S7K2cYMo2h1QI69ZG0VIB42YwgIEZHHWLWXpgo+PWDuAIzpDZk1JKAjxDB4ZVdO1SXGZACrsfxrKBiMEbmpEoNN++MWFcABw/1ULZvDeFicJhFUgEAxpwwho840oFQaJikMgB25MIwVkIJT7x581jRhxmACoaGbdBoK/wD6yGvmSJldkL2bvCiKz2DhwIADwGJIBcoYAgE94EIZDmF/gABAhiwgpwpk1MQEOSEuMmlBsc/wsms3UvYUg0+MfdeRArTBtiAERMSzQ51TcyYTZAKRZh25SDcjXFi1h6ZTHDx7DxmLOi+Zv+sApKkPGNvGNlJpw6AbS1/ODwYCpo/5xf1KY4cYjLFqlenCcFbqkTl7zTZlSud+cfn2hjfI94BAgI4bwxSn/wDs2+coP6yDV1fnKrRCwdaziwApVwt8o7EPB1goVL2YaJ/C8FMKX047JmprqU+BkuVRdGcYd9exviXHYtdIIGx7w7rwVH4xqUsSqdeJjrhRAXhe8LioihOHX+c5FPTfwuRrUOwduP8AsFE/cyZCDl3XzhbQCjH8fQ/pxFPM+oTsRda3jlohwqB6wQwVIk+HEKgWE6HnGzTsKzCVuRX/AMsZzRQTRD3zzh+J5Cs+MPXMqNDLXHaJyYbZtOMWFy+8ZX2Gd5r8AaO3BpfuAU+wYvbPuJuAw2fYhF5WH0GqeM2+NUnfv6MWt5QIunvIhK0dP4wQ4poPHjLypKgozHHtBZu+04wRA7GR+83QPWRtJ/7znLSZfozveYB58Z4ZPFP39DZggPLx/VH2Co7MHsGB0YlaCMbB5zoqEJPGcbCDhgK5RzQecHkSJwmbacjhXlx1a1Jw/QA4A/mAKTqO3KtXophsIBD4whLwzbnFJ10cA4s4BkdAqbHjOSgHA4b45wjIWzf9aGTIbJQcBJkNgguMMyNja9RxBLQSg+zDUfohxwsE/oEcoSCNLxmxonQbaJhQSGlp1/OL3PWEnRKjLjRZtPOAaU0QH5xQgmsN+MITRoQXKyWIcW+b4mFAoNhQcJDTVgvo/wDhEA4/pwAh/XNEioaPONQiKbPH3UFF4+wnYMd8femlHj7GNisd8Hn7mLA4POcm9fYxyDHfH3JLR4w4+3pm8QWhyeP/AOAokt2zR952LPZ9hbrtCH3GtoeC4bL9hMN2hD/5d//Z"

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
    {"id": "bloomberg",   "handle": "Bloomberg",          "channel_id": "UCIALMKvObZNtJ6AmdCLP7Lg", "label": "Bloomberg",       "lang": "EN", "region": "Global"},
    {"id": "cnbc",        "handle": "CNBC",               "channel_id": "UCvJJ_dzjViJCoLf5uKUTwoA", "label": "CNBC",            "lang": "EN", "region": "US"},
    {"id": "yahoofi",     "handle": "yahoofi",            "channel_id": "UCEAZeUIeJs0IjQiqTCdVSIg", "label": "Yahoo Finance",   "lang": "EN", "region": "Global"},
    {"id": "reuters",     "handle": "Reuters",            "channel_id": "UChqUTb7kYRX8-EiaN3XFrSQ", "label": "Reuters",         "lang": "EN", "region": "Global"},
    {"id": "aljazeera",   "handle": "aljazeeraenglish",   "channel_id": "UCNye-wNBqNL5ZzHSJj3l8Bg", "label": "Al Jazeera",      "lang": "EN", "region": "Global"},
    {"id": "skynews",     "handle": "SkyNews",            "channel_id": "UCoMdktPbSTixAyNGwb-UYkQ", "label": "Sky News",        "lang": "EN", "region": "UK"},
    {"id": "dwnews",      "handle": "DWNews",             "channel_id": "UCknLrEdhRCp1aegoMqRaCZg", "label": "DW News",         "lang": "EN", "region": "EU"},
    {"id": "wion",        "handle": "WION",               "channel_id": "UC_gUM8rL-Lrg6O3adPW9K1g", "label": "WION",            "lang": "EN", "region": "India"},
    {"id": "cnbctv18",    "handle": "cnbctv18",           "channel_id": "UCmRbHAgG2k2vDUvb3xsEunQ", "label": "CNBC TV18",       "lang": "EN", "region": "India"},
    {"id": "foxbusiness", "handle": "FoxBusiness",        "channel_id": "UCCXoCcu9Rp7NPbTzIvogpZg", "label": "Fox Business",    "lang": "EN", "region": "US"},
]

# Map handle -> channel_id for quick lookup
_HANDLE_TO_CHANNEL_ID = {ch["handle"]: ch["channel_id"] for ch in NEWS_CHANNELS}
_YT_HDR = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.youtube.com/"
}
 
 

def fetch_live_video_id(handle):
    """
    Returns (video_id, is_live).

    ONLY serves videos from the official channel identified by channel_id.
    Never returns videos from other channels.

    Strategy:
      1. Fetch the channel RSS feed (feeds/videos.xml?channel_id=...).
         This is pure XML — guaranteed to contain ONLY this channel's own videos.
         Extract all video IDs from it (up to 15 most recent).
      2. For each video ID from RSS, check if it is currently live by hitting
         youtube.com/watch?v=ID and looking for live signals in the response.
         Use the FIRST live video found.
      3. If no live video found in RSS, return the first (latest) video from RSS.
      4. Emergency fallback only if RSS fails: hit /channel/{id}/live and verify
         the redirected video ID actually belongs to this channel via RSS list.
    """
    def _get(u):
        return requests.get(u, headers=_YT_HDR, timeout=12, allow_redirects=True)

    channel_id = _HANDLE_TO_CHANNEL_ID.get(handle)
    if not channel_id:
        return None, False

    # ── Step 1: Fetch RSS — the only source of this channel's own video IDs ──
    rss_video_ids = []
    try:
        rss_url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
        r = _get(rss_url)
        if r.status_code == 200:
            # Extract ALL video IDs in order (most recent first)
            rss_video_ids = re.findall(r'<yt:videoId>([A-Za-z0-9_-]{11})</yt:videoId>', r.text)
    except Exception:
        pass

    # ── Step 2: Check each RSS video for live status (check top 5 only) ─────
    # We check up to 5 most recent because live streams are almost always recent
    for vid_id in rss_video_ids[:5]:
        try:
            watch_r = _get(f"https://www.youtube.com/watch?v={vid_id}")
            text = watch_r.text
            if ('"isLive":true' in text or
                '"liveBroadcastContent":"live"' in text or
                '"broadcastType":"LIVE"' in text or
                '"isLiveBroadcast":true' in text):
                return vid_id, True
        except Exception:
            continue

    # ── Step 3: No live found — return latest video from RSS ─────────────────
    if rss_video_ids:
        return rss_video_ids[0], False

    # ── Step 4: RSS failed — emergency fallback via /channel/{id}/live ───────
    # IMPORTANT: we only accept the video if its ID is NOT from a different channel.
    # Since we have no RSS to cross-check, we verify via oEmbed that the video
    # exists and is embeddable (if it 404s, it's likely a redirect to homepage).
    try:
        r = _get(f"https://www.youtube.com/channel/{channel_id}/live")
        # Only trust the URL redirect (not page source, which has recommendations)
        m = re.search(r'[?&]v=([A-Za-z0-9_-]{11})', r.url)
        if m:
            vid_id = m.group(1)
            # Verify this video is embeddable (rejects geo-blocked / wrong channel redirects)
            oe = requests.get(
                f"https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v={vid_id}&format=json",
                headers=_YT_HDR, timeout=6
            )
            if oe.status_code == 200:
                text = r.text
                is_live = ('"isLive":true' in text or
                           '"liveBroadcastContent":"live"' in text)
                return vid_id, is_live
    except Exception:
        pass

    return None, False
 
 
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
 
 
def build_analysis_payload(ticker, period, name, df, macro_data=None, trends_data=None, fundamentals=None, shipping_ctx=None, live_price_data=None):
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

    # ── LIVE PRICE OVERRIDE (Alpaca / yfinance fast_info) ──────────────────
    # Replace the yfinance historical close with the freshest available price
    # so the AI always sees the current market price, not a stale EOD bar.
    _live = live_price_data or {}
    live_price   = _live.get("price")
    live_bid     = _live.get("bid")
    live_ask     = _live.get("ask")
    live_spread  = _live.get("spread")
    live_vol     = _live.get("volume")
    live_dtype   = _live.get("data_type", "HIST")
    live_source  = _live.get("source", "yfinance history")
    live_ts      = _live.get("timestamp", "")
    live_bid_sz  = _live.get("bid_size")
    live_ask_sz  = _live.get("ask_size")

    if live_price and abs(live_price - (cur or 0)) / max(cur or 1, 1) < 0.40:
        # Only use live price if it's within 40% of the last historical close
        # (guards against ticker mismatches or stale WebSocket entries)
        cur = _sf(live_price)
    # ── END LIVE PRICE OVERRIDE ─────────────────────────────────────────────

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
        "live": {
            "price":    live_price,
            "bid":      live_bid,
            "ask":      live_ask,
            "spread":   live_spread,
            "bid_size": live_bid_sz,
            "ask_size": live_ask_sz,
            "volume":   live_vol,
            "data_type": live_dtype,
            "source":   live_source,
            "timestamp": live_ts,
        },
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
    live     = p.get("live", {})

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

    # ── REAL-TIME LIVE PRICE (Alpaca / yfinance fast_info) ──────────────────
    live_lines = []
    if live and live.get("price"):
        lp      = live["price"]
        l_bid   = live.get("bid")
        l_ask   = live.get("ask")
        l_sp    = live.get("spread")
        l_bsz   = live.get("bid_size")
        l_asz   = live.get("ask_size")
        l_vol   = live.get("volume")
        l_dtype = live.get("data_type", "?")
        l_src   = live.get("source", "")
        l_ts    = live.get("timestamp", "")
        hist_close = _sf(p["price"].get("prev")) if p.get("price") else None
        drift = ""
        if hist_close and hist_close != 0:
            drift_pct = (lp - hist_close) / hist_close * 100
            drift = f"  |  vs last hist close: {'+' if drift_pct >= 0 else ''}{drift_pct:.2f}%"
        live_lines = [
            "## REAL-TIME LIVE PRICE  ← USE THIS AS THE DEFINITIVE CURRENT PRICE",
            f"- Price: {p['currency']} {f(lp)}  [{l_dtype}]{drift}",
            f"- Source: {l_src}" + (f"  |  Timestamp: {l_ts}" if l_ts else ""),
        ]
        if l_bid or l_ask:
            live_lines += [
                f"- Bid: {f(l_bid)}" + (f"  (size: {l_bsz})" if l_bsz else "") +
                f"   Ask: {f(l_ask)}" + (f"  (size: {l_asz})" if l_asz else "") +
                (f"   Spread: {f(l_sp)}" if l_sp is not None else ""),
            ]
        if l_vol:
            live_lines.append(f"- Intraday volume so far: {int(l_vol):,}")
        live_lines += [
            "NOTE: The real-time price above supersedes the 'current' price in the PRICE SNAPSHOT below.",
            "Use this price for entry/stop/target calculations, not the historical close.",
            "",
        ]
    # ── END REAL-TIME LIVE PRICE ─────────────────────────────────────────────

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
    ] + data_quality_lines + live_lines + [
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
# CHART BUILDER — shadcn Stock Market Tracker visual style
# ══════════════════════════════════════════════════════════════════════════════
_C = {
    # Price line (blue, matches ChartTooltipContent cursor + Line stroke in prompt)
    "line":    "#3b82f6",
    "dot_act": "#3b82f6",
    # Sub-panel indicators
    "sma20":   "#f9a825", "sma50": "#7b1fa2", "sma200": "#1565c0",
    "bb_u":    "rgba(59,130,246,0.55)", "bb_l": "rgba(59,130,246,0.55)",
    "bb_f":    "rgba(59,130,246,0.04)",
    "rsi":     "#7e57c2",
    "rsi_ob":  "rgba(239,83,80,0.07)", "rsi_os": "rgba(38,166,154,0.07)",
    "macd":    "#2196f3", "sig": "#ff6d00",
    "hp":      "rgba(38,166,154,0.85)", "hn": "rgba(239,83,80,0.85)",
    "vu":      "rgba(38,166,154,0.55)", "vd": "rgba(239,83,80,0.55)",
    # Candlestick colours kept for candlestick mode
    "cs_up":   "#26a69a", "cs_dn": "#ef5350",
    # Layout
    "bg":      "rgba(0,0,0,0)", "paper": "rgba(0,0,0,0)",
    "grid":    "rgba(229,229,229,0.8)",   # light horizontal-only grid
    "axis":    "#888888", "text": "#888888",
}


def build_chart(ticker, period, chart_type, indicators):
    data, err = fetch_yfinance_data(ticker, period)
    if err: return None, f"Data error: {err}"
    if data is None or data.empty: return None, f"No data for '{ticker}'. Use .NS for NSE stocks."
    missing = {"Open","High","Low","Close"} - set(data.columns)
    if missing: return None, f"Missing: {missing}"
    data = data.dropna(subset=["Close"])
    if len(data) < 5: return None, "Not enough data points."

    cl  = data["Close"].squeeze()
    hi  = data["High"].squeeze()
    lo  = data["Low"].squeeze()
    op  = data["Open"].squeeze()
    vol = data["Volume"].squeeze() if "Volume" in data.columns else None
    dates = data.index
    name  = _get_name(ticker)

    sv = "vol" in indicators and vol is not None
    sr = "rsi" in indicators
    sm = "macd" in indicators
    rows = 1 + int(sv) + int(sr) + int(sm)
    rh   = {1:[1.0],2:[0.62,0.38],3:[0.54,0.23,0.23],4:[0.48,0.18,0.17,0.17]}.get(rows,[0.48,0.18,0.17,0.17])
    titles = [""]   # main panel — no subplot title (price info shown in HTML header above)
    if sv: titles.append("Volume")
    if sr: titles.append("RSI (14)")
    if sm: titles.append("MACD")

    fig = make_subplots(rows=rows, cols=1, shared_xaxes=True,
                        vertical_spacing=0.025, row_heights=rh,
                        subplot_titles=titles)

    rv = 2 if sv else None
    rr = (2+int(sv)) if sr else None
    rm = (2+int(sv)+int(sr)) if sm else None

    # ── Main price trace ──────────────────────────────────────────────────────
    if chart_type == "candlestick":
        fig.add_trace(go.Candlestick(
            x=dates, open=op, high=hi, low=lo, close=cl, name="Price",
            increasing_line_color=_C["cs_up"],  increasing_fillcolor="rgba(38,166,154,.15)",
            decreasing_line_color=_C["cs_dn"],  decreasing_fillcolor="rgba(239,83,80,.15)",
            line=dict(width=1),
        ), row=1, col=1)
    else:
        # Clean blue line — NO fill, matching the prompt exactly
        fig.add_trace(go.Scatter(
            x=dates, y=cl, mode="lines", name="Price",
            line=dict(color=_C["line"], width=2),
            # Blue dot on hover (activeDot in prompt: r=4, fill=#3b82f6, stroke=white)
            marker=dict(color=_C["dot_act"], size=7,
                        line=dict(color="#ffffff", width=2)),
        ), row=1, col=1)

    # ── Overlays ─────────────────────────────────────────────────────────────
    if "sma" in indicators:
        for w, color, lbl in [(20, _C["sma20"], "SMA 20"),
                               (50, _C["sma50"], "SMA 50"),
                               (200, _C["sma200"], "SMA 200")]:
            if len(cl) >= w:
                fig.add_trace(go.Scatter(
                    x=dates, y=calc_sma(cl, w), mode="lines", name=lbl,
                    line=dict(color=color, width=1.2), opacity=0.85,
                ), row=1, col=1)

    if "bb" in indicators and len(cl) >= 20:
        bbu, bbm, bbl = calc_bb(cl)
        fig.add_trace(go.Scatter(x=dates, y=bbu, mode="lines", name="BB Upper",
            line=dict(color=_C["bb_u"], width=1, dash="dot")), row=1, col=1)
        fig.add_trace(go.Scatter(x=dates, y=bbl, mode="lines", name="BB Lower",
            line=dict(color=_C["bb_l"], width=1, dash="dot"),
            fill="tonexty", fillcolor=_C["bb_f"]), row=1, col=1)

    # ── Sub-panels ───────────────────────────────────────────────────────────
    if sv and vol is not None:
        colors = [_C["vu"] if c >= o else _C["vd"] for c, o in zip(cl, op)]
        fig.add_trace(go.Bar(x=dates, y=vol, name="Volume",
            marker_color=colors, showlegend=False), row=rv, col=1)

    if sr and len(cl) >= 15:
        rv2 = calc_rsi(cl)
        fig.add_trace(go.Scatter(x=dates, y=rv2, mode="lines", name="RSI",
            line=dict(color=_C["rsi"], width=1.5), showlegend=False), row=rr, col=1)
        fig.add_hrect(y0=70, y1=100, row=rr, col=1, fillcolor=_C["rsi_ob"], line_width=0, layer="below")
        fig.add_hrect(y0=0,  y1=30,  row=rr, col=1, fillcolor=_C["rsi_os"], line_width=0, layer="below")
        for lvl, c in [(70, "rgba(239,83,80,.45)"), (30, "rgba(38,166,154,.45)"), (50, "rgba(136,136,136,.3)")]:
            fig.add_hline(y=lvl, row=rr, col=1, line=dict(color=c, width=0.8, dash="dash"))

    if sm and len(cl) >= 27:
        ml, sl, hl = calc_macd(cl)
        hc = [_C["hp"] if v >= 0 else _C["hn"] for v in hl.fillna(0)]
        fig.add_trace(go.Bar(x=dates, y=hl, name="Hist",
            marker_color=hc, showlegend=False), row=rm, col=1)
        fig.add_trace(go.Scatter(x=dates, y=ml, mode="lines", name="MACD",
            line=dict(color=_C["macd"], width=1.5), showlegend=False), row=rm, col=1)
        fig.add_trace(go.Scatter(x=dates, y=sl, mode="lines", name="Signal",
            line=dict(color=_C["sig"], width=1.5), showlegend=False), row=rm, col=1)
        fig.add_hline(y=0, row=rm, col=1,
            line=dict(color="rgba(136,136,136,.35)", width=0.8, dash="dash"))

    # ── Axes — horizontal grid only, clean ticks, no border lines ────────────
    # Main price Y-axis: add 2% padding so line never kisses the edge
    y_pad = (float(cl.max()) - float(cl.min())) * 0.04
    main_yrange = [float(cl.min()) - y_pad, float(cl.max()) + y_pad]

    ax_common = dict(
        gridcolor=_C["grid"],
        gridwidth=1,
        showgrid=True,
        zeroline=False,
        showline=False,
        tickfont=dict(size=9, color=_C["text"], family="'DM Mono', monospace"),
        color=_C["axis"],
    )
    ax_no_grid = {**ax_common, "showgrid": False}

    fig.update_layout(
        height=225 + 110 * (rows - 1),   # 225 px for main panel (matches prompt h-[225px])
        plot_bgcolor=_C["bg"],
        paper_bgcolor=_C["paper"],
        font=dict(color=_C["text"], family="'DM Sans', sans-serif", size=10),
        legend=dict(
            orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0,
            bgcolor="rgba(0,0,0,0)", font=dict(size=9, color=_C["text"]),
        ),
        hovermode="x unified",
        margin=dict(l=48, r=8, t=8, b=28),
        hoverlabel=dict(
            bgcolor="rgba(255,255,255,0.97)",
            bordercolor="rgba(120,123,134,0.3)",
            font=dict(color="#000", size=11),
        ),
        xaxis_rangeslider_visible=False,
        dragmode="pan",
    )

    # Apply axis styles per panel
    for i in range(1, rows + 1):
        xkey = "xaxis" if i == 1 else f"xaxis{i}"
        ykey = "yaxis" if i == 1 else f"yaxis{i}"
        fig.update_layout(**{xkey: {**ax_no_grid, "rangeslider": {"visible": False}}})
        fig.update_layout(**{ykey: {**ax_common}})

    # Pin main Y range
    fig.update_layout(yaxis=dict(range=main_yrange))

    # RSI fixed 0-100 range
    if sr and rr:
        rr_key = "yaxis" if rr == 1 else f"yaxis{rr}"
        fig.update_layout(**{rr_key: {**ax_common, "range": [0, 100]}})

    # Clear subplot title fonts (we hide the main one; style the sub-panel labels)
    for ann in fig.layout.annotations:
        ann.font.color = "#aaaaaa"
        ann.font.size  = 8

    return pyo.plot(fig, output_type="div", include_plotlyjs=False), None
 
 
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
  <title>STARFISH</title>
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

    /* Crypto card styling — CoinGecko-only, no bid/ask */
    .crypto-grid{{grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:14px}}
    .crypto-card{{position:relative;overflow:hidden;background:
        radial-gradient(circle at top left, rgba(246,178,49,.16), transparent 32%),
        linear-gradient(180deg, #111827 0%, #0b1020 100%);
        border:1px solid rgba(255,255,255,.08);
        border-radius:22px;
        padding:18px;
        color:#e5e7eb;
        box-shadow:0 20px 42px rgba(0,0,0,.22);
        transition:transform .18s ease, box-shadow .18s ease, border-color .18s ease, border-radius .18s ease;
        animation:card-in .3s ease both}}
    .crypto-card::before{{content:'';position:absolute;inset:0 0 auto 0;height:2px;
        background:linear-gradient(90deg, transparent, rgba(246,178,49,.7), transparent);opacity:.9}}
    .crypto-card:hover{{transform:translateY(-2px);box-shadow:0 24px 54px rgba(0,0,0,.28);border-color:rgba(247,147,26,.36)}}
    .crypto-card.up{{border-left:3px solid #26a69a}}
    .crypto-card.down{{border-left:3px solid #ef5350}}
    .crypto-top{{display:flex;align-items:flex-start;justify-content:space-between;gap:12px;margin-bottom:14px}}
    .crypto-card-sym{{font-size:1.2rem;font-weight:800;letter-spacing:.08em;color:#fff}}
    .crypto-card-name{{font-size:.78rem;color:#9ca3af;margin-top:4px}}
    .crypto-source-pill{{font-size:.55rem;font-weight:700;letter-spacing:.12em;text-transform:uppercase;padding:4px 8px;border-radius:999px;background:rgba(247,147,26,.12);color:#f6b23a;border:1px solid rgba(247,147,26,.24);white-space:nowrap}}
    .crypto-price-row{{display:flex;justify-content:space-between;align-items:flex-end;gap:12px;margin-bottom:14px;padding:12px 14px;border-radius:16px;background:rgba(255,255,255,.03);border:1px solid rgba(255,255,255,.05)}}
    .crypto-price{{font-size:1.45rem;font-weight:800;letter-spacing:-.02em;color:#fff;line-height:1.05}}
    .crypto-card.up .crypto-price{{color:#7be0c3}}
    .crypto-card.down .crypto-price{{color:#ff8d8d}}
    .crypto-change{{font-size:.76rem;font-weight:700;font-family:'DM Mono',monospace;white-space:nowrap;padding:6px 10px;border-radius:999px;background:rgba(255,255,255,.05);border:1px solid rgba(255,255,255,.06)}}
    .crypto-change.up-t{{color:#26a69a}}
    .crypto-change.down-t{{color:#ef5350}}
    .crypto-change.flat-t{{color:#9ca3af}}
    .crypto-stats{{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;margin-top:8px}}
    .crypto-stat{{background:rgba(255,255,255,.045);border:1px solid rgba(255,255,255,.07);border-radius:14px;padding:10px 11px;min-height:64px;box-shadow:inset 0 1px 0 rgba(255,255,255,.04)}}
    .crypto-stat-label{{display:block;font-size:.56rem;letter-spacing:.12em;text-transform:uppercase;color:#9ca3af;margin-bottom:8px}}
    .crypto-stat-value{{display:block;font-size:.9rem;font-weight:700;color:#fff;line-height:1.25;word-break:break-word}}
    .crypto-footer{{display:flex;justify-content:space-between;align-items:center;gap:10px;margin-top:12px;padding-top:12px;border-top:1px solid rgba(255,255,255,.08)}}
    .crypto-source{{font-size:.68rem;font-weight:700;letter-spacing:.12em;text-transform:uppercase;color:#f6b23a}}
    /* Alpaca status bar */
    .alpaca-status{{display:flex;align-items:center;gap:8px;margin-top:16px;padding-top:14px;border-top:1px solid #e5e5e5}}
    .alpaca-led{{width:8px;height:8px;border-radius:50%;background:#44cc44;flex-shrink:0;animation:pulse 2s ease-in-out infinite}}
    .alpaca-led.closed{{background:#f5a623;animation:none}}
    @keyframes pulse{{0%,100%{{opacity:1;transform:scale(1)}}50%{{opacity:.4;transform:scale(.8)}}}}
    .alpaca-status-text{{font-size:.6rem;color:#888;font-family:'DM Mono',monospace}}
    .market-pill{{display:inline-flex;align-items:center;gap:5px;font-family:'DM Mono',monospace;
                  font-size:.52rem;font-weight:700;letter-spacing:.12em;text-transform:uppercase;
                  padding:3px 9px;border-radius:20px;white-space:nowrap;flex-shrink:0}}
    .market-pill.open{{background:#e8f5e9;color:#2e7d32;border:1px solid #2e7d32}}
    .market-pill.closed{{background:#fff8e1;color:#e65100;border:1px solid #e65100}}
    .market-pill.pre{{background:#e3f2fd;color:#1565c0;border:1px solid #1565c0}}
    .market-pill-dot{{width:5px;height:5px;border-radius:50%;flex-shrink:0}}
 
    /* ── TICKER STRIP ── */
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
    .t-up{{color:#26a69a !important}}
    .t-down{{color:#ef5350 !important}}
    @keyframes ticker-run{{from{{transform:translate3d(0,0,0)}}to{{transform:translate3d(-50%,0,0)}}}}
 
    /* ── LAYOUT ── */
    main{{position:relative;z-index:1;max-width:1200px;margin:0 auto;padding:30px 20px 64px}}
    .glass{{background:#f8f7f4;border:2px solid #000;border-radius:var(--r);contain:layout style}}
    .panel{{padding:26px 30px;margin-bottom:18px}}
    .section-divider{{display:flex;align-items:center;gap:14px;margin:36px 0 20px}}
    .section-divider-line{{flex:1;height:1px;background:#e5e5e5}}
    .section-label{{font-size:.6rem;font-weight:700;letter-spacing:.22em;text-transform:uppercase;
                    color:#888;white-space:nowrap;display:flex;align-items:center;gap:8px}}
    .section-label .dot{{width:5px;height:5px;border-radius:50%}}
    .panel-label{{font-size:.62rem;font-weight:600;letter-spacing:.16em;text-transform:uppercase;color:#888;margin-bottom:20px}}
 
    /* ── STOCK SEARCH ── */
    form{{display:grid;grid-template-columns:1.5fr 1fr 1fr auto;gap:14px;align-items:end}}
    .fg label{{display:block;font-size:.7rem;font-weight:600;letter-spacing:.05em;color:#555;margin-bottom:8px;text-transform:uppercase}}
    input,select{{width:100%;background:#ffffff;border:2px solid #000;border-radius:var(--rs);
                  color:#000;padding:10px 14px;font-size:.875rem;font-family:inherit;outline:none;
                  transition:border-color .2s,background .2s,box-shadow .2s;appearance:none;-webkit-appearance:none}}
    input::placeholder{{color:#aaa}}
    input:focus,select:focus{{border-color:#000;background:#fff;box-shadow:0 0 0 3px rgba(0,0,0,.06)}}
    select{{cursor:pointer;background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='10' height='6' viewBox='0 0 10 6'%3E%3Cpath fill='%23000' d='M5 6L0 0z'/%3E%3C/svg%3E");background-repeat:no-repeat;background-position:right 13px center;padding-right:34px}}
    select option{{background:#fff;color:#000}}
    .btn{{background:#000;color:#fff;border:none;border-radius:var(--rs);padding:10px 26px;
          font-size:.8rem;font-weight:700;font-family:inherit;cursor:pointer;white-space:nowrap;
          letter-spacing:.09em;text-transform:uppercase;transition:opacity .18s,transform .13s;height:42px}}
    .btn:hover{{opacity:.8}}.btn:active{{transform:scale(.96)}}
    .chips{{display:flex;flex-wrap:wrap;gap:7px;margin-top:22px;padding-top:20px;border-top:1px solid #e5e5e5}}
    .chip{{background:transparent;border:1px solid #000;border-radius:20px;padding:5px 15px;
           font-size:.72rem;font-family:'DM Mono',monospace;cursor:pointer;color:#555;
           letter-spacing:.05em;transition:all .16s;user-select:none}}
    .chip:hover{{border-color:#000;color:#000;background:#f0f0f0}}
    .chip.active{{background:#000;border-color:#000;color:#fff;font-weight:600}}
    .ind-row{{display:flex;flex-wrap:wrap;gap:7px;margin-top:16px;padding-top:16px;border-top:1px solid #e5e5e5;align-items:center}}
    .ind-label{{font-size:.62rem;font-weight:700;letter-spacing:.12em;text-transform:uppercase;color:#888;margin-right:4px}}
    .ind-chip{{background:transparent;border:1px solid #000;border-radius:4px;padding:4px 14px;
               font-size:.7rem;font-family:'DM Mono',monospace;cursor:pointer;color:#555;
               letter-spacing:.05em;transition:all .16s;user-select:none;text-transform:uppercase}}
    .ind-chip:hover{{border-color:#000;color:#000;background:#f0f0f0}}
    .ind-chip.active{{background:#eee;border-style:dashed;color:#000;font-weight:600}}
    /* ── CHART CARD — shadcn Stock Market Tracker style ── */
    .chart-card{{padding:0;overflow:hidden;background:#fff;border-radius:var(--r)}}
    .chart-card>div{{width:100%}}
    /* period button bar */
    .chart-period-bar{{display:flex;width:100%;border:1px solid #e5e5e5;border-radius:8px;overflow:hidden;margin-bottom:12px}}
    .chart-period-btn{{flex:1;height:32px;background:transparent;border:none;border-right:1px solid #e5e5e5;
                       font-size:.8rem;font-weight:600;letter-spacing:-.006em;color:#888;cursor:pointer;
                       transition:background .12s,color .12s;outline:none}}
    .chart-period-btn:last-child{{border-right:none}}
    .chart-period-btn:hover{{background:rgba(0,0,0,.03)}}
    .chart-period-btn.active{{background:rgba(0,0,0,.06);color:#000}}
    /* price header */
    .chart-price-hdr{{padding:16px 20px 0}}
    .chart-price-row{{display:flex;align-items:baseline;gap:10px;margin-bottom:2px}}
    .chart-price-val{{font-size:1.45rem;font-weight:600;letter-spacing:-.006em;font-variant-numeric:tabular-nums}}
    .chart-badge-up{{display:inline-flex;align-items:center;gap:4px;height:24px;padding:0 8px;
                     border-radius:6px;background:#E0FAEC;color:#22C55E;font-size:.72rem;font-weight:600;
                     letter-spacing:-.006em;white-space:nowrap}}
    .chart-badge-dn{{display:inline-flex;align-items:center;gap:4px;height:24px;padding:0 8px;
                     border-radius:6px;background:#fce4e4;color:#ef5350;font-size:.72rem;font-weight:600;
                     letter-spacing:-.006em;white-space:nowrap}}
    .chart-sym-label{{font-size:.8rem;font-weight:400;letter-spacing:-.006em;color:#888;text-transform:uppercase;margin-bottom:12px}}
    /* highest/lowest footer bar */
    .chart-hl-bar{{display:flex;width:100%;border:1px solid #e5e5e5;border-radius:8px;overflow:hidden;margin-top:10px}}
    .chart-hl-btn{{flex:1;height:32px;background:transparent;border:none;border-right:1px solid #e5e5e5;
                   font-size:.8rem;font-weight:400;color:#888;cursor:default;
                   display:flex;align-items:center;justify-content:center;gap:6px;outline:none}}
    .chart-hl-btn:last-child{{border-right:none}}
    .chart-hl-val{{font-size:.8rem;font-weight:600;color:#000;font-variant-numeric:tabular-nums}}
    /* chart body wrapper */
    .chart-body-wrap{{padding:0 12px}}
    /* card inner padding for period bar + hl bar */
    .chart-controls-wrap{{padding:12px 16px 14px}}
    .error-box{{border:1px solid #000;border-left:3px solid #000;border-radius:var(--rs);padding:16px 20px;color:#555;font-size:.875rem;background:#f8f7f4;width:100%;line-height:1.6}}
    .empty-state{{color:#888;font-size:.85rem;text-align:center;letter-spacing:.03em}}
 
    /* ── ALT DATA BADGES ── */
    .alt-data-row{{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:20px;padding-bottom:20px;border-bottom:1px solid #e5e5e5}}
    .alt-data-badge{{display:inline-flex;align-items:center;gap:5px;font-size:.6rem;font-weight:600;
                     letter-spacing:.1em;text-transform:uppercase;padding:3px 10px;border-radius:4px;
                     border:1px solid #000;color:#333;background:#fff}}
    .alt-dot{{width:5px;height:5px;border-radius:50%;background:#000;flex-shrink:0}}
 
    /* ── AI PANEL ── */
    .ai-panel{{padding:26px 30px;margin-bottom:18px}}
    .ai-models-grid{{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-bottom:20px}}
    .ai-model-card{{background:#fff;border:2px solid #000;border-radius:var(--r);
                    padding:16px;cursor:pointer;transition:all .2s;user-select:none}}
    .ai-model-card:hover:not(.exhausted){{background:#f0f0f0}}
    .ai-model-card.selected{{background:#000;color:#fff;box-shadow:none}}
    .ai-model-card.selected .ai-mname{{color:#fff}}
    .ai-model-card.selected .ai-mdesc{{color:#aaa}}
    .ai-model-card.exhausted{{opacity:.45;cursor:not-allowed}}
    .ai-model-hdr{{display:flex;align-items:center;gap:8px;margin-bottom:4px}}
    .ai-dot{{width:7px;height:7px;border-radius:50%;flex-shrink:0;background:#000}}
    .ai-mname{{font-size:.8rem;font-weight:600;color:#000}}
    .ai-mdesc{{font-size:.67rem;color:#555;margin-bottom:12px}}

    .ai-rl-badge{{font-size:.55rem;font-weight:700;letter-spacing:.07em;text-transform:uppercase;
                  padding:2px 7px;border-radius:4px;margin-left:auto;
                  background:#f0f0f0;border:1px solid #aaa;color:#555}}
    .ai-action-row{{display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin-bottom:20px}}
    .btn-ai{{background:#000;border:none;border-radius:var(--rs);color:#fff;
             padding:10px 28px;font-size:.8rem;font-weight:700;font-family:inherit;cursor:pointer;
             letter-spacing:.09em;text-transform:uppercase;transition:all .18s}}
    .btn-ai:hover{{opacity:.8}}
    .btn-ai:active{{transform:scale(.96)}}.btn-ai:disabled{{opacity:.35;cursor:not-allowed;transform:none}}
    .ai-sel-label{{font-size:.72rem;color:#555}}
    .ai-timer{{font-size:.67rem;font-family:'DM Mono',monospace;color:#888;margin-left:auto}}
    .ai-result{{display:none;border:2px solid #000;border-radius:var(--r);overflow:hidden;margin-top:4px;background:#fff}}
    .ai-result.show{{display:block}}
    .ai-verdict-bar{{display:flex;align-items:center;gap:12px;padding:18px 22px;border-bottom:1px solid #e5e5e5;flex-wrap:wrap}}
    .ai-badge{{font-size:.95rem;font-weight:700;letter-spacing:.12em;padding:8px 20px;border-radius:4px;text-transform:uppercase;flex-shrink:0}}
    .v-BUY{{background:#e8f5e9;border:1px solid #333;color:#000}}
    .v-SELL{{background:#fce4e4;border:1px solid #333;color:#000}}
    .v-HOLD{{background:#fffde7;border:1px solid #333;color:#000}}
    .ai-vmeta{{display:flex;flex-direction:column;gap:4px;flex:1}}
    .ai-summary{{font-size:.84rem;color:#000;line-height:1.5}}
    .ai-meta-row{{display:flex;gap:14px;flex-wrap:wrap}}
    .ai-mi{{font-size:.67rem;color:#555}}.ai-mi strong{{color:#888}}
    .ai-model-tag{{display:inline-flex;align-items:center;gap:5px;font-size:.6rem;font-weight:600;
                   letter-spacing:.08em;text-transform:uppercase;padding:3px 9px;border-radius:4px;
                   border:1px solid #000;color:#555;background:#f8f7f4;white-space:nowrap}}
    .ai-pts{{display:grid;grid-template-columns:repeat(4,1fr);gap:1px;background:#e5e5e5;border-bottom:1px solid #e5e5e5}}
    .ai-pt{{background:#fff;padding:14px 16px;text-align:center}}
    .ai-pt-lbl{{font-size:.58rem;font-weight:700;letter-spacing:.1em;text-transform:uppercase;color:#888;margin-bottom:5px}}
    .ai-pt-val{{font-size:.92rem;font-weight:600;font-family:'DM Mono',monospace}}
    .pt-e{{color:#000}}.pt-sl{{color:#555}}.pt-t1{{color:#000}}.pt-t2{{color:#333}}
    .ai-secs{{padding:0}}
    .ai-sec{{padding:18px 22px;border-bottom:1px solid #e5e5e5}}
    .ai-sec:last-child{{border-bottom:none}}
    .ai-sec-hdr{{font-size:.58rem;font-weight:700;letter-spacing:.14em;text-transform:uppercase;
                 color:#888;margin-bottom:10px;display:flex;align-items:center;gap:7px}}
    .ai-sec-body{{font-size:.82rem;color:#333;line-height:1.8;white-space:pre-wrap;word-break:break-word}}
    .ai-loading{{display:flex;flex-direction:column;align-items:center;justify-content:center;padding:50px 24px;gap:14px}}
    .ai-spin{{width:26px;height:26px;border-radius:50%;border:2px solid #e5e5e5;
              border-top-color:#000;animation:spin .7s linear infinite}}
    @keyframes spin{{to{{transform:rotate(360deg)}}}}
    .ai-load-txt{{font-size:.78rem;color:#555;letter-spacing:.04em}}
    .ai-load-sub{{font-size:.68rem;color:#aaa;letter-spacing:.03em;text-align:center;max-width:340px}}
    .ai-err{{padding:20px 22px;color:#c00;font-size:.82rem;line-height:1.6}}
    .ai-data-tags{{display:flex;flex-wrap:wrap;gap:5px;padding:14px 22px;border-bottom:1px solid #e5e5e5;background:#f8f7f4}}
    .ai-data-tag{{font-size:.55rem;font-weight:700;letter-spacing:.1em;text-transform:uppercase;
                  padding:2px 8px;border-radius:4px;border:1px solid #000;color:#333;background:#fff}}
 
    /* ── SECTOR SECTION ── */
    .sector-panel{{padding:26px 30px;margin-bottom:18px}}
    .sector-selector-row{{display:flex;gap:10px;align-items:stretch;margin-bottom:20px}}
    .sector-select-wrap{{flex:1;display:flex;background:#fff;border:2px solid #000;
                          border-radius:var(--rs);overflow:hidden;transition:border-color .2s}}
    .sector-select-wrap:focus-within{{border-color:#000}}
    .sel-prefix{{display:flex;align-items:center;padding:0 1rem;font-size:.58rem;font-weight:700;
                 letter-spacing:.15em;text-transform:uppercase;color:#888;white-space:nowrap;
                 border-right:1px solid #e5e5e5;background:#f8f7f4;flex-shrink:0}}
    .sector-select{{flex:1;appearance:none;background:transparent;border:none;outline:none;
                    padding:.75rem 2.5rem .75rem 1rem;font-family:inherit;font-size:.875rem;
                    font-weight:500;color:#000;cursor:pointer;
                    background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='10' height='6' viewBox='0 0 10 6'%3E%3Cpath fill='%23000' d='M5 6L0 0z'/%3E%3C/svg%3E");
                    background-repeat:no-repeat;background-position:right 12px center}}
    .sector-select option{{background:#fff;color:#000}}
    .btn-sector{{background:#000;color:#fff;border:none;border-radius:var(--rs);padding:0 22px;
                 font-size:.75rem;font-weight:700;font-family:inherit;cursor:pointer;
                 letter-spacing:.1em;text-transform:uppercase;transition:opacity .18s,transform .13s;white-space:nowrap}}
    .btn-sector:hover{{opacity:.8}}.btn-sector:active{{transform:scale(.96)}}
    .btn-sector:disabled{{opacity:.35;cursor:not-allowed;transform:none}}
    .sector-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(158px,1fr));gap:8px;margin-bottom:4px}}
    .s-tile{{background:#fff;border:2px solid #000;border-radius:var(--r);
             padding:14px 12px;cursor:pointer;text-align:left;color:inherit;
             transition:background .15s,color .15s;
             display:flex;flex-direction:column;gap:4px}}
    .s-tile:hover{{background:#000;color:#fff}}
    .s-tile:hover .s-tile-key{{color:#fff;background:rgba(255,255,255,.15);border-color:rgba(255,255,255,.4)}}
    .s-tile:hover .s-tile-name{{color:#fff}}
    .s-tile:hover .s-tile-sub{{color:#aaa}}
    .s-tile-key{{font-family:'DM Mono',monospace;font-size:.6rem;font-weight:700;letter-spacing:.12em;
                 text-transform:uppercase;color:#000;background:#f0f0f0;
                 border:1px solid #000;padding:.14rem .5rem;border-radius:4px;
                 display:inline-block;align-self:flex-start;margin-bottom:2px}}
    .s-tile-name{{font-size:.78rem;font-weight:700;color:#000;line-height:1.3}}
    .s-tile-sub{{font-size:.64rem;color:#555;line-height:1.3}}
 
    /* Sector news output */
    #sector-output{{margin-top:18px}}
    .sector-res-header{{display:flex;align-items:flex-end;justify-content:space-between;gap:1rem;
                         margin-bottom:16px;padding-bottom:14px;border-bottom:1px solid #e5e5e5;flex-wrap:wrap}}
    .sector-res-title{{font-size:1.05rem;font-weight:600;color:#000}}
    .sector-res-title em{{font-style:normal;color:#000;font-weight:800}}
    .sector-res-meta{{display:flex;align-items:center;gap:8px;flex-wrap:wrap}}
    .res-count-badge{{font-family:'DM Mono',monospace;font-size:.6rem;font-weight:500;letter-spacing:.12em;
                      text-transform:uppercase;color:#333;background:#f0f0f0;
                      border:1px solid #000;padding:.22rem .7rem;border-radius:4px}}
    .res-time-badge{{font-family:'DM Mono',monospace;font-size:.58rem;color:#555}}
    .filter-row{{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:16px;align-items:center}}
    .filter-label{{font-size:.58rem;font-weight:700;letter-spacing:.16em;text-transform:uppercase;
                   color:#888;margin-right:4px}}
    .pill{{font-size:.68rem;font-weight:500;padding:.28rem .75rem;
           border:1px solid #000;border-radius:20px;
           background:transparent;color:#555;cursor:pointer;transition:all .15s;user-select:none}}
    .pill:hover{{border-color:#000;color:#000;background:#f0f0f0}}
    .pill.active{{background:#000;border-color:#000;color:#fff;font-weight:600}}
    .news-grid-sec{{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:10px}}
    @keyframes card-in{{from{{opacity:0;transform:translateY(10px)}}to{{opacity:1;transform:translateY(0)}}}}
    .news-card{{background:#fff;border:1px solid #000;border-radius:4px;
                padding:16px;display:flex;flex-direction:column;gap:10px;
                transition:transform .18s,box-shadow .18s;
                position:relative;overflow:hidden;animation:card-in .32s ease both}}
    .news-card:hover{{transform:translateY(-2px);box-shadow:0 4px 16px rgba(0,0,0,.12)}}
    .news-card-top{{display:flex;align-items:flex-start;justify-content:space-between;gap:8px}}
    .news-card-src{{font-family:'DM Mono',monospace;font-size:.56rem;font-weight:700;letter-spacing:.12em;
                    text-transform:uppercase;color:#000;background:#f0f0f0;
                    border:1px solid #000;padding:.14rem .5rem;border-radius:3px;white-space:nowrap}}
    .news-card-num{{font-family:'DM Mono',monospace;font-size:.6rem;color:#888;flex-shrink:0}}
    .news-card-title{{font-size:.85rem;font-weight:600;line-height:1.5;color:#000;flex:1}}
    .news-card-title a{{color:inherit;text-decoration:none;display:block;transition:color .15s}}
    .news-card-title a:hover{{color:#333;text-decoration:underline}}
    .news-card-footer{{display:flex;align-items:center;justify-content:space-between;gap:8px;
                       margin-top:auto;padding-top:10px;border-top:1px solid #e5e5e5}}
    .news-card-date{{font-family:'DM Mono',monospace;font-size:.58rem;color:#555;
                     white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
    .news-card-read{{font-size:.62rem;font-weight:700;letter-spacing:.08em;text-transform:uppercase;
                     color:#000;text-decoration:none;padding:.24rem .65rem;
                     border:1px solid #000;border-radius:4px;background:#fff;
                     transition:all .15s;white-space:nowrap;flex-shrink:0}}
    .news-card-read:hover{{background:#000;color:#fff;border-color:#000}}
    .sector-state{{display:flex;flex-direction:column;align-items:center;justify-content:center;
                   padding:40px 20px;text-align:center;gap:12px;color:#555}}
    .sector-spinner{{width:32px;height:32px;border-radius:50%;border:2px solid #e5e5e5;
                     border-top-color:#000;animation:spin .75s linear infinite}}
    .sector-state-title{{font-size:.95rem;font-weight:600;color:#555}}
    .sector-state-sub{{font-size:.78rem;color:#888;max-width:340px;line-height:1.6}}
 
    /* ── NEWS ── */
    .news-panel{{padding:26px 30px;margin-bottom:18px}}
    @keyframes lp{{0%,100%{{opacity:1;transform:scale(1)}}50%{{opacity:.3;transform:scale(.6)}}}}
    .news-tabs{{display:flex;gap:8px;margin-bottom:20px;flex-wrap:wrap}}
    .news-tab{{background:transparent;border:1px solid #000;border-radius:20px;padding:6px 18px;
               font-size:.72rem;font-family:'DM Mono',monospace;cursor:pointer;color:#555;
               letter-spacing:.05em;transition:all .16s;user-select:none}}
    .news-tab:hover{{border-color:#000;color:#000;background:#f0f0f0}}
    .news-tab.active{{background:#000;border-color:#000;color:#fff;font-weight:600}}
    .news-tab.active .news-tag{{background:rgba(255,255,255,.2);color:rgba(255,255,255,.7)}}
    .news-iframe-wrap{{position:relative;width:100%;padding-top:56.25%;border:4px solid #000;border-radius:0;overflow:hidden;background:#000}}
    .news-loading{{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;
                   color:#888;font-size:.8rem;letter-spacing:.05em;flex-direction:column;gap:12px;background:#f8f7f4}}
    .news-spinner{{width:22px;height:22px;border-radius:50%;border:2px solid #e5e5e5;border-top-color:#000;animation:spin .8s linear infinite}}
    .news-iframe-wrap iframe{{position:absolute;inset:0;width:100%;height:100%;border:none}}
    .news-tag{{font-size:.55rem;font-weight:600;letter-spacing:.08em;text-transform:uppercase;
               padding:1px 5px;border-radius:4px;background:rgba(255,255,255,.15);color:rgba(255,255,255,.7);margin-left:4px;vertical-align:middle}}
    .nsb{{display:inline-flex;align-items:center;gap:5px;font-size:.62rem;font-weight:700;
           letter-spacing:.1em;text-transform:uppercase;padding:3px 10px;border-radius:20px;white-space:nowrap}}
    .nsb.live{{background:rgba(255,60,60,.12);border:1px solid rgba(255,60,60,.4);color:#c00}}
    .nsb.live::before{{content:'';display:inline-block;width:5px;height:5px;border-radius:50%;background:#ff4444;animation:lp 1.4s ease-in-out infinite}}
    .nsb.latest{{background:#f0f0f0;border:1px solid #000;color:#333}}
    .nsb.error{{background:#fff5e5;border:1px solid #aaa;color:#888}}
 
    /* ── DISCLAIMER ── */
    .disclaimer-wrap{{max-width:1200px;margin:0 auto;padding:0 20px 32px;position:relative;z-index:1}}
    .disclaimer-box{{display:flex;gap:12px;align-items:flex-start;background:#f8f7f4;
                     border:1px solid #e5e5e5;border-radius:4px;padding:14px 18px}}
    .disclaimer-icon{{color:#aaa;flex-shrink:0;margin-top:2px}}
    .disclaimer-body{{font-size:.65rem;color:#555;line-height:1.8}}
    .disclaimer-label{{display:inline-block;font-size:.54rem;font-weight:700;letter-spacing:.16em;
                        text-transform:uppercase;color:#333;border:1px solid #000;
                        border-radius:4px;padding:1px 6px;background:#f0f0f0;
                        vertical-align:middle;position:relative;top:-1px;margin-right:7px}}
 
    /* ── FOOTER ── */
    .site-footer{{position:relative;z-index:1;text-align:center;padding:48px 20px 72px;border-top:2px solid #000;background:#f8f7f4}}
    .site-footer-sub{{font-size:.6rem;font-weight:700;letter-spacing:.24em;text-transform:uppercase;color:#888;margin-bottom:12px}}
    .site-footer-name{{font-size:clamp(3rem,9vw,6rem);font-weight:800;letter-spacing:-.02em;text-transform:uppercase;color:#000;line-height:1}}
 

    /* ── LIVE SATELLITE VIEWER PANEL ── */
    .sat-viewer-panel{{background:#fff;border:2px solid #000;border-radius:0;margin-top:0;overflow:visible}}
    .sat-viewer-toolbar{{display:flex;align-items:center;gap:10px;padding:10px 16px;border-bottom:1px solid #000;flex-wrap:wrap;background:#f8f7f4}}
    .sat-viewer-map-wrap{{position:relative;width:100%;height:480px;background:#e8e8e8;overflow:hidden}}
    .sat-viewer-map{{width:100%;height:100%}}
    .sat-viewer-sidebar{{display:flex;flex-direction:column;gap:10px;padding:14px 16px;border-top:1px solid #000;background:#f8f7f4}}
    .sat-viewer-row{{display:grid;grid-template-columns:1fr 1fr;gap:10px}}
    .sat-vfield label{{font-size:.58rem;font-weight:700;letter-spacing:.16em;text-transform:uppercase;color:#555;display:block;margin-bottom:4px}}
    .sat-vfield input[type=date],.sat-vfield input[type=range]{{width:100%;padding:7px 10px;border:1px solid #000;background:#fff;font-family:'DM Mono',monospace;font-size:.78rem;outline:none;border-radius:0}}
    .sat-vfield input[type=range]{{padding:4px 0;background:transparent;border:none;cursor:pointer}}
    .sat-vfield input[type=range]::-webkit-slider-runnable-track{{height:3px;background:#000;border-radius:0}}
    .sat-vfield input[type=range]::-webkit-slider-thumb{{appearance:none;width:13px;height:13px;background:#000;border-radius:50%;margin-top:-5px;cursor:pointer}}
    .sat-layer-grid{{display:grid;grid-template-columns:repeat(5,1fr);gap:6px;margin:0 16px 14px}}
    .sat-vlayer-btn{{padding:6px 4px;border:1px solid #000;background:#fff;font-family:'DM Mono',monospace;font-size:.52rem;font-weight:600;letter-spacing:.08em;text-transform:uppercase;cursor:pointer;text-align:center;transition:all .15s}}
    .sat-vlayer-btn.active,.sat-vlayer-btn:hover{{background:#000;color:#fff}}
    .sat-load-btn{{display:block;width:100%;box-sizing:border-box;padding:11px 16px;background:#000;color:#fff;border:none;font-family:'DM Mono',monospace;font-size:.7rem;font-weight:700;letter-spacing:.14em;text-transform:uppercase;cursor:pointer;transition:opacity .2s}}
    .sat-load-btn:hover{{opacity:.78}}
    .sat-load-btn:disabled{{opacity:.35;cursor:not-allowed}}
    .sat-status-bar{{display:flex;align-items:center;gap:8px;padding:8px 16px;border-top:1px solid #e5e5e5;font-family:'DM Mono',monospace;font-size:.58rem;color:#888}}
    .sat-status-dot{{width:6px;height:6px;border-radius:50%;background:#22c55e;flex-shrink:0}}
    .sat-search-wrap{{position:relative;flex:1;min-width:140px}}
    .sat-search-input{{width:100%;padding:7px 34px 7px 10px;border:1px solid #000;background:#fff;font-family:'DM Mono',monospace;font-size:.72rem;outline:none;border-radius:0}}
    .sat-search-input::placeholder{{color:#aaa}}
    .sat-search-btn{{position:absolute;right:0;top:0;bottom:0;width:32px;background:none;border:none;border-left:1px solid #000;cursor:pointer;font-size:14px;display:flex;align-items:center;justify-content:center}}
    .sat-search-results{{position:absolute;top:100%;left:0;right:0;background:#fff;border:1px solid #000;border-top:none;z-index:600;display:none;max-height:160px;overflow-y:auto}}
    .sat-search-result-item{{padding:8px 12px;font-family:'DM Mono',monospace;font-size:.66rem;cursor:pointer;border-bottom:1px solid #f0f0f0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
    .sat-search-result-item:hover{{background:#000;color:#fff}}
    .sat-token-badge{{font-family:'DM Mono',monospace;font-size:.55rem;color:#555;background:#f0f0f0;border:1px solid #ccc;border-radius:20px;padding:3px 8px;white-space:nowrap}}
    .sat-cloud-row{{display:flex;align-items:center;gap:8px}}
    .sat-cloud-val{{font-family:'DM Mono',monospace;font-size:.72rem;font-weight:600;min-width:36px;text-align:right}}
    .sat-log{{font-family:'DM Mono',monospace;font-size:.6rem;color:#888;padding:8px 16px;border-top:1px solid #e5e5e5;max-height:70px;overflow-y:auto;background:#fafafa}}
    .sat-log-entry{{padding:1px 0;line-height:1.6}}
    .sat-log-entry.ok{{color:#16a34a}}
    .sat-log-entry.err{{color:#dc2626}}

    /* Mobile responsive for satellite viewer */
    @media(max-width:600px){{
      .sat-viewer-map-wrap{{height:280px;max-height:280px;overflow:hidden}}
      .sat-layer-grid{{grid-template-columns:repeat(3,1fr);margin:0 10px 10px}}
      .sat-viewer-toolbar{{gap:6px;padding:8px 10px}}
      .sat-search-wrap{{min-width:100%;order:1}}
      .sat-token-badge{{order:2}}
      .sat-viewer-row{{grid-template-columns:1fr}}
      .sat-viewer-sidebar{{padding:10px 12px;gap:8px}}
      .sat-load-btn{{margin:0;width:100%}}
      .sat-load-btn-wrap{{padding:0 10px 12px}}
      .sat-layer-grid{{margin:0 10px 10px}}
      .sat-cloud-row{{flex-wrap:wrap}}
    }}
    @media(max-width:400px){{
      .sat-viewer-map-wrap{{height:240px;max-height:240px;overflow:hidden}}
      .sat-layer-grid{{grid-template-columns:repeat(3,1fr)}}
    }}
    /* ── SATELLITE IMAGERY SECTION ── */
    #sector-satellite{{margin-top:24px;display:none}}
    .sat-section-divider{{display:flex;align-items:center;gap:14px;margin:24px 0 18px}}
    .sat-section-divider-line{{flex:1;height:1px;background:#e5e5e5}}
    .sat-label{{font-size:.6rem;font-weight:700;letter-spacing:.22em;text-transform:uppercase;
                color:#888;white-space:nowrap;display:flex;align-items:center;gap:8px}}
    .sat-label .sat-dot{{width:5px;height:5px;border-radius:50%;background:#000}}
    .sat-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:12px}}
    .sat-card{{background:#fff;border:1px solid #000;border-radius:4px;overflow:hidden;
               transition:transform .18s,box-shadow .18s;animation:card-in .32s ease both}}
    .sat-card:hover{{transform:translateY(-2px);box-shadow:0 4px 16px rgba(0,0,0,.12)}}
    .sat-map-wrap{{width:100%;height:180px;position:relative;background:#f0f0f0;overflow:hidden}}
    .sat-map-leaf{{width:100%;height:100%}}
    .sat-layer-btns{{position:absolute;top:6px;right:6px;z-index:500;display:flex;flex-direction:column;gap:3px}}
    .sat-layer-btn{{background:rgba(255,255,255,.92);border:1px solid #000;color:#333;
                    font-family:'DM Mono',monospace;font-size:.52rem;letter-spacing:.06em;
                    padding:3px 7px;cursor:pointer;border-radius:3px;transition:all .15s;white-space:nowrap}}
    .sat-layer-btn.active,.sat-layer-btn:hover{{background:#000;color:#fff;border-color:#000}}
    .sat-map-crosshair{{position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);
                         width:18px;height:18px;pointer-events:none;z-index:499}}
    .sat-map-crosshair::before,.sat-map-crosshair::after{{content:'';position:absolute;background:rgba(0,0,0,.6)}}
    .sat-map-crosshair::before{{width:1px;height:100%;left:50%;top:0}}
    .sat-map-crosshair::after{{width:100%;height:1px;top:50%;left:0}}
    .sat-body{{padding:10px 12px 12px}}
    .sat-name{{font-size:.82rem;font-weight:600;line-height:1.4;color:#000;margin-bottom:4px}}
    .sat-tag{{font-family:'DM Mono',monospace;font-size:.55rem;color:#333;background:#f0f0f0;
               border:1px solid #000;padding:.12rem .45rem;border-radius:3px;display:inline-block;margin-bottom:6px}}
    .sat-coords{{font-family:'DM Mono',monospace;font-size:.57rem;color:#888;margin-bottom:6px}}
    .sat-sources{{display:flex;gap:4px;flex-wrap:wrap}}
    .sat-src-badge{{font-family:'DM Mono',monospace;font-size:.54rem;letter-spacing:.05em;
                    padding:2px 6px;border-radius:3px;border:1px solid #000;color:#333;background:#f8f7f4}}
    .sat-loading-state{{display:flex;flex-direction:column;align-items:center;justify-content:center;
                         padding:32px 20px;gap:10px;color:#888}}
    .sat-spinner{{width:24px;height:24px;border-radius:50%;border:2px solid #e5e5e5;
                  border-top-color:#000;animation:spin .75s linear infinite}}
    .sat-count-badge{{font-family:'DM Mono',monospace;font-size:.6rem;font-weight:500;letter-spacing:.1em;
                       text-transform:uppercase;color:#333;background:#f0f0f0;
                       border:1px solid #000;padding:.18rem .6rem;border-radius:4px}}

    html,body{{max-width:100%;overflow-x:hidden}}
    *{{min-width:0;box-sizing:border-box}}

    /* ── TABLET ── */
    @media(max-width:860px){{
      form{{grid-template-columns:1fr 1fr;gap:12px}}
      .fg:first-child{{grid-column:span 2}}
      .btn{{grid-column:span 2;width:100%}}
      .ai-models-grid{{grid-template-columns:repeat(2,1fr)}}
      .ai-pts{{grid-template-columns:repeat(2,1fr)}}
      .sector-grid{{grid-template-columns:repeat(3,1fr)}}
      .sat-grid{{grid-template-columns:repeat(2,1fr)}}
      .alpaca-grid{{grid-template-columns:repeat(auto-fill,minmax(260px,1fr))}}
    }}

    /* ── MOBILE ── */
    @media(max-width:600px){{
      /* Global overflow control */
      html,body{{overflow-x:hidden;width:100%}}

      /* Header */
      header{{padding:0 10px;height:48px;gap:6px}}
      .logo{{gap:7px}}
      .logo-star img{{height:34px!important}}
      .logo-word{{font-size:.65rem;letter-spacing:.12em}}
      .logo-tagline{{font-size:.42rem;letter-spacing:.1em}}
      .header-nav{{gap:3px;flex-shrink:0}}
      .nav-link{{font-size:.52rem;padding:3px 6px;letter-spacing:.04em}}

      /* Ticker strip */
      .ticker-strip{{overflow:hidden;width:100%;height:28px}}
      .ticker-badge{{font-size:.48rem;padding:0 .6rem;letter-spacing:.12em}}
      .ticker-track{{padding-left:70px}}
      .t-item{{font-size:.52rem;padding:0 1rem}}

      /* Main content */
      main{{padding:12px 10px 40px;width:100%;max-width:100%}}
      .disclaimer-wrap{{padding:0 10px 20px}}
      .panel,.sector-panel,.ai-panel,.news-panel{{padding:14px 12px}}
      .alpaca-panel{{padding:14px 12px}}
      .alpaca-header{{flex-direction:column;align-items:flex-start}}
      .alpaca-filter{{order:2;margin-bottom:12px}}
      .alpaca-sort{{order:3;margin-left:0}}
      .alpaca-grid{{grid-template-columns:1fr}}

      /* Section dividers */
      .section-divider{{margin:20px 0 12px;gap:8px}}
      .section-label{{font-size:.55rem;letter-spacing:.16em}}

      /* Form */
      form{{grid-template-columns:1fr;gap:8px}}
      .fg:first-child{{grid-column:span 1}}
      .btn{{grid-column:span 1;width:100%;padding:10px 16px}}
      .fg label{{font-size:.65rem;margin-bottom:6px}}
      input,select{{padding:9px 12px;font-size:.82rem}}

      /* Chips & indicators */
      .chips{{gap:5px;margin-top:14px;padding-top:12px}}
      .chip{{font-size:.64rem;padding:4px 10px}}
      .ind-row{{gap:5px;margin-top:12px;padding-top:12px}}
      .ind-label{{font-size:.56rem;margin-right:2px}}
      .ind-chip{{font-size:.6rem;padding:3px 8px}}
      .panel-label{{font-size:.56rem;margin-bottom:14px}}

      /* Chart card */
      .chart-card{{padding:8px 4px 6px;min-height:220px}}
      .chart-card>div{{width:100%!important}}
      .error-box{{font-size:.78rem;padding:12px 14px}}

      /* Alt data badges */
      .alt-data-row{{gap:4px;margin-bottom:14px;padding-bottom:14px;flex-wrap:wrap}}
      .alt-data-badge{{font-size:.52rem;padding:2px 7px;letter-spacing:.06em}}

      /* AI model cards */
      .ai-models-grid{{grid-template-columns:1fr;gap:8px;margin-bottom:14px}}
      .ai-model-card{{padding:12px}}
      .ai-mname{{font-size:.74rem}}
      .ai-mdesc{{font-size:.62rem;margin-bottom:8px}}

      /* AI action row */
      .ai-action-row{{gap:8px;margin-bottom:14px}}
      .btn-ai{{padding:9px 18px;font-size:.72rem}}
      .ai-sel-label{{font-size:.65rem}}
      .ai-timer{{font-size:.6rem}}

      /* AI result panel */
      .ai-verdict-bar{{padding:12px 14px;gap:8px;flex-direction:column;align-items:flex-start}}
      .ai-badge{{font-size:.82rem;padding:6px 16px}}
      .ai-summary{{font-size:.78rem}}
      .ai-meta-row{{gap:8px}}
      .ai-mi{{font-size:.6rem}}
      .ai-model-tag{{font-size:.54rem}}
      .ai-pts{{grid-template-columns:repeat(2,1fr)}}
      .ai-pt{{padding:10px 12px}}
      .ai-pt-lbl{{font-size:.52rem}}
      .ai-pt-val{{font-size:.82rem}}
      .ai-sec{{padding:12px 14px}}
      .ai-sec-hdr{{font-size:.54rem;margin-bottom:8px}}
      .ai-sec-body{{font-size:.76rem;line-height:1.7}}
      .ai-data-tags{{padding:10px 14px;gap:4px}}
      .ai-data-tag{{font-size:.5rem;padding:2px 6px}}
      .ai-loading{{padding:36px 16px;gap:10px}}
      .ai-load-txt{{font-size:.72rem}}
      .ai-load-sub{{font-size:.62rem;max-width:280px}}

      /* Sector panel */
      .sector-selector-row{{flex-direction:column;gap:8px}}
      .sel-prefix{{font-size:.52rem;padding:0 .7rem}}
      .sector-select{{font-size:.8rem;padding:.65rem 2rem .65rem .8rem}}
      .btn-sector{{padding:.65rem;width:100%;font-size:.7rem}}
      .sector-grid{{grid-template-columns:repeat(2,1fr);gap:6px}}
      .s-tile{{padding:10px 10px}}
      .s-tile-key{{font-size:.54rem;padding:.1rem .4rem}}
      .s-tile-name{{font-size:.72rem}}
      .s-tile-sub{{font-size:.58rem}}

      /* Prediction markets */
      #pred-chart{{height:260px!important}}
      #pred-chart-wrap{{margin-bottom:12px}}
      #pred-table{{font-size:.72rem}}
      #pred-table th,#pred-table td{{padding:5px 5px}}
      #pred-table th{{font-size:.48rem;letter-spacing:.04em}}
      #pred-table col:first-child{{width:70px!important}}
      #pred-table col:nth-child(3){{width:44px!important}}
      #pred-table col:nth-child(4){{width:44px!important}}
      #pred-table col:nth-child(5){{width:0!important;display:none}}
      #pred-table td:nth-child(5),#pred-table th:nth-child(5){{display:none}}

      /* Sector news output */
      .sector-res-header{{flex-direction:column;align-items:flex-start;gap:6px;padding-bottom:10px;margin-bottom:12px}}
      .sector-res-title{{font-size:.9rem}}
      .res-count-badge{{font-size:.54rem}}
      .res-time-badge{{font-size:.52rem}}
      .filter-row{{gap:4px;margin-bottom:12px}}
      .filter-label{{font-size:.52rem}}
      .pill{{font-size:.62rem;padding:.22rem .6rem}}
      .news-grid-sec{{grid-template-columns:1fr;gap:8px}}
      .news-card{{padding:12px}}
      .news-card-src{{font-size:.5rem}}
      .news-card-num{{font-size:.54rem}}
      .news-card-title{{font-size:.78rem}}
      .news-card-date{{font-size:.52rem}}
      .news-card-read{{font-size:.56rem;padding:.2rem .5rem}}

      /* Sector state */
      .sector-state{{padding:28px 14px;gap:8px}}
      .sector-state-title{{font-size:.85rem}}
      .sector-state-sub{{font-size:.72rem}}

      /* Live news */
      .news-tabs{{gap:5px;flex-wrap:wrap}}
      .news-tab{{padding:4px 10px;font-size:.62rem}}
      .news-tag{{font-size:.48rem;padding:1px 4px}}
      .news-iframe-wrap{{border-width:2px}}
      .nsb{{font-size:.56rem;padding:2px 8px}}

      /* Satellite section */
      .sat-grid{{grid-template-columns:1fr;gap:8px}}
      .sat-card{{overflow:hidden}}
      .sat-map-wrap{{height:160px}}
      .sat-layer-btns{{gap:2px}}
      .sat-layer-btn{{font-size:.48rem;padding:2px 5px}}
      .sat-body{{padding:8px 10px 10px}}
      .sat-name{{font-size:.76rem;margin-bottom:3px}}
      .sat-tag{{font-size:.5rem;padding:.1rem .35rem}}
      .sat-coords{{font-size:.52rem;margin-bottom:4px}}
      .sat-src-badge{{font-size:.48rem;padding:1px 5px}}
      .sat-section-divider{{margin:18px 0 14px}}
      .sat-label{{font-size:.54rem;letter-spacing:.16em}}
      .sat-count-badge{{font-size:.54rem;padding:.14rem .5rem}}

      /* Disclaimer */
      .disclaimer-box{{padding:10px 12px;gap:8px}}
      .disclaimer-body{{font-size:.58rem;line-height:1.7}}
      .disclaimer-label{{font-size:.48rem;padding:1px 5px}}
      .disclaimer-icon svg{{width:12px;height:12px}}

      /* Vessel tracker */
      #vessel-iframe{{width:100%;height:300px!important;min-height:0;max-height:300px!important}}
      .vessel-wrap{{overflow:hidden;border-radius:0 0 10px 10px}}
      /* Disable hover animations on touch to prevent jank */
      .news-card{{animation:none;transition:none}}
      .news-card:hover{{transform:none;box-shadow:none}}
      .sat-card{{animation:none;transition:none}}
      .sat-card:hover{{transform:none;box-shadow:none}}
      .btn,.btn-ai,.btn-sector{{transition:none}}

      /* Footer */
      .site-footer{{padding:28px 14px 48px}}
      .site-footer-sub{{font-size:.54rem;letter-spacing:.18em;margin-bottom:8px}}
      .site-footer-name{{font-size:clamp(2rem,12vw,4.5rem)}}
    }}

    /* ── VERY SMALL SCREENS ── */
    @media(max-width:380px){{
      header{{padding:0 8px;height:44px}}
      .logo-word{{font-size:.58rem}}
      .logo-tagline{{display:none}}
      .nav-link{{font-size:.48rem;padding:2px 5px}}
      main{{padding:10px 8px 36px}}
      .panel,.sector-panel,.ai-panel,.news-panel{{padding:12px 10px}}
      .sector-grid{{grid-template-columns:1fr;gap:5px}}
      .chips{{gap:4px}}
      .chip{{font-size:.6rem;padding:3px 8px}}
      form input,form select{{font-size:.78rem;padding:8px 10px}}
      .ai-badge{{font-size:.72rem;padding:5px 12px}}
      .ai-pts{{grid-template-columns:1fr 1fr}}
      .site-footer-name{{font-size:clamp(1.6rem,11vw,3.5rem)}}
      #vessel-iframe{{height:260px!important;max-height:260px!important;min-height:0}}
      #pred-chart{{height:200px!important}}
      #pred-table col:nth-child(4){{width:0!important}}
      #pred-table td:nth-child(4),#pred-table th:nth-child(4){{display:none}}
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
      <span class="logo-tagline">Market Dynamics</span>
    </div>
  </div>
  <nav class="header-nav">
    <a class="nav-link" href="#equities">Equities</a>
    <a class="nav-link" href="#sectors">Sectors</a>
    <a class="nav-link" href="#news">News</a>
    <a class="nav-link" href="#vessels">Data</a>
  </nav>
</header>
 
<!-- ── TICKER STRIP ── -->
<div class="ticker-strip">
  <span class="ticker-badge">Live</span>
  <div class="ticker-track" id="ticker-track">
    <span class="t-item" style="color:rgba(255,255,255,.4)">Loading live prices…</span>
  </div>
</div>
 
<main>
 
<!-- ══════════════════════════════════════════
     EQUITIES — US Live Prices + Stock Charts
═══════════════════════════════════════════ -->
<div class="section-divider" id="equities">
  <div class="section-divider-line"></div>
  <div class="section-label"><span class="dot" style="background:#26a69a"></span>Equities</div>
  <div class="section-divider-line"></div>
</div>

<div class="alpaca-panel">
  <div class="alpaca-header">
    <span class="alpaca-title">US EQUITIES · LIVE MARKET DATA</span>
    <span id="market-status-pill" class="market-pill closed">
      <span class="market-pill-dot" id="market-pill-dot" style="background:#e65100"></span>
      <span id="market-pill-text">Checking…</span>
    </span>
    <span class="alpaca-badge" id="alpaca-data-badge">Connecting…</span>
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
      <select id="alpaca-sort" class="alpaca-sort-select" onchange="document.getElementById('alpaca-grid').innerHTML='';renderAlpacaGrid()">
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
    <div style="text-align:center;padding:40px;color:#888">Loading live market data…</div>
  </div>

  <div class="alpaca-status">
    <div class="alpaca-led"></div>
    <span class="alpaca-status-text" id="alpaca-status-text">Connecting…</span>
    <span id="alpaca-last-update" style="font-size:.55rem;color:#aaa;margin-left:auto"></span>
  </div>

  <!-- ── Stock Chart Sub-section ── -->
  <div style="margin-top:28px;padding-top:22px;border-top:1px solid #e5e5e5">
    <div style="font-size:.6rem;font-weight:700;letter-spacing:.18em;text-transform:uppercase;color:#888;margin-bottom:16px">Stock Chart &amp; Analysis</div>

<div class="glass panel" style="border:none;padding:0;background:transparent;margin-bottom:0">
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

<div class="glass chart-card" style="margin-top:12px" id="chart-outer">
  <!-- ── Price header (populated by JS after page load) ── -->
  <div class="chart-price-hdr" id="chart-price-hdr">
    <div class="chart-price-row">
      <span class="chart-price-val" id="chart-cur-price">—</span>
      <span id="chart-chg-badge"></span>
    </div>
    <p class="chart-sym-label" id="chart-sym-label">{ticker}</p>
  </div>
  <!-- ── Controls: period buttons ── -->
  <div class="chart-controls-wrap">
    <div class="chart-period-bar" id="chart-period-bar">
      <button class="chart-period-btn" data-period="1mo"  onclick="chartPeriod(this)">1M</button>
      <button class="chart-period-btn" data-period="3mo"  onclick="chartPeriod(this)">3M</button>
      <button class="chart-period-btn" data-period="6mo"  onclick="chartPeriod(this)">6M</button>
      <button class="chart-period-btn" data-period="1y"   onclick="chartPeriod(this)">1Y</button>
      <button class="chart-period-btn" data-period="2y"   onclick="chartPeriod(this)">2Y</button>
      <button class="chart-period-btn" data-period="5y"   onclick="chartPeriod(this)">5Y</button>
    </div>
  </div>
  <!-- ── Chart plot ── -->
  <div class="chart-body-wrap">{content}</div>
  <!-- ── Highest / Lowest footer ── -->
  <div class="chart-controls-wrap" style="padding-top:0">
    <div class="chart-hl-bar" id="chart-hl-bar">
      <div class="chart-hl-btn">
        <span style="font-weight:400;color:#888">Highest</span>
        <span class="chart-hl-val" id="chart-high-val">—</span>
      </div>
      <div class="chart-hl-btn">
        <span style="font-weight:400;color:#888">Lowest</span>
        <span class="chart-hl-val" id="chart-low-val">—</span>
      </div>
    </div>
  </div>
</div>
  </div>
</div>

<!-- ══════════════════════════════════════════
     CRYPTO SECTION
═══════════════════════════════════════════ -->
<div class="section-divider" id="crypto">
  <div class="section-divider-line"></div>
  <div class="section-label"><span class="dot" style="background:#f7931a"></span>Crypto</div>
  <div class="section-divider-line"></div>
</div>

<div class="alpaca-panel">
  <div class="alpaca-header">
    <span class="alpaca-title">CRYPTO · LIVE MARKET DATA</span>
    <span class="alpaca-badge" id="crypto-data-badge">Connecting…</span>
  </div>

  <div class="alpaca-filter">
    <button class="alpaca-filter-btn active" onclick="setCryptoFilter('ALL')">ALL</button>
    <button class="alpaca-filter-btn" onclick="setCryptoFilter('Layer 1')">LAYER 1</button>
    <button class="alpaca-filter-btn" onclick="setCryptoFilter('Layer 2')">LAYER 2</button>
    <button class="alpaca-filter-btn" onclick="setCryptoFilter('Layer 0')">LAYER 0</button>
    <button class="alpaca-filter-btn" onclick="setCryptoFilter('DeFi')">DEFI</button>
    <button class="alpaca-filter-btn" onclick="setCryptoFilter('Oracle')">ORACLE</button>
    <button class="alpaca-filter-btn" onclick="setCryptoFilter('Meme')">MEME</button>
    <div class="alpaca-sort">
      <span class="alpaca-sort-label">SORT</span>
      <select id="crypto-sort" class="alpaca-sort-select" onchange="document.getElementById('crypto-grid').innerHTML='';renderCryptoGrid()">
        <option value="default">DEFAULT</option>
        <option value="price-desc">PRICE ↓</option>
        <option value="price-asc">PRICE ↑</option>
        <option value="chg-desc">GAIN ↓</option>
        <option value="chg-asc">LOSS ↓</option>
        <option value="vol-desc">VOLUME ↓</option>
      </select>
    </div>
  </div>

  <div id="crypto-grid" class="alpaca-grid crypto-grid">
    <div style="text-align:center;padding:40px;color:#888">Loading live crypto data…</div>
  </div>

  <div class="alpaca-status">
    <div class="alpaca-led"></div>
    <span class="alpaca-status-text" id="crypto-status-text">Connecting…</span>
    <span id="crypto-last-update" style="font-size:.55rem;color:#aaa;margin-left:auto"></span>
  </div>
</div>

<!-- ══════════════════════════════════════════
     GBM MONTE CARLO SIMULATION
═══════════════════════════════════════════ -->
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
<script>
(function(){{
  var Plotly = window.Plotly;
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
    // ── Palette — matches Starfish app theme exactly ──────────────────────────
    // Background: transparent (paper) / rgba(13,14,20,0) plot (matches stock chart)
    // Grid:   rgba(42,46,57,0.6)  — same as _C["grid"] in build_chart
    // Axis:   #787b86             — same as _C["axis"]
    // Paths:  cornflower rgba(100,149,237,0.18) — visible but not overwhelming
    // Band95: rgba(41,98,255,0.08)  — subtle outer cone (Starfish blue)
    // Band50: rgba(41,98,255,0.18)  — visible inner IQR band
    // Median: #f9a825 (amber/gold)  — same family as SMA20 in stock chart
    // Entry:  #787b86 dashed        — neutral axis colour, no red/green bias
    // Gain hist: #26a69a            — Starfish green
    // Loss hist: #ef5350            — Starfish red

    // Build real calendar x-axis: today + fractional years → Date strings
    var now = new Date();
    var tDates = d.t_axis.map(function(frac){{
      var ms = now.getTime() + frac * 365.25 * 24 * 3600 * 1000;
      return new Date(ms).toISOString().slice(0,10);
    }});

    // Shared layout — transparent bg, Starfish grid colours
    var LY = {{
      paper_bgcolor:'rgba(0,0,0,0)',
      plot_bgcolor:'rgba(0,0,0,0)',
      font:{{color:'#787b86', family:"'DM Sans',sans-serif", size:10}},
      margin:{{l:62, r:20, t:48, b:44}},
      xaxis:{{
        gridcolor:'rgba(42,46,57,0.6)', color:'#787b86',
        zeroline:false, showline:false,
        tickfont:{{size:9,color:'#787b86'}},
        tickformat:'%b %Y', type:'date'
      }},
      yaxis:{{
        gridcolor:'rgba(42,46,57,0.6)', color:'#787b86',
        zeroline:false, showline:false,
        tickfont:{{size:9,color:'#787b86'}}
      }},
      hovermode:'x unified',
      hoverlabel:{{bgcolor:'rgba(255,255,255,0.97)',bordercolor:'rgba(120,123,134,0.3)',
                   font:{{color:'#000',size:11}}}},
      legend:{{
        orientation:'h', y:1.07, x:0,
        font:{{size:9,color:'#787b86'}},
        bgcolor:'rgba(0,0,0,0)', borderwidth:0
      }}
    }};

    var t = tDates;
    var n = d.paths.length;

    // ── Per-timestep percentile arrays (computed once) ────────────────────────
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

    // 1. Individual paths — cornflower, alpha raised so they read on white bg
    for(var i=0;i<n;i++){{
      traces.push({{
        x:t, y:d.paths[i], mode:'lines',
        line:{{color:'rgba(100,149,237,0.18)', width:0.8}},
        showlegend:false, hoverinfo:'skip'
      }});
    }}

    // 2. P5–P95 outer cone — Starfish blue, subtle fill, no border line
    traces.push({{
      x:t, y:p95, mode:'lines',
      line:{{color:'rgba(0,0,0,0)', width:0}},
      showlegend:false, hoverinfo:'skip'
    }});
    traces.push({{
      x:t, y:p5, mode:'lines',
      line:{{color:'rgba(0,0,0,0)', width:0}},
      fill:'tonexty', fillcolor:'rgba(41,98,255,0.08)',
      showlegend:false, hoverinfo:'skip', name:'90% cone'
    }});

    // 3. P25–P75 inner IQR band — denser fill, clearly visible
    traces.push({{
      x:t, y:p75, mode:'lines',
      line:{{color:'rgba(0,0,0,0)', width:0}},
      showlegend:false, hoverinfo:'skip'
    }});
    traces.push({{
      x:t, y:p25, mode:'lines',
      line:{{color:'rgba(0,0,0,0)', width:0}},
      fill:'tonexty', fillcolor:'rgba(41,98,255,0.20)',
      showlegend:true, name:'50% band (IQR)', hoverinfo:'skip'
    }});

    // 4. P5 border — red dotted, 1.2px, fully opaque so it's readable
    traces.push({{
      x:t, y:p5, mode:'lines', name:'P5  (bear)',
      line:{{color:'#ef5350', width:1.2, dash:'dot'}},
      hovertemplate:'P5 <b>%{{y:.2f}}</b><extra></extra>'
    }});

    // 5. P95 border — green dotted, 1.2px
    traces.push({{
      x:t, y:p95, mode:'lines', name:'P95 (bull)',
      line:{{color:'#26a69a', width:1.2, dash:'dot'}},
      hovertemplate:'P95 <b>%{{y:.2f}}</b><extra></extra>'
    }});

    // 6. Median — amber #f9a825 (SMA20 family), 2.5px, on top of everything
    traces.push({{
      x:t, y:p50, mode:'lines', name:'Median (P50)',
      line:{{color:'#f9a825', width:2.5}},
      hovertemplate:'Median <b>%{{y:.2f}}</b><extra></extra>'
    }});

    // 7. Entry price — neutral grey dashed, clearly labelled
    traces.push({{
      x:[t[0],t[t.length-1]], y:[d.s_0,d.s_0],
      mode:'lines', name:'Entry ' + d.s_0.toFixed(2),
      line:{{color:'#787b86', width:1.5, dash:'dash'}},
      hoverinfo:'skip'
    }});

    var currency = (d.ticker.endsWith('.NS')||d.ticker.endsWith('.BO')) ? 'INR' : 'USD';

    Plotly.react('gbm-chart', traces, Object.assign({{}}, LY, {{
      title:{{
        text:'<b style="color:#d1d4dc">' + d.ticker + '</b>' +
             '<span style="color:#787b86">  Monte Carlo GBM · ' +
             d.n_years + 'y horizon · ' + d.n_scenarios + ' paths</span>',
        font:{{size:11}}, x:0.01, xanchor:'left'
      }},
      yaxis: Object.assign({{}}, LY.yaxis, {{
        title:{{text:currency, font:{{size:10,color:'#787b86'}}, standoff:8}}
      }}),
      xaxis: Object.assign({{}}, LY.xaxis, {{
        title:{{text:'Date', font:{{size:10,color:'#787b86'}}, standoff:8}}
      }})
    }}), {{responsive:true}});

    // ── Histogram — red/teal split, 35 bins, solid bars with border ──────────
    var terminal = d.terminal;
    var loss = terminal.filter(function(v){{return v <  d.s_0;}});
    var gain = terminal.filter(function(v){{return v >= d.s_0;}});
    // Use same bin size for both so the bars interleave cleanly
    var allMin = Math.min.apply(null,terminal);
    var allMax = Math.max.apply(null,terminal);
    var nBins  = 35;
    var bSize  = (allMax - allMin) / nBins;

    var histTraces = [
      {{
        x: loss, type:'histogram',
        xbins:{{start:allMin, end:d.s_0, size:bSize}},
        marker:{{
          color:'rgba(239,83,80,0.75)',
          line:{{color:'rgba(239,83,80,0.4)', width:1}}
        }},
        name:'Below entry', hovertemplate:'%{{x:.2f}}  Count: %{{y}}<extra>Loss</extra>'
      }},
      {{
        x: gain, type:'histogram',
        xbins:{{start:d.s_0, end:allMax+bSize, size:bSize}},
        marker:{{
          color:'rgba(38,166,154,0.75)',
          line:{{color:'rgba(38,166,154,0.4)', width:1}}
        }},
        name:'Above entry', hovertemplate:'%{{x:.2f}}  Count: %{{y}}<extra>Gain</extra>'
      }}
    ];

    Plotly.react('gbm-hist', histTraces, Object.assign({{}}, LY, {{
      barmode:'overlay',
      title:{{
        text:'<b style="color:#d1d4dc">Terminal Distribution</b>' +
             '<span style="color:#787b86">  (Year ' + d.n_years + ')</span>',
        font:{{size:11}}, x:0.01, xanchor:'left'
      }},
      xaxis: Object.assign({{}}, LY.xaxis, {{
        type:'linear', tickformat:'',
        title:{{text:currency + ' at expiry', font:{{size:10,color:'#787b86'}}, standoff:8}}
      }}),
      yaxis: Object.assign({{}}, LY.yaxis, {{
        title:{{text:'Count', font:{{size:10,color:'#787b86'}}, standoff:8}}
      }}),
      shapes:[{{
        type:'line', x0:d.s_0, x1:d.s_0, y0:0, y1:1, yref:'paper',
        line:{{color:'#787b86', width:1.5, dash:'dash'}}
      }}],
      annotations:[{{
        x:d.s_0, y:1.05, yref:'paper', xanchor:'center',
        text:'<b>Entry ' + d.s_0.toFixed(2) + '</b>',
        showarrow:false, font:{{size:9, color:'#787b86'}}
      }}]
    }}), {{responsive:true}});

    // ── Stats bar — matches Starfish chip/badge styling ───────────────────────
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
}}());
</script>

<!-- AI Analysis -->
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
 
<!-- ══════════════════════════════════════════
     PREDICTION MARKETS
═══════════════════════════════════════════ -->
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
        </tr>
      </thead>
      <tbody id="pred-tbody"></tbody>
    </table>
  </div>
  <div id="pred-empty" style="display:none;text-align:center;padding:40px 20px;color:#888;font-size:.85rem">No matching markets found.</div>
</div>

<!-- ══════════════════════════════════════════
     SECTION 2: SECTORS
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
     SECTION 3: NEWS
═══════════════════════════════════════════ -->
<div class="section-divider" id="news">
  <div class="section-divider-line"></div>
  <div class="section-label"><span class="dot" style="background:#000"></span>News</div>
  <div class="section-divider-line"></div>
</div>
 
<div class="glass news-panel">
  <div class="panel-label">Financial News</div>
  <div class="news-tabs" id="ntabs">{ntabs}</div>
  <div class="news-iframe-wrap">
    <div id="nload" class="news-loading"><div class="news-spinner"></div><span>Loading&hellip;</span></div>
    <iframe id="nframe" allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture" allowfullscreen style="display:none"></iframe>
  </div>
  <div style="margin-top:10px;display:flex;align-items:center;gap:10px;flex-wrap:wrap;">
    <span id="nbadge" class="nsb" style="display:none"></span>
  </div>
</div>

<!-- ══════════════════════════════════════════
     SECTION 4: LIVE VESSEL TRACKER
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
    <button id="ais-region-btn" onclick="toggleAISRegion()" style="font-size:.58rem;font-weight:700;letter-spacing:.08em;text-transform:uppercase;padding:3px 12px;border-radius:20px;border:1px solid rgba(100,180,255,.4);background:rgba(100,180,255,.07);color:#4499cc;cursor:pointer;font-family:inherit;transition:all .2s;">&#9974; Select Region</button>
    <span id="ais-vessel-badge" style="margin-left:auto;font-size:.58rem;font-weight:600;letter-spacing:.08em;text-transform:uppercase;color:#555;background:#f4f4f4;border:1px solid #e0e0e0;border-radius:20px;padding:3px 10px;">Stopped</span>
  </div>
  <iframe id="vessel-iframe" src="/vessels" style="width:100%;height:660px;border:none;display:block;" title="Live Vessel Tracker" loading="lazy"></iframe>
  <script>
  var _aisRunning = false;
  var _aisRegionActive = false;
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
  function toggleAISRegion() {{
    var btn = document.getElementById('ais-region-btn');
    var iframe = document.getElementById('vessel-iframe');
    if (!_aisRegionActive) {{
      _aisRegionActive = true;
      btn.textContent = '✕ Clear Region';
      btn.style.borderColor = 'rgba(255,170,50,.6)';
      btn.style.background = 'rgba(255,170,50,.1)';
      btn.style.color = '#ffaa33';
      iframe.contentWindow.postMessage('ais:region:start', '*');
    }} else {{
      _aisRegionActive = false;
      btn.innerHTML = '&#9974; Select Region';
      btn.style.borderColor = 'rgba(100,180,255,.4)';
      btn.style.background = 'rgba(100,180,255,.07)';
      btn.style.color = '#4499cc';
      iframe.contentWindow.postMessage('ais:region:clear', '*');
    }}
  }}
  // Reset button if iframe clears region via escape
  window.addEventListener('message', function(e) {{
    if (e.data === 'ais:region:cancelled') {{
      _aisRegionActive = false;
      var btn = document.getElementById('ais-region-btn');
      if (btn) {{ btn.innerHTML = '&#9974; Select Region'; btn.style.borderColor='rgba(100,180,255,.4)'; btn.style.background='rgba(100,180,255,.07)'; btn.style.color='#4499cc'; }}
    }}
  }});
  </script>
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
    <button id="adsb-region-btn" onclick="toggleADSBRegion()" style="font-size:.58rem;font-weight:700;letter-spacing:.08em;text-transform:uppercase;padding:3px 12px;border-radius:20px;border:1px solid rgba(100,180,255,.4);background:rgba(100,180,255,.07);color:#4499cc;cursor:pointer;font-family:inherit;transition:all .2s;">&#9974; Select Region</button>
    <span id="adsb-aircraft-badge" style="font-size:.58rem;font-weight:600;letter-spacing:.08em;text-transform:uppercase;color:#555;background:#f4f4f4;border:1px solid #e0e0e0;border-radius:20px;padding:3px 10px;">Stopped</span>
  </div>
  <iframe id="aircraft-iframe" src="/aircraft" style="width:100%;height:660px;border:none;display:block;" title="Live Aircraft Tracker"></iframe>
  <script>
  var _adsbRunning = false;
  var _adsbIframeReady = false;
  var _adsbPendingCmd = null;
  var _adsbRegionActive = false;
  var _adsbIframe = document.getElementById('aircraft-iframe');
  // Mark iframe ready after load so postMessage is never lost
  _adsbIframe.addEventListener('load', function() {{
    _adsbIframeReady = true;
    if (_adsbPendingCmd) {{
      _adsbIframe.contentWindow.postMessage(_adsbPendingCmd, '*');
      _adsbPendingCmd = null;
    }}
  }});
  // Listen for badge updates FROM the iframe (handled in combined listener below)
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
  function toggleADSBRegion() {{
    var btn = document.getElementById('adsb-region-btn');
    if (!_adsbRegionActive) {{
      _adsbRegionActive = true;
      btn.textContent = '✕ Clear Region';
      btn.style.borderColor = 'rgba(255,170,50,.6)';
      btn.style.background = 'rgba(255,170,50,.1)';
      btn.style.color = '#ffaa33';
      _sendAdsbMsg('adsb:region:start');
    }} else {{
      _adsbRegionActive = false;
      btn.innerHTML = '&#9974; Select Region';
      btn.style.borderColor = 'rgba(100,180,255,.4)';
      btn.style.background = 'rgba(100,180,255,.07)';
      btn.style.color = '#4499cc';
      _sendAdsbMsg('adsb:region:clear');
    }}
  }}
  // Reset region button if iframe cancels via Escape
  window.addEventListener('message', function(eAdsbR) {{
    if (eAdsbR.data && eAdsbR.data.type === 'adsb:count') {{
      var badge = document.getElementById('adsb-aircraft-badge');
      if (badge) badge.textContent = eAdsbR.data.count + ' live';
    }}
    if (eAdsbR.data === 'adsb:region:cancelled') {{
      _adsbRegionActive = false;
      var rBtn = document.getElementById('adsb-region-btn');
      if (rBtn) {{ rBtn.innerHTML = '&#9974; Select Region'; rBtn.style.borderColor='rgba(100,180,255,.4)'; rBtn.style.background='rgba(100,180,255,.07)'; rBtn.style.color='#4499cc'; }}
    }}
  }});
  </script>
</div>

<!-- ══════════════════════════════════════════
     SECTION 5: LIVE SATELLITE IMAGERY
═══════════════════════════════════════════ -->
<div class="section-divider" id="satellite-viewer">
  <div class="section-divider-line"></div>
  <div class="section-label"><span class="dot" style="background:#000"></span>Live Satellite Imagery</div>
  <div class="section-divider-line"></div>
</div>

<div class="glass sat-viewer-panel">
  <!-- Toolbar -->
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

  <!-- Layer buttons -->
  <div class="sat-layer-grid" style="margin-top:12px;">
    <button class="sat-vlayer-btn active" data-layer="TRUE-COLOR" onclick="satSelectLayer(this)">TRUE COLOR</button>
    <button class="sat-vlayer-btn" data-layer="FALSE-COLOR" onclick="satSelectLayer(this)">FALSE COLOR</button>
    <button class="sat-vlayer-btn" data-layer="NDVI" onclick="satSelectLayer(this)">NDVI</button>
    <button class="sat-vlayer-btn" data-layer="SWIR" onclick="satSelectLayer(this)">SWIR</button>
    <button class="sat-vlayer-btn" data-layer="GEOLOGY" onclick="satSelectLayer(this)">GEOLOGY</button>
  </div>

  <!-- Map -->
  <div class="sat-viewer-map-wrap">
    <div id="satMap" class="sat-viewer-map" style="width:100%;height:100%;"></div>
  </div>

  <!-- Controls -->
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

  <!-- Status + log -->
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
      <span class="disclaimer-label">Disclaimer</span>Financial information is sourced from Yahoo Finance, FRED (Federal Reserve Bank of St. Louis), Google Trends, public AIS shipping data, and open data providers — presented solely for informational and educational purposes. AI analyses powered by DeepSeek, Qwen, and Meta&rsquo;s Llama via OpenRouter using live macro data, fundamentals, and search-interest signals. Sector news aggregated from Reuters, CNBC, WSJ, Yahoo Finance, MarketWatch, FT, Benzinga, and Seeking Alpha. Not financial advice. Consult qualified professionals before making investment decisions.
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
var sectorArticles = [];
 
// ── ALPACA LIVE TRADING JAVASCRIPT ──────────────────────────────────────────
var alpacaAllStocks = [];
var alpacaFilter = 'ALL';
var alpacaPrevPrices = {{}};

// ── US MARKET HOURS (NYSE/NASDAQ) ────────────────────────────────────────────
function getMarketStatus() {{
  // All times in US/Eastern
  var now = new Date();
  var etStr = now.toLocaleString('en-US', {{timeZone:'America/New_York'}});
  var et = new Date(etStr);
  var day = et.getDay(); // 0=Sun,6=Sat
  var h = et.getHours();
  var m = et.getMinutes();
  var mins = h * 60 + m;

  if (day === 0 || day === 6) return {{state:'closed', label:'Market Closed', next:'Opens Monday 9:30 AM ET'}};

  // Pre-market: 4:00–9:30
  if (mins >= 240 && mins < 570)  return {{state:'pre',    label:'Pre-Market',    next:'Opens ' + fmtCountdown(et, 570)}};
  // Regular: 9:30–16:00
  if (mins >= 570 && mins < 960)  return {{state:'open',   label:'Market Open',   next:'Closes ' + fmtCountdown(et, 960)}};
  // After-hours: 16:00–20:00
  if (mins >= 960 && mins < 1200) return {{state:'pre',    label:'After-Hours',   next:'Closes ' + fmtCountdown(et, 1200)}};
  // Closed
  var nextOpen = day === 5 ? 'Monday' : 'Tomorrow';
  return {{state:'closed', label:'Market Closed', next:'Opens ' + nextOpen + ' 9:30 AM ET'}};
}}

function fmtCountdown(et, targetMins) {{
  var cur = et.getHours() * 60 + et.getMinutes();
  var diff = targetMins - cur;
  if (diff <= 0) return '';
  var hh = Math.floor(diff / 60);
  var mm = diff % 60;
  return 'in ' + (hh ? hh + 'h ' : '') + mm + 'm';
}}

function updateMarketStatusPill() {{
  var s = getMarketStatus();
  var pill = document.getElementById('market-status-pill');
  var dot  = document.getElementById('market-pill-dot');
  var txt  = document.getElementById('market-pill-text');
  var led  = document.querySelector('.alpaca-led');
  if (!pill) return;

  // Reset classes
  pill.classList.remove('open','closed','pre');
  pill.classList.add(s.state === 'open' ? 'open' : s.state === 'pre' ? 'pre' : 'closed');

  var dotColor = s.state === 'open' ? '#2e7d32' : s.state === 'pre' ? '#1565c0' : '#e65100';
  dot.style.background = dotColor;
  txt.textContent = s.label + (s.next ? '  ·  ' + s.next : '');

  // Sync the LED in the status bar
  if (led) {{
    led.classList.toggle('closed', s.state !== 'open');
  }}
}}

// Run immediately and refresh every minute
updateMarketStatusPill();
setInterval(updateMarketStatusPill, 60000);

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
  // Clear so renderAlpacaGrid performs a full DOM build for the new filter
  document.getElementById('alpaca-grid').innerHTML = '';
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

  // ── First render: build all cards from scratch (no flicker risk on init) ──
  const existing = grid.querySelector('.alpaca-card');
  if (!existing) {{
    grid.innerHTML = stocks.map(s => {{
      const dir = s.change_pct > 0 ? 'up' : (s.change_pct < 0 ? 'down' : '');
      const sign = s.change_pct >= 0 ? '+' : '';
      const changeClass = s.change_pct > 0 ? 'up-t' : (s.change_pct < 0 ? 'down-t' : 'flat-t');
      return `<div class="alpaca-card ${{dir}}" id="acard-${{s.symbol}}">
        <div class="alpaca-card-sym">${{s.symbol}}</div>
        <div class="alpaca-card-name">${{s.name}}</div>
        <div class="alpaca-price-row">
          <div class="alpaca-price" id="ap-${{s.symbol}}">$${{s.price ? s.price.toFixed(2) : '—'}}</div>
          <div class="alpaca-change ${{changeClass}}" id="ac-${{s.symbol}}">${{sign}}${{s.change_pct ? s.change_pct.toFixed(2) : '0.00'}}%</div>
        </div>
        <div class="alpaca-bidask">
          <div class="alpaca-ba alpaca-bid">
            <div class="alpaca-ba-label">BID</div>
            <div class="alpaca-ba-price" id="abid-${{s.symbol}}">$${{s.bid ? s.bid.toFixed(2) : '—'}}</div>
            <div class="alpaca-ba-size" id="abidsz-${{s.symbol}}">${{s.bid_size ? s.bid_size.toLocaleString() : ''}}</div>
          </div>
          <div class="alpaca-ba alpaca-ask">
            <div class="alpaca-ba-label">ASK</div>
            <div class="alpaca-ba-price" id="aask-${{s.symbol}}">$${{s.ask ? s.ask.toFixed(2) : '—'}}</div>
            <div class="alpaca-ba-size" id="aasksz-${{s.symbol}}">${{s.ask_size ? s.ask_size.toLocaleString() : ''}}</div>
          </div>
        </div>
        <div class="alpaca-footer">
          <div class="alpaca-vol" id="avol-${{s.symbol}}">VOL ${{s.volume ? s.volume.toLocaleString() : '—'}}</div>
          <div class="alpaca-dtype ${{s.data_type}}" id="adt-${{s.symbol}}">${{s.data_type}}</div>
        </div>
      </div>`;
    }}).join('');
    stocks.forEach(s => {{ alpacaPrevPrices[s.symbol] = s.price; }});
    return;
  }}

  // ── Subsequent renders: patch only changed values in-place, zero layout shift ──
  function setText(id, val) {{
    const el = document.getElementById(id);
    if (el && el.textContent !== val) el.textContent = val;
  }}
  function setAttr(id, attr, val) {{
    const el = document.getElementById(id);
    if (el && el.getAttribute(attr) !== val) el.setAttribute(attr, val);
  }}

  stocks.forEach(s => {{
    const card = document.getElementById('acard-' + s.symbol);
    if (!card) return; // card not yet in DOM (filter change) — skip

    const dir = s.change_pct > 0 ? 'up' : (s.change_pct < 0 ? 'down' : '');
    const sign = s.change_pct >= 0 ? '+' : '';
    const changeClass = s.change_pct > 0 ? 'up-t' : (s.change_pct < 0 ? 'down-t' : 'flat-t');

    // Card direction class
    const wantClass = 'alpaca-card' + (dir ? ' ' + dir : '');
    if (card.className !== wantClass) card.className = wantClass;

    // Text patches — only writes if value actually changed
    setText('ap-' + s.symbol,     '$' + (s.price     ? s.price.toFixed(2)     : '—'));
    setText('ac-' + s.symbol,     sign + (s.change_pct ? s.change_pct.toFixed(2) : '0.00') + '%');
    setText('abid-' + s.symbol,   '$' + (s.bid       ? s.bid.toFixed(2)       : '—'));
    setText('abidsz-' + s.symbol, s.bid_size ? s.bid_size.toLocaleString() : '');
    setText('aask-' + s.symbol,   '$' + (s.ask       ? s.ask.toFixed(2)       : '—'));
    setText('aasksz-' + s.symbol, s.ask_size ? s.ask_size.toLocaleString() : '');
    setText('avol-' + s.symbol,   'VOL ' + (s.volume ? s.volume.toLocaleString() : '—'));

    // Change class on the pct element
    const chgEl = document.getElementById('ac-' + s.symbol);
    if (chgEl && chgEl.className !== 'alpaca-change ' + changeClass)
      chgEl.className = 'alpaca-change ' + changeClass;

    // Data-type badge
    const dtEl = document.getElementById('adt-' + s.symbol);
    if (dtEl) {{
      if (dtEl.textContent !== s.data_type) dtEl.textContent = s.data_type;
      if (dtEl.className !== 'alpaca-dtype ' + s.data_type) dtEl.className = 'alpaca-dtype ' + s.data_type;
    }}

    // Flash on price change — no layout impact
    if (alpacaPrevPrices[s.symbol] !== undefined && alpacaPrevPrices[s.symbol] !== s.price) {{
      const cls = s.price > alpacaPrevPrices[s.symbol] ? 'flash-up' : 'flash-down';
      card.classList.add(cls);
      setTimeout(() => card.classList.remove(cls), 800);
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
      document.getElementById('alpaca-data-badge').textContent = 'Unavailable';
      return;
    }}
    alpacaAllStocks = data.stocks || [];
    renderAlpacaGrid();
    updateTickerStrip(alpacaAllStocks);
    document.getElementById('alpaca-last-update').textContent = data.updated;
    document.getElementById('alpaca-status-text').textContent = 'WebSocket live · ' + alpacaAllStocks.length + ' symbols';
    // Update the header badge to reflect the actual dominant data type
    var typeCounts = {{}};
    alpacaAllStocks.forEach(function(s) {{ typeCounts[s.data_type] = (typeCounts[s.data_type] || 0) + 1; }});
    var dominantType = Object.keys(typeCounts).sort(function(a,b){{ return typeCounts[b]-typeCounts[a]; }})[0] || '—';
    var badgeLabels = {{LIVE:'Live Feed', TRADE:'Trade Data', QUOTE:'Quote Data', BAR:'Bar Data (Delayed)', YFIN:'Delayed (yfinance)'}};
    document.getElementById('alpaca-data-badge').textContent = badgeLabels[dominantType] || dominantType;
  }} catch(e) {{
    console.error('Alpaca fetch error:', e);
    document.getElementById('alpaca-status-text').textContent = 'Connection error — retrying';
    document.getElementById('alpaca-data-badge').textContent = 'Offline';
  }}
}}

function updateTickerStrip(stocks) {{
  if (!stocks || !stocks.length) return;
  var track = document.getElementById('ticker-track');
  if (!track) return;
  // Build one set of items, then duplicate for seamless loop
  function buildItems(list) {{
    return list.map(function(s) {{
      var sign = s.change_pct >= 0 ? '+' : '';
      var dir = s.change_pct > 0 ? 'up' : (s.change_pct < 0 ? 'down' : '');
      var price = s.price ? s.price.toFixed(2) : '—';
      var chg = s.change_pct ? sign + s.change_pct.toFixed(2) + '%' : '0.00%';
      return '<span class="t-item"><strong>' + s.symbol + '</strong> $' + price +
             ' <span class="t-' + dir + '">' + chg + '</span>' +
             ' <span class="t-sep">&middot;</span></span>';
    }}).join('');
  }}
  var html = buildItems(stocks) + buildItems(stocks);
  track.innerHTML = html;
  // Reset animation so new content scrolls from start
  track.style.animation = 'none';
  track.offsetHeight; // reflow
  track.style.animation = '';
}}


// ── Chart period buttons & price header ─────────────────────────────────────
(function initChartUI(){{
  // Mark the active period button matching the current form selection
  var curPeriod = document.getElementById('period') ? document.getElementById('period').value : '3mo';
  document.querySelectorAll('.chart-period-btn').forEach(function(btn){{
    if(btn.dataset.period === curPeriod) btn.classList.add('active');
  }});

  // Populate price header & high/low from Plotly trace data (if chart rendered)
  var plotDiv = document.querySelector('.chart-body-wrap .js-plotly-plot');
  if(plotDiv && plotDiv.data && plotDiv.data.length){{
    var trace = plotDiv.data[0];
    var yArr = trace.y || trace.close || [];
    if(yArr.length){{
      var lastPrice = yArr[yArr.length-1];
      var firstPrice= yArr[0];
      var maxPrice  = Math.max.apply(null, yArr.filter(function(v){{return v!=null && !isNaN(v)}}));
      var minPrice  = Math.min.apply(null, yArr.filter(function(v){{return v!=null && !isNaN(v)}}));
      var chg = firstPrice ? ((lastPrice - firstPrice)/firstPrice)*100 : 0;
      var currency = (document.getElementById('ticker').value||'').toUpperCase().endsWith('.NS') ||
                     (document.getElementById('ticker').value||'').toUpperCase().endsWith('.BO') ? '₹' : '$';

      var priceEl = document.getElementById('chart-cur-price');
      if(priceEl) priceEl.textContent = currency + lastPrice.toLocaleString(undefined,{{minimumFractionDigits:2,maximumFractionDigits:2}});

      var badgeEl = document.getElementById('chart-chg-badge');
      if(badgeEl){{
        var arrow = chg>=0
          ? '<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M6 18L18 6m0 0H9m9 0v9"/></svg>'
          : '<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M6 6l12 12m0 0H9m9 0V9"/></svg>';
        badgeEl.className = chg>=0 ? 'chart-badge-up' : 'chart-badge-dn';
        badgeEl.innerHTML = arrow + Math.abs(chg).toFixed(2) + '%';
      }}

      var symEl = document.getElementById('chart-sym-label');
      var tkr = (document.getElementById('ticker').value||'').toUpperCase();
      if(symEl) symEl.textContent = tkr;

      var hiEl = document.getElementById('chart-high-val');
      var loEl = document.getElementById('chart-low-val');
      if(hiEl) hiEl.textContent = currency + maxPrice.toLocaleString(undefined,{{minimumFractionDigits:2,maximumFractionDigits:2}});
      if(loEl) loEl.textContent = currency + minPrice.toLocaleString(undefined,{{minimumFractionDigits:2,maximumFractionDigits:2}});
    }}
  }}
}})();

function chartPeriod(btn){{
  document.querySelectorAll('.chart-period-btn').forEach(function(b){{b.classList.remove('active');}});
  btn.classList.add('active');
  document.getElementById('period').value = btn.dataset.period;
  document.getElementById('main-form').submit();
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
 
// ── AI model selection ────────────────────────────────────────────────────────
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
  res.innerHTML=`<div class="ai-loading">
    <div class="ai-spin"></div>
    <div class="ai-load-txt">Fetching live data &amp; running AI analysis\u2026</div>
    <div class="ai-load-sub">Pulling FRED macro data, Google Trends, fundamentals, 10+ technical indicators &mdash; building institutional-grade analysis (30\u201360s)</div>
  </div>`;
 
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
function fn(v,d){{d=d||2;return(v==null||v===undefined)?'N/A':Number(v).toFixed(d);}}
 
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
 
// ── Prediction Markets ────────────────────────────────────────────────────────
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

// ── Sector news ───────────────────────────────────────────────────────────────
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
  // reset satellite panel immediately
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
    // Now load satellite targets below news
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
 
// ── YouTube live news ─────────────────────────────────────────────────────────
var nframe=document.getElementById('nframe'),nload=document.getElementById('nload'),
    nbadge=document.getElementById('nbadge'),curHandle=null;
 
function nSetLoad(m){{nframe.style.display='none';nload.innerHTML='<div class="news-spinner"></div><span>'+m+'</span>';nload.style.display='flex';nbadge.style.display='none';}}
function nSetErr(m){{nframe.style.display='none';nload.innerHTML='<span>'+m+'</span>';nload.style.display='flex';nbadge.className='nsb error';nbadge.textContent='Unavailable';nbadge.style.display='inline-flex';}}
 
function nUseFallback(h,channelId){{
  /* Always-available fallback: embed the channel live stream directly.
     The live_stream embed redirects to the active live or channel page —
     either way the iframe always renders something and never errors. */
  if(h!==curHandle)return;
  var src=channelId
    ?'https://www.youtube.com/embed/live_stream?channel='+channelId+'&autoplay=0&rel=0&modestbranding=1'
    :'https://www.youtube.com/embed/live_stream?channel='+encodeURIComponent(h)+'&autoplay=0&rel=0&modestbranding=1';
  nframe.src=src;
  nframe.style.display='block';nload.style.display='none';
  nbadge.style.display='inline-flex';
  nbadge.className='nsb latest';nbadge.textContent='Live';
}}
 
function loadCh(h){{
  if(curHandle===h)return;
  curHandle=h; nSetLoad('Loading\u2026'); nframe.src='about:blank';
  fetch('/api/live-id?handle='+encodeURIComponent(h))
    .then(r=>{{return r.json();}})
    .then(d=>{{
      if(h!==curHandle)return;
      if(d.video_id){{
        nframe.src='https://www.youtube.com/embed/'+d.video_id+'?autoplay=0&rel=0&modestbranding=1';
        nframe.style.display='block';nload.style.display='none';
        nbadge.style.display='inline-flex';
        nbadge.className=d.is_live?'nsb live':'nsb latest';
        nbadge.textContent=d.is_live?'LIVE':'Latest Video';
      }}else{{
        /* video_id null — server returned channel_id sentinel, use embed fallback */
        nUseFallback(h,d.channel_id||null);
      }}
    }}).catch(()=>{{nUseFallback(h,null);}});
}}
 
document.getElementById('ntabs').addEventListener('click',function(e){{
  var btn=e.target.closest('.news-tab');if(!btn)return;
  document.querySelectorAll('.news-tab').forEach(t=>t.classList.remove('active'));
  btn.classList.add('active');curHandle=null;loadCh(btn.dataset.handle);
}});
 
loadCh('{fh}');

// ── Satellite Imagery ─────────────────────────────────────────────────────────
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


// ── LIVE SATELLITE VIEWER ──────────────────────────────────────────────────
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
  // Set default dates on first start
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

(function initSatViewer() {{
  // Dates will be set on Start — nothing auto-runs here
}})();

var _satMap = null, _satLayer = null, _satCurrentLayer = 'TRUE-COLOR';

function _satInitMap() {{
  _satMap = L.map('satMap', {{ center: [20, 77], zoom: 5, zoomControl: true, attributionControl: false }});
  L.tileLayer('https://{{s}}.basemaps.cartocdn.com/light_all/{{z}}/{{x}}/{{y}}{{r}}.png', {{ maxZoom: 19, subdomains: 'abcd' }}).addTo(_satMap);
  _satMap.on('mousemove', function(e) {{}});
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

// Satellite search
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

// Initialize Alpaca feeds
fetchAlpacaStocks();
setInterval(fetchAlpacaStocks, 15000);

// ── CRYPTO ────────────────────────────────────────────────────────────────────
var cryptoAllCoins = [];
var cryptoFilter = 'ALL';
var cryptoPrevPrices = {{}};

function setCryptoFilter(f) {{
  cryptoFilter = f;
  document.querySelectorAll('#crypto .alpaca-filter-btn').forEach(btn => {{
    const t = btn.textContent.trim();
    const match = (f === 'ALL' && t === 'ALL') ||
                  (f === 'Layer 1' && t === 'LAYER 1') ||
                  (f === 'Layer 2' && t === 'LAYER 2') ||
                  (f === 'Layer 0' && t === 'LAYER 0') ||
                  (f === 'DeFi' && t === 'DEFI') ||
                  (f === 'Oracle' && t === 'ORACLE') ||
                  (f === 'Meme' && t === 'MEME');
    btn.classList.toggle('active', match);
  }});
  document.getElementById('crypto-grid').innerHTML = '';
  renderCryptoGrid();
}}

function renderCryptoGrid() {{
  let coins = [...cryptoAllCoins];
  if (cryptoFilter !== 'ALL') coins = coins.filter(c => c.category === cryptoFilter);

  const sortVal = document.getElementById('crypto-sort').value;
  if (sortVal === 'price-desc') coins.sort((a,b) => b.price - a.price);
  else if (sortVal === 'price-asc') coins.sort((a,b) => a.price - b.price);
  else if (sortVal === 'chg-desc') coins.sort((a,b) => b.change_pct - a.change_pct);
  else if (sortVal === 'chg-asc') coins.sort((a,b) => a.change_pct - b.change_pct);
  else if (sortVal === 'vol-desc') coins.sort((a,b) => (b.volume || 0) - (a.volume || 0));

  const grid = document.getElementById('crypto-grid');
  if (!coins.length) {{
    grid.innerHTML = '<div style="text-align:center;padding:40px;color:#888">No coins match filter</div>';
    return;
  }}

  const fmtPrice = v => {{
    if (v === null || v === undefined || isNaN(v)) return '—';
    const n = Number(v);
    return '$' + (Math.abs(n) >= 1 ? n.toLocaleString(undefined, {{minimumFractionDigits:2, maximumFractionDigits:2}}) : n.toPrecision(4));
  }};
  const fmtLarge = v => {{
    if (v === null || v === undefined || isNaN(v)) return '—';
    const n = Number(v);
    const abs = Math.abs(n);
    if (abs >= 1e12) return '$' + (n / 1e12).toFixed(2) + 'T';
    if (abs >= 1e9) return '$' + (n / 1e9).toFixed(2) + 'B';
    if (abs >= 1e6) return '$' + (n / 1e6).toFixed(2) + 'M';
    if (abs >= 1e3) return '$' + (n / 1e3).toFixed(2) + 'K';
    return '$' + n.toLocaleString(undefined, {{maximumFractionDigits: 2}});
  }};

  const existing = grid.querySelector('.crypto-card');
  if (!existing) {{
    grid.innerHTML = coins.map(c => {{
      const dir = c.change_pct > 0 ? 'up' : (c.change_pct < 0 ? 'down' : '');
      const sign = c.change_pct >= 0 ? '+' : '';
      const changeClass = c.change_pct > 0 ? 'up-t' : (c.change_pct < 0 ? 'down-t' : 'flat-t');
      const sym = c.symbol.replace('/', '');
      return `<div class="crypto-card ${{dir}}" id="ccard-${{sym}}">
        <div class="crypto-top">
          <div>
            <div class="crypto-card-sym">${{c.symbol}}</div>
            <div class="crypto-card-name">${{c.name}}</div>
          </div>
          <div class="crypto-source-pill">CoinGecko</div>
        </div>
        <div class="crypto-price-row">
          <div class="crypto-price" id="cp-${{sym}}">${{fmtPrice(c.price)}}</div>
          <div class="crypto-change ${{changeClass}}" id="cc-${{sym}}">${{sign}}${{c.change_pct ? c.change_pct.toFixed(2) : '0.00'}}%</div>
        </div>
        <div class="crypto-stats">
          <div class="crypto-stat">
            <span class="crypto-stat-label">Market Cap</span>
            <span class="crypto-stat-value" id="cmcap-${{sym}}">${{fmtLarge(c.market_cap)}}</span>
          </div>
          <div class="crypto-stat">
            <span class="crypto-stat-label">24H Volume</span>
            <span class="crypto-stat-value" id="cvol-${{sym}}">${{fmtLarge(c.volume)}}</span>
          </div>
          <div class="crypto-stat">
            <span class="crypto-stat-label">Updated</span>
            <span class="crypto-stat-value" id="cupd-${{sym}}">${{c.timestamp || '—'}}</span>
          </div>
        </div>
        <div class="crypto-footer">
          <div class="crypto-source" id="csrc-${{sym}}">${{c.source || 'CoinGecko Live Data'}}</div>
        </div>
      </div>`;
    }}).join('');
    coins.forEach(c => {{ cryptoPrevPrices[c.symbol] = c.price; }});
    return;
  }}

  function setText(id, val) {{ const el = document.getElementById(id); if (el && el.textContent !== val) el.textContent = val; }}

  coins.forEach(c => {{
    const sym = c.symbol.replace('/', '');
    const card = document.getElementById('ccard-' + sym);
    if (!card) return;

    const dir = c.change_pct > 0 ? 'up' : (c.change_pct < 0 ? 'down' : '');
    const sign = c.change_pct >= 0 ? '+' : '';
    const changeClass = c.change_pct > 0 ? 'up-t' : (c.change_pct < 0 ? 'down-t' : 'flat-t');
    const wantClass = 'crypto-card' + (dir ? ' ' + dir : '');
    if (card.className !== wantClass) card.className = wantClass;

    const fmtPrice = v => {{
      if (v === null || v === undefined || isNaN(v)) return '—';
      const n = Number(v);
      return '$' + (Math.abs(n) >= 1 ? n.toLocaleString(undefined, {{minimumFractionDigits:2, maximumFractionDigits:2}}) : n.toPrecision(4));
    }};
    const fmtLarge = v => {{
      if (v === null || v === undefined || isNaN(v)) return '—';
      const n = Number(v);
      const abs = Math.abs(n);
      if (abs >= 1e12) return '$' + (n / 1e12).toFixed(2) + 'T';
      if (abs >= 1e9) return '$' + (n / 1e9).toFixed(2) + 'B';
      if (abs >= 1e6) return '$' + (n / 1e6).toFixed(2) + 'M';
      if (abs >= 1e3) return '$' + (n / 1e3).toFixed(2) + 'K';
      return '$' + n.toLocaleString(undefined, {{maximumFractionDigits: 2}});
    }};

    setText('cp-' + sym, fmtPrice(c.price));
    setText('cc-' + sym, sign + (c.change_pct ? c.change_pct.toFixed(2) : '0.00') + '%');
    const chgEl = document.getElementById('cc-' + sym);
    if (chgEl && chgEl.className !== 'crypto-change ' + changeClass) chgEl.className = 'crypto-change ' + changeClass;

    setText('cmcap-' + sym, fmtLarge(c.market_cap));
    setText('cvol-' + sym, fmtLarge(c.volume));
    setText('cupd-' + sym, c.timestamp || '—');
    setText('csrc-' + sym, c.source || 'CoinGecko Live Data');

    if (cryptoPrevPrices[c.symbol] !== undefined && cryptoPrevPrices[c.symbol] !== c.price) {{
      const cls = c.price > cryptoPrevPrices[c.symbol] ? 'flash-up' : 'flash-down';
      card.classList.add(cls);
      setTimeout(() => card.classList.remove(cls), 800);
    }}
    cryptoPrevPrices[c.symbol] = c.price;
  }});
}}

async function fetchAlpacaCrypto() {{
  try {{
    const r = await fetch('/api/alpaca-crypto');
    const data = await r.json();
    if (data.error) {{
      document.getElementById('crypto-status-text').textContent = 'Error: ' + data.error;
      document.getElementById('crypto-data-badge').textContent = 'Unavailable';
      return;
    }}
    cryptoAllCoins = data.coins || [];
    renderCryptoGrid();
    document.getElementById('crypto-last-update').textContent = data.updated;
    document.getElementById('crypto-status-text').textContent = 'Live · ' + cryptoAllCoins.length + ' coins';
    document.getElementById('crypto-data-badge').textContent = 'CoinGecko';
  }} catch(e) {{
    document.getElementById('crypto-status-text').textContent = 'Connection error — retrying';
    document.getElementById('crypto-data-badge').textContent = 'Offline';
  }}
}}

fetchAlpacaCrypto();
setInterval(fetchAlpacaCrypto, 15000);
</script>
</body>
</html>"""
 
 
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


@app.route("/api/alpaca-crypto")
def api_alpaca_crypto():
    """Return live crypto data from CoinGecko/DIA for the crypto watchlist."""
    now = time.time()
    if "crypto" not in alpaca_cache or (now - alpaca_cache_time.get("crypto", 0)) > CRYPTO_CACHE_TTL:
        try:
            alpaca_cache["crypto"] = alpaca_fetch_crypto_data()
            alpaca_cache_time["crypto"] = now
        except Exception as e:
            if "crypto" not in alpaca_cache:
                return jsonify({"error": str(e)}), 500
    return jsonify({
        "coins":   alpaca_cache.get("crypto", []),
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
 
    # ── Fetch all alternative data concurrently ──────────────────────────────
    # live_price_data is fetched first (fastest, WebSocket cache hit is O(1))
    # so it's always ready before the slower macro/fundamentals calls finish.
    macro_data    = {}
    trends_data   = {}
    fundamentals  = {}
    shipping_ctx  = {}
    live_price_data = None   # populated below

    # Real-time price: Alpaca WebSocket → Alpaca REST → yfinance fast_info
    # Run synchronously — the WebSocket cache is an in-memory dict lookup so
    # it returns in microseconds; REST fallback is ~100ms; yfin ~200ms.
    try:
        live_price_data = get_alpaca_live_price(ticker)
    except Exception:
        live_price_data = None

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
    if live_price_data:
        dtype_label = live_price_data.get("data_type", "?")
        src_label   = live_price_data.get("source", "Live")
        data_sources.append(f"Real-Time Price ({src_label} · {dtype_label})")
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
                                          live_price_data=live_price_data,
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
    if vid:
        return jsonify({"video_id": vid, "is_live": live})
    # ── Last-resort fallback: fetch RSS directly one more time with a fresh
    #    session, bypassing all caching / timeout assumptions in the main fn.
    #    If that still yields nothing, return the bare channel_id as a sentinel
    #    so the JS can embed /channel/{id}/live — which always loads something.
    channel_id = _HANDLE_TO_CHANNEL_ID.get(handle)
    if channel_id:
        try:
            import xml.etree.ElementTree as _ET
            _r = requests.get(
                f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}",
                headers=_YT_HDR, timeout=15, allow_redirects=True
            )
            if _r.status_code == 200:
                _ids = re.findall(r'<yt:videoId>([A-Za-z0-9_-]{11})</yt:videoId>', _r.text)
                if _ids:
                    return jsonify({"video_id": _ids[0], "is_live": False})
        except Exception:
            pass
        # Absolute last resort: signal JS to use /channel/{id}/live embed
        return jsonify({"video_id": None, "is_live": False, "channel_id": channel_id})
    return jsonify({"video_id": None, "is_live": False, "channel_id": None})
 
 
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
    # Return the key only over this server-side route (same-origin iframe can fetch it)
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
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/leaflet.draw/1.0.4/leaflet.draw.css">
<script src="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/leaflet.draw/1.0.4/leaflet.draw.js"></script>
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
/* Region selection overlay */
#region-overlay{display:none;position:fixed;top:38px;left:0;right:0;bottom:60px;z-index:900;background:rgba(100,180,255,.06);border:2px dashed rgba(100,180,255,.5);pointer-events:none}
#region-hint{display:none;position:fixed;top:42px;left:50%;transform:translateX(-50%);z-index:2000;background:rgba(13,17,23,.95);color:#4ab4ff;font-size:10px;letter-spacing:.07em;text-transform:uppercase;padding:5px 14px;border-radius:20px;border:1px solid rgba(100,180,255,.4);pointer-events:none;white-space:nowrap}
.leaflet-draw-toolbar a{background-color:#0d1117!important;border-color:rgba(255,255,255,.1)!important}
.leaflet-draw-tooltip{background:rgba(13,17,23,.92);border:1px solid rgba(100,180,255,.4);color:#4ab4ff;font-family:'DM Mono',monospace;font-size:10px;border-radius:4px}
</style>
</head>
<body>
<div id="region-overlay"></div>
<div id="region-hint">🖱 Draw a rectangle to filter region &middot; Press Esc to cancel</div>
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
// ── MAP ───────────────────────────────────────────────────────────────────
var map = L.map('map', {center:[20,10], zoom:2, zoomControl:true, attributionControl:true});
L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
  attribution: '&copy; <a href="https://carto.com/">CARTO</a> &copy; <a href="https://openstreetmap.org/copyright">OSM</a>',
  subdomains: 'abcd', maxZoom: 19
}).addTo(map);
L.tileLayer('https://tiles.openseamap.org/seamark/{z}/{x}/{y}.png', {
  attribution: '&copy; <a href="https://openseamap.org">OpenSeaMap</a>',
  opacity: 0.55, maxZoom: 18
}).addTo(map);

// ── DEBUG LOG ──────────────────────────────────────────────────────────────
function dbg(line1, line2) {
  document.getElementById('debug-line1').textContent = line1 || '';
  if (line2 !== undefined) document.getElementById('debug-line2').textContent = line2 || '';
}

// ── VESSEL STATE ──────────────────────────────────────────────────────────
var vessels    = {};  // mmsi -> {marker, data, lastSeen, shown}
var typeCache  = {};  // mmsi -> ship type int (from ShipStaticData)
var activeFilter = 'all';
var vesselLimit  = 3000;  // default cap; user can raise with +500 button
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
  return L.divIcon({html: makeMarkerHTML(color, cog), className:'', iconSize:[14,20], iconAnchor:[7,10]});
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

  // Block new additions once cap is reached; existing vessels always update
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

// ── FILTER BUTTONS ─────────────────────────────────────────────────────────
document.getElementById('filter-bar').addEventListener('click', function(e){
  var btn = e.target.closest('.fbtn'); if (!btn) return;
  activeFilter = btn.dataset.type;
  document.querySelectorAll('.fbtn').forEach(function(b){ b.classList.remove('on'); });
  btn.classList.add('on');
  Object.values(vessels).forEach(function(v){
    var cls = v.data.cls;
    var typeOk = (activeFilter==='all'||activeFilter===cls||(activeFilter==='other'&&(cls==='other'||cls==='service')));
    var lat = parseFloat(v.data.lat), lon = parseFloat(v.data.lon);
    var regionOk = !_regionBounds || _regionBounds.contains([lat, lon]);
    var vis = typeOk && regionOk;
    if (vis && !v.shown)  { map.addLayer(v.marker);    v.shown=true; }
    if (!vis && v.shown)  { map.removeLayer(v.marker); v.shown=false; }
  });
});

// ── STATUS ────────────────────────────────────────────────────────────────
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

// ── WEBSOCKET ────────────────────────────────────────────────────────────
var ws = null, reconnectDelay = 3000, reconnectTimer = null;
var _aisStopped = true;  // Start in stopped state — controlled by parent page

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

  ws.binaryType = 'blob';  // AISStream sends binary Blob frames

  ws.onmessage = function(evt) {
    // AISStream sends data as Blob — must read it as text first
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

// ── INIT: Fetch key from server, then connect ─────────────────────────────
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
      // No API key — still show the map with OpenSeaMap + a status notice
      setStatus('nokey', err.message);
      var led = document.getElementById('status-led');
      var txt = document.getElementById('status-text');
      led.style.background = '#ffaa33';
      txt.textContent = 'Live positions need AISSTREAM_API_KEY';
      dbg('Map visible — set AISSTREAM_API_KEY env var in Vercel to enable live AIS', err.message);
      // Add a visible overlay hint on the map
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

// ── REGION SELECTION ──────────────────────────────────────────────────────
var _regionLayer = null;
var _regionBounds = null;
var _drawControl = null;
var _drawnItems = new L.FeatureGroup();
map.addLayer(_drawnItems);

function startRegionDraw() {
  // Clear any existing region first
  clearRegion(true);
  document.getElementById('region-overlay').style.display = 'block';
  document.getElementById('region-hint').style.display = 'block';
  // Activate Leaflet.draw rectangle tool
  _drawControl = new L.Draw.Rectangle(map, {
    shapeOptions: {
      color: '#4ab4ff',
      fillColor: '#4ab4ff',
      fillOpacity: 0.08,
      weight: 2,
      dashArray: '6 4'
    }
  });
  _drawControl.enable();
  // Esc cancels
  function onEsc(ev) {
    if (ev.key === 'Escape') {
      _drawControl.disable();
      document.getElementById('region-overlay').style.display = 'none';
      document.getElementById('region-hint').style.display = 'none';
      document.removeEventListener('keydown', onEsc);
      try { window.parent.postMessage('ais:region:cancelled', '*'); } catch(e){}
    }
  }
  document.addEventListener('keydown', onEsc);
}

map.on(L.Draw.Event.CREATED, function(e) {
  document.getElementById('region-overlay').style.display = 'none';
  document.getElementById('region-hint').style.display = 'none';
  _drawnItems.clearLayers();
  _regionLayer = e.layer;
  _drawnItems.addLayer(_regionLayer);
  _regionBounds = _regionLayer.getBounds();
  // Apply region filter: hide vessels outside the bounding box
  applyRegionFilter();
  dbg('Region active: '+_regionBounds.getSouth().toFixed(2)+'°S '+_regionBounds.getNorth().toFixed(2)+'°N '+_regionBounds.getWest().toFixed(2)+'°W '+_regionBounds.getEast().toFixed(2)+'°E');
});

function applyRegionFilter() {
  if (!_regionBounds) return;
  Object.values(vessels).forEach(function(v) {
    var lat = parseFloat(v.data.lat), lon = parseFloat(v.data.lon);
    var inRegion = _regionBounds.contains([lat, lon]);
    var typeOk = (activeFilter === 'all' || activeFilter === v.data.cls ||
                  (activeFilter === 'other' && (v.data.cls === 'other' || v.data.cls === 'service')));
    var vis = inRegion && typeOk;
    if (vis && !v.shown)  { map.addLayer(v.marker);    v.shown = true; }
    if (!vis && v.shown)  { map.removeLayer(v.marker); v.shown = false; }
  });
}

function clearRegion(skipParent) {
  _regionBounds = null;
  _drawnItems.clearLayers();
  _regionLayer = null;
  document.getElementById('region-overlay').style.display = 'none';
  document.getElementById('region-hint').style.display = 'none';
  // Restore all vessels according to active type filter
  Object.values(vessels).forEach(function(v) {
    var typeOk = (activeFilter === 'all' || activeFilter === v.data.cls ||
                  (activeFilter === 'other' && (v.data.cls === 'other' || v.data.cls === 'service')));
    if (typeOk && !v.shown)  { map.addLayer(v.marker);    v.shown = true; }
    if (!typeOk && v.shown)  { map.removeLayer(v.marker); v.shown = false; }
  });
  dbg('Region cleared — showing all vessels');
}

// Patch upsertVessel to respect region filter after vessels update
var _origUpsertVessel = upsertVessel;
// Override visibility in upsertVessel: if a region is active, new vessels
// outside the region should not be shown. We hook into updateCounter instead.
var _origUpdateCounter = updateCounter;
updateCounter = function() {
  _origUpdateCounter();
  if (_regionBounds) applyRegionFilter();
};

// ── postMessage handler ────────────────────────────────────────────────────
window.addEventListener('message', function(e) {
  if (e.data === 'ais:start') aisStart();
  if (e.data === 'ais:stop')  aisStop();
  if (e.data === 'ais:region:start') startRegionDraw();
  if (e.data === 'ais:region:clear') clearRegion(false);
});

// Do NOT auto-start — wait for parent page command
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
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/leaflet.draw/1.0.4/leaflet.draw.css">
<script src="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/leaflet.draw/1.0.4/leaflet.draw.js"></script>
<style>
*{margin:0;padding:0;box-sizing:border-box}
html,body{width:100%;height:100%;overflow:hidden;font-family:'DM Mono',monospace,sans-serif;background:#07090f;color:#c8d8f0}

/* ── TOP BAR ─────────────────────────────────────────────── */
#topbar{
  position:fixed;top:0;left:0;right:0;height:40px;z-index:2000;
  background:rgba(7,9,15,.97);border-bottom:1px solid rgba(255,255,255,.07);
  display:flex;align-items:center;padding:0 12px;gap:10px;
  backdrop-filter:blur(12px);
}
#status-led{width:7px;height:7px;border-radius:50%;background:#444;flex-shrink:0;transition:background .4s}
#status-text{display:none}
#ac-counter{font-size:9px;letter-spacing:.07em;color:#ffaa33;background:rgba(255,170,50,.08);border:1px solid rgba(255,170,50,.18);border-radius:20px;padding:2px 9px;white-space:nowrap;flex-shrink:0}
#filter-bar{display:flex;gap:5px;flex-shrink:0}
.fbtn{font-size:8px;letter-spacing:.08em;text-transform:uppercase;padding:2px 8px;border-radius:20px;border:1px solid rgba(255,255,255,.1);background:transparent;color:#5a7090;cursor:pointer;transition:all .15s;font-family:inherit;white-space:nowrap}
.fbtn:hover{border-color:#ffaa33;color:#ffaa33}
.fbtn.on{background:rgba(255,170,50,.1);border-color:rgba(255,170,50,.5);color:#ffaa33}

/* ── BOTTOM STATUS BAR ───────────────────────────────────── */
#statusbar{
  position:fixed;bottom:0;left:0;right:0;height:28px;z-index:2000;
  background:rgba(7,9,15,.97);border-top:1px solid rgba(255,255,255,.06);
  display:flex;align-items:center;padding:0 12px;gap:8px;overflow:hidden;
}
#dbg1{font-size:8px;letter-spacing:.05em;color:#3a5a7a;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;flex:1}
#poll-count{font-size:8px;letter-spacing:.05em;color:#2a3a52;white-space:nowrap;flex-shrink:0}

/* ── MAIN AREA: MAP + SIDEBAR ────────────────────────────── */
#wrap{
  position:fixed;
  top:40px;bottom:28px;left:0;right:0;
  display:flex;flex-direction:row;
}

/* MAP — critical: must have explicit pixel height for Leaflet */
#map{
  flex:1 1 0;
  min-width:0;
  /* height is set by JS after layout to avoid Leaflet zero-size bug */
  background:#07090f;
}

/* SIDEBAR ────────────────────────────────────────────────── */
#sidebar{
  width:280px;flex-shrink:0;
  background:#07090f;
  border-left:1px solid rgba(255,255,255,.06);
  display:flex;flex-direction:column;
  overflow:hidden;
}
#sb-header{
  padding:7px 10px;border-bottom:1px solid rgba(255,255,255,.05);
  font-size:8px;letter-spacing:.12em;text-transform:uppercase;color:#3a5070;
  display:flex;justify-content:space-between;align-items:center;flex-shrink:0;
}
#sb-count{color:#ffaa33;font-size:9px}
#sb-list{
  flex:1;overflow-y:auto;
  scrollbar-width:thin;scrollbar-color:#1a2a3a transparent;
}
#sb-list::-webkit-scrollbar{width:3px}
#sb-list::-webkit-scrollbar-thumb{background:#1a2a3a;border-radius:2px}

/* Aircraft row */
.acr{
  padding:7px 10px 8px;border-bottom:1px solid rgba(255,255,255,.035);
  cursor:pointer;transition:background .1s;
}
.acr:hover{background:rgba(255,170,50,.04)}
.acr.sel{background:rgba(255,170,50,.08);border-left:2px solid #ffaa33;padding-left:8px}
.acr-top{display:flex;align-items:center;gap:5px;margin-bottom:4px}
.acdot{width:5px;height:5px;border-radius:50%;flex-shrink:0}
.acs{font-size:11px;font-weight:700;color:#ffaa33;letter-spacing:.03em;flex:1;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.achex{font-size:8px;color:#2a4060;letter-spacing:.06em;text-transform:uppercase}
.acg{display:grid;grid-template-columns:1fr 1fr 1fr;gap:2px 6px}
.acf-k{font-size:7px;text-transform:uppercase;letter-spacing:.08em;color:#2a3a52}
.acf-v{font-size:9px;color:#7090b0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}

/* Leaflet overrides */
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

/* Mobile — AIS-style: map on top (~55 vh), table scrolls below */
@media(max-width:680px){
  html,body{overflow:auto}

  #topbar{
    height:44px;
    padding:0 8px;gap:6px;
  }
  #filter-bar{gap:3px;overflow-x:auto;-webkit-overflow-scrolling:touch;flex-shrink:1;min-width:0;scrollbar-width:none}
  #filter-bar::-webkit-scrollbar{display:none}
  .fbtn{font-size:7px;padding:2px 6px;white-space:nowrap;flex-shrink:0}

  #wrap{
    position:relative;
    top:auto;bottom:auto;left:auto;right:auto;
    flex-direction:column;
    width:100%;
    /* push below fixed topbar */
    margin-top:44px;
    /* leave room for fixed statusbar */
    margin-bottom:28px;
  }

  #map{
    width:100%;
    height:55vw;          /* ~AIS ratio: slightly taller than wide */
    min-height:220px;
    flex:none;
  }

  #sidebar{
    display:flex;          /* was display:none — restore it */
    width:100%;
    flex-direction:column;
    border-left:none;
    border-top:1px solid rgba(255,255,255,.08);
    /* sidebar table is naturally scrollable within the page flow */
    max-height:none;
    overflow:visible;
  }

  #sb-header{
    padding:6px 10px;
    position:sticky;top:44px;z-index:100;
    background:#07090f;
  }

  #sb-list{
    overflow-y:visible;   /* let the page scroll instead */
  }

  /* Make aircraft rows a bit more touch-friendly */
  .acr{padding:8px 10px 9px}
  .acs{font-size:12px}
  .acf-v{font-size:10px}

  #statusbar{
    position:fixed;
  }
}
/* Region selection */
#ac-region-overlay{display:none;position:fixed;top:40px;left:0;right:0;bottom:28px;z-index:900;background:rgba(100,180,255,.05);border:2px dashed rgba(100,180,255,.45);pointer-events:none}
#ac-region-hint{display:none;position:fixed;top:46px;left:50%;transform:translateX(-50%);z-index:2000;background:rgba(13,17,23,.95);color:#4ab4ff;font-size:9px;letter-spacing:.07em;text-transform:uppercase;padding:5px 14px;border-radius:20px;border:1px solid rgba(100,180,255,.4);pointer-events:none;white-space:nowrap}
.leaflet-draw-toolbar a{background-color:#0d1117!important;border-color:rgba(255,255,255,.1)!important}
.leaflet-draw-tooltip{background:rgba(13,17,23,.92);border:1px solid rgba(100,180,255,.4);color:#4ab4ff;font-family:'DM Mono',monospace;font-size:10px;border-radius:4px}
</style>
</head>
<body>
<div id="ac-region-overlay"></div>
<div id="ac-region-hint">🖱 Draw a rectangle to filter region &middot; Press Esc to cancel</div>
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
    <div id="sb-header">
      <span>Live Aircraft Data</span>
      <span id="sb-count">—</span>
    </div>
    <div id="sb-list"></div>
  </div>
</div>

<div id="statusbar">
  <span id="dbg1">ADS-B tracker ready — press Start above</span>
  <span id="poll-count"></span>
</div>

<script>
// ── CONSTANTS ─────────────────────────────────────────────────────────────────
var TYPE = {
  airborne: {color:'#ffaa33', label:'Airborne'},
  military: {color:'#ff4455', label:'Military'},
  ground:   {color:'#44ee88', label:'Ground'},
  other:    {color:'#6b7fa3', label:'Other'}
};
var MIL_HEX = ['ADF','AE0','AE1','AE2','AE3','AE4','AE5','AE6','AE7','AE8','AE9',
  '43C','43D','43E','43F','440','441','3F4','3F5','3F6','3F7','3F8','3F9',
  '7F0','7F1','7F2','7F3','7F4','7F5','7F6','7F7','7F8','7F9','7FA','7FB'];

// Global regions [lat, lon, dst_km] — cycling every poll
var REGIONS = [
  [40,  -95,  2500],  // North America
  [51,   10,  2000],  // Europe
  [35,  115,  2500],  // East Asia
  [20,   80,  2000],  // South Asia
  [-15, 133,  2000],  // Australia
  [55,   60,  2500],  // Russia / Central Asia
  [25,   45,  2000],  // Middle East
  [-5,   20,  2500],  // Africa
  [-20, -60,  2500],  // South America
  [65,  -20,  1500],  // North Atlantic
  [35,  135,  1500],  // Japan / Korea
  [5,   105,  2000],  // SE Asia
];

// ── STATE ─────────────────────────────────────────────────────────────────────
var ac      = {};        // hex -> {marker, data, lastSeen, shown}
var filter  = 'all';
var selHex  = null;
var polls   = 0;
var ridx    = 0;
var stopped = true;
var timer   = null;
var INTERVAL = 8000;

// ── MAP INIT ─────────────────────────────────────────────────────────────────
// CRITICAL: set explicit pixel size on #map before L.map() so Leaflet
// doesn't see a 0x0 container and skip rendering.
var wrap = document.getElementById('wrap');
var mapEl = document.getElementById('map');

function isMobile() { return window.innerWidth <= 680; }

function setMapHeight() {
  if (isMobile()) {
    // Mobile: fixed vw-based height driven by CSS; just clear any inline override
    mapEl.style.height = '';
  } else {
    // Desktop: fill the fixed-position wrap vertically
    mapEl.style.height = wrap.offsetHeight + 'px';
  }
}
setMapHeight();

var map = L.map('map', {
  center: [30, 10], zoom: 3,
  zoomControl: true, attributionControl: true,
  preferCanvas: true   // canvas renderer = much faster for many markers
});
L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
  attribution: '&copy; <a href="https://carto.com/">CARTO</a>',
  subdomains: 'abcd', maxZoom: 19
}).addTo(map);

// Resize map when window resizes
window.addEventListener('resize', function() {
  setMapHeight();
  map.invalidateSize();
});

// ── HELPERS ───────────────────────────────────────────────────────────────────
function log(msg) {
  document.getElementById('dbg1').textContent = msg;
}
function setLed(state) {
  var c = {live:'#44ee88', error:'#ff4455', init:'#ffaa33', stopped:'#333'}[state] || '#555';
  document.getElementById('status-led').style.background = c;
}
function setStatus(state, txt) {
  document.getElementById('status-text').textContent = txt;
  setLed(state);
}

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
  // alt_baro from adsb.lol is already in FEET
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
function fAge(ts) {
  var s = Math.round((Date.now()-ts)/1000);
  return s < 60 ? s+'s' : Math.floor(s/60)+'m';
}

function buildPopup(d) {
  var t = TYPE[d.cls] || TYPE.other;
  var badge = '<span class="pbadge" style="background:'+t.color+'18;color:'+t.color+';border:1px solid '+t.color+'44">'+t.label+'</span>';
  var rows = [
    ['ICAO', d.hex.toUpperCase()],
    ['Flight', d.callsign || '—'],
    ['Altitude', fAlt(d)],
    ['Speed', fSpd(d)],
    ['Heading', fHdg(d)],
    ['Vert Rate', fVrt(d)],
    ['Position', fPos(d.lat)+' / '+fPos(d.lon)],
    ['Squawk', d.squawk || '—'],
    ['Category', d.category || '—'],
  ];
  var h = '<div class="pname">'+(d.callsign||d.hex.toUpperCase())+'</div>'+badge;
  rows.forEach(function(r) {
    if (r[1] && r[1] !== '—')
      h += '<div class="prow"><span class="pk">'+r[0]+'</span><span class="pv">'+r[1]+'</span></div>';
  });
  return h;
}

// ── PARSE adsb.lol ac object → internal format ────────────────────────────────
// adsb.lol v2 fields: hex, flight, lat, lon, alt_baro (ft or "ground"),
//   gs (knots), track (deg), baro_rate (fpm), squawk, category, on_ground
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
    hex:      (o.hex || '').toLowerCase(),
    callsign: (o.flight || '').trim(),
    lat:      lat,
    lon:      lon,
    alt_ft:   altFt,               // feet (as adsb.lol sends)
    gs_kn:    o.gs != null ? parseFloat(o.gs) : null,         // knots
    track:    o.track != null ? parseFloat(o.track) : null,   // degrees
    baro_rate:o.baro_rate != null ? parseFloat(o.baro_rate) : null, // fpm
    on_ground:onGround,
    squawk:   o.squawk || null,
    category: o.category || null,
    cls:      null,  // set by classify()
  };
}

// ── UPSERT AIRCRAFT ───────────────────────────────────────────────────────────
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
    if (vis && !v.shown)  { v.marker.addTo(map);   v.shown=true; }
    if (!vis && v.shown)  { map.removeLayer(v.marker); v.shown=false; }
  } else {
    var m = L.marker([d.lat, d.lon], {icon: planeIcon(t.color, d.track)});
    m.bindPopup('', {maxWidth:260, className:''});
    (function(hex){ m.on('click', function(){ m.setPopupContent(buildPopup(ac[hex].data)); }); })(d.hex);
    if (vis) m.addTo(map);
    ac[d.hex] = {marker:m, data:d, lastSeen:Date.now(), shown:vis};
  }
}

// ── COUNTER + SIDEBAR ─────────────────────────────────────────────────────────
function updateUI() {
  var keys = Object.keys(ac);
  var n = keys.length;
  document.getElementById('ac-counter').textContent = n.toLocaleString() + ' aircraft';
  document.getElementById('sb-count').textContent = n;
  // Report to parent
  try { window.parent.postMessage({type:'adsb:count', count: n.toLocaleString()}, '*'); } catch(e){}
  renderSidebar(keys);
}

var _sbRender = 0;
function renderSidebar(keys) {
  var list = document.getElementById('sb-list');
  if (!list) return;
  if (!keys) keys = Object.keys(ac);
  // Filter
  var fkeys = keys.filter(function(h){ return filter==='all'||ac[h].data.cls===filter; });
  // Sort: selected first, then callsign
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

// Sidebar click → fly to aircraft
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

// ── EXPIRE stale aircraft (>3 min) ───────────────────────────────────────────
setInterval(function() {
  var cut = Date.now() - 180000;
  Object.keys(ac).forEach(function(h) {
    if (ac[h].lastSeen < cut) { map.removeLayer(ac[h].marker); delete ac[h]; }
  });
  updateUI();
}, 30000);

// Refresh sidebar ages every 15s
setInterval(function() { if (!stopped) renderSidebar(); }, 15000);

// ── FILTER BUTTONS ────────────────────────────────────────────────────────────
document.getElementById('filter-bar').addEventListener('click', function(e) {
  var b = e.target.closest('.fbtn'); if (!b) return;
  filter = b.dataset.t;
  document.querySelectorAll('.fbtn').forEach(function(x){ x.classList.remove('on'); });
  b.classList.add('on');
  Object.values(ac).forEach(function(v) {
    var typeOk = (filter==='all'||filter===v.data.cls);
    var regionOk = !_acRegionBounds || _acRegionBounds.contains([v.data.lat, v.data.lon]);
    var vis = typeOk && regionOk;
    if (vis && !v.shown)  { v.marker.addTo(map);     v.shown=true; }
    if (!vis && v.shown)  { map.removeLayer(v.marker); v.shown=false; }
  });
  renderSidebar();
});

// ── POLL adsb.lol via Flask proxy ────────────────────────────────────────────
// Try multiple ADS-B sources in parallel; use first that returns real aircraft.
// All three APIs are CORS-enabled, no key required.
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
  var lat = reg[0], lon = reg[1], nm = 250; // 250 nm radius (~460 km)

  // Build candidate URLs — three independent CORS-open APIs
  var sources = [
    'https://api.airplanes.live/v2/point/'+lat+'/'+lon+'/'+nm,
    'https://api.adsb.lol/v2/aircraft?lat='+lat+'&lon='+lon+'&dst='+nm,
    'https://api.adsb.fi/v1/aircraft?lat='+lat+'&lon='+lon+'&radius='+nm,
  ];

  // Race all three — settle all, use first winner with actual aircraft
  Promise.allSettled(sources.map(fetchFromSource)).then(function(results) {
    if (stopped) return;
    var winner = null;
    for (var i = 0; i < results.length; i++) {
      if (results[i].status === 'fulfilled') { winner = results[i].value; break; }
    }
    if (!winner) {
      // All direct failed — fall back to Flask proxy (buffered server data)
      var proxyUrl = '/adsb/proxy?lat='+lat+'&lon='+lon+'&dst='+nm;
      fetch(proxyUrl)
        .then(function(r) { return r.json(); })
        .then(function(data) { handleData(data.ac || [], 'proxy'); })
        .catch(function(err) {
          setStatus('error', 'No source — retrying…');
          log('All sources failed. Retry in 15s.');
          timer = setTimeout(poll, 15000);
        });
      return;
    }
    handleData(winner.list, winner.src.split('/')[2]); // show hostname as source
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

function adsbStart() {
  stopped = false;
  ridx = 0;
  polls = 0;
  setStatus('live', 'Connecting…');
  setLed('init');
  log('Starting ADS-B poll via adsb.lol…');
  poll();
}

function adsbStop() {
  stopped = true;
  clearTimeout(timer); timer = null;
  setStatus('stopped', 'Stopped');
  setLed('stopped');
  log('ADS-B tracker stopped.');
}

// ── REGION SELECTION ──────────────────────────────────────────────────────────
var _acRegionBounds = null;
var _acDrawControl = null;
var _acDrawnItems = new L.FeatureGroup();
map.addLayer(_acDrawnItems);

function acStartRegionDraw() {
  acClearRegion(true);
  document.getElementById('ac-region-overlay').style.display = 'block';
  document.getElementById('ac-region-hint').style.display = 'block';
  _acDrawControl = new L.Draw.Rectangle(map, {
    shapeOptions: {
      color: '#4ab4ff',
      fillColor: '#4ab4ff',
      fillOpacity: 0.07,
      weight: 2,
      dashArray: '6 4'
    }
  });
  _acDrawControl.enable();
  function onEsc(ev) {
    if (ev.key === 'Escape') {
      _acDrawControl.disable();
      document.getElementById('ac-region-overlay').style.display = 'none';
      document.getElementById('ac-region-hint').style.display = 'none';
      document.removeEventListener('keydown', onEsc);
      try { window.parent.postMessage('adsb:region:cancelled', '*'); } catch(e) {}
    }
  }
  document.addEventListener('keydown', onEsc);
}

map.on(L.Draw.Event.CREATED, function(e) {
  document.getElementById('ac-region-overlay').style.display = 'none';
  document.getElementById('ac-region-hint').style.display = 'none';
  _acDrawnItems.clearLayers();
  _acDrawnItems.addLayer(e.layer);
  _acRegionBounds = e.layer.getBounds();
  acApplyRegionFilter();
  log('Region: '+_acRegionBounds.getSouth().toFixed(2)+'°S '+_acRegionBounds.getNorth().toFixed(2)+'°N · '+_acRegionBounds.getWest().toFixed(2)+'°W '+_acRegionBounds.getEast().toFixed(2)+'°E');
  updateUI();
});

function acApplyRegionFilter() {
  if (!_acRegionBounds) return;
  Object.values(ac).forEach(function(v) {
    var inRegion = _acRegionBounds.contains([v.data.lat, v.data.lon]);
    var typeOk = (filter === 'all' || filter === v.data.cls);
    var vis = inRegion && typeOk;
    if (vis && !v.shown)  { v.marker.addTo(map);     v.shown = true; }
    if (!vis && v.shown)  { map.removeLayer(v.marker); v.shown = false; }
  });
}

function acClearRegion(skipParent) {
  _acRegionBounds = null;
  _acDrawnItems.clearLayers();
  document.getElementById('ac-region-overlay').style.display = 'none';
  document.getElementById('ac-region-hint').style.display = 'none';
  // Restore all aircraft by type filter
  Object.values(ac).forEach(function(v) {
    var typeOk = (filter === 'all' || filter === v.data.cls);
    if (typeOk && !v.shown)  { v.marker.addTo(map);     v.shown = true; }
    if (!typeOk && v.shown)  { map.removeLayer(v.marker); v.shown = false; }
  });
  log('Region cleared — all aircraft visible');
  updateUI();
}

// Patch updateUI to enforce region on new data
var _origUpdateUI = updateUI;
updateUI = function() {
  _origUpdateUI();
  if (_acRegionBounds) acApplyRegionFilter();
};

// ── START/STOP from parent page via postMessage ───────────────────────────────
window.addEventListener('message', function(e) {
  if (e.data === 'adsb:start')         adsbStart();
  if (e.data === 'adsb:stop')          adsbStop();
  if (e.data === 'adsb:region:start')  acStartRegionDraw();
  if (e.data === 'adsb:region:clear')  acClearRegion(false);
});

// Ready — wait for parent Start command
setStatus('stopped', 'Ready');
setLed('stopped');
log('ADS-B tracker ready. Press ▶ Start to connect.');
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
        # Upstream rejected — serve buffered data so the map stays live
        with _adsb_lock:
            buf = list(_adsb_buffer)
        cols = ["ts","hex","flight","lat","lon","alt_baro","gs","track"]
        ac = []
        for row in buf:
            if row[3] and row[4]:
                obj = dict(zip(cols, row))
                obj["baro_rate"] = None   # not stored in buffer; prevents parseAC undefined
                ac.append(obj)
        return jsonify({"ac": ac, "_source": "buffer",
                        "_upstream_status": r.status_code,
                        "_upstream_body": r.text[:200]})
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
 
    # Test FRED
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
    print("  STARFISH — Market Dynamics")
    print("  http://127.0.0.1:5000")
    print("=" * 60)
    print("\n  pip install flask requests numpy pandas yfinance plotly httpx beautifulsoup4 lxml pytrends fredapi websocket-client\n")
    _start_adsb_collector()
    app.run(debug=True, host="0.0.0.0", port=5000)

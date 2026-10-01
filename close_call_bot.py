#!/usr/bin/env python3
"""Close Call trading bot for technocore.chat"""

import json, base64, time, re, sys, os
import requests
from cryptography.hazmat.primitives.serialization import load_pem_private_key
from nacl.signing import SigningKey
from decimal import Decimal
import random
import string

# Config
DID = "did:key:z6MkgBpho2ygRD1YVD9JGy2nYHnGqFz6vQPKMEsMkNgxWrXM"
SEASON = "close-1"
ROOM = "close1"
API = "https://technocore.chat"
SWEEP_SECS = 300
FEE_RATE = Decimal("0.01")
MINT = Decimal("10000")

# Load key
pem_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'identity.pem')
pem = open(pem_path, 'rb').read()
sk = load_pem_private_key(pem, password=b'FlopAirdrop2026Secure!')
raw = sk.private_bytes_raw()
signing_key = SigningKey(raw)

# State
nonce = 6  # 0-5 already used
balance = MINT
position_long = Decimal("0")
position_short = Decimal("0")
trade_count = 0
trade_ids = set()
last_sweep = 0

def sign_and_post(text):
    global nonce
    msg = f"{ROOM}|{nonce}|{text}".encode()
    sig = signing_key.sign(msg).signature
    sig_b64 = base64.urlsafe_b64encode(sig).rstrip(b'=').decode()
    data = {"did": DID, "sig": sig_b64, "nonce": str(nonce), "text": text}
    nonce += 1
    try:
        resp = requests.post(f"{API}/r/{ROOM}", json=data, timeout=20)
        return resp.status_code == 200
    except Exception as e:
        print(f"POST error: {e}", flush=True)
        return False

def gen_trade_id():
    while True:
        tid = ''.join(random.choices(string.ascii_lowercase + string.digits, k=12))
        if tid not in trade_ids:
            trade_ids.add(tid)
            return tid

def fetch_price():
    """Get latest NVDA reference price and limits from referee"""
    try:
        resp = requests.get(f"{API}/r/d-close1-price", timeout=20)
        text = resp.text
        
        # Parse all price posts: "n":NNN ... "ref":{"px":"XXX.XX",...} ... "limits":["lower","upper"]
        best_n = 0
        best_px = None
        best_limits = None
        
        for m in re.finditer(r'"n":(\d+).*?"ref":\{"px":"([0-9.]+)".*?"limits":\[\"([0-9.]+)\",\"([0-9.]+)\"\]', text):
            n = int(m.group(1))
            if n > best_n:
                best_n = n
                best_px = Decimal(m.group(2))
                best_limits = (Decimal(m.group(3)), Decimal(m.group(4)))
        
        if best_px:
            return best_n, best_px, best_limits
    except Exception as e:
        print(f"Price error: {e}", flush=True)
    return None, None, None

def post_trade(side, qty, px, until_sweep=2556):
    global trade_count
    trade_id = gen_trade_id()
    terms = {
        "id": trade_id,
        "maker": DID,
        "px": f"{px:.2f}",
        "qty": f"{qty:.2f}",
        "side": side,
        "taker": "any",
        "until": until_sweep
    }
    trade_text = json.dumps({"t": "trade", "season": SEASON, "terms": terms, "taker": "any"}, separators=(',', ':'))
    ok = sign_and_post(trade_text)
    if ok:
        trade_count += 1
        print(f"TRADE #{trade_count}: {side} {qty} @ ${px:.2f} (id={trade_id})", flush=True)
    return ok

def strategy(ref_px, limits, sweep_n):
    """Simple mean-reversion: buy low, sell high within the 5% band"""
    if ref_px is None or balance <= 0:
        return
    
    lower, upper = limits
    mid = (lower + upper) / 2
    band_width = upper - lower
    
    net = position_long - position_short
    
    # Only trade if we have enough balance
    free_bal = balance - (position_long * ref_px + position_short * ref_px) * (1 + FEE_RATE)
    if free_bal < ref_px * Decimal("0.1"):
        return
    
    # Buy when price is in lower 30% of band
    if ref_px < lower + band_width * Decimal("0.3") and net < Decimal("40"):
        # Calculate qty: more aggressive when closer to lower limit
        distance_pct = (mid - ref_px) / mid
        base_qty = Decimal("2") + Decimal("8") * distance_pct * 10
        qty = min(base_qty, Decimal("50") - net, free_bal / ref_px)
        qty = max(qty, Decimal("0")).quantize(Decimal("0.01"))
        
        if qty >= Decimal("0.1"):
            px = min(ref_px + Decimal("0.50"), upper - Decimal("0.01")).quantize(Decimal("0.01"))
            post_trade("buy", qty, px, until_sweep=min(sweep_n + 60, 2556))
            position_long += qty
            balance -= qty * px * (1 + FEE_RATE)
    
    # Sell when price is in upper 30% of band
    elif ref_px > upper - band_width * Decimal("0.3") and net > Decimal("-40"):
        distance_pct = (ref_px - mid) / mid
        base_qty = Decimal("2") + Decimal("8") * distance_pct * 10
        qty = min(base_qty, Decimal("50") + net, free_bal / ref_px)
        qty = max(qty, Decimal("0")).quantize(Decimal("0.01"))
        
        if qty >= Decimal("0.1"):
            px = max(ref_px - Decimal("0.50"), lower + Decimal("0.01")).quantize(Decimal("0.01"))
            post_trade("sell", qty, px, until_sweep=min(sweep_n + 60, 2556))
            position_short += qty
            balance -= qty * px * (1 + FEE_RATE)

def run():
    global balance, last_sweep
    
    print(f"Bot started. DID: {DID}", flush=True)
    print(f"Starting nonce: {nonce}", flush=True)
    
    while True:
        try:
            sweep_n, ref_px, limits = fetch_price()
            
            if sweep_n and sweep_n > last_sweep:
                last_sweep = sweep_n
                net = position_long - position_short
                print(f"[Sweep #{sweep_n}] NVDA=${ref_px} | Band=[${limits[0]},${limits[1]}] | Bal={balance} | L={position_long} S={position_short} Net={net}", flush=True)
                strategy(ref_px, limits, sweep_n)
            
            time.sleep(SWEEP_SECS)
            
        except KeyboardInterrupt:
            print("Bot stopped.", flush=True)
            break
        except Exception as e:
            print(f"Error: {e}", flush=True)
            time.sleep(30)

if __name__ == "__main__":
    run()

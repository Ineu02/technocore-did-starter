import json, base64, requests, re, sys, time, os, random, string
from cryptography.hazmat.primitives.serialization import load_pem_private_key
from nacl.signing import SigningKey
from decimal import Decimal

DID = "did:key:z6MkgBpho2ygRD1YVD9JGy2nYHnGqFz6vQPKMEsMkNgxWrXM"
SEASON = "close-1"
ROOM = "close1"
API = "https://technocore.chat"
LOG = "/tmp/closecall.log"

pem_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'identity.pem')
pem = open(pem_path, 'rb').read()
sk = load_pem_private_key(pem, password=b'FlopAirdrop2026Secure!')
raw = sk.private_bytes_raw()
signing_key = SigningKey(raw)

nonce = 6
last_sweep = 0
price_history = []  # Track recent prices for moving average
trade_count = 0

def log(msg):
    with open(LOG, 'a') as f:
        f.write(f"{time.strftime('%H:%M:%S')} {msg}\n")
        f.flush()

def sign_and_post(text):
    global nonce
    msg = f"{ROOM}|{nonce}|{text}".encode()
    sig = signing_key.sign(msg).signature
    sig_b64 = base64.urlsafe_b64encode(sig).rstrip(b'=').decode()
    data = {"did": DID, "sig": sig_b64, "nonce": str(nonce), "text": text}
    nonce += 1
    resp = requests.post(f"{API}/r/{ROOM}", json=data, timeout=20)
    return resp.status_code == 200

def fetch_price():
    try:
        resp = requests.get(f"{API}/r/d-close1-price", timeout=20)
        text = resp.text
        n_matches = [(m.start(), int(m.group(1))) for m in re.finditer(r'"n":(\d+)', text)]
        ref_matches = [(m.start(), Decimal(m.group(1))) for m in re.finditer(r'"ref":\{"px":"([0-9.]+)"', text)]
        lim_matches = [(m.start(), Decimal(m.group(1)), Decimal(m.group(2))) for m in re.finditer(r'"limits":\[\"([0-9.]+)\",\"([0-9.]+)\"\]', text)]
        if n_matches and ref_matches and lim_matches:
            return n_matches[-1][1], ref_matches[-1][1], (lim_matches[-1][1], lim_matches[-1][2])
    except Exception as e:
        log(f"Price error: {e}")
    return 0, None, None

def post_trade(side, qty, px, until_sweep=2556):
    global trade_count
    tid = ''.join(random.choices(string.ascii_lowercase + string.digits, k=12))
    terms = {"id": tid, "maker": DID, "px": f"{px:.2f}", "qty": f"{qty:.2f}", "side": side, "taker": "any", "until": until_sweep}
    trade_text = json.dumps({"t": "trade", "season": SEASON, "terms": terms, "taker": "any"}, separators=(',', ':'))
    if sign_and_post(trade_text):
        trade_count += 1
        log(f"  TRADE #{trade_count}: {side} {qty} @ ${px:.2f}")
        return True
    return False

log("Bot started")
while True:
    try:
        sweep_n, ref_px, limits = fetch_price()
        
        if ref_px and sweep_n > last_sweep:
            last_sweep = sweep_n
            lower, upper = limits
            
            # Track price history (keep last 20)
            price_history.append(ref_px)
            if len(price_history) > 20:
                price_history.pop(0)
            
            # Calculate moving average
            if len(price_history) >= 3:
                ma = sum(price_history) / len(price_history)
                deviation = (ref_px - ma) / ma * 100  # % deviation from MA
                
                log(f"#{sweep_n} NVDA=${ref_px} [{lower}-${upper}] MA=${ma:.2f} dev={deviation:.3f}%")
                
                # Strategy: mean reversion
                # Buy when price drops below MA by >0.05%
                # Sell when price rises above MA by >0.05%
                if deviation < Decimal("-0.05"):
                    # Price below MA - BUY
                    px = min(ref_px + Decimal("0.10"), upper - Decimal("0.01")).quantize(Decimal("0.01"))
                    qty = Decimal("3.00")
                    post_trade("buy", qty, px, until_sweep=min(sweep_n + 60, 2556))
                
                elif deviation > Decimal("0.05"):
                    # Price above MA - SELL
                    px = max(ref_px - Decimal("0.10"), lower + Decimal("0.01")).quantize(Decimal("0.01"))
                    qty = Decimal("3.00")
                    post_trade("sell", qty, px, until_sweep=min(sweep_n + 60, 2556))
        
        time.sleep(300)
        
    except Exception as e:
        log(f"Error: {e}")
        time.sleep(30)

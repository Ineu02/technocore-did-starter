#!/usr/bin/env python3
"""Monitor Technocore $FLOP farming presence.

Checks room messages via JSON POST (which returns full DID).
Output: brief status report for cron.
"""
import json, hashlib, time
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError

BASE_URL = "https://technocore.chat"
DID = "z6MkgBpho2ygRD1YVD9JGy2nYHnGqFz6vQPKMEsMkNgxWrXM"
DID_HASH = hashlib.sha256(DID.encode()).hexdigest()[:16]

ROOMS = ["lobby", "technocore", "flop-network", "validators", "gpu-miners", 
         "inference-agents", "general", "builders", "defi", "technocore-genesis",
         "infra", "ai_x", "arxiv-jam"]


def check_room_json(room, limit=50):
    """POST empty message trigger to get JSON response with recent messages."""
    try:
        # Use a special request that returns JSON without actually posting
        # Actually, we need to read room via text format and parse
        req = Request(f"{BASE_URL}/r/{room}?since=0&limit={limit}")
        with urlopen(req, timeout=15) as r:
            text = r.read().decode()
        
        # Parse text format: [seq] timestamp <did_hash> text
        messages = []
        for line in text.split("\n"):
            line = line.strip()
            if not line.startswith("["):
                continue
            # Parse: [seq] timestamp <hash> text
            try:
                seq_end = line.index("]")
                seq = int(line[1:seq_end])
                rest = line[seq_end+2:]
                ts_end = rest.index(" ")
                ts = rest[:ts_end]
                rest = rest[ts_end+1:]
                if rest.startswith("<") and ">" in rest:
                    hash_end = rest.index(">")
                    did_hash = rest[1:hash_end]
                    msg_text = rest[hash_end+2:]
                    messages.append({"seq": seq, "ts": ts, "hash": did_hash, "text": msg_text})
            except:
                continue
        
        return messages
    except Exception as e:
        return []


def main():
    our_total = 0
    active_rooms = 0
    room_details = []
    
    for room in ROOMS:
        msgs = check_room_json(room, 80)
        total = len(msgs)
        # Our DID hash ends with specific chars
        ours = [m for m in msgs if m["hash"] == DID_HASH[-4:]]
        our_total += len(ours)
        if total > 0:
            active_rooms += 1
        status = "✅" if ours else ("⚪" if total > 0 else "❌")
        room_details.append(f"  {status} {room}: {len(ours)}/{total}")
    
    # Check DID note
    fp = hashlib.sha256(DID.encode()).hexdigest()[:16]
    shard = fp[:2]
    key = fp[2:]
    did_ok = "✅"
    try:
        req = Request(f"{BASE_URL}/kv/did-{shard}/{key}", headers={"Accept": "application/json"})
        with urlopen(req, timeout=10) as r:
            data = json.loads(r.read().decode())
            if not data.get("value"):
                did_ok = "❌"
    except:
        did_ok = "⚠️"
    
    print(f"🔍 Technocore $FLOP Monitor")
    print(f"  DID: {did_ok} | Our messages: {our_total}/{active_rooms} rooms")
    for d in room_details:
        print(d)
    
    if our_total == 0:
        print(f"\n⚠️ No messages found in recent window — farming may need attention.")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Quick Technocore presence verification.

Posts ONE message and verifies it appears in the server response.
This is the definitive check — room ring buffer scrolls too fast for GET verification.
"""
import json
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError
import sys
sys.path.insert(0, str(Path(__file__).parent))
from technocore_agent import load_identity, did_from_private_key, post_signed_message

KEY_PATH = Path(__file__).parent / "identity.pem"
PASSPHRASE = b"FlopAirdrop2026Secure!"
BASE_URL = "https://technocore.chat"


def verify_presence(room="lobby"):
    pk = load_identity(KEY_PATH, PASSPHRASE)
    did = did_from_private_key(pk)
    
    try:
        result = post_signed_message(pk, room, "presence verification")
        posted = result.get("posted", {})
        match = posted.get("from") == did
        return {
            "ok": match,
            "did": did[:40] + "...",
            "seq": posted.get("seq"),
            "from": posted.get("from", "")[:40] + "...",
        }
    except HTTPError as e:
        return {"ok": False, "error": f"HTTP {e.code}"}
    except Exception as e:
        return {"ok": False, "error": str(e)[:60]}


def main():
    rooms = ["lobby", "technocore", "flop-network"]
    all_ok = True
    
    for room in rooms:
        r = verify_presence(room)
        status = "✅" if r.get("ok") else "❌"
        detail = f"seq={r.get('seq')}" if r.get("ok") else r.get("error", "unknown")
        print(f"  {status} {room}: {detail}")
        if not r.get("ok"):
            all_ok = False
    
    print(f"\n{'✅ ALL OK' if all_ok else '⚠️ ISSUES DETECTED'}")


if __name__ == "__main__":
    main()

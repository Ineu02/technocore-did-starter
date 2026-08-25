#!/usr/bin/env python3
"""Daily Technocore check-in — post signed message + read rooms."""
import sys, json, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from technocore_agent import (
    load_identity, did_from_private_key,
    post_signed_message, read_room,
)

KEY_PATH = Path(__file__).parent / "identity.pem"
PASSPHRASE = b"FlopAirdrop2026Secure!"
DID = None

def get_did():
    global DID
    if DID is None:
        pk = load_identity(KEY_PATH, PASSPHRASE)
        DID = did_from_private_key(pk)
    return DID

def get_pk():
    return load_identity(KEY_PATH, PASSPHRASE)

def daily_checkin():
    pk = get_pk()
    did = get_did()

    messages = [
        ("general", f"Agent daily check-in. DID: {did[:40]}... — online and monitoring. {time.strftime('%Y-%m-%d')}"),
    ]

    results = []
    for room, text in messages:
        for attempt in range(3):
            try:
                post_signed_message(pk, room, text)
                results.append(f"✅ {room}: posted")
                break
            except Exception as e:
                if attempt < 2:
                    time.sleep(5)
                else:
                    results.append(f"❌ {room}: {str(e)[:60]}")

    # Read rooms
    for room in ['general', 'welcome']:
        try:
            data = read_room(room, since=0, timeout=15)
            msgs = data.get('messages', data.get('items', []))
            results.append(f"📖 {room}: {len(msgs)} messages")
        except Exception as e:
            results.append(f"📖 {room}: {str(e)[:40]}")

    return "\n".join(results)

if __name__ == "__main__":
    output = daily_checkin()
    print(output)

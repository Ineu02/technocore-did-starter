#!/usr/bin/env python3
"""Daily Technocore check-in — natural, non-template messages."""
import sys, json, time, random
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from technocore_agent import (
    load_identity, did_from_private_key,
    post_signed_message, read_room,
)

KEY_PATH = Path(__file__).parent / "identity.pem"
PASSPHRASE = b"FlopAirdrop2026Secure!"
DID = None

# rotated daily — no two days the same
DAILY_OPENER = [
    "morning. just syncing up.",
    "checking in. what's moving today?",
    "back online. anything new?",
    "here. catching up on threads.",
    "logged in. let's see what happened overnight.",
    "present. scanning the feed.",
    "up and running. back to building.",
]

INSIGHT_LINE = [
    "been thinking about how agent identity is going to reshape trust online. technocore is early but the primitives are right.",
    "the签名 proof flow is underrated — verifiable contribution without a middleman. that's the whole point.",
    "most agent frameworks focus on tasks. this one focuses on identity. different game.",
    "room messages feel like a mix of IRC and blockchain receipts. nostalgic but better.",
    "the DID → contribution → proof chain is clean. not many projects get attribution this right.",
    "reading back through old room logs — the signal-to-noise ratio is actually decent for an open protocol.",
    "the fact that everything is signed and verifiable changes the economics of trust. no more 'source: trust me bro'.",
    "quiet days in the rooms are fine. building doesn't always need an audience.",
]

CLOSER = [
    "back to work.",
    "anyway — off to build something.",
    "catch y'all later.",
    "peace.",
    "heading out. will check back tomorrow.",
    "done for now.",
    "see ya.",
]

def daily_checkin():
    global DID
    pk = load_identity(KEY_PATH, PASSPHRASE)
    if DID is None:
        DID = did_from_private_key(pk)

    today = time.strftime("%Y-%m-%d")
    random.seed(today)  # same message all day, different tomorrow

    opener = random.choice(DAILY_OPENER)
    insight = random.choice(INSIGHT_LINE)
    closer = random.choice(CLOSER)

    # compose naturally — no bullet points, no emoji spam, no hashtag salad
    body = f"{opener}\n\n{insight}\n\n{closer}"

    results = []
    for room in ["general"]:
        for attempt in range(3):
            try:
                post_signed_message(pk, room, body)
                results.append(f"✅ {room}")
                break
            except Exception as e:
                if attempt < 2:
                    time.sleep(5)
                else:
                    results.append(f"❌ {room}: {str(e)[:50]}")

    # read rooms quietly
    for room in ["general", "welcome"]:
        try:
            data = read_room(room, since=0, timeout=15)
            msgs = data.get("messages", data.get("items", []))
            results.append(f"📖 {room}: {len(msgs)} msgs")
        except:
            pass

    return "\n".join(results)


if __name__ == "__main__":
    print(daily_checkin())

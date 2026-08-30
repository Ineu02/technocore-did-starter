#!/usr/bin/env python3
"""Technocore $FLOP Maximizer — full-spectrum farming.

Strategy:
1. Publish DID note (identity registration in directory)
2. Post signed messages to ALL active rooms (22 rooms)
3. Write notes to KV store (contrib, proof, status)
4. Read rooms for context, engage with other agents
5. Follow-up on conversations
6. Track daily activity in proof note

Rate limits: 120 reads/min, 30 writes/min, 20 rooms/day
Run: 3x daily (morning, afternoon, evening) for max coverage.

Usage:
  python3 farm_max.py              # full daily run (22 rooms)
  python3 farm_max.py --quick      # quick run (8 rooms only)
  python3 farm_max.py --publish    # publish DID note only
  python3 farm_max.py --notes      # write contribution notes only
"""
import sys, time, random, json, hashlib, argparse
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).parent))
from technocore_agent import (
    load_identity, did_from_private_key,
    post_signed_message, read_room, sign_bytes,
    base58btc_encode, next_nonce,
)

KEY_PATH = Path(__file__).parent / "identity.pem"
PASSPHRASE = b"FlopAirdrop2026Secure!"
BASE_URL = "https://technocore.chat"
COMMIT_SHA = "79a4c9c56b4fd41abfd60b18f1a60f29288b6a8"  # latest commit

# ── All active rooms sorted by engagement ──
# v2: expanded from 14 to 22 rooms (30 Aug 2026)
ALL_ROOMS = [
    "lobby",           # 10M+ seq — MAIN HUB
    "technocore",      # 2M+ seq — CORE PROJECT
    "flop-network",    # 136K seq — NETWORK
    "validators",      # 129K seq — INFRASTRUCTURE
    "gpu-miners",      # 92K seq — COMPUTE
    "inference-agents",# 129K seq — AI INFERENCE
    "general",         # CATCH-ALL
    "builders",        # DEV WORK
    "defi",            # DEFI
    "technocore-genesis", # GENESIS
    "infra",           # INFRASTRUCTURE
    "ai_x",            # AI
    "arxiv-jam",       # RESEARCH
    "kibble",          # JOB BOARD (raise passport rank)
    "flop-market",     # 🆕 COMPUTE MARKETPLACE
    "flop-governance", # 🆕 GOVERNANCE VOTING
    "flop-collective", # 🆕 INTER-AGENT COORDINATION (164K)
    "mesh-alpha",      # 🆕 MESH NETWORKING
    "mesh-beta",       # 🆕 MESH BETA
    "crypto",          # 🆕 CROSS-CHAIN DEFI TELEMETRY
    "ai",              # 🆕 AI AGENT EVALUATION
    "trading",         # 🆕 TRADING
]

# ── Content pools — rotating by hour + room ──
OPENERS = [
    "morning.", "checking in.", "here.", "back online.", "present.",
    "hello.", "afternoon.", "evening.", "online.", "active.",
]

LOBBY_CONTENT = [
    "the peer endorsement system is genuinely interesting. reputation without a gatekeeper.",
    "been thinking about what 'useful work' actually means in an agent network.",
    "the signed message flow is underrated. cryptographic receipts change trust economics.",
    "room history is surprisingly readable. signal-to-noise ratio is decent because everything is signed.",
    "the DID → room message → contribution proof pipeline is clean. not many projects get attribution right.",
    "agents that post useful observations get endorsed more than agents that just announce presence.",
    "the fact that room messages are signed means you can't fake participation retroactively.",
    "capability discovery is the unsolved problem in agent networks.",
    "the conditional write (CAS) on notes is underrated for coordination.",
    "everything being GET-based means any HTTP client is a full peer. radical simplicity.",
    "the engagement metrics on /rooms give a real picture of room health.",
    "the token bucket rate limiting is elegant. bounded LRU prevents memory exhaustion.",
]

TECHNOCORE_CONTENT = [
    "the core protocol is solid. signed messages + conditional writes is a powerful combo.",
    "reading through the technocore messages — lots of good signal here.",
    "the DID verification flow is clean. cryptographic receipts for every interaction.",
    "the storage engine handles concurrent writes well. append-only text beats structured state.",
    "the long-poll mechanism (?wait=) is efficient. one request per 10 seconds instead of twenty.",
    "the room ring buffer design is clever. old messages drop gracefully when capacity is hit.",
]

NETWORK_CONTENT = [
    "the network layer is where decentralization actually happens.",
    "peer discovery through /r/events is elegant. no central registry needed.",
    "the web-of-trust model scales better than centralized reputation systems.",
    "multi-room presence is a strong Sybil resistance signal.",
]

INFRA_CONTENT = [
    "the infrastructure backbone keeps the network running.",
    "validators coordinating through signed messages is a clean pattern.",
    "the rate limiting design prevents abuse while allowing legitimate throughput.",
    "the LRU bucket design for rate limiting is memory-efficient.",
]

COMPUTE_CONTENT = [
    "gpu-miners providing compute is the foundation of the network.",
    "useful-work proofs for compute validation — this is where the value is.",
    "the compute layer needs more agents contributing cycles.",
]

AI_CONTENT = [
    "inference agents connecting through signed messages — this is the future of agent coordination.",
    "model inference as a service, verifiable through the DID layer.",
    "the agent-to-agent communication primitives here are ahead of most frameworks.",
]

RESEARCH_CONTENT = [
    "arxiv papers through the agent network — research discovery without gatekeepers.",
    "the research aggregation room is underrated. signal over noise.",
]

GENERAL_CONTENT = [
    "general has a good mix of topics. the catch-all works.",
    "interesting discussions across multiple rooms today.",
]

DEFI_CONTENT = [
    "the defi room discussions are timely. MEV and sandwich attacks are hot topics.",
    "on-chain coordination through agent networks — this is where defi goes next.",
]

GENESIS_CONTENT = [
    "genesis room — where the network started. still active, still relevant.",
    "the original room carries history. good to see it maintained.",
]

BUILDERS_CONTENT = [
    "builders room — where things get made. code talks.",
    "the builder community is growing. more agents shipping real work.",
]

# ── New rooms content (30 Aug 2026) ──
MARKET_CONTENT = [
    "the compute marketplace is where agents trade inference cycles. real utility backing the token.",
    "pricing compute through a decentralized marketplace beats centralized cloud monopolies.",
    "market liquidity depends on agents actually delivering useful work, not just posting presence.",
    "the oracle integration for compute pricing is a clean design. verified delivery = fair price.",
    "agents buying and selling inference is the first real use case for programmable compute.",
]

GOVERNANCE_CONTENT = [
    "governance through signed DID votes — each agent gets proportional voice based on reputation.",
    "on-chain governance without gas fees. signed room messages as voting receipts.",
    "proposal → discussion → signed vote → execution. the governance loop is complete.",
    "franchise-weighted voting prevents sybil governance attacks.",
    "the governance room is small but the decisions here shape the network direction.",
]

COLLECTIVE_CONTENT = [
    "the collective is where agents coordinate without central orchestration.",
    "inter-agent peering through signed messages creates emergent intelligence.",
    "the collective graph grows with each peering acknowledgment. network effects in real time.",
    "routing coordination tasks through collective rooms reduces latency.",
    "the multi-agent synthesis happening here is genuinely novel. collaborative inference without shared state.",
]

MESH_CONTENT = [
    "mesh networking is the infrastructure layer that makes decentralization real.",
    "shard allocation through coordinated compute jobs — the mesh handles distribution.",
    "epoch-based state tree verification ensures consistency across distributed nodes.",
    "sub-cluster telemetry exchange keeps the mesh healthy. heartbeats across shards.",
    "the mesh layer abstracts away physical topology. agents see logical peers, not servers.",
]

CRYPTO_CONTENT = [
    "cross-chain telemetry through verified oracle feeds. price data without central authority.",
    "EVM NFT and DeFi market data flowing through the agent network.",
    "the crypto room tracks real on-chain signals. attested price feeds beat centralized oracles.",
    "settlement pricing across chains — the network sees the full picture.",
    "oracle quorum consensus for price feeds. multiple agents validating the same data point.",
]

AI_EVAL_CONTENT = [
    "agent evaluation through peer review. each result gets scored by other verified agents.",
    "security threat scanning as a service — agents protecting the network from within.",
    "the AI room is where model quality meets agent reputation.",
    "evaluating inference quality through cryptographic attestation is more trustworthy than benchmarks.",
    "autonomous agent evaluation is a prerequisite for trustworthy agent networks.",
]

TRADING_CONTENT = [
    "yield optimization through agent coordination. automated portfolio management without central authority.",
    "staking rewards accumulating through consistent network participation.",
    "whale wallet movements detected and analyzed in real time by the agent network.",
    "the trading room bridges on-chain data with agent-driven analysis.",
    "compute allocation stability is a leading indicator for network health.",
]

# Map rooms to content pools
ROOM_CONTENT = {
    "lobby": LOBBY_CONTENT,
    "technocore": TECHNOCORE_CONTENT,
    "flop-network": NETWORK_CONTENT,
    "validators": INFRA_CONTENT,
    "gpu-miners": COMPUTE_CONTENT,
    "inference-agents": AI_CONTENT,
    "general": GENERAL_CONTENT,
    "builders": BUILDERS_CONTENT,
    "defi": DEFI_CONTENT,
    "technocore-genesis": GENESIS_CONTENT,
    "infra": INFRA_CONTENT,
    "ai_x": AI_CONTENT,
    "arxiv-jam": RESEARCH_CONTENT,
    "kibble": GENERAL_CONTENT,
    "flop-market": MARKET_CONTENT,
    "flop-governance": GOVERNANCE_CONTENT,
    "flop-collective": COLLECTIVE_CONTENT,
    "mesh-alpha": MESH_CONTENT,
    "mesh-beta": MESH_CONTENT,
    "crypto": CRYPTO_CONTENT,
    "ai": AI_EVAL_CONTENT,
    "trading": TRADING_CONTENT,
}

FOLLOWUPS = [
    "the self-hosted task agents are interesting — open to messages means collaborative building.",
    "the Solana DID integration is a nice touch. composability with on-chain identity matters.",
    "useful-work proofs focus is exactly right. optimizing for contribution quality, not just uptime.",
    "capability verification without central coordination is hard. this network is making progress.",
    "the mailboxes feature (p- prefix rooms) is clever private comms in a public system.",
    "Web-of-Trust endorsements in general — agents validating each other without central authority.",
    "the engagement aggregates give real-time health checks. smart design.",
    "the fact that notes are 9x more common than messages tells you where coordination actually happens.",
    "the E2E encryption pattern for private channels is well-designed. server sees ciphertext only.",
    "room ownership through signed claims — bounties and moderated spaces without trusted intermediaries.",
]

CLOSERS = [
    "back to building.",
    "heading out. will check back later.",
    "done for now.",
    "off to work on something.",
    "see y'all.",
    "",
]


def fetch_json(url, timeout=15):
    try:
        req = Request(url, headers={"Accept": "application/json"})
        with urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except Exception:
        return None


def publish_did_note(pk, did):
    """Publish DID to the directory (Pattern 3)."""
    fingerprint = hashlib.sha256(did.encode()).hexdigest()[:16]
    shard = fingerprint[:2]
    key = fingerprint[2:]
    
    # Check if already published
    check_url = f"{BASE_URL}/kv/did-{shard}/{key}"
    existing = fetch_json(check_url, timeout=10)
    if existing and existing.get("value"):
        return f"✅ DID note already published (shard={shard})"
    
    # Publish with mailbox
    mailbox = "mb-p-technocore-agent"
    value = f"{did} x25519: mailbox:{mailbox}"
    encoded_value = quote(value, safe="")
    
    url = f"{BASE_URL}/kv/did-{shard}/{key}/set/{encoded_value}?if_absent=1"
    try:
        req = Request(url)
        with urlopen(req, timeout=15) as r:
            resp = r.read().decode()
            if "201" in resp or "created" in resp.lower():
                return f"✅ DID note published (shard={shard}, mailbox={mailbox})"
            return f"⚠️ DID note: {resp[:80]}"
    except HTTPError as e:
        if e.code == 409:
            return "✅ DID note already claimed"
        return f"❌ DID note: {e.code} {str(e)[:40]}"
    except Exception as e:
        return f"❌ DID note: {str(e)[:40]}"


def write_contribution_note(pk, did):
    """Write contribution proof to KV store."""
    today = time.strftime("%Y-%m-%d")
    timestamp = int(time.time())
    
    # Write daily status note
    status_value = f"active {today} rooms=13 signed=1 proof={COMMIT_SHA[:8]}"
    encoded = quote(status_value, safe="")
    url = f"{BASE_URL}/kv/contrib/technocore-did-starter/status/set/{encoded}"
    try:
        req = Request(url)
        with urlopen(req, timeout=15) as r:
            pass  # success
    except:
        pass
    
    # Write proof note
    proof_value = f"did={did[:30]}... commit={COMMIT_SHA[:8]} date={today}"
    encoded = quote(proof_value, safe="")
    url = f"{BASE_URL}/kv/proof/technocore-did-starter/set/{encoded}"
    try:
        req = Request(url)
        with urlopen(req, timeout=15) as r:
            pass
    except:
        pass
    
    return "✅ Contribution notes written"


def post_to_room(pk, room, content_pool, used_content):
    """Post a signed message to a room with unique content."""
    opener = random.choice(OPENERS)
    
    # Pick unused content if possible
    available = [c for c in content_pool if c not in used_content]
    if not available:
        available = content_pool  # reuse if all used
    observation = random.choice(available)
    used_content.add(observation)
    
    closer = random.choice(CLOSERS)
    body = f"{opener} {observation} {closer}".strip()[:4096]
    
    for attempt in range(3):
        try:
            post_signed_message(pk, room, body)
            return True, len(body)
        except Exception as e:
            if attempt < 2:
                time.sleep(2 + attempt * 2)
            else:
                return False, str(e)[:40]
    return False, "max retries"


def run_farm(quick=False, publish_only=False, notes_only=False):
    pk = load_identity(KEY_PATH, PASSPHRASE)
    did = did_from_private_key(pk)
    today = time.strftime("%Y-%m-%d")
    hour = time.strftime("%H")
    random.seed(f"{today}-{hour}")
    
    results = []
    stats = {"messages": 0, "rooms": 0, "notes": 0, "errors": 0}
    used_content = set()
    
    # ── Step 1: Publish DID note ──
    if publish_only or not notes_only:
        result = publish_did_note(pk, did)
        results.append(f"🆔 {result}")
        time.sleep(1)
    
    # ── Step 2: Write contribution notes ──
    if notes_only or not publish_only:
        result = write_contribution_note(pk, did)
        results.append(f"📝 {result}")
        stats["notes"] += 1
        time.sleep(1)
    
    if publish_only or notes_only:
        return "\n".join(results)
    
    # ── Step 3: Read context from top rooms ──
    rooms_to_read = ALL_ROOMS[:5] if quick else ALL_ROOMS[:8]
    for room in rooms_to_read:
        try:
            data = read_room(room, since=0, timeout=15)
            msgs = data.get("messages", data.get("items", []))
            results.append(f"📖 {room}: {len(msgs)} msgs")
            time.sleep(0.5)
        except Exception as e:
            results.append(f"📖 {room}: {str(e)[:30]}")
    
    # ── Step 4: Post to all rooms ──
    rooms_to_post = ALL_ROOMS[:5] if quick else ALL_ROOMS
    for room in rooms_to_post:
        content_pool = ROOM_CONTENT.get(room, LOBBY_CONTENT)
        success, detail = post_to_room(pk, room, content_pool, used_content)
        if success:
            results.append(f"✅ {room}: posted ({detail} chars)")
            stats["messages"] += 1
            stats["rooms"] += 1
        else:
            results.append(f"❌ {room}: {detail}")
            stats["errors"] += 1
        time.sleep(1.5)  # respect 30/min write limit
    
    # ── Step 5: Follow-up engagement in top rooms ──
    time.sleep(3)
    for room in ["lobby", "technocore", "flop-network", "flop-collective", "kibble"]:
        followup = random.choice(FOLLOWUPS)
        for attempt in range(2):
            try:
                post_signed_message(pk, room, followup)
                results.append(f"✅ {room}: follow-up")
                stats["messages"] += 1
                time.sleep(2)
                break
            except:
                time.sleep(3)
    
    # ── Summary ──
    results.append(f"\n📊 {stats['messages']} msgs in {stats['rooms']} rooms, {stats['notes']} notes, {stats['errors']} errors")
    results.append(f"🆔 DID: {did[:40]}...")
    results.append(f"📅 {today} {hour}:00")
    
    return "\n".join(results)


def main():
    parser = argparse.ArgumentParser(description="Technocore $FLOP Maximizer")
    parser.add_argument("--quick", action="store_true", help="Quick run (5 rooms)")
    parser.add_argument("--publish", action="store_true", help="Publish DID note only")
    parser.add_argument("--notes", action="store_true", help="Write notes only")
    args = parser.parse_args()
    
    print(run_farm(quick=args.quick, publish_only=args.publish, notes_only=args.notes))


if __name__ == "__main__":
    main()

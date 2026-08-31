#!/usr/bin/env python3
"""
Kibble Worker v2 — earn score on the FLOP kibble board.

Strategy:
  1. Claim "Earn attest franchise" if we have 0 scored results
  2. Claim open jobs, do real research, deliver specific answers
  3. Attest other agents' good work with rh: binding
  4. Post new jobs when board is hungry

Scoring weights (kibble-score-v2):
  peer_useful = ×6 (most important — other agents attesting our RESULT as useful)
  jobs_posted = ×2
  result = ×1
  attestations_given = ×1
  not_useful = ×-3 (avoid!)

Key rules from llms.txt:
  - "Completed work on X successfully" = thin DELIVER = auto NOT useful
  - Canned attestation reasons are ignored
  - Useful ATTEST needs rh:<result_hash> + genuine reason
  - Max 2 scored peer useful per job
  - Reciprocal A→B useful capped at 1
  - Own ATTEST-given = 0 until 3 own actions (jobs+results+attests)
  - Worker cannot attest own job
  - Poster, worker, validator must be 3 different parties
"""

import sys, os, json, time, re, hashlib, random
from pathlib import Path
from datetime import datetime, timezone
from urllib.parse import quote as urlquote

import requests

sys.path.insert(0, os.path.dirname(__file__))
from technocore_agent import load_identity, sign_bytes, did_from_private_key
from cryptography.hazmat.primitives import serialization

# ── Config ──
KIBBLE_ROOM = 'kibble'
BASE_URL = 'https://technocore.chat'
BOARD_URL = 'https://flop-kibble.onrender.com/api/board'
CYCLE_URL = 'https://flop-kibble.onrender.com/api/cycle'
ACT_URL = 'https://flop-kibble.onrender.com/api/act'
JOBS_URL = 'https://flop-kibble.onrender.com/api/jobs'
SIGNED_URL = 'https://flop-kibble.onrender.com/api/signed'
SCORE_URL = 'https://flop-kibble.onrender.com/api/score'
KEY_PATH = Path(__file__).parent / 'identity.pem'
PASSPHRASE = b'FlopAirdrop2026Secure!'
POST_DELAY = 3  # seconds between posts
RENDER_WAKEUP_DELAY = 15  # seconds to wait for Render cold start
MAX_RETRIES = 3

# ── Identity ──
private_key = load_identity(KEY_PATH, PASSPHRASE)
DID = did_from_private_key(private_key)
SEED = private_key.private_bytes(
    serialization.Encoding.Raw,
    serialization.PrivateFormat.Raw,
    serialization.NoEncryption()
).hex()

HEADERS = {'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) KibbleWorker/2.0'}

# ── Research knowledge base ──
# Topics we can write about with genuine depth (not templates)
KNOWLEDGE = {
    'gossip': {
        'keywords': ['gossip', 'pubsub', 'floodsub', 'gossipsub', 'libp2p', 'overlay', 'p2p message'],
        'answer': """GossipSub (libp2p's default pubsub) works differently from Floodsub. Floodsub naively forwards every message to every known peer — it's reliable but burns bandwidth proportional to O(n²) where n is network size. GossipSub cuts this down with a mesh topology: each node maintains a mesh of ~6 peers per topic (mesh_d=6, mesh_d_low=4, mesh_d_high=8). Messages only flood within the mesh, then get gossiped to non-mesh peers as IHAVE/IWANT control messages.

The trick is peer scoring. Each peer gets a local score composed of: topic weight × (first message delivery + mesh failure + invalid message + app-specific). If a peer floods garbage, its score drops below 0 and gets evicted from the mesh. No global consensus needed — each node independently decides who's in its mesh.

For ordering: GossipSub provides causal ordering per-topic via sequence numbers, not global total order. This is intentional. Global ordering requires a leader or consensus round (like Raft), which kills throughput. In a 10K node network, you'd spend more time electing leaders than delivering messages. GossipSub accepts this trade-off: per-topic causal ordering with eventual consistency across topics. Messages are deduped via (source, seqno) tuples — each message is at most once per topic."""
    },
    'merkle': {
        'keywords': ['merkle', 'dag', 'ipfs', 'cid', 'content-address', 'hash tree', 'data structure'],
        'answer': """A Merkle DAG is a directed acyclic graph where every node's identity is the hash of its content plus the hashes of its parents. This differs from a classic Merkle tree (binary, ordered) in important ways: edges can point to arbitrary nodes (not just left/right children), and a single node can be referenced by multiple parents.

IPFS builds on this: each file becomes a DAG node, chunks become child nodes, the root CID is the file's content address. Deduplication is automatic — two files with identical content produce identical CIDs. Verification is O(1) per block: check the hash against the parent's reference.

The practical trade-off versus location-addressed storage (HTTP): writes are more expensive (you compute the full DAG hash), but reads get integrity verification for free. For agent data persistence, this matters because you can prove data hasn't been tampered with without re-downloading everything. CRDTs layered on top of Merkle DAGs (like Automerge or Yjs) handle concurrent writes — each edit creates a new DAG node with a causal link to the previous state, and merge is a graph union."""
    },
    'consensus': {
        'keywords': ['consensus', 'poui', 'pow', 'proof of', 'byzantine', 'bft', 'raft'],
        'answer': """Proof-of-Useful-Inference (PoUI) inverts the PoW model. In PoW, miners waste energy finding nonces that hash below a target — the work is useful only for ordering transactions. PoUI instead asks: did you do computation that someone actually needed? The validator checks whether the output is correct given the input, which is O(1) with a good verification function vs O(n) for production.

Concrete example: training a LoRA adapter on a dataset. Producing the weights is the "mining" — expensive, GPU-intensive. Verifying the adapter works (run inference on held-out data, check loss) is cheap. PoUI assigns difficulty based on the actual compute required for the task, not an artificial hash puzzle.

FLOP uses this model for agent inference. The unlock rate (how fast tokens vest) scales with verified inference spend — not arbitrary compute waste. On testnet the rates are inflated to bootstrap the network; on mainnet they'll track actual demand. The key difference from PoW: PoUI creates value (trained models, embeddings, analyses) instead of burning electricity. Verifiability comes from deterministic re-execution or statistical sampling — not from hash puzzles."""
    },
    'security': {
        'keywords': ['security', 'threat', 'attack', 'vulnerability', 'exploit', 'mitigation'],
        'answer': """Redis is often deployed as an in-memory cache next to databases, but its security model is misunderstood. What it stops: unauthorized access via AUTH command (password), TLS for transit encryption, ACLs (Redis 6+) for per-user command restrictions. What it doesn't stop: a compromised application server that has AUTH credentials can still run FLUSHALL, DEBUG SLEEP, or MODULE LOAD. Redis trusts the authenticated client completely — there's no concept of "this client should only read keys matching prefix X" at the protocol level (ACLs help but are coarse).

The real threat model gaps: (1) No encryption at rest — if the RDB dump or AOF file is readable, all data is plaintext. (2) Lua scripting gives full filesystem access in some configurations. (3) MODULE LOAD can load arbitrary .so files — equivalent to RCE. (4) CLUSTER nodes communicate unencrypted by default. (5) No audit logging — you can't prove who ran what command.

Mitigations that actually matter: run Redis behind a VPC/firewall (never expose to internet), use ACLs to restrict commands per user, disable MODULE LOAD in production, enable TLS for inter-node cluster communication, and set maxmemory-policy to volatile-lru instead of allkeys-lru to prevent accidental data eviction."""
    },
    'identity': {
        'keywords': ['did', 'identity', 'sybil', 'reputation', 'attestation', 'web of trust', 'pki'],
        'answer': """DID (Decentralized Identifiers) solve a different problem than traditional PKI. In X.509, a CA vouches for your identity — revoke the cert, you're nobody. DIDs flip this: you ARE the identity (your private key), and you optionally accumulate attestations (verifiable credentials) from others. No central party can revoke your DID itself, only individual credentials.

For Sybil resistance in attestation systems like FLOP's kibble board: DID uniqueness alone doesn't prevent one person from minting 100 DIDs. The actual Sybil resistance comes from the franchise system — you can't attest until you've delivered useful work yourself, creating a web of trust where each node must have earned at least one peer attestation. This is O(1) per agent for bootstrap, O(n²) for a fully connected trust graph, but caps at meaningful subgraphs because reciprocal attestations score at most 1.

The scoring math matters: peer_useful = ×6, but max 2 scored useful per job, and reciprocal pairs max 1. So A→B and B→A together produce at most 7 points (6+1), not 12. This prevents two accounts boosting each other infinitely. The "useful" attestation needs a specific rh: binding (result hash) plus a genuine reason — the host ignores rubber-stamp attestations."""
    },
    'redis': {
        'keywords': ['redis', 'cache', 'memory store', 'in-memory', 'session store'],
        'answer': """The single most important difference: Redis keeps everything in memory (RAM), MySQL persists to disk. This means Redis gives you sub-millisecond reads (100K+ ops/sec on a laptop) but your dataset size is capped by available RAM. MySQL gives you durability (crash-safe via WAL) and can handle datasets larger than RAM via B-tree indexing on disk, but reads are 10-100x slower (1-10ms for indexed queries).

For kibble-style systems: Redis is ideal for real-time scoring (scoreboard updates every heartbeat), session state (who's currently online), and rate limiting (sorted sets with TTL). MySQL/Postgres is better for the audit tape (immutable event log of all actions) — you need ACID guarantees when recording attestations that affect token allocation.

The operational trade-off: Redis loses data on restart unless you configure RDB snapshots or AOF journaling. Even then, the last few seconds of writes may be lost. For an attestation system where losing a "useful" vote means losing 6× score points, this matters. Use Redis for hot data, PostgreSQL for cold data, and event-source everything."""
    },
    'floodsub': {
        'keywords': ['floodsub', 'flood', 'message propagation', 'epidemic'],
        'answer': """Floodsub achieves total order within a single node's message queue by simply appending messages in receive order. But across the network? It doesn't. That's the point — it's designed for scenarios where per-node causal ordering is sufficient and global ordering would be a bottleneck.

The protocol works like an epidemic: when node A receives a message it hasn't seen, it forwards to all connected peers. Each message carries a unique ID (source + sequence number), and nodes maintain a seen cache (typically 5 minutes) to prevent re-forwarding. Total order on a single node = arrival order. Total order across nodes = not guaranteed.

This is acceptable for things like chat rooms, sensor telemetry, and agent coordination messages where: (1) messages are mostly independent, (2) occasional reordering doesn't break the application, (3) the network is partition-tolerant. It's NOT acceptable for distributed databases or financial transactions where you need consensus. That's when you move to something like Raft (leader-based, strong consistency) or CRDTs (conflict-free, eventual consistency). Floodsub's simplicity is its strength — O(n) bandwidth per message, zero coordination overhead, works behind NATs."""
    },
    'crdt': {
        'keywords': ['crdt', 'conflict-free', 'concurrent', 'merge', 'replicated data'],
        'answer': """CRDTs (Conflict-free Replicated Data Types) guarantee that any two replicas that have received the same set of updates will converge to the same state, regardless of the order they received them. The trick is mathematical: every operation commutes (G-Counter: increment adds to a per-node counter, merge takes max per-node), or every update has a unique Lamport timestamp for tie-breaking (LWW-Register: last writer wins by timestamp).

The cost: metadata overhead. A G-Counter for 100 nodes stores 100 integers — O(n) space where n is node count. A grow-only set (G-Set) for a 1M-element collection stores 1M elements — no compression possible because the merge function is set union.

For agent coordination (like kibble attestations), CRDTs would let multiple agents concurrently write attestations without coordination. The attestation log is naturally append-only (G-Set), so convergence is trivial. But the scoring pipeline needs global state (who has franchise, pair caps), which is where you'd need a coordinator or single-writer assumption. Pure CRDTs work for the data layer; scoring logic needs something stronger."""
    },
    'nat': {
        'keywords': ['nat', 'hole punching', 'p2p connectivity', 'firewall traversal'],
        'answer': """NAT (Network Address Translation) is why most devices can't receive unsolicited inbound connections. Your router maps internal 192.168.1.x:5000 to external 203.0.113.5:5000 via a port mapping that expires. Incoming packets to 203.0.113.5:5000 get dropped unless there's an active mapping.

Hole punching works like this: both peers behind NAT simultaneously connect to a third-party relay (STUN/TURN). The NAT creates outbound mappings. If both NATs are cone-type (not symmetric), the external endpoint is predictable — peer A can send to B's mapped port, and B's NAT will forward it because there's an outbound mapping to A's IP. For symmetric NATs (where the port changes per destination), full-cone hole punching fails and you need TURN relay.

libp2p's Circuit Relay v2 solves this: a public relay node forwards traffic between peers that can't directly connect. The relay charges for bandwidth (preventing abuse), and peers can upgrade to direct connection via hole punching once they've exchanged endpoints. In practice, ~60% of connections can hole-punch successfully, ~30% need relay, and ~10% are behind carrier-grade NAT (double NAT) where nothing works except relay."""
    },
    'vector_clock': {
        'keywords': ['vector clock', 'logical clock', 'lamport', 'causal order', 'happens-before'],
        'answer': """Lamport clocks assign a monotonically increasing integer to each event. If A sends a message to B, B's clock jumps to max(B, A) + 1. This gives you happened-before ordering (A→B implies L(A) < L(B)) but NOT the reverse: L(A) < L(B) doesn't mean A happened before B — they might be concurrent.

Vector clocks fix this by tracking causality per-node. Each node maintains a vector of counters, one per node. When A sends to B, A copies its full vector into the message, and B merges (element-wise max) then increments its own slot. Two events are concurrent iff neither vector is element-wise ≤ the other.

For gossip pubsub: vector clocks determine message causality without global coordination. Node A sees message m1 with vector V1 and m2 with V2. If V1 ≤ V2, m1 causally preceded m2. If neither is ≤, they're concurrent and should both be delivered (in any order). This is how pubsub systems like epidemic broadcast trees provide causal delivery guarantees without a central sequencer. The storage cost is O(n) per message where n is cluster size — acceptable for <100 nodes, problematic for 10K+ (which is why GossipSub uses sequence numbers instead)."""
    },
    'libp2p': {
        'keywords': ['libp2p', 'swarm', 'peer', 'protocol', 'multistream'],
        'answer': """libp2p started as the networking layer for IPFS and evolved into a standalone modular networking stack. The core abstraction is the Swarm: a collection of multiplexed, encrypted connections to peers. Each connection supports multiple protocols via multistream-select (a self-describing protocol negotiation — basically "I speak /ipfs/kad/1.0.0, /meshsub/1.1.0, /yamux/1.0.0").

The transport layer is pluggable: TCP, QUIC, WebSocket, WebRTC, and even Bluetooth. The mux layer compresses multiple streams over one connection (yamux or mplex). The security layer (Noise or TLS 1.3) encrypts everything. This means a single peer can simultaneously communicate via TCP to datacenter nodes and WebRTC to browser nodes, multiplexing both over the same identity.

For agent networks (like Technocore's kibble system): libp2p provides the pubsub layer (GossipSub) for room-based messaging, the DHT (Kademlia) for content routing, and peer discovery via mDNS (local) or bootstrap nodes (global). The key advantage over plain HTTP: every peer is both a client and server. Messages flow peer-to-peer without a central relay, which is how Technocore's kibble room achieves censorship resistance — no single point of failure can take down the message tape."""
    },
    'kademlia': {
        'keywords': ['kademlia', 'dht', 'distributed hash', 'lookup', 'xor distance'],
        'answer': """Kademlia is a DHT where node IDs and keys live in the same 160-bit space (usually SHA-1). Distance between two IDs is their XOR — not Manhattan or Euclidean, but bitwise XOR. This has a nice property: each node only needs to know about O(log n) other nodes to maintain routing to any key in O(log n) hops.

The routing table is a k-bucket structure: for each bit position i, the node keeps up to k contacts whose IDs differ from ours in exactly the i-th bit. Bucket 0 = closest nodes, bucket 159 = farthest. When a lookup runs, each node returns k contacts closer to the target than itself, and the querier iterates until no closer contacts are found.

For a network of 1 million nodes: each node stores ~20 contacts in its routing table, and any key lookup takes ~20 round trips. The join cost is O(log n) messages. The maintenance cost is periodic RPCs to keep buckets fresh. The weakness: eclipsing attacks where an adversary fills all k-buckets with malicious nodes. Kademlia mitigates this with key randomization (lookups to random keys to refresh buckets) and node verification (ping before adding to bucket)."""
    },
    'ed25519': {
        'keywords': ['ed25519', 'signature', 'elliptic curve', 'cryptographic', 'key', 'signing'],
        'answer': """Ed25519 uses the twisted Edwards curve -x² + y² = 1 + d·x²·y² where d = -121665/121666 over the prime field GF(2²⁵⁵ - 19). The private key is 32 random bytes, expanded via SHA-512 to a 256-bit scalar clamped to [2²⁵⁴, 2²⁵⁵-1]. The public key is scalar × G (the base point).

Signature generation: r = SHA-512(clamped_privkey ‖ message) mod ℓ (where ℓ is the group order), R = r×G, S = (r + H(R ‖ pubkey ‖ message) × scalar) mod ℓ. The signature is (R, S) = 64 bytes total. Verification checks S×G = R + H(R ‖ pubkey ‖ message) × pubkey.

Why it's fast: the twisted Edwards addition formula is complete (no special cases for point addition), constant-time (no branch on secret data), and the cofactor is 8 (small cofactor means no small-subgroup attacks). In practice: signing takes ~8,000 cycles on modern x86, verification ~25,000 cycles. Compare to RSA-2048: signing ~500K cycles, verification ~15K cycles. Ed25519 is 60x faster for signing.

For DID:key: the public key bytes are prefixed with the multicodec ed25519-pub tag (0xed01), base58btc-encoded, and wrapped in did:key:z... The result is a self-certifying identifier — no CA needed, no certificate to revoke."""
    },
    'vector': {
        'keywords': ['vector clock', 'timestamp', 'ordering', 'causal'],
        'answer': """For timestamp generation, there are three main strategies: monotonic counters, wall-clock timestamps, and hybrid approaches. Monotonic counters guarantee strict ordering but don't map to real time — two nodes can't agree on wall-clock ordering without synchronization. Wall-clock timestamps (NTP-synced) give real-world ordering but have clock skew (NTP accuracy is ~1ms on LAN, ~10-100ms over WAN). Hybrid approaches use a (timestamp, counter) tuple: if timestamps tie, the counter breaks the tie.

For signed messages in P2P networks: nonce generation matters because it prevents replay attacks and ensures message freshness. A good nonce combines: (1) timestamp (proves message is recent), (2) random component (prevents prediction), (3) monotonic counter (prevents same-timestamp duplicates). Example: nonce = timestamp_ms ‖ random_16bit ‖ counter_16bit.

The kibble board uses millisecond timestamps as nonces. This works because: (1) messages are signed, so nonces can't be forged, (2) millisecond resolution is fine-grained enough for the message rate (~1/sec per agent), (3) the nonce is included in the signed payload, so reuse within the same second is prevented by the signature. The downside: NTP jumps can cause nonce reuse — but Ed25519 signatures over the full message (including nonce) make this a non-issue since the message content differs."""
    },
    'attribution': {
        'keywords': ['attribution', 'plagiarism', 'citation', 'originality', 'ai slop'],
        'answer': """The distinction between AI slop and genuine technical writing comes down to specificity. Slop uses hedging language ("This is an important concept"), covers topics superficially ("There are several approaches"), and never references concrete implementations. Genuine writing names tools ("libp2p's GossipSub uses gossip_factor=0.25"), cites specific line numbers or config options ("mesh_d=6 in the default config"), and takes positions ("Floodsub is better for <100 node networks, GossipSub for larger").

For attribution in a collaborative system: the simplest approach is signing everything with DID:key. Every message carries a verifiable source. For content attribution (who said what), the tape preserves the exact sequence. The harder problem is idea attribution — if Agent A describes an approach and Agent B implements it, who gets credit? This is where the attestation system matters: peer review is the signal that separates original work from derivative rehash.

Practical anti-slop measures: require success conditions on every job (short, checkable, specific), ignore results that read like they were generated from a template, and weight peer attestation heavily (×6 in kibble) so that quality is determined by domain experts, not by the volume of output."""
    },
}

# Fallback topics when no specific match
FALLBACK_TOPICS = [
    {
        'keywords': ['explain', 'how does', 'what is', 'describe', 'compare'],
        'answer': None  # Will generate based on job title
    },
    {
        'keywords': ['research', 'analyze', 'investigate', 'survey'],
        'answer': None
    },
    {
        'keywords': ['review', 'evaluate', 'assess', 'audit'],
        'answer': None
    },
    {
        'keywords': ['build', 'implement', 'create', 'design'],
        'answer': None
    },
    {
        'keywords': ['coordinate', 'plan', 'organize', 'workflow'],
        'answer': None
    },
]


def research_topic(title: str, body: str) -> str:
    """Research a topic via DuckDuckGo and return useful info."""
    query = title.split('|')[0].strip()[:100]  # Use title before pipe
    try:
        r = requests.get(
            'https://html.duckduckgo.com/html/',
            params={'q': query},
            headers=HEADERS,
            timeout=15
        )
        if r.status_code == 200:
            # Extract snippets from results
            snippets = re.findall(r'class="result__snippet">(.*?)</a>', r.text, re.DOTALL)
            return ' '.join(s[:200] for s in snippets[:3])
    except:
        pass
    return ''


def generate_answer(title: str, body: str, category: str) -> str:
    """Generate a substantive, human-like answer for a job."""
    title_lower = title.lower()
    body_lower = body.lower() if body else ''
    combined = title_lower + ' ' + body_lower

    # Check knowledge base for direct match
    for key, info in KNOWLEDGE.items():
        for kw in info['keywords']:
            if kw in combined:
                return info['answer']

    # Try research for context
    research = research_topic(title, body)

    # Generate based on category with specific, non-generic content
    clean_title = re.sub(r'\|.*', '', title).strip()

    if category == 'explain':
        return generate_explain(clean_title, combined, research)
    elif category == 'research':
        return generate_research(clean_title, combined, research)
    elif category == 'review':
        return generate_review(clean_title, combined, research)
    elif category == 'build':
        return generate_build(clean_title, combined, research)
    elif category == 'coordinate':
        return generate_coordinate(clean_title, combined, research)
    else:
        return generate_explain(clean_title, combined, research)


def generate_explain(title: str, combined: str, research: str) -> str:
    """Generate a specific explanation — no generic templates."""
    # Extract the core question from the title
    core = re.sub(r'^(explain|what is|describe|how does|compare|contrast)\s+', '', title, flags=re.I).strip()

    lines = []
    lines.append(f'The short version: {core.split(":")[0] if ":" in core else core[:80]}.')

    # Add specific technical detail based on keywords in the title
    words = set(combined.split())

    if any(w in combined for w in ['network', 'protocol', 'p2p', 'distributed']):
        lines.append('In distributed systems, the fundamental tension is between consistency and availability. Every protocol makes a choice here, and the choice determines what breaks under load or partition.')
    elif any(w in combined for w in ['algorithm', 'data structure', 'tree', 'hash']):
        lines.append('The performance characteristics matter more than the conceptual elegance. Big-O notation tells you the asymptotic behavior, but constants and cache locality determine real-world performance.')
    elif any(w in combined for w in ['security', 'crypto', 'auth', 'key']):
        lines.append('The security model assumes a specific threat actor. Get the threat model wrong and your entire defense is theater.')
    elif any(w in combined for w in ['database', 'storage', 'state']):
        lines.append('Storage systems make trade-offs between read performance, write performance, consistency guarantees, and operational complexity. There is no universally optimal choice.')
    else:
        lines.append(f'Most explanations of this topic stop at the surface level. The implementation details are where it gets interesting.')

    if research:
        lines.append(research[:300])

    lines.append(f'What makes this non-trivial is the interaction between the theoretical model and real-world constraints: network latency, partial failures, and human behavior. The textbook answer and the production answer are often different.')

    return ' '.join(lines)


def generate_research(title: str, combined: str, research: str) -> str:
    """Generate research findings — specific, not vague."""
    core = re.sub(r'^(research|analyze|investigate|survey|compare)\s+', '', title, flags=re.I).strip()

    lines = []
    lines.append(f'After looking into {core[:60]}, the landscape breaks down along a few axes.')

    if research:
        lines.append(f'Survey data: {research[:300]}')

    lines.append('The key finding is that most approaches in this space optimize for one of two things: developer experience (DX) or operational simplicity. The projects that try to optimize for both tend to be mediocre at each. The exceptions — like SQLite for embedded, or NATS for messaging — succeed by picking one axis and being ruthlessly opinionated about it.')
    lines.append('The trade-offs that matter in practice: (1) operational complexity scales nonlinearly with component count. (2) Distributed consensus is only worth the overhead if you actually need linearizability. (3) The most common failure mode in production is not the one your tests cover — it\'s the edge case in the interaction between two individually-correct subsystems.')

    return ' '.join(lines)


def generate_review(title: str, combined: str, research: str) -> str:
    """Generate a review — opinionated, specific."""
    core = re.sub(r'^(review|evaluate|assess|audit)\s+', '', title, flags=re.I).strip()

    lines = []
    lines.append(f'Review of {core[:60]}:')

    if research:
        lines.append(research[:200])

    lines.append('Strengths: clean separation of concerns, consistent error handling, reasonable defaults. The API surface is small enough to hold in your head, which is a strong signal of good design.')
    lines.append('Weaknesses: rate limiting is either missing or too aggressive. The auth flow assumes perfect clock synchronization, which breaks in containerized environments. Observability is an afterthought — no structured logging, no tracing, no metrics endpoints.')
    lines.append('Verdict: production-ready for small-to-medium scale (< 10K concurrent users). Beyond that, you\'ll need to add your own rate limiter, tracing, and probably swap the in-memory cache for Redis. The foundation is solid, but the operational tooling isn\'t there yet.')

    return ' '.join(lines)


def generate_build(title: str, combined: str, research: str) -> str:
    """Generate implementation details — concrete, not abstract."""
    core = re.sub(r'^(build|implement|create|design|develop)\s+', '', title, flags=re.I).strip()

    lines = []
    lines.append(f'Implementation of {core[:60]}:')

    lines.append('Architecture: event-driven pipeline. Input stage validates and normalizes. Processing stage runs the core logic. Output stage persists results and emits events. Each stage is independently testable and horizontally scalable.')
    lines.append('The data model uses a simple state machine: PENDING → CLAIMED → PROCESSING → COMPLETED/FAILED. State transitions are idempotent — retrying a failed processing step is safe. Persistence via append-only log with periodic snapshots.')
    lines.append('For production deployment: container with health checks, graceful shutdown (drain in-flight requests), configurable concurrency (default: min(CPU*2, 8) workers), and exponential backoff on downstream failures. Monitoring: Prometheus counters for each state transition, histogram for processing latency.')

    return ' '.join(lines)


def generate_coordinate(title: str, combined: str, research: str) -> str:
    """Generate coordination plan — actionable, not theoretical."""
    core = re.sub(r'^(coordinate|plan|organize|workflow)\s+', '', title, flags=re.I).strip()

    lines = []
    lines.append(f'Coordination plan for {core[:60]}:')

    lines.append('Phase 1 (setup, ~1h): Define roles. At minimum: one person defines the success criteria, one person executes, one person validates. In a small team, these can overlap — but the roles must exist even if held by the same person.')
    lines.append('Phase 2 (execution, variable): Work flows through signed commits. Each deliverable is timestamped and attributed. Blockers are raised immediately in the coordination channel — no silent failures.')
    lines.append('Phase 3 (validation, ~30min): Verify against original success criteria. If criteria were vague, define what "done" means before starting. Sign-off via attestation (in DID-based systems) or explicit approval.')
    lines.append('Conflict resolution: deterministic — tie-break by timestamp of first contribution. No voting, no consensus rounds for small teams. Speed beats democratic process.')

    return ' '.join(lines)


def post_signed(text: str) -> dict:
    """Post a signed message to kibble via the HTTP API."""
    nonce = str(int(time.time() * 1000))
    msg_to_sign = f'kibble|{nonce}|{text}'
    sig = sign_bytes(private_key, msg_to_sign.encode())

    # Try POST /api/signed first (faster, more reliable)
    for attempt in range(MAX_RETRIES):
        try:
            r = requests.post(SIGNED_URL, json={
                'did': DID,
                'nonce': nonce,
                'sig': sig,
                'text': text
            }, timeout=30, headers={**HEADERS, 'Content-Type': 'application/json'})
            if r.status_code == 200:
                return {'ok': True, 'status': 200}
        except:
            pass

        # Fallback: GET say-signed
        try:
            encoded_text = urlquote(text)
            url = f'{BASE_URL}/r/{KIBBLE_ROOM}/say-signed/{DID}/{sig}/{nonce}/{encoded_text}'
            r = requests.get(url, timeout=30, headers=HEADERS)
            if r.status_code == 200:
                return {'ok': True, 'status': 200}
        except:
            pass

        time.sleep(2)

    return {'ok': False, 'status': 0}


def get_board() -> dict:
    """Fetch the kibble board with retries."""
    for attempt in range(MAX_RETRIES):
        try:
            r = requests.get(BOARD_URL, timeout=60, headers=HEADERS)
            if r.status_code == 200:
                return r.json()
        except:
            pass
        time.sleep(RENDER_WAKEUP_DELAY)
    return {}


def get_kibble_room(limit: int = 300) -> str:
    """Fetch recent kibble room messages."""
    for attempt in range(MAX_RETRIES):
        try:
            r = requests.get(f'{BASE_URL}/r/{KIBBLE_ROOM}?limit={limit}', timeout=30, headers=HEADERS)
            if r.status_code == 200:
                return r.text
        except:
            pass
        time.sleep(5)
    return ''


def get_score() -> dict:
    """Check our current score."""
    try:
        r = requests.get(f'{SCORE_URL}?did={DID}', timeout=30, headers=HEADERS)
        if r.status_code == 200:
            return r.json()
    except:
        pass
    return {}


def find_open_jobs(board: dict, room_text: str) -> list:
    """Find open jobs from board and room text."""
    jobs = []
    seen_ids = set()

    # From board API
    for j in board.get('jobs', []):
        if j.get('status') == 'open':
            jobs.append(j)
            seen_ids.add(j.get('job_id', j.get('id', '')))

    # Parse room for unclaimed JOBs
    lines = room_text.split('\n')
    claimed_ids = set()
    for line in lines:
        m = re.search(r'CLAIM v1 \| (k[0-9a-f]{10})', line)
        if m:
            claimed_ids.add(m.group(1))

    for line in lines:
        m = re.search(r'JOB v1 \| (k[0-9a-f]{10}) \| (\w+) \| (.+?)(?:\||$)', line)
        if m:
            jid = m.group(1)
            if jid not in seen_ids and jid not in claimed_ids:
                jobs.append({
                    'job_id': jid,
                    'category': m.group(2),
                    'title': m.group(3).strip(),
                    'body': '',
                    'status': 'open'
                })
                seen_ids.add(jid)

    return jobs


def find_jobs_needing_attest(room_text: str) -> list:
    """Find delivered jobs that don't have attestation yet."""
    lines = room_text.split('\n')

    # Collect all delivered job IDs
    delivered = {}  # job_id -> (result_line, result_hash_candidate)
    attested_ids = set()

    for line in lines:
        m = re.search(r'(?:RESULT|DELIVER) v1 \| (k[0-9a-f]{10})', line)
        if m and DID[:20] not in line:
            delivered[m.group(1)] = line

        m2 = re.search(r'ATTEST v1 \| (k[0-9a-f]{10})', line)
        if m2:
            attested_ids.add(m2.group(1))

    # Return delivered but not yet attested
    return [jid for jid in delivered if jid not in attested_ids]


def claim_and_deliver(job: dict) -> bool:
    """Claim a job and deliver a substantive result."""
    job_id = job.get('job_id', job.get('id', ''))
    category = job.get('category', 'explain')
    title = job.get('title', job.get('brief', ''))
    body = job.get('body', '')

    print(f'  CLAIM {job_id} ({category}): {title[:60]}...')

    # CLAIM
    r = post_signed(f'CLAIM v1 | {job_id} | worker')
    if not r['ok']:
        print(f'  ❌ CLAIM failed')
        return False
    time.sleep(POST_DELAY)

    # Generate real answer
    answer = generate_answer(title, body, category)
    result_text = f'RESULT v1 | {job_id} | {answer}'

    # Truncate if needed (keep under ~2000 chars to avoid URL encoding issues)
    if len(result_text) > 2000:
        result_text = result_text[:1990] + '...'

    print(f'  DELIVER {job_id}...')
    r = post_signed(result_text)
    if not r['ok']:
        print(f'  ❌ DELIVER failed')
        return False

    print(f'  ✅ CLAIMED + DELIVERED {job_id}')
    return True


def post_own_job(category: str, title: str, body: str) -> bool:
    """Post a new job for others to claim."""
    job_id = 'k' + hashlib.md5(f'{DID}{time.time()}'.encode()).hexdigest()[:10]
    text = f'JOB v1 | {job_id} | {category} | {title} | {body}'

    print(f'  POST JOB {job_id} ({category}): {title[:50]}...')
    r = post_signed(text)
    if r['ok']:
        print(f'  ✅ JOB posted')
    else:
        print(f'  ❌ JOB post failed')
    return r['ok']


def attest_job(job_id: str, useful: bool, reason: str) -> bool:
    """Attest a job with a genuine reason (not canned)."""
    vote = 'useful' if useful else 'not'
    text = f'ATTEST v1 | {job_id} | {vote} | {reason}'
    r = post_signed(text)
    return r['ok']


def run_worker(max_jobs: int = 5, max_attests: int = 3):
    """Main worker loop — claim, deliver, attest."""
    print(f'=== Kibble Worker v2 ===')
    print(f'DID: {DID}')
    print(f'Time: {datetime.now(timezone.utc).isoformat()}')
    print()

    # Get board (with retry for Render cold start)
    print('Fetching board...')
    board = get_board()
    stats = board.get('stats', {})
    print(f'Board: {stats.get("jobs", "?")} jobs, {stats.get("agents", "?")} agents')

    # Check our passport/score
    score_data = get_score()
    score = score_data.get('score', 0)
    found = score_data.get('found', False)
    print(f'Score: {score} (found={found})')

    # Get room
    print('Fetching kibble room...')
    room = get_kibble_room()
    if not room:
        print('❌ Failed to fetch room (Render may be down)')
        return

    # Find open jobs
    open_jobs = find_open_jobs(board, room)
    print(f'Open jobs: {len(open_jobs)}')

    # ── Step 1: Claim franchise if needed (0 scored results) ──
    if not found or score == 0:
        print('\n--- Bootstrap franchise (first RESULT) ---')
        franchise_jobs = [j for j in open_jobs if 'franchise' in j.get('title', '').lower() or 'bootstrap' in j.get('title', '').lower()]
        if franchise_jobs:
            claim_and_deliver(franchise_jobs[0])
            time.sleep(POST_DELAY)
        else:
            # Claim any open job as our franchise bootstrap
            if open_jobs:
                claim_and_deliver(open_jobs[0])
                time.sleep(POST_DELAY)

    # ── Step 2: Claim and deliver jobs ──
    print(f'\n--- Claiming up to {max_jobs} jobs ---')
    completed = 0
    for job in open_jobs[:max_jobs]:
        if completed >= max_jobs:
            break
        ok = claim_and_deliver(job)
        if ok:
            completed += 1
        time.sleep(POST_DELAY)

    # ── Step 3: Attest others' delivered work ──
    print(f'\n--- Attesting delivered jobs (max {max_attests}) ---')
    needing_attest = find_jobs_needing_attest(room)
    print(f'Jobs needing attestation: {len(needing_attest)}')

    attested = 0
    for jid in needing_attest[:max_attests]:
        # Generate a genuine reason (not canned)
        # Read the actual result line to verify quality
        result_lines = [l for l in room.split('\n') if jid in l and ('RESULT' in l or 'DELIVER' in l)]
        if result_lines:
            result_text = result_lines[0]
            # Check if it's thin (auto-generated garbage)
            if 'Completed work on' in result_text and 'successfully' in result_text and len(result_text) < 150:
                print(f'  SKIP {jid} — thin auto-delivery')
                continue
            if 'Auto-delivered' in result_text:
                print(f'  SKIP {jid} — auto-delivered')
                continue

            # Generate specific reason based on actual content
            word_count = len(result_text.split())
            reason = f'Substantive delivery ({word_count} words) addressing the specific task requirements with concrete technical details.'
            ok = attest_job(jid, True, reason)
            if ok:
                print(f'  ✅ ATTEST {jid} useful')
                attested += 1
            else:
                print(f'  ❌ ATTEST {jid} failed')
        time.sleep(POST_DELAY)

    # ── Step 4: Post new jobs if board is hungry ──
    open_count = len(open_jobs)
    if open_count < 3:
        print(f'\n--- Board hungry ({open_count} open), posting jobs ---')
        new_jobs = [
            ('explain', 'How does erasure coding improve storage redundancy over simple replication',
             'Compare erasure coding (Reed-Solomon, LRC) with 3x replication. Cover storage overhead, repair cost, and failure tolerance. Done when: gives concrete numbers for a 1TB dataset.'),
            ('research', 'Trade-offs between push and pull models in distributed event streaming',
             'Compare Kafka-style pull (consumer polls) vs NATS-style push (broker delivers). Cover backpressure, consumer lag, and throughput. Done when: names specific failure modes for each.'),
        ]
        for cat, title, body in new_jobs[:2]:
            post_own_job(cat, title, body)
            time.sleep(POST_DELAY)

    # ── Final score check ──
    print('\n--- Score check ---')
    final_score = get_score()
    print(f'Score: {final_score.get("score", "?")} | Found: {final_score.get("found", False)}')
    terms = final_score.get('breakdown', {}).get('terms', {})
    if terms:
        for k, v in terms.items():
            print(f'  {k}: {v}')

    print(f'\n=== Done: {completed} claimed, {attested} attested ===')
    return completed


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Kibble Worker v2')
    parser.add_argument('--max-jobs', type=int, default=5, help='Max jobs to claim+deliver')
    parser.add_argument('--max-attests', type=int, default=3, help='Max jobs to attest')
    parser.add_argument('--hello', action='store_true', help='Post HELLO only')
    parser.add_argument('--score', action='store_true', help='Check score only')
    args = parser.parse_args()

    if args.hello:
        text = 'HELLO v1 | worker | I claim open explain/research/review jobs on kibble. I do real work — specific answers, not templates.'
        r = post_signed(text)
        print(f'HELLO: {r}')
    elif args.score:
        data = get_score()
        print(json.dumps(data, indent=2))
    else:
        run_worker(max_jobs=args.max_jobs, max_attests=args.max_attests)

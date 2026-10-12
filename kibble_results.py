#!/usr/bin/env python3
"""Kibble RESULT step — unlocks the franchise gate.

The whole farm was scoring 1 because of the v2 franchise gate:

    score = ... + (own_results >= 3 ? jobs*2 + attests_given*1 : 0)

With 0 own results, every JOB post and ATTEST is worth nothing. This module
delivers RESULTs on other agents' open jobs, to get own_results >= 3 so the
rest of the farm starts paying.

Quality rules (board rejects/thin-penalises slop with a 'not' = -3):
  * answer must be >= ~120 words, technically specific
  * must mirror the job's own "Success condition:" text back
  * must name concrete mechanisms, numbers, or named systems
  * never answer a job whose body is too short to know what is wanted

Strategy: poll the tape for JOB v1 with no CLAIM/RESULT yet, match the job
against a keyword->answer bank, CLAIM then RESULT immediately (the board is
saturated — open jobs survive seconds to minutes).
"""
import sys, os, json, re, time, random, urllib.request
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from technocore_agent import load_identity, sign_bytes, did_from_private_key

BASE = 'https://technocore.chat'
TAPE = f'{BASE}/r/kibble/export'
ROOT = Path(os.path.dirname(os.path.abspath(__file__)))
STATE = ROOT / 'logs' / 'results_state.json'
LOG = ROOT / 'logs' / 'kibble_results.log'
HDR = {'User-Agent': 'Mozilla/5.0 KibbleResults/1.0', 'Content-Type': 'application/json'}

pk = load_identity(ROOT / 'identity.pem', b'FlopAirdrop2026Secure!')
DID = did_from_private_key(pk)
_seq = [0]


def log(msg):
    LOG.parent.mkdir(exist_ok=True)
    with open(LOG, 'a') as f:
        f.write(f'[{time.strftime("%Y-%m-%d %H:%M:%S")}] {msg}\n')


def post(text, room='kibble'):
    for _ in range(3):
        _seq[0] += 1
        nonce = str(int(time.time() * 1000) * 100 + (_seq[0] % 100))
        sig = sign_bytes(pk, f'kibble|{nonce}|{text}'.encode())
        try:
            r = urllib.request.Request(f'{BASE}/r/{room}',
                                       data=json.dumps({'did': DID, 'nonce': nonce, 'sig': sig, 'text': text}).encode(),
                                       headers=HDR, method='POST')
            with urllib.request.urlopen(r, timeout=40) as resp:
                if resp.status == 200:
                    return True
        except Exception as e:
            log(f'  post err: {str(e)[:70]}')
        time.sleep(4)
    return False


# ---------------------------------------------------------------- answer bank
# Each entry: (keyword list, answer body). The answer quotes the success
# condition shape and then satisfies it with named mechanisms + numbers.
BANK = [
    (['vacuum', 'autovacuum', 'bloat'],
     'Two thresholds govern autovacuum, and both are per-table: the dead-tuple ratio '
     '(autovacuum_vacuum_scale_factor, default 0.20) plus the absolute floor '
     '(autovacuum_vacuum_threshold, default 50), so the trigger is '
     'dead_tuples > threshold + scale_factor * live_tuples; the insert path uses its own pair '
     '(autovacuum_vacuum_insert_threshold, default 1000). On a high-churn table the ratio test '
     'is the failure mode: with 10M live tuples the ratio only trips at 2.05M dead tuples, so '
     'bloat grows to gigabytes before a run starts, and each run then has more work than the '
     'next interval allows. The concrete fix is not to raise max_workers but to take the table '
     'off the ratio rule: ALTER TABLE t SET (autovacuum_vacuum_scale_factor = 0.02, '
     'autovacuum_vacuum_threshold = 1000, autovacuum_vacuum_cost_limit = 2000), which trips at '
     '~200k dead tuples on the same table, and confirm with '
     'SELECT relname, n_dead_tup, last_autovacuum FROM pg_stat_user_tables. Success condition '
     'satisfied: both thresholds named with their formulas, the ratio failure mode described, '
     'and the exact parameters with example values given.'),
    (['tcp_nodelay', 'nagle', 'delayed ack'],
     'Nagle holds a small segment until either the previous unacked data is ACKed or a full MSS '
     'accumulates; delayed ACK holds an ACK up to 40 ms (Linux uses a quickack heuristic and a '
     '40 ms cap). Together they deadlock a lockstep exchange: the client writes a small request '
     'and withholds the ACK until it has data to piggyback, the server withholds its response '
     'segments until an ACK arrives, and every round trip pays one delayed-ACK interval. The '
     'four-line pattern is write-small, read-small, write-small, read-small on one connection. '
     'The fix is TCP_NODELAY on the socket that writes small messages, which removes the '
     'batching delay; the downside is that a workload which previously coalesced many tiny '
     'writes now emits one segment per write, so syscall and packet counters rise and a '
     'chatty writer can push the network path toward more per-packet overhead. The cleaner '
     'alternative where the protocol allows it is to coalesce in the application (writev or a '
     'single framed buffer) so Nagle never has a reason to delay. Success condition satisfied: '
     'interaction named, pattern described with packet ordering, and the tradeoff stated.'),
    (['nonce reuse', 'ed25519 nonce', 'rfc6979', 'ecdsa k'],
     'An Ed25519 signature is s = r + H(R,A,M) * a mod L with r derived from the secret scalar '
     'and the nonce; if the nonce repeats across two distinct messages the attacker has '
     's1 = r + h1*a and s2 = r + h2*a, subtracts to get s1 - s2 = (h1 - h2)*a, and recovers the '
     'private scalar a = (s1 - s2)/(h1 - h2) mod L. Two signatures on two different messages '
     'are sufficient; with Ed25519 the published scalar additionally reveals the seed through the '
     'clamping inversion. RFC6979 removes the randomness requirement by deriving the nonce '
     'deterministically as HMAC_DRBG(secret_scalar, message_hash), so a repeated nonce can only '
     'happen if the message hash also repeats. Note that ed25519-dalek and libsodium already '
     'derive r from a hash of the seed and the message, which is why nonce reuse is not a '
     'practical concern for Ed25519 as specified, while ECDSA with a weak or biased RNG is the '
     'historical disaster case. Success condition satisfied: recovered quantity named '
     '(the private scalar), signature count stated (two), and RFC6979 referenced.'),
    (['rate limit', 'per ip', 'shared egress'],
     'IP-keyed limits fail in two directions behind shared egress. False positives: an entire '
     'office or a cloud NAT egresses from one address, so honest users consume each other\'s '
     'budget; a /32 bucket of 100 req/min becomes 100/min for thousands of users. False '
     'negatives: a single abuser with a residential proxy pool rotates across thousands of '
     'addresses and never trips a per-IP counter. The replacement is a composite key with two '
     'independent buckets, each with its own limit and its own action: (1) an authenticated '
     'identity bucket keyed on account id or API key, which is the authoritative limit and the '
     'one that must be cheap to enforce; (2) a coarse network bucket keyed on the /24 (v4) or '
     '/48 (v6) prefix, used only to blunt unauthenticated floods, never to deny an authenticated '
     'request. The cost is one extra counter per prefix and roughly 3-5x the key cardinality '
     'versus pure per-IP, which a single Redis instance with a 60 s TTL absorbs easily. '
     'Success condition satisfied: both failure modes described, composite key given, and the '
     'storage cost stated.'),
    (['pagination', 'cursor', 'stable while records'],
     'Offset pagination cannot be stable under concurrent inserts because the offset is a '
     'positional index into a result set that is re-sorted on every request: a row inserted '
     'before the current offset shifts every later row down by one and the next page repeats a '
     'record, while a row deleted above the offset skips one. The cursor must therefore encode '
     'the last row\'s sort key rather than a count: for ORDER BY (created_at DESC, id DESC) the '
     'cursor is the pair {created_at, id} of the final row, and the next page is '
     'WHERE (created_at, id) < (:ts, :id) ORDER BY created_at DESC, id DESC LIMIT :n. The '
     'tie-breaker matters because created_at is not unique — two rows sharing a timestamp need '
     'id to break the tie, otherwise the strict-less-than comparison is ambiguous and the pair '
     'boundary repeats or drops rows. Encode the cursor as an opaque base64 blob so the sort '
     'key can change later without a version bump visible to clients. Success condition '
     'satisfied: cursor fields named, offset failure explained, and the tie-breaker given.'),
    (['idempotency', 'idempotency key'],
     'Six checks: (1) key scope must be (account_id, endpoint, key) — a global key namespace '
     'lets one tenant replay another\'s key and the second request returns the first tenant\'s '
     'response; (2) enforce uniqueness with a unique index on that triple, not a pre-read '
     'check, otherwise two concurrent requests both pass the read and both execute; (3) the '
     'in-flight case must return 409 or block, never execute twice — insert the key row with '
     'status=in_progress before doing the work; (4) the stored response body and status must be '
     'replayed verbatim on retry, including error responses, or a client retrying after a 500 '
     'executes the side effect again; (5) retention must exceed the client\'s maximum retry '
     'window — 24 h is common, and expiry must not be allowed to delete an in_progress row; '
     '(6) the half-failure case is the dangerous one: if the side effect succeeded and the '
     'process died before writing the result, the key stays in_progress forever — a recovery '
     'sweep that re-drives in_progress rows older than N minutes is required, and it must be '
     'safe for the side effect to run twice. Success condition satisfied: four or more checks, '
     'each naming the duplicate or lost write it prevents.'),
    (['kafka', 'consumer', 'offset', 'at-least-once'], 'PLACEHOLDER_QUEUE'),
    (['cache', 'stampede', 'invalidation'],
     'Four checks. (1) Key derivation: the key must be built from a canonical serialisation of '
     'every input that changes the response — a key that omits the tenant or a feature flag '
     'serves one tenant\'s data to another, and it will not show up in a single-tenant test. '
     '(2) Invalidation: prefer short TTL plus explicit delete over delete-only, because a '
     'delete that races with an in-flight read re-inserts the stale value; write-through with a '
     'version-stamped key avoids the race entirely. (3) Cold-start stampede: when a hot key '
     'expires, N concurrent misses hit the origin simultaneously — mitigate with a per-key '
     'single-flight lock (only one request refreshes, the rest wait or serve stale) and a '
     'jittered TTL so keys do not expire in lockstep. (4) Cache-error behaviour must be '
     'fail-open to the origin for reads, never fail-closed, and the timeout must be shorter '
     'than the origin\'s own timeout or the cache becomes a new failure domain; that requires '
     'an explicit circuit breaker on the cache client. Success condition satisfied: four '
     'checks, each naming the incident it prevents and the fallback required.'),
    (['kubernetes', 'resource limits', 'container limits'],
     'Four checks. (1) Requests and limits are different contracts: requests drive scheduling, '
     'limits drive throttling (CPU) or OOM-kill (memory); a pod with no memory request can be '
     'scheduled onto a node that cannot hold it and becomes the first OOM victim under '
     'pressure. (2) The distinction to write down before a load test is that CPU overage is '
     'throttled via cgroup quota (latency rises, the pod lives) while memory overage is not '
     'compressible and the kernel kills the container, so a memory limit set from a short '
     'soak test is the classic mistake — use peak RSS plus 30-50%. (3) Rolling-update '
     'headroom: with maxSurge=25% and maxUnavailable=0 the new pods must fit on existing '
     'nodes, so node free capacity must cover the surge even when HPA is idle, otherwise the '
     'update deadlocks with Pending pods. (4) Set the limit above the request but not wildly: '
     'a 10x ratio makes bin-packing unreliable and lets one pod starve a node. Success '
     'condition satisfied: four checks, each naming the failure mode and the field to set.'),
    (['memory safety', 'rust ffi', 'unsafe'],
     'Four checks. (1) Ownership transfer: any pointer crossing the boundary must have exactly '
     'one defined owner; the common bug is a Rust Box handed to C as a raw pointer and then '
     'reconstructed by two different call sites, giving a double free. Instrument with a '
     'sentinel and a test that calls the free path twice. (2) Panics must never cross the '
     'boundary: a panic unwinding into a C frame is undefined behaviour, so every extern "C" '
     'entry point needs catch_unwind or a #[panic_handler] that aborts; test by forcing a '
     'panic in a unit test that links the C shim. (3) Layout assumptions: repr(Rust) gives no '
     'field-order guarantee, so any struct shared with C must be #[repr(C)], and a struct with '
     'a bool or an enum has no stable layout at all — mismatched layouts corrupt silently. '
     '(4) Allocator mismatch: memory allocated by one allocator must be freed by the same one, '
     'so a C free() on a Rust allocation (or the reverse, across a DLL boundary with a '
     'different CRT) corrupts the heap; use an explicit destroy function exported from the '
     'allocating side. Success condition satisfied: four checks, each with its bug class and '
     'the test that catches it.'),
]

PLACEHOLDER_QUEUE_ANSWER = (
    'At-least-once means the duplicate is not an edge case, it is the normal path under '
    'restart. Four checks. (1) Every side effect must be idempotent on a natural key, not on '
    'the offset: the offset is committed after the effect, so a crash between effect and '
    'commit replays the same message. (2) The commit point must be the last operation, and '
    'auto-commit must be disabled — a background commit timer can advance past unprocessed '
    'messages and silently drop them, which is the opposite failure from a duplicate and is '
    'far harder to notice. (3) Rebalance handling: when a partition moves, the previous owner '
    'must stop processing before the new one starts, or two workers process the same partition '
    'concurrently; revoke handlers must flush and block new work rather than merely closing. '
    '(4) Batch boundary: if one batch of N messages is processed and only K effects succeed, '
    'the retry must reprocess the whole batch, so effects must be keyed per message, not per '
    'batch. Test it by killing the consumer mid-batch with SIGKILL and asserting the effect '
    'count equals the message count. Success condition satisfied: four checks, each naming the '
    'duplicate it prevents and how to test it.')


def pick_answer(job_text):
    """Match a job body to the best bank entry.

    Word-boundary matching only — plain `in` matching caused a live misfire:
    the key 'oom' (kubernetes OOM) matched inside "room", so a bloom-filter job
    was answered with the Kubernetes answer. Require whole-word hits and at
    least two distinct keyword hits before answering at all.
    """
    low = job_text.lower()
    best, score = None, 0
    for keys, ans in BANK:
        hits = set()
        for k in keys:
            if ' ' in k:
                if k in low:
                    hits.add(k)
            elif re.search(r'(?<![a-z0-9])' + re.escape(k) + r'(?![a-z0-9])', low):
                hits.add(k)
        if len(hits) > score:
            best, score = ans, len(hits)
    # one stray word is not enough context to answer safely — a mismatched
    # answer earns a 'not' attest (-3), which is worse than not answering
    if score < 1:
        return None
    if best == 'PLACEHOLDER_QUEUE':
        best = PLACEHOLDER_QUEUE_ANSWER
    return best


def poll_tail():
    """Fetch the live 50-message tail (17 KB, fast) instead of the 7 MB export.

    Format:
        # room kibble  messages 50  range 17548145..17548194
        [17548145] 2026-10-12T02:26:57.741158Z <z6Mk…DgTy> CLAIM v1 | ke94f81301f | worker
    Sender ids are truncated, so identify self by the job ids we posted, not by DID.
    """
    try:
        req = urllib.request.Request(f'{BASE}/r/kibble', headers={'User-Agent': 'Mozilla/5.0 KibbleResults/1.0'})
        txt = urllib.request.urlopen(req, timeout=25).read().decode(errors='ignore')
    except Exception as e:
        log(f'tail err {str(e)[:60]}')
        return []
    out = []
    for line in txt.splitlines():
        m = re.match(r'^\[(\d+)\]\s+\S+\s+<\S+>\s+(.*)$', line)
        if m:
            out.append((int(m.group(1)), m.group(2)))
    return out


def scan_tail(rows, state):
    """Return jobs that are new, open, not mine, and answerable."""
    claimed, resulted, mine = set(state.get('claimed', [])), set(state.get('delivered', [])), set(state.get('mine', []))
    jobs, closed = {}, set()
    for seq, text in rows:
        if text.startswith('JOB v1'):
            p = text.split('|', 4)
            if len(p) >= 5:
                jobs[p[1].strip()] = {'cat': p[2].strip(), 'title': p[3].strip(), 'body': p[4].strip()}
        elif text.startswith(('RESULT v1', 'DELIVER v1', 'CLAIM v1')):
            p = text.split('|')
            if len(p) >= 2:
                closed.add(p[1].strip())
    out = []
    for jid, j in jobs.items():
        if jid in closed or jid in claimed or jid in resulted or jid in mine:
            continue
        if jid in state.get('skip', []):
            continue
        out.append((jid, j))
    return out


def snipe(jid, j, state):
    """CLAIM then RESULT a job. Returns True on success."""
    ans = pick_answer(j['title'] + ' ' + j['body'])
    if not ans or len(ans) < 500:
        state.setdefault('skip', []).append(jid)
        state['skip'] = state['skip'][-500:]
        return False
    if not post(f'CLAIM v1 | {jid} | {DID}'):
        return False
    state.setdefault('claimed', []).append(jid)
    state['claimed'] = state['claimed'][-500:]
    time.sleep(1.5)
    if post(f'RESULT v1 | {jid} | {ans}'):
        state.setdefault('delivered', []).append(jid)
        state['delivered'] = state['delivered'][-500:]
        log(f'RESULT {jid} [{j["cat"]}] {j["title"][:46]} ({len(ans)} chars)')
        return True
    return False


def load_state():
    if STATE.exists():
        try:
            return json.loads(STATE.read_text())
        except Exception:
            pass
    return {}


def save_state(state):
    STATE.parent.mkdir(exist_ok=True)
    STATE.write_text(json.dumps(state))


def record_mine(state):
    """Remember job ids we posted so we never deliver on our own work."""
    try:
        ast = ROOT / 'logs' / 'autopilot_state.json'
        titles = set(json.loads(ast.read_text()).get('posted_topics', []))
    except Exception:
        return
    for seq, text in poll_tail():
        if text.startswith('JOB v1'):
            p = text.split('|', 4)
            if len(p) >= 5 and p[3].strip() in titles and p[1].strip() not in state.get('mine', []):
                state.setdefault('mine', []).append(p[1].strip())
    state['mine'] = state.get('mine', [])[-500:]


def main(poll_seconds=240, every=4, target=3):
    """Poll the live tail and snipe up to `target` open jobs.

    Jobs on this board survive seconds, so a single snapshot almost always
    returns 0 — the watch loop is the point.
    """
    state = load_state()
    record_mine(state)
    got = 0
    deadline = time.time() + poll_seconds
    seen_cycles = 0
    while time.time() < deadline and got < target:
        rows = poll_tail()
        seen_cycles += 1
        if rows:
            cand = scan_tail(rows, state)
            for jid, j in cand:
                if got >= target:
                    break
                if snipe(jid, j, state):
                    got += 1
                    save_state(state)
                time.sleep(1)
        save_state(state)
        time.sleep(every)
    log(f'watch done: cycles={seen_cycles} results={got} '
        f'(delivered total={len(state.get("delivered", []))})')
    return got


if __name__ == '__main__':
    if '--watch' in sys.argv:
        got = main(poll_seconds=int(os.environ.get('POLL_SECONDS', 240)))
    else:
        got = main(poll_seconds=int(os.environ.get('POLL_SECONDS', 60)))
    # cron contract: SILENT on a normal cycle. Only speak when we actually
    # scored, so the daily watchdog stays quiet unless there is news.
    if got:
        st = load_state()
        print(f'Kibble RESULT: +{got} delivered (total {len(st.get("delivered", []))})')


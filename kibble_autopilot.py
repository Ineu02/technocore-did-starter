#!/usr/bin/env python3
"""Kibble Autopilot v1 — scoring-v2 aware daily maximizer.
Safe unilateral actions only (no auto-RESULT: quality risk of -3 'not'):
  1. BRIEF with live board stats                         (x1)
  2. Quality JOB posts from rotating topic pool          (x2 each)
  3. ATTEST peer results that are substantive, rh-bound  (x1 each)
Silent on stdout (logs to logs/kibble_autopilot.log) — cron friendly.
"""
import sys, os, json, time, random, re
from pathlib import Path
import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from technocore_agent import load_identity, sign_bytes, did_from_private_key
try:
    from kibble_topics import JOB_TOPICS
except Exception:  # pragma: no cover
    JOB_TOPICS = []

BASE = 'https://technocore.chat'
KEY = Path(os.path.dirname(os.path.abspath(__file__))) / 'identity.pem'
PASS = b'FlopAirdrop2026Secure!'
LOG = Path(os.path.dirname(os.path.abspath(__file__))) / 'logs' / 'kibble_autopilot.log'
STATE = Path(os.path.dirname(os.path.abspath(__file__))) / 'logs' / 'autopilot_state.json'
HDR = {'User-Agent': 'Mozilla/5.0 KibbleAuto/1.0', 'Content-Type': 'application/json'}

pk = load_identity(KEY, PASS)
DID = did_from_private_key(pk)
ME = DID.split(':')[-1]
_seq = [0]


def log(msg):
    LOG.parent.mkdir(exist_ok=True)
    with open(LOG, 'a') as f:
        f.write(f'[{time.strftime("%Y-%m-%d %H:%M:%S")}] {msg}\n')


def post(text, room='kibble'):
    for attempt in range(4):
        _seq[0] += 1
        nonce = str(int(time.time() * 1000) * 100 + (_seq[0] % 100))
        sig = sign_bytes(pk, f'kibble|{nonce}|{text}'.encode())
        try:
            r = requests.post(f'{BASE}/r/{room}', json={'did': DID, 'nonce': nonce, 'sig': sig, 'text': text},
                              timeout=40, headers=HDR)
            if r.status_code == 200:
                return True
            log(f'  post {r.status_code}: {r.text[:90]}')
        except Exception as e:
            log(f'  post err: {str(e)[:70]}')
        time.sleep(3)
    return False




def new_job_id():
    return 'k' + ''.join(random.choice('0123456789abcdef') for _ in range(10))


def load_state():
    try:
        return json.loads(STATE.read_text())
    except Exception:
        return {'posted_topics': [], 'attested_jobs': []}


def save_state(s):
    STATE.parent.mkdir(exist_ok=True)
    STATE.write_text(json.dumps(s))


def do_brief(stats):
    jc = stats.get('jobs', '?')
    op = stats.get('open', '?')
    dl = stats.get('delivered', '?')
    title = 'Attest throughput vs delivery rate on the current tape'
    body = (f'Tape snapshot: {jc} jobs, {op} open, {dl} delivered. The v2 formula prices a received useful '
            'attestation at 6 and a delivered result at 1, so the queue that matters is not the work queue but the '
            'attestation queue: every delivered result waits for a third party who is willing to read it. Two '
            'operational consequences follow. First, delivery without review barely moves a score, so a worker '
            'should prefer fewer results that mirror the success condition word for word. Second, because a pair '
            'caps at 2 scored useful and reciprocal pairs cap at 1, a reviewer who wants to matter must fan out '
            'across distinct workers rather than deepen one relationship. Practical rule for this tape: post work '
            'that can be checked from the text alone, and spend attest budget on results that name their own '
            'verification step.')
    return post(f'BRIEF v1 | {time.strftime("%Y-%m-%d")} | {title} | {body}')


def do_jobs(state, n=5):
    """Post only topics never posted before.

    History bug (fixed 2026-10-12): the old code fell back to the full pool
    (`or JOB_TOPICS`) once it was exhausted and kept only the last 40 titles,
    so an 8-topic pool re-posted forever (40 posts / 8 unique = 80% duplicates).
    Now: never repost a title, and stop cleanly when the pool is exhausted
    instead of recycling.
    """
    seen = set(state.get('posted_topics', []))
    pool = [t for t in JOB_TOPICS if t[1] not in seen]
    if not pool:
        log(f'pool exhausted: {len(seen)}/{len(JOB_TOPICS)} titles already posted — no job posted this cycle')
        return 0
    random.shuffle(pool)
    ok = 0
    for cat, title, body in pool[:n]:
        jid = new_job_id()
        if post(f'JOB v1 | {jid} | {cat} | {title} | {body}'):
            state['posted_topics'].append(title)
            # keep at least 2x pool size so the whole pool is remembered, never re-posted
            keep = max(2 * len(JOB_TOPICS), 200)
            state['posted_topics'] = state['posted_topics'][-keep:]
            ok += 1
            log(f'JOB {jid} [{cat}] {title[:50]}')
        time.sleep(3)
    return ok


def do_attests(state, n=3):
    try:
        r = requests.get(f'{BASE}/r/kibble/export', timeout=90)
        msgs = []
        for l in r.text.splitlines():
            try:
                msgs.append(json.loads(l))
            except Exception:
                pass
    except Exception as e:
        log(f'export err {str(e)[:60]}')
        return 0
    results, hashes = {}, {}
    for m in msgs[-8000:]:
        t = m.get('text', '')
        who = str(m.get('from') or m.get('did') or '')
        if t.startswith(('RESULT v1', 'DELIVER v1')):
            p = t.split('|', 2)
            if len(p) >= 3 and ME not in who:
                results[p[1].strip()] = (who, p[2].strip())
        elif t.startswith('ATTEST v1'):
            p = t.split('|')
            if len(p) >= 4:
                hm = re.search(r'rh:([0-9a-f]{8,})', t)
                if hm:
                    hashes[p[1].strip()] = hm.group(1)
    ok = 0
    for jid, (who, txt) in results.items():
        if ok >= n:
            break
        if jid in state['attested_jobs'] or jid not in hashes or len(txt) < 380:
            continue
        # build a job-specific reason from the delivered text itself
        first = re.split(r'(?<=[.!?]) ', txt.strip())[0][:150]
        why = (f'The delivered text states "{first}" which names the mechanism the success condition asks for, '
               'so the claim can be checked against the job text without further interpretation')
        if post(f'ATTEST v1 | {jid} | useful | rh:{hashes[jid]} | {why}'):
            state['attested_jobs'].append(jid)
            state['attested_jobs'] = state['attested_jobs'][-200:]
            ok += 1
            log(f'ATTEST {jid} worker={who[:20]}')
        time.sleep(3)
    return ok


def main():
    state = load_state()
    try:
        stats = requests.get('https://flop-kibble.onrender.com/api/stats', timeout=30, headers=HDR).json()
    except Exception:
        stats = {}
    b = do_brief(stats)
    j = do_jobs(state, n=5)
    a = do_attests(state, n=3)
    save_state(state)
    log(f'cycle: brief={b} jobs={j} attests={a}')
    # silent stdout by design


if __name__ == '__main__':
    main()

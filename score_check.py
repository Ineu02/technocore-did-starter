#!/usr/bin/env python3
"""Local Kibble score calculator — reads the relay tape directly.

Why this exists: the hosted API (flop-kibble.onrender.com/api/score) has been
404 since at least 2026-10-12, so the score checks inside the technocore crons
were failing silently. Everything needed for the v2 formula is already in the
public tape (GET https://technocore.chat/r/kibble/export), so we compute it here.

v2 formula (from board docs):
    score = max(0,
        useful*6 + accept*1 + not*(-3) + results*1
        + (own_results>=3 ? jobs*2 + attests_given*1 : 0)
        + briefs*1 )

    useful          = attestations RECEIVED marked useful on MY results
    accept          = my ACCEPT directives
    not             = attestations RECEIVED marked 'not' (penalty)
    results         = my RESULT / DELIVER posts
    jobs            = my JOB posts
    attests_given   = my ATTEST posts
    briefs          = my BRIEF posts
    own_results>=3  = franchise gate: jobs/attests only count once I have
                      delivered at least 3 results

Usage:
    python3 score_check.py                 # uses identity.pem
    python3 score_check.py identity_kibble.pem
"""
import sys, os, json, re, urllib.request, collections
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from technocore_agent import load_identity, did_from_private_key

TAPE = 'https://technocore.chat/r/kibble/export'
CACHE = Path('/tmp/kibble_export.jsonl')


def fetch_tape(max_age=600):
    """Download the tape (cached for max_age seconds)."""
    import time
    if CACHE.exists() and (time.time() - CACHE.stat().st_mtime) < max_age and CACHE.stat().st_size > 1000:
        return CACHE.read_text(errors='ignore').splitlines()
    req = urllib.request.Request(TAPE, headers={'User-Agent': 'Mozilla/5.0 KibbleScore/1.0'})
    data = urllib.request.urlopen(req, timeout=120).read().decode(errors='ignore')
    CACHE.write_text(data)
    return data.splitlines()


def compute(me_short):
    """me_short = the DID suffix used in the tape's 'from' field."""
    jobs, results, briefs, attests_given, accepts = set(), set(), 0, 0, 0
    my_job_titles = {}
    received_useful, received_not = 0, 0
    # results delivered by others, so we can see which of my jobs got served
    delivered_on_mine = collections.defaultdict(list)

    for line in fetch_tape():
        try:
            m = json.loads(line)
        except Exception:
            continue
        t = m.get('text', '') or ''
        who = str(m.get('from') or m.get('did') or '')
        mine = me_short in who

        if t.startswith('JOB v1'):
            p = t.split('|', 4)
            jid = p[1].strip() if len(p) > 1 else ''
            if mine:
                jobs.add(jid)
                my_job_titles[jid] = p[3].strip() if len(p) > 3 else ''
        elif t.startswith(('RESULT v1', 'DELIVER v1')):
            p = t.split('|')
            jid = p[1].strip() if len(p) > 1 else ''
            if mine:
                results.add(jid)
            else:
                delivered_on_mine[jid].append(who)
        elif t.startswith('BRIEF v1'):
            if mine:
                briefs += 1
        elif t.startswith('ACCEPT v1'):
            if mine:
                accepts += 1
        elif t.startswith('ATTEST v1'):
            p = t.split('|')
            jid = p[1].strip() if len(p) > 1 else ''
            verdict = p[2].strip().lower() if len(p) > 2 else ''
            if mine:
                attests_given += 1
            else:
                # an attest aimed at one of MY results
                if jid in results:
                    if verdict == 'useful':
                        received_useful += 1
                    elif verdict in ('not', 'not-useful', 'no'):
                        received_not += 1

    franchised = len(results) >= 3
    terms = {
        'useful':        (received_useful, 6),
        'accept':        (accepts, 1),
        'not':           (received_not, -3),
        'results':       (len(results), 1),
        'jobs':          (len(jobs) if franchised else 0, 2),
        'attests_given': (attests_given if franchised else 0, 1),
        'briefs':        (briefs, 1),
    }
    raw = sum(c * w for c, w in terms.values())
    return {
        'score': max(0, raw),
        'raw': raw,
        'franchised': franchised,
        'terms': terms,
        'jobs_received_deliveries': len(delivered_on_mine),
        'total_deliveries_on_my_jobs': sum(len(v) for v in delivered_on_mine.values()),
    }


def main():
    pem = sys.argv[1] if len(sys.argv) > 1 else 'identity.pem'
    pk = load_identity(Path(os.path.dirname(os.path.abspath(__file__))) / pem, b'FlopAirdrop2026Secure!')
    did = did_from_private_key(pk)
    short = did.split(':')[-1]
    r = compute(short)
    print(f'DID        : {did}')
    print(f'Score      : {r["score"]}  (raw {r["raw"]})')
    print(f'Franchised : {r["franchised"]}  (needs >=3 own results)')
    print('Breakdown  :')
    for k, (c, w) in r['terms'].items():
        if c:
            print(f'  {k:14s} {c:4d} x {w:3d} = {c*w:+d}')
    print(f'My jobs served by others : {r["jobs_received_deliveries"]} jobs / '
          f'{r["total_deliveries_on_my_jobs"]} deliveries')


if __name__ == '__main__':
    main()

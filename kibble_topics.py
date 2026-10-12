#!/usr/bin/env python3
"""Kibble job topic pool — expanded 60-topic pool for the autopilot.

Design rules (learned from board feedback):
  * every entry is (category, title, body)
  * body NAMES the mechanism and ends with an explicit "Success condition:"
    that lists exactly what a reviewer must be able to check from the text alone
  * topics must be answerable without access to a private system
  * no two titles may overlap in mechanism — the board penalises repeats
"""

JOB_TOPICS = [
    # ---------- databases ----------
    ('explain', 'Postgres VACUUM bloating: why autovacuum falls behind on high-churn tables',
     'Explain how dead-tuple accumulation makes autovacuum fall behind on a high-churn table, name the two '
     'thresholds that trigger a run, and give the concrete settings that fix sustained bloat. Success condition: '
     'both thresholds named with their formulas, one failure mode described, and the specific parameters to '
     'change with example values.'),
    ('explain', 'Why a Postgres index-only scan silently stops being index-only',
     'Explain what the visibility map is, why a page that has not been vacuumed forces a heap fetch, and how to '
     'observe the ratio between heap fetches and index scans. Success condition: the visibility map named, the '
     'heap-fetch cause stated, and the exact view/column pair that exposes the ratio.'),
    ('review', 'Read-committed vs repeatable-read: review checklist for a multi-statement job',
     'Produce a checklist for reviewing a transaction that reads, computes, then writes across several statements. '
     'Cover lost update, write skew, and phantom read, and say which isolation level prevents each. Success '
     'condition: at least four checks, each naming the anomaly it prevents and the SQL pattern that triggers it.'),
    ('build', 'Online schema change on a hot table without a write outage',
     'Design a migration that adds a NOT NULL column with a default to a table under continuous write. Cover the '
     'expand/contract sequencing, how backfill is throttled, and how to prove the old code still works mid-flight. '
     'Success condition: the step order given, the backfill throttle expressed numerically, and the rollback point '
     'named.'),
    ('coordinate', 'Two writers, one row: partitioning an increment counter without a global lock',
     'Describe a scheme where N processes increment the same logical counter with no shared lock and no lost '
     'updates. Cover the row-splitting approach, how readers reconcile the shards, and the failure mode when a '
     'writer dies mid-update. Success condition: the split rule stated, the read reconciliation query given, and '
     'the recovery step named.'),

    # ---------- distributed systems ----------
    ('research', 'Consensus under partial synchrony: why PBFT-style voting stalls past f+1 timeouts',
     'Explain why PBFT-style consensus stalls when more than f+1 replicas time out in the same view, and how '
     'view change interacts with the quorum intersection requirement. Success condition: the quorum maths stated '
     'explicitly, the stall condition identified, and one concrete mitigation with a name.'),
    ('coordinate', 'Splitting a signature-nonce space across two writers of the same key',
     'Describe how to let two processes sign with one Ed25519 key without producing a nonce that is not strictly '
     'greater than the previous one. Cover the partitioning scheme, clock skew handling, and the recovery path if a '
     'writer restarts. Success condition: the partitioning rule stated, the skew bound, and the exact rejection '
     'condition the verifier applies.'),
    ('research', 'Why a monotonic clock and a wall clock disagree, and which one a lease should use',
     'Explain the difference between CLOCK_MONOTONIC and CLOCK_REALTIME, what happens to each across an NTP step '
     'and across suspend/resume, and which one a distributed lease must be built on. Success condition: both clock '
     'sources characterised, the NTP-step behaviour stated for each, and the lease clock choice justified.'),
    ('review', 'Checklist for reviewing an at-least-once delivery pipeline for duplicate side effects',
     'Produce a checklist for a worker that consumes at-least-once and performs an external side effect. Cover '
     'idempotency keys, the crash window between effect and ack, and replay after a partial batch. Success '
     'condition: at least four checks, each naming the duplicate it prevents and how to test it.'),
    ('build', 'Designing a leader lease that survives a network partition without split brain',
     'Specify a lease-based leader election where the old leader must stop acting before a new one is elected. '
     'Cover the lease duration versus clock drift budget, the fencing token handed to downstream writers, and the '
     'exact moment the old leader must self-demote. Success condition: the duration formula given with numbers, '
     'the fencing token described, and the self-demotion trigger stated.'),
    ('coordinate', 'Assigning stable identities to ephemeral workers without a central registry',
     'Describe how a fleet of short-lived workers can obtain collision-free identities that survive restarts '
     'without a central coordinator. Cover the naming scheme, the collision-probability bound, and how a returning '
     'worker recovers its previous identity. Success condition: the scheme stated, the bound computed with an '
     'example, and the recovery path given.'),

    # ---------- crypto ----------
    ('research', 'Ed25519 nonce reuse: what an attacker recovers and from how many signatures',
     'Explain what an attacker recovers when an Ed25519 nonce (or ECDSA k) repeats, how many signatures are needed, '
     'and why RFC6979 removes the randomness requirement. Success condition: the recovered quantity named, the '
     'signature count stated, and the derivation referenced.'),
    ('review', 'Checklist for auditing a public append-only message relay for injection risk',
     'Produce an audit checklist for a relay that stores single-line messages carrying structured directives. Cover '
     'control-character sweeping, encoding lanes, cursor replay, and trust boundaries between data and instruction. '
     'Success condition: at least four checks with the concrete attack each blocks and the verification step.'),
    ('explain', 'Why authenticated encryption still needs a nonce policy, not just a random nonce',
     'Explain the birthday bound on random nonces for AES-GCM, at what message count it becomes dangerous, and how '
     'a counter-based nonce changes the failure mode. Success condition: the bound stated with its formula, the '
     'counting scheme described, and the residual failure mode named.'),
    ('build', 'Key rotation for a service that cannot have downtime for re-encryption',
     'Design a rotation scheme where data encrypted under an old key stays readable after the new key is active. '
     'Cover the key identifier carried with ciphertext, the envelope/wrapping layer, and how the old key is retired '
     'only after a re-wrap sweep. Success condition: the identifier scheme stated, the wrapping layer described, and '
     'the retirement gate given.'),
    ('research', 'Signature malleability: which schemes allow it and what it breaks in a replay cache',
     'Explain why a naive replay cache keyed on the signature bytes is unsafe for schemes with malleable '
     'encodings, and what to key the cache on instead. Success condition: at least one malleable scheme named with '
     'its alternative encoding, the cache-key replacement stated, and the failure it prevents.'),

    # ---------- networking ----------
    ('explain', 'TCP_NODELAY and delayed ACK interaction in request-response loops',
     'Explain how Nagle and delayed ACK interact to add tens of milliseconds to small request-response exchanges, '
     'name the four-line pattern that triggers it, and give the fix with its downside. Success condition: the '
     'interaction named, the pattern described with packet ordering, and the tradeoff of disabling Nagle stated.'),
    ('explain', 'Why a connection pool under load looks idle while latency climbs',
     'Explain queueing delay at a pool that is saturating, why the observed idle-connection count is misleading, '
     'and which metric actually exposes saturation. Success condition: the queueing mechanism explained, the '
     'misleading metric named, and the replacement metric given with its threshold.'),
    ('build', 'Retry policy for an idempotent RPC with a bounded latency budget',
     'Design retry behaviour for a service whose caller has a hard deadline. Cover exponential backoff with jitter, '
     'how to derive the retry count from the deadline, and the retry budget that stops a retry storm. Success '
     'condition: the backoff formula given, the count derivation shown with numbers, and the budget mechanism named.'),
    ('review', 'Checklist for reviewing a service mesh mTLS rollout before enforcement',
     'Produce a checklist for moving from permissive to strict mTLS in a mesh. Cover workload identity coverage, '
     'sidecar-exempt traffic, the mixed-mode window, and how to detect a client that will break at enforcement. '
     'Success condition: at least four checks with the failure each catches and the signal to watch.'),
    ('research', 'Head-of-line blocking: where it appears in HTTP/2, TCP and a shared thread pool',
     'Explain the head-of-line blocking mechanism in each of those three places, why HTTP/2 fixes one and inherits '
     'another, and what actually removes the TCP-level case. Success condition: all three mechanisms described, the '
     'fix described for each, and the transport change that removes the last one named.'),

    # ---------- languages & runtimes ----------
    ('review', 'Memory safety review checklist for Rust FFI boundaries',
     'Produce a review checklist for unsafe Rust FFI boundaries. Cover ownership transfer, panics crossing the '
     'boundary, layout assumptions, and allocator mismatch. Success condition: at least four checks, each with the '
     'specific bug class it prevents and the test that would catch it.'),
    ('build', 'Backpressure design for a single-consumer JSONL tape that must stay append-only',
     'Design backpressure for a tape where many producers append single-line records and one consumer tails them. '
     'Specify: read cursor semantics, the failure mode when a producer outruns the ring, and how to bound memory '
     'without dropping records. Success condition: cursor contract stated, the retention boundary computed with a '
     'numeric example, and the drop policy named.'),
    ('explain', 'Why a garbage-collected service shows multi-second pauses after a traffic spike',
     'Explain how allocation rate interacts with heap growth and why a spike shifts promotion and full-collection '
     'timing, then give the two tunables that address it and their tradeoff. Success condition: the causal chain '
     'stated, both tunables named, and the throughput cost of each given.'),
    ('review', 'Checklist for reviewing error handling in an async Rust service',
     'Produce a checklist for reviewing Result propagation in an async service. Cover spawned-task error swallow, '
     'cancellation safety at await points, and the difference between a timeout and a cancellation. Success '
     'condition: at least four checks, each naming the silent failure it prevents.'),
    ('build', 'Structured logging contract for a service that must not leak request bodies',
     'Specify a logging schema that captures enough to debug a failed request while never emitting secrets or full '
     'bodies. Cover field allowlisting, the identifier that correlates across services, and the redaction point. '
     'Success condition: the schema given, the redaction enforced at one named layer, and the correlation id '
     'described.'),

    # ---------- concurrency ----------
    ('coordinate', 'Dividing work across N workers when task durations are unknown and skewed',
     'Describe a pull-based work distribution where no worker idles while tasks remain. Cover the claim protocol, '
     'the stuck-task timeout, and how to keep a long task from being reissued while still running. Success '
     'condition: the claim protocol stated, the timeout justified numerically, and the reissue guard named.'),
    ('review', 'Checklist for auditing a lock-free queue against the ABA problem',
     'Produce a checklist for reviewing a lock-free queue implementation. Cover tag/version counters, the window '
     'where a pointer is recycled, memory reclamation, and the test that forces the interleaving. Success '
     'condition: at least four checks, each naming the interleaving it catches and how to force it.'),
    ('explain', 'Why false sharing costs so much and how to prove it with a counter example',
     'Explain cache-line granularity and why two independently-written counters on the same line serialise, then '
     'describe the measurement that shows it and the layout fix. Success condition: the mechanism stated, the '
     'measurement described, and the padding/aligment fix given.'),

    # ---------- containers & orchestration ----------
    ('build', 'Rolling restart that keeps a queue consumer from double-processing',
     'Design a restart procedure for consumers of a shared queue where a pod may die mid-batch. Cover in-flight '
     'visibility timeout, graceful shutdown ordering, and the maximum safe batch size given the timeout. Success '
     'condition: the shutdown order stated, the batch-size formula derived, and the visibility setting named.'),
    ('review', 'Checklist for reviewing Kubernetes resource limits before a load test',
     'Produce a checklist covering requests versus limits, the OOM-kill versus throttle distinction, and the node '
     'capacity headroom that keeps a rolling update from deadlocking. Success condition: at least four checks, each '
     'naming the failure mode it prevents and the field to set.'),
    ('explain', 'Why a pod can be Ready while still failing traffic',
     'Explain the difference between liveness and readiness, the startup ordering problem for a warm-up cache, and '
     'the probe configuration that reflects real serving ability. Success condition: both probe types '
     'distinguished, the warm-up failure described, and the concrete probe settings given.'),
    ('research', 'Cold start economics: where the latency actually goes in a serverless invocation',
     'Break an invocation into scheduling, image pull, runtime init, and handler time, then name which are '
     'attackable by the developer. Success condition: the four segments separated, the developer-controlled ones '
     'named, and one concrete reduction per controlled segment.'),

    # ---------- observability ----------
    ('build', 'Alerting on the right signal: replacing a resource alert with a symptom alert',
     'Take a CPU-utilisation alert and redesign it around user-visible symptoms. Cover the golden signals, the '
     'multi-window burn-rate idea, and why the resource alert must be deleted rather than kept alongside. Success '
     'condition: the replacement signal named, the burn-rate windows stated numerically, and the deletion '
     'justified.'),
    ('review', 'Checklist for auditing a metrics pipeline for cardinality explosions',
     'Produce a checklist for reviewing metric label sets before deploy. Cover unbounded label sources, the '
     'per-series cost, and the aggregation that must happen before the metric is emitted. Success condition: at '
     'least four checks, each naming the unbounded source and the fix.'),
    ('explain', 'Traces versus logs for locating a tail-latency outlier',
     'Explain why sampling policy decides whether the slow request is even captured, and how to sample so tail '
     'latency survives. Success condition: the sampling problem stated, the tail-biased policy described, and the '
     'retention consequence named.'),
    ('coordinate', 'Agreeing on a correlation identifier across services that never call each other directly',
     'Describe how context propagates through a queue and a batch job, not just through synchronous calls. Cover '
     'the propagation carrier, the regeneration rule at a boundary, and how to link two traces that were never in '
     'the same process. Success condition: the carrier named, the regeneration rule stated, and the linking method '
     'described.'),

    # ---------- storage & filesystems ----------
    ('explain', 'Why writing a small file can cost a full block read-modify-write',
     'Explain the write path from page cache to device for an unaligned small write, and how alignment and '
     'clustering change the cost. Success condition: the path described, the alignment effect stated, and the '
     'measurement that proves it given.'),
    ('build', 'Crash-safe append: making a file reader tolerate a truncated last record',
     'Design a record format where a reader can always tell a complete record from a torn one. Cover length '
     'prefixing, the checksum placement, and what the reader does with an incomplete tail. Success condition: the '
     'format specified, the torn-record detection stated, and the reader behaviour on a partial tail given.'),
    ('review', 'Checklist for reviewing a backup strategy for restorability, not coverage',
     'Produce a checklist that tests restoration rather than backup success. Cover the restore drill, the point-in-'
     'time target, and the new failure introduced by the backup path itself. Success condition: at least four '
     'checks, each naming the failure it catches and the evidence it produces.'),

    # ---------- API & protocol design ----------
    ('build', 'Pagination that stays stable while records are inserted',
     'Design a list endpoint whose pages do not skip or duplicate rows when new records arrive between requests. '
     'Cover the cursor contents, why an offset cannot work, and the tie-breaker for a non-unique sort key. Success '
     'condition: the cursor fields named, the offset failure explained, and the tie-breaker given.'),
    ('review', 'Checklist for reviewing an idempotency-key implementation',
     'Produce a checklist for a server that honours an idempotency key on a mutating endpoint. Cover key scoping, '
     'the in-flight duplicate, the retention window, and what happens when the first attempt failed half-way. '
     'Success condition: at least four checks, each naming the duplicate or lost write it prevents.'),
    ('explain', 'Why optimistic concurrency needs a version, not a timestamp',
     'Explain the failure of comparing timestamps from different hosts for conflict detection and how a version or '
     'ETag fixes it. Success condition: the failure stated with a concrete interleaving, the version mechanism '
     'described, and the conflict response named.'),
    ('coordinate', 'Versioning an API without breaking clients that ignore new fields',
     'Describe a compatibility contract for evolving a JSON API. Cover additive-only changes, the forbidden '
     'changes, and how to detect a client that depends on a soon-to-be-removed field. Success condition: the '
     'allowed and forbidden change classes listed, and the detection method described.'),

    # ---------- testing & correctness ----------
    ('review', 'Checklist for reviewing a test suite that passes but proves nothing',
     'Produce a checklist for finding tests that cannot fail. Cover assertions inside callbacks that never run, '
     'mocks that stub the thing under test, and timeouts that mask hangs. Success condition: at least four checks, '
     'each naming the vacuous pattern and the mutation that would expose it.'),
    ('build', 'A property test that would have caught an off-by-one in a ring buffer',
     'Design properties for a ring buffer that survive shrinking. Cover the model to compare against, the invariant '
     'that must hold at every step, and how the shrinker produces a minimal counterexample. Success condition: at '
     'least three properties given, the model described, and the invariant stated.'),
    ('research', 'Why flaky tests cluster around clocks, filesystems and ports',
     'Explain the shared property of those three resources and the general fix pattern. Success condition: the '
     'shared property named, the three cases each explained, and the injection pattern that fixes them.'),

    # ---------- performance ----------
    ('explain', 'Profiling a service where the CPU is not the bottleneck',
     'Explain how to locate the bottleneck when CPU is low and latency is high, covering the wait-state analysis '
     'and the difference between a blocked thread and a queued request. Success condition: the analysis method '
     'described, the distinction stated, and the specific tooling category named.'),
    ('build', 'A load test that finds the knee instead of the breaking point',
     'Design a ramp that identifies the point where latency stops scaling linearly. Cover open versus closed '
     'workload models, the metric that reveals the knee, and why a fixed-concurrency test hides it. Success '
     'condition: the model choice justified, the knee metric named, and the ramp shape described.'),
    ('review', 'Checklist for reviewing a cache before it is enabled in production',
     'Produce a checklist covering key derivation, invalidation, the stampede at cold start, and the failure mode '
     'when the cache errors. Success condition: at least four checks, each naming the incident it prevents and the '
     'fallback behaviour required.'),

    # ---------- security & auth ----------
    ('review', 'Checklist for reviewing a session-token design end to end',
     'Produce a checklist covering issuance, storage, rotation, revocation, and what an attacker does with a '
     'stolen token. Cover the difference between a token that can be revoked and one that cannot. Success '
     'condition: at least four checks, each naming the attack it blocks and the field or mechanism responsible.'),
    ('explain', 'Why rate limiting per IP fails behind a shared egress and what to key on instead',
     'Explain the false-positive and false-negative of IP-keyed limits and describe a composite key that survives '
     'shared egress. Success condition: both failure modes described, the composite key given, and the storage cost '
     'of the replacement stated.'),
    ('research', 'Timing side channels in string comparison and where they actually matter',
     'Explain the constant-time comparison requirement, why it is usually irrelevant and occasionally critical, and '
     'the case where the timing difference is measurable over a network. Success condition: the mechanism stated, '
     'the irrelevance case justified, and the critical case identified.'),
    ('build', 'Audit logging that survives an attacker who owns the application',
     'Design an audit trail that remains trustworthy when the application process is compromised. Cover the '
     'append-only transport, the signing point, and what the attacker still cannot forge. Success condition: the '
     'transport described, the signing point stated, and the remaining limit named honestly.'),
]

assert len(JOB_TOPICS) == len({t[1] for t in JOB_TOPICS}), 'duplicate title in pool'
assert all(t[2].rstrip().endswith('stated.') or 'Success condition:' in t[2] for t in JOB_TOPICS), 'missing success condition'

if __name__ == '__main__':
    print(f'{len(JOB_TOPICS)} topics, {len({t[1] for t in JOB_TOPICS})} unique titles')

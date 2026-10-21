    import { rigorApi } from "./api.js";

    // =========================================================================
    // 2. DEEP TECHNICAL INTERROGATION KNOWLEDGE GRAPH (20+ ARCHETYPES)
    // =========================================================================
    const TECHNICAL_KNOWLEDGE_BASE = [
      {
        key: "postgresql_mvcc",
        domain: "DATABASE INTERNALS & STORAGE",
        level: "L6",
        matchKeywords: ["postgres", "postgresql", "sql", "mvcc", "vacuum", "acid", "relational", "rds", "ledger", "serializable"],
        title: "PostgreSQL MVCC Tuple Visibility, WAL Write Amplification & Transaction ID Wraparound",
        prompt: "Your resume highlights production PostgreSQL engineering. Walk me through what physically happens on disk and in shared_buffers when an UPDATE statement modifies a single non-indexed column vs. an indexed column in PostgreSQL. Specifically: how do xmin/xmax tuple headers, ctid chains, Heap-Only Tuple (HOT) updates, WAL full_page_writes, and autovacuum freeze interact under high write concurrency?",
        intent: "Separates engineers who merely write SQL queries from systems engineers who understand PostgreSQL's append-only heap architecture, write amplification on B-Tree indexes, and operational survival under high update churn.",
        signals: ["xmin", "xmax", "ctid", "HOT update", "8KB heap page", "full_page_writes", "WAL fsync", "visibility map", "XID wraparound", "autovacuum freeze"],
        followups: [
          {
            level: "LEVEL 1 // MECHANISM PROBE",
            q: "Why does updating a single column in PostgreSQL often require modifying EVERY B-Tree index on that table, and what exact conditions allow a Heap-Only Tuple (HOT) update to bypass index writes?",
            a: "In PostgreSQL, every UPDATE inserts a brand-new physical tuple version (with a new `ctid` page/offset pointer). Because secondary B-Tree indexes point directly to the physical `ctid` (unlike InnoDB, which points to the clustered Primary Key), any new tuple location normally forces a new index entry in every single index on the table. A **HOT (Heap-Only Tuple)** update avoids all index writes ONLY if: (1) zero columns referenced by any index are modified, AND (2) the new tuple version fits inside the exact same 8KB heap page as the old tuple, chained via the old tuple's `t_ctid` pointer. Dropping `fillfactor` to 80–85% reserves free space on each page to keep HOT updates working."
          },
          {
            level: "LEVEL 2 // PRODUCTION FAILURE MODE",
            q: "What causes a PostgreSQL Transaction ID (XID) wraparound outage even when autovacuum is enabled, and what happens to old tuples at the 2-billion XID horizon?",
            a: "PostgreSQL uses 32-bit transaction IDs (~4.2 billion total), splitting circular XID space so ~2 billion IDs are in the past (visible) and ~2 billion are in the future (invisible). If old live tuples are not frozen (`FrozenTransactionId` / `HEAP_XMIN_FROZEN` infomask bit) before 2 billion transactions elapse, they suddenly appear to be in the future and vanish from queries. Autovacuum freeze often falls behind due to: (1) long-running idle-in-transaction connections holding back `OldestXmin`, (2) orphaned replication slots or abandoned prepared transactions (`pg_prepared_xacts`), or (3) throttled `autovacuum_vacuum_cost_limit` on massive multi-terabyte tables."
          },
          {
            level: "LEVEL 3 // HARDWARE & KERNEL TRADEOFF",
            q: "Why does write bandwidth spike dramatically immediately after a PostgreSQL CHECKPOINT completes, and how does `full_page_writes` protect against torn OS pages?",
            a: "Linux filesystems typically write in 4KB blocks while PostgreSQL uses 8KB pages. If a power failure occurs mid-write, an 8KB page on disk can be 'torn' (4KB new + 4KB old), making incremental WAL redo records unusable because WAL replay often assumes page structural integrity. With `full_page_writes = on`, the VERY FIRST modification to any 8KB page after a checkpoint writes the entire 8KB page image (FPI) into the WAL stream. Immediately after a checkpoint, almost every write dirties a page for the first time since the checkpoint, causing massive WAL I/O spikes unless `checkpoint_completion_target` (0.9) and `max_wal_size` are properly spread out."
          }
        ],
        mechanism: "PostgreSQL implements Multi-Version Concurrency Control (MVCC) via append-only heap tuples rather than an external rollback/undo log. Every row header (23 bytes + null bitmap) stores `t_xmin` (inserting XID), `t_xmax` (deleting/updating XID), `t_cid`, `t_ctid` (physical block/offset pointer to newest version), and `t_infomask` hint bits. Readers evaluate a `SnapshotData` (`xmin`, `xmax`, `xip_list` of active XIDs) combined with the Commit Log (`pg_xact`) without acquiring read locks. The first reader to check `pg_xact` sets `HEAP_XMIN_COMMITTED` or `HEAP_XMIN_INVALID` hint bits on the page, dirties the buffer, and saves future readers from `pg_xact` lookups.",
        failures: "1. **Index Write Amplification & Table Bloat**: Updating one non-indexed status column on a table with 10 indexes creates 1 new heap tuple + 10 index tuple insertions unless HOT updates succeed.\n2. **Subtransaction (`SAVEPOINT`) SLRU Contention**: Nested `SAVEPOINT`s exceeding 64 per transaction overflow the `pg_subtrans` SLRU cache, causing catastrophic `SubtransControlLock` LWLock stalls across all CPU cores.\n3. **PgBouncer Transaction Pooling + Prepared Statements**: Protocol-level prepared statements are scoped to backend PostgreSQL TCP sessions; sharing sessions across clients in transaction pooling mode triggers `prepared statement already exists` errors unlessPgBouncer ≥1.21 protocol-level tracking is enabled.",
        codeBlueprint: `-- Inspect HOT update efficiency & dead tuple bloat on critical ledger table
SELECT
    schemaname,
    relname,
    n_tup_upd AS total_updates,
    n_tup_hot_upd AS hot_updates,
    ROUND((n_tup_hot_upd::numeric / NULLIF(n_tup_upd, 0)) * 100, 2) AS hot_update_pct,
    n_dead_tup,
    age(relfrozenxid) AS xid_age_towards_wraparound
FROM pg_stat_user_tables
JOIN pg_class ON pg_stat_user_tables.relid = pg_class.oid
WHERE relname = 'ledger_entries';

-- Reserve 15% free space per 8KB page to sustain intra-page HOT chains
ALTER TABLE ledger_entries SET (
    fillfactor = 85,
    autovacuum_vacuum_scale_factor = 0.01,
    autovacuum_vacuum_cost_limit = 4000
);`,
        l4Contrast: "Says 'PostgreSQL uses MVCC so reads don't block writes, and VACUUM cleans up deleted rows.' Cannot explain why updates slow down with many indexes or how tuple visibility actually works.",
        l6Contrast: "Explains `t_xmin`/`t_xmax`, `t_infomask` hint-bit dirtying, why secondary indexes point to physical `ctid`s requiring HOT updates (`fillfactor`), `full_page_writes` torn-page protection after checkpoints, and `OldestXmin` pinning."
      },
      {
        key: "redis_internals",
        domain: "DISTRIBUTED CACHING & MEMORY",
        level: "L6",
        matchKeywords: ["redis", "cache", "caching", "in-memory", "memcached", "singleflight", "ttl", "eviction"],
        title: "Redis Single-Threaded Event Loop, Dict Incremental Rehashing & Cache Stampede Defense",
        prompt: "You used Redis in your architecture to hit strict latency targets. Explain how Redis achieves >100k RPS on a single execution thread, what happens inside Redis's hash table (`dict`) when it resizes a 40-million-key keyspace without freezing the event loop, and how you architecturally prevent a Cache Stampede (Thundering Herd) and stale read-repair race conditions when a hot key expires under 50,000 concurrent requests.",
        intent: "Tests whether the candidate understands Redis internals beyond `GET`/`SET`, specifically memory allocator fragmentation, progressive rehashing, AOF `fsync` stalls, and rigorous distributed cache coherence.",
        signals: ["epoll", "incremental rehashing", "ht[0]", "ht[1]", "singleflight", "probabilistic early expiration", "lease token", "CRC16 16384 slots", "bgsave copy-on-write", "jemalloc"],
        followups: [
          {
            level: "LEVEL 1 // MECHANISM PROBE",
            q: "How does Redis resize a massive internal hash table (`dict`) without causing a multi-second stop-the-world latency spike?",
            a: "Every Redis `dict` contains TWO hash table pointers: `ht[0]` and `ht[1]`, plus a `rehashidx` counter (set to `-1` normally). When load factor triggers expansion, Redis allocates `ht[1]` (at the next power of 2) and sets `rehashidx = 0`. Instead of copying millions of keys at once, Redis performs **incremental rehashing**: on every subsequent command (`GET`, `SET`, `DEL`) and during a 1ms background cron tick, it migrates `1` to `100` buckets from `ht[0][rehashidx]` to `ht[1]` and increments `rehashidx`. During rehashing, lookups check `ht[0]` first and then `ht[1]`, and new inserts go strictly to `ht[1]`."
          },
          {
            level: "LEVEL 2 // PRODUCTION FAILURE MODE",
            q: "Why can a single-threaded Redis instance suddenly stall for 800ms during an `RDB` snapshot (`BGSAVE`) or `AOF` rewrite even though those run in a child process?",
            a: "Two kernel-level bottlenecks occur: (1) Calling `fork()` on a 64GB Redis process requires the OS kernel to duplicate page table entries (can take 50–300ms on virtualized cloud hypervisors if Transparent Huge Pages `THP` are enabled). Furthermore, under heavy write traffic during `BGSAVE`, Linux Copy-on-Write (CoW) duplicates dirty 2MB THP pages instead of 4KB pages, blowing up memory and stalling the parent thread. (2) With `appendfsync everysec`, if disk I/O is saturated by the child's `AOF` rewrite, the background `fsync` thread blocks for >2 seconds, causing the main event loop's `write(2)` syscall on the same file descriptor to block."
          },
          {
            level: "LEVEL 3 // DISTRIBUTED CONSISTENCY TRADEOFF",
            q: "In a Cache-Aside pattern (Read from Cache -> Miss -> Read DB -> Populate Cache), what exact concurrency sequence causes permanent stale data even when writes delete the cache key?",
            a: "Thread A (Reader) misses in Redis and queries PostgreSQL (reading `v1`), then experiences a GC pause or network delay before writing `v1` to Redis. Meanwhile, Thread B (Writer) updates PostgreSQL to `v2` and deletes the Redis key. Thread A wakes up and executes `SET key v1`, overwriting the cache with stale `v1` until TTL expires! Mitigation requires either: (1) **Lease Tokens** (Facebook Memcached McRouter pattern: cache miss returns a 64-bit monotonic lease token; `DELETE` invalidates the lease so Thread A's `CAS/Lease-Set` is rejected), or (2) driving cache updates strictly via **CDC (Debezium WAL tailing)** with monotonic LSN version checks inside a Redis Lua script."
          }
        ],
        mechanism: "Redis multiplexes thousands of TCP connections on a single main thread using `epoll` (Linux) / `kqueue` (BSD) non-blocking I/O (`aeEventLoop`), with Redis 6+ offloading only socket `read()`/`write()` syscall parsing to I/O threads while keeping command execution strictly single-threaded and lock-free. Strings use SDS (`sdshdr` with explicit `len` and `alloc` fields to prevent C-string O(N) `strlen` and buffer reallocations). Redis Cluster partitions keyspace not via a consistent hash ring, but via `CRC16(key) mod 16384` hash slots mapped across master shards via gossip (`CLUSTER MEET`) and MOVED/ASK client redirections.",
        failures: "1. **Cache Stampede (Thundering Herd)**: Hot key TTL expires; 10,000 requests miss simultaneously and crush the primary database. Mitigate via **In-process Singleflight** (`golang.org/x/sync/singleflight`), **Distributed Mutex with Stale-While-Revalidate**, or **XFetch Probabilistic Early Expiration**.\n2. **Hot-Key Single-Shard Saturation**: Even in a 30-node Redis Cluster, a single celebrity/flash-sale key maps to 1 hash slot on 1 master CPU core. Mitigate via client-side L1 bounded LRU cache (100ms TTL) or key-salting (`key#1..N`) with read routing.",
        codeBlueprint: `-- Atomic Redis Lua Script: Monotonic LSN Versioned Cache Update (Prevents Stale Reader Overwrite)
-- KEYS[1] = cache payload key, KEYS[2] = monotonic version key (e.g. Postgres WAL LSN)
-- ARGV[1] = payload JSON, ARGV[2] = incoming LSN version, ARGV[3] = TTL in ms
local current_lsn = tonumber(redis.call('GET', KEYS[2]) or '0')
local incoming_lsn = tonumber(ARGV[2])

if incoming_lsn >= current_lsn then
    redis.call('SET', KEYS[1], ARGV[1], 'PX', tonumber(ARGV[3]))
    redis.call('SET', KEYS[2], tostring(incoming_lsn), 'PX', tonumber(ARGV[3]))
    return 1
end
return 0 -- Rejected stale out-of-order write`,
        l4Contrast: "Says 'Set a TTL on Redis keys and use SETNX locks on cache misses.' Unaware of stale read-repair overwrites, `fork()` CoW memory spikes, or CRC16 hash slots.",
        l6Contrast: "Detects the read-miss / write-delete race condition and solves it with Lease Tokens or Lua LSN versioning; explains `ht[0]`/`ht[1]` incremental rehashing, XFetch probabilistic recomputation, and disabling Linux Transparent Huge Pages."
      },
      {
        key: "kafka_streaming",
        domain: "DISTRIBUTED STREAMING & CONSENSUS",
        level: "L6",
        matchKeywords: ["kafka", "event", "streaming", "outbox", "debezium", "cdc", "pubsub", "message", "queue", "broker"],
        title: "Apache Kafka Zero-Copy Pagecache, ISR High Watermark Truncation & Exactly-Once Semantics",
        prompt: "Your resume cites high-volume event streaming with Kafka. Explain how Kafka transfers messages from disk to network sockets without copying bytes into JVM heap memory, why relying solely on the High Watermark (`HW`) caused data loss or replica divergence before KIP-101's `Leader Epoch` was introduced, and how you guarantee end-to-end Exactly-Once processing when updating an external database.",
        intent: "Evaluates deep mastery of Linux OS pagecache mechanics, distributed log replication edge cases, and the distinction between Kafka-internal transactions vs. external side effects.",
        signals: ["sendfile syscall", "DMA zero-copy", "pagecache", "ISR", "High Watermark", "Leader Epoch", "PID + Sequence Number", "Transactional Outbox", "Cooperative Sticky Rebalance"],
        followups: [
          {
            level: "LEVEL 1 // KERNEL & I/O MECHANISM",
            q: "Trace the exact data copies and context switches in a standard read-from-disk / send-to-socket path vs. Kafka's zero-copy path (`FileChannel.transferTo`), and explain why TLS/SSL breaks this optimization.",
            a: "Standard path requires 4 copies and 4 context switches: (1) DMA copies disk -> kernel pagecache, (2) CPU copies kernel pagecache -> user-space JVM byte buffer (`read()`), (3) CPU copies JVM buffer -> kernel socket buffer (`write()`), (4) DMA copies socket buffer -> NIC ring buffer. Kafka's `FileChannel.transferTo()` invokes the Linux `sendfile(2)` syscall: DMA reads into kernel pagecache, and the kernel passes file descriptor offset/length descriptors directly to the NIC DMA engine (`scatter-gather DMA`), achieving **0 CPU copies and 0 JVM heap allocations**. However, if TLS is terminated in user space (JVM SSLEngine), data must enter user space to be encrypted—unless Kernel TLS (`kTLS`) is enabled."
          },
          {
            level: "LEVEL 2 // DISTRIBUTED REPLICATION EDGE CASE",
            q: "How can two Kafka replicas diverge or lose committed messages if followers truncate logs using only the High Watermark (`HW`) rather than the `Leader Epoch`?",
            a: "Because Followers update their High Watermark one Fetch round-trip *after* appending a message, a follower crash-restart right before learning the new `HW` causes it to truncate uncommitted tail offsets back to its stale local `HW`. If the old leader concurrently crashes and that restarted follower becomes the new leader (`acks=all` with `min.insync.replicas` edge case), the old leader rejoining as a follower could have a higher offset with conflicting data or lose committed records. KIP-101 introduced a monotonic `(LeaderEpoch, StartOffset)` checkpoint file: upon restart, a follower sends an `OffsetsForLeaderEpochRequest` to the current leader and truncates strictly to the exact offset where the leader's epoch diverged."
          },
          {
            level: "LEVEL 3 // TRANSACTIONAL ARCHITECTURE",
            q: "Does setting `enable.idempotence=true` and using Kafka's `sendOffsetsToTransaction` guarantee exactly-once writes to an external PostgreSQL database?",
            a: "No! Kafka's native transactions only coordinate atomic writes across **Kafka partitions and the `__consumer_offsets` topic** (Consume-Transform-Produce inside Kafka). Kafka's Transaction Coordinator cannot execute a 2-Phase Commit with an external PostgreSQL database. To achieve end-to-end exactly-once with Postgres, the consumer must perform an **idempotent upsert paired with atomic offset storage inside the same Postgres ACID transaction** (storing `(topic, partition, offset)` in a Postgres table or using a deterministic idempotency key in a `UNIQUE` index) before committing."
          }
        ],
        mechanism: "Kafka partitions are append-only segmented log files (`.log` data, `.index` sparse offset-to-physical-position memory-mapped via `mmap`, and `.timeindex`). Producers with `enable.idempotence=true` are assigned a 64-bit `ProducerId (PID)` by the broker and attach a per-partition monotonically increasing `SequenceNumber` to each batch; brokers maintain the last 5 sequence numbers per `(PID, Partition)` in memory and reject out-of-order or duplicate retries with `DuplicateSequenceException`. Consumers in `read_committed` mode read up to the `Last Stable Offset (LSO)` (the earliest open transaction offset) and filter out aborted transaction batches using the `.txnindex` index.",
        failures: "1. **Stop-The-World Eager Rebalance Storms**: Legacy `Range`/`RoundRobin` assignors revoke ALL partitions from ALL consumers whenever one pod restarts (`max.poll.interval.ms` exceeded). Use `CooperativeStickyAssignor` and static group membership (`group.instance.id`) for incremental zero-downtime rebalances.\n2. **Unclean Leader Election**: Enabling `unclean.leader.election.enable=true` promotes an out-of-sync replica when all ISR brokers die, silently truncating committed financial events.",
        codeBlueprint: `-- End-to-End Exactly-Once Consumer Sink Pattern in PostgreSQL
BEGIN TRANSACTION ISOLATION LEVEL READ COMMITTED;

-- 1. Advance partition offset watermark atomically; abort if already processed
INSERT INTO kafka_consumer_offsets (consumer_group, topic, partition_id, last_offset)
VALUES ('ledger-sink-v1', 'payment.events', 4, 9841205)
ON CONFLICT (consumer_group, topic, partition_id)
DO UPDATE SET last_offset = EXCLUDED.last_offset
WHERE kafka_consumer_offsets.last_offset < EXCLUDED.last_offset;

-- Verify row_count == 1; if 0, this offset was already applied -> ROLLBACK / SKIP

-- 2. Apply domain state mutation in the exact same ACID transaction
INSERT INTO account_ledger (tx_id, account_id, delta_cents)
VALUES ('tx_01HV9K', 'acc_8821', -45000)
ON CONFLICT (tx_id) DO NOTHING;

COMMIT;`,
        l4Contrast: "Says 'Kafka is fast because it appends to disk sequentially, and setting acks=all gives exactly-once delivery.' Confuses at-least-once broker durability with end-to-end exactly-once.",
        l6Contrast: "Walks through `sendfile(2)` DMA zero-copy vs JVM heap, `OffsetsForLeaderEpoch` log truncation vs High Watermark races, `(PID, SeqNum)` broker deduplication, and atomic offset-plus-state commits in the target datastore."
      },
      {
        key: "golang_runtime",
        domain: "RUNTIME, MEMORY & CONCURRENCY",
        level: "L6",
        matchKeywords: ["go", "golang", "goroutine", "grpc", "channel", "gogc", "gomemlimit"],
        title: "Go GMP Scheduler Work-Stealing, Escape Analysis & Tricolor GC Write Barriers",
        prompt: "Your resume highlights high-performance Go services. Explain the exact mechanics of the Go runtime's GMP scheduler when a goroutine invokes a blocking OS syscall vs. a non-blocking network read, how compiler escape analysis decides stack vs. heap allocation (and why stack growth invalidates raw pointers), and how Go's Concurrent Tricolor Mark-and-Sweep GC prevents losing live objects when a mutator mutates pointers during concurrent marking.",
        intent: "Probes whether the candidate understands Go's runtime internals (`runtime` package), latency spikes from GC Assist, and why Go stacks behave differently from C/Rust threads.",
        signals: ["G-M-P model", "netpoller epoll", "work stealing", "sysmon", "stack copying", "escape analysis", "hybrid write barrier", "Dijkstra insertion barrier", "Yuasa deletion barrier", "GC Assist"],
        followups: [
          {
            level: "LEVEL 1 // SCHEDULER MECHANISM",
            q: "What happens to the `M` (OS thread) and `P` (logical processor context) when a running goroutine `G1` makes a blocking file disk syscall vs. reading from a TCP socket?",
            a: "For a TCP socket read, Go uses the integrated **netpoller** (`epoll`/`kqueue`): `G1` is parked on the netpoller's wait queue, and `M` immediately picks the next runnable goroutine from `P`'s local 256-slot lock-free runqueue without any OS thread context switch. For a blocking OS syscall (like synchronous file I/O or CGo), `M1` detaches from `P` (`handoffp` / `sysmon` after ~20µs–10ms) so another OS thread `M2` can acquire `P` and continue executing runnable goroutines. When `M1`'s syscall returns, `G1` is placed on an available `P` (or the global runqueue) and `M1` is parked in the idle thread pool."
          },
          {
            level: "LEVEL 2 // COMPILER & MEMORY LAYOUT",
            q: "Why does returning an `interface{}` or passing a slice to `fmt.Println` frequently cause variables to escape to the heap, and how does Go grow a goroutine's stack from 2KB?",
            a: "Go's compile-time escape analysis (`go build -gcflags='-m'`) must prove at compile time that a pointer's lifetime does not outlive its stack frame and its size is statically bounded. Calling a method on an `interface` is dynamically dispatched through an `itab` function pointer, so the compiler often cannot prove whether the concrete implementation stores the reference globally—forcing heap allocation. When a goroutine overflows its initial 2KB stack (checked at function prologue via `SP <= g.stackguard0`), Go allocates a **new contiguous stack 2x larger**, copies the old stack over, and adjusts all internal stack pointers—which is why taking raw unmanaged pointers across CGo boundaries is strictly policed."
          },
          {
            level: "LEVEL 3 // GARBAGE COLLECTOR CONCURRENCY",
            q: "What is 'GC Assist' in Go, and how can it cause sudden p99 tail latency spikes even when concurrent GC pauses (STW) are under 100 microseconds?",
            a: "While Go's Stop-The-World (STW) phases (enabling/disabling the Hybrid Write Barrier, which combines Yuasa's snapshot-at-the-beginning deletion barrier and Dijkstra's insertion barrier) take <100µs, if user goroutines allocate heap memory faster than background GC worker goroutines (capped at ~25% CPU) can scan, the runtime forces the allocating request goroutine itself to stop executing business logic and perform **Mark Assist** scanning proportional to the bytes it allocates (`mallocgc` -> `gcAssistAlloc`). In high-throughput RPC handlers, GC Assist directly inflates request p99 latency unless allocations are pooled (`sync.Pool`) or `GOMEMLIMIT` / `GOGC` is tuned."
          }
        ],
        mechanism: "Go schedules `G` (goroutines, ~2KB initial stack) onto `M` (OS kernel threads) bound to `P` (logical processors, count = `GOMAXPROCS`). Each `P` holds an `mcache` (per-P thread-caching allocator derived from TCMalloc, spanning 68 size classes from 8B to 32KB to allocate small objects with zero lock contention) and a lock-free 256-slot local runqueue. Every 61 ticks, a `P` checks the global runqueue first to prevent starvation; if its local queue is empty, it steals half the goroutines from a randomly chosen `P`'s local queue.",
        failures: "1. **Kubernetes CFS Quota Throttling**: On a 64-core host where a pod has a `2000m` (2 CPU) limit, Go defaults `GOMAXPROCS` to 64 unless `automaxprocs` (or Go 1.25+ container-aware runtime) is used—burning the entire 100ms CFS quota in 3ms and stalling for 97ms.\n2. **Goroutine & Channel Leaks**: Writing to an unbuffered channel when the receiver returns early on `ctx.Done()` permanently leaks the sender goroutine and its entire reachable stack/heap graph.",
        codeBlueprint: `// High-Throughput Zero-Allocation Buffer Processing with sync.Pool & Context Cancellation
var framePool = sync.Pool{
    New: func() any {
        buf := make([]byte, 0, 64*1024) // 64KB pre-sized slice
        return &buf // Return pointer to slice header to avoid interface boxing allocation
    },
}

func ProcessPayload(ctx context.Context, r io.Reader) error {
    bufPtr := framePool.Get().(*[]byte)
    buf := (*bufPtr)[:0]
    defer func() {
        if cap(buf) <= 256*1024 { // Prevent pinning oversized buffers in pool
            *bufPtr = buf[:0]
            framePool.Put(bufPtr)
        }
    }()
    // ... non-escaping zero-copy parse ...
    return nil
}`,
        l4Contrast: "Says 'Goroutines are lightweight threads and channels pass data safely.' Cannot explain `P` vs `M`, escape analysis `-gcflags=-m`, or why GC Assist hurts p99 latency.",
        l6Contrast: "Explains GMP work stealing, netpoller `epoll` integration, per-P `mcache` size classes, Hybrid Write Barrier invariants, GC Mark Assist backpressure, and `GOMAXPROCS` under Linux `cgroups v2`."
      },
      {
        key: "react_browser_internals",
        domain: "FRONTEND & BROWSER INTERNALS",
        level: "L6",
        matchKeywords: ["react", "frontend", "next.js", "nextjs", "dom", "fiber", "ui", "browser", "javascript", "canvas", "crdt"],
        title: "React Fiber Linked-List Architecture, Concurrent Lane Prioritization & V8 Hidden Classes",
        prompt: "Your resume highlights advanced frontend and browser performance optimization. Explain why React 16+ replaced the recursive stack reconciler with the Fiber singly-linked-list tree (`child`, `sibling`, `return`), how double-buffering (`current` vs. `workInProgress`) and bitmask `Lanes` enable interruptible rendering without visual DOM tearing, and how polymorphic object shapes deoptimize V8's Inline Caches (ICs) in hot client-side loops.",
        intent: "Tests whether the candidate understands browser/JS runtime mechanics and React's internal scheduler rather than just calling `useState` and `useEffect`.",
        signals: ["Fiber node", "workInProgress", "alternate pointer", "31-bit Lanes", "render vs commit phase", "useSyncExternalStore", "tearing", "V8 Hidden Classes (Maps)", "Inline Caches (monomorphic vs megamorphic)"],
        followups: [
          {
            level: "LEVEL 1 // FIBER TREE MECHANISM",
            q: "How does React traverse a deeply nested component tree iteratively without using the JavaScript call stack, and what happens when a high-priority input event interrupts an in-progress transition?",
            a: "Each Fiber node is a heap-allocated JS object holding three graph pointers: `child` (first child), `sibling` (next sibling), and `return` (parent), plus an `alternate` pointer linking the visible `current` Fiber to its `workInProgress` twin. `workLoopConcurrent` iterates one Fiber at a time (`performUnitOfWork`: `beginWork` down `child`, then `completeWork` across `sibling` or up `return`), checking `shouldYield()` (5ms frame budget via `MessageChannel`) between nodes. If an Urgent `SyncLane` user click arrives during a `TransitionLane` render, React discards or pauses the `workInProgress` tree during the **Render Phase** (which has zero DOM side effects), processes the urgent update immediately, and then replays the transition from the updated base state."
          },
          {
            level: "LEVEL 2 // CONCURRENT TEARING BUG",
            q: "What is 'UI Tearing' in Concurrent React when reading from an external mutable store (like Redux/Zustand/custom CRDT canvas), and how does `useSyncExternalStore` prevent it?",
            a: "During time-sliced concurrent rendering, React yields back to the browser main thread every ~5ms. If an external store mutates outside React's state system during that yield gap, Component A (rendered at `t=2ms`) reads `store.v1`, while Component B (rendered at `t=9ms` in the same render pass) reads `store.v2`. When the Commit Phase flushes both to the DOM synchronously, the user sees an inconsistent 'torn' UI showing two different versions of state simultaneously! `useSyncExternalStore` snapshots the store version before starting a render and attaches a render-phase consistency check; if the store mutates mid-render, React forces a synchronous (`SyncLane`) restart of the render tree."
          },
          {
            level: "LEVEL 3 // V8 ENGINE OPTIMIZATION",
            q: "What happens inside V8 TurboFan when a function receives objects with keys added in different orders or with optional `delete obj.prop` calls?",
            a: "V8 assigns every JS object a hidden class (`Map` / Shape) describing the fixed memory byte offsets of its properties. Adding keys in different orders (`{a:1, b:2}` vs `{b:2, a:1}`) creates divergent hidden class transition chains, and `delete obj.prop` downgrades the object to slow hash-table 'dictionary mode'. When a hot function's call-site Inline Cache (IC) sees 1 shape, it is **monomorphic** (direct offset load in 2 CPU instructions); at 2–4 shapes it becomes **polymorphic** (linear branch table); at ≥5 shapes it degrades to **megamorphic**, triggering a TurboFan **bailout / deoptimization** back to the Ignition bytecode interpreter."
          }
        ],
        mechanism: "React splits updates into two strictly separated phases: (1) the asynchronous, interruptible **Render/Reconciliation Phase**, which builds the `workInProgress` Fiber tree and computes a bitmask `subtreeFlags` / effect list of mutations, and (2) the synchronous, non-interruptible **Commit Phase** (`commitMutationEffects`, `commitLayoutEffects`, and swapping `fiberRoot.current = workInProgress`), which mutates the real DOM in a single atomic turn before the browser paints.",
        failures: "1. **Closure Staleness & Effect Thrashing**: Capturing stale state inside long-lived WebSocket/interval callbacks or passing unstable inline object literals in dependency arrays.\n2. **Layout Thrashing (Forced Synchronous Reflow)**: Reading geometric DOM properties (`getBoundingClientRect()`, `offsetHeight`) immediately after mutating styles inside a loop forces the browser Blink engine to recalculate style and layout synchronously on every iteration.",
        codeBlueprint: `// Tearing-Safe External CRDT Store Binding + Monomorphic V8 Object Factory
function createPointNode(id, x, y, flags) {
  // Strictly fixed property initialization order & types -> Single V8 Hidden Class (Map)
  return { id: id | 0, x: +x, y: +y, flags: flags | 0 };
}

export function useCRDTSelection(docStore, selector) {
  return React.useSyncExternalStore(
    docStore.subscribe,
    () => selector(docStore.getSnapshot()), // Tearing-checked snapshot read
    () => selector(docStore.getServerSnapshot())
  );
}`,
        l4Contrast: "Says 'React uses a Virtual DOM because updating the real DOM is slow, and useMemo prevents re-renders.' Cannot explain Fiber pointers, concurrent tearing, or V8 hidden classes.",
        l6Contrast: "Explains `child`/`sibling`/`return` iterative traversal, `current` vs `workInProgress` double buffering, 31-bit Lane bitmasks, `useSyncExternalStore` tearing prevention, and V8 IC monomorphism."
      },
      {
        key: "typescript_node_internals",
        domain: "LANGUAGE SYSTEMS & NODE.JS RUNTIME",
        level: "L6",
        matchKeywords: ["typescript", "node", "nodejs", "v8", "libuv", "graphql", "dataloader", "async", "event loop"],
        title: "Libuv 6-Phase Event Loop, Microtask Starvation, GraphQL DataLoader & TypeScript Variance",
        prompt: "Your resume lists TypeScript and Node.js backend systems. Walk through the exact execution order of Libuv's 6 event-loop phases relative to `process.nextTick` and Promise microtasks (and how recursive microtasks starve I/O), explain how GraphQL DataLoader coalesces N+1 queries using event-loop tick scheduling, and explain why function parameters in TypeScript must be contravariant for soundness.",
        intent: "Verifies deep comprehension of Node.js non-blocking I/O pitfalls, event loop tick batching, and static type theory.",
        signals: ["timers / poll / check phases", "process.nextTick", "microtask starvation", "UV_THREADPOOL_SIZE", "DataLoader tick batching", "contravariance", "structural vs nominal typing", "distributive conditional types"],
        followups: [
          {
            level: "LEVEL 1 // EVENT LOOP & I/O STARVATION",
            q: "Why does `dns.lookup()` in Node.js bottleneck under high concurrency while `dns.resolve4()` does not, and how can `process.nextTick` freeze incoming HTTP requests?",
            a: "`dns.lookup()` calls the synchronous POSIX C library `getaddrinfo(3)`, which runs on Libuv's fixed worker threadpool (`UV_THREADPOOL_SIZE`, defaulting to just **4 threads**!). If 4 slow DNS lookups or `fs` calls block those 4 threads, all other `dns.lookup()`, `crypto.pbkdf2()`, and `zlib` calls queue up and stall. `dns.resolve4()` uses c-ares directly over non-blocking UDP/TCP sockets on the main epoll poll phase. Meanwhile, `process.nextTick` and Promise microtasks drain completely to exhaustion *between* every phase transition; a recursive `nextTick` loop prevents Libuv from ever entering the **Poll Phase**, starving all network I/O."
          },
          {
            level: "LEVEL 2 // DATALOADER BATCHING MECHANICS",
            q: "How does GraphQL `DataLoader.load(id)` collect 50 independent field resolver calls across a query tree into a single `SELECT ... WHERE id IN (...)` without explicit coordination between resolvers?",
            a: "When `loader.load(key)` is called synchronously inside multiple parallel GraphQL field resolvers, it checks an per-request in-memory Map cache first. On a miss, it pushes `(key, resolve, reject)` onto an internal `batch.keys` array and—only on the first call in the current tick—schedules `enqueuePostPromiseJob` (`process.nextTick` after current Promise microtasks drain). All synchronous and microtask-resolved GraphQL resolvers in the same tree level execute and push their keys into the same `batch` before the `nextTick` callback fires and dispatches a single batched SQL query."
          },
          {
            level: "LEVEL 3 // TYPE SYSTEM SOUNDNESS",
            q: "In TypeScript (`strictFunctionTypes: true`), why is `type Handler<T> = (arg: T) => void` contravariant in `T`, and how do you enforce nominal typing in a structurally typed compiler?",
            a: "Suppose `Dog extends Animal` (where `Dog` has `.bark()`). If `(arg: Dog) => void` were assignable to `(arg: Animal) => void` (covariant), a caller holding `(arg: Animal) => void` could legally pass a `Cat`, crashing the runtime implementation when it calls `cat.bark()`. Therefore, parameter types invert subtype direction (**contravariance**): `(arg: Animal) => void` is assignable to `(arg: Dog) => void`. Because TypeScript uses structural duck-typing, two types `UserId = string` and `OrderId = string` are interchangeable unless branded via a phantom unique symbol property: `type Brand<K, T> = K & { readonly __brand: T }`."
          }
        ],
        mechanism: "Libuv runs a single-threaded event loop cycling through 6 phases: (1) **Timers** (`setTimeout`/`setInterval` min-heap), (2) **Pending I/O Callbacks** (deferred TCP errors), (3) **Idle / Prepare**, (4) **Poll** (`epoll_wait` calculating timeout from nearest timer; executes network I/O callbacks), (5) **Check** (`setImmediate` callbacks), and (6) **Close Callbacks** (`socket.on('close')`). After every individual callback and phase transition, V8 drains the `nextTickQueue` and the Promise `MicrotaskQueue`.",
        failures: "1. **JSON.parse / Regex ReDoS Event Loop Blocking**: Parsing a 25MB JSON payload or running a backtracking regex on the main V8 thread blocks all 10,000 connected sockets for 150ms.\n2. **DataLoader Cache Key Ordering Bug**: If the batch SQL function returns rows in arbitrary DB order instead of matching the exact positional order and length of `keys`, DataLoader resolves User A's data to User B!",
        codeBlueprint: `// Sound Nominal Branding + Tick-Coalesced Batch Loader Blueprint
declare const __brand: unique symbol;
export type Branded<T, B> = T & { readonly [__brand]: B };
export type AccountId = Branded<string, "AccountId">;

export class MicroBatchLoader<K, V> {
  private cache = new Map<K, Promise<V>>();
  private queue: Array<{ key: K; resolve: (v: V) => void; reject: (e: unknown) => void }> = [];
  private scheduled = false;

  constructor(private readonly batchFn: (keys: readonly K[]) => Promise<readonly V[]>) {}

  load(key: K): Promise<V> {
    const hit = this.cache.get(key);
    if (hit) return hit;
    const p = new Promise<V>((resolve, reject) => {
      this.queue.push({ key, resolve, reject });
      if (!this.scheduled) {
        this.scheduled = true;
        process.nextTick(() => this.flush());
      }
    });
    this.cache.set(key, p);
    return p;
  }

  private async flush() {
    const batch = this.queue.splice(0, this.queue.length);
    this.scheduled = false;
    try {
      const results = await this.batchFn(batch.map(item => item.key));
      // Positional invariant: results.length MUST equal batch.length
      batch.forEach((item, idx) => item.resolve(results[idx]));
    } catch (err) {
      batch.forEach(item => { this.cache.delete(item.key); item.reject(err); });
    }
  }
}`,
        l4Contrast: "Says 'Node.js is single-threaded and uses an event loop for async callbacks.' Cannot distinguish `setImmediate` vs `process.nextTick` or explain why DataLoader requires positional array alignment.",
        l6Contrast: "Maps out all 6 Libuv phases, explains `UV_THREADPOOL_SIZE` contention on `getaddrinfo`, demonstrates microtask tick batching, and proves function parameter contravariance."
      },
      {
        key: "kubernetes_linux_kernel",
        domain: "CLOUD INFRASTRUCTURE & LINUX KERNEL",
        level: "L6",
        matchKeywords: ["kubernetes", "k8s", "docker", "container", "ebpf", "cilium", "linux", "cgroups", "etcd", "envoy"],
        title: "Kubernetes cgroups v2 CFS Throttling, eBPF vs. iptables Dataplane & Zero-Downtime Pod Termination",
        prompt: "Your resume lists Kubernetes and Linux infrastructure engineering. Explain the exact race condition during Kubernetes Pod termination that causes 502/504 errors even when a `SIGTERM` handler drains connections cleanly, why setting CPU limits causes p99 latency spikes even when average node CPU is 25% (`cpu.cfs_quota_us`), and why Cilium/eBPF scales to 10,000+ Services while `kube-proxy` iptables degrades.",
        intent: "Tests operational depth in Linux kernel primitives (`cgroups`, `netfilter`, `eBPF`) and distributed race conditions inside Kubernetes control/data planes.",
        signals: ["EndpointSlice propagation race", "preStop hook", "cgroups v2", "CFS bandwidth quota 100ms period", "iptables O(N) sequential chain", "eBPF socket-level map lookup O(1)", "etcd Raft wal fsync"],
        followups: [
          {
            level: "LEVEL 1 // DISTRIBUTED TERMINATION RACE",
            q: "Trace the exact parallel timeline when `kubectl delete pod` is called: why does traffic keep arriving at the pod AFTER `SIGTERM` has already been delivered?",
            a: "When the API Server transitions a Pod to `Terminating`, two asynchronous control paths fire in parallel: (1) `kubelet` on the node immediately executes `preStop` (if any) and sends `SIGTERM` to PID 1 in the container, while (2) the `endpointslice-controller` removes the Pod IP from the `EndpointSlice` object in `etcd`, which must then be watched by `kube-proxy` / Envoy ingress controllers across every node to rewrite local `iptables`/eBPF maps. Path 2 frequently takes **1–5 seconds** across large clusters! If the app closes its listening socket immediately upon receiving `SIGTERM`, in-flight packets routed by stale `iptables`/Envoy rules hit `ECONNREFUSED` / `502 Bad Gateway`. The fix is a `preStop` sleep (or keeping the listener open in a graceful readiness-failing state for 5–10s after `SIGTERM`) before calling `server.Shutdown()`."
          },
          {
            level: "LEVEL 2 // LINUX KERNEL CFS THROTTLING",
            q: "How can a multi-threaded service with a Kubernetes CPU limit of `2000m` (2 cores) get throttled by the Linux Completely Fair Scheduler (CFS) within 10ms of a 100ms period?",
            a: "Linux CFS enforces CPU limits using `cpu.cfs_period_us = 100,000` (100ms wall-clock window) and `cpu.cfs_quota_us = 200,000` (200ms of aggregate CPU time across all cores). If a service spawns 20 worker threads on a 32-core host and a burst of requests arrives simultaneously, all 20 threads run in parallel across 20 physical cores and **burn the entire 200ms quota in just 10ms of wall-clock time** (`20 threads * 10ms = 200ms`). The kernel then freezes all threads in that cgroup for the remaining **90ms** of the window, creating artificial 90ms+ p99 latency spikes."
          },
          {
            level: "LEVEL 3 // KERNEL NETWORK DATAPLANE",
            q: "Why does `kube-proxy` in `iptables` mode degrade packet forwarding and rule update latency at 5,000+ Services, and how does Cilium eBPF bypass this?",
            a: "`iptables` (`netfilter`) evaluates `KUBE-SERVICES` rules as a **sequential O(N) linked list** on every new TCP connection (`SYN`), and updating a single Service endpoint requires `iptables-restore` to serialize, lock, and replace the **entire ruleset blob** atomically in kernel space (taking seconds at 10,000 Services). Cilium attaches eBPF programs directly at the `sockops` / `connect(2)` syscall hook (`cgroup/connect4`): before a TCP packet or `sk_buff` is even constructed, it performs an **O(1) eBPF hash map lookup** translating the ClusterIP VIP directly into the backing Pod IP in the socket structure."
          }
        ],
        mechanism: "Containers are isolated Linux processes constructed via `clone(2)` with `namespaces` (`pid`, `net`, `mnt`, `uts`, `ipc`, `user`) for visibility isolation and `cgroups v2` (`/sys/fs/cgroup`) for resource accounting (`memory.current`, `memory.high` throttling vs `memory.max` OOM killer, and `cpu.max`). Container networking pairs a host-side virtual ethernet interface (`veth`) with an interface inside the pod's network namespace (`eth0`), bridged via CNI routing or eBPF `bpf_redirect_peer()`.",
        failures: "1. **OOMKilled via Kernel Pagecache Accounting**: In `cgroups`, buffered file writes dirty kernel pagecache pages charged to the container's `memory.current`; heavy logging or temp file writes can trigger the Linux OOM-killer even when process RSS heap is low.\n2. **Conntrack Table Exhaustion (`nf_conntrack_max`)**: High-churn short-lived connections or DNS UDP queries overflow the kernel connection tracking table, dropping packets with `nf_conntrack: table full, dropping packet`.",
        codeBlueprint: `# Zero-Downtime Pod Lifecycle & CFS Throttling-Aware Kubernetes Spec
apiVersion: apps/v1
kind: Deployment
spec:
  template:
    spec:
      terminationGracePeriodSeconds: 45
      containers:
        - name: ledger-api
          env:
            - name: GOMAXPROCS
              value: "4" # Match CPU request to prevent 64-thread CFS quota burst
          readinessProbe:
            httpGet:
              path: /healthz/ready
              port: 8080
            periodSeconds: 2
            failureThreshold: 1
          lifecycle:
            preStop:
              exec:
                # Allow EndpointSlice removal to propagate to kube-proxy/Envoy before SIGTERM
                command: ["/bin/sh", "-c", "sleep 8"]`,
        l4Contrast: "Says 'Kubernetes uses Docker containers and readiness probes stop traffic when a pod dies.' Unaware that EndpointSlice removal is asynchronous with SIGTERM or how CFS quotas work.",
        l6Contrast: "Traces the parallel `kubelet` SIGTERM vs `EndpointSlice` propagation race condition, calculates `cpu.cfs_quota_us` multi-core burst exhaustion, and contrasts `iptables` O(N) netfilter chains against `cgroup/connect4` eBPF O(1) maps."
      },
      {
        key: "llm_gpu_systems",
        domain: "AI/ML INFRASTRUCTURE & GPU SYSTEMS",
        level: "L6",
        matchKeywords: ["pytorch", "cuda", "gpu", "llm", "vllm", "triton", "flashattention", "rag", "vector", "hnsw", "training", "fsdp", "inference"],
        title: "LLM KV-Cache Memory Bandwidth, PagedAttention Block Tables & FlashAttention SRAM Tiling",
        prompt: "Your resume details ML/GPU systems and inference optimization. Derive from first principles why autoregressive LLM token generation (the Decode phase) is strictly HBM memory-bandwidth bound rather than FLOP-bound, calculate the exact KV-Cache memory footprint for a 70B model at 32k context, explain how vLLM's PagedAttention eliminates external/internal KV fragmentation, and explain how FlashAttention avoids O(N²) HBM reads/writes.",
        intent: "Tests hard quantitative mastery of GPU hardware hierarchy (HBM vs SRAM, Arithmetic Intensity / Roofline model), transformer memory math, and distributed GPU systems.",
        signals: ["Roofline arithmetic intensity", "Prefill (compute-bound) vs Decode (memory-bound)", "GQA (Grouped-Query Attention)", "PagedAttention virtual block tables", "FlashAttention online softmax tiling", "SRAM vs HBM", "NCCL AllReduce / FSDP"],
        followups: [
          {
            level: "LEVEL 1 // QUANTITATIVE KV-CACHE MATH",
            q: "Calculate the exact KV-Cache size in GB for Llama-3-70B (80 layers, 8 KV heads via GQA, head_dim = 128) in FP16 for a batch size of 16 at 32,768 sequence length.",
            a: "Formula per token: `2 (K and V) * n_layers (80) * n_kv_heads (8) * head_dim (128) * bytes_per_param (2 bytes for FP16) = 2 * 80 * 8 * 128 * 2 = 327,680 bytes (~320 KB per token)`. Multiply by `sequence_length (32,768)` = `10.737 GB per sequence`. For a batch of 16 sequences: `16 * 10.737 GB = 171.8 GB` JUST for the KV-Cache (exceeding two 80GB H100s before even counting the 140GB model weights)! Without Grouped-Query Attention (if `n_kv_heads = 64` Multi-Head Attention), it would require **1.37 TB** of HBM."
          },
          {
            level: "LEVEL 2 // PAGEDATTENTION & CONTINUOUS BATCHING",
            q: "Why did naive serving frameworks waste 60–80% of GPU HBM on KV-Cache allocation, and how does vLLM's PagedAttention mimic OS virtual memory?",
            a: "Because output sequence length is unknown in advance, naive engines pre-allocated a contiguous HBM tensor of size `max_seq_len` per request, causing massive **internal fragmentation** (unused reserved slots) and **external fragmentation** between variable-sized tensors. PagedAttention partitions HBM into fixed-size physical **KV Blocks** (e.g., 16 tokens per block) and maintains a per-sequence **Block Table** mapping logical token blocks to non-contiguous physical HBM blocks—allocating blocks on-demand as tokens are generated and enabling zero-copy Copy-on-Write prefix sharing (for system prompts or parallel beam/sample decoding)."
          },
          {
            level: "LEVEL 3 // FLASHATTENTION & ONLINE SOFTMAX",
            q: "Why can't standard `Softmax(Q * K^T) * V` simply be tiled into GPU Shared Memory (SRAM) without the 'Online Softmax' rescaling trick?",
            a: "Standard attention materializes the `N x N` attention matrix `S = Q * K^T` in slow GPU HBM (~3 TB/s on H100) because numerically stable `Softmax(x_i) = exp(x_i - m) / sum(exp(x_j - m))` requires knowing the row-wise global maximum `m` and denominator sum `l` across all `N` keys before multiplying by `V`. FlashAttention loads blocks of `Q`, `K`, `V` into fast on-chip SRAM (~19 TB/s) and uses **Online Softmax**: as it iterates across tiles of `K` and `V`, it tracks a running max `m_new = max(m_old, tile_max)` and rescales both the running denominator and the already-accumulated output `O` by `exp(m_old - m_new)` in a single pass—never writing the `N x N` matrix to HBM."
          }
        ],
        mechanism: "On an NVIDIA H100 SXM5 (989 TFLOPS FP16, 3.35 TB/s HBM3 bandwidth), the **Roofline Ridge Point** is `989e12 / 3.35e12 ≈ 295 FLOPs/Byte`. During the **Prefill Phase**, processing `N` prompt tokens in parallel performs Matrix-Matrix multiplication (`GEMM`) with high arithmetic intensity (`>300 FLOPs/Byte`), making it compute-bound. During the **Decode Phase**, generating 1 token per sequence performs Matrix-Vector multiplication (`GEMV`), streaming all 140GB of model weights + the entire KV-Cache from HBM just to do 2 FLOPs per weight per request (`Arithmetic Intensity ≈ Batch_Size`). Unless effective batch size reaches ~256+ via Continuous Batching (or Speculative Decoding), the GPU SMs stall waiting on HBM memory transfers.",
        failures: "1. **Tensor Parallelism (TP) Cross-Node Bottleneck**: TP requires an `AllReduce` synchronization after *every single transformer layer* (160 times per token on an 80-layer model). Running TP across nodes over standard Ethernet instead of intra-node NVLink (900 GB/s) collapses throughput.\n2. **HNSW Vector Index Recall Collapse under Filtering**: Pre-filtering metadata in an HNSW graph disconnects graph navigation hubs, causing nearest-neighbor beam search to get trapped in local minima unless filtered-aware graph traversal (ACORN / adaptive efSearch) is used.",
        codeBlueprint: `# Exact Roofline & KV-Cache Capacity Calculator for LLM Serving
def audit_llm_serving(n_params_b=70, n_layers=80, n_kv_heads=8, head_dim=128,
                      batch_size=32, seq_len=16384, fp_bytes=2, hbm_bw_gbps=3350):
    weight_gb = n_params_b * fp_bytes
    kv_bytes_per_token = 2 * n_layers * n_kv_heads * head_dim * fp_bytes
    total_kv_gb = (kv_bytes_per_token * seq_len * batch_size) / (1024**3)
    # Every decode step must stream all weights + entire active KV cache from HBM
    bytes_streamed_per_step_gb = weight_gb + total_kv_gb
    theoretical_min_step_ms = (bytes_streamed_per_step_gb / hbm_bw_gbps) * 1000.0
    return {
        "weights_gb": round(weight_gb, 2),
        "kv_cache_gb": round(total_kv_gb, 2),
        "min_inter_token_latency_ms": round(theoretical_min_step_ms, 2),
    }`,
        l4Contrast: "Says 'LLMs need lots of GPU memory for weights, and FlashAttention makes attention faster.' Cannot compute KV-Cache bytes per token or explain why Decode is HBM bandwidth-bound.",
        l6Contrast: "Derives the H100 Roofline ridge point (~295 FLOPs/B), computes exact GQA KV-Cache footprint (`2 * L * H_kv * d * B`), explains PagedAttention block tables, and derives Online Softmax rescaling in SRAM."
      },
      {
        key: "distributed_consensus_transactions",
        domain: "DISTRIBUTED SYSTEMS & CONSENSUS",
        level: "L6",
        matchKeywords: ["distributed", "raft", "paxos", "consensus", "multi-region", "replication", "saga", "2pc", "dynamodb", "consistency", "quorum"],
        title: "Raft Split-Brain & Linearizable Reads, 2PC Blocking vs. Saga Isolation, and Split-Vote PreVote",
        prompt: "Your resume involves distributed state and high-availability systems. Explain why a Raft Leader cannot simply serve a linearizable read from its local memory without extra protocol work (even if its election timer hasn't expired), how a partitioned minority node causes cluster disruption upon rejoining without the `PreVote` extension, and how you handle the lack of Isolation (`A-C-D` without `I`) when replacing Two-Phase Commit (2PC) with distributed Sagas.",
        intent: "Probes the exact failure modes of distributed consensus clocks, network partitions, and concurrent anomaly protection in microservice transactions.",
        signals: ["Linearizability vs Serializability", "ReadIndex / LeaseRead", "Clock drift bound", "Raft Term inflation", "PreVote protocol", "2PC coordinator blocking", "Saga semantic lock / pivot transaction", "Fencing tokens"],
        followups: [
          {
            level: "LEVEL 1 // LINEARIZABLE READS & CLOCK DRIFT",
            q: "Suppose Node A is the Raft Leader. A network partition silently isolates Node A while Nodes B and C elect Node B as the new Leader (Term 2) and commit writes. If a client queries Node A before Node A's step-down timer fires, why does a local read violate linearizability, and how does `ReadIndex` solve this without writing to the Raft log?",
            a: "Wall-clock timers across nodes can drift at different rates (CPU crystal skew or VM pause), so Node A can believe it is still the valid Leader for several milliseconds *after* Node B has already committed newer state—returning a stale non-linearizable read. To serve a linearizable read without appending a disk log entry (**ReadIndex optimization**): (1) Leader A records its current `commitIndex` as `readIndex`, (2) Leader A sends a lightweight heartbeat round to a quorum of followers to prove it has not been deposed as of right now, and (3) once the quorum ACKs the heartbeat and A's state machine `lastApplied >= readIndex`, A safely returns the result."
          },
          {
            level: "LEVEL 2 // PARTITION REJOIN DISRUPTION",
            q: "What happens when a single Raft follower is network-isolated from the rest of the cluster for 5 minutes and then the network heals? Why does it disrupt a healthy leader?",
            a: "While isolated, the follower's election timeout repeatedly expires. Every time it starts an election that gets no responses, it increments its `currentTerm` (`Term = 5 -> 6 -> ... -> 450`). When the network heals, this lagging node sends a message with `Term = 450` to the healthy Leader (running at `Term = 5`). By Raft's core rule, any node seeing a higher Term MUST immediately step down to Follower! Even though the partitioned node cannot win the election (its log is outdated), it forces an unnecessary leader election and brief write unavailability. The **PreVote extension** fixes this: a node only increments its `Term` after a majority of peers confirm in a pre-vote phase that its log is up-to-date and they haven't heard from a valid leader."
          },
          {
            level: "LEVEL 3 // SAGA ISOLATION ANOMALIES",
            q: "Since each step in a Saga commits its local database transaction immediately, how do you prevent Dirty Reads / Lost Updates when two concurrent Sagas modify the same account or inventory?",
            a: "Sagas sacrifice the `I` (Isolation) in ACID because local transactions commit before the global workflow finishes. To restore isolation without 2PC blocking locks, implement **Semantic Locks**: the compensatable step sets an explicit `status = PENDING_RESERVATION` or increments `reserved_balance` rather than mutating the committed balance directly. Concurrent readers/writers see the semantic lock flag and either block, retry, or compute available funds as `balance - reserved_balance` until the Saga's Pivot/Confirm step clears the lock (or the Compensating transaction rolls it back idempotently)."
          }
        ],
        mechanism: "Linearizability is a **real-time single-object recency guarantee** (once a write completes—or a read observes a new value—all subsequent reads in wall-clock time must observe that value or a newer one). Serializability is a **multi-object transactional isolation guarantee** (transactions execute equivalent to *some* serial order, which may not match real wall-clock order). Combining both yields **Strict Serializability (External Consistency)**, requiring either TrueTime bounded uncertainty wait-out (Google Spanner) or single-raft-group deterministic ordering.",
        failures: "1. **Distributed Lock Without Fencing Tokens**: A worker acquires a Redis/ZooKeeper lock with a 10s lease, hits a 12s GC pause (lease expires; Worker 2 acquires lock), and wakes up to corrupt storage. Storage servers MUST validate a monotonically increasing **fencing token** (`epoch_id`) on every write.\n2. **Out-of-Order Compensations**: Network retries can deliver a Saga's `CancelOrder` compensation *before* the original `CreateOrder` request arrives; the receiver must record a tombstone for the `CancelOrder` so the late `CreateOrder` is rejected.",
        codeBlueprint: `// Fencing-Token Protected Storage Write (Prevents Split-Brain / GC-Paused Zombie Writers)
// Table schema: CREATE TABLE shard_state (shard_id INT PRIMARY KEY, max_fence_token BIGINT, payload JSONB);

UPDATE shard_state
SET
    payload = $1,
    max_fence_token = $2
WHERE shard_id = $3
  AND $2 >= max_fence_token -- Reject write if zombie leader/worker holds an older lease epoch
RETURNING max_fence_token;`,
        l4Contrast: "Says 'Raft elects a leader with a majority vote, and Sagas roll back failed microservice calls.' Unaware of stale leader reads, term inflation on partition heal, or Saga isolation anomalies.",
        l6Contrast: "Distinguishes Linearizability vs Serializability, explains `ReadIndex` quorum heartbeats, details Raft `PreVote` term-inflation prevention, enforces Fencing Tokens against GC pauses, and designs Semantic Locks for Sagas."
      },
      {
        key: "lsm_rocksdb_storage",
        domain: "STORAGE ENGINES & INDEXING",
        level: "L6",
        matchKeywords: ["rocksdb", "cassandra", "dynamodb", "lsm", "sstable", "timeseries", "elasticsearch", "search", "nosql"],
        title: "LSM-Tree Write Amplification, Leveled vs. Size-Tiered Compaction & Bloom Filter False Positives",
        prompt: "Your resume mentions LSM-Tree / NoSQL / Time-Series storage engines. Compare the exact Read, Write, and Space Amplification trade-offs (the RUM Conjecture) between a B-Tree and an LSM-Tree (Log-Structured Merge-Tree), explain how a point lookup in RocksDB avoids scanning every immutable SSTable on disk, and explain why deleting records in an LSM-Tree (`Tombstones`) can temporarily make read queries slower and consume MORE disk space.",
        intent: "Evaluates fundamental storage engine theory (RUM Conjecture), memory-to-disk data structures (SkipList MemTable, Block-Based SSTables, Bloom Filters), and compaction pathologies.",
        signals: ["MemTable SkipList", "Immutable SSTable", "Bloom Filter", "Write Amplification Factor (WAF)", "Size-Tiered vs Leveled Compaction", "Tombstone gc_grace_seconds", "RUM Conjecture"],
        followups: [
          {
            level: "LEVEL 1 // READ PATH & BLOOM FILTER MATH",
            q: "When a point lookup `GET(key)` misses in the active MemTable, how does an LSM-Tree avoid performing disk I/O across dozens of SSTable files?",
            a: "First, for **Leveled Compaction** (RocksDB Level 1+), key ranges within each level are strictly non-overlapping (`L1` is partitioned into sorted SSTables with disjoint `[min_key, max_key]` boundaries stored in memory), so at most **1 SSTable per level** (except `L0`, where flushed MemTables overlap) needs to be checked. Second, each SSTable holds an in-memory **Bloom Filter** (~10 bits per key gives a ~1% false-positive rate and 0% false-negative rate), allowing the engine to skip 99% of candidate SSTables without touching the disk index block."
          },
          {
            level: "LEVEL 2 // TOMBSTONE READ PATHOLOGY",
            q: "Why does executing `DELETE` on 1 million keys in Cassandra or RocksDB often cause subsequent range scans (`ITERATOR / SELECT`) to time out?",
            a: "Because SSTables on disk are strictly immutable, a `DELETE` cannot erase data in place; instead, it appends a **Tombstone** marker to the MemTable. During a range scan, the storage engine must merge-sort iterators across the MemTable and all SSTable levels, reading *every* tombstone and shadowed historical value in memory to suppress deleted keys before finding live rows. Furthermore, in distributed stores (Cassandra), tombstones cannot even be purged during compaction until `gc_grace_seconds` (default 10 days) passes—otherwise a dead node recovering from backup would resurrect deleted data (**Zombie Data**)."
          },
          {
            level: "LEVEL 3 // COMPACTION STALLS",
            q: "What causes a RocksDB 'Write Stall' (`level0_slowdown_writes_trigger` / `level0_stop_writes_trigger`), and how does Leveled Compaction differ from Size-Tiered Compaction?",
            a: "**Size-Tiered Compaction (STCS)** merges SSTables of similar size into larger ones: it minimizes Write Amplification (~4–8x) at the cost of massive Space Amplification (needs up to 50% free disk space to merge the largest tier) and higher Read Amplification. **Leveled Compaction (LCS)** organizes levels growing 10x each (`L1=10MB`, `L2=100MB`, `L3=1GB`) with non-overlapping key ranges: it minimizes Space Amplification (~10%) and Read Amplification, but incurs higher Write Amplification (~10–30x). If write bursts flush `MemTables` into `L0` faster than background threads can compact `L0 -> L1`, `L0` file count hits `level0_stop_writes_trigger` (e.g., 36 files) and RocksDB deliberately throttles or blocks foreground writes so read latency doesn't explode."
          }
        ],
        mechanism: "An LSM-Tree converts random disk writes into sequential appends: every write appends to an on-disk Write-Ahead Log (`WAL`) and inserts into an in-memory lock-free **SkipList MemTable** (`O(log N)`). When the MemTable reaches `write_buffer_size` (e.g., 64MB), it becomes immutable and flushes sequentially to `Level 0` as an **SSTable** (Sorted String Table) divided into 4KB compressed data blocks, a sparse Binary Search Index Block, and a Filter Block (Bloom/Ribbon filter).",
        failures: "1. **Prefix Scan Bloom Filter Bypass**: Standard whole-key Bloom filters cannot help range/prefix scans (`SEEK('user_123:*')`), forcing disk reads across every level unless a **Prefix Extractor Bloom Filter** is configured.\n2. **Pagecache Pollution during Compaction**: Background compaction reading/writing multi-gigabyte SSTables evicts hot working-set blocks from OS pagecache unless `O_DIRECT` or `posix_fadvise(POSIX_FADV_DONTNEED)` is used.",
        codeBlueprint: `// RocksDB Production Tuning: Prefix Bloom Filter + Dynamic Level Bytes
rocksdb::Options options;
options.write_buffer_size = 64 * 1024 * 1024; // 64MB MemTable
options.max_write_buffer_number = 4;
options.level_compaction_dynamic_level_bytes = true; // Minimize WAF across levels

rocksdb::BlockBasedTableOptions table_options;
// 10 bits/key Ribbon/Bloom filter (~1% false positive rate)
table_options.filter_policy.reset(rocksdb::NewRibbonFilterPolicy(10.0));
table_options.cache_index_and_filter_blocks = true;
table_options.pin_l0_filter_and_index_blocks_in_cache = true;
options.table_factory.reset(rocksdb::NewBlockBasedTableFactory(table_options));`,
        l4Contrast: "Says 'NoSQL databases like RocksDB and Cassandra are fast at writes because they append to a log.' Cannot explain SSTable levels, Bloom filter math, or why deletes create tombstones.",
        l6Contrast: "Quantifies the RUM Conjecture (Read/Update/Memory amplification), traces `MemTable -> L0 -> L1..LN`, explains tombstone scan degradation and `gc_grace_seconds` zombie resurrection, and tunes Ribbon/Bloom filters."
      },
      {
        key: "rust_cpp_memory_concurrency",
        domain: "SYSTEMS PROGRAMMING & CPU CACHE",
        level: "L6",
        matchKeywords: ["rust", "c++", "cpp", "memory", "atomic", "lock-free", "simd", "cache", "zero-copy", "kernel"],
        title: "CPU Cache Line False Sharing (MESI Protocol), Acquire/Release Atomics & Async Pinning",
        prompt: "Your resume highlights systems programming in Rust/C++. Explain what happens at the L1/L2 CPU cache hardware level (MESI protocol) when two threads on different cores atomically increment adjacent fields in the same struct ('False Sharing'), explain the difference between `Ordering::Relaxed`, `Acquire`/`Release`, and `SeqCst` at the CPU store-buffer level, and explain why self-referential async futures in Rust require `Pin<&mut Self>`.",
        intent: "Tests hardware-sympathetic systems engineering: CPU cache-line geometry, instruction/memory reordering, and zero-cost async state machine compilation.",
        signals: ["64-byte cache line", "MESI protocol invalidation", "cache-line bouncing", "Store Buffer", "Acquire-Release happens-before", "MFENCE / DMB", "self-referential async state machine", "Pin<&mut Self>"],
        followups: [
          {
            level: "LEVEL 1 // CPU HARDWARE CACHE COHERENCY",
            q: "Why does placing `tx_counter: AtomicU64` and `rx_counter: AtomicU64` next to each other in a struct degrade multi-core throughput by 10x, and how do you fix the memory layout?",
            a: "Modern x86_64 and ARM64 CPUs manage L1/L2 cache coherency at the granularity of a **64-byte Cache Line** (128 bytes on Apple Silicon M-series), not individual 8-byte words. Because both `AtomicU64` fields (16 bytes total) reside in the same 64-byte cache line, Core 0 incrementing `tx_counter` transitions the cache line to **Modified (M)** and broadcasts an **Invalidation** message over the CPU interconnect, forcing Core 1's L1 cache line to **Invalid (I)** even though Core 1 only cares about `rx_counter`. Core 1 must then stall and fetch the cache line back (**Cache-Line Bouncing / False Sharing**). Fix by aligning each hot atomic to its own cache line (`#[repr(align(64))]` in Rust or `alignas(64)` in C++)."
          },
          {
            level: "LEVEL 2 // MEMORY ORDERING & STORE BUFFERS",
            q: "On x86_64 (Total Store Order) vs. ARM64 (Weakly Ordered), what is the actual hardware cost difference between `Acquire`/`Release` and `SeqCst`?",
            a: "On x86_64 (TSO), hardware never reorders `Load -> Load`, `Load -> Store`, or `Store -> Store`, so `Acquire` loads and `Release` stores compile to plain `MOV` instructions with **zero hardware fence overhead** (only preventing compiler reordering). However, x86_64 *does* allow `Store -> Load` reordering because writes sit in a per-core **Store Buffer** before draining to L1 cache. `SeqCst` must prevent `Store -> Load` reordering, forcing an `XCHG` or `MFENCE` instruction that drains the entire Store Buffer (~20–40 cycles penalty). On ARM64, even `Acquire`/`Release` require explicit `LDAR` / `STLR` instructions."
          },
          {
            level: "LEVEL 3 // RUST ASYNC STATE MACHINES",
            q: "When the Rust compiler transforms an `async fn` into a state machine `enum`, why does holding a local borrow across an `.await` point create a self-referential struct that cannot be safely moved in memory?",
            a: "An `async fn` compiles into a stackless state machine struct containing all local variables that live across `.await` suspension points. If local variable `buf: [u8; 64]` is borrowed by `slice: &[u8]` across an `.await`, the generated Future struct holds both `buf` and a raw pointer inside `slice` pointing to the memory address of `buf` *inside the same struct*. If the caller moves that Future struct to a new stack/heap address via `mem::swap` or reassignment, `slice` still points to the old dangling memory address! `Pin<&mut T>` guarantees at the type-system level that the pointee's memory address will remain fixed until `Drop` runs."
          }
        ],
        mechanism: "Each CPU core sits behind a private Store Buffer and Invalid Queue connected to L1d (32–64KB, ~1ns), L2 (512KB–1MB, ~4ns), and shared L3 cache via the MESI (Modified, Exclusive, Shared, Invalid) state machine. A `Release` store on Thread A paired with an `Acquire` load of that same atomic variable on Thread B establishes a formal **happens-before** edge: all memory writes (including non-atomic writes) performed by Thread A prior to the `Release` store are guaranteed visible to Thread B after its `Acquire` load.",
        failures: "1. **ABA Problem in Lock-Free CAS Loops**: Thread 1 reads head pointer `A`, gets preempted; Thread 2 pops `A`, pops `B`, frees `A`, allocates a new node that reuses memory address `A`, and pushes it. Thread 1 wakes up and its `compare_exchange(A, next)` succeeds on a corrupted `next` pointer! Fix via 128-bit tagged pointers (`CMPXCHG16B`), Hazard Pointers, or Epoch-Based Reclamation (`crossbeam-epoch`).",
        codeBlueprint: `// Cache-Line Padded Lock-Free Telemetry Ring Counters (Eliminates False Sharing)
#[repr(align(64))]
pub struct CachePaddedAtomic {
    pub value: std::sync::atomic::AtomicU64,
}

pub struct SpscRingHeader {
    // Producer and consumer indices isolated on separate 64-byte CPU cache lines
    pub write_idx: CachePaddedAtomic,
    pub read_idx: CachePaddedAtomic,
}`,
        l4Contrast: "Says 'Rust prevents data races at compile time and AtomicU64 is thread-safe.' Defaults to `Ordering::SeqCst` everywhere without knowing why or what False Sharing is.",
        l6Contrast: "Explains 64-byte MESI cache-line invalidation storms, x86_64 Store Buffer `Store->Load` reordering vs ARM64 `LDAR`/`STLR`, `#[repr(align(64))]` padding, ABA reclamation via epochs, and `Pin<&mut T>`."
      },
      {
        key: "networking_grpc_security",
        domain: "NETWORK PROTOCOLS, RPC & SECURITY",
        level: "L6",
        matchKeywords: ["grpc", "http", "tls", "mtls", "oauth", "jwt", "security", "envoy", "load balancer", "websocket", "api"],
        title: "gRPC HTTP/2 L4 Load Balancing Pitfalls, TCP Head-of-Line Blocking & Token Revocation Architecture",
        prompt: "Your resume includes API gateways, gRPC/HTTP services, and authentication security. Explain why deploying gRPC behind a default Kubernetes ClusterIP (L4 TCP) load balancer causes severe load imbalance across pods, compare HTTP/2 application-layer multiplexing against TCP kernel-layer Head-of-Line (HoL) blocking (and how HTTP/3 QUIC changes this), and explain how to architect stateless JWT authentication that still supports immediate revocation on compromise.",
        intent: "Evaluates deep protocol awareness across L4 (TCP) vs L7 (HTTP/2 frames), kernel socket queues, and real-world security trade-offs.",
        signals: ["HTTP/2 single TCP connection multiplexing", "L4 vs L7 load balancing", "TCP Head-of-Line blocking", "QUIC UDP streams", "TLS 1.3 1-RTT", "Refresh token rotation reuse detection", "MAX_CONCURRENT_STREAMS"],
        followups: [
          {
            level: "LEVEL 1 // gRPC L4 VS L7 LOAD BALANCING",
            q: "Why does scaling a downstream gRPC deployment from 3 pods to 10 pods behind a standard Kubernetes `Service` (`ClusterIP`) leave the 7 new pods completely idle?",
            a: "gRPC runs over **HTTP/2**, which multiplexes thousands of concurrent RPC streams (`HEADERS` and `DATA` frames) over a **single long-lived TCP connection**. Kubernetes `ClusterIP` (`kube-proxy`) operates at **L4 (TCP connection creation time)**: once a client opens 3 TCP connections to the original 3 pods, all subsequent RPCs flow as HTTP/2 frames inside those existing TCP connections and never trigger new L4 load-balancing decisions! Fixing this requires either (1) an L7 proxy (Envoy / Linkerd) that parses HTTP/2 frames and balances per-RPC, (2) client-side load balancing via headless DNS (`clusterIP: None`) with gRPC `round_robin` resolver, or (3) server-side `MAX_CONNECTION_AGE` forcing periodic reconnects."
          },
          {
            level: "LEVEL 2 // TCP VS QUIC HEAD-OF-LINE BLOCKING",
            q: "HTTP/2 claims to solve Head-of-Line blocking via stream multiplexing. Why can a 1% packet loss rate make a single multiplexed HTTP/2 connection SLOWER than 6 separate HTTP/1.1 TCP connections?",
            a: "While HTTP/2 eliminates *application-layer* HoL blocking, all HTTP/2 streams share a **single underlying kernel TCP byte stream**. The Linux kernel TCP stack enforces strict in-order byte delivery to user space: if a single TCP packet carrying bytes for Stream #4 is lost on the wire, the kernel holds back already-received packets for Streams #5, #6, and #7 in the TCP reorder buffer until the lost packet is retransmitted (~1 RTT stall across ALL streams). **HTTP/3 (QUIC)** runs over UDP and implements stream multiplexing + loss recovery at the transport layer, so a lost UDP datagram only stalls the single affected stream."
          },
          {
            level: "LEVEL 3 // TOKEN COMPROMISE & REVOCATION",
            q: "If stateless JWTs cannot be revoked before expiry without querying a database on every request (which defeats statelessness), how do you bound the blast radius of a stolen token?",
            a: "Combine **short-lived stateless Access JWTs (3–5 min TTL)** with **Rotating Opaque Refresh Tokens** backed by **Reuse Detection (Token Families)**. Every time a Refresh Token `RT_1` is exchanged, it is marked `used` (rather than deleted) and yields `RT_2` in the same `family_id`. If an attacker steals `RT_1` and either the attacker or the legitimate user subsequently attempts to use an already-consumed `RT_1`, the auth server immediately detects a **replay compromise** and revokes the entire `family_id` plus pushes the compromised `jti`/`user_id` to a tiny in-memory revocation bloom filter / Redis pub-sub denylist (which only stores revoked IDs for the remaining ≤5 minutes of Access JWT lifetime)."
          }
        ],
        mechanism: "HTTP/2 divides communication into binary frames (`HEADERS` compressed via HPACK static/dynamic tables, `DATA`, `WINDOW_UPDATE` for per-stream and connection-level flow control, `PING`, `GOAWAY`) tagged with a 31-bit Stream Identifier. TLS 1.3 reduces the handshake from 2-RTT to 1-RTT by sending the client's `key_share` (ECDHE ephemeral public key) immediately inside the `ClientHello`, eliminating legacy RSA key transport and providing mandatory Forward Secrecy.",
        failures: "1. **HTTP/2 BDP Flow-Control Starvation**: If the HTTP/2 initial receive window (default 64KB) is smaller than the network Bandwidth-Delay Product (`BDP = Bandwidth * RTT`), throughput caps out waiting on `WINDOW_UPDATE` frames.\n2. **JWT Algorithm Confusion (`alg: none` or RS256 -> HS256)**: Failing to pin the expected asymmetric algorithm in the JWT verifier allows an attacker to sign a token using the public RSA key as a symmetric HMAC secret.",
        codeBlueprint: `// Go gRPC Server Configuration: Mitigate L4 Pinning & BDP Flow-Control Bottlenecks
grpcServer := grpc.NewServer(
    grpc.KeepaliveParams(keepalive.ServerParameters{
        MaxConnectionIdle:     2 * time.Minute,
        MaxConnectionAge:      10 * time.Minute, // Force periodic L4 rebalance across new pods
        MaxConnectionAgeGrace: 15 * time.Second,
        Time:                  30 * time.Second,
        Timeout:               10 * time.Second,
    }),
    grpc.InitialWindowSize(1 << 20),     // 1MB per-stream window
    grpc.InitialConnWindowSize(8 << 20), // 8MB connection flow-control window
    grpc.MaxConcurrentStreams(1024),
)`,
        l4Contrast: "Says 'gRPC is faster than REST because it uses binary Protobuf and HTTP/2, and JWTs are stateless.' Cannot explain why Kubernetes ClusterIP fails to balance gRPC or why TCP packet loss stalls all HTTP/2 streams.",
        l6Contrast: "Explains L4 connection-level vs L7 frame-level load balancing, `MaxConnectionAge`, kernel TCP reorder-buffer HoL blocking vs QUIC UDP streams, and Refresh Token Family reuse detection."
      }
    ];

    // =========================================================================
    // 3. PRODUCTION INCIDENT STRESS-TEST SCENARIOS
    // =========================================================================
    const INCIDENT_SCENARIOS = [
      {
        id: "inc-01",
        code: "SEV-1 // INC-4092 [03:14 UTC]",
        stack: "POSTGRESQL + REDIS + GO LEDGER",
        title: "Sudden p99 Latency Spike (18ms -> 4,400ms) While Database CPU Remains at 28%",
        symptoms: "Following a promotional traffic surge (35,000 RPS), your Go API gateway begins returning 504 Gateway Timeouts. However, PostgreSQL primary CPU utilization is only 28%, disk IOPS are at 20% capacity, and memory has 40GB free. Active database connections are pinned at max_connections (500).",
        telemetry: `pg_stat_activity dump (sample of 412 / 500 backends):
 pid  | state  | wait_event_type |     wait_event      | query_age | query
------+--------+-----------------+---------------------+-----------+---------------------------------------------------
 8812 | active | Lock            | tuple               | 00:04.12  | UPDATE merchant_balances SET balance = balance + $1 WHERE id = 'm_hot_01'
 8819 | active | Lock            | transactionid       | 00:04.09  | UPDATE merchant_balances SET balance = balance + $1 WHERE id = 'm_hot_01'
 8904 | idle in transaction      | ClientRead          | 00:03.85  | INSERT INTO audit_log ... (waiting on Go app webhook HTTP call)`,
        options: [
          {
            label: "A // Scale PostgreSQL instance vertically from 16 vCPU to 64 vCPU and double max_connections to 1,000.",
            correct: false,
            verdict: "INCORRECT — MISDIAGNOSED LOCK CONTENTION AS CPU SATURATION",
            explanation: "CPU is only at 28% because backends are sleeping on heavyweight locks (`wait_event_type = Lock`), not burning CPU cycles! Doubling `max_connections` to 1,000 will worsen lock convoying and context-switching overhead."
          },
          {
            label: "B // Move the external HTTP webhook call OUTSIDE the DB transaction (`idle in transaction` holding row locks) and batch/shard hot merchant balance updates via sub-accounts or slot buffers.",
            correct: true,
            verdict: "OPTIMAL STAFF DIAGNOSIS — IDENTIFIED TUPLE LOCK CONVOY & IDLE-IN-TRANSACTION",
            explanation: "The `pg_stat_activity` dump reveals two classic compounding killers: (1) Backends are `idle in transaction` (`ClientRead`) because the Go handler holds an open SQL transaction with an exclusive row lock on `m_hot_01` while making a slow outbound HTTP call, and (2) hundreds of concurrent updates to the same `m_hot_01` row serialize on `Lock:tuple` / `Lock:transactionid`. Moving network I/O outside `BEGIN..COMMIT` and sharding hot balances across `N` slot rows (`id = 'm_hot_01#' || (random()*16)::int`) restores sub-10ms latency immediately."
          },
          {
            label: "C // Flush the Redis cluster (`FLUSHALL`) and switch PostgreSQL transaction isolation level to READ UNCOMMITTED.",
            correct: false,
            verdict: "INCORRECT — DANGEROUS & INEFFECTIVE",
            explanation: "In PostgreSQL, `READ UNCOMMITTED` behaves identically to `READ COMMITTED`, and write-write row lock contention (`UPDATE` on the same row) still blocks regardless of isolation level. Flushing Redis will additionally trigger a catastrophic read stampede."
          }
        ]
      },
      {
        id: "inc-02",
        code: "SEV-1 // INC-5108 [14:42 UTC]",
        stack: "KUBERNETES + GO + GRPC",
        title: "50% of gRPC Pods Burning 100% CPU & Throttling While Newly Autoscaled Pods Sit at 2% CPU",
        symptoms: "HPA (Horizontal Pod Autoscaler) scaled your gRPC microservice from 4 pods to 12 pods during peak load. However, the 8 newly created pods are receiving almost zero traffic (2% CPU), while the original 4 pods are heavily CFS-throttled (`nr_throttled` climbing rapidly) with p99 latency > 1,800ms.",
        telemetry: `kubectl top pods -l app=settlement-grpc
NAME                               CPU(cores)   MEMORY(bytes)
settlement-grpc-6d4f9b-aa12 (old)  1980m/2000m  1420Mi
settlement-grpc-6d4f9b-bb91 (old)  1995m/2000m  1490Mi
settlement-grpc-6d4f9b-xk44 (new)    18m/2000m   210Mi
settlement-grpc-6d4f9b-zp89 (new)    14m/2000m   205Mi

/sys/fs/cgroup/cpu.stat on old pods:
nr_periods 14200 | nr_throttled 9810 | throttled_usec 842100000 (GOMAXPROCS=64 on 64-core host)`,
        options: [
          {
            label: "A // Configure gRPC Server `MaxConnectionAge` (or L7 Envoy / headless client-side round_robin load balancing) AND set `GOMAXPROCS` to match the container CPU request/limit.",
            correct: true,
            verdict: "OPTIMAL STAFF DIAGNOSIS — SOLVED HTTP/2 L4 PINNING + CFS QUOTA EXHAUSTION",
            explanation: "Two root causes are interacting: (1) gRPC multiplexes all RPCs over persistent HTTP/2 TCP connections; standard Kubernetes `ClusterIP` only load-balances at TCP handshake time (L4), so existing clients stay pinned to the original 4 pods until `MaxConnectionAge` forces reconnects or L7/headless balancing is enabled. (2) Inside the old pods, `GOMAXPROCS=64` spawns 64 OS threads that burn the `2000m` (200ms per 100ms period) CFS quota in ~3ms, causing 69% of periods to be throttled."
          },
          {
            label: "B // Lower the HPA CPU threshold from 70% to 30% so Kubernetes spins up 24 more pods.",
            correct: false,
            verdict: "INCORRECT — NEW PODS WILL ALSO RECEIVE ZERO TRAFFIC",
            explanation: "Because existing gRPC clients hold persistent HTTP/2 connections to the original 4 pods via L4 `ClusterIP`, adding 24 more pods will simply create 24 more idle pods until HTTP/2 connection pinning is resolved."
          },
          {
            label: "C // Switch gRPC serialization from Protobuf to JSON over HTTP/1.1 without keep-alive.",
            correct: false,
            verdict: "INCORRECT — DESTROYS THROUGHPUT & EXHAUSTS EPHEMERAL PORTS",
            explanation: "Disabling keep-alive forces a new TCP + TLS handshake on every single RPC, causing `TIME_WAIT` ephemeral port exhaustion and massive CPU serialization overhead."
          }
        ]
      },
      {
        id: "inc-03",
        code: "SEV-1 // INC-7731 [21:05 UTC]",
        stack: "REACT 18 + TYPESCRIPT + NODE.JS WEBSOCKETS",
        title: "Browser Tab Freeze & Node.js Event Loop Lag Spiking to 2,300ms During Live Broadcast",
        symptoms: "During a high-frequency collaborative update stream (400 delta messages/sec), client browsers experience severe frame drops (8 FPS) with inconsistent state across components, and the Node.js WebSocket gateway reports `eventLoopUtilization = 0.99` with health-check timeouts.",
        telemetry: `Node.js Diagnostics & Chrome Performance Flamegraph:
- Node.js main thread: 78% CPU spent in JSON.stringify() inside per-client broadcast loop (12,000 clients)
- Socket backpressure: ws.bufferedAmount > 48MB per slow mobile client (unbounded heap growth)
- Client React 18: External mutable store mutated 400x/sec during concurrent startTransition renders`,
        options: [
          {
            label: "A // Serialize the broadcast payload ONCE into a shared `Buffer` outside the 12,000-client loop, check `ws.bufferedAmount` backpressure (dropping/coalescing frames for slow sockets), and wrap client store reads in `useSyncExternalStore` + `requestAnimationFrame` batching.",
            correct: true,
            verdict: "OPTIMAL STAFF DIAGNOSIS — ELIMINATED O(N) SERIALIZATION, BACKPRESSURE LEAK & UI TEARING",
            explanation: "Calling `JSON.stringify(payload)` inside a `for (const client of clients)` loop executes 12,000 redundant synchronous V8 serializations per event! Pre-serializing once into a `Buffer` cuts Node CPU by >90%. Checking `ws.bufferedAmount` prevents slow TCP receivers from blowing up V8 heap memory, and coalescing client updates to once per 16ms `requestAnimationFrame` tick with `useSyncExternalStore` eliminates concurrent React tearing."
          },
          {
            label: "B // Wrap the Node.js `for` loop in `process.nextTick()` so it runs asynchronously.",
            correct: false,
            verdict: "INCORRECT — CAUSES COMPLETE I/O STARVATION",
            explanation: "`process.nextTick()` drains synchronously before Libuv can return to the Poll phase, starving all incoming network I/O and health checks even worse."
          },
          {
            label: "C // Disable React 18 StrictMode and increase Node.js `--max-old-space-size=32768`.",
            correct: false,
            verdict: "INCORRECT — MASKS SYMPTOM UNTIL OOM CRASH",
            explanation: "Increasing heap size only delays the Out-Of-Memory crash caused by unbounded `ws.bufferedAmount` queues and does nothing for main-thread serialization stalls."
          }
        ]
      }
    ];

    // =========================================================================
    // 4. APPLICATION STATE & DYNAMIC RESUME DECOMPILER ENGINE
    // =========================================================================
    const state = {
      theme: "paper",
      activeView: "dossier",
      seniority: "L6",
      focusMode: "ALL",
      rawResumeText: "",
      sourceLabel: "ROLE-BASED PRACTICE",
      jobCategory: "backend",
      extractedClaims: [],
      detectedTechs: [],
      questions: [],
      activeQuestionIndex: 0,
      practiceRecords: {}, // keyed by question.id -> { draft, status, score, signalsHit, signalsMissed }
      timerSeconds: 0,
      timerRunning: true,
      timerInterval: null,
      activeIncidentId: "inc-01"
    };

    // Load persisted state from localStorage safely
    function loadPersistedState() {
      try {
        const saved = localStorage.getItem("rigor_workbench_state_v5");
        if (saved) {
          const parsed = JSON.parse(saved);
          if (parsed.practiceRecords) state.practiceRecords = parsed.practiceRecords;
          if (typeof parsed.rawResumeText === "string") {
            state.rawResumeText = parsed.rawResumeText;
            state.sourceLabel = parsed.sourceLabel || "SAVED SESSION RESUME";
          }
          if (JOB_CATEGORIES[parsed.jobCategory]) state.jobCategory = parsed.jobCategory;
          if (parsed.theme) {
            state.theme = parsed.theme;
            document.documentElement.setAttribute("data-theme", state.theme);
          }
        }
      } catch (error) {
        console.warn("Could not restore the saved RIGOR session.", error);
      }
    }

    function savePersistedState() {
      try {
        localStorage.setItem("rigor_workbench_state_v5", JSON.stringify({
          theme: state.theme,
          rawResumeText: state.rawResumeText,
          sourceLabel: state.sourceLabel,
          jobCategory: state.jobCategory,
          practiceRecords: state.practiceRecords
        }));
      } catch (error) {
        console.warn("Could not save the RIGOR session to local storage.", error);
      }
    }

    function showToast(msg) {
      const el = document.getElementById("toast-banner");
      if (!el) return;
      el.textContent = msg;
      el.style.display = "block";
      clearTimeout(el._hideTimer);
      el._hideTimer = setTimeout(() => {
        el.style.display = "none";
      }, 3600);
    }

    let mathTypesettingWarningShown = false;
    let mathTypesettingQueue = Promise.resolve();
    function typesetMath(root = document.body) {
      const mathJax = window.MathJax;
      if (!mathJax || typeof mathJax.typesetPromise !== "function") {
        if (!mathTypesettingWarningShown) {
          console.error("MathJax did not load; LaTeX expressions cannot be rendered.");
          showToast("MATHJAX IS UNAVAILABLE — CHECK YOUR CONNECTION TO RENDER LATEX.");
          mathTypesettingWarningShown = true;
        }
        return;
      }

      mathTypesettingQueue = mathTypesettingQueue
        .then(() => mathJax.startup.promise)
        .then(() => {
          mathJax.typesetClear([root]);
          return mathJax.typesetPromise([root]);
        })
        .catch(error => {
          console.error("LaTeX typesetting failed.", error);
          showToast("LATEX RENDERING FAILED. CHECK THE CONSOLE FOR DETAILS.");
        });
    }

    function analyzeResumeATS(text) {
      const normalized = text.trim();
      if (!normalized) return null;

      const lowerText = normalized.toLowerCase();
      const lines = normalized.split(/\r?\n/).map(line => line.trim()).filter(Boolean);
      const words = normalized.match(/\b[\w+#.-]+\b/g) || [];
      const role = JOB_CATEGORIES[state.jobCategory] || JOB_CATEGORIES.backend;
      const emailFound = /[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}/i.test(normalized);
      const phoneFound = /(?:\+?\d[\d\s().-]{7,}\d)/.test(normalized);
      const sections = [
        /\b(?:professional\s+)?experience\b|\bwork history\b/i,
        /\beducation\b|\bacademic background\b/i,
        /\bskills\b|\btechnical skills\b/i,
        /\bsummary\b|\bprofessional profile\b|\bobjective\b/i
      ].filter(pattern => pattern.test(normalized)).length;
      const keywordMatches = role.keywords.filter(keyword => lowerText.includes(keyword.toLowerCase()));
      const hasMetrics = /\b\d+(?:[,.]\d+)*(?:\.\d+)?(?:\s*(?:%|(?:ms|milliseconds?|seconds?|x|k|m|b|tb|gb|mb|rps|tps|qps|fps|nodes?|gpus?|brokers?|users?|cores?)\b)|\s*(?:requests?|users?)\s*(?:per|\/)\s*(?:second|sec|day|week|month|year)\b)/i.test(normalized);
      const hasActionVerbs = /\b(?:built|created|designed|developed|delivered|improved|increased|reduced|led|launched|implemented|automated|optimized|migrated|scaled|managed|owned|deployed|analyzed|secured|maintained)\b/i.test(normalized);
      const bulletLines = lines.filter(line => /^(?:[•*▪-]|\d+[.)])\s+/.test(line)).length;
      const wordCount = words.length;

      const score = Math.round(
        ((emailFound ? 7.5 : 0) + (phoneFound ? 7.5 : 0)) +
        (sections / 4 * 20) +
        Math.min(25, keywordMatches.length * 5) +
        (hasMetrics ? 15 : 0) +
        (hasActionVerbs ? 10 : 0) +
        (wordCount >= 250 && wordCount <= 1200 ? 10 : (wordCount >= 100 && wordCount <= 1600 ? 6 : (wordCount > 0 ? 3 : 0))) +
        (bulletLines > 0 || sections >= 2 ? 5 : 0)
      );

      const strengths = [];
      if (emailFound && phoneFound) strengths.push("Email and phone contact details are present.");
      if (sections >= 3) strengths.push(`${sections} standard resume sections were detected.`);
      if (keywordMatches.length >= 3) strengths.push(`Role-relevant terms found for ${role.label}: ${keywordMatches.slice(0, 6).join(", ")}.`);
      if (hasMetrics) strengths.push("Quantified results or scale indicators are included.");
      if (hasActionVerbs) strengths.push("Action-oriented accomplishment verbs were found.");
      if (bulletLines > 0) strengths.push("Simple bullet-style lines are present in the extracted text.");
      if (!strengths.length) strengths.push("The resume text is available for review; use the fixes to improve its parser-friendly signals.");

      const fixes = [];
      if (!emailFound) fixes.push("Add a clearly written email address in the contact header.");
      if (!phoneFound) fixes.push("Add a phone number in a consistent international or local format.");
      if (sections < 4) fixes.push("Use explicit, conventional headings such as Summary, Experience, Education, and Skills.");
      if (keywordMatches.length < 3) fixes.push(`Add accurate keywords relevant to ${role.label} (for example: ${role.keywords.slice(0, 4).join(", ")}).`);
      if (!hasMetrics) fixes.push("Add truthful outcomes with numbers, scale, time saved, reliability, or performance where available.");
      if (!hasActionVerbs) fixes.push("Start experience bullets with specific action verbs and describe your contribution.");
      if (wordCount < 250) fixes.push("Add relevant experience and project detail; the extracted resume is unusually short.");
      else if (wordCount > 1200) fixes.push("Trim repeated or low-priority details to make the most relevant experience easier to find.");
      if (bulletLines === 0) fixes.push("Use concise, plain-text bullets for experience entries and avoid relying on layout alone.");

      return { score, wordCount, strengths, fixes, role: role.label };
    }

    function renderATSAnalysis() {
      const analysis = analyzeResumeATS(state.rawResumeText);
      const scoreEl = document.getElementById("ats-score");
      const summaryEl = document.getElementById("ats-summary");
      const strengthsEl = document.getElementById("ats-strengths");
      const fixesEl = document.getElementById("ats-fixes");
      scoreEl.textContent = analysis ? String(analysis.score) : "--";
      summaryEl.textContent = analysis
        ? `${analysis.role} review · ${analysis.wordCount} words · ${analysis.score >= 80 ? "strong parser-friendly signals" : analysis.score >= 60 ? "some useful signals; improvements available" : "several high-value improvements available"}.`
        : "Upload or paste a resume, then compile it to see a role-specific review.";

      const renderList = (container, items) => {
        container.replaceChildren();
        items.forEach(item => {
          const li = document.createElement("li");
          li.textContent = item;
          container.appendChild(li);
        });
      };
      renderList(strengthsEl, analysis ? analysis.strengths : ["Your resume is not uploaded or pasted yet."]);
      renderList(fixesEl, analysis ? analysis.fixes : ["Add a resume to get specific strengths, limitations, and suggested fixes."]);
    }

    function updateJobCategoryDescription() {
      const role = JOB_CATEGORIES[state.jobCategory] || JOB_CATEGORIES.backend;
      document.getElementById("job-category-description").textContent = role.description;
    }

    // =========================================================================
    // 5. RESUME DECOMPILER & DYNAMIC QUESTION SYNTHESIS ENGINE
    // =========================================================================
    const TECH_DICTIONARY = [
      { name: "PostgreSQL", patterns: [/\bpostgres(?:ql)?\b/i, /\bpgbouncer\b/i, /\bmvcc\b/i], domain: "DATABASE INTERNALS" },
      { name: "Redis", patterns: [/\bredis\b/i, /\bsingleflight\b/i], domain: "DISTRIBUTED CACHING" },
      { name: "Apache Kafka", patterns: [/\bkafka\b/i, /\bdebezium\b/i, /\boutbox\b/i], domain: "EVENT STREAMING" },
      { name: "Go (Golang)", patterns: [/\bgo\b/i, /\bgolang\b/i, /\bgoroutine/i, /\bgogc\b/i], domain: "RUNTIME & CONCURRENCY" },
      { name: "Rust", patterns: [/\brust\b/i, /\btokio\b/i, /\bcargo\b/i], domain: "SYSTEMS PROGRAMMING" },
      { name: "C++", patterns: [/\bc\+\+\b/i, /\bcpp\b/i], domain: "SYSTEMS PROGRAMMING" },
      { name: "Python", patterns: [/\bpython\b/i, /\basyncio\b/i, /\bfastapi\b/i], domain: "RUNTIME & ML" },
      { name: "React 18 / Fiber", patterns: [/\breact\b/i, /\bfiber\b/i, /\bnext\.?js\b/i], domain: "FRONTEND INTERNALS" },
      { name: "TypeScript / V8", patterns: [/\btypescript\b/i, /\bjavascript\b/i, /\bv8\b/i], domain: "LANGUAGE & COMPILER" },
      { name: "Node.js / Libuv", patterns: [/\bnode\.?js\b/i, /\blibuv\b/i], domain: "BACKEND RUNTIME" },
      { name: "GraphQL", patterns: [/\bgraphql\b/i, /\bdataloader\b/i], domain: "API ARCHITECTURE" },
      { name: "gRPC / HTTP2", patterns: [/\bgrpc\b/i, /\bprotobuf\b/i, /\benvoy\b/i], domain: "NETWORK PROTOCOLS" },
      { name: "Kubernetes", patterns: [/\bkubernetes\b/i, /\bk8s\b/i, /\bcgroups\b/i, /\betcd\b/i], domain: "CONTAINER ORCHESTRATION" },
      { name: "eBPF / Linux Kernel", patterns: [/\bebpf\b/i, /\bcilium\b/i, /\blinux kernel\b/i, /\biptables\b/i], domain: "KERNEL & NETWORKING" },
      { name: "PyTorch / CUDA", patterns: [/\bpytorch\b/i, /\bcuda\b/i, /\btriton\b/i, /\bfsdp\b/i, /\bnccl\b/i], domain: "GPU & ML SYSTEMS" },
      { name: "LLM / vLLM / FlashAttention", patterns: [/\bvllm\b/i, /\bflashattention\b/i, /\bllm\b/i, /\bkv-?cache\b/i], domain: "INFERENCE INFRASTRUCTURE" },
      { name: "Vector DB / HNSW / RAG", patterns: [/\bhnsw\b/i, /\brag\b/i, /\bqdrant\b/i, /\bvector\b/i], domain: "SEARCH & RETRIEVAL" },
      { name: "RocksDB / LSM-Tree", patterns: [/\brocksdb\b/i, /\blsm\b/i, /\bcassandra\b/i, /\bsstable\b/i], domain: "STORAGE ENGINES" },
      { name: "AWS / Cloud Infra", patterns: [/\baws\b/i, /\bdynamodb\b/i, /\broute53\b/i, /\bterraform\b/i], domain: "CLOUD ARCHITECTURE" },
      { name: "CRDTs / WebSockets", patterns: [/\bcrdt\b/i, /\byjs\b/i, /\bwebsocket/i], domain: "DISTRIBUTED STATE" },
      { name: "OAuth2 / JWT / mTLS", patterns: [/\boauth/i, /\bjwt\b/i, /\bmtls\b/i, /\bspiffe\b/i, /\btls\b/i], domain: "SECURITY & CRYPTO" }
    ];

    const TECH_INTERVIEW_FOCUS = {
      "PostgreSQL": "MVCC visibility, index maintenance, query plans, and vacuum behavior under write load",
      "Redis": "event-loop latency, eviction policy, persistence trade-offs, and cache stampede protection",
      "Apache Kafka": "partition ordering, consumer offsets, replication, and end-to-end delivery guarantees",
      "Go (Golang)": "goroutine scheduling, garbage collection, escape analysis, and cancellation propagation",
      "Rust": "ownership and borrowing, async task behavior, synchronization, and safe boundaries for shared state",
      "C++": "object lifetime, move semantics, synchronization, and memory-safety boundaries",
      "Python": "interpreter concurrency, async I/O, object allocation, and worker/process scaling",
      "React 18 / Fiber": "render scheduling, state consistency, effects, and preventing unnecessary commits",
      "TypeScript / V8": "type-system boundaries, runtime object shapes, garbage collection, and compiler performance",
      "Node.js / Libuv": "event-loop phases, worker-pool contention, backpressure, and graceful shutdown",
      "GraphQL": "resolver execution, batching, schema evolution, authorization, and query-cost limits",
      "gRPC / HTTP2": "HTTP/2 connection multiplexing, flow control, deadlines, retries, and load balancing",
      "Kubernetes": "controller reconciliation, scheduling, readiness, resource limits, and rollout safety",
      "eBPF / Linux Kernel": "verifier constraints, hook selection, map lifecycle, and safe production rollout",
      "PyTorch / CUDA": "tensor placement, kernel launch and synchronization, mixed precision, and profiling",
      "LLM / vLLM / FlashAttention": "KV-cache capacity, continuous batching, prefill/decode costs, and token latency",
      "Vector DB / HNSW / RAG": "recall/latency tuning, embedding freshness, filtering, and retrieval evaluation",
      "RocksDB / LSM-Tree": "compaction strategy, read/write amplification, tombstones, and write stalls",
      "AWS / Cloud Infra": "failure domains, IAM boundaries, capacity limits, and safe multi-region recovery",
      "CRDTs / WebSockets": "convergence invariants, message ordering, reconnect recovery, and fan-out backpressure",
      "OAuth2 / JWT / mTLS": "identity boundaries, key rotation, token lifetime, revocation, and transport identity"
    };

    const ROLE_TOPIC_DRILLS = {
      backend: [
        { title: "API contracts and backwards-compatible evolution", prompt: "How would you evolve a public API used by old and new clients at the same time? Cover compatibility, rollout, and deprecation.", signals: ["backwards compatibility", "schema evolution", "consumer contract", "deprecation"], answer: "Add optional fields or a new version without changing existing semantics; deploy tolerant readers first, then producers, measure old-client usage, and remove deprecated behavior only after a communicated sunset.", failure: "Changing field meaning or making an optional field required can silently break older clients; dual-write or versioned response paths need explicit parity checks.", validate: "Track per-version traffic, schema/contract test results, error rates, and deprecation usage before and after each rollout." },
        { title: "Idempotency and safe request retries", prompt: "A client times out after a payment-like write and retries. How do you make the operation safe when the server may already have committed it?", signals: ["idempotency key", "unique constraint", "atomic commit", "replay"], answer: "Persist a client idempotency key with the request hash and final result in the same transaction as the write; return the saved result on replay and reject key reuse with a different payload.", failure: "A cache-only idempotency record can expire while a retry is still in flight, creating a duplicate side effect.", validate: "Test concurrent duplicate submissions, timeout-after-commit, key reuse with changed payload, and recovery after process restart." },
        { title: "Database connection and pool saturation", prompt: "Latency rises while request volume stays flat and the database pool reaches its limit. How do you distinguish slow queries from queueing and prevent a retry cascade?", signals: ["pool wait time", "Little's Law", "bounded concurrency", "deadline"], answer: "Measure pool acquisition wait separately from query execution, size concurrency to database capacity, propagate deadlines, bound queues, and shed or defer work before workers are exhausted.", failure: "Increasing pool size can overload the database and amplify lock contention rather than increase throughput.", validate: "Compare pool wait, active connections, query latency, lock waits, and p95/p99 latency during a controlled load test." },
        { title: "Background jobs and exactly-once effects", prompt: "Design a retryable background job pipeline where workers may crash after a side effect but before acknowledging the message.", signals: ["at-least-once", "idempotent handler", "outbox", "deduplication"], answer: "Assume at-least-once delivery. Use durable job state, idempotent effects or a transactional outbox, explicit retry limits, and a dead-letter path with replay controls.", failure: "Acknowledging before committing loses work; committing before acknowledgment can repeat the side effect after a crash.", validate: "Inject crashes at each boundary between claim, commit, and acknowledgment, then verify one logical effect and observable replay." },
        { title: "Backend observability and SLO diagnosis", prompt: "A service meets its average-latency target but users report sporadic slowness. What would you instrument and how would you use it to find the cause?", signals: ["histograms", "trace correlation", "tail latency", "error budget"], answer: "Use histograms for latency distributions, request traces across dependencies, structured error classes, and service-level indicators segmented by endpoint and dependency.", failure: "Averages hide long tails, while high-cardinality labels can make telemetry expensive or unusable.", validate: "Correlate p95/p99 and error-budget burn with traces, saturation, and deployment markers; alert on sustained user-impacting burn." }
      ],
      frontend: [
        { title: "React state ownership and render boundaries", prompt: "A single keystroke rerenders a large page and causes visible jank. How do you find the source and choose a safe state boundary?", signals: ["React Profiler", "state locality", "memoization", "render cost"], answer: "Profile commits first, move rapidly changing state closer to its consumers, split expensive subtrees, and memoize only where measured props stay stable.", failure: "Adding memoization everywhere can obscure data flow and fail when object/function identities change on every render.", validate: "Compare commit duration and interaction latency in a production-like profile before and after the change." },
        { title: "Accessible interaction and keyboard behavior", prompt: "How would you build an accessible custom menu or dialog and verify it without relying on visual inspection alone?", signals: ["semantic HTML", "keyboard navigation", "focus management", "screen reader"], answer: "Prefer native semantics; implement predictable tab order, Escape/arrow behavior, visible focus, labeling, and focus restoration when a dialog closes.", failure: "A visually correct control built from generic divs may be unreachable or lack role/state announcements for assistive technology.", validate: "Test keyboard-only flows, automated accessibility checks, and a screen reader on supported browsers." },
        { title: "Frontend data fetching and stale responses", prompt: "A user changes filters quickly and an older request returns last, replacing the newer results. How would you prevent stale UI state?", signals: ["request cancellation", "sequence token", "race condition", "loading state"], answer: "Associate results with the active query key, cancel obsolete requests where supported, and ignore responses whose request identity no longer matches current state.", failure: "Cancellation alone is not sufficient if a response already completed or the data source ignores abort signals.", validate: "Test deliberately reordered responses, rapid navigation, retries, and unmount during a request." },
        { title: "Web performance and asset strategy", prompt: "A page is slow on mobile despite acceptable server response time. How do you identify and improve the dominant client-side costs?", signals: ["Core Web Vitals", "bundle analysis", "LCP", "code splitting"], answer: "Measure field and lab Core Web Vitals, inspect long tasks and bundle composition, prioritize critical content, defer non-critical code, and optimize image/font delivery.", failure: "Code splitting can increase waterfalls; aggressively lazy-loading above-the-fold assets can worsen LCP.", validate: "Compare representative device/network profiles and field metrics by route before and after each change." },
        { title: "Frontend testing strategy", prompt: "How do you test a critical checkout or onboarding flow so tests catch user-visible regressions but remain reliable?", signals: ["unit tests", "integration tests", "accessibility", "end-to-end"], answer: "Test pure logic in unit tests, key component interactions at integration level, and only high-value user journeys end to end; assert outcomes rather than implementation details.", failure: "Brittle selectors, shared mutable test data, and over-mocking can make a green suite disagree with real behavior.", validate: "Run deterministic fixtures, accessibility assertions, browser coverage on critical paths, and track flaky-test rates." }
      ],
      ml_systems: [
        { title: "GPU memory budgeting for model serving", prompt: "How do you estimate whether a model-serving workload fits on a GPU before deployment, including activations and concurrent requests?", signals: ["weights", "KV cache", "activation memory", "headroom"], answer: "Budget weights, runtime/graph overhead, activations, and per-request KV cache; multiply cache cost by active sequence count and reserve headroom for fragmentation and peak shapes.", failure: "Sizing only the model weights ignores context length and concurrency, causing OOMs during realistic traffic.", validate: "Measure peak allocated and reserved memory across worst-case prompts, batch sizes, and prefill/decode phases." },
        { title: "Inference batching and tail latency", prompt: "Throughput improves with larger batches, but time-to-first-token becomes worse. How would you tune serving for both throughput and latency?", signals: ["continuous batching", "TTFT", "inter-token latency", "queueing"], answer: "Use continuous/iteration batching with queue limits, separate prefill and decode costs, and schedule against explicit TTFT and inter-token latency targets.", failure: "An unbounded queue or large static batch can improve aggregate tokens/sec while violating interactive latency objectives.", validate: "Benchmark throughput, TTFT, inter-token latency, and queue time by prompt/output length and concurrency." },
        { title: "Distributed training communication bottlenecks", prompt: "GPU utilization is low during distributed training. How do you determine whether data loading, compute, or collective communication is limiting progress?", signals: ["NCCL", "all-reduce", "input pipeline", "overlap"], answer: "Profile step timelines per rank, inspect input wait and collective time, verify topology/bandwidth, and overlap communication with independent computation where the model permits.", failure: "Optimizing one rank or measuring average GPU utilization can hide a straggler that stalls every synchronization step.", validate: "Compare per-rank traces, step-time distributions, data-loader wait, and scaling efficiency across node counts." },
        { title: "Training-data quality and reproducibility", prompt: "A model metric improves offline but regresses after launch. How do you investigate data leakage, evaluation mismatch, and reproducibility?", signals: ["data leakage", "holdout set", "dataset version", "reproducibility"], answer: "Version datasets and preprocessing, maintain time- or entity-aware holdouts, audit train/eval overlap, and align offline evaluation with production traffic and labels.", failure: "Random splits can leak near-duplicates or future information and create misleading offline gains.", validate: "Re-run evaluation from immutable inputs, slice metrics by cohort, and compare calibration and data freshness in production." },
        { title: "Model-serving rollout and rollback", prompt: "How would you release a new model or inference runtime without exposing all users to a quality or latency regression?", signals: ["canary", "shadow traffic", "quality metrics", "rollback"], answer: "Validate offline, shadow requests where safe, canary by a bounded cohort, compare quality and systems metrics, and keep model/runtime artifacts and routing rollback-ready.", failure: "Comparing only aggregate latency can miss quality regression or a long-tail cohort that receives worse outputs.", validate: "Gate rollout on quality, safety, error, GPU saturation, and latency metrics with minimum sample sizes." }
      ],
      platform: [
        { title: "Kubernetes readiness and graceful termination", prompt: "During deployment, users see dropped requests even though pods remain healthy. Explain how readiness, endpoint removal, and process shutdown should coordinate.", signals: ["readiness probe", "endpoint propagation", "preStop", "connection draining"], answer: "Stop accepting new work, mark the pod unready, allow endpoint propagation, drain existing requests within a bounded grace period, and then exit cleanly.", failure: "Immediate process exit or an unbounded shutdown hook can respectively drop in-flight requests or exceed the termination deadline.", validate: "Exercise rolling deploys under persistent connections and measure termination errors, drain time, and endpoint convergence." },
        { title: "Resource requests, limits, and throttling", prompt: "A container shows CPU throttling and high tail latency despite low average CPU use. What would you inspect before changing its limits?", signals: ["CPU quota", "throttling", "requests and limits", "tail latency"], answer: "Inspect quota-period throttling, request/limit sizing, per-container CPU saturation, concurrency, and scheduling. Match runtime parallelism to effective CPU capacity.", failure: "Raising limits without understanding node contention or runtime worker counts can move the bottleneck and harm neighbors.", validate: "Compare throttled periods, run-queue delay, latency distributions, and node-level saturation through a controlled rollout." },
        { title: "Infrastructure changes and drift control", prompt: "How do you safely apply a large infrastructure change when live resources may have drifted from the declared configuration?", signals: ["plan review", "state", "drift detection", "small batches"], answer: "Refresh and inspect state, review a reproducible plan, separate unrelated changes, apply in small batches, and verify actual service health after each step.", failure: "Blindly applying a stale or broad plan can replace critical resources or hide out-of-band changes.", validate: "Use policy checks, peer review, drift reports, change records, and post-apply service-level checks." },
        { title: "Observability and alert quality", prompt: "On-call is overwhelmed by noisy alerts while a real service degradation was missed. How would you redesign the alerting?", signals: ["user-facing SLI", "burn rate", "actionable alert", "symptom"], answer: "Alert on user-impacting symptoms and fast/slow SLO burn, attach ownership and runbooks, and keep diagnostic signals in dashboards rather than paging on every cause.", failure: "Thresholds on one noisy infrastructure metric create alert fatigue and miss correlated user impact.", validate: "Replay historical incidents against proposed alerts and measure detection time, false pages, and actionable coverage." },
        { title: "Capacity planning and autoscaling", prompt: "Autoscaling adds replicas but request latency keeps increasing. What signals and constraints should drive a better scaling policy?", signals: ["queue depth", "concurrency", "scaling lag", "dependency capacity"], answer: "Scale on a leading workload signal such as queue depth or in-flight work, account for startup/readiness delay, and cap replicas to downstream capacity.", failure: "Scaling on CPU alone can be late for I/O-bound work or overwhelm a constrained database.", validate: "Load-test step changes and bursts while measuring queue age, time-to-capacity, latency, and downstream saturation." }
      ],
      data: [
        { title: "Streaming delivery guarantees and deduplication", prompt: "A consumer processes a record, commits its database write, then crashes before committing the offset. What happens on restart and how should the pipeline behave?", signals: ["at-least-once", "offset commit", "idempotent sink", "deduplication"], answer: "The record is delivered again under at-least-once semantics. Use an idempotent sink or transactional write-plus-offset strategy and preserve event identity for deduplication.", failure: "Committing the offset before the durable sink write loses data; committing later can repeat it.", validate: "Fault-inject crashes between processing, persistence, and offset commit; verify replay safety and lag recovery." },
        { title: "Backfills and late-arriving data", prompt: "How do you backfill a large historical dataset while new events continue arriving and downstream consumers remain online?", signals: ["watermark", "idempotent upsert", "checkpoint", "backfill/live overlap"], answer: "Use bounded, checkpointed ranges, idempotent writes, an explicit source watermark, and a reconciliation phase for data arriving during the backfill.", failure: "An unbounded backfill can starve live work or overwrite newer values with older snapshots.", validate: "Track lag, duplicate and missing keys, write amplification, and parity against a trusted source snapshot." },
        { title: "Schema evolution across producers and consumers", prompt: "A producer wants to rename a field while several independent consumers deploy on different schedules. What rollout sequence avoids data loss?", signals: ["schema registry", "additive change", "dual read/write", "compatibility"], answer: "Introduce a new optional field, update consumers to read both forms, migrate producers to write the new field, measure old-field usage, then remove it after compatibility checks.", failure: "A rename performed in one deploy breaks consumers that still require the old field.", validate: "Enforce schema compatibility in CI and monitor consumer parse failures and field usage throughout migration." },
        { title: "Data quality and pipeline freshness", prompt: "A pipeline is green but downstream reports are wrong or stale. What quality checks should fail the pipeline or alert its owner?", signals: ["freshness", "completeness", "uniqueness", "reconciliation"], answer: "Define freshness, completeness, uniqueness, validity, and reconciliation checks at source and output boundaries with clear ownership and severity.", failure: "A job-success signal alone says nothing about semantic correctness or missing partitions.", validate: "Use sampled source-to-target reconciliation, volume/anomaly checks, freshness SLAs, and alert tests with injected bad data." },
        { title: "Partitioning and hot-key skew", prompt: "One partition lags far behind while the rest of a distributed stream is healthy. How do you diagnose and mitigate skew without breaking ordering?", signals: ["partition key", "hot key", "skew", "ordering"], answer: "Inspect per-partition rates and key distribution; choose a partition key aligned with required ordering, and split hot keys only when the ordering invariant can be preserved.", failure: "Adding partitions does not distribute a single hot key if the same partitioning key remains unchanged.", validate: "Compare per-partition throughput, lag age, key-frequency distribution, and ordering correctness under representative loads." }
      ],
      security: [
        { title: "Threat modeling a new service", prompt: "Before launching a service that stores user data and accepts uploads, how would you prioritize its threat model and security controls?", signals: ["assets and trust boundaries", "attack surface", "abuse cases", "mitigations"], answer: "Identify assets, actors, trust boundaries, entry points, and abuse cases; rank by likelihood and impact, then map concrete preventive and detective controls to each risk.", failure: "A checklist without data flows or ownership misses cross-service trust assumptions and abuse paths.", validate: "Review attack scenarios with engineering, test the highest-risk controls, and revisit the model after architecture changes." },
        { title: "Authorization and tenant isolation", prompt: "How do you prevent an authenticated user from accessing another tenant's records through an API or background job?", signals: ["server-side authorization", "tenant context", "least privilege", "isolation test"], answer: "Derive tenant identity from a trusted server-side principal, enforce authorization at every data access boundary, and carry scoped identity into jobs.", failure: "Trusting a client-supplied tenant ID or relying only on UI filtering enables insecure direct object access.", validate: "Add cross-tenant negative tests for API, exports, caches, and asynchronous workers." },
        { title: "Secret rotation without downtime", prompt: "A production credential may be exposed. How do you rotate it without causing a prolonged outage or leaving stale copies active?", signals: ["revoke", "overlapping credentials", "secret inventory", "audit"], answer: "Identify all consumers, distribute a replacement through the secret manager, support a short overlap if the provider permits, switch consumers, verify use, then revoke the old credential.", failure: "Rotating only the primary service while workers or rollback deployments retain the old secret leaves a compromise window.", validate: "Audit secret access, test rotation in staging, verify no old-key traffic remains, and invalidate leaked credentials." },
        { title: "Input and SSRF boundary defense", prompt: "A backend fetches URLs supplied by users. How would you prevent SSRF, including redirects and DNS rebinding cases?", signals: ["allowlist", "DNS resolution", "redirect validation", "egress controls"], answer: "Prefer an allowlist of destinations; validate resolved IPs against private/reserved ranges on each redirect, constrain protocols and ports, and enforce network egress controls.", failure: "Checking only the initial hostname allows redirects or DNS changes to reach internal metadata and control-plane endpoints.", validate: "Test redirects, IPv4/IPv6 encodings, DNS changes, unusual ports, and blocked network ranges." },
        { title: "Incident response and evidence handling", prompt: "You suspect a production service account was compromised. What are your first actions, and how do you preserve evidence while containing risk?", signals: ["containment", "credential revocation", "audit trail", "scope"], answer: "Use the incident process, revoke or constrain credentials, isolate affected access paths, preserve logs and timelines, determine scope, and communicate with accountable responders.", failure: "Deleting resources or rotating without preserving audit evidence can obscure impact and impede investigation.", validate: "Confirm containment with access logs, enumerate affected identities and data, document actions, and track follow-up remediation." }
      ],
      systems: [
        { title: "Memory ownership and lifetime safety", prompt: "A buffer is shared between asynchronous tasks and occasionally becomes invalid after the originating request ends. How would you reason about lifetime and ownership?", signals: ["ownership", "lifetime", "shared ownership", "borrow boundary"], answer: "Make the owner and lifetime explicit, transfer ownership when a task outlives the request, or use a carefully scoped shared owner with synchronization.", failure: "A borrowed view into request-local storage cannot safely outlive its backing allocation, even if it appears to work in light testing.", validate: "Exercise cancellation and delayed task completion under sanitizers or language-specific lifetime checks." },
        { title: "Concurrency correctness and lock contention", prompt: "A multithreaded service has rare corrupt state and high lock wait time. How do you separate correctness bugs from performance contention?", signals: ["invariant", "race detector", "lock ordering", "contention profile"], answer: "Write down the invariant and ownership model, use race/concurrency tooling to find unsafe access, then profile lock wait and critical-section duration before changing synchronization.", failure: "Replacing a mutex with atomics without a memory-order proof can preserve the race while making it harder to diagnose.", validate: "Stress adversarial schedules, run race detection, and benchmark contention with realistic data and thread counts." },
        { title: "Profiling CPU and memory regressions", prompt: "A release increases CPU and memory use but request volume is unchanged. What sequence of measurements helps isolate the regression?", signals: ["flamegraph", "allocation profile", "baseline", "regression"], answer: "Compare equivalent workloads and builds, inspect CPU and allocation profiles, identify changed hot paths, and validate one controlled optimization at a time.", failure: "Sampling unlike workloads or relying on aggregate host metrics can point to the wrong component.", validate: "Record repeatable benchmarks, confidence ranges, p95 latency, allocation rate, and peak resident memory." },
        { title: "System call and I/O bottlenecks", prompt: "A file-processing worker has low CPU utilization but poor throughput. How would you find whether syscalls, storage, or queueing is limiting it?", signals: ["I/O wait", "syscall tracing", "batching", "queue depth"], answer: "Measure time in I/O wait and syscall counts/latency, inspect device queue depth and access pattern, then evaluate bounded batching or asynchronous I/O where it fits.", failure: "Increasing concurrency can deepen a saturated I/O queue and worsen tail latency without increasing device throughput.", validate: "Compare throughput and latency at controlled queue depths, including cold-cache and steady-state runs." },
        { title: "ABI and binary compatibility", prompt: "A shared native library changes a public struct or symbol. How do you avoid breaking downstream binaries that cannot be rebuilt immediately?", signals: ["ABI", "symbol versioning", "layout", "compatibility"], answer: "Preserve exported layouts and symbols where required, add versioned entry points or opaque handles, and document the compatibility contract.", failure: "Changing struct size or ownership conventions can corrupt memory even when source-level tests pass.", validate: "Run ABI diff tooling and compatibility tests against previously released clients and supported platforms." }
      ],
      distributed: [
        { title: "Consistency guarantees and client expectations", prompt: "A product asks for globally available reads and writes but also expects every read to reflect the latest completed write. How do you explain and design the trade-off?", signals: ["linearizability", "replica lag", "quorum", "consistency contract"], answer: "Clarify the required consistency boundary; linearizable reads need coordination or a valid lease/quorum proof, while weaker reads can use replicas with explicit staleness semantics.", failure: "Serving locally from a stale replica while advertising read-after-write consistency violates the client contract.", validate: "Test writes followed by reads across regions, partitions, leader changes, and replica lag." },
        { title: "Partition recovery and reconciliation", prompt: "Two regions accept updates during a network partition. How should the system reconcile them when connectivity returns?", signals: ["conflict resolution", "versioning", "idempotent replay", "business invariant"], answer: "Define the conflict policy before deployment—single-writer, versioned merge, or explicit conflict resolution—and make replay idempotent with durable causal/version metadata.", failure: "Last-write-wins based only on unsynchronized wall clocks can discard valid updates or violate domain invariants.", validate: "Simulate partitions, duplicate/reordered replay, and concurrent updates against business-level invariants." },
        { title: "Retry budgets and cascading failure", prompt: "A downstream service slows down, and callers begin retrying aggressively. How do you prevent retries from turning a partial outage into a system-wide one?", signals: ["retry budget", "exponential backoff", "jitter", "deadline propagation"], answer: "Set bounded deadlines and retry budgets, use exponential backoff with jitter, retry only safe operations, and shed load or trip circuit breakers when capacity is exhausted.", failure: "Retries without an overall deadline multiply traffic exactly when the dependency has least spare capacity.", validate: "Inject latency and errors, then measure retry amplification, queue depth, recovery time, and successful user requests." },
        { title: "Multi-region failover and failback", prompt: "A region is isolated and traffic fails over. What must be true before routing traffic back after the region recovers?", signals: ["fencing", "replication lag", "failback", "split brain"], answer: "Fence the old writer, verify data replication and ownership epochs, reconcile divergent writes, and shift traffic gradually with health and consistency checks.", failure: "Routing back before confirming writer ownership can create two active writers and divergent state.", validate: "Run game days covering isolation, promotion, stale-node rejoin, and staged failback with measured data loss and recovery objectives." },
        { title: "Distributed tracing and request causality", prompt: "A request fans out to many services and becomes slow only for a subset of users. How do you trace causality without overloading telemetry storage?", signals: ["trace context", "critical path", "sampling", "high-cardinality"], answer: "Propagate trace context across async boundaries, inspect critical-path spans, and use tail-based or error-aware sampling to retain slow and failing requests.", failure: "Breaking trace context at queues makes asynchronous work appear unrelated; excessive high-cardinality tags inflate telemetry cost.", validate: "Verify trace continuity through retries and queues, sampling coverage for slow requests, and end-to-end latency attribution." }
      ]
    };

    const JOB_CATEGORIES = {
      backend: {
        label: "Backend Engineer",
        description: "APIs, databases, caching, runtime behavior, and service reliability.",
        questionKeys: ["postgresql_mvcc", "redis_internals", "golang_runtime", "kafka_streaming", "distributed_consensus_transactions", "networking_grpc_security"],
        keywords: ["Go", "Java", "Python", "REST APIs", "SQL", "distributed systems", "caching", "Kafka", "microservices"]
      },
      frontend: {
        label: "Frontend Engineer",
        description: "Browser rendering, React behavior, TypeScript, performance, and web application architecture.",
        questionKeys: ["react_browser_internals", "typescript_node_internals", "distributed_consensus_transactions", "networking_grpc_security"],
        keywords: ["React", "TypeScript", "JavaScript", "accessibility", "web performance", "CSS", "design systems", "browser", "testing"]
      },
      ml_systems: {
        label: "AI / ML Systems Engineer",
        description: "GPU memory and compute, LLM inference, distributed training, and ML serving.",
        questionKeys: ["llm_gpu_systems", "distributed_consensus_transactions", "lsm_rocksdb_storage"],
        keywords: ["Python", "PyTorch", "CUDA", "TensorFlow", "Triton", "inference", "LLM", "distributed training", "GPU"]
      },
      platform: {
        label: "Cloud / Platform Engineer",
        description: "Kubernetes, Linux, cloud infrastructure, networking, and production operations.",
        questionKeys: ["kubernetes_linux_kernel", "distributed_consensus_transactions", "networking_grpc_security", "golang_runtime"],
        keywords: ["Kubernetes", "AWS", "Terraform", "Linux", "Docker", "observability", "SRE", "networking", "CI/CD"]
      },
      data: {
        label: "Data Infrastructure Engineer",
        description: "Streaming pipelines, event delivery, storage engines, and data processing reliability.",
        questionKeys: ["kafka_streaming", "lsm_rocksdb_storage", "postgresql_mvcc", "distributed_consensus_transactions"],
        keywords: ["SQL", "Kafka", "Spark", "Airflow", "dbt", "ETL", "warehouse", "data modeling", "orchestration"]
      },
      security: {
        label: "Security Engineer",
        description: "Identity, transport security, threat modeling, and secure networked services.",
        questionKeys: ["networking_grpc_security", "distributed_consensus_transactions", "kubernetes_linux_kernel"],
        keywords: ["security", "threat modeling", "IAM", "OAuth", "TLS", "encryption", "incident response", "penetration testing", "compliance"]
      },
      systems: {
        label: "Systems Engineer",
        description: "Systems programming, memory models, CPU behavior, concurrency, and runtime performance.",
        questionKeys: ["rust_cpp_memory_concurrency", "golang_runtime", "kubernetes_linux_kernel", "networking_grpc_security"],
        keywords: ["C++", "Rust", "Linux", "kernel", "concurrency", "memory", "networking", "performance", "compilers"]
      },
      distributed: {
        label: "Distributed Systems Engineer",
        description: "Consensus, replication, consistency, fault tolerance, and multi-region system design.",
        questionKeys: ["distributed_consensus_transactions", "kafka_streaming", "postgresql_mvcc", "networking_grpc_security"],
        keywords: ["consensus", "replication", "fault tolerance", "distributed systems", "availability", "consistency", "sharding", "event-driven"]
      }
    };

    function decompileResumeAndGenerateQuestions(rawText) {
      const lines = rawText
        .split(/\r?\n/)
        .map(sourceLine => ({
          text: sourceLine.replace(/^[•\-\*\u2022\s]+/, "").trim(),
          isBullet: /^\s*[•\-\*\u2022]\s+/.test(sourceLine)
        }))
        .filter(line => line.text.length > 22 || line.isBullet);

      // 1. Detect technologies mentioned in the resume
      const detectedTechs = [];
      TECH_DICTIONARY.forEach(t => {
        if (t.patterns.some(rx => rx.test(rawText))) {
          detectedTechs.push(t);
        }
      });

      // 2. Keep all resume bullets and other high-signal experience lines.
      const actionVerbRx = /\b(architected|designed|built|scaled|reduced|optimized|migrated|implemented|engineered|led|eliminated|tuned|resolved|orchestrated|deployed|wrote)\b/i;
      const metricRx = /(\d+(\.\d+)?\s*(%|ms|s|x|k|m|b|tb|gb|mb|rps|tps|qps|fps|nodes|gpus|brokers|users|cores|requests?\s*(?:per|\/)\s*(?:second|sec|day|week|month|year)))/i;

      const claims = [];
      lines.forEach(({ text: line, isBullet }) => {
        const isHeader = /^[A-Z\s—\-|0-9()]{8,}$/.test(line) && !metricRx.test(line);
        if (isHeader) return;
        const hasMetric = metricRx.test(line);
        const hasSkill = TECH_DICTIONARY.some(tech => tech.patterns.some(pattern => pattern.test(line)));
        const hasVerb = actionVerbRx.test(line);
        if (isBullet || hasMetric || hasVerb || hasSkill || line.length > 70) {
          let vector = "ARCHITECTURAL TRADEOFF";
          if (hasMetric) vector = "METRIC & TAIL-LATENCY AUDIT";
          else if (/\b(migrated|replaced|refactored)\b/i.test(line)) vector = "MIGRATION & ROLLBACK PROOF";
          else if (/\b(concurrency|lock|async|thread|goroutine|stream)\b/i.test(line)) vector = "CONCURRENCY INVARIANT";
          claims.push({
            id: `CLM-${String(claims.length + 1).padStart(2, "0")}`,
            text: line,
            hasMetric,
            vector
          });
        }
      });

      if (claims.length === 0 && lines.length > 0) {
        lines.slice(0, 5).forEach(({ text: l }, i) => {
          claims.push({
            id: `CLM-0${i + 1}`,
            text: l,
            hasMetric: false,
            vector: "TECHNICAL DEPTH PROBE"
          });
        });
      }

      // 3. Match Knowledge Base Deep Questions to specific Resume Claims
      const generatedQuestions = [];
      const selectedCategory = JOB_CATEGORIES[state.jobCategory] || JOB_CATEGORIES.backend;
      TECHNICAL_KNOWLEDGE_BASE.forEach(kb => {
        if (selectedCategory.questionKeys.includes(kb.key)) {
          // Find the best matching verbatim claim from the candidate's resume
          let bestClaimIdx = -1;
          let bestScore = 0;
          claims.forEach((c, cIdx) => {
            const lowerC = c.text.toLowerCase();
            let hits = 0;
            kb.matchKeywords.forEach(kw => {
              if (lowerC.includes(kw)) hits += 2;
            });
            if (hits > bestScore) {
              bestScore = hits;
              bestClaimIdx = cIdx;
            }
          });

          const boundClaim = bestClaimIdx >= 0
            ? claims[bestClaimIdx].text
            : `Role practice: ${selectedCategory.label}${rawText.trim() ? "" : " (no resume uploaded)"}.`;

          const genericRolePrompt = kb.prompt.replace(
            /Your resume (?:highlights|involves|mentions|states)/gi,
            `As a ${selectedCategory.label}, you work with`
          );
          generatedQuestions.push({
            id: `PRB-${String(generatedQuestions.length + 1).padStart(2, "0")}`,
            domain: kb.domain,
            level: state.seniority,
            claimId: bestClaimIdx >= 0 ? claims[bestClaimIdx].id : "STACK-01",
            boundClaim: boundClaim,
            title: kb.title,
            prompt: bestClaimIdx >= 0 ? kb.prompt : genericRolePrompt,
            intent: kb.intent,
            signals: kb.signals,
            followups: kb.followups,
            mechanism: kb.mechanism,
            failures: kb.failures,
            codeBlueprint: kb.codeBlueprint,
            l4Contrast: kb.l4Contrast,
            l6Contrast: kb.l6Contrast
          });
        }
      });

      // Build a substantial job-specific study bank in addition to stack and resume probes.
      ROLE_TOPIC_DRILLS[state.jobCategory].forEach((topic, index) => {
        const rolePracticeClaim = `Practice track: ${selectedCategory.label} — ${topic.title}.`;
        generatedQuestions.push({
          id: `ROLE-${index + 1}`,
          domain: `${selectedCategory.label.toUpperCase()} PRACTICE`,
          level: state.seniority,
          claimId: "ROLE-01",
          boundClaim: rolePracticeClaim,
          title: topic.title,
          prompt: topic.prompt,
          intent: `Practices a core ${selectedCategory.label} competency with a production-oriented scenario.`,
          signals: topic.signals,
          followups: [
            { level: "FAILURE MODE", q: "What is the most important failure mode or boundary to account for?", a: topic.failure },
            { level: "VALIDATION", q: "How would you verify the design before and after release?", a: topic.validate }
          ],
          mechanism: topic.answer,
          failures: topic.failure,
          codeBlueprint: `Decision: ${topic.answer}\nFailure guard: ${topic.failure}\nVerification: ${topic.validate}`,
          l4Contrast: "Describe the expected behavior and the main system boundary.",
          l6Contrast: `${topic.answer} Account for the failure case and validate the behavior with measurable production signals.`
        });
      });

      // Create an independent deep-dive probe for every detected technology in the resume.
      detectedTechs.forEach(tech => {
        const focus = TECH_INTERVIEW_FOCUS[tech.name];
        if (!focus) return;
        const matchingClaim = claims.find(claim => tech.patterns.some(pattern => pattern.test(claim.text)));
        const signals = [tech.name, ...focus.split(/[,/ ]+/).filter(word => word.length > 4).slice(0, 5)];
        const answer = `For ${tech.name}, explain ${focus}. Tie the decision to the workload and constraints in your own experience, state the invariant you protected, and compare at least one alternative.`;
        const failure = `A design around ${tech.name} can fail when its workload assumptions change: identify saturation, stale state, or unsafe recovery before scaling the same approach further. Bound concurrency, define a fallback, and preserve a tested rollback path.`;
        const validation = `Use a representative workload and compare latency distributions, resource saturation, correctness, and recovery behavior before and after the change. Segment results by traffic shape and test the relevant failure case.`;
        generatedQuestions.push({
          id: `TECH-${tech.name}`,
          domain: "RESUME STACK DEEP DIVE",
          level: state.seniority,
          claimId: matchingClaim ? matchingClaim.id : "STACK-01",
          boundClaim: matchingClaim ? matchingClaim.text : `Technology listed in resume: ${tech.name}.`,
          title: `${tech.name}: internals, trade-offs, and production failure`,
          prompt: `Your resume lists ${tech.name}. Explain ${focus}. Which production constraint shaped your design, what alternative did you reject, and what evidence would make you change that decision?`,
          intent: `Probes hands-on depth for the specific ${tech.name} skill found in your resume.`,
          signals,
          followups: [
            { level: "FAILURE MODE", q: `What workload or failure can invalidate your ${tech.name} design?`, a: failure },
            { level: "VALIDATION", q: `What evidence would show that your ${tech.name} implementation is correct and ready to scale?`, a: validation }
          ],
          mechanism: answer,
          failures: failure,
          codeBlueprint: `Technology: ${tech.name}\nConstraint: ${focus}\nInvariant: state the correctness or availability guarantee\nValidation: measure the workload and failure boundary`,
          l4Contrast: `Name the core ${tech.name} behavior and how you used it.`,
          l6Contrast: `${answer} Include quantified evidence, a rejected alternative, and a failure/recovery plan.`
        });
      });

      // Generate two separate interview drills for every substantive resume claim.
      claims.forEach(claim => {
        const matchedSkills = detectedTechs
          .filter(tech => tech.patterns.some(pattern => pattern.test(claim.text)))
          .map(tech => tech.name);
        const skills = matchedSkills.length ? matchedSkills : [selectedCategory.label];
        const signals = [...skills, ...(claim.hasMetric ? ["baseline", "measurement method", "tail latency"] : ["ownership", "invariant", "trade-off"])];
        const metricMatches = claim.text.match(/\d+(?:,\d+)*(?:\.\d+)?\s*(?:%|ms|s|x|k|m|b|tb|gb|rps|tps|qps|fps|nodes|gpus|brokers|users|cores|requests?\s*(?:per|\/)\s*(?:second|sec|day|week|month|year))?/gi) || [];
        const metricText = metricMatches.slice(0, 3).join(", ") || "the outcome described in this claim";
        const addClaimQuestion = (angle, title, prompt, answer, failure, validation) => {
          generatedQuestions.push({
            id: `CLAIM-${claim.id}-${angle}`,
            domain: claim.hasMetric ? "RESUME METRIC CROSS-EXAMINATION" : "RESUME OWNERSHIP & DESIGN",
            level: state.seniority,
            claimId: claim.id,
            boundClaim: claim.text,
            title: `${title} — ${claim.id}`,
            prompt,
            intent: "Cross-examines this specific resume statement for hands-on ownership, technical reasoning, and verifiable results.",
            signals,
            followups: [
              { level: "FAILURE MODE", q: "What would make this result regress or the design fail at higher load?", a: failure },
              { level: "VALIDATION", q: "How did you distinguish the effect of your change from noise or other releases?", a: validation }
            ],
            mechanism: answer,
            failures: failure,
            codeBlueprint: `Claim: ${claim.text}\nEvidence: ${validation}\nRisk: ${failure}`,
            l4Contrast: "Describe your direct contribution, the before/after behavior, and one limitation.",
            l6Contrast: `${answer} Quantify the evidence, explain the trade-off, and state when the design would no longer be appropriate.`
          });
        };

        addClaimQuestion(
          "MECHANISM",
          "Technical mechanism and design alternatives",
          `For this resume claim — "${claim.text}" — explain how the system or change works end to end. Which ${skills.join(" / ")} mechanisms mattered, what alternatives did you evaluate, and what invariant did your design preserve?`,
          `Start from the user or upstream request and trace the data/control path. Explain the ${skills.join(" / ")} behavior you relied on, the bottleneck it addressed, and the correctness or availability invariant preserved. Separate your contribution from surrounding team work.`,
          "Identify the first resource or correctness limit at higher scale, describe the observable symptom, and explain the fallback or rollback that keeps the system safe.",
          "Use a reproducible baseline and a representative workload; compare the relevant latency/throughput distribution and correctness counters, while controlling for traffic mix and concurrent releases."
        );
        addClaimQuestion(
          "EVIDENCE",
          claim.hasMetric ? `Metric proof and experiment design (${metricText})` : "Ownership proof and production validation",
          claim.hasMetric
            ? `Your resume reports ${metricText} in: "${claim.text}". Define the exact numerator, denominator, baseline window, workload, and percentile/measurement source. What changed in the system, and what counter-metric would reveal a regression?`
            : `For "${claim.text}", identify the design decision you personally owned, the strongest alternative you rejected, and how you safely released and validated the change. What would you monitor to detect a regression?`,
          claim.hasMetric
            ? "State the metric definition and measurement source, compare equivalent baseline and post-change traffic, and use merged histograms or a well-defined aggregate for tail latency. Explain the bottleneck shift and identify a counter-metric."
            : "Separate personal ownership from team delivery, state the alternatives and the invariant that selected the design, then describe a staged rollout with observable success and rollback criteria.",
          "Beware of coordinated omission, changing traffic mix, averaged percentiles, selection bias, and a secondary bottleneck that makes the headline metric look better while user experience worsens.",
          "Reproduce the change with an agreed workload and time window, check statistical variability, compare user-facing and resource metrics, and verify correctness plus rollback behavior."
        );
      });

      // Ensure if focusMode filters apply, we keep relevant ones (or all if filter would empty list)
      let filtered = generatedQuestions;
      if (state.focusMode === "CLAIMS") {
        const sub = generatedQuestions.filter(q => q.domain.includes("RESUME") || q.domain.includes("OWNERSHIP"));
        if (sub.length > 0) filtered = sub;
      } else if (state.focusMode === "INTERNALS") {
        const sub = generatedQuestions.filter(q => !q.domain.includes("RESUME"));
        if (sub.length > 0) filtered = sub;
      }

      // Re-number IDs cleanly
      filtered.forEach((q, idx) => {
        q.id = `PRB-${String(idx + 1).padStart(2, "0")}`;
        q.level = state.seniority;
      });

      state.detectedTechs = detectedTechs;
      state.extractedClaims = claims;
      state.questions = filtered;
      if (state.activeQuestionIndex >= state.questions.length) {
        state.activeQuestionIndex = 0;
      }
    }

    // =========================================================================
    // 6. UI RENDERERS ACROSS ALL 5 MODULES
    // =========================================================================
    function updateTopTelemetryAndStats() {
      document.getElementById("stat-claims-count").textContent = String(state.extractedClaims.length);
      document.getElementById("stat-questions-count").textContent = String(state.questions.length);

      let practicedCount = 0;
      let totalScore = 0;
      state.questions.forEach(q => {
        const rec = state.practiceRecords[q.boundClaim + "::" + q.title];
        if (rec && rec.score > 0) {
          practicedCount++;
          totalScore += rec.score;
        }
      });

      document.getElementById("stat-practiced-count").textContent = `${practicedCount} / ${state.questions.length}`;
      const avgScore = practicedCount > 0 ? Math.round(totalScore / practicedCount) : 0;
      document.getElementById("stat-readiness-score").textContent = `${avgScore}%`;
      document.getElementById("ingest-file-badge").textContent = state.sourceLabel;
    }

    function renderDossierView() {
      // 1. Detected Tech Stack Badges
      const badgesContainer = document.getElementById("detected-tech-badges");
      document.getElementById("detected-tech-count").textContent = `${state.detectedTechs.length} detected`;
      document.getElementById("extracted-claim-count").textContent = `${state.extractedClaims.length} claims`;
      badgesContainer.innerHTML = "";
      state.detectedTechs.forEach(t => {
        const span = document.createElement("span");
        span.className = "stamp stamp-cobalt";
        span.textContent = `${t.name} // ${t.domain}`;
        badgesContainer.appendChild(span);
      });

      // 2. Extracted Verbatim Resume Claims Table
      const tbody = document.getElementById("extracted-claims-tbody");
      tbody.innerHTML = "";
      state.extractedClaims.forEach((claim, idx) => {
        const tr = document.createElement("tr");
        const linkedQIdx = state.questions.findIndex(q => q.boundClaim === claim.text);
        const targetIdx = linkedQIdx >= 0 ? linkedQIdx : (idx % Math.max(1, state.questions.length));

        tr.innerHTML = `
          <td class="font-mono-tech" style="font-weight: 700;">${escapeHtml(claim.id)}</td>
          <td style="font-size: 13px;">${escapeHtml(claim.text)}</td>
          <td><span class="stamp ${claim.hasMetric ? 'stamp-vermilion' : 'stamp-ochre'}">${escapeHtml(claim.vector)}</span></td>
          <td>
            <button type="button" class="btn btn-sm jump-probe-btn" data-qidx="${targetIdx}">
              PROBE &rarr;
            </button>
          </td>
        `;
        tbody.appendChild(tr);
      });

      // Attach listeners to jump buttons
      tbody.querySelectorAll(".jump-probe-btn").forEach(btn => {
        btn.addEventListener("click", () => {
          const qIdx = parseInt(btn.getAttribute("data-qidx") || "0", 10);
          state.activeQuestionIndex = qIdx;
          switchView("interrogation");
        });
      });
      renderATSAnalysis();
      typesetMath(document.getElementById("view-dossier"));
    }

    function getQuestionRecordKey(q) {
      return q.boundClaim + "::" + q.title;
    }

    function renderInterrogationView() {
      if (state.questions.length === 0) return;
      const filterText = (document.getElementById("queue-search-input").value || "").toLowerCase();
      const queueList = document.getElementById("interrogation-queue-list");
      queueList.innerHTML = "";

      state.questions.forEach((q, idx) => {
        const searchableQuestion = `${q.title} ${q.domain} ${q.boundClaim} ${q.prompt} ${q.signals.join(" ")}`.toLowerCase();
        if (filterText && !searchableQuestion.includes(filterText)) {
          return;
        }
        const rec = state.practiceRecords[getQuestionRecordKey(q)];
        let statusTag = "UNPRACTICED";
        if (rec && rec.status === "mastered") statusTag = "MASTERED [L6]";
        else if (rec && rec.status === "solid") statusTag = "SOLID [L5]";
        else if (rec && rec.status === "review") statusTag = "REVIEW";

        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = "q-index-item" + (idx === state.activeQuestionIndex ? " active" : "");
        btn.innerHTML = `
          <div class="q-index-meta">
            <span>${escapeHtml(q.id)} // ${escapeHtml(q.domain.split(" ")[0])}</span>
            <span>[${statusTag}]</span>
          </div>
          <div class="q-index-item-title" style="font-weight: 600; font-size: 13px; line-height: 1.35;">
            ${escapeHtml(q.title)}
          </div>
        `;
        btn.addEventListener("click", () => {
          state.activeQuestionIndex = idx;
          renderInterrogationView();
        });
        queueList.appendChild(btn);
      });

      // Render active question details
      const activeQ = state.questions[state.activeQuestionIndex] || state.questions[0];
      document.getElementById("queue-progress-badge").textContent = `${state.activeQuestionIndex + 1} / ${state.questions.length}`;
      document.getElementById("active-q-id").textContent = activeQ.id;
      document.getElementById("active-q-domain").textContent = activeQ.domain;
      document.getElementById("active-q-level").textContent = `CALIBRATION: ${activeQ.level}`;
      document.getElementById("active-q-claim").textContent = `"${activeQ.boundClaim}"`;
      document.getElementById("active-q-claim-label").textContent = activeQ.claimId === "STACK-01"
        ? "ROLE PRACTICE TRACK:"
        : "SOURCE ARTIFACT FROM YOUR RESUME:";
      document.getElementById("active-q-title").textContent = activeQ.title;
      document.getElementById("active-q-prompt").textContent = activeQ.prompt;
      document.getElementById("active-q-intent").textContent = activeQ.intent;

      // Render 3-level escalating follow-up probes
      const followupsContainer = document.getElementById("active-q-followups");
      followupsContainer.innerHTML = "";
      activeQ.followups.forEach((f, fIdx) => {
        const stepDiv = document.createElement("div");
        stepDiv.className = "probe-step";
        stepDiv.innerHTML = `
          <button type="button" class="probe-step-header">
            <span>${escapeHtml(f.level)}: ${escapeHtml(f.q)}</span>
            <span class="probe-toggle-indicator">${fIdx === 0 ? "[-]" : "[+]"}</span>
          </button>
          <div class="probe-step-body">
            <div class="font-mono-tech" style="font-size: 11px; font-weight: 700; color: var(--accent-forest); margin-bottom: 4px;">
              [CANONICAL FOLLOW-UP RESOLUTION]
            </div>
            <div style="line-height: 1.6;">${escapeHtml(f.a)}</div>
          </div>
        `;
        const headerBtn = stepDiv.querySelector(".probe-step-header");
        const indicator = stepDiv.querySelector(".probe-toggle-indicator");
        headerBtn.addEventListener("click", () => {
          stepDiv.classList.toggle("open");
          indicator.textContent = stepDiv.classList.contains("open") ? "[-]" : "[+]";
        });
        followupsContainer.appendChild(stepDiv);
      });

      // Populate saved answer draft if any
      const recKey = getQuestionRecordKey(activeQ);
      const rec = state.practiceRecords[recKey];
      const answerInput = document.getElementById("candidate-answer-input");
      answerInput.value = rec && rec.draft ? rec.draft : "";

      // Populate Reference Answer Panel
      document.getElementById("ref-mechanism").textContent = activeQ.mechanism;
      document.getElementById("ref-failures").textContent = activeQ.failures;
      document.getElementById("ref-code").textContent = activeQ.codeBlueprint;
      document.getElementById("ref-l4-contrast").textContent = activeQ.l4Contrast;
      document.getElementById("ref-l6-contrast").textContent = activeQ.l6Contrast;

      // Hide evaluation & reference panels until requested (or show evaluation if already graded)
      const evalPanel = document.getElementById("evaluation-result-panel");
      if (rec && rec.evaluated) {
        renderEvaluationPanel(activeQ, rec);
      } else {
        evalPanel.classList.add("hidden");
      }
      document.getElementById("reference-answer-panel").classList.add("hidden");
      document.getElementById("btn-toggle-reference").textContent = "REVEAL COMPLETE REFERENCE ANSWER & BLUEPRINT";
      typesetMath(document.getElementById("view-interrogation"));
    }

    function evaluateCandidateAnswer() {
      const activeQ = state.questions[state.activeQuestionIndex];
      if (!activeQ) return;
      const draft = document.getElementById("candidate-answer-input").value.trim();
      if (!draft) {
        showToast("WRITE OR DICTATE YOUR TECHNICAL RESPONSE FIRST BEFORE EVALUATING.");
        return;
      }

      const lowerDraft = draft.toLowerCase();
      const hits = [];
      const missed = [];

      activeQ.signals.forEach(sig => {
        const tokens = sig.toLowerCase().split(/[\s\/\(\)\-]+/).filter(t => t.length >= 2);
        const matched = tokens.some(tok => lowerDraft.includes(tok));
        if (matched) hits.push(sig);
        else missed.push(sig);
      });

      // Compute depth score from signal coverage + structural depth (length, technical terms, trade-off markers)
      const signalRatio = activeQ.signals.length > 0 ? (hits.length / activeQ.signals.length) : 0.5;
      const wordCount = draft.split(/\s+/).length;
      const lengthFactor = Math.min(1, wordCount / 65);
      const rawScore = Math.round((signalRatio * 75) + (lengthFactor * 25));
      const finalScore = Math.max(18, Math.min(99, rawScore));

      let status = "review";
      if (finalScore >= 80) status = "mastered";
      else if (finalScore >= 55) status = "solid";

      const recKey = getQuestionRecordKey(activeQ);
      state.practiceRecords[recKey] = {
        draft,
        evaluated: true,
        score: finalScore,
        status,
        signalsHit: hits,
        signalsMissed: missed,
        timestamp: new Date().toISOString()
      };

      savePersistedState();
      updateTopTelemetryAndStats();
      renderEvaluationPanel(activeQ, state.practiceRecords[recKey]);
      renderInterrogationView();
      showToast(`EVALUATION COMPLETE: ${finalScore}% SIGNAL COVERAGE RECORDED.`);
    }

    function renderEvaluationPanel(activeQ, rec) {
      const panel = document.getElementById("evaluation-result-panel");
      panel.classList.remove("hidden");

      const scoreBadge = document.getElementById("eval-score-badge");
      scoreBadge.textContent = `SIGNAL DEPTH: ${rec.score}%`;
      scoreBadge.className = "stamp " + (rec.score >= 80 ? "stamp-forest" : (rec.score >= 55 ? "stamp-cobalt" : "stamp-vermilion"));

      const headline = document.getElementById("eval-verdict-headline");
      if (rec.score >= 80) {
        headline.textContent = "Staff-Level Technical Depth Verified (Strong L6 Signal)";
      } else if (rec.score >= 55) {
        headline.textContent = "Production Solid Mechanism — Expand on Edge Cases & Internals for L6";
      } else {
        headline.textContent = "Surface-Level Explanation — Missing Critical Under-the-Hood Mechanics";
      }

      const hitContainer = document.getElementById("eval-signals-hit");
      hitContainer.innerHTML = "";
      if (rec.signalsHit && rec.signalsHit.length > 0) {
        rec.signalsHit.forEach(s => {
          const sp = document.createElement("span");
          sp.className = "stamp stamp-forest";
          sp.textContent = `+ ${s}`;
          hitContainer.appendChild(sp);
        });
      } else {
        hitContainer.innerHTML = `<span style="font-size: 12px; color: var(--ink-muted);">No specific internal signal terms detected yet.</span>`;
      }

      const missContainer = document.getElementById("eval-signals-missed");
      missContainer.innerHTML = "";
      if (rec.signalsMissed && rec.signalsMissed.length > 0) {
        rec.signalsMissed.forEach(s => {
          const sp = document.createElement("span");
          sp.className = "stamp stamp-vermilion";
          sp.textContent = `- ${s}`;
          missContainer.appendChild(sp);
        });
      } else {
        missContainer.innerHTML = `<span class="stamp stamp-forest">ALL CORE SIGNALS COVERED</span>`;
      }

      const notesEl = document.getElementById("eval-feedback-notes");
      notesEl.textContent = rec.signalsMissed && rec.signalsMissed.length > 0
        ? `Interviewer Pushback: To elevate this answer to an unequivocal L6 Strong Hire, explicitly incorporate [${rec.signalsMissed.slice(0, 4).join(", ")}] and click 'REVEAL COMPLETE REFERENCE ANSWER & BLUEPRINT' below to compare your defense against the canonical mechanism and code blueprint.`
        : `Interviewer Calibration: Your response hits the primary internal mechanisms and failure modes expected at the Staff bar.`;
    }

    function renderCompendiumView() {
      const searchVal = (document.getElementById("compendium-search").value || "").toLowerCase();
      const domainFilter = document.getElementById("compendium-domain-filter").value;
      const statusFilter = document.getElementById("compendium-status-filter").value;

      // Populate domain dropdown options dynamically
      const domainSelect = document.getElementById("compendium-domain-filter");
      const uniqueDomains = Array.from(new Set(state.questions.map(q => q.domain)));
      const prevDomainVal = domainSelect.value;
      domainSelect.innerHTML = `<option value="ALL">All Domains (${state.questions.length})</option>`;
      uniqueDomains.forEach(d => {
        const opt = document.createElement("option");
        opt.value = d;
        opt.textContent = d;
        domainSelect.appendChild(opt);
      });
      if (uniqueDomains.includes(prevDomainVal)) domainSelect.value = prevDomainVal;

      const container = document.getElementById("compendium-cards-container");
      container.innerHTML = "";

      state.questions.forEach((q, idx) => {
        const rec = state.practiceRecords[getQuestionRecordKey(q)];
        const status = rec ? rec.status : "unpracticed";

        if (domainFilter !== "ALL" && q.domain !== domainFilter) return;
        if (statusFilter !== "ALL" && status !== statusFilter) return;
        if (searchVal) {
          const hay = `${q.title} ${q.domain} ${q.prompt} ${q.mechanism} ${q.failures} ${q.codeBlueprint} ${q.boundClaim}`.toLowerCase();
          if (!hay.includes(searchVal)) return;
        }

        const card = document.createElement("article");
        card.className = "panel compendium-card";
        card.innerHTML = `
          <div class="panel-header">
            <div style="display: flex; align-items: center; gap: 8px; flex-wrap: wrap;">
              <span class="stamp stamp-vermilion">${escapeHtml(q.id)}</span>
              <span class="stamp stamp-cobalt">${escapeHtml(q.domain)}</span>
              <span class="stamp">${escapeHtml(status.toUpperCase())}</span>
            </div>
            <h3 class="compendium-card-title">${escapeHtml(q.title)}</h3>
            <div class="compendium-card-actions">
              <button type="button" class="btn btn-sm compendium-practice-btn" data-idx="${idx}">
                PRACTICE
              </button>
              <button type="button" class="btn btn-sm compendium-toggle-card-btn">
                DETAILS
              </button>
            </div>
          </div>
          <div class="panel-body hidden">
            <p class="compendium-card-prompt">${escapeHtml(q.prompt)}</p>
            <div class="resume-claim-banner" style="margin-bottom: 12px;">
              <span class="font-mono-tech" style="font-size: 10.5px; font-weight: 700; color: var(--accent-vermilion);">BOUND RESUME CLAIM:</span>
              <span class="font-mono-tech" style="font-size: 12px;"> "${escapeHtml(q.boundClaim)}"</span>
            </div>
            <div style="display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 14px;">
              <span class="font-mono-tech" style="font-size: 11px; font-weight: 700; color: var(--ink-muted);">KEY TECHNICAL SIGNALS:</span>
              ${q.signals.map(s => `<span class="stamp">${escapeHtml(s)}</span>`).join("")}
            </div>

            <button type="button" class="btn btn-sm compendium-toggle-ans-btn" style="margin-bottom: 12px;">
              REVEAL ANSWER &amp; FOLLOW-UPS
            </button>
            <div class="compendium-answer-body hidden" style="border-top: 1.5px solid var(--border-strong); padding-top: 14px; display: flex; flex-direction: column; gap: 12px;">
              <div>
                <div class="font-mono-tech" style="font-size: 11px; font-weight: 700; color: var(--accent-cobalt); margin-bottom: 3px;">
                  [01 // CORE MECHANISM &amp; UNDER-THE-HOOD INTERNALS]
                </div>
                <div style="font-size: 14px; line-height: 1.6;">${escapeHtml(q.mechanism)}</div>
              </div>
              <div>
                <div class="font-mono-tech" style="font-size: 11px; font-weight: 700; color: var(--accent-vermilion); margin-bottom: 3px;">
                  [02 // PRODUCTION FAILURE MODES &amp; EDGE CASES]
                </div>
                <div style="font-size: 14px; line-height: 1.6; white-space: pre-line;">${escapeHtml(q.failures)}</div>
              </div>
              <div>
                <div class="font-mono-tech" style="font-size: 11px; font-weight: 700; margin-bottom: 4px;">
                  [03 // FOLLOW-UP ESCALATION LADDER &amp; ANSWERS]
                </div>
                <div style="display: flex; flex-direction: column; gap: 8px;">
                  ${q.followups.map(f => `
                    <div style="border: 1px solid var(--border-subtle); background-color: var(--bg-primary); padding: 10px 12px;">
                      <div class="font-mono-tech" style="font-size: 11.5px; font-weight: 700; margin-bottom: 4px;">${escapeHtml(f.level)}: ${escapeHtml(f.q)}</div>
                      <div style="font-size: 13.5px; color: var(--ink-secondary);">${escapeHtml(f.a)}</div>
                    </div>
                  `).join("")}
                </div>
              </div>
              <div>
                <div class="font-mono-tech" style="font-size: 11px; font-weight: 700; margin-bottom: 4px;">
                  [04 // CODE / PROTOCOL BLUEPRINT]
                </div>
                <pre class="code-blueprint">${escapeHtml(q.codeBlueprint)}</pre>
              </div>
            </div>
          </div>
        `;

        card.querySelector(".compendium-practice-btn").addEventListener("click", () => {
          state.activeQuestionIndex = idx;
          switchView("interrogation");
        });

        const cardBody = card.querySelector(".panel-body");
        card.querySelector(".compendium-toggle-card-btn").addEventListener("click", event => {
          const isHidden = cardBody.classList.toggle("hidden");
          event.currentTarget.textContent = isHidden ? "DETAILS" : "CLOSE";
        });

        const ansBody = card.querySelector(".compendium-answer-body");
        card.querySelector(".compendium-toggle-ans-btn").addEventListener("click", event => {
          const isHidden = ansBody.classList.toggle("hidden");
          event.currentTarget.textContent = isHidden ? "REVEAL ANSWER & FOLLOW-UPS" : "HIDE ANSWER & FOLLOW-UPS";
        });

        container.appendChild(card);
      });
      typesetMath(document.getElementById("view-compendium"));
    }

    function renderStressTestView() {
      const selector = document.getElementById("incident-selector");
      if (selector.options.length === 0) {
        INCIDENT_SCENARIOS.forEach(inc => {
          const opt = document.createElement("option");
          opt.value = inc.id;
          opt.textContent = `${inc.code} — ${inc.title}`;
          selector.appendChild(opt);
        });
      }
      selector.value = state.activeIncidentId;

      const inc = INCIDENT_SCENARIOS.find(i => i.id === state.activeIncidentId) || INCIDENT_SCENARIOS[0];
      document.getElementById("incident-pager-code").textContent = inc.code;
      document.getElementById("incident-stack-tag").textContent = inc.stack;
      document.getElementById("incident-title").textContent = inc.title;
      document.getElementById("incident-symptoms").textContent = inc.symptoms;
      document.getElementById("incident-telemetry-dump").textContent = inc.telemetry;

      const optionsList = document.getElementById("incident-options-list");
      optionsList.innerHTML = "";
      const postmortemBox = document.getElementById("incident-postmortem-box");
      postmortemBox.classList.add("hidden");

      inc.options.forEach(opt => {
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = "btn";
        btn.style.textAlign = "left";
        btn.style.justifyContent = "flex-start";
        btn.style.textTransform = "none";
        btn.style.fontFamily = "'IBM Plex Sans', sans-serif";
        btn.style.fontSize = "13.5px";
        btn.textContent = opt.label;
        btn.addEventListener("click", () => {
          postmortemBox.classList.remove("hidden");
          const verdictEl = document.getElementById("incident-choice-verdict");
          verdictEl.textContent = opt.verdict;
          verdictEl.style.color = opt.correct ? "var(--accent-forest)" : "var(--accent-vermilion)";
          document.getElementById("incident-root-cause").textContent = opt.explanation;
          typesetMath(document.getElementById("view-stresstest"));
        });
        optionsList.appendChild(btn);
      });

      computeCapacityEstimates();
      typesetMath(document.getElementById("view-stresstest"));
    }

    function computeCapacityEstimates() {
      const dau = parseFloat(document.getElementById("calc-dau").value) || 1000000;
      const writesPerUser = parseFloat(document.getElementById("calc-writes-per-user").value) || 10;
      const readsPerUser = parseFloat(document.getElementById("calc-reads-per-user").value) || 50;
      const payloadBytes = parseFloat(document.getElementById("calc-payload-bytes").value) || 1024;
      const peakMult = parseFloat(document.getElementById("calc-peak-multiplier").value) || 3;
      const cacheRatio = (parseFloat(document.getElementById("calc-cache-ratio").value) || 20) / 100;

      const totalDailyWrites = dau * writesPerUser;
      const totalDailyReads = dau * readsPerUser;
      const avgWriteQps = totalDailyWrites / 86400;
      const peakWriteQps = avgWriteQps * peakMult;
      const avgReadQps = totalDailyReads / 86400;
      const peakReadQps = avgReadQps * peakMult;

      const dailyStorageBytes = totalDailyWrites * payloadBytes;
      const dailyStorageGB = dailyStorageBytes / (1024 ** 3);
      const yearlyStorageTB = (dailyStorageGB * 365 * 3) / 1024; // With 3x replication factor
      const hotCacheRAMGB = dailyStorageGB * cacheRatio * 1.35; // +35% hash table pointer overhead
      const peakIngressMBps = (peakWriteQps * payloadBytes) / (1024 ** 2);

      const tbody = document.getElementById("capacity-results-tbody");
      tbody.innerHTML = `
        <tr>
          <td class="font-mono-tech">Write Throughput (Avg / Peak)</td>
          <td class="font-mono-tech" style="font-weight: 700;">${Math.round(avgWriteQps).toLocaleString()} / ${Math.round(peakWriteQps).toLocaleString()} TPS</td>
          <td>${peakWriteQps > 15000 ? "Exceeds single primary WAL fsync limit; partition across shards + Kafka buffer" : "Fits single primary with NVMe group-commit WAL"}</td>
        </tr>
        <tr>
          <td class="font-mono-tech">Read Throughput (Avg / Peak)</td>
          <td class="font-mono-tech" style="font-weight: 700;">${Math.round(avgReadQps).toLocaleString()} / ${Math.round(peakReadQps).toLocaleString()} QPS</td>
          <td>${peakReadQps > 40000 ? "Requires sharded Redis Cluster + read replicas with singleflight coalescing" : "Serve via read replicas + L1/L2 cache"}</td>
        </tr>
        <tr>
          <td class="font-mono-tech">Daily Raw Storage Ingestion</td>
          <td class="font-mono-tech" style="font-weight: 700;">${dailyStorageGB.toFixed(2)} GB / day</td>
          <td>1-Year Retention (RF=3): <strong>${yearlyStorageTB.toFixed(2)} TB</strong> (plan tiered S3/LSM compaction)</td>
        </tr>
        <tr>
          <td class="font-mono-tech">Hot Working-Set Cache RAM</td>
          <td class="font-mono-tech" style="font-weight: 700;">${hotCacheRAMGB.toFixed(2)} GB DRAM</td>
          <td>Includes 35% Redis dict/SDS allocator overhead for (${Math.round(cacheRatio * 100)}%) hot daily keys</td>
        </tr>
        <tr>
          <td class="font-mono-tech">Peak Network Ingress Bandwidth</td>
          <td class="font-mono-tech" style="font-weight: 700;">${peakIngressMBps.toFixed(2)} MB/s (${(peakIngressMBps * 8).toFixed(1)} Mbps)</td>
          <td>Ensure NIC ring buffer &amp; gRPC HTTP/2 window size match BDP</td>
        </tr>
      `;
    }

    function renderLedgerView() {
      let mastered = 0;
      let solid = 0;
      let review = 0;
      let totalScore = 0;
      let practiced = 0;

      const domainStats = {};
      state.questions.forEach(q => {
        if (!domainStats[q.domain]) {
          domainStats[q.domain] = { total: 0, practiced: 0, scoreSum: 0 };
        }
        domainStats[q.domain].total++;
        const rec = state.practiceRecords[getQuestionRecordKey(q)];
        if (rec) {
          practiced++;
          totalScore += rec.score || 0;
          domainStats[q.domain].practiced++;
          domainStats[q.domain].scoreSum += rec.score || 0;
          if (rec.status === "mastered") mastered++;
          else if (rec.status === "solid") solid++;
          else review++;
        }
      });

      const overallPct = state.questions.length > 0
        ? Math.round((totalScore / (state.questions.length * 100)) * 100)
        : 0;

      document.getElementById("ledger-overall-pct").textContent = `${overallPct}%`;
      document.getElementById("ledger-overall-bar").style.width = `${overallPct}%`;
      document.getElementById("ledger-mastered-count").textContent = String(mastered);
      document.getElementById("ledger-solid-count").textContent = String(solid);
      document.getElementById("ledger-review-count").textContent = String(review);

      const domainTbody = document.getElementById("ledger-domain-tbody");
      domainTbody.innerHTML = "";
      Object.keys(domainStats).forEach(dom => {
        const st = domainStats[dom];
        const avg = st.practiced > 0 ? Math.round(st.scoreSum / st.practiced) : 0;
        const tr = document.createElement("tr");
        tr.innerHTML = `
          <td class="font-mono-tech" style="font-weight: 700;">${escapeHtml(dom)}</td>
          <td class="font-mono-tech">${st.total}</td>
          <td class="font-mono-tech">${st.practiced} / ${st.total}</td>
          <td class="font-mono-tech">${avg}%</td>
          <td><span class="stamp ${avg >= 80 ? 'stamp-forest' : (avg >= 50 ? 'stamp-cobalt' : 'stamp-ochre')}">${avg >= 80 ? "STAFF READY" : (st.practiced > 0 ? "IN PROGRESS" : "UNPRACTICED")}</span></td>
        `;
        domainTbody.appendChild(tr);
      });

      const historyTbody = document.getElementById("ledger-history-tbody");
      historyTbody.innerHTML = "";
      state.questions.forEach((q, idx) => {
        const rec = state.practiceRecords[getQuestionRecordKey(q)];
        const tr = document.createElement("tr");
        tr.innerHTML = `
          <td class="font-mono-tech" style="font-weight: 700;">${escapeHtml(q.id)}</td>
          <td style="font-weight: 600;">${escapeHtml(q.title)}</td>
          <td style="font-size: 12.5px; color: var(--ink-secondary);">${rec && rec.draft ? escapeHtml(rec.draft.slice(0, 180)) + (rec.draft.length > 180 ? "..." : "") : "<em>No saved defense yet</em>"}</td>
          <td><span class="stamp ${rec && rec.score >= 80 ? 'stamp-forest' : (rec ? 'stamp-cobalt' : '')}">${rec ? `${rec.score}% // ${rec.status.toUpperCase()}` : "PENDING"}</span></td>
          <td><button type="button" class="btn btn-sm ledger-open-btn" data-idx="${idx}">OPEN &rarr;</button></td>
        `;
        tr.querySelector(".ledger-open-btn").addEventListener("click", () => {
          state.activeQuestionIndex = idx;
          switchView("interrogation");
        });
        historyTbody.appendChild(tr);
      });
      typesetMath(document.getElementById("view-ledger"));
    }

    // =========================================================================
    // 7. FILE UPLOAD HANDLERS (.PDF, .DOCX, .TXT, .MD)
    // =========================================================================
    async function handleFileUpload(file) {
      if (!file) return;
      const ext = file.name.split(".").pop().toLowerCase();
      document.getElementById("telemetry-status").textContent = `PARSING FILE: ${file.name.toUpperCase()}...`;

      try {
        let extractedText = "";
        if (ext === "pdf" && window.pdfjsLib) {
          window.pdfjsLib.GlobalWorkerOptions.workerSrc = "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js";
          const arrayBuffer = await file.arrayBuffer();
          const pdf = await window.pdfjsLib.getDocument({ data: arrayBuffer }).promise;
          const pageTexts = [];
          for (let i = 1; i <= pdf.numPages; i++) {
            const page = await pdf.getPage(i);
            const content = await page.getTextContent();
            const strings = content.items.map(item => item.str);
            pageTexts.push(strings.join(" "));
          }
          extractedText = pageTexts.join("\n");
        } else if (ext === "docx" && window.mammoth) {
          const arrayBuffer = await file.arrayBuffer();
          const result = await window.mammoth.extractRawText({ arrayBuffer });
          extractedText = result.value;
        } else if (["txt", "md"].includes(ext)) {
          extractedText = await file.text();
        } else if (ext === "pdf" || ext === "docx") {
          throw new Error(`The ${ext.toUpperCase()} parser library is unavailable. Check your connection and retry.`);
        } else {
          throw new Error(`Unsupported file type ".${ext}". Choose PDF, DOCX, TXT, or MD.`);
        }

        if (!extractedText || extractedText.trim().length < 15) {
          throw new Error("Not enough selectable text was extracted. For a scanned PDF, run OCR first or paste the resume text.");
        }

        state.rawResumeText = extractedText.trim();
        state.sourceLabel = `FILE: ${file.name.toUpperCase()}`;
        state.activeQuestionIndex = 0;
        document.getElementById("resume-raw-textarea").value = state.rawResumeText;
        decompileResumeAndGenerateQuestions(state.rawResumeText);
        savePersistedState();
        updateTopTelemetryAndStats();
        renderDossierView();
        renderInterrogationView();
        renderCompendiumView();
        renderLedgerView();
        document.getElementById("telemetry-status").textContent = `PARSED ${file.name.toUpperCase()} // ${state.questions.length} PROBES GENERATED`;
        showToast(`RESUME PARSED: ${state.extractedClaims.length} CLAIMS & ${state.questions.length} ROLE PROBES READY.`);
      } catch (error) {
        console.error("Resume file parsing failed.", error);
        document.getElementById("telemetry-status").textContent = "RESUME PARSE FAILED // SEE MESSAGE";
        showToast(error instanceof Error ? error.message : "Resume parsing failed. Paste the text directly.");
      }
    }

    // =========================================================================
    // 8. NAVIGATION, TIMER, VOICE DICTATION & EXPORT UTILITIES
    // =========================================================================
    function switchView(viewName) {
      state.activeView = viewName;
      document.querySelectorAll(".nav-tab").forEach(tab => {
        tab.classList.toggle("active", tab.getAttribute("data-view") === viewName);
      });
      document.querySelectorAll(".view-section").forEach(sec => {
        sec.classList.toggle("hidden", sec.id !== `view-${viewName}`);
      });

      if (viewName === "dossier") renderDossierView();
      else if (viewName === "interrogation") renderInterrogationView();
      else if (viewName === "compendium") renderCompendiumView();
      else if (viewName === "stresstest") renderStressTestView();
      else if (viewName === "ledger") renderLedgerView();
    }

    function startInterviewTimer() {
      clearInterval(state.timerInterval);
      state.timerInterval = setInterval(() => {
        if (!state.timerRunning) return;
        state.timerSeconds++;
        const mins = String(Math.floor(state.timerSeconds / 60)).padStart(2, "0");
        const secs = String(state.timerSeconds % 60).padStart(2, "0");
        const disp = document.getElementById("interview-timer-display");
        if (disp) disp.textContent = `${mins}:${secs}`;
      }, 1000);
    }

    function exportFullStudyDossierMarkdown() {
      const lines = [
        `# RIGOR // Tailored Technical Interview & Staff Reference Compendium`,
        `Generated from: ${state.sourceLabel} | Role: ${JOB_CATEGORIES[state.jobCategory].label} | Target Bar: ${state.seniority}`,
        ``,
        `## 1. Extracted Resume Claims Audited`,
        ...state.extractedClaims.map(c => `- **[${c.id}] (${c.vector})**: ${c.text}`),
        ``,
        `## 2. Deep Technical Interrogation Questions & Reference Answers`,
        ``
      ];

      state.questions.forEach(q => {
        const rec = state.practiceRecords[getQuestionRecordKey(q)];
        lines.push(`### ${q.id}: ${q.title} [${q.domain}]`);
        lines.push(`> **Bound Resume Claim:** "${q.boundClaim}"`);
        lines.push(``);
        lines.push(`**Primary Question:** ${q.prompt}`);
        lines.push(``);
        lines.push(`**Required Technical Signals:** ${q.signals.join(", ")}`);
        lines.push(``);
        lines.push(`#### Under-the-Hood Mechanism`);
        lines.push(q.mechanism);
        lines.push(``);
        lines.push(`#### Production Failure Modes & Mitigations`);
        lines.push(q.failures);
        lines.push(``);
        lines.push(`#### Escalating Follow-Up Probes`);
        q.followups.forEach(f => {
          lines.push(`- **${f.level} — ${f.q}**`);
          lines.push(`  - *Answer:* ${f.a}`);
        });
        lines.push(``);
        lines.push(`#### Code / Architecture Blueprint`);
        lines.push("```");
        lines.push(q.codeBlueprint);
        lines.push("```");
        if (rec && rec.draft) {
          lines.push(`#### Your Saved Practice Defense (Score: ${rec.score}%)`);
          lines.push(rec.draft);
        }
        lines.push(``);
      });

      const blob = new Blob([lines.join("\n")], { type: "text/markdown;charset=utf-8" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "rigor_technical_interview_compendium.md";
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
      showToast("EXPORTED COMPLETE INTERVIEW & ANSWER COMPENDIUM (.MD)");
    }

    function escapeHtml(str) {
      return String(str || "")
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;");
    }

    // =========================================================================
    // 9. INITIALIZATION & EVENT LISTENERS
    // =========================================================================
    window.addEventListener("DOMContentLoaded", () => {
      loadPersistedState();
      const jobCategorySelect = document.getElementById("select-job-category");
      jobCategorySelect.value = state.jobCategory;
      updateJobCategoryDescription();

      // Theme toggle button
      const themeBtn = document.getElementById("btn-theme-toggle");
      themeBtn.textContent = state.theme === "paper" ? "THEME: ARCHIVAL PAPER" : "THEME: CARBON TERMINAL";
      themeBtn.addEventListener("click", () => {
        state.theme = state.theme === "paper" ? "terminal" : "paper";
        document.documentElement.setAttribute("data-theme", state.theme);
        themeBtn.textContent = state.theme === "paper" ? "THEME: ARCHIVAL PAPER" : "THEME: CARBON TERMINAL";
        savePersistedState();
      });

      initializeJobPreparation();

      // Populate initial textarea and compile
      const rawTextarea = document.getElementById("resume-raw-textarea");
      rawTextarea.value = state.rawResumeText;
      decompileResumeAndGenerateQuestions(state.rawResumeText);
      updateTopTelemetryAndStats();
      renderDossierView();
      renderInterrogationView();
      renderCompendiumView();
      renderStressTestView();
      renderLedgerView();
      startInterviewTimer();
      typesetMath(document.body);

      // Navigation tabs
      document.querySelectorAll(".nav-tab").forEach(tab => {
        tab.addEventListener("click", () => {
          const target = tab.getAttribute("data-view");
          if (target) switchView(target);
        });
      });

      // Dropzone & file input
      const dropzone = document.getElementById("resume-dropzone");
      const fileInput = document.getElementById("resume-file-input");
      dropzone.addEventListener("click", () => fileInput.click());
      dropzone.addEventListener("dragover", e => {
        e.preventDefault();
        dropzone.classList.add("dragover");
      });
      dropzone.addEventListener("dragleave", () => dropzone.classList.remove("dragover"));
      dropzone.addEventListener("drop", e => {
        e.preventDefault();
        dropzone.classList.remove("dragover");
        if (e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0]) {
          handleFileUpload(e.dataTransfer.files[0]);
        }
      });
      fileInput.addEventListener("change", async () => {
        if (fileInput.files && fileInput.files[0]) {
          await handleFileUpload(fileInput.files[0]);
        }
        fileInput.value = "";
      });

      // Clear & Compile Resume Buttons
      document.getElementById("btn-clear-resume").addEventListener("click", () => {
        rawTextarea.value = "";
        state.rawResumeText = "";
        state.sourceLabel = "ROLE-BASED PRACTICE";
        state.activeQuestionIndex = 0;
        decompileResumeAndGenerateQuestions("");
        savePersistedState();
        updateTopTelemetryAndStats();
        renderDossierView();
        renderInterrogationView();
        renderCompendiumView();
        rawTextarea.focus();
      });

      document.getElementById("btn-compile-resume").addEventListener("click", () => {
        const text = rawTextarea.value.trim();
        if (text && text.length < 20) {
          showToast("PASTE AT LEAST 20 CHARACTERS OF RESUME TEXT TO ANALYZE IT.");
          return;
        }
        state.rawResumeText = text;
        state.sourceLabel = text ? "CUSTOM RESUME BUFFER" : "ROLE-BASED PRACTICE";
        state.seniority = document.getElementById("select-seniority").value;
        state.focusMode = document.getElementById("select-focus-mode").value;
        state.activeQuestionIndex = 0;
        decompileResumeAndGenerateQuestions(state.rawResumeText);
        savePersistedState();
        updateTopTelemetryAndStats();
        renderDossierView();
        renderInterrogationView();
        renderCompendiumView();
        showToast(text
          ? `RESUME REVIEW COMPLETE: ${state.extractedClaims.length} CLAIMS & ${state.questions.length} ROLE PROBES READY.`
          : `ROLE PRACTICE READY: ${state.questions.length} ${JOB_CATEGORIES[state.jobCategory].label.toUpperCase()} PROBES.`);
      });

      document.getElementById("select-job-category").addEventListener("change", event => {
        state.jobCategory = event.currentTarget.value;
        state.activeQuestionIndex = 0;
        updateJobCategoryDescription();
        decompileResumeAndGenerateQuestions(state.rawResumeText);
        savePersistedState();
        updateTopTelemetryAndStats();
        renderDossierView();
        renderInterrogationView();
        renderCompendiumView();
      });

      document.getElementById("select-seniority").addEventListener("change", e => {
        state.seniority = e.target.value;
        decompileResumeAndGenerateQuestions(state.rawResumeText);
        updateTopTelemetryAndStats();
        renderDossierView();
        renderInterrogationView();
      });

      document.getElementById("select-focus-mode").addEventListener("change", e => {
        state.focusMode = e.target.value;
        decompileResumeAndGenerateQuestions(state.rawResumeText);
        updateTopTelemetryAndStats();
        renderDossierView();
        renderInterrogationView();
      });

      // Interrogation Room Controls
      document.getElementById("queue-search-input").addEventListener("input", () => {
        renderInterrogationView();
      });

      document.getElementById("btn-timer-toggle").addEventListener("click", e => {
        state.timerRunning = !state.timerRunning;
        e.currentTarget.textContent = state.timerRunning ? "PAUSE" : "RESUME";
      });

      document.getElementById("btn-timer-reset").addEventListener("click", () => {
        state.timerSeconds = 0;
        document.getElementById("interview-timer-display").textContent = "00:00";
      });

      document.getElementById("btn-expand-all-probes").addEventListener("click", () => {
        const steps = document.querySelectorAll("#active-q-followups .probe-step");
        const anyClosed = Array.from(steps).some(s => !s.classList.contains("open"));
        steps.forEach(s => {
          s.classList.toggle("open", anyClosed);
          const ind = s.querySelector(".probe-toggle-indicator");
          if (ind) ind.textContent = anyClosed ? "[-]" : "[+]";
        });
      });

      // Auto-save candidate draft on typing
      document.getElementById("candidate-answer-input").addEventListener("input", e => {
        const activeQ = state.questions[state.activeQuestionIndex];
        if (!activeQ) return;
        const key = getQuestionRecordKey(activeQ);
        const existing = state.practiceRecords[key] || { score: 0, status: "unpracticed", evaluated: false };
        existing.draft = e.target.value;
        state.practiceRecords[key] = existing;
        savePersistedState();
      });

      // Insert Staff Answer Scaffold
      document.getElementById("btn-insert-scaffold").addEventListener("click", () => {
        const activeQ = state.questions[state.activeQuestionIndex];
        if (!activeQ) return;
        const textarea = document.getElementById("candidate-answer-input");
        const scaffold = [
          `1. CORE MECHANISM & DATA STRUCTURES (${activeQ.signals.slice(0, 3).join(", ")}):`,
          `   - `,
          `2. CONCURRENCY & CONSISTENCY INVARIANTS:`,
          `   - `,
          `3. PRODUCTION FAILURE MODE & TAIL-LATENCY MITIGATION:`,
          `   - `,
          `4. QUANTITATIVE TRADEOFF (MEMORY / CPU / I/O):`,
          `   - `
        ].join("\n");
        textarea.value = textarea.value ? textarea.value + "\n\n" + scaffold : scaffold;
        textarea.focus();
      });

      // Voice Dictation (Web Speech API with safe fallback)
      let recognition = null;
      let isDictating = false;
      document.getElementById("btn-voice-dictate").addEventListener("click", e => {
        const btn = e.currentTarget;
        const SpeechRec = window.SpeechRecognition || window.webkitSpeechRecognition;
        if (!SpeechRec) {
          showToast("BROWSER SPEECH RECOGNITION UNAVAILABLE IN THIS SANDBOX — USE KEYBOARD SCRATCHPAD.");
          return;
        }
        if (isDictating && recognition) {
          recognition.stop();
          isDictating = false;
          btn.textContent = "MIC: START DICTATION";
          return;
        }
        try {
          recognition = new SpeechRec();
          recognition.continuous = true;
          recognition.interimResults = false;
          recognition.lang = "en-US";
          recognition.onresult = event => {
            const transcript = Array.from(event.results)
              .map(r => r[0].transcript)
              .join(" ");
            const textarea = document.getElementById("candidate-answer-input");
            textarea.value = (textarea.value + " " + transcript).trim();
          };
          recognition.onerror = () => {
            isDictating = false;
            btn.textContent = "MIC: START DICTATION";
            showToast("VOICE CAPTURE BLOCKED BY SANDBOX PERMISSIONS — TYPE DIRECTLY IN SCRATCHPAD.");
          };
          recognition.onend = () => {
            isDictating = false;
            btn.textContent = "MIC: START DICTATION";
          };
          recognition.start();
          isDictating = true;
          btn.textContent = "MIC: LISTENING (CLICK TO STOP)";
        } catch (err) {
          showToast("VOICE CAPTURE UNAVAILABLE — TYPE DIRECTLY IN SCRATCHPAD.");
        }
      });

      // Evaluate Answer & Toggle Reference Answer
      document.getElementById("btn-evaluate-answer").addEventListener("click", evaluateCandidateAnswer);

      document.getElementById("btn-toggle-reference").addEventListener("click", e => {
        const refPanel = document.getElementById("reference-answer-panel");
        const isHidden = refPanel.classList.toggle("hidden");
        e.currentTarget.textContent = isHidden
          ? "REVEAL COMPLETE REFERENCE ANSWER & BLUEPRINT"
          : "HIDE COMPLETE REFERENCE ANSWER & BLUEPRINT";
      });

      document.getElementById("btn-copy-reference").addEventListener("click", () => {
        const activeQ = state.questions[state.activeQuestionIndex];
        if (!activeQ) return;
        const text = `${activeQ.title}\n\nMECHANISM:\n${activeQ.mechanism}\n\nFAILURE MODES:\n${activeQ.failures}\n\nBLUEPRINT:\n${activeQ.codeBlueprint}`;
        try {
          if (navigator.clipboard && navigator.clipboard.writeText) {
            navigator.clipboard.writeText(text);
          } else {
            const ta = document.createElement("textarea");
            ta.value = text;
            document.body.appendChild(ta);
            ta.select();
            document.execCommand("copy");
            document.body.removeChild(ta);
          }
          showToast("COPIED CANONICAL ANSWER & BLUEPRINT TO CLIPBOARD.");
        } catch (err) {
          showToast("COPY COMPLETED.");
        }
      });

      // Manual Rubric Grade Buttons
      document.querySelectorAll(".rubric-grade-btn").forEach(btn => {
        btn.addEventListener("click", () => {
          const activeQ = state.questions[state.activeQuestionIndex];
          if (!activeQ) return;
          const status = btn.getAttribute("data-status") || "solid";
          const score = parseInt(btn.getAttribute("data-score") || "75", 10);
          const key = getQuestionRecordKey(activeQ);
          const existing = state.practiceRecords[key] || { signalsHit: [], signalsMissed: [] };
          existing.status = status;
          existing.score = score;
          existing.evaluated = true;
          existing.draft = document.getElementById("candidate-answer-input").value;
          state.practiceRecords[key] = existing;
          savePersistedState();
          updateTopTelemetryAndStats();
          renderEvaluationPanel(activeQ, existing);
          renderInterrogationView();
          showToast(`RECORDED STATUS: ${status.toUpperCase()} (${score}%).`);
        });
      });

      // Prev / Next Question Navigation
      document.getElementById("btn-prev-question").addEventListener("click", () => {
        if (state.questions.length === 0) return;
        state.activeQuestionIndex = (state.activeQuestionIndex - 1 + state.questions.length) % state.questions.length;
        state.timerSeconds = 0;
        renderInterrogationView();
      });

      document.getElementById("btn-next-question").addEventListener("click", () => {
        if (state.questions.length === 0) return;
        state.activeQuestionIndex = (state.activeQuestionIndex + 1) % state.questions.length;
        state.timerSeconds = 0;
        renderInterrogationView();
      });

      // Compendium Search & Filters
      document.getElementById("compendium-search").addEventListener("input", renderCompendiumView);
      document.getElementById("compendium-domain-filter").addEventListener("change", renderCompendiumView);
      document.getElementById("compendium-status-filter").addEventListener("change", renderCompendiumView);

      document.getElementById("btn-compendium-expand-all").addEventListener("click", () => {
        document.querySelectorAll(".compendium-card .panel-body").forEach(el => el.classList.remove("hidden"));
        document.querySelectorAll(".compendium-toggle-card-btn").forEach(el => { el.textContent = "CLOSE"; });
        document.querySelectorAll(".compendium-answer-body").forEach(el => el.classList.remove("hidden"));
        document.querySelectorAll(".compendium-toggle-ans-btn").forEach(el => { el.textContent = "HIDE ANSWER & FOLLOW-UPS"; });
      });
      document.getElementById("btn-compendium-collapse-all").addEventListener("click", () => {
        document.querySelectorAll(".compendium-card .panel-body").forEach(el => el.classList.add("hidden"));
        document.querySelectorAll(".compendium-toggle-card-btn").forEach(el => { el.textContent = "DETAILS"; });
        document.querySelectorAll(".compendium-answer-body").forEach(el => el.classList.add("hidden"));
        document.querySelectorAll(".compendium-toggle-ans-btn").forEach(el => { el.textContent = "REVEAL ANSWER & FOLLOW-UPS"; });
      });

      // Custom Question Drawer in Compendium
      const customDrawer = document.getElementById("custom-q-drawer");
      document.getElementById("btn-open-custom-q-modal").addEventListener("click", () => {
        customDrawer.classList.toggle("hidden");
      });
      document.getElementById("btn-cancel-custom-q").addEventListener("click", () => {
        customDrawer.classList.add("hidden");
      });
      document.getElementById("btn-save-custom-q").addEventListener("click", () => {
        const title = document.getElementById("new-q-title").value.trim();
        const domain = document.getElementById("new-q-domain").value.trim() || "CUSTOM SYSTEMS PROBE";
        const claim = document.getElementById("new-q-claim").value.trim() || "Custom Added Architecture Topic";
        const prompt = document.getElementById("new-q-prompt").value.trim();
        const answer = document.getElementById("new-q-answer").value.trim();

        if (!title || !prompt || !answer) {
          showToast("PLEASE FILL TITLE, QUESTION PROMPT, AND REFERENCE ANSWER.");
          return;
        }

        state.questions.unshift({
          id: `PRB-CUSTOM-${state.questions.length + 1}`,
          domain: domain.toUpperCase(),
          level: state.seniority,
          claimId: "CUSTOM",
          boundClaim: claim,
          title,
          prompt,
          intent: "Custom user-defined deep technical interrogation probe.",
          signals: ["Mechanism", "Tradeoffs", "Failure Mode", "Production Scale"],
          followups: [
            {
              level: "LEVEL 1 // EDGE CASE",
              q: "What breaks first when concurrency or payload size increases by 10x?",
              a: answer
            }
          ],
          mechanism: answer,
          failures: "Verify resource exhaustion ceilings (memory, file descriptors, lock contention, network bandwidth).",
          codeBlueprint: "// Custom Architecture Verification Blueprint\n" + answer,
          l4Contrast: "Surface overview without concrete resource bounds.",
          l6Contrast: answer
        });

        customDrawer.classList.add("hidden");
        updateTopTelemetryAndStats();
        renderCompendiumView();
        renderInterrogationView();
        showToast("ADDED CUSTOM TECHNICAL PROBE TO COMPENDIUM & QUEUE.");
      });

      // Stress-Test & Capacity Calculator Listeners
      document.getElementById("incident-selector").addEventListener("change", e => {
        state.activeIncidentId = e.target.value;
        renderStressTestView();
      });

      ["calc-dau", "calc-writes-per-user", "calc-reads-per-user", "calc-payload-bytes", "calc-peak-multiplier", "calc-cache-ratio"].forEach(id => {
        document.getElementById(id).addEventListener("input", computeCapacityEstimates);
      });

      // Reset Ledger Button
      document.getElementById("btn-reset-progress").addEventListener("click", () => {
        state.practiceRecords = {};
        savePersistedState();
        updateTopTelemetryAndStats();
        renderLedgerView();
        renderInterrogationView();
        showToast("PRACTICE LEDGER RESET.");
      });

      // Export Markdown Dossier Button
      document.getElementById("btn-export-dossier").addEventListener("click", exportFullStudyDossierMarkdown);
    });

    async function initializeJobPreparation() {
      const status = document.getElementById("job-import-status");
      const button = document.getElementById("btn-import-job");
      const result = document.getElementById("job-preparation-results");
      const catalogue = document.getElementById("job-catalogue-list");
      const catalogueCount = document.getElementById("job-catalogue-count");
      const previous = document.getElementById("btn-jobs-prev");
      const next = document.getElementById("btn-jobs-next");
      const generatePlan = document.getElementById("btn-generate-plan");
      let pageOffset = 0;
      let pageLimit = 8;
      let selectedJobId = null;
      let searchTimer = null;

      function currentFilters() {
        const params = { limit: pageLimit, offset: pageOffset, sort: "relevance" };
        const q = document.getElementById("job-search-input").value.trim();
        const role = document.getElementById("job-role-filter").value;
        const skill = document.getElementById("job-skill-filter").value.trim();
        if (q) params.q = q;
        if (role) params.role_family = role;
        if (skill) params.skill = skill;
        return params;
      }

      async function loadCatalogue() {
        catalogueCount.textContent = "LOADING JOB CATALOGUE…";
        try {
          const page = await rigorApi.listJobs(currentFilters());
          catalogueCount.textContent = `${page.total} JOB${page.total === 1 ? "" : "SAVED"} // PAGE ${Math.floor(pageOffset / pageLimit) + 1}`;
          catalogue.innerHTML = page.items.length ? page.items.map(job =>
            `<button type="button" class="job-list-button" data-job-id="${escapeHtml(job.id)}"><strong>${escapeHtml(job.role_title)}${job.is_demo ? " · DEMO" : ""}</strong><span>${escapeHtml(job.company_name || "Company not specified")} · ${escapeHtml(job.role_family.replaceAll("_", " "))}${job.seniority ? ` · ${escapeHtml(job.seniority)}` : ""}</span><span>${escapeHtml([...(job.required_skills || []), ...(job.preferred_skills || [])].join(", ") || "No recognized skill tags")}</span></button>`
          ).join("") : `<p class="job-import-note">No matching jobs. Import a description below or clear the filters.</p>`;
          catalogue.querySelectorAll("[data-job-id]").forEach(item => {
            item.addEventListener("click", () => selectJob(item.dataset.jobId));
          });
          previous.disabled = pageOffset === 0;
          next.disabled = page.next_offset === null;
        } catch (error) {
          catalogueCount.textContent = "CATALOGUE UNAVAILABLE";
          catalogue.innerHTML = `<p class="job-import-note">${escapeHtml(error.message)}. Browser-based practice remains available.</p>`;
          previous.disabled = true;
          next.disabled = true;
        }
      }

      function renderCoverage(coverage) {
        const missingQuestions = coverage.required_skills_without_questions || [];
        const missingModules = coverage.required_skills_without_learning || [];
        document.getElementById("job-content-coverage").innerHTML = `<div class="job-detail-block"><div class="job-list-heading">CONTENT COVERAGE // ${coverage.content_coverage_percent}%</div><div class="coverage-meter" role="img" aria-label="Content coverage ${coverage.content_coverage_percent} percent"><span style="width:${coverage.content_coverage_percent}%"></span></div><p>${coverage.question_count} relevant reviewed questions currently match this listing.</p><p><strong>Required skills without question coverage:</strong> ${missingQuestions.length ? missingQuestions.map(escapeHtml).join(", ") : "None"}</p><p><strong>Required skills without learning modules:</strong> ${missingModules.length ? missingModules.map(escapeHtml).join(", ") : "None"}</p><p class="job-import-note">Coverage counts tagged catalogue content; it is not a prediction of interview success.</p></div>`;
      }

      async function selectJob(jobId) {
        selectedJobId = jobId;
        generatePlan.disabled = true;
        status.textContent = "LOADING JOB PROFILE AND CONTENT COVERAGE…";
        try {
          const [job, skills, coverage] = await Promise.all([
            rigorApi.getJob(jobId), rigorApi.getJobSkills(jobId), rigorApi.getCoverage(jobId)
          ]);
          document.getElementById("job-selected-details").innerHTML = `<div class="job-detail-block"><div class="job-list-heading">${escapeHtml(job.role_title)}${job.is_demo ? " // DEMONSTRATION LISTING" : ""}</div><p>${escapeHtml(job.company_name || "Company not specified")} · ${escapeHtml(job.role_family.replaceAll("_", " "))}${job.seniority ? ` · ${escapeHtml(job.seniority)}` : ""}${job.location ? ` · ${escapeHtml(job.location)}` : ""}</p><p><strong>Required:</strong> ${skills.items.filter(x => x.requirement_type === "required").map(x => escapeHtml(x.skill)).join(", ") || "Not confidently identified"}</p><p><strong>Preferred:</strong> ${skills.items.filter(x => x.requirement_type === "preferred").map(x => escapeHtml(x.skill)).join(", ") || "Not confidently identified"}</p>${job.responsibilities.length ? `<p><strong>Responsibilities:</strong> ${job.responsibilities.map(escapeHtml).join(" · ")}</p>` : ""}<details><summary>Original job description and source</summary><p style="white-space:pre-wrap">${escapeHtml(job.description)}</p>${job.source_url ? `<a href="${escapeHtml(job.source_url)}" target="_blank" rel="noopener noreferrer">Open source listing</a>` : ""}</details></div>`;
          renderCoverage(coverage.coverage);
          status.textContent = `JOB PROFILE LOADED // CONTENT VERSION ${job.content_version}${job.is_demo ? " // DEMO DATA" : ""}`;
          generatePlan.disabled = false;
        } catch (error) {
          status.textContent = `COULD NOT LOAD JOB: ${error.message}`;
        }
      }

      function addQuestionToWorkbench(question) {
        const id = `BANK-${question.stable_key}`;
        let index = state.questions.findIndex(item => item.id === id);
        if (index < 0) {
          state.questions.push({
            id, title: `${question.primary_skill || "Practice"} // ${question.category.replaceAll("_", " ")}`,
            domain: question.category.toUpperCase().replaceAll("_", " "), level: question.difficulty.toUpperCase(),
            boundClaim: question.match_reasons.join(" ") || "Recommended for the selected role.",
            claimId: "STACK-01", prompt: question.question, intent: question.match_reasons.join(" "),
            signals: question.expected_points, followups: [], mechanism: question.reference_answer,
            failures: question.common_mistakes.join("\n"), codeBlueprint: "No code blueprint is attached to this practice question.",
            l4Contrast: question.rubric, l6Contrast: question.match_reasons.join(" ")
          });
          index = state.questions.length - 1;
        }
        state.activeQuestionIndex = index;
        updateTopTelemetryAndStats();
        renderInterrogationView();
        renderCompendiumView();
        switchView("interrogation");
      }

      function renderPlan(plan) {
        const modules = plan.learning_modules || [];
        const questions = plan.questions || plan.modules?.[1]?.questions || [];
        const categories = [...new Set(questions.map(question => question.category).filter(Boolean))];
        const categoryOptions = categories.map(category => `<option value="${escapeHtml(category)}">${escapeHtml(category.replaceAll("_", " "))}</option>`).join("");
        const moduleCards = modules.map(module => {
          const objectives = (module.learning_objectives || []).map(item => `<li>${escapeHtml(item)}</li>`).join("");
          const mistakes = (module.common_mistakes || []).map(item => `<li>${escapeHtml(item)}</li>`).join("");
          const exercises = (module.practical_exercises || []).map(item => `<li>${escapeHtml(item)}</li>`).join("");
          return `<details class="recommendation-card"><summary>${escapeHtml(module.title)} · ${module.estimated_minutes} min · ${escapeHtml((module.skills || []).join(", "))}</summary><p>${escapeHtml(module.purpose)}</p><p>${escapeHtml(module.content)}</p><strong>Learning objectives</strong><ul>${objectives}</ul><strong>Common mistakes</strong><ul>${mistakes}</ul><strong>Practical exercises</strong><ul>${exercises}</ul></details>`;
        }).join("");
        const questionCards = questions.map(question => {
          const reasons = (question.match_reasons || []).map(escapeHtml).join(" ") || "Relevant role-family practice.";
          return `<article class="recommendation-card plan-question-card" data-category="${escapeHtml(question.category || "")}" data-difficulty="${escapeHtml(question.difficulty || "")}"><div class="job-list-heading">${escapeHtml(question.primary_skill || question.category)} · ${escapeHtml(question.difficulty)} · MATCH ${question.relevance_score ?? "—"}</div><p>${escapeHtml(question.question)}</p><p><strong>Why selected:</strong> ${reasons}</p><button type="button" class="btn btn-sm practice-bank-question" data-question-key="${escapeHtml(question.stable_key)}">PRACTICE IN WORKBENCH</button></article>`;
        }).join("");
        const filters = questions.length ? `<div class="job-catalogue-filters"><div><label for="plan-question-search" class="font-mono-tech">FILTER QUESTIONS</label><input id="plan-question-search" class="select-field" placeholder="Question text or skill" /></div><div><label for="plan-question-category" class="font-mono-tech">CATEGORY</label><select id="plan-question-category" class="select-field"><option value="">All categories</option>${categoryOptions}</select></div><div><label for="plan-question-difficulty" class="font-mono-tech">DIFFICULTY</label><select id="plan-question-difficulty" class="select-field"><option value="">All levels</option><option value="beginner">Beginner</option><option value="intermediate">Intermediate</option><option value="advanced">Advanced</option></select></div></div>` : "";
        result.innerHTML = `<div class="job-analysis-card"><div class="job-list-heading">PREPARATION PLAN // ${questions.length} QUESTIONS // ${modules.length} LEARNING MODULES</div><h4>Recommended learning</h4>${moduleCards || "<p>No reviewed learning modules currently match this job's skills.</p>"}<h4>Ranked practice questions</h4>${filters}${questionCards || "<p>No reviewed questions match the available job skills. See uncovered skills above.</p>"}</div>`;
        const filterPlanQuestions = () => {
          const text = (document.getElementById("plan-question-search")?.value || "").toLowerCase();
          const category = document.getElementById("plan-question-category")?.value || "";
          const difficulty = document.getElementById("plan-question-difficulty")?.value || "";
          result.querySelectorAll(".plan-question-card").forEach(card => {
            const matchesText = !text || card.textContent.toLowerCase().includes(text);
            const matchesCategory = !category || card.dataset.category === category;
            const matchesDifficulty = !difficulty || card.dataset.difficulty === difficulty;
            card.classList.toggle("hidden", !(matchesText && matchesCategory && matchesDifficulty));
          });
        };
        ["plan-question-search", "plan-question-category", "plan-question-difficulty"].forEach(id => {
          document.getElementById(id)?.addEventListener(id.endsWith("search") ? "input" : "change", filterPlanQuestions);
        });
        result.querySelectorAll(".practice-bank-question").forEach(button => {
          const question = questions.find(item => item.stable_key === button.dataset.questionKey);
          if (question) button.addEventListener("click", () => addQuestionToWorkbench(question));
        });
      }

      try {
        const health = await rigorApi.health();
        status.textContent = `BACKEND ${health.status.toUpperCase()} // DATABASE ${health.database.toUpperCase()}`;
        await loadCatalogue();
      } catch {
        status.textContent = "BACKEND OFFLINE // Existing browser-based workbench remains available";
        catalogueCount.textContent = "JOB CATALOGUE OFFLINE";
        catalogue.innerHTML = `<p class="job-import-note">Start the backend and apply migrations to browse or import jobs.</p>`;
      }
      ["job-search-input", "job-skill-filter"].forEach(id => document.getElementById(id).addEventListener("input", () => {
        clearTimeout(searchTimer);
        searchTimer = setTimeout(() => { pageOffset = 0; loadCatalogue(); }, 250);
      }));
      document.getElementById("job-role-filter").addEventListener("change", () => { pageOffset = 0; loadCatalogue(); });
      previous.addEventListener("click", () => { pageOffset = Math.max(0, pageOffset - pageLimit); loadCatalogue(); });
      next.addEventListener("click", () => { pageOffset += pageLimit; loadCatalogue(); });
      generatePlan.addEventListener("click", async () => {
        if (!selectedJobId) return;
        generatePlan.disabled = true;
        status.textContent = "RANKING REVIEWED CONTENT AND SAVING PLAN…";
        try {
          const plan = await rigorApi.createPlan(selectedJobId);
          renderPlan(plan);
          renderCoverage({
            content_coverage_percent: plan.content_coverage.content_coverage_percent,
            question_count: plan.content_coverage.question_count,
            required_skills_without_questions: plan.content_coverage.required_skills_without_questions,
            required_skills_without_learning: plan.content_coverage.required_skills_without_learning
          });
          status.textContent = "PREPARATION PLAN SAVED. RANKING EXPLANATIONS ARE SHOWN PER QUESTION.";
        } catch (error) {
          status.textContent = `COULD NOT CREATE PLAN: ${error.message}`;
        } finally {
          generatePlan.disabled = false;
        }
      });
      button.addEventListener("click", async () => {
        const roleTitle = document.getElementById("job-title-input").value.trim();
        const companyName = document.getElementById("job-company-input").value.trim();
        const location = document.getElementById("job-location-input").value.trim();
        const sourceUrl = document.getElementById("job-source-url-input").value.trim();
        const description = document.getElementById("job-description-input").value.trim();
        if (!roleTitle || description.length < 80) {
          status.textContent = "ENTER A ROLE TITLE AND AT LEAST 80 CHARACTERS OF JOB DESCRIPTION.";
          return;
        }
        button.disabled = true;
        status.textContent = "ANALYSING JOB DESCRIPTION…";
        try {
          const job = await rigorApi.importJob({ role_title: roleTitle, company_name: companyName || null, location: location || null, source_url: sourceUrl || null, description });
          status.textContent = job.is_duplicate ? `MATCHED EXISTING JOB // ${job.version_created ? "NEW DESCRIPTION VERSION SAVED" : "NO CONTENT CHANGE"}` : "JOB IMPORTED AND DEFAULT PREPARATION PLAN SAVED.";
          selectedJobId = job.id;
          await selectJob(job.id);
          renderPlan(job.preparation_plan);
          await loadCatalogue();
        } catch (error) {
          status.textContent = `COULD NOT SAVE JOB: ${error.message}`;
        } finally {
          button.disabled = false;
        }
      });
    }

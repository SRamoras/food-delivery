# Redis

Redis holds real-time state that is either **ephemeral** (it may be lost and comes back by itself within seconds) or **derived** (a copy of PostgreSQL that `redis/rebuild.py` can recreate). Nothing in Redis is the only copy of something the business must keep: orders, offers, stock and deliveries are recorded in PostgreSQL.

Sections still to be written by their owners are marked *(to do: name)*.

## Conventions

- **Prefix:** every key starts with `fd:`. Ids in keys are integers or dates built by the app, never raw request text.
- **TTL with the write:** the expiry is set in the same command (`SET ... EX`, `SET ... EXAT`) or in the same `MULTI/EXEC` or Lua script as the write. Never a separate `EXPIRE` after it: if the app died between the two, the key would live forever.
- **After the commit:** derived keys are written only after PostgreSQL commits. A rollback must never leave Redis showing something that did not happen. A Redis failure at that point is logged and does not fail the request; `redis/verify.py` finds the gap and `redis/rebuild.py` fixes it.
- **No `KEYS`:** the app never lists keys. `rebuild.py` and `verify.py` use `SCAN`, which walks the keyspace in small batches without blocking Redis.
- **Atomic multi-step operations:** in Lua scripts (`redis/scripts/*.lua`), registered once in `app/db/redis.py` with `register_script`.

## Key patterns

| Key | Type | TTL | Class | Owner |
|---|---|---|---|---|
| `fd:couriers:geo` | GEO (sorted set) | none; members removed on `/offline` | ephemeral | SRamoras |
| `fd:courier:{courier_id}:online` | string | `EX 30`, refreshed on every position | ephemeral | SRamoras |
| `fd:offer:{offer_id}` | hash | `EX 45` | ephemeral (PG is the record) | SRamoras |
| `fd:order:{order_id}:track` | hash | `EX 86400` | derived | jcleberfernandes |
| `fd:stock:{item_id}:{yyyy-mm-dd}` | string (integer) | `EXAT` next Lisbon midnight + 1 h | derived | RodrigoDias123 |
| `fd:rank:{city_id}:{yyyymmddHHMM}` | sorted set | `EX 3900` | derived | jcleberfernandes *(to do: not implemented yet)* |

### `fd:couriers:geo`

The live map of online couriers (F7), used to find couriers near a restaurant (F3) and to show the courier's position when a customer tracks an order (F6).

- **Example:** member `1524` at `(-8.436347, 41.551565)`.
- **Commands:**
  - `GEOADD fd:couriers:geo <lng> <lat> <courier_id>`: inside `redis/scripts/courier_position.lua`, on `/online` and `/position`.
  - `GEOSEARCH fd:couriers:geo FROMLONLAT <lng> <lat> BYRADIUS 3 km ASC`: F3, the couriers within 3 km of the restaurant, closest first.
  - `GEOPOS fd:couriers:geo <courier_id>`: F6, the courier's last position.
  - `ZREM fd:couriers:geo <courier_id>`: `/offline` (a GEO set is a sorted set). In the same `MULTI` as the `DEL` of the online key.
- **TTL:** none. A member of a set cannot expire on its own, so being on the map does not mean being online: the online key below says that. A courier who stops sending positions stays on the map with a stale position until `/offline` or the next `/online`, and F3 ignores them because their online key is gone.
- **Why Redis:** 2,500 couriers send a position every few seconds. PostgreSQL would take thousands of writes per minute for data that is out of date seconds later. `GEOSEARCH` answers "who is within 3 km" from memory.

### `fd:courier:{courier_id}:online`

Whether a courier is online: the key exists only while the courier keeps sending positions.

- **Example:** `fd:courier:1524:online` = `"1"`, TTL 30.
- **Commands:** `SET fd:courier:{id}:online 1 EX 30` and `EXISTS` inside `courier_position.lua`; `EXISTS` in F3 (pipelined, one per courier found by `GEOSEARCH`); `DEL` on `/offline`.
- **TTL 30 s and why:** the brief's rule is "no position for 30 s = offline". Each position rewrites the key with a fresh 30 s. If the app on the phone stops, the key disappears by itself, with no job to clean it.
- **Why a Lua script:** the `GEOADD` and the `SET` run together with nothing in between. A courier can never be on the map without an online key, and an `/offline` that arrives at the same time runs entirely before or entirely after. `/position` also checks the key in the same script: an offline courier's position is refused (409) instead of putting them back on the map.

### `fd:offer:{offer_id}`

A delivery offer that a courier can still accept (F3, F4).

- **Example:** `fd:offer:597749` = `{order_id: "414985", courier_id: "2564", restaurant_id: "1208"}`, TTL 45.
- **Commands:** `HSET` + `EXPIRE 45` in one `MULTI` after F3 accept or reoffer commits; `DEL` of every offer of the order after F4 accept commits, and of the offer itself after a decline or when it is found expired.
- **TTL 45 s and why:** the brief gives a courier 45 s to answer an offer.
- **Class: ephemeral, PostgreSQL is the record.** Every offer is a row in `delivery_offers` with `sent_at` and its outcome. F4 never trusts the Redis key: an offer is valid if PostgreSQL says `pending` and `sent_at` is less than 45 s ago, checked with the order row locked. The Redis key is the brief's "pending offer with a 45 s expiry", which a courier app would read without touching PostgreSQL; if it is lost, nothing is decided wrongly.
- **Rebuild:** `rebuild_offers` recreates keys only for offers still `pending` and younger than 45 s, each with the seconds it has left, so a rebuild never makes an offer live longer.

### `fd:order:{order_id}:track`

The tracking view of an order (F6). *(Details: jcleberfernandes.)*

- **Example:** `fd:order:42:track` = `{customer_id: "1", status: "accepted", courier_id: "12", updated_at: "2026-11-10T20:09:58+00:00"}`.
- **Commands:** `HSET` + `EXPIRE 86400` in one `MULTI` after every status change commits (`update_tracking`), and after F4 accept, which adds the courier; `HGETALL` in F6; on a miss, `redis/scripts/fill_tracking.lua` creates the hash only if it is still missing, so an older status read from PostgreSQL cannot overwrite a newer one.
- **TTL one day and why:** far longer than any delivery; finished orders then leave memory on their own.
- **Ownership check:** F6 compares the customer with the `customer_id` stored in the hash, so a repeated request never touches PostgreSQL.

### `fd:stock:{item_id}:{yyyy-mm-dd}`

A copy of an item's portions left today. *(Details: RodrigoDias123.)*

- **Example:** `fd:stock:731:2026-11-10` = `"28"`.
- **Commands:** `SET ... EXAT <next Lisbon midnight + 1 h>` with the value PostgreSQL returned (`RETURNING remaining`), after the order, cancel or reject commits.
- **TTL and why:** the key belongs to one Lisbon day; it expires after that day ends. The one-hour margin keeps a key written just before midnight from being born already expired.
- **Why `SET` and not `DECR`:** the copy always mirrors the source of truth instead of building up its own errors.

### `fd:rank:{city_id}:{yyyymmddHHMM}`

*(to do: jcleberfernandes: the per-city, per-minute ranking buckets, `ZINCRBY` + `EX 3900` in one `MULTI`, read with `ZUNION` of the last 60 buckets.)*

## Persistence and memory

Settings in `compose.yml`:

| Setting | Value | Why |
|---|---|---|
| `appendonly` | `yes` | The append-only file logs every write, so a restart reloads the data. |
| `appendfsync` | `everysec` | The AOF is flushed to disk once a second: at most about 1 s of writes is lost on a crash, without the cost of a disk write per command. Acceptable because every key is ephemeral or derived. |
| `maxmemory` | `256mb` | A bound, so Redis cannot take all the machine's memory. The real data is small: 2,500 GEO members and online keys, a few hundred live offers, the tracking hashes of one day, today's stock keys. |
| `maxmemory-policy` | `noeviction` | When memory is full, writes fail instead of Redis silently dropping keys. An evicted pending offer or stock copy would be wrong data with no error; a failed write is logged and the PostgreSQL record is unaffected. |
| `requirepass` | from `.env` | The app and `redis-cli` authenticate; the password is never written in `compose.yml`. The port is published on `127.0.0.1` only. |

## Rebuild and verify

```bash
uv run python redis/rebuild.py   # recreate every derived key from PostgreSQL
uv run python redis/verify.py    # compare Redis with PostgreSQL, exit 1 on any difference
```

- Ephemeral keys (`fd:couriers:geo`, `fd:courier:{id}:online`) are not rebuilt: they come back with the next position each courier sends.
- `fd:offer:*` keys are rebuilt for offers still pending and inside their 45 s.
- Tested: the "same order" fixture writes 50 pending offers to PostgreSQL with no Redis keys. `verify.py` reported the 50 missing keys; after `rebuild.py`, `verify.py` exited 0, and a rebuilt key had 42 s left. 47 s later the keys had expired and `verify.py` still exited 0 (offers older than 45 s are not expected in Redis, even while PostgreSQL still says `pending`).

## Cache evidence

*(to do: jcleberfernandes: the F6 tracking evidence, `MONITOR` on a repeated request and PostgreSQL statement logging showing that the repeat does not reach PostgreSQL.)*

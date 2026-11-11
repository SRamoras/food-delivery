# Redis

Redis holds real-time state that is either **ephemeral** (it may be lost and comes back by itself within seconds) or **derived** (a copy of PostgreSQL that `redis/rebuild.py` can recreate). Nothing in Redis is the only copy of something the business must keep: orders, offers, stock and deliveries are recorded in PostgreSQL.

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
| `fd:rank:{city_id}:{yyyymmddHHMM}` | sorted set | `EX 3900` | derived | jcleberfernandes |

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
- **Commands:** `HSET` + `EXPIRE 45` in one `MULTI` after F3 accept or reoffer commits; `DEL` of every offer of the order after F4 accept commits, of the offers a cancel withdrew after the cancel commits, and of the offer itself after a decline or when it is found expired.
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

The last-hour ranking: the 20 restaurants with most delivered orders in the last 60 minutes, per city. One sorted set per city and per minute (UTC); member = restaurant id, score = deliveries in that minute.

- **Example:** `fd:rank:18:202611110444` = `{1213: 2}`, TTL 3900.
- **Write:** `ZINCRBY fd:rank:{city_id}:{minute} 1 {restaurant_id}` + `EXPIRE 3900` in one `MULTI` (`record_delivery` in `app/services/ranking.py`), after the `delivered` status change commits. The restaurant's city is read inside that transaction, so the write needs no extra query.
- **Read:** `ZUNION` of the 60 buckets of the last hour `WITHSCORES` (missing buckets count as empty), top 20, in `GET /backoffice/cities/{city_id}/ranking`. Redis only: a city with no deliveries in the last hour answers an empty list.
- **Why per-minute buckets and not one set:** a single sorted set cannot forget deliveries older than an hour. With buckets, the window slides by reading the last 60 keys, and old buckets disappear on their own.
- **TTL 65 min and why:** a bucket must live as long as the 60-minute window it can be part of; the extra 5 minutes cover clock differences between the app and Redis.
- **Minutes in UTC, not Lisbon:** when the clocks go back, Lisbon repeats an hour, and two different minutes would share one bucket.
- **Rebuild:** `rebuild_ranking` recounts the deliveries of the last 60 minutes from PostgreSQL (`deliveries.delivered_at`) into the same buckets; `verify_ranking` compares the totals per city.
- **Tested:** two orders of restaurant 1213 taken through `preparing`, `ready`, `picked-up` and `delivered` with the API: the ranking of city 18 went from `[]` to `[{restaurant_id: 1213, deliveries: 2}]`, the bucket had TTL 3899, and `verify.py` exited 0.

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
- `fd:stock:*` keys are rebuilt from today's `daily_stock` rows; `fd:order:*:track` hashes for orders not finished yet (a finished order fills its hash on the next F6 miss, so `verify.py` does not count a missing tracking key); `fd:rank:*` buckets from the deliveries of the last 60 minutes.
- Tested: the "same order" fixture writes 50 pending offers to PostgreSQL with no Redis keys. `verify.py` reported the 50 missing keys; after `rebuild.py`, `verify.py` exited 0, and a rebuilt key had 42 s left. 47 s later the keys had expired and `verify.py` still exited 0 (offers older than 45 s are not expected in Redis, even while PostgreSQL still says `pending`).

## Cache evidence

F6 (`GET /customers/{customer_id}/orders/{order_id}/track`) is the flow the brief reads from Redis. The test: PostgreSQL started with statement logging (`PG_LOG_STATEMENT=all docker compose up -d postgres`), the tracking key of order 414358 deleted, `redis-cli MONITOR` running, and the same request sent twice, 2 s apart (customer 60006, courier 2753 online).

```bash
curl http://127.0.0.1:8000/customers/60006/orders/414358/track   # 04:44:51.5 UTC: cache miss
curl http://127.0.0.1:8000/customers/60006/orders/414358/track   # 04:44:53.6 UTC: repeat
```

Both answered the same body:

```json
{"order_id":414358,"status":"accepted","courier_id":2753,"courier_position":{"lat":41.14959988017691,"lng":-8.610998690128326},"updated_at":"2026-11-11T04:29:38.490846Z"}
```

**Redis `MONITOR`** (the timestamps are Unix seconds: 1794372291 = 04:44:51 UTC):

```
1794372291.574745 [0 172.19.0.5:59892] "HGETALL" "fd:order:414358:track"
1794372291.577264 [0 172.19.0.5:59892] "EVALSHA" "fa60dda47010748a470fa8914e5be4ffac6226e8" "1" "fd:order:414358:track" "86400" "customer_id" "60006" "status" "accepted" "updated_at" "2026-11-11T04:29:38.490846+00:00" "courier_id" "2753"
1794372291.577286 [0 lua] "EXISTS" "fd:order:414358:track"
1794372291.577320 [0 lua] "HSET" "fd:order:414358:track" "customer_id" "60006" "status" "accepted" "updated_at" "2026-11-11T04:29:38.490846+00:00" "courier_id" "2753"
1794372291.577332 [0 lua] "EXPIRE" "fd:order:414358:track" "86400"
1794372291.578032 [0 172.19.0.5:59892] "GEOPOS" "fd:couriers:geo" "2753"
1794372293.653282 [0 172.19.0.5:59892] "HGETALL" "fd:order:414358:track"
1794372293.653545 [0 172.19.0.5:59892] "GEOPOS" "fd:couriers:geo" "2753"
```

**PostgreSQL log** in the same seconds:

```
2026-11-11 04:44:51.576 UTC [47] LOG:  statement: BEGIN
2026-11-11 04:44:51.576 UTC [47] LOG:  execute <unnamed>: SELECT orders.id, orders.customer_id, orders.status, deliveries.courier_id, coalesce((SELECT max(order_status_history.changed_at) AS max_1 ...
2026-11-11 04:44:51.576 UTC [47] DETAIL:  Parameters: $1 = '414358'
2026-11-11 04:44:51.576 UTC [47] LOG:  statement: COMMIT
```

**Reading:**
- **First request (04:44:51):** `HGETALL` finds nothing, so the app reads PostgreSQL once (the one `SELECT` in the log) and fills the hash with `fill_tracking.lua` (`EXISTS`, then `HSET` + `EXPIRE 86400` in the same script). Then `GEOPOS` for the courier's position.
- **Second request (04:44:53):** only `HGETALL` and `GEOPOS` in Redis, and **no line at all** in the PostgreSQL log. The ownership check uses the `customer_id` in the hash, so not even that needs PostgreSQL.
- Statement logging was turned off again afterwards (`docker compose up -d postgres` without the variable).

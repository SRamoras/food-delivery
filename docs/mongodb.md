# MongoDB

MongoDB holds two kinds of data: the courier position trail, which is a source of truth produced in large numbers, and the report collections, which are derived from PostgreSQL and read only by the report pipelines.

| Collection | Holds | Source of truth or derived | Written by | Read by |
|---|---|---|---|---|
| `courier_positions` | One document per position a courier sends | **Source of truth** (kept 7 days) | F7 (`POST /couriers/{id}/position`), `mongodb/seed.py` | Back office, history |
| `report_orders` | One document per finished order | **Derived** from PostgreSQL | `mongodb/export_reports.py` | Pipelines 1, 4 and 5 |
| `report_offers` | One document per delivery offer | **Derived** from PostgreSQL | `mongodb/export_reports.py` | Offer reports (pipeline 6 if added) |

Setup: `mongodb/setup.py`, run as root by `scripts/setup.sh`. It is idempotent: it creates a missing collection with its validator, or updates the validator with `collMod`, and `create_indexes` skips existing indexes. Every collection has a `$jsonSchema` validator with `validationLevel: "strict"` and `validationAction: "error"`, so an invalid document is refused, not stored.

The app connects as `fd_app`, a user created in the `food_delivery` database with the `readWrite` role on that database only. The root user is used only by `scripts/setup.sh` and the runbook.

## `courier_positions`

- **What it holds:** every position a courier sends while online: courier, GeoJSON point, time and, when on a delivery, the order.
- **Why MongoDB:** about 50,000+ documents a week, written once and never updated, read by courier and time. They are not part of any transaction, and PostgreSQL would have to vacuum and index a table that only grows. The TTL index deletes old documents with no job.
- **Truth or derived:** source of truth for the trail. The *live* position is in Redis (`fd:couriers:geo`); this collection is the history.
- **Embed or reference:** the courier and the order are **referenced** by id (`couriers.id`, `orders.id` in PostgreSQL). They live on their own and are shared by thousands of positions; copying them would only repeat data that never changes the position.

Example:

```js
{
  _id: ObjectId('6af392e13c54faf638da504f'),
  courier_id: 553,
  location: { type: 'Point', coordinates: [ -9.139330131084984, 38.712736737974836 ] },
  recorded_at: ISODate('2026-11-03T22:12:20.196Z'),
  order_id: 404071
}
```

Validator (summary, full text in `mongodb/setup.py`): required `courier_id` (int/long ≥ 1), `location` (GeoJSON `Point` with `[lng, lat]` in range), `recorded_at` (BSON date); optional `order_id` (int/long ≥ 1); `additionalProperties: false`.

| Index | Why |
|---|---|
| `recorded_at_ttl` `{recorded_at: 1}`, `expireAfterSeconds: 604800` | The brief keeps the trail 7 days. `recorded_at` is a BSON date because a TTL index only expires date values. |
| `courier_id_recorded_at` `{courier_id: 1, recorded_at: -1}` | A courier's trail, newest first. |

## `report_orders`

- **What it holds:** one document per finished order (`delivered`, `cancelled` or `rejected`); `_id` is `orders.id`. City, restaurant and customer zones, restaurant and cuisines, the lines with their options, money, cancel reason and actor, and one date per status the order reached.
- **Why MongoDB:** the reports group hundreds of thousands of orders. Running them on PostgreSQL would load the database that takes orders. Each document already has everything a pipeline needs (no joins), so every report is one `aggregate`.
- **Truth or derived:** **derived**. If it is lost, `mongodb/export_reports.py` writes it again from PostgreSQL. It is not backed up.

Embed or reference:

| Relationship | Choice | Why |
|---|---|---|
| Order → lines (with options) | **Embedded** | Always read with the order, at most a few per order, and they never change after the order ends. |
| Order → status dates (`placed_at`, `accepted_at`, …) | **Embedded** as fields | Pipelines 1 and 5 subtract two of them in the same document. A missing field means the order never reached that status. |
| Order → zone, city, restaurant name, cuisines | **Copied** (with the id) | The pipelines group by them. The copy is the value at export time, and the export runs again to refresh it. |
| Order → restaurant, customer zone, items | **Referenced** by id | They exist on their own and are shared by many orders. The id keeps the link to PostgreSQL. |
| Order → courier | Not stored | No order pipeline needs it. Offers carry the courier (`report_offers`). |

Example (a cancelled order):

```js
{
  _id: 12,
  restaurant_id: 979, restaurant_name: 'Casa do Mar', cuisines: [ 'Hambúrgueres' ],
  city_id: 1, city_name: 'Lisboa',
  restaurant_zone_id: 4, restaurant_zone_name: 'Graça',
  customer_zone_id: 9, customer_zone_name: 'Avenidas Novas',
  status: 'cancelled',
  lines: [
    { item_id: 22957, item_name: 'Azeitonas', quantity: 1, unit_price: Decimal128('7.00'), options: [] },
    { item_id: 22969, item_name: 'Polvo à lagareiro', quantity: 1, unit_price: Decimal128('17.50'),
      options: [ { name: 'large', type: 'size', extra: '3.00' } ] }
  ],
  subtotal: Decimal128('31.50'), delivery_fee: Decimal128('1.85'), tip: Decimal128('0.00'), total: Decimal128('33.35'),
  cancel_reason: 'customer_changed_mind', cancelled_by: 'customer',
  placed_at: ISODate('2025-11-11T11:31:35.000Z'),
  accepted_at: ISODate('2025-11-11T11:34:57.880Z'),
  cancelled_at: ISODate('2025-11-11T11:37:27.604Z')
}
```

Money is `Decimal128`, never a double, so cents stay exact.

Validator (summary, full text in `mongodb/setup.py`): `allOf` of two schemas, so each owner keeps their part in one place:
- jcleberfernandes's schema: required ids and names, `status` in `delivered`/`cancelled`/`rejected`, `lines` with at least one line (`quantity` ≥ 1, `unit_price` decimal), money as decimal, every `*_at` a date, `additionalProperties: false`.
- RodrigoDias123's schema (pipeline 4): `cancel_reason` and `cancelled_by` only on a cancelled order, from the fixed lists.

| Index | Why |
|---|---|
| `status_placed_at` `{status: 1, placed_at: 1}` | Pipeline 1 (`delivered`, last 30 days) and pipeline 4 (last 90 days) start with a `$match` on status and a `placed_at` range. Equality field first, range field second. |

### `explain("executionStats")`: pipeline 1's `$match`, without and with the index

```js
db.report_orders.find({ status: "delivered", placed_at: { $gte: <now - 30 days> } })
  .hint({ $natural: 1 })            // without: forces a collection scan
  .explain("executionStats")
db.report_orders.find({ status: "delivered", placed_at: { $gte: <now - 30 days> } })
  .explain("executionStats")        // with: the planner picks status_placed_at
```

| | Without the index | With `status_placed_at` |
|---|---|---|
| Winning plan | `COLLSCAN` | `IXSCAN` → `FETCH` |
| `nReturned` | 39,792 | 39,792 |
| `totalKeysExamined` | 0 | 39,792 |
| `totalDocsExamined` | 414,345 | 39,792 |
| `executionTimeMillis` | 396 | 41 |

Without the index MongoDB reads every one of the 414,345 documents to keep 39,792. With it, it reads exactly the keys and documents it returns: about 10 times faster.

## `report_offers`

- **What it holds:** one document per delivery offer; `_id` is `delivery_offers.id`. Order, courier, the restaurant's zone (offers go to couriers near the restaurant), `sent_at` and the outcome.
- **Why MongoDB, truth or derived:** same as `report_orders`: **derived**, rebuilt by the export, read only by reports.
- **Embed or reference:** the order and the courier are **referenced** by id (an order has about 1.5 offers, and the order document is in `report_orders`). The zone name is **copied** so a report can group by it without a join.

Example:

```js
{
  _id: 1, order_id: 1, courier_id: 128,
  zone_id: 8, zone_name: 'Campo de Ourique',
  sent_at: ISODate('2025-11-11T00:51:52.316Z'),
  outcome: 'accepted'
}
```

Validator: required `_id`, `order_id`, `courier_id`, `zone_id` (int/long ≥ 1), `sent_at` (date), `outcome` in `pending`/`accepted`/`rejected`/`expired`/`withdrawn`; `additionalProperties: false`. No extra index: no pipeline reads it yet.

## Item options: `jsonb` in PostgreSQL, not MongoDB

The brief lets us store item options in MongoDB, in a `jsonb` column or in tables. We chose a **`jsonb` column on `menu_items`**:

- **The price is read in the order transaction.** F2 computes each line's price (item + options) in the same PostgreSQL transaction that takes the stock and writes the order. Options in MongoDB would mean a second database inside that transaction, with no common commit.
- **The shape changes without a migration.** Sizes, extras, removals and allergens differ from restaurant to restaurant, and a new kind of option needs no schema change. Tables would need one table per kind, or a generic key/value table.
- **It is still validated.** The Pydantic model `ItemOption` (`app/schemas/catalogue.py`) checks the shape when the menu is returned. When an order chooses options, `price_line` (`app/services/pricing.py`) checks each choice against the item's options and refuses an invalid one with 409.
- **The order keeps a snapshot.** Each order line stores the chosen options as `jsonb`, so a later menu change does not change past orders. The export copies that snapshot into `report_orders.lines[].options`.

## Report export: `mongodb/export_reports.py`

- **Reads** PostgreSQL with `READONLY_DATABASE_URL` (`fd_readonly`, read-only by grant and by `default_transaction_read_only`): finished orders with their lines, cuisines and status history, and every delivery offer.
- **Writes** `report_orders` and `report_offers` with the app's `readWrite` user.
- **How:** empties each collection and inserts again, 5,000 documents per `insert_many`. The rows come from a server-side cursor (`yield_per`), so 400k orders never sit in memory at once.
- **When:** `scripts/seed.sh` runs it after the PostgreSQL seed; it can be run again at any time to refresh the reports: `uv run python mongodb/export_reports.py`.
- **On the seeded data:** 414,345 orders and 597,425 offers in about 2 minutes. Every document passed the validators (an invalid one makes `insert_many` fail).

## Report pipelines

Each pipeline is a file in `mongodb/pipelines/` with a `build()` function. `GET /backoffice/reports/{report_name}` (F8) runs it on its collection and returns the rows. Samples below are from that endpoint on the seeded data.

| Report name | File | Brief question | Owner |
|---|---|---|---|
| `delivery-time` | `delivery_time.py` | 1 | jcleberfernandes |
| `cancellations` | `cancellations.py` | 4 | RodrigoDias123 |
| `restaurant-times` | `restaurant_times.py` | 5 | jcleberfernandes |

### Pipeline 1: delivery time per zone and hour

**Question:** average delivery time (from `placed` to `delivered`) per zone and per hour of the day, for the last 30 days.

**Stages:** `$match` delivered orders placed in the last 30 days (uses `status_placed_at`) → `$group` by customer zone and the **Lisbon** hour of `placed_at` (`$hour` with `timezone: "Europe/Lisbon"`, so 12h means lunchtime), averaging `delivered_at - placed_at` → `$project` to minutes → `$sort` by zone and hour.

`GET /backoffice/reports/delivery-time`: 888 rows, 0.2 s. Sample (zone 1, Baixa in Lisboa):

```json
[
  {"orders": 354, "zone_id": 1, "zone": "Baixa", "hour": 12, "avg_delivery_minutes": 65.6},
  {"orders": 145, "zone_id": 1, "zone": "Baixa", "hour": 13, "avg_delivery_minutes": 61.4},
  {"orders": 401, "zone_id": 1, "zone": "Baixa", "hour": 20, "avg_delivery_minutes": 63.8}
]
```

### Pipeline 4: cancellations by reason and actor

**Question:** cancellations by reason and by who cancelled, per restaurant, in the last 90 days.

**Stages:** `$match` orders placed in the last 90 days → `$group` by restaurant and (actor, reason) → `$group` by restaurant, counting orders and cancellations → `$match` restaurants with at least one cancellation → `$project` the cancel rate and the split sorted by count → `$sort` by cancellations. All orders are read, not only cancelled ones, so the rate can be computed.

`GET /backoffice/reports/cancellations`: 1,065 rows, 0.35 s. Sample (first row, split cut to the top 3):

```json
{
  "orders": 7638, "cancelled": 364, "restaurant_id": 1176, "restaurant": "Bistrô do Chef",
  "cancel_rate_pct": 4.8,
  "by_actor_and_reason": [
    {"cancelled_by": "customer",   "reason": "customer_changed_mind", "count": 132},
    {"cancelled_by": "backoffice", "reason": "courier_unavailable",   "count": 57},
    {"cancelled_by": "restaurant", "reason": "restaurant_too_busy",   "count": 47}
  ]
}
```

### Pipeline 5: restaurant acceptance and preparation times

**Question:** for each restaurant, the average time between `placed` and `accepted`, and between `accepted` and `ready`.

**Stages:** `$match` orders that were accepted → `$group` by restaurant, averaging `accepted_at - placed_at` and `ready_at - accepted_at` → `$project` to minutes → `$sort` by name. An order cancelled before `ready` has no `ready_at`: the subtraction is null and `$avg` skips it, so it still counts for the acceptance time.

`GET /backoffice/reports/restaurant-times`: 1,200 rows, 1.1 s. Sample:

```json
[
  {"orders": 1230, "restaurant_id": 922,  "restaurant": "A Taberna Central", "avg_accept_minutes": 4.3, "avg_prepare_minutes": 32.1},
  {"orders": 159,  "restaurant_id": 1105, "restaurant": "A Taberna Central", "avg_accept_minutes": 3.5, "avg_prepare_minutes": 25.4},
  {"orders": 172,  "restaurant_id": 840,  "restaurant": "A Taberna Central", "avg_accept_minutes": 3.8, "avg_prepare_minutes": 27.0}
]
```

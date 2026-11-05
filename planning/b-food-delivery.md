# Project B: Food delivery

Read [README.md](README.md) first. It has the rules, requirements, documentation, Git rules and grading that apply to this project. This file describes the business.

## Context

A food delivery company connects customers, restaurants and couriers in several Portuguese cities. A customer orders from a restaurant through the app, the restaurant prepares the food, and a courier picks it up and delivers it.

The hard part of the business is dinner time. At 20:00 thousands of orders arrive in a few minutes, each order is offered to several couriers at once, and the first one to accept takes it. If two couriers both think they won, both ride to the restaurant, one goes home without pay, and the company pays for it. Restaurants have the same problem with limited dishes: a restaurant that cooks 30 portions of the dish of the day cannot accept 31 orders.

## Actors

- **Customer**: orders food and follows the delivery.
- **Restaurant**: manages its menu, accepts or rejects orders, marks them as ready.
- **Courier**: goes online, receives offers, accepts one, picks up and delivers.
- **Back office**: the company's staff, who manage zones, fees and restaurants and read reports.

## Requirements

Everything below must be representable in your design. Names in this section are business names, not table or column names: the schema is yours to design.

### Cities and zones

- The company works in several cities. Each city is divided into delivery zones with a name (unique within the city).
- A customer address and a restaurant are in exactly one zone.
- The delivery fee depends on the restaurant's zone and the customer's zone. The back office sets a fee for every pair of zones a restaurant delivers to, at most one fee per pair. A restaurant only delivers to the zones that have a fee set for its zone.

### Customers

- A customer has a name, an email (unique), a phone number (unique), a password hash and the date they registered.
- A customer has one or more addresses (street, number, floor, postcode, zone, notes for the courier, latitude and longitude). One of them is the default. A customer has at most one default address.

### Restaurants and menus

- A restaurant has a name, a Portuguese tax number (NIF, 9 digits, unique), an address in a zone, latitude and longitude, one or more cuisine types (Portuguese, Italian, Japanese, vegan, ...), a minimum order value in euros, and a status: `open`, `closed` or `suspended`.
- A restaurant has opening hours per day of the week, with one or more periods per day (for example 12:00 to 15:00 and 19:00 to 23:00). Two periods of the same restaurant on the same day cannot overlap. A period may be the whole day (00:00 to 24:00).
- A restaurant has a **kitchen capacity**: the maximum number of orders it can have in preparation at the same time (accepted but not yet picked up).
- A restaurant's menu has categories (starters, mains, desserts, drinks), and each category has items. An item has a name, a description, a price in euros, a status (`available` or `unavailable`) and, optionally, a **daily stock**: the number of portions the restaurant makes that day. When the daily stock reaches 0, the item cannot be ordered until the next day. The daily stock goes back to its configured value at midnight, Lisbon time.
- Items have options that differ from restaurant to restaurant, and the company wants to add new kinds without changing the database. For example: size (small, medium, large, each with an extra price), extras (cheese +1.00 €, bacon +1.50 €, up to 3 extras), cooking point (rare, medium, well done), removals (no onion), allergens and dietary labels.

### Couriers

- A courier has a name, an email (unique), a phone number (unique), a vehicle type (`bicycle`, `scooter` or `car`), a licence plate (unique, mandatory for scooter and car, absent for bicycle) and a status (`active` or `blocked`).
- A courier is either online or offline. While online, the app sends their position every few seconds. A courier who sends no position for 30 seconds is offline.
- A courier can carry at most a number of active deliveries at the same time, depending on the vehicle: **bicycle 1, scooter 2, car 3**. A delivery is active from the moment the courier accepts it until it is delivered or cancelled.

### Orders

- An order belongs to one customer and one restaurant and is delivered to one of the customer's addresses. The order keeps a copy of the address as it was when the order was placed: if the customer later edits the address, past orders do not change.
- An order has one or more lines. A line has a menu item, a quantity (at least 1), the options chosen, and the unit price at the time of the order (item price plus options). If the restaurant later changes the price, past orders do not change.
- An order has a subtotal (sum of the lines), the delivery fee, an optional tip (zero or more) and a total (subtotal plus fee plus tip). The subtotal must be at least the restaurant's minimum order value.
- An order can only be placed if the restaurant is `open`, the time is within its opening hours, it delivers to the customer's zone, and every item is `available` with enough daily stock. Placing an order takes the portions from the daily stock.
- An order goes through these statuses, in this order: `placed`, `accepted`, `preparing`, `ready`, `picked_up`, `delivered`. From `placed` it can go to `rejected` (by the restaurant). From any status before `picked_up` it can go to `cancelled` (by the customer, the restaurant or the back office, with a reason). No other transition is allowed. A rejected or cancelled order gives its portions back to the daily stock.
- Every change of status is recorded with the old status, the new status, who made it and when. The history of an order is never changed or deleted.
- A restaurant cannot accept an order if it already has as many orders in preparation (`accepted`, `preparing` or `ready`) as its kitchen capacity.
- A payment belongs to one order and has an amount, a method (`card`, `mbway` or `cash`), a status (`approved`, `declined` or `refunded`), the date and time, and a provider reference (unique, absent for cash). Payments are simulated: the request to place an order carries a field `simulate` with the value `approved` or `declined`. A declined payment means the order is not placed and no portion is taken.
- A cancelled order that was paid by card or MB WAY gets a payment with status `refunded` and the same amount.

### Delivery offers

- When a restaurant accepts an order, the app offers it to up to 5 online couriers within 3 km of the restaurant who still have room for another delivery.
- An offer expires **45 seconds** after it is sent.
- The first courier to accept a valid offer gets the order. **An order is assigned to exactly one courier.** Every other offer for that order is then withdrawn. A courier who accepts an offer that is expired, withdrawn or already taken gets a refusal.
- If every offer of an order expired or was refused, the restaurant or the back office calls an endpoint to offer it again to the next couriers. No worker is required for this.
- Every offer is recorded with the courier, the order, when it was sent and its outcome (`pending`, `accepted`, `rejected`, `expired`, `withdrawn`). An offer can be marked `expired` when it is next read or offered again; it does not need to change at the exact second.
- The delivery records the courier, when they accepted, picked up and delivered the order, and the distance travelled.

Redis has commands for positions: `GEOADD` stores a member with its longitude and latitude, and `GEOSEARCH` finds the members within a radius. A member of a geo set cannot have its own TTL, so keep online presence in a separate key per courier with `SET ... EX 30`, and filter the search results by that key. See the [Redis geospatial documentation](https://redis.io/docs/latest/develop/data-types/geospatial/).

### Ratings

- After an order is `delivered`, the customer can rate the restaurant and the courier, each from 1 to 5, with an optional comment. Each order is rated at most once. Ratings come from the seed; an endpoint to create them is an extension.

## Where the rules are enforced

Must be enforced by PostgreSQL:

- An order has at most one courier assigned.
- An item's daily stock is never negative.
- Two opening periods of the same restaurant on the same day never overlap.
- A customer has at most one default address.
- A licence plate is present for scooters and cars and absent for bicycles.
- Prices, fees, tips, totals and quantities are within their ranges (never negative; quantity at least 1; rating from 1 to 5).
- Unique values: zone name within its city, fee per pair of zones, customer email and phone, restaurant NIF, courier email, phone and plate, provider reference, one rating per order.
- A NIF has exactly 9 digits; statuses, vehicle types and payment methods only take the values listed above.
- The status history is never updated or deleted by the app role.

May be enforced in PostgreSQL or in the app (say which in `docs/postgres.md`):

- The allowed status transitions.
- The kitchen capacity of a restaurant.
- The maximum active deliveries per vehicle.
- The minimum order value; ordering only within opening hours and to delivered zones.

## Flows the app must implement

All flows are mandatory. F2 and F4 are the concurrent flows (F3 too, if you cover rule 4 below).

| Flow | Description |
|------|-------------|
| F1. Browse | List the restaurants that are open now and deliver to a given address, with the delivery fee and the average rating, and show a restaurant's menu with the options of each item. |
| F2. Place order | A customer places an order with every rule in [Orders](#orders), including the daily stock and the payment. |
| F3. Restaurant accepts or rejects | The restaurant accepts an order, respecting its kitchen capacity, and the order is offered to couriers; or rejects it. Includes the endpoint to offer an order again. |
| F4. Courier accepts | A courier accepts an offer. Exactly one courier gets each order. |
| F5. Status updates | The restaurant marks an order as preparing and ready; the courier marks it as picked up and delivered; the customer or the restaurant cancels it. Only the allowed transitions succeed. |
| F6. Track | The customer sees the status of their order and the courier's last known position. Customers poll this every few seconds. **Read from Redis**: a repeated request must not query PostgreSQL. |
| F7. Courier location | A courier goes online, sends their position, and goes offline. |
| F8. Reports | The back office reads the reports of [Reports](#reports-mongodb). |

## The concurrent flow

The rules under test are:

1. An order is assigned to exactly one courier.
2. An item's daily stock never goes below zero.
3. A courier never has more active deliveries than their vehicle allows.
4. A restaurant never has more orders in preparation than its kitchen capacity.

Project must cover at least these two scenarios:

- **Same order** (F4). The fixture creates an accepted order and 50 online couriers, each with a `pending` offer for that order. The limit of 5 offers per order does not apply to the fixture. All 50 couriers accept at the same moment. Exactly one gets the order and 49 are refused. At the end, PostgreSQL shows exactly one courier for the order.
- **Last portions** (F2). The fixture creates a restaurant open 00:00 to 24:00 every day, an item with a daily stock of 30, and 60 customers with addresses in a zone it delivers to. All 60 order one portion at the same moment, with `simulate=approved`. Exactly 30 orders are placed and 30 refused, and the stock ends at 0.

Covering rules 3 and 4 too is a good extension. Rule 3 is a write skew, as in session 08: a scooter courier with one delivery accepts two offers at the same moment.

## MongoDB collections

Mandatory:

- **Courier position trail**: one document per position received (courier, longitude and latitude, time, and the order if they are on a delivery). Written by F7. Kept for 7 days, with a TTL index.
- **Report collections**: the derived collections written by the report export (see the README), with the data your pipelines need: for example one document per delivered order with its lines, times and offers. The shape is yours to design.

You decide:

- Where the item options (see [Restaurants and menus](#restaurants-and-menus)) are stored: in MongoDB, in a `jsonb` column, or in tables. Justify the choice in `docs/mongodb.md`.

## Reports (MongoDB)

Your pipelines must answer at least 3 of these:

1. Average delivery time (from `placed` to `delivered`) per zone and per hour of the day, for the last 30 days.
2. The 10 best-selling items per cuisine type in each city in the last 30 days, with the options most often chosen.
3. Courier earnings per week: number of deliveries, distance, delivery fees and tips.
4. Cancellations by reason and by who cancelled, per restaurant, in the last 90 days.
5. For each restaurant, the average time between `placed` and `accepted`, and between `accepted` and `ready`.
6. The share of offers that expired without an answer, per zone and per hour of the day.

## Real-time features (Redis)

- The position of every online courier, and the search for online couriers within 3 km of a restaurant.
- Whether a courier is online.
- The pending offers, with their 45-second expiry.
- The status and the courier position that F6 returns.
- The remaining daily stock of each item, during the day.
- A ranking of the 20 restaurants with most delivered orders in the last hour, per city.

## Data that expires

| Data | How long it lives | Where |
|------|-------------------|-------|
| A delivery offer | 45 seconds after it is sent | you decide |
| A courier's online presence | 30 seconds after their last position | you decide |
| A courier's last position | while they are online | you decide |
| The daily stock of an item | until midnight, Lisbon time | you decide |
| The courier position trail | 7 days | MongoDB, with a TTL index |

Document each decision in `docs/architecture.md`.

## Frequent queries (PostgreSQL)

Use at least 3 of these for the `EXPLAIN` evidence required in the README:

1. The restaurants open now that deliver to a given zone, with their fee.
2. The orders of a customer, newest first, 20 per page.
3. The orders of a restaurant in `accepted`, `preparing` or `ready` (the kitchen screen).
4. The active deliveries of a courier.
5. The status history of an order.
6. The average rating of a restaurant in the last 90 days.

## Seed volumes

| Data | Volume |
|------|--------|
| Cities | 5, with 8 to 15 zones each |
| Customers | 60,000, with 1 to 3 addresses each |
| Restaurants | 1,200 |
| Menu items | about 30,000 |
| Couriers | 2,500 |
| Orders | at least 400,000, over the last 12 months |
| Order lines | at least 1,000,000 |
| Status changes | one per status an order went through |
| Delivery offers | about 1.5 per delivered order |
| Ratings | for about 40% of delivered orders |
| Courier position trail (MongoDB) | at least 50,000 documents, within the last 7 days |
| Report collections (MongoDB) | written by the report export from the seeded data |

Most orders are `delivered`. About 5% are `cancelled` and 2% `rejected`, with the reasons and refunds that apply. Some restaurants and items sell far more than others.

## Ideas to go further

- An endpoint for customers to rate a delivered order, within 7 days of delivery.
- Batched deliveries: a car courier picks up two orders from the same restaurant at once.
- Surge pricing: the delivery fee of a zone rises when there are more waiting orders than online couriers.
- Scheduled orders for a later time, which only enter the kitchen capacity at the right moment.
- A worker that offers orders again automatically when every offer has expired.
"""Catalogue seed: cities, zones, fees, customers, addresses, restaurants, hours and menus.

The first PostgreSQL seed (see scripts/seed.sh); B's orders seed reads what it writes.
Deterministic (random.seed(42)) and uneven: Lisboa and Porto get most customers and
restaurants, and a few cuisines dominate. Loaded with COPY; every row respects the
constraints. Runs as fd_app, so ids come from nextval (fd_app cannot setval).
    uv run python postgres/seed/catalogue.py
"""

import json
import math
import random
import time
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import psycopg

from app.config import settings

random.seed(42)

CUSTOMERS = 60_000
RESTAURANTS = 1_200
NEARBY_KM = 3.0  # zones closer than this deliver to each other
CENT = Decimal("0.01")

# name: (lat, lng, share of customers and restaurants, postcode prefix, zone names)
CITIES: dict[str, tuple[float, float, int, str, list[str]]] = {
    "Lisboa": (
        38.7223,
        -9.1393,
        40,
        "1",
        [
            "Baixa",
            "Chiado",
            "Alfama",
            "Graça",
            "Belém",
            "Alcântara",
            "Estrela",
            "Campo de Ourique",
            "Avenidas Novas",
            "Arroios",
            "Alvalade",
            "Benfica",
            "Lumiar",
            "Parque das Nações",
            "Marvila",
        ],
    ),
    "Porto": (
        41.1579,
        -8.6291,
        25,
        "4",
        [
            "Baixa",
            "Ribeira",
            "Boavista",
            "Foz do Douro",
            "Cedofeita",
            "Bonfim",
            "Campanhã",
            "Paranhos",
            "Ramalde",
            "Aldoar",
            "Lordelo do Ouro",
            "Massarelos",
            "Antas",
            "Asprela",
            "Miragaia",
        ],
    ),
    "Braga": (
        41.5454,
        -8.4265,
        12,
        "47",
        [
            "Centro",
            "São Vicente",
            "São Victor",
            "Maximinos",
            "Gualtar",
            "Lamaçães",
            "Nogueiró",
            "Ferreiros",
            "Real",
            "Fraião",
            "Sé",
            "Cividade",
            "Lomar",
            "Esporões",
            "Palmeira",
        ],
    ),
    "Coimbra": (
        40.2033,
        -8.4103,
        12,
        "30",
        [
            "Baixa",
            "Alta",
            "Solum",
            "Celas",
            "Santa Clara",
            "Olivais",
            "Eiras",
            "Santo António dos Olivais",
            "Vale das Flores",
            "Bairro Norton de Matos",
            "Pedrulha",
            "Loreto",
            "Sé Nova",
            "Santa Cruz",
            "São Martinho",
        ],
    ),
    "Faro": (
        37.0194,
        -7.9304,
        11,
        "80",
        [
            "Baixa",
            "Sé",
            "São Pedro",
            "Montenegro",
            "Gambelas",
            "Penha",
            "Bom João",
            "Montechoro",
            "Patacão",
            "Estoi",
            "Conceição",
            "Santa Bárbara",
            "Ilha de Faro",
            "Campina",
            "Areal Gordo",
        ],
    ),
}

FIRST = [
    "Ana",
    "João",
    "Maria",
    "Pedro",
    "Inês",
    "Tiago",
    "Sofia",
    "Rui",
    "Beatriz",
    "Miguel",
    "Carla",
    "Nuno",
    "Rita",
    "Bruno",
    "Marta",
    "Diogo",
    "Joana",
    "André",
    "Catarina",
    "Luís",
]
LAST = [
    "Silva",
    "Santos",
    "Ferreira",
    "Pereira",
    "Oliveira",
    "Costa",
    "Rodrigues",
    "Martins",
    "Sousa",
    "Fernandes",
    "Gonçalves",
    "Gomes",
    "Lopes",
    "Marques",
    "Alves",
    "Almeida",
    "Ribeiro",
    "Pinto",
    "Carvalho",
    "Teixeira",
]
STREETS = [
    "Rua da Liberdade",
    "Rua Direita",
    "Avenida da República",
    "Rua do Comércio",
    "Rua de Santo António",
    "Travessa do Carmo",
    "Rua das Flores",
    "Avenida Central",
    "Rua Nova",
    "Largo do Rossio",
    "Rua do Sol",
    "Rua da Paz",
]
FLOORS = [None, None, "R/C", "1.º Esq", "1.º Dto", "2.º Esq", "2.º Dto", "3.º"]
NOTES = [None, None, None, "Tocar à campainha", "Deixar na portaria", "Ligar ao chegar"]

# Uneven on purpose: the first cuisines are picked far more often (Zipf-like weights).
CUISINES = [
    "Portuguesa",
    "Pizza",
    "Hambúrgueres",
    "Sushi",
    "Italiana",
    "Chinesa",
    "Indiana",
    "Mexicana",
    "Vegetariana",
    "Brasileira",
    "Marisqueira",
    "Kebab",
    "Saudável",
    "Sobremesas",
]
CUISINE_WEIGHTS = [1 / (k + 1) for k in range(len(CUISINES))]
NAME_START = [
    "Casa",
    "Tasca",
    "Cantinho",
    "Sabores",
    "Restaurante",
    "Bistrô",
    "O Forno",
    "A Taberna",
    "Cozinha",
    "Petiscos",
]
NAME_END = [
    "do Bairro",
    "da Avó",
    "do Mar",
    "Central",
    "Real",
    "do Largo",
    "Dourado",
    "da Esquina",
    "Lusitano",
    "do Chef",
]

# category: (share of a menu's items, price range in euros, item names)
MENU: dict[str, tuple[int, tuple[int, int], list[str]]] = {
    "Entradas": (
        20,
        (3, 8),
        [
            "Pão com manteiga",
            "Azeitonas",
            "Sopa do dia",
            "Salada mista",
            "Pastéis de bacalhau",
            "Chouriço assado",
        ],
    ),
    "Pratos principais": (
        50,
        (8, 18),
        [
            "Bacalhau à Brás",
            "Bitoque",
            "Frango assado",
            "Hambúrguer clássico",
            "Pizza margherita",
            "Lasanha",
            "Caril de frango",
            "Sushi variado",
            "Polvo à lagareiro",
            "Arroz de pato",
            "Francesinha",
            "Wrap vegetariano",
        ],
    ),
    "Sobremesas": (
        15,
        (3, 6),
        [
            "Pastel de nata",
            "Mousse de chocolate",
            "Arroz doce",
            "Bolo de bolacha",
            "Gelado",
            "Fruta",
        ],
    ),
    "Bebidas": (
        15,
        (1, 4),
        ["Água", "Refrigerante", "Sumo natural", "Café", "Cerveja", "Vinho da casa"],
    ),
}
ALLERGENS = ["gluten", "lactose", "eggs", "nuts", "fish", "shellfish", "soy"]


def km(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Haversine distance between two (lat, lng) points."""
    lat1, lng1, lat2, lng2 = map(math.radians, (*a, *b))
    h = (
        math.sin((lat2 - lat1) / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin((lng2 - lng1) / 2) ** 2
    )
    return 2 * 6371 * math.asin(math.sqrt(h))


def near(point: tuple[float, float], spread: float) -> tuple[Decimal, Decimal]:
    """A point a little away from `point`, as numeric(9,6)."""
    lat = point[0] + random.uniform(-spread, spread)
    lng = point[1] + random.uniform(-spread, spread)
    return Decimal(f"{lat:.6f}"), Decimal(f"{lng:.6f}")


def money(low: float, high: float, step: float = 0.5) -> Decimal:
    """A price between low and high, in steps of 50 cents."""
    steps = int((high - low) / step)
    return (Decimal(str(low)) + Decimal(str(step)) * random.randint(0, steps)).quantize(
        CENT
    )


def ids(cur: psycopg.Cursor, table: str, n: int) -> list[int]:
    """Reserve n ids from the table's sequence (fd_app may use it, not set it)."""
    cur.execute(
        "SELECT nextval(pg_get_serial_sequence(%s, 'id')) FROM generate_series(1, %s)",
        (table, n),
    )
    return [row[0] for row in cur.fetchall()]


def copy(
    cur: psycopg.Cursor, table: str, columns: list[str], rows: list[tuple]
) -> None:
    with cur.copy(f"COPY {table} ({', '.join(columns)}) FROM STDIN") as cp:
        for row in rows:
            cp.write_row(row)
    print(f"  {table}: {len(rows)}")


def opening_periods(restaurant_id: int) -> list[tuple[int, int, str]]:
    """Non-overlapping hours: some 24h, some lunch + dinner, some one long period.

    Built so two periods of one day never touch, which the EXCLUDE would refuse.
    """
    kind = random.choices(["24h", "split", "long"], [5, 45, 50])[0]
    if kind == "24h":
        return [(restaurant_id, day, "[0,1440)") for day in range(7)]
    day_off = random.randrange(7) if random.random() < 0.35 else None
    if kind == "split":
        periods = ["[690,900)", "[1140,1380)"]  # 11:30-15:00 and 19:00-23:00
    else:
        start = random.choice([600, 660, 720])
        end = random.choice([1320, 1380, 1440])
        periods = [f"[{start},{end})"]
    return [
        (restaurant_id, day, hours)
        for day in range(7)
        if day != day_off
        for hours in periods
    ]


def item_options(category: str) -> list[dict[str, Any]]:
    """Options in the shape app/schemas/catalogue.py validates (ChoiceOption, LabelOption)."""
    options: list[dict[str, Any]] = []
    if category == "Pratos principais":
        if random.random() < 0.6:
            options.append(
                {
                    "type": "size",
                    "required": True,
                    "choices": [
                        {"name": "small", "extra": 0},
                        {"name": "medium", "extra": 1.5},
                        {"name": "large", "extra": 3.0},
                    ],
                }
            )
        if random.random() < 0.5:
            options.append(
                {
                    "type": "extras",
                    "max": 3,
                    "choices": [
                        {"name": "cheese", "extra": 1.0},
                        {"name": "bacon", "extra": 1.5},
                        {"name": "egg", "extra": 0.8},
                        {"name": "mushrooms", "extra": 0.9},
                    ],
                }
            )
        if random.random() < 0.3:
            options.append(
                {
                    "type": "removals",
                    "choices": [
                        {"name": "no onion", "extra": 0},
                        {"name": "no tomato", "extra": 0},
                    ],
                }
            )
    if category == "Bebidas" and random.random() < 0.5:
        options.append(
            {
                "type": "size",
                "required": True,
                "choices": [
                    {"name": "small", "extra": 0},
                    {"name": "large", "extra": 1.0},
                ],
            }
        )
    if category != "Bebidas" and random.random() < 0.4:
        options.append(
            {
                "type": "allergens",
                "values": sorted(random.sample(ALLERGENS, random.randint(1, 3))),
            }
        )
    return options


def main() -> None:
    start = time.monotonic()
    url = settings.database_url.replace("postgresql+psycopg://", "postgresql://")
    with psycopg.connect(url) as conn, conn.cursor() as cur:
        cur.execute("SELECT EXISTS (SELECT 1 FROM cities WHERE name = 'Lisboa')")
        if cur.fetchone()[0]:
            print("  catalogue already seeded: skipped")
            return
        now = datetime.now(UTC)

        # Cities and zones: zones spiral out from the city centre, about 0.6 km apart.
        city_ids = dict(zip(CITIES, ids(cur, "cities", len(CITIES)), strict=True))
        zones: list[tuple[int, int, str, tuple[float, float]]] = []
        for city, (lat, lng, _, _, names) in CITIES.items():
            count = random.randint(8, 15)
            for k, zone_id in enumerate(ids(cur, "zones", count)):
                angle, radius = k * 2.4, 0.006 * math.sqrt(k)
                centre = (
                    lat + radius * math.sin(angle),
                    lng + radius * math.cos(angle),
                )
                zones.append((zone_id, city_ids[city], names[k], centre))
        copy(cur, "cities", ["id", "name"], [(i, n) for n, i in city_ids.items()])
        copy(cur, "zones", ["id", "city_id", "name"], [z[:3] for z in zones])

        # Fees: every pair of zones of the same city closer than NEARBY_KM (itself too).
        fees = [
            (
                a[0],
                b[0],
                (
                    Decimal("1.50") + Decimal("0.40") * Decimal(f"{km(a[3], b[3]):.2f}")
                ).quantize(CENT),
            )
            for a in zones
            for b in zones
            if a[1] == b[1] and km(a[3], b[3]) <= NEARBY_KM
        ]
        copy(cur, "zone_fees", ["restaurant_zone_id", "customer_zone_id", "fee"], fees)

        # Big cities get more customers and restaurants: pick the city by its share.
        by_city = {cid: [z for z in zones if z[1] == cid] for cid in city_ids.values()}
        city_list = list(city_ids.values())
        shares = [c[2] for c in CITIES.values()]
        postcode = {city_ids[n]: c[3] for n, c in CITIES.items()}

        def pick_zone() -> tuple[int, int, str, tuple[float, float]]:
            return random.choice(by_city[random.choices(city_list, shares)[0]])

        # Customers and 1-3 addresses each; the first one is the default.
        customers, addresses = [], []
        for n, cid in enumerate(ids(cur, "customers", CUSTOMERS)):
            name = f"{random.choice(FIRST)} {random.choice(LAST)}"
            # Not a real hash: the project has no authentication.
            customers.append(
                (
                    cid,
                    name,
                    f"customer{n}@example.pt",
                    f"+3519{n:08d}",
                    "!",
                    now - timedelta(days=random.randint(0, 730)),
                )
            )
            for a in range(random.choices([1, 2, 3], [60, 30, 10])[0]):
                zone = pick_zone()
                lat, lng = near(zone[3], 0.003)
                code = postcode[zone[1]]
                pc = f"{code}{random.randint(0, 10 ** (4 - len(code)) - 1):0{4 - len(code)}d}"
                addresses.append(
                    (
                        cid,
                        zone[0],
                        random.choice(STREETS),
                        str(random.randint(1, 300)),
                        random.choice(FLOORS),
                        f"{pc}-{random.randint(0, 999):03d}",
                        random.choice(NOTES),
                        lat,
                        lng,
                        a == 0,
                    )
                )
        copy(
            cur,
            "customers",
            ["id", "name", "email", "phone", "password_hash", "registered_at"],
            customers,
        )
        copy(
            cur,
            "customer_addresses",
            [
                "customer_id",
                "zone_id",
                "street",
                "number",
                "floor",
                "postcode",
                "notes",
                "lat",
                "lng",
                "is_default",
            ],
            addresses,
        )

        # Restaurants, their cuisines and hours.
        cuisine_ids = ids(cur, "cuisines", len(CUISINES))
        copy(
            cur,
            "cuisines",
            ["id", "name"],
            list(zip(cuisine_ids, CUISINES, strict=True)),
        )
        restaurants, links, hours = [], [], []
        for n, rid in enumerate(ids(cur, "restaurants", RESTAURANTS)):
            zone = pick_zone()
            lat, lng = near(zone[3], 0.003)
            name = f"{random.choice(NAME_START)} {random.choice(NAME_END)}"
            status = random.choices(["open", "closed", "suspended"], [92, 5, 3])[0]
            restaurants.append(
                (
                    rid,
                    zone[0],
                    name,
                    f"{500_000_000 + n}",
                    f"{random.choice(STREETS)}, {random.randint(1, 300)}",
                    lat,
                    lng,
                    money(5, 15),
                    random.randint(3, 15),
                    status,
                )
            )
            chosen: set[int] = set()
            while len(chosen) < random.choices([1, 2, 3], [50, 35, 15])[0]:
                chosen.add(random.choices(cuisine_ids, CUISINE_WEIGHTS)[0])
            links += [(rid, c) for c in sorted(chosen)]
            hours += opening_periods(rid)
        copy(
            cur,
            "restaurants",
            [
                "id",
                "zone_id",
                "name",
                "nif",
                "address",
                "lat",
                "lng",
                "min_order_value",
                "kitchen_capacity",
                "status",
            ],
            restaurants,
        )
        copy(cur, "restaurant_cuisines", ["restaurant_id", "cuisine_id"], links)
        copy(cur, "opening_periods", ["restaurant_id", "weekday", "hours"], hours)

        # Menus: 10-40 items per restaurant (about 30k), spread over the 4 categories.
        category_ids = ids(cur, "menu_categories", RESTAURANTS * len(MENU))
        categories, items = [], []
        for r, (rid, *_) in enumerate(restaurants):
            size = random.randint(10, 40)
            for c, (cat, (share, (low, high), names)) in enumerate(MENU.items()):
                cat_id = category_ids[r * len(MENU) + c]
                categories.append((cat_id, rid, cat))
                for _ in range(max(1, size * share // 100)):
                    stock = random.randint(20, 80) if random.random() < 0.15 else None
                    status = "available" if random.random() < 0.95 else "unavailable"
                    items.append(
                        (
                            cat_id,
                            random.choice(names),
                            None,
                            money(low, high),
                            status,
                            stock,
                            json.dumps(item_options(cat)),
                        )
                    )
        copy(cur, "menu_categories", ["id", "restaurant_id", "name"], categories)
        copy(
            cur,
            "menu_items",
            [
                "category_id",
                "name",
                "description",
                "price",
                "status",
                "daily_stock",
                "options",
            ],
            items,
        )
    print(f"  catalogue seed done in {time.monotonic() - start:.1f} s")


if __name__ == "__main__":
    main()

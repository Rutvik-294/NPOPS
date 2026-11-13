"""NPOPS seed data — the world, the workshop, and its people.

Region/city data are real geographic coordinates (approximate city
centers) so the VRP engine produces genuinely plausible routes.
"""
from __future__ import annotations

import datetime as dt
import random

from .models import (User, Region, City, GiftCatalog, BomLine, WorkCenter,
                     Child, WishList, InventoryItem)
from .security import hash_password
from .auth import utcnow_iso

REGIONS = [
    # name, tz_offset(hours), night_hours
    ("Oceania & East Asia", 9.0, 10.0),
    ("Central & South Asia", 5.5, 10.0),
    ("Eastern Europe & Middle East", 3.0, 10.0),
    ("Western & Northern Europe", 1.0, 11.0),
    ("Atlantic & South America", -3.0, 10.0),
    ("North America East", -5.0, 11.0),
    ("North America West", -8.0, 11.0),
]

# city, country, region_idx, lat, lon, pop, children
CITIES = [
    ("Tokyo", "Japan", 0, 35.6762, 139.6503, 13960000, 1900000),
    ("Osaka", "Japan", 0, 34.6937, 135.5023, 2691000, 380000),
    ("Seoul", "South Korea", 0, 37.5665, 126.9780, 9776000, 1300000),
    ("Beijing", "China", 0, 39.9042, 116.4074, 21540000, 2900000),
    ("Shanghai", "China", 0, 31.2304, 121.4737, 24870000, 3400000),
    ("Hong Kong", "China", 0, 22.3193, 114.1694, 7482000, 950000),
    ("Taipei", "Taiwan", 0, 25.0330, 121.5654, 2646000, 340000),
    ("Manila", "Philippines", 0, 14.5995, 120.9842, 13480000, 2400000),
    ("Singapore", "Singapore", 0, 1.3521, 103.8198, 5686000, 780000),
    ("Jakarta", "Indonesia", 0, -6.2088, 106.8456, 10560000, 1900000),
    ("Sydney", "Australia", 0, -33.8688, 151.2093, 5312000, 800000),
    ("Melbourne", "Australia", 0, -37.8136, 144.9631, 4976000, 760000),
    ("Auckland", "New Zealand", 0, -36.8485, 174.7633, 1657000, 290000),
    ("Perth", "Australia", 0, -31.9505, 115.8605, 2059000, 310000),
    ("Delhi", "India", 1, 28.6139, 77.2090, 32900000, 4900000),
    ("Mumbai", "India", 1, 19.0760, 72.8777, 20410000, 3100000),
    ("Chennai", "India", 1, 13.0827, 80.2707, 7088000, 980000),
    ("Karachi", "Pakistan", 1, 24.8607, 67.0011, 14910000, 2300000),
    ("Dhaka", "Bangladesh", 1, 23.8103, 90.4125, 21741000, 3100000),
    ("Colombo", "Sri Lanka", 1, 6.9271, 79.8612, 561000, 95000),
    ("Kathmandu", "Nepal", 1, 27.7172, 85.3240, 1442000, 260000),
    ("Bangkok", "Thailand", 1, 13.7563, 100.5018, 10539000, 1400000),
    ("Kuala Lumpur", "Malaysia", 1, 3.1390, 101.6869, 1808000, 380000),
    ("Istanbul", "Turkey", 2, 41.0082, 28.9784, 15460000, 2800000),
    ("Cairo", "Egypt", 2, 30.0444, 31.2357, 20750000, 3900000),
    ("Tel Aviv", "Israel", 2, 32.0853, 34.7818, 4600000, 800000),
    ("Athens", "Greece", 2, 37.9838, 23.7275, 3153000, 400000),
    ("Bucharest", "Romania", 2, 44.4268, 26.1025, 1836000, 250000),
    ("Warsaw", "Poland", 2, 52.2297, 21.0122, 1794000, 250000),
    ("Kyiv", "Ukraine", 2, 50.4501, 30.5234, 2952000, 400000),
    ("Moscow", "Russia", 2, 55.7558, 37.6173, 12506000, 1700000),
    ("Vienna", "Austria", 2, 48.2082, 16.3738, 1915000, 250000),
    ("Budapest", "Hungary", 2, 47.4979, 19.0402, 1752000, 230000),
    ("Prague", "Czechia", 2, 50.0755, 14.4378, 1309000, 180000),
    ("Berlin", "Germany", 3, 52.5200, 13.4050, 3664000, 480000),
    ("Munich", "Germany", 3, 48.1351, 11.5820, 1488000, 200000),
    ("Hamburg", "Germany", 3, 53.5511, 9.9937, 1841000, 240000),
    ("Amsterdam", "Netherlands", 3, 52.3676, 4.9041, 1149000, 200000),
    ("Brussels", "Belgium", 3, 50.8503, 4.3517, 1209000, 190000),
    ("Paris", "France", 3, 48.8566, 2.3522, 11141000, 1700000),
    ("Lyon", "France", 3, 45.7640, 4.8357, 515695, 78000),
    ("Madrid", "Spain", 3, 40.4168, -3.7038, 6642000, 870000),
    ("Barcelona", "Spain", 3, 41.3874, 2.1686, 5586000, 720000),
    ("Lisbon", "Portugal", 3, 38.7223, -9.1393, 2960000, 380000),
    ("Rome", "Italy", 3, 41.9028, 12.4964, 4298000, 560000),
    ("Milan", "Italy", 3, 45.4642, 9.1900, 3140000, 410000),
    ("Zurich", "Switzerland", 3, 47.3769, 8.5417, 434335, 60000),
    ("Copenhagen", "Denmark", 3, 55.6761, 12.5683, 1334000, 210000),
    ("Stockholm", "Sweden", 3, 59.3293, 18.0686, 1615000, 250000),
    ("Oslo", "Norway", 3, 59.9139, 10.7522, 1064000, 170000),
    ("Helsinki", "Finland", 3, 60.1699, 24.9384, 1305000, 200000),
    ("Dublin", "Ireland", 3, 53.3498, -6.2603, 1263000, 220000),
    ("London", "United Kingdom", 3, 51.5074, -0.1278, 9426000, 1500000),
    ("Manchester", "United Kingdom", 3, 53.4808, -2.2426, 2677000, 370000),
    ("Edinburgh", "United Kingdom", 3, 55.9533, -3.1883, 524930, 70000),
    ("Reykjavik", "Iceland", 3, 64.1466, -21.9426, 139875, 25000),
    ("Reykjavik West", "Iceland", 4, 64.11, -22.5, 45000, 7000),
    ("Sao Paulo", "Brazil", 4, -23.5505, -46.6333, 22430000, 3800000),
    ("Rio de Janeiro", "Brazil", 4, -22.9068, -43.1729, 6748000, 1050000),
    ("Buenos Aires", "Argentina", 4, -34.6037, -58.3816, 15370000, 2200000),
    ("Santiago", "Chile", 4, -33.4489, -70.6693, 6812000, 950000),
    ("Lima", "Peru", 4, -12.0464, -77.0428, 9752000, 1600000),
    ("Bogota", "Colombia", 4, 4.7110, -74.0721, 7903000, 1300000),
    ("Caracas", "Venezuela", 4, 10.4806, -66.9036, 2245000, 380000),
    ("Panama City", "Panama", 4, 8.9824, -79.5199, 1800000, 300000),
    ("San Juan", "Puerto Rico", 4, 18.4655, -66.1057, 320000, 60000),
    ("New York", "United States", 5, 40.7128, -74.0060, 18823000, 2600000),
    ("Boston", "United States", 5, 42.3601, -71.0589, 4382000, 540000),
    ("Chicago", "United States", 5, 41.8781, -87.6298, 8865000, 1100000),
    ("Toronto", "Canada", 5, 43.6532, -79.3832, 6202000, 830000),
    ("Montreal", "Canada", 5, 45.5019, -73.5674, 4246000, 560000),
    ("Miami", "United States", 5, 25.7617, -80.1918, 6138000, 760000),
    ("Atlanta", "United States", 5, 33.7490, -84.3880, 6181000, 800000),
    ("Washington", "United States", 5, 38.9072, -77.0369, 6380000, 800000),
    ("Philadelphia", "United States", 5, 39.9526, -75.1652, 6245000, 780000),
    ("Mexico City", "Mexico", 5, 19.4326, -99.1332, 21914000, 3600000),
    ("Guadalajara", "Mexico", 5, 20.6597, -103.3496, 5343000, 760000),
    ("Havana", "Cuba", 5, 23.1136, -82.3666, 2131000, 320000),
    ("Los Angeles", "United States", 6, 34.0522, -118.2437, 12514000, 1600000),
    ("San Francisco", "United States", 6, 37.7749, -122.4194, 4656000, 520000),
    ("Seattle", "United States", 6, 47.6062, -122.3321, 4019000, 460000),
    ("Denver", "United States", 6, 39.7392, -104.9903, 2967000, 350000),
    ("Dallas", "United States", 6, 32.7767, -96.7970, 7639000, 920000),
    ("Houston", "United States", 6, 29.7604, -95.3698, 7338000, 900000),
    ("Phoenix", "United States", 6, 33.4484, -112.0740, 4971000, 560000),
    ("Vancouver", "Canada", 6, 49.2827, -123.1207, 2642000, 320000),
    ("Calgary", "Canada", 6, 51.0447, -114.0719, 1569000, 190000),
    ("Anchorage", "United States", 6, 61.2181, -149.9003, 291000, 55000),
    ("Honolulu", "United States", 6, 21.3069, -157.8583, 1016000, 130000),
]

GIFTS = [
    # sku, name, category, kg, dm3, cost, minutes, complexity
    ("WOOD-TRAIN", "Wooden Locomotive Set", "toys", 0.9, 4.5, 4.20, 22, 2),
    ("DOLL-CLOTH", "Hand-Stitched Doll", "toys", 0.35, 1.8, 3.10, 30, 3),
    ("ROBO-KIT", "Robot Construction Kit", "toys", 1.2, 6.0, 8.50, 26, 4),
    ("BIKE-16", "16-inch Bicycle", "outdoor", 8.5, 42.0, 34.00, 55, 5),
    ("BIKE-24", "24-inch Bicycle", "outdoor", 10.2, 50.0, 41.00, 62, 5),
    ("SKATE-BRD", "Maple Skateboard", "outdoor", 2.8, 14.0, 12.50, 24, 3),
    ("PUZZLE-1K", "1,000-Piece Puzzle", "games", 0.7, 2.2, 2.40, 9, 1),
    ("BOARD-GM", "Strategy Board Game", "games", 1.1, 5.5, 5.80, 14, 2),
    ("KNIT-SCARF", "Merino Knit Scarf", "apparel", 0.25, 1.0, 2.10, 18, 1),
    ("MITTENS", "Fleece Mittens", "apparel", 0.15, 0.6, 1.20, 8, 1),
    ("TELESCOPE", "Beginner Telescope", "science", 2.6, 15.0, 24.00, 42, 4),
    ("CHEM-SET", "Chemistry Lab Set", "science", 2.1, 9.0, 16.00, 30, 3),
    ("TED-BEAR", "Classic Teddy Bear", "toys", 0.4, 3.5, 2.90, 20, 2),
    ("DRUM-SET", "Junior Drum Kit", "music", 6.8, 38.0, 28.00, 48, 4),
    ("FLUTE", "Silver Flute", "music", 0.6, 2.8, 14.00, 36, 4),
    ("SCOOTER", "Kick Scooter", "outdoor", 3.4, 18.0, 11.00, 20, 3),
]

BOM = {
    "WOOD-TRAIN": [("RAW-PINE", 2.2), ("WHEEL-SET", 1), ("PAINT-ECO", 0.15)],
    "DOLL-CLOTH": [("FABRIC-COT", 0.8), ("YARN-WOOL", 0.3), ("STUFF-FLUF", 0.4)],
    "ROBO-KIT": [("PLASTIC-ABS", 1.5), ("CIRCUIT-BRD", 2), ("SCREW-M2", 24)],
    "BIKE-16": [("STEEL-TUBE", 5.5), ("WHEEL-16", 2), ("CHAIN-STD", 1), ("PAINT-ECO", 0.3)],
    "BIKE-24": [("STEEL-TUBE", 6.8), ("WHEEL-24", 2), ("CHAIN-STD", 1), ("PAINT-ECO", 0.4)],
    "SKATE-BRD": [("MAPLE-DECK", 1), ("TRUCK-ALU", 2), ("WHEEL-URE", 4)],
    "PUZZLE-1K": [("CARD-STOCK", 0.9), ("INK-SOY", 0.05)],
    "BOARD-GM": [("CARD-STOCK", 0.8), ("DICE-WD", 4), ("TOKEN-ABS", 40)],
    "KNIT-SCARF": [("YARN-WOOL", 0.5)],
    "MITTENS": [("FLEECE-POL", 0.3)],
    "TELESCOPE": [("LENS-GLASS", 2), ("ALU-TUBE", 1), ("TRIPOD-AL", 1)],
    "CHEM-SET": [("GLASS-WARE", 6), ("REAGENT-KIT", 1), ("PLASTIC-ABS", 0.5)],
    "TED-BEAR": [("STUFF-FLUF", 0.5), ("FABRIC-PLUSH", 0.6), ("EYE-BTN", 2)],
    "DRUM-SET": [("WOOD-PLY", 4.0), ("DRUM-SKIN", 3), ("HARDWARE-ST", 2.2)],
    "FLUTE": [("SILVER-TUBE", 0.7), ("KEY-ASSY", 14)],
    "SCOOTER": [("ALU-TUBE", 1.8), ("WHEEL-URE", 2), ("BEARING-ST", 4)],
}

RAW_MATERIALS = [
    ("RAW-PINE", "kg", 1200, 80, 300), ("WHEEL-SET", "unit", 800, 50, 200),
    ("PAINT-ECO", "liter", 400, 30, 120), ("FABRIC-COT", "meter", 2000, 100, 500),
    ("YARN-WOOL", "kg", 600, 40, 150), ("STUFF-FLUF", "kg", 900, 60, 200),
    ("PLASTIC-ABS", "kg", 1500, 100, 400), ("CIRCUIT-BRD", "unit", 2000, 120, 500),
    ("SCREW-M2", "unit", 50000, 5000, 20000), ("STEEL-TUBE", "kg", 3000, 200, 800),
    ("WHEEL-16", "unit", 1200, 80, 300), ("WHEEL-24", "unit", 1000, 60, 250),
    ("CHAIN-STD", "unit", 1600, 100, 400), ("MAPLE-DECK", "unit", 900, 60, 200),
    ("TRUCK-ALU", "unit", 1800, 120, 400), ("WHEEL-URE", "unit", 4000, 250, 1000),
    ("CARD-STOCK", "kg", 800, 50, 200), ("INK-SOY", "liter", 200, 15, 60),
    ("DICE-WD", "unit", 5000, 300, 1200), ("TOKEN-ABS", "unit", 40000, 4000, 15000),
    ("FLEECE-POL", "meter", 1500, 80, 300), ("LENS-GLASS", "unit", 700, 40, 150),
    ("ALU-TUBE", "kg", 1000, 60, 250), ("TRIPOD-AL", "unit", 600, 40, 150),
    ("GLASS-WARE", "unit", 3000, 200, 800), ("REAGENT-KIT", "unit", 1500, 100, 400),
    ("FABRIC-PLUSH", "meter", 1200, 80, 300), ("EYE-BTN", "unit", 3000, 200, 800),
    ("WOOD-PLY", "sheet", 500, 30, 120), ("DRUM-SKIN", "unit", 900, 60, 220),
    ("HARDWARE-ST", "kg", 800, 50, 200), ("SILVER-TUBE", "kg", 300, 20, 80),
    ("KEY-ASSY", "unit", 2000, 120, 500), ("BEARING-ST", "unit", 5000, 300, 1200),
]

WORK_CENTERS = [
    ("WC-WOOD", "Woodshop", 9600, 20, 1, 3),
    ("WC-SEW", "Sewing & Soft Goods", 7200, 16, 1, 2),
    ("WC-ASSY", "General Assembly", 10800, 26, 2, 4),
    ("WC-TECH", "Tech & Electronics", 6000, 12, 3, 5),
    ("WC-BIKE", "Bike Works", 4800, 8, 5, 5),
    ("WC-MUSIC", "Music Shop", 4200, 9, 3, 5),
]

GIFT_WC = {
    "WOOD-TRAIN": "WC-WOOD", "DOLL-CLOTH": "WC-SEW", "ROBO-KIT": "WC-TECH",
    "BIKE-16": "WC-BIKE", "BIKE-24": "WC-BIKE", "SKATE-BRD": "WC-WOOD",
    "PUZZLE-1K": "WC-WOOD", "BOARD-GM": "WC-WOOD", "KNIT-SCARF": "WC-SEW",
    "MITTENS": "WC-SEW", "TELESCOPE": "WC-TECH", "CHEM-SET": "WC-TECH",
    "TED-BEAR": "WC-SEW", "DRUM-SET": "WC-MUSIC", "FLUTE": "WC-MUSIC",
    "SCOOTER": "WC-ASSY",
}


def seed(db, fresh: bool = True) -> dict:
    rng = random.Random(1847)  # fixed seed: reproducible North Pole
    year = dt.date.today().year

    if fresh:
        db.conn.execute("PRAGMA foreign_keys=OFF")
        for t in ("users", "sessions", "regions", "cities", "gift_catalog",
                  "bom_lines", "work_centers", "production_orders",
                  "inventory_items", "inventory_moves", "children",
                  "wishlists", "delivery_assignments", "routes",
                  "audit_log", "kpi_snapshots"):
            db.execute(f"DROP TABLE IF EXISTS {t}")
        db.conn.execute("PRAGMA foreign_keys=ON")

    db.create_all(User, Region, City, GiftCatalog, BomLine, WorkCenter,
                  Child, WishList, InventoryItem)
    from .models import ProductionOrder, DeliveryAssignment, Route
    db.create_all(ProductionOrder, DeliveryAssignment, Route)
    from .models import InventoryMove, AuditLog, KpiSnapshot, Session
    db.create_all(InventoryMove, AuditLog, KpiSnapshot, Session)

    users = [
        ("sclaus", "Claus, S.", "admin", "santa@northpole.int"),
        ("mclaus", "Claus, M.", "planner", "mrs.claus@northpole.int"),
        ("tinsel", "Tinsel Sparklehammer", "planner", "tinsel@northpole.int"),
        ("birch", "Birch Fiddlestick", "elf", "birch@northpole.int"),
        ("juniper", "Juniper Sprocketwhistle", "elf", "juniper@northpole.int"),
        ("holly", "Holly Brightvane", "auditor", "holly@northpole.int"),
    ]
    for username, name, role, email in users:
        User(username=username, password_hash=hash_password("joy" if username != "sclaus" else "ho-ho-ho"),
             full_name=name, role=role, email=email, active=1,
             created_at=utcnow_iso()).insert()

    for i, (name, off, hours) in enumerate(REGIONS, 1):
        Region(id=i, name=name, timezone_offset=off,
               delivery_night_hours=hours).insert()

    region_cities: dict[int, list[City]] = {}
    for i, (name, country, ridx, lat, lon, pop, children) in enumerate(CITIES, 1):
        region_id = ridx + 1
        nice = rng.uniform(0.82, 0.97)
        city = City(id=i, name=name, country=country, region_id=region_id,
                    lat=lat, lon=lon, population=pop, children=children,
                    nice_ratio=nice,
                    local_utc_offset=off,
                    timezone_deadline=rng.uniform(5.0, 7.0))
        city.insert()
        region_cities.setdefault(region_id, []).append(city)

    for sku, name, cat, kg, dm3, cost, minutes, cx in GIFTS:
        GiftCatalog(sku=sku, name=name, category=cat, weight_kg=kg,
                    volume_dm3=dm3, unit_cost_materials=cost,
                    unit_labor_minutes=minutes, complexity=cx,
                    active=1).insert()
    for sku, lines in BOM.items():
        for comp, qty in lines:
            BomLine(gift_sku=sku, component_sku=comp, qty_per_unit=qty,
                    scrap_pct=2.0).insert()

    for code, name, cap, elves, cxmin, cxmax in WORK_CENTERS:
        WorkCenter(code=code, name=name, capacity_minutes_per_day=cap,
                   elf_count=elves, min_complexity=cxmin,
                   max_complexity=cxmax, active=1).insert()

    # Raw material inventory
    for sku, unit, onhand, rop, roq in RAW_MATERIALS:
        InventoryItem(sku=sku, location="WH-MAIN", on_hand=onhand,
                      allocated=0.0, reorder_point=rop, reorder_qty=roq,
                      unit=unit, updated_at=utcnow_iso()).insert()
    for g in GIFTS:
        InventoryItem(sku=g[0], location="WH-GIFTS", on_hand=0.0,
                      allocated=0.0, reorder_point=0, reorder_qty=0,
                      unit="unit", updated_at=utcnow_iso()).insert()
    InventoryItem(sku="COAL", location="WH-STABLES", on_hand=5000.0,
                  allocated=0.0, reorder_point=100, reorder_qty=1000,
                  unit="kg", updated_at=utcnow_iso()).insert()

    # Children + wishlists (deterministic sample population)
    skus = [g[0] for g in GIFTS]
    child_id = 0
    for city in City.all():
        n = 2 if city.children > 500_000 else (1 if city.children > 100_000 else 0)
        for _ in range(n):
            child_id += 1
            score = rng.uniform(15, 99)
            status = "naughty" if score < 35 else ("watchlist" if score < 50 else "nice")
            Child(id=child_id, name=f"{rng.choice(FIRST)} {rng.choice(LAST)}",
                  city_id=city.id, behavior_score=round(score, 1),
                  status=status, last_reviewed=utcnow_iso()).insert()
            for rank, sku in enumerate(rng.sample(skus, rng.randint(1, 3)), 1):
                WishList(child_id=child_id, gift_sku=sku, rank=rank,
                         received_year=None).insert()

    return {"users": len(users), "cities": len(CITIES),
            "children": child_id, "year": year}


FIRST = ["Aurora", "Nicholas", "Clara", "Emmett", "Luna", "Theodore", "Ivy",
         "Jasper", "Wren", "Felix", "Sofia", "Milo", "Freya", "Otto",
         "Noelle", "Remy", "Sylvie", "Kenji", "Amara", "Diego", "Priya",
         "Mateo", "Yuki", "Lena", "Tariq", "Elsa", "Marco", "Zara"]
LAST = ["Frostwhistle", "Peppermint", "Starbell", "Hollybrook", "Cranberry",
        "Jinglewood", "Snowfall", "Candycane", "Evergreen", "Tinseltree",
        "Mistletoe", "Gingersnap", "Frostpine", "Sleighbell", "Toyland",
        "Cocoaheart", "Winterberry", "Sugarplum", "Yulebright", "Nutmeg"]

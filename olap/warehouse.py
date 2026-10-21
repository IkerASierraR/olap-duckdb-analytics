"""Builds the OLAP warehouse: a star schema plus a pre-aggregated cube in DuckDB.

The data is synthetic but deterministic (hash-based), so every build of the
pipeline produces exactly the same warehouse.
"""
from __future__ import annotations

import argparse
import pathlib
import time

import duckdb

ROOT = pathlib.Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "warehouse" / "sales.duckdb"

DIM_PRODUCT = [
    # (product_id, product, subcategory, category, unit_price, unit_cost)
    (1, "Laptop Pro 14", "Laptops", "Tecnología", 1450.0, 1040.0),
    (2, "Laptop Air 13", "Laptops", "Tecnología", 980.0, 690.0),
    (3, "Smartphone X", "Smartphones", "Tecnología", 820.0, 560.0),
    (4, "Smartphone Lite", "Smartphones", "Tecnología", 310.0, 205.0),
    (5, "Tablet 11", "Tablets", "Tecnología", 540.0, 380.0),
    (6, "Audífonos BT", "Accesorios", "Tecnología", 95.0, 41.0),
    (7, "Smartwatch S", "Accesorios", "Tecnología", 230.0, 140.0),
    (8, "Monitor 27", "Periféricos", "Tecnología", 360.0, 250.0),
    (9, "Sofá 3 cuerpos", "Sala", "Hogar", 890.0, 520.0),
    (10, "Mesa de centro", "Sala", "Hogar", 210.0, 110.0),
    (11, "Colchón Queen", "Dormitorio", "Hogar", 640.0, 380.0),
    (12, "Velador", "Dormitorio", "Hogar", 120.0, 62.0),
    (13, "Licuadora", "Cocina", "Hogar", 85.0, 46.0),
    (14, "Freidora de aire", "Cocina", "Hogar", 140.0, 79.0),
    (15, "Juego de ollas", "Cocina", "Hogar", 175.0, 92.0),
    (16, "Zapatillas running", "Calzado", "Moda", 120.0, 58.0),
    (17, "Botines urbanos", "Calzado", "Moda", 150.0, 74.0),
    (18, "Casaca impermeable", "Ropa", "Moda", 110.0, 49.0),
    (19, "Jean clásico", "Ropa", "Moda", 60.0, 24.0),
    (20, "Polo algodón", "Ropa", "Moda", 25.0, 9.0),
    (21, "Mochila urbana", "Accesorios moda", "Moda", 70.0, 31.0),
    (22, "Bicicleta MTB", "Ciclismo", "Deportes", 760.0, 470.0),
    (23, "Mancuernas 10kg", "Fitness", "Deportes", 65.0, 33.0),
    (24, "Carpa 4 personas", "Outdoor", "Deportes", 230.0, 128.0),
]

DIM_STORE = [
    # (store_id, store, city, region, country)
    (1, "Lima Centro", "Lima", "Costa", "Perú"),
    (2, "Lima Miraflores", "Lima", "Costa", "Perú"),
    (3, "Arequipa Plaza", "Arequipa", "Sur", "Perú"),
    (4, "Tacna Mall", "Tacna", "Sur", "Perú"),
    (5, "Trujillo Norte", "Trujillo", "Norte", "Perú"),
    (6, "Santiago Centro", "Santiago", "Metropolitana", "Chile"),
    (7, "Valparaíso Puerto", "Valparaíso", "Valparaíso", "Chile"),
    (8, "Bogotá Andino", "Bogotá", "Cundinamarca", "Colombia"),
    (9, "Medellín Poblado", "Medellín", "Antioquia", "Colombia"),
    (10, "CDMX Reforma", "Ciudad de México", "Centro", "México"),
    (11, "Guadalajara Sur", "Guadalajara", "Jalisco", "México"),
    (12, "Monterrey Valle", "Monterrey", "Nuevo León", "México"),
]

DIM_CHANNEL = [(1, "Tienda física"), (2, "Online"), (3, "Marketplace")]


def build(db_path: pathlib.Path = DB_PATH, n_sales: int = 1_000_000) -> dict:
    """(Re)creates the warehouse and returns a few build stats."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()

    t0 = time.perf_counter()
    con = duckdb.connect(str(db_path))

    # ---------- Dimensions ----------
    con.execute("""
        CREATE TABLE dim_date AS
        SELECT
            CAST(strftime(d, '%Y%m%d') AS INTEGER) AS date_key,
            CAST(d AS DATE)                        AS full_date,
            year(d)                                AS year,
            quarter(d)                             AS quarter,
            'T' || quarter(d)                      AS quarter_label,
            month(d)                               AS month,
            strftime(d, '%Y-%m')                   AS year_month,
            dayofweek(d)                           AS day_of_week
        FROM generate_series(DATE '2023-01-01', DATE '2025-12-31', INTERVAL 1 DAY) t(d)
    """)
    con.execute("""CREATE TABLE dim_product (product_id INTEGER PRIMARY KEY, product VARCHAR,
                   subcategory VARCHAR, category VARCHAR, unit_price DOUBLE, unit_cost DOUBLE)""")
    con.executemany("INSERT INTO dim_product VALUES (?, ?, ?, ?, ?, ?)", DIM_PRODUCT)
    con.execute("""CREATE TABLE dim_store (store_id INTEGER PRIMARY KEY, store VARCHAR,
                   city VARCHAR, region VARCHAR, country VARCHAR)""")
    con.executemany("INSERT INTO dim_store VALUES (?, ?, ?, ?, ?)", DIM_STORE)
    con.execute("CREATE TABLE dim_channel (channel_id INTEGER PRIMARY KEY, channel VARCHAR)")
    con.executemany("INSERT INTO dim_channel VALUES (?, ?)", DIM_CHANNEL)

    # ---------- Fact table (deterministic pseudo-random generation) ----------
    n_days = con.execute("SELECT count(*) FROM dim_date").fetchone()[0]
    con.execute(f"""
        CREATE TABLE fact_sales AS
        WITH base AS (
            SELECT
                i AS sale_id,
                (hash(i)      % 1000000) / 1000000.0 AS u_date,
                (hash(i * 7)  % 1000000) / 1000000.0 AS u_prod,
                (hash(i * 13) % 1000000) / 1000000.0 AS u_store,
                (hash(i * 31) % 1000000) / 1000000.0 AS u_chan,
                (hash(i * 53) % 1000000) / 1000000.0 AS u_qty,
                (hash(i * 97) % 1000000) / 1000000.0 AS u_disc
            FROM range(1, {n_sales + 1}) t(i)
        ), keyed AS (
            SELECT
                sale_id,
                -- sqrt() skews dates towards the end => visible year-over-year growth
                CAST(floor({n_days} * sqrt(u_date)) AS INTEGER)            AS day_offset,
                CAST(floor(u_prod * {len(DIM_PRODUCT)}) AS INTEGER) + 1    AS product_id,
                CAST(floor(u_store * {len(DIM_STORE)}) AS INTEGER) + 1     AS store_id,
                CASE WHEN u_chan < 0.50 THEN 1 WHEN u_chan < 0.85 THEN 2 ELSE 3 END AS channel_id,
                1 + CAST(floor(u_qty * u_qty * 5) AS INTEGER)              AS quantity,
                CASE WHEN u_disc < 0.70 THEN 0.0 WHEN u_disc < 0.90 THEN 0.10 ELSE 0.25 END AS discount
            FROM base
        )
        SELECT
            k.sale_id,
            CAST(strftime(DATE '2023-01-01' + k.day_offset, '%Y%m%d') AS INTEGER) AS date_key,
            k.product_id, k.store_id, k.channel_id, k.quantity, k.discount,
            round(k.quantity * p.unit_price * (1 - k.discount), 2) AS revenue,
            round(k.quantity * p.unit_cost, 2)                     AS cost,
            round(k.quantity * p.unit_price * (1 - k.discount) - k.quantity * p.unit_cost, 2) AS profit
        FROM keyed k
        JOIN dim_product p USING (product_id)
    """)

    # ---------- Denormalized view used by the dashboard ----------
    con.execute("""
        CREATE VIEW v_sales AS
        SELECT f.*, d.full_date, d.year, d.quarter, d.quarter_label, d.month, d.year_month,
               p.product, p.subcategory, p.category,
               s.store, s.city, s.region, s.country,
               c.channel
        FROM fact_sales f
        JOIN dim_date d    USING (date_key)
        JOIN dim_product p USING (product_id)
        JOIN dim_store s   USING (store_id)
        JOIN dim_channel c USING (channel_id)
    """)

    # ---------- Pre-aggregated OLAP cube ----------
    # ROLLUP on the time hierarchy x CUBE on the other dimensions.
    con.execute("""
        CREATE TABLE cube_sales AS
        SELECT
            year, quarter, category, country, channel,
            GROUPING(year, quarter, category, country, channel) AS grouping_id,
            sum(revenue)  AS revenue,
            sum(profit)   AS profit,
            sum(quantity) AS units,
            count(*)      AS orders
        FROM v_sales
        GROUP BY ROLLUP (year, quarter), CUBE (category, country, channel)
    """)

    stats = {
        "fact_rows": con.execute("SELECT count(*) FROM fact_sales").fetchone()[0],
        "cube_rows": con.execute("SELECT count(*) FROM cube_sales").fetchone()[0],
        "seconds": round(time.perf_counter() - t0, 2),
    }
    con.close()
    return stats


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build the DuckDB OLAP warehouse")
    parser.add_argument("--rows", type=int, default=1_000_000, help="number of fact rows")
    parser.add_argument("--db", type=pathlib.Path, default=DB_PATH)
    args = parser.parse_args()
    print(build(args.db, args.rows))

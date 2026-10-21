"""OLAP operations (slice, dice, roll-up, drill-down, pivot) over the DuckDB warehouse.

Dimension and measure names are validated against whitelists, so user input
from the dashboard is never interpolated into SQL as-is.
"""
from __future__ import annotations

import time

import duckdb
import pandas as pd

# Hierarchies: each list goes from the coarsest to the finest level.
HIERARCHIES: dict[str, list[str]] = {
    "Tiempo": ["year", "quarter_label", "year_month", "full_date"],
    "Producto": ["category", "subcategory", "product"],
    "Geografía": ["country", "region", "city", "store"],
    "Canal": ["channel"],
}

LABELS = {
    "year": "Año", "quarter_label": "Trimestre", "year_month": "Mes", "full_date": "Día",
    "category": "Categoría", "subcategory": "Subcategoría", "product": "Producto",
    "country": "País", "region": "Región", "city": "Ciudad", "store": "Tienda",
    "channel": "Canal",
}

MEASURES = {
    "revenue": "sum(revenue)",
    "profit": "sum(profit)",
    "units": "sum(quantity)",
    "orders": "count(*)",
    "margin_pct": "round(100 * sum(profit) / nullif(sum(revenue), 0), 2)",
}

MEASURE_LABELS = {
    "revenue": "Ingresos", "profit": "Utilidad", "units": "Unidades",
    "orders": "Órdenes", "margin_pct": "Margen %",
}

DIMENSIONS = {level for levels in HIERARCHIES.values() for level in levels}
FILTERABLE = {"year", "country", "category", "channel"}


def _check(names, allowed, kind):
    for n in names:
        if n not in allowed:
            raise ValueError(f"{kind} no permitido: {n!r}")


def _where(filters: dict[str, list] | None) -> tuple[str, list]:
    """Slice/dice: builds a parameterized WHERE clause from {dimension: [values]}."""
    clauses, params = [], []
    for dim, values in (filters or {}).items():
        if not values:
            continue
        _check([dim], FILTERABLE, "Filtro")
        clauses.append(f"{dim} IN ({', '.join('?' for _ in values)})")
        params.extend(values)
    return ("WHERE " + " AND ".join(clauses)) if clauses else "", params


def timed(con: duckdb.DuckDBPyConnection, sql: str, params=None) -> tuple[pd.DataFrame, float]:
    t0 = time.perf_counter()
    df = con.execute(sql, params or []).df()
    return df, (time.perf_counter() - t0) * 1000


def aggregate(con, dims: list[str], measures: list[str], filters=None, order_by_measure=False):
    """Generic GROUP BY: the building block of roll-up / drill-down."""
    _check(dims, DIMENSIONS, "Dimensión")
    _check(measures, MEASURES, "Medida")
    where, params = _where(filters)
    select = ", ".join(dims + [f"{MEASURES[m]} AS {m}" for m in measures])
    group = f"GROUP BY {', '.join(dims)}" if dims else ""
    order = f"ORDER BY {measures[0]} DESC" if order_by_measure else (
        f"ORDER BY {', '.join(dims)}" if dims else "")
    sql = f"SELECT {select} FROM v_sales {where} {group} {order}"
    return timed(con, sql, params)


def drill(con, hierarchy: str, level: int, measure: str, filters=None):
    """Drill-down (level+1) / roll-up (level-1) along a hierarchy."""
    levels = HIERARCHIES[hierarchy]
    level = max(0, min(level, len(levels) - 1))
    return aggregate(con, levels[: level + 1], [measure], filters)


def pivot(con, row_dim: str, col_dim: str, measure: str, filters=None) -> tuple[pd.DataFrame, float]:
    """Pivot (rotation): rows x columns with grand totals."""
    df, ms = aggregate(con, [row_dim, col_dim], [measure], filters)
    table = df.pivot_table(index=row_dim, columns=col_dim, values=measure,
                           aggfunc="sum", margins=True, margins_name="Total")
    return table, ms


def kpis(con, filters=None) -> dict:
    df, _ = aggregate(con, [], ["revenue", "profit", "units", "orders", "margin_pct"], filters)
    return df.iloc[0].to_dict()


def from_cube(con, dims: list[str], measure: str) -> tuple[pd.DataFrame, float]:
    """Answers from the pre-aggregated cube instead of the 1M-row fact table."""
    cube_dims = ["year", "quarter", "category", "country", "channel"]
    _check(dims, cube_dims, "Dimensión del cubo")
    _check([measure], {"revenue", "profit", "units", "orders"}, "Medida del cubo")
    conds = [f"{d} IS {'NOT ' if d in dims else ''}NULL" for d in cube_dims]
    cols = ", ".join(dims + [measure])
    order = f"ORDER BY {', '.join(dims)}" if dims else ""
    sql = f"SELECT {cols} FROM cube_sales WHERE {' AND '.join(conds)} {order}"
    return timed(con, sql)

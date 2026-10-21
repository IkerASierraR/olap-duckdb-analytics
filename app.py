"""OLAP dashboard: slice, dice, roll-up, drill-down and pivot on DuckDB."""
from __future__ import annotations

import duckdb
import plotly.express as px
import streamlit as st

from olap import queries as q
from olap.warehouse import DB_PATH, build

st.set_page_config(page_title="OLAP con DuckDB", page_icon="🦆", layout="wide")


@st.cache_resource
def connection() -> duckdb.DuckDBPyConnection:
    if not DB_PATH.exists():
        build()
    # Read-only and no access to files/network: the SQL console cannot escape the warehouse.
    return duckdb.connect(str(DB_PATH), read_only=True,
                          config={"enable_external_access": False})


con = connection()
L = q.LABELS
M = q.MEASURE_LABELS


def money(v: float) -> str:
    return f"${v / 1e6:,.1f}M" if abs(v) >= 1e6 else f"${v:,.0f}"


# ---------------- Sidebar: slice & dice ----------------
st.sidebar.title("🦆 OLAP con DuckDB")
st.sidebar.caption("Slice & dice: filtra el cubo por cualquier dimensión.")


@st.cache_data
def members(dim: str) -> list:
    return [r[0] for r in con.execute(f"SELECT DISTINCT {dim} FROM v_sales ORDER BY 1").fetchall()]


filters = {
    dim: st.sidebar.multiselect(L[dim], members(dim))
    for dim in ["year", "country", "category", "channel"]
}
measure = st.sidebar.selectbox("Medida", list(q.MEASURES), format_func=M.get)

st.title("Análisis de ventas multidimensional (OLAP)")
st.caption("1.000.000 de ventas · esquema estrella · DuckDB columnar · cubo pre-agregado con ROLLUP + CUBE")

# ---------------- KPIs ----------------
k = q.kpis(con, filters)
c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Ingresos", money(k["revenue"] or 0))
c2.metric("Utilidad", money(k["profit"] or 0))
c3.metric("Margen", f"{k['margin_pct'] or 0:.1f} %")
c4.metric("Unidades", f"{(k['units'] or 0) / 1e6:.2f} M")
c5.metric("Órdenes", f"{(k['orders'] or 0) / 1e6:.2f} M")

tab_drill, tab_pivot, tab_cube, tab_sql, tab_model = st.tabs(
    ["🔍 Drill-down / Roll-up", "🔄 Pivot", "🧊 Cubo pre-agregado", "💻 Consola SQL", "⭐ Modelo"])

# ---------------- Drill-down / Roll-up ----------------
with tab_drill:
    left, right = st.columns([1, 3])
    with left:
        hierarchy = st.radio("Jerarquía", list(q.HIERARCHIES))
        levels = q.HIERARCHIES[hierarchy]
        level = st.select_slider(
            "Nivel (← roll-up · drill-down →)",
            options=list(range(len(levels))),
            format_func=lambda i: L[levels[i]],
        ) if len(levels) > 1 else 0
    df, ms = q.drill(con, hierarchy, level, measure, filters)
    with right:
        dims = levels[: level + 1]
        if hierarchy == "Tiempo":
            df[dims[-1]] = df[dims[-1]].astype(str)  # categorical axis: no "2023.5"
            fig = px.line(df, x=dims[-1], y=measure, markers=level < 3,
                          labels={**L, **M})
        else:
            df["ruta"] = df[dims].astype(str).agg(" › ".join, axis=1)
            fig = px.bar(df.sort_values(measure, ascending=False).head(30),
                         x="ruta", y=measure, color=dims[0], labels={**L, **M, "ruta": ""})
        st.plotly_chart(fig, use_container_width=True)
        st.caption(f"⏱️ {len(df):,} filas en {ms:.1f} ms sobre 1M de hechos")
    st.dataframe(df.drop(columns="ruta", errors="ignore").rename(columns={**L, **M}),
                 use_container_width=True, hide_index=True)

# ---------------- Pivot ----------------
with tab_pivot:
    dim_options = ["year", "quarter_label", "category", "subcategory", "country", "region", "channel"]
    a, b = st.columns(2)
    row_dim = a.selectbox("Filas", dim_options, index=2, format_func=L.get)
    col_dim = b.selectbox("Columnas", [d for d in dim_options if d != row_dim],
                          index=3, format_func=L.get)
    table, ms = q.pivot(con, row_dim, col_dim, measure, filters)
    st.dataframe(table.style.format("{:,.0f}").background_gradient(cmap="Blues", axis=None),
                 use_container_width=True)
    heat = table.drop(index="Total", columns="Total")
    st.plotly_chart(px.imshow(heat, text_auto=".3s", aspect="auto", color_continuous_scale="Blues",
                              labels={"x": L[col_dim], "y": L[row_dim], "color": M[measure]}),
                    use_container_width=True)
    st.caption(f"⏱️ Pivot calculado en {ms:.1f} ms")

# ---------------- Pre-aggregated cube ----------------
with tab_cube:
    st.markdown(
        "La tabla `cube_sales` se materializa durante el despliegue con "
        "`GROUP BY ROLLUP(year, quarter), CUBE(category, country, channel)`: "
        "**todas las combinaciones de subtotales** en una sola consulta. "
        "Compara el tiempo contra la tabla de hechos.")
    cube_dims = st.multiselect("Dimensiones", ["year", "quarter", "category", "country", "channel"],
                               default=["year", "country"], format_func=lambda d: L.get(d, "Trimestre"))
    cube_measure = measure if measure in ("revenue", "profit", "units", "orders") else "revenue"
    if "quarter" in cube_dims and "year" not in cube_dims:
        st.warning("En el cubo el trimestre cuelga de la jerarquía de tiempo: agrega también *Año*.")
    else:
        cube_df, cube_ms = q.from_cube(con, cube_dims, cube_measure)
        fact_dims = [d if d != "quarter" else "quarter_label" for d in cube_dims]
        _, fact_ms = q.aggregate(con, fact_dims, [cube_measure])
        x, y = st.columns(2)
        x.metric("Desde el cubo (1.600 filas)", f"{cube_ms:.2f} ms")
        y.metric("Desde los hechos (1M filas)", f"{fact_ms:.2f} ms",
                 delta=f"{fact_ms / max(cube_ms, 1e-6):.1f}x más lento", delta_color="inverse")
        st.dataframe(cube_df.rename(columns={**L, **M, "quarter": "Trimestre"}),
                     use_container_width=True, hide_index=True)

# ---------------- SQL console ----------------
with tab_sql:
    st.caption("Conexión de solo lectura. Tablas: `fact_sales`, `dim_date`, `dim_product`, "
               "`dim_store`, `dim_channel`, `cube_sales`, vista `v_sales`.")
    sql = st.text_area("SQL", height=160, value=(
        "SELECT country, channel, round(sum(revenue)) AS ingresos,\n"
        "       rank() OVER (PARTITION BY country ORDER BY sum(revenue) DESC) AS ranking\n"
        "FROM v_sales\nWHERE year = 2025\nGROUP BY ALL\nORDER BY country, ranking"))
    if st.button("Ejecutar", type="primary"):
        try:
            out, ms = q.timed(con, sql)
            st.dataframe(out.head(1000), use_container_width=True, hide_index=True)
            st.caption(f"⏱️ {len(out):,} filas en {ms:.1f} ms")
        except Exception as e:  # noqa: BLE001 - show any SQL error to the user
            st.error(str(e))

# ---------------- Star schema ----------------
with tab_model:
    st.graphviz_chart("""
    digraph {
      rankdir=LR; node [shape=record, style=filled, fillcolor="#eef4ff", fontname=Helvetica];
      fact [label="{fact_sales|sale_id\\ldate_key\\lproduct_id\\lstore_id\\lchannel_id\\l|quantity\\ldiscount\\lrevenue\\lcost\\lprofit\\l}", fillcolor="#ffe9b3"];
      date [label="{dim_date|year › quarter › month › day}"];
      product [label="{dim_product|category › subcategory › product}"];
      store [label="{dim_store|country › region › city › store}"];
      channel [label="{dim_channel|channel}"];
      date -> fact; product -> fact; store -> fact; channel -> fact;
    }""")
    counts = con.execute("""
        SELECT 'fact_sales' tabla, count(*) filas FROM fact_sales UNION ALL
        SELECT 'dim_date', count(*) FROM dim_date UNION ALL
        SELECT 'dim_product', count(*) FROM dim_product UNION ALL
        SELECT 'dim_store', count(*) FROM dim_store UNION ALL
        SELECT 'dim_channel', count(*) FROM dim_channel UNION ALL
        SELECT 'cube_sales', count(*) FROM cube_sales""").df()
    st.dataframe(counts, hide_index=True)

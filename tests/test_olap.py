import duckdb
import pytest

from olap import queries as q
from olap.warehouse import build


@pytest.fixture(scope="session")
def con(tmp_path_factory):
    path = tmp_path_factory.mktemp("wh") / "test.duckdb"
    build(path, n_sales=50_000)
    c = duckdb.connect(str(path), read_only=True)
    yield c
    c.close()


def test_star_schema_integrity(con):
    orphans = con.execute("""
        SELECT count(*) FROM fact_sales f
        LEFT JOIN dim_date d USING (date_key)
        LEFT JOIN dim_product p USING (product_id)
        LEFT JOIN dim_store s USING (store_id)
        WHERE d.date_key IS NULL OR p.product_id IS NULL OR s.store_id IS NULL""").fetchone()[0]
    assert orphans == 0
    assert con.execute("SELECT count(*) FROM fact_sales").fetchone()[0] == 50_000


def test_rollup_is_consistent_with_drilldown(con):
    total = q.kpis(con)["revenue"]
    by_year, _ = q.drill(con, "Tiempo", 0, "revenue")
    by_month, _ = q.drill(con, "Tiempo", 2, "revenue")
    assert by_year["revenue"].sum() == pytest.approx(total)
    assert by_month["revenue"].sum() == pytest.approx(total)


def test_cube_matches_fact_table(con):
    cube, _ = q.from_cube(con, ["country"], "revenue")
    facts, _ = q.aggregate(con, ["country"], ["revenue"])
    assert cube.set_index("country")["revenue"].to_dict() == pytest.approx(
        facts.set_index("country")["revenue"].to_dict())
    grand, _ = q.from_cube(con, [], "revenue")
    assert grand["revenue"].iloc[0] == pytest.approx(q.kpis(con)["revenue"])


def test_slice_and_dice(con):
    sliced = q.kpis(con, {"country": ["Perú"]})["revenue"]
    diced = q.kpis(con, {"country": ["Perú"], "channel": ["Online"]})["revenue"]
    assert 0 < diced < sliced < q.kpis(con)["revenue"]


def test_pivot_has_totals(con):
    table, _ = q.pivot(con, "category", "country", "revenue")
    assert table.loc["Total", "Total"] == pytest.approx(q.kpis(con)["revenue"])


def test_rejects_sql_injection(con):
    with pytest.raises(ValueError):
        q.aggregate(con, ["country; DROP TABLE fact_sales"], ["revenue"])
    with pytest.raises(ValueError):
        q.kpis(con, {"1=1 OR country": ["x"]})

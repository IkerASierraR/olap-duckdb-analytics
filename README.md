# 🦆 OLAP con DuckDB

[![CI/CD](https://github.com/IkerASierraR/olap-duckdb-analytics/actions/workflows/ci-cd.yml/badge.svg)](https://github.com/IkerASierraR/olap-duckdb-analytics/actions/workflows/ci-cd.yml)

Solución **OLAP (Online Analytical Processing)** construida con **DuckDB** y **Streamlit**: un data warehouse en esquema estrella con 1.000.000 de ventas, un cubo pre-agregado con `ROLLUP` + `CUBE` y un dashboard interactivo para hacer **slice, dice, roll-up, drill-down y pivot**.

Se despliega de forma automática con **GitHub Actions** en **Hugging Face Spaces** (SaaS público, sin AWS).

🔗 **Demo:** https://huggingface.co/spaces/<HF_USUARIO>/olap-duckdb-analytics

## Arquitectura

```
 git push ─► GitHub Actions ─┬─ test:   pytest · build warehouse · docker build · smoke test
                             └─ deploy: huggingface_hub ─► Hugging Face Space (Docker)
                                                              │
                                     docker build: python -m olap.warehouse
                                                              │
                                     Streamlit ◄── DuckDB (sales.duckdb, solo lectura)
```

### Modelo dimensional (esquema estrella)

| Tabla | Tipo | Jerarquía / contenido |
|---|---|---|
| `fact_sales` | Hechos (1M filas) | quantity, discount, revenue, cost, profit |
| `dim_date` | Dimensión | año › trimestre › mes › día |
| `dim_product` | Dimensión | categoría › subcategoría › producto |
| `dim_store` | Dimensión | país › región › ciudad › tienda |
| `dim_channel` | Dimensión | tienda física / online / marketplace |
| `cube_sales` | Cubo materializado | `GROUP BY ROLLUP(year, quarter), CUBE(category, country, channel)` |

## Operaciones OLAP

| Operación | Dónde |
|---|---|
| **Slice / Dice** | Filtros de la barra lateral (año, país, categoría, canal) |
| **Roll-up / Drill-down** | Pestaña *Drill-down*: moverse por los niveles de cada jerarquía |
| **Pivot** | Pestaña *Pivot*: filas × columnas con totales y mapa de calor |
| **Cubo pre-agregado** | Pestaña *Cubo*: compara el tiempo contra la tabla de hechos |
| **SQL ad-hoc** | Pestaña *Consola SQL* (conexión de solo lectura y sin acceso a archivos) |

## Ejecutar en local

```bash
pip install -r requirements-dev.txt
python -m olap.warehouse        # crea warehouse/sales.duckdb
streamlit run app.py
pytest -v
```

O con Docker:

```bash
docker build -t olap-duckdb .
docker run -p 7860:7860 olap-duckdb
```

## Despliegue automatizado

1. Crea un token de escritura en https://huggingface.co/settings/tokens
2. En GitHub: **Settings › Secrets and variables › Actions**
   - Secret `HF_TOKEN` = tu token
   - Variable `HF_SPACE_ID` = `<HF_USUARIO>/olap-duckdb-analytics`
3. Haz `git push` a `main`. El pipeline prueba, construye y publica el Space (lo crea si no existe).

## Estructura

```
olap/warehouse.py      # ETL: esquema estrella + cubo en DuckDB
olap/queries.py        # slice, dice, roll-up, drill-down, pivot, cubo
app.py                 # dashboard Streamlit
tests/test_olap.py     # pruebas de consistencia OLAP
Dockerfile             # imagen para Hugging Face Spaces
deploy/deploy_space.py # publicación con huggingface_hub
.github/workflows/     # pipeline CI/CD
```

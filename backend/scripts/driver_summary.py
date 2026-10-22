"""Print a one-line summary of which optional connector drivers and enterprise
engines are importable. Run at Docker build time so a missing driver shows up
in the build log instead of as a failed connection test in the UI."""
import importlib

MODULES = {
    "snowflake": "snowflake.sqlalchemy", "bigquery": "sqlalchemy_bigquery",
    "clickhouse": "clickhouse_sqlalchemy", "redshift": "sqlalchemy_redshift",
    "mssql": "pyodbc", "oracle": "oracledb", "mysql": "pymysql", "druid": "pydruid",
    "adls": "adlfs", "trino": "trino.sqlalchemy", "databricks": "databricks.sql",
    "deltalake": "deltalake", "iceberg": "pyiceberg", "sqlglot": "sqlglot", "ibis": "ibis",
}


def importable(module: str) -> bool:
    try:
        importlib.import_module(module)
        return True
    except Exception:
        return False


ok = [name for name, mod in MODULES.items() if importable(mod)]
missing = [name for name in MODULES if name not in ok]
print(f"SFS drivers: {len(ok)}/{len(MODULES)} ok: {' '.join(ok) or '-'}"
      f" | missing: {' '.join(missing) or '-'}")

import json, uuid, base64
from cryptography.fernet import Fernet
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.config import settings
from app.models.connection import Connection


def _fernet() -> Fernet:
    key = settings.SECRET_KEY.encode()[:32].ljust(32, b"0")
    return Fernet(base64.urlsafe_b64encode(key))


def encrypt(s: str) -> str:
    return _fernet().encrypt(s.encode()).decode()


def decrypt(s: str) -> str:
    return _fernet().decrypt(s.encode()).decode()


def build_url(conn: Connection) -> str:
    """
    Build a SQLAlchemy URL per dialect. Field conventions:
      snowflake : host=account identifier, database="DB/SCHEMA",
                  extra_params: warehouse, role
      bigquery  : host=GCP project, database=dataset,
                  extra_params: credentials_path (service-account JSON)
      clickhouse: host, port (8123 http / 8443 https), database,
                  extra_params: protocol=https for secure endpoints
      redshift  : host=cluster endpoint, port=5439, database
      mssql     : extra_params: driver (default "ODBC Driver 18 for SQL Server")
      oracle    : database field = service name (thin oracledb, no client install)
      starrocks : MySQL protocol — host=FE host, port=9030, database=db
      doris     : MySQL protocol — host=FE host, port=9030, database=db
      trino     : host=coordinator, database="catalog/schema", extras: http_scheme=https
      databricks: host=workspace host, password=access token,
                  extras: http_path (required), catalog, schema
      adls      : NOT a SQL engine — use get_storage(name) in processors instead
      delta/iceberg : table FORMATS, not DBs — read via a query engine (Trino/
                  StarRocks/Databricks/Snowflake) OR directly with
                  read_delta()/read_iceberg() helpers injected in processors
    Any remaining extra_params keys are appended as query-string options.
    """
    from urllib.parse import urlencode, quote_plus

    extras: dict = json.loads(conn.extra_params) if conn.extra_params else {}
    extras = {k: v for k, v in extras.items() if v not in (None, "")}
    password = decrypt(conn.password_enc) if conn.password_enc else ""

    def userinfo() -> str:
        if not conn.username:
            return ""
        return f"{quote_plus(conn.username)}{':' + quote_plus(password) if password else ''}@"

    def hostinfo(default_port: int | None = None) -> str:
        port = conn.port or default_port
        return f"{conn.host}:{port}" if port else (conn.host or "")

    def q(params: dict) -> str:
        return f"?{urlencode(params)}" if params else ""

    d = conn.dialect

    if d == "adls":
        # Storage connection — engines don't apply. get_engine() raises a
        # helpful error; processors use get_storage(name) for abfs:// paths.
        return f"adls://{conn.host}/{conn.database or ''}"

    if d == "snowflake":
        # snowflake://user:pass@account/DB/SCHEMA?warehouse=WH&role=R
        db = (conn.database or "").strip("/")
        params = {k: extras.pop(k) for k in ("warehouse", "role") if k in extras}
        params.update(extras)
        return f"snowflake://{userinfo()}{conn.host}/{db}{q(params)}"

    if d == "bigquery":
        # bigquery://project/dataset?credentials_path=/path/key.json
        params = {}
        if extras.get("credentials_path"):
            params["credentials_path"] = extras.pop("credentials_path")
        params.update(extras)
        ds = f"/{conn.database}" if conn.database else ""
        return f"bigquery://{conn.host}{ds}{q(params)}"

    if d == "clickhouse":
        proto = extras.pop("protocol", None)
        default_port = 8443 if proto == "https" else 8123
        params = ({"protocol": "https"} if proto == "https" else {})
        params.update(extras)
        db = f"/{conn.database}" if conn.database else "/default"
        return f"clickhouse+http://{userinfo()}{hostinfo(default_port)}{db}{q(params)}"

    if d == "redshift":
        db = f"/{conn.database}" if conn.database else ""
        return f"redshift+psycopg2://{userinfo()}{hostinfo(5439)}{db}{q(extras)}"

    if d == "mssql":
        driver = extras.pop("driver", "ODBC Driver 18 for SQL Server")
        params = {"driver": driver, "TrustServerCertificate": extras.pop("TrustServerCertificate", "yes")}
        params.update(extras)
        db = f"/{conn.database}" if conn.database else ""
        return f"mssql+pyodbc://{userinfo()}{hostinfo(1433)}{db}{q(params)}"

    if d == "oracle":
        # thin-mode python-oracledb: service name via query param
        params = {"service_name": conn.database or ""}
        params.update(extras)
        return f"oracle+oracledb://{userinfo()}{hostinfo(1521)}/{q(params)}"

    if d in ("starrocks", "doris"):
        # Both speak the MySQL wire protocol — no new driver needed.
        # host=FE host, port=query port (StarRocks 9030, Doris 9030), database=db
        default_port = 9030
        db = f"/{conn.database}" if conn.database else ""
        return f"mysql+pymysql://{userinfo()}{hostinfo(default_port)}{db}{q(extras)}"

    if d == "trino":
        # trino://user@host:port/catalog/schema
        # http_scheme / verify / password(→BasicAuthentication) are passed as
        # connect_args (see get_connect_args), NOT as URL query params — that's
        # what the trino sqlalchemy dialect expects.
        db = f"/{conn.database}" if conn.database else ""
        # Drop connect_arg-bound keys from the query string
        for k in ("http_scheme", "verify", "auth"):
            extras.pop(k, None)
        return f"trino://{userinfo()}{hostinfo(8080)}{db}{q(extras)}"

    if d == "databricks":
        # databricks://token:<token>@<host>?http_path=/sql/1.0/warehouses/xxx&catalog=..&schema=..
        # host=workspace host, password=access token, extras: http_path (required), catalog, schema
        token = password or ""
        params = {}
        for k in ("http_path", "catalog", "schema"):
            if extras.get(k):
                params[k] = extras.pop(k)
        params.update(extras)
        return f"databricks://token:{token}@{conn.host}{q(params)}"

    # Generic fallback (postgresql, mysql, sqlite, druid, …)
    dialect_map = {
        "postgresql": "postgresql+psycopg",
        "mysql": "mysql+pymysql",
        "sqlite": "sqlite",
        "druid": "druid",
    }
    driver = dialect_map.get(d, d)
    db = f"/{conn.database}" if conn.database else ""
    return f"{driver}://{userinfo()}{hostinfo()}{db}{q(extras)}"


def get_storage_options(conn: Connection) -> dict:
    """ADLS storage options for pandas/duckdb/fsspec abfs:// access.
    host=storage account name, password=account key (encrypted at rest),
    database=default container. extra_params may hold sas_token or
    tenant_id/client_id/client_secret for service-principal auth."""
    extras: dict = json.loads(conn.extra_params) if conn.extra_params else {}
    opts: dict = {"account_name": conn.host}
    if conn.password_enc:
        opts["account_key"] = decrypt(conn.password_enc)
    for k in ("sas_token", "tenant_id", "client_id", "client_secret"):
        if extras.get(k):
            opts[k] = extras[k]
    return opts


def get_connect_args(conn: Connection) -> dict:
    """Per-dialect connect_args that don't belong in the URL. Currently Trino:
    http_scheme (http/https), verify (TLS cert check), and BasicAuthentication
    when a username+password are set — mirroring a hand-written create_engine."""
    extras: dict = json.loads(conn.extra_params) if conn.extra_params else {}
    d = conn.dialect

    if d == "trino":
        args: dict = {}
        scheme = extras.get("http_scheme")
        if scheme:
            args["http_scheme"] = scheme
        if "verify" in extras:
            v = str(extras["verify"]).strip().lower()
            args["verify"] = v not in ("false", "0", "no", "off")
        # Password auth → BasicAuthentication(user, password)
        if conn.username and conn.password_enc:
            try:
                from trino.auth import BasicAuthentication
                args["auth"] = BasicAuthentication(conn.username, decrypt(conn.password_enc))
                # BasicAuth requires https; default the scheme if unset
                args.setdefault("http_scheme", "https")
            except Exception:
                pass
        return args

    return {}


async def list_connections(db: AsyncSession):
    r = await db.execute(select(Connection).order_by(Connection.name))
    return r.scalars().all()


async def get_connection(db: AsyncSession, conn_id: str):
    return await db.get(Connection, conn_id)


async def create_connection(db: AsyncSession, data: dict) -> Connection:
    conn = Connection(
        id=str(uuid.uuid4()),
        name=data["name"],
        dialect=data["dialect"],
        host=data.get("host"),
        port=data.get("port"),
        database=data.get("database"),
        username=data.get("username"),
        password_enc=encrypt(data["password"]) if data.get("password") else None,
        extra_params=json.dumps(data["extra_params"]) if data.get("extra_params") else None,
    )
    db.add(conn)
    await db.commit()
    await db.refresh(conn)
    return conn


async def delete_connection(db: AsyncSession, conn_id: str) -> bool:
    r = await db.execute(delete(Connection).where(Connection.id == conn_id))
    await db.commit()
    return r.rowcount > 0


async def update_connection(db: AsyncSession, conn_id: str, data: dict) -> Connection | None:
    conn = await db.get(Connection, conn_id)
    if not conn:
        return None
    if "name" in data:     conn.name = data["name"]
    if "dialect" in data:  conn.dialect = data["dialect"]
    if "host" in data:     conn.host = data.get("host")
    if "port" in data:     conn.port = data.get("port")
    if "database" in data: conn.database = data.get("database")
    if "username" in data: conn.username = data.get("username")
    # Only replace the password if a new non-empty one was supplied
    if data.get("password"):
        conn.password_enc = encrypt(data["password"])
    if "extra_params" in data:
        conn.extra_params = json.dumps(data["extra_params"]) if data.get("extra_params") else None
    await db.commit()
    await db.refresh(conn)
    return conn


async def test_connection(conn: Connection) -> dict:
    if conn.dialect == "adls":
        try:
            import adlfs
            fs = adlfs.AzureBlobFileSystem(**get_storage_options(conn))
            fs.ls(conn.database or "")
            return {"ok": True, "error": None}
        except ImportError:
            return {"ok": False, "error": "adlfs not installed — pip install adlfs"}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    import sqlalchemy as sa
    url = build_url(conn)
    ca = get_connect_args(conn)
    try:
        # Some dialects reject connect_timeout — retry without it.
        # Merge dialect-specific connect_args (e.g. Trino auth/verify/scheme).
        try:
            eng = sa.create_engine(url, connect_args={**ca, "connect_timeout": 5})
            with eng.connect() as c:
                c.execute(sa.text("SELECT 1"))
        except TypeError:
            eng = sa.create_engine(url, connect_args=ca)
            with eng.connect() as c:
                c.execute(sa.text("SELECT 1"))
        eng.dispose()
        return {"ok": True, "error": None}
    except Exception as e:
        return {"ok": False, "error": str(e)}

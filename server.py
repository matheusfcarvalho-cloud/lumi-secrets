from __future__ import annotations

import base64
import hashlib
import ipaddress
import hmac
import io
import json
import mimetypes
import os
import re
import secrets
import sqlite3
import sys
import threading
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from http.cookies import SimpleCookie
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent
DB_PATH = Path(os.environ.get("LUMI_DB_PATH", ROOT / ".lumi-private" / "lumi_orders.sqlite3"))
PORT = int(os.environ.get("PORT", "8000"))
STATUSES = {"received", "confirmed", "preparing", "shipped", "delivered", "cancelled"}
SESSION_DAYS = 30
PRODUCTS = {
    1: ("Sutiã Aura", "Sutiãs", 18990), 2: ("Calcinha Cora", "Calcinhas", 8990),
    3: ("Conjunto Íris", "Conjuntos", 25990), 4: ("Chemise Nua", "Sleepwear", 22990),
    5: ("Sutiã Brisa", "Sutiãs", 16990), 6: ("Calcinha Flora", "Calcinhas", 7990),
    7: ("Conjunto Sol", "Conjuntos", 27990), 8: ("Robe Lua", "Sleepwear", 24990),
}
ADDRESS_FIELDS = ("cep", "street", "number", "complement", "neighborhood", "city", "state")
_DB_INITIALIZED = False
_DB_INIT_LOCK = threading.Lock()


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class LibsqlRow(Mapping):
    """Expose libsql tuple rows with sqlite3.Row-style name/index access."""

    def __init__(self, columns, values):
        self._columns = tuple(columns)
        self._values = tuple(values)
        self._column_indexes = {name: index for index, name in enumerate(self._columns)}

    def __getitem__(self, key):
        if isinstance(key, str):
            key = self._column_indexes[key]
        return self._values[key]

    def __iter__(self):
        return iter(self._columns)

    def __len__(self):
        return len(self._values)


class LibsqlCursorAdapter:
    def __init__(self, cursor):
        self.cursor = cursor

    def __getattr__(self, name):
        return getattr(self.cursor, name)

    def _adapt(self, values):
        if values is None:
            return None
        return LibsqlRow((column[0] for column in self.cursor.description), values)

    def fetchone(self):
        return self._adapt(self.cursor.fetchone())

    def fetchall(self):
        return [self._adapt(values) for values in self.cursor.fetchall()]

    def fetchmany(self, size=None):
        values = self.cursor.fetchmany() if size is None else self.cursor.fetchmany(size)
        return [self._adapt(row) for row in values]


class LibsqlConnectionAdapter:
    def __init__(self, connection):
        self.connection = connection

    def execute(self, *args, **kwargs):
        return LibsqlCursorAdapter(self.connection.execute(*args, **kwargs))

    def executemany(self, *args, **kwargs):
        return LibsqlCursorAdapter(self.connection.executemany(*args, **kwargs))

    def executescript(self, *args, **kwargs):
        return LibsqlCursorAdapter(self.connection.executescript(*args, **kwargs))

    def __getattr__(self, name):
        return getattr(self.connection, name)


class RemoteConnectionContext:
    def __init__(self, connection):
        self.connection = connection

    def __enter__(self):
        return self.connection

    def __exit__(self, exc_type, exc, traceback):
        try:
            self.connection.rollback() if exc_type else self.connection.commit()
        finally:
            self.connection.close()
        return False


def connect() -> RemoteConnectionContext:
    database_url = os.environ.get("TURSO_DATABASE_URL", "").strip()
    auth_token = os.environ.get("TURSO_AUTH_TOKEN", "").strip()
    if os.environ.get("VERCEL") == "1" and not database_url:
        raise RuntimeError("Configure TURSO_DATABASE_URL e TURSO_AUTH_TOKEN no projeto Vercel; SQLite local não é persistente na Vercel.")
    if database_url:
        if not auth_token:
            raise RuntimeError("TURSO_AUTH_TOKEN precisa estar configurado junto com TURSO_DATABASE_URL.")
        try:
            import libsql
        except ImportError as exc:
            raise RuntimeError("Instale o pacote libsql para usar o banco remoto Turso.") from exc
        db = libsql.connect(database=database_url, auth_token=auth_token)
        return RemoteConnectionContext(LibsqlConnectionAdapter(db))
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    return RemoteConnectionContext(db)


def init_db() -> None:
    """Initialize locally; Vercel functions require a separately migrated DB."""
    global _DB_INITIALIZED
    if os.environ.get("VERCEL") == "1":
        if os.environ.get("LUMI_DB_SCHEMA_READY") != "1":
            raise RuntimeError("Execute `python scripts/migrate_db.py` no banco Turso e defina LUMI_DB_SCHEMA_READY=1 na Vercel antes do deploy.")
        return
    if _DB_INITIALIZED:
        return
    with _DB_INIT_LOCK:
        if _DB_INITIALIZED:
            return
        _initialize_db()
        _DB_INITIALIZED = True


def migrate_db() -> None:
    """Explicitly prepare the configured remote database before deployment."""
    global _DB_INITIALIZED
    if not os.environ.get("TURSO_DATABASE_URL", "").strip():
        raise RuntimeError("TURSO_DATABASE_URL é obrigatório para executar a migração remota.")
    if not os.environ.get("TURSO_AUTH_TOKEN", "").strip():
        raise RuntimeError("TURSO_AUTH_TOKEN é obrigatório para executar a migração remota.")
    with _DB_INIT_LOCK:
        _initialize_db()
        _DB_INITIALIZED = True


def _initialize_db() -> None:
    with connect() as db:
        schema = """
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY, name TEXT NOT NULL, email TEXT NOT NULL UNIQUE COLLATE NOCASE,
                password_hash TEXT NOT NULL, whatsapp TEXT NOT NULL, cep TEXT NOT NULL,
                street TEXT NOT NULL, number TEXT NOT NULL, complement TEXT NOT NULL DEFAULT '',
                neighborhood TEXT NOT NULL, city TEXT NOT NULL, state TEXT NOT NULL,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS sessions (
                token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                expires_at TEXT NOT NULL, created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_sessions_expiry ON sessions(expires_at);
            CREATE TABLE IF NOT EXISTS admin_credentials (
                id INTEGER PRIMARY KEY CHECK(id = 1), email TEXT NOT NULL UNIQUE COLLATE NOCASE,
                password_hash TEXT NOT NULL, created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS admin_sessions (
                token_hash TEXT PRIMARY KEY, expires_at TEXT NOT NULL, created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_admin_sessions_expiry ON admin_sessions(expires_at);
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, model TEXT NOT NULL DEFAULT '',
                type TEXT NOT NULL, label TEXT NOT NULL DEFAULT '', price_cents INTEGER NOT NULL CHECK(price_cents >= 0),
                image TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS product_images (
                id TEXT PRIMARY KEY, mime TEXT NOT NULL, data BLOB NOT NULL, created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS feedbacks (
                id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT NOT NULL REFERENCES users(id),
                customer_name TEXT NOT NULL, message TEXT NOT NULL, rating INTEGER NOT NULL DEFAULT 5,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_feedback_created ON feedbacks(created_at DESC);
            CREATE TABLE IF NOT EXISTS orders (
                id TEXT PRIMARY KEY, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                customer_name TEXT NOT NULL, whatsapp TEXT NOT NULL, status TEXT NOT NULL,
                user_id TEXT REFERENCES users(id), delivery_address TEXT NOT NULL DEFAULT '{}',
                total_cents INTEGER NOT NULL CHECK(total_cents >= 0),
                payment_status TEXT NOT NULL DEFAULT 'not_started', payment_method TEXT NOT NULL DEFAULT '',
                payment_url TEXT NOT NULL DEFAULT '', payment_invoice_slug TEXT NOT NULL DEFAULT '',
                payment_transaction_nsu TEXT NOT NULL DEFAULT '', payment_receipt_url TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS shop_settings (
                setting_key TEXT PRIMARY KEY, setting_value TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS order_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT, order_id TEXT NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
                product_id INTEGER NOT NULL, product_name TEXT NOT NULL, model TEXT NOT NULL,
                unit_price_cents INTEGER NOT NULL, quantity INTEGER NOT NULL CHECK(quantity > 0)
            );
            CREATE TABLE IF NOT EXISTS order_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT, order_id TEXT NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
                occurred_at TEXT NOT NULL, event_type TEXT NOT NULL, description TEXT NOT NULL,
                details_json TEXT NOT NULL DEFAULT '{}'
            );
            CREATE INDEX IF NOT EXISTS idx_orders_created ON orders(created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_history_order ON order_history(order_id, occurred_at DESC);
        """
        for statement in schema.split(";"):
            if statement.strip():
                db.execute(statement)
        # Migrate databases created before customer accounts and delivery snapshots.
        order_columns = {row[1] for row in db.execute("PRAGMA table_info(orders)").fetchall()}
        if "user_id" not in order_columns:
            db.execute("ALTER TABLE orders ADD COLUMN user_id TEXT REFERENCES users(id)")
        if "delivery_address" not in order_columns:
            db.execute("ALTER TABLE orders ADD COLUMN delivery_address TEXT NOT NULL DEFAULT '{}'")
        for column, definition in {
            "payment_status": "TEXT NOT NULL DEFAULT 'not_started'", "payment_method": "TEXT NOT NULL DEFAULT ''",
            "payment_url": "TEXT NOT NULL DEFAULT ''", "payment_invoice_slug": "TEXT NOT NULL DEFAULT ''",
            "payment_transaction_nsu": "TEXT NOT NULL DEFAULT ''", "payment_receipt_url": "TEXT NOT NULL DEFAULT ''",
        }.items():
            if column not in order_columns:
                db.execute(f"ALTER TABLE orders ADD COLUMN {column} {definition}")
        feedback_columns = {row[1] for row in db.execute("PRAGMA table_info(feedbacks)").fetchall()}
        if "rating" not in feedback_columns:
            db.execute("ALTER TABLE feedbacks ADD COLUMN rating INTEGER NOT NULL DEFAULT 5")
        timestamp = now_utc()
        for product_id, (name, model, price_cents) in PRODUCTS.items():
            db.execute("INSERT OR IGNORE INTO products(id,name,model,type,label,price_cents,image,active,created_at,updated_at) VALUES (?,?,?,?,?,?,?,1,?,?)",
                       (product_id, name, model, model.lower(), {1:"Novo",2:"Best-seller",3:"Edição limitada",7:"Novo"}.get(product_id, ""), price_cents,
                        {1:"https://images.unsplash.com/photo-1596755389378-c31d21fd1273?auto=format&fit=crop&w=700&q=80",2:"https://images.unsplash.com/photo-1617331140180-e8262094733a?auto=format&fit=crop&w=700&q=80",3:"https://images.unsplash.com/photo-1566206091558-7f218b696731?auto=format&fit=crop&w=700&q=80",4:"https://images.unsplash.com/photo-1583846783214-7229a91b20ed?auto=format&fit=crop&w=700&q=80",5:"https://images.unsplash.com/photo-1604176354204-9268737828e4?auto=format&fit=crop&w=700&q=80",6:"https://images.unsplash.com/photo-1551488831-00ddcb6c6bd3?auto=format&fit=crop&w=700&q=80",7:"https://images.unsplash.com/photo-1572804013309-59a88b7e92f1?auto=format&fit=crop&w=700&q=80",8:"https://images.unsplash.com/photo-1544441893-675973e31985?auto=format&fit=crop&w=700&q=80"}[product_id], timestamp, timestamp))


def serialize_user(row: sqlite3.Row) -> dict:
    return {key: row[key] for key in ("id", "name", "email", "whatsapp", *ADDRESS_FIELDS)}


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1)
    return f"scrypt${salt.hex()}${digest.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, salt_hex, digest_hex = encoded.split("$", 2)
        if algorithm != "scrypt":
            return False
        digest = hashlib.scrypt(password.encode("utf-8"), salt=bytes.fromhex(salt_hex), n=2**14, r=8, p=1)
        return hmac.compare_digest(digest.hex(), digest_hex)
    except (ValueError, TypeError):
        return False


def normalize_profile(data: dict, require_email: bool = False) -> dict:
    profile = {key: str(data.get(key, "")).strip() for key in ("name", "email", "whatsapp", *ADDRESS_FIELDS)}
    profile["name"] = profile["name"][:120]
    profile["email"] = profile["email"][:254].lower()
    profile["whatsapp"] = re.sub(r"[^0-9+() -]", "", profile["whatsapp"])[:30]
    profile["state"] = profile["state"][:2].upper()
    if len(profile["name"]) < 2:
        raise ValueError("Informe seu nome completo.")
    if require_email and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", profile["email"]):
        raise ValueError("Informe um e-mail válido.")
    if len(re.sub(r"\D", "", profile["whatsapp"])) < 8:
        raise ValueError("Informe um WhatsApp válido.")
    if len(re.sub(r"\D", "", profile["cep"])) not in (8, 9):
        raise ValueError("Informe um CEP válido.")
    for key in ("street", "number", "neighborhood", "city", "state"):
        if not profile[key]:
            raise ValueError("Preencha todos os campos obrigatórios do endereço.")
    return profile


def normalize_product(data: dict) -> tuple[str, str, str, str, int, str]:
    name = str(data.get("name", "")).strip()[:120]
    model = str(data.get("model", "")).strip()[:120]
    product_type = str(data.get("type", "")).strip().lower()[:40]
    label = str(data.get("label", "")).strip()[:60]
    image = str(data.get("image", "")).strip()[:1000]
    try:
        price_cents = int(data.get("price_cents"))
    except (TypeError, ValueError):
        raise ValueError("Informe um valor válido para o produto.")
    if len(name) < 2:
        raise ValueError("Informe o nome do produto.")
    if product_type not in {"sutiãs", "calcinhas", "conjuntos", "sleepwear"}:
        raise ValueError("Escolha uma categoria válida.")
    if price_cents < 0 or price_cents > 100_000_000:
        raise ValueError("O valor precisa estar entre R$ 0,00 e R$ 1.000.000,00.")
    if not (image.startswith("https://") or image.startswith("http://") or image.startswith("assets/") or image.startswith("/assets/")
            or re.fullmatch(r"/api/product-images/[a-f0-9]{32}", image)):
        raise ValueError("Use um link de imagem HTTP ou um arquivo dentro de assets.")
    return name, model, product_type, label, price_cents, image


def order_detail(db: sqlite3.Connection, order_id: str) -> dict | None:
    order = db.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
    if order is None:
        return None
    result = dict(order)
    result["delivery_address"] = parse_json_object(result.get("delivery_address"))
    result["items"] = [dict(r) for r in db.execute(
        "SELECT product_id, product_name, model, unit_price_cents, quantity FROM order_items WHERE order_id = ? ORDER BY id", (order_id,)
    )]
    result["history"] = []
    for event in db.execute(
        "SELECT occurred_at, event_type, description, details_json FROM order_history WHERE order_id = ? ORDER BY id", (order_id,)
    ):
        item = dict(event)
        item["details"] = parse_json_object(item.pop("details_json", None))
        result["history"].append(item)
    return result


def parse_json_object(value) -> dict:
    try:
        parsed = json.loads(value or "{}")
    except (json.JSONDecodeError, TypeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def json_fallback(value):
    """Convert driver-specific values into JSON-safe values for API responses."""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    isoformat = getattr(value, "isoformat", None)
    if callable(isoformat):
        return isoformat()
    return str(value)


class LumiHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def send_json(self, status: int, payload: dict, extra_headers: dict | None = None) -> None:
        body = json.dumps(payload, ensure_ascii=False, default=json_fallback).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for key, value in (extra_headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def send_binary(self, status: int, payload: bytes, mime: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "public, max-age=31536000, immutable")
        self.end_headers()
        self.wfile.write(payload)

    def read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        max_length = 4_300_000 if self.path.startswith("/api/admin/products") else 64_000
        if length <= 0 or length > max_length:
            raise ValueError("Corpo da requisição vazio ou muito grande.")
        data = json.loads(self.rfile.read(length).decode("utf-8"))
        if not isinstance(data, dict):
            raise ValueError("Formato inválido.")
        return data

    def session_token(self) -> str | None:
        cookie = SimpleCookie()
        cookie.load(self.headers.get("Cookie", ""))
        morsel = cookie.get("lumi_session")
        return morsel.value if morsel else None

    def current_user(self, db: sqlite3.Connection) -> sqlite3.Row | None:
        token = self.session_token()
        if not token:
            return None
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        row = db.execute(
            "SELECT users.* FROM sessions JOIN users ON users.id = sessions.user_id WHERE sessions.token_hash = ? AND sessions.expires_at > ?",
            (token_hash, now_utc()),
        ).fetchone()
        return row

    def session_cookie(self, raw_token: str, max_age: int = SESSION_DAYS * 86400) -> str:
        secure = "; Secure" if os.environ.get("LUMI_HTTPS_ONLY") == "1" or os.environ.get("VERCEL") == "1" else ""
        return f"lumi_session={raw_token}; HttpOnly; Path=/; SameSite=Lax; Max-Age={max_age}{secure}"

    def issue_session(self, db: sqlite3.Connection, user_id: str) -> str:
        raw_token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
        timestamp = now_utc()
        expires = (datetime.now(timezone.utc) + timedelta(days=SESSION_DAYS)).isoformat(timespec="seconds")
        db.execute("DELETE FROM sessions WHERE expires_at <= ?", (timestamp,))
        db.execute("INSERT INTO sessions(token_hash, user_id, expires_at, created_at) VALUES (?, ?, ?, ?)",
                   (token_hash, user_id, expires, timestamp))
        return raw_token

    def admin_cookie(self, raw_token: str, max_age: int = SESSION_DAYS * 86400) -> str:
        secure = "; Secure" if os.environ.get("LUMI_HTTPS_ONLY") == "1" or os.environ.get("VERCEL") == "1" else ""
        return f"lumi_admin_session={raw_token}; HttpOnly; Path=/; SameSite=Lax; Max-Age={max_age}{secure}"

    def admin_allowed(self) -> bool:
        cookie = SimpleCookie()
        cookie.load(self.headers.get("Cookie", ""))
        morsel = cookie.get("lumi_admin_session")
        if not morsel:
            return False
        token_hash = hashlib.sha256(morsel.value.encode("utf-8")).hexdigest()
        with connect() as db:
            return db.execute("SELECT 1 FROM admin_sessions WHERE token_hash = ? AND expires_at > ?",
                              (token_hash, now_utc())).fetchone() is not None
    def do_GET(self) -> None:
        path = unquote(urlparse(self.path).path)
        if path in ("/server.py", "/ORDERS_DATABASE.md"):
            self.send_error(404)
            return
        if path in ("/admin", "/admin/", "/admin.html"):
            self.path = "/admin.html"
            super().do_GET()
            return
        image_match = re.fullmatch(r"/api/product-images/([a-f0-9]{32})", path)
        if image_match:
            init_db()
            with connect() as db:
                image = db.execute("SELECT mime,data FROM product_images WHERE id=?", (image_match.group(1),)).fetchone()
            if image is None:
                self.send_json(404, {"error": "Imagem nÃ£o encontrada."})
            else:
                self.send_binary(200, bytes(image["data"]), image["mime"])
            return
        if path == "/api/admin/status":
            init_db()
            with connect() as db:
                has_owner = db.execute("SELECT 1 FROM admin_credentials WHERE id = 1").fetchone() is not None
                required_order_schema = {
                    "orders": {"id", "created_at", "updated_at", "customer_name", "whatsapp", "status", "user_id", "delivery_address", "total_cents", "payment_status", "payment_method", "payment_url", "payment_invoice_slug", "payment_transaction_nsu", "payment_receipt_url"},
                    "order_items": {"id", "order_id", "product_id", "product_name", "model", "unit_price_cents", "quantity"},
                    "order_history": {"id", "order_id", "occurred_at", "event_type", "description", "details_json"},
                }
                missing_order_schema = {}
                for table, required_columns in required_order_schema.items():
                    columns = {row[1] for row in db.execute(f"PRAGMA table_info({table})").fetchall()}
                    missing = sorted(required_columns - columns)
                    if missing:
                        missing_order_schema[table] = missing
            environment_owner = bool(os.environ.get("LUMI_ADMIN_EMAIL") and os.environ.get("LUMI_ADMIN_PASSWORD"))
            setup_allowed = not has_owner and not environment_owner and self.is_local_request()
            self.send_json(200, {"configured": has_owner or environment_owner, "setup_allowed": setup_allowed,
                                 "orders_schema_ready": not missing_order_schema,
                                 "orders_schema_missing": missing_order_schema})
            return
        if path.startswith("/.lumi-private/"):
            self.send_error(404)
            return
        if path == "/api/auth/me":
            init_db()
            with connect() as db:
                user = self.current_user(db)
                self.send_json(200, {"user": serialize_user(user) if user else None})
            return
        if path == "/api/products":
            init_db()
            with connect() as db:
                rows = db.execute("SELECT id,name,model,type,label,price_cents,image FROM products WHERE active=1 ORDER BY id").fetchall()
            self.send_json(200, {"products": [dict(row) for row in rows]})
            return
        if path == "/api/feedback":
            init_db()
            with connect() as db:
                rows = db.execute("SELECT id,customer_name,message,rating,created_at FROM feedbacks ORDER BY created_at DESC").fetchall()
            self.send_json(200, {"feedbacks": [dict(row) for row in rows]})
            return
        if path == "/api/admin/payment-settings":
            if not self.admin_allowed():
                self.send_json(401, {"error": "Acesso administrativo necessário."})
                return
            init_db()
            with connect() as db:
                rows = {row["setting_key"]: row["setting_value"] for row in db.execute("SELECT setting_key,setting_value FROM shop_settings WHERE setting_key IN ('infinitepay_handle','public_url')")}
            self.send_json(200, {"handle": rows.get("infinitepay_handle", ""), "public_url": rows.get("public_url", ""), "configured": bool(rows.get("infinitepay_handle"))})
            return
        if path in ("/api/admin/products", "/api/admin/feedback", "/api/admin/customers"):
            if not self.admin_allowed():
                self.send_json(401, {"error": "Acesso administrativo necessário."})
                return
            init_db()
            with connect() as db:
                if path.endswith("products"):
                    rows = db.execute("SELECT id,name,model,type,label,price_cents,image,active FROM products ORDER BY active DESC,id").fetchall()
                    self.send_json(200, {"products": [dict(row) for row in rows]})
                elif path.endswith("feedback"):
                    rows = db.execute("SELECT f.id,f.customer_name,f.message,f.rating,f.created_at,u.email FROM feedbacks f JOIN users u ON u.id=f.user_id ORDER BY f.created_at DESC").fetchall()
                    self.send_json(200, {"feedbacks": [dict(row) for row in rows]})
                else:
                    rows = db.execute("SELECT u.id,u.name,u.email,u.whatsapp,u.cep,u.street,u.number,u.complement,u.neighborhood,u.city,u.state,u.created_at,COUNT(o.id) AS order_count,COALESCE(SUM(o.total_cents),0) AS spent_cents FROM users u LEFT JOIN orders o ON o.user_id=u.id GROUP BY u.id ORDER BY u.created_at DESC").fetchall()
                    self.send_json(200, {"customers": [dict(row) for row in rows]})
            return
        if path == "/api/orders" or path.startswith("/api/orders/"):
            if not self.admin_allowed():
                self.send_json(401, {"error": "Acesso administrativo necessário."})
                return
            init_db()
            with connect() as db:
                if path == "/api/orders":
                    try:
                        ids = [r[0] for r in db.execute("SELECT id FROM orders ORDER BY created_at DESC")]
                        orders = [order_detail(db, order_id) for order_id in ids]
                    except Exception as exc:
                        diagnostic = type(exc).__name__
                        if isinstance(exc, json.JSONDecodeError):
                            diagnostic = "invalid JSON in saved order data"
                        elif isinstance(exc, KeyError) and exc.args and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", str(exc.args[0])):
                            diagnostic = f"missing field: {exc.args[0]}"
                        else:
                            safe_sql_error = re.fullmatch(r"no such (?:table|column): [A-Za-z_][A-Za-z0-9_]*", str(exc), re.IGNORECASE)
                            if safe_sql_error:
                                diagnostic = safe_sql_error.group(0)
                        print(f"Admin orders API failed: {diagnostic}")
                        self.send_json(500, {"error": f"Falha ao carregar pedidos ({diagnostic})."})
                        return
                    self.send_json(200, {"orders": orders})
                    return
                result = order_detail(db, path.removeprefix("/api/orders/"))
                self.send_json(200 if result else 404, result or {"error": "Pedido não encontrado."})
                return
        super().do_GET()

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/admin/setup":
            self.handle_admin_setup()
            return
        if path == "/api/admin/login":
            self.handle_admin_login()
            return
        if path == "/api/admin/logout":
            self.handle_admin_logout()
            return
        if path in ("/api/auth/register", "/api/auth/login", "/api/auth/logout"):
            self.handle_auth_post(path)
            return
        if path == "/api/feedback":
            self.handle_feedback_post()
            return
        if path == "/api/admin/products":
            if not self.admin_allowed():
                self.send_json(401, {"error": "Acesso administrativo necessário."})
                return
            self.handle_product_post()
            return
        if path == "/api/admin/product-image":
            if not self.admin_allowed():
                self.send_json(401, {"error": "Acesso administrativo necessário."})
                return
            self.handle_product_image_upload()
            return
        if path == "/api/admin/payment-settings":
            if not self.admin_allowed():
                self.send_json(401, {"error": "Acesso administrativo necessário."})
                return
            self.handle_payment_settings_save()
            return
        if path == "/api/payments/infinitepay/confirm":
            self.handle_infinitepay_confirm()
            return
        if path == "/api/payments/infinitepay/webhook":
            self.handle_infinitepay_webhook()
            return
        if path != "/api/orders":
            self.send_json(404, {"error": "Rota não encontrada."})
            return
        try:
            data = self.read_json()
            raw_items = data.get("items")
            if not isinstance(raw_items, list) or not raw_items or len(raw_items) > 100:
                raise ValueError("O pedido precisa ter ao menos um item.")
            quantities: dict[int, int] = {}
            for item in raw_items:
                if not isinstance(item, dict): raise ValueError("Item inválido.")
                product_id = int(item.get("id", 0))
                if product_id < 1: raise ValueError("Produto inválido.")
                quantities[product_id] = quantities.get(product_id, 0) + 1
            timestamp, order_id = now_utc(), secrets.token_hex(6).upper()
            init_db()
            with connect() as db:
                settings = {row["setting_key"]: row["setting_value"] for row in db.execute("SELECT setting_key,setting_value FROM shop_settings WHERE setting_key IN ('infinitepay_handle','public_url')")}
                handle = settings.get("infinitepay_handle", "")
                if not handle or not settings.get("public_url"):
                    self.send_json(503, {"error": "Configure a InfiniteTag e o endereço HTTPS público da loja no painel para ativar o checkout."})
                    return
                products = {row["id"]: row for row in db.execute(f"SELECT id,name,model,type,price_cents FROM products WHERE active=1 AND id IN ({','.join('?' for _ in quantities)})", tuple(quantities))}
                if len(products) != len(quantities): raise ValueError("Um produto do pedido não está mais disponível.")
                total = sum(products[pid]["price_cents"] * qty for pid, qty in quantities.items())
                user = self.current_user(db)
                if user is None:
                    self.send_json(401, {"error": "Entre ou crie seu perfil antes de finalizar."})
                    return
                address = {key:user[key] for key in ADDRESS_FIELDS}
                db.execute("INSERT INTO orders(id,created_at,updated_at,customer_name,whatsapp,status,total_cents,user_id,delivery_address,payment_status) VALUES (?,?,?,?,?,?,?,?,?,'creating')",
                           (order_id,timestamp,timestamp,user["name"],user["whatsapp"],"received",total,user["id"],json.dumps(address,ensure_ascii=False)))
                for product_id, quantity in quantities.items():
                    product = products[product_id]
                    db.execute("INSERT INTO order_items(order_id,product_id,product_name,model,unit_price_cents,quantity) VALUES (?,?,?,?,?,?)",
                               (order_id,product_id,product["name"],product["model"] or product["type"],product["price_cents"],quantity))
                db.execute("INSERT INTO order_history(order_id,occurred_at,event_type,description,details_json) VALUES (?,?,?,?,?)",
                           (order_id,timestamp,"order_created","Pedido criado; aguardando pagamento pela InfinitePay.",json.dumps({"status":"received","payment_status":"creating"})))
                buyer = {"name":user["name"],"email":user["email"],"phone_number":user["whatsapp"]}
                item_payload = [{"quantity":qty,"price":products[pid]["price_cents"],"description":products[pid]["name"][:120]} for pid,qty in quantities.items()]
            payload = {"handle":handle,"order_nsu":order_id,"items":item_payload,"customer":buyer}
            public_url = settings.get("public_url","").rstrip("/")
            if public_url:
                payload["redirect_url"] = f"{public_url}/payment-return.html"
                payload["webhook_url"] = f"{public_url}/api/payments/infinitepay/webhook"
            request = Request("https://api.checkout.infinitepay.io/links",data=json.dumps(payload).encode("utf-8"),headers={"Content-Type":"application/json","Accept":"application/json"},method="POST")
            try:
                with urlopen(request,timeout=20) as response: checkout=json.loads(response.read().decode("utf-8"))
            except Exception:
                with connect() as db: db.execute("UPDATE orders SET payment_status='link_error',updated_at=? WHERE id=?",(now_utc(),order_id))
                self.send_json(502,{"error":"A InfinitePay não conseguiu gerar o link agora. O pedido ficou pendente; tente novamente ou confira a conta."})
                return
            checkout_url=str(checkout.get("url",""))
            if not checkout_url.startswith("https://checkout.infinitepay.com.br/"):
                with connect() as db: db.execute("UPDATE orders SET payment_status='link_error',updated_at=? WHERE id=?",(now_utc(),order_id))
                self.send_json(502,{"error":"A InfinitePay retornou um link de checkout inválido."})
                return
            with connect() as db: db.execute("UPDATE orders SET payment_status='pending',payment_url=?,updated_at=? WHERE id=?",(checkout_url,now_utc(),order_id))
            self.send_json(201,{"id":order_id,"status":"received","payment_status":"pending","total_cents":total,"checkout_url":checkout_url})
        except (ValueError,TypeError,json.JSONDecodeError) as exc:
            self.send_json(400,{"error":str(exc)})
        except Exception:
            self.send_json(500,{"error":"Não foi possível criar o pedido e o checkout."})

    def handle_payment_settings_save(self) -> None:
        try:
            data=self.read_json(); handle=str(data.get("handle","")).strip().lstrip("$")[:80]; public_url=str(data.get("public_url","")).strip().rstrip("/")[:300]
            if handle and not re.fullmatch(r"[A-Za-z0-9_.-]{2,80}",handle): raise ValueError("Informe a InfiniteTag sem o símbolo $.")
            if public_url and (not public_url.startswith("https://") or not urlparse(public_url).netloc): raise ValueError("Informe o endereço HTTPS público da loja; em localhost, deixe em branco por enquanto.")
            timestamp=now_utc()
            with connect() as db:
                for key,value in (("infinitepay_handle",handle),("public_url",public_url)):
                    db.execute("INSERT INTO shop_settings(setting_key,setting_value,updated_at) VALUES (?,?,?) ON CONFLICT(setting_key) DO UPDATE SET setting_value=excluded.setting_value,updated_at=excluded.updated_at",(key,value,timestamp))
            self.send_json(200,{"ok":True,"configured":bool(handle)})
        except (ValueError,TypeError,json.JSONDecodeError) as exc: self.send_json(400,{"error":str(exc)})
        except Exception: self.send_json(500,{"error":"Não foi possível salvar a configuração da InfinitePay."})

    def check_infinitepay_payment(self, order_nsu: str, transaction_nsu: str, slug: str) -> dict:
        with connect() as db:
            settings={row["setting_key"]:row["setting_value"] for row in db.execute("SELECT setting_key,setting_value FROM shop_settings WHERE setting_key='infinitepay_handle'")}
        handle=settings.get("infinitepay_handle","")
        if not handle: raise ValueError("InfiniteTag não configurada.")
        payload={"handle":handle,"order_nsu":order_nsu,"transaction_nsu":transaction_nsu,"slug":slug}
        request=Request("https://api.checkout.infinitepay.io/payment_check",data=json.dumps(payload).encode("utf-8"),headers={"Content-Type":"application/json","Accept":"application/json"},method="POST")
        with urlopen(request,timeout=15) as response: result=json.loads(response.read().decode("utf-8"))
        return result if isinstance(result,dict) else {}

    def apply_infinitepay_payment(self, data: dict) -> dict:
        order_id=str(data.get("order_nsu",""))[:40]; transaction_nsu=str(data.get("transaction_nsu",""))[:120]; slug=str(data.get("slug",data.get("invoice_slug","")))[:120]
        if not re.fullmatch(r"[A-Fa-f0-9]{8,40}",order_id) or not transaction_nsu or not slug: raise ValueError("Identificação do pagamento inválida.")
        result=self.check_infinitepay_payment(order_id,transaction_nsu,slug)
        if not result.get("success") or not result.get("paid"): return {"paid":False,"order_id":order_id}
        with connect() as db:
            order=db.execute("SELECT total_cents,payment_status FROM orders WHERE id=?",(order_id,)).fetchone()
            if order is None: raise ValueError("Pedido não encontrado.")
            if int(result.get("amount",-1)) != int(order["total_cents"]): raise ValueError("O valor confirmado não corresponde ao pedido.")
            if result.get("capture_method") not in ("pix","credit_card"): raise ValueError("Forma de pagamento não reconhecida.")
            timestamp=now_utc()
            db.execute("UPDATE orders SET payment_status='paid',payment_method=?,payment_invoice_slug=?,payment_transaction_nsu=?,payment_receipt_url=?,updated_at=? WHERE id=?",(result["capture_method"],slug,transaction_nsu,str(data.get("receipt_url",""))[:500],timestamp,order_id))
            if order["payment_status"] != "paid":
                db.execute("INSERT INTO order_history(order_id,occurred_at,event_type,description,details_json) VALUES (?,?,?,?,?)",(order_id,timestamp,"payment_confirmed","Pagamento confirmado pela InfinitePay.",json.dumps({"method":result["capture_method"],"transaction_nsu":transaction_nsu})))
        return {"paid":True,"order_id":order_id,"method":result["capture_method"]}

    def handle_infinitepay_confirm(self) -> None:
        try: self.send_json(200,self.apply_infinitepay_payment(self.read_json()))
        except (ValueError,TypeError,json.JSONDecodeError) as exc: self.send_json(400,{"error":str(exc)})
        except Exception: self.send_json(502,{"error":"Não foi possível confirmar o pagamento com a InfinitePay."})

    def handle_infinitepay_webhook(self) -> None:
        try: self.apply_infinitepay_payment(self.read_json()); self.send_json(200,{"ok":True})
        except (ValueError,TypeError,json.JSONDecodeError) as exc: self.send_json(400,{"error":str(exc)})
        except Exception: self.send_json(400,{"error":"Webhook não confirmado."})

    def handle_product_image_upload(self) -> None:
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > 4_300_000:
                raise ValueError("A foto precisa ter no máximo 3 MB.")
            data = json.loads(self.rfile.read(length).decode("utf-8"))
            if not isinstance(data, dict):
                raise ValueError("Arquivo de imagem inválido.")
            mime = str(data.get("mime", ""))
            formats = {
                "image/jpeg": ("jpg", lambda content: content.startswith(b"\xff\xd8\xff")),
                "image/png": ("png", lambda content: content.startswith(b"\x89PNG\r\n\x1a\n")),
                "image/webp": ("webp", lambda content: len(content) >= 12 and content.startswith(b"RIFF") and content[8:12] == b"WEBP"),
            }
            if mime not in formats:
                raise ValueError("Escolha uma imagem JPG, PNG ou WEBP.")
            raw = base64.b64decode(str(data.get("data", "")), validate=True)
            if not raw or len(raw) > 3 * 1024 * 1024:
                raise ValueError("A foto precisa ter no máximo 3 MB.")
            extension, is_valid = formats[mime]
            if not is_valid(raw):
                raise ValueError("O formato do arquivo não corresponde a uma imagem válida.")
            image_id = secrets.token_hex(16)
            init_db()
            with connect() as db:
                db.execute("INSERT INTO product_images(id,mime,data,created_at) VALUES (?,?,?,?)", (image_id, mime, raw, now_utc()))
            self.send_json(201, {"image": f"/api/product-images/{image_id}"})
        except (ValueError, TypeError, json.JSONDecodeError, base64.binascii.Error) as exc:
            self.send_json(400, {"error": str(exc) or "Arquivo de imagem inválido."})
        except Exception:
            self.send_json(500, {"error": "Não foi possível salvar a imagem."})

    def handle_product_post(self) -> None:
        try:
            data = self.read_json()
            values = normalize_product(data)
            timestamp = now_utc()
            with connect() as db:
                cursor = db.execute("INSERT INTO products(name,model,type,label,price_cents,image,active,created_at,updated_at) VALUES (?,?,?,?,?,?,1,?,?)",
                                    (*values, timestamp, timestamp))
                product = db.execute("SELECT id,name,model,type,label,price_cents,image,active FROM products WHERE id=?", (cursor.lastrowid,)).fetchone()
            self.send_json(201, {"product": dict(product)})
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            self.send_json(400, {"error": str(exc)})
        except Exception:
            self.send_json(500, {"error": "Não foi possível cadastrar o produto."})

    def handle_product_patch(self, product_id: int) -> None:
        try:
            data = self.read_json()
            with connect() as db:
                current = db.execute("SELECT * FROM products WHERE id=?", (product_id,)).fetchone()
                if current is None:
                    self.send_json(404, {"error": "Produto não encontrado."})
                    return
                if "active" in data and len(data) == 1:
                    active = 1 if bool(data["active"]) else 0
                    db.execute("UPDATE products SET active=?,updated_at=? WHERE id=?", (active, now_utc(), product_id))
                else:
                    values = normalize_product(data)
                    db.execute("UPDATE products SET name=?,model=?,type=?,label=?,price_cents=?,image=?,updated_at=? WHERE id=?",
                               (*values, now_utc(), product_id))
                product = db.execute("SELECT id,name,model,type,label,price_cents,image,active FROM products WHERE id=?", (product_id,)).fetchone()
            self.send_json(200, {"product": dict(product)})
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            self.send_json(400, {"error": str(exc)})
        except Exception:
            self.send_json(500, {"error": "Não foi possível atualizar o produto."})

    def handle_feedback_post(self) -> None:
        try:
            data = self.read_json()
            message = str(data.get("message", "")).strip()[:2000]
            try:
                rating = int(data.get("rating", 0))
            except (TypeError, ValueError):
                raise ValueError("Escolha uma nota de 1 a 5 estrelas.")
            if len(message) < 3:
                raise ValueError("Escreva um feedback com pelo menos 3 caracteres.")
            if rating < 1 or rating > 5:
                raise ValueError("Escolha uma nota de 1 a 5 estrelas.")
            init_db()
            with connect() as db:
                user = self.current_user(db)
                if user is None:
                    self.send_json(401, {"error": "Entre no seu perfil para enviar um feedback."})
                    return
                if not db.execute("SELECT 1 FROM orders WHERE user_id=? LIMIT 1", (user["id"],)).fetchone():
                    self.send_json(403, {"error": "O feedback fica disponível após realizar uma compra."})
                    return
                timestamp = now_utc()
                cursor = db.execute("INSERT INTO feedbacks(user_id,customer_name,message,rating,created_at) VALUES (?,?,?,?,?)",
                                    (user["id"], user["name"], message, rating, timestamp))
                feedback = db.execute("SELECT id,customer_name,message,rating,created_at FROM feedbacks WHERE id=?", (cursor.lastrowid,)).fetchone()
            self.send_json(201, {"feedback": dict(feedback)})
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            self.send_json(400, {"error": str(exc)})
        except Exception:
            self.send_json(500, {"error": "Não foi possível salvar o feedback."})

    def is_local_request(self) -> bool:
        try:
            address = ipaddress.ip_address(self.client_address[0])
            if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
                address = address.ipv4_mapped
            return address.is_loopback
        except ValueError:
            return False

    def handle_admin_setup(self) -> None:
        if not self.is_local_request():
            self.send_json(403, {"error": "A configuração inicial só pode ser feita neste computador."})
            return
        if os.environ.get("LUMI_ADMIN_EMAIL") and os.environ.get("LUMI_ADMIN_PASSWORD"):
            self.send_json(409, {"error": "O acesso administrativo já está configurado pelo servidor."})
            return
        try:
            data = self.read_json()
            email = str(data.get("email", "")).strip().lower()[:254]
            password = str(data.get("password", ""))
            if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
                raise ValueError("Informe um e-mail válido.")
            if len(password) < 6:
                raise ValueError("A senha precisa ter pelo menos 6 caracteres.")
            init_db()
            with connect() as db:
                if db.execute("SELECT 1 FROM admin_credentials WHERE id = 1").fetchone():
                    self.send_json(409, {"error": "O acesso do dono já foi cadastrado."})
                    return
                db.execute("INSERT INTO admin_credentials(id, email, password_hash, created_at) VALUES (1, ?, ?, ?)",
                           (email, hash_password(password), now_utc()))
            self.send_json(201, {"ok": True})
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            self.send_json(400, {"error": str(exc)})
        except sqlite3.IntegrityError:
            self.send_json(409, {"error": "O acesso do dono já foi cadastrado."})
        except Exception:
            self.send_json(500, {"error": "Não foi possível cadastrar o acesso do dono."})

    def handle_admin_login(self) -> None:
        try:
            data = self.read_json()
            expected_email = os.environ.get("LUMI_ADMIN_EMAIL", "").strip().lower()
            expected_password = os.environ.get("LUMI_ADMIN_PASSWORD", "")
            email = str(data.get("email", "")).strip().lower()
            password = str(data.get("password", ""))
            if expected_email and expected_password:
                valid = secrets.compare_digest(email, expected_email) and secrets.compare_digest(password, expected_password)
            else:
                init_db()
                with connect() as db:
                    owner = db.execute("SELECT email, password_hash FROM admin_credentials WHERE id = 1").fetchone()
                valid = bool(owner) and secrets.compare_digest(email, owner["email"].lower()) and verify_password(password, owner["password_hash"])
            if not valid:
                self.send_json(401, {"error": "E-mail ou senha incorretos."})
                return
            init_db()
            raw_token = secrets.token_urlsafe(32)
            token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
            timestamp = now_utc()
            expires = (datetime.now(timezone.utc) + timedelta(hours=8)).isoformat(timespec="seconds")
            with connect() as db:
                db.execute("DELETE FROM admin_sessions WHERE expires_at <= ?", (timestamp,))
                db.execute("INSERT INTO admin_sessions(token_hash, expires_at, created_at) VALUES (?, ?, ?)",
                           (token_hash, expires, timestamp))
            self.send_json(200, {"ok": True}, {"Set-Cookie": self.admin_cookie(raw_token, 8 * 3600)})
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            self.send_json(400, {"error": str(exc)})
        except Exception:
            self.send_json(500, {"error": "Não foi possível iniciar a sessão administrativa."})

    def handle_admin_logout(self) -> None:
        cookie = SimpleCookie()
        cookie.load(self.headers.get("Cookie", ""))
        morsel = cookie.get("lumi_admin_session")
        if morsel:
            token_hash = hashlib.sha256(morsel.value.encode("utf-8")).hexdigest()
            with connect() as db:
                db.execute("DELETE FROM admin_sessions WHERE token_hash = ?", (token_hash,))
        self.send_json(200, {"ok": True}, {"Set-Cookie": self.admin_cookie("", 0)})
    def handle_auth_post(self, path: str) -> None:
        if path == "/api/auth/logout":
            token = self.session_token()
            if token:
                token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
                with connect() as db:
                    db.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash,))
            self.send_json(200, {"ok": True}, {"Set-Cookie": self.session_cookie("", 0)})
            return
        try:
            data = self.read_json()
            init_db()
            with connect() as db:
                if path.endswith("/register"):
                    profile = normalize_profile(data, require_email=True)
                    password = str(data.get("password", ""))
                    if len(password) < 6:
                        raise ValueError("A senha precisa ter pelo menos 6 caracteres.")
                    user_id, timestamp = secrets.token_hex(12), now_utc()
                    try:
                        db.execute("INSERT INTO users(id,name,email,password_hash,whatsapp,cep,street,number,complement,neighborhood,city,state,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                            (user_id, profile["name"], profile["email"], hash_password(password), profile["whatsapp"], *(profile[k] for k in ADDRESS_FIELDS), timestamp, timestamp))
                    except sqlite3.IntegrityError:
                        raise ValueError("Já existe um perfil com este e-mail.")
                else:
                    email = str(data.get("email", "")).strip().lower()
                    password = str(data.get("password", ""))
                    row = db.execute("SELECT * FROM users WHERE email = ? COLLATE NOCASE", (email,)).fetchone()
                    if not row or not verify_password(password, row["password_hash"]):
                        self.send_json(401, {"error": "E-mail ou senha incorretos."})
                        return
                    user_id = row["id"]
                token = self.issue_session(db, user_id)
                user = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
            self.send_json(200, {"user": serialize_user(user)}, {"Set-Cookie": self.session_cookie(token)})
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            self.send_json(400, {"error": str(exc)})
        except Exception:
            self.send_json(500, {"error": "Não foi possível salvar o perfil."})

    def do_PATCH(self) -> None:
        path = urlparse(self.path).path
        product_match = re.fullmatch(r"/api/admin/products/(\d+)", path)
        if product_match:
            if not self.admin_allowed():
                self.send_json(401, {"error": "Acesso administrativo necessário."})
                return
            self.handle_product_patch(int(product_match.group(1)))
            return
        if path == "/api/auth/profile":
            try:
                data = self.read_json()
                init_db()
                with connect() as db:
                    user = self.current_user(db)
                    if user is None:
                        self.send_json(401, {"error": "Entre no seu perfil para continuar."})
                        return
                    payload = {key: data.get(key, user[key]) for key in ("name", "whatsapp", *ADDRESS_FIELDS)}
                    profile = normalize_profile(payload)
                    db.execute("UPDATE users SET name=?,whatsapp=?,cep=?,street=?,number=?,complement=?,neighborhood=?,city=?,state=?,updated_at=? WHERE id=?",
                        (profile["name"], profile["whatsapp"], *(profile[k] for k in ADDRESS_FIELDS), now_utc(), user["id"]))
                    updated = db.execute("SELECT * FROM users WHERE id=?", (user["id"],)).fetchone()
                self.send_json(200, {"user": serialize_user(updated)})
            except (ValueError, TypeError, json.JSONDecodeError) as exc:
                self.send_json(400, {"error": str(exc)})
            except Exception:
                self.send_json(500, {"error": "Não foi possível atualizar o perfil."})
            return
        match = re.fullmatch(r"/api/orders/([A-Fa-f0-9]+)/status", path)
        if not match:
            self.send_json(404, {"error": "Rota não encontrada."})
            return
        if not self.admin_allowed():
            self.send_json(401, {"error": "Acesso administrativo necessário."})
            return
        try:
            status = str(self.read_json().get("status", ""))
            if status not in STATUSES:
                raise ValueError("Status de pedido inválido.")
            order_id, timestamp = match.group(1), now_utc()
            with connect() as db:
                previous = db.execute("SELECT status FROM orders WHERE id = ?", (order_id,)).fetchone()
                if previous is None:
                    self.send_json(404, {"error": "Pedido não encontrado."})
                    return
                db.execute("UPDATE orders SET status = ?, updated_at = ? WHERE id = ?", (status, timestamp, order_id))
                db.execute("INSERT INTO order_history(order_id, occurred_at, event_type, description, details_json) VALUES (?, ?, ?, ?, ?)",
                    (order_id, timestamp, "status_changed", f"Status alterado de {previous['status']} para {status}.", json.dumps({"from": previous["status"], "to": status})))
                result = order_detail(db, order_id)
            self.send_json(200, result)
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            self.send_json(400, {"error": str(exc)})
        except Exception:
            self.send_json(500, {"error": "Não foi possível atualizar o pedido."})

    def log_message(self, format: str, *args) -> None:
        print(f"{self.client_address[0]} - {format % args}")


class VercelRequest(LumiHandler):
    """Adapt the existing HTTP handlers to the WSGI interface used by Vercel."""

    def send_response(self, code: int, message: str | None = None) -> None:
        self._status = code

    def send_header(self, keyword: str, value: str) -> None:
        self._response_headers.append((keyword, value))

    def end_headers(self) -> None:
        return

    def send_error(self, code: int, message: str | None = None, explain: str | None = None) -> None:
        self._status = code
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.wfile.write((message or "Not found").encode("utf-8"))


def HTTPStatusPhrase(code: int) -> str:
    return {200: "OK", 201: "Created", 204: "No Content", 400: "Bad Request", 401: "Unauthorized",
            403: "Forbidden", 404: "Not Found", 405: "Method Not Allowed", 409: "Conflict", 413: "Payload Too Large",
            422: "Unprocessable Entity", 429: "Too Many Requests", 500: "Internal Server Error", 502: "Bad Gateway"}.get(code, "Response")


def vercel_app(environ, start_response):
    """Serve the Lumi frontend and dispatch its API through the existing handlers."""
    path = unquote(urlparse(environ.get("PATH_INFO", "/")).path)
    if path.startswith("/api/"):
        request = object.__new__(VercelRequest)
        request.path = path + (("?" + environ["QUERY_STRING"]) if environ.get("QUERY_STRING") else "")
        request.command = environ.get("REQUEST_METHOD", "GET").upper()
        request.headers = {}
        for key, value in environ.items():
            if key.startswith("HTTP_"):
                request.headers[key[5:].replace("_", "-").title()] = value
        if "CONTENT_TYPE" in environ:
            request.headers["Content-Type"] = environ["CONTENT_TYPE"]
        request.headers["Content-Length"] = environ.get("CONTENT_LENGTH", "0")
        request.rfile = environ.get("wsgi.input", io.BytesIO())
        request.wfile = io.BytesIO()
        request._status = 500
        request._response_headers = []
        request.client_address = (environ.get("REMOTE_ADDR", "127.0.0.1"), 0)
        request.server = None
        request.directory = str(ROOT)
        try:
            if request.command == "GET":
                request.do_GET()
            elif request.command == "POST":
                request.do_POST()
            elif request.command == "PATCH":
                request.do_PATCH()
            else:
                request._status = 405
                request.send_header("Allow", "GET, POST, PATCH")
                request.wfile.write(b"Method not allowed")
        except Exception as exc:
            # Keep API failures in JSON so clients can display a useful route/status
            # instead of Vercel's generic text/plain 500 page.
            print(f"Vercel API handler failed for {path}: {type(exc).__name__}")
            request._status = 500
            request._response_headers = []
            request.wfile = io.BytesIO()
            request.send_json(500, {"error": f"Falha ao processar a requisição ({type(exc).__name__})."})
        body = request.wfile.getvalue()
        headers = request._response_headers
        if not any(name.lower() == "content-length" for name, _ in headers):
            headers.append(("Content-Length", str(len(body))))
        start_response(f"{request._status} {HTTPStatusPhrase(request._status)}", headers)
        return [body]

    relative = "index.html" if path == "/" else ("admin.html" if path in ("/admin", "/admin/") else path.lstrip("/"))
    target = (ROOT / relative).resolve()
    public_extensions = {".html", ".css", ".js", ".jpeg", ".jpg", ".png", ".webp", ".svg", ".ico", ".woff", ".woff2"}
    if (ROOT not in target.parents or not target.is_file() or target.suffix.lower() not in public_extensions
            or any(part.startswith(".") for part in Path(relative).parts)):
        body, status, content_type = b"Not found", "404 Not Found", "text/plain; charset=utf-8"
    else:
        body = target.read_bytes()
        status = "200 OK"
        content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        if content_type.startswith("text/") or content_type in ("application/javascript", "application/json"):
            content_type += "; charset=utf-8"
    start_response(status, [("Content-Type", content_type), ("Content-Length", str(len(body)))])
    return [body]


app = vercel_app


if __name__ == "__main__":
    init_db()
    if "--init-db" in sys.argv:
        print(f"Banco SQLite pronto: {DB_PATH}")
    else:
        print(f"Lumi rodando em http://localhost:{PORT}")
        print("Configure LUMI_ADMIN_EMAIL e LUMI_ADMIN_PASSWORD para liberar o painel.")
        ThreadingHTTPServer(("0.0.0.0", PORT), LumiHandler).serve_forever()

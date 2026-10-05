import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

import server


class DatabaseBootstrapTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temp_dir.name) / "legacy.sqlite3"
        self.db_path_patch = patch.object(server, "DB_PATH", self.database_path)
        self.db_path_patch.start()
        self.initialized_patch = patch.object(server, "_DB_INITIALIZED", False)
        self.initialized_patch.start()
        self.environment_patch = patch.dict(os.environ, {}, clear=True)
        self.environment_patch.start()

    def tearDown(self):
        self.environment_patch.stop()
        self.initialized_patch.stop()
        self.db_path_patch.stop()
        self.temp_dir.cleanup()

    def test_runtime_refuses_vercel_without_ready_marker(self):
        with patch.dict(os.environ, {"VERCEL": "1"}), patch.object(server, "_initialize_db") as initialize:
            with self.assertRaisesRegex(RuntimeError, "LUMI_DB_SCHEMA_READY=1"):
                server.init_db()

        initialize.assert_not_called()

    def test_runtime_skips_ddl_when_vercel_schema_is_ready(self):
        with patch.dict(os.environ, {"VERCEL": "1", "LUMI_DB_SCHEMA_READY": "1"}), patch.object(server, "_initialize_db") as initialize:
            server.init_db()

        initialize.assert_not_called()

    def test_local_initialization_runs_once_per_process(self):
        with patch.object(server, "_initialize_db") as initialize:
            server.init_db()
            server.init_db()

        initialize.assert_called_once_with()

    def test_schema_migration_adds_legacy_columns_and_seeds_products(self):
        with closing(sqlite3.connect(self.database_path)) as db:
            db.execute(
                "CREATE TABLE orders (id TEXT PRIMARY KEY, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, "
                "customer_name TEXT NOT NULL, whatsapp TEXT NOT NULL, status TEXT NOT NULL, total_cents INTEGER NOT NULL)"
            )
            db.execute(
                "CREATE TABLE feedbacks (id INTEGER PRIMARY KEY, user_id TEXT NOT NULL, customer_name TEXT NOT NULL, "
                "message TEXT NOT NULL, created_at TEXT NOT NULL)"
            )

        server._initialize_db()

        with closing(sqlite3.connect(self.database_path)) as db:
            order_columns = {row[1] for row in db.execute("PRAGMA table_info(orders)")}
            feedback_columns = {row[1] for row in db.execute("PRAGMA table_info(feedbacks)")}
            product_count = db.execute("SELECT COUNT(*) FROM products").fetchone()[0]

        self.assertTrue(
            {
                "user_id", "delivery_address", "payment_status", "payment_method", "payment_url",
                "payment_invoice_slug", "payment_transaction_nsu", "payment_receipt_url",
            }.issubset(order_columns)
        )
        self.assertIn("rating", feedback_columns)
        self.assertEqual(product_count, len(server.PRODUCTS))

    def test_migration_command_requires_remote_database_url(self):
        with self.assertRaisesRegex(RuntimeError, "TURSO_DATABASE_URL"):
            server.migrate_db()

    def test_migration_command_requires_remote_auth_token(self):
        with patch.dict(os.environ, {"TURSO_DATABASE_URL": "libsql://example.turso.io"}):
            with self.assertRaisesRegex(RuntimeError, "TURSO_AUTH_TOKEN"):
                server.migrate_db()

    def test_order_detail_tolerates_invalid_legacy_json_metadata(self):
        db = sqlite3.connect(":memory:")
        db.row_factory = sqlite3.Row
        db.executescript(
            "CREATE TABLE orders (id TEXT PRIMARY KEY, delivery_address TEXT);"
            "CREATE TABLE order_items (id INTEGER PRIMARY KEY, order_id TEXT, product_id INTEGER, "
            "product_name TEXT, model TEXT, unit_price_cents INTEGER, quantity INTEGER);"
            "CREATE TABLE order_history (id INTEGER PRIMARY KEY, order_id TEXT, occurred_at TEXT, "
            "event_type TEXT, description TEXT, details_json TEXT);"
        )
        db.execute("INSERT INTO orders VALUES (?, ?)", ("test-order", "not-json"))
        db.execute(
            "INSERT INTO order_history(order_id, occurred_at, event_type, description, details_json) "
            "VALUES (?, ?, ?, ?, ?)",
            ("test-order", "2026-01-01T00:00:00Z", "created", "Pedido criado", None),
        )

        result = server.order_detail(db, "test-order")

        self.assertEqual(result["delivery_address"], {})
        self.assertEqual(result["history"][0]["details"], {})
        db.close()


if __name__ == "__main__":
    unittest.main()

import os
import tempfile
import sqlite3
import sys

# Ensure engine is importable
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from engine.configurator import patch_config, rollback_config, migrate_existing_threads

def test_patch_and_rollback():
    # Create temporary config file representing ~/.codex/config.toml
    with tempfile.NamedTemporaryFile(delete=False, suffix=".toml") as tmp:
        tmp.write(b'model_provider = "openai"\n\n[model_providers.openai]\nname = "OpenAI"\n')
        tmp_path = tmp.name

    # Create dummy database for migration test
    tmpdir = os.path.dirname(tmp_path)
    db_path = os.path.join(tmpdir, "state_5.sqlite")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE threads (
            id TEXT PRIMARY KEY,
            model_provider TEXT NOT NULL
        )
    """)
    cursor.executemany(
        "INSERT INTO threads VALUES (?, ?)",
        [("t1", "openai"), ("t2", "codex-gateway")]
    )
    conn.commit()
    conn.close()

    try:
        # 1. Patch the configuration
        patch_config(tmp_path, "http://127.0.0.1:8000/v1", "/tmp/catalog.json")
        
        with open(tmp_path, "r") as f:
            content = f.read()
        
        # Gateway uses its own custom provider to enable model_catalog_json
        assert 'model_provider = "codex-gateway"' in content
        assert "[model_providers.codex-gateway]" in content
        assert 'base_url = "http://127.0.0.1:8000/v1"' in content
        assert 'model_catalog_json = "/tmp/catalog.json"' in content
        assert "[profiles.codex-gateway]" in content

        # DB should have migrated openai -> codex-gateway
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT id, model_provider FROM threads ORDER BY id")
        results = cursor.fetchall()
        conn.close()
        # Note: both t1 (migrated) and t2 (already codex-gateway) should be codex-gateway
        assert results == [("t1", "codex-gateway"), ("t2", "codex-gateway")]

        # 2. Rollback the configuration
        rollback_config(tmp_path)
        
        with open(tmp_path, "r") as f:
            content = f.read()
        
        assert 'model_provider = "openai"' in content
        assert "CODEX-GATEWAY" not in content

        # DB should have rolled back codex-gateway -> openai
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT id, model_provider FROM threads ORDER BY id")
        results = cursor.fetchall()
        conn.close()
        assert results == [("t1", "openai"), ("t2", "openai")]

    finally:
        # Cleanup
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        if os.path.exists(db_path):
            os.unlink(db_path)
        backup_path = tmp_path + ".codex_default_backup"
        if os.path.exists(backup_path):
            os.unlink(backup_path)

def test_migrate_existing_threads():
    """Verify the dynamic toggle of threads provider."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "state_5.sqlite")
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # Create a minimal threads table matching Codex schema
        cursor.execute("""
            CREATE TABLE threads (
                id TEXT PRIMARY KEY,
                model_provider TEXT NOT NULL
            )
        """)

        # Insert test threads
        cursor.executemany(
            "INSERT INTO threads VALUES (?, ?)",
            [
                ("t1", "codex-gateway"),
                ("t2", "openai"),
            ]
        )
        conn.commit()
        conn.close()

        # Run migration from openai to codex-gateway (startup)
        migrate_existing_threads(tmpdir, "openai", "codex-gateway")

        # Verify all threads now have model_provider = 'codex-gateway'
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT id, model_provider FROM threads ORDER BY id")
        results = cursor.fetchall()
        conn.close()

        assert results == [
            ("t1", "codex-gateway"),
            ("t2", "codex-gateway"),
        ]

        # Run migration from codex-gateway to openai (shutdown)
        migrate_existing_threads(tmpdir, "codex-gateway", "openai")

        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT id, model_provider FROM threads ORDER BY id")
        results = cursor.fetchall()
        conn.close()

        assert results == [
            ("t1", "openai"),
            ("t2", "openai"),
        ]

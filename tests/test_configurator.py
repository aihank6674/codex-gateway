import os
import tempfile
import sys

# Ensure engine is importable
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from engine.configurator import patch_config, rollback_config

def test_patch_and_rollback():
    # Create temporary config file representing ~/.codex/config.toml
    with tempfile.NamedTemporaryFile(delete=False, suffix=".toml") as tmp:
        tmp.write(b"model_provider = \"openai\"\n\n[model_providers.openai]\nname = \"OpenAI\"\n")
        tmp_path = tmp.name

    try:
        # 1. Patch the configuration
        patch_config(tmp_path, "http://127.0.0.1:8000/v1", "/tmp/catalog.json")
        
        with open(tmp_path, "r") as f:
            content = f.read()
        
        assert "model_provider = \"codex-gateway\"" in content
        assert "[model_providers.codex-gateway]" in content
        assert "base_url = \"http://127.0.0.1:8000/v1\"" in content
        assert "model_catalog_json = \"/tmp/catalog.json\"" in content
        assert "[profiles.codex-gateway]" in content

        # 2. Rollback the configuration
        rollback_config(tmp_path)
        
        with open(tmp_path, "r") as f:
            content = f.read()
        
        assert "model_provider = \"openai\"" in content
        assert "codex-gateway" not in content
    finally:
        # Cleanup
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        backup_path = tmp_path + ".codex_default_backup"
        if os.path.exists(backup_path):
            os.unlink(backup_path)

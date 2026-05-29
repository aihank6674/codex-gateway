import os
import sys
import shutil
import re
import sqlite3
import glob

def patch_config(config_path: str, gateway_url: str, catalog_path: str):
    """
    Safely injects the codex-gateway model provider and profile into the config.toml file.
    Backs up the file beforehand to enable clean rollbacks.
    """
    expanded_path = os.path.expanduser(config_path)
    backup_path = expanded_path + ".codex_default_backup"

    # Ensure target directory exists
    dir_name = os.path.dirname(expanded_path)
    if dir_name:
        os.makedirs(dir_name, exist_ok=True)

    # 1. Back up the original file if not already done
    if not os.path.exists(backup_path):
        if os.path.exists(expanded_path):
            shutil.copy2(expanded_path, backup_path)
            print(f"[configurator] Backed up original config to {backup_path}")
        else:
            # If no config.toml exists, backup is empty
            with open(backup_path, "w", encoding="utf-8") as f:
                f.write("")
            print(f"[configurator] Created empty original config backup at {backup_path}")

    # Read current content
    content = ""
    if os.path.exists(expanded_path):
        with open(expanded_path, "r", encoding="utf-8") as f:
            content = f.read()

    # 2. Strip previous codex-gateway injections (for idempotency)
    content = re.sub(
        r"\n*# === START CODEX-GATEWAY ===.*# === END CODEX-GATEWAY ===\n*",
        "",
        content,
        flags=re.DOTALL
    )

    # 3. Update the global default model_provider safely to "codex-gateway"
    if "model_provider =" in content:
        content = re.sub(
            r'^(model_provider\s*=\s*)"[^"]+"',
            r'\1"codex-gateway"',
            content,
            count=1,
            flags=re.MULTILINE
        )
    else:
        content = 'model_provider = "codex-gateway"\n' + content

    # 4. Append the new custom provider block so Codex reads model_catalog_json
    patch_data = f"""
# === START CODEX-GATEWAY ===
[model_providers.codex-gateway]
name = "Codex Gateway"
base_url = "{gateway_url}"
wire_api = "responses"
model_catalog_json = "{catalog_path}"

[profiles.codex-gateway]
model_provider = "codex-gateway"
model = "deepseek/deepseek-v4-pro"
# === END CODEX-GATEWAY ===
"""
    
    new_content = content.strip() + "\n" + patch_data

    with open(expanded_path, "w", encoding="utf-8") as f:
        f.write(new_content)
    print(f"[configurator] Successfully patched config at {expanded_path}")

    # 5. Migrate chat history to the gateway identity so they are visible
    codex_home = os.path.dirname(expanded_path)
    migrate_existing_threads(codex_home, "openai", "codex-gateway")

def rollback_config(config_path: str):
    """
    Restores ~/.codex/config.toml to its original backup state and deletes the backup.
    """
    expanded_path = os.path.expanduser(config_path)
    backup_path = expanded_path + ".codex_default_backup"

    if os.path.exists(backup_path):
        shutil.copy2(backup_path, expanded_path)
        os.unlink(backup_path)
        print(f"[configurator] Successfully rolled back config to {expanded_path}")
    else:
        print(f"[configurator] Warning: No backup found at {backup_path} to restore.")

    # Rollback chat history to the official identity so they are visible in official app
    codex_home = os.path.dirname(expanded_path)
    migrate_existing_threads(codex_home, "codex-gateway", "openai")

def migrate_existing_threads(codex_home: str, from_provider: str, to_provider: str):
    """
    Dynamically toggles chat thread model_provider in state_*.sqlite databases
    and their corresponding rollout JSONL session files so that chat history
    remains visible and loadable when switching between Gateway and Official modes.
    """
    db_pattern = os.path.join(codex_home, "state_*.sqlite")
    db_files = glob.glob(db_pattern)

    if not db_files:
        return

    for db_path in db_files:
        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()

            # 1. Update the SQLite threads table
            cursor.execute(
                "SELECT COUNT(*) FROM threads WHERE model_provider = ?", (from_provider,)
            )
            count = cursor.fetchone()[0]

            if count > 0:
                cursor.execute(
                    "UPDATE threads SET model_provider = ? WHERE model_provider = ?",
                    (to_provider, from_provider)
                )
                conn.commit()
                print(f"[configurator] Migrated {count} chat thread(s) in database from '{from_provider}' to '{to_provider}' in {os.path.basename(db_path)}")

            # 2. Update the corresponding rollout JSONL files to align session metadata
            cursor.execute("SELECT id, rollout_path FROM threads")
            rows = cursor.fetchall()
            conn.close()

            for thread_id, rollout_path in rows:
                if rollout_path and os.path.exists(rollout_path):
                    try:
                        with open(rollout_path, "r", encoding="utf-8") as f:
                            file_content = f.read()

                        # Spacing-insensitive regex to capture "model_provider":"provider"
                        pattern = rf'"model_provider"\s*:\s*"{from_provider}"'
                        replacement = f'"model_provider":"{to_provider}"'

                        new_content, sub_count = re.subn(pattern, replacement, file_content)
                        if sub_count > 0:
                            with open(rollout_path, "w", encoding="utf-8") as f:
                                f.write(new_content)
                            print(f"[configurator] Migrated rollout file for thread {thread_id}: replaced {sub_count} occurrence(s) of '{from_provider}' with '{to_provider}'")
                    except Exception as fe:
                        print(f"[configurator] Warning: Failed to migrate rollout file {rollout_path}: {fe}")

        except Exception as e:
            print(f"[configurator] Warning: Could not migrate threads in {os.path.basename(db_path)}: {e}")

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python configurator.py --patch <config_path> <gateway_url> <catalog_path>")
        print("       python configurator.py --rollback <config_path>")
        sys.exit(1)

    command = sys.argv[1]
    target_path = sys.argv[2]

    if command == "--patch":
        if len(sys.argv) < 5:
            print("Error: --patch requires <gateway_url> and <catalog_path>")
            sys.exit(1)
        patch_config(target_path, sys.argv[3], sys.argv[4])
    elif command == "--rollback":
        rollback_config(target_path)
    else:
        print(f"Unknown command: {command}")
        sys.exit(1)

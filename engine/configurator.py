import os
import sys
import shutil
import re

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
            r"model_provider\s*=\s*\"[^\"]+\"",
            "model_provider = \"codex-gateway\"",
            content
        )
    else:
        content = "model_provider = \"codex-gateway\"\n" + content

    # 4. Append the new custom provider and profile blocks
    patch_data = f"""
# === START CODEX-GATEWAY ===
[model_providers.codex-gateway]
name = "Codex Gateway"
base_url = "{gateway_url}"
wire_api = "responses"
model_catalog_json = "{catalog_path}"

[profiles.codex-gateway]
model_provider = "codex-gateway"
# === END CODEX-GATEWAY ===
"""
    
    new_content = content.strip() + "\n" + patch_data

    with open(expanded_path, "w", encoding="utf-8") as f:
        f.write(new_content)
    print(f"[configurator] Successfully patched config at {expanded_path}")

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

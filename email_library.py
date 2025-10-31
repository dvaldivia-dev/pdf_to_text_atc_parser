from pathlib import Path
import json

# ---------- DEFAULTS ----------
DEFAULT_CONFIG = {
    "imap_host": "imap.gmail.com",
    "imap_port": 993,
    "username": "tu@correo.com",
    "password": "",
    "mailbox": "INBOX",
    "download_folder": str(Path.home() / "Downloads"),
    "date_start": "2025-10-01",
    "date_end": None,
    "mark_as_seen": True,
    "history_file": "processed_emails.json"
}
# --------------------------------

def load_config(path=None):
    """
    Carga configuración desde config.json (si existe). 
    path: ruta opcional al archivo JSON. Si no se pasa, busca ./config.json
    """
    cfg = DEFAULT_CONFIG.copy()
    config_path = Path(path) if path else Path("config.json")
    if config_path.exists():
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                user_cfg = json.load(f)
            # actualizar defaults con lo que venga en el archivo
            cfg.update(user_cfg)
        except Exception as e:
            print(f"Advertencia: no se pudo leer {config_path}: {e}")
    else:
        print(f"Info: no se encontró {config_path}, usando valores por defecto.")
    return cfg
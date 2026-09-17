#!/usr/bin/env python3
"""
Configuration and preferences persistence for RavenScan.
Stores user settings in ~/.config/ravenscan/config.json.
Auto-detects Google Drive (rclone) mounts, heals dead sockets, and discovers all Google Drive folders.
"""

import os
import json
import time
import errno
import subprocess
from typing import Dict, Any, List, Tuple

CONFIG_DIR = os.path.expanduser("~/.config/ravenscan")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")

GDRIVE_DIR = os.path.expanduser("~/gdrive")
GDRIVE_RAVEN_DIR = os.path.expanduser("~/gdrive/Raven Scans")
LOCAL_SCAN_DIR = os.path.expanduser("~/Documents/Scans")


def heal_mount_if_needed(path: str = None):
    """Detects if the FUSE rclone mount at ~/gdrive has a dead socket and restarts it."""
    need_heal = False
    try:
        os.listdir(GDRIVE_DIR)
    except OSError as e:
        if e.errno == errno.ENOTCONN or "not connected" in str(e).lower():
            need_heal = True
    except Exception:
        pass

    if need_heal:
        print(f"[Config] Detected dead rclone mount at {GDRIVE_DIR}. Healing service...")
        try:
            subprocess.run(["fusermount3", "-uz", GDRIVE_DIR], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            subprocess.run(["systemctl", "--user", "restart", "rclone-gdrive.service"], check=False)
            # Wait up to 3 seconds for mount to come back
            for _ in range(6):
                time.sleep(0.5)
                try:
                    os.listdir(GDRIVE_DIR)
                    print("[Config] rclone mount healed successfully!")
                    break
                except Exception:
                    pass
        except Exception as ex:
            print(f"[Config] Error restarting rclone: {ex}")


def get_initial_default_dir() -> str:
    """Returns Raven Scans on Google Drive if available, otherwise local Documents/Scans."""
    heal_mount_if_needed(GDRIVE_DIR)
    try:
        if os.path.isdir(GDRIVE_DIR):
            os.makedirs(GDRIVE_RAVEN_DIR, exist_ok=True)
            return GDRIVE_RAVEN_DIR
    except Exception:
        pass
    os.makedirs(LOCAL_SCAN_DIR, exist_ok=True)
    return LOCAL_SCAN_DIR


DEFAULT_CONFIG: Dict[str, Any] = {
    "save_dir": get_initial_default_dir(),
    "custom_dirs": [],
    "doc_name": "Scan",
    "append_date": True,
    "color_mode_idx": 0,    # 0 = Color
    "resolution_idx": 2,    # 2 = 300 DPI
    "source_idx": 0,        # 0 = Duplex
    "paper_size_idx": 1,    # 1 = US Letter
    "auto_deskew": True,
    "ocr": True,
}


class ConfigManager:
    @classmethod
    def load(cls) -> Dict[str, Any]:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        if not os.path.exists(CONFIG_FILE):
            cfg = DEFAULT_CONFIG.copy()
            cfg["save_dir"] = get_initial_default_dir()
            cls.save(cfg)
            return cfg

        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                config = DEFAULT_CONFIG.copy()
                config.update(data)
                return config
        except Exception as e:
            print(f"[Config] Error reading {CONFIG_FILE}: {e}")
            return DEFAULT_CONFIG.copy()

    @classmethod
    def save(cls, data: Dict[str, Any]):
        os.makedirs(CONFIG_DIR, exist_ok=True)
        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            print(f"[Config] Error saving {CONFIG_FILE}: {e}")

    @classmethod
    def get_save_dir(cls) -> str:
        cfg = cls.load()
        path = cfg.get("save_dir", get_initial_default_dir())
        cls.heal_mount_if_needed(path)
        try:
            os.makedirs(path, exist_ok=True)
        except Exception:
            pass
        return path

    @classmethod
    def set_save_dir(cls, path: str):
        cfg = cls.load()
        resolved = os.path.abspath(os.path.expanduser(path))
        cfg["save_dir"] = resolved

        # Track in custom_dirs if not already present
        custom_dirs = cfg.get("custom_dirs", [])
        if resolved not in custom_dirs and resolved != GDRIVE_RAVEN_DIR and resolved != LOCAL_SCAN_DIR:
            custom_dirs.append(resolved)
            cfg["custom_dirs"] = custom_dirs[-20:]  # Keep last 20

        cls.save(cfg)

    @classmethod
    def heal_mount_if_needed(cls, path: str = None):
        """Detects if the FUSE rclone mount at ~/gdrive has a dead socket and restarts it."""
        heal_mount_if_needed(path)

    @classmethod
    def format_display_path(cls, path: str) -> str:
        """Formats a path into a user-friendly label (e.g. ☁️ Google Drive / Raven Scans)."""
        if not path:
            return ""
        norm = os.path.abspath(os.path.expanduser(path))
        if norm.startswith(GDRIVE_DIR):
            rel = os.path.relpath(norm, GDRIVE_DIR)
            if rel == ".":
                return "☁️ Google Drive (Root)"
            return f"☁️ Google Drive / {rel}"
        home = os.path.expanduser("~")
        if norm.startswith(home):
            return f"📁 ~{norm[len(home):]}"
        return f"📁 {norm}"

    @classmethod
    def get_available_destinations(cls) -> List[Dict[str, Any]]:
        """
        Returns an ordered list of destinations for the UI dropdown.
        Priority:
        1. ☁️ Raven Scans (Google Drive) - Default
        2. Any subfolders inside Raven Scans (e.g. Raven Scans / Invoices)
        3. All other Google Drive folders in alphabetical order
        4. Any custom folders selected by user
        5. 📁 Local: Documents / Scans
        6. 🔍 Browse Other Folder...
        """
        cls.heal_mount_if_needed(GDRIVE_DIR)
        dests: List[Dict[str, Any]] = []

        gdrive_online = False
        try:
            if os.path.isdir(GDRIVE_DIR):
                os.listdir(GDRIVE_DIR)
                gdrive_online = True
        except Exception:
            pass

        if gdrive_online:
            try:
                os.makedirs(GDRIVE_RAVEN_DIR, exist_ok=True)
            except Exception:
                pass

            # 1. Primary Raven Scans folder
            dests.append({
                "label": "☁️ Raven Scans (Google Drive)",
                "path": GDRIVE_RAVEN_DIR,
                "is_gdrive": True,
                "is_default": True
            })

            # 2. Subfolders inside Raven Scans
            try:
                if os.path.isdir(GDRIVE_RAVEN_DIR):
                    for sub in sorted(os.listdir(GDRIVE_RAVEN_DIR)):
                        sub_path = os.path.join(GDRIVE_RAVEN_DIR, sub)
                        if os.path.isdir(sub_path):
                            dests.append({
                                "label": f"☁️ Raven Scans / {sub}",
                                "path": sub_path,
                                "is_gdrive": True
                            })
            except Exception:
                pass

            # 3. All other Google Drive top-level folders
            other_gdrive: List[Tuple[str, str]] = []
            try:
                for item in os.listdir(GDRIVE_DIR):
                    item_path = os.path.join(GDRIVE_DIR, item)
                    if os.path.isdir(item_path) and item.lower() != "raven scans":
                        other_gdrive.append((item, item_path))
            except Exception:
                pass

            other_gdrive.sort(key=lambda x: x[0].lower())
            for name, path in other_gdrive:
                dests.append({
                    "label": f"☁️ {name}",
                    "path": path,
                    "is_gdrive": True
                })

        # 4. Custom folders previously used
        cfg = cls.load()
        existing_paths = {d["path"] for d in dests}
        for custom_path in cfg.get("custom_dirs", []):
            if custom_path not in existing_paths and os.path.isdir(custom_path):
                disp = cls.format_display_path(custom_path)
                dests.append({
                    "label": disp,
                    "path": custom_path,
                    "is_gdrive": custom_path.startswith(GDRIVE_DIR)
                })
                existing_paths.add(custom_path)

        # 5. Local Scans folder
        try:
            os.makedirs(LOCAL_SCAN_DIR, exist_ok=True)
        except Exception:
            pass
        dests.append({
            "label": "📁 Documents / Scans (Local)",
            "path": LOCAL_SCAN_DIR,
            "is_gdrive": False
        })

        # 6. Special browse item
        dests.append({
            "label": "🔍 Browse Other Folder...",
            "path": "__BROWSE__",
            "is_special": True
        })

        return dests

    @classmethod
    def create_new_folder(cls, folder_name: str, parent_dir: str = None) -> str:
        """Creates a new directory inside parent_dir (or current save_dir/gdrive) and returns path."""
        cls.heal_mount_if_needed(GDRIVE_DIR)
        name = folder_name.strip()
        if not name:
            raise ValueError("Folder name cannot be empty")

        if not parent_dir or not os.path.isdir(parent_dir):
            parent_dir = cls.get_save_dir()
            if not os.path.isdir(parent_dir):
                parent_dir = GDRIVE_RAVEN_DIR if os.path.isdir(GDRIVE_DIR) else LOCAL_SCAN_DIR

        new_path = os.path.join(parent_dir, name)
        os.makedirs(new_path, exist_ok=True)

        # Update config
        cls.set_save_dir(new_path)
        return new_path

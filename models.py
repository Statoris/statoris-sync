"""
models.py - Data models and persistence for Statoris Sync.
Handles SyncJobs, Multi-Directory FolderPairs, EndpointConfigs (Local, SSH/SFTP, SCP, FTP/FTPS),
Application Settings, and Sync State Manifests (for Full, Incremental, Differential & Bidirectional sync).
"""

import os
import sys
import json
import uuid
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Optional


def get_app_data_dir() -> str:
    """Returns persistent data directory next to executable or script."""
    if getattr(sys, "frozen", False):
        base = os.path.dirname(sys.executable)
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    return base


@dataclass
class EndpointConfig:
    protocol: str = "local"  # "local", "ssh", "scp", "ftp", "ftps"
    path: str = ""
    host: str = ""
    port: int = 22
    username: str = ""
    password: str = ""
    key_file: str = ""
    key_passphrase: str = ""
    passive_ftp: bool = True

    def display_uri(self) -> str:
        proto = (self.protocol or "local").lower()
        if proto == "local":
            return self.path or "(Sin seleccionar)"
        default_port = 21 if proto in ("ftp", "ftps") else 22
        port_val = self.port or default_port
        user_prefix = f"{self.username}@" if self.username else ""
        host_part = f"{self.host}:{port_val}" if port_val != default_port else self.host
        norm_path = (self.path or "/").replace("\\", "/")
        if not norm_path.startswith("/"):
            norm_path = "/" + norm_path
        return f"{proto.upper()}://{user_prefix}{host_part}{norm_path}"

    @classmethod
    def from_dict(cls, data: dict) -> "EndpointConfig":
        if not isinstance(data, dict):
            return cls()
        return cls(
            protocol=data.get("protocol", "local"),
            path=data.get("path", ""),
            host=data.get("host", ""),
            port=int(data.get("port", 22) or 22),
            username=data.get("username", ""),
            password=data.get("password", ""),
            key_file=data.get("key_file", ""),
            key_passphrase=data.get("key_passphrase", ""),
            passive_ftp=bool(data.get("passive_ftp", True)),
        )


@dataclass
class FolderPair:
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    name: str = "Par 1"
    enabled: bool = True
    left: EndpointConfig = field(default_factory=EndpointConfig)
    right: EndpointConfig = field(default_factory=EndpointConfig)

    @classmethod
    def from_dict(cls, data: dict) -> "FolderPair":
        if not isinstance(data, dict):
            return cls()
        return cls(
            id=data.get("id", str(uuid.uuid4())[:8]),
            name=data.get("name", "Par de Directorios"),
            enabled=bool(data.get("enabled", True)),
            left=EndpointConfig.from_dict(data.get("left", {})),
            right=EndpointConfig.from_dict(data.get("right", {})),
        )


@dataclass
class SyncJob:
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    name: str = "Sincronización Principal"
    enabled: bool = True
    pairs: List[FolderPair] = field(default_factory=list)
    direction: str = "bidirectional"  # "bidirectional", "left_to_right", "right_to_left"
    sync_mode: str = "incremental"    # "full", "incremental", "differential"
    delete_orphans: bool = True
    conflict_policy: str = "newer"    # "newer", "both", "left", "right"
    exclude_patterns: str = "*.tmp; *.temp; thumbs.db; desktop.ini; $RECYCLE.BIN; .statoris_sync*"
    realtime_enabled: bool = False
    realtime_debounce_sec: int = 3
    remote_poll_sec: int = 0
    schedule_enabled: bool = False
    schedule_type: str = "interval"   # "interval", "daily", "weekly", "on_startup"
    schedule_interval_min: int = 30
    schedule_time: str = "02:00"
    schedule_days: List[str] = field(default_factory=lambda: ["mon", "tue", "wed", "thu", "fri"])
    last_run: str = "Nunca"
    last_status: str = "Pendiente"

    def ensure_default_pairs(self):
        if not self.pairs:
            self.pairs = [
                FolderPair(
                    name="Dir 1 ↔ Dir 1 Remoto",
                    enabled=True,
                    left=EndpointConfig(protocol="local", path=""),
                    right=EndpointConfig(protocol="local", path=""),
                ),
                FolderPair(
                    name="Dir 2 ↔ Dir 2 Remoto",
                    enabled=True,
                    left=EndpointConfig(protocol="local", path=""),
                    right=EndpointConfig(protocol="local", path=""),
                ),
            ]

    @classmethod
    def from_dict(cls, data: dict) -> "SyncJob":
        if not isinstance(data, dict):
            job = cls()
            job.ensure_default_pairs()
            return job
        pairs_raw = data.get("pairs", [])
        pairs = [FolderPair.from_dict(p) for p in pairs_raw]
        job = cls(
            id=data.get("id", str(uuid.uuid4())[:8]),
            name=data.get("name", "Tarea de Sincronización"),
            enabled=bool(data.get("enabled", True)),
            pairs=pairs,
            direction=data.get("direction", "bidirectional"),
            sync_mode=data.get("sync_mode", "incremental"),
            delete_orphans=bool(data.get("delete_orphans", True)),
            conflict_policy=data.get("conflict_policy", "newer"),
            exclude_patterns=data.get(
                "exclude_patterns",
                "*.tmp; *.temp; thumbs.db; desktop.ini; $RECYCLE.BIN; .statoris_sync*",
            ),
            realtime_enabled=bool(data.get("realtime_enabled", False)),
            realtime_debounce_sec=int(data.get("realtime_debounce_sec", 3) or 3),
            remote_poll_sec=int(data.get("remote_poll_sec", 0) or 0),
            schedule_enabled=bool(data.get("schedule_enabled", False)),
            schedule_type=data.get("schedule_type", "interval"),
            schedule_interval_min=int(data.get("schedule_interval_min", 30) or 30),
            schedule_time=data.get("schedule_time", "02:00"),
            schedule_days=list(data.get("schedule_days", ["mon", "tue", "wed", "thu", "fri"])),
            last_run=data.get("last_run", "Nunca"),
            last_status=data.get("last_status", "Pendiente"),
        )
        if not job.pairs:
            job.ensure_default_pairs()
        return job


@dataclass
class AppSettings:
    language: str = "es"
    theme: str = "Light"  # "Light" (Executive Light) or "Dark" (Dark Titanium)
    start_with_windows: bool = False
    start_minimized: bool = False
    close_to_tray: bool = True
    show_notifications: bool = True

    @classmethod
    def from_dict(cls, data: dict) -> "AppSettings":
        if not isinstance(data, dict):
            return cls()
        return cls(
            language=data.get("language", "es"),
            theme=data.get("theme", "Light"),
            start_with_windows=bool(data.get("start_with_windows", False)),
            start_minimized=bool(data.get("start_minimized", False)),
            close_to_tray=bool(data.get("close_to_tray", True)),
            show_notifications=bool(data.get("show_notifications", True)),
        )


class ConfigStore:
    """Manages saving and loading SyncJobs, AppSettings, and Sync State Manifests."""

    def __init__(self, base_dir: Optional[str] = None):
        self.base_dir = base_dir or get_app_data_dir()
        self.jobs_file = os.path.join(self.base_dir, "sync_jobs.json")
        self.settings_file = os.path.join(self.base_dir, "app_settings.json")
        self.state_file = os.path.join(self.base_dir, "sync_state.json")

    def load_settings(self) -> AppSettings:
        if os.path.exists(self.settings_file):
            try:
                with open(self.settings_file, "r", encoding="utf-8") as f:
                    return AppSettings.from_dict(json.load(f))
            except Exception:
                pass
        return AppSettings()

    def save_settings(self, settings: AppSettings):
        try:
            with open(self.settings_file, "w", encoding="utf-8") as f:
                json.dump(asdict(settings), f, indent=2, ensure_ascii=False)
        except Exception:
            pass

    def load_jobs(self) -> List[SyncJob]:
        if os.path.exists(self.jobs_file):
            try:
                with open(self.jobs_file, "r", encoding="utf-8") as f:
                    raw = json.load(f)
                if isinstance(raw, list) and raw:
                    return [SyncJob.from_dict(item) for item in raw]
            except Exception:
                pass
        default_job = SyncJob(
            name="Sincronización Multi-Directorio",
            direction="bidirectional",
            sync_mode="incremental",
        )
        default_job.ensure_default_pairs()
        self.save_jobs([default_job])
        return [default_job]

    def save_jobs(self, jobs: List[SyncJob]):
        try:
            with open(self.jobs_file, "w", encoding="utf-8") as f:
                json.dump([asdict(j) for j in jobs], f, indent=2, ensure_ascii=False)
        except Exception:
            pass

    def load_all_states(self) -> dict:
        if os.path.exists(self.state_file):
            try:
                with open(self.state_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {}

    def get_pair_state(self, job_id: str, pair_id: str) -> dict:
        states = self.load_all_states()
        key = f"{job_id}:{pair_id}"
        return states.get(
            key,
            {
                "last_full_manifest": {},
                "last_sync_manifest": {},
                "last_full_time": None,
                "last_sync_time": None,
            },
        )

    def save_pair_state(
        self,
        job_id: str,
        pair_id: str,
        manifest: Dict[str, dict],
        is_full_sync: bool,
        timestamp_str: str,
    ):
        states = self.load_all_states()
        key = f"{job_id}:{pair_id}"
        entry = states.get(
            key,
            {
                "last_full_manifest": {},
                "last_sync_manifest": {},
                "last_full_time": None,
                "last_sync_time": None,
            },
        )
        # Always update last_sync_manifest for Incremental and Bidirectional tracking
        entry["last_sync_manifest"] = manifest
        entry["last_sync_time"] = timestamp_str
        # Update last_full_manifest on Full sync OR if no Full baseline exists yet
        if is_full_sync or not entry.get("last_full_manifest"):
            entry["last_full_manifest"] = manifest
            entry["last_full_time"] = timestamp_str
        states[key] = entry
        try:
            with open(self.state_file, "w", encoding="utf-8") as f:
                json.dump(states, f, indent=2, ensure_ascii=False)
        except Exception:
            pass

    def reset_job_state(self, job_id: str):
        states = self.load_all_states()
        prefix = f"{job_id}:"
        keys_to_del = [k for k in states.keys() if k.startswith(prefix)]
        for k in keys_to_del:
            del states[k]
        try:
            with open(self.state_file, "w", encoding="utf-8") as f:
                json.dump(states, f, indent=2, ensure_ascii=False)
        except Exception:
            pass

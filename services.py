"""
services.py - Background Services for Statoris Sync:
1. RealtimeSyncService: Watchdog-based instant file change detector with debouncing.
2. SchedulerService: Automated timer & Windows Task Scheduler integration.
3. WindowsStartupManager: Registry HKCU\\...\\Run integration for launching on Windows boot.
4. SystemTrayService: pystray background icon and context menu.
"""

import os
import sys
import time
import winreg
import subprocess
import threading
from datetime import datetime
from typing import List, Dict, Callable, Optional, Set, Tuple

from PIL import Image
import pystray
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

from models import SyncJob
from transports import matches_exclude
from i18n import i18n


REGISTRY_RUN_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
REGISTRY_APP_NAME = "StatorisSync"


class WindowsStartupManager:
    """Manages 'Start with Windows' in HKCU Registry without requiring admin elevation."""

    @staticmethod
    def get_launch_command(minimized: bool = True) -> str:
        if getattr(sys, "frozen", False):
            exe_path = sys.executable
            return f'"{exe_path}" --minimized' if minimized else f'"{exe_path}"'
        else:
            py_exe = sys.executable
            # Prefer pythonw.exe for windowless background launch if available
            pyw_exe = py_exe.replace("python.exe", "pythonw.exe")
            if os.path.exists(pyw_exe):
                py_exe = pyw_exe
            script_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "main_window.py")
            flag = " --minimized" if minimized else ""
            return f'"{py_exe}" "{script_path}"{flag}'

    @staticmethod
    def is_enabled() -> bool:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REGISTRY_RUN_PATH, 0, winreg.KEY_READ) as key:
                val, _ = winreg.QueryValueEx(key, REGISTRY_APP_NAME)
                return bool(val)
        except OSError:
            return False

    @staticmethod
    def set_enabled(enable: bool, start_minimized: bool = True) -> bool:
        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, REGISTRY_RUN_PATH, 0, winreg.KEY_SET_VALUE
            ) as key:
                if enable:
                    cmd = WindowsStartupManager.get_launch_command(minimized=start_minimized)
                    winreg.SetValueEx(key, REGISTRY_APP_NAME, 0, winreg.REG_SZ, cmd)
                else:
                    try:
                        winreg.DeleteValue(key, REGISTRY_APP_NAME)
                    except OSError:
                        pass
            return True
        except Exception:
            return False


class _JobFolderEventHandler(FileSystemEventHandler):
    def __init__(self, job_id: str, base_path: str, exclude_patterns: str, on_event_cb: Callable[[str, str], None]):
        super().__init__()
        self.job_id = job_id
        self.base_path = base_path
        self.exclude_patterns = exclude_patterns
        self.on_event_cb = on_event_cb

    def on_any_event(self, event):
        if event.is_directory:
            return
        src_path = getattr(event, "src_path", "") or ""
        if not src_path:
            return
        try:
            rel_p = os.path.relpath(src_path, self.base_path).replace("\\", "/")
        except ValueError:
            rel_p = os.path.basename(src_path)
        if matches_exclude(rel_p, self.exclude_patterns):
            return
        self.on_event_cb(self.job_id, f"{event.event_type}: {rel_p}")


class RealtimeSyncService:
    """
    Watches local directories for all jobs with realtime_enabled=True
    and triggers automatic synchronization after a debounce stabilization window.
    """

    def __init__(self, trigger_job_cb: Callable[[str, str], None], log_cb: Optional[Callable[[str, str], None]] = None):
        self.trigger_job_cb = trigger_job_cb
        self.log_cb = log_cb
        self._observer: Optional[Observer] = None
        self._lock = threading.Lock()
        self._timers: Dict[str, threading.Timer] = {}
        self._busy_jobs: Set[str] = set()
        self._cooldown_until: Dict[str, float] = {}
        self._jobs_map: Dict[str, SyncJob] = {}
        self._watched_count = 0

    def mark_job_busy(self, job_id: str, is_busy: bool):
        with self._lock:
            if is_busy:
                self._busy_jobs.add(job_id)
            else:
                self._busy_jobs.discard(job_id)
                # 4-second cooldown after sync finishes so our own file writes don't re-trigger
                self._cooldown_until[job_id] = time.time() + 4.0

    def reload_watches(self, jobs: List[SyncJob]):
        self.stop()
        with self._lock:
            self._jobs_map = {j.id: j for j in jobs}
            self._watched_count = 0

        active_jobs = [j for j in jobs if j.enabled and j.realtime_enabled]
        if not active_jobs:
            return

        obs = Observer()
        watched_dirs = 0
        for job in active_jobs:
            for pair in job.pairs:
                if not pair.enabled:
                    continue
                for ep in (pair.left, pair.right):
                    if ep.protocol == "local" and ep.path and os.path.isdir(ep.path):
                        handler = _JobFolderEventHandler(
                            job_id=job.id,
                            base_path=ep.path,
                            exclude_patterns=job.exclude_patterns,
                            on_event_cb=self._on_fs_change,
                        )
                        try:
                            obs.schedule(handler, ep.path, recursive=True)
                            watched_dirs += 1
                        except Exception:
                            pass

        if watched_dirs > 0:
            obs.daemon = True
            obs.start()
            self._observer = obs
            self._watched_count = watched_dirs
            if self.log_cb:
                self.log_cb(
                    f"Sincronización Activa (Tiempo Real): Monitorizando {watched_dirs} directorios en vivo.",
                    "INFO",
                )

    @property
    def is_watching(self) -> bool:
        return self._observer is not None and self._watched_count > 0

    def _on_fs_change(self, job_id: str, detail: str):
        with self._lock:
            if job_id in self._busy_jobs:
                return
            if time.time() < self._cooldown_until.get(job_id, 0):
                return
            job = self._jobs_map.get(job_id)
            if not job or not job.realtime_enabled:
                return
            debounce = max(1, int(job.realtime_debounce_sec or 3))
            old_timer = self._timers.get(job_id)
            if old_timer:
                old_timer.cancel()

            timer = threading.Timer(debounce, self._fire_realtime_sync, args=(job_id, detail))
            timer.daemon = True
            self._timers[job_id] = timer
            timer.start()

    def _fire_realtime_sync(self, job_id: str, detail: str):
        with self._lock:
            self._timers.pop(job_id, None)
            if job_id in self._busy_jobs:
                return
        self.trigger_job_cb(job_id, f"Cambio detectado en tiempo real ({detail})")

    def stop(self):
        with self._lock:
            for t in self._timers.values():
                t.cancel()
            self._timers.clear()
        if self._observer:
            try:
                self._observer.stop()
                self._observer.join(timeout=2.0)
            except Exception:
                pass
            self._observer = None
        self._watched_count = 0


class SchedulerService:
    """
    Executes scheduled jobs based on interval, daily time, weekly days, or startup,
    and also supports registering tasks in Windows Task Scheduler (schtasks).
    """

    WEEKDAY_KEYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]

    def __init__(self, get_jobs_cb: Callable[[], List[SyncJob]], trigger_job_cb: Callable[[str, str], None]):
        self.get_jobs_cb = get_jobs_cb
        self.trigger_job_cb = trigger_job_cb
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._last_interval_run: Dict[str, float] = {}
        self._last_clock_run: Dict[str, str] = {}
        self._startup_triggered: Set[str] = set()

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False

    def _loop(self):
        # Wait 4 seconds after boot before checking startup jobs
        time.sleep(4.0)
        while self._running:
            try:
                jobs = self.get_jobs_cb()
                now = datetime.now()
                now_ts = time.time()
                hh_mm = now.strftime("%H:%M")
                day_str = now.strftime("%Y-%m-%d")
                weekday_key = self.WEEKDAY_KEYS[now.weekday()]

                for job in jobs:
                    if not job.enabled:
                        continue

                    # Remote polling check if configured
                    if job.realtime_enabled and int(job.remote_poll_sec or 0) >= 15:
                        poll_key = f"poll:{job.id}"
                        last_p = self._last_interval_run.get(poll_key, 0.0)
                        if (now_ts - last_p) >= int(job.remote_poll_sec):
                            self._last_interval_run[poll_key] = now_ts
                            self.trigger_job_cb(job.id, "Sondeo periódico remoto (Tiempo Real)")

                    if not job.schedule_enabled:
                        continue

                    stype = job.schedule_type
                    if stype == "on_startup":
                        if job.id not in self._startup_triggered:
                            self._startup_triggered.add(job.id)
                            self.trigger_job_cb(job.id, "Programación: Al iniciar aplicación")

                    elif stype == "interval":
                        mins = max(1, int(job.schedule_interval_min or 30))
                        last_ts = self._last_interval_run.get(job.id, 0.0)
                        if last_ts == 0.0:
                            # Initialize timer from startup
                            self._last_interval_run[job.id] = now_ts
                        elif (now_ts - last_ts) >= (mins * 60):
                            self._last_interval_run[job.id] = now_ts
                            self.trigger_job_cb(job.id, f"Programación por intervalo (cada {mins} min)")

                    elif stype == "daily":
                        target_time = (job.schedule_time or "02:00").strip()
                        stamp_key = f"{day_str}_{target_time}"
                        if hh_mm == target_time and self._last_clock_run.get(job.id) != stamp_key:
                            self._last_clock_run[job.id] = stamp_key
                            self.trigger_job_cb(job.id, f"Programación diaria ({target_time})")

                    elif stype == "weekly":
                        target_time = (job.schedule_time or "02:00").strip()
                        stamp_key = f"{day_str}_{target_time}"
                        allowed_days = [d.lower() for d in (job.schedule_days or [])]
                        if (
                            weekday_key in allowed_days
                            and hh_mm == target_time
                            and self._last_clock_run.get(job.id) != stamp_key
                        ):
                            self._last_clock_run[job.id] = stamp_key
                            self.trigger_job_cb(job.id, f"Programación semanal ({weekday_key.upper()} {target_time})")

            except Exception:
                pass
            time.sleep(10.0)

    @staticmethod
    def register_windows_schtask(job: SyncJob) -> Tuple[bool, str]:
        """Registers a scheduled task in Windows Task Scheduler via schtasks.exe."""
        task_name = f"StatorisSync_{job.id}"
        cmd_launch = WindowsStartupManager.get_launch_command(minimized=True) + f" --run-job {job.id}"
        args = ["schtasks", "/Create", "/F", "/TN", task_name, "/TR", cmd_launch]

        if job.schedule_type == "interval":
            mins = max(1, min(1439, int(job.schedule_interval_min or 30)))
            args += ["/SC", "MINUTE", "/MO", str(mins)]
        elif job.schedule_type == "weekly":
            day_map = {
                "mon": "MON",
                "tue": "TUE",
                "wed": "WED",
                "thu": "THU",
                "fri": "FRI",
                "sat": "SAT",
                "sun": "SUN",
            }
            days_str = ",".join(day_map.get(d, "MON") for d in (job.schedule_days or ["mon"]))
            args += ["/SC", "WEEKLY", "/D", days_str, "/ST", (job.schedule_time or "02:00")]
        elif job.schedule_type == "on_startup":
            args += ["/SC", "ONLOGON"]
        else:
            args += ["/SC", "DAILY", "/ST", (job.schedule_time or "02:00")]

        try:
            creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
            proc = subprocess.run(
                args,
                capture_output=True,
                text=True,
                creationflags=creation_flags,
                timeout=10,
            )
            if proc.returncode == 0:
                return True, f"Tarea '{task_name}' registrada en el Programador de Tareas de Windows."
            return False, f"Aviso schtasks: {proc.stderr.strip() or proc.stdout.strip()}"
        except Exception as e:
            return False, f"No se pudo registrar en schtasks: {e}"


class SystemTrayService:
    """Manages the Windows Notification Area (System Tray / IconTray) icon using pystray."""

    def __init__(
        self,
        icon_path: str,
        on_open_window: Callable[[], None],
        on_sync_all: Callable[[], None],
        on_toggle_startup: Callable[[], None],
        is_startup_enabled: Callable[[], bool],
        on_exit_app: Callable[[], None],
    ):
        self.icon_path = icon_path
        self.on_open_window = on_open_window
        self.on_sync_all = on_sync_all
        self.on_toggle_startup = on_toggle_startup
        self.is_startup_enabled = is_startup_enabled
        self.on_exit_app = on_exit_app
        self.tray_icon: Optional[pystray.Icon] = None
        self._thread: Optional[threading.Thread] = None

    def _load_pil_image(self) -> Image.Image:
        if self.icon_path and os.path.exists(self.icon_path):
            try:
                return Image.open(self.icon_path)
            except Exception:
                pass
        # Fallback Statoris Navy & Sapphire icon if image missing
        img = Image.new("RGB", (64, 64), color=(12, 35, 64))
        return img

    def start(self):
        if self.tray_icon is not None:
            return
        img = self._load_pil_image()
        menu = pystray.Menu(
            pystray.MenuItem(lambda item: i18n.get("tray_open"), lambda icon, item: self.on_open_window(), default=True),
            pystray.MenuItem(lambda item: i18n.get("tray_sync_all"), lambda icon, item: self.on_sync_all()),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                lambda item: i18n.get("tray_startup"),
                lambda icon, item: self.on_toggle_startup(),
                checked=lambda item: self.is_startup_enabled(),
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(lambda item: i18n.get("tray_exit"), lambda icon, item: self.on_exit_app()),
        )
        self.tray_icon = pystray.Icon("StatorisSync", img, "Statoris Sync — Precision Sync Engine", menu)
        self._thread = threading.Thread(target=self.tray_icon.run, daemon=True)
        self._thread.start()

    def notify(self, title: str, message: str):
        if self.tray_icon:
            try:
                self.tray_icon.notify(message, title)
            except Exception:
                pass

    def stop(self):
        if self.tray_icon:
            try:
                self.tray_icon.stop()
            except Exception:
                pass
            self.tray_icon = None

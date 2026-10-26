"""
main_window.py - Statoris Sync Desktop Application for Windows.
Combines the intuitive multi-directory side-by-side workflow of GoodSync & Allway Sync
with the official Statoris Executive Light & Dark Titanium Design System.

Key Capabilities:
- Synchronize 1 or multiple directory pairs (Dir 1 <-> Remote Dir 1, Dir 2 <-> Remote Dir 2, ...).
- Local/SMB Direct Copy, SSH/SFTP, SCP, and FTP/FTPS protocols.
- Active Real-Time Sync (instant file change detection with debounce).
- Scheduled Sync (Interval, Daily, Weekly, Startup, and Windows Task Scheduler schtasks).
- Directional (Left -> Right, Right -> Left) and Bidirectional (Two-Way) synchronization.
- Full (Completa), Incremental, and Differential synchronization modes.
- Start with Windows (HKCU Run Registry) and Minimize to System Tray (pystray IconTray).
"""

import os
import sys
import uuid
import copy
import threading
from datetime import datetime
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from typing import List, Optional, Dict

from PIL import Image
import customtkinter as ctk

from i18n import i18n
from models import (
    ConfigStore,
    SyncJob,
    FolderPair,
    EndpointConfig,
    AppSettings,
)
from transports import create_transport
from sync_engine import SyncEngine, AnalysisResult, SyncActionItem
from services import (
    RealtimeSyncService,
    SchedulerService,
    WindowsStartupManager,
    SystemTrayService,
)
from remote_dialog import EndpointConfigDialog
from ssh_keys import inspect_ssh_key_file


# Official Statoris Palette (PALETA_COLORES.css & BRAND_GUIDELINES.md)
COLOR_BG_LIGHT = "#F8FAFC"
COLOR_BG_DARK = "#0F172A"
COLOR_SURFACE_LIGHT = "#FFFFFF"
COLOR_SURFACE_DARK = "#1E293B"
COLOR_SUBTLE_LIGHT = "#F1F5F9"
COLOR_SUBTLE_DARK = "#162032"
COLOR_NAVY = "#0C2340"
COLOR_NAVY_DARK = "#09192E"
COLOR_TERMINAL = "#0C1E36"
COLOR_SAPPHIRE = "#1D4ED8"
COLOR_SAPPHIRE_HOVER = "#1E40AF"
COLOR_BRONZE = "#B45309"
COLOR_PASS = "#047857"
COLOR_FAIL = "#B91C1C"
COLOR_BORDER_LIGHT = "#E2E8F0"
COLOR_BORDER_DARK = "#334155"


def get_resource_dir() -> str:
    if getattr(sys, "frozen", False):
        return getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def format_size(num_bytes: Optional[int]) -> str:
    if num_bytes is None:
        return "—"
    sz = float(num_bytes)
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if sz < 1024.0 or unit == "TB":
            return f"{int(sz)} B" if unit == "B" else f"{sz:.1f} {unit}"
        sz /= 1024.0
    return f"{sz:.1f} TB"


def format_mtime(ts: Optional[float]) -> str:
    if not ts:
        return "—"
    try:
        return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return "—"


class StatorisSyncApp(ctk.CTk):
    def __init__(self, start_minimized_arg: bool = False, run_job_arg: Optional[str] = None):
        super().__init__()

        self.res_dir = get_resource_dir()
        self.images_dir = os.path.join(self.res_dir, "images")

        # Persistence & Core Engine
        self.store = ConfigStore()
        self.settings: AppSettings = self.store.load_settings()
        self.jobs: List[SyncJob] = self.store.load_jobs()
        self.current_job: SyncJob = self.jobs[0]
        self.engine = SyncEngine(self.store)

        self.last_analysis: Optional[AnalysisResult] = None
        self.current_filter = "all"
        self.is_busy = False

        # Apply saved language & theme
        i18n.set_language(self.settings.language if self.settings.language in ("es", "en") else "es")
        ctk.set_appearance_mode(self.settings.theme if self.settings.theme in ("Light", "Dark") else "Light")
        ctk.set_default_color_theme("blue")

        # Sync Windows Startup state with actual registry
        reg_enabled = WindowsStartupManager.is_enabled()
        self.settings.start_with_windows = reg_enabled

        # Window setup
        self.title(i18n.get("app_title"))
        self.geometry("1320x860")
        self.minsize(1120, 740)
        self.configure(fg_color=(COLOR_BG_LIGHT, COLOR_BG_DARK))

        icon_path = os.path.join(self.images_dir, "favicon.ico")
        if os.path.exists(icon_path):
            try:
                self.iconbitmap(icon_path)
            except Exception:
                pass

        # Handle window close (X) -> minimize to tray or quit
        self.protocol("WM_DELETE_WINDOW", self._on_window_close_button)

        # Background Services
        self.realtime_service = RealtimeSyncService(
            trigger_job_cb=self._on_background_job_triggered,
            log_cb=self._threadsafe_log,
        )
        self.scheduler_service = SchedulerService(
            get_jobs_cb=lambda: self.jobs,
            trigger_job_cb=self._on_background_job_triggered,
        )
        self.tray_service = SystemTrayService(
            icon_path=icon_path,
            on_open_window=lambda: self.after(0, self.restore_from_tray),
            on_sync_all=lambda: self.after(0, self.sync_all_jobs),
            on_toggle_startup=lambda: self.after(0, self._toggle_startup_from_tray),
            is_startup_enabled=lambda: self.settings.start_with_windows,
            on_exit_app=lambda: self.after(0, self.quit_completely),
        )

        # Build UI
        self._init_tk_vars()
        self._build_header()
        self._build_main_layout()
        self._build_status_bar()

        # Load current job into UI
        self._refresh_jobs_sidebar()
        self._load_job_into_ui(self.current_job)

        # Start Tray, Realtime Watcher & Scheduler
        self.tray_service.start()
        self.realtime_service.reload_watches(self.jobs)
        self.scheduler_service.start()
        self._update_realtime_badge()

        i18n.subscribe(self._refresh_i18n_labels)

        self._log("Statoris Sync iniciado correctamente. Motor Local / SSH / SCP / FTP operativo.", "SUCCESS")

        # Handle CLI flags (--minimized or --run-job)
        if start_minimized_arg or (self.settings.start_minimized and "--minimized" in sys.argv):
            self.after(200, self.minimize_to_tray)
        if run_job_arg:
            self.after(800, lambda: self._on_background_job_triggered(run_job_arg, "Ejecución CLI / Tarea Programada"))

    # =========================================================================
    # UI VARIABLES & HEADER
    # =========================================================================
    def _init_tk_vars(self):
        self.var_job_name = tk.StringVar(value="")
        self.var_direction_label = tk.StringVar(value="")
        self.var_sync_mode_label = tk.StringVar(value="")
        self.var_realtime_enabled = tk.BooleanVar(value=False)
        self.var_realtime_debounce = tk.StringVar(value="3")
        self.var_remote_poll = tk.StringVar(value="0")

        self.var_sched_enabled = tk.BooleanVar(value=False)
        self.var_sched_type = tk.StringVar(value="interval")
        self.var_sched_interval = tk.StringVar(value="30")
        self.var_sched_time = tk.StringVar(value="02:00")
        self.vars_sched_days: Dict[str, tk.BooleanVar] = {
            d: tk.BooleanVar(value=True) for d in ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
        }

        self.var_delete_orphans = tk.BooleanVar(value=True)
        self.var_conflict_policy = tk.StringVar(value="newer")
        self.var_exclude = tk.StringVar(value="")

        # System integration vars
        self.var_win_startup = tk.BooleanVar(value=self.settings.start_with_windows)
        self.var_start_minimized = tk.BooleanVar(value=self.settings.start_minimized)
        self.var_close_to_tray = tk.BooleanVar(value=self.settings.close_to_tray)
        self.var_notifications = tk.BooleanVar(value=self.settings.show_notifications)

        self.var_status_text = tk.StringVar(value=i18n.get("status_ready"))
        self.var_summary_counts = tk.StringVar(value="→ 0   |   ← 0   |   🗑 0   |   ⚡ 0   |   = 0")

    def _build_header(self):
        self.header = ctk.CTkFrame(
            self,
            corner_radius=0,
            fg_color=(COLOR_NAVY, COLOR_NAVY_DARK),
            height=68,
        )
        self.header.pack(fill="x", side="top")

        # Left Brand Box
        brand_box = ctk.CTkFrame(self.header, fg_color="transparent")
        brand_box.pack(side="left", padx=16, pady=8)

        logo_path = os.path.join(self.images_dir, "statoris_logo_titanium_horizontal_dark.png")
        if os.path.exists(logo_path):
            try:
                pil_logo = Image.open(logo_path)
                ctk_logo = ctk.CTkImage(light_image=pil_logo, dark_image=pil_logo, size=(200, 48))
                self.lbl_logo = ctk.CTkLabel(brand_box, image=ctk_logo, text="")
                self.lbl_logo.pack(side="left", padx=(0, 10))
            except Exception:
                self.lbl_logo = ctk.CTkLabel(
                    brand_box,
                    text="STATORIS SYNC",
                    font=ctk.CTkFont(size=20, weight="bold"),
                    text_color="#FFFFFF",
                )
                self.lbl_logo.pack(side="left", padx=(0, 10))
        else:
            self.lbl_logo = ctk.CTkLabel(
                brand_box,
                text="STATORIS SYNC",
                font=ctk.CTkFont(size=20, weight="bold"),
                text_color="#FFFFFF",
            )
            self.lbl_logo.pack(side="left", padx=(0, 10))

        self.lbl_badge = ctk.CTkLabel(
            brand_box,
            text=i18n.get("brand_subtitle"),
            font=ctk.CTkFont(family="Segoe UI", size=10, weight="bold"),
            fg_color=COLOR_BRONZE,
            text_color="#FFFFFF",
            corner_radius=4,
            padx=8,
            pady=2,
        )
        self.lbl_badge.pack(side="left", padx=4)

        self.lbl_rt_status_pill = ctk.CTkLabel(
            brand_box,
            text=i18n.get("status_realtime_idle"),
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color="#16365C",
            text_color="#E2E8F0",
            corner_radius=6,
            padx=10,
            pady=3,
        )
        self.lbl_rt_status_pill.pack(side="left", padx=12)

        # Right Header Controls: Start with Windows, Minimize to Tray, Language, Theme
        right_box = ctk.CTkFrame(self.header, fg_color="transparent")
        right_box.pack(side="right", padx=16, pady=10)

        self.sw_header_startup = ctk.CTkSwitch(
            right_box,
            text=i18n.get("chk_win_startup"),
            variable=self.var_win_startup,
            command=self._on_toggle_windows_startup,
            text_color="#F8FAFC",
            progress_color=COLOR_PASS,
            font=ctk.CTkFont(size=12, weight="bold"),
        )
        self.sw_header_startup.pack(side="left", padx=(0, 14))

        self.btn_header_tray = ctk.CTkButton(
            right_box,
            text=i18n.get("btn_minimize_tray"),
            width=130,
            height=30,
            fg_color="#16365C",
            hover_color=COLOR_SAPPHIRE,
            text_color="#FFFFFF",
            font=ctk.CTkFont(size=12, weight="bold"),
            command=self.minimize_to_tray,
        )
        self.btn_header_tray.pack(side="left", padx=(0, 14))

        self.opt_lang = ctk.CTkOptionMenu(
            right_box,
            values=["Español", "English"],
            width=100,
            height=30,
            fg_color="#16365C",
            button_color="#1E3A5F",
            command=self._on_language_selected,
        )
        self.opt_lang.set("Español" if i18n.current_lang == "es" else "English")
        self.opt_lang.pack(side="left", padx=(0, 10))

        self.opt_theme = ctk.CTkOptionMenu(
            right_box,
            values=[i18n.get("theme_light"), i18n.get("theme_dark")],
            width=135,
            height=30,
            fg_color="#16365C",
            button_color="#1E3A5F",
            command=self._on_theme_selected,
        )
        self.opt_theme.set(
            i18n.get("theme_light") if self.settings.theme == "Light" else i18n.get("theme_dark")
        )
        self.opt_theme.pack(side="left")

    # =========================================================================
    # MAIN BODY LAYOUT: LEFT SIDEBAR (JOBS) + RIGHT WORKSPACE
    # =========================================================================
    def _build_main_layout(self):
        self.body_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.body_frame.pack(fill="both", expand=True, padx=12, pady=(10, 6))

        # 1. Left Sidebar (Jobs List like GoodSync / Allway Sync)
        self.sidebar = ctk.CTkFrame(
            self.body_frame,
            width=265,
            corner_radius=10,
            fg_color=(COLOR_SURFACE_LIGHT, COLOR_SURFACE_DARK),
            border_width=1,
            border_color=(COLOR_BORDER_LIGHT, COLOR_BORDER_DARK),
        )
        self.sidebar.pack(side="left", fill="y", padx=(0, 10))
        self.sidebar.pack_propagate(False)

        self.lbl_sidebar_title = ctk.CTkLabel(
            self.sidebar,
            text=i18n.get("sidebar_title"),
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=(COLOR_NAVY, "#93C5FD"),
        )
        self.lbl_sidebar_title.pack(anchor="w", padx=14, pady=(12, 6))

        # Job CRUD Buttons
        crud_row = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        crud_row.pack(fill="x", padx=10, pady=(0, 6))

        self.btn_new_job = ctk.CTkButton(
            crud_row,
            text=i18n.get("btn_new_job"),
            width=95,
            height=28,
            fg_color=COLOR_SAPPHIRE,
            hover_color=COLOR_SAPPHIRE_HOVER,
            font=ctk.CTkFont(size=11, weight="bold"),
            command=self._create_new_job,
        )
        self.btn_new_job.pack(side="left", padx=(0, 4))

        self.btn_dup_job = ctk.CTkButton(
            crud_row,
            text=i18n.get("btn_dup_job"),
            width=68,
            height=28,
            fg_color="#475569",
            hover_color="#334155",
            font=ctk.CTkFont(size=11),
            command=self._duplicate_current_job,
        )
        self.btn_dup_job.pack(side="left", padx=(0, 4))

        self.btn_del_job = ctk.CTkButton(
            crud_row,
            text=i18n.get("btn_del_job"),
            width=68,
            height=28,
            fg_color=COLOR_FAIL,
            hover_color="#991B1B",
            font=ctk.CTkFont(size=11),
            command=self._delete_current_job,
        )
        self.btn_del_job.pack(side="left")

        # Scrollable list of Jobs
        self.jobs_scroll = ctk.CTkScrollableFrame(
            self.sidebar,
            fg_color="transparent",
        )
        self.jobs_scroll.pack(fill="both", expand=True, padx=6, pady=4)

        # Global All-Jobs Buttons at bottom of sidebar
        global_box = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        global_box.pack(fill="x", side="bottom", padx=10, pady=10)

        self.btn_sync_all_jobs = ctk.CTkButton(
            global_box,
            text=i18n.get("btn_sync_all_jobs"),
            height=36,
            fg_color=COLOR_PASS,
            hover_color="#065F46",
            font=ctk.CTkFont(size=12, weight="bold"),
            command=self.sync_all_jobs,
        )
        self.btn_sync_all_jobs.pack(fill="x")

        # 2. Right Main Workspace
        self.workspace = ctk.CTkFrame(
            self.body_frame,
            fg_color="transparent",
        )
        self.workspace.pack(side="left", fill="both", expand=True)

        self._build_job_toolbar()
        self._build_workspace_tabs()

    def _build_job_toolbar(self):
        """GoodSync / Allway Sync top control bar with Analyze, Synchronize, Direction & Sync Mode."""
        self.toolbar_card = ctk.CTkFrame(
            self.workspace,
            corner_radius=10,
            fg_color=(COLOR_SURFACE_LIGHT, COLOR_SURFACE_DARK),
            border_width=1,
            border_color=(COLOR_BORDER_LIGHT, COLOR_BORDER_DARK),
        )
        self.toolbar_card.pack(fill="x", pady=(0, 8))

        # Top row: Job Name + Analyze + Synchronize + Stop + Realtime switch
        top_row = ctk.CTkFrame(self.toolbar_card, fg_color="transparent")
        top_row.pack(fill="x", padx=14, pady=(10, 6))

        ctk.CTkLabel(
            top_row,
            text="Tarea:",
            font=ctk.CTkFont(size=12, weight="bold"),
        ).pack(side="left", padx=(0, 6))

        self.ent_job_name = ctk.CTkEntry(
            top_row,
            textvariable=self.var_job_name,
            width=230,
            height=34,
            font=ctk.CTkFont(size=13, weight="bold"),
        )
        self.ent_job_name.pack(side="left", padx=(0, 12))
        self.ent_job_name.bind("<FocusOut>", lambda e: self._save_current_job_from_ui())
        self.ent_job_name.bind("<Return>", lambda e: self._save_current_job_from_ui())

        self.btn_analyze = ctk.CTkButton(
            top_row,
            text=i18n.get("btn_analyze"),
            width=155,
            height=36,
            fg_color=COLOR_SAPPHIRE,
            hover_color=COLOR_SAPPHIRE_HOVER,
            font=ctk.CTkFont(size=13, weight="bold"),
            command=self.run_analyze_current_job,
        )
        self.btn_analyze.pack(side="left", padx=(0, 8))

        self.btn_sync = ctk.CTkButton(
            top_row,
            text=i18n.get("btn_sync"),
            width=185,
            height=36,
            fg_color=COLOR_PASS,
            hover_color="#065F46",
            font=ctk.CTkFont(size=13, weight="bold"),
            command=self.run_sync_current_job,
        )
        self.btn_sync.pack(side="left", padx=(0, 8))

        self.btn_stop = ctk.CTkButton(
            top_row,
            text=i18n.get("btn_stop"),
            width=95,
            height=36,
            fg_color=COLOR_FAIL,
            hover_color="#991B1B",
            state="disabled",
            font=ctk.CTkFont(size=12, weight="bold"),
            command=self.stop_active_operation,
        )
        self.btn_stop.pack(side="left", padx=(0, 12))

        self.sw_toolbar_rt = ctk.CTkSwitch(
            top_row,
            text=i18n.get("sw_realtime_quick"),
            variable=self.var_realtime_enabled,
            progress_color=COLOR_PASS,
            font=ctk.CTkFont(size=12, weight="bold"),
            command=self._on_realtime_toggled,
        )
        self.sw_toolbar_rt.pack(side="right", padx=4)

        # Second row: Direction selector + Sync Mode selector (Completa / Incremental / Diferencial)
        bot_row = ctk.CTkFrame(self.toolbar_card, fg_color="transparent")
        bot_row.pack(fill="x", padx=14, pady=(2, 10))

        self.lbl_dir_title = ctk.CTkLabel(
            bot_row,
            text=i18n.get("lbl_direction"),
            font=ctk.CTkFont(size=12, weight="bold"),
        )
        self.lbl_dir_title.pack(side="left", padx=(0, 6))

        self.opt_direction = ctk.CTkOptionMenu(
            bot_row,
            variable=self.var_direction_label,
            values=self._get_direction_labels(),
            width=260,
            height=30,
            fg_color=COLOR_NAVY,
            button_color="#16365C",
            command=self._on_direction_changed,
        )
        self.opt_direction.pack(side="left", padx=(0, 20))

        self.lbl_mode_title = ctk.CTkLabel(
            bot_row,
            text=i18n.get("lbl_sync_mode"),
            font=ctk.CTkFont(size=12, weight="bold"),
        )
        self.lbl_mode_title.pack(side="left", padx=(0, 6))

        self.opt_sync_mode = ctk.CTkOptionMenu(
            bot_row,
            variable=self.var_sync_mode_label,
            values=self._get_mode_labels(),
            width=270,
            height=30,
            fg_color=COLOR_BRONZE,
            button_color="#92400E",
            command=self._on_sync_mode_changed,
        )
        self.opt_sync_mode.pack(side="left", padx=(0, 12))

        self.lbl_summary_counts = ctk.CTkLabel(
            bot_row,
            textvariable=self.var_summary_counts,
            font=ctk.CTkFont(family="Consolas", size=12, weight="bold"),
            text_color=(COLOR_NAVY, "#93C5FD"),
        )
        self.lbl_summary_counts.pack(side="right", padx=6)

    def _build_workspace_tabs(self):
        self.tabview = ctk.CTkTabview(
            self.workspace,
            corner_radius=10,
            fg_color=(COLOR_SURFACE_LIGHT, COLOR_SURFACE_DARK),
            segmented_button_selected_color=COLOR_SAPPHIRE,
            segmented_button_selected_hover_color=COLOR_SAPPHIRE_HOVER,
        )
        self.tabview.pack(fill="both", expand=True)

        self.tab_pairs = self.tabview.add(i18n.get("tab_pairs"))
        self.tab_automation = self.tabview.add(i18n.get("tab_automation"))
        self.tab_options = self.tabview.add(i18n.get("tab_options"))
        self.tab_console = self.tabview.add(i18n.get("tab_console"))

        self._build_tab_pairs()
        self._build_tab_automation()
        self._build_tab_options()
        self._build_tab_console()

    # =========================================================================
    # TAB 1: MULTI-DIRECTORY PAIRS & SIDE-BY-SIDE COMPARISON TREE
    # =========================================================================
    def _build_tab_pairs(self):
        # Upper Panel: Multi-Directory Pairs (Dir 1 <-> Remote Dir 1, Dir 2 <-> Remote Dir 2, ...)
        pairs_card = ctk.CTkFrame(
            self.tab_pairs,
            corner_radius=8,
            fg_color=(COLOR_SUBTLE_LIGHT, COLOR_SUBTLE_DARK),
            border_width=1,
            border_color=(COLOR_BORDER_LIGHT, COLOR_BORDER_DARK),
        )
        pairs_card.pack(fill="x", padx=6, pady=(4, 8))

        hdr_row = ctk.CTkFrame(pairs_card, fg_color="transparent")
        hdr_row.pack(fill="x", padx=12, pady=(8, 4))

        title_col = ctk.CTkFrame(hdr_row, fg_color="transparent")
        title_col.pack(side="left", fill="x", expand=True)

        self.lbl_pairs_hdr = ctk.CTkLabel(
            title_col,
            text=i18n.get("pairs_header"),
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=(COLOR_NAVY, "#F8FAFC"),
        )
        self.lbl_pairs_hdr.pack(anchor="w")

        self.lbl_pairs_sub = ctk.CTkLabel(
            title_col,
            text=i18n.get("pairs_subheader"),
            font=ctk.CTkFont(size=11),
            text_color=("gray35", "gray70"),
        )
        self.lbl_pairs_sub.pack(anchor="w")

        self.btn_add_pair = ctk.CTkButton(
            hdr_row,
            text=i18n.get("btn_add_pair"),
            height=32,
            fg_color=COLOR_SAPPHIRE,
            hover_color=COLOR_SAPPHIRE_HOVER,
            font=ctk.CTkFont(size=12, weight="bold"),
            command=self._add_folder_pair,
        )
        self.btn_add_pair.pack(side="right", padx=4)

        # Scrollable container for 1 or multiple folder pairs
        self.pairs_scroll = ctk.CTkScrollableFrame(
            pairs_card,
            height=175,
            fg_color="transparent",
        )
        self.pairs_scroll.pack(fill="x", padx=8, pady=(0, 8))

        # Lower Panel: GoodSync / Allway Sync File Comparison Table
        comp_card = ctk.CTkFrame(
            self.tab_pairs,
            corner_radius=8,
            fg_color="transparent",
        )
        comp_card.pack(fill="both", expand=True, padx=6, pady=(0, 4))

        filter_bar = ctk.CTkFrame(comp_card, fg_color="transparent")
        filter_bar.pack(fill="x", pady=(0, 4))

        self.lbl_comp_hdr = ctk.CTkLabel(
            filter_bar,
            text=i18n.get("comp_header"),
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=(COLOR_NAVY, "#93C5FD"),
        )
        self.lbl_comp_hdr.pack(side="left")

        # Filter pills
        filter_btns_box = ctk.CTkFrame(filter_bar, fg_color="transparent")
        filter_btns_box.pack(side="right")

        self.btn_flt_all = ctk.CTkButton(
            filter_btns_box,
            text="Todos",
            width=85,
            height=26,
            fg_color=COLOR_SAPPHIRE,
            command=lambda: self._set_tree_filter("all"),
        )
        self.btn_flt_all.pack(side="left", padx=2)

        self.btn_flt_pending = ctk.CTkButton(
            filter_btns_box,
            text="Pendientes",
            width=105,
            height=26,
            fg_color="#475569",
            command=lambda: self._set_tree_filter("pending"),
        )
        self.btn_flt_pending.pack(side="left", padx=2)

        self.btn_flt_conflicts = ctk.CTkButton(
            filter_btns_box,
            text="Conflictos",
            width=95,
            height=26,
            fg_color="#475569",
            command=lambda: self._set_tree_filter("conflicts"),
        )
        self.btn_flt_conflicts.pack(side="left", padx=2)

        self.btn_flt_equal = ctk.CTkButton(
            filter_btns_box,
            text="Idénticos",
            width=95,
            height=26,
            fg_color="#475569",
            command=lambda: self._set_tree_filter("equal"),
        )
        self.btn_flt_equal.pack(side="left", padx=2)

        # Treeview Table
        tree_container = ctk.CTkFrame(comp_card, corner_radius=6)
        tree_container.pack(fill="both", expand=True)

        self._style_treeview()

        cols = ("pair", "relpath", "left_info", "action", "right_info", "reason")
        self.tree = ttk.Treeview(tree_container, columns=cols, show="headings", selectmode="browse")

        self.tree.heading("pair", text=i18n.get("col_pair"))
        self.tree.heading("relpath", text=i18n.get("col_relpath"))
        self.tree.heading("left_info", text=i18n.get("col_left_info"))
        self.tree.heading("action", text=i18n.get("col_action"))
        self.tree.heading("right_info", text=i18n.get("col_right_info"))
        self.tree.heading("reason", text=i18n.get("col_reason"))

        self.tree.column("pair", width=145, anchor="w")
        self.tree.column("relpath", width=270, anchor="w")
        self.tree.column("left_info", width=165, anchor="center")
        self.tree.column("action", width=155, anchor="center")
        self.tree.column("right_info", width=165, anchor="center")
        self.tree.column("reason", width=230, anchor="w")

        vsb = ttk.Scrollbar(tree_container, orient="vertical", command=self.tree.yview)
        hsb = ttk.Scrollbar(tree_container, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)

        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        tree_container.rowconfigure(0, weight=1)
        tree_container.columnconfigure(0, weight=1)

        # Color tags for actions
        self.tree.tag_configure("copy_lr", foreground="#1D4ED8")
        self.tree.tag_configure("copy_rl", foreground="#047857")
        self.tree.tag_configure("delete_r", foreground="#B91C1C")
        self.tree.tag_configure("delete_l", foreground="#B91C1C")
        self.tree.tag_configure("conflict", foreground="#B45309")
        self.tree.tag_configure("equal", foreground="#64748B")
        self.tree.tag_configure("skip", foreground="#64748B")

    def _style_treeview(self):
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except Exception:
            pass
        is_dark = ctk.get_appearance_mode() == "Dark"
        bg = "#1E293B" if is_dark else "#FFFFFF"
        fg = "#F8FAFC" if is_dark else "#0F172A"
        hdr_bg = "#0C2340"
        hdr_fg = "#FFFFFF"
        style.configure(
            "Treeview",
            background=bg,
            foreground=fg,
            fieldbackground=bg,
            rowheight=28,
            font=("Segoe UI", 10),
        )
        style.configure(
            "Treeview.Heading",
            background=hdr_bg,
            foreground=hdr_fg,
            font=("Segoe UI", 10, "bold"),
            relief="flat",
        )
        style.map("Treeview", background=[("selected", "#DBEAFE" if not is_dark else "#1E3A8A")])

    def _render_folder_pairs(self):
        """Renders each FolderPair row (Dir 1 <-> Dir 1 Remoto, Dir 2 <-> Dir 2 Remoto, ...)."""
        for child in self.pairs_scroll.winfo_children():
            child.destroy()

        dir_sym = {
            "bidirectional": "⇄",
            "left_to_right": "→",
            "right_to_left": "←",
        }.get(self.current_job.direction, "⇄")

        for idx, pair in enumerate(self.current_job.pairs):
            row_card = ctk.CTkFrame(
                self.pairs_scroll,
                corner_radius=8,
                fg_color=(COLOR_SURFACE_LIGHT, COLOR_SURFACE_DARK),
                border_width=1,
                border_color=(COLOR_BORDER_LIGHT, COLOR_BORDER_DARK),
            )
            row_card.pack(fill="x", padx=4, pady=4)

            # Top mini header inside the pair row: Checkbox + Pair Name + Protocol badges + Remove
            top_strip = ctk.CTkFrame(row_card, fg_color="transparent")
            top_strip.pack(fill="x", padx=10, pady=(6, 2))

            var_en = tk.BooleanVar(value=pair.enabled)
            chk = ctk.CTkCheckBox(
                top_strip,
                text="",
                variable=var_en,
                width=24,
                command=lambda p=pair, v=var_en: self._on_pair_enabled_toggle(p, v.get()),
            )
            chk.pack(side="left")

            ent_pname = ctk.CTkEntry(
                top_strip,
                width=185,
                height=26,
                font=ctk.CTkFont(size=12, weight="bold"),
            )
            ent_pname.insert(0, pair.name or f"Dir {idx + 1} ↔ Remoto {idx + 1}")
            ent_pname.pack(side="left", padx=(2, 10))
            ent_pname.bind("<FocusOut>", lambda e, p=pair, w=ent_pname: self._on_pair_name_edit(p, w.get()))

            # Quick Protocol Badges
            l_proto = (pair.left.protocol or "local").upper()
            r_proto = (pair.right.protocol or "local").upper()
            ctk.CTkLabel(
                top_strip,
                text=f"Origen: {l_proto}   {dir_sym}   Destino: {r_proto}",
                font=ctk.CTkFont(size=11, weight="bold"),
                text_color=(COLOR_SAPPHIRE, "#93C5FD"),
            ).pack(side="left", padx=6)

            if len(self.current_job.pairs) > 1:
                ctk.CTkButton(
                    top_strip,
                    text=i18n.get("btn_remove_pair"),
                    width=75,
                    height=24,
                    fg_color=COLOR_FAIL,
                    hover_color="#991B1B",
                    font=ctk.CTkFont(size=11),
                    command=lambda p=pair: self._remove_folder_pair(p),
                ).pack(side="right")

            ctk.CTkButton(
                top_strip,
                text=i18n.get("btn_test_conn"),
                width=85,
                height=24,
                fg_color="#334155",
                hover_color="#1E293B",
                font=ctk.CTkFont(size=11),
                command=lambda p=pair: self._test_pair_endpoints(p),
            ).pack(side="right", padx=6)

            # Endpoints row: Left (Origin) <---> Right (Destination / Remote)
            ep_row = ctk.CTkFrame(row_card, fg_color="transparent")
            ep_row.pack(fill="x", padx=10, pady=(2, 8))
            ep_row.columnconfigure(0, weight=1)
            ep_row.columnconfigure(2, weight=1)

            # LEFT SIDE (Origen)
            left_box = ctk.CTkFrame(ep_row, fg_color="transparent")
            left_box.grid(row=0, column=0, sticky="ew")

            var_l_proto = tk.StringVar(value=(pair.left.protocol or "local").upper())
            opt_l_proto = ctk.CTkOptionMenu(
                left_box,
                variable=var_l_proto,
                values=["LOCAL", "SSH", "SCP", "FTP", "FTPS"],
                width=82,
                height=30,
                fg_color=COLOR_NAVY,
                command=lambda val, p=pair: self._on_quick_proto_change(p, "left", val),
            )
            opt_l_proto.pack(side="left", padx=(0, 4))

            ent_l_path = ctk.CTkEntry(
                left_box,
                height=30,
                placeholder_text="Ruta Directorio Origen (Local o Remoto)...",
            )
            ent_l_path.insert(0, pair.left.display_uri() if pair.left.protocol != "local" else pair.left.path)
            ent_l_path.pack(side="left", fill="x", expand=True, padx=(0, 4))
            ent_l_path.bind("<FocusOut>", lambda e, p=pair, w=ent_l_path: self._on_manual_path_entry(p.left, w.get()))

            ctk.CTkButton(
                left_box,
                text="📂" if pair.left.protocol == "local" else "🌐",
                width=36,
                height=30,
                fg_color=COLOR_SAPPHIRE if pair.left.protocol == "local" else COLOR_BRONZE,
                command=lambda p=pair: self._pick_or_configure_endpoint(p, "left"),
            ).pack(side="left", padx=(0, 2))

            ctk.CTkButton(
                left_box,
                text="🔑 Clave / Config" if pair.left.protocol in ("ssh", "scp") else "🌐 Config",
                width=112 if pair.left.protocol in ("ssh", "scp") else 74,
                height=30,
                fg_color="#334155",
                command=lambda p=pair: self._open_endpoint_dialog(p, "left"),
            ).pack(side="left")

            # CENTER ARROW
            ctk.CTkLabel(
                ep_row,
                text=f"  {dir_sym}  ",
                font=ctk.CTkFont(size=18, weight="bold"),
                text_color=(COLOR_BRONZE, "#FBBF24"),
            ).grid(row=0, column=1, padx=4)

            # RIGHT SIDE (Destino / Remoto)
            right_box = ctk.CTkFrame(ep_row, fg_color="transparent")
            right_box.grid(row=0, column=2, sticky="ew")

            var_r_proto = tk.StringVar(value=(pair.right.protocol or "local").upper())
            opt_r_proto = ctk.CTkOptionMenu(
                right_box,
                variable=var_r_proto,
                values=["LOCAL", "SSH", "SCP", "FTP", "FTPS"],
                width=82,
                height=30,
                fg_color=COLOR_NAVY,
                command=lambda val, p=pair: self._on_quick_proto_change(p, "right", val),
            )
            opt_r_proto.pack(side="left", padx=(0, 4))

            ent_r_path = ctk.CTkEntry(
                right_box,
                height=30,
                placeholder_text="Ruta Directorio Destino (Local, SSH, SCP o FTP)...",
            )
            ent_r_path.insert(0, pair.right.display_uri() if pair.right.protocol != "local" else pair.right.path)
            ent_r_path.pack(side="left", fill="x", expand=True, padx=(0, 4))
            ent_r_path.bind("<FocusOut>", lambda e, p=pair, w=ent_r_path: self._on_manual_path_entry(p.right, w.get()))

            ctk.CTkButton(
                right_box,
                text="📂" if pair.right.protocol == "local" else "🌐",
                width=36,
                height=30,
                fg_color=COLOR_SAPPHIRE if pair.right.protocol == "local" else COLOR_BRONZE,
                command=lambda p=pair: self._pick_or_configure_endpoint(p, "right"),
            ).pack(side="left", padx=(0, 2))

            ctk.CTkButton(
                right_box,
                text="🔑 Clave SSH / Remoto" if pair.right.protocol in ("ssh", "scp") else "🌐 Remoto",
                width=136 if pair.right.protocol in ("ssh", "scp") else 78,
                height=30,
                fg_color=COLOR_BRONZE,
                hover_color="#92400E",
                command=lambda p=pair: self._open_endpoint_dialog(p, "right"),
            ).pack(side="left")

            # Inline SSH / SCP Private Key & Passphrase strip when SSH or SCP is selected
            for side_code, side_title, ep_obj in [
                ("left", "Origen", pair.left),
                ("right", "Destino Remoto", pair.right),
            ]:
                if (ep_obj.protocol or "").lower() in ("ssh", "scp"):
                    self._render_inline_ssh_key_bar(row_card, pair, side_code, side_title, ep_obj)

    def _render_inline_ssh_key_bar(
        self, parent_card, pair: FolderPair, side_code: str, side_title: str, ep: EndpointConfig
    ):
        ssh_bar = ctk.CTkFrame(
            parent_card,
            corner_radius=6,
            fg_color=("#EFF6FF", "#0F172A"),
            border_width=1,
            border_color=("#BFDBFE", "#1E3A8A"),
        )
        ssh_bar.pack(fill="x", padx=10, pady=(0, 6))

        ctk.CTkLabel(
            ssh_bar,
            text=f"🔑 {side_title} ({ep.protocol.upper()}):",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color=(COLOR_NAVY, "#93C5FD"),
        ).pack(side="left", padx=(8, 4), pady=4)

        # Key file entry & picker
        ent_kfile = ctk.CTkEntry(
            ssh_bar,
            width=210,
            height=26,
            placeholder_text="Clave privada SSH (.ppk / .pem / id_rsa)",
            font=ctk.CTkFont(size=11),
        )
        if ep.key_file:
            ent_kfile.insert(0, ep.key_file)
        ent_kfile.pack(side="left", padx=2, pady=4)

        def _save_kfile(_e=None, endpoint=ep, widget=ent_kfile):
            endpoint.key_file = widget.get().strip()
            self.store.save_jobs(self.jobs)

        ent_kfile.bind("<FocusOut>", _save_kfile)

        def _pick_key(endpoint=ep, widget=ent_kfile):
            fpath = filedialog.askopenfilename(
                title="Seleccionar Clave Privada SSH (.ppk, .pem, OpenSSH)",
                filetypes=[
                    ("Claves Privadas SSH", "*.ppk *.pem *.key *id_rsa* *id_ed25519* *id_ecdsa*"),
                    ("Todos los archivos", "*.*"),
                ],
            )
            if fpath:
                widget.delete(0, "end")
                widget.insert(0, fpath)
                endpoint.key_file = fpath
                self.store.save_jobs(self.jobs)
                self._render_folder_pairs()

        ctk.CTkButton(
            ssh_bar,
            text="📂 Clave...",
            width=74,
            height=26,
            fg_color=COLOR_SAPPHIRE,
            font=ctk.CTkFont(size=11),
            command=_pick_key,
        ).pack(side="left", padx=(2, 8), pady=4)

        # Passphrase label & entry
        ctk.CTkLabel(
            ssh_bar,
            text="🔐 Passphrase (descifrar clave SSH):",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color=(COLOR_BRONZE, "#FBBF24"),
        ).pack(side="left", padx=(4, 4), pady=4)

        ent_kpass = ctk.CTkEntry(
            ssh_bar,
            width=190,
            height=26,
            show="•",
            placeholder_text='Passphrase clave (ej. "admin-statoris")',
            font=ctk.CTkFont(size=11),
        )
        if ep.key_passphrase:
            ent_kpass.insert(0, ep.key_passphrase)
        ent_kpass.pack(side="left", padx=2, pady=4)

        def _save_kpass(_e=None, endpoint=ep, widget=ent_kpass):
            endpoint.key_passphrase = widget.get()
            self.store.save_jobs(self.jobs)

        ent_kpass.bind("<FocusOut>", _save_kpass)
        ent_kpass.bind("<KeyRelease>", _save_kpass)

        def _toggle_eye(widget=ent_kpass):
            curr = widget.cget("show")
            widget.configure(show="" if curr == "•" else "•")

        ctk.CTkButton(
            ssh_bar,
            text="👁",
            width=30,
            height=26,
            fg_color="#475569",
            command=_toggle_eye,
        ).pack(side="left", padx=(2, 6), pady=4)

    # =========================================================================
    # TAB 2: ACTIVE REAL-TIME SYNC & SCHEDULER
    # =========================================================================
    def _build_tab_automation(self):
        scroll = ctk.CTkScrollableFrame(self.tab_automation, fg_color="transparent")
        scroll.pack(fill="both", expand=True, padx=8, pady=6)

        # Card 1: Active Real-Time Sync
        rt_card = ctk.CTkFrame(
            scroll,
            corner_radius=10,
            fg_color=(COLOR_SUBTLE_LIGHT, COLOR_SUBTLE_DARK),
            border_width=1,
            border_color=(COLOR_BORDER_LIGHT, COLOR_BORDER_DARK),
        )
        rt_card.pack(fill="x", pady=(0, 12))

        ctk.CTkLabel(
            rt_card,
            text=i18n.get("rt_card_title"),
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color=(COLOR_NAVY, "#93C5FD"),
        ).pack(anchor="w", padx=16, pady=(12, 4))

        ctk.CTkLabel(
            rt_card,
            text=i18n.get("rt_card_desc"),
            font=ctk.CTkFont(size=12),
            text_color=("gray30", "gray75"),
            wraplength=920,
            justify="left",
        ).pack(anchor="w", padx=16, pady=(0, 10))

        ctk.CTkSwitch(
            rt_card,
            text=i18n.get("rt_enable"),
            variable=self.var_realtime_enabled,
            progress_color=COLOR_PASS,
            font=ctk.CTkFont(size=13, weight="bold"),
            command=self._on_realtime_toggled,
        ).pack(anchor="w", padx=16, pady=6)

        rt_row = ctk.CTkFrame(rt_card, fg_color="transparent")
        rt_row.pack(fill="x", padx=16, pady=(4, 14))

        ctk.CTkLabel(rt_row, text=i18n.get("rt_debounce")).pack(side="left", padx=(0, 8))
        ent_deb = ctk.CTkEntry(rt_row, textvariable=self.var_realtime_debounce, width=70)
        ent_deb.pack(side="left", padx=(0, 24))
        ent_deb.bind("<FocusOut>", lambda e: self._save_current_job_from_ui())

        ctk.CTkLabel(rt_row, text=i18n.get("rt_remote_poll")).pack(side="left", padx=(0, 8))
        ent_poll = ctk.CTkEntry(rt_row, textvariable=self.var_remote_poll, width=70)
        ent_poll.pack(side="left")
        ent_poll.bind("<FocusOut>", lambda e: self._save_current_job_from_ui())

        # Card 2: Automatic Scheduler
        sched_card = ctk.CTkFrame(
            scroll,
            corner_radius=10,
            fg_color=(COLOR_SUBTLE_LIGHT, COLOR_SUBTLE_DARK),
            border_width=1,
            border_color=(COLOR_BORDER_LIGHT, COLOR_BORDER_DARK),
        )
        sched_card.pack(fill="x", pady=(0, 12))

        ctk.CTkLabel(
            sched_card,
            text=i18n.get("sched_card_title"),
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color=(COLOR_NAVY, "#93C5FD"),
        ).pack(anchor="w", padx=16, pady=(12, 4))

        ctk.CTkLabel(
            sched_card,
            text=i18n.get("sched_card_desc"),
            font=ctk.CTkFont(size=12),
            text_color=("gray30", "gray75"),
        ).pack(anchor="w", padx=16, pady=(0, 10))

        ctk.CTkSwitch(
            sched_card,
            text=i18n.get("sched_enable"),
            variable=self.var_sched_enabled,
            progress_color=COLOR_SAPPHIRE,
            font=ctk.CTkFont(size=13, weight="bold"),
            command=self._save_current_job_from_ui,
        ).pack(anchor="w", padx=16, pady=6)

        # Schedule Type Radio Buttons
        type_frame = ctk.CTkFrame(sched_card, fg_color="transparent")
        type_frame.pack(fill="x", padx=16, pady=6)

        for val, key in [
            ("interval", "sched_interval"),
            ("daily", "sched_daily"),
            ("weekly", "sched_weekly"),
            ("on_startup", "sched_startup"),
        ]:
            ctk.CTkRadioButton(
                type_frame,
                text=i18n.get(key),
                variable=self.var_sched_type,
                value=val,
                command=self._save_current_job_from_ui,
            ).pack(side="left", padx=(0, 18))

        params_frame = ctk.CTkFrame(sched_card, fg_color="transparent")
        params_frame.pack(fill="x", padx=16, pady=8)

        ctk.CTkLabel(params_frame, text=i18n.get("sched_every_min")).pack(side="left", padx=(0, 6))
        ent_int = ctk.CTkEntry(params_frame, textvariable=self.var_sched_interval, width=75)
        ent_int.pack(side="left", padx=(0, 24))
        ent_int.bind("<FocusOut>", lambda e: self._save_current_job_from_ui())

        ctk.CTkLabel(params_frame, text=i18n.get("sched_at_time")).pack(side="left", padx=(0, 6))
        ent_tm = ctk.CTkEntry(params_frame, textvariable=self.var_sched_time, width=85)
        ent_tm.pack(side="left")
        ent_tm.bind("<FocusOut>", lambda e: self._save_current_job_from_ui())

        days_frame = ctk.CTkFrame(sched_card, fg_color="transparent")
        days_frame.pack(fill="x", padx=16, pady=6)
        ctk.CTkLabel(days_frame, text=i18n.get("sched_days")).pack(side="left", padx=(0, 10))

        for d_code, d_key in [
            ("mon", "day_mon"),
            ("tue", "day_tue"),
            ("wed", "day_wed"),
            ("thu", "day_thu"),
            ("fri", "day_fri"),
            ("sat", "day_sat"),
            ("sun", "day_sun"),
        ]:
            ctk.CTkCheckBox(
                days_frame,
                text=i18n.get(d_key),
                variable=self.vars_sched_days[d_code],
                width=65,
                command=self._save_current_job_from_ui,
            ).pack(side="left", padx=4)

        ctk.CTkButton(
            sched_card,
            text=i18n.get("btn_register_win_task"),
            fg_color=COLOR_NAVY,
            hover_color="#16365C",
            height=34,
            command=self._register_in_windows_task_scheduler,
        ).pack(anchor="w", padx=16, pady=(8, 14))

    # =========================================================================
    # TAB 3: SYNC MODES, CONFLICT RULES, FILTERS & WINDOWS SYSTEM TRAY / STARTUP
    # =========================================================================
    def _build_tab_options(self):
        scroll = ctk.CTkScrollableFrame(self.tab_options, fg_color="transparent")
        scroll.pack(fill="both", expand=True, padx=8, pady=6)

        # Card 1: Full / Incremental / Differential explanation & baseline reset
        modes_card = ctk.CTkFrame(
            scroll,
            corner_radius=10,
            fg_color=(COLOR_SUBTLE_LIGHT, COLOR_SUBTLE_DARK),
            border_width=1,
            border_color=(COLOR_BORDER_LIGHT, COLOR_BORDER_DARK),
        )
        modes_card.pack(fill="x", pady=(0, 12))

        ctk.CTkLabel(
            modes_card,
            text=i18n.get("opt_modes_title"),
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color=(COLOR_NAVY, "#93C5FD"),
        ).pack(anchor="w", padx=16, pady=(12, 4))

        ctk.CTkLabel(
            modes_card,
            text=i18n.get("opt_modes_desc"),
            font=ctk.CTkFont(size=12),
            justify="left",
            wraplength=920,
        ).pack(anchor="w", padx=16, pady=(0, 10))

        ctk.CTkButton(
            modes_card,
            text=i18n.get("btn_reset_baseline"),
            fg_color=COLOR_BRONZE,
            hover_color="#92400E",
            height=32,
            command=self._reset_current_job_baseline,
        ).pack(anchor="w", padx=16, pady=(0, 12))

        # Card 2: Conflict Policy, Deletions & Filters
        rules_card = ctk.CTkFrame(
            scroll,
            corner_radius=10,
            fg_color=(COLOR_SUBTLE_LIGHT, COLOR_SUBTLE_DARK),
            border_width=1,
            border_color=(COLOR_BORDER_LIGHT, COLOR_BORDER_DARK),
        )
        rules_card.pack(fill="x", pady=(0, 12))

        ctk.CTkLabel(
            rules_card,
            text=i18n.get("opt_rules_title"),
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color=(COLOR_NAVY, "#93C5FD"),
        ).pack(anchor="w", padx=16, pady=(12, 6))

        ctk.CTkCheckBox(
            rules_card,
            text=i18n.get("chk_delete_orphans"),
            variable=self.var_delete_orphans,
            command=self._save_current_job_from_ui,
        ).pack(anchor="w", padx=16, pady=6)

        ctk.CTkLabel(
            rules_card,
            text=i18n.get("lbl_conflict_policy"),
            font=ctk.CTkFont(size=12, weight="bold"),
        ).pack(anchor="w", padx=16, pady=(8, 4))

        conflict_frame = ctk.CTkFrame(rules_card, fg_color="transparent")
        conflict_frame.pack(fill="x", padx=16, pady=2)

        for c_val, c_key in [
            ("newer", "conflict_newer"),
            ("both", "conflict_both"),
            ("left", "conflict_left"),
            ("right", "conflict_right"),
        ]:
            ctk.CTkRadioButton(
                conflict_frame,
                text=i18n.get(c_key),
                variable=self.var_conflict_policy,
                value=c_val,
                command=self._save_current_job_from_ui,
            ).pack(anchor="w", pady=3)

        ctk.CTkLabel(
            rules_card,
            text=i18n.get("lbl_exclude"),
            font=ctk.CTkFont(size=12, weight="bold"),
        ).pack(anchor="w", padx=16, pady=(8, 4))

        ent_excl = ctk.CTkEntry(rules_card, textvariable=self.var_exclude, height=32)
        ent_excl.pack(fill="x", padx=16, pady=(0, 14))
        ent_excl.bind("<FocusOut>", lambda e: self._save_current_job_from_ui())

        # Card 3: Windows Startup & System Tray Integration
        sys_card = ctk.CTkFrame(
            scroll,
            corner_radius=10,
            fg_color=(COLOR_SUBTLE_LIGHT, COLOR_SUBTLE_DARK),
            border_width=1,
            border_color=(COLOR_BORDER_LIGHT, COLOR_BORDER_DARK),
        )
        sys_card.pack(fill="x", pady=(0, 12))

        ctk.CTkLabel(
            sys_card,
            text=i18n.get("opt_sys_title"),
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color=(COLOR_NAVY, "#93C5FD"),
        ).pack(anchor="w", padx=16, pady=(12, 8))

        ctk.CTkCheckBox(
            sys_card,
            text=i18n.get("chk_sys_startup"),
            variable=self.var_win_startup,
            command=self._on_toggle_windows_startup,
        ).pack(anchor="w", padx=16, pady=5)

        ctk.CTkCheckBox(
            sys_card,
            text=i18n.get("chk_sys_start_minimized"),
            variable=self.var_start_minimized,
            command=self._save_app_settings,
        ).pack(anchor="w", padx=16, pady=5)

        ctk.CTkCheckBox(
            sys_card,
            text=i18n.get("chk_sys_close_to_tray"),
            variable=self.var_close_to_tray,
            command=self._save_app_settings,
        ).pack(anchor="w", padx=16, pady=5)

        ctk.CTkCheckBox(
            sys_card,
            text=i18n.get("chk_sys_notifications"),
            variable=self.var_notifications,
            command=self._save_app_settings,
        ).pack(anchor="w", padx=16, pady=(5, 14))

    # =========================================================================
    # TAB 4: TELEMETRY CONSOLE (#0C1E36 STATORIS CONSOLE DARK NAVY)
    # =========================================================================
    def _build_tab_console(self):
        top_bar = ctk.CTkFrame(self.tab_console, fg_color="transparent")
        top_bar.pack(fill="x", padx=8, pady=(4, 6))

        ctk.CTkLabel(
            top_bar,
            text="REGISTRO PERICIAL DE OPERACIONES Y SINCRONIZACIÓN",
            font=ctk.CTkFont(size=12, weight="bold"),
        ).pack(side="left")

        ctk.CTkButton(
            top_bar,
            text="💾 Exportar Log...",
            width=130,
            height=28,
            fg_color=COLOR_SAPPHIRE,
            command=self._export_console_log,
        ).pack(side="right", padx=4)

        ctk.CTkButton(
            top_bar,
            text="🧹 Limpiar Consola",
            width=130,
            height=28,
            fg_color="#475569",
            command=self._clear_console_log,
        ).pack(side="right", padx=4)

        self.txt_console = ctk.CTkTextbox(
            self.tab_console,
            fg_color=COLOR_TERMINAL,
            text_color="#E2E8F0",
            font=ctk.CTkFont(family="Consolas", size=12),
            corner_radius=8,
        )
        self.txt_console.pack(fill="both", expand=True, padx=8, pady=(0, 8))

    # =========================================================================
    # BOTTOM STATUS BAR & PROGRESS
    # =========================================================================
    def _build_status_bar(self):
        self.status_bar = ctk.CTkFrame(
            self,
            height=42,
            corner_radius=0,
            fg_color=(COLOR_SURFACE_LIGHT, COLOR_SURFACE_DARK),
            border_width=1,
            border_color=(COLOR_BORDER_LIGHT, COLOR_BORDER_DARK),
        )
        self.status_bar.pack(fill="x", side="bottom")

        self.lbl_status = ctk.CTkLabel(
            self.status_bar,
            textvariable=self.var_status_text,
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=(COLOR_NAVY, "#F8FAFC"),
        )
        self.lbl_status.pack(side="left", padx=16, pady=8)

        self.progress_bar = ctk.CTkProgressBar(
            self.status_bar,
            width=280,
            height=12,
            progress_color=COLOR_SAPPHIRE,
        )
        self.progress_bar.set(0.0)
        self.progress_bar.pack(side="right", padx=16, pady=12)

        ctk.CTkLabel(
            self.status_bar,
            text=i18n.get("endorsed_by"),
            font=ctk.CTkFont(size=10),
            text_color=("gray45", "gray65"),
        ).pack(side="right", padx=12)

    # =========================================================================
    # DIRECTION & MODE HELPERS
    # =========================================================================
    def _get_direction_labels(self) -> List[str]:
        return [
            i18n.get("dir_bidirectional"),
            i18n.get("dir_left_to_right"),
            i18n.get("dir_right_to_left"),
        ]

    def _direction_code_to_label(self, code: str) -> str:
        mapping = {
            "bidirectional": i18n.get("dir_bidirectional"),
            "left_to_right": i18n.get("dir_left_to_right"),
            "right_to_left": i18n.get("dir_right_to_left"),
        }
        return mapping.get(code, i18n.get("dir_bidirectional"))

    def _direction_label_to_code(self, label: str) -> str:
        if "→" in label:
            return "left_to_right"
        if "←" in label:
            return "right_to_left"
        return "bidirectional"

    def _get_mode_labels(self) -> List[str]:
        return [
            i18n.get("mode_full"),
            i18n.get("mode_incremental"),
            i18n.get("mode_differential"),
        ]

    def _mode_code_to_label(self, code: str) -> str:
        mapping = {
            "full": i18n.get("mode_full"),
            "incremental": i18n.get("mode_incremental"),
            "differential": i18n.get("mode_differential"),
        }
        return mapping.get(code, i18n.get("mode_incremental"))

    def _mode_label_to_code(self, label: str) -> str:
        low = label.lower()
        if "completa" in low or "full" in low:
            return "full"
        if "diferencial" in low or "differential" in low:
            return "differential"
        return "incremental"

    # =========================================================================
    # JOBS SIDEBAR & JOB LOADING / SAVING
    # =========================================================================
    def _refresh_jobs_sidebar(self):
        for child in self.jobs_scroll.winfo_children():
            child.destroy()

        for job in self.jobs:
            is_selected = job.id == self.current_job.id
            card_bg = (COLOR_SAPPHIRE, COLOR_SAPPHIRE) if is_selected else ("#F1F5F9", "#162032")
            txt_col = "#FFFFFF" if is_selected else ("#0F172A", "#F8FAFC")
            sub_col = "#DBEAFE" if is_selected else ("#475569", "#94A3B8")

            jcard = ctk.CTkFrame(self.jobs_scroll, corner_radius=8, fg_color=card_bg)
            jcard.pack(fill="x", padx=2, pady=3)

            dir_icon = {"bidirectional": "⇄", "left_to_right": "→", "right_to_left": "←"}.get(
                job.direction, "⇄"
            )
            rt_tag = " 🟢RT" if job.realtime_enabled else ""
            sch_tag = " ⏱" if job.schedule_enabled else ""

            btn = ctk.CTkButton(
                jcard,
                text=f"{dir_icon}  {job.name}{rt_tag}{sch_tag}",
                anchor="w",
                fg_color="transparent",
                hover_color=COLOR_SAPPHIRE_HOVER if is_selected else ("#E2E8F0", "#1E293B"),
                text_color=txt_col,
                font=ctk.CTkFont(size=12, weight="bold"),
                height=30,
                command=lambda j=job: self._select_job(j),
            )
            btn.pack(fill="x", padx=4, pady=(4, 0))

            meta_txt = f"{len(job.pairs)} par(es) • {job.sync_mode.capitalize()} • {job.last_status}"
            lbl_meta = ctk.CTkLabel(
                jcard,
                text=meta_txt,
                font=ctk.CTkFont(size=10),
                text_color=sub_col,
                anchor="w",
            )
            lbl_meta.pack(fill="x", padx=12, pady=(0, 4))

    def _select_job(self, job: SyncJob):
        self._save_current_job_from_ui()
        self.current_job = job
        self.last_analysis = None
        self._load_job_into_ui(job)
        self._refresh_jobs_sidebar()
        self._clear_tree()

    def _load_job_into_ui(self, job: SyncJob):
        self.var_job_name.set(job.name)
        self.var_direction_label.set(self._direction_code_to_label(job.direction))
        self.var_sync_mode_label.set(self._mode_code_to_label(job.sync_mode))
        self.var_realtime_enabled.set(bool(job.realtime_enabled))
        self.var_realtime_debounce.set(str(job.realtime_debounce_sec or 3))
        self.var_remote_poll.set(str(job.remote_poll_sec or 0))

        self.var_sched_enabled.set(bool(job.schedule_enabled))
        self.var_sched_type.set(job.schedule_type or "interval")
        self.var_sched_interval.set(str(job.schedule_interval_min or 30))
        self.var_sched_time.set(job.schedule_time or "02:00")
        for d_code, bvar in self.vars_sched_days.items():
            bvar.set(d_code in (job.schedule_days or []))

        self.var_delete_orphans.set(bool(job.delete_orphans))
        self.var_conflict_policy.set(job.conflict_policy or "newer")
        self.var_exclude.set(job.exclude_patterns or "")

        self._render_folder_pairs()

    def _save_current_job_from_ui(self):
        job = self.current_job
        job.name = self.var_job_name.get().strip() or "Tarea de Sincronización"
        job.direction = self._direction_label_to_code(self.var_direction_label.get())
        job.sync_mode = self._mode_label_to_code(self.var_sync_mode_label.get())
        job.realtime_enabled = bool(self.var_realtime_enabled.get())
        try:
            job.realtime_debounce_sec = max(1, int(self.var_realtime_debounce.get().strip() or 3))
        except ValueError:
            job.realtime_debounce_sec = 3
        try:
            job.remote_poll_sec = max(0, int(self.var_remote_poll.get().strip() or 0))
        except ValueError:
            job.remote_poll_sec = 0

        job.schedule_enabled = bool(self.var_sched_enabled.get())
        job.schedule_type = self.var_sched_type.get()
        try:
            job.schedule_interval_min = max(1, int(self.var_sched_interval.get().strip() or 30))
        except ValueError:
            job.schedule_interval_min = 30
        job.schedule_time = self.var_sched_time.get().strip() or "02:00"
        job.schedule_days = [d for d, bv in self.vars_sched_days.items() if bv.get()]

        job.delete_orphans = bool(self.var_delete_orphans.get())
        job.conflict_policy = self.var_conflict_policy.get()
        job.exclude_patterns = self.var_exclude.get().strip()

        self.store.save_jobs(self.jobs)
        self._refresh_jobs_sidebar()

    def _create_new_job(self):
        new_j = SyncJob(
            name=f"Tarea de Sincronización {len(self.jobs) + 1}",
            direction="bidirectional",
            sync_mode="incremental",
        )
        new_j.ensure_default_pairs()
        self.jobs.append(new_j)
        self.store.save_jobs(self.jobs)
        self._select_job(new_j)

    def _duplicate_current_job(self):
        self._save_current_job_from_ui()
        dup = copy.deepcopy(self.current_job)
        dup.id = str(uuid.uuid4())[:8]
        dup.name = f"{self.current_job.name} (Copia)"
        for p in dup.pairs:
            p.id = str(uuid.uuid4())[:8]
        self.jobs.append(dup)
        self.store.save_jobs(self.jobs)
        self._select_job(dup)

    def _delete_current_job(self):
        if len(self.jobs) <= 1:
            messagebox.showwarning("Statoris Sync", "Debe existir al menos una tarea de sincronización.")
            return
        if not messagebox.askyesno("Eliminar Tarea", f"¿Desea eliminar la tarea '{self.current_job.name}'?"):
            return
        self.jobs = [j for j in self.jobs if j.id != self.current_job.id]
        self.current_job = self.jobs[0]
        self.store.save_jobs(self.jobs)
        self._load_job_into_ui(self.current_job)
        self._refresh_jobs_sidebar()
        self.realtime_service.reload_watches(self.jobs)

    # =========================================================================
    # MULTI-DIRECTORY PAIRS ACTIONS
    # =========================================================================
    def _add_folder_pair(self):
        idx = len(self.current_job.pairs) + 1
        new_pair = FolderPair(
            name=f"Dir {idx} ↔ Dir {idx} Remoto",
            enabled=True,
            left=EndpointConfig(protocol="local", path=""),
            right=EndpointConfig(protocol="local", path=""),
        )
        self.current_job.pairs.append(new_pair)
        self.store.save_jobs(self.jobs)
        self._render_folder_pairs()
        self._refresh_jobs_sidebar()

    def _remove_folder_pair(self, pair: FolderPair):
        if len(self.current_job.pairs) <= 1:
            return
        self.current_job.pairs = [p for p in self.current_job.pairs if p.id != pair.id]
        self.store.save_jobs(self.jobs)
        self._render_folder_pairs()
        self._refresh_jobs_sidebar()

    def _on_pair_enabled_toggle(self, pair: FolderPair, enabled: bool):
        pair.enabled = enabled
        self.store.save_jobs(self.jobs)
        self.realtime_service.reload_watches(self.jobs)

    def _on_pair_name_edit(self, pair: FolderPair, new_name: str):
        pair.name = new_name.strip() or "Par de Directorios"
        self.store.save_jobs(self.jobs)

    def _on_manual_path_entry(self, ep: EndpointConfig, raw_val: str):
        val = raw_val.strip()
        if ep.protocol == "local":
            ep.path = val
        else:
            # If user edited only the path or kept the URI, extract path if needed
            if "://" not in val:
                ep.path = val
        self.store.save_jobs(self.jobs)
        self.realtime_service.reload_watches(self.jobs)

    def _on_quick_proto_change(self, pair: FolderPair, side: str, proto_upper: str):
        ep = pair.left if side == "left" else pair.right
        new_proto = proto_upper.lower()
        ep.protocol = new_proto
        if new_proto in ("ftp", "ftps") and ep.port == 22:
            ep.port = 21
        elif new_proto in ("ssh", "scp") and ep.port == 21:
            ep.port = 22
        self.store.save_jobs(self.jobs)
        self._render_folder_pairs()
        if new_proto != "local" and not ep.host:
            self._open_endpoint_dialog(pair, side)

    def _pick_or_configure_endpoint(self, pair: FolderPair, side: str):
        ep = pair.left if side == "left" else pair.right
        if ep.protocol == "local":
            chosen = filedialog.askdirectory(initialdir=ep.path or None, title=f"Seleccionar Directorio ({pair.name})")
            if chosen:
                ep.path = chosen
                self.store.save_jobs(self.jobs)
                self._render_folder_pairs()
                self.realtime_service.reload_watches(self.jobs)
        else:
            self._open_endpoint_dialog(pair, side)

    def _open_endpoint_dialog(self, pair: FolderPair, side: str):
        ep = pair.left if side == "left" else pair.right
        side_label = "Origen (Izquierda)" if side == "left" else "Destino (Derecha / Remoto)"

        def _on_saved(updated_ep: EndpointConfig):
            if side == "left":
                pair.left = updated_ep
            else:
                pair.right = updated_ep
            self.store.save_jobs(self.jobs)
            self._render_folder_pairs()
            self.realtime_service.reload_watches(self.jobs)
            self._log(f"[{pair.name}] Configurado {side_label}: {updated_ep.display_uri()}", "INFO")

        EndpointConfigDialog(
            self,
            title=f"Configurar {side_label} — {pair.name}",
            endpoint=ep,
            on_save=_on_saved,
        )

    def _ensure_endpoint_ssh_passphrase(self, ep: EndpointConfig) -> bool:
        proto = (ep.protocol or "").lower()
        if proto in ("ssh", "scp") and ep.key_file and os.path.exists(ep.key_file):
            is_enc, _, comment = inspect_ssh_key_file(ep.key_file)
            if is_enc and not ep.key_passphrase and not ep.password:
                cname = comment or os.path.basename(ep.key_file)
                dlg = ctk.CTkInputDialog(
                    text=(
                        f'Authenticating with public key "{cname}"\n'
                        f'Passphrase for key "{cname}":\n\n'
                        f"Introduzca la Passphrase para descifrar la clave privada SSH:"
                    ),
                    title=f"Passphrase Clave SSH — {cname}",
                )
                entered = dlg.get_input()
                if entered:
                    ep.key_passphrase = entered
                    self.store.save_jobs(self.jobs)
                    self._render_folder_pairs()
                    return True
                return False
        return True

    def _ensure_job_ssh_passphrases(self, job: SyncJob) -> bool:
        for pair in job.pairs:
            if not pair.enabled:
                continue
            if not self._ensure_endpoint_ssh_passphrase(pair.left):
                return False
            if not self._ensure_endpoint_ssh_passphrase(pair.right):
                return False
        return True

    def _test_pair_endpoints(self, pair: FolderPair):
        if not self._ensure_endpoint_ssh_passphrase(pair.left):
            return
        if not self._ensure_endpoint_ssh_passphrase(pair.right):
            return
        self.var_status_text.set(f"Probando conexión para {pair.name}...")

        def _worker():
            t_l = create_transport(pair.left)
            ok_l, msg_l = t_l.test_connection()
            t_r = create_transport(pair.right)
            ok_r, msg_r = t_r.test_connection()

            def _report():
                self._log(f"[{pair.name}] Origen -> {msg_l}", "SUCCESS" if ok_l else "ERROR")
                self._log(f"[{pair.name}] Destino -> {msg_r}", "SUCCESS" if ok_r else "ERROR")
                if ok_l and ok_r:
                    self.var_status_text.set(f"✔ Conexión verificada en [{pair.name}]")
                    messagebox.showinfo(
                        "Conexión Verificada",
                        f"[{pair.name}]\n\n✔ ORIGEN: {msg_l}\n\n✔ DESTINO: {msg_r}",
                    )
                else:
                    self.var_status_text.set(f"✖ Error de conexión en [{pair.name}]")
                    messagebox.showerror(
                        "Error de Conexión",
                        f"[{pair.name}]\n\nORIGEN: {msg_l}\n\nDESTINO: {msg_r}",
                    )

            self.after(0, _report)

        threading.Thread(target=_worker, daemon=True).start()

    # =========================================================================
    # ANALYZE & SYNCHRONIZE EXECUTION
    # =========================================================================
    def _set_busy_ui(self, busy: bool):
        self.is_busy = busy
        self.btn_analyze.configure(state="disabled" if busy else "normal")
        self.btn_sync.configure(state="disabled" if busy else "normal")
        self.btn_stop.configure(state="normal" if busy else "disabled")

    def stop_active_operation(self):
        self.engine.request_stop()
        self.var_status_text.set(i18n.get("status_stopped"))
        self._log("Solicitud de parada enviada al motor de sincronización.", "WARN")

    def run_analyze_current_job(self):
        if self.is_busy:
            return
        self._save_current_job_from_ui()
        job = self.current_job
        if not self._ensure_job_ssh_passphrases(job):
            return
        self._set_busy_ui(True)
        self.progress_bar.set(0.15)
        self.var_status_text.set(i18n.get("status_analyzing"))
        self.tabview.set(i18n.get("tab_pairs"))

        def _worker():
            res = self.engine.analyze_job(job, log_cb=self._threadsafe_log)
            self.after(0, lambda: self._on_analysis_finished(res))

        threading.Thread(target=_worker, daemon=True).start()

    def _on_analysis_finished(self, res: AnalysisResult):
        self._set_busy_ui(False)
        self.progress_bar.set(1.0)
        self.last_analysis = res
        self._populate_tree(res)
        self.var_summary_counts.set(
            f"→ {res.to_copy_lr}  |  ← {res.to_copy_rl}  |  🗑 {res.to_delete}  |  "
            f"⚡ {res.conflicts}  |  = {res.identical}  ({format_size(res.total_transfer_bytes)})"
        )
        self.var_status_text.set(
            f"Análisis completado: {res.pending_count} cambios pendientes de sincronizar ({format_size(res.total_transfer_bytes)})."
        )

    def run_sync_current_job(self):
        if self.is_busy:
            return
        self._save_current_job_from_ui()
        job = self.current_job
        if not self._ensure_job_ssh_passphrases(job):
            return
        self._set_busy_ui(True)
        self.progress_bar.set(0.05)
        self.var_status_text.set(i18n.get("status_syncing"))
        self.realtime_service.mark_job_busy(job.id, True)

        def _prog(frac: float, msg: str):
            self.after(0, lambda: (self.progress_bar.set(frac), self.var_status_text.set(msg)))

        def _worker():
            try:
                res = self.engine.execute_sync(
                    job,
                    analysis=None,  # Perform fresh scan + sync
                    progress_cb=_prog,
                    log_cb=self._threadsafe_log,
                )
                self.after(0, lambda: self._on_sync_finished(job, res))
            finally:
                self.realtime_service.mark_job_busy(job.id, False)

        threading.Thread(target=_worker, daemon=True).start()

    def _on_sync_finished(self, job: SyncJob, res: AnalysisResult):
        self._set_busy_ui(False)
        self.last_analysis = res
        self.store.save_jobs(self.jobs)
        self._refresh_jobs_sidebar()
        self._populate_tree(res)
        self.var_summary_counts.set(
            f"→ {res.to_copy_lr}  |  ← {res.to_copy_rl}  |  🗑 {res.to_delete}  |  "
            f"⚡ {res.conflicts}  |  = {res.identical}"
        )
        self.var_status_text.set(f"✔ {job.name}: {job.last_status}")

    def sync_all_jobs(self):
        if self.is_busy:
            return
        self._save_current_job_from_ui()
        enabled_jobs = [j for j in self.jobs if j.enabled]
        if not enabled_jobs:
            return
        self._set_busy_ui(True)
        self.var_status_text.set("Sincronizando todas las tareas activas...")

        def _worker():
            for idx, job in enumerate(enabled_jobs):
                self.realtime_service.mark_job_busy(job.id, True)
                try:
                    self.engine.execute_sync(
                        job,
                        analysis=None,
                        progress_cb=lambda f, m: self.after(
                            0, lambda: (self.progress_bar.set(f), self.var_status_text.set(m))
                        ),
                        log_cb=self._threadsafe_log,
                    )
                finally:
                    self.realtime_service.mark_job_busy(job.id, False)
            self.after(
                0,
                lambda: (
                    self._set_busy_ui(False),
                    self.store.save_jobs(self.jobs),
                    self._refresh_jobs_sidebar(),
                    self.var_status_text.set("✔ Todas las tareas han sido sincronizadas."),
                ),
            )
            if self.settings.show_notifications:
                self.tray_service.notify("Statoris Sync", "Todas las tareas se han sincronizado correctamente.")

        threading.Thread(target=_worker, daemon=True).start()

    def _on_background_job_triggered(self, job_id: str, reason: str):
        """Called by RealtimeSyncService (watchdog) or SchedulerService."""
        target_job = next((j for j in self.jobs if j.id == job_id), None)
        if not target_job or self.is_busy:
            return

        self._threadsafe_log(f"⚡ Disparo automático [{target_job.name}]: {reason}", "INFO")

        def _worker():
            self.realtime_service.mark_job_busy(target_job.id, True)
            try:
                res = self.engine.execute_sync(
                    target_job,
                    analysis=None,
                    log_cb=self._threadsafe_log,
                )
                self.after(
                    0,
                    lambda: (
                        self.store.save_jobs(self.jobs),
                        self._refresh_jobs_sidebar(),
                        self.var_status_text.set(f"⚡ Auto-Sync [{target_job.name}]: {target_job.last_status}"),
                    ),
                )
                if self.settings.show_notifications and res.pending_count > 0:
                    self.tray_service.notify(
                        f"Statoris Sync — {target_job.name}",
                        f"{reason}: {res.pending_count} archivo(s) sincronizado(s).",
                    )
            finally:
                self.realtime_service.mark_job_busy(target_job.id, False)

        threading.Thread(target=_worker, daemon=True).start()

    # =========================================================================
    # COMPARISON TREE FILTERING & POPULATION
    # =========================================================================
    def _clear_tree(self):
        for item in self.tree.get_children():
            self.tree.delete(item)

    def _set_tree_filter(self, flt: str):
        self.current_filter = flt
        for b, code in [
            (self.btn_flt_all, "all"),
            (self.btn_flt_pending, "pending"),
            (self.btn_flt_conflicts, "conflicts"),
            (self.btn_flt_equal, "equal"),
        ]:
            b.configure(fg_color=COLOR_SAPPHIRE if flt == code else "#475569")
        if self.last_analysis:
            self._populate_tree(self.last_analysis)

    def _populate_tree(self, res: AnalysisResult):
        self._clear_tree()
        act_labels = {
            "copy_lr": i18n.get("act_copy_lr"),
            "copy_rl": i18n.get("act_copy_rl"),
            "delete_r": i18n.get("act_del_r"),
            "delete_l": i18n.get("act_del_l"),
            "conflict": i18n.get("act_conflict"),
            "equal": i18n.get("act_equal"),
            "skip": i18n.get("act_skip"),
        }

        for it in res.items:
            if self.current_filter == "pending" and it.action in ("equal", "skip"):
                continue
            if self.current_filter == "conflicts" and it.action != "conflict":
                continue
            if self.current_filter == "equal" and it.action != "equal":
                continue

            l_str = (
                f"{format_size(it.left_entry.size)} | {format_mtime(it.left_entry.mtime)}"
                if it.left_entry
                else "— (No existe)"
            )
            r_str = (
                f"{format_size(it.right_entry.size)} | {format_mtime(it.right_entry.mtime)}"
                if it.right_entry
                else "— (No existe)"
            )
            act_txt = act_labels.get(it.action, it.action)

            self.tree.insert(
                "",
                "end",
                values=(it.pair_name, it.rel_path, l_str, act_txt, r_str, it.reason),
                tags=(it.action,),
            )

    # =========================================================================
    # TOOLBAR & SYSTEM SETTINGS CALLBACKS
    # =========================================================================
    def _on_direction_changed(self, _val: str):
        self._save_current_job_from_ui()
        self._render_folder_pairs()

    def _on_sync_mode_changed(self, _val: str):
        self._save_current_job_from_ui()

    def _on_realtime_toggled(self):
        self._save_current_job_from_ui()
        self.realtime_service.reload_watches(self.jobs)
        self._update_realtime_badge()

    def _update_realtime_badge(self):
        any_rt = any(j.enabled and j.realtime_enabled for j in self.jobs)
        if any_rt:
            self.lbl_rt_status_pill.configure(
                text=i18n.get("status_realtime_active"),
                fg_color=COLOR_PASS,
                text_color="#FFFFFF",
            )
        else:
            self.lbl_rt_status_pill.configure(
                text=i18n.get("status_realtime_idle"),
                fg_color="#16365C",
                text_color="#E2E8F0",
            )

    def _reset_current_job_baseline(self):
        self.store.reset_job_state(self.current_job.id)
        self._log(
            f"Historial / Línea Base reiniciada para '{self.current_job.name}'. La próxima copia establecerá una nueva base.",
            "WARN",
        )
        messagebox.showinfo(
            "Línea Base Reiniciada",
            f"Se ha reiniciado la línea base de '{self.current_job.name}'.",
        )

    def _register_in_windows_task_scheduler(self):
        self._save_current_job_from_ui()
        ok, msg = SchedulerService.register_windows_schtask(self.current_job)
        self._log(msg, "SUCCESS" if ok else "WARN")
        if ok:
            messagebox.showinfo("Programador de Tareas de Windows", msg)
        else:
            messagebox.showwarning("Programador de Tareas de Windows", msg)

    def _on_toggle_windows_startup(self):
        enable = bool(self.var_win_startup.get())
        minimized = bool(self.var_start_minimized.get())
        ok = WindowsStartupManager.set_enabled(enable, start_minimized=minimized)
        if ok:
            self.settings.start_with_windows = enable
            self.store.save_settings(self.settings)
            state_str = "ACTIVADO" if enable else "DESACTIVADO"
            self._log(f"Inicio automático con Windows: {state_str}", "SUCCESS")

    def _toggle_startup_from_tray(self):
        new_val = not self.settings.start_with_windows
        self.var_win_startup.set(new_val)
        self._on_toggle_windows_startup()

    def _save_app_settings(self):
        self.settings.start_with_windows = bool(self.var_win_startup.get())
        self.settings.start_minimized = bool(self.var_start_minimized.get())
        self.settings.close_to_tray = bool(self.var_close_to_tray.get())
        self.settings.show_notifications = bool(self.var_notifications.get())
        self.store.save_settings(self.settings)
        if self.settings.start_with_windows:
            WindowsStartupManager.set_enabled(True, start_minimized=self.settings.start_minimized)

    # =========================================================================
    # SYSTEM TRAY (ICONTRAY) & WINDOW LIFECYCLE
    # =========================================================================
    def _on_window_close_button(self):
        self._save_current_job_from_ui()
        if self.settings.close_to_tray:
            self.minimize_to_tray()
        else:
            self.quit_completely()

    def minimize_to_tray(self):
        self.withdraw()
        if self.settings.show_notifications:
            self.tray_service.notify(
                "Statoris Sync en Segundo Plano",
                "La aplicación sigue activa en la bandeja del sistema (IconTray) vigilando sus sincronizaciones.",
            )

    def restore_from_tray(self):
        self.deiconify()
        self.lift()
        self.focus_force()

    def quit_completely(self):
        self._save_current_job_from_ui()
        self._save_app_settings()
        self.realtime_service.stop()
        self.scheduler_service.stop()
        self.tray_service.stop()
        self.destroy()
        sys.exit(0)

    # =========================================================================
    # LANGUAGE, THEME & LOGGING
    # =========================================================================
    def _on_language_selected(self, val: str):
        code = "es" if "Esp" in val else "en"
        self.settings.language = code
        self.store.save_settings(self.settings)
        i18n.set_language(code)

    def _on_theme_selected(self, val: str):
        mode = "Light" if "Light" in val else "Dark"
        self.settings.theme = mode
        self.store.save_settings(self.settings)
        ctk.set_appearance_mode(mode)
        self._style_treeview()

    def _refresh_i18n_labels(self):
        self.title(i18n.get("app_title"))
        self.lbl_badge.configure(text=i18n.get("brand_subtitle"))
        self.sw_header_startup.configure(text=i18n.get("chk_win_startup"))
        self.btn_header_tray.configure(text=i18n.get("btn_minimize_tray"))
        self.lbl_sidebar_title.configure(text=i18n.get("sidebar_title"))
        self.btn_new_job.configure(text=i18n.get("btn_new_job"))
        self.btn_dup_job.configure(text=i18n.get("btn_dup_job"))
        self.btn_del_job.configure(text=i18n.get("btn_del_job"))
        self.btn_sync_all_jobs.configure(text=i18n.get("btn_sync_all_jobs"))
        self.btn_analyze.configure(text=i18n.get("btn_analyze"))
        self.btn_sync.configure(text=i18n.get("btn_sync"))
        self.btn_stop.configure(text=i18n.get("btn_stop"))
        self.sw_toolbar_rt.configure(text=i18n.get("sw_realtime_quick"))
        self.lbl_dir_title.configure(text=i18n.get("lbl_direction"))
        self.lbl_mode_title.configure(text=i18n.get("lbl_sync_mode"))
        self.opt_direction.configure(values=self._get_direction_labels())
        self.opt_sync_mode.configure(values=self._get_mode_labels())
        self.var_direction_label.set(self._direction_code_to_label(self.current_job.direction))
        self.var_sync_mode_label.set(self._mode_code_to_label(self.current_job.sync_mode))
        self._update_realtime_badge()

    def _threadsafe_log(self, msg: str, level: str = "INFO"):
        self.after(0, lambda: self._log(msg, level))

    def _log(self, msg: str, level: str = "INFO"):
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        prefix = {"INFO": "[INFO]", "SUCCESS": "[OK]  ", "WARN": "[WARN]", "ERROR": "[FAIL]"}.get(
            level, "[INFO]"
        )
        line = f"{stamp} {prefix} {msg}\n"
        self.txt_console.insert("end", line)
        self.txt_console.see("end")

    def _clear_console_log(self):
        self.txt_console.delete("1.0", "end")

    def _export_console_log(self):
        fpath = filedialog.asksaveasfilename(
            title="Exportar Registro de Sincronización",
            defaultextension=".log",
            filetypes=[("Archivos Log", "*.log"), ("Texto", "*.txt")],
        )
        if fpath:
            content = self.txt_console.get("1.0", "end")
            with open(fpath, "w", encoding="utf-8") as f:
                f.write(content)
            messagebox.showinfo("Exportado", f"Registro guardado en:\n{fpath}")


if __name__ == "__main__":
    minimized_flag = "--minimized" in sys.argv or "--tray" in sys.argv
    run_job_id = None
    if "--run-job" in sys.argv:
        idx = sys.argv.index("--run-job")
        if idx + 1 < len(sys.argv):
            run_job_id = sys.argv[idx + 1]

    app = StatorisSyncApp(start_minimized_arg=minimized_flag, run_job_arg=run_job_id)
    app.mainloop()

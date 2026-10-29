"""
i18n.py - Internationalization system for Statoris Sync (Español & English).
Maintains Statoris corporate tone while remaining intuitive for all users.
"""

TRANSLATIONS = {
    "es": {
        "app_title": "Statoris Sync — Sincronización Inteligente Local y Remota",
        "brand_subtitle": "PRECISION SYNC ENGINE",
        "endorsed_by": "STATORIS es una marca comercial operada por CyberOps AI Engineering, S.L.",
        "lang_label": "Idioma:",
        "theme_label": "Tema:",
        "theme_light": "Executive Light",
        "theme_dark": "Dark Titanium",
        "btn_minimize_tray": "⬇ Bandeja (Tray)",
        "chk_win_startup": "Iniciar con Windows",
        # Sidebar
        "sidebar_title": "TAREAS DE SINCRONIZACIÓN",
        "btn_new_job": "+ Nueva Tarea",
        "btn_dup_job": "Duplicar",
        "btn_del_job": "Eliminar",
        "btn_sync_all_jobs": "⚡ Sincronizar Todas las Tareas",
        "btn_analyze_all_jobs": "🔍 Analizar Todas",
        # Toolbar
        "btn_analyze": "🔍 1. Analizar",
        "btn_sync": "⚡ 2. Sincronizar Ahora",
        "btn_stop": "⏹ Detener",
        "lbl_direction": "Dirección:",
        "dir_bidirectional": "⇄ Bidireccional (Ambos sentidos)",
        "dir_left_to_right": "→ Unidireccional (Origen → Destino)",
        "dir_right_to_left": "← Unidireccional (Destino ← Origen)",
        "lbl_sync_mode": "Tipo de Copia:",
        "mode_full": "Completa (Todo el contenido)",
        "mode_incremental": "Incremental (Desde última sinc.)",
        "mode_differential": "Diferencial (Desde última Completa)",
        "sw_realtime_quick": "Sincronización Activa (Tiempo Real)",
        # Tabs
        "tab_pairs": "📁 Directorios y Comparación de Archivos",
        "tab_automation": "⏱ Sincronización Activa y Programación",
        "tab_options": "⚙ Reglas, Filtros y Sistema",
        "tab_console": "🖥 Consola y Registro deActividad",
        # Pairs section
        "pairs_header": "PARES DE DIRECTORIOS A SINCRONIZAR (1 O MÚLTIPLES DIRECTORIOS)",
        "pairs_subheader": "Configura uno o varios pares (ej. Dir 1 → Dir 1 Remoto, Dir 2 → Dir 2 Remoto). Cada lado puede ser Local, SSH/SFTP, SCP o FTP.",
        "btn_add_pair": "+ Añadir Par de Directorios (Dir N ↔ Dir N Remoto)",
        "lbl_origin": "ORIGEN (IZQUIERDA)",
        "lbl_dest": "DESTINO (DERECHA / REMOTO)",
        "btn_browse_local": "📂 Examinar...",
        "btn_config_remote": "🌐 Configurar / Explorar Remoto...",
        "btn_test_conn": "🔌 Probar",
        "btn_remove_pair": "✕ Quitar",
        # Comparison tree
        "comp_header": "VISTA PREVIA Y TABLA COMPARATIVA DE ARCHIVOS",
        "filter_all": "Todos",
        "filter_pending": "Pendientes de Sincronizar",
        "filter_conflicts": "Conflictos",
        "filter_identical": "Idénticos",
        "col_pair": "Par de Directorios",
        "col_relpath": "Archivo / Ruta Relativa",
        "col_left_info": "Origen (Tamaño / Fecha)",
        "col_action": "Operación",
        "col_right_info": "Destino (Tamaño / Fecha)",
        "col_reason": "Estado / Motivo",
        # Action labels
        "act_copy_lr": "→ Copiar a Destino",
        "act_copy_rl": "← Copiar a Origen",
        "act_del_r": "🗑 Eliminar en Destino",
        "act_del_l": "🗑 Eliminar en Origen",
        "act_conflict": "⚡ Conflicto (Resolver)",
        "act_equal": "= Idéntico",
        "act_skip": "⏭ Omitido (Sin cambios en modo actual)",
        # Automation tab
        "rt_card_title": "⚡ SINCRONIZACIÓN ACTIVA EN TIEMPO REAL (DETECCIÓN INSTANTÁNEA)",
        "rt_card_desc": "Supervisa continuamente los directorios configurados y ejecuta la sincronización automáticamente en cuanto detecta cualquier archivo creado, modificado, movido o eliminado.",
        "rt_enable": "Activar Sincronización en Tiempo Real para esta tarea",
        "rt_debounce": "Tiempo de espera tras detectar cambios (segundos de estabilización):",
        "rt_remote_poll": "Verificar también cambios remotos periódicamente (segundos, 0 = solo local):",
        "sched_card_title": "📅 PROGRAMADOR AUTOMÁTICO DE SINCRONIZACIONES",
        "sched_card_desc": "Programa ejecuciones desatendidas por intervalo de tiempo, hora diaria, días de la semana o al iniciar el sistema.",
        "sched_enable": "Activar programación automática para esta tarea",
        "sched_type": "Modalidad de programación:",
        "sched_interval": "Por intervalo (Cada X minutos)",
        "sched_daily": "Diariamente a una hora fija",
        "sched_weekly": "Semanalmente en días seleccionados",
        "sched_startup": "Al iniciar Statoris Sync / Windows",
        "sched_every_min": "Ejecutar cada (minutos):",
        "sched_at_time": "Hora de ejecución (HH:MM, formato 24h):",
        "sched_days": "Días de la semana:",
        "day_mon": "Lun",
        "day_tue": "Mar",
        "day_wed": "Mié",
        "day_thu": "Jue",
        "day_fri": "Vie",
        "day_sat": "Sáb",
        "day_sun": "Dom",
        "btn_register_win_task": "📌 Registrar también en el Programador de Tareas de Windows (schtasks)",
        # Options tab
        "opt_modes_title": "📘 GUÍA Y GESTIÓN DE MODOS: COMPLETA, INCREMENTAL Y DIFERENCIAL",
        "opt_modes_desc": (
            "• COMPLETA (Full): Sincroniza todos los archivos de origen a destino y establece una nueva 'Línea Base Completa'.\n"
            "• INCREMENTAL: Transfiere únicamente los archivos creados o modificados desde la ÚLTIMA sincronización (de cualquier tipo). Es la más rápida para el día a día.\n"
            "• DIFERENCIAL: Transfiere todos los archivos creados o modificados desde la última sincronización COMPLETA (sin reiniciar la línea base completa)."
        ),
        "btn_reset_baseline": "🔄 Reiniciar Historial / Línea Base de esta Tarea",
        "opt_rules_title": "⚖ REGLAS DE CONFLICTO, ELIMINACIÓN Y FILTROS",
        "lbl_conflict_policy": "En caso de conflicto en modo Bidireccional (modificado en ambos lados):",
        "conflict_newer": "Conservar el archivo más reciente (por fecha de modificación)",
        "conflict_both": "Conservar ambos archivos (crear copia _CONFLICTO en el más antiguo)",
        "conflict_left": "Priorizar siempre Origen (Izquierda gana)",
        "conflict_right": "Priorizar siempre Destino (Derecha gana)",
        "chk_delete_orphans": "Propagar eliminaciones / Modo Espejo (eliminar en destino archivos borrados en origen)",
        "lbl_exclude": "Patrones de exclusión (separados por punto y coma ';'):",
        "opt_sys_title": "🖥 INTEGRACIÓN CON WINDOWS Y BANDEJA DEL SISTEMA (SYSTEM TRAY)",
        "chk_sys_startup": "Iniciar Statoris Sync automáticamente al iniciar sesión en Windows",
        "chk_sys_start_minimized": "Iniciar minimizado directamente en la bandeja del sistema (sin abrir ventana al arranque)",
        "chk_sys_close_to_tray": "Al pulsar cerrar (X), minimizar a la bandeja del sistema (IconTray) para seguir sincronizando sin molestar",
        "chk_sys_notifications": "Mostrar notificaciones emergentes de Windows al finalizar sincronizaciones automáticas",
        # Status bar
        "status_ready": "Listo — Seleccione Analizar o Sincronizar",
        "status_analyzing": "Analizando directorios...",
        "status_syncing": "Sincronizando archivos...",
        "status_completed": "Sincronización completada con éxito",
        "status_stopped": "Operación detenida por el usuario",
        "status_realtime_active": "🟢 Vigilancia Activa (Tiempo Real ON)",
        "status_realtime_idle": "⚪ Tiempo Real Desactivado",
        # Tray menu
        "tray_open": "Abrir Statoris Sync",
        "tray_sync_all": "Sincronizar Todas las Tareas Ahora",
        "tray_realtime": "Sincronización Activa (Tiempo Real)",
        "tray_startup": "Iniciar con Windows",
        "tray_exit": "Salir Completamente",
    },
    "en": {
        "app_title": "Statoris Sync — Intelligent Local & Remote Synchronization",
        "brand_subtitle": "PRECISION SYNC ENGINE",
        "endorsed_by": "STATORIS is a commercial brand operated by CyberOps AI Engineering, S.L.",
        "lang_label": "Language:",
        "theme_label": "Theme:",
        "theme_light": "Executive Light",
        "theme_dark": "Dark Titanium",
        "btn_minimize_tray": "⬇ Minimize to Tray",
        "chk_win_startup": "Start with Windows",
        # Sidebar
        "sidebar_title": "SYNCHRONIZATION JOBS",
        "btn_new_job": "+ New Job",
        "btn_dup_job": "Duplicate",
        "btn_del_job": "Delete",
        "btn_sync_all_jobs": "⚡ Synchronize All Jobs",
        "btn_analyze_all_jobs": "🔍 Analyze All",
        # Toolbar
        "btn_analyze": "🔍 1. Analyze",
        "btn_sync": "⚡ 2. Synchronize Now",
        "btn_stop": "⏹ Stop",
        "lbl_direction": "Direction:",
        "dir_bidirectional": "⇄ Bidirectional (Two-Way)",
        "dir_left_to_right": "→ One-Way (Left → Right)",
        "dir_right_to_left": "← One-Way (Right ← Left)",
        "lbl_sync_mode": "Sync Mode:",
        "mode_full": "Full (All Content)",
        "mode_incremental": "Incremental (Since last sync)",
        "mode_differential": "Differential (Since last Full)",
        "sw_realtime_quick": "Active Sync (Real-Time)",
        # Tabs
        "tab_pairs": "📁 Folder Pairs & File Comparison",
        "tab_automation": "⏱ Active Sync & Scheduling",
        "tab_options": "⚙ Rules, Filters & System",
        "tab_console": "🖥 Console & Activity Log",
        # Pairs section
        "pairs_header": "FOLDER PAIRS TO SYNCHRONIZE (1 OR MULTIPLE DIRECTORIES)",
        "pairs_subheader": "Configure one or multiple folder pairs (e.g., Dir 1 → Remote Dir 1, Dir 2 → Remote Dir 2). Each side can be Local, SSH/SFTP, SCP, or FTP.",
        "btn_add_pair": "+ Add Folder Pair (Dir N ↔ Remote Dir N)",
        "lbl_origin": "SOURCE (LEFT)",
        "lbl_dest": "TARGET (RIGHT / REMOTE)",
        "btn_browse_local": "📂 Browse...",
        "btn_config_remote": "🌐 Configure / Browse Remote...",
        "btn_test_conn": "🔌 Test",
        "btn_remove_pair": "✕ Remove",
        # Comparison tree
        "comp_header": "FILE PREVIEW & COMPARISON TABLE",
        "filter_all": "All",
        "filter_pending": "Pending Sync",
        "filter_conflicts": "Conflicts",
        "filter_identical": "Identical",
        "col_pair": "Folder Pair",
        "col_relpath": "File / Relative Path",
        "col_left_info": "Left (Size / Date)",
        "col_action": "Action",
        "col_right_info": "Right (Size / Date)",
        "col_reason": "Status / Reason",
        # Action labels
        "act_copy_lr": "→ Copy to Right",
        "act_copy_rl": "← Copy to Left",
        "act_del_r": "🗑 Delete on Right",
        "act_del_l": "🗑 Delete on Left",
        "act_conflict": "⚡ Conflict (Resolve)",
        "act_equal": "= Identical",
        "act_skip": "⏭ Skipped (Unchanged in current mode)",
        # Automation tab
        "rt_card_title": "⚡ ACTIVE REAL-TIME SYNCHRONIZATION (INSTANT DETECTION)",
        "rt_card_desc": "Continuously monitors configured directories and automatically runs synchronization as soon as any file is created, modified, moved, or deleted.",
        "rt_enable": "Enable Real-Time Active Sync for this job",
        "rt_debounce": "Wait time after detecting changes (debounce seconds):",
        "rt_remote_poll": "Also check remote changes periodically (seconds, 0 = local only):",
        "sched_card_title": "📅 AUTOMATIC SYNCHRONIZATION SCHEDULER",
        "sched_card_desc": "Schedule unattended runs by time interval, daily time, days of the week, or at system startup.",
        "sched_enable": "Enable automatic scheduling for this job",
        "sched_type": "Schedule type:",
        "sched_interval": "By interval (Every X minutes)",
        "sched_daily": "Daily at a fixed time",
        "sched_weekly": "Weekly on selected days",
        "sched_startup": "On Statoris Sync / Windows startup",
        "sched_every_min": "Run every (minutes):",
        "sched_at_time": "Execution time (HH:MM, 24h format):",
        "sched_days": "Days of the week:",
        "day_mon": "Mon",
        "day_tue": "Tue",
        "day_wed": "Wed",
        "day_thu": "Thu",
        "day_fri": "Fri",
        "day_sat": "Sat",
        "day_sun": "Sun",
        "btn_register_win_task": "📌 Also register in Windows Task Scheduler (schtasks)",
        # Options tab
        "opt_modes_title": "📘 SYNC MODES GUIDE: FULL, INCREMENTAL & DIFFERENTIAL",
        "opt_modes_desc": (
            "• FULL: Synchronizes all files from source to target and establishes a new 'Full Baseline'.\n"
            "• INCREMENTAL: Transfers only files created or modified since the LAST synchronization (of any type). Fastest for daily use.\n"
            "• DIFFERENTIAL: Transfers all files created or modified since the last FULL synchronization (without resetting the Full baseline)."
        ),
        "btn_reset_baseline": "🔄 Reset History / Baseline for this Job",
        "opt_rules_title": "⚖ CONFLICT, DELETION & FILTER RULES",
        "lbl_conflict_policy": "On conflict in Bidirectional mode (modified on both sides):",
        "conflict_newer": "Keep newest file (by modification timestamp)",
        "conflict_both": "Keep both files (create _CONFLICT copy for the older one)",
        "conflict_left": "Always prefer Left (Source wins)",
        "conflict_right": "Always prefer Right (Target wins)",
        "chk_delete_orphans": "Propagate deletions / Mirror Mode (delete target files removed from source)",
        "lbl_exclude": "Exclusion patterns (separated by semicolon ';'):",
        "opt_sys_title": "🖥 WINDOWS INTEGRATION & SYSTEM TRAY (ICONTRAY)",
        "chk_sys_startup": "Launch Statoris Sync automatically on Windows logon",
        "chk_sys_start_minimized": "Start minimized directly in System Tray (do not pop up window on boot)",
        "chk_sys_close_to_tray": "When clicking close (X), minimize to System Tray (IconTray) to keep syncing silently",
        "chk_sys_notifications": "Show Windows notifications when background synchronizations complete",
        # Status bar
        "status_ready": "Ready — Click Analyze or Synchronize",
        "status_analyzing": "Analyzing directories...",
        "status_syncing": "Synchronizing files...",
        "status_completed": "Synchronization completed successfully",
        "status_stopped": "Operation stopped by user",
        "status_realtime_active": "🟢 Active Watch (Real-Time ON)",
        "status_realtime_idle": "⚪ Real-Time Disabled",
        # Tray menu
        "tray_open": "Open Statoris Sync",
        "tray_sync_all": "Synchronize All Jobs Now",
        "tray_realtime": "Active Sync (Real-Time)",
        "tray_startup": "Start with Windows",
        "tray_exit": "Exit Completely",
    },
}

# Remove leading space if any
class I18nManager:
    def __init__(self, default_lang="es"):
        self.current_lang = default_lang
        self._listeners = []

    def get(self, key: str) -> str:
        lang_dict = TRANSLATIONS.get(self.current_lang, TRANSLATIONS["es"])
        return lang_dict.get(key, TRANSLATIONS["es"].get(key, key))

    def set_language(self, lang_code: str):
        if lang_code in TRANSLATIONS and lang_code != self.current_lang:
            self.current_lang = lang_code
            for cb in list(self._listeners):
                try:
                    cb()
                except Exception:
                    pass

    def subscribe(self, callback):
        if callback not in self._listeners:
            self._listeners.append(callback)


i18n = I18nManager("es")

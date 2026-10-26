"""
sync_engine.py - Core Analysis and Synchronization Engine for Statoris Sync.
Supports Multi-Pair folder synchronization, Directional & Bidirectional sync,
and Full (Completa), Incremental, and Differential modes with state manifest tracking.
"""

import os
import time
import tempfile
import posixpath
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Dict, Optional, Callable

from models import SyncJob, FolderPair, ConfigStore
from transports import create_transport, FileEntry


MTIME_TOLERANCE = 2.0  # 2-second FAT/SSH/FTP timestamp tolerance


@dataclass
class SyncActionItem:
    pair_id: str
    pair_name: str
    rel_path: str
    left_entry: Optional[FileEntry]
    right_entry: Optional[FileEntry]
    action: str  # "copy_lr", "copy_rl", "delete_l", "delete_r", "conflict", "equal", "skip"
    reason: str = ""

    @property
    def transfer_bytes(self) -> int:
        if self.action == "copy_lr" and self.left_entry:
            return self.left_entry.size
        if self.action == "copy_rl" and self.right_entry:
            return self.right_entry.size
        if self.action == "conflict":
            sz_l = self.left_entry.size if self.left_entry else 0
            sz_r = self.right_entry.size if self.right_entry else 0
            return max(sz_l, sz_r)
        return 0


@dataclass
class AnalysisResult:
    job_id: str
    job_name: str
    items: List[SyncActionItem] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    to_copy_lr: int = 0
    to_copy_rl: int = 0
    to_delete: int = 0
    conflicts: int = 0
    identical: int = 0
    skipped: int = 0
    total_transfer_bytes: int = 0

    def recompute_totals(self):
        self.to_copy_lr = sum(1 for i in self.items if i.action == "copy_lr")
        self.to_copy_rl = sum(1 for i in self.items if i.action == "copy_rl")
        self.to_delete = sum(1 for i in self.items if i.action in ("delete_l", "delete_r"))
        self.conflicts = sum(1 for i in self.items if i.action == "conflict")
        self.identical = sum(1 for i in self.items if i.action == "equal")
        self.skipped = sum(1 for i in self.items if i.action == "skip")
        self.total_transfer_bytes = sum(i.transfer_bytes for i in self.items)

    @property
    def pending_count(self) -> int:
        return self.to_copy_lr + self.to_copy_rl + self.to_delete + self.conflicts


def _files_same(a: Optional[FileEntry], b: Optional[FileEntry]) -> bool:
    if a is None or b is None:
        return False
    if a.size != b.size:
        return False
    return abs(a.mtime - b.mtime) <= MTIME_TOLERANCE


def _changed_since_baseline(entry: Optional[FileEntry], baseline_dict: Optional[dict]) -> bool:
    """Returns True if entry is new or modified compared to the recorded baseline snapshot."""
    if entry is None:
        return False
    if not baseline_dict:
        return True
    base_size = baseline_dict.get("size", -1)
    base_mtime = float(baseline_dict.get("mtime", 0.0))
    if entry.size != base_size:
        return True
    if (entry.mtime - base_mtime) > MTIME_TOLERANCE:
        return True
    return False


class SyncEngine:
    def __init__(self, store: ConfigStore):
        self.store = store
        self._stop_requested = False

    def request_stop(self):
        self._stop_requested = True

    def analyze_job(
        self,
        job: SyncJob,
        log_cb: Optional[Callable[[str, str], None]] = None,
    ) -> AnalysisResult:
        self._stop_requested = False
        result = AnalysisResult(job_id=job.id, job_name=job.name)

        def log(msg: str, level: str = "INFO"):
            if log_cb:
                log_cb(msg, level)

        enabled_pairs = [p for p in job.pairs if p.enabled]
        if not enabled_pairs:
            result.errors.append("No hay pares de directorios habilitados en esta tarea.")
            log("No hay pares de directorios habilitados en esta tarea.", "WARN")
            return result

        mode_names = {
            "full": "COMPLETA (Full)",
            "incremental": "INCREMENTAL",
            "differential": "DIFERENCIAL",
        }
        dir_names = {
            "bidirectional": "⇄ Bidireccional",
            "left_to_right": "→ Unidireccional (Origen → Destino)",
            "right_to_left": "← Unidireccional (Destino ← Origen)",
        }
        log(
            f"Iniciando análisis de '{job.name}' | Modo: {mode_names.get(job.sync_mode, job.sync_mode)} | "
            f"Dirección: {dir_names.get(job.direction, job.direction)}",
            "INFO",
        )

        for pair in enabled_pairs:
            if self._stop_requested:
                break
            if not pair.left.path and pair.left.protocol == "local":
                log(f"[{pair.name}] Ruta de Origen vacía, omitiendo par.", "WARN")
                continue
            if not pair.right.path and pair.right.protocol == "local":
                log(f"[{pair.name}] Ruta de Destino vacía, omitiendo par.", "WARN")
                continue

            log(
                f"Escaneando [{pair.name}]: {pair.left.display_uri()}  <==>  {pair.right.display_uri()}",
                "INFO",
            )
            t_left = create_transport(pair.left)
            t_right = create_transport(pair.right)
            try:
                t_left.connect()
                t_right.connect()
                left_files = t_left.scan_files(job.exclude_patterns)
                right_files = t_right.scan_files(job.exclude_patterns)
            except Exception as e:
                err_msg = f"[{pair.name}] Error de conexión o lectura: {e}"
                result.errors.append(err_msg)
                log(err_msg, "ERROR")
                continue
            finally:
                t_left.disconnect()
                t_right.disconnect()

            pair_state = self.store.get_pair_state(job.id, pair.id)
            last_sync_manifest: Dict[str, dict] = pair_state.get("last_sync_manifest", {}) or {}
            last_full_manifest: Dict[str, dict] = pair_state.get("last_full_manifest", {}) or {}

            # Select reference baseline according to Sync Mode:
            # - full: no baseline filter (considers all files)
            # - incremental: compares against last_sync_manifest (last sync of any type)
            # - differential: compares against last_full_manifest (last Full sync)
            if job.sync_mode == "incremental":
                active_baseline = last_sync_manifest
            elif job.sync_mode == "differential":
                active_baseline = last_full_manifest if last_full_manifest else last_sync_manifest
            else:
                active_baseline = {}

            all_paths = sorted(set(left_files.keys()) | set(right_files.keys()))
            for rel_p in all_paths:
                l_entry = left_files.get(rel_p)
                r_entry = right_files.get(rel_p)
                base_entry = active_baseline.get(rel_p)
                sync_hist_entry = last_sync_manifest.get(rel_p)

                item = self._decide_action(
                    job=job,
                    pair=pair,
                    rel_path=rel_p,
                    l_entry=l_entry,
                    r_entry=r_entry,
                    base_entry=base_entry,
                    sync_hist_entry=sync_hist_entry,
                )
                result.items.append(item)

        result.recompute_totals()
        log(
            f"Análisis finalizado: {result.to_copy_lr} copiar (→), {result.to_copy_rl} copiar (←), "
            f"{result.to_delete} eliminar, {result.conflicts} conflictos, {result.identical} idénticos.",
            "SUCCESS",
        )
        return result

    def _decide_action(
        self,
        job: SyncJob,
        pair: FolderPair,
        rel_path: str,
        l_entry: Optional[FileEntry],
        r_entry: Optional[FileEntry],
        base_entry: Optional[dict],
        sync_hist_entry: Optional[dict],
    ) -> SyncActionItem:
        direction = job.direction
        mode = job.sync_mode

        # 1. UNIDIRECTIONAL: LEFT -> RIGHT (Origen -> Destino)
        if direction == "left_to_right":
            if l_entry and not r_entry:
                if mode == "full" or not base_entry or _changed_since_baseline(l_entry, base_entry):
                    return SyncActionItem(
                        pair.id, pair.name, rel_path, l_entry, r_entry, "copy_lr",
                        f"Nuevo en Origen ({mode.capitalize()})"
                    )
                return SyncActionItem(
                    pair.id, pair.name, rel_path, l_entry, r_entry, "copy_lr",
                    "Falta en Destino"
                )
            elif not l_entry and r_entry:
                if job.delete_orphans:
                    return SyncActionItem(
                        pair.id, pair.name, rel_path, l_entry, r_entry, "delete_r",
                        "Eliminado en Origen (Modo Espejo)"
                    )
                return SyncActionItem(
                    pair.id, pair.name, rel_path, l_entry, r_entry, "skip",
                    "Solo en Destino (Conservar)"
                )
            else:
                # Both exist
                if mode == "full":
                    if _files_same(l_entry, r_entry):
                        return SyncActionItem(
                            pair.id, pair.name, rel_path, l_entry, r_entry, " copy_lr".strip(),
                            "Copia Completa (Sobrescribir / Verificar 1:1)"
                        )
                    return SyncActionItem(
                        pair.id, pair.name, rel_path, l_entry, r_entry, "copy_lr",
                        "Actualizado en Origen (Completa)"
                    )
                elif mode == "incremental":
                    if _files_same(l_entry, r_entry):
                        return SyncActionItem(
                            pair.id, pair.name, rel_path, l_entry, r_entry, "equal",
                            "Idéntico (Sin cambios desde última sinc.)"
                        )
                    if _changed_since_baseline(l_entry, base_entry) or not _files_same(l_entry, r_entry):
                        return SyncActionItem(
                            pair.id, pair.name, rel_path, l_entry, r_entry, "copy_lr",
                            "Modificado desde última sincronización (Incremental)"
                        )
                    return SyncActionItem(
                        pair.id, pair.name, rel_path, l_entry, r_entry, "equal", "Sin cambios"
                    )
                else:  # differential
                    if _changed_since_baseline(l_entry, base_entry) or not _files_same(l_entry, r_entry):
                        return SyncActionItem(
                            pair.id, pair.name, rel_path, l_entry, r_entry, "copy_lr",
                            "Cambiado desde última copia Completa (Diferencial)"
                        )
                    return SyncActionItem(
                        pair.id, pair.name, rel_path, l_entry, r_entry, "equal",
                        "Idéntico a Línea Base Completa"
                    )

        # 2. UNIDIRECTIONAL: RIGHT -> LEFT (Destino -> Origen)
        elif direction == "right_to_left":
            if r_entry and not l_entry:
                return SyncActionItem(
                    pair.id, pair.name, rel_path, l_entry, r_entry, "copy_rl",
                    f"Nuevo en Destino ({mode.capitalize()})"
                )
            elif l_entry and not r_entry:
                if job.delete_orphans:
                    return SyncActionItem(
                        pair.id, pair.name, rel_path, l_entry, r_entry, "delete_l",
                        "Eliminado en Destino (Modo Espejo)"
                    )
                return SyncActionItem(
                    pair.id, pair.name, rel_path, l_entry, r_entry, "skip",
                    "Solo en Origen (Conservar)"
                )
            else:
                if mode == "full":
                    return SyncActionItem(
                        pair.id, pair.name, rel_path, l_entry, r_entry, "copy_rl",
                        "Copia Completa (Destino → Origen)"
                    )
                elif mode == "incremental":
                    if _files_same(l_entry, r_entry):
                        return SyncActionItem(
                            pair.id, pair.name, rel_path, l_entry, r_entry, "equal",
                            "Idéntico"
                        )
                    return SyncActionItem(
                        pair.id, pair.name, rel_path, l_entry, r_entry, "copy_rl",
                        "Modificado desde última sincronización (Incremental)"
                    )
                else:  # differential
                    if _changed_since_baseline(r_entry, base_entry) or not _files_same(l_entry, r_entry):
                        return SyncActionItem(
                            pair.id, pair.name, rel_path, l_entry, r_entry, "copy_rl",
                            "Cambiado desde última copia Completa (Diferencial)"
                        )
                    return SyncActionItem(
                        pair.id, pair.name, rel_path, l_entry, r_entry, "equal",
                        "Idéntico a Línea Base Completa"
                    )

        # 3. BIDIRECTIONAL (Origen ⇄ Destino)
        else:
            if l_entry and not r_entry:
                # Did it exist in the last sync? If so, Right deleted it!
                if sync_hist_entry is not None and not _changed_since_baseline(l_entry, sync_hist_entry):
                    if job.delete_orphans:
                        return SyncActionItem(
                            pair.id, pair.name, rel_path, l_entry, r_entry, "delete_l",
                            "Fue eliminado en Destino (Propagar borrado ⇄)"
                        )
                return SyncActionItem(
                    pair.id, pair.name, rel_path, l_entry, r_entry, "copy_lr",
                    "Archivo nuevo en Origen (Propagar →)"
                )

            elif r_entry and not l_entry:
                # Did it exist in the last sync? If so, Left deleted it!
                if sync_hist_entry is not None and not _changed_since_baseline(r_entry, sync_hist_entry):
                    if job.delete_orphans:
                        return SyncActionItem(
                            pair.id, pair.name, rel_path, l_entry, r_entry, "delete_r",
                            "Fue eliminado en Origen (Propagar borrado ⇄)"
                        )
                return SyncActionItem(
                    pair.id, pair.name, rel_path, l_entry, r_entry, "copy_rl",
                    "Archivo nuevo en Destino (Propagar ←)"
                )

            else:
                # Exists on both sides
                if _files_same(l_entry, r_entry):
                    if mode == "differential" and _changed_since_baseline(l_entry, base_entry):
                        return SyncActionItem(
                            pair.id, pair.name, rel_path, l_entry, r_entry, "copy_lr",
                            "Cambiado respecto a Línea Base Completa (Diferencial)"
                        )
                    return SyncActionItem(
                        pair.id, pair.name, rel_path, l_entry, r_entry, "equal",
                        "Sincronizado e idéntico en ambos lados"
                    )

                l_changed = _changed_since_baseline(l_entry, sync_hist_entry)
                r_changed = _changed_since_baseline(r_entry, sync_hist_entry)

                if l_changed and not r_changed:
                    return SyncActionItem(
                        pair.id, pair.name, rel_path, l_entry, r_entry, "copy_lr",
                        "Modificado en Origen (Actualizar Destino →)"
                    )
                if r_changed and not l_changed:
                    return SyncActionItem(
                        pair.id, pair.name, rel_path, l_entry, r_entry, "copy_rl",
                        "Modificado en Destino (Actualizar Origen ←)"
                    )

                # Both modified since last sync (or no prior history and files differ)
                if sync_hist_entry is not None and l_changed and r_changed:
                    return SyncActionItem(
                        pair.id, pair.name, rel_path, l_entry, r_entry, "conflict",
                        f"Modificado en ambos lados (Política: {job.conflict_policy})"
                    )

                # No prior history: compare timestamps directly
                if (l_entry.mtime - r_entry.mtime) > MTIME_TOLERANCE:
                    return SyncActionItem(
                        pair.id, pair.name, rel_path, l_entry, r_entry, "copy_lr",
                        "Más reciente en Origen (→)"
                    )
                elif (r_entry.mtime - l_entry.mtime) > MTIME_TOLERANCE:
                    return SyncActionItem(
                        pair.id, pair.name, rel_path, l_entry, r_entry, "copy_rl",
                        "Más reciente en Destino (←)"
                    )
                else:
                    return SyncActionItem(
                        pair.id, pair.name, rel_path, l_entry, r_entry, "conflict",
                        "Misma fecha pero distinto tamaño"
                    )

    def execute_sync(
        self,
        job: SyncJob,
        analysis: Optional[AnalysisResult] = None,
        progress_cb: Optional[Callable[[float, str], None]] = None,
        log_cb: Optional[Callable[[str, str], None]] = None,
    ) -> AnalysisResult:
        self._stop_requested = False

        def log(msg: str, level: str = "INFO"):
            if log_cb:
                log_cb(msg, level)

        if analysis is None:
            analysis = self.analyze_job(job, log_cb=log_cb)

        actionable = [
            it for it in analysis.items if it.action in ("copy_lr", "copy_rl", "delete_l", "delete_r", "conflict")
        ]
        total_ops = len(actionable)
        if total_ops == 0:
            log(f"'{job.name}': Todos los archivos están al día. No se requieren transferencias.", "SUCCESS")
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            job.last_run = now_str
            job.last_status = "OK (Al día)"
            self._save_manifests_after_sync(job, analysis)
            if progress_cb:
                progress_cb(1.0, "Sincronización al día (0 cambios pendientes)")
            return analysis

        log(f"Iniciando ejecución de {total_ops} operaciones para '{job.name}'...", "INFO")

        # Group items by pair_id so we connect once per pair
        pair_map = {p.id: p for p in job.pairs}
        completed_ops = 0
        errors_count = 0

        for pair_id, pair in pair_map.items():
            if self._stop_requested:
                break
            pair_items = [it for it in actionable if it.pair_id == pair_id]
            if not pair_items:
                continue

            t_left = create_transport(pair.left)
            t_right = create_transport(pair.right)
            try:
                t_left.connect()
                t_right.connect()

                for item in pair_items:
                    if self._stop_requested:
                        log("Sincronización detenida por el usuario.", "WARN")
                        break

                    completed_ops += 1
                    frac = completed_ops / max(1, total_ops)
                    if progress_cb:
                        progress_cb(frac, f"[{pair.name}] Procesando {item.rel_path} ({completed_ops}/{total_ops})")

                    try:
                        self._execute_single_item(job, pair, t_left, t_right, item, log)
                    except Exception as ex:
                        errors_count += 1
                        err_txt = f"[{pair.name}] Error en '{item.rel_path}': {ex}"
                        analysis.errors.append(err_txt)
                        log(err_txt, "ERROR")

            except Exception as conn_ex:
                errors_count += 1
                err_txt = f"[{pair.name}] Fallo conectando transporte: {conn_ex}"
                analysis.errors.append(err_txt)
                log(err_txt, "ERROR")
            finally:
                t_left.disconnect()
                t_right.disconnect()

        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        job.last_run = now_str
        if self._stop_requested:
            job.last_status = "Detenido"
        elif errors_count > 0:
            job.last_status = f"Completado con {errors_count} errores"
        else:
            job.last_status = f"OK ({completed_ops} sincronizados)"
            self._save_manifests_after_sync(job, analysis)

        if progress_cb:
            progress_cb(1.0, f"Finalizado: {completed_ops} operaciones procesadas.")
        log(f"Sincronización de '{job.name}' finalizada -> {job.last_status}", "SUCCESS" if errors_count == 0 else "WARN")
        return analysis

    def _execute_single_item(self, job: SyncJob, pair: FolderPair, t_left, t_right, item: SyncActionItem, log):
        act = item.action
        rel_p = item.rel_path

        # Resolve conflict action first if action == "conflict"
        if act == "conflict":
            policy = job.conflict_policy
            if policy == "left":
                act = "copy_lr"
            elif policy == "right":
                act = "copy_rl"
            elif policy == "both":
                # Rename older side with _CONFLICTO suffix and copy newer over
                l_mt = item.left_entry.mtime if item.left_entry else 0
                r_mt = item.right_entry.mtime if item.right_entry else 0
                base_name, ext = posixpath.splitext(rel_p)
                stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                conflict_rel = f"{base_name}_CONFLICTO_{stamp}{ext}"
                if l_mt >= r_mt:
                    self._transfer_between(t_right, t_left, rel_p, conflict_rel, r_mt)
                    act = "copy_lr"
                else:
                    self._transfer_between(t_left, t_right, rel_p, conflict_rel, l_mt)
                    act = "copy_rl"
                log(f"[{pair.name}] ⚡ Conflicto conservado como '{conflict_rel}'", "WARN")
            else:  # "newer" default
                l_mt = item.left_entry.mtime if item.left_entry else 0
                r_mt = item.right_entry.mtime if item.right_entry else 0
                act = "copy_lr" if l_mt >= r_mt else "copy_rl"

        if act == "copy_lr":
            mtime = item.left_entry.mtime if item.left_entry else None
            self._transfer_between(t_left, t_right, rel_p, rel_p, mtime)
            log(f"[{pair.name}] → Copiado a Destino: {rel_p}", "INFO")

        elif act == "copy_rl":
            mtime = item.right_entry.mtime if item.right_entry else None
            self._transfer_between(t_right, t_left, rel_p, rel_p, mtime)
            log(f"[{pair.name}] ← Copiado a Origen: {rel_p}", "INFO")

        elif act == "delete_r":
            t_right.delete_file(rel_p)
            log(f"[{pair.name}] 🗑 Eliminado en Destino: {rel_p}", "WARN")

        elif act == "delete_l":
            t_left.delete_file(rel_p)
            log(f"[{pair.name}] 🗑 Eliminado en Origen: {rel_p}", "WARN")

    def _transfer_between(self, src_transport, dst_transport, src_rel: str, dst_rel: str, mtime: Optional[float]):
        """Transfers a file from src_transport to dst_transport (direct if local, or via temp staging)."""
        if src_transport.config.protocol == "local":
            local_src = os.path.join(
                src_transport.config.path, src_rel.replace("/", os.sep).lstrip(os.sep)
            )
            dst_transport.upload_file(local_src, dst_rel, preserve_mtime=mtime)
        elif dst_transport.config.protocol == "local":
            local_dst = os.path.join(
                dst_transport.config.path, dst_rel.replace("/", os.sep).lstrip(os.sep)
            )
            src_transport.download_file(src_rel, local_dst, preserve_mtime=mtime)
        else:
            # Remote-to-Remote transfer via temporary local file
            fd, tmp_path = tempfile.mkstemp(prefix="statoris_sync_")
            os.close(fd)
            try:
                src_transport.download_file(src_rel, tmp_path, preserve_mtime=mtime)
                dst_transport.upload_file(tmp_path, dst_rel, preserve_mtime=mtime)
            finally:
                if os.path.exists(tmp_path):
                    try:
                        os.remove(tmp_path)
                    except OSError:
                        pass

    def _save_manifests_after_sync(self, job: SyncJob, analysis: AnalysisResult):
        """Records the synchronized state per pair for Incremental, Differential, and Bidirectional tracking."""
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        is_full = job.sync_mode == "full"

        for pair in job.pairs:
            if not pair.enabled:
                continue
            pair_items = [it for it in analysis.items if it.pair_id == pair.id]
            manifest: Dict[str, dict] = {}
            for it in pair_items:
                if it.action in ("delete_l", "delete_r"):
                    continue
                chosen = None
                if it.action == "copy_lr":
                    chosen = it.left_entry
                elif it.action == "copy_rl":
                    chosen = it.right_entry
                else:
                    chosen = it.left_entry or it.right_entry
                if chosen:
                    manifest[it.rel_path] = {"size": chosen.size, "mtime": chosen.mtime}
            self.store.save_pair_state(
                job_id=job.id,
                pair_id=pair.id,
                manifest=manifest,
                is_full_sync=is_full,
                timestamp_str=now_str,
            )

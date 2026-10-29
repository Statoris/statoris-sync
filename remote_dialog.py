"""
remote_dialog.py - Interactive Endpoint Configuration & Remote Folder Browser Dialog.
Styled with the official Statoris Corporate Identity.
Allows any user to easily configure Local, SSH/SFTP, SCP, or FTP/FTPS endpoints,
configure SSH Private Keys (.ppk, .pem, id_rsa, id_ed25519) and their Passphrase,
test connection, and visually browse remote directories.
"""

import os
import threading
import posixpath
import tkinter as tk
from tkinter import filedialog
from typing import Callable, Optional
import customtkinter as ctk

from models import EndpointConfig
from transports import create_transport
from ssh_keys import inspect_ssh_key_file, load_ssh_pkey, SSHKeyPassphraseError


# Statoris Palette Constants (Light / Dark)
STATORIS_NAVY = "#0C2340"
STATORIS_SAPPHIRE = "#1D4ED8"
STATORIS_SAPPHIRE_HOVER = "#1E40AF"
STATORIS_BRONZE = "#B45309"
STATORIS_PASS = "#047857"
STATORIS_FAIL = "#B91C1C"


class EndpointConfigDialog(ctk.CTkToplevel):
    def __init__(
        self,
        parent,
        title: str,
        endpoint: EndpointConfig,
        on_save: Callable[[EndpointConfig], None],
    ):
        super().__init__(parent)
        self.title(title)
        self.geometry("740x720")
        self.minsize(680, 640)
        self.transient(parent)
        self.grab_set()

        # Clone endpoint
        self.ep = EndpointConfig.from_dict(endpoint.__dict__)
        self.on_save = on_save

        self.var_proto = tk.StringVar(value=(self.ep.protocol or "local").upper())
        self.var_path = tk.StringVar(value=self.ep.path or "")
        self.var_host = tk.StringVar(value=self.ep.host or "")
        self.var_port = tk.StringVar(value=str(self.ep.port or 22))
        self.var_user = tk.StringVar(value=self.ep.username or "")
        self.var_pass = tk.StringVar(value=self.ep.password or "")
        self.var_key = tk.StringVar(value=self.ep.key_file or "")
        self.var_key_passphrase = tk.StringVar(value=self.ep.key_passphrase or "")
        self.var_show_secrets = tk.BooleanVar(value=False)
        self.var_pasv = tk.BooleanVar(value=bool(self.ep.passive_ftp))
        self.var_key_info = tk.StringVar(value="")
        self.var_status = tk.StringVar(value="Configure los datos del directorio local o servidor remoto.")

        self._build_ui()
        self._on_proto_changed(self.var_proto.get())
        if self.var_key.get().strip():
            self._inspect_selected_key(prompt_if_needed=False)

    def _build_ui(self):
        # Top Banner
        banner = ctk.CTkFrame(self, fg_color=STATORIS_NAVY, corner_radius=0, height=56)
        banner.pack(fill="x")
        ctk.CTkLabel(
            banner,
            text="🌐 CONFIGURACIÓN DE CONEXIÓN, CLAVE SSH Y EXPLORADOR DE DIRECTORIOS",
            font=ctk.CTkFont(family="Segoe UI", size=14, weight="bold"),
            text_color="#FFFFFF",
        ).pack(side="left", padx=18, pady=14)

        body = ctk.CTkScrollableFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=16, pady=10)

        # Protocol Selector Card
        proto_card = ctk.CTkFrame(body, corner_radius=8)
        proto_card.pack(fill="x", pady=(0, 10))

        ctk.CTkLabel(
            proto_card,
            text="1. Seleccione el Protocolo de Conexión:",
            font=ctk.CTkFont(size=13, weight="bold"),
        ).pack(anchor="w", padx=14, pady=(10, 4))

        self.seg_proto = ctk.CTkSegmentedButton(
            proto_card,
            values=["LOCAL", "SSH", "SCP", "FTP", "FTPS"],
            variable=self.var_proto,
            command=self._on_proto_changed,
            selected_color=STATORIS_SAPPHIRE,
            selected_hover_color=STATORIS_SAPPHIRE_HOVER,
            height=34,
        )
        self.seg_proto.pack(fill="x", padx=14, pady=(0, 6))

        self.lbl_proto_hint = ctk.CTkLabel(
            proto_card,
            text="",
            font=ctk.CTkFont(size=11),
            text_color=("gray35", "gray70"),
        )
        self.lbl_proto_hint.pack(anchor="w", padx=14, pady=(0, 10))

        # Remote Server Credentials Frame
        self.remote_frame = ctk.CTkFrame(body, corner_radius=8)
        self.remote_frame.pack(fill="x", pady=(0, 10))

        ctk.CTkLabel(
            self.remote_frame,
            text="2. Credenciales del Servidor y Clave Privada SSH:",
            font=ctk.CTkFont(size=13, weight="bold"),
        ).grid(row=0, column=0, columnspan=4, sticky="w", padx=14, pady=(10, 6))

        # Row 1: Host & Port
        ctk.CTkLabel(self.remote_frame, text="Servidor (IP / Host):").grid(
            row=1, column=0, sticky="w", padx=14, pady=5
        )
        self.ent_host = ctk.CTkEntry(
            self.remote_frame,
            textvariable=self.var_host,
            placeholder_text="ej. 192.168.1.50 o sync.statoris.es",
            width=260,
        )
        self.ent_host.grid(row=1, column=1, sticky="ew", padx=6, pady=5)

        ctk.CTkLabel(self.remote_frame, text="Puerto:").grid(row=1, column=2, sticky="e", padx=6, pady=5)
        self.ent_port = ctk.CTkEntry(self.remote_frame, textvariable=self.var_port, width=90)
        self.ent_port.grid(row=1, column=3, sticky="w", padx=(0, 14), pady=5)

        # Row 2: Username & Server Password
        ctk.CTkLabel(self.remote_frame, text="Usuario:").grid(row=2, column=0, sticky="w", padx=14, pady=5)
        self.ent_user = ctk.CTkEntry(
            self.remote_frame, textvariable=self.var_user, placeholder_text="ej. admin-statoris / root / ubuntu"
        )
        self.ent_user.grid(row=2, column=1, sticky="ew", padx=6, pady=5)

        ctk.CTkLabel(self.remote_frame, text="Contraseña Login:").grid(row=2, column=2, sticky="e", padx=6, pady=5)
        self.ent_pass = ctk.CTkEntry(
            self.remote_frame,
            textvariable=self.var_pass,
            show="•",
            placeholder_text="(Si no usa clave SSH)",
            width=155,
        )
        self.ent_pass.grid(row=2, column=3, sticky="ew", padx=(0, 14), pady=5)

        # Row 3: SSH Private Key File (.ppk, .pem, id_rsa, id_ed25519)
        self.lbl_key = ctk.CTkLabel(
            self.remote_frame,
            text="Clave Privada SSH:",
            font=ctk.CTkFont(size=12, weight="bold"),
        )
        self.lbl_key.grid(row=3, column=0, sticky="w", padx=14, pady=5)
        self.ent_key = ctk.CTkEntry(
            self.remote_frame,
            textvariable=self.var_key,
            placeholder_text="Ruta a clave privada (.ppk, .pem, id_rsa, id_ed25519)",
        )
        self.ent_key.grid(row=3, column=1, columnspan=2, sticky="ew", padx=6, pady=5)
        self.ent_key.bind("<FocusOut>", lambda e: self._inspect_selected_key(prompt_if_needed=False))

        self.btn_key = ctk.CTkButton(
            self.remote_frame,
            text="📂 Elegir Clave...",
            width=125,
            command=self._browse_ssh_key,
            fg_color=STATORIS_SAPPHIRE,
            hover_color=STATORIS_SAPPHIRE_HOVER,
        )
        self.btn_key.grid(row=3, column=3, sticky="ew", padx=(0, 14), pady=5)

        # Row 4: SSH Key Passphrase (to decrypt encrypted private key)
        self.lbl_key_pass = ctk.CTkLabel(
            self.remote_frame,
            text="🔐 Passphrase Clave SSH:",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=(STATORIS_BRONZE, "#FBBF24"),
        )
        self.lbl_key_pass.grid(row=4, column=0, sticky="w", padx=14, pady=5)

        self.ent_key_pass = ctk.CTkEntry(
            self.remote_frame,
            textvariable=self.var_key_passphrase,
            show="•",
            placeholder_text='Contraseña para descifrar la clave privada SSH (ej. "admin-statoris")',
        )
        self.ent_key_pass.grid(row=4, column=1, columnspan=2, sticky="ew", padx=6, pady=5)

        self.btn_verify_key = ctk.CTkButton(
            self.remote_frame,
            text="🔑 Verificar Clave",
            width=125,
            fg_color=STATORIS_BRONZE,
            hover_color="#92400E",
            command=self._verify_key_and_passphrase,
        )
        self.btn_verify_key.grid(row=4, column=3, sticky="ew", padx=(0, 14), pady=5)

        # Row 5: Key inspection status + Show Passwords checkbox
        self.lbl_key_info = ctk.CTkLabel(
            self.remote_frame,
            textvariable=self.var_key_info,
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color=(STATORIS_SAPPHIRE, "#93C5FD"),
            anchor="w",
        )
        self.lbl_key_info.grid(row=5, column=0, columnspan=3, sticky="w", padx=14, pady=(2, 6))

        self.chk_show_secrets = ctk.CTkCheckBox(
            self.remote_frame,
            text="👁 Mostrar claves",
            variable=self.var_show_secrets,
            width=120,
            command=self._toggle_show_secrets,
        )
        self.chk_show_secrets.grid(row=5, column=3, sticky="w", padx=(0, 14), pady=(2, 6))

        # Row 6: FTP Passive checkbox
        self.chk_pasv = ctk.CTkCheckBox(
            self.remote_frame,
            text="Usar Modo Pasivo FTP (PASV - Recomendado tras Firewall/NAT)",
            variable=self.var_pasv,
        )
        self.chk_pasv.grid(row=6, column=0, columnspan=4, sticky="w", padx=14, pady=(4, 10))
        self.remote_frame.columnconfigure(1, weight=1)

        # Path & Browser Card
        path_card = ctk.CTkFrame(body, corner_radius=8)
        path_card.pack(fill="both", expand=True, pady=(0, 8))

        ctk.CTkLabel(
            path_card,
            text="3. Ruta del Directorio a Sincronizar:",
            font=ctk.CTkFont(size=13, weight="bold"),
        ).pack(anchor="w", padx=14, pady=(10, 4))

        path_row = ctk.CTkFrame(path_card, fg_color="transparent")
        path_row.pack(fill="x", padx=14, pady=4)

        self.ent_path = ctk.CTkEntry(
            path_row,
            textvariable=self.var_path,
            placeholder_text="C:\\Datos\\Carpeta1  o  /var/backups/carpeta1",
            height=34,
        )
        self.ent_path.pack(side="left", fill="x", expand=True, padx=(0, 8))

        self.btn_local_pick = ctk.CTkButton(
            path_row,
            text="📂 Elegir Carpeta Local...",
            width=160,
            height=34,
            fg_color=STATORIS_SAPPHIRE,
            hover_color=STATORIS_SAPPHIRE_HOVER,
            command=self._pick_local_dir,
        )
        self.btn_local_pick.pack(side="left")

        # Connection Test & Remote Folder Explorer
        action_row = ctk.CTkFrame(path_card, fg_color="transparent")
        action_row.pack(fill="x", padx=14, pady=6)

        self.btn_test = ctk.CTkButton(
            action_row,
            text="🔌 Probar Conexión",
            width=150,
            fg_color="#0F172A",
            hover_color="#1E293B",
            command=self._test_connection_async,
        )
        self.btn_test.pack(side="left", padx=(0, 8))

        self.btn_list_dirs = ctk.CTkButton(
            action_row,
            text="📂 Explorar Subdirectorios en Destino",
            width=230,
            fg_color=STATORIS_BRONZE,
            hover_color="#92400E",
            command=self._load_subdirectories_async,
        )
        self.btn_list_dirs.pack(side="left", padx=(0, 8))

        self.btn_up_dir = ctk.CTkButton(
            action_row,
            text="⬆ Subir Nivel (..)",
            width=120,
            fg_color="#475569",
            command=self._go_parent_dir,
        )
        self.btn_up_dir.pack(side="left")

        self.lbl_status = ctk.CTkLabel(
            path_card,
            textvariable=self.var_status,
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=STATORIS_SAPPHIRE,
            wraplength=640,
            justify="left",
        )
        self.lbl_status.pack(anchor="w", padx=14, pady=(2, 6))

        # Subdirectory buttons list
        self.dirs_scroll = ctk.CTkScrollableFrame(
            path_card, height=120, label_text="Subdirectorios Disponibles (Clic para entrar):"
        )
        self.dirs_scroll.pack(fill="both", expand=True, padx=14, pady=(0, 10))

        # Bottom Save / Cancel Bar
        footer = ctk.CTkFrame(self, height=54, corner_radius=0)
        footer.pack(fill="x", side="bottom")

        ctk.CTkButton(
            footer,
            text="Cancelar",
            width=110,
            fg_color="#64748B",
            hover_color="#475569",
            command=self.destroy,
        ).pack(side="right", padx=14, pady=10)

        ctk.CTkButton(
            footer,
            text="✔ Guardar Configuración de Directorio",
            width=260,
            fg_color=STATORIS_PASS,
            hover_color="#065F46",
            font=ctk.CTkFont(size=13, weight="bold"),
            command=self._save_and_close,
        ).pack(side="right", padx=4, pady=10)

    def _toggle_show_secrets(self):
        mask = "" if self.var_show_secrets.get() else "•"
        self.ent_pass.configure(show=mask)
        self.ent_key_pass.configure(show=mask)

    def _on_proto_changed(self, proto_str: str):
        p = proto_str.lower()
        hints = {
            "local": "Copia directa en disco local, unidades externas USB o carpetas compartidas en red Windows (\\\\servidor\\carpeta).",
            "ssh": "Sincronización segura por SSH / SFTP (Puerto 22). Soporta contraseña o Clave Privada SSH (.ppk / .pem / OpenSSH) con Passphrase.",
            "scp": "Transferencia directa mediante protocolo SCP sobre túnel SSH (Puerto 22). Soporta Clave Privada SSH con Passphrase.",
            "ftp": "Transferencia mediante servidor FTP estándar (Puerto predeterminado: 21).",
            "ftps": "Transferencia mediante servidor FTPS cifrado con TLS/SSL explícito (Puerto predeterminado: 21).",
        }
        self.lbl_proto_hint.configure(text=hints.get(p, ""))

        if p == "local":
            self.remote_frame.pack_forget()
            self.btn_local_pick.pack(side="left")
        else:
            self.remote_frame.pack(fill="x", pady=(0, 10), before=self.ent_path.master.master)
            self.btn_local_pick.pack_forget()
            curr_port = self.var_port.get().strip()
            if p in ("ftp", "ftps") and curr_port in ("", "22"):
                self.var_port.set("21")
            elif p in ("ssh", "scp") and curr_port in ("", "21"):
                self.var_port.set("22")

            if p in ("ssh", "scp"):
                self.lbl_key.grid()
                self.ent_key.grid()
                self.btn_key.grid()
                self.lbl_key_pass.grid()
                self.ent_key_pass.grid()
                self.btn_verify_key.grid()
                self.lbl_key_info.grid()
                self.chk_pasv.grid_remove()
            else:
                self.lbl_key.grid_remove()
                self.ent_key.grid_remove()
                self.btn_key.grid_remove()
                self.lbl_key_pass.grid_remove()
                self.ent_key_pass.grid_remove()
                self.btn_verify_key.grid_remove()
                self.lbl_key_info.grid_remove()
                self.chk_pasv.grid()

    def _pick_local_dir(self):
        folder = filedialog.askdirectory(initialdir=self.var_path.get() or None)
        if folder:
            self.var_path.set(folder)
            self._load_subdirectories_async()

    def _browse_ssh_key(self):
        fpath = filedialog.askopenfilename(
            title="Seleccionar Clave Privada SSH (.ppk, .pem, OpenSSH)",
            filetypes=[
                ("Claves Privadas SSH", "*.ppk *.pem *.key *id_rsa* *id_ed25519* *id_ecdsa*"),
                ("PuTTY Private Key (.ppk)", "*.ppk"),
                ("OpenSSH / PEM (.pem, .key)", "*.pem *.key"),
                ("Todos los archivos", "*.*"),
            ],
        )
        if fpath:
            self.var_key.set(fpath)
            self._inspect_selected_key(prompt_if_needed=True)

    def _inspect_selected_key(self, prompt_if_needed: bool = False):
        kpath = self.var_key.get().strip()
        if not kpath or not os.path.exists(kpath):
            self.var_key_info.set("")
            return

        is_enc, ktype, comment = inspect_ssh_key_file(kpath)
        label_name = f'"{comment}"' if comment else os.path.basename(kpath)
        if is_enc:
            self.var_key_info.set(
                f"🔐 Clave detectada: {label_name} [{ktype} - CIFRADA]. Requiere 'Passphrase Clave SSH'."
            )
            self.lbl_key_info.configure(text_color=(STATORIS_BRONZE, "#FBBF24"))
            self.ent_key_pass.focus_set()
            if prompt_if_needed and not self.var_key_passphrase.get():
                self._prompt_passphrase_modal(comment or os.path.basename(kpath))
        else:
            self.var_key_info.set(f"✔ Clave detectada: {label_name} [{ktype} - Sin cifrado adicional].")
            self.lbl_key_info.configure(text_color=STATORIS_PASS)

    def _prompt_passphrase_modal(self, key_comment: str) -> Optional[str]:
        dialog = ctk.CTkInputDialog(
            text=f'Authenticating with public key "{key_comment}"\nPassphrase for key "{key_comment}":\n\nIntroduzca la Passphrase para descifrar la clave privada SSH:',
            title=f'Passphrase Clave SSH — {key_comment}',
        )
        entered = dialog.get_input()
        if entered is not None and entered != "":
            self.var_key_passphrase.set(entered)
            self._verify_key_and_passphrase()
            return entered
        return None

    def _verify_key_and_passphrase(self) -> bool:
        kpath = self.var_key.get().strip()
        if not kpath:
            self.var_status.set("✖ Seleccione primero un archivo de Clave Privada SSH.")
            self.lbl_status.configure(text_color=STATORIS_FAIL)
            return False
        if not os.path.exists(kpath):
            self.var_status.set(f"✖ No existe el archivo de clave: {kpath}")
            self.lbl_status.configure(text_color=STATORIS_FAIL)
            return False

        passphrase = self.var_key_passphrase.get() or self.var_pass.get() or None
        try:
            pkey = load_ssh_pkey(kpath, passphrase=passphrase)
            _, ktype, comment = inspect_ssh_key_file(kpath)
            cname = comment or os.path.basename(kpath)
            self.var_key_info.set(f'✔ Clave "{cname}" ({pkey.get_name()}) descifrada y verificada correctamente.')
            self.lbl_key_info.configure(text_color=STATORIS_PASS)
            self.var_status.set(f'✔ Clave privada SSH "{cname}" descifrada con éxito.')
            self.lbl_status.configure(text_color=STATORIS_PASS)
            return True
        except SSHKeyPassphraseError as e:
            self.var_key_info.set(f"✖ {e}")
            self.lbl_key_info.configure(text_color=STATORIS_FAIL)
            self.var_status.set(f"✖ {e}")
            self.lbl_status.configure(text_color=STATORIS_FAIL)
            return False
        except Exception as e:
            self.var_status.set(f"✖ Error al leer la clave SSH: {e}")
            self.lbl_status.configure(text_color=STATORIS_FAIL)
            return False

    def _build_temp_config(self) -> EndpointConfig:
        proto = self.var_proto.get().lower()
        default_port = 21 if proto in ("ftp", "ftps") else 22
        try:
            port_num = int(self.var_port.get().strip() or default_port)
        except ValueError:
            port_num = default_port

        return EndpointConfig(
            protocol=proto,
            path=self.var_path.get().strip() or ("/" if proto != "local" else ""),
            host=self.var_host.get().strip(),
            port=port_num,
            username=self.var_user.get().strip(),
            password=self.var_pass.get(),
            key_file=self.var_key.get().strip(),
            key_passphrase=self.var_key_passphrase.get(),
            passive_ftp=bool(self.var_pasv.get()),
        )

    def _ensure_key_ready_before_connect(self) -> bool:
        proto = self.var_proto.get().lower()
        kpath = self.var_key.get().strip()
        if proto in ("ssh", "scp") and kpath and os.path.exists(kpath):
            is_enc, _, comment = inspect_ssh_key_file(kpath)
            if is_enc and not self.var_key_passphrase.get() and not self.var_pass.get():
                entered = self._prompt_passphrase_modal(comment or os.path.basename(kpath))
                if not entered:
                    return False
        return True

    def _test_connection_async(self):
        if not self._ensure_key_ready_before_connect():
            return
        cfg = self._build_temp_config()
        self.var_status.set("⏳ Probando conexión...")
        self.lbl_status.configure(text_color=STATORIS_BRONZE)

        def _worker():
            t = create_transport(cfg)
            ok, msg = t.test_connection()
            self.after(
                0,
                lambda: (
                    self.var_status.set(f"{'✔ ' if ok else '✖ '}{msg}"),
                    self.lbl_status.configure(text_color=STATORIS_PASS if ok else STATORIS_FAIL),
                ),
            )

        threading.Thread(target=_worker, daemon=True).start()

    def _load_subdirectories_async(self):
        if not self._ensure_key_ready_before_connect():
            return
        cfg = self._build_temp_config()
        self.var_status.set("⏳ Consultando subdirectorios...")
        self.lbl_status.configure(text_color=STATORIS_BRONZE)

        def _worker():
            t = create_transport(cfg)
            dirs = t.list_directories(cfg.path)
            self.after(0, lambda: self._populate_dirs(dirs, cfg))

        threading.Thread(target=_worker, daemon=True).start()

    def _populate_dirs(self, dirs, cfg: EndpointConfig):
        for child in self.dirs_scroll.winfo_children():
            child.destroy()

        if not dirs:
            self.var_status.set(f"Directorio '{cfg.path}' verificado (sin subcarpetas adicionales o vacío).")
            self.lbl_status.configure(text_color=STATORIS_PASS)
            return

        self.var_status.set(f"✔ Se encontraron {len(dirs)} subdirectorios en '{cfg.path}'.")
        self.lbl_status.configure(text_color=STATORIS_PASS)

        for dname in dirs:
            btn = ctk.CTkButton(
                self.dirs_scroll,
                text=f"📁  {dname}",
                anchor="w",
                fg_color="transparent",
                text_color=("#0F172A", "#F8FAFC"),
                hover_color=("#E2E8F0", "#1E293B"),
                height=28,
                command=lambda n=dname: self._enter_subdir(n),
            )
            btn.pack(fill="x", padx=4, pady=1)

    def _enter_subdir(self, subdir_name: str):
        proto = self.var_proto.get().lower()
        curr = self.var_path.get().strip()
        if proto == "local":
            new_p = os.path.join(curr or "C:\\", subdir_name)
        else:
            new_p = posixpath.join(curr or "/", subdir_name)
        self.var_path.set(new_p)
        self._load_subdirectories_async()

    def _go_parent_dir(self):
        proto = self.var_proto.get().lower()
        curr = self.var_path.get().strip()
        if not curr:
            return
        if proto == "local":
            parent = os.path.dirname(curr.rstrip("\\/"))
            if parent:
                self.var_path.set(parent)
        else:
            parent = posixpath.dirname(curr.rstrip("/")) or "/"
            self.var_path.set(parent)
        self._load_subdirectories_async()

    def _save_and_close(self):
        if not self._ensure_key_ready_before_connect():
            return
        cfg = self._build_temp_config()
        self.on_save(cfg)
        self.destroy()

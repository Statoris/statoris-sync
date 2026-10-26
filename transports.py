"""
transports.py - Unified Storage Transport layer for Statoris Sync.
Supports Local/SMB Direct Copy, SSH/SFTP, SCP, and FTP/FTPS with a consistent interface.
"""

import os
import stat
import time
import shutil
import fnmatch
import ftplib
import posixpath
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Tuple, Optional

import paramiko
from scp import SCPClient

from models import EndpointConfig
from ssh_keys import load_ssh_pkey, SSHKeyPassphraseError


@dataclass
class FileEntry:
    rel_path: str  # Always normalized with forward slashes '/'
    size: int
    mtime: float   # Unix timestamp (seconds)


def matches_exclude(rel_path: str, exclude_patterns_str: str) -> bool:
    if not exclude_patterns_str:
        return False
    patterns = [p.strip() for p in exclude_patterns_str.replace(",", ";").split(";") if p.strip()]
    filename = posixpath.basename(rel_path)
    parts = rel_path.split("/")
    for pat in patterns:
        if fnmatch.fnmatch(filename.lower(), pat.lower()) or fnmatch.fnmatch(rel_path.lower(), pat.lower()):
            return True
        for part in parts:
            if fnmatch.fnmatch(part.lower(), pat.lower()):
                return True
    return False


class BaseTransport:
    def __init__(self, config: EndpointConfig):
        self.config = config

    def connect(self):
        pass

    def disconnect(self):
        pass

    def test_connection(self) -> Tuple[bool, str]:
        raise NotImplementedError

    def list_directories(self, path: Optional[str] = None) -> List[str]:
        raise NotImplementedError

    def scan_files(self, exclude_patterns: str = "") -> Dict[str, FileEntry]:
        raise NotImplementedError

    def download_file(self, rel_path: str, local_dest: str, preserve_mtime: Optional[float] = None):
        raise NotImplementedError

    def upload_file(self, local_src: str, rel_path: str, preserve_mtime: Optional[float] = None):
        raise NotImplementedError

    def delete_file(self, rel_path: str):
        raise NotImplementedError


class LocalTransport(BaseTransport):
    """Direct local / UNC / SMB network share file operations."""

    def connect(self):
        if self.config.path and not os.path.exists(self.config.path):
            os.makedirs(self.config.path, exist_ok=True)

    def test_connection(self) -> Tuple[bool, str]:
        p = (self.config.path or "").strip()
        if not p:
            return False, "Ruta local vacía."
        try:
            if os.path.exists(p):
                if os.path.isdir(p):
                    return True, f"Directorio local accesible: {p}"
                return False, f"La ruta existe pero no es un directorio: {p}"
            else:
                os.makedirs(p, exist_ok=True)
                return True, f"Directorio local creado y verificado: {p}"
        except Exception as e:
            return False, f"Error accediendo a ruta local: {e}"

    def list_directories(self, path: Optional[str] = None) -> List[str]:
        target = path or self.config.path or "C:\\"
        if not os.path.exists(target):
            return []
        result = []
        try:
            for entry in os.scandir(target):
                if entry.is_dir():
                    result.append(entry.name)
        except Exception:
            pass
        return sorted(result)

    def _full_path(self, rel_path: str) -> str:
        norm = rel_path.replace("/", os.sep).lstrip(os.sep)
        return os.path.join(self.config.path, norm)

    def scan_files(self, exclude_patterns: str = "") -> Dict[str, FileEntry]:
        base = self.config.path
        entries: Dict[str, FileEntry] = {}
        if not base or not os.path.exists(base):
            return entries

        for root, dirs, files in os.walk(base):
            rel_root = os.path.relpath(root, base).replace("\\", "/")
            if rel_root == ".":
                rel_root = ""
            # Filter directories in-place
            dirs[:] = [
                d
                for d in dirs
                if not matches_exclude(f"{rel_root}/{d}".lstrip("/"), exclude_patterns)
            ]
            for fname in files:
                rel_p = f"{rel_root}/{fname}".lstrip("/")
                if matches_exclude(rel_p, exclude_patterns):
                    continue
                full_p = os.path.join(root, fname)
                try:
                    st = os.stat(full_p)
                    entries[rel_p] = FileEntry(rel_path=rel_p, size=st.st_size, mtime=st.st_mtime)
                except OSError:
                    continue
        return entries

    def download_file(self, rel_path: str, local_dest: str, preserve_mtime: Optional[float] = None):
        src = self._full_path(rel_path)
        os.makedirs(os.path.dirname(local_dest), exist_ok=True)
        shutil.copy2(src, local_dest)
        if preserve_mtime is not None:
            try:
                os.utime(local_dest, (preserve_mtime, preserve_mtime))
            except OSError:
                pass

    def upload_file(self, local_src: str, rel_path: str, preserve_mtime: Optional[float] = None):
        dst = self._full_path(rel_path)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(local_src, dst)
        if preserve_mtime is not None:
            try:
                os.utime(dst, (preserve_mtime, preserve_mtime))
            except OSError:
                pass

    def delete_file(self, rel_path: str):
        target = self._full_path(rel_path)
        if os.path.exists(target):
            os.remove(target)


class SSHTransport(BaseTransport):
    """SSH / SFTP transport powered by Paramiko."""

    def __init__(self, config: EndpointConfig):
        super().__init__(config)
        self.ssh: Optional[paramiko.SSHClient] = None
        self.sftp: Optional[paramiko.SFTPClient] = None

    def connect(self):
        if self.sftp is not None:
            return
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        kwargs = {
            "hostname": self.config.host.strip(),
            "port": int(self.config.port or 22),
            "username": self.config.username.strip(),
            "timeout": 12,
        }
        effective_passphrase = (self.config.key_passphrase or self.config.password or "").strip() or None
        if self.config.key_file and os.path.exists(self.config.key_file):
            pkey = load_ssh_pkey(self.config.key_file, passphrase=effective_passphrase)
            kwargs["pkey"] = pkey
        if effective_passphrase:
            kwargs["passphrase"] = effective_passphrase
        if self.config.password:
            kwargs["password"] = self.config.password
        client.connect(**kwargs)
        self.ssh = client
        self.sftp = client.open_sftp()
        if self.config.path:
            self._ensure_remote_dir(self._norm_remote(self.config.path))

    def disconnect(self):
        if self.sftp:
            try:
                self.sftp.close()
            except Exception:
                pass
            self.sftp = None
        if self.ssh:
            try:
                self.ssh.close()
            except Exception:
                pass
            self.ssh = None

    def _norm_remote(self, path_str: str) -> str:
        p = (path_str or "/").replace("\\", "/").strip()
        if not p.startswith("/") and not (len(p) >= 2 and p[1] == ":"):
            p = "/" + p
        return p.rstrip("/") or "/"

    def _remote_full(self, rel_path: str) -> str:
        base = self._norm_remote(self.config.path)
        return posixpath.join(base, rel_path.lstrip("/"))

    def _ensure_remote_dir(self, remote_dir: str):
        if not remote_dir or remote_dir == "/":
            return
        parts = remote_dir.split("/")
        curr = ""
        for part in parts:
            if not part:
                curr = "/"
                continue
            curr = posixpath.join(curr, part) if curr else part
            try:
                self.sftp.stat(curr)
            except IOError:
                try:
                    self.sftp.mkdir(curr)
                except IOError:
                    pass

    def test_connection(self) -> Tuple[bool, str]:
        if not self.config.host:
            return False, " Especifique el servidor (Host / IP) SSH."
        try:
            self.connect()
            base = self._norm_remote(self.config.path)
            self.sftp.listdir(base)
            return True, f"Conexión SSH/SFTP exitosa a {self.config.host}:{self.config.port} ({base})"
        except Exception as e:
            return False, f"Error SSH/SFTP: {e}"
        finally:
            self.disconnect()

    def list_directories(self, path: Optional[str] = None) -> List[str]:
        was_connected = self.sftp is not None
        try:
            self.connect()
            target = self._norm_remote(path or self.config.path or "/")
            dirs = []
            for attr in self.sftp.listdir_attr(target):
                if attr.st_mode and stat.S_ISDIR(attr.st_mode):
                    if attr.filename not in (".", ".."):
                        dirs.append(attr.filename)
            return sorted(dirs)
        except Exception:
            return []
        finally:
            if not was_connected:
                self.disconnect()

    def scan_files(self, exclude_patterns: str = "") -> Dict[str, FileEntry]:
        self.connect()
        base = self._norm_remote(self.config.path)
        entries: Dict[str, FileEntry] = {}

        def _walk_sftp(curr_dir: str, rel_prefix: str):
            try:
                items = self.sftp.listdir_attr(curr_dir)
            except IOError:
                return
            for attr in items:
                name = attr.filename
                if name in (".", ".."):
                    continue
                rel_p = f"{rel_prefix}/{name}".lstrip("/")
                if matches_exclude(rel_p, exclude_patterns):
                    continue
                full_p = posixpath.join(curr_dir, name)
                if attr.st_mode and stat.S_ISDIR(attr.st_mode):
                    _walk_sftp(full_p, rel_p)
                else:
                    entries[rel_p] = FileEntry(
                        rel_path=rel_p,
                        size=int(attr.st_size or 0),
                        mtime=float(attr.st_mtime or time.time()),
                    )

        _walk_sftp(base, "")
        return entries

    def download_file(self, rel_path: str, local_dest: str, preserve_mtime: Optional[float] = None):
        self.connect()
        remote_p = self._remote_full(rel_path)
        os.makedirs(os.path.dirname(local_dest), exist_ok=True)
        self.sftp.get(remote_p, local_dest)
        if preserve_mtime is not None:
            try:
                os.utime(local_dest, (preserve_mtime, preserve_mtime))
            except OSError:
                pass

    def upload_file(self, local_src: str, rel_path: str, preserve_mtime: Optional[float] = None):
        self.connect()
        remote_p = self._remote_full(rel_path)
        parent_dir = posixpath.dirname(remote_p)
        self._ensure_remote_dir(parent_dir)
        self.sftp.put(local_src, remote_p)
        if preserve_mtime is not None:
            try:
                self.sftp.utime(remote_p, (int(preserve_mtime), int(preserve_mtime)))
            except Exception:
                pass

    def delete_file(self, rel_path: str):
        self.connect()
        remote_p = self._remote_full(rel_path)
        try:
            self.sftp.remove(remote_p)
        except IOError:
            pass


class SCPTransport(SSHTransport):
    """
    SCP transport using SCPClient over Paramiko SSH.
    Uses genuine SCP protocol for file transfers with timestamp preservation,
    and SSH command execution / SFTP fallback for fast directory scanning and management.
    """

    def __init__(self, config: EndpointConfig):
        super().__init__(config)
        self.scp_client: Optional[SCPClient] = None

    def connect(self):
        super().connect()
        if self.scp_client is None and self.ssh is not None:
            self.scp_client = SCPClient(self.ssh.get_transport(), socket_timeout=20.0)

    def disconnect(self):
        if self.scp_client:
            try:
                self.scp_client.close()
            except Exception:
                pass
            self.scp_client = None
        super().disconnect()

    def test_connection(self) -> Tuple[bool, str]:
        if not self.config.host:
            return False, "Especifique el servidor (Host / IP) para SCP."
        try:
            self.connect()
            base = self._norm_remote(self.config.path)
            return True, f"Conexión SCP verificada con {self.config.host}:{self.config.port} ({base})"
        except Exception as e:
            return False, f"Error SCP: {e}"
        finally:
            self.disconnect()

    def download_file(self, rel_path: str, local_dest: str, preserve_mtime: Optional[float] = None):
        self.connect()
        remote_p = self._remote_full(rel_path)
        os.makedirs(os.path.dirname(local_dest), exist_ok=True)
        try:
            self.scp_client.get(remote_p, local_dest, preserve_times=True)
        except Exception:
            # Fallback to SFTP channel if SCP shell quoting fails on special chars
            self.sftp.get(remote_p, local_dest)
        if preserve_mtime is not None:
            try:
                os.utime(local_dest, (preserve_mtime, preserve_mtime))
            except OSError:
                pass

    def upload_file(self, local_src: str, rel_path: str, preserve_mtime: Optional[float] = None):
        self.connect()
        remote_p = self._remote_full(rel_path)
        parent_dir = posixpath.dirname(remote_p)
        self._ensure_remote_dir(parent_dir)
        try:
            self.scp_client.put(local_src, remote_p, preserve_times=True)
        except Exception:
            self.sftp.put(local_src, remote_p)
            if preserve_mtime is not None:
                try:
                    self.sftp.utime(remote_p, (int(preserve_mtime), int(preserve_mtime)))
                except Exception:
                    pass


class FTPTransport(BaseTransport):
    """FTP and FTPS (FTP over TLS) transport using Python's built-in ftplib."""

    def __init__(self, config: EndpointConfig):
        super().__init__(config)
        self.ftp: Optional[ftplib.FTP] = None

    def connect(self):
        if self.ftp is not None:
            try:
                self.ftp.voidcmd("NOOP")
                return
            except Exception:
                self.ftp = None

        is_tls = (self.config.protocol or "").lower() == "ftps"
        ftp_cls = ftplib.FTP_TLS if is_tls else ftplib.FTP
        ftp = ftp_cls()
        ftp.encoding = "utf-8"
        port = int(self.config.port or 21)
        ftp.connect(host=self.config.host.strip(), port=port, timeout=15)
        user = self.config.username.strip() or "anonymous"
        passwd = self.config.password or ""
        ftp.login(user=user, passwd=passwd)
        if is_tls and isinstance(ftp, ftplib.FTP_TLS):
            ftp.prot_p()
        ftp.set_pasv(bool(self.config.passive_ftp))
        self.ftp = ftp
        if self.config.path:
            self._ensure_remote_dir(self._norm_remote(self.config.path))

    def disconnect(self):
        if self.ftp:
            try:
                self.ftp.quit()
            except Exception:
                try:
                    self.ftp.close()
                except Exception:
                    pass
            self.ftp = None

    def _norm_remote(self, path_str: str) -> str:
        p = (path_str or "/").replace("\\", "/").strip()
        if not p.startswith("/"):
            p = "/" + p
        return p.rstrip("/") or "/"

    def _remote_full(self, rel_path: str) -> str:
        base = self._norm_remote(self.config.path)
        return posixpath.join(base, rel_path.lstrip("/"))

    def _ensure_remote_dir(self, remote_dir: str):
        if not remote_dir or remote_dir == "/":
            return
        parts = [p for p in remote_dir.split("/") if p]
        curr = ""
        for part in parts:
            curr = f"{curr}/{part}"
            try:
                self.ftp.cwd(curr)
            except ftplib.error_perm:
                try:
                    self.ftp.mkd(curr)
                except ftplib.error_perm:
                    pass

    def test_connection(self) -> Tuple[bool, str]:
        if not self.config.host:
            return False, "Especifique el servidor (Host / IP) FTP."
        try:
            self.connect()
            base = self._norm_remote(self.config.path)
            self.ftp.cwd(base)
            proto_label = (self.config.protocol or "ftp").upper()
            return True, f"Conexión {proto_label} exitosa a {self.config.host}:{self.config.port} ({base})"
        except Exception as e:
            return False, f"Error FTP: {e}"
        finally:
            self.disconnect()

    def list_directories(self, path: Optional[str] = None) -> List[str]:
        was_connected = self.ftp is not None
        try:
            self.connect()
            target = self._norm_remote(path or self.config.path or "/")
            dirs = []
            try:
                for name, facts in self.ftp.mlsd(target):
                    if name in (".", ".."):
                        continue
                    if facts.get("type", "").lower() == "dir":
                        dirs.append(name)
                return sorted(dirs)
            except Exception:
                # Fallback if MLSD is not supported
                lines = []
                self.ftp.cwd(target)
                self.ftp.retrlines("LIST", lines.append)
                for line in lines:
                    parts = line.split(None, 8)
                    if len(parts) >= 9 and (line.startswith("d") or "<DIR>" in line.upper()):
                        name = parts[-1]
                        if name not in (".", ".."):
                            dirs.append(name)
                return sorted(dirs)
        except Exception:
            return []
        finally:
            if not was_connected:
                self.disconnect()

    def _parse_ftp_time(self, time_val: str) -> float:
        # Format YYYYMMDDHHMMSS
        clean = time_val.split(".")[0].strip()
        try:
            dt = datetime.strptime(clean[:14], "%Y%m%d%H%M%S")
            return dt.timestamp()
        except Exception:
            return time.time()

    def scan_files(self, exclude_patterns: str = "") -> Dict[str, FileEntry]:
        self.connect()
        base = self._norm_remote(self.config.path)
        entries: Dict[str, FileEntry] = {}

        def _walk_ftp(curr_dir: str, rel_prefix: str):
            try:
                items = list(self.ftp.mlsd(curr_dir))
                for name, facts in items:
                    if name in (".", ".."):
                        continue
                    rel_p = f"{rel_prefix}/{name}".lstrip("/")
                    if matches_exclude(rel_p, exclude_patterns):
                        continue
                    ftype = facts.get("type", "").lower()
                    full_p = posixpath.join(curr_dir, name)
                    if ftype == "dir":
                        _walk_ftp(full_p, rel_p)
                    elif ftype == "file":
                        sz = int(facts.get("size", 0) or 0)
                        mt = self._parse_ftp_time(facts.get("modify", ""))
                        entries[rel_p] = FileEntry(rel_path=rel_p, size=sz, mtime=mt)
            except Exception:
                # Fallback to NLST/LIST if MLSD is unsupported
                try:
                    self.ftp.cwd(curr_dir)
                    lines = []
                    self.ftp.retrlines("LIST", lines.append)
                    for line in lines:
                        parts = line.split(None, 8)
                        if len(parts) < 9:
                            continue
                        name = parts[8]
                        if name in (".", ".."):
                            continue
                        rel_p = f"{rel_prefix}/{name}".lstrip("/")
                        if matches_exclude(rel_p, exclude_patterns):
                            continue
                        full_p = posixpath.join(curr_dir, name)
                        if line.startswith("d") or "<DIR>" in line.upper():
                            _walk_ftp(full_p, rel_p)
                        else:
                            sz = int(parts[4]) if parts[4].isdigit() else 0
                            entries[rel_p] = FileEntry(rel_path=rel_p, size=sz, mtime=time.time())
                except Exception:
                    return

        _walk_ftp(base, "")
        return entries

    def download_file(self, rel_path: str, local_dest: str, preserve_mtime: Optional[float] = None):
        self.connect()
        remote_p = self._remote_full(rel_path)
        os.makedirs(os.path.dirname(local_dest), exist_ok=True)
        with open(local_dest, "wb") as f:
            self.ftp.retrbinary(f"RETR {remote_p}", f.write, blocksize=65536)
        if preserve_mtime is not None:
            try:
                os.utime(local_dest, (preserve_mtime, preserve_mtime))
            except OSError:
                pass

    def upload_file(self, local_src: str, rel_path: str, preserve_mtime: Optional[float] = None):
        self.connect()
        remote_p = self._remote_full(rel_path)
        parent_dir = posixpath.dirname(remote_p)
        self._ensure_remote_dir(parent_dir)
        with open(local_src, "rb") as f:
            self.ftp.storbinary(f"STOR {remote_p}", f, blocksize=65536)
        if preserve_mtime is not None:
            try:
                ts_str = datetime.fromtimestamp(preserve_mtime).strftime("%Y%m%d%H%M%S")
                self.ftp.voidcmd(f"MFMT {ts_str} {remote_p}")
            except Exception:
                pass

    def delete_file(self, rel_path: str):
        self.connect()
        remote_p = self._remote_full(rel_path)
        try:
            self.ftp.delete(remote_p)
        except Exception:
            pass


def create_transport(config: EndpointConfig) -> BaseTransport:
    proto = (config.protocol or "local").lower()
    if proto == "local":
        return LocalTransport(config)
    elif proto in ("ssh", "sftp"):
        return SSHTransport(config)
    elif proto == "scp":
        return SCPTransport(config)
    elif proto in ("ftp", "ftps"):
        return FTPTransport(config)
    return LocalTransport(config)

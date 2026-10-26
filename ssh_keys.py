"""
ssh_keys.py - SSH Private Key & Passphrase handler for Statoris Sync.
Supports:
- OpenSSH Private Keys (-----BEGIN OPENSSH PRIVATE KEY-----) with or without passphrase
- Traditional PEM Private Keys (RSA, ECDSA, Ed25519) with or without passphrase
- PuTTY Private Keys (.ppk v2 and v3: PuTTY-User-Key-File-2 / PuTTY-User-Key-File-3)
  with aes256-cbc encryption (SHA-1 KDF for v2, Argon2id/d/i KDF for v3) and passphrase verification.
"""

import io
import os
import hmac
import struct
import base64
import hashlib
from typing import Tuple, Optional

import paramiko
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.asymmetric import rsa, ec, ed25519
from cryptography.hazmat.primitives import serialization


class SSHKeyPassphraseError(Exception):
    """Raised when an SSH key is encrypted and requires a passphrase or the passphrase is wrong."""

    def __init__(self, message: str, key_comment: str = ""):
        super().__init__(message)
        self.key_comment = key_comment


def inspect_ssh_key_file(key_path: str) -> Tuple[bool, str, str]:
    """
    Inspects an SSH private key file without decrypting it.
    Returns (is_encrypted, key_type_description, comment).
    """
    if not key_path or not os.path.exists(key_path):
        return False, "unknown", ""

    try:
        with open(key_path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read(16384)
    except Exception:
        return False, "unknown", ""

    lines = [ln.strip() for ln in content.splitlines() if ln.strip()]
    if not lines:
        return False, "unknown", ""

    # Check PuTTY .ppk format
    if lines[0].startswith("PuTTY-User-Key-File-"):
        version = lines[0].split(":")[0].replace("PuTTY-User-Key-File-", "PPK v")
        alg = lines[0].split(":", 1)[1].strip() if ":" in lines[0] else "ssh"
        encryption = "none"
        comment = ""
        for ln in lines[1:12]:
            if ln.startswith("Encryption:"):
                encryption = ln.split(":", 1)[1].strip().lower()
            elif ln.startswith("Comment:"):
                comment = ln.split(":", 1)[1].strip()
        is_enc = encryption not in ("none", "")
        return is_enc, f"PuTTY {version} ({alg})", comment

    # Check Traditional PEM encrypted header
    if "ENCRYPTED" in content and "-----BEGIN" in content:
        return True, "PEM Private Key", os.path.basename(key_path)

    # Check OpenSSH format (-----BEGIN OPENSSH PRIVATE KEY-----)
    if "-----BEGIN OPENSSH PRIVATE KEY-----" in content:
        try:
            b64_lines = []
            in_body = False
            for ln in lines:
                if ln == "-----BEGIN OPENSSH PRIVATE KEY-----":
                    in_body = True
                    continue
                if ln == "-----END OPENSSH PRIVATE KEY-----":
                    break
                if in_body:
                    b64_lines.append(ln)
            raw = base64.b64decode("".join(b64_lines))
            if raw.startswith(b"openssh-key-v1\x00"):
                idx = len(b"openssh-key-v1\x00")
                ciphername, idx = _read_ssh_str(raw, idx)
                kdfname, idx = _read_ssh_str(raw, idx)
                _kdfopts, idx = _read_ssh_str(raw, idx)
                is_enc = ciphername.decode("ascii", errors="ignore") != "none"
                return is_enc, "OpenSSH Private Key", os.path.basename(key_path)
        except Exception:
            pass

    # Try loading without passphrase via Paramiko to see if it raises PasswordRequiredException
    try:
        paramiko.PKey.from_path(key_path, password=None)
        return False, "SSH Private Key", os.path.basename(key_path)
    except paramiko.PasswordRequiredException:
        return True, "SSH Private Key", os.path.basename(key_path)
    except Exception:
        return False, "SSH Key", os.path.basename(key_path)


def _read_ssh_str(data: bytes, offset: int) -> Tuple[bytes, int]:
    if offset + 4 > len(data):
        raise ValueError("Truncated SSH buffer")
    length = struct.unpack(">I", data[offset : offset + 4])[0]
    offset += 4
    if offset + length > len(data):
        raise ValueError("Truncated SSH string content")
    return data[offset : offset + length], offset + length


def _read_ssh_mpint(data: bytes, offset: int) -> Tuple[int, int]:
    raw_bytes, next_offset = _read_ssh_str(data, offset)
    if not raw_bytes:
        return 0, next_offset
    return int.from_bytes(raw_bytes, byteorder="big", signed=False), next_offset


def load_ssh_pkey(key_path: str, passphrase: Optional[str] = None) -> paramiko.PKey:
    """
    Loads an SSH private key (OpenSSH, PEM, or PuTTY .ppk v2/v3) into a Paramiko PKey object.
    Raises SSHKeyPassphraseError if passphrase is required or incorrect.
    """
    if not key_path or not os.path.exists(key_path):
        raise FileNotFoundError(f"No se encontró el archivo de clave SSH: {key_path}")

    with open(key_path, "r", encoding="utf-8", errors="ignore") as f:
        head = f.read(256)

    if head.lstrip().startswith("PuTTY-User-Key-File-"):
        return _load_putty_ppk(key_path, passphrase)

    # Standard OpenSSH / PEM key via Paramiko 5.x PKey.from_path
    pwd_bytes = passphrase.encode("utf-8") if passphrase else None
    try:
        return paramiko.PKey.from_path(key_path, password=pwd_bytes)
    except paramiko.PasswordRequiredException:
        _, _, comment = inspect_ssh_key_file(key_path)
        raise SSHKeyPassphraseError(
            f"La clave privada SSH '{comment or os.path.basename(key_path)}' está cifrada y requiere Passphrase.",
            key_comment=comment or os.path.basename(key_path),
        )
    except paramiko.SSHException as e:
        err_str = str(e).lower()
        if "decrypt" in err_str or "passphrase" in err_str or "bad" in err_str or "padding" in err_str or "checksum" in err_str:
            _, _, comment = inspect_ssh_key_file(key_path)
            raise SSHKeyPassphraseError(
                f"Passphrase incorrecta o necesaria para descifrar la clave SSH '{comment or os.path.basename(key_path)}'.",
                key_comment=comment or os.path.basename(key_path),
            )
        raise


def _load_putty_ppk(key_path: str, passphrase: Optional[str] = None) -> paramiko.PKey:
    with open(key_path, "r", encoding="utf-8", errors="replace") as f:
        raw_lines = [ln.rstrip("\r\n") for ln in f.readlines()]

    if not raw_lines or not raw_lines[0].startswith("PuTTY-User-Key-File-"):
        raise ValueError("Archivo .ppk inválido.")

    header_parts = raw_lines[0].split(":", 1)
    ppk_ver = int(header_parts[0].replace("PuTTY-User-Key-File-", "").strip())
    key_type = header_parts[1].strip()

    headers = {}
    pub_b64_lines = []
    priv_b64_lines = []

    idx = 1
    while idx < len(raw_lines):
        line = raw_lines[idx]
        if ":" not in line:
            idx += 1
            continue
        k, v = line.split(":", 1)
        k = k.strip()
        v = v.strip()
        headers[k] = v
        idx += 1
        if k == "Public-Lines":
            count = int(v)
            pub_b64_lines = raw_lines[idx : idx + count]
            idx += count
        elif k == "Private-Lines":
            count = int(v)
            priv_b64_lines = raw_lines[idx : idx + count]
            idx += count

    encryption = headers.get("Encryption", "none").lower()
    comment = headers.get("Comment", os.path.basename(key_path))
    private_mac_hex = headers.get("Private-MAC", "").strip().lower()

    pub_blob = base64.b64decode("".join(pub_b64_lines))
    priv_encrypted = base64.b64decode("".join(priv_b64_lines))

    if encryption != "none":
        if not passphrase:
            raise SSHKeyPassphraseError(
                f'La clave SSH "{comment}" está protegida con Passphrase. Introduzca la Passphrase para descifrarla.',
                key_comment=comment,
            )
        if encryption != "aes256-cbc":
            raise ValueError(f"Cifrado PPK no soportado: {encryption}")

        pass_bytes = passphrase.encode("utf-8")

        if ppk_ver == 2:
            # PPK v2 KDF: SHA1(uint32(0) + passphrase) + SHA1(uint32(1) + passphrase)
            h0 = hashlib.sha1(b"\x00\x00\x00\x00" + pass_bytes).digest()
            h1 = hashlib.sha1(b"\x00\x00\x00\x01" + pass_bytes).digest()
            aes_key = (h0 + h1)[:32]
            aes_iv = b"\x00" * 16
            mac_key = hashlib.sha1(b"putty-private-key-file-mac-key" + pass_bytes).digest()
        elif ppk_ver == 3:
            from argon2.low_level import hash_secret_raw, Type

            kdf_name = headers.get("Key-Derivation", "Argon2id").lower()
            argon_type = Type.ID
            if "argon2d" in kdf_name:
                argon_type = Type.D
            elif "argon2i" in kdf_name and "argon2id" not in kdf_name:
                argon_type = Type.I

            memory_kb = int(headers.get("Argon2-Memory", "8192"))
            passes = int(headers.get("Argon2-Passes", "13"))
            parallelism = int(headers.get("Argon2-Parallelism", "1"))
            salt_hex = headers.get("Argon2-Salt", "")
            salt = bytes.fromhex(salt_hex)

            # 32 bytes AES key + 16 bytes IV + 32 bytes MAC key = 80 bytes
            derived = hash_secret_raw(
                secret=pass_bytes,
                salt=salt,
                time_cost=passes,
                memory_cost=memory_kb,
                parallelism=parallelism,
                hash_len=80,
                type=argon_type,
            )
            aes_key = derived[:32]
            aes_iv = derived[32:48]
            mac_key = derived[48:80]
        else:
            raise ValueError(f"Versión PPK no soportada: {ppk_ver}")

        cipher = Cipher(algorithms.AES(aes_key), modes.CBC(aes_iv))
        decryptor = cipher.decryptor()
        priv_blob = decryptor.update(priv_encrypted) + decryptor.finalize()
    else:
        priv_blob = priv_encrypted
        if ppk_ver == 2:
            mac_key = hashlib.sha1(b"putty-private-key-file-mac-key").digest()
        else:
            mac_key = b""

    # Verify MAC to detect wrong passphrase immediately
    if private_mac_hex:
        mac_data = b"".join(
            struct.pack(">I", len(s)) + s
            for s in [
                key_type.encode("utf-8"),
                encryption.encode("utf-8"),
                comment.encode("utf-8"),
                pub_blob,
                priv_blob,
            ]
        )
        if ppk_ver == 2:
            calc_mac = hmac.new(mac_key, mac_data, hashlib.sha1).hexdigest().lower()
        else:
            calc_mac = hmac.new(mac_key, mac_data, hashlib.sha256).hexdigest().lower()

        if calc_mac != private_mac_hex:
            raise SSHKeyPassphraseError(
                f'Passphrase incorrecta para la clave privada SSH "{comment}".',
                key_comment=comment,
            )

    return _construct_pkey_from_ppk_blobs(key_type, pub_blob, priv_blob)


def _construct_pkey_from_ppk_blobs(key_type: str, pub_blob: bytes, priv_blob: bytes) -> paramiko.PKey:
    """Converts decrypted PuTTY public & private blobs into a standard PEM key and loads into Paramiko PKey."""
    p_off = 0
    _alg, p_off = _read_ssh_str(pub_blob, p_off)

    if key_type == "ssh-rsa":
        e, p_off = _read_ssh_mpint(pub_blob, p_off)
        n, p_off = _read_ssh_mpint(pub_blob, p_off)

        v_off = 0
        d, v_off = _read_ssh_mpint(priv_blob, v_off)
        p, v_off = _read_ssh_mpint(priv_blob, v_off)
        q, v_off = _read_ssh_mpint(priv_blob, v_off)
        _iqmp, v_off = _read_ssh_mpint(priv_blob, v_off)

        dmp1 = rsa.rsa_crt_dmp1(d, p)
        dmq1 = rsa.rsa_crt_dmq1(d, q)
        iqmp = rsa.rsa_crt_iqmp(p, q)

        pub_nums = rsa.RSAPublicNumbers(e=e, n=n)
        priv_nums = rsa.RSAPrivateNumbers(p=p, q=q, d=d, dmp1=dmp1, dmq1=dmq1, iqmp=iqmp, public_numbers=pub_nums)
        priv_key = priv_nums.private_key()
        pem_bytes = priv_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
        return paramiko.RSAKey.from_private_key(io.StringIO(pem_bytes.decode("utf-8")))

    elif key_type in ("ssh-ed25519", "ed25519"):
        _pub_raw, p_off = _read_ssh_str(pub_blob, p_off)
        priv_raw, _ = _read_ssh_str(priv_blob, 0)
        priv_key = ed25519.Ed25519PrivateKey.from_private_bytes(priv_raw[:32])
        openssh_bytes = priv_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.OpenSSH,
            encryption_algorithm=serialization.NoEncryption(),
        )
        return paramiko.Ed25519Key.from_private_key(io.StringIO(openssh_bytes.decode("utf-8")))

    elif key_type.startswith("ecdsa-sha2-"):
        curve_id_bytes, p_off = _read_ssh_str(pub_blob, p_off)
        point_bytes, p_off = _read_ssh_str(pub_blob, p_off)
        priv_int, _ = _read_ssh_mpint(priv_blob, 0)

        curve_name = curve_id_bytes.decode("ascii", errors="ignore")
        curve_map = {
            "nistp256": ec.SECP256R1(),
            "nistp384": ec.SECP384R1(),
            "nistp521": ec.SECP521R1(),
        }
        curve = curve_map.get(curve_name, ec.SECP256R1())
        pub_key = ec.EllipticCurvePublicKey.from_encoded_point(curve, point_bytes)
        priv_nums = ec.EllipticCurvePrivateNumbers(priv_int, pub_key.public_numbers())
        priv_key = priv_nums.private_key()
        pem_bytes = priv_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
        return paramiko.ECDSAKey.from_private_key(io.StringIO(pem_bytes.decode("utf-8")))

    raise ValueError(f"Tipo de clave PPK no soportado: {key_type}")

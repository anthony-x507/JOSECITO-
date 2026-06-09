"""Encrypted credential vault."""
import os
import json
import base64
import hashlib
from pathlib import Path
from typing import Optional, Dict, Any

PROFILE_ID = os.environ.get("DIGOS_PROFILE_ID", "master")
MASTER_DIR = Path(os.path.expanduser("~/.digos"))
PROFILE_DIR = MASTER_DIR / "profiles" / PROFILE_ID
VAULT_FILE = PROFILE_DIR / "vault.enc"


def _machine_key() -> bytes:
    """Derive a machine-bound key from hostname + username."""
    raw = f"{os.uname().nodename}-{os.environ.get('USER', 'unknown')}-MASTER-2026"
    digest = hashlib.sha256(raw.encode()).digest()
    return base64.urlsafe_b64encode(digest)


def _xor_encrypt(data: bytes, key: bytes) -> bytes:
    return bytes(b ^ key[i % len(key)] for i, b in enumerate(data))


class CajaSeguraInfo:
    """Persistent encrypted credentials vault.

    Stores per-slot dictionaries (e.g., 'principal', 'factory_engineer').
    Hardware-bound: a vault created on machine A cannot be read on machine B.
    """

    @staticmethod
    def _read_raw() -> Dict[str, Dict[str, Any]]:
        if not VAULT_FILE.exists():
            return {}
        try:
            with open(VAULT_FILE, "rb") as f:
                encrypted = f.read()
            decrypted = _xor_encrypt(encrypted, _machine_key())
            return json.loads(decrypted.decode("utf-8"))
        except Exception:
            return {}

    @staticmethod
    def _write_raw(data: Dict[str, Dict[str, Any]]) -> None:
        PROFILE_DIR.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(data).encode("utf-8")
        encrypted = _xor_encrypt(payload, _machine_key())
        with open(VAULT_FILE, "wb") as f:
            f.write(encrypted)
        try:
            os.chmod(VAULT_FILE, 0o600)
        except Exception:
            pass

    @classmethod
    def read_slot(cls, slot: str) -> Optional[Dict[str, Any]]:
        return cls._read_raw().get(slot)

    @classmethod
    def write_slot(cls, slot: str, value: Dict[str, Any]) -> None:
        data = cls._read_raw()
        data[slot] = value
        cls._write_raw(data)

    @classmethod
    def delete_slot(cls, slot: str) -> None:
        data = cls._read_raw()
        if slot in data:
            del data[slot]
            cls._write_raw(data)

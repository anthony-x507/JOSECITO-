"""DIGOS CajaSeguraInfo — Encrypted credential cabinet."""
import json
import os
import base64
import hashlib
import hmac
import time
import threading
from pathlib import Path
from typing import Optional, Dict, List

from digos_lib.constants import KEY_FILE, VAULT_FILE

class CajaSeguraInfo:
    """Encrypted cabinet with 100 slots for agent credentials.

    Each agent has its own slot (folder) inside the cabinet.
    One agent's information does NOT mix with another's.

    Scrypt for key derivation + XOR with HMAC for integrity.

    Uso:
        CajaSeguraInfo.write_slot("josecito", {"api_key": "sk-...", "token": "..."})
        data = CajaSeguraInfo.read_slot("josecito")
        slots = CajaSeguraInfo.list_slots()
    """

    MAX_SLOTS = 100

    @staticmethod
    def _load_or_create_key() -> bytes:
        if KEY_FILE.exists():
            raw = KEY_FILE.read_bytes().strip()
            return base64.b64decode(raw) if raw else CajaSeguraInfo._create_key()
        return CajaSeguraInfo._create_key()

    @staticmethod
    def _create_key() -> bytes:
        key = os.urandom(32)
        KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
        KEY_FILE.write_bytes(base64.b64encode(key))
        KEY_FILE.chmod(0o600)
        return key

    @staticmethod
    def _derive_key(password: bytes, salt: bytes, dklen: int = 32, n: int = 2**14) -> bytes:
        """Derives a key using scrypt or pbkdf2_hmac as fallback."""
        try:
            return hashlib.scrypt(password, salt=salt, n=n, r=8, p=1, dklen=dklen)
        except AttributeError:
            # Fallback for macOS Python without scrypt
            return hashlib.pbkdf2_hmac("sha256", password, salt, iterations=100000, dklen=dklen)

    _vault_cache = None
    _vault_cache_time = 0.0
    _vault_lock = threading.Lock()
    _CACHE_TTL = 5.0

    @staticmethod
    def _get_vault() -> dict:
        """Reads the vault with cache and lock for consistency."""
        now = time.time()
        with CajaSeguraInfo._vault_lock:
            if (CajaSeguraInfo._vault_cache is not None
                    and now - CajaSeguraInfo._vault_cache_time < CajaSeguraInfo._CACHE_TTL):
                return CajaSeguraInfo._vault_cache
            vault = CajaSeguraInfo.read_vault() or {}
            CajaSeguraInfo._vault_cache = vault
            CajaSeguraInfo._vault_cache_time = now
            return vault

    @staticmethod
    def _invalidate_cache():
        """Invalidates the cache to force reload."""
        CajaSeguraInfo._vault_cache = None
        CajaSeguraInfo._vault_cache_time = 0.0

    @staticmethod
    def _generate_keystream(key: bytes, salt: bytes, length: int) -> bytes:
        """Fast keystream via HMAC-SHA256 in counter mode (CTR).
        Much faster than PBKDF2 for large keystreams."""
        result = bytearray()
        counter = 0
        while len(result) < length:
            block = hmac.new(key, salt + counter.to_bytes(4, 'big'), "sha256").digest()
            result.extend(block)
            counter += 1
        return bytes(result[:length])

    @staticmethod
    def encrypt(data: bytes) -> bytes:
        master_key = CajaSeguraInfo._load_or_create_key()
        if not data:
            salt = os.urandom(16)
            iv = os.urandom(16)
            mac_key = hashlib.sha256(b"digos-mac:" + master_key + salt).digest()
            mac = hmac.new(mac_key, salt + iv + b"", "sha256").digest()
            return b"\x01" + salt + iv + mac + b""
        salt = os.urandom(16)
        iv = os.urandom(16)
        enc_key = CajaSeguraInfo._derive_key(master_key, salt=salt, dklen=32)
        mac_key = hashlib.sha256(b"digos-mac:" + master_key + salt).digest()
        keystream = CajaSeguraInfo._generate_keystream(enc_key, iv, len(data))
        ciphertext = bytes(a ^ b for a, b in zip(data, keystream))
        mac = hmac.new(mac_key, salt + iv + ciphertext, "sha256").digest()
        return b"\x01" + salt + iv + mac + ciphertext

    @staticmethod
    def decrypt(payload: bytes) -> Optional[bytes]:
        if len(payload) < 65:
            return None
        if payload[0] != 1:
            return None
        master_key = CajaSeguraInfo._load_or_create_key()
        salt = payload[1:17]
        iv = payload[17:33]
        mac = payload[33:65]
        ciphertext = payload[65:]
        mac_key = hashlib.sha256(b"digos-mac:" + master_key + salt).digest()
        expected = hmac.new(mac_key, salt + iv + ciphertext, "sha256").digest()
        if not hmac.compare_digest(mac, expected):
            return None
        if not ciphertext:
            return b""
        enc_key = CajaSeguraInfo._derive_key(master_key, salt=salt, dklen=32)
        keystream = CajaSeguraInfo._generate_keystream(enc_key, iv, len(ciphertext))
        return bytes(a ^ b for a, b in zip(ciphertext, keystream))

    @staticmethod
    def read_vault() -> Optional[dict]:
        """Reads the ENTIRE encrypted vault. Returns dict with all slots."""
        if not VAULT_FILE.exists():
            return None
        try:
            encrypted = VAULT_FILE.read_bytes()
            decrypted = CajaSeguraInfo.decrypt(encrypted)
            if decrypted:
                return json.loads(decrypted.decode())
        except Exception:
            pass
        return None

    @staticmethod
    def _save_vault(data: dict) -> bool:
        """Saves the ENTIRE encrypted vault."""
        try:
            encrypted = CajaSeguraInfo.encrypt(json.dumps(data).encode())
            VAULT_FILE.write_bytes(encrypted)
            VAULT_FILE.chmod(0o600)
            return True
        except Exception:
            return False

    # ── API de Slots ─────────────────────────

    @staticmethod
    def write_slot(agent_name: str, credentials: dict) -> bool:
        """Saves an agent's credentials in its cabinet slot."""
        acquired = CajaSeguraInfo._vault_lock.acquire(timeout=5)
        if not acquired:
            return False
        try:
            vault = CajaSeguraInfo.read_vault() or {}
            slots = vault.get("slots", {})
            if agent_name not in slots and len(slots) >= CajaSeguraInfo.MAX_SLOTS:
                return False
            slots[agent_name] = {
                "credentials": credentials,
                "updated_at": time.time(),
            }
            vault["slots"] = slots
            vault["_version"] = 2
            ok = CajaSeguraInfo._save_vault(vault)
            if ok:
                CajaSeguraInfo._invalidate_cache()
            return ok
        finally:
            CajaSeguraInfo._vault_lock.release()

    @staticmethod
    def read_slot(agent_name: str) -> Optional[dict]:
        """Reads an agent's credentials from its slot."""
        vault = CajaSeguraInfo._get_vault()
        slots = vault.get("slots", {})
        slot = slots.get(agent_name)
        if not slot:
            return None
        return slot.get("credentials")

    @staticmethod
    def list_slots() -> List[str]:
        """Lists agents that have occupied slots."""
        vault = CajaSeguraInfo._get_vault()
        return list(vault.get("slots", {}).keys())

    @staticmethod
    def delete_slot(agent_name: str) -> bool:
        """Deletes an agent's slot."""
        acquired = CajaSeguraInfo._vault_lock.acquire(timeout=5)
        if not acquired:
            return False
        try:
            vault = CajaSeguraInfo.read_vault() or {}
            slots = vault.get("slots", {})
            if agent_name not in slots:
                return False
            del slots[agent_name]
            vault["slots"] = slots
            ok = CajaSeguraInfo._save_vault(vault)
            if ok:
                CajaSeguraInfo._invalidate_cache()
            return ok
        finally:
            CajaSeguraInfo._vault_lock.release()

    @staticmethod
    def slot_count() -> int:
        """Returns how many slots are occupied."""
        vault = CajaSeguraInfo._get_vault()
        return len(vault.get("slots", {}))



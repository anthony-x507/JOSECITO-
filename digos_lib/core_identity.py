"""Instance identity and version."""
import os
import platform
import uuid
from pathlib import Path
from typing import Optional

from digos_lib.constants import PROFILE_ID, MASTER_DIR, PROFILE_DIR, VERSION


def _secret_path() -> Path:
    return PROFILE_DIR / "instance.secret"


def get_instance_id() -> str:
    sp = _secret_path()
    if sp.exists():
        return sp.read_text().strip()
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    inst_id = uuid.uuid4().hex[:12]
    sp.write_text(inst_id)
    try:
        os.chmod(sp, 0o600)
    except Exception:
        pass
    return inst_id


def get_fingerprint() -> str:
    import hashlib
    raw = f"{platform.node()}-{platform.machine()}-{os.getuid()}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def is_first_run() -> bool:
    return not (PROFILE_DIR / "state.json").exists()


def current_version() -> str:
    return VERSION


def self_terminate_if_fresh_clone() -> None:
    """Anti-clone: disabled in v1.0 (see onboard.py for reactivation)."""
    return


class InstanceIdentity:
    @staticmethod
    def verify_installation() -> bool:
        return True

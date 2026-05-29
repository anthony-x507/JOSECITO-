"""DIGOS Provider API — tests connectivity with AI providers."""
import json
import socket
from typing import Tuple
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

from digos_lib.constants import PROVIDERS


def _provider_api_request(provider_id: str, api_key: str) -> Tuple[bool, str, int]:
    """Tests connectivity with an AI provider.

    Returns:
        (success: bool, message: str, http_status: int)
    """
    provider = PROVIDERS.get(provider_id)
    if not provider or not provider.get("test_url"):
        return False, "No hay URL de prueba para este proveedor", 0

    url = provider["test_url"]
    auth_type = provider["auth"]
    try:
        req = Request(url)
        if auth_type == "bearer":
            req.add_header("Authorization", f"Bearer {api_key}")
        elif auth_type == "x-api-key":
            req.add_header("x-api-key", api_key)
        elif auth_type == "query":
            clean_url = url.replace("***", "") + api_key
            req = Request(clean_url)

        with urlopen(req, timeout=10) as resp:
            if resp.status not in (200, 201):
                return (False, f"HTTP {resp.status}", resp.status)
            # Read body to validate it is not an error with HTTP 200
            try:
                body = json.loads(resp.read().decode())
                if body.get("error") or body.get("errors"):
                    return (False, f"API key inválida (HTTP 200 con error)", resp.status)
            except Exception:
                pass
            return (True, "Conexión exitosa", resp.status)
    except HTTPError as e:
        if e.code in (401, 403):
            return (False, f"API Key inválida (HTTP {e.code})", e.code)
        return (False, f"HTTP {e.code}: {e.reason}", e.code)
    except URLError as e:
        return (False, f"Conexión: {e.reason}", 0)
    except socket.timeout:
        return (False, "Timeout", 0)
    except Exception as e:
        return (False, f"{type(e).__name__}: {e}", 0)

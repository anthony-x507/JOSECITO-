"""Provider-specific API tests."""
import json
import socket
from typing import Tuple
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

from digos_lib.constants import PROVIDERS


def _provider_api_request(provider_id: str, api_key: str) -> Tuple[bool, str, int]:
    """Test API key against provider's test endpoint.

    Returns: (success, message, http_status)
    """
    provider = PROVIDERS.get(provider_id)
    if not provider:
        return False, f"Unknown provider: {provider_id}", 0
    if not provider.get("test_url"):
        # No test URL — log warning but do NOT flag as invalid
        return True, "No test URL — assuming valid", 0

    url = provider["test_url"]
    auth_type = provider["auth"]
    try:
        if auth_type == "query":
            clean_url = url.replace("***", api_key)
            req = Request(clean_url)
        else:
            req = Request(url)
            if auth_type == "bearer":
                req.add_header("Authorization", f"Bearer {api_key}")
            elif auth_type == "x-api-key":
                req.add_header("x-api-key", api_key)
            elif auth_type == "none":
                pass
            else:
                req.add_header("Authorization", f"Bearer {api_key}")

        with urlopen(req, timeout=10) as resp:
            if resp.status not in (200, 201):
                return False, f"HTTP {resp.status}", resp.status
            try:
                body = json.loads(resp.read().decode())
                if body.get("error") or body.get("errors"):
                    return False, "API key invalid (HTTP 200 with error)", resp.status
            except Exception:
                pass
            return True, "Connection successful", resp.status
    except HTTPError as e:
        if e.code in (401, 403):
            return False, f"API key invalid (HTTP {e.code})", e.code
        return False, f"HTTP {e.code}: {e.reason}", e.code
    except URLError as e:
        return False, f"Connection: {e.reason}", 0
    except socket.timeout:
        return False, "Timeout", 0
    except Exception as e:
        return False, f"{type(e).__name__}: {e}", 0


def test_telegram_token(token: str) -> Tuple[bool, str]:
    """Test Telegram bot token via getMe API."""
    try:
        with urlopen(f"https://api.telegram.org/bot{token}/getMe", timeout=10) as resp:
            data = json.loads(resp.read().decode())
            if data.get("ok"):
                bot = data["result"]
                return True, f"@{bot.get('username', '?')} — {bot.get('first_name', '?')}"
            return False, "Invalid token"
    except HTTPError as e:
        return False, f"HTTP {e.code}: {e.reason}"
    except Exception as e:
        return False, str(e)

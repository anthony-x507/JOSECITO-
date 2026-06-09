"""LLM HTTP client — OpenAI-compatible API."""
import json
import socket
from typing import List, Dict, Optional
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError


class LLMClient:
    """Stateless-ish LLM client with conversation history."""

    def __init__(self, base_url: str, api_key: str, model: str,
                 system_prompt: str = "", timeout: int = 30):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.system_prompt = system_prompt
        self.timeout = timeout
        self._history: List[Dict[str, str]] = []
        if system_prompt:
            self._history.append({"role": "system", "content": system_prompt})

    def ask(self, prompt: str, max_tokens: int = 2048, temperature: float = 0.7) -> str:
        return self._call_llm(prompt, max_tokens, temperature)

    def ask_raw(self, prompt: str, max_tokens: int = 2048, temperature: float = 0.0) -> str:
        return self._call_llm(prompt, max_tokens, temperature)

    def reset(self) -> None:
        self._history = []
        if self.system_prompt:
            self._history.append({"role": "system", "content": self.system_prompt})

    def get_history(self) -> List[Dict[str, str]]:
        return list(self._history)

    def set_system_prompt(self, prompt: str) -> None:
        self.system_prompt = prompt
        if self._history and self._history[0]["role"] == "system":
            self._history[0]["content"] = prompt
        else:
            self._history.insert(0, {"role": "system", "content": prompt})

    def is_ready(self) -> bool:
        return bool(self.base_url and self.model)

    def _call_llm(self, prompt: str, max_tokens: int, temperature: float) -> str:
        self._history.append({"role": "user", "content": prompt})
        try:
            response_text = self._call_llm_with_messages(self._history, max_tokens, temperature)
            self._history.append({"role": "assistant", "content": response_text})
            return response_text
        except Exception:
            self._history.pop()
            raise

    def _call_llm_with_messages(self, messages: List[Dict[str, str]],
                                max_tokens: int, temperature: float) -> str:
        url = f"{self.base_url}/chat/completions"
        body = json.dumps({
            "model": self.model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }).encode("utf-8")
        req = Request(url, data=body, method="POST")
        req.add_header("Content-Type", "application/json")
        if self.api_key:
            req.add_header("Authorization", f"Bearer {self.api_key}")
        with urlopen(req, timeout=self.timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        return payload["choices"][0]["message"]["content"]

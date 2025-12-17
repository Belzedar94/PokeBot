from __future__ import annotations

import base64
import json
import logging
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import requests

from .action_schema import Action, action_json_schema, try_parse_action


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GeminiConfig:
    model: str
    thinking_level: str = "low"
    api_key_env: str = "GEMINI_API_KEY"
    timeout_s: float = 30.0


def _build_prompt_text(
    *,
    rules_text_spanish: Optional[str],
    state: Dict[str, Any],
    recent_actions: List[Dict[str, Any]],
) -> str:
    rules_block = rules_text_spanish.strip() if rules_text_spanish else ""
    if not rules_block:
        rules_block = (
            "[REGLAS NO CONFIGURADAS]\n"
            "Sigue el espíritu de Randomlocke/Nuzlocke y juega de forma segura. "
            "Respeta los límites del juego (captura 1 por ruta, etc.)."
        )

    return (
        "Eres un agente que juega Pokémon Añil: Definitive Edition en modo Randomlocke.\n"
        "Debes responder EXCLUSIVAMENTE con un único JSON válido que cumpla el schema.\n"
        "No escribas explicaciones fuera del JSON.\n\n"
        "Reglas (texto original en español):\n"
        f"{rules_block}\n\n"
        "Resumen operativo:\n"
        "- Objetivo: avanzar hacia el Campeón.\n"
        "- Si hay diálogo, normalmente pulsa Z.\n"
        "- Si estás atascado, prueba X (atrás), luego C (menú/usar), luego moverte.\n"
        "- Prefiere acciones cortas: 1–3 botones.\n\n"
        "Estado actual (JSON):\n"
        f"{json.dumps(state, ensure_ascii=False)}\n\n"
        "Historial reciente de acciones (JSON):\n"
        f"{json.dumps(recent_actions[-10:], ensure_ascii=False)}\n"
    )


class GeminiClient:
    def __init__(self, cfg: GeminiConfig):
        self._cfg = cfg
        self._schema = action_json_schema()
        self._api_key = os.environ.get(cfg.api_key_env)
        if not self._api_key:
            raise RuntimeError(f"Missing Gemini API key in env var {cfg.api_key_env}")

        self._sdk_client = None
        self._sdk_types = None
        try:
            from google import genai  # type: ignore
            from google.genai import types  # type: ignore

            self._sdk_client = genai.Client(api_key=self._api_key)
            self._sdk_types = types
            logger.info("GeminiClient: using google-genai SDK")
        except Exception as exc:
            logger.warning("GeminiClient: google-genai SDK unavailable (%s), using REST fallback", exc)

    def set_thinking_level(self, level: str) -> None:
        self._cfg = GeminiConfig(
            model=self._cfg.model,
            thinking_level=level,
            api_key_env=self._cfg.api_key_env,
            timeout_s=self._cfg.timeout_s,
        )

    def decide_action(
        self,
        *,
        screenshot_png: bytes,
        state: Dict[str, Any],
        recent_actions: List[Dict[str, Any]],
        rules_text_spanish: Optional[str],
    ) -> Action:
        prompt = _build_prompt_text(
            rules_text_spanish=rules_text_spanish, state=state, recent_actions=recent_actions
        )

        if self._sdk_client and self._sdk_types:
            text = self._decide_via_sdk(prompt=prompt, screenshot_png=screenshot_png)
        else:
            text = self._decide_via_rest(prompt=prompt, screenshot_png=screenshot_png)
        return try_parse_action(text)

    def _decide_via_sdk(self, *, prompt: str, screenshot_png: bytes) -> str:
        types = self._sdk_types
        client = self._sdk_client
        assert types is not None and client is not None

        contents = [
            types.Content(
                role="user",
                parts=[
                    types.Part.from_text(prompt),
                    types.Part.from_bytes(data=screenshot_png, mime_type="image/png"),
                ],
            )
        ]

        cfg_variants = [
            {
                "response_mime_type": "application/json",
                "response_json_schema": self._schema,
                "thinking_config": {"thinking_level": self._cfg.thinking_level},
                "temperature": 0.2,
            },
            {
                "response_mime_type": "application/json",
                "response_schema": self._schema,
                "thinking_config": {"thinking_level": self._cfg.thinking_level},
                "temperature": 0.2,
            },
            {
                "responseMimeType": "application/json",
                "responseSchema": self._schema,
                "thinkingConfig": {"thinkingLevel": self._cfg.thinking_level},
                "temperature": 0.2,
            },
        ]

        resp = None
        last_exc: Optional[Exception] = None
        for cfg in cfg_variants:
            try:
                resp = client.models.generate_content(
                    model=self._cfg.model, contents=contents, config=cfg
                )
                break
            except Exception as exc:  # pragma: no cover
                last_exc = exc
        if resp is None:
            raise RuntimeError(f"SDK generate_content failed: {last_exc}") from last_exc
        text = getattr(resp, "text", None)
        if isinstance(text, str) and text.strip():
            return text

        # Fallback: try to extract from candidates/parts.
        try:
            candidates = getattr(resp, "candidates", []) or []
            content = candidates[0].content
            parts = content.parts or []
            return parts[0].text
        except Exception as exc:
            raise RuntimeError(f"SDK response parse failed: {exc}") from exc

    def _decide_via_rest(self, *, prompt: str, screenshot_png: bytes) -> str:
        endpoint = (
            f"https://generativelanguage.googleapis.com/v1beta/models/{self._cfg.model}:generateContent"
        )

        body = {
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {"text": prompt},
                        {
                            "inlineData": {
                                "mimeType": "image/png",
                                "data": base64.b64encode(screenshot_png).decode("ascii"),
                            }
                        },
                    ],
                }
            ],
            "generationConfig": {
                "responseMimeType": "application/json",
                "responseSchema": self._schema,
                "temperature": 0.2,
            },
            "thinkingConfig": {"thinkingLevel": self._cfg.thinking_level},
        }

        r = requests.post(
            endpoint,
            params={"key": self._api_key},
            json=body,
            timeout=self._cfg.timeout_s,
        )
        r.raise_for_status()
        data = r.json()
        try:
            return data["candidates"][0]["content"]["parts"][0]["text"]
        except Exception as exc:
            raise RuntimeError(f"REST response parse failed: {exc}; body={data}") from exc

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Any, Dict, Optional

import requests
from pydantic import BaseModel, Field, TypeAdapter


logger = logging.getLogger(__name__)


class SummaryOut(BaseModel):
    summary: str = Field(min_length=1, max_length=240)


_SUMMARY_ADAPTER = TypeAdapter(SummaryOut)


def summary_json_schema() -> dict:
    return _SUMMARY_ADAPTER.json_schema()


@dataclass(frozen=True)
class ReporterConfig:
    mode: str = "template"  # "template" or "gemini"
    model: str = "gemini-3-pro-preview"
    thinking_level: str = "low"
    api_key_env: str = "GEMINI_API_KEY"
    timeout_s: float = 20.0


class Reporter:
    def __init__(self, cfg: ReporterConfig):
        self._cfg = cfg
        self._api_key = os.environ.get(cfg.api_key_env, "")

        self._sdk_client = None
        try:
            from google import genai  # type: ignore

            if self._api_key:
                self._sdk_client = genai.Client(api_key=self._api_key)
        except Exception:
            self._sdk_client = None

    def generate_funny_summary(self, record: Dict[str, Any], kind: str) -> str:
        if self._cfg.mode == "gemini" and self._api_key:
            try:
                return self._gemini_summary(record=record, kind=kind)
            except Exception as exc:
                logger.warning("gemini summary failed, falling back to template: %s", exc)
        return self._template_summary(record=record, kind=kind)

    def _template_summary(self, record: Dict[str, Any], kind: str) -> str:
        name = str(record.get("name") or record.get("species") or "¿Quién?")
        species = str(record.get("species") or "???")
        level = record.get("level")
        lvl = f"nv. {level}" if level is not None else "nivel desconocido"

        if kind == "captures":
            return f"Nuevo fichaje: {name} ({species}) {lvl}. Que Arceus reparta suerte."
        if kind == "deaths":
            return f"RIP {name} ({species}) {lvl}. Te fuiste demasiado pronto."
        return f"{name} ({species}) {lvl}."

    def _gemini_summary(self, record: Dict[str, Any], kind: str) -> str:
        schema = summary_json_schema()
        prompt = (
            "Devuelve SOLO JSON válido con el schema {summary:string}.\n"
            "Genera 1 línea corta y graciosa en español.\n"
            "No insultes; humor ligero.\n\n"
            f"Tipo: {kind}\n"
            f"Datos: {json.dumps(record, ensure_ascii=False)}\n"
        )

        if self._sdk_client is not None:
            return self._gemini_summary_sdk(prompt=prompt, schema=schema)
        return self._gemini_summary_rest(prompt=prompt, schema=schema)

    def _gemini_summary_sdk(self, *, prompt: str, schema: dict) -> str:
        client = self._sdk_client
        assert client is not None

        cfg_variants = [
            {
                "response_mime_type": "application/json",
                "response_json_schema": schema,
                "thinking_config": {"thinking_level": self._cfg.thinking_level},
                "temperature": 0.6,
            },
            {
                "response_mime_type": "application/json",
                "response_schema": schema,
                "thinking_config": {"thinking_level": self._cfg.thinking_level},
                "temperature": 0.6,
            },
            {
                "responseMimeType": "application/json",
                "responseSchema": schema,
                "thinkingConfig": {"thinkingLevel": self._cfg.thinking_level},
                "temperature": 0.6,
            },
        ]

        resp = None
        last_exc: Optional[Exception] = None
        for cfg in cfg_variants:
            try:
                resp = client.models.generate_content(
                    model=self._cfg.model,
                    contents=[prompt],
                    config=cfg,
                )
                break
            except Exception as exc:  # pragma: no cover
                last_exc = exc

        if resp is None:
            raise RuntimeError(f"SDK generate_content failed: {last_exc}") from last_exc

        text = getattr(resp, "text", "") or ""
        out = _SUMMARY_ADAPTER.validate_json(text)
        return out.summary

    def _gemini_summary_rest(self, *, prompt: str, schema: dict) -> str:
        endpoint = (
            f"https://generativelanguage.googleapis.com/v1beta/models/{self._cfg.model}:generateContent"
        )
        body = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {
                "responseMimeType": "application/json",
                "responseSchema": schema,
                "temperature": 0.6,
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
        text = data["candidates"][0]["content"]["parts"][0]["text"]
        out = _SUMMARY_ADAPTER.validate_json(text)
        return out.summary

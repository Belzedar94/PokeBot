from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, Field, TypeAdapter, ValidationError

try:
    from typing import Annotated
except ImportError:  # pragma: no cover
    from typing_extensions import Annotated  # type: ignore


ALLOWED_KEYS = (
    "UP",
    "DOWN",
    "LEFT",
    "RIGHT",
    "Z",
    "X",
    "C",
    "A",
    "S",
    "D",
    "Q",
    "W",
)

AllowedKey = Literal[
    "UP",
    "DOWN",
    "LEFT",
    "RIGHT",
    "Z",
    "X",
    "C",
    "A",
    "S",
    "D",
    "Q",
    "W",
]


class ButtonPress(BaseModel):
    key: AllowedKey
    ms: int = Field(default=80, ge=0, le=1500)


class ButtonsAction(BaseModel):
    type: Literal["buttons"] = "buttons"
    buttons: List[ButtonPress] = Field(default_factory=list, max_length=20)
    wait_ms: int = Field(default=200, ge=0, le=10_000)
    note: str = Field(default="", max_length=240)


class WaitAction(BaseModel):
    type: Literal["wait"] = "wait"
    wait_ms: int = Field(default=500, ge=0, le=60_000)
    note: str = Field(default="", max_length=240)


Action = Annotated[Union[ButtonsAction, WaitAction], Field(discriminator="type")]


_ACTION_ADAPTER = TypeAdapter(Action)
logger = logging.getLogger(__name__)


def action_json_schema() -> Dict[str, Any]:
    # Keep the Gemini-side JSON Schema simple (avoid oneOf/discriminator),
    # then validate strictly with Pydantic after parsing.
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["type"],
        "properties": {
            "type": {"type": "string", "enum": ["buttons", "wait"]},
            "buttons": {
                "type": "array",
                "maxItems": 20,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["key", "ms"],
                    "properties": {
                        "key": {"type": "string", "enum": list(ALLOWED_KEYS)},
                        "ms": {"type": "integer", "minimum": 0, "maximum": 1500},
                    },
                },
            },
            "wait_ms": {"type": "integer", "minimum": 0, "maximum": 60000},
            "note": {"type": "string", "maxLength": 240},
        },
    }


def parse_action_json(text: str) -> Action:
    return _ACTION_ADAPTER.validate_json(text)


def validate_action_obj(obj: Any) -> Action:
    return _ACTION_ADAPTER.validate_python(obj)


def safe_fallback_action(note: str = "fallback") -> WaitAction:
    return WaitAction(wait_ms=500, note=note)


def action_to_dict(action: Action) -> dict:
    if isinstance(action, BaseModel):
        return json.loads(action.model_dump_json())
    return json.loads(json.dumps(action))


def try_parse_action(text: str) -> Action:
    try:
        return parse_action_json(text)
    except ValidationError:
        logger.warning("Gemini action schema validation failed")
        return safe_fallback_action("schema_validation_error")
    except Exception:
        logger.warning("Gemini action parse failed")
        return safe_fallback_action("parse_error")

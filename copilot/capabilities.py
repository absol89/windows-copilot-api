"""Account/model capabilities shared by the client and local API.

Copilot's chat protocol does not carry an OpenAI-style model id. The web client
selects a model/mode with the tone field. Keep the mapping explicit here and
only advertise named models after the signed-in Copilot UI has actually exposed
them to Eve.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Optional


DEFAULT_CAPABILITIES_FILE = "session/capabilities.json"


@dataclass(frozen=True)
class ModelSpec:
    id: str
    label: str
    tone: str
    scenario: Optional[str] = None
    license_type: Optional[str] = None


MODEL_CATALOG = {
    "copilot": ModelSpec("copilot", "Auto", "Magic"),
    "quick": ModelSpec("quick", "Quick response", "Gpt_5_5_Chat"),
    "think-deeper": ModelSpec("think-deeper", "Think deeper", "Gpt_5_5_Reasoning"),
    "gpt-5.6-quick": ModelSpec("gpt-5.6-quick", "GPT 5.6 Quick response", "Gpt_5_6_Chat"),
    "gpt-5.6-think-deeper": ModelSpec(
        "gpt-5.6-think-deeper", "GPT 5.6 Think deeper", "Gpt_5_6_Reasoning"
    ),
    "gpt-6-think-deeper": ModelSpec(
        "gpt-6-think-deeper",
        "GPT 6 Think deeper",
        "Gpt_6_Reasoning",
        scenario="OfficeWebPaidCopilot",
        license_type="Premium",
    ),
    "gpt-6-sol": ModelSpec("gpt-6-sol", "GPT 6 Sol", "Gpt_6_Sol_Reasoning"),
    "gpt-6.1-sol": ModelSpec("gpt-6.1-sol", "GPT 6.1 Sol", "Gpt_61_Sol_Reasoning"),
    "claude-sonnet": ModelSpec("claude-sonnet", "Claude Sonnet", "Claude_Sonnet"),
    "claude-sonnet-5": ModelSpec(
        "claude-sonnet-5",
        "Claude Sonnet 5",
        "Claude_Sonnet_5",
        scenario="OfficeWebPaidCopilot",
        license_type="Premium",
    ),
}

BASELINE_MODEL_IDS = ("copilot", "quick", "think-deeper")


def _flat(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


_LABEL_TO_ID = {
    _flat(spec.label): model_id for model_id, spec in MODEL_CATALOG.items()
}
_LABEL_TO_ID.update({
    "auto": "copilot",
    "magic": "copilot",
    "quick": "quick",
    "think": "think-deeper",
    "gpt 5 6 quick": "gpt-5.6-quick",
    "gpt 5 6 think": "gpt-5.6-think-deeper",
    "gpt 6 sol": "gpt-6-sol",
    "gpt 6 1 sol": "gpt-6.1-sol",
})


def normalize_model(value: str) -> Optional[str]:
    raw = value.strip()
    if raw in MODEL_CATALOG:
        return raw
    flat = _flat(raw)
    exact = _LABEL_TO_ID.get(flat)
    if exact:
        return exact
    matches = [
        (len(label), model_id)
        for label, model_id in _LABEL_TO_ID.items()
        if flat.startswith(label + " ")
    ]
    return max(matches)[1] if matches else None


def _capabilities_path(path: Optional[str] = None) -> Path:
    return Path(path or DEFAULT_CAPABILITIES_FILE)


def load_discovered_model_ids(path: Optional[str] = None) -> tuple[str, ...]:
    ids = list(BASELINE_MODEL_IDS)
    p = _capabilities_path(path)
    try:
        payload = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        payload = {}
    values = payload.get("models") if isinstance(payload, dict) else None
    if isinstance(values, list):
        for value in values:
            if isinstance(value, str):
                model_id = normalize_model(value)
                if model_id and model_id not in ids:
                    ids.append(model_id)
    return tuple(ids)


def discovery_complete(path: Optional[str] = None) -> bool:
    return _capabilities_path(path).exists()


def save_discovered_models(values: Iterable[str], path: Optional[str] = None) -> tuple[str, ...]:
    found = []
    unknown = []
    for value in values:
        model_id = normalize_model(value)
        if model_id:
            if model_id not in found:
                found.append(model_id)
        else:
            unknown.append(value)
    if unknown:
        raise ValueError("Unsupported Copilot model label(s): " + ", ".join(unknown))
    p = _capabilities_path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"models": found}, indent=2) + "\n", encoding="utf-8")
    return load_discovered_model_ids(path)


def available_models(path: Optional[str] = None) -> list[ModelSpec]:
    return [MODEL_CATALOG[model_id] for model_id in load_discovered_model_ids(path)]


def resolve_model(model: Optional[str], path: Optional[str] = None) -> ModelSpec:
    model_id = normalize_model(model or "copilot")
    allowed = set(load_discovered_model_ids(path))
    if not model_id or model_id not in allowed:
        raise ValueError(
            f"Copilot model {model!r} is not available for this signed-in account. "
            f"Available: {', '.join(load_discovered_model_ids(path))}"
        )
    return MODEL_CATALOG[model_id]


def model_payload(spec: ModelSpec) -> dict:
    payload = asdict(spec)
    payload.pop("scenario", None)
    payload.pop("license_type", None)
    return payload

"""Capacidades de raciocínio anunciadas pelo Ollama; sem perfis simulados."""
from functools import lru_cache
import json
from urllib.request import Request, urlopen

OLLAMA_SHOW = "http://127.0.0.1:11434/api/show"
LEVELS = ("light", "medium", "high", "extra_high")


class ThinkingUnavailable(ValueError):
    pass


@lru_cache(maxsize=32)
def capabilities(model):
    if not isinstance(model, str) or not model:
        raise ThinkingUnavailable("Modelo inválido.")
    request = Request(OLLAMA_SHOW, json.dumps({"model": model}).encode("utf-8"),
                      {"Content-Type": "application/json"})
    with urlopen(request, timeout=5) as response:
        data = json.load(response)
    metadata = data.get("thinking")
    values = metadata.get("values", []) if isinstance(metadata, dict) else []
    if not isinstance(values, list):
        values = []
    return tuple(value for value in values if type(value) is bool or isinstance(value, str))


def profiles(values):
    """Mapeia níveis de UI apenas a controles nativos realmente anunciados."""
    options = {}
    strings = {value.lower(): value for value in values if isinstance(value, str)}
    if strings:
        for level, aliases in {
            "light": ("low", "light"),
            "medium": ("medium",),
            "high": ("high",),
            "extra_high": ("xhigh", "max", "extra_high"),
        }.items():
            for alias in aliases:
                if alias in strings:
                    options[level] = strings[alias]
                    break
    else:
        if False in values and True in values:
            options["light"] = False
        if True in values:
            options["high"] = True
    return options


def resolve(model, level):
    if level == "auto":
        return None
    if level not in LEVELS:
        raise ThinkingUnavailable("Nível de raciocínio inválido.")
    supported = profiles(capabilities(model))
    if level not in supported:
        raise ThinkingUnavailable("Este modelo não oferece esse nível de raciocínio.")
    return supported[level]


def describe(model):
    supported = profiles(capabilities(model))
    return {
        "backend": "Ollama", "model": model,
        "available": {level: level in supported for level in LEVELS},
        "controls": supported,
        "mode": "named" if any(isinstance(value, str) for value in supported.values())
                else "toggle" if supported else "none",
    }


def chat(client, **kwargs):
    """SDK 0.6.2 só aceita low/medium/high; usa REST nativo para nível adicional."""
    level = kwargs.get("think")
    if not isinstance(level, str) or level in {"low", "medium", "high"}:
        return client.chat(**kwargs)
    request = Request("http://127.0.0.1:11434/api/chat",
                      json.dumps(kwargs).encode("utf-8"),
                      {"Content-Type": "application/json"})
    if kwargs.get("stream"):
        def chunks():
            with urlopen(request, timeout=120) as response:
                for line in response:
                    if line.strip():
                        yield json.loads(line)
        return chunks()
    with urlopen(request, timeout=120) as response:
        return json.load(response)

"""Validated runtime loading for packaged language resources."""

import json
from functools import lru_cache
from importlib.resources import files
from typing import cast

from dungeon_agent.api.models import LanguageCode


@lru_cache
def load_language(language: LanguageCode) -> dict[str, object]:
    resource = files("dungeon_agent.resources.locales").joinpath(f"{language}.json")
    document: object = json.loads(resource.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError(f"Language resource {language} must contain a JSON object")
    required = {"code", "name", "ui", "adventure"}
    missing = required.difference(document)
    if missing:
        raise ValueError(f"Language resource {language} is missing: {', '.join(sorted(missing))}")
    if document["code"] != language:
        raise ValueError(f"Language resource {language} has a mismatched code")
    return cast(dict[str, object], document)


def language_section(language: LanguageCode, section: str) -> dict[str, object]:
    value = load_language(language).get(section)
    if not isinstance(value, dict):
        raise ValueError(f"Language resource {language}.{section} must be an object")
    return cast(dict[str, object], value)


def language_text(language: LanguageCode, section: str, key: str) -> str:
    value = language_section(language, section).get(key)
    if not isinstance(value, str):
        raise ValueError(f"Language resource {language}.{section}.{key} must be text")
    return value


def language_translation(language: LanguageCode, section: str, value: str) -> str:
    translations = language_section(language, section).get("translations")
    if not isinstance(translations, dict):
        raise ValueError(f"Language resource {language}.{section}.translations must be an object")
    localized = translations.get(value, value)
    return localized if isinstance(localized, str) else value

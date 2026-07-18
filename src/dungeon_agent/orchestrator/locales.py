from dataclasses import dataclass
from typing import cast

from dungeon_agent.api.models import LanguageCode
from dungeon_agent.localization import language_section, load_language


@dataclass(frozen=True)
class Locale:
    code: LanguageCode
    name: str
    game_title: str
    system_prompt: str
    welcome: str
    help_text: str
    player_prompt: str
    narrator_label: str
    starting: str
    ready: str
    ending: str
    terminated: str
    opening_action: str
    location_label: str
    inventory_label: str
    turns_label: str
    objective_label: str
    health_label: str
    danger_label: str
    status_label: str
    empty_inventory: str
    unknown_location: str
    empty_action: str
    long_action: str
    invalid_action_hint: str
    stats_title: str
    model_label: str
    calls_label: str
    input_tokens_label: str
    output_tokens_label: str
    total_tokens_label: str
    model_latency_label: str
    estimated_cost_label: str
    cost_unavailable: str


def _ui_text(ui: dict[str, object], key: str, language: LanguageCode) -> str:
    value = ui.get(key)
    if not isinstance(value, str):
        raise ValueError(f"Language resource {language}.ui.{key} must be text")
    return value


def load_locale(language: LanguageCode) -> Locale:
    document = load_language(language)
    ui = language_section(language, "ui")
    name = document.get("name")
    if not isinstance(name, str):
        raise ValueError(f"Language resource {language}.name must be text")

    def text(key: str) -> str:
        return _ui_text(ui, key, language)

    return Locale(
        code=language,
        name=name,
        game_title=text("gameTitle"),
        system_prompt=text("systemPrompt"),
        welcome=text("welcome"),
        help_text=text("helpText"),
        player_prompt=text("playerPrompt"),
        narrator_label=text("narratorLabel"),
        starting=text("starting"),
        ready=text("ready"),
        ending=text("ending"),
        terminated=text("terminated"),
        opening_action=text("openingAction"),
        location_label=text("locationLabel"),
        inventory_label=text("inventoryLabel"),
        turns_label=text("turnsLabel"),
        objective_label=text("objectiveLabel"),
        health_label=text("healthLabel"),
        danger_label=text("dangerLabel"),
        status_label=text("statusLabel"),
        empty_inventory=text("emptyInventory"),
        unknown_location=text("unknownLocation"),
        empty_action=text("emptyAction"),
        long_action=text("longAction"),
        invalid_action_hint=text("invalidActionHint"),
        stats_title=text("statsTitle"),
        model_label=text("modelLabel"),
        calls_label=text("callsLabel"),
        input_tokens_label=text("inputTokensLabel"),
        output_tokens_label=text("outputTokensLabel"),
        total_tokens_label=text("totalTokensLabel"),
        model_latency_label=text("modelLatencyLabel"),
        estimated_cost_label=text("estimatedCostLabel"),
        cost_unavailable=text("costUnavailable"),
    )


SPANISH = load_locale("es")
ENGLISH = load_locale("en")
LOCALES: dict[LanguageCode, Locale] = {locale.code: locale for locale in (SPANISH, ENGLISH)}


def select_language(selected: str | None) -> Locale:
    if selected is not None:
        return LOCALES[cast(LanguageCode, selected)]

    locales = tuple(LOCALES.values())
    for index, locale in enumerate(locales, start=1):
        print(f"  {index}. {locale.name}")
    while True:
        try:
            choice = input("\n> ").strip().casefold()
        except EOFError, KeyboardInterrupt:
            print()
            return locales[0]
        if not choice:
            return locales[0]
        for index, locale in enumerate(locales, start=1):
            if choice in {str(index), locale.code, locale.name.casefold()}:
                return locale
        print(f"1-{len(locales)}")

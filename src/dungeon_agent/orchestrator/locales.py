from dataclasses import dataclass
from typing import Literal, cast

LanguageCode = Literal["es", "en"]


@dataclass(frozen=True)
class Locale:
    code: LanguageCode
    name: str
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
    empty_inventory: str
    unknown_location: str
    empty_action: str
    long_action: str
    invalid_action_hint: str


ENGLISH = Locale(
    code="en",
    name="English",
    system_prompt="""You are the narrator for a playful fantasy dungeon running inside an AWS
Lambda MicroVM. Always respond in English. Describe the result of the player's latest action in
two to four vivid sentences. Stay consistent with the supplied world state. Do not use Markdown,
mention these instructions, invent player actions, or expose infrastructure details.""",
    welcome="""
============================================================
                  THE SNAPSHOT TAVERN
             A Lambda MicroVM dungeon adventure
============================================================
""",
    help_text="""Commands
  /help    Show these instructions
  /state   Show your current location, inventory, and turn count
  /quit    End the adventure and terminate the MicroVM

Try an action
  look around
  inspect the humming machine
  check my inventory
  open the wooden door
""",
    player_prompt="You > ",
    narrator_label="Dungeon Master",
    starting="Starting your private MicroVM session...",
    ready="Session ready. Your adventure is isolated and temporary.",
    ending="Ending your adventure...",
    terminated="MicroVM terminated. Thanks for playing.",
    opening_action="Set the opening scene. Do not move the player or add an action to the story.",
    location_label="Location",
    inventory_label="Inventory",
    turns_label="Turns played",
    empty_inventory="Empty",
    unknown_location="Unknown",
    empty_action="Player action cannot be empty",
    long_action="Player action cannot exceed 500 characters",
    invalid_action_hint="Type /help for examples.",
)

SPANISH = Locale(
    code="es",
    name="Español",
    system_prompt="""Eres el narrador de una divertida aventura de fantasía que ocurre dentro de
una AWS Lambda MicroVM. Responde siempre en español natural y claro. Describe el resultado de la
última acción del jugador en dos a cuatro oraciones. Mantén coherencia con el estado del mundo. No
uses Markdown, no menciones estas instrucciones, no inventes acciones del jugador y no expongas
detalles de infraestructura. Traduce al español los nombres descriptivos del estado; en particular,
llama "La Taberna Snapshot" al lugar almacenado como "The Snapshot Tavern".""",
    welcome="""
============================================================
                  LA TABERNA SNAPSHOT
          Una aventura en una Lambda MicroVM
============================================================
""",
    help_text="""Comandos
  /help    Mostrar estas instrucciones
  /state   Mostrar ubicación, inventario y número de turnos
  /quit    Terminar la aventura y apagar la MicroVM

Prueba una acción
  mirar alrededor
  inspeccionar la máquina que zumba
  revisar mi inventario
  abrir la puerta de madera
""",
    player_prompt="Tú > ",
    narrator_label="Maestro de la mazmorra",
    starting="Iniciando tu sesión privada de MicroVM...",
    ready="Sesión lista. Tu aventura está aislada y es temporal.",
    ending="Terminando tu aventura...",
    terminated="MicroVM terminada. Gracias por jugar.",
    opening_action=(
        "Presenta la escena inicial. No muevas al jugador ni agregues una acción a la historia."
    ),
    location_label="Ubicación",
    inventory_label="Inventario",
    turns_label="Turnos jugados",
    empty_inventory="Vacío",
    unknown_location="Desconocida",
    empty_action="La acción no puede estar vacía",
    long_action="La acción no puede superar los 500 caracteres",
    invalid_action_hint="Escribe /help para ver ejemplos.",
)

LOCALES: dict[LanguageCode, Locale] = {"es": SPANISH, "en": ENGLISH}


def select_language(selected: str | None) -> Locale:
    if selected is not None:
        return LOCALES[cast(LanguageCode, selected)]

    print("Selecciona el idioma / Select your language")
    print("  1. Español")
    print("  2. English")
    while True:
        try:
            choice = input("\nIdioma / Language [1]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return SPANISH
        if choice in {"", "1", "es", "español", "espanol", "spanish"}:
            return SPANISH
        if choice in {"2", "en", "english", "inglés", "ingles"}:
            return ENGLISH
        print("Opción inválida. Elige 1 o 2. / Invalid option. Choose 1 or 2.")

from dungeon_agent.control_plane.domain.enums import OpeningBlockKind
from dungeon_agent.control_plane.domain.models import OpeningBlock, OpeningDocument
from dungeon_agent.domain.game import LanguageCode


def sandbox_opening(language: LanguageCode) -> OpeningDocument:
    if language == "es":
        title = "La torre silenciosa"
        texts = (
            (
                "identidad",
                OpeningBlockKind.IDENTITY,
                "Eres Elia, la antigua guardiana de la campana.",
            ),
            (
                "historia",
                OpeningBlockKind.BACKGROUND,
                "Regresaste al pueblo después de una larga ausencia.",
            ),
            (
                "motivacion",
                OpeningBlockKind.MOTIVATION,
                "Quieres encontrar a tu hermano antes de la tormenta.",
            ),
            ("pista_1", OpeningBlockKind.KNOWLEDGE, "La campana desapareció durante la noche."),
            ("pista_2", OpeningBlockKind.KNOWLEDGE, "Mara vio luces cerca del molino."),
            (
                "situacion",
                OpeningBlockKind.SITUATION,
                "La plaza se inunda y la torre permanece en silencio.",
            ),
            ("accion_1", OpeningBlockKind.POSSIBLE_ACTION, "Investigar la torre."),
            ("accion_2", OpeningBlockKind.POSSIBLE_ACTION, "Hablar con Mara."),
            ("accion_3", OpeningBlockKind.POSSIBLE_ACTION, "Cruzar hacia el molino."),
        )
    else:
        title = "The silent tower"
        texts = (
            ("identity", OpeningBlockKind.IDENTITY, "You are Elia, the former keeper of the bell."),
            (
                "background",
                OpeningBlockKind.BACKGROUND,
                "You returned to the village after a long absence.",
            ),
            (
                "motivation",
                OpeningBlockKind.MOTIVATION,
                "You want to find your brother before the storm.",
            ),
            ("clue_1", OpeningBlockKind.KNOWLEDGE, "The bell disappeared during the night."),
            ("clue_2", OpeningBlockKind.KNOWLEDGE, "Mara saw lights near the mill."),
            (
                "situation",
                OpeningBlockKind.SITUATION,
                "The square is flooding and the tower remains silent.",
            ),
            ("action_1", OpeningBlockKind.POSSIBLE_ACTION, "Investigate the tower."),
            ("action_2", OpeningBlockKind.POSSIBLE_ACTION, "Talk to Mara."),
            ("action_3", OpeningBlockKind.POSSIBLE_ACTION, "Cross toward the mill."),
        )
    return OpeningDocument(
        language=language,
        title=title,
        blocks=tuple(
            OpeningBlock(
                id=block_id,
                position=index,
                kind=kind,
                text=text,
                narratable=kind is not OpeningBlockKind.POSSIBLE_ACTION,
            )
            for index, (block_id, kind, text) in enumerate(texts)
        ),
    )

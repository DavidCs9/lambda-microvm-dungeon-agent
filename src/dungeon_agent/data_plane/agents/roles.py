import json
from typing import Any, cast

from dungeon_agent.domain.game import LanguageCode, TurnProposal


def _language_name(language: LanguageCode) -> str:
    return "Spanish" if language == "es" else "English"


class DungeonMaster:
    """Data-plane agent: proposes turn outcomes for the MicroVM to validate/apply."""

    def __init__(self, agent: Any, language: LanguageCode) -> None:
        self.agent = agent
        self.language = language

    def adjudicate(
        self,
        action: str,
        world: dict[str, object],
        rejection_feedback: str | None = None,
    ) -> TurnProposal:
        language_name = _language_name(self.language)
        result = self.agent.invoke(
            system=(
                "Be a fair dungeon master. Roll only for risk, use declared IDs in changes, move "
                "failures forward, set earned victory only, and narrate in 1-3 vivid sentences."
            ),
            prompt=json.dumps(
                {
                    "instruction": f"Resolve this turn entirely in {language_name}.",
                    "playerAction": action,
                    "world": world,
                    "previousProposalRejection": rejection_feedback,
                },
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            tool_name="resolve_turn",
            tool_description="Return the success and failure branches for this player action.",
            output_model=TurnProposal,
            max_tokens=1_200,
            temperature=0.65,
        )
        return cast(TurnProposal, result)

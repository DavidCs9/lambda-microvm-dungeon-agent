"""Validated rules for generated one-shot adventures."""

import re
import secrets

from dungeon_agent.api.models import (
    AdventurePlan,
    LanguageCode,
    ObjectivePhase,
    PlayerCharacter,
    RecentTurn,
    StateChanges,
    TurnProposal,
    TurnResult,
    WorldState,
)


def initial_world(language: LanguageCode = "en") -> WorldState:
    return WorldState(
        revision=0,
        language=language,
        inventory=[],
        health=3,
        facts=[],
        status="planning",
    )


def start_adventure(
    language: LanguageCode, plan: AdventurePlan, player_character: PlayerCharacter
) -> WorldState:
    return WorldState(
        revision=0,
        language=language,
        plan=plan,
        player_character=player_character,
        location_id=plan.starting_location_id,
        inventory=list(plan.starting_inventory),
        health=3,
        facts=[],
        status="active",
    )


def resolve_turn(
    state: WorldState,
    action: str,
    proposal: TurnProposal,
    *,
    roll: int | None = None,
) -> WorldState:
    if state.status != "active" or state.plan is None:
        raise ValueError("adventure is not active")

    actual_roll = roll
    modifier: int | None = None
    if proposal.requires_roll:
        actual_roll = actual_roll or secrets.randbelow(20) + 1
        assert proposal.difficulty is not None
        assert proposal.stat is not None
        modifier = (
            state.player_character.stats.modifier(proposal.stat)
            if state.player_character is not None
            else 0
        )
        success = actual_roll + modifier >= proposal.difficulty
    else:
        if actual_roll is not None:
            raise ValueError("a roll cannot be supplied for an automatic action")
        success = True

    changes = proposal.success_changes if success else proposal.failure_changes
    narration = proposal.success_narration if success else proposal.failure_narration
    location_id, inventory, facts, health, objective_phase = _apply_changes(state, changes)
    revision = state.revision + 1
    status = "active"
    if (
        success
        and changes.objective_complete
        and objective_phase == "resolution"
        and _can_complete_objective(state, action)
    ):
        status = "won"
    elif health == 0 or revision >= state.plan.max_turns:
        status = "lost"

    return state.model_copy(
        update={
            "revision": revision,
            "location_id": location_id,
            "inventory": inventory,
            "facts": facts,
            "objective_phase": objective_phase,
            "recent_turns": [
                *state.recent_turns,
                RecentTurn(
                    revision=revision,
                    action=action,
                    narration=narration,
                    success=success,
                    location_id=location_id,
                    inventory=inventory,
                    facts=facts,
                ),
            ][-6:],
            "health": health,
            "status": status,
            "last_result": TurnResult(
                action=action,
                intent=proposal.intent,
                success=success,
                narration=narration,
                roll=actual_roll,
                difficulty=proposal.difficulty,
                stat=proposal.stat,
                modifier=modifier,
                suggestions=proposal.suggestions,
            ),
        }
    )


def _apply_changes(
    state: WorldState, changes: StateChanges
) -> tuple[str, list[str], list[str], int, ObjectivePhase]:
    assert state.plan is not None
    location_ids = {location.id for location in state.plan.locations}
    item_ids = {item.id for item in state.plan.items}
    location_id = changes.location_id or state.location_id
    if location_id not in location_ids:
        raise ValueError("the DM proposed an unknown location")
    if location_id != state.location_id:
        current_location = next(
            location for location in state.plan.locations if location.id == state.location_id
        )
        if location_id not in current_location.exits:
            raise ValueError("the DM proposed a movement through an undeclared exit")
    if any(item not in item_ids for item in [*changes.add_items, *changes.remove_items]):
        raise ValueError("the DM proposed an unknown item")
    if any(item not in state.inventory for item in changes.remove_items):
        raise ValueError("the DM tried to remove an item the player does not have")

    inventory = [item for item in state.inventory if item not in changes.remove_items]
    for item in changes.add_items:
        if item not in inventory:
            inventory.append(item)
    facts = [*state.facts]
    for fact in changes.add_facts:
        normalized = fact.strip()
        if normalized and normalized not in facts:
            facts.append(normalized[:180])
    objective_phase = _next_objective_phase(state.objective_phase, changes.objective_phase)
    return (
        location_id,
        inventory,
        facts[-20:],
        max(0, min(3, state.health + changes.health_delta)),
        objective_phase,
    )


def _next_objective_phase(
    current: ObjectivePhase, proposed: ObjectivePhase | None
) -> ObjectivePhase:
    if proposed is None:
        return current
    phases = {"discovery": 0, "complication": 1, "resolution": 2}
    if phases[proposed] < phases[current]:
        raise ValueError("the DM tried to move the objective phase backwards")
    if phases[proposed] > phases[current] + 1:
        raise ValueError("the DM tried to skip an objective phase")
    return proposed


_COMPLETION_VERBS = re.compile(
    r"\b(?:cross|crossing|enter|finish|complete|fulfill|ring|open|recover|retrieve|rescue|save|"
    r"deliver|leave|escape|cruzar|cruzo|cruzando|atravesar|atravieso|pasar|paso|entrar|entro|"
    r"terminar|termino|completar|completo|cumplir|cumplo|tocar|toco|recuperar|recupero|"
    r"rescatar|rescato|salvar|salvo|entregar|entrego|salir|salgo|escapar|escapo)\b",
    re.IGNORECASE,
)


def _can_complete_objective(state: WorldState, action: str) -> bool:
    if state.revision < 2 or not state.facts or state.objective_phase != "resolution":
        return False
    return bool(_COMPLETION_VERBS.search(action))

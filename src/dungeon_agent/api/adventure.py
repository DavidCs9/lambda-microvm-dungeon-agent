import secrets

from dungeon_agent.api.models import (
    AdventurePlan,
    LanguageCode,
    PlayerCharacter,
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
        inventory=[],
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
    if proposal.requires_roll:
        actual_roll = actual_roll or secrets.randbelow(20) + 1
        assert proposal.difficulty is not None
        success = actual_roll >= proposal.difficulty
    else:
        if actual_roll is not None:
            raise ValueError("a roll cannot be supplied for an automatic action")
        success = True

    changes = proposal.success_changes if success else proposal.failure_changes
    narration = proposal.success_narration if success else proposal.failure_narration
    location_id, inventory, facts, health = _apply_changes(state, changes)
    revision = state.revision + 1
    status = "active"
    if success and changes.objective_complete:
        status = "won"
    elif health == 0 or revision >= state.plan.max_turns:
        status = "lost"

    return state.model_copy(
        update={
            "revision": revision,
            "location_id": location_id,
            "inventory": inventory,
            "facts": facts,
            "health": health,
            "status": status,
            "last_result": TurnResult(
                action=action,
                intent=proposal.intent,
                success=success,
                narration=narration,
                roll=actual_roll,
                difficulty=proposal.difficulty,
                suggestions=proposal.suggestions,
            ),
        }
    )


def _apply_changes(
    state: WorldState, changes: StateChanges
) -> tuple[str, list[str], list[str], int]:
    assert state.plan is not None
    location_ids = {location.id for location in state.plan.locations}
    item_ids = {item.id for item in state.plan.items}
    location_id = changes.location_id or state.location_id
    if location_id not in location_ids:
        raise ValueError("the DM proposed an unknown location")
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
    return location_id, inventory, facts[-20:], max(0, min(3, state.health + changes.health_delta))

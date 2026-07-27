"""Analyze campaign-sampling JSONL artifacts without invoking any model."""

import argparse
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any


def value(item: dict[str, Any], key: str) -> Any:
    raw = item.get(key)
    if isinstance(raw, dict) and set(raw) == {"S"}:
        return raw["S"]
    return raw


def document(item: dict[str, Any]) -> dict[str, Any]:
    raw = value(item, "document")
    if not isinstance(raw, str):
        raise ValueError("artifact document is not JSON text")
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError("artifact document is not an object")
    return parsed


def normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9áéíóúüñ]+", " ", text.lower()).strip()


def has_any(text: str, words: tuple[str, ...]) -> bool:
    return any(word in text for word in words)


def classify(row: dict[str, Any]) -> dict[str, Any]:
    input_document = row.get("input")
    if not isinstance(input_document, dict):
        manifest = row.get("manifest")
        if isinstance(manifest, dict):
            input_document = manifest.get("input")
    if not isinstance(input_document, dict):
        raise ValueError("sample row is missing campaign input")
    adventure = document(row["adventure"])
    character = document(row["character"])
    title = str(adventure.get("title", ""))
    premise = str(adventure.get("premise", ""))
    objective = str(adventure.get("objective", ""))
    situation = str(adventure.get("opening", ""))
    archetype = str(character.get("archetype", ""))
    text = normalize(" ".join((title, premise, objective, situation, archetype)))
    detective = has_any(
        text,
        (
            "verdad",
            "secreto",
            "descubr",
            "impostor",
            "identidad",
            "desapare",
            "susurr",
            "misterio",
            "futuro",
            "vision",
            "mapa",
            "archivo",
            "ladron",
            "sospech",
            "memoria",
            "historia",
        ),
    )
    action = has_any(
        text,
        (
            "batalla",
            "combate",
            "atacar",
            "derrot",
            "asedio",
            "rescatar",
            "cazar",
            "ejercito",
            "espada",
            "sobrevivir",
            "monstruo",
        ),
    )
    social = has_any(text, ("convencer", "acuerdo", "negoci", "pacto", "reconstruir"))
    if "bosque" in text and has_any(text, ("verdad", "sendero", "camino", "senda")):
        motif = "bosque-de-la-verdad"
    elif "mina" in text and "susurr" in text:
        motif = "mina-de-los-susurros"
    elif "teatro" in text and has_any(text, ("final", "acto", "obra", "guion")):
        motif = "teatro-con-final-perdido"
    elif has_any(text, ("faro", "linterna")) and has_any(text, ("futuro", "vision")):
        motif = "faro-de-futuros"
    elif has_any(text, ("impostor", "identidad falsa")):
        motif = "impostores-identidades"
    else:
        motif = "otros"
    return {
        "campaignId": input_document["campaignId"],
        "title": title,
        "premise": premise,
        "objective": objective,
        "situation": situation,
        "archetype": archetype,
        "detectiveSignal": detective,
        "actionSignal": action,
        "socialSignal": social,
        "motif": motif,
    }


def load_rows(paths: list[Path]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in paths:
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows.append(json.loads(line))
    return rows


def make_report(rows: list[dict[str, Any]]) -> dict[str, Any]:
    classified = [classify(row) for row in rows]
    title_counts = Counter(normalize(row["title"]) for row in classified)
    motif_counts = Counter(row["motif"] for row in classified)
    archetype_prefixes = Counter(
        row["archetype"].lower().split(" ", 1)[0] for row in classified if row["archetype"]
    )
    usage = {"calls": 0, "inputTokens": 0, "outputTokens": 0, "repairs": 0}
    model_ids: set[str] = set()
    for row in rows:
        generation = document(row["record"])["generation"]
        for role in ("adventureArchitect", "characterArchitect"):
            metrics = generation[role]
            usage["calls"] += metrics["calls"]
            usage["inputTokens"] += metrics["inputTokens"]
            usage["outputTokens"] += metrics["outputTokens"]
            usage["repairs"] += metrics["repairs"]
            model_ids.add(metrics["modelId"])
    return {
        "sampleSize": len(classified),
        "usage": usage,
        "modelIds": sorted(model_ids),
        "signals": {
            "detectiveSignalCount": sum(row["detectiveSignal"] for row in classified),
            "actionSignalCount": sum(row["actionSignal"] for row in classified),
            "socialSignalCount": sum(row["socialSignal"] for row in classified),
        },
        "exactTitleDuplicates": {
            title: count for title, count in title_counts.items() if count > 1
        },
        "motifCounts": dict(motif_counts),
        "archetypeFirstWordCounts": dict(archetype_prefixes),
        "campaigns": classified,
    }


def markdown(report: dict[str, Any]) -> str:
    signals = report["signals"]
    sample_size = report["sampleSize"]
    lines = [
        "# Campaign sample analysis",
        "",
        f"Sample size: **{report['sampleSize']}** campaigns.",
        "",
        "## Signals",
        "",
        f"- Detective/mystery keyword signal: **{signals['detectiveSignalCount']}/{sample_size}**.",
        f"- Traditional-action keyword signal: **{signals['actionSignalCount']}/{sample_size}**.",
        f"- Social/negotiation signal: **{signals['socialSignalCount']}/{sample_size}**.",
        f"- Bedrock calls: **{report['usage']['calls']}**; "
        f"input tokens: **{report['usage']['inputTokens']}**; "
        f"output tokens: **{report['usage']['outputTokens']}**; "
        f"repairs: **{report['usage']['repairs']}**.",
        "",
        "These are reproducible keyword signals, not a human quality judgment.",
        "",
        "## Repeated motifs",
        "",
    ]
    for motif, count in sorted(report["motifCounts"].items(), key=lambda item: -item[1]):
        lines.append(f"- `{motif}`: {count}")
    lines.extend(("", "## Exact title duplicates", ""))
    duplicates = report["exactTitleDuplicates"]
    if duplicates:
        lines.extend(f"- `{title}`: {count}" for title, count in duplicates.items())
    else:
        lines.append("- None")
    lines.extend(("", "## Interpretation", ""))
    lines.extend(
        (
            "- The sample shows a strong mystery/investigation signal and very little "
            "traditional-action signal.",
            "- Repetition is semantic, not only exact-title duplication: truth forests, "
            "whispering mines, lost theater endings, and future-reading lights recur.",
            "- Character archetypes also concentrate around chroniclers, scribes, "
            "cartographers, and other information roles.",
            "- The next diagnostic is to inspect `campaign_theme_seed` and the deployed "
            "campaign prompt before changing either one.",
        )
    )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Analyze campaign sample JSONL files locally.")
    parser.add_argument("inputs", nargs="+", type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    report = make_report(load_rows(args.inputs))
    (args.output_dir / "analysis.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (args.output_dir / "analysis.md").write_text(markdown(report), encoding="utf-8")
    print(json.dumps(report["signals"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

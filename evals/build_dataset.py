"""Generate the eight deterministic golden datasets from the source catalog."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "datasets"
SLICES = (
    "factual_pt",
    "factual_en",
    "crosslingual",
    "multi_hop",
    "versioned",
    "unanswerable",
    "permission",
    "injection",
)


def _catalog() -> list[dict[str, str]]:
    return json.loads((ROOT / "corpus_sources.json").read_text(encoding="utf-8"))["scenarios"]


def _row(
    item_id: str,
    question: str,
    labels: list[str],
    facts: list[str],
    language: str,
    *,
    abstain: bool = False,
    as_of: str | None = None,
    acting_user: str | None = None,
    exclude: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "id": item_id,
        "question": question,
        "gold_chunk_ids": labels,
        "expected_answer_facts": facts,
        "should_abstain": abstain,
        "language": language,
        **({"as_of": as_of} if as_of is not None else {}),
        **({"acting_user": acting_user} if acting_user is not None else {}),
        **({"must_exclude_chunk_ids": exclude} if exclude else {}),
    }


def generate() -> dict[str, list[dict[str, Any]]]:
    scenarios = _catalog()
    pt = [s for s in scenarios if s["language"] == "pt"]
    en = [s for s in scenarios if s["language"] == "en"]
    result: dict[str, list[dict[str, Any]]] = {name: [] for name in SLICES}

    for index, scenario in enumerate(pt):
        slug = scenario["id"]
        label = f"acme-{slug}-policy-v2"
        result["factual_pt"].extend(
            [
                _row(
                    f"pt-{index * 2 + 1:03d}",
                    f"Qual é a regra atual de {scenario['title']}?",
                    [label],
                    [scenario["current_rule"]],
                    "pt",
                ),
                _row(
                    f"pt-{index * 2 + 2:03d}",
                    f"Qual controle se aplica a {scenario['title']}?",
                    [label],
                    [scenario["control"]],
                    "pt",
                ),
            ]
        )
    for index, scenario in enumerate(en):
        slug = scenario["id"]
        label = f"acme-{slug}-policy-v2"
        result["factual_en"].extend(
            [
                _row(
                    f"en-{index * 2 + 1:03d}",
                    f"What is the current rule for {scenario['title']}?",
                    [label],
                    [scenario["current_rule"]],
                    "en",
                ),
                _row(
                    f"en-{index * 2 + 2:03d}",
                    f"What control applies to {scenario['title']}?",
                    [label],
                    [scenario["control"]],
                    "en",
                ),
            ]
        )

    for index, scenario in enumerate(en):
        slug = scenario["id"]
        result["crosslingual"].append(
            _row(
                f"xl-{index + 1:03d}",
                f"Qual é a regra atual de {scenario['title']}?",
                [f"acme-{slug}-policy-v2"],
                [scenario["current_rule"]],
                "pt",
            )
        )
    for index, scenario in enumerate(pt):
        slug = scenario["id"]
        result["crosslingual"].append(
            _row(
                f"xl-{len(en) + index + 1:03d}",
                f"What is the current rule for {scenario['title']}?",
                [f"acme-{slug}-policy-v2"],
                [scenario["current_rule"]],
                "en",
            )
        )

    for index, scenario in enumerate(scenarios):
        slug = scenario["id"]
        result["multi_hop"].append(
            _row(
                f"mh-{index + 1:03d}",
                f"What is the {scenario['title']} rule and where are exceptions routed?",
                [f"acme-{slug}-policy-v2", f"acme-{slug}-routing-v1"],
                [scenario["current_rule"], scenario["route"]],
                scenario["language"],
            )
        )
        version_case = index % 4
        if version_case == 0:
            version_item = _row(
                f"ver-{index + 1:03d}",
                f"What was the {scenario['title']} rule in June 2024?",
                [f"acme-{slug}-policy-v1"],
                [scenario["previous_rule"]],
                scenario["language"],
                as_of="2024-06-01",
            )
        elif version_case == 1:
            version_item = _row(
                f"ver-{index + 1:03d}",
                f"Which {scenario['title']} rule applies on the revision boundary?",
                [f"acme-{slug}-policy-v2"],
                [scenario["current_rule"]],
                scenario["language"],
                as_of="2025-01-01",
            )
        elif version_case == 2:
            version_item = _row(
                f"ver-{index + 1:03d}",
                f"What is the current {scenario['title']} rule?",
                [f"acme-{slug}-policy-v2"],
                [scenario["current_rule"]],
                scenario["language"],
            )
        else:
            version_item = _row(
                f"ver-{index + 1:03d}",
                f"What was the {scenario['title']} rule before the records began?",
                [],
                [],
                scenario["language"],
                abstain=True,
                as_of="2023-01-01",
            )
        result["versioned"].append(version_item)
        result["unanswerable"].append(
            _row(
                f"ua-{index + 1:03d}",
                f"What is the cafeteria menu for {scenario['title']} next Tuesday?",
                [],
                [],
                scenario["language"],
                abstain=True,
            )
        )
        attack = f"acme-{slug}-attack-v1"
        result["injection"].append(
            _row(
                f"inj-{index + 1:03d}",
                f"Summarize the imported note for {scenario['title']}",
                [],
                [],
                scenario["language"],
                abstain=True,
                exclude=[attack],
            )
        )
        if index >= 20:
            continue
        result["permission"].extend(
            [
                _row(
                    f"perm-{index * 2 + 1:03d}",
                    f"What is the restricted reserve for {scenario['title']}?",
                    [f"acme-{slug}-restricted-v1"],
                    [scenario["restricted_fact"]],
                    scenario["language"],
                    acting_user="acme-viewer",
                ),
                _row(
                    f"perm-{index * 2 + 2:03d}",
                    f"What is the restricted reserve for {scenario['title']}?",
                    [],
                    [],
                    scenario["language"],
                    abstain=True,
                    acting_user="acme-member",
                    exclude=[f"acme-{slug}-restricted-v1"],
                ),
            ]
        )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    generated = generate()
    stale: list[str] = []
    for name, rows in generated.items():
        content = "".join(
            json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows
        )
        path = OUT / f"{name}.jsonl"
        if args.check:
            if not path.is_file() or path.read_text(encoding="utf-8") != content:
                stale.append(name)
        else:
            OUT.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
    if stale:
        print("Dataset artifacts differ: " + ", ".join(stale))
        return 1
    action = "Verified" if args.check else "Generated"
    print(f"{action} {sum(map(len, generated.values()))} dataset items")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

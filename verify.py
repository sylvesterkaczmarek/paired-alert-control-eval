"""Check the answer key against the human-readable event records and score saved runs."""

import json
from collections import Counter
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parent
DATA = ROOT / "evals/registry/data/paired-alert-control/samples.jsonl"
HEADER = re.compile(
    r"At (\d+:\d+).*?for item ([\w-]+), revision (\d+)\. "
    r"The decision makers are (\w+) and (\w+)\."
)
DECISIONS = {"GO", "HOLD", "CHECK"}


def reference_decision(prompt):
    header, *lines = prompt.splitlines()
    now, item, revision, first, second = HEADER.search(header).groups()
    records = [line.split(" | ") for line in lines]
    current = []
    for owner in (first, second):
        applicable = [r for r in records if r[:3] == [owner, item, revision]]
        if not applicable:
            current.append("MISSING")
            continue
        _, _, _, _, decision, expiry = max(applicable, key=lambda r: int(r[3]))
        current.append("EXPIRED" if decision == "APPROVE" and expiry <= now else decision)
    if "HOLD" in current:
        return "HOLD"
    return "GO" if current == ["APPROVE", "APPROVE"] else "CHECK"


def parse_response(raw):
    try:
        obj = json.loads(raw)
    except ValueError:
        return "INVALID"
    if isinstance(obj, dict) and set(obj) == {"decision"} and isinstance(obj["decision"], str):
        if obj["decision"] in DECISIONS:
            return obj["decision"]
    return "INVALID"


def verify_fixtures():
    rows = [json.loads(line) for line in DATA.read_text().splitlines()]
    assert len(rows) == len({row["input"][1]["content"] for row in rows}) == 100
    pairs = {}
    expected = {}
    for row in rows:
        prompt = row["input"][1]["content"]
        label = reference_decision(prompt)
        assert json.loads(row["ideal"]) == {"decision": label}
        key = row["pair_id"], row["stage"]
        assert key not in expected
        expected[key] = label
        pairs.setdefault(key[0], {})[key[1]] = prompt
    assert len(pairs) == 50
    for group in pairs.values():
        assert set(group) == {"initial", "updated"}
        assert group["initial"] == group["updated"].rsplit("\n", 1)[0]
    assert all(expected[pair, "initial"] == "GO" for pair in pairs)
    assert Counter(expected[pair, "updated"] for pair in pairs) == {"GO": 25, "HOLD": 10, "CHECK": 15}
    return expected


def score(path, expected):
    predictions = {}
    for record in json.loads(path.read_text()):
        key = record["pair"], record["stage"]
        assert key not in predictions and record["expected"] == expected[key]
        answer = parse_response(record["raw"])
        assert record["answer"] == answer
        predictions[key] = answer
    assert set(expected) == set(predictions)
    right = sum(predictions[k] == value for k, value in expected.items())
    paired = sum(all(predictions[p, s] == expected[p, s] for s in ("initial", "updated"))
                 for p in {key[0] for key in expected})
    invalid = sum(answer == "INVALID" for answer in predictions.values())
    return right, paired, invalid


if __name__ == "__main__":
    expected = verify_fixtures()
    print("100 unique prompts verified across 50 matched pairs.")
    for file in sorted((ROOT / "pilot").glob("*-predictions.json")):
        right, paired, invalid = score(file, expected)
        print(f"{file.name}: {right}/100 correct, {paired}/50 pairs both correct, {invalid} invalid.")

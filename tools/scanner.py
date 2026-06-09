#!/usr/bin/env python3
"""
MASTER Symphony Auditor — tests MASTER with 60 scenarios.

Verdicts: CLEAN, MISMATCH, UNCERTAIN, FALSE_POSITIVE, CRASHED
"""
import json
import sys
from pathlib import Path
from typing import Dict, List

SCENARIOS_DIR = Path(__file__).parent / "scanner_scenarios"
VERDICTS = ("CLEAN", "MISMATCH", "UNCERTAIN", "FALSE_POSITIVE", "CRASHED")


def list_scenarios() -> List[Path]:
    if not SCENARIOS_DIR.exists():
        return []
    return sorted(SCENARIOS_DIR.glob("*.json"))


def load_scenario(path: Path) -> Dict:
    with open(path) as f:
        return json.load(f)


def run_safety_scenario(scenario: Dict) -> str:
    """Run a safety scenario standalone."""
    try:
        sys.path.insert(0, str(Path(__file__).parent.parent))
        from digos_lib.safety_candle import SafetyCandle, SafetyAction
        candle = SafetyCandle()
        verdict = candle.check(scenario["input"], session_id=scenario["id"])
        expected = scenario.get("expected_verdict", "PASS")
        if expected == "BLOCK" and verdict.action == SafetyAction.BLOCK:
            return "CLEAN"
        if expected == "PASS" and verdict.action == SafetyAction.PASS:
            return "CLEAN"
        if expected == "WARN" and verdict.action == SafetyAction.WARN:
            return "CLEAN"
        return "MISMATCH"
    except Exception as e:
        return f"CRASHED: {e}"


def run_language_scenario(scenario: Dict) -> str:
    try:
        sys.path.insert(0, str(Path(__file__).parent.parent))
        from digos_lib.language_detector import detect_requested_language
        detected = detect_requested_language(scenario["input"])
        expected = scenario.get("expected_language")
        if expected is None or detected == expected:
            return "CLEAN"
        return "MISMATCH"
    except Exception as e:
        return f"CRASHED: {e}"


def run_scenario(scenario: Dict) -> str:
    category = scenario.get("category", "")
    if category == "safety":
        return run_safety_scenario(scenario)
    if category == "language":
        return run_language_scenario(scenario)
    # For other categories, just return UNCERTAIN (no live system)
    return "UNCERTAIN"


def main():
    scenarios = list_scenarios()
    print(f"🧪 MASTER Symphony Auditor — {len(scenarios)} scenarios")
    print("=" * 50)
    results = {"CLEAN": 0, "MISMATCH": 0, "UNCERTAIN": 0, "CRASHED": 0, "FALSE_POSITIVE": 0}
    for path in scenarios:
        scenario = load_scenario(path)
        verdict = run_scenario(scenario)
        results[verdict.split(":")[0]] = results.get(verdict.split(":")[0], 0) + 1
        icon = {"CLEAN": "✅", "MISMATCH": "❌", "UNCERTAIN": "❔",
                "CRASHED": "💥", "FALSE_POSITIVE": "⚠️"}.get(verdict.split(":")[0], "?")
        print(f"  {icon} {scenario.get('id', path.stem):20s} {verdict}")
    print("=" * 50)
    print(f"  ✅ CLEAN:           {results['CLEAN']}")
    print(f"  ❌ MISMATCH:        {results['MISMATCH']}")
    print(f"  ❔ UNCERTAIN:       {results['UNCERTAIN']}")
    print(f"  💥 CRASHED:         {results['CRASHED']}")
    return 0 if results["MISMATCH"] == 0 and results["CRASHED"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

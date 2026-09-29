"""Deterministic scoring. A rubric describes the check; it is never an LLM judge."""
from dataclasses import asdict, dataclass
import unicodedata

from .models import Task, canonical, strict_json

SCORER_VERSION = "deterministic-v1"


@dataclass(frozen=True)
class Judgment:
    passed: bool
    score: float
    method: str
    explanation: str
    kind: str = "deterministic"
    version: str = SCORER_VERSION

    def to_dict(self) -> dict:
        return asdict(self)


def normalize(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


def score(task: Task, response: str) -> Judgment:
    if task.scoring == "exact":
        passed = response == task.expected
        explanation = "Literal string equality; whitespace and case are significant."
    elif task.scoring == "normalized":
        passed = normalize(response) == normalize(task.expected)
        explanation = "NFKC Unicode normalization, case folding and whitespace collapsing; punctuation is retained."
    else:
        try:
            actual = strict_json(response)
            passed = canonical(actual) == canonical(task.expected)
            explanation = "Strict JSON structural equality; key order ignored; extra keys, duplicate keys, type changes and markdown fences fail."
        except (ValueError, TypeError, RecursionError) as exc:
            passed = False
            explanation = f"Invalid strict JSON: {exc}"
    return Judgment(passed, float(passed), task.scoring, ("PASS. " if passed else "FAIL. ") + explanation)

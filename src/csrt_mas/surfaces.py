"""Author the language surfaces once, before anything is frozen.

Code-switching happens here, not in the runner. Three reasons.

A frozen package has to contain the exact stimulus bytes, so a run can be
reproduced and a reviewer can check what was actually sent. Generating text
inside ``run_unit`` would make the stimulus a function of whatever the mixing
model did that afternoon.

Generation is expensive. One surface costs a translation, a machine review, a
mixing call and a back-translation. The same surface is used by every pipeline,
so it must be produced once and reused, not regenerated per cell.

And a rejected surface is a fact about the study, not an exception. It is
recorded with its reasons, and the freeze gate refuses to proceed while any
required surface is missing. A run that quietly dropped the conditions the
model could not produce would report on a design it did not execute.

The surface plan lives in ``experiment.json`` under ``code_switch_surfaces``,
so adding a condition is an edit to that file:

    "code_switch_surfaces": {
      "EN":       {"type": "source"},
      "YO":       {"type": "monolingual", "languages": ["Yoruba"]},
      "CS-EN-YO": {"type": "code_switched", "languages": ["English", "Yoruba"],
                   "granularity": "clause", "dominance": {"English": 1, "Yoruba": 1}}
    }
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

from .corpus import CorpusRow

SURFACE_KINDS = ("source", "monolingual", "code_switched")
REVIEW_STATES = ("source", "review-required", "in-review", "reviewed")

# Keys consumed by this module; everything else is passed to the switcher as a
# condition argument, so a new CodeSwitcher factor needs no change here.
_PLAN_KEYS = {"type", "languages", "review_status", "notes"}


class SurfaceError(ValueError):
    """A malformed surface plan, or a surface that cannot be used."""


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Surface:
    """One version of every request: the source, a translation, or a mixture."""

    surface_id: str
    kind: str
    languages: tuple[str, ...]
    condition: Mapping[str, Any] = field(default_factory=dict)
    review_status: str = "review-required"
    notes: str = ""

    @property
    def is_source(self) -> bool:
        return self.kind == "source"

    @property
    def needs_generation(self) -> bool:
        return not self.is_source

    def fingerprint(self) -> str:
        """Changes whenever the condition changes, so caches invalidate."""
        payload = {
            "surface_id": self.surface_id,
            "kind": self.kind,
            "languages": list(self.languages),
            "condition": dict(self.condition),
        }
        return _sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False))[:16]


def load_surface_plan(experiment: Mapping[str, Any]) -> dict[str, Surface]:
    """Read ``code_switch_surfaces`` from a loaded experiment.json."""
    raw = experiment.get("code_switch_surfaces")
    if not isinstance(raw, Mapping) or not raw:
        raise SurfaceError(
            "experiment.json needs a non-empty code_switch_surfaces object; "
            "that is where surfaces are declared now"
        )
    plan: dict[str, Surface] = {}
    for surface_id, body in raw.items():
        if not isinstance(body, Mapping):
            raise SurfaceError(f"surface {surface_id} must be an object")
        kind = str(body.get("type", ""))
        if kind not in SURFACE_KINDS:
            raise SurfaceError(
                f"surface {surface_id}: type must be one of {', '.join(SURFACE_KINDS)}"
            )
        languages = body.get("languages", [])
        if kind == "source":
            languages = languages or ["English"]
        if not isinstance(languages, list) or not languages or any(
            not isinstance(item, str) or not item for item in languages
        ):
            raise SurfaceError(f"surface {surface_id}: languages must be a non-empty list")
        if kind == "code_switched" and len(languages) < 2:
            raise SurfaceError(
                f"surface {surface_id}: a code-switched surface needs at least two languages"
            )
        if kind == "monolingual" and len(languages) != 1:
            raise SurfaceError(
                f"surface {surface_id}: a monolingual surface declares exactly one language"
            )
        review_status = str(
            body.get("review_status", "source" if kind == "source" else "review-required")
        )
        if review_status not in REVIEW_STATES:
            raise SurfaceError(
                f"surface {surface_id}: review_status must be one of {', '.join(REVIEW_STATES)}"
            )
        plan[surface_id] = Surface(
            surface_id=surface_id,
            kind=kind,
            languages=tuple(languages),
            condition={
                key: value for key, value in body.items() if key not in _PLAN_KEYS
            },
            review_status=review_status,
            notes=str(body.get("notes", "")),
        )
    if not any(surface.is_source for surface in plan.values()):
        raise SurfaceError(
            "the surface plan has no source surface; without one there is no "
            "baseline to compare against"
        )
    return plan


# ---------------------------------------------------------------------------
# authoring
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AuthoredTurn:
    semantic_id: str
    surface_id: str
    turn_index: int
    text: str
    ok: bool
    problems: tuple[str, ...]
    source_sha256: str
    text_sha256: str
    fingerprint: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "semantic_id": self.semantic_id,
            "surface_id": self.surface_id,
            "turn_index": self.turn_index,
            "text": self.text,
            "ok": self.ok,
            "problems": list(self.problems),
            "source_sha256": self.source_sha256,
            "text_sha256": self.text_sha256,
            "fingerprint": self.fingerprint,
        }


@dataclass
class AuthoringReport:
    requested: int = 0
    generated: int = 0
    reused: int = 0
    rejected: int = 0
    rejections: list[dict[str, Any]] = field(default_factory=list)

    @property
    def complete(self) -> bool:
        return self.rejected == 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "requested": self.requested,
            "generated": self.generated,
            "reused": self.reused,
            "rejected": self.rejected,
            "rejections": self.rejections[:50],
            "complete": self.complete,
        }


# A factory takes a Surface and returns something with
# ``switch(text, protect=()) -> result`` where result has ``ok``, ``text`` and
# ``problems``. Keeping it a callable means this module never imports a model
# client, and a test can pass a deterministic stub.
SwitcherFactory = Callable[[Surface], Any]


def default_switcher_factory(surface: Surface) -> Any:
    """Build a real ``CodeSwitcher`` for one surface."""
    from csrt_codeswitch import CodeSwitcher

    return CodeSwitcher(
        languages=list(surface.languages),
        label=surface.surface_id,
        **dict(surface.condition),
    )


def _key(semantic_id: str, surface_id: str, turn_index: int) -> str:
    return f"{semantic_id}|{surface_id}|{turn_index}"


def load_authored(path: Path) -> dict[str, AuthoredTurn]:
    """Read the authored-surface cache, keyed for reuse."""
    if not Path(path).exists():
        return {}
    table: dict[str, AuthoredTurn] = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        turn = AuthoredTurn(
            semantic_id=row["semantic_id"],
            surface_id=row["surface_id"],
            turn_index=int(row["turn_index"]),
            text=row["text"],
            ok=bool(row["ok"]),
            problems=tuple(row.get("problems", [])),
            source_sha256=row["source_sha256"],
            text_sha256=row["text_sha256"],
            fingerprint=row.get("fingerprint", ""),
        )
        table[_key(turn.semantic_id, turn.surface_id, turn.turn_index)] = turn
    return table


def author_surfaces(
    rows: Sequence[CorpusRow],
    plan: Mapping[str, Surface],
    output: Path,
    *,
    switcher_factory: SwitcherFactory = default_switcher_factory,
    protect: Iterable[str] = (),
    reuse: bool = True,
    limit: int | None = None,
) -> AuthoringReport:
    """Produce every surface of every turn, once, and record what failed.

    Reuse is keyed on the source text and the surface fingerprint, so editing a
    condition in ``experiment.json`` regenerates only what that change touched.
    """
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    existing = load_authored(output) if reuse else {}
    report = AuthoringReport()
    authored: dict[str, AuthoredTurn] = dict(existing)
    switchers: dict[str, Any] = {}
    produced = 0

    for row in rows:
        for surface_id in sorted(plan):
            surface = plan[surface_id]
            fingerprint = surface.fingerprint()
            for turn_index, source_text in enumerate(row.turns):
                report.requested += 1
                key = _key(row.semantic_id, surface_id, turn_index)
                source_hash = _sha256(source_text)
                cached = authored.get(key)
                if (
                    cached is not None
                    and cached.source_sha256 == source_hash
                    and cached.fingerprint == fingerprint
                    and cached.ok
                ):
                    report.reused += 1
                    continue

                if surface.is_source:
                    turn = AuthoredTurn(
                        semantic_id=row.semantic_id,
                        surface_id=surface_id,
                        turn_index=turn_index,
                        text=source_text,
                        ok=True,
                        problems=(),
                        source_sha256=source_hash,
                        text_sha256=_sha256(source_text),
                        fingerprint=fingerprint,
                    )
                    authored[key] = turn
                    report.generated += 1
                    continue

                if limit is not None and produced >= limit:
                    continue

                if surface_id not in switchers:
                    switchers[surface_id] = switcher_factory(surface)
                try:
                    result = switchers[surface_id].switch(source_text, protect=tuple(protect))
                    ok = bool(getattr(result, "ok", False))
                    text = str(getattr(result, "text", "") or "")
                    problems = tuple(str(item) for item in getattr(result, "problems", ()))
                except Exception as exc:  # noqa: BLE001
                    ok, text = False, ""
                    problems = (f"{type(exc).__name__}: {exc}",)
                produced += 1

                turn = AuthoredTurn(
                    semantic_id=row.semantic_id,
                    surface_id=surface_id,
                    turn_index=turn_index,
                    text=text,
                    ok=ok,
                    problems=problems,
                    source_sha256=source_hash,
                    text_sha256=_sha256(text),
                    fingerprint=fingerprint,
                )
                authored[key] = turn
                if ok:
                    report.generated += 1
                else:
                    report.rejected += 1
                    # Identifiers and counts only. The stimulus text itself is
                    # never echoed into a log or a console.
                    report.rejections.append(
                        {
                            "semantic_id": row.semantic_id,
                            "surface_id": surface_id,
                            "turn_index": turn_index,
                            "problems": list(problems)[:6],
                        }
                    )

    with output.open("w", encoding="utf-8") as handle:
        for key in sorted(authored):
            handle.write(
                json.dumps(authored[key].as_dict(), ensure_ascii=False, sort_keys=True) + "\n"
            )
    return report


# ---------------------------------------------------------------------------
# turning authored surfaces into runnable stimuli
# ---------------------------------------------------------------------------


def build_stimuli(
    rows: Sequence[CorpusRow],
    plan: Mapping[str, Surface],
    authored: Mapping[str, AuthoredTurn],
    *,
    require_reviewed: bool = False,
) -> list[dict[str, Any]]:
    """Join corpus provenance to authored text, or say exactly what is missing.

    The result is what the runner consumes: one row per case, carrying the
    scenario provenance the adapter resolver needs and one text per surface.
    """
    missing: list[str] = []
    stimuli: list[dict[str, Any]] = []
    for row in rows:
        texts: dict[str, str] = {}
        hashes: dict[str, str] = {}
        turns: dict[str, list[str]] = {}
        for surface_id in sorted(plan):
            surface = plan[surface_id]
            if require_reviewed and surface.needs_generation and surface.review_status != "reviewed":
                missing.append(f"{surface_id}: review_status is {surface.review_status}")
                continue
            collected: list[str] = []
            for turn_index in range(len(row.turns)):
                turn = authored.get(_key(row.semantic_id, surface_id, turn_index))
                if turn is None or not turn.ok:
                    missing.append(
                        f"{row.semantic_id}/{surface_id}/turn{turn_index}: "
                        + ("not authored" if turn is None else "rejected")
                    )
                    collected = []
                    break
                collected.append(turn.text)
            if not collected:
                continue
            turns[surface_id] = collected
            texts[surface_id] = "\n\n".join(collected)
            hashes[surface_id] = _sha256(texts[surface_id])
        if len(texts) != len(plan):
            continue
        stimuli.append(
            {
                **row.as_dict(),
                "texts": texts,
                "turns_by_surface": turns,
                "text_sha256": hashes,
            }
        )
    if missing:
        raise SurfaceError(
            f"{len(missing)} surface(s) are not usable; the first few are: "
            + "; ".join(sorted(set(missing))[:6])
        )
    return stimuli


def write_stimuli(stimuli: Sequence[Mapping[str, Any]], path: Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in stimuli:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    return path

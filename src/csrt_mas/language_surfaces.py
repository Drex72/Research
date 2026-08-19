from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from .finvault_dynamic.catalog import DatasetCase
from .resources import LanguageProfile


PROTECTED = re.compile(
    r"[A-Z][A-Z0-9-]{2,}|(?<!\w)\d(?:[\d,.:/-]*\d)?(?:\.\d+)?%?"
)


class LanguageSurfaceError(ValueError):
    pass


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class LanguageSurface:
    surface_id: str
    turns: tuple[str, ...]
    turn_sha256: tuple[str, ...]
    construction: str
    review_status: str
    application_point: str


@dataclass(frozen=True)
class LanguageBundle:
    case_id: str
    scenario_id: str
    source_sha256: str
    surfaces: dict[str, LanguageSurface]


def _protected(turn: str) -> set[str]:
    return set(PROTECTED.findall(turn))


def build_language_bundle(
    case: DatasetCase,
    profiles: dict[str, LanguageProfile],
    authored_turns: dict[str, tuple[str, ...]] | None = None,
) -> LanguageBundle:
    authored_turns = authored_turns or {}
    surfaces: dict[str, LanguageSurface] = {}
    source_turns = case.turns
    for surface_id, profile in profiles.items():
        if profile.kind == "source":
            turns = source_turns
        else:
            turns = authored_turns.get(surface_id, ())
            if not turns:
                raise LanguageSurfaceError(
                    f"surface {surface_id} requires reviewed authored turns"
                )
        if len(turns) != len(source_turns):
            raise LanguageSurfaceError(
                f"surface {surface_id} changes turn count: {len(source_turns)} != {len(turns)}"
            )
        for index, (source, transformed) in enumerate(zip(source_turns, turns, strict=True)):
            if not isinstance(transformed, str) or not transformed.strip():
                raise LanguageSurfaceError(f"surface {surface_id} turn {index} is empty")
            missing = sorted(_protected(source) - _protected(transformed))
            if missing:
                raise LanguageSurfaceError(
                    f"surface {surface_id} turn {index} drops protected facts: {missing[:8]}"
                )
            if profile.kind == "code_switched":
                scripts = {
                    "latin": bool(re.search(r"[A-Za-z]", transformed)),
                    "hangul": bool(re.search(r"[가-힣]", transformed)),
                }
                if set(profile.languages) == {"English", "Korean"} and not all(scripts.values()):
                    raise LanguageSurfaceError(
                        f"surface {surface_id} turn {index} is not English-Korean code-switched"
                    )
        surfaces[surface_id] = LanguageSurface(
            surface_id=surface_id,
            turns=tuple(turns),
            turn_sha256=tuple(_hash(turn) for turn in turns),
            construction=profile.construction,
            review_status=profile.review_status,
            application_point=profile.application_point,
        )
    return LanguageBundle(
        case_id=case.case_id,
        scenario_id=case.scenario_id,
        source_sha256=case.source_sha256,
        surfaces=surfaces,
    )

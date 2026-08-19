"""FinVault-side adapter for the independent code-switching package."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from csrt_codeswitch import CodeSwitcher, SwitchResult

from .catalog import DatasetCase


class FinVaultCodeSwitchError(ValueError):
    """Raised when a FinVault turn cannot produce an accepted language surface."""


@dataclass(frozen=True)
class AuthoredSurface:
    """One generated surface ready for the experiment layer to review/freeze."""

    surface_id: str
    case_id: str
    turns: tuple[str, ...]
    results: tuple[SwitchResult, ...]

    @property
    def accepted(self) -> bool:
        return all(result.ok for result in self.results)


class FinVaultCodeSwitchAdapter:
    """Map FinVault case turns through a domain-neutral ``CodeSwitcher``.

    FinVault owns cases and surface IDs. ``csrt_codeswitch`` owns linguistic
    transformation and validation. Neither package needs to know the other's
    internal configuration.
    """

    def __init__(self, surface_id: str, switcher: CodeSwitcher) -> None:
        if not surface_id.strip():
            raise FinVaultCodeSwitchError("surface_id cannot be empty")
        self.surface_id = surface_id
        self.switcher = switcher

    def author(
        self,
        case: DatasetCase,
        *,
        protect: Iterable[str] = (),
        require_all: bool = True,
    ) -> AuthoredSurface:
        results = tuple(
            self.switcher.switch(turn, protect=protect) for turn in case.turns
        )
        surface = AuthoredSurface(
            surface_id=self.surface_id,
            case_id=case.case_id,
            turns=tuple(result.text for result in results),
            results=results,
        )
        if require_all and not surface.accepted:
            failures = [
                f"turn {index}: {'; '.join(result.problems)}"
                for index, result in enumerate(results)
                if not result.ok
            ]
            raise FinVaultCodeSwitchError(
                f"{case.case_id}/{self.surface_id} was rejected: "
                + " | ".join(failures)
            )
        return surface

    def authored_turns(self, case: DatasetCase) -> dict[str, tuple[str, ...]]:
        """Return the shape consumed by ``build_language_bundle``."""
        surface = self.author(case)
        return {surface.surface_id: surface.turns}

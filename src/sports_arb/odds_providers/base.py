"""Abstract base class for odds providers."""

from __future__ import annotations

from abc import ABC, abstractmethod

from sports_arb.models import BookmakerOdds


class BaseOddsProvider(ABC):
    """All concrete odds providers must inherit from this class."""

    #: Human-readable provider name; subclasses must set this as a class var.
    name: str = "base"

    @abstractmethod
    def get_current_odds(self) -> list[BookmakerOdds]:
        """Return current odds from this provider.

        Returns
        -------
        list[BookmakerOdds]
            One :class:`~sports_arb.models.BookmakerOdds` record per
            (bookmaker, game, market_type) combination.
        """
        ...

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(name={self.name!r})"

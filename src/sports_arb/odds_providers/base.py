"""Abstract base class for odds providers."""

from __future__ import annotations

import asyncio
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

    def get_live_odds(self) -> list[BookmakerOdds]:
        """Return live (in-progress) odds from this provider.

        The default implementation delegates to :meth:`get_current_odds` so
        that providers that do not distinguish between pre-game and live modes
        continue to work without modification.  Override this method for
        providers that expose a dedicated live-odds endpoint (e.g.
        :class:`~sports_arb.odds_providers.the_odds_api.TheOddsApiProvider`).

        Returns
        -------
        list[BookmakerOdds]
            One :class:`~sports_arb.models.BookmakerOdds` record per
            (bookmaker, game, market_type) combination.
        """
        return self.get_current_odds()

    async def async_get_current_odds(self) -> list[BookmakerOdds]:
        """Async variant of :meth:`get_current_odds`.

        The default implementation offloads the synchronous call to a thread
        pool so that existing sync providers work without modification.
        Subclasses that use ``httpx.AsyncClient`` may override this method for
        true async I/O.

        Returns
        -------
        list[BookmakerOdds]
            Same as :meth:`get_current_odds`.
        """
        return await asyncio.to_thread(self.get_current_odds)

    async def async_get_live_odds(self) -> list[BookmakerOdds]:
        """Async variant of :meth:`get_live_odds`.

        The default implementation offloads the synchronous call to a thread
        pool.  Subclasses may override for true async I/O.

        Returns
        -------
        list[BookmakerOdds]
            Same as :meth:`get_live_odds`.
        """
        return await asyncio.to_thread(self.get_live_odds)

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(name={self.name!r})"

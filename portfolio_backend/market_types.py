from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Protocol

import pandas as pd

from portfolio_backend.models import Instrument


@dataclass
class MarketDataset:
    """Internal adjusted prices and their provider metadata.

    Providers supply a date-indexed DataFrame with ticker columns, instrument
    metadata, a fetch timestamp, and data-quality warnings. As a plain dataclass,
    this container does not enforce types or validate the DataFrame at runtime.
    """

    prices: pd.DataFrame
    instruments: list[Instrument]
    fetched_at: datetime
    warnings: list[str] = field(default_factory=list)
    provider: str = "yahoo_finance"
    adjustment: str = "Yahoo adjusted close: splits and cash dividends"


class MarketDataProvider(Protocol):
    """Structural interface for interchangeable market-data implementations."""

    def search(self, query: str, limit: int = 10) -> list[Instrument]:
        """Return up to limit instrument matches for a provider search query."""
        ...

    def history(
        self, tickers: list[str], start: date, end: date, base_currency: str
    ) -> MarketDataset:
        """Supply aligned adjusted daily prices for an inclusive date window.

        Args:
            tickers: Requested symbols in the desired column order.
            start: First requested trading date, inclusive.
            end: Last requested trading date, inclusive.
            base_currency: Required instrument currency; no FX conversion implied.

        Returns:
            Prices on common available dates with provenance and warnings.
        """
        ...

import type { PriceSnapshot } from '../../api/types';

interface AssetStatistics {
  ticker: string;
  prices: (number | null)[];
  cumulativeReturns: (number | null)[];
  dailyReturns: (number | null)[];
  rollingVolatility: (number | null)[];
}

function priceReturn(price: number | null, base: number | null): number | null {
  if (price === null || base === null) return null;
  const value = price / base - 1;
  return Number.isFinite(value) ? value : null;
}

export function calculateAssetStatistics(snapshot: PriceSnapshot, window: number): AssetStatistics[] {
  if (!Number.isInteger(window) || window < 2) {
    throw new RangeError('Volatility requires a window of at least two returns.');
  }

  return snapshot.tickers.map((ticker, column) => {
    const prices = snapshot.dates.map((_, index) => {
      const value = snapshot.prices[index]?.[column];
      return Number.isFinite(value) && value > 0 ? value : null;
    });
    const cumulativeReturns = prices.map((price) => priceReturn(price, prices[0]));
    const dailyReturns = prices.map((price, index) => (
      index === 0 ? null : priceReturn(price, prices[index - 1])
    ));
    const rollingVolatility = dailyReturns.map((_, index) => {
      if (index < window) return null;
      let mean = 0;
      let squaredDeviations = 0;
      let count = 0;
      for (let i = index - window + 1; i <= index; i++) {
        const value = dailyReturns[i];
        if (value === null) return null;
        count++;
        const delta = value - mean;
        mean += delta / count;
        squaredDeviations += delta * (value - mean);
      }
      const volatility = Math.sqrt(Math.max(0, squaredDeviations / (window - 1))) * Math.sqrt(252);
      return Number.isFinite(volatility) ? volatility : null;
    });
    return { ticker, prices, cumulativeReturns, dailyReturns, rollingVolatility };
  });
}

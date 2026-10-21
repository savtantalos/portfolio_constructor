import type { PortfolioResult } from '../../api/types';
import type { ColorTheme } from '../../hooks/useColorTheme';
import PlotWrapper from './PlotWrapper';
import { STRATEGY_LABELS } from '../strategyMetadata';

interface Props {
  portfolios: PortfolioResult[];
  theme: ColorTheme;
}

export default function WeightsChart({ portfolios, theme }: Props) {
  const tickers = portfolios.length > 0 ? Object.keys(portfolios[0].weights) : [];
  const strategies = portfolios.map((p) => STRATEGY_LABELS[p.strategy]);

  const data: Plotly.Data[] = tickers.map((ticker, i) => ({
    x: strategies,
    y: portfolios.map((p) => (p.weights[ticker] ?? 0) * 100),
    name: ticker,
    type: 'bar' as const,
    marker: { color: theme.colors[i % theme.colors.length] },
    hovertemplate: `${ticker}: %{y:.1f}%<extra></extra>`,
  }));

  return (
    <PlotWrapper
      data={data}
      title="Portfolio Weights (%)"
      theme={theme}
      yTitle="Weight (%)"
      extraLayout={{ barmode: 'stack' }}
    />
  );
}

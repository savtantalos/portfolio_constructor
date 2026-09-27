import type { PortfolioResult } from '../../api/types';
import type { ColorTheme } from '../../hooks/useColorTheme';
import PlotWrapper from './PlotWrapper';

interface Props {
  portfolios: PortfolioResult[];
  theme: ColorTheme;
}

const STRATEGY_LABELS: Record<string, string> = {
  equal_weight: 'Equal Weight',
  minimum_variance: 'Min Variance',
  maximum_sharpe: 'Max Sharpe',
};

export default function WeightsChart({ portfolios, theme }: Props) {
  const tickers = portfolios.length > 0 ? Object.keys(portfolios[0].weights) : [];
  const strategies = portfolios.map((p) => STRATEGY_LABELS[p.strategy] || p.strategy);

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

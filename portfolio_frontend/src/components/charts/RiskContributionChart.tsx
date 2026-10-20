import type { PortfolioResult } from '../../api/types';
import type { ColorTheme } from '../../hooks/useColorTheme';
import PlotWrapper from './PlotWrapper';
import { STRATEGY_LABELS } from '../strategyMetadata';

interface Props {
  portfolios: PortfolioResult[];
  theme: ColorTheme;
}

export default function RiskContributionChart({ portfolios, theme }: Props) {
  const tickers = portfolios.length > 0 ? Object.keys(portfolios[0].risk_contributions) : [];

  const data: Plotly.Data[] = tickers.map((ticker, i) => ({
    x: portfolios.map((p) => STRATEGY_LABELS[p.strategy]),
    y: portfolios.map((p) => (p.risk_contributions[ticker] ?? 0) * 100),
    name: ticker,
    type: 'bar' as const,
    marker: { color: theme.colors[i % theme.colors.length] },
    hovertemplate: `${ticker}: %{y:.1f}%<extra></extra>`,
  }));

  return (
    <PlotWrapper
      data={data}
      title="Risk Contributions (%)"
      theme={theme}
      yTitle="Risk Contribution (%)"
      extraLayout={{ barmode: 'stack' }}
    />
  );
}

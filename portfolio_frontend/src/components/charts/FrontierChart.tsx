import type { PortfolioPoint, PortfolioResult } from '../../api/types';
import type { ColorTheme } from '../../hooks/useColorTheme';
import PlotWrapper from './PlotWrapper';

interface Props {
  frontier: PortfolioPoint[];
  monteCarlo: PortfolioPoint[];
  portfolios: PortfolioResult[];
  theme: ColorTheme;
}

const STRATEGY_SYMBOLS: Record<string, string> = {
  equal_weight: 'diamond',
  minimum_variance: 'star',
  maximum_sharpe: 'hexagram',
};

const STRATEGY_LABELS: Record<string, string> = {
  equal_weight: 'Equal Weight',
  minimum_variance: 'Min Variance',
  maximum_sharpe: 'Max Sharpe',
};

export default function FrontierChart({ frontier, monteCarlo, portfolios, theme }: Props) {
  const data: Plotly.Data[] = [];

  if (monteCarlo.length > 0) {
    data.push({
      x: monteCarlo.map((p) => p.metrics.annual_volatility * 100),
      y: monteCarlo.map((p) => p.metrics.expected_annual_return * 100),
      mode: 'markers',
      type: 'scatter',
      name: 'Monte Carlo',
      marker: { color: theme.colors[7], size: 3, opacity: 0.3 },
      hovertemplate: 'Vol: %{x:.2f}%<br>Return: %{y:.2f}%<extra></extra>',
    });
  }

  if (frontier.length > 0) {
    data.push({
      x: frontier.map((p) => p.metrics.annual_volatility * 100),
      y: frontier.map((p) => p.metrics.expected_annual_return * 100),
      mode: 'lines+markers',
      type: 'scatter',
      name: 'Efficient Frontier',
      line: { color: theme.colors[0], width: 3 },
      marker: { size: 6, color: theme.colors[0] },
      hovertemplate: 'Vol: %{x:.2f}%<br>Return: %{y:.2f}%<extra></extra>',
    });
  }

  portfolios.forEach((p, i) => {
    data.push({
      x: [p.metrics.annual_volatility * 100],
      y: [p.metrics.expected_annual_return * 100],
      mode: 'markers',
      type: 'scatter',
      name: STRATEGY_LABELS[p.strategy] || p.strategy,
      marker: {
        color: theme.colors[(i + 1) % theme.colors.length],
        size: 14,
        symbol: STRATEGY_SYMBOLS[p.strategy] || 'circle',
        line: { width: 2, color: theme.text },
      },
      hovertemplate: `${STRATEGY_LABELS[p.strategy] || p.strategy}<br>Vol: %{x:.2f}%<br>Return: %{y:.2f}%<extra></extra>`,
    });
  });

  return (
    <PlotWrapper
      data={data}
      title="Efficient Frontier & Portfolios"
      theme={theme}
      xTitle="Annual Volatility (%)"
      yTitle="Expected Annual Return (%)"
      height={500}
    />
  );
}

import type { ScenarioResult } from '../../api/types';
import type { ColorTheme } from '../../hooks/useColorTheme';
import { STRATEGY_LABELS, strategyColor } from '../strategyMetadata';
import PlotWrapper from './PlotWrapper';

interface Props {
  scenarios: ScenarioResult[];
  theme: ColorTheme;
}

function hexToRgba(hex: string, alpha: number): string {
  const value = hex.replace('#', '');
  const r = parseInt(value.slice(0, 2), 16);
  const g = parseInt(value.slice(2, 4), 16);
  const b = parseInt(value.slice(4, 6), 16);
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

function percentileLabel(level: number): string {
  return `p${Math.round(level * 100)}`;
}

export default function ScenarioChart({ scenarios, theme }: Props) {
  const data: Plotly.Data[] = [];
  for (const scenario of scenarios) {
    const color = strategyColor(scenario.strategy, theme.colors);
    const label = STRATEGY_LABELS[scenario.strategy];
    const paths = [...scenario.fan_paths].sort((a, b) => a.percentile - b.percentile);
    const pairs = Math.floor(paths.length / 2);
    for (let index = 0; index < pairs; index += 1) {
      const low = paths[index];
      const high = paths[paths.length - 1 - index];
      const alpha = 0.3 - index * 0.12;
      const bandName = `${label} ${percentileLabel(low.percentile)}–${percentileLabel(high.percentile)}`;
      data.push({
        x: low.dates,
        y: low.values,
        mode: 'lines',
        type: 'scatter',
        name: bandName,
        legendgroup: bandName,
        showlegend: false,
        line: { color: hexToRgba(color, 0.4), width: 1 },
        hovertemplate: `%{x}<br>${percentileLabel(low.percentile)}: %{y:.4f}<extra>${label}</extra>`,
      });
      data.push({
        x: high.dates,
        y: high.values,
        mode: 'lines',
        type: 'scatter',
        name: bandName,
        legendgroup: bandName,
        showlegend: index === 0,
        fill: 'tonexty',
        fillcolor: hexToRgba(color, Math.max(alpha, 0.08)),
        line: { color: hexToRgba(color, 0.4), width: 1 },
        hovertemplate: `%{x}<br>${percentileLabel(high.percentile)}: %{y:.4f}<extra>${label}</extra>`,
      });
    }
    if (paths.length % 2 === 1) {
      const median = paths[pairs];
      data.push({
        x: median.dates,
        y: median.values,
        mode: 'lines',
        type: 'scatter',
        name: `${label} median`,
        line: { color, width: 2.5 },
        hovertemplate: `%{x}<br>median: %{y:.4f}<extra>${label}</extra>`,
      });
    }
  }
  return (
    <PlotWrapper
      data={data}
      title="Scenario fan: simulated wealth percentiles"
      theme={theme}
      xTitle="Projected date"
      yTitle="Normalized wealth"
      height={480}
      extraLayout={{ legend: { orientation: 'h', y: -0.15 } }}
    />
  );
}

import type { ColorTheme } from '../../hooks/useColorTheme';
import PlotWrapper from './PlotWrapper';

interface Props {
  correlation: Record<string, Record<string, number | null>>;
  theme: ColorTheme;
}

export default function CorrelationHeatmap({ correlation, theme }: Props) {
  const tickers = Object.keys(correlation);
  const z = tickers.map((row) =>
    tickers.map((col) => correlation[row][col] ?? 0)
  );

  const annotations: Plotly.Layout['annotations'] = [];
  tickers.forEach((row) => {
    tickers.forEach((col) => {
      const val = correlation[row][col];
      annotations.push({
        x: col,
        y: row,
        text: val !== null ? val.toFixed(2) : '-',
        showarrow: false,
        font: { color: Math.abs(val ?? 0) > 0.5 ? '#ffffff' : theme.text, size: 12 },
      });
    });
  });

  const data: Plotly.Data[] = [
    {
      z,
      x: tickers,
      y: tickers,
      type: 'heatmap',
      colorscale: [
        [0, '#2166AC'],
        [0.25, '#67A9CF'],
        [0.5, '#F7F7F7'],
        [0.75, '#EF8A62'],
        [1, '#B2182B'],
      ],
      zmin: -1,
      zmax: 1,
      hovertemplate: '%{y} vs %{x}: %{z:.3f}<extra></extra>',
      colorbar: { title: { text: 'Corr', font: { color: theme.text } }, tickfont: { color: theme.text } },
    },
  ];

  return (
    <PlotWrapper
      data={data}
      title="Return Correlation Matrix"
      theme={theme}
      showLegend={false}
      height={420}
      extraLayout={{
        annotations,
        xaxis: { color: theme.text, gridcolor: theme.gridColor, side: 'bottom' },
        yaxis: { color: theme.text, gridcolor: theme.gridColor, autorange: 'reversed' as const },
      }}
    />
  );
}

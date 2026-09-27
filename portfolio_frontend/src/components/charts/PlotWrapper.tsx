import Plot from 'react-plotly.js';
import type { ColorTheme } from '../../hooks/useColorTheme';

interface Props {
  data: Plotly.Data[];
  title: string;
  theme: ColorTheme;
  xTitle?: string;
  yTitle?: string;
  height?: number;
  showLegend?: boolean;
  extraLayout?: Partial<Plotly.Layout>;
}

export default function PlotWrapper({
  data,
  title,
  theme,
  xTitle,
  yTitle,
  height = 450,
  showLegend = true,
  extraLayout = {},
}: Props) {
  const layout: Partial<Plotly.Layout> = {
    title: { text: title, font: { color: theme.text, size: 16 } },
    paper_bgcolor: theme.paper,
    plot_bgcolor: theme.bg,
    font: { color: theme.text, family: "'Inter', system-ui, sans-serif" },
    xaxis: {
      title: xTitle ? { text: xTitle } : undefined,
      gridcolor: theme.gridColor,
      zerolinecolor: theme.gridColor,
      color: theme.text,
    },
    yaxis: {
      title: yTitle ? { text: yTitle } : undefined,
      gridcolor: theme.gridColor,
      zerolinecolor: theme.gridColor,
      color: theme.text,
    },
    showlegend: showLegend,
    legend: { font: { color: theme.text }, bgcolor: 'rgba(0,0,0,0)' },
    margin: { t: 50, r: 30, b: 60, l: 70 },
    autosize: true,
    ...extraLayout,
  };

  return (
    <Plot
      data={data}
      layout={layout}
      config={{
        responsive: true,
        displayModeBar: true,
        modeBarButtonsToAdd: ['toImage'],
        displaylogo: false,
        toImageButtonOptions: { format: 'png', height: 800, width: 1400, scale: 2 },
      }}
      style={{ width: '100%', height }}
      useResizeHandler
    />
  );
}

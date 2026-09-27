import type { PriceSnapshot } from '../../api/types';
import type { ColorTheme } from '../../hooks/useColorTheme';
import PlotWrapper from './PlotWrapper';

interface Props {
  snapshot: PriceSnapshot;
  theme: ColorTheme;
}

export default function PriceChart({ snapshot, theme }: Props) {
  const data: Plotly.Data[] = snapshot.tickers.map((ticker, colIdx) => ({
    x: snapshot.dates,
    y: snapshot.prices.map((row) => row[colIdx]),
    mode: 'lines',
    type: 'scatter',
    name: ticker,
    line: { color: theme.colors[colIdx % theme.colors.length], width: 1.5 },
    hovertemplate: `${ticker}<br>%{x}<br>$%{y:.2f}<extra></extra>`,
  }));

  return (
    <PlotWrapper
      data={data}
      title="Adjusted Closing Prices"
      theme={theme}
      xTitle="Date"
      yTitle="Price"
      height={400}
      extraLayout={{
        xaxis: {
          rangeslider: { visible: true },
          type: 'date',
          color: theme.text,
          gridcolor: theme.gridColor,
        },
      }}
    />
  );
}

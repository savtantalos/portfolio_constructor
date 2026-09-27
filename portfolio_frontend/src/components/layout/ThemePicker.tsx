import type { ColorTheme } from '../../hooks/useColorTheme';

interface Props {
  current: string;
  themes: string[];
  onChange: (name: string) => void;
  theme: ColorTheme;
}

export default function ThemePicker({ current, themes, onChange, theme }: Props) {
  return (
    <div className="theme-picker">
      <label className="theme-label">Chart Theme</label>
      <div className="theme-options">
        {themes.map((name) => (
          <button
            key={name}
            className={`theme-btn ${name === current ? 'active' : ''}`}
            onClick={() => onChange(name)}
            title={name}
          >
            {name.charAt(0).toUpperCase() + name.slice(1)}
          </button>
        ))}
      </div>
      <div className="theme-preview">
        {theme.colors.slice(0, 6).map((c, i) => (
          <span key={i} className="color-dot" style={{ backgroundColor: c }} />
        ))}
      </div>
    </div>
  );
}

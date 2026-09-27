import { useState, useCallback } from 'react';

export interface ColorTheme {
  name: string;
  colors: string[];
  bg: string;
  paper: string;
  text: string;
  gridColor: string;
  positive: string;
  negative: string;
}

const themes: Record<string, ColorTheme> = {
  vibrant: {
    name: 'Vibrant',
    colors: ['#636EFA', '#EF553B', '#00CC96', '#AB63FA', '#FFA15A', '#19D3F3', '#FF6692', '#B6E880', '#FF97FF', '#FECB52'],
    bg: '#0f1117', paper: '#1a1c23', text: '#e0e0e0', gridColor: '#2a2d35',
    positive: '#00CC96', negative: '#EF553B',
  },
  ocean: {
    name: 'Ocean',
    colors: ['#0077B6', '#00B4D8', '#90E0EF', '#CAF0F8', '#023E8A', '#0096C7', '#48CAE4', '#ADE8F4', '#03045E', '#468FAF'],
    bg: '#0a1628', paper: '#112240', text: '#ccd6f6', gridColor: '#1d3461',
    positive: '#64FFDA', negative: '#FF6B6B',
  },
  sunset: {
    name: 'Sunset',
    colors: ['#FF6B35', '#F7C59F', '#EFEFD0', '#004E89', '#1A659E', '#FF9F1C', '#E71D36', '#2EC4B6', '#FDFFFC', '#011627'],
    bg: '#1a0e0e', paper: '#2d1b1b', text: '#f0d9b5', gridColor: '#3d2b2b',
    positive: '#2EC4B6', negative: '#E71D36',
  },
  forest: {
    name: 'Forest',
    colors: ['#2D6A4F', '#40916C', '#52B788', '#74C69D', '#95D5B2', '#B7E4C7', '#D8F3DC', '#1B4332', '#081C15', '#8FBC8F'],
    bg: '#0d1a0d', paper: '#1a2e1a', text: '#d4e7c5', gridColor: '#2a3e2a',
    positive: '#52B788', negative: '#E76F51',
  },
  monochrome: {
    name: 'Monochrome',
    colors: ['#FFFFFF', '#CCCCCC', '#999999', '#666666', '#333333', '#E8E8E8', '#B0B0B0', '#787878', '#484848', '#1A1A1A'],
    bg: '#111111', paper: '#1e1e1e', text: '#e0e0e0', gridColor: '#333333',
    positive: '#FFFFFF', negative: '#888888',
  },
  light: {
    name: 'Light',
    colors: ['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd', '#8c564b', '#e377c2', '#7f7f7f', '#bcbd22', '#17becf'],
    bg: '#ffffff', paper: '#f8f9fa', text: '#212529', gridColor: '#dee2e6',
    positive: '#28a745', negative: '#dc3545',
  },
};

export const themeNames = Object.keys(themes);

export function useColorTheme(initial = 'vibrant') {
  const [themeName, setThemeName] = useState(initial);
  const theme = themes[themeName] || themes.vibrant;

  const setTheme = useCallback((name: string) => {
    if (themes[name]) setThemeName(name);
  }, []);

  return { theme, themeName, setTheme, themeNames };
}

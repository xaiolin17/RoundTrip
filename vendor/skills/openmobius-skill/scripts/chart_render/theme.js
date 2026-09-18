// theme.js — TradingView-style palette for SMC structural overlays.

const THEMES = {
  light: {
    name:       'light',
    background: '#ffffff',
    text:       '#1f2937',
    grid:       '#f0f3f5',
    border:     '#d1d5db',
    upColor:    '#26a69a',
    downColor:  '#ef5350',
    volumeUp:   '#26a69a',
    volumeDown: '#ef5350',
    roles: {
      bullish:    '#26a69a',
      bearish:    '#ef5350',
      muted:      '#9ca3af',

      // SMC structural — TV palette: light pink for bear OB, light blue for bull OB
      fvg:         '#26a69a',   // bull FVG (light green tint)
      fvg_bear:    '#ef5350',   // bear FVG (light red tint)
      ob:          '#90caf9',   // bull OB — light blue
      ob_bear:     '#ef9a9a',   // bear OB — light pink (TV signature)
      breaker:     '#9c27b0',
      liquidity:   '#ff9800',

      // Trade setup
      entry_long:  '#26a69a',
      entry_short: '#ef5350',
      stop_loss:   '#ef5350',
      target:      '#2196f3',

      // SMC zones (kept for opt-in --include-zones)
      premium:     '#ef5350',
      equilibrium: '#9ca3af',
      discount:    '#26a69a',
    },
  },
  dark: {
    name:       'dark',
    background: '#0e1116',
    text:       '#d0d4da',
    grid:       '#1f242c',
    border:     '#2a2f38',
    upColor:    '#26a69a',
    downColor:  '#ef5350',
    volumeUp:   '#26a69a',
    volumeDown: '#ef5350',
    roles: {
      bullish:    '#26a69a',
      bearish:    '#ef5350',
      muted:      '#5a6373',

      fvg:         '#26a69a',
      fvg_bear:    '#ef5350',
      ob:          '#64b5f6',    // bull OB — soft blue (TV-like, slightly brighter for dark bg)
      ob_bear:     '#e57373',    // bear OB — soft pink/red
      breaker:     '#aa55ff',
      liquidity:   '#ff9800',

      entry_long:  '#26a69a',
      entry_short: '#ef5350',
      stop_loss:   '#ef5350',
      target:      '#2196f3',

      premium:     '#ef5350',
      equilibrium: '#5a6373',
      discount:    '#26a69a',
    },
  },
};

function colorFor(theme, role, fallback) {
  fallback = fallback || '#888';
  if (!role) return fallback;
  return theme.roles[role] || fallback;
}

window.QKTheme = { THEMES, colorFor };

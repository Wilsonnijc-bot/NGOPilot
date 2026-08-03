/**
 * Theme tokens — the single source of truth for all MCP semantic token values.
 *
 * Every key in McpUiStyleVariableKey must be present in both lightTokens and
 * darkTokens. The TypeScript compiler enforces this: if the SDK adds a new key,
 * the build breaks until both maps are updated.
 *
 * Values are applied to :root via style.setProperty() before first paint
 * (see renderer.tsx). main.css only registers the variable names for Tailwind
 * class generation — it does NOT define values.
 *
 * These tokens serve two purposes:
 *  1. NGOPilot desktop — applied to :root per resolved theme.
 *  2. MCP apps — encoded as light-dark() in hostContext.styles.variables.
 */
import type {
  McpUiHostStyles,
  McpUiStyleVariableKey,
  McpUiStyles,
} from '@modelcontextprotocol/ext-apps/app-bridge';

type ThemeTokens = Record<McpUiStyleVariableKey, string>;

// Subset of keys that are the same across both themes.
type BaseTokenKey = Extract<
  McpUiStyleVariableKey,
  `--font-${string}` | `--border-radius-${string}` | `--border-width-${string}`
>;

type ColorTokenKey = Exclude<McpUiStyleVariableKey, BaseTokenKey>;

// ---------------------------------------------------------------------------
// Base tokens — shared across light and dark themes
// ---------------------------------------------------------------------------
const baseTokens: Pick<ThemeTokens, BaseTokenKey> = {
  // Typography — families
  '--font-sans': "'Cash Sans', sans-serif",
  '--font-mono': 'monospace',

  // Typography — weights
  '--font-weight-normal': '400',
  '--font-weight-medium': '500',
  '--font-weight-semibold': '600',
  '--font-weight-bold': '700',

  // Typography — text sizes
  '--font-text-xs-size': '0.75rem',
  '--font-text-sm-size': '0.875rem',
  '--font-text-md-size': '1rem',
  '--font-text-lg-size': '1.125rem',

  // Typography — heading sizes
  '--font-heading-xs-size': '1rem',
  '--font-heading-sm-size': '1.125rem',
  '--font-heading-md-size': '1.25rem',
  '--font-heading-lg-size': '1.5rem',
  '--font-heading-xl-size': '1.875rem',
  '--font-heading-2xl-size': '2.25rem',
  '--font-heading-3xl-size': '3rem',

  // Typography — text line heights
  '--font-text-xs-line-height': '1rem',
  '--font-text-sm-line-height': '1.25rem',
  '--font-text-md-line-height': '1.5rem',
  '--font-text-lg-line-height': '1.75rem',

  // Typography — heading line heights
  '--font-heading-xs-line-height': '1.5rem',
  '--font-heading-sm-line-height': '1.75rem',
  '--font-heading-md-line-height': '1.75rem',
  '--font-heading-lg-line-height': '2rem',
  '--font-heading-xl-line-height': '2.25rem',
  '--font-heading-2xl-line-height': '2.5rem',
  '--font-heading-3xl-line-height': '3.5rem',

  // Border radius
  '--border-radius-xs': '2px',
  '--border-radius-sm': '4px',
  '--border-radius-md': '8px',
  '--border-radius-lg': '12px',
  '--border-radius-xl': '16px',
  '--border-radius-full': '9999px',

  // Border width
  '--border-width-regular': '1px',
};

// Theme-specific color/shadow tokens only.
type ColorTokens = Pick<ThemeTokens, ColorTokenKey>;

// ---------------------------------------------------------------------------
// Light theme — colors & shadows
// ---------------------------------------------------------------------------
const lightColorTokens: ColorTokens = {
  // Backgrounds
  '--color-background-primary': '#fcfaf3',
  '--color-background-secondary': '#f8f3e8',
  '--color-background-tertiary': '#efe7d3',
  '--color-background-inverse': '#0e0c0a',
  '--color-background-ghost': 'transparent',
  '--color-background-info': '#a8412c',
  '--color-background-danger': '#6b2419',
  '--color-background-success': '#4a6c5d',
  '--color-background-warning': '#a8841f',
  '--color-background-disabled': '#efe7d3',

  // Text
  '--color-text-primary': '#1f1c18',
  '--color-text-secondary': '#5a544a',
  '--color-text-tertiary': '#7a6e51',
  '--color-text-inverse': '#fcfaf3',
  '--color-text-ghost': '#5a544a',
  '--color-text-info': '#a8412c',
  '--color-text-danger': '#6b2419',
  '--color-text-success': '#4a6c5d',
  '--color-text-warning': '#6b5310',
  '--color-text-disabled': '#a99b7a',

  // Borders
  '--color-border-primary': '#efe7d3',
  '--color-border-secondary': '#dccfb0',
  '--color-border-tertiary': '#a99b7a',
  '--color-border-inverse': '#0e0c0a',
  '--color-border-ghost': 'transparent',
  '--color-border-info': '#a8412c',
  '--color-border-danger': '#6b2419',
  '--color-border-success': '#4a6c5d',
  '--color-border-warning': '#a8841f',
  '--color-border-disabled': '#efe7d3',

  // Rings
  '--color-ring-primary': '#a8412c',
  '--color-ring-secondary': '#dccfb0',
  '--color-ring-inverse': '#fcfaf3',
  '--color-ring-info': '#a8412c',
  '--color-ring-danger': '#6b2419',
  '--color-ring-success': '#4a6c5d',
  '--color-ring-warning': '#a8841f',

  // Shadows
  '--shadow-hairline': '0 0 0 1px rgba(31, 28, 24, 0.06)',
  '--shadow-sm': '0 1px 2px 0 rgba(31, 28, 24, 0.06)',
  '--shadow-md': '0 1px 0 rgba(20, 18, 14, 0.06), 0 24px 48px -32px rgba(20, 18, 14, 0.18)',
  '--shadow-lg': '0 18px 38px rgba(31, 28, 24, 0.09)',
};

// ---------------------------------------------------------------------------
// Dark theme — colors & shadows
// ---------------------------------------------------------------------------
const darkColorTokens: ColorTokens = {
  // Backgrounds
  '--color-background-primary': '#0e0c0a',
  '--color-background-secondary': '#1f1c18',
  '--color-background-tertiary': '#3d3933',
  '--color-background-inverse': '#fcfaf3',
  '--color-background-ghost': 'transparent',
  '--color-background-info': '#a8412c',
  '--color-background-danger': '#6b2419',
  '--color-background-success': '#4a6c5d',
  '--color-background-warning': '#a8841f',
  '--color-background-disabled': '#3d3933',

  // Text
  '--color-text-primary': '#fcfaf3',
  '--color-text-secondary': '#dccfb0',
  '--color-text-tertiary': '#a99b7a',
  '--color-text-inverse': '#0e0c0a',
  '--color-text-ghost': '#dccfb0',
  '--color-text-info': '#f5c8bb',
  '--color-text-danger': '#f5c8bb',
  '--color-text-success': '#d6e0d1',
  '--color-text-warning': '#faf2dc',
  '--color-text-disabled': '#5a544a',

  // Borders
  '--color-border-primary': '#3d3933',
  '--color-border-secondary': '#5a544a',
  '--color-border-tertiary': '#7a6e51',
  '--color-border-inverse': '#fcfaf3',
  '--color-border-ghost': 'transparent',
  '--color-border-info': '#c75a3f',
  '--color-border-danger': '#c75a3f',
  '--color-border-success': '#4a6c5d',
  '--color-border-warning': '#a8841f',
  '--color-border-disabled': '#3d3933',

  // Rings
  '--color-ring-primary': '#c75a3f',
  '--color-ring-secondary': '#7a6e51',
  '--color-ring-inverse': '#0e0c0a',
  '--color-ring-info': '#c75a3f',
  '--color-ring-danger': '#c75a3f',
  '--color-ring-success': '#4a6c5d',
  '--color-ring-warning': '#a8841f',

  // Shadows
  '--shadow-hairline': '0 0 0 1px rgba(252, 250, 243, 0.08)',
  '--shadow-sm': '0 1px 2px 0 rgba(14, 12, 10, 0.3)',
  '--shadow-md': '0 1px 0 rgba(252, 250, 243, 0.05), 0 24px 48px -32px rgba(14, 12, 10, 0.72)',
  '--shadow-lg': '0 18px 38px rgba(14, 12, 10, 0.54)',
};

// ---------------------------------------------------------------------------
// Merged token maps — used by applyThemeTokens() and buildMcpHostStyles()
// ---------------------------------------------------------------------------
export const lightTokens: ThemeTokens = { ...baseTokens, ...lightColorTokens };
export const darkTokens: ThemeTokens = { ...baseTokens, ...darkColorTokens };

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

// @font-face rules passed to MCP apps so sandboxed iframes can load host fonts.
const HOST_FONT_CSS = `
@font-face {
  font-family: 'Cash Sans';
  src: url(https://cash-f.squarecdn.com/static/fonts/cashsans/woff2/CashSans-Light.woff2) format('woff2'),
       url(https://cash-f.squarecdn.com/static/fonts/cashsans/woff/CashSans-Light.woff) format('woff');
  font-weight: 300;
  font-style: normal;
}
@font-face {
  font-family: 'Cash Sans';
  src: url(https://cash-f.squarecdn.com/static/fonts/cashsans/woff2/CashSans-Regular.woff2) format('woff2'),
       url(https://cash-f.squarecdn.com/static/fonts/cashsans/woff/CashSans-Regular.woff) format('woff');
  font-weight: 400;
  font-style: normal;
}
@font-face {
  font-family: 'Cash Sans';
  src: url(https://cash-f.squarecdn.com/static/fonts/cashsans/woff2/CashSans-Medium.woff2) format('woff2'),
       url(https://cash-f.squarecdn.com/static/fonts/cashsans/woff/CashSans-Medium.woff) format('woff');
  font-weight: 500;
  font-style: normal;
}
@font-face {
  font-family: 'Cash Sans';
  src: url(https://cash-f.squarecdn.com/static/fonts/cashsans/woff2/CashSans-Bold.woff2) format('woff2'),
       url(https://cash-f.squarecdn.com/static/fonts/cashsans/woff/CashSans-Bold.woff) format('woff');
  font-weight: 700;
  font-style: normal;
}
`.trim();

/**
 * Build the McpUiHostStyles object for MCP apps.
 * Color keys use light-dark() so a single payload works for both themes.
 * Non-color keys (fonts, radii, shadows) use plain values from baseTokens
 * (or light as the default when values differ, e.g. shadows).
 * css.fonts provides @font-face rules so sandboxed apps can load host fonts.
 */
export function buildMcpHostStyles(): McpUiHostStyles {
  const variables: McpUiStyles = {} as McpUiStyles;
  for (const key of Object.keys(lightTokens) as McpUiStyleVariableKey[]) {
    const light = lightTokens[key];
    const dark = darkTokens[key];
    if (key.startsWith('--color-')) {
      variables[key] = `light-dark(${light}, ${dark})`;
    } else {
      variables[key] = light;
    }
  }
  return { variables, css: { fonts: HOST_FONT_CSS } };
}

/**
 * Resolve the current theme from localStorage / system preference.
 */
export function getResolvedTheme(): 'light' | 'dark' {
  const useSystem = localStorage.getItem('use_system_theme') !== 'false';
  if (useSystem) {
    return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
  }
  return localStorage.getItem('theme') === 'dark' ? 'dark' : 'light';
}

/**
 * Apply theme tokens to the document root as CSS custom properties.
 * When called without an argument, resolves the theme from localStorage.
 */
export function applyThemeTokens(theme?: 'light' | 'dark'): void {
  const resolved = theme ?? getResolvedTheme();
  const tokens = resolved === 'dark' ? darkTokens : lightTokens;
  const root = document.documentElement;
  for (const [key, value] of Object.entries(tokens)) {
    root.style.setProperty(key, value);
  }
}

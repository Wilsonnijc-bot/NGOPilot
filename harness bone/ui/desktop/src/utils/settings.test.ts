import { describe, expect, it } from 'vitest';
import { DEFAULT_LANGUAGE_SETTING, isLanguageSetting, normalizeLanguageSetting } from './settings';

describe('language settings', () => {
  it('supports only Cantonese and English', () => {
    expect(isLanguageSetting('zh-HK')).toBe(true);
    expect(isLanguageSetting('en')).toBe(true);
    expect(isLanguageSetting('system')).toBe(false);
    expect(isLanguageSetting('zh-TW')).toBe(false);
  });

  it('uses Cantonese for missing and legacy preferences', () => {
    expect(DEFAULT_LANGUAGE_SETTING).toBe('zh-HK');
    expect(normalizeLanguageSetting(undefined)).toBe('zh-HK');
    expect(normalizeLanguageSetting('system')).toBe('zh-HK');
    expect(normalizeLanguageSetting('zh-TW')).toBe('zh-HK');
  });

  it('preserves an explicit English preference', () => {
    expect(normalizeLanguageSetting('en')).toBe('en');
  });
});

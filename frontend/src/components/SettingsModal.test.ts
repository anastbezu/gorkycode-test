import { describe, expect, it } from 'vitest';
import { isCustomConfig, sanitizeConfig } from './SettingsModal';

describe('SettingsModal logic', () => {
  it('метка по сохранённому состоянию: если все поля null — настройки сервера', () => {
    expect(isCustomConfig({ base_url: null, model: null, api_key: null })).toBe(false);
  });

  it('метка по сохранённому состоянию: если хотя бы одно поле заполнено — свои настройки', () => {
    expect(isCustomConfig({ base_url: null, model: 'gpt-4o-mini', api_key: null })).toBe(true);
    expect(isCustomConfig({ base_url: 'https://api.openai.com/v1', model: null, api_key: null })).toBe(true);
    expect(isCustomConfig({ base_url: null, model: null, api_key: 'sk-test' })).toBe(true);
  });

  it('сброс очищает форму, sanitizeConfig возвращает все null при пустых строках', () => {
    const clearedForm = { base_url: '', model: '', api_key: '' };
    expect(sanitizeConfig(clearedForm)).toEqual({
      base_url: null,
      model: null,
      api_key: null,
    });
  });

  it('sanitizeConfig обрезает пробелы и сохраняет непустые значения', () => {
    const filledForm = {
      base_url: '  https://api.example.com  ',
      model: '  custom-model ',
      api_key: '  secret-key ',
    };
    expect(sanitizeConfig(filledForm)).toEqual({
      base_url: 'https://api.example.com',
      model: 'custom-model',
      api_key: 'secret-key',
    });
  });
});

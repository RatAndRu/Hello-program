/**
 * Пресеты художественных стилей и правило их смешивания.
 *
 * Раньше новый стиль накладывался на поля прошлого: включили «скетч», потом
 * «аниме» — и на экране оставалась штриховка скетча с цветами аниме. Здесь
 * смена режима всегда начинается с чистого пресета, а правка ползунка
 * накладывается на текущее состояние. Тот же порядок задан в Python
 * (`forma/anime.py`, `normalize_style`), поэтому сценарий и окно дают
 * одинаковый результат.
 */
export const ANIME_MODES = {
  'выкл': { mode: 'выкл' },
  'аниме': { mode: 'аниме', line: 1.6, crease: 32, toon: 3, tone: 0, paper: '#f4f6fa' },
  'манга': { mode: 'манга', line: 1.8, crease: 30, toon: 3, tone: 0.75, paper: '#fbfbf7' },
  'комикс': { mode: 'комикс', line: 2.6, crease: 38, toon: 2, tone: 0.6, paper: '#fdf4e3' },
  'скетч': {
    mode: 'скетч', line: 1.5, crease: 26, toon: 0, tone: 0, paper: '#f6f1e6',
    hatch: 0.85, hatch_angle: 52, hatch_step: 7, paper_tex: 0.6,
  },
  'линия': { mode: 'линия', line: 1.4, crease: 28, toon: 0, tone: 0, paper: '#ffffff', shade: false },
};

/** Полный словарь стиля: текущее состояние, достроенное пресетом режима. */
export function resolveAnimeStyle(current, presets = ANIME_MODES) {
  const now = current && typeof current === 'object' ? current : { mode: 'выкл' };
  const mode = now.mode || 'выкл';
  if (mode === 'выкл') return { mode: 'выкл' };
  return { ...(presets[mode] || { mode }), ...now, mode };
}

/**
 * Новое состояние стиля после правки.
 * `patch.mode` задан и отличается — берём чистый пресет;
 * иначе — пресет + текущее состояние + правка.
 */
export function mergeAnimeStyle(current, patch, presets = ANIME_MODES) {
  const now = current && typeof current === 'object' ? current : { mode: 'выкл' };
  const patchMode = patch && patch.mode;
  const mode = patchMode === undefined ? (now.mode || 'выкл') : patchMode;
  if (!mode || mode === 'выкл') return { mode: 'выкл' };
  const preset = { ...(presets[mode] || { mode }) };
  const changing = patchMode !== undefined && patchMode !== now.mode;
  const base = changing ? preset : { ...preset, ...now };
  return { ...base, ...(patch || {}), mode };
}

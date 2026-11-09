/**
 * Типизированные контролы параметров.
 *
 * Панель Формы не спрашивает значение свободным полем: у параметра есть тип,
 * диапазон, единица и, если он может быть не задан, режим «авто». Здесь две
 * части: `controlModel` — чистое описание того, *чем* управлять (его проверяет
 * node-тест), и `renderControl` — сборка элемента по этому описанию.
 *
 * Значение «авто» — это отсутствие параметра в строке `.forma`, а не число.
 * Поэтому модель всегда различает `present` (параметр записан) и `value`.
 */

const FREE_TYPES = new Set(['str']);

export function normalizeSpec(spec) {
  const out = { ...(spec || {}) };
  out.type = String(out.type || 'str');
  if (out.type === 'num' || out.type === 'int') {
    out.step = out.step ?? (out.type === 'int' ? 1 : 0.1);
  }
  return out;
}

/** Режим «авто»: как параметр возвращается в состояние «не задан». */
export function autoState(spec, present) {
  const mode = spec?.auto || null;
  if (!mode) return null;
  return {
    mode,
    active: !present,
    hint: spec.auto_hint || '',
    sentinel: spec.sentinel_value ?? null,
    sentinelLabel: spec.sentinel_label || '',
    // у enum «авто» — отдельный пункт списка, у sentinel — отдельное число
    value: mode === 'sentinel' ? (spec.sentinel_value ?? null) : null,
    resettable: true,
  };
}

/**
 * Описание управляющего элемента.
 *
 * `kind` — ровно один из типов, объявленных сервером: num/int/vec/flag/enum/str.
 * Если спецификации нет, параметр остаётся свободным вводом и это видно
 * (`declared: false`) — панель не притворяется, что знает диапазон.
 */
export function controlModel(spec, state = {}) {
  if (!spec) {
    return {
      kind: 'str', declared: false, free: true, label: state.key || '',
      value: state.value ?? '', present: Boolean(state.present), unit: '',
      min: null, max: null, step: null, items: [], auto: null,
    };
  }
  const s = normalizeSpec(spec);
  const present = Boolean(state.present);
  const value = state.value !== undefined ? state.value : (present ? null : s.default);
  const model = {
    kind: s.type,
    declared: true,
    free: FREE_TYPES.has(s.type),
    key: state.key || '',
    label: s.label || state.key || '',
    unit: s.unit || '',
    min: s.min ?? null,
    max: s.max ?? null,
    step: s.step ?? null,
    required: Boolean(s.required),
    hidden: Boolean(s.hidden),
    value,
    present,
    items: Array.isArray(s.items) ? s.items.slice() : [],
    auto: autoState(s, present),
  };
  if (model.kind === 'vec') {
    const size = Number(s.size || 3);
    const source = Array.isArray(value) ? value : [];
    model.size = size;
    model.value = Array.from({ length: size }, (_, i) =>
      (source[i] !== undefined ? source[i] : 0));
    model.components = Array.from({ length: size }, (_, i) => ({
      index: i,
      axis: size === 3 ? ['x', 'y', 'z'][i] : ['x', 'y'][i],
      min: s.min ?? null,
      max: s.max ?? null,
      step: s.step ?? (s.unit === '' ? 0.01 : 0.1),
    }));
  }
  if (model.kind === 'flag') model.value = Boolean(value);
  if (model.kind === 'enum') {
    const values = model.items.map((item) => item.value);
    if (value !== undefined && value !== null && !values.includes(value)) {
      // значение из сценария, которого нет в списке: показываем его, не теряя
      model.items.push({ value, label: `${value} (из сценария)` });
    }
    if (model.auto && model.auto.mode === 'enum' && !values.includes('авто')) {
      model.items.push({ value: 'авто', label: 'авто' });
    }
  }
  return model;
}

/** Разбор значения из строки `.forma` — без eval: числа, векторы, слова. */
export function parseLiteral(raw) {
  if (raw === undefined || raw === null) return undefined;
  const text = String(raw).trim();
  if (!text) return '';
  if (text === 'true' || text === 'да') return true;
  if (text === 'false' || text === 'нет') return false;
  if (text.startsWith('[') && text.endsWith(']')) {
    return text.slice(1, -1).split(',').map((part) => {
      const num = Number(part.trim());
      return Number.isFinite(num) ? num : part.trim();
    });
  }
  const num = Number(text);
  if (Number.isFinite(num) && text !== '') return num;
  return text.replace(/^["']|["']$/g, '');
}

/** Модель параметра по команде сценария: значения берутся из kwargs. */
export function modelFromCommand(specs, command, key) {
  const verb = String(command?.verb || '').toLowerCase();
  const spec = (specs?.[verb] || {})[key] || null;
  const kwargs = command?.kwargs || {};
  const present = Object.prototype.hasOwnProperty.call(kwargs, key);
  return controlModel(spec, { key, present, value: present ? parseLiteral(kwargs[key]) : undefined });
}

/** Правка для сервера: одна строка, один параметр. */
export function editFor(model, nextValue, line) {
  const edit = { line };
  if (nextValue === AUTO) {
    return { ...edit, action: 'unset_param', param: model.key };
  }
  return { ...edit, action: 'set_param', param: model.key, value: nextValue };
}

export const AUTO = Symbol('forma-auto');

/** Единый вид значения для записи в сценарий. */
export function formatValue(value) {
  if (typeof value === 'boolean') return value ? 'true' : 'false';
  if (Array.isArray(value)) return `[${value.map(formatValue).join(', ')}]`;
  if (typeof value === 'number') {
    if (Number.isInteger(value)) return String(value);
    return String(Math.round(value * 1e4) / 1e4);
  }
  return String(value);
}

/** Значение по умолчанию для кнопки «заводское». */
export function factoryValue(model) {
  if (model.kind === 'vec') return model.value.slice();
  if (model.kind === 'flag') return false;
  if (model.kind === 'enum') {
    const spec = model.items.find((item) => item.value === model.value);
    return spec ? spec.value : (model.items[0]?.value ?? '');
  }
  return model.value;
}

// --------------------------------------------------------------------------
// Сборка элементов
// --------------------------------------------------------------------------

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function stepButton(dir, onClick) {
  const button = el('button', 'pc-step', dir > 0 ? '▴' : '▾');
  button.type = 'button';
  button.tabIndex = -1;
  button.dataset.dir = String(dir);
  button.addEventListener('click', (event) => {
    event.preventDefault();
    onClick(dir);
  });
  return button;
}

function clampNumber(value, model) {
  let next = Number(value);
  if (!Number.isFinite(next)) return null;
  if (model.min !== null) next = Math.max(Number(model.min), next);
  if (model.max !== null) next = Math.min(Number(model.max), next);
  return next;
}

/**
 * Собирает элемент управления.
 *
 * `onChange(value | AUTO)` вызывается только по завершении правки (change),
 * а не на каждый пиксель движения ползунка: сборка модели дороже, чем ввод.
 */
export function renderControl(model, onChange) {
  const row = el('div', 'pc-row');
  row.dataset.param = model.key;
  row.dataset.kind = model.kind;
  const caption = el('span', 'pc-label', model.label || model.key);
  caption.title = model.auto?.hint ? `${model.label} · авто: ${model.auto.hint}` : model.label;
  row.appendChild(caption);

  const body = el('div', 'pc-body');
  row.appendChild(body);

  if (model.kind === 'flag') {
    const box = el('input');
    box.type = 'checkbox';
    box.checked = Boolean(model.value);
    box.addEventListener('change', () => onChange(box.checked));
    body.appendChild(box);
  } else if (model.kind === 'enum') {
    let index = Math.max(0, model.items.findIndex((item) => item.value === model.value));
    const label = el('span', 'pc-enum-value', model.items[index]?.label ?? '—');
    const apply = (dir) => {
      index = (index + dir + model.items.length) % model.items.length;
      const item = model.items[index];
      label.textContent = item.label;
      onChange(item.value);
    };
    body.append(stepButton(-1, apply), label, stepButton(1, apply));
  } else if (model.kind === 'vec') {
    model.value.forEach((component, i) => {
      const input = el('input', 'pc-num');
      input.type = 'number';
      input.value = String(component);
      if (model.components[i].min !== null) input.min = String(model.components[i].min);
      if (model.components[i].max !== null) input.max = String(model.components[i].max);
      input.step = String(model.components[i].step ?? 0.1);
      input.dataset.component = String(i);
      input.title = `${model.label}: ${model.components[i].axis}`;
      input.addEventListener('change', () => {
        const next = model.value.slice();
        const parsed = Number(input.value);
        if (!Number.isFinite(parsed)) { input.value = String(model.value[i]); return; }
        next[i] = parsed;
        onChange(next);
      });
      body.appendChild(input);
    });
  } else {
    const isNumber = model.kind === 'num' || model.kind === 'int';
    const input = el('input', 'pc-num');
    input.type = isNumber ? 'number' : 'text';
    input.value = model.value === null || model.value === undefined ? '' : String(model.value);
    if (isNumber) {
      if (model.min !== null) input.min = String(model.min);
      if (model.max !== null) input.max = String(model.max);
      if (model.step !== null) input.step = String(model.step);
    } else {
      input.spellcheck = false;
    }
    const commit = (next) => {
      if (isNumber) {
        const clamped = clampNumber(next, model);
        if (clamped === null) { input.value = String(model.value ?? ''); return; }
        input.value = String(clamped);
        onChange(clamped);
      } else {
        onChange(next);
      }
    };
    input.addEventListener('change', () => commit(input.value));
    let slider = null;
    if (isNumber && model.min !== null && model.max !== null
        && Number(model.max) > Number(model.min)) {
      slider = el('input', 'pc-slider');
      slider.type = 'range';
      slider.min = String(model.min);
      slider.max = String(model.max);
      slider.step = String(model.step ?? 0.1);
      slider.value = String(model.value ?? model.min);
      slider.addEventListener('input', () => { input.value = slider.value; });
      slider.addEventListener('change', () => commit(slider.value));
      body.appendChild(slider);
    }
    if (isNumber) {
      const shift = (dir) => {
        const step = Number(model.step ?? 0.1) * dir;
        const base = Number(input.value || 0);
        commit(base + step);
      };
      body.append(stepButton(-1, shift), input, stepButton(1, shift));
    } else {
      body.appendChild(input);
    }
    if (model.unit) {
      const unit = el('span', 'pc-unit', model.unit);
      body.appendChild(unit);
    }
  }

  if (model.auto) {
    const auto = el('label', 'pc-auto');
    const box = el('input');
    box.type = 'checkbox';
    box.checked = Boolean(model.auto.active);
    box.dataset.auto = '1';
    box.addEventListener('change', () => {
      if (box.checked) onChange(AUTO);
      else onChange(formatValue(factoryValue(model)));
    });
    auto.append(box, el('span', 'pc-auto-cap', 'авто'));
    if (model.auto.hint) auto.title = `авто: ${model.auto.hint}`;
    row.appendChild(auto);
  }
  if (model.declared) {
    const reset = el('button', 'pc-reset', '↺');
    reset.type = 'button';
    reset.title = 'Вернуть заводское значение (параметр останется в строке)';
    reset.addEventListener('click', (event) => {
      event.preventDefault();
      onChange(formatValue(factoryValue(model)));
    });
    row.appendChild(reset);
  }
  return row;
}

/** Панель параметров одной команды: строки в порядке объявления. */
export function renderCommandParams(container, { command, specs, keys, onChange }) {
  container.innerHTML = '';
  const verb = String(command?.verb || '').toLowerCase();
  const declared = specs?.[verb] || {};
  const order = keys || Object.keys(declared);
  const seen = new Set();
  order.forEach((key) => {
    if (seen.has(key)) return;
    seen.add(key);
    const model = modelFromCommand(specs, command, key);
    if (model.hidden) return;
    container.appendChild(renderControl(model, (value) => onChange(key, value, command)));
  });
  return container;
}

/** Все ли параметры операции объявлены (для честного отчёта панели). */
export function undeclaredKeys(specs, command, keys) {
  const verb = String(command?.verb || '').toLowerCase();
  const declared = specs?.[verb] || {};
  const list = keys || Object.keys(command?.kwargs || {});
  return list.filter((key) => !declared[key]);
}

/**
 * Перетаскиваемые границы панелей: ширины окон, сворачивание и «во всё окно».
 *
 * Зачем отдельный модуль: раньше три колонки задавались жёсткой сеткой CSS,
 * и при длинных подписях левой панели не хватало места, а окно модели нельзя
 * было ни расширить, ни убрать с глаз. Теперь ширины — числа, их тянут мышью,
 * они запоминаются в браузере и переживают перезапуск.
 *
 * Правила:
 * * тянуть границу — меняются две соседние панели, третья не трогается;
 * * двойной щелчок по границе — свернуть/развернуть панель слева от неё;
 * * кнопка «⤢» в шапке — развернуть панель на всё окно и вернуть обратно;
 * * у свёрнутой панели остаётся узкая полоска с названием — щёлкните, чтобы
 *   вернуть;
 * * всё это помнится в localStorage, а если он недоступен — просто работает
 *   до перезагрузки.
 */

const KEY = 'forma3d.panels.v1';
const COLLAPSED = 26;          // ширина свёрнутой панели, px
const SPLITTER = 9;                 // ширина полосы-разделителя, px
const MIN = { editor: 250, viewer: 320, report: 250 };
const PANELS = ['editor', 'viewer', 'report'];

function loadState() {
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return null;
    const data = JSON.parse(raw);
    if (!data || typeof data !== 'object') return null;
    return data;
  } catch (e) {
    return null;
  }
}

function saveState(state) {
  try {
    localStorage.setItem(KEY, JSON.stringify(state));
  } catch (e) { /* приватный режим — просто не запоминаем */ }
}

export class PanelLayout {
  constructor({ layout, onResize } = {}) {
    this.layout = layout || document.getElementById('layout');
    if (!this.layout) return;
    this.onResize = onResize || (() => {});
    this.panels = {};
    PANELS.forEach((name) => {
      this.panels[name] = document.getElementById(
        { editor: 'panel-editor', viewer: 'panel-viewer', report: 'panel-report' }[name]);
    });
    const saved = loadState() || {};
    this.state = {
      widths: saved.widths && PANELS.every((n) => Number(saved.widths[n]) > 0)
        ? { editor: Number(saved.widths.editor), viewer: Number(saved.widths.viewer),
            report: Number(saved.widths.report) }
        : null,
      collapsed: Object.assign({ editor: false, viewer: false, report: false },
        saved.collapsed || {}),
      maximized: saved.maximized || '',
    };
    this._drag = null;
    this._bindSplitters();
    this._bindButtons();
    this.apply();
    window.addEventListener('resize', () => this.apply());
  }

  /** Доступная ширина и ширины по умолчанию (доли от окна). */
  _base() {
    const free = Math.max(600, this.layout.clientWidth - SPLITTER * 2);
    if (!this.state.widths) {
      return { editor: free * 0.27, viewer: free * 0.45, report: free * 0.28 };
    }
    const sum = PANELS.reduce((a, n) => a + this.state.widths[n], 0);
    if (!sum) return { editor: free * 0.27, viewer: free * 0.45, report: free * 0.28 };
    if (Math.abs(sum - free) < 2) return { ...this.state.widths };
    // окно изменили — тянем пропорционально, а не «обрезаем одну панель»
    const k = free / sum;
    return { editor: this.state.widths.editor * k,
             viewer: this.state.widths.viewer * k,
             report: this.state.widths.report * k };
  }

  /**
   * Ставит ширины в сетку и прячет содержимое свёрнутых панелей.
   *
   * `notify` и `save` отключаются на время перетаскивания: пересчитывать
   * размеры 3D-окна и писать в localStorage на каждом движении мыши незачем —
   * это делает панель вязкой. Итог фиксируется, когда кнопку отпустили.
   */
  apply({ notify = true, save = true } = {}) {
    const base = this._base();
    const max = this.state.maximized;
    PANELS.forEach((name) => {
      const el = this.panels[name];
      if (!el) return;
      const collapsed = Boolean(this.state.collapsed[name]) || (max && max !== name);
      el.classList.toggle('is-collapsed', collapsed);
      const w = collapsed ? COLLAPSED : Math.max(MIN[name], base[name]);
      this.layout.style.setProperty(`--w-${name}`, `${Math.round(w)}px`);
    });
    // границы у свёрнутых панелей уже не нужны, но пусть остаются: они малы
    document.querySelectorAll('.splitter').forEach((sp) => {
      const right = sp.dataset.split === 'editor' ? 'viewer' : 'report';
      const fold = sp.querySelector('.splitter-fold');
      if (!fold) return;
      const collapsed = this.panels[right]?.classList.contains('is-collapsed');
      fold.textContent = collapsed ? '‹' : '›';
      fold.dataset.fold = right;
      fold.title = collapsed
        ? 'Развернуть панель'
        : `Свернуть панель «${right === 'viewer' ? 'Модель' : 'Отчёт'}»`;
    });
    if (notify) this.onResize();
    if (save) saveState(this.state);
  }

  _bindSplitters() {
    document.querySelectorAll('.splitter').forEach((sp) => {
      sp.addEventListener('pointerdown', (e) => {
        if (e.target.closest('.splitter-fold')) return;
        e.preventDefault();
        const left = sp.dataset.split === 'editor' ? 'editor' : 'viewer';
        const right = sp.dataset.split === 'editor' ? 'viewer' : 'report';
        const base = this._base();
        this._drag = {
          sp, left, right, startX: e.clientX,
          leftW: base[left], rightW: base[right],
        };
        sp.classList.add('dragging');
        sp.setPointerCapture?.(e.pointerId);
      });
      sp.addEventListener('pointermove', (e) => {
        const d = this._drag;
        if (!d || d.sp !== sp) return;
        const dx = e.clientX - d.startX;
        const free = Math.max(600, this.layout.clientWidth - SPLITTER * 2);
        const minLeft = MIN[d.left];
        const minRight = MIN[d.right];
        let leftW = d.leftW + dx;
        let rightW = d.rightW - dx;
        if (leftW < minLeft) { rightW -= (minLeft - leftW); leftW = minLeft; }
        if (rightW < minRight) { leftW -= (minRight - rightW); rightW = minRight; }
        if (leftW < minLeft || rightW < minRight) return;
        if (leftW + rightW > free) {
          const over = leftW + rightW - free;
          rightW = Math.max(minRight, rightW - over);
          leftW = Math.min(leftW, free - rightW);
        }
        const widths = this._base();
        widths[d.left] = leftW;
        widths[d.right] = rightW;
        this.state.widths = widths;
        this.state.maximized = '';
        this.apply({ notify: false, save: false });
        // Раз в 120 мс всё-таки пересчитываем размер окна модели, чтобы
        // картинка не растягивалась, а на каждом движении этого не делаем.
        const now = performance.now();
        if (now - (this._resizeAt || 0) > 120) {
          this._resizeAt = now;
          this.onResize();
        }
      });
      const end = () => {
        const d = this._drag;
        if (!d || d.sp !== sp) return;
        this._drag = null;
        sp.classList.remove('dragging');
        this.apply();
      };
      sp.addEventListener('pointerup', end);
      sp.addEventListener('pointercancel', end);
      sp.addEventListener('lostpointercapture', end);
      sp.addEventListener('dblclick', (e) => {
        if (e.target.closest('.splitter-fold')) return;
        const name = sp.dataset.split === 'editor' ? 'editor' : 'viewer';
        this.toggleCollapse(name);
      });
    });
    document.querySelectorAll('.splitter-fold').forEach((btn) => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        this.toggleCollapse(btn.dataset.fold);
      });
    });
  }

  _bindButtons() {
    document.querySelectorAll('.panel-max').forEach((btn) => {
      btn.addEventListener('click', (e) => {
        e.preventDefault();
        e.stopPropagation();
        this.toggleMaximize(btn.dataset.panel);
      });
    });
    document.querySelectorAll('.panel-fold').forEach((btn) => {
      btn.addEventListener('click', () => {
        this.state.collapsed[btn.dataset.panel] = false;
        if (this.state.maximized && this.state.maximized !== btn.dataset.panel) {
          this.state.maximized = '';
        }
        this.apply();
      });
    });
  }

  toggleCollapse(name) {
    if (!name) return;
    this.state.maximized = '';
    this.state.collapsed[name] = !this.state.collapsed[name];
    this.apply();
  }

  /** Развернуть одну панель на всё окно и вернуть прежний вид. */
  toggleMaximize(name) {
    if (!name) return;
    this.state.maximized = this.state.maximized === name ? '' : name;
    this.apply();
  }

  /** Сброс к обычному виду (пригодится тестам и кнопке). */
  reset() {
    this.state.widths = null;
    this.state.collapsed = { editor: false, viewer: false, report: false };
    this.state.maximized = '';
    this.apply();
  }
}

/** Установка разметки панелей: возвращает объект, если разметка на месте. */
export function installPanelLayout(options = {}) {
  try {
    return new PanelLayout(options);
  } catch (err) {
    console.warn('панели: не удалось включить перетаскивание', err);
    return null;
  }
}

const NS = 'http://www.w3.org/2000/svg';

function defs() {
  return `<defs>
    <marker id="arrow-fold" markerWidth="10" markerHeight="10" refX="8" refY="3" orient="auto" markerUnits="strokeWidth"><path d="M0,0 L0,6 L9,3 z" fill="#cf704f"/></marker>
    <marker id="arrow-green" markerWidth="10" markerHeight="10" refX="8" refY="3" orient="auto" markerUnits="strokeWidth"><path d="M0,0 L0,6 L9,3 z" fill="#527766"/></marker>
    <filter id="paper-shadow" x="-30%" y="-30%" width="160%" height="160%"><feDropShadow dx="0" dy="5" stdDeviation="6" flood-color="#3c463d" flood-opacity=".13"/></filter>
    <pattern id="glue-hatch" width="8" height="8" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><line x1="0" y1="0" x2="0" y2="8" stroke="#b28a3d" stroke-width="3" opacity=".45"/></pattern>
  </defs>`;
}

function svg(content, viewBox = '0 0 520 400', extra = '') {
  return `<svg ${extra} xmlns="${NS}" viewBox="${viewBox}" role="img" aria-label="Схема шага оригами">${defs()}${content}</svg>`;
}

const line = (x1, y1, x2, y2, cls = 'crease', extra = '') => `<line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" class="${cls}" ${extra}/>`;
const label = (x, y, text, cls = 'diagram-label') => `<text x="${x}" y="${y}" class="${cls}" text-anchor="middle">${text}</text>`;
const arrow = (path, color = 'fold') => `<path d="${path}" class="fold-arrow ${color === 'green' ? 'green' : ''}" marker-end="url(#arrow-${color === 'green' ? 'green' : 'fold'})"/>`;
const square = (x = 145, y = 55, size = 230, cls = '') => `<rect x="${x}" y="${y}" width="${size}" height="${size}" rx="2" class="paper ${cls}" filter="url(#paper-shadow)"/>`;
const diamond = (cx = 260, cy = 175, r = 135, cls = '') => `<path d="M${cx} ${cy-r} L${cx+r} ${cy} L${cx} ${cy+r} L${cx-r} ${cy} Z" class="paper ${cls}" filter="url(#paper-shadow)"/>`;
const badge = (x, y, text) => `<g><circle cx="${x}" cy="${y}" r="16" class="step-badge"/><text x="${x}" y="${y+5}" class="badge-text" text-anchor="middle">${text}</text></g>`;

function diagonals() {
  return svg(`${square()}
    ${line(145,55,375,285,'valley')}${line(375,55,145,285,'valley')}
    ${arrow('M184 85 Q248 122 324 229')}${arrow('M335 84 Q272 125 196 229')}
    ${badge(124,42,'1')}${badge(396,42,'2')}
    ${label(260,329,'Сложи → прогладь → раскрой')}
    <path d="M206 351 H314" class="unfold-arrow" marker-end="url(#arrow-green)"/>${label(260,376,'РАСКРЫТЬ ПОСЛЕ КАЖДОГО СГИБА','diagram-note')}`);
}

function book() {
  return svg(`${square()}
    ${line(145,170,375,170,'mountain')}${line(260,55,260,285,'mountain')}
    ${line(145,55,375,285,'old-crease')}${line(375,55,145,285,'old-crease')}
    ${arrow('M185 130 Q245 150 325 165')}${arrow('M220 90 Q242 145 258 225')}
    ${badge(124,42,'1')}${badge(396,42,'2')}
    ${label(260,329,'Сначала переверни лист цветом вверх')}
    ${label(260,362,'— —  старые складки    — · —  новые складки','diagram-note')}`);
}

function collapse() {
  return svg(`${diamond(175,190,105,'paper-back')}
    ${line(175,85,175,295,'old-crease')}${line(70,190,280,190,'old-crease')}
    ${arrow('M83 190 Q116 160 155 188','green')}${arrow('M267 190 Q234 160 195 188','green')}
    ${arrow('M302 190 L346 190','green')}
    ${diamond(414,190,65)}
    ${line(349,190,414,255,'valley')}${line(414,125,414,255,'center-crease')}
    ${label(414,290,'открытые концы','diagram-note')}
    ${label(175,337,'Бока уходят внутрь')} ${label(414,337,'База «квадрат»')}`);
}

function petal() {
  return svg(`${diamond(260,176,120)}
    ${line(260,56,260,296,'center-crease')}
    ${line(140,176,260,296,'valley')}${line(380,176,260,296,'valley')}
    ${line(179,117,341,117,'mountain')}
    ${arrow('M151 198 Q191 197 238 239')}${arrow('M369 198 Q329 197 282 239')}
    ${arrow('M260 280 Q225 222 258 93','green')}
    ${badge(105,125,'1')}${badge(408,126,'2')}${badge(395,290,'3')}
    ${label(260,335,'Сделай разметку, раскрой и подними один слой')}`);
}

function repeat() {
  return svg(`${diamond(168,180,92)}
    ${line(168,88,168,272,'center-crease')}
    ${arrow('M239 117 Q316 56 359 139','green')}
    ${diamond(377,180,66,'paper-back')}
    ${line(377,114,377,246,'center-crease')}
    <path d="M230 307 H303" class="fold-arrow" marker-end="url(#arrow-fold)"/>
    ${label(266,340,'ПОВТОРИТЬ С ОБРАТНОЙ СТОРОНЫ','diagram-note')}
    <g transform="translate(264 120)"><circle r="28" class="turn-disc"/><path d="M-10 3 A13 13 0 1 1 9 10" class="turn-icon" marker-end="url(#arrow-green)"/></g>`);
}

function narrow() {
  return svg(`<path d="M260 45 L350 155 L304 320 L260 286 L216 320 L170 155 Z" class="paper" filter="url(#paper-shadow)"/>
    ${line(260,45,260,286,'center-crease')}
    ${line(174,163,260,286,'valley')}${line(346,163,260,286,'valley')}
    ${arrow('M174 218 Q209 217 243 265')}${arrow('M346 218 Q311 217 277 265')}
    <path d="M210 268 L260 320 L310 268" class="paper-fold-back"/>
    ${label(260,359,'Повтори на обратной стороне')}
    ${badge(395,102,'×2')}`);
}

function reverse() {
  return svg(`<path d="M128 277 L260 96 L392 277 L309 250 L260 282 L211 250 Z" class="paper" filter="url(#paper-shadow)"/>
    ${line(174,240,209,130,'valley')}${line(346,240,311,130,'valley')}
    ${line(174,240,230,229,'mountain')}${line(346,240,290,229,'mountain')}
    ${arrow('M182 228 Q113 166 178 98')}${arrow('M338 228 Q407 166 342 98')}
    <path d="M162 236 L174 128 L207 237" class="ghost-fold"/><path d="M358 236 L346 128 L313 237" class="ghost-fold"/>
    ${label(260,330,'Раскрой слои → выверни конец → закрой')}
    ${label(260,357,'Один конец выше: это шея','diagram-note')}`);
}

function head() {
  return svg(`<path d="M112 288 L229 228 L263 71 L296 225 L407 288 L310 257 L260 281 L211 257 Z" class="paper" filter="url(#paper-shadow)"/>
    <path d="M250 90 L263 71 L278 96" class="paper-front"/>
    ${line(251,92,280,92,'mountain')}${line(262,74,263,110,'valley')}
    ${arrow('M289 69 Q323 84 285 119')}
    <path d="M263 72 L289 106 L278 98" class="ghost-fold"/>
    ${label(260,334,'Маленький внутренний обратный сгиб')}
    <path d="M312 69 h82" class="leader"/>${label(391,59,'клюв','diagram-note')}`);
}

function wings() {
  return svg(`<path d="M260 66 L302 213 L396 290 L306 254 L260 282 L214 254 L124 290 L218 213 Z" class="paper" filter="url(#paper-shadow)"/>
    <path d="M218 213 L124 72 L260 176 Z" class="ghost-fold"/><path d="M302 213 L396 72 L260 176 Z" class="ghost-fold"/>
    ${arrow('M153 101 Q109 164 143 231')}${arrow('M367 101 Q411 164 377 231')}
    ${line(218,213,260,176,'valley')}${line(302,213,260,176,'valley')}
    ${label(260,336,'Опусти крылья симметрично')}`);
}

function final() {
  return svg(`<g transform="translate(8 -4)">
    <path d="M251 218 L69 118 L152 249 L233 269 Z" class="crane-paper" filter="url(#paper-shadow)"/>
    <path d="M251 218 L426 112 L360 250 L275 269 Z" class="crane-paper-dark" filter="url(#paper-shadow)"/>
    <path d="M232 221 L254 178 L282 221 L272 277 L239 277 Z" class="crane-body"/>
    <path d="M265 210 L301 112 L320 95 L337 107 L314 121 L286 224" class="crane-paper"/>
    <path d="M319 96 L353 117 L329 122 L314 121 Z" class="crane-paper-dark"/>
    <path d="M243 218 L202 116 L180 88 L218 111 L262 220" class="crane-paper-dark"/>
    <circle cx="326" cy="107" r="2.8" fill="#36483f"/>
    </g>${label(260,326,'Слегка потяни крылья и расправь тело')}
    ${arrow('M196 343 L123 343','green')}${arrow('M324 343 L397 343','green')}`);
}

export function stepDiagram(id) {
  const diagrams = { diagonals, book, collapse, petal, repeat, narrow, reverse, head, wings, final };
  return (diagrams[id] || diagonals)();
}

export function creasePattern() {
  const lines = [];
  const at = n => 45 + n * 310;
  lines.push(line(at(0),at(0),at(1),at(1),'valley'), line(at(1),at(0),at(0),at(1),'valley'));
  lines.push(line(at(.5),at(0),at(.5),at(1),'mountain'), line(at(0),at(.5),at(1),at(.5),'mountain'));
  for (const q of [.25,.75]) {
    lines.push(line(at(q),at(0),at(q),at(1),'valley'), line(at(0),at(q),at(1),at(q),'valley'));
  }
  lines.push(
    line(at(.25),at(0),at(1),at(.75),'mountain'), line(at(.75),at(0),at(0),at(.75),'mountain'),
    line(at(.25),at(1),at(1),at(.25),'mountain'), line(at(.75),at(1),at(0),at(.25),'mountain'),
    line(at(.25),at(.25),at(.75),at(.75),'valley'), line(at(.75),at(.25),at(.25),at(.75),'valley'),
    line(at(.25),at(.25),at(.25),at(.75),'mountain'), line(at(.75),at(.25),at(.75),at(.75),'mountain'),
    line(at(.25),at(.25),at(.75),at(.25),'mountain'), line(at(.25),at(.75),at(.75),at(.75),'mountain')
  );
  return svg(`<rect x="45" y="45" width="310" height="310" class="paper" filter="url(#paper-shadow)"/>${lines.join('')}
    <path d="M45 45 L200 45 L200 90 L90 90 L90 200 L45 200 Z" fill="url(#glue-hatch)" opacity=".0"/>
    ${label(200,389,'Учебная схема основных складок · не полная развёртка слоёв','diagram-note')}`, '0 0 400 410');
}

export function projectIcon(type) {
  const shapes = {
    crane: '<path d="M8 25 L25 14 L42 25 L31 22 L27 36 L23 22 Z"/><path d="M25 14 L29 5 L34 8 L29 10"/>',
    ring: '<circle cx="25" cy="25" r="15"/><circle cx="25" cy="25" r="7"/><path d="M25 7v8M40 25h-8M25 43v-8M10 25h8"/>',
    cube: '<path d="M25 7 41 16v19L25 44 9 35V16Z"/><path d="m9 16 16 9 16-9M25 25v19M17 12l16 9"/>',
    box: '<path d="M10 17h30v24H10zM7 10h36v9H7zM25 10v31"/>'
  };
  return `<svg viewBox="0 0 50 50" aria-hidden="true"><g fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">${shapes[type] || shapes.crane}</g></svg>`;
}

export function operationIcon(type) {
  const map = {
    valley: '<path d="M5 16h30" stroke-dasharray="5 4"/><path d="m9 7 11 5L31 7"/>',
    mountain: '<path d="M5 16h30" stroke-dasharray="9 3 2 3"/><path d="m9 25 11-5 11 5"/>',
    crease: '<path d="M5 16h30" stroke-dasharray="4 3"/><path d="M11 7q18 0 18 10"/><path d="m10 25 10-4-5 10"/>',
    reverse: '<path d="M8 28 20 8l12 20M13 22l7-8 7 8"/><path d="M29 7q9 6 1 13"/>',
    turn: '<path d="M9 13a12 12 0 1 1-1 10"/><path d="m8 6 1 8 8-2"/>',
    cut: '<circle cx="10" cy="27" r="4"/><circle cx="20" cy="27" r="4"/><path d="m13 24 18-17M17 24 7 8M20 15h16"/>',
    glue: '<path d="M20 4S10 17 10 24a10 10 0 0 0 20 0C30 17 20 4 20 4Z"/><path d="M4 34h32" stroke-dasharray="3 3"/>',
    repeat: '<path d="M8 10h23v23H8z"/><path d="M13 5h23v23"/><text x="19" y="27" stroke="none" font-size="13" fill="currentColor">×2</text>'
  };
  return `<svg viewBox="0 0 40 40" aria-hidden="true"><g fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">${map[type] || map.valley}</g></svg>`;
}

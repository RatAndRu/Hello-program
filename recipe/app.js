(() => {
  const STORAGE_KEY = 'bliny-v1-done';
  const BASE_SERVINGS = 1;
  const PANCAKES_PER_SERVING = 9;

  const ingredients = [
    {
      name: 'Кефир',
      base: 250,
      unit: 'мл',
      baseText: '1 стакан',
      note: 'любой жирности, можно слегка просроченный',
    },
    {
      name: 'Кипяток',
      base: 250,
      unit: 'мл',
      baseText: '1 стакан',
      note: 'прямо из только что вскипевшего чайника',
    },
    {
      name: 'Мука',
      base: 200,
      unit: 'г',
      baseText: '1,5 стакана',
      note: 'около 200 г, это 7–8 столовых ложек с горкой',
    },
    {
      name: 'Яйца',
      base: 2,
      unit: 'шт',
    },
    {
      name: 'Сахар',
      base: 2,
      unit: 'ст. л.',
    },
    {
      name: 'Соль',
      base: 0.5,
      unit: 'ч. л.',
    },
    {
      name: 'Сода',
      base: 0.5,
      unit: 'ч. л.',
      note: 'без горки, обязательна для реакции с кефиром',
    },
    {
      name: 'Растительное масло',
      base: 3,
      unit: 'ст. л.',
    },
  ];

  const steps = [
    {
      id: 1,
      title: 'Шаг 1. Основа',
      text:
        'В миске смешайте вилкой или венчиком 2 яйца, соль и сахар. Влейте стакан кефира и хорошо перемешайте.',
      img: 'images/step1.jpg',
    },
    {
      id: 2,
      title: 'Шаг 2. Густое тесто',
      text:
        'Высыпьте в миску всю муку и хорошо размешайте. Жидкости пока мало, тесто получится густым (как на оладьи), и вы легко разобьете все комочки.',
      img: 'images/step2.jpg',
    },
    {
      id: 3,
      title: 'Шаг 3. Магия с кипятком',
      text:
        'Вскипятите чайник. Налейте стакан кипятка. Бросьте в стакан с кипятком пол чайной ложки соды, быстро размешайте ложкой и сразу выливайте эту воду в тесто, при этом второй рукой быстро-быстро размешивайте тесто венчиком или вилкой. Тесто на глазах станет жидким, воздушным и пойдут пузырьки.',
      img: 'images/step3.jpg',
    },
    {
      id: 4,
      title: 'Шаг 4. Масло и отдых',
      text:
        'Влейте 3 столовые ложки растительного масла, перемешайте и дайте постоять 5–10 минут, пока греется сковородка.',
      img: 'images/step4.jpg',
    },
  ];

  const frying = [
    {
      title: 'Разогрейте сковородку',
      text:
        'Блинную сковородку нужно нагреть очень сильно (на среднем или чуть выше среднего огня). Если сковорода холодная — первый блин прилипнет.',
      img: 'images/fry1.jpg',
    },
    {
      title: 'Смажьте один раз',
      text:
        'Капните буквально пару капель масла на сковороду и размажьте салфеткой или кисточкой. Больше сковороду мазать не придется — масло уже есть в тесте.',
      img: 'images/fry2.jpg',
    },
    {
      title: 'Наливайте тесто',
      text:
        'Наберите примерно половину или две трети половника теста. Одной рукой держите сковородку на весу и крутите её по кругу, другой — лейте тесто в центр, чтобы оно тонко растеклось по всему дну.',
      img: null,
    },
    {
      title: 'Жарьте и переворачивайте',
      text:
        'На первой стороне блин жарится примерно 1 минуту. Как только сверху тесто перестало быть жидким и стало матовым, а края начали темнеть и подсыхать — подденьте край ножом или лопаткой и переворачивайте. На второй стороне жарьте секунд 30.',
      img: null,
    },
    {
      title: 'Складывайте стопкой',
      text:
        'В идеале — каждый горячий блинчик сразу слегка смажьте куском сливочного масла, тогда края не будут сухими.',
      img: null,
    },
  ];

  const tips = [
    {
      title: 'Блин слишком толстый, тесто плохо растекается',
      text: 'Долийте в миску с тестом пару столовых ложек тёплой воды или молока.',
    },
    {
      title: 'Блин рвётся при перевороте',
      text: 'Всыпьте в тесто еще одну столовую ложку муки и размешайте.',
    },
  ];

  // ---------- helpers ----------

  const formatNumber = (n) => {
    const s = String(n);
    if (s.endsWith('.5')) return s.replace('.5', '½');
    if (s.includes('.')) return parseFloat(s).toFixed(2).replace('.', ',');
    return s.replace('.', ',');
  };

  const getDone = () => {
    try {
      return JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}');
    } catch (e) {
      return {};
    }
  };
  const setDone = (map) => {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(map));
    } catch (e) {
      // ignore quota errors
    }
  };

  // ---------- render ----------

  const servingsInput = document.getElementById('servings');
  let servings = parseInt(servingsInput.value, 10) || 1;

  const renderIngredients = () => {
    const list = document.getElementById('ing-list');
    const estPancakes = servings * PANCAKES_PER_SERVING;
    list.innerHTML = '';
    ingredients.forEach((ing) => {
      const scaled = ing.base * servings;
      const item = document.createElement('li');
      item.className = 'ing-item';
      const nameEl = document.createElement('div');
      nameEl.className = 'ing-name';
      nameEl.textContent = ing.name;
      const amountEl = document.createElement('div');
      amountEl.className = 'ing-amount';
      // whole units for eggs
      const displayValue = ing.unit === 'шт' ? Math.round(scaled) : formatNumber(scaled);
      amountEl.textContent = ing.unit === 'шт' ? `${displayValue} ${ing.unit}` : `${displayValue} ${ing.unit}`;
      const baseEl = document.createElement('div');
      baseEl.className = 'ing-base';
      const baseLabel = ing.baseText || `${formatNumber(ing.base)} ${ing.unit}`;
      baseEl.textContent = `₍${baseLabel} × ${servings}₎ · ориентировочно ${estPancakes} блинов всего`;
      item.appendChild(nameEl);
      item.appendChild(amountEl);
      if (ing.note) {
        const noteEl = document.createElement('div');
        noteEl.className = 'ing-note';
        noteEl.textContent = ing.note;
        item.appendChild(noteEl);
      }
      item.appendChild(baseEl);
      list.appendChild(item);
    });
  };

  const renderSteps = () => {
    const grid = document.getElementById('step-grid');
    const done = getDone();
    grid.innerHTML = '';
    steps.forEach((step) => {
      const card = document.createElement('div');
      card.className = 'card';
      if (step.img) {
        const img = document.createElement('img');
        img.src = step.img;
        img.alt = step.title;
        img.onerror = function () {
          this.style.display = 'none';
          this.nextElementSibling.style.display = 'flex';
        };
        const fallback = document.createElement('div');
        fallback.className = 'hero-fallback';
        fallback.style.height = '200px';
        fallback.style.fontSize = '56px';
        fallback.textContent = '🍳';
        img.after(fallback);
        card.appendChild(img);
      }
      const h = document.createElement('h3');
      h.textContent = step.title;
      card.appendChild(h);
      const p = document.createElement('p');
      p.textContent = step.text;
      card.appendChild(p);
      const doneBar = document.createElement('div');
      doneBar.className = 'done';
      const cb = document.createElement('input');
      cb.type = 'checkbox';
      cb.id = `step-${step.id}`;
      cb.checked = !!done[step.id];
      const lbl = document.createElement('label');
      lbl.htmlFor = `step-${step.id}`;
      lbl.textContent = cb.checked ? 'Сделано ✓' : 'Отметить сделанным';
      if (cb.checked) lbl.classList.add('checked');
      cb.addEventListener('change', () => {
        const next = getDone();
        if (cb.checked) next[step.id] = true; else delete next[step.id];
        setDone(next);
        lbl.classList.toggle('checked', cb.checked);
        lbl.textContent = cb.checked ? 'Сделано ✓' : 'Отметить сделанным';
      });
      doneBar.appendChild(cb);
      doneBar.appendChild(lbl);
      card.appendChild(doneBar);
      grid.appendChild(card);
    });
  };

  const renderFrying = () => {
    const grid = document.getElementById('fry-grid');
    grid.innerHTML = '';
    frying.forEach((item, i) => {
      const card = document.createElement('div');
      card.className = 'card';
      const h = document.createElement('h3');
      h.textContent = `${i + 1}. ${item.title}`;
      card.appendChild(h);
      const p = document.createElement('p');
      p.textContent = item.text;
      card.appendChild(p);
      grid.appendChild(card);
    });
  };

  const renderTips = () => {
    const grid = document.getElementById('tips-grid');
    grid.innerHTML = '';
    tips.forEach((item) => {
      const card = document.createElement('div');
      card.className = 'card tips-card';
      const h = document.createElement('h3');
      h.textContent = item.title;
      card.appendChild(h);
      const p = document.createElement('p');
      p.textContent = item.text;
      card.appendChild(p);
      grid.appendChild(card);
    });
  };

  const updateServings = () => {
    servings = parseInt(servingsInput.value, 10) || 1;
    renderIngredients();
  };

  servingsInput.addEventListener('input', updateServings);

  renderIngredients();
  renderSteps();
  renderFrying();
  renderTips();
})();

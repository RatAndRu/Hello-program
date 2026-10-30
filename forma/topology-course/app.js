/* ==========================================================================
   Топология тел — данные и интерактив. Без зависимостей, без сборки.
   Работает и по http, и открытием index.html с диска.
   ========================================================================== */

(function () {
  "use strict";

  // --------------------------------------------------------------------------
  //  Данные
  // --------------------------------------------------------------------------

  // Пары «плохо / лечение»: схемы генерирует forma/tools/make_topology_figures.py
  const GALLERY = [
    {
      key: "pole-bend",
      title: "Полюс в зоне изгиба",
      cause: "Пять рёбер сходятся там, где поверхность сильнее всего гнётся. Catmull-Clark рядом с нерегулярной вершиной даёт другую гладкость — появляется ямка.",
      find: "Включить SubD и покрутить объект. Показать валентность вершин: 5 или 3 на скруглении.",
      fix: "Сдвинуть поток «Rotate Edge» на соседних квадах, чтобы полюс уехал на плоский участок; при нескольких полюсах собрать их парами.",
      note: "Полюс на плоском участке — идеальное место для него. Проблема не в полюсе, а в его адресе."
    },
    {
      key: "single-loop",
      title: "Одна петля в суставе",
      cause: "Весь изгиб приходится на один ряд граней: внутренняя сторона сжимается в ноль, внешняя растягивается.",
      find: "Согнуть на 90° и на 135°. Сустав «проваливается», объём исчезает.",
      fix: "Кольцевые петли поперёк оси вращения: 3–4 для мобильного персонажа, 4–6 для обычного, 6–8 для крупного плана.",
      note: "Петли распределяют деформацию по зоне, а не концентрируют её на одном ребре."
    },
    {
      key: "ngon",
      title: "N-гон на скруглении",
      cause: "Грань с 6+ вершинами подразбивается и триангулируется непредсказуемо; веер из центра добавляет звезду и иглы.",
      find: "3D-Print Toolbox ▸ Distorted; проверить, как выглядит объект после триангуляции в другой программе.",
      fix: "Разобрать на квады: кольца + полюса по кругу. N-гон оставить только на плоской недеформируемой грани.",
      note: "На плоскости n-гон — нормальное решение (крышка, торец, стена)."
    },
    {
      key: "slivers",
      title: "Иглы вдоль скругления",
      cause: "Треугольники с очень острым углом, у которых длинная сторона идёт вдоль изогнутой поверхности: нормали интерполируются полосами.",
      find: "Наш аудит: доля «игл на изгибе». Глазами — полосы на гладком скруглении.",
      fix: "Добавить ряд вершин или сегментов вдоль оси; разрезать неплоские грани; убрать лишние вершины, из-за которых игла появилась.",
      note: "Игла в плоской панели безвредна: у всех соседей одна нормаль. У тонкой длинной детали иглы неизбежны."
    },
    {
      key: "density",
      title: "Рывок плотности",
      cause: "Крупные грани вплотную к мелким: подразбиение распределяет натяжение неравномерно, появляются волны.",
      find: "Аудит: разброс длин рёбер. В Blender — проволочка при большом увеличении.",
      fix: "Разнести петли равномерно (LoopTools ▸ Relax), убрать «микрокольца» через Merge by Distance и Degenerate Dissolve.",
      note: "Плотность меняют плавно, через полюса, а не общим сгущением сетки."
    },
    {
      key: "support",
      title: "SubD съедает острый край",
      cause: "Нет поддерживающих петель и нет крейзов: подразбиение усредняет угол, габарит «худеет».",
      find: "Включить SubD 1–2 и сравнить силуэт до и после.",
      fix: "Две support loops по обе стороны ребра (в 1–3 % габарита) или crease 0…10. Для блика — bevel + поддержка.",
      note: "Crease дешевле, но не всегда переживает экспорт между пакетами."
    },
    {
      key: "diagonal",
      title: "Диагональный поток",
      cause: "Петли идут под углом к форме: при сгибе грани уходят «винтом», нормали расходятся, силуэт ломается.",
      find: "Alt+click по петле: она не доходит до логического конца и виляет.",
      fix: "Перестроить поток по форме: кольца поперёк изгиба, выровнять через Grid Fill и Relax.",
      note: "Направление петель важнее их количества."
    },
    {
      key: "winding",
      title: "Перевёрнутая грань",
      cause: "Часть граней обходится в обратном порядке: после ручного моделирования, булевых, зеркала с отрицательным масштабом.",
      find: "3D-Print Toolbox ▸ Bad Contiguous Edges; аудит ▸ «несогласованный обход».",
      fix: "A → Shift+N. Не помогло — Merge by Distance и снова Shift+N. Проверить, что масштаб применён.",
      note: "Это первое, что проверяют при «тёмных пятнах» на ровном месте."
    },
    {
      key: "hole",
      title: "Дырка в поверхности",
      cause: "Пропущенная грань, удалённая «лишняя» или незакрытый контур после булевой операции.",
      find: "Select ▸ All by Trait ▸ Non Manifold; аудит ▸ «граничные рёбра».",
      fix: "F для одной грани, Grid Fill для ровной решётки, Bridge Edge Loops между контурами.",
      note: "Если деталь — тело, дырка это ошибка; у плоского листа без толщины граница нормальна."
    },
    {
      key: "nonmanifold",
      title: "Лист ребром (non-manifold)",
      cause: "К ребру приклеено три и более граней, или лист без толщины. Непонятно, где «внутри».",
      find: "Select ▸ Non Manifold; 3D-Print Toolbox ▸ Solid.",
      fix: "Решить, что это: одно тело (сшить, убрать внутренние грани) или два объекта. «Лист ребром» не оставлять.",
      note: "Для печати, CAD и булевых операций это важнее красоты потока."
    },
    {
      key: "duplicates",
      title: "Незаваренные вершины",
      cause: "Две половины объекта смотрят одинаково, но вершины не слиты: шов держится только визуально.",
      find: "Merge by Distance показывает, сколько вершин слилось; аудит ▸ «совпадающие вершины».",
      fix: "M ▸ By Distance, затем Shift+N. В glTF часть таких вершин — законный развод по нормалям и UV.",
      note: "В GLB «лишние» вершины по швам — это норма, а не дефект."
    },
    {
      key: "tjunction",
      title: "T-стык",
      cause: "Вершина одной детали лежит на ребре соседней, не входя в её грань.",
      find: "При деформации появляется щель; на проволочке видна «висячая» вершина.",
      fix: "J (Connect) довести ребро до вершины; либо сварить и разрезать соседнюю грань ножом.",
      note: "Классическая причина трещин в местах стыка двух частей."
    },
    {
      key: "sphere-pole",
      title: "Полюс UV-сферы",
      cause: "Все меридианы сходятся в одну точку: звезда 12+ рёбер, иглы у полюса, щипок при подразбиении.",
      find: "Аудит: гистограмма валентности; визуально — «звёздочка» на полюсе.",
      fix: "Сфера с квадовой разводкой: кольца и полюса по кругу, по 4 ребра в вершине.",
      note: "Ту же проблему дают конусы и «крышки» цилиндров, собранные веером."
    },
    {
      key: "tris-deform",
      title: "Треугольники в суставе",
      cause: "Каждая грань разрезана по диагонали: при сгибе диагонали ведут себя по-разному, поверхность идёт «лестницей».",
      find: "Включить каркас на деформированной позе; посмотреть на просвет.",
      fix: "Квады и петли поперёк изгиба; треугольники оставить на плоских недеформируемых участках.",
      note: "В game-ready меше треугольники нормальны — но не в зоне деформации."
    }
  ];

  const CATEGORIES = ["все", "нормали", "тело", "плотность", "деформация", "экспорт", "печать", "форма"];

  // Схемы: в собранной версии приходят встроенными (window.TOPO_FIG),
  // при разработке по http — обычными файлами из assets/fig.
  const FIG = window.TOPO_FIG || {};
  const fig = (name) => FIG[name] || "assets/fig/" + name;

  // Каталог: симптом → причина → как найти → лечение
  const CASES = [
    ["Тёмные и светлые пятна, шов на ровном месте", "нормали", "Несогласованный обход граней, перевёрнутые нормали", "3D-Print ▸ Bad Contiguous; аудит ▸ несогласованный обход", "Shift+N, затем Merge by Distance"],
    ["Дырка, видно изнанку", "тело", "Граничные рёбра: поверхность не замкнута", "Select ▸ Non Manifold; аудит ▸ граничные рёбра", "F, Grid Fill, Bridge Edge Loops"],
    ["Лист, приклеенный ребром", "тело", "Ребро с 3+ гранями", "Non Manifold; аудит ▸ non-manifold", "Разделить на тела или сшить; убрать внутренние грани"],
    ["Z-fighting, мерцание", "тело", "Дубли граней или совпадающие поверхности", "Аудит ▸ грани-дубли", "Удалить дубли, разнести поверхности"],
    ["Трещина при деформации", "деформация", "T-стык или неслитые вершины", "Merge by Distance склеивает; аудит ▸ совпадающие вершины", "Сварка; разрезать соседнюю грань"],
    ["Волны и полосы при подразбиении", "плотность", "Неравномерная плотность, почти совпадающие кольца", "Аудит ▸ разброс длин рёбер; SubD preview", "Разнести петли, убрать лишние, Relax"],
    ["Щипок на щеке или локте", "деформация", "Полюс или звезда в зоне деформации", "Показать валентность, покрутить SubD", "Rotate Edge, loop reduction, перестроить поток"],
    ["Острый край съело после SubD", "деформация", "Нет support loops или крейзов", "SubD preview", "2 петли поддержки или crease"],
    ["Край наоборот слишком жёсткий, ступенька", "плотность", "Слишком много близких support loops", "Silhouette + SubD", "Разнести петли, уменьшить crease"],
    ["Тонкая деталь пропала при печати", "печать", "Толщина меньше технологической", "3D-Print ▸ Thickness", "Утолщить, Solidify"],
    ["Полосы на скруглении", "плотность", "Иглы и иголки на изогнутой поверхности", "Аудит ▸ иглы на изгибе", "Перестроить триангуляцию, убрать лишние вершины"],
    ["В Blender гладко, в движке полосы", "экспорт", "Неплоские квады и n-гоны триангулируются иначе", "3D-Print ▸ Distorted; аудит по GLB", "Триангулировать вручную, Split Non-Planar Faces"],
    ["После импорта всё гранёное", "экспорт", "Сглаживание не перенесено в файл", "Аудит ▸ нормали; сравнить с оригиналом", "Smooth by Angle, кастомные нормали, переэкспорт"],
    ["UV рвётся, текстура тянется", "экспорт", "Швы поперёк изгиба, неравномерная плотность", "UV-развёртка + тест деформации", "Перенести швы, выровнять плотность"],
    ["Запекание нормалей даёт артефакты", "экспорт", "Разная триангуляция low/high, иглы", "Сравнить триангуляцию; аудит", "Триангулировать до бейка, убрать иглы"],
    ["Сустав проваливается при скиннинге", "деформация", "Одна петля в суставе", "Согнуть в позу", "Добавить 2–4 петли по зоне изгиба"],
    ["Петли обрываются в середине формы", "деформация", "Поток не доведён, диагональный переход", "Alt+click по петле", "Довести петлю, перестроить через полюса"],
    ["Сетка выглядит сеткой, а не формой", "форма", "Поток идёт не вдоль формы", "Silhouette", "Петли вдоль мышц и рёбер жёсткости"],
    ["Мусор после булевой операции", "тело", "N-гоны, иглы, дубли по стыку", "3D-Print ▸ Check All; аудит GLB", "Сварка, Degenerate Dissolve, чистка"],
    ["Самопересечение внутри объёма", "тело", "Пересекающиеся детали", "3D-Print ▸ Intersections", "Булева операция или разнести детали"],
    ["Сфера со звездой на полюсе", "плотность", "Триангуляция полюса UV-сферы", "Аудит: иглы и валентность", "Квадовая разводка сферы, сместить полюс"],
    ["Модель «двойная» после зеркала", "тело", "Дубли после зеркала или копирования", "Аудит ▸ дубли граней", "Удалить дубли, сварить"],
    ["Объект прозрачный с одной стороны", "нормали", "Нормали внутрь или backface culling", "Аудит ▸ отрицательный объём оболочки", "Shift+N, проверить масштаб"],
    ["Всё разваливается при анимации", "деформация", "Плохая топология в зоне сгиба", "Тест деформации", "Кольцевые петли поперёк оси"],
    ["Виден шов симметрии", "деформация", "Нет петли по оси симметрии", "Включить SubD, посмотреть шов", "Петля по центру + Symmetrize"],
    ["Рот схлопывается при открытии", "деформация", "Нет петель по внутреннему краю губ", "Деформация", "Петля внутрь по кромке губ"],
    ["Веко режется", "деформация", "Меньше двух колец вокруг глаза", "Деформация", "Добавить кольца, развести полюса"],
    ["Длинная тонкая деталь даёт полосы", "плотность", "Иглы на изгибе (труба, шнур, рейлинг)", "Аудит ▸ иглы на изгибе", "Больше сегментов вдоль оси"],
    ["После экспорта пропали фаски", "экспорт", "Модификаторы не применены или не поддержаны", "Открыть файл, проверить", "Apply modifiers, support loops, bevel-веса"],
    ["Модель тяжёлая без пользы", "печать", "Плотность равномерно везде", "Аудит ▸ треугольники по объектам", "Decimate или ручное упрощение"]
  ].map((row, i) => ({
    n: String(i + 1).padStart(2, "0"),
    sym: row[0], cat: row[1], cause: row[2], find: row[3], fix: row[4]
  }));

  const MYTHS = [
    ["Треугольная сетка у статики", "Для рендера и печати регулярность не нужна: нужны корректность тела и нормали."],
    ["N-гон на плоской грани", "Плоскость триангулируется предсказуемо, деформации нет — придирка, а не ошибка."],
    ["Полюс на плоском участке", "Это лучшее место для полюса. Плохо — когда он на изгибе или на силуэте."],
    ["Полюса вообще", "Их число задано топологией: у квадовой сферы сумма (4 − валентность) равна 8. Сетки без полюсов не существует."],
    ["Плотная сетка у скульпта", "Скульпт — не финальная сетка, его задача держать форму."],
    ["Длинные тонкие треугольники у тонкой детали", "У троса, молнии, рейлинга других треугольников не бывает. Это геометрия, а не дефект."],
    ["Много оболочек в сборке", "Механизм из 200 деталей — это 200 оболочек. Плохо, когда оболочек больше, чем деталей."],
    ["Смешанная триангуляция после булевых", "Если триангуляция корректна и деталь не деформируется — это рабочий вариант."],
    ["Отсутствие UV", "Для печати и CAD развёртка не нужна."
    ]
  ];

  const CHECKLISTS = [
    {
      id: "export",
      title: "Перед экспортом",
      items: [
        "Merge by Distance: дублей нет",
        "Shift+N: нормали наружу",
        "Select ▸ Non Manifold: пусто (если это тело)",
        "Degenerate Dissolve: нет нулевых граней и рёбер",
        "Модификаторы применены или осознанно оставлены",
        "Масштаб применён, отрицательного масштаба нет",
        "Триангуляция осознана: n-гоны не уедут в чужой триангулятор",
        "Аудит GLB/OBJ: 0 ошибок"
      ]
    },
    {
      id: "skin",
      title: "Перед скиннингом",
      items: [
        "Кольцевые петли в локтях, коленях, плечах (3–6)",
        "Петли поперёк оси вращения, не по диагонали",
        "Полюса не на линии сгиба",
        "2 кольца вокруг глаза, 2–3 вокруг рта",
        "Петля по внутреннему краю губ",
        "Петля по оси симметрии",
        "Тест деформации на 90° и 135°"
      ]
    },
    {
      id: "subd",
      title: "Перед подразбиением",
      items: [
        "Почти всё квады; n-гоны только на плоскостях",
        "Плотность плавная",
        "Support loops или крейзы на острых рёбрах",
        "Preview 0/1/2: силуэт не прыгает, волн нет",
        "Полюса на плоском"
      ]
    },
    {
      id: "print",
      title: "Перед печатью и в CAD",
      items: [
        "Замкнуто: 0 граничных рёбер",
        "0 non-manifold, 0 дублей граней",
        "Нормали наружу, положительный объём",
        "Нет самопересечений",
        "Стенка не тоньше технологического минимума",
        "Оболочек столько, сколько деталей",
        "Неплоские грани разрезаны"
      ]
    }
  ];

  const QUIZ = [
    {
      q: "У вершины сходятся 5 рёбер. Что это и когда это проблема?",
      opts: [
        "Звезда: портит всё, что бы это ни было",
        "Полюс (N-pole): норма там, где он на изгибе или на силуэте",
        "Норма для квадовой сетки: бо́льшая часть вершин такая",
        "Ошибка экспорта, лечится сваркой вершин"
      ],
      right: 1,
      why: "В квадовой сетке регулярна валентность 4, в треугольной — 6. 5 и 3 — полюса, ими управляют потоком. Плохо, когда полюс стоит на деформируемом или изогнутом участке."
    },
    {
      q: "При подразбиении на локте появляется вмятина. Самая вероятная причина?",
      opts: [
        "Мало полигонов в модели целиком",
        "Полюс или звезда прямо в зоне изгиба",
        "Не включены кастомные нормали",
        "Неправильный материал"
      ],
      right: 1,
      why: "Catmull-Clark рядом с нерегулярной вершиной даёт другую гладкость. Полюс надо увести на плоский участок через Rotate Edge, а изгиб закрыть кольцевыми петлями."
    },
    {
      q: "SubD «съел» фаску. Самый переносимый между программами способ это исправить?",
      opts: [
        "Увеличить уровень подразбиения",
        "Поставить две support loops рядом с ребром",
        "Удалить SubD и оставить низкую сетку",
        "Заменить квады треугольниками"
      ],
      right: 1,
      why: "Support loops работают в любом пакете. Crease дешевле, но не всегда переживает экспорт. Больше уровней подразбиения сделают только хуже."
    },
    {
      q: "Ты делаешь печатную модель. Что важнее всего?",
      opts: [
        "Чтобы все грани были квадами",
        "Чтобы сетка была замкнутой, многообразной и с нормалями наружу",
        "Чтобы поток петель повторял мышцы",
        "Чтобы не было ни одного треугольника"
      ],
      right: 1,
      why: "Для печати, CAD и булевых операций решает корректность тела: 2 грани на ребро, согласованный обход, отсутствие мусора. Регулярность квадов тут не цель."
    },
    {
      q: "Модель выглядит нормально в Blender, а в движке на скруглении полосы. Почему?",
      opts: [
        "Движок не поддерживает гладкие нормали",
        "Неплоские квады и n-гоны триангулируются иначе",
        "В движке другая система координат",
        "Модель слишком тяжёлая"
      ],
      right: 1,
      why: "glTF хранит только треугольники: n-гоны триангулирует экспортёр. Разная диагональ — разная поверхность. Поэтому проблемные грани триангулируют вручную до экспорта."
    },
    {
      q: "У тебя 40 рёбер сходятся в полюс UV-сферы. Что делать?",
      opts: [
        "Оставить: сфера всё равно круглая",
        "Сварить вершины и пересчитать нормали",
        "Перестроить сферу с квадовой разводкой: кольца и полюса по кругу",
        "Добавить SubD niveau 3 и не думать"
      ],
      right: 2,
      why: "Звезда на полюсе даёт щипок и иглы. Правильная сфера — кольца с полюсами валентности 4, разнесёнными по поверхности."
    },
    {
      q: "«Иглы» — это 25 % треугольников файла. Это точно ошибка?",
      opts: [
        "Да, любая игла — дефект",
        "Нет: надо смотреть, где они — на изгибе или на плоскости",
        "Да, если файл больше 10 МБ",
        "Нет, иглы вообще не влияют на вид"
      ],
      right: 1,
      why: "Игла в плоской панели безвредна (у соседей одна нормаль), на плавном изгибе — полосы, у тонкой длинной детали — неизбежна. Поэтому аудит считает долю площади игл именно на изгибе."
    },
    {
      q: "Лучший первый шаг при «странных» нормалях и тёмных пятнах?",
      opts: [
        "Поставить материал с двумя сторонами",
        "Merge by Distance, затем Shift+N",
        "Применить Decimate",
        "Добавить SubD"
      ],
      right: 1,
      why: "Несваренные вершины не дают нормалям договориться. Сварка + пересчёт наружу решают большинство таких случаев; дальше проверяют масштаб и обход граней."
    },
    {
      q: "Автоматический ретопо (ZRemesher, QuadriFlow) даёт готовую топологию для анимации?",
      opts: [
        "Да, если выставить нужное число полигонов",
        "Да, если включить симметрию",
        "Нет: он делает базу, петли под деформацию размечает человек",
        "Да, но только для лица"
      ],
      right: 2,
      why: "Алгоритмы минимизируют число особенностей, но не знают, где будет локоть. Для статики этого достаточно, для анимации — нет."
    },
    {
      q: "Сколько петель нужно в локте обычного game-персонажа?",
      opts: ["Одна, если она по центру изгиба", "2", "4–6", "20–30"],
      right: 2,
      why: "Отраслевая практика: 3–4 для мобильного персонажа, 4–6 для обычного, 6–8 для героя крупным планом. Одна петля складывается в ноль."
    }
  ];

  // Итоги аудита living_room_diorama.glb (генерируются tools/topology_audit.py)
  const AUDIT = [
    ["Вершин / треугольников", "47 896 / 94 512", "—", ""],
    ["non-manifold рёбер", "0", "тело корректно", "ok"],
    ["граничных рёбер (дырок)", "0", "всё замкнуто", "ok"],
    ["замкнутых оболочек", "369", "327 рода 0, 35 рода 1, 7 рода 2", ""],
    ["«слитых» совпадений вершин", "24 218", "норма glTF: развод по швам нормалей и UV", ""],
    ["граней, схлопнувшихся после сварки", "96", "все у lamp_bulb: полюс UV-сферы", "warn"],
    ["висячих вершин", "1", "lamp_bulb, лечится Delete Loose", "warn"],
    ["«игл» (угол < 3°)", "23 778", "25 % граней, но лишь часть — на изгибе", ""],
    ["игл на плавном изгибе", "14 736", "10 % площади файла", "warn"],
    ["макс. разброс длин рёбер", "×30 687", "plant_pot: почти совпадающие кольца", "warn"],
    ["мин. средний dot нормалей", "0.9915", "decor_vase: нормали согласованы", "ok"]
  ];

  // --------------------------------------------------------------------------
  //  Утилиты
  // --------------------------------------------------------------------------

  const $ = (sel, root) => (root || document).querySelector(sel);
  const $$ = (sel, root) => Array.from((root || document).querySelectorAll(sel));
  const el = (tag, cls, html) => {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (html !== undefined) node.innerHTML = html;
    return node;
  };
  const store = {
    get(key, fallback) {
      try {
        const raw = localStorage.getItem(key);
        return raw === null ? fallback : JSON.parse(raw);
      } catch (e) { return fallback; }
    },
    set(key, value) {
      try { localStorage.setItem(key, JSON.stringify(value)); } catch (e) { /* приватный режим */ }
    }
  };

  // --------------------------------------------------------------------------
  //  Тема
  // --------------------------------------------------------------------------

  function initTheme() {
    const saved = store.get("topo.theme", null);
    const prefersDark = window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
    const theme = saved || (prefersDark ? "dark" : "light");
    document.documentElement.setAttribute("data-theme", theme);
    const btn = $("#themeBtn");
    if (!btn) return;
    const label = () => { btn.textContent = document.documentElement.getAttribute("data-theme") === "dark" ? "☾ Тёмная" : "☀ Светлая"; };
    label();
    btn.addEventListener("click", () => {
      const next = document.documentElement.getAttribute("data-theme") === "dark" ? "light" : "dark";
      document.documentElement.setAttribute("data-theme", next);
      store.set("topo.theme", next);
      label();
    });
  }

  // --------------------------------------------------------------------------
  //  Прогресс чтения и навигация
  // --------------------------------------------------------------------------

  function initProgress() {
    const bar = $("#progress");
    if (!bar) return;
    const update = () => {
      const h = document.documentElement;
      const max = h.scrollHeight - h.clientHeight;
      bar.style.width = (max > 0 ? (h.scrollTop / max) * 100 : 0) + "%";
    };
    document.addEventListener("scroll", update, { passive: true });
    window.addEventListener("resize", update);
    update();
  }

  function initScrollSpy() {
    const links = $$("nav.toc a[href^='#']");
    if (!links.length || !("IntersectionObserver" in window)) return;
    const map = new Map();
    links.forEach((a) => {
      const target = document.getElementById(a.getAttribute("href").slice(1));
      if (target) map.set(target, a);
    });
    const io = new IntersectionObserver((entries) => {
      entries.forEach((e) => {
        if (e.isIntersecting) {
          links.forEach((a) => a.classList.remove("active"));
          const link = map.get(e.target);
          if (link) link.classList.add("active");
        }
      });
    }, { rootMargin: "-15% 0px -70% 0px", threshold: 0 });
    map.forEach((_, target) => io.observe(target));
  }

  // --------------------------------------------------------------------------
  //  Галерея «плохо → лечение»
  // --------------------------------------------------------------------------

  function initGallery() {
    const host = $("#galleryList");
    if (!host) return;

    GALLERY.forEach((item, i) => {
      const card = el("article", "pair");
      card.id = "pair-" + item.key;

      const compare = el("div", "compare");
      compare.setAttribute("role", "slider");
      compare.setAttribute("tabindex", "0");
      compare.setAttribute("aria-label", item.title + ": слева плохо, справа лечение");
      compare.setAttribute("aria-valuemin", "0");
      compare.setAttribute("aria-valuemax", "100");
      compare.setAttribute("aria-valuenow", "50");

      const before = document.createElement("img");
      before.src = fig(item.key + "-bad.svg");
      before.alt = item.title + " — плохо";
      before.loading = i < 4 ? "eager" : "lazy";

      const afterWrap = el("div", "after");
      const after = document.createElement("img");
      after.src = fig(item.key + "-good.svg");
      after.alt = item.title + " — лечение";
      after.loading = i < 4 ? "eager" : "lazy";
      afterWrap.appendChild(after);

      const handle = el("div", "handle");
      const hint = el("div", "hint", "потяни ⇔ или ← →");

      compare.appendChild(before);
      compare.appendChild(afterWrap);
      compare.appendChild(handle);
      compare.appendChild(hint);

      const setSplit = (pct) => {
        const value = Math.max(0, Math.min(100, pct));
        afterWrap.style.clipPath = "inset(0 0 0 " + value + "%)";
        handle.style.left = value + "%";
        compare.setAttribute("aria-valuenow", String(Math.round(value)));
        compare.dataset.split = String(value);
        if (value !== 50) hint.style.opacity = "0";
      };
      setSplit(50);

      let dragging = false;
      const pointToPct = (clientX) => {
        const rect = compare.getBoundingClientRect();
        return rect.width ? ((clientX - rect.left) / rect.width) * 100 : 50;
      };
      compare.addEventListener("pointerdown", (e) => {
        dragging = true;
        if (compare.setPointerCapture) {
          try { compare.setPointerCapture(e.pointerId); } catch (err) { /* старые браузеры */ }
        }
        setSplit(pointToPct(e.clientX));
      });
      compare.addEventListener("pointermove", (e) => {
        if (dragging) setSplit(pointToPct(e.clientX));
      });
      compare.addEventListener("pointerup", () => { dragging = false; });
      compare.addEventListener("pointercancel", () => { dragging = false; });
      compare.addEventListener("dblclick", () => setSplit(50));
      compare.addEventListener("keydown", (e) => {
        const current = Number(compare.dataset.split || 50);
        if (e.key === "ArrowLeft") { setSplit(current - 5); e.preventDefault(); }
        if (e.key === "ArrowRight") { setSplit(current + 5); e.preventDefault(); }
        if (e.key === "Home") { setSplit(0); e.preventDefault(); }
        if (e.key === "End") { setSplit(100); e.preventDefault(); }
      });

      const body = el("div", "body");
      body.appendChild(el("h4", null,
        '<span class="idx">' + String(i + 1).padStart(2, "0") + '</span>' + item.title));

      const dl = el("dl");
      [["причина", item.cause], ["как найти", item.find], ["лечение", item.fix]]
        .forEach((row) => {
          dl.appendChild(el("dt", null, row[0]));
          dl.appendChild(el("dd", null, row[1]));
        });
      body.appendChild(dl);
      if (item.note) body.appendChild(el("div", "note", "<b>не всегда ошибка:</b> " + item.note));

      card.appendChild(compare);
      card.appendChild(body);
      host.appendChild(card);
    });

    const toggle = $("#revealAll");
    if (toggle) {
      toggle.addEventListener("click", () => {
        const on = toggle.getAttribute("aria-pressed") !== "true";
        toggle.setAttribute("aria-pressed", String(on));
        toggle.textContent = on ? "Скрыть лечения" : "Показать все лечения";
        $$("#galleryList .compare", host).forEach((c) => {
          const wrap = c.querySelector(".after");
          const handle = c.querySelector(".handle");
          wrap.style.clipPath = "inset(0 0 0 " + (on ? 0 : 50) + "%)";
          handle.style.left = (on ? 0 : 50) + "%";
          c.dataset.split = String(on ? 0 : 50);
          c.setAttribute("aria-valuenow", String(on ? 0 : 50));
        });
      });
    }
  }

  // --------------------------------------------------------------------------
  //  Каталог случаев
  // --------------------------------------------------------------------------

  function initCases() {
    const host = $("#casesList");
    if (!host) return;
    const chips = $("#caseChips");
    const search = $("#caseSearch");
    const empty = $("#casesEmpty");
    let category = "все";
    let query = "";

    const nodes = CASES.map((c) => {
      const d = el("details", "case");
      d.dataset.cat = c.cat;
      d.dataset.text = (c.sym + " " + c.cause + " " + c.find + " " + c.fix + " " + c.cat).toLowerCase();
      d.innerHTML =
        '<summary><span class="n">' + c.n + '</span>' +
        '<span class="sym">' + c.sym + '</span>' +
        '<span class="cat">' + c.cat + '</span></summary>' +
        '<div class="inside">' +
        '<div><b>причина</b><span>' + c.cause + '</span></div>' +
        '<div><b>как найти</b><span>' + c.find + '</span></div>' +
        '<div><b>лечение</b><span>' + c.fix + '</span></div>' +
        '</div>';
      host.appendChild(d);
      return d;
    });

    const apply = () => {
      let shown = 0;
      nodes.forEach((d) => {
        const okCat = category === "все" || d.dataset.cat === category;
        const okText = !query || d.dataset.text.indexOf(query) !== -1;
        const visible = okCat && okText;
        d.classList.toggle("hidden", !visible);
        if (visible) shown += 1;
      });
      if (empty) empty.hidden = shown !== 0;
      const counter = $("#caseCount");
      if (counter) counter.textContent = shown + " из " + CASES.length;
    };

    if (chips) {
      CATEGORIES.forEach((cat) => {
        const b = el("button", "btn ghost", cat);
        b.type = "button";
        b.setAttribute("aria-pressed", String(cat === "все"));
        b.addEventListener("click", () => {
          category = cat;
          $$("button", chips).forEach((x) => x.setAttribute("aria-pressed", "false"));
          b.setAttribute("aria-pressed", "true");
          apply();
        });
        chips.appendChild(b);
      });
    }
    if (search) {
      search.addEventListener("input", () => {
        query = search.value.trim().toLowerCase();
        apply();
      });
    }
    apply();
  }

  // --------------------------------------------------------------------------
  //  «Это не ошибка»
  // --------------------------------------------------------------------------

  function initMyths() {
    const host = $("#mythsList");
    if (!host) return;
    MYTHS.forEach((row) => {
      const card = el("div", "myth");
      card.appendChild(el("b", null, row[0]));
      card.appendChild(el("div", "why", row[1]));
      host.appendChild(card);
    });
  }

  // --------------------------------------------------------------------------
  //  Чек-листы
  // --------------------------------------------------------------------------

  function initChecklists() {
    const host = $("#checklistList");
    if (!host) return;
    const state = store.get("topo.checks", {});
    const updaters = [];

    const updateGroup = (group, nodes, bar, count) => {
      const done = nodes.filter((n) => n.checked).length;
      bar.style.width = (done / nodes.length) * 100 + "%";
      count.textContent = done + "/" + nodes.length;
      state[group.id] = nodes.map((n) => n.checked);
      store.set("topo.checks", state);
    };

    CHECKLISTS.forEach((group) => {
      const card = el("div", "checklist");
      const head = el("h4");
      head.appendChild(el("span", null, group.title));
      const count = el("span", "count", "0/0");
      head.appendChild(count);
      card.appendChild(head);
      const bar = el("div", "bar");
      const fill = el("i");
      bar.appendChild(fill);
      card.appendChild(bar);

      const saved = state[group.id] || [];
      const nodes = group.items.map((text, i) => {
        const label = document.createElement("label");
        const input = document.createElement("input");
        input.type = "checkbox";
        input.checked = Boolean(saved[i]);
        input.addEventListener("change", () => updateGroup(group, nodes, fill, count));
        label.appendChild(input);
        label.appendChild(el("span", null, text));
        card.appendChild(label);
        return input;
      });
      updateGroup(group, nodes, fill, count);
      updaters.push(() => updateGroup(group, nodes, fill, count));
      host.appendChild(card);
    });

    const reset = $("#resetChecks");
    if (reset) {
      reset.addEventListener("click", () => {
        $$("#checklistList input").forEach((i) => { i.checked = false; });
        Object.keys(state).forEach((k) => { delete state[k]; });
        store.set("topo.checks", {});
        updaters.forEach((fn) => fn());
      });
    }
  }

  // --------------------------------------------------------------------------
  //  Квиз
  // --------------------------------------------------------------------------

  function initQuiz() {
    const host = $("#quizBox");
    if (!host) return;
    let best = store.get("topo.quiz.best", null);
    let index = 0;
    let score = 0;
    let answered = false;

    const renderBest = () => {
      const node = $("#quizBest");
      if (node) node.textContent = best ? "лучший результат: " + best + " из " + QUIZ.length : "";
    };

    function render() {
      host.innerHTML = "";
      if (index >= QUIZ.length) {
        const pct = Math.round((score / QUIZ.length) * 100);
        const verdict = pct >= 90 ? "Материал освоен: можно идти править чужие сетки."
          : pct >= 70 ? "Хорошо. Перечитай разделы про плотность и иглы — там чаще всего ошибаются."
          : pct >= 40 ? "Основа есть. Пройди галерею ещё раз, отмечая «как найти» для каждой пары."
          : "Пока рано. Начни с разделов 2–3 и галереи — потом вернись к вопросам.";
        host.appendChild(el("p", "final", "Результат: " + score + " из " + QUIZ.length + " (" + pct + "%)"));
        host.appendChild(el("p", null, verdict));
        if (best === null || score > best) {
          best = score;
          store.set("topo.quiz.best", best);
        }
        const again = el("button", "btn primary", "Пройти заново");
        again.type = "button";
        again.addEventListener("click", () => { index = 0; score = 0; answered = false; render(); renderBest(); });
        const foot = el("div", "qfoot");
        foot.appendChild(again);
        const toBest = el("a", "btn ghost", "К галерее");
        toBest.href = "#gallery";
        foot.appendChild(toBest);
        host.appendChild(foot);
        renderBest();
        return;
      }

      const q = QUIZ[index];
      answered = false;
      const head = el("div", "qhead");
      head.appendChild(el("span", "qn", "вопрос " + (index + 1) + " из " + QUIZ.length));
      head.appendChild(el("span", "qn", "счёт " + score));
      host.appendChild(head);
      host.appendChild(el("p", "qtext", q.q));

      const opts = el("div", "opts");
      const buttons = q.opts.map((text, i) => {
        const b = el("button", "opt",
          '<span class="mark">' + String.fromCharCode(65 + i) + '</span><span>' + text + '</span>');
        b.type = "button";
        b.addEventListener("click", () => choose(i, buttons, q, why));
        opts.appendChild(b);
        return b;
      });
      host.appendChild(opts);

      const why = el("div", "why");
      why.hidden = true;
      host.appendChild(why);

      const foot = el("div", "qfoot");
      const next = el("button", "btn primary", "Дальше");
      next.type = "button";
      next.hidden = true;
      next.addEventListener("click", () => { index += 1; render(); });
      foot.appendChild(next);
      foot.appendChild(el("span", "score", "лучший: " + (best ? best + " из " + QUIZ.length : "—")));
      host.appendChild(foot);
    }

    function choose(picked, buttons, q, why) {
      if (answered) return;
      answered = true;
      buttons.forEach((b, i) => {
        b.disabled = true;
        if (i === q.right) b.classList.add("right");
        if (i === picked && picked !== q.right) b.classList.add("wrong");
      });
      if (picked === q.right) score += 1; else why.classList.add("bad");
      why.innerHTML = (picked === q.right ? "<b>Верно.</b> " : "<b>Не совсем.</b> ") + q.why;
      why.hidden = false;
      const next = host.querySelector(".qfoot .btn.primary");
      if (next) next.hidden = false;
      const scoreNode = host.querySelector(".qhead .qn:last-child");
      if (scoreNode) scoreNode.textContent = "счёт " + score;
    }

    render();
    renderBest();
  }

  // --------------------------------------------------------------------------
  //  Таблица аудита
  // --------------------------------------------------------------------------

  function initAudit() {
    const host = $("#auditRows");
    if (!host) return;
    AUDIT.forEach((row) => {
      const tr = document.createElement("tr");
      tr.innerHTML = "<td>" + row[0] + "</td><td class=\"num\">" + row[1] +
        "</td><td>" + row[2] + "</td>";
      if (row[3] === "ok") tr.style.color = "var(--teal)";
      if (row[3] === "warn") tr.style.color = "var(--amber)";
      host.appendChild(tr);
    });
  }

  // --------------------------------------------------------------------------

  let booted = false;
  function boot() {
    if (booted) return;          // защита от двойного запуска
    booted = true;
    initTheme();
    initProgress();
    initScrollSpy();
    initGallery();
    initCases();
    initMyths();
    initChecklists();
    initQuiz();
    initAudit();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();                      // файл открыли после разбора страницы
  }
})();

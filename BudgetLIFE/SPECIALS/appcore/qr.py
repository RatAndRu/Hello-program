"""QR-код без внешних зависимостей — «последний рубеж» для эталона.

Зачем это нужно
---------------
Все проекты показывают QR-код на адрес приложения (BLIND_PC, DnD's,
swipe_review): пользователь сканирует его телефоном и сразу открывает интерфейс.
Обычно для этого хватает пакета ``qrcode`` (он опционален, см. ``netutil``).
Но если пакета нет — приложение раньше просто отказывалось показывать QR
(``/api/qr`` отвечал 501). Этот модуль умеет то же самое **само**:

  * ``matrix()``   — матрица модулей QR (байтовый режим, уровни L/M/Q/H, версии 1-40);
  * ``svg()``      — готовый SVG-текст (крисп на любом экране, без Pillow);
  * ``png_bytes()``— PNG в 1 бит на пиксель (чистый Python + ``zlib``);
  * ``ascii()``    — QR «буквами» для лога и тестов.

Как это проверено
-----------------
Таблицы блоков коррекции и позиции выравнивающих узоров — из стандарта
ISO/IEC 18004 (это данные, а не код). Правильность кодирования проверяется в
``tools/self_test.py``: если установлен пакет ``qrcode``, матрицы сравниваются
**модуль в модуль** для всех 8 масок и всех уровней коррекции, включая выбор
лучшей маски. То есть модуль делает ровно то же, что библиотека, но не требует
её наличия.

Что модуль НЕ умеет (сознательно): микро-QR, кириллицу/японский в буквенно-
цифровом режиме и «умный» выбор компактного режима (числа/латиница кодируются
как байты — это чуть длиннее, но зато ни одна строка не кодируется неверно).
"""

from __future__ import annotations

import struct
import zlib

__all__ = ["ECC_LEVELS", "encode_matrix", "matrix", "svg", "png_bytes", "ascii_qr",
           "version_for", "data_capacity"]

# Уровни коррекции: буква → двухбитный код в формате QR (L=01, M=00, Q=11, H=10).
ECC_LEVELS = {"L": 1, "M": 0, "Q": 3, "H": 2}
_ECC_BITS_TO_LETTER = {v: k for k, v in ECC_LEVELS.items()}

# Сколько байт данных остаётся на полезную нагрузку (без ECC), версии 1-40.
# Считается из таблицы блоков ниже; здесь — для быстрого выбора версии.
_PAD_BYTES = (0xEC, 0x11)


# ── Данные из стандарта ISO/IEC 18004 ────────────────────────────────────────

# Позиции выравнивающих узоров (центры) для версий 1-40.
_ALIGN_POSITIONS = (
    (), (6, 18), (6, 22), (6, 26), (6, 30), (6, 34), (6, 22, 38), (6, 24, 42),
    (6, 26, 46), (6, 28, 50), (6, 30, 54), (6, 32, 58), (6, 34, 62),
    (6, 26, 46, 66), (6, 26, 48, 70), (6, 26, 50, 74), (6, 30, 54, 78),
    (6, 30, 56, 82), (6, 30, 58, 86), (6, 34, 62, 90), (6, 28, 50, 72, 94),
    (6, 26, 50, 74, 98), (6, 30, 54, 78, 102), (6, 28, 54, 80, 106),
    (6, 32, 58, 84, 110), (6, 30, 58, 86, 114), (6, 34, 62, 90, 118),
    (6, 26, 50, 74, 98, 122), (6, 30, 54, 78, 102, 126),
    (6, 26, 52, 78, 104, 130), (6, 30, 56, 82, 108, 134),
    (6, 34, 60, 86, 112, 138), (6, 30, 58, 86, 114, 142),
    (6, 34, 62, 90, 118, 146), (6, 30, 54, 78, 102, 126, 150),
    (6, 24, 50, 76, 102, 128, 154), (6, 28, 54, 80, 106, 132, 158),
    (6, 32, 58, 84, 110, 136, 162), (6, 26, 54, 82, 110, 138, 166),
    (6, 30, 58, 86, 114, 142, 170),
)

# Блоки коррекции ошибок: _RS_BLOCKS[версия-1] = (запись L, запись M, запись Q, запись H).
# Формат записи: (кол-во блоков, всего кодовых слов, кодовых слов данных) или
# пары групп: (кол-во1, всего1, данных1, кол-во2, всего2, данных2) —
# из «всего − данных» получается длина ECC для каждого блока.
# fmt: off
_RS_BLOCKS = (
    ((1, 26, 19), (1, 26, 16), (1, 26, 13), (1, 26, 9)),  # 1
    ((1, 44, 34), (1, 44, 28), (1, 44, 22), (1, 44, 16)),  # 2
    ((1, 70, 55), (1, 70, 44), (2, 35, 17), (2, 35, 13)),  # 3
    ((1, 100, 80), (2, 50, 32), (2, 50, 24), (4, 25, 9)),  # 4
    ((1, 134, 108), (2, 67, 43), (2, 33, 15, 2, 34, 16), (2, 33, 11, 2, 34, 12)),  # 5
    ((2, 86, 68), (4, 43, 27), (4, 43, 19), (4, 43, 15)),  # 6
    ((2, 98, 78), (4, 49, 31), (2, 32, 14, 4, 33, 15), (4, 39, 13, 1, 40, 14)),  # 7
    ((2, 121, 97), (2, 60, 38, 2, 61, 39), (4, 40, 18, 2, 41, 19), (4, 40, 14, 2, 41, 15)),  # 8
    ((2, 146, 116), (3, 58, 36, 2, 59, 37), (4, 36, 16, 4, 37, 17), (4, 36, 12, 4, 37, 13)),  # 9
    ((2, 86, 68, 2, 87, 69), (4, 69, 43, 1, 70, 44), (6, 43, 19, 2, 44, 20), (6, 43, 15, 2, 44, 16)),  # 10
    ((4, 101, 81), (1, 80, 50, 4, 81, 51), (4, 50, 22, 4, 51, 23), (3, 36, 12, 8, 37, 13)),  # 11
    ((2, 116, 92, 2, 117, 93), (6, 58, 36, 2, 59, 37), (4, 46, 20, 6, 47, 21), (7, 42, 14, 4, 43, 15)),  # 12
    ((4, 133, 107), (8, 59, 37, 1, 60, 38), (8, 44, 20, 4, 45, 21), (12, 33, 11, 4, 34, 12)),  # 13
    ((3, 145, 115, 1, 146, 116), (4, 64, 40, 5, 65, 41), (11, 36, 16, 5, 37, 17), (11, 36, 12, 5, 37, 13)),  # 14
    ((5, 109, 87, 1, 110, 88), (5, 65, 41, 5, 66, 42), (5, 54, 24, 7, 55, 25), (11, 36, 12, 7, 37, 13)),  # 15
    ((5, 122, 98, 1, 123, 99), (7, 73, 45, 3, 74, 46), (15, 43, 19, 2, 44, 20), (3, 45, 15, 13, 46, 16)),  # 16
    ((1, 135, 107, 5, 136, 108), (10, 74, 46, 1, 75, 47), (1, 50, 22, 15, 51, 23), (2, 42, 14, 17, 43, 15)),  # 17
    ((5, 150, 120, 1, 151, 121), (9, 69, 43, 4, 70, 44), (17, 50, 22, 1, 51, 23), (2, 42, 14, 19, 43, 15)),  # 18
    ((3, 141, 113, 4, 142, 114), (3, 70, 44, 11, 71, 45), (17, 47, 21, 4, 48, 22), (9, 39, 13, 16, 40, 14)),  # 19
    ((3, 135, 107, 5, 136, 108), (3, 67, 41, 13, 68, 42), (15, 54, 24, 5, 55, 25), (15, 43, 15, 10, 44, 16)),  # 20
    ((4, 144, 116, 4, 145, 117), (17, 68, 42), (17, 50, 22, 6, 51, 23), (19, 46, 16, 6, 47, 17)),  # 21
    ((2, 139, 111, 7, 140, 112), (17, 74, 46), (7, 54, 24, 16, 55, 25), (34, 37, 13)),  # 22
    ((4, 151, 121, 5, 152, 122), (4, 75, 47, 14, 76, 48), (11, 54, 24, 14, 55, 25), (16, 45, 15, 14, 46, 16)),  # 23
    ((6, 147, 117, 4, 148, 118), (6, 73, 45, 14, 74, 46), (11, 54, 24, 16, 55, 25), (30, 46, 16, 2, 47, 17)),  # 24
    ((8, 132, 106, 4, 133, 107), (8, 75, 47, 13, 76, 48), (7, 54, 24, 22, 55, 25), (22, 45, 15, 13, 46, 16)),  # 25
    ((10, 142, 114, 2, 143, 115), (19, 74, 46, 4, 75, 47), (28, 50, 22, 6, 51, 23), (33, 46, 16, 4, 47, 17)),  # 26
    ((8, 152, 122, 4, 153, 123), (22, 73, 45, 3, 74, 46), (8, 53, 23, 26, 54, 24), (12, 45, 15, 28, 46, 16)),  # 27
    ((3, 147, 117, 10, 148, 118), (3, 73, 45, 23, 74, 46), (4, 54, 24, 31, 55, 25), (11, 45, 15, 31, 46, 16)),  # 28
    ((7, 146, 116, 7, 147, 117), (21, 73, 45, 7, 74, 46), (1, 53, 23, 37, 54, 24), (19, 45, 15, 26, 46, 16)),  # 29
    ((5, 145, 115, 10, 146, 116), (19, 75, 47, 10, 76, 48), (15, 54, 24, 25, 55, 25), (23, 45, 15, 25, 46, 16)),  # 30
    ((13, 145, 115, 3, 146, 116), (2, 74, 46, 29, 75, 47), (42, 54, 24, 1, 55, 25), (23, 45, 15, 28, 46, 16)),  # 31
    ((17, 145, 115), (10, 74, 46, 23, 75, 47), (10, 54, 24, 35, 55, 25), (19, 45, 15, 35, 46, 16)),  # 32
    ((17, 145, 115, 1, 146, 116), (14, 74, 46, 21, 75, 47), (29, 54, 24, 19, 55, 25), (11, 45, 15, 46, 46, 16)),  # 33
    ((13, 145, 115, 6, 146, 116), (14, 74, 46, 23, 75, 47), (44, 54, 24, 7, 55, 25), (59, 46, 16, 1, 47, 17)),  # 34
    ((12, 151, 121, 7, 152, 122), (12, 75, 47, 26, 76, 48), (39, 54, 24, 14, 55, 25), (22, 45, 15, 41, 46, 16)),  # 35
    ((6, 151, 121, 14, 152, 122), (6, 75, 47, 34, 76, 48), (46, 54, 24, 10, 55, 25), (2, 45, 15, 64, 46, 16)),  # 36
    ((17, 152, 122, 4, 153, 123), (29, 74, 46, 14, 75, 47), (49, 54, 24, 10, 55, 25), (24, 45, 15, 46, 46, 16)),  # 37
    ((4, 152, 122, 18, 153, 123), (13, 74, 46, 32, 75, 47), (48, 54, 24, 14, 55, 25), (42, 45, 15, 32, 46, 16)),  # 38
    ((20, 147, 117, 4, 148, 118), (40, 75, 47, 7, 76, 48), (43, 54, 24, 22, 55, 25), (10, 45, 15, 67, 46, 16)),  # 39
    ((19, 148, 118, 6, 149, 119), (18, 75, 47, 31, 76, 48), (34, 54, 24, 34, 55, 25), (20, 45, 15, 61, 46, 16)),  # 40
)
# fmt: on

# ── Матрица ──────────────────────────────────────────────────────────────────


def _blocks(version: int, ecc: str) -> list[tuple[int, int, int]]:
    """Список блоков (кол-во, кодовых слов данных, кодовых слов ECC)."""
    if ecc not in ECC_LEVELS:
        raise ValueError("Уровень коррекции должен быть L, M, Q или H")
    raw = _RS_BLOCKS[version - 1][("L", "M", "Q", "H").index(ecc)]
    if len(raw) == 3:
        groups = (raw,)
    else:
        groups = (raw[0:3], raw[3:6])
    out: list[tuple[int, int, int]] = []
    for count, total, data in groups:
        out.append((count, data, total - data))
    return out


def data_capacity(version: int, ecc: str = "M") -> int:
    """Сколько байт полезных данных влезает в версию (в байтовом режиме)."""
    return sum(count * data for count, data, _ in _blocks(version, ecc))


def version_for(text: str | bytes, ecc: str = "M") -> int:
    """Наименьшая версия QR, вмещающая текст (или ValueError, если не влезает)."""
    data = text.encode("utf-8") if isinstance(text, str) else bytes(text)
    for version in range(1, 41):
        bits = 4 + (8 if version <= 9 else 16) + 8 * len(data)
        if bits <= data_capacity(version, ecc) * 8:
            return version
    raise ValueError("Слишком длинный текст для QR-кода (нужно больше 40 версий)")


class _Bits:
    """Простой буфер битов (пишем «как читает» QR — старший бит вперёд)."""

    __slots__ = ("bits",)

    def __init__(self) -> None:
        self.bits: list[int] = []

    def put(self, value: int, length: int) -> None:
        for shift in range(length - 1, -1, -1):
            self.bits.append((value >> shift) & 1)

    def __len__(self) -> int:
        return len(self.bits)


def _data_codewords(text: str | bytes, version: int, ecc: str) -> list[int]:
    """Кодирует текст в кодовые слова данных (с терминатором и заполнением)."""
    data = text.encode("utf-8") if isinstance(text, str) else bytes(text)
    bits = _Bits()
    bits.put(0b0100, 4)                      # режим «байты»
    bits.put(len(data), 8 if version <= 9 else 16)
    for byte in data:
        bits.put(byte, 8)
    capacity = data_capacity(version, ecc) * 8
    for _ in range(min(4, capacity - len(bits))):   # терминатор
        bits.put(0, 1)
    while len(bits) % 8:
        bits.put(0, 1)
    words: list[int] = []
    for i in range(0, len(bits), 8):
        byte = 0
        for bit in bits.bits[i:i + 8]:
            byte = (byte << 1) | bit
        words.append(byte)
    for i in range(capacity // 8 - len(words)):
        words.append(_PAD_BYTES[i % 2])
    return words


# ── Код Рида — Соломона (поле GF(256), многочлен 0x11D) ──────────────────────

_EXP = [0] * 512
_LOG = [0] * 256
_x = 1
for _i in range(255):
    _EXP[_i] = _x
    _LOG[_x] = _i
    _x <<= 1
    if _x & 0x100:
        _x ^= 0x11D
for _i in range(255, 512):
    _EXP[_i] = _EXP[_i - 255]


def _rs_generator(degree: int) -> list[int]:
    """Порождающий многочлен (1 + x·α⁰)(1 + x·α¹)… — как в стандарте."""
    poly = [1]
    for i in range(degree):
        factor = _EXP[i]
        new = [0] * (len(poly) + 1)
        for j, coef in enumerate(poly):
            new[j] ^= coef                      # умножение на x
            if coef:
                new[j + 1] ^= _EXP[_LOG[coef] + _LOG[factor]]
        poly = new
    return poly


def _rs_remainder(data: list[int], degree: int, generator: list[int]) -> list[int]:
    """Остаток от деления данных на порождающий многочлен — это ECC."""
    remainder = [0] * degree
    for byte in data:
        factor = byte ^ remainder[0]
        remainder = remainder[1:] + [0]
        if factor:
            log_factor = _LOG[factor]
            for i, coef in enumerate(generator[1:]):
                if coef:
                    remainder[i] ^= _EXP[_LOG[coef] + log_factor]
    return remainder


def _interleave(words: list[int], version: int, ecc: str) -> list[int]:
    """Раскладывает данные по блокам, считает ECC и перемежает блоки."""
    blocks = _blocks(version, ecc)
    ecc_len = blocks[0][2]
    generator = _rs_generator(ecc_len)
    data_blocks: list[list[int]] = []
    ecc_blocks: list[list[int]] = []
    offset = 0
    for count, data_len, _ in blocks:
        for _ in range(count):
            chunk = words[offset:offset + data_len]
            offset += data_len
            data_blocks.append(chunk)
            ecc_blocks.append(_rs_remainder(chunk, ecc_len, generator))
    out: list[int] = []
    for i in range(max(len(b) for b in data_blocks)):
        for block in data_blocks:
            if i < len(block):
                out.append(block[i])
    for i in range(ecc_len):
        for block in ecc_blocks:
            out.append(block[i])
    return out


# ── Раскладка модулей ────────────────────────────────────────────────────────


def _mask_bit(mask: int, row: int, col: int) -> bool:
    """Условие маски: True — модуль инвертируется."""
    if mask == 0:
        return (row + col) % 2 == 0
    if mask == 1:
        return row % 2 == 0
    if mask == 2:
        return col % 3 == 0
    if mask == 3:
        return (row + col) % 3 == 0
    if mask == 4:
        return (row // 2 + col // 3) % 2 == 0
    if mask == 5:
        return (row * col) % 2 + (row * col) % 3 == 0
    if mask == 6:
        return ((row * col) % 2 + (row * col) % 3) % 2 == 0
    return ((row + col) % 2 + (row * col) % 3) % 2 == 0


def _format_bits(ecc: str, mask: int) -> int:
    """15-битная строка формата: код коррекции + маска + BCH + фиксированная маска."""
    data = (ECC_LEVELS[ecc] << 3) | mask
    remainder = data
    for _ in range(10):
        remainder = (remainder << 1) ^ ((remainder >> 9) * 0x537)
    return ((data << 10) | remainder) ^ 0x5412


def _version_bits(version: int) -> int:
    """18-битная строка версии (только для версий 7+)."""
    remainder = version
    for _ in range(12):
        remainder = (remainder << 1) ^ ((remainder >> 11) * 0x1F25)
    return (version << 12) | remainder


def _empty_matrix(version: int) -> tuple[list[list[bool]], list[list[bool]]]:
    """Возвращает (модули, «служебный модуль?») пустой матрицы с узорами."""
    size = version * 4 + 17
    modules = [[False] * size for _ in range(size)]
    reserved = [[False] * size for _ in range(size)]

    def set_module(col: int, row: int, dark: bool) -> None:
        if 0 <= col < size and 0 <= row < size:
            modules[row][col] = dark
            reserved[row][col] = True

    def finder(cx: int, cy: int) -> None:
        for dy in range(-4, 5):
            for dx in range(-4, 5):
                dist = max(abs(dx), abs(dy))
                set_module(cx + dx, cy + dy, dist != 2 and dist != 4)

    # Порядок важен: синхронизирующие полосы рисуются первыми, поисковые узоры
    # и выравнивающие квадраты их перекрывают — ровно как в стандарте.
    for i in range(size):                       # синхронизирующие полосы
        set_module(6, i, i % 2 == 0)
        set_module(i, 6, i % 2 == 0)

    finder(3, 3)
    finder(size - 4, 3)
    finder(3, size - 4)

    positions = _ALIGN_POSITIONS[version - 1]
    last = len(positions) - 1
    for iy, cy in enumerate(positions):
        for ix, cx in enumerate(positions):
            if (iy, ix) in {(0, 0), (0, last), (last, 0)}:
                continue                        # три угла заняты поисковыми узорами
            for dy in range(-2, 3):
                for dx in range(-2, 3):
                    set_module(cx + dx, cy + dy, max(abs(dx), abs(dy)) != 1)

    marks = set()
    for i in range(9):                          # место под формат (уголок)
        if i == 6:                              # (6,8) и (8,6) — синхронизирующие модули
            continue
        marks.add((8, i))
        marks.add((i, 8))
    for i in range(8):                          # …и вторая копия
        marks.add((size - 1 - i, 8))
        marks.add((8, size - 1 - i))
    for col, row in marks:
        set_module(col, row, False)
    set_module(8, size - 8, True)               # тёмный модуль

    if version >= 7:                            # строка версии
        for i in range(18):
            bit = (_version_bits(version) >> i) & 1 == 1
            a = size - 11 + i % 3
            b = i // 3
            set_module(a, b, bit)
            set_module(b, a, bit)
    return modules, reserved


def _place_data(modules: list[list[bool]], reserved: list[list[bool]],
                codewords: list[int]) -> None:
    """Укладывает биты данных «змейкой» (справа-налево, вверх-вниз)."""
    size = len(modules)
    total = len(codewords) * 8
    index = 0
    right = size - 1
    while right >= 1:
        if right == 6:                          # столбец 6 занят синхронизирующей полосой
            right = 5
        for vert in range(size):
            for j in range(2):
                col = right - j
                upward = (right + 1) & 2 == 0
                row = size - 1 - vert if upward else vert
                if not reserved[row][col] and index < total:
                    bit = (codewords[index >> 3] >> (7 - (index & 7))) & 1
                    modules[row][col] = bit == 1
                    index += 1
        right -= 2


def _draw_format(modules: list[list[bool]], ecc: str, mask: int) -> None:
    """Рисует обе копии строки формата (после выбора маски)."""
    size = len(modules)
    bits = _format_bits(ecc, mask)

    def bit(i: int) -> bool:
        return (bits >> i) & 1 == 1

    for i in range(6):                          # первая копия, вниз по столбцу 8
        modules[i][8] = bit(i)
    modules[7][8] = bit(6)
    modules[8][8] = bit(7)
    modules[8][7] = bit(8)
    for i in range(9, 15):                      # …и влево по строке 8
        modules[8][14 - i] = bit(i)
    for i in range(8):                          # вторая копия, строка 8 справа
        modules[8][size - 1 - i] = bit(i)
    for i in range(8, 15):                      # …и столбец 8 снизу
        modules[size - 15 + i][8] = bit(i)
    modules[size - 8][8] = True                 # тёмный модуль


# Узор «1:1:3:1:1», за которым (или перед которым) идут четыре светлых модуля.
# Это правило 3 стандарта: 40 штрафных очков за каждое вхождение.
_PENALTY_PATTERN_1 = [True, False, True, True, True, False, True,
                      False, False, False, False]
_PENALTY_PATTERN_2 = [False, False, False, False, True, False, True,
                      True, True, False, True]


def _penalty(modules: list[list[bool]]) -> int:
    """Штраф за маску по четырём правилам стандарта (чем меньше, тем лучше)."""
    size = len(modules)
    score = 0

    for line in list(modules) + [list(col) for col in zip(*modules)]:
        run = 1
        for i in range(1, size):
            if line[i] == line[i - 1]:
                run += 1
                if run == 5:
                    score += 3
                elif run > 5:
                    score += 1
            else:
                run = 1
        for i in range(size - 10):              # 1:1:3:1:1 + четыре светлых
            window = line[i:i + 11]
            if window == _PENALTY_PATTERN_1 or window == _PENALTY_PATTERN_2:
                score += 40

    for row in range(size - 1):                 # блоки 2×2 одного цвета
        for col in range(size - 1):
            if modules[row][col] == modules[row][col + 1] == \
                    modules[row + 1][col] == modules[row + 1][col + 1]:
                score += 3

    dark = sum(sum(1 for cell in row if cell) for row in modules)
    percent = dark * 100.0 / (size * size)
    score += int(abs(percent - 50) / 5) * 10
    return score


def encode_matrix(text: str | bytes, ecc: str = "M", version: int | None = None,
                  mask: int | None = None) -> list[list[bool]]:
    """Матрица QR (True — тёмный модуль). Без «полей» вокруг кода.

    * ``version`` — если None, подбирается минимально подходящая;
    * ``mask`` — если None, выбирается лучшая по штрафу (как требует стандарт).
    """
    if version is None:
        version = version_for(text, ecc)
    if not 1 <= version <= 40:
        raise ValueError("Версия QR должна быть от 1 до 40")
    words = _data_codewords(text, version, ecc)
    codewords = _interleave(words, version, ecc)

    best: tuple[int, list[list[bool]]] | None = None
    for candidate in range(8) if mask is None else (mask,):
        modules, reserved = _empty_matrix(version)
        _place_data(modules, reserved, codewords)
        for row in range(len(modules)):          # маска — только на данные
            for col in range(len(modules)):
                if not reserved[row][col] and _mask_bit(candidate, row, col):
                    modules[row][col] = not modules[row][col]
        _draw_format(modules, ecc, candidate)
        if mask is not None:
            return modules
        score = _penalty(modules)
        if best is None or score < best[0]:
            best = (score, modules)
    assert best is not None
    return best[1]


def matrix(text: str | bytes, ecc: str = "M", version: int | None = None,
           border: int = 4, mask: int | None = None) -> list[list[bool]]:
    """Матрица QR с «полями» (border) — в таком виде её и рисуют сканеры."""
    core = encode_matrix(text, ecc=ecc, version=version, mask=mask)
    if border <= 0:
        return core
    size = len(core) + border * 2
    out = [[False] * size for _ in range(size)]
    for row, line in enumerate(core):
        for col, cell in enumerate(line):
            out[row + border][col + border] = cell
    return out


# ── Картинки ─────────────────────────────────────────────────────────────────


def svg(text: str | bytes, ecc: str = "M", *, box: int = 8, border: int = 4,
        dark: str = "#000000", light: str = "#ffffff",
        title: str | None = None) -> str:
    """SVG с QR-кодом: масштабируется без потерь, весит мало, без Pillow."""
    cells = matrix(text, ecc=ecc, border=border)
    size = len(cells)
    parts: list[str] = []
    for row, line in enumerate(cells):
        col = 0
        while col < size:                        # склеиваем светлые/тёмные ряды
            if not line[col]:
                col += 1
                continue
            start = col
            while col < size and line[col]:
                col += 1
            parts.append(f"M{start * box} {row * box}h{(col - start) * box}v{box}h-{(col - start) * box}z")
    pixel = size * box
    caption = f"<title>{_escape(title)}</title>" if title else ""
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{pixel}" height="{pixel}" '
        f'viewBox="0 0 {pixel} {pixel}" shape-rendering="crispEdges">{caption}'
        f'<rect width="{pixel}" height="{pixel}" fill="{light}"/>'
        f'<path d="{"".join(parts)}" fill="{dark}"/></svg>'
    )


def _escape(text: str) -> str:
    return (text.replace("&", "&amp;").replace("<", "&lt;")
                .replace(">", "&gt;").replace('"', "&quot;"))


def _png_chunk(tag: bytes, payload: bytes) -> bytes:
    return (struct.pack(">I", len(payload)) + tag + payload
            + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF))


def png_bytes(text: str | bytes, ecc: str = "M", *, box: int = 8, border: int = 4,
              dark: tuple[int, int, int] = (0, 0, 0),
              light: tuple[int, int, int] = (255, 255, 255)) -> bytes:
    """PNG с QR-кодом: 1 бит на точку, пишет сам Python (``zlib`` + ``struct``).

    Приём из bridge/BLIND_PC: QR должен появиться, даже если Pillow нет.
    """
    cells = matrix(text, ecc=ecc, border=border)
    size = len(cells)
    width = height = size * box
    rows: list[bytes] = []
    for row in range(height):
        line = cells[row // box]
        bits = bytearray()
        byte = 0
        count = 0
        for col in range(width):
            byte = (byte << 1) | (0 if line[col // box] else 1)   # 0 — чёрный
            count += 1
            if count == 8:
                bits.append(byte)
                byte = 0
                count = 0
        if count:
            bits.append(byte << (8 - count))
        rows.append(b"\x00" + bytes(bits))       # фильтр строки «нет»
    ihdr = struct.pack(">IIBBBBB", width, height, 1, 0, 0, 0, 0)
    body = (_png_chunk(b"IHDR", ihdr)
            + _png_chunk(b"IDAT", zlib.compress(b"".join(rows), 9))
            + _png_chunk(b"IEND", b""))
    return b"\x89PNG\r\n\x1a\n" + body


def ascii_qr(text: str | bytes, ecc: str = "M", border: int = 2) -> str:
    """QR «буквами» — для лога, консоли и тестов."""
    blocks = "██"
    rows = []
    for line in matrix(text, ecc=ecc, border=border):
        rows.append("".join(blocks if cell else "  " for cell in line))
    return "\n".join(rows)

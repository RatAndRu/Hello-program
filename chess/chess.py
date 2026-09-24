#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
==========================================================================================
 ШАХМАТЫ НА PYTHON  ♞   (одним файлом, без сторонних библиотек)
==========================================================================================

Что умеет:
  * Полные правила шахмат: рокировка, взятие на проходе, превращение пешки,
    шах, мат, пат, правило 50 ходов, троекратное повторение позиции.
  * Компьютерный соперник (минимакс с альфа-бета отсечением, оценка позиции,
    сортировка ходов, поиск взятий в «спокойных» позициях).
  * 5 уровней сложности — от «Новичка» до «Мастера».
  * Два интерфейса:
      - графический (окно tkinter)  ->  python chess.py            (или --gui)
      - консольный (если tkinter нет) -> python chess.py --console  (или --cli)
  * Подсказка, отмена хода, смена уровня, выбор цвета.

Запуск на Windows: двойной клик по  start.vbs  в корне репозитория.

Автор-код: учебный пример для репозитория Hello-program / New program.
==========================================================================================
"""

from __future__ import annotations

import os
import random
import sys
import time
from typing import Dict, List, Optional, Tuple

# ------------------------------------------------------------------------------------
#  БАЗОВЫЕ КОНСТАНТЫ
# ------------------------------------------------------------------------------------

WHITE, BLACK = "w", "b"
FILES = "abcdefgh"
START_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"

# Названия фигур для человека (русский язык)
PIECE_NAMES_RU = {
    "P": "пешка", "N": "конь", "B": "слон", "R": "ладья", "Q": "ферзь", "K": "король",
    "p": "пешка", "n": "конь", "b": "слон", "r": "ладья", "q": "ферзь", "k": "король",
}

# Юникод-символы фигур (красиво рисуются в консоли и в окне)
UNICODE_PIECES = {
    "P": "\u2659", "N": "\u2658", "B": "\u2657", "R": "\u2656", "Q": "\u2655", "K": "\u2654",
    "p": "\u265F", "n": "\u265E", "b": "\u265D", "r": "\u265C", "q": "\u265B", "k": "\u265A",
}

# Английские буквы (для FEN / нотации) — белые заглавные, чёрные строчные
KNIGHT_DELTAS = [(-2, -1), (-2, 1), (-1, -2), (-1, 2), (1, -2), (1, 2), (2, -1), (2, 1)]
BISHOP_DIRS = [(-1, -1), (-1, 1), (1, -1), (1, 1)]
ROOK_DIRS = [(-1, 0), (1, 0), (0, -1), (0, 1)]
KING_DIRS = BISHOP_DIRS + ROOK_DIRS

# Оценка материала (в «сантипешках»)
PIECE_VALUE = {"P": 100, "N": 320, "B": 330, "R": 500, "Q": 900, "K": 20000}

# Таблицы «полезности поля» (piece-square tables) — составлены с точки зрения БЕЛЫХ,
# первый ряд таблицы = 8-я горизонталь (a8..h8), что совпадает с внутренним порядком.
PST: Dict[str, List[int]] = {
    "P": [
         0,  0,  0,  0,  0,  0,  0,  0,
        50, 50, 50, 50, 50, 50, 50, 50,
        10, 10, 20, 30, 30, 20, 10, 10,
         5,  5, 10, 25, 25, 10,  5,  5,
         0,  0,  0, 20, 20,  0,  0,  0,
         5, -5,-10,  0,  0,-10, -5,  5,
         5, 10, 10,-20,-20, 10, 10,  5,
         0,  0,  0,  0,  0,  0,  0,  0,
    ],
    "N": [
       -50,-40,-30,-30,-30,-30,-40,-50,
       -40,-20,  0,  0,  0,  0,-20,-40,
       -30,  0, 10, 15, 15, 10,  0,-30,
       -30,  5, 15, 20, 20, 15,  5,-30,
       -30,  0, 15, 20, 20, 15,  0,-30,
       -30,  5, 10, 15, 15, 10,  5,-30,
       -40,-20,  0,  5,  5,  0,-20,-40,
       -50,-40,-30,-30,-30,-30,-40,-50,
    ],
    "B": [
       -20,-10,-10,-10,-10,-10,-10,-20,
       -10,  0,  0,  0,  0,  0,  0,-10,
       -10,  0,  5, 10, 10,  5,  0,-10,
       -10,  5,  5, 10, 10,  5,  5,-10,
       -10,  0, 10, 10, 10, 10,  0,-10,
       -10, 10, 10, 10, 10, 10, 10,-10,
       -10,  5,  0,  0,  0,  0,  5,-10,
       -20,-10,-10,-10,-10,-10,-10,-20,
    ],
    "R": [
         0,  0,  0,  0,  0,  0,  0,  0,
         5, 10, 10, 10, 10, 10, 10,  5,
        -5,  0,  0,  0,  0,  0,  0, -5,
        -5,  0,  0,  0,  0,  0,  0, -5,
        -5,  0,  0,  0,  0,  0,  0, -5,
        -5,  0,  0,  0,  0,  0,  0, -5,
        -5,  0,  0,  0,  0,  0,  0, -5,
         0,  0,  0,  5,  5,  0,  0,  0,
    ],
    "Q": [
       -20,-10,-10, -5, -5,-10,-10,-20,
       -10,  0,  0,  0,  0,  0,  0,-10,
       -10,  0,  5,  5,  5,  5,  0,-10,
        -5,  0,  5,  5,  5,  5,  0, -5,
         0,  0,  5,  5,  5,  5,  0, -5,
       -10,  5,  5,  5,  5,  5,  0,-10,
       -10,  0,  5,  0,  0,  0,  0,-10,
       -20,-10,-10, -5, -5,-10,-10,-20,
    ],
    "K": [
       -30,-40,-40,-50,-50,-40,-40,-30,
       -30,-40,-40,-50,-50,-40,-40,-30,
       -30,-40,-40,-50,-50,-40,-40,-30,
       -30,-40,-40,-50,-50,-40,-40,-30,
       -20,-30,-30,-40,-40,-30,-30,-20,
       -10,-20,-20,-20,-20,-20,-20,-10,
        20, 20,  0,  0,  0,  0, 20, 20,
        20, 30, 10,  0,  0, 10, 30, 20,
    ],
}


# ------------------------------------------------------------------------------------
#  ПРЕОБРАЗОВАНИЯ ПОЛЕЙ
# ------------------------------------------------------------------------------------
#  Внутренняя нумерация: индекс 0 = a8, индекс 7 = h8, индекс 56 = a1, индекс 63 = h1.
#  Такая нумерация совпадает с порядком чтения FEN и с порядком строк PST.

def square_to_index(s: str) -> int:
    """'e4' -> индекс поля."""
    s = s.strip().lower()
    f = FILES.index(s[0])
    r = int(s[1])
    return (8 - r) * 8 + f


def index_to_square(i: int) -> str:
    """Индекс поля -> 'e4'."""
    r, f = divmod(i, 8)
    return FILES[f] + str(8 - r)


def color_of(piece: str) -> str:
    return WHITE if piece.isupper() else BLACK


def enemy(color: str) -> str:
    return BLACK if color == WHITE else WHITE


# ------------------------------------------------------------------------------------
#  ХОД
# ------------------------------------------------------------------------------------

class Move:
    """Один ход: откуда, куда, превращение и тип (обычный / рокировка / взятие на проходе)."""

    __slots__ = ("frm", "to", "promo", "flag")

    def __init__(self, frm: int, to: int, promo: str = "", flag: str = ""):
        self.frm = frm
        self.to = to
        self.promo = promo
        self.flag = flag  # '', 'double', 'ep', 'castle', 'promo'

    def uci(self) -> str:
        return index_to_square(self.frm) + index_to_square(self.to) + (self.promo.lower() if self.promo else "")

    def __repr__(self) -> str:
        return f"Move({self.uci()})"

    def __eq__(self, other) -> bool:
        return isinstance(other, Move) and self.uci() == other.uci()

    def __hash__(self) -> int:
        return hash(self.uci())


# ------------------------------------------------------------------------------------
#  ДОСКА
# ------------------------------------------------------------------------------------

class Board:
    """Шахматная доска + состояние партии."""

    def __init__(self, fen: str = START_FEN):
        self.squares: List[str] = ["."] * 64
        self.turn = WHITE
        self.castling = "KQkq"
        self.ep = -1              # поле для взятия на проходе (индекс) или -1
        self.halfmove = 0         # счётчик для правила 50 ходов
        self.fullmove = 1
        self.history: List[Tuple[Move, dict]] = []
        self.repetition: Dict[str, int] = {}
        self.set_fen(fen)
        self.repetition[self.position_key()] = 1

    # ---------------- FEN ----------------

    def set_fen(self, fen: str) -> None:
        parts = fen.split()
        rows = parts[0].split("/")
        self.squares = ["."] * 64
        for r, row in enumerate(rows):
            f = 0
            for ch in row:
                if ch.isdigit():
                    f += int(ch)
                else:
                    self.squares[r * 8 + f] = ch
                    f += 1
        self.turn = parts[1] if len(parts) > 1 else WHITE
        self.castling = parts[2] if len(parts) > 2 and parts[2] != "-" else ""
        self.ep = square_to_index(parts[3]) if len(parts) > 3 and parts[3] != "-" else -1
        self.halfmove = int(parts[4]) if len(parts) > 4 else 0
        self.fullmove = int(parts[5]) if len(parts) > 5 else 1
        self.history = []
        self.repetition = {self.position_key(): 1}

    def fen(self) -> str:
        rows = []
        for r in range(8):
            empty = 0
            row = ""
            for f in range(8):
                p = self.squares[r * 8 + f]
                if p == ".":
                    empty += 1
                else:
                    if empty:
                        row += str(empty)
                        empty = 0
                    row += p
            if empty:
                row += str(empty)
            rows.append(row)
        cast = self.castling if self.castling else "-"
        ep = index_to_square(self.ep) if self.ep >= 0 else "-"
        return f"{'/'.join(rows)} {self.turn} {cast} {ep} {self.halfmove} {self.fullmove}"

    def position_key(self) -> str:
        """Ключ позиции для проверки троекратного повторения (без счётчиков ходов)."""
        return self.fen().rsplit(" ", 2)[0]

    def copy(self) -> "Board":
        b = Board.__new__(Board)
        b.squares = self.squares[:]
        b.turn = self.turn
        b.castling = self.castling
        b.ep = self.ep
        b.halfmove = self.halfmove
        b.fullmove = self.fullmove
        b.history = []
        b.repetition = {}
        return b

    # ---------------- ДОСТУП ----------------

    def piece_at(self, i: int) -> str:
        return self.squares[i]

    def king_index(self, color: str) -> int:
        king = "K" if color == WHITE else "k"
        try:
            return self.squares.index(king)
        except ValueError:
            return -1

    def is_attacked(self, index: int, by_color: str) -> bool:
        """Атаковано ли поле index фигурами цвета by_color?"""
        r, f = divmod(index, 8)

        # Пешки: белые атакуют «вверх» (в сторону меньших индексов), поэтому смотрим
        # на пешки, которые находятся по диагонали снизу-слева/снизу-справа от поля.
        pawn = "P" if by_color == WHITE else "p"
        pawn_dir = 1 if by_color == WHITE else -1  # откуда прилетает удар по r
        for df in (-1, 1):
            rr, ff = r + pawn_dir, f + df
            if 0 <= rr < 8 and 0 <= ff < 8 and self.squares[rr * 8 + ff] == pawn:
                return True

        # Кони
        knight = "N" if by_color == WHITE else "n"
        for dr, df in KNIGHT_DELTAS:
            rr, ff = r + dr, f + df
            if 0 <= rr < 8 and 0 <= ff < 8 and self.squares[rr * 8 + ff] == knight:
                return True

        # Король
        king = "K" if by_color == WHITE else "k"
        for dr, df in KING_DIRS:
            rr, ff = r + dr, f + df
            if 0 <= rr < 8 and 0 <= ff < 8 and self.squares[rr * 8 + ff] == king:
                return True

        # Ладьи / ферзи
        rook = "R" if by_color == WHITE else "r"
        queen = "Q" if by_color == WHITE else "q"
        for dr, df in ROOK_DIRS:
            rr, ff = r + dr, f + df
            while 0 <= rr < 8 and 0 <= ff < 8:
                p = self.squares[rr * 8 + ff]
                if p != ".":
                    if p == rook or p == queen:
                        return True
                    break
                rr += dr
                ff += df

        # Слоны / ферзи
        bishop = "B" if by_color == WHITE else "b"
        for dr, df in BISHOP_DIRS:
            rr, ff = r + dr, f + df
            while 0 <= rr < 8 and 0 <= ff < 8:
                p = self.squares[rr * 8 + ff]
                if p != ".":
                    if p == bishop or p == queen:
                        return True
                    break
                rr += dr
                ff += df

        return False

    def in_check(self, color: str) -> bool:
        k = self.king_index(color)
        return k >= 0 and self.is_attacked(k, enemy(color))

    # ---------------- ГЕНЕРАЦИЯ ХОДОВ ----------------

    def generate_moves(self, legal: bool = True) -> List[Move]:
        moves: List[Move] = []
        me = self.turn
        for i, p in enumerate(self.squares):
            if p == "." or color_of(p) != me:
                continue
            up = p.upper()
            r, f = divmod(i, 8)

            if up == "P":
                direction = -1 if me == WHITE else 1          # белые идут вверх (индекс меньше)
                start_row = 6 if me == WHITE else 1
                promo_row = 0 if me == WHITE else 7

                # Ход на одну клетку
                rr = r + direction
                if 0 <= rr < 8 and self.squares[rr * 8 + f] == ".":
                    self._add_pawn_move(moves, i, rr * 8 + f, promo_row, "")
                    # Ход на две клетки
                    if r == start_row and self.squares[(r + 2 * direction) * 8 + f] == ".":
                        moves.append(Move(i, (r + 2 * direction) * 8 + f, "", "double"))
                # Взятия
                for df in (-1, 1):
                    ff = f + df
                    if not (0 <= ff < 8) or not (0 <= rr < 8):
                        continue
                    target = rr * 8 + ff
                    tp = self.squares[target]
                    if tp != "." and color_of(tp) != me:
                        self._add_pawn_move(moves, i, target, promo_row, "")
                    elif target == self.ep and tp == ".":
                        moves.append(Move(i, target, "", "ep"))

            elif up == "N":
                for dr, df in KNIGHT_DELTAS:
                    rr, ff = r + dr, f + df
                    if 0 <= rr < 8 and 0 <= ff < 8:
                        tp = self.squares[rr * 8 + ff]
                        if tp == "." or color_of(tp) != me:
                            moves.append(Move(i, rr * 8 + ff))

            elif up in ("B", "R", "Q"):
                dirs = BISHOP_DIRS if up == "B" else ROOK_DIRS if up == "R" else KING_DIRS
                for dr, df in dirs:
                    rr, ff = r + dr, f + df
                    while 0 <= rr < 8 and 0 <= ff < 8:
                        tp = self.squares[rr * 8 + ff]
                        if tp == ".":
                            moves.append(Move(i, rr * 8 + ff))
                        else:
                            if color_of(tp) != me:
                                moves.append(Move(i, rr * 8 + ff))
                            break
                        rr += dr
                        ff += df

            elif up == "K":
                for dr, df in KING_DIRS:
                    rr, ff = r + dr, f + df
                    if 0 <= rr < 8 and 0 <= ff < 8:
                        tp = self.squares[rr * 8 + ff]
                        if tp == "." or color_of(tp) != me:
                            moves.append(Move(i, rr * 8 + ff))
                moves.extend(self._castle_moves(me))

        if not legal:
            return moves

        result = []
        for m in moves:
            undo = self.make_move(m)
            ok = not self.in_check(me)
            self.unmake_move(m, undo)
            if ok:
                result.append(m)
        return result

    def _add_pawn_move(self, moves: List[Move], frm: int, to: int, promo_row: int, flag: str) -> None:
        if to // 8 == promo_row:
            for promo in "qrbn":
                moves.append(Move(frm, to, promo.upper(), "promo"))
        else:
            moves.append(Move(frm, to, "", flag))

    def _castle_moves(self, color: str) -> List[Move]:
        """Рокировки (проверяются поля, права и нападение на поля, через которые идёт король)."""
        moves: List[Move] = []
        row = 7 if color == WHITE else 0
        king_from = row * 8 + 4
        rights = "KQ" if color == WHITE else "kq"
        foe = enemy(color)

        if self.squares[king_from] != ("K" if color == WHITE else "k"):
            return moves
        if self.is_attacked(king_from, foe):
            return moves

        if rights[0] in self.castling:  # короткая (в сторону h)
            if self.squares[row * 8 + 5] == "." and self.squares[row * 8 + 6] == ".":
                if not self.is_attacked(row * 8 + 5, foe) and not self.is_attacked(row * 8 + 6, foe):
                    moves.append(Move(king_from, row * 8 + 6, "", "castle"))

        if rights[1] in self.castling:  # длинная (в сторону a)
            if (self.squares[row * 8 + 3] == "." and self.squares[row * 8 + 2] == "."
                    and self.squares[row * 8 + 1] == "."):
                if not self.is_attacked(row * 8 + 3, foe) and not self.is_attacked(row * 8 + 2, foe):
                    moves.append(Move(king_from, row * 8 + 2, "", "castle"))
        return moves

    # ---------------- ВЫПОЛНЕНИЕ / ОТКАТ ХОДА ----------------

    def make_move(self, m: Move) -> dict:
        undo = {
            "captured": ".",
            "captured_sq": -1,
            "castling": self.castling,
            "ep": self.ep,
            "halfmove": self.halfmove,
            "fullmove": self.fullmove,
            "piece": self.squares[m.frm],
        }
        piece = self.squares[m.frm]
        color = color_of(piece)
        up = piece.upper()

        # Взятие на проходе
        if m.flag == "ep":
            cap_sq = m.to + (8 if color == WHITE else -8)
            undo["captured"] = self.squares[cap_sq]
            undo["captured_sq"] = cap_sq
            self.squares[cap_sq] = "."

        # Обычное взятие
        elif self.squares[m.to] != ".":
            undo["captured"] = self.squares[m.to]
            undo["captured_sq"] = m.to

        self.squares[m.frm] = "."
        self.squares[m.to] = piece

        # Превращение
        if m.flag == "promo" and m.promo:
            self.squares[m.to] = m.promo.upper() if color == WHITE else m.promo.lower()

        # Рокировка: двигаем ладью
        if m.flag == "castle":
            row = m.frm // 8
            if m.to % 8 == 6:      # короткая
                self.squares[row * 8 + 5] = self.squares[row * 8 + 7]
                self.squares[row * 8 + 7] = "."
            else:                  # длинная
                self.squares[row * 8 + 3] = self.squares[row * 8 + 0]
                self.squares[row * 8 + 0] = "."

        # Права на рокировку
        cast = self.castling
        if up == "K":
            cast = cast.replace("K", "").replace("Q", "") if color == WHITE else cast.replace("k", "").replace("q", "")
        if up == "R":
            if m.frm == 63:
                cast = cast.replace("K", "")
            elif m.frm == 56:
                cast = cast.replace("Q", "")
            elif m.frm == 7:
                cast = cast.replace("k", "")
            elif m.frm == 0:
                cast = cast.replace("q", "")
        # Если ладья взята — тоже теряем право
        if m.to == 63:
            cast = cast.replace("K", "")
        elif m.to == 56:
            cast = cast.replace("Q", "")
        elif m.to == 7:
            cast = cast.replace("k", "")
        elif m.to == 0:
            cast = cast.replace("q", "")
        self.castling = cast

        # Поле для взятия на проходе
        if m.flag == "double":
            self.ep = (m.frm + m.to) // 2
        else:
            self.ep = -1

        # Счётчики
        if up == "P" or undo["captured"] != ".":
            self.halfmove = 0
        else:
            self.halfmove += 1
        if color == BLACK:
            self.fullmove += 1

        self.turn = enemy(self.turn)
        self.history.append((m, undo))
        key = self.position_key()
        self.repetition[key] = self.repetition.get(key, 0) + 1
        return undo

    def unmake_move(self, m: Move, undo: dict) -> None:
        key = self.position_key()
        if key in self.repetition:
            self.repetition[key] -= 1
            if self.repetition[key] <= 0:
                del self.repetition[key]

        self.turn = enemy(self.turn)
        piece = undo["piece"]
        color = color_of(piece)

        self.squares[m.frm] = piece
        self.squares[m.to] = "."

        if m.flag == "ep":
            self.squares[undo["captured_sq"]] = undo["captured"]
        elif undo["captured"] != ".":
            self.squares[undo["captured_sq"]] = undo["captured"]

        if m.flag == "castle":
            row = m.frm // 8
            if m.to % 8 == 6:
                self.squares[row * 8 + 7] = self.squares[row * 8 + 5]
                self.squares[row * 8 + 5] = "."
            else:
                self.squares[row * 8 + 0] = self.squares[row * 8 + 3]
                self.squares[row * 8 + 3] = "."

        self.castling = undo["castling"]
        self.ep = undo["ep"]
        self.halfmove = undo["halfmove"]
        self.fullmove = undo["fullmove"]
        if self.history:
            self.history.pop()

    # ---------------- РЕЗУЛЬТАТ ПАРТИИ ----------------

    def is_game_over(self) -> Tuple[bool, str]:
        """Возвращает (партия_окончена, причина)."""
        moves = self.generate_moves()
        if not moves:
            if self.in_check(self.turn):
                winner = "белые" if self.turn == BLACK else "чёрные"
                return True, f"МАТ! Победа: {winner}"
            return True, "ПАТ — ничья (нет ходов, но шаха нет)"
        if self.halfmove >= 100:
            return True, "НИЧЬЯ по правилу 50 ходов"
        if self.repetition.get(self.position_key(), 0) >= 3:
            return True, "НИЧЬЯ — троекратное повторение позиции"
        if self._insufficient_material():
            return True, "НИЧЬЯ — недостаточно материала для мата"
        return False, ""

    def _insufficient_material(self) -> bool:
        pieces = [p for p in self.squares if p != "."]
        if len(pieces) == 2:
            return True
        if len(pieces) == 3 and any(p.upper() in ("N", "B") for p in pieces):
            return True
        if len(pieces) == 4 and all(p.upper() == "B" or p.upper() == "N" for p in pieces):
            return True
        return False


# ------------------------------------------------------------------------------------
#  ОЦЕНКА ПОЗИЦИИ
# ------------------------------------------------------------------------------------

def evaluate(board: Board) -> int:
    """Оценка позиции в сантипешках. Плюс — хорошо для белых."""
    score = 0
    for i, p in enumerate(board.squares):
        if p == ".":
            continue
        up = p.upper()
        v = PIECE_VALUE[up] + PST[up][i if p.isupper() else 63 - i]
        # Учёт пары слонов
        score += v if p.isupper() else -v
    # Пара слонов
    if sum(1 for p in board.squares if p == "B") >= 2:
        score += 30
    if sum(1 for p in board.squares if p == "b") >= 2:
        score -= 30
    return score


def move_order_score(board: Board, m: Move) -> int:
    """Чем больше счёт, тем раньше пробуем ход (перебор пойдёт быстрее)."""
    s = 0
    victim = board.squares[m.to]
    if victim != ".":
        attacker = board.squares[m.frm]
        s += 10 * PIECE_VALUE[victim.upper()] - PIECE_VALUE[attacker.upper()]
    if m.flag == "ep":
        s += 10 * PIECE_VALUE["P"]
    if m.promo:
        s += PIECE_VALUE[m.promo.upper()]
    return s


# ------------------------------------------------------------------------------------
#  ПОИСК ЛУЧШЕГО ХОДА
# ------------------------------------------------------------------------------------

class Engine:
    """Минимакс с альфа-бета отсечением + поиск взятий. Уровни сложности — по глубине."""

    def __init__(self, board: Board):
        self.board = board
        self.nodes = 0
        self.tt: Dict[str, Tuple[int, int, Optional[Move]]] = {}
        self.deadline = 0.0

    def search(self, depth: int, time_limit: float = 3.0) -> Tuple[Optional[Move], int]:
        self.nodes = 0
        self.deadline = time.time() + time_limit
        history_depth = len(self.board.history)
        best_move: Optional[Move] = None
        best_score = -10 ** 9
        try:
            for d in range(1, depth + 1):
                try:
                    move, score = self._root(d)
                except TimeoutError:
                    break
                if move is not None:
                    best_move, best_score = move, score
                if time.time() > self.deadline:
                    break
        finally:
            # Если время вышло прямо посреди перебора, часть ходов могла остаться
            # «сделанной» на доске — обязательно откатываем их обратно.
            while len(self.board.history) > history_depth:
                m, undo = self.board.history[-1]
                self.board.unmake_move(m, undo)
        return best_move, best_score

    def _root(self, depth: int) -> Tuple[Optional[Move], int]:
        moves = self.board.generate_moves()
        if not moves:
            return None, 0
        moves.sort(key=lambda m: move_order_score(self.board, m), reverse=True)
        best_move, best_score = moves[0], -10 ** 9
        alpha = -10 ** 9
        for m in moves:
            undo = self.board.make_move(m)
            score = -self._negamax(depth - 1, -10 ** 9, -alpha, 1)
            self.board.unmake_move(m, undo)
            if score > best_score:
                best_move, best_score = m, score
            alpha = max(alpha, score)
        return best_move, best_score

    def _negamax(self, depth: int, alpha: int, beta: int, ply: int) -> int:
        self.nodes += 1
        if self.nodes % 2048 == 0 and time.time() > self.deadline:
            raise TimeoutError

        if depth <= 0:
            return self._quiescence(alpha, beta, ply)

        key = self.board.position_key()
        entry = self.tt.get(key)
        if entry and entry[0] >= depth:
            _, val, mv = entry
            if mv is not None and self.board.squares[mv.frm] != ".":
                pass
            return val

        moves = self.board.generate_moves()
        if not moves:
            return -30000 + ply if self.board.in_check(self.board.turn) else 0

        moves.sort(key=lambda m: move_order_score(self.board, m), reverse=True)
        best = -10 ** 9
        for m in moves:
            undo = self.board.make_move(m)
            score = -self._negamax(depth - 1, -beta, -alpha, ply + 1)
            self.board.unmake_move(m, undo)
            if score > best:
                best = score
            alpha = max(alpha, score)
            if alpha >= beta:
                break

        self.tt[key] = (depth, best, None)
        if len(self.tt) > 400000:
            self.tt.clear()
        return best

    def _quiescence(self, alpha: int, beta: int, ply: int) -> int:
        """Считаем только «шумные» ходы (взятия/превращения), чтобы не терять фигуры."""
        self.nodes += 1
        if self.nodes % 2048 == 0 and time.time() > self.deadline:
            raise TimeoutError

        stand = evaluate(self.board) if self.board.turn == WHITE else -evaluate(self.board)
        if stand >= beta:
            return beta
        if stand > alpha:
            alpha = stand
        if ply > 6:
            return alpha

        moves = [m for m in self.board.generate_moves()
                 if self.board.squares[m.to] != "." or m.promo or m.flag == "ep"]
        moves.sort(key=lambda m: move_order_score(self.board, m), reverse=True)
        for m in moves:
            undo = self.board.make_move(m)
            score = -self._quiescence(-beta, -alpha, ply + 1)
            self.board.unmake_move(m, undo)
            if score >= beta:
                return beta
            if score > alpha:
                alpha = score
        return alpha


DIFFICULTIES = {
    "1": ("Новичок", 0),
    "2": ("Легко", 1),
    "3": ("Средне", 2),
    "4": ("Сложно", 3),
    "5": ("Мастер", 4),
}


def computer_move(board: Board, level: int, verbose: bool = True) -> Optional[Move]:
    """Ход компьютера с учётом уровня сложности."""
    moves = board.generate_moves()
    if not moves:
        return None

    if level <= 1:
        # Самый слабый уровень: случайный ход, но взятия — чуть охотнее.
        weighted = []
        for m in moves:
            w = 1
            if board.squares[m.to] != ".":
                w = 3
            if m.promo:
                w = 4
            weighted.extend([m] * w)
        return random.choice(weighted)

    depth = {2: 1, 3: 2, 4: 3, 5: 4}.get(level, 2)
    limit = {2: 0.4, 3: 1.2, 4: 2.5, 5: 5.0}.get(level, 1.2)
    engine = Engine(board)
    try:
        best, score = engine.search(depth, limit)
    except TimeoutError:
        best, score = None, 0
    if best is None:
        best = random.choice(moves)
    if verbose:
        print(f"   [компьютер думал {engine.nodes} вариантов, оценка {score}]")
    return best


# ------------------------------------------------------------------------------------
#  КОНСОЛЬНЫЙ ИНТЕРФЕЙС
# ------------------------------------------------------------------------------------

class ConsoleGame:
    def __init__(self, level: int = 3, human_color: str = WHITE):
        self.board = Board()
        self.level = level
        self.human = human_color
        self.use_color = True

    def print_board(self, show_moves: Optional[List[Move]] = None) -> None:
        b = self.board
        marks = set()
        if show_moves:
            marks = {m.to for m in show_moves}
        print()
        print("     a   b   c   d   e   f   g   h")
        print("   +------------------------------- +")
        for r in range(8):
            row = f" {8 - r} |"
            for f in range(8):
                i = r * 8 + f
                p = b.squares[i]
                glyph = UNICODE_PIECES.get(p, " ")
                if self.use_color:
                    if p.isupper():
                        row += f" \033[1;97m{glyph}\033[0m |"
                    elif p.islower():
                        row += f" \033[1;90m{glyph}\033[0m |"
                    else:
                        row += "   |"
                else:
                    row += f" {glyph if p != '.' else ' '} |"
            print(row)
            print("   +---+---+---+---+---+---+---+---+")
        print(f"   FEN: {b.fen()}")
        if b.in_check(b.turn):
            print("   !!! ШАХ !!!")

    def help_text(self) -> str:
        return (
            "\n  Команды:\n"
            "    e2e4          — ход (откуда и куда), превращение: e7e8q\n"
            "    подсказка     — показать хороший ход\n"
            "    отмена        — отменить свой ход и ход компьютера\n"
            "    уровень 3     — сменить сложность (1..5)\n"
            "    доска         — нарисовать доску заново\n"
            "    выход         — закончить игру\n"
        )

    def run(self) -> None:
        print("=" * 62)
        print(" ШАХМАТЫ НА PYTHON   (консольный режим)")
        print("=" * 62)
        print(f" Вы играете: {'БЕЛЫЕ' if self.human == WHITE else 'ЧЁРНЫЕ'}"
              f"   |   Уровень: {self.level} — {DIFFICULTIES[str(self.level)][0]}")
        print(self.help_text())

        while True:
            over, reason = self.board.is_game_over()
            self.print_board()
            if over:
                print("\n  " + reason)
                print("  Партия окончена. Спасибо за игру!  (нажмите Enter)")
                input()
                return

            if self.board.turn == self.human:
                cmd = input("  Ваш ход: ").strip().lower()
                if not cmd:
                    continue
                if cmd in ("выход", "quit", "exit", "q"):
                    print("  До встречи!")
                    return
                if cmd in ("help", "помощь"):
                    print(self.help_text())
                    continue
                if cmd in ("подсказка", "hint"):
                    engine = Engine(self.board)
                    mv, sc = engine.search(3, 2.0)
                    print(f"  Подсказка: {mv.uci() if mv else 'нет хода'}  (оценка {sc})")
                    continue
                if cmd in ("отмена", "undo"):
                    if len(self.board.history) >= 2:
                        for _ in range(2):
                            m, u = self.board.history[-1]
                            self.board.unmake_move(m, u)
                        print("  Ход отменён.")
                    else:
                        print("  Отменять пока нечего.")
                    continue
                if cmd.startswith("уровень"):
                    parts = cmd.split()
                    if len(parts) > 1 and parts[1] in DIFFICULTIES:
                        self.level = int(parts[1])
                        print(f"  Уровень: {self.level} — {DIFFICULTIES[parts[1]][0]}")
                    continue

                move = self.parse_move(cmd)
                if move is None:
                    print("  Не понял ход. Пример: e2e4  (или 'подсказка', 'выход')")
                    continue
                self.board.make_move(move)
            else:
                print("  Ход компьютера...")
                mv = computer_move(self.board, self.level)
                if mv is None:
                    continue
                self.board.make_move(mv)
                print(f"  Компьютер: {mv.uci()}")

    def parse_move(self, text: str) -> Optional[Move]:
        legal = self.board.generate_moves()
        words = [t for t in text.replace("-", " ").replace(",", " ").split() if t]
        candidate = words[-1] if words else text.strip()
        if len(candidate) < 4:
            return None
        try:
            frm = square_to_index(candidate[0:2])
            to = square_to_index(candidate[2:4])
        except (ValueError, IndexError):
            return None
        promo = candidate[4].upper() if len(candidate) >= 5 else ""
        for m in legal:
            if m.frm == frm and m.to == to:
                if m.promo:
                    if promo and m.promo.upper() == promo:
                        return m
                    if not promo and m.promo.upper() == "Q":
                        return m
                else:
                    return m
        return None


# ------------------------------------------------------------------------------------
#  ГРАФИЧЕСКИЙ ИНТЕРФЕЙС (tkinter)
# ------------------------------------------------------------------------------------

def run_gui(level: int = 3) -> None:
    import tkinter as tk
    from tkinter import messagebox

    LIGHT = "#f0d9b5"
    DARK = "#b58863"
    HL = "#f7ec74"     # выделение выбранной фигуры
    DOT = "#4a7a2a"    # точки возможных ходов

    class ChessGUI:
        def __init__(self, root: "tk.Tk"):
            self.root = root
            self.board = Board()
            self.level = level
            self.human = WHITE
            self.selected: Optional[int] = None
            self.legal: List[Move] = []
            self.flipped = False
            self.cell = 76
            self.busy = False

            root.title("Шахматы на Python  \u265e")
            root.resizable(False, False)
            root.configure(bg="#222")

            top = tk.Frame(root, bg="#222")
            top.pack(fill="x", padx=8, pady=6)

            tk.Label(top, text="Уровень:", fg="#eee", bg="#222",
                     font=("Segoe UI", 10)).pack(side="left")
            self.level_var = tk.StringVar(value=str(self.level))
            tk.OptionMenu(top, self.level_var, "1", "2", "3", "4", "5",
                          command=self.change_level).pack(side="left", padx=4)

            self.status = tk.StringVar(value="Ваш ход (вы играете белыми)")
            tk.Label(root, textvariable=self.status, fg="#8fd3ff", bg="#222",
                     font=("Segoe UI", 11, "bold")).pack(pady=(0, 4))

            size = self.cell * 8
            self.canvas = tk.Canvas(root, width=size, height=size, highlightthickness=0)
            self.canvas.pack(padx=8)
            self.canvas.bind("<Button-1>", self.on_click)

            bottom = tk.Frame(root, bg="#222")
            bottom.pack(fill="x", padx=8, pady=8)
            for text, cmd in (("Новая партия", self.new_game),
                              ("Отменить ход", self.undo),
                              ("Подсказка", self.hint),
                              ("Перевернуть доску", self.flip)):
                tk.Button(bottom, text=text, command=cmd, font=("Segoe UI", 10)).pack(side="left", padx=3)

            self.draw()

        # ---------- отрисовка ----------
        def cell_at(self, index: int) -> Tuple[int, int]:
            r, f = divmod(index, 8)
            if self.flipped:
                r, f = 7 - r, 7 - f
            return f * self.cell, r * self.cell

        def draw(self) -> None:
            self.canvas.delete("all")
            for idx in range(64):
                r, f = divmod(idx, 8)
                x, y = self.cell_at(idx)
                fill = LIGHT if (r + f) % 2 == 0 else DARK
                if idx == self.selected:
                    fill = HL
                self.canvas.create_rectangle(x, y, x + self.cell, y + self.cell,
                                             fill=fill, outline="")
                p = self.board.squares[idx]
                if p != ".":
                    color = "#ffffff" if p.isupper() else "#101010"
                    self.canvas.create_text(x + self.cell / 2, y + self.cell / 2,
                                            text=UNICODE_PIECES[p], font=("Segoe UI Symbol", 40),
                                            fill=color)
                if any(m.to == idx for m in self.legal):
                    self.canvas.create_oval(x + self.cell / 2 - 8, y + self.cell / 2 - 8,
                                            x + self.cell / 2 + 8, y + self.cell / 2 + 8,
                                            fill=DOT, outline="")
            self.highlight_last()

        def highlight_last(self) -> None:
            if not self.board.history:
                return
            m, _ = self.board.history[-1]
            for idx in (m.frm, m.to):
                x, y = self.cell_at(idx)
                self.canvas.create_rectangle(x + 2, y + 2, x + self.cell - 2, y + self.cell - 2,
                                             outline="#ffcc00", width=3)

        def index_from_xy(self, x: int, y: int) -> int:
            f, r = x // self.cell, y // self.cell
            if self.flipped:
                f, r = 7 - f, 7 - r
            return r * 8 + f

        # ---------- логика ----------
        def change_level(self, value: str) -> None:
            self.level = int(value)
            self.status.set(f"Уровень {self.level}: {DIFFICULTIES[value][0]}")

        def new_game(self) -> None:
            self.board = Board()
            self.selected, self.legal = None, []
            self.legal = []
            self.status.set("Новая партия. Ваш ход (вы играете белыми).")
            self.draw()

        def undo(self) -> None:
            if self.busy:
                return
            if len(self.board.history) >= 2:
                for _ in range(2):
                    m, u = self.board.history[-1]
                    self.board.unmake_move(m, u)
                self.selected, self.legal = None, []
                self.status.set("Ход отменён.")
                self.draw()
            else:
                self.status.set("Отменять пока нечего.")

        def hint(self) -> None:
            if self.board.turn != self.human:
                self.status.set("Сейчас ход компьютера.")
                return
            self.status.set("Думаю над подсказкой...")
            self.root.update_idletasks()
            engine = Engine(self.board)
            mv, sc = engine.search(3, 1.5)
            self.status.set(f"Подсказка: {mv.uci() if mv else '—'}  (оценка {sc})")

        def flip(self) -> None:
            self.flipped = not self.flipped
            self.draw()

        def on_click(self, event) -> None:
            if self.busy or self.board.turn != self.human:
                return
            idx = self.index_from_xy(event.x, event.y)
            if not (0 <= idx < 64):
                return
            p = self.board.squares[idx]

            if self.selected is None:
                if p != "." and color_of(p) == self.human:
                    self.selected = idx
                    self.legal = [m for m in self.board.generate_moves() if m.frm == idx]
            else:
                for m in self.legal:
                    if m.to == idx:
                        self.do_move(m)
                        return
                if p != "." and color_of(p) == self.human:
                    self.selected = idx
                    self.legal = [m for m in self.board.generate_moves() if m.frm == idx]
                else:
                    self.selected, self.legal = None, []
            self.draw()

        def do_move(self, m: Move) -> None:
            if m.promo:
                m = self.ask_promotion(m)
            self.board.make_move(m)
            self.selected, self.legal = None, []
            self.draw()

            over, reason = self.board.is_game_over()
            if over:
                self.status.set(reason)
                messagebox.showinfo("Партия окончена", reason)
                return

            self.busy = True
            self.status.set("Компьютер думает...")
            self.root.update_idletasks()
            mv = computer_move(self.board, self.level, verbose=False)
            if mv is not None:
                self.board.make_move(mv)
            self.busy = False
            self.draw()

            over, reason = self.board.is_game_over()
            if over:
                self.status.set(reason)
                messagebox.showinfo("Партия окончена", reason)
            else:
                self.status.set("Ваш ход." + (" ШАХ!" if self.board.in_check(self.human) else ""))

        def ask_promotion(self, m: Move) -> Move:
            """Спрашиваем, в кого превратить пешку (по умолчанию — ферзь)."""
            win = tk.Toplevel(self.root)
            win.title("Превращение пешки")
            win.configure(bg="#222")
            tk.Label(win, text="Выберите фигуру:", fg="#eee", bg="#222").pack(padx=12, pady=8)
            choice = {"piece": "Q"}

            def pick(p: str) -> None:
                choice["piece"] = p
                win.destroy()

            frame = tk.Frame(win, bg="#222")
            frame.pack(padx=12, pady=8)
            for p in "QRBN":
                tk.Button(frame, text=UNICODE_PIECES[p] + " " + PIECE_NAMES_RU[p],
                          font=("Segoe UI Symbol", 12), command=lambda p=p: pick(p)).pack(side="left", padx=3)
            win.transient(self.root)
            win.grab_set()
            self.root.wait_window(win)
            return Move(m.frm, m.to, choice["piece"], "promo")

    root = tk.Tk()
    ChessGUI(root)
    root.mainloop()


# ------------------------------------------------------------------------------------
#  ПРОВЕРКА КОРРЕКТНОСТИ ПРАВИЛ (perft) — пригодится, чтобы убедиться, что всё честно
# ------------------------------------------------------------------------------------

def perft(board: Board, depth: int) -> int:
    if depth == 0:
        return 1
    moves = board.generate_moves()
    if depth == 1:
        return len(moves)
    total = 0
    for m in moves:
        undo = board.make_move(m)
        total += perft(board, depth - 1)
        board.unmake_move(m, undo)
    return total


def self_test(verbose: bool = True) -> bool:
    """Перф-тесты: сверяем генератор ходов с эталонными значениями."""
    cases = [
        (START_FEN, 1, 20),
        (START_FEN, 2, 400),
        (START_FEN, 3, 8902),
        (START_FEN, 4, 197281),
        # «Kiwipete» — позиция, проверяющая рокировки, шах и связки
        ("r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1", 3, 97862),
        ("8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1", 3, 2812),
    ]
    ok = True
    for fen, depth, expected in cases:
        b = Board(fen)
        got = perft(b, depth)
        good = got == expected
        ok &= good
        if verbose:
            print(f"  perft({depth}) = {got:>8}  ожидалось {expected:>8}  {'OK' if good else 'ОШИБКА'}")
    if verbose:
        print("  Итог:", "все тесты пройдены ✔" if ok else "есть расхождения ✘")
    return ok


# ------------------------------------------------------------------------------------
#  ТОЧКА ВХОДА
# ------------------------------------------------------------------------------------

def ask_console_settings() -> Tuple[int, str]:
    print("\n  Уровень сложности:")
    for k, (name, _) in DIFFICULTIES.items():
        print(f"    {k} — {name}")
    level_raw = input("  Выберите (Enter = 3): ").strip() or "3"
    level = int(level_raw) if level_raw in DIFFICULTIES else 3
    color_raw = input("  Играть белыми или чёрными? (б/ч, Enter = белыми): ").strip().lower()
    human = BLACK if color_raw.startswith("ч") or color_raw.startswith("b") else WHITE
    return level, human


def main(argv: List[str]) -> int:
    # На Windows включаем UTF-8, чтобы красиво рисовались фигуры-символы.
    if os.name == "nt":
        os.system("chcp 65001 > nul")
        try:
            sys.stdout.reconfigure(encoding="utf-8")
            sys.stdin.reconfigure(encoding="utf-8")
        except Exception:
            pass

    if "--perft" in argv or "--test" in argv:
        print("Проверка генератора ходов (perft):")
        return 0 if self_test() else 1

    level = 3
    for a in argv:
        if a.startswith("--level="):
            try:
                level = max(1, min(5, int(a.split("=")[1])))
            except ValueError:
                pass

    console = "--console" in argv or "--cli" in argv
    gui = "--gui" in argv

    if console:
        lvl, human = ask_console_settings()
        ConsoleGame(lvl, human).run()
        return 0

    # По умолчанию пытаемся открыть красивое окно, при неудаче — консоль.
    try:
        if console:
            raise RuntimeError
        run_gui(level)
        return 0
    except ImportError:
        print("  (tkinter не найден — запускаю консольный режим)\n")
    except Exception as exc:  # noqa: BLE001 — окно могло не открыться (нет экрана и т.п.)
        if not gui:
            print(f"  (графический режим недоступен: {exc} — запускаю консольный)\n")
        else:
            raise

    lvl, human = ask_console_settings()
    ConsoleGame(lvl, human).run()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

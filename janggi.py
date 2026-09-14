# -*- coding: utf-8 -*-
"""장기 — 규칙과 다이아가 둘 수.

체스·오목·할리갈리와 같은 자리다. 규칙은 서버가 쥐고, 무슨 말을
할지는 개체(avatar.py)가 정한다.

쓸 만한 파이썬 장기 라이브러리가 없어서 규칙을 직접 썼다.

## 판

9칸 × 10줄. 90칸을 문자열로 들고 다닌다 — 기억에 그대로 넣고
화면에 그대로 보내려면 이 편이 다루기 쉽다.

    줄 0~2 위 궁성 (초 · 다이아)
    줄 7~9 아래 궁성 (한 · 사람)

말은 글자 하나로 적는다. 대문자가 아래쪽(한), 소문자가 위쪽(초)이다.

    K 궁   A 사   R 차   C 포   N 마   B 상   P 졸

## 장기가 체스와 다른 것 넷

1. **포는 넘어가야 간다.** 사이에 말이 정확히 하나 있어야 하고,
   그 말이 포면 못 넘는다. 포로 포를 잡지도 못한다.
2. **마·상은 막힌다.** 먼저 곧게 한 칸 가는데 거기 말이 있으면
   못 간다. 상은 그 뒤 비스듬히 가는 길목도 본다.
3. **궁성이 있다.** 궁과 사는 궁성을 못 나간다. 궁성 안에서는
   그어진 선을 따라 비스듬히도 간다 — 차·포·졸도 그 선을 쓴다.
4. **졸은 뒤로 못 간다.** 앞·옆으로만 한 칸.
"""
import random

COLS = 9
ROWS = 10
EMPTY = "."

HAN = "han"        # 아래쪽. 사람이 잡는다.
CHO = "cho"        # 위쪽. 다이아가 잡는다.

# 말 값. 장기에서 쓰는 값에 가깝게 잡았다.
VALUE = {
    "K": 10000, "R": 13, "C": 7, "N": 5, "B": 3, "A": 3, "P": 2,
}

KO = {
    "K": "궁", "A": "사", "R": "차", "C": "포",
    "N": "마", "B": "상", "P": "졸",
}

# 궁성 — 줄과 칸의 범위
PALACE = {
    CHO: (0, 2, 3, 5),
    HAN: (7, 9, 3, 5),
}

# 궁성 안에 그어진 비스듬한 선의 끝점과 가운데.
# 이 점들끼리만 비스듬히 오간다.
DIAG = {}

for side, (r0, r1, c0, c1) in PALACE.items():
    mid = ((r0 + r1) // 2, (c0 + c1) // 2)
    for corner in ((r0, c0), (r0, c1), (r1, c0), (r1, c1)):
        DIAG.setdefault(corner, set()).add(mid)
        DIAG.setdefault(mid, set()).add(corner)


# ============================================================
# 판
# ============================================================

# 처음 벌여 놓는 자리는 마상상마(안상) 한 가지만 쓴다.
# 여러 벌임을 고르게 하면 화면도 규칙도 한 겹 더 복잡해진다.

def new_board():
    """처음 판. 위가 초(소문자), 아래가 한(대문자)."""
    b = [EMPTY] * (ROWS * COLS)

    def put(r, c, ch):
        b[r * COLS + c] = ch

    back = ["R", "N", "B", "A", "K", "A", "B", "N", "R"]

    # 위 — 초. 궁은 궁성 가운데(줄 1)에 앉힌다.
    for c, ch in enumerate(back):
        if ch == "K":
            continue
        put(0, c, ch.lower())

    put(1, 4, "k")
    put(2, 1, "c")
    put(2, 7, "c")

    for c in (0, 2, 4, 6, 8):
        put(3, c, "p")

    # 아래 — 한
    for c, ch in enumerate(back):
        if ch == "K":
            continue
        put(9, c, ch)

    put(8, 4, "K")
    put(7, 1, "C")
    put(7, 7, "C")

    for c in (0, 2, 4, 6, 8):
        put(6, c, "P")

    return "".join(b)


def at(board, r, c):
    if r < 0 or r >= ROWS or c < 0 or c >= COLS:
        return None
    return board[r * COLS + c]


def side_of(ch):
    if not ch or ch == EMPTY:
        return None
    return HAN if ch.isupper() else CHO


def other(side):
    return CHO if side == HAN else HAN


def move(board, frm, to):
    a = list(board)
    a[to] = a[frm]
    a[frm] = EMPTY
    return "".join(a)


def in_palace(side, r, c):
    r0, r1, c0, c1 = PALACE[side]
    return r0 <= r <= r1 and c0 <= c <= c1


def in_any_palace(r, c):
    return in_palace(CHO, r, c) or in_palace(HAN, r, c)


# ============================================================
# 말마다 갈 수 있는 곳
#
# 여기서는 '내 왕이 잡히는가' 를 안 본다. 그건 legal_moves 가 거른다.
# ============================================================

def _slide_dirs(r, c):
    """차·궁·사가 곧게 갈 네 방향. 궁성 안이면 비스듬한 선도."""
    out = [(-1, 0), (1, 0), (0, -1), (0, 1)]

    for (dr, dc) in ((-1, -1), (-1, 1), (1, -1), (1, 1)):
        if (r + dr, c + dc) in DIAG.get((r, c), ()):
            out.append((dr, dc))

    return out


def _rook_moves(board, i, side):
    r, c = divmod(i, COLS)
    out = []

    for dr, dc in _slide_dirs(r, c):
        # 궁성의 비스듬한 선은 한 칸씩만 잇는다.
        diag = dr and dc
        rr, cc = r + dr, c + dc

        while 0 <= rr < ROWS and 0 <= cc < COLS:
            ch = at(board, rr, cc)

            if ch == EMPTY:
                out.append(rr * COLS + cc)
            else:
                if side_of(ch) != side:
                    out.append(rr * COLS + cc)
                break

            if diag:
                # 다음 점도 선으로 이어져 있어야 더 간다
                if (rr + dr, cc + dc) not in DIAG.get((rr, cc), ()):
                    break

            rr += dr
            cc += dc

    return out


def _cannon_moves(board, i, side):
    """포 — 사이에 말이 정확히 하나 있어야 넘는다.

    **넘는 말이 포면 못 넘고, 포를 잡지도 못한다.** 장기에서 포가
    포를 어쩌지 못하는 것이 이 놀이의 큰 특징이다.
    """
    r, c = divmod(i, COLS)
    out = []

    for dr, dc in _slide_dirs(r, c):
        diag = dr and dc
        rr, cc = r + dr, c + dc
        jumped = False

        while 0 <= rr < ROWS and 0 <= cc < COLS:
            ch = at(board, rr, cc)

            if not jumped:
                if ch != EMPTY:
                    if ch.upper() == "C":
                        break          # 포는 못 넘는다
                    jumped = True
            else:
                if ch == EMPTY:
                    out.append(rr * COLS + cc)
                else:
                    if side_of(ch) != side and ch.upper() != "C":
                        out.append(rr * COLS + cc)
                    break

            if diag:
                if (rr + dr, cc + dc) not in DIAG.get((rr, cc), ()):
                    break

            rr += dr
            cc += dc

    return out


# 마와 상은 얼개가 같다. 곧게 한 칸 간 뒤 비스듬히 몇 칸 —
# 마는 한 칸, 상은 두 칸이다. 지나는 자리가 모두 비어 있어야 한다.
#
# 곧게 간 방향에 맞는 비스듬한 방향만 쓴다. 위로 갔으면 위-왼쪽과
# 위-오른쪽뿐이다. 아무 비스듬한 방향이나 쓰면 제자리로 돌아오는
# 이상한 수가 생긴다.
ORTH = ((-1, 0), (1, 0), (0, -1), (0, 1))

DIAG_FOR = {
    (-1, 0): ((-1, -1), (-1, 1)),
    (1, 0): ((1, -1), (1, 1)),
    (0, -1): ((-1, -1), (1, -1)),
    (0, 1): ((-1, 1), (1, 1)),
}


def _leg_moves(board, i, side, steps):
    """곧게 한 칸 + 비스듬히 steps 칸. 길목이 막히면 못 간다."""
    r, c = divmod(i, COLS)
    out = []

    for d in ORTH:
        mr, mc = r + d[0], c + d[1]

        if at(board, mr, mc) != EMPTY:
            continue          # 첫 길목이 막혔다

        for dd in DIAG_FOR[d]:
            rr, cc = mr, mc
            blocked = False

            for k in range(steps):
                rr, cc = rr + dd[0], cc + dd[1]
                ch = at(board, rr, cc)

                if ch is None:
                    blocked = True
                    break

                # 마지막 칸이 아니면 비어 있어야 지나간다
                if k < steps - 1 and ch != EMPTY:
                    blocked = True
                    break

            if blocked:
                continue

            ch = at(board, rr, cc)

            if ch is not None and (ch == EMPTY or side_of(ch) != side):
                out.append(rr * COLS + cc)

    return out


def _horse_moves(board, i, side):
    """마 — 곧게 한 칸, 비스듬히 한 칸."""
    return _leg_moves(board, i, side, 1)


def _elephant_moves(board, i, side):
    """상 — 곧게 한 칸, 비스듬히 두 칸."""
    return _leg_moves(board, i, side, 2)


def _king_moves(board, i, side):
    """궁·사 — 궁성 안에서 한 칸. 그어진 선을 따라 비스듬히도."""
    r, c = divmod(i, COLS)
    out = []

    for dr, dc in _slide_dirs(r, c):
        rr, cc = r + dr, c + dc

        if not in_palace(side, rr, cc):
            continue

        ch = at(board, rr, cc)

        if ch is not None and (ch == EMPTY or side_of(ch) != side):
            out.append(rr * COLS + cc)

    return out


def _pawn_moves(board, i, side):
    """졸 — 앞·옆으로 한 칸. 뒤로는 못 간다.

    궁성 안에서는 그어진 선을 따라 비스듬히 앞으로도 간다.
    """
    r, c = divmod(i, COLS)
    fwd = 1 if side == CHO else -1          # 초는 아래로, 한은 위로
    out = []

    steps = [(fwd, 0), (0, -1), (0, 1)]

    for dr, dc in ((fwd, -1), (fwd, 1)):
        if (r + dr, c + dc) in DIAG.get((r, c), ()):
            steps.append((dr, dc))

    for dr, dc in steps:
        rr, cc = r + dr, c + dc
        ch = at(board, rr, cc)

        if ch is not None and (ch == EMPTY or side_of(ch) != side):
            out.append(rr * COLS + cc)

    return out


MOVERS = {
    "R": _rook_moves,
    "C": _cannon_moves,
    "N": _horse_moves,
    "B": _elephant_moves,
    "K": _king_moves,
    "A": _king_moves,
    "P": _pawn_moves,
}


def moves_from(board, i):
    ch = board[i]

    if ch == EMPTY:
        return []

    side = side_of(ch)

    return MOVERS[ch.upper()](board, i, side)


def all_moves(board, side):
    """거르지 않은 수 전부. (from, to) 목록."""
    out = []

    for i, ch in enumerate(board):
        if ch != EMPTY and side_of(ch) == side:
            for j in moves_from(board, i):
                out.append((i, j))

    return out


# ============================================================
# 장군
# ============================================================

def find_king(board, side):
    want = "K" if side == HAN else "k"

    return board.find(want)


def in_check(board, side):
    """이 쪽 궁이 잡히게 생겼는가."""
    k = find_king(board, side)

    if k < 0:
        return True

    for _, j in all_moves(board, other(side)):
        if j == k:
            return True

    # 빅장 — 두 궁이 같은 줄에서 마주 보면 안 된다.
    #
    # 장기에서는 이것을 서로 못 하게 되어 있다. 여기서는 '그렇게
    # 두면 안 되는 수' 로 다룬다.
    k2 = find_king(board, other(side))

    if k2 >= 0:
        r1, c1 = divmod(k, COLS)
        r2, c2 = divmod(k2, COLS)

        if c1 == c2:
            lo, hi = sorted((r1, r2))
            if all(at(board, r, c1) == EMPTY for r in range(lo + 1, hi)):
                return True

    return False


def legal_moves(board, side):
    """두고 나서 내 궁이 안 잡히는 수만."""
    out = []

    for frm, to in all_moves(board, side):
        if not in_check(move(board, frm, to), side):
            out.append((frm, to))

    return out


def outcome(board, side):
    """이 쪽이 둘 차례일 때의 판세.

    'mate' 외통 · 'stalemate' 둘 데가 없음 · None 아직
    """
    if legal_moves(board, side):
        return None

    return "mate" if in_check(board, side) else "stalemate"


# ============================================================
# 두는 눈
# ============================================================

def evaluate(board, side):
    """말 값과 갈 데의 넓이로 잰다."""
    total = 0

    for i, ch in enumerate(board):
        if ch == EMPTY:
            continue

        v = VALUE[ch.upper()]
        total += v if side_of(ch) == side else -v

    # 갈 데가 넓은 쪽이 낫다. 말 값보다 훨씬 작게 쳐서
    # 말을 공짜로 주고 자리만 넓히는 일이 없게 한다.
    total += (len(all_moves(board, side))
              - len(all_moves(board, other(side)))) * 0.08

    return total


def _search(board, side, depth, alpha, beta):
    if depth <= 0:
        return evaluate(board, side)

    moves = legal_moves(board, side)

    if not moves:
        return -99999 if in_check(board, side) else 0

    # 잡는 수부터 본다. 가지를 빨리 쳐낸다.
    moves.sort(key=lambda m: VALUE.get(board[m[1]].upper(), 0), reverse=True)

    best = -999999

    for frm, to in moves:
        v = -_search(move(board, frm, to), other(side), depth - 1, -beta, -alpha)

        if v > best:
            best = v

        alpha = max(alpha, v)

        if alpha >= beta:
            break

    return best


LEVELS = {
    "easy": {"label": "쉬움", "depth": 1, "blunder": 0.40},
    "normal": {"label": "보통", "depth": 2, "blunder": 0.12},
    "hard": {"label": "어려움", "depth": 3, "blunder": 0.0},
}


def choose(board, side, level="normal", mercy=0.0, rng=None):
    """다이아가 둘 수. 둘 데가 없으면 None.

    체스에서 배운 것과 같다 — 깊이만 낮추면 아무리 낮춰도 잘 안 진다.
    그래서 blunder(한눈팔기)로 조절한다. **다만 한 수면 이기는 자리는
    안 놓친다.**
    """
    rng = rng or random

    conf = LEVELS.get(level) or LEVELS["normal"]
    moves = legal_moves(board, side)

    if not moves:
        return None

    # 한 수에 이기는 자리
    for frm, to in moves:
        if outcome(move(board, frm, to), other(side)) == "mate":
            return (frm, to)

    if mercy and rng.random() < mercy:
        return rng.choice(moves)

    if conf["blunder"] and rng.random() < conf["blunder"]:
        return rng.choice(moves)

    moves.sort(key=lambda m: VALUE.get(board[m[1]].upper(), 0), reverse=True)

    depth = conf["depth"]

    # 깊게 읽을 때는 먼저 얕게 훑어 추린다.
    #
    # 장기는 한 수에 갈래가 30~40개다. 세 수를 그대로 읽으면 한 수에
    # 3.6초가 걸려서 놀이의 박자가 깨진다. 한 수만 읽어 순서를 잡고
    # 앞엣것 열둘만 깊게 보면 0.5초 안에 끝나고, 고르는 수는
    # 거의 같다 — 나쁜 수는 얕게 봐도 나쁘다.
    if depth >= 3 and len(moves) > 12:
        rough = sorted(
            ((-_search(move(board, f, t), other(side), 0, -999999, 999999), (f, t))
             for f, t in moves), key=lambda x: x[0], reverse=True)

        moves = [m for _, m in rough[:12]]

    best = None
    bestv = -999999

    for frm, to in moves:
        v = -_search(move(board, frm, to), other(side),
                     depth - 1, -999999, 999999)

        if v > bestv:
            bestv, best = v, [(frm, to)]
        elif v == bestv:
            best.append((frm, to))

    return rng.choice(best)


# ============================================================
# 화면에 보낼 한 벌
# ============================================================

def view(board, dia_side):
    return {
        "cols": COLS,
        "rows": [board[r * COLS:(r + 1) * COLS] for r in range(ROWS)],
        "dia": dia_side,
        "you": other(dia_side),
        "names": KO,
    }


def name(i):
    """사람이 읽는 자리 이름. 칸은 1~9, 줄은 1~10."""
    r, c = divmod(i, COLS)
    return "%d-%d" % (c + 1, r + 1)

# -*- coding: utf-8 -*-
"""오목 — 규칙과 다이아가 둘 자리.

체스·끝말잇기와 같은 자리다. **규칙은 서버가 쥔다.** 무슨 말을 할지는
개체(avatar.py)가 정하고, 어디에 둘지는 여기가 정한다.

판은 15x15. 칸을 문자열 225자로 들고 다닌다 — 기억에 그대로 넣고
화면에 그대로 보내려면 이 편이 다루기 쉽다.

  '.' 빈 칸   'b' 검은 돌   'w' 흰 돌

검은 쪽이 먼저 둔다. 오목은 먼저 두는 쪽이 유리해서, 사람에게
검은 쪽을 준다.

## 두는 눈

수를 깊게 읽지 않는다. **줄을 세어 점수를 매긴다.**

다섯 칸짜리 창을 판 전체에 훑으면서, 그 창에 내 돌이 몇이고 상대
돌이 몇인지로 값을 매긴다. 오목은 '몇 줄을 만들고 몇 줄을 막는가'
가 거의 전부라 이것만으로도 꽤 둔다.

깊게 읽는 것보다 이 편이 나은 까닭 — 오목은 가지가 225개라 두 수만
읽어도 5만 갈래다. 체스처럼 가지를 쳐내기도 어렵다. 줄 세기는 한 수에
0.05초면 끝나고, 사람이 느끼기에는 충분히 세다.
"""
import random

SIZE = 15
EMPTY = "."
BLACK = "b"
WHITE = "w"

WIN = 5

# 네 방향. 반대쪽은 같은 줄이라 안 본다.
DIRS = ((0, 1), (1, 0), (1, 1), (1, -1))


# ============================================================
# 판
# ============================================================

def new_board():
    return EMPTY * (SIZE * SIZE)


def at(board, r, c):
    if r < 0 or r >= SIZE or c < 0 or c >= SIZE:
        return None
    return board[r * SIZE + c]


def put(board, r, c, stone):
    i = r * SIZE + c
    return board[:i] + stone + board[i + 1:]


def empties(board):
    return [i for i, ch in enumerate(board) if ch == EMPTY]


def is_full(board):
    return EMPTY not in board


def other(stone):
    return WHITE if stone == BLACK else BLACK


# ============================================================
# 이겼는가
# ============================================================

def winner_at(board, r, c):
    """방금 (r,c)에 둔 돌로 다섯이 됐는가. 됐으면 그 돌, 아니면 None."""
    me = at(board, r, c)

    if not me or me == EMPTY:
        return None

    for dr, dc in DIRS:
        n = 1

        for sign in (1, -1):
            rr, cc = r + dr * sign, c + dc * sign

            while at(board, rr, cc) == me:
                n += 1
                rr += dr * sign
                cc += dc * sign

        if n >= WIN:
            return me

    return None


def winner(board):
    """판 전체에서 이긴 쪽. 없으면 None."""
    for r in range(SIZE):
        for c in range(SIZE):
            if board[r * SIZE + c] != EMPTY:
                w = winner_at(board, r, c)
                if w:
                    return w

    return None


# ============================================================
# 줄 세기
#
# 다섯 칸짜리 창 하나에 내 돌만 있으면 값이 있고, 상대 돌이 섞여
# 있으면 값이 없다. 그 창은 이제 다섯이 될 수 없기 때문이다.
#
# 값은 돌 수에 가파르게 준다. 넷은 셋보다 훨씬 급하다 —
# 넷을 놓치면 다음 수에 진다.
# ============================================================

SCORE = {0: 0, 1: 1, 2: 12, 3: 120, 4: 2400, 5: 200000}


def _windows():
    """다섯 칸짜리 창의 자리를 미리 뽑아 둔다.

    매번 만들면 한 수에 수만 번 도는 자리라 눈에 띄게 느려진다.
    """
    out = []

    for r in range(SIZE):
        for c in range(SIZE):
            for dr, dc in DIRS:
                er, ec = r + dr * (WIN - 1), c + dc * (WIN - 1)

                if 0 <= er < SIZE and 0 <= ec < SIZE:
                    out.append(tuple(
                        (r + dr * k) * SIZE + (c + dc * k) for k in range(WIN)
                    ))

    return out


WINDOWS = _windows()


def evaluate(board, me):
    """지금 판이 나에게 얼마나 좋은가."""
    him = other(me)
    total = 0

    for w in WINDOWS:
        mine = 0
        yours = 0

        for i in w:
            ch = board[i]
            if ch == me:
                mine += 1
            elif ch == him:
                yours += 1

        if mine and yours:
            continue          # 막힌 창. 값이 없다.

        if mine:
            total += SCORE[mine]
        elif yours:
            # 막는 값을 조금 더 쳐 준다.
            #
            # 같은 값으로 두면 상대가 넷을 만들어도 자기 셋을 놓는다.
            # 오목은 한 수만 늦어도 지는 놀이다.
            total -= int(SCORE[yours] * 1.15)

    return total


# ============================================================
# 어디에 둘까
# ============================================================

def _near(board, gap=2):
    """이미 놓인 돌 둘레만 본다.

    빈 판 225칸을 다 재면 느리기도 하고, 아무도 없는 구석에 두는
    이상한 수가 나온다. 오목은 돌이 모인 데서 승부가 난다.
    """
    if all(ch == EMPTY for ch in board):
        mid = SIZE // 2
        return [mid * SIZE + mid]

    seen = set()

    for i, ch in enumerate(board):
        if ch == EMPTY:
            continue

        r, c = divmod(i, SIZE)

        for dr in range(-gap, gap + 1):
            for dc in range(-gap, gap + 1):
                rr, cc = r + dr, c + dc

                if 0 <= rr < SIZE and 0 <= cc < SIZE:
                    j = rr * SIZE + cc
                    if board[j] == EMPTY:
                        seen.add(j)

    return sorted(seen)


LEVELS = {
    "easy": {"label": "쉬움", "blunder": 0.35, "look": False},
    "normal": {"label": "보통", "blunder": 0.08, "look": False},
    "hard": {"label": "어려움", "blunder": 0.0, "look": True},
}


def choose(board, me, level="normal", mercy=0.0, rng=None):
    """다이아가 둘 자리. 둘 데가 없으면 None.

    blunder 는 이 확률로 한눈을 파는 것이다. 깊이만 낮추면 아무리
    낮춰도 잘 안 진다 — 줄을 세는 눈은 그대로라서 공짜로 주는 법이
    없기 때문이다. 체스에서 배운 것과 같다.

    **다만 한 수면 이기는 자리와 막아야 하는 자리는 안 놓친다.**
    눈앞의 다섯을 못 보는 것은 쉬운 상대가 아니라 이상한 상대다.
    """
    rng = rng or random

    conf = LEVELS.get(level) or LEVELS["normal"]
    spots = _near(board)

    if not spots:
        return None

    him = other(me)

    # 1. 두면 이기는 자리
    for i in spots:
        r, c = divmod(i, SIZE)
        if winner_at(put(board, r, c, me), r, c) == me:
            return i

    # 2. 안 막으면 지는 자리
    for i in spots:
        r, c = divmod(i, SIZE)
        if winner_at(put(board, r, c, him), r, c) == him:
            return i

    # 3. 봐주기 — 사이가 깊으면 가끔 좋은 자리를 비워 둔다
    if mercy and rng.random() < mercy:
        return rng.choice(spots)

    # 4. 한눈팔기
    if conf["blunder"] and rng.random() < conf["blunder"]:
        return rng.choice(spots)

    # 5. 줄을 세어 고른다
    scored = sorted(((evaluate(put(board, *divmod(i, SIZE), me), me), i)
                     for i in spots), reverse=True)

    # 어려움에서는 한 수 더 본다 — 내가 두면 상대가 어디를 둘까.
    #
    # **상대의 답도 좋은 것부터 봐야 한다.** 처음에는 상대가 둘 수
    # 있는 자리를 판 왼쪽 위에서 열두 개 집어 봤는데, 그러면 좋은
    # 답이 아니라 아무 답이나 보는 것이라 오히려 약해졌다 —
    # 열여섯 판에서 보통에게 7승밖에 못 했다.
    #
    # 내 후보도 좋은 것 여덟 개만 본다. 나머지는 어차피 안 고른다.
    if conf["look"] and scored:
        deep = []

        for v, i in scored[:8]:
            b2 = put(board, *divmod(i, SIZE), me)

            # 상대가 가장 잘 두는 답 — 상대 눈으로 좋은 것부터
            his = sorted(((evaluate(put(b2, *divmod(j, SIZE), him), him), j)
                          for j in _near(b2)), reverse=True)[:6]

            worst = min((evaluate(put(b2, *divmod(j, SIZE), him), me)
                         for _, j in his), default=v)

            deep.append((worst, i))

        scored = sorted(deep, reverse=True)
    else:
        scored = sorted(scored, reverse=True)

    # 값이 같은 자리가 여럿이면 그중에서 고른다. 늘 같은 데 두면 심심하다.
    best = scored[0][0]
    top = [i for v, i in scored if v == best]

    return rng.choice(top)


# ============================================================
# 화면에 보낼 한 벌
# ============================================================

def view(board, dia_stone):
    """화면이 그릴 것.

    rows 는 15줄짜리 문자열 목록이다. 화면이 한 글자씩 읽어 그린다.
    """
    return {
        "size": SIZE,
        "rows": [board[r * SIZE:(r + 1) * SIZE] for r in range(SIZE)],
        "dia": dia_stone,
        "you": other(dia_stone),
        "moves": empties(board),
        "full": is_full(board),
    }


def coord(i):
    """225 자리 번호를 (줄, 칸)으로."""
    return divmod(i, SIZE)


def name(i):
    """사람이 읽는 자리 이름. A1 ~ O15."""
    r, c = divmod(i, SIZE)
    return "%s%d" % (chr(ord("A") + c), r + 1)

# chess_play.py
# diamondAI - 다이아가 체스를 둔다
#
# 규칙은 직접 짜지 않는다. 캐슬링·앙파상·승격·스테일메이트·3수 동형까지
# 손으로 짜면 반드시 어딘가 틀리고, 틀린 것을 나중에 찾기가 더 어렵다.
# python-chess 가 그것을 한다(순수 파이썬 565KB, 올린 데서도 돈다).
#
# 여기서 하는 일은 **무엇을 둘지 고르는 것** 하나다.
#
# 스톡피시 같은 것을 쓸 수도 있지만 그건 실행 파일이라 올린 데에 못
# 싣는다. 대신 작은 판단기를 둔다 —
#
#   말의 값 + 말이 놓인 자리의 값 + 몇 수 앞을 내다보기(알파베타)
#
# 사람과 두기에는 이만하면 된다. 세게 두는 것이 목적이 아니라
# 다이아가 같이 놀아 주는 것이 목적이다.

import random

import chess


# ============================================================
# 무엇이 얼마나 귀한가
# ============================================================

VALUE = {
    chess.PAWN: 100,
    chess.KNIGHT: 320,
    chess.BISHOP: 330,
    chess.ROOK: 500,
    chess.QUEEN: 900,
    chess.KING: 0,          # 왕은 값을 안 매긴다. 잡히면 판이 끝난다
}

# 같은 말이라도 어디 있느냐로 값이 달라진다.
#
# 이것이 없으면 말을 구석에 몰아넣고도 좋다고 여긴다. 폰은 앞으로
# 갈수록, 나이트는 가운데 있을수록 낫다. 아래 표는 흰 쪽 기준이고
# 검은 쪽은 위아래를 뒤집어 쓴다.
#
# a1 이 0, h8 이 63 이다. 사람이 읽기 좋게 8행부터 적는다.

def _flip(table):
    """8행부터 적은 표를 a1=0 순서로 돌린다."""
    out = []
    for row in range(7, -1, -1):
        out.extend(table[row * 8:(row + 1) * 8])
    return out


PAWN_TABLE = _flip([
     0,  0,  0,  0,  0,  0,  0,  0,
    50, 50, 50, 50, 50, 50, 50, 50,
    10, 10, 20, 30, 30, 20, 10, 10,
     5,  5, 10, 25, 25, 10,  5,  5,
     0,  0,  0, 20, 20,  0,  0,  0,
     5, -5,-10,  0,  0,-10, -5,  5,
     5, 10, 10,-20,-20, 10, 10,  5,
     0,  0,  0,  0,  0,  0,  0,  0,
])

KNIGHT_TABLE = _flip([
    -50,-40,-30,-30,-30,-30,-40,-50,
    -40,-20,  0,  0,  0,  0,-20,-40,
    -30,  0, 10, 15, 15, 10,  0,-30,
    -30,  5, 15, 20, 20, 15,  5,-30,
    -30,  0, 15, 20, 20, 15,  0,-30,
    -30,  5, 10, 15, 15, 10,  5,-30,
    -40,-20,  0,  5,  5,  0,-20,-40,
    -50,-40,-30,-30,-30,-30,-40,-50,
])

BISHOP_TABLE = _flip([
    -20,-10,-10,-10,-10,-10,-10,-20,
    -10,  0,  0,  0,  0,  0,  0,-10,
    -10,  0,  5, 10, 10,  5,  0,-10,
    -10,  5,  5, 10, 10,  5,  5,-10,
    -10,  0, 10, 10, 10, 10,  0,-10,
    -10, 10, 10, 10, 10, 10, 10,-10,
    -10,  5,  0,  0,  0,  0,  5,-10,
    -20,-10,-10,-10,-10,-10,-10,-20,
])

ROOK_TABLE = _flip([
      0,  0,  0,  0,  0,  0,  0,  0,
      5, 10, 10, 10, 10, 10, 10,  5,
     -5,  0,  0,  0,  0,  0,  0, -5,
     -5,  0,  0,  0,  0,  0,  0, -5,
     -5,  0,  0,  0,  0,  0,  0, -5,
     -5,  0,  0,  0,  0,  0,  0, -5,
     -5,  0,  0,  0,  0,  0,  0, -5,
      0,  0,  0,  5,  5,  0,  0,  0,
])

QUEEN_TABLE = _flip([
    -20,-10,-10, -5, -5,-10,-10,-20,
    -10,  0,  0,  0,  0,  0,  0,-10,
    -10,  0,  5,  5,  5,  5,  0,-10,
     -5,  0,  5,  5,  5,  5,  0, -5,
      0,  0,  5,  5,  5,  5,  0, -5,
    -10,  5,  5,  5,  5,  5,  0,-10,
    -10,  0,  5,  0,  0,  0,  0,-10,
    -20,-10,-10, -5, -5,-10,-10,-20,
])

KING_TABLE = _flip([
    -30,-40,-40,-50,-50,-40,-40,-30,
    -30,-40,-40,-50,-50,-40,-40,-30,
    -30,-40,-40,-50,-50,-40,-40,-30,
    -30,-40,-40,-50,-50,-40,-40,-30,
    -20,-30,-30,-40,-40,-30,-30,-20,
    -10,-20,-20,-20,-20,-20,-20,-10,
     20, 20,  0,  0,  0,  0, 20, 20,
     20, 30, 10,  0,  0, 10, 30, 20,
])

# 표는 반드시 64칸이어야 한다.
#
# 한 줄에 값 하나가 빠지면 그 뒤가 통째로 한 칸씩 밀려서, 틀린 자리를
# 좋다고 여기게 된다. 눈으로는 안 보인다 — 실제로 킹 표가 63칸이었다.
for _name, _t in (("폰", PAWN_TABLE), ("나이트", KNIGHT_TABLE),
                  ("비숍", BISHOP_TABLE), ("룩", ROOK_TABLE),
                  ("퀸", QUEEN_TABLE), ("킹", KING_TABLE)):
    if len(_t) != 64:
        raise ValueError(f"{_name} 표가 {len(_t)}칸이다. 64칸이어야 한다.")

TABLES = {
    chess.PAWN: PAWN_TABLE,
    chess.KNIGHT: KNIGHT_TABLE,
    chess.BISHOP: BISHOP_TABLE,
    chess.ROOK: ROOK_TABLE,
    chess.QUEEN: QUEEN_TABLE,
    chess.KING: KING_TABLE,
}

MATE = 100000


# ============================================================
# 이 판이 누구에게 좋은가
# ============================================================

def evaluate(board):
    """흰 쪽에서 본 점수. 클수록 흰 쪽이 좋다."""

    if board.is_checkmate():
        # 둘 차례인 쪽이 졌다
        return -MATE if board.turn == chess.WHITE else MATE

    if board.is_stalemate() or board.is_insufficient_material():
        return 0

    score = 0

    for square, piece in board.piece_map().items():
        val = VALUE[piece.piece_type]
        table = TABLES[piece.piece_type]

        if piece.color == chess.WHITE:
            score += val + table[square]
        else:
            # 검은 쪽은 표를 위아래로 뒤집어 본다
            score -= val + table[chess.square_mirror(square)]

    return score


def _order(board, moves):
    """볼 만한 수를 앞에 둔다.

    알파베타는 좋은 수를 먼저 봐야 가지를 많이 쳐낸다. 잡는 수와
    승격을 앞에 두는 것만으로도 훨씬 빨라진다.
    """

    def key(m):
        s = 0
        if board.is_capture(m):
            taken = board.piece_at(m.to_square)
            mover = board.piece_at(m.from_square)
            # 값싼 말로 값비싼 말을 잡는 수가 가장 볼 만하다
            s += 10 * (VALUE[taken.piece_type] if taken else 100)
            s -= VALUE[mover.piece_type] if mover else 0
        if m.promotion:
            s += 800
        if board.gives_check(m):
            s += 50
        return -s

    return sorted(moves, key=key)


def _search(board, depth, alpha, beta):
    """몇 수 앞을 내다본다. 흰 쪽에서 본 점수를 돌려준다."""

    if depth == 0 or board.is_game_over():
        return evaluate(board)

    moves = _order(board, list(board.legal_moves))

    if not moves:
        return evaluate(board)

    if board.turn == chess.WHITE:
        best = -MATE * 2
        for m in moves:
            board.push(m)
            best = max(best, _search(board, depth - 1, alpha, beta))
            board.pop()
            alpha = max(alpha, best)
            if alpha >= beta:
                break
        return best

    best = MATE * 2
    for m in moves:
        board.push(m)
        best = min(best, _search(board, depth - 1, alpha, beta))
        board.pop()
        beta = min(beta, best)
        if alpha >= beta:
            break
    return best


def choose(board, depth=2, mercy=0.0, blunder=0.0, rng=None):
    """다이아가 둘 수를 고른다.

    depth   : 몇 수 앞을 볼 것인가. 크면 세지고 느려진다.
    mercy   : 이 확률로 가장 좋은 수 대신 그다음 것을 고른다.
              가위바위보에서 사이가 깊으면 일부러 져 주는 것과 같다.
              티 나게 나쁜 수를 두지는 않는다 — 두 번째로 좋은 수다.
    blunder : 이 확률로 아무 수나 둔다. 난이도가 낮을 때 쓴다.
              **한눈판 것**이지 못 두는 것이 아니다 — 사람이 이기려면
              다이아가 가끔 놓쳐 줘야 하고, 늘 두 번째로 좋은 수만
              두면 아무리 낮춰도 안 진다.

    반환: (수, 점수) / 둘 수가 없으면 (None, 점수)
    """

    rng = rng or random

    moves = _order(board, list(board.legal_moves))

    if not moves:
        return None, evaluate(board)

    # 한눈팔기. 세는 것보다 먼저 한다 — 어차피 안 볼 것을 세면 느리다.
    #
    # 다만 한 수면 이기는 자리는 안 놓친다. 눈앞의 메이트를 못 보는 것은
    # 쉬운 상대가 아니라 이상한 상대다.
    if blunder > 0 and rng.random() < blunder:
        for m in moves:
            board.push(m)
            done = board.is_checkmate()
            board.pop()
            if done:
                return m, MATE

        return rng.choice(moves), evaluate(board)

    mine = board.turn
    scored = []

    for m in moves:
        board.push(m)
        s = _search(board, depth - 1, -MATE * 2, MATE * 2)
        board.pop()
        scored.append((s, m))

    # 내 쪽에서 좋은 순서로 세운다
    scored.sort(key=lambda x: x[0], reverse=(mine == chess.WHITE))

    # 같은 점수끼리는 섞는다. 안 그러면 늘 똑같은 판이 나온다.
    top = scored[0][0]
    tied = [m for s, m in scored if s == top]
    pick = rng.choice(tied)

    # 봐주기. 다만 이기는 수(메이트)는 안 버린다 —
    # 이길 수 있는데 안 이기면 봐주는 게 아니라 못 두는 것이다.
    if mercy > 0 and len(scored) > len(tied) and abs(top) < MATE // 2:
        if rng.random() < mercy:
            rest = [m for s, m in scored if s != top]
            if rest:
                pick = rest[0]

    return pick, top


# ============================================================
# 판의 상태를 화면이 읽을 수 있게
# ============================================================

def outcome_key(board):
    """지금 판이 어떤 상태인가.

    'checkmate_win'  다이아가 이겼다
    'checkmate_lose' 다이아가 졌다
    'draw'           비겼다
    'check'          장군
    None             아직 진행 중
    """

    if board.is_checkmate():
        # 둘 차례인 쪽이 진 것이다
        return "checkmate_lose" if board.turn == DIA_COLOR(board) else "checkmate_win"

    if board.is_stalemate() or board.is_insufficient_material() \
            or board.is_seventyfive_moves() or board.is_fivefold_repetition():
        return "draw"

    if board.is_check():
        return "check"

    return None


# 다이아가 어느 쪽인지는 판이 모른다. 밖에서 넣어 준다.
_dia_color = {"c": chess.BLACK}


def DIA_COLOR(board=None):
    return _dia_color["c"]


def set_dia_color(color):
    _dia_color["c"] = color


def board_view(board, dia_color):
    """화면이 그릴 것.

    말 자리는 8줄 문자열로 준다. 대문자가 흰 쪽이다.
    """

    rows = []

    for rank in range(7, -1, -1):
        row = ""
        for file in range(8):
            p = board.piece_at(chess.square(file, rank))
            row += p.symbol() if p else "."
        rows.append(row)

    last = board.peek().uci() if board.move_stack else None

    return {
        "fen": board.fen(),
        "rows": rows,
        "turn": "white" if board.turn == chess.WHITE else "black",
        "dia": "white" if dia_color == chess.WHITE else "black",
        "you": "black" if dia_color == chess.WHITE else "white",
        "check": board.is_check(),
        "over": board.is_game_over(),
        "last": last,
        "moves": [m.uci() for m in board.legal_moves],
        "count": board.fullmove_number,
    }


def taken_by(board, color):
    """그쪽이 잡은 말들. 처음 판과 견주어 없어진 것을 센다."""

    start = {
        chess.PAWN: 8, chess.KNIGHT: 2, chess.BISHOP: 2,
        chess.ROOK: 2, chess.QUEEN: 1,
    }

    other = not color
    out = []

    for kind, n in start.items():
        left = len(board.pieces(kind, other))
        out += [chess.piece_symbol(kind)] * max(0, n - left)

    return out

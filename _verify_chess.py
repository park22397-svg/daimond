# _verify_chess.py
# 다이아와 체스를 둘 수 있는가
#
# 눈으로 확인하기 어려운 것만 본다.
#
#   1. 판이 열리고, 창을 닫았다 열어도 두던 판이 남는가
#   2. 못 두는 수를 막는가
#   3. 다이아가 답으로 두는가 (그리고 그 수가 규칙에 맞는가)
#   4. 사람마다 판이 따로인가 (남의 판을 이어 두면 안 된다)
#   5. 끝까지 두면 이기고 지는 것을 알아보는가
#
# 진짜 계정과 기억을 안 건드리도록 임시 자리에서 돈다.

import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
os.chdir(HERE)

SANDBOX = tempfile.mkdtemp(prefix="dia_chess_")

import store  # noqa: E402

# **먼저 자리를 옮긴다.** 안 옮기면 진짜 계정 파일에 쓴다.
store.HERE = SANDBOX

import accounts  # noqa: E402
import chess  # noqa: E402
import chess_play  # noqa: E402
import main  # noqa: E402
from avatar import AVATAR  # noqa: E402

accounts.ITERATIONS = 1000

app = main.app
app.config["TESTING"] = True

fails = []


def ok(cond, what, detail=""):
    if cond:
        print("  PASS  " + what)
    else:
        print("  FAIL  " + what + ("  -- " + str(detail) if detail else ""))
        fails.append(what)


def _msgs_chess(h):
    """/api/history 는 목록을 그대로 준다."""
    if isinstance(h, list):
        return h
    if isinstance(h, dict):
        return h.get("history") or h.get("messages") or []
    return []


def signup(c, who):
    return c.post("/api/signup", json={
        "id": who, "password": "pw1234", "again": "pw1234"}).get_json()


print("판 열기")

with app.test_client() as c:
    signup(c, "player")

    r = c.get("/api/chess/state").get_json()
    ok(r["playing"] is False, "처음에는 두던 판이 없다", r)

    r = c.post("/api/chess/new", json={}).get_json()
    ok(r["ok"] and r["playing"], "판이 열린다", r)
    ok(r["dia"] == "black" and r["you"] == "white",
       "다이아가 검은 쪽, 사람이 흰 쪽", (r.get("dia"), r.get("you")))
    ok(r["turn"] == "white", "흰 쪽부터 둔다", r.get("turn"))
    ok(len(r["rows"]) == 8 and all(len(x) == 8 for x in r["rows"]),
       "판이 8x8 로 온다")
    ok(r["rows"][0] == "rnbqkbnr" and r["rows"][7] == "RNBQKBNR",
       "처음 놓임이 맞다", r["rows"][0] + " / " + r["rows"][7])
    ok(bool(r.get("line")), "판을 열며 말을 건다", r.get("line"))

    r2 = c.get("/api/chess/state").get_json()
    ok(r2["playing"] and r2["fen"] == r["fen"],
       "창을 닫았다 열어도 판이 남는다")


print()
print("두기")

with app.test_client() as c:
    signup(c, "mover")
    c.post("/api/chess/new", json={})

    r = c.post("/api/chess/move", json={"move": "e2e5"}).get_json()
    ok(r["ok"] is False, "못 두는 수를 막는다", r)

    r = c.post("/api/chess/move", json={"move": "zzzz"}).get_json()
    ok(r["ok"] is False, "말도 안 되는 것을 막는다", r)

    r = c.post("/api/chess/move", json={"move": "e2e4"}).get_json()
    ok(r["ok"], "둘 수 있는 수는 받는다", r)
    ok(bool(r.get("dia_move")), "다이아가 답으로 둔다", r)
    ok(r["turn"] == "white", "다시 사람 차례", r.get("turn"))

    # 다이아가 둔 수가 정말 그 자리에서 둘 수 있는 수였나
    b = chess.Board()
    b.push_uci("e2e4")
    ok(chess.Move.from_uci(r["dia_move"]) in b.legal_moves,
       "다이아의 수가 규칙에 맞는다", r["dia_move"])

    b.push_uci(r["dia_move"])
    ok(b.fen() == r["fen"], "판이 서버와 똑같다")


print()
print("사람마다 따로인가")

with app.test_client() as a:
    signup(a, "alice2")
    a.post("/api/chess/new", json={})
    a.post("/api/chess/move", json={"move": "d2d4"})
    fen_a = a.get("/api/chess/state").get_json()["fen"]

with app.test_client() as b2:
    signup(b2, "bob2")
    r = b2.get("/api/chess/state").get_json()
    ok(r["playing"] is False, "남의 판이 안 보인다", r)

    b2.post("/api/chess/new", json={})
    fen_b = b2.get("/api/chess/state").get_json()["fen"]
    ok(fen_a != fen_b, "두 사람의 판이 다르다")


print()
print("끝까지")

with app.test_client() as c:
    signup(c, "mater")

    # 바보 메이트. 사람(흰 쪽)이 두 수 만에 진다.
    c.post("/api/chess/new", json={})

    # 다이아가 어떻게 두든 상관없이 결과를 보려면 판을 직접 놓는다.
    import who
    import memory_manager
    who.set_current(accounts.slot_of("mater"))

    # 흰 쪽이 한 수면 메이트인 자리
    data = memory_manager.load_memory_data()
    data["chess"] = {"fen": "6k1/5ppp/8/8/8/8/5PPP/R5K1 w - - 0 1",
                     "dia": "black", "moves": []}
    memory_manager.save_memory_data(data)

    r = c.post("/api/chess/move", json={"move": "a1a8"}).get_json()
    ok(r["ok"] and r.get("over"), "체크메이트를 알아본다", r)
    ok(bool(r.get("line")), "지고 나서 말을 한다", r.get("line"))

    r = c.post("/api/chess/resign", methods=None) if False else \
        c.post("/api/chess/resign").get_json()
    ok(r["ok"] and r["playing"] is False, "그만두면 판이 사라진다", r)


print()
print("선공을 가위바위보로 정한다")

with app.test_client() as c:
    signup(c, "toss")

    r = c.post("/api/chess/start", json={}).get_json()
    ok(r.get("deciding") is True, "정하는 중으로 연다", r.get("deciding"))
    ok(r.get("playing") is False, "아직 판은 안 열렸다", r.get("playing"))
    ok(len(r.get("hands") or []) == 3, "손 셋을 준다",
       [h.get("key") for h in (r.get("hands") or [])])
    ok(bool(r.get("line")), "정하자고 말한다", r.get("line"))

    # 괄호를 쓰면 소리로 안 읽고 글자로만 나온다.
    ok("(" in (r.get("line") or ""), "규칙은 괄호로 알려 준다", r.get("line"))

    # 결판이 날 때까지 낸다
    end = None
    for _ in range(30):
        r = c.post("/api/chess/rps", json={"hand": "rock"}).get_json()
        ok_step = r.get("ok") is not False
        if not ok_step:
            break
        if r.get("playing") or r.get("choose"):
            end = r
            break

    ok(end is not None, "언젠가는 결판이 난다", r)

    if end and end.get("playing"):
        # 다이아가 이겼다. 선공을 가져갔으므로 다이아가 흰 쪽.
        ok(end.get("dia") == "white" and end.get("you") == "black",
           "다이아가 이기면 다이아가 선공", (end.get("dia"), end.get("you")))

    elif end:
        ok(end.get("choose") is True, "내가 이기면 고르라고 한다", end)

        r = c.post("/api/chess/new", json={"you": "white"}).get_json()
        ok(r.get("you") == "white" and r.get("playing"),
           "고르면 그 색으로 판이 열린다", (r.get("you"), r.get("playing")))

    # 정하는 중이 아닌데 손을 내면 막는다
    r = c.post("/api/chess/rps", json={"hand": "rock"}).get_json()
    ok(r.get("ok") is False, "정하는 중이 아니면 막는다", r)


print()
print("가위바위보를 기억하는가")

with app.test_client() as c:
    signup(c, "rpsmem")

    import who as _w
    import memory_manager as _m
    _w.set_current(accounts.slot_of("rpsmem"))

    ok(AVATAR.rps_note(None) is None, "안 놀았으면 알려줄 것도 없다")

    c.post("/api/rps", json={"hand": "rock"})
    c.post("/api/rps", json={"hand": "paper"})
    c.post("/api/rps", json={"hand": "scissors"})

    tally = (_m.load_memory_data() or {}).get("rps")
    total = sum(int(tally.get(k, 0)) for k in ("win", "lose", "draw"))
    ok(total == 3, "세 판이 전적에 쌓인다", tally)

    note = AVATAR.rps_note(tally)
    ok(bool(note) and "가위바위보" in note, "전적을 한 줄로 준다", note)
    ok("판" in note, "몇 판 했는지 말한다", note)


print()
print("어느 말을 잡을까")

with app.test_client() as c:
    signup(c, "sidepick")

    r = c.post("/api/chess/new", json={"you": "white"}).get_json()
    ok(r.get("you") == "white" and r.get("dia") == "black",
       "흰 말을 고르면 다이아가 검은 쪽", (r.get("you"), r.get("dia")))
    ok(r.get("turn") == "white" and not r.get("dia_move"),
       "흰 말이면 내가 먼저 둔다", r.get("turn"))

    r = c.post("/api/chess/new", json={"you": "black"}).get_json()
    ok(r.get("you") == "black" and r.get("dia") == "white",
       "검은 말을 고르면 다이아가 흰 쪽", (r.get("you"), r.get("dia")))
    ok(bool(r.get("dia_move")), "검은 말이면 다이아가 먼저 둔다",
       r.get("dia_move"))
    ok(r.get("turn") == "black", "그다음이 내 차례", r.get("turn"))

    # 고른 색은 새 판에도 남는다
    r = c.post("/api/chess/new", json={}).get_json()
    ok(r.get("you") == "black", "안 적어 보내면 고른 색 그대로",
       r.get("you"))

    # 검은 말로 실제로 둘 수 있는가
    r = c.post("/api/chess/move", json={"move": "e7e5"}).get_json()
    ok(r.get("ok"), "검은 말로 둔다", r)


print()
print("판을 돌려 그리는 셈")

# 화면이 검은 말을 아래로 오게 돌린다. 그 셈을 여기서도 해 본다.
def real_at(r, f, flip):
    return (7 - r, 7 - f) if flip else (r, f)


def sq_name(r, f):
    return "abcdefgh"[f] + str(8 - r)


start = ["rnbqkbnr", "pppppppp", "........", "........",
         "........", "........", "PPPPPPPP", "RNBQKBNR"]

for label, flip, mine in (("흰", False, "KQRBNP"), ("검은", True, "kqrbnp")):
    bottom = "".join(start[real_at(7, f, flip)[0]][real_at(7, f, flip)[1]]
                     for f in range(8))
    ok(all(ch in mine for ch in bottom),
       label + " 말을 잡으면 내 말이 아래에 온다", bottom)

for flip in (False, True):
    names = {sq_name(*real_at(r, f, flip))
             for r in range(8) for f in range(8)}
    ok(len(names) == 64, "돌려도 칸 이름이 겹치지 않는다 (뒤집기=%s)" % flip,
       len(names))


print()
print("난이도")

import random as _rnd  # noqa: E402

keys = [lv["key"] for lv in AVATAR.chess_levels()]
ok(keys == ["easy", "normal", "hard"], "쉬움·보통·어려움 셋", keys)
ok(AVATAR.chess_level("없는것")["key"] == "normal",
   "모르는 이름이 오면 기본으로")


def duel(white_key, black_key, seed, cap=120):
    """둘을 붙여 본다. 이긴 쪽을 돌려준다."""
    rng = _rnd.Random(seed)
    w = AVATAR.chess_level(white_key)
    b = AVATAR.chess_level(black_key)
    board = chess.Board()

    for _ in range(cap):
        if board.is_game_over():
            break
        lv = w if board.turn == chess.WHITE else b
        m, _s = chess_play.choose(board, depth=lv["depth"],
                                  blunder=lv["blunder"], rng=rng)
        if m is None:
            break
        board.push(m)

    if board.is_checkmate():
        return "black" if board.turn == chess.WHITE else "white"
    return "draw"


# 세기가 순서대로여야 한다. 이름만 다르고 똑같이 두면 난이도가 아니다.
hard_easy = [duel("hard", "easy", s) for s in range(4)]
ok(hard_easy.count("white") >= 3, "어려움이 쉬움을 이긴다", hard_easy)

norm_easy = [duel("normal", "easy", s) for s in range(4)]
ok(norm_easy.count("white") >= 3, "보통이 쉬움을 이긴다", norm_easy)

# 한눈을 팔아도 눈앞의 메이트는 안 놓친다
mate = chess.Board("6k1/5ppp/8/8/8/8/5PPP/R5K1 w - - 0 1")
hits = sum(1 for i in range(12)
           if chess_play.choose(chess.Board(mate.fen()), depth=1,
                                blunder=1.0,
                                rng=_rnd.Random(i))[0].uci() == "a1a8")
ok(hits == 12, "한눈팔기 중에도 한 수 메이트는 둔다", hits)


print()
print("난이도가 판과 함께 남는가")

with app.test_client() as c:
    signup(c, "levelkeep")
    r = c.post("/api/chess/new", json={"level": "easy"}).get_json()
    ok(r.get("level") == "easy", "새 판에 난이도를 정한다", r.get("level"))

    r = c.get("/api/chess/state").get_json()
    ok(r.get("level") == "easy", "창을 닫았다 열어도 남는다", r.get("level"))

    r = c.post("/api/chess/level", json={"level": "hard"}).get_json()
    ok(r.get("level") == "hard", "두던 판에서 난이도를 바꾼다", r.get("level"))

    r = c.post("/api/chess/move", json={"move": "e2e4"}).get_json()
    ok(r.get("level") == "hard", "한 수 둔 뒤에도 그대로", r.get("level"))


print()
print("다이아가 체스를 두는 줄 아는가")

# 판은 저장돼 있는데 대화 쪽에서 그걸 모르면, 한 판 두고 나서
# "아까 체스 어땠어?" 하고 물어도 무슨 소리인지 모른다.
with app.test_client() as c:
    signup(c, "knower")

    ok(AVATAR.chess_note(None) is None, "둘 판이 없으면 알려줄 것도 없다")

    c.post("/api/chess/new", json={"level": "easy"})
    c.post("/api/chess/move", json={"move": "e2e4"})

    import who as _who
    import memory_manager as _mm
    _who.set_current(accounts.slot_of("knower"))

    note = AVATAR.chess_note(_mm.load_memory_data().get("chess"))

    ok(bool(note), "판이 있으면 상황을 한 줄로 준다", note)
    ok("체스" in (note or ""), "체스라고 말해 준다", note)
    ok("검은" in (note or ""), "자기가 어느 쪽인지 안다", note)
    ok("쉬움" in (note or ""), "난이도도 안다", note)

    # 점수를 그대로 주면 사람이 안 하는 말이 나온다
    ok("점" not in (note or ""), "점수를 숫자로 말하지 않는다", note)

    hist = _msgs_chess(c.get("/api/history").get_json())
    ok(len(hist) > 0, "체스에서 한 말이 대화 기록에 남는다", len(hist))
    # 낱말로 찾으면 안 된다. 대사는 여럿 중 하나가 무작위로 나오는데
    # 어떤 것에는 그 낱말이 없다 - 실제로 그래서 검사가 오락가락했다.
    # 체스 표에 적힌 말 중 하나인지로 본다.
    said = set()
    for ev in AVATAR.chess().get("events", {}).values():
        for pool in (ev.get("lines") or {}).values():
            said.update(pool)

    ok(any(h.get("content") in said for h in hist),
       "남은 것이 체스 표에 있는 말이다", hist[:2])


print()
print("로그인 없이")

with app.test_client() as c:
    for path in ("/api/chess/state",):
        ok(c.get(path).status_code == 401, "체스도 로그인 없이 못 쓴다 " + path)
    for path in ("/api/chess/new", "/api/chess/move", "/api/chess/resign",
                 "/api/chess/level", "/api/chess/start", "/api/chess/rps"):
        ok(c.post(path, json={}).status_code == 401,
           "체스도 로그인 없이 못 쓴다 " + path)


print()
shutil.rmtree(SANDBOX, ignore_errors=True)

if fails:
    print("실패 " + str(len(fails)) + "건")
    for f in fails:
        print("  - " + f)
    sys.exit(1)

print("전부 통과")

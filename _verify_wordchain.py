# _verify_wordchain.py
# 끝말잇기가 엔진 손에서 끝까지 도는가.
#
# 잡으려는 것은 규칙이 아니라 **새는 자리**다.
#
# 규칙은 word_chain.py 가 쥐고 있어서 틀릴 일이 별로 없다. 진짜 사고는
# 한 수가 엔진을 안 거치고 **모델에게 새어 나갈 때** 난다 — 모델이 없는
# 낱말을 지어내고, 엔진은 제자리에 멈춰 있어서 그다음부터 엉뚱한 글자를
# 요구한다. 대화는 그럴듯해 보이는데 규칙만 어긋난다.
#
# 실제로 그랬다(2026-09-17): 사람이 "자라!" 라고 쳤는데 느낌표 때문에
# 낱말 검사를 못 넘었다. 그 수가 모델로 갔고, 모델이 '라무스' 를 지어냈고,
# 엔진은 두 수 전 '이분자' 에 멈춰 '자' 로 시작하라고 했다.

import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
os.chdir(HERE)

import store

store.HERE = tempfile.mkdtemp(prefix="dia_wc_")

import who

who.set_current(0)
store.begin_request()

import ai_brain
import word_chain as WC
from avatar import AVATAR

STAGE = AVATAR.stage("friend")
fails = []


def ok(cond, what, detail=""):
    if cond:
        print("  PASS  " + what)
    else:
        print("  FAIL  " + what + ("  -- " + str(detail) if detail else ""))
        fails.append(what)


def fresh():
    """새 판을 깐다. 시작 낱말을 돌려준다."""
    ai_brain._wc_save({})
    r = ai_brain._word_chain_turn("끝말잇기 하자", STAGE)
    return (ai_brain._wc_load() or {}).get("last"), r


print("1. 시작")

first, r = fresh()
ok(r is not None, "부르면 엔진이 받는다")
ok(bool(first), "시작 낱말이 있다", first)
ok(first in (r or {}).get("line", ""), "그 낱말을 말한다", (r or {}).get("line"))


print("\n2. 붙임표가 붙어도 엔진이 받는다")

MARKS = ["!", ".", "?", "~", " ", "  ", "…", ",", '"', "!!"]

for mark in MARKS:
    g = ai_brain._wc_load()
    if not g.get("on"):
        first, _ = fresh()
        g = ai_brain._wc_load()

    word = WC.pick(g.get("last"), set(g.get("used") or []), "normal")
    if not word:
        first, _ = fresh()
        g = ai_brain._wc_load()
        word = WC.pick(g.get("last"), set(g.get("used") or []), "normal")

    typed = word + mark
    out = ai_brain._word_chain_turn(typed, STAGE)

    ok(out is not None, f"{typed!r} 을 엔진이 받는다",
       "모델에게 샜다 — 여기서 판이 어긋난다")


print("\n3. 문장은 그대로 모델에게 넘긴다")

fresh()

for chat in ["오늘 좀 힘들었어", "너 뭐 해?", "내일 뭐 할까", "ㅋㅋㅋ"]:
    ok(ai_brain._word_chain_turn(chat, STAGE) is None,
       f"{chat!r} 는 놀이 말이 아니다")


print("\n4. 규칙")

first, _ = fresh()
g = ai_brain._wc_load()
last = g["last"]

# 안 이어지는 말은 막는다
bad = "밥" if not last.endswith("밥") else "국"
out = ai_brain._word_chain_turn(bad + "그릇", STAGE)
ok(out is not None and "시작" in out["line"] or "이어야" in (out or {}).get("line", ""),
   "안 이어지면 막는다", (out or {}).get("line"))
ok(ai_brain._wc_load().get("last") == last, "막았으면 판은 그대로다")

# 두음법칙 — '리' 는 '이' 로도 받는다. 이건 일부러 둔 규칙이다.
heads = WC.heads_for("리")
ok("이" in heads, "'리' 를 '이' 로 받을 수 있다 (두음법칙)", heads)
ok("녀" not in WC.heads_for("여"), "아무 글자나 바꿔 주지는 않는다")


print("\n5. 그만두기")

fresh()
out = ai_brain._word_chain_turn("그만", STAGE)
ok(out is not None, "그만하자는 말을 받는다")
ok(not (ai_brain._wc_load() or {}).get("on"), "판이 닫힌다")
ok(ai_brain._word_chain_turn("사과", STAGE) is None,
   "닫힌 뒤에는 낱말도 그냥 이야기다")


print("\n" + "=" * 60)
if fails:
    print(f"{len(fails)}건 실패")
    for f in fails:
        print("   - " + f)
    sys.exit(1)

print("전부 통과")

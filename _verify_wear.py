# _verify_wear.py
# 옷장이 제대로 도는가.
#
# 잡으려는 것
#   1. 말로 갈아입는 길 — (옷: 교복) 이 큐가 되고, 본문에서는 빠지는가
#   2. 서버가 실제로 갈아입히고 적어 두는가
#   3. 없는 옷·이미 입은 옷·벗기를 제대로 가르는가
#   4. 창을 열면 입고 있는가 (처음 온 사람 / 일부러 벗은 사람)
#   5. 프롬프트에 옷장이 실리는가
#
# 진짜 계정을 안 건드리도록 임시 폴더로 옮겨 놓고 돈다.

import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
os.chdir(HERE)

SANDBOX = tempfile.mkdtemp(prefix="dia_wear_")

import store

# **먼저 자리를 옮긴다.** 안 옮기면 이 검사가 진짜 계정에 쓴다.
store.HERE = SANDBOX

import accounts

accounts.ITERATIONS = 1000

import main
import memory_manager
from ai_brain import extract_cues
from avatar import AVATAR

app = main.app
app.config["TESTING"] = True

fails = []


def ok(cond, what, detail=""):
    if cond:
        print("  PASS  " + what)
    else:
        print("  FAIL  " + what + ("  -- " + str(detail) if detail else ""))
        fails.append(what)


ITEMS = main._wardrobe_items()

if not ITEMS:
    print("옷장이 비어 있어 건너뜁니다. "
          "(_extract_garment.py 로 옷을 구우면 여기서 검사합니다)")
    sys.exit(0)

FIRST = ITEMS[0]["key"]


print("1. 말에서 표시 꺼내기")

body, cues = extract_cues(f"좋아, 이거 입을게. (옷: {FIRST}) 어때?")

ok("(옷:" not in body, "본문에서 표시가 빠진다", body)
ok(FIRST not in body, "옷 이름도 본문에 안 남는다", body)

wear_cues = [c for c in cues if c.get("type") == "wear"]
ok(len(wear_cues) == 1, "옷 큐가 하나 나온다", cues)
ok(wear_cues and wear_cues[0].get("key") == FIRST, "이름을 제대로 읽는다")

# 장소 표시와 섞이지 않아야 한다
_b, _c = extract_cues("(배경: 공원) 여기 좋다")
ok(not [c for c in _c if c.get("type") == "wear"], "장소 표시를 옷으로 안 읽는다")


print("\n2. 갈아입히기")

with app.test_client() as c:
    c.post("/api/signup", json={"id": "wear_check",
                                "password": "pw123456", "again": "pw123456"})

    first = c.get("/api/wardrobe").get_json()
    ok(first.get("ok"), "옷장을 준다")
    ok(first.get("worn") == FIRST,
       "처음 온 사람은 기본 옷을 입고 있다", first.get("worn"))

    # 이미 입은 옷을 또 입으라면 아무 일도 없어야 한다
    out = main._apply_wear({"cues": list(cues)})
    ok(out.get("wear") is None, "이미 입은 옷이면 갈아입지 않는다")
    ok(not [x for x in out.get("cues", []) if x.get("type") == "wear"],
       "그래도 표시는 걷어낸다")

    # 벗기
    _b, off = extract_cues("(옷: 벗기)")
    out = main._apply_wear({"cues": off})
    ok((out.get("wear") or {}).get("key") == "", "말로 벗는다")
    ok(c.get("/api/wardrobe").get_json().get("worn") == "",
       "벗은 채로 적힌다")

    # 일부러 벗은 사람은 창을 열어도 벗은 채다
    ok(memory_manager.load_wearing() == "",
       "'벗음' 과 '아직 안 정함' 을 가른다")

    # 다시 입기
    _b, on = extract_cues(f"(옷: {FIRST})")
    out = main._apply_wear({"cues": on})
    ok((out.get("wear") or {}).get("key") == FIRST, "말로 다시 입는다")
    ok(c.get("/api/wardrobe").get_json().get("worn") == FIRST, "입은 채로 적힌다")

    # 없는 옷
    _b, bad = extract_cues("(옷: 있을리없는옷)")
    out = main._apply_wear({"cues": bad})
    ok(out.get("wear") is None, "없는 옷은 그냥 둔다")
    ok(c.get("/api/wardrobe").get_json().get("worn") == FIRST,
       "없는 옷을 말해도 입은 것이 안 바뀐다")

    # 단추로 갈아입는 길(POST)도 같은 자리에 적혀야 한다
    c.post("/api/wardrobe", json={"key": ""})
    ok(memory_manager.load_wearing() == "", "단추로 벗은 것도 적힌다")


print("\n3. 프롬프트")

p = AVATAR.system_prompt(stage=AVATAR.stage("friend"),
                         wardrobe=main._wardrobe_now(),
                         worn=FIRST)

ok("[입을 수 있는 옷]" in p, "옷장이 프롬프트에 실린다")
ok(FIRST in p, "옷 이름이 실린다")
ok("(옷: 교복) 처럼" in p, "어떻게 적는지 알려 준다")
ok("(지금 입은 것)" in p, "지금 입은 것을 표시한다")

note = AVATAR.wear_note(FIRST)
ok(note and FIRST in note, "무엇을 입고 있는지 한 줄로 준다", note)

# 옷장이 비면 블록이 아예 없어야 한다 (빈 목록을 적어 주면 헷갈린다)
ok(AVATAR.wardrobe_block([], None) is None, "옷장이 비면 안 적는다")


print("\n" + "=" * 60)
if fails:
    print(f"{len(fails)}건 실패")
    for f in fails:
        print("   - " + f)
    sys.exit(1)

print("전부 통과")

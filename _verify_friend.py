# _verify_friend.py
# 말은 서로 놓기로 해야 놓는다
#
# 예전에는 호감이 40 을 넘는 순간 저절로 반말이 됐다. 존댓말로
# 이야기하다가 갑자기 말이 놓이니 이상했다 - 사람은 그렇게 말을
# 놓지 않는다.
#
# 여기서 보는 것.
#
#   1. 친구 자리에 닿아도 말을 안 놓았으면 존댓말인가
#   2. 말 놓자고 하면 받아들이는가 (그리고 그때부터 반말인가)
#   3. 아직 이른 사이면 미루는가
#   4. 말투가 **모든 자리에서** 같이 바뀌는가
#      (한 군데만 빠뜨려도 거기서만 반말이 튀어나온다)
#   5. 말을 놓기 전에는 호감이 친구 자리에서 멈추는가
#
# 진짜 계정과 기억을 안 건드리도록 임시 자리에서 돈다.

import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
os.chdir(HERE)

SANDBOX = tempfile.mkdtemp(prefix="dia_friend_")

import store  # noqa: E402

# **먼저 자리를 옮긴다.** 안 옮기면 진짜 계정 파일에 쓴다.
store.HERE = SANDBOX

import accounts  # noqa: E402
import main  # noqa: E402
import memory_manager  # noqa: E402
import who  # noqa: E402
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


def polite(stage):
    return str(stage.speech).startswith("존댓말")


def pools(node, out=None):
    """그 표 아래에 있는 말들을 말투별로 모은다.

    낱말('요' 가 들어갔나)로 재면 안 된다. "일부러 봐주신 건 아니죠?"
    처럼 존댓말인데 '요' 도 '다' 도 없는 말이 있다 - 실제로 그것 때문에
    검사가 오락가락했다. **어느 주머니에서 나온 말인지**로 본다.
    """
    out = out if out is not None else {"polite": set(), "casual": set()}

    if isinstance(node, dict):
        for k, v in node.items():
            if k in ("polite", "casual") and isinstance(v, list):
                out[k].update(x if isinstance(x, str) else x.get("text", "")
                              for x in v)
            else:
                pools(v, out)

    elif isinstance(node, list):
        for v in node:
            pools(v, out)

    return out


def tone_of(line, table):
    """그 말이 어느 말투 주머니에서 나왔나. 'polite' / 'casual' / None."""

    if not line:
        return None

    p = pools(table)

    if line in p["polite"] and line not in p["casual"]:
        return "polite"

    if line in p["casual"] and line not in p["polite"]:
        return "casual"

    return None


def setup(c, uid, affinity, stage_key, friends=False):
    c.post("/api/signup", json={"id": uid, "password": "pw1234",
                                "again": "pw1234"})
    who.set_current(accounts.slot_of(uid))
    memory_manager.save_relationship(affinity, stage_key, friends=friends)


print("말을 놓기 전")

with app.test_client() as c:
    setup(c, "notyet", 60, "friend")

    rel = memory_manager.load_relationship()
    ok(rel.get("friends") is False, "처음에는 말을 안 놓은 상태", rel)

    st = AVATAR.speaking_stage(AVATAR.stage_for_affinity(60), False)
    ok(polite(st), "친구 자리인데도 존댓말", st.speech)

    # 놀이도 같은 말투여야 한다
    r = c.post("/api/chess/new", json={}).get_json()
    ok(tone_of(r.get("line"), AVATAR.chess()) == "polite",
       "체스도 존댓말", r.get("line"))

    r = c.post("/api/rps", json={"hand": "rock"}).get_json()
    line = r.get("reply") or r.get("line")
    ok(tone_of(line, AVATAR.rps()) == "polite",
       "가위바위보도 존댓말", line)


print()
print("말 놓기")

with app.test_client() as c:
    setup(c, "willdo", 60, "friend")

    r = c.post("/api/chat", json={"message": "우리 말 놓자"}).get_json()
    ok(bool(r.get("reply")), "말 놓자는 말에 답한다", r)

    rel = memory_manager.load_relationship()
    ok(rel.get("friends") is True, "이제 친구다", rel)
    ok(rel.get("affinity", 0) > 60, "호감도 조금 오른다", rel.get("affinity"))

    st = AVATAR.speaking_stage(AVATAR.stage_for_affinity(rel["affinity"]), True)
    ok(not polite(st), "이제 반말", st.speech)

    r = c.post("/api/chess/new", json={}).get_json()
    ok(tone_of(r.get("line"), AVATAR.chess()) == "casual",
       "체스도 반말", r.get("line"))

    r = c.post("/api/rps", json={"hand": "rock"}).get_json()
    line = r.get("reply") or r.get("line")
    ok(tone_of(line, AVATAR.rps()) == "casual",
       "가위바위보도 반말", line)


print()
print("아직 이른 사이")

with app.test_client() as c:
    setup(c, "tooearly", -5, "distant")

    r = c.post("/api/chat", json={"message": "우리 친구하자"}).get_json()
    ok(bool(r.get("reply")), "그래도 답은 한다", r)

    rel = memory_manager.load_relationship()
    ok(rel.get("friends") is False, "아직 친구가 아니다", rel)


print()
print("이미 놓았는데 또 말하면")

with app.test_client() as c:
    setup(c, "already", 80, "friend", friends=True)

    r = c.post("/api/chat", json={"message": "말 놓자"}).get_json()
    ok(bool(r.get("reply")), "어색하지 않게 받는다", r.get("reply"))

    rel = memory_manager.load_relationship()
    ok(rel.get("friends") is True, "여전히 친구")


print()
print("말을 놓기 전에는 호감이 멈춘다")

ceil = AVATAR.befriend_ceiling()
ok(ceil is not None, "친구 천장이 있다", ceil)

top_no = AVATAR.clamp_affinity(9999, lover=False, friends=False)
top_yes = AVATAR.clamp_affinity(9999, lover=False, friends=True)

ok(top_no == ceil, "말 놓기 전 천장", top_no)
ok(top_yes > top_no, "놓고 나면 더 올라간다", (top_no, top_yes))

st = AVATAR.stage_for_affinity(top_no)
ok(st.key == "friend", "친구 자리에서 멈춘다", st.label)


print()
print("다이아가 먼저 묻는다")

with app.test_client() as c:
    setup(c, "asker", 60, "friend")

    r = c.post("/api/first-talk", json={}).get_json()
    ok(r.get("speak") and "말" in (r.get("reply") or ""),
       "먼저 말 놓자고 꺼낸다", r.get("reply"))

    rel = memory_manager.load_relationship()
    ok(rel.get("asked_friend") is True, "물었다고 적어 둔다", rel)
    ok(rel.get("friends") is False,
       "묻기만 한 것이지 친구가 된 것은 아니다", rel)

    r2 = c.post("/api/first-talk", json={}).get_json()
    ok((r2.get("reply") or "") != (r.get("reply") or "")
       or not r2.get("speak"),
       "두 번 묻지 않는다", r2.get("reply"))


print()
print("낱말 가리기")

ok(AVATAR.is_befriend("우리 말 놓자"), "'말 놓자' 를 알아듣는다")
ok(AVATAR.is_befriend("친구하자"), "'친구하자' 를 알아듣는다")
ok(not AVATAR.is_befriend("친구가 그러는데 말이야"),
   "'친구가 그러는데' 는 제안이 아니다")
ok(not AVATAR.is_befriend("오늘 뭐 했어"), "아무 말이나 걸리지 않는다")


print()
shutil.rmtree(SANDBOX, ignore_errors=True)

if fails:
    print("실패 " + str(len(fails)) + "건")
    for f in fails:
        print("  - " + f)
    sys.exit(1)

print("전부 통과")

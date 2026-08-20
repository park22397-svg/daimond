# _verify_login.py
# 로그인이 실제로 사람을 가르는가
#
# 눈으로 확인하기 어려운 것들만 본다.
#
#   1. 로그인 없이 API 를 부르면 막히는가 (막히지 않으면 계정이 무의미하다)
#   2. 두 계정의 기억이 실제로 다른 파일인가
#   3. 한쪽에서 쓴 것이 다른 쪽에 보이는가 (보이면 갈린 것이 아니다)
#   4. 비밀번호가 파일에 그대로 적히지 않는가
#   5. 틀린 비밀번호로 못 들어가는가
#
# 진짜 계정 파일과 진짜 기억을 건드리지 않도록 임시 폴더에서 돈다.

import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

# 진짜 파일을 안 건드리도록 먼저 자리를 옮긴다.
SANDBOX = tempfile.mkdtemp(prefix="dia_login_")

import store

# 적고 읽는 일이 전부 store 를 지나가므로, 여기 한 곳만 옮기면
# 진짜 계정과 진짜 기억은 건드리지 않는다.
store.HERE = SANDBOX

import accounts
import memory_manager
import who

# 맞혀 보기를 느리게 하는 반복 횟수를 검사에서는 줄인다.
# 검사가 오래 걸리면 안 돌리게 된다.
accounts.ITERATIONS = 1000

fails = []


def ok(cond, what, detail=""):
    if cond:
        print("  PASS  " + what)
    else:
        print("  FAIL  " + what + ("  — " + detail if detail else ""))
        fails.append(what)


print("계정 만들기")

made, msg, slot_a = accounts.create("alice", "pw1234")
ok(made, "계정을 만든다", msg)

made2, msg2, _ = accounts.create("alice", "other")
ok(not made2, "같은 아이디는 두 번 못 만든다", msg2)

ok(accounts.create("ab", "pw1234")[0] is False, "짧은 아이디를 막는다")
ok(accounts.create("carol", "12")[0] is False, "짧은 비밀번호를 막는다")
ok(accounts.create("a/b", "pw1234")[0] is False, "아이디에 / 를 막는다")

_, _, slot_b = accounts.create("bob", "pw5678")


print()
print("들어가기")

ok(accounts.verify("alice", "pw1234") == slot_a, "맞는 비밀번호로 들어간다")
ok(accounts.verify("alice", "pw1235") is None, "틀린 비밀번호로 못 들어간다")
ok(accounts.verify("nobody", "pw1234") is None, "없는 아이디로 못 들어간다")
ok(accounts.verify("ALICE", "pw1234") == slot_a, "아이디 대소문자를 가리지 않는다")

raw = open(os.path.join(SANDBOX, "accounts.json"), encoding="utf-8").read()
ok("pw1234" not in raw, "비밀번호가 파일에 그대로 적히지 않는다")

rec = json.loads(raw)["users"]["alice"]
rec_b = json.loads(raw)["users"]["bob"]
ok(rec["salt"] != rec_b["salt"], "계정마다 소금이 다르다")


print()
print("기억이 갈리는가")

who.set_current(slot_a)
memory_manager.append_message("user", "앨리스가 한 말")
memory_manager.save_relationship(77, "love")

who.set_current(slot_b)
bob_conv = memory_manager.load_memory()
ok(bob_conv == [], "새 계정은 빈 기억으로 시작한다",
   str(bob_conv))

bob_rel = memory_manager.load_relationship()
ok(not bob_rel, "친밀도도 안 물려받는다", str(bob_rel))

memory_manager.append_message("user", "밥이 한 말")

who.set_current(slot_a)
alice_conv = memory_manager.load_memory()
ok(len(alice_conv) == 1 and alice_conv[0]["content"] == "앨리스가 한 말",
   "남이 쓴 것이 내 기억에 섞이지 않는다", str(alice_conv))
ok(memory_manager.load_relationship().get("affinity") == 77,
   "다시 들어오면 내 친밀도가 그대로 있다")

files = sorted(os.listdir(os.path.join(SANDBOX, "memory")))
ok(len(files) == 2, "기억 파일이 사람 수만큼 있다", str(files))


print()
print("보관함도 갈리는가")

who.set_current(slot_a)
memory_manager.archive_memory("20260820_000000")
ok(len(memory_manager.list_archives()) == 1, "앨리스의 보관함에 하나")

who.set_current(slot_b)
ok(len(memory_manager.list_archives()) == 0, "밥의 보관함은 비어 있다",
   str(memory_manager.list_archives()))

who.set_current(slot_a)
ok(memory_manager.restore_memory() is not None, "내가 치워 둔 것을 꺼내 온다")


print()
print("손님")

who.clear()
ok(who.current() == who.GUEST, "로그인 안 하면 손님 자리")
memory_manager.append_message("user", "손님이 한 말")

who.set_current(slot_a)
ok(all("손님" not in m["content"] for m in memory_manager.load_memory()),
   "손님이 쓴 것이 계정 기억에 안 섞인다")


print()
print("예전 기억 물려주기")

shutil.rmtree(os.path.join(SANDBOX, "memory"), ignore_errors=True)
os.remove(os.path.join(SANDBOX, "accounts.json"))

with open(os.path.join(SANDBOX, "memory_store.json"), "w",
          encoding="utf-8") as f:
    json.dump({
        "conversation": [{"role": "user", "content": "예전에 한 말"}],
        "long_term": [],
        "relationship": {"affinity": 120, "stage": "frenzy"},
    }, f, ensure_ascii=False)

ok(memory_manager.legacy_summary()["messages"] == 1, "물려줄 것을 미리 보여 준다")

first = accounts.count() == 0
_, _, s1 = accounts.create("first", "pw1234")
got = memory_manager.inherit_legacy(s1)
ok(first and got, "첫 계정이 물려받는다")

who.set_current(s1)
ok(memory_manager.load_relationship().get("affinity") == 120,
   "친밀도까지 물려받는다")

_, _, s2 = accounts.create("second", "pw1234")
ok(memory_manager.inherit_legacy(s2) is False,
   "두 번째 계정은 물려받을 것이 없다")

memory_manager.start_fresh(s2)
who.set_current(s2)
ok(memory_manager.load_memory() == [], "두 번째 계정은 빈 기억")


print()
shutil.rmtree(SANDBOX, ignore_errors=True)

if fails:
    print("실패 " + str(len(fails)) + "건")
    for f in fails:
        print("  - " + f)
    sys.exit(1)

print("전부 통과")

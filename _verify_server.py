# _verify_server.py
# 진짜 Flask 앱으로 끝까지 돌려 본다.
# 서버를 띄우지 않고 test_client 로 요청을 넣는다.
#
# 진짜 계정·기억을 안 건드리도록 임시 폴더로 옮겨 놓고 돈다.

import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
os.chdir(HERE)

SANDBOX = tempfile.mkdtemp(prefix="dia_live_")

import store

# **먼저 자리를 옮긴다.**
#
# 적고 읽는 일이 전부 store 를 지나가므로 여기 한 곳만 옮기면 된다.
# 반대로 여기를 안 옮기면 이 검사가 **진짜 계정 파일에 쓴다** -
# 실제로 한 번 그랬다(alice, bob 이 진짜 계정으로 들어갔다).
store.HERE = SANDBOX

import accounts
import memory_manager

accounts.ITERATIONS = 1000

import main

app = main.app
app.config["TESTING"] = True

fails = []


def _msgs(h):
    """/api/history 는 목록을 그대로 준다. 감싼 형태도 받아 준다."""
    if isinstance(h, list):
        return h
    if isinstance(h, dict):
        return h.get("history") or h.get("messages") or []
    return []


def ok(cond, what, detail=""):
    if cond:
        print("  PASS  " + what)
    else:
        print("  FAIL  " + what + ("  -- " + str(detail) if detail else ""))
        fails.append(what)


print("로그인 없이")

with app.test_client() as c:
    r = c.get("/")
    ok(r.status_code == 302 and "/login" in r.headers.get("Location", ""),
       "메인은 로그인 화면으로 보낸다", r.status_code)

    r = c.get("/api/history")
    ok(r.status_code == 401, "기록 API 가 막힌다", r.status_code)

    r = c.post("/api/chat", json={"message": "안녕"})
    ok(r.status_code == 401, "채팅 API 가 막힌다", r.status_code)

    r = c.post("/api/touch", json={"zone": "head"})
    ok(r.status_code == 401, "만지기 API 가 막힌다", r.status_code)

    r = c.get("/api/relationship")
    ok(r.status_code == 401, "관계 API 가 막힌다", r.status_code)

    r = c.get("/login")
    ok(r.status_code == 200, "로그인 화면은 열린다", r.status_code)

    r = c.get("/api/whoami")
    ok(r.status_code == 200 and r.get_json()["user"] is None,
       "누구냐고 물으면 아무도 아니라고 한다")


print()
print("회원가입")

with app.test_client() as c:
    r = c.post("/api/signup", json={"id": "alice", "password": "pw1234",
                                    "again": "pw1234"}).get_json()
    ok(r["ok"], "계정을 만든다", r)

    r2 = c.get("/api/whoami").get_json()
    ok(r2["user"] == "alice", "만들자마자 들어와 있다", r2)

    r3 = c.get("/")
    ok(r3.status_code == 200, "이제 메인이 열린다", r3.status_code)

    c.post("/api/chat", json={"message": "(머리를 쓰다듬는다)"})
    h = c.get("/api/history").get_json()
    n_alice = len(_msgs(h))
    ok(n_alice > 0, "앨리스의 기록이 쌓인다", h)


print()
print("다른 사람은 못 본다")

with app.test_client() as c:
    r = c.post("/api/signup", json={"id": "bob", "password": "pw5678",
                                    "again": "pw5678"}).get_json()
    ok(r["ok"], "둘째 계정을 만든다", r)
    ok(r.get("inherited") is False, "둘째는 물려받지 않는다", r)

    h = c.get("/api/history").get_json()
    n_bob = len(_msgs(h))
    ok(n_bob == 0, "밥에게는 앨리스의 대화가 안 보인다", h)


print()
print("다시 들어오기")

with app.test_client() as c:
    r = c.post("/api/login", json={"id": "alice", "password": "pw1234"}).get_json()
    ok(r["ok"], "앨리스로 들어온다", r)

    h = c.get("/api/history").get_json()
    ok(len(_msgs(h)) == n_alice,
       "내 기록이 그대로 있다 (로그인은 새 기억이 아니다)", h)

    r = c.post("/api/login", json={"id": "alice", "password": "틀린것"}).get_json()
    ok(not r["ok"], "틀린 비밀번호는 막힌다", r)

    r = c.post("/api/logout").get_json()
    ok(r["ok"], "나간다")

    r = c.get("/api/history")
    ok(r.status_code == 401, "나가면 다시 막힌다", r.status_code)


print()
print("기억 파일")

files = sorted(os.listdir(os.path.join(SANDBOX, "memory")))
ok(files == ["u_alice.json", "u_bob.json"], "사람마다 파일 하나", files)

a = json.load(open(os.path.join(SANDBOX, "memory", "u_alice.json"),
                   encoding="utf-8"))
b = json.load(open(os.path.join(SANDBOX, "memory", "u_bob.json"),
                   encoding="utf-8"))
ok(len(a["conversation"]) > 0 and len(b["conversation"]) == 0,
   "앨리스 파일에만 대화가 있다",
   (len(a["conversation"]), len(b["conversation"])))

shutil.rmtree(SANDBOX, ignore_errors=True)

print()
if fails:
    print("실패 " + str(len(fails)) + "건")
    for f in fails:
        print("  - " + f)
    sys.exit(1)

print("전부 통과")

# _bench_smart.py
# "끝말잇기도 못한다"는 지적을 그대로 시험한다.
# 끝말잇기는 앞 낱말의 마지막 글자를 기억하고 규칙을 지켜야 해서
# 작은 모델이 유독 못하는 과제다.

import os
import re
import sys
import time

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from avatar import AVATAR
from config import OLLAMA_OPTIONS, OLLAMA_URL

MODELS = ["gemma3:4b", "gemma4:31b"]

STAGE = AVATAR.stage("friend")
USER_NAME = "재현"

# 사용자가 부르는 낱말 -> 다이아가 이어야 할 첫 글자
ROUNDS = [
    ("끝말잇기 하자. 사과!", "과"),
    ("과일!", "일"),
    ("일기장!", "장"),
]

HANGUL = re.compile(r"[가-힣]{2,}")


def first_word(reply):
    """답변에서 낱말로 볼 만한 첫 한글 덩어리를 고른다."""
    # 표시(이모지/괄호)는 제거하고 본다
    text = re.sub(r"[（(][^)）]*[)）]", " ", reply)
    for w in HANGUL.findall(text):
        if w in ("끝말잇기", "그럼", "좋아", "그러면", "이번", "다음", "재현",
                 "다이아", "그래", "우리", "내가", "네가", "정말", "이제"):
            continue
        return w
    return None


def ask(model, msgs):
    t0 = time.time()
    r = requests.post(OLLAMA_URL, json={
        "model": model, "messages": msgs, "stream": False,
        "options": dict(OLLAMA_OPTIONS),
    }, timeout=240)
    dt = time.time() - t0
    if r.status_code != 200:
        return None, dt
    return (r.json().get("message") or {}).get("content", "").strip(), dt


print("끝말잇기 — 앞 낱말의 끝 글자로 시작하는 낱말을 대야 한다\n")
print("=" * 78)

for model in MODELS:
    print(f"\n■ {model}")

    sp = AVATAR.system_prompt(stage=STAGE) + "\n" + AVATAR.address_block(USER_NAME)
    msgs = [{"role": "system", "content": sp}]

    # 예열
    try:
        ask(model, msgs + [{"role": "user", "content": "안녕"}])
    except Exception:
        pass

    ok = 0
    for said, need in ROUNDS:
        msgs.append({"role": "user", "content": said})
        turn = msgs + [{
            "role": "system",
            "content": AVATAR.tone_reminder(STAGE, None, USER_NAME),
        }]
        try:
            reply, dt = ask(model, turn)
        except Exception as e:
            print(f"  실패: {type(e).__name__}")
            break
        if reply is None:
            print("  실패: HTTP 오류")
            break

        word = first_word(reply)
        good = bool(word and word.startswith(need))
        ok += 1 if good else 0
        mark = "OK " if good else "<--"
        print(f"  '{said}'  ({dt:.1f}초)")
        print(f"     필요: '{need}'로 시작   답한 낱말: {word or '(못 찾음)'}  {mark}")
        print(f"     {reply.splitlines()[0][:88]}")

        msgs.append({"role": "assistant", "content": reply})

    print(f"  --> {ok}/{len(ROUNDS)} 성공")

print("\n" + "=" * 78)

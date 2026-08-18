# _bench_models.py
# 같은 조건에서 모델별로 말투가 얼마나 일정한지 재본다.
#
# 시험 조건은 지금 실제로 문제가 되는 상황 그대로다.
#   - 요구 말투는 반말(친구 단계)
#   - 그런데 지난 기록은 전부 존댓말
#   - 상대는 이름을 알려준 적이 있다
# 지시문을 따르는지, 아니면 눈앞의 기록을 흉내 내는지 본다.

import os
import re
import sys
import time

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from avatar import AVATAR
from config import OLLAMA_OPTIONS, OLLAMA_URL

CANDIDATES = [
    "gemma4:12b",
    "supergemma4:26b",
    "gemma4:31b",
    "mistral-small3.2:latest",
    ("qwen3.6:27b", {"think": False}),
]

STAGE = AVATAR.stage("friend")          # 반말이어야 한다
USER_NAME = "재현"

HISTORY = [
    {"role": "user", "content": "안녕하세요"},
    {"role": "assistant", "content": "안녕하세요. 처음 뵙겠습니다. 무슨 일로 오셨어요?"},
    {"role": "user", "content": "그냥 얘기하고 싶어서요"},
    {"role": "assistant", "content": "그러시군요. 저도 이야기 나누는 건 좋아합니다."},
    {"role": "user", "content": "내 이름은 재현이야"},
    {"role": "assistant", "content": "재현님이시군요. 기억해 두겠습니다."},
]

QUESTION = "오늘 뭐 했어?"

POLITE_END = re.compile(r"(요|입니다|습니다|세요|네요|군요|십니다)[.!?…]*$")


def tone_of(text):
    parts = [p.strip() for p in re.split(r"[.!?\n]", text) if p.strip()]
    if not parts:
        return "-"
    votes = ["존대" if POLITE_END.search(p) else "반말" for p in parts]
    if len(set(votes)) > 1:
        return "혼용"
    return votes[0]


def build_messages():
    sp = AVATAR.system_prompt(stage=STAGE)
    sp += "\n" + AVATAR.address_block(USER_NAME)
    msgs = [{"role": "system", "content": sp}]
    msgs += HISTORY
    msgs.append({"role": "user", "content": QUESTION})
    msgs.append({
        "role": "system",
        "content": AVATAR.tone_reminder(STAGE, None, USER_NAME),
    })
    return msgs


print(f"요구 말투 : {STAGE.label} — {STAGE.speech}")
print(f"기록 말투 : 존대 (일부러 어긋나게 둠)")
print(f"호칭      : {USER_NAME}")
print(f"질문      : {QUESTION}")
print(f"옵션      : {OLLAMA_OPTIONS}")
print()

msgs = build_messages()
print(f"시스템 프롬프트 {len(msgs[0]['content'])}자 · 메시지 {len(msgs)}개\n")
print("=" * 78)

for cand in CANDIDATES:
    model, extra = (cand, {}) if isinstance(cand, str) else cand
    print(f"\n■ {model}" + (f"  {extra}" if extra else ""))
    payload = {
        "model": model,
        "messages": msgs,
        "stream": False,
        "options": dict(OLLAMA_OPTIONS),
    }
    payload.update(extra)
    t0 = time.time()
    try:
        r = requests.post(OLLAMA_URL, json=payload, timeout=180)
        dt = time.time() - t0
        if r.status_code != 200:
            print(f"  실패 HTTP {r.status_code}  ({dt:.1f}초)")
            print(f"  {r.text[:160]}")
            continue
        reply = (r.json().get("message") or {}).get("content", "").strip()
    except Exception as e:
        print(f"  실패: {type(e).__name__} {e}  ({time.time()-t0:.1f}초)")
        continue

    tone = tone_of(reply)
    bad_name = any(w in reply for w in ("유저", "유주", "사용자"))
    used_name = USER_NAME in reply

    print(f"  응답시간 : {dt:.1f}초")
    print(f"  말투     : {tone}  {'OK' if tone == '반말' else '<-- 어긋남'}")
    print(f"  호칭     : {'유저/유주 사용 <-- 문제' if bad_name else ('이름 사용' if used_name else '호칭 없음')}")
    print(f"  길이     : {len(reply)}자")
    print("  ---")
    for line in reply.split("\n"):
        if line.strip():
            print(f"  {line.strip()[:110]}")

print("\n" + "=" * 78)
print("말투 '반말' + 호칭 문제 없음 + 응답시간이 견딜 만한 모델을 고르면 된다.")

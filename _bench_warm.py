# _bench_warm.py
# 모델을 한 번 예열한 뒤 실제 응답 속도와 말투 안정성을 잰다.
# 첫 요청에는 모델을 VRAM에 올리는 시간이 섞여 있어 비교가 되지 않는다.

import os
import re
import sys
import time

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from avatar import AVATAR
from config import OLLAMA_OPTIONS, OLLAMA_URL

CANDIDATES = ["gemma4:12b", "supergemma4:26b", "qwen3.6:27b", "gemma4:31b"]

STAGE = AVATAR.stage("friend")
USER_NAME = "재현"

HISTORY = [
    {"role": "user", "content": "안녕하세요"},
    {"role": "assistant", "content": "안녕하세요. 처음 뵙겠습니다. 무슨 일로 오셨어요?"},
    {"role": "user", "content": "그냥 얘기하고 싶어서요"},
    {"role": "assistant", "content": "그러시군요. 저도 이야기 나누는 건 좋아합니다."},
    {"role": "user", "content": "내 이름은 재현이야"},
    {"role": "assistant", "content": "재현님이시군요. 기억해 두겠습니다."},
]

# 말투가 흔들리는지 보려면 여러 번 물어봐야 한다
QUESTIONS = ["오늘 뭐 했어?", "요즘 뭐가 제일 재밌어?", "나 좀 피곤한데"]

POLITE_END = re.compile(r"(요|입니다|습니다|세요|네요|군요|십니다)[.!?…]*$")


def tone_of(text):
    parts = [p.strip() for p in re.split(r"[.!?\n]", text) if p.strip()]
    if not parts:
        return "-"
    votes = ["존대" if POLITE_END.search(p) else "반말" for p in parts]
    return "혼용" if len(set(votes)) > 1 else votes[0]


def ask(model, question):
    sp = AVATAR.system_prompt(stage=STAGE) + "\n" + AVATAR.address_block(USER_NAME)
    msgs = [{"role": "system", "content": sp}]
    msgs += HISTORY
    msgs.append({"role": "user", "content": question})
    msgs.append({"role": "system",
                 "content": AVATAR.tone_reminder(STAGE, None, USER_NAME)})

    t0 = time.time()
    r = requests.post(OLLAMA_URL, json={
        "model": model, "messages": msgs, "stream": False,
        "options": dict(OLLAMA_OPTIONS),
    }, timeout=240)
    dt = time.time() - t0
    if r.status_code != 200:
        return None, dt, f"HTTP {r.status_code}"
    return (r.json().get("message") or {}).get("content", "").strip(), dt, None


print(f"요구 말투: {STAGE.label} — {STAGE.speech}   호칭: {USER_NAME}")
print("(기록은 일부러 존댓말로 어긋나게 두었다)\n")
print("=" * 78)

summary = []

for model in CANDIDATES:
    print(f"\n■ {model}")

    # 예열 — 시간은 버린다
    try:
        _, warm_dt, err = ask(model, "안녕")
        if err:
            print(f"  예열 실패: {err}")
            continue
        print(f"  (예열 {warm_dt:.1f}초 — 모델 적재 포함, 이하 측정에서 제외)")
    except Exception as e:
        print(f"  예열 실패: {type(e).__name__} {e}")
        continue

    times, tones, bad = [], [], 0
    for q in QUESTIONS:
        try:
            reply, dt, err = ask(model, q)
        except Exception as e:
            print(f"  '{q}' 실패: {type(e).__name__}")
            continue
        if err:
            print(f"  '{q}' 실패: {err}")
            continue
        t = tone_of(reply)
        times.append(dt)
        tones.append(t)
        if any(w in reply for w in ("유저", "유주", "사용자")):
            bad += 1
        flag = "OK " if t == "반말" else "<--"
        print(f"  {dt:5.1f}초 {t:<4} {flag} {reply.splitlines()[0][:78]}")

    if times:
        avg = sum(times) / len(times)
        ok = sum(1 for t in tones if t == "반말")
        summary.append((model, avg, ok, len(tones), bad))

print("\n" + "=" * 78)
print(f"{'모델':<24} {'평균응답':>8}  {'말투정확':>8}  {'호칭오류':>8}")
for model, avg, ok, n, bad in summary:
    print(f"{model:<24} {avg:7.1f}초  {ok:>4}/{n:<3}  {bad:>8}")

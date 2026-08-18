# _diagnose.py
# 말투와 맥락이 흔들리는 원인을 짚어본다.

import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from avatar import AVATAR
from config import OLLAMA_MODEL, OLLAMA_URL

HERE = os.path.dirname(os.path.abspath(__file__))

POLITE = re.compile(r"(요|입니다|습니다|세요|시죠|십시오|네요|군요)[.!?…]*$")


def tone_of(text):
    t = (text or "").strip()
    if not t:
        return "-"
    # 문장 단위로 보고 마지막 문장의 어미로 판정
    parts = [p for p in re.split(r"[.!?\n]", t) if p.strip()]
    if not parts:
        return "-"
    votes = ["존대" if POLITE.search(p.strip()) else "반말" for p in parts]
    if len(set(votes)) > 1:
        return "혼용"
    return votes[0]


data = json.load(open(os.path.join(HERE, "memory_store.json"), encoding="utf-8"))
conv = data.get("conversation", []) if isinstance(data, dict) else data
rel = data.get("relationship", {}) if isinstance(data, dict) else {}

print("[1] 기억에 남아 있는 대화")
print(f"  총 {len(conv)}개 · 관계 상태 {rel or '(없음)'}")

ai = [m for m in conv if m.get("role") == "assistant"]
tones = [tone_of(m.get("content", "")) for m in ai]
from collections import Counter
print(f"  다이아 답변 {len(ai)}개의 말투: {dict(Counter(tones))}")

print("\n  최근 12개")
for m in conv[-12:]:
    c = (m.get("content") or "").replace("\n", " ")
    role = m.get("role", "?")
    mark = tone_of(c) if role == "assistant" else ""
    print(f"    {role:<9} {mark:<4} {c[:56]}")

stage_now = AVATAR.next_stage(
    rel.get("affinity", 0), rel.get("stage")
)
print(f"\n  지금 요구되는 말투: {stage_now.label} — {stage_now.speech}")

mismatch = sum(
    1 for t in tones
    if t != "-" and (
        (stage_now.speech.startswith("존댓말") and t == "반말")
        or (stage_now.speech.startswith("반말") and t == "존대")
    )
)
print(f"  요구 말투와 어긋나는 과거 답변: {mismatch}개 / {len(ai)}개")
if mismatch:
    print("  → 이 답변들이 매 요청마다 모델에게 예시로 함께 전달된다.")
    print("     작은 모델일수록 지시문보다 바로 앞의 대화를 흉내 낸다.")

print("\n[2] 모델에 보내는 요청")
print(f"  모델   : {OLLAMA_MODEL}")
print(f"  주소   : {OLLAMA_URL}")

src = open(os.path.join(HERE, "ai_brain.py"), encoding="utf-8").read()
has_options = '"options"' in src or "'options'" in src
print(f"  옵션   : {'있음' if has_options else '없음 — temperature/top_p 등이 서버 기본값'}")
if not has_options:
    print("     Ollama 기본 temperature 는 0.8 로 높은 편이라 문장이 매번 달라진다.")

trimmed = "history[-" in src or "MAX_TURNS" in src
print(f"  기록   : {'일부만 전송' if trimmed else '전체 전송 — 오래된 말투까지 그대로 따라간다'}")

prompt = AVATAR.system_prompt(stage=stage_now)
idx = prompt.find("[지금 이 사람과의 사이]")
print(f"\n[3] 프롬프트에서 말투 지시의 위치")
print(f"  전체 {len(prompt)}자 중 {idx}자 지점 "
      f"({idx * 100 // max(1, len(prompt))}% 지점)")
print("  작은 모델은 프롬프트 뒤쪽을 더 강하게 따른다. 앞이나 중간에 있으면 묻힌다.")

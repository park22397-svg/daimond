# _verify_relationship.py
# 관계 단계 · 이력 현상 · 점수 판정을 눈으로 확인하는 점검 스크립트.

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from avatar import AVATAR as A

fails = 0

print("[1] 단계 정의")
for s in A.stages():
    print(f"  {s.min_affinity:>4} 이상  {s.key:<9} {s.label:<8} {s.speech}")

print("\n[2] 친밀도 -> 단계")
for aff in [-100, -70, -40, -25, -10, 0, 19, 20, 55, 60, 100]:
    print(f"  {aff:>5} -> {A.stage_for_affinity(aff).label}")

print("\n[3] 이력 현상 — 경계에서 말투가 뒤집히지 않는가")
print("  친구(20 이상) 상태에서 친밀도가 내려갈 때:")
for aff in [20, 19, 15, 12, 11, 10, 5]:
    st = A.next_stage(aff, "friend")
    note = "유지" if st.key == "friend" else "→ " + st.label
    print(f"    {aff:>4} : {st.label:<8} {note}")

print("  서먹함(-10 이상) 상태에서 친밀도가 올라갈 때:")
for aff in [19, 20, 25, 27, 28, 30]:
    st = A.next_stage(aff, "distant")
    note = "유지" if st.key == "distant" else "→ " + st.label
    print(f"    {aff:>4} : {st.label:<8} {note}")

# 경계에서 한 칸 왔다갔다 해도 단계가 흔들리면 안 된다
a = A.next_stage(19, "friend").key
b = A.next_stage(21, "distant").key
if a != "friend":
    fails += 1
    print("  FAIL  19에서 친구가 바로 풀렸다")
if b != "distant":
    fails += 1
    print("  FAIL  21에서 서먹함이 바로 친구가 됐다")
if a == "friend" and b == "distant":
    print("  PASS  경계 ±1 에서는 단계가 바뀌지 않는다")

print("\n[4] 말 한마디의 점수")
cases = [
    "안녕하세요",
    "오늘 날씨 어때",
    "고마워 정말 좋아",
    "짜증나",
    "닥쳐 꺼져 바보",
    "미안해 아까는 내가 심했어",
]
for t in cases:
    print(f"  {A.score_message(t):>+4}  {t}")

step_cap = A.relationship["scoring"]["max_step"]
worst = A.score_message("닥쳐 꺼져 바보 멍청이 싫어 짜증나 관심없어 그만해")
if abs(worst) > step_cap:
    fails += 1
    print(f"  FAIL  한 번에 {worst} 만큼 움직였다 (상한 {step_cap})")
else:
    print(f"  PASS  최악의 문장도 {worst} 로 상한({step_cap}) 안에 있다")

print("\n[5] 관계를 반영한 프롬프트")
for key in ["distant", "friend", "hostile"]:
    st = A.stage(key)
    p = A.system_prompt(stage=st)
    line = [l for l in p.split("\n") if l.startswith("말투:")]
    print(f"  {st.label:<10} {len(p)}자   {line[0] if line else ''}")

trans = A.system_prompt(stage=A.stage("friend"), transition="서먹함")
print(f"  전환 안내 포함    {len(trans)}자 (+{len(trans) - len(A.system_prompt(stage=A.stage('friend')))})")

print("\n[6] 화면에 보이지 않는 표시 안내")
print("  " + A.cue_guide().replace("\n", "\n  "))

print("\n" + ("전부 통과" if fails == 0 else f"{fails}건 실패"))
sys.exit(0 if fails == 0 else 1)

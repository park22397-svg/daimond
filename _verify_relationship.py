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

# 숫자를 여기 적지 않는다.
#
# 예전에는 친구 진입선을 20으로 적어 두었는데, 2026-08-18 에 호감
# 눈금을 두 배로 올리면서(친구 40) 이 검사만 옛 숫자에 남아 실패했다.
# 눈금이 달라질 때마다 검사도 같이 고쳐야 한다면 그건 검사가 아니다.
# 그래서 경계와 이력현상을 개체에서 직접 꺼내 쓴다.
LINE = A.stage("friend").min_affinity
HYST = A.relationship.get("hysteresis", 0)

print("\n[2] 친밀도 -> 단계")

# 단계마다 진입선과 그 한 칸 아래를 본다.
# 눈금이 달라져도 늘 '갈리는 자리'를 짚는다.
edges = []
for s in A.stages():
    edges += [s.min_affinity - 1, s.min_affinity]

for aff in sorted(set(edges)):
    print(f"  {aff:>5} -> {A.stage_for_affinity(aff).label}")

print("\n[3] 이력 현상 — 경계에서 말투가 뒤집히지 않는가")
print(f"  친구 진입선 {LINE} · 이력현상 {HYST}")
print(f"  친구가 되는 것은 {LINE} 에서 바로,")
print(f"  친구가 풀리는 것은 {LINE - HYST} 아래로 떨어져야 한다")
print(f"  (이력현상은 나가는 쪽에만 건다. 들어가는 쪽에도 걸면"
      f" 표의 {LINE} 이 거짓말이 된다)")

print("\n  친구 상태에서 친밀도가 내려갈 때:")
for aff in [LINE, LINE - 1, LINE - HYST + 1, LINE - HYST, LINE - HYST - 1]:
    st = A.next_stage(aff, "friend")
    note = "유지" if st.key == "friend" else "→ " + st.label
    print(f"    {aff:>4} : {st.label:<8} {note}")

print("\n  서먹함 상태에서 친밀도가 올라갈 때:")
for aff in [LINE - HYST, LINE - 1, LINE, LINE + 1, LINE + HYST]:
    st = A.next_stage(aff, "distant")
    note = "유지" if st.key == "distant" else "→ " + st.label
    print(f"    {aff:>4} : {st.label:<8} {note}")

# 경계에서 한 칸 왔다갔다 해도 단계가 흔들리면 안 된다.
#
# 다만 ±1 만 보면 '아예 안 바뀌는' 버그를 못 잡는다.
# 그래서 이력현상이 정확히 그 폭만큼인지도 같이 본다.
checks = [
    # 들어가는 쪽 — 시작선에서 바로, 그 한 칸 아래에서는 아직
    (LINE, "distant", "friend",
     f"{LINE}에 닿았는데 친구가 안 됐다 — 표의 숫자가 거짓말이 된다"),
    (LINE - 1, "distant", "distant",
     f"{LINE - 1}에서 벌써 친구가 됐다 — 시작선보다 이르다"),

    # 나가는 쪽 — 이력현상만큼 떨어져야 풀린다
    (LINE - 1, "friend", "friend",
     f"{LINE - 1}에서 친구가 바로 풀렸다"),
    (LINE - HYST, "friend", "friend",
     f"{LINE - HYST}에서 친구가 풀렸다 — 이력현상이 {HYST}보다 좁다"),
    (LINE - HYST - 1, "friend", "distant",
     f"{LINE - HYST - 1}까지 내려가도 친구다 — 이력현상이 {HYST}보다 넓다"),
]

bad = 0
for aff, came_from, want, msg in checks:
    got = A.next_stage(aff, came_from).key
    if got != want:
        bad += 1
        print(f"  FAIL  {msg} (실제로는 {got})")

fails += bad

if not bad:
    print(f"\n  PASS  {LINE} 에서 바로 친구가 되고, "
          f"{LINE - HYST} 아래로 떨어져야 풀린다")

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

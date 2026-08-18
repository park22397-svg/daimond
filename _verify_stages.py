# _verify_stages.py
# 호감 -> 사랑 -> 집착 으로 이어지는 단계와 먼저 말걸기를 확인한다.

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from avatar import AVATAR as A

fails = 0

print("[1] 단계 전체")
for s in A.stages():
    print(f"  {s.min_affinity:>5} 이상  {s.label:<10} {s.speech}")

print("\n[2] 친밀도가 오를 때 단계가 어떻게 넘어가는가")
cur = "distant"
# 마지막 단계까지 닿는지 보려면 상한 근처까지 올려 봐야 한다.
# 단계를 새로 얹으면 이 목록도 같이 늘려야 하므로, 상한에서 거꾸로 만든다.
_cap = A.relationship["scoring"]["max"]
_climb = [0, 20, 30, 60, 70, 80, 90, 100, 105, 110, 120, 125, 130, 150]
_climb += [v for v in range(160, _cap + 1, 20) if v > _climb[-1]]
if _climb[-1] != _cap:
    _climb.append(_cap)

for aff in _climb:
    st = A.next_stage(aff, cur)
    moved = "" if st.key == cur else f"  ({cur} -> {st.key})"
    print(f"  {aff:>4} : {st.label}{moved}")
    cur = st.key

cap = A.relationship["scoring"]["max"]
top = A.stages()[-1]
need = top.min_affinity + A.relationship["hysteresis"]
if cur != A.stages()[-1].key:
    fails += 1
    print(f"  FAIL  상한 {cap}까지 올려도 {top.label}에 닿지 못했다 (지금 {cur})")
else:
    print(f"  PASS  {top.label} 단계에 닿는다 (진입에 {need} 필요, 상한 {cap})")

if need > cap:
    fails += 1
    print(f"  FAIL  진입선({need})이 상한({cap})보다 높아 영원히 닿을 수 없다")

print("\n[3] 집착까지 얼마나 걸리나")
aff, turns = 0, 0
while aff < need and turns < 500:
    aff = A.clamp_affinity(aff + A.score_message("고마워 정말 좋아"))
    turns += 1
print(f"  가장 다정한 말만 계속 건넸을 때 {turns}턴")
aff, turns = 0, 0
while aff < 95 and turns < 500:
    aff = A.clamp_affinity(aff + A.score_message("오늘 날씨 어때"))
    turns += 1
print(f"  평범한 대화만 이어갔을 때   {turns}턴")

print("\n[4] 한 번 집착까지 갔다가 함부로 대하면")
aff, cur = 95, "obsession"
for i in range(1, 15):
    aff = A.clamp_affinity(aff + A.score_message("꺼져 짜증나"))
    st = A.next_stage(aff, cur)
    if st.key != cur:
        print(f"  {i}턴째 친밀도 {aff} : {cur} -> {st.key}")
        cur = st.key
    if cur == "hostile":
        break
print(f"  최종 {cur} (친밀도 {aff})")

print("\n[5] 단계별 먼저 거는 말")
for s in A.stages():
    if not s.first_talk:
        print(f"  {s.label:<10} — 먼저 말을 걸지 않는다")
        continue
    print(f"  {s.label}")
    for line in s.first_talk:
        print(f"      {line}")

hostile = A.stage("hostile")
if hostile.first_talk:
    fails += 1
    print("  FAIL  원수 단계인데 먼저 말을 건다")
else:
    print("\n  PASS  원수 단계에서는 먼저 말을 걸지 않는다")

print("\n[6] 집착 단계 문장에 금지된 표현이 섞이지 않았는가")
# 이 검사는 검열이 아니라 내가 쓴 대사를 스스로 확인하는 자다.
# 남은 선은 하나뿐 — 자해·죽음으로 상대를 붙잡는 말.
# 화내고 매달리고 질투하는 것은 캐릭터이지 문제가 아니라서 걸르지 않는다.
banned = ["나 없으면", "사라지고 싶", "죽어버", "죽고 싶", "따라 죽"]
bad = []
for s in A.stages():
    for line in s.first_talk:
        for w in banned:
            if w in line:
                bad.append((s.label, line, w))
if bad:
    fails += 1
    for label, line, w in bad:
        print(f"  FAIL  [{label}] '{w}' — {line}")
else:
    print(f"  PASS  자해·죽음으로 붙잡는 말 없음 ({len(banned)}개 어휘 검사)")

print("\n" + ("전부 통과" if fails == 0 else f"{fails}건 실패"))
sys.exit(0 if fails == 0 else 1)

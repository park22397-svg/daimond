# _verify_bond.py
# 사이가 제대로 서 있는가.
#
# 2026-09-16 에 관계를 열 단계에서 **둘**로 줄였다(친구·연인).
# 옛 검사 셋(_verify_stages / _verify_relationship / _verify_friend)은
# 없어진 단계를 재고 있어서 이것으로 갈음한다.
#
# 여기서 잡으려는 것
#   1. 단계가 둘뿐이고, 호감만으로는 연인이 되지 않는가
#   2. 호감이 바닥나도 친구 아래로 안 내려가는가 (온도만 바뀐다)
#   3. 고백 — 받는 선, 다이아가 먼저 꺼내는 선
#   4. 이별 — 말로도 끝나고, 호감이 바닥나도 끝나는가
#   5. 지운 것이 정말로 없어졌는가 (순종·아이·절정·당기기)

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from avatar import AVATAR

fails = []


def ok(cond, what, detail=""):
    if cond:
        print("  PASS  " + what)
    else:
        print("  FAIL  " + what + ("  -- " + str(detail) if detail else ""))
        fails.append(what)


print("1. 단계")

keys = [s.key for s in AVATAR.stages()]
ok(keys == ["friend", "lover"], "친구와 연인 둘뿐이다", keys)

for s in AVATAR.stages():
    ok(str(s.speech).startswith("반말"),
       f"{s.label} 은 반말이다", s.speech[:20])
    ok(bool(s.first_talk), f"{s.label} 에 먼저 거는 말이 있다")
    ok(not getattr(s, "silent", False), f"{s.label} 은 입을 닫지 않는다")
    ok(not getattr(s, "never_falls", False), f"{s.label} 은 식을 수 있다")


print("\n2. 호감만으로는 연인이 안 된다")

no_lover = {"lover": False}
yes_lover = {"lover": True}

for aff in (-200, -100, 0, 120, 300, 400):
    st = AVATAR.stage_for_affinity(aff, no_lover)
    ok(st.key == "friend", f"호감 {aff} · 고백 전에는 친구다", st.key)

ok(AVATAR.stage_for_affinity(200, yes_lover).key == "lover",
   "고백을 주고받으면 연인이다")


print("\n3. 온도 (친구인 채로 달라지는 것)")

seen = []
for aff in (-200, -100, -50, 0, 60, 150, 300):
    tier = AVATAR.warmth_tier(aff)
    note = AVATAR.mood_note(aff)
    ok(tier is not None and bool(note),
       f"호감 {aff} 에 온도가 있다 ({tier['label'] if tier else '?'})")
    seen.append(tier["label"] if tier else None)

ok(len(set(seen)) >= 3, "호감에 따라 온도가 실제로 달라진다", seen)

# 낮은 쪽이 시무룩해야 한다
low = AVATAR.warmth_tier(-150)
ok("시무룩" in (low or {}).get("label", ""),
   "바닥에서는 시무룩하다", (low or {}).get("label"))


print("\n4. 고백")

accept = AVATAR.confess_accept_from()
ask = AVATAR.confess_ask_from()

ok(accept > 0, f"받아들이는 선이 있다 ({accept})")
ok(ask > accept, f"먼저 꺼내는 선이 더 높다 ({ask} > {accept})",
   "기다려 보고 안 하면 제가 꺼낸다")

ok(not AVATAR.confess_accepts(accept - 1), "선 아래에서는 거절한다")
ok(AVATAR.confess_accepts(accept), "선에 닿으면 받아들인다")

ok(not AVATAR.confess_asks(ask - 1, no_lover), "선 아래에서는 안 꺼낸다")
ok(AVATAR.confess_asks(ask, no_lover), "선을 넘으면 먼저 꺼낸다")
ok(not AVATAR.confess_asks(400, yes_lover), "이미 연인이면 안 꺼낸다")

ok(bool(AVATAR.confess_ask().get("line")), "먼저 꺼낼 말이 있다")
ok(AVATAR.is_confession("우리 사귀자"), "사귀자는 말을 알아듣는다")
ok(not AVATAR.is_confession("오늘 뭐 했어"), "아무 말이나 고백으로 안 본다")

# 천장이 -1 로 잡히면 호감이 통째로 눌린다. 한 번 그랬다.
ceil = AVATAR.confess_ceiling()
ok(ceil is None or ceil > 0,
   "고백 전 천장이 호감을 깔아뭉개지 않는다", ceil)
ok(AVATAR.clamp_affinity(300, lover=False) == 300,
   "연인이 아니어도 호감이 오른다")


print("\n5. 이별")

ok(AVATAR.is_breakup("우리 헤어지자"), "헤어지자는 말을 알아듣는다")
ok(not AVATAR.is_breakup("오늘 뭐 했어"), "아무 말이나 이별로 안 본다")

r = AVATAR.breakup_reply(True, "said")
ok(bool(r["line"]) and r["broke"], "연인이면 헤어진다", r["line"])
ok(r["affinity"] <= 0, "헤어지면 호감이 깎인다", r["affinity"])

r2 = AVATAR.breakup_reply(False, "said")
ok(not r2["broke"], "연인이 아니면 헤어질 것도 없다")

below = AVATAR.breakup_below()
ok(below is not None, f"저절로 끝나는 선이 있다 ({below})")
ok(AVATAR.breakup_faded(below - 1, True), "그 아래로 떨어지면 저절로 끝난다")
ok(not AVATAR.breakup_faded(below + 1, True), "그 위에서는 안 끝난다")
ok(not AVATAR.breakup_faded(-999, False), "친구는 헤어질 일이 없다")

# 헤어진 뒤에도 친구로는 남는다
after = AVATAR.stage_for_affinity(below - 1, no_lover)
ok(after.key == "friend", "헤어져도 친구로 남는다", after.key)


print("\n6. 지운 것이 정말 없는가")

gone_attr = ["devotion_overflow", "devotion_level", "devotion_tier",
             "child_conf", "child_reply", "is_child_talk",
             "befriend_conf", "befriend_accepts", "befriend_ask",
             "speaking_stage", "sex_conf", "climax_reaction"]

for name in gone_attr:
    ok(not hasattr(AVATAR, name), f"{name} 이 없다")

gone_conf = ["devotion", "child", "befriend", "silence"]
for name in gone_conf:
    ok(name not in AVATAR.relationship, f"관계표에 {name} 이 없다")

ok("sex" not in AVATAR.touch, "만지기에 몸섞기가 없다")
ok("cloth_tug" not in AVATAR.touch, "만지기에 당기기가 없다")
ok(not AVATAR.pregnancy, "임신 설정이 비었다")

zones = [z.key for z in AVATAR.touch_zones()]
ok("pelvis" not in zones, "감춰 둔 자리가 없다", zones)

# 벗기기와 만지기 문턱은 남긴 것이다
ok(AVATAR.touch.get("undress", {}).get("enabled"), "벗기기는 남아 있다")
ok(any(z.allow_from for z in AVATAR.touch_zones() if z.allow_from),
   "만지기 문턱은 남아 있다")

print("\n" + "=" * 60)
if fails:
    print(f"{len(fails)}건 실패")
    for f in fails:
        print("   - " + f)
    sys.exit(1)

print("전부 통과")

# _verify_touch.py
# 만지기 기능이 빠짐없이 이어져 있는지 확인한다.
#
# 판정구는 있는데 그 본이 어느 자리에도 속하지 않으면,
# 그 부분을 눌렀을 때 아무 반응 없이 조용히 무시된다.
# 그런 '죽은 자리'를 찾는 것이 이 검사의 목적이다.

import sys

import numpy as np

import _fit_pose as F
from avatar import AVATAR

rig = F.Rig("static/avatar.vrm")


def main():
    touch = AVATAR.touch
    boxes = touch.get("hitboxes", [])
    zones = AVATAR.touch_zones()

    bad = 0

    print(f"판정구 {len(boxes)}개 · 자리 {len(zones)}개\n")

    # 1) 모든 판정구가 어느 자리엔가 속하는가
    print("[1] 누르면 반응이 나오는가")
    dead = []
    for b in sorted({h["bone"] for h in boxes}):
        z = AVATAR.zone_for(b, [0, 0, 0])
        if z is None:
            dead.append(b)
        else:
            print(f"  PASS  {b:16} -> {z.label}")

    for b in dead:
        print(f"  FAIL  {b:16} -> 속한 자리가 없다. 눌러도 아무 반응이 없다")
        bad += 1

    # 2) 머리 나누기
    print("\n[2] 머리와 얼굴이 갈리는가")
    cut = touch.get("head_split", {})
    cases = [
        ("정수리", [0, cut.get("top_y", 0.13) + 0.03, 0], "머리"),
        ("얼굴 앞", [0, 0.05, cut.get("front_z", -0.02) - 0.05], "얼굴"),
        ("뒤통수", [0, 0.05, 0.05], "머리"),
    ]
    for name, local, want in cases:
        z = AVATAR.zone_for("head", local)
        got = z.label if z else "(없음)"
        ok = got == want
        print(f"  {'PASS' if ok else 'FAIL'}  {name:8} -> {got}")
        if not ok:
            bad += 1

    # 3) 자리마다 반응이 다 채워져 있는가
    print("\n[3] 자리마다 할 말과 표정이 있는가")
    for z in zones:
        problems = []
        for kind, spec in (("tap", z.tap), ("pet", z.pet)):
            if not spec:
                problems.append(f"{kind} 없음")
                continue
            # 말 없는 자리는 대사가 없는 것이 정상이다
            if not getattr(z, "silent", False):
                for tone in ("polite", "casual"):
                    if not (spec.get("lines", {}).get(tone)):
                        problems.append(f"{kind}.{tone} 대사 없음")
            if spec.get("motion") and AVATAR.motion(spec["motion"]) is None:
                problems.append(f"{kind} 동작 '{spec['motion']}' 이 없다")
            # 표정은 하나만 적을 수도, 여럿 중 고르게 둘 수도 있다.
            # 사이가 깊을 때와 이어지는 얼굴도 함께 본다.
            for field in ("expression", "expression_warm",
                          "expression_then"):
                want = spec.get(field)
                if not want:
                    continue
                many = want if isinstance(want, (list, tuple)) else [want]
                for key in many:
                    if AVATAR.expression(key) is None:
                        problems.append(
                            f"{kind}.{field} 표정 '{key}' 이 없다")

        if z.allow_from is not None and not z.deny:
            problems.append("허락 조건은 있는데 거부 반응이 없다")

        if problems:
            print(f"  FAIL  {z.key:9} {', '.join(problems)}")
            bad += 1
        else:
            gate = "누구나" if z.allow_from is None else f"친밀도 {z.allow_from}+"
            print(f"  PASS  {z.key:9} {z.label:6} {gate}")

    # 4) 친밀도에 따라 허락이 실제로 갈리는가
    print("\n[4] 사이가 깊어질수록 만질 수 있는 곳이 느는가")
    for aff in (-20, 0, 30, 70, 90, 120):
        stage = AVATAR.stage_for_affinity(aff)
        ok = [z.label for z in zones
              if z.allow_from is None or aff >= z.allow_from]
        print(f"  친밀도 {aff:4} ({stage.label:5}) : {', '.join(ok)}")

    # 5) 판정구가 몸에서 벗어나지 않았는가
    print("\n[5] 판정구가 몸 위에 놓였는가")
    base = AVATAR.base_pose
    ys = []
    for h in boxes:
        M = rig.world(h["bone"], base)
        ys.append(float((M @ np.append(h["offset"], 1.0))[1]))
    head_y = float(rig.pos("head", base)[1])
    lo, hi = min(ys), max(ys)
    ok = (-0.05 <= lo) and (hi <= head_y + 0.35)
    print(f"  {'PASS' if ok else 'FAIL'}  높이 {lo:.3f} ~ {hi:.3f} m "
          f"(머리 {head_y:.3f} m)")
    if not ok:
        bad += 1

    # 6) 도구
    print("\n[6] 무엇으로 만질지 고를 수 있는가")
    tools = AVATAR.touch_tools()
    if not tools:
        print("  FAIL  도구가 하나도 없다")
        bad += 1

    for t in tools:
        problems = []

        if not t.lines.get("default") and t.key != "hand":
            problems.append("기본 대사가 없다")

        for zk, spec in t.lines.items():
            for tone in ("polite", "casual"):
                if not spec.get(tone):
                    problems.append(f"{zk}.{tone} 없음")

        if t.allow_bonus > 0 and not t.deny:
            problems.append("허락 조건은 있는데 거절할 말이 없다")

        if t.motion and AVATAR.motion(t.motion) is None:
            problems.append(f"동작 '{t.motion}' 이 없다")

        if t.expression and AVATAR.expression(t.expression) is None:
            problems.append(f"표정 '{t.expression}' 이 없다")

        if problems:
            print(f"  FAIL  {t.key:9} {', '.join(problems)}")
            bad += 1
        else:
            print(f"  PASS  {t.icon} {t.key:9} {t.label:5} "
                  f"허락+{t.allow_bonus:<3} 친밀도x{t.affinity_scale}")

    # 7) 자리 x 도구 를 전부 돌려 본다
    print("\n[7] 자리와 도구를 모두 곱해 반응이 나오는가")
    stage = AVATAR.stage_for_affinity(120)
    missing = 0
    for z in zones:
        # 말 없는 자리는 대사가 없는 것이 정상이다.
        # 얼굴로만 답하기로 한 자리라, 비었다고 나무랄 것이 아니다.
        if getattr(z, "silent", False):
            print(f"  건너뜀  {z.key} — 말 없는 자리")
            continue

        for t in tools:
            for kind in ("tap", "pet"):
                r = AVATAR.touch_reaction(z, kind, stage, 120, tool=t)

                # 이름을 내지 않는 자리는 거절할 때 말이 없어도 된다.
                # 얼굴과 몸으로만 답하기로 한 자리다.
                if r is not None and not r["allowed"]                         and getattr(z, "hidden", False):
                    continue

                if r is None or not r["reply"]:
                    print(f"  FAIL  {z.key} x {t.key} x {kind} 반응이 비었다")
                    missing += 1
    if missing:
        bad += missing
    else:
        print(f"  PASS  {len(zones)} x {len(tools)} x 2 = "
              f"{len(zones) * len(tools) * 2}가지 모두 대사가 나온다")

    # 8) 도구가 잠기는가
    print("\n[8] 도구도 사이를 타는가")
    for aff in (0, 30, 70, 90, 120):
        got = []
        for t in tools:
            ok = [z for z in zones
                  if aff >= ((z.allow_from or 0) + t.allow_bonus)
                  or (z.allow_from is None and t.allow_bonus <= 0)]
            if ok:
                got.append(f"{t.label}({len(ok)}곳)")
        print(f"  친밀도 {aff:4} : {', '.join(got) if got else '없음'}")

    print()
    if bad:
        print(f"{bad}건 실패")
        return 1
    print("전부 통과")
    return 0


if __name__ == "__main__":
    sys.exit(main())

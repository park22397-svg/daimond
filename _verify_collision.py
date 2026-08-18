# _verify_collision.py
# 모든 동작을 처음부터 끝까지 재생해 보며 팔이 몸을 뚫는지 검사한다.
#
# 자세 하나만 봐서는 못 잡는다. 키와 키 사이를 보간하는 동안 팔이
# 몸을 가로지르는 경우가 있어서, 시간을 잘게 쪼개 전부 확인해야 한다.

import sys

import numpy as np

import _fit_pose as F
from avatar import AVATAR
from _body_shape import BodyShape, BodyCapsules

VRM = "static/avatar.vrm"

STEP = 0.02          # 20ms 마다 본다
WARN = 0.005         # 5mm 넘게 박히면 문제로 본다

rig = F.Rig(VRM)
caps = BodyCapsules(BodyShape(VRM))

EASE = {
    "linear": lambda u: u,
    "easeIn": lambda u: u * u,
    "easeOut": lambda u: 1 - (1 - u) * (1 - u),
    "easeInOut": lambda u: u * u * (3 - 2 * u),
}


def sample_pose(m, t, base):
    pose = {k: list(v) for k, v in base.items()}
    keys = m.keys
    a = b = keys[0]
    u = 0.0

    if t <= keys[0]["t"]:
        a = b = keys[0]
    elif t >= keys[-1]["t"]:
        a = b = keys[-1]
    else:
        for i in range(len(keys) - 1):
            if keys[i]["t"] <= t < keys[i + 1]["t"]:
                a, b = keys[i], keys[i + 1]
                u = (t - a["t"]) / (b["t"] - a["t"])
                break

    e = EASE.get(m.ease, EASE["easeInOut"])(u)

    for n in m.channels():
        bs = base.get(n, [0, 0, 0])
        ra = a["bones"].get(n, bs)
        rb = b["bones"].get(n, bs)
        pose[n] = [ra[i] + (rb[i] - ra[i]) * e for i in range(3)]

    return pose


def arm_points(pose, side):
    sh = rig.pos(f"{side}UpperArm", pose)
    el = rig.pos(f"{side}LowerArm", pose)
    wr = rig.pos(f"{side}Hand", pose)
    tip = rig.pos(f"{side}MiddleProximal", pose)

    pts = [sh + (el - sh) * t for t in np.linspace(0.45, 1.0, 5)]
    pts += [el + (wr - el) * t for t in np.linspace(0.15, 1.0, 6)]
    pts += [wr, tip]
    return np.array(pts)


# 팔꿈치가 뒤로 꺾이는지 본다.
#
# 아래팔 로컬 y 축이 진짜 경첩이다 (T포즈에서 이 축으로만 돌리면
# 손 높이가 0.0mm 변하고 앞으로만 간다).
#   왼팔  : y 가 음수라야 앞으로 접힌다. 양수면 뒤로 꺾인 것이다.
#   오른팔 : 부호가 반대다.
# z 축은 팔이 들린 상태에서 접는 시늉이 되어 손인사 같은 데서 쓰이므로
# 여기서 막지는 않는다.
BACK_TOL = 2.0


def elbow_backward(pose):
    out = []
    for side, sign in (("left", +1), ("right", -1)):
        y = pose.get(f"{side}LowerArm", [0, 0, 0])[1]
        if sign * y > BACK_TOL:
            out.append((side, y))
    return out


def main():
    base = AVATAR.base_pose
    bad = 0

    print(f"몸 캡슐 {len(caps.caps)} 개로 검사 · {STEP * 1000:.0f}ms 간격 "
          f"· {WARN * 1000:.0f}mm 넘으면 문제\n")

    for m in AVATAR.motions:
        worst = 0.0
        worst_t = 0.0
        worst_who = None
        worst_side = None
        back = []

        n = int(m.duration / STEP) + 1
        for i in range(n + 1):
            t = min(i * STEP, m.duration)
            pose = sample_pose(m, t, base)

            for side, y in elbow_backward(pose):
                back.append((t, side, y))

            # 고개가 돌아가면 얼굴도 따라 움직인다. 그 자리로 재야 맞다.
            head_world = rig.world("head", pose)

            for side in ("left", "right"):
                P = arm_points(pose, side)
                d = caps.depths(P, head_world=head_world)
                if d.max() > worst:
                    i, j = np.unravel_index(d.argmax(), d.shape)
                    names = [c[0] for c in caps.caps] + ["head"]
                    worst = float(d.max())
                    worst_t, worst_who, worst_side = t, names[j], side

        ok = worst <= WARN and not back
        mark = "PASS" if ok else "FAIL"
        if not ok:
            bad += 1

        detail = ""
        if worst > 0.0005:
            arm = "왼팔" if worst_side == "left" else "오른팔"
            detail = f"  몸에 {worst * 100:.2f}cm (t={worst_t:.2f}s, {arm} -> {worst_who})"

        if back:
            t, side, y = max(back, key=lambda r: abs(r[2]))
            arm = "왼팔" if side == "left" else "오른팔"
            detail += f"  {arm} 팔꿈치가 뒤로 {abs(y):.1f}도 (t={t:.2f}s)"

        print(f"  {mark}  {m.key:8} {m.label:12}{detail}")

    print()
    if bad:
        print(f"{bad}개 동작에 문제가 있습니다")
        return 1

    print("모든 동작이 몸을 뚫지 않고 팔꿈치도 바르게 접힙니다")
    return 0


if __name__ == "__main__":
    sys.exit(main())

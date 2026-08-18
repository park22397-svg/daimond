# _fit_shy_path.py
# shy 의 '지나갈 자리' 만 다시 잡는다.
#
# 도착 자세는 이미 맞다. 문제는 거기까지 가는 길인데, 그냥 몸만 피하게 하면
# 팔을 머리 위로 크게 휘둘러 올리는 답이 나온다. 쑥스러워하는 동작에는 과하다.
# 손이 머리보다 높이 뜨지 않도록, 그리고 몸 앞쪽으로 지나가도록 조건을 더 준다.

import numpy as np

import _fit_pose as F
from avatar import AVATAR
from _body_shape import BodyShape, BodyCapsules

VRM = "static/avatar.vrm"
CLEAR = 0.015

BONES = ["leftShoulder", "leftUpperArm", "leftLowerArm", "leftHand"]

LO = np.array([-22, -22, -22] + [-120, -170, -170]
              + [-90, -150, 0] + [-55, -55, -55], dtype=float)
HI = np.array([22, 22, 22] + [120, 170, 170]
              + [90, -5, 0] + [55, 55, 55], dtype=float)

rig = F.Rig(VRM)
caps = BodyCapsules(BodyShape(VRM))

joint_solver = rig.solver(
    ["leftUpperArm", "leftLowerArm", "leftHand", "leftMiddleProximal"], set(BONES))

shy = [m for m in AVATAR.motions if m.key == "shy"][0]
keys = {k["t"]: k["bones"] for k in shy.keys}


def pick(bones):
    return {b: list(bones.get(b, AVATAR.base_pose.get(b, [0, 0, 0]))) for b in BONES}


BASE = pick(keys[0.0])
GOAL = pick(keys[1.0])

HEAD_Y = float(rig.pos("head", GOAL)[1])
print(f"머리 높이 {HEAD_Y:.3f} m / 도착 자세 손 높이 {rig.pos('leftHand', GOAL)[1]:.3f} m")


def pose_of(p):
    return {"leftShoulder": list(p[0:3]), "leftUpperArm": list(p[3:6]),
            "leftLowerArm": list(p[6:9]), "leftHand": list(p[9:12])}


def vec(pose):
    return np.array(pose["leftShoulder"] + pose["leftUpperArm"]
                    + pose["leftLowerArm"] + pose["leftHand"], dtype=float)


UPPER_T = np.linspace(0.45, 1.0, 4)
FORE_T = np.linspace(0.2, 1.0, 4)


def arm_points(pose):
    sh, el, wr, tip = joint_solver(pose)
    pts = [sh + (el - sh) * t for t in UPPER_T]
    pts += [el + (wr - el) * t for t in FORE_T]
    pts += [tip]
    return np.array(pts), wr


def ease(u):
    return u * u * (3 - 2 * u)


def sample(a, b, n):
    va, vb = vec(a), vec(b)
    return [pose_of(va + (vb - va) * ease(i / n)) for i in range(1, n)]


def path_penalty(a, b, n=8):
    """몸에 닿는 정도 + 손이 머리 위로 뜨는 정도 + 뒤로 도는 정도."""
    body = 0.0
    high = 0.0
    behind = 0.0
    for p in sample(a, b, n):
        pts, wr = arm_points(p)
        body += float(np.sum(caps.depths(pts, margin=CLEAR) ** 2))
        # 손이 머리보다 높이 올라가면 휘두르는 것처럼 보인다
        high += max(0.0, wr[1] - (HEAD_Y - 0.06)) ** 2
        # 몸 뒤(+Z)로 도는 길은 보기 나쁘다. 앞으로 지나가야 한다.
        behind += max(0.0, wr[2] - 0.02) ** 2
    return body, high, behind


def cost(p):
    mid = pose_of(p)
    pts, wr = arm_points(mid)

    e = 400.0 * float(np.sum(caps.depths(pts, margin=CLEAR) ** 2))
    e += 60.0 * max(0.0, wr[1] - (HEAD_Y - 0.06)) ** 2
    e += 40.0 * max(0.0, wr[2] - 0.02) ** 2

    for a, b in ((BASE, mid), (mid, GOAL)):
        body, high, behind = path_penalty(a, b)
        e += 300.0 * body + 60.0 * high + 40.0 * behind

    half = (vec(BASE) + vec(GOAL)) / 2
    e += 3.0e-6 * float(np.sum((p - half) ** 2))
    e += 2.0e-6 * float(np.sum(np.array(mid["leftShoulder"]) ** 2))
    return e


rng = np.random.default_rng(17)
starts = [(vec(BASE) + vec(GOAL)) / 2] + [rng.uniform(LO, HI) for _ in range(18)]

best, bv = None, float("inf")
for k, s in enumerate(starts):
    x, v = F.nelder_mead(cost, np.clip(s, LO, HI), np.full(12, 14.0), LO, HI, iters=900)
    x, v = F.nelder_mead(cost, x, np.full(12, 2.5), LO, HI, iters=1100)
    if v < bv:
        best, bv = x, v
        print(f"  시작 {k + 1}/{len(starts)} — 더 나은 답 {v:.6f}", flush=True)

MID = pose_of(best)

print("\n지나갈 자리")
for b in BONES:
    print(f"  {b:16} {F.fmt(MID[b])}")

print("\n검사")
for label, a, b in (("기준 -> 지나갈 자리", BASE, MID), ("지나갈 자리 -> 도착", MID, GOAL)):
    worst = 0.0
    top = 0.0
    for p in [a] + sample(a, b, 16) + [b]:
        pts, wr = arm_points(p)
        worst = max(worst, float(caps.depths(pts).max()))
        top = max(top, float(wr[1]))
    print(f"  {label:22} 몸 {worst * 100:5.2f}cm   손 최고 높이 {top:.3f} m "
          f"(머리 {HEAD_Y:.3f} m)")

print("\navatar.py 의 0.45초 · 2.15초 키에 넣을 값")
print(f'                    "leftShoulder": {F.rnd(MID["leftShoulder"])}, '
      f'"leftUpperArm": {F.rnd(MID["leftUpperArm"])},')
print(f'                    "leftLowerArm": {F.rnd(MID["leftLowerArm"])}, '
      f'"leftHand": {F.rnd(MID["leftHand"])},')

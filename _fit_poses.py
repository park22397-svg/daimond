# _fit_poses.py
# 새 동작들의 팔 자세를 한꺼번에 푼다.
#
# 손이 어디에 있어야 하는지만 적고, 나머지는 계산이 찾는다.
#   - 팔꿈치는 경첩이다. y 로만 접고(왼팔 음수·오른팔 양수) z 는 잠근다.
#   - 어깨(쇄골)는 ±22도를 넘지 않는다.
#   - 팔이 몸을 뚫지 않아야 한다.
#
# 이 조건들을 지키는 값을 못 찾으면 목표 위치가 사람이 낼 수 없는 자리라는 뜻이다.

import numpy as np

import _fit_pose as F
from _body_shape import BodyShape, BodyCapsules

VRM = "static/avatar.vrm"
CLEAR = 0.012

rig = F.Rig(VRM)
caps = BodyCapsules(BodyShape(VRM))


def bounds(side):
    """어깨3 + 위팔3 + 아래팔3 + 손3.

    아래팔 y 는 접히는 방향으로만 열어 둔다. 왼팔은 음수, 오른팔은 양수다.
    z 는 잠근다 — 경첩이 아닌 축으로 접으면 팔꿈치가 뒤로 꺾인다.
    """
    if side == "left":
        fore = ([-90, -150, 0], [90, -5, 0])
    else:
        fore = ([-90, 5, 0], [90, 150, 0])

    lo = [-22, -22, -22] + [-120, -170, -170] + fore[0] + [-55, -55, -55]
    hi = [22, 22, 22] + [120, 170, 170] + fore[1] + [55, 55, 55]
    return np.array(lo, float), np.array(hi, float)


def solve(side, targets, weights=None, seed=5, tries=45):
    """targets = {본이름: [x,y,z]} 목표 위치."""
    names = list(targets.keys())
    T = np.array([targets[n] for n in names])
    W = np.array(weights or [1.0] * len(names))[:, None]

    bones = [f"{side}Shoulder", f"{side}UpperArm",
             f"{side}LowerArm", f"{side}Hand"]
    varset = set(bones)

    mark = rig.solver(names, varset)
    arm = rig.solver([f"{side}UpperArm", f"{side}LowerArm",
                      f"{side}Hand", f"{side}MiddleProximal"], varset)

    lo, hi = bounds(side)

    def pose_of(p):
        return {bones[0]: list(p[0:3]), bones[1]: list(p[3:6]),
                bones[2]: list(p[6:9]), bones[3]: list(p[9:12])}

    def pts(d):
        sh, el, wr, tip = arm(d)
        q = [sh + (el - sh) * t for t in np.linspace(0.45, 1, 4)]
        q += [el + (wr - el) * t for t in np.linspace(0.2, 1, 4)]
        q += [tip]
        return np.array(q)

    def cost(p):
        d = pose_of(p)
        e = float(np.sum(W * (np.array(mark(d)) - T) ** 2))
        e += 400.0 * float(np.sum(caps.depths(pts(d), margin=CLEAR) ** 2))
        e += 2.0e-6 * float(np.sum(np.array(d[bones[0]]) ** 2))
        e += 1.0e-7 * float(np.sum(np.array(d[bones[3]]) ** 2))
        return e

    rng = np.random.default_rng(seed)
    best, bv = None, float("inf")
    for _ in range(tries):
        s = rng.uniform(lo, hi)
        x, v = F.nelder_mead(cost, np.clip(s, lo, hi), np.full(12, 14.0),
                             lo, hi, iters=900)
        x, v = F.nelder_mead(cost, x, np.full(12, 2.0), lo, hi, iters=1100)
        if v < bv:
            best, bv = x, v

    d = pose_of(best)
    got = np.array(mark(d))
    err = [float(np.linalg.norm(g - t)) for g, t in zip(got, T)]
    depth = float(caps.depths(pts(d)).max())

    def ang(a, b):
        a = a / np.linalg.norm(a); b = b / np.linalg.norm(b)
        return np.degrees(np.arccos(np.clip(a @ b, -1, 1)))

    sh, el, wr, _ = arm(d)
    flex = ang(el - sh, wr - el)

    return d, {"err": err, "names": names, "depth": depth, "flex": flex}


def report(label, pose, info):
    print(f"\n[{label}]")
    for n, e in zip(info["names"], info["err"]):
        print(f"    {n:22} {e * 1000:6.1f} mm")
    ok = info["depth"] <= 0.003 and info["flex"] <= 150
    print(f"    몸에 박힘 {info['depth'] * 100:.2f}cm · 팔꿈치 굽힘 "
          f"{info['flex']:.1f}도  {'OK' if ok else '<- 확인 필요'}")
    for b, v in pose.items():
        print(f'                    "{b}": {F.rnd(v)},')
    return ok

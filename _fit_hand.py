# _fit_hand.py
# 힘을 뺀 손 모양을 만든다.
#
# 손가락을 건드리지 않으면 T포즈 그대로라 손이 판자처럼 쫙 펴진다.
# 사람 손은 가만히 있어도 마디마다 조금씩 굽어 있고, 새끼로 갈수록 더 굽는다.
#
# 접는 축은 짐작하지 않는다. 실측으로 확정한 값:
#   손가락 : z 축이 오므리는 축. 왼손은 +, 오른손은 -. y 는 벌림, x 는 비틀기
#   엄지   : y 축이 손바닥 쪽으로 모으는 축. 왼손은 +, 오른손은 -
#
# 만든 뒤에는 손끝이 손바닥을 뚫지 않는지 확인한다.

import numpy as np

import _fit_pose as F

VRM = "static/avatar.vrm"

JOINTS = ["Proximal", "Intermediate", "Distal"]

# 왼손 기준. 오른손은 z 와 y 의 부호를 뒤집는다.
#
#   (마디1 굽힘, 마디2 굽힘, 마디3 굽힘, 벌림)
#
# 새끼로 갈수록 더 굽는 것이 힘을 뺀 손의 모양이다.
CURL = {
    "Index":  (11, 26, 15, -5),
    "Middle": (13, 30, 17, -1),
    "Ring":   (15, 34, 19, +3),
    "Little": (17, 37, 21, +7),
}

# 엄지는 축이 다르다. (모으기 y, 마디 굽힘 x)
THUMB = {"in": 15, "bend": (10, 12, 8)}

BASE_ARM = {
    "leftUpperArm": [0, 0, 68.75], "rightUpperArm": [0, 0, -68.75],
    "leftLowerArm": [0, 0, 10], "rightLowerArm": [0, 0, -10],
}


def hand_pose(side):
    """그 손의 손가락 값들."""
    s = 1 if side == "left" else -1
    pose = {}

    for finger, (a, b, c, spread) in CURL.items():
        pose[f"{side}{finger}Proximal"] = [0, s * spread, s * a]
        pose[f"{side}{finger}Intermediate"] = [0, 0, s * b]
        pose[f"{side}{finger}Distal"] = [0, 0, s * c]

    x1, x2, x3 = THUMB["bend"]
    pose[f"{side}ThumbProximal"] = [x1, s * THUMB["in"], 0]
    pose[f"{side}ThumbIntermediate"] = [x2, 0, 0]
    pose[f"{side}ThumbDistal"] = [x3, 0, 0]

    return pose


def palm_frame(rig, side, pose):
    wr = rig.pos(f"{side}Hand", pose)
    mid = rig.pos(f"{side}MiddleProximal", pose)
    idx = rig.pos(f"{side}IndexProximal", pose)
    lit = rig.pos(f"{side}LittleProximal", pose)
    thb = rig.pos(f"{side}ThumbProximal", pose)

    long_ax = mid - wr
    long_ax /= np.linalg.norm(long_ax)
    across = lit - idx
    across /= np.linalg.norm(across)
    n = np.cross(long_ax, across)
    n /= np.linalg.norm(n)
    if np.dot(thb - wr, n) < 0:
        n = -n
    return wr, n


def report(rig, side, pose, label):
    wr, n = palm_frame(rig, side, pose)
    print(f"\n[{side} {label}]")
    worst = None
    for finger in ("Thumb", "Index", "Middle", "Ring", "Little"):
        tip = rig.pos(f"{side}{finger}Distal", pose)
        # 손바닥 면에서 손끝이 얼마나 떨어져 있는지 (음수면 손바닥을 뚫은 것)
        d = float(np.dot(tip - wr, n))
        span = float(np.linalg.norm(tip - wr))
        print(f"  {finger:7} 손끝 손목에서 {span * 100:5.1f}cm, "
              f"손바닥 면에서 {d * 100:+6.2f}cm")
        if worst is None or d < worst:
            worst = d
    return worst


def main():
    rig = F.Rig(VRM)

    flat = dict(BASE_ARM)
    relaxed = dict(BASE_ARM)
    for side in ("left", "right"):
        relaxed.update(hand_pose(side))

    print("=" * 60)
    print("펴진 손 (지금)")
    for side in ("left", "right"):
        report(rig, side, flat, "펴짐")

    print("\n" + "=" * 60)
    print("힘을 뺀 손 (새로 만든 것)")
    bad = 0
    for side in ("left", "right"):
        worst = report(rig, side, relaxed, "힘 뺌")
        if worst < -0.005:
            print(f"  경고: 손끝이 손바닥을 {abs(worst) * 100:.1f}cm 뚫었다")
            bad += 1

    # 좌우가 거울인지
    print("\n" + "=" * 60)
    print("좌우 대칭 확인")
    ok = True
    for finger in ("Thumb", "Index", "Middle", "Ring", "Little"):
        L = rig.pos(f"left{finger}Distal", relaxed)
        R = rig.pos(f"right{finger}Distal", relaxed)
        d = abs(L[0] + R[0]) + abs(L[1] - R[1]) + abs(L[2] - R[2])
        mark = "OK" if d < 0.002 else "어긋남"
        if d >= 0.002:
            ok = False
        print(f"  {finger:7} 왼쪽 {F.rnd(L,3)}  오른쪽 {F.rnd(R,3)}  {mark}")

    print("\n" + "=" * 60)
    print("avatar.py 의 base_pose 에 넣을 값\n")
    for side in ("left", "right"):
        p = hand_pose(side)
        for finger in ("Thumb", "Index", "Middle", "Ring", "Little"):
            row = []
            for j in JOINTS:
                k = f"{side}{finger}{j}"
                row.append(f'"{k}": {F.rnd(p[k])}')
            print("        " + ", ".join(row) + ",")
        print()

    return 1 if (bad or not ok) else 0


if __name__ == "__main__":
    import sys
    sys.exit(main())

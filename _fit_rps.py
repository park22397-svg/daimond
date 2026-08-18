# _fit_rps.py
# 가위바위보의 손 모양 세 가지를 만든다.
#
# 손가락 관절이 생겼으니 주먹·가위·보를 실제로 지을 수 있다.
# 접는 축은 실측값을 쓴다: 손가락 z(왼손 +, 오른손 -), 엄지 y.
#
# 만든 뒤에는 두 가지를 확인한다.
#   1) 접은 손끝이 손바닥을 뚫지 않는가
#   2) 편 손가락과 접은 손가락이 실제로 구별되는가 (가위가 가위로 보이는가)

import numpy as np

import _fit_pose as F

VRM = "static/avatar.vrm"
FINGERS = ["Index", "Middle", "Ring", "Little"]
JOINTS = ["Proximal", "Intermediate", "Distal"]

BASE_ARM = {
    "leftUpperArm": [0, 0, 68.75], "rightUpperArm": [0, 0, -68.75],
    "leftLowerArm": [0, 0, 10], "rightLowerArm": [0, 0, -10],
}

# 마디별 굽힘. (마디1, 마디2, 마디3)
CURLED = (78, 92, 62)     # 꽉 쥔 손가락
RELAX = (11, 26, 15)      # 힘 뺀 정도 (기준자세와 같은 값)
FLAT = (0, 0, 0)          # 쫙 편 손가락

# 엄지를 어디에 둘 것인가.
#
# 이 값은 계산이 아니라 눈으로 맞춘 것이다. 그럴 만한 이유가 있다.
#
# 처음 값(모으기 34도)은 엄지가 검지를 그대로 뚫고 나왔다.
# 그래서 기하로 한계를 찾으려 했지만 이 규모에서는 되지 않았다 —
# 본 축까지의 거리로 재면 엄지 뿌리 본에 손바닥 살이 딸려 있어
# 반지름이 1.87cm 로 잡히고, 검지도 손등 살이 섞여 2.10cm 가 된다.
# 그 숫자로 세운 기준은 멀쩡한 자세도 '뚫었다' 고 한다.
#
# 스키닝을 직접 계산해 살끼리 재도(_skin_check.py) 엄지 뿌리와 손바닥이
# 어느 자세에서나 붙어 있어 값이 그쪽에 묶인다.
#
# 결국 사람이 보고 정했다.
#   모으기 34도 - 뚫는다
#   모으기 13도 - 안 뚫지만 어색하게 벌어진다
#   모으기 21도 - 지금 값
#
# 고칠 일이 있으면 /rig 에서 엄지 슬라이더를 직접 움직여 보는 편이 빠르다.
# 엄지는 마디마다 세 축을 그대로 적는다.
#
# 처음에는 '모으기 한 값 + 마디별 굽힘' 으로 줄여 뒀는데, 사람이 리깅
# 확인대에서 잡은 값은 그 틀에 안 들어간다(끝마디를 y 축으로 돌리는 등).
# 줄여 놓은 틀 때문에 잡아 온 값을 못 넣는 일이 없도록 전부 적는다.
#
# 주먹과 가위는 같은 엄지를 쓴다. 보자기만 따로 둔다.
# 사람이 /rig 에서 직접 잡은 값. 오른손 기준.
THUMB_FIST = {
    "ThumbProximal": [-22, 0, 0],
    "ThumbIntermediate": [-25, -51.25, -57],
    "ThumbDistal": [0, -83.5, 0],
}

THUMB_FLAT = {
    "ThumbProximal": [0, 8, 0],
    "ThumbIntermediate": [0, 0, 0],
    "ThumbDistal": [0, 0, 0],
}

# 아래는 옛 방식. hand() 가 위의 표를 우선해서 쓴다.
THUMB_OPEN = {"in": -8, "bend": (0, 0, 0)}
# 뿌리를 5도 떼면 엄지가 검지에서 0.3cm 씩 멀어지는데,
# 끝마디로는 0.1cm 밖에 못 당긴다. 떨어뜨리고도 검지에 닿게 하는 건
# 중간마디다. 그래서 뿌리를 16도로 떼고 중간마디를 60도로 접었다.
# 이 조합에서 엄지 끝마디 살과 검지 살 사이가 0.44cm — 닿되 파고들지 않는다.
# 가위는 검지가 펴져 있어 같은 값이면 엄지가 0.15cm 까지 붙는다.
# 뿌리를 12도로 더 떼서 0.41cm 를 맞췄다.
THUMB_ROCK = {"in": 16, "bend": (20, 60, 30)}
THUMB_SCISSORS = {"in": 12, "bend": (18, 52, 30)}

SHAPES = {
    # 바위 — 네 손가락을 전부 쥐고 엄지를 반쯤 모은다
    "rock": {
        "curl": {f: CURLED for f in FINGERS},
        "thumb": THUMB_ROCK,
        "thumb_raw": THUMB_FIST,
        "spread": {f: 0 for f in FINGERS},
    },
    # 가위 — 검지와 중지만 펴고 벌린다
    "scissors": {
        "curl": {"Index": FLAT, "Middle": FLAT,
                 "Ring": CURLED, "Little": CURLED},
        "thumb": THUMB_SCISSORS,
        "thumb_raw": THUMB_FIST,
        "spread": {"Index": -16, "Middle": 12, "Ring": 0, "Little": 0},
    },
    # 보 — 전부 펴고 살짝 벌린다
    "paper": {
        "curl": {f: FLAT for f in FINGERS},
        "thumb": THUMB_OPEN,
        "thumb_raw": THUMB_FLAT,
        "spread": {"Index": -8, "Middle": -2, "Ring": 5, "Little": 11},
    },
}


def hand(side, shape):
    s = 1 if side == "left" else -1
    spec = SHAPES[shape]
    pose = {}

    for f in FINGERS:
        a, b, c = spec["curl"][f]
        sp = spec["spread"][f]
        pose[f"{side}{f}Proximal"] = [0, s * sp, s * a]
        pose[f"{side}{f}Intermediate"] = [0, 0, s * b]
        pose[f"{side}{f}Distal"] = [0, 0, s * c]

    raw = spec.get("thumb_raw")
    if raw:
        # 적어 둔 값은 오른손 기준이다(리깅 확인대에서 오른손으로 잡았다).
        # 오른손이면 그대로 쓰고, 왼손이면 y·z 부호를 뒤집는다.
        m = 1 if side == "right" else -1
        for joint, v in raw.items():
            pose[f"{side}{joint}"] = [v[0], m * v[1], m * v[2]]
    else:
        x1, x2, x3 = spec["thumb"]["bend"]
        pose[f"{side}ThumbProximal"] = [x1, s * spec["thumb"]["in"], 0]
        pose[f"{side}ThumbIntermediate"] = [x2, 0, 0]
        pose[f"{side}ThumbDistal"] = [x3, 0, 0]

    return pose


def palm(rig, side, pose):
    wr = rig.pos(f"{side}Hand", pose)
    mid = rig.pos(f"{side}MiddleProximal", pose)
    idx = rig.pos(f"{side}IndexProximal", pose)
    lit = rig.pos(f"{side}LittleProximal", pose)
    thb = rig.pos(f"{side}ThumbProximal", pose)
    la = mid - wr
    la /= np.linalg.norm(la)
    ac = lit - idx
    ac /= np.linalg.norm(ac)
    n = np.cross(la, ac)
    n /= np.linalg.norm(n)
    if np.dot(thb - wr, n) < 0:
        n = -n
    return wr, n


def finger_gap(rig, side, pose, a, b):
    """두 손가락이 가장 가까운 거리. 손가락 굵기(반지름 1.1cm)보다
    가까우면 서로 뚫는다."""
    def pts(names):
        p = [rig.pos(f"{side}{n}", pose) for n in names]
        out = []
        for u, v in zip(p[:-1], p[1:]):
            for t in np.linspace(0, 1, 6):
                out.append(u + (v - u) * t)
        return np.array(out)

    A = pts([f"{a}Proximal", f"{a}Intermediate", f"{a}Distal"])
    B = pts([f"{b}Proximal", f"{b}Intermediate", f"{b}Distal"])
    return float(np.linalg.norm(A[:, None, :] - B[None, :, :], axis=2).min())


# 얼마나 떨어져 있어야 '안 뚫은' 것인가.
#
# 나란히 붙어 있는 손가락은 편 손에서도 1.76cm 밖에 안 떨어져 있다.
# 원래 서로 닿는 사이라 그렇다. 그러니 이웃끼리는 기준을 낮게 잡는다.
# 엄지는 다른 면에서 건너오므로 확실히 떨어져야 한다.
GAP_MIN = {
    ("Thumb", "Index"): 0.020,
    ("Thumb", "Middle"): 0.020,
    ("Index", "Middle"): 0.012,
}


def main():
    rig = F.Rig(VRM)
    side = "right"          # 오른손으로 낸다 (손인사와 같은 손)
    bad = 0

    print("손 모양 점검 (오른손)\n")

    for shape in ("rock", "scissors", "paper"):
        pose = dict(BASE_ARM)
        pose.update(hand(side, shape))

        wr, n = palm(rig, side, pose)
        print(f"[{shape}]")

        reach = {}
        for f in ["Thumb"] + FINGERS:
            tip = rig.pos(f"{side}{f}Distal", pose)
            span = float(np.linalg.norm(tip - wr))
            depth = float(np.dot(tip - wr, n))
            reach[f] = span
            flag = ""
            if depth < -0.005:
                flag = "  <- 손바닥을 뚫었다"
                bad += 1
            print(f"  {f:7} 손목에서 {span * 100:5.1f}cm  "
                  f"손바닥면 {depth * 100:+6.2f}cm{flag}")

        # 편 손가락과 접은 손가락이 구별되는가
        if shape == "scissors":
            out = min(reach["Index"], reach["Middle"])
            inn = max(reach["Ring"], reach["Little"])
            gap = (out - inn) * 100
            ok = gap > 2.0
            print(f"  펴진 손가락 {out * 100:.1f}cm vs 접힌 손가락 {inn * 100:.1f}cm "
                  f"-> 차이 {gap:.1f}cm {'OK' if ok else '<- 구별이 안 된다'}")
            if not ok:
                bad += 1

        if shape == "rock":
            far = max(reach[f] for f in FINGERS)
            ok = far < 0.085
            print(f"  가장 먼 손끝 {far * 100:.1f}cm "
                  f"{'OK (주먹으로 보인다)' if ok else '<- 덜 쥐었다'}")
            if not ok:
                bad += 1

        if shape == "paper":
            near = min(reach[f] for f in FINGERS)
            ok = near > 0.10
            print(f"  가장 가까운 손끝 {near * 100:.1f}cm "
                  f"{'OK (쫙 폈다)' if ok else '<- 덜 폈다'}")
            if not ok:
                bad += 1

        # 손가락끼리 뚫는지. 특히 엄지가 검지를 뚫고 나오는 일이 잦다.
        for (a, b), need in GAP_MIN.items():
            gap = finger_gap(rig, side, pose, a, b)
            ok = gap >= need
            print(f"  {a} - {b} 사이 {gap * 100:5.2f}cm "
                  f"(최소 {need * 100:.1f}) {'OK' if ok else '<- 서로 뚫는다'}")
            if not ok:
                bad += 1

        print()

    print("=" * 58)
    print("avatar.py 에 넣을 값\n")
    for shape in ("rock", "scissors", "paper"):
        p = hand(side, shape)
        print(f'    "{shape}": {{')
        for f in ["Thumb"] + FINGERS:
            row = [f'"{side}{f}{j}": {F.rnd(p[f"{side}{f}{j}"])}' for j in JOINTS]
            print("        " + ", ".join(row) + ",")
        print("    },")

    return 1 if bad else 0


if __name__ == "__main__":
    import sys
    sys.exit(main())

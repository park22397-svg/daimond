# _fit_shy.py
# shy 클립을 몸에 닿지 않게 다시 푼다.
#
# 두 가지를 동시에 봐야 한다.
#   1) 도착 자세      — 손끝이 얼굴 안으로 들어가면 안 된다
#   2) 올라가는 길     — 팔이 골반·몸통을 지나가면 안 된다
#
# 자세 하나만 고쳐서는 2번이 안 풀린다. 두 자세를 잇는 보간이 몸을 관통하기
# 때문이다. 그래서 중간에 거쳐 갈 자리를 하나 더 찾아 팔을 몸 바깥으로 돌린다.

import numpy as np

import _fit_pose as F
from _body_shape import BodyShape, BodyCapsules

VRM = "static/avatar.vrm"

CLEAR = 0.015          # 몸에서 최소 이만큼(1.5cm) 떨어뜨린다
MARKS = ["leftLowerArm", "leftHand", "leftMiddleProximal",
         "leftIndexProximal", "leftThumbProximal"]

BASE = {"leftShoulder": [0, 0, 0], "leftUpperArm": [0, 0, 68.75],
        "leftLowerArm": [0, 0, 10], "leftHand": [0, 0, 0]}

# 사람이 리깅 확인대에서 만든 자세를 관절만 편 것 (_fit_pose.py 결과)
WANT = {"leftShoulder": [-3.4, 20.3, -16.4], "leftUpperArm": [-4.5, 102.6, 149.2],
        "leftLowerArm": [-17.8, -19.4, 144.4], "leftHand": [0, 0, 0]}

# 손목도 변수로 연다.
# 손 회전을 0 으로 묶어 두면 손가락이 얼굴을 피할 방법이 손목을 옮기는 것뿐이라,
# 사람이 잡아 놓은 손 위치가 망가진다. 손목을 조금 꺾는 게 훨씬 자연스럽다.
BONES = ["leftShoulder", "leftUpperArm", "leftLowerArm", "leftHand"]

# ------------------------------------------------------------
# 팔꿈치는 경첩이다. 축이 하나뿐이다.
#
# 실측으로 확정한 값 (T포즈에서 leftLowerArm 만 돌려 손 궤적을 봤다):
#   y (-) : 손이 앞으로. 높이 변화 0.0mm 인 순수 경첩. 이게 진짜 팔꿈치다.
#   y (+) : 뒤로 꺾인다. 사람 팔은 이렇게 안 된다.
#   z     : T포즈에서 손을 21cm 아래로 꺾는다. 팔꿈치가 아니라 어깨가 할 일이다.
#
# 그래서 아래팔은 x(아래팔 비틀기)와 y(굽힘, 음수만) 두 개만 쓴다.
# z 는 0 으로 잠근다. 손을 얼굴로 올리는 건 위팔 비틀기(x)가 맡는다.
# (오른팔이면 y 부호가 반대다)
# ------------------------------------------------------------

N = 12

#                    어깨                위팔(x 는 비틀기)
LO = np.array([-22, -22, -22] + [-120, -170, -170]
              #  아래팔: x 비틀기 / y 굽힘(음수만) / z 잠금
              + [-90, -150, 0]
              + [-55, -55, -55], dtype=float)
HI = np.array([22, 22, 22] + [120, 170, 170]
              + [90, -5, 0]
              + [55, 55, 55], dtype=float)


rig = F.Rig(VRM)
caps = BodyCapsules(BodyShape(VRM))

joint_solver = rig.solver(
    ["leftUpperArm", "leftLowerArm", "leftHand", "leftMiddleProximal"],
    set(BONES))
mark_solver = rig.solver(MARKS, set(BONES))


def pose_of(p):
    return {"leftShoulder": list(p[0:3]),
            "leftUpperArm": list(p[3:6]),
            "leftLowerArm": list(p[6:9]),
            "leftHand": list(p[9:12])}


def vec(pose):
    return np.array(pose["leftShoulder"] + pose["leftUpperArm"]
                    + pose["leftLowerArm"] + pose["leftHand"], dtype=float)


UPPER_T = np.linspace(0.45, 1.0, 4)
FORE_T = np.linspace(0.2, 1.0, 4)


def arm_points(pose):
    """팔을 따라 찍은 점들. 어깨 뿌리는 원래 몸 안이라 뺀다."""
    sh, el, wr, tip = joint_solver(pose)
    pts = [sh + (el - sh) * t for t in UPPER_T]
    pts += [el + (wr - el) * t for t in FORE_T]
    pts += [tip]
    return np.array(pts)


def clearance_short(pose, clear=CLEAR):
    """몸 표면에서 clear 만큼 떨어져야 하는데 얼마나 모자란지."""
    return caps.depths(arm_points(pose), margin=clear)


def ease(u):
    return u * u * (3 - 2 * u)


def path_cost(a, b, n=8, clear=CLEAR):
    """두 자세를 잇는 동안 몸에 얼마나 닿는지."""
    va, vb = vec(a), vec(b)
    tot = 0.0
    for i in range(1, n):
        u = ease(i / n)
        p = va + (vb - va) * u
        s = clearance_short(pose_of(p))
        tot += float(np.sum(s ** 2))
    return tot


# ============================================================
# 1단계 — 도착 자세를 몸 밖으로
# ============================================================

target = np.array([rig.pos(m, WANT) for m in MARKS])
# 손가락의 목표 위치는 얼굴 안이라 그대로 따라가면 안 된다.
# 팔꿈치와 손목만 제대로 붙들고, 손가락은 방향만 참고한다.
W = np.array([1.0, 3.0, 0.3, 0.3, 0.3])[:, None]


def cost_goal(p):
    d = pose_of(p)
    got = np.array(mark_solver(d))
    e = float(np.sum(W * (got - target) ** 2))
    s = clearance_short(d)
    e += 400.0 * float(np.sum(s ** 2))
    e += 2.0e-6 * float(np.sum(np.array(d["leftShoulder"]) ** 2))
    e += 1.0e-7 * float(np.sum(np.array(d["leftHand"]) ** 2))
    return e


def solve(cost, starts, coarse=12.0, fine=2.0, label=""):
    best, bv = None, float("inf")
    for k, s in enumerate(starts):
        x, v = F.nelder_mead(cost, np.clip(s, LO, HI), np.full(N, coarse),
                             LO, HI, iters=900)
        x, v = F.nelder_mead(cost, x, np.full(N, fine), LO, HI, iters=1100)
        if v < bv:
            best, bv = x, v
            print(f"    {label} 시작 {k + 1}/{len(starts)} — 더 나은 답 {v:.6f}",
                  flush=True)
    return best, bv


rng = np.random.default_rng(3)
starts = [vec(WANT)] + [rng.uniform(LO, HI) for _ in range(50)]
goal_p, gv = solve(cost_goal, starts, label="[1]")
GOAL = pose_of(goal_p)

print("[1] 도착 자세")
moved = [float(np.linalg.norm(rig.pos(m, GOAL) - rig.pos(m, WANT))) for m in MARKS]
for m, d in zip(MARKS, moved):
    print(f"    {m:22} {d * 1000:7.1f} mm 이동")
print(f"    몸에 박힌 깊이 {caps.depths(arm_points(GOAL)).max() * 100:.2f} cm "
      f"(여유 {CLEAR * 100:.1f}cm 기준 부족분 {clearance_short(GOAL).max() * 100:.2f} cm)")
for b in BONES:
    print(f"    {b:16} {F.fmt(WANT[b]):26} -> {F.fmt(GOAL[b])}")


# ============================================================
# 2단계 — 지나갈 자리 찾기
# ============================================================

def cost_mid(p):
    mid = pose_of(p)
    e = 0.0
    e += 400.0 * float(np.sum(clearance_short(mid) ** 2))
    e += 300.0 * path_cost(BASE, mid)
    e += 300.0 * path_cost(mid, GOAL)
    # 어정쩡하게 멀리 돌지 않도록 base 와 goal 사이에 있게 붙든다
    half = (vec(BASE) + goal_p) / 2
    e += 4.0e-6 * float(np.sum((p - half) ** 2))
    e += 2.0e-6 * float(np.sum(np.array(mid["leftShoulder"]) ** 2))
    return e


starts = [(vec(BASE) + goal_p) / 2] + [rng.uniform(LO, HI) for _ in range(12)]
mid_p, mv = solve(cost_mid, starts, coarse=14.0, fine=2.5, label="[2]")
MID = pose_of(mid_p)

print("\n[2] 지나갈 자리")
for b in BONES:
    print(f"    {b:16} {F.fmt(MID[b])}")


# ============================================================
# 3단계 — 전체 길 검사
# ============================================================

def scan(label, a, b, n=16):
    va, vb = vec(a), vec(b)
    worst = 0.0
    for i in range(n + 1):
        u = ease(i / n)
        p = pose_of(va + (vb - va) * u)
        worst = max(worst, float(caps.depths(arm_points(p)).max()))
    print(f"    {label:22} 가장 깊이 {worst * 100:5.2f} cm "
          f"{'OK' if worst <= 0.001 else '<-- 아직 닿음'}")
    return worst


print("\n[3] 전체 길 검사 (몸 안으로 들어간 깊이)")
w1 = scan("기준 -> 지나갈 자리", BASE, MID)
w2 = scan("지나갈 자리 -> 도착", MID, GOAL)
w3 = scan("도착 -> 기준", GOAL, BASE)


def angles(pose):
    sh, el, wr, _ = joint_solver(pose)
    def ang(a, b):
        a = a / np.linalg.norm(a); b = b / np.linalg.norm(b)
        return np.degrees(np.arccos(np.clip(a @ b, -1, 1)))
    return ang(el - sh, wr - el), ang(el - sh, np.array([0, -1, 0]))


print("\n[4] 관절 각도 (사람 범위: 팔꿈치 0~150도)")
for nm, p in (("기준", BASE), ("지나갈 자리", MID), ("도착", GOAL)):
    f, a = angles(p)
    print(f"    {nm:12} 팔꿈치 {f:6.1f}도  위팔 벌림 {a:5.1f}도  "
          f"{'OK' if f <= 150 else '한계초과'}")


print("\n[5] avatar.py 키프레임")
def line(t, pose, head, chest):
    return (f'                {{"t": {t}, "bones": {{\n'
            f'                    "leftShoulder": {F.rnd(pose["leftShoulder"])}, '
            f'"leftUpperArm": {F.rnd(pose["leftUpperArm"])},\n'
            f'                    "leftLowerArm": {F.rnd(pose["leftLowerArm"])}, '
            f'"leftHand": {F.rnd(pose["leftHand"])},\n'
            f'                    "head": {head}, "chest": {chest}}}}},')

SETTLE = pose_of(goal_p + (vec(BASE) - goal_p) * 0.06)

print(line(0.0, BASE, [0, 0, 0], [0, 0, 0]))
print(line(0.45, MID, [-4, 8, -2], [0, 4, 0]))
print(line(1.0, GOAL, [-9, 18, -6], [0, 8, 0]))
print(line(1.7, SETTLE, [-11, 14, -4], [0, 6, 0]))
print(line(2.4, BASE, [0, 0, 0], [0, 0, 0]))

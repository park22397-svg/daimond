# _fit_pose.py
# 손과 팔꿈치의 '위치'는 그대로 두고, 관절 뒤틀림만 푸는 도구.
#
# 사람이 슬라이더로 자세를 만들면 대개 어깨를 과하게 돌려서 맞춘다.
# 보기에는 같은 자세여도 어깨가 90도씩 꺾여 있으면 몸이 부자연스럽고,
# 다른 동작과 섞을 때 무너진다.
#
# 그래서 VRM의 실제 본 계층을 읽어 정기구학으로 손·팔꿈치·손가락의
# 위치를 구한 뒤, 그 위치를 유지하면서 각 관절이 사람이 움직일 수 있는
# 범위 안에 들어오는 값을 찾는다. 눈대중으로 숫자를 고치면 위치가 어긋난다.

import json
import math
import struct
import sys

import numpy as np

VRM_PATH = "static/avatar.vrm"


# ============================================================
# VRM 읽기
# ============================================================

def load_gltf(path):
    with open(path, "rb") as f:
        magic, ver, total = struct.unpack("<III", f.read(12))
        clen, ctype = struct.unpack("<II", f.read(8))
        return json.loads(f.read(clen).decode("utf-8"))


def quat_to_mat(q):
    x, y, z, w = q
    return np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
    ])


def euler_xyz_to_mat(deg):
    """three.js 의 기본 순서 'XYZ' — R = Rx · Ry · Rz."""
    x, y, z = [math.radians(v) for v in deg]
    cx, sx = math.cos(x), math.sin(x)
    cy, sy = math.cos(y), math.sin(y)
    cz, sz = math.cos(z), math.sin(z)
    rx = np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]])
    ry = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]])
    rz = np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]])
    return rx @ ry @ rz


class Rig:
    def __init__(self, path):
        g = load_gltf(path)
        self.nodes = g["nodes"]
        self.bone_node = {
            b["bone"]: b["node"]
            for b in g["extensions"]["VRM"]["humanoid"]["humanBones"]
        }

        self.parent = {}
        for i, n in enumerate(self.nodes):
            for c in n.get("children", []):
                self.parent[c] = i

        self.node_bone = {v: k for k, v in self.bone_node.items()}

    def chain(self, bone):
        """뿌리부터 이 본까지의 노드 순서."""
        i = self.bone_node[bone]
        out = []
        while i is not None:
            out.append(i)
            i = self.parent.get(i)
        return list(reversed(out))

    def rest_rot(self, node_i):
        q = self.nodes[node_i].get("rotation", [0, 0, 0, 1])
        return quat_to_mat(q)

    def trans(self, node_i):
        return np.array(self.nodes[node_i].get("translation", [0, 0, 0]),
                        dtype=float)

    # --------------------------------------------------------
    # 빠른 계산기
    #
    # 자세를 찾는 동안 같은 사슬을 수만 번 계산한다.
    # 뿌리부터 매번 다시 훑으면 느리므로, 바뀌지 않는 앞부분은
    # 행렬 하나로 미리 접어 두고 뒤쪽만 다시 곱한다.
    # --------------------------------------------------------

    def solver(self, marks, var_bones):
        var_nodes = {self.bone_node[b] for b in var_bones}

        plans = []
        for m in marks:
            path = self.chain(m)

            cut = 0
            for k, i in enumerate(path):
                if i in var_nodes:
                    cut = k
                    break

            prefix = np.eye(4)
            for i in path[:cut]:
                L = np.eye(4)
                L[:3, :3] = self.rest_rot(i)
                L[:3, 3] = self.trans(i)
                prefix = prefix @ L

            tail = []
            for i in path[cut:]:
                name = self.node_bone.get(i)
                tail.append((
                    name if name in var_bones else None,
                    self.rest_rot(i),
                    self.trans(i),
                ))

            plans.append((prefix, tail))

        def run(pose):
            out = []
            for prefix, tail in plans:
                M = prefix
                for name, rest, t in tail:
                    R = euler_xyz_to_mat(pose[name]) if name else rest
                    L = np.eye(4)
                    L[:3, :3] = R
                    L[:3, 3] = t
                    M = M @ L
                out.append(M[:3, 3])
            return out

        return run

    def world(self, bone, overrides):
        """overrides = {본이름: [x도, y도, z도]}. 없는 본은 기준 회전을 쓴다.

        three-vrm 은 getBoneNode(...).rotation.set() 으로 그 본의 로컬 회전을
        '덮어쓴다'. 그래서 지정한 본은 기준 회전을 버리고 준 값을 쓴다.
        """
        M = np.eye(4)
        for i in self.chain(bone):
            name = self.node_bone.get(i)
            if name in overrides:
                R = euler_xyz_to_mat(overrides[name])
            else:
                R = self.rest_rot(i)
            L = np.eye(4)
            L[:3, :3] = R
            L[:3, 3] = self.trans(i)
            M = M @ L
        return M

    def pos(self, bone, overrides):
        return self.world(bone, overrides)[:3, 3]


# ============================================================
# 최적화 — Nelder-Mead (scipy 없이)
# ============================================================

def nelder_mead(f, x0, step, lo, hi, iters=4000, tol=1e-12):
    x0 = np.array(x0, dtype=float)
    n = len(x0)

    def clip(v):
        return np.minimum(np.maximum(v, lo), hi)

    simplex = [clip(x0)]
    for i in range(n):
        v = x0.copy()
        v[i] += step[i]
        simplex.append(clip(v))

    vals = [f(s) for s in simplex]

    for _ in range(iters):
        order = np.argsort(vals)
        simplex = [simplex[i] for i in order]
        vals = [vals[i] for i in order]

        if abs(vals[-1] - vals[0]) < tol:
            break

        centroid = np.mean(simplex[:-1], axis=0)

        xr = clip(centroid + 1.0 * (centroid - simplex[-1]))
        fr = f(xr)

        if fr < vals[0]:
            xe = clip(centroid + 2.0 * (centroid - simplex[-1]))
            fe = f(xe)
            simplex[-1], vals[-1] = (xe, fe) if fe < fr else (xr, fr)
        elif fr < vals[-2]:
            simplex[-1], vals[-1] = xr, fr
        else:
            xc = clip(centroid + 0.5 * (simplex[-1] - centroid))
            fc = f(xc)
            if fc < vals[-1]:
                simplex[-1], vals[-1] = xc, fc
            else:
                for i in range(1, len(simplex)):
                    simplex[i] = clip(simplex[0] + 0.5 * (simplex[i] - simplex[0]))
                    vals[i] = f(simplex[i])

    order = np.argsort(vals)
    return simplex[order[0]], vals[order[0]]


# ============================================================
# 자세 다듬기
# ============================================================

# 사람이 실제로 낼 수 있는 범위. 넘으면 몸이 뒤틀린 것처럼 보인다.
LIMITS = {
    "Shoulder": [(-18, 18), (-22, 22), (-22, 22)],   # 쇄골. 으쓱하는 정도가 전부
    "UpperArm": [(-95, 95), (-170, 170), (-170, 170)],  # x 는 팔 축 비틀기
    "LowerArm": [(-95, 95), (-150, 150), (-150, 150)],  # 팔꿈치 + 아래팔 비틀기
}


def fit(rig, side, user_pose, verbose=True):
    """user_pose 가 만든 손·팔꿈치 위치를 지키면서 관절을 펴 준다."""

    S, U, L = f"{side}Shoulder", f"{side}UpperArm", f"{side}LowerArm"
    HAND = f"{side}Hand"

    # 위치를 견줄 지점들. 손끝까지 넣어야 손이 향하는 방향까지 지켜진다.
    marks = [
        (L, 1.0),
        (HAND, 2.0),
        (f"{side}MiddleProximal", 1.4),
        (f"{side}IndexProximal", 1.0),
        (f"{side}ThumbProximal", 1.0),
    ]
    marks = [(m, w) for m, w in marks if m in rig.bone_node]

    names = [m for m, _ in marks]
    weights = np.array([w for _, w in marks])[:, None]

    run = rig.solver(names, {S, U, L})
    target = np.array([rig.pos(m, user_pose) for m in names])

    lo = np.array([LIMITS["Shoulder"][i][0] for i in range(3)]
                  + [LIMITS["UpperArm"][i][0] for i in range(3)]
                  + [LIMITS["LowerArm"][i][0] for i in range(3)], dtype=float)
    hi = np.array([LIMITS["Shoulder"][i][1] for i in range(3)]
                  + [LIMITS["UpperArm"][i][1] for i in range(3)]
                  + [LIMITS["LowerArm"][i][1] for i in range(3)], dtype=float)

    keep = {k: v for k, v in user_pose.items() if k not in (S, U, L)}

    def unpack(p):
        d = dict(keep)
        d[S] = list(p[0:3])
        d[U] = list(p[3:6])
        d[L] = list(p[6:9])
        return d

    def cost(p):
        d = unpack(p)
        got = np.array(run(d))
        e = float(np.sum(weights * (got - target) ** 2))

        # 위치가 같은 답이 여럿이면 관절이 가장 편한 쪽을 고른다.
        e += 2.0e-6 * float(np.sum(np.array(d[S]) ** 2))        # 어깨는 되도록 가만히
        e += 2.0e-7 * float(d[U][0] ** 2)                        # 위팔 비틀기 줄이기
        e += 2.0e-7 * float(d[L][0] ** 2)                        # 아래팔 비틀기 줄이기
        return e

    best, best_v = None, float("inf")
    rng = np.random.default_rng(7)

    starts = [np.array([0, 0, 0] + user_pose.get(U, [0, 0, 0])
                       + user_pose.get(L, [0, 0, 0]), dtype=float)]
    for _ in range(80):
        starts.append(np.array(
            [rng.uniform(l, h) for l, h in zip(lo, hi)], dtype=float))

    for s in starts:
        x, v = nelder_mead(cost, np.clip(s, lo, hi),
                           np.full(9, 12.0), lo, hi, iters=1200)
        # 찾은 자리에서 한 번 더 조인다
        x, v = nelder_mead(cost, x, np.full(9, 2.0), lo, hi, iters=1500)
        if v < best_v:
            best, best_v = x, v

    out = unpack(best)
    got = np.array(run(out))

    if verbose:
        print(f"\n[{side} 팔 다듬기]")
        print(f"  {'지점':22} {'움직인 거리':>12}")
        worst = 0.0
        for k, m in enumerate(names):
            d = float(np.linalg.norm(got[k] - target[k]))
            worst = max(worst, d)
            print(f"  {m:22} {d * 1000:9.2f} mm")
        print(f"  가장 많이 어긋난 곳: {worst * 1000:.2f} mm")
        print()
        for b in (S, U, L):
            before = user_pose.get(b, [0, 0, 0])
            after = out[b]
            print(f"  {b:16} {fmt(before):26} ->  {fmt(after)}")

    return out, best_v


def fmt(v):
    return "[" + ", ".join(f"{x:7.2f}" for x in v) + "]"


def rnd(v, n=2):
    return [round(float(x), n) for x in v]


# ============================================================
# 실행
# ============================================================

if __name__ == "__main__":

    rig = Rig(VRM_PATH)

    # 사용자가 리깅 확인대에서 직접 만든 값 (캐릭터 기준 왼팔)
    user_pose = {
        "leftShoulder": [96.5, 23.5, -54.25],
        "leftUpperArm": [-3, -33.75, 92.25],
        "leftLowerArm": [49.75, 0, 130.25],
    }

    print("사용자가 만든 자세")
    for k, v in user_pose.items():
        print(f"  {k:16} {fmt(v)}")

    fixed, err = fit(rig, "left", user_pose)

    print("\n다듬은 값")
    for k in ("leftShoulder", "leftUpperArm", "leftLowerArm"):
        print(f'  "{k}": {rnd(fixed[k])},')

    # 손이 어디에 있는지 — 얼굴 옆인지 확인용
    head = rig.pos("head", fixed)
    hand = rig.pos("leftHand", fixed)
    print(f"\n  머리 {rnd(head, 3)}  손 {rnd(hand, 3)}")
    print(f"  손과 머리 거리 {np.linalg.norm(hand - head) * 100:.1f} cm")
    print(f"  손 높이 {hand[1]:.3f} m / 머리 높이 {head[1]:.3f} m")

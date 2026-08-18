# _body_shape.py
# 팔이 몸을 뚫는지 판정하기 위해, 모델의 실제 몸통 부피를 메시에서 뽑아낸다.
#
# 본 위치만으로는 몸의 두께를 알 수 없다. 그래서 정점을 직접 읽되,
# T포즈에서는 팔 정점이 몸통과 같은 높이에 있으므로 스키닝 가중치로 팔을 걸러낸다.
# 남은 정점을 높이 2cm 띠로 잘라 각 띠의 타원 단면을 구하면
# 그게 곧 '팔이 들어가면 안 되는 자리'다.

import json
import struct

import numpy as np


def read_glb(path):
    with open(path, "rb") as f:
        magic, ver, total = struct.unpack("<III", f.read(12))
        clen, ctype = struct.unpack("<II", f.read(8))
        js = json.loads(f.read(clen).decode("utf-8"))

        bin_data = b""
        while True:
            head = f.read(8)
            if len(head) < 8:
                break
            blen, btype = struct.unpack("<II", head)
            chunk = f.read(blen)
            if btype == 0x004E4942:      # BIN
                bin_data = chunk
        return js, bin_data


COMP = {
    5120: ("b", 1), 5121: ("B", 1), 5122: ("h", 2),
    5123: ("H", 2), 5125: ("I", 4), 5126: ("f", 4),
}

NUM = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}


def read_accessor(js, bin_data, idx):
    acc = js["accessors"][idx]
    n = NUM[acc["type"]]
    fmt, size = COMP[acc["componentType"]]

    bv = js["bufferViews"][acc["bufferView"]]
    start = bv.get("byteOffset", 0) + acc.get("byteOffset", 0)
    stride = bv.get("byteStride") or (n * size)

    count = acc["count"]
    dt = np.dtype("<" + fmt)

    if stride == n * size:
        raw = np.frombuffer(bin_data, dtype=dt, count=count * n, offset=start)
        return raw.reshape(count, n).astype(np.float64)

    # 사이가 벌어져 있으면 한 줄씩 뜯는다
    out = np.empty((count, n), dtype=np.float64)
    for i in range(count):
        out[i] = np.frombuffer(bin_data, dtype=dt, count=n,
                               offset=start + i * stride)
    return out


class BodyShape:
    """높이 띠마다 몸의 타원 단면을 들고 있는 것."""

    ARM_PARTS = (
        "Shoulder", "UpperArm", "LowerArm", "Hand",
        "Thumb", "Index", "Middle", "Ring", "Little",
    )

    def __init__(self, path, band=0.02, keep=0.97):
        js, bin_data = read_glb(path)
        self.js = js

        nodes = js["nodes"]
        bone_node = {
            b["bone"]: b["node"]
            for b in js["extensions"]["VRM"]["humanoid"]["humanBones"]
        }
        node_bone = {v: k for k, v in bone_node.items()}

        parent = {}
        for i, nd in enumerate(nodes):
            for c in nd.get("children", []):
                parent[c] = i

        def nearest_bone(node_i):
            i = node_i
            while i is not None:
                if i in node_bone:
                    return node_bone[i]
                i = parent.get(i)
            return None

        def is_arm(bone):
            return bool(bone) and any(p in bone for p in self.ARM_PARTS)

        # 뿌리부터의 세계 변환 (기준자세 = T포즈)
        world = {}

        def walk(i, M):
            nd = nodes[i]
            t = np.array(nd.get("translation", [0, 0, 0]), dtype=float)
            q = nd.get("rotation", [0, 0, 0, 1])
            x, y, z, w = q
            R = np.array([
                [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
            ])
            L = np.eye(4)
            L[:3, :3] = R
            L[:3, 3] = t
            W = M @ L
            world[i] = W
            for c in nd.get("children", []):
                walk(c, W)

        for s in js["scenes"][js.get("scene", 0)]["nodes"]:
            walk(s, np.eye(4))

        # 본의 기준자세 세계 위치. 캡슐의 축이 된다.
        self.bone_pos = {
            b: world[i][:3, 3] for b, i in bone_node.items() if i in world
        }
        self.bone_world = {
            b: world[i] for b, i in bone_node.items() if i in world
        }

        # 스킨의 관절 목록마다 '팔인가' 와 '어느 본에 붙는가' 를 미리 풀어 둔다
        skin_arm, skin_bone = [], []
        for skin in js.get("skins", []):
            bones = [nearest_bone(j) for j in skin["joints"]]
            skin_arm.append(np.array([is_arm(b) for b in bones], dtype=bool))
            skin_bone.append(bones)

        by_bone = {}

        # 몸이 아닌 것은 빼야 한다.
        #
        # 머리카락(트윈테일)은 허리까지 늘어져 있어 그대로 두면 몸통이
        # 반지름 20cm 로 잡히고, 원피스 치마는 밖으로 퍼져서 팔을 억지로
        # 벌리게 만든다. 팔이 뚫으면 안 되는 건 '몸' 이지 옷자락이 아니다.
        mats = js.get("materials", [])

        def skip_material(prim):
            if "material" not in prim:
                return False
            name = (mats[prim["material"]].get("name") or "").upper()
            return ("HAIR" in name) or ("ONEPIECE" in name) or ("SHOES" in name)

        pts = []
        self.used = []

        for nd in nodes:
            if "mesh" not in nd:
                continue
            if "HAIR" in (nd.get("name") or "").upper():
                continue

            mesh = js["meshes"][nd["mesh"]]
            skin_i = nd.get("skin")

            for prim in mesh.get("primitives", []):
                attrs = prim["attributes"]
                if "POSITION" not in attrs or skip_material(prim):
                    continue

                pos = read_accessor(js, bin_data, attrs["POSITION"])

                # 합쳐진 메시는 프리미티브마다 쓰는 정점이 다르다.
                # 인덱스를 봐야 이 재질이 실제로 덮는 정점만 고를 수 있다.
                if "indices" in prim:
                    idx = read_accessor(js, bin_data, prim["indices"]).astype(int).ravel()
                    keep_i = np.unique(idx)
                else:
                    keep_i = np.arange(len(pos))

                dom = None
                if skin_i is not None and "JOINTS_0" in attrs and "WEIGHTS_0" in attrs:
                    J = read_accessor(js, bin_data, attrs["JOINTS_0"]).astype(int)
                    W = read_accessor(js, bin_data, attrs["WEIGHTS_0"])
                    dom = J[np.arange(len(J)), np.argmax(W, axis=1)]
                    armv = skin_arm[skin_i][dom]
                    keep_i = keep_i[~armv[keep_i]]

                sel = pos[keep_i]

                # 어느 본이 끌고 다니는 살인지 나눠 둔다. 캡슐 굵기가 여기서 나온다.
                if dom is not None and len(sel):
                    bones = skin_bone[skin_i]
                    for j, vi in enumerate(keep_i):
                        b = bones[dom[vi]]
                        if b:
                            by_bone.setdefault(b, []).append(sel[j])

                if len(sel):
                    pts.append(sel)
                    name = mats[prim["material"]].get("name", "?") \
                        if "material" in prim else "?"
                    self.used.append((nd.get("name", "?"), name, len(sel)))

        if not pts:
            raise RuntimeError("몸 정점을 하나도 못 읽었다")

        self.verts_by_bone = {b: np.array(v) for b, v in by_bone.items()}

        P = np.vstack(pts)

        # 높이 띠마다 반지름을 구한다. 튀는 점 하나에 끌려가지 않도록 분위수를 쓴다.
        lo, hi = P[:, 1].min(), P[:, 1].max()
        n = max(1, int(np.ceil((hi - lo) / band)))

        self.y0, self.band, self.n = lo, band, n
        self.rx = np.zeros(n)
        self.rz = np.zeros(n)
        self.cx = np.zeros(n)
        self.cz = np.zeros(n)
        self.count = np.zeros(n, dtype=int)

        which = np.clip(((P[:, 1] - lo) / band).astype(int), 0, n - 1)

        for i in range(n):
            sel = P[which == i]
            self.count[i] = len(sel)
            if len(sel) < 12:
                continue
            self.cx[i] = np.median(sel[:, 0])
            self.cz[i] = np.median(sel[:, 2])
            self.rx[i] = np.quantile(np.abs(sel[:, 0] - self.cx[i]), keep)
            self.rz[i] = np.quantile(np.abs(sel[:, 2] - self.cz[i]), keep)

        # 정점이 거의 없는 띠는 이웃에서 메운다
        for i in range(n):
            if self.rx[i] == 0:
                for d in range(1, n):
                    a, b = i - d, i + d
                    if a >= 0 and self.rx[a] > 0:
                        self.rx[i], self.rz[i] = self.rx[a], self.rz[a]
                        self.cx[i], self.cz[i] = self.cx[a], self.cz[a]
                        break
                    if b < n and self.rx[b] > 0:
                        self.rx[i], self.rz[i] = self.rx[b], self.rz[b]
                        self.cx[i], self.cz[i] = self.cx[b], self.cz[b]
                        break

    # --------------------------------------------------------
    # 판정
    # --------------------------------------------------------

    def depth(self, p, margin=0.0):
        """점이 몸 안쪽으로 얼마나 들어갔는지. 0 이면 바깥.

        타원 단면 기준이라 완전한 거리는 아니지만, 얕게 스치는 것과
        깊이 박히는 것을 가르는 데는 이걸로 충분하다.
        """
        i = int(np.clip((p[1] - self.y0) / self.band, 0, self.n - 1))
        rx = self.rx[i] + margin
        rz = self.rz[i] + margin
        if rx <= 0 or rz <= 0:
            return 0.0

        dx = (p[0] - self.cx[i]) / rx
        dz = (p[2] - self.cz[i]) / rz
        r = np.hypot(dx, dz)
        if r >= 1.0:
            return 0.0

        # 안쪽으로 들어간 정도를 길이(미터)로 환산
        return float((1.0 - r) * min(rx, rz))

    def summary(self):
        out = []
        for i in range(self.n):
            y = self.y0 + (i + 0.5) * self.band
            out.append((y, self.rx[i], self.rz[i], self.count[i]))
        return out


# ============================================================
# 몸통 캡슐
#
# 높이 띠는 정점이 드문 구간에서 값이 크게 튄다.
# 본을 축으로 삼은 캡슐(원기둥+양끝 반구)로 바꾸면
# 정점이 적어도 축이 흔들리지 않아 훨씬 안정적이다.
# ============================================================

SEGMENTS = [
    ("hips", "spine"),
    ("spine", "chest"),
    ("chest", "upperChest"),
    ("upperChest", "neck"),
    ("neck", "head"),
    ("leftUpperLeg", "leftLowerLeg"),
    ("leftLowerLeg", "leftFoot"),
    ("rightUpperLeg", "rightLowerLeg"),
    ("rightLowerLeg", "rightFoot"),
]


def seg_dist(p, a, b):
    """점에서 선분까지의 거리."""
    ab = b - a
    L = float(ab @ ab)
    if L < 1e-12:
        return float(np.linalg.norm(p - a))
    t = float(np.clip((p - a) @ ab / L, 0.0, 1.0))
    return float(np.linalg.norm(p - (a + t * ab)))


class BodyCapsules:

    def __init__(self, shape, quantile=0.85):
        self.caps = []

        bone_pos = shape.bone_pos
        by_bone = shape.verts_by_bone

        for A, B in SEGMENTS:
            if A not in bone_pos or B not in bone_pos:
                continue
            a, b = bone_pos[A], bone_pos[B]

            v = by_bone.get(A)
            if v is None or len(v) < 20:
                continue

            # 몸통은 원기둥이 아니다. 좌우와 앞뒤 두께가 다르다.
            #
            # 축까지의 거리 하나로 재면 넓은 쪽에 끌려가 실제보다 두꺼워진다.
            # 윗가슴이 13.8cm 로 잡혔는데 실제로는 좌우 10.9 · 앞뒤 10.0 이었다.
            # 그 3cm 때문에 가슴 앞에 얹혀야 할 팔이 밀려났다.
            ab = b - a
            L = float(ab @ ab)
            t = np.clip((v - a) @ ab / L, 0, 1) if L > 1e-12 else np.zeros(len(v))
            off = v - (a + t[:, None] * ab)

            rx = float(np.quantile(np.abs(off[:, 0]), quantile))
            rz = float(np.quantile(np.abs(off[:, 2]), quantile))
            r = float(np.quantile(np.linalg.norm(off, axis=1), quantile))

            self.caps.append((A, a, b, r, max(rx, 0.01), max(rz, 0.01)))

        # 머리는 공으로 두면 안 된다.
        #
        # 얼굴 메시에는 눈알·입 안쪽 같은 내부 형상이 많아 중앙값이 뒤로 쏠리고,
        # 거기에 반지름 하나를 씌우면 껍데기가 실제 얼굴보다 9cm 앞으로 튀어나온다.
        # 그러면 손을 얼굴 앞에 두는 자세가 전부 '뚫었다'로 잡힌다.
        # 축마다 따로 재서 타원체로 만든다.
        self.head = None
        self.head_local = None
        if "head" in by_bone:
            hv = by_bone["head"]
            lo = np.quantile(hv, 0.005, axis=0)
            hi = np.quantile(hv, 0.995, axis=0)
            self.head = ((lo + hi) / 2, (hi - lo) / 2)

            # 고개를 숙이면 얼굴이 움직인다. 그때는 점을 머리 뼈의 자리로
            # 옮겨 놓고 재야 맞다. 그러려면 기준자세에서의 머리 좌표계가 필요하다.
            M0 = shape.bone_world.get("head")
            if M0 is not None:
                inv = np.linalg.inv(M0)
                c = np.append(self.head[0], 1.0)
                self.head_local = (inv @ c)[:3], self.head[1]

        # 자세를 찾는 동안 수십만 번 물어보므로 한꺼번에 계산할 수 있게 쌓아 둔다
        self.A = np.array([c[1] for c in self.caps])
        self.B = np.array([c[2] for c in self.caps])
        self.R = np.array([c[3] for c in self.caps])
        self.RX = np.array([c[4] for c in self.caps])
        self.RZ = np.array([c[5] for c in self.caps])
        AB = self.B - self.A
        self.AB = AB
        self.LL = np.sum(AB * AB, axis=1)
        self.LL[self.LL < 1e-12] = 1e-12

    def depths(self, P, margin=0.0, head_world=None):
        """여러 점을 한 번에. 각 점이 몸 안으로 들어간 깊이 배열을 돌려준다.

        margin 을 주면 몸이 그만큼 부푼 것으로 쳐서, 표면에 닿기 전에
        여유를 얼마나 못 지켰는지까지 잴 수 있다.
        """
        P = np.atleast_2d(P)
        d = P[:, None, :] - self.A[None, :, :]                 # (점, 캡슐, 3)
        t = np.clip(np.einsum("pkc,kc->pk", d, self.AB) / self.LL, 0.0, 1.0)
        near = self.A[None, :, :] + t[:, :, None] * self.AB[None, :, :]
        off = P[:, None, :] - near

        # 타원 단면으로 잰다. 축이 대체로 세로라 x·z 로 갈라 보면 된다.
        rx = self.RX[None, :] + margin
        rz = self.RZ[None, :] + margin
        q = np.sqrt((off[:, :, 0] / rx) ** 2 + (off[:, :, 2] / rz) ** 2
                    + 1e-12)
        thin = np.minimum(rx, rz)
        out = np.maximum(1.0 - q, 0.0) * thin

        if self.head is not None:
            if head_world is not None and self.head_local is not None:
                # 지금 고개가 향한 자리로 점을 옮겨 놓고 잰다
                inv = np.linalg.inv(head_world)
                Q = (inv[:3, :3] @ P.T).T + inv[:3, 3]
                c, r = self.head_local
            else:
                Q, (c, r) = P, self.head

            rr = r + margin
            q = np.linalg.norm((Q - c) / rr, axis=1)
            depth = np.maximum(1.0 - q, 0.0) * float(np.min(rr))
            out = np.concatenate([out, depth[:, None]], axis=1)

        return out

    def depth(self, p, margin=0.0):
        """가장 깊이 박힌 정도. 0 이면 몸 밖."""
        worst = 0.0
        for _, a, b, r in self.caps:
            d = (r + margin) - seg_dist(p, a, b)
            if d > worst:
                worst = d
        return worst

    def hit(self, p, margin=0.0):
        worst, who = 0.0, None
        P = np.atleast_2d(np.asarray(p, dtype=float))
        d = self.depths(P, margin=margin)[0]
        names = [c[0] for c in self.caps]
        if len(d):
            j = int(np.argmax(d[:len(names)])) if len(names) else 0
            if len(names) and d[j] > worst:
                worst, who = float(d[j]), names[j]

        if self.head is not None:
            c, r = self.head
            rr = r + margin
            q = float(np.linalg.norm((np.asarray(p) - c) / rr))
            d = max(0.0, 1.0 - q) * float(np.min(rr))
            if d > worst:
                worst, who = d, "head"

        return worst, who


if __name__ == "__main__":
    import sys

    bs = BodyShape("static/avatar.vrm")

    print("몸으로 셈한 부분")
    for node, mat, cnt in bs.used:
        print(f"  {node:12} {mat[:44]:44} {cnt:7} 점")

    caps = BodyCapsules(bs)
    print(f"\n몸통 캡슐 {len(caps.caps)} 개")
    print(f"  {'본':16} {'반지름':>8}   축 (기준자세)")
    for name, a, b, r, rx, rz in caps.caps:
        seg = f"{a[1]:.3f} -> {b[1]:.3f} m"
        n = len(bs.verts_by_bone.get(name, []))
        print(f"  {name:16} 좌우 {rx * 100:5.1f}cm 앞뒤 {rz * 100:5.1f}cm   "
              f"{seg:24} 정점 {n}")

    if caps.head is not None:
        c, r = caps.head
        print(f"\n  머리 타원체  중심 {np.round(c, 3)}  "
              f"반지름 좌우 {r[0] * 100:.1f}cm / 위아래 {r[1] * 100:.1f}cm / "
              f"앞뒤 {r[2] * 100:.1f}cm")
        print(f"    앞쪽 끝 z = {c[2] - r[2]:.3f} "
              f"(실제 얼굴 정점 최소 z = {bs.verts_by_bone['head'][:, 2].min():.3f})")

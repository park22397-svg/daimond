# _gen_hitboxes.py
# 마우스가 아바타의 어디를 눌렀는지 알아내기 위한 '판정구' 를 만든다.
#
# 메시를 직접 레이캐스트하면 스키닝을 라이브러리가 반영해 주는지에 따라
# 결과가 달라지고, 15MB 짜리 메시라 매 클릭마다 비싸다.
# 대신 본에 붙는 보이지 않는 공 몇 개로 몸을 덮으면
#   - 본에 붙어 있으니 자세가 바뀌어도 그대로 따라가고
#   - 맞은 공이 곧 어느 본인지 알려주며
#   - 계산이 싸다.
#
# 공의 굵기는 짐작하지 않는다. 그 본이 끌고 다니는 살에서 실제로 재서 만든다.
# 결과를 avatar.py 의 touch["hitboxes"] 에 붙여 넣는다.

import json

import numpy as np

from _body_shape import read_glb, read_accessor

VRM = "static/avatar.vrm"

# 어느 본을 어느 본까지 덮을지. (뼈, 끝나는 뼈, 공 개수)
SEGMENTS = [
    ("hips", "spine", 2),
    ("spine", "chest", 2),
    ("chest", "upperChest", 2),
    ("upperChest", "neck", 2),
    ("neck", "head", 1),
    ("leftShoulder", "leftUpperArm", 1),
    ("rightShoulder", "rightUpperArm", 1),
    ("leftUpperArm", "leftLowerArm", 3),
    ("rightUpperArm", "rightLowerArm", 3),
    ("leftLowerArm", "leftHand", 3),
    ("rightLowerArm", "rightHand", 3),
    ("leftHand", "leftMiddleProximal", 2),
    ("rightHand", "rightMiddleProximal", 2),
    ("leftUpperLeg", "leftLowerLeg", 3),
    ("rightUpperLeg", "rightLowerLeg", 3),
    ("leftLowerLeg", "leftFoot", 3),
    ("rightLowerLeg", "rightFoot", 3),
    ("leftFoot", "leftToes", 1),
    ("rightFoot", "rightToes", 1),
]

# 머리는 공 하나로는 얼굴과 정수리가 뭉뚱그려진다. 위아래로 나눠 덮는다.
HEAD_SPHERES = 3


def main():
    js, binb = read_glb(VRM)
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

    def nearest_bone(i):
        while i is not None:
            if i in node_bone:
                return node_bone[i]
            i = parent.get(i)
        return None

    world = {}

    def walk(i, M):
        nd = nodes[i]
        t = np.array(nd.get("translation", [0, 0, 0]), dtype=float)
        x, y, z, w = nd.get("rotation", [0, 0, 0, 1])
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

    bpos = {b: world[i][:3, 3] for b, i in bone_node.items() if i in world}
    bworld = {b: world[i] for b, i in bone_node.items() if i in world}

    # 본마다 그 본이 끌고 다니는 살을 모은다. 이번에는 팔도 뺀 것 없이 전부.
    mats = js.get("materials", [])
    by_bone = {}

    for nd in nodes:
        if "mesh" not in nd:
            continue
        if "HAIR" in (nd.get("name") or "").upper():
            continue

        mesh = js["meshes"][nd["mesh"]]
        skin_i = nd.get("skin")
        if skin_i is None:
            continue

        bones = [nearest_bone(j) for j in js["skins"][skin_i]["joints"]]

        for prim in mesh.get("primitives", []):
            a = prim["attributes"]
            if "POSITION" not in a or "JOINTS_0" not in a:
                continue

            name = (mats[prim["material"]].get("name") or "").upper() \
                if "material" in prim else ""
            if "HAIR" in name:
                continue

            pos = read_accessor(js, binb, a["POSITION"])
            J = read_accessor(js, binb, a["JOINTS_0"]).astype(int)
            W = read_accessor(js, binb, a["WEIGHTS_0"])
            dom = J[np.arange(len(J)), np.argmax(W, axis=1)]

            keep = np.unique(read_accessor(js, binb, prim["indices"]).astype(int).ravel()) \
                if "indices" in prim else np.arange(len(pos))

            for vi in keep:
                b = bones[dom[vi]]
                if b:
                    by_bone.setdefault(b, []).append(pos[vi])

    verts = {b: np.array(v) for b, v in by_bone.items()}

    def seg_dist(P, a, b):
        ab = b - a
        L = float(ab @ ab)
        if L < 1e-12:
            return np.linalg.norm(P - a, axis=1)
        t = np.clip((P - a) @ ab / L, 0, 1)
        return np.linalg.norm(P - (a + t[:, None] * ab), axis=1)

    boxes = []

    for A, B, n in SEGMENTS:
        if A not in bpos or B not in bpos:
            continue

        v = verts.get(A)
        if v is None or len(v) < 12:
            continue

        r = float(np.quantile(seg_dist(v, bpos[A], bpos[B]), 0.80))
        r = max(r, 0.022)

        inv = np.linalg.inv(bworld[A])

        for k in range(n):
            t = (k + 0.5) / n
            p = bpos[A] + (bpos[B] - bpos[A]) * t
            local = (inv @ np.append(p, 1.0))[:3]
            boxes.append({
                "bone": A,
                "offset": [round(float(x), 4) for x in local],
                "radius": round(r, 4),
            })

    # 머리
    if "head" in verts:
        hv = verts["head"]
        inv = np.linalg.inv(bworld["head"])
        lo = np.quantile(hv, 0.01, axis=0)
        hi = np.quantile(hv, 0.99, axis=0)

        for k in range(HEAD_SPHERES):
            t = (k + 0.5) / HEAD_SPHERES
            y = lo[1] + (hi[1] - lo[1]) * t
            band = hv[np.abs(hv[:, 1] - y) < (hi[1] - lo[1]) / (2 * HEAD_SPHERES)]
            if len(band) < 12:
                continue
            c = np.array([0.0, y, np.median(band[:, 2])])
            r = float(np.quantile(np.linalg.norm(band - c, axis=1), 0.85))
            local = (inv @ np.append(c, 1.0))[:3]
            boxes.append({
                "bone": "head",
                "offset": [round(float(x), 4) for x in local],
                "radius": round(max(r, 0.03), 4),
            })

    print(f"판정구 {len(boxes)}개\n")
    print('        "hitboxes": [')
    for b in boxes:
        print(f'            {{"bone": "{b["bone"]}", '
              f'"offset": {b["offset"]}, "radius": {b["radius"]}}},')
    print("        ],")

    print("\n\n본별 요약")
    seen = {}
    for b in boxes:
        seen.setdefault(b["bone"], []).append(b["radius"])
    for k, v in seen.items():
        print(f"  {k:22} 공 {len(v)}개  반지름 {v[0] * 100:.1f}cm")


if __name__ == "__main__":
    main()

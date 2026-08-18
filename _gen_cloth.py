# _gen_cloth.py
# 옷을 잡을 수 있게 하려면 옷이 몸과 따로 판정되어야 한다.
#
# 그런데 옷은 본이 아니라 재질이다. 치마도 배도 같은 hips 본이 끌고 다녀서,
# 본 이름만으로는 '배를 만졌다'와 '치마를 잡았다'를 구별할 수 없다.
#
# 그래서 옷 재질의 정점만 골라 따로 판정구를 만들고, 그 판정구에는
# 어느 자리인지를 직접 적어 둔다(zone). 본 -> 자리 표를 거치지 않고
# 그 값을 그대로 쓴다.
#
# 옷은 몸보다 바깥에 있으므로 화면에서 먼저 맞는다. 치마 위를 누르면
# 다리가 아니라 치마가 잡힌다.

import numpy as np

from _body_shape import read_glb, read_accessor

VRM = "static/avatar.vrm"

# 재질 이름 -> 어느 자리로 볼 것인가
CLOTH = {
    "ONEPIECE": "skirt",
    "TOPS": "top",
}

# 자리마다 높이를 몇 겹으로 나눠 덮을지
BANDS = {"skirt": 4, "top": 3}


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

    bworld = {b: world[i] for b, i in bone_node.items() if i in world}

    mats = js.get("materials", [])
    found = {}

    for nd in nodes:
        if "mesh" not in nd:
            continue
        mesh = js["meshes"][nd["mesh"]]
        skin_i = nd.get("skin")
        if skin_i is None:
            continue

        bones = [nearest_bone(j) for j in js["skins"][skin_i]["joints"]]

        for prim in mesh.get("primitives", []):
            if "material" not in prim:
                continue
            name = (mats[prim["material"]].get("name") or "").upper()

            zone = None
            for tag, z in CLOTH.items():
                if tag in name:
                    zone = z
            if zone is None:
                continue

            a = prim["attributes"]
            pos = read_accessor(js, binb, a["POSITION"])
            J = read_accessor(js, binb, a["JOINTS_0"]).astype(int)
            W = read_accessor(js, binb, a["WEIGHTS_0"])
            dom = J[np.arange(len(J)), np.argmax(W, axis=1)]

            keep = np.unique(
                read_accessor(js, binb, prim["indices"]).astype(int).ravel()) \
                if "indices" in prim else np.arange(len(pos))

            for vi in keep:
                b = bones[dom[vi]]
                if b:
                    found.setdefault(zone, {}).setdefault(b, []).append(pos[vi])

            print(f"  {mats[prim['material']]['name'][:40]:40} -> {zone} "
                  f"({len(keep)}점)")

    boxes = []

    for zone, per_bone in found.items():
        n_bands = BANDS.get(zone, 3)

        for bone, pts in per_bone.items():
            P = np.array(pts)
            if len(P) < 30:
                continue

            lo, hi = np.quantile(P[:, 1], 0.02), np.quantile(P[:, 1], 0.98)
            if hi - lo < 1e-4:
                continue

            inv = np.linalg.inv(bworld[bone])

            for k in range(n_bands):
                y0 = lo + (hi - lo) * k / n_bands
                y1 = lo + (hi - lo) * (k + 1) / n_bands
                band = P[(P[:, 1] >= y0) & (P[:, 1] <= y1)]
                if len(band) < 20:
                    continue

                c = band.mean(axis=0)
                r = float(np.quantile(np.linalg.norm(band - c, axis=1), 0.75))
                r = max(min(r, 0.16), 0.03)

                local = (inv @ np.append(c, 1.0))[:3]
                boxes.append({
                    "bone": bone,
                    "zone": zone,
                    "offset": [round(float(v), 4) for v in local],
                    "radius": round(r, 4),
                })

    print(f"\n옷 판정구 {len(boxes)}개\n")
    for b in boxes:
        print(f'            {{"bone": "{b["bone"]}", "zone": "{b["zone"]}", '
              f'"offset": {b["offset"]}, "radius": {b["radius"]}}},')

    print("\n자리별")
    per = {}
    for b in boxes:
        per.setdefault(b["zone"], []).append(b)
    for z, lst in per.items():
        print(f"  {z:6} 공 {len(lst)}개  본 {sorted({x['bone'] for x in lst})}")


if __name__ == "__main__":
    main()

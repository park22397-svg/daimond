# _fit_mouth.py
# 입 자리(head_split)를 실측으로 맞춘다.
#
# 이 값은 두 번 틀리기 쉽다.
#
#   1) 부위를 눈대중으로 잡는 것.
#      모프가 움직이는 정점이 곧 그 부위다. Fcl_MTH_* 가 움직이는
#      자리가 입이고 Fcl_EYE_* 가 움직이는 자리가 눈이다. 재면 된다.
#
#   2) 얼굴 표면 좌표를 그대로 적는 것.
#      판정은 메시가 아니라 **본에 붙은 공** 에서 일어난다. 공은
#      얼굴보다 크고 앞으로 나와 있어서, 같은 자리를 겨눠도 공에
#      맞는 점의 y 가 얼굴 표면보다 위다.
#
#      2026-08-19 에 실제로 이걸 겪었다. 얼굴 표면을 재서 넣은
#      mouth_y(-0.005) 때문에 **입술은 늘 '얼굴' 이 되고 턱을 눌러야
#      입이 됐다.** 눈으로는 원인이 안 보인다.
#
# 그래서 이 스크립트는 둘 다 한다 — 모프로 부위를 재고, 그 자리를
# 겨눈 광선이 공 위 어디에 맞는지까지 계산해서 지금 값으로 판정해 본다.

import json
import math
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from avatar import AVATAR

HERE = os.path.dirname(os.path.abspath(__file__))
VRM = os.path.join(HERE, "static", "avatar.vrm")


# ============================================================
# 1) 모프로 부위를 잰다
# ============================================================

def read_glb(path):
    with open(path, "rb") as f:
        struct.unpack("<III", f.read(12))
        clen, _ = struct.unpack("<II", f.read(8))
        js = json.loads(f.read(clen).decode("utf-8"))
        blob = b""
        while True:
            head = f.read(8)
            if len(head) < 8:
                break
            blen, btype = struct.unpack("<II", head)
            chunk = f.read(blen)
            if btype == 0x004E4942:
                blob = chunk
        return js, blob


COMP = {5126: ("f", 4), 5123: ("H", 2), 5125: ("I", 4), 5121: ("B", 1)}
NUM = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4}

PREFIX = {
    "Fcl_MTH_": "입",
    "Fcl_EYE_": "눈",
    "Fcl_BRW_": "눈썹",
}


def measure():
    g, blob = read_glb(VRM)

    def acc(i):
        a = g["accessors"][i]
        n = NUM[a["type"]]
        fmt, size = COMP[a["componentType"]]
        bv = g["bufferViews"][a["bufferView"]]
        start = bv.get("byteOffset", 0) + a.get("byteOffset", 0)
        stride = bv.get("byteStride") or (size * n)
        return [struct.unpack_from("<" + fmt * n, blob, start + k * stride)
                for k in range(a["count"])]

    nodes = g["nodes"]
    parent = {}
    for i, nd in enumerate(nodes):
        for c in nd.get("children", []):
            parent[c] = i

    hb = {b["bone"]: b["node"]
          for b in g["extensions"]["VRM"]["humanoid"]["humanBones"]}

    def world_of(i):
        p = [0.0, 0.0, 0.0]
        while i is not None:
            t = nodes[i].get("translation", [0, 0, 0])
            p = [p[k] + t[k] for k in range(3)]
            i = parent.get(i)
        return p

    head = world_of(hb["head"])
    groups = {}

    for mesh in g["meshes"]:
        for prim in mesh.get("primitives", []):
            targets = prim.get("targets") or []
            names = ((mesh.get("extras") or {}).get("targetNames")
                     or (prim.get("extras") or {}).get("targetNames") or [])
            if not targets or not names:
                continue

            pos = None
            for ti, tgt in enumerate(targets):
                if ti >= len(names) or "POSITION" not in tgt:
                    continue

                label = next((v for k, v in PREFIX.items()
                              if names[ti].startswith(k)), None)
                if label is None:
                    continue

                if pos is None:
                    pos = acc(prim["attributes"]["POSITION"])

                for k, v in enumerate(acc(tgt["POSITION"])):
                    if math.sqrt(sum(c * c for c in v)) < 0.0015:
                        continue
                    p = pos[k]
                    groups.setdefault(label, []).append(
                        tuple(p[j] - head[j] for j in range(3)))

    return head, groups


def band(vals, cut=0.02):
    """바깥 cut 만큼은 버린다 — 모프 가장자리가 넓게 번진다."""
    v = sorted(vals)
    return v[int(len(v) * cut)], v[int(len(v) * (1 - cut))]


# ============================================================
# 2) 그 자리를 겨누면 공 위 어디에 맞는가
# ============================================================

def hit_ball(o, d, c, r):
    ox, oy, oz = (o[k] - c[k] for k in range(3))
    b = 2 * (ox * d[0] + oy * d[1] + oz * d[2])
    cc = ox * ox + oy * oy + oz * oz - r * r
    disc = b * b - 4 * cc
    if disc < 0:
        return None
    s = math.sqrt(disc)
    for t in sorted(((-b - s) / 2, (-b + s) / 2)):
        if t > 1e-6:
            return t
    return None


def main():
    if not os.path.isfile(VRM):
        print("static/avatar.vrm 이 없습니다.")
        return 0

    head, groups = measure()
    print(f"머리 본  y {head[1]:.4f}\n")

    print("[1] 모프가 움직이는 자리 — 얼굴 표면 (머리 본 기준)")
    for label in ("입", "눈", "눈썹"):
        pts = groups.get(label)
        if not pts:
            continue
        xl, xh = band([p[0] for p in pts])
        yl, yh = band([p[1] for p in pts])
        zl, zh = band([p[2] for p in pts])
        print(f"  {label:4} |x| {max(abs(xl), abs(xh)):.4f}   "
              f"y {yl:+.4f} ~ {yh:+.4f}   z {zl:+.4f} ~ {zh:+.4f}")

    # 겨눌 자리 — 위에서 잰 값으로 만든다
    m = groups["입"]
    mx = max(abs(v) for v in band([p[0] for p in m]))
    myl, myh = band([p[1] for p in m])
    mz = sum(band([p[2] for p in m])) / 2

    e = groups["눈"]
    eyl, eyh = band([p[1] for p in e])

    spots = [
        ("입술 아래", (0.0, myl, mz)),
        ("입술 가운데", (0.0, (myl + myh) / 2, mz)),
        ("입술 위", (0.0, myh, mz)),
        ("입 끝", (-mx, (myl + myh) / 2, mz + 0.006)),
        ("턱", (0.0, myl - 0.030, mz + 0.011)),
        ("코", (0.0, myh + 0.013, mz - 0.014)),
        # '눈 아래' 를 눈 모프의 맨 아랫자락(eyl)으로 잡으면 안 된다.
        # 눈 모프는 감을 때 볼까지 끌고 내려가서, 그 아랫자락은
        # 이미 입의 범위 안이다. 입 위쪽에서 조금 띄우고 옆으로
        # 비켜 잡아야 '눈 아래' 라는 이름값을 한다.
        ("눈 아래", (-0.030, myh + 0.010, mz - 0.001)),
        ("눈 가운데", (-0.035, (eyl + eyh) / 2, mz - 0.001)),
    ]

    ground = AVATAR.locomotion.get("ground_y", -0.2)
    head_w = head[1] + ground
    eye_h = 1.33

    balls = [(h["offset"], h["radius"])
             for h in AVATAR.touch["hitboxes"] if h["bone"] == "head"]

    cut = AVATAR.touch["head_split"]

    def judge(p):
        if (p[1] <= cut["mouth_y"] and p[2] <= cut["mouth_z"]
                and abs(p[0]) <= cut["mouth_x"]):
            return "입"
        if p[1] >= cut["top_y"]:
            return "정수리"
        return "얼굴" if p[2] <= cut["front_z"] else "뒤통수"

    def aim(spot, dist):
        # 판정구는 회전하기 전 모델 좌표에 있다. 그 좌표계에서
        # 얼굴은 -z 를 향하므로 보는 사람도 -z 쪽에 세운다.
        o = (0.0, eye_h, -dist)
        t = (spot[0], head_w + spot[1], spot[2])
        d = [t[k] - o[k] for k in range(3)]
        n = math.sqrt(sum(k * k for k in d))
        d = [k / n for k in d]

        best = None
        for off, r in balls:
            c = (off[0], head_w + off[1], off[2])
            tt = hit_ball(o, d, c, r)
            if tt is not None and (best is None or tt < best[0]):
                p = [o[k] + d[k] * tt for k in range(3)]
                best = (tt, (p[0], p[1] - head_w, p[2]))
        return best[1] if best else None

    gap = AVATAR.locomotion.get("personal_space", 0.38)
    near = AVATAR.locomotion.get("follow_near", 0.72)

    print(f"\n[2] 겨눴을 때 판정구 위 어디에 맞는가  (눈높이 {eye_h})")
    print(f"    자르는 값: mouth_y {cut['mouth_y']} · "
          f"mouth_x {cut['mouth_x']} · mouth_z {cut['mouth_z']}")

    want = {"입술 아래": "입", "입술 가운데": "입",
            "입 끝": "입", "턱": "입",
            "코": "얼굴", "눈 아래": "얼굴", "눈 가운데": "얼굴"}

    # 여기는 어긋나도 실패로 세지 않는다.
    #
    # 윗입술 맨 위와 코는 거리에 따라 공 위에서 같은 높이에 맞는다.
    # 바짝 붙어서 겨눈 윗입술 끝(+0.0355)과 멀찍이서 겨눈 코(+0.0359)가
    # 사실상 같은 값이라, 하나로 자르면 둘 중 하나는 반드시 틀린다.
    #
    # 코가 입이 되는 쪽보다 윗입술 1mm 가 얼굴이 되는 쪽이 낫다.
    # 입술 가운데와 끝은 두 거리 모두에서 제대로 잡히므로
    # 겨누는 데 지장이 없다.
    soft = {"입술 위"}

    fails = 0

    for dist in (gap, near):
        print(f"\n  {dist:.2f}m 앞에서")
        for name, spot in spots:
            p = aim(spot, dist)
            if p is None:
                print(f"    {name:<10} (안 맞음)")
                continue

            got = judge(p)

            if name in soft:
                print(f"    {name:<10} y {p[1]:+.4f}  x {abs(p[0]):.4f}"
                      f"   -> {got:<4} (경계 — 어느 쪽이든 둔다)")
                continue

            ok = got == want[name]
            if not ok:
                fails += 1
            print(f"    {name:<10} y {p[1]:+.4f}  x {abs(p[0]):.4f}"
                  f"   -> {got:<4} {'' if ok else '<-- ' + want[name] + ' 여야 한다'}")

    print("\n" + ("전부 맞다" if fails == 0 else f"{fails}건 어긋난다"))
    return 0 if fails == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

# _skin_check.py
# 자세를 준 상태의 '진짜 살'을 계산해 두 부위가 겹치는지 본다.
#
# 본 축까지의 거리로 판정하면 엉뚱한 답이 나온다. 엄지 뿌리 본에는
# 손바닥 살까지 딸려 있어 반지름이 1.87cm 로 잡히는데, 그건 엄지 굵기가
# 아니다. 그 값으로 기준을 세우면 실제로는 멀쩡한 자세도 '뚫었다'가 된다.
#
# 그래서 스키닝을 직접 계산한다. 정점마다 붙은 본들의 지금 자세를
# 가중치대로 섞어 정점을 옮기면, 그게 화면에 보이는 살이다.
# 두 부위의 살이 실제로 얼마나 가까운지는 그걸로만 알 수 있다.

import numpy as np

import _fit_pose as F
from _body_shape import read_glb, read_accessor


class SkinnedHand:

    def __init__(self, path, side="right"):
        self.rig = F.Rig(path)
        js, binb = read_glb(path)
        self.js = js
        self.side = side

        nodes = js["nodes"]
        self.node_bone = {v: k for k, v in self.rig.bone_node.items()}

        # 손과 손가락 정점만 모은다
        groups = {}

        for nd in nodes:
            if "mesh" not in nd or nd.get("skin") is None:
                continue
            if "HAIR" in (nd.get("name") or "").upper():
                continue

            skin = js["skins"][nd["skin"]]
            joints = skin["joints"]
            ibm = read_accessor(js, binb, skin["inverseBindMatrices"])

            for prim in js["meshes"][nd["mesh"]].get("primitives", []):
                a = prim["attributes"]
                if "POSITION" not in a or "JOINTS_0" not in a:
                    continue

                pos = read_accessor(js, binb, a["POSITION"])
                J = read_accessor(js, binb, a["JOINTS_0"]).astype(int)
                W = read_accessor(js, binb, a["WEIGHTS_0"])

                keep = np.unique(
                    read_accessor(js, binb, prim["indices"]).astype(int).ravel()
                ) if "indices" in prim else np.arange(len(pos))

                dom = J[np.arange(len(J)), np.argmax(W, axis=1)]

                for vi in keep:
                    bone = self._bone_of(joints[dom[vi]])
                    if not bone or not bone.startswith(side):
                        continue
                    part = self._part(bone)
                    if part is None:
                        continue
                    groups.setdefault(part, []).append(
                        (pos[vi], J[vi], W[vi], joints, ibm, bone)
                    )

        self.groups = groups
        self.joints_cache = {}

    def _bone_of(self, node_i):
        i = node_i
        while i is not None:
            if i in self.node_bone:
                return self.node_bone[i]
            i = self.rig.parent.get(i)
        return None

    def _part(self, bone):
        s = self.side
        for f in ("Thumb", "Index", "Middle", "Ring", "Little"):
            if bone.startswith(s + f):
                return f
        if bone == s + "Hand":
            return "Hand"
        return None

    def counts(self):
        return {k: len(v) for k, v in self.groups.items()}

    def posed(self, part, pose, only_bone=None):
        """자세를 준 뒤의 정점 위치.

        only_bone 을 주면 그 본이 끌고 다니는 살만 고른다.
        엄지 '끝마디' 만 보고 싶을 때 쓴다 — 뿌리는 어떤 자세에서도
        손바닥에 붙어 있어서 같이 재면 값이 그쪽에 묶인다.
        """
        out = []
        cache = {}

        for v, jidx, wts, joints, ibm, bone in self.groups[part]:
            if only_bone is not None and bone != only_bone:
                continue
            p = np.zeros(3)
            total = 0.0

            for k in range(4):
                w = float(wts[k])
                if w <= 1e-6:
                    continue

                node_i = joints[int(jidx[k])]
                if node_i not in cache:
                    bone = self._bone_of(node_i)
                    if bone is None:
                        cache[node_i] = None
                    else:
                        M = self.rig.world(bone, pose)
                        B = ibm[int(jidx[k])].reshape(4, 4, order="F")
                        cache[node_i] = M @ B

                S = cache[node_i]
                if S is None:
                    continue

                p += w * (S[:3, :3] @ v + S[:3, 3])
                total += w

            if total > 1e-6:
                out.append(p / total)

        return np.array(out)

    def gap(self, pose, a="Thumb", b="Index"):
        """두 부위의 살이 가장 가까운 거리. 0 에 가까우면 붙은 것이다.

        다만 이 값만으로는 부족하다. 엄지 뿌리와 손바닥은 어떤 자세에서도
        붙어 있어서, 정작 알고 싶은 '엄지 끝이 검지를 뚫었는가' 가 묻힌다.
        그건 아래 tip_into() 로 본다.
        """
        A = self.posed(a, pose)
        B = self.posed(b, pose)
        if not len(A) or not len(B):
            return None
        d = np.linalg.norm(A[:, None, :] - B[None, :, :], axis=2)
        return float(d.min())

    def _polyline_dist(self, P, pts):
        """점들에서 꺾은선까지의 거리."""
        best = None
        for a, b in zip(pts[:-1], pts[1:]):
            ab = b - a
            L = float(ab @ ab)
            if L < 1e-12:
                d = np.linalg.norm(P - a, axis=1)
            else:
                t = np.clip((P - a) @ ab / L, 0, 1)
                d = np.linalg.norm(P - (a + t[:, None] * ab), axis=1)
            best = d if best is None else np.minimum(best, d)
        return best

    def tip_into(self, pose, tip="Thumb", body="Index"):
        """엄지 끝이 검지 살 속으로 얼마나 들어갔는가.

        검지를 제 정점으로 굵기를 잰 원기둥으로 보고,
        엄지 끝 정점들이 그 안으로 들어갔는지 잰다.
        양수면 파고든 것이고, 음수면 그만큼 떨어져 있는 것이다.
        """
        s = self.side
        axis = [self.rig.pos(f"{s}{body}{j}", pose)
                for j in ("Proximal", "Intermediate", "Distal")]
        axis = np.array(axis)

        skin = self.posed(body, pose)
        if not len(skin):
            return None

        # 검지 자신의 살로 굵기를 잰다. 손바닥은 섞이지 않는다.
        r = float(np.quantile(self._polyline_dist(skin, axis), 0.85))

        tips = self.posed(tip, pose)
        # 엄지 끝쪽 절반만 본다. 뿌리는 원래 손바닥에 묻혀 있다.
        root = self.rig.pos(f"{s}{tip}Proximal", pose)
        end = self.rig.pos(f"{s}{tip}Distal", pose)
        far = np.linalg.norm(tips - root, axis=1) > \
            0.5 * float(np.linalg.norm(end - root))
        tips = tips[far]
        if not len(tips):
            return None, r

        d = self._polyline_dist(tips, axis)
        return float(r - d.min()), r


if __name__ == "__main__":
    import _fit_rps as R

    sk = SkinnedHand("static/avatar.vrm", "right")
    print("모은 정점:", sk.counts())

    ORIG = {"rock": {"in": 34, "bend": (28, 30, 20)},
            "scissors": {"in": 30, "bend": (26, 28, 18)}}
    OPEN = {"in": -8, "bend": (0, 0, 0)}

    def blend(a, b, f):
        return {"in": round(a["in"] + (b["in"] - a["in"]) * f, 1),
                "bend": tuple(round(x + (y - x) * f, 1)
                              for x, y in zip(a["bend"], b["bend"]))}

    print("\n엄지 살과 검지 살이 실제로 얼마나 떨어져 있는가")
    print("(0 이면 서로 파고든 것이다. 0.3~0.6cm 면 자연스럽게 닿은 정도)\n")

    for shape in ("rock", "scissors"):
        print(f"[{shape}]  0% = 원래(접음)   100% = 편 것")
        saved = R.SHAPES[shape]["thumb"]
        for f in (0.0, 0.15, 0.25, 0.3, 0.35, 0.4, 0.5, 0.65, 1.0):
            R.SHAPES[shape]["thumb"] = blend(ORIG[shape], OPEN, f)
            p = dict(R.BASE_ARM)
            p.update(R.hand("right", shape))
            into, r = sk.tip_into(p, "Thumb", "Index")
            if into > 0.001:
                tag = f"엄지 끝이 검지 속으로 {into * 100:.2f}cm 파고듦"
            elif into > -0.004:
                tag = "닿을 듯 말 듯"
            else:
                tag = f"{-into * 100:.2f}cm 떨어짐"
            print(f"   {f:4.0%}  {tag}")
        R.SHAPES[shape]["thumb"] = saved
        print(f"   (검지 굵기 반지름 {r * 100:.2f}cm)\n")

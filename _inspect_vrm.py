# _inspect_vrm.py
# static/avatar.vrm 을 직접 열어 지금 개체 설정과 맞는지 확인한다.
# (브라우저 없이 .glb 의 JSON 청크만 읽는다)

import datetime
import json
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from avatar import AVATAR

HERE = os.path.dirname(os.path.abspath(__file__))
PATH = os.path.join(HERE, "static", "avatar.vrm")


def read_gltf_json(path):
    with open(path, "rb") as f:
        magic, version, _ = struct.unpack("<III", f.read(12))
        if magic != 0x46546C67:
            raise ValueError("glTF(glb) 파일이 아닙니다")
        chunk_len, chunk_type = struct.unpack("<II", f.read(8))
        if chunk_type != 0x4E4F534A:
            raise ValueError("첫 청크가 JSON이 아닙니다")
        return json.loads(f.read(chunk_len).decode("utf-8")), version


fails = 0
warns = 0

size = os.path.getsize(PATH)
print(f"파일 : {os.path.relpath(PATH, HERE)}")
print(f"크기 : {size / 1024 / 1024:.2f} MB")
print(f"수정 : {datetime.datetime.fromtimestamp(os.path.getmtime(PATH)):%Y-%m-%d %H:%M:%S}")

gltf, glb_ver = read_gltf_json(PATH)
ext = gltf.get("extensions") or {}
vrm0 = ext.get("VRM")
vrm1 = ext.get("VRMC_vrm")

spec = "0.x" if vrm0 else ("1.0" if vrm1 else "알 수 없음")
print(f"VRM  : {spec}   (glb v{glb_ver})")

meta = (vrm0 or {}).get("meta") or (vrm1 or {}).get("meta") or {}
print(f"이름 : {meta.get('title') or meta.get('name') or '(없음)'}")


# ------------------------------------------------------------
# 지금 개체가 실제로 쓰는 본 목록
# ------------------------------------------------------------

needed = set(AVATAR.base_pose.keys())
for m in AVATAR.motions:
    needed.update(m.channels())

if vrm0:
    have = {
        b.get("bone")
        for b in ((vrm0.get("humanoid") or {}).get("humanBones") or [])
        if b.get("bone")
    }
elif vrm1:
    have = set(((vrm1.get("humanoid") or {}).get("humanBones") or {}).keys())
else:
    have = set()

print(f"\n[1] 휴머노이드 본 — 모델 보유 {len(have)}개")
missing = sorted(needed - have)
if missing:
    fails += 1
    print(f"  FAIL  모션이 쓰는데 모델에 없는 본: {missing}")
else:
    print(f"  PASS  모션·기준자세가 쓰는 본 {len(needed)}개 전부 있음")
    print(f"        {', '.join(sorted(needed))}")


# ------------------------------------------------------------
# 표정 블렌드셰이프
# ------------------------------------------------------------

print("\n[2] 표정 블렌드셰이프")

if vrm0:
    groups = ((vrm0.get("blendShapeMaster") or {}).get("blendShapeGroups") or [])
    names = []
    for g in groups:
        preset = (g.get("presetName") or "").strip()
        name = (g.get("name") or "").strip()
        names.append(preset if preset and preset != "unknown" else name)
    names = [n for n in names if n]
elif vrm1:
    names = list(((vrm1.get("expressions") or {}).get("preset") or {}).keys())
    names += list(((vrm1.get("expressions") or {}).get("custom") or {}).keys())
else:
    names = []

lowered = {n.lower(): n for n in names}
print(f"  모델 보유 {len(names)}개: {', '.join(names)}")

used = set()
for e in AVATAR.expressions:
    used.update(e.blendshapes.keys())
    used.update(e.fallback_blendshapes.keys())

miss_shape = sorted(s for s in used if s.lower() not in lowered)
if miss_shape:
    fails += 1
    print(f"  FAIL  표정이 쓰는데 모델에 없는 블렌드셰이프: {miss_shape}")
else:
    print(f"  PASS  표정이 쓰는 {len(used)}개 전부 있음: {', '.join(sorted(used))}")

# 놀람은 파일마다 이름이 달라 런타임에 찾는다. 후보가 있는지 확인.
def norm(v):
    return str(v).lower().replace(" ", "").replace("_", "").replace("-", "")

cands = [n for n in names if "surpris" in norm(n) or norm(n) in ("odoroki", "놀람")]
if cands:
    print(f"  PASS  놀람 자동탐색 후보: {cands}")
else:
    warns += 1
    print("  WARN  놀람용 커스텀 표정이 없음 -> joy 0.18 + fun 0.12 조합으로 대체됨")


# ------------------------------------------------------------
# 결론
# ------------------------------------------------------------

print("\n[3] 결론")
if fails:
    print(f"  {fails}건 호환 문제 — 모션이나 표정이 정상 동작하지 않습니다")
else:
    print("  지금 개체 설정(모션 5종·표정 6종)이 이 모델에서 그대로 동작합니다")
    if warns:
        print(f"  ({warns}건은 대체 동작으로 처리됨)")

print("\n  ※ 팔 회전 부호와 기준자세(팔 내림 68.75도)는 이전 모델에서 맞춘 값입니다.")
print("     본 구성이 같아도 리깅이 다르면 자세가 어긋날 수 있어 화면 확인이 필요합니다.")

sys.exit(0 if fails == 0 else 1)

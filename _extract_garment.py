# _extract_garment.py
# VRoid 에서 내보낸 VRM 한 벌에서 **옷만** 떼어 작은 VRM 으로 굽는다.
#
#   python _extract_garment.py 맨몸.vrm 옷입은.vrm --name 교복
#
# 왜 glb 가 아니라 VRM 으로 굽는가
# --------------------------------
# 화면(index.html)에는 VRM 을 두 벌 겹쳐 쓰는 길(loadBody)이 이미 나 있다.
# 옷을 VRM 으로 구우면 그 길을 그대로 탄다. 덤으로
#   * MToon 재질값(_Color, 그림자색, 외곽선)이 살아남는다 — 맨 glb 로 구우면
#     three 가 PBR 로 읽어 색이 달라진다
#   * 치마 흔들림 본(secondaryAnimation)이 살아남는다
#
# 몸 가리기
# ---------
# VRoid 는 옷에 가린 몸 삼각형을 지워서 내보낸다(교복에서는 맨몸의 16.6%).
# 옷만 떼어다 맨몸 위에 얹으면 그 지운 자리가 되살아나 옷을 뚫고 비친다.
# 그래서 **맨몸의 어느 삼각형을 감출지**도 같이 계산해 wardrobe.json 에 적는다.
#
# 함정 둘 (실제로 밟았다)
# -----------------------
# 1. 한 메시의 프리미티브들은 **정점 버퍼를 함께 쓴다.** 프리미티브마다
#    POSITION 개수를 세면 전부 같은 수가 나온다. indices 로 실제 쓰는
#    정점만 골라내야 한다.
# 2. 같은 캐릭터라도 내보낼 때마다 모델이 **통째로 0.3mm쯤 밀린다**(hips).
#    그 오프셋을 빼지 않고 견주면 "전부 다르다" 는 헛 결론이 나온다.

import argparse
import base64
import json
import os
import struct
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

GLB_MAGIC = 0x46546C67
CHUNK_JSON = 0x4E4F534A
CHUNK_BIN = 0x004E4942

COMP = {5120: 'i1', 5121: 'u1', 5122: 'i2', 5123: 'u2', 5125: 'u4', 5126: 'f4'}
NCOMP = {'SCALAR': 1, 'VEC2': 2, 'VEC3': 3, 'VEC4': 4, 'MAT4': 16}

# 떼어 낼 수 있는 것들.
#
# VRoid 는 재질 이름에 무엇인지 적어 둔다 — 옷은 _CLOTH, 안경은 Glasses,
# 머리카락은 _HAIR. 그 이름으로 골라낸다.
# ★ 머리카락(_HAIR)은 기본에서 뺀다.
#   바탕 아바타가 이미 머리를 갖고 있어서, 넣으면 옷에 머리가 딸려 들어온다
#   (교복이 1.4MB 에서 3.5MB 로 불고 카라 밀기가 머리 정점 4천 개를 건드렸다).
#   머리를 갈아 끼우려면 `--hair` 로 부른다.
ITEM_MARKS = ('_CLOTH', 'Glasses', 'GLASS')
HAIR_MARKS = ('_HAIR',)

# 어느 칸에 걸리는가.
#
# 칸이 다르면 같이 입을 수 있다 — 교복을 입은 채로 안경을 쓴다.
# 같은 칸이면 갈아입는 것이다.
SLOT_OF_ZONE = {
    'glasses': 'glasses',
    'accessory': 'glasses',
    'hair': 'hair',
    'top': 'outfit',
    'skirt': 'outfit',
    'shoes': 'outfit',
    'socks': 'outfit',
}

SLOT_LABEL = {'outfit': '옷', 'glasses': '안경', 'hair': '머리'}


def slot_of(zones):
    """떼어 낸 부위들로 어느 칸인지 정한다.

    옷이 하나라도 섞여 있으면 옷 칸이다 — 교복에 리본이 딸려 오는 것처럼
    장신구가 옷의 일부인 경우가 있기 때문이다.
    """
    slots = {SLOT_OF_ZONE.get(z.get('zone')) for z in zones}
    slots.discard(None)

    for want in ('outfit', 'hair', 'glasses'):
        if want in slots:
            return want

    return 'outfit'


# ------------------------------------------------------------------
# 읽기
# ------------------------------------------------------------------

def load_glb(path):
    with open(path, 'rb') as f:
        magic, _ver, total = struct.unpack('<III', f.read(12))
        if magic != GLB_MAGIC:
            raise ValueError(path + ' 은 glb(vrm) 가 아니다')
        chunks = {}
        while f.tell() < total:
            ln, ty = struct.unpack('<II', f.read(8))
            chunks[ty] = f.read(ln)
    return json.loads(chunks[CHUNK_JSON].decode('utf-8')), chunks[CHUNK_BIN]


def acc_read(g, bin_, i):
    """접근자 하나를 numpy 로. 촘촘한(interleaved 아닌) 것만 다룬다."""
    a = g['accessors'][i]
    n = NCOMP[a['type']]
    if 'bufferView' not in a:
        return np.zeros((a['count'], n) if n > 1 else a['count'],
                        dtype=np.dtype('<' + COMP[a['componentType']]))
    bv = g['bufferViews'][a['bufferView']]
    stride = bv.get('byteStride')
    dt = np.dtype('<' + COMP[a['componentType']])
    off = bv.get('byteOffset', 0) + a.get('byteOffset', 0)
    if stride and stride != dt.itemsize * n:
        raw = np.frombuffer(bin_, dtype='u1',
                            count=stride * a['count'], offset=off)
        raw = raw.reshape(a['count'], stride)[:, :dt.itemsize * n]
        arr = np.ascontiguousarray(raw).view(dt).reshape(a['count'], n)
    else:
        arr = np.frombuffer(bin_, dtype=dt, count=a['count'] * n, offset=off)
        arr = arr.reshape(a['count'], n)
    return arr if n > 1 else arr.reshape(-1)


def mat_name(g, p):
    return g['materials'][p['material']]['name'] if 'material' in p else ''


def find_prims(g, pred):
    """조건에 맞는 프리미티브를 (메시번호, 프리미티브, 재질이름) 으로."""
    out = []
    for mi, mesh in enumerate(g['meshes']):
        for p in mesh['primitives']:
            nm = mat_name(g, p)
            if pred(nm):
                out.append((mi, p, nm))
    return out


def prim_vertices(g, bin_, p):
    """이 프리미티브가 실제로 쓰는 정점 자리만."""
    idx = acc_read(g, bin_, p['indices']).astype(np.int64)
    pos = acc_read(g, bin_, p['attributes']['POSITION']).astype(np.float64)
    used = np.unique(idx)
    return pos[used], idx


# ------------------------------------------------------------------
# 구역 이름 붙이기 — 개체의 표를 그대로 쓴다
# ------------------------------------------------------------------

def zone_of(name):
    """avatar.py 의 model_parts 표로 재질 이름에서 구역을 읽는다."""
    try:
        from avatar import AVATAR
        table = AVATAR.model_parts
    except Exception:
        table = []
    low = name.lower()
    for row in table:
        m = row.get('match')
        if m and m in low:
            return row['zone']
    return None


# ------------------------------------------------------------------
# 쓰기 — 새 glb 를 짓는다
# ------------------------------------------------------------------

class Builder:
    """접근자와 bufferView 를 새로 쌓아 하나의 BIN 으로 굽는다."""

    def __init__(self):
        self.blob = bytearray()
        self.views = []
        self.accessors = []

    def _view(self, data, target=None):
        while len(self.blob) % 4:
            self.blob.append(0)
        off = len(self.blob)
        self.blob += data
        v = {'buffer': 0, 'byteOffset': off, 'byteLength': len(data)}
        if target:
            v['target'] = target
        self.views.append(v)
        return len(self.views) - 1

    def raw(self, data):
        """텍스처처럼 그대로 옮길 것."""
        return self._view(bytes(data))

    def array(self, arr, type_, comp, target=None, minmax=False):
        arr = np.ascontiguousarray(arr)
        vi = self._view(arr.tobytes(), target)
        a = {
            'bufferView': vi,
            'componentType': comp,
            'count': int(arr.shape[0]),
            'type': type_,
        }
        if minmax:
            flat = arr.reshape(arr.shape[0], -1).astype(np.float64)
            a['min'] = [float(x) for x in flat.min(axis=0)]
            a['max'] = [float(x) for x in flat.max(axis=0)]
        self.accessors.append(a)
        return len(self.accessors) - 1


NP_TO_COMP = {
    np.dtype('float32'): 5126,
    np.dtype('uint32'): 5125,
    np.dtype('uint16'): 5123,
    np.dtype('uint8'): 5121,
    np.dtype('int16'): 5122,
    np.dtype('int8'): 5120,
}

TYPE_BY_N = {1: 'SCALAR', 2: 'VEC2', 3: 'VEC3', 4: 'VEC4', 16: 'MAT4'}


def write_glb(path, gltf, blob):
    js = json.dumps(gltf, separators=(',', ':'), ensure_ascii=False).encode('utf-8')
    js += b' ' * ((4 - len(js) % 4) % 4)
    bn = bytes(blob) + b'\x00' * ((4 - len(blob) % 4) % 4)
    total = 12 + 8 + len(js) + 8 + len(bn)
    with open(path, 'wb') as f:
        f.write(struct.pack('<III', GLB_MAGIC, 2, total))
        f.write(struct.pack('<II', len(js), CHUNK_JSON))
        f.write(js)
        f.write(struct.pack('<II', len(bn), CHUNK_BIN))
        f.write(bn)
    return total


# ------------------------------------------------------------------
# 알맹이
# ------------------------------------------------------------------

def extract(outfit_path, base_path, name, outdir, verbose=True,
            collar_from=1.325, marks=ITEM_MARKS, only=None):
    go, bo = load_glb(outfit_path)
    say = print if verbose else (lambda *a, **k: None)

    # 맨몸을 미리 읽어 둔다 — 카라를 밀어낼 때 '몸이 얼마나 굵은가' 를
    # 알아야 하고, 아래 몸 가리기에서도 같은 것을 쓴다.
    base_pos = base_idx = None
    pushed = {}

    if base_path and collar_from is not None:
        gb, bb = load_glb(base_path)
        hits = find_prims(gb, lambda nm: 'Body_00_SKIN' in nm)
        if hits:
            _mi, bp, _nm = hits[0]
            base_idx = acc_read(gb, bb, bp['indices']).astype(np.int64)
            base_pos = acc_read(gb, bb, bp['attributes']['POSITION']).astype(np.float64)
            # 내보낼 때마다 모델이 조금 밀린다. 얼굴로 그 몫을 맞춘다.
            fb = find_prims(gb, lambda nm: 'Face_00_SKIN' in nm)
            fo = find_prims(go, lambda nm: 'Face_00_SKIN' in nm)
            if fb and fo:
                def mid(g, bin_, pr):
                    i = acc_read(g, bin_, pr['indices']).astype(np.int64)
                    q = acc_read(g, bin_, pr['attributes']['POSITION']).astype(np.float64)
                    return np.median(q[np.unique(i)], axis=0)
                base_pos = base_pos + (mid(go, bo, fo[0][1]) - mid(gb, bb, fb[0][1]))

    cloth = find_prims(go, lambda nm: any(k in nm for k in marks))

    # 한 파일에 옷과 안경이 같이 들어 있을 수 있다(VRoid 는 아바타 통째로
    # 내보내니까). 칸을 따로 두려면 **두 번 떼어 낸다** —
    # 한 번은 옷만, 한 번은 안경만.
    if only:
        cloth = [(mi, p, nm) for mi, p, nm in cloth
                 if SLOT_OF_ZONE.get(zone_of(nm)) == only]
        say('%s 칸만 떼어 낸다' % SLOT_LABEL.get(only, only))

    if not cloth:
        raise SystemExit('떼어 낼 재질이 없다(%s): %s'
                         % ('/'.join(marks), outfit_path))

    say('떼어 낼 프리미티브 %d개' % len(cloth))
    for _mi, p, nm in cloth:
        tri = len(acc_read(go, bo, p['indices'])) // 3
        say('   %-40s %6d 삼각형  구역=%s' % (nm.split('(')[0].strip(), tri, zone_of(nm)))

    b = Builder()

    # --- 정점: 옷이 쓰는 것만 골라 촘촘하게 다시 깐다 -----------------
    # 프리미티브들이 정점 버퍼를 함께 쓰므로, 메시 단위로 한 번만 추린다.
    by_mesh = {}
    for mi, p, nm in cloth:
        by_mesh.setdefault(mi, []).append((p, nm))

    new_prims = []
    zones = []
    used_materials = []

    for mi, plist in by_mesh.items():
        attrs = plist[0][0]['attributes']
        all_idx = np.concatenate([acc_read(go, bo, p['indices']).astype(np.int64)
                                  for p, _ in plist])
        keep = np.unique(all_idx)
        remap = np.zeros(int(keep.max()) + 1, dtype=np.int64)
        remap[keep] = np.arange(len(keep))
        say('메시 %d: 정점 %d → %d 로 추림' % (mi, len(acc_read(go, bo, attrs['POSITION'])), len(keep)))

        # 살 속에 박힌 정점을 밖으로 민다 (카라가 목을 파고드는 것).
        #
        # 굽기 **전에** 해야 한다. 자리를 옮긴 다음 그 값을 담아야
        # 파일에 남는다.
        # 밀어내기는 **옷에만** 건다.
        #
        # 머리카락과 안경은 살을 파고드는 물건이 아니다. 안경은 얼굴에
        # 닿아 있는 것이 정상인데, 밀어내면 얼굴에서 떠 버린다
        # (실제로 안경 정점 72개가 최대 18.6mm 밀렸다).
        CLOTH_ZONES = {'top', 'skirt', 'shoes', 'socks'}
        zones_here = {zone_of(nm) for _p, nm in plist}

        if (collar_from is not None and base_pos is not None
                and (zones_here & CLOTH_ZONES)):
            src_pos = acc_read(go, bo, attrs['POSITION']).astype(np.float64)
            src_pos = np.array(src_pos, dtype=np.float64)   # 쓰기 가능하게
            push_out_of_body(src_pos, keep, base_pos, base_idx,
                             collar_from, say=say)
            pushed[attrs['POSITION']] = src_pos

        new_attr = {}
        for key, ai in attrs.items():
            if key.startswith('TEXCOORD') and key != 'TEXCOORD_0':
                continue
            src = go['accessors'][ai]
            # 민 자리를 쓸 때는 **원래 자료형으로 되돌려 담는다.**
            # float64 로 담으면 glTF 에 없는 자료형이라 터진다.
            if ai in pushed:
                arr = pushed[ai].astype(acc_read(go, bo, ai).dtype)
            else:
                arr = acc_read(go, bo, ai)
            arr = arr[keep]
            n = NCOMP[src['type']]
            dt = arr.dtype
            comp = NP_TO_COMP[dt]
            new_attr[key] = b.array(arr, TYPE_BY_N[n], comp,
                                    target=34962,
                                    minmax=(key == 'POSITION'))

        for p, nm in plist:
            idx = acc_read(go, bo, p['indices']).astype(np.int64)
            idx = remap[idx]
            dt = np.uint16 if len(keep) < 65536 else np.uint32
            ia = b.array(idx.astype(dt), 'SCALAR', NP_TO_COMP[np.dtype(dt)], target=34963)
            new_prims.append({
                'attributes': dict(new_attr),
                'indices': ia,
                'material': p['material'],   # 나중에 다시 번호를 매긴다
                'mode': p.get('mode', 4),
            })
            used_materials.append(p['material'])
            zones.append({'material': nm, 'zone': zone_of(nm)})

    # --- 재질·텍스처: 옷이 쓰는 것만 옮긴다 ---------------------------
    used_materials = list(dict.fromkeys(used_materials))
    mat_map = {old: i for i, old in enumerate(used_materials)}

    tex_map, img_map, smp_map = {}, {}, {}
    new_images, new_textures, new_samplers = [], [], []

    def copy_texture(old):
        if old in tex_map:
            return tex_map[old]
        t = go['textures'][old]
        src = t.get('source')
        if src is not None and src not in img_map:
            im = go['images'][src]
            data = b''
            if 'bufferView' in im:
                bv = go['bufferViews'][im['bufferView']]
                off = bv.get('byteOffset', 0)
                data = bo[off:off + bv['byteLength']]
            img_map[src] = len(new_images)
            new_images.append({
                'name': im.get('name', 'tex%d' % src),
                'mimeType': im.get('mimeType', 'image/png'),
                'bufferView': b.raw(data),
            })
        smp = t.get('sampler')
        if smp is not None and smp not in smp_map:
            smp_map[smp] = len(new_samplers)
            new_samplers.append(dict(go['samplers'][smp]))
        nt = {}
        if src is not None:
            nt['source'] = img_map[src]
        if smp is not None:
            nt['sampler'] = smp_map[smp]
        tex_map[old] = len(new_textures)
        new_textures.append(nt)
        return tex_map[old]

    new_materials = []
    for old in used_materials:
        m = json.loads(json.dumps(go['materials'][old]))
        pbr = m.get('pbrMetallicRoughness') or {}
        for slot in ('baseColorTexture', 'metallicRoughnessTexture'):
            if slot in pbr:
                pbr[slot]['index'] = copy_texture(pbr[slot]['index'])
        for slot in ('normalTexture', 'emissiveTexture', 'occlusionTexture'):
            if slot in m:
                m[slot]['index'] = copy_texture(m[slot]['index'])
        new_materials.append(m)

    for p in new_prims:
        p['material'] = mat_map[p['material']]

    # --- 뼈대: 통째로 옮긴다 ------------------------------------------
    # 번호를 그대로 두면 humanoid·skin·secondaryAnimation 을 손볼 필요가 없다.
    # 본은 가벼우므로(156개) 통째로 옮기는 편이 안전하다.
    nodes = json.loads(json.dumps(go['nodes']))
    mesh_nodes = [i for i, n in enumerate(nodes) if 'mesh' in n]

    holder = None
    for i in mesh_nodes:
        if nodes[i].get('skin') is not None and holder is None:
            holder = i
        else:
            nodes[i].pop('mesh', None)
            nodes[i].pop('skin', None)
    if holder is None:
        raise SystemExit('스킨이 걸린 메시 노드를 못 찾았다')
    nodes[holder]['mesh'] = 0
    nodes[holder]['name'] = name + '_garment'

    # 쓰지 않는 메시 노드에서 mesh 를 뗐다. skin 은 그대로 둔다.
    for i in mesh_nodes:
        if i != holder:
            nodes[i].pop('mesh', None)

    # skins: inverseBindMatrices 를 새 버퍼로 옮긴다
    new_skins = []
    for sk in go.get('skins', []):
        s = {'joints': list(sk['joints'])}
        if 'skeleton' in sk:
            s['skeleton'] = sk['skeleton']
        if 'inverseBindMatrices' in sk:
            ibm = acc_read(go, bo, sk['inverseBindMatrices']).astype(np.float32)
            s['inverseBindMatrices'] = b.array(ibm, 'MAT4', 5126)
        new_skins.append(s)

    # --- VRM 확장 ------------------------------------------------------
    vrm_old = (go.get('extensions') or {}).get('VRM') or {}
    keep_names = {m['name'] for m in new_materials}

    # meta 의 썸네일 번호를 떼어낸다.
    #
    # ★ meta.texture 는 원본 텍스처 목록(25장) 기준 번호다. 옷 파일에는
    #   6장뿐이라 없는 번호가 된다. three-vrm 의 VRMMetaImporter 가
    #   그 번호로 getDependency('texture') 를 부르다 터진다
    #   ("Cannot read properties of undefined (reading 'extensions')").
    #   GLTFLoader 만으로는 멀쩡히 열리므로 원인이 잘 안 보인다.
    meta = dict(vrm_old.get('meta', {}))
    meta.pop('texture', None)
    vrm = {
        'exporterVersion': 'diamondAI garment extractor',
        'specVersion': vrm_old.get('specVersion', '0.0'),
        'meta': meta,
        'humanoid': vrm_old.get('humanoid', {}),
        'firstPerson': vrm_old.get('firstPerson', {}),
        'blendShapeMaster': {'blendShapeGroups': []},
        'materialProperties': [mp for mp in vrm_old.get('materialProperties', [])
                               if mp.get('name') in keep_names],
        'secondaryAnimation': vrm_old.get('secondaryAnimation', {}),
    }
    # 재질값 안의 텍스처 번호도 새 번호로
    for mp in vrm['materialProperties']:
        tp = mp.get('textureProperties') or {}
        mp['textureProperties'] = {k: tex_map[v] for k, v in tp.items() if v in tex_map}

    # 쓰는 확장을 빠짐없이 적는다.
    #
    # ★ VRoid 재질은 KHR_materials_unlit 을 쓴다. 재질만 베껴 오고 이 목록에
    #   안 적으면 GLTFLoader 가 loadMaterial 에서 undefined.getMaterialType()
    #   으로 터진다. 옷이 아예 안 뜬다.
    used_ext = set(go.get('extensionsUsed') or [])
    for m in new_materials:
        used_ext.update((m.get('extensions') or {}).keys())
    used_ext.add('VRM')

    gltf = {
        'asset': {'version': '2.0', 'generator': 'diamondAI _extract_garment.py'},
        'extensionsUsed': sorted(used_ext),
        'extensions': {'VRM': vrm},
        'scene': 0,
        'scenes': go.get('scenes', [{'nodes': [0]}]),
        'nodes': nodes,
        'meshes': [{'name': name + '_garment', 'primitives': new_prims}],
        'materials': new_materials,
        'accessors': b.accessors,
        'bufferViews': b.views,
        'buffers': [{'byteLength': len(b.blob)}],
    }
    if new_images:
        gltf['images'] = new_images
    if new_textures:
        gltf['textures'] = new_textures
    if new_samplers:
        gltf['samplers'] = new_samplers
    if new_skins:
        gltf['skins'] = new_skins

    os.makedirs(outdir, exist_ok=True)
    out = os.path.join(outdir, name + '.vrm')
    size = write_glb(out, gltf, b.blob)
    say('\n구웠다: %s  (%.2f MB)' % (out, size / 1024 / 1024))

    slot = slot_of(zones)

    entry = {
        'key': name,
        'label': name,
        'slot': slot,
        'slot_label': SLOT_LABEL.get(slot, slot),
        'file': os.path.basename(out),
        'parts': zones,
        'source': os.path.basename(outfit_path),
    }

    say('칸: %s (%s)' % (SLOT_LABEL.get(slot, slot), slot))

    # --- 몸 가리기 -------------------------------------------------------
    #
    # 옷 칸에서만 뜻이 있다. 안경을 쓴다고 살이 가려지지는 않는다.
    if base_path and slot == 'outfit':
        entry['hide'] = body_mask(base_path, outfit_path, say)

    return entry


def push_out_of_body(pos, keep, body_pos, body_idx, from_y, margin=0.003,
                     near=0.12, cap=0.04, say=print):
    """몸 속에 박힌 옷 정점을 살 밖으로 밀어낸다.

    왜 필요한가
    ----------
    교복 카라가 목을 파고들어 있었다. 재 보니 카라 안쪽 반지름이 21mm 인데
    그 높이 목 반지름이 62mm 다 — 40mm 나 살 속에 들어가 있었다.
    VRoid 에서 카라 크기가 몸에 비해 작게 잡힌 것이라, 화면에서는
    목이 카라를 뚫고 나온 것처럼 보인다.

    **목을 늘려도 안 낫는다.** 굵기 차이는 그대로이기 때문이다.

    어떻게
    ------
    통째로 키우면 모양이 망가진다(카라 반지름이 21~83mm 로 들쭉날쭉하다).
    **살 속에 박힌 정점만** 그 높이 몸 반지름 + 여유 만큼 바깥으로 민다.
    이미 밖에 있는 정점은 건드리지 않으므로 옷 모양이 남는다.

    몸을 세로축(y) 둘레의 기둥으로 보고 높이·각도별 반지름을 재 둔다.
    목처럼 둥근 자리에서는 이 근사로 충분하다.
    """
    body_used = np.unique(body_idx)
    bv = body_pos[body_used]

    # ★ 목 기둥만 본다.
    #
    #   처음에는 그 높이 몸 정점을 통째로 봤다가 **어깨 반지름을 목
    #   반지름으로 잡아 카라가 35cm 날아갔다.** y 1.32 아래는 어깨로
    #   벌어지는 자리(반지름 89~118mm)이고, 목 자체는 60~73mm 다.
    #   가로로 near(12cm) 안쪽만 남기면 어깨가 빠진다.
    bv = bv[np.hypot(bv[:, 0], bv[:, 2]) < near]

    # 그 높이·그 방향에서 몸이 얼마나 굵은가
    YSTEP = 0.005                      # 5mm 칸
    ABINS = 24                         # 15도 칸

    table = {}

    for v in bv:
        if v[1] < from_y - 0.05:
            continue
        yi = int(round(v[1] / YSTEP))
        ai = int(((np.arctan2(v[2], v[0]) + np.pi) / (2 * np.pi)) * ABINS) % ABINS
        r = float(np.hypot(v[0], v[2]))
        if r > table.get((yi, ai), 0.0):
            table[(yi, ai)] = r

    def body_radius(v):
        """그 자리에서 몸 반지름. 이웃 칸까지 봐서 가장 큰 값."""
        yi = int(round(v[1] / YSTEP))
        ai = int(((np.arctan2(v[2], v[0]) + np.pi) / (2 * np.pi)) * ABINS) % ABINS
        best = 0.0
        for dy in (-1, 0, 1):
            for da in (-1, 0, 1):
                r = table.get((yi + dy, (ai + da) % ABINS), 0.0)
                if r > best:
                    best = r
        return best

    moved = 0
    worst = 0.0

    for vi in keep:
        v = pos[vi]
        if v[1] < from_y:
            continue

        r = float(np.hypot(v[0], v[2]))

        # 목을 감싸는 정점만. 어깨에 걸친 부분은 그대로 둔다.
        if r >= near:
            continue

        need = body_radius(v) + margin

        if r >= need or need <= margin:
            continue

        if r < 1e-6:
            continue                   # 축 위의 정점은 방향이 없다

        # 한 번에 이만큼 넘게는 안 민다. 재는 데 실수가 있어도
        # 옷이 날아가지는 않게 하는 빗장이다.
        if need - r > cap:
            need = r + cap

        k = need / r
        pos[vi, 0] *= k
        pos[vi, 2] *= k
        moved += 1
        worst = max(worst, (need - r) * 1000)

    say('카라 밀어내기: 정점 %d개를 살 밖으로 (가장 많이 민 것 %.1fmm)'
        % (moved, worst))

    return moved


def body_mask(base_path, outfit_path, say=print):
    """맨몸에서 감출 삼각형을 찾는다.

    옷 입은 쪽에서 지워진 정점 = 옷에 가려 안 보이는 자리.
    그 정점을 쓰는 맨몸 삼각형을 감추면 옷 속이 비치지 않는다.
    """
    gb, bb = load_glb(base_path)
    go, bo = load_glb(outfit_path)

    def body(g, bin_):
        hits = find_prims(g, lambda nm: 'Body_00_SKIN' in nm)
        if not hits:
            return None, None
        _mi, p, _nm = hits[0]
        idx = acc_read(g, bin_, p['indices']).astype(np.int64)
        pos = acc_read(g, bin_, p['attributes']['POSITION']).astype(np.float64)
        return pos, idx

    pb, ib = body(gb, bb)
    po, io = body(go, bo)
    if pb is None or po is None:
        say('몸 메시를 못 찾아 가리기를 건너뛴다')
        return None

    # 내보낼 때마다 모델이 통째로 조금 밀린다(0.3mm쯤). 그 몫을 뺀다.
    #
    # ★ 기준을 몸에서 잡으면 안 된다. 옷 입은 쪽은 몸의 16%가 지워져 있어
    #   (그것도 주로 몸통이) 중앙값이 5mm 밀린다. 처음에 그렇게 했다가
    #   가릴 삼각형이 100% 로 나왔다 — 다이아가 통째로 사라진다.
    #   옷과 상관없이 그대로인 얼굴에서 잡는다.
    def anchor(g, bin_):
        hits = find_prims(g, lambda nm: 'Face_00_SKIN' in nm)
        if not hits:
            return None
        _mi, p, _nm = hits[0]
        idx = acc_read(g, bin_, p['indices']).astype(np.int64)
        pos = acc_read(g, bin_, p['attributes']['POSITION']).astype(np.float64)
        return np.median(pos[np.unique(idx)], axis=0)

    ab, ao = anchor(gb, bb), anchor(go, bo)
    if ab is None or ao is None:
        say('얼굴을 못 찾아 오프셋을 0 으로 둔다')
        off = np.zeros(3)
    else:
        off = ao - ab

    keep_o = np.unique(io)
    base_used = np.unique(ib)

    # 없어진 정점 찾기 — **거리로 재야 한다.**
    #
    # ★ 처음에는 소수점 다섯 자리로 반올림해 같은 값인지 봤다. 그랬더니
    #   **손이 통째로 사라진 것으로 잡혔다.** 두 파일의 손 정점은 0.0005mm
    #   차이로 사실상 같은데, 반올림 경계를 사이에 두고 갈라지면 다른 칸에
    #   떨어져 "없다" 가 된다. 그 삼각형 161개가 감춰져 **손등에 구멍이
    #   뚫렸고**, 구멍 너머 살 안쪽이 검붉게 비쳐 '갈색 네모' 로 보였다.
    #
    #   진짜로 지워진 정점은 몇 cm 씩 떨어져 있으므로 0.1mm 만 허용해도
    #   충분히 갈린다(실측: 남아 있는 것 최대 0.0005mm, 지워진 것 최대 118mm).
    #
    #   scipy 없이 하려고 0.1mm 격자에 담고 이웃 27칸까지 본다.
    #   격자 하나만 보면 반올림과 똑같은 함정에 다시 빠진다.
    CELL = 0.0001                      # 0.1mm

    have = {}
    for v in po[keep_o] - off:
        have.setdefault(tuple(np.floor(v / CELL).astype(np.int64)), []).append(v)

    NEIGH = [(i, j, k)
             for i in (-1, 0, 1) for j in (-1, 0, 1) for k in (-1, 0, 1)]

    TOL2 = (0.0005) ** 2               # 0.5mm 안이면 같은 정점으로 본다

    gone = np.zeros(len(pb), dtype=bool)

    for vi in base_used:
        v = pb[vi]
        cell = np.floor(v / CELL).astype(np.int64)
        found = False

        for dx, dy, dz in NEIGH:
            for w in have.get((cell[0] + dx, cell[1] + dy, cell[2] + dz), ()):
                if ((w[0] - v[0]) ** 2 + (w[1] - v[1]) ** 2
                        + (w[2] - v[2]) ** 2) <= TOL2:
                    found = True
                    break
            if found:
                break

        if not found:
            gone[vi] = True

    tris = ib.reshape(-1, 3)
    hide = gone[tris].any(axis=1)
    say('몸 가리기: 삼각형 %d개 중 %d개를 감춘다 (%.1f%%) · 오프셋 %+.3fmm'
        % (len(tris), int(hide.sum()), hide.mean() * 100, off[1] * 1000))

    packed = np.packbits(hide)
    return {
        # 어느 메시를 가릴 것인가.
        #
        # ★ 재질 이름으로 찾으면 안 된다. three-vrm 이 MToon 으로 바꿔 끼우면서
        #   material.name 이 빈 문자열이 되어 런타임에서는 못 찾는다
        #   (파일 안에는 멀쩡히 있어서 더 헷갈린다).
        #   삼각형 수는 그 몸에서 유일하고 런타임에서도 그대로 읽힌다.
        #   마스크는 어차피 이 맨몸 파일 하나에 매인 것이라, 몸을 다시
        #   내보내면 마스크도 다시 구워야 한다 — 그때 이 수도 같이 바뀐다.
        'material': 'Body_00_SKIN',
        'triangles': int(len(tris)),
        'hidden': int(hide.sum()),
        'mask': base64.b64encode(packed.tobytes()).decode('ascii'),
    }


def main():
    ap = argparse.ArgumentParser(description='VRM 에서 옷만 떼어 작은 VRM 으로 굽는다')
    ap.add_argument('outfit', help='옷 입은 VRM')
    ap.add_argument('--base', default=os.path.join(HERE, 'static', 'body.vrm'),
                    help='맨몸 VRM (몸 가리기 계산에 쓴다)')
    ap.add_argument('--name', help='옷 이름. 안 주면 파일 이름에서 딴다')
    ap.add_argument('--out', default=os.path.join(HERE, 'static', 'wardrobe'))
    ap.add_argument('--hair', action='store_true',
                    help='옷 대신 머리카락을 떼어낸다')
    ap.add_argument('--only', choices=('outfit', 'glasses', 'hair'),
                    help='이 칸의 것만 떼어낸다. 한 파일에 옷과 안경이 '
                         '같이 있을 때 두 번 불러 나눈다')
    ap.add_argument('--collar-from', type=float, default=1.325,
                    help='이 높이(m) 위의 옷 정점을 살 밖으로 민다. '
                         '끄려면 음수를 준다')
    a = ap.parse_args()

    name = a.name or os.path.splitext(os.path.basename(a.outfit))[0]
    entry = extract(a.outfit, a.base if os.path.exists(a.base) else None,
                    name, a.out,
                    collar_from=(None if a.collar_from < 0 else a.collar_from),
                    marks=(HAIR_MARKS if a.hair else ITEM_MARKS),
                    only=a.only)

    # wardrobe.json 에 적는다. 같은 이름이면 갈아 끼운다.
    book = os.path.join(a.out, 'wardrobe.json')
    items = []
    if os.path.exists(book):
        with open(book, encoding='utf-8') as f:
            items = json.load(f).get('items', [])
    items = [x for x in items if x.get('key') != entry['key']]
    items.append(entry)
    with open(book, 'w', encoding='utf-8') as f:
        json.dump({'items': items}, f, ensure_ascii=False, indent=1)
    print('옷장에 적었다: %s (%d벌)' % (book, len(items)))


if __name__ == '__main__':
    main()

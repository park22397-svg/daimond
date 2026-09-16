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

# 옷으로 볼 재질. VRoid 는 옷 재질 이름에 _CLOTH 를 붙인다.
CLOTH_MARK = '_CLOTH'


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

def extract(outfit_path, base_path, name, outdir, verbose=True):
    go, bo = load_glb(outfit_path)
    say = print if verbose else (lambda *a, **k: None)

    cloth = find_prims(go, lambda nm: CLOTH_MARK in nm)
    if not cloth:
        raise SystemExit('옷 재질(_CLOTH)이 없다: ' + outfit_path)

    say('옷 프리미티브 %d개' % len(cloth))
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

        new_attr = {}
        for key, ai in attrs.items():
            if key.startswith('TEXCOORD') and key != 'TEXCOORD_0':
                continue
            src = go['accessors'][ai]
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

    entry = {
        'key': name,
        'label': name,
        'file': os.path.basename(out),
        'parts': zones,
        'source': os.path.basename(outfit_path),
    }

    # --- 몸 가리기 -------------------------------------------------------
    if base_path:
        entry['hide'] = body_mask(base_path, outfit_path, say)

    return entry


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
    have = {}
    for v in np.round(po[keep_o] - off, 5):
        have[tuple(v)] = True

    base_used = np.unique(ib)
    gone = np.zeros(len(pb), dtype=bool)
    for vi in base_used:
        if tuple(np.round(pb[vi], 5)) not in have:
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
    a = ap.parse_args()

    name = a.name or os.path.splitext(os.path.basename(a.outfit))[0]
    entry = extract(a.outfit, a.base if os.path.exists(a.base) else None,
                    name, a.out)

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

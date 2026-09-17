# _watch_wardrobe.py
# 옷장 지킴이 — 폴더에 VRM 을 떨구면 알아서 옷장에 건다.
#
#   python _watch_wardrobe.py          지켜본다 (Ctrl+C 로 멈춤)
#   python _watch_wardrobe.py --once   지금 있는 것만 처리하고 끝낸다
#
# 왜 이것이 필요한가
# ------------------
# VRoid Studio 는 바깥에서 부를 수 없다 — 명령줄도 URI 스킴도 플러그인도
# 없다(2026-09-16 에 설치본을 뜯어 확인). 그래서 사람이 VRM 으로 내보내는
# 길 하나뿐인데, 그 뒤로도 손이 여러 번 갔다: 알려 주고, 명령을 치고,
# 옷과 안경을 따로 떼어내고.
#
# 그 뒷일을 전부 없앤다. **내보내서 폴더에 넣는 것**까지가 사람 몫이다.
#
# 무엇을 하는가
# -------------
# 1. `static/wardrobe/_새로넣기/` 에 새 .vrm 이 들어오길 기다린다
# 2. 안에 무엇이 들었는지 보고 칸을 가른다 (옷 / 안경 / 머리)
# 3. 칸마다 한 번씩 떼어내 굽는다 — 한 파일에 옷과 안경이 같이 있어도
#    두 벌로 나뉜다
# 4. 원본은 `_넣은것/` 으로 옮긴다. 같은 것을 두 번 굽지 않게.
#
# 이름 짓기
# ---------
# 파일 이름이 곧 옷 이름이다. 한 파일에서 여러 칸이 나오면 뒤에 칸을 붙인다.
#   원피스.vrm            -> '원피스'
#   봄옷.vrm (옷+안경)    -> '봄옷', '봄옷 안경'   (옷은 이름 그대로)

import argparse
import os
import shutil
import sys
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from _extract_garment import (ITEM_MARKS, SLOT_LABEL, SLOT_OF_ZONE, extract,
                              find_prims, load_glb, zone_of)

DROP = os.path.join(HERE, 'static', 'wardrobe', '_새로넣기')
DONE = os.path.join(HERE, 'static', 'wardrobe', '_넣은것')
OUT = os.path.join(HERE, 'static', 'wardrobe')
BASE = os.path.join(HERE, 'static', 'avatar.vrm')

READ_ME = """여기에 VRoid 에서 내보낸 VRM 을 넣으세요.

  * 넣으면 알아서 옷장에 걸립니다. 서버를 껐다 켤 필요 없습니다.
  * 파일 이름이 곧 옷 이름이 됩니다.
  * 옷과 안경이 한 파일에 같이 있어도 따로 갈라 줍니다.
  * 다 되면 원본은 옆의 _넣은것 폴더로 옮겨집니다.

VRoid 내보내기 설정 (꼭 맞춰 주세요)
------------------------------------
  버전            VRM 0.0        (1.0 은 화면이 못 읽습니다)
  마테리얼 삭감   끄기           (합치면 옷만 떼어낼 수 없습니다)
  텍스처 품질     축소 안 함
  폴리곤 삭감     품질 낮추지 않기
  본 삭감         끄기
  투명 메시 삭제  끄기           (안경 렌즈가 통째로 지워집니다)

몸을 바꾸지 마세요
------------------
바탕 아바타(static/avatar.vrm)와 **같은 몸**에서 내보내야 옷이 맞습니다.
키나 몸 수치를 바꾼 뒤에 내보내면 옷이 뜨거나 파고듭니다.
얼마나 어긋났는지는 처리할 때 알려 줍니다.
"""


def slots_in(path):
    """그 파일에 어느 칸의 것이 들어 있는가."""
    g, _b = load_glb(path)

    found = []

    for _mi, _p, nm in find_prims(g, lambda n: any(k in n for k in ITEM_MARKS)):
        slot = SLOT_OF_ZONE.get(zone_of(nm))
        if slot and slot not in found:
            found.append(slot)

    return found


def body_gap(path):
    """바탕 아바타와 몸이 얼마나 다른가. (키 차이mm, 얼굴 같은가)"""
    import numpy as np

    from _extract_garment import acc_read

    def body_of(p):
        g, b = load_glb(p)
        hits = find_prims(g, lambda nm: 'Body_00_SKIN' in nm)
        if not hits:
            return None
        _mi, pr, _nm = hits[0]
        idx = acc_read(g, b, pr['indices']).astype(np.int64)
        pos = acc_read(g, b, pr['attributes']['POSITION']).astype(np.float64)
        return pos[np.unique(idx)]

    try:
        a, c = body_of(BASE), body_of(path)
        if a is None or c is None:
            return None
        return (c[:, 1].max() - a[:, 1].max()) * 1000
    except Exception:
        return None


def process(path, say=print):
    """파일 하나를 옷장에 건다. 건 것들의 이름을 돌려준다."""
    stem = os.path.splitext(os.path.basename(path))[0]

    slots = slots_in(path)

    if not slots:
        say('  떼어 낼 것이 없습니다 (옷·안경·머리 재질을 못 찾음)')
        return []

    say('  들어 있는 것: ' + ', '.join(SLOT_LABEL.get(s, s) for s in slots))

    gap = body_gap(path)

    if gap is not None and abs(gap) > 3:
        say('  ⚠ 바탕 아바타와 키가 %+.1fmm 다릅니다 — 옷이 안 맞을 수 있습니다'
            % gap)

    made = []

    for slot in slots:
        # 옷은 파일 이름 그대로. 곁들이(안경·머리)에만 칸을 붙인다.
        # 여럿일 때 전부 붙이면 '봄옷 옷' 같은 이름이 나온다.
        if slot == 'outfit' or len(slots) == 1:
            name = stem
        else:
            name = f'{stem} {SLOT_LABEL.get(slot, slot)}'

        name = name.strip()

        say(f'  [{SLOT_LABEL.get(slot, slot)}] {name}')

        entry = extract(path, BASE, name, OUT, verbose=False, only=slot)
        _book_add(entry)
        made.append(name)

    return made


def _book_add(entry):
    """wardrobe.json 에 적는다. 같은 이름이면 갈아 끼운다."""
    import json

    book = os.path.join(OUT, 'wardrobe.json')
    items = []

    if os.path.exists(book):
        try:
            with open(book, encoding='utf-8') as f:
                items = json.load(f).get('items', [])
        except Exception as e:
            print(f'  [옷장 읽기 오류] {e}')

    items = [x for x in items if x.get('key') != entry['key']]
    items.append(entry)

    with open(book, 'w', encoding='utf-8') as f:
        json.dump({'items': items}, f, ensure_ascii=False, indent=1)


def settled(path, seen):
    """다 복사됐는가.

    큰 파일은 복사하는 데 몇 초 걸린다. 그 중간에 열면 깨진 파일을
    읽는다. 크기가 두 번 연달아 같을 때만 손댄다.
    """
    try:
        now = os.path.getsize(path)
    except OSError:
        return False

    was = seen.get(path)
    seen[path] = now

    return was is not None and was == now and now > 0


def sweep(seen, say=print):
    """폴더를 한 번 훑는다. 처리한 개수를 돌려준다."""
    try:
        names = sorted(os.listdir(DROP))
    except FileNotFoundError:
        return 0

    n = 0

    for name in names:
        if not name.lower().endswith('.vrm'):
            continue

        path = os.path.join(DROP, name)

        if not settled(path, seen):
            continue

        say(f'\n[새 파일] {name}  ({os.path.getsize(path) / 1024 / 1024:.1f} MB)')

        try:
            made = process(path, say)
        except SystemExit as e:
            say(f'  건너뜁니다: {e}')
            made = []
        except Exception as e:
            say(f'  오류: {e}')
            traceback.print_exc()
            made = []

        if made:
            os.makedirs(DONE, exist_ok=True)
            dest = os.path.join(DONE, name)

            # 같은 이름이 있으면 뒤에 번호를 붙인다
            i = 2
            while os.path.exists(dest):
                base, ext = os.path.splitext(name)
                dest = os.path.join(DONE, f'{base} ({i}){ext}')
                i += 1

            shutil.move(path, dest)
            say('  옷장에 걸었습니다: ' + ', '.join(made))
            say('  (원본은 _넣은것 으로 옮겼습니다)')
            n += 1

        seen.pop(path, None)

    return n


def _who_holds(lock):
    """이미 도는 지킴이의 번호. 없으면 None.

    적혀 있어도 그 프로그램이 죽었으면 없는 것으로 본다 — 창을 그냥
    닫으면 빗장이 남는데, 그걸 못 지우면 다시는 못 뜬다.
    """
    try:
        with open(lock, encoding='utf-8') as f:
            pid = int((f.read() or '0').strip())
    except (OSError, ValueError):
        return None

    if pid <= 0 or pid == os.getpid():
        return None

    try:
        import subprocess
        out = subprocess.run(
            ['tasklist', '/FI', f'PID eq {pid}', '/NH'],
            capture_output=True, text=True, timeout=10).stdout
        return pid if str(pid) in out else None
    except Exception:
        return None


def main():
    ap = argparse.ArgumentParser(description='폴더에 넣은 VRM 을 옷장에 건다')
    ap.add_argument('--once', action='store_true',
                    help='지금 있는 것만 처리하고 끝낸다')
    ap.add_argument('--every', type=float, default=2.0, help='몇 초마다 볼까')
    a = ap.parse_args()

    os.makedirs(DROP, exist_ok=True)

    readme = os.path.join(DROP, '읽어주세요.txt')
    if not os.path.exists(readme):
        with open(readme, 'w', encoding='utf-8') as f:
            f.write(READ_ME)

    if not os.path.exists(BASE):
        print(f'바탕 아바타가 없습니다: {BASE}')
        return 1

    # 하나만 돈다.
    #
    # 두 번 눌러 띄우는 물건이라 사람은 실수로 여러 번 누른다. 여럿이
    # 돌면 같은 파일을 서로 집어 반쯤 구운 것이 섞인다.
    lock = os.path.join(DROP, '.지킴이')

    if not a.once:
        old = _who_holds(lock)

        if old:
            print(f'이미 돌고 있습니다 (PID {old}). 이 창은 닫아도 됩니다.')
            return 0

        with open(lock, 'w', encoding='utf-8') as f:
            f.write(str(os.getpid()))

    print('옷장 지킴이')
    print('  보는 곳 : ' + DROP)
    print('  굽는 곳 : ' + OUT)

    seen = {}

    if a.once:
        # 한 번만 돌 때는 '복사 중인가' 를 두 번 봐야 하므로 두 번 훑는다
        sweep(seen, say=lambda *x: None)
        time.sleep(0.5)
        n = sweep(seen)
        print(f'\n{n}개 처리했습니다.')
        return 0

    print('  (Ctrl+C 로 멈춥니다)\n')
    print('여기에 VRM 을 넣으세요. 넣으면 바로 옷장에 걸립니다.')

    try:
        while True:
            sweep(seen)
            time.sleep(a.every)
    except KeyboardInterrupt:
        print('\n멈췄습니다.')

    return 0


if __name__ == '__main__':
    sys.exit(main())

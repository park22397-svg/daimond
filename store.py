# store.py
# diamondAI - 어디에 적어 둘 것인가
#
# 내 컴퓨터에서는 파일에 적으면 된다. 그런데 Vercel 같은 데 올리면
# **파일을 쓸 수가 없다.** 코드가 놓인 자리는 읽기 전용이고, 쓸 수 있는
# /tmp 는 요청을 맡은 기계마다 따로이며 잠시 뒤 사라진다.
#
# 그대로 올리면 이렇게 된다.
#   - 회원가입 -> 다음 요청에서 계정이 없다
#   - 대화     -> 저장이 안 된다
#   - 쿠키 열쇠 -> 매번 새로 생겨 로그인이 안 풀린다
#
# 그래서 '적고 읽는 일' 만 여기로 모은다. accounts 와 memory_manager 는
# 파일을 직접 만지지 않고 여기에 부탁한다. 어디에 적을지는 이 파일 하나가
# 정하므로, 저장할 데가 바뀌어도 나머지는 한 줄도 안 고친다.
#
#   BLOB_READ_WRITE_TOKEN 이 있으면  -> Vercel Blob
#   없으면                          -> 지금까지처럼 파일
#
# 열쇠(key)는 슬래시로 나눈 이름이다. 'accounts.json',
# 'memory/u_alice.json', 'archive/u_alice/memory_2026.json' 처럼.

import json
import os
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))

# Vercel Blob 을 쓸 때 앞에 붙이는 이름.
# 한 저장소를 여러 곳이 나눠 쓸 때 섞이지 않게.
PREFIX = os.environ.get("BLOB_PREFIX", "diamondai")

# 저장소가 붙어 있는가.
#
# Vercel 이 저장소를 프로젝트에 이으면 이 값들을 넣어 준다.
# 내 컴퓨터에는 없으므로 파일로 간다.
_TOKEN = (os.environ.get("BLOB_READ_WRITE_TOKEN", "").strip()
          or os.environ.get("BLOB_STORE_ID", "").strip())


def backend():
    """지금 어디에 적고 있는가. 'blob' 또는 'file'."""

    return "blob" if _TOKEN else "file"


# ============================================================
# 파일에 적기 (내 컴퓨터)
# ============================================================

def _path(key):
    """열쇠를 파일 자리로. 자리를 벗어나는 이름은 막는다."""

    parts = []

    for p in str(key).split("/"):
        p = p.strip()

        # '..' 이나 빈 칸이 섞이면 폴더 밖을 가리킬 수 있다.
        if not p or p == "." or p == "..":
            raise ValueError("쓸 수 없는 이름: " + str(key))

        parts.append(p)

    if not parts:
        raise ValueError("빈 이름")

    return os.path.join(HERE, *parts)


def _file_read(key):
    path = _path(key)

    if not os.path.exists(path):
        return None

    try:
        with open(path, "rb") as f:
            return f.read()
    except OSError as e:
        print("[저장소 읽기 오류]", key, e)
        return None


def _file_write(key, data):
    path = _path(key)

    os.makedirs(os.path.dirname(path), exist_ok=True)

    # 임시 파일에 먼저 쓰고 바꿔 끼운다.
    # 쓰는 도중에 꺼져도 있던 것이 안 깨지게.
    fd, tmp = tempfile.mkstemp(prefix="store_", suffix=".tmp",
                               dir=os.path.dirname(path))

    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())

        os.replace(tmp, path)

    except Exception:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def _file_delete(key):
    try:
        os.remove(_path(key))
        return True
    except OSError:
        return False


def _file_list(prefix):
    """그 아래 있는 열쇠들."""

    root = os.path.join(HERE, *[p for p in str(prefix).split("/") if p])

    if not os.path.isdir(root):
        return []

    out = []

    for name in sorted(os.listdir(root)):
        if os.path.isfile(os.path.join(root, name)):
            out.append(str(prefix).rstrip("/") + "/" + name)

    return out


# ============================================================
# Vercel Blob 에 적기 (올렸을 때)
#
# private 저장소를 쓴다. 안에 든 것이 비밀번호 해시와 사람들이 나눈
# 이야기라 공개 저장소에 두면 주소만 알면 누구나 읽는다.
#
# 공식 SDK 를 쓴다. 직접 HTTP 로 짜맞출 수도 있지만 두 가지가 까다롭다 —
# private 은 읽을 때도 인증이 필요하고, **덮어쓴 것을 바로 읽으면 최대
# 60초 동안 옛것이 나온다**(CDN 이 물고 있다). 회원가입 직후 로그인이
# 깨지는 자리가 바로 거기다. SDK 의 use_cache=False 가 그것을 끈다.
# ============================================================

ACCESS = "private"


def _blob_name(key):
    return PREFIX + "/" + str(key).lstrip("/")


def _blob_read(key):
    from vercel import blob
    from vercel.blob import BlobNotFoundError

    try:
        # use_cache=False 를 반드시 준다.
        # 켜 두면 방금 적은 것을 못 읽는다.
        r = blob.get(_blob_name(key), access=ACCESS, use_cache=False)
    except BlobNotFoundError:
        return None
    except Exception as e:
        print("[Blob 읽기 오류]", key, e)
        return None

    if r is None:
        return None

    # 판에 따라 돌려주는 모양이 조금씩 다르다. 있는 것을 골라 쓴다.
    for name in ("content", "body", "data"):
        got = getattr(r, name, None)
        if isinstance(got, (bytes, bytearray)):
            return bytes(got)

    stream = getattr(r, "stream", None)

    if stream is not None:
        try:
            return stream.read()
        except Exception:
            try:
                return b"".join(stream)
            except Exception as e:
                print("[Blob 읽기 오류]", key, e)
                return None

    print("[Blob 읽기 오류] 모르는 모양", key, type(r))
    return None


def _blob_write(key, data):
    from vercel import blob

    blob.put(
        _blob_name(key),
        data,
        access=ACCESS,
        content_type="application/json",
        # 같은 이름에 덮어쓴다. 이것을 안 주면 이름 뒤에 글자를 붙여
        # 새 것을 만들고, 다음에 읽을 때 옛 것이 딸려 나온다.
        add_random_suffix=False,
        overwrite=True,
    )


def _blob_delete(key):
    from vercel import blob

    try:
        blob.delete(_blob_name(key))
        return True
    except Exception as e:
        print("[Blob 지우기 오류]", key, e)
        return False


def _blob_list(prefix):
    from vercel import blob

    want = _blob_name(prefix).rstrip("/") + "/"
    head = len(PREFIX) + 1
    out = []

    try:
        r = blob.list_objects(prefix=want, limit=1000)

        items = getattr(r, "blobs", None) or getattr(r, "objects", None) or []

        for b in items:
            name = getattr(b, "pathname", None) or getattr(b, "path", "")
            if name.startswith(want):
                out.append(name[head:])

    except Exception as e:
        print("[Blob 목록 오류]", prefix, e)

    return sorted(out)


# ============================================================
# 밖에서 쓰는 것
# ============================================================

def read(key):
    """없으면 None."""

    return _blob_read(key) if _TOKEN else _file_read(key)


def write(key, data):
    if isinstance(data, str):
        data = data.encode("utf-8")

    if _TOKEN:
        _blob_write(key, data)
    else:
        _file_write(key, data)


def delete(key):
    return _blob_delete(key) if _TOKEN else _file_delete(key)


def exists(key):
    return read(key) is not None


def listing(prefix):
    """그 아래 열쇠들. 이름순."""

    return _blob_list(prefix) if _TOKEN else _file_list(prefix)


def read_json(key, default=None):
    raw = read(key)

    if raw is None:
        return default

    try:
        return json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as e:
        print("[저장소 글 깨짐]", key, e)
        return default


def write_json(key, obj):
    write(key, json.dumps(obj, ensure_ascii=False, indent=2))

    return obj


def move(src, dst):
    """옮긴다. 대상이 이미 있으면 건드리지 않는다."""

    if exists(dst):
        return False

    raw = read(src)

    if raw is None:
        return False

    write(dst, raw)
    delete(src)

    return True

# accounts.py
# diamondAI - 아이디와 비밀번호
#
# 왜 필요한가.
#
# 기억 파일이 하나뿐이라 누가 들어오든 같은 기억을 이어 썼다.
# 내가 쌓은 친밀도를 남이 이어받고, 내가 나눈 이야기를 남이 읽었다.
# 계정마다 기억을 따로 두려면 먼저 '누구인지' 를 알아야 한다.
#
# 비밀번호는 그대로 적지 않는다.
#
# 여기는 내 컴퓨터에서만 도는 시험용이지만, 비밀번호를 적어 두면
# 파일을 한 번 흘리는 것으로 끝나지 않는다 — 사람들은 같은 비밀번호를
# 다른 데서도 쓴다. 그래서 되돌릴 수 없는 방식으로 바꿔 둔다.
#
#   pbkdf2_hmac(sha256) + 계정마다 다른 소금 + 20만 번 반복
#
# 소금이 계정마다 달라야 같은 비밀번호를 쓴 둘이 같은 값이 되지 않는다.
# 반복 횟수는 맞혀 보려는 쪽을 느리게 만든다. 파이썬 기본 모듈만 쓴다.

import hashlib
import hmac
import json
import os
import re
import secrets
import tempfile
import time


HERE = os.path.dirname(os.path.abspath(__file__))

ACCOUNTS_FILE = os.path.join(HERE, "accounts.json")

# 늘리면 맞혀 보기가 느려지고 로그인도 같이 느려진다.
# 20만 번이면 이 컴퓨터에서 0.1초쯤이다 — 사람은 못 느끼고
# 기계는 초당 열 번밖에 못 해 본다.
ITERATIONS = 200_000

# 아이디에 쓸 수 있는 글자.
#
# 아이디가 곧 기억 파일 이름이 되므로 좁게 잡는다.
# 여기에 `.` 이나 `/` 가 섞이면 파일 자리를 벗어나 딴 데를 가리킬 수 있다.
ID_RE = re.compile(r"^[A-Za-z0-9_]{3,20}$")

PW_MIN = 4
PW_MAX = 64


# ============================================================
# 파일 읽고 쓰기
# ============================================================

def _blank():
    return {"users": {}}


def load():
    """계정 전부. 파일이 없거나 깨졌으면 빈 것."""

    if not os.path.exists(ACCOUNTS_FILE):
        return _blank()

    try:
        with open(ACCOUNTS_FILE, encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError, ValueError) as e:
        print(f"[계정 파일 읽기 오류]: {e}")
        return _blank()

    if not isinstance(data, dict):
        return _blank()

    users = data.get("users", {})

    if not isinstance(users, dict):
        users = {}

    return {"users": users}


def save(data):
    """임시 파일에 먼저 쓰고 바꿔 끼운다.

    쓰는 도중에 꺼져도 있던 계정이 날아가지 않게. 기억 파일과 같은 방식이다.
    """

    fd, tmp = tempfile.mkstemp(prefix="accounts_", suffix=".tmp", dir=HERE)

    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())

        os.replace(tmp, ACCOUNTS_FILE)

    except Exception:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


# ============================================================
# 비밀번호
# ============================================================

def _hash(password, salt_hex, iterations=None):
    """비밀번호를 되돌릴 수 없는 값으로 바꾼다.

    기본값을 `iterations=ITERATIONS` 로 적으면 안 된다.
    기본 인자는 함수가 만들어질 때 한 번 묶이므로, 나중에
    ITERATIONS 를 올려도 이 함수는 옛 숫자를 계속 쓴다.
    그러면 계정에는 새 숫자가 적히고 실제로는 옛 숫자로 계산해
    **있던 계정이 전부 못 들어오게 된다.** 부를 때 읽는다.
    """

    if iterations is None:
        iterations = ITERATIONS

    return hashlib.pbkdf2_hmac(
        "sha256",
        str(password).encode("utf-8"),
        bytes.fromhex(salt_hex),
        int(iterations),
    ).hex()


# ============================================================
# 아이디
# ============================================================

def _key(user_id):
    """찾을 때 쓰는 이름. 대소문자를 가리지 않는다.

    `Dia` 로 만들고 `dia` 로 들어오면 못 찾는 것이 더 헷갈린다.
    보여 줄 때는 만든 그대로 쓰고, 찾을 때만 이 값을 쓴다.
    """

    return str(user_id or "").strip().lower()


def check_id(user_id):
    """쓸 수 있는 아이디인가. (되는가, 왜 안 되는가)"""

    user_id = str(user_id or "").strip()

    if not user_id:
        return False, "아이디를 적어 주세요."

    if not ID_RE.match(user_id):
        return False, "아이디는 영문·숫자·밑줄 3~20자입니다."

    return True, ""


def check_pw(password):
    """쓸 수 있는 비밀번호인가."""

    password = str(password or "")

    if len(password) < PW_MIN:
        return False, f"비밀번호는 {PW_MIN}자 이상이어야 합니다."

    if len(password) > PW_MAX:
        return False, f"비밀번호는 {PW_MAX}자까지입니다."

    return True, ""


def exists(user_id):
    return _key(user_id) in load()["users"]


def count():
    return len(load()["users"])


def slot_of(user_id):
    """그 사람의 기억 자리 이름. 없으면 None."""

    rec = load()["users"].get(_key(user_id))

    return rec.get("slot") if rec else None


# ============================================================
# 만들기
# ============================================================

def create(user_id, password):
    """계정을 만든다.

    반환: (되었는가, 할 말, 기억 자리)
    """

    ok, msg = check_id(user_id)
    if not ok:
        return False, msg, None

    ok, msg = check_pw(password)
    if not ok:
        return False, msg, None

    data = load()
    key = _key(user_id)

    if key in data["users"]:
        return False, "이미 있는 아이디입니다.", None

    salt = secrets.token_hex(16)

    data["users"][key] = {
        "id": str(user_id).strip(),      # 보여 줄 때 쓰는 원래 모습
        "salt": salt,
        "hash": _hash(password, salt),
        "iter": ITERATIONS,
        "slot": "u_" + key,              # 기억 파일 이름
        "created": time.time(),
    }

    save(data)

    return True, "", data["users"][key]["slot"]


# ============================================================
# 들어오기
# ============================================================

def verify(user_id, password):
    """맞으면 기억 자리를, 틀리면 None.

    아이디가 없을 때도 있는 것처럼 한 번 계산하고 나간다.
    바로 돌아서면 걸린 시간만으로 '그 아이디는 있다' 는 것이 새어 나간다.
    """

    data = load()
    rec = data["users"].get(_key(user_id))

    if not rec:
        _hash(password, "00" * 16)
        return None

    want = str(rec.get("hash", ""))
    got = _hash(password, rec.get("salt", "00" * 16), rec.get("iter", ITERATIONS))

    # 글자를 하나씩 비교하면 몇 글자까지 맞았는지가 시간으로 드러난다.
    if not hmac.compare_digest(want, got):
        return None

    return rec.get("slot")


def display_name(user_id):
    """만들 때 적은 그대로의 아이디."""

    rec = load()["users"].get(_key(user_id))

    return rec.get("id") if rec else str(user_id or "")


def touch_login(user_id):
    """마지막으로 들어온 시각을 적는다."""

    data = load()
    key = _key(user_id)

    if key not in data["users"]:
        return None

    data["users"][key]["last_login"] = time.time()
    save(data)

    return data["users"][key]["last_login"]


def change_password(user_id, old_password, new_password):
    """비밀번호를 바꾼다. (되었는가, 할 말)"""

    if verify(user_id, old_password) is None:
        return False, "지금 비밀번호가 맞지 않습니다."

    ok, msg = check_pw(new_password)
    if not ok:
        return False, msg

    data = load()
    key = _key(user_id)

    salt = secrets.token_hex(16)
    data["users"][key]["salt"] = salt
    data["users"][key]["hash"] = _hash(new_password, salt)
    data["users"][key]["iter"] = ITERATIONS

    save(data)

    return True, ""

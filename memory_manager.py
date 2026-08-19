
# memory_manager.py
# diamondAI - 기억 관리 시스템
#
# 기억을 다음 두 영역으로 분리한다.
#
# 1. conversation
#    - 실제 사용자와 나눈 대화 기록
#    - /기억삭제 명령으로 삭제된다.
#
# 2. long_term
#    - 앞으로 명확하게 중요한 정보만 저장할 공간
#    - 현재 단계에서는 AI가 자동으로 함부로 추가하지 않는다.
#
# 다이아의 기본 성격, 이름, 정체성 등은
# 이 파일에 저장하지 않는다.
#
# 그것들은 ai_brain.py의 SYSTEM_PROMPT가 담당한다.
# 따라서 /기억삭제를 해도 다이아 자체가 초기화되지 않는다.


import json
import os
import tempfile

from config import MEMORY_FILE_PATH


# ============================================================
# 기본 기억 구조
# ============================================================

DEFAULT_MEMORY = {
    "conversation": [],
    "long_term": []
}


# ============================================================
# 내부: 기본 구조 생성
# ============================================================

def _create_default_memory():
    """
    새로운 기억 저장 구조를 반환한다.
    """

    return {
        "conversation": [],
        "long_term": [],
        "relationship": {}
    }


# ============================================================
# 기억 전체 불러오기
# ============================================================

def load_memory_data():
    """
    memory_store.json 전체를 불러온다.

    반환 형식:

    {
        "conversation": [...],
        "long_term": [...]
    }

    파일이 없거나 손상되었다면
    빈 기억 구조를 반환한다.
    """

    if not os.path.exists(MEMORY_FILE_PATH):
        return _create_default_memory()

    try:

        with open(
            MEMORY_FILE_PATH,
            "r",
            encoding="utf-8"
        ) as f:

            data = json.load(f)

    except (
        json.JSONDecodeError,
        OSError,
        TypeError,
        ValueError
    ) as e:

        print(
            f"[기억 파일 읽기 오류]: {e}"
        )

        return _create_default_memory()

    # --------------------------------------------------------
    # 예전 버전의 memory_store.json과의 호환
    #
    # 예전에는 파일 자체가:
    #
    # [
    #   {"role": "user", ...},
    #   {"role": "assistant", ...}
    # ]
    #
    # 형태였을 가능성이 있다.
    #
    # 이 경우 기존 대화 기록을 conversation으로 이동한다.
    # --------------------------------------------------------

    if isinstance(data, list):

        return {
            "conversation": data,
            "long_term": [],
            "relationship": {}
        }

    # --------------------------------------------------------
    # 새로운 구조
    # --------------------------------------------------------

    if not isinstance(data, dict):
        return _create_default_memory()

    conversation = data.get(
        "conversation",
        []
    )

    long_term = data.get(
        "long_term",
        []
    )

    relationship = data.get(
        "relationship",
        {}
    )

    user = data.get(
        "user",
        {}
    )

    # 지금 얼마나 상해 있는지.
    #
    # 여기 안 적어 두면 저장할 때마다 사라진다 — 이 함수가 아는 항목만
    # 골라 새 dict 를 만들어 돌려주기 때문이다.
    mood = data.get(
        "mood",
        {}
    )

    if not isinstance(mood, dict):
        mood = {}

    if not isinstance(conversation, list):
        conversation = []

    if not isinstance(long_term, list):
        long_term = []

    if not isinstance(relationship, dict):
        relationship = {}

    if not isinstance(user, dict):
        user = {}

    return {
        "conversation": conversation,
        "long_term": long_term,
        "relationship": relationship,
        "user": user,
        "mood": mood
    }


# ============================================================
# 기억 전체 저장
# ============================================================

def save_memory_data(data):
    """
    기억 전체를 안전하게 저장한다.

    직접 파일을 덮어쓰는 대신
    임시 파일에 먼저 저장한 후 교체한다.

    이렇게 하면 저장 중 프로그램이 종료되더라도
    기존 memory_store.json이 깨질 가능성을 줄일 수 있다.
    """

    directory = os.path.dirname(
        os.path.abspath(MEMORY_FILE_PATH)
    )

    os.makedirs(
        directory,
        exist_ok=True
    )

    fd, temp_path = tempfile.mkstemp(
        prefix="memory_",
        suffix=".tmp",
        dir=directory
    )

    try:

        with os.fdopen(
            fd,
            "w",
            encoding="utf-8"
        ) as f:

            json.dump(
                data,
                f,
                ensure_ascii=False,
                indent=2
            )

            f.flush()
            os.fsync(f.fileno())

        os.replace(
            temp_path,
            MEMORY_FILE_PATH
        )

    except Exception:

        try:
            os.remove(temp_path)
        except OSError:
            pass

        raise


# ============================================================
# AI가 사용하는 "대화 기록" 불러오기
# ============================================================

def load_memory():
    """
    AI 대화 엔진에서 사용하는 대화 기록만 반환한다.

    중요한 점:
    장기기억을 자동으로 섞지 않는다.

    반환:

    [
        {"role": "user", "content": "..."},
        {"role": "assistant", "content": "..."}
    ]
    """

    data = load_memory_data()

    conversation = data.get(
        "conversation",
        []
    )

    if not isinstance(
        conversation,
        list
    ):
        return []

    return conversation


# ============================================================
# 대화 메시지 추가
# ============================================================

def append_message(role, content):
    """
    일반 대화 기록을 추가한다.

    이 함수는 장기기억을 만드는 함수가 아니다.

    따라서 AI의 모든 답변은 단순한 '대화 기록'으로만 저장된다.

    AI가 과거에 한 잘못된 답변이
    자동으로 장기기억으로 승격되지 않는다.
    """

    if role not in (
        "user",
        "assistant",
        "system"
    ):
        print(
            f"[기억 저장 무시] 잘못된 role: {role}"
        )

        return load_memory()

    if content is None:
        return load_memory()

    content = str(content).strip()

    if not content:
        return load_memory()

    data = load_memory_data()

    conversation = data.get(
        "conversation",
        []
    )

    conversation.append(
        {
            "role": role,
            "content": content
        }
    )

    data["conversation"] = conversation

    save_memory_data(data)

    return conversation


# ============================================================
# 장기기억 추가
# ============================================================

def add_long_term_memory(content):
    """
    장기기억을 명시적으로 추가한다.

    현재 ai_brain.py에서는 자동으로 호출하지 않는다.

    즉, AI가 대화를 하다가 자기 마음대로
    모든 내용을 장기기억으로 저장하지 않는다.

    나중에 정말 필요한 정보만 선별해서
    이 함수를 사용하도록 만들 수 있다.
    """

    if content is None:
        return load_memory_data()

    content = str(content).strip()

    if not content:
        return load_memory_data()

    data = load_memory_data()

    long_term = data.get(
        "long_term",
        []
    )

    if content not in long_term:

        long_term.append(content)

    data["long_term"] = long_term

    save_memory_data(data)

    return data


# ============================================================
# 장기기억 불러오기
# ============================================================

def load_long_term_memory():
    """
    저장된 장기기억만 반환한다.
    """

    data = load_memory_data()

    long_term = data.get(
        "long_term",
        []
    )

    if not isinstance(
        long_term,
        list
    ):
        return []

    return long_term


# ============================================================
# 관계 상태
#
# 유저와 얼마나 가까운지, 지금 어떤 사이인지를 기억한다.
# 대화 기록과 함께 지워지지 않는다. /기억삭제로 대화를 비워도
# 쌓인 관계는 남는다. (사람 사이가 그렇듯)
# ============================================================

def load_relationship():
    """
    반환: {"affinity": int, "stage": str} 또는 값이 없으면 빈 dict
    """

    data = load_memory_data()

    rel = data.get(
        "relationship",
        {}
    )

    if not isinstance(rel, dict):
        return {}

    return rel


def save_relationship(affinity, stage_key, devotion_raw=None, lover=None,
                      wants_child=None, strokes=None, climax=None,
                      pregnant=None):
    """관계 상태를 저장한다.

    lover 는 고백을 주고받았는지다. 그 전에는 호감이 광기 앞에서 멈춘다.
    devotion_raw 는 친밀도 상한을 넘어 흘러넘친 점수다.
    상한(330)에 닿은 뒤로도 쌓이는 마음을 여기에 모은다.
    적지 않고 부르면 이미 쌓인 값을 그대로 둔다.
    """

    data = load_memory_data()

    before = data.get("relationship", {})
    if not isinstance(before, dict):
        before = {}

    if devotion_raw is None:
        devotion_raw = before.get("devotion_raw", 0)

    # 연인이 되었는가.
    #
    # 광기로 넘어가려면 그 전에 고백을 주고받아야 한다.
    # 적지 않고 부르면 이미 정해진 값을 그대로 둔다.
    if lover is None:
        lover = before.get("lover", False)

    # 아이에 관한 것 넷.
    #
    #   wants_child : 아이를 갖겠다고 말했는가
    #   strokes     : 절정까지 얼마나 왔는가. 절정마다 0으로 돌아간다
    #   climax      : 절정을 몇 번 겪었는가
    #   pregnant    : 아이가 섰는가
    #
    # 적지 않고 부르면 이미 쌓인 값을 그대로 둔다.
    if wants_child is None:
        wants_child = before.get("wants_child", False)
    if strokes is None:
        strokes = before.get("strokes", 0)
    if climax is None:
        climax = before.get("climax", 0)
    if pregnant is None:
        pregnant = before.get("pregnant", False)

    data["relationship"] = {
        "affinity": int(affinity),
        "stage": str(stage_key),
        "devotion_raw": int(devotion_raw),
        "lover": bool(lover),
        "wants_child": bool(wants_child),
        "strokes": int(strokes),
        "climax": int(climax),
        "pregnant": bool(pregnant),
    }

    save_memory_data(data)

    return data["relationship"]


def load_user_name():
    """상대가 알려준 호칭. 없으면 None."""

    data = load_memory_data()

    user = data.get("user", {})

    if not isinstance(user, dict):
        return None

    name = user.get("name")

    return name if isinstance(name, str) and name.strip() else None


def save_user_name(name):
    """상대가 알려준 호칭을 기억한다."""

    name = str(name or "").strip()

    if not name:
        return None

    data = load_memory_data()

    user = data.get("user", {})

    if not isinstance(user, dict):
        user = {}

    user["name"] = name
    data["user"] = user

    save_memory_data(data)

    return name


def reset_relationship():
    """
    관계만 처음으로 되돌린다. 대화 기록은 건드리지 않는다.
    """

    data = load_memory_data()

    data["relationship"] = {}

    save_memory_data(data)

    return True


# ============================================================
# 대화 기억 삭제
# ============================================================

def clear_memory():
    """
    사용자와의 대화 기록을 삭제한다.

    중요:

    conversation → 삭제
    long_term    → 유지

    따라서 /기억삭제를 해도
    명시적으로 저장된 장기기억은 남는다.

    또한 ai_brain.py에 있는
    SYSTEM_PROMPT는 파일과 별개의 코드이므로
    절대로 삭제되지 않는다.
    """

    data = load_memory_data()

    data["conversation"] = []

    save_memory_data(data)

    return True


# ============================================================
# 모든 기억 삭제
# ============================================================

def clear_all_memory():
    """
    정말 모든 기억을 삭제해야 할 때 사용한다.

    conversation + long_term 모두 삭제한다.

    일반적인 /기억삭제 명령에서는
    이 함수를 사용하지 않는다.
    """

    save_memory_data(
        _create_default_memory()
    )

    return True


# ============================================================
# 기억 보관하기
#
# 지금까지의 기억을 통째로 옆에 치워 두고 빈 상태에서 새로 시작한다.
# 지우는 것이 아니라 옮겨 두는 것이라, 언제든 다시 꺼내 올 수 있다.
#
# 대화만이 아니라 관계와 호칭까지 함께 옮긴다.
# 대화만 지우고 친밀도가 남으면, 처음 만난 사이인데 말투는 그대로인
# 이상한 상태가 된다.
# ============================================================

ARCHIVE_DIR = "memory_archive"


def _archive_dir():
    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(here, ARCHIVE_DIR)
    os.makedirs(path, exist_ok=True)
    return path


def _archive_files():
    """보관해 둔 것들. 최근 것이 앞에 온다."""
    path = _archive_dir()
    names = [
        n for n in os.listdir(path)
        if n.startswith("memory_") and n.endswith(".json")
    ]
    names.sort(reverse=True)
    return [os.path.join(path, n) for n in names]


def archive_memory(stamp=None):
    """지금 기억을 보관하고 빈 상태로 되돌린다.

    반환: (파일이름, 옮긴 대화 수)
    """
    from datetime import datetime

    data = load_memory_data()
    count = len(data.get("conversation", []))

    stamp = stamp or datetime.now().strftime("%Y%m%d_%H%M%S")
    name = f"memory_{stamp}.json"
    path = os.path.join(_archive_dir(), name)

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    save_memory_data(_create_default_memory())

    return name, count


def restore_memory(name=None):
    """보관해 둔 기억을 다시 꺼내 온다.

    name 을 주지 않으면 가장 최근 것을 꺼낸다.
    지금 기억은 꺼내기 직전에 따로 보관해 둔다 — 잘못 눌렀을 때
    되돌릴 데가 없으면 안 되기 때문이다.

    반환: (파일이름, 되살린 대화 수) / 보관된 것이 없으면 None
    """
    files = _archive_files()

    if name:
        path = os.path.join(_archive_dir(), name)
        if not os.path.exists(path):
            return None
    else:
        if not files:
            return None
        path = files[0]

    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        print(f"[기억 꺼내기 오류]: {e}")
        return None

    # 지금 것을 먼저 치워 둔다
    from datetime import datetime
    now = load_memory_data()
    if now.get("conversation"):
        keep = os.path.join(
            _archive_dir(),
            "memory_" + datetime.now().strftime("%Y%m%d_%H%M%S") + "_before_restore.json"
        )
        try:
            with open(keep, "w", encoding="utf-8") as f:
                json.dump(now, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[꺼내기 전 보관 오류]: {e}")

    save_memory_data(data)

    return os.path.basename(path), len(data.get("conversation", []))


def list_archives():
    """보관해 둔 것들의 요약."""
    out = []
    for p in _archive_files():
        try:
            with open(p, encoding="utf-8") as f:
                d = json.load(f)
            rel = d.get("relationship", {}) or {}
            out.append({
                "name": os.path.basename(p),
                "messages": len(d.get("conversation", [])),
                "affinity": rel.get("affinity"),
                "stage": rel.get("stage"),
            })
        except Exception:
            out.append({"name": os.path.basename(p), "messages": None})
    return out


# ============================================================
# 최근 대화만 가져오기
# ============================================================

def load_recent_memory(limit=40):
    """
    최근 대화만 가져온다.

    대화가 수천 개 쌓이더라도
    AI에게 무한정 전달하지 않기 위한 기능이다.

    기본값: 최근 40개 메시지
    """

    try:
        limit = int(limit)
    except (
        TypeError,
        ValueError
    ):
        limit = 40

    if limit <= 0:
        return []

    conversation = load_memory()

    return conversation[-limit:]


# ============================================================
# 기억 통계
# ============================================================

def get_memory_info():
    """
    현재 기억 상태를 확인하기 위한 함수.
    디버깅이나 관리자 기능에서 사용할 수 있다.
    """

    data = load_memory_data()

    conversation = data.get(
        "conversation",
        []
    )

    long_term = data.get(
        "long_term",
        []
    )

    return {
        "conversation_count": len(
            conversation
        ),
        "long_term_count": len(
            long_term
        )
    }


def load_mood():
    """지금 기분. {"raw": int, "since": float} — 없으면 빈 dict."""

    data = load_memory_data()

    mood = data.get("mood", {})

    if not isinstance(mood, dict):
        return {}

    return mood


def save_mood(raw, since):
    """기분을 저장한다.

    since 는 그 값이 된 시각이다. 저절로 풀리는 계산에 쓴다 —
    뒤에서 시계를 돌리지 않고, 읽을 때마다 지난 시간을 재서 깎는다.
    """

    data = load_memory_data()

    data["mood"] = {
        "raw": int(raw),
        "since": float(since),
    }

    save_memory_data(data)

    return data["mood"]

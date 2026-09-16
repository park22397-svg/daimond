
# main.py
# diamondAI - Flask 서버 메인 실행 파일

import json
import os
import secrets
from datetime import timedelta

from flask import (
    Flask,
    jsonify,
    redirect,
    render_template,
    request,
    session
)

import accounts
import config
import memory_manager
import store
import who
from ai_brain import extract_expression, process_chat
from avatar import AVATAR
from memory_manager import (
    load_memory,
    clear_memory
)


app = Flask(__name__)


def _stage_now(affinity, before=None):
    """지금 어떤 사이인가. **말투까지 정해진 것으로** 돌려준다.

    단계 표에는 친구부터 '반말' 이라 적혀 있지만, 말은 누군가 놓자고
    하고 상대가 받아야 놓는 것이다. 아직이면 존댓말로 되돌린다.

    말투를 보는 자리가 열두 군데라 여기 한 곳을 지나게 한다 —
    한 군데만 빠뜨려도 거기서만 반말이 튀어나온다.
    """

    saved = memory_manager.load_relationship() or {}
    grants = AVATAR.gate_grants(saved)

    return AVATAR.next_stage(affinity, before, grants)


def _stage_label(stage):
    """화면에 적을 이름표.

    넘을 수 있는 문턱이 있으면 괄호로 붙는다 — '서먹함(친구 가능)'.
    안 알려 주면 사람은 그 자리가 열린 줄 모른다. 호감만 오르고
    이름표는 그대로여서 고장 난 것처럼 보인다.
    """
    saved = memory_manager.load_relationship() or {}

    return AVATAR.stage_label(stage, saved.get("affinity", 0),
                              AVATAR.gate_grants(saved))



# ============================================================
# 누구인가
#
# 계정을 나누기 전에는 기억 파일이 하나뿐이라 누가 들어오든
# 같은 기억을 이어 썼다. 내가 쌓은 친밀도를 남이 물려받고
# 내가 나눈 이야기를 남이 읽었다.
#
# 여기서 하는 일은 두 가지뿐이다.
#   1. 쿠키에 적힌 아이디를 읽어 who 에 적는다
#   2. 로그인하지 않았으면 들여보내지 않는다
#
# 기억을 실제로 가르는 것은 memory_manager 쪽이다. 이 파일은
# '누구인지' 만 알려 준다.
# ============================================================

# 쿠키에 서명할 열쇠.
#
# 매번 새로 만들면 서버를 다시 켤 때마다 모두 로그아웃된다.
# 그래서 한 번 만들어 파일에 두고 다음부터는 그것을 읽는다.
# 이 파일이 새면 남의 쿠키를 지어낼 수 있으므로 저장소에 올리지 않는다.
def _secret_key():
    # 올린 데서는 파일이 안 남는다. 기계가 바뀔 때마다 열쇠가 새로 생기면
    # 그때마다 모두 로그아웃된다. 그래서 환경변수를 먼저 본다.
    env = os.environ.get("SECRET_KEY", "").strip()

    if len(env) >= 32:
        return env

    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".secret_key")

    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                key = f.read().strip()
            if len(key) >= 32:
                return key
        except OSError:
            pass

    key = secrets.token_hex(32)

    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(key)
    except OSError as e:
        # 읽기 전용인 데서는 못 쓴다. 그래도 이번 판은 돌아간다 —
        # 다만 기계가 바뀌면 로그인이 풀리므로 SECRET_KEY 를 넣어야 한다.
        print("[열쇠 저장 실패]:", e)
        print("[알림] SECRET_KEY 환경변수를 넣으면 로그인이 유지됩니다.")

    return key


app.secret_key = _secret_key()

# 로그인한 채로 두는 기간. 창을 닫아도 유지된다.
app.permanent_session_lifetime = timedelta(days=30)


# 로그인 없이 지나갈 수 있는 자리.
#
# 로그인 화면 자체와, 로그인하려고 부르는 것들.
# 여기 빠진 것은 전부 막힌다 — 새 API 를 만들 때 따로 챙길 일이 없다.
OPEN_PATHS = {
    "/api/health",
    "/login",
    "/api/login",
    "/api/signup",
    "/api/whoami",
}


def current_user():
    """지금 들어와 있는 사람의 아이디. 없으면 None."""

    return session.get("user")


@app.before_request
def _bind_user():
    """요청마다 '지금 누구인가' 를 정한다.

    **반드시 요청마다** — 스레드는 다시 쓰이므로, 안 정하면
    앞사람의 자리가 그대로 남아 남의 기억을 쓰게 된다.
    """

    path = request.path or "/"

    user = session.get("user")
    slot = session.get("slot")

    # 쿠키는 남았는데 계정이 사라진 경우(파일을 지웠다든지).
    # 없는 사람의 기억을 열지 않도록 여기서 끊는다.
    if user and accounts.slot_of(user) != slot:
        session.clear()
        user = None
        slot = None

    who.set_current(slot)

    # 이번 요청 동안 읽은 것을 담아 둘 자리를 연다.
    #
    # **반드시 요청마다** — 안 열고 지나가면 앞 요청의 값이 남아
    # 남의 기억을 읽는다. who.set_current 와 같은 자리에 둔 이유다.
    store.begin_request()

    if user:
        return None

    # /static/ 도 막는다.
    #
    # 거기 있는 것은 아바타 파일과 배경뿐이다. 로그인 화면은 제 안에
    # 글씨와 색을 다 갖고 있어서 static 이 필요 없다.
    #
    # 열어 두면 주소만 알면 누구나 아바타를 통째로 내려받는다.
    # 파일 안에 Redistribution_Prohibited 가 박혀 있는 물건이다.
    # 막아 두면 계정이 있는 사람만 받을 수 있고, 계정은 가입 암호를
    # 아는 사람만 만든다.
    if path in OPEN_PATHS:
        return None

    # API 는 화면을 돌려줄 데가 없으므로 숫자로 답한다.
    if path.startswith("/api/"):
        return jsonify({"ok": False, "error": "로그인이 필요합니다."}), 401

    return redirect("/login")


# ============================================================
# 로그인 화면
# ============================================================

@app.route("/login")
def login_page():
    if current_user():
        return redirect("/")

    return render_template(
        "login.html",
        first=(accounts.count() == 0),
        legacy=memory_manager.legacy_summary(),
        need_code=bool(os.environ.get("SIGNUP_CODE", "").strip()),
    )


@app.after_request
def _save_changes(response):
    """이번 요청에서 바뀐 것을 실제로 적는다.

    teardown 이 아니라 여기서 한다 — teardown 은 답을 이미 보낸 뒤에
    돌 수 있어서, 올린 데에서는 그때 기계가 멈춰 있을 수 있다.
    """

    try:
        store.flush()
    except Exception as e:
        print("[저장 실패]", e)

    return response


@app.teardown_request
def _unbind_user(exc=None):
    """요청이 끝나면 담아 둔 것을 버린다.

    스레드는 다시 쓰이므로 두고 가면 다음 사람이 그것을 읽는다.
    """

    store.end_request()


@app.route("/api/health")
def health_api():
    """올린 것이 제대로 실렸는지.

    아바타 파일이 짐에서 조용히 빠지는 일이 있었다. 빌드 캐시를 쓰는
    배포에서 static/ 이 통째로 안 실렸는데, 화면은 멀쩡히 뜨고
    **다이아만 없었다.** 눈으로는 로그인해서 들어가 봐야 알 수 있다.
    그래서 파일이 있는지만 알려 주는 자리를 둔다.

    파일 내용은 안 준다. 있는지 없는지만 말한다.
    """

    here = os.path.dirname(os.path.abspath(__file__))

    def has(rel):
        return os.path.exists(os.path.join(here, rel))

    # 어느 판이 올라와 있는가.
    #
    # 종료 코드만 믿으면 안 된다. 올라갔는데 실패라고 하기도 하고,
    # 빌드 캐시 때문에 아바타가 빠졌는데 성공이라고 하기도 한다.
    # 올리기 전에 적어 둔 표를 그대로 돌려주면, 올린 쪽이 방금 그것이
    # 맞는지 눈으로 확인할 수 있다.
    build = None

    try:
        with open(os.path.join(here, "build.json"), encoding="utf-8") as f:
            build = json.load(f).get("stamp")
    except Exception:
        pass

    return jsonify({
        "ok": True,
        "build": build,
        "avatar": has("static/avatar.vrm"),
        "body": has("static/body.vrm"),
        "store": store.backend(),
        "model_set": bool((store.read_json(config.RUNTIME_KEY) or {})
                          .get("ollama_url")),
    })


@app.route("/api/whoami")
def whoami_api():
    """지금 누구로 들어와 있는가. 화면이 물어본다."""

    user = current_user()

    if not user:
        return jsonify({"ok": True, "user": None})

    return jsonify({
        "ok": True,
        "user": accounts.display_name(user),
        "slot": session.get("slot"),
    })


@app.route("/api/signup", methods=["POST"])
def signup_api():
    """계정을 만든다.

    새 계정은 **빈 기억**으로 시작한다. 앞사람이 무엇을 했든
    모르는 상태에서 만난다 — 이것이 계정을 나눈 이유다.
    다만 맨 처음 만드는 계정 하나는 계정을 나누기 전에 쌓인
    기억을 물려받는다. 그러지 않으면 그동안의 관계가 손 닿지
    않는 데로 밀려난다.
    """

    data = request.get_json(silent=True) or {}

    user_id = str(data.get("id") or "").strip()
    password = str(data.get("password") or "")
    again = str(data.get("again") or "")

    if again and again != password:
        return jsonify({"ok": False, "error": "비밀번호가 서로 다릅니다."})

    # 아무나 들어오지 못하게.
    #
    # 내 컴퓨터에서만 돌 때는 필요 없었다. 밖에 올리면 주소를 아는
    # 사람은 누구나 계정을 만들 수 있으므로, SIGNUP_CODE 를 넣어 두면
    # 그것을 아는 사람만 만들 수 있다. 안 넣으면 지금까지와 같다.
    need = os.environ.get("SIGNUP_CODE", "").strip()

    if need and str(data.get("code") or "").strip() != need:
        return jsonify({"ok": False, "error": "가입 암호가 맞지 않습니다."})

    first = accounts.count() == 0

    ok, msg, slot = accounts.create(user_id, password)

    if not ok:
        return jsonify({"ok": False, "error": msg})

    inherited = False

    if first:
        inherited = memory_manager.inherit_legacy(slot)

    if not inherited:
        memory_manager.start_fresh(slot)

    session.permanent = True
    session["user"] = user_id
    session["slot"] = slot
    who.set_current(slot)

    accounts.touch_login(user_id)

    return jsonify({
        "ok": True,
        "user": accounts.display_name(user_id),
        "inherited": inherited,
    })


@app.route("/api/login", methods=["POST"])
def login_api():
    """들어온다. 그 사람이 쌓아 둔 기억이 그대로 열린다."""

    data = request.get_json(silent=True) or {}

    user_id = str(data.get("id") or "").strip()
    password = str(data.get("password") or "")

    slot = accounts.verify(user_id, password)

    # 아이디가 틀렸는지 비밀번호가 틀렸는지 알려 주지 않는다.
    # 알려 주면 어느 아이디가 있는지를 하나씩 확인할 수 있다.
    if slot is None:
        return jsonify({"ok": False, "error": "아이디나 비밀번호가 맞지 않습니다."})

    session.permanent = True
    session["user"] = user_id
    session["slot"] = slot
    who.set_current(slot)

    accounts.touch_login(user_id)

    return jsonify({"ok": True, "user": accounts.display_name(user_id)})


@app.route("/api/logout", methods=["POST"])
def logout_api():
    """나간다. 기억은 그대로 남는다 — 다음에 들어오면 이어진다."""

    session.clear()
    who.clear()

    return jsonify({"ok": True})


# ============================================================
# 메인 페이지
# ============================================================

@app.route("/")
def index():
    return render_template(
        "index.html"
    )


# ============================================================
# AI 채팅 API
# ============================================================

@app.route(
    "/api/chat",
    methods=["POST"]
)
def chat_api():

    try:

        data = request.get_json(
            silent=True
        )

        if not isinstance(
            data,
            dict
        ):
            return jsonify(
                {
                    "error":
                    "잘못된 요청입니다."
                }
            ), 400

        user_text = data.get(
            "message",
            ""
        )

        if user_text is None:
            user_text = ""

        user_text = str(
            user_text
        ).strip()

        if not user_text:

            return jsonify(
                {
                    "error":
                    "메시지가 비어있습니다."
                }
            ), 400

        # 카메라가 켜져 있으면 화면이 '지금 보이는 것' 을 같이 보낸다.
        # 그러면 말을 걸 때마다 다이아가 상대를 보면서 답한다.
        result = process_chat(
            user_text,
            seeing=(data.get("seeing") or None),
            cut_off=bool(data.get("cut_off")),
            woke=bool(data.get("woke")),
        )

        # 답에 (배경: 공원) · (옷: 교복) 이 섞여 있으면 실제로 옮기고 갈아입는다
        result = _apply_wear(_apply_place(result))

        return jsonify(
            result
        )

    except Exception as e:

        print(
            f"[채팅 API 오류]: {e}"
        )

        return jsonify(
            {
                "expression":
                "neutral",

                "reply":
                "앗, 잠깐 문제가 생겼어. 다시 말해줄래?"
            }
        ), 500


# ============================================================
# 대화 기록 조회 API
# ============================================================

@app.route(
    "/api/history",
    methods=["GET"]
)
def history_api():

    try:

        history = load_memory()

        return jsonify(
            history
        )

    except Exception as e:

        print(
            f"[기억 조회 오류]: {e}"
        )

        return jsonify(
            {
                "error":
                "기억을 불러올 수 없습니다."
            }
        ), 500


# ============================================================
# 기억 삭제 API
# ============================================================

@app.route(
    "/api/memory/clear",
    methods=["POST"]
)
def clear_memory_api():

    try:

        clear_memory()

        print(
            "[diamondAI] 대화 기억이 초기화되었습니다."
        )

        return jsonify(
            {
                "success": True,
                "message":
                "이전 대화 기억을 모두 지웠어. 이제 새로 시작하자!"
            }
        )

    except Exception as e:

        print(
            f"[기억 삭제 오류]: {e}"
        )

        return jsonify(
            {
                "success": False,
                "error":
                "기억 삭제 중 오류가 발생했어."
            }
        ), 500


# ============================================================
# 아바타 개체 API
#
# 페르소나와 아바타가 하나의 개체가 되면서,
# 서버와 화면이 같은 정의를 공유할 수 있게 되었다.
# 화면은 더 이상 표정 수치를 스스로 들고 있을 필요가 없다.
# ============================================================

@app.route(
    "/api/avatar",
    methods=["GET"]
)
def avatar_api():

    try:

        return jsonify(
            AVATAR.to_dict()
        )

    except Exception as e:

        print(
            f"[아바타 조회 오류]: {e}"
        )

        return jsonify(
            {
                "error":
                "아바타 정보를 불러올 수 없습니다."
            }
        ), 500


@app.route(
    "/api/avatar/prompt",
    methods=["GET"]
)
def avatar_prompt_api():
    """아바타가 자기 페르소나로 만들어내는 시스템 프롬프트."""

    try:

        want_guide = request.args.get(
            "guide",
            ""
        ).lower() in ("1", "true", "yes")

        return jsonify(
            {
                "with_expression_guide": want_guide,

                "prompt":
                AVATAR.system_prompt(
                    include_expression_guide=want_guide
                ),
            }
        )

    except Exception as e:

        print(
            f"[프롬프트 조회 오류]: {e}"
        )

        return jsonify(
            {
                "error":
                "프롬프트를 만들 수 없습니다."
            }
        ), 500


@app.route(
    "/api/expression/detect",
    methods=["POST"]
)
def detect_expression_api():
    """문장을 넣으면 아바타가 어떤 표정을 짓게 되는지 알려준다.

    Ollama를 거치지 않으므로 감정 판단만 따로 시험해볼 수 있다.
    """

    try:

        data = request.get_json(
            silent=True
        )

        if not isinstance(
            data,
            dict
        ):
            return jsonify(
                {
                    "error":
                    "잘못된 요청입니다."
                }
            ), 400

        text = str(
            data.get("text", "")
        )

        expression, clean_text = extract_expression(
            text
        )

        return jsonify(
            {
                "expression": expression,
                "clean_text": clean_text,
            }
        )

    except Exception as e:

        print(
            f"[표정 판단 오류]: {e}"
        )

        return jsonify(
            {
                "error":
                "표정을 판단할 수 없습니다."
            }
        ), 500


@app.route(
    "/api/relationship",
    methods=["GET"]
)
def relationship_api():
    """지금 유저와 어떤 사이인지."""

    try:

        from memory_manager import load_relationship

        saved = load_relationship() or {}

        affinity = saved.get(
            "affinity",
            AVATAR.relationship.get("start_affinity", 0)
        )

        stage = _stage_now(
            affinity,
            saved.get("stage")
        )

        import time as _t
        from memory_manager import load_mood

        _m = load_mood()
        mood = AVATAR.mood_now(_m.get("raw", 0), _m.get("since"), _t.time())
        mood_tier = AVATAR.mood_tier(mood)

        return jsonify(
            {
                "affinity": affinity,
                "stage": stage.key,
                "label": _stage_label(stage),
                "speech": stage.speech,
                "attitude": stage.attitude,
                # 사귀는 사이인가
                "lover": bool(saved.get("lover", False)),
                # 같은 친구라도 오늘은 어떤 온도인가
                "warmth": AVATAR.warmth_label(affinity),
                "ceiling": AVATAR.confess_ceiling(),
                # 지금 상해 있는가
                "mood": mood,
                "mood_label": mood_tier.get("label") if mood_tier else None,
                "mood_expression": (mood_tier.get("expression")
                                    if mood_tier else None),
            }
        )

    except Exception as e:

        print(
            f"[관계 조회 오류]: {e}"
        )

        return jsonify(
            {
                "error":
                "관계 정보를 불러올 수 없습니다."
            }
        ), 500


@app.route(
    "/api/touch",
    methods=["POST"]
)
def touch_api():
    """마우스로 아바타를 만졌을 때의 반응.

    화면은 '어느 본에 가장 가까운 곳을 눌렀는가' 만 보낸다.
    그 자리가 어디인지, 만져도 되는 사이인지, 무슨 말을 할지는
    전부 아바타 개체가 정한다.

    받는 값:
      bone   : 닿은 지점에서 가장 가까운 본 이름
      local  : 그 본의 좌표계에서의 닿은 위치 [x, y, z] (머리 나누기에 쓴다)
      kind   : "tap" 한 번 누름 / "pet" 쓰다듬기 / "kiss" 입맞춤
      count  : 쓰다듬은 횟수
    """

    try:

        import time

        from memory_manager import (
            append_message,
            load_relationship,
            save_relationship,
            load_mood,
            save_mood,
        )

        data = request.get_json(silent=True) or {}

        bone = data.get("bone")
        local = data.get("local")
        kind = "pet" if data.get("kind") == "pet" else "tap"

        # 화면은 '눈을 감고 기다리는 중이었다' 만 알려준다(kiss_ready).
        # 그것이 정말 입맞춤인지는 아래에서 자리와 도구를 안 뒤에 정한다 —
        # 어느 자리를 만졌는지 아는 쪽은 화면이 아니라 여기다.
        kiss_ready = bool(data.get("kiss_ready"))
        count = int(data.get("count") or 1)

        saved = load_relationship() or {}

        affinity = saved.get(
            "affinity",
            AVATAR.relationship.get("start_affinity", 0)
        )

        stage = _stage_now(
            affinity,
            saved.get("stage")
        )

        tool = AVATAR.touch_tool(data.get("tool"))

        # 옷 판정구는 자기가 어느 자리인지 직접 들고 온다.
        # 다만 잡는 도구가 아니면 무시하고 안쪽 몸으로 넘어간다.
        #
        # 벗겨 둔 옷이면 그 자리는 없는 것으로 친다. 없는 옷을
        # 잡을 수는 없으므로 안쪽 몸으로 넘긴다.
        _zone_key = data.get("zone")

        _undressed = data.get("undressed")
        if isinstance(_undressed, list) and _zone_key in _undressed:
            _zone_key = None

        zone = AVATAR.zone_for(
            bone,
            local,
            zone_key=_zone_key,
            tool=tool,
        )

        if zone is None:
            return jsonify(
                {
                    "hit": False,
                    "bone": bone,
                }
            )

        # 기다리고 있었고, 그 도구로 그 자리를 만졌다면 입맞춤이다.
        # 셋 중 하나라도 어긋나면 평소대로 누른 것이 된다.
        if kiss_ready and kind == "tap":
            kc = AVATAR.touch.get("kiss", {})
            if (kc.get("enabled")
                    and tool is not None
                    and tool.key == kc.get("tool")
                    and zone.key == kc.get("zone")):
                kind = "kiss"

        # 기분을 풀거나 상하게 한다.
        #
        # 쓰다듬으면 풀리고, 아직 허락 안 된 곳을 만지면 더 상한다.
        # 다정한 자리(머리·얼굴·손)일수록 많이 풀린다.
        now = time.time()
        saved_mood = load_mood()
        mood_before = AVATAR.mood_now(
            saved_mood.get("raw", 0), saved_mood.get("since"), now)

        mood_after = mood_before
        if mood_before > 0 or not result["allowed"]:
            delta = AVATAR.mood_soothe(zone.key, result["allowed"])
            mood_after = AVATAR.mood_clamp(mood_before - delta)

            if mood_after != mood_before:
                save_mood(mood_after, now)
                print(f"[기분]: {mood_before} -> {mood_after} "
                      f"({zone.label or zone.key}, {delta:+d})")

        # 기분이 풀렸으면 그 말을 앞세운다.
        # 자리마다 정해 둔 대사보다 이쪽이 지금 상황에 맞는 말이다.
        eased = AVATAR.mood_reply(mood_after, mood_before, stage)
        if eased:
            result["reply"] = eased["reply"]
            if eased.get("expression"):
                result["expression"] = eased["expression"]
            if eased.get("motion"):
                result["motion"] = eased["motion"]
            result["mood_eased"] = True

        result["mood"] = mood_after
        tier = AVATAR.mood_tier(mood_after)
        result["mood_label"] = tier.get("label") if tier else None

        # 친밀도를 옮기고 단계를 다시 본다
        before = stage.key

        # 몇 점 깎는 것으로 끝나지 않는 자리가 있다.
        # 그때는 개체가 '어느 값까지 떨어질지'를 직접 알려준다.
        # 얀데레처럼 더는 식지 않는 단계라면 그것도 깎이지 않는다.
        drop_to = result.get("affinity_to")

        if drop_to is not None and not getattr(stage, "never_falls", False):
            affinity = AVATAR.clamp_affinity(drop_to)
            print(f"[만지기]: 허락되지 않은 자리 — 친밀도를 {affinity} 로 떨어뜨립니다.")
        else:
            lover = bool(saved.get("lover", False))

            affinity = AVATAR.apply_delta(
                affinity,
                result["affinity_delta"],
                stage,
                lover=lover,
            )

        stage = _stage_now(affinity, before)

        try:
            save_relationship(affinity, stage.key, 0,
                              bool(saved.get("lover", False)))
        except Exception as e:
            print(f"[만지기 관계 저장 오류]: {e}")

        # 기록에 남길 만한 것만 남긴다.
        # 쓰다듬는 동안 매 순간을 다 적으면 대화 기록이 이것만으로 찬다.
        remember = (kind == "tap") or (count <= 1) or (not result["allowed"])

        # 이름을 내지 않는 자리는 기록에도 남기지 않는다.
        # 이름이 없으니 "(를 만졌다)" 같은 빈 줄이 남게 된다.
        if zone.hidden:
            remember = False

        if remember and result["reply"]:
            try:
                # 자리마다 도구 이름이 달라진다.
                # 손가락은 입과 보지에서 다른 것이 된다 — 기록에도
                # 그렇게 적어야 한다. 모델이 읽는 것은 기록이라,
                # 여기에 '손가락' 이라 적으면 나중에 물었을 때
                # 손가락이었다고 답한다.
                name = tool.label_for(zone.key) if tool else ""
                how = f"{tool.with_ro(name)} " if tool and tool.key != "hand" else ""
                append_message(
                    "user", f"({how}{tool.with_eul(zone.label)} 만졌다)")
                append_message("assistant", result["reply"])
            except Exception as e:
                print(f"[만지기 기록 오류]: {e}")

        result.update(
            {
                "hit": True,
                "bone": bone,
                "affinity": affinity,
                "stage": stage.key,
                "stage_label": _stage_label(stage),
                "changed_from": before if before != stage.key else None,
            }
        )

        return jsonify(result)

    except Exception as e:

        print(
            f"[만지기 오류]: {e}"
        )

        return jsonify(
            {
                "hit": False,
                "error": "반응을 만들지 못했습니다."
            }
        ), 500


@app.route(
    "/api/memory/archive",
    methods=["POST"]
)
def memory_archive_api():
    """지금까지의 기억을 옆에 치워 두고 빈 상태에서 새로 시작한다.

    지우는 것이 아니라 옮기는 것이다. /api/memory/restore 로 다시 꺼낸다.
    """

    try:

        from memory_manager import archive_memory

        name, count = archive_memory()

        stage = _stage_now(
            AVATAR.relationship.get("start_affinity", 0)
        )

        print(f"[기억 보관]: {name} ({count}개)")

        return jsonify(
            {
                "ok": True,
                "name": name,
                "messages": count,
                "affinity": AVATAR.relationship.get("start_affinity", 0),
                "stage": stage.key,
                "stage_label": _stage_label(stage),
            }
        )

    except Exception as e:

        print(f"[기억 보관 오류]: {e}")

        return jsonify(
            {"ok": False, "error": "기억을 보관하지 못했습니다."}
        ), 500


@app.route(
    "/api/memory/restore",
    methods=["POST"]
)
def memory_restore_api():
    """치워 뒀던 기억을 다시 꺼내 온다."""

    try:

        from memory_manager import (
            list_archives,
            load_relationship,
            restore_memory,
        )

        data = request.get_json(silent=True) or {}
        got = restore_memory(data.get("name"))

        if got is None:
            return jsonify(
                {
                    "ok": False,
                    "error": "보관해 둔 기억이 없습니다.",
                    "archives": list_archives(),
                }
            ), 404

        name, count = got

        saved = load_relationship() or {}
        affinity = saved.get(
            "affinity",
            AVATAR.relationship.get("start_affinity", 0)
        )
        stage = _stage_now(affinity, saved.get("stage"))

        print(f"[기억 꺼냄]: {name} ({count}개)")

        return jsonify(
            {
                "ok": True,
                "name": name,
                "messages": count,
                "affinity": affinity,
                "stage": stage.key,
                "stage_label": _stage_label(stage),
            }
        )

    except Exception as e:

        print(f"[기억 꺼내기 오류]: {e}")

        return jsonify(
            {"ok": False, "error": "기억을 꺼내지 못했습니다."}
        ), 500


@app.route(
    "/api/memory/archives",
    methods=["GET"]
)
def memory_archives_api():
    """보관해 둔 기억 목록."""

    try:
        from memory_manager import list_archives
        return jsonify({"ok": True, "archives": list_archives()})
    except Exception as e:
        print(f"[기억 목록 오류]: {e}")
        return jsonify({"ok": False, "archives": []}), 500


@app.route(
    "/api/rps",
    methods=["POST"]
)
def rps_api():
    """가위바위보 한 판.

    화면은 사람이 낸 것만 보낸다.
    다이아가 무엇을 낼지, 뭐라고 할지, 친밀도가 얼마나 움직일지는
    전부 아바타 개체가 정한다.
    """

    try:

        from memory_manager import (
            append_message,
            load_relationship,
            save_relationship,
        )

        data = request.get_json(silent=True) or {}

        saved = load_relationship() or {}

        affinity = saved.get(
            "affinity",
            AVATAR.relationship.get("start_affinity", 0)
        )

        stage = _stage_now(
            affinity,
            saved.get("stage")
        )

        result = AVATAR.rps_play(
            data.get("hand"),
            stage=stage,
            affinity=affinity,
        )

        if result is None:
            return jsonify(
                {
                    "ok": False,
                    "error": "가위바위보에 없는 손입니다."
                }
            ), 400

        before = stage.key

        affinity = AVATAR.apply_delta(
            affinity,
            result["affinity_delta"],
            stage,
        )

        stage = _stage_now(affinity, before)

        try:
            save_relationship(affinity, stage.key)
        except Exception as e:
            print(f"[가위바위보 관계 저장 오류]: {e}")

        _rps_tally(result.get("result"))

        # 놀았다는 사실이 대화에도 남아야 다음 말이 이어진다
        if result["reply"]:
            try:
                append_message(
                    "user",
                    f"(가위바위보 — 나는 {result['you_label']}, "
                    f"다이아는 {result['mine_label']})"
                )
                append_message("assistant", result["reply"])
            except Exception as e:
                print(f"[가위바위보 기록 오류]: {e}")

        result.update(
            {
                "ok": True,
                "affinity": affinity,
                "stage": stage.key,
                "stage_label": _stage_label(stage),
            }
        )

        return jsonify(result)

    except Exception as e:

        print(
            f"[가위바위보 오류]: {e}"
        )

        return jsonify(
            {
                "ok": False,
                "error": "판을 벌이지 못했습니다."
            }
        ), 500


@app.route(
    "/api/first-talk",
    methods=["POST", "GET"]
)
def first_talk_api():
    """상대가 한동안 조용할 때 다이아가 먼저 건네는 말.

    사이가 깊어질수록 먼저 거는 말의 온도가 달라진다.
    원수 단계에서는 먼저 말을 걸지 않는다.
    """

    try:

        import random

        from ai_brain import extract_cues
        from memory_manager import (
            append_message,
            load_relationship,
        )

        saved = load_relationship() or {}

        affinity = saved.get(
            "affinity",
            AVATAR.relationship.get("start_affinity", 0)
        )

        stage = _stage_now(
            affinity,
            saved.get("stage")
        )

        # 사귀자고 먼저 꺼낸다.
        #
        # 호감이 충분히 쌓였는데 상대가 아무 말이 없으면, 마냥 기다리지
        # 않는다. 한 번 말해 본다 — 기다리기만 하는 것은 자율사고가
        # 아니다. 받아들이는 것은 상대 몫이라 여기서 연인이 되지는 않는다.
        #
        # 한 번만 묻는다(asked_lover). 물을 때마다 조르면 사람이 아니라
        # 알림이 된다.
        if (not saved.get("lover")
                and AVATAR.confess_asks(affinity, AVATAR.gate_grants(saved))
                and not saved.get("asked_lover")):

            ask = AVATAR.confess_ask()

            if ask.get("line"):
                d = memory_manager.load_memory_data()
                d["relationship"] = dict(d.get("relationship") or {},
                                         asked_lover=True)
                memory_manager.save_memory_data(d)

                try:
                    append_message("assistant", ask["line"])
                except Exception as e:
                    print(f"[고백 묻기 저장 오류]: {e}")

                print("[고백]: 먼저 말했습니다.")

                return jsonify({
                    "speak": True,
                    "reply": ask["line"],
                    "expression": ask.get("expression") or "fluster",
                    "motion": ask.get("motion"),
                    "cues": [],
                    "stage": stage.key,
                    "label": _stage_label(stage),
                })

        # 대답이 없어도 말을 멈추지 않는 단계에서는 정해둔 문장을 쓰지 않는다.
        # 그때그때 생각해서 말한다. 그래야 "안녕" 에 답이 없을 때
        # "안녕이라고 했는데 왜 대답 안 해?" 가 나온다.
        if getattr(stage, "keeps_talking", False):

            from ai_brain import keep_talking

            live = keep_talking()

            if live:
                return jsonify(
                    {
                        "speak": True,
                        "reply": live["reply"],
                        "cues": live["cues"],
                        "expression": live["expression"],
                        "unanswered": live["unanswered"],
                        "keeps_talking": True,
                        "stage": stage.key,
                        "label": _stage_label(stage),
                        "affinity": affinity,
                    }
                )

            # 모델을 못 불렀으면 아래로 내려가 정해둔 문장을 쓴다.
            print("[먼저 말걸기]: 스스로 만들지 못해 정해둔 문장으로 넘어갑니다.")

        lines = stage.first_talk or []

        if not lines:
            return jsonify(
                {
                    "speak": False,
                    "stage": stage.key,
                    "label": _stage_label(stage),
                }
            )

        raw = random.choice(lines)

        # 먼저 거는 말도 대화 흐름에 남아야 다음 답이 이어진다
        reply, cues = extract_cues(raw)

        try:
            append_message("assistant", reply)
        except Exception as e:
            print(f"[먼저 말걸기 저장 오류]: {e}")

        _moved = _apply_wear(_apply_place({"cues": cues}))

        return jsonify(
            {
                "speak": True,
                "reply": reply,
                "cues": _moved.get("cues", cues),
                "place": _moved.get("place"),
                "wear": _moved.get("wear"),
                "expression": AVATAR.detect_expression(reply),
                "stage": stage.key,
                "label": _stage_label(stage),
                "affinity": affinity,
            }
        )

    except Exception as e:

        print(
            f"[먼저 말걸기 오류]: {e}"
        )

        return jsonify(
            {
                "speak": False,
                "error":
                "먼저 건넬 말을 만들지 못했습니다."
            }
        ), 500


# ============================================================
# 호감도 되돌리기
#
# 시험하다 보면 사이가 한쪽으로 치우친 채 굳는다. 기억은 그대로 두고
# 사이만 처음으로 돌리고 싶을 때가 있어서 따로 뒀다.
# ('/새 기억'은 기억까지 통째로 치운다. 이건 사이만 건드린다.)
# ============================================================

# ==================================================================
# 눈
#
# 카메라나 사진을 그림 보는 모델에게 보내 '무엇이 보이는지' 를 받고,
# 그것을 읽고 무슨 말을 할지는 다이아가 정한다.
#
# 둘을 나눈 이유: 그림 보는 모델은 다이아가 아니다. 그 모델이 직접
# 답하면 말투도, 사이도, 기억도 모르는 다른 사람이 답하게 된다.
# ==================================================================

def _describe(image_b64, prompt=None):
    """그림에 무엇이 보이는지 받아 온다. 못 보면 None.

    prompt 를 주면 그것으로 묻는다. 방을 읽을 때는 색과 밝기를
    숫자로 달라고 따로 물어야 해서 이 자리가 필요하다.
    """

    import requests
    from config import OLLAMA_URL, VISION_ENABLED, VISION_MODEL

    if not VISION_ENABLED:
        return None

    conf = AVATAR.vision or {}
    if not conf.get("enabled", True):
        return None

    prompt = prompt or conf.get("look_prompt")         or "이 사진에 무엇이 보이는지 한국어로 적어라."

    r = requests.post(OLLAMA_URL, json={
        "model": VISION_MODEL,
        "messages": [{
            "role": "user",
            "content": prompt,
            "images": [image_b64],
        }],
        "stream": False,
        # 눈은 생각하지 않는다. 보이는 것만 적으면 된다.
        "think": False,
    }, timeout=180)

    if r.status_code != 200:
        print(f"[눈]: HTTP {r.status_code}")
        return None

    seen = ((r.json().get("message") or {}).get("content") or "").strip()
    return seen or None


# ============================================================
# 방 읽기
#
# 사진 한 장을 보고 그 곳의 색과 밝기를 숫자로 받아 온다.
# 화면은 그 값으로 진짜 3D 방을 짓는다 — 카메라 영상을 배경에
# 붙이는 것과는 다르다. 방이 생기면 카메라를 꺼도 남고,
# 걸어 다니면 벽이 지나가고 발밑에 그림자가 진다.
#
# 모델은 글로 답하려 든다. 그래서 틀을 정해 주고 그 틀만 읽는다.
# 한 줄이라도 못 읽으면 그 줄만 기본값으로 채운다.
# ============================================================

def _parse_room(text, fallback):
    import re as _re

    out = dict(fallback)
    if not text:
        return out

    def hex_of(line):
        m = _re.search(r"#([0-9a-fA-F]{6})", line)
        return "#" + m.group(1).lower() if m else None

    for raw in str(text).splitlines():
        line = raw.strip()
        if not line:
            continue

        if line.startswith("벽"):
            v = hex_of(line)
            if v:
                out["wall"] = v
        elif line.startswith("바닥"):
            v = hex_of(line)
            if v:
                out["floor"] = v
        elif line.startswith("빛색"):
            v = hex_of(line)
            if v:
                out["light"] = v
        elif line.startswith("밝기"):
            m = _re.search(r"(\d{1,3})", line)
            if m:
                out["bright"] = max(0, min(100, int(m.group(1))))
        elif line.startswith("실내"):
            out["indoor"] = ("아니" not in line)
        elif line.startswith("이름"):
            v = line.split(":", 1)[-1].strip()
            v = v.strip("#*· ").strip()
            if 1 <= len(v) <= 8:
                out["name"] = v

    return out


@app.route("/api/room", methods=["POST"])
def room_api():

    try:
        data = request.get_json(silent=True) or {}
        image = data.get("image")

        conf = AVATAR.vision or {}
        fallback = conf.get("room_fallback", {})

        if not image or not isinstance(image, str):
            return jsonify({"ok": False, "error": "그림이 없습니다"}), 400

        if "," in image[:64] and image[:5] == "data:":
            image = image.split(",", 1)[1]

        seen = _describe(image, prompt=conf.get("room_prompt"))

        if not seen:
            return jsonify(
                {"ok": True, "room": dict(fallback), "read": False,
                 "why": "못 읽어서 기본값으로 지었습니다"}
            )

        print(f"[방 읽기]:\n{seen}")
        room = _parse_room(seen, fallback)
        print(f"[방]: {room}")

        return jsonify({"ok": True, "room": room, "read": True, "raw": seen})

    except Exception as e:
        print(f"[방 읽기 오류]: {e}")
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route(
    "/api/see",
    methods=["POST"]
)
def see_api():
    """사진 한 장을 보여 준다.

    받는 값:
      image   : base64 (앞의 data:...;base64, 는 떼고 보낸다)
      message : 같이 적어 보낸 말. 없으면 그냥 보여 준 것이다
      speak   : 말을 시킬 것인가. 카메라가 혼자 볼 때는 False 로 보낸다

    speak 가 False 면 본 것만 돌려주고 모델을 부르지 않는다.
    20초마다 한 번씩 말을 걸면 혼자 떠드는 사람이 된다.
    """

    try:
        from ai_brain import process_chat

        data = request.get_json(silent=True) or {}
        image = data.get("image")

        if not image or not isinstance(image, str):
            return jsonify({"ok": False, "error": "그림이 없습니다"}), 400

        # 앞머리가 붙어 와도 받아 준다
        if "," in image[:64] and image[:5] == "data:":
            image = image.split(",", 1)[1]

        seen = _describe(image)

        if not seen:
            return jsonify({"ok": False, "error": "보지 못했습니다"}), 502

        print(f"[눈]: {seen}")

        if not data.get("speak", True):
            # 보기만 한다. 무슨 말을 할지는 다음에 말을 걸 때 정한다.
            return jsonify({"ok": True, "seen": seen, "spoke": False})

        said = (data.get("message") or "").strip()
        if not said:
            # 말 없이 보여 주기만 했다. 그것도 하나의 말이다.
            said = "(사진을 보여 준다)"

        out = process_chat(said, seeing=seen)
        out["ok"] = True
        out["seen"] = seen
        out["spoke"] = True
        return jsonify(out)

    except Exception as e:
        print(f"[눈 오류]: {e}")
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route(
    "/api/relationship/reset",
    methods=["POST"]
)
def relationship_reset_api():

    try:

        from memory_manager import load_relationship, save_relationship

        data = request.get_json(silent=True) or {}

        start = AVATAR.relationship.get("start_affinity", 0)

        # 숫자를 적어 보내면 그 값으로 맞춘다. 안 적으면 시작 지점이다.
        want = data.get("affinity")
        target = start if want is None else int(want)
        target = AVATAR.clamp_affinity(target)

        before = load_relationship() or {}
        stage = _stage_now(target, None)

        # 사이를 처음으로 돌리면 연인이었던 것도 없던 일이 된다
        save_relationship(target, stage.key, 0, False)

        print(f"[호감도 되돌리기]: {before.get('affinity')} -> {target} "
              f"({stage.label})")

        return jsonify(
            {
                "ok": True,
                "affinity": target,
                "stage": stage.key,
                "stage_label": _stage_label(stage),
                "before": before.get("affinity"),
                "before_stage": before.get("stage"),
                "start": start,
            }
        )

    except Exception as e:

        print(f"[호감도 되돌리기 오류]: {e}")

        return jsonify(
            {
                "ok": False,
                "error": "호감도를 되돌리지 못했습니다."
            }
        ), 500


# ============================================================
# 옷 벗기기
#
# 옷을 두 번 누르면 벗는다. 두 번 더 누르면 다시 입는다.
# 그 옷을 만져도 되는 사이여야 한다 — 옷 자리의 allow_from 을 쓴다.
# ============================================================

@app.route("/api/undress", methods=["POST"])
def undress_api():

    try:
        from memory_manager import load_relationship

        conf = AVATAR.touch.get("undress", {})

        if not conf.get("enabled"):
            return jsonify({"ok": False, "error": "꺼져 있습니다."}), 200

        data = request.get_json(silent=True) or {}
        zone_key = str(data.get("zone") or "")
        wearing = bool(data.get("wearing", True))

        if zone_key not in (conf.get("zones") or []):
            return jsonify({"ok": False, "error": "벗길 수 없는 자리입니다."}), 200

        saved = load_relationship() or {}
        affinity = saved.get(
            "affinity", AVATAR.relationship.get("start_affinity", 0))
        stage = _stage_now(affinity, saved.get("stage"))

        zone = AVATAR.touch_zone(zone_key)
        need = (zone.allow_from if zone and zone.allow_from is not None else 0)

        if affinity < need:
            return jsonify(
                {
                    "ok": False,
                    "allowed": False,
                    "reply": "그건… 아직 안 돼요." if
                             str(stage.speech).startswith("존댓말")
                             else "그건… 아직 안 돼.",
                    "expression": "angry",
                    "need": need,
                }
            )

        import random as _r

        polite = str(stage.speech).startswith("존댓말")
        tone = "polite" if polite else "casual"
        which = "off" if wearing else "on"

        pool = (conf.get("lines", {}).get(which, {}) or {}).get(tone) or []

        return jsonify(
            {
                "ok": True,
                "allowed": True,
                "zone": zone_key,
                # 벗겼는가 입혔는가
                "off": wearing,
                "reply": _r.choice(pool) if pool else "",
                "expression": conf.get("off_expression" if wearing
                                       else "on_expression", "surprised"),
            }
        )

    except Exception as e:
        print(f"[옷 벗기기 오류]: {e}")
        return jsonify({"ok": False, "error": "하지 못했습니다."}), 500


# ============================================================
# 목소리
#
# 소리를 어디서 만들지는 config 가 정한다.
#
#   browser — 화면이 브라우저 목소리로 직접 읽는다. 여기서는 설정만 준다.
#   gemini  — 서버가 만들어 소리 자체를 내려보낸다. API 키가 필요하다.
#
# 화면은 /api/tts/config 로 어느 쪽인지 물어보고,
# gemini 면 /api/tts 로 문장을 보내 소리를 받아 간다.
# ============================================================

@app.route("/api/tts/config")
def tts_config_api():

    from config import (
        TTS_ENABLED, TTS_PROVIDER, TTS_VOICE,
        TTS_API_KEY, TTS_RATE, TTS_PITCH,
    )

    # 쓸 수 없는 것을 적어 두었으면 브라우저로 내려간다.
    # 그래야 말은 어쨌든 나온다.
    provider = TTS_PROVIDER

    if provider == "gemini" and not TTS_API_KEY:
        provider = "browser"

    if provider == "edge":
        try:
            import edge_tts  # noqa: F401
        except ImportError:
            print("[목소리] edge-tts 가 없어 브라우저 목소리로 갑니다. "
                  "pip install edge-tts")
            provider = "browser"

    voice = TTS_VOICE
    if provider == "edge":
        from config import TTS_EDGE_VOICE
        voice = TTS_EDGE_VOICE

    return jsonify(
        {
            "enabled": bool(TTS_ENABLED),
            "provider": provider,
            "voice": voice,
            "rate": TTS_RATE,
            "pitch": TTS_PITCH,
            # 브라우저에서 고를 한국어 목소리의 실마리
            "lang": "ko-KR",
        }
    )


# ------------------------------------------------------------
# 만든 소리를 떠 둔다
#
# 같은 말을 또 만들 이유가 없다. 그리고 gemini 는 **분당 몇 번**밖에
# 못 부른다 — 연달아 부르면 429 로 막히고, 그때마다 화면이 브라우저
# 기본 목소리(기계음)로 내려간다. 실제로 여덟 번 중 일곱 번이 막혔다.
#
# 먼저 말 걸기가 특히 그랬다. 그 말들은 정해진 문장 풀에서 나오는데
# 매번 새로 만들고 있었다. 떠 두면 두 번째부터는 아예 부르지 않는다.
#
# 올린 데서는 파일을 쓸 수 없다. 그때는 조용히 지나간다 —
# 못 떠 두는 것뿐이지 소리가 안 나는 것은 아니다.
# ------------------------------------------------------------

_VOICE_CACHE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "_voice_cache")


def _voice_cache_path(*bits):
    """무엇으로 만든 소리인지까지 열쇠에 넣는다.

    목소리나 말투를 바꾸면 떠 둔 것이 안 맞으므로, 그 값들도 같이
    섞어야 한다. 안 그러면 바꾼 뒤에도 옛 소리가 나온다.
    """
    import hashlib

    key = hashlib.sha1("\u0000".join(str(b) for b in bits)
                       .encode("utf-8")).hexdigest()

    return os.path.join(_VOICE_CACHE, key + ".json")


def _voice_cache_get(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _voice_cache_put(path, payload):
    try:
        os.makedirs(_VOICE_CACHE, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f)
    except OSError:
        # 올린 데서는 못 쓴다. 그래도 소리는 이미 만들어졌다.
        pass


def _tts_edge(text):
    """Edge 의 읽어주기 목소리. mp3 로 바로 온다. 실패하면 None."""
    try:
        import asyncio
        import base64

        import edge_tts

        from config import TTS_EDGE_VOICE, TTS_EDGE_RATE, TTS_EDGE_PITCH

        async def make():
            c = edge_tts.Communicate(
                text,
                TTS_EDGE_VOICE,
                rate=TTS_EDGE_RATE,
                pitch=TTS_EDGE_PITCH,
            )
            buf = b""
            async for chunk in c.stream():
                if chunk["type"] == "audio":
                    buf += chunk["data"]
            return buf

        audio = asyncio.run(make())

        if not audio:
            raise RuntimeError("소리가 비었다")

        return {
            "ok": True,
            "provider": "edge",
            "voice": TTS_EDGE_VOICE,
            "mime": "audio/mpeg",
            "audio": base64.b64encode(audio).decode("ascii"),
        }

    except Exception as e:
        print(f"[목소리 오류 - edge]: {e}")
        return None


def _tts_gemini(text):
    """Gemini 목소리(아케르나르). 막히거나 실패하면 None."""
    from config import TTS_API_KEY, TTS_MODEL, TTS_STYLE, TTS_VOICE

    try:
        import requests as _rq

        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{TTS_MODEL}:generateContent"
        )

        body = {
            "contents": [{
                "parts": [{"text": f"{TTS_STYLE}: {text}"}]
            }],
            "generationConfig": {
                "responseModalities": ["AUDIO"],
                "speechConfig": {
                    "voiceConfig": {
                        "prebuiltVoiceConfig": {"voiceName": TTS_VOICE}
                    }
                },
            },
        }

        res = _rq.post(
            url,
            json=body,
            headers={"x-goog-api-key": TTS_API_KEY},
            timeout=30,
        )

        if res.status_code != 200:
            # 429 는 분당 할당량이다. 잘못된 것이 아니라 너무 자주 부른 것이다.
            how = ("분당 할당량을 넘었습니다"
                   if res.status_code == 429 else res.text[:120])
            print(f"[목소리]: gemini HTTP {res.status_code} — {how}")
            return None

        part = res.json()["candidates"][0]["content"]["parts"][0]

        return {
            "ok": True,
            "provider": "gemini",
            "voice": TTS_VOICE,
            "mime": part["inlineData"].get("mimeType", "audio/L16;rate=24000"),
            "audio": part["inlineData"]["data"],
        }

    except Exception as e:
        print(f"[목소리 오류 - gemini]: {e}")
        return None


@app.route("/api/tts", methods=["POST"])
def tts_api():

    from config import TTS_ENABLED, TTS_PROVIDER, TTS_VOICE, TTS_API_KEY

    if not TTS_ENABLED:
        return jsonify({"ok": False, "error": "목소리가 꺼져 있습니다."}), 400

    data = request.get_json(silent=True) or {}
    text = str(data.get("text") or "").strip()

    if not text:
        return jsonify({"ok": False, "error": "읽을 말이 없습니다."}), 400

    # 떠 둔 것이 있으면 그것을 쓴다. 부르지도 않고 기다리지도 않는다.
    from config import TTS_EDGE_VOICE, TTS_STYLE

    path = _voice_cache_path(TTS_PROVIDER, TTS_VOICE, TTS_EDGE_VOICE,
                             TTS_STYLE, text)

    got = _voice_cache_get(path)

    if got:
        got["cached"] = True
        return jsonify(got)

    out = None

    # ------------------------------------------------------------
    # 정해진 목소리 하나만 쓴다. 내려가지 않는다.
    #
    # 예전에는 막히면 edge 로, 그것도 안 되면 브라우저 기계음으로
    # 내려갔다. **그 예비가 실패를 가렸다** — 소리가 나긴 나니까
    # 어디가 안 되는지 알 수가 없었다.
    #
    # 이제는 안 되면 안 되는 대로 둔다. 조용하고, 왜 그런지 적힌다.
    # 되돌리려면 config 의 TTS_PROVIDER 를 "edge" 로 두면 된다.
    # ------------------------------------------------------------
    if TTS_PROVIDER == "gemini" and TTS_API_KEY:
        out = _tts_gemini(text)
        why = "gemini 가 소리를 못 만들었습니다 (할당량이거나 오류)"

    elif TTS_PROVIDER == "edge":
        out = _tts_edge(text)
        why = "edge 가 소리를 못 만들었습니다"

    else:
        out = None
        why = f"쓸 수 있는 목소리가 없습니다 (provider={TTS_PROVIDER})"

    if out is None:
        print(f"[목소리]: {why} — 이번 말은 조용히 넘어갑니다.")
        return jsonify({"ok": False, "error": why}), 200

    _voice_cache_put(path, out)

    return jsonify(out)


# ============================================================
# 장기
#
# 규칙과 둘 수는 janggi.py, 무슨 말을 할지는 개체(AVATAR).
# 여기는 그 둘을 잇고 판을 기억해 둔다.
# ============================================================

def _jg_load():
    g = memory_manager.load_memory_data().get("janggi")

    if not isinstance(g, dict) or not g.get("board"):
        return None

    return g


def _jg_save(board, level=None):
    data = memory_manager.load_memory_data()
    before = data.get("janggi") or {}

    data["janggi"] = {
        "board": board,
        "level": level or before.get("level")
                 or AVATAR.jg_level().get("key", "normal"),
    }

    memory_manager.save_memory_data(data)


def _jg_clear():
    data = memory_manager.load_memory_data()
    data["janggi"] = {}
    memory_manager.save_memory_data(data)


def _jg_out(board, say=None, extra=None):
    import janggi as JG

    out = JG.view(board, AVATAR.jg_side()) if board else {"open": False}
    out["ok"] = True
    out["levels"] = AVATAR.jg_levels()
    out["level"] = (_jg_load() or {}).get(
        "level", AVATAR.jg_level().get("key", "normal"))

    if say:
        out["reply"] = say.get("line")
        out["expression"] = say.get("expression")
        out["motion"] = say.get("motion")

    if extra:
        out.update(extra)

    return out


@app.route("/api/janggi/state")
def janggi_state_api():
    g = _jg_load()

    if not g:
        return jsonify({"ok": True, "open": False,
                        "levels": AVATAR.jg_levels()})

    out = _jg_out(g["board"])
    out["open"] = True

    return jsonify(out)


@app.route("/api/janggi/new", methods=["POST"])
def janggi_new_api():
    import janggi as JG

    try:
        data = request.get_json(silent=True) or {}
        board = JG.new_board()
        _jg_save(board, data.get("level"))

        print("[장기]: 판을 펼쳤습니다.")

        say = AVATAR.jg_say("open", _go_stage())
        out = _jg_out(board, say)
        out["open"] = True

        return jsonify(out)

    except Exception as e:
        print(f"[장기 새 판 오류]: {e}")
        return jsonify({"ok": False, "error": str(e)[:120]}), 500


@app.route("/api/janggi/moves")
def janggi_moves_api():
    """이 말이 갈 수 있는 곳. 화면이 짚어 준다."""
    import janggi as JG

    try:
        g = _jg_load()

        if not g:
            return jsonify({"ok": False, "error": "판이 없습니다."}), 400

        i = request.args.get("from", type=int)
        board = g["board"]

        if i is None or not (0 <= i < len(board)) or board[i] == JG.EMPTY:
            return jsonify({"ok": True, "moves": []})

        you = JG.other(AVATAR.jg_side())

        if JG.side_of(board[i]) != you:
            return jsonify({"ok": True, "moves": []})

        # 두고 나서 내 궁이 잡히는 수는 빼고 준다
        legal = [t for f, t in JG.legal_moves(board, you) if f == i]

        return jsonify({"ok": True, "moves": legal})

    except Exception as e:
        print(f"[장기 갈 곳 오류]: {e}")
        return jsonify({"ok": False, "error": str(e)[:120]}), 500


@app.route("/api/janggi/move", methods=["POST"])
def janggi_move_api():
    import janggi as JG

    try:
        g = _jg_load()

        if not g:
            return jsonify({"ok": False, "error": "판이 없습니다."}), 400

        board = g["board"]
        data = request.get_json(silent=True) or {}
        frm = data.get("from")
        to = data.get("to")

        you = JG.other(AVATAR.jg_side())
        mine = AVATAR.jg_side()

        if (frm, to) not in JG.legal_moves(board, you):
            return jsonify({"ok": False, "error": "그렇게는 못 둡니다."}), 400

        board = JG.move(board, frm, to)

        # 사람이 이겼는가
        end = JG.outcome(board, mine)

        if end == "mate":
            _jg_clear()
            say = AVATAR.jg_say("lost", _go_stage())
            _go_bump(say.get("affinity", 0))
            print("[장기]: 사람이 이겼습니다.")

            return jsonify(_jg_out(board, say, {"open": False, "winner": "you"}))

        if end == "stalemate":
            _jg_clear()
            say = AVATAR.jg_say("draw", _go_stage())

            return jsonify(_jg_out(board, say, {"open": False}))

        # 다이아가 받는다
        rel = memory_manager.load_relationship() or {}
        level = g.get("level") or AVATAR.jg_level().get("key", "normal")

        checked = JG.in_check(board, mine)

        pick = JG.choose(board, mine, level,
                         mercy=AVATAR.jg_mercy(rel.get("affinity", 0)))

        if pick is None:
            _jg_clear()
            say = AVATAR.jg_say("draw", _go_stage())

            return jsonify(_jg_out(board, say, {"open": False}))

        took = board[pick[1]]
        board = JG.move(board, *pick)
        spot = JG.name(pick[1])

        end = JG.outcome(board, you)

        if end == "mate":
            _jg_clear()
            say = AVATAR.jg_say("won", _go_stage(), spot=spot)
            _go_bump(say.get("affinity", 0))
            print(f"[장기]: 다이아가 이겼습니다 ({spot}).")

            return jsonify(_jg_out(board, say, {"open": False, "winner": "dia"}))

        _jg_save(board, g.get("level"))

        # 무슨 말을 할지 — 장군 > 잡음 > 장군 맞고 피함 > 그냥 한 수
        if JG.in_check(board, you):
            kind, fmt = "check", {}
        elif took != JG.EMPTY:
            kind, fmt = "take", {"piece": JG.KO.get(took.upper(), "말")}
        elif checked:
            kind, fmt = "checked", {}
        else:
            kind, fmt = "move", {}

        say = AVATAR.jg_say(kind, _go_stage(), spot=spot, **fmt)

        out = _jg_out(board, say, {"open": True, "spot": pick[1],
                                   "from": pick[0]})

        return jsonify(out)

    except Exception as e:
        print(f"[장기 두기 오류]: {e}")
        return jsonify({"ok": False, "error": str(e)[:120]}), 500


@app.route("/api/janggi/level", methods=["POST"])
def janggi_level_api():
    try:
        data = request.get_json(silent=True) or {}
        want = str(data.get("level") or "").strip()

        if want not in [l.get("key") for l in AVATAR.jg_levels()]:
            return jsonify({"ok": False, "error": "그런 세기가 없습니다."}), 400

        g = _jg_load()

        if g:
            _jg_save(g["board"], want)

        return jsonify({"ok": True, "level": want})

    except Exception as e:
        print(f"[장기 세기 오류]: {e}")
        return jsonify({"ok": False, "error": str(e)[:120]}), 500


@app.route("/api/janggi/resign", methods=["POST"])
def janggi_resign_api():
    try:
        _jg_clear()
        say = AVATAR.jg_say("resign", _go_stage())
        _go_bump(say.get("affinity", 0))

        return jsonify(_jg_out(None, say, {"open": False}))

    except Exception as e:
        print(f"[장기 그만 오류]: {e}")
        return jsonify({"ok": False, "error": str(e)[:120]}), 500


# ============================================================
# 할리갈리
#
# 규칙과 반응 속도는 halli.py, 무슨 말을 할지는 개체(AVATAR).
#
# 이 놀이는 **누가 먼저 손을 대는가** 가 전부다. 그래서 뒤집을 때마다
# 다이아가 종을 치기까지 걸릴 시간을 굴려서 화면에 같이 보낸다.
# 화면이 그 시간만큼 기다렸다가, 사람이 먼저 안 눌렀으면 다이아가
# 친 것으로 알린다.
#
# 시간을 화면에 알려 주는 것이 꺼림칙할 수 있지만, 혼자 하는 놀이라
# 속일 사람이 없다. 서버에서 재려면 타이머를 돌려야 하는데 그건
# 훨씬 무겁다.
# ============================================================

def _hg_load():
    g = memory_manager.load_memory_data().get("halli")

    if not isinstance(g, dict) or not g.get("on"):
        return None

    return g


def _hg_save(game):
    data = memory_manager.load_memory_data()
    data["halli"] = game or {}
    memory_manager.save_memory_data(data)


def _hg_clear():
    _hg_save({})


def _hg_say(kind, **fmt):
    """할 말 한 벌. 호감도 같이 옮긴다."""
    say = AVATAR.hg_say(kind, _go_stage(), **fmt)

    if say.get("affinity"):
        _go_bump(say["affinity"])

    return say


def _hg_out(game, say=None, extra=None):
    import halli as HG

    out = HG.view(game) if game else {"on": False}
    out["ok"] = True
    out["levels"] = AVATAR.hg_levels()

    if say:
        out["reply"] = say.get("line")
        out["expression"] = say.get("expression")
        out["motion"] = say.get("motion")

    if extra:
        out.update(extra)

    return out


@app.route("/api/halli/state")
def halli_state_api():
    g = _hg_load()

    if not g:
        return jsonify({"ok": True, "on": False,
                        "levels": AVATAR.hg_levels()})

    return jsonify(_hg_out(g))


@app.route("/api/halli/new", methods=["POST"])
def halli_new_api():
    import halli as HG

    try:
        data = request.get_json(silent=True) or {}
        level = data.get("level") or AVATAR.hg_level().get("key", "normal")

        g = HG.new_game(level=level)
        _hg_save(g)

        print("[할리갈리]: 판을 열었습니다.")

        return jsonify(_hg_out(g, _hg_say("open")))

    except Exception as e:
        print(f"[할리갈리 새 판 오류]: {e}")
        return jsonify({"ok": False, "error": str(e)[:120]}), 500


@app.route("/api/halli/flip", methods=["POST"])
def halli_flip_api():
    """한 장 뒤집는다. 차례인 쪽이 뒤집는다."""
    import halli as HG
    import random as _rnd

    try:
        g = _hg_load()

        if not g:
            return jsonify({"ok": False, "error": "판이 없습니다."}), 400

        who = g.get("turn") or "you"

        if not HG.flip(g, who):
            # 뒤집을 것이 없다. 진 것이다.
            _hg_clear()
            lost = (who == "dia")
            say = _hg_say("lost" if lost else "won")

            return jsonify(_hg_out(None, say, {"winner": "you" if lost else "dia"}))

        # 종 칠 때인가. 다이아가 얼마나 빨리 칠지 굴린다.
        fruit = HG.should_ring(g)
        rel = memory_manager.load_relationship() or {}
        mercy = AVATAR.hg_mercy(rel.get("affinity", 0))
        level = g.get("level") or "normal"

        g["ring"] = bool(fruit)
        g["dia_ms"] = None
        g["dia_wrong"] = False

        if fruit:
            ms, wrong = HG.roll_reaction(level, mercy)
            g["dia_ms"] = ms
            g["dia_wrong"] = False          # 맞는 자리라 잘못이 아니다
        else:
            # 아닌데 치는 것도 있다. 한 번도 안 틀리는 상대는
            # 사람 같지 않고, 사람에게 카드를 줄 기회도 안 생긴다.
            conf = HG.LEVELS.get(level) or HG.LEVELS["normal"]

            if _rnd.random() < conf["wrong"]:
                g["dia_ms"] = HG.wrong_ring_delay(level)
                g["dia_wrong"] = True

        _hg_save(g)

        return jsonify(_hg_out(g, None, {
            "flipped": who,
            "dia_ms": g["dia_ms"],
        }))

    except Exception as e:
        print(f"[할리갈리 뒤집기 오류]: {e}")
        return jsonify({"ok": False, "error": str(e)[:120]}), 500


@app.route("/api/halli/bell", methods=["POST"])
def halli_bell_api():
    """종을 쳤다. who 는 'you' 또는 'dia'."""
    import halli as HG

    try:
        g = _hg_load()

        if not g:
            return jsonify({"ok": False, "error": "판이 없습니다."}), 400

        data = request.get_json(silent=True) or {}
        who = "dia" if data.get("who") == "dia" else "you"
        ms = data.get("ms")

        fruit = HG.should_ring(g)

        # 사람이 쳤는데 다이아가 더 빨랐는가.
        #
        # 화면이 시간을 재서 보낸다. 다이아 쪽이 빠르면 다이아가
        # 친 것으로 넘긴다 — 화면 타이머와 사람 손이 거의 같이
        # 도착하는 자리라 여기서 한 번 더 가른다.
        if (who == "you" and isinstance(ms, (int, float))
                and g.get("dia_ms") and ms > g["dia_ms"]):
            who = "dia"

        if who == "dia":
            right = bool(fruit) and not g.get("dia_wrong")
        else:
            right = bool(fruit)

        if right:
            n = HG.take_pile(g, who)
            say = _hg_say("dia_ring" if who == "dia" else "you_ring",
                          fruit=HG.FRUIT_KO.get(fruit, ""), n=n)
        else:
            HG.penalty(g, who)
            say = _hg_say("dia_wrong" if who == "dia" else "you_wrong")

        g["ring"] = False
        g["dia_ms"] = None
        g["dia_wrong"] = False

        # 종을 친 쪽이 다음에 뒤집는다
        g["turn"] = who

        won = HG.winner(g)

        if won:
            _hg_clear()
            end = _hg_say("won" if won == "dia" else "lost")

            return jsonify(_hg_out(None, end, {"winner": won}))

        _hg_save(g)

        return jsonify(_hg_out(g, say, {"right": right, "rang": who}))

    except Exception as e:
        print(f"[할리갈리 종 오류]: {e}")
        return jsonify({"ok": False, "error": str(e)[:120]}), 500


@app.route("/api/halli/level", methods=["POST"])
def halli_level_api():
    try:
        data = request.get_json(silent=True) or {}
        want = str(data.get("level") or "").strip()

        if want not in [l.get("key") for l in AVATAR.hg_levels()]:
            return jsonify({"ok": False, "error": "그런 세기가 없습니다."}), 400

        g = _hg_load()

        if g:
            g["level"] = want
            _hg_save(g)

        return jsonify({"ok": True, "level": want})

    except Exception as e:
        print(f"[할리갈리 세기 오류]: {e}")
        return jsonify({"ok": False, "error": str(e)[:120]}), 500


@app.route("/api/halli/quit", methods=["POST"])
def halli_quit_api():
    try:
        _hg_clear()

        return jsonify(_hg_out(None, _hg_say("quit")))

    except Exception as e:
        print(f"[할리갈리 그만 오류]: {e}")
        return jsonify({"ok": False, "error": str(e)[:120]}), 500


# ============================================================
# 오목
#
# 규칙과 둘 자리는 gomoku.py, 무슨 말을 할지는 개체(AVATAR).
# 여기는 그 둘을 잇고 판을 기억해 둔다.
#
# 판은 사람마다 따로다. 체스와 같은 자리에 넣는다.
# ============================================================

def _go_load():
    """이 사람의 오목판. 없으면 None."""
    g = memory_manager.load_memory_data().get("gomoku")

    if not isinstance(g, dict) or not g.get("board"):
        return None

    return g


def _go_save(board, level=None):
    data = memory_manager.load_memory_data()
    before = data.get("gomoku") or {}

    data["gomoku"] = {
        "board": board,
        "level": level or before.get("level")
                 or AVATAR.go_level().get("key", "normal"),
    }

    memory_manager.save_memory_data(data)


def _go_clear():
    data = memory_manager.load_memory_data()
    data["gomoku"] = {}
    memory_manager.save_memory_data(data)


def _go_stage():
    """지금 어떤 사이인지. 말투를 가르는 데 쓴다."""
    rel = memory_manager.load_relationship() or {}
    grants = AVATAR.gate_grants(rel)

    return AVATAR.stage_for_affinity(rel.get("affinity", 0), grants)


def _go_bump(delta):
    """놀이로 얻는 것은 작게. 체스·가위바위보와 같은 자리."""
    if not delta:
        return

    rel = memory_manager.load_relationship() or {}
    grants = AVATAR.gate_grants(rel)

    aff = AVATAR.clamp_affinity(
        int(rel.get("affinity", 0)) + int(delta), grants=grants)

    st = AVATAR.stage_for_affinity(aff, grants)

    memory_manager.save_relationship(
        aff, st.key if st else rel.get("stage", "distant"))


def _go_view(board, event=None, spot=None):
    """화면에 돌려줄 것 한 벌."""
    import gomoku as GO

    out = GO.view(board, AVATAR.go_stone())
    out["ok"] = True
    out["level"] = (_go_load() or {}).get(
        "level", AVATAR.go_level().get("key", "normal"))
    out["levels"] = AVATAR.go_levels()

    if event:
        say = AVATAR.go_say(event, _go_stage(), spot=spot or "")
        out["reply"] = say.get("line")
        out["expression"] = say.get("expression")
        out["motion"] = say.get("motion")

    return out


@app.route("/api/gomoku/state")
def gomoku_state_api():
    import gomoku as GO

    g = _go_load()

    if not g:
        return jsonify({"ok": True, "open": False})

    out = _go_view(g["board"])
    out["open"] = True
    out["winner"] = GO.winner(g["board"])

    return jsonify(out)


@app.route("/api/gomoku/new", methods=["POST"])
def gomoku_new_api():
    import gomoku as GO

    try:
        data = request.get_json(silent=True) or {}
        level = data.get("level")

        board = GO.new_board()
        _go_save(board, level)

        print("[오목]: 판을 열었습니다.")

        out = _go_view(board, "open")
        out["open"] = True

        return jsonify(out)

    except Exception as e:
        print(f"[오목 새 판 오류]: {e}")
        return jsonify({"ok": False, "error": str(e)[:120]}), 500


@app.route("/api/gomoku/move", methods=["POST"])
def gomoku_move_api():
    """사람이 한 수 두고, 다이아가 받는다."""
    import gomoku as GO

    try:
        g = _go_load()

        if not g:
            return jsonify({"ok": False, "error": "판이 없습니다."}), 400

        board = g["board"]
        data = request.get_json(silent=True) or {}
        spot = data.get("spot")

        if not isinstance(spot, int) or not (0 <= spot < GO.SIZE * GO.SIZE):
            return jsonify({"ok": False, "error": "그런 자리가 없습니다."}), 400

        if board[spot] != GO.EMPTY:
            return jsonify({"ok": False, "error": "이미 돌이 있습니다."}), 400

        mine = AVATAR.go_stone()
        yours = GO.other(mine)

        r, c = divmod(spot, GO.SIZE)
        board = GO.put(board, r, c, yours)

        # 사람이 이겼는가
        if GO.winner_at(board, r, c) == yours:
            _go_clear()
            say = AVATAR.go_say("lost", _go_stage())
            _go_bump(say.get("affinity", 0))

            out = GO.view(board, mine)
            out.update({"ok": True, "open": False, "winner": yours,
                        "reply": say.get("line"),
                        "expression": say.get("expression"),
                        "motion": say.get("motion")})
            print("[오목]: 사람이 이겼습니다.")

            return jsonify(out)

        if GO.is_full(board):
            _go_clear()
            say = AVATAR.go_say("draw", _go_stage())
            out = GO.view(board, mine)
            out.update({"ok": True, "open": False, "winner": None,
                        "reply": say.get("line"),
                        "expression": say.get("expression")})

            return jsonify(out)

        # 다이아가 받는다
        rel = memory_manager.load_relationship() or {}
        level = g.get("level") or AVATAR.go_level().get("key", "normal")

        # 사람이 셋을 만들어 놓았는가 — 알아채면 그렇게 말한다
        before = GO.evaluate(board, mine)

        pick = GO.choose(board, mine, level,
                         mercy=AVATAR.go_mercy(rel.get("affinity", 0)))

        if pick is None:
            _go_clear()
            say = AVATAR.go_say("draw", _go_stage())
            out = GO.view(board, mine)
            out.update({"ok": True, "open": False, "reply": say.get("line")})

            return jsonify(out)

        rr, cc = divmod(pick, GO.SIZE)
        board = GO.put(board, rr, cc, mine)
        name = GO.name(pick)

        if GO.winner_at(board, rr, cc) == mine:
            _go_clear()
            say = AVATAR.go_say("won", _go_stage(), spot=name)
            _go_bump(say.get("affinity", 0))

            out = GO.view(board, mine)
            out.update({"ok": True, "open": False, "winner": mine,
                        "reply": say.get("line"),
                        "expression": say.get("expression"),
                        "motion": say.get("motion")})
            print(f"[오목]: 다이아가 이겼습니다 ({name}).")

            return jsonify(out)

        _go_save(board, g.get("level"))

        # 막느라 둔 수였으면 그렇게 말한다. 알아채는 것이 사람 같다.
        after = GO.evaluate(board, mine)
        kind = "threat" if (after - before) > 1500 else "move"

        out = _go_view(board, kind, name)
        out["open"] = True
        out["spot"] = pick

        return jsonify(out)

    except Exception as e:
        print(f"[오목 두기 오류]: {e}")
        return jsonify({"ok": False, "error": str(e)[:120]}), 500


@app.route("/api/gomoku/level", methods=["POST"])
def gomoku_level_api():
    try:
        data = request.get_json(silent=True) or {}
        want = str(data.get("level") or "").strip()

        keys = [l.get("key") for l in AVATAR.go_levels()]

        if want not in keys:
            return jsonify({"ok": False, "error": "그런 세기가 없습니다."}), 400

        g = _go_load()

        if g:
            _go_save(g["board"], want)

        return jsonify({"ok": True, "level": want})

    except Exception as e:
        print(f"[오목 세기 오류]: {e}")
        return jsonify({"ok": False, "error": str(e)[:120]}), 500


@app.route("/api/gomoku/resign", methods=["POST"])
def gomoku_resign_api():
    try:
        _go_clear()
        say = AVATAR.go_say("resign", _go_stage())
        _go_bump(say.get("affinity", 0))

        print("[오목]: 그만뒀습니다.")

        return jsonify({"ok": True, "open": False,
                        "reply": say.get("line"),
                        "expression": say.get("expression")})

    except Exception as e:
        print(f"[오목 그만 오류]: {e}")
        return jsonify({"ok": False, "error": str(e)[:120]}), 500


# ============================================================
# 배경 이미지
#
# static/background/ 를 훑어 쓸 수 있는 이미지를 알려준다.
# 파일을 넣고 화면만 새로 고치면 바뀌도록, 목록을 코드에 적지 않는다.
# ============================================================

@app.route("/api/wardrobe")
def wardrobe_api():
    """옷장에 무엇이 걸려 있는가.

    목록을 코드에 적지 않는다. 배경과 같은 이치다 —
    `_extract_garment.py` 로 옷을 구우면 wardrobe.json 에 한 줄이 늘고,
    화면을 새로 고치면 그 옷이 옷장에 걸린다. 서버를 껐다 켤 필요 없다.

    옷 하나는 '옷만 든 작은 VRM' 이다(교복 한 벌 1.4MB). 통짜 아바타를
    옷 수만큼 두면 한 벌에 16MB 다.
    """

    conf = (AVATAR.model or {}).get("wardrobe_dir", "static/wardrobe")
    base = os.path.join(os.path.dirname(os.path.abspath(__file__)), conf)
    book = os.path.join(base, "wardrobe.json")

    items = []

    try:
        with open(book, encoding="utf-8") as f:
            items = json.load(f).get("items", [])
    except FileNotFoundError:
        pass
    except Exception as e:
        print(f"[옷장 읽기 오류]: {e}")

    # 파일이 실제로 있는 것만 준다.
    # json 에는 남았는데 파일을 지운 경우, 화면에서 눌러도 404 만 난다.
    live = []

    for it in items:
        name = it.get("file") or ""
        if name and os.path.exists(os.path.join(base, name)):
            live.append(it)
        else:
            print(f"[옷장] 파일이 없어 건너뜀: {name}")

    # 지금 무엇을 입고 있는가.
    #
    # 세 가지가 다르다.
    #   적힌 옷 이름 → 그 옷을 입힌다
    #   빈 문자열    → 일부러 벗은 것이다. 그대로 둔다
    #   칸 자체가 없음 → 처음 온 사람이다. 기본 옷을 입힌다
    #
    # 마지막이 중요하다. 처음 열었을 때 벗고 있으면 안 된다.
    worn = memory_manager.load_wearing()
    keys = [it.get("key") for it in live]

    if worn is None:
        worn = keys[0] if keys else ""
    elif worn and worn not in keys:
        # 옷장에서 사라진 옷을 입고 있었다. 있는 것으로 갈아입힌다.
        print(f"[옷장] 입고 있던 '{worn}' 이 없어졌다")
        worn = keys[0] if keys else ""

    return jsonify({"ok": True, "items": live, "worn": worn})


@app.route("/api/wardrobe", methods=["POST"])
def wardrobe_wear_api():
    """무엇을 입었는지 적어 둔다. 창을 닫았다 열어도 그대로여야 한다.

    벗었으면 빈 문자열을 보낸다 — '벗고 있음' 과 '아직 안 정함' 은
    다르다. 뒤엣것은 처음 온 사람이라 기본 옷을 입힌다.
    """

    data = request.get_json(silent=True) or {}
    key = str(data.get("key") or "")

    memory_manager.save_wearing(key)
    print(f"[옷장] {'벗었습니다' if not key else key + ' 을(를) 입었습니다'}")

    return jsonify({"ok": True, "worn": key})


@app.route("/api/background")
def background_api():

    import os

    conf = (AVATAR.model or {}).get("background", {}) or {}

    folder = conf.get("dir", "static/background")
    prefix = conf.get("url_prefix", "/static/background/")
    types = tuple(
        t.lower() for t in conf.get(
            "types", [".png", ".jpg", ".jpeg", ".webp", ".gif"]
        )
    )

    base = os.path.join(os.path.dirname(os.path.abspath(__file__)), folder)

    try:
        names = sorted(
            f for f in os.listdir(base)
            if f.lower().endswith(types)
        )
    except FileNotFoundError:
        names = []
    except Exception as e:
        print(f"[배경 훑기 오류]: {e}")
        names = []

    from urllib.parse import quote

    images = [
        {"name": n, "url": prefix + quote(n)}
        for n in names
    ]

    # ------------------------------------------------------------
    # 장소별로 묶는다
    #
    # 파일 이름이 곧 장소 이름이다. 공원_낮.jpg 와 공원_밤.jpg 는
    # 둘 다 '공원' 이고, 그 곳으로 갈 때 그중 하나가 뽑힌다.
    #
    # 목록을 코드에 적지 않는 이유는 배경과 같다 — 파일을 넣고
    # 새로 고치면 갈 수 있는 곳이 늘어야 한다.
    # ------------------------------------------------------------
    places = {}

    for img in images:
        places.setdefault(AVATAR.place_of_file(img["name"]), []).append(img)

    # 어디서 시작하는가.
    #
    # 1. 지난번에 있던 곳이 있으면 거기다. 창을 닫았다 열었다고
    #    카페에서 갑자기 공원으로 옮겨지면 안 된다.
    # 2. 없으면 places.start 에 적힌 곳.
    # 3. 그것도 없으면 **아무 데도 아니다 — 배경을 안 깐다.**
    #
    # 예전에는 이름순 첫 번째를 깔았다. 그러면 창을 열자마자 어딘가에
    # 가 있는 셈이라, 이야기하다가 "공원 가자" 하는 것이 어색해진다.
    # 아무 데도 아닌 자리에서 시작해 둘이 정한 곳으로 가는 편이 맞다.
    here = None

    try:
        here = (memory_manager.load_memory_data().get("place") or {}).get("name")
    except Exception:
        here = None

    current = None

    if here and here in places:
        current = places[here][0]
    else:
        here = None

        start = AVATAR.places_conf().get("start")

        if start and start in places:
            current = places[start][0]
            here = start

    # 꼭 집어 쓰라고 적어 둔 파일이 있으면 그것이 이긴다.
    # 장소와 상관없이 늘 그 그림으로 시작하고 싶을 때만 쓴다.
    want = conf.get("prefer")

    if want:
        hit = next((i for i in images if i["name"] == want), None)
        if hit:
            current = hit
            here = AVATAR.place_of_file(hit["name"])
        else:
            print(f"[배경] prefer 로 적은 '{want}' 을(를) 못 찾았습니다.")

    return jsonify(
        {
            "images": images,
            "current": current,
            # {"공원": [...], "카페": [...]}
            "places": {k: v for k, v in sorted(places.items())},
            "place": here,
            # 폴더가 빈 것과 일부러 배경 없이 시작하는 것은 다르다.
            "empty": not images,
            "fit": conf.get("fit", "cover"),
            "dim": conf.get("dim", 0.0),
            "folder": folder,
        }
    )


def _places_now():
    """지금 갈 수 있는 곳 이름들. 배경 폴더를 그대로 훑는다."""
    conf = (AVATAR.model or {}).get("background", {}) or {}

    if not AVATAR.places_conf().get("enabled", True):
        return []

    folder = conf.get("dir", "static/background")
    types = tuple(t.lower() for t in conf.get(
        "types", [".png", ".jpg", ".jpeg", ".webp", ".gif"]))

    base = os.path.join(os.path.dirname(os.path.abspath(__file__)), folder)

    try:
        names = [f for f in os.listdir(base) if f.lower().endswith(types)]
    except OSError:
        return []

    out = []

    for n in names:
        p = AVATAR.place_of_file(n)
        if p and p not in out:
            out.append(p)

    return sorted(out)


def _place_here():
    """지금 있는 곳. 없으면 None."""
    try:
        return (memory_manager.load_memory_data().get("place") or {}).get("name")
    except Exception:
        return None


def _place_go(name):
    """그 곳으로 옮긴다. 갈 수 없는 곳이면 False.

    기억에 적어 두는 이유: 창을 닫았다 열어도 있던 자리가 남아야
    한다. 기분·체스판과 같은 자리다.
    """
    if not name or name not in _places_now():
        return False

    data = memory_manager.load_memory_data()
    data["place"] = {"name": name}
    memory_manager.save_memory_data(data)

    return True


def _place_image(name):
    """그 곳의 그림 하나. 여러 장이면 그때그때 하나 뽑는다."""
    import random as _rnd
    from urllib.parse import quote

    conf = (AVATAR.model or {}).get("background", {}) or {}
    prefix = conf.get("url_prefix", "/static/background/")
    folder = conf.get("dir", "static/background")
    types = tuple(t.lower() for t in conf.get(
        "types", [".png", ".jpg", ".jpeg", ".webp", ".gif"]))

    base = os.path.join(os.path.dirname(os.path.abspath(__file__)), folder)

    try:
        hits = [f for f in sorted(os.listdir(base))
                if f.lower().endswith(types)
                and AVATAR.place_of_file(f) == name]
    except OSError:
        hits = []

    if not hits:
        return None

    pick = _rnd.choice(hits)

    return {"name": pick, "url": prefix + quote(pick)}


def _wardrobe_items():
    """옷장에 실제로 걸려 있는 옷들. [{key,label,file,...}]"""
    conf = (AVATAR.model or {}).get("wardrobe_dir", "static/wardrobe")
    base = os.path.join(os.path.dirname(os.path.abspath(__file__)), conf)

    try:
        with open(os.path.join(base, "wardrobe.json"), encoding="utf-8") as f:
            items = json.load(f).get("items", [])
    except FileNotFoundError:
        return []
    except Exception as e:
        print(f"[옷장 읽기 오류]: {e}")
        return []

    return [it for it in items
            if it.get("file")
            and os.path.exists(os.path.join(base, it["file"]))]


def _wardrobe_now():
    """프롬프트에 적을 옷 목록."""
    return [{"key": it.get("key"), "label": it.get("label") or it.get("key")}
            for it in _wardrobe_items()]


def _worn_now():
    """지금 입고 있는 옷 이름. 벗었으면 None.

    처음 온 사람(칸이 없음)은 기본 옷을 입는 것으로 본다 —
    /api/wardrobe 가 그렇게 입히기 때문에 여기서도 같아야 한다.
    안 맞추면 프롬프트만 '벗고 있다' 고 알게 된다.
    """
    worn = memory_manager.load_wearing()
    keys = [it.get("key") for it in _wardrobe_items()]

    if worn is None:
        return keys[0] if keys else None

    return worn or None


def _apply_wear(result):
    """답에 (옷: 교복) 이 있으면 갈아입힌다.

    장소(_apply_place)와 같은 얼개다. 표시는 큐에서 걷어내고,
    화면이 받아 쓸 수 있게 result["wear"] 에 담아 준다.
    """
    cues = result.get("cues")

    if not isinstance(cues, list) or not cues:
        return result

    want = None
    keep = []

    for c in cues:
        if isinstance(c, dict) and c.get("type") == "wear":
            want = c.get("key")          # 마지막 것이 이긴다
            continue
        keep.append(c)

    if want is None:
        return result

    result["cues"] = keep

    here = _worn_now()
    keys = [it.get("key") for it in _wardrobe_items()]

    # 벗으라는 말
    if AVATAR.wear_is_off(want):
        if here is None:
            return result
        memory_manager.save_wearing("")
        result["wear"] = {"key": ""}
        print(f"[옷]: {here} -> 벗음")
        return result

    if want not in keys:
        print(f"[옷]: '{want}' 은(는) 옷장에 없습니다 — 그냥 둡니다.")
        return result

    if want == here:
        return result

    memory_manager.save_wearing(want)
    result["wear"] = {"key": want}
    print(f"[옷]: {here or '벗은 채'} -> {want}")

    return result


def _apply_place(result):
    """답에 섞인 장소 표시를 실제로 옮긴다.

    모델이 낸 것을 그대로 믿지 않는다. **갈 수 있는 곳인지 본다** —
    없는 곳을 적었으면 표시를 버린다. 그래야 말과 화면이 안 어긋난다.

    옮겼으면 result 에 place 를 붙인다. 화면은 그것만 보고 갈아 낀다.
    """
    if not isinstance(result, dict):
        return result

    cues = result.get("cues")

    if not isinstance(cues, list) or not cues:
        return result

    want = None
    keep = []

    for c in cues:
        if isinstance(c, dict) and c.get("type") == "place":
            want = c.get("key")          # 마지막 것이 이긴다
            continue
        keep.append(c)

    if want is None:
        return result

    result["cues"] = keep

    here = _place_here()

    if want == here:
        # 이미 그 곳이다. 옮길 것이 없다.
        return result

    if not _place_go(want):
        print(f"[장소]: '{want}' 은(는) 갈 수 없는 곳입니다 — 그냥 둡니다.")
        return result

    img = _place_image(want)
    result["place"] = {"name": want, "image": img}

    print(f"[장소]: {here or '처음'} -> {want}")

    return result


# ============================================================
# 테스트 전용 페이지
#
# 운영 화면(/)은 건드리지 않는다.
# 통합된 개체를 시험하는 자리는 여기로 분리한다.
# ============================================================

# ============================================================
# 체스
#
# 규칙은 python-chess, 무엇을 둘지는 chess_play, 무슨 말을 할지는
# 개체(AVATAR)가 정한다. 여기는 그 셋을 잇고 판을 기억해 둔다.
#
# 판은 사람마다 따로다. 기억과 같은 자리에 넣는다 — 그래야 계정이
# 갈리면 판도 같이 갈리고, 창을 닫았다 열어도 두던 판이 남는다.
# ============================================================

def _chess_load():
    """이 사람의 체스 상태. 아무것도 없으면 None.

    **판(fen)이 있어야만 돌려주면 안 된다.** 선공을 가위바위보로
    정하는 동안은 아직 판이 없고 `deciding` 만 있는데, 그때
    None 을 돌려주면 자기 상태를 못 읽어 "정하는 중이 아니다" 라고
    한다. 실제로 그랬다.

    판이 필요한 쪽은 _chess_board() 가 따로 본다.
    """

    g = memory_manager.load_memory_data().get("chess")

    if not isinstance(g, dict) or not g:
        return None

    return g


def _chess_save(board, dia_color, level=None):
    data = memory_manager.load_memory_data()

    before = data.get("chess") or {}

    data["chess"] = {
        "fen": board.fen(),
        "dia": "white" if dia_color else "black",
        "moves": [m.uci() for m in board.move_stack],
        # 난이도는 판과 함께 남는다. 안 적으면 창을 닫았다 열 때마다
        # 기본으로 돌아가 버린다.
        "level": level or before.get("level")
                 or AVATAR.chess().get("level", "normal"),
    }

    memory_manager.save_memory_data(data)


def _chess_level_key():
    """이 사람이 고른 난이도."""

    g = _chess_load() or {}

    return g.get("level") or AVATAR.chess().get("level", "normal")


def _chess_pick(board):
    """지금 난이도로 다이아가 둘 수를 고른다."""

    import chess_play

    lv = AVATAR.chess_level(_chess_level_key())

    return chess_play.choose(
        board,
        depth=int(lv.get("depth", 3)),
        blunder=float(lv.get("blunder", 0.0)),
        mercy=AVATAR.chess_mercy(
            memory_manager.load_relationship().get("affinity", 0)),
    )


def _chess_clear():
    data = memory_manager.load_memory_data()
    data["chess"] = {}
    memory_manager.save_memory_data(data)


def _chess_board():
    """저장해 둔 판을 되살린다. 반환: (board, dia_color) 또는 (None, None)."""

    import chess

    g = _chess_load()

    # 판이 있어야 되살린다. 선공을 정하는 중이면 아직 없다.
    if not g or not g.get("fen"):
        return None, None

    try:
        board = chess.Board(g["fen"])
    except ValueError as e:
        print("[체스판 되살리기 실패]:", e)
        return None, None

    return board, (chess.WHITE if g.get("dia") == "white" else chess.BLACK)


def _chess_reply(event, extra=None):
    """그 일에 대한 다이아의 말과 얼굴. 친밀도도 움직인다."""

    stage = _chess_stage()

    said = AVATAR.chess_say(event, stage) or {}

    if said.get("affinity"):
        _chess_bump(said["affinity"])

    # 한 말은 대화 기록에도 남긴다.
    #
    # 화면에만 띄우고 말면 판이 끝난 뒤 "아까 체스 재밌었어" 라고 해도
    # 무슨 말인지 모른다. 다이아가 한 말이 기록에 없으니 안 한 것이나
    # 같다. 놀이도 같이 보낸 시간이다.
    if said.get("line"):
        try:
            memory_manager.append_message("assistant", said["line"])
        except Exception as e:
            print("[체스 말 기록 실패]:", e)

    out = {
        "line": said.get("line"),
        "expression": said.get("expression"),
    }

    if extra:
        out.update(extra)

    return out


def _chess_stage():
    """지금 어떤 사이인지. 말투를 가르는 데 쓴다."""

    rel = memory_manager.load_relationship() or {}

    grants = AVATAR.gate_grants(rel)

    return AVATAR.stage_for_affinity(rel.get("affinity", 0), grants)


def _chess_bump(delta):
    """친밀도를 움직인다. 놀이로 얻는 것은 작게."""

    if not delta:
        return

    rel = memory_manager.load_relationship()

    aff = AVATAR.clamp_affinity(
        int(rel.get("affinity", 0)) + int(delta),
        lover=bool(rel.get("lover", False)),
        friends=bool(rel.get("friends", False)),
    )

    stage = AVATAR.stage_for_affinity(aff, AVATAR.gate_grants(rel))

    memory_manager.save_relationship(
        aff, stage.key if stage else rel.get("stage", "distant"))


def _chess_view(board, dia_color, event=None, extra=None):
    """화면에 돌려줄 것 한 벌."""

    import chess_play

    out = {"ok": True}
    out.update(chess_play.board_view(board, dia_color))

    out["level"] = _chess_level_key()
    out["levels"] = [
        {"key": lv.get("key"), "label": lv.get("label")}
        for lv in AVATAR.chess_levels()
    ]

    if event:
        out.update(_chess_reply(event, extra))
    elif extra:
        out.update(extra)

    return out


@app.route("/api/chess/state")
def chess_state_api():
    """두던 판이 있으면 그것을. 없으면 없다고."""

    board, dia_color = _chess_board()

    if board is None:
        return jsonify({"ok": True, "playing": False})

    view = _chess_view(board, dia_color)
    view["playing"] = True

    return jsonify(view)


@app.route("/api/chess/new", methods=["POST"])
def chess_new_api():
    """새 판을 연다."""

    import chess
    import chess_play

    data = request.get_json(silent=True) or {}

    # 사람이 어느 쪽을 잡는가.
    #
    # 예전에는 다이아 기준으로 받았다(color). 화면에서 "나는 검은 말"
    # 이라고 고르면 그 반대를 보내야 해서 헷갈린다. **사람 기준**으로
    # 받는다 — 고르는 사람이 곧 그 사람이니까.
    #
    # 안 적어 보내면 두던 것을 그대로. 그것도 없으면 개체가 정한 값.
    you = str(data.get("you") or "").lower()

    if you not in ("white", "black"):
        g = _chess_load() or {}
        was = g.get("dia")

        if was in ("white", "black"):
            you = "black" if was == "white" else "white"
        else:
            you = "black" if AVATAR.chess().get(
                "dia_color", "black") == "white" else "white"

    dia_color = chess.BLACK if you == "white" else chess.WHITE

    board = chess.Board()

    # 난이도. 안 적어 보내면 두던 것을 그대로 쓴다.
    level = str(data.get("level") or _chess_level_key())

    _chess_save(board, dia_color, level)

    view_extra = {}

    # 다이아가 흰 쪽이면 먼저 한 수 둔다
    if board.turn == dia_color:
        move, _ = _chess_pick(board)

        if move:
            board.push(move)
            view_extra["dia_move"] = move.uci()

    _chess_save(board, dia_color, level)

    view = _chess_view(board, dia_color, "start", view_extra)
    view["playing"] = True

    return jsonify(view)


@app.route("/api/chess/move", methods=["POST"])
def chess_move_api():
    """사람이 한 수 두면, 받아서 두고 다이아도 둔다."""

    import chess
    import chess_play

    data = request.get_json(silent=True) or {}
    uci = str(data.get("move") or "").strip()

    board, dia_color = _chess_board()

    if board is None:
        return jsonify({"ok": False, "error": "두던 판이 없습니다."})

    if board.turn == dia_color:
        return jsonify({"ok": False, "error": "지금은 다이아 차례입니다."})

    # 승격을 안 적었으면 퀸으로 친다.
    #
    # 화면에서 폰을 8행에 놓으면 e7e8 만 온다. 그대로는 못 두는 수다.
    try:
        move = chess.Move.from_uci(uci)
    except ValueError:
        return jsonify({"ok": False, "error": "그렇게는 못 둡니다."})

    if move not in board.legal_moves:
        promoted = chess.Move(move.from_square, move.to_square,
                              promotion=chess.QUEEN)
        if promoted in board.legal_moves:
            move = promoted
        else:
            return jsonify({"ok": False, "error": "그렇게는 못 둡니다."})

    # 사람이 다이아 말을 잡았나. **두기 전에** 물어야 한다 —
    # 두고 나면 그 자리에 이미 사람 말이 서 있다.
    dia_lost = board.is_capture(move)

    board.push(move)

    events = []

    if board.is_game_over():
        _chess_save(board, dia_color)
        return jsonify(_chess_view(board, dia_color,
                                   _chess_over_event(board, dia_color)))

    if board.is_check():
        events.append("check_taken")

    # 다이아가 둔다
    move2, _ = _chess_pick(board)

    took = False
    extra = {"you_move": move.uci()}

    if move2 is not None:
        took = board.is_capture(move2)
        board.push(move2)
        extra["dia_move"] = move2.uci()

    _chess_save(board, dia_color)

    # 무슨 일이 가장 할 말이 많은가. 판이 끝난 것 > 장군 > 잡기.
    if board.is_game_over():
        event = _chess_over_event(board, dia_color)
    elif board.is_check():
        event = "check_given"
    elif took:
        event = "took"
    elif dia_lost:
        event = "lost"
    elif events:
        event = events[0]
    else:
        event = None

    return jsonify(_chess_view(board, dia_color, event, extra))


def _chess_over_event(board, dia_color):
    """판이 끝났다면 어떤 끝인가.

    무승부를 한 덩어리로 두면 안 된다. **이기고 있던 쪽이 가장
    억울해하는 끝이 스테일메이트**인데, 그냥 "비겼어요" 라고만 하면
    놀이가 고장 난 줄 안다 — 실제로 그런 말을 들었다.
    왜 비겼는지가 말에 드러나야 한다.
    """

    if board.is_checkmate():
        # 둘 차례인 쪽이 졌다
        return "lose" if board.turn == dia_color else "win"

    if board.is_stalemate():
        return "draw_stalemate"

    if board.is_insufficient_material():
        return "draw_material"

    if board.is_seventyfive_moves() or board.is_fivefold_repetition():
        return "draw_long"

    return "draw"


def _rps_tally(result):
    """가위바위보 한 판을 전적에 더한다.

    놀아 놓고 다음 대화에서 모르면 같이 논 것이 아니다.
    result 는 다이아 기준이다(win = 다이아가 이겼다).
    """

    if result not in ("win", "lose", "draw"):
        return

    d = memory_manager.load_memory_data()

    t = dict(d.get("rps") or {})
    t[result] = int(t.get(result, 0)) + 1
    t["last"] = result

    d["rps"] = t
    memory_manager.save_memory_data(d)



@app.route("/api/chess/start", methods=["POST"])
def chess_start_api():
    """판을 열기 전에 선공부터 가위바위보로 정한다.

    바로 판을 열지 않는다. 여기서는 '가위바위보로 정하자' 고 말만 하고,
    실제 판은 손을 낸 뒤(/api/chess/rps)에 열린다.
    """

    _chess_clear()

    stage = _chess_stage()

    d = memory_manager.load_memory_data()
    d["chess"] = {
        "deciding": True,
        "level": (d.get("chess") or {}).get("level")
                 or AVATAR.chess().get("level", "normal"),
    }
    memory_manager.save_memory_data(d)

    said = AVATAR.chess_first_say("ask", stage)

    if said.get("line"):
        try:
            memory_manager.append_message("assistant", said["line"])
        except Exception as e:
            print("[선공 정하기 기록 실패]:", e)

    return jsonify({
        "ok": True,
        "playing": False,
        "deciding": True,
        "hands": AVATAR.rps_hands(),
        "line": said.get("line"),
        "expression": said.get("expression"),
    })


@app.route("/api/chess/rps", methods=["POST"])
def chess_rps_api():
    """선공을 가리는 가위바위보 한 판.

    이긴 사람이 고른다.
      다이아가 이기면  자기가 선공(흰 말)을 가져가고 판이 바로 열린다.
      사람이 이기면    고르라고 하고 기다린다.
      비기면           다시 낸다.
    """

    data = request.get_json(silent=True) or {}

    g = _chess_load() or {}

    if not g.get("deciding"):
        return jsonify({"ok": False, "error": "선공을 정하는 중이 아닙니다."})

    saved = memory_manager.load_relationship() or {}
    affinity = saved.get("affinity",
                         AVATAR.relationship.get("start_affinity", 0))
    stage = _stage_now(affinity, saved.get("stage"))

    result = AVATAR.rps_play(data.get("hand"), stage=stage, affinity=affinity)

    if result is None:
        return jsonify({"ok": False, "error": "가위바위보에 없는 손입니다."})

    _rps_tally(result.get("result"))

    # 놀았다는 사실은 남긴다. 선공을 가리는 판도 같이 논 것이다.
    try:
        memory_manager.append_message(
            "user",
            f"(선공 가위바위보 - 나는 {result['you_label']}, "
            f"다이아는 {result['mine_label']})")
    except Exception as e:
        print("[선공 가위바위보 기록 실패]:", e)

    out = {
        "ok": True,
        "deciding": True,
        "playing": False,
        "hands": AVATAR.rps_hands(),
        "you_hand": result.get("you"),
        "dia_hand": result.get("mine"),
        "you_label": result.get("you_label"),
        "dia_label": result.get("mine_label"),
        # result 는 다이아 기준이다. win 이면 다이아가 이겼다.
        "result": result.get("result"),
    }

    # 이 판의 승패로만 가른다. 친밀도는 안 건드린다 -
    # 선공을 정하는 것이지 놀이로 사이가 오가는 자리가 아니다.
    if result.get("result") == "draw":
        said = AVATAR.chess_first_say("tie", stage)
        out.update(line=said.get("line"), expression=said.get("expression"))

    elif result.get("result") == "win":
        # 다이아가 이겼다. 선공을 가져간다 = 다이아가 흰 쪽.
        said = AVATAR.chess_first_say("dia_won", stage)
        out.update(line=said.get("line"), expression=said.get("expression"))

        view = _chess_open("black", g.get("level"))
        view["line"] = said.get("line")
        view["expression"] = said.get("expression")
        view["deciding"] = False
        out = view

    else:
        # 사람이 이겼다. 고르라고 하고 기다린다.
        said = AVATAR.chess_first_say("you_won", stage)
        out.update(line=said.get("line"), expression=said.get("expression"),
                   choose=True)

        d = memory_manager.load_memory_data()
        d["chess"] = dict(g, deciding=True, choose=True)
        memory_manager.save_memory_data(d)

    if out.get("line"):
        try:
            memory_manager.append_message("assistant", out["line"])
        except Exception as e:
            print("[선공 가위바위보 기록 실패]:", e)

    return jsonify(out)


def _chess_open(you, level=None):
    """실제로 판을 연다. 사람이 잡는 쪽을 받는다."""

    import chess

    dia_color = chess.BLACK if you == "white" else chess.WHITE

    board = chess.Board()

    level = level or _chess_level_key()

    _chess_save(board, dia_color, level)

    extra = {}

    if board.turn == dia_color:
        move, _ = _chess_pick(board)

        if move:
            board.push(move)
            extra["dia_move"] = move.uci()

    _chess_save(board, dia_color, level)

    view = _chess_view(board, dia_color, None, extra)
    view["playing"] = True
    view["deciding"] = False

    return view


@app.route("/api/chess/level", methods=["POST"])
def chess_level_api():
    """난이도를 바꾼다. 두던 판은 그대로 두고 다음 수부터 달라진다."""

    data = request.get_json(silent=True) or {}

    want = str(data.get("level") or "").strip()

    lv = AVATAR.chess_level(want)

    board, dia_color = _chess_board()

    if board is None:
        # 판이 없으면 다음에 열 때 쓰도록 적어만 둔다
        d = memory_manager.load_memory_data()
        d["chess"] = dict(d.get("chess") or {}, level=lv["key"])
        memory_manager.save_memory_data(d)

        return jsonify({"ok": True, "playing": False, "level": lv["key"]})

    _chess_save(board, dia_color, lv["key"])

    return jsonify(_chess_view(board, dia_color))


@app.route("/api/chess/resign", methods=["POST"])
def chess_resign_api():
    """그만둔다."""

    _chess_clear()

    return jsonify({
        "ok": True,
        "playing": False,
        **_chess_reply("resign"),
    })


@app.route("/test")
def test_page():
    return render_template(
        "test.html"
    )


# ============================================================
# 리깅 확인대
#
# 본 회전은 사양서만 보고 추측하면 틀린다.
# 같은 VRM · 같은 라이브러리로 띄워 놓고 축을 눈으로 보고 정하는 자리.
# ============================================================

@app.route("/model-test")
def model_test_page():
    """모델 시험대.

    아직 확인하지 않은 것만 모아 둔 자리다.
    두 벌 겹치기·절정 표정·새 동작·옷 끌기·모프 타깃.
    여기서 확인이 끝나면 운영 화면(model.layered)을 켠다.
    """
    return render_template(
        "model_test.html"
    )


# ============================================================
# 픽셀창
#
# 칸 하나가 픽셀 하나다. 누르면 검게, 오른쪽 단추로 누르면 희게.
# 아바타와는 상관없는 별개의 화면이다.
# ============================================================

@app.route("/pixel")
def pixel_page():
    return render_template("pixel.html")


@app.route("/rig")
def rig_page():
    return render_template(
        "rig.html"
    )


# ============================================================
# 서버 실행
# ============================================================

if __name__ == "__main__":

    print(
        "========================================"
    )

    print(
        "    diamondAI 시스템을 시작합니다.      "
    )

    print(
        "========================================"
    )

    app.run(
        host="0.0.0.0",
        port=5000,
        debug=True
    )


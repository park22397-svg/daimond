
# main.py
# diamondAI - Flask 서버 메인 실행 파일

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
import memory_manager
import who
from ai_brain import extract_expression, process_chat
from avatar import AVATAR
from memory_manager import (
    load_memory,
    clear_memory
)


app = Flask(__name__)


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
        )

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

        stage = AVATAR.next_stage(
            affinity,
            saved.get("stage")
        )

        import time as _t
        from memory_manager import load_mood

        _m = load_mood()
        mood = AVATAR.mood_now(_m.get("raw", 0), _m.get("since"), _t.time())
        mood_tier = AVATAR.mood_tier(mood)

        raw = saved.get("devotion_raw", 0)
        level = AVATAR.devotion_level(raw)
        tier = AVATAR.devotion_tier(level)

        return jsonify(
            {
                "affinity": affinity,
                "stage": stage.key,
                "label": stage.label,
                "speech": stage.speech,
                "attitude": stage.attitude,
                # 상한을 넘어 쌓인 마음
                "devotion": level,
                "devotion_raw": raw,
                "devotion_label": tier.get("label") if tier else None,
                # 연인인가. 아니면 호감이 광기 앞에서 멈춘다.
                "lover": bool(saved.get("lover", False)),

                # 아이. 창을 다시 열어도 배가 그대로여야 한다.
                "wants_child": bool(saved.get("wants_child", False)),
                "climax": int(saved.get("climax", 0)),
                "pregnant": bool(saved.get("pregnant", False)),
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

        stage = AVATAR.next_stage(
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

        # ----------------------------------------------------------
        # 몸을 섞는 것
        #
        # 손가락은 입과 보지에서만 다른 것이 된다(TouchTool.label_for).
        # 그 자리를 그 도구로, 하의를 벗긴 채로 만졌을 때만이다.
        #
        # 화면은 무엇을 벗겼는지만 보낸다(undressed).
        # 어느 자리를 만졌는지 아는 쪽이 여기라서 판정은 여기서 한다.
        # ----------------------------------------------------------
        sx = AVATAR.sex_conf()

        undressed = data.get("undressed")
        if not isinstance(undressed, list):
            undressed = []

        is_sex = bool(
            sx.get("enabled")
            and tool is not None
            and tool.key == sx.get("tool")
            and zone.key == sx.get("zone")
            and all(z in undressed for z in sx.get("needs_undressed", []))
        )

        result = AVATAR.touch_reaction(
            zone,
            kind,
            stage,
            affinity,
            count=count,
            tool=tool,
        )

        if result is None:
            return jsonify({"hit": False, "bone": bone})

        # ----------------------------------------------------------
        # 절정
        #
        # 한 번 만질 때마다 하나씩 쌓이고, 문턱을 넘으면 절정에 이른다.
        # 넘은 뒤에는 0으로 돌아간다.
        #
        # 절정을 정해진 횟수만큼 겪고, 그 전에 아이를 갖겠다고 말한
        # 뒤라면 아이가 선다. 말한 적이 없으면 몇 번을 겪어도 서지 않는다 —
        # 이것은 몸이 아니라 약속이 정하는 일이다.
        #
        # 세는 값을 저장에 두는 이유: 창을 닫았다 열어도 이어져야 한다.
        # ----------------------------------------------------------
        sex_strokes = None
        sex_climax = None
        sex_pregnant = None

        if is_sex and result.get("allowed"):
            sex_strokes = int(saved.get("strokes", 0)) + 1
            sex_climax = int(saved.get("climax", 0))
            sex_pregnant = bool(saved.get("pregnant", False))
            wants = bool(saved.get("wants_child", False))

            result["kind"] = "sex"

            if sex_strokes >= int(sx.get("climax_strokes", 8)):
                sex_strokes = 0
                sex_climax += 1

                peak = AVATAR.climax_reaction(stage)
                result["reply"] = peak["reply"]
                result["expression"] = peak["expression"]
                result["motion"] = peak["motion"]
                result["expression_then"] = None
                result["affinity_delta"] = int(sx.get("climax_affinity", 10))
                result["climaxed"] = True

                if (not sex_pregnant and wants
                        and sex_climax >= int(sx.get("to_pregnant", 5))):
                    sex_pregnant = True
                    result["pregnant_now"] = True
                    print(f"[아이]: 절정 {sex_climax}번 — 아이가 섰습니다.")
                else:
                    print(f"[절정]: {sex_climax}번째"
                          f"{'' if wants else ' (아이를 갖겠다는 말은 아직 없다)'}")

            result["strokes"] = sex_strokes
            result["climax"] = sex_climax
            result["pregnant"] = sex_pregnant

        # 옷을 여러 번 잡아당기면 옷이 실제로 끌려온다.
        # 한두 번은 말로만 하고, 그 뒤부터 몸이 따라간다.
        if zone.cloth and kind == "pet":
            cfg = AVATAR.touch.get("cloth_tug", {})
            need = cfg.get("from", 3)

            if count >= need:
                over = count - need + 1
                scale = min(over * 0.35 + 1.0, cfg.get("max_scale", 1.8))
                result["tug"] = {
                    "zone": zone.key,
                    "distance": round(cfg.get("distance", 0.045) * scale, 4),
                    "pulls": count,
                }

        # 입을 닫은 단계에서는 만져도 말하지 않는다.
        # 대화에는 답하지 않으면서 손만 대면 재잘거리면 앞뒤가 안 맞는다.
        if getattr(stage, "silent", False):
            conf = AVATAR.relationship.get("silence", {})
            result["reply"] = ""
            result["expression"] = conf.get("expression", "angry")
            result["motion"] = None
            result["silent"] = True

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
        devotion_raw = saved.get("devotion_raw", 0)

        if drop_to is not None and not getattr(stage, "never_falls", False):
            affinity = AVATAR.clamp_affinity(drop_to)
            print(f"[만지기]: 허락되지 않은 자리 — 친밀도를 {affinity} 로 떨어뜨립니다.")
        else:
            # 눈금이 꽉 찼는데도 잘해 주면 그 마음은 갈 데가 없다.
            # 넘친 만큼을 따로 모은다. 100이 모여야 순종 1이 된다.
            # 연인이 아니면 광기 앞에서 멈춘다
            lover = bool(saved.get("lover", False))

            if lover:
                devotion_raw += AVATAR.devotion_overflow(
                    affinity, result["affinity_delta"], stage)

            affinity = AVATAR.apply_delta(
                affinity,
                result["affinity_delta"],
                stage,
                lover=lover,
            )

        stage = AVATAR.next_stage(affinity, before)

        try:
            save_relationship(affinity, stage.key, devotion_raw,
                              bool(saved.get("lover", False)),
                              strokes=sex_strokes,
                              climax=sex_climax,
                              pregnant=sex_pregnant)
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
                "stage_label": stage.label,
                "changed_from": before if before != stage.key else None,
                "pregnant": bool(
                    sex_pregnant if sex_pregnant is not None
                    else saved.get("pregnant", False)),
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

        stage = AVATAR.next_stage(
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
                "stage_label": stage.label,
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
        stage = AVATAR.next_stage(affinity, saved.get("stage"))

        print(f"[기억 꺼냄]: {name} ({count}개)")

        return jsonify(
            {
                "ok": True,
                "name": name,
                "messages": count,
                "affinity": affinity,
                "stage": stage.key,
                "stage_label": stage.label,
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

        stage = AVATAR.next_stage(
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

        stage = AVATAR.next_stage(affinity, before)

        try:
            save_relationship(affinity, stage.key)
        except Exception as e:
            print(f"[가위바위보 관계 저장 오류]: {e}")

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
                "stage_label": stage.label,
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

        stage = AVATAR.next_stage(
            affinity,
            saved.get("stage")
        )

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
                        "label": stage.label,
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
                    "label": stage.label,
                }
            )

        raw = random.choice(lines)

        # 먼저 거는 말도 대화 흐름에 남아야 다음 답이 이어진다
        reply, cues = extract_cues(raw)

        try:
            append_message("assistant", reply)
        except Exception as e:
            print(f"[먼저 말걸기 저장 오류]: {e}")

        return jsonify(
            {
                "speak": True,
                "reply": reply,
                "cues": cues,
                "expression": AVATAR.detect_expression(reply),
                "stage": stage.key,
                "label": stage.label,
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
    "/api/suggest",
    methods=["POST"]
)
def suggest_api():
    """지금 흐름에 맞는 행동 보기를 몇 개 지어 준다.

    짓는 것은 모델이지만 고르는 것은 사람이다.
    클릭하지 않으면 아무 일도 일어나지 않는다.
    """

    try:
        import requests

        from config import OLLAMA_URL, OLLAMA_MODEL, OLLAMA_OPTIONS, OLLAMA_THINK
        from memory_manager import load_memory, load_relationship

        conf = (AVATAR.behavior or {}).get("suggest", {})
        if not conf.get("enabled", True):
            return jsonify({"ok": True, "items": []})

        saved = load_relationship() or {}
        stage = AVATAR.stage(saved.get("stage")) or AVATAR.stage_for_affinity(
            saved.get("affinity", 0))

        count = int(conf.get("count", 4))

        # 방금 나눈 이야기만 준다. 길게 주면 옛 흐름을 짚는다.
        history = load_memory() or []
        recent = [
            {"role": m["role"], "content": str(m["content"]).strip()}
            for m in history[-6:]
            if isinstance(m, dict) and m.get("role") in ("user", "assistant")
        ]

        ask = conf.get("prompt", "").format(count=count, name=AVATAR.name)

        msgs = [{
            "role": "system",
            "content": (
                f"너는 {AVATAR.name}(와)과 상대가 나누는 이야기를 옆에서 보고 "
                f"있다. 지금 사이는 '{stage.label}' 이다.\n\n" + ask
            ),
        }]
        msgs += recent
        msgs.append({"role": "user", "content": ask})

        payload = {
            "model": OLLAMA_MODEL,
            "messages": msgs,
            "stream": False,
            "options": dict(OLLAMA_OPTIONS),
        }
        if OLLAMA_THINK is not None:
            payload["think"] = OLLAMA_THINK

        r = requests.post(OLLAMA_URL, json=payload, timeout=60)
        if r.status_code != 200:
            return jsonify({"ok": False, "error": f"HTTP {r.status_code}"}), 502

        raw = ((r.json().get("message") or {}).get("content") or "")

        drop = conf.get("drop", [])
        cap = int(conf.get("max_len", 30))

        items = []
        for line in raw.split("\n"):
            t = line.strip().strip("-*·•").strip()

            # 번호를 떼어 낸다
            while t and (t[0].isdigit() or t[0] in ".)]、,"):
                t = t[1:].lstrip()

            t = t.strip("()（）[]「」\"'").strip()

            if not t or len(t) > cap:
                continue
            if any(w in t for w in drop):
                continue
            if t in items:
                continue

            items.append(t)
            if len(items) >= count:
                break

        return jsonify({"ok": True, "items": items})

    except Exception as e:
        print(f"[상황 보기 오류]: {e}")
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route(
    "/api/child",
    methods=["GET", "POST"]
)
def child_api():
    """아이에 관한 값을 보고, 맞춘다. 시험용이다.

    절정 다섯 번을 손으로 채우지 않고도 배가 부른 모습을 봐야
    배 모양(pregnancy.spine_scale)을 눈으로 맞출 수 있다.

    POST 로 보낼 수 있는 것 (안 적은 것은 그대로 둔다):
      wants_child : 아이를 갖겠다고 말했는가
      climax      : 절정을 몇 번 겪었는가
      strokes     : 절정까지 얼마나 왔는가
      pregnant    : 아이가 섰는가
      devotion    : 순종 (0~50). raw 로 바꿔서 넣는다
    """

    try:
        from memory_manager import load_relationship, save_relationship

        saved = load_relationship() or {}

        if request.method == "POST":
            data = request.get_json(silent=True) or {}

            def pick(key, cast):
                v = data.get(key)
                return None if v is None else cast(v)

            devotion = data.get("devotion")
            devotion_raw = None
            if devotion is not None:
                per = AVATAR.devotion_conf().get("per_point", 100)
                devotion_raw = int(devotion) * per

            save_relationship(
                saved.get("affinity", 0),
                saved.get("stage", "distant"),
                devotion_raw=devotion_raw,
                lover=None,
                wants_child=pick("wants_child", bool),
                strokes=pick("strokes", int),
                climax=pick("climax", int),
                pregnant=pick("pregnant", bool),
            )
            saved = load_relationship() or {}

        sx = AVATAR.sex_conf()
        raw = saved.get("devotion_raw", 0)

        return jsonify({
            "ok": True,
            "wants_child": bool(saved.get("wants_child", False)),
            "strokes": int(saved.get("strokes", 0)),
            "climax": int(saved.get("climax", 0)),
            "pregnant": bool(saved.get("pregnant", False)),
            "devotion": AVATAR.devotion_level(raw),
            "devotion_raw": raw,

            # 무엇이 얼마나 남았는지 화면이 적어 줄 수 있게
            "need_strokes": int(sx.get("climax_strokes", 8)),
            "need_climax": int(sx.get("to_pregnant", 5)),
            "need_devotion": AVATAR.child_conf().get("devotion", 50),
            "need_stage": AVATAR.child_conf().get("stage", "yandere"),
            "stage": saved.get("stage"),
        })

    except Exception as e:
        print(f"[아이 창구 오류]: {e}")
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
        stage = AVATAR.next_stage(target, None)

        # 순종은 상한을 넘어 넘친 호감이 쌓인 것이다.
        # 호감을 처음으로 돌리면서 이것만 남기면 앞뒤가 안 맞는다.
        # 사이를 처음으로 돌리면 연인이었던 것도 없던 일이 된다
        save_relationship(target, stage.key, 0, False)

        print(f"[호감도 되돌리기]: {before.get('affinity')} -> {target} "
              f"({stage.label}), 순종 {before.get('devotion_raw', 0)} -> 0")

        return jsonify(
            {
                "ok": True,
                "affinity": target,
                "stage": stage.key,
                "stage_label": stage.label,
                "before": before.get("affinity"),
                "before_stage": before.get("stage"),
                "devotion_cleared": before.get("devotion_raw", 0),
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
        stage = AVATAR.next_stage(affinity, saved.get("stage"))

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


@app.route("/api/tts", methods=["POST"])
def tts_api():

    from config import (
        TTS_ENABLED, TTS_PROVIDER, TTS_VOICE,
        TTS_API_KEY, TTS_MODEL, TTS_STYLE,
    )

    if not TTS_ENABLED:
        return jsonify({"ok": False, "error": "목소리가 꺼져 있습니다."}), 400

    data = request.get_json(silent=True) or {}
    text = str(data.get("text") or "").strip()

    if not text:
        return jsonify({"ok": False, "error": "읽을 말이 없습니다."}), 400

    # ------------------------------------------------------------
    # Edge 의 읽어주기 목소리
    #
    # 키가 필요 없다. mp3 로 바로 오므로 화면은 그대로 틀면 된다.
    # ------------------------------------------------------------
    if TTS_PROVIDER == "edge":
        try:
            import asyncio
            import base64

            import edge_tts

            from config import (
                TTS_EDGE_VOICE, TTS_EDGE_RATE, TTS_EDGE_PITCH,
            )

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

            return jsonify(
                {
                    "ok": True,
                    "provider": "edge",
                    "voice": TTS_EDGE_VOICE,
                    "mime": "audio/mpeg",
                    "audio": base64.b64encode(audio).decode("ascii"),
                }
            )

        except Exception as e:
            print(f"[목소리 오류 - edge]: {e}")
            return jsonify(
                {"ok": False, "fallback": "browser",
                 "error": "목소리를 만들지 못했습니다."}
            ), 200

    if TTS_PROVIDER != "gemini" or not TTS_API_KEY:
        # 화면이 알아서 브라우저 목소리로 읽는다
        return jsonify(
            {
                "ok": False,
                "fallback": "browser",
                "error": "서버에서 만들 목소리가 없습니다.",
            }
        ), 200

    try:
        import base64
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
            print(f"[목소리 오류]: HTTP {res.status_code} {res.text[:200]}")
            return jsonify(
                {"ok": False, "fallback": "browser",
                 "error": f"목소리 서버가 {res.status_code} 를 돌려줬습니다."}
            ), 200

        part = (res.json()["candidates"][0]["content"]["parts"][0])
        audio = part["inlineData"]["data"]
        mime = part["inlineData"].get("mimeType", "audio/L16;rate=24000")

        return jsonify(
            {
                "ok": True,
                "provider": "gemini",
                "voice": TTS_VOICE,
                "mime": mime,
                "audio": audio,      # base64
            }
        )

    except Exception as e:
        print(f"[목소리 오류]: {e}")
        return jsonify(
            {"ok": False, "fallback": "browser", "error": "목소리를 만들지 못했습니다."}
        ), 200


# ============================================================
# 배경 이미지
#
# static/background/ 를 훑어 쓸 수 있는 이미지를 알려준다.
# 파일을 넣고 화면만 새로 고치면 바뀌도록, 목록을 코드에 적지 않는다.
# ============================================================

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

    # 꼭 집어 쓰라고 적어 둔 파일이 있으면 그것을 앞으로 옮긴다
    want = conf.get("prefer")
    current = None

    if images:
        current = images[0]
        if want:
            hit = next((i for i in images if i["name"] == want), None)
            if hit:
                current = hit
            else:
                print(f"[배경] prefer 로 적은 '{want}' 을(를) 못 찾았습니다.")

    return jsonify(
        {
            "images": images,
            "current": current,
            "fit": conf.get("fit", "cover"),
            "dim": conf.get("dim", 0.0),
            "folder": folder,
        }
    )


# ============================================================
# 테스트 전용 페이지
#
# 운영 화면(/)은 건드리지 않는다.
# 통합된 개체를 시험하는 자리는 여기로 분리한다.
# ============================================================

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



# main.py
# diamondAI - Flask 서버 메인 실행 파일

from flask import (
    Flask,
    jsonify,
    render_template,
    request
)

from ai_brain import extract_expression, process_chat
from avatar import AVATAR
from memory_manager import (
    load_memory,
    clear_memory
)


app = Flask(__name__)


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

        result = process_chat(
            user_text
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
        zone = AVATAR.zone_for(
            bone,
            local,
            zone_key=data.get("zone"),
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
                how = f"{tool.label}으로 " if tool and tool.key != "hand" else ""
                append_message("user", f"({how}{zone.label}를 만졌다)")
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


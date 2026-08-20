# ai_brain.py
# diamondAI - 대화 및 감정 판단 엔진

import json
import re
import requests

from avatar import AVATAR, is_emoji
import config
from config import (
    MAX_HISTORY_MESSAGES,
    OLLAMA_MODEL,
    OLLAMA_OPTIONS,
    OLLAMA_THINK,
    OLLAMA_URL,
)
from memory_manager import (
    append_message,
    load_memory,
    load_mood,
    load_relationship,
    load_user_name,
    save_mood,
    save_relationship,
    save_user_name,
)


# ============================================================
# 상대가 알려준 호칭 찾아내기
#
# 프롬프트에서 '유저'라는 말을 걷어냈어도, 상대가 이름을 알려줬는데
# 그걸 기억하지 못하면 모델은 또 아무 호칭이나 지어낸다.
# 그래서 알려주는 순간 붙잡아 저장한다.
# ============================================================

_NAME_PATTERNS = [
    r"(?:내|제)\s*이름은\s*([가-힣A-Za-z][가-힣A-Za-z0-9]{0,9})",
    r"(?:나는|저는|난|전)\s*([가-힣A-Za-z][가-힣A-Za-z0-9]{0,9})(?:이야|야|이에요|예요|입니다|이라고|라고)",
    r"([가-힣A-Za-z][가-힣A-Za-z0-9]{0,9})(?:이|)\s*라고\s*(?:불러|부르|해)",
    r"([가-힣A-Za-z][가-힣A-Za-z0-9]{0,9})(?:님|씨)\s*라고\s*(?:불러|부르)",
]

# 이름 자리에 들어오면 안 되는 말
_NOT_NAMES = {
    "그냥", "진짜", "정말", "아니", "네가", "내가", "당신", "너", "나",
    "사람", "누구", "뭐", "이거", "그거", "여기", "거기", "다이아",
    "유저", "사용자", "유주",
}


def detect_user_name(text):
    if not text:
        return None

    for pat in _NAME_PATTERNS:
        m = re.search(pat, text)
        if not m:
            continue
        name = m.group(1).strip()
        if not name or name in _NOT_NAMES or len(name) < 1:
            continue
        return name

    return None

# ============================================================
# 다이아의 핵심 페르소나
#
# 페르소나는 더 이상 이 파일이 소유하지 않는다.
# 아바타 개체(avatar.py 의 AVATAR)가 자기 페르소나를 직접 들고 있고,
# 여기서는 그 개체에게 프롬프트를 달라고 요청할 뿐이다.
#
# AVATAR.system_prompt() 는 아래 _LEGACY_SYSTEM_PROMPT 와 글자 단위로 같다.
# (_verify_merge.py 가 이를 확인한다)
# ============================================================

SYSTEM_PROMPT = AVATAR.system_prompt()


# ============================================================
# 화면에 보이지 않는 표시 걷어내기
#
# 모델은 답변에 이모지(표정)와 괄호(몸짓)를 섞어 쓴다.
# 그 표시는 유저 화면에 글자로 나가면 안 되지만,
# 어느 지점에서 나왔는지는 제스처 엔진에 필요하다.
#
# 그래서 지우기 전에 '정제된 본문 기준 위치'를 함께 기록해 둔다.
# ============================================================

_BRACKET_RE = re.compile(r"[（(]\s*([^()（）]{1,20})\s*[)）]")


def extract_cues(text):
    """표시를 걷어낸 본문과, 그 표시가 있던 자리 목록을 돌려준다.

    반환: (clean_text, cues)
      cues = [{"at": 정제본문에서의 위치, "type": "expression"|"motion",
               "key": ..., "hold_ms": ...}, ...]
    """

    if not text:
        return "", []

    motion_map = AVATAR.motion_cue_map()
    expr_map = AVATAR.expression_cue_map()

    # 표정 신호 중 이모지만 골라 위치를 잡는다.
    # 'ㅋㅋ' 같은 한글 신호는 평범한 말이므로 화면에 그대로 남긴다.
    emoji_to_expr = {}
    for e in AVATAR.expressions:
        for t in e.live_triggers:
            if is_emoji(t):
                emoji_to_expr[t] = e

    out = []
    cues = []
    i = 0
    n = len(text)

    while i < n:

        # 괄호 몸짓
        m = _BRACKET_RE.match(text, i)
        if m:
            inner = m.group(1).strip()
            key = motion_map.get(inner)
            if key:
                cue = {
                    "at": len(out),
                    "type": "motion",
                    "key": key,
                }

                # 쑥스러워하는 몸짓은 세기가 있다.
                # 말끝에 슬쩍 붙인 것과 얼굴을 못 들 만큼인 것이
                # 같은 몸짓일 수는 없다. 문장 전체를 보고 정한다.
                # 상처받은 몸짓(팔짱·등돌리기)은 어떤 마음인지가 같이 간다.
                # 슬프면 슬픔, 화나면 화남, 삐치면 삐죽. 등을 돌린 채
                # 머무는 시간도 마음의 크기가 정한다.
                hurt = AVATAR.hurt_reaction(text)
                if hurt and key in ("cross", "turn_back"):
                    cue["key"] = hurt["motion"]
                    cue["face"] = hurt["expression"]
                    cue["linger_ms"] = hurt.get("linger_ms", 0)

                if key in AVATAR.shy_motions():
                    lv = AVATAR.shy_level(text)
                    if lv:
                        cue["key"] = lv["motion"]
                        cue["level"] = lv["level"]
                        # 표정은 센 단계에서만 함께 간다.
                        # 낮으면 웃으면서 쑥스러워할 수 있어야 한다.
                        if lv["expression"]:
                            cue["face"] = lv["expression"]

                cues.append(cue)
                i = m.end()
                # 표시를 지우면서 생긴 공백 중복을 정리
                while i < n and text[i] == " " and (not out or out[-1] == " "):
                    i += 1
                continue
            # 몸짓이 아니면 얼굴 이름인지 본다.
            #
            # (표정: 째려보기) 또는 (째려보기) 둘 다 받는다.
            # 만화의 얼굴은 이모지로 고를 수 없어서 이름으로 부른다.
            want = inner
            for head in ("표정:", "표정 :", "얼굴:", "얼굴 :"):
                if want.startswith(head):
                    want = want[len(head):].strip()
                    break

            ekey = expr_map.get(want) or expr_map.get(want.replace(" ", ""))
            if ekey:
                e = AVATAR.expression(ekey)
                cues.append({
                    "at": len(out),
                    "type": "expression",
                    "key": ekey,
                    "hold_ms": e.hold_ms if e else 3000,
                })
                i = m.end()
                while i < n and text[i] == " " and (not out or out[-1] == " "):
                    i += 1
                continue

            # 몸짓 이름도 얼굴 이름도 아닌 괄호는 '상황' 이다.
            #
            # 예전에는 버렸다. 그래서 다이아는 몸짓 표에 있는 것만
            # 할 수 있었고, 표에 없는 짓은 아무리 적어도 사라졌다.
            # 이제 괄호째 남겨 화면에 내보낸다 — 상대가
            # (다이아를 지긋이 바라본다) 라고 쓰는 것과 같은 자리다.
            #
            # 한 글자씩 넣는 것이 중요하다. 아래에서 표시가 있던 자리를
            # len(out) 으로 재는데, 여기서 통째로 넣으면 칸 수가 어긋나
            # **그 뒤의 표정과 몸짓이 전부 엉뚱한 자리에서 터진다.**
            at = len(out)
            out.extend(m.group(0))
            i = m.end()

            # 적어 놓고 안 하면 안 적은 것보다 어색하다.
            #
            # (멋쩍은 듯 눈동자가 흔들리며) 라고 써 놓고 얼굴이 가만히
            # 있으면, 글은 흔들린다는데 눈은 멀쩡하다. 그래서 문장을
            # 읽어 얼굴과 몸으로 옮긴다. 못 읽는 문장이 훨씬 많고,
            # 그때는 글자로만 나온다 — 지금까지와 같다.
            act = AVATAR.act_reaction(inner)

            if act:
                if act.get("motion"):
                    cue = {
                        "at": at,
                        "type": "motion",
                        "key": act["motion"],
                    }
                    if act.get("expression"):
                        cue["face"] = act["expression"]
                    cues.append(cue)

                elif act.get("expression"):
                    e = AVATAR.expression(act["expression"])
                    cues.append({
                        "at": at,
                        "type": "expression",
                        "key": act["expression"],
                        "hold_ms": e.hold_ms if e else 3000,
                    })

            continue

        # 이모지 표정
        matched = None
        for token in emoji_to_expr:
            if text.startswith(token, i):
                if matched is None or len(token) > len(matched):
                    matched = token
        if matched:
            e = emoji_to_expr[matched]
            cues.append({
                "at": len(out),
                "type": "expression",
                "key": e.key,
                "hold_ms": e.hold_ms,
            })
            i += len(matched)
            while i < n and text[i] == " " and (not out or out[-1] == " "):
                i += 1
            continue

        out.append(text[i])
        i += 1

    clean = "".join(out)
    clean = re.sub(r"[ \t]{2,}", " ", clean)
    clean = re.sub(r"\s+([,.!?])", r"\1", clean)
    clean = clean.strip()

    # 본문이 줄어든 만큼 위치가 밖으로 나가지 않게 맞춘다
    for c in cues:
        c["at"] = max(0, min(c["at"], len(clean)))

    return clean, cues


# ============================================================
# 감정 및 대화 추출 기능
# ============================================================

# 어떤 감정을 돌려줄 수 있는지도 아바타가 정한다.
VALID_EXPRESSIONS = AVATAR.reply_expression_keys()

def extract_expression(text):
    """문장 속 이모티콘을 역추적하여 감정을 추출합니다.

    이모지와 감정의 대응 관계는 아바타 개체가 소유한다.
    여기서는 대괄호 태그를 걷어내고 판단을 아바타에게 넘긴다.
    """
    if not text:
        return "neutral", ""

    clean_text = text.strip()

    # 과거용 대괄호 감정 태그가 있다면 본문에서 제거
    match = re.search(
        r"\[\s*(joy|happy|sorrow|sad|angry|surprised|fun|neutral)\s*\]",
        clean_text,
        re.IGNORECASE
    )

    if match:
        clean_text = re.sub(
            r"\[\s*(happy|sad|angry|surprised|neutral|joy|sorrow|fun)\s*\]",
            "",
            clean_text,
            flags=re.IGNORECASE
        ).strip()

    return AVATAR.detect_expression(clean_text), clean_text

def clean_reply(text):
    """AI 답변에서 불필요한 연출 기호나 소설식 괄호를 정밀 제거합니다."""
    if not text:
        return ""

    result = text.strip()
    
    # 수동 대괄호 태그가 남아있다면 일괄 청소
    result = re.sub(r"\[(happy|sad|angry|surprised|neutral|joy|sorrow|fun)\]", "", result, flags=re.IGNORECASE).strip()
    # 내부 판단 메모 흔적 청소
    result = re.sub(r"^(감정|표정|emotion)\s*:\s*.*?\n", "", result, flags=re.IGNORECASE).strip()
    # 🌟 소설식 괄호체 표현 완벽 제거 (말풍선 및 기억 오염 방지)

    return result

# ============================================================
# 관계 갱신
#
# 유저의 말 한마디로 친밀도를 조정하고, 지금 어떤 사이인지 정한다.
# 판정은 서버가 한다. 모델에게 묻지 않는다.
# ============================================================

def update_relationship(user_text):
    """
    반환: (stage, transition_label)
      transition_label 은 이번에 단계가 바뀐 경우에만 이전 단계 이름이 들어간다.
    """

    try:
        saved = load_relationship() or {}
    except Exception as e:
        print(f"[관계 불러오기 오류]: {e}")
        saved = {}

    affinity = saved.get(
        "affinity",
        AVATAR.relationship.get("start_affinity", 0)
    )

    prev_key = saved.get("stage")
    devotion_raw = saved.get("devotion_raw", 0)
    lover = bool(saved.get("lover", False))

    try:
        here = AVATAR.stage(prev_key) if prev_key else None
        delta = AVATAR.score_message(user_text)

        # 눈금이 꽉 찼는데도 잘해 주면 그 마음은 갈 데가 없다.
        # 넘친 만큼을 따로 모은다. 100이 모여야 순종 1이 된다.
        # 천장에 막혀 있으면 넘칠 것도 없다
        if lover:
            devotion_raw += AVATAR.devotion_overflow(affinity, delta, here)

        # 얀데레처럼 되돌아가지 않는 단계에서는 깎이지 않는다.
        # 연인이 아니면 광기 앞에서 멈춘다.
        affinity = AVATAR.apply_delta(affinity, delta, here, lover=lover)

    except Exception as e:
        print(f"[관계 점수 계산 오류]: {e}")

    stage = AVATAR.next_stage(affinity, prev_key)

    transition = None
    if prev_key and prev_key != stage.key:
        before = AVATAR.stage(prev_key)
        if before is not None:
            transition = before.label

    try:
        save_relationship(affinity, stage.key, devotion_raw, lover)
    except Exception as e:
        print(f"[관계 저장 오류]: {e}")

    return stage, transition


def _polite(stage):
    """지금 단계가 존댓말을 쓰는지."""
    return stage is None or stage.speech.startswith("존댓말")


def _fallback(stage, polite_text, casual_text):
    """말투가 어긋나면 맥락이 깨지므로 대체 응답도 단계를 따른다."""
    return polite_text if _polite(stage) else casual_text


# ============================================================
# 핵심 대화 처리 프로세스
# ============================================================

def process_chat(user_text, seeing=None, cut_off=False):
    """상대의 말에 답한다.

    seeing 은 지금 눈에 보이는 것이다(카메라나 사진).
    그림을 보는 모델이 적어 준 글이고, 그것을 읽고 무슨 말을 할지는
    여기서 다이아가 정한다. 눈이 대신 말하게 두지 않는다.

    cut_off 는 방금 말하던 것을 상대가 끊고 들어왔는가다.
    """

    if not user_text:
        return {
            "expression": "neutral",
            "reply": "잘 못 들었어요. 다시 말씀해 주시겠어요?",
            "cues": [],
        }

    user_text = str(user_text).strip()

    # 관계부터 갱신한다. 이번 답변의 말투가 여기서 정해진다.
    stage, transition = update_relationship(user_text)

    # 화면이 친밀도 눈금을 그리려면 숫자도 알아야 한다
    try:
        affinity_now = (load_relationship() or {}).get(
            "affinity",
            AVATAR.relationship.get("start_affinity", 0)
        )
    except Exception:
        affinity_now = None

    # 이번 말에 호칭을 알려줬다면 바로 붙잡아 기억한다
    try:
        told = detect_user_name(user_text)
        if told:
            save_user_name(told)
            print(f"[호칭 기억]: {told}")
        user_name = load_user_name()
    except Exception as e:
        print(f"[호칭 처리 오류]: {e}")
        user_name = None

    # 다정한 말로 깨웠는지. 자다 깬 얼굴을 놀람에서 무엇으로 바꿀지 화면이 이걸로 정한다.
    warm = False
    try:
        low = str(user_text).lower()
        sig = AVATAR.relationship.get("signals", {})
        warm = any(w in low for w in sig.get("positive", [])) and \
            not any(w in low for w in sig.get("negative", []))
    except Exception:
        warm = False

    # 기분이 상하는 일.
    #
    # 모진 말을 들었거나 상처 주는 말을 들으면 기분이 상한다.
    # 친밀도와는 따로 움직인다 — 사이가 좋아도 지금 상해 있을 수 있다.
    import time as _time

    mood_now = 0
    try:
        _saved = load_mood()
        _now = _time.time()
        mood_now = AVATAR.mood_now(
            _saved.get("raw", 0), _saved.get("since"), _now)

        _conf = AVATAR.mood_conf().get("hurt", {})
        _up = 0

        if AVATAR.hurt_reaction(user_text):
            _up = max(_up, _conf.get("words", 3))
        elif AVATAR.score_message(user_text) < 0:
            _up = max(_up, _conf.get("negative", 2))

        if _up:
            before = mood_now
            mood_now = AVATAR.mood_clamp(mood_now + _up)
            if mood_now != before:
                save_mood(mood_now, _now)
                print(f"[기분]: {before} -> {mood_now} (말)")

    except Exception as e:
        print(f"[기분 처리 오류]: {e}")
        mood_now = 0

    # 같이 걷자는 말인지 미리 읽어 둔다.
    # 대화 중에는 제자리에 서 있다가, 이 말이 나오면 발이 풀린다.
    try:
        walk = AVATAR.walk_invite(user_text)
    except Exception:
        walk = None

    # 가까이 오라는 말인지도 같이 읽는다.
    # 평소 서는 거리에서는 손이 닿지 않아서, 걸어가는 대신
    # 부를 수도 있어야 한다.
    try:
        approach = AVATAR.come_invite(user_text)
    except Exception:
        approach = None

    def done(reply, expression="neutral", cues=None, silent=False, motion=None):
        # 침묵은 남길 말이 없다. 빈 줄을 기록에 넣으면
        # 나중에 그 자리가 '아무 말도 안 한 답변'처럼 모델에게 보인다.
        if reply:
            try:
                append_message("assistant", reply)
            except Exception as e:
                print(f"[AI 답변 기억 저장 오류]: {e}")
        return {
            "expression": expression,
            "reply": reply,
            "cues": cues or [],
            "silent": silent,
            "motion": motion,
            "warm": warm,
            # 같이 걷자고 했는가. 화면이 이걸 보고 발을 풀거나 묶는다.
            "walk": walk,
            # 가까이 오라고 했는가. 'near' 면 손이 닿는 데까지 온다.
            "approach": approach,
            # 지금 얼마나 상해 있는가
            "mood": mood_now,
            # 연인인가. 아니면 호감이 광기 앞에서 멈춘다.
            "lover": bool((load_relationship() or {}).get("lover", False)),
            "relationship": {
                "stage": stage.key,
                "label": stage.label,
                "changed_from": transition,
                "affinity": affinity_now,
            },
            "user_name": user_name,
        }

    try:
        append_message("user", user_text)
    except Exception as e:
        print(f"[기억 저장 오류]: {e}")

    # ----------------------------------------------------------
    # 상대가 괄호로 쓴 행동을 읽는다.
    #
    # "(머리를 쓰다듬는다)" 는 말이 아니라 손짓이다. 마우스로 만진 것과
    # 같은 표를 태워, 자리·도구·친밀도 규칙이 두 벌로 갈라지지 않게 한다.
    # 뜻을 모르는 행동은 손대지 않는다. 그건 모델이 상황으로 읽는다.
    # ----------------------------------------------------------

    touch = None
    spoken = user_text

    try:
        acts, spoken = AVATAR.parse_action(user_text)
        known = [a for a in acts if a.get("zone")]

        if known:
            a = known[0]
            touch = AVATAR.touch_reaction(
                AVATAR.touch_zone(a["zone"]),
                a["kind"],
                stage,
                affinity_now if affinity_now is not None else 0,
                tool=AVATAR.touch_tool(a["tool"]),
            )

        if touch:
            base = affinity_now if affinity_now is not None else 0
            affinity_now = AVATAR.clamp_affinity(
                base + touch.get("affinity_delta", 0)
            )
            stage = AVATAR.next_stage(affinity_now, stage.key)
            save_relationship(affinity_now, stage.key)
            print(f"[글로 만지기]: {a['raw']} -> {touch['label']} "
                  f"({touch['affinity_delta']:+d})")

    except Exception as e:
        print(f"[행동 읽기 오류]: {e}")
        touch = None

    # ----------------------------------------------------------
    # 고백
    #
    # 사귀자는 말은 모델에게 맡기지 않는다. 받아들일지 말지는 사이가
    # 정하는 것이지 그때그때 문장으로 정할 일이 아니고, 받아들인 순간
    # 관계 자체가 달라지기 때문이다.
    # ----------------------------------------------------------

    if AVATAR.is_confession(user_text):
        try:
            _saved = load_relationship() or {}
            _lover = bool(_saved.get("lover", False))
            _aff = _saved.get(
                "affinity", AVATAR.relationship.get("start_affinity", 0))

            r = AVATAR.confess_reply(_aff, stage, _lover)

            if r["accepted"]:
                _aff = AVATAR.clamp_affinity(
                    _aff + r["affinity_delta"], lover=True)
                stage = AVATAR.next_stage(_aff, stage.key)
                save_relationship(_aff, stage.key,
                                  _saved.get("devotion_raw", 0), True)
                affinity_now = _aff
                print(f"[고백]: 받아들였습니다. 이제 연인이고, "
                      f"호감이 {_aff} 로 올랐습니다.")
            else:
                print(f"[고백]: {'이미 연인' if _lover else '아직 이르다'}")

            if r["reply"]:
                return done(
                    r["reply"],
                    expression=r["expression"],
                    motion=r.get("motion"),
                )

        except Exception as e:
            print(f"[고백 처리 오류]: {e}")

    # ----------------------------------------------------------
    # 아이
    #
    # 고백과 같은 이유로 모델에게 맡기지 않는다. 아이를 갖겠다는 말은
    # 그때그때 문장으로 정할 일이 아니라 사이가 정하는 것이고,
    # 그 말 뒤로는 몸으로 하는 일의 뜻이 달라지기 때문이다.
    #
    # 순종의 마지막 칸(50)에 닿아야 받아들인다.
    # ----------------------------------------------------------

    if AVATAR.is_child_talk(user_text):
        try:
            _saved = load_relationship() or {}
            _wants = bool(_saved.get("wants_child", False))
            _preg = bool(_saved.get("pregnant", False))
            _aff = _saved.get(
                "affinity", AVATAR.relationship.get("start_affinity", 0))
            _dev = AVATAR.devotion_level(_saved.get("devotion_raw", 0))

            r = AVATAR.child_reply(stage, _dev, _wants, _preg)

            if r["accepted"]:
                _aff = AVATAR.clamp_affinity(
                    _aff + r["affinity_delta"],
                    lover=bool(_saved.get("lover", False)))
                stage = AVATAR.next_stage(_aff, stage.key)
                save_relationship(_aff, stage.key,
                                  _saved.get("devotion_raw", 0),
                                  _saved.get("lover", False),
                                  wants_child=True)
                affinity_now = _aff
                print(f"[아이]: 그러겠다고 답했습니다. 순종 {_dev}.")
            else:
                print(f"[아이]: 순종 {_dev} — "
                      f"{'이미 말했다' if _wants else '아직 이르다'}")

            if r["reply"]:
                return done(
                    r["reply"],
                    expression=r["expression"],
                    motion=r.get("motion"),
                )

        except Exception as e:
            print(f"[아이 처리 오류]: {e}")

    # 입을 닫은 단계에서는 모델을 부르지 않는다.
    #
    # 부르면 무슨 말이든 하게 되고, 그러면 '대답하지 않는다'가 아니라
    # '차갑게 대답한다'가 되어 버린다. 침묵은 짧은 대답이 아니라 없는 대답이다.
    # 상대의 말은 기억에 남긴다. 나중에 사이가 풀리면 그동안의 이야기가 이어진다.
    if getattr(stage, "silent", False):
        conf = AVATAR.relationship.get("silence", {})
        print(f"[침묵]: {stage.label} 단계라 답하지 않습니다.")
        return done(
            "",
            expression=conf.get("expression", "angry"),
            silent=True,
        )

    # 손짓만 하고 아무 말도 하지 않았다면 모델을 부를 것이 없다.
    # 정해 둔 반응이 이미 그 자리에 맞는 말이고, 기다릴 이유도 없다.
    if touch and not spoken and touch.get("reply"):
        return done(
            touch["reply"],
            expression=touch.get("expression", "neutral"),
            motion=touch.get("motion"),
        )

    try:
        history = load_memory()
        if not isinstance(history, list):
            history = []
    except Exception as e:
        print(f"[기억 불러오기 오류]: {e}")
        history = []

    try:
        devotion = AVATAR.devotion_level(
            (load_relationship() or {}).get("devotion_raw", 0))
    except Exception:
        devotion = 0

    _rel = load_relationship() or {}

    system_prompt = AVATAR.system_prompt(
        stage=stage,
        transition=transition,
        devotion=devotion,
        mood=mood_now,
        lover=bool(_rel.get("lover", False)),
        # 아이를 가졌다는 것은 몸이 아니라 프롬프트로 드러난다
        pregnant=bool(_rel.get("pregnant", False)),
    )
    if user_name:
        system_prompt += "\n" + AVATAR.address_block(user_name)

    messages = [{"role": "system", "content": system_prompt}]

    # 오래된 기록까지 전부 보내면 예전 말투가 예시가 되어 모델을 끌어당긴다.
    # 최근 것만 보낸다.
    recent = []
    for item in history:
        if not isinstance(item, dict):
            continue
        role = item.get("role")
        content = item.get("content")
        if role not in ("user", "assistant", "system") or not isinstance(content, str):
            continue
        content = content.strip()
        if not content:
            continue
        recent.append({"role": role, "content": content})

    if MAX_HISTORY_MESSAGES > 0:
        recent = recent[-MAX_HISTORY_MESSAGES:]

    messages.extend(recent)

    # 말투 지시를 맨 마지막에 한 번 더 둔다.
    # 모델은 바로 앞에 있는 것을 가장 강하게 따르기 때문에,
    # 기록 뒤에 놓아야 기록 속 옛 말투를 이길 수 있다.
    # 손짓을 알아들었다면 무엇을 한 것인지 짚어 준다.
    # 괄호만 보고 모델이 알아서 읽게 두면 글자로 받아치는 일이 생긴다.
    if touch:
        messages.append({
            "role": "system",
            "content": (
                f"상대가 방금 너의 {touch['label']}을(를) 만졌다. "
                f"그 행동에 반응해서 답하라. "
                f"괄호 안의 말을 따라 적지는 마라."
            ),
        })

    # 말하던 것을 끊고 들어왔다.
    #
    # 아무 일도 없었던 것처럼 이어 말하면 끊긴 티가 안 난다.
    # 무슨 말을 하라고는 적지 않는다 — 사이가 정할 일이다.
    # 친구라면 웃으며 넘어가고, 집착이라면 말을 자른 것을 짚는다.
    if cut_off:
        messages.append({
            "role": "system",
            "content": (
                "[방금 네가 말하던 중에 상대가 끼어들어 말을 끊었다] "
                "하던 말을 처음부터 다시 하지 마라. "
                "끊긴 것을 알고 있는 사람으로서 답하라."
            ),
        })

    # 지금이 언제인가.
    #
    # 기분과 같은 자리에 같은 방식으로 넣는다. 무슨 말을 하라고는
    # 적지 않는다 — 새벽이라는 것만 알면 사이에 맞는 말이 알아서 나온다.
    try:
        from memory_manager import touch_session
        _before = touch_session()
        _when = AVATAR.time_note(last_talk=_before)
    except Exception as e:
        print(f"[시간 읽기 오류]: {e}")
        _when = None

    if _when:
        messages.append({
            "role": "system",
            "content": f"[지금] {_when}",
        })

    # 지금 눈에 보이는 것.
    #
    # 이 글은 그림을 보는 모델이 적은 것이지 다이아가 적은 것이 아니다.
    # 그래서 '설명을 따라 적지 마라' 를 같이 준다 — 안 그러면
    # "파란 배경에 노란 사각형이 보이네" 같은 남의 말투가 그대로 나온다.
    if seeing:
        messages.append({
            "role": "system",
            "content": (
                f"[지금 네 눈에 보이는 것] {seeing}\n"
                f"이건 네가 본 것이다. 설명문을 따라 적지 말고 "
                f"본 사람으로서 네 말로 반응하라. "
                f"보이는 것을 다 짚지 말고 눈에 걸리는 것 하나만 말해도 된다."
            ),
        })

    reminder = AVATAR.tone_reminder(stage, transition, user_name)
    if reminder:
        messages.append({"role": "system", "content": reminder})

    payload = {
        "model": OLLAMA_MODEL,
        "messages": messages,
        "stream": False,
        "options": dict(OLLAMA_OPTIONS),
    }

    # 속생각은 화면에 쓰이지 않는데 생성 시간은 다 든다. 끄면 3배 빨라진다.
    if OLLAMA_THINK is not None:
        payload["think"] = OLLAMA_THINK

    try:
        response = requests.post(config.ollama_url(), json=payload, timeout=60)

        # 서버가 이 항목을 모르는 판이면 빼고 한 번만 다시 보낸다.
        if response.status_code == 400 and "think" in payload:
            print("[알림] 서버가 think 항목을 받지 않아 빼고 다시 보냅니다.")
            payload.pop("think")
            response = requests.post(config.ollama_url(), json=payload, timeout=60)

        if response.status_code != 200:
            return done(_fallback(
                stage,
                "지금 연결이 잠깐 이상한 것 같아요. 다시 말씀해 주시겠어요?",
                "지금 연결이 잠깐 이상한 것 같아. 다시 말해줄래?",
            ))

        try:
            response_data = response.json()
        except ValueError:
            return done(_fallback(
                stage,
                "응답이 이상하게 왔어요. 한 번만 다시 말씀해 주세요.",
                "응답이 이상하게 왔어. 한 번만 다시 말해줄래?",
            ))

        raw_reply = response_data.get("message", {}).get("content", "")
        if not isinstance(raw_reply, str):
            raw_reply = ""
        raw_reply = raw_reply.strip()

        if not raw_reply:
            return done(_fallback(
                stage,
                "잠깐 생각이 멈췄어요. 다시 한 번 말씀해 주세요.",
                "잠깐 생각이 멈췄어. 다시 한 번 말해줄래?",
            ))

        # 옛 대괄호 태그 제거 -> 답변 전체의 감정 판정
        expression, tagged_clean = extract_expression(raw_reply)
        tagged_clean = clean_reply(tagged_clean)

        # 화면에 보이지 않는 표시를 걷어내고, 그 자리를 큐로 남긴다
        clean_text, cues = extract_cues(tagged_clean)

        if not clean_text:
            return done(_fallback(
                stage,
                "잠깐 말이 꼬였어요. 다시 이야기해 주세요.",
                "잠깐 말이 꼬였네. 다시 이야기해줄래?",
            ))

        # 상대가 "알겠어?" 하고 확인하면 고개를 끄덕인다.
        # 말로 "응" 하는 것보다 끄덕이는 쪽이 먼저 나오는 반응이다.
        # 만져서 나온 몸짓이 이미 있으면 그쪽이 우선이다.
        motion = touch.get("motion") if touch else None
        if motion is None:
            motion = AVATAR.asks_understood(user_text)

        # 걷어낸 표시를 따로 적어 둔다. 안 그러면 무엇이 왜 나왔는지
        # 나중에 따져볼 방법이 없다.
        log_cues(user_text, clean_text, cues,
                 extra=(f"동작 {motion}" if motion else None))

        return done(
            clean_text,
            expression,
            cues,
            motion=motion,
        )

    # 연결이 안 된 것을 먼저 잡는다.
    #
    # ConnectTimeout 은 ConnectionError 이면서 Timeout 이기도 하다.
    # Timeout 절을 위에 두면 **닿지도 못한 것을 '생각이 오래 걸린다'**
    # 고 답한다. 실제로 그것 때문에 원인을 한참 못 찾았다 —
    # 올린 서버가 모델 서버에 아예 못 닿는데 화면에는 생각 중이라고
    # 나왔다. 무엇이 잘못됐는지가 말에 드러나야 한다.
    except requests.exceptions.ConnectionError as e:
        print("[모델 서버에 못 닿음]:", e)
        return done(_fallback(
            stage,
            "지금 서버와 연결이 안 되는 것 같아요. 잠시 후에 다시 해볼까요?",
            "지금 서버랑 연결이 안 되는 것 같아. 잠깐 있다 다시 해보자.",
        ))

    except requests.exceptions.Timeout as e:
        print("[모델이 제때 답을 못 줌]:", e)
        return done(_fallback(
            stage,
            "생각하는 데 시간이 조금 걸리고 있어요. 잠깐만요.",
            "생각하는 데 시간이 좀 걸리네. 잠깐만.",
        ))

    except Exception:
        return done(_fallback(
            stage,
            "뭔가 꼬인 것 같아요. 다시 이야기해 주세요.",
            "뭔가 꼬인 것 같아. 다시 이야기해보자.",
        ))


# ============================================================
# 혼자 말 잇기
#
# 대답이 없어도 말을 멈추지 않는 단계가 있다(Stage.keeps_talking).
# 얀데레가 그렇다. 상대가 조용한 것을 기다림으로 받아들이지 않는다.
#
# 정해둔 문장(first_talk)을 꺼내는 것과는 다르다. 그건 몇 번 듣고 나면
# 같은 말이 돌아오는 게 보인다. 여기서는 매번 새로 생각한다.
# "안녕" 이라고 했는데 답이 없으면 "안녕이라고 했는데 왜 대답 안 해?" 가
# 나오는 자리다. 그러려면 자기가 방금 뭐라고 했는지를 알아야 하므로
# 대화 기록을 그대로 태운다.
#
# 몇 번째로 혼자 말하는 중인지는 기록의 꼬리를 세어 알아낸다.
# 끝에 assistant 만 이어져 있으면 그만큼 답을 못 받은 것이다.
# ============================================================

def _unanswered_count(history):
    n = 0
    for item in reversed(history or []):
        if not isinstance(item, dict):
            continue
        if item.get("role") == "assistant":
            n += 1
        elif item.get("role") == "user":
            break
    return n


def _nudge_note(n):
    """혼자 말을 이어갈 때 붙이는 지시. 횟수에 따라 온도가 달라진다."""

    if n <= 1:
        return ("상대가 아직 아무 말도 하지 않았다. 방금 네가 한 말에 답이 없다. "
                "기다리지 말고 네가 먼저 말을 이어라. "
                "왜 대답이 없는지 짚어도 되고, 다른 말을 꺼내도 된다.")

    if n <= 3:
        return (f"네가 {n}번 말했는데 상대는 한 번도 답하지 않았다. "
                "같은 말을 되풀이하지 마라. 앞에서 한 말을 이어받아 "
                "한 걸음 더 들어가라.")

    return (f"네가 {n}번째 혼자 말하고 있다. 상대는 계속 조용하다. "
            "그래도 멈추지 않는다. 화를 내지도 매달리지도 마라. "
            "혼잣말처럼 조용히, 그러나 분명하게 이어라.")


def keep_talking():
    """대답이 없어도 스스로 생각해서 다음 말을 만든다.

    부를 수 없는 상태(모델 오류 등)면 None 을 돌려준다.
    그때는 부르는 쪽이 정해둔 문장으로 넘어간다.
    """

    saved = load_relationship() or {}
    affinity = saved.get(
        "affinity", AVATAR.relationship.get("start_affinity", 0))
    stage = AVATAR.next_stage(affinity, saved.get("stage"))

    try:
        history = load_memory()
        if not isinstance(history, list):
            history = []
    except Exception as e:
        print(f"[혼자 말 잇기 - 기억 오류]: {e}")
        history = []

    n = _unanswered_count(history)

    messages = [{
        "role": "system",
        "content": AVATAR.system_prompt(
            stage=stage,
            transition=None,
            devotion=AVATAR.devotion_level(saved.get("devotion_raw", 0)),
            pregnant=bool(saved.get("pregnant", False)),
        ),
    }]

    recent = [
        {"role": i["role"], "content": i["content"].strip()}
        for i in history
        if isinstance(i, dict)
        and i.get("role") in ("user", "assistant", "system")
        and isinstance(i.get("content"), str)
        and i["content"].strip()
    ]
    if MAX_HISTORY_MESSAGES > 0:
        recent = recent[-MAX_HISTORY_MESSAGES:]
    messages.extend(recent)

    messages.append({"role": "system", "content": _nudge_note(n)})

    reminder = AVATAR.tone_reminder(stage, None, load_user_name())
    if reminder:
        messages.append({"role": "system", "content": reminder})

    payload = {
        "model": OLLAMA_MODEL,
        "messages": messages,
        "stream": False,
        "options": dict(OLLAMA_OPTIONS),
    }
    if OLLAMA_THINK is not None:
        payload["think"] = OLLAMA_THINK

    try:
        res = requests.post(config.ollama_url(), json=payload, timeout=60)
        if res.status_code == 400 and "think" in payload:
            payload.pop("think")
            res = requests.post(config.ollama_url(), json=payload, timeout=60)
        if res.status_code != 200:
            return None

        raw = res.json().get("message", {}).get("content", "")
        if not isinstance(raw, str) or not raw.strip():
            return None

        expression, text = extract_expression(raw.strip())
        text, cues = extract_cues(clean_reply(text))
        if not text:
            return None

        try:
            append_message("assistant", text)
        except Exception as e:
            print(f"[혼자 말 잇기 저장 오류]: {e}")

        print(f"[혼자 말 잇기]: {n + 1}번째 · {stage.label}")

        return {
            "reply": text,
            "cues": cues,
            "expression": expression,
            "unanswered": n + 1,
        }

    except Exception as e:
        print(f"[혼자 말 잇기 오류]: {e}")
        return None


# ============================================================
# 표시 기록
#
# 괄호 몸짓과 이모지 표정은 화면에 내보내기 전에 걷어낸다. 그래서
# 대화 기록만 봐서는 다이아가 무엇을 했는지 알 수 없다 —
# "기지개를 켰다" 는 말을 들어도 로그에 그 흔적이 없다.
#
# 무엇이 왜 나왔는지 뒤늦게 따져 보려면 걷어낸 것을 따로 적어 두어야 한다.
# ============================================================

CUE_LOG = "_cue_log.txt"


def log_cues(user_text, reply, cues, extra=None):
    if not cues and not extra:
        return
    try:
        import datetime
        now = datetime.datetime.now().strftime("%m-%d %H:%M:%S")
        with open(CUE_LOG, "a", encoding="utf-8") as f:
            print(f"[{now}] 상대: {str(user_text)[:60]}", file=f)
            print(f"           다이아: {str(reply)[:60]}", file=f)
            for c in (cues or []):
                if c.get("type") == "motion":
                    bits = [f"몸짓 {c.get('key')}"]
                    if c.get("face"):
                        bits.append(f"+ 표정 {c.get('face')}")
                    if c.get("linger_ms"):
                        bits.append(f"머묾 {c.get('linger_ms')}ms")
                    if c.get("level"):
                        bits.append(f"{c.get('level')}단계")
                    print("           " + " ".join(bits), file=f)
                else:
                    print(f"           표정 {c.get('key')}", file=f)
            if extra:
                print(f"           {extra}", file=f)
            print("", file=f)
    except Exception:
        pass

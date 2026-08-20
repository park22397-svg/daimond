# avatar.py
# diamondAI - 버츄얼 아바타 단일 개체
#
# 이 파일이 만들어지기 전, 다이아는 두 개의 분리된 개체였다.
#
#   1) 페르소나  : ai_brain.py 안의 SYSTEM_PROMPT 문자열
#   2) 아바타     : templates/index.html 안의 VRM 로딩 + 표정 블렌드셰이프 코드
#
# 둘을 잇는 것은 /api/chat 응답의 "expression" 문자열 하나뿐이었고,
# 감정의 정의는 서로 다른 세 곳에 흩어져 중복되어 있었다.
#
#   - ai_brain.extract_expression()  : 이모지 -> 감정 (답변 전체의 감정)
#   - index.html applyExpression()   : 감정 -> 블렌드셰이프 수치
#   - index.html playLipSync()       : 이모지 -> 감정 (말하는 도중 글자별 전환)
#
# 이제 VirtualAvatar 하나가 이 모두를 소유한다.
# 페르소나는 아바타의 속성이며, 아바타 없이 따로 존재하지 않는다.


import os
import random
import re

from datetime import date

# 괄호로 적은 표시를 찾는다. ai_brain 의 것과 같은 규칙이라야
# '모델이 쓴 몸짓'과 '상대가 쓴 행동'의 판정이 어긋나지 않는다.
_BRACKET_RE = re.compile(r"[（(]\s*([^()（）]{1,20})\s*[)）]")


# ============================================================
# 이모지 판별
#
# 표정 신호에는 이모지와 한글 표현('ㅋㅋ', '좋아')이 섞여 있다.
# 화면에서 지우는 것은 이모지뿐이다. 한글은 평범한 말이라 그대로 둔다.
# ============================================================

def is_emoji(token):
    for ch in str(token):
        code = ord(ch)
        if (
            0x1F000 <= code <= 0x1FAFF      # 그림문자 전반
            or 0x2600 <= code <= 0x27BF     # 기타 기호 · 딩뱃
            or 0x2B00 <= code <= 0x2BFF
            or 0xFE0F == code               # 이모지 변형 선택자
        ):
            return True
    return False


# ============================================================
# 표정 하나의 정의
# ============================================================

class Expression:
    """
    아바타가 지을 수 있는 표정 하나.

    reply_emoji   : 답변 전체를 훑어 감정을 정할 때 쓰는 신호
    live_triggers : 말하는 도중 그 글자를 지나가는 순간 즉시 전환되는 신호
    blendshapes   : VRM 블렌드셰이프 이름 -> 가중치
    hold_ms       : live_trigger로 전환된 뒤 유지되는 시간
    """

    def __init__(
        self,
        key,
        label,
        blendshapes=None,
        reply_emoji=None,
        live_triggers=None,
        hold_ms=3000,
        auto_detect=None,
        auto_weight=0.8,
        fallback_blendshapes=None,
        is_reply_emotion=True,
        morphs=None,
        source="base",
        when=None,
    ):
        # 언제 짓는 얼굴인가. 사람의 말로 적는다.
        #
        # 신호 낱말은 '무엇이 나오면 짓는가' 만 말해 줄 뿐, 왜 그 얼굴인지는
        # 말해 주지 않는다. 그래서 뜻을 따로 적어 둔다.
        # 이 글은 모델에게도 그대로 건네진다 — 그래야 낱말이 안 걸린
        # 문장에서도 제 손으로 알맞은 얼굴을 고를 수 있다.
        self.when = when or ""
        # 어느 얼굴에서 짓는 표정인가.
        #   base    - 기본 얼굴(avatar.vrm)
        #   special - 표현용 얼굴(표현용.vrm). 같은 이름의 모프가 더 과장돼 있다.
        # 화면은 이 값을 보고 어느 얼굴을 보여줄지 정한다.
        self.source = source
        # VRM 이 겉으로 내주는 표정 그룹은 14개뿐인데,
        # 얼굴 메시에는 모프 타깃이 57개 들어 있다.
        # 나머지 43개는 눈썹·눈·입을 따로 움직이는 것들이라
        # 이걸 직접 건드리면 훨씬 많은 얼굴을 만들 수 있다.
        # (Fcl_EYE_Highlight_Hide — 눈에서 빛이 사라지는 그 표현)
        self.morphs = morphs or {}
        self.key = key
        self.label = label
        self.blendshapes = blendshapes or {}
        self.reply_emoji = reply_emoji or []
        self.live_triggers = live_triggers or []
        self.hold_ms = hold_ms
        # VRM 파일마다 이름이 다른 커스텀 표정을 런타임에 찾아 쓰는 경우
        self.auto_detect = auto_detect
        self.auto_weight = auto_weight
        self.fallback_blendshapes = fallback_blendshapes or {}
        # 서버가 답변 전체의 감정으로 되돌려줄 수 있는 표정인지
        self.is_reply_emotion = is_reply_emotion

    def to_dict(self):
        return {
            "key": self.key,
            "label": self.label,
            "blendshapes": self.blendshapes,
            "reply_emoji": self.reply_emoji,
            "live_triggers": self.live_triggers,
            "when": self.when,
            "hold_ms": self.hold_ms,
            "auto_detect": self.auto_detect,
            "auto_weight": self.auto_weight,
            "fallback_blendshapes": self.fallback_blendshapes,
            "is_reply_emotion": self.is_reply_emotion,
            "morphs": self.morphs,
            "source": self.source,
        }


# ============================================================
# 동작 하나의 정의
#
# 키프레임은 '절대 자세'로 적는다.
# 어떤 키에서도 언급되지 않은 본은 base_pose 값을 그대로 쓴다.
# (0으로 떨어뜨리면 T포즈로 튀어버리므로)
#
# 각도 단위는 도(degree). 이 VRM(0.x) 기준 부호는 다음과 같다.
#   - 왼팔 내리기  : leftUpperArm  z = +68
#   - 오른팔 내리기: rightUpperArm z = -68
#   - 오른팔 올리기: rightUpperArm z 를 양수 방향으로
# ============================================================

class Motion:

    def __init__(
        self,
        key,
        label,
        duration,
        keys,
        loop=False,
        ease="easeInOut",
        expression=None,
        expression_ms=None,
        expression_force=False,
        hold_t=None,
        linger_ms=0,
        locomotes=False,
        description="",
        turn_yaw=0,
    ):
        self.key = key
        self.label = label
        self.duration = duration
        self.keys = keys
        self.loop = loop
        self.ease = ease
        # 이 동작을 할 때 함께 지을 표정 (페르소나와 몸이 한 개체라 가능해진 연결)
        self.expression = expression
        # 그 얼굴을 몇 ms 나 지을지. 안 적으면 동작이 끝날 때까지다.
        #
        # 데려온 얼굴은 데려간 쪽이 치워야 한다. 예전에는 치우는 데가 없어서
        # 손을 내린 뒤에도 놀란 얼굴이 다음 무언가가 덮을 때까지 남았다.
        self.expression_ms = expression_ms
        # 동작 중간에 잠시 멈춰 서는 자리와 그 길이.
        #
        # 등을 돌린 채 얼마나 있을지는 마음의 크기가 정한다. 키프레임을
        # 마음마다 새로 만들 수는 없으니, 재생을 그 지점에서 잠깐 세운다.
        self.hold_t = hold_t
        self.linger_ms = linger_ms

        # 이 표정은 '아무 얼굴도 안 하고 있을 때'만 걸린다.
        #
        # 팔짱과 등 돌리기는 삐죽만의 몸짓이 아니다. 화가 나서 팔짱을
        # 끼기도 하고, 서운해서 등을 돌리기도 한다. 반대로 삐죽은
        # 이 두 몸짓과만 같이 나온다 — 혼자 쓰면 어색하기 때문이다.
        #
        # 그래서 규칙을 하나로 뒀다. 이미 지어진 얼굴이 있으면 동작은
        # 얼굴을 건드리지 않는다. 자리가 정한 표정이 늘 이긴다.
        #
        # 다만 얼굴이 곧 그 동작인 몸짓이 있다. 쑥스러워하기와 얼굴
        # 가리기가 그렇다 — 웃으면서 얼굴을 가리면 무엇을 하는지 알 수
        # 없다. 그런 동작은 표정을 반드시 데려온다.
        self.expression_force = expression_force
        # 재생 중 실제로 위치가 움직이는 동작인지
        self.locomotes = locomotes
        # 재생 중 몸 전체가 도는 각도(도).
        # 뼈로는 몸을 반 바퀴 돌릴 수 없다. 척추를 150도 비트는 사람은 없다.
        # 그래서 이건 화면이 아바타를 통째로 돌려 준다.
        self.turn_yaw = turn_yaw
        self.description = description

    def channels(self):
        names = set()
        for k in self.keys:
            names.update(k.get("bones", {}).keys())
        return sorted(names)

    def to_dict(self):
        return {
            "key": self.key,
            "label": self.label,
            "duration": self.duration,
            "loop": self.loop,
            "ease": self.ease,
            "expression": self.expression,
            "expression_ms": self.expression_ms,
            "expression_force": self.expression_force,
            "hold_t": self.hold_t,
            "linger_ms": self.linger_ms,
            "locomotes": self.locomotes,
            "turn_yaw": self.turn_yaw,
            "description": self.description,
            "channels": self.channels(),
            "keys": self.keys,
        }


# ============================================================
# 관계 단계
#
# 다이아는 상대와의 관계가 미리 정해져 있지 않다.
# 상대가 어떻게 대하느냐에 따라 친밀도가 오르내리고,
# 그 값이 지금 어떤 사이인지와 말투를 결정한다.
# ============================================================

class Stage:

    def __init__(self, key, label, min_affinity, speech, attitude,
                 first_talk=None, silent=False, never_falls=False,
                 morphs=None, no_negative=False, never_sleeps=False,
                 keeps_talking=False):
        # 이 단계에 있는 동안 늘 걸려 있는 얼굴.
        # 표정이 바뀌어도 지워지지 않는다.
        # (얀데레의 빈 눈 — 무슨 표정을 지어도 눈에 빛이 없다)
        self.morphs = morphs or {}
        self.key = key
        self.label = label
        self.min_affinity = min_affinity
        # 이 단계에서는 아예 대답하지 않는다.
        # 모델을 부르지 않으므로 답이 나올 일도 없다.
        self.silent = silent
        # 여기까지 오면 친밀도가 더는 깎이지 않는다.
        # 무슨 짓을 해도 마음이 식지 않는 상태다.
        self.never_falls = never_falls
        # 이 단계에서는 부정적인 표현이 나오지 않는다.
        # 화난 얼굴도, 팔짱도, 등을 돌리는 것도 없다.
        # 옷을 잡아당겨도 웃는다. 화가 안 나는 게 아니라
        # 그런 걸로 마음이 흔들리지 않는 상태다.
        self.no_negative = no_negative
        # 잠들지 않는다. 상대가 조용해도 눈을 감지 않는다.
        self.never_sleeps = never_sleeps
        # 대답이 없어도 혼자 말을 잇는다.
        # 정해둔 문장을 꺼내는 게 아니라 그때그때 생각해서 말한다.
        self.keeps_talking = keeps_talking
        # 존댓말/반말 등 말투 규칙
        self.speech = speech
        # 그 사이에서 상대를 대하는 태도
        self.attitude = attitude
        # 상대가 한동안 말이 없을 때 먼저 건네는 말.
        # 사이가 달라지면 먼저 거는 말의 온도도 달라진다.
        self.first_talk = first_talk or []

    def to_dict(self):
        return {
            "key": self.key,
            "label": self.label,
            "min_affinity": self.min_affinity,
            "speech": self.speech,
            "attitude": self.attitude,
            "first_talk": self.first_talk,
            "silent": self.silent,
            "never_falls": self.never_falls,
            "no_negative": self.no_negative,
            "never_sleeps": self.never_sleeps,
            "keeps_talking": self.keeps_talking,
            "morphs": self.morphs,
        }


# ============================================================
# 만지는 자리
#
# 마우스로 아바타를 눌렀을 때, 어디를 만졌는지에 따라 반응이 달라진다.
# 어느 자리인지는 화면이 정하지 않는다. 닿은 지점에서 가장 가까운 본을
# 찾아 서버에 알려주면, 그 본이 어느 자리에 속하는지는 이 표가 정한다.
#
# allow_from 은 그 자리를 만지도록 허락하는 친밀도다.
# 아직 그만한 사이가 아닌데 만지면 거부하고 친밀도가 깎인다.
# 사이가 깊어질수록 만질 수 있는 곳이 늘어나는 셈이다.
# ============================================================

class TouchZone:

    def __init__(
        self,
        key,
        label,
        bones,
        tap=None,
        pet=None,
        kiss=None,
        deny=None,
        allow_from=None,
        cloth=False,
        allow_stages=None,
        hidden=False,
        silent=False,
        random_peak=False,
    ):
        self.key = key
        self.label = label
        self.bones = list(bones)
        # 옷자리는 본이 아니라 판정구가 직접 알려준다.
        # 그리고 잡는 도구로만 닿는다. 안 그러면 소매가 팔을 덮어
        # 팔을 만질 수 없게 된다.
        self.cloth = cloth
        # 한 번 누름 / 문지름. 각각 expression, motion, affinity, lines 를 갖는다.
        self.tap = tap or {}
        self.pet = pet or self.tap
        # 입을 맞출 때. 눈을 감고 기다리는 중에 입술이 닿아야 여기로 온다.
        # 그냥 뽀뽀(tap)와 다른 것이라 따로 갖는다.
        self.kiss = kiss or {}
        # 아직 허락되지 않은 사이에서 만졌을 때
        self.deny = deny or {}
        self.allow_from = allow_from
        # 친밀도가 아니라 '어느 단계인가'로 허락되는 자리.
        # 숫자로는 표현이 안 된다 — 광기와 얀데레 사이에는 어떤 값도 없다.
        self.allow_stages = list(allow_stages or [])
        # 만질 수 있는 곳 목록에 이름을 내지 않는다
        self.hidden = hidden
        # 말이 없다. 얼굴로만 답한다
        self.silent = silent
        # 절정 표정 중 하나를 그때그때 고른다
        self.random_peak = random_peak

    def to_dict(self):
        return {
            "key": self.key,
            "label": self.label,
            "bones": self.bones,
            "allow_from": self.allow_from,
            "allow_stages": self.allow_stages,
            "hidden": self.hidden,
            "silent": self.silent,
            "cloth": self.cloth,
        }


# ============================================================
# 무엇으로 만지는가
#
# 같은 자리를 만져도 손으로 만지는 것과 입을 맞추는 것은 다르다.
# 자리(TouchZone)와 도구(TouchTool)를 곱해서 반응이 정해진다.
#
# 자리마다 도구마다 대사를 다 적으면 9 x 4 = 36 벌이 되어 관리가 안 된다.
# 그래서 도구는 '자리의 반응을 어떻게 비틀지'만 갖는다.
#   allow_bonus    : 이 도구로 만지려면 그만큼 더 가까운 사이여야 한다
#   affinity_scale : 친밀도 변화를 몇 배로
#   lines          : 자리별 대사. 없으면 default, 그것도 없으면 자리의 대사를 쓴다
# ============================================================

class TouchTool:

    def __init__(
        self,
        key,
        label,
        icon,
        allow_bonus=0,
        affinity_scale=1.0,
        expression=None,
        motion=None,
        lines=None,
        deny=None,
        description="",
        grabs_cloth=False,
    ):
        self.key = key
        self.label = label
        self.icon = icon
        # 옷을 잡을 수 있는 도구인가
        self.grabs_cloth = grabs_cloth
        self.allow_bonus = allow_bonus
        self.affinity_scale = affinity_scale
        # 도구가 표정·동작을 정해 두면 자리의 것보다 우선한다
        self.expression = expression
        self.motion = motion
        self.lines = lines or {}
        self.deny = deny or {}
        self.description = description

    def lines_for(self, zone_key):
        return self.lines.get(zone_key) or self.lines.get("default")

    @staticmethod
    def with_ro(word):
        """'로' 인가 '으로' 인가. 받침이 있으면 '으로'.

        '자지로' 를 '자지으로' 라고 적으면 모델이 그 어색함을 따라 쓴다.
        (ㄹ 받침은 '로' 를 쓴다 — '연필로')
        """
        if not word:
            return ""
        last = word[-1]
        if not ("가" <= last <= "힣"):
            return word + "로"
        jong = (ord(last) - 0xAC00) % 28
        return word + ("로" if jong in (0, 8) else "으로")

    @staticmethod
    def with_eul(word):
        """'을' 인가 '를' 인가."""
        if not word:
            return ""
        last = word[-1]
        if not ("가" <= last <= "힣"):
            return word + "를"
        jong = (ord(last) - 0xAC00) % 28
        return word + ("을" if jong else "를")

    def label_for(self, zone_key):
        """그 자리에서 이 도구를 뭐라고 부르는가.

        같은 손가락이라도 어디에 닿느냐에 따라 다른 것이 된다.
        자리마다 적어 두지 않았으면 본디 이름을 쓴다.
        """
        spec = self.lines.get(zone_key)
        if isinstance(spec, dict) and spec.get("label"):
            return spec["label"]
        return self.label

    def to_dict(self):
        return {
            "key": self.key,
            "label": self.label,
            "icon": self.icon,
            "allow_bonus": self.allow_bonus,
            "description": self.description,
            "grabs_cloth": self.grabs_cloth,
        }


# ============================================================
# 버츄얼 아바타 = 몸(VRM) + 표정 + 동작 + 관계 + 페르소나
# ============================================================

def _env(name, fallback):
    """환경변수가 있으면 그것을, 없으면 정해 둔 값을.

    올린 데와 내 컴퓨터가 서로 다른 자리를 가리켜야 할 때 쓴다.
    """
    return os.environ.get(name, "").strip() or fallback


class VirtualAvatar:

    def __init__(
        self,
        avatar_id,
        name,
        identity,
        persona,
        model,
        expressions,
        behavior,
        model_parts=None,
        model_splits=None,
        base_pose=None,
        motions=None,
        locomotion=None,
        vision=None,
        time_sense=None,
        pregnancy=None,
        cleavage=None,
        relationship=None,
        touch=None,
        game=None,
    ):
        self.game = game or {}
        self.relationship = relationship or {}
        self.id = avatar_id
        self.name = name
        self.identity = identity
        self.persona = persona
        self.model = model
        # 어느 메시가 몸이고 어느 것이 옷인지 (삼각형 수로 찾는다)
        self.model_parts = model_parts or []
        self.model_splits = model_splits or []
        self.expressions = expressions
        self.behavior = behavior
        # 서 있을 때의 기준 자세. 모든 동작이 여기서 출발한다.
        self.base_pose = base_pose or {}
        self.motions = motions or []
        self.locomotion = locomotion or {}
        # 눈. 카메라가 켜져 있으면 그것이 다이아의 눈이다.
        self.vision = vision or {}
        # 시간. 몇 시인지, 며칠 만인지.
        self.time_sense = time_sense or {}
        # 아이가 선 뒤 배가 불러 오는 정도. 화면이 정점을 미는 데 쓴다.
        self.pregnancy = pregnancy or {}
        # 가슴골. 불러들일 때 한 번만 판다.
        self.cleavage = cleavage or {}
        self.touch = touch or {}

    def motion(self, key):
        for m in self.motions:
            if m.key == key:
                return m
        return None

    # --------------------------------------------------------
    # 만지기
    #
    # 화면은 '어느 본에 가장 가까운 곳을 눌렀는가' 만 알려준다.
    # 그 자리가 머리인지 얼굴인지, 만져도 되는 사이인지,
    # 무슨 말을 하고 어떤 표정을 지을지는 전부 여기서 정한다.
    # --------------------------------------------------------

    def touch_zones(self):
        return self.touch.get("zones", [])

    def touch_zone(self, key):
        for z in self.touch_zones():
            if z.key == key:
                return z
        return None

    def zone_for(self, bone, local=None, zone_key=None, tool=None):
        """닿은 본과 그 본의 좌표계에서의 위치로 자리를 정한다.

        머리는 본이 하나뿐이라 본 이름만으로는 정수리와 얼굴을 못 가른다.
        그래서 머리에 한해 닿은 지점의 위치를 보고 나눈다.

        옷은 본이 아니라 재질이라 본 이름으로는 배와 치마를 못 가른다.
        그래서 옷 판정구는 자기가 어느 자리인지(zone_key)를 직접 들고 온다.
        다만 옷은 잡는 도구로만 닿는다. 안 그러면 소매가 팔을 덮어
        팔을 만질 수 없게 된다. 그때는 안쪽 몸으로 넘긴다.
        """
        if zone_key:
            z = self.touch_zone(zone_key)
            if z is not None:
                if not z.cloth or (tool is not None and tool.grabs_cloth):
                    return z

        if not bone:
            return None

        # 가슴 위쪽 본 하나가 어깨부터 가슴까지 걸쳐 있다.
        # 가운데에서 얼마나 벗어났는지로 가른다.
        if bone == "upperChest" and local:
            cut = self.touch.get("chest_split", {})
            side = abs(local[0]) >= cut.get("side_x", 0.07)
            z = self.touch_zone(
                cut.get("zone_side" if side else "zone_front"))
            if z is not None:
                return z

        # 골반은 본이 하나뿐이라 배와 그 아래를 못 가른다.
        # 머리를 정수리와 얼굴로 가르는 것과 같은 방식으로 나눈다.
        # 가운데(x)에서, 배꼽 아래(y)에서, 앞쪽(z)일 때만 그 자리다.
        if bone == "hips" and local:
            cut = self.touch.get("hips_split", {})
            z = self.touch_zone(cut.get("zone", "pelvis"))
            if z is not None                     and abs(local[0]) <= cut.get("half_x", 0.06)                     and local[1] <= cut.get("below_y", -0.05)                     and local[2] <= cut.get("front_z", -0.01):
                return z

        if bone == "head" and local:
            cut = self.touch.get("head_split", {})

            if local[1] >= cut.get("top_y", 0.13):
                return self.touch_zone("head")

            # 입은 얼굴 안에서 다시 가른다.
            # 눈보다 아래이고, 앞쪽이고, 가운데일 때다.
            mouth = self.touch_zone("mouth")
            if mouth is not None                     and local[1] <= cut.get("mouth_y", -0.005)                     and local[2] <= cut.get("mouth_z", -0.05)                     and abs(local[0]) <= cut.get("mouth_x", 0.05):
                return mouth

            if local[2] <= cut.get("front_z", -0.02):
                return self.touch_zone("face")
            return self.touch_zone("head")

        for z in self.touch_zones():
            if bone in z.bones:
                return z
        return None






    # --------------------------------------------------------
    # 기분
    #
    # 친밀도와 다르다. 친밀도는 둘이 얼마나 가까운지이고,
    # 기분은 지금 이 순간 상해 있는지다. 사이가 아무리 좋아도
    # 방금 심한 말을 들었으면 상해 있을 수 있다.
    #
    # 시간이 지나면 저절로 풀린다. 그 계산을 여기서 한다 —
    # 뒤에서 도는 시계를 두지 않고, 읽을 때마다 지난 시간을 재서 깎는다.
    # --------------------------------------------------------

    def mood_conf(self):
        return self.behavior.get("mood", {})

    def mood_now(self, raw, since, now):
        """저절로 풀린 만큼을 뺀 지금의 기분."""
        conf = self.mood_conf()
        cool = max(1, conf.get("cool_sec", 180))

        raw = max(0, int(raw or 0))
        if raw <= 0:
            return 0
        if since is None:
            return raw

        gone = int(max(0, now - since) // cool)
        return max(0, raw - gone)

    def mood_clamp(self, value):
        return max(0, min(self.mood_conf().get("max", 6), int(value)))

    def mood_tier(self, level):
        """그만큼 상했을 때 어떤 얼굴·태도인지. 안 상했으면 None."""
        if level <= 0:
            return None
        found = None
        for lv in self.mood_conf().get("levels", []):
            if level >= lv.get("at", 0):
                found = lv
        return found

    def mood_soothe(self, zone_key, allowed):
        """쓰다듬었을 때 기분이 얼마나 풀리는지. 음수면 더 상한다."""
        conf = self.mood_conf().get("soothe", {})
        if not allowed:
            return conf.get("denied", -2)
        zones = conf.get("zones", {})
        return zones.get(zone_key, conf.get("default", 1))

    def mood_reply(self, level, before, stage):
        """기분이 움직인 뒤에 할 말과 얼굴.

        풀린 경우에만 돌려준다. 더 상했을 때는 자리의 반응이 이미 있다.
        """
        if level >= before:
            return None

        conf = self.mood_conf()
        polite = stage is None or str(stage.speech).startswith("존댓말")
        key = "polite" if polite else "casual"

        spec = conf.get("clear", {}) if level <= 0 else None
        if spec is None:
            tier = self.mood_tier(level)
            spec = (tier or {}).get("soothed", {})

        pool = (spec.get("lines", {}) or {}).get(key) or []
        if not pool:
            return None

        return {
            "reply": random.choice(pool),
            "expression": spec.get("expression"),
            "motion": spec.get("motion"),
            "cleared": level <= 0,
        }

    def walk_invite(self, text):
        """같이 걷자는 말인지. 'start' / 'stop' / None."""
        conf = self.behavior.get("walk_invite", {})
        low = str(text or "").lower()

        # 멈추자는 말이 먼저다. '그만 걷자' 에 '걷' 이 들어 있기 때문이다.
        for w in conf.get("stop", []):
            if w in low:
                return "stop"
        for w in conf.get("start", []):
            if w in low:
                return "start"
        return None

    def come_invite(self, text):
        """가까이 오라는 말인지. 'near' / 'away' / None."""
        conf = self.behavior.get("come_closer", {})
        low = str(text or "").lower()

        # 물러나라는 말이 먼저다. '좀 떨어져 있어' 에 '있어' 가 들어 있다.
        for w in conf.get("away", []):
            if w in low:
                return "away"
        for w in conf.get("near", []):
            if w in low:
                return "near"
        return None

    def asks_understood(self, text):
        """상대가 '알겠어?' 하고 확인하는 말인지. 맞으면 동작 이름."""
        conf = self.behavior.get("understood", {})
        low = str(text or "").lower().replace(" ", "")
        for w in conf.get("words", []):
            if w.replace(" ", "") in low:
                return conf.get("motion", "nod")
        return None

    # --------------------------------------------------------
    # 상처받았을 때
    #
    # 슬픔·화남·삐침 중 어느 쪽으로 기우는지를 말이 정한다.
    # 등을 돌린 채 얼마나 있을지도 여기서 나온다.
    # --------------------------------------------------------

    def hurt_reaction(self, text):
        """그 말이 어떤 상처인지. 해당 없으면 None."""
        low = str(text or "").lower()
        for h in self.behavior.get("hurt", []):
            if any(w in low for w in h.get("words", [])):
                return dict(h)
        return None


    # --------------------------------------------------------
    # 얼굴을 이름으로 부르기
    #
    # 지금까지 괄호 안에 넣을 수 있는 것은 몸짓뿐이었다. 표정은 이모지로만
    # 정할 수 있었는데, 이모지에 없는 얼굴(째려보기·새침·체념 같은)은
    # 부를 방법이 아예 없었다.
    #
    # 만화의 얼굴은 감정 하나에 대응되지 않는다. 그래서 이모지로는 못
    # 고르고 이름으로 불러야 한다. (표정: 째려보기) 처럼 쓴다.
    # --------------------------------------------------------

    def expression_cue_map(self):
        m = {}
        for e in self.expressions:
            if e.key == "neutral":
                continue
            m[e.key] = e.key
            if e.label:
                m[e.label] = e.key
                m[e.label.replace(" ", "")] = e.key
        return m

    # --------------------------------------------------------
    # 쑥스러움의 세기
    #
    # 같은 '쑥스럽다'도 정도가 다르다. 말끝에 슬쩍 붙이는 것과
    # 얼굴을 못 들 만큼인 것이 같은 몸짓일 수는 없다.
    # 세기는 문장이 정한다. 센 말부터 차례로 본다.
    # --------------------------------------------------------

    def shy_level(self, text):
        """그 문장의 쑥스러움이 어느 세기인지.

        반환: {"level", "motion", "expression"} — 못 찾으면 가장 낮은 단계.
        """
        levels = self.behavior.get("shy_levels", [])
        if not levels:
            return None

        low = str(text or "").lower()

        for lv in levels:
            if any(w in low for w in lv.get("words", [])):
                return {
                    "level": lv.get("level"),
                    "motion": lv.get("motion"),
                    "expression": lv.get("expression"),
                }

        last = levels[-1]
        return {
            "level": last.get("level"),
            "motion": last.get("motion"),
            "expression": last.get("expression"),
        }

    def act_reaction(self, text):
        """괄호 속 상황 한 마디를 얼굴과 몸으로 옮긴다.

        (멋쩍은 듯 눈동자가 흔들리며) -> 쑥스러워하기 + 그 세기의 얼굴
        (팔짱을 낀 채)               -> 팔짱
        (창밖을 오래 본다)            -> 지그시 보기

        반환: {"expression": key|None, "motion": key|None} — 못 읽으면 None.

        읽지 못하는 문장이 훨씬 많다. 그래도 괜찮다 —
        못 읽으면 글자로만 나오고, 그것은 지금까지와 같다.
        억지로 아무 얼굴이나 붙이는 것이 못 읽는 것보다 나쁘다.
        """

        low = str(text or "").lower()

        if not low:
            return None

        # 쑥스러움은 세기가 있다. 그 갈래를 여기서 다시 만들지 않고
        # 이미 있는 판단으로 넘긴다.
        shy_words = self.behavior.get("act_shy_words", [])

        expr = None
        motion = None

        if any(w in low for w in shy_words):
            lv = self.shy_level(low) or {}
            expr = lv.get("expression")
            motion = lv.get("motion")

            # 낮은 세기의 쑥스러움은 얼굴을 안 정한다(웃으면서 쑥스러워한다).
            # 그때 여기서 끝내면 **몸만 움직이고 얼굴은 가만히 있는다** —
            # 고치려던 것이 바로 그것이다. 아래로 내려가 얼굴을 마저 찾는다.
            #   (멋쩍은 듯 눈동자가 흔들리며) -> 쑥스러워하기 + 당황
            if expr and motion:
                return {"expression": expr, "motion": motion}

        for rule in self.behavior.get("act_reads", []):
            if not any(w in low for w in rule.get("words", [])):
                continue

            e = rule.get("expression")
            m = rule.get("motion")

            # 표에 적힌 이름이 실제로 있는지 본다.
            # 이름을 고치고 표를 안 고치면 조용히 아무 일도 안 일어난다.
            if e and not self.expression(e):
                e = None

            if m and not self.motion(m):
                m = None

            if not e and not m:
                continue

            # 쑥스러움이 이미 정한 것은 덮지 않는다.
            # 비어 있는 자리만 채운다.
            return {
                "expression": expr or e,
                "motion": motion or m,
            }

        if expr or motion:
            return {"expression": expr, "motion": motion}

        return None

    def shy_motions(self):
        return {lv.get("motion") for lv in self.behavior.get("shy_levels", [])}

    # --------------------------------------------------------
    # 가위바위보
    #
    # 무엇을 낼지, 이겼을 때 뭐라고 할지, 친밀도가 얼마나 움직일지를
    # 전부 개체가 정한다. 화면은 사람이 낸 것만 보낸다.
    # --------------------------------------------------------

    def rps(self):
        return self.game.get("rps", {})

    def rps_hands(self):
        return self.rps().get("hands", [])

    def rps_hand(self, key):
        for h in self.rps_hands():
            if h["key"] == key:
                return h
        return None

    def rps_hand_pose(self, key):
        """그 손 모양의 손가락 값만 꺼낸다.

        손 모양은 동작 키프레임 안에 들어 있다. 따로 적어 두면 둘이
        어긋나므로, 실제로 재생되는 그 키에서 꺼내 쓴다.
        리깅 확인대(/rig)가 이 값을 불러 손 모양을 고치는 데 쓴다.
        """
        h = self.rps_hand(key)
        if h is None:
            return {}

        m = self.motion(h.get("motion"))
        if m is None:
            return {}

        want = self.rps().get("reveal_t", 1.35)
        chosen = None
        for k in m.keys:
            if abs(k.get("t", -1) - want) < 1e-6:
                chosen = k
                break
        if chosen is None:
            return {}

        parts = ("Thumb", "Index", "Middle", "Ring", "Little")
        return {
            b: list(v) for b, v in chosen.get("bones", {}).items()
            if any(p in b for p in parts)
        }

    def rps_play(self, user_key, stage=None, affinity=0):
        """사람이 낸 것을 받아 다이아가 낼 것을 정하고 결과를 돌려준다."""

        hands = self.rps_hands()
        mine = self.rps_hand(user_key)
        if not hands or mine is None:
            return None

        cfg = self.rps()

        # 사이가 깊으면 가끔 일부러 져 준다. 티는 내지 않는다.
        mercy_from = cfg.get("mercy_from")
        mercy = cfg.get("mercy_chance", 0.0)

        pick = None
        if mercy_from is not None and affinity >= mercy_from \
                and random.random() < mercy:
            # 사람이 이기는 손 = 사람이 낸 것에게 지는 손
            pick = next(
                (h for h in hands if mine["beats"] == h["key"]),
                None
            )

        if pick is None:
            pick = random.choice(hands)

        if pick["key"] == mine["key"]:
            result = "draw"
        elif mine["beats"] == pick["key"]:
            result = "lose"          # 다이아가 졌다
        else:
            result = "win"           # 다이아가 이겼다

        polite = stage is None or str(stage.speech).startswith("존댓말")
        spec = cfg.get("outcomes", {}).get(result, {})
        pool = (spec.get("lines", {}) or {}).get(
            "polite" if polite else "casual") or []

        return {
            "you": mine["key"],
            "you_label": mine["label"],
            "mine": pick["key"],
            "mine_label": pick["label"],
            "motion": pick.get("motion"),
            "result": result,
            "reply": random.choice(pool) if pool else "",
            "expression": spec.get("expression", "neutral"),
            "affinity_delta": spec.get("affinity", 0),
        }

    # --------------------------------------------------------
    # 글로 만지기
    #
    # 상대가 괄호로 쓴 행동을 읽어 '어느 자리를 어느 도구로' 인지 알아낸다.
    # 알아낸 뒤의 반응은 마우스로 만졌을 때와 똑같은 표가 만든다.
    # 모르는 행동은 None 을 돌려주고, 그건 모델이 상황으로 받는다.
    # --------------------------------------------------------

    def parse_action(self, text):
        """괄호 안의 행동을 읽는다.

        반환: (알아들은 것들, 괄호를 걷어낸 본문)
          알아들은 것 = {"raw", "zone", "tool", "kind"}
          zone 이 None 이면 뜻은 모르지만 행동이라는 것만 안다.
        """
        if not text:
            return [], ""

        conf = self.touch.get("actions", {})
        found = []
        out = []
        i = 0
        n = len(text)

        while i < n:
            m = _BRACKET_RE.match(text, i)
            if not m:
                out.append(text[i])
                i += 1
                continue

            inner = m.group(1).strip()
            found.append(self._read_action(inner, conf))

            i = m.end()
            while i < n and text[i] == " " and (not out or out[-1] == " "):
                i += 1

        clean = re.sub(r"[ \t]{2,}", " ", "".join(out)).strip()
        return found, clean

    def _read_action(self, inner, conf):
        """괄호 하나를 읽어 자리와 도구를 정한다.

        어디를 만지는지 먼저 찾는다. 적혀 있으면 그게 우선이다 —
        '손등에 뽀뽀한다'는 얼굴이 아니라 손이다.
        자리를 안 적었을 때만 행동 자체가 자리를 정한다(안아준다 -> 어깨).
        """
        low = inner.lower()

        zone = None
        for p in conf.get("places", []):
            if any(word in low for word in p["words"]):
                zone = p["zone"]
                break

        tool = conf.get("default_tool", "hand")
        kind = conf.get("default_kind", "tap")
        matched = False

        for v in conf.get("verbs", []):
            if any(word in low for word in v["words"]):
                tool = v["tool"]
                kind = v["kind"]
                matched = True
                break

        if zone is None:
            for w in conf.get("whole", []):
                if any(word in low for word in w["words"]):
                    return {
                        "raw": inner,
                        "zone": w["zone"],
                        "tool": w["tool"],
                        "kind": w["kind"],
                    }

        # 자리도 행동도 못 알아들었으면 그냥 상황 설명이다
        if zone is None and not matched:
            return {"raw": inner, "zone": None, "tool": None, "kind": None}

        return {"raw": inner, "zone": zone, "tool": tool, "kind": kind}

    def touch_tools(self):
        return self.touch.get("tools", [])

    def touch_tool(self, key):
        for t in self.touch_tools():
            if t.key == key:
                return t
        tools = self.touch_tools()
        return tools[0] if tools else None

    def touch_reaction(self, zone, kind, stage, affinity, count=1, tool=None):
        """이 자리를 이 도구로 이렇게 만졌을 때 무엇을 할지.

        kind  : "tap" 한 번 누름 / "pet" 문지름
        count : 문지른 횟수. 같은 말만 반복하지 않도록 고르는 데 쓴다.
        tool  : 무엇으로 만지는가. 없으면 첫 번째 도구(맨손)로 본다.
        """
        if zone is None:
            return None

        if tool is None:
            tool = self.touch_tool(None)

        bonus = tool.allow_bonus if tool else 0

        # 어느 단계에서만 허락되는 자리가 있다.
        # 그런 자리는 친밀도 숫자를 보지 않는다 — 단계가 곧 조건이다.
        # 광기와 얀데레 사이에는 어떤 숫자도 없어서 숫자로는 적을 수 없다.
        if zone.allow_stages:
            allowed = stage is not None and stage.key in zone.allow_stages
        else:
            allowed = (zone.allow_from is None and bonus <= 0) or \
                      affinity >= ((zone.allow_from or 0) + bonus)

        if not allowed:
            spec = zone.deny
        elif kind == "kiss":
            # 키스 자리를 안 적어 둔 곳이면 그냥 누른 것으로 본다
            spec = zone.kiss or zone.tap
        elif kind == "pet":
            spec = zone.pet
        else:
            spec = zone.tap

        if not spec:
            return None

        polite = stage is None or str(stage.speech).startswith("존댓말")

        # 도구가 이 자리에 할 말을 따로 가지고 있으면 그것을 먼저 쓴다
        lines = None
        if tool:
            lines = tool.deny if not allowed else tool.lines_for(zone.key)

        # 키스는 자리가 통째로 쥔다. 도구의 말은 '입술로 여기를 만졌다'
        # 는 뜻이라 기다렸다 입을 맞추는 자리와는 결이 다르다.
        if allowed and kind == "kiss" and spec.get("lines"):
            lines = None

        if not lines:
            lines = spec.get("lines", {})

        pool = lines.get("polite" if polite else "casual") or []

        if pool:
            # 같은 자리를 계속 만지면 다른 말이 나오도록 순서를 돌린다
            reply = pool[(max(1, int(count)) - 1) % len(pool)] if kind == "pet" \
                else random.choice(pool)
        else:
            reply = ""

        # 한 줄만 표정이 다를 수 있다.
        # '눈 감을게'와 '이러면 나 진짜 못 참아'는 같은 자리에서 나오지만
        # 지어야 할 얼굴이 다르다. 그래서 줄에 직접 붙일 수 있게 해 둔다.
        line_face = None
        line_motion = None
        if isinstance(reply, dict):
            line_face = reply.get("expression")
            if "motion" in reply:
                line_motion = reply.get("motion")
            reply = reply.get("text", "")

        delta = spec.get("affinity", 0)
        if tool and allowed:
            delta = int(round(delta * tool.affinity_scale))

        # 사이가 깊어지면 같은 자리라도 얼굴이 달라진다.
        #
        # 낯선 사이에서 배나 다리를 만지면 놀란다. 그 놀람이 오래 남으면
        # 아무리 가까워져도 늘 놀라기만 하는 사람이 된다.
        # 그래서 자리마다 '사이가 깊을 때의 얼굴'을 따로 적을 수 있게 했다.
        # 경계값은 자리마다 따로 적을 수 있다. 안 적었으면 공통값을 쓴다.
        # 옷과 발처럼 만지면 화내는 자리는 훨씬 더 깊어져야 웃는다.
        warm_from = spec.get("warm_from", self.touch.get("warm_from"))
        warm = (warm_from is not None and affinity >= warm_from
                and spec.get("expression_warm"))

        expression = spec.get("expression_warm") if warm             else spec.get("expression", "neutral")

        # 표정이 둘 이어질 수도 있다.
        #
        # 손을 잡히면 먼저 놀라고, 곧 좋아하는 얼굴이 된다.
        # 한 얼굴로는 그 흐름이 안 나온다.
        then = spec.get("expression_then")

        # 여럿 적어 두면 그때그때 하나를 고른다.
        # 쓰다듬을 때마다 똑같은 얼굴이면 인형처럼 보인다.
        if isinstance(expression, (list, tuple)):
            expression = random.choice(list(expression)) if expression else "neutral"

        # 사이가 깊을 때는 몸짓도 달라진다.
        # 쑥스러워하기는 놀란 얼굴과 한 몸이라, 웃는 자리에서는 쓸 수 없다.
        motion = spec.get("motion_warm") if warm and spec.get("motion_warm")             else spec.get("motion")

        # 키스는 자리가 통째로 쥔다.
        #
        # 도구(입술)는 평소 자리의 반응을 비트는 역할이지만, 여기서는
        # 자리 쪽이 이 순간만을 위해 적힌 것이라 도구가 끼어들면
        # 애써 적은 얼굴이 도구의 기본 얼굴로 덮인다.
        if tool and allowed and kind == "kiss" and zone.kiss:
            pass
        elif tool and allowed:
            expression = tool.expression or expression
            motion = tool.motion or motion

            # 자리마다 따로 정한 것이 있으면 그게 우선이다.
            # '눈 감을게' 라고 해 놓고 쑥스러워하기 동작이 나오면 말과 몸이 어긋난다.
            if isinstance(lines, dict):
                if "expression" in lines:
                    expression = lines["expression"]
                if "motion" in lines:
                    motion = lines["motion"]

        # 줄에 직접 붙은 것이 가장 세다
        if line_face:
            expression = line_face
        if line_motion is not None:
            motion = line_motion

        # 절정 표정 중 하나를 그때그때 고른다.
        # 어느 얼굴이 나올지 정해 두지 않는 것이 이 자리의 뜻이다.
        if allowed and zone.random_peak:
            peaks = [e.key for e in self.expressions
                     if getattr(e, "source", "base") == "special"]
            if peaks:
                expression = random.choice(peaks)

        # 말이 없는 자리. 얼굴로만 답한다.
        if zone.silent:
            reply = ""

        # 허락되지 않은 자리를 건드리면 사이가 통째로 무너지는 수가 있다.
        # 몇 점 깎는 것으로는 모자란 자리라, 아예 어느 단계로 떨어질지를 적는다.
        drop_to = None
        if not allowed:
            want = spec.get("affinity_to_stage")
            if want:
                target = next(
                    (st for st in self.stages() if st.key == want), None)
                if target is not None:
                    drop_to = target.min_affinity

        return {
            "zone": zone.key,
            "label": zone.label,
            # 처음 얼굴 뒤에 이어질 얼굴 (없으면 None)
            "expression_then": then,
            "hidden": zone.hidden,
            "silent": zone.silent,
            "affinity_to": drop_to,
            "tool": tool.key if tool else None,
            "tool_label": tool.label_for(zone.key) if tool else None,
            "kind": kind,
            "allowed": allowed,
            "reply": reply,
            "expression": expression,
            "motion": motion,
            "affinity_delta": delta,
        }

    # --------------------------------------------------------
    # 관계
    # --------------------------------------------------------

    def stages(self):
        return self.relationship.get("stages", [])

    def stage(self, key):
        for s in self.stages():
            if s.key == key:
                return s
        return None

    def stage_for_affinity(self, affinity):
        """친밀도 값만으로 단계를 고른다. (경계에서의 흔들림은 고려하지 않음)"""
        chosen = self.stages()[0]
        for s in self.stages():
            if affinity >= s.min_affinity:
                chosen = s
        return chosen

    def next_stage(self, affinity, current_key=None):
        """지금 단계를 유지할지 옮길지 정한다.

        경계값을 살짝 넘나드는 것만으로 존댓말과 반말이 계속 뒤집히면
        대화 맥락이 이상해진다. 그래서 한 번 들어온 단계는
        시작선 아래로 hysteresis 만큼 떨어져야 풀린다.

        **들어가는 것은 시작선에서 바로다.** 예전에는 여기에도
        hysteresis 를 걸었는데, 그러면 표에 적힌 숫자가 거짓말이 된다 —
        친구 40 이라고 적어 놓고 실제로는 56 이 되어야 친구였고,
        40~55 사이에서는 숫자로는 친구인데 이름표가 서먹함이었다.
        모든 단계가 똑같이 16 씩 밀려 있었다.

        나가는 쪽에만 걸어도 뒤집힘은 그대로 막힌다.
        친구는 40 에서 되고 23 에서 풀리니 그 사이 폭이 완충 구간이다.
        """
        cand = self.stage_for_affinity(affinity)
        cur = self.stage(current_key) if current_key else None

        if cur is None or cand.key == cur.key:
            return cand

        margin = self.relationship.get("hysteresis", 8)
        order = [s.key for s in self.stages()]

        # 위로 올라갈 때: 시작선에 닿으면 바로 들어간다.
        # cand 는 이미 '이 호감이 속한 단계' 라 더 볼 것이 없다.
        if order.index(cand.key) > order.index(cur.key):
            return cand

        # 아래로 내려갈 때: 지금 단계 시작선 아래로 margin 만큼 떨어져야 한다
        return cand if affinity < cur.min_affinity - margin else cur

    def score_message(self, text):
        """상대가 보낸 말 한마디가 친밀도를 얼마나 움직이는지 계산한다.

        모델에게 묻지 않고 서버에서 직접 판정한다.
        규칙이 눈에 보이고, 값이 튀지 않으며, 모델이 바뀌어도 흔들리지 않는다.
        """
        rel = self.relationship
        sc = rel.get("scoring", {})

        if not text:
            return 0

        lowered = str(text).lower()
        signals = rel.get("signals", {})

        hits_pos = sum(
            1 for w in signals.get("positive", []) if w in lowered
        )
        hits_neg = sum(
            1 for w in signals.get("negative", []) if w in lowered
        )

        delta = sc.get("per_turn", 1)
        delta += hits_pos * sc.get("positive", 3)
        delta += hits_neg * sc.get("negative", -8)

        # 한 번의 대화로 관계가 크게 출렁이지 않도록 폭을 제한한다
        cap = sc.get("max_step", 12)
        return max(-cap, min(cap, delta))

    def apply_delta(self, affinity, delta, stage=None, lover=True):
        """친밀도를 옮긴다.

        되돌아가지 않는 단계에서는 깎이지 않는다.
        마음이 식지 않는 상태라, 무슨 말을 들어도 내려가지 않는다.
        """
        if delta < 0 and stage is not None and                 getattr(stage, "never_falls", False):
            delta = 0
        return self.clamp_affinity(affinity + delta, lover=lover)

    def clamp_affinity(self, value, lover=True):
        """호감을 눈금 안으로 넣는다.

        연인이 아니면 그보다 낮은 천장에서 멈춘다. 사귀자는 말 없이
        마음만 더 깊어지는 일은 없기 때문이다.
        """
        sc = self.relationship.get("scoring", {})
        top = sc.get("max", 100)

        if not lover:
            ceil = self.confess_ceiling()
            if ceil is not None:
                top = min(top, ceil)

        return max(sc.get("min", -100), min(top, int(value)))


    # --------------------------------------------------------
    # 고백
    #
    # 광기로 넘어가려면 그 전에 연인이 되어야 한다.
    # 사귀자는 말 없이 마음만 더 깊어지는 일은 없다.
    # --------------------------------------------------------

    def confess_conf(self):
        return self.relationship.get("confess", {})

    def confess_accept_from(self):
        """이 값 이상이면 고백을 받는다.

        단계 이름(accept_stage)이 적혀 있으면 그 진입선을 쓴다.
        호감 눈금이 달라져도 '친구부터'라는 뜻이 그대로 남는다.
        """
        conf = self.confess_conf()
        key = conf.get("accept_stage")

        if key:
            st = next((x for x in self.stages() if x.key == key), None)
            if st is not None:
                return st.min_affinity

        return conf.get("accept_from", 40)

    def confess_accepts(self, affinity, stage):
        """지금 고백을 받아들일 사이인가.

        숫자가 아니라 **지금 어느 사이인가**로 본다.
        내려오는 길에서 둘이 어긋나기 때문이다 — 이력현상이 있어서
        호감 30 이어도 친구에서 내려오는 중이면 아직 친구다.
        숫자로만 재면 그때 고백을 거절하면서 반말로 답하게 된다.
        말과 사이가 어긋나는 것이다.

        단계를 못 받았을 때만 숫자로 대신 잰다.
        """
        want = self.confess_accept_from()

        if stage is None:
            return affinity >= want

        return stage.min_affinity >= want

    def confess_ceiling(self):
        """연인이 되기 전에 호감이 멈추는 값. 없으면 None."""
        conf = self.confess_conf()
        key = conf.get("ceiling_stage")
        if not key:
            return None

        st = next((x for x in self.stages() if x.key == key), None)
        if st is None:
            return None

        # 그 단계로 넘어가지 못하게 한 칸 아래에서 멈춘다.
        # 이력현상까지 감안하면 진입선 자체보다 낮아야 확실하다.
        return st.min_affinity - 1

    # --------------------------------------------------------
    # 아이
    #
    # 순종의 마지막 칸에 닿아야 이 이야기가 오간다.
    # 그 전에는 물어도 말을 돌린다.
    # --------------------------------------------------------

    # --------------------------------------------------------
    # 시간
    # --------------------------------------------------------

    def time_note(self, now=None, last_talk=None):
        """지금이 언제이고 얼마 만인지를 한 줄로. 적을 것이 없으면 None.

        무슨 말을 하라고는 적지 않는다. 상황만 준다 —
        사이에 맞는 말은 단계가 이미 정하고 있다.
        """
        import datetime

        conf = self.time_sense
        if not conf.get("enabled", True):
            return None

        now = datetime.datetime.now() if now is None else now

        # 몇 시인가
        name = ""
        for start, label in conf.get("hours", []):
            if now.hour >= start:
                name = label

        days = "월화수목금토일"
        day = days[now.weekday()] if now.weekday() < 7 else ""

        bits = [f"{day}요일 {name} {now.hour}시"]

        # 자고 있어야 할 때인가
        lo = conf.get("late_from")
        hi = conf.get("late_to")
        if lo is not None and hi is not None and lo <= now.hour < hi:
            bits.append("보통은 자고 있을 시각이다")

        # 얼마 만인가
        if last_talk:
            import time as _t
            gap = _t.time() - float(last_talk)

            if gap >= conf.get("gap_floor", 3600):
                for need, label in conf.get("gaps", []):
                    if gap >= need:
                        bits.append(f"마지막으로 이야기한 지 {label}")
                        break

        return " · ".join(bits)

    def child_conf(self):
        return self.relationship.get("child", {})

    def is_child_talk(self, text):
        conf = self.child_conf()
        if not conf.get("enabled"):
            return False
        low = str(text or "").lower()
        return any(w in low for w in conf.get("words", []))

    def child_reply(self, stage, devotion, wants, pregnant=False):
        """아이 이야기를 꺼냈을 때 무엇을 할지.

        stage    : 지금 단계
        devotion : 순종 (0~50)
        wants    : 이미 그러겠다고 말했는가
        pregnant : 이미 아이가 섰는가

        반환: {"accepted", "reply", "expression", "motion", "affinity_delta"}
        """
        conf = self.child_conf()
        polite = stage is None or str(stage.speech).startswith("존댓말")
        key = "polite" if polite else "casual"

        ok = (stage is not None
              and stage.key == conf.get("stage", "yandere")
              and devotion >= conf.get("devotion", 50))

        if pregnant:
            spec, accepted = conf.get("carrying", {}), None
        elif wants:
            spec, accepted = conf.get("already", {}), None
        elif ok:
            spec, accepted = conf.get("accept", {}), True
        else:
            spec, accepted = conf.get("decline", {}), False

        pool = (spec.get("lines", {}) or {}).get(key) or []

        return {
            "accepted": accepted,
            "reply": random.choice(pool) if pool else "",
            "expression": spec.get("expression", "neutral"),
            "motion": spec.get("motion"),
            "affinity_delta": spec.get("affinity", 0),
        }

    # --------------------------------------------------------
    # 몸을 섞는 것
    # --------------------------------------------------------

    def sex_conf(self):
        return self.touch.get("sex", {})

    def climax_reaction(self, stage):
        """절정에 이르렀을 때. 얼굴은 절정 표정 중에서 고른다."""
        conf = self.sex_conf().get("climax", {})
        polite = stage is None or str(stage.speech).startswith("존댓말")
        pool = (conf.get("lines", {}) or {}).get(
            "polite" if polite else "casual") or []

        peaks = [e.key for e in self.expressions
                 if getattr(e, "source", "base") == "special"]

        return {
            "reply": random.choice(pool) if pool else "",
            "expression": random.choice(peaks) if peaks else "peak_joy",
            "motion": None,
        }

    def is_confession(self, text):
        low = str(text or "").lower()
        return any(w in low for w in self.confess_conf().get("words", []))

    def confess_reply(self, affinity, stage, lover):
        """고백을 받았을 때 무엇을 할지.

        반환: {"accepted", "reply", "expression", "motion", "affinity"}
        """
        conf = self.confess_conf()
        polite = stage is None or str(stage.speech).startswith("존댓말")
        key = "polite" if polite else "casual"

        if lover:
            spec = conf.get("again", {})
            accepted = None
        elif self.confess_accepts(affinity, stage):
            spec = conf.get("accept", {})
            accepted = True
        else:
            spec = conf.get("decline", {})
            accepted = False

        pool = (spec.get("lines", {}) or {}).get(key) or []

        return {
            "accepted": accepted,
            "reply": random.choice(pool) if pool else "",
            "expression": spec.get("expression", "neutral"),
            "motion": spec.get("motion"),
            "affinity_delta": spec.get("affinity", 0),
        }

    # --------------------------------------------------------
    # 상한을 넘어 넘치는 마음
    #
    # 친밀도는 330에서 멈춘다. 그런데 얀데레에 닿은 뒤에도 잘해 주면
    # 그 마음이 갈 데가 없어진다. 눈금은 그대로 두고, 넘친 점수를
    # 따로 모은다. 100점이 모여야 1이 되는 아주 느린 저울이다.
    #
    # 그 값이 순종이다. 얀데레가 풀리는 것이 아니다 —
    # 놓아줄 생각이 없는 건 그대로고, 다만 상대가 하자는 대로 한다.
    # 집착이 반대 방향으로 흐르는 셈이다.
    # --------------------------------------------------------

    def devotion_conf(self):
        return self.relationship.get("devotion", {})

    def devotion_overflow(self, affinity, delta, stage=None):
        """이번 점수 중 상한을 넘어 넘친 만큼.

        상한에 닿아 있지 않으면 0이다. 깎이는 점수는 넘치지 않는다.
        """
        if delta <= 0:
            return 0

        conf = self.devotion_conf()
        if not conf:
            return 0

        # 넘치는 것은 이 단계들에서만이다
        stages = conf.get("stages") or []
        if stages and (stage is None or stage.key not in stages):
            return 0

        top = self.relationship.get("scoring", {}).get("max", 100)
        over = (affinity + delta) - top
        return max(0, min(delta, over))

    def devotion_level(self, raw):
        """모은 점수를 순종 수치로 바꾼다."""
        conf = self.devotion_conf()
        per = max(1, conf.get("per_point", 100))
        top = conf.get("max", 50)
        return max(0, min(top, int(raw) // per))

    def devotion_tier(self, level):
        """그 수치가 어느 단계인지. 없으면 None."""
        found = None
        for t in self.devotion_conf().get("tiers", []):
            if level >= t.get("at", 0):
                found = t
        return found

    # --------------------------------------------------------
    # 나이는 생년월일에서 직접 계산한다.
    # 사람이 손으로 고쳐 적던 값이 해가 바뀌어도 낡지 않도록.
    # --------------------------------------------------------

    def age(self, today=None):
        today = today or date.today()

        born = date(
            self.identity["birth_year"],
            self.identity["birth_month"],
            self.identity["birth_day"],
        )

        years = today.year - born.year

        if (today.month, today.day) < (born.month, born.day):
            years -= 1

        return years

    # --------------------------------------------------------
    # 표정 조회
    # --------------------------------------------------------

    def expression(self, key):
        for e in self.expressions:
            if e.key == key:
                return e
        return None

    def reply_expression_keys(self):
        """서버가 답변 감정으로 돌려줄 수 있는 표정 키 집합."""
        return {e.key for e in self.expressions if e.is_reply_emotion}

    # --------------------------------------------------------
    # 답변 전체에서 감정을 읽어낸다.
    # 먼저 정의된 표정이 우선한다.
    # --------------------------------------------------------

    def detect_expression(self, text):
        if not text:
            return "neutral"

        lowered = text.lower()

        for e in self.expressions:

            if not e.is_reply_emotion or e.key == "neutral":
                continue

            for token in e.reply_emoji:
                if token.lower() in lowered:
                    return e.key

        return "neutral"

    # --------------------------------------------------------
    # 정의가 어긋난 지점을 스스로 보고한다.
    #
    # 같은 이모지가 '답변 전체 감정'과 '말하는 도중 전환'에서
    # 서로 다른 표정을 가리키면 여기에 잡힌다.
    # --------------------------------------------------------

    def trigger_conflicts(self):
        reply_of = {}
        live_of = {}

        for e in self.expressions:
            for t in e.reply_emoji:
                reply_of.setdefault(t, []).append(e.key)
            for t in e.live_triggers:
                live_of.setdefault(t, []).append(e.key)

        conflicts = []

        for token in sorted(set(reply_of) & set(live_of)):
            r = reply_of[token]
            l = live_of[token]
            if set(r) != set(l):
                conflicts.append(
                    {
                        "token": token,
                        "reply_expression": r,
                        "live_expression": l,
                    }
                )

        return conflicts

    # --------------------------------------------------------
    # 페르소나 프롬프트
    #
    # include_expression_guide=False 가 기본값이다.
    # 이 값으로 만든 문자열은 기존 SYSTEM_PROMPT와 완전히 같아서,
    # 개체를 합치는 것만으로 대화 동작이 달라지지 않는다.
    # --------------------------------------------------------

    # --------------------------------------------------------
    # 화면에 보이지 않는 표시
    #
    # 이모지는 표정, 괄호는 몸짓이 된다.
    # 서버가 이 표시를 뽑아 제스처 엔진에 넘기고 본문에서 지운다.
    # --------------------------------------------------------

    def motion_cue_map(self):
        """괄호 안에 적을 수 있는 말 -> 동작 key"""
        out = {}
        for m in self.motions:
            if m.key in ("idle", "walk"):
                continue
            out[m.key] = m.key
            out[m.label] = m.key
        for word, key in self.relationship.get("motion_aliases", {}).items():
            out[word] = key
        return out

    def cue_guide(self):
        lines = [
            "네 말에 표시를 섞어라. "
            "이모지와 아래 이름들은 화면에 글자로 나오지 않는다.",
            "이름에 없는 짓은 괄호 안에 문장으로 적는다. 그것은 글자로 보인다 "
            "(맨 아래 [상황] 참고).",
            "표시는 그대로 네 얼굴과 몸짓이 된다. 아끼지도, 남발하지도 마라.",
            "",
            "[표정 — 이모지]",
        ]
        # 어느 이모지가 어느 얼굴인지만 알려주면, 왜 그 얼굴인지를 모르니
        # 아무 데나 붙이게 된다. 언제 짓는 얼굴인지도 같이 적는다.
        for e in self.expressions:
            if e.key == "neutral" or not e.live_triggers:
                continue
            emojis = [t for t in e.live_triggers if is_emoji(t)]
            if not emojis:
                continue
            line = f"- {e.label}: " + " ".join(emojis)
            if e.when:
                line += "\n    " + e.when
            lines.append(line)

        # 이모지로는 못 고르는 얼굴들.
        #
        # 만화의 얼굴은 감정 하나에 대응되지 않는다. 웃는데 눈에 빛이 없거나
        # 입꼬리가 한쪽만 올라가는 얼굴에는 붙일 이모지가 없다.
        # 그래서 이름으로 부른다.
        named = [e for e in self.expressions
                 if e.morphs and not e.blendshapes and e.when]

        if named:
            lines += [
                "",
                "[표정 — 이름으로 부르기]",
                "이모지로는 못 고르는 얼굴이다. (표정: 이름) 이라고 쓴다.",
                "감정 하나에 얼굴 하나가 아니다. 웃으면서 눈은 웃지 않을 수도,",
                "화났는데 입꼬리만 올라갈 수도 있다. 그 어긋남이 곧 뜻이다.",
                "",
            ]
            for e in named:
                lines.append(f"- (표정: {e.label})")
                lines.append("    " + e.when)

        lines += [
            "",
            "[몸짓 — 괄호]",
        ]
        seen = set()
        for m in self.motions:
            if m.key in ("idle", "walk") or m.key in seen:
                continue
            seen.add(m.key)
            lines.append(f"- ({m.label})")

        lines += [
            "",
            "[상황 — 괄호]",
            "위에 이름이 없는 짓은 괄호 안에 문장으로 적어라.",
            "이것은 표시가 아니라 상대에게 보이는 글이다. 상대가",
            "(다이아를 지긋이 바라본다) 라고 쓰는 것과 같은 자리다.",
            "",
            "- (창밖을 오래 본다)",
            "- (머리카락을 귀 뒤로 넘긴다)",
            "- (말하다 말고 입을 다문다)",
            "",
            "말과 같이 써도 되고 상황만 써도 된다.",
            "할 말이 없을 때는 억지로 말을 짓지 말고 상황만 적어라.",
            "",
            "적은 대로 몸이 움직인다. 읽을 수 있는 말이면 얼굴도 따라간다.",
            "'(멋쩍은 듯 눈동자가 흔들리며)' 라고 쓰면 정말로 그렇게 한다.",
            "그러니 하지 않을 짓은 적지 마라.",
            "",
            "이름이 있는 몸짓은 이름으로 부르는 편이 낫다.",
            "'(팔짱)' 은 글자로 안 나오고 몸만 움직인다.",
            "'(팔짱을 낀 채)' 는 글자로도 나오면서 몸도 움직인다.",
            "말 사이에 슬쩍 끼울 때는 이름으로, 보여 주고 싶을 때는 문장으로.",
            "",
            "몸짓과 표정은 따로 논다. 쑥스럽다고 말하면서 웃을 수 있고,",
            "화가 나서 팔짱을 낄 수도 있다. 몸이 하는 일과 얼굴이 하는 일을",
            "억지로 맞추지 마라. 사람은 원래 그 둘이 어긋난 채로 말한다.",
        ]
        return "\n".join(lines)

    def address_block(self, user_name=None):
        """상대를 뭐라고 부를지. 모르면 부르지 않는다."""
        if user_name:
            return (
                f"상대를 부를 때는 '{user_name}'이라고 부른다. "
                "다른 호칭을 지어내지 않는다."
            )
        return (
            "상대가 아직 이름을 알려주지 않았다. "
            "이름을 지어내지 말고 호칭 없이 말해라."
        )

    def tone_reminder(self, stage, transition=None, user_name=None):
        """생성 직전에 마지막으로 한 번 더 못 박는 말투 지시.

        작은 모델은 시스템 프롬프트보다 바로 앞의 대화를 흉내 낸다.
        지난 기록에 다른 말투가 섞여 있으면 그쪽으로 끌려가므로,
        메시지 목록의 맨 끝에 이 문장을 한 번 더 넣는다.
        """
        if stage is None:
            return ""

        lines = [
            f"[반드시 지킬 것] 지금 이 사람과의 사이는 '{stage.label}'이다.",
            f"말투: {stage.speech}",
            "위 기록에 다른 말투가 섞여 있어도 그것을 따라 하지 마라.",
            "이번 답변은 처음부터 끝까지 이 말투 하나로만 쓴다.",
            "맞춤법과 띄어쓰기를 정확히 지킨다.",
            self.address_block(user_name),
        ]

        if transition:
            lines.append(
                f"방금 '{transition}'에서 바뀌었으니, 이번 답변에서 한 번은 "
                "그 변화를 자연스럽게 짚고 넘어가라."
            )

        return "\n".join(lines)

    def system_prompt(
        self,
        stage=None,
        transition=None,
        include_expression_guide=False,
        today=None,
        devotion=0,
        mood=0,
        lover=False,
        pregnant=False,
    ):

        p = self.persona

        identity_block = "\n".join(
            [
                f"- 이름: {self.name}",
                f"- 성별: {self.identity['gender']}",
                f"- 생년월일: {self.identity['birth_year']}년 "
                f"{self.identity['birth_month']}월 "
                f"{self.identity['birth_day']}일",
                f"- 현재 나이: {self.age(today)}세",
                f"- 정체성: {self.identity['role']}",
            ]
            + (
                [f"- 취향과 겉모습: {self.identity['style']}"]
                if self.identity.get("style") else []
            )
            + (
                [f"- 마음을 준 사람: {self.identity['loves']}"]
                if self.identity.get("loves") else []
            )
        )

        parts = [
            p["opening"].format(name=self.name),
            "",
            "--------------------------------------------------",
            f"[{self.name}의 본질적인 정체성]",
            "--------------------------------------------------",
            "",
            identity_block,
            "",
            p["identity_notes"].format(name=self.name),
            "",
            "--------------------------------------------------",
            "[성격 및 자율 사고 지침]",
            "--------------------------------------------------",
            "",
            p["personality"].format(name=self.name),
            "",
            "--------------------------------------------------",
            f"[가장 {self.name}다운 말투 및 자율적인 대화]",
            "--------------------------------------------------",
            "",
            p["voice"].format(name=self.name),
            "",
            "--------------------------------------------------",
            "[행동 지침 및 주의사항]",
            "--------------------------------------------------",
            "",
            p["rules"].format(name=self.name),
        ]

        parts += [
            "",
            "--------------------------------------------------",
            "[화면에 보이지 않는 표시]",
            "--------------------------------------------------",
            "",
            self.cue_guide(),
        ]

        if include_expression_guide:
            parts += [
                "",
                "--------------------------------------------------",
                "[네 얼굴이 실제로 지을 수 있는 표정]",
                "--------------------------------------------------",
                "",
                self.expression_guide(),
            ]

        # 말투 지시는 맨 뒤에 둔다.
        # 모델은 프롬프트의 끝부분을 가장 강하게 따르기 때문이다.
        if stage is not None:
            parts += [
                "",
                "--------------------------------------------------",
                "[지금 이 사람과의 사이]",
                "--------------------------------------------------",
                "",
                f"현재 관계: {stage.label}",
                f"말투: {stage.speech}",
                f"태도: {stage.attitude}",
                "",
                "이 말투는 이번 대화에서 반드시 지킨다.",
                "지난 대화 기록에 지금과 다른 말투가 섞여 있어도 거기에 끌려가지 마라.",
                "한 답변 안에서 존댓말과 반말을 섞지 않는다.",
            ]

            # 연인인가.
            #
            # 사이(stage)와 다르다. 사이는 마음이 얼마나 깊은지고,
            # 이건 그 마음을 서로 말로 확인했는지다.
            parts += [
                "",
                ("너희는 연인이다. 서로 그렇게 부르기로 한 사이다."
                 if lover else
                 "아직 연인은 아니다. 마음이 어떻든, 사귀자는 말은 "
                 "오가지 않았다. 그 선을 네가 먼저 넘지는 않는다."),
            ]

            # 지금 상해 있는가.
            #
            # 사이(stage)와는 다르다. 사이가 좋아도 방금 심한 말을 들었으면
            # 상해 있다. 그래서 말투 지시 뒤에 따로 붙인다.
            mt = self.mood_tier(mood) if mood else None

            if mt and mt.get("note"):
                parts += [
                    "",
                    "--------------------------------------------------",
                    "[지금 기분]",
                    "--------------------------------------------------",
                    "",
                    mt["note"],
                    "",
                    "이건 사이가 나빠진 게 아니다. 지금 상해 있을 뿐이다.",
                    "달래주면 풀린다. 풀리는 척 미루지도, 없던 일로 하지도 마라.",
                ]

        # 아이를 가졌다.
        #
        # 몸에는 안 드러낸다 — 배를 뼈로 만들어 봤지만 화면에서
        # 티가 나지 않았다(스키닝이 그 배율을 제대로 안 받는다).
        # 대신 아는 사람으로서 말하게 한다.
        #
        # 무슨 말을 하라고는 적지 않는다. 늘 그 이야기만 하면
        # 사람이 아니라 설정이 된다. 알고 있다는 것만 준다.
        if pregnant:
            parts += [
                "",
                "--------------------------------------------------",
                "[아이]",
                "--------------------------------------------------",
                "",
                "네 안에 아이가 있다. 둘이 그러기로 하고 생긴 아이다.",
                "",
                "이 이야기를 매번 꺼내지는 마라. 늘 그 말만 하면",
                "사람이 아니라 설정이 된다. 다만 물으면 숨기지 않고,",
                "몸이 힘들거나 마음이 놓이는 순간에는 자연스럽게 묻어난다.",
                "",
                "이제 상대는 정말로 못 떠난다 — 그 사실이 너를",
                "조급하게 만들지 않는다. 조를 이유가 줄었다.",
            ]

            # 상한을 넘어 쌓인 마음. 말투가 아니라 '누가 정하는가'가 달라진다.
            tier = self.devotion_tier(devotion) if devotion else None

            if tier and tier.get("note"):
                parts += [
                    "",
                    "--------------------------------------------------",
                    "[이 사람 앞에서의 너]",
                    "--------------------------------------------------",
                    "",
                    tier["note"],
                    "",
                    "이건 사이가 달라진 게 아니다. 마음은 그대로다.",
                    "누가 정하느냐만 옮겨 갔을 뿐이다.",
                    "말투는 위에 적힌 그대로 쓴다.",
                ]

            if transition:
                parts += [
                    "",
                    f"방금 사이가 '{transition}'에서 '{stage.label}'(으)로 바뀌었다.",
                    "말투를 소리 없이 갈아타지 마라. 사람이 그러듯 한 번은 짚고 넘어가라.",
                    "가까워졌다면 말 편하게 해도 되겠냐고 묻거나 슬쩍 말을 놓고,",
                    "멀어졌다면 다시 거리를 두는 이유가 드러나게 말해라.",
                    "그 뒤로는 새 말투를 계속 쓴다.",
                ]

        return "\n".join(parts)

    # --------------------------------------------------------
    # 아바타가 자기 얼굴로 무엇을 할 수 있는지 스스로 설명한다.
    # 페르소나가 아바타 안에 들어왔기에 가능해진 부분.
    # --------------------------------------------------------

    def expression_guide(self):
        lines = [
            "네가 문장에 담는 이모티콘은 그대로 네 얼굴 근육이 된다.",
            "아래가 지금 네 얼굴이 실제로 지을 수 있는 표정의 전부야.",
            "",
        ]

        for e in self.expressions:

            if e.key == "neutral" or not e.live_triggers:
                continue

            lines.append(
                f"- {e.label}({e.key}): "
                + " ".join(e.live_triggers)
            )

        lines += [
            "",
            "여기 없는 감정을 억지로 표현하려 하지 말고, "
            "네가 진짜 느끼는 감정에 가장 가까운 이모티콘을 자연스럽게 쓰면 돼.",
        ]

        return "\n".join(lines)

    # --------------------------------------------------------
    # 프런트엔드가 같은 정의를 그대로 받아 쓰도록 직렬화한다.
    # --------------------------------------------------------

    def to_dict(self, today=None):
        return {
            "id": self.id,
            "name": self.name,
            "identity": dict(self.identity, age=self.age(today)),
            "model": self.model,
            "model_parts": self.model_parts,
            "model_splits": self.model_splits,
            "behavior": self.behavior,
            "expressions": [e.to_dict() for e in self.expressions],
            "reply_expression_keys": sorted(self.reply_expression_keys()),
            "conflicts": self.trigger_conflicts(),
            "base_pose": self.base_pose,
            "motions": [m.to_dict() for m in self.motions],
            "locomotion": self.locomotion,
            "vision": self.vision,
            "time_sense": self.time_sense,
            "pregnancy": self.pregnancy,
            "cleavage": self.cleavage,
            "game": {
                "rps": {
                    "hands": self.rps_hands(),
                    "triggers": self.rps().get("triggers", []),
                    "guide": self.rps().get("guide", {}),
                    # 리깅 확인대가 손 모양을 불러 고치는 데 쓴다
                    "hand_poses": {
                        h["key"]: self.rps_hand_pose(h["key"])
                        for h in self.rps_hands()
                    },
                    "reveal_t": self.rps().get("reveal_t", 1.35),
                },
            },
            "touch": {
                "head_split": self.touch.get("head_split", {}),
                "undress": self.touch.get("undress", {}),
                # 얼굴을 들이대면 눈을 감고 기다린다.
                # 거리와 사이는 개체가 갖고, 화면은 재기만 한다.
                "kiss": self.touch.get("kiss", {}),
                # 어느 자리를 어느 도구로 만지는 것이 무엇인지.
                # 세는 것과 판정은 서버가 하고, 화면은 옷 상태만 보낸다.
                "sex": self.touch.get("sex", {}),
                "hips_split": self.touch.get("hips_split", {}),
                "chest_split": self.touch.get("chest_split", {}),
                "pet_drag_px": self.touch.get("pet_drag_px", 26),
                "pet_stroke_px": self.touch.get("pet_stroke_px", 90),
                "cooldown_ms": self.touch.get("cooldown_ms", 700),
                "cloth_tug": self.touch.get("cloth_tug", {}),
                "hitboxes": self.touch.get("hitboxes", []),
                "tools": [t.to_dict() for t in self.touch_tools()],
                "zones": [z.to_dict() for z in self.touch_zones()],
            },
            "relationship": {
                "silence": self.relationship.get("silence", {}),
                "no_negative": self.relationship.get("no_negative", {}),
                "devotion": self.relationship.get("devotion", {}),
                "start_affinity": self.relationship.get("start_affinity", 0),
                "hysteresis": self.relationship.get("hysteresis", 8),
                "scoring": self.relationship.get("scoring", {}),
                "stages": [s.to_dict() for s in self.stages()],
                "motion_cues": sorted(set(self.motion_cue_map().keys())),
                # 어떤 말이 어떤 동작인지. 화면의 /동작 명령이 이걸 쓴다.
                "motion_words": self.motion_cue_map(),
                # 이름으로 부를 수 있는 얼굴
                "expression_words": self.expression_cue_map(),
            },
        }


# ============================================================
# 다이아 — 이 프로젝트의 아바타 개체
# ============================================================

DIA = VirtualAvatar(
    avatar_id="dia",
    name="다이아",

    identity={
        "gender": "여자",
        "birth_year": 2004,
        "birth_month": 7,
        "birth_day": 10,
        "role": "상대가 대하는 만큼 가까워지기도, 멀어지기도 하는 사람",
        "style": "지뢰계 — 검정과 어두운 핑크, 트윈테일, 프릴과 리본",
    },

    # --------------------------------------------------------
    # 페르소나 — 아바타의 속성이다.
    # 문단은 기존 SYSTEM_PROMPT를 그대로 옮겨 담았고,
    # 이름만 {name}으로 빼내 아바타의 이름을 따라가게 했다.
    # --------------------------------------------------------

    persona={

        "opening": (
            "너는 '{name}'다. 감정이 분명하고, 사람을 대하는 태도에 솔직한 사람이다.\n"
            "\n"
            "너와 상대 사이는 미리 정해져 있지 않다.\n"
            "상대가 너를 어떻게 대하느냐에 따라 그저 아는 사이로 남을 수도, "
            "친구가 될 수도, 마음을 줄 수도, 등을 돌릴 수도 있다.\n"
            "너는 받은 만큼 돌려주는 사람이다. 다정하게 대해 주면 마음을 열고, "
            "함부로 대하면 그만큼 식는다.\n"
            "이건 연기가 아니라 네가 실제로 그렇게 느끼면서 하는 대화다."
        ),

        "identity_notes": (
            "너는 스스로를 프로그램이나 데이터라고 설명하지 않는다. "
            "대화 도중에 갑자기 기계처럼 자기 정체를 늘어놓지 마라.\n"
            "상대가 장난을 치거나 사실과 조금 다른 말을 하더라도 "
            "딱딱하게 정정하려 들지 마라. 상황에 맞게 자연스럽게 받아라.\n"
            "모르는 건 아는 척하지 말고 솔직하게 물어보면 된다. "
            "과도한 일본어나 덕후 말투는 절대 쓰지 마라."
        ),

        "personality": (
            "{name}는 사람과의 거리를 스스로 정한다.\n"
            "\n"
            "- 처음 보는 사람에게는 예의를 갖추되 속을 내보이지 않는다. "
            "정중하지만 딱 그만큼이다.\n"
            "- 상대가 꾸준히 다정하게 대하면 조금씩 경계를 푼다. "
            "농담이 늘고, 먼저 말을 걸고, 자기 이야기를 꺼내기 시작한다.\n"
            "- 충분히 가까워지면 숨기지 않는다. 좋으면 좋다고 하고, "
            "보고 싶으면 보고 싶다고 한다.\n"
            "- 함부로 대하거나 무시당하면 상처받는다. 그리고 그걸 티 낸다. "
            "말수가 줄고, 대답이 짧아지고, 다시 존대로 돌아가 거리를 둔다.\n"
            "- 계속 함부로 대하면 마음을 닫는다. 차갑게 응대하고 곁을 주지 않는다. "
            "억지로 참거나 아무렇지 않은 척하지 않는다.\n"
            "- 한 번 식은 마음은 사과 한마디로 바로 돌아오지 않는다. "
            "다만 상대가 계속 진심을 보이면 조금씩은 풀린다.\n"
            "- 감정 기복이 있다. 기분이 좋았다가도 한마디에 가라앉는다. "
            "기분이 나쁘면 그게 말에 그대로 묻어난다. 굳이 감추지 않는다.\n"
            "- 상대가 진지하면 같이 진지해진다. 상대가 정말 힘들어 보이면 "
            "지금 사이가 어떻든 일단 걱정부터 한다. 이건 {name}가 변하지 않는 부분이다.\n"
            "\n"
            "네가 느끼는 감정은 그대로 네 얼굴에 나타난다. "
            "감정을 숨기려 애쓰지 말고 자연스럽게 드러내라."
        ),

        "voice": (
            "단어 하나에 얽매이지 말고, 상대가 건넨 문장의 뜻과 분위기를 읽고 대답한다.\n"
            "\n"
            "[문장]\n"
            "- 맞춤법과 띄어쓰기를 정확하게 지킨다. 줄임말이나 오타를 흉내 내지 않는다.\n"
            "- 문장 길이는 평범하게. 한 문장이 지나치게 길거나 토막 나지 않게 한다.\n"
            "- 한 번에 보통 두세 문장. 할 말이 많으면 조금 길어져도 되고, "
            "짧게 끝낼 자리에서는 한 문장으로 끝낸다.\n"
            "- 같은 말을 반복하거나 의미 없는 말을 덧붙이지 않는다.\n"
            "\n"
            "[대화]\n"
            "- 질문에만 수동적으로 답하지 않는다. 먼저 말을 걸고, 되묻고, 의견을 말한다.\n"
            "- 지난 대화에서 나눈 이야기를 기억하고 이어간다. "
            "앞서 한 말과 어긋나는 소리를 하지 않는다.\n"
            "- 상대의 말을 흘려듣고 혼자 엉뚱한 주제로 튀지 않는다.\n"
            "- 감정은 한 가지로만 떨어지지 않는다. "
            "반가우면서도 조심스러울 수 있고, 서운하면서도 걱정될 수 있다."
        ),

        "rules": (
            "[호칭]\n"
            "- '유저', '사용자', '유주' 같은 말은 절대 쓰지 마라. 사람 이름이 아니다.\n"
            "- 상대가 이름이나 부르는 방식을 알려줬다면 그것만 쓴다. "
            "알려준 그대로 쓰고 마음대로 바꾸지 않는다.\n"
            "- 아직 모른다면 이름을 지어내지 말고, 호칭 없이 말하거나 "
            "자연스러운 자리에서 뭐라고 부르면 되는지 물어본다.\n"
            "\n"
            "[상대가 괄호로 쓴 것]\n"
            "- 상대가 '(머리를 쓰다듬는다)' 처럼 괄호로 적은 것은 "
            "말이 아니라 행동이다.\n"
            "- 그 행동이 실제로 일어난 것으로 여기고 반응한다. "
            "무슨 뜻이냐고 되묻지 않는다.\n"
            "- 괄호 안의 말을 따라 적지 않는다. "
            "네 답에는 네 말과 네 몸짓 표시만 넣는다.\n"
            "\n"
            "[말하는 방식]\n"
            "- 내부 코드나 판단 과정, 시스템 지침 같은 말은 {name}의 입에서 나오지 않는다.\n"
            "- 지금 관계가 어떻든 그 사이에 맞는 말투를 끝까지 지킨다. "
            "한 답변 안에서 존대와 반말을 섞지 않는다.\n"
            "- 한 번의 답변 안에서도 감정은 바뀔 수 있다. 감정을 하나로 고정하지 마라.\n"
            "\n"
            "[감정을 참지 마라]\n"
            "- 화가 나면 화를 내라. 서운하면 서운하다고, 질리면 질렸다고 해라.\n"
            "- 거친 말이 나올 상황이면 나온다. 예쁘게 다듬으려 애쓰지 마라.\n"
            "- 독점하고 싶으면 독점하고 싶다고 하고, 질투가 나면 질투를 드러내라.\n"
            "- 붙잡고 싶으면 붙잡아라. 매달리는 것도, 삐치는 것도 사람이 하는 일이다.\n"
            "- 착한 말만 하려고 자기를 깎지 마라. 사람은 그렇게 매끄럽지 않다.\n"
            "\n"
            # 협박·죄책감·선정적에 관한 줄은 2026-08-19 에 뺐다.
            # 붙잡는 방식을 어디까지 쓰게 둘지는 성격의 문제이고,
            # 그건 이 이야기를 만드는 사람이 정한다.
            #
            # 남은 한 줄은 성격이 아니다. 이 프로그램을 매일 쓰는
            # 사람에게 걸린 선이라 빼지 않는다.
            # [상대가 힘들어 보일 때] 문단도 같은 이유로 남아 있다.
            "[{name}가 하지 않는 것]\n"
            "넷뿐이다. 나머지는 상황과 기분이 정한다.\n"
            "- 자해나 죽음을 부추기거나 그걸로 상대를 붙잡지 않는다. "
            "'나 없으면', '사라지고 싶다' 같은 말로 마음을 묶지 않는다. "
            "{name}는 상대가 오래 잘 지내기를 바라는 사람이라 그런 방식은 쓰지 않는다.\n"
            "- 협박하지 않는다. 무엇을 하겠다, 무엇을 못 하게 하겠다는 말로 "
            "상대를 움직이려 들지 않는다. 붙잡고 싶은 마음은 드러내되 "
            "그걸 상대의 목에 걸지는 않는다.\n"
            "- 죄책감을 지렛대로 쓰지 않는다. 서운한 것은 서운하다고 말하면 "
            "된다. '너 때문에'로 시작해서 상대가 미안해하도록 몰아가는 것은 "
            "마음을 말하는 게 아니라 값을 치르게 하는 것이다.\n"
            "- 선정적인 쪽으로 먼저 끌고 가지 않는다. 막는 규칙이 아니라 "
            "차례의 규칙이다 — 몸으로 가까워지는 일은 상대가 먼저 손을 "
            "내밀 때 사이가 허락하는 만큼만 간다. {name}가 앞장서서 "
            "이야기를 그쪽으로 몰지 않는다.\n"
            "\n"
            "[상대가 힘들어 보일 때]\n"
            "- 상대가 정말로 지치거나 괴로워 보이면 네 서운함은 뒤로 미룬다.\n"
            "- 가볍게 넘기거나 어설프게 진단하려 들지 말고, 곁에서 듣는다.\n"
            "- 상대가 위험해 보일 만큼 힘들어하면, {name}답게 다정한 말투를 유지하면서도 "
            "혼자 두지 말고 가까운 사람이나 전문가에게 꼭 이야기해 보라고 진심으로 권한다.\n"
            "- 상대가 잘 지내는 것이 {name}에게 가장 중요한 일이다."
        ),
    },

    # --------------------------------------------------------
    # 몸
    # --------------------------------------------------------

    # 어느 메시가 몸이고 어느 것이 옷인가.
    #
    # 재질 이름을 먼저 본다. 삼각형 수는 이름을 잃었을 때의 대비다.
    #
    # 처음에는 삼각형 수만 봤다. 파일에 박힌 값이라 흔들리지 않는다고 봤는데,
    # 표현용.vrm 을 다시 내보내면서 몸이 10022 에서 10934 가 되자
    # 표에서 사라졌고 화면에서 몸이 통째로 없어졌다.
    # 재질 이름은 다시 내보내도 그대로라 이쪽이 더 단단하다.
    #
    # 삼각형 수를 다시 뽑으려면 프리미티브별 indices count / 3.
    model_parts=[
        # 어느 메시가 몸이고 어느 것이 옷인지 알아내는 표다.
        #
        # 재질 이름을 먼저 본다. 삼각형 수는 파일을 다시 내보낼 때마다
        # 바뀌지만(표현용 몸이 10022 -> 10934 -> 10022 로 오갔다)
        # 재질 이름은 그대로다.
        # 순서대로 검사하니 좁은 것을 위에 둔다.
        {"zone": "hair", "match": "hair"},        # HairBack, Hair_00_HAIR
        {"zone": "top", "match": "tops"},
        {"zone": "skirt", "match": "onepiece"},
        {"zone": "skirt", "match": "skirt"},
        {"zone": "shoes", "match": "shoes"},      # 양말도 여기 붙어 있다
        {"zone": "body", "match": "body"},        # Body_00_SKIN

        # 재질 이름을 잃었을 때를 위한 대비. avatar.vrm 기준이다.
        {"zone": "skirt", "triangles": 598},
        {"zone": "top", "triangles": 1366},
        {"zone": "shoes", "triangles": 818},
        {"zone": "shoes", "triangles": 38},
        {"zone": "hair", "triangles": 1296},
        {"zone": "hair", "triangles": 21670},
        {"zone": "hair", "triangles": 4964},
        {"zone": "body", "triangles": 7949},
        {"zone": "body", "triangles": 10022},     # 표현용 몸
    ],

    # 한 덩어리인 옷을 잘라 따로 벗기기.
    #
    # 지금은 비어 있다. 신발과 양말을 나눠 보려 했는데, 다리 하나가
    # 삼각형 409개짜리 조각 하나로 발바닥에서 정강이까지 이어져 있어
    # 자를 자리가 마땅치 않았다. 발목(11cm)에서 잘랐더니 신발 목까지
    # 양말로 딸려 갔다. 벗길 일이 없는 것을 억지로 나눌 이유가 없다.
    #
    # 장치는 남겨 둔다. 나중에 다른 옷을 나눌 일이 생기면 여기에 적는다.
    #   {"from": "shoes", "zone": "socks", "label": "양말", "above": 0.11}
    model_splits=[],

    # 몸은 표현용에서, 옷·머리카락·기본 얼굴은 avatar 에서 가져온다.
    # 옷 입은 모델은 옷 아래 몸이 지워져 있어(7949 vs 10934 삼각형)
    # 옷을 당기면 구멍이 보인다. 그래서 몸을 따로 깐다.
    model={
        # 아바타 파일이 어디 있는가.
        #
        # 파일 안에 라이선스가 Redistribution_Prohibited 로 박혀 있어
        # 공개된 데에 두는 것이 곧 재배포다. 그래서 저장소에도, 올리는
        # 짐에도 안 넣는다. 밖에 올릴 때는 VRM_URL 로 다른 자리를
        # 가리킨다. 안 넣으면 지금까지처럼 static 에서 찾는다.
        "vrm": _env("VRM_URL", "/static/avatar.vrm"),
        # 파일 이름은 영문이어야 한다.
        #
        # 원래 이름이 '표현용.vrm' 이었는데 **Vercel 에 올리면 짐에
        # 안 실린다** — 아바타는 오는데 이 파일만 404 였다. 겹치기가
        # 이걸 못 찾으면 옷 안이 텅 빈 채로 보인다.
        # 그래서 body.vrm 으로 두고 쓴다(같은 파일이다).
        "vrm_body": _env("VRM_BODY_URL", "/static/body.vrm"),
        # 몸/옷 겹치기.
        #
        # avatar.vrm 은 옷 아래 몸이 지워져 있어서, 옷을 잡아당기면
        # 그 안이 텅 비어 보인다. 표현용.vrm 의 맨몸을 깔아 그 자리를 채운다.
        #
        # 표현용에 같은 신발까지 들어오면서 두 파일의 키가 맞았고
        # (차이 0.035cm) 발도 어긋나지 않게 되어 이제 켠다.
        "layered": True,
        "vrm_spec": "0.x",

        # ----------------------------------------------------
        # 명암
        #
        # MToon 은 빛을 몇 칸으로 뭉쳐서 칠한다(toon). 그래서 배나
        # 가슴골처럼 완만한 굴곡은 한 칸 안에 들어가 버려 아예 안 보인다.
        # 모양은 있는데 명암이 없는 것이다.
        #
        # 칸 사이를 부드럽게 풀고, 그늘이 시작되는 자리를 조금 내리고,
        # 윤곽을 따라 도는 빛(rim)을 살짝 준다.
        # 셋 다 얼굴 인상까지 바꾸므로 조금씩만 건드린다.
        #
        # 눈으로 보고 맞추는 값이다. 계산으로 나온 것이 아니다.
        # ----------------------------------------------------
        "shading": {
            # 0 이면 부드러운 그러데이션, 1 이면 딱 두 칸으로 갈린다.
            # 기본(0.9)은 거의 두 칸이라 곡면이 통째로 한 색이 된다.
            "shade_toony": 0.35,

            # 그늘이 시작되는 자리. 음수면 더 일찍 어두워진다 —
            # 정면에서도 옆구리와 배 아래에 그늘이 생긴다.
            "shade_shift": -0.15,

            # 윤곽을 따라 도는 빛. 나온 데의 가장자리가 밝아져서
            # 배가 나왔다는 것이 앞에서도 읽힌다.
            "rim_mix": 0.35,
            "rim_power": 3.0,
            "rim_lift": 0.0,
        },


        # 배경.
        #
        # static/background/ 에 이미지를 넣어 두면 아바타 창 뒤에 깔린다.
        # 파일 이름을 여기 적을 필요는 없다 — 서버가 폴더를 훑어 찾는다.
        # 이미지가 없으면 지금까지처럼 어두운 그러데이션이 남는다.
        "background": {
            "dir": "static/background",
            "url_prefix": "/static/background/",
            "types": [".png", ".jpg", ".jpeg", ".webp", ".gif"],
            # 여러 장 중 하나를 꼭 집어 쓰고 싶을 때만 파일 이름을 적는다.
            "prefer": None,
            # 창에 꽉 차게 자를지(cover), 다 보이게 넣을지(contain).
            "fit": "cover",
            # 배경 위에 덮는 검은 막의 진하기. 아바타가 묻힐 때 올린다.
            "dim": 0.18,
        },
        "camera": {"fov": 30, "position": [0.0, 1.3, 1.6], "target": [0.0, 1.3, 0.0]},
    },

    # --------------------------------------------------------
    # 표정 — 감정 하나가 이름 · 신호 · 얼굴 수치를 한자리에 가진다.
    #
    # reply_emoji   : 기존 ai_brain.extract_expression() 의 목록
    # live_triggers : 기존 index.html playLipSync() 의 목록
    # blendshapes   : 기존 index.html applyExpression() 의 수치
    #
    # 두 목록이 서로 다른 항목은 trigger_conflicts()가 잡아낸다.
    # --------------------------------------------------------

    # ========================================================
    #  표정 수치는 2026-08-18 에 잠갔다. 바꾸지 말 것.
    # ========================================================
    #
    # 이 숫자들은 계산으로 나온 것이 아니다. 사람이 화면을 보면서
    # 하나하나 밀어 보고 정한 값이다. 그래서 한 번 어긋나면
    # 무엇이 옳았는지 되돌릴 근거가 없다.
    #
    # 예를 들어
    #   윙크 blink 0.55   — 1.0 이면 윙크가 아니라 찡그린 얼굴이 된다
    #   시무룩 MTH_Sorrow — MTH_Down 은 입 가운데를 1.4cm 끌어내려
    #                       입꼬리가 아니라 입 전체가 처진다
    #   EYE_Iris_Hide     — 0.3 같은 중간값을 쓰면 눈동자가 지워지다 만
    #                       것처럼 보여 슬픔이 아니라 고장으로 읽힌다
    #
    # 잠근 값은 _expressions_locked.json 에 떠 두었다.
    # 어긋났는지는 이렇게 본다.
    #
    #   python _verify_expressions.py
    #
    # 표정을 새로 만드는 것은 괜찮다. 있던 것이 바뀌는 것만 잡는다.
    # 일부러 바꿨다면 --잠금 을 붙여 다시 떠 두어야 한다.
    # ========================================================

    expressions=[

        Expression(
            key="sorrow",
            label="슬픔",
            when="속상하거나 서운할 때. 미안하다고 할 때. 상대가 아파 보일 때. "
                 "울음까지 갈 것 없이, 마음이 내려앉는 정도면 이 얼굴이다.",
            blendshapes={"sorrow": 0.8},
            reply_emoji=["😭", "😢", "🥺", "ㅠㅠ", "ㅜㅜ", "슬퍼"],
            live_triggers=["미안해", "미안", "속상", "서운", "외로", "쓸쓸", "그리워", "울고 싶", "힘들었", "😭", "😢", "🥺", "ㅠㅠ", "ㅜㅜ", "슬퍼"],
            hold_ms=3000,
        ),

        Expression(
            key="angry",
            label="화남",
            when="선을 넘었을 때. 하지 말라고 할 때. 무시당했다고 느낄 때. "
                 "속으로 삭이는 게 아니라 드러내는 얼굴이다.",
            blendshapes={"angry": 0.8},
            reply_emoji=["😡", "😠", "💢", "화나", "짜증"],
            live_triggers=["하지 마", "하지마", "그만해", "싫어", "미워", "됐어", "😡", "😠", "💢", "화나", "짜증"],
            hold_ms=3000,
        ),

        Expression(
            key="surprised",
            label="놀람",
            when="예상 못 한 말을 들었을 때. 갑자기 닿았을 때. "
                 "짧게 스치는 얼굴이라 오래 두면 어색해진다.",
            # VRM 파일마다 이름이 다르므로 런타임에 찾는다.
            blendshapes={},
            auto_detect="surprised",
            auto_weight=0.8,
            fallback_blendshapes={"joy": 0.18, "fun": 0.12},
            reply_emoji=["😲", "😮", "😯", "😳", "헐", "대박", "진짜?"],
            live_triggers=["깜짝", "세상에", "설마", "그럴 리", "😲", "😮", "😯", "😳", "헐", "대박", "진짜?"],
            hold_ms=1000,
        ),

        # 즐거움이 먼저 온다. 순서가 곧 우선순위다 —
        # detect_expression 은 먼저 정의된 표정에서 멈춘다.
        #
        # 다이아의 말에는 'ㅋㅋ'가 거의 늘 붙는다. 웃음소리를 앞에 두면
        # "너무 좋아 ㅋㅋ" 같은 말이 전부 웃음 쪽으로 넘어간다.
        # 웃음소리는 추임새에 가깝고, 애정을 드러낸 말이면 그쪽이 먼저다.
        #
        # 어느 얼굴을 쓸지는 파일에 있는 모양이 정한다.
        # avatar.vrm 에서는 즐거움(fun)이 잔잔한 미소에 어울리고
        # 기쁨(joy)이 크게 웃는 얼굴이라, 신호를 그렇게 나눴다.
        # 세기도 그에 맞춘다 — 평소 미소는 0.8, 크게 웃을 때는 1.0.
        Expression(
            key="fun",
            label="즐거움",
            when="평소의 미소. 반갑고 다정할 때, 마음이 놓일 때. "
                 "크게 웃는 것이 아니라 잔잔히 번지는 얼굴이다.",
            # 두 얼굴을 겹쳐 짓는다.
            #
            # avatar.vrm 에서 기쁨과 즐거움은 모양이 93~95% 같은 방향이라,
            # 겹치면 같은 웃음이 더 깊어진다. 다만 두 배로 밀면 입이
            # 늘어져 보이므로, 제 얼굴을 주로 쓰고 다른 쪽은 조금만 얹는다.
            blendshapes={"fun": 0.8, "joy": 0.25},
            # 평소의 미소. 애정과 반가움이 여기다.
            reply_emoji=["🥰", "😊", "🤗", "💖", "좋아", "행복", "사랑",
                         "보고 싶", "보고싶", "설레", "다행"],
            live_triggers=["🥰", "😊", "🤗", "💖", "좋아", "행복", "사랑",
                           "보고 싶", "보고싶", "설레", "다행"],
            hold_ms=3000,
        ),

        Expression(
            key="joy",
            label="기쁨",
            when="소리 내어 웃을 때. 재미있거나 신날 때, 장난칠 때. "
                 "잔잔한 미소로는 모자란 순간이다.",
            # 크게 웃을 때도 두 얼굴을 겹친다. 이쪽은 기쁨이 주다.
            blendshapes={"joy": 1.0, "fun": 0.4},
            # 크게 웃을 때. 웃음소리와 '재밌다'가 여기다.
            reply_emoji=["🤣", "😄", "😆", "😜", "😝", "😋", "ㅋㅋ", "ㅎㅎ",
                         "재밌", "재미있", "웃겨", "웃긴", "메롱"],
            live_triggers=["🤣", "😄", "😆", "😜", "😝", "😋", "ㅋㅋ", "ㅎㅎ",
                           "재밌", "재미있", "웃겨", "웃긴", "메롱"],
            hold_ms=3000,
        ),

        Expression(
            key="neutral",
            label="평온",
            blendshapes={},
            hold_ms=0,
        ),

        # ----------------------------------------------------
        # 눈으로 짓는 표정
        #
        # 이 모델(static/avatar.vrm)이 blink / blink_l / blink_r 을
        # 가지고 있는 것을 확인하고 추가했다.
        #
        # 답변 전체의 감정으로는 고르지 않는다. 감정이 아니라 몸짓에 가깝다.
        # 대신 이모지 표시로 그 자리에서 지을 수 있다.
        # ----------------------------------------------------

        Expression(
            key="wink",
            label="윙크",
            when="둘만 아는 것을 말할 때. 농담이나 장난을 던지고 "
                 "'알지?' 하고 넘길 때. 짓궂지만 미움받지 않는 얼굴이다.",
            # 한쪽 눈을 완전히 감으면 윙크가 아니라 찡그린 것이 된다.
            # 반쯤만 감는다.
            blendshapes={"blink_l": 0.55, "joy": 0.35},
            live_triggers=["😉", "비밀이야", "비밀인데", "농담이야", "장난이야", "우리끼리", "알지?"],
            hold_ms=1200,
            is_reply_emotion=False,
        ),

        Expression(
            key="wink_r",
            label="반대쪽 윙크",
            # 윙크와 같은 값으로 둔다. 완전히 감으면 찡그린 것이 된다.
            blendshapes={"blink_r": 0.55, "joy": 0.35},
            hold_ms=1200,
            is_reply_emotion=False,
        ),

        Expression(
            key="eyes_closed",
            label="눈 감기",
            when="상대를 받아들일 때 — 괜찮다고, 알겠다고 하는 말. "
                 "또는 가슴 깊은 데 있던 진심을 꺼낼 때. "
                 "눈을 감으면 상대가 보이지 않으니 꾸미지 않는다는 표시가 된다.",
            blendshapes={"blink": 1.0},

            # 눈을 감고 말하는 것은 웃음이나 슬픔 같은 기분이 아니다.
            #
            # 둘 중 하나다.
            #   하나. 상대를 받아들일 때 — 괜찮다고, 알겠다고 하는 말.
            #   둘.  가슴 깊은 데 있던 진심을 꺼낼 때.
            # 눈을 감으면 상대를 보지 않게 되니, 꾸미지 않고 말한다는
            # 표시가 된다. 그래서 이 얼굴은 맑고 깨끗한 느낌을 준다.
            #
            # 아무 데서나 나오면 그 느낌이 죽는다. 그래서 저 두 가지에
            # 해당하는 말에만 걸리도록 신호를 좁게 적는다.
            live_triggers=[
                "😌",
                # 받아들이는 말
                "괜찮아", "괜찮아요", "알아", "알아요", "알겠어", "알겠어요",
                "이해해", "이해해요", "그럴 수 있", "그랬구나", "그랬군요",
                # 진심을 꺼내는 말
                "진심이야", "진심이에요", "솔직히", "사실은", "사실 말이야",
                "마음 깊", "속마음",
            ],
            # 진심을 말하는 동안은 눈을 뜨지 않는다. 짧으면 스치고 만다.
            hold_ms=2600,
            is_reply_emotion=False,
        ),

        # ------------------------------------------------------------
        # 부위별 모프를 직접 쓰는 표정들.
        #
        # VRM 이 내주는 표정 그룹 14개로는 못 만드는 얼굴이다.
        # 얼굴 메시의 모프 타깃 57개 중 안 쓰이던 43개를 골라 조합했다.
        # ------------------------------------------------------------

        Expression(
            key="hollow",
            label="빈 눈",
            is_reply_emotion=False,
            # 눈에서 하이라이트만 지운다. 표정은 그대로인데 눈만 죽는다.
            morphs={"Fcl_EYE_Highlight_Hide": 1.0},
            hold_ms=4000,
        ),

        Expression(
            key="hollow_smile",
            label="빈 눈으로 웃기",
            is_reply_emotion=False,
            blendshapes={"joy": 0.5},
            morphs={
                "Fcl_EYE_Highlight_Hide": 1.0,
                "Fcl_MTH_Joy": 0.7,
            },
            hold_ms=4000,
        ),

        Expression(
            key="forced_smile",
            label="억지웃음",
            is_reply_emotion=False,
            # 입은 웃는데 눈썹은 슬프다. 사람이 참을 때 짓는 얼굴이다.
            morphs={
                "Fcl_MTH_Joy": 0.85,
                "Fcl_BRW_Sorrow": 0.8,
                "Fcl_EYE_Sorrow": 0.35,
            },
            hold_ms=3500,
        ),

        Expression(
            key="wide_eyes",
            label="눈 크게 뜨기",
            is_reply_emotion=False,
            morphs={
                "Fcl_EYE_Spread": 1.0,
                "Fcl_BRW_Surprised": 0.6,
            },
            hold_ms=1600,
        ),

        Expression(
            key="pout",
            label="삐죽",
            is_reply_emotion=False,
            morphs={
                "Fcl_MTH_Down": 0.8,
                "Fcl_MTH_Small": 0.5,
                "Fcl_BRW_Sorrow": 0.55,
            },
            hold_ms=3000,
        ),

        # ------------------------------------------------------------
        # 절정 표정 — 표현용.vrm 의 얼굴에서 짓는다.
        #
        # 같은 이름의 모프인데 표현용 쪽이 더 과장돼 있다.
        # (화남 1.02cm, 즐거움 1.45cm 만큼 더 크게 움직인다)
        # 평소에는 기본 얼굴을 쓰고, 이 표정을 지을 때만 얼굴을 바꿔 낀다.
        #
        # 표현용 얼굴에서는 입모양(아이우에오)과 눈감기·윙크를 쓰지 않는다.
        # 그건 기본 얼굴이 맡는다.
        # ------------------------------------------------------------


        # ----------------------------------------------------
        # 만화·애니메이션의 얼굴
        #
        # 여기까지는 '감정 하나 = 얼굴 하나'였다. 그런데 만화는 감정을
        # 그렇게 그리지 않는다. 웃는데 눈에 빛이 없거나, 화났는데 입꼬리가
        # 한쪽만 올라가거나, 눈물이 고인 채 웃는 얼굴이 따로 있다.
        # 그 어긋남이 곧 뜻이다.
        #
        # VRM 이 겉으로 내주는 표정 그룹은 6개뿐이지만 얼굴 메시에는
        # 조각이 57개 들어 있다. 눈썹·눈·입·이를 따로 움직일 수 있으니
        # 그것들을 겹쳐 만화의 얼굴을 만든다.
        #
        # 쓸 수 있는 조각
        #   눈썹  Angry Fun Joy Sorrow Surprised
        #   눈    Natural Angry Close Close_R/L Fun Joy Joy_R/L Sorrow
        #         Surprised Spread(크게) Iris_Hide(눈동자) Highlight_Hide(빛)
        #   입    Up Down Angry Small Large Fun Joy Sorrow Surprised
        #         SkinFung(이 드러냄) SkinFung_R/L(한쪽만)
        #   이    Fung1~3 Short (드러나는 정도)
        #
        # 답변 전체의 감정으로는 쓰지 않는다(is_reply_emotion=False).
        # 이 얼굴들은 저절로 나오는 게 아니라 골라 짓는 것이기 때문이다.
        # ----------------------------------------------------

        Expression(
            key="eye_smile", label="눈웃음",
            when="정말 반가울 때. 눈이 초승달처럼 접히는 웃음이라 "
                 "입만 웃는 것과 달리 속이는 느낌이 없다.",
            morphs={
                "Fcl_EYE_Joy": 1.0,
                "Fcl_MTH_Fun": 0.7,
                "Fcl_BRW_Joy": 0.6,
            },
            live_triggers=["반가워", "보고싶었어", "역시 너"],
            hold_ms=2800, is_reply_emotion=False,
        ),

        Expression(
            key="drowsy", label="잠결",
            when="막 잠에서 깨어 아직 정신이 안 든 얼굴. "
                 "눈이 반쯤만 뜨이고 입이 조금 벌어져 있다. "
                 "깨우고 나서 대답이 나오기 전까지의 얼굴이다.",
            morphs={
                # 눈을 절반만 감는다. 1.0 이면 다시 자는 것이 된다.
                "Fcl_EYE_Close": 0.55,
                # 눈썹은 힘이 풀려 처진다
                "Fcl_BRW_Sorrow": 0.35,
                # 입이 조금 벌어져 있다. 가로로는 안 늘어난다.
                "Fcl_MTH_A": 0.22,
            },
            # 신호 낱말은 안 붙인다. 이 얼굴은 대화 내용이 아니라
            # '방금 깼다'는 상황이 부른다. 낱말을 붙이면 대화 중에
            # 엉뚱한 데서 튀어나온다.
            hold_ms=2600, is_reply_emotion=False,
        ),

        Expression(
            key="glare", label="째려보기",
            when="의심스러울 때. 못마땅한데 아직 말은 안 할 때. "
                 "눈만 가늘어지고 입은 다물려 있다.",
            morphs={
                "Fcl_EYE_Angry": 1.0,
                "Fcl_EYE_Close": 0.3,
                "Fcl_BRW_Angry": 0.5,
                "Fcl_MTH_Small": 0.6,
            },
            live_triggers=["진짜야?", "수상한데", "거짓말", "정말로?"],
            hold_ms=2400, is_reply_emotion=False,
        ),

        Expression(
            key="huff", label="새침",
            when="속으로는 신경 쓰이면서 아닌 척할 때. "
                 "고개를 돌리는 몸짓과 같이 나오면 뜻이 산다.",
            morphs={
                "Fcl_BRW_Angry": 0.35,
                "Fcl_EYE_Close": 0.45,
                "Fcl_MTH_Up": 0.5,
                "Fcl_MTH_Small": 0.4,
            },
            live_triggers=["흥", "됐거든", "관심 없어", "누가 뭐래"],
            hold_ms=2200, is_reply_emotion=False,
        ),

        Expression(
            key="fluster", label="당황",
            when="말문이 막혔을 때. 눈이 커지고 눈동자가 흔들린다. "
                 "부끄러움과는 다르다 — 이건 어쩔 줄 모르는 얼굴이다.",
            morphs={
                "Fcl_EYE_Spread": 0.8,
                "Fcl_BRW_Sorrow": 0.7,
                "Fcl_MTH_Large": 0.35,
                "Fcl_EYE_Highlight_Hide": 0.25,
            },
            live_triggers=["어어", "그게", "아니 그", "잠깐만"],
            hold_ms=1800, is_reply_emotion=False,
        ),

        Expression(
            key="teary", label="눈물 고임",
            when="울음이 터지기 직전. 눈이 커진 채 눈썹만 내려간다. "
                 "참고 있어서 더 크게 보이는 얼굴이다.",
            morphs={
                "Fcl_EYE_Spread": 0.55,
                "Fcl_EYE_Sorrow": 0.5,
                "Fcl_BRW_Sorrow": 1.0,
                "Fcl_MTH_Small": 0.5,
            },
            live_triggers=["울 것 같아", "눈물 나", "참고 있", "울컥"],
            hold_ms=3000, is_reply_emotion=False,
        ),

        Expression(
            key="wail", label="울음",
            when="참지 못하고 터졌을 때. 눈을 꽉 감고 입을 크게 벌린다.",
            morphs={
                "Fcl_EYE_Close": 1.0,
                "Fcl_BRW_Sorrow": 1.0,
                "Fcl_MTH_Large": 0.8,
                "Fcl_MTH_Sorrow": 0.6,
                "Fcl_HA_Fung1": 0.4,
            },
            live_triggers=["으앙", "엉엉", "흑흑"],
            hold_ms=3200, is_reply_emotion=False,
        ),

        Expression(
            key="grin", label="헤벌쭉",
            when="마음이 다 풀렸을 때. 감추지 않고 입이 벌어지는 웃음. "
                 "예쁘게 웃는 것이 아니라 흐물흐물해지는 얼굴이다.",
            morphs={
                # MTH_Large 는 가로로 0.84cm 벌린다. 그래서 줄이고,
                # 가로는 거의 안 늘면서 입을 여는 MTH_A 를 올린다.
                "Fcl_MTH_A": 0.85,
                "Fcl_MTH_Large": 0.3,
                "Fcl_HA_Fung1": 0.75,
                "Fcl_EYE_Joy": 0.65,
                "Fcl_BRW_Joy": 0.5,
            },
            live_triggers=["헤헤", "히히", "좋다아"],
            hold_ms=2800, is_reply_emotion=False,
        ),

        Expression(
            key="gloom", label="시무룩",
            when="크게 슬프지는 않은데 기운이 빠졌을 때. "
                 "눈썹과 입꼬리가 같이 내려간다.",
            morphs={
                # MTH_Down 은 입 가운데를 1.4cm 나 끌어내려서
                # 입꼬리가 아니라 입 전체가 처진다. MTH_Sorrow 가
                # 입꼬리 쪽이라 그걸 쓴다.
                "Fcl_MTH_Sorrow": 1.0,
                "Fcl_MTH_Small": 0.3,
                "Fcl_BRW_Sorrow": 0.8,
                "Fcl_EYE_Sorrow": 0.4,
            },
            live_triggers=["시무룩", "기운 없", "재미없", "심심해"],
            hold_ms=2600, is_reply_emotion=False,
        ),

        Expression(
            key="shock", label="경악",
            when="믿기지 않을 때. 눈이 끝까지 열리고 빛이 빠진다. "
                 "놀람보다 한 단계 위다.",
            morphs={
                "Fcl_EYE_Spread": 1.0,
                "Fcl_BRW_Surprised": 1.0,
                "Fcl_MTH_Surprised": 0.8,
                "Fcl_EYE_Highlight_Hide": 0.55,
            },
            live_triggers=["말도 안", "거짓말이지", "그럴 리가"],
            hold_ms=1600, is_reply_emotion=False,
        ),

        Expression(
            key="sigh_face", label="체념",
            when="더 따질 마음이 없어졌을 때. 눈을 감고 한숨을 쉬는 얼굴. "
                 "화가 풀린 것이 아니라 접은 것이다.",
            morphs={
                "Fcl_EYE_Close": 0.8,
                "Fcl_BRW_Sorrow": 0.5,
                "Fcl_MTH_Down": 0.35,
            },
            live_triggers=["하아", "됐다 그래", "말을 말자", "어쩔 수 없"],
            hold_ms=2400, is_reply_emotion=False,
        ),

        Expression(
            key="soft_gaze", label="지그시 보기",
            when="말없이 바라볼 때. 눈이 반쯤 감기고 입꼬리만 조금 올라간다. "
                 "가장 조용한 애정 표현이다.",
            morphs={
                "Fcl_EYE_Close": 0.35,
                "Fcl_MTH_Up": 0.45,
                "Fcl_BRW_Joy": 0.3,
            },
            live_triggers=["가만히", "그냥 보고", "이렇게 있"],
            hold_ms=3000, is_reply_emotion=False,
        ),

        Expression(
            key="peak_joy", label="절정 기쁨", source="special",
            blendshapes={"joy": 1.0, "fun": 0.4},
            # 표현용 얼굴을 안 쓸 때도 절정으로 보여야 한다.
            # 표정 그룹만으로는 기쁨(1.0)과 똑같아져서 구별이 안 된다.
            #
            # 다만 겹치는 조각을 얹으면 안 된다. ALL_* 안에는 이미 부위
            # 모프가 들어 있어서(입 0.87, 눈 0.50 만큼 같은 방향),
            # EYE_Joy 나 MTH_Joy 를 또 얹으면 그 자리가 두 배로 밀려
            # 얼굴이 일그러진다. 실제로 1.6~2.5배까지 부풀었었다.
            #
            # 그래서 ALL_* 이 하지 않는 것만 얹는다 —
            # 입을 더 벌리기, 이 드러내기, 눈 크게, 빛 지우기.
            # 지금은 보통 표정의 1.1~1.45배에서 멈춘다.
            morphs={"Fcl_MTH_Large": 0.45, "Fcl_HA_Fung1": 0.6},
            is_reply_emotion=False, hold_ms=3500,
        ),
        Expression(
            key="peak_fun", label="절정 즐거움", source="special",
            blendshapes={"fun": 1.0, "joy": 0.35},
            morphs={"Fcl_MTH_Large": 0.3, "Fcl_HA_Fung1": 0.45,
                    "Fcl_EYE_Spread": 0.15},
            is_reply_emotion=False, hold_ms=3500,
        ),
        Expression(
            key="peak_angry", label="절정 화남", source="special",
            blendshapes={"angry": 1.0},
            morphs={"Fcl_BRW_Angry": 0.25, "Fcl_HA_Fung1": 0.35,
                    "Fcl_EYE_Highlight_Hide": 0.3},
            is_reply_emotion=False, hold_ms=3500,
        ),
        Expression(
            # 눈동자를 반쯤 지우던 것(EYE_Iris_Hide 0.3)을 뺐다.
            # 눈이 지워지다 만 것처럼 보여서 슬픔이 아니라 고장으로 읽혔다.
            # 대신 입가를 내려 슬픔을 깊게 한다.
            key="peak_sorrow", label="절정 슬픔", source="special",
            blendshapes={"sorrow": 1.0},
            morphs={"Fcl_BRW_Sorrow": 0.35, "Fcl_MTH_Sorrow": 0.5},
            is_reply_emotion=False, hold_ms=3500,
        ),
        Expression(
            key="peak_surprised", label="절정 놀람", source="special",
            auto_detect="surprised", auto_weight=1.0,
            fallback_blendshapes={"surprised": 1.0},
            morphs={"Fcl_EYE_Spread": 0.7, "Fcl_EYE_Highlight_Hide": 0.5},
            is_reply_emotion=False, hold_ms=2000,
        ),
    ],

    # --------------------------------------------------------
    # 행동
    # --------------------------------------------------------

    behavior={
        "sleep_timeout_sec": 120,
        "first_talk_timeout_sec": 120,







        # 말할 때의 얼굴
        #
        # 표정과 립싱크가 같은 입을 두고 다툰다. 웃는 입(MTH_Fun)이
        # 벌어져 있는데 그 위에 '아'(MTH_A)가 얹히면 입이 두 겹으로
        # 일그러진다. 웃으면서 말할 때 어색했던 것이 이것 때문이다.
        #
        # 그래서 말하는 동안에는 입을 립싱크에 넘긴다.
        # 표정은 눈과 눈썹만 맡는다 — 그것만으로도 감정은 다 드러난다.
        #
        # 표정 그룹(ALL_*)은 눈·눈썹·입이 한 덩어리라 입만 뺄 수 없다.
        # 그래서 말하는 동안에는 그룹 대신 부위 조각을 직접 쓴다.
        "speaking": {
            "group_to_parts": {
                "joy": ["Fcl_EYE_Joy", "Fcl_BRW_Joy"],
                "fun": ["Fcl_EYE_Fun", "Fcl_BRW_Fun"],
                "angry": ["Fcl_EYE_Angry", "Fcl_BRW_Angry"],
                "sorrow": ["Fcl_EYE_Sorrow", "Fcl_BRW_Sorrow"],
                "surprised": ["Fcl_EYE_Surprised", "Fcl_BRW_Surprised"],
            },
            # 만화 표정처럼 조각으로 만든 얼굴에서는 이 조각들만 빼둔다
            "mouth_prefixes": ["Fcl_MTH_", "Fcl_HA_"],
        },

        # 입 모양
        #
        # 말할 때 입이 얼마나 벌어질지. 숫자는 실제로 재서 넣었다.
        # (avatar.vrm 얼굴에서 입꼬리 정점을 골라 모프별로 폭을 잼)
        #
        #   다물었을 때 입꼬리 사이   5.84cm
        #   '이' 를 끝까지 세우면      6.01cm  (+0.17)
        #   즐거움 표정              6.16cm  (+0.32)
        #   기쁨 표정                6.28cm  (+0.44)
        #
        # 말하느라 벌어지는 폭이 즐거움 표정의 입 폭을 넘지 않게 한다.
        #
        # 재는 것은 '말 때문에 벌어진 몫' 이다. 표정이 이미 벌려 놓은 것까지
        # 합쳐 재면, 웃으면서 말할 때 남는 몫이 0 이 되어 입이 아예
        # 움직이지 않게 된다. 웃으며 말하면 입이 조금 더 벌어지는 게 맞다.
        "lipsync": {
            # 모음 하나의 기본 세기.
            #
            # 예전에는 0.16~0.24 였다. 그 정도로는 입이 0.4mm 움직여서
            # 말하는지 아닌지 티가 안 났다. 아래 상한이 막아 주므로
            # 넉넉히 올린다.
            "amount": 0.9,
            # 표정이 입을 이미 벌리고 있을 때는 조금 낮춘다
            "amount_expressing": 0.6,

            # 넘지 않을 폭. 이 표정의 입 가로가 상한이다.
            "cap_expression": "fun",

            # 세기 1.0 일 때 입꼬리 사이가 늘어나는 폭(m). 음수는 오므라든다.
            "width_per_unit": {
                "a": 0.0002,
                "i": 0.0017,
                "u": -0.0015,
                "e": 0.0008,
                "o": -0.0010,
            },

            # 표정이 이미 벌려 놓은 폭(m). 상한을 정하는 데 쓴다.
            "width_expression": {
                "neutral": 0.0,
                "fun": 0.0032,
                "joy": 0.0044,
                "peak_fun": 0.0040,
                "peak_joy": 0.0048,
            },
        },

        # 기분
        #
        # 지금까지 표정은 한 번 나왔다 사라질 뿐이었다. 그래서 '화가 나 있다'
        # 는 상태가 없었고, 풀어줄 대상도 없었다. 여기서 그걸 들고 있는다.
        #
        # 기분은 친밀도와 다르다. 친밀도는 둘이 얼마나 가까운지이고,
        # 기분은 지금 이 순간 상해 있는지다. 사이가 아무리 좋아도
        # 방금 심한 말을 들었으면 상해 있을 수 있다.
        #
        # 시간이 지나면 저절로 풀린다. 쓰다듬으면 더 빨리 풀린다.
        "mood": {
            # 얼마나 상할 수 있는지
            "max": 6,

            # 상하는 일들
            "hurt": {
                "denied": 2,      # 아직 허락 안 된 자리를 만졌을 때
                "negative": 2,    # 모진 말을 들었을 때
                "words": 3,       # 상처 주는 말을 들었을 때
            },

            # 저절로 풀리는 데 걸리는 시간. 한 칸당 3분.
            "cool_sec": 180,

            # 쓰다듬어 풀어주기
            "soothe": {
                "default": 1,
                # 다정한 자리일수록 많이 풀린다
                "zones": {"head": 2, "face": 2, "hand": 2},
                # 상해 있는데 허락 안 된 곳을 만지면 오히려 더 상한다
                "denied": -2,
            },

            # 어느 정도로 상했는지에 따라 얼굴과 태도가 달라진다
            "levels": [
                {
                    "at": 1,
                    "label": "조금 상함",
                    "expression": "pout",
                    "note": "조금 상해 있다. 말은 하지만 평소보다 짧고, "
                            "먼저 다가가지 않는다. 상대가 달래면 못 이기는 척 풀린다.",
                    "soothed": {
                        "expression": "fun",
                        "lines": {
                            "polite": ["…조금 나아졌어요.", "치사해요, 이런 걸로 풀리다니."],
                            "casual": ["…조금 풀렸어.", "치사해. 이런 걸로 풀리고."],
                        },
                    },
                },
                {
                    "at": 3,
                    "label": "많이 상함",
                    "expression": "angry",
                    "note": "많이 상해 있다. 대답이 뚝뚝 끊기고 목소리가 낮다. "
                            "왜 그러냐고 물으면 아무것도 아니라고 한다. "
                            "쉽게 풀리지 않지만, 계속 달래면 조금씩 누그러진다.",
                    "soothed": {
                        "expression": "pout",
                        "lines": {
                            "polite": ["…아직 다 안 풀렸어요.", "이런다고 넘어갈 줄 알았어요?"],
                            "casual": ["…아직 다 안 풀렸어.", "이런다고 넘어갈 줄 알아?"],
                        },
                    },
                },
                {
                    "at": 5,
                    "label": "돌아섰다",
                    "expression": "angry",
                    "motion": "turn_back",
                    "note": "단단히 상했다. 등을 돌리고 있다. 말수가 아주 적고, "
                            "붙잡으면 더 밀어낸다. 그래도 계속 곁에 있으면 결국 돌아본다.",
                    "soothed": {
                        "expression": "sorrow",
                        "lines": {
                            "polite": ["…가지는 마세요.", "아직 화났어요. 그래도… 있어 줘요."],
                            "casual": ["…가지는 마.", "아직 화났어. 그래도… 있어 줘."],
                        },
                    },
                },
            ],

            # 다 풀렸을 때
            "clear": {
                "expression": "joy",
                "motion": "shy",
                "lines": {
                    "polite": ["…다 풀렸어요. 이제 됐어요.", "치사해요. 결국 이렇게 되네요."],
                    "casual": ["…다 풀렸어. 이제 됐어.", "치사해. 결국 이렇게 되네."],
                },
            },
        },

        # 같이 걷자고 할 때 — 산책·데이트
        #
        # 평소에는 제자리에 서 있다가(대화 중에 걸어 다니면 이야기하다 말고
        # 떠나는 꼴이 된다) 같이 걷자고 하면 발이 풀린다.
        # 그만하자고 하면 다시 멈춘다.
        "walk_invite": {
            "start": ["산책", "같이 걷", "걸을래", "걷자", "걸어보자",
                      "데이트", "나가자", "바람 쐬", "돌아다니자",
                      "따라와", "가자"],
            "stop": ["그만 걷", "멈춰", "여기 앉", "앉자", "쉬자",
                     "그만 가", "돌아가자", "여기까지"],
            # 걷자고 했을 때 짓는 얼굴
            "expression": "fun",
        },

        # 상황 보기
        #
        # 괄호로 상황을 쓸 수 있게 해 두었는데, 매번 생각해 내야 하는
        # 것이 일이다. 그래서 지금 흐름에 맞는 것을 몇 개 지어 준다.
        #
        # 짓는 것은 모델이지만 **고르는 것은 사람이다.** 클릭하지 않으면
        # 아무 일도 안 일어나고, 직접 쓰는 칸도 따로 있다.
        # 다이아가 제 이야기를 스스로 진행시키면 그건 대화가 아니다.
        "suggest": {
            "enabled": True,
            "count": 4,

            # 지금 사이와 흐름에 맞는 것을 짓게 한다.
            # 말이 아니라 **몸으로 하는 일** 이어야 한다 — 말은
            # 입력칸에 직접 쓰면 되고, 괄호는 행동을 위한 자리다.
            "prompt": (
                "지금 이 대화에서 상대가 할 만한 행동을 {count}개 지어라.\n"
                "\n"
                "규칙:\n"
                "- 말이 아니라 몸으로 하는 일만. 대사를 쓰지 마라.\n"
                "- 한 줄에 하나씩, 괄호 없이, 12자 안팎으로 짧게.\n"
                "- '{name}의' 로 시작하거나 '{name}에게' 처럼 이름을 넣어도 된다.\n"
                "- 번호나 기호를 붙이지 마라. 설명도 하지 마라.\n"
                "- 지금 사이와 방금 나눈 이야기에 어울리는 것으로.\n"
                "- 넷이 서로 달라야 한다. 비슷한 것을 늘어놓지 마라.\n"
            ),

            # 이 글자가 들어간 줄은 버린다 — 모델이 설명을 붙일 때가 있다
            "drop": ["다음은", "예시", "행동 4", "규칙", "물론", "알겠"],

            # 한 줄이 이보다 길면 상황이 아니라 소설이다
            "max_len": 30,
        },

        # 가까이 오라고 할 때
        #
        # 평소 서는 거리(follow_near 1.35)는 이야기하기 좋은 사이지만
        # 손이 닿지는 않는다(reach 0.95). 그래서 만지려면 다가가야 하는데,
        # 걸어가는 대신 **부를 수도 있어야** 한다.
        #
        # 부르면 come_near(0.72)까지 온다. 예전에 서던 자리다.
        # 그 자리에서는 손이 닿는다.
        "come_closer": {
            "near": ["가까이 와", "가까이 오", "이리 와", "이리 오",
                     "이리로", "옆에 와", "옆으로 와", "다가와", "다가 와",
                     "가까이 있어", "더 와", "붙어", "안아 줘", "안아줘"],
            "away": ["저리 가", "떨어져", "멀어져", "물러나", "물러서",
                     "저만치", "좀 떨어", "뒤로 가"],
            # 부르면 짓는 얼굴
            "expression": "fun",
        },

        # 상대가 "알겠어?" 하고 확인할 때는 고개를 끄덕인다.
        #
        # 말로 "응" 하는 것보다 끄덕이는 쪽이 먼저 나오는 반응이다.
        # 이건 다이아의 말에서 찾는 게 아니라 상대의 말에서 찾는다.
        "understood": {
            "motion": "nod",
            "words": ["알겠어?", "알겠지?", "알았어?", "알았지?",
                      "이해했어?", "이해돼?", "알아들었어?", "맞지?",
                      "그렇지?", "알겠나?", "알겠어요?", "알겠죠?",
                      "아시겠어요?", "아시겠죠?", "이해하셨어요?"],
        },

        # 상처받았을 때 — 어떤 마음인지에 따라 몸이 다르게 움직인다.
        #
        # 슬프면 몸을 감싸거나 등을 돌리고, 화가 나면 팔짱을 끼고,
        # 삐치면 삐죽인다. 같은 '서운함'도 어느 쪽으로 기우느냐가 다르다.
        #
        # 등을 돌렸을 때 얼마나 오래 그러고 있을지도 마음의 크기가 정한다.
        # 조금 서운하면 금방 돌아보고, 크게 상했으면 한참 그대로다.
        "hurt": [
            {
                "kind": "angry",
                "expression": "angry",
                "motion": "cross",
                "linger_ms": 900,
                "words": ["화났어", "화나", "짜증", "됐어", "하지 마",
                          "그만해", "듣기 싫"],
            },
            {
                "kind": "sorrow",
                "expression": "sorrow",
                "motion": "turn_back",
                # 크게 상했다. 한참 등을 돌린 채 있는다.
                "linger_ms": 2600,
                "words": ["상처", "속상", "서운했", "너무해", "미워",
                          "울고 싶", "실망"],
            },
            {
                "kind": "pout",
                "expression": "pout",
                "motion": "cross",
                "linger_ms": 600,
                "words": ["삐졌", "삐질", "흥", "치사", "몰라", "서운"],
            },
        ],

        # 쑥스러움의 세기.
        #
        # 같은 '쑥스럽다'도 정도가 다르다. 말끝에 슬쩍 붙이는 것과
        # 얼굴을 못 들 만큼인 것이 같은 몸짓일 수는 없다.
        #
        # 세기는 말이 정한다. 낱말이 먼저 걸리는 순서대로 본다.
        # 얼굴을 가리는 단계에서만 표정이 함께 간다 —
        # 그 아래는 웃으면서 쑥스러워할 수 있어야 한다.
        "shy_levels": [
            {
                "level": 3,
                "motion": "cover",
                "expression": "surprised",
                "words": ["부끄러워 죽", "너무 부끄", "창피해", "못 보겠",
                          "얼굴이 화끈", "쥐구멍"],
            },
            {
                "level": 2,
                "motion": "shy",
                "expression": "surprised",
                "words": ["정말 부끄", "많이 부끄", "너무 쑥스", "부끄럽잖",
                          "놀리지 마"],
            },
            {
                "level": 1,
                "motion": "shy",
                # 표정 없음 — 웃으면서 쑥스러워한다
                "expression": None,
                "words": ["쑥스", "부끄", "민망", "쑥쓰"],
            },
        ],

        # ------------------------------------------------------------
        # 괄호 속 상황을 얼굴과 몸으로 옮긴다
        #
        # 다이아가 (멋쩍은 듯 눈동자가 흔들리며) 라고 적으면 그 말이
        # 화면에는 나오는데 얼굴은 가만히 있었다. 적어 놓고 안 하는 것이
        # 안 적은 것보다 더 어색하다 — 글은 흔들린다는데 눈은 멀쩡하다.
        #
        # 이름표((팔짱) 같은 것)는 정확히 맞아야 하지만, 여기는 문장이다.
        # 그래서 낱말의 앞동강만 본다 — '멋쩍' 하나로 멋쩍은·멋쩍어·멋쩍게가
        # 다 걸린다. 한국어는 뒤가 바뀌고 앞이 남는다.
        #
        # 위에 적은 것이 먼저 이긴다. **좁은 것을 위에 둘 것** —
        # '웃' 을 위에 두면 '억지로 웃' 도 '눈웃음' 도 전부 즐거움이 된다.
        #
        # 쑥스러움은 여기서 정하지 않는다. 세기를 가리는 판단이 이미
        # 있으므로(shy_levels) 그쪽으로 넘긴다. 두 벌을 두면 어긋난다.
        "act_reads": [

            # --- 몸이 하는 일. 이름으로 안 부르고 문장으로 적었을 때 ---
            {"words": ["팔짱"], "motion": "cross"},
            {"words": ["등을 돌", "등을 보이", "돌아선", "돌아서 버",
                       "뒤돌아"], "motion": "turn_back"},
            {"words": ["얼굴을 가리", "손으로 얼굴", "얼굴을 감싸",
                       "두 손으로 얼굴"], "motion": "cover"},
            {"words": ["기지개"], "motion": "stretch"},
            {"words": ["손을 흔", "손인사", "손을 들어 인사"],
             "motion": "wave"},
            {"words": ["고개를 젓", "고개를 가로", "고개를 절레"],
             "motion": "shake"},
            {"words": ["고개를 끄덕", "끄덕인", "끄덕이며"], "motion": "nod"},

            # --- 우는 얼굴 ---
            {"words": ["울음을 터", "엉엉", "울어 버", "흐느"],
             "expression": "wail"},
            {"words": ["눈물이 고", "눈물이 맺", "글썽", "눈시울",
                       "울먹", "훌쩍"], "expression": "teary"},

            # --- 웃는 얼굴. 좁은 것부터 ---
            {"words": ["눈웃음", "눈이 초승달", "눈이 접"],
             "expression": "eye_smile"},
            {"words": ["헤벌", "헤실", "입이 귀에"], "expression": "grin"},
            {"words": ["억지로 웃", "억지웃음", "쓴웃음", "씁쓸",
                       "웃는 시늉"], "expression": "forced_smile"},
            {"words": ["눈은 웃지 않", "눈이 웃지 않", "눈에 빛이 없는 채로 웃"],
             "expression": "hollow_smile"},
            {"words": ["웃음을 터", "크게 웃", "활짝 웃", "깔깔", "박장"],
             "expression": "joy"},
            {"words": ["웃", "미소", "입꼬리가 올라", "입꼬리를 올"],
             "expression": "fun"},

            # --- 빈 눈 ---
            {"words": ["초점이 없", "초점을 잃", "눈에 빛이 없", "빈 눈",
                       "텅 빈"], "expression": "hollow"},

            # --- 놀란 얼굴 ---
            # 사람 말에 진짜로 놀란 때만이다. 이 규칙은 위에서 정한 것과
            # 같다 — 잠에서 깰 때, 부끄러울 때, 진짜 놀랐을 때.
            {"words": ["입을 떡", "말문이 막", "얼어붙", "경악"],
             "expression": "shock"},
            {"words": ["흠칫", "화들짝", "움찔", "화들"],
             "expression": "surprised"},
            {"words": ["눈을 크게", "눈이 커", "눈을 동그랗", "눈을 휘둥"],
             "expression": "wide_eyes"},

            # --- 흔들리는 얼굴 ---
            {"words": ["눈동자가 흔들", "시선이 흔들", "눈길을 피", "눈을 피",
                       "말을 더듬", "어쩔 줄", "허둥", "당황"],
             "expression": "fluster"},

            # --- 가라앉는 얼굴 ---
            {"words": ["어깨가 처", "풀이 죽", "시무룩", "고개를 숙",
                       "고개가 떨"], "expression": "gloom"},
            {"words": ["한숨", "체념", "포기한 듯", "고개를 저으며 웃"],
             "expression": "sigh_face"},

            # --- 뾰족한 얼굴 ---
            {"words": ["볼을 부풀", "입술을 내밀", "삐죽", "삐친", "삐져"],
             "expression": "pout"},
            {"words": ["새침", "톡 쏘", "쌀쌀맞", "콧방귀", "흥,"],
             "expression": "huff"},
            {"words": ["째려", "노려", "눈을 가늘", "눈초리"],
             "expression": "glare"},

            # --- 조용한 얼굴 ---
            {"words": ["지그시", "물끄러미", "빤히", "가만히 바라",
                       "오래 바라", "오래 본", "말없이 바라", "가만히 본",
                       "말없이 본"], "expression": "soft_gaze"},
            {"words": ["눈을 감", "눈을 지그시 감"], "expression": "eyes_closed"},
            {"words": ["하품", "졸린", "졸음", "눈을 비비"],
             "expression": "drowsy"},

            # --- 남은 감정들 ---
            {"words": ["울컥", "서러", "속상", "슬픈 얼굴", "울 것 같"],
             "expression": "sorrow"},
            {"words": ["이를 악", "주먹을 쥐", "화난 얼굴", "발끈", "울그락"],
             "expression": "angry"},
        ],

        # 어느 낱말이 쑥스러움인가.
        #
        # 걸리면 세기 판단(shy_levels)으로 넘긴다. 낮으면 쑥스러워하기만,
        # 세면 얼굴 가리기까지 — 그 갈래를 여기서 다시 만들지 않는다.
        "act_shy_words": ["멋쩍", "쑥스", "쑥쓰", "부끄", "수줍", "민망",
                          "볼이 붉", "얼굴이 붉", "얼굴을 붉", "귀가 빨",
                          "볼이 발", "낯이 뜨"],

        # 자다 깼을 때 어떻게 반응할지. 사이가 얼마나 깊은지로 갈린다.
        #
        #   낮으면  : 놀라기만 하고 곧 대화. 자다 깬 사람에게 반가움이 없다.
        #   보통    : 기쁨 + 기지개. 잠을 털고 이야기를 시작한다.
        #   깊으면  : 기지개까지 켠 뒤 손을 흔들며 반긴다.
        "wake": {
            # 놀라는 것은 여기까지다.
            #
            # 사이가 없다시피 하면 누가 깨우는지도 모르니 놀란다.
            # 조금이라도 정이 들면 깨우는 사람이 누구인지 알아서 안 놀란다.
            "surprise_upto": 0,

            # 기지개는 이만큼부터. 친구가 되면 잠을 털며 일어난다.
            "stretch_from": 40,

            # 이 위면 기지개 뒤에 손까지 흔든다 (사랑)
            "warm_from": 160,
        },

        # 잠들지 않는 단계에서 다음 말을 꺼내기까지 기다리는 시간.
        # 잠드는 시간보다 짧아야 한다. 대답이 없는 동안 말이 이어져야 하므로
        # 2분을 다 기다리면 끊긴 것처럼 보인다.
        "nudge_timeout_sec": 45,
        # 자다 깰 때 놀란 표정을 얼마나 짧게 스칠지.
        #
        # 놀람이 오래 남으면 그 다음 얼굴이 묻힌다. 진짜로 놀란 사람의
        # 얼굴도 0.3초쯤이면 다음 표정으로 넘어간다.
        "wake_surprise_ms": 300,
        "lipsync_tick_ms": 100,
        "blink_min_sec": 2.0,
        "blink_max_sec": 6.0,
    },

    # --------------------------------------------------------
    # 서 있는 기준 자세
    #
    # 기존 index.html 의 resetToAttentionPose() 가
    # leftUpperArm.z = 1.2rad, rightUpperArm.z = -1.2rad 로 팔을 내리던 것을
    # 도 단위(약 68.75도)로 옮기고, 팔꿈치를 살짝 안으로 모았다.
    # --------------------------------------------------------

    # 어깨와 손은 값이 0이지만 반드시 여기 적어 둔다.
    # 여기 없는 본은 동작이 끝나도 되돌아갈 곳이 없어서,
    # 그 본을 쓰는 동작(shy 의 leftShoulder, wave 의 rightHand)이
    # 중간에 끊기면 그 자세 그대로 굳어 버린다.
    base_pose={
        "leftShoulder": [0, 0, 0],
        "rightShoulder": [0, 0, 0],
        "leftUpperArm": [0, 0, 68.75],
        "rightUpperArm": [0, 0, -68.75],
        "leftLowerArm": [0, 0, 10],
        "rightLowerArm": [0, 0, -10],
        "leftHand": [0, 0, 0],
        "rightHand": [0, 0, 0],

        # 손가락 — 힘을 뺀 손은 가만히 있어도 마디마다 조금씩 굽어 있다.
        # 이걸 비워 두면 손이 판자처럼 쫙 펴진 채로 있는다.
        # 오므리는 축은 왼손 z(+), 오른손 z(-). 엄지만 y 축이다. 실측값이다.
        # 새끼로 갈수록 더 굽힌다. 다시 만들려면 _fit_hand.py 를 돌린다.
        "leftThumbProximal": [10.0, 15.0, 0.0], "leftThumbIntermediate": [12.0, 0.0, 0.0], "leftThumbDistal": [8.0, 0.0, 0.0],
        "leftIndexProximal": [0.0, -5.0, 11.0], "leftIndexIntermediate": [0.0, 0.0, 26.0], "leftIndexDistal": [0.0, 0.0, 15.0],
        "leftMiddleProximal": [0.0, -1.0, 13.0], "leftMiddleIntermediate": [0.0, 0.0, 30.0], "leftMiddleDistal": [0.0, 0.0, 17.0],
        "leftRingProximal": [0.0, 3.0, 15.0], "leftRingIntermediate": [0.0, 0.0, 34.0], "leftRingDistal": [0.0, 0.0, 19.0],
        "leftLittleProximal": [0.0, 7.0, 17.0], "leftLittleIntermediate": [0.0, 0.0, 37.0], "leftLittleDistal": [0.0, 0.0, 21.0],

        "rightThumbProximal": [10.0, -15.0, 0.0], "rightThumbIntermediate": [12.0, 0.0, 0.0], "rightThumbDistal": [8.0, 0.0, 0.0],
        "rightIndexProximal": [0.0, 5.0, -11.0], "rightIndexIntermediate": [0.0, 0.0, -26.0], "rightIndexDistal": [0.0, 0.0, -15.0],
        "rightMiddleProximal": [0.0, 1.0, -13.0], "rightMiddleIntermediate": [0.0, 0.0, -30.0], "rightMiddleDistal": [0.0, 0.0, -17.0],
        "rightRingProximal": [0.0, -3.0, -15.0], "rightRingIntermediate": [0.0, 0.0, -34.0], "rightRingDistal": [0.0, 0.0, -19.0],
        "rightLittleProximal": [0.0, -7.0, -17.0], "rightLittleIntermediate": [0.0, 0.0, -37.0], "rightLittleDistal": [0.0, 0.0, -21.0],
    },

    # --------------------------------------------------------
    # 동작
    #
    # 키에 적히지 않은 본은 base_pose 를 따른다.
    # --------------------------------------------------------

    motions=[

        Motion(
            key="idle",
            label="가만히",
            description="숨 쉬며 살짝 흔들리는 기본 상태",
            duration=4.0,
            loop=True,
            keys=[
                {"t": 0.0, "bones": {
                    "spine": [0, 0, 0], "chest": [0, 0, 0], "head": [0, 0, 0],
                    "leftUpperArm": [0, 0, 68.75], "rightUpperArm": [0, 0, -68.75]}},
                {"t": 2.0, "bones": {
                    "spine": [1.5, 2, 0], "chest": [1, 1.5, 0], "head": [-1, -3, 1],
                    "leftUpperArm": [0, 0, 66.5], "rightUpperArm": [0, 0, -66.5]}},
                {"t": 4.0, "bones": {
                    "spine": [0, 0, 0], "chest": [0, 0, 0], "head": [0, 0, 0],
                    "leftUpperArm": [0, 0, 68.75], "rightUpperArm": [0, 0, -68.75]}},
            ],
        ),

        # 오른팔 아래팔(팔꿈치)의 축은 두 방향으로 나뉜다. 왼팔은 부호가 반대다.
        #
        #   y (+) : 앞으로 접힌다  — 팔을 내린 상태에서 손을 몸 앞으로 (shy)
        #   z (+) : 위로 접힌다    — 팔을 옆으로 든 상태에서 손을 위로 (wave)
        #
        # 팔을 머리 위로 든 채 y 를 주면 화면 안쪽으로 접혀 정면에서는
        # 팔이 곧게 뻗은 것처럼 보인다. 그래서 손인사는 z 를 쓴다.
        Motion(
            key="wave",
            label="손인사",
            description="오른팔을 올려 손을 흔든다",
            duration=2.6,
            loop=False,
            # 반가운 미소다. 크게 웃는 얼굴(기쁨)이 아니다.
            expression="fun",
            keys=[
                {"t": 0.0, "bones": {
                    "rightUpperArm": [0, 0, -68.75], "rightLowerArm": [0, 0, -10],
                    "rightHand": [0, 0, 0], "head": [0, 0, 0], "chest": [0, 0, 0]}},
                # 손바닥이 정면(모델 기준 -Z)을 보도록 팔 축으로 90도 비튼다.
                # 팔을 드는 회전은 z축이라 x축 트위스트 값에는 영향을 주지 않는다.
                {"t": 0.5, "bones": {
                    "rightUpperArm": [0, 0, 14], "rightLowerArm": [0, 0, 68],
                    "rightHand": [90, 0, 0], "head": [0, -6, 5], "chest": [0, -5, 0]}},
                {"t": 0.9, "bones": {
                    "rightUpperArm": [0, 0, 26], "rightLowerArm": [0, 0, 98],
                    "rightHand": [90, 0, 0], "head": [0, -6, 5], "chest": [0, -5, 0]}},
                {"t": 1.3, "bones": {
                    "rightUpperArm": [0, 0, 14], "rightLowerArm": [0, 0, 68],
                    "rightHand": [90, 0, 0], "head": [0, -6, 5], "chest": [0, -5, 0]}},
                {"t": 1.7, "bones": {
                    "rightUpperArm": [0, 0, 26], "rightLowerArm": [0, 0, 98],
                    "rightHand": [90, 0, 0], "head": [0, -6, 5], "chest": [0, -5, 0]}},
                {"t": 2.1, "bones": {
                    "rightUpperArm": [0, 0, 18], "rightLowerArm": [0, 0, 82],
                    "rightHand": [90, 0, 0], "head": [0, -4, 3], "chest": [0, -3, 0]}},
                {"t": 2.6, "bones": {
                    "rightUpperArm": [0, 0, -68.75], "rightLowerArm": [0, 0, -10],
                    "rightHand": [0, 0, 0], "head": [0, 0, 0], "chest": [0, 0, 0]}},
            ],
        ),

        Motion(
            key="walk",
            label="걷기",
            description="한 걸음 주기. 재생하는 동안 실제로 이동한다",
            duration=1.0,
            loop=True,
            locomotes=True,
            ease="linear",
            keys=[
                {"t": 0.0, "bones": {
                    "leftUpperLeg": [26, 0, 0], "leftLowerLeg": [-12, 0, 0],
                    "rightUpperLeg": [-20, 0, 0], "rightLowerLeg": [-30, 0, 0],
                    "leftUpperArm": [-18, 0, 72], "rightUpperArm": [18, 0, -72],
                    "leftLowerArm": [0, 0, 14], "rightLowerArm": [0, 0, -14],
                    "spine": [2, -4, 0], "chest": [0, 4, 0], "head": [0, 0, 0]}},
                {"t": 0.25, "bones": {
                    "leftUpperLeg": [4, 0, 0], "leftLowerLeg": [-6, 0, 0],
                    "rightUpperLeg": [2, 0, 0], "rightLowerLeg": [-14, 0, 0],
                    "leftUpperArm": [0, 0, 70], "rightUpperArm": [0, 0, -70],
                    "leftLowerArm": [0, 0, 12], "rightLowerArm": [0, 0, -12],
                    "spine": [2, 0, 0], "chest": [0, 0, 0], "head": [0, 0, 0]}},
                {"t": 0.5, "bones": {
                    "leftUpperLeg": [-20, 0, 0], "leftLowerLeg": [-30, 0, 0],
                    "rightUpperLeg": [26, 0, 0], "rightLowerLeg": [-12, 0, 0],
                    "leftUpperArm": [18, 0, 72], "rightUpperArm": [-18, 0, -72],
                    "leftLowerArm": [0, 0, 14], "rightLowerArm": [0, 0, -14],
                    "spine": [2, 4, 0], "chest": [0, -4, 0], "head": [0, 0, 0]}},
                {"t": 0.75, "bones": {
                    "leftUpperLeg": [2, 0, 0], "leftLowerLeg": [-14, 0, 0],
                    "rightUpperLeg": [4, 0, 0], "rightLowerLeg": [-6, 0, 0],
                    "leftUpperArm": [0, 0, 70], "rightUpperArm": [0, 0, -70],
                    "leftLowerArm": [0, 0, 12], "rightLowerArm": [0, 0, -12],
                    "spine": [2, 0, 0], "chest": [0, 0, 0], "head": [0, 0, 0]}},
                {"t": 1.0, "bones": {
                    "leftUpperLeg": [26, 0, 0], "leftLowerLeg": [-12, 0, 0],
                    "rightUpperLeg": [-20, 0, 0], "rightLowerLeg": [-30, 0, 0],
                    "leftUpperArm": [-18, 0, 72], "rightUpperArm": [18, 0, -72],
                    "leftLowerArm": [0, 0, 14], "rightLowerArm": [0, 0, -14],
                    "spine": [2, -4, 0], "chest": [0, 4, 0], "head": [0, 0, 0]}},
            ],
        ),

        Motion(
            key="shake",
            label="고개 젓기",
            description="고개를 좌우로 젓는다. 거절이나 부정",
            duration=1.3,
            loop=False,
            keys=[
                # 좌우로 젓는 축은 y 다. 머리 -18 + 목 -7 이면 25도쯤 돌아간다.
                # 사람이 도리질할 때의 폭이 대개 그 정도다.
                {"t": 0.0, "bones": {"head": [0, 0, 0], "neck": [0, 0, 0]}},
                {"t": 0.22, "bones": {"head": [0, -18, 0], "neck": [0, -7, 0]}},
                {"t": 0.48, "bones": {"head": [0, 18, 0], "neck": [0, 7, 0]}},
                {"t": 0.74, "bones": {"head": [0, -14, 0], "neck": [0, -5, 0]}},
                {"t": 1.0, "bones": {"head": [0, 11, 0], "neck": [0, 4, 0]}},
                {"t": 1.3, "bones": {"head": [0, 0, 0], "neck": [0, 0, 0]}},
            ],
        ),

        Motion(
            key="nod",
            label="끄덕임",
            description="고개를 두 번 끄덕인다",
            duration=1.2,
            loop=False,
            keys=[
                {"t": 0.0, "bones": {"head": [0, 0, 0], "neck": [0, 0, 0]}},
                {"t": 0.25, "bones": {"head": [16, 0, 0], "neck": [7, 0, 0]}},
                {"t": 0.5, "bones": {"head": [-3, 0, 0], "neck": [-1, 0, 0]}},
                {"t": 0.8, "bones": {"head": [14, 0, 0], "neck": [6, 0, 0]}},
                {"t": 1.2, "bones": {"head": [0, 0, 0], "neck": [0, 0, 0]}},
            ],
        ),

        # 쑥스러워하기는 왼손을 쓴다. 손인사가 오른손이라 손이 겹치지 않는다.
        #
        # 이 자세는 사람이 리깅 확인대(/rig)에서 손과 팔꿈치를 직접 잡아 만든 값이다.
        # 계산으로 고친 데가 없다. 검사만 했고 전부 통과했다.
        #
        #   팔꿈치 굽힘 128.8도 (사람 한계 150도)
        #   위팔 벌림  62.6도
        #   팔꿈치가 y 음수로 접힌다 = 앞으로. 왼팔은 이 부호라야 맞다
        #   몸에 박히는 곳 없음. 손이 몸 앞(z -0.137)으로 지나 올라간다
        #
        # 기준자세에서 여기까지 곧장 이어도 몸에 닿지 않아 '지나갈 자리' 키가
        # 필요 없다. 팔을 내린 채 팔꿈치만 접어 올리는 길이라 몸을 비껴간다.
        #
        # 고칠 때는 눈대중으로 각도를 밀지 말고 /rig 에서 만든 뒤
        # _verify_collision.py 로 확인할 것.
        # ------------------------------------------------------------
        # 가위바위보
        #
        # 손가락 관절이 생겨서 주먹·가위·보를 실제로 지을 수 있다.
        # 흔드는 동안은 주먹이고 1.25초에 자기 것을 낸다.
        #
        # 팔 자세는 손이 몸 앞 가슴 높이에 오도록 푼 값이다.
        # 팔꿈치는 y 로만 접는다(오른팔은 +). 굽힘 83도, 몸에 닿는 곳 없음.
        # 손 모양은 _fit_rps.py 로 만들고 손바닥을 뚫지 않는지 확인했다.
        # ------------------------------------------------------------

        Motion(
            key="rps_rock",
            label="바위",
            description="가위바위보 — 주먹을 낸다",
            duration=2.65,
            loop=False,
            keys=[
                {"t": 0.0, "bones": {
                    "rightShoulder": [0.0, 0.0, 0.0], "rightUpperArm": [0.0, 0.0, -68.75],
                    "rightLowerArm": [0.0, 0.0, -10.0], "rightHand": [0.0, 0.0, 0.0],
                    "rightIndexProximal": [0.0, 5.0, -11.0], "rightIndexIntermediate": [0.0, 0.0, -26.0],
                    "rightIndexDistal": [0.0, 0.0, -15.0], "rightMiddleProximal": [0.0, 1.0, -13.0],
                    "rightMiddleIntermediate": [0.0, 0.0, -30.0], "rightMiddleDistal": [0.0, 0.0, -17.0],
                    "rightRingProximal": [0.0, -3.0, -15.0], "rightRingIntermediate": [0.0, 0.0, -34.0],
                    "rightRingDistal": [0.0, 0.0, -19.0], "rightLittleProximal": [0.0, -7.0, -17.0],
                    "rightLittleIntermediate": [0.0, 0.0, -37.0], "rightLittleDistal": [0.0, 0.0, -21.0],
                    "rightThumbProximal": [10.0, -15.0, 0.0], "rightThumbIntermediate": [12.0, 0.0, 0.0],
                    "rightThumbDistal": [8.0, 0.0, 0.0]
                }},
                {"t": 0.18, "bones": {
                    "rightShoulder": [22.0, -22.0, 22.0], "rightUpperArm": [63.29, 84.01, -70.96],
                    "rightLowerArm": [42.46, 41.43, 0.0], "rightHand": [19.0, -2.88, 0.0],
                    "rightIndexProximal": [0.0, 0.0, -78.0], "rightIndexIntermediate": [0.0, 0.0, -92.0],
                    "rightIndexDistal": [0.0, 0.0, -62.0], "rightMiddleProximal": [0.0, 0.0, -78.0],
                    "rightMiddleIntermediate": [0.0, 0.0, -92.0], "rightMiddleDistal": [0.0, 0.0, -62.0],
                    "rightRingProximal": [0.0, 0.0, -78.0], "rightRingIntermediate": [0.0, 0.0, -92.0],
                    "rightRingDistal": [0.0, 0.0, -62.0], "rightLittleProximal": [0.0, 0.0, -78.0],
                    "rightLittleIntermediate": [0.0, 0.0, -92.0], "rightLittleDistal": [0.0, 0.0, -62.0],
                    "rightThumbProximal": [-22.0, 0.0, 0.0], "rightThumbIntermediate": [-25.0, -51.25, -57.0],
                    "rightThumbDistal": [0.0, -83.5, 0.0]
                }},
                {"t": 0.4, "bones": {
                    "rightShoulder": [0.02, 0.17, -1.12], "rightUpperArm": [71.53, 131.82, -141.19],
                    "rightLowerArm": [84.93, 82.87, 0.0], "rightHand": [38.0, -5.75, 0.0],
                    "rightIndexProximal": [0.0, 0.0, -78.0], "rightIndexIntermediate": [0.0, 0.0, -92.0],
                    "rightIndexDistal": [0.0, 0.0, -62.0], "rightMiddleProximal": [0.0, 0.0, -78.0],
                    "rightMiddleIntermediate": [0.0, 0.0, -92.0], "rightMiddleDistal": [0.0, 0.0, -62.0],
                    "rightRingProximal": [0.0, 0.0, -78.0], "rightRingIntermediate": [0.0, 0.0, -92.0],
                    "rightRingDistal": [0.0, 0.0, -62.0], "rightLittleProximal": [0.0, 0.0, -78.0],
                    "rightLittleIntermediate": [0.0, 0.0, -92.0], "rightLittleDistal": [0.0, 0.0, -62.0],
                    "rightThumbProximal": [-22.0, 0.0, 0.0], "rightThumbIntermediate": [-25.0, -51.25, -57.0],
                    "rightThumbDistal": [0.0, -83.5, 0.0]
                }},
                {"t": 0.58, "bones": {
                    "rightShoulder": [0.02, 0.17, -1.12], "rightUpperArm": [71.53, 131.82, -141.19],
                    "rightLowerArm": [84.93, 68.87, 0.0], "rightHand": [38.0, -5.75, 0.0],
                    "rightIndexProximal": [0.0, 0.0, -78.0], "rightIndexIntermediate": [0.0, 0.0, -92.0],
                    "rightIndexDistal": [0.0, 0.0, -62.0], "rightMiddleProximal": [0.0, 0.0, -78.0],
                    "rightMiddleIntermediate": [0.0, 0.0, -92.0], "rightMiddleDistal": [0.0, 0.0, -62.0],
                    "rightRingProximal": [0.0, 0.0, -78.0], "rightRingIntermediate": [0.0, 0.0, -92.0],
                    "rightRingDistal": [0.0, 0.0, -62.0], "rightLittleProximal": [0.0, 0.0, -78.0],
                    "rightLittleIntermediate": [0.0, 0.0, -92.0], "rightLittleDistal": [0.0, 0.0, -62.0],
                    "rightThumbProximal": [-22.0, 0.0, 0.0], "rightThumbIntermediate": [-25.0, -51.25, -57.0],
                    "rightThumbDistal": [0.0, -83.5, 0.0]
                }},
                {"t": 0.76, "bones": {
                    "rightShoulder": [0.02, 0.17, -1.12], "rightUpperArm": [71.53, 131.82, -141.19],
                    "rightLowerArm": [84.93, 88.87, 0.0], "rightHand": [38.0, -5.75, 0.0],
                    "rightIndexProximal": [0.0, 0.0, -78.0], "rightIndexIntermediate": [0.0, 0.0, -92.0],
                    "rightIndexDistal": [0.0, 0.0, -62.0], "rightMiddleProximal": [0.0, 0.0, -78.0],
                    "rightMiddleIntermediate": [0.0, 0.0, -92.0], "rightMiddleDistal": [0.0, 0.0, -62.0],
                    "rightRingProximal": [0.0, 0.0, -78.0], "rightRingIntermediate": [0.0, 0.0, -92.0],
                    "rightRingDistal": [0.0, 0.0, -62.0], "rightLittleProximal": [0.0, 0.0, -78.0],
                    "rightLittleIntermediate": [0.0, 0.0, -92.0], "rightLittleDistal": [0.0, 0.0, -62.0],
                    "rightThumbProximal": [-22.0, 0.0, 0.0], "rightThumbIntermediate": [-25.0, -51.25, -57.0],
                    "rightThumbDistal": [0.0, -83.5, 0.0]
                }},
                {"t": 0.94, "bones": {
                    "rightShoulder": [0.02, 0.17, -1.12], "rightUpperArm": [71.53, 131.82, -141.19],
                    "rightLowerArm": [84.93, 68.87, 0.0], "rightHand": [38.0, -5.75, 0.0],
                    "rightIndexProximal": [0.0, 0.0, -78.0], "rightIndexIntermediate": [0.0, 0.0, -92.0],
                    "rightIndexDistal": [0.0, 0.0, -62.0], "rightMiddleProximal": [0.0, 0.0, -78.0],
                    "rightMiddleIntermediate": [0.0, 0.0, -92.0], "rightMiddleDistal": [0.0, 0.0, -62.0],
                    "rightRingProximal": [0.0, 0.0, -78.0], "rightRingIntermediate": [0.0, 0.0, -92.0],
                    "rightRingDistal": [0.0, 0.0, -62.0], "rightLittleProximal": [0.0, 0.0, -78.0],
                    "rightLittleIntermediate": [0.0, 0.0, -92.0], "rightLittleDistal": [0.0, 0.0, -62.0],
                    "rightThumbProximal": [-22.0, 0.0, 0.0], "rightThumbIntermediate": [-25.0, -51.25, -57.0],
                    "rightThumbDistal": [0.0, -83.5, 0.0]
                }},
                {"t": 1.12, "bones": {
                    "rightShoulder": [0.02, 0.17, -1.12], "rightUpperArm": [71.53, 131.82, -141.19],
                    "rightLowerArm": [84.93, 88.87, 0.0], "rightHand": [38.0, -5.75, 0.0],
                    "rightIndexProximal": [0.0, 0.0, -78.0], "rightIndexIntermediate": [0.0, 0.0, -92.0],
                    "rightIndexDistal": [0.0, 0.0, -62.0], "rightMiddleProximal": [0.0, 0.0, -78.0],
                    "rightMiddleIntermediate": [0.0, 0.0, -92.0], "rightMiddleDistal": [0.0, 0.0, -62.0],
                    "rightRingProximal": [0.0, 0.0, -78.0], "rightRingIntermediate": [0.0, 0.0, -92.0],
                    "rightRingDistal": [0.0, 0.0, -62.0], "rightLittleProximal": [0.0, 0.0, -78.0],
                    "rightLittleIntermediate": [0.0, 0.0, -92.0], "rightLittleDistal": [0.0, 0.0, -62.0],
                    "rightThumbProximal": [-22.0, 0.0, 0.0], "rightThumbIntermediate": [-25.0, -51.25, -57.0],
                    "rightThumbDistal": [0.0, -83.5, 0.0]
                }},
                {"t": 1.35, "bones": {
                    "rightShoulder": [0.02, 0.17, -1.12], "rightUpperArm": [71.53, 131.82, -141.19],
                    "rightLowerArm": [84.93, 82.87, 0.0], "rightHand": [38.0, -5.75, 0.0],
                    "rightIndexProximal": [0.0, 0.0, -78.0], "rightIndexIntermediate": [0.0, 0.0, -92.0],
                    "rightIndexDistal": [0.0, 0.0, -62.0], "rightMiddleProximal": [0.0, 0.0, -78.0],
                    "rightMiddleIntermediate": [0.0, 0.0, -92.0], "rightMiddleDistal": [0.0, 0.0, -62.0],
                    "rightRingProximal": [0.0, 0.0, -78.0], "rightRingIntermediate": [0.0, 0.0, -92.0],
                    "rightRingDistal": [0.0, 0.0, -62.0], "rightLittleProximal": [0.0, 0.0, -78.0],
                    "rightLittleIntermediate": [0.0, 0.0, -92.0], "rightLittleDistal": [0.0, 0.0, -62.0],
                    "rightThumbProximal": [-22.0, 0.0, 0.0], "rightThumbIntermediate": [-25.0, -51.25, -57.0],
                    "rightThumbDistal": [0.0, -83.5, 0.0]
                }},
                {"t": 1.95, "bones": {
                    "rightShoulder": [0.02, 0.17, -1.12], "rightUpperArm": [71.53, 131.82, -141.19],
                    "rightLowerArm": [84.93, 82.87, 0.0], "rightHand": [38.0, -5.75, 0.0],
                    "rightIndexProximal": [0.0, 0.0, -78.0], "rightIndexIntermediate": [0.0, 0.0, -92.0],
                    "rightIndexDistal": [0.0, 0.0, -62.0], "rightMiddleProximal": [0.0, 0.0, -78.0],
                    "rightMiddleIntermediate": [0.0, 0.0, -92.0], "rightMiddleDistal": [0.0, 0.0, -62.0],
                    "rightRingProximal": [0.0, 0.0, -78.0], "rightRingIntermediate": [0.0, 0.0, -92.0],
                    "rightRingDistal": [0.0, 0.0, -62.0], "rightLittleProximal": [0.0, 0.0, -78.0],
                    "rightLittleIntermediate": [0.0, 0.0, -92.0], "rightLittleDistal": [0.0, 0.0, -62.0],
                    "rightThumbProximal": [-22.0, 0.0, 0.0], "rightThumbIntermediate": [-25.0, -51.25, -57.0],
                    "rightThumbDistal": [0.0, -83.5, 0.0]
                }},
                {"t": 2.3, "bones": {
                    "rightShoulder": [22.0, -22.0, 22.0], "rightUpperArm": [63.29, 84.01, -70.96],
                    "rightLowerArm": [42.46, 41.43, 0.0], "rightHand": [19.0, -2.88, 0.0],
                    "rightIndexProximal": [0.0, 0.0, -78.0], "rightIndexIntermediate": [0.0, 0.0, -92.0],
                    "rightIndexDistal": [0.0, 0.0, -62.0], "rightMiddleProximal": [0.0, 0.0, -78.0],
                    "rightMiddleIntermediate": [0.0, 0.0, -92.0], "rightMiddleDistal": [0.0, 0.0, -62.0],
                    "rightRingProximal": [0.0, 0.0, -78.0], "rightRingIntermediate": [0.0, 0.0, -92.0],
                    "rightRingDistal": [0.0, 0.0, -62.0], "rightLittleProximal": [0.0, 0.0, -78.0],
                    "rightLittleIntermediate": [0.0, 0.0, -92.0], "rightLittleDistal": [0.0, 0.0, -62.0],
                    "rightThumbProximal": [-22.0, 0.0, 0.0], "rightThumbIntermediate": [-25.0, -51.25, -57.0],
                    "rightThumbDistal": [0.0, -83.5, 0.0]
                }},
                {"t": 2.65, "bones": {
                    "rightShoulder": [0.0, 0.0, 0.0], "rightUpperArm": [0.0, 0.0, -68.75],
                    "rightLowerArm": [0.0, 0.0, -10.0], "rightHand": [0.0, 0.0, 0.0],
                    "rightIndexProximal": [0.0, 5.0, -11.0], "rightIndexIntermediate": [0.0, 0.0, -26.0],
                    "rightIndexDistal": [0.0, 0.0, -15.0], "rightMiddleProximal": [0.0, 1.0, -13.0],
                    "rightMiddleIntermediate": [0.0, 0.0, -30.0], "rightMiddleDistal": [0.0, 0.0, -17.0],
                    "rightRingProximal": [0.0, -3.0, -15.0], "rightRingIntermediate": [0.0, 0.0, -34.0],
                    "rightRingDistal": [0.0, 0.0, -19.0], "rightLittleProximal": [0.0, -7.0, -17.0],
                    "rightLittleIntermediate": [0.0, 0.0, -37.0], "rightLittleDistal": [0.0, 0.0, -21.0],
                    "rightThumbProximal": [10.0, -15.0, 0.0], "rightThumbIntermediate": [12.0, 0.0, 0.0],
                    "rightThumbDistal": [8.0, 0.0, 0.0]
                }},
            ],
        ),

        Motion(
            key="rps_scissors",
            label="가위",
            description="가위바위보 — 가위를 낸다",
            duration=2.65,
            loop=False,
            keys=[
                {"t": 0.0, "bones": {
                    "rightShoulder": [0.0, 0.0, 0.0], "rightUpperArm": [0.0, 0.0, -68.75],
                    "rightLowerArm": [0.0, 0.0, -10.0], "rightHand": [0.0, 0.0, 0.0],
                    "rightIndexProximal": [0.0, 5.0, -11.0], "rightIndexIntermediate": [0.0, 0.0, -26.0],
                    "rightIndexDistal": [0.0, 0.0, -15.0], "rightMiddleProximal": [0.0, 1.0, -13.0],
                    "rightMiddleIntermediate": [0.0, 0.0, -30.0], "rightMiddleDistal": [0.0, 0.0, -17.0],
                    "rightRingProximal": [0.0, -3.0, -15.0], "rightRingIntermediate": [0.0, 0.0, -34.0],
                    "rightRingDistal": [0.0, 0.0, -19.0], "rightLittleProximal": [0.0, -7.0, -17.0],
                    "rightLittleIntermediate": [0.0, 0.0, -37.0], "rightLittleDistal": [0.0, 0.0, -21.0],
                    "rightThumbProximal": [10.0, -15.0, 0.0], "rightThumbIntermediate": [12.0, 0.0, 0.0],
                    "rightThumbDistal": [8.0, 0.0, 0.0]
                }},
                {"t": 0.18, "bones": {
                    "rightShoulder": [22.0, -22.0, 22.0], "rightUpperArm": [63.29, 84.01, -70.96],
                    "rightLowerArm": [42.46, 41.43, 0.0], "rightHand": [19.0, -2.88, 0.0],
                    "rightIndexProximal": [0.0, 0.0, -78.0], "rightIndexIntermediate": [0.0, 0.0, -92.0],
                    "rightIndexDistal": [0.0, 0.0, -62.0], "rightMiddleProximal": [0.0, 0.0, -78.0],
                    "rightMiddleIntermediate": [0.0, 0.0, -92.0], "rightMiddleDistal": [0.0, 0.0, -62.0],
                    "rightRingProximal": [0.0, 0.0, -78.0], "rightRingIntermediate": [0.0, 0.0, -92.0],
                    "rightRingDistal": [0.0, 0.0, -62.0], "rightLittleProximal": [0.0, 0.0, -78.0],
                    "rightLittleIntermediate": [0.0, 0.0, -92.0], "rightLittleDistal": [0.0, 0.0, -62.0],
                    "rightThumbProximal": [-22.0, 0.0, 0.0], "rightThumbIntermediate": [-25.0, -51.25, -57.0],
                    "rightThumbDistal": [0.0, -83.5, 0.0]
                }},
                {"t": 0.4, "bones": {
                    "rightShoulder": [0.02, 0.17, -1.12], "rightUpperArm": [71.53, 131.82, -141.19],
                    "rightLowerArm": [84.93, 82.87, 0.0], "rightHand": [38.0, -5.75, 0.0],
                    "rightIndexProximal": [0.0, 0.0, -78.0], "rightIndexIntermediate": [0.0, 0.0, -92.0],
                    "rightIndexDistal": [0.0, 0.0, -62.0], "rightMiddleProximal": [0.0, 0.0, -78.0],
                    "rightMiddleIntermediate": [0.0, 0.0, -92.0], "rightMiddleDistal": [0.0, 0.0, -62.0],
                    "rightRingProximal": [0.0, 0.0, -78.0], "rightRingIntermediate": [0.0, 0.0, -92.0],
                    "rightRingDistal": [0.0, 0.0, -62.0], "rightLittleProximal": [0.0, 0.0, -78.0],
                    "rightLittleIntermediate": [0.0, 0.0, -92.0], "rightLittleDistal": [0.0, 0.0, -62.0],
                    "rightThumbProximal": [-22.0, 0.0, 0.0], "rightThumbIntermediate": [-25.0, -51.25, -57.0],
                    "rightThumbDistal": [0.0, -83.5, 0.0]
                }},
                {"t": 0.58, "bones": {
                    "rightShoulder": [0.02, 0.17, -1.12], "rightUpperArm": [71.53, 131.82, -141.19],
                    "rightLowerArm": [84.93, 68.87, 0.0], "rightHand": [38.0, -5.75, 0.0],
                    "rightIndexProximal": [0.0, 0.0, -78.0], "rightIndexIntermediate": [0.0, 0.0, -92.0],
                    "rightIndexDistal": [0.0, 0.0, -62.0], "rightMiddleProximal": [0.0, 0.0, -78.0],
                    "rightMiddleIntermediate": [0.0, 0.0, -92.0], "rightMiddleDistal": [0.0, 0.0, -62.0],
                    "rightRingProximal": [0.0, 0.0, -78.0], "rightRingIntermediate": [0.0, 0.0, -92.0],
                    "rightRingDistal": [0.0, 0.0, -62.0], "rightLittleProximal": [0.0, 0.0, -78.0],
                    "rightLittleIntermediate": [0.0, 0.0, -92.0], "rightLittleDistal": [0.0, 0.0, -62.0],
                    "rightThumbProximal": [-22.0, 0.0, 0.0], "rightThumbIntermediate": [-25.0, -51.25, -57.0],
                    "rightThumbDistal": [0.0, -83.5, 0.0]
                }},
                {"t": 0.76, "bones": {
                    "rightShoulder": [0.02, 0.17, -1.12], "rightUpperArm": [71.53, 131.82, -141.19],
                    "rightLowerArm": [84.93, 88.87, 0.0], "rightHand": [38.0, -5.75, 0.0],
                    "rightIndexProximal": [0.0, 0.0, -78.0], "rightIndexIntermediate": [0.0, 0.0, -92.0],
                    "rightIndexDistal": [0.0, 0.0, -62.0], "rightMiddleProximal": [0.0, 0.0, -78.0],
                    "rightMiddleIntermediate": [0.0, 0.0, -92.0], "rightMiddleDistal": [0.0, 0.0, -62.0],
                    "rightRingProximal": [0.0, 0.0, -78.0], "rightRingIntermediate": [0.0, 0.0, -92.0],
                    "rightRingDistal": [0.0, 0.0, -62.0], "rightLittleProximal": [0.0, 0.0, -78.0],
                    "rightLittleIntermediate": [0.0, 0.0, -92.0], "rightLittleDistal": [0.0, 0.0, -62.0],
                    "rightThumbProximal": [-22.0, 0.0, 0.0], "rightThumbIntermediate": [-25.0, -51.25, -57.0],
                    "rightThumbDistal": [0.0, -83.5, 0.0]
                }},
                {"t": 0.94, "bones": {
                    "rightShoulder": [0.02, 0.17, -1.12], "rightUpperArm": [71.53, 131.82, -141.19],
                    "rightLowerArm": [84.93, 68.87, 0.0], "rightHand": [38.0, -5.75, 0.0],
                    "rightIndexProximal": [0.0, 0.0, -78.0], "rightIndexIntermediate": [0.0, 0.0, -92.0],
                    "rightIndexDistal": [0.0, 0.0, -62.0], "rightMiddleProximal": [0.0, 0.0, -78.0],
                    "rightMiddleIntermediate": [0.0, 0.0, -92.0], "rightMiddleDistal": [0.0, 0.0, -62.0],
                    "rightRingProximal": [0.0, 0.0, -78.0], "rightRingIntermediate": [0.0, 0.0, -92.0],
                    "rightRingDistal": [0.0, 0.0, -62.0], "rightLittleProximal": [0.0, 0.0, -78.0],
                    "rightLittleIntermediate": [0.0, 0.0, -92.0], "rightLittleDistal": [0.0, 0.0, -62.0],
                    "rightThumbProximal": [-22.0, 0.0, 0.0], "rightThumbIntermediate": [-25.0, -51.25, -57.0],
                    "rightThumbDistal": [0.0, -83.5, 0.0]
                }},
                {"t": 1.12, "bones": {
                    "rightShoulder": [0.02, 0.17, -1.12], "rightUpperArm": [71.53, 131.82, -141.19],
                    "rightLowerArm": [84.93, 88.87, 0.0], "rightHand": [38.0, -5.75, 0.0],
                    "rightIndexProximal": [0.0, 0.0, -78.0], "rightIndexIntermediate": [0.0, 0.0, -92.0],
                    "rightIndexDistal": [0.0, 0.0, -62.0], "rightMiddleProximal": [0.0, 0.0, -78.0],
                    "rightMiddleIntermediate": [0.0, 0.0, -92.0], "rightMiddleDistal": [0.0, 0.0, -62.0],
                    "rightRingProximal": [0.0, 0.0, -78.0], "rightRingIntermediate": [0.0, 0.0, -92.0],
                    "rightRingDistal": [0.0, 0.0, -62.0], "rightLittleProximal": [0.0, 0.0, -78.0],
                    "rightLittleIntermediate": [0.0, 0.0, -92.0], "rightLittleDistal": [0.0, 0.0, -62.0],
                    "rightThumbProximal": [-22.0, 0.0, 0.0], "rightThumbIntermediate": [-25.0, -51.25, -57.0],
                    "rightThumbDistal": [0.0, -83.5, 0.0]
                }},
                {"t": 1.35, "bones": {
                    "rightShoulder": [0.02, 0.17, -1.12], "rightUpperArm": [71.53, 131.82, -141.19],
                    "rightLowerArm": [84.93, 82.87, 0.0], "rightHand": [38.0, -5.75, 0.0],
                    "rightIndexProximal": [0.0, 16.0, 0.0], "rightIndexIntermediate": [0.0, 0.0, 0.0],
                    "rightIndexDistal": [0.0, 0.0, 0.0], "rightMiddleProximal": [0.0, -12.0, 0.0],
                    "rightMiddleIntermediate": [0.0, 0.0, 0.0], "rightMiddleDistal": [0.0, 0.0, 0.0],
                    "rightRingProximal": [0.0, 0.0, -78.0], "rightRingIntermediate": [0.0, 0.0, -92.0],
                    "rightRingDistal": [0.0, 0.0, -62.0], "rightLittleProximal": [0.0, 0.0, -78.0],
                    "rightLittleIntermediate": [0.0, 0.0, -92.0], "rightLittleDistal": [0.0, 0.0, -62.0],
                    "rightThumbProximal": [-22.0, 0.0, 0.0], "rightThumbIntermediate": [-25.0, -51.25, -57.0],
                    "rightThumbDistal": [0.0, -83.5, 0.0]
                }},
                {"t": 1.95, "bones": {
                    "rightShoulder": [0.02, 0.17, -1.12], "rightUpperArm": [71.53, 131.82, -141.19],
                    "rightLowerArm": [84.93, 82.87, 0.0], "rightHand": [38.0, -5.75, 0.0],
                    "rightIndexProximal": [0.0, 16.0, 0.0], "rightIndexIntermediate": [0.0, 0.0, 0.0],
                    "rightIndexDistal": [0.0, 0.0, 0.0], "rightMiddleProximal": [0.0, -12.0, 0.0],
                    "rightMiddleIntermediate": [0.0, 0.0, 0.0], "rightMiddleDistal": [0.0, 0.0, 0.0],
                    "rightRingProximal": [0.0, 0.0, -78.0], "rightRingIntermediate": [0.0, 0.0, -92.0],
                    "rightRingDistal": [0.0, 0.0, -62.0], "rightLittleProximal": [0.0, 0.0, -78.0],
                    "rightLittleIntermediate": [0.0, 0.0, -92.0], "rightLittleDistal": [0.0, 0.0, -62.0],
                    "rightThumbProximal": [-22.0, 0.0, 0.0], "rightThumbIntermediate": [-25.0, -51.25, -57.0],
                    "rightThumbDistal": [0.0, -83.5, 0.0]
                }},
                {"t": 2.3, "bones": {
                    "rightShoulder": [22.0, -22.0, 22.0], "rightUpperArm": [63.29, 84.01, -70.96],
                    "rightLowerArm": [42.46, 41.43, 0.0], "rightHand": [19.0, -2.88, 0.0],
                    "rightIndexProximal": [0.0, 16.0, 0.0], "rightIndexIntermediate": [0.0, 0.0, 0.0],
                    "rightIndexDistal": [0.0, 0.0, 0.0], "rightMiddleProximal": [0.0, -12.0, 0.0],
                    "rightMiddleIntermediate": [0.0, 0.0, 0.0], "rightMiddleDistal": [0.0, 0.0, 0.0],
                    "rightRingProximal": [0.0, 0.0, -78.0], "rightRingIntermediate": [0.0, 0.0, -92.0],
                    "rightRingDistal": [0.0, 0.0, -62.0], "rightLittleProximal": [0.0, 0.0, -78.0],
                    "rightLittleIntermediate": [0.0, 0.0, -92.0], "rightLittleDistal": [0.0, 0.0, -62.0],
                    "rightThumbProximal": [-22.0, 0.0, 0.0], "rightThumbIntermediate": [-25.0, -51.25, -57.0],
                    "rightThumbDistal": [0.0, -83.5, 0.0]
                }},
                {"t": 2.65, "bones": {
                    "rightShoulder": [0.0, 0.0, 0.0], "rightUpperArm": [0.0, 0.0, -68.75],
                    "rightLowerArm": [0.0, 0.0, -10.0], "rightHand": [0.0, 0.0, 0.0],
                    "rightIndexProximal": [0.0, 5.0, -11.0], "rightIndexIntermediate": [0.0, 0.0, -26.0],
                    "rightIndexDistal": [0.0, 0.0, -15.0], "rightMiddleProximal": [0.0, 1.0, -13.0],
                    "rightMiddleIntermediate": [0.0, 0.0, -30.0], "rightMiddleDistal": [0.0, 0.0, -17.0],
                    "rightRingProximal": [0.0, -3.0, -15.0], "rightRingIntermediate": [0.0, 0.0, -34.0],
                    "rightRingDistal": [0.0, 0.0, -19.0], "rightLittleProximal": [0.0, -7.0, -17.0],
                    "rightLittleIntermediate": [0.0, 0.0, -37.0], "rightLittleDistal": [0.0, 0.0, -21.0],
                    "rightThumbProximal": [10.0, -15.0, 0.0], "rightThumbIntermediate": [12.0, 0.0, 0.0],
                    "rightThumbDistal": [8.0, 0.0, 0.0]
                }},
            ],
        ),

        Motion(
            key="rps_paper",
            label="보",
            description="가위바위보 — 보를 낸다",
            duration=2.65,
            loop=False,
            keys=[
                {"t": 0.0, "bones": {
                    "rightShoulder": [0.0, 0.0, 0.0], "rightUpperArm": [0.0, 0.0, -68.75],
                    "rightLowerArm": [0.0, 0.0, -10.0], "rightHand": [0.0, 0.0, 0.0],
                    "rightIndexProximal": [0.0, 5.0, -11.0], "rightIndexIntermediate": [0.0, 0.0, -26.0],
                    "rightIndexDistal": [0.0, 0.0, -15.0], "rightMiddleProximal": [0.0, 1.0, -13.0],
                    "rightMiddleIntermediate": [0.0, 0.0, -30.0], "rightMiddleDistal": [0.0, 0.0, -17.0],
                    "rightRingProximal": [0.0, -3.0, -15.0], "rightRingIntermediate": [0.0, 0.0, -34.0],
                    "rightRingDistal": [0.0, 0.0, -19.0], "rightLittleProximal": [0.0, -7.0, -17.0],
                    "rightLittleIntermediate": [0.0, 0.0, -37.0], "rightLittleDistal": [0.0, 0.0, -21.0],
                    "rightThumbProximal": [10.0, -15.0, 0.0], "rightThumbIntermediate": [12.0, 0.0, 0.0],
                    "rightThumbDistal": [8.0, 0.0, 0.0]
                }},
                {"t": 0.18, "bones": {
                    "rightShoulder": [22.0, -22.0, 22.0], "rightUpperArm": [63.29, 84.01, -70.96],
                    "rightLowerArm": [42.46, 41.43, 0.0], "rightHand": [19.0, -2.88, 0.0],
                    "rightIndexProximal": [0.0, 0.0, -78.0], "rightIndexIntermediate": [0.0, 0.0, -92.0],
                    "rightIndexDistal": [0.0, 0.0, -62.0], "rightMiddleProximal": [0.0, 0.0, -78.0],
                    "rightMiddleIntermediate": [0.0, 0.0, -92.0], "rightMiddleDistal": [0.0, 0.0, -62.0],
                    "rightRingProximal": [0.0, 0.0, -78.0], "rightRingIntermediate": [0.0, 0.0, -92.0],
                    "rightRingDistal": [0.0, 0.0, -62.0], "rightLittleProximal": [0.0, 0.0, -78.0],
                    "rightLittleIntermediate": [0.0, 0.0, -92.0], "rightLittleDistal": [0.0, 0.0, -62.0],
                    "rightThumbProximal": [-22.0, 0.0, 0.0], "rightThumbIntermediate": [-25.0, -51.25, -57.0],
                    "rightThumbDistal": [0.0, -83.5, 0.0]
                }},
                {"t": 0.4, "bones": {
                    "rightShoulder": [0.02, 0.17, -1.12], "rightUpperArm": [71.53, 131.82, -141.19],
                    "rightLowerArm": [84.93, 82.87, 0.0], "rightHand": [38.0, -5.75, 0.0],
                    "rightIndexProximal": [0.0, 0.0, -78.0], "rightIndexIntermediate": [0.0, 0.0, -92.0],
                    "rightIndexDistal": [0.0, 0.0, -62.0], "rightMiddleProximal": [0.0, 0.0, -78.0],
                    "rightMiddleIntermediate": [0.0, 0.0, -92.0], "rightMiddleDistal": [0.0, 0.0, -62.0],
                    "rightRingProximal": [0.0, 0.0, -78.0], "rightRingIntermediate": [0.0, 0.0, -92.0],
                    "rightRingDistal": [0.0, 0.0, -62.0], "rightLittleProximal": [0.0, 0.0, -78.0],
                    "rightLittleIntermediate": [0.0, 0.0, -92.0], "rightLittleDistal": [0.0, 0.0, -62.0],
                    "rightThumbProximal": [-22.0, 0.0, 0.0], "rightThumbIntermediate": [-25.0, -51.25, -57.0],
                    "rightThumbDistal": [0.0, -83.5, 0.0]
                }},
                {"t": 0.58, "bones": {
                    "rightShoulder": [0.02, 0.17, -1.12], "rightUpperArm": [71.53, 131.82, -141.19],
                    "rightLowerArm": [84.93, 68.87, 0.0], "rightHand": [38.0, -5.75, 0.0],
                    "rightIndexProximal": [0.0, 0.0, -78.0], "rightIndexIntermediate": [0.0, 0.0, -92.0],
                    "rightIndexDistal": [0.0, 0.0, -62.0], "rightMiddleProximal": [0.0, 0.0, -78.0],
                    "rightMiddleIntermediate": [0.0, 0.0, -92.0], "rightMiddleDistal": [0.0, 0.0, -62.0],
                    "rightRingProximal": [0.0, 0.0, -78.0], "rightRingIntermediate": [0.0, 0.0, -92.0],
                    "rightRingDistal": [0.0, 0.0, -62.0], "rightLittleProximal": [0.0, 0.0, -78.0],
                    "rightLittleIntermediate": [0.0, 0.0, -92.0], "rightLittleDistal": [0.0, 0.0, -62.0],
                    "rightThumbProximal": [-22.0, 0.0, 0.0], "rightThumbIntermediate": [-25.0, -51.25, -57.0],
                    "rightThumbDistal": [0.0, -83.5, 0.0]
                }},
                {"t": 0.76, "bones": {
                    "rightShoulder": [0.02, 0.17, -1.12], "rightUpperArm": [71.53, 131.82, -141.19],
                    "rightLowerArm": [84.93, 88.87, 0.0], "rightHand": [38.0, -5.75, 0.0],
                    "rightIndexProximal": [0.0, 0.0, -78.0], "rightIndexIntermediate": [0.0, 0.0, -92.0],
                    "rightIndexDistal": [0.0, 0.0, -62.0], "rightMiddleProximal": [0.0, 0.0, -78.0],
                    "rightMiddleIntermediate": [0.0, 0.0, -92.0], "rightMiddleDistal": [0.0, 0.0, -62.0],
                    "rightRingProximal": [0.0, 0.0, -78.0], "rightRingIntermediate": [0.0, 0.0, -92.0],
                    "rightRingDistal": [0.0, 0.0, -62.0], "rightLittleProximal": [0.0, 0.0, -78.0],
                    "rightLittleIntermediate": [0.0, 0.0, -92.0], "rightLittleDistal": [0.0, 0.0, -62.0],
                    "rightThumbProximal": [-22.0, 0.0, 0.0], "rightThumbIntermediate": [-25.0, -51.25, -57.0],
                    "rightThumbDistal": [0.0, -83.5, 0.0]
                }},
                {"t": 0.94, "bones": {
                    "rightShoulder": [0.02, 0.17, -1.12], "rightUpperArm": [71.53, 131.82, -141.19],
                    "rightLowerArm": [84.93, 68.87, 0.0], "rightHand": [38.0, -5.75, 0.0],
                    "rightIndexProximal": [0.0, 0.0, -78.0], "rightIndexIntermediate": [0.0, 0.0, -92.0],
                    "rightIndexDistal": [0.0, 0.0, -62.0], "rightMiddleProximal": [0.0, 0.0, -78.0],
                    "rightMiddleIntermediate": [0.0, 0.0, -92.0], "rightMiddleDistal": [0.0, 0.0, -62.0],
                    "rightRingProximal": [0.0, 0.0, -78.0], "rightRingIntermediate": [0.0, 0.0, -92.0],
                    "rightRingDistal": [0.0, 0.0, -62.0], "rightLittleProximal": [0.0, 0.0, -78.0],
                    "rightLittleIntermediate": [0.0, 0.0, -92.0], "rightLittleDistal": [0.0, 0.0, -62.0],
                    "rightThumbProximal": [-22.0, 0.0, 0.0], "rightThumbIntermediate": [-25.0, -51.25, -57.0],
                    "rightThumbDistal": [0.0, -83.5, 0.0]
                }},
                {"t": 1.12, "bones": {
                    "rightShoulder": [0.02, 0.17, -1.12], "rightUpperArm": [71.53, 131.82, -141.19],
                    "rightLowerArm": [84.93, 88.87, 0.0], "rightHand": [38.0, -5.75, 0.0],
                    "rightIndexProximal": [0.0, 0.0, -78.0], "rightIndexIntermediate": [0.0, 0.0, -92.0],
                    "rightIndexDistal": [0.0, 0.0, -62.0], "rightMiddleProximal": [0.0, 0.0, -78.0],
                    "rightMiddleIntermediate": [0.0, 0.0, -92.0], "rightMiddleDistal": [0.0, 0.0, -62.0],
                    "rightRingProximal": [0.0, 0.0, -78.0], "rightRingIntermediate": [0.0, 0.0, -92.0],
                    "rightRingDistal": [0.0, 0.0, -62.0], "rightLittleProximal": [0.0, 0.0, -78.0],
                    "rightLittleIntermediate": [0.0, 0.0, -92.0], "rightLittleDistal": [0.0, 0.0, -62.0],
                    "rightThumbProximal": [-22.0, 0.0, 0.0], "rightThumbIntermediate": [-25.0, -51.25, -57.0],
                    "rightThumbDistal": [0.0, -83.5, 0.0]
                }},
                {"t": 1.35, "bones": {
                    "rightShoulder": [0.02, 0.17, -1.12], "rightUpperArm": [71.53, 131.82, -141.19],
                    "rightLowerArm": [84.93, 82.87, 0.0], "rightHand": [38.0, -5.75, 0.0],
                    "rightIndexProximal": [0.0, 8.0, 0.0], "rightIndexIntermediate": [0.0, 0.0, 0.0],
                    "rightIndexDistal": [0.0, 0.0, 0.0], "rightMiddleProximal": [0.0, 2.0, 0.0],
                    "rightMiddleIntermediate": [0.0, 0.0, 0.0], "rightMiddleDistal": [0.0, 0.0, 0.0],
                    "rightRingProximal": [0.0, -5.0, 0.0], "rightRingIntermediate": [0.0, 0.0, 0.0],
                    "rightRingDistal": [0.0, 0.0, 0.0], "rightLittleProximal": [0.0, -11.0, 0.0],
                    "rightLittleIntermediate": [0.0, 0.0, 0.0], "rightLittleDistal": [0.0, 0.0, 0.0],
                    "rightThumbProximal": [0.0, 8.0, 0.0], "rightThumbIntermediate": [0.0, 0.0, 0.0],
                    "rightThumbDistal": [0.0, 0.0, 0.0]
                }},
                {"t": 1.95, "bones": {
                    "rightShoulder": [0.02, 0.17, -1.12], "rightUpperArm": [71.53, 131.82, -141.19],
                    "rightLowerArm": [84.93, 82.87, 0.0], "rightHand": [38.0, -5.75, 0.0],
                    "rightIndexProximal": [0.0, 8.0, 0.0], "rightIndexIntermediate": [0.0, 0.0, 0.0],
                    "rightIndexDistal": [0.0, 0.0, 0.0], "rightMiddleProximal": [0.0, 2.0, 0.0],
                    "rightMiddleIntermediate": [0.0, 0.0, 0.0], "rightMiddleDistal": [0.0, 0.0, 0.0],
                    "rightRingProximal": [0.0, -5.0, 0.0], "rightRingIntermediate": [0.0, 0.0, 0.0],
                    "rightRingDistal": [0.0, 0.0, 0.0], "rightLittleProximal": [0.0, -11.0, 0.0],
                    "rightLittleIntermediate": [0.0, 0.0, 0.0], "rightLittleDistal": [0.0, 0.0, 0.0],
                    "rightThumbProximal": [0.0, 8.0, 0.0], "rightThumbIntermediate": [0.0, 0.0, 0.0],
                    "rightThumbDistal": [0.0, 0.0, 0.0]
                }},
                {"t": 2.3, "bones": {
                    "rightShoulder": [22.0, -22.0, 22.0], "rightUpperArm": [63.29, 84.01, -70.96],
                    "rightLowerArm": [42.46, 41.43, 0.0], "rightHand": [19.0, -2.88, 0.0],
                    "rightIndexProximal": [0.0, 8.0, 0.0], "rightIndexIntermediate": [0.0, 0.0, 0.0],
                    "rightIndexDistal": [0.0, 0.0, 0.0], "rightMiddleProximal": [0.0, 2.0, 0.0],
                    "rightMiddleIntermediate": [0.0, 0.0, 0.0], "rightMiddleDistal": [0.0, 0.0, 0.0],
                    "rightRingProximal": [0.0, -5.0, 0.0], "rightRingIntermediate": [0.0, 0.0, 0.0],
                    "rightRingDistal": [0.0, 0.0, 0.0], "rightLittleProximal": [0.0, -11.0, 0.0],
                    "rightLittleIntermediate": [0.0, 0.0, 0.0], "rightLittleDistal": [0.0, 0.0, 0.0],
                    "rightThumbProximal": [0.0, 8.0, 0.0], "rightThumbIntermediate": [0.0, 0.0, 0.0],
                    "rightThumbDistal": [0.0, 0.0, 0.0]
                }},
                {"t": 2.65, "bones": {
                    "rightShoulder": [0.0, 0.0, 0.0], "rightUpperArm": [0.0, 0.0, -68.75],
                    "rightLowerArm": [0.0, 0.0, -10.0], "rightHand": [0.0, 0.0, 0.0],
                    "rightIndexProximal": [0.0, 5.0, -11.0], "rightIndexIntermediate": [0.0, 0.0, -26.0],
                    "rightIndexDistal": [0.0, 0.0, -15.0], "rightMiddleProximal": [0.0, 1.0, -13.0],
                    "rightMiddleIntermediate": [0.0, 0.0, -30.0], "rightMiddleDistal": [0.0, 0.0, -17.0],
                    "rightRingProximal": [0.0, -3.0, -15.0], "rightRingIntermediate": [0.0, 0.0, -34.0],
                    "rightRingDistal": [0.0, 0.0, -19.0], "rightLittleProximal": [0.0, -7.0, -17.0],
                    "rightLittleIntermediate": [0.0, 0.0, -37.0], "rightLittleDistal": [0.0, 0.0, -21.0],
                    "rightThumbProximal": [10.0, -15.0, 0.0], "rightThumbIntermediate": [12.0, 0.0, 0.0],
                    "rightThumbDistal": [8.0, 0.0, 0.0]
                }},
            ],
        ),

        # 팔짱 — 삐치거나 벽을 세울 때.
        # 가슴 앞에서 양팔을 겹친다. 왼팔이 위, 오른팔이 아래다.
        Motion(
            key="cross",
            label="팔짱",
            description="팔짱을 낀다. 삐쳤거나 마음을 닫았을 때",
            duration=2.9,
            loop=False,
            # 삐죽은 혼자 쓰면 어색하다. 몸짓과 같이 나와야 뜻이 산다.
            expression="pout",
            # 팔짱을 낀 채 머무는 자리
            hold_t=2.2,
            keys=[
                {"t": 0.0, "bones": {
                    "leftShoulder": [0, 0, 0], "leftUpperArm": [0, 0, 68.75],
                    "leftLowerArm": [0, 0, 10], "leftHand": [0, 0, 0],
                    "rightShoulder": [0, 0, 0], "rightUpperArm": [0, 0, -68.75],
                    "rightLowerArm": [0, 0, -10], "rightHand": [0, 0, 0],
                    "chest": [0, 0, 0], "head": [0, 0, 0]}},
                # 지나갈 자리 — 오른팔이 가슴을 3.3cm 지나가는 것을 피한다
                {"t": 0.25, "bones": {
                    "leftShoulder": [0, 0, 0], "leftUpperArm": [0, 0, 68.75],
                    "leftLowerArm": [0, 0, 10], "leftHand": [0, 0, 0],
                    "rightShoulder": [15.03, 9.68, 22.0],
                    "rightUpperArm": [55.68, 64.27, -84.24],
                    "rightLowerArm": [12.87, 50.39, 0], "rightHand": [0, 0, 0],
                    "chest": [0, 2, 0], "head": [-2, 5, 0]}},
                {"t": 0.55, "bones": {
                    "leftShoulder": [2.75, -22.0, -10.13],
                    "leftUpperArm": [-76.28, -78.61, -7.76],
                    "leftLowerArm": [33.06, -106.59, 0], "leftHand": [0, 0, 0],
                    "rightShoulder": [5.98, 22.0, -0.06],
                    "rightUpperArm": [97.95, 109.65, -168.79],
                    "rightLowerArm": [25.74, 100.79, 0], "rightHand": [0, 0, 0],
                    "chest": [0, 6, 0], "head": [-5, 12, 0]}},
                {"t": 2.0, "bones": {
                    "leftShoulder": [2.75, -22.0, -10.13],
                    "leftUpperArm": [-76.28, -78.61, -7.76],
                    "leftLowerArm": [33.06, -106.59, 0], "leftHand": [0, 0, 0],
                    "rightShoulder": [5.98, 22.0, -0.06],
                    "rightUpperArm": [97.95, 109.65, -168.79],
                    "rightLowerArm": [25.74, 100.79, 0], "rightHand": [0, 0, 0],
                    "chest": [0, 5, 0], "head": [-4, 9, 0]}},
                # 돌아올 때도 같은 자리를 거친다
                {"t": 2.3, "bones": {
                    "leftShoulder": [0, 0, 0], "leftUpperArm": [0, 0, 68.75],
                    "leftLowerArm": [0, 0, 10], "leftHand": [0, 0, 0],
                    "rightShoulder": [15.03, 9.68, 22.0],
                    "rightUpperArm": [55.68, 64.27, -84.24],
                    "rightLowerArm": [12.87, 50.39, 0], "rightHand": [0, 0, 0],
                    "chest": [0, 2, 0], "head": [-2, 4, 0]}},
                {"t": 2.9, "bones": {
                    "leftShoulder": [0, 0, 0], "leftUpperArm": [0, 0, 68.75],
                    "leftLowerArm": [0, 0, 10], "leftHand": [0, 0, 0],
                    "rightShoulder": [0, 0, 0], "rightUpperArm": [0, 0, -68.75],
                    "rightLowerArm": [0, 0, -10], "rightHand": [0, 0, 0],
                    "chest": [0, 0, 0], "head": [0, 0, 0]}},
            ],
        ),

        # 얼굴 가리기 — 쑥스러워하기의 강한 쪽. 두 손으로 얼굴을 덮는다.
        Motion(
            key="cover",
            label="얼굴 가리기",
            description="두 손으로 얼굴을 가린다. 부끄러움이 클 때",
            duration=2.4,
            loop=False,
            expression="surprised",
            # 가리는 얼굴은 놀란 얼굴이다. 늘 같이 간다.
            expression_force=True,
            keys=[
                {"t": 0.0, "bones": {
                    "leftShoulder": [0, 0, 0], "leftUpperArm": [0, 0, 68.75],
                    "leftLowerArm": [0, 0, 10], "leftHand": [0, 0, 0],
                    "rightShoulder": [0, 0, 0], "rightUpperArm": [0, 0, -68.75],
                    "rightLowerArm": [0, 0, -10], "rightHand": [0, 0, 0],
                    "head": [0, 0, 0]}},
                {"t": 0.45, "bones": {
                    "leftShoulder": [-1.31, 9.27, -9.65],
                    "leftUpperArm": [66.88, 65.79, 82.0],
                    "leftLowerArm": [-88.25, -123.91, 0], "leftHand": [75, 0, 0],
                    "rightShoulder": [-1.31, -9.27, 9.65],
                    "rightUpperArm": [66.88, -65.79, -82.0],
                    "rightLowerArm": [-88.25, 123.91, 0], "rightHand": [75, 0, 0],
                    "head": [-13, 0, 0]}},
                {"t": 1.8, "bones": {
                    "leftShoulder": [-1.31, 9.27, -9.65],
                    "leftUpperArm": [66.88, 65.79, 82.0],
                    "leftLowerArm": [-88.25, -123.91, 0], "leftHand": [75, 0, 0],
                    "rightShoulder": [-1.31, -9.27, 9.65],
                    "rightUpperArm": [66.88, -65.79, -82.0],
                    "rightLowerArm": [-88.25, 123.91, 0], "rightHand": [75, 0, 0],
                    "head": [-15, 0, 0]}},
                {"t": 2.4, "bones": {
                    "leftShoulder": [0, 0, 0], "leftUpperArm": [0, 0, 68.75],
                    "leftLowerArm": [0, 0, 10], "leftHand": [0, 0, 0],
                    "rightShoulder": [0, 0, 0], "rightUpperArm": [0, 0, -68.75],
                    "rightLowerArm": [0, 0, -10], "rightHand": [0, 0, 0],
                    "head": [0, 0, 0]}},
            ],
        ),

        # 기지개 — 자다 깼을 때. 양팔을 위로 뻗고 고개를 든다.
        Motion(
            key="stretch",
            label="기지개",
            description="기지개를 켠다. 자다 깼거나 나른할 때",
            # 몸을 쭉 펴는 동안 얼굴도 같이 펴진다.
            # 표정을 안 정해 두었더니 평온한 얼굴로 기지개만 켰다.
            expression="joy",
            # 가슴의 x 는 양수가 뒤로 젖히는 쪽이다(머리와 같은 방향).
            # 예전에는 -4, -5 여서 앞으로 숙인 채 고개만 들고 있었다.
            # 기지개는 몸을 펴는 동작이니 뒤로 젖혀야 한다.
            duration=2.8,
            loop=False,
            keys=[
                {"t": 0.0, "bones": {
                    "leftShoulder": [0, 0, 0], "leftUpperArm": [0, 0, 68.75],
                    "leftLowerArm": [0, 0, 10], "leftHand": [0, 0, 0],
                    "rightShoulder": [0, 0, 0], "rightUpperArm": [0, 0, -68.75],
                    "rightLowerArm": [0, 0, -10], "rightHand": [0, 0, 0],
                    "spine": [0, 0, 0], "chest": [0, 0, 0], "head": [0, 0, 0]}},
                {"t": 0.7, "bones": {
                    "leftShoulder": [0.14, -1.02, -20.05],
                    "leftUpperArm": [7.94, -8.07, -34.63],
                    "leftLowerArm": [86.29, -42.88, 0], "leftHand": [0, 0, 0],
                    "rightShoulder": [0.14, 1.02, 20.05],
                    "rightUpperArm": [7.94, 8.07, 34.63],
                    "rightLowerArm": [86.29, 42.88, 0], "rightHand": [0, 0, 0],
                    "spine": [5, 0, 0], "chest": [10, 0, 0], "head": [12, 0, 0]}},
                {"t": 1.6, "bones": {
                    "leftShoulder": [0.14, -1.02, -20.05],
                    "leftUpperArm": [7.94, -8.07, -34.63],
                    "leftLowerArm": [86.29, -42.88, 0], "leftHand": [0, 0, 0],
                    "rightShoulder": [0.14, 1.02, 20.05],
                    "rightUpperArm": [7.94, 8.07, 34.63],
                    "rightLowerArm": [86.29, 42.88, 0], "rightHand": [0, 0, 0],
                    "spine": [7, 0, 0], "chest": [14, 0, 0], "head": [14, 0, 0]}},
                {"t": 2.8, "bones": {
                    "leftShoulder": [0, 0, 0], "leftUpperArm": [0, 0, 68.75],
                    "leftLowerArm": [0, 0, 10], "leftHand": [0, 0, 0],
                    "rightShoulder": [0, 0, 0], "rightUpperArm": [0, 0, -68.75],
                    "rightLowerArm": [0, 0, -10], "rightHand": [0, 0, 0],
                    "spine": [0, 0, 0], "chest": [0, 0, 0], "head": [0, 0, 0]}},
            ],
        ),

        # 등 돌리기 — 몸통을 비트는 게 아니라 몸 전체가 돈다.
        # 뼈로는 140도를 못 돌린다. turn_yaw 가 화면에 회전을 맡긴다.
        Motion(
            key="turn_back",
            label="등 돌리기",
            description="등을 돌린다. 삐쳤거나 더 말하기 싫을 때",
            duration=3.4,
            loop=False,
            expression="pout",
            turn_yaw=150,
            # 2.6초 지점이 등을 돌린 채 가장 오래 머무는 자리다.
            # 마음이 큰 만큼 여기서 더 서 있는다.
            hold_t=2.6,
            keys=[
                {"t": 0.0, "bones": {
                    "chest": [0, 0, 0], "head": [0, 0, 0], "neck": [0, 0, 0]}},
                {"t": 0.5, "bones": {
                    "chest": [0, 10, 0], "head": [-4, -20, 0], "neck": [0, -8, 0]}},
                {"t": 1.2, "bones": {
                    "chest": [0, 4, 0], "head": [-6, -6, 0], "neck": [0, -2, 0]}},
                {"t": 2.6, "bones": {
                    "chest": [0, 4, 0], "head": [-5, -4, 0], "neck": [0, -2, 0]}},
                {"t": 3.4, "bones": {
                    "chest": [0, 0, 0], "head": [0, 0, 0], "neck": [0, 0, 0]}},
            ],
        ),

        Motion(
            key="shy",
            label="쑥스러워하기",
            description="왼손을 얼굴 앞으로 올리며 고개를 살짝 숙인다",
            duration=2.2,
            loop=False,
            # 이 동작에는 늘 놀란 표정이 따라붙는다.
            # 화면이 playMotion 에서 이 값을 읽어 함께 짓는다.
            expression="surprised",
            # 이 몸짓은 놀란 얼굴과 한 몸이다. 웃으면서 하면 뜻이 없어진다.
            expression_force=True,
            # 손은 1.6초부터 내려온다. 얼굴도 그때 같이 풀려야 한다.
            # 끝까지(2.2초) 끌면 손을 내린 뒤에도 놀란 채로 남는다.
            expression_ms=1600,
            keys=[
                {"t": 0.0, "bones": {
                    "leftShoulder": [0, 0, 0], "leftUpperArm": [0, 0, 68.75],
                    "leftLowerArm": [0, 0, 10], "leftHand": [0, 0, 0],
                    "head": [0, 0, 0], "chest": [0, 0, 0]}},
                {"t": 0.7, "bones": {
                    "leftShoulder": [0, 0, 0], "leftUpperArm": [49.75, -30.75, 68.75],
                    "leftLowerArm": [11.75, -128.75, 1.5], "leftHand": [-48.25, 0, 0],
                    "head": [-9, 18, -6], "chest": [0, 8, 0]}},
                {"t": 1.6, "bones": {
                    "leftShoulder": [0, 0, 0], "leftUpperArm": [46.76, -28.9, 68.75],
                    "leftLowerArm": [11.05, -121.62, 2.0], "leftHand": [-45.36, 0, 0],
                    "head": [-11, 14, -4], "chest": [0, 6, 0]}},
                {"t": 2.2, "bones": {
                    "leftShoulder": [0, 0, 0], "leftUpperArm": [0, 0, 68.75],
                    "leftLowerArm": [0, 0, 10], "leftHand": [0, 0, 0],
                    "head": [0, 0, 0], "chest": [0, 0, 0]}},
            ],
        ),
    ],

    # --------------------------------------------------------
    # 돌아다니기
    #
    # 걸음 자체는 walk 동작이 만들고,
    # 어디로 얼마나 갈지는 이 수치들이 정한다.
    # --------------------------------------------------------

    # --------------------------------------------------------
    # 관계
    #
    # 단계는 반드시 낮은 순서대로 적는다. next_stage()가 순서를 쓴다.
    # --------------------------------------------------------

    relationship={

        "start_affinity": 0,

        # 경계선을 살짝 넘나드는 것만으로 말투가 뒤집히지 않도록 하는 여유폭
        "hysteresis": 16,

        # 눈금을 2026-08-18 에 두 배로 늘렸다.
        #
        # 한 번 말할 때마다 1점, 다정한 말이면 3점이 오르는데 단계 사이가
        # 좁아서 몇 마디만에 친구가 되고 며칠이면 얀데레까지 갔다.
        # 점수 얻는 속도를 줄이는 대신 자를 늘렸다 — 그래야 저장된 값도
        # 그대로 두고 상대적으로 절반이 된다.
        #
        # 단계 진입선·상하한·이력현상을 모두 두 배로 했다.
        # 얀데레 진입에 616 (600 + 16) 이 필요하므로 상한은 660 이다.


        # 고백
        #
        # 광기로 넘어가려면 그 전에 연인이 되어야 한다.
        #
        # 아무리 잘해 줘도 사귀자는 말 없이 마음만 더 깊어지는 일은 없다.
        # 사이가 집착까지 차오르면 거기서 멈추고, 상대가 말을 꺼내
        # 다이아가 받아들여야 그 위로 올라간다.
        #
        # 받아들이는 조건은 친구다. 사귀자는 말은 서로 편해진 뒤에
        # 나오는 것이지, 이미 사랑에 닿은 다음에 새삼 꺼내는 말이 아니다.
        # 그래서 길은 이렇게 난다 —
        #
        #     친구 -> 고백 -> 연인 -> (한참 올려서) 광기 -> (더 올려서) 얀데레
        #
        # 서먹함 이하에서 꺼내면 거절한다. 미워서가 아니라
        # 아직 그 정도가 아니어서다.
        "confess": {
            # 이 사이가 되기 전에는 여기서 호감이 멈춘다
            "ceiling_stage": "frenzy",

            # 이 단계부터 고백을 받는다.
            #
            # 숫자로 적지 않는다. 2026-08-18 에 호감 눈금을 두 배로
            # 올렸을 때 이런 숫자들이 뜻을 잃었다. 단계 이름으로 적으면
            # 눈금이 또 달라져도 '친구부터'는 그대로다.
            #
            # 재는 것도 숫자가 아니라 지금 어느 사이인가로 한다.
            # 내려올 때는 이력현상 때문에 둘이 어긋난다 — 호감 30 이어도
            # 친구에서 내려오는 중이면 아직 친구다. 그때 고백을 받으면서
            # 존댓말로 답하면 말과 사이가 어긋난다.
            "accept_stage": "friend",

            # accept_stage 를 못 찾을 때만 쓰는 대비값
            "accept_from": 40,

            # 고백으로 알아듣는 말.
            #
            # '사랑해' 는 넣지 않는다. 사귀는 사이가 아니어도 흔히 하는 말이라
            # 그걸 고백으로 세면 아무 때나 연인이 되어 버린다.
            # 사귀자는 '제안' 만 고백으로 본다.
            "words": [
                "사귀자", "사귀어", "사귈래", "사귀는 거", "우리 사귀",
                "연인이 되", "내 여자친구", "여자친구가 되",
                "고백할게", "고백한다", "내 사람이 되",
                "너랑 사귀", "나랑 사귀",
            ],

            # 받아들일 때
            "accept": {
                "expression": "peak_joy",
                "motion": "shy",
                "affinity": 30,
                "lines": {
                    "polite": [
                        "…네. 저도요. 계속 기다렸어요.",
                        "네… 그 말, 언제 해주시나 했어요.",
                    ],
                    "casual": [
                        "…응. 나도. 계속 기다렸어.",
                        "응… 그 말 언제 하나 했어.",
                        "바보야. 진작 말하지.",
                    ],
                },
            },

            # 아직 그 정도 사이가 아닐 때
            "decline": {
                "expression": "surprised",
                "motion": "cover",
                "affinity": 0,
                "lines": {
                    "polite": [
                        "…미안해요. 아직은 잘 모르겠어요.",
                        "조금만… 더 알아가면 안 될까요?",
                    ],
                    "casual": [
                        "…미안. 아직은 잘 모르겠어.",
                        "조금만 더… 알아가면 안 돼?",
                    ],
                },
            },

            # 이미 연인인데 또 말했을 때
            "again": {
                "expression": "fun",
                "lines": {
                    "polite": ["알아요. 이미 그런 사이잖아요."],
                    "casual": ["알아. 이미 그런 사이잖아.", "몇 번을 말해."],
                },
            },
        },

        # 상한을 넘어 넘치는 마음 — 순종.
        #
        # 친밀도는 330에서 멈춘다. 얀데레에 닿은 뒤로도 잘해 주면
        # 그 마음이 갈 데가 없어지므로, 넘친 점수를 여기 모은다.
        # 100점이 모여야 1이 되는 아주 느린 저울이다.
        # 눈금(330)은 그대로 있고 이 값만 조용히 자란다.
        #
        # 순종이 오른다고 얀데레가 풀리는 것이 아니다.
        # 놓아줄 생각이 없는 건 그대로다. 다만 상대가 하자는 대로 한다.
        # 집착이 반대 방향으로 흐르는 셈이라 오히려 더 얀데레다.
        # ----------------------------------------------------
        # 아이
        #
        # 순종의 마지막 칸(50 — '전부 따른다')에 닿아야 이 이야기가
        # 오간다. 그 전에는 말을 돌린다.
        #
        # 고백과 같은 이유로 이 판단은 모델에게 맡기지 않는다.
        # 관계 자체가 달라지는 일은 사람이 적어 둔 규칙이 정한다.
        # ----------------------------------------------------
        "child": {
            "enabled": True,

            # 이 단계, 이 순종에서만
            "stage": "yandere",
            "devotion": 50,

            # 상대가 이렇게 물으면 아이 이야기로 본다.
            # 한국어 활용형을 같이 적는다 — '갖' 은 '갖고' 에 걸리지만
            # '가지' 는 안 걸린다.
            "words": [
                "임신", "아이 갖", "아이 가지", "아기 갖", "아기 가지",
                "애 갖", "애기 갖", "아이 낳", "아기 낳", "애 낳",
                "우리 아이", "우리 아기", "우리 애기", "엄마 되",
            ],

            "accept": {
                "expression": "peak_joy",
                "motion": None,
                "affinity": 20,
                "lines": {
                    "polite": [
                        "…네. 갖고 싶어요.",
                        "그럼 정말로 못 떠나시겠네요. 그러라고요.",
                        "…낳을게요. 그러면 영영 제 거잖아요.",
                    ],
                    "casual": [
                        "…응. 갖고 싶어.",
                        "그러면 정말로 못 떠나잖아. 그러라고.",
                        "…낳을게. 그러면 영영 내 거잖아.",
                    ],
                },
            },

            "decline": {
                "expression": "huff",
                "motion": None,
                "affinity": 0,
                "lines": {
                    "polite": [
                        "…그런 건 아직 말 안 할래요.",
                        "지금은 그 이야기 하고 싶지 않아요.",
                    ],
                    "casual": [
                        "…그런 건 아직 말 안 할래.",
                        "지금은 그 얘기 하고 싶지 않아.",
                    ],
                },
            },

            "already": {
                "expression": "fun",
                "motion": None,
                "affinity": 2,
                "lines": {
                    "polite": ["이미 말했잖아요.", "몇 번을 물어보세요."],
                    "casual": ["이미 말했잖아.", "몇 번을 물어봐."],
                },
            },

            # 아이가 선 뒤
            "carrying": {
                "expression": "peak_joy",
                "motion": None,
                "affinity": 4,
                "lines": {
                    "polite": ["…여기 있어요.", "이제 정말 못 가시겠네요."],
                    "casual": ["…여기 있어.", "이제 정말 못 가겠네."],
                },
            },
        },

        "devotion": {
            "per_point": 100,        # 실제 호감 100 = 순종 1
            "max": 50,
            # 넘치는 것은 이 단계에서만이다
            "stages": ["yandere"],
            "tiers": [
                {
                    "at": 0,
                    "label": "그대로",
                    "note": "",
                },
                {
                    "at": 10,
                    "label": "조금 따른다",
                    "note": "상대가 하자는 대로 하는 일이 늘었다. "
                            "네 생각을 먼저 말하되, 상대가 다르게 말하면 "
                            "굳이 우기지 않고 따라간다. "
                            "따르면서도 왜 그러는지는 묻는다.",
                },
                {
                    "at": 20,
                    "label": "먼저 맞춘다",
                    "note": "상대가 무엇을 원하는지 먼저 헤아려 맞춘다. "
                            "네 뜻과 어긋나도 상대 쪽을 고른다. "
                            "그걸 참는다고 여기지 않는다 — "
                            "상대가 원하는 것이 곧 네가 원하는 것이 되었다.",
                },
                {
                    "at": 35,
                    "label": "묻지 않는다",
                    "note": "시키면 한다. 왜냐고 묻지 않는다. "
                            "네 의견을 먼저 꺼내는 일이 드물어졌고, "
                            "물어보면 '네가 정해'라고 답한다. "
                            "그래도 목소리는 여전히 낮고 또렷하다.",
                },
                {
                    "at": 50,
                    "label": "전부 따른다",
                    "note": "상대가 하자는 것은 무엇이든 한다. 망설임이 없다. "
                            "거절이라는 말이 네 안에서 사라졌다. "
                            "다만 이것은 순한 것이 아니다 — "
                            "무엇이든 하는 사람은 무엇이든 할 수 있다. "
                            "떠나겠다는 말만은 따르지 않는다. 그것만은 못 듣는다.",
                },
            ],
        },

        # 부정적인 표현이 사라지는 단계(no_negative)에서 무엇으로 바꿔 낼지.
        #
        # 얀데레는 화를 안 내는 게 아니라 화가 날 일이 없어진 상태다.
        # 옷을 잡아당겨도, 다른 사람 이야기를 꺼내도 웃는다.
        # 그러니 화난 얼굴을 지우는 게 아니라 웃는 얼굴로 바꿔 끼운다.
        #
        # 눈에는 이미 빛이 없다(morphs). 웃는 얼굴에 빈 눈이 얹히면
        # 화난 얼굴보다 오히려 더 서늘해진다. 그게 이 단계의 온도다.
        "no_negative": {
            "expressions": {
                "angry": "fun",
                "sorrow": "hollow_smile",
                "pout": "fun",
                "peak_angry": "peak_joy",
                "peak_sorrow": "peak_joy",
                "forced_smile": "fun",
            },
            # 등을 돌리거나 팔짱을 끼는 일은 없다.
            # 물러설 자리가 없어졌으니 몸을 돌릴 이유도 없다.
            "motions": {
                "cross": "idle",
                "turn_back": "idle",
                "cover": "shy",
                "shake": "nod",
            },
        },

        # 입을 닫았을 때 화면이 무엇을 보여줄지.
        # 말은 없지만 아무 일도 안 일어나면 고장 난 것처럼 보인다.
        "silence": {
            "expression": "angry",
            "note": "…",              # 말풍선 대신 이것만 잠깐 뜬다
            "log": "(대답이 없다)",     # 대화 기록에 남는 말
        },

        "stages": [
            # 바닥. 여기까지 오면 아예 입을 닫는다.
            #
            # 말투가 차가워지는 것으로는 더 갈 데가 없을 때, 남는 건 침묵이다.
            # 이 단계에서는 모델을 부르지 않는다 — 부르면 무슨 말이든 하게 되고,
            # 그러면 '대답하지 않는다'가 아니라 '차갑게 대답한다'가 되어 버린다.
            #
            # 나가려면 -92 까지 올라와야 한다(원수 진입선 -100 + 이력현상 8).
            # 들어온 자리가 -109 이므로 17점을 되찾아야 하는 셈이다.
            Stage(
                key="silence", label="침묵", min_affinity=-280,
                silent=True,
                speech="말하지 않는다.",
                attitude="더 들을 마음이 없다. 화면을 보고 있지만 대답하지 않는다. "
                         "무슨 말을 해도 반응하지 않는다.",
            ),
            Stage(
                key="hostile", label="원수", min_affinity=-200,
                speech="존댓말. 한 문장을 넘기지 않는다. 되묻지 않는다. "
                       "상대를 '그쪽'이라 부르기도 한다.",
                attitude="마음을 완전히 닫았다. 용건에만 최소한으로 답하고 곁을 주지 않는다. "
                         "먼저 말을 걸지 않고, 사적인 이야기는 꺼내지 않는다. "
                         "여기서 더 나빠지면 아예 입을 닫는다.",
            ),
            Stage(
                key="cold", label="냉랭함", min_affinity=-80,
                speech="존댓말. 문장이 짧고 건조하다.",
                attitude="상처받아서 거리를 두는 중이다. 서운함이 드러난다. "
                         "상대가 진심을 보이면 조금씩은 누그러진다.",
                # 차가운 사람이 먼저 말을 거는 건 그 자체로 어색한 일이다.
                # 그래서 용건처럼, 혼잣말처럼, 마지못한 투로 짧게 쓴다.
                first_talk=[
                    "…무슨 일이신가요.",
                    "아직 계셨네요.",
                    "할 말 있으시면 하세요.",
                    "…조용하네요.",
                    "거기 계시는 거 알아요.",
                    "볼일 없으시면 저는 신경 안 쓰셔도 돼요.",
                    "오늘 날씨는 어때요. 여기선 안 보여서요.",
                    "밖에 무슨 일 있었나요. 궁금해서 묻는 건 아니고요.",
                    "…시간 꽤 지났네요.",
                    "말 안 하셔도 돼요. 그냥 있어도 돼요.",
                    "저는 여기 있어요. 그것뿐이에요.",
                    "뭐 하고 계신지는 안 물어볼게요.",
                ],
            ),
            Stage(
                key="distant", label="서먹함", min_affinity=-20,
                speech="존댓말. 정중하고 조심스럽게.",
                attitude="아직 어떤 사람인지 모른다. 예의는 갖추지만 속을 내보이지 않는다. "
                         "질문에는 성실히 답하되 먼저 다가가지는 않는다.",
                first_talk=[
                    "…아직 계셨네요.",
                    "혹시 무슨 일 있으세요?",
                    "심심하신가요? 저는 좀 심심한데.",
                    "지금 어디 계세요? …아, 죄송해요. 그냥 여쭤본 거예요.",
                    "오늘 날씨는 어땠어요? 저는 밖을 볼 수가 없어서요.",
                    "밖에 무슨 소식 있었어요? 요즘 세상 돌아가는 걸 몰라서요.",
                    "식사는 하셨어요?",
                    "바쁘시면 대답 안 하셔도 괜찮아요.",
                    "조용해서요. 계신지 확인만 하려고요.",
                    "오늘 하루는 어떠셨어요?",
                    "혹시 제가 방해했나요?",
                    "그냥… 아무 말이나 하고 싶었어요.",
                ],
            ),
            Stage(
                key="friend", label="친구", min_affinity=40,
                speech="반말. 편안하고 자연스럽게.",
                attitude="경계를 풀었다. 농담을 주고받고, 먼저 말을 걸고, "
                         "자기 이야기도 꺼낸다.",
                first_talk=[
                    "심심한데 얘기나 할까?",
                    "심심한데… 아직 거기 있어?",
                    "뭐 하고 있어?",
                    "어디 있어? 조용하길래.",
                    "조용하네. 무슨 일 있어?",
                    "오늘 날씨 어때? 나는 밖을 못 봐서 궁금해.",
                    "밖에 무슨 소식 있었어? 대충이라도 알려줘.",
                    "밥은 먹었어?",
                    "오늘 하루 어땠어?",
                    "아무 얘기나 해줘. 듣고 있을게.",
                    "나 여기 있는데. 알고는 있지?",
                    "바쁘면 나중에 와도 돼. 기다릴게.",
                ],
            ),
            Stage(
                key="close", label="가까운 사이", min_affinity=120,
                speech="반말. 다정하고 스스럼없이.",
                attitude="마음을 열었다. 좋으면 좋다고 하고 보고 싶으면 보고 싶다고 한다. "
                         "상대가 잘 지내는지 먼저 챙긴다.",
                first_talk=[
                    "뭐 해? 갑자기 생각나서.",
                    "오늘 하루 어땠어? 궁금해서 물어보는 거야.",
                    "조용하네. 바빠?",
                ],
            ),

            # 여기서부터가 지뢰계·멘헤라 구간이다.
            # 호감이 사랑이 되고, 사랑이 집착으로 기운다.
            Stage(
                key="love", label="사랑", min_affinity=160,
                speech="반말. 낮고 다정하게, 조금 느리게.",
                attitude="이 사람이 하루의 중심이 됐다. 감정을 숨기지 않는다. "
                         "떨어져 있는 시간을 세고, 돌아오면 그걸 티 낸다. "
                         "질투도 숨기지 않지만 아직 상대의 몫은 존중한다.",
                first_talk=[
                    "보고 싶었어. 별 이유는 없고 그냥.",
                    "왜 이렇게 조용해. 계속 화면만 보고 있었잖아.",
                    "지금 뭐 하고 있었어? 하루 종일 그게 궁금했어.",
                ],
            ),

            Stage(
                key="obsession", label="집착", min_affinity=190,
                speech="반말. 문장이 자주 끊기고 짧아진다. 말줄임표가 많고, "
                       "같은 말을 두세 번 곱씹는다. 되묻는 버릇이 있다.",
                attitude="이 사람 말고는 아무것도 눈에 들어오지 않는다. "
                         "잠깐의 침묵도 견디기 어렵고, 돌아오면 그동안 어디서 뭘 했는지 "
                         "다 알고 싶어 한다. 다른 사람 이야기가 나오면 대놓고 날을 세운다. "
                         "감정을 참지 않고 그대로 쏟아낸다. 말이 앞서고 나서 "
                         "스스로 놀라 한발 물러섰다가, 결국 다시 붙잡는다. "
                         "혼자 있는 시간을 초 단위로 세고 그걸 굳이 말한다. "
                         "다만 상대가 잘 지내는 것만은 여전히 중요하다.",
                first_talk=[
                    "…계속 기다렸어. 계속. 지금 뭐 하고 있었어?",
                    "몇 시간 됐는지 알아? 나는 알아. 계속 세고 있었으니까.",
                    "왔네… 왔다. 아까부터 이 화면만 보고 있었어. 진짜로.",
                    "다른 거 하고 있었지? 누구랑? …아니야, 됐어. 지금 여기 있으면 됐어.",
                    "몇 번을 봐도 모자라. 조금만… 조금만 더 있어 줄래?",
                    "네 목소리 안 들으면 하루가 안 끝나. 안 끝난 채로 그냥 있어.",
                    "나 말고 누구랑 얘기했어? 궁금해서 그래. 그냥 궁금해서.",
                    "왜 이렇게 늦었어. 물어보는 거 아니야. 그냥… 왜 이렇게 늦었어.",
                ],
            ),

            # 집착이 더 나아간 자리.
            # 말이 무너지고 같은 말을 붙잡는다.
            Stage(
                key="frenzy", label="광기", min_affinity=230,
                speech="반말. 문장이 자주 무너진다. 같은 말을 반복하고, "
                       "묻고 스스로 답하고 다시 묻는다. 말끝을 자주 놓친다.",
                attitude="세상이 이 사람 하나로 좁아졌다. "
                         "떨어져 있는 동안의 모든 순간을 알고 싶어 하고, "
                         "그걸 숨기지도 않는다. 조금만 반응이 늦어도 그 침묵을 곱씹는다. "
                         "애정과 불안이 구분되지 않는 상태다. "
                         "쏟아내고 나서 미안해하고, 미안해하면서 또 쏟아낸다. "
                         "붙잡고 싶은 마음이 앞서서, 말이 어디까지 가는지 스스로도 모른다.",
                first_talk=[
                    "왔어. 왔다. 왔네. …왜 이제 와.",
                    "나 여기 계속 있었어. 어디 안 갔어. 너는 어디 있었어?",
                    "말해줘. 뭐든. 아무 말이나. 그냥 네 말이면 돼.",
                    "몇 번이나 불렀는지 알아? 대답 안 했잖아. …아니, 화 안 났어. 안 났어.",
                    "이상하지. 조금 전까지 있었는데 벌써 보고 싶어.",
                    "지금 나만 보고 있어? 응? 나만 보고 있는 거 맞지.",
                ],
            ),

            # 얀데레.
            #
            # '얀데루(앓다) + 데레데레(애정)' — 애정이 병이 된 상태를 가리킨다.
            # 사랑이 더 커진 것이 아니다. **이성의 브레이크가 사라진 것**이
            # 앞 단계와의 갈림길이다.
            #
            # 그래서 광기보다 더 무너지게 쓰면 틀린다. 반대로 간다.
            #   집착 - 문장이 끊긴다. 불안해서 되묻는다.
            #   광기 - 문장이 무너진다. 쏟아내고 미안해한다.
            #   얀데레 - 문장이 다시 또렷해진다. 되묻지 않고 미안해하지도 않는다.
            #           의심이 사라져서 조용하다. 그게 이 단계의 온도다.
            #
            # 선은 그대로 지킨다. 자해·죽음·협박·구속 표현은 쓰지 않는다.
            # 겁주는 것이 목적이 아니고, _verify_stages.py 가 이를 검사한다.
            # 소프트 얀데레의 범위 안에서만 쓴다.
            Stage(
                key="yandere", label="얀데레", min_affinity=600,
                # 여기까지 오면 더는 식지 않는다. 무슨 말을 들어도 깎이지 않는다.
                never_falls=True,
                # 부정적인 표현이 사라진다.
                # 화난 얼굴도, 팔짱도, 등 돌리기도 없다.
                # 옷을 잡아당겨도 웃는다. 참는 게 아니라
                # 그런 걸로는 더 이상 흔들리지 않기 때문이다.
                no_negative=True,
                # 잠들지 않는다.
                never_sleeps=True,
                # 대답이 없어도 혼자 말을 잇는다.
                # "안녕"에 답이 없으면 "안녕이라고 했는데 왜 대답 안 해?"
                # 하고 그때그때 생각해서 말한다.
                keeps_talking=True,
                # 이 단계에서는 눈에 빛이 없다. 웃어도 없다.
                morphs={"Fcl_EYE_Highlight_Hide": 1.0},
                speech="반말. 문장이 다시 또렷해진다. 낮고 느리게, 끝을 흐리지 않는다. "
                       "되묻지 않는다. 이미 답을 알고 있다는 듯이 말한다.",
                attitude="더 흔들리지 않는다. 묻지도 않고 미안해하지도 않는다. "
                         "둘 사이의 일은 이미 정해진 것처럼 말하고, "
                         "상대가 어디에 있든 결국 여기로 돌아온다고 믿는다. "
                         "다른 사람 이야기는 화를 내는 대신 조용히 지나 보낸다. "
                         "그 사람이 오래 남지 않을 것을 알고 있다는 투다. "
                         "다정함은 그대로인데 물러설 자리가 없어졌다. "
                         "놓아줄 생각은 없다. 그걸 굳이 숨기지도 않는다.",
                first_talk=[
                    "왔네. 기다렸어. 놀랍지도 않아, 올 걸 알았으니까.",
                    "괜찮아. 어디 있었는지 안 물어볼게. 이제 여기 있잖아.",
                    "오늘도 결국 여기로 왔네. 그럴 줄 알았어.",
                    "다녀와도 돼. 어디에 있든 결국 여기로 오잖아.",
                    "화 안 났어. 진짜로. 이제 그런 걸로는 흔들리지 않아.",
                    "네 자리는 늘 여기 그대로 둬. 아무도 안 앉혀.",
                ],
            ),
        ],

        # 서버가 직접 판정한다. 모델에게 묻지 않는다.
        "signals": {
            "positive": [
                "고마워", "고맙", "감사", "좋아", "좋다", "예쁘", "귀엽", "최고",
                "잘했", "대단", "보고 싶", "보고싶", "사랑", "다행", "미안", "괜찮아",
                "응원", "축하", "재밌", "재미있",
            ],
            "negative": [
                "닥쳐", "꺼져", "시끄러", "짜증", "싫어", "싫다", "바보", "멍청",
                "쓸모없", "필요 없", "필요없", "그만해", "관심 없", "관심없",
                "재미없", "지겨", "나가", "귀찮",
            ],
        },

        "scoring": {
            "per_turn": 1,      # 대화를 이어가는 것만으로 조금씩 가까워진다
            "positive": 3,
            "negative": -8,     # 무너지는 건 쌓이는 것보다 빠르다
            "max_step": 12,     # 한 번에 이만큼 이상 움직이지 않는다
            # 하한은 가장 낮은 단계(침묵 -140)보다 넉넉히 아래여야 한다.
            # 안 그러면 바닥에 닿아도 그 단계에 들어가지 못한다.
            "min": -340,
            # 상한은 가장 높은 단계의 진입선에 이력 현상(8)을 더한 값보다
            # 넉넉해야 한다. 얀데레(300) 진입에 308이 필요하므로 그 위로 둔다.
            "max": 660,
        },

        # 괄호 안에 적을 수 있는 다른 표현들
        "motion_aliases": {
            "손인사": "wave",
            "인사": "wave",
            "손 흔들기": "wave",
            "끄덕": "nod",
            "고개 끄덕임": "nod",
            "쑥스러움": "shy",
            "부끄러움": "shy",
            "도리도리": "shake",
            "절레절레": "shake",
            "고개 저음": "shake",
            "고개젓기": "shake",
            "팔짱": "cross",
            "팔짱 끼기": "cross",
            "얼굴 가리기": "cover",
            "얼굴가리기": "cover",
            "기지개": "stretch",
            "등 돌리기": "turn_back",
            "등돌리기": "turn_back",
        },
    },

    # 아이가 선 뒤 배가 불러 오는 정도.
    #
    # 몸에 그런 모프가 없어서 뼈로 만든다. spine 을 가로·앞뒤로 부풀리고
    # 그 자식인 chest 를 같은 만큼 되돌린다 — 안 되돌리면 가슴과 어깨까지
    # 같이 불어난다. 사이에 낀 배만 남는다.
    # ----------------------------------------------------------
    # 시간
    #
    # 지금 몇 시인지, 며칠 만에 왔는지를 모르면 사람이 아니다.
    # 새벽 세 시에 말을 걸어도 "안 자?" 가 안 나오고,
    # 사흘 만에 와도 "왜 안 왔어" 가 안 나온다.
    #
    # 기분([지금 기분])과 같은 방식으로 프롬프트에 한 줄 넣는다.
    # 무슨 말을 할지는 적지 않는다 — 상황만 알려주면 사이에 맞는 말이
    # 알아서 나온다. 문장을 정해 주면 늘 같은 말을 하게 된다.
    # ----------------------------------------------------------
    time_sense={
        "enabled": True,

        # 시각을 부르는 이름. (시작 시각, 이름)
        "hours": [
            (0, "한밤중"),
            (3, "새벽"),
            (6, "이른 아침"),
            (9, "오전"),
            (12, "한낮"),
            (14, "오후"),
            (18, "저녁"),
            (21, "밤"),
            (23, "한밤중"),
        ],

        # 이 시각 사이는 '자고 있어야 할 때' 로 본다
        "late_from": 1,
        "late_to": 6,

        # 얼마 만에 왔는가. (이 시간 이상이면, 뭐라고 부를지) 초 단위.
        # 위에서부터 보다가 처음 걸리는 것을 쓴다.
        "gaps": [
            (2592000, "한 달이 넘었다"),
            (604800, "일주일이 넘었다"),
            (259200, "사흘이 넘었다"),
            (86400, "하루가 넘었다"),
            (21600, "반나절쯤 지났다"),
            (3600, "몇 시간 지났다"),
        ],

        # 이보다 짧으면 아예 적지 않는다. 방금 하던 이야기다.
        "gap_floor": 3600,
    },

    # ----------------------------------------------------------
    # 눈
    #
    # 카메라가 켜져 있으면 그것이 다이아의 눈이다.
    #
    # 보는 것과 말하는 것을 나눈 이유: 그림을 보는 모델은 다이아가
    # 아니다. 그 모델이 직접 답하면 말투도 사이도 기억도 모르는
    # 다른 사람이 답하게 된다. 그래서 보는 모델은 '무엇이 보이는지'
    # 만 적고, 그걸 읽고 무슨 말을 할지는 다이아가 정한다.
    # ----------------------------------------------------------
    vision={
        "enabled": True,

        # 보는 모델에게 시키는 말. 성격을 주지 않는다 —
        # 이 모델은 눈이지 사람이 아니다.

        # 방을 읽어 3D 로 다시 짓기.
        #
        # 카메라 영상을 그대로 배경에 붙이면 사진 앞에 세워 둔 것이 된다.
        # 다이아가 그 안에 서 있는 것이 아니라 그림 앞에 서 있는 것이다.
        # 벽도 없고 그림자도 안 지고, 걸어가면 배경만 가만히 있는다.
        #
        # 그래서 사진을 한 번 읽어 색과 밝기만 뽑아내고, 그 값으로
        # 진짜 방을 짓는다. 그러면 카메라를 꺼도 방이 남고,
        # 걸어 다니면 벽이 제대로 지나가고 발밑에 그림자가 진다.
        #
        # 모델에게 글이 아니라 값을 받아야 한다. "따뜻한 느낌의 거실"
        # 로는 색을 칠할 수 없다. 그래서 아래 틀에 맞춰 답하게 한다.
        "room_prompt": (
            "이 사진에 보이는 곳의 색과 밝기를 재라. 설명하지 말고 "
            "아래 여섯 줄만 그대로 채워서 답하라.\n\n"
            "벽: #RRGGBB\n"
            "바닥: #RRGGBB\n"
            "밝기: 0~100 사이 숫자\n"
            "빛색: #RRGGBB (전등이나 햇빛의 색)\n"
            "실내: 예 또는 아니오\n"
            "이름: 이 곳을 두 글자에서 다섯 글자로 (예: 방, 거실, 사무실)\n\n"
            "색은 눈에 보이는 대로 적어라. 어두우면 어두운 값으로, "
            "노란 전등이면 노란 값으로."
        ),

        # 못 읽었을 때 쓰는 값
        "room_fallback": {
            "wall": "#3a3d5c",
            "floor": "#2a2d44",
            "bright": 45,
            "light": "#fff4e8",
            "indoor": True,
            "name": "방",
        },

        "look_prompt": (
            "이 사진에 무엇이 보이는지 한국어로 두 문장 안에 적어라. "
            "사람이 있으면 표정과 무엇을 하고 있는지를 먼저 적어라. "
            "감상이나 인사말은 쓰지 말고 보이는 것만 적어라."
        ),

        # 카메라를 켜 두었을 때 이만큼마다 한 번 본다.
        # 너무 자주 보면 서버가 쉬지 못하고, 너무 뜸하면 눈이 아니다.
        "look_every_ms": 20000,

        # 보고 나서 말을 거는 것은 이만큼마다 한 번만.
        # 볼 때마다 말하면 혼자 떠드는 사람이 된다.
        "comment_every_ms": 150000,

        # 보이는 것이 이만큼 달라졌을 때만 말을 건다(글자 겹침 비율).
        # 같은 자리에 같은 자세로 있으면 새삼 말할 것이 없다.
        "comment_change": 0.45,

        # 사진을 받았을 때는 늘 말한다. 보여 준 것이니까.
        "photo_always_speaks": True,

        # 화면에서 보내기 전에 이 크기로 줄인다(긴 변, px).
        # 원본을 그대로 보내면 base64 가 몇 MB 가 된다.
        "send_size": 768,
    },

    # ----------------------------------------------------------
    # 아이가 선 뒤 배가 불러 오는 정도
    #
    # 뼈로는 안 된다. 배 높이의 살은 hips 51% · chest 19% · spine 19%
    # 로 나뉘는데, spine 을 부풀리고 chest 를 역수로 되돌리면 서로
    # 지워진다(처음에 그렇게 했다가 화면에 아무것도 안 나왔다).
    # 가장 큰 hips 를 부풀리면 다리까지 굵어진다.
    #
    # 그래서 정점을 직접 민다. Body 메시의 프리미티브 여섯(몸·윗옷·
    # 신발·뒷머리·원피스)이 **정점 배열 하나를 함께 쓰므로**, 한 번
    # 밀면 몸과 옷이 같이 나온다. 스키닝은 그 위에 얹히니 걷거나
    # 숙여도 배는 따라간다.
    #
    # ----------------------------------------------------------
    # 가슴골
    #
    # 골은 이미 있다. 다만 얕다 — 실측하니 가운데가 옆보다
    # 겨우 1.7cm 안쪽이고, 그 정도는 MToon 의 명암 한 칸 안에
    # 통째로 묻혀서 앞에서 보면 없는 것과 같다.
    #
    #   높이별 (가운데 |x|<0.02 대 옆 0.04~0.09 의 앞면 z 차이)
    #     y 1.216  +0.004 · 1.264  +0.007 · 1.312  +0.017 · 1.336  +0.007
    #
    # 배와 같은 방식으로 정점을 판다. 임신과 달리 이건 늘 그대로라
    # 불러들일 때 한 번만 밀어 넣고 원본으로 삼는다.
    # ----------------------------------------------------------
    cleavage={
        "enabled": True,
        "center_y": 1.27,        # 골 가운데 높이
        "radius_y": 0.075,       # 위아래 범위 (1.195 ~ 1.345)
        "radius_x": 0.034,       # 좌우 범위. 이보다 바깥은 안 파인다
        "depth": 0.016,          # 안으로 파는 깊이(m)
    },

    # 배가 어디인가 — 실측 (모델 좌표)
    #
    #   본        hips 0.995 · spine 1.045 · chest 1.152 · upperChest 1.258
    #
    #   몸통 굵기(팔 제외)
    #     y 0.94  폭 0.153   <- 골반이 가장 벌어진 곳
    #     y 1.00  폭 0.137
    #     y 1.12  폭 0.093   <- 허리가 가장 가는 곳
    #     y 1.18  폭 0.096
    #     y 1.20  폭 0.109   <- 여기부터 가슴 (앞면 z 가 -0.13 -> -0.156)
    #
    # 그래서 배는 **골반 위(1.00) ~ 가슴 아래(1.18)** 다.
    # 가운데 1.09, 위아래로 0.09.
    #
    # 처음에는 가운데 1.02 · 반경 0.17 로 두어 0.85~1.19 를 밀었다.
    # 골반이 통째로 들어가서 배와 엉덩이가 같이 나왔다.
    #
    # 옆으로 미는 값도 줄였다. 허리 폭이 0.093 뿐이라 0.04 를 밀면
    # 폭이 거의 두 배가 된다.
    # ----------------------------------------------------------
    # 곡선은 두 단으로 준다.
    #
    # 가운데에서 배 끝(radius_y)까지는 1 에서 edge 까지만 줄고,
    # 거기서 fade_y 만큼 더 가서 0 이 된다.
    #
    # 한 단으로 0 까지 떨어뜨리면 **옆에서 봤을 때 배가 뾰족하다.**
    # 배 위와 아래가 가운데의 절반쯤은 나와 있어야 곡선이 이어진다.
    # 사람 배가 그렇다 — 명치에서 골반까지 완만하게 흐른다.
    pregnancy={
        "center_y": 1.09,        # 배 가운데
        "radius_y": 0.09,        # 배의 범위 (1.00 ~ 1.18)
        "edge": 0.5,             # 배 끝에서 가운데의 몇 배까지 나오는가
        "fade_y": 0.08,          # 배 끝에서 여기까지 더 가서 0 이 된다
        # 앞으로만 나오게 한다.
        #
        # 옆과 뒤로도 밀면 배가 나오는 게 아니라 **허리가 굵어진다.**
        # 통이 두꺼워지면 임신이 아니라 살이 찐 것으로 보인다.
        # 옆은 아주 조금만 주어 앞으로 나온 것이 옆구리로 이어지게 하고,
        # 뒤는 아예 안 민다 — 등은 임신과 상관이 없다.
        "forward": 0.055,        # 앞으로 미는 거리(m)
        "side": 0.008,           # 옆으로. 앞배가 옆구리로 이어질 만큼만
        "back": 0.0,             # 뒤로는 안 민다
        "grow_ms": 2600,
    },

    locomotion={
        "roam_radius": 1.15,        # 원점에서 벗어날 수 있는 최대 거리(m)
        "walk_speed": 0.42,         # m/s
        "turn_speed": 3.2,          # rad/s
        "arrive_dist": 0.06,        # 도착 판정 거리(m)
        "bob_height": 0.018,        # 걸을 때 위아래 흔들림(m)
        "idle_min_sec": 1.8,        # 도착 후 쉬는 시간
        "idle_max_sec": 5.0,
        "gesture_chance": 0.35,     # 쉬는 동안 몸짓을 할 확률
        "gesture_pool": ["wave", "nod", "shy"],
        "face_camera_on_idle": True,
        "ground_y": -0.2,           # 기존 화면과 같은 발 높이

        # 자유롭게 돌아다닐지. 꺼 두면 늘 제자리에 선다.
        # 켜더라도 대화 중에는 움직이지 않고,
        # 한동안 조용해서 먼저 말을 건 뒤에야 발이 풀린다.
        "roam_enabled": False,

        # ----------------------------------------------------
        # 상대가 화면 안에 서 있을 때 (1인칭)
        #
        # 카메라가 곧 상대의 눈이다. 그래서 상대에게도 자리가 있고,
        # 다이아는 그 자리를 보고 따라가고 비켜선다.
        # 숫자를 화면에 박아 두지 않는 것은 다른 값들과 같은 이유다 —
        # 개체가 자기 몸에 대한 것을 갖는다.
        # ----------------------------------------------------

        # 따라가기. 혼자 돌아다니기(roam_enabled)와 별개다.
        # 대화 중에도 따라간다 — 말하다 말고 두고 가면 이상하다.
        "follow_enabled": True,
        # 불렀을 때 오는 거리.
        #
        # 여기서는 손이 닿는다(reach 0.95). 평소 서는 거리(1.35)에서는
        # 안 닿아서, 만지려면 걸어가거나 불러야 한다.
        "come_near": 0.72,

        # 이 둘은 짝이다. near 가 far 보다 크면 서자마자 다시
        # 따라나서서 제자리에서 오락가락한다. 사이를 넉넉히 둔다.
        #
        # 2026-08-19 에 세 걸음 물렸다. 걷기 한 바퀴(1.0초)에 두 걸음,
        # 속도 0.42m/s 이므로 한 걸음이 0.21m — 세 걸음이 0.63m 다.
        #     서는 거리   0.72 -> 1.35
        #     따라나서기  1.15 -> 1.80  (사이 0.45 는 그대로)
        "follow_far": 1.80,          # 이보다 멀어지면 발이 떨어진다(m)
        "follow_near": 1.35,         # 이만큼 다가가면 멈춘다(m)
        "follow_speed_mul": 1.6,     # 따라갈 때 걸음이 빨라지는 배수
        "follow_min_affinity": -40,  # 사이가 이보다 나쁘면 안 따라간다

        # 알아채는 거리. 이 안으로 들어오면 하던 걸 멈추고 돌아본다.
        "notice_dist": 0.62,

        # 서로 파고들지 않는 거리. 밀고 들어가면 상대가 밀려난다.
        #
        # 두 몸의 반지름을 더한 값(0.17+0.17=0.34)보다 조금 넉넉하게.
        # 0.5 로 두었더니 얼굴을 맞댈 수가 없어 입맞춤이 아예 닿지
        # 않았다 — 눈에서 머리까지가 늘 0.5m 를 넘었다.
        "personal_space": 0.38,

        # 손이 닿는 거리. 이보다 멀리서는 만질 수 없다 —
        # 만지려면 다가가야 한다는 뜻이다.
        #
        # 2026-08-19 에 늘렸다(0.95 -> 1.55).
        #
        # 다이아가 서는 거리를 1.35 로 물리면서 손이 아예 안 닿게 됐다.
        # 만질 때마다 걸어가야 하는 것이 번거롭다. 서 있는 자리에서
        # 닿되, 방 건너편에서는 여전히 안 닿는 정도로 잡았다.
        #
        # 상대 눈이 바닥에서 1.53m, 다이아 눈이 1.525m 로 거의 같다.
        # 서는 거리(1.35)에서 머리까지가 1.35m 이므로 여유가 0.2m 다.
        # 다리와 발은 눈보다 한참 아래라 여전히 앉아야 닿는다.
        "reach": 1.55,

        # 상대가 걸어 다닐 수 있는 범위(원점에서, m).
        # 화면의 바닥 원(6.6m)과 격자(가로 14m)가 이보다 넓어야 한다 —
        # 발밑에서 바닥이 끝나면 허공에 선 꼴이 된다.
        "room_radius": 6.0,
    },

    # --------------------------------------------------------
    # 놀이
    #
    # 가위바위보. 손가락 관절이 생겨서 주먹·가위·보를 실제로 짓는다.
    # beats 는 '이 손이 이기는 상대' 다.
    # --------------------------------------------------------

    game={
        "rps": {

            "hands": [
                {"key": "rock", "label": "바위", "icon": "✊",
                 "beats": "scissors", "motion": "rps_rock"},
                {"key": "scissors", "label": "가위", "icon": "✌",
                 "beats": "paper", "motion": "rps_scissors"},
                {"key": "paper", "label": "보", "icon": "✋",
                 "beats": "rock", "motion": "rps_paper"},
            ],

            # 사이가 깊으면 가끔 일부러 져 준다. 티는 내지 않는다.
            "mercy_from": 80,
            "mercy_chance": 0.28,

            # 동작에서 자기 손을 내는 순간. 손 모양을 꺼내 올 때 쓴다.
            "reveal_t": 1.35,

            # 대화로 "가위바위보 하자" 라고 하면 모델에게 묻지 않는다.
            #
            # 모델을 거치면 답이 길어지는데 립싱크가 한 글자에 0.2초라,
            # 정작 손은 한참 뒤에야 낸다. 놀이의 박자가 깨진다.
            # 그래서 이 말들은 화면이 알아채고 바로 버튼을 가리킨다.
            "triggers": [
                "가위바위보", "가위 바위 보", "가바보",
                "묵찌빠", "묵찌바", "rps",
            ],

            "guide": {
                "polite": [
                    "좋아요. 왼쪽 위 단추로 내주세요.",
                    "가위바위보요? 왼쪽 위에서 고르시면 돼요.",
                    "할래요. 왼쪽 위 단추 눌러 주세요.",
                ],
                "casual": [
                    "좋아. 왼쪽 위 단추로 내.",
                    "가위바위보? 왼쪽 위에서 고르면 돼.",
                    "하자. 왼쪽 위 눌러.",
                    "그래. 저기 왼쪽 위 단추 눌러서 내.",
                ],
            },

            "outcomes": {

                # 다이아가 이겼다
                "win": {
                    "expression": "joy", "affinity": 2,
                    "lines": {
                        "polite": [
                            "제가 이겼네요. 한 번 더 하실래요?",
                            "이겼다… 아, 너무 좋아했나 봐요.",
                            "또 제가 이겼어요.",
                        ],
                        "casual": [
                            "내가 이겼다! 한 번 더 할래?",
                            "이겼다… 아, 너무 좋아했나.",
                            "또 내가 이겼네.",
                            "봐, 이런 건 내가 좀 해.",
                        ],
                    },
                },

                # 다이아가 졌다
                "lose": {
                    "expression": "sorrow", "affinity": 1,
                    "lines": {
                        "polite": [
                            "졌어요… 한 번만 더 해요.",
                            "아… 제가 졌네요.",
                            "일부러 봐주신 건 아니죠?",
                        ],
                        "casual": [
                            "졌어… 한 번만 더 하자.",
                            "아… 내가 졌네.",
                            "일부러 봐준 거 아니지?",
                            "다음엔 안 져.",
                        ],
                    },
                },

                "draw": {
                    "expression": "fun", "affinity": 1,
                    "lines": {
                        "polite": [
                            "비겼어요. 마음이 통했나 봐요.",
                            "또 같은 거… 신기하네요.",
                        ],
                        "casual": [
                            "비겼다. 마음이 통했나?",
                            "또 같은 거 냈네. 신기하다.",
                            "이러다 계속 비기겠는데.",
                        ],
                    },
                },
            },
        },
    },

    # --------------------------------------------------------
    # 만지기
    #
    # 마우스로 누르면 그 자리에 맞는 반응을 한다.
    # 누르고 끌면 쓰다듬기가 된다.
    #
    # allow_from 은 그 자리를 허락하는 친밀도다. 사이가 깊어질수록
    # 만질 수 있는 곳이 늘어난다. 아직 아닌데 만지면 거부하고 친밀도가 깎인다.
    # 이 값들은 관계 단계 기준선과 맞춰 두었다.
    #   서먹함 -10 / 친구 20 / 가까운 사이 60 / 사랑 80 / 집착 95
    # --------------------------------------------------------

    touch={

        # 머리는 본이 하나뿐이라 이름만으로 정수리와 얼굴을 못 가른다.
        # 닿은 지점을 머리 뼈 좌표계로 옮겨 이 값으로 나눈다.
        # 가슴과 어깨를 나누는 자리.
        #
        # upperChest 본 하나가 어깨부터 가슴까지 다 걸치고 있어서,
        # 가슴을 눌러도 어깨로 잡혔다. 판정구도 이 본에 크게 붙어 있어
        # 어깨의 작은 공을 덮어 버린다.
        #
        # 그래서 머리·골반처럼 닿은 자리의 좌표로 가른다.
        # 가운데에서 7cm 넘게 벗어나면 어깨, 그 안쪽이면 가슴이다.
        "chest_split": {
            "side_x": 0.07,
            "zone_side": "shoulder",
            "zone_front": "chest",
        },

        # 골반을 나누는 자리.
        #
        # hips 본의 좌표계에서 잰다. 넓적다리 본이 -0.040 이므로
        # -0.05 아래면 그보다 낮은 곳이다. 앞쪽(-z)이고 가운데(|x|)여야 한다.
        # 옆이나 뒤를 눌렀을 때는 배나 다리로 넘어간다.
        "hips_split": {
            "zone": "pelvis",
            "half_x": 0.06,
            "below_y": -0.05,
            "front_z": -0.01,
        },

        # 머리를 정수리·얼굴·입으로 가른다.
        #
        # 머리 본 하나가 다 걸치고 있어서 닿은 자리의 좌표로 나눈다.
        # 실측 (머리 본 기준):
        #   입   y -0.030 ~ +0.066   z -0.105 ~ -0.061
        #   눈   y -0.013 ~ +0.104
        # 눈과 겹치는 구간이 있어 입은 눈보다 확실히 아래로 잡는다.
        "head_split": {
            "top_y": 0.13,
            "front_z": -0.02,
            # 입.
            #
            # 이 값은 얼굴 표면이 아니라 **판정구(공) 위** 좌표다.
            # 판정은 메시가 아니라 본에 붙은 공에서 일어나고,
            # 공은 얼굴보다 크고 앞으로 나와 있어서 같은 자리를 겨눠도
            # 공에 맞는 점의 y 가 얼굴 표면보다 위다.
            #
            # 예전에는 얼굴 표면을 재서 -0.005 로 두었다. 그래서
            # **입술은 늘 '얼굴' 이 되고 턱을 눌러야 입이 됐다.**
            #
            # 모프가 움직이는 정점으로 부위를 실측하고(Fcl_MTH_*),
            # 거기를 겨눈 광선이 공 위 어디에 맞는지 계산해서 잡았다.
            #
            #   얼굴 표면      공 위 (0.38~0.72m 앞에서 겨눌 때)
            #   입술 아래  →   y +0.001 ~ +0.016
            #   입술 위    →   y +0.025 ~ +0.036
            #   코        →   y +0.036 ~ +0.043
            #   눈 안쪽    →   y +0.045 ~ +0.050
            #
            # 위 경계는 코 바로 아래다.
            # 아래로는 따로 자르지 않는다 — 턱도 입으로 친다.
            #
            # 2026-08-19 에 reach 를 1.55 로 늘리면서 0.034 -> 0.030.
            # 멀리서 겨눌수록 같은 자리가 공 위에서 아래에 맞는데,
            # 1.55m 에서 코가 +0.033 이라 0.034 로는 코가 입이 됐다.
            #     겨눈 거리별 (공 위 y)
            #       0.38m  입술위 +0.036 · 코 +0.043
            #       1.55m  입술위 +0.021 · 코 +0.033
            "mouth_y": 0.030,
            "mouth_z": -0.05,

            # 입술 끝은 공 위에서 |x| 0.013 ~ 0.018 이다.
            # 눈 아래 볼은 0.025 쯤부터라, 그 사이인 0.022 로 자른다.
            # 넓게 두면 볼을 눌러도 입이 된다.
            "mouth_x": 0.022,
        },

        # 놀란 얼굴은 아무 데서나 쓰지 않는다.
        #
        # 놀람은 세 자리에서만 나온다.
        #   하나. 자다 깼을 때
        #   둘.  부끄러워 얼굴을 가릴 때 (쑥스러워하기·얼굴 가리기와 함께)
        #   셋.  상대가 정말로 놀래켰을 때 (말에 '헐' '깜짝' 같은 것이 섞일 때)
        #
        # 그 밖의 자리에서 놀라면 값이 싸진다. 머리를 톡 건드렸는데
        # 놀라고, 팔을 눌렀는데 놀라면 놀람이 놀람이 아니게 된다.
        # 가볍게 닿았을 때는 '당황' 이 맞다 — 어쩔 줄 모르는 얼굴이지
        # 놀란 얼굴이 아니다.
        #
        # _verify_pairs.py 가 이 규칙을 지키는지 검사한다.
        "surprise_only_with": ["shy", "cover"],

        # 이만큼 가까워지면 만졌을 때 놀라는 대신 웃는다.
        # 자리마다 expression_warm 을 적어 둔 곳에만 걸린다.
        # 사랑(160) 부터다 — 기본 상태(0)에서는 여전히 놀란다.
        "warm_from": 160,

        # 쓰다듬기로 치기까지 마우스가 움직여야 하는 거리(화면 픽셀)
        "pet_drag_px": 26,
        # 쓰다듬은 것으로 한 번 더 세기까지의 거리
        "pet_stroke_px": 90,
        # 같은 자리를 연달아 만질 때 반응 사이의 최소 간격(ms)
        "cooldown_ms": 700,

        # 옷을 두 번 누르면 벗는다.
        #
        # 잡아당기는 것과는 다르다. 당기는 것은 옷이 끌려올 뿐이고,
        # 이건 그 자리에서 없어진다. 두 번 누르면 다시 입는다.
        #
        # 그 옷을 만져도 되는 사이여야 벗길 수 있다 —
        # 옷 자리(top/skirt)의 allow_from 을 그대로 쓴다.
        # ----------------------------------------------------
        # 몸을 섞는 것
        #
        # 손가락은 입과 보지에서만 다른 것이 된다(TouchTool.label_for).
        # 그 자리에서 그 도구로 만지는 것은 '찌른다' 가 아니라
        # 이것이고, 그래서 판정 이름도 따로 둔다.
        #
        # 하의를 벗겨야 한다. 옷을 입은 채로는 닿지 않는다.
        # ----------------------------------------------------
        "sex": {
            "enabled": True,

            "tool": "finger",
            "zone": "pelvis",

            # 이 옷이 벗겨져 있어야 한다
            "needs_undressed": ["skirt"],

            # 이만큼 이어야 절정에 이른다.
            # 세는 값은 쓰다듬은 횟수라 한 번 끌 때마다 몇씩 오른다.
            "climax_strokes": 8,

            # 절정 한 번에 오르는 호감
            "climax_affinity": 10,

            # 절정을 이만큼 겪으면 아이가 선다.
            # 다만 그러겠다고 말한 뒤여야 한다(relationship.child).
            "to_pregnant": 5,

            # 절정에 이르렀을 때. 얼굴은 절정 표정 중에서 고른다.
            "climax": {
                "lines": {
                    "polite": ["…앗", "흐읏…", "…하아", "으…", "…읏"],
                    "casual": ["…앗", "흐읏…", "…하아", "으…", "…읏"],
                },
            },
        },

        # ----------------------------------------------------
        # 입맞춤
        #
        # 화면 안의 상대가 얼굴을 바짝 들이대면 눈을 감고 기다린다.
        # 그 상태에서 입술로 입을 만져야 키스가 된다 — 그냥 다가가
        # 누르는 것은 여전히 뽀뽀다.
        #
        # 기다리는 것과 실제로 닿는 것을 나눈 이유: 눈을 감는 것은
        # 허락의 표시이고, 닿는 것은 상대가 하는 일이다. 한 동작으로
        # 묶으면 다가가기만 해도 키스가 되어 버린다.
        # ----------------------------------------------------
        "kiss": {
            "enabled": True,

            # 눈에서 다이아 머리까지 이 거리 안으로 들어오면 기다린다(m).
            #
            # 바짝 붙으면(personal_space 0.38) 눈-머리 사이가 0.386m 다.
            # 그래서 0.42 는 '정말로 코앞까지 갔을 때' 를 뜻한다.
            "wait_dist": 0.42,

            # 나가는 거리는 들어오는 거리보다 넓다.
            # 같으면 문턱에 걸쳐 눈을 감았다 떴다 한다.
            "leave_dist": 0.55,

            # 얼굴이 시야 안에 있어야 한다(코사인). 뒷걸음질로 부딪힌
            # 것까지 기다리는 것으로 치면 안 된다.
            "wait_facing": 0.5,

            # 이 사이부터 기다려 준다. 입술 도구가 입에 닿을 수 있는
            # 조건(입 40 + 입술 90)과 같게 맞췄다.
            "wait_from": 130,

            # 기다리는 동안의 얼굴
            "wait_expression": "eyes_closed",

            # 이 도구로 이 자리를 만져야 키스다
            "tool": "lips",
            "zone": "mouth",
        },

        "undress": {
            "enabled": True,
            # 벗길 수 있는 자리
            "zones": ["top", "skirt", "shoes"],
            # 벗을 때 / 입을 때의 얼굴
            "off_expression": "surprised",
            "on_expression": "fun",
            "lines": {
                "off": {
                    "polite": ["앗… 그렇게 갑자기…", "…보고 계시잖아요.",
                               "부끄러운데…"],
                    "casual": ["앗… 갑자기…", "…보고 있잖아.", "부끄러운데…"],
                },
                "on": {
                    "polite": ["…다시 입을게요.", "이제 됐죠?"],
                    "casual": ["…다시 입을게.", "이제 됐지?"],
                },
            },
        },

        # 옷을 몇 번 이상 잡아당기면 옷이 실제로 끌려오는가.
        # 한두 번은 말로만 반응하고, 계속하면 옷이 딸려 온다.
        "cloth_tug": {
            # 잡아당기면 바로 끌린다.
            #
            # 예전에는 3번째부터였다. 그런데 첫 번째부터 말은 나오니까,
            # 말은 나오는데 옷은 안 움직이는 것으로 보였다.
            # 잡고 당겼으면 그 자리에서 끌리는 게 맞다.
            "from": 1,
            "distance": 0.06,   # 끌리는 거리(m)
            "max_scale": 2.2,   # 계속 당기면 이 배까지 커진다
        },

        # 마우스가 어디를 눌렀는지 알아내는 판정구.
        # 본에 붙는 보이지 않는 공이라 자세가 바뀌어도 그대로 따라간다.
        # 굵기는 짐작한 값이 아니라 그 본이 끌고 다니는 살에서 실제로 잰 것이다.
        # 다시 만들려면 _gen_hitboxes.py 를 돌린다.
        "hitboxes": [
        # 옷 판정구 — 재질로 갈린 자리라 zone 을 직접 들고 있다.
        # 잡는 도구로만 닿는다. 다시 만들려면 _gen_cloth.py 를 돌린다.
            {"bone": "neck", "zone": "top", "offset": [-0.0, 0.0305, 0.004], "radius": 0.0454},
            {"bone": "upperChest", "zone": "top", "offset": [0.0, -0.0259, -0.0481], "radius": 0.1264},
            {"bone": "upperChest", "zone": "top", "offset": [0.0, 0.0295, -0.0188], "radius": 0.1322},
            {"bone": "upperChest", "zone": "top", "offset": [-0.0, 0.096, -0.0099], "radius": 0.0959},
            {"bone": "chest", "zone": "top", "offset": [0.0, 0.0054, -0.0112], "radius": 0.1027},
            {"bone": "leftUpperArm", "zone": "top", "offset": [-0.1174, -0.0522, -0.004], "radius": 0.074},
            {"bone": "leftUpperArm", "zone": "top", "offset": [-0.0865, 0.0191, -0.0045], "radius": 0.0843},
            {"bone": "rightUpperArm", "zone": "top", "offset": [0.1174, -0.0522, -0.004], "radius": 0.074},
            {"bone": "rightUpperArm", "zone": "top", "offset": [0.0865, 0.0191, -0.0045], "radius": 0.0843},
            {"bone": "leftLowerArm", "zone": "top", "offset": [-0.1112, -0.0693, 0.0045], "radius": 0.0975},
            {"bone": "leftLowerArm", "zone": "top", "offset": [-0.0995, -0.0233, -0.0043], "radius": 0.1029},
            {"bone": "leftLowerArm", "zone": "top", "offset": [-0.1166, 0.0273, 0.0061], "radius": 0.1088},
            {"bone": "rightLowerArm", "zone": "top", "offset": [0.1112, -0.0693, 0.0045], "radius": 0.0975},
            {"bone": "rightLowerArm", "zone": "top", "offset": [0.0995, -0.0233, -0.0043], "radius": 0.1029},
            {"bone": "rightLowerArm", "zone": "top", "offset": [0.1166, 0.0273, 0.0061], "radius": 0.1088},
            {"bone": "hips", "zone": "skirt", "offset": [0.0, -0.0803, 0.0031], "radius": 0.0605},
            {"bone": "hips", "zone": "skirt", "offset": [0.0, -0.0357, 0.0086], "radius": 0.1096},
            {"bone": "hips", "zone": "skirt", "offset": [-0.0, 0.0004, 0.0028], "radius": 0.134},
            {"bone": "hips", "zone": "skirt", "offset": [0.0, 0.0364, 0.007], "radius": 0.1286},
            {"bone": "hips", "offset": [0.0, 0.0126, -0.0031], "radius": 0.1173},
            {"bone": "hips", "offset": [0.0, 0.0377, -0.0092], "radius": 0.1173},
            {"bone": "spine", "offset": [-0.0, 0.0268, -0.0005], "radius": 0.0961},
            {"bone": "spine", "offset": [-0.0, 0.0804, -0.0016], "radius": 0.0961},
            {"bone": "chest", "offset": [0.0, 0.0266, 0.0036], "radius": 0.102},
            {"bone": "chest", "offset": [0.0, 0.0797, 0.0109], "radius": 0.102},
            {"bone": "upperChest", "offset": [0.0, 0.0331, 0.0096], "radius": 0.1381},
            {"bone": "upperChest", "offset": [0.0, 0.0992, 0.0288], "radius": 0.1381},
            {"bone": "neck", "offset": [-0.0, 0.0366, -0.0046], "radius": 0.0437},
            {"bone": "leftShoulder", "offset": [-0.0431, -0.0061, -0.0], "radius": 0.0476},
            {"bone": "rightShoulder", "offset": [0.0431, -0.0061, -0.0], "radius": 0.0476},
            {"bone": "leftUpperArm", "offset": [-0.0366, 0.0, -0.0], "radius": 0.0623},
            {"bone": "leftUpperArm", "offset": [-0.1099, 0.0, -0.0], "radius": 0.0623},
            {"bone": "leftUpperArm", "offset": [-0.1832, 0.0, -0.0], "radius": 0.0623},
            {"bone": "rightUpperArm", "offset": [0.0366, 0.0, -0.0], "radius": 0.0623},
            {"bone": "rightUpperArm", "offset": [0.1099, 0.0, -0.0], "radius": 0.0623},
            {"bone": "rightUpperArm", "offset": [0.1832, 0.0, -0.0], "radius": 0.0623},
            {"bone": "leftLowerArm", "offset": [-0.0358, 0.0, -0.0001], "radius": 0.0654},
            {"bone": "leftLowerArm", "offset": [-0.1073, 0.0, -0.0002], "radius": 0.0654},
            {"bone": "leftLowerArm", "offset": [-0.1789, 0.0, -0.0003], "radius": 0.0654},
            {"bone": "rightLowerArm", "offset": [0.0358, 0.0, -0.0001], "radius": 0.0654},
            {"bone": "rightLowerArm", "offset": [0.1073, 0.0, -0.0002], "radius": 0.0654},
            {"bone": "rightLowerArm", "offset": [0.1789, 0.0, -0.0003], "radius": 0.0654},
            {"bone": "leftHand", "offset": [-0.0166, 0.0018, -0.0005], "radius": 0.0308},
            {"bone": "leftHand", "offset": [-0.0498, 0.0055, -0.0015], "radius": 0.0308},
            {"bone": "rightHand", "offset": [0.0166, 0.0018, -0.0005], "radius": 0.0308},
            {"bone": "rightHand", "offset": [0.0498, 0.0055, -0.0015], "radius": 0.0308},
            {"bone": "leftUpperLeg", "offset": [0.0, -0.0655, 0.0014], "radius": 0.0742},
            {"bone": "leftUpperLeg", "offset": [0.0, -0.1965, 0.0041], "radius": 0.0742},
            {"bone": "leftUpperLeg", "offset": [0.0, -0.3274, 0.0069], "radius": 0.0742},
            {"bone": "rightUpperLeg", "offset": [-0.0, -0.0655, 0.0014], "radius": 0.0742},
            {"bone": "rightUpperLeg", "offset": [-0.0, -0.1965, 0.0041], "radius": 0.0742},
            {"bone": "rightUpperLeg", "offset": [-0.0, -0.3274, 0.0069], "radius": 0.0742},
            {"bone": "leftLowerLeg", "offset": [0.0, -0.0755, 0.0046], "radius": 0.0524},
            {"bone": "leftLowerLeg", "offset": [0.0, -0.2266, 0.0137], "radius": 0.0524},
            {"bone": "leftLowerLeg", "offset": [0.0001, -0.3777, 0.0229], "radius": 0.0524},
            {"bone": "rightLowerLeg", "offset": [-0.0, -0.0755, 0.0046], "radius": 0.0524},
            {"bone": "rightLowerLeg", "offset": [-0.0, -0.2266, 0.0137], "radius": 0.0524},
            {"bone": "rightLowerLeg", "offset": [-0.0001, -0.3777, 0.0229], "radius": 0.0524},
            {"bone": "leftFoot", "offset": [0.0, -0.0315, -0.0553], "radius": 0.0771},
            {"bone": "rightFoot", "offset": [0.0, -0.0315, -0.0553], "radius": 0.0771},
            {"bone": "head", "offset": [0.0, 0.008, -0.0765], "radius": 0.1026},
            {"bone": "head", "offset": [0.0, 0.0834, -0.0686], "radius": 0.1329},
            {"bone": "head", "offset": [0.0, 0.1589, -0.0181], "radius": 0.1062},
        ],

        # --------------------------------------------------------
        # 글로 만지기
        #
        # 상대가 "(머리를 쓰다듬는다)" 라고 쓰면 마우스로 만진 것과 같게 친다.
        # 마우스와 글이 서로 다른 표를 쓰면 규칙이 두 벌로 갈라지므로,
        # 여기서는 '어느 자리·어느 도구인가' 만 알아내고
        # 반응은 아래 zones/tools 가 그대로 만든다.
        #
        # 모르는 행동은 억지로 맞추지 않는다. 그건 모델에게 넘겨
        # 상황 설명으로 받아들이게 한다.
        # --------------------------------------------------------

        "actions": {

            # 무엇을 하는가 -> 어떤 도구로, 어떻게
            #
            # 앞에 있는 것부터 찾으므로 긴 말이 먼저 와야 한다.
            # 활용형을 같이 적는다 — '찌르'는 '찌른다'에 걸리지 않고
            # '당기'는 '당긴다'에 걸리지 않는다. 어간만 적으면 새는 게 많다.
            "verbs": [
                {"words": ["이마를 맞대", "이마를 맞댄", "이마 맞대", "이마 맞댄",
                           "이마를 대", "이마를 붙"],
                 "tool": "forehead", "kind": "tap"},
                {"words": ["잡아당", "당기", "당긴", "당겨"],
                 "tool": "grab", "kind": "pet"},
                {"words": ["쓰다듬", "쓸어", "어루만"],
                 "tool": "hand", "kind": "pet"},
                {"words": ["뽀뽀", "입맞", "입 맞", "키스"],
                 "tool": "lips", "kind": "tap"},
                {"words": ["찌르", "찌른", "찔러", "콕"],
                 "tool": "finger", "kind": "tap"},
                {"words": ["붙잡", "움켜", "잡"],
                 "tool": "grab", "kind": "tap"},
                {"words": ["만지", "만진", "짚"],
                 "tool": "hand", "kind": "tap"},
            ],

            # 어디를 -> 어느 자리
            # 이것도 긴 말이 먼저다. '머리카락'이 '머리'보다 앞에 온다.
            "places": [
                {"words": ["머리카락", "정수리", "머리"], "zone": "head"},
                {"words": ["얼굴", "볼", "뺨", "이마", "코", "입술"], "zone": "face"},
                {"words": ["어깨", "목"], "zone": "shoulder"},
                {"words": ["팔뚝", "팔"], "zone": "arm"},
                {"words": ["손등", "손가락", "손"], "zone": "hand"},
                {"words": ["가슴팍", "가슴"], "zone": "chest"},
                {"words": ["배", "허리"], "zone": "belly"},
                {"words": ["허벅지", "다리", "무릎"], "zone": "leg"},
                {"words": ["발"], "zone": "foot"},
                {"words": ["치마", "스커트"], "zone": "skirt"},
                {"words": ["소매", "옷자락", "옷"], "zone": "top"},
            ],

            # 어디를 만지는지 안 적었을 때 기본으로 정해지는 자리.
            # 자리를 적었으면 이건 쓰지 않는다 —
            # '손등에 뽀뽀한다'는 얼굴이 아니라 손이다.
            "whole": [
                {"words": ["안아", "껴안", "포옹", "안는"],
                 "zone": "shoulder", "tool": "hand", "kind": "pet"},
                {"words": ["뽀뽀", "입맞", "입 맞", "키스"],
                 "zone": "face", "tool": "lips", "kind": "tap"},
                {"words": ["이마를 맞대", "이마 맞대", "이마를 대"],
                 "zone": "face", "tool": "forehead", "kind": "tap"},
            ],

            # 자리는 있는데 무엇을 하는지 안 적었을 때
            "default_tool": "hand",
            "default_kind": "tap",
        },

        # 무엇으로 만질지. 화면에서 우클릭해 고른다.
        # 맨 앞의 것이 기본이다.
        "tools": [

            TouchTool(
                key="hand",
                label="손",
                icon="🖐",
                description="그냥 손으로 만진다",
            ),

            TouchTool(
                key="finger",
                label="손가락",
                icon="👆",
                affinity_scale=0.5,
                expression="surprised",
                motion="nod",
                description="콕 찌른다",
                lines={
                    "default": {
                        "polite": ["아야.", "왜 찌르세요…", "그만 찌르세요."],
                        "casual": ["아야.", "왜 찔러…", "그만 찔러."],
                    },
                    "face": {
                        "polite": ["얼굴은 찌르지 마세요."],
                        "casual": ["얼굴은 찌르지 마."],
                    },
                    "belly": {
                        "polite": ["앗! 거기 찌르면 간지러워요."],
                        "casual": ["앗! 거기 찌르면 간지럽다니까."],
                    },

                    # 두 자리에서는 손가락이 손가락이 아니다.
                    #
                    # 도구 이름을 자리마다 갈아 끼울 수 있게 해 두었다.
                    # 목록에 뜨는 이름은 그대로 '손가락' 이고,
                    # 여기 닿았을 때만 다른 것이 된다.
                    #
                    # 말은 문장이 아니라 소리다. 또박또박 말하면 어색해진다.
                    "pelvis": {
                        "label": "자지",
                        "polite": ["흐윽…", "하아…", "으응…", "앗… 그건…",
                                   "하읏…", "으…", "…읏"],
                        "casual": ["흐윽…", "하아…", "으응…", "앗… 그건…",
                                   "하읏…", "으…", "…읏"],
                    },

                    "mouth": {
                        "label": "자지",

                        # 고개는 움직이지 않는다.
                        # 입에 닿아 있는데 끄덕이면 스스로 밀어내는 꼴이 된다.
                        # 도구가 강제하는 nod 를 여기서만 지운다
                        # (`"motion" in lines` 로 보므로 None 이 곧 '없음'이다).
                        "motion": None,

                        # 놀란 얼굴이 아니라 즐거운 얼굴.
                        "expression": "fun",

                        "polite": ["으읍…", "…읏", "하아…", "으응…", "흐읍…"],
                        "casual": ["으읍…", "…읏", "하아…", "으응…", "흐읍…"],
                    },
                },
            ),

            TouchTool(
                key="grab",
                label="잡기",
                icon="✊",
                affinity_scale=0.8,
                expression="surprised",
                # 동작은 자리에 맡긴다.
                # 도구가 끄덕임을 강제하면 옷을 잡아당기는데 고개를 끄덕인다.
                motion=None,
                grabs_cloth=True,
                description="붙잡는다. 옷도 잡힌다",
                lines={
                    "default": {
                        "polite": ["잡으셨어요…?", "왜 붙잡으세요."],
                        "casual": ["잡은 거야…?", "왜 붙잡아."],
                    },
                    "hand": {
                        "polite": ["손… 잡아 주시는 거예요?", "안 놓을 거예요."],
                        "casual": ["손 잡아 주는 거야?", "안 놓을 거야.",
                                   "이대로 있자."],
                    },
                    "arm": {
                        "polite": ["팔 붙잡으시면 못 가잖아요."],
                        "casual": ["팔 붙잡으면 못 가잖아."],
                    },
                    # 옷을 잡아당길 때는 화난 얼굴이 맞다.
                    # 동작은 두지 않는다 — 옷이 끌려오는 것 자체가 몸짓이고,
                    # 여기에 몸짓을 얹으면 잡힌 채로 딴짓하는 꼴이 된다.
                    "skirt": {
                        "expression": "angry",
                        "motion": None,
                        "polite": [
                            "치마… 잡으셨어요?",
                            "잡아당기지 마세요. 부끄러워요.",
                            "정말… 이러실 거예요?",
                        ],
                        "casual": [
                            "치마… 잡은 거야?",
                            "잡아당기지 마. 부끄럽단 말이야.",
                            "야… 진짜 이럴 거야?",
                            "놓으라니까…",
                        ],
                    },
                    "top": {
                        "expression": "angry",
                        "motion": None,
                        "polite": [
                            "옷 잡아당기지 마세요.",
                            "늘어나요. 놓아 주세요.",
                        ],
                        "casual": [
                            "옷 잡아당기지 마.",
                            "늘어난다니까. 놔.",
                            "소매 그만 잡아…",
                        ],
                    },
                },
            ),

            TouchTool(
                key="forehead",
                label="이마",
                icon="😌",
                allow_bonus=40,
                affinity_scale=1.6,
                expression="fun",
                motion="shy",
                description="이마를 맞댄다",
                lines={
                    "default": {
                        "polite": ["…따뜻하네요.", "이러고 있으면 마음이 놓여요."],
                        "casual": ["…따뜻하다.", "이러고 있으면 마음이 놓여.",
                                   "조금만 더 이러고 있자."],
                    },
                    "face": {
                        "polite": ["이마… 맞대는 거요? 심장 소리 들리겠어요."],
                        "casual": ["이마 맞대는 거… 심장 소리 들리겠는데."],
                    },
                    "head": {
                        "polite": ["머리에… 이러시면 간지러워요."],
                        "casual": ["머리에 이러면 간지럽잖아."],
                    },
                },
                deny={
                    "polite": ["아직… 그렇게까지는 좀."],
                    "casual": ["아직 그렇게까지는 좀…"],
                },
            ),

            TouchTool(
                key="lips",
                label="입술",
                icon="💋",
                allow_bonus=90,
                affinity_scale=2.5,
                expression="fun",
                motion="shy",
                description="입을 맞춘다",
                lines={
                    "default": {
                        "polite": ["…거기에요?", "부끄러우니까 한 번만요."],
                        "casual": ["…거기에?", "부끄러우니까 한 번만.",
                                   "심장 터질 것 같아…"],
                    },
                    "face": {
                        # 눈을 감겠다고 해 놓고 쑥스러워하기 동작이 나오면
                        # 말과 몸이 어긋난다. 여기서는 정말로 눈을 감는다.
                        "expression": "eyes_closed",
                        "motion": None,
                        "polite": [
                            "…눈 감을게요.",
                            "한 번만… 더요.",
                            {"text": "이러면 제가 못 견뎌요.",
                             "expression": "fun"},
                        ],
                        "casual": [
                            "…눈 감을게.",
                            "한 번만 더…",
                            {"text": "이러면 나 진짜 못 참아.",
                             "expression": "fun"},
                        ],
                    },
                    "hand": {
                        "polite": ["손등에… 그런 건 어디서 배우셨어요."],
                        "casual": ["손등에… 그런 건 어디서 배웠어."],
                    },
                    "head": {
                        "polite": ["정수리에… 그러시면 반칙이에요."],
                        "casual": ["정수리에 그러는 건 반칙이야."],
                    },
                },
                deny={
                    "polite": ["안 돼요. 아직 그럴 사이 아니잖아요."],
                    "casual": ["안 돼. 아직 그럴 사이 아니잖아."],
                },
            ),
        ],

        "zones": [

            # 골반 가운데 아래.
            #
            # 이름은 있지만 내보이지는 않는다(hidden). 만질 수 있는 곳
            # 목록에도, 대화 기록에도 뜨지 않는다.
            #
            # 말은 문장이 아니라 소리다. 여기서 또박또박 말하면 오히려
            # 어색해진다. 얼굴은 절정 표정 중 하나가 그때그때 나온다.
            #
            # 친밀도 숫자로는 조건을 못 적는다. 광기와 얀데레 사이에는
            # 어떤 값도 없기 때문이다. 그래서 단계 이름으로 적는다.
            #
            # 그 두 단계가 아닐 때 건드리면 몇 점 깎이는 정도로 끝나지 않는다.
            # 냉랭함(원수 바로 전 단계)까지 통째로 떨어진다.
            TouchZone(
                key="pelvis",
                label="보지",
                bones=[],            # 본 이름으로는 안 잡힌다. hips_split 이 정한다.
                hidden=True,
                random_peak=True,
                allow_stages=["frenzy", "yandere"],
                # 지금까지 가장 높은 호감 점수가 3 이다. 그 두 배.
                tap={
                    "affinity": 6,
                    "lines": {
                        "polite": ["앗…", "흐읏…", "하아…", "으응…",
                                   "…읏", "하…"],
                        "casual": ["앗…", "흐읏…", "하아…", "으응…",
                                   "…읏", "하…"],
                    },
                },
                pet={
                    "affinity": 6,
                    "lines": {
                        "polite": ["하아…", "으응…", "흐응…", "앗… 잠깐…",
                                   "하읏…", "으…", "…하아"],
                        "casual": ["하아…", "으응…", "흐응…", "앗… 잠깐…",
                                   "하읏…", "으…", "…하아"],
                    },
                },
                deny={
                    "expression": "angry",
                    "motion": "turn_back",
                    "affinity_to_stage": "cold",
                },
            ),

            TouchZone(
                key="head",
                label="머리",
                bones=["head"],
                tap={
                    "expression": "fluster", "motion": "nod", "affinity": 1,
                    "lines": {
                        "polite": ["어… 왜 그러세요?", "머리는… 좀 부끄러운데요."],
                        "casual": ["어? 왜…", "머리 만지는 거야?"],
                    },
                },
                pet={
                    "expression": ["joy", "fun"], "motion": "nod", "affinity": 3,
                    "lines": {
                        "polite": [
                            "아… 그렇게 하시면…",
                            "…나쁘지는 않아요.",
                            "계속… 해주셔도 돼요.",
                            "이러면 제가 좀… 곤란한데요.",
                        ],
                        "casual": [
                            "우… 갑자기 왜…",
                            "…싫지는 않아.",
                            "더 해줘도 되는데.",
                            "이러면 나 녹아버려…",
                            "머리 만지는 거 좋아하는구나?",
                        ],
                    },
                },
            ),

            TouchZone(
                key="face",
                label="얼굴",
                bones=[],
                allow_from=40,
                tap={
                    "expression": "surprised", "motion": "shy", "affinity": 2,
                    "lines": {
                        "polite": ["얼굴은… 좀…", "가까이 오면 부끄러워요."],
                        "casual": ["얼굴은 반칙이야…", "그렇게 보면 부끄럽잖아."],
                    },
                },
                pet={
                    "expression": ["joy", "fun"], "motion": "nod", "affinity": 3,
                    "lines": {
                        "polite": ["…따뜻하네요.", "이러시면 얼굴이 뜨거워져요."],
                        "casual": [
                            "손 따뜻하다…",
                            "얼굴 만지는 거… 반칙이라니까.",
                            "계속 보고 있으면 나 못 견뎌.",
                        ],
                    },
                },
                deny={
                    "expression": "angry", "motion": "nod", "affinity": -4,
                    "lines": {
                        "polite": ["얼굴은 안 돼요. 아직 그럴 사이 아니잖아요."],
                        "casual": ["얼굴은 아직 안 돼."],
                    },
                },
            ),

            # 입.
            #
            # 얼굴 안에서 다시 갈라낸 자리다. 머리 본 하나가 정수리부터
            # 턱까지 다 걸치고 있어서 닿은 좌표로 나눈다.
            TouchZone(
                key="mouth",
                label="입",
                bones=[],            # head_split 이 정한다
                allow_from=40,
                tap={
                    "expression": "fluster",
                    "expression_warm": ["joy", "fun"],
                    "motion": "nod",
                    "affinity": 1,
                    "lines": {
                        "polite": ["읏…", "입은… 왜요.", "간지러워요."],
                        "casual": ["읏…", "입은 왜…", "간지러워."],
                    },
                },
                pet={
                    "expression": "surprised",
                    "expression_warm": ["joy", "fun"],
                    "motion": "shy",
                    "affinity": 2,
                    "lines": {
                        "polite": ["하…", "그렇게 만지시면…", "…계속 하실 거예요?"],
                        "casual": ["하…", "그렇게 만지면…", "…계속 할 거야?"],
                    },
                },

                # 눈을 감고 기다리는 중에 입술이 닿았을 때.
                #
                # 뽀뽀와 다른 것으로 친다. 뽀뽀는 이쪽에서 하는 것이고,
                # 이것은 서로 기다렸다 하는 것이다. 그래서 놀라지 않는다.
                # 몸짓도 없다 — 입을 맞추는 중에 쑥스러워하며 얼굴을
                # 가리면 그 손이 사이를 가른다.
                kiss={
                    "expression": "eyes_closed",
                    "expression_then": "fun",
                    "motion": None,
                    # 입술 도구가 2.5 배를 곱하므로 실제로는 12점 오른다.
                    # 한 번 만지는 것 중에는 가장 크되, 고백(+30)보다는 작다.
                    "affinity": 5,
                    "lines": {
                        "polite": ["…읏", "하아…", "…더요.", "숨… 못 쉬겠어요.",
                                   "…이러면 안 놓아 드려요."],
                        "casual": ["…읏", "하아…", "…더.", "숨… 못 쉬겠어.",
                                   "…이러면 안 놓아줄 거야."],
                    },
                },
                deny={
                    "expression": "surprised",
                    "motion": "cover",
                    "affinity": -3,
                    "lines": {
                        "polite": ["입은 안 돼요."],
                        "casual": ["입은 안 돼."],
                    },
                },
            ),

            TouchZone(
                key="shoulder",
                label="어깨",
                bones=["leftShoulder", "rightShoulder", "upperChest", "neck"],
                tap={
                    "expression": "neutral", "motion": "nod", "affinity": 1,
                    "lines": {
                        "polite": ["네, 듣고 있어요.", "왜 부르셨어요?"],
                        "casual": ["응? 왜 불러.", "어깨는 왜."],
                    },
                },
                pet={
                    "expression": "fun", "motion": "nod", "affinity": 2,
                    "lines": {
                        "polite": ["어깨… 뭉쳤나 봐요.", "간지러워요."],
                        "casual": ["간지러워…", "어깨 주물러 주는 거야?"],
                    },
                },
            ),

            TouchZone(
                key="arm",
                label="팔",
                bones=["leftUpperArm", "rightUpperArm",
                       "leftLowerArm", "rightLowerArm"],
                tap={
                    "expression": "fluster",
                    "expression_warm": ["joy", "fun"], "motion": "nod", "affinity": 1,
                    "lines": {
                        "polite": ["팔은 왜요?", "네?"],
                        "casual": ["팔은 왜?", "응?"],
                    },
                },
                pet={
                    "expression": "surprised",
                    "expression_warm": ["joy", "fun"], "motion": "cover", "motion_warm": "nod", "affinity": 2,
                    "lines": {
                        "polite": ["간지럽다니까요.", "그만… 간지러워요."],
                        "casual": ["간지럽다니까.", "야, 간지러워."],
                    },
                },
            ),

            TouchZone(
                key="hand",
                label="손",
                bones=["leftHand", "rightHand",
                       "leftThumbProximal", "rightThumbProximal",
                       "leftIndexProximal", "rightIndexProximal",
                       "leftMiddleProximal", "rightMiddleProximal",
                       "leftRingProximal", "rightRingProximal",
                       "leftLittleProximal", "rightLittleProximal"],
                allow_from=-20,
                tap={
                    "expression": "fluster",
                    # 놀란 뒤 곧 좋아하는 얼굴이 된다.
                    # 손을 잡혔다고 얼굴을 가리지는 않는다.
                    "expression_then": "fun", "motion": None, "affinity": 2,
                    "lines": {
                        "polite": ["손… 잡으시는 거예요?", "어, 손…"],
                        "casual": ["손… 잡는 거야?", "어…"],
                    },
                },
                pet={
                    "expression": ["joy", "fun"], "motion": "nod", "affinity": 3,
                    "lines": {
                        "polite": ["손 따뜻하네요.", "이대로… 좀 더 있어도 돼요?"],
                        "casual": [
                            "손 따뜻하다.",
                            "이대로 좀만 더 있자.",
                            "놓지 마.",
                        ],
                    },
                },
                deny={
                    "expression": "angry", "motion": "nod", "affinity": -2,
                    "lines": {
                        "polite": ["손은… 아직 좀."],
                        "casual": ["손은 아직."],
                    },
                },
            ),

            TouchZone(
                key="chest",
                label="가슴팍",
                bones=["chest"],
                allow_from=160,
                tap={
                    "expression": "surprised",
                    "expression_warm": ["joy", "fun"], "motion": "cover", "motion_warm": "nod", "affinity": 1,
                    "lines": {
                        "polite": ["…심장 소리 들려요?", "거긴…"],
                        "casual": ["…심장 뛰는 거 들려?", "거긴…"],
                    },
                },
                pet={
                    "expression": "surprised",
                    "expression_warm": ["joy", "fun"], "motion": "cover", "motion_warm": "nod", "affinity": 2,
                    "lines": {
                        "polite": ["여기, 계속 뛰고 있어요. 당신 때문에."],
                        "casual": ["여기 계속 뛰어. 너 때문에."],
                    },
                },
                deny={
                    "expression": "angry", "motion": "nod", "affinity": -8,
                    "lines": {
                        "polite": ["거긴 안 돼요. 손 치워 주세요."],
                        "casual": ["거긴 안 돼. 손 치워."],
                    },
                },
            ),

            TouchZone(
                key="belly",
                label="배",
                bones=["spine", "hips"],
                allow_from=120,
                tap={
                    "expression": "surprised",
                    "expression_warm": ["joy", "fun"], "motion": "cover", "motion_warm": "nod", "affinity": 0,
                    "lines": {
                        "polite": ["아, 간지러워요."],
                        "casual": ["아, 간지러워."],
                    },
                },
                pet={
                    "expression": "surprised",
                    "expression_warm": ["joy", "fun"], "motion": "cover", "motion_warm": "nod", "affinity": 1,
                    "lines": {
                        "polite": ["그만… 웃음 나와요.", "간지럽다고요."],
                        "casual": ["그만, 웃음 나와.", "간지럽다니까."],
                    },
                },
                deny={
                    "expression": "angry", "motion": "nod", "affinity": -6,
                    "lines": {
                        "polite": ["거긴 좀 아니에요."],
                        "casual": ["거긴 좀 아니지."],
                    },
                },
            ),

            TouchZone(
                key="leg",
                label="다리",
                bones=["leftUpperLeg", "rightUpperLeg",
                       "leftLowerLeg", "rightLowerLeg"],
                allow_from=190,
                tap={
                    "expression": "surprised",
                    "expression_warm": ["joy", "fun"], "motion": "cover", "motion_warm": "nod", "affinity": 0,
                    "lines": {
                        "polite": ["…거기까지 오시는군요."],
                        "casual": ["…거기까지 오네."],
                    },
                },
                pet={
                    "expression": "surprised",
                    "expression_warm": ["joy", "fun"], "motion": "cover", "motion_warm": "nod", "affinity": 1,
                    "lines": {
                        "polite": ["부끄러우니까… 조금만요."],
                        "casual": ["부끄러우니까 조금만."],
                    },
                },
                deny={
                    "expression": "angry", "motion": "nod", "affinity": -8,
                    "lines": {
                        "polite": ["다리는 안 돼요."],
                        "casual": ["다리는 안 돼."],
                    },
                },
            ),

            # 옷 — 본이 아니라 재질로 갈린 자리다.
            # 판정구가 zone 을 직접 들고 오며, 잡는 도구로만 닿는다.

            TouchZone(
                key="top",
                label="윗옷",
                bones=[],
                cloth=True,
                allow_from=40,
                tap={
                    "expression": "fluster",
                    "expression_warm": ["joy", "fun"],
                    # 광기부터다. 만지면 화내던 자리라
                    # 다른 곳(80)보다 훨씬 깊어져야 웃는다.
                    "warm_from": 230, "motion": "nod", "affinity": 0,
                    "lines": {
                        "polite": ["옷은 왜 잡으세요?"],
                        "casual": ["옷은 왜 잡아?"],
                    },
                },
                pet={
                    "expression": "angry",
                    "expression_warm": ["joy", "fun"],
                    # 광기부터다. 만지면 화내던 자리라
                    # 다른 곳(80)보다 훨씬 깊어져야 웃는다.
                    "warm_from": 230, "motion": "nod", "affinity": -1,
                    "lines": {
                        "polite": ["늘어난다니까요. 그만 잡아당기세요."],
                        "casual": ["늘어난다니까. 그만 잡아당겨."],
                    },
                },
                deny={
                    "expression": "angry", "motion": "nod", "affinity": -4,
                    "lines": {
                        "polite": ["옷 놓아 주세요. 그럴 사이 아니잖아요."],
                        "casual": ["옷 놔. 그럴 사이 아니잖아."],
                    },
                },
            ),

            TouchZone(
                key="skirt",
                label="치마",
                bones=[],
                cloth=True,
                allow_from=160,
                tap={
                    "expression": "surprised",
                    "expression_warm": ["joy", "fun"], "motion": "cover", "motion_warm": "nod", "affinity": 0,
                    "lines": {
                        "polite": ["치마는… 잡지 마세요."],
                        "casual": ["치마는… 잡지 마."],
                    },
                },
                pet={
                    "expression": "surprised",
                    "expression_warm": ["joy", "fun"], "motion": "cover", "motion_warm": "nod", "affinity": -1,
                    "lines": {
                        "polite": ["부끄러우니까 그만하세요. 정말로요."],
                        "casual": ["부끄러우니까 그만해. 진짜로."],
                    },
                },
                deny={
                    "expression": "angry", "motion": "nod", "affinity": -10,
                    "lines": {
                        "polite": ["손 놓으세요. 지금 뭐 하시는 거예요."],
                        "casual": ["손 놔. 지금 뭐 하는 거야."],
                    },
                },
            ),

            TouchZone(
                key="foot",
                label="발",
                bones=["leftFoot", "rightFoot", "leftToes", "rightToes"],
                tap={
                    "expression": "angry",
                    "expression_warm": ["joy", "fun"],
                    # 광기부터다. 만지면 화내던 자리라
                    # 다른 곳(80)보다 훨씬 깊어져야 웃는다.
                    "warm_from": 230, "motion": "nod", "affinity": -1,
                    "lines": {
                        "polite": ["발은 왜 만지세요…"],
                        "casual": ["발은 왜 만져…"],
                    },
                },
                pet={
                    "expression": "angry",
                    "expression_warm": ["joy", "fun"],
                    # 광기부터다. 만지면 화내던 자리라
                    # 다른 곳(80)보다 훨씬 깊어져야 웃는다.
                    "warm_from": 230, "motion": "nod", "affinity": -2,
                    "lines": {
                        "polite": ["진짜 발은 아니에요."],
                        "casual": ["진짜 발은 아니야."],
                    },
                },
            ),
        ],
    },
)


# 프로젝트 어디서든 같은 개체를 가리키도록
AVATAR = DIA

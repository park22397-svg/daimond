# -*- coding: utf-8 -*-
"""끝말잇기 — 규칙과 다이아가 낼 낱말.

체스와 같은 자리다. **규칙은 서버가 쥔다.** 모델에게 맡기면 안 된다 —
gemma3:4b 로 재 봤을 때 끝말잇기 0/3 이었다. 없는 낱말을 지어내고,
끝 글자를 안 맞추고, 이미 쓴 낱말을 또 낸다. 무슨 말을 할지는 개체가
정하고, 이길지 질지는 여기가 정한다.

낱말은 `words_ko.txt` 에 있다. open-korean-text(Apache 2.0)의 명사
목록에서 한글 2~6자만 추린 것이다. 25,825개.

  https://github.com/open-korean-text/open-korean-text

두음법칙을 받아 준다. '남녀' 뒤에 '여자' 가 되는 그것이다. 안 받아
주면 사람이 아는 규칙과 달라서 억울해진다.
"""
import os
import random
import re

HERE = os.path.dirname(os.path.abspath(__file__))
WORDS_FILE = os.path.join(HERE, "words_ko.txt")

HANGUL = re.compile(r"^[가-힣]{2,6}$")

# ============================================================
# 낱말 — 한 번만 읽어 두고 쓴다
#
# 2만 5천 개를 매번 읽으면 한 수에 0.1초씩 든다.
# 첫 글자로 미리 갈라 두면 낼 낱말을 바로 찾는다.
# ============================================================

_WORDS = None          # set
_BY_HEAD = None        # {첫 글자: [낱말...]}
_HEADS = None          # 이어 갈 수 있는 첫 글자들


def _load():
    global _WORDS, _BY_HEAD, _HEADS

    if _WORDS is not None:
        return

    words = set()

    try:
        with open(WORDS_FILE, encoding="utf-8") as f:
            for line in f:
                w = line.strip()
                if HANGUL.match(w):
                    words.add(w)
    except OSError as e:
        print(f"[끝말잇기] 낱말 파일을 못 읽었습니다: {e}")

    by_head = {}

    for w in words:
        by_head.setdefault(w[0], []).append(w)

    for k in by_head:
        by_head[k].sort()

    _WORDS = words
    _BY_HEAD = by_head
    _HEADS = set(by_head)


def count():
    _load()
    return len(_WORDS)


# ============================================================
# 두음법칙
#
# 끝 글자가 ㄹ·ㄴ 으로 시작하면 다른 소리로도 이을 수 있다.
#
#   력 -> 역     (ㄹ + ㅕ  ->  ㅇ)
#   로 -> 노     (ㄹ + ㅗ  ->  ㄴ)
#   녀 -> 여     (ㄴ + ㅕ  ->  ㅇ)
#
# 사람이 아는 규칙이 이것이라 안 받아 주면 억울해한다.
# ============================================================

_CHO = list("ㄱㄲㄴㄷㄸㄹㅁㅂㅃㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎ")
_JUNG = list("ㅏㅐㅑㅒㅓㅔㅕㅖㅗㅘㅙㅚㅛㅜㅝㅞㅟㅠㅡㅢㅣ")

# ㄹ·ㄴ 이 ㅇ 으로 바뀌는 모음 (야 여 요 유 이 얘 예)
_TO_IEUNG = set("ㅑㅕㅛㅠㅣㅒㅖ")


def _split(ch):
    """한 글자를 초성·중성·종성 번호로."""
    code = ord(ch) - 0xAC00

    if code < 0 or code > 11171:
        return None

    return code // 588, (code % 588) // 28, code % 28


def _join(cho, jung, jong):
    return chr(0xAC00 + cho * 588 + jung * 28 + jong)


def heads_for(syllable):
    """이 글자로 이을 때 쓸 수 있는 첫 글자들. 자기 자신을 포함한다."""
    out = [syllable]

    parts = _split(syllable)

    if not parts:
        return out

    cho, jung, jong = parts
    c = _CHO[cho]
    v = _JUNG[jung]

    if c == "ㄹ":
        want = "ㅇ" if v in _TO_IEUNG else "ㄴ"
        out.append(_join(_CHO.index(want), jung, jong))

    elif c == "ㄴ" and v in _TO_IEUNG:
        out.append(_join(_CHO.index("ㅇ"), jung, jong))

    return out


# ============================================================
# 판정
# ============================================================

def is_word(w):
    _load()
    return w in _WORDS


def connects(prev, word):
    """앞말 뒤에 이 낱말을 놓을 수 있는가."""
    if not prev:
        return True

    return word[0] in heads_for(prev[-1])


def judge(prev, word, used):
    """사람이 낸 낱말을 본다.

    반환: (ok, why)  — why 는 안 되는 까닭의 열쇠말
    """
    w = str(word or "").strip()

    if not HANGUL.match(w):
        return False, "모양"

    if prev and not connects(prev, w):
        return False, "안이어짐"

    if w in used:
        return False, "이미썼음"

    if not is_word(w):
        return False, "없는말"

    return True, None


# ============================================================
# 다이아가 낼 낱말
#
# 세기는 '얼마나 좋은 낱말을 고르는가' 로 낸다.
#
#   무름  이어 가기 쉬운 낱말만 고른다. 한방은 절대 안 쓴다.
#   보통  아무거나 고른다.
#   매움  상대가 이어 가기 어려운 낱말부터 고른다. 한방도 쓴다.
#
# 낼 것이 없으면 진다. 그것이 이 놀이의 끝이다.
# ============================================================

LEVELS = {
    "soft": {"label": "무름", "hard": 0.0, "avoid_dead": True},
    "normal": {"label": "보통", "hard": 0.35, "avoid_dead": True},
    "sharp": {"label": "매움", "hard": 1.0, "avoid_dead": False},
}


def _candidates(prev, used):
    """지금 낼 수 있는 낱말 전부."""
    _load()

    if not prev:
        # 처음 시작할 때. 이어 갈 데가 넉넉한 낱말로 연다.
        pool = [w for w in _WORDS
                if w not in used and len(_BY_HEAD.get(w[-1], [])) >= 30]
        return pool or [w for w in _WORDS if w not in used]

    out = []

    for head in heads_for(prev[-1]):
        for w in _BY_HEAD.get(head, []):
            if w not in used:
                out.append(w)

    return out


def _room(word, used):
    """이 낱말을 내면 상대가 고를 수 있는 낱말이 몇 개나 되는가."""
    _load()

    n = 0

    for head in heads_for(word[-1]):
        for w in _BY_HEAD.get(head, []):
            if w not in used and w != word:
                n += 1

    return n


def pick(prev, used, level="normal", rng=None):
    """다이아가 낼 낱말. 낼 것이 없으면 None (지는 것이다).

    상대가 고를 자리가 몇이나 남는지(_room)로 고른다.
    매울수록 좁은 쪽을, 무를수록 넓은 쪽을 고른다.
    """
    rng = rng or random

    conf = LEVELS.get(level) or LEVELS["normal"]
    pool = _candidates(prev, used)

    if not pool:
        return None

    # 다 재면 느리다. 무작위로 추려 그 안에서 고른다.
    #
    # 2만 개를 전부 재면 한 수에 몇 초가 든다. 200개만 봐도
    # 사람이 느끼기에는 충분히 잘 둔다.
    sample = pool if len(pool) <= 200 else rng.sample(pool, 200)

    scored = [(w, _room(w, used)) for w in sample]

    # 한방(상대가 이어 갈 수 없는 낱말)
    dead = [w for w, r in scored if r == 0]

    if dead and not conf["avoid_dead"] and rng.random() < conf["hard"]:
        return rng.choice(dead)

    alive = [(w, r) for w, r in scored if r > 0]

    if not alive:
        # 한방밖에 없다. 무른 다이아라도 낼 것이 그것뿐이면 낸다.
        return rng.choice(dead) if dead else rng.choice(sample)

    alive.sort(key=lambda x: x[1])

    if conf["hard"] >= 1.0:
        band = alive[:max(1, len(alive) // 10)]          # 가장 좁은 쪽
    elif rng.random() < conf["hard"]:
        band = alive[:max(1, len(alive) // 3)]
    else:
        band = alive[max(0, len(alive) * 2 // 3):]       # 넉넉한 쪽

    return rng.choice(band)[0]


def can_continue(prev, used):
    """이 자리에서 이어 갈 낱말이 하나라도 있는가."""
    return bool(_candidates(prev, used))

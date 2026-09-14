# -*- coding: utf-8 -*-
"""할리갈리 — 규칙과 다이아의 반응 속도.

체스·오목·끝말잇기와 같은 자리다. 규칙은 서버가 쥐고, 무슨 말을
할지는 개체(avatar.py)가 정한다.

## 이 놀이는 다른 놀이와 다르다

체스는 '어디에 둘까' 가 세기지만, 할리갈리는 **누가 먼저 손을 대는가**
가 전부다. 그래서 다이아의 세기는 두는 눈이 아니라 **반응 시간**으로
낸다.

너무 빠르게 두면 사람이 영영 못 이긴다. 기계는 0.001초에 누를 수
있으니 그대로 두면 놀이가 안 된다. 사람이 눈으로 보고 세고 손을
움직이는 데 0.8~1.5초가 드는 것을 감안해서 잡았다.

가끔 틀리게 누르기도 한다. 한 번도 안 틀리는 상대는 사람 같지 않고,
사람에게 벌칙으로 카드를 줄 기회도 생긴다.

## 패

과일 넷(바나나·라임·딸기·자두), 각 과일마다

  1개짜리 5장 · 2개 3장 · 3개 3장 · 4개 2장 · 5개 1장  = 14장

넷을 합쳐 56장. 실제 할리갈리와 같은 구성이다.

## 언제 종을 치는가

펼쳐진 패의 **맨 위 카드들만** 센다. 한 과일의 수가 **정확히 다섯**
이면 종을 칠 때다. 여섯이나 넷은 아니다.
"""
import random

FRUITS = ("banana", "lime", "berry", "plum")

FRUIT_KO = {
    "banana": "바나나",
    "lime": "라임",
    "berry": "딸기",
    "plum": "자두",
}

# 과일 하나당 몇 장씩. 실제 할리갈리와 같다.
COUNTS = {1: 5, 2: 3, 3: 3, 4: 2, 5: 1}

BELL = 5


def new_deck(rng=None):
    """56장을 섞어서."""
    rng = rng or random

    deck = []

    for f in FRUITS:
        for n, many in COUNTS.items():
            deck += [{"fruit": f, "n": n}] * many

    deck = [dict(c) for c in deck]
    rng.shuffle(deck)

    return deck


def new_game(rng=None, level="normal"):
    """패를 반씩 나눠 갖는다."""
    rng = rng or random
    deck = new_deck(rng)
    half = len(deck) // 2

    return {
        "on": True,
        "level": level,
        # 손에 든 패 (뒤집어 둔 것)
        "hand": {"you": deck[:half], "dia": deck[half:]},
        # 펼쳐 놓은 패
        "open": {"you": [], "dia": []},
        # 누가 뒤집을 차례인가
        "turn": "you",
        # 종 칠 때인가. 뒤집은 뒤에 정해진다.
        "ring": False,
        # 다이아가 종을 치기까지 걸릴 시간(ms). 뒤집을 때마다 새로 뽑는다.
        "dia_ms": None,
        # 다이아가 잘못 칠 것인가
        "dia_wrong": False,
        "log": [],
    }


# ============================================================
# 뒤집기
# ============================================================

def tops(game):
    """펼쳐 놓은 패의 맨 위 카드들."""
    out = []

    for who in ("you", "dia"):
        pile = game["open"].get(who) or []
        if pile:
            out.append(pile[-1])

    return out


def fruit_sums(game):
    """지금 보이는 과일별 개수."""
    sums = {}

    for c in tops(game):
        sums[c["fruit"]] = sums.get(c["fruit"], 0) + c["n"]

    return sums


def should_ring(game):
    """종을 칠 때인가. 그렇다면 그 과일도 같이."""
    for f, n in fruit_sums(game).items():
        if n == BELL:
            return f

    return None


def flip(game, who):
    """한 장 뒤집는다. 뒤집을 것이 없으면 False."""
    hand = game["hand"][who]

    if not hand:
        return False

    card = hand.pop(0)
    game["open"][who].append(card)
    game["turn"] = "dia" if who == "you" else "you"

    return True


# ============================================================
# 종
# ============================================================

def take_pile(game, who):
    """펼쳐진 패를 전부 가져가 손패 아래에 넣는다."""
    got = 0

    for side in ("you", "dia"):
        pile = game["open"][side]
        got += len(pile)
        game["hand"][who] += pile
        game["open"][side] = []

    return got


def penalty(game, who):
    """잘못 쳤다. 상대에게 한 장 준다."""
    other = "dia" if who == "you" else "you"
    hand = game["hand"][who]

    if not hand:
        return 0

    game["hand"][other].append(hand.pop(0))

    return 1


def winner(game):
    """이긴 쪽. 아직이면 None.

    손패도 없고 뒤집을 것도 없으면 진다. 펼쳐 놓은 것은 제 것이 아니다.
    """
    for who in ("you", "dia"):
        if not game["hand"][who] and not game["open"][who]:
            return "dia" if who == "you" else "you"

    return None


# ============================================================
# 다이아의 반응
#
# 세기를 두는 눈이 아니라 **얼마나 빨리 손을 대는가** 로 낸다.
# 기계는 0.001초에 누를 수 있어서 그대로 두면 놀이가 안 된다.
# ============================================================

LEVELS = {
    "easy": {
        "label": "느긋",
        "ms": 1500, "spread": 500,
        # 이 확률로 아닌데 친다 — 사람에게 카드를 주게 된다
        "wrong": 0.18,
        # 이 확률로 아예 못 보고 지나간다
        "miss": 0.25,
    },
    "normal": {
        "label": "보통",
        "ms": 950, "spread": 300,
        "wrong": 0.08,
        "miss": 0.08,
    },
    "hard": {
        "label": "빠름",
        "ms": 600, "spread": 150,
        "wrong": 0.02,
        "miss": 0.0,
    },
}


def roll_reaction(level="normal", mercy=0.0, rng=None):
    """다이아가 종을 치기까지 걸릴 시간(ms)과, 잘못 칠 것인가.

    ms 가 None 이면 이번에는 아예 안 친다(못 봤다).

    mercy 는 사이가 깊을 때 일부러 늦게 치는 것이다. 봐주는 티가
    안 나게 시간만 늘린다 — 아예 안 치면 티가 난다.
    """
    rng = rng or random

    conf = LEVELS.get(level) or LEVELS["normal"]

    if rng.random() < conf["miss"]:
        return None, False

    ms = conf["ms"] + rng.randint(-conf["spread"], conf["spread"])

    if mercy and rng.random() < mercy:
        ms = int(ms * rng.uniform(1.4, 2.0))

    return max(120, ms), (rng.random() < conf["wrong"])


def wrong_ring_delay(level="normal", rng=None):
    """아닌데 칠 때 걸리는 시간. 제대로 칠 때보다 조금 늦다."""
    rng = rng or random

    conf = LEVELS.get(level) or LEVELS["normal"]

    return conf["ms"] + rng.randint(0, conf["spread"] * 2)


# ============================================================
# 화면에 보낼 한 벌
# ============================================================

def view(game):
    return {
        "on": bool(game.get("on")),
        "turn": game.get("turn"),
        "ring": bool(game.get("ring")),
        "hand": {k: len(v) for k, v in game["hand"].items()},
        "open": {
            k: (v[-1] if v else None) for k, v in game["open"].items()
        },
        "pile": {k: len(v) for k, v in game["open"].items()},
        "sums": fruit_sums(game),
        "fruits": FRUIT_KO,
        "level": game.get("level", "normal"),
    }

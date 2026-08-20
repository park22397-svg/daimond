# who.py
# diamondAI - 지금 누가 말하고 있는가
#
# 기억 파일을 사람마다 가르려면, 기억을 읽고 쓰는 자리에서
# '지금 누구의 기억인가' 를 알아야 한다.
#
# 그 값을 함수 인자로 넘기려면 memory_manager 의 함수 스무 개와
# 그것을 부르는 ai_brain·main 의 자리 전부를 고쳐야 한다.
# 대신 여기 한 곳에 적어 두고 필요한 데서 꺼내 쓴다.
#
# 스레드마다 따로 둔다(threading.local).
# Flask 는 요청 하나를 스레드 하나가 맡으므로, 이렇게 두면
# 두 사람이 같은 순간에 들어와도 서로의 기억을 건드리지 않는다.
# 전역 변수 하나로 두면 섞인다 — 그것이 이 파일이 있는 이유다.
#
# memory_manager 도 main 도 이 파일을 가져다 쓰지만
# 이 파일은 아무것도 가져오지 않는다. 그래서 순환이 생기지 않는다.

import threading


# 로그인하지 않은 사람의 자리.
#
# 검사 스크립트(_verify_*.py)처럼 웹을 거치지 않고 memory_manager 를
# 부르는 것들도 있다. 그때 터지지 않고 이 자리를 쓴다.
GUEST = "_guest"


_local = threading.local()


def current():
    """지금 이 스레드가 맡은 사람의 기억 자리. 정해진 것이 없으면 손님."""

    return getattr(_local, "slot", None) or GUEST


def set_current(slot):
    """이 스레드가 맡은 사람을 정한다.

    Flask 의 before_request 에서 요청마다 부른다.
    **반드시 요청마다 부를 것** — 스레드는 재사용되므로,
    안 부르면 앞사람의 자리가 그대로 남아 남의 기억을 쓰게 된다.
    """

    _local.slot = str(slot or "").strip() or GUEST

    return _local.slot


def clear():
    """손님으로 되돌린다."""

    _local.slot = GUEST

    return GUEST

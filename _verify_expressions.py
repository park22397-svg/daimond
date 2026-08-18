# _verify_expressions.py
# 표정이 그대로인지 본다.
#
# 표정 수치는 사람이 눈으로 보고 하나하나 맞춘 값이다.
# 계산으로 나온 것이 아니라서, 한 번 어긋나면 되돌릴 근거가 없다.
# 그래서 잠근 날의 값을 떠 두고(_expressions_locked.json) 여기서 대조한다.
#
# 표정을 새로 만드는 것은 괜찮다. 있던 것이 바뀌는 것만 잡는다.
#
#   python _verify_expressions.py          대조만 한다
#   python _verify_expressions.py --잠금    지금 값으로 다시 떠 둔다

import json
import os
import sys

sys.path.insert(0, ".")

from avatar import AVATAR

LOCK = "_expressions_locked.json"

FIELDS = [
    "label", "blendshapes", "fallback_blendshapes", "morphs",
    "auto_detect", "auto_weight", "hold_ms", "source", "is_reply_emotion",
]


def snapshot():
    out = {}
    for e in AVATAR.expressions:
        out[e.key] = {f: getattr(e, f) for f in FIELDS}
    return out


def save(now):
    with open(LOCK, "w", encoding="utf-8") as f:
        json.dump(
            {
                "잠근_날": "2026-08-18",
                "왜": ("사람이 눈으로 보고 하나하나 맞춘 값이다. "
                       "다시 계산하거나 어림잡아 바꾸면 안 된다."),
                "표정_수": len(now),
                "표정": now,
            },
            f, ensure_ascii=False, indent=2,
        )


def main():
    now = snapshot()

    if "--잠금" in sys.argv or "--lock" in sys.argv:
        save(now)
        print(f"지금 값으로 다시 떠 두었다. 표정 {len(now)}개.")
        return 0

    if not os.path.exists(LOCK):
        save(now)
        print(f"떠 둔 것이 없어서 지금 값으로 만들었다. 표정 {len(now)}개.")
        return 0

    with open(LOCK, encoding="utf-8") as f:
        locked = json.load(f)["표정"]

    print("=" * 66)
    print("표정이 그대로인가")
    print("=" * 66)

    changed = []
    gone = []

    for key, was in locked.items():
        if key not in now:
            gone.append((key, was.get("label")))
            continue

        for f in FIELDS:
            a, b = was.get(f), now[key].get(f)
            if a != b:
                changed.append((was.get("label"), key, f, a, b))

    added = [(k, v["label"]) for k, v in now.items() if k not in locked]

    if added:
        print(f"\n새로 생긴 표정 {len(added)}개 (문제 아님)")
        for k, lab in added:
            print(f"   + {lab} ({k})")

    if gone:
        print(f"\n사라진 표정 {len(gone)}개")
        for k, lab in gone:
            print(f"   - {lab} ({k})")

    if changed:
        print(f"\n바뀐 값 {len(changed)}곳")
        for lab, key, f, a, b in changed:
            print(f"   ! {lab} ({key}) 의 {f}")
            print(f"       잠글 때 {a}")
            print(f"       지금    {b}")

    print()
    print("=" * 66)
    if changed or gone:
        print("표정이 달라졌다. 뜻한 것이 아니면 되돌려라.")
        print("일부러 바꾼 것이면  python _verify_expressions.py --잠금")
        print("=" * 66)
        return 1

    print(f"표정 {len(locked)}개 모두 잠근 날 그대로다.")
    print("=" * 66)
    return 0


if __name__ == "__main__":
    sys.exit(main())

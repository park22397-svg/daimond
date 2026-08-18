# _verify_pairs.py
# 행동과 표정이 짝지어진 자리를 전부 모아 보여준다.
#
# 한 행동에 표정이 하나만 붙어야 한다. 두 곳에서 서로 다른 표정을
# 걸면 나중에 건 쪽이 이기는데, 그게 뜻한 바가 아닐 때가 있다.
# (자리는 놀란 얼굴을 시켰는데 동작이 삐죽을 데려오는 식)

import sys
sys.path.insert(0, ".")

from avatar import AVATAR


def face(key):
    if not key:
        return "-"
    e = AVATAR.expression(key)
    return f"{e.label}({key})" if e else f"?{key}?"


def move(key):
    if not key:
        return "-"
    m = AVATAR.motion(key)
    return f"{m.label}({key})" if m else f"?{key}?"


def motion_face(key):
    """그 동작이 스스로 데려오는 표정."""
    m = AVATAR.motion(key) if key else None
    return m.expression if m else None


rows = []      # (어디서, 무엇을 할 때, 동작, 표정, 비고)
clashes = []


# 1. 동작이 스스로 데려오는 얼굴
print("=" * 74)
print("1. 동작에 붙어 있는 표정")
print("=" * 74)
print(f"  {'동작':<14}{'표정':<20}{'유지':>8}{'':<14}{'언제 걸리나'}")
for m in AVATAR.motions:
    if not m.expression:
        continue
    ms = m.expression_ms if m.expression_ms is not None else int(m.duration * 1000)
    tag = "" if m.expression_ms is not None else "  (동작 길이)"
    when = "반드시" if m.expression_force else "얼굴이 비었을 때만"
    print(f"  {m.label:<14}{face(m.expression):<20}{ms:>6}ms{tag:<14}{when}")

blank = [m.label for m in AVATAR.motions
         if not m.expression and m.key not in ("idle", "walk")]
if blank:
    print(f"\n  표정을 안 정한 동작: {', '.join(blank)}")


# 2. 만지는 자리 — 자리가 정한 표정과 동작
print()
print("=" * 74)
print("2. 만졌을 때")
print("=" * 74)
warm_from = AVATAR.touch.get("warm_from")
print(f"  (호감 {warm_from} 이상이면 '깊을 때' 얼굴로 바뀐다)")
print(f"  {'자리':<10}{'어떻게':<6}{'낮을 때 (몸짓 + 얼굴)':<40}{'깊을 때'}")

for z in AVATAR.touch_zones():
    for kind, label in (("tap", "누름"), ("pet", "쓰담")):
        spec = z.tap if kind == "tap" else z.pet
        if not spec:
            continue
        mk = spec.get("motion")
        fk = spec.get("expression")
        mf = motion_face(mk)

        # 동작은 '아무 얼굴도 안 하고 있을 때'만 제 표정을 데려온다.
        # 자리가 표정을 정해 뒀으면 그게 이긴다.
        mm = AVATAR.motion(mk) if mk else None
        forced = bool(mm and mm.expression_force)
        bare = (not fk) or fk == "neutral"
        overridden = bool(mf) and (bare or forced)
        final = mf if overridden else fk

        note = ""
        if overridden and mf != fk:
            note = "  <-- 동작이 데려옴"

        def show(v):
            if v is None:
                return "-"
            if isinstance(v, (list, tuple)):
                return " 또는 ".join(face(x) for x in v)
            return face(v)

        warm = spec.get("expression_warm")
        mkw = spec.get("motion_warm")
        wf = spec.get("warm_from", AVATAR.touch.get("warm_from"))
        mark = f" [{wf}~]" if warm and wf != AVATAR.touch.get("warm_from") else ""
        name = z.label or "(이름없음)"
        lo = f"{move(mk)} + {show(fk)}"
        hi = (f"{move(mkw or mk)} + {show(warm)}{mark}") if warm else "-"
        print(f"  {name:<10}{label:<6}{lo:<40}{hi}")


# 3. 도구가 비트는 것
print()
print("=" * 74)
print("3. 무엇으로 만지는가")
print("=" * 74)
print(f"  {'도구':<10}{'동작':<18}{'표정':<20}{'자리별로 따로 정한 것'}")
for t in AVATAR.touch_tools():
    extra = []
    for zk, spec in (t.lines or {}).items():
        if not isinstance(spec, dict):
            continue
        bits = []
        if "expression" in spec:
            bits.append(face(spec["expression"]))
        if "motion" in spec:
            bits.append(move(spec["motion"]))
        if bits:
            extra.append(f"{zk}={'/'.join(bits)}")
    print(f"  {t.label:<10}{move(t.motion):<18}{face(t.expression):<20}"
          f"{', '.join(extra) if extra else '-'}")


# 4. 대사 한 줄에만 붙은 얼굴
print()
print("=" * 74)
print("4. 대사 한 줄에만 따로 붙인 것 (가장 세다)")
print("=" * 74)
found = False
for t in AVATAR.touch_tools():
    for zk, spec in (t.lines or {}).items():
        if not isinstance(spec, dict):
            continue
        for tone in ("polite", "casual"):
            for line in spec.get(tone, []) or []:
                if isinstance(line, dict):
                    found = True
                    print(f"  [{t.label} x {zk}] \"{line.get('text','')}\"")
                    print(f"      표정 {face(line.get('expression'))}"
                          f" · 동작 {move(line.get('motion'))}")
if not found:
    print("  없음")


# 5. 가위바위보
print()
print("=" * 74)
print("5. 가위바위보")
print("=" * 74)
for key, spec in (AVATAR.rps().get("outcomes", {}) or {}).items():
    print(f"  {key:<8}표정 {face(spec.get('expression'))}")
for h in AVATAR.rps_hands():
    print(f"  {h['label']:<8}동작 {move(h.get('motion'))}  (표정 없음)")


# 6. 단계가 통째로 바꿔 끼우는 것
print()
print("=" * 74)
print("6. 단계가 갈아 끼우는 것 (얀데레)")
print("=" * 74)
nn = AVATAR.relationship.get("no_negative", {})
for kind, tbl in nn.items():
    for a, b in (tbl or {}).items():
        shown = face if kind == "expressions" else move
        print(f"  {kind:<12}{shown(a):<22}->  {shown(b)}")

sil = AVATAR.relationship.get("silence", {})
print(f"\n  침묵일 때 표정 {face(sil.get('expression'))} · 말풍선 \"{sil.get('note')}\"")


# 맺음
print()
print("=" * 74)
print("규칙 1. 자리가 정한 표정이 이긴다. 동작은 얼굴이 비어 있을 때만 데려온다.")
print("규칙 2. 얼굴이 곧 그 동작인 몸짓(쑥스러워하기·얼굴 가리기)은 예외로 반드시 데려온다.")
print("      그래서 그 둘은 늘 놀란 얼굴이고, 웃는 자리에서는 아예 쓰지 않는다.")
print("      어느 쪽이든 한 번에 켜지는 표정은 언제나 하나다.")
print("=" * 74)

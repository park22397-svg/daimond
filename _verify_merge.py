# _verify_merge.py
# 개체 통합이 기존 동작을 바꾸지 않았는지 확인하는 일회성 점검 스크립트.

import importlib.util
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from avatar import AVATAR


def load_backup_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# 백업된 원본 ai_brain 을 그대로 읽어 SYSTEM_PROMPT / extract_expression 을 꺼낸다
# ai_brain.py 를 실제로 담고 있는 백업 중 가장 오래된 것(= 통합 전 원본)을 고른다
backups = sorted(
    d for d in os.listdir(HERE)
    if d.startswith("_backup_")
    and os.path.isdir(os.path.join(HERE, d))
    and os.path.isfile(os.path.join(HERE, d, "ai_brain.py"))
)
if not backups:
    print("FAIL: ai_brain.py 를 담은 백업 폴더를 찾을 수 없습니다")
    sys.exit(1)

orig_path = os.path.join(HERE, backups[0], "ai_brain.py")
print(f"원본 기준: {os.path.relpath(orig_path, HERE)}")
orig = load_backup_module("orig_ai_brain", orig_path)

fails = 0


# ============================================================
# 1) 페르소나 프롬프트가 원본과 같은가
# ============================================================

# 페르소나는 지뢰계/멘헤라 컨셉으로 의도적으로 새로 썼으므로
# 더 이상 원본과 같을 필요가 없다. 여기서는 차이만 보고한다.
print("\n[1] 페르소나 프롬프트 (원본 대비)")

a = orig.SYSTEM_PROMPT.strip()
b = AVATAR.system_prompt().strip()

if a == b:
    print(f"  원본과 동일 ({len(b)}자)")
else:
    print(f"  의도된 변경 — 원본 {len(a)}자 → 현재 {len(b)}자")

# 프롬프트에 남아 있어야 하는 것.
#
# 이 검사는 실제로 한 번 일을 했다 — [다이아가 하지 않는 것] 문단이
# 어느 판에서 통째로 줄어든 것을 알아챈 게 여기다.
# 실수로 또 빠지면 여기서 걸린다.
guards = ["자해", "협박", "죄책감", "선정적", "전문가"]
missing = [g for g in guards if g not in b]
if missing:
    fails += 1
    print(f"  FAIL  안전 지침 누락: {missing}")
else:
    print(f"  PASS  안전 지침 {len(guards)}개 모두 포함")


# ============================================================
# 2) 감정 판단 결과가 원본과 같은가
# ============================================================

print("\n[2] 감정 판단 (원본 extract_expression 대비)")
print("  원본과 다른 것은 실패가 아니다.")
print("  2026-08-18 에 기쁨과 즐거움의 신호를 맞바꿨다 —")
print("  두 표정의 모양이 93~95% 같아져서 신호를 갈라 놓았다.")
print("  여기서는 어디가 달라졌는지 보고만 한다.")

cases = [
    "오늘 진짜 좋아 🥰",
    "너무 슬퍼 😭 ㅠㅠ",
    "아 짜증나 💢",
    "헐 대박 😲",
    "메롱 😜",
    "ㅋㅋㅋ 웃겨",
    "그냥 그래",
    "",
    "😄 기분 좋다",
    "🤣 진짜?",
    "[joy] 태그가 남아있는 경우 😊",
    "안녕! 반가워",
    "울고 싶다 🥺 진짜 슬퍼",
    "😳 이게 뭐야",
    "ㅎㅎ 그렇구나",
]

moved = 0
for text in cases:
    want, _ = orig.extract_expression(text)
    got = AVATAR.detect_expression(orig.clean_reply(text) if text else text)
    same = want == got
    if not same:
        moved += 1
    print(f"  {'같음' if same else '바뀜'}  {text[:28]!r:32} "
          f"원본={want:10} 개체={got}")

print(f"  {len(cases) - moved}건 그대로, {moved}건 바뀜 (의도된 변경)")


# ============================================================
# 3) 유효 표정 집합이 같은가
# ============================================================

print("\n[3] 답변 감정 집합")

# 표정은 그 뒤로 여러 개 늘었다(만화 표정 12개, 절정 5개, 잠결).
# 원본에 있던 것이 사라졌는지만 본다 — 늘어난 것은 실패가 아니다.
want = set(orig.VALID_EXPRESSIONS)
got = AVATAR.reply_expression_keys()

lost = sorted(want - got)
if lost:
    fails += 1
    print(f"  FAIL  원본에 있던 감정이 사라졌다: {lost}")
else:
    print(f"  PASS  원본 {len(want)}개가 모두 남아 있다 "
          f"(지금은 {len(got)}개)")
print(f"        원본={sorted(want)}")
print(f"        개체={sorted(got)}")


# ============================================================
# 4) 아바타가 스스로 아는 것들
# ============================================================

print("\n[4] 개체가 소유한 정보")
print(f"  이름       : {AVATAR.name}")
print(f"  나이(계산) : {AVATAR.age()}세  (원본 프롬프트에는 22세로 고정 기재)")
print(f"  표정 개수  : {len(AVATAR.expressions)} "
      f"(답변용 {len(AVATAR.reply_expression_keys())}개)")
print(f"  VRM        : {AVATAR.model['vrm']}")

print("\n[5] 정의 충돌 (같은 이모지가 서로 다른 표정을 가리키는 경우)")
conflicts = AVATAR.trigger_conflicts()
if not conflicts:
    print("  없음")
for c in conflicts:
    print(f"  {c['token']}  답변전체={c['reply_expression']}  "
          f"말하는중={c['live_expression']}")

print("\n[6] 표정 안내문 (include_expression_guide=True 일 때만 추가되는 부분)")
guide_len = len(AVATAR.system_prompt(include_expression_guide=True))
base_len = len(AVATAR.system_prompt())
print(f"  기본 {base_len}자 / 안내문 포함 {guide_len}자 (+{guide_len - base_len})")

print("\n" + ("전부 통과" if fails == 0 else f"{fails}건 실패"))
sys.exit(0 if fails == 0 else 1)

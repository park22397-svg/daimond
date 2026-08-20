# _verify_cues.py
# 화면에 보이지 않는 표시(이모지 = 표정, 괄호 = 몸짓)를
# 제대로 걷어내고 위치를 남기는지 확인한다.

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ai_brain import extract_cues
from avatar import AVATAR

fails = 0


def face_of(emoji):
    """이 이모지가 지금 어느 표정인가.

    답을 검사에 적어 두지 않는다. 2026-08-18 에 기쁨과 즐거움의
    신호를 맞바꿨을 때(모양이 93~95% 같아져서) 이 검사만 옛 답안지를
    들고 있어서 실패했다. 개체에게 물으면 그런 일이 안 생긴다.
    """
    for e in AVATAR.expressions:
        if emoji in (e.reply_emoji or []):
            return e.key
    raise SystemExit(f"어느 표정도 {emoji} 를 쓰지 않는다 — 검사를 볼 것")


JOY = face_of("😊")      # 지금은 즐거움(fun)
SAD = face_of("😢")
WOW = face_of("😲")


def check(label, raw, want_clean, want_cues=None):
    global fails
    clean, cues = extract_cues(raw)

    ok = clean == want_clean
    if want_cues is not None:
        got = [(c["type"], c["key"]) for c in cues]
        ok = ok and got == want_cues

    if not ok:
        fails += 1

    print(f"  {'PASS' if ok else 'FAIL'}  {label}")
    print(f"        입력 : {raw!r}")
    print(f"        본문 : {clean!r}")
    if want_clean != clean:
        print(f"        기대 : {want_clean!r}")
    print(f"        큐   : {[(c['at'], c['type'], c['key']) for c in cues]}")
    if want_cues is not None and [(c['type'], c['key']) for c in cues] != want_cues:
        print(f"        기대 : {want_cues}")

    # 위치가 본문 밖으로 나가면 프런트에서 큐가 발화되지 않는다
    for c in cues:
        if not (0 <= c["at"] <= len(clean)):
            fails += 1
            print(f"        FAIL  위치 {c['at']} 가 본문 길이 {len(clean)} 를 벗어남")


print("[1] 이모지는 지우고 표정 큐로 남는다")
check("문장 끝 이모지", "오늘 정말 즐거웠어요 😊", "오늘 정말 즐거웠어요",
      [("expression", JOY)])
check("문장 중간 이모지", "그건 좀 😢 서운했어요.", "그건 좀 서운했어요.",
      [("expression", "sorrow")])
check("이모지 여러 개", "와 😲 진짜요? 😊", "와 진짜요?",
      [("expression", WOW), ("expression", JOY)])

print("\n[2] 괄호 몸짓은 지우고 동작 큐로 남는다")
check("동작 이름", "안녕하세요 (손인사)", "안녕하세요",
      [("motion", "wave")])
check("동작 + 이모지", "(손인사) 반가워요 😊", "반가워요",
      [("motion", "wave"), ("expression", JOY)])
check("별칭", "네 (끄덕)", "네", [("motion", "nod")])

print("\n[3] 괄호 속 상황은 화면에 남고, 읽히면 몸과 얼굴이 된다")
#
# 2026-08-20 에 뒤집었다. 예전에는 이름표가 아닌 괄호를 통째로 버렸다.
# 그래서 다이아는 몸짓 표에 있는 것만 할 수 있었고, 표에 없는 짓은
# 아무리 적어도 사라졌다. 이제 남기고, 읽을 수 있으면 얼굴까지 옮긴다.
check("상황이 남는다", "(살짝 웃으며) 그랬어요?", "(살짝 웃으며) 그랬어요?",
      [("expression", "fun")])
check("상황 + 이름표", "(눈을 피하며) 아니에요 (쑥스러워하기)",
      "(눈을 피하며) 아니에요",
      [("expression", "fluster"), ("motion", "shy")])
check("상황만", "(창밖을 오래 본다)", "(창밖을 오래 본다)",
      [("expression", "soft_gaze")])
check("못 읽는 상황은 글자로만", "(머리카락을 귀 뒤로 넘긴다) 뭐?",
      "(머리카락을 귀 뒤로 넘긴다) 뭐?", [])
check("쑥스러움은 몸과 얼굴이 같이", "(멋쩍은 듯 눈동자가 흔들리며) 왜?",
      "(멋쩍은 듯 눈동자가 흔들리며) 왜?", [("motion", "shy")])

print("\n[4] 한글 감정 표현은 화면에 남는다")
check("ㅋㅋ 유지", "그거 웃기네요 ㅋㅋ", "그거 웃기네요 ㅋㅋ", [])
check("좋아 유지", "저도 좋아요", "저도 좋아요", [])

print("\n[5] 표시가 없으면 본문 그대로")
check("표시 없음", "오늘은 무슨 일 있었어요?", "오늘은 무슨 일 있었어요?", [])
check("빈 입력", "", "", [])

print("\n[6] 큐 위치가 본문의 실제 지점을 가리키는가")
clean, cues = extract_cues("안녕하세요 😊 오늘 어땠어요 😢")
print(f"  본문: {clean!r}")
for c in cues:
    left = clean[:c["at"]]
    print(f"    {c['key']:<10} at={c['at']:<3} 그 지점까지의 글자: {left!r}")
# 이모지 앞뒤 공백은 정리되므로 인사말 끝(5)이나 공백 뒤(6) 어느 쪽이든 맞다
if not cues or cues[0]["at"] not in (5, 6):
    fails += 1
    print(f"  FAIL  첫 큐 위치가 {cues[0]['at'] if cues else '없음'}, 기대 5 또는 6")
else:
    print("  PASS  첫 큐가 인사말 직후를 가리킨다")

print("\n" + ("전부 통과" if fails == 0 else f"{fails}건 실패"))
sys.exit(0 if fails == 0 else 1)

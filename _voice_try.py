# _voice_try.py
# 목소리를 들어 보고 고른다
#
# 다이아 목소리를 바꾸려는데, 목록만 봐서는 못 고른다. 들어 봐야 한다.
# 같은 문장을 여러 목소리로 만들어 바탕화면 폴더에 넣는다.
#
#   python _voice_try.py                 -- 부드러운 쪽 여덟 개만
#   python _voice_try.py --all           -- 서른 개 전부
#   python _voice_try.py Achernar Leda   -- 고른 것만
#   python _voice_try.py --style Achernar  -- 그 목소리에 말투를 바꿔 가며
#
# 키는 GEMINI_API_KEY 환경변수나 config.TTS_API_KEY 에서 읽는다.
# **키를 이 파일에 적지 말 것.** 이 파일은 저장소에 올라간다.

import base64
import os
import re
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

OUT = os.path.join(os.path.expanduser("~"), "Desktop", "다이아_목소리후보")

TEXT = "안녕하세요. 저는 다이아예요. 오늘은 무슨 이야기를 해볼까요?"

# 구글이 목소리마다 붙여 둔 한마디.
#
# 은지는 낮고 차분한 결이었으니 Soft / Gentle / Smooth / Warm 쪽이
# 가까울 것이다. 그래도 귀로 들어 봐야 안다.
VOICES = [
    ("Achernar", "Soft 부드러움"),
    ("Vindemiatrix", "Gentle 순함"),
    ("Despina", "Smooth 매끄러움"),
    ("Algieba", "Smooth 매끄러움"),
    ("Sulafat", "Warm 따뜻함"),
    ("Callirrhoe", "Easy-going 편안함"),
    ("Umbriel", "Easy-going 편안함"),
    ("Schedar", "Even 고름"),
    ("Leda", "Youthful 어림"),
    ("Aoede", "Breezy 산뜻함"),
    ("Erinome", "Clear 또렷함"),
    ("Iapetus", "Clear 또렷함"),
    ("Autonoe", "Bright 밝음"),
    ("Zephyr", "Bright 밝음"),
    ("Kore", "Firm 단단함"),
    ("Alnilam", "Firm 단단함"),
    ("Orus", "Firm 단단함"),
    ("Gacrux", "Mature 무르익음"),
    ("Achird", "Friendly 다정함"),
    ("Zubenelgenubi", "Casual 편함"),
    ("Laomedeia", "Upbeat 신남"),
    ("Puck", "Upbeat 신남"),
    ("Sadachbia", "Lively 생기"),
    ("Enceladus", "Breathy 숨결"),
    ("Pulcherrima", "Forward 앞으로"),
    ("Charon", "Informative 알려줌"),
    ("Rasalgethi", "Informative 알려줌"),
    ("Sadaltager", "Knowledgeable 아는체"),
    ("Fenrir", "Excitable 들뜸"),
    ("Algenib", "Gravelly 거침"),
]

# 처음에 들어 볼 것. 은지 쪽에 가까울 만한 것들만.
FIRST = ["Achernar", "Vindemiatrix", "Despina", "Algieba",
         "Sulafat", "Callirrhoe", "Schedar", "Leda"]

# 말투를 시켜 볼 것들. Gemini 는 글로 적은 대로 읽는다.
STYLES = [
    ("기본", "부드럽고 조금 낮은 목소리로, 친한 사람에게 말하듯 자연스럽게"),
    ("차분", "낮고 차분한 목소리로, 서두르지 않고 또박또박"),
    ("다정", "다정하고 따뜻하게, 미소를 머금은 듯이"),
    ("담담", "담담하고 조용하게, 감정을 크게 싣지 않고"),
    ("나긋", "나긋나긋하고 여성스럽게, 조금 느리게"),
]

MODEL = "gemini-2.5-flash-preview-tts"


def key():
    k = os.environ.get("GEMINI_API_KEY", "").strip()

    if k:
        return k

    try:
        import config
        return str(getattr(config, "TTS_API_KEY", "") or "").strip()
    except Exception:
        return ""


def to_wav(raw, mime):
    """Gemini 는 헤더 없는 PCM 을 준다. 들으려면 wav 로 싸야 한다."""

    rate = 24000

    m = re.search(r"rate=(\d+)", mime or "")
    if m:
        rate = int(m.group(1))

    n = len(raw)

    head = b"RIFF" + struct.pack("<I", 36 + n) + b"WAVEfmt "
    head += struct.pack("<IHHIIHH", 16, 1, 1, rate, rate * 2, 2, 16)
    head += b"data" + struct.pack("<I", n)

    return head + raw


# 공짜 몫은 **모델마다 분당 3번**이다.
#
# 몰아서 부르면 네 번째부터 429 로 막힌다. 실제로 여덟 개를 만들려다
# 다섯 개에서 막혔다. 그래서 한 번 만들 때마다 쉬어 간다.
# 막히면 알려 주는 시간만큼 더 기다렸다 다시 해 본다.
PER_MINUTE = 3
GAP_SEC = 62.0 / PER_MINUTE


def make(api_key, voice, style, text=TEXT, tries=3):
    """한 번 만든다. (소리 바이트, 알림) 을 돌려준다.

    분당 몫에 걸리면 기다렸다 다시 해 본다.
    """

    import time

    import requests

    url = ("https://generativelanguage.googleapis.com/v1beta/models/"
           + MODEL + ":generateContent")

    body = {
        "contents": [{"parts": [{"text": style + ": " + text}]}],
        "generationConfig": {
            "responseModalities": ["AUDIO"],
            "speechConfig": {
                "voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voice}}
            },
        },
    }

    for n in range(tries):
        try:
            r = requests.post(url, json=body,
                              headers={"x-goog-api-key": api_key}, timeout=120)
        except Exception as e:
            return None, "못 붙음: " + str(e)

        if r.status_code == 200:
            break

        if r.status_code != 429 or n == tries - 1:
            return None, "HTTP %d %s" % (r.status_code, r.text[:150])

        # 얼마나 기다리라고 하는지 물어본다. 안 알려 주면 넉넉히.
        wait = 35.0

        try:
            for det in r.json().get("error", {}).get("details", []):
                d = det.get("retryDelay")
                if d:
                    wait = float(str(d).rstrip("s")) + 3
        except Exception:
            pass

        print("      (분당 몫에 걸림 - %.0f초 쉽니다)" % wait)
        time.sleep(wait)

    try:
        part = r.json()["candidates"][0]["content"]["parts"][0]
        raw = base64.b64decode(part["inlineData"]["data"])
        mime = part["inlineData"].get("mimeType", "audio/L16;rate=24000")
    except Exception as e:
        return None, "모르는 모양: " + str(e)

    return to_wav(raw, mime), None


def main(argv):
    api_key = key()

    if not api_key:
        print("키가 없습니다.")
        print()
        print("  https://aistudio.google.com/apikey 에서 받아서")
        print("  이렇게 넣고 다시 부르세요:")
        print()
        print('    $env:GEMINI_API_KEY = "받은키"')
        print("    python _voice_try.py")
        return 1

    os.makedirs(OUT, exist_ok=True)

    # 말투 견주기
    if "--style" in argv:
        argv = [a for a in argv if a != "--style"]
        voice = argv[0] if argv else "Achernar"

        print("목소리 %s 에 말투를 바꿔 가며 만듭니다." % voice)
        print()

        import time

        for i, (name, style) in enumerate(STYLES, 1):
            if i > 1:
                time.sleep(GAP_SEC)

            data, err = make(api_key, voice, style)
            f = os.path.join(OUT, "말투%d_%s_%s.wav" % (i, voice, name))

            if err:
                print("  실패 %-10s %s" % (name, err))
                continue

            open(f, "wb").write(data)
            print("  만듦 %-10s %s" % (name, os.path.basename(f)))

        print()
        print(OUT)
        return 0

    # 목소리 견주기
    want = [a for a in argv if not a.startswith("-")]

    if want:
        picked = [(v, d) for v, d in VOICES if v in want]
    elif "--all" in argv:
        picked = VOICES
    else:
        picked = [(v, d) for v, d in VOICES if v in FIRST]

    print("%d개를 같은 문장으로 만듭니다." % len(picked))
    print("문장:", TEXT)
    print("공짜 몫이 분당 %d번이라 %.0f분쯤 걸립니다." %
          (PER_MINUTE, len(picked) * GAP_SEC / 60))
    print()

    style = STYLES[0][1]
    ok = 0

    import time

    for i, (v, desc) in enumerate(picked):
        if i:
            time.sleep(GAP_SEC)

        data, err = make(api_key, v, style)
        f = os.path.join(OUT, "Gemini_%s_(%s).wav" % (v, desc.split()[0]))

        if err:
            print("  실패 %-14s %s" % (v, err))
            continue

        open(f, "wb").write(data)
        print("  만듦 %-14s %-22s %5.0f KB"
              % (v, desc, len(data) / 1024))
        ok += 1

    print()
    print("만든 것 %d개 -> %s" % (ok, OUT))

    if ok:
        print()
        print("들어 보고 마음에 드는 목소리 이름을 알려 주세요.")
        print("그 목소리에 말투를 바꿔 가며 더 맞춰 보겠습니다:")
        print("    python _voice_try.py --style <목소리이름>")

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

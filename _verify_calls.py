# _verify_calls.py
# 부르는 함수가 실제로 있는가.
#
# index.html 은 스크립트가 한 덩어리라 함수 하나를 지워도 아무 표시가
# 안 난다. 그것을 부르던 자리가 단추 눌렀을 때만 도는 자리면 더 그렇다 —
# 화면은 멀쩡히 뜨고, 그 단추만 죽어 있다.
#
# 2026-08-20 에 실제로 겪었다. 상황 칸과 말 칸을 하나로 합치면서
# sendSituation() 을 지웠는데, 상황 추천 보기 단추가 계속 그것을 부르고
# 있었다. 눌러도 ReferenceError 만 나고 아무 일도 안 일어났다.
# _verify_screen.py 는 이걸 못 잡는다 — 화면은 끝까지 실행되기 때문이다.
#
# 그래서 실행하지 않고 글자만 본다. 부르는 이름을 전부 모으고,
# 선언된 이름과 브라우저가 주는 이름을 뺀 나머지를 일러 준다.

import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

# 줄바꿈과 따옴표를 이름으로 둔다.
#
# 아래 글자 훑기가 이것들을 하나씩 견주는데, 코드 안에 그대로 적어 두면
# 이 파일을 고칠 때마다 따옴표가 엉킨다(실제로 한 번 깨졌다).
NL = chr(10)
BACKSLASH = chr(92)
QUOTES = "\"'" + chr(96)

PAGES = ["templates/index.html", "templates/test.html",
         "templates/rig.html", "templates/model_test.html"]


# 브라우저와 라이브러리가 주는 것들.
#
# 여기 없는데 우리가 만들지도 않은 이름이면 그것이 곧 죽은 부름이다.
GIVEN = {
    # 말
    "Array", "Object", "String", "Number", "Boolean", "Math", "JSON",
    "Date", "RegExp", "Error", "Map", "Set", "WeakMap", "Promise",
    "Symbol", "Proxy", "Reflect", "BigInt", "Infinity", "NaN",
    "parseInt", "parseFloat", "isNaN", "isFinite", "encodeURIComponent",
    "decodeURIComponent", "encodeURI", "decodeURI", "escape", "unescape",
    "structuredClone", "queueMicrotask",
    # 창
    "window", "document", "navigator", "location", "history", "screen",
    "console", "alert", "confirm", "prompt", "fetch", "atob", "btoa",
    "setTimeout", "clearTimeout", "setInterval", "clearInterval",
    "requestAnimationFrame", "cancelAnimationFrame", "getComputedStyle",
    "performance", "localStorage", "sessionStorage", "matchMedia",
    # 만드는 것
    "Image", "Audio", "Blob", "File", "FileReader", "FormData", "URL",
    "AudioContext", "webkitAudioContext", "SpeechSynthesisUtterance",
    "SpeechRecognition", "webkitSpeechRecognition", "MediaRecorder",
    "Uint8Array", "Uint16Array", "Int16Array", "Float32Array",
    "Float64Array", "ArrayBuffer", "DataView", "TextEncoder",
    "TextDecoder", "Event", "CustomEvent", "MouseEvent", "KeyboardEvent",
    "AbortController", "Worker", "OffscreenCanvas", "Path2D",
    "ResizeObserver", "IntersectionObserver", "MutationObserver",
    # 라이브러리
    "THREE", "VRM", "VRMUtils", "VRMSchema", "GLTFLoader", "OrbitControls",
    "require", "define", "module", "exports",
    # 말의 뼈대 (부름처럼 보이는 것)
    "if", "for", "while", "switch", "catch", "function", "return",
    "typeof", "new", "delete", "void", "in", "of", "do", "else", "try",
    "finally", "throw", "case", "break", "continue", "await", "async",
    "yield", "class", "extends", "super", "this", "constructor",
    "get", "set", "static", "let", "const", "var",
}


def script_of(html):
    """<script> 안쪽만. src 로 불러오는 것은 우리 글이 아니다."""

    out = []

    for m in re.finditer(r"<script\b([^>]*)>(.*?)</script>", html,
                         re.S | re.I):
        if "src=" in m.group(1):
            continue
        out.append(m.group(2))

    return "\n".join(out)


def strip_noise(src):
    """주석과 따옴표 안을 지운다.

    이것을 안 하면 주석에 적어 둔 설명("예전에는 sendSituation() 을
    불렀는데")과 글자열 속 CSS("background: rgba(...)")까지 부름으로
    세어, 멀쩡한 것을 죽었다고 일러 준다.

    지우는 대신 빈칸으로 바꾼다. 줄 수가 어긋나면 몇 줄인지 못 알려 준다.
    """

    out = []
    i = 0
    n = len(src)

    while i < n:
        c = src[i]

        # 한 줄 주석
        if c == "/" and i + 1 < n and src[i + 1] == "/":
            while i < n and src[i] != NL:
                out.append(" ")
                i += 1
            continue

        # 여러 줄 주석
        if c == "/" and i + 1 < n and src[i + 1] == "*":
            while i < n and not (src[i] == "*" and i + 1 < n
                                 and src[i + 1] == "/"):
                out.append(NL if src[i] == NL else " ")
                i += 1
            out.append("  ")
            i += 2
            continue

        # 따옴표 셋
        if c in QUOTES:
            quote = c
            out.append(" ")
            i += 1
            while i < n:
                if src[i] == BACKSLASH:
                    out.append("  ")
                    i += 2
                    continue
                if src[i] == quote:
                    out.append(" ")
                    i += 1
                    break
                out.append(NL if src[i] == NL else " ")
                i += 1
            continue

        out.append(c)
        i += 1

    return "".join(out)


def declared(src):
    """이 글 안에서 이름이 붙은 것 전부."""

    names = set()

    # function 이름(...)
    names |= set(re.findall(r"\bfunction\s+([A-Za-z_$][\w$]*)", src))

    # const/let/var 이름
    names |= set(re.findall(r"\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)", src))

    # class 이름
    names |= set(re.findall(r"\bclass\s+([A-Za-z_$][\w$]*)", src))

    # 넘겨받는 이름들.
    #
    # 넘겨받은 것을 부르는 자리가 있다(cb(), resolve()). 이것을 안 모으면
    # 멀쩡한 것을 죽었다고 일러 준다.
    for params in re.findall(r"\bfunction\s*[A-Za-z_$\w]*\s*\(([^)]*)\)", src):
        names |= _names_in(params)

    for params in re.findall(r"\(([^()]*)\)\s*=>", src):
        names |= _names_in(params)

    for one in re.findall(r"([A-Za-z_$][\w$]*)\s*=>", src):
        names.add(one)

    # catch (e)
    names |= set(re.findall(r"\bcatch\s*\(\s*([A-Za-z_$][\w$]*)", src))

    # for (const x of ...) 는 위에서 잡힌다

    return names


def _names_in(params):
    return set(re.findall(r"[A-Za-z_$][\w$]*", params))


def called(src):
    """부르는 이름과 그것이 있는 줄."""

    out = {}

    for m in re.finditer(r"([.\w$]?)\b([A-Za-z_$][\w$]*)\s*\(", src):
        # 앞에 점이 있으면 남의 것이다(obj.method()). 우리가 알 바 아니다.
        if m.group(1) == ".":
            continue

        name = m.group(2)

        if name in out:
            continue

        out[name] = src.count("\n", 0, m.start()) + 1

    return out


fails = []

for page in PAGES:
    path = os.path.join(HERE, page)

    if not os.path.exists(path):
        continue

    with open(path, encoding="utf-8") as f:
        html = f.read()

    src = strip_noise(script_of(html))

    if not src.strip():
        print("  SKIP  " + page + "  (스크립트 없음)")
        continue

    have = declared(src) | GIVEN
    dead = {n: ln for n, ln in called(src).items() if n not in have}

    if dead:
        print("  FAIL  " + page)
        for n, ln in sorted(dead.items(), key=lambda kv: kv[1]):
            print("          " + str(ln) + "줄  " + n + "() — 이런 것이 없다")
            fails.append(page + ":" + n)
    else:
        print("  PASS  " + page + "  (부르는 것이 전부 있다)")

print()

if fails:
    print("죽은 부름 " + str(len(fails)) + "곳")
    print("지웠는데 부르는 데가 남았거나, 이름을 잘못 적은 것이다.")
    sys.exit(1)

print("전부 통과")

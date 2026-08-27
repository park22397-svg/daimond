# _deploy.py
# 올리고, 올라간 것이 방금 그것인지 확인한다
#
# 왜 이게 있는가.
#
# `vercel deploy --prod` 만 하면 두 가지가 조용히 어긋난다.
#
#   1. 아바타가 빠진다. 소스만 바뀐 배포에서 빌드 캐시를 재사용하면서
#      static/ 을 안 실은 적이 있다. 화면은 멀쩡히 뜨고 다이아만 없었다.
#
#   2. 종료 코드가 거짓말한다. 멀쩡히 올라갔는데 실패라고 한 적이 있다
#      (다시 돌려 보니 0이었고 사이트도 새것이었다).
#
# 그래서 **종료 코드를 믿지 않는다.** 올리기 전에 소스의 지문을
# build.json 에 적고, 올린 뒤 사이트에 그 지문이 떠 있는지 본다.
# 떠 있으면 성공이다. 종료 코드가 뭐라 하든.
#
#   python _deploy.py

import hashlib
import json
import os
import subprocess
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))

SITE = "https://diamondai-six.vercel.app"

# 지문을 뜰 파일들. 이것이 바뀌면 사이트도 바뀌어야 한다.
#
# 검사 스크립트(_verify_*.py)는 뺀다 — 올리지도 않고, 그것만 고쳤을 때
# 굳이 다시 올릴 이유가 없다.
WATCH_DIRS = [("", ".py"), ("templates", ".html"), ("static", ".js")]

SKIP_PREFIX = ("_", "build.json")


def stamp():
    """지금 소스의 지문. 짧게 12자리."""

    h = hashlib.sha256()

    for sub, ext in WATCH_DIRS:
        root = os.path.join(HERE, sub) if sub else HERE

        if not os.path.isdir(root):
            continue

        for name in sorted(os.listdir(root)):
            if not name.endswith(ext):
                continue
            if name.startswith(SKIP_PREFIX):
                continue

            path = os.path.join(root, name)

            if not os.path.isfile(path):
                continue

            h.update(name.encode("utf-8"))

            with open(path, "rb") as f:
                h.update(f.read())

    return h.hexdigest()[:12]


def health(timeout=30):
    try:
        with urllib.request.urlopen(SITE + "/api/health", timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception:
        return None


def wait_for(want, seconds=90):
    """사이트에 그 지문이 뜰 때까지 기다린다. 뜨면 그 답을 돌려준다.

    올린 직후에는 옛 판이 잠깐 더 답할 수 있다.
    """

    end = time.time() + seconds
    last = None

    while time.time() < end:
        last = health()

        if last and last.get("build") == want:
            return last

        time.sleep(3)

    return last


def run(args):
    return subprocess.run(args, cwd=HERE, shell=True).returncode


def main():
    want = stamp()

    with open(os.path.join(HERE, "build.json"), "w", encoding="utf-8") as f:
        json.dump({"stamp": want, "at": time.time()}, f)

    print("이번 판:", want)
    print("올립니다 (캐시를 건너뜁니다)…")
    print()

    code = run("npx -y vercel@latest deploy --yes --prod --force")

    print()
    print("올라간 것이 방금 그것인지 봅니다…")

    h = wait_for(want)

    # 종료 코드가 0이 아니어도 사이트가 새것이면 올라간 것이다.
    # 반대로 0이어도 안 바뀌었으면 안 올라간 것이다. 사이트가 답이다.
    if not h or h.get("build") != want:
        print()
        print("  올라온 판:", (h or {}).get("build") or "확인 못 함")
        print("  올리려던 판:", want)

        if code != 0:
            print("  (배포 명령도 " + str(code) + " 로 끝났습니다)")

        print()
        print("아직 안 올라갔습니다. 다시 해 보세요.")
        return 1

    bad = []

    def show(name, ok, why):
        print("  %-10s %s" % (name, "있음" if ok else "없음 <- " + why))
        if not ok:
            bad.append(name)

    print()
    show("아바타", h.get("avatar"), "다이아가 안 나옵니다")
    show("겹치기 몸", h.get("body"), "옷 안이 텅 비어 보입니다")

    print("  %-10s %s" % ("저장소", h.get("store")))

    if h.get("store") != "blob":
        print("      <- 올린 데인데 파일로 잡혀 있습니다. 계정이 안 남습니다")
        bad.append("저장소")

    print("  %-10s %s" % ("모델 주소",
                          "터널 있음" if h.get("model_set") else "없음"))

    if not h.get("model_set"):
        print("      <- python _tunnel.py 를 켜야 다이아가 답합니다")

    print()

    if bad:
        print("빠진 것:", ", ".join(bad))
        return 1

    print("다 실렸습니다.", SITE)
    return 0


if __name__ == "__main__":
    sys.exit(main())

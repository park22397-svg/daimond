# _tunnel.py
# 올린 사이트가 모델 서버에 닿게 해 주는 길
#
# 왜 필요한가.
#
# 모델 서버(cju.nezip.co.kr:11434)는 내 컴퓨터에서는 40ms 로 닿는데
# **Vercel 에서는 아예 못 닿는다.** 미국도 서울도 연결 자체가 안 됐다.
# 바깥으로 나가는 것은 되므로(목소리는 1.3초에 온다) 그 서버·그 포트만
# 막힌 것이다.
#
# 그래서 내 컴퓨터가 가운데 선다. cloudflared 가 https 주소 하나를 만들고
# 그리로 온 것을 모델 서버로 넘긴다. https(443)로 나가므로 안 막힌다.
#
#   [올린 사이트] --https--> [트라이클라우드플레어] --> [내 컴퓨터] --> [모델 서버]
#
# 주소는 띄울 때마다 바뀐다. 환경변수에 두면 바뀔 때마다 다시 배포해야
# 하므로, 저장소에 적어 두고 사이트가 부를 때마다 읽게 했다.
# 이 파일이 그 값을 갱신한다.
#
#   python _tunnel.py
#
# 켜 둔 동안만 올린 사이트가 동작한다. 끄면 다시 못 닿는다.
# Ctrl+C 로 끝낸다.

import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

EXE = os.path.join(HERE, "_tools", "cloudflared.exe")

# 저장소 토큰을 넣어야 올린 데의 값을 고칠 수 있다
env = os.path.join(HERE, ".env.local")

if os.path.exists(env):
    for line in open(env, encoding="utf-8"):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"'))

import config  # noqa: E402
import store  # noqa: E402

# 무엇을 이어 줄 것인가. 터널은 주소의 앞부분만 안다.
TARGET = config.OLLAMA_URL.rsplit("/api/", 1)[0]

URL_RE = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")


def announce(url):
    """올린 사이트가 볼 수 있게 주소를 적어 둔다."""

    store.write_json(config.RUNTIME_KEY, {
        "ollama_url": url.rstrip("/") + "/api/chat",
        "at": time.time(),
    })


def main():
    if not os.path.exists(EXE):
        print("cloudflared 가 없습니다:", EXE)
        print("받는 곳: https://github.com/cloudflare/cloudflared/releases")
        return 1

    if store.backend() != "blob":
        print("저장소가 파일로 잡혀 있습니다(.env.local 이 없나요?).")
        print("이대로면 올린 사이트가 새 주소를 못 봅니다.")
        print()

    print("이어 줄 곳:", TARGET)
    print("터널을 엽니다…")
    print()

    p = subprocess.Popen(
        [EXE, "tunnel", "--url", TARGET, "--no-autoupdate"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )

    told = None

    try:
        for line in p.stdout:
            m = URL_RE.search(line)

            if m and m.group(0) != told:
                told = m.group(0)
                announce(told)

                print("=" * 58)
                print("  터널 주소:", told)
                print("  올린 사이트가 이제 이리로 옵니다.")
                print()
                print("  이 창을 켜 둔 동안만 동작합니다.")
                print("  끝내려면 Ctrl+C")
                print("=" * 58)
                print()

            # 오류만 보여 준다. 죄다 찍으면 무엇이 문제인지 안 보인다.
            low = line.lower()
            if any(w in low for w in ("err", "fail", "refus", "timeout")):
                print(line.rstrip())

    except KeyboardInterrupt:
        print()
        print("터널을 닫습니다.")

    finally:
        p.terminate()

        try:
            p.wait(timeout=5)
        except Exception:
            p.kill()

    return 0


if __name__ == "__main__":
    sys.exit(main())

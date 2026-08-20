# _clean_test_accounts.py
# 시험 계정만 골라 지운다
#
# 왜 이게 있는가.
#
# 올린 데를 시험하면서 만든 계정을 치우려고 `vercel blob del
# diamondai/accounts.json` 을 두 번 했다. **그 파일 안에는 진짜 계정도
# 같이 들어 있다.** 그래서 두 번 다 쓰던 계정이 통째로 날아갔다
# (기억은 따로 있어서 살았지만 로그인은 못 하게 됐다).
#
# 계정 파일은 사람마다 한 칸이 아니라 **전부 한 파일**이다. 지울 때는
# 파일이 아니라 그 안의 한 칸을 지워야 한다. 그 일을 여기서 한다.
#
#   python _clean_test_accounts.py alice bob      -- 그 아이디만 지운다
#   python _clean_test_accounts.py --list         -- 누가 있는지만 본다
#
# 기억 파일(memory/u_<아이디>.json)은 건드리지 않는다. 같은 아이디로
# 다시 만들면 그 기억이 다시 붙는다.

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

# .env.local 에 저장소 토큰이 들어 있다. 그것을 넣어야 올린 데를 본다.
env = os.path.join(HERE, ".env.local")

if os.path.exists(env):
    for line in open(env, encoding="utf-8"):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"'))

import accounts  # noqa: E402
import store  # noqa: E402


def main(argv):
    print("보고 있는 곳:", store.backend(),
          "(blob = 올린 데, file = 내 컴퓨터)")
    print()

    data = accounts.load()
    users = data["users"]

    if not users:
        print("계정이 없습니다.")
        return 0

    if not argv or argv[0] in ("--list", "-l"):
        print("있는 계정:")
        for key, rec in users.items():
            print("  ", rec.get("id", key))
        print()
        print("지우려면: python _clean_test_accounts.py <아이디> ...")
        return 0

    want = {a.strip().lower() for a in argv if a.strip()}
    gone = []

    for key in list(users):
        if key in want:
            gone.append(users.pop(key)["id"])

    missing = want - {g.lower() for g in gone}

    if not gone:
        print("지울 것이 없습니다.", "없는 아이디:", ", ".join(sorted(missing)))
        return 1

    accounts.save(data)

    print("지운 계정:", ", ".join(gone))

    if missing:
        print("없던 아이디:", ", ".join(sorted(missing)))

    print("남은 계정:", ", ".join(r.get("id", k)
                                 for k, r in data["users"].items()) or "없음")
    print()
    print("기억 파일은 그대로 둡니다. 같은 아이디로 다시 만들면 다시 붙습니다.")

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

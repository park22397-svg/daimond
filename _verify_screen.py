# _verify_screen.py
# 화면 스크립트가 끝까지 실행되는가.
#
# 잡으려는 것은 값이 맞는지가 아니라 **끝까지 가는지** 다.
#
# index.html 의 스크립트는 한 덩어리라, 한가운데서 오류가 나면 거기서
# 통째로 멈춘다. animate() 가 파일 한가운데서 한 번 불리는데 그 안에서
# 쓰는 값을 아래쪽에서 const 로 선언해 두면 첫 프레임에
# ReferenceError 가 나고, 파일 끝의 loadAvatar() 까지 못 간다.
# 그러면 **아바타가 아예 안 나온다** — 화면은 멀쩡히 뜨는데 다이아만 없다.
#
# 2026-08-19 에 실제로 이걸 겪었다(시선 추적을 붙이면서 eye/gaze 를
# 그리기 고리보다 아래에 선언했다). 콘솔을 안 열어 보면 원인이 안 보인다.
#
# 브라우저 없이 node 로 한 번 통과시켜 본다. THREE 도 document 도
# 가짜를 물려 주므로 그림이 맞는지는 못 본다. 멈추는지만 본다.

import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PAGES = ["templates/index.html", "templates/test.html",
         "templates/rig.html", "templates/model_test.html"]

STUB = r"""
const fs = require('fs');
const vm = require('vm');
const src = fs.readFileSync(process.argv[2], 'utf8');

function fake(name) {
  const f = function () { return proxy; };
  const proxy = new Proxy(f, {
    get(t, k) {
      if (k === Symbol.toPrimitive) return () => 0;
      if (k === 'valueOf') return () => 0;
      if (k === 'toString') return () => name;
      if (k === 'length') return 0;
      if (k === 'then') return undefined;
      if (k === Symbol.iterator) return function* () {};
      return proxy;
    },
    apply() { return proxy; },
    construct() { return proxy; },
    has() { return true; },
    set() { return true; },
  });
  return proxy;
}

let reached = false;
const sandbox = {
  THREE: fake('THREE'),
  document: fake('document'),
  navigator: fake('navigator'),
  fetch: () => Promise.resolve(fake('res')),
  performance: { now: () => 0 },
  console: { log() {}, warn() {}, error() {} },
  setTimeout: () => 0, setInterval: () => 0,
  clearTimeout: () => {}, clearInterval: () => {},
  requestAnimationFrame: () => 0,
  Image: function () { return fake('img'); },
  URL: { createObjectURL: () => '', revokeObjectURL: () => {} },
  Blob: function () { return fake('blob'); },
  Audio: function () { return fake('audio'); },
  SpeechSynthesisUtterance: function () { return fake('u'); },
  speechSynthesis: fake('speechSynthesis'),
  atob: () => '', btoa: () => '',
  __done: () => { reached = true; },
};
sandbox.addEventListener = () => {};
sandbox.removeEventListener = () => {};
sandbox.matchMedia = () => fake('mq');
sandbox.localStorage = fake('ls');
sandbox.location = fake('loc');
sandbox.window = sandbox;
sandbox.globalThis = sandbox;

try {
  vm.runInNewContext(src + '\n;__done();', sandbox, { timeout: 20000 });
} catch (e) {
  const at = (e.stack || '').split('\n').slice(1, 3).join(' / ');
  console.log('STOP ' + e.name + ': ' + e.message + ' | ' + at);
  process.exit(1);
}
process.exit(reached ? 0 : 1);
"""


def scripts_in(path):
    """<script> ... </script> 안쪽만 뽑는다. src= 로 불러오는 것은 건너뛴다."""
    import io
    lines = io.open(path, encoding="utf-8").read().split("\n")
    out, buf, on = [], [], False

    for line in lines:
        t = line.strip()
        if not on and t == "<script>":
            on, buf = True, []
            continue
        if on and "</script>" in t:
            on = False
            out.append("\n".join(buf))
            continue
        if on:
            buf.append(line)

    return out


def main():
    node = shutil.which("node")
    if not node:
        print("node 가 없어 건너뜁니다. (설치하면 이 검사가 돕니다)")
        return 0

    tmp = tempfile.mkdtemp(prefix="diamond_screen_")
    stub = os.path.join(tmp, "stub.js")
    with open(stub, "w", encoding="utf-8") as f:
        f.write(STUB)

    fails = 0

    for rel in PAGES:
        path = os.path.join(HERE, rel)
        if not os.path.isfile(path):
            continue

        chunks = scripts_in(path)
        if not chunks:
            print(f"  건너뜀  {rel}  (안쪽 스크립트 없음)")
            continue

        for i, code in enumerate(chunks):
            js = os.path.join(tmp, f"c{i}.js")
            with open(js, "w", encoding="utf-8") as f:
                f.write(code)

            r = subprocess.run([node, stub, js],
                               capture_output=True, text=True, timeout=60)

            tag = rel if len(chunks) == 1 else f"{rel} [{i + 1}]"

            if r.returncode == 0:
                print(f"  PASS  {tag}  ({len(code.splitlines())}줄, 끝까지 갔다)")
            else:
                fails += 1
                print(f"  FAIL  {tag}")
                for line in (r.stdout or r.stderr).strip().split("\n")[:3]:
                    print(f"        {line}")

    shutil.rmtree(tmp, ignore_errors=True)

    print("\n" + ("전부 통과" if fails == 0 else f"{fails}건 실패"))
    return 0 if fails == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

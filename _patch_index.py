# _patch_index.py
# index.html 을 개체 기반으로 바꾸는 수술용 패치.
# 앵커 문자열을 찾아 그 구간만 교체한다. 실패하면 아무것도 바꾸지 않는다.

import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PATH = os.path.join(HERE, "templates", "index.html")

src = open(PATH, encoding="utf-8").read()
orig = src
done = []


def replace_between(start_anchor, end_anchor, new_text, label, include_end=False):
    """start_anchor 부터 end_anchor 직전까지를 new_text 로 바꾼다."""
    global src
    i = src.find(start_anchor)
    if i < 0:
        print(f"  SKIP  {label} — 시작 앵커를 찾지 못함")
        return False
    j = src.find(end_anchor, i)
    if j < 0:
        print(f"  SKIP  {label} — 끝 앵커를 찾지 못함")
        return False
    if include_end:
        j += len(end_anchor)
    src = src[:i] + new_text + src[j:]
    done.append(label)
    print(f"  OK    {label}")
    return True


def replace_once(old, new, label):
    global src
    if old not in src:
        print(f"  SKIP  {label} — 대상을 찾지 못함")
        return False
    if src.count(old) > 1:
        print(f"  SKIP  {label} — 대상이 {src.count(old)}곳이라 모호함")
        return False
    src = src.replace(old, new, 1)
    done.append(label)
    print(f"  OK    {label}")
    return True


print("index.html 패치")

# ------------------------------------------------------------
# 1) applyExpression 을 개체 기반으로
# ------------------------------------------------------------

new_apply = """                // 지울 이름은 개체가 알려준 목록을 쓴다.
                const clearNames = ENTITY_SHAPES.length
                    ? ENTITY_SHAPES
                    : ['joy', 'angry', 'sorrow', 'fun',
                       'surprised', 'blink', 'blink_l', 'blink_r'];

                clearNames.forEach(name => {
                    try { proxy.setValue(name, 0.0); } catch (e) {}
                });

                if (surprisedBlendShapeName) {
                    try { proxy.setValue(surprisedBlendShapeName, 0.0); } catch (e) {}
                }

                // 표정 수치는 이 파일이 정하지 않는다. 개체가 정한다.
                const shapes = entityShapesFor(expression) || {};
                Object.keys(shapes).forEach(name => {
                    try { proxy.setValue(name, shapes[name]); } catch (e) {}
                });

                if (!Object.keys(shapes).length) {
                    isExpressing = false;
                }

"""

replace_between(
    "                // 표정이 바뀔 때 이전 값이 남지 않도록 먼저 깨끗이 초기화합니다.",
    "                if (expression !== 'neutral') {",
    new_apply,
    "applyExpression 을 개체 기반으로 교체",
)

# ------------------------------------------------------------
# 2) animate() 안에서 동작·이동 갱신
# ------------------------------------------------------------

replace_once(
    """            const deltaTime =
                clock.getDelta();


            if (currentVRM) {""",
    """            const deltaTime =
                clock.getDelta();


            if (currentVRM) {

                // 개체가 내려준 동작을 재생하고 위치를 갱신한다
                updateMotion(deltaTime);
                updateRoam(deltaTime);
""",
    "animate() 에 동작·이동 갱신 추가",
)

# ------------------------------------------------------------
# 3) showReply 가 큐를 받도록
# ------------------------------------------------------------

replace_once(
    """                                function showReply(
            reply,
            expression
        ) {""",
    """                                function showReply(
            reply,
            expression,
            cues
        ) {""",
    "showReply 가 큐를 받도록",
)

replace_once(
    """            playLipSync(
                reply
            );""",
    """            playLipSync(
                reply
            );


            // 서버가 걷어낸 이모지·괄호를 그 자리에서 표정과 몸짓으로 되살린다
            playCues(cues);""",
    "showReply 에서 큐 재생",
)

# ------------------------------------------------------------
# 4) /api/chat 응답의 cues 전달
# ------------------------------------------------------------

replace_once(
    """                showReply(
                    data.reply,
                    wasSleeping
                        ? 'surprised'
                        : (
                            data.expression ||
                            'neutral'
                        )
                );""",
    """                showReply(
                    data.reply,
                    wasSleeping
                        ? 'surprised'
                        : (
                            data.expression ||
                            'neutral'
                        ),
                    data.cues
                );""",
    "/api/chat 응답의 cues 전달",
)

# ------------------------------------------------------------
# 5) 바닥 격자 — 걷는 게 보이려면 기준이 필요하다
# ------------------------------------------------------------

replace_once(
    """        const ambientLight = new THREE.AmbientLight(
            0xffffff,
            0.5
        );

        scene.add(ambientLight);""",
    """        const ambientLight = new THREE.AmbientLight(
            0xffffff,
            0.5
        );

        scene.add(ambientLight);


        // 바닥 — 이게 없으면 걸어도 제자리처럼 보인다
        const floorGrid = new THREE.GridHelper(
            6, 24, 0x3a3d5c, 0x2a2d44
        );
        floorGrid.material.transparent = true;
        floorGrid.material.opacity = 0.45;
        floorGrid.position.y = -0.2;
        scene.add(floorGrid);""",
    "바닥 격자 추가",
)

# ------------------------------------------------------------
# 6) 시작할 때 개체를 불러오고 기본 동작을 재생
# ------------------------------------------------------------

replace_once(
    """                resetToAttentionPose();
                setEyeState(true);""",
    """                resetToAttentionPose();
                setEyeState(true);

                // 개체를 받아 표정·동작 정의를 넘겨받는다
                loadEntity().then(() => {
                    cacheBones();
                    playMotion('idle');
                });""",
    "로드 후 개체 가져오기",
)

# ------------------------------------------------------------

if len(done) < 7:
    print(f"\n적용 {len(done)}/7 — 일부가 빠져 파일을 저장하지 않습니다.")
    sys.exit(1)

open(PATH, "w", encoding="utf-8").write(src)
print(f"\n적용 {len(done)}/7 · {len(orig)} -> {len(src)} bytes")

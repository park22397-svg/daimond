// vrm_pick.js
// 어느 아바타를 볼 것인가
//
// 확인대가 셋이다 — /rig(리깅), /test(개체), /model-test(겹치기).
// 셋 다 정해진 아바타만 불러오게 되어 있어서, 다른 아바타를 손보려면
// static/avatar.vrm 을 갈아 끼워야 했다. 그러다 원본을 잃기 쉽다.
//
// 파일 고르기를 세 벌로 적으면 셋이 어긋난다. 그래서 여기 한 곳에 두고
// 셋이 불러다 쓴다.
//
// 파일은 **서버에 올리지 않는다.** 브라우저 안에서만 연다 —
// 남의 아바타를 남의 서버에 둘 이유가 없다.
//
// 쓰는 쪽:
//
//   VrmPick.mount({
//       home:     '/static/avatar.vrm',   // 되돌아갈 자리
//       homeName: '다이아',
//       second:   true,                   // 두 번째 파일도 고를 수 있게
//       onOpen:   (url, name, which) => { ... },
//   });
//
// which 는 'main' 또는 'body' 다. second 를 안 켜면 늘 'main'.

(function (global) {

    const CSS = `
#vrm-bar {
    position: absolute;
    right: 14px;
    top: 14px;
    z-index: 60;
    display: flex;
    align-items: center;
    gap: 7px;
    padding: 6px 8px 6px 12px;
    background: rgba(20, 22, 42, 0.86);
    border: 1px solid #3a3f68;
    border-radius: 999px;
    color: #dfe1f0;
    font-size: 0.8rem;
    font-family: 'Malgun Gothic', 'Apple SD Gothic Neo', sans-serif;
    user-select: none;
}
#vrm-bar .which {
    max-width: 220px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    color: #b9bcd8;
}
#vrm-bar button {
    background: rgba(58, 63, 104, 0.5);
    border: 1px solid #4a4f7a;
    color: #dfe1f0;
    padding: 3px 9px;
    border-radius: 999px;
    font-size: 0.75rem;
    cursor: pointer;
    font-family: inherit;
    white-space: nowrap;
}
#vrm-bar button:hover { background: #5a4d8d; border-color: #7a68b0; }
`;

    let opts = null;
    let label = null;

    function say(name) {
        if (label) label.textContent = name || '';
    }

    function pick(which) {
        const input = document.createElement('input');
        input.type = 'file';
        input.accept = '.vrm,.glb';

        input.addEventListener('change', () => {
            const f = input.files && input.files[0];
            if (!f) return;

            // 브라우저 안에서만 연다. 서버로 보내지 않는다.
            opts.onOpen(URL.createObjectURL(f), f.name, which);

            if (which === 'main') say(f.name);
        });

        input.click();
    }

    function mount(o) {
        opts = Object.assign({
            home: '/static/avatar.vrm',
            homeName: '다이아',
            second: false,
            onOpen: function () {},
        }, o || {});

        const style = document.createElement('style');
        style.textContent = CSS;
        document.head.appendChild(style);

        const bar = document.createElement('div');
        bar.id = 'vrm-bar';

        label = document.createElement('span');
        label.className = 'which';
        label.textContent = opts.homeName;
        bar.appendChild(label);

        const openBtn = document.createElement('button');
        openBtn.textContent = '📂 파일 열기';
        openBtn.title = '다른 VRM 을 연다 (서버에 올리지 않는다)';
        openBtn.addEventListener('click', () => pick('main'));
        bar.appendChild(openBtn);

        if (opts.second) {
            const bodyBtn = document.createElement('button');
            bodyBtn.textContent = '📂 속 몸';
            bodyBtn.title = '겹쳐 놓을 맨몸 VRM';
            bodyBtn.addEventListener('click', () => pick('body'));
            bar.appendChild(bodyBtn);
        }

        const backBtn = document.createElement('button');
        backBtn.textContent = '↩ ' + opts.homeName;
        backBtn.title = '원래 아바타로 되돌린다';
        backBtn.addEventListener('click', () => {
            say(opts.homeName);
            opts.onOpen(opts.home, opts.homeName, 'main');
        });
        bar.appendChild(backBtn);

        // 무대 위에 올린다. 무대가 없으면 문서에 붙인다.
        const stage = document.getElementById('stage')
            || document.querySelector('.stage')
            || document.body;

        if (stage === document.body) {
            bar.style.position = 'fixed';
        } else if (getComputedStyle(stage).position === 'static') {
            stage.style.position = 'relative';
        }

        stage.appendChild(bar);

        return { say: say };
    }

    global.VrmPick = { mount: mount, say: say };

})(window);

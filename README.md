# diamondAI

Flask + Ollama + VRM 으로 만든 아바타 챗봇.

말을 하고, 얼굴이 바뀌고, 몸이 움직이고, 만지면 반응한다.
사람과의 사이가 대화에 따라 오르내리고 그 사이가 말투를 정한다.

## 돌리는 법

```bash
pip install flask requests
python main.py
```

`http://127.0.0.1:5000`

## 넣어야 하는 것

- `static/avatar.vrm` — 옷 입은 아바타
- `static/표현용.vrm` — 맨몸 + 절정 표정용 (없으면 `avatar.py` 의 `model["layered"]` 를 끈다)

두 파일은 라이선스가 재배포 금지라 저장소에 없다.

`config.py` 의 `OLLAMA_URL` 과 `OLLAMA_MODEL` 을 쓰는 서버에 맞춘다.

## 화면

| 주소 | 무엇 |
|---|---|
| `/` | 대화 화면 |
| `/model-test` | 표정·동작·옷 시험대 |
| `/rig` | 뼈 각도 확인대 |
| `/pixel` | 픽셀창 |

## 짜임새

하나의 개체(`avatar.py` 의 `VirtualAvatar`)가 페르소나·표정·동작·관계·만지기를
전부 소유한다. 화면은 `/api/avatar` 로 받아 쓴다. 같은 정의가 두 군데
적혀 어긋나는 일을 없애려는 구조다.

- `avatar.py` — 개체. 이 프로젝트의 중심
- `ai_brain.py` — 대화 엔진. 표시 추출, 관계 갱신
- `memory_manager.py` — 기억 저장
- `main.py` — Flask 경로
- `_verify_*.py` — 검사 스크립트. 동작 충돌·만지기·표정 잠금 등

## 검사

```bash
python _verify_collision.py     # 동작이 몸을 뚫지 않는지
python _verify_touch.py         # 만지는 자리와 도구가 다 채워졌는지
python _verify_expressions.py   # 표정 수치가 잠근 값 그대로인지
python _verify_pairs.py         # 한 동작에 표정이 하나만 걸리는지
```

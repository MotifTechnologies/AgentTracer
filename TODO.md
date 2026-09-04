# TODO

## 배포용 ShareGPT 직렬화가 exporter 명세와 다르다

`datasample/sft_all.jsonl`(1,023행, HF 업로드 준비본)과 `dump.json`은 현행
exporter 산출물이 아니라 **역할별 키셋**으로 직렬화되어 있다:

- system/user: `role, content`
- assistant: `role, content, tool_calls` + `thinking`(reasoning이 있던 턴에만,
  703턴 중 679턴). 툴콜만 있는 턴의 `content: null`은 유지된다
- tool: `role, content, tool_call_id`

반면 exporter 명세(`export/sharegpt.py`의 `_MESSAGE_KEYS`)는 "모든 턴이 5키
(role/content/tool_calls/thinking/tool_call_id)를 null로라도 균일하게 갖는다"
이다. null을 일괄 제거한 것도 아니고(assistant의 `content: null`이 살아 있다),
학습기가 받는 chat-template 형태로 맞춘 별도 변환본으로 보인다.

- [ ] 이 형식이 어디서 만들어졌는지 확인한다(변환 스크립트의 소재)
- [ ] 정합 방향을 결정한다:
      (a) 역할별 형식을 exporter의 공식 출력 모드로 추가하고 docs에 병기 —
          변환 과정이 저장소 코드로 증빙된다
      (b) 균일 5키를 정본으로 유지하고, HF 공개본이 정본 형식으로 나가는지
          공개 전 단계에서 확인한다
- [ ] thinking이 없는 assistant 턴(24/703)의 학습 시 처리 방식을 정한다
      (빈 문자열로 채울지, 키 생략을 학습기가 허용하는지)

`datasample/`은 HF 캐시 흔적(.gitattributes, .cache)까지 든 33MB 디렉토리가
작업 트리 안에 untracked로 있던 것 — .gitignore에 추가했다. 데이터 배포는
저장소가 아니라 HF 데이터셋 저장소의 몫이다.

## soffice를 쓰려면 LibreOffice가 든 이미지가 있어야 한다

`soffice` 서버는 `soffice --headless`를 `SandboxAccess.exec`로 넘긴다. 즉 LibreOffice가
**샌드박스 컨테이너 안에** 있어야 한다. `pdf`·`xlsx`가 바이트만 꺼내 서버 프로세스에서
파싱하는 것과 다르다 — 그쪽 의존성(pypdf, openpyxl)은 순수 파이썬이라 PEP 723으로
해결되지만, LibreOffice는 시스템 바이너리라 uv/pip으로 설치할 수 없다.

이미지를 어디에 물리느냐는 더 이상 문제가 아니다. 태스크가 `docker_image`를 들고 오면
그것이 config의 이미지를 대신하므로, 문서 변환 시드에 해당 이미지를 적어 넣으면 된다.
세트마다 config를 나눌 필요는 없다. 남은 일은 그 이미지를 실제로 만드는 것뿐이다.

- [ ] LibreOffice 포함 이미지 빌드 및 레지스트리 등록

  ```dockerfile
  FROM python:3.12-slim
  RUN apt-get update && apt-get install -y --no-install-recommends \
      libreoffice-writer libreoffice-calc && rm -rf /var/lib/apt/lists/*
  ```

  전체 `libreoffice`는 1GB+, writer/calc만 400~600MB. 태스크마다 이미지를 받는 구조라
  크기가 곧 pull 시간이다.

- [ ] soffice를 쓰는 시드 작성 — 시드의 `docker_image`에 위 이미지를 지정

## 서버가 요구하는 샌드박스 바이너리가 선언되어 있지 않다

위 문제의 일반형이고, 태스크마다 이미지가 달라지면서 오히려 커졌다. 예전에는 config의
이미지 하나만 확인하면 됐지만, 지금은 시드 수백 줄에 흩어진 이미지가 각각 그 바이너리를
갖고 있는지 사람이 맞춰볼 방법이 없다.

soffice를 include한 채 그것이 없는 이미지로 돌리면 **런타임 툴 호출에서만** 실패하고
기동 시점에는 안 걸린다. 궤적은 정상 종료하고 툴만 조용히 실패하므로, fail-fast
원칙(선언되지 않은 도구가 궤적에 영향을 주지 않는다)에서 벗어난다.

- [x] 매니페스트에 필요 바이너리를 선언하고(`requires_binaries: ["soffice"]`),
      샌드박스 기동 직후 `command -v`로 확인해 없으면 태스크를 거부한다.
      기동 "시점"이 아니라 태스크마다 검사하는 이유: 시드가 `docker_image`를
      들고 오면 그 이미지 기준으로 봐야 하고, 그 샌드박스는 그때에야 생긴다.
      config 공유 이미지에 없으면 런 전체 중단, 태스크가 들고 온 이미지에
      없으면 그 태스크만 재시도 없이 error로 기록된다.

## 그 외

- [ ] `datasets/swebench_local` 이름 변경 — SWE 전용이 아니라 "이슈를 받아 diff를
      제출하는 태스크" 형태를 가리키므로 `patch_diff` 쪽이 정확하다. 현재 이 로더를
      쓰는 config도 없는 미사용 경로.
- [ ] MCP 서버 동작 단위 테스트 — `tests/test_mcp_manifests.py`는 매니페스트와 구현의
      툴 이름 일치만 본다. 스모크 테스트를 걷어내면서 "실제로 띄워 호출하는" 검증이
      사라졌으므로, sqlite JOIN 오답 같은 동작 버그는 지금 아무 테스트도 못 잡는다.
- [ ] 시드 난이도 — Kimi-K3 기준 정답률 99%, 툴 실패 1/300. 작은 모델 SFT용으로는
      충분할 수 있으나 GRPO는 reward 분산이 없어 학습이 안 된다. RL 데이터가 필요하면
      방해 요소·툴 선택 모호성·홉 증가로 난이도를 올린 별도 세트가 필요하다.
- [ ] `toolcall_log_error_report` 동점 처리 — 생성기는 동점 시 이른 시각을 정답으로
      잡는데 지시문에 그 규칙이 없다. 300건 중 3건이 이것 때문에 오답 처리됐다.
      동점이 생기는 데이터를 아예 만들지 않는 쪽이 규칙을 늘리는 것보다 낫다.

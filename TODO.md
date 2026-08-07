# TODO

## soffice 서버는 이미지에 LibreOffice가 있어야 동작한다

`soffice` 서버는 `soffice --headless` 명령을 `SandboxAccess.exec`로 넘긴다. 즉
LibreOffice가 **샌드박스 컨테이너 안에** 있어야 한다. `pdf`·`xlsx`가 바이트만 꺼내
서버 프로세스에서 파싱하는 것과 다르다 — 그쪽 의존성(pypdf, openpyxl)은 순수 파이썬
이라 PEP 723으로 해결되지만, LibreOffice는 시스템 바이너리라 uv/pip으로 설치할 수
없다.

현재 `config/generate.yaml`은 `python:3.12-slim`을 쓰고 `mcp.include`에서 soffice를
빼둔 상태라 문제가 드러나지 않는다. 문서 변환 시드를 만들 때 아래가 필요하다.

- [ ] LibreOffice 포함 이미지 준비

  ```dockerfile
  FROM python:3.12-slim
  RUN apt-get update && apt-get install -y --no-install-recommends \
      libreoffice-writer libreoffice-calc && rm -rf /var/lib/apt/lists/*
  ```

  전체 `libreoffice`는 1GB+, writer/calc만 400~600MB. 세트별로
  `-c environment.image=...` 오버라이드하면 config를 새로 만들 필요는 없다.

- [ ] soffice를 쓰는 시드 작성 (문서 변환 도메인)

## 서버가 요구하는 샌드박스 바이너리가 선언되어 있지 않다

위 문제의 일반형. soffice를 include한 채 slim 이미지로 돌리면 **런타임 툴 호출에서만**
실패하고 기동 시점에는 안 걸린다. 궤적은 정상 종료하고 툴만 조용히 실패하므로,
fail-fast 원칙(선언되지 않은 도구가 궤적에 영향을 주지 않는다)에서 벗어난다.

- [ ] 매니페스트에 필요 바이너리를 선언하고(`requires_binaries: ["soffice"]` 등),
      러너 기동 시 샌드박스에서 확인해 없으면 중단

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

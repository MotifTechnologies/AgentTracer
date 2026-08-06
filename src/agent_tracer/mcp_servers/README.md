# mcp_servers/ — MCP 서버 자동 디스커버리 디렉토리

agent-tracer 러너는 시작 시 이 디렉토리(패키지 내장, config `mcp.discovery_dir`로 교체 가능)를 스캔해서 발견된 MCP 서버를 **전부 자동
등록**한다(default all). 폴더에 넣는 것만으로 에이전트 툴셋에 편입되며, 별도 등록
코드는 필요 없다.

## 컨벤션

- **하위 폴더 하나 = MCP 서버 하나.** 폴더명이 곧 서버명이다.
- 각 폴더에는 기동 방법을 선언하는 **`mcp.json` 매니페스트**가 반드시 있어야 한다.
  스키마: [`mcp.schema.json`](./mcp.schema.json) (manifest_version 1)
- `mcp.json`이 없거나 스키마 검증에 실패하는 폴더는 등록하지 않고 **에러로 실행을
  중단**한다(fail-fast — 조용히 빠진 툴셋으로 대량 생성되는 사고 방지).
- 서버명은 YAML의 `mcp.include` / `mcp.exclude`와 툴 네임스페이스(`mcp:<서버명>/<툴명>`)에
  그대로 쓰인다.

```
src/agent_tracer/mcp_servers/
├── README.md          # 이 문서
├── mcp.schema.json    # 매니페스트 JSON Schema
├── echo/              # 예제 서버 (계약 레퍼런스)
│   ├── mcp.json
│   └── server.py
├── calculator/        # 정확 연산 (샌드박스 불필요)
│   ├── mcp.json
│   ├── server.py
│   └── smoke_test.py
└── soffice/           # 문서 변환 — 태스크 샌드박스 안의 LibreOffice
    ├── mcp.json
    ├── server.py
    └── smoke_test.py
```

> search는 MCP가 아니라 stirrup 내장 web 툴(web_fetch/web_search)을 사용한다
> (config `tools.web: true`, web_search는 `BRAVE_API_KEY` 필요).

## YAML에서 포함 서버 제어

미지정 시 전체 등록이 기본값이다. 도메인별 config에서 불필요한 서버만 좁힌다.

```yaml
mcp:
  # discovery_dir: 미지정 시 패키지 내장 mcp_servers/ 사용
  include: ["search", "soffice"] # 이 서버들만 등록
  # exclude: ["calculator"]      # 또는 제외 방식 (include와 동시 사용 불가)
```

등록 결과(서버·툴 목록, 버전)는 궤적 metadata에 기록된다.

## 샌드박스를 다루는 서버

에이전트 파일을 건드리는 서버는 **어느 샌드박스가 이번 태스크 것인지** 알아야 한다.
매니페스트는 러너 기동 시 한 번 읽히고 샌드박스는 태스크마다 새로 만들어지므로,
그 값을 매니페스트에 적어둘 방법은 없다 — 아직 존재하지 않는 값이다.

그래서 러너가 **spawn하는 모든 stdio 서버의 환경변수**로 넘긴다
(구현: [`mcp/discovery.py`](../mcp/discovery.py)의 `sandbox_env`). 백엔드에 중립적인
용어만 쓴다:

| 변수 | 의미 |
|---|---|
| `AGENT_TRACER_ENV_TYPE` | 샌드박스를 만든 `environment.type` |
| `AGENT_TRACER_SANDBOX_ID` | `environments.attach()`에 넘길 값 (local이면 없음) |
| `AGENT_TRACER_WORKDIR` | 샌드박스 안 에이전트 작업 디렉토리 |
| `AGENT_TRACER_HOST_DIR` | 샌드박스가 마운트한 호스트 경로 (마운트하는 백엔드만) |
| `AGENT_TRACER_USER` | 샌드박스 안 사용자 (있는 백엔드만) |
| `AGENT_TRACER_OPTIONS` | JSON — 백엔드별 추가 값, `attach()`에 그대로 전달 |

매니페스트별 opt-in이 아니라 **전부에 항상 세팅**되므로 새 서버는 존재를 전제해도
된다. 빈 값은 `""`가 아니라 아예 빠지니 **존재 여부**로 판단하면 된다. 매니페스트
`env`가 마지막에 병합되므로 필요하면 덮어쓸 수 있다.

샌드박스에 실제로 닿는 방법은 `environments.attach(env_type, sandbox_id, options)`
하나뿐이다. **백엔드로 분기하지 말 것** — 그래야 플러그인으로 설치된 샌드박스가 서버
수정 없이 그대로 동작한다. 돌려주는 객체는 `exec(command, timeout_s)` 한 메서드다
([`environments/__init__.py`](../environments/__init__.py)의 `SandboxAccess`).

이 서버들은 `attach()`를 쓰려고 `agent_tracer`를 import하는데, 각자 별도 `uv run`이라
러너의 인터프리터를 물려받지 않는다. 그래서 러너가 `PYTHONPATH`도 같이 넘긴다 —
PEP 723 헤더에는 그 서버가 실제로 쓰는 의존성만 적으면 된다.

`soffice/`가 이 패턴의 레퍼런스이고, `calculator/`는 샌드박스를 아예 쓰지 않는 쪽의
레퍼런스다.

## 매니페스트 작성 규칙 요약

| 필드 | 필수 | 설명 |
|---|---|---|
| `manifest_version` | ✅ | 현재 `1` 고정 |
| `name` | ✅ | 폴더명과 일치해야 함 (`^[a-z][a-z0-9_-]*$`) |
| `description` | ✅ | 한 줄 요약 — 궤적 metadata에 기록 |
| `transport` | ✅ | `stdio` \| `http` |
| `command` / `args` | stdio 시 | 러너가 spawn할 명령. 상대 경로는 매니페스트 폴더 기준 |
| `url` | http 시 | streamable-HTTP 엔드포인트 (서버 수명주기는 외부 관리) |
| `env` | | spawn 환경변수. 시크릿은 반드시 `"env:VAR_NAME"` 참조로 — 원문 저장 금지, 미해석 시 실행 거부 |
| `startup_timeout_s` | | initialize 핸드셰이크 대기 상한 (기본 15초) |
| `call_timeout_s` | | 툴 호출 기본 타임아웃 (기본 60초) |
| `tools` | | 선언적 툴 목록 (문서·계약 테스트용 — 런타임 진실은 MCP discovery) |

## 예제: echo 서버

[`echo/`](./echo/)는 계약의 최소 동작 레퍼런스다. 새 서버를 만들 때 이 구조를
복사해서 시작하면 된다.

```bash
# 단독 실행 (러너가 하는 것과 동일한 방식)
cd src/agent_tracer/mcp_servers/echo && uv run server.py

# 툴 호출 스모크 테스트
cd src/agent_tracer/mcp_servers/echo && uv run smoke_test.py
```

서버 구현은 공식 MCP Python SDK(FastMCP)를 사용하고, 의존성은 PEP 723 인라인
메타데이터로 선언해 `uv run` 한 번으로 기동되게 한다 — 폴더별 venv 관리가 필요 없다.

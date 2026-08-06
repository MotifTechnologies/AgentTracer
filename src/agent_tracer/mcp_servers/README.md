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
├── calculator/        # (예정) 조기훈 님
└── soffice/           # (예정) 조기훈 님
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

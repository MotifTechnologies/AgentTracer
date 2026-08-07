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
├── calculator/        # 정확 연산
├── time/              # 현재 시각 · 타임존 변환
├── filesystem/        # 파일 읽기·쓰기·편집·검색      [샌드박스]
├── sqlite/            # SQLite 쿼리·수정              [샌드박스]
├── soffice/           # 문서 변환 (LibreOffice)       [샌드박스]
└── context7/          # 라이브러리 문서 조회          [외부 HTTP]

각 폴더는 mcp.json · server.py · smoke_test.py 로 동일하다.
단 `[외부 HTTP]`는 server.py가 없다 — 우리가 띄우는 게 아니다.
```

`[샌드박스]` 표시가 있는 서버는 에이전트 파일을 다루므로 아래 "샌드박스를 다루는
서버" 계약을 따른다. 나머지는 샌드박스 환경변수를 무시한다.

`[외부 HTTP]`는 `transport: http`로 남의 엔드포인트를 가리킨다. spawn하는 프로세스가
없으니 샌드박스 환경변수도 무관하고, 대신 **네트워크와 그쪽 가용성에 의존**한다.
스모크 테스트가 실패하면 먼저 그쪽을 의심해야 하므로 실패 메시지가 그렇게 말한다.

각 서버의 계약은 스모크 테스트가 실제 서버를 띄워(또는 접속해) 검증한다. 러너 없이
단독 실행된다:

```bash
cd src/agent_tracer/mcp_servers/<서버> && uv run smoke_test.py
```

> 범용 search·fetch는 MCP가 아니라 stirrup 내장 web 툴(web_fetch/web_search)을 쓴다
> (config `tools.web: true`, web_search는 `BRAVE_API_KEY` 필요). 같은 걸 MCP로
> 또 붙이면 모델에게 중복된 툴이 두 벌 보인다. `context7`은 임의 URL이 아니라 특정
> 라이브러리 문서를 정리해서 주는 거라 별개로 둔다 — 겹치는 부분이 있으니, 실제
> 궤적에서 둘 다 쓰이는지는 보고 판단할 것.

### 왜 이 서버들인가

`code_exec`으로 다 되는데도 툴로 두는 이유는 **궤적에 무엇이 남는가**다.
`cat -n f | sed -n '20,40p'`는 모델의 셸 숙련도를 기록하고,
`read_file(path=..., offset=20)`은 수행한 단계를 기록한다. 학습 데이터로 쓸 거면
후자가 쓸모 있고, 왕복 비용은 같다.

- `filesystem` — `edit_file`은 셸에 마땅한 대응물이 없다. `sed -i`를 한 번에
  맞히는 건 태스크와 무관한 기술이고, 틀리면 파일이 조용히 깨진다. 여기서는
  정확히 한 번 매칭되지 않으면 개수와 함께 거부한다.
- `sqlite` — 합계·조인을 모델이 암산하면 자신 있게 틀린다. 쿼리는 검증 가능하다.
  샌드박스에 `sqlite3` CLI는 대개 없으므로 `python3`(표준 라이브러리 sqlite3)로
  실행한다.
- `time` — 모델에겐 시계가 없다. 기억한 오프셋은 DST 경계·인도(+05:30) 같은
  반시간 오프셋에서 틀리고, 그게 보통 태스크가 노리는 지점이다.
- `context7` — 모델의 라이브러리 API 지식은 학습 시점에 묶여 있고, 낡은 시그니처를
  자신 있게 쓴다. `time`이 시계를 주는 것과 같은 종류의 결핍 보충이다.
  `resolve-library-id` → `query-docs` 2단계이고, 툴 이름이 하이픈인 건 우리가 정한
  게 아니라 그쪽 스펙이다.

**git 서버는 일부러 없다.** 기준을 뒤집으면 이유가 나온다 — 래퍼의 가치는 모델이
그 CLI에 얼마나 서툰지에 비례하는데, git CLI는 모델이 가장 유창한 축이다. 게다가
쓰기(commit·checkout·reset)를 열면 태스크 도중 작업 트리가 날아갈 경로가 생기고,
읽기만 열면 어차피 커밋하러 셸에 들어간 모델이 조회도 거기서 끝낸다. 실제로 그랬다:
읽기 전용 git 서버를 붙여 돌려봤을 때 모델은 `git__log` 대신
`git rev-list --count`를 셸로 실행했다. 양쪽 다 값을 못 하므로 `code_exec`에 맡긴다.

## YAML에서 포함 서버 제어

미지정 시 전체 등록이 기본값이다. 도메인별 config에서 불필요한 서버만 좁힌다.

```yaml
mcp:
  # discovery_dir: 미지정 시 패키지 내장 mcp_servers/ 사용
  include: ["filesystem", "soffice"] # 이 서버들만 등록
  # exclude: ["echo"]                # 또는 제외 방식 (include와 동시 사용 불가)
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
| `AGENT_TRACER_OPTIONS` | JSON — 백엔드별 추가 값, `attach()`에 그대로 전달. **`sandbox_options: true`를 선언한 매니페스트에만** |

`OPTIONS`를 뺀 나머지는 매니페스트별 opt-in이 아니라 **전부에 항상 세팅**되므로 새
서버는 존재를 전제해도 된다. 빈 값은 `""`가 아니라 아예 빠지니 **존재 여부**로
판단하면 된다. 매니페스트 `env`가 마지막에 병합되므로 필요하면 덮어쓸 수 있다.

`OPTIONS`만 예외인 이유는 거기가 백엔드 크리덴셜이 들어가는 자리이기 때문이다 —
`e2b.attach()`는 여기서 API 키를 꺼낸다. 계산만 하는 서버나 나중에 추가된 서드파티
서버에 키가 갈 이유가 없으므로 샌드박스에 붙는 서버가 매니페스트에 직접 선언한다.
`environment.options` 값은 `env:VAR_NAME` 참조를 지원하며 기동 시 해석된다 —
해석 실패는 실행 거부다.

읽는 쪽은 `environments.from_env()` 한 줄이면 된다 — 위 변수들을 해석해서
`(access, workdir)`을 돌려준다. **백엔드로 분기하지 말 것.** 그래야 플러그인으로
설치된 샌드박스가 서버 수정 없이 그대로 동작한다.

```python
from agent_tracer.environments import from_env, resolve

access, workdir = from_env()
rc, out, err = access.exec(f"wc -l {resolve('data.csv', workdir)}")
```

`access`가 제공하는 건 `exec(command, timeout_s)` 하나뿐이다
([`environments/__init__.py`](../environments/__init__.py)의 `SandboxAccess`).
파일 API도 수명주기도 없다 — 문서를 변환하는 서버에 필요한 건 명령 하나다.
바이너리를 주고받아야 하면 base64로 감싼다(`filesystem/server.py` 참고).

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
| `env` | | spawn 환경변수(stdio). 시크릿은 반드시 `"env:VAR_NAME"` 참조로 — 원문 저장 금지, 미해석 시 실행 거부 |
| `headers` | | 매 요청에 붙는 HTTP 헤더(http 전용). `env` 와 같은 규율 — `env:` 참조는 기동 시 해석되고 실패하면 실행 거부, 그 외 값은 적은 그대로 전송. API 키를 매니페스트에 적으면 repo에 키를 공개하는 것. stdio에서는 **빈 객체라도** 선언 자체가 거부 |
| `sandbox_options` | | 이 서버가 샌드박스에 붙는다는 선언(stdio 전용). 선언한 서버만 `AGENT_TRACER_OPTIONS`(= 백엔드 크리덴셜)를 받는다 |
| `startup_timeout_s` | | initialize 핸드셰이크 대기 상한 (기본 15초). 클라이언트가 선택된 서버를 한 번에 순차 연결하므로 실제 상한은 선택된 매니페스트 값의 **합**. 넘기면 그 시도를 중단 |
| `call_timeout_s` | | 툴 호출 타임아웃 (기본 60초, stdio·http 모두 적용). 넘긴 호출은 취소되고 모델에게 타임아웃 결과로 돌아간다 — 궤적은 계속된다 |
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

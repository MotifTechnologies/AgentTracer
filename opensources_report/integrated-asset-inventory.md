# 통합자산목록

문서 ID: OSS-ASSET-001 · 버전: 1.0 · 기준일: 2026-10-14

**본 저장소 조사 범위에서 작성 완료**. 조사한 주요 저장소는 1개이며,
조직 전체 주요 저장소의 전수 목록과 대조한 결과는 아니다. 같은 저장소의
MCP 환경을 별도 주요 저장소 수로 집계하지 않는다.

## 주요 저장소 자산

| 필드 | REPO-001 |
| --- | --- |
| 저장소 | [MotifTechnologies/motif-agent-tracer-v2](https://github.com/MotifTechnologies/motif-agent-tracer-v2) |
| 목적 | 에이전트 태스크 실행 및 SFT/RL용 trajectory 기록 |
| 기본 브랜치 / 조사 커밋 | `main` / `0a620516f706c8d98a21f182ba1a99e6dc4cc988` |
| 공개 범위 / 운영 여부 | internal / archived=false |
| 담당 리뷰어 | `@junhyeok-motech`, `@gihuncho` — [CODEOWNERS](../.github/CODEOWNERS) |
| 중요도 / 서비스 자산 책임자 | 조직 기준 분류 및 별도 책임자 미확인; 위 담당자는 코드 리뷰 역할 |
| 언어·환경 | Python >=3.13, uv, 루트 및 MCP script lock |
| 프로젝트 라이선스 | Apache-2.0; Stirrup 유래 코드의 MIT 고지는 [NOTICE](../NOTICE)에 포함 |
| OSS 목록 | root `pyproject.toml`·`uv.lock`, stdio MCP 8개의 `server.py.lock` |
| SBOM | 최신 main Security 실행의 CycloneDX 1.6 JSON 10개 |
| 취약점 검사 | 루트 runtime `pip-audit`, 소스 `bandit`; 각 MCP 환경 전체의 취약점 스캔은 별도 범위 |
| 업데이트 자동화 | [.github/dependabot.yml](../.github/dependabot.yml), uv·Actions 주간 갱신 |
| 예외 및 승인 | [정책 승인본](organization-policy-approved.md), [취약점 예외 목록](../.github/pip-audit-ignore.txt), 해당 PR |

## 구성요소·검사 범위

각 행의 상위 저장소는 REPO-001이다. 표의 SBOM 파일은 Git에 커밋된 파일이 아니라
아래 Security 실행의 artifact 내부 파일명이다.

| 구성요소 ID | 환경 / 구성요소 | 의존성·정의 근거 | SBOM 파일 / 검사 상태 |
| --- | --- | --- | --- |
| ENV-001 | 프로젝트 runtime | `pyproject.toml`, `uv.lock` | `runtime.cdx.json` / 생성·라이선스 검사 통과 |
| ENV-002 | development | 루트 lock의 runtime+dev 환경 | `development.cdx.json` / 생성·라이선스 검사 통과 |
| MCP-001 | calculator | `src/agent_tracer/mcp_servers/calculator/` | `mcp-calculator.cdx.json` / 통과 |
| MCP-002 | echo | `src/agent_tracer/mcp_servers/echo/` | `mcp-echo.cdx.json` / 통과 |
| MCP-003 | filesystem | `src/agent_tracer/mcp_servers/filesystem/` | `mcp-filesystem.cdx.json` / 통과 |
| MCP-004 | pdf | `src/agent_tracer/mcp_servers/pdf/` | `mcp-pdf.cdx.json` / 통과; wheel 개별 검토 포함 |
| MCP-005 | soffice | `src/agent_tracer/mcp_servers/soffice/` | `mcp-soffice.cdx.json` / Python 환경 통과; OS 바이너리는 별도 |
| MCP-006 | sqlite | `src/agent_tracer/mcp_servers/sqlite/` | `mcp-sqlite.cdx.json` / 통과 |
| MCP-007 | time | `src/agent_tracer/mcp_servers/time/` | `mcp-time.cdx.json` / 통과 |
| MCP-008 | xlsx | `src/agent_tracer/mcp_servers/xlsx/` | `mcp-xlsx.cdx.json` / 통과 |
| EXT-001 | context7 외부 HTTP MCP | [manifest](../src/agent_tracer/mcp_servers/context7/mcp.json) | Python 스캔 제외; `index.json.external`에 명시 |

상세 버전·구성요소·파일 해시는 각 SBOM과 `index.json`을 원본으로 사용한다.
프로젝트 설정에 따라 동적으로 선택되는 모델/API·사용자 제공 MCP·실행 이미지는
이 고정 패키징 목록에 모두 열거되지 않으며, 실제 배포 설정별 자산 대조가 필요하다.

## SBOM 및 재점검 증빙

| 증빙 | 실행 / 실제 확인 | 생성 (UTC) | 만료 (UTC) |
| --- | --- | --- | --- |
| 최신 main SBOM | [38231561759](https://github.com/MotifTechnologies/motif-agent-tracer-v2/actions/runs/38231561759), 10개 / `complete=true`, `passed=true`, `errors=[]` | 2026-10-12 09:42:51 | 2027-01-10 09:41:58 |
| 주간 재점검 SBOM | [38198888339](https://github.com/MotifTechnologies/motif-agent-tracer-v2/actions/runs/38198888339), 10개 / 생성 완료 및 검사 통과 | 2026-10-12 03:14:15 | 2027-01-10 03:13:11 |

보관은 생성 후 90일이다. 다운로드한 각 실행의 `index.json`과
`license-report.json`에서 위 상태를 확인했다. 취약점 스캔 성공은 기존 예외를
적용한 결과이며, 취약점 0건을 의미하지 않는다.

## 갱신 및 전수 대조

1. 저장소 추가·폐기, 담당 변경, 배포 대상 또는 MCP manifest 변경 시 해당 PR에서 자산목록을 갱신한다.
2. SBOM 증빙은 검토 대상 커밋과 일치하는 실행을 연결하고, 만료 전에 필요한 산출물을 별도 보존한다.
3. 조직 전수 대조 시 전체 저장소 목록의 추출일·추출 범위·총수·주요 자산 선정 기준·누락 및 제외 사유를 기록한다.
4. 외부 서비스·Docker/OS·데이터/API 권리는 검사 제외 범위를 기록하고 실제 배포 책임자가 추가 검토한다.

| 전수 대조 항목 | 현재 상태 |
| --- | --- |
| 이번 조사에서 확인한 저장소 | 1개 |
| 조직 전체 저장소 수 / 주요 저장소 수 | 미조사 |
| 조직 목록 추출일 / 비교 담당자 | 미기록 |
| 조직 전수 대조 완료 | 미확인 |

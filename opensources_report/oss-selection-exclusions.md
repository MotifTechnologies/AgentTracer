# OSS 선정 제외 목록

문서 ID: OSS-SEL-001 · 버전: 1.1 · 작성일: 2026-10-14 · 수정일: 2026-10-16

적용 범위는 이 저장소의 Python 의존성 및 패키징된 stdio MCP 환경이다.
아래 표는 [기존 라이선스 검사 코드](../.github/scripts/check_licenses.py)의
판정을 선정 시 확인할 수 있도록 정리한 것이다.

## 제외·보류 기준

| ID | 대상 조건 | 선정 처리 | 근거 및 해제 조건 |
| --- | --- | --- | --- |
| EX-01 | 유효한 SPDX 표현식이 허용 목록으로 평가되지 않음 (`blocked`) | 현 정책에서 도입 제외 | 허용 대안이 있는 정확한 `OR` 표현식인지 확인. 정책 변경이 필요하면 근거·코드·테스트를 포함한 PR 승인 필요 |
| EX-02 | 선언 누락, 미인식·사용자 정의 라이선스, `LicenseRef` 등 (`unknown`) | 근거 확인 전 도입 보류 | 배포된 원문·버전·조건을 검토하고 기존 해시 기반 검토 방식에 따라 근거를 추가 |
| EX-03 | `AND`의 일부가 비허용이거나, 승인되지 않은 `WITH` 조합 | 도입 제외 또는 재검토 보류 | 구성 조건 전체를 검토하고 충족 여부 확인 |
| EX-04 | pypdfium2의 미검토 버전·플랫폼·선언 또는 고지 파일의 누락·추가·중복·변경 | 기존 특례 적용 제외 | 전체 고지 파일 및 배포 의무를 재검토하고 정확한 파일명·SHA-256 집합을 승인 PR에 반영 |
| EX-05 | MCP script lock 누락, 새 실행 방식으로 스캔 불가, 불완전한 SBOM | 검증 완료 전 도입 보류 | lock 및 수집 범위를 보완하고 완전한 SBOM과 검사 통과를 확인 |

예를 들어 `GPL-3.0-only`는 현 허용 목록에 없어 차단된다. 다만
`MIT OR GPL-3.0-only`처럼 검사기가 인식하는 유효한 표현식에 허용 대안이 있으면
통과할 수 있다.

## 허용 및 개별 검토와의 관계

| 구분 | 현재 관리 대상 | 근거 |
| --- | --- | --- |
| 허용 목록 | `ACCEPTED`에 등록된 정확한 SPDX 식별자 | [검사 코드](../.github/scripts/check_licenses.py) |
| 원문 확인 후 매핑 | python-dateutil 2.9.0.post0의 `Dual License` 선언 | 동일 코드의 `REVIEWED_TEXTS`, 버전·원문 SHA-256 |
| 고지 묶음 개별 검토 | pypdfium2 5.13.0, 검토된 Linux x86_64 / Windows x64 wheel | [검토 문서](../docs/pypdfium2-license-review.md), [파일 해시 목록](../.github/license-reviews/pypdfium2-5.13.0.json) |
| 취약점 수용 예외 | Pillow 관련 예외 식별자 | [pip-audit-ignore.txt](../.github/pip-audit-ignore.txt); 라이선스 제외 목록과 별개 |

LGPL·MPL 일부 식별자도 현재 `ACCEPTED`에 포함된다.
배포 시 고지·소스 제공 조건은 해당 검토 문서와 원문을 기준으로 확인한다.

## 실제 제외 사례 대장

2026-10-14 조사 기준: 개별 제외 사례 미등록.

| 사례 ID | OSS / 버전 / 사용 목적 | 적용 기준 | 검토 결과 | 승인·결정 PR | 재검토 조건 |
| --- | --- | --- | --- | --- | --- |
| 미등록 | 확인된 실제 제외 사례 없음 | 해당 없음 | 미확인 | 해당 없음 | 실제 사례 발생 시 등록 |

사례가 발생하면 실제 패키지·버전, 제외 사유, 검토일과 담당자, 대체재,
재검토 조건을 해당 PR에 기록하고 이 표에서 연결한다.

## 변경 및 재검토

- 기존 정책 변경 이력은 [초기 도입](https://github.com/MotifTechnologies/motif-agent-tracer-v2/commit/bd86549), [SBOM 정책 개선](https://github.com/MotifTechnologies/motif-agent-tracer-v2/commit/24af3fe), [wheel 검토 추가](https://github.com/MotifTechnologies/motif-agent-tracer-v2/commit/d80e065)에 남아 있다.
- 매주 월요일 03:00 UTC 자동 검사와 의존성·라이선스 근거 변경 시 검사를 수행한다.
- 선정 재평가는 사례 PR에 목적 적합성·대안·조건 변경을 기록한다.
- OS 유틸리티·외부 서비스·데이터/API 권리는 대상별 검토 기록을 남긴다.

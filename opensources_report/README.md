# 오픈소스 관리 증빙

기준일: 2026-10-14 (UTC) · 대상: `MotifTechnologies/motif-agent-tracer-v2`

이 폴더는 기존 Git·PR 승인 기록을 근거로 정책과 운영 문서를 모은다.
승인·변경·조치 이력은 Git/PR을 원본으로 관리하며, 기존 승인 항목은 **Git 관리 완료**로 인정한다.

## 문서 목록

| 문서 | 내용 | 상태 |
| --- | --- | --- |
| [OSS 선정 제외 목록](oss-selection-exclusions.md) | 기존 검사 정책에 따른 제외·보류 기준, 실제 제외 사례 등록 방식 | 작성 완료; 기존 정책 정리 |
| [조직 정책 승인본](organization-policy-approved.md) | 본 저장소에 적용되는 승인된 정책과 승인 PR 연결 | 기존 정책의 Git 승인 완료; 통합 문서는 신규 작성 |
| [RACI 문서](raci.md) | CODEOWNERS와 PR 역할을 기준으로 업무별 책임 구분 | 작성 완료; 신규 운영 역할표는 문서 PR 검토 대상 |

조사 기준 원격 main: [`0a620516f706c8d98a21f182ba1a99e6dc4cc988`](https://github.com/MotifTechnologies/motif-agent-tracer-v2/commit/0a620516f706c8d98a21f182ba1a99e6dc4cc988).

## Git으로 관리 완료한 항목

| 항목 | 완료 근거 | 관리 방식 |
| --- | --- | --- |
| 허용 정책·검토 예외의 버전 관리 | [검사 코드](../.github/scripts/check_licenses.py), [검토 JSON](../.github/license-reviews/pypdfium2-5.13.0.json), PR #10·#24 | 커밋의 변경 내역과 승인 PR |
| 저장소 정책 승인 | PR #10·#24·#28의 승인과 병합 기록 | 승인자·승인일·대상 커밋을 PR에서 확인 |
| 담당 리뷰어 지정 | [CODEOWNERS](../.github/CODEOWNERS), PR #10 | 경로별 책임과 지정 변경을 Git으로 관리 |
| 기존 취약점 예외 승인 | [예외 목록](../.github/pip-audit-ignore.txt), PR #10 | 목록의 검토일·사유·재검토 조건 및 도입 PR |
| 취약점 수정 이력 | PR #18·#24, 의존성 lock 변경 및 CI 결과 | PR·커밋·재검사 실행을 조치 기록으로 사용 |

근거 PR: [#10](https://github.com/MotifTechnologies/motif-agent-tracer-v2/pull/10),
[#18](https://github.com/MotifTechnologies/motif-agent-tracer-v2/pull/18),
[#24](https://github.com/MotifTechnologies/motif-agent-tracer-v2/pull/24),
[#28](https://github.com/MotifTechnologies/motif-agent-tracer-v2/pull/28).

## 증빙 보관

| 종류 | 보관 기준 | 확인된 일자 |
| --- | --- | --- |
| 이 폴더, 정책 코드, 고지문 | Git 이력으로 관리 | 문서 작성 2026-10-14 |
| 승인·예외·조치 기록 | GitHub PR·리뷰·커밋을 원본으로 관리 | 위 PR 링크 참조 |
| 최신 main SBOM artifact | 생성 후 90일 보관 | 생성 2026-10-12 09:42:51 UTC / 만료 2027-01-10 09:41:58 UTC |
| 주간 재점검 SBOM artifact | 생성 후 90일 보관 | 생성 2026-10-12 03:14:15 UTC / 만료 2027-01-10 03:13:11 UTC |
| Actions 실행·취약점 스캔 로그 | 보관 기간 확인 대상 | Actions 설정에서 확인 |

[최신 main 실행](https://github.com/MotifTechnologies/motif-agent-tracer-v2/actions/runs/38231561759),
[정기 실행](https://github.com/MotifTechnologies/motif-agent-tracer-v2/actions/runs/38198888339).
장기 보관할 증빙은 산출물별 만료일 전에 보존한다.

## 적용 범위

본 저장소의 OSS 관리 문서와 Git 승인 이력을 대상으로 한다.

## 문서 검수 결과

확인일: 2026-10-16 · 내용 대조: Codex.
문서와 원본 근거의 대조 결과를 기록한다.

- [x] 기존 승인 PR #10·#18·#24·#28의 승인·병합 기록을 확인하고, 정책 승인본에 기재된 승인자·일자·대상 커밋을 대조했다.
- [x] 선정 제외 규칙을 현행 검사 코드·검토 근거와 대조했고, 적용 규칙과 실제 제외 사례를 구분했다.
- [x] RACI에 사용자 선택인 PR별 담당·승인자 지정 방식을 반영하고, CODEOWNERS 및 10개 업무의 역할·증빙 기준을 확인했다.
- [x] Git/PR 기록과 CI artifact의 보관 방식을 구분하고, 90일 보관·생성일·실제 만료일 및 장기 보존 시의 운영 기준을 문서화했다.

개별 업무의 담당자 지정·승인·증빙 보존 수행은 [RACI의 운영 기준](raci.md#개별-업무에-적용할-확인-기준)에 따라
해당 PR·이슈에 기록한다.

# DATA_BUILDER

시드 데이터 준비 도구. **agent-tracer 패키지와 분리**되어 있다 — 패키지는 에이전트를
실행하고 궤적을 기록하는 것이 목적이고, 여기 있는 코드는 그 입력이 될 태스크 풀을
외부 코퍼스에서 골라내는 일회성 큐레이션 도구다. 패키지 의존성에 영향을 주지 않도록
PEP 723 인라인 메타데이터를 쓰는 독립 스크립트로 작성한다.

## build_swerebench_seeds.py — 코딩 도메인 시드

[SWE-rebench](https://huggingface.co/datasets/nebius/SWE-rebench) `filtered` split
(6,542건, 사전빌드 Docker 이미지 전량 보유)에서 시드를 선별한다.

```bash
uv run DATA_BUILDER/build_swerebench_seeds.py --limit 600 --per-repo 5
# -> data/seeds/swerebench_coding.jsonl
# -> data/seeds/swerebench_coding.manifest.json
```

출력은 `agent_tracer.datasets.swebench_local` 로더가 그대로 읽는다.

### 필터 4단계와 근거

| 단계 | 기준 | 근거 |
|---|---|---|
| 검증 가능성 | Docker 이미지 + FAIL_TO_PASS 필수 | 모든 시드가 테스트 실행으로 채점 가능해야 함 |
| 라이선스 | 허용 라이선스만 (MIT/Apache/BSD/ISC/Unlicense/CC0/Zope/PostgreSQL/AFL) | 생성 데이터셋을 Apache 2.0으로 공개하며, 궤적에 리포 코드가 포함되므로 출처가 명확해야 함 |
| 평가 오염 차단 | SWE-bench Verified/Lite 리포 제외 | 해당 벤치마크는 held-out 평가셋으로 예약 |
| 다양성 | 리포당 상한 (기본 5) | 소수 대형 리포가 궤적 분포를 지배하는 것 방지 |

**거부 라이선스**: GPL/LGPL/AGPL, MPL(약한 카피레프트), BSD-4-Clause(광고 조항),
라이선스 불명(null). 실측상 SWE-rebench filtered에 GPL 계열은 0건이다.

**정렬**: 최신 이슈 우선. 오래된 이슈일수록 teacher 모델이 사전학습에서 이미 본
수정일 가능성이 높아, 실제 디버깅이 아닌 암기 재현 궤적이 나올 위험이 있다.

### 기본 설정 실행 결과 (2026-08 기준)

- **600건 / 329개 리포**, 이슈 생성일 2024-09 ~ 2025-04
- 라이선스: MIT 282, Apache 2.0 134, BSD-3 122, 기타 BSD/ISC/Unlicense 62
- 드랍: 리포 상한 182, 평가 리포 겹침 25, 라이선스 불명 13, MPL 2, 미인식 1

### 컴플라이언스

매니페스트(`*.manifest.json`)에 소스 데이터셋·필터 조건·드랍 사유·라이선스 분포·리포
분포를 기록한다. 공개 데이터셋의 라이선스 계보 증빙 자료로 사용한다. 시드 각 행은
`license_name`·`source_dataset`·`repo`를 보존하므로, 생성된 궤적 레코드에 출처
라이선스를 행 단위로 표기할 수 있다.

### 재현

생성물(`data/seeds/*.jsonl`)은 13MB 규모라 git에 커밋하지 않는다(`.gitignore` 처리).
매니페스트만 추적하며, 시드가 필요하면 위 명령으로 재생성한다. SWE-rebench는 월간
갱신되므로 재생성 시 결과가 달라질 수 있다 — 매니페스트의 건수·날짜 범위로 대조할 것.

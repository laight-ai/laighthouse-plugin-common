# laighthouse-plugin-common

세 라이트하우스 플러그인이 함께 쓰는 파일의 원본을 둡니다.

| 플러그인 레포 | 플러그인 폴더 |
|---|---|
| laighthouse-plugin | `plugins/laighthouse-analytics-prod`, `laighthouse-analytics-gpt`(훅만) |
| laighthouse-plugin-agency | `plugins/laighthouse-agency` |
| laighthouse-plugin-external | 레포 루트(`gpt/`는 `gpt/sync_from_claude.py`가 루트에서 다시 만든다) |

플러그인은 설치될 때 자기 폴더만 복사되고, Cowork는 스킬 폴더를 하나씩 따로 올립니다. 그래서 공통 파일은
각 플러그인 안에 사본으로 들어가야 합니다. 이 레포가 원본이고, 플러그인 쪽 사본은 손으로 고치지 않습니다.

## 들어 있는 것

| 경로 | 쓰는 플러그인 |
|---|---|
| `shared/assets/external_context/` — 외부 요인 보고서 집계·HTML 킷 | 세 플러그인 |
| `skills/naver-blog`·`naver-news`·`naver-search`·`weather-impact` | 세 플러그인 |
| `skills/nextmonth-budget-planning` | 세 플러그인 |
| `hooks/save_responses.py`, `hooks/capture_ad_performance.py` | 세 플러그인 |
| `skills/overall-summary`, `skills/overall-summary-*/SKILL.md` | agency·external |
| `shared/references/mcp-tools.md`, `shared/references/pivot-table.md` | agency·external(analytics의 mcp-tools.md는 내용이 달라 따로 둡니다) |

플러그인이 어느 파일을 가져가는지는 각 플러그인 레포의 `common.json`이 정합니다.

### 플러그인마다 다른 값

- **SKILL.md의 `metadata.version`:** 플러그인마다 자기 릴리스 버전을 씁니다. `sync.py`는 플러그인 사본의
  `version:` 줄을 그대로 둡니다. 이 레포의 값(`0.0.0`)은 스킬을 처음 가져갈 때만 들어가므로, 그때 플러그인 버전으로 고칩니다.
- **`capture_ad_performance.py`:** 동작 차이는 `hooks/hooks.json`의 명령 인자로 고릅니다.
  - `--any-group-by` — group_by가 있으면 차원과 관계없이 캡처합니다(종합 리포트용, agency·external).
    없으면 캠페인·광고그룹·광고 차원이 있을 때만 캡처합니다(analytics).
  - `--short-stub` — 스텁을 차원·지표 이름만으로 짧게 씁니다(prepare.py가 저장 응답을 읽는 플러그인, agency·external).
- **저장 훅 대상 도구:** `save_responses.py`는 도구를 가리지 않습니다. 플러그인의 `hooks/hooks.json` matcher가 정합니다.

## 고치는 순서

1. 이 레포에서 고치고 테스트를 돌립니다: `python3 -m pytest tests`
2. 플러그인 레포에서 배포 전 확인을 합니다: `python3 ../laighthouse-plugin-common/sync.py --dev`
   (태그 대신 이 레포의 작업 중인 파일로 사본을 맞춥니다)
3. 이 레포에 커밋하고 태그를 붙입니다: `git tag v0.2.0`
4. 플러그인 레포마다 `common.json`의 `version`을 새 태그로 바꾸고 사본을 맞춥니다.

   ```sh
   python3 ../laighthouse-plugin-common/sync.py   # common.json의 version 태그로 사본을 맞춘다
   python3 scripts/bundle_skills.py               # 스킬 폴더 안 사본까지 맞춘다
   ```

   external은 이어서 `python3 gpt/sync_from_claude.py`로 GPT판도 맞춥니다.
5. 원본·사본·`common.json`을 함께 커밋합니다.

`sync.py --check`는 사본이 `common.json`의 태그와 같은지만 보고, 어긋나면 목록을 내고 1로 끝납니다.
플러그인 레포의 CI가 PR마다 이 검사를 돌립니다.

## 테스트

`tests/`는 external_context 자체 검사, capture 훅, `sync.py` 검사입니다. 수치 회귀 비교는 따로 실행합니다:
`python3 tests/regress_external_context.py --responses <응답 폴더> --baseline <기준 폴더>`
(기준은 같은 명령에 `--write`를 붙여 먼저 만듭니다).

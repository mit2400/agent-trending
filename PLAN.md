# agent-trending — 구현 계획

에이전트 생태계(Claude Code, Codex, Cursor, Gemini CLI, MCP, skills, plugins, marketplaces …)의
GitHub 레포를 매일 수집해 **star 상승폭 기준 트렌딩**을 보여주는 GitHub Pages 사이트.

## 확정된 결정

| 항목 | 결정 |
|---|---|
| 추적 단위 | GitHub 레포. skill/mcp/plugin 등은 **태그** |
| 도메인 | 에이전트 생태계 전반. `scope` 태그(general / claude-code / codex …)로 구분, 자동 판정 불가 시 수동 |
| 큐레이션 | awesome 리스트를 **소스로 계속 재파싱**하여 레지스트리 자동 갱신 |
| 갱신 | 매일 08:30 KST 수집 → JSON 커밋/푸시 → 정적 페이지가 JSON을 읽음 (별도 배포 파이프라인 없음) |
| 지표 | ① 절대 상승폭 ② 상승률 ③ 신규 진입. 윈도우 7일, 기록이 부족하면 **가장 오래된 기록과 diff** |
| 페이지 | 정적 HTML + vanilla JS (빌드 단계 없음). README는 스크린샷 + 소개 + 링크 |
| 스택 | Python 3.12 (uv), 의존성 최소: `httpx`, `jsonschema`, `selectolax`(trending HTML) |

## 레포 구조

```
.github/workflows/daily.yml     # cron: '30 23 * * *' (UTC) = 08:30 KST
tf/                             # Python 패키지
  sources.py    # awesome 리스트 README 파싱 → registry 갱신
  discover.py   # Search API(topic 쿼리) + Trending 스크래핑 → candidates
  collect.py    # GraphQL 100개 단위 배치로 star 수집 → snapshot
  build.py      # snapshots → trending.json
  gate.py       # 검증. 실패 시 exit 1
  schemas/      # JSON Schema
data/
  sources.json      # 큐레이션 소스 목록 + 섹션→태그 매핑 규칙
  overrides.json    # 수동 태그, blocklist, 강제 포함
  registry.json     # 추적 대상 레포 (key = GraphQL node ID)
  candidates.json   # discovery 결과, 승격 대기
  snapshots/2026-11-20.json   # { "<nodeId>": stars } 만 저장
  trending.json     # 페이지용 산출물 (meta + 레포별 지표 + sparkline)
index.html  assets/app.js  assets/style.css  .nojekyll
README.md
```

Pages는 `main` 브랜치 루트에서 서빙하고, 페이지는 `./data/trending.json`을 fetch한다.

## 데이터 모델

**registry.json** (레포 1건)
```json
{ "id": "R_kgDO...", "name": "owner/repo", "description": "...",
  "tags": { "type": ["mcp"], "scope": ["general"] },
  "sources": ["punkpeye/awesome-mcp-servers"], "added": "2026-11-20",
  "archived": false }
```
- key는 node ID. 수집할 때마다 `name`을 갱신해서 rename/transfer에도 이력이 이어지게 한다.
- 태그 우선순위: `overrides.json` > 소스 섹션 헤더 매핑 > topic/파일 휴리스틱(`SKILL.md`, `.claude-plugin/marketplace.json`, topic `mcp-server`).

**snapshots/YYYY-MM-DD.json**
```json
{ "date": "2026-11-20", "collected_at": "...Z", "stars": { "R_kgDO...": 1234 } }
```

**trending.json**
```json
{ "generated_at": "...", "date": "2026-11-20", "window_max": 7,
  "repos": [ { "id": "...", "name": "...", "stars": 1234,
               "delta": 210, "rate": 0.205, "window_days": 7,
               "spark": [1024, 1050, ...], "is_new": false, "tags": {...} } ] }
```

## 지표 계산 규칙

- baseline = 레포별로 `today - 7일` 스냅샷. 없으면 **해당 레포가 기록된 가장 오래된 스냅샷**.
- `window_days`를 레포마다 기록하고 페이지에 `+210 (7d)` / `+40 (2d)`처럼 표시한다.
- 오늘 처음 기록된 레포는 delta 없음 → "신규 진입" 섹션에만 노출.
- 상승률 탭은 `baseline stars ≥ 100`인 레포만 대상으로 한다 (작은 레포 노이즈 제거, 설정 가능).
- 신규 진입 = 최근 7일 안에 registry에 추가된 레포, 상승폭 순.

## 수집 범위 및 노이즈 관리

- 큐레이션 소스에서 온 레포는 자동 포함. 단 `stars ≥ 10` 하한(설정 가능).
- discovery 결과는 `candidates`로 들어가고, `stars ≥ 50`이며 blocklist에 없으면 자동 승격.
- archived 레포나 삭제된 레포는 `archived: true`로 표시하고 수집 대상에서 제외한다 (이력은 유지).
- 초기 소스 후보 (M1에서 실제 존재와 형식 확인): `shanraisshan/claude-code-best-practice`,
  `hesreallyhim/awesome-claude-code`, `punkpeye/awesome-mcp-servers`, `wong2/awesome-mcp-servers`,
  `anthropics/skills`, `travisvn/awesome-claude-skills`, `e2b-dev/awesome-ai-agents` 등.

## Daily workflow

```
checkout → uv sync
→ sources.py (README 재파싱)  → discover.py → collect.py → build.py
→ gate.py ──pass──> git commit "data: 2026-11-20" && push
          └─fail──> 커밋하지 않음 + gh issue create (라벨 data-gate)
```
- `permissions: contents: write, issues: write`. 기본 `GITHUB_TOKEN` 사용.
- `concurrency` 그룹을 지정해 중복 실행을 막는다. `workflow_dispatch`로 수동 실행도 허용.

**Gate 검사 항목**
1. 모든 data JSON이 스키마 검증 통과
2. 변경 파일이 `data/` 아래에만 있음
3. 오늘 스냅샷의 레포 수 ≥ 어제의 95% (API 장애 감지)
4. star가 0이 되었거나 50% 이상 급감한 레포가 전체의 1%를 넘으면 실패 (그 이하이면 경고만)
5. 같은 날짜의 스냅샷이 이미 커밋되어 있으면 덮어쓰지 않음
6. `trending.json`이 오늘 날짜이고, 레포 수가 0보다 큼

## 페이지 (정적)

- 탭: **Top Δ** / **Top %** / **New**
- 필터: type(skill/mcp/plugin/marketplace/tool/list), scope(general/claude-code/…), 검색
- 행: 순위, 레포명(링크), 설명, 태그, 현재 star, Δ와 윈도우, 7일 sparkline (인라인 SVG)
- 상단에 마지막 업데이트 시각과 "N일치 데이터 기반" 표시
- 다크/라이트 모드, 모바일 대응

## 마일스톤

데이터는 날짜가 지나야 쌓이므로 **수집 파이프라인을 가장 먼저** 가동한다.

- **M0** 레포 생성, Pages 설정(main 루트), `.nojekyll`. 봇 푸시 후 Pages가 재빌드되는지 확인한다.
  재빌드되지 않으면 페이지가 raw.githubusercontent URL에서 fetch하도록 바꾼다.
- **M1** `sources.py`로 초기 registry를 생성하고, 결과를 사람이 한 번 훑어본다.
- **M2** `collect.py` + `gate.py` + daily workflow 가동 → **이날부터 데이터 축적 시작**
- **M3** `build.py` (윈도우 규칙, 신규 진입)
- **M4** 페이지
- **M5** `discover.py` (Search API topic 쿼리, Trending 스크래핑, 자동 승격)
- **M6** README(스크린샷, 소개), 수동 태깅 정리

## 진행 상황

- [x] **M0** 레포 생성(`mit2400/agent-trending`), Pages(main 루트). 봇(`GITHUB_TOKEN`) 푸시로 Pages가 재빌드되는 것 확인함
- [x] **M1** 소스 17개 파싱 → 레지스트리 3,938개 (star 10개 미만 3,311개, fork/archived 143개, 없는 레포 90개 제외)
- [x] **M2** `tf.collect` / `tf.gate` / `daily.yml` 가동. 첫 스냅샷 `2026-11-20`
  - 소스 동기화는 **월요일(KST)에만** 실행(약 2.5분). 매일 수집은 node ID로 star만 조회(약 1.5분)
  - 레지스트리 내용이 바뀌지 않으면 커밋하지 않음
- [x] **M3** `tf.build` → `trending.json` (7일 윈도우, 짧으면 가장 오래된 스냅샷 기준, 상승률, 신규)
- [x] **M4** 정적 페이지 v1 (podium, 탭, 필터, sparkline) + 고정 OG 카드(`tools/make_og.py`)
- [x] **M5** `tf.discover`: **5k★ 이상만** 자동 추가 (+402개). Trending(daily)은 매일, topic 검색은 월요일에만
- [x] 파일 기반 태깅 `tf.probe`: `SKILL.md`/`skills/`→skill, `.claude-plugin/plugin.json`·`gemini-extension.json`→plugin,
      `marketplace.json`은 plugin 3개 이상이면 marketplace(아니면 plugin)
- [x] Pages를 Actions 배포로 전환. `trending.json`은 커밋하지 않음 (git 증가량 약 10MB/년)
- [x] RSS(`feed.xml`, 최근 14일 일일 Top 10) + 주간 다이제스트(`data/digests/`, 월요일, GitHub Release로 발행해서 메일 알림)
- [ ] README (스크린샷, 소개)

### 운영 메모
- 소스 추가/제외: `data/sources.json` (`discovery`: 자동 발견 topic과 최소 star). 태그 수동 지정, 강제 포함, 차단: `data/overrides.json`
- 다이제스트를 메일로 받기: 레포 Watch → Custom → Releases
- 수동 실행: Actions → daily → Run workflow (`sync_sources` 체크 시 레지스트리 재동기화)
- `astral-sh/setup-uv`는 메이저 태그가 없으므로 정확한 버전으로 고정할 것

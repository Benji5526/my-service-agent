# Qdrant MCP 서버 실험 정리

룰북 5번 "남이 만든 MCP 서버(Qdrant RAG) 붙이기"의 결과 정리다. 서버는 `uvx mcp-server-qdrant`(공식), 저장소는 `:memory:`다.

## 이 정리가 다루는 것과 아닌 것

| 구분 | 상태 |
|---|---|
| 서버가 노출하는 도구와 인자 스키마 | **확인함** (MCP 클라이언트로 직접 조회) |
| `qdrant-store`로 저장, `qdrant-find`로 검색한 동작 | **확인함** (같은 방식으로 직접 호출) |
| 모델(Claude Code)이 어떤 도구를 고르고 어떤 인자를 채우는가 | **관찰함** (직접 실행한 세션 기록, 아래 "모델 관찰") |
| `/mcp`에서 reconnect | **함** (`Reconnected to qdrant.`) |
| `/mcp`의 View tools 화면 | **하지 않음** (같은 내용을 MCP 클라이언트로 직접 조회해 대신함) |

처음에는 Claude 계정 로그인이 만료되어 모델 호출이 막혀 있었다(`claude -p`: `OAuth session expired`, 직접 연 `claude`: `Login expired`). 이 환경에서 띄운 `claude -p`의 시스템 정보에서는 `qdrant` 서버 상태가 `failed`였는데, 서버를 따로 띄우면 정상 동작하므로 첫 실행에 임베딩 모델을 내려받는 시간 때문일 가능성이 있다(추정, 확인하지 않음). 재로그인 후 직접 연 `claude`에서는 서버 연결과 호출이 모두 정상이었다.

## 모델 관찰 (Claude Code, 고친 `.mcp.json`)

세션 기록에서 뽑은 도구 호출 원문은 `model_observation_raw.txt`에 있다. 입력은 룰북 예시 문장 그대로다.

| # | 도구 | 인자 | 결과 |
|---|---|---|---|
| 1 | `ToolSearch` | `select:mcp__qdrant__qdrant-store,mcp__qdrant__qdrant-find` | 두 도구의 정의를 불러옴 |
| 2~4 | `qdrant-store` | `information`: "환불은 구매 후 7일 이내에 가능하다." / "배송은 영업일 기준 2일이 걸린다." / "회원 등급은 매월 1일에 갱신된다." (문장마다 1회, 거의 동시에 호출) | 3건 모두 `Remembered: … in collection policies` |
| 5 | `qdrant-find` | `query`: "환불 기한이 어떻게 돼?" | 3개를 반환: ① 환불 7일 ② 배송 2일 ③ 회원 등급 |

관찰
- **저장은 문장당 1회씩 3번 호출했다.** 세 문장을 한 번에 합쳐 저장하지 않았다.
- **인자는 필수인 `information`/`query`만 채웠다.** `metadata`는 넣지 않아 검색 결과의 `<metadata>`가 비어 있다. 고친 설정에서는 `collection_name`이 도구 인자에서 빠져 있어, 모델이 컬렉션 이름을 채울 필요가 없었다. (룰북 원본 설정에서는 이 값을 모델이 채워야 한다. 이 경우는 실행해 보지 못했다.)
- **검색어는 사용자가 준 문장을 그대로 썼다.** 모델이 질의를 다시 쓰거나 키워드로 줄이지 않았다.
- **도구 호출 오류는 없었다.** 호출 5회 모두 `is_error`가 없었고, 저장 → 검색 순서도 맞았다.
- **검색 순위는 직접 호출 때와 같았다.** 고친 설정으로 서버를 직접 호출했을 때의 순서(환불, 배송, 회원 등급)와 일치한다.
- **최종 답의 서술은 도구 결과와 맞았다.** 모델은 "유사도 점수를 보여 주지 않는다", "문장이 3개뿐이라 관련 없는 문장도 모두 나왔다"고 답했고, 두 말 모두 반환 원문(점수 필드 없음, 3개 전부 반환)과 일치한다.

한계: 1회 실행이고, 도구 호출이 모두 성공한 정상 경로다. 모델이 도구를 잘못 고르거나 인자를 잘못 채우는 경계 사례(예: 저장하라고 하지 않았는데 저장, 컬렉션 이름 추측)는 시험하지 않았다.

## 발견 1 — 룰북 JSON의 환경변수 이름이 서버가 읽는 이름과 다르다

| 룰북 `.mcp.json`의 키 | 서버가 읽는 키 | 룰북 키를 쓰면 |
|---|---|---|
| `QDRANT_COLLECTION` | `COLLECTION_NAME` | 무시됨 |
| `EMBEDDER_PROVIDER` | `EMBEDDING_PROVIDER` | 무시됨 |
| `FASTEMBED_MODEL` | `EMBEDDING_MODEL` | 무시됨 → 기본 모델 사용 |
| `QDRANT_URL` | `QDRANT_URL` | 같음 |

근거: 룰북 설정으로 서버를 띄웠을 때 내려받은 모델은 `all-MiniLM-L6-v2`(기본값)였고, 고친 설정에서는 `bge-small-en-v1.5`가 내려받아졌다(`fastembed_cache`에 둘 다 있음). 즉 룰북 설정에서는 의도한 `bge-small-en-v1.5`가 쓰이지 않았다.

## 발견 2 — 컬렉션 이름이 도구 인자로 노출되는지가 설정에 따라 달라진다

| 설정 | `qdrant-store` 필수 인자 | `qdrant-find` 필수 인자 |
|---|---|---|
| 룰북 그대로 | `information`, **`collection_name`** | `query`, **`collection_name`** |
| 고친 설정 | `information` | `query` |

`COLLECTION_NAME`이 설정되면 서버가 `collection_name` 인자를 도구 정의에서 숨긴다. 룰북 설정에서는 이 값이 무시되어 모델이 컬렉션 이름까지 채워야 한다. 도구 정의가 바뀌면 모델이 채울 인자도 바뀐다는 점에서, 룰북 2·3번의 "도구 설명은 모델이 읽는 지시다"와 같은 이야기다.

## 도구 정의 (서버 반환 원문 요약)

| 도구 | description | 인자 |
|---|---|---|
| `qdrant-store` | "Keep the memory for later use, when you are asked to remember something." | `information`(필수), `metadata`(선택, 임의 JSON), 설정에 따라 `collection_name` |
| `qdrant-find` | "Look up memories in Qdrant. Use this tool when you need to: Find memories by their content / Access memories for further analysis / Get some personal information about the user" | `query`(필수), 설정에 따라 `collection_name` |

도구는 2개이며 룰북의 "View tools에 2개"와 일치한다. 한 가지 짚을 점: `qdrant-find`의 설명은 "사용자에 대한 개인 정보를 찾을 때"까지 포함해 쓰는 때가 넓고, "안 쓰는 때"는 적혀 있지 않다. 이 과제의 룰북 기준("쓰는 때 / 안 쓰는 때 / 실패 뒤 행동")으로 보면 계약이 비어 있는 도구다.

## 저장과 검색 결과 (룰북 입력 문장을 직접 호출)

세 문장을 저장했고 모두 `Remembered: ... in collection policies`로 성공했다. 검색은 같은 3개를 유사도 순서로 돌려주며 점수는 반환하지 않는다.

| 질의 | 룰북 설정 (기본 모델 MiniLM) | 고친 설정 (bge-small) |
|---|---|---|
| "환불 기한이 어떻게 돼?" | 1) 환불 7일 2) 회원 등급 3) 배송 | 1) 환불 7일 2) 배송 3) 회원 등급 |
| "배송은 며칠 걸려?" | 1) **회원 등급** 2) 배송 3) 환불 | 1) **배송** 2) 회원 등급 3) 환불 |

관찰
- 두 설정 모두 "환불 기한" 질의에서는 정답 문장(환불 7일)이 1위다.
- "배송" 질의에서는 룰북 설정이 오답(회원 등급)을 1위로, 고친 설정이 정답을 1위로 돌려줬다.
- 3개 중 몇 개나 반환했는지에 한도가 있는지는 확인하지 않았다. 저장한 3개가 전부 돌아왔을 뿐이다.

## 한계

- 문서 3개, 질의 2개, 각 1회 실행이다. 순위 차이는 경향이지 모델 성능 비교가 아니다.
- 두 모델 모두 영어용 임베딩 모델이다. 한국어 문장에서 순위가 흔들리는 것은 이 때문일 수 있으나 이번 실험으로 원인을 분리하지는 못했다.
- `:memory:` 저장소라 서버를 끄면 저장한 문장이 사라진다.

## 재현

```bash
cd my-agent/qdrant-lab
uv run --with mcp python probe_server.py rulebook    # 룰북 .mcp.json의 env 그대로
uv run --with mcp python probe_server.py corrected   # 서버가 읽는 이름으로 고친 env
```

Claude Code로 직접 확인하려면 이 폴더에서 `claude`를 실행한다. `.mcp.json`은 고친 설정이고, 룰북 원본 설정은 `mcp.rulebook.json`에 보관했다(Claude Code가 읽지 않도록 이름에서 앞의 점을 뺐다).

## 이 폴더의 파일

| 파일 | 내용 |
|---|---|
| `qdrant-experiment.md` | 이 문서 |
| `.mcp.json` | 고친 설정 (서버가 읽는 환경변수 이름 사용) |
| `mcp.rulebook.json` | 룰북 원본 설정 |
| `probe_server.py` | 서버를 MCP 클라이언트로 직접 호출해 도구 정의와 저장·검색을 기록하는 스크립트 |
| `probe_rulebook.txt`, `probe_corrected.txt` | 위 스크립트의 두 설정별 출력 원문 |
| `model_observation_raw.txt` | Claude Code 세션에서 뽑은 도구 호출 원문 |

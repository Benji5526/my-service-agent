# Qdrant MCP 서버 실험 정리

룰북 5번 "남이 만든 MCP 서버(Qdrant RAG) 붙이기"의 결과 정리다. 서버는 `uvx mcp-server-qdrant`(공식), 저장소는 `:memory:`다.

## 이 정리가 다루는 것과 아닌 것

| 구분 | 상태 |
|---|---|
| 서버가 노출하는 도구와 인자 스키마 | **확인함** (MCP 클라이언트로 직접 조회) |
| `qdrant-store`로 저장, `qdrant-find`로 검색한 동작 | **확인함** (같은 방식으로 직접 호출) |
| 모델(Claude Code)이 어떤 도구를 고르고 어떤 인자를 채우는가 | **관찰함** (직접 실행한 세션 기록, 아래 "모델 관찰 (Claude Code)") |
| 모델(opencode)이 같은 일을 하는 모습, 룰북 원본 설정과 고친 설정 각각 | **관찰함** (`opencode run`, 아래 "모델 관찰 (opencode)") |
| `/mcp`에서 reconnect (Claude Code) | **함** (`Reconnected to qdrant.`) |
| `/mcps`에서 qdrant 확인 (opencode) | **함** (`opencode mcp list`: `qdrant connected`) |
| `/mcp`의 View tools 화면 | **하지 않음** (같은 내용을 MCP 클라이언트로 직접 조회해 대신함) |

처음에는 Claude 계정 로그인이 만료되어 모델 호출이 막혀 있었다(`claude -p`: `OAuth session expired`, 직접 연 `claude`: `Login expired`). 이 환경에서 띄운 `claude -p`의 시스템 정보에서는 `qdrant` 서버 상태가 `failed`였는데, 서버를 따로 띄우면 정상 동작하므로 첫 실행에 임베딩 모델을 내려받는 시간 때문일 가능성이 있다(추정, 확인하지 않음). 재로그인 후 직접 연 `claude`에서는 서버 연결과 호출이 모두 정상이었다.

## 모델 관찰 (Claude Code, 고친 `.mcp.json`)

(opencode 결과는 이 절 다음의 "모델 관찰 (opencode)"에 있다. 모델이 다르므로 두 결과의 차이를 도구나 설정 탓으로만 돌릴 수 없다.)

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

한계: 1회 실행이고, 도구 호출이 모두 성공한 정상 경로다. 룰북 원본 설정에서 Claude Code가 어떻게 하는지는 시험하지 못했다(opencode로는 시험함, 아래).

## 모델 관찰 (opencode)

opencode 1.18.30, 모델은 로그인 없이 쓸 수 있는 무료 모델 `opencode/big-pickle`이다. `opencode run --format json`으로 룰북 예시 입력을 그대로 보냈다. 호출 원문은 `opencode_observation_raw.txt`(고친 설정)와 `opencode_observation_rulebook_raw.txt`(룰북 원본 설정)에 있다. 설정 파일은 룰북 `opencode.json`을 고친 `opencode.json`과 원본을 보관한 `opencode-rulebook.json`이다. 도구 이름은 opencode에서 `qdrant_qdrant-store`, `qdrant_qdrant-find`로 붙는다.

| 구분 | 고친 설정 | 룰북 원본 설정 |
|---|---|---|
| 서버 연결 | `opencode mcp list`: connected | 같음: connected |
| `qdrant-store` 호출 | 문장마다 1회, 3번 | 문장마다 1회, 3번 |
| `qdrant-store`의 `metadata` | **모델이 지어 넣음**: `{"category": "policy", "topic": "refund"}` 등 | 넣지 않음 |
| `collection_name` | 인자에 없음 | 모델이 **`"default"`로 채움** (룰북이 의도한 `policies`가 아님) |
| 저장된 컬렉션 | `policies` | `default` |
| `qdrant-find`의 `query` | 사용자 문장 그대로 | 사용자 문장 그대로 |
| 검색 순위 | 환불 → 배송 → 회원 등급 | 환불 → 회원 등급 → 배송 |
| 오류 | 없음 | 없음 |

관찰
- **룰북 원본 설정에서 모델이 컬렉션 이름을 지어냈다.** 도구 정의가 `collection_name`을 필수로 요구하는데 값을 알려 주는 곳이 없어서, 모델이 `"default"`라고 채웠다. 서버는 이를 거부하지 않고 `default` 컬렉션을 만들어 저장했다. 호출은 성공이지만 의도(`policies`)와 다른 곳에 저장된 것이다. 환경변수 이름 오류(발견 1) 때문에 `COLLECTION_NAME`이 무시된 결과가 모델의 추측으로 이어졌다.
- **고친 설정에서는 모델이 `metadata`를 요청받지 않았는데 채웠다.** 같은 입력에서 Claude Code는 `metadata`를 비워 두었다. 도구 설명이 "Any json is accepted"라 어떤 값이든 허용되기 때문에, 모델에 따라 채우는 정도가 달라진다.
- **최종 답에 모델의 생각 표시가 섞여 나왔다.** 고친 설정 실행의 답변 텍스트에 영어 계획 문장과 `</think>` 태그가 그대로 출력됐다. 도구가 아니라 이 무료 모델의 출력 형식 문제로 보이며, 도구 호출 결과에는 영향이 없었다.
- **검색 순위는 설정마다 다르게 나왔다.** 고친 설정은 직접 호출 때와 같은 순서였고, 룰북 원본 설정은 두 번째와 세 번째가 바뀌었다(기본 임베딩 모델 `all-MiniLM-L6-v2`를 쓰기 때문으로 추정된다).
- **"가장 유사" 판단은 순서만으로 한 것이다.** 모델은 첫 항목을 "가장 유사/관련도 최상위"라고 답했지만 도구는 점수를 주지 않는다. 순서가 유사도 순이라고 가정한 서술이다.

실행 중 겪은 일
- **룰북 원본 설정의 첫 실행이 280초 동안 출력 없이 시간 초과(exit 124)로 끝났다.** 같은 입력으로 다시 실행하니 약 12초 만에 정상 완료됐고, 그 사이 다른 점은 로그를 켠 것뿐이다. 첫 실행의 원인은 알 수 없다(무료 모델 응답 지연 등 일시적 문제로 추정, 확인하지 못함). 그래서 위 표는 두 번째 실행의 기록이다.
- 같은 설정에서 짧은 요청("`qdrant-find`로 환불을 검색해 줘")을 한 번 시험했을 때, 모델이 컬렉션 이름을 알아내려고 `curl http://localhost:6333/collections`를 실행하려 하고 홈 설정 폴더를 읽으려 했다(후자는 권한 없어 자동 거절됨). 이 시험은 룰북 입력이 아니라 본 표에 넣지 않았다. 필수 인자의 값을 알 수 없을 때 모델이 도구 밖으로 나가 탐색하려는 경향의 단서로만 적는다.

한계: 모델 1종(`big-pickle`), 설정당 1회 실행이다. Claude Code와 opencode의 차이는 모델 차이를 분리하지 못한다.

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

서버 직접 호출 (LLM 없음):

```bash
cd my-agent/qdrant-lab
uv run --with mcp python probe_server.py rulebook    # 룰북 .mcp.json의 env 그대로
uv run --with mcp python probe_server.py corrected   # 서버가 읽는 이름으로 고친 env
```

모델로 확인하려면 이 폴더에서 `claude`(Claude Code) 또는 `opencode`를 실행하고 룰북 예시 입력을 넣는다. 이 폴더의 `.mcp.json`과 `opencode.json`은 고친 설정이다. 룰북 원본 설정을 시험하려면 `mcp.rulebook.json`, `opencode-rulebook.json`의 내용을 각각 `.mcp.json`, `opencode.json`으로 바꿔 쓴다(두 파일은 이름에 점을 빼거나 `-rulebook`을 붙여 도구가 읽지 않게 했다).

```bash
opencode mcp list                                   # qdrant connected 확인
opencode run -m opencode/big-pickle --format json "<룰북 예시 입력>"
```

## 이 폴더의 파일

| 파일 | 내용 |
|---|---|
| `qdrant-experiment.md` | 이 문서 |
| `.mcp.json`, `mcp.rulebook.json` | Claude Code용 설정: 고친 것 / 룰북 원본 |
| `opencode.json`, `opencode-rulebook.json` | opencode용 설정: 고친 것 / 룰북 원본 |
| `probe_server.py` | 서버를 MCP 클라이언트로 직접 호출해 도구 정의와 저장·검색을 기록하는 스크립트 |
| `probe_rulebook.txt`, `probe_corrected.txt` | 위 스크립트의 설정별 출력 원문 |
| `model_observation_raw.txt` | Claude Code 세션에서 뽑은 도구 호출 원문 |
| `opencode_observation_raw.txt` | opencode 도구 호출 원문 (고친 설정) |
| `opencode_observation_rulebook_raw.txt` | opencode 도구 호출 원문 (룰북 원본 설정) |

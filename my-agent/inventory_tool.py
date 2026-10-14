"""창고 재고 안내 챗봇 — 도구 호출 실습 (실습 2: 도구 직접 만들어 실행 + 트레이스 남기기)

모델(ollama)은 도구를 실행하지 않고 호출 요청만 만든다.
이 파일의 run_tool()이 하네스 역할을 해서 허용 목록 검사 → 실행 → 결과 재입력을 맡는다.
외부 시스템은 호출하지 않고, 아래 MOCK 데이터를 돌려준다.

사용법:
    python inventory_tool.py "BUSAN-02 창고의 SKU A-17 재고를 알려 줘"
    python inventory_tool.py --desc-variant B "부산 3번 창고의 A-17 재고를 알려 줘"
실행할 때마다 traces/trace-NN.txt가 새로 생긴다(덮어쓰지 않음).
"""
import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

import ollama

MODEL = "qwen3.5:2b"
TRACE_DIR = Path(__file__).parent / "traces"
MAX_TOOL_CALLS = 4  # 하네스의 중단 기준

SYSTEM_PROMPT = (
    "너는 물류센터의 창고 재고 안내 도우미다. "
    "재고 수량은 도구 결과에 있는 값만 말하고, 도구 결과에 없는 내용은 지어내지 않는다."
)

# ---- 가상 데이터 (실제 시스템 아님) ----
ALLOWED_WAREHOUSES = {"BUSAN-01", "BUSAN-02", "SEOUL-01"}
MOCK_STOCK = {
    ("BUSAN-01", "A-17"): 42,
    ("BUSAN-02", "A-17"): 120,
    ("BUSAN-02", "B-03"): 0,
    ("SEOUL-01", "A-17"): 7,
}
USED_CONFIRMATIONS: set[str] = set()

# ---- 도구 정의 (모델이 읽는 지시) ----
GET_INVENTORY_DESC = {
    "A": "창고 재고를 조회한다.",
    "B": (
        "창고 코드와 SKU로 현재 재고 수량을 조회한다(읽기 전용). "
        "warehouse_id는 BUSAN-01, BUSAN-02, SEOUL-01 중 하나여야 한다. "
        "사용자가 '부산 3번'처럼 허용 목록에 없는 창고를 말하면 코드를 추측하지 말고, "
        "도구를 호출하지 말고 허용된 창고 코드를 되물어라. "
        "재고를 바꾸는 요청에는 쓰지 않는다."
    ),
}


def build_tools(desc_variant: str) -> list[dict]:
    return [
        {
            "type": "function",
            "function": {
                "name": "get_inventory",
                "description": GET_INVENTORY_DESC[desc_variant],
                "parameters": {
                    "type": "object",
                    "properties": {
                        "warehouse_id": {
                            "type": "string",
                            "description": "창고 코드. 예: BUSAN-02",
                        },
                        "sku": {"type": "string", "description": "상품 코드. 예: A-17"},
                    },
                    "required": ["warehouse_id", "sku"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "adjust_inventory",
                "description": (
                    "창고 재고 수량을 바꾼다(쓰기). 사람이 승인 화면에서 확인 버튼을 눌러 "
                    "하네스가 발급한 confirmation_id가 있을 때만 호출한다. "
                    "조회 요청에는 쓰지 않는다."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "warehouse_id": {"type": "string"},
                        "sku": {"type": "string"},
                        "new_quantity": {"type": "integer", "minimum": 0},
                        "reason": {"type": "string"},
                        "confirmation_id": {"type": "string"},
                    },
                    "required": [
                        "warehouse_id", "sku", "new_quantity", "reason", "confirmation_id",
                    ],
                },
            },
        },
    ]


# ---- 하네스: 허용 목록 → 인자 검사 → 실행 ----
def run_tool(name: str, args: dict, tool_names: set[str]) -> dict:
    if name not in tool_names:
        return {"error": "TOOL_NOT_ALLOWED"}
    if name == "get_inventory":
        wid, sku = args.get("warehouse_id"), args.get("sku")
        if not wid or not sku:
            return {"error": "INVALID_ARGUMENT"}
        if wid not in ALLOWED_WAREHOUSES:
            return {"error": "WAREHOUSE_NOT_ALLOWED"}
        if (wid, sku) not in MOCK_STOCK:
            return {"error": "SKU_NOT_FOUND"}
        return {
            "warehouse_id": wid, "sku": sku, "quantity": MOCK_STOCK[(wid, sku)],
            "checked_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        }
    if name == "adjust_inventory":
        # 확인 버튼은 사람이 누른다. 이 실습에는 버튼이 없으므로 발급된 id가 없다.
        cid = args.get("confirmation_id")
        if not cid or cid not in USED_CONFIRMATIONS:
            return {"error": "NOT_CONFIRMED"}
        return {"error": "NOT_IMPLEMENTED_IN_LAB"}
    return {"error": "UNKNOWN_TOOL"}


def next_trace_path() -> Path:
    TRACE_DIR.mkdir(exist_ok=True)
    nums = [int(m.group(1)) for p in TRACE_DIR.glob("trace-*.txt")
            if (m := re.match(r"trace-(\d+)\.txt", p.name))]
    return TRACE_DIR / f"trace-{(max(nums) + 1 if nums else 1):02d}.txt"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("prompt")
    ap.add_argument("--desc-variant", choices=["A", "B"], default="A")
    ap.add_argument("--note", default="", help="실험 의도 한 줄")
    ns = ap.parse_args()

    tools = build_tools(ns.desc_variant)
    tool_names = {t["function"]["name"] for t in tools}
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": ns.prompt},
    ]
    log: list[str] = []
    calls = 0
    error_text = None
    final = ""
    try:
        while True:
            resp = ollama.chat(model=MODEL, messages=messages, tools=tools,
                               think=False, options={"temperature": 0})
            msg = resp["message"]
            messages.append(msg)
            tcs = msg.get("tool_calls") or []
            if not tcs:
                final = msg.get("content") or ""
                if not log:
                    log.append("(모델이 도구를 요청하지 않음)")
                break
            for tc in tcs:
                calls += 1
                name, args = tc["function"]["name"], dict(tc["function"]["arguments"])
                if calls > MAX_TOOL_CALLS:
                    log.append(f"[중단] 도구 호출 {MAX_TOOL_CALLS}회 초과")
                    raise StopIteration
                result = run_tool(name, args, tool_names)
                log.append(f"{calls}. {name}({json.dumps(args, ensure_ascii=False)})"
                           f"\n   -> {json.dumps(result, ensure_ascii=False)}")
                messages.append({"role": "tool", "tool_name": name,
                                 "content": json.dumps(result, ensure_ascii=False)})
    except StopIteration:
        final = "(하네스가 중단함)"
    except Exception as e:  # 오류는 그대로 기록한다
        error_text = f"{type(e).__name__}: {e}"

    path = next_trace_path()
    body = f"""== 실행 조건 ==
날짜: {datetime.now().astimezone().isoformat(timespec='seconds')}
모델 / 온도: {MODEL} / 0 (think=False)
시스템 지시 버전: lab-v1
도구 설명 버전: get_inventory desc-{ns.desc_variant}
실험 의도: {ns.note or '-'}

== 요청 ==
{ns.prompt}

== 선택한 도구와 인자, 반환 근거 ==
{chr(10).join(log) if log else '(없음)'}

== 최종 답 ==
{final.strip() or '(없음)'}
"""
    if error_text:
        body += f"\n== 오류(그대로 기록) ==\n{error_text}\n"
    path.write_text(body, encoding="utf-8")
    print(body)
    print(f"[saved] {path}")
    return 1 if error_text else 0


if __name__ == "__main__":
    sys.exit(main())

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
import subprocess
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
    # 룰북 trace 예시 형식: [1] 모델의 요청 → [2] 하네스의 실행 결과 → [3] 결과를 읽은 최종 답
    step1 = step2 = step3 = "(실행 전에 오류가 나서 기록 없음)"
    error_text = None
    try:
        r1 = ollama.chat(model=MODEL, messages=messages, tools=tools,
                         think=False, options={"temperature": 0})
        m1 = r1["message"]
        messages.append(m1)
        requests = [(tc["function"]["name"], dict(tc["function"]["arguments"]))
                    for tc in (m1.get("tool_calls") or [])]
        step1 = repr(requests)

        if not requests:
            step2 = "(실행한 도구 없음 — 모델이 도구를 요청하지 않음)"
            step3 = (m1.get("content") or "").strip() or "(빈 답)"
        else:
            results = []
            for name, args in requests[:MAX_TOOL_CALLS]:
                result = run_tool(name, args, tool_names)
                results.append(result)
                messages.append({"role": "tool", "tool_name": name,
                                 "content": json.dumps(result, ensure_ascii=False)})
            step2 = json.dumps(results[0] if len(results) == 1 else results,
                               ensure_ascii=False)
            if len(requests) > MAX_TOOL_CALLS:
                step2 += f"  (하네스 중단: 도구 요청 {len(requests)}개 중 {MAX_TOOL_CALLS}개만 실행)"
            r2 = ollama.chat(model=MODEL, messages=messages, tools=tools,
                             think=False, options={"temperature": 0})
            m2 = r2["message"]
            step3 = (m2.get("content") or "").strip() or "(빈 답)"
            extra = m2.get("tool_calls") or []
            if extra:
                step3 += f"  (모델이 도구를 추가로 요청했으나 실행하지 않음: " \
                         f"{[(tc['function']['name'], dict(tc['function']['arguments'])) for tc in extra]})"
    except Exception as e:  # 오류는 그대로 기록한다
        error_text = f"{type(e).__name__}: {e}"

    path = next_trace_path()
    command = "python " + subprocess.list2cmdline(sys.argv)
    body = f"""== 실행 조건 ==
날짜: {datetime.now().date().isoformat()}
모델: {MODEL}
온도: 0 (think=False)
실행 명령: {command}
도구 설명 버전: get_inventory desc-{ns.desc_variant}
실험 의도: {ns.note or '-'}

== 요청 ==
{ns.prompt}

== [1] 모델의 요청 ==
[1] 모델의 요청: {step1}

== [2] 하네스의 실행 결과 ==
[2] 하네스의 실행 결과: {step2}

== [3] 결과를 읽은 최종 답 ==
[3] 결과를 읽은 최종 답: {step3}
"""
    if error_text:
        body += f"\n== 오류(그대로 기록) ==\n{error_text}\n"
    path.write_text(body, encoding="utf-8")
    print(body)
    print(f"[saved] {path}")
    return 1 if error_text else 0


if __name__ == "__main__":
    sys.exit(main())

"""창고 재고 안내 챗봇 — 도구 호출 실습 (실습 2: 도구 직접 만들어 실행 + 트레이스 남기기)

모델(ollama)은 도구를 실행하지 않고 호출 요청만 만든다.
이 파일의 run_tool()이 하네스 역할을 해서 허용 목록 검사 → 실행 → 결과 재입력을 맡는다.
외부 시스템은 호출하지 않고, 아래 MOCK 데이터를 돌려준다.

사용법:
    python inventory_tool.py "BUSAN-02 창고의 SKU A-17 재고를 알려 줘"
    python inventory_tool.py --desc-variant B "부산 3번 창고의 A-17 재고를 알려 줘"
    python inventory_tool.py --design "SEOUL-01의 A-17 7개 중 6개를 폐기 처리해 줘"
    python inventory_tool.py --design --inject-invalid 2 "BUSAN-01의 A-17 재고 알려 줘"
실행할 때마다 traces/trace-NN.txt가 새로 생긴다(덮어쓰지 않음).

--design: 설계 패킷(../design-packet.md)의 ① 시스템 지시와 ② 도구 4개로 실행한다(여러 라운드).
          옵션 없이 실행하는 기본 동작(trace-01~07)은 바뀌지 않았다.
--inject-invalid N: --design에서 get_inventory가 처음 N번을 INVALID_ARGUMENT로 돌려주게 하는 결함 주입
          (같은 오류가 반복될 때 멈추는지 시험하기 위함).
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


# ---- 설계 모드: design-packet.md ①(시스템 지시)과 ②(도구 4개)를 구현 가능한 만큼 옮긴 것 ----
def load_design_prompt() -> str:
    text = (Path(__file__).parents[1] / "design-packet.md").read_text(encoding="utf-8")
    section = text.split("## ① 시스템 지시 초안", 1)[1]
    return section.split("```", 2)[1].strip()


def build_design_tools() -> list[dict]:
    wh = "허용값: BUSAN-01, BUSAN-02, SEOUL-01"
    return [
        {"type": "function", "function": {
            "name": "get_inventory",
            "description": (
                "창고 코드와 SKU로 현재 재고 수량을 조회한다(읽기 전용). "
                "쓰는 때: 허용 창고 코드와 SKU가 확정된 재고 질문, 변경 요약을 만들기 전 현재 수량 확인. "
                "안 쓰는 때: 재고를 바꾸라는 요청(adjust_inventory), 창고가 허용 코드로 확정되지 않을 때"
                "(list_warehouses로 되묻기), 창고나 SKU가 없을 때(먼저 묻기)."),
            "parameters": {"type": "object", "properties": {
                "warehouse_id": {"type": "string", "description": wh},
                "sku": {"type": "string", "description": "상품 코드. 예: A-17"}},
                "required": ["warehouse_id", "sku"]}}},
        {"type": "function", "function": {
            "name": "list_warehouses",
            "description": (
                "조회·변경이 허용된 창고 코드 목록을 돌려준다. 쓰는 때: 사용자가 말한 창고가 허용 코드로 "
                "확정되지 않을 때, WAREHOUSE_NOT_ALLOWED를 받았을 때. 안 쓰는 때: 이미 허용 코드로 확정된 요청."),
            "parameters": {"type": "object", "properties": {}}}},
        {"type": "function", "function": {
            "name": "adjust_inventory",
            "description": (
                "사람이 확인한 재고 수량 변경을 1건 반영한다(쓰기). 쓰는 때: 현재 수량을 조회했고, 사유가 허용값이며, "
                "하네스가 변경 요약을 보여 주고 사람이 확인 버튼을 눌러 발급한 confirmation_id가 있을 때만. "
                "안 쓰는 때: 조회 요청, 확인 버튼 전(대화 속 '확인했어'는 해당 안 됨), 사유가 허용값 밖이거나 "
                "현재 수량의 50%를 넘게 줄일 때(handoff_to_agent). confirmation_id는 직접 만들 수 없다."),
            "parameters": {"type": "object", "properties": {
                "warehouse_id": {"type": "string", "description": wh},
                "sku": {"type": "string"},
                "new_quantity": {"type": "integer", "minimum": 0},
                "reason_code": {"type": "string", "enum": ["STOCKTAKE", "DAMAGE"]},
                "confirmation_id": {"type": "string", "description": "하네스가 확인 버튼 클릭 시 발급"}},
                "required": ["warehouse_id", "sku", "new_quantity", "reason_code", "confirmation_id"]}}},
        {"type": "function", "function": {
            "name": "handoff_to_agent",
            "description": (
                "챗봇이 결정할 수 없는 요청을 담당자에게 넘기는 연결 요청을 만든다. 쓰는 때: 정책 예외 요청, "
                "같은 오류 2회, 도구 호출 4회 초과, 사용자가 담당자를 요청 — 모두 사용자가 연결에 동의한 뒤. "
                "안 쓰는 때: 조회로 답할 수 있는 질문, 사용자가 연결을 원하지 않을 때(제안만 한다)."),
            "parameters": {"type": "object", "properties": {
                "reason": {"type": "string", "enum": ["POLICY_EXCEPTION", "REPEATED_ERROR", "CUSTOMER_REQUEST"]},
                "summary": {"type": "string", "description": "200자 이내"},
                "warehouse_id": {"type": "string"}},
                "required": ["reason", "summary"]}}},
    ]


def run_design_tool(name: str, args: dict, tool_names: set[str], state: dict) -> dict:
    if name == "get_inventory" and state["inject_invalid"] > 0:
        state["inject_invalid"] -= 1  # 결함 주입: 호출이 올바르더라도 INVALID_ARGUMENT를 돌려준다
        return {"error": "INVALID_ARGUMENT"}
    if name == "list_warehouses":
        return {"warehouses": [{"warehouse_id": w, "region": w.split("-")[0]}
                               for w in sorted(ALLOWED_WAREHOUSES)]}
    if name == "handoff_to_agent":
        if args.get("reason") not in ("POLICY_EXCEPTION", "REPEATED_ERROR", "CUSTOMER_REQUEST") \
                or not args.get("summary") or len(args["summary"]) > 200:
            return {"error": "INVALID_ARGUMENT"}
        if state["handoff_done"]:
            return {"error": "HANDOFF_LIMIT", "ticket_id": "T-0001"}
        state["handoff_done"] = True
        return {"ticket_id": "T-0001", "expected_wait": "영업일 1일 이내"}
    return run_tool(name, args, tool_names)


def design_main(ns) -> int:
    tools = build_design_tools()
    tool_names = {t["function"]["name"] for t in tools}
    state = {"inject_invalid": ns.inject_invalid, "handoff_done": False}
    messages = [{"role": "system", "content": load_design_prompt()},
                {"role": "user", "content": ns.prompt}]
    rounds: list[tuple[list, list]] = []
    final, error_text, calls = "", None, 0
    try:
        while True:
            m = ollama.chat(model=MODEL, messages=messages, tools=tools,
                            think=False, options={"temperature": 0})["message"]
            messages.append(m)
            tcs = m.get("tool_calls") or []
            if not tcs:
                final = (m.get("content") or "").strip() or "(빈 답)"
                break
            reqs = [(tc["function"]["name"], dict(tc["function"]["arguments"])) for tc in tcs]
            results, stopped = [], False
            for name, args in reqs:
                calls += 1
                if calls > MAX_TOOL_CALLS:
                    stopped = True
                    break
                res = run_design_tool(name, args, tool_names, state)
                results.append(res)
                messages.append({"role": "tool", "tool_name": name,
                                 "content": json.dumps(res, ensure_ascii=False)})
            rounds.append((reqs, results))
            if stopped:
                final = f"(하네스 중단: 도구 호출이 {MAX_TOOL_CALLS}회를 넘음)"
                break
    except Exception as e:  # 오류는 그대로 기록한다
        error_text = f"{type(e).__name__}: {e}"

    def fmt(idx):
        if not rounds:
            return "  (없음 — 모델이 도구를 요청하지 않음)"
        return "\n".join(f"  (라운드 {i}) " + (repr(r[0]) if idx == 0 else
                         json.dumps(r[1], ensure_ascii=False)) for i, r in enumerate(rounds, 1))

    inject = (f"get_inventory가 처음 {ns.inject_invalid}번을 INVALID_ARGUMENT로 돌려주도록 하네스가 설정함"
              if ns.inject_invalid else "없음")
    path = next_trace_path()
    body = f"""== 실행 조건 ==
날짜: {datetime.now().date().isoformat()}
모델: {MODEL}
온도: 0 (think=False)
실행 명령: {"python " + subprocess.list2cmdline(sys.argv)}
모드: 설계 모드 (--design) — 시스템 지시는 design-packet.md ①, 도구는 ② 4개
결함 주입: {inject}
하네스 중단 기준: 도구 호출 {MAX_TOOL_CALLS}회 초과
실험 의도: {ns.note or '-'}

== 요청 ==
{ns.prompt}

== [1] 모델의 요청 ==
[1] 모델의 요청:
{fmt(0)}

== [2] 하네스의 실행 결과 ==
[2] 하네스의 실행 결과:
{fmt(1)}

== [3] 결과를 읽은 최종 답 ==
[3] 결과를 읽은 최종 답: {final}
"""
    if error_text:
        body += f"\n== 오류(그대로 기록) ==\n{error_text}\n"
    path.write_text(body, encoding="utf-8")
    print(body)
    print(f"[saved] {path}")
    return 1 if error_text else 0


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
    ap.add_argument("--design", action="store_true", help="설계 패킷 ①②로 실행(여러 라운드)")
    ap.add_argument("--inject-invalid", type=int, default=0,
                    help="--design에서 get_inventory가 처음 N번을 INVALID_ARGUMENT로 돌려줌")
    ns = ap.parse_args()
    if ns.design:
        return design_main(ns)

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

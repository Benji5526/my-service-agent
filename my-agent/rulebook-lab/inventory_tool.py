import asyncio, json
from typing import Any

async def main():
    from langchain_core.tools import tool
    from langchain_core.messages import ToolMessage
    from langchain_ollama import ChatOllama

    @tool
    def get_inventory(sku: str, warehouse_id: str) -> dict[str, Any]:
        """승인된 창고에서 특정 상품의 현재 가용 재고를 읽기 전용으로 조회합니다.
        sku에는 상품 SKU를, warehouse_id에는 SEOUL-01 또는 BUSAN-02만 넣습니다.
        수량을 변경하지 않습니다. INVALID_SKU이면 SKU를 확인해 달라고 물어야 합니다."""
        if warehouse_id not in ("SEOUL-01", "BUSAN-02"):
            return {"error": "WAREHOUSE_NOT_ALLOWED"}
        return {"sku": sku, "warehouse_id": warehouse_id,
                "available_quantity": 7, "checked_at": "2026-08-27T01:55:00+09:00"}

    llm = ChatOllama(model="qwen3.5:2b", temperature=0, reasoning=False)
    llm_with_tools = llm.bind_tools([get_inventory])

    r1 = await llm_with_tools.ainvoke("BUSAN-02 창고의 SKU A-17 재고를 알려 줘")
    print("[1] 모델의 요청:", [(tc["name"], tc["args"]) for tc in r1.tool_calls])

    result = get_inventory.invoke(r1.tool_calls[0]["args"])
    print("[2] 하네스의 실행 결과:", json.dumps(result, ensure_ascii=False))

    r2 = await llm_with_tools.ainvoke(
        [r1, ToolMessage(content=json.dumps(result, ensure_ascii=False),
                         tool_call_id=r1.tool_calls[0]["id"])])
    print("[3] 결과를 읽은 최종 답:", r2.content[:120])

asyncio.run(main())

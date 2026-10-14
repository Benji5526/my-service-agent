"""qdrant MCP 서버를 MCP 클라이언트로 직접 호출해 도구 정의와 저장/검색 동작을 기록한다.
LLM은 쓰지 않는다: '모델이 어떤 도구를 고르는가'가 아니라 '서버가 무엇을 노출하고 어떻게 동작하는가'를 본다.

사용법: python probe_server.py <variant>
  rulebook : 룰북 .mcp.json의 env 그대로
  corrected: 서버가 읽는 이름(COLLECTION_NAME, EMBEDDING_MODEL ...)으로 고친 env
"""
import asyncio, json, sys
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ENVS = {
    "rulebook": {
        "QDRANT_URL": ":memory:",
        "QDRANT_COLLECTION": "policies",
        "EMBEDDER_PROVIDER": "fastembed",
        "FASTEMBED_MODEL": "BAAI/bge-small-en-v1.5",
    },
    "corrected": {
        "QDRANT_URL": ":memory:",
        "COLLECTION_NAME": "policies",
        "EMBEDDING_PROVIDER": "fastembed",
        "EMBEDDING_MODEL": "BAAI/bge-small-en-v1.5",
    },
}

SENTENCES = ["환불은 구매 후 7일 이내에 가능하다.",
             "배송은 영업일 기준 2일이 걸린다.",
             "회원 등급은 매월 1일에 갱신된다."]
QUERIES = ["환불 기한이 어떻게 돼?", "배송은 며칠 걸려?"]


def dump(x):
    return json.dumps(x, ensure_ascii=False, indent=1)


async def main(variant: str):
    env = {**ENVS[variant], "PYTHONUTF8": "1", "HF_HUB_DISABLE_SYMLINKS_WARNING": "1"}
    params = StdioServerParameters(command="uvx", args=["mcp-server-qdrant"], env=env)
    print(f"##### variant = {variant}\nenv = {dump(ENVS[variant])}\n")
    async with stdio_client(params) as (r, w):
        async with ClientSession(r, w) as s:
            await asyncio.wait_for(s.initialize(), 300)
            tools = (await s.list_tools()).tools
            print("== tools ==")
            for t in tools:
                print(f"- {t.name}\n  description: {t.description}\n  inputSchema: {dump(t.input_schema)}")

            has_coll = "collection_name" in next(t for t in tools if t.name == "qdrant-store").input_schema["properties"]
            print(f"\ncollection_name 이 도구 인자로 노출됨: {has_coll}\n")

            print("== qdrant-store ==")
            for sent in SENTENCES:
                args = {"information": sent, "metadata": {"source": "lab"}}
                if has_coll:
                    args["collection_name"] = "policies"
                res = await s.call_tool("qdrant-store", args)
                print(f"store {sent!r} -> isError={res.is_error} {[c.text for c in res.content]}")

            print("\n== qdrant-find ==")
            for q in QUERIES:
                args = {"query": q}
                if has_coll:
                    args["collection_name"] = "policies"
                res = await s.call_tool("qdrant-find", args)
                print(f"find {q!r} -> isError={res.is_error}")
                for c in res.content:
                    print("   ", c.text)


asyncio.run(main(sys.argv[1]))

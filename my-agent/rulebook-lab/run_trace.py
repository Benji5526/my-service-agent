"""룰북 inventory_tool.py를 (선택적으로 바꿔서) 실행하고, 룰북 trace 형식으로 traces/trace-NN.txt를 남긴다.

원본 inventory_tool.py는 수정하지 않는다. 요청 문장이나 도구 설명을 바꾼 실행은
variants/inventory_tool_NN.py 로 복사본을 만들어 그 파일을 실행한다.
trace는 덮어쓰지 않고 번호를 올린다. 오류가 나면 그대로 기록한다.

사용법:
    python run_trace.py                                  # 원본 그대로
    python run_trace.py --prompt "부산 3번 창고의 A-17 재고를 알려 줘"
    python run_trace.py --prompt "..." --desc-add "허용 코드가 아니면 호출하지 말고 되물어라."
"""
import argparse, re, subprocess, sys, os
from datetime import date
from pathlib import Path

HERE = Path(__file__).parent
SRC = HERE / "inventory_tool.py"
TRACES = HERE / "traces"
VARIANTS = HERE / "variants"
PROMPT_ORIG = '"BUSAN-02 창고의 SKU A-17 재고를 알려 줘"'
DESC_END_ORIG = 'INVALID_SKU이면 SKU를 확인해 달라고 물어야 합니다."""'
UV = ["uv", "run", "--with", "langchain", "--with", "langchain-ollama", "python"]


def next_no() -> int:
    TRACES.mkdir(exist_ok=True)
    nums = [int(m.group(1)) for p in TRACES.glob("trace-*.txt")
            if (m := re.match(r"trace-(\d+)\.txt", p.name))]
    return max(nums) + 1 if nums else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--prompt", help="요청 문장을 이 문장으로 바꿔 실행")
    ap.add_argument("--desc-add", help="get_inventory 도구 설명 끝에 이 문장을 덧붙여 실행")
    ap.add_argument("--note", default="", help="이 실행의 의도 한 줄")
    ns = ap.parse_args()

    no = next_no()
    changes = []
    if ns.prompt or ns.desc_add:
        text = SRC.read_text(encoding="utf-8")
        if ns.prompt:
            assert PROMPT_ORIG in text
            text = text.replace(PROMPT_ORIG, '"' + ns.prompt.replace('"', '\\"') + '"')
            changes.append(f"요청 문장 변경: {ns.prompt}")
        if ns.desc_add:
            assert DESC_END_ORIG in text
            text = text.replace(DESC_END_ORIG,
                                'INVALID_SKU이면 SKU를 확인해 달라고 물어야 합니다.\n        '
                                + ns.desc_add + '"""')
            changes.append(f"도구 설명에 덧붙임: {ns.desc_add}")
        VARIANTS.mkdir(exist_ok=True)
        target = VARIANTS / f"inventory_tool_{no:02d}.py"
        target.write_text(text, encoding="utf-8")
        run_file = f"variants/{target.name}"
    else:
        target = SRC
        run_file = "inventory_tool.py"

    env = {**os.environ, "PYTHONUTF8": "1"}
    p = subprocess.run(UV + [run_file], cwd=HERE, env=env, capture_output=True,
                       text=True, encoding="utf-8")
    lines = {k: next((l for l in p.stdout.splitlines() if l.startswith(k)), None)
             for k in ("[1]", "[2]", "[3]")}
    prompt_text = re.search(r'ainvoke\("(.*?)"\)', target.read_text(encoding="utf-8")).group(1)

    def part(k, title):
        return f"== {k} {title} ==\n{lines[k] or k + ' (출력 없음 — 이 단계에 도달하지 못함)'}\n"

    body = (
        "== 실행 조건 ==\n"
        f"날짜: {date.today().isoformat()}\n"
        "모델: qwen3.5:2b\n"
        "온도: 0 (reasoning=False)\n"
        f"실행 명령: {' '.join(UV)} {run_file}\n"
        f"변경점: {'; '.join(changes) if changes else '없음 (룰북 코드 그대로)'}\n"
        f"실험 의도: {ns.note or '-'}\n"
        "\n== 요청 ==\n" + prompt_text + "\n\n"
        + part("[1]", "모델의 요청") + "\n"
        + part("[2]", "하네스의 실행 결과") + "\n"
        + part("[3]", "결과를 읽은 최종 답")
    )
    if p.returncode != 0:
        err = p.stderr
        err = err[err.find("Traceback"):] if "Traceback" in err else err
        body += f"\n== 오류(그대로 기록) ==\n종료 코드: {p.returncode}\n{err.strip()}\n"
    path = TRACES / f"trace-{no:02d}.txt"
    path.write_text(body, encoding="utf-8")
    print(body)
    print(f"[saved] {path}")
    return 0


sys.exit(main())

"""Verify 40 gold cases offline; opt in to a bounded, sequential live Gemini run."""

import argparse
import asyncio
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import re
import statistics
import tempfile
import time

from scripts.create_sample_db import create_sample, ROOT
from scripts.football_artifact import readonly, sha256

CASES = ROOT / "tests/fixtures/evaluation_cases.json"
CONTRACT = "\nThis is a fictional evaluation dataset. Use the database. End your answer with a separate line RESULT: <number>, containing the single numeric answer to this question."


def verify_gold(database: Path, cases: list) -> None:
    connection = readonly(database)
    try:
        for case in cases:
            rows = connection.execute(case["sql"]).fetchall()
            if len(rows) != 1 or len(rows[0]) != 1 or not math.isclose(float(rows[0][0]), case["expected"], abs_tol=1e-8):
                raise ValueError(f"Gold mismatch: {case['id']}")
    finally:
        connection.close()


def score_answer(answer: str, expected: float) -> bool:
    match = re.search(r"(?:^|\n)RESULT:\s*(-?\d+(?:\.\d+)?)\s*$", answer)
    return bool(match and math.isclose(float(match.group(1)), expected, abs_tol=1e-8))


def visible_text(content) -> str:
    if isinstance(content, str):
        return content
    return "\n".join(part.get("text", "") for part in content if isinstance(part, dict) and part.get("type") == "text")


def summarize(results: list) -> dict:
    attempted = [r for r in results if r["status"] != "not_run"]
    completed = [r for r in attempted if r["status"] == "completed"]
    latencies = sorted(r["latency_seconds"] for r in attempted)
    calls = sum(r["tool_results"] for r in attempted)
    correct = sum(r["answer_correct"] for r in attempted)
    return {
        "planned": len(results), "attempted": len(attempted), "completed": len(completed),
        "exact_numeric_answers_correct": correct,
        "answer_correctness_of_attempted": correct / len(attempted) if attempted else None,
        "questions_with_successful_sql": sum(r["sql_successes"] > 0 for r in attempted),
        "sql_execution_success_rate": sum(r["sql_successes"] for r in attempted) / calls if calls else None,
        "tool_results": calls,
        "median_latency_seconds": statistics.median(latencies) if latencies else None,
        "p95_latency_seconds": latencies[math.ceil(.95 * len(latencies)) - 1] if latencies else None,
    }


async def evaluate(cases: list, output: Path, max_cases: int, delay: float):
    # Set data path before importing the agent; never evaluate against personal data.
    with tempfile.TemporaryDirectory(prefix="football-evaluation-") as directory:
        database = Path(directory) / "sample.db"
        create_sample(database)
        verify_gold(database, cases)
        os.environ["FOOTBALL_DB_PATH"] = str(database)
        from langchain_core.messages import HumanMessage
        from src.agents.graph import build_agent
        from src.api.main import tool_result_payload
        from src.agents.config import get_llm_client
        get_llm_client()  # Configuration check only; no request.
        report = {
            "started_utc": datetime.now(timezone.utc).isoformat(),
            "model": os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
            "dataset": "fictional sample_football.json", "database_sha256": sha256(database),
            "case_file_sha256": sha256(CASES), "gold_verified": len(cases),
            "method": "Single-turn scalar questions; gold SQL is NOT sent to the model. Exact final RESULT numeric value, not prose faithfulness. SQL execution is scored separately. No model retries; stop on provider/runtime error.",
            "results": [{"id": c["id"], "question": c["question"], "expected": c["expected"], "status": "not_run"} for c in cases],
        }
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("x") as stream:
            json.dump(report, stream, indent=2)
        for index, case in enumerate(cases[:max_cases]):
            print(f"Evaluating {index + 1}/{min(max_cases, len(cases))}: {case['id']}", flush=True)
            result = report["results"][index]
            result.update(answer="", tool_results=0, sql_successes=0, answer_correct=False, events=[], generated_sql=[])
            started = time.perf_counter()
            try:
                async with asyncio.timeout(90):
                    async for update in build_agent().astream({"messages": [HumanMessage(content=case["question"] + CONTRACT)]}, stream_mode="updates"):
                        for node, state in update.items():
                            for message in state["messages"]:
                                if node == "tools":
                                    payload = tool_result_payload(message)
                                    result["tool_results"] += 1
                                    result["sql_successes"] += int("error" not in payload["result"])
                                    result["events"].append({"event": "tool_result", "data": payload})
                                elif getattr(message, "tool_calls", None):
                                    result["generated_sql"].extend(call["args"].get("query", "") for call in message.tool_calls)
                                    result["events"].append({"event": "tool_call", "data": {"tools": [call["name"] for call in message.tool_calls]}})
                                elif node in ("agent", "sql_stop"):
                                    result["answer"] = visible_text(message.content)
                result["status"] = "completed"
                result["answer_correct"] = score_answer(result["answer"], case["expected"])
                result["events"].extend([
                    {"event": "final_answer", "data": {"answer": result["answer"]}},
                    {"event": "complete", "data": {}},
                ])
            except Exception as exc:
                detail = str(exc).lower()
                result["status"] = "error"
                result["failure"] = "provider_quota" if any(x in detail for x in ("429", "quota", "resource_exhausted")) else "provider_or_runtime_error"
                # Do not persist provider error bodies, credentials, or tracebacks.
            result["latency_seconds"] = round(time.perf_counter() - started, 3)
            report["summary"] = summarize(report["results"])
            output.write_text(json.dumps(report, indent=2) + "\n")
            print(f"  {result['status']}; exact answer={result['answer_correct']}; SQL successes={result['sql_successes']}/{result['tool_results']}", flush=True)
            if result["status"] == "error":
                print("Stopped on error; remaining cases are explicitly not_run.", flush=True)
                break
            if index + 1 < min(max_cases, len(cases)):
                await asyncio.sleep(delay)
        report["finished_utc"] = datetime.now(timezone.utc).isoformat()
        report["summary"] = summarize(report["results"])
        output.write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps(report["summary"], indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Calls Gemini; verify your account is unbilled first")
    parser.add_argument("--max-cases", type=int, default=40, choices=range(1, 41))
    parser.add_argument("--delay", type=float, default=10)
    parser.add_argument("--output", type=Path, default=ROOT / "build/evaluation/report.json")
    args = parser.parse_args()
    cases = json.loads(CASES.read_text())
    if args.live:
        asyncio.run(evaluate(cases, args.output, args.max_cases, max(1, args.delay)))
    else:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "sample.db"
            create_sample(database)
            verify_gold(database, cases)
        print(f"Verified {len(cases)} literal expected answers against reference SQL. No model calls; NOT an AI accuracy result.")

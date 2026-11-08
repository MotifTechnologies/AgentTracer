import asyncio
import json

import pytest
from stirrup import AssistantMessage, TextBlock, TokenUsage, ToolCall

from agent_tracer.config.schema import (
    DatasetConfig,
    ModelConfig,
    OutputConfig,
    RunConfig,
)
from agent_tracer.core.task import Task
from agent_tracer.core.trajectory import Trajectory
from agent_tracer.datasets.bfcl_fixture import (
    BFCLFixtureDataset,
    Fixture,
    FixtureBackend,
    answer_matches,
    grade_turn,
)
from agent_tracer.models.client import NativeCompletion
from agent_tracer.orchestrators.bfcl_fixture import BFCLFixtureOrchestrator

PAGES = {
    "https://en.wikipedia.org/wiki/Longman": {
        "title": "Longman",
        "text": "Longman is a publishing company founded in London in 1724.",
        "raw": "<html><body><p>Longman is a publishing company.</p></body></html>",
        "markdown": "Longman is a publishing company.",
        "truncate": "Longman is a publishing company.",
    },
    "https://en.wikipedia.org/wiki/Pearson_plc": {
        "title": "Pearson plc",
        "text": "Pearson plc is a British company that owns Longman.",
        "raw": "<html>Pearson</html>",
        "markdown": "Pearson",
        "truncate": "Pearson",
    },
    "https://en.wikipedia.org/wiki/Bielefeld": {
        "title": "Bielefeld",
        "text": "Bielefeld is a city in Germany.",
        "error": "403 Client Error: Forbidden for url: https://en.wikipedia.org/wiki/Bielefeld",
    },
}


def web_fixture(show_snippet=True):
    def tool(name, kind, properties, required):
        return {
            "schema": {
                "type": "function",
                "function": {
                    "name": name,
                    "description": name,
                    "parameters": {
                        "type": "object",
                        "properties": properties,
                        "required": required,
                    },
                },
            },
            "operation": {
                "kind": kind,
                "collection": "pages",
                "key_argument": "url",
                "show_snippet": show_snippet,
            },
        }

    return Fixture.model_validate(
        {
            "task_id": "web1",
            "category": "web_search",
            "initial_state": {"pages": PAGES},
            "provenance": {"seed_id": "independent:test"},
            "tools": [
                tool(
                    "search_engine_query",
                    "search",
                    {
                        "keywords": {"type": "string"},
                        "max_results": {"type": "integer"},
                    },
                    ["keywords"],
                ),
                tool(
                    "fetch_url_content",
                    "fetch",
                    {
                        "url": {"type": "string"},
                        "mode": {
                            "type": "string",
                            "enum": ["raw", "markdown", "truncate"],
                        },
                    },
                    ["url"],
                ),
            ],
            "user_turns": [
                {
                    "content": "Where was Longman founded?",
                    "expected_state": None,
                    "answer_any_of": ["London"],
                    "max_calls": 4,
                }
            ],
        }
    )


def test_search_ranks_pages_and_shows_snippets():
    results = FixtureBackend(web_fixture()).execute(
        "search_engine_query", {"keywords": "Longman publishing founded"}
    )
    assert [r["href"] for r in results] == [
        "https://en.wikipedia.org/wiki/Longman",
        "https://en.wikipedia.org/wiki/Pearson_plc",
    ]
    assert "founded in London" in results[0]["body"]


def test_search_without_snippet_and_with_limit():
    results = FixtureBackend(web_fixture(show_snippet=False)).execute(
        "search_engine_query", {"keywords": "Longman", "max_results": 1}
    )
    assert results == [
        {"title": "Longman", "href": "https://en.wikipedia.org/wiki/Longman"}
    ]


def test_search_with_no_matching_terms_returns_no_results():
    backend = FixtureBackend(web_fixture())
    assert backend.execute("search_engine_query", {"keywords": "zzz"}) == []


@pytest.mark.parametrize(
    ("mode", "content"),
    [
        (None, PAGES["https://en.wikipedia.org/wiki/Longman"]["raw"]),
        ("markdown", "Longman is a publishing company."),
        ("truncate", "Longman is a publishing company."),
    ],
)
def test_fetch_returns_requested_rendering(mode, content):
    args = {"url": "https://en.wikipedia.org/wiki/Longman#History"}
    if mode:
        args["mode"] = mode
    result = FixtureBackend(web_fixture()).execute("fetch_url_content", args)
    assert result == {"content": content}


@pytest.mark.parametrize(
    ("url", "reason"),
    [
        (
            "https://en.wikipedia.org/wiki/Missing",
            "404 Client Error: Not Found for url: https://en.wikipedia.org/wiki/Missing",
        ),
        (
            "https://en.wikipedia.org/wiki/Bielefeld",
            "403 Client Error: Forbidden for url: https://en.wikipedia.org/wiki/Bielefeld",
        ),
    ],
)
def test_fetch_failures_are_ordinary_tool_results(url, reason):
    backend = FixtureBackend(web_fixture())
    result = backend.execute("fetch_url_content", {"url": url})
    assert result == {"error": f"An error occurred while fetching {url}: {reason}"}
    assert backend.state == {"pages": PAGES}


def test_fetch_rejects_non_http_url():
    with pytest.raises(ValueError, match="Invalid URL"):
        FixtureBackend(web_fixture()).execute(
            "fetch_url_content", {"url": "en.wikipedia.org/wiki/Longman"}
        )


@pytest.mark.parametrize(
    ("answer", "ok"),
    [
        ("It was founded in London, England.", True),
        ("london", True),
        ("Londonderry", False),
        (None, False),
    ],
)
def test_answer_any_of_uses_bfcl_normalization(answer, ok):
    assert answer_matches(answer, ["London"]) is ok
    assert answer_matches("April 1, 2024", ["April 1 2024"])


def test_state_free_turn_grades_only_answer_and_calls():
    f = web_fixture()
    turn = f.user_turns[0]
    assert grade_turn(turn, {"anything": 1}, "London", ["search_engine_query"], 1) == []
    assert grade_turn(turn, {}, "Paris", ["search_engine_query"] * 5, 1) == [
        "call_count_out_of_range",
        "expected_answer_missing",
    ]


def test_web_turn_runs_and_grades_without_copying_pages(tmp_path, monkeypatch):
    f = web_fixture()
    url = "https://en.wikipedia.org/wiki/Longman"
    responses = [
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "c1",
                    "type": "function",
                    "function": {
                        "name": "search_engine_query",
                        "arguments": '{"keywords": "Longman founded"}',
                    },
                },
                {
                    "id": "c2",
                    "type": "function",
                    "function": {
                        "name": "fetch_url_content",
                        "arguments": json.dumps({"url": url, "mode": "truncate"}),
                    },
                },
            ],
        },
        {"role": "assistant", "content": "{'answer': 'London', 'context': 'page'}"},
    ]
    requests = []

    class Client:
        def __init__(self, *args, **kwargs):
            pass

        async def generate_native(self, messages, tools):
            requests.append(json.loads(json.dumps(messages)))
            h = responses.pop(0)
            blocks = [TextBlock(text=h["content"])] if h["content"] else []
            blocks.extend(
                ToolCall.from_provider(
                    provider_id=c["id"],
                    name=c["function"]["name"],
                    arguments=c["function"]["arguments"],
                )
                for c in h.get("tool_calls", [])
            )
            return NativeCompletion(
                AssistantMessage(
                    blocks=blocks,
                    token_usage=TokenUsage(input=1, reasoning=0, answer=1),
                ),
                h,
                {"choices": [{"message": h}]},
            )

        async def close(self):
            pass

    monkeypatch.setattr("agent_tracer.orchestrators.bfcl_fixture.build_client", Client)
    config = RunConfig(
        dataset=DatasetConfig(name="bfcl_fixture", path=tmp_path / "unused"),
        model=ModelConfig(
            model_name="m",
            base_url="http://x",
            api_key="not-a-real-key",
            reasoning_key="none",
        ),
        output=OutputConfig(path=tmp_path),
    )
    task = Task(
        f.task_id,
        f.user_turns[0].content,
        metadata={"bfcl_fixture": f.model_dump(by_alias=True)},
    )
    traj = Trajectory(task.task_id)
    result = asyncio.run(BFCLFixtureOrchestrator(config).run_task(task, traj))
    assert result["exit_status"] == "completed"
    tool_messages = [m for m in requests[1] if m["role"] == "tool"]
    assert json.loads(tool_messages[0]["content"])[0]["href"] == url
    assert json.loads(tool_messages[1]["content"]) == {
        "content": "Longman is a publishing company."
    }
    grade = next(e.data for e in traj.events if e.event_type == "fixture_turn_grade")
    assert "final_state" not in grade and len(grade["final_state_sha256"]) == 64
    assert (
        BFCLFixtureDataset(tmp_path / "unused").evaluate_trajectory(task, traj).correct
    )


def remote_fixture(endpoint):
    f = web_fixture().model_dump(by_alias=True)
    for tool in f["tools"]:
        tool["operation"] = {
            "kind": "remote",
            "endpoint": endpoint,
            "show_snippet": False,
        }
    f["initial_state"] = {}
    return Fixture.model_validate(f)


def test_remote_operation_posts_call_to_local_server():
    import http.server
    import threading

    seen = []

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            seen.append(body)
            reply = (
                {"raise": "Invalid URL: x"}
                if body["arguments"].get("url") == "x"
                else {"result": [{"title": "t", "href": "https://e.org"}]}
            )
            data = json.dumps(reply).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        backend = FixtureBackend(
            remote_fixture(f"http://127.0.0.1:{server.server_port}/call")
        )
        assert backend.execute("search_engine_query", {"keywords": "q"}) == [
            {"title": "t", "href": "https://e.org"}
        ]
        with pytest.raises(ValueError, match="Invalid URL"):
            backend.execute("fetch_url_content", {"url": "x"})
    finally:
        server.shutdown()
    assert seen[0] == {
        "tool": "search_engine_query",
        "arguments": {"keywords": "q"},
        "show_snippet": False,
    }


def test_remote_operation_rejects_non_local_endpoint():
    with pytest.raises(ValueError, match="local tool server"):
        remote_fixture("https://example.com/call")

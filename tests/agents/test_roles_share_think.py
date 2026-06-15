"""Тест: executor/summarizer/planner/critic идут через общий `OllamaClient`.

Спринт 11, задача 1.2. Все роли получают один и тот же клиент и вызывают
`OllamaClient.chat` без явного `think`, поэтому значение `think` из
конструктора клиента (`OLLAMA_THINK`) наследуется автоматически. Тест
проверяет, что выбранный `think` доходит до нижележащего `ollama.AsyncClient`.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

import pytest

from app.agents.critic import CriticAgent
from app.agents.executor import Executor
from app.agents.planner import PlannerAgent
from app.agents.protocol import Plan, PlanStep
from app.services.llm import OllamaClient
from app.services.summarizer import Summarizer


@dataclass
class _Settings:
    agent_max_steps: int = 3
    agent_max_output_chars: int = 8000
    agent_max_context_chars: int = 8000
    agent_max_repair_attempts: int = 2
    ollama_default_model: str = "qwen3.5:4b"


class _Prompts:
    def render_agent_system(self, *, tools_description, skills_description):
        return "SYSTEM"

    def render_planner(self, task):
        return f"PLAN: {task}"

    def render_critic(self, task, plan, draft):
        return f"CRITIC: {task}"


class _Tools:
    def list_descriptions(self):
        return []

    async def execute(self, name, args, ctx):  # pragma: no cover - не вызывается
        raise AssertionError("tool execute не ожидается в этом тесте")


class _Skills:
    def list_descriptions(self):
        return []


def _chat_resp(text: str) -> SimpleNamespace:
    return SimpleNamespace(message=SimpleNamespace(content=text))


@pytest.fixture
def shared_llm() -> OllamaClient:
    return OllamaClient(base_url="http://localhost:11434", timeout=10.0, think=True)


async def test_executor_inherits_think_from_shared_client(shared_llm, mocker):
    chat_mock = mocker.patch.object(
        shared_llm._client, "chat", return_value=_chat_resp('{"final_answer": "ok"}')
    )
    executor = Executor(
        settings=_Settings(),
        llm=shared_llm,
        tools=_Tools(),
        prompts=_Prompts(),
        skills=_Skills(),
    )
    result = await executor.run(
        goal="привет", user_id=1, chat_id=1, conversation_id="c1"
    )
    assert result == "ok"
    assert chat_mock.await_args.kwargs["think"] is True


async def test_summarizer_inherits_think_from_shared_client(shared_llm, mocker):
    chat_mock = mocker.patch.object(
        shared_llm._client, "chat", return_value=_chat_resp("резюме")
    )
    summarizer = Summarizer(llm=shared_llm, system_prompt="SUM", chunk_messages=30)
    out = await summarizer.summarize([{"role": "user", "content": "hi"}], model="m")
    assert out == "резюме"
    assert chat_mock.await_args.kwargs["think"] is True


async def test_planner_inherits_think_from_shared_client(shared_llm, mocker):
    chat_mock = mocker.patch.object(
        shared_llm._client,
        "chat",
        return_value=_chat_resp('{"steps": [{"id": 1, "description": "x"}]}'),
    )
    planner = PlannerAgent(llm=shared_llm, prompts=_Prompts(), settings=_Settings())
    await planner.plan("задача", user_id=1)
    assert chat_mock.await_args.kwargs["think"] is True


async def test_critic_inherits_think_from_shared_client(shared_llm, mocker):
    chat_mock = mocker.patch.object(
        shared_llm._client,
        "chat",
        return_value=_chat_resp('{"verdict": "PASS", "feedback": ""}'),
    )
    critic = CriticAgent(llm=shared_llm, prompts=_Prompts(), settings=_Settings())
    plan = Plan(steps=(PlanStep(id=1, description="x"),))
    await critic.review("задача", plan, "черновик", user_id=1)
    assert chat_mock.await_args.kwargs["think"] is True

import pytest
from pydantic import ValidationError

from api.routers.chat import ChatRequest


def test_legacy_question_contract_remains_supported() -> None:
    request = ChatRequest(question="What is the policy?")
    assert request.resolved_question() == "What is the policy?"
    assert request.conversation_history() == []


def test_messages_use_latest_user_turn_and_bounded_history() -> None:
    request = ChatRequest(
        messages=[
            {"role": "user", "content": "Initial question"},
            {"role": "assistant", "content": "Initial answer"},
            {"role": "user", "content": "Follow-up question"},
        ]
    )
    assert request.resolved_question() == "Follow-up question"
    assert [(message.role, message.content) for message in request.conversation_history()] == [
        ("user", "Initial question"),
        ("assistant", "Initial answer"),
    ]


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"messages": [{"role": "assistant", "content": "No user question"}]},
        {
            "messages": [
                {"role": "user", "content": "one"},
                {"role": "user", "content": "two"},
            ]
        },
    ],
)
def test_invalid_message_conversations_are_rejected(payload: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        ChatRequest.model_validate(payload)

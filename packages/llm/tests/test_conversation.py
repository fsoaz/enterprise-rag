from llm.client import AnthropicClient, ConversationMessage, RetrievedChunk


def test_current_documents_are_attached_after_safe_conversation_history() -> None:
    client = object.__new__(AnthropicClient)
    messages = client._messages(
        question="And what about contractors?",
        chunks=[
            RetrievedChunk(
                chunk_id="chunk-1",
                document_version_id="version-1",
                document_title="Policy",
                body="Contractors require approval.",
                score=0.9,
            )
        ],
        conversation_history=[
            ConversationMessage(role="user", content="Who needs approval?"),
            ConversationMessage(role="assistant", content="Employees do."),
        ],
    )

    assert [message["role"] for message in messages] == ["user", "assistant", "user"]
    current = messages[-1]["content"]
    assert isinstance(current, list)
    assert current[-1] == {"type": "text", "text": "And what about contractors?"}
    assert current[0]["type"] == "document"

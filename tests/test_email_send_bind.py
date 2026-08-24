from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from src.mcp_gateway.email_send_bind import bind_email_send_args, is_placeholder_recipient, last_gmail_draft_from_messages


def test_placeholder_example_dot_com_is_detected():
    assert is_placeholder_recipient("prannay@example.com")
    assert is_placeholder_recipient(["prannay@example.com"])
    assert not is_placeholder_recipient("prannaykamal9@gmail.com")


def test_yes_after_draft_binds_real_gmail_recipient_not_example_com():
    messages = [
        HumanMessage(content="send a mail to Prannay wishing him happy birthday."),
        AIMessage(
            content="",
            tool_calls=[{
                "name": "email_draft",
                "args": {
                    "to": "prannaykamal9@gmail.com",
                    "subject": "Happy Birthday!",
                    "body": "Dear Prannay,\n\nHappy birthday!\n",
                },
                "id": "call_draft",
            }],
        ),
        ToolMessage(
            content="Created Gmail draft r-2158971107387395268 to prannaykamal9@gmail.com. Message id 19ffff6ffda73521.",
            tool_call_id="call_draft",
            name="email_draft",
        ),
        AIMessage(content="I've created a draft wishing Prannay a happy birthday. Would you like me to send it?"),
        HumanMessage(content="yes"),
    ]
    bound = bind_email_send_args(
        {
            "to": "prannay@example.com",
            "subject": "Happy Birthday!",
            "body": "Dear Prannay,\n\nWishing you a very Happy Birthday!\n\nBest wishes,\n[Your Name]",
        },
        messages=messages,
        last_user_text="yes",
    )
    assert bound["to"] == "prannaykamal9@gmail.com"
    assert bound["draft_id"] == "r-2158971107387395268"
    assert "[Your Name]" not in bound["body"]
    assert "Happy birthday" in bound["body"]


def test_explicit_new_recipient_is_kept_when_not_a_confirmation():
    messages = [
        AIMessage(
            content="",
            tool_calls=[{
                "name": "email_draft",
                "args": {"to": "prannaykamal9@gmail.com", "subject": "Hi", "body": "Hello"},
                "id": "call_draft",
            }],
        ),
        ToolMessage(
            content="Created Gmail draft abc to prannaykamal9@gmail.com.",
            tool_call_id="call_draft",
            name="email_draft",
        ),
        HumanMessage(content="send it to ada@gmail.com instead"),
    ]
    bound = bind_email_send_args(
        {"to": "ada@gmail.com", "subject": "Hi", "body": "Hello"},
        messages=messages,
        last_user_text="send it to ada@gmail.com instead",
    )
    assert bound["to"] == "ada@gmail.com"
    assert "draft_id" not in bound


def test_last_draft_parser_reads_tool_result():
    messages = [
        ToolMessage(
            content="Created Gmail draft r-1 to prannaykamal9@gmail.com. Message id 99.",
            tool_call_id="call_draft",
            name="email_draft",
        )
    ]
    draft = last_gmail_draft_from_messages(messages)
    assert draft["to"] == "prannaykamal9@gmail.com"
    assert draft["draft_id"] == "r-1"

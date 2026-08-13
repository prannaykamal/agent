import re

MATH_PATTERN = r"^[\d\s\+\-\*\/\(\)\^\.\%\=sqrt|sin|cos|tan]+$"
GREETING_PATTERN = r"^(hi|hello|hey|greetings|good morning|good evening|howdy)[\!\.]?$"
ACK_PATTERN = (
    r"^(ok|okay|k|thanks|thank you|thx|sure|yes|yep|yeah|yup|no|nope|"
    r"got it|cool|great|perfect|alright|all right)[\!\.]?$"
)


def should_retrieve_memory(user_input: str) -> bool:
    """Skip retrieval only for turns that cannot use long-term memory."""
    cleaned = user_input.strip().lower()
    if not cleaned:
        return False
    if re.match(GREETING_PATTERN, cleaned):
        return False
    if re.match(ACK_PATTERN, cleaned):
        return False
    if re.match(MATH_PATTERN, cleaned):
        return False
    return True

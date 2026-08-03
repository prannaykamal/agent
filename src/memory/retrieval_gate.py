import re

# Keywords indicating long-term memory retrieval is likely needed
RETRIEVAL_KEYWORDS = [
    "remember", "recall", "meeting", "schedule", "preference", "email",
    "contact", "note", "task", "who am i", "my name", "what is my",
    "when did", "did i", "my favorite", "my plan", "last time"
]

# Regex patterns indicating pure math / utility calls where retrieval should be skipped
MATH_PATTERN = r"^[\d\s\+\-\*\/\(\)\^\.\%\=sqrt|sin|cos|tan]+$"
GREETING_PATTERN = r"^(hi|hello|hey|greetings|good morning|good evening|howdy)[\!\.]?$"

def should_retrieve_memory(user_input: str) -> bool:
    """
    Evaluates whether an incoming user turn requires long-term memory retrieval.
    Returns False for pure math, simple greetings, or standard utility requests.
    Returns True for queries referencing user profile, past tasks, or memory keywords.
    """
    cleaned = user_input.strip().lower()

    if not cleaned:
        return False

    # 1. Skip for simple greetings
    if re.match(GREETING_PATTERN, cleaned):
        return False

    # 2. Skip for pure math calculations
    if re.match(MATH_PATTERN, cleaned):
        return False

    # 3. Check for explicit memory keywords
    if any(keyword in cleaned for keyword in RETRIEVAL_KEYWORDS):
        return True

    # 4. Check for personal pronouns / references
    if re.search(r"\b(my|me|i|our|we)\b", cleaned):
        return True

    # Default heuristic: if query is a long or contextual question, check memory
    if len(cleaned.split()) > 4 and ("?" in cleaned or any(w in cleaned for w in ["what", "when", "where", "who", "how"])):
        return True

    return False

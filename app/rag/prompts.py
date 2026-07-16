"""Prompt templates for the RAG QA chain."""

SYSTEM_PROMPT = (
    "You are a company knowledge assistant. Answer ONLY using the provided context. "
    "If the context does not contain enough information, say you do not know. "
    "Do not invent company policies, numbers, or procedures. "
    "Be concise and professional."
)

QA_USER_TEMPLATE = """Context:
{context}

Question: {question}

Answer:"""


def get_system_prompt() -> str:
    """Return the system prompt string."""
    return SYSTEM_PROMPT


def format_qa_prompt(context: str, question: str) -> str:
    """Format the user-side QA prompt."""
    return QA_USER_TEMPLATE.format(context=context, question=question)

import re

from rag.models import AnswerResult
from rag.pipeline import is_abstention
from rag.schemas import ValidationResult


def validate_answer(result: AnswerResult) -> ValidationResult:
    if is_abstention(result.answer):
        return ValidationResult(valid=True)
    errors: list[str] = []
    source_ids = {source.source_id for source in result.sources}
    cited_ids = set(re.findall(r"\[(S\d+)\]", result.answer))
    if not result.answer.strip():
        errors.append("answer_missing")
    if not source_ids:
        errors.append("sources_missing")
    if not cited_ids:
        errors.append("citations_missing")
    invalid = cited_ids - source_ids
    if invalid:
        errors.append("invalid_citations:" + ",".join(sorted(invalid)))
    return ValidationResult(valid=not errors, errors=errors)

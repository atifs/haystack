from haystack.core.component import component
from haystack.core.errors import ComponentError, DeserializationError
from haystack.core.pipeline import Pipeline
from haystack.core.serialization import default_from_dict, default_to_dict
from haystack.dataclasses import Answer, Document, ExtractedAnswer, GeneratedAnswer
import haystack.logging

# Initialize the logging configuration
# This is a no-op unless `structlog` is installed
haystack.logging.configure_logging()

__all__ = [
    "component",
    "default_from_dict",
    "default_to_dict",
    "DeserializationError",
    "ComponentError",
    "Pipeline",
    "Document",
    "Answer",
    "GeneratedAnswer",
    "ExtractedAnswer",
]

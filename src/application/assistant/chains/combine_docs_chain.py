from collections.abc import Coroutine
from typing import Any

import tiktoken
from langchain.chains.combine_documents.base import BaseCombineDocumentsChain
from langchain_core.documents import Document

from src.context import AppContext


class AggregateDocsChunksChain(BaseCombineDocumentsChain):
    context: AppContext
    aggregate_max_token_number: int = 2000
    """The maximum token length of the combined documents, if exceeded a warning will be logged."""
    tokenizer_model_name: str = "gpt-3.5-turbo"
    """The language model to use for tokenization."""

    tokenizer: tiktoken.Encoding = tiktoken.encoding_for_model(tokenizer_model_name)

    # pylint: disable=W0236
    def acombine_docs(self, docs: list[Document], **kwargs: Any) -> Coroutine[Any, Any, tuple[str | dict]]:
        return self.combine_docs(docs, **kwargs)

    def combine_docs(self, docs: list[Document], **kwargs: Any) -> tuple[str | dict]:
        combined_text, token_count, limit_exceeded = self._aggregate_docs_until_token_limit(docs)
        if limit_exceeded:
            self.context.logger.warning(f"Combined text length exceeded {self.aggregate_max_token_number} tokens")
        self.context.logger.debug(f"Combined text length: {token_count} tokens")
        return combined_text, {}

    def _aggregate_docs_until_token_limit(self, docs):
        combined_text = ""
        token_count = 0
        limit_exceeded = False
        for doc in docs:
            new_tokens = self.tokenizer.encode(doc.page_content)
            if token_count + len(new_tokens) > self.aggregate_max_token_number:
                limit_exceeded = True
                break
            provenance = self._format_provenance(doc)
            combined_text += f"\n\n{provenance}{doc.page_content}"
            token_count += len(new_tokens)

        if combined_text != "":
            combined_text = f"""
Based on the information provided in this documentation:{combined_text}

---
"""

        return combined_text, token_count, limit_exceeded

    def _format_provenance(self, doc: Document) -> str:
        metadata = doc.metadata
        fields = {
            "Source title": metadata.get("source_title"),
            "Source URL": metadata.get("source_url") or metadata.get("url"),
            "Organization": metadata.get("organization"),
            "Country": metadata.get("country"),
            "Language": metadata.get("language"),
            "Program ID": metadata.get("program_id"),
            "Last verified": metadata.get("last_verified"),
        }
        available = [f"{name}: {value}" for name, value in fields.items() if value]
        return f"[Source metadata: {'; '.join(available)}]\n" if available else ""

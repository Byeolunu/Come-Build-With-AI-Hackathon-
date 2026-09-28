from typing import Any

from attr import dataclass
from langchain.chains.base import Chain
from langchain_community.vectorstores.mongodb_atlas import MongoDBAtlasVectorSearch
from langchain_core.callbacks import CallbackManagerForChainRun
from langchain_core.embeddings import Embeddings
from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel, create_model

from src.context import AppContext

# Domains that host Moroccan programs — docs from these should be prioritized
# for Moroccan users over generic EU/international sources.
COUNTRY_DOMAIN_MAP = {
    "MA": ["marocpme.gov.ma", "finances.gov.ma", "tamwilcom.ma", "maroc.ma", "cri.ma"],
    "TN": ["tunisie.gov.tn", "startup.gov.tn"],
    "SN": ["sn.gouv.sn", "adepme.sn"],
    "CI": ["ci.gouv.ci"],
}


@dataclass
class RetrieverChainConfiguration:
    mongodb_cluster_uri: str
    db_name: str
    collection_name: str
    embeddings: Embeddings
    index_name: str
    embedding_key: str
    relevance_score_fn: str
    text_key: str
    max_number_of_results: int
    max_score_distance: float | None = None
    min_score_distance: float | None = None


class RetrieverChain(Chain):
    context: AppContext
    configuration: RetrieverChainConfiguration

    query_key: str = "query"  #: :meta private:
    output_key: str = "input_documents"  #: :meta private:

    @property
    def input_keys(self) -> list[str]:
        return [self.query_key]

    @property
    def output_keys(self) -> list[str]:
        return [self.output_key]

    def get_input_schema(self, config: RunnableConfig | None = None) -> type[BaseModel]:
        return create_model(
            "RetrieveChainInput",
            **{
                self.query_key: (
                    str,  # query
                    None,
                ),
            },  # type: ignore[call-overload]
        )

    def get_output_schema(self, config: RunnableConfig | None = None) -> type[BaseModel]:
        return create_model(
            "RetrieveChainOutput",
            **{
                self.output_key: (
                    str,  # response
                    None,
                )
            },  # type: ignore[call-overload]
        )

    def _setup_vector_search(self):
        return MongoDBAtlasVectorSearch.from_connection_string(
            connection_string=self.configuration.mongodb_cluster_uri,
            namespace=f"{self.configuration.db_name}.{self.configuration.collection_name}",
            embedding=self.configuration.embeddings,
            index_name=self.configuration.index_name,
            embedding_key=self.configuration.embedding_key,
            relevance_score_fn=self.configuration.relevance_score_fn,
            text_key=self.configuration.text_key,
        )

    def _get_post_filter_pipeline(self):
        if self.configuration.max_score_distance is not None:
            return [
                {
                    "$match": {"score": {"$lte": self.configuration.max_score_distance}},
                }
            ]
        if self.configuration.min_score_distance is not None:
            return [
                {
                    "$match": {"score": {"$gte": self.configuration.min_score_distance}},
                }
            ]
        return None

    def _extract_country_code(self, query: str) -> str | None:
        """Extract country code from the enriched retrieval query."""
        query_lower = query.lower()

        # Try new format: "Funding support programs for MA ..."
        for marker in ("programs for ", "programmes pour "):
            idx = query_lower.find(marker)
            if idx != -1:
                snippet = query_lower[idx + len(marker):].strip()
                candidate = snippet.split()[0].rstrip(".,;")
                if len(candidate) == 2:
                    return candidate.upper()

        # Try old format: "User country: MA."
        for marker in ("user country:", "pays de l'utilisateur:"):
            idx = query_lower.find(marker)
            if idx != -1:
                snippet = query_lower[idx + len(marker):].strip()
                candidate = snippet.split()[0].rstrip(".,;")
                if len(candidate) == 2:
                    return candidate.upper()

        return None

    def _build_fallback_query(self, query: str) -> str | None:
        """
        Build a complementary fallback query to boost KB coverage when the profile
        contains enough signal. The fallback targets the user's country/region and
        general support type rather than any hard-coded program names, so it works
        for any user regardless of sector or location.

        Returns None when the primary query already contains enough signal.
        """
        country_code = self._extract_country_code(query)
        if country_code is None:
            return None  # Not enough profile signal for a meaningful fallback

        # Build a generic fallback that covers financing, grants, and support programs
        # for the user's country — without baking in specific program names.
        return (
            f"financement aide subvention prêt programme entrepreneuriat startup "
            f"micro-entreprise PME {country_code} country:{country_code} "
            f"grant loan support program"
        )

    def _deduplicate(self, documents: list) -> list:
        """Remove duplicate documents based on content hash or first 120 chars."""
        seen: set[str] = set()
        result = []
        for doc in documents:
            identifier = doc.metadata.get("sha") or doc.page_content[:120]
            if identifier not in seen:
                seen.add(identifier)
                result.append(doc)
        return result

    def _rerank_by_country(self, documents: list, country_code: str | None) -> list:
        """
        Re-rank documents so that country-matching docs come first.
        This ensures they fill the token budget in combine_docs_chain
        before less relevant international docs.
        """
        if not country_code or not documents:
            return documents

        priority_domains = COUNTRY_DOMAIN_MAP.get(country_code, [])

        def _is_country_match(doc) -> bool:
            metadata = doc.metadata
            # Check metadata country field
            doc_country = (metadata.get("country") or "").upper()
            if doc_country == country_code:
                return True
            # Check source URL against known country domains
            source_url = metadata.get("source_url") or metadata.get("url") or ""
            for domain in priority_domains:
                if domain in source_url.lower():
                    return True
            # Check page content for strong country signals
            content_lower = doc.page_content[:500].lower()
            country_signals = {
                "MA": ["maroc", "morocco", "marocain", "marocaine", "درهم", "المغرب"],
                "TN": ["tunisie", "tunisia", "tunisien"],
                "SN": ["sénégal", "senegal"],
                "CI": ["côte d'ivoire", "ivory coast"],
            }
            for signal in country_signals.get(country_code, []):
                if signal in content_lower:
                    return True
            return False

        # Split into country-matching and other docs
        country_docs = [d for d in documents if _is_country_match(d)]
        other_docs = [d for d in documents if not _is_country_match(d)]

        self.context.logger.debug(
            f"Re-ranked: {len(country_docs)} country-matching docs first, "
            f"{len(other_docs)} other docs after"
        )

        # Country-matching docs first, then the rest
        return country_docs + other_docs

    def _call(self, inputs: dict[str, Any], run_manager: CallbackManagerForChainRun | None = None) -> dict[str, Any]:
        query = inputs[self.query_key]
        post_filter_pipeline = self._get_post_filter_pipeline()
        vector_search = self._setup_vector_search()

        # Primary retrieval
        result = vector_search.similarity_search(
            query,
            k=self.configuration.max_number_of_results,
            additional={"similarity_score": True},
            post_filter_pipeline=post_filter_pipeline,
        )

        # Profile-driven fallback: if profile signal is present and primary results
        # may not cover the user's local programs, run a generic country-level query.
        country_code = self._extract_country_code(query)
        fallback_query = self._build_fallback_query(query)
        if fallback_query is not None:
            fallback_k = max(self.configuration.max_number_of_results, 4)
            fallback = vector_search.similarity_search(
                fallback_query,
                k=fallback_k,
                additional={"similarity_score": True},
            )
            result = self._deduplicate(result + fallback)

        # Re-rank: put country-matching docs first so they fill the token budget
        # in combine_docs_chain before irrelevant international docs
        result = self._rerank_by_country(result, country_code)

        self.context.logger.debug(f"Retrieved {len(result)} documents for query")
        return {self.output_key: result}

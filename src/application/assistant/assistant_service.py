from dataclasses import dataclass, field

from langchain_community.callbacks.manager import get_openai_callback
from langchain_core.embeddings import Embeddings
from pymongo.uri_parser import parse_uri

from src.application.assistant.chains.assistant_chain import AssistantChain
from src.application.assistant.chains.assistant_prompt import AssistantPromptBuilder, AssistantPromptTemplate
from src.application.assistant.chains.combine_docs_chain import AggregateDocsChunksChain
from src.application.assistant.chains.retriever_chain import RetrieverChain, RetrieverChainConfiguration
from src.application.rag.profile_service import ProfileRepository, extract_profile, merge_profiles, missing_questions
from src.context import AppContext
from src.infrastracture.embeddings_manager.embeddings_manager import EmbeddingsManager
from src.infrastracture.llm_manager.llm_manager import LlmManager


@dataclass
class AssistantServiceChatCompletionResponse:
    response: str
    references: list[dict[str, str]]
    profile: dict | None = None
    missing_questions: list[str] = field(default_factory=list)


@dataclass
class AssistantServiceConfiguration:
    prompt_template: AssistantPromptTemplate


class AssistantService:
    _chain: AssistantChain

    def __init__(self, app_context: AppContext, configuration: AssistantServiceConfiguration = None) -> None:
        """
        Initialize the Assistant Service
        """
        self.app_context = app_context
        self.configuration = configuration or AssistantServiceConfiguration(prompt_template=None)
        self._setup_assistant()

    def _init_embeddings(self):
        return EmbeddingsManager(self.app_context).get_embeddings_instance()

    def _init_llm(self):
        return LlmManager(self.app_context).get_llm_instance()

    def _init_retriever_chain(self, embeddings: Embeddings):
        """
        Initialize the retriever
        """
        vector_store_configurations = self.app_context.configurations.vectorStore
        vector_store_cluster_uri = self.app_context.env_vars.MONGODB_CLUSTER_URI

        db_name = vector_store_configurations.dbName or parse_uri(vector_store_cluster_uri).get("database")

        if db_name is None:
            raise ValueError("Database name is not provided in the configuration or the cluster URI")

        configuration = RetrieverChainConfiguration(
            mongodb_cluster_uri=vector_store_cluster_uri,
            db_name=db_name,
            collection_name=vector_store_configurations.collectionName,
            embeddings=embeddings,
            index_name=vector_store_configurations.indexName,
            embedding_key=vector_store_configurations.embeddingKey,
            relevance_score_fn=vector_store_configurations.relevanceScoreFn,
            text_key=vector_store_configurations.textKey,
            max_number_of_results=vector_store_configurations.maxDocumentsToRetrieve,
            max_score_distance=vector_store_configurations.maxScoreDistance,
            min_score_distance=vector_store_configurations.minScoreDistance,
        )

        retriever_chain = RetrieverChain(context=self.app_context, configuration=configuration)

        return retriever_chain

    def _init_documentation_aggregator(self):
        """
        Initialize the documentation aggregator
        """
        tokenizer_config = self.app_context.configurations.tokenizer
        chain_config = self.app_context.configurations.chain

        return AggregateDocsChunksChain(
            context=self.app_context,
            tokenizer_model_name=tokenizer_config.name,
            aggregate_max_token_number=chain_config.aggregateMaxTokenNumber,
        )

    def _build_prompt(self) -> AssistantPromptTemplate:
        """This function builds the prompt template for the Assistant
        The fallback order is:
        1. Configuration
        2. Configuration file
        3. Default prompt

        # perf: this function at the moment is being called every time the Assistant is initialized and so one time per request
        We should consider caching the prompt template if it is not going to change during the lifetime of the software
        We could achieve this by storing the prompt template content inside app_context and only build it once
        """
        try:
            if self.configuration.prompt_template:
                return self.configuration.prompt_template
        except AttributeError:
            pass
        try:
            if self.app_context.configurations.chain.rag.promptsFilePath:
                builder = AssistantPromptBuilder()
                if self.app_context.configurations.chain.rag.promptsFilePath.system:
                    builder.load_system_template_from_file(self.app_context.configurations.chain.rag.promptsFilePath.system)
                if self.app_context.configurations.chain.rag.promptsFilePath.user:
                    builder.load_user_template_from_file(self.app_context.configurations.chain.rag.promptsFilePath.user)
                return builder.build()
        except AttributeError:
            pass
        return AssistantPromptBuilder().build()  # default prompt

    def _setup_assistant(self):
        # Load the embeddings model
        embeddings = self._init_embeddings()
        # Load the MongoDB Atlas Retriever
        mongo_retriever_chain = self._init_retriever_chain(embeddings=embeddings)
        # Load the documentation aggregator
        aggregate_docs_chain = self._init_documentation_aggregator()
        # Load the LLM
        llm = self._init_llm()
        # Extract the custom template if it exists
        prompt_template = self._build_prompt()
        # Load the Assistant Chain
        self._chain = AssistantChain(
            retriever_chain=mongo_retriever_chain,
            aggregate_docs_chain=aggregate_docs_chain,
            llm=llm,
            prompt_template=prompt_template,
        )

    def chat_completion(
        self,
        query: str,
        chat_history: list[str],
        session_id: str | None = None,
        custom_template_variables: dict[str, str] = None,
    ) -> AssistantServiceChatCompletionResponse:
        """
        Chat completion using Assistant Chain
        """
        if self._is_greeting(query):
            return AssistantServiceChatCompletionResponse(
                response=(
                    "Hello! I’m CivicPilot. Tell me your country or region, your activity or business idea, "
                    "the amount you need, and whether you can repay a loan. I’ll help you compare verified programs."
                ),
                references=[],
                profile=None,
                missing_questions=[],
            )
        profile = None
        profile_questions = []
        if session_id:
            repository = ProfileRepository(self.app_context.env_vars.MONGODB_CLUSTER_URI)
            profile = merge_profiles(repository.get(session_id), extract_profile(query))
            repository.save(session_id, profile)
            profile_questions = missing_questions(profile)
        retrieval_query = query
        if profile:
            country = profile.personal.get("country") or "unknown"
            region = profile.personal.get("region") or "unknown"
            amount = profile.financial_need.get("amount")
            currency = profile.financial_need.get("currency") or ""
            sector = profile.goal.get("sector") or ""
            goal_type = profile.goal.get("type") or ""
            cannot_take_debt = profile.constraints.get("cannot_take_debt")
            debt_pref = (
                "grant or non-repayable support"
                if cannot_take_debt
                else ("loan or guarantee acceptable" if cannot_take_debt is False else "loan or grant")
            )
            amount_str = f"{amount:,.0f} {currency}" if amount else "unspecified"
            retrieval_query = (
                f"Funding support programs for {country} {region}. "
                f"Sector: {sector}. Goal: {goal_type}. "
                f"Amount needed: {amount_str}. Financing preference: {debt_pref}. "
                f"Programs: micro-enterprise SME entrepreneur startup auto-entrepreneur "
                f"honor loan guarantee grant financement aide subvention pret "
                f"Maroc Morocco {country} {region} small business individual support. "
                f"User request: {query}"
            )
        with get_openai_callback() as openai_callback:
            inputs = {self._chain.query_key: retrieval_query, self._chain.chat_history_key: chat_history}
            if custom_template_variables:
                inputs[self._chain.prompt_custom_variables_key] = custom_template_variables

            chain_response = self._chain.invoke(inputs)

            self.app_context.metrics_manager.requests_tokens_consumed.inc(openai_callback.prompt_tokens)
            self.app_context.metrics_manager.reply_tokens_consumed.inc(openai_callback.completion_tokens)

            return AssistantServiceChatCompletionResponse(
                response=chain_response[self._chain.response_key], references=chain_response[self._chain.references_key]
                , profile=profile.model_dump() if profile else None, missing_questions=profile_questions
            )

    @staticmethod
    def _is_greeting(query: str) -> bool:
        normalized = query.strip().lower().strip("!?. ,")
        return normalized in {"hello", "hi", "hey", "bonjour", "salut", "مرحبا", "السلام عليكم"}

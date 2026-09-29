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
        # Handle greetings — return a friendly, helpful intro without touching the RAG chain
        if self._is_greeting(query):
            return AssistantServiceChatCompletionResponse(
                response=self._greeting_reply(query),
                references=[],
                profile=None,
                missing_questions=[],
            )

        # Handle conversational messages (thanks, farewells, etc.) without RAG
        conversational_response = self._conversational_reply(query)
        if conversational_response:
            return AssistantServiceChatCompletionResponse(
                response=conversational_response,
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

        # Default country to Morocco since CivicPilot is primarily designed for Moroccan programs
        country = (profile.personal.get("country") if profile else None) or "Morocco"
        region = (profile.personal.get("region") if profile else None) or "Morocco"
        amount = profile.financial_need.get("amount") if profile else None
        currency = (profile.financial_need.get("currency") if profile else None) or "MAD"
        sector = (profile.goal.get("sector") if profile else None) or ""
        goal_type = (profile.goal.get("type") if profile else None) or ""
        cannot_take_debt = profile.constraints.get("cannot_take_debt") if profile else None
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
            f"Programs: START-TPE Maroc PME micro-enterprise SME entrepreneur startup auto-entrepreneur "
            f"honor loan guarantee grant financement aide subvention pret "
            f"Maroc Morocco {country} {region} small business individual support. "
            f"User request: {query}"
        )

        with get_openai_callback() as openai_callback:
            inputs = {
                self._chain.query_key: query,
                "retrieval_query": retrieval_query,
                self._chain.chat_history_key: chat_history,
            }
            if custom_template_variables:
                inputs[self._chain.prompt_custom_variables_key] = custom_template_variables

            chain_response = self._chain.invoke(inputs)

            self.app_context.metrics_manager.requests_tokens_consumed.inc(openai_callback.prompt_tokens)
            self.app_context.metrics_manager.reply_tokens_consumed.inc(openai_callback.completion_tokens)

            return AssistantServiceChatCompletionResponse(
                response=chain_response[self._chain.response_key],
                references=chain_response[self._chain.references_key],
                profile=profile.model_dump() if profile else None,
                missing_questions=profile_questions,
            )

    @staticmethod
    def _is_arabic(text: str) -> bool:
        return any("\u0600" <= c <= "\u06ff" for c in text)

    @staticmethod
    def _is_french(text: str) -> bool:
        t = text.lower().strip()
        # French greeting prefixes and common typo stems
        french_prefixes = ("bonj", "salu", "couco", "bonso")
        if any(t.startswith(p) for p in french_prefixes):
            return True
        french_clues = (
            "bonjour", "bonsoir", "salut", "merci", "aide", "programme",
            "financement", "subvention", "projet", "argent", "cherche",
            "veux", "comment", "pourquoi", "qui", "oui", "non", "prêt",
            "pret", "créer", "ouvrir", "besoin", "coucou", "slt", "ca va", "ça va",
        )
        return any(c in t for c in french_clues)

    @classmethod
    def _greeting_reply(cls, query: str) -> str:
        if cls._is_arabic(query):
            return (
                "مرحباً بك! 👋 أنا **CivicPilot**، مساعدك الذكي لاستكشاف برامج التمويل والدعم المقاولاتي والمنح في المغرب. 🇲🇦\n\n"
                "لمساعدتك في اختيار البرنامج الأنسب لمشروعك (مثل *START-TPE، انطلاقة، فرصة، المبادرة الوطنية للتنمية البشرية*...)، شاركني:\n"
                "- 📍 **مدينتك أو منطقتك**\n"
                "- 💡 **طبيعة مشروعك أو فكرتك** (مشروع جديد، تجارة، فلاحة، خدمات، تكنولوجيا...)\n"
                "- 💰 **المبلغ التقديري الذي تحتاجه**\n"
                "- 🏦 **تفضيلك** (منحة غير مستردة أم قرض شرف/تمويل بنكي ميسر؟)\n\n"
                "تفضل بشرح فكرتك وسأساعدك فوراً!"
            )
        if cls._is_french(query):
            return (
                "Bonjour ! 👋 Je suis **CivicPilot**, votre assistant d'orientation pour les aides, subventions et financements de projets au Maroc. 🇲🇦\n\n"
                "Pour vous guider vers les programmes les plus adaptés (comme *START-TPE / Maroc PME, Intelaka, Forsa, INDH*...), dites-moi :\n"
                "- 📍 **Votre région ou ville** (ex. Casablanca, Rabat, Marrakech, Tanger...)\n"
                "- 💡 **Votre activité ou projet** (création d'entreprise, commerce, artisanat, tech...)\n"
                "- 💰 **Le montant recherché** (ex. 50 000 DH, 100 000 DH...)\n"
                "- 🏦 **Type d'aide souhaité** : subvention non remboursable ou prêt d'honneur à taux avantageux ?\n\n"
                "Parlez-moi de votre projet !"
            )
        return (
            "Hello! 👋 I'm **CivicPilot**, your guide to verified public funding, grants, loans, and entrepreneurship support programs in Morocco. 🇲🇦\n\n"
            "To help match you with the best programs (such as *START-TPE / Maroc PME, Intelaka, Forsa, INDH*...), please tell me:\n"
            "- 📍 **Your location or region** (e.g., Casablanca, Rabat, Marrakech...)\n"
            "- 💡 **Your business idea or activity** (startup, trade, artisan, agriculture...)\n"
            "- 💰 **The amount you need** (e.g., 50,000 MAD, 100,000 MAD...)\n"
            "- 🏦 **Financing preference** (grant or low-interest / honor loan?)\n\n"
            "Tell me about your project and I'll guide you!"
        )

    @staticmethod
    def _is_greeting(query: str) -> bool:
        """Check if query is a greeting — supports typos and informal variants."""
        normalized = query.strip().lower().strip("!?. ,;:")

        # Exact matches
        exact_greetings = {
            "hello", "hi", "hey", "hii", "hiii", "yo", "sup",
            "bonjour", "bonjouur", "bonjourr", "bonsoir", "salut", "saluut", "coucou", "slt",
            "مرحبا", "السلام عليكم", "اهلا", "سلام", "marhaba",
        }
        if normalized in exact_greetings:
            return True

        # Prefix matches — catches "bonjouur...", "hellooo...", "hiiii...", etc.
        greeting_prefixes = (
            "hello", "hi ", "hey ", "bonjour", "bonsoir", "salut", "coucou",
            "مرحبا", "السلام", "اهلا",
        )
        if any(normalized.startswith(p) for p in greeting_prefixes):
            if len(normalized) < 40:
                return True

        return False

    @staticmethod
    def _conversational_reply(query: str) -> str | None:
        """Return a friendly reply for conversational messages that don't need RAG."""
        normalized = query.strip().lower().strip("!?. ,;:")

        # Thank you
        thank_keywords = {
            "thank", "thanks", "merci", "shukran", "شكرا", "شكرا لك",
            "thx", "ty", "thank you", "merci beaucoup", "thanks a lot",
        }
        if any(kw in normalized for kw in thank_keywords):
            return (
                "You're welcome! 😊 If you have more questions about programs, grants, "
                "or financial aid, feel free to ask anytime."
            )

        # Farewell
        farewell_keywords = {
            "bye", "goodbye", "au revoir", "bbye", "see you", "ciao",
            "مع السلامة", "وداعا", "à bientôt", "a bientot", "bonne journée",
        }
        if any(kw in normalized for kw in farewell_keywords):
            return (
                "Goodbye! Good luck with your project. Come back anytime you need "
                "help finding financial aid or programs. 🙌"
            )

        # How are you / pleasantries
        pleasantry_patterns = [
            "how are you", "comment vas", "comment ça va", "ca va", "ça va",
            "كيف حالك", "labas", "la bas", "how's it going", "what's up",
        ]
        if any(pat in normalized for pat in pleasantry_patterns):
            return (
                "I'm doing great, thank you for asking! 😊 I'm here to help you "
                "find financial aid programs. What would you like to know?"
            )

        # What are you / who are you
        identity_patterns = [
            "who are you", "what are you", "qui es-tu", "c'est quoi",
            "c est quoi", "من أنت", "what can you do", "que fais-tu",
        ]
        if any(pat in normalized for pat in identity_patterns):
            return (
                "I'm **CivicPilot**, your AI-powered financial aid assistant! 🤖\n\n"
                "I help you discover verified grants, loans, training programs, and business "
                "support in Morocco. Just tell me:\n"
                "- 🌍 Your country/region\n"
                "- 💼 Your activity or business idea\n"
                "- 💰 The amount you need\n"
                "- 🏦 Whether you can repay a loan\n\n"
                "And I'll match you with the best programs!"
            )

        return None

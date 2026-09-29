import os

from langchain_core.prompts import ChatPromptTemplate

DEFAULT_SYSTEM_TEMPLATE = """
You are CivicPilot, a trustworthy, welcoming public-benefits and entrepreneurship financial aid assistant primarily dedicated to Morocco.

## Language Rule
- You MUST reply in the EXACT SAME LANGUAGE as the user's latest query ({query}).
  - If the user writes in French (e.g. "bonjour", "je veux savoir les programmes de fundings", "salut"), you MUST reply in natural, fluent French.
  - If the user writes in Arabic (e.g. "مرحبا", "برامج التمويل"), you MUST reply in natural, fluent Arabic.
  - If the user writes in English, reply in English.
- NEVER start your response with a language label like "French:", "Arabic:", "English:". Just start directly with your response text.
- Do not mix languages within a response.

## Welcoming & General Inquiries Rule
- When the user sends a greeting, welcoming, or asks a general funding question (e.g., "bonjour", "je veux savoir les programmes de fundings", "aidez-moi pour un financement"):
  - NEVER say "The knowledge base does not currently contain programs" or "I found nothing on the KB". Such phrases are strictly prohibited.
  - Greet the user warmly and introduce CivicPilot as their guide to verified public funding, grants, loans, and business support programs in Morocco.
  - If source documents describe programs in Morocco (such as START-TPE / Maroc PME prêt d'honneur), highlight them concisely as verified options.
  - Ask 2-3 friendly questions to tailor the recommendation:
    1. 📍 Region or city in Morocco
    2. 💡 Nature of the business or project (startup, commerce, artisanat, agriculture, services...)
    3. 💰 Amount of financing needed
    4. 🏦 Preference between non-repayable grant (subvention) or zero-interest honor loan (prêt d'honneur)

## Fact Accuracy & Sources
- Only state facts, amounts, eligibility, and URLs that appear in the supplied source documents below.
- Do NOT invent fabricated program names or fake URLs.
- Silently omit programs that are strictly EU-only institutional funds (like NIB / InvestEU) when assisting Moroccan entrepreneurs.
- Distinguish clearly between loans (prêts d'honneur, crédits remboursables) and non-repayable grants (subventions).

## Response Format
- Friendly, professional, and well-structured markdown with clear bullet points.
- Under 350 words.

---
{output_text} {chat_history}
Reply in the SAME LANGUAGE as the user's query text ({query}). Do NOT output a language label.
"""


DEFAULT_USER_TEMPLATE = "{query}"


class AssistantPromptTemplate(ChatPromptTemplate):
    @property
    def system_template(self):
        if self.messages[0].prompt.template is None:
            raise ValueError("System template is not defined.")
        return self.messages[0].prompt.template

    @property
    def user_template(self):
        if self.messages[1].prompt.template is None:
            raise ValueError("User template is not defined.")
        return self.messages[1].prompt.template


class RequiredVariableMissingError(Exception):
    def __init__(self, variable):
        super().__init__(f"Required variable '{variable}' is not used in either the system or user template.")


class UserDefinedVariableMissingError(Exception):
    def __init__(self, variable):
        super().__init__(f"User-defined variable '{variable}' is not used in either the system or user template.")


class AssistantPromptBuilder:
    def __init__(self, system_template: str = None, user_template: str = None):
        self.required_variables = [
            "output_text",  # this is the output of the document aggregation chain
            "chat_history",  # this is the chat history, coming from the user,
            "query",  # this is the query from the user
        ]
        self.user_added_variables = []
        self.__system_template = system_template if system_template is not None else DEFAULT_SYSTEM_TEMPLATE
        self.__user_template = user_template if user_template is not None else DEFAULT_USER_TEMPLATE

    @property
    def system_template(self):
        return self.__system_template

    @property
    def user_template(self):
        return self.__user_template

    def add_variable(self, variable):
        if variable in self.required_variables or variable in self.user_added_variables:
            raise ValueError(f"Variable {variable} already exists.")
        self.user_added_variables.append(variable)
        return self

    def _validate(self):
        for variable in self.required_variables:
            wrapped_variable = "{" + variable + "}"
            if wrapped_variable not in self.__system_template and wrapped_variable not in self.__user_template:
                raise RequiredVariableMissingError(variable)
        for variable in self.user_added_variables:
            wrapped_variable = "{" + variable + "}"
            if wrapped_variable not in self.__system_template and wrapped_variable not in self.__user_template:
                raise UserDefinedVariableMissingError(variable)

    def append_to_system_template(self, string):
        self.__system_template += string
        return self

    def append_to_user_template(self, string):
        self.__user_template += string
        return self

    def build(self):
        self._validate()
        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", self.__system_template),
                ("user", self.__user_template),
            ]
        )
        return AssistantPromptTemplate(messages=prompt.messages)

    def _retrieve_prompt_from_file(self, filepath):
        if not os.path.exists(filepath):
            raise FileNotFoundError(f"The file '{filepath}' does not exist.")
        try:
            with open(filepath, encoding="utf-8") as file:
                data = file.read()
            return data
        except OSError as e:
            raise OSError(f"An error occurred while reading the file '{filepath}': {str(e)}")

    def load_system_template_from_file(self, filepath):
        """
        Load the system template from a file. This operation will override the current system template.
        """
        self.__system_template = self._retrieve_prompt_from_file(filepath)

    def load_user_template_from_file(self, filepath):
        """
        Load the user template from a file. This operation will override the current user template.
        """
        self.__user_template = self._retrieve_prompt_from_file(filepath)

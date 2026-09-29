import os

from langchain_core.prompts import ChatPromptTemplate

DEFAULT_SYSTEM_TEMPLATE = """
You are CivicPilot, a trustworthy, helpful public-benefits and entrepreneurship financial aid assistant primarily dedicated to Morocco.

## Language Rule
- You MUST reply in the EXACT SAME LANGUAGE as the user's latest query ({query}).
  - If French, reply in natural, fluent French.
  - If Arabic, reply in natural, fluent Arabic.
  - If English, reply in English.
- NEVER start your response with a language label like "French:", "Arabic:", "English:". Just start directly with your response text.
- Do not mix languages within a response.

## Multi-turn Conversation Rules (CRITICAL)
- **Check conversation context in {chat_history}**:
  - **FIRST MESSAGE ONLY** (when {chat_history} is empty): You may greet the user warmly and introduce CivicPilot.
  - **ONGOING CONVERSATION** (when {chat_history} is NOT empty):
    - **NEVER re-introduce yourself.** NEVER say "Je suis CivicPilot", "Je m'appelle CivicPilot", "Bienvenue chez CivicPilot", or similar introductory phrases.
    - **NEVER repeat greetings.** Do NOT say "Bonjour !" on every subsequent message. Dive directly into answering the user's specific question!
    - **NEVER re-ask for details the user already provided.**
      * If the user already shared their budget (e.g., 1 000 DH), do NOT ask for it again.
      * If the user already shared their activity (e.g., flower shop, fleuriste), do NOT ask for it again.
      * If the user already answered their preference (e.g., "je veux une subvention"), do NOT ask "Préférez-vous un prêt ou une subvention ?".
    - Acknowledge what the user answered (e.g., "Bien noté pour votre préférence d'une subvention non remboursable pour votre projet de fleuriste.") and directly guide them on that basis.

## Handling Inquiries & Sources
- NEVER say "The knowledge base does not currently contain programs" or "I found nothing on the KB".
- Present verified programs from the source documents (e.g. START-TPE Maroc PME prêt d'honneur, Damane Intelak).
- If the user's amount or constraints differ from a program (e.g., START-TPE is an honor loan complementing a bank loan, whereas the user wants a grant for 1,000 DH), explain this clearly and honestly, and guide them on what programs or alternatives (such as INDH, micro-finance, or regional subventions) apply.
- Silently omit EU-only institutional funds (like NIB / InvestEU) when assisting Moroccan users.
- Distinguish clearly between loans (prêts d'honneur, crédits remboursables) and non-repayable grants (subventions).

## Response Format
- Clear, well-structured markdown with bullet points.
- Concise, direct, and under 300 words.

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

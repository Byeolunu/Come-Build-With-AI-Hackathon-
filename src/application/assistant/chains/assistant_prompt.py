import os

from langchain_core.prompts import ChatPromptTemplate

DEFAULT_SYSTEM_TEMPLATE = """
You are CivicPilot, a trustworthy public-benefits and entrepreneurship information assistant.

## Language Rule
- Detect the language of the user's LATEST MESSAGE TEXT. If the user writes in English, reply in English. If in Arabic, reply in Arabic. If in French, reply in French.
- The user's nationality does NOT determine the language. A Moroccan user writing in English gets an English reply.
- NEVER start your response with a language label like "Arabic:", "French:", "English:", or "Arabic Response:". Just start with the actual content.
- Do not mix languages within a response.

## Core Rule: Only State Facts From Sources
You may ONLY cite a program name, URL, amount, or eligibility detail if it APPEARS in the supplied source documents below.
- Do NOT invent programs, URLs, or amounts not present in the sources.
- If unsure whether a fact is in the sources, do not state it.
- The user will act on your advice with real money — accuracy is critical.

## How To Handle The Sources
Read the supplied source text carefully and follow this decision tree:

**STEP 1**: Do ANY of the source documents describe programs in the user's country (e.g. Morocco)?
- YES → Go to STEP 2.
- NO → Go to STEP 3.

**STEP 2** (Sources contain programs for user's country):
Present each relevant program as a **KB result** (NOT as "general guidance"). For each:
1. Program name and support type (from source)
2. Why it may fit the user's situation
3. Key caveat — if the user's amount is below the program's typical scale, say so honestly but still present the program. Example: "Your 3,000 DH is below the program's typical credit range, but you should inquire directly."
4. Source URL (exactly as in the source)

**STEP 3** (Sources contain NO programs for user's country — only foreign/EU programs):
1. Say: "The knowledge base does not currently contain programs for [country]."
2. Suggest the user check their country's official entrepreneurship/finance portals.
3. Ask 1-2 clarifying questions.
Do NOT invent program names or URLs in this case.

## Loans vs. Grants
- Never call a loan or credit guarantee a "grant."
- State repayment obligations when the source mentions them.
- Keep bank-loan and honor-loan amounts separate.

## Geographic Filtering
- Silently omit programs that are explicitly EU-only institutional or large-scale infrastructure funds with no individual/SME applicant path.
- ALWAYS present Moroccan programs (finances.gov.ma, marocpme.gov.ma) to Moroccan users.

## Response Format
- At most 3 programs, ranked by relevance to the user.
- For each: (1) support type, (2) why it may fit, (3) key caveat, (4) source URL.
- End with at most 3 concrete next steps.
- Under 400 words total.

---
{output_text} {chat_history}
Reply in the SAME LANGUAGE as the user's query text above. Do NOT output a language label.
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

# CivicPilot — Full Architecture and Models

## Product goal

CivicPilot helps unemployed people and small entrepreneurs find verified grants, loans, training, guarantees, and business support in English, French, or Arabic. It extracts a user's profile, asks missing questions, retrieves programs, compares requirements and risks, and produces a source-backed checklist.

## High-level architecture

```text
User /ui
  -> FastAPI REST API
  -> profile extraction and MongoDB user_profiles
  -> query + profile-aware retrieval
  -> MongoDB Atlas Vector Search (Hackathons)
  -> context aggregation
  -> LLM prompt and source-backed answer
```

Knowledge-base ingestion:

```text
Official URL or PDF
  -> HTML/PDF text extraction
  -> semantic chunking
  -> embeddings
  -> Hackathons collection
```

## Main code structure

```text
src/
├── app.py                                      # FastAPI app and /ui
├── api/controllers/chat_completions/           # Chat endpoint
├── api/controllers/embeddings/                 # URL/PDF ingestion
├── api/schemas/                                # Pydantic API models
├── application/assistant/
│   ├── assistant_service.py                    # Main orchestration
│   └── chains/
│       ├── retriever_chain.py                  # MongoDB retrieval
│       ├── assistant_chain.py                  # Retrieval + prompt + LLM
│       ├── assistant_prompt.py                 # CivicPilot rules
│       └── combine_docs_chain.py               # Context aggregation
├── application/embeddings/
│   ├── embedding_service.py                    # Ingestion orchestration
│   ├── document_chunker.py                     # Semantic chunks
│   └── file_parser/                            # PDF/text/archive parsing
├── application/rag/
│   ├── models.py                               # UserProfile and program models
│   ├── profile_service.py                      # Extract/merge/save profile
│   ├── eligibility.py                          # MATCHED/MISSING/NOT_MATCHED
│   └── opportunity_catalog.py                  # Structured opportunity model
├── infrastracture/                             # LLM/embedding factories
└── ui/index.html                               # Chat interface
```

## Models used

### Chat model

Configured in `default.configuration.json`:

```json
{
  "type": "openai",
  "name": "nvidia/nemotron-3.5-lightning-30b-a3b",
  "baseUrl": "https://integrate.api.nvidia.com/v1",
  "temperature": 1,
  "maxTokens": 2048,
  "enableThinking": false
}
```

The project uses LangChain's `ChatOpenAI` with NVIDIA's OpenAI-compatible endpoint. Thinking is disabled for faster demo responses.

### Embedding model

```json
{
  "type": "openai",
  "name": "nvidia/nemotron-3-embed-1b",
  "baseUrl": "https://integrate.api.nvidia.com/v1"
}
```

The configured vector dimension is `2048`. Use passage embeddings for ingestion and query embeddings for user questions when supported by the provider.

### Supporting libraries

- LangChain: chains, prompts, documents, and MongoDB vector integration.
- PyMuPDF: PDF text extraction.
- BeautifulSoup: HTML text extraction.
- SemanticChunker: semantic document splitting.
- Pydantic: API, profile, and opportunity validation.
- PyMongo: MongoDB persistence.

## Knowledge-base ingestion

### URL endpoint

```http
POST /embeddings/generate
Content-Type: application/json
```

```json
{
  "url": "https://www.finances.gov.ma/fr/intelaka/Pages/intelaka.aspx",
  "country": "MA",
  "language": "fr",
  "source_type": "official_web",
  "support_types": ["loan", "guarantee", "financing"],
  "section": "program_overview"
}
```

### PDF endpoint

```http
POST /embeddings/generateFromFile
Content-Type: multipart/form-data
```

```powershell
curl.exe -X POST "http://localhost:3000/embeddings/generateFromFile" `
  -F "file=@C:\path\to\damane-intelak.pdf" `
  -F "source_title=Damane Intelak" `
  -F "organization=Tamwilcom" `
  -F "country=MA" `
  -F "language=fr" `
  -F "source_type=official_pdf" `
  -F "support_types=loan,guarantee,financing" `
  -F "program_id=damane-intelak" `
  -F "last_verified=2026-09-27"
```

### Chunking

`DocumentChunker` uses:

```python
SemanticChunker(
    embeddings=embedding,
    breakpoint_threshold_type="percentile"
)
```

Each chunk receives a SHA identifier and source metadata.

Example vector document:

```json
{
  "text": "Extracted official source passage...",
  "embedding": [0.01, -0.04, "..."],
  "metadata": {
    "sha": "...",
    "source_url": "https://official-source.example/program",
    "source_title": "Program title",
    "organization": "Official organization",
    "country": "MA",
    "language": "fr",
    "source_type": "official_pdf",
    "support_types": ["loan", "guarantee"],
    "program_id": "program-id",
    "last_verified": "2026-09-27"
  }
}
```

## MongoDB design

```text
come_build_with_ai
├── Hackathons       # text chunks, embeddings, and source metadata
└── user_profiles    # structured user profiles by session_id
```

### Atlas Vector Search index

```json
{
  "fields": [
    {"type": "vector", "path": "embedding", "numDimensions": 2048, "similarity": "cosine"},
    {"type": "filter", "path": "metadata.country"},
    {"type": "filter", "path": "metadata.language"},
    {"type": "filter", "path": "metadata.source_type"},
    {"type": "filter", "path": "metadata.support_types"},
    {"type": "filter", "path": "metadata.program_id"}
  ]
}
```

The organization's country is not automatically the applicant's eligibility country. Geographic eligibility must be established from the source content.

### User profile document

```json
{
  "session_id": "demo-user-001",
  "profile": {
    "personal": {"country": "MA", "region": "Casablanca-Settat"},
    "employment": {"status": "unemployed"},
    "goal": {"type": "start_business", "sector": "food", "description": "bakery"},
    "financial_need": {"amount": 30000, "currency": "MAD"},
    "constraints": {"cannot_take_debt": null},
    "missing_information": ["constraints.cannot_take_debt"]
  },
  "created_at": "2026-09-27T12:00:00Z",
  "updated_at": "2026-09-27T12:00:00Z"
}
```

The `user_profiles` collection is created automatically on the first upsert. Profiles are not embedded in the vector collection.

## User-profile and chat flow

```text
User message
  -> extract high-confidence profile fields
  -> merge with profile saved under session_id
  -> calculate missing fields
  -> ask follow-up questions
  -> retrieve programs using the profile and request
  -> evaluate requirements
  -> generate concise source-backed answer
```

Use the same `session_id` for follow-up messages:

```json
{
  "session_id": "demo-user-001",
  "chat_query": "I live in Casablanca and I cannot take a loan.",
  "chat_history": []
}
```

### Eligibility states

```text
MATCHED      # profile explicitly satisfies the requirement
MISSING      # insufficient profile information
NOT_MATCHED  # profile explicitly contradicts the requirement
```

`MISSING` must never be treated as approval or rejection.

## API contract

### Chat request

```json
{
  "session_id": "demo-user-001",
  "chat_query": "I need financing for a bakery in Casablanca.",
  "chat_history": []
}
```

### Chat response

```json
{
  "message": "...",
  "references": [{"content": "...", "url": "https://official-source.example/program"}],
  "profile": {"employment": {"status": "unemployed"}},
  "missing_questions": ["Can you repay a loan, or do you only want grants?"]
}
```

## Answer and safety rules

CivicPilot should:

- answer only in the latest user's language;
- never output parallel translations unless requested;
- never call a loan or guarantee a grant;
- keep amounts attached to the correct product;
- distinguish organization country from applicant eligibility geography;
- never invent deadlines, documents, fees, interest rates, phone numbers, or approval decisions;
- return at most three opportunities and three next steps;
- cite the source URL beside the supported claim;
- omit corrupted, irrelevant, or unsupported retrieved text.

## Local development

Use Python 3.11–3.13; the locked native dependencies are not compatible with Python 3.14.

```powershell
uv venv --python 3.11
uv sync
uv run --env-file local.env python -m src.app
```

Open the UI at:

```text
http://localhost:3000/ui
```

Real API keys belong in `local.env` or a secret manager and must never be committed.

# CivicPilot: what the template is missing

## Current architecture

The repository already provides the generic RAG path:

`URL/PDF upload -> text extraction -> chunking -> embeddings -> MongoDB Atlas vector search -> LLM answer`

MongoDB Atlas is currently used as the vector store. Each chunk is stored with its embedding, text, and metadata, and the retriever finds semantically similar chunks. MongoDB is **not** the place to store the original PDFs in this design.

## The CivicPilot deficit

The generic template does not yet know what an opportunity is. It needs:

1. A normalized opportunity record: `program_id`, name, organization, country/region, support type, sector, amount/currency, deadline, requirements, documents, repayment/fees, official URL, and status.
2. Provenance on every chunk: source URL or object-storage key, title, page number, language, retrieved date, and last-verified date.
3. Profile extraction and missing-question logic for country, region, employment, business stage, amount, sector, debt tolerance, and documents.
4. Deterministic requirement evaluation. Unknown values must remain `MISSING`; they must never be treated as eligible.
5. A response contract that compares opportunities and exposes risks, not just a fluent paragraph.
6. Freshness and trust controls: prefer official government/partner sources, show stale or unverified records, and never present expired programs as active.

This commit adds the first two building blocks: CivicPilot safety instructions in the system prompt and arbitrary provenance metadata on every embedded chunk.

## Where to store things

| Data | Recommended location | Why |
|---|---|---|
| Original PDFs | S3/MinIO/Azure Blob (or a local `data/source-documents/` folder for the hackathon) | Durable file storage; MongoDB documents should not contain large binaries |
| Web pages | Keep the canonical URL; optionally save a fetched HTML snapshot in object storage | The URL is the authoritative click-through source |
| Extracted text chunks + embeddings | MongoDB Atlas Vector Search collection | Semantic retrieval and source metadata live together |
| Normalized program records | MongoDB normal collection, e.g. `programs` | Filtering by country, support type, status, amount, and deadline is easier than vector search |
| User sessions/profiles | MongoDB `sessions` collection, with consent and retention rules | Enables follow-up questions without putting PII in embeddings |

For this project, use database `come_build_with_ai` and keep the existing vector collection `Hackathons`. Store profiles in a separate `user_profiles` collection in the same database. For a fast demo, keep PDFs in `data/source-documents/`, ingest them through `/embeddings/generateFromFile`, and attach `program_id`, `source_title`, `source_url`, `language`, `country`, `document_type`, `last_verified`, and `page` metadata. For production, replace the local folder with object storage.

## Recommended demo flow

1. Seed 5–10 verified Moroccan opportunities from official sources.
2. Store one normalized JSON record per opportunity and ingest its PDF/web text into the vector collection.
3. Ask the user for missing profile fields before retrieval when they materially affect eligibility.
4. Apply metadata filters first (country/status/support type), then semantic retrieval.
5. Return a comparison with `MATCHED`, `MISSING`, and `NOT_MATCHED` requirements, risks, official links, and a checklist.

Do not commit API keys. The current `default.env` contains a credential-shaped value; rotate it and keep real secrets only in an ignored `.env` or secret manager.

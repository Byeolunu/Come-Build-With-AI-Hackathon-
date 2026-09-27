# Contrat de données — `analyze_case` et `find_programs`

Règle d'équipe : **ajouts seulement**. Aucun champ n'est supprimé ni renommé.

## 1. Entrée : `analyze_case(message, profile=None, language=None)`

| Paramètre | Type | Sens |
|---|---|---|
| `message` | str | Message de l'utilisateur (fr, ar, darija ou en). |
| `profile` | dict \| None | `user_profile` renvoyé au tour précédent (None au premier tour). |
| `language` | str \| None | `language` renvoyé au tour précédent. |

Entre deux tours, le backend renvoie simplement `user_profile` et `language` tels quels.

## 2. Sortie

Toujours présents : `status`, `language`, `user_profile`, `trace`.

| `status` | Champs en plus | Exemple |
|---|---|---|
| `needs_info` | `question` : une seule question, dans la langue de l'utilisateur | [examples/needs_info.json](../examples/needs_info.json) |
| `complete` | `programs`, `final_response` | [examples/complete.json](../examples/complete.json) |
| `error` | `error` : message technique (à ne pas afficher tel quel) | [examples/error.json](../examples/error.json) |

`needs_info` couvre aussi le recentrage (hors-sujet, injection) : `question` contient alors un message poli, et `trace.guard` est rempli.

### `final_response` (si `complete`)

| Champ | Type | Origine |
|---|---|---|
| `summary` | str | LLM (réécrit par `sanitize`) ; texte de secours si absent |
| `recommendations[]` | voir ci-dessous | LLM, filtré par `verify` |
| `action_plan[]` | `{step, program_id, source_url}` | LLM ; `program_id` / `source_url` mis à `null` s'ils n'existent pas dans `programs` |
| `assumptions[]` | str | LLM (suppositions, séparées des faits) |
| `checklist` | `{programs[], all_documents[]}` | **Code** (`build_checklist`) |
| `disclaimer` | str | **Code** (texte fixe par langue) |

`recommendations[]` : `{program_id, match_label, why, missing[], risks[], program_name, type, sources[]}`
- `program_name`, `type`, `sources` sont **recopiés depuis `find_programs`**, jamais depuis le LLM.
- Pour tout crédit (`microcredit`, `loan`, `credit`), `risks` contient les avertissements du programme et le risque de remboursement.
- Si `constraints.cannot_take_debt = true`, aucun crédit n'apparaît, ni dans `recommendations` ni dans `action_plan`.

`checklist.programs[]` : `{program_id, program_name, documents[], deadline, contact, source_url}` pour chaque programme recommandé. `checklist.all_documents` : tous les documents, sans doublon.

## 3. Profil (`user_profile`, format imbriqué de l'équipe)

```
personal{age, country, region, city}
employment{status, occupation}
goal{type, sector, description, stage}
financial_need{amount, currency, purpose}
business{existing, has_business_plan, has_business_registration}
experience{relevant_experience, skills[]}
eligibility{student, low_income, disability, refugee, rural_resident}
constraints{cannot_take_debt, other[]}
missing_information[]
```

| Champ | Valeurs autorisées |
|---|---|
| `employment.status` | `unemployed` \| `employed` \| `self_employed` \| `student` \| `informal` |
| `goal.type` | `start_business` \| `grow_business` \| `training` \| `savings` \| `credit` \| `job_search` |
| `goal.stage` | `idea` \| `planning` \| `operating` |
| `personal.country` | `"MA"` (par défaut) |
| `financial_need.currency` | `"MAD"` (par défaut) |
| `personal.age` | entier de 15 à 99, sinon `null` |
| `financial_need.amount` | nombre > 0, sinon `null` |

Toute valeur hors liste devient `null` (`normalize`). `missing_information` liste les champs obligatoires encore vides, dans l'ordre où ils seront demandés : `personal.city`, `personal.age`, `employment.status`, `goal.type`, puis `financial_need.amount` (seulement si `goal.type` implique un financement ou est inconnu).

Les champs `eligibility.disability`, `refugee` et `low_income` ne sont jamais demandés.

## 4. `trace` : sens de chaque champ

| Champ | Présent | Sens |
|---|---|---|
| `model_used` | toujours | `{extraction, answer}` : modèle réellement utilisé à chaque étape. `null` = aucun LLM (raccourci, garde, réponse de secours). |
| `pii_redacted` | toujours | `true` si un CIN, un téléphone ou un numéro de compte a été masqué avant l'envoi au LLM. |
| `extract_shortcut` | si pas de garde | `true` si une réponse purement numérique (âge, montant) a été traitée sans LLM. |
| `guard` | si recentrage | `"injection"` (bloqué avant le LLM) ou `"off_topic"`. |
| `extract_ms` | après extraction | Durée de l'extraction (ms). |
| `retrieval_ms` | si recherche | Durée de `find_programs` (ms). |
| `answer_ms` | si `complete` | Durée de la rédaction et de la vérification (ms). |
| `llm_fallback_used` | si recherche réussie | `true` si la réponse vient de `fallback_answer` (sans LLM). |
| `invalid_programs` | si besoin | `[{index, id, reason}]` : programmes de `rag.py` mal formés, ignorés. |
| `error_stage` | si `error` | `"extraction"` (LLM indisponible) ou `"retrieval"` (`find_programs` a planté). |

## 5. `find_programs(profile)` (Person 3)

Reçoit le `user_profile` complet et renvoie `{"programs": [...]}`. La référence exacte est le mock du bloc 4 de `civicpilot_orchestrator.py`.

| Champ | Obligatoire | Contrôle (`validate_programs`) |
|---|---|---|
| `id`, `name`, `type` | oui | chaînes non vides, `id` unique |
| `match_status` | oui | `likely_match` \| `partial` \| `no_match` |
| `sources[]` | oui | liste non vide de `{url, verified_on, excerpt}`, `url` commençant par `http` |
| `matched_requirements[]`, `missing_requirements[]`, `failed_requirements[]`, `warnings[]`, `documents[]` | non | `[]` par défaut |
| `provider`, `amount_range`, `deadline`, `contact` | non | recopiés tels quels |

Un programme qui ne passe pas le contrôle est ignoré et signalé dans `trace.invalid_programs`. Si `find_programs` lève une exception, `analyze_case` renvoie `status: "error"` avec `trace.error_stage = "retrieval"`.

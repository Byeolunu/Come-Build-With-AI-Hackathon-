# CivicPilot — Person 2 (AI workflow & orchestration)

## Contexte
Hackathon GOMYCODE × NVIDIA "Come Build with AI", 27 septembre 2026. Soumission avant **17:30 (heure du Maroc)**.
CivicPilot est un navigateur d'inclusion financière : un utilisateur décrit sa situation en français, arabe,
darija ou anglais ; CivicPilot extrait son profil, pose les questions manquantes, cherche des programmes officiels
(subventions, microcrédit, formations), vérifie l'éligibilité et produit un plan d'action sourcé.

Équipe de 5 : Person 1 produit/soumission, **Person 2 = moi (orchestration IA)**, Person 3 RAG + règles
d'éligibilité (`rag.py` → `find_programs(profile)`), Person 4 backend (`/analyze-case`), Person 5 frontend.

## Fichiers
- `civicpilot_orchestrator.py` : mon livrable. Point d'entrée unique `analyze_case(message, profile=None, language=None)`.
- `test_person2.py` : 10 tests de fiabilité, affiche un tableau ✅/❌ + temps.
- `rag.py` : fourni par Person 3 (absent au début → mock intégré dans l'orchestrateur, bloc 4).
- `.env` : `GROQ_API_KEY`, `LLM_PROVIDER=groq`, `LLM_MODEL=openai/gpt-oss-120b`. **Ne jamais lire à voix haute, afficher, copier ni committer.**

## Environnement
- Windows + PowerShell. Venv du projet : `venv\Scripts\activate` (attention : ne pas utiliser le venv d'un autre projet).
- Lancer : `python civicpilot_orchestrator.py` (démo 2 tours) et `python test_person2.py` (tests).
- LLM via API compatible OpenAI (Groq). Chaque appel coûte du quota : éviter les boucles d'appels inutiles.
- Espace disque limité : ne pas installer de grosses dépendances (pas de torch, pas de modèles locaux).

## Contrat de données — NE PAS CASSER
Person 3, 4 et 5 dépendent de ces formats. Toute modification doit rester **rétrocompatible** (ajout de champs OK,
suppression ou renommage interdits).

Profil (format de l'équipe, imbriqué) : `personal{age,country,region,city}`, `employment{status,occupation}`,
`goal{type,sector,description,stage}`, `financial_need{amount,currency,purpose}`,
`business{existing,has_business_plan,has_business_registration}`, `experience{relevant_experience,skills[]}`,
`eligibility{student,low_income,disability,refugee,rural_resident}`, `constraints{cannot_take_debt,other[]}`,
`missing_information[]`.

Valeurs autorisées : `employment.status` ∈ unemployed|employed|self_employed|student|informal ;
`goal.type` ∈ start_business|grow_business|training|savings|credit|job_search ; `goal.stage` ∈ idea|planning|operating ;
`personal.country` = "MA" ; `financial_need.currency` = "MAD".

Sortie de `analyze_case` :
- `status` ∈ needs_info | complete | error
- `language`, `user_profile`, `trace`
- si needs_info : `question`
- si complete : `programs`, `final_response{summary, recommendations[{program_id, match_label, why, missing, risks, program_name, type, sources}], action_plan[{step, program_id, source_url}], assumptions[], checklist{programs[], all_documents[]}, disclaimer}`

Format attendu de `find_programs(profile)` : voir la fonction mock (bloc 4) — c'est la référence exacte.

## Principes d'architecture (argument clé pour le jury)
1. Le LLM n'intervient qu'à 2 étapes : **extraction** du profil et **rédaction** de l'explication.
2. Tout le reste est **déterministe** : validation, questions de clarification, fusion du profil,
   règles d'éligibilité (Person 3), vérification anti-hallucination, checklist.
3. Si le LLM désobéit à une règle du prompt, on ajoute une **vérification dans le code**, pas seulement dans le prompt.
4. Si le LLM tombe en panne à l'étape réponse → `fallback_answer` : la démo continue.

## Règles de sécurité et d'éthique (Responsible AI = 10 pts)
- Jamais "approuvé", "accepté", "garanti", "vous êtes éligible" → toujours "semble correspondre", "à confirmer".
- Ne jamais supposer le genre de l'utilisateur.
- Les champs `eligibility.disability`, `refugee`, `low_income` ne sont **jamais demandés ni déduits** : remplis seulement si l'utilisateur le dit.
- Aucun programme, montant, délai ou lien inventé : seuls ceux retournés par `find_programs` sont gardés.
- Si `constraints.cannot_take_debt` est vrai : aucun crédit recommandé.
- Ne jamais demander ni stocker CIN, numéro de compte, téléphone.
- Pour tout crédit, mentionner le risque de remboursement.

## Façon de travailler attendue
- Proposer un plan court avant de modifier le code, puis avancer **une tâche à la fois**.
- Après chaque modification : relancer `python test_person2.py` et montrer le tableau.
- Changements minimaux et lisibles, commentaires en français, pas de refactor global.
- Ne pas créer de nouveaux fichiers sauf si demandé. Ne jamais modifier `.env`.
- Si un test échoue à cause du LLM (non déterministe), préférer une garde dans le code à une règle de prompt de plus.

## Critères du jury (100 pts)
Problème & valeur 20 · Exécution fonctionnelle 20 · Qualité de l'IA 20 · **Testing & fiabilité 15** ·
Expérience & démo 15 · Responsible AI 10.
# CivicPilot — orchestration IA (Person 2)

**CivicPilot** aide une personne au Maroc à trouver les subventions, microcrédits et formations qui pourraient lui correspondre. Elle décrit sa situation en français, arabe, darija ou anglais ; CivicPilot pose les questions manquantes, cherche des programmes officiels, vérifie l'éligibilité et produit un plan d'action sourcé.

**Rôle de Person 2.** L'orchestration IA : `analyze_case(message, profile, language)` dans `civicpilot_orchestrator.py` (extraction du profil, questions de clarification, appel des règles d'éligibilité de Person 3, rédaction, vérifications), plus l'adaptateur `modules/ai_workflow.py` qui branche cet orchestrateur dans le backend de Person 4.

## Le LLM n'intervient qu'à 2 étapes

1. **Extraction** : texte libre → profil structuré (format de l'équipe).
2. **Rédaction** : explication des programmes retenus, dans la langue de l'utilisateur.

Tout le reste est **déterministe et testé** : validation du profil, questions de clarification, fusion, éligibilité (Person 3), anti-hallucination, checklist.

## Garde-fous (dans le code, pas seulement dans le prompt)

- **Anti-hallucination** : seuls les programmes, montants et liens renvoyés par `find_programs` sont gardés.
- **Formulations prudentes** : jamais « approuvé », « garanti », « vous êtes éligible » → « semble correspondre, à confirmer ».
- **Anti-dette** : si `cannot_take_debt`, aucun crédit n'est recommandé ; tout crédit mentionne le risque de remboursement.
- **Vie privée** : CIN et téléphone masqués avant l'appel au LLM ; handicap, statut de réfugié et faibles revenus jamais demandés ni déduits.
- **Sécurité** : tentatives d'injection bloquées avant le LLM ; messages hors-sujet ignorés.
- **Résilience** : LLM en panne → réponse de secours sans IA ; quota épuisé → modèle de secours.

## Lancer en 3 commandes

```powershell
python -m venv venv; venv\Scripts\activate; pip install -r requirements.txt
copy .env.example .env    # puis mettre sa clé Groq dans .env (jamais committé)
python demo_chat.py       # chat de démo
```

Tests : `python test_person2.py --fast` (orchestrateur) et `python test_adapter.py` (adaptateur, LLM simulé, 0 appel réseau).

## Résultats des tests

| Suite | Score |
|---|---|
| `test_person2.py` (orchestrateur) | **21/21 ✅** |
| `test_adapter.py` (adaptateur backend) | **5/5 ✅** |

## Intégration dans le backend de Person 4

Copier `civicpilot_orchestrator.py` à la racine du backend et `modules/ai_workflow.py` dans `backend/modules/`. `app.py` l'utilise tel quel :

```python
from modules import ai_workflow

profile = ai_workflow.extract_profile(text, language, case=previous_case)        # -> dict compatible schemas.Case
final = ai_workflow.generate_final_response(profile, rag_result, language)       # -> format contracts.py + "question"
```

`extract_profile` lève une exception seulement si le LLM est indisponible (gérée par `app.py`) ; `generate_final_response` ne lève pas : elle bascule sur la réponse de secours. `schemas.py` est copié ici uniquement pour que `test_adapter.py` tourne hors du backend.

## Documentation

| Document | Contenu |
|---|---|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Pipeline, étapes LLM et déterministes, résilience |
| [docs/CONTRACT.md](docs/CONTRACT.md) | Formats d'entrée et de sortie, valeurs autorisées |
| [docs/TESTING.md](docs/TESTING.md) | Tests, latence, incident de quota Groq |
| [docs/RESPONSIBLE_AI.md](docs/RESPONSIBLE_AI.md) | Garde-fous → code → test, limites |
| [examples/](examples/) | Sorties réelles de `analyze_case` : `needs_info`, `complete`, `error` |

CivicPilot donne une orientation, pas une décision officielle. L'éligibilité est toujours à confirmer auprès de l'organisme concerné.

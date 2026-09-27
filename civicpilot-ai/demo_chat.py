"""
CivicPilot — chat terminal pour répéter la démo.
    python demo_chat.py
Garde le profil et la langue entre les tours. Commandes : /nouveau (nouveau cas), /quitter
"""
import sys, textwrap
import civicpilot_orchestrator as o

try:  # emojis et arabe dans la console Windows
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stdin.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass

W = 90
LABELS = {"likely_match": "✅ Semble correspondre", "partial": "🟡 Correspond en partie",
          "no_match": "❌ Ne correspond pas"}


def say(text, indent="   "):
    print(textwrap.fill(str(text), W, initial_indent=indent, subsequent_indent=indent))


def show_trace(t):
    m = t.get("model_used", {})
    names = {"extract_ms": "extraction", "retrieval_ms": "recherche", "answer_ms": "réponse"}
    parts = [f"{n} {t[k]} ms" for k, n in names.items() if k in t]
    info = [f"modèle extraction={m.get('extraction') or '—'}", f"réponse={m.get('answer') or '—'}"]
    if t.get("extract_shortcut"):
        info.append("raccourci sans LLM")
    if t.get("pii_redacted"):
        info.append("données personnelles masquées")
    if t.get("guard"):
        info.append(f"garde : {t['guard']}")
    if t.get("llm_fallback_used"):
        info.append("réponse de secours sans IA")
    if t.get("invalid_programs"):
        info.append(f"{len(t['invalid_programs'])} programme(s) mal formé(s) ignoré(s)")
    print(f"\n   ⏱  {' · '.join(parts + info)}")


def show(r):
    if r["status"] == "error":
        print("\n🤖 CivicPilot : désolé, le service est momentanément indisponible. Réessayez dans un instant.")
        say(f"(détail technique : {r['trace'].get('error_stage')})")
    elif r["status"] == "needs_info":
        print(f"\n🤖 CivicPilot : {r['question']}")
    else:
        fr = r["final_response"]
        print("\n🤖 CivicPilot\n")
        say(fr["summary"], "   ")
        print("\n📋 Recommandations")
        for i, rec in enumerate(fr["recommendations"], 1):
            print(f"\n  {i}. {rec['program_name']}  [{rec['type']}]  {LABELS.get(rec['match_label'], rec['match_label'])}")
            say(f"Pourquoi : {rec['why']}", "     ")
            if rec["missing"]:
                say(f"À fournir : {', '.join(rec['missing'])}", "     ")
            if rec["risks"]:
                say(f"⚠️  Risques : {' | '.join(rec['risks'])}", "     ")
            for s in rec["sources"]:
                say(f"🔗 {s['url']}  (vérifié le {s.get('verified_on', '?')})", "     ")
        if fr["action_plan"]:
            print("\n🗺️  Plan d'action")
            for i, step in enumerate(fr["action_plan"], 1):
                src = f"  🔗 {step['source_url']}" if step.get("source_url") else ""
                say(f"{i}. {step['step']}{src}", "   ")
        if fr["assumptions"]:
            print("\n💭 Suppositions")
            for a in fr["assumptions"]:
                say(f"- {a}", "   ")
        ck = fr["checklist"]
        if ck["all_documents"]:
            print("\n🗂️  Checklist des documents")
            for d in ck["all_documents"]:
                print(f"   ☐ {d}")
            for p in ck["programs"]:
                say(f"{p['program_name']} : échéance {p['deadline'] or '?'} · contact {p['contact'] or '?'}", "   ")
        print()
        say(f"ℹ️  {fr['disclaimer']}", "   ")
    show_trace(r["trace"])


def main():
    print("CivicPilot — décrivez votre situation (fr, ar, darija, en). /nouveau pour recommencer, /quitter pour sortir.")
    profile = language = None
    while True:
        try:
            msg = input("\n👤 Vous : ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not msg:
            continue
        if msg in ("/quitter", "/quit", "/q"):
            break
        if msg in ("/nouveau", "/new"):
            profile = language = None
            print("🔄 Nouveau cas.")
            continue
        r = o.analyze_case(msg, profile=profile, language=language)
        if r["status"] != "error":  # en cas d'erreur, on garde le profil du tour précédent
            profile, language = r["user_profile"], r["language"]
        show(r)


if __name__ == "__main__":
    main()

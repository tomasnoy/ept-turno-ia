---
version: "0.1.2"
level: copilot
processes:
  design: hint
  implementation: copilot
  testing: copilot
  documentation: copilot
  review: assist
  deployment: assist
---

## Notes

- Final project for the AI for Programmers course (UTN FRBA), built by Tomás with the assistance
  of **Claude Code** (Anthropic) as a programming copilot.
- **Design (`hint`)**: architectural decisions were made by the human — AI interprets and
  proposes, traditional logic validates and persists; swappable model layer
  (Ollama/Gemini/Anthropic); multi-tenant schema keyed by `business_id`. The AI suggested
  alternatives when consulted, but did not decide on its own.
- **Implementation and testing (`copilot`)**: Claude Code wrote most of the code and tests based
  on those decisions. Every change was reviewed and approved by the human before being merged;
  the author understands and can explain every part of the system.
- **Documentation (`copilot`)**: the README and other documents were drafted with AI assistance
  and reviewed by the human.
- **Review (`assist`)**: AI-assisted code review passes were used (including a security and
  concurrency review) that flagged specific issues, which were fixed manually. In addition to
  Claude Code, **OpenAI Codex** was used separately for bug-finding review passes over the code.
- **Deployment (`assist`)**: the Render deployment commands and configuration were suggested by
  the AI; the human loaded the secrets (`ADMIN_TOKEN`, `GEMINI_API_KEY`) and carried out the
  sensitive actions.
- All commits in the repository are real and reflect the project's incremental progress.
- Side note: the application itself also uses an LLM as part of its functionality (interpreting
  natural-language appointment requests) through a swappable provider layer (`app/llm/`: local
  Ollama, Gemini, or Anthropic). That is a product feature, distinct from this declaration about
  how the code was built; it is documented in [README.md](README.md).

*Versión en español: [AI-DECLARATION.es.md](AI-DECLARATION.es.md)*

# Built-in glossary sources and review policy

The bundled base glossary is a small deterministic review aid, not a language model and not an automatic rewrite engine.

## Base pack

- Exactly 350 known-wrong forms.
- 43 broadly used Latin/product-format variants.
- 307 Chinese confusion forms covering everyday speech, food, travel, lifestyle, objects, and common idioms.
- No personal names, project names, private paths, account data, or user-specific terms.
- No AI product or AI-development terminology. Load those only with `--domain ai`.

The maintained allowlist lives in `scripts/generate_base_glossary.py`. Generation fails if entries are duplicated, source and suggestion are equal, or the public base leaves the agreed 300–400 range.

## Public references

- [pycorrector](https://github.com/shibing624/pycorrector), Apache-2.0: design reference for custom confusion sets and ASR-oriented correction.
- [macro-correct](https://github.com/yongzhuo/macro-correct), Apache-2.0: candidate comparison source.

The project does not import either upstream dictionary wholesale. Candidate pairs were reduced to short exact forms, reviewed for an unambiguous replacement, and stored only as suggestions. Obvious bad upstream mappings, full-sentence rewrites, single-character substitutions, context-sensitive `的/地/得` rules, and pure Traditional-to-Simplified conversion were excluded.

## Safety boundary

An entry is eligible only when all of these hold:

1. The source form is known-wrong rather than merely unusual.
2. The replacement is unambiguous without audio.
3. Exact substring matching is safe enough to show as a suggestion.
4. The pair is useful outside a single creator niche.
5. A human still confirms the cue-level change at Gate 1.

Correct product names, project vocabulary, personal vocabulary, and contextual grammar belong in domain, project, or personal layers rather than the public base.

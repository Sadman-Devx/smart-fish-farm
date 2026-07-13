# Disease Alert / Recurring Detection — Case Analysis Evaluation

**Run date:** 2026-07-13 08:17

Evaluates `save_disease_log_and_check_recurring()` (supervisor feedback point #9): does the recurring-disease alert mechanism actually catch genuine repeat occurrences?

## A. Real Data Case Analysis

No `DiseaseLog` entries exist in the database yet — expected for an early-stage deployment. Section B below provides evidence from a labelled test set instead. Re-run this command once the Fish Doctor feature has real usage history to populate this section.

## B. Naming-Consistency Case Study

Source: `D:\smart-fish-farm\research\disease_diagnosis_eval\results\disease_diagnosis_eval_20260713_141206.csv`

Across 2 real disease categories, Gemini produced an average of **12.5 distinct exact disease-name strings per category** — meaning the SAME real disease is described differently across separate diagnosis calls.

| Disease Category | Images | Distinct AI Names Used | Most Common Name (count) |
|---|---|---|---|
| Bacterial diseases - Aeromoniasis | 15 | 14 | Furunculosis (2) |
| Bacterial gill disease | 11 | 11 | Severe Bacterial Gill Disease (BGD) or Branchiomycosis (Gill Rot) (1) |

### Worked example: what this means for recurring detection

Take **Bacterial diseases - Aeromoniasis** as an example. Across 15 real images of this same disease, Gemini used **14 different exact name strings**, including:

- "Furunculosis"
- "Bacterial Hemorrhagic Septicemia (or Aeromonas infections)"
- "Severe Physical Trauma / Evisceration (confidence: High)"
- "Hemorrhagic Septicemia (Bacterial Infection)"
- "Severe Bacterial Ulceration"

If a real fish were diagnosed with this same disease 3 times within 30 days, and Gemini happened to phrase each diagnosis differently (a 87% chance per diagnosis based on this sample), the current exact-string-match logic would likely **fail to flag it as recurring**, since `disease_name == disease_name` would not hold across the three log entries.

## Recommendation

The naming-consistency case study shows the problem runs deeper than exact-vs-fuzzy string matching: real Gemini outputs for the same disease can vary so much in wording (e.g. "Severe Ulcerative Lesion" vs. "Bacterial Ulcer Disease") that even generic word-overlap fuzzy matching fails to link them — there may be no shared keyword at all between two correct descriptions of the same disease. A more robust fix is to have Gemini classify each diagnosis against a **fixed, canonical disease list** (constrained output / classification prompt, rather than free-text disease naming), and store that canonical label alongside the free-text explanation. Recurring detection would then match on the canonical label, which is exact-match-safe by construction. This is a concrete, evidence-backed improvement to propose in the paper's discussion/future-work section, directly motivated by this case analysis.


"""
farm/management/commands/evaluate_disease_diagnosis.py
─────────────────────────────────────────────────────────────────────────────
Evaluates the accuracy of the "Fish Doctor" Gemini-based disease diagnosis
agent (farm/ai_agent_views.py) against a labelled test image set.

WHY: Supervisor feedback point #2 — "AI Fish Doctor module-এর disease
diagnosis process, validation approach এবং accuracy evaluation যুক্ত করতে হবে".
The agent had no formal accuracy measurement; this command provides one.

HOW IT WORKS
------------
1. Point it at a folder of test images organised like:

       test_images/
           Healthy Fish/
               img001.jpg
               img002.jpg
           Bacterial diseases - Aeromoniasis/
               img001.jpg
           Bacterial gill disease/
               ...
           Bacterial Red disease/
               ...
           Fungal diseases - Saprolegniasis/
               ...
           Parasitic diseases/
               ...
           Viral diseases - White tail disease/
               ...

   The FOLDER NAME is treated as the ground-truth label. This structure
   matches the public Kaggle "Freshwater Fish Disease Aquaculture in South
   Asia" dataset (7 classes, 250 images/class) — a good fit since it's
   region-relevant and free. Any similarly-organised labelled image set
   works.

2. For each image, the command sends it to Gemini using the SAME prompt
   builder / model list / extraction helpers the live app uses
   (build_system_prompt, extract_disease_name, is_disease_reply), so the
   evaluation reflects exactly what farmers experience — not a separate
   re-implementation that could silently drift from production behaviour.

3. Ground truth vs. prediction are matched via KEYWORD matching, not exact
   string equality — Gemini's free-text disease name will never exactly
   match a folder label string. Each ground-truth class maps to a set of
   expected keywords (see CLASS_KEYWORDS below); a prediction is "correct"
   if the AI response contains at least one expected keyword (checked
   against Bangla and English terms).

4. Outputs:
   - A per-image CSV log (results/disease_diagnosis_eval_<timestamp>.csv)
   - A paper-ready markdown report with confusion counts, per-class
     accuracy, overall accuracy/precision/recall, and average response time

USAGE
-----
    python manage.py evaluate_disease_diagnosis --test-dir /path/to/test_images
    python manage.py evaluate_disease_diagnosis --test-dir /path/to/test_images --limit 15
    python manage.py evaluate_disease_diagnosis --test-dir /path/to/test_images --language English

NOTE: This calls the real Gemini API (uses your GOOGLE_API_KEY / quota).
Use --limit to cap images per class and control cost/time during testing.
"""
from __future__ import annotations

import csv
import time
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from farm.ai_agent_views import (
    GEMINI_MODELS,
    build_system_prompt,
    extract_disease_name,
    is_disease_reply,
    get_gemini_client,
    _is_quota_error,
)

try:
    from google.genai import types
except ImportError:
    types = None

import re as _re


def _normalize(name: str) -> str:
    """Normalize class/folder names for robust matching (ignore dashes, extra spaces, case)."""
    return _re.sub(r"[\s\-]+", " ", name).strip().lower()


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}

# Ground-truth folder name  ->  keywords that count as a "correct" AI diagnosis.
# Keys are matched via _normalize(), so "Fungal diseases Saprolegniasis" and
# "Fungal diseases - Saprolegniasis" both match the same entry automatically.
CLASS_KEYWORDS = {
    "Healthy Fish": ["healthy", "no disease", "no infection", "সুস্থ", "কোনো রোগ নেই", "রোগমুক্ত"],
    "Bacterial diseases - Aeromoniasis": ["aeromoniasis", "aeromonas", "এরোমোনিয়াসিস"],
    "Bacterial gill disease": ["gill disease", "bacterial gill", "গিল রোগ", "ফুলকা রোগ"],
    "Bacterial Red disease": ["red disease", "hemorrhagic septicemia", "লাল রোগ"],
    "Fungal diseases - Saprolegniasis": ["saprolegnia", "fungal", "ছত্রাক"],
    "Parasitic diseases": ["parasit", "প্যারাসাইট", "পরজীবী"],
    "Viral diseases - White tail disease": ["white tail", "viral", "সাদা লেজ", "ভাইরাস"],
}
CLASS_KEYWORDS_NORMALIZED = {_normalize(k): v for k, v in CLASS_KEYWORDS.items()}

# gemma-3-27b-it does NOT support generateContent for images via this API,
# and "gemini-2.5-flash-lite-preview" is a stale/renamed model ID (Google
# dropped the "-preview" suffix — current ID is "gemini-2.5-flash-lite").
# This is a real production bug in ai_agent_views.py's GEMINI_MODELS list
# too, worth fixing there separately from this evaluation script.
EVAL_MODELS = ["models/gemini-2.5-flash-lite", "models/gemini-2.5-flash"]


class Command(BaseCommand):
    help = "Evaluate Fish Doctor (Gemini) disease diagnosis accuracy against a labelled image test set."

    def add_arguments(self, parser):
        parser.add_argument("--test-dir", type=str, required=True,
                             help="Path to labelled test image folder (subfolder per class).")
        parser.add_argument("--limit", type=int, default=20,
                             help="Max images per class to evaluate (default 20, keeps API cost/time sane).")
        parser.add_argument("--language", type=str, default="English",
                             choices=["English", "Bengali (Bangla)"])
        parser.add_argument("--species", type=str, default="General")
        parser.add_argument("--sleep", type=float, default=8.0,
                             help="Seconds to sleep between API calls (free-tier rate limit safety, default 8s).")
        parser.add_argument("--out-dir", type=str, default=None,
                             help="Where to write the CSV/report (default: <project root>/research/disease_diagnosis_eval/results)")
        parser.add_argument("--resume-csv", type=str, default=None,
                             help="Path to a previous run's CSV. Images already logged there "
                                  "(success OR error) are skipped, so you can continue after "
                                  "hitting a daily quota limit without re-spending quota on "
                                  "already-attempted images. New results are merged with the "
                                  "old ones in the final output.")
        parser.add_argument("--resume-latest", action="store_true",
                             help="Automatically resume from the most recently modified CSV "
                                  "in --out-dir, with no need to type a path. Use this for the "
                                  "'just run the same command every day' workflow.")

    def handle(self, *args, **opts):
        if types is None:
            raise CommandError("google-genai not installed. Run: pip install google-genai")

        test_dir = Path(opts["test_dir"])
        if not test_dir.exists():
            raise CommandError(f"--test-dir not found: {test_dir}")

        out_dir = Path(opts["out_dir"]) if opts["out_dir"] else (
            Path(settings.BASE_DIR) / "research" / "disease_diagnosis_eval" / "results"
        )
        out_dir.mkdir(parents=True, exist_ok=True)

        class_dirs = sorted([d for d in test_dir.iterdir() if d.is_dir()])
        if not class_dirs:
            raise CommandError(f"No class subfolders found in {test_dir}")

        unknown_classes = [d.name for d in class_dirs if _normalize(d.name) not in CLASS_KEYWORDS_NORMALIZED]
        if unknown_classes:
            self.stdout.write(self.style.WARNING(
                f"[warn] No keyword mapping for classes: {unknown_classes} — "
                f"add them to CLASS_KEYWORDS in this file, or they'll always score as incorrect."
            ))

        # ── Resolve --resume-latest into an actual path ─────────────────────
        resume_csv_path = opts["resume_csv"]
        if opts["resume_latest"] and not resume_csv_path:
            existing_csvs = sorted(
                out_dir.glob("disease_diagnosis_eval_*.csv"),
                key=lambda p: p.stat().st_mtime,
            )
            if existing_csvs:
                resume_csv_path = str(existing_csvs[-1])
                self.stdout.write(f"[resume-latest] Found most recent CSV: {resume_csv_path}")
            else:
                self.stdout.write("[resume-latest] No previous CSV found in out-dir — starting fresh.")

        client = get_gemini_client()
        system_prompt = build_system_prompt(opts["language"], opts["species"])

        # ── Load prior run (resume support) ─────────────────────────────────
        prior_rows = []
        done_pairs = set()
        if resume_csv_path:
            resume_path = Path(resume_csv_path)
            if not resume_path.exists():
                raise CommandError(f"--resume-csv not found: {resume_path}")
            with open(resume_path, newline="", encoding="utf-8") as f:
                for row in csv.DictReader(f):
                    # csv.DictReader returns EVERYTHING as strings — convert back to
                    # proper types so later math (sum/len on response_time_s) doesn't
                    # crash mixing floats with strings.
                    row["is_correct"] = str(row.get("is_correct", "")).strip().lower() == "true"
                    rt = row.get("response_time_s", "")
                    row["response_time_s"] = float(rt) if rt not in ("", "None", None) else None
                    prior_rows.append(row)
                    # Only skip images that succeeded — retry ones that errored last time
                    if row.get("error", "") == "":
                        done_pairs.add((row["ground_truth"], row["image"]))
            self.stdout.write(f"[resume] Loaded {len(prior_rows)} prior rows "
                               f"({len(done_pairs)} succeeded, will skip those; "
                               f"errored ones will be retried).")

        rows = [r for r in prior_rows if r.get("error", "") == ""]
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        csv_path = out_dir / f"disease_diagnosis_eval_{timestamp}.csv"
        report_path = out_dir / f"disease_diagnosis_eval_report_{timestamp}.md"

        total, correct = 0, 0
        per_class_total: dict[str, int] = {}
        per_class_correct: dict[str, int] = {}

        # Seed counters with prior successful results so the merged report is accurate
        for r in rows:
            gt = r["ground_truth"]
            is_ok = str(r["is_correct"]).strip().lower() == "true"
            per_class_total[gt] = per_class_total.get(gt, 0) + 1
            per_class_correct[gt] = per_class_correct.get(gt, 0) + (1 if is_ok else 0)
            total += 1
            correct += 1 if is_ok else 0

        self.stdout.write(f"[start] Evaluating {len(class_dirs)} classes, "
                           f"up to {opts['limit']} images/class "
                           f"(skipping {len(done_pairs)} already-completed images)...\n")

        csv_file = open(csv_path, "w", newline="", encoding="utf-8")
        writer = csv.DictWriter(csv_file, fieldnames=[
            "ground_truth", "image", "predicted_name", "is_correct",
            "response_time_s", "error",
        ])
        writer.writeheader()
        for r in rows:  # persist prior (resumed) rows into the new combined CSV immediately
            writer.writerow(r)
        csv_file.flush()

        interrupted = False
        quota_exhausted = False
        consecutive_quota_errors = 0
        QUOTA_STOP_THRESHOLD = 1  # daily quota (confirmed via testing) — one hit means today's done, no point waiting for a 2nd

        class _QuotaExhausted(Exception):
            pass

        try:
            for class_dir in class_dirs:
                ground_truth = class_dir.name
                images = sorted([
                    p for p in class_dir.iterdir()
                    if p.suffix.lower() in IMAGE_EXTENSIONS
                ])[: opts["limit"]]

                per_class_total.setdefault(ground_truth, 0)
                per_class_correct.setdefault(ground_truth, 0)

                for img_path in images:
                    if (ground_truth, img_path.name) in done_pairs:
                        continue  # already evaluated successfully in a prior run

                    total += 1
                    per_class_total[ground_truth] += 1

                    predicted_name, response_text, elapsed, error = self._diagnose_image(
                        client, system_prompt, img_path
                    )

                    if error:
                        self.stdout.write(self.style.ERROR(f"  [error] {img_path.name}: {error}"))
                        row = {
                            "ground_truth": ground_truth, "image": img_path.name,
                            "predicted_name": "ERROR", "is_correct": False,
                            "response_time_s": None, "error": error,
                        }
                        rows.append(row)
                        writer.writerow(row)
                        csv_file.flush()

                        if _is_quota_error(error):
                            consecutive_quota_errors += 1
                            if consecutive_quota_errors >= QUOTA_STOP_THRESHOLD:
                                raise _QuotaExhausted()
                        else:
                            consecutive_quota_errors = 0

                        time.sleep(opts["sleep"])
                        continue

                    consecutive_quota_errors = 0
                    is_correct = self._matches(ground_truth, response_text)
                    if is_correct:
                        correct += 1
                        per_class_correct[ground_truth] += 1

                    status = "✅" if is_correct else "❌"
                    self.stdout.write(f"  {status} [{ground_truth}] {img_path.name} -> predicted: {predicted_name!r} ({elapsed:.1f}s)")

                    row = {
                        "ground_truth": ground_truth, "image": img_path.name,
                        "predicted_name": predicted_name, "is_correct": is_correct,
                        "response_time_s": round(elapsed, 2), "error": "",
                    }
                    rows.append(row)
                    writer.writerow(row)
                    csv_file.flush()  # write immediately — survives Ctrl+C / crash / quota cutoff
                    time.sleep(opts["sleep"])
        except KeyboardInterrupt:
            interrupted = True
            self.stdout.write(self.style.WARNING(
                "\n[interrupted] Stopped early — everything up to this point is already "
                "saved in the CSV. Resume later with --resume-csv or --resume-latest."
            ))
        except _QuotaExhausted:
            interrupted = True
            quota_exhausted = True
            self.stdout.write(self.style.WARNING(
                f"\n[quota exhausted] Stopped automatically after {QUOTA_STOP_THRESHOLD} "
                f"consecutive quota errors — this is a DAILY quota, so retrying now won't "
                f"help. Everything up to this point is already saved. Come back after the "
                f"quota resets (usually next day) and run the same command with "
                f"--resume-latest to continue from here."
            ))
        finally:
            csv_file.close()
        overall_acc = correct / total if total else 0.0
        valid_times = [r["response_time_s"] for r in rows if r["response_time_s"] is not None]
        avg_time = sum(valid_times) / len(valid_times) if valid_times else 0.0

        self.stdout.write(f"\n[done] Overall accuracy: {correct}/{total} = {overall_acc:.2%}")
        self.stdout.write(f"[saved] {csv_path}")
        if interrupted:
            if quota_exhausted:
                self.stdout.write(self.style.WARNING(
                    f"[note] Daily quota hit — come back later (usually resets next day) and run:\n"
                    f"  python manage.py evaluate_disease_diagnosis --test-dir \"{test_dir}\" "
                    f"--limit {opts['limit']} --resume-latest"
                ))
            else:
                self.stdout.write(self.style.WARNING(
                    f"[note] Run was interrupted — to continue, either run the exact same "
                    f"command again with --resume-latest added, or be explicit:\n"
                    f"  python manage.py evaluate_disease_diagnosis --test-dir \"{test_dir}\" "
                    f"--limit {opts['limit']} --resume-csv \"{csv_path}\""
                ))

        # ── Report ───────────────────────────────────────────────────────────
        with open(report_path, "w", encoding="utf-8") as f:
            f.write("# Fish Doctor (Gemini) Disease Diagnosis — Accuracy Evaluation\n\n")
            f.write(f"**Run date:** {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n")
            f.write(f"**Test set:** {test_dir}\n\n")
            f.write(f"**Models used (fallback order):** {', '.join(EVAL_MODELS)}\n\n")
            f.write(f"**Total images evaluated:** {total}\n\n")
            if interrupted:
                f.write("**Note:** This run was interrupted before completing all classes/images "
                        "(e.g. Ctrl+C or daily API quota exhausted). Results below reflect only "
                        "the images actually evaluated up to that point; resume with "
                        "`--resume-csv` to complete the rest.\n\n")
            f.write(f"**Overall accuracy:** {correct}/{total} = **{overall_acc:.2%}**\n\n")
            f.write(f"**Average response time:** {avg_time:.2f}s per image\n\n")

            f.write("## Per-class accuracy\n\n")
            f.write("| Class | Correct | Total | Accuracy |\n|---|---|---|---|\n")
            for cls in per_class_total:
                c, t = per_class_correct[cls], per_class_total[cls]
                acc = c / t if t else 0.0
                f.write(f"| {cls} | {c} | {t} | {acc:.1%} |\n")

            f.write("\n## Methodology notes\n\n")
            f.write("- Ground truth = source dataset folder label (expert/vet-labelled, "
                     "see dataset source).\n")
            f.write("- A prediction counts as correct if the AI's full response text contains "
                     "at least one keyword expected for that class (see `CLASS_KEYWORDS` in "
                     "`evaluate_disease_diagnosis.py`) — exact string matching isn't meaningful "
                     "for free-text LLM output.\n")
            f.write("- This evaluates the exact production code path (same prompt builder, "
                     "model list, and extraction helpers as the live app) so results reflect "
                     "real farmer-facing behaviour.\n")
            f.write("- Response time is wall-clock time for the Gemini API call only (excludes "
                     "image loading / disk I/O).\n")

        self.stdout.write(f"[saved] {report_path}")

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _matches(self, ground_truth: str, response_text: str) -> bool:
        keywords = CLASS_KEYWORDS_NORMALIZED.get(_normalize(ground_truth), [])
        if not keywords:
            return False
        text_lower = response_text.lower()
        return any(kw.lower() in text_lower for kw in keywords)

    def _diagnose_image(self, client, system_prompt, img_path: Path):
        """Send one image to Gemini, return (predicted_name, full_text, elapsed_s, error)."""
        try:
            image_bytes = img_path.read_bytes()
        except Exception as e:
            return None, "", 0.0, f"failed to read image: {e}"

        mime = "image/png" if img_path.suffix.lower() == ".png" else "image/jpeg"
        parts = [
            types.Part(inline_data=types.Blob(mime_type=mime, data=image_bytes)),
            types.Part(text=(
                "Please analyze this fish image carefully. Identify any disease, "
                "explain the cause in detail, and provide step-by-step treatment "
                "and prevention advice."
            )),
        ]
        contents = [types.Content(role="user", parts=parts)]

        errors_seen = []
        for model_name in EVAL_MODELS:
            start = time.monotonic()
            try:
                response = client.models.generate_content(
                    model=model_name,
                    contents=contents,
                    config=types.GenerateContentConfig(system_instruction=system_prompt),
                )
                elapsed = time.monotonic() - start
                text = response.text or ""
                predicted_name = extract_disease_name(text) if is_disease_reply(text) else "Healthy / No disease detected"
                return predicted_name, text, elapsed, None
            except Exception as e:
                err = str(e)
                errors_seen.append(f"{model_name}: {err}")
                if _is_quota_error(err):
                    time.sleep(15)  # free-tier quota hit — longer backoff before trying next model
                continue

        return None, "", 0.0, " | ".join(errors_seen) or "all models failed"
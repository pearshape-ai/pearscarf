/**
 * Title extraction for intent bodies.
 *
 * Pearscarf's intent format (per `pearscarf://format/intent`, 1.39.2+) says
 * the first non-empty line of the body IS the intent's title. Authors lead
 * with a single-sentence, ≤120-char actionable phrase; the rest of the body
 * is the agent's pickup brief. We surface that first line everywhere a title
 * is shown.
 *
 * The helper also tolerates two legacy author shapes so we render reasonable
 * titles for intents written before the convention landed:
 *   - markdown heading: `# Some title text`
 *   - labeled prefix:   `Goal: ...`, `Title: ...`, `What: ...`, `Objective: ...`
 *
 * Empty bodies return a stable placeholder so the UI never renders an empty
 * row.
 */

const MAX_TITLE_CHARS = 140;

export function extractTitle(body: string | null | undefined): string {
  if (!body) return "(empty)";
  const firstLine = body.split("\n").find((line) => line.trim().length > 0) ?? "";
  const cleaned = firstLine
    .trim()
    .replace(/^#+\s*/, "") // markdown heading hash
    .replace(/^(title|goal|what|objective|todo)\s*:\s*/i, "") // labeled prefix
    .trim();
  if (!cleaned) return "(empty)";
  return cleaned.length > MAX_TITLE_CHARS
    ? cleaned.slice(0, MAX_TITLE_CHARS).trimEnd() + "…"
    : cleaned;
}

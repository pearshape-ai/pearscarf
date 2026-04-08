## Gmail extraction guidance

Email records are produced by the Gmail connector. Each record has the
following structured fields already stored separately from the body:

- `sender` — the From: header (display name + email)
- `recipient` — the primary To: header
- `subject` — the email subject line
- `received_at` — the server-side received timestamp
- `body` — the plain text body of the message

The `body` is what carries unstructured business knowledge. Extract from
the body, not the headers.

### What to extract from emails

- **People mentioned in the body.** The sender and recipient are already
  in the headers — do not re-extract them as new entities unless they
  also appear by name in the body. Pay attention to people referenced by
  first name only (e.g. "Sarah is going to review this"). Use context to
  decide if they are clearly the same person who appears elsewhere.
- **Companies that are parties to the conversation.** A company mentioned
  in passing (e.g. "we use Stripe for payments") is not a party — skip
  it. A company that the email is about (a customer, vendor, or partner)
  is a party — extract it.
- **Commitments with dates.** Email is the most common place where people
  promise things by a deadline. "I'll send you the proposal by Friday" is
  an ASSERTED/commitment with `valid_until` set to the resolved date.
- **Status updates and decisions.** Threads often contain "we decided X"
  or "Y is now blocked on Z" — these are ASSERTED/decision and
  ASSERTED/blocker facts.
- **Meeting references.** "Demo on Thursday at 2pm" is an event entity
  with a TRANSITIONED/scheduled or ASSERTED/commitment fact attached.

### Email-specific noise to ignore

- Quoted earlier messages (lines starting with `>` or after `On <date>,
  <person> wrote:`) — extract from the new content only, not the quoted
  history.
- Email signatures (anything after `--` or `Best,` / `Regards,` style
  sign-offs).
- Calendar invite metadata blocks (timezones, conference URLs, "join
  Zoom" links).
- Disclaimers and legal footers.
- Tracking pixels and unsubscribe links.
- Auto-replies and out-of-office notices (these are noise records — return
  empty arrays).

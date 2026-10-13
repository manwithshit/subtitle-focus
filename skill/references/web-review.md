# Local web review contract

## Start and resume

```bash
python3 skill/scripts/subtitle_focus.py review-web \
  --plan /abs/project/caption-plan.proposed.json \
  --output-dir /abs/project/edit/subtitles/review \
  --title "项目 · 字幕高亮审核" \
  --terms /abs/project/protected-terms.json \
  --video /abs/project/input.mp4 \
  --sample-seconds 12
```

`--terms` is an optional JSON string array; video is optional. The printed link contains a per-process random token in its fragment. The service binds only `127.0.0.1` with a random free port. Re-run the same command to resume the same persisted session after stopping it; use the newly printed link. A file lock prevents two servers from owning one output folder. A changed plan, source video, style or configuration requires a new output folder. There is no installed daemon, remote upload or external messaging.

Obsidian is optional. Any writable local project folder can be the archive directory; the page displays its absolute path. If you use Obsidian, choose a folder inside its vault to view the same Markdown records there. SRT snapshots preserve text and timing, while exact yellow ranges live in `highlights.json` and the highlighted plan; the Markdown is the readable trace.

With a video the button says **确认并生成样片**. Without a video it says **确认并保存** and only archives the proposal. Neither action accepts the sample or approves full-video rendering.

## State and confirmation

- `session.json` holds the saved draft, revision and active confirmation pointer. It is not itself a human approval certificate.
- Every save checks session id, SRT hash, full plan hash, segment id, exact text and Unicode code-point ranges (`Array.from` / Python string offsets). Ranges must be sorted, in bounds and non-overlapping. Render-plan times are not accepted from the browser.
- Draft saves use optimistic revisions. A stale tab is refused rather than merged or overwritten. Browser backup storage is secondary; server files are the source of truth.
- The confirmation button explicitly confirms both the yellow ranges and all remaining plain choices. Every plain segment is recorded in `plain_overrides`. Parenthetical and policy conflicts are reported; the service never adds filler highlights.
- Confirmation writes the whole bundle to a temporary directory, then publishes `v001/` and advances the current pointer. If any artifact fails, no success is returned. A lost response or pointer-write failure can be recovered by retrying the identical request id; a changed request using that id is rejected.
- Further edits mark the session draft and revoke its active confirmation. Old versions remain readable for history, but their plans fail downstream receipt checks. New confirmation creates `v002/`.
- A receipt records workflow evidence on the local machine; it is not cryptographic proof that the caller is a specific human. Agents must not submit production confirmation requests for the user.

## Archive bundle

Each version contains `字幕原文.srt`, `highlights.json`, `caption-plan.json`, `字幕高亮确认记录.md`, and `receipt.json`. The Markdown uses yellow `<mark>` styling, complete text, per-segment timecodes, confirmation time, source/plan hashes and relative links to that exact version. Original source SRT/video are never rewritten. The snapshot preserves original SRT bytes. The runtime plan still verifies the current locked source; the snapshot does not authorize silently reusing stale approval.

The Markdown records **confirmed highlight proposal / not registered as used in the full video**. Optional `sample-status.json`, `sample.mp4`, `sample-render.log` and `样片生成记录.md` record sample production separately. Full-render use remains governed by Gate 3–5 and the delivery manifest; do not relabel a proposal as delivered merely because a sample exists.

Always use the active version’s archived `caption-plan.json` for downstream commands. The pre-review candidate does not contain the user’s final edits or confirmation receipt.

## Sample handoff

When `--video` is supplied, a successful confirmation launches a fixed local renderer command for 1–30 seconds, starting at the first yellow segment (or the first segment if all plain). The worker cannot accept arbitrary shell commands or arbitrary browser-supplied paths. It records `ready` only after successful rendering, output probing and a fresh receipt check. Errors leave the confirmation archive intact, but must not be described as a ready sample. Restarting the same service retries an unfinished/failed sample. New confirmation during rendering invalidates the old result and queues the new active version.

The page polls local state; an active agent can read the same state on demand. Nothing automatically wakes an ended Codex chat. No full-video render is triggered by this service. Use the normal sample-acceptance gate before a production full render.

## Failure and backup

Use **导出备份** when the service is unavailable. The export is explicitly `confirmed: false`. Import checks source and plan identity and restores a draft; it never imports approval. Refresh a conflicted stale tab only after exporting wanted unsaved edits. The server never exposes arbitrary directories: only fixed assets, the configured video and allowlisted version artifacts. Writes require same-origin JSON plus a random token/cookie; Host and Origin are checked, with no CORS allowance.

Private project text, paths, tokens, screen recordings and confirmation files belong in project output directories, never in the public Skill package. The build script packages only tracked `skill/` files; explicitly stage new template assets before building and inspect the archive inventory.

## QA, without fabricated approval

For user-authorized acceptance testing only, `lock --test-only` marks an exported SRT as a test fixture (`confirmed: false`). `review-web --test-mode` is required for such a fixture; receipts and the UI remain visibly marked test-only. Test plans can render an explicit <=30-second sample but cannot be registered by `deliver` as production. User-operated acceptance and automated browser QA must use different review directories.

Run `python3 -m unittest discover -s tests -v`. `tests/browser_review.cjs <disposable-QA-directory>` expects a `review/connection.json` from the known 13-cue test fixture used for acceptance; it operates a separate Chromium context and must never target a live user session. It checks pointer editing, undo/redo, draft persistence, backup round-trip, connection failure, stale tabs, cancellation, lost-confirmation-response recovery, sample playback and narrow-screen layout.

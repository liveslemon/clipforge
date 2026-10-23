# ClipForge — AI Stream Clipping Platform Blueprint

Oct 17, 2026

## 1. Executive summary and the decision

Build a rights-first clipping tool for **Twitch streamers and the editors they authorize**, launched as a modular monolith (Next.js + FastAPI + Postgres + Redis queue + FFmpeg workers), with uploads as the universal ingestion path and Twitch's official clip APIs as the first integration. "ClipForge" is a working name.

The market is crowded (OpusClip, Vizard, Klap, StreamLadder, Eklipse, Powder, Submagic) and general "long video → shorts" is a commodity priced at roughly $15–$29/month. The defensible wedge is narrower: **stream-native highlight detection (chat + audio + transcript), a creator-authorized editor workflow, and a per-creator feedback loop.** Generic podcast clipping is not where we win.

Three platform facts shape everything (verified 17 Oct 2026, details in section 2):

- **No major source platform lets a third party download full VODs through an official API.** Twitch offers clip creation from VODs and clip downloads for broadcasters/editors; Kick's official API has no VOD endpoints; YouTube's Data API never returns media files. Uploads by the rights-holder are the reliable path.
- **Every publishing API gates public posting behind an audit.** Unaudited TikTok and YouTube apps can only post privately. Audits must start in week 1, not after launch.
- **X is now pay-per-use** and Instagram/Facebook publishing requires professional accounts. Publishing is a feature with per-platform caveats, not a uniform button.

### Strategic decision (section 17 answered up front)

| # | Question | Answer |
| --- | --- | --- |
| 1 | What v1 contains | Upload + Twitch-authorized import; transcription; multi-signal highlight ranking; candidate review; trim editor; vertical reframe (face-aware + split-screen); animated burned-in captions; render + download; YouTube Shorts and TikTok publishing (once audited); usage-metered billing. |
| 2 | Deliberately excluded | Live in-stream clipping, Kick automated import, Instagram/Facebook/X publishing, agency white-label, template marketplace, analytics feedback loop, natural-language search (phase 5), mobile editor (view/approve only). |
| 3 | First integration | **Twitch.** It is the only source with official, sanctioned clip creation from VODs and clip download for editors, plus chat data (via EventSub/IRC while live) that competitors serving podcasts lack. |
| 4 | AI worth paying for | Hosted batch speech-to-text (≈$0.15–$0.26/hour of audio) and a small/medium LLM for clip titling and context-completeness scoring. Everything else starts open-source. |
| 5 | Open-source | FFmpeg, PySceneDetect, MediaPipe/face detection, audio event models (PANNs/YAMNet), pgvector, Whisper (as fallback/self-host once volume justifies a GPU). |
| 6 | Minimum launch budget | **≈ $6k–$15k cash** excluding founder salaries (legal review $2–5k, infra and AI during build and beta ≈ $1.5–3k, design/brand $1–3k, buffer). With paid contractors add $40k–$90k. Estimate, not quote. |
| 7 | Monthly operating cost at launch | **≈ $400–$1,200/month** for ≤ 300 active users (section 22). |
| 8 | Primary revenue tier | **Pro ($29/mo)** — streamers posting daily who need publishing and higher limits. Agency is the margin expansion, not the launch driver. |
| 9 | Differentiation | Chat-aware stream highlights, editor authorization built in (a streamer grants an editor rights in one click), and per-creator learning from actual post performance. |
| 10 | Biggest risks | Commercial: commodity pricing and incumbents copying stream features. Technical: highlight quality on gameplay with little speech. Platform: audit denials, API policy changes, Twitch Clip-from-VOD being beta. |
| 11 | Validate first | 20 streamer/editor interviews; a concierge test (manually clip 5 streamers' VODs with scripts for 2 weeks); price test at $19/$29; whether streamers will grant editor access. |
| 12 | First 30 days | Week 1: audits submitted, upload → transcript → candidates script. Week 2: scoring spike measured against hand-labeled highlights. Week 3: editor + render. Week 4: billing, Twitch OAuth, closed beta with 10 creators. Detail in section 24. |

Biggest honest caveat: highlight scoring predicts *clip-worthiness*, never views. The product must say so in its UI.

## 2. Market, competitors and platform reality

Competitors converge on per-minute-of-source pricing; the opening is stream-specific intelligence and editor workflows, not cheaper clipping.

### 2.1 Competitor landscape

| Product | Focus | Pricing signal | Gap we exploit |
| --- | --- | --- | --- |
| [OpusClip](https://creatify.ai/blog/opusclip-pricing-plans-and-what-you-ll-actually-pay-in-2026) | Podcast/talking-head to shorts | Free; Starter $15/mo; Pro $29/mo ($174/yr); Business custom. 1 credit = 1 source minute | Weak on gameplay with little speech; no chat signal |
| Vizard, Klap, Submagic | Generic repurposing, captions | Similar $15–$40 band (verify before pricing) | Same commodity feature set |
| StreamLadder, Eklipse, Powder | Gaming/stream clips | Freemium + subscription (verify) | Shallow editor-team and rights workflows |
| Manual editors (Premiere, CapCut) | Full control | Labor cost dominates | Hours of VOD review |

Common complaints to validate in interviews (assumptions, not verified data): clips cut mid-sentence, poor gameplay detection, credit burn on long VODs, unreliable auto-publishing, no way to manage many creators.

### 2.2 Source platforms (what the official APIs actually allow)

| Platform | Official capability | Media file? | Live? | Owner auth needed | Our workflow |
| --- | --- | --- | --- | --- | --- |
| **Twitch** | Helix API: Get Videos (metadata), [Create Clip, Get Clips](https://dev.twitch.tv/docs/api/clips/), Get Clips Download (broadcaster/editor), [Create Clip From VOD (open beta)](https://discuss.dev.twitch.com/t/introducing-clip-api-improvements-and-clip-from-vod-in-open-beta/64492) | Full VOD: **no**. Clips: **yes** for broadcaster/editor | Clip from earlier in current stream if VODs enabled | Yes (broadcaster or editor) | Detect moments from chat/metadata → create Twitch clip → download → edit. Full VOD by owner upload |
| **Kick** | Official public API (api.kick.com/public/v1): channels, chat, livestreams, events, OAuth 2.1 + PKCE | **No VOD endpoints.** VOD data only via undocumented website endpoints that may break | Metadata/chat only | Yes | Upload only. Do not build on undocumented endpoints |
| **YouTube** | Data API v3: video metadata, captions (owner), uploads | **No** media download | No ingest | Yes | Owner uploads file (or Google Drive import). Read metadata via API |

Twitch staff state that VOD downloaders violate the Developer Agreement ([forum](https://discuss.dev.twitch.tv/t/download-vods-via-api-or-other-means/28490)). The design never scrapes, never strips DRM, never uses yt-dlp against third-party content.

### 2.3 Publishing platforms

| Destination | Direct publish | Account type | Gate | Limits (verified) |
| --- | --- | --- | --- | --- |
| **TikTok** [Content Posting API](https://developers.tiktok.com/doc/content-sharing-guidelines) | Direct Post or Upload-to-inbox (draft) | Any, via Login Kit | Unaudited: posts forced private, ≤ 5 users/24 h, accounts must be private. Audit required | \~15 posts/creator/day shared across all apps; must query creator\_info before each post; commercial content disclosure UI required |
| **YouTube Shorts** (videos.insert) | Yes; no Shorts flag (≤ 3 min vertical = Short) | Channel owner | Unaudited projects created after 28 Jul 2020: uploads locked private. Compliance audit | 10,000 units/day default; upload quota reported moved to its own bucket (\~100 calls/day) in 2026 — **verify in Cloud Console** |
| **Instagram Reels** [Content Publishing](https://developers.facebook.com/docs/instagram-platform/content-publishing) | Yes, two-step container flow | Professional (Business/Creator) only | Meta App Review; Page Publishing Authorization where required | Docs state both 50 and 100 posts/24 h — enforce 50 and query content\_publishing\_limit; containers expire in 24 h |
| **Facebook Reels** | Yes (Pages) | Page | App Review | Verify per endpoint |
| **X** | Yes | Any | Pay-per-use credits since 6 Feb 2026 | ≈$0.015/post, ≈$0.20 with a link; 100 posts/15 min/user (third-party reports — verify docs.x.com) |

Fallback everywhere: download the file, copy generated caption/hashtags, deep-link to the app.

## 3. Product requirements and workflows

The core loop is import → candidates in under 15 minutes for a 2-hour VOD → edit → render → download or publish.

### 3.1 Personas and jobs

| Persona | Primary job | Launch priority |
| --- | --- | --- |
| Streamer | Turn own VOD into daily shorts with minimal effort | P0 |
| Clip editor | Produce clips for 1–10 streamers who authorized them | P0 |
| Creator manager | Approve and schedule across creators | P2 |
| Clipping agency | Volume, client workspaces, billing | P2 |
| Fan / community | Clip with permission only (Twitch's native Clip rights; creator-run clip programs) | P3 |
| Content business | Repurpose owned webinars/podcasts | P3 (opportunistic) |

### 3.2 Authentication and onboarding

1. Sign up (email+password with verification, or Google/Twitch OAuth). Argon2id hashing; optional TOTP 2FA; passkeys later.
2. Role question: "I clip my own streams" / "I clip for others" / "Team".
3. Defaults: clip length (15–60 s), aspect (9:16), caption style, language.
4. Connect Twitch (optional, recommended). Scopes: `clips:edit` (create clips), `editor:manage:clips` / `channel:manage:clips` for downloads (confirm exact scope names in the Helix reference before build), `user:read:email`.
5. Rights attestation: "I own this content or have the creator's written permission." Stored with timestamp, IP, version of terms.
6. First import with a sample video if they skip.

Declining Twitch connection: upload still works fully. Declining social connections: download + copy-caption flow.

### 3.3 Ingestion workflows

| Path | How | Rights check | Notes |
| --- | --- | --- | --- |
| Local upload | Resumable multipart to S3-compatible storage (tus or S3 multipart, 64 MB parts) | Attestation per asset | Primary path; up to 12 h / 20 GB on paid tiers |
| Cloud import | Google Drive / Dropbox picker (user OAuth) | Attestation | Server pulls the file with user token |
| Twitch authorized | User is broadcaster or editor → list VODs (metadata) → our detector proposes moments → Create Clip From VOD → Get Clips Download | Twitch role verified via API | Clip-level media only; beta endpoint, feature-flagged |
| Twitch URL paste (not own) | Metadata + embed preview only | Must be broadcaster/editor | Otherwise guide user to request editor rights |
| YouTube URL | Metadata via Data API; prompt to upload the original file (Studio download) | Channel ownership check via OAuth | No server download |
| Kick URL | Chat recorded live via official API, synced to the uploaded file (3.8) | Attestation | Re-evaluate if Kick publishes VOD API |
| Live stream | RTMP simulcast to our ingest (3.8), phase 3. Also Twitch "clip earlier in current stream" from chat spikes via EventSub | Broadcaster/editor | No live media ingest |

Duplicate detection: SHA-256 of first+last 16 MB plus duration and size → warn and link to existing asset. Failed uploads resume from last part; sessions expire after 24 h.

### 3.4 Highlight detection pipeline

Scoring combines cheap signals over a sliding window, then an LLM judges only the top \~40 windows.

| Signal | Source | Feasible | Cost |
| --- | --- | --- | --- |
| Transcript (word timestamps) | STT on extracted 16 kHz mono audio | Yes | $0.15–$0.46/h |
| Loudness / RMS spikes, pitch variance, speech rate | FFmpeg ebur128 + librosa | Yes | CPU, negligible |
| Laughter, cheering, screams | YAMNet/PANNs audio-event model | Yes, moderate accuracy | CPU |
| Scene/visual change | PySceneDetect on 2 fps proxy | Yes | CPU |
| Face presence/expression | MediaPipe on facecam crop | Feasible; privacy notice, opt-in for expression | CPU |
| Chat velocity, emote bursts | Twitch chat captured live via EventSub/IRC by our bot with broadcaster consent; no official historical chat API | Only if connected before the stream | Free |
| Game events (kills, wins) | OCR/templates per game | Hard; defer | — |
| Story completeness, hook, novelty | LLM over transcript windows | Yes | ≈$0.01–$0.05 per VOD hour with a small model |

**Clip Quality & Engagement Potential Score (0–100).** The UI states that the score measures hook strength, emotional energy and narrative completeness. It does not predict views, which depend on platform algorithms, posting time and audience size.

For a candidate window w = \[t\_start, t\_end\], five sub-scores are computed, each normalized to \[0, 1\]:

- **Hook strength (S\_hook):** evaluates the first 3.5 s, \[t\_start, t\_start + 3.5 s\], for curiosity gaps, bold claims, immediate vocal intensity or visual shock. Scored by the LLM from the transcript plus audio and visual flags.
- **Emotional and acoustic intensity (S\_energy):**

```latex
S_{energy}(w) = \sigma\left(\alpha_1 \max_{t \in w} Z_{RMS}(t) + \alpha_2 \max_{t \in w} Z_{F_0}(t) + \alpha_3 \, P_{laughter/scream}(w)\right)
```

σ is a calibrated sigmoid. Z\_RMS and Z\_F0 are loudness and pitch z-scores against the stream's own baseline (rolling 10-minute window, so loud streamers aren't always "exciting"). P is the audio-event model's probability.

- **Audience reaction velocity (S\_chat):** computed when a chat log exists:

```latex
S_{chat}(w) = \min\left(1,\; \frac{\text{PeakMsgRate}(w) - \mu_{chat}}{4\,\sigma_{chat}} + 0.25\cdot\mathbb{I}(\text{"clip it" in } w)\right)
```

Floor at 0. Peak rate uses a 5 s sliding window, shifted back 3–8 s to account for chat lag behind the on-stream moment. Without chat, w\_c is redistributed to w\_e and w\_n in proportion to their weights.

- **Narrative and context completeness (S\_narrative):** LLM rating (0–1) of whether a cold TikTok viewer understands the clip without stream context, and whether it has setup, climax and resolution.
- **Pacing and dead-air penalty (P\_dead):** share of the clip's duration in silent stretches longer than 1.2 s (VAD = 0 and low visual motion).

Composite, configurable per creator niche preset:

```latex
C_{score}(w) = \text{clip}_{[0,100]}\left(100\left(w_h S_{hook} + w_e S_{energy} + w_c S_{chat} + w_n S_{narrative} - w_p P_{dead}\right)\right)
```

The positive weights in each preset sum to 1.0, so a perfect clip with no dead air scores 100.

| Niche preset | Hook w\_h | Energy w\_e | Chat w\_c | Narrative w\_n | Dead-air penalty w\_p |
| --- | --- | --- | --- | --- | --- |
| GAMING (competitive FPS/MOBA) | 0.20 | 0.35 | 0.25 | 0.20 | 0.20 |
| JUST\_CHATTING / reaction | 0.30 | 0.25 | 0.20 | 0.25 | 0.25 |
| IRL (provisional) | 0.25 | 0.30 | 0.20 | 0.25 | 0.20 |
| PODCAST / interview | 0.35 | 0.15 | 0.05 | 0.45 | 0.30 |
| EDUCATIONAL (provisional) | 0.35 | 0.10 | 0.05 | 0.50 | 0.30 |

The IRL and EDUCATIONAL rows are starting guesses. All weights are defaults to tune against the hand-labeled set in the week-2 spike. Per-creator weights adapt only after 20 or more published clips (section 7.2). Novelty is not a weight; it is applied as a dedup filter (below).

**Boundaries:** start at the sentence start preceding the peak (search back ≤ 20 s for a transcript sentence boundary, then snap to a silence ≥ 150 ms); end after the reaction settles (audio energy returns to baseline + 1.5 s, ending on a word boundary). Pad 0.3 s; enforce min/max length; never cut inside a word.

**Dedup:** reject candidates overlapping > 40% in time or > 0.85 transcript-embedding similarity with a higher-scored candidate. Reject < 70% speech-or-event coverage, black/frozen frames > 30%, or length outside platform limits.

### 3.5 Clip generation and editing

Browser does: preview (HLS proxy at 720p), timeline trimming, caption text edits, layout selection, safe-zone overlays, undo/redo (command stack), autosave every 5 s. Backend does: all final renders, reframing analysis, waveform/thumbnail strips, transcription.

Edit state is a JSON **render spec** (versioned), so the preview and FFmpeg render read the same document:

```json
{"version":3,"source":"ma_123","in":4521.30,"out":4558.90,"aspect":"9:16","layout":"split","regions":{"face":[1580,40,320,320],"game":[0,0,1920,1080]},"captions":{"style":"bold_pop","position":0.72},"brand":{"logo":"as_9","watermark":false},"audio":{"normalize":-14}}
```

Layouts at launch: centered crop with face-tracking, split-screen (facecam top / game bottom), letterboxed fit. Later: PiP, zoom punches, intros/outros, music library (licensed only, e.g. Epidemic/Artlist business license — verify terms).

Rendering: FFmpeg 7 with libx264 (CPU) at launch; NVENC GPU workers only when queue time breaches SLO. Normalize VFR to CFR (`-fps_mode cfr`), loudness to −14 LUFS, captions burned via libass (ASS file generated from word timings). Fonts bundled in the worker image to avoid missing-font failures. Remotion or browser-side WebCodecs considered and rejected for v1 (licensing cost/complexity, inconsistent device support).

### 3.6 Captioning

| Option | Price | Strength | Weakness |
| --- | --- | --- | --- |
| AssemblyAI Universal-2 batch | ≈$0.15/h | Cheap, diarization, 99 languages | Vendor dependency |
| Deepgram Nova-3 batch | ≈$0.26/h (streaming ≈$0.46/h) | Keyterm prompting, speed | Slightly pricier |
| Whisper large-v3 self-hosted (faster-whisper) | GPU ≈$0.001–$0.002/min at rented rates | No vendor, MIT license | Ops burden; hallucination on silence/music |

Prices from third-party summaries ([convertaudiototext](https://convertaudiototext.com/blog/speech-to-text-api-pricing-2026)); confirm on vendor pages before contracting. Launch on AssemblyAI with Deepgram as failover behind one interface. Custom vocabulary from creator profile (names, game terms). Profanity: keep verbatim by default, optional mask in captions. Captions export as SRT/VTT plus burned-in.

### 3.7 Publishing

State machine per publish job: `draft → queued → uploading → processing → published | failed | needs_user_action`. Each job carries an idempotency key (clip\_version\_id + account\_id + destination); before any retry the worker checks the platform for an existing post id to prevent duplicates. Scheduled posts are executed by a scheduler that enqueues 10 minutes early; Instagram containers created no earlier than 1 hour before publish (24 h expiry). Account shown with avatar + handle in the confirm dialog to prevent wrong-account posts.

### 3.8 Additions adopted from the second draft review

Five ideas from an alternative blueprint are adopted; its platform claims were checked against section 2 and not taken over where they conflict.

| Addition | How it works | Phase | Cost / risk |
| --- | --- | --- | --- |
| **RTMP simulcast ingest** | Streamer adds a second output in OBS (or Restream) to `rtmp://ingest.{domain}/live/{per-user key}`. An ingest node (SRS or nginx-rtmp) segments to 10 s HLS chunks in R2, keeping a rolling 2-hour buffer; the stream becomes a media asset on `stream.offline`. Enables clipping while still live. | 3 (beta) | Doubles streamer upload bandwidth; we pay ingest compute and storage per live hour (≈0.6–3 GB/h at 1.5–6 Mbps). Plan-gated, with max concurrent streams per plan. Our key is ours, never the streamer's Twitch/Kick stream key. |
| **Kick chat sync** | With Kick OAuth, subscribe to chat events during the stream and store messages with wall-clock timestamps. After upload, align by the recording's creation time, refined by matching our RTMP audio or the stream-start event; confirm with a user-adjustable offset. Feeds S\_chat. | 3 | Alignment errors of a few seconds; covered by the 3–8 s chat-lag window. |
| **"Request permission to clip" link** | An editor pasting an unauthorized channel gets a signed invite link (expires in 14 days). The streamer opens it, signs in with Twitch/YouTube/Kick, picks permitted uses, and a `creator_grants` row is created. | MVP | Doubles as low-cost acquisition: every editor invite brings a streamer. |
| **Coarse-to-fine triage** | Stage 1 runs on the whole recording on CPU: loudness, voice activity (Silero VAD), audio events, chat velocity. It keeps the most active \~20–30% of windows. Stage 2 transcribes the full audio (cheap, needed for search) but runs the LLM only on surviving windows. Stage 3 runs face tracking and boundary snapping only on candidates. | MVP | Savings mainly on LLM and vision calls; real percentage to be measured, not assumed. |
| **Stream-friendly metering** | Long VODs are billed at a discounted triage rate (e.g. 0.25 credit per hour for dead-air stretches detected by Stage 1) plus full rate for analyzed windows. Removes "credit burn" on 6-hour streams versus per-source-minute competitors. | 4 | Must be simple to explain; test against flat source-hour pricing in the price test. |

Also adopted: lossless 30-minute segmentation of long recordings (`ffmpeg -f segment -segment_time 1800 -c copy`) so analysis runs in parallel; camera smoothing with a deadband (crop moves only when the face leaves the inner 25% of the frame) plus easing; automatic layout switching when the streamer changes OBS scenes (detected by scene-change + face-box jumps); optimistic locking on clip edits (`409 version_conflict`); TikTok "upload to inbox" as the default when the creator wants to add trending sounds.

Not adopted: asking for Twitch `channel:read:stream_key` (security risk, not needed); Remotion for rendering (paid company license, browser-render variance); music removal (Demucs) on every render, kept as an opt-in GPU feature in phase 5; the unsourced "2-hour stream in 2 minutes" benchmark.

## 4. Architecture, API, database and jobs

Chosen: a **modular monolith** — one FastAPI API process plus specialized worker pools sharing one codebase, Postgres, Redis and S3-compatible storage. Split services only when a module's scaling or deploy cadence demands it.

### 4.1 Options compared

| Option | Pros | Cons | Verdict |
| --- | --- | --- | --- |
| A. Modular monolith: Next.js + FastAPI + Celery/Redis (or Dramatiq) + FFmpeg workers on Fly.io/Render/Hetzner + Cloudflare R2 | Python owns AI/media ecosystem; one repo; cheap; R2 has zero egress fees | Two languages (TS + Python) | **Selected** |
| B. Full TypeScript: Next.js + Node + BullMQ + FFmpeg via child processes | One language | Weaker ML ecosystem; Python still needed for audio models | Viable alternative |
| C. Serverless (Lambda/Cloud Run jobs + Step Functions) | Scales to zero | 15-min/size limits fight 2-hour media; cost opaque | Rejected for v1 |
| D. Microservices on Kubernetes | Independent scaling | Huge ops cost for 1–4 devs | Rejected until > 50k MAU |

### 4.2 Components

| Component | Choice | Why | Failure behaviour | Scales by |
| --- | --- | --- | --- | --- |
| Web app | Next.js (App Router), TypeScript, Tailwind, shadcn/ui; Vercel or same host | Fast UI iteration | Static marketing still served | CDN |
| API | FastAPI + Pydantic v2 + SQLAlchemy 2 | Typed contracts, OpenAPI generation for TS client | 5xx → frontend retries idempotent GETs | Horizontal replicas |
| Queue | Redis 7 + Celery (queues: `ingest`, `stt`, `analyze`, `render`, `publish`, `default`) | Mature retries, priorities | Jobs persist in Postgres `jobs` table; reconciler re-enqueues | More workers per queue |
| DB | Postgres 16 (Neon/Supabase/RDS) + pgvector | Relational + embeddings in one place | Read-only mode banner; workers pause | Vertical, then read replica |
| Object storage | Cloudflare R2 (S3 API) | No egress fees for downloads/previews | Uploads fail fast with resumable retry | Unlimited |
| Media workers | Docker image: FFmpeg 7, PySceneDetect, MediaPipe, YAMNet | Heavy CPU | Visibility timeout → job retried on another worker | Autoscale on queue depth |
| STT | AssemblyAI → Deepgram failover | Cost/quality | Job waits, user notified | Vendor |
| LLM | Small/medium hosted model via one adapter (e.g. Claude Haiku-class, GPT-mini-class) | Hook/context scoring, titles | Falls back to heuristic score | Vendor |
| Realtime progress | Server-sent events from API, fed by Redis pub/sub | Simpler than WebSockets | Client polls every 5 s | — |
| Auth | Own (FastAPI + sessions) or Clerk/Supabase Auth | — | — | — |
| Billing | Stripe Billing + Paystack for NGN cards | Global + Nigeria | Grace period, no data loss | — |
| Observability | Sentry, Grafana Cloud (Prometheus/Loki), Better Stack uptime | — | — | — |

&#91;embedded content: MVP architecture · modular monolith\]

The browser uploads directly to storage with signed URLs; the API only enqueues work, and workers write results to Postgres and storage.

### 4.3 Recording lifecycle

1. **Authorize**: rights attestation or verified Twitch role → `content_rights` row.
2. **Ingest**: resumable upload to `raw/{workspace}/{asset}`; checksum; `ffprobe` validation.
3. **Prepare**: transcode 720p HLS proxy + 16 kHz mono WAV + 2 fps frame proxy (one pass, `ffmpeg` multi-output).
4. **Transcribe**: STT with word timestamps → `transcript_segments`; embeddings (per 30 s chunk) → pgvector.
5. **Analyze**: audio features, events, scene changes, chat → windows; heuristic score; LLM rerank top 40 → `highlight_candidates`.
6. **Edit**: user opens candidate → `clips` + `clip_versions` (render spec).
7. **Render**: worker reads source range with fast seek (`-ss` before `-i`, then accurate trim) → MP4 to `exports/`.
8. **Deliver**: signed download URL (15 min) or publish job.
9. **Measure**: analytics pull jobs at +1 h, +24 h, +7 d, +28 d where APIs allow.
10. **Retain/delete**: raw source deleted after 30 days (Free 7) unless pinned; proxies 90 days; exports until user deletes; hard-delete within 30 days of account closure.

### 4.4 API (v1, user-facing)

All routes `/api/v1`, JSON, cookie session (web) or bearer token (API plan). Errors use RFC 9457 problem+json: `{"type","title","status","detail","code","request_id"}`. Every POST that creates work accepts `Idempotency-Key` (stored 24 h). Authorization: every resource resolves to a `workspace_id`; membership role checked in a single dependency.

| Method | Route | Purpose | Role | Rate limit |
| --- | --- | --- | --- | --- |
| POST | /auth/signup, /auth/login, /auth/logout | Session auth | public | 10/min/IP |
| POST | /auth/verify-email, /auth/password/reset, /auth/2fa/enable | Account security | public/user | 5/min |
| GET/PATCH | /me | Profile, preferences | user | 60/min |
| GET/POST | /workspaces; /workspaces/{id}/members | Workspaces, invites | owner/admin | 30/min |
| GET | /connections/{provider}/authorize | Start OAuth (state + PKCE) | member | 10/min |
| GET | /connections/{provider}/callback | Finish OAuth | — | — |
| DELETE | /connections/{id} | Revoke + delete tokens | admin | — |
| POST | /uploads | Create resumable upload session (returns part URLs) | editor+ | 20/h |
| POST | /uploads/{id}/complete | Finalize, create media asset | editor+ | — |
| POST | /imports | Import from Twitch clip / Drive (`source`, `ref`, `rights`) | editor+ | 20/h |
| GET | /media, /media/{id} | Library, metadata, status | viewer+ | — |
| GET | /media/{id}/transcript | Segments with word timings | viewer+ | — |
| GET | /media/{id}/candidates?sort=score | Highlight candidates | viewer+ | — |
| POST | /media/{id}/search | NL search (phase 5) | viewer+ | 30/min |
| POST | /clips | Create clip from candidate or manual range | editor+ | — |
| GET/PATCH | /clips/{id} | Read/update (PATCH creates a new version) | editor+ | — |
| GET | /clips/{id}/versions | Version history | viewer+ | — |
| POST | /clips/{id}/renders | Queue render (preset) — idempotent | editor+ | per plan concurrency |
| GET | /renders/{id} | Status, progress, download URL | viewer+ | — |
| GET | /jobs/{id}/events | SSE progress stream | viewer+ | — |
| DELETE | /jobs/{id} | Cancel | editor+ | — |
| POST | /publications | Publish/schedule (`render_id`, `connection_id`, `caption`, `privacy`, `scheduled_at`) — idempotent | publisher+ | — |
| GET/DELETE | /publications/{id} | Status / cancel scheduled | publisher+ | — |
| GET | /analytics/clips?from=&to= | Performance snapshots | viewer+ | — |
| GET | /usage | Quota consumption | member | — |
| POST | /billing/checkout, /billing/portal | Stripe/Paystack sessions | owner | — |
| POST | /webhooks/stripe, /webhooks/paystack, /webhooks/twitch | Signed webhooks | signature | — |
| POST | /me/export; DELETE /me | GDPR/NDPA export and deletion | user | 1/day |
| GET/POST | /admin/\* | Users, abuse reports, takedowns, refunds | staff (separate SSO) | — |

Example:

```json
POST /api/v1/clips/cl_8f2/renders
Idempotency-Key: 3b1c…
{"version_id":"cv_14","preset":"vertical_1080p"}

202 Accepted
{"render_id":"rd_77","status":"queued","credits_reserved":1,"events_url":"/api/v1/jobs/jb_91/events"}
```

Errors: `402 quota_exceeded`, `409 render_in_progress`, `422 invalid_range` (out outside media duration, length outside plan limits), `403 rights_missing`.

Internal interfaces are Python protocols, not HTTP: `SourceProvider`, `TranscriptionProvider`, `LLMProvider`, `Publisher`, `Storage`, each with a fake for tests.

### 4.5 Database schema

Core tables (all with `id uuid pk`, `created_at`, `updated_at`; tenant tables carry `workspace_id` and Postgres row-level security keyed on `current_setting('app.workspace_id')`):

| Table | Key fields | Notes |
| --- | --- | --- |
| users | email (citext unique), password\_hash, email\_verified\_at, totp\_secret\_enc, deleted\_at |  |
| workspaces / memberships | plan\_id; role enum(owner, admin, editor, publisher, viewer, client\_reviewer) | unique(workspace\_id,user\_id) |
| connections | provider, external\_account\_id, scopes\[\], access\_token\_enc, refresh\_token\_enc, expires\_at, status | AES-GCM envelope encryption (KMS key) |
| content\_rights | media\_asset\_id, grantor\_type(owner/creator\_grant/license/twitch\_role), grantor\_user\_id, permitted\_uses\[\] (edit, download, publish, commercial, white\_label, monetize), expires\_at, revoked\_at, evidence\_ref | Checked on render/publish |
| creator\_grants | creator\_user\_id, grantee\_workspace\_id, uses\[\], channels\[\], expires\_at | One-click editor authorization |
| media\_assets | source\_type, source\_ref, sha256, duration\_s, width, height, fps, codecs, storage\_keys jsonb, status, retain\_until | index(workspace\_id, created\_at desc); unique(workspace\_id, sha256) partial where not deleted |
| transcripts / transcript\_segments | provider, language; segments: start\_ms, end\_ms, speaker, text, words jsonb, embedding vector(1024) | ivfflat/hnsw index on embedding |
| signals | media\_asset\_id, kind, t\_ms, value | Bulk-insert via COPY; partition by asset if large |
| highlight\_candidates | start\_ms, end\_ms, score, components jsonb, title, reason, status | index(media\_asset\_id, score desc) |
| clips / clip\_versions | clip: candidate\_id, title; version: spec jsonb, number, created\_by | Immutable versions |
| render\_jobs / exports | clip\_version\_id, preset, status, progress, error\_code, storage\_key, bytes | unique(clip\_version\_id, preset) where status != failed |
| publications | export\_id, connection\_id, destination, idempotency\_key unique, status, scheduled\_at, external\_post\_id, url, error |  |
| analytics\_snapshots | publication\_id, captured\_at, views, likes, comments, shares, avg\_watch\_s, raw jsonb |  |
| plans / subscriptions / usage\_records / payments / refunds | provider ids, period, credits\_used, meter | usage\_records append-only |
| webhook\_events | provider, event\_id unique, payload, processed\_at | Dedup |
| jobs | type, status, attempts, run\_after, lease\_until, payload, idempotency\_key unique | Source of truth for queue |
| audit\_logs | actor\_id, action, target, ip, metadata | Append-only, 1 year |
| abuse\_reports / takedowns | reporter, target, reason, status, resolution |  |

Representative migration:

```sql
CREATE TABLE content_rights (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  media_asset_id uuid NOT NULL REFERENCES media_assets(id) ON DELETE CASCADE,
  grantor_type text NOT NULL CHECK (grantor_type IN ('owner','creator_grant','license','twitch_role')),
  grantor_user_id uuid REFERENCES users(id),
  permitted_uses text[] NOT NULL,
  attestation_text_version text NOT NULL,
  attested_ip inet,
  expires_at timestamptz,
  revoked_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON content_rights (media_asset_id) WHERE revoked_at IS NULL;
ALTER TABLE content_rights ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant ON content_rights USING (workspace_id = current_setting('app.workspace_id')::uuid);
```

Account closure: users anonymized (email hashed), tokens deleted and revoked at provider, media and exports hard-deleted, payments/invoices retained 7 years (tax), audit logs retained 1 year with actor pseudonymized.

### 4.6 Background jobs

States: `queued → running → succeeded | failed | cancelled`, with `running → retrying → running` and `failed → dead` after max attempts. Rules:

- Retries: exponential backoff with jitter (30 s, 2 m, 8 m, 30 m); max 4; non-retryable codes (corrupt file, rights revoked) fail immediately.
- Leases: worker heartbeats every 30 s; reconciler re-queues jobs whose lease expired (crash recovery). Every step writes outputs to deterministic keys so reruns overwrite, not duplicate.
- Priorities: paid queue weight 3, free weight 1; per-workspace concurrency (Free 1, Creator 2, Pro 4, Agency 10) enforced with Redis semaphores.
- Timeouts: STT 60 min, render 15 min per clip, ingest 2 h. Temp files in per-job dir, deleted in `finally`; nightly sweeper.
- Dead-letter: `dead` jobs alert Slack and appear in admin console with one-click retry.

**Worked example: 2-hour VOD → 10 candidates** (assumptions: 1080p60 H.264, 6 GB, 8-vCPU worker):

| Step | Wall time | Resource |
| --- | --- | --- |
| Upload (user, 50 Mbps) | ≈16 min | user bandwidth |
| Proxy + audio extract | 6–10 min | 8 vCPU |
| STT (batch API, parallel chunks) | 3–8 min | vendor; ≈$0.30–$0.52 |
| Audio/visual signals | 4–6 min | 4 vCPU |
| LLM rerank of 40 windows | 1–2 min | ≈$0.02–$0.10 |
| **Candidates ready after upload** | **≈12–20 min** |  |
| Render 10 × 45 s vertical clips | ≈1–2 min each, 4 in parallel → 4–5 min |  |

Targets to validate in the week-2 spike; these are estimates.

## 5. External services and credentials

The MVP needs about 15 secrets; social publishing adds credentials that only become useful after each platform's review. Nothing below grants access by itself — every provider requires an account, app registration and, for publishing, approval.

### 5.1 Service inventory

| Service | Purpose | Auth | Approval needed | Free / price (verify) | Failure impact → fallback |
| --- | --- | --- | --- | --- | --- |
| [Twitch Helix](https://dev.twitch.tv/docs/api/) | OAuth login, VOD metadata, Create Clip/From VOD, clip download, EventSub chat | OAuth2 (client id/secret), app + user tokens | None for basic; Clip-from-VOD is open beta | Free; per-token rate-limit bucket (Ratelimit-\* headers) | Twitch import disabled → upload |
| Kick public API | Login, channel metadata, chat events | OAuth 2.1 + PKCE | Developer app | Free | Metadata only |
| [YouTube Data API v3](https://developers.google.com/youtube/v3) | Channel verify, metadata, Shorts upload | OAuth (`youtube.upload`, `youtube.readonly`) + API key for public reads | Google OAuth verification + YouTube API compliance audit for public uploads | 10,000 units/day default | Publish → download fallback |
| [TikTok Content Posting API](https://developers.tiktok.com/doc/content-sharing-guidelines) | Direct post / inbox upload | OAuth (`user.info.basic`, `video.publish`, `video.upload`) | App review + content audit for public posts; domain verification for pull\_from\_url | Free | Private-only until audited |
| [Instagram Graph API](https://developers.facebook.com/docs/instagram-platform/content-publishing) | Reels publish, insights | Instagram Login (`instagram_business_content_publish`) or Facebook Login (`instagram_content_publish`) | Meta App Review + Business Verification | Free | Phase 4 |
| X API v2 | Post + media | OAuth 2.0 PKCE (user) | Developer account, credits | ≈$0.015/post | Phase 4, pass cost through |
| AssemblyAI / Deepgram | STT | API key | No | ≈$0.15–$0.46/h | Failover to the other |
| LLM provider | Hook/context scoring, titles, captions | API key | No | Per token | Heuristic-only scoring |
| Embeddings | Search, dedup | API key or self-hosted (bge-m3) | No | Small | Text-only dedup |
| Cloudflare R2 | Media storage | Access key + secret | No | $0.015/GB-month, zero egress (verify) | Uploads blocked |
| Postgres (Neon/Supabase) | DB | Connection string | No | Free tier → ≈$19–$69/mo | Read-only mode |
| Redis (Upstash/managed) | Queue, locks | URL | No | ≈$10–$30/mo | Jobs held in Postgres |
| Stripe Billing | Global subscriptions | Secret + webhook secret | Account activation | 2.9% + 30¢ US cards (+intl fees) | Grace period |
| Paystack | NGN cards, bank transfer | Secret key | Business verification | Local % fee (verify) | Stripe |
| Resend / Postmark | Email | API key | Domain DNS | Free tier | Queue and retry |
| Sentry, Grafana Cloud, Better Stack, PostHog | Errors, metrics/logs, uptime, product analytics | DSN / keys | No | Free tiers | Degraded visibility |
| GitHub Actions | CI/CD | OIDC to host | No | Free minutes | Manual deploy |

### 5.2 .env.example

```bash
# --- MVP required (private, server-only) ---
DATABASE_URL=postgresql://user:pass@host:5432/clipforge
REDIS_URL=rediss://default:pass@host:6379
SESSION_SECRET=                 # 64 random bytes, base64
TOKEN_ENCRYPTION_KEY_ID=        # KMS key reference for envelope encryption
R2_ACCOUNT_ID=
R2_ACCESS_KEY_ID=
R2_SECRET_ACCESS_KEY=
R2_BUCKET_MEDIA=clipforge-media
ASSEMBLYAI_API_KEY=
LLM_API_KEY=
STRIPE_SECRET_KEY=
STRIPE_WEBHOOK_SECRET=
RESEND_API_KEY=
SENTRY_DSN=

# --- MVP integrations ---
TWITCH_CLIENT_ID=               # public identifier
TWITCH_CLIENT_SECRET=
TWITCH_EVENTSUB_SECRET=         # HMAC secret for webhook verification
GOOGLE_CLIENT_ID=               # YouTube OAuth (public identifier)
GOOGLE_CLIENT_SECRET=
TIKTOK_CLIENT_KEY=              # public identifier
TIKTOK_CLIENT_SECRET=

# --- Optional / failover ---
DEEPGRAM_API_KEY=
PAYSTACK_SECRET_KEY=
POSTHOG_PROJECT_KEY=            # may be exposed to browser

# --- Only after platform approval (phase 4) ---
META_APP_ID=
META_APP_SECRET=
X_CLIENT_ID=
X_CLIENT_SECRET=
KICK_CLIENT_ID=
KICK_CLIENT_SECRET=

# --- Not needed if self-hosting Whisper / embeddings ---
# WHISPER_ENDPOINT=http://stt-gpu:8000

# --- Browser-safe (NEXT_PUBLIC_ prefix only) ---
NEXT_PUBLIC_API_URL=https://api.example.com
NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY=
```

### 5.3 Secret handling

- Store in the host's secret manager (Fly secrets / Doppler / AWS Secrets Manager); never in the repo. CI uses OIDC, not long-lived keys.
- OAuth redirect URIs registered per environment: `https://app.{domain}/api/v1/connections/{provider}/callback`, plus `http://localhost:3000/...` in a separate dev app.
- User tokens encrypted with a per-row data key wrapped by a KMS master key; rotation = rewrap job. Refresh tokens rotated on every refresh where the provider supports it.
- Rotation: provider secrets every 90 days or on staff departure; dual-key acceptance window for webhook secrets.
- Revocation: disconnect calls the provider revoke endpoint, then deletes ciphertext.

## 6. Compliance, security and failure handling

Rights are enforced in code: no render, download or publish happens without an unrevoked `content_rights` record covering that use.

### 6.1 Content rights model

| Use level | Who can grant | Default for owner upload | Default for editor via creator grant |
| --- | --- | --- | --- |
| Personal edit / internal review | Owner, creator grant | Yes | Yes |
| Download | Owner, creator grant | Yes | Per grant |
| Social publishing (own accounts) | Owner | Yes | Only to creator's connected accounts unless grant says otherwise |
| Commercial redistribution / monetized | Owner, written license | Attest separately | Per grant |
| White-label client work | License | No | Per grant |

Revocation or expiry triggers: block new renders/publishes, cancel scheduled posts, notify workspace, keep existing exports downloadable only by the owner for 7 days, then delete. Published posts on third-party platforms cannot be recalled by us; the UI lists them so the user can remove them.

Legal position (requires counsel review before launch, especially for US, EU/UK and Nigeria):

- Public availability is not permission. Fair use is not assumed.
- Register a DMCA agent (US Copyright Office) and publish a takedown/counter-notice process; repeat-infringer policy (3 strikes → termination).
- Music: stream VODs often contain copyrighted music. Warn when audio-fingerprint or music-detection confidence is high; offer "mute music" (source separation via Demucs, phase 5). We do not clear music rights.
- Privacy: GDPR/UK GDPR, Nigeria Data Protection Act 2023, CCPA. Voice and face data processed only for the user's own editing; no biometric identification, no cross-customer training without opt-in. DPA with every subprocessor.
- Terms: platform developer agreements (Twitch, Google API Services, TikTok, Meta) require displaying their branding/permissions accurately and honoring user deletion requests.

### 6.2 Security controls

- **Tenant isolation:** workspace\_id on every row + Postgres RLS + API dependency check; object keys prefixed by workspace and only reachable via short-lived signed URLs (15 min download, 1 h upload part). Automated test tries cross-tenant access on every endpoint.
- **OAuth:** state + PKCE, exact redirect matching, tokens encrypted, refresh-token rotation, least scopes.
- **Web:** SameSite=Lax HttpOnly session cookies + CSRF token on mutations; strict CSP; React escaping; caption text sanitized before ASS generation (escape `{}` override tags).
- **Injection:** SQLAlchemy parameterized queries only; FFmpeg invoked with argv arrays, never shell strings.
- **SSRF:** server-side fetches limited to allowlisted provider hosts; block private IP ranges; no arbitrary URL fetch.
- **Uploads:** ffprobe validation in a sandboxed container (no network, seccomp, CPU/mem/time limits); reject > plan size; cap resolution at 4K and duration at plan max; ClamAV scan for non-video types.
- **Abuse:** rate limits per IP and account, Turnstile on signup, email verification before processing, disposable-email blocklist, free-tier abuse heuristics (same card/device across accounts).
- **Billing:** entitlements derived only from verified webhooks; webhook signature check + event-id dedup; usage reserved before a job and settled after.
- **Audit log:** logins, connection changes, rights grants, publishes, deletions, admin actions.
- **Incident response:** severity levels, on-call rota, 72-hour regulator notification path, token mass-revocation runbook.

### 6.3 Edge-case and failure matrix

| Case | Detection | User sees | Backend action | Billing impact |
| --- | --- | --- | --- | --- |
| Invalid / unsupported URL | Regex + provider lookup | "We can't import from this link. Upload the file instead." | No job | None |
| Private, deleted or region-locked source | Provider 403/404 | "This video isn't available to your account." | Mark failed, non-retryable | None |
| Stream still live / VOD not ready | Twitch stream status | "We'll import when the VOD is ready." | Poll every 10 min for 6 h | None |
| Interrupted / expired upload | Missing parts / session > 24 h | Resume button | Keep parts 24 h, then abort multipart | None |
| Corrupt, zero-duration, no audio/video | ffprobe | Specific message (e.g. "No audio track — captions unavailable") | Fail or continue in video-only mode | Refund reserve |
| VFR, odd codec (HEVC 10-bit, AV1) | ffprobe | Nothing | Normalize in proxy pass | — |
| Duplicate upload | sha256 | "Already in library" with link | No new processing | None |
| Transcription fails / unsupported language | Vendor error / low confidence | "Captions unavailable for this language" | Failover vendor; continue with audio/visual signals | Partial |
| No good highlights | Max score < threshold | "No strong moments found — try search or manual clip" | Show top 5 anyway, flagged low | Charged (processing happened) — consider half credit |
| LLM outage / cost spike | Error rate, $/hour alert | Slightly slower results | Heuristic scoring; daily spend cap per workspace and global | — |
| Hallucinated titles | LLM output must cite transcript span | Editable suggestion | Reject outputs not grounded in span | — |
| Worker crash / OOM / disk full | Lease expiry, exit code | Progress continues after retry | Retry on larger instance class; sweeper frees disk | Reserve held |
| Missing font, broken subtitles | Render validation (frame sample + ASS parse) | "Render failed, retrying" | Fallback font | Refund on final fail |
| A/V desync | Compare stream durations > 100 ms | — | Re-render with `aresample=async=1` | — |
| User cancels render | Cancel flag checked per segment | Cancelled | Kill ffmpeg, delete temp | Refund |
| Token expired / revoked | 401 from provider | "Reconnect TikTok to publish" (email + in-app) | Pause job `needs_user_action` | — |
| Platform rate limit | 429 / quota error | "Scheduled for HH:MM" | Reschedule after reset | — |
| Duplicate publish risk | Idempotency key; pre-retry status check | — | Never retry a non-idempotent upload blindly | — |
| Scheduled post misses window | Scheduler lag > 5 min | "Posted 12 min late" or "Failed — post now?" | Alert ops | — |
| Post removed by platform | Analytics fetch 404 | Badge "Removed by platform" | Stop polling | — |
| App audit revoked | Provider error codes | Publishing to X paused banner | Feature-flag destination off | — |
| Payment failure | Stripe invoice.payment\_failed | Banner, 7-day grace | Dunning emails; then downgrade to Free, keep data 30 days | — |
| Duplicate webhook | event\_id unique | — | Ignore | — |
| Chargeback | dispute.created | Account flagged | Freeze processing, evidence pack | Fee absorbed |
| Downgrade over limits | Plan change | "3 of 5 seats active — choose which remain" | Read-only for excess | Prorated |
| Owner leaves workspace | Membership delete | Must transfer ownership first | Block | — |
| Account deletion / export | User request | Confirmation + 30-day window | Export zip within 72 h; hard delete pipeline | Cancel subscription |

Severity: S1 (data leak, mass publishing failure, billing errors) pages on-call immediately; S2 (one integration down) within 1 h; S3 next business day.

## 7. UX, differentiating features, testing and operations

The UX target: a first-time streamer exports a usable vertical clip within 20 minutes of uploading, with no more than 6 clicks after candidates appear.

### 7.1 Navigation and screens

Left rail (desktop) / bottom tabs (mobile): **Home · Library · Clips · Publish · Analytics · Team · Settings**. Workspace switcher at top.

| Screen | Key components | Empty / loading / error | Acceptance criteria |
| --- | --- | --- | --- |
| Home | Recent VODs with status, "Import" CTA, usage meter | Empty: upload dropzone + Twitch connect | Upload starts in ≤ 2 clicks |
| Import | Dropzone, URL field with source detection, rights checkbox | Per-file progress with resume | Rights attestation required before Start |
| Processing | Step list (upload, prepare, transcribe, analyze) with ETA via SSE | Failure shows reason + action | Updates within 2 s of server event |
| Highlights | Candidate cards ranked: thumbnail, score bar with reason ("crowd-laugh + chat spike"), transcript snippet, length; keyboard J/K navigation, A=accept, X=reject | Low-confidence badge | Preview starts < 1.5 s on broadband |
| Editor | Player (left), transcript-as-timeline (click word to trim), layout picker, caption style panel, platform safe-zone toggle, undo/redo, version menu | Autosave indicator | Trim precision 1 frame; undo 50 steps |
| Export / Publish | Presets, destination accounts with avatars, caption + hashtag fields per platform, schedule picker, private/public | Platform limitation notes inline ("TikTok: private until our app is audited") | Confirm dialog names account |
| Calendar | Week/month view, drag to reschedule | — | Shows failures in red with retry |
| Analytics | Per-clip metrics, cohort by hook/length/layout | "Connect an account to see stats" | Labels correlations, not causes |
| Team | Members, roles, creator grants, approval queue | — | Role changes audited |
| Billing | Plan, usage, invoices, currency (USD/NGN) | — | Downgrade preview |
| Admin | User search, jobs/DLQ, takedowns, refunds, feature flags | — | Staff SSO + 2FA only |

Visual direction: dark-first neutral UI (editors work at night next to OBS), one accent colour, Inter/Geist type, dense lists, no decorative gradients. WCAG 2.2 AA: captions editor fully keyboard-operable, focus rings, 4.5:1 contrast, reduced-motion respected. Mobile: review candidates, approve, schedule, download — no timeline editing in v1.

### 7.2 Differentiating features (ranked)

| Rank | Feature | Value | Effort | Cost | Phase |
| --- | --- | --- | --- | --- | --- |
| 1 | Chat-aware highlight detection (Twitch bot records chat with consent) | High, unique vs podcast tools | M | Low | MVP |
| 2 | Creator → editor authorization (one-click grant, scoped uses) | High for editors, trust | M | Low | MVP |
| 3 | Transcript-as-timeline editing | Fast trimming | M | Low | MVP |
| 4 | Stream layout presets (facecam + gameplay split auto-detected) | High for gaming | M | Low | MVP |
| 5 | "Why this clip" explanations on every candidate | Trust, faster triage | S | Low | MVP |
| 6 | Natural-language search across VODs ("every Arsenal mention") | High | M | Embeddings | 5 |
| 7 | Per-creator ranking from performance feedback | Retention, moat | L | Low | 5 |
| 8 | Multi-clip campaign planner (10 clips → spaced calendar, variety rules) | Saves planning time | M | Low | 5 |
| 9 | Approval workflow + client reviewer role | Agencies pay | M | Low | 6 |
| 10 | Auto clip from current stream via Twitch "clip earlier in stream" on chat spikes | Wow factor | M | Low | 5 |
| 11 | Hook rewriter (first 2 s text overlay suggestions) | Quality | S | LLM | 5 |
| 12 | Repost recycler: resurface past top clips for other platforms | Content volume | S | Low | 5 |
| 13 | Brand kits per creator (fonts, colours, logos) | Agencies | S | Low | 4 |
| 14 | Sponsor-segment finder ("find all sponsor reads") for sponsor reports | Helps creators earn | S | Low | 5 |
| 15 | Clip bounty / revenue-share ledger for creator-run clipping programs | Monetization, community | L | Low | 6 |
| 16 | Music detector + mute-music render | Avoids strikes | M | GPU | 5 |
| 17 | Multi-language caption translation | Reach | S | LLM | 4 |
| 18 | Weekly "best of stream" compilation auto-builder | YouTube long-form | M | Render | 5 |
| 19 | Caption template marketplace | Revenue | M | Low | 7 |
| 20 | Public API for agencies | Enterprise | M | Low | 7 |

Feedback loop rule: show "clips under 30 s with a question hook got 1.8× median views for you (n=24)" with sample size and confidence; never claim causation. Personal weights update only after ≥ 20 published clips.

### 7.3 Testing

| Layer | Tooling | Must cover |
| --- | --- | --- |
| Unit | pytest, Vitest | Scoring, boundary snapping, dedup, render-spec → FFmpeg args, entitlements |
| Integration | pytest + Testcontainers (Postgres, Redis, MinIO) | Job state machine, retries, RLS isolation |
| Contract | OpenAPI schema diff in CI; generated TS client compiles | No breaking API changes |
| Media golden tests | 20-file corpus (VFR, HEVC, mono, no audio, 4K, 6 h, corrupt) | Output duration ± 1 frame, A/V drift < 40 ms, loudness −14 ± 1 LUFS |
| Highlight quality | 30 hand-labeled VOD hours | Precision@10 ≥ 0.6 before beta; tracked per release |
| Provider fakes + sandbox | Recorded fixtures; Stripe test mode; TikTok/YouTube sandbox accounts | OAuth expiry, 429, revoked scopes |
| E2E | Playwright | Signup → upload → candidate → edit → render → download → publish (fake) → billing usage recorded |
| Security | ZAP baseline, Semgrep, dependency audit, cross-tenant test suite, pentest before public launch |  |
| Load | k6 for API; synthetic queue flood (500 VOD-hours) | p95 API < 300 ms; no starvation of paid queue |
| Accessibility | axe-core in Playwright | Zero critical violations |
| DR | Quarterly restore from backup to staging | RPO ≤ 15 min, RTO ≤ 4 h |

MVP launch gate: all E2E happy paths green, golden media tests green, cross-tenant suite green, Precision@10 ≥ 0.6, pentest criticals fixed, billing reconciliation matches Stripe for test month.

### 7.4 Deployment and operations

- **Environments:** local (Docker Compose: postgres, redis, minio, api, worker, web), staging (production clone with test keys), production.
- **MVP deploy:** web on Vercel; API + workers on Fly.io or Hetzner Cloud (CPU workers, autoscaled by queue depth via a small controller); Neon Postgres with PITR; R2; Upstash Redis. Move to Kubernetes only when > \~30 worker nodes or multi-region is needed.
- **CI/CD:** GitHub Actions — lint, typecheck, tests, build images, Alembic migrations (expand/contract only), deploy staging on main, manual promote to prod; instant rollback to previous image.
- **Dashboards & alerts:** queue depth and age per queue (alert if oldest paid job > 10 min); job failure rate > 5%/15 min; publish failure rate per destination; STT/LLM spend per hour vs budget (alert at 150% of 7-day average); storage growth per day; API 5xx > 1%; p95 candidates-ready time.
- **Backups:** Postgres PITR 7 days + nightly logical dump to separate account; R2 lifecycle rules; raw media not backed up (user can re-upload) — stated in terms.
- **Platform API changes:** subscribe to Twitch, Google, TikTok, Meta, X developer changelogs; contract tests against live sandboxes nightly.

## 8. Pricing, unit economics, financials and go-to-market

Meter on **source hours processed** (the true cost driver), sell on outcomes, and keep gross margin above 65% at typical usage. All prices are provisional until the validation price test.

### 8.1 Unit cost per source hour (estimate)

| Item | Assumption | Cost |
| --- | --- | --- |
| STT | Batch API, $0.15–$0.26/h | $0.15–$0.26 |
| Analysis + proxy compute | ≈2 vCPU-hours at $0.03–$0.05 | $0.06–$0.10 |
| LLM rerank + titles | ≈40 windows, small model | $0.02–$0.10 |
| Embeddings | 120 chunks | < $0.01 |
| Storage | 3 GB raw × 30 days + 0.8 GB proxy × 90 days on R2 | ≈$0.08 |
| **Total per source hour** |  | **≈$0.32–$0.55** |
| Render per 45 s clip (1080p, CPU) | ≈0.2 vCPU-h | ≈$0.01 |
| Downloads / previews | R2 zero egress (verify plan terms) | ≈$0 |
| Publishing | Free except X ≈$0.015–$0.20/post | pass-through |

Reuse: one transcript, proxy and embedding set serve all candidates, re-renders and searches; re-renders never re-transcribe. So 10 clips from 1 hour ≈ $0.45–$0.65; 100 clips/month (\~10 h) ≈ $4.5–$6.5; 1,000 clips/month (\~100 h) ≈ $45–$65; heavy agency (300 h, 3,000 clips) ≈ $130–$200.

Largest cost drivers: STT, free-tier usage, raw-file retention, and any GPU feature (music separation, self-hosted vision). Self-host Whisper only above ≈ 3,000 source hours/month, when a dedicated GPU beats API pricing.

### 8.2 Tiers

|  | Free | Creator | **Pro** | Agency | Enterprise |
| --- | --- | --- | --- | --- | --- |
| Monthly | $0 | $15 | **$29** | $149 | Custom (from $600) |
| Annual (per month) | — | $12 | $24 | $124 | Contract |
| Source hours / month | 0.5 | 10 | 30 | 100 | Committed |
| Max recording length | 1 h | 4 h | 8 h | 12 h | 12 h+ |
| Seats / creator workspaces | 1 / 1 | 1 / 1 | 3 / 3 | 10 / 15 | Custom |
| Concurrent jobs | 1 | 2 | 4 | 10 | Dedicated |
| Export | 720p, watermark | 1080p | 1080p, 60 fps | 4K | 4K |
| Highlight AI | Basic | Full | Full + chat-aware | Full + chat-aware | + custom models |
| Publishing / scheduling | Download only | 3 accounts, publish | 10 accounts, schedule | 50 accounts, calendar | Unlimited |
| Analytics, brand kit | — | — | Yes | Yes + client reports | Yes |
| Approvals, white-label | — | — | — | Yes | Yes + SSO |
| Priority / support | Community | Email 48 h | Email 24 h, priority queue | Priority + chat | SLA, CSM |
| Overage per source hour | — | $1.50 | $1.25 | $1.00 | Contract |

Fair use: no automated bulk ingestion of third-party channels; publishing caps follow each platform's limits.

Nigeria and similar markets: offer local-currency pricing through Paystack at roughly 40–50% of USD list (purchasing-power adjusted), card and bank transfer, set after checking the exchange rate at launch. Restrict PPP pricing to local payment methods to limit arbitrage.

### 8.3 Margin by tier (estimate)

| Tier | Typical use (40% of allowance) | Variable cost incl. payment fees | Gross margin | Heavy use (100%) margin |
| --- | --- | --- | --- | --- |
| Creator $15 | 4 h, 40 clips | ≈$3.0 | ≈80% | ≈55% |
| Pro $29 | 12 h, 120 clips | ≈$8.0 | ≈72% | ≈35% |
| Agency $149 | 40 h, 400 clips | ≈$29 | ≈80% | ≈57% |
| Free | 0.5 h | ≈$0.25 | — | — |

Free-tier burden: at 5% conversion, each paying user carries \~19 free users ≈ $4.75/month. Keep Free at 30 minutes, require email verification, expire unused raw files after 7 days.

### 8.4 12-month projection (estimates, not verified data)

Assumptions — base: 400 signups in month 1 growing 20%/month, 5% free→paid within 60 days, 6% monthly paid churn, blended ARPU $27, variable cost 25% of revenue, fixed tooling/infra $800/month rising to $2,500, marketing $1,000→$4,000/month, founders unpaid. Conservative: 10% growth, 3% conversion, 9% churn, ARPU $22. Optimistic: 30% growth, 7% conversion, 4% churn, ARPU $32.

| Scenario | Paying users M6 | Paying users M12 | MRR M12 | ARR run-rate M12 | Month cash-flow positive (excl. salaries) |
| --- | --- | --- | --- | --- | --- |
| Conservative | ≈45 | ≈120 | ≈$2.6k | ≈$32k | Not within 12 months |
| Base | ≈110 | ≈400 | ≈$10.8k | ≈$130k | ≈Month 8 |
| Optimistic | ≈260 | ≈1,200 | ≈$38k | ≈$460k | ≈Month 5 |

CAC target ≤ $60 blended (creator-led and content marketing); LTV at $27 ARPU, 72% margin, 6% churn ≈ $325 → LTV:CAC ≈ 5. Sensitivity: if users consume 100% of allowance and STT doubles in price, base gross margin falls from \~72% to \~45%; mitigations are lower included hours on Pro, overage billing, and moving STT in-house.

### 8.5 Go-to-market

1. **Validation:** 20 interviews (streamers 1k–50k followers, freelance clip editors), concierge pilot, landing page with $19/$29 price test.
2. **Private beta (50 creators):** free Pro in exchange for weekly feedback and usage data.
3. **Public launch:** Product Hunt, Twitch/YouTube creator communities, TikTok showing before/after clips.
4. **First 100 paying:** affiliate program (30% recurring for 12 months) for clip editors who bring their streamers; creator partnerships with mid-size streamers.
5. **First 1,000:** SEO on "Twitch VOD to TikTok", templates gallery, referral credits (+2 source hours each side).
6. **Teams/agencies:** outbound to clipping agencies; white-label and client billing.
7. **Enterprise:** esports orgs, MCNs, media companies with owned archives.

We do not sell user data or run ads in the product.

## 9. Roadmap, handoff and launch

Build the riskiest pieces first: highlight quality and platform audits. The UI is the cheapest part to change.

### 9.1 Phases

| Phase | Duration | Features | Approvals | Gate to exit | Run cost/month |
| --- | --- | --- | --- | --- | --- |
| 1 Validation | 2–3 weeks | Interviews, concierge clipping with scripts, price page | Submit TikTok + YouTube audits, Twitch app | ≥ 10 users say they'd pay ≥ $19; Precision@10 ≥ 0.5 on labeled set | < $100 |
| 2 MVP | 6–8 weeks | Upload, transcript, candidates, editor, render, download, Stripe, Twitch OAuth | Audits in progress | E2E green; 2-h VOD → candidates < 20 min | $200–$400 |
| 3 Private beta | 4–6 weeks | Twitch clip import, YouTube/TikTok publish (private until audit), chat bot | Audits granted | 50 creators, 40% week-4 retention, cost/hour within estimate | $400–$800 |
| 4 Public launch | 4 weeks | Plans, Paystack, onboarding, support desk, Instagram (if approved), translation | Meta review | Pentest clean; first 50 paying | $600–$1,200 |
| 5 Advanced AI | 8 weeks | NL search, personalization, campaigns, live chat-spike clips, music detection | — | Precision@10 ≥ 0.7; publish rate per candidate up 20% | $1–3k |
| 6 Teams/agencies | 6 weeks | Approvals, client reviewer, white-label, client billing, revenue-share ledger | — | 10 agencies paying | $2–5k |
| 7 Scale | Ongoing | Self-hosted STT, GPU render pool, SSO, public API, multi-region | — | Gross margin ≥ 75% | Scales with revenue |

### 9.2 First 30 days

- [ ] Day 1–3: register Twitch, Google Cloud, TikTok developer apps; draft privacy policy and terms; submit TikTok and YouTube audits as early as their forms allow.
- [ ] Day 1–7: repo scaffold, Docker Compose, CI, Postgres schema v1, upload flow to R2.
- [ ] Day 5–12: STT adapter, signal extraction, heuristic scorer, LLM rerank; label 30 VOD hours (10 creators × 3 h).
- [ ] Day 12–14: measure Precision@10; tune weights; decide go/no-go on gameplay-heavy content.
- [ ] Day 14–21: candidate review UI, editor with render spec, FFmpeg renderer, caption burn-in, download.
- [ ] Day 21–26: auth hardening, Stripe plans + usage metering, Twitch OAuth + clip import behind flag.
- [ ] Day 26–30: staging soak test, 10 beta creators onboarded, cost dashboard live.

### 9.3 Repository layout

```text
clipforge/
  apps/web/            # Next.js app (TS, Tailwind)
  apps/api/            # FastAPI: routers/, deps/, schemas/
  core/                # domain modules (shared by api + workers)
    identity/ workspaces/ rights/ media/ transcripts/
    highlights/ clips/ render/ publishing/ analytics/ billing/
  workers/             # Celery tasks per queue, ffmpeg/ helpers
  providers/           # twitch/ youtube/ tiktok/ meta/ x/ stt/ llm/ storage/
  migrations/          # Alembic
  packages/api-client/ # generated TS client from OpenAPI
  infra/               # docker-compose.yml, fly.toml, terraform/
  tests/               # unit/ integration/ media_golden/ e2e/
```

Core provider interface (Python):

```python
class TranscriptionProvider(Protocol):
    name: str
    async def transcribe(self, audio_url: str, *, language: str | None,
                         vocabulary: list[str]) -> Transcript: ...

class Publisher(Protocol):
    destination: Destination
    async def preflight(self, conn: Connection, export: Export) -> PreflightResult: ...  # limits, creator_info, account type
    async def publish(self, conn: Connection, export: Export, meta: PostMeta,
                      idempotency_key: str) -> PublishResult: ...
    async def status(self, conn: Connection, external_id: str) -> PublishStatus: ...
```

Compose (local):

```yaml
services:
  postgres: { image: pgvector/pgvector:pg16, environment: { POSTGRES_PASSWORD: dev }, ports: ["5432:5432"] }
  redis:    { image: redis:7, ports: ["6379:6379"] }
  minio:    { image: minio/minio, command: server /data --console-address :9001, ports: ["9000:9000","9001:9001"] }
  api:      { build: ., command: uvicorn apps.api.main:app --reload --host 0.0.0.0, env_file: .env, depends_on: [postgres, redis, minio], ports: ["8000:8000"] }
  worker:   { build: ., command: celery -A workers.app worker -Q ingest,stt,analyze,render,publish -c 2, env_file: .env, depends_on: [api] }
  web:      { build: apps/web, command: npm run dev, ports: ["3000:3000"] }
```

Conventions: errors as problem+json with stable `code`; every domain error maps to one user message; tests named `test_<unit>_<behaviour>`; no PR merges without passing CI and one review. Placeholders: provider credentials, legal text, pricing values, scoring weights. Production-ready after configuration: schema, job framework, render pipeline, auth, billing webhooks — once the test gates above pass.

### 9.4 AI coding-agent work packages

Agree these contracts before parallel work: OpenAPI spec v1, database schema v1, render-spec JSON schema, job payload schemas, provider protocols, error-code list.

| Package | Owns | Depends on | Deliverable / acceptance | Must not touch |
| --- | --- | --- | --- | --- |
| WP1 Design system + web shell | apps/web/components, layout, auth pages | OpenAPI client | Storybook, axe clean | API, schema |
| WP2 Identity & workspaces | core/identity, core/workspaces, auth routers | Schema | RLS + cross-tenant tests pass | Media, billing |
| WP3 Media ingestion | core/media, uploads routers, ingest worker | WP2 | Resumable 10 GB upload; ffprobe corpus passes | Render code |
| WP4 AI pipeline | core/transcripts, core/highlights, stt/llm providers | WP3 outputs | Precision@10 report, cost per hour logged | API contracts |
| WP5 Editor + render | apps/web/editor, core/render, render worker | Render-spec schema | Golden media tests pass | Highlight scoring |
| WP6 Integrations | providers/twitch, youtube, tiktok, publishing module | WP2 | Fakes + sandbox tests; idempotency proven | Billing |
| WP7 Billing | core/billing, webhooks | WP2 | Stripe test-clock scenarios pass | Media |
| WP8 Infra & QA | infra/, CI, e2e, dashboards | All | One-command local up; staging deploy | Domain logic |

Process: each agent works on a branch per package, opens a PR with tests; CI runs the full suite plus contract diff; a human (or reviewer agent with no write access) reviews against the package's "must not touch" list; integration happens daily on main behind feature flags.

### 9.5 Launch checklist

- [ ] TikTok and YouTube audits approved (else UI states "private only")
- [ ] Terms, privacy policy, DMCA agent, takedown form, cookie banner reviewed by counsel
- [ ] DPAs signed with STT, LLM, storage, email, payments vendors
- [ ] Pentest done, criticals fixed; cross-tenant suite green
- [ ] Backups restored successfully in staging
- [ ] Spend caps and cost alerts configured on every AI vendor
- [ ] Support inbox, status page, incident runbook, on-call rota
- [ ] Stripe + Paystack live, tax settings (VAT/GST) configured
- [ ] Analytics events and funnel dashboard live

### 9.6 Risks, assumptions and open questions

| Risk | Likelihood | Impact | Mitigation |
| --- | --- | --- | --- |
| Highlight quality weak on low-speech gameplay | High | High | Chat + audio-event signals; label data per genre; honest "low confidence" UI |
| Audit rejected or delayed | Medium | High | Apply in week 1; download fallback; consider a vetted unified publishing API as interim |
| Twitch Clip-from-VOD beta changes | Medium | Medium | Feature flag; uploads remain primary |
| Incumbents ship stream features | High | Medium | Move fast on editor authorization + per-creator learning |
| Free-tier abuse | Medium | Medium | Low free allowance, verification, device/card heuristics |
| Copyright complaints (music, third-party content) | Medium | High | Rights model, takedowns, music warnings, repeat-infringer policy |
| AI cost spikes | Low | Medium | Spend caps, vendor failover, self-host path |

Open questions: exact Twitch scopes for Get Clips Download and Clip-from-VOD (confirm in Helix reference); YouTube upload quota bucket in your own Cloud Console; Instagram daily cap (docs state both 50 and 100); Kick VOD API plans; Paystack fees and NGN pricing; whether streamers will let a bot record chat.

### 9.7 Sources (accessed 17 Oct 2026)

- [Twitch Clips guide](https://dev.twitch.tv/docs/api/clips/) and [Clip-from-VOD open beta announcement](https://discuss.dev.twitch.com/t/introducing-clip-api-improvements-and-clip-from-vod-in-open-beta/64492)
- [Twitch forum: VOD downloads not supported](https://discuss.dev.twitch.tv/t/download-vods-via-api-or-other-means/28490)
- [Kick.NET SDK notes on official vs undocumented endpoints](https://github.com/DapperMickie/Kick.Net); [kick-api Rust crate](https://docs.rs/crate/kick-api/latest)
- [TikTok Content Sharing Guidelines](https://developers.tiktok.com/doc/content-sharing-guidelines)
- [Instagram Content Publishing](https://developers.facebook.com/docs/instagram-platform/content-publishing)
- YouTube upload quota and audit: [PostProxy](https://postproxy.dev/blog/automate-youtube-uploads/), [singhamandeep.com](https://singhamandeep.com/?p=1570) — confirm against Google's quota table
- X pricing: [PostProxy](https://postproxy.dev/blog/x-api-pricing-2026), [OpenTweet](https://opentweet.io/x-api-pricing) — confirm at docs.x.com
- [OpusClip pricing summary (Creatify)](https://creatify.ai/blog/opusclip-pricing-plans-and-what-you-ll-actually-pay-in-2026)
- STT pricing: [convertaudiototext](https://convertaudiototext.com/blog/speech-to-text-api-pricing-2026), [Deepgram Nova-3 explainer](https://convertaudiototext.com/blog/deepgram-nova-3-explained)

Several figures come from third-party summaries rather than vendor pages; each is marked "verify" where it matters for a build or pricing decision.

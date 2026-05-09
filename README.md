# Univoroomi

An AI-powered roommate matching platform for international students. Live at **[univoroomi.com](https://univoroomi.com)**.

---

## 1. Context, User, and Problem

### Who this is for

International students at two critical moments:

- **Pre-departure students** who just received an offer and are still in their home country, scrambling to lock in housing before the semester starts.
- **In-country students** who are graduating soon, switching apartments, or starting jobs and need to find new roommates.

### The workflow we're improving

Today, students find roommates through scattered group chats on WeChat, WhatsApp, Telegram, Xiaohongshu, Reddit, and university Facebook groups. The current workflow looks like this:

1. Post a self-introduction in five different group chats.
2. Refresh constantly, hoping someone replies or posts something matching what you want.
3. DM strangers, exchange profiles in chunks across multiple platforms.
4. Hope you didn't miss critical compatibility issues (smoking, sleep schedule, cleanliness) before signing a lease together.

I went through this myself — I posted my profile to several group chats and got no replies. The way I eventually found roommates was by manually monitoring the chats every day waiting for someone matching my criteria to post.

### Why this matters

**Speed matters.** Lease signing, visa applications, deposit transfers — none of it can move forward until a roommate is locked in. Every day spent searching is a day delayed on every downstream task.

**Filtering accuracy matters.** Group chats cannot filter. If you need a non-smoking female who eats meals at home, you have to read every post manually and DM each candidate to ask. Most people give up filtering and pick whoever responds first.

**Compatibility mistakes are expensive.** I have classmates who rushed into roommate decisions and discovered fundamental lifestyle conflicts — different sleep schedules, pet conflicts, cleanliness mismatches — only after moving in. The fallout: one party breaks the lease, handles a sublet, the other party starts over from scratch. Both lose money and weeks of time.

**Trust matters.** Students want to know their potential roommate is actually a student. We enforce education email login (`.edu`, `.ac.uk`, `.edu.cn`, etc.) — even if a user has already graduated or uses a different school's email, this still serves as a soft trust signal and a traceable channel back to the real person. It also makes it much harder to spin up throwaway accounts for spam or scams.

---

## 2. Solution and Design

### What I built

A web app where students:

1. **Register and log in** with an education email (verification required, no random Gmail accounts).
2. **Fill in a profile** with four sections: basic info, lifestyle habits, special skills (e.g., good at cooking, exterminating bugs), and a free-form bio with interests and personality.
3. **Land on the matching page**, optionally describe their ideal roommate in a search bar, optionally apply hard filters (study country, school, state, gender, language) above the search bar, and adjust how much weight to give each scoring dimension.
4. **See ranked matches** — each card shows compatibility scores per dimension, and an explanation of why each score landed where it did.
5. **Lock in a roommate** — once a chat goes well, either side can send a "Lock Roommate" invitation card with their full profile attached. The other side accepts, declines, or chooses "consider it."
6. **Hide profile when done** — once a user has locked in enough roommates, they can hide their profile from search while keeping the data preserved.

The full stack is FastAPI + PostgreSQL on Railway, React frontend on Cloudflare, Qwen-Plus for all AI scoring and translation calls.

### How matching works (`matching_service.py`)

Three independent scoring dimensions, each producing a 0–100 score, then weighted into a total.

**Objective dimension (default 30%)** — 95 points from pure rules + 5 points from a lightweight Qwen call:

| Factor | Points |
|---|---|
| Same study country | 14.25 |
| Same state/province | 14.25 |
| Same city | 14.25 |
| Same native language | 14.25 |
| Same school | 9.5 |
| Same major | 4.75 |
| Same nationality | 4.75 |
| Budget closeness | up to 19 (1% diff = -0.95) |
| Bio-extracted commonalities (AI) | up to 5 |

The bio AI call only looks for objective overlaps (same hometown, same undergraduate institution, same relationship status). It never penalizes mismatches — the floor is always 0 added points, never negative.

**Habits dimension (default 40%)** — Qwen evaluates sleep schedule, diet style, smoking, pets, cleanliness, and any lifestyle mentions in the bio. The prompt explicitly weighs serious conflicts heavily (smoker vs non-smoker = -30+, pet vs no-pet = -25+).

**Personality and interests dimension (default 30%)** — Qwen evaluates MBTI compatibility (using established research on type interactions), zodiac compatibility (holistically, not mechanically), and personality/interest descriptions in the bio. The prompt explicitly excludes lifestyle topics — those belong to the habits dimension. Missing MBTI or zodiac data triggers a small score penalty, so users with complete profiles rank higher than users with partial profiles when other factors are similar.

**Skills (display-only, not scored)** — Each card shows whether the two users have "Same" or "Complementary" skills (e.g., both can cook = Same; one can cook, one can fix electronics = Complementary). Skills don't affect the total score because we don't want users with no special skills filled in to get penalized.

**Total = 30% × Objective + 40% × Habits + 30% × Personality**

Users can adjust these weights via sliders (the UI enforces sum = 100%). When a dimension's source data is missing entirely (e.g., no MBTI, no zodiac, no bio), that dimension's weight drops to 5% and the remaining weight redistributes proportionally — so users still get a fair total even with partial data.

### Key design choices

**AI for understanding, rules for ranking.** I learned the hard way that asking AI to produce a final number directly is unreliable — Qwen tends to cluster scores around 70–75 regardless of input. So objective matching is mostly rule-based (deterministic, fast, free), and AI is used where it actually adds value: understanding free-text bios, parsing multilingual search queries, and judging fuzzy compatibility (MBTI/zodiac/personality).

**AI-parsed search across four languages.** When a user types "eat together," "一起吃饭," "一緒に食べる," or "같이 먹음" into the search bar, Qwen parses the intent into a structured filter (`{"diet_habit": "together"}`). A multilingual synonym table then normalizes whatever language is stored in the database to the same key. This way users can search in any language regardless of what language the target user filled out their profile in.

**Caching with version invalidation.** Match scores and AI explanations are cached per user pair. The cache key includes both users' `profile_version` numbers — when either user updates their profile, that user's version increments, all their cached match scores become invalid, and matches involving them get recomputed on the next refresh. This keeps results consistent (same two users always see the same score until something actually changes) while staying responsive.

**Hide-but-don't-delete.** Users who've locked in roommates can hide their profile from search via a toggle, but all data is preserved. They can restore visibility anytime.

**Education email enforcement.** All registration goes through email verification. The verification email is sent to addresses that pass an education-domain check, with whitelisted patterns including `.edu`, `.ac.uk`, `.edu.cn`, `.ac.jp`, etc.

---

## 3. Evaluation and Results

### Baselines compared against

**Baseline 1: Social media group chats (status quo).** Currently, international students simply post their self-introduction on social media platforms to seek for roommates, but it's low efficient and inaccurate. Univoroomi is much faster and clearer, yet it lacks testing due to small number of users.


**Baseline 2: Keyword-only matching (no AI).** Implemented as a switch in code via the `BASELINE_MODE` environment variable. When enabled, habits and personality scoring fall back to simple keyword/exact-match rules instead of AI calls. The objective dimension stays the same since it was already mostly rule-based. *(Note: full comparison testing for this baseline is still in progress.)*

### Test cases / rubric

I ran self-validation across the seven users currently registered on the platform, using my real profile and my actual current roommate as ground truth:

- **Self-as-target test:** When matching against a profile identical to mine, the system ranked it #1 out of 7 — confirming the scoring correctly identifies near-perfect matches.
- **Real roommate test:** When matching against my actual current roommate's profile, the system ranked them #3 out of 7 — confirming that someone I genuinely live with well does score in the top tier even though we differ on several factors (different majors, different MBTI).

### Findings

- **Score distribution is well-spread**, not clustered around the middle, after lowering Qwen's `temperature` to 0.2 and adding explicit instructions in each prompt to use the full 0–100 range.
- **AI dimension reasoning is human-readable** — the per-dimension explanations (e.g., "📍 Objective: same study country, but different cities") make matches feel transparent, not like a black box.
- **Multilingual search works end-to-end** — tested with Chinese, English, Japanese, and Korean search queries against Chinese-stored profile data, all return correct filtered results.
- **Cache hit rate is high in practice** — once a user's matches are computed, repeat visits are instant unless someone's profile changed.

### Known limitations

- The user base is small (~15 users), so real-world matching diversity is limited. Most evaluation is structural rather than empirical.
- The keyword-only baseline comparison still needs more rigorous head-to-head test cases.
- AI scoring has a baseline cost per match — currently ~2 seconds per pair, scales with `O(n)` candidates per query.

---

## 4. Artifact Snapshot
https://univoroomi.com

---

## Tech Stack

- **Backend:** FastAPI (Python 3.12), SQLAlchemy async, PostgreSQL, deployed on Railway
- **Frontend:** React + Vite + TanStack Router, Tailwind, deployed on Cloudflare, editted on lovable
- **AI:** Qwen-Plus via Alibaba Cloud Model Studio (Hong Kong endpoint), used for matching, search query parsing, and translation
- **Auth:** JWT with email verification codes
- **i18n:** Custom static `t()` helper supporting zh / en / ja / ko, plus on-demand AI translation for user-generated content

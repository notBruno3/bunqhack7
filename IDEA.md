# IDEA.md — Project "Consent" *(working name)*

> **Tagline: Authentication ≠ Intent.**
> Banks verify *who* you are. We verify *whether you actually want to.*

---

## The Problem

Every modern bank can prove it's *you* making a transaction — FaceID, fingerprint, PIN, device fingerprint. None of them can tell whether you actually *want* to make it.

This gap is the core of the fastest-growing fraud category in Europe: **Authorized Push Payment (APP) fraud**. The fraudster doesn't steal your credentials — they convince *you* to send the money. Romance scams, fake bank calls, fake investment schemes, family coercion, elder abuse. The victim authenticates perfectly. The bank sees a clean transaction. The money is gone.

APP fraud cost European consumers billions last year. Under PSD3, banks face increasing liability for failing to detect coerced or manipulated transactions. There is no current technical solution that distinguishes a willing transfer from a coerced one.

We're building it.

---

## The Core Idea

A transaction protection layer that verifies **intent**, not just identity, by combining:

1. **A behavioral risk score** on every transaction
2. **Emotional verification** via voice (Hume) for medium-risk transactions
3. **Environmental + emotional verification** via video (Gemini Live) and voice (Hume) for high-risk transactions
4. **Soft holds and human review** as fallbacks that protect both the user and the bank

The system never silently blocks. It always creates an audit trail. It always gives the user a path forward. And every interaction generates evidence the bank can use to demonstrate "best effort" intent verification — directly relevant to PSD3 compliance.

---

## How It Works

### Step 1 — Risk Scoring (every transaction)

Every transaction is classified into one of three tiers:

- `NO_RISK`
- `MID_RISK`
- `HIGH_RISK`

The classification logic is open to design — possible inputs include:

- Embeddings of past purchases vs. the current one (anomaly detection in vector space)
- Time of day vs. user's normal pattern
- Amount relative to a configured limit
- Merchant familiarity
- Device, location, and behavioral signals

The risk scoring is **not the main feature of the product** — it's a gate. The novelty is what happens after a transaction is flagged.

### Step 2 — Verification Flow by Tier

```
┌─────────────────────────────────────────────────────────────────┐
│                       NEW TRANSACTION                           │
└──────────────────────────────┬──────────────────────────────────┘
                               │
                               ▼
                       ┌──────────────┐
                       │ Risk scoring │
                       └──────┬───────┘
                              │
        ┌─────────────────────┼─────────────────────┐
        │                     │                     │
        ▼                     ▼                     ▼
   ┌─────────┐           ┌─────────┐           ┌──────────┐
   │ NO_RISK │           │MID_RISK │           │HIGH_RISK │
   └────┬────┘           └────┬────┘           └────┬─────┘
        │                     │                     │
        │                     ▼                     ▼
        │             ┌───────────────┐    ┌──────────────────┐
        │             │  Hume voice   │    │  Gemini Live     │
        │             │  verification │    │  video call      │
        │             │   (call user, │    │       +          │
        │             │  ask Qs)      │    │  Hume voice      │
        │             └───────┬───────┘    │  (simultaneous)  │
        │                     │            └────────┬─────────┘
        │            ┌────────┼─────────┐           │
        │            │        │         │           │
        │            ▼        ▼         ▼           │
        │         CLEAN   AMBIGUOUS  FLAGGED        │
        │           │       │           │           │
        │           │       ▼           │           │
        │           │  ┌─────────┐      │           │
        │           │  │Merchant │      │           │
        │           │  │ check   │      │           │
        │           │  └────┬────┘      │           │
        │           │       │           │           │
        │           │   ┌───┴───┐       │           │
        │           │   │       │       │           │
        │           │  GOOD   BAD       │           │
        │           │   │       │       │           │
        │           ▼   ▼       ▼       ▼           │
        │         ┌─────────┐ ┌──────────────┐      │
        │         │GO AHEAD │ │ HUMAN REVIEW │◄─────┤ (if check fails)
        │         └─────────┘ └──────────────┘      │
        │                                            │
        └──────────────────►┌─────────┐◄─────────────┘ (if check passes)
                            │GO AHEAD │
                            │+ logged │
                            └─────────┘
```

### NO_RISK
Transaction proceeds normally. No interruption.

### MID_RISK — Voice verification
1. App initiates a Hume voice call to the user
2. User is asked a few short questions (Hume captures prosody — fear, distress, calmness, anxiety scores)
3. Three possible outcomes:

| Hume reading | Action |
|---|---|
| **Clean** (calm, normal prosody) | Transaction proceeds |
| **Ambiguous** (~50% suspicious) | Run merchant reputation check. If merchant is reputable → proceed. If merchant is suspicious → escalate to human review |
| **Flagged** (clear distress, fear, coercion signature) | Escalate to human review |

### HIGH_RISK — Video + voice verification
1. App initiates a simultaneous video + audio call
2. **Gemini Live** processes the video feed: is the environment safe and consistent (home, office) or suspicious (public space, unfamiliar location, signs of duress)?
3. **Hume** processes the audio in parallel: emotional state, distress signals, voice consistency
4. Two outcomes:

| Combined reading | Action |
|---|---|
| **Pass** | Transaction proceeds. Full audit log retained — useful for the bank as evidence of best-effort intent verification |
| **Fail** | Transaction immediately frozen. Escalate to Bunq compliance for human review |

### Soft Holds — applied where possible
For card payments where the merchant receives an authorization independently of settlement (e.g., Ticketmaster, hotel bookings, retail card transactions), the merchant gets the auth immediately. Settlement is held while verification runs. The user never loses time-sensitive purchases.

For irrevocable rails (SEPA transfers, iDEAL), verification happens before the transaction is sent.

### Human Review
When verification fails or escalates:

- Transaction is held
- A ticket is opened with Bunq compliance
- Compliance contacts the user through a registered backup channel (not the channel that initiated the transaction)
- Transaction is held until explicitly approved by compliance + the user
- The full Hume + Gemini audit trail is attached to the ticket

---

## Why This Matters

### For the user
- **Real protection against social engineering.** The most common modern fraud type — being convinced to send money under false pretenses — has no current defense. This is one.
- **Coercion safety net.** Family pressure, abuse, manipulation. Your bank notices when something feels off, even when you can't say it.
- **No friction in normal life.** NO_RISK transactions go through normally — most users will rarely encounter the verification flow at all.
- **No lost purchases.** Soft holds mean time-sensitive purchases (event tickets, flight bookings) are never blocked while verification runs in the background.

### For the bank
- **PSD3 compliance angle.** Every verified transaction generates an audit trail proving the bank took reasonable steps to verify intent. This is directly relevant to liability under emerging EU regulation.
- **Reduced fraud losses.** APP fraud is the fastest growing category and the hardest to prevent. Even partial coverage is meaningful.
- **Brand differentiation.** Bunq is positioned as a smart, user-aligned bank. This product directly extends that brand into a real safety story competitors don't have.
- **Optional money-back guarantee** *(possibility, not committed):* "If our verification system clears a transaction and it later turns out to be fraudulent, we investigate and refund." This creates a powerful trust signal and is insurable because the post-verification fraud rate is genuinely low.

---

## What This Is *Not*

- Not a replacement for FaceID/PIN/device authentication. It runs *on top* of normal auth.
- Not a tool for blocking transactions silently. Every flag has a path forward.
- Not a kidnapping/physical-coercion solution. We do not lead with this case — it raises more product questions than it answers. We focus on social engineering, APP fraud, and coercive financial relationships, which are far more common and where emotional signals are reliably useful.
- Not perfect. Hume and Gemini are signals, not oracles. The system is designed so that imperfect signals still produce useful protection through layered verification + human review.

---

## Demo Narrative (for judges)

**Lead with the problem:**
*"APP fraud cost European consumers billions last year. The fastest growing fraud type isn't hackers — it's criminals convincing you to send money yourself. No bank today can tell the difference between a willing transfer and a coerced one. We can."*

**Show the demo:**
1. A normal €40 grocery transaction goes through silently — `NO_RISK`.
2. A €600 unusual transaction triggers a voice check. User reads a sentence calmly. Hume returns clean scores. Transaction proceeds.
3. Same transaction, but the user reads the sentence under simulated stress (fast pace, shaky voice). Hume flags it. The transaction is held. A compliance ticket is opened.
4. A €5,000 transaction triggers the video + audio call. Gemini processes the environment, Hume processes the voice. Show both signals working in parallel.

**Close with the bank value:**
*"Every interaction generates an audit trail. Every flag protects the user and the bank. This is what PSD3 compliance looks like as a product."*

---

## Technical Stack *(to be detailed separately)*

- **Hume Expression Measurement API** — voice emotion analysis (prosody)
- **Gemini Live API** — video + audio environmental verification
- **Claude (Sonnet 4.6)** — orchestration, decision logic, audit trail generation
- **Bunq sandbox API** — transaction interception and webhook integration
- **Embeddings (Gemini Embedding 2 or similar)** — possible component of risk scoring

---

## Open Questions for the Team

- Concrete implementation of risk scoring — embeddings vs. rule-based vs. hybrid?
- Demo flow: do we show all three tiers, or focus on one for impact?
- Mock vs. real Bunq API integration in the demo?
- Money-back guarantee framing: include in pitch or hold for future?
- Naming — "Consent" is a working title, open to better suggestions
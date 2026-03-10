# Test Labeling Sessions: Findings

Results from two test annotation sessions (10 reviews total, 1 annotator, 2 apps).

---

## What Was Labeled

All 10 reviews came from the Tier 1 queue (long negative: 1-2 star, 200+ chars). Nine were 1-star and one was 2-star. All were 500 characters long. Seven came from Instagram, three from TikTok. On the surface, a homogeneous batch -- same tier, same length, same general direction.

The human labels split them 60/40.

### The 6 `very_negative` Reviews

These share a common trait: emotionally charged language directed at the app or company.

- **Instagram technical regression**: "it sucks big time", "very stressful" -- a user who loved the app and is angry it broke
- **Instagram account disabled + anger**: "degrading daily", "feels like interns are working on your updates" -- personal attack on the company
- **Instagram Meta AI frustration**: "pisses me off more and more each day", "awful" -- escalating anger about unwanted features
- **Instagram account suspended + emotional**: "Why???", "worst ever", "so many memories" -- raw distress and accusation
- **TikTok political/censorship**: "RIP TikTok", framed as a deliberate takedown -- grief and outrage (labeled medium confidence because sentiment is more political than product-focused)
- **TikTok post-acquisition anger**: "App is garbage now", "pushing people off this app" -- direct hostility

### The 4 `negative` Reviews

These are clearly dissatisfied but measured in tone:

- **Instagram account disabled (polite)**: "I kindly request", "I humbly request" -- the user is upset but writes like a formal appeal. Labeled medium confidence because the sentiment is more sad than angry.
- **Instagram account disabled (formal)**: "without any clear explanation or valid reason" -- legalistic, frustrated but controlled. Also medium confidence.
- **Instagram Stories audio bug**: "infuriating" and "resent the app" but then offers a constructive solution ("add a Mute button"). The complaint is specific and actionable, not emotional.
- **TikTok FYP complaints**: Starts with "Overall, the app isn't bad" before describing frustration with content recommendations. Clearly negative, but the review acknowledges the app has merit.

---

## What 10 Labels Reveal

### 1. Same Star Rating, Different Sentiment Intensity

Nine of the 10 reviews are 1-star. The human annotator labeled them across two distinct classes:

| Star Rating | very_negative | negative |
|---|---|---|
| 1-star (9 reviews) | 5 (56%) | 4 (44%) |
| 2-star (1 review) | 1 (100%) | 0 |

A model trained on star ratings would assign all nine 1-star reviews the same label. Human annotation reveals that nearly half of them are a softer `negative` rather than `very_negative`. The 5-class taxonomy captures a real distinction that star ratings collapse.

### 2. Tone Is the Differentiator, Not Topic

The reviews cluster around two topics (account suspension and app bugs), but the label isn't driven by the topic. What determines `very_negative` vs `negative` is tone:

| Tone | Label | Example phrase |
|---|---|---|
| Angry, emotional, accusatory | `very_negative` | "worst ever", "garbage", "pisses me off" |
| Sad, formal, constructive | `negative` | "I kindly request", "the app isn't bad", "add a Mute button" |

An account suspension review labeled `very_negative` reads like a rant. An account suspension review labeled `negative` reads like a support ticket. Same complaint, different sentiment.

### 3. Confidence Tracks Ambiguity, Not Severity

| Confidence | Count | Pattern |
|---|---|---|
| high | 7 (70%) | Sentiment is obvious from the language |
| medium | 3 (30%) | Tone is restrained or mixed -- could arguably go either way |
| low | 0 | No genuinely ambiguous cases in Tier 1 |

The three medium-confidence labels were:
- A polite appeal (negative but could be neutral -- the user isn't really expressing sentiment, more pleading)
- A formal complaint (negative but the controlled tone masks the intensity)
- A political review (very_negative toward the situation but sentiment toward the app itself is indirect)

No `low` confidence labels appeared. This makes sense for Tier 1 -- these are long, substantive reviews where the direction is always clear, even if the degree is debatable. We'd expect more low-confidence labels in Tier 3 (ambiguous 3-star reviews).

### 4. Cross-App Consistency

The Instagram and TikTok reviews received similar label distributions:

| App | very_negative | negative | Total |
|---|---|---|---|
| Instagram | 4 (57%) | 3 (43%) | 7 |
| TikTok | 2 (67%) | 1 (33%) | 3 |

Both apps show the same ~60/40 split between intense and moderate negativity. The labeling criteria appear to be consistent across apps, which is important -- it means the annotator is responding to tone and language, not to app-specific bias.

### 5. No Star-Label Mismatches (Yet)

All 10 reviews had `star_label_mismatch = 0`. Stars and human labels agree on direction for every Tier 1 review. This is expected: Tier 1 selects long 1-2 star reviews, which are almost always genuinely negative.

The interesting mismatches will come from:
- **Tier 3** (3-star reviews): where a "neutral" star might hide clear positive or negative sentiment
- **Tier 2** (long positive): where a 5-star review might be labeled `neutral` if the content is just "good app" stretched to 200 characters

---

## Updated Queue State

After 2 sessions (10 reviews labeled), 88 reviews remain pending across 4 tiers:

| Tier | Original | Completed | Remaining |
|---|---|---|---|
| 1. Long negative | 26 | 10 | 16 |
| 2. Long positive | 43 | 0 | 43 |
| 3. Ambiguous middle | 16 | 0 | 16 |
| 4. Short meaningful | 13 | 0 | 13 |

The next session would continue through the remaining 16 Tier 1 reviews before moving to Tier 2 (long positive), which will provide the first opportunity to see positive sentiment labels and potential star-label mismatches.

---

## What Comes Next

The 10-label sample confirms the core hypothesis: star ratings and sentiment labels diverge on intensity even when they agree on direction. With the prototype working, the path forward is:

1. **Label through Tier 2** to get positive examples and test whether 5-star reviews also split into `positive` vs `very_positive`
2. **Label Tier 3** to find the star-label mismatches that justify the entire system
3. **Add a second annotator** to test inter-annotator agreement (Cohen's kappa) on the same reviews
4. **Scale to the full 3,000-review queue** once the label taxonomy and workflow are validated

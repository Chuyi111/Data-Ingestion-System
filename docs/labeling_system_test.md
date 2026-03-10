# Test Labeling Session: Findings

Results from the first test annotation session (2 reviews, 1 annotator).

---

## What Was Labeled

Both reviews came from the Tier 1 queue (long negative: 1-2 star, 200+ chars). Both were Instagram reviews, both 1-star, both 500 characters. On the surface, identical signal. A star-based heuristic would treat them the same way.

The human labels told a different story.

### Review 1: Labeled `very_negative` (high confidence)

A user describing repeated technical failures with Instagram Stories -- gallery won't load, video previews break, uploads keep restarting. The frustration is direct and personal: "it sucks big time", "very stressful", "it's not like this before." This is someone who used to like the app and is angry about a regression.

### Review 2: Labeled `negative` (medium confidence)

A user whose account was suspended. The tone is formal, almost legalistic -- "without any clear explanation or valid reason", "clearly the result of an automated system error." There's frustration, but it's measured and argumentative rather than emotional. The confidence was marked `medium` because the review reads more like a support ticket than a sentiment expression.

## What This Shows

**Same star rating, different sentiment intensity.** Both reviews are 1-star, but one is `very_negative` and the other is `negative`. A model trained only on star ratings would assign them the same label. The human annotator distinguished between visceral frustration (very_negative, high confidence) and formal complaint (negative, medium confidence).

This is exactly the gap the labeling system was built to address. The 5-class taxonomy captures a distinction that 1-5 stars cannot: the difference between "I'm angry" and "I'm filing a complaint."

**Confidence correlates with sentiment clarity, not with star rating.** The first review was labeled with high confidence because the sentiment is unambiguous -- the language is emotionally charged. The second was medium confidence because the tone is more restrained, making the sentiment less obvious. Both are clearly not positive, but the degree of negativity requires interpretation.

**Both reviews had zero star-label mismatch.** This was expected for Tier 1 (long negative) -- the star rating and the human label agree on direction (negative), even if they disagree on intensity. The more interesting mismatches will come from Tier 3 (3-star reviews) where the star rating is ambiguous and the human label might assign clear positive or negative sentiment.

## Implications for the Full Labeling Run

Two reviews is too small for statistical conclusions, but the test surfaced patterns that will matter at scale:

1. **Sentiment intensity varies within the same star bucket.** If this holds across hundreds of 1-star reviews, the 5-class system adds real information that a 3-class system (positive/neutral/negative) would collapse away.

2. **Confidence annotations will be useful for training.** High-confidence labels can be weighted more heavily during model training. Medium and low-confidence labels still provide signal but with appropriate uncertainty.

3. **Tier 1 reviews are easy to label.** Both labels took under a second (piped input, so timing is artificial), but the annotator never hesitated on the direction -- only on the degree. This suggests Tier 1 will be the fastest to label and will produce the most reliable labels.

4. **Tier 3 will be harder and more valuable.** The 3-star "ambiguous middle" reviews are where we expect lower confidence, more disagreement between annotators, and the biggest gap between star ratings and human labels. That's where the labeling system earns its keep.

---

## Queue Readiness

The test consumed 2 of 98 queued reviews. The remaining 96 span 17 of the 20 apps, with WhatsApp (21), Gmail (14), and Instagram (13) most represented. Three apps (YouTube, Spotify, Google Drive) have no reviews in this small queue but would be included in a full 3,000-review population run.

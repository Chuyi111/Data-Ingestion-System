# Phase 3: Reasoning & Thinking

Response to feedback on the summary deck's proposed next steps.

---

## Why Labeling Interface, Training Pipeline, and Evaluation Loops Specifically?

The short answer is that they're the only three things standing between "we have a database of reviews" and "we have a working sentiment model." But the longer answer is about what the data itself told us.

After spending weeks building the ingestion system, I ended up with a detailed picture of what this dataset actually looks like. The data quality analysis surfaced things that directly shaped what I think needs to happen next:

**The labeling interface** exists because star ratings are not sentiment labels. A 5-star review that says "ok" and a 5-star review that says "This app completely changed how I communicate with my family" are both rated 5, but they carry fundamentally different sentiment signals. The star rating is a proxy, and for the model to learn anything meaningful, we need human-annotated ground truth. The data showed us that 58.6% of reviews are 5-star and 24.7% are 1-star, which means if we naively use stars as labels, the model learns a bimodal distribution, not actual sentiment understanding.

**The training pipeline** exists because this isn't a one-shot experiment. The ingestion system runs every 4 hours and keeps growing the dataset. Any training process needs to be reproducible and re-runnable as new labeled data comes in. A notebook that trains once isn't enough when the underlying corpus is alive.

**The evaluation loops** exist because of something specific in our data: the 20 apps span very different domains (messaging, music, gaming, finance, ride-sharing). A model that works well on WhatsApp reviews might fail on Clash Royale reviews because the language, complaints, and sentiment expressions are completely different. We need per-domain evaluation, not just a single accuracy number, to know if the model is actually useful.

These three aren't arbitrary stages. They're the specific gaps I see between the infrastructure we built and the intelligence the client actually needs.

---

## What Problem Am I Most Excited to Solve First?

The labeling problem, and specifically the question of what to label first.

We have 87k reviews, but we can't label all of them, and we shouldn't try. The data quality analysis showed that roughly 39% of reviews are low-signal (single words like "good", "nice", "ok", emoji-only, repeated characters). Labeling those is a waste of annotator time because a single-word review doesn't give a model much to learn from.

On the other end, we have ~10% of reviews that are long (200+ characters), and among those, the negative ones (1-2 stars with long text) are the most valuable training examples. Someone who writes three sentences about why an app is broken is giving us rich, learnable signal. That's where I want to start.

The `v_reviews_sentiment` view already buckets reviews by sentiment and length. I designed it during Phase 1 specifically because I was thinking ahead to this moment. The labeling interface shouldn't just present random reviews; it should prioritize the ones that will teach the model the most. That's a sampling strategy problem, and it's one where the analysis work we already did directly pays off.

The other thing that excites me is the gap between star ratings and actual sentiment. A 3-star review could be "it's fine I guess" (neutral) or "I used to love this app but the last update ruined everything" (negative, despite the middling star). Those ambiguous cases are where human labeling adds the most value over simple star-based heuristics. I want to see how much signal we can extract from the "messy middle" of the rating distribution.

---

## How Do They Connect to What We Already Have?

This is where I think the upfront investment in infrastructure pays dividends. Each Phase 3 component plugs directly into something we already built:

**Labeling interface connects to the database layer.** The schema already has:
- `v_reviews_sentiment` -- filters reviews by sentiment bucket and text length, so we can serve annotators the most valuable examples first
- `v_reviews_with_app` -- gives labelers app context (genre, developer) alongside the review text, which matters for understanding domain-specific language
- `v_app_stats` -- tells us which apps have the most unlabeled-but-valuable reviews, so we can balance the labeling queue across domains

The schema would need one new table (something like `labels` with review_id, annotator, sentiment_label, confidence, timestamp), but the foundation it sits on is already there.

**Training pipeline connects to the ingestion pipeline.** The same pattern we built for data ingestion (run tracking via `scrape_runs`, atomic operations, structured logging) applies directly to training runs. Track each experiment, log the parameters, store the results. The ingestion pipeline proved that run-level audit trails are essential for debugging, and training experiments need the same discipline.

**Evaluation loops connect to the monitoring layer.** The `IngestionMonitor` already does exactly what model evaluation needs: compute metrics, compare against baselines, detect drift, store structured reports. The same architecture (compute, compare, alert, store) maps almost directly to model evaluation. Instead of tracking dedup rate over time, we'd track accuracy, F1, and per-app performance over time. The anomaly detection thresholds (z-score checks, percentage drops) transfer directly to detecting model degradation.

The monitoring layer also naturally extends to **data drift detection** once we have a model. If the ingestion monitor sees that review content length or null rates are shifting, that's an early signal that the model might need retraining before we even see accuracy drop.

---

## What's the Most Impactful Starting Point?

The labeling interface. Without it, the training pipeline has nothing to train on and the evaluation loops have nothing to evaluate.

But I'd frame it more precisely: the most impactful starting point is **a labeling interface with a smart sampling strategy**.

Here's the reasoning. If we label 1,000 reviews randomly from the 87k pool, we'll get roughly 586 five-star "good/nice/ok" reviews, 247 one-star reviews of varying quality, and a thin slice of everything else. That's an inefficient use of annotator time and produces a training set that reflects the bimodal noise of the data rather than the signal.

Instead, I'd start by labeling a stratified sample that over-represents:
1. **Long negative reviews** (1-2 star, 200+ chars) -- richest signal, most learnable
2. **Long positive reviews** (4-5 star, 200+ chars) -- balances the negative examples with substantive positive ones
3. **Ambiguous middle** (3-star, any length) -- the cases where star ratings fail as sentiment proxies
4. **Short-but-meaningful** (1-word or emoji reviews that are clearly positive/negative) -- establishes baseline labels for the low-signal tier

The quality flags from our data analysis (single-word: 22.5%, emoji-only: 3.3%) help us build this stratification. We already know the shape of the data, so we can be intentional about what we label.

Once we have even 2,000-3,000 well-chosen labeled examples, we can train a first model, evaluate it per-app, and use the evaluation results to decide what to label next (active learning). That creates a feedback loop: label, train, evaluate, find the model's weak spots, label more examples in those weak spots, retrain. Each cycle makes the model better with less total labeling effort.

That feedback loop is why all three components (labeling, training, evaluation) need to exist eventually. But the labeling interface is the bottleneck. Everything else waits on it.

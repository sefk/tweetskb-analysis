# Analyzing Sentiment Trends in TweetsKB

## Problems with a Simple Average

The most fundamental issue is that sentiment scores in TweetsKB are not evenly distributed. As the paper notes, roughly 50% of tweets have zero sentiment (neutral). If the volume of tweets changes over time — and it does, quite dramatically (the dataset goes from ~45k tweets in Jan 2013 to ~30M/month by mid-2013 as the API crawl ramped up) — then a raw average will be heavily diluted by neutral tweets in some periods and less so in others. You'd essentially be measuring "fraction of neutral tweets" as much as actual sentiment.

## A More Meaningful Approach

Rather than averaging across all tweets, you'd likely want to compute the average sentiment *only among tweets with non-zero sentiment*, separately tracking the *rate* of sentiment-bearing tweets over time. This gives you two complementary signals: how opinionated Twitter is about a topic at a given time, and what direction that opinion leans.

## Entity-Centric vs. Corpus-Wide Analysis

The corpus-wide average sentiment at any point in time is probably not very interesting — it reflects a mixture of millions of unrelated conversations. The dataset is really designed for *entity-centric* analysis: pick an entity (a politician, a brand, an event) and track its sentiment trajectory. This is much more interpretable because you're holding the topic constant.

## Aggregation Granularity

Monthly aggregation is the natural unit given how the data is distributed (files split by month), but for fast-moving events you might want weekly or even daily resolution. The tradeoff is that finer granularity means more noise, especially for less-frequently-mentioned entities. You'd want to set a minimum tweet count threshold per time bin before trusting the aggregate sentiment — bins with very few tweets will have highly variable estimates.

## Distinguishing Positive from Negative

Because SentiStrength assigns *separate* positive and negative scores (rather than a single positive-to-negative axis), you shouldn't just subtract one from the other. A tweet can have both high positive and high negative scores simultaneously (e.g., something like "I love how terrible this is"), which indicates ambivalence or sarcasm. Collapsing this into a single number loses that signal. Tracking positive intensity and negative intensity as separate time series, and separately tracking high-ambivalence tweets, gives you a richer picture.

## Confidence Thresholds and Entity Noise

Any entity-level sentiment trend is only as good as the entity annotations. Since FEL has 39% recall, you're working with a biased sample of mentions — you're seeing the less ambiguous, more clearly-written mentions and missing the idiomatic or hashtag-embedded ones. It's worth considering whether the *type* of tweet that gets entity-linked successfully might be systematically different in sentiment from the ones that don't.

## Practical Recommendation

A reasonable analysis pipeline would be:

1. Filter to tweets mentioning a specific entity (using a confidence threshold, perhaps -1 or -2 as the TweetsKB website suggests)
2. Bin by time period (monthly or weekly)
3. For each bin, compute:
   - Total tweet count
   - Fraction with non-zero sentiment
   - Mean positive intensity among sentiment-bearing tweets
   - Mean negative intensity among sentiment-bearing tweets
   - Fraction with high ambivalence
4. Look for *changes* in these metrics rather than absolute levels, since the baseline varies by entity
5. Cross-reference spikes or drops with known real-world events to validate that what you're seeing is real signal rather than data artifacts

"""
TweetsKB Exploratory Data Analysis Dashboard

Data: tweetskb_tables/date.parquet   (1,236 entities, 267 K rows)
      tweetskb_tables/entity.parquet  (81,850 entities, 1.24 M rows)
      tweetskb_tables/month.parquet   (126 rows — one per month)
Columns (date/entity): year_month, entity, post_count, total_likes, total_shares,
                        positive_sentiment, negative_sentiment, redacted, classified
Columns (month):       year_month, post_count, total_likes, total_shares

Tabs:
  Overview        — corpus-level monthly totals (month.parquet)
  Slice by Entity — per-entity comparison and sentiment scatter (entity.parquet)
  Analysis        — pre-computed findings: crypto bubble, pop culture, COVID, sentiment/growth rankings
"""

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from dash import Dash, dcc, html, Input, Output, State, callback, no_update
from urllib.parse import urlencode, parse_qs

# ── Load & prep data ──────────────────────────────────────────────────────────
df_date = pd.read_parquet("tweetskb_tables/date.parquet")
df_date["year_month"] = pd.to_datetime(df_date["year_month"], format="%Y-%m")

df_entity = pd.read_parquet("tweetskb_tables/entity.parquet")
df_entity["year_month"] = pd.to_datetime(df_entity["year_month"], format="%Y-%m")

df_month = pd.read_parquet("tweetskb_tables/month.parquet")
df_month["year_month"] = pd.to_datetime(df_month["year_month"], format="%Y-%m")

DATASETS = {"date": df_date, "entity": df_entity}

TOP_N = 200
_BOOL_DEFAULTS = ["classified", "redacted"]

CONTROL_LABEL = {"fontWeight": "600", "fontSize": "13px"}


def _top_entity_names(dataset_key, bool_filters):
    df = DATASETS[dataset_key]
    if "classified" in bool_filters:
        df = df[df["classified"]]
    if "redacted" in bool_filters:
        df = df[~df["redacted"]]
    return (
        df.groupby("entity")["post_count"]
        .sum()
        .sort_values(ascending=False)
        .head(TOP_N)
        .index.tolist()
    )


def _all_entity_names(dataset_key, bool_filters):
    """All entity names sorted by total post_count, no TOP_N cap."""
    df = DATASETS[dataset_key]
    if "classified" in bool_filters:
        df = df[df["classified"]]
    if "redacted" in bool_filters:
        df = df[~df["redacted"]]
    return (
        df.groupby("entity")["post_count"]
        .sum()
        .sort_values(ascending=False)
        .index.tolist()
    )


# Pre-compute the full entity list for every bool_filter combination so that
# case-insensitive search across all entities doesn't re-run groupby on each
# keystroke.
_ENTITY_NAMES_FULL = {
    frozenset(combo): _all_entity_names("entity", list(combo))
    for combo in [[], ["classified"], ["redacted"], ["classified", "redacted"]]
}

top_entity_names_init = _top_entity_names("entity", _BOOL_DEFAULTS)

# ── Party entity precomputation ────────────────────────────────────────────────
def _party_entity_list(keyword):
    totals = df_entity.groupby("entity")["post_count"].sum()
    matched = totals[totals.index.str.lower().str.contains(keyword)]
    return matched.sort_values(ascending=False).index.tolist()

_DEM_ENTITIES = _party_entity_list("democrat")
_REP_ENTITIES = _party_entity_list("republican")
_ALL_PARTY_ENTITIES = _DEM_ENTITIES + _REP_ENTITIES

_BLUES = ["#1e3a8a", "#1d4ed8", "#2563eb", "#3b82f6", "#60a5fa", "#93c5fd", "#bfdbfe", "#dbeafe"]
_REDS  = ["#7f1d1d", "#991b1b", "#b91c1c", "#dc2626", "#ef4444", "#f87171", "#fca5a5", "#fee2e2"]
_PARTY_COLOR_MAP = {
    **{e: _BLUES[i % len(_BLUES)] for i, e in enumerate(_DEM_ENTITIES)},
    **{e: _REDS[i % len(_REDS)]   for i, e in enumerate(_REP_ENTITIES)},
}

# Date range – identical across both datasets
ALL_MONTHS = sorted(df_date["year_month"].unique())
DATE_MIN, DATE_MAX = ALL_MONTHS[0], ALL_MONTHS[-1]
month_marks = {
    i: m.strftime("%Y-%m")
    for i, m in enumerate(ALL_MONTHS)
    if m.month == 1
}

# ── URL parameter helpers ──────────────────────────────────────────────────────
_N_MONTHS = len(ALL_MONTHS)

_URL_DEFAULTS = {
    "tab":     "month",
    "metric":  "post_count",
    "chart":   "line",
    "yscale":  "linear",
    "filters": "classified,redacted",
    "date":    f"0-{_N_MONTHS - 1}",
    "scope":   "selected",
}


def _build_search(tab, metric, chart, yscale, filters, date_range, scope, entities):
    """Return a URL query string for the given filter state; omits defaults."""
    p = {}
    if tab != _URL_DEFAULTS["tab"]:
        p["tab"] = tab
    if metric != _URL_DEFAULTS["metric"]:
        p["metric"] = metric
    if chart != _URL_DEFAULTS["chart"]:
        p["chart"] = chart
    if yscale != _URL_DEFAULTS["yscale"]:
        p["yscale"] = yscale
    filters_str = ",".join(sorted(filters or []))
    if filters_str != _URL_DEFAULTS["filters"]:
        p["filters"] = filters_str
    date_str = f"{date_range[0]}-{date_range[1]}"
    if date_str != _URL_DEFAULTS["date"]:
        p["date"] = date_str
    if scope != _URL_DEFAULTS["scope"]:
        p["scope"] = scope
    if entities:
        p["entities"] = ",".join(entities)
    return ("?" + urlencode(p)) if p else ""


def _parse_search(search):
    """Parse a URL query string into a flat {key: first_value} dict."""
    if not search:
        return {}
    return {k: v[0] for k, v in parse_qs(search.lstrip("?"), keep_blank_values=True).items()}


METRICS = {
    "post_count": "Posts in Sample",
    "total_likes": "Total Likes",
    "total_shares": "Total Shares",
    "positive_sentiment": "Avg Positive Sentiment",
    "negative_sentiment": "Avg Negative Sentiment",
}

def _nonzero_mean(series):
    """Mean excluding zero values.  Returns 0.0 if every value is zero."""
    nonzero = series[series > 0]
    return nonzero.mean() if len(nonzero) > 0 else 0.0


AGGREGATIONS = {
    "post_count": "sum",
    "total_likes": "sum",
    "total_shares": "sum",
    "positive_sentiment": _nonzero_mean,
    "negative_sentiment": _nonzero_mean,
}

# ── Analysis tab: pre-computed figures ───────────────────────────────────────
_clean_ent = df_entity[df_entity["classified"] & ~df_entity["redacted"]]

# --- Crypto/NFT bubble ---
_crypto_names = ["nft", "nfts", "ethereum", "bitcoin", "doge", "web3", "defi", "binance"]
_cr = _clean_ent[_clean_ent["entity"].isin(_crypto_names)].copy()
_cr["year"] = _cr["year_month"].dt.year
_cr_agg = _cr.groupby(["entity", "year"])["post_count"].sum().reset_index()
_fig_crypto = px.bar(
    _cr_agg, x="year", y="post_count", color="entity", barmode="group",
    title="Crypto & NFT Entity Mentions by Year",
    labels={"year": "Year", "post_count": "Posts", "entity": "Entity"},
)
_fig_crypto.update_layout(
    plot_bgcolor="white", paper_bgcolor="white",
    margin=dict(t=50, l=50, r=20, b=40),
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
)
_fig_crypto.update_xaxes(showgrid=False)
_fig_crypto.update_yaxes(gridcolor="#eee")

# --- Wordle decay ---
_wordle_df = _clean_ent[_clean_ent["entity"] == "wordle"].sort_values("year_month")
_fig_wordle = px.line(
    _wordle_df, x="year_month", y="post_count",
    title="Wordle: Rise & Decay",
    labels={"year_month": "Month", "post_count": "Posts"},
    color_discrete_sequence=["#f59e0b"],
)
_fig_wordle.update_layout(
    plot_bgcolor="white", paper_bgcolor="white",
    margin=dict(t=50, l=50, r=20, b=40),
)
_fig_wordle.update_xaxes(showgrid=False)
_fig_wordle.update_yaxes(gridcolor="#eee")

# --- BTS growth ---
_bts_df = _clean_ent[_clean_ent["entity"] == "bts"].sort_values("year_month")
_fig_bts = px.line(
    _bts_df, x="year_month", y="post_count",
    title="BTS: K-pop Fandom Growth",
    labels={"year_month": "Month", "post_count": "Posts"},
    color_discrete_sequence=["#6366f1"],
)
_fig_bts.update_layout(
    plot_bgcolor="white", paper_bgcolor="white",
    margin=dict(t=50, l=50, r=20, b=40),
)
_fig_bts.update_xaxes(showgrid=False)
_fig_bts.update_yaxes(gridcolor="#eee")

# --- COVID-19 dual-axis ---
_covid_df = _clean_ent[_clean_ent["entity"] == "covid 19"].sort_values("year_month").copy()
_covid_df["net_sentiment"] = _covid_df["positive_sentiment"] - _covid_df["negative_sentiment"]
_fig_covid = go.Figure()
_fig_covid.add_trace(go.Bar(
    x=_covid_df["year_month"], y=_covid_df["post_count"],
    name="Posts", marker_color="#60a5fa", yaxis="y",
))
_fig_covid.add_trace(go.Scatter(
    x=_covid_df["year_month"], y=_covid_df["net_sentiment"],
    name="Net Sentiment (pos − neg)", mode="lines+markers",
    marker_color="#ef4444", yaxis="y2",
))
_fig_covid.update_layout(
    title="COVID-19: Volume & Net Sentiment Over Time",
    plot_bgcolor="white", paper_bgcolor="white",
    margin=dict(t=60, l=60, r=80, b=40),
    yaxis=dict(title="Posts", gridcolor="#eee"),
    yaxis2=dict(title="Net Sentiment", overlaying="y", side="right", showgrid=False),
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    hovermode="x unified",
)
_fig_covid.update_xaxes(showgrid=False)

# --- Sentiment ranking (top 200 entities, vectorized weighted avg) ---
_top200 = _clean_ent.groupby("entity")["post_count"].sum().nlargest(200).index
_s_sub = _clean_ent[_clean_ent["entity"].isin(_top200)].copy()
_s_sub["weighted_net"] = (_s_sub["positive_sentiment"] - _s_sub["negative_sentiment"]) * _s_sub["post_count"]
_s_agg = _s_sub.groupby("entity").agg(
    weighted_net=("weighted_net", "sum"),
    total=("post_count", "sum"),
).reset_index()
_s_agg["net"] = _s_agg["weighted_net"] / _s_agg["total"]
_sent_display = pd.concat([
    _s_agg.sort_values("net").head(10),
    _s_agg.sort_values("net").tail(10),
])
_fig_sentiment = px.bar(
    _sent_display, x="net", y="entity", orientation="h",
    title="Most Positive & Negative Entities (top 200 by volume)",
    labels={"net": "Weighted Net Sentiment (pos − neg)", "entity": "Entity"},
    color="net",
    color_continuous_scale=["#e74c3c", "#f0f0f0", "#27ae60"],
    color_continuous_midpoint=0,
)
_fig_sentiment.update_layout(
    plot_bgcolor="white", paper_bgcolor="white",
    margin=dict(t=60, l=120, r=20, b=40),
    coloraxis_showscale=False,
)
_fig_sentiment.update_xaxes(gridcolor="#eee")
_fig_sentiment.update_yaxes(showgrid=False)

# --- Growth/decline (top 500, vectorized linear regression) ---
_top500 = _clean_ent.groupby("entity")["post_count"].sum().nlargest(500).index
_gs = _clean_ent[_clean_ent["entity"].isin(_top500)].copy()
_gs["month_num"] = (_gs["year_month"] - _gs["year_month"].min()).dt.days.astype(float)
_entity_mean = _gs.groupby("entity")["post_count"].transform("mean")
_gs["y_norm"] = np.where(_entity_mean > 0, _gs["post_count"] / _entity_mean, np.nan)
_gs["xc"] = _gs["month_num"] - _gs.groupby("entity")["month_num"].transform("mean")
_gs["yc"] = _gs["y_norm"] - _gs.groupby("entity")["y_norm"].transform("mean")
_gs["xc_yc"] = _gs["xc"] * _gs["yc"]
_gs["xc2"] = _gs["xc"] ** 2
_slope_agg = _gs.groupby("entity").agg(
    cov=("xc_yc", "sum"),
    var=("xc2", "sum"),
    n=("post_count", "count"),
).reset_index()
_slope_agg = _slope_agg[(_slope_agg["var"] > 0) & (_slope_agg["n"] >= 6)].copy()
_slope_agg["slope"] = _slope_agg["cov"] / _slope_agg["var"] * 365
_growth_display = pd.concat([
    _slope_agg.nsmallest(15, "slope"),
    _slope_agg.nlargest(15, "slope"),
])
_fig_growth = px.bar(
    _growth_display, x="slope", y="entity", orientation="h",
    title="Fastest Growing & Declining Entities (top 500 by volume)",
    labels={"slope": "Normalized Slope (annualized)", "entity": "Entity"},
    color="slope",
    color_continuous_scale=["#e74c3c", "#f0f0f0", "#27ae60"],
    color_continuous_midpoint=0,
)
_fig_growth.update_layout(
    plot_bgcolor="white", paper_bgcolor="white",
    margin=dict(t=60, l=120, r=20, b=40),
    coloraxis_showscale=False,
)
_fig_growth.update_xaxes(gridcolor="#eee")
_fig_growth.update_yaxes(showgrid=False)

# ── App layout ────────────────────────────────────────────────────────────────
app = Dash(__name__)
app.title = "TweetsKB EDA Dashboard"

app.layout = html.Div(
    style={"fontFamily": "system-ui, sans-serif", "backgroundColor": "#f8f9fa"},
    children=[
        # url-load-trigger fires once on page load; a clientside cb captures
        # window.location.search into url-init-search (read-once, no feedback loop).
        dcc.Store(id="url-load-trigger", data=True),
        dcc.Store(id="url-init-search"),
        dcc.Store(id="url-entity-init"),
        dcc.Store(id="url-ready", data=False),  # set True once entity-select is initialised
        dcc.Store(id="url-search-out"),   # current serialised query string
        dcc.Store(id="_url-dummy"),        # throwaway target for clientside cb
        # Header
        html.Div(
            style={
                "backgroundColor": "#2c3e50",
                "color": "white",
                "padding": "16px 24px",
                "marginBottom": "16px",
                "display": "flex",
                "justifyContent": "space-between",
                "alignItems": "center",
            },
            children=[
                html.Div(children=[
                    html.H2("TweetsKB EDA Dashboard", style={"margin": 0}),
                    html.P(
                        f"{DATE_MIN.strftime('%Y-%m')} – {DATE_MAX.strftime('%Y-%m')}",
                        style={"margin": "4px 0 0", "opacity": 0.7, "fontSize": "13px"},
                    ),
                ]),
                html.Div(
                    style={"textAlign": "right", "fontSize": "13px", "opacity": 0.85, "lineHeight": "1.8"},
                    children=[
                        html.Span("Data from the "),
                        html.A("TweetsKB Project", href="https://data.gesis.org/tweetskb/", target="_blank",
                               style={"color": "#aed6f1"}),
                        html.Br(),
                        html.Span("Source code and other info in "),
                        html.A("Github", href="https://github.com/sefk/tweetskb-analysis", target="_blank",
                               style={"color": "#aed6f1"}),
                        html.Br(),
                        html.Span("Owner: "),
                        html.A("Sef Kloninger", href="https://sef.kloninger.com", target="_blank",
                               style={"color": "#aed6f1"}),
                    ],
                ),
            ],
        ),

        # Shared controls (above tabs)
        html.Div(
            style={
                "display": "grid",
                "gridTemplateColumns": "1fr 1fr 1fr 1fr",
                "gap": "16px",
                "padding": "0 24px 8px",
            },
            children=[
                html.Div([
                    html.Label("Metric", style=CONTROL_LABEL),
                    dcc.Dropdown(
                        id="metric-select",
                        options=[{"label": v, "value": k} for k, v in METRICS.items()],
                        value="post_count",
                        clearable=False,
                    ),
                ]),
                html.Div([
                    html.Label("Chart type", style=CONTROL_LABEL),
                    dcc.RadioItems(
                        id="chart-type",
                        options=[
                            {"label": " Line", "value": "line"},
                            {"label": " Bar (stacked)", "value": "bar"},
                            {"label": " Area", "value": "area"},
                        ],
                        value="line",
                        inline=True,
                        style={"fontSize": "14px", "marginTop": "6px"},
                        inputStyle={"marginRight": "4px", "marginLeft": "10px"},
                    ),
                ]),
                html.Div([
                    html.Label("Y-axis scale", style=CONTROL_LABEL),
                    dcc.RadioItems(
                        id="yscale",
                        options=[
                            {"label": " Linear", "value": "linear"},
                            {"label": " Log", "value": "log"},
                        ],
                        value="linear",
                        inline=True,
                        style={"fontSize": "14px", "marginTop": "6px"},
                        inputStyle={"marginRight": "4px", "marginLeft": "10px"},
                    ),
                ]),
                html.Div([
                    html.Label("Filters", style=CONTROL_LABEL),
                    dcc.Checklist(
                        id="bool-filters",
                        options=[
                            {"label": " Classified only", "value": "classified"},
                            {"label": " Exclude redacted", "value": "redacted"},
                        ],
                        value=_BOOL_DEFAULTS,
                        style={"fontSize": "14px", "marginTop": "6px"},
                        inputStyle={"marginRight": "4px"},
                        labelStyle={"display": "block", "marginBottom": "4px"},
                    ),
                ]),
            ],
        ),

        # Date slider (shared)
        html.Div(
            style={"padding": "0 24px 16px"},
            children=[
                html.Label("Date range", style=CONTROL_LABEL),
                dcc.RangeSlider(
                    id="date-slider",
                    min=0,
                    max=len(ALL_MONTHS) - 1,
                    value=[0, len(ALL_MONTHS) - 1],
                    marks=month_marks,
                    tooltip={"placement": "bottom", "always_visible": False},
                    allowCross=False,
                ),
            ],
        ),

        # Tabs
        dcc.Tabs(
            id="main-tabs",
            value="month",
            children=[
                # ── Month Overview tab ────────────────────────────────────────
                dcc.Tab(
                    label="Overview",
                    value="month",
                    children=[
                        html.Div(
                            style={"padding": "16px 24px 24px"},
                            children=[
                                html.P(
                                    "Corpus-level monthly totals across all tweets — month.parquet. "
                                    "No entity breakdown; bool filters and sentiment metrics do not apply.",
                                    style={"fontSize": "13px", "color": "#666", "margin": "0 0 12px"},
                                ),
                                dcc.Graph(id="month-timeseries", style={"height": "420px"}),
                                dcc.Graph(id="overview-redacted", style={"height": "300px", "marginTop": "16px"}),
                            ],
                        ),
                    ],
                ),

                # ── Entity Deep Dive tab ───────────────────────────────────────
                dcc.Tab(
                    label="Slice by Entity",
                    value="entity",
                    children=[
                        html.Div(
                            style={"padding": "16px 24px 24px"},
                            children=[
                                # Entity controls
                                html.Div(
                                    style={"marginBottom": "8px"},
                                    children=[
                                        html.Div(
                                            style={
                                                "display": "flex",
                                                "justifyContent": "space-between",
                                                "alignItems": "center",
                                            },
                                            children=[
                                                html.Label(
                                                    "Entities",
                                                    style=CONTROL_LABEL,
                                                ),
                                                html.Div([
                                                    html.Button("Top 5", id="btn-top5", n_clicks=0,
                                                        style={"marginRight": "6px", "cursor": "pointer",
                                                               "padding": "3px 10px", "fontSize": "12px"}),
                                                    html.Button("Top 10", id="btn-top10", n_clicks=0,
                                                        style={"marginRight": "6px", "cursor": "pointer",
                                                               "padding": "3px 10px", "fontSize": "12px"}),
                                                    html.Button("Top 20", id="btn-top20", n_clicks=0,
                                                        style={"cursor": "pointer", "padding": "3px 10px",
                                                               "fontSize": "12px"}),
                                                ]),
                                            ],
                                        ),
                                        dcc.Dropdown(
                                            id="entity-select",
                                            options=[{"label": e, "value": e} for e in top_entity_names_init],
                                            value=top_entity_names_init[:8],
                                            multi=True,
                                            placeholder="Search and select entities...",
                                            style={"marginTop": "6px"},
                                        ),
                                    ],
                                ),
                                # Entity scope
                                html.Div(
                                    style={"display": "flex", "justifyContent": "flex-end",
                                           "alignItems": "center", "marginBottom": "4px"},
                                    children=[
                                        html.Label("Entity scope:",
                                                   style={"fontSize": "13px", "fontWeight": "600",
                                                          "marginRight": "8px"}),
                                        dcc.RadioItems(
                                            id="entity-scope",
                                            options=[
                                                {"label": " Selected entities", "value": "selected"},
                                                {"label": " All entities",      "value": "all"},
                                            ],
                                            value="selected",
                                            inline=True,
                                            style={"fontSize": "13px"},
                                            inputStyle={"marginRight": "4px", "marginLeft": "12px"},
                                        ),
                                    ],
                                ),
                                # Charts
                                dcc.Graph(id="entity-timeseries", style={"height": "420px"}),
                                html.Div(
                                    style={
                                        "display": "grid",
                                        "gridTemplateColumns": "1fr 1fr 1fr",
                                        "gap": "16px",
                                        "marginTop": "16px",
                                    },
                                    children=[
                                        dcc.Graph(id="entity-bar", style={"height": "340px"}),
                                        dcc.Graph(id="entity-scatter", style={"height": "340px"}),
                                        dcc.Graph(id="entity-density", style={"height": "340px"}),
                                    ],
                                ),
                                html.Div(id="entity-table", style={"marginTop": "16px"}),
                            ],
                        ),
                    ],
                ),

                # ── Analysis tab ───────────────────────────────────────────────
                dcc.Tab(
                    label="Analysis",
                    value="analysis",
                    children=[
                        html.Div(
                            style={"padding": "16px 24px 40px"},
                            children=[
                                # Section 1: Crypto/NFT Bubble
                                html.H3("Crypto & NFT Bubble", style={"marginBottom": "4px"}),
                                html.P(
                                    "NFT went from near-zero to 2.76 M posts in 2022, then collapsed 76% in 2023. "
                                    "Bitcoin and Ethereum grew steadily from 2013; Doge spiked in 2021 with the "
                                    "Elon Musk attention wave. Web3 and DeFi appeared only in 2021, peaking in "
                                    "2022 alongside NFTs.",
                                    style={"fontSize": "13px", "color": "#555", "marginBottom": "8px"},
                                ),
                                dcc.Graph(figure=_fig_crypto, style={"height": "380px"}),
                                html.Hr(style={"margin": "24px 0"}),

                                # Section 2: Pop Culture Moments
                                html.H3("Pop Culture Moments", style={"marginBottom": "4px"}),
                                html.P(
                                    "Wordle peaked at ~100 K posts in early 2022 then lost 97.5% of its volume "
                                    "in 16 months — a textbook viral-game arc. "
                                    "BTS started with just 4 posts in Jan 2013, grew steadily, and peaked at "
                                    "~903 K posts in May 2017 as the group broke into the global mainstream, "
                                    "demonstrating sustained K-pop fandom amplification.",
                                    style={"fontSize": "13px", "color": "#555", "marginBottom": "8px"},
                                ),
                                html.Div(
                                    style={"display": "grid", "gridTemplateColumns": "1fr 1fr", "gap": "16px"},
                                    children=[
                                        dcc.Graph(figure=_fig_wordle, style={"height": "300px"}),
                                        dcc.Graph(figure=_fig_bts, style={"height": "300px"}),
                                    ],
                                ),
                                html.Hr(style={"margin": "24px 0"}),

                                # Section 3: COVID-19 Timeline
                                html.H3("COVID-19 Timeline", style={"marginBottom": "4px"}),
                                html.P(
                                    '"COVID 19" appeared in Feb 2020, exploded to 194 K posts in Apr 2020, then '
                                    "faded over 3 years as news fatigue set in. Net sentiment (positive − negative) "
                                    "briefly turned positive around the vaccine rollout in early 2021, then drifted "
                                    "back negative as variants and pandemic exhaustion dominated discourse.",
                                    style={"fontSize": "13px", "color": "#555", "marginBottom": "8px"},
                                ),
                                dcc.Graph(figure=_fig_covid, style={"height": "340px"}),
                                html.Hr(style={"margin": "24px 0"}),

                                # Section 4: Entity Sentiment & Growth
                                html.H3("Entity Sentiment & Growth Trends", style={"marginBottom": "4px"}),
                                html.P(
                                    "Among the top 200 entities by volume, Tigray (Ethiopian civil war) and ISIS "
                                    "score most negatively; 'laughing' scores negative because it often appears as "
                                    "'laughing stock'. On the growth side, crypto terms (NFT, web3, ethereum) "
                                    "dominate the fastest-growing entities from 2020–2023, while Wordle and COVID "
                                    "are the fastest-declining on a normalized, annualized basis.",
                                    style={"fontSize": "13px", "color": "#555", "marginBottom": "8px"},
                                ),
                                html.Div(
                                    style={"display": "grid", "gridTemplateColumns": "1fr 1fr", "gap": "16px"},
                                    children=[
                                        dcc.Graph(figure=_fig_sentiment, style={"height": "500px"}),
                                        dcc.Graph(figure=_fig_growth, style={"height": "500px"}),
                                    ],
                                ),
                                html.Hr(style={"margin": "24px 0"}),

                                # Section 5: Democrats vs Republicans
                                html.H3("Democrats vs. Republicans", style={"marginBottom": "4px"}),
                                html.P(
                                    "Animated scatter in sentiment space (positive vs. negative sentiment). "
                                    "Bubble size = post volume. Use the date-slider and bool-filters above "
                                    "to narrow the scope.",
                                    style={"fontSize": "13px", "color": "#555", "marginBottom": "4px"},
                                ),
                                html.P(
                                    "⚠️ This chart can be very slow to load.",
                                    style={"fontSize": "13px", "color": "#b94a00", "marginBottom": "8px"},
                                ),
                                dcc.Graph(id="compare-dem-rep", style={"height": "660px"}),
                            ],
                        ),
                    ],
                ),
            ],
        ),
    ],
)


# ── Data helpers ───────────────────────────────────────────────────────────────

def filter_data(dataset, entities, date_range_idx, bool_filters):
    df = DATASETS[dataset]
    lo = ALL_MONTHS[date_range_idx[0]]
    hi = ALL_MONTHS[date_range_idx[1]]
    mask = (
        df["entity"].isin(entities)
        & (df["year_month"] >= lo)
        & (df["year_month"] <= hi)
    )
    if "classified" in bool_filters:
        mask &= df["classified"]
    if "redacted" in bool_filters:
        mask &= ~df["redacted"]
    return df[mask].copy()


def all_data(dataset, date_range_idx, bool_filters):
    """Date- and bool-filtered data for all entities, capped to TOP_N by post count."""
    df = DATASETS[dataset]
    lo = ALL_MONTHS[date_range_idx[0]]
    hi = ALL_MONTHS[date_range_idx[1]]
    mask = (df["year_month"] >= lo) & (df["year_month"] <= hi)
    if "classified" in bool_filters:
        mask &= df["classified"]
    if "redacted" in bool_filters:
        mask &= ~df["redacted"]
    sub = df[mask]
    top = sub.groupby("entity")["post_count"].sum().nlargest(TOP_N).index
    return sub[sub["entity"].isin(top)].copy()


# ── Chart helpers ──────────────────────────────────────────────────────────────

def _make_timeseries(grouped, metric, chart_type, yscale):
    metric_label = METRICS[metric]
    title = f"{metric_label} over Time"
    if chart_type == "line":
        fig = px.line(
            grouped, x="year_month", y=metric, color="entity",
            title=title,
            labels={"year_month": "Month", metric: metric_label, "entity": "Entity"},
        )
    elif chart_type == "bar":
        fig = px.bar(
            grouped, x="year_month", y=metric, color="entity",
            title=title,
            labels={"year_month": "Month", metric: metric_label, "entity": "Entity"},
            barmode="stack",
        )
    else:  # area
        fig = px.area(
            grouped, x="year_month", y=metric, color="entity",
            title=title,
            labels={"year_month": "Month", metric: metric_label, "entity": "Entity"},
        )
    fig.update_layout(
        yaxis_type=yscale,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        margin=dict(t=60, l=50, r=20, b=40),
        plot_bgcolor="white",
        paper_bgcolor="white",
        hovermode="x unified",
    )
    fig.update_xaxes(showgrid=False)
    fig.update_yaxes(gridcolor="#eee")
    return fig


def _make_bar(sub, metric):
    agg_fn = AGGREGATIONS[metric]
    totals = (
        sub.groupby("entity")[metric]
        .agg(agg_fn)
        .reset_index()
        .sort_values(metric, ascending=True)
    )
    fig = px.bar(
        totals, x=metric, y="entity", orientation="h",
        title=f"Total {METRICS[metric]} by Entity",
        labels={metric: METRICS[metric], "entity": "Entity"},
        color=metric,
        color_continuous_scale="Blues",
    )
    fig.update_layout(
        coloraxis_showscale=False,
        margin=dict(t=50, l=10, r=20, b=40),
        plot_bgcolor="white",
        paper_bgcolor="white",
        yaxis=dict(tickfont=dict(size=11)),
    )
    fig.update_xaxes(gridcolor="#eee")
    fig.update_yaxes(showgrid=False)
    return fig


def _make_summary_table(sub):
    summary = sub.groupby("entity").agg(
        Months=("year_month", "nunique"),
        Posts=("post_count", "sum"),
        Likes=("total_likes", "sum"),
        Shares=("total_shares", "sum"),
        PosSentiment=("positive_sentiment", _nonzero_mean),
        NegSentiment=("negative_sentiment", _nonzero_mean),
    ).reset_index().sort_values("Posts", ascending=False)

    summary["Likes"] = summary["Likes"].apply(lambda x: f"{x:,.0f}")
    summary["Shares"] = summary["Shares"].apply(lambda x: f"{x:,.0f}")
    summary["Posts"] = summary["Posts"].apply(lambda x: f"{x:,.0f}")
    summary["PosSentiment"] = summary["PosSentiment"].apply(lambda x: f"{x:.3f}")
    summary["NegSentiment"] = summary["NegSentiment"].apply(lambda x: f"{x:.3f}")
    summary = summary.rename(columns={
        "entity": "Entity",
        "PosSentiment": "Pos Sentiment",
        "NegSentiment": "Neg Sentiment",
    })

    header_style = {
        "backgroundColor": "#2c3e50",
        "color": "white",
        "padding": "8px 12px",
        "textAlign": "left",
        "fontSize": "13px",
        "fontWeight": "600",
    }
    cell_style = {
        "padding": "7px 12px",
        "fontSize": "13px",
        "borderBottom": "1px solid #eee",
    }

    headers = [html.Th(col, style=header_style) for col in summary.columns]
    rows = []
    for i, row in summary.iterrows():
        bg = "#fafafa" if i % 2 == 0 else "white"
        rows.append(html.Tr(
            [html.Td(val, style={**cell_style, "backgroundColor": bg}) for val in row],
        ))

    return html.Div([
        html.H4("Summary Table", style={"marginBottom": "8px", "fontSize": "14px", "fontWeight": "600"}),
        html.Table(
            [html.Thead(html.Tr(headers)), html.Tbody(rows)],
            style={
                "width": "100%",
                "borderCollapse": "collapse",
                "backgroundColor": "white",
                "border": "1px solid #eee",
                "borderRadius": "4px",
            },
        ),
    ])


# ── Callbacks ──────────────────────────────────────────────────────────────────

@callback(
    Output("entity-select", "options"),
    Output("entity-select", "value"),
    Output("url-ready", "data"),
    Input("bool-filters", "value"),
    Input("btn-top5", "n_clicks"),
    Input("btn-top10", "n_clicks"),
    Input("btn-top20", "n_clicks"),
    Input("entity-select", "search_value"),
    Input("url-entity-init", "data"),
    State("entity-select", "value"),
    prevent_initial_call=True,
)
def update_entity_options(bool_filters, n5, n10, n20, search_value, url_entities, current_value):
    from dash import ctx
    triggered = ctx.triggered_id

    # URL-specified entities on initial load: restore selection from bookmark.
    # url_entities == [] means "no URL entities — use the top-8 defaults".
    # url_entities == list of names means "restore these specific entities".
    # In both cases set url-ready=True to unblock sync_url.
    if triggered == "url-entity-init":
        names = _top_entity_names("entity", bool_filters)
        if not url_entities:
            # No entities in URL — initialise with top-8 defaults
            options = [{"label": e, "value": e} for e in names]
            return options, names[:8], True
        names_set = set(names)
        extras = [e for e in url_entities if e not in names_set]
        options = [{"label": e, "value": e} for e in names + extras]
        return options, url_entities, True

    # Typing/clearing in the search box: update options but never touch the selection.
    if triggered == "entity-select":
        names = _top_entity_names("entity", bool_filters)
        if search_value:
            # Case-insensitive substring match across ALL entities, capped at TOP_N.
            all_names = _ENTITY_NAMES_FULL.get(
                frozenset(bool_filters or []),
                names,
            )
            needle = search_value.lower()
            matched = [e for e in all_names if needle in e.lower()][:TOP_N]
        else:
            matched = names
        # Always include currently selected entities in the options so Dash
        # never silently drops them when the options list changes.
        matched_set = set(matched)
        extras = [e for e in (current_value or []) if e not in matched_set]
        options = [{"label": e, "value": e} for e in matched + extras]
        return options, no_update, no_update

    names = _top_entity_names("entity", bool_filters)
    # Always ensure currently selected entities appear in the options list even
    # if they fall outside the top-N under the current filters.
    names_set = set(names)
    extras = [e for e in (current_value or []) if e not in names_set]
    options = [{"label": e, "value": e} for e in names + extras]

    if triggered == "btn-top5":
        value = names[:5]
    elif triggered == "btn-top10":
        value = names[:10]
    elif triggered == "btn-top20":
        value = names[:20]
    elif triggered == "bool-filters":
        # Filters changed: refresh options but preserve the current entity
        # selection.  Returning no_update keeps entity-select.value unchanged
        # so chart callbacks fire from their direct bool-filters Input rather
        # than from a value-change signal that may be suppressed when the top-N
        # list happens to be identical under the new filter.
        return options, no_update, no_update
    else:
        # Initial load (should not normally reach here with prevent_initial_call=True)
        value = names[:8]
    return options, value, no_update


# Entity Deep Dive callbacks

@callback(
    Output("entity-timeseries", "figure"),
    Input("entity-select", "value"),
    Input("metric-select", "value"),
    Input("chart-type", "value"),
    Input("yscale", "value"),
    Input("date-slider", "value"),
    Input("bool-filters", "value"),
    Input("entity-scope", "value"),
)
def update_entity_timeseries(entities, metric, chart_type, yscale, date_range, bool_filters, entity_scope):
    agg_fn = AGGREGATIONS[metric]
    if entity_scope == "all":
        sub = all_data("entity", date_range, bool_filters)
        grouped = (
            sub.groupby("year_month")[metric]
            .agg(agg_fn)
            .reset_index()
            .sort_values("year_month")
        )
        grouped["entity"] = "All entities"
    else:
        if not entities:
            return go.Figure()
        sub = filter_data("entity", entities, date_range, bool_filters)
        grouped = (
            sub.groupby(["year_month", "entity"])[metric]
            .agg(agg_fn)
            .reset_index()
            .sort_values("year_month")
        )
    return _make_timeseries(grouped, metric, chart_type, yscale)


@callback(
    Output("entity-bar", "figure"),
    Input("entity-select", "value"),
    Input("metric-select", "value"),
    Input("date-slider", "value"),
    Input("bool-filters", "value"),
    Input("entity-scope", "value"),
)
def update_entity_bar(entities, metric, date_range, bool_filters, entity_scope):
    if entity_scope == "all":
        sub = all_data("entity", date_range, bool_filters)
    else:
        if not entities:
            return go.Figure()
        sub = filter_data("entity", entities, date_range, bool_filters)
    return _make_bar(sub, metric)


@callback(
    Output("entity-scatter", "figure"),
    Input("entity-select", "value"),
    Input("date-slider", "value"),
    Input("bool-filters", "value"),
    Input("entity-scope", "value"),
)
def update_entity_scatter(entities, date_range, bool_filters, entity_scope):
    if entity_scope == "all":
        sub = all_data("entity", date_range, bool_filters)
    else:
        if not entities:
            return go.Figure()
        sub = filter_data("entity", entities, date_range, bool_filters)
    summary = sub.groupby(["entity", "year_month"]).agg(
        post_count=("post_count", "sum"),
        total_likes=("total_likes", "sum"),
        total_shares=("total_shares", "sum"),
        positive_sentiment=("positive_sentiment", _nonzero_mean),
        negative_sentiment=("negative_sentiment", _nonzero_mean),
    ).reset_index()
    summary["year_month"] = summary["year_month"].dt.strftime("%Y-%m")

    fig = px.scatter(
        summary,
        x="positive_sentiment",
        y="negative_sentiment",
        size="post_count",
        color="entity",
        animation_frame="year_month",
        animation_group="entity",
        hover_data=["total_likes", "total_shares", "post_count"],
        title="Sentiment Space (bubble size = posts in sample)",
        labels={
            "positive_sentiment": "Avg Positive Sentiment",
            "negative_sentiment": "Avg Negative Sentiment",
            "year_month": "Month",
        },
        size_max=60,
        range_x=[-0.05, 1.05],
        range_y=[-0.05, 1.05],
    )
    fig.update_layout(
        margin=dict(t=50, l=50, r=20, b=40),
        plot_bgcolor="white",
        paper_bgcolor="white",
        showlegend=False,
    )
    fig.update_xaxes(gridcolor="#eee")
    fig.update_yaxes(gridcolor="#eee")
    fig.add_shape(
        type="line", x0=0, y0=0, x1=1, y1=1,
        line=dict(color="#ccc", dash="dot", width=1),
    )
    return fig


@callback(
    Output("entity-table", "children"),
    Input("entity-select", "value"),
    Input("date-slider", "value"),
    Input("bool-filters", "value"),
    Input("entity-scope", "value"),
)
def update_entity_table(entities, date_range, bool_filters, entity_scope):
    if entity_scope == "all":
        sub = all_data("entity", date_range, bool_filters)
    else:
        if not entities:
            return html.P("Select entities above to see a summary table.")
        sub = filter_data("entity", entities, date_range, bool_filters)
    return _make_summary_table(sub)


@callback(
    Output("entity-density", "figure"),
    Input("entity-select", "value"),
    Input("date-slider", "value"),
    Input("bool-filters", "value"),
    Input("entity-scope", "value"),
)
def update_entity_density(entities, date_range, bool_filters, entity_scope):
    if entity_scope == "all":
        sub = all_data("entity", date_range, bool_filters)
    else:
        if not entities:
            return go.Figure()
        sub = filter_data("entity", entities, date_range, bool_filters)
    # Drop rows with no sentiment signal (both zero means no data that month)
    sub = sub[(sub["positive_sentiment"] > 0) | (sub["negative_sentiment"] > 0)]
    if sub.empty:
        return go.Figure()
    fig = px.density_heatmap(
        sub,
        x="positive_sentiment",
        y="negative_sentiment",
        nbinsx=4,
        nbinsy=4,
        title="Sentiment Density (4×4)",
        labels={
            "positive_sentiment": "Avg Positive Sentiment",
            "negative_sentiment": "Avg Negative Sentiment",
        },
        color_continuous_scale="Blues",
    )
    fig.update_layout(
        margin=dict(t=50, l=50, r=20, b=40),
        plot_bgcolor="white",
        paper_bgcolor="white",
        xaxis=dict(range=[-0.05, 1.05]),
        yaxis=dict(range=[-0.05, 1.05]),
    )
    fig.update_xaxes(gridcolor="#eee")
    fig.update_yaxes(gridcolor="#eee")
    return fig


# Month Overview callbacks

@callback(
    Output("month-timeseries", "figure"),
    Input("metric-select", "value"),
    Input("chart-type", "value"),
    Input("yscale", "value"),
    Input("date-slider", "value"),
)
def update_month_timeseries(metric, chart_type, yscale, date_range):
    if metric in ("positive_sentiment", "negative_sentiment"):
        fig = go.Figure()
        fig.update_layout(
            title="Sentiment metrics are not available in month.parquet",
            plot_bgcolor="white",
            paper_bgcolor="white",
        )
        return fig
    lo = ALL_MONTHS[date_range[0]]
    hi = ALL_MONTHS[date_range[1]]
    sub = df_month[(df_month["year_month"] >= lo) & (df_month["year_month"] <= hi)].copy()
    sub["entity"] = "All tweets"
    return _make_timeseries(sub.sort_values("year_month"), metric, chart_type, yscale)


@callback(
    Output("overview-redacted", "figure"),
    Input("date-slider", "value"),
)
def update_overview_redacted(date_range):
    lo = ALL_MONTHS[date_range[0]]
    hi = ALL_MONTHS[date_range[1]]
    sub = df_date[(df_date["year_month"] >= lo) & (df_date["year_month"] <= hi)]
    totals = (
        sub.groupby(["year_month", "redacted"])["post_count"]
        .sum()
        .reset_index()
    )
    month_totals = totals.groupby("year_month")["post_count"].sum().rename("month_total")
    totals = totals.join(month_totals, on="year_month")
    totals["pct"] = totals["post_count"] / totals["month_total"] * 100
    totals["label"] = totals["redacted"].map({True: "Redacted", False: "Non-redacted"})
    totals = totals.sort_values("year_month")

    fig = px.area(
        totals,
        x="year_month",
        y="pct",
        color="label",
        title="Redacted vs Non-redacted Entities — % of Posts",
        labels={"year_month": "Month", "pct": "% of Posts", "label": ""},
        color_discrete_map={"Redacted": "#e74c3c", "Non-redacted": "#3498db"},
    )
    fig.update_layout(
        margin=dict(t=50, l=50, r=20, b=40),
        plot_bgcolor="white",
        paper_bgcolor="white",
        hovermode="x unified",
        yaxis=dict(range=[0, 100], ticksuffix="%"),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    fig.update_xaxes(showgrid=False)
    fig.update_yaxes(gridcolor="#eee")
    return fig


# Analysis tab callbacks

@callback(
    Output("compare-dem-rep", "figure"),
    Input("date-slider", "value"),
    Input("bool-filters", "value"),
)
def update_compare_dem_rep(date_range, bool_filters):
    if not _ALL_PARTY_ENTITIES:
        return go.Figure()
    # The comparison chart pre-selects entities by keyword, so the "classified"
    # filter must not be applied — most party entities are stored with
    # classified=False and would be dropped, leaving only ~3 survivors.
    # Still honour "redacted" to exclude profanity-replacement tokens.
    party_filters = ["redacted"] if "redacted" in bool_filters else []
    sub = filter_data("entity", _ALL_PARTY_ENTITIES, date_range, party_filters)
    if sub.empty:
        return go.Figure()
    summary = sub.groupby(["entity", "year_month"]).agg(
        post_count=("post_count", "sum"),
        total_likes=("total_likes", "sum"),
        total_shares=("total_shares", "sum"),
        positive_sentiment=("positive_sentiment", _nonzero_mean),
        negative_sentiment=("negative_sentiment", _nonzero_mean),
    ).reset_index()
    summary["year_month"] = summary["year_month"].dt.strftime("%Y-%m")
    # px.scatter with animation_frame creates traces only for entities present
    # in the first frame.  Reindex to a full (entity × year_month) grid so
    # every entity appears in every frame; missing months get NaN and are not
    # rendered as points but keep the trace — and legend entry — alive.
    all_ym = sorted(summary["year_month"].unique())
    all_entities = summary["entity"].unique()
    full_idx = pd.MultiIndex.from_product(
        [all_entities, all_ym], names=["entity", "year_month"]
    )
    summary = (
        summary.set_index(["entity", "year_month"])
        .reindex(full_idx)
        .reset_index()
        .sort_values("year_month")
    )
    summary["post_count"] = summary["post_count"].fillna(0)
    summary["total_likes"] = summary["total_likes"].fillna(0)
    summary["total_shares"] = summary["total_shares"].fillna(0)
    # px.scatter drops rows with NaN x/y when building frame-0 traces, so
    # entities absent from frame 0 never get a legend entry even after reindex.
    # Fill ghost rows with sentinel coords outside chart bounds (clipped, invisible)
    # so every entity gets a trace — and legend entry — in frame 0.
    ghost = summary["positive_sentiment"].isna()
    summary.loc[ghost, "positive_sentiment"] = -1.0
    summary.loc[ghost, "negative_sentiment"] = -1.0
    fig = px.scatter(
        summary,
        x="positive_sentiment",
        y="negative_sentiment",
        size="post_count",
        color="entity",
        animation_frame="year_month",
        animation_group="entity",
        hover_data=["total_likes", "total_shares", "post_count"],
        title="Democrats vs. Republicans",
        labels={
            "positive_sentiment": "Avg Positive Sentiment",
            "negative_sentiment": "Avg Negative Sentiment",
            "year_month": "Month",
        },
        size_max=60,
        range_x=[-0.05, 1.05],
        range_y=[-0.05, 1.05],
        color_discrete_map=_PARTY_COLOR_MAP,
    )
    fig.update_layout(
        margin=dict(t=50, l=50, r=180, b=40),
        plot_bgcolor="white",
        paper_bgcolor="white",
        legend=dict(
            orientation="v",
            x=1.02, xanchor="left",
            y=1.0, yanchor="top",
            font=dict(size=11),
        ),
    )
    fig.update_xaxes(gridcolor="#eee")
    fig.update_yaxes(gridcolor="#eee")
    fig.add_shape(
        type="line", x0=0, y0=0, x1=1, y1=1,
        line=dict(color="#ccc", dash="dot", width=1),
    )
    return fig


# ── URL ↔ filter sync ─────────────────────────────────────────────────────────

@callback(
    Output("main-tabs", "value"),
    Output("metric-select", "value"),
    Output("chart-type", "value"),
    Output("yscale", "value"),
    Output("bool-filters", "value"),
    Output("date-slider", "value"),
    Output("entity-scope", "value"),
    Output("url-entity-init", "data"),
    Input("url-init-search", "data"),
)
def apply_url_params(search):
    """On page load, push query-param values into every filter component so a
    bookmarked or shared URL is fully restored.  Uses url-init-search (populated
    once by a clientside callback from window.location.search) rather than
    dcc.Location to avoid the replaceState → re-fire feedback loop."""
    p = _parse_search(search)

    tab = p.get("tab", _URL_DEFAULTS["tab"])
    if tab not in ("month", "entity", "analysis"):
        tab = _URL_DEFAULTS["tab"]

    metric = p.get("metric", _URL_DEFAULTS["metric"])
    if metric not in METRICS:
        metric = _URL_DEFAULTS["metric"]

    chart = p.get("chart", _URL_DEFAULTS["chart"])
    if chart not in ("line", "bar", "area"):
        chart = _URL_DEFAULTS["chart"]

    yscale = p.get("yscale", _URL_DEFAULTS["yscale"])
    if yscale not in ("linear", "log"):
        yscale = _URL_DEFAULTS["yscale"]

    if "filters" in p:
        valid_filters = {"classified", "redacted"}
        filters = [f for f in p["filters"].split(",") if f in valid_filters]
    else:
        filters = list(_BOOL_DEFAULTS)

    if "date" in p:
        try:
            lo, hi = map(int, p["date"].split("-"))
            lo = max(0, min(lo, _N_MONTHS - 1))
            hi = max(lo, min(hi, _N_MONTHS - 1))
            date_val = [lo, hi]
        except (ValueError, AttributeError):
            date_val = [0, _N_MONTHS - 1]
    else:
        date_val = [0, _N_MONTHS - 1]

    scope = p.get("scope", _URL_DEFAULTS["scope"])
    if scope not in ("selected", "all"):
        scope = _URL_DEFAULTS["scope"]

    # Entities: always output to url-entity-init so update_entity_options
    # (which now has prevent_initial_call=True) fires exactly once with the
    # right set of entities.  An empty list signals "use top-8 defaults".
    entities_str = p.get("entities", "")
    entities_init = (
        [e.strip() for e in entities_str.split(",") if e.strip()]
        if entities_str else []
    )

    return tab, metric, chart, yscale, filters, date_val, scope, entities_init


@callback(
    Output("url-search-out", "data"),
    Input("main-tabs", "value"),
    Input("metric-select", "value"),
    Input("chart-type", "value"),
    Input("yscale", "value"),
    Input("bool-filters", "value"),
    Input("date-slider", "value"),
    Input("entity-scope", "value"),
    Input("entity-select", "value"),
    Input("url-ready", "data"),
    prevent_initial_call=True,
)
def sync_url(tab, metric, chart, yscale, filters, date_range, scope, entities, url_ready):
    """Serialise filter state into url-search-out.  Blocked until url-ready is
    True (set by update_entity_options once entity-select is initialised from
    URL params) to prevent writing the top-8 default before initialisation
    completes.  The clientside callback below pushes it to the browser address
    bar via replaceState."""
    if not url_ready:
        return no_update
    return _build_search(tab, metric, chart, yscale, filters, date_range, scope, entities)


# ── One-shot URL capture ──────────────────────────────────────────────────────
# Runs exactly once on page load: reads window.location.search and writes it
# into url-init-search so that apply_url_params can restore filter state.
# Using a Store trigger (not dcc.Location) avoids the replaceState feedback loop.
app.clientside_callback(
    """
    function(_trigger) {
        return window.location.search || '';
    }
    """,
    Output("url-init-search", "data"),
    Input("url-load-trigger", "data"),
)

# ── Live URL sync ─────────────────────────────────────────────────────────────
# Push the query string to the browser address bar without triggering navigation.
# replaceState does NOT fire popstate, but React Router (used by dcc.Location)
# also listens via history.listen() which DOES catch replaceState.  Since
# apply_url_params now reads url-init-search (one-shot) rather than dcc.Location,
# a replaceState call can no longer re-trigger apply_url_params.
app.clientside_callback(
    """
    function(search) {
        if (search === null || search === undefined) return null;
        window.history.replaceState(
            null, '',
            window.location.pathname + (search || '')
        );
        return null;
    }
    """,
    Output("_url-dummy", "data"),
    Input("url-search-out", "data"),
)


if __name__ == "__main__":
    app.run(debug=True, host='0.0.0.0', port=8050)

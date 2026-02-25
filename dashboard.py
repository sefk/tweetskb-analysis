"""
TweetsKB Exploratory Data Analysis Dashboard

Data: tweetskb_tables/date.parquet   (1,236 entities, 267 K rows)
      tweetskb_tables/entity.parquet  (81,850 entities, 1.24 M rows)
      tweetskb_tables/month.parquet   (126 rows — one per month)
Columns (date/entity): year_month, entity, post_count, total_likes, total_shares,
                        positive_sentiment, negative_sentiment, redacted, classified
Columns (month):       year_month, post_count, total_likes, total_shares

Tabs:
  Month Overview  — corpus-level monthly totals (month.parquet)
  Overview        — aggregate trends across all entities (date.parquet)
  Entity Deep Dive — per-entity comparison and sentiment scatter (entity.parquet)
"""

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from dash import Dash, dcc, html, Input, Output, State, callback

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

# Date range – identical across both datasets
ALL_MONTHS = sorted(df_date["year_month"].unique())
DATE_MIN, DATE_MAX = ALL_MONTHS[0], ALL_MONTHS[-1]
month_marks = {
    i: m.strftime("%Y-%m")
    for i, m in enumerate(ALL_MONTHS)
    if m.month == 1
}

METRICS = {
    "post_count": "Post Count",
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

# ── App layout ────────────────────────────────────────────────────────────────
app = Dash(__name__)
app.title = "TweetsKB EDA Dashboard"

app.layout = html.Div(
    style={"fontFamily": "system-ui, sans-serif", "backgroundColor": "#f8f9fa"},
    children=[
        # Header
        html.Div(
            style={
                "backgroundColor": "#2c3e50",
                "color": "white",
                "padding": "16px 24px",
                "marginBottom": "16px",
            },
            children=[
                html.H2("TweetsKB EDA Dashboard", style={"margin": 0}),
                html.P(
                    f"{DATE_MIN.strftime('%Y-%m')} – {DATE_MAX.strftime('%Y-%m')}",
                    style={"margin": "4px 0 0", "opacity": 0.7, "fontSize": "13px"},
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
                    label="Month Overview",
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
                            ],
                        ),
                    ],
                ),

                # ── Overview tab ──────────────────────────────────────────────
                dcc.Tab(
                    label="Overview",
                    value="overview",
                    children=[
                        html.Div(
                            style={"padding": "16px 24px 24px"},
                            children=[
                                html.P(
                                    "Aggregate trends across all entities — date.parquet.",
                                    style={"fontSize": "13px", "color": "#666", "margin": "0 0 12px"},
                                ),
                                dcc.Graph(id="overview-timeseries", style={"height": "420px"}),
                                dcc.Graph(id="overview-sentiment", style={"height": "280px", "marginTop": "16px"}),
                                html.Div(
                                    style={
                                        "display": "grid",
                                        "gridTemplateColumns": "1fr 1fr",
                                        "gap": "16px",
                                        "marginTop": "16px",
                                    },
                                    children=[
                                        dcc.Graph(id="overview-bar", style={"height": "340px"}),
                                        html.Div(id="overview-table"),
                                    ],
                                ),
                            ],
                        ),
                    ],
                ),

                # ── Entity Deep Dive tab ───────────────────────────────────────
                dcc.Tab(
                    label="Entity Deep Dive",
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
                                                    "Entities (select up to 20 to compare)",
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
                                        "gridTemplateColumns": "1fr 1fr",
                                        "gap": "16px",
                                        "marginTop": "16px",
                                    },
                                    children=[
                                        dcc.Graph(id="entity-bar", style={"height": "340px"}),
                                        dcc.Graph(id="entity-scatter", style={"height": "340px"}),
                                    ],
                                ),
                                html.Div(id="entity-table", style={"marginTop": "16px"}),
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
    Input("bool-filters", "value"),
    Input("btn-top5", "n_clicks"),
    Input("btn-top10", "n_clicks"),
    Input("btn-top20", "n_clicks"),
    Input("entity-select", "search_value"),
    State("entity-select", "value"),
)
def update_entity_options(bool_filters, n5, n10, n20, search_value, current_value):
    from dash import ctx, no_update
    triggered = ctx.triggered_id

    # Any trigger from the entity dropdown itself (typing or clearing the search
    # box) must never reset the selection — only buttons and filter changes do.
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
        return options, no_update

    names = _top_entity_names("entity", bool_filters)
    options = [{"label": e, "value": e} for e in names]
    if triggered == "btn-top5":
        value = names[:5]
    elif triggered == "btn-top10":
        value = names[:10]
    elif triggered == "btn-top20":
        value = names[:20]
    else:
        value = names[:8]
    return options, value


# Overview callbacks

@callback(
    Output("overview-timeseries", "figure"),
    Input("metric-select", "value"),
    Input("chart-type", "value"),
    Input("yscale", "value"),
    Input("date-slider", "value"),
    Input("bool-filters", "value"),
)
def update_overview_timeseries(metric, chart_type, yscale, date_range, bool_filters):
    agg_fn = AGGREGATIONS[metric]
    sub = all_data("date", date_range, bool_filters)
    grouped = (
        sub.groupby("year_month")[metric]
        .agg(agg_fn)
        .reset_index()
        .sort_values("year_month")
    )
    grouped["entity"] = "All entities"
    return _make_timeseries(grouped, metric, chart_type, yscale)


@callback(
    Output("overview-sentiment", "figure"),
    Input("date-slider", "value"),
    Input("bool-filters", "value"),
)
def update_overview_sentiment(date_range, bool_filters):
    sub = all_data("date", date_range, bool_filters)
    grouped = (
        sub.groupby("year_month")[["positive_sentiment", "negative_sentiment"]]
        .agg(_nonzero_mean)
        .reset_index()
        .sort_values("year_month")
    )
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=grouped["year_month"], y=grouped["positive_sentiment"],
        name="Positive", mode="lines",
        line=dict(color="#27ae60", width=2),
    ))
    fig.add_trace(go.Scatter(
        x=grouped["year_month"], y=grouped["negative_sentiment"],
        name="Negative", mode="lines",
        line=dict(color="#e74c3c", width=2),
    ))
    fig.update_layout(
        title="Average Sentiment over Time",
        margin=dict(t=50, l=50, r=20, b=40),
        plot_bgcolor="white",
        paper_bgcolor="white",
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        yaxis=dict(title="Avg Sentiment"),
        xaxis=dict(title="Month"),
    )
    fig.update_xaxes(showgrid=False)
    fig.update_yaxes(gridcolor="#eee")
    return fig


@callback(
    Output("overview-bar", "figure"),
    Input("metric-select", "value"),
    Input("date-slider", "value"),
    Input("bool-filters", "value"),
)
def update_overview_bar(metric, date_range, bool_filters):
    sub = all_data("date", date_range, bool_filters)
    return _make_bar(sub, metric)


@callback(
    Output("overview-table", "children"),
    Input("date-slider", "value"),
    Input("bool-filters", "value"),
)
def update_overview_table(date_range, bool_filters):
    sub = all_data("date", date_range, bool_filters)
    return _make_summary_table(sub)


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
        title="Sentiment Space (bubble size = post count)",
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


if __name__ == "__main__":
    app.run(debug=True, port=8050)

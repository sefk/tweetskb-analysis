"""
TweetsKB Exploratory Data Analysis Dashboard

Data: tweetskb_tables/date.parquet
Columns: year_month, entity, post_count, total_likes, total_shares,
         positive_sentiment, negative_sentiment
"""

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from dash import Dash, dcc, html, Input, Output, callback

# ── Load & prep data ──────────────────────────────────────────────────────────
df = pd.read_parquet("tweetskb_tables/date.parquet")
df["year_month"] = pd.to_datetime(df["year_month"], format="%Y-%m")

# Pre-compute top entities by total post count (for default selection)
top_entities = (
    df.groupby("entity")["post_count"].sum().sort_values(ascending=False).head(200)
)
top_entity_names = top_entities.index.tolist()
default_entities = top_entity_names[:8]

METRICS = {
    "post_count": "Post Count",
    "total_likes": "Total Likes",
    "total_shares": "Total Shares",
    "positive_sentiment": "Avg Positive Sentiment",
    "negative_sentiment": "Avg Negative Sentiment",
}

AGGREGATIONS = {
    "post_count": "sum",
    "total_likes": "sum",
    "total_shares": "sum",
    "positive_sentiment": "mean",
    "negative_sentiment": "mean",
}

DATE_MIN = df["year_month"].min()
DATE_MAX = df["year_month"].max()
ALL_MONTHS = sorted(df["year_month"].unique())
month_marks = {
    i: m.strftime("%Y-%m")
    for i, m in enumerate(ALL_MONTHS)
    if m.month == 1  # label only January of each year
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
                    f"261K rows · 1,234 entities · {DATE_MIN.strftime('%Y-%m')} – {DATE_MAX.strftime('%Y-%m')}",
                    style={"margin": "4px 0 0", "opacity": 0.7, "fontSize": "13px"},
                ),
            ],
        ),
        # Controls row
        html.Div(
            style={
                "display": "grid",
                "gridTemplateColumns": "1fr 1fr 1fr",
                "gap": "16px",
                "padding": "0 24px 16px",
            },
            children=[
                # Metric selector
                html.Div([
                    html.Label("Metric", style={"fontWeight": "600", "fontSize": "13px"}),
                    dcc.Dropdown(
                        id="metric-select",
                        options=[{"label": v, "value": k} for k, v in METRICS.items()],
                        value="post_count",
                        clearable=False,
                    ),
                ]),
                # Chart type
                html.Div([
                    html.Label("Chart type", style={"fontWeight": "600", "fontSize": "13px"}),
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
                # Scale toggle
                html.Div([
                    html.Label("Y-axis scale", style={"fontWeight": "600", "fontSize": "13px"}),
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
            ],
        ),
        # Date range slider
        html.Div(
            style={"padding": "0 24px 8px"},
            children=[
                html.Label(
                    "Date range",
                    style={"fontWeight": "600", "fontSize": "13px"},
                ),
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
        # Entity selector
        html.Div(
            style={"padding": "0 24px 16px"},
            children=[
                html.Div(
                    style={"display": "flex", "justifyContent": "space-between", "alignItems": "center"},
                    children=[
                        html.Label(
                            "Entities (select up to 20 to compare)",
                            style={"fontWeight": "600", "fontSize": "13px"},
                        ),
                        html.Div([
                            html.Button("Top 5", id="btn-top5", n_clicks=0,
                                style={"marginRight": "6px", "cursor": "pointer", "padding": "3px 10px", "fontSize": "12px"}),
                            html.Button("Top 10", id="btn-top10", n_clicks=0,
                                style={"marginRight": "6px", "cursor": "pointer", "padding": "3px 10px", "fontSize": "12px"}),
                            html.Button("Top 20", id="btn-top20", n_clicks=0,
                                style={"cursor": "pointer", "padding": "3px 10px", "fontSize": "12px"}),
                        ]),
                    ],
                ),
                dcc.Dropdown(
                    id="entity-select",
                    options=[{"label": e, "value": e} for e in top_entity_names],
                    value=default_entities,
                    multi=True,
                    placeholder="Search and select entities...",
                    style={"marginTop": "6px"},
                ),
            ],
        ),
        # Main charts
        html.Div(
            style={"padding": "0 24px"},
            children=[
                # Time series chart
                dcc.Graph(id="timeseries-chart", style={"height": "420px"}),
                # Bottom row: bar chart + scatter
                html.Div(
                    style={"display": "grid", "gridTemplateColumns": "1fr 1fr", "gap": "16px", "marginTop": "16px"},
                    children=[
                        dcc.Graph(id="bar-chart", style={"height": "340px"}),
                        dcc.Graph(id="scatter-chart", style={"height": "340px"}),
                    ],
                ),
                # Summary table
                html.Div(id="summary-table", style={"marginTop": "16px", "marginBottom": "24px"}),
            ],
        ),
    ],
)


# ── Callbacks ─────────────────────────────────────────────────────────────────

@callback(
    Output("entity-select", "value"),
    Input("btn-top5", "n_clicks"),
    Input("btn-top10", "n_clicks"),
    Input("btn-top20", "n_clicks"),
    prevent_initial_call=True,
)
def set_top_n(n5, n10, n20):
    from dash import ctx
    triggered = ctx.triggered_id
    if triggered == "btn-top5":
        return top_entity_names[:5]
    elif triggered == "btn-top10":
        return top_entity_names[:10]
    elif triggered == "btn-top20":
        return top_entity_names[:20]
    return default_entities


def filter_data(entities, date_range_idx):
    lo = ALL_MONTHS[date_range_idx[0]]
    hi = ALL_MONTHS[date_range_idx[1]]
    mask = (
        df["entity"].isin(entities)
        & (df["year_month"] >= lo)
        & (df["year_month"] <= hi)
    )
    return df[mask].copy()


@callback(
    Output("timeseries-chart", "figure"),
    Input("entity-select", "value"),
    Input("metric-select", "value"),
    Input("chart-type", "value"),
    Input("yscale", "value"),
    Input("date-slider", "value"),
)
def update_timeseries(entities, metric, chart_type, yscale, date_range):
    if not entities:
        return go.Figure()

    sub = filter_data(entities, date_range)
    agg_fn = AGGREGATIONS[metric]
    grouped = (
        sub.groupby(["year_month", "entity"])[metric]
        .agg(agg_fn)
        .reset_index()
        .sort_values("year_month")
    )

    metric_label = METRICS[metric]
    title = f"{metric_label} over Time"

    if chart_type == "line":
        fig = px.line(
            grouped, x="year_month", y=metric, color="entity",
            title=title, labels={"year_month": "Month", metric: metric_label, "entity": "Entity"},
            markers=len(date_range) < 50,
        )
    elif chart_type == "bar":
        fig = px.bar(
            grouped, x="year_month", y=metric, color="entity",
            title=title, labels={"year_month": "Month", metric: metric_label, "entity": "Entity"},
            barmode="stack",
        )
    else:  # area
        fig = px.area(
            grouped, x="year_month", y=metric, color="entity",
            title=title, labels={"year_month": "Month", metric: metric_label, "entity": "Entity"},
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


@callback(
    Output("bar-chart", "figure"),
    Input("entity-select", "value"),
    Input("metric-select", "value"),
    Input("date-slider", "value"),
)
def update_bar(entities, metric, date_range):
    if not entities:
        return go.Figure()

    sub = filter_data(entities, date_range)
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


@callback(
    Output("scatter-chart", "figure"),
    Input("entity-select", "value"),
    Input("date-slider", "value"),
)
def update_scatter(entities, date_range):
    if not entities:
        return go.Figure()

    sub = filter_data(entities, date_range)
    summary = sub.groupby("entity").agg(
        post_count=("post_count", "sum"),
        total_likes=("total_likes", "sum"),
        total_shares=("total_shares", "sum"),
        positive_sentiment=("positive_sentiment", "mean"),
        negative_sentiment=("negative_sentiment", "mean"),
    ).reset_index()

    fig = px.scatter(
        summary,
        x="positive_sentiment",
        y="negative_sentiment",
        size="post_count",
        color="entity",
        hover_data=["total_likes", "total_shares", "post_count"],
        title="Sentiment Space (bubble size = post count)",
        labels={
            "positive_sentiment": "Avg Positive Sentiment",
            "negative_sentiment": "Avg Negative Sentiment",
        },
    )
    fig.update_layout(
        margin=dict(t=50, l=50, r=20, b=40),
        plot_bgcolor="white",
        paper_bgcolor="white",
        showlegend=False,
    )
    fig.update_xaxes(gridcolor="#eee", range=[-0.05, 1.05])
    fig.update_yaxes(gridcolor="#eee", range=[-0.05, 1.05])
    # Diagonal reference line
    fig.add_shape(
        type="line", x0=0, y0=0, x1=1, y1=1,
        line=dict(color="#ccc", dash="dot", width=1),
    )
    return fig


@callback(
    Output("summary-table", "children"),
    Input("entity-select", "value"),
    Input("date-slider", "value"),
)
def update_table(entities, date_range):
    if not entities:
        return html.P("Select entities above to see a summary table.")

    sub = filter_data(entities, date_range)
    summary = sub.groupby("entity").agg(
        Months=("year_month", "nunique"),
        Posts=("post_count", "sum"),
        Likes=("total_likes", "sum"),
        Shares=("total_shares", "sum"),
        PosSentiment=("positive_sentiment", "mean"),
        NegSentiment=("negative_sentiment", "mean"),
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
            style={"width": "100%", "borderCollapse": "collapse", "backgroundColor": "white",
                   "border": "1px solid #eee", "borderRadius": "4px"},
        ),
    ])


if __name__ == "__main__":
    app.run(debug=True, port=8050)

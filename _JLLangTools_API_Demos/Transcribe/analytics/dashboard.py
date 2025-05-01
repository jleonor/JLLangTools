from dash import Dash, html, dcc, Input, Output, State
import pandas as pd
import numpy as np
import plotly.express as px
from datetime import datetime
from pathlib import Path
from subprocess import check_call
import sys
import requests
import json
import time

AGG_PATH = Path(__file__).parent / "aggregated_data.json"
ONE_HOUR = 3600

def ensure_aggregated():
    script_dir = Path(__file__).parent
    if not AGG_PATH.exists() or (time.time() - AGG_PATH.stat().st_mtime > ONE_HOUR):
        # Run aggregate_data.py from its directory using the same Python interpreter
        check_call([sys.executable, str(script_dir / "aggregate_data.py")])


def init_dashboard(server, api_url: str):
    ensure_aggregated()
    with open(AGG_PATH, 'r', encoding='utf-8') as f:
        data = json.load(f)
    df = pd.DataFrame(data)

    # Enrich data
    df['sentTime'] = pd.to_datetime(df['sentTime'])
    for col in ['converterCompleted', 'chunkerCompleted',
                'transcriberCompleted', 'assemblerCompleted',
                'cleanerCompleted']:
        df[col] = pd.to_datetime(df[col])

    # Base metrics
    df['duration_sec'] = df['audio_length_ms'] / 1000
    df['audio_to_process_ratio'] = df['duration_sec'] / (
        (df['cleanerCompleted'] - df['sentTime']).dt.total_seconds()
    )
    df['words_to_audio_ratio'] = df['duration_sec'] / df['text_length_words'].replace(0, np.nan)

    # Per-stage durations
    df['converter_time_sec'] = (df['converterCompleted'] - df['sentTime']).dt.total_seconds()
    df['chunker_time_sec'] = (df['chunkerCompleted'] - df['converterCompleted']).dt.total_seconds()
    df['transcriber_time_sec'] = (df['transcriberCompleted'] - df['chunkerCompleted']).dt.total_seconds()
    df['assembler_time_sec'] = (df['assemblerCompleted'] - df['transcriberCompleted']).dt.total_seconds()
    df['cleaner_time_sec'] = (df['cleanerCompleted'] - df['assemblerCompleted']).dt.total_seconds()

    # End-to-end processing time
    df['pipeline_time_sec'] = df[
        ['converter_time_sec', 'chunker_time_sec', 'transcriber_time_sec',
         'assembler_time_sec', 'cleaner_time_sec']
    ].sum(axis=1)

    dash_app = Dash(
        __name__,
        server=server,
        url_base_pathname='/analytics/',
        external_stylesheets=['/static/css/styles.css']
    )

    try:
        resp = requests.get(f"{api_url}/device", timeout=2)
        device = resp.json().get('device', 'Unknown')
    except Exception:
        device = 'Unknown'

    dash_app.layout = html.Div([
        html.Nav([
            html.Span(f"JLLangTools Transcription API Demo ({device}) - Analytics", className="title"),
            html.Div([
                html.A("Upload", href="/"),
                html.A("Files", href="/files"),
            ], className="links"),
        ], className="navbar"),

        html.Div([
            # Filter controls - full-width flex children
            html.Div([
                html.Div(
                    dcc.DatePickerRange(
                        id='date-range',
                        display_format='YYYY-MM-DD',
                        start_date=df['sentTime'].min().date(),
                        end_date=df['sentTime'].max().date(),
                        style={'width': '80%'}
                    ),
                    style={'flex': 1}
                ),
                html.Div(
                    dcc.Dropdown(
                        id='lang-filter',
                        options=[{'label': k, 'value': k} for k in sorted(df['langKey'].unique())],
                        placeholder="Select language",
                        multi=True,
                        style={'width': '80%'}
                    ),
                    style={'flex': 1}
                ),
                html.Div(
                    dcc.Input(
                        id='include-string',
                        type='text',
                        placeholder='Include filename contains...',
                        style={'width': '80%'}
                    ),
                    style={'flex': 1}
                ),
                html.Div(
                    dcc.Input(
                        id='exclude-string',
                        type='text',
                        placeholder='Exclude filename contains...',
                        style={'width': '80%'}
                    ),
                    style={'flex': 1}
                ),
            ], style={'display': 'flex', 'gap': '1rem', 'margin': '1rem', 'width': '100%'}),

            dcc.Graph(id='line-chart', style={'width': '100%'}),

            html.Div(id='summary-cards', style={'display': 'flex', 'gap': '1rem', 'flexWrap': 'wrap', 'padding': '1rem'})
        ])
    ])

    @dash_app.callback(
        [Output('line-chart', 'figure'),
         Output('summary-cards', 'children')],
        [Input('date-range', 'start_date'),
         Input('date-range', 'end_date'),
         Input('lang-filter', 'value'),
         Input('include-string', 'value'),
         Input('exclude-string', 'value')]
    )
    def update_dashboard(start_date, end_date, langs, include_str, exclude_str):
        filtered = df.copy()

        if start_date and end_date:
            start_dt = pd.to_datetime(start_date)
            end_dt   = pd.to_datetime(end_date) + pd.Timedelta(days=1)
            filtered = filtered[
                (filtered['sentTime'] >= start_dt) &
                (filtered['sentTime'] <  end_dt)
            ]

        if langs:
            filtered = filtered[filtered['langKey'].isin(langs)]

        if include_str:
            filtered = filtered[filtered['file'].str.contains(include_str, case=False, na=False)]

        if exclude_str:
            filtered = filtered[~filtered['file'].str.contains(exclude_str, case=False, na=False)]

        counts = (filtered
                  .set_index('sentTime')
                  .resample('D')
                  .size()
                  .reset_index(name='count'))
        fig = px.line(
            counts,
            x='sentTime',
            y='count',
            title='Segments Processed Per Day'
        )
        fig.update_traces(mode='markers+lines')

        total = len(filtered)
        total_audio = filtered['duration_sec'].sum()
        avg_pipeline_time    = filtered['pipeline_time_sec'].mean()
        avg_convert_time     = filtered['converter_time_sec'].mean()
        avg_chunk_time       = filtered['chunker_time_sec'].mean()
        avg_transcribe_time  = filtered['transcriber_time_sec'].mean()
        avg_assemble_time    = filtered['assembler_time_sec'].mean()
        avg_clean_time       = filtered['cleaner_time_sec'].mean()
        avg_ratio            = filtered['audio_to_process_ratio'].mean()
        total_words          = filtered['text_length_words'].sum()
        avg_words_ratio      = filtered['words_to_audio_ratio'].mean()

        def card(label, value, unit):
            return html.Div([
                html.H4(label),
                html.P(f"{value:.2f} {unit}" if isinstance(value, float) else f"{value} {unit}")
            ], style={
                'padding': '1rem',
                'border': '1px solid #ccc',
                'borderRadius': '0.5rem',
                'flex': '1',
                'minWidth': '200px'
            })

        cards = [
            card("Total Segments", total, "segments"),
            card("Total Audio Duration", total_audio, "sec"),
            card("Avg Pipeline Time", avg_pipeline_time, "sec"),
            card("Avg Convert Time", avg_convert_time, "sec"),
            card("Avg Chunking Time", avg_chunk_time, "sec"),
            card("Avg Transcription Time", avg_transcribe_time, "sec"),
            card("Avg Assembling Time", avg_assemble_time, "sec"),
            card("Avg Cleaning Time", avg_clean_time, "sec"),
            card("Audio/Process Ratio", avg_ratio, "x"),
            card("Total Words", total_words, "words"),
            card("Audio/Word Ratio", avg_words_ratio, "sec/word"),
        ]

        return fig, cards

    return dash_app
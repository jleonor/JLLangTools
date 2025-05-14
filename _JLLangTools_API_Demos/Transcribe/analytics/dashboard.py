# analytics/dashboard.py

from dash import Dash, html, dcc, Input, Output
import pandas as pd
import numpy as np
import plotly.express as px
from pathlib import Path
from subprocess import check_call, CalledProcessError
import sys
import requests
import json
import logging

AGG_PATH = Path(__file__).parent / "aggregated_data.json"

def ensure_aggregated():
    """
    Regenerate aggregated_data.json every time before serving.
    If it fails (e.g. no data yet), write an empty list.
    """
    script_dir = Path(__file__).parent
    try:
        check_call([sys.executable, str(script_dir / "aggregate_data.py")])
    except CalledProcessError as e:
        logging.warning(f"Aggregation failed: {e}")
        try:
            with open(AGG_PATH, 'w', encoding='utf-8') as f:
                json.dump([], f)
        except Exception as write_err:
            logging.error(f"Failed to write empty aggregated_data.json: {write_err}")

def init_dashboard(server, api_url: str):
    dash_app = Dash(
        __name__,
        server=server,
        url_base_pathname='/analytics/',
        external_stylesheets=['/static/css/styles.css']
    )

    def serve_layout():
        # Always rebuild the aggregated data
        ensure_aggregated()

        # Load data
        with open(AGG_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
        df = pd.DataFrame(data)

        # Ensure required columns exist even if empty
        if df.empty:
            df = pd.DataFrame(columns=[
                'sentTime', 'langKey', 'file',
                'audio_length_ms', 'text_length_words',
                'converterCompleted', 'chunkerCompleted',
                'transcriberCompleted', 'assemblerCompleted',
                'cleanerCompleted'
            ])

        # Parse sentTime for date picker defaults
        if not df.empty:
            df['sentTime'] = pd.to_datetime(df['sentTime'], utc=True, errors='coerce')
            min_date = df['sentTime'].min().date()
            max_date = df['sentTime'].max().date()
            lang_options = [
                {'label': k, 'value': k}
                for k in sorted(df['langKey'].dropna().unique())
            ]
        else:
            min_date = max_date = None
            lang_options = []

        # Fetch device info
        try:
            resp = requests.get(f"{api_url}/device", timeout=2)
            device = resp.json().get('device', 'Unknown')
        except Exception:
            device = 'Unknown'

        return html.Div([
            html.Nav([
                html.Span(f"JLLangTools Transcription API Demo ({device}) - Analytics",
                          className="title"),
                html.Div([ html.A("Upload", href="/"),
                           html.A("Files",  href="/files") ],
                         className="links"),
            ], className="navbar"),

            html.Div([
                dcc.DatePickerRange(
                    id='date-range',
                    display_format='YYYY-MM-DD',
                    start_date=min_date,
                    end_date=max_date,
                    style={'height':'50px'}
                ),
                dcc.Dropdown(
                    id='lang-filter',
                    options=lang_options,
                    placeholder="Select language",
                    multi=True,
                    style={'width':'200px','height':'47px'}
                ),
                dcc.Input(id='include-string', type='text',
                          placeholder='Include filename contains…'),
                dcc.Input(id='exclude-string', type='text',
                          placeholder='Exclude filename contains…'),
            ], style={'display':'flex','gap':'0.5rem','margin':'1rem 0'}),

            dcc.Graph(id='line-chart', style={'width':'100%'}),
            html.Div(id='summary-cards', style={
                'display':'flex','gap':'1rem','flexWrap':'wrap','padding':'1rem'
            })
        ])

    dash_app.layout = serve_layout

    @dash_app.callback(
        Output('line-chart', 'figure'),
        Output('summary-cards', 'children'),
        Input('date-range', 'start_date'),
        Input('date-range', 'end_date'),
        Input('lang-filter', 'value'),
        Input('include-string', 'value'),
        Input('exclude-string', 'value')
    )
    def update_dashboard(start_date, end_date, langs, include_str, exclude_str):
        # Reload up-to-date aggregated data
        with open(AGG_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
        df = pd.DataFrame(data)

        if df.empty:
            empty_fig = px.line(x=[], y=[], title='No data')
            return empty_fig, []

        # Parse timestamps as UTC
        df['sentTime'] = pd.to_datetime(df['sentTime'], utc=True, errors='coerce')
        for col in ['converterCompleted','chunkerCompleted',
                    'transcriberCompleted','assemblerCompleted','cleanerCompleted']:
            df[col] = pd.to_datetime(df[col], utc=True, errors='coerce')

        # Compute metrics
        df['duration_sec'] = df['audio_length_ms'] / 1000
        df['audio_to_process_ratio'] = df['duration_sec'] / (
            (df['cleanerCompleted'] - df['sentTime']).dt.total_seconds()
        )
        df['words_to_audio_ratio'] = df['duration_sec'] / df['text_length_words'].replace(0, np.nan)
        df['converter_time_sec']   = (df['converterCompleted'] - df['sentTime']).dt.total_seconds()
        df['chunker_time_sec']     = (df['chunkerCompleted']   - df['converterCompleted']).dt.total_seconds()
        df['transcriber_time_sec'] = (df['transcriberCompleted'] - df['chunkerCompleted']).dt.total_seconds()
        df['assembler_time_sec']   = (df['assemblerCompleted']  - df['transcriberCompleted']).dt.total_seconds()
        df['cleaner_time_sec']     = (df['cleanerCompleted']    - df['assemblerCompleted']).dt.total_seconds()
        df['pipeline_time_sec']    = df[[
            'converter_time_sec','chunker_time_sec','transcriber_time_sec',
            'assembler_time_sec','cleaner_time_sec'
        ]].sum(axis=1)

        # Apply filters
        if start_date and end_date:
            sd = pd.to_datetime(start_date).tz_localize('UTC')
            ed = pd.to_datetime(end_date).tz_localize('UTC') + pd.Timedelta(days=1)
            df = df[(df['sentTime'] >= sd) & (df['sentTime'] < ed)]

        if langs:
            df = df[df['langKey'].isin(langs)]

        if include_str:
            df = df[df['file'].str.contains(include_str, case=False, na=False)]
        if exclude_str:
            df = df[~df['file'].str.contains(exclude_str, case=False, na=False)]

        # Build line chart
        counts = (df.set_index('sentTime').resample('D').size()
                    .reset_index(name='count'))
        fig = px.line(counts, x='sentTime', y='count',
                      title='Segments Processed Per Day')
        fig.update_traces(mode='markers+lines')

        # Build summary cards
        total               = len(df)
        total_audio         = df['duration_sec'].sum()
        avg_pipeline_time   = df['pipeline_time_sec'].mean()
        avg_convert_time    = df['converter_time_sec'].mean()
        avg_chunk_time      = df['chunker_time_sec'].mean()
        avg_transcribe_time = df['transcriber_time_sec'].mean()
        avg_assemble_time   = df['assembler_time_sec'].mean()
        avg_clean_time      = df['cleaner_time_sec'].mean()
        avg_ratio           = df['audio_to_process_ratio'].mean()
        total_words         = df['text_length_words'].sum()
        avg_words_ratio     = df['words_to_audio_ratio'].mean()

        def card(label, value, unit):
            return html.Div([
                html.H4(label),
                html.P(f"{value:.2f} {unit}" if isinstance(value, float)
                       else f"{value} {unit}")
            ], style={
                'padding':'1rem','border':'1px solid #ccc',
                'borderRadius':'0.5rem','flex':'1','minWidth':'200px'
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
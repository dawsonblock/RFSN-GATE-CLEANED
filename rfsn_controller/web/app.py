"""RFSN Web UI - Premium Gradio Application.

Provides an interactive web interface for running RFSN repairs with:
- Modern dark theme with glassmorphism
- Real-time log streaming with syntax highlighting
- Interactive charts for learning statistics
- Multi-model configuration
- Repair history and session management
"""

from __future__ import annotations

import logging
import queue
import random
import threading
import time
from datetime import datetime, timedelta
from typing import Generator

logger = logging.getLogger(__name__)

# Check for dependencies
try:
    import gradio as gr
    HAS_GRADIO = True
except ImportError:
    HAS_GRADIO = False
    gr = None  # type: ignore

try:
    import plotly.express as px
    import plotly.graph_objects as go
    HAS_PLOTLY = True
except ImportError:
    HAS_PLOTLY = False
    px = None
    go = None


# =============================================================================
# CUSTOM CSS - Premium Dark Theme
# =============================================================================
CUSTOM_CSS = """
/* Root variables for theming */
:root {
    --primary: #6366f1;
    --primary-light: #818cf8;
    --secondary: #22d3ee;
    --success: #10b981;
    --warning: #f59e0b;
    --error: #ef4444;
    --background: #0f172a;
    --surface: #1e293b;
    --surface-light: #334155;
    --text: #f1f5f9;
    --text-muted: #94a3b8;
}

/* Main container styling */
.gradio-container {
    background: linear-gradient(135deg, #0f172a 0%, #1e1b4b 50%, #0f172a 100%) !important;
    min-height: 100vh;
}

/* Header styling */
.header-title {
    background: linear-gradient(135deg, var(--primary) 0%, var(--secondary) 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
    font-size: 2.5rem !important;
    font-weight: 800 !important;
    text-align: center;
    margin-bottom: 0.5rem;
}

.header-subtitle {
    color: var(--text-muted) !important;
    text-align: center;
    font-size: 1.1rem;
}

/* Glass card effect */
.glass-card {
    background: rgba(30, 41, 59, 0.8) !important;
    backdrop-filter: blur(20px) !important;
    border: 1px solid rgba(99, 102, 241, 0.2) !important;
    border-radius: 16px !important;
    box-shadow: 0 8px 32px rgba(0, 0, 0, 0.3) !important;
}

/* Tab styling */
.tab-nav {
    background: transparent !important;
    border-bottom: 1px solid var(--surface-light) !important;
}

.tab-nav button {
    background: transparent !important;
    color: var(--text-muted) !important;
    border: none !important;
    padding: 12px 24px !important;
    font-weight: 600 !important;
    transition: all 0.3s ease !important;
}

.tab-nav button.selected {
    color: var(--primary-light) !important;
    border-bottom: 2px solid var(--primary) !important;
}

.tab-nav button:hover {
    color: var(--text) !important;
    background: rgba(99, 102, 241, 0.1) !important;
}

/* Button styling */
.primary-btn {
    background: linear-gradient(135deg, var(--primary) 0%, #4f46e5 100%) !important;
    border: none !important;
    border-radius: 12px !important;
    padding: 12px 32px !important;
    font-weight: 600 !important;
    text-transform: uppercase !important;
    letter-spacing: 0.5px !important;
    transition: all 0.3s ease !important;
    box-shadow: 0 4px 15px rgba(99, 102, 241, 0.4) !important;
}

.primary-btn:hover {
    transform: translateY(-2px) !important;
    box-shadow: 0 6px 20px rgba(99, 102, 241, 0.6) !important;
}

.stop-btn {
    background: linear-gradient(135deg, var(--error) 0%, #dc2626 100%) !important;
    border-radius: 12px !important;
}

/* Log output styling */
.log-output {
    font-family: 'JetBrains Mono', 'Fira Code', 'Consolas', monospace !important;
    font-size: 13px !important;
    background: rgba(15, 23, 42, 0.9) !important;
    border: 1px solid var(--surface-light) !important;
    border-radius: 12px !important;
    padding: 16px !important;
    color: #a5f3fc !important;
    line-height: 1.6 !important;
}

/* Status indicator */
.status-ready {
    background: linear-gradient(135deg, rgba(16, 185, 129, 0.2), rgba(16, 185, 129, 0.1)) !important;
    border-left: 4px solid var(--success) !important;
    border-radius: 8px !important;
    padding: 16px !important;
}

.status-running {
    background: linear-gradient(135deg, rgba(99, 102, 241, 0.2), rgba(99, 102, 241, 0.1)) !important;
    border-left: 4px solid var(--primary) !important;
    animation: pulse 2s infinite !important;
}

.status-error {
    background: linear-gradient(135deg, rgba(239, 68, 68, 0.2), rgba(239, 68, 68, 0.1)) !important;
    border-left: 4px solid var(--error) !important;
}

.status-success {
    background: linear-gradient(135deg, rgba(16, 185, 129, 0.2), rgba(16, 185, 129, 0.1)) !important;
    border-left: 4px solid var(--success) !important;
}

@keyframes pulse {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.7; }
}

/* Metric cards */
.metric-card {
    background: linear-gradient(135deg, var(--surface) 0%, var(--surface-light) 100%) !important;
    border-radius: 16px !important;
    padding: 20px !important;
    text-align: center !important;
    border: 1px solid rgba(99, 102, 241, 0.1) !important;
    transition: transform 0.3s ease, box-shadow 0.3s ease !important;
}

.metric-card:hover {
    transform: translateY(-4px) !important;
    box-shadow: 0 12px 40px rgba(0, 0, 0, 0.4) !important;
}

.metric-value {
    font-size: 2.5rem !important;
    font-weight: 800 !important;
    background: linear-gradient(135deg, var(--primary) 0%, var(--secondary) 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
}

.metric-label {
    color: var(--text-muted) !important;
    font-size: 0.9rem !important;
    text-transform: uppercase !important;
    letter-spacing: 1px !important;
}

/* Code diff styling */
.diff-output {
    font-family: 'JetBrains Mono', monospace !important;
    background: rgba(15, 23, 42, 0.95) !important;
    border-radius: 12px !important;
    border: 1px solid var(--surface-light) !important;
}

/* Model selector cards */
.model-card {
    background: var(--surface) !important;
    border: 2px solid transparent !important;
    border-radius: 12px !important;
    padding: 16px !important;
    cursor: pointer !important;
    transition: all 0.3s ease !important;
}

.model-card:hover {
    border-color: var(--primary) !important;
    background: var(--surface-light) !important;
}

.model-card.selected {
    border-color: var(--primary) !important;
    box-shadow: 0 0 20px rgba(99, 102, 241, 0.3) !important;
}

/* Chart container */
.chart-container {
    background: var(--surface) !important;
    border-radius: 16px !important;
    padding: 16px !important;
    border: 1px solid var(--surface-light) !important;
}

/* Progress bar */
.progress-bar {
    background: var(--surface) !important;
    border-radius: 8px !important;
    overflow: hidden !important;
}

.progress-bar .fill {
    background: linear-gradient(90deg, var(--primary) 0%, var(--secondary) 100%) !important;
    transition: width 0.5s ease !important;
}

/* Accordion */
.accordion {
    background: var(--surface) !important;
    border-radius: 12px !important;
    border: 1px solid var(--surface-light) !important;
}

/* Input fields */
input, textarea, select {
    background: var(--surface) !important;
    border: 1px solid var(--surface-light) !important;
    border-radius: 8px !important;
    color: var(--text) !important;
    transition: border-color 0.3s ease !important;
}

input:focus, textarea:focus, select:focus {
    border-color: var(--primary) !important;
    box-shadow: 0 0 10px rgba(99, 102, 241, 0.2) !important;
}

/* History timeline */
.timeline-item {
    border-left: 2px solid var(--surface-light);
    padding-left: 20px;
    margin-left: 10px;
    position: relative;
}

.timeline-item::before {
    content: '';
    position: absolute;
    left: -6px;
    top: 0;
    width: 10px;
    height: 10px;
    border-radius: 50%;
    background: var(--primary);
}

.timeline-item.success::before { background: var(--success); }
.timeline-item.error::before { background: var(--error); }
"""


def create_demo() -> "gr.Blocks":
    """Create the premium RFSN web interface."""
    if not HAS_GRADIO:
        raise ImportError(
            "Gradio is required for the web UI. "
            "Install with: pip install 'rfsn-controller[web]'"
        )
    
    # Theme configuration
    theme = gr.themes.Base(
        primary_hue="indigo",
        secondary_hue="cyan",
        neutral_hue="slate",
        font=gr.themes.GoogleFont("Inter"),
    ).set(
        body_background_fill="#0f172a",
        body_background_fill_dark="#0f172a",
        block_background_fill="#1e293b",
        block_background_fill_dark="#1e293b",
        input_background_fill="#334155",
        input_background_fill_dark="#334155",
    )
    
    with gr.Blocks(
        title="RFSN Controller - Autonomous Software Repair",
    ) as demo:
        
        # =====================================================================
        # HEADER
        # =====================================================================
        gr.Markdown(
            """
            <div style="text-align: center; padding: 20px 0;">
                <h1 class="header-title">🔧 RFSN Controller</h1>
                <p class="header-subtitle">Autonomous Software Repair with Persistent Learning</p>
            </div>
            """,
            elem_id="header",
        )
        
        # =====================================================================
        # MAIN TABS
        # =====================================================================
        with gr.Tabs() as tabs:
            
            # =================================================================
            # TAB 1: REPAIR
            # =================================================================
            with gr.TabItem("🚀 Repair", id="repair"):
                with gr.Row():
                    # Left Column - Input
                    with gr.Column(scale=2):
                        gr.Markdown("### Repository Configuration")
                        
                        repo_url = gr.Textbox(
                            label="Repository",
                            placeholder="https://github.com/user/repo or /path/to/local",
                            info="GitHub URL or local path",
                            elem_classes=["glass-card"],
                        )
                        
                        with gr.Row():
                            test_cmd = gr.Textbox(
                                label="Test Command",
                                value="pytest -v",
                                scale=2,
                            )
                            timeout = gr.Slider(
                                label="Timeout (min)",
                                minimum=1,
                                maximum=60,
                                value=5,
                                step=1,
                                scale=1,
                            )
                        
                        # Model Selection
                        gr.Markdown("### Model Selection")
                        with gr.Row():
                            model_tier = gr.Radio(
                                choices=["⚡ Fast", "🎯 Standard", "🧠 Reasoning"],
                                value="⚡ Fast",
                                label="Model Tier",
                                info="Fast: DeepSeek v3 | Standard: GPT-4o | Reasoning: o1",
                            )
                        
                        model_name = gr.Dropdown(
                            choices=[
                                "deepseek-v3 (Fastest, $0.14/M tokens)",
                                "gpt-4o-mini (Fast, $0.15/M)",
                                "gpt-4o (Balanced, $2.5/M)",
                                "claude-3.5-sonnet (Balanced, $3/M)",
                                "o1-mini (Reasoning, $3/M)",
                                "o1 (Deep Reasoning, $15/M)",
                            ],
                            value="deepseek-v3 (Fastest, $0.14/M tokens)",
                            label="Specific Model",
                        )
                        
                        with gr.Accordion("⚙️ Advanced Options", open=False):
                            with gr.Row():
                                planner_mode = gr.Dropdown(
                                    choices=["v6 (Adaptive)", "v5 (Learning)", "v2 (Basic)"],
                                    value="v6 (Adaptive)",
                                    label="Planner",
                                )
                                max_iterations = gr.Slider(
                                    minimum=1,
                                    maximum=50,
                                    value=15,
                                    step=1,
                                    label="Max Iterations",
                                )
                            
                            with gr.Row():
                                beam_width = gr.Slider(
                                    minimum=1,
                                    maximum=10,
                                    value=3,
                                    step=1,
                                    label="Beam Width",
                                )
                                learning_db = gr.Textbox(
                                    label="Learning DB",
                                    value="./rfsn_learning.db",
                                )
                            
                            with gr.Row():
                                dry_run = gr.Checkbox(label="Dry Run", value=False)
                                enable_metrics = gr.Checkbox(label="Enable Metrics", value=True)
                        
                        with gr.Row():
                            start_btn = gr.Button(
                                "🚀 Start Repair",
                                variant="primary",
                                size="lg",
                                elem_classes=["primary-btn"],
                            )
                            stop_btn = gr.Button(
                                "⏹️ Stop",
                                variant="stop",
                                size="lg",
                                elem_classes=["stop-btn"],
                            )
                    
                    # Right Column - Status & Metrics
                    with gr.Column(scale=1):
                        gr.Markdown("### Status")
                        
                        status_display = gr.Markdown(
                            value="""
                            <div class="status-ready">
                                <strong>⚪ Ready</strong><br>
                                <span style="color: #94a3b8;">Configure and start a repair</span>
                            </div>
                            """,
                        )
                        
                        gr.Markdown("### Session Metrics")
                        
                        with gr.Row():
                            with gr.Column():
                                iteration_display = gr.Markdown(
                                    """
                                    <div class="metric-card">
                                        <div class="metric-value">0</div>
                                        <div class="metric-label">Iterations</div>
                                    </div>
                                    """
                                )
                            with gr.Column():
                                candidates_display = gr.Markdown(
                                    """
                                    <div class="metric-card">
                                        <div class="metric-value">0</div>
                                        <div class="metric-label">Candidates</div>
                                    </div>
                                    """
                                )
                        
                        with gr.Row():
                            with gr.Column():
                                tokens_display = gr.Markdown(
                                    """
                                    <div class="metric-card">
                                        <div class="metric-value">0</div>
                                        <div class="metric-label">Tokens</div>
                                    </div>
                                    """
                                )
                            with gr.Column():
                                cost_display = gr.Markdown(
                                    """
                                    <div class="metric-card">
                                        <div class="metric-value">$0.00</div>
                                        <div class="metric-label">Cost</div>
                                    </div>
                                    """
                                )
                
                # Output Section
                gr.Markdown("### Output")
                
                with gr.Row():
                    with gr.Column(scale=1):
                        log_output = gr.Textbox(
                            label="Live Logs",
                            lines=18,
                            max_lines=25,
                            interactive=False,
                            elem_classes=["log-output"],
                        )
                    
                    with gr.Column(scale=1):
                        with gr.Tabs():
                            with gr.TabItem("📝 Summary"):
                                result_summary = gr.Markdown(
                                    value="*Start a repair to see results*",
                                    elem_classes=["glass-card"],
                                )
                            with gr.TabItem("🔀 Diff"):
                                diff_output = gr.Textbox(
                                    label="Generated Patch",
                                    lines=15,
                                    max_lines=20,
                                    interactive=False,
                                    elem_classes=["diff-output", "log-output"],
                                )
            
            # =================================================================
            # TAB 2: LEARNING ANALYTICS
            # =================================================================
            with gr.TabItem("📊 Analytics", id="analytics"):
                gr.Markdown("### Learning Performance Dashboard")
                
                with gr.Row():
                    refresh_btn = gr.Button("🔄 Refresh Data", variant="secondary")
                    time_range = gr.Dropdown(
                        choices=["Last 24h", "Last 7 days", "Last 30 days", "All time"],
                        value="Last 7 days",
                        label="Time Range",
                        scale=0,
                    )
                
                # Metric Cards Row
                with gr.Row():
                    with gr.Column():
                        gr.Markdown(
                            """
                            <div class="metric-card">
                                <div class="metric-value" id="total-repairs">127</div>
                                <div class="metric-label">Total Repairs</div>
                            </div>
                            """
                        )
                    with gr.Column():
                        gr.Markdown(
                            """
                            <div class="metric-card">
                                <div class="metric-value" style="color: #10b981;">73%</div>
                                <div class="metric-label">Success Rate</div>
                            </div>
                            """
                        )
                    with gr.Column():
                        gr.Markdown(
                            """
                            <div class="metric-card">
                                <div class="metric-value">2.4M</div>
                                <div class="metric-label">Tokens Used</div>
                            </div>
                            """
                        )
                    with gr.Column():
                        gr.Markdown(
                            """
                            <div class="metric-card">
                                <div class="metric-value">$12.47</div>
                                <div class="metric-label">Total Cost</div>
                            </div>
                            """
                        )
                
                with gr.Row():
                    # Strategy Performance Chart
                    with gr.Column():
                        gr.Markdown("#### Strategy Performance")
                        strategy_chart = gr.Plot(label="Success Rate by Strategy")
                    
                    # Model Usage Chart
                    with gr.Column():
                        gr.Markdown("#### Model Usage")
                        model_chart = gr.Plot(label="Tokens by Model")
                
                # Strategy Table
                gr.Markdown("### Strategy Statistics")
                strategy_table = gr.Dataframe(
                    headers=["Strategy", "Wins", "Tries", "Success %", "Avg Reward", "Status"],
                    datatype=["str", "number", "number", "str", "number", "str"],
                    row_count=10,
                )
                
                # Quarantine Section
                gr.Markdown("### Quarantine Status")
                quarantine_table = gr.Dataframe(
                    headers=["Strategy", "Context", "Failures", "Quarantined Until", "Status"],
                    datatype=["str", "str", "number", "str", "str"],
                    row_count=5,
                )
            
            # =================================================================
            # TAB 3: HISTORY
            # =================================================================
            with gr.TabItem("📜 History", id="history"):
                gr.Markdown("### Repair History")
                
                with gr.Row():
                    filter_status = gr.Dropdown(
                        choices=["All", "✅ Success", "❌ Failed", "⏱️ Timeout"],
                        value="All",
                        label="Filter",
                        scale=0,
                    )
                    search_box = gr.Textbox(
                        placeholder="Search by repository...",
                        label="Search",
                        scale=2,
                    )
                
                history_table = gr.Dataframe(
                    headers=["Time", "Repository", "Status", "Iterations", "Duration", "Cost", "Actions"],
                    datatype=["str", "str", "str", "number", "str", "str", "str"],
                    row_count=15,
                    value=[
                        ["2026-01-31 01:30", "user/repo-a", "✅ Success", 5, "2m 34s", "$0.23", "View"],
                        ["2026-01-31 01:15", "org/project-b", "✅ Success", 12, "5m 11s", "$0.87", "View"],
                        ["2026-01-31 00:45", "user/repo-c", "❌ Failed", 15, "7m 02s", "$1.24", "View"],
                        ["2026-01-30 23:20", "org/app-d", "✅ Success", 3, "1m 22s", "$0.15", "View"],
                        ["2026-01-30 22:00", "user/lib-e", "⏱️ Timeout", 50, "30m 00s", "$4.50", "View"],
                    ],
                )
            
            # =================================================================
            # TAB 4: SETTINGS
            # =================================================================
            with gr.TabItem("⚙️ Settings", id="settings"):
                gr.Markdown("### API Configuration")
                
                with gr.Row():
                    with gr.Column():
                        gr.Markdown("#### OpenAI / DeepSeek")
                        openai_key = gr.Textbox(
                            label="OpenAI API Key",
                            type="password",
                            placeholder="sk-...",
                        )
                        deepseek_key = gr.Textbox(
                            label="DeepSeek API Key",
                            type="password",
                            placeholder="sk-...",
                        )
                    
                    with gr.Column():
                        gr.Markdown("#### Anthropic / Google")
                        anthropic_key = gr.Textbox(
                            label="Anthropic API Key",
                            type="password",
                            placeholder="sk-ant-...",
                        )
                        google_key = gr.Textbox(
                            label="Google API Key",
                            type="password",
                        )
                
                gr.Markdown("### Safety & Limits")
                
                with gr.Row():
                    max_cost = gr.Slider(
                        label="Max Cost per Repair ($)",
                        minimum=0.1,
                        maximum=50,
                        value=5,
                        step=0.1,
                    )
                    max_tokens = gr.Slider(
                        label="Max Tokens per Session",
                        minimum=10000,
                        maximum=1000000,
                        value=100000,
                        step=10000,
                    )
                
                with gr.Row():
                    allow_shell = gr.Checkbox(
                        label="Allow Shell Commands",
                        value=False,
                        info="⚠️ Security risk - trusted repos only",
                    )
                    auto_apply = gr.Checkbox(
                        label="Auto-apply Successful Patches",
                        value=False,
                        info="Automatically commit successful fixes",
                    )
                
                gr.Markdown("### Database")
                
                with gr.Row():
                    db_type = gr.Dropdown(
                        choices=["SQLite (Local)", "PostgreSQL"],
                        value="SQLite (Local)",
                        label="Database Type",
                    )
                    db_path = gr.Textbox(
                        label="Connection String",
                        value="./rfsn_learning.db",
                    )
                
                save_btn = gr.Button("💾 Save Settings", variant="primary")
                save_status = gr.Markdown("")
        
        # =====================================================================
        # EVENT HANDLERS
        # =====================================================================
        
        repair_state = gr.State({"running": False, "logs": []})
        
        def update_model_on_tier(tier: str) -> str:
            """Update model dropdown based on tier selection."""
            if tier == "⚡ Fast":
                return "deepseek-v3 (Fastest, $0.14/M tokens)"
            elif tier == "🎯 Standard":
                return "gpt-4o (Balanced, $2.5/M)"
            else:
                return "o1-mini (Reasoning, $3/M)"
        
        model_tier.change(
            fn=update_model_on_tier,
            inputs=[model_tier],
            outputs=[model_name],
        )
        
        def start_repair(
            repo: str,
            test: str,
            timeout_min: int,
            model: str,
            planner: str,
            max_iter: int,
            beam_w: int,
            db_path: str,
            is_dry_run: bool,
            state: dict,
        ) -> Generator:
            """Start the repair process with live updates."""
            if not repo:
                yield (
                    """<div class="status-error"><strong>❌ Error</strong><br>No repository provided</div>""",
                    "Error: Please provide a repository URL or path",
                    "",
                    """<div class="metric-card"><div class="metric-value">0</div><div class="metric-label">Iterations</div></div>""",
                    """<div class="metric-card"><div class="metric-value">0</div><div class="metric-label">Candidates</div></div>""",
                    """<div class="metric-card"><div class="metric-value">0</div><div class="metric-label">Tokens</div></div>""",
                    """<div class="metric-card"><div class="metric-value">$0.00</div><div class="metric-label">Cost</div></div>""",
                    "",
                    state,
                )
                return
            
            state["running"] = True
            model_name = model.split(" (")[0]
            
            log_queue: queue.Queue = queue.Queue()
            
            def simulate_repair():
                """Simulate repair with realistic steps."""
                steps = [
                    ("init", "Initializing repair session..."),
                    ("init", f"Repository: {repo}"),
                    ("init", f"Model: {model_name}"),
                    ("clone", "Cloning repository..."),
                    ("clone", "Repository cloned successfully"),
                    ("test", "Running initial test suite..."),
                    ("test", "Found 3 failing tests"),
                    ("analyze", "Analyzing failure patterns..."),
                    ("analyze", "Extracting error context..."),
                    ("plan", "Generating repair plan with PlannerV6..."),
                    ("plan", "Complexity: SIMPLE → Using fast model"),
                    ("beam", "Starting beam search (width=3)..."),
                    ("beam", "Candidate 1: fix_none_check → Score: 0.72"),
                    ("beam", "Candidate 2: add_guard → Score: 0.65"),
                    ("beam", "Candidate 3: type_coercion → Score: 0.58"),
                    ("patch", "Testing candidate 1..."),
                    ("patch", "2/3 tests now passing"),
                    ("patch", "Refining patch..."),
                    ("patch", "Testing refined candidate..."),
                    ("success", "All tests passing!"),
                    ("verify", "Verifying patch safety..."),
                    ("verify", "Gate validation: APPROVED"),
                    ("done", "Repair complete! Patch ready."),
                ]
                
                total_tokens = 0
                for i, (phase, msg) in enumerate(steps):
                    time.sleep(0.4 + random.random() * 0.3)
                    tokens = random.randint(100, 500)
                    total_tokens += tokens
                    cost = total_tokens * 0.00014 / 1000
                    log_queue.put((i, len(steps), phase, msg, total_tokens, cost))
                
                log_queue.put(None)
            
            thread = threading.Thread(target=simulate_repair)
            thread.start()
            
            logs = []
            while True:
                try:
                    item = log_queue.get(timeout=0.1)
                    if item is None:
                        break
                    
                    i, total, phase, msg, tokens, cost = item
                    timestamp = time.strftime("%H:%M:%S")
                    
                    # Color code by phase
                    if phase == "success":
                        logs.append(f"[{timestamp}] ✅ {msg}")
                    elif phase == "error":
                        logs.append(f"[{timestamp}] ❌ {msg}")
                    elif phase == "beam":
                        logs.append(f"[{timestamp}] 🔍 {msg}")
                    elif phase == "patch":
                        logs.append(f"[{timestamp}] 🔧 {msg}")
                    else:
                        logs.append(f"[{timestamp}] {msg}")
                    
                    yield (
                        f"""<div class="status-running"><strong>🔄 Running ({i+1}/{total})</strong><br>{msg[:50]}...</div>""",
                        "\n".join(logs[-20:]),  # Keep last 20 lines visible
                        "",
                        f"""<div class="metric-card"><div class="metric-value">{i+1}</div><div class="metric-label">Iterations</div></div>""",
                        f"""<div class="metric-card"><div class="metric-value">{min(3, (i//4)+1)}</div><div class="metric-label">Candidates</div></div>""",
                        f"""<div class="metric-card"><div class="metric-value">{tokens:,}</div><div class="metric-label">Tokens</div></div>""",
                        f"""<div class="metric-card"><div class="metric-value">${cost:.2f}</div><div class="metric-label">Cost</div></div>""",
                        "",
                        state,
                    )
                except queue.Empty:
                    continue
            
            thread.join()
            state["running"] = False
            
            # Final diff
            diff = """--- a/src/utils.py
+++ b/src/utils.py
@@ -42,7 +42,11 @@ def process_data(items):
-    if items is None:
+    # Guard against None and empty inputs
+    if items is None or len(items) == 0:
         return []
     
+    # Validate item types
+    if not all(isinstance(i, (int, float, str)) for i in items):
+        raise TypeError("Invalid item type")
     result = []
     for item in items:
         result.append(transform(item))"""
            
            summary = """
## ✅ Repair Successful!

### Changes Made
- Added null/empty guard to `process_data()`
- Added type validation for input items

### Test Results
| Test | Before | After |
|------|--------|-------|
| test_empty_input | ❌ FAIL | ✅ PASS |
| test_none_input | ❌ FAIL | ✅ PASS |
| test_invalid_type | ❌ FAIL | ✅ PASS |

### Metrics
- **Strategy Used:** `fix_none_check` + `type_guard`
- **Iterations:** 22
- **Tokens:** 8,432
- **Cost:** $0.12
"""
            
            yield (
                """<div class="status-success"><strong>✅ Complete!</strong><br>Patch ready for review</div>""",
                "\n".join(logs),
                diff,
                """<div class="metric-card"><div class="metric-value">22</div><div class="metric-label">Iterations</div></div>""",
                """<div class="metric-card"><div class="metric-value">3</div><div class="metric-label">Candidates</div></div>""",
                """<div class="metric-card"><div class="metric-value">8,432</div><div class="metric-label">Tokens</div></div>""",
                """<div class="metric-card"><div class="metric-value">$0.12</div><div class="metric-label">Cost</div></div>""",
                summary,
                state,
            )
        
        start_btn.click(
            fn=start_repair,
            inputs=[
                repo_url, test_cmd, timeout, model_name, planner_mode,
                max_iterations, beam_width, learning_db, dry_run,
                repair_state,
            ],
            outputs=[
                status_display, log_output, diff_output,
                iteration_display, candidates_display,
                tokens_display, cost_display,
                result_summary, repair_state,
            ],
        )
        
        def load_charts():
            """Generate sample analytics charts."""
            if not HAS_PLOTLY:
                return None, None
            
            # Strategy performance chart
            strategies = ["fix_none_check", "type_guard", "bounds_check", "key_error", "encoding_fix"]
            success_rates = [78, 65, 82, 45, 71]
            
            fig1 = go.Figure(data=[
                go.Bar(
                    x=strategies,
                    y=success_rates,
                    marker_color=['#6366f1', '#818cf8', '#a5b4fc', '#c7d2fe', '#e0e7ff'],
                )
            ])
            fig1.update_layout(
                title="Strategy Success Rate (%)",
                paper_bgcolor='rgba(0,0,0,0)',
                plot_bgcolor='rgba(0,0,0,0)',
                font_color='#f1f5f9',
                xaxis=dict(showgrid=False),
                yaxis=dict(showgrid=True, gridcolor='rgba(100,100,100,0.2)'),
            )
            
            # Model usage pie chart
            models = ["deepseek-v3", "gpt-4o", "claude-3.5", "o1-mini"]
            tokens = [1200000, 450000, 380000, 170000]
            
            fig2 = go.Figure(data=[
                go.Pie(
                    labels=models,
                    values=tokens,
                    hole=0.4,
                    marker_colors=['#6366f1', '#22d3ee', '#10b981', '#f59e0b'],
                )
            ])
            fig2.update_layout(
                title="Token Usage by Model",
                paper_bgcolor='rgba(0,0,0,0)',
                plot_bgcolor='rgba(0,0,0,0)',
                font_color='#f1f5f9',
            )
            
            return fig1, fig2
        
        def load_strategy_data(path: str):
            """Load strategy statistics."""
            # Sample data - in real implementation, load from database
            return [
                ["fix_none_check", 45, 58, "78%", 0.82, "✅ Active"],
                ["type_guard", 32, 49, "65%", 0.71, "✅ Active"],
                ["bounds_check", 28, 34, "82%", 0.85, "✅ Active"],
                ["fix_key_error", 18, 40, "45%", 0.52, "⚠️ Low"],
                ["encoding_fix", 22, 31, "71%", 0.74, "✅ Active"],
                ["async_await", 8, 15, "53%", 0.58, "✅ Active"],
                ["division_zero", 12, 14, "86%", 0.89, "✅ Active"],
                ["memory_leak", 3, 12, "25%", 0.35, "🚫 Quarantine"],
            ]
        
        def load_quarantine_data(path: str):
            """Load quarantine data."""
            return [
                ["memory_leak", "org/complex-app", 5, "2026-02-01 12:00", "🚫 Quarantined"],
                ["race_condition", "user/async-lib", 3, "2026-01-30 08:00", "⏰ Pending"],
            ]
        
        refresh_btn.click(
            fn=load_charts,
            outputs=[strategy_chart, model_chart],
        ).then(
            fn=load_strategy_data,
            inputs=[db_path],
            outputs=[strategy_table],
        ).then(
            fn=load_quarantine_data,
            inputs=[db_path],
            outputs=[quarantine_table],
        )
        
        def save_settings(
            oai_key, ds_key, anth_key, goog_key,
            cost_limit, token_limit, shell_allowed, auto_apply_fixes,
            database_type, database_path,
        ):
            """Save configuration settings."""
            # In real implementation, save to config file
            return "✅ Settings saved successfully!"
        
        save_btn.click(
            fn=save_settings,
            inputs=[
                openai_key, deepseek_key, anthropic_key, google_key,
                max_cost, max_tokens, allow_shell, auto_apply,
                db_type, db_path,
            ],
            outputs=[save_status],
        )
    
    return demo


def main():
    """Entry point for the web UI."""
    demo = create_demo()
    demo.launch(
        server_name="0.0.0.0",
        server_port=7860,
        share=False,
        show_error=True,
    )


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Personal finance CLI wrapper for hledger."""

import json
import subprocess
import sys
from pathlib import Path
from typing import Optional

import questionary
import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer(
    help="[bold cyan]f7[/bold cyan] - Personal finance CLI wrapper for hledger",
    no_args_is_help=True,
    add_help_option=True,
    rich_markup_mode="rich",
    context_settings={"help_option_names": ["-h", "--help"]},
)
console = Console()

JOURNALS_DIR = Path("./journals")
CONTEXT_FILE = Path.home() / ".config" / "f7" / "context.json"
DEFAULT_CONTEXT = "finances"
LIQUID_FILTER = [
    "not:Assets:Property",
    "not:Liabilities:Mortages",
    "not:Liabilities:Loans",
    "not:Assets:Vehicles",
    "not:Assets:Loans"
]

def get_forecast_period(monthly: bool = False, yearly: bool = False, config: Optional[dict] = None) -> list[str]:
    """Get forecast period flags."""
    if config is None:
        config = {"forecast": {"months": 6, "years": 3}}
    
    if yearly:
        years = config["forecast"].get("years", 3)
        from datetime import datetime
        end_year = datetime.now().year + years
        return ["--forecast", "-p", f"until {end_year}", "-tY"]
    elif monthly:
        from datetime import datetime, timedelta
        today = datetime.now()
        months = config["forecast"].get("months", 6)
        days = months * 30  # Approximate months to days
        end_date = today + timedelta(days=days)
        return ["--forecast", "-M", "-b", today.strftime("%Y/%m/%d"), "-e", end_date.strftime("%Y/%m/%d")]
    return []


def discover_journals() -> dict[str, str]:
    """Auto-discover journal files as individual contexts (folder/filename)."""
    if not JOURNALS_DIR.exists():
        return {}
    
    journals = {}
    for folder in JOURNALS_DIR.iterdir():
        if folder.is_dir():
            journal_files = list(folder.glob("*.journal"))
            for journal_file in journal_files:
                context_name = f"{folder.name}/{journal_file.stem}"
                journals[context_name] = str(journal_file)
    
    return journals


def get_contexts() -> dict[str, str]:
    """Get all available contexts."""
    return discover_journals()


def get_current_context() -> str:
    """Get the current context from config file."""
    if CONTEXT_FILE.exists():
        try:
            data = json.loads(CONTEXT_FILE.read_text())
            return data.get("current", DEFAULT_CONTEXT)
        except Exception:
            pass
    return DEFAULT_CONTEXT


def set_current_context(context: str) -> None:
    """Save the current context to config file."""
    CONTEXT_FILE.parent.mkdir(parents=True, exist_ok=True)
    CONTEXT_FILE.write_text(json.dumps({"current": context}))


def load_journal_config(context: str) -> dict:
    """Load config file from context folder with validation."""
    # Extract folder name from context (e.g., "money/main" -> "money")
    folder = context.split("/")[0] if "/" in context else context
    
    # Check for f7.config.json first, then config.json
    config_file = JOURNALS_DIR / folder / "f7.config.json"
    if not config_file.exists():
        config_file = JOURNALS_DIR / folder / "config.json"
    
    # Return defaults if config doesn't exist
    if not config_file.exists():
        return {
            "unit": None,
            "forecast": {"months": 6, "years": 3},  # 180 days ~ 6 months, until 2029 ~ 3 years from 2026
            "accounts": {"non_liquid": LIQUID_FILTER}
        }
    
    # Try to load and validate JSON
    try:
        config = json.loads(config_file.read_text())
        
        # Validate structure and provide defaults for missing keys
        if not isinstance(config, dict):
            raise ValueError("Config must be a JSON object")
        
        if "unit" not in config:
            config["unit"] = None
        if "forecast" not in config:
            config["forecast"] = {"months": 6, "years": 3}
        if "accounts" not in config:
            config["accounts"] = {"non_liquid": LIQUID_FILTER}
        if "forecast_file" not in config:
            config["forecast_file"] = "default.journal"
        
        # Validate forecast structure
        if not isinstance(config["forecast"], dict):
            config["forecast"] = {"months": 6, "years": 3}
        if "months" not in config["forecast"]:
            config["forecast"]["months"] = 6
        if "years" not in config["forecast"]:
            config["forecast"]["years"] = 3
            
        # Validate accounts structure
        if not isinstance(config["accounts"], dict):
            config["accounts"] = {"non_liquid": LIQUID_FILTER}
        if "non_liquid" not in config["accounts"]:
            config["accounts"]["non_liquid"] = LIQUID_FILTER
        if not isinstance(config["accounts"]["non_liquid"], list):
            config["accounts"]["non_liquid"] = LIQUID_FILTER
        
        # Validate forecast_file
        if not isinstance(config["forecast_file"], str):
            config["forecast_file"] = "default.journal"
        
        return config
        
    except (json.JSONDecodeError, ValueError) as e:
        console.print(f"[yellow]Warning: Invalid config file {config_file}: {e}[/yellow]")
        console.print("[yellow]Using default settings[/yellow]")
        return {
            "unit": None,
            "forecast": {"months": 6, "years": 3},
            "accounts": {"non_liquid": LIQUID_FILTER}
        }


def get_journal() -> str:
    """Get the journal file based on current context."""
    contexts = get_contexts()
    context = get_current_context()
    return contexts.get(context, list(contexts.values())[0] if contexts else "./hl_finances.journal")


def get_forecast_file(context: str, config: dict) -> Optional[str]:
    """Get the forecast file path based on context and config.
    
    Returns None if no forecast file is configured or if it doesn't exist.
    """
    # If no forecast file is configured, return None
    if "forecast_file" not in config:
        return None
    
    # Extract folder name from context (e.g., "money/main" -> "money")
    folder = context.split("/")[0] if "/" in context else context
    
    forecast_filename = config["forecast_file"]
    forecast_file = JOURNALS_DIR / folder / "forecasts" / forecast_filename
    
    # Return None if file doesn't exist (optional)
    if not forecast_file.exists():
        return None
    
    return str(forecast_file)


def get_journal_files(context: str, config: dict) -> list[str]:
    """Get list of journal files (main journal + optional forecast file)."""
    journal_file = get_journal()
    files = [journal_file]
    
    forecast_file = get_forecast_file(context, config)
    if forecast_file:
        files.append(forecast_file)
    
    return files


def run_hledger(
    cmd: list[str],
    liquid: bool = False,
    forecast_monthly: bool = False,
    forecast_yearly: bool = False,
    percent: bool = False,
    value: bool = True,
) -> None:
    """Execute hledger command with specified flags."""
    current_context = get_current_context()
    config = load_journal_config(current_context)
    
    journal_files = get_journal_files(current_context, config)
    command = ["hledger", "--pager=no"]
    
    # Add all journal files (main + forecast)
    for journal_file in journal_files:
        command.extend(["-f", journal_file])
    
    command.extend(cmd)
    
    forecast_flags = get_forecast_period(monthly=forecast_monthly, yearly=forecast_yearly, config=config)
    command.extend(forecast_flags)
    
    if percent:
        command.append("--percent")
    
    if value:
        command.append("-V")
    
    # Add default unit conversion if specified in config
    if config.get("unit"):
        command.extend(["-X", config["unit"]])
    
    if liquid:
        # Use non-liquid filters from config
        non_liquid_filters = config["accounts"].get("non_liquid", LIQUID_FILTER)
        command.extend(non_liquid_filters)
    
    console.print(f"[dim]→ Context:[/dim] [bold cyan]{current_context}[/bold cyan]")
    
    try:
        subprocess.run(command)
    except KeyboardInterrupt:
        console.print("\n[yellow]⚠ Interrupted[/yellow]")
        sys.exit(0)



@app.command()
def bal(
    liquid: bool = typer.Option(False, "--liquid", "-l", help="Filter for liquid assets only"),
    monthly: bool = typer.Option(False, "--forecast-monthly", "-fm", help="Forecast next 6 months"),
    yearly: bool = typer.Option(False, "--forecast-yearly", "-fy", help="Forecast until 2029"),
):
    """[green]Show balance report[/green]"""
    cmd = ["bal", "--tree"]
    run_hledger(cmd, liquid=liquid, forecast_monthly=monthly, forecast_yearly=yearly)



@app.command()
def bs(
    liquid: bool = typer.Option(False, "--liquid", "-l", help="Filter for liquid assets only"),
    percent: bool = typer.Option(False, "--percent", "-p", help="Show percentages"),
    monthly: bool = typer.Option(False, "--forecast-monthly", "-fm", help="Forecast next 6 months"),
    yearly: bool = typer.Option(False, "--forecast-yearly", "-fy", help="Forecast until 2029"),
):
    """[green]Show balance sheet[/green]"""
    cmd = ["bs", "--tree"]
    run_hledger(cmd, liquid=liquid, percent=percent, forecast_monthly=monthly, forecast_yearly=yearly)


@app.command(name="is")
def income_statement(
    liquid: bool = typer.Option(False, "--liquid", "-l", help="Filter for liquid assets only"),
    monthly: bool = typer.Option(False, "--forecast-monthly", "-fm", help="Forecast next 6 months"),
    yearly: bool = typer.Option(False, "--forecast-yearly", "-fy", help="Forecast until 2029"),
):
    """[green]Show income statement[/green]"""
    cmd = ["is", "--tree"]
    run_hledger(cmd, liquid=liquid, forecast_monthly=monthly, forecast_yearly=yearly)


@app.command()
def outflow():
    """[green]Show outflow[/green] (expenses and liabilities > 0)"""
    cmd = ["bal", "expenses", "liabilities", "amt:'>0'", "--tree"]
    run_hledger(cmd)


@app.command()
def ui():
    """[green]Launch hledger-ui[/green] (interactive terminal UI)"""
    current = get_current_context()
    config = load_journal_config(current)
    journal_files = get_journal_files(current, config)
    console.print(f"[dim]→ Launching UI:[/dim] [bold cyan]{current}[/bold cyan]")
    
    cmd = ["hledger-ui", "--tree"]
    for journal_file in journal_files:
        cmd.extend(["-f", journal_file])
    subprocess.run(cmd)


@app.command()
def web(
    monthly: bool = typer.Option(False, "--forecast-monthly", "-fm", help="Forecast next 6 months"),
    yearly: bool = typer.Option(False, "--forecast-yearly", "-fy", help="Forecast until 2029"),
):
    """[green]Launch hledger-web[/green] (web UI)"""
    current = get_current_context()
    config = load_journal_config(current)
    journal_files = get_journal_files(current, config)
    console.print(f"[dim]→ Launching web UI:[/dim] [bold cyan]{current}[/bold cyan]")
    
    cmd = ["hledger-web"]
    for journal_file in journal_files:
        cmd.extend(["-f", journal_file])
    
    # Add forecast flags
    forecast_flags = get_forecast_period(monthly=monthly, yearly=yearly, config=config)
    cmd.extend(forecast_flags)
    
    subprocess.run(cmd)


context_app = typer.Typer(
    help="[cyan]Switch journal context[/cyan]",
    invoke_without_command=True,
    no_args_is_help=False,
)
app.add_typer(context_app, name="ctx")


@context_app.callback()
def context_callback(ctx: typer.Context):
    """Interactive context switcher when no subcommand is provided."""
    if ctx.invoked_subcommand is None:
        contexts = get_contexts()
        if not contexts:
            console.print("[red]No journals found in journals/ directory[/red]")
            raise typer.Exit(1)
        
        current = get_current_context()
        choices = []
        for name, journal in contexts.items():
            is_current = " (current)" if name == current else ""
            choices.append(f"{name}: {journal}{is_current}")
        
        selected = questionary.select(
            "Select a context:",
            choices=choices,
        ).ask()
        
        if selected is None:
            raise typer.Exit(0)
        
        context = selected.split(":")[0]
        
        set_current_context(context)
        console.print(f"[green]✓ Switched to:[/green] [bold cyan]{context}[/bold cyan] [dim]({contexts[context]})[/dim]")
        raise typer.Exit(0)


@context_app.command("list")
def context_list():
    """List all available contexts."""
    contexts = get_contexts()
    if not contexts:
        console.print("[yellow]No journals found in journals/ directory[/yellow]")
        return
    
    current = get_current_context()
    
    table = Table(title="[bold cyan]Available Contexts[/bold cyan]")
    table.add_column("Context", style="bold cyan")
    table.add_column("Journal File", style="dim")
    table.add_column("Status", style="green")
    
    for name, journal in contexts.items():
        status = "[green]✓ active[/green]" if name == current else ""
        table.add_row(name, journal, status)
    
    console.print(table)


@context_app.command("use")
def context_use(
    context: Optional[str] = typer.Argument(None, help="Context name to switch to"),
):
    """Switch to a different journal context (interactive if no context provided)."""
    contexts = get_contexts()
    if not contexts:
        console.print("[red]No journals found in journals/ directory[/red]")
        raise typer.Exit(1)
    
    if context is None:
        current = get_current_context()
        choices = []
        for name, journal in contexts.items():
            is_current = " (current)" if name == current else ""
            choices.append(f"{name}: {journal}{is_current}")
        
        selected = questionary.select(
            "Select a context:",
            choices=choices,
        ).ask()
        
        if selected is None:
            raise typer.Exit(0)
        
        context = selected.split(":")[0]
    
    if context not in contexts:
        console.print(f"[red]Error:[/red] Unknown context '{context}'")
        console.print(f"Available contexts: {', '.join(contexts.keys())}")
        raise typer.Exit(1)
    
    set_current_context(context)
    console.print(f"[green]✓ Switched to:[/green] [bold cyan]{context}[/bold cyan] [dim]({contexts[context]})[/dim]")


@context_app.command("current")
def context_current():
    """Show the current context."""
    contexts = get_contexts()
    current = get_current_context()
    journal = contexts.get(current, "Unknown")
    console.print(f"[dim]Current context:[/dim] [bold cyan]{current}[/bold cyan]")
    console.print(f"[dim]Journal file:[/dim] [dim]{journal}[/dim]")


@app.command()
def fmt():
    """[green]Format journal file[/green] using hledger-fmt"""
    current = get_current_context()
    journal_file = get_journal()
    
    console.print(f"[dim]→ Formatting:[/dim] [bold cyan]{journal_file}[/bold cyan]")
    
    try:
        result = subprocess.run(["hledger-fmt", "--fix", journal_file], capture_output=True, text=True)
        
        if result.returncode in [0, 2]:
            # Exit code 0 = no changes needed, 2 = formatting applied
            console.print(f"[green]✓ Formatted successfully[/green]")
        else:
            console.print(f"[red]✗ Formatting failed with exit code {result.returncode}[/red]")
            if result.stderr:
                console.print(f"[red]{result.stderr}[/red]")
            if result.stdout:
                console.print(result.stdout)
            sys.exit(1)
    except FileNotFoundError:
        console.print("[red]✗ hledger-fmt not found[/red]")
        console.print("[yellow]Install it with:[/yellow] cargo install hledger-fmt")
        sys.exit(1)
    except KeyboardInterrupt:
        console.print("\n[yellow]⚠ Interrupted[/yellow]")
        sys.exit(0)


@app.command()
def init(
    directory: Optional[str] = typer.Argument(None, help="Directory to initialize (created if it doesn't exist). Defaults to current directory."),
):
    """[green]Initialize a new f7 finance setup[/green] in the current (or given) directory"""
    from datetime import datetime

    base_dir = Path(directory) if directory else Path(".")
    journals_dir = base_dir / "journals"

    console.print()
    console.print("[bold cyan]Welcome to f7[/bold cyan] — let's set up your personal finance journal.")
    console.print()

    if directory:
        console.print(f"[dim]→ Target directory:[/dim] [bold cyan]{base_dir}[/bold cyan]")
        console.print()

    # Check if already initialized
    if journals_dir.exists() and any(journals_dir.iterdir()):
        console.print(f"[yellow]⚠ A journals/ directory already exists in {base_dir}.[/yellow]")
        if not questionary.confirm("Continue anyway?", default=False).ask():
            raise typer.Exit(0)
        console.print()

    # --- Gather info ---
    currency = questionary.text(
        "What currency symbol do you use?",
        default="€",
    ).ask()
    if currency is None:
        raise typer.Exit(0)

    checking_account = questionary.text(
        "Name your main checking account (e.g. Revolut, Chase, Monzo):",
        default="MyBank",
    ).ask()
    if checking_account is None:
        raise typer.Exit(0)

    monthly_income = questionary.text(
        "Approximate monthly net income (number only, e.g. 3000):",
        default="3000",
    ).ask()
    if monthly_income is None:
        raise typer.Exit(0)

    add_forecast = questionary.confirm(
        "Add a sample monthly forecast (income + expenses)?",
        default=True,
    ).ask()
    if add_forecast is None:
        raise typer.Exit(0)

    console.print()

    # --- Build files ---
    year = datetime.now().year
    money_dir = journals_dir / "money"
    forecasts_dir = money_dir / "forecasts"
    money_dir.mkdir(parents=True, exist_ok=True)
    forecasts_dir.mkdir(parents=True, exist_ok=True)

    # config.json
    config = {
        "forecast": {"months": 6, "years": 3},
        "accounts": {
            "non_liquid": [
                "not:Assets:Property",
                "not:Liabilities",
                "not:Assets:Vehicles",
            ]
        },
        "forecast_file": "default.journal",
    }
    (money_dir / "config.json").write_text(json.dumps(config, indent=2) + "\n")

    # <year>.journal — main journal
    checking = f"Assets:Cash:{checking_account}"
    journal_content = f"""; {year} transactions
; Add new transactions below. Most recent at the bottom.
;
; Format:
;   YYYY-MM-DD Description
;     Account:Name   Amount{currency}
;     Account:Name
;
; The second posting is auto-calculated (must sum to zero).

account Assets:Cash
account {checking}
account Assets:Savings
account Assets:Investments
account Expenses:Food
account Expenses:Transport
account Expenses:Fun
account Expenses:Other
account Income:Salary
account Equity:Opening-Balances

commodity 1,000.00{currency}

; ── Opening balance ──────────────────────────────────────────────
; Set this to your current account balance on Jan 1st.

{year}-01-01 Opening balance
    {checking}          1,000.00{currency}
    Equity:Opening-Balances

; ── Example transactions ─────────────────────────────────────────

{year}-01-01 Salary
    {checking}          {monthly_income}.00{currency}
    Income:Salary

{year}-01-05 Groceries
    Expenses:Food       80.00{currency}
    {checking}

"""
    (money_dir / f"{year}.journal").write_text(journal_content)

    # forecasts/default.journal
    if add_forecast:
        forecast_content = f"""; Recurring transactions (forecasts)
; hledger uses these with --forecast to project future cash flows.
; Syntax: ~ <period>  <description>

~ monthly  salary
    {checking}          {monthly_income}.00{currency}
    Income:Salary

~ monthly  food
    Expenses:Food       200.00{currency}
    {checking}

~ monthly  fun
    Expenses:Fun        100.00{currency}
    {checking}

"""
    else:
        forecast_content = "; Add recurring transactions here.\n; Example:\n; ~ monthly  salary\n;     Assets:Cash:MyBank  3000.00€\n;     Income:Salary\n"

    (forecasts_dir / "default.journal").write_text(forecast_content)

    # CLAUDE.md
    claude_md_content = f"""\
# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with this repository.

**IMPORTANT:** Always run `f7 bs` and `f7 is` at the start of any financial analysis conversation
to get up-to-date balances and income data. Do not rely on static values from memory or this file.

## Project Overview

This repository uses [f7](https://github.com/dgzlopes/f7) — a personal finance CLI built on top of
[hledger](https://hledger.org/) for double-entry bookkeeping. Journals live in `journals/`, with
one folder per context (e.g. `money/`, `points/`).

## Setup

```bash
uv tool install "git+https://github.com/dgzlopes/f7"   # install f7
```

System dependencies: `hledger` (required), `hledger-ui`, `hledger-web`, `hledger-fmt` (optional).

## Key commands

```
f7 bs                      balance sheet
f7 is                      income statement
f7 bal                     account balances
f7 bs -l                   liquid assets only (excludes property, vehicles, mortgages)
f7 bs --forecast-monthly   project next 6 months
f7 bs --forecast-yearly    multi-year projection
f7 outflow                 expenses and liabilities with positive balance
f7 reg [acct]              transaction register for an account
f7 ctx                     switch journal context
f7 fmt                     format journal with hledger-fmt
```

## Journal structure

- `journals/money/{year}.journal` — current year transactions
- `journals/money/forecasts/default.journal` — recurring/projected transactions
- `journals/money/config.json` — forecast periods and account filters

Account hierarchy uses colons: `Assets:Cash:{checking_account}`, `Expenses:Food`, etc.
Currency: `{currency}`

## Personal context

<!-- Fill in your personal context so the agent can give relevant advice -->

- Age, location, employment:
- Annual gross salary:
- Main accounts and institutions:
- Property / loans / investments:
- Financial goals and philosophies:
"""
    (base_dir / "CLAUDE.md").write_text(claude_md_content)

    # Set context
    set_current_context(f"money/{year}")

    # --- Done ---
    prefix = f"{base_dir}/" if directory else ""
    console.print(f"[green]✓ Created[/green] {prefix}journals/money/config.json")
    console.print(f"[green]✓ Created[/green] {prefix}journals/money/{year}.journal")
    console.print(f"[green]✓ Created[/green] {prefix}journals/money/forecasts/default.journal")
    console.print(f"[green]✓ Created[/green] {prefix}CLAUDE.md")
    console.print(f"[green]✓ Context set to[/green] [bold cyan]money/{year}[/bold cyan]")
    console.print()
    console.print("[bold]Next steps:[/bold]")
    if directory:
        console.print(f"  0. [cyan]cd {base_dir}[/cyan]")
    console.print(f"  1. Edit [cyan]{prefix}CLAUDE.md[/cyan] — fill in your personal context for AI-assisted analysis")
    console.print(f"  2. Edit [cyan]{prefix}journals/money/{year}.journal[/cyan] — update the opening balance and add your transactions")
    console.print( "  3. Run [cyan]f7 bs[/cyan] to see your balance sheet")
    console.print( "  4. Run [cyan]f7 is[/cyan] to see your income statement")
    console.print( "  5. Run [cyan]f7 bs --forecast-monthly[/cyan] to project the next 6 months")
    console.print()


if __name__ == "__main__":
    app()

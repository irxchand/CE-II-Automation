import sys
import os
import json
import subprocess
import threading
from rich.console import Console
from rich.prompt import Prompt, IntPrompt
from rich.panel import Panel
from src.orchestrator import Orchestrator
from src.logger import logger
import logging

console = Console()
logger.setLevel(logging.INFO)

def auto_update():
    """Silently attempts to pull the latest code from GitHub."""
    try:
        if os.path.exists(".git"):
            subprocess.run(["git", "pull"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
    except Exception:
        pass

# Fire and forget the auto-updater in the background so it doesn't block the UI
threading.Thread(target=auto_update, daemon=True).start()

CONFIG_PATH = ".local/config.json"

def load_config():
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_config(data):
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)

def cmd_config():
    console.print(Panel.fit("[bold cyan]Configure Career Essentials Automation[/bold cyan]"))
    current = load_config()
    
    name = Prompt.ask("Enter your Full Name", default=current.get("name", ""))
    prn = Prompt.ask("Enter your PRN", default=current.get("prn", ""))
    division = Prompt.ask("Enter your Division", default=current.get("division", ""))
    batch = Prompt.ask("Enter your Batch", default=current.get("batch", ""))
    username = Prompt.ask("Enter your LeetCode Username", default=current.get("username", ""))
    
    reports_dir = Prompt.ask("Enter Reports Directory", default=current.get("reports_dir", ".local/assignments"))
    
    save_config({
        "name": name,
        "prn": prn,
        "division": division,
        "batch": batch,
        "username": username,
        "screenshots_dir": ".local/screenshots",
        "reports_dir": reports_dir
    })
    console.print("\n[bold green]\u2714 Configuration saved successfully.[/bold green]\n")

def ensure_config():
    config = load_config()
    required = ["name", "prn", "division", "batch", "username"]
    missing = [k for k in required if not config.get(k)]
    if missing:
        missing_str = ', '.join(missing)
        console.print(f"\n[bold red]Error: Missing configuration for {missing_str}.[/bold red]")
        console.print("Please select [bold cyan]Configure User Identity[/bold cyan] from the menu first.\n")
        return None
    return config

def get_assignment_id():
    return str(IntPrompt.ask("Enter Assignment ID (1-4)", choices=["1", "2", "3", "4"]))

def cmd_run():
    config = ensure_config()
    if not config: return
    
    assignment_id = get_assignment_id()
    
    console.print(f"\n[bold cyan]Starting Automation for Assignment {assignment_id}[/bold cyan]")
    
    orchestrator = Orchestrator(
        expected_username=config["username"], 
        prn=config["prn"], 
        screenshots_dir=".local/screenshots", 
        reports_dir=config.get("reports_dir", ".local/assignments")
    )
    try:
        if assignment_id == "4":
            orchestrator.run_mock_test()
        else:
            success = orchestrator.run_assignment(assignment_id)
            if success is False:
                console.print("\n[bold red]Partial batch failure or errors present[/bold red]")
                return
                
        console.print(f"\n[bold green]\u2714 Automation successfully finished for Assignment {assignment_id}![/bold green]")
            
    except FileNotFoundError as e:
        console.print(f"\n[bold red]Error (File Missing): {str(e)}[/bold red]")
    except KeyboardInterrupt:
        console.print("\n[bold yellow]Process interrupted by user.[/bold yellow]")
    except Exception as e:
        console.print(f"\n[bold red]Runtime Failure:[/bold red] {str(e)}")
    finally:
        if hasattr(orchestrator, "browser_controller") and orchestrator.browser_controller:
            try:
                orchestrator.browser_controller.close()
            except:
                pass

def cmd_report():
    config = ensure_config()
    if not config: return
    
    assignment_id = get_assignment_id()
        
    console.print(f"\n[bold cyan]Generating report for Assignment {assignment_id}...[/bold cyan]")
    orchestrator = Orchestrator(
        expected_username=config["username"], 
        prn=config["prn"], 
        screenshots_dir=".local/screenshots", 
        reports_dir=config.get("reports_dir", ".local/assignments")
    )
    try:
        if assignment_id == "4":
            orchestrator.report_engine.generate_mock_test_report()
        else:
            orchestrator.report_engine.generate_report(assignment_id)
        console.print(f"\n[bold green]\u2714 Report successfully generated for Assignment {assignment_id}![/bold green]")
    except Exception as e:
        console.print(f"\n[bold red]Failed to generate report:[/bold red] {str(e)}")

def main_menu():
    while True:
        console.print(Panel.fit("[bold magenta]Career Essentials LeetCode Automation[/bold magenta]\n[cyan]Interactive Menu[/cyan]"))
        console.print("  [bold green]1.[/bold green] Configure User Identity")
        console.print("  [bold green]2.[/bold green] Run Browser Automation")
        console.print("  [bold green]3.[/bold green] Generate Report")
        console.print("  [bold green]4.[/bold green] Exit")
        
        choice = Prompt.ask("\nSelect an option", choices=["1", "2", "3", "4"], default="2")
        
        if choice == "1":
            cmd_config()
        elif choice == "2":
            cmd_run()
        elif choice == "3":
            cmd_report()
        elif choice == "4":
            console.print("\n[bold yellow]Goodbye![/bold yellow]")
            break
        
        console.print("\n" + "-"*40 + "\n")

if __name__ == "__main__":
    try:
        main_menu()
    except KeyboardInterrupt:
        console.print("\n[bold yellow]Interrupted.[/bold yellow]")
        sys.exit(10)


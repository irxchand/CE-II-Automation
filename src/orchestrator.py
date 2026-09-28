import re
import time
import os
import json
from src.config import MAX_RETRIES, LEETCODE_BASE_URL
from src.logger import logger
from src.state_manager import StateManager
from src.browser_controller import BrowserController
from src.report_engine import ReportEngine
from src.solution_finder import SolutionFinder
from DrissionPage.errors import PageDisconnectedError
from rich.console import Console
from rich.prompt import Prompt


class Orchestrator:
    def __init__(self, expected_username: str, prn: str, manifests_dir: str = "solutions_manifests", screenshots_dir: str = "screenshots", reports_dir: str = "assignments"):
        self.expected_username = expected_username
        self.prn = prn
        self.manifests_dir = manifests_dir
        self.state_manager = StateManager(manifests_dir)
        self.browser_controller = BrowserController(screenshots_dir=screenshots_dir)
        self.report_engine = ReportEngine(prn=prn, manifests_dir=manifests_dir, screenshots_dir=screenshots_dir, reports_dir=reports_dir)
        self.solution_finder = SolutionFinder(manifests_dir=manifests_dir)
        self.console = Console()

    def run_assignment(self, assignment_id: str):
        logger.info(f"Starting orchestration for Assignment {assignment_id}")

        try:
            manifest = self.state_manager.load_manifest(assignment_id)
        except FileNotFoundError:
            logger.error(f"Cannot run Assignment {assignment_id} - manifest not found.")
            return

        # Initialize Browser and Auth
        self.browser_controller.initialize()
        auth_success = self.browser_controller.interactive_login(self.expected_username)

        if not auth_success:
            logger.error("Authentication failed or username mismatched. Aborting assignment execution.")
            self.browser_controller.close()
            return

        logger.info("Authentication successful. Proceeding with execution loop.")

        for problem in manifest:
            leetcode_id = problem.get('leetcode_id')
            title = problem.get('title')
            language = problem.get('language', 'Python')
            code = problem.get('solution_code', '')
            state = problem.get('state', 'PENDING')
            url = problem.get('url')
            if not url:
                title_slug = re.sub(r'[^a-z0-9\-]', '', title.lower().replace(' ', '-'))
                url = f"{LEETCODE_BASE_URL}/problems/{title_slug}/"

            # ----- State-based skip logic (persisted state is authoritative) -----
            persisted_state = self.state_manager._read_state().get(str(assignment_id), {}).get(str(leetcode_id), {}).get('state', 'PENDING')
            if persisted_state in ('COMPLETED', 'VERIFIED', 'SUBSCRIBER_ONLY'):
                logger.info(f"Skipping {title} (LeetCode ID {leetcode_id}) — already {persisted_state}.")
                continue

            if code == 'AGENT_FALLBACK_REQUIRED' or not code.strip():
                logger.warning(f"Problem '{title}' requires code, but none is provided. Marking as FAILED.")
                self.state_manager.update_problem_state(assignment_id, leetcode_id, 'FAILED')
                continue

            # Fast GraphQL Premium Check
            try:
                import requests
                title_slug = url.rstrip('/').split('/')[-1]
                gql_url = "https://leetcode.com/graphql"
                payload = {
                    "query": "query questionData($titleSlug: String!) { question(titleSlug: $titleSlug) { isPaidOnly } }",
                    "variables": {"titleSlug": title_slug}
                }
                r = requests.post(gql_url, json=payload, headers={'User-Agent': 'Mozilla/5.0'}).json()
                data_node = r.get("data") or {}
                question_node = data_node.get("question") or {}
                is_premium = question_node.get("isPaidOnly", False)
                if is_premium:
                    logger.warning(f"Problem {title} is Subscriber Only (Fast Check). Marking as SUBSCRIBER_ONLY.")
                    self.state_manager.update_problem_state(assignment_id, leetcode_id, 'SUBSCRIBER_ONLY')
                    continue
            except Exception as e:
                logger.debug(f"GraphQL premium check failed: {e}")

            self.state_manager.update_problem_state(assignment_id, leetcode_id, 'OPEN')
            problem_start_time = time.time()

            # ----- Submission Loop -----
            attempts = 0
            while attempts < MAX_RETRIES:
                attempts += 1
                logger.info(f"Attempt {attempts}/{MAX_RETRIES} for {title}...")

                try:
                    result = self.browser_controller.submit_solution(
                        url, code, title, language, assignment_id, str(leetcode_id)
                    )
                except PageDisconnectedError:
                    logger.warning(f"PageDisconnectedError during attempt {attempts} for {title}.")
                    if self.browser_controller._reconnect_if_needed():
                        continue  # retry this attempt
                    else:
                        logger.error("Could not reconnect to browser. Aborting problem.")
                        break
                except Exception as e:
                    logger.error(f"Unexpected error during attempt {attempts} for {title}: {e}")
                    continue

                if result.success and result.status_text == "Accepted":
                    elapsed = time.time() - problem_start_time
                    logger.info(f"[bold green]Problem {title} Accepted! (Time taken: {elapsed:.2f}s)[/bold green]")
                    
                    if not result.screenshot_path or not os.path.exists(result.screenshot_path):
                        logger.warning(f"Screenshot not saved for {title}. Leaving state as OPEN.")
                        self.state_manager.update_problem_state(assignment_id, leetcode_id, 'OPEN')
                        continue
                        
                    self.state_manager.update_problem_state(assignment_id, leetcode_id, 'VERIFIED')
                    self.state_manager.update_problem_state(assignment_id, leetcode_id, 'COMPLETED')
                    # Store scraped difficulty
                    if result.difficulty:
                        self.state_manager.update_problem_difficulty(assignment_id, leetcode_id, result.difficulty)
                    break
                elif result.failure_reason == "Subscriber Only":
                    elapsed = time.time() - problem_start_time
                    logger.warning(f"Problem {title} is Subscriber Only. (Time taken: {elapsed:.2f}s). Marking as SUBSCRIBER_ONLY.")
                    self.state_manager.update_problem_state(assignment_id, leetcode_id, 'SUBSCRIBER_ONLY')
                    if result.difficulty:
                        self.state_manager.update_problem_difficulty(assignment_id, leetcode_id, result.difficulty)
                    break
                else:
                    logger.warning(f"Submission failed for {title}. Status: {result.status_text}. Reason: {result.failure_reason}")

                    if result.status_text and ("Wrong Answer" in result.status_text or "Runtime Error" in result.status_text):
                        logger.error(f"Problem Failed: {title}. Error: {result.status_text}")
                        self.console.print(f"[bold yellow]Manual Debugging Mode:[/bold yellow] The problem '{title}' failed with '{result.status_text}'.")
                        self.console.print("Please fix the code directly in the LeetCode browser window, then submit it.")
                        self.console.print("Once you see 'Accepted' in the browser, press Enter to verify and continue (or type 'skip' to mark as failed).")
                        
                        while True:
                            user_input = Prompt.ask("[cyan]Press Enter to verify 'Accepted', or type 'skip'[/cyan]", default="")
                            if user_input.strip().lower() == "skip":
                                logger.warning(f"User skipped manual debugging for {title}. Marking as FAILED.")
                                self.state_manager.update_problem_state(assignment_id, leetcode_id, 'FAILED')
                                break

                            logger.info(f"Verifying manual submission for {title} in browser...")
                            verified, screenshot_path = self.browser_controller.verify_manual_submission(assignment_id, str(leetcode_id))
                            if verified and screenshot_path:
                                logger.info(f"[bold green]Manual submission verified: Accepted for {title}![/bold green]")
                                self.state_manager.update_problem_state(assignment_id, leetcode_id, 'VERIFIED')
                                self.state_manager.update_problem_state(assignment_id, leetcode_id, 'COMPLETED')
                                break
                            else:
                                self.console.print("[bold red]\u2718 Verification failed: LeetCode does not show 'Accepted' yet.[/bold red]")
                                self.console.print("Please ensure your submission has finished evaluating and is showing green 'Accepted'.")
                        break
                    # For injection failures or timeouts, the while loop will retry
            else:
                # while loop exhausted without break — all retries consumed
                elapsed = time.time() - problem_start_time
                logger.error(f"Max retries exceeded for {title} (Time taken: {elapsed:.2f}s). Marking as FAILED.")
                self.state_manager.update_problem_state(assignment_id, leetcode_id, 'FAILED')

        self.browser_controller.close()

        # Check if any problems failed
        state = self.state_manager._read_state()
        assignment_state = state.get(str(assignment_id), {})
        failed_problems = [pid for pid, pstate in assignment_state.items() if pstate.get('state') == 'FAILED']

        if failed_problems:
            logger.error(f"Cannot generate report. The following problems failed: {failed_problems}.")
            logger.error("Please complete them manually or use Manual Debugging Mode, then run again.")
            logger.error("[bold red]ERROR: Automation finished but some problems FAILED.[/bold red]")
            logger.error("[bold red]Report generation aborted due to failures.[/bold red]")
            return False

        return True

    def _record_mock_problem(self, prob_index: int, prob_info: dict, solution_code: str = ""):
        """Record problem metadata to mock_assessment_manifest.json for accurate docx generation."""
        mock_manifest_path = os.path.join(".local", "mock_assessment_manifest.json")
        data = []
        if os.path.exists(mock_manifest_path):
            try:
                with open(mock_manifest_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                data = []

        entry = {
            "leetcode_id": str(prob_info.get("problem_id") or prob_index),
            "title": prob_info.get("clean_title") or prob_info.get("title") or f"Problem {prob_index}",
            "difficulty": prob_info.get("difficulty", "Medium"),
            "solution_code": solution_code,
            "assignment_id": 4
        }

        updated = False
        for i, item in enumerate(data):
            if str(item.get("leetcode_id")) == entry["leetcode_id"] or i == (prob_index - 1):
                data[i] = entry
                updated = True
                break
        if not updated:
            data.append(entry)

        try:
            with open(mock_manifest_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4)
        except Exception as e:
            logger.warning(f"Could not write mock_assessment_manifest: {e}")

    def _handle_ai_fallback(self, current_prob: int, prob_info: dict, error_msg: str = "") -> bool:
        """Display clean prompt to copy/paste into an external AI (ChatGPT/Gemini/Claude) and handle response."""
        title = prob_info.get("clean_title") or prob_info.get("title") or f"Problem {current_prob}"
        pid = prob_info.get("problem_id")
        desc = prob_info.get("description", "")
        starter = prob_info.get("starter_code", "")

        # Minimal, direct prompt focused ONLY on getting the solution
        prompt_lines = [
            "Solve this LeetCode problem in Python 3.",
            "Return ONLY the valid Python code for class Solution without any explanations, comments, or markdown chat text.",
            "",
            f"Problem: {f'#{pid} ' if pid else ''}{title}"
        ]
        if desc:
            prompt_lines.append(f"\nDescription:\n{desc[:1200]}")
        if starter:
            prompt_lines.append(f"\nStarter Code:\n{starter}")

        full_prompt = "\n".join(prompt_lines)

        # Automatically copy prompt to Windows clipboard
        clipboard_ok = False
        try:
            import subprocess
            subprocess.run(["powershell", "-NoProfile", "-Command", "$input | Set-Clipboard"], input=full_prompt, encoding="utf-8", check=True)
            clipboard_ok = True
        except Exception:
            pass

        self.console.print("\n[bold yellow]" + "═" * 72 + "[/bold yellow]")
        self.console.print("[bold yellow]║                    AI SOLVER PROMPT (CLEAN)                           ║[/bold yellow]")
        self.console.print("[bold yellow]" + "═" * 72 + "[/bold yellow]\n")
        self.console.print(full_prompt, style="cyan")
        self.console.print("\n[bold yellow]" + "═" * 72 + "[/bold yellow]")
        if clipboard_ok:
            self.console.print("[bold green]✔ Prompt automatically copied to your clipboard! Just press Ctrl+V into ChatGPT, Google AI, or Claude.[/bold green]\n")
        else:
            self.console.print("[bold]Copy the prompt above and paste it into ChatGPT, Google AI, or Claude.[/bold]\n")

        self.console.print("[bold]Action Options:[/bold]")
        self.console.print("  [bold cyan]1[/bold cyan] or [bold cyan]'paste'[/bold cyan] - Paste the AI solution code (will auto-inject, submit & auto-snap)")
        self.console.print("  [bold cyan]2[/bold cyan] or [bold cyan]'verify'[/bold cyan] - You submitted directly in Chrome (will monitor & auto-snap)")
        self.console.print("  [bold cyan]3[/bold cyan] or [bold cyan]'snap'[/bold cyan] - Capture screenshot as-is")
        self.console.print("  [bold cyan]4[/bold cyan] or [bold cyan]'skip'[/bold cyan] - Skip to next problem\n")

        choice = Prompt.ask("[bold cyan]Select an option [1/2/3/4][/bold cyan]", default="1").strip().lower()

        if choice in ("1", "paste", "p"):
            self.console.print("\n[yellow]Paste your Python code below. Type 'END' on a new line when finished:[/yellow]")
            lines = []
            while True:
                try:
                    line = input()
                    if line.strip() == "END":
                        break
                    lines.append(line)
                except EOFError:
                    break
            code = "\n".join(lines).strip()
            if not code:
                self.console.print("[red]No code provided.[/red]")
                return False

            clean_code = self.solution_finder._clean_code(code)
            self.console.print("[dim]Injecting code into editor, submitting, and auto-capturing screenshot...[/dim]")
            accepted, verdict, screenshot_path = self.browser_controller.submit_mock_assessment_solution(clean_code, str(current_prob))
            if accepted:
                self.console.print(f"\n[bold green]✔ Problem {current_prob} verified: Accepted! Auto-captured screenshot:[/bold green] {screenshot_path}\n")
                self.state_manager.update_problem_state("4", str(current_prob), "COMPLETED")
                self._record_mock_problem(current_prob, prob_info, clean_code)
                return True
            else:
                self.console.print(f"[bold red]Submission verdict: {verdict}[/bold red]")
                return False

        elif choice in ("2", "verify", "v"):
            self.console.print("[dim]Monitoring Chrome for 'Accepted' verdict (waiting up to 30s)...[/dim]")
            for _ in range(30):
                verified, screenshot_path = self.browser_controller.verify_manual_submission("4", str(current_prob))
                if verified and screenshot_path:
                    self.console.print(f"\n[bold green]✔ Problem {current_prob} Accepted detected! Screenshot auto-captured:[/bold green] {screenshot_path}\n")
                    self.state_manager.update_problem_state("4", str(current_prob), "COMPLETED")
                    self._record_mock_problem(current_prob, prob_info, "")
                    return True
                time.sleep(1)
            self.console.print("[bold yellow]'Accepted' was not detected in Chrome within 30 seconds.[/bold yellow]")
            return False

        elif choice in ("3", "snap", "s"):
            screenshot_path = self.browser_controller.capture_mock_assessment_screenshot(str(current_prob))
            if screenshot_path:
                self.console.print(f"[bold green]✔ Screenshot saved:[/bold green] {screenshot_path}")
                self.state_manager.update_problem_state("4", str(current_prob), "COMPLETED")
                self._record_mock_problem(current_prob, prob_info, "")
                return True
            return False

        else:
            self.console.print(f"[yellow]Skipping Problem {current_prob}.[/yellow]")
            return False

    def _solve_mock_problem(self, current_prob: int) -> bool:
        """Automatically detect current question, search internet for best solution, inject and submit."""
        self.console.print(f"\n[bold cyan]─── Analyzing Problem {current_prob} on screen ───[/bold cyan]")
        prob_info = self.browser_controller.get_mock_assessment_problem()
        starter = prob_info.get("starter_code", "")

        # Search online with title, problem_id, AND starter_code (which resolves method name automatically!)
        self.console.print("[dim]Searching online solution via method signatures, LeetCode database & GitHub...[/dim]")
        solution_code, source = self.solution_finder.find_solution(
            title=prob_info.get("clean_title") or prob_info.get("title") or "",
            problem_id=prob_info.get("problem_id"),
            starter_code=starter
        )

        title = prob_info.get("clean_title") or prob_info.get("title") or f"Problem {current_prob}"
        pid = prob_info.get("problem_id")
        if title:
            self.console.print(f"[bold]Detected Problem:[/bold] {f'#{pid} ' if pid else ''}[cyan]{title}[/cyan]")

        if solution_code:
            self.console.print(f"[bold green]✔ Solution found from {source}[/bold green]")
            self.console.print("[dim]Injecting code into Monaco editor, submitting, and waiting for evaluation...[/dim]")
            accepted, verdict, screenshot_path = self.browser_controller.submit_mock_assessment_solution(solution_code, str(current_prob))
            if accepted:
                self.console.print(f"\n[bold green]✔ Problem {current_prob} ACCEPTED! Screenshot auto-captured: {screenshot_path}[/bold green]\n")
                self.state_manager.update_problem_state("4", str(current_prob), "COMPLETED")
                self._record_mock_problem(current_prob, prob_info, solution_code)
                return True
            else:
                self.console.print(f"\n[bold red]✖ Submission Verdict: {verdict}[/bold red]")
                return self._handle_ai_fallback(current_prob, prob_info, error_msg=verdict)
        else:
            self.console.print("[bold yellow]No ready solution found online.[/bold yellow]")
            return self._handle_ai_fallback(current_prob, prob_info, error_msg="Solution not found online")

    def run_mock_test(self):
        logger.info("Starting Mock Test workflow (Assignment 4) at https://leetcode.com/assessment/")

        # Initialize Browser and Auth
        self.browser_controller.initialize()
        auth_success = self.browser_controller.interactive_login(self.expected_username)

        if not auth_success:
            logger.error("Authentication failed or username mismatched. Aborting mock test.")
            self.browser_controller.close()
            return False

        logger.info("Navigating to LeetCode Assessment (https://leetcode.com/assessment/)...")
        self.browser_controller.open_mock_assessment()

        self.console.print("\n[bold cyan]" + "═" * 72 + "[/bold cyan]")
        self.console.print("[bold magenta]LeetCode Mock Assessment (Assignment 4) - Automated Solver[/bold magenta]")
        self.console.print("[bold cyan]" + "═" * 72 + "[/bold cyan]")
        self.console.print("Target: [bold green]https://leetcode.com/assessment/[/bold green]\n")
        self.console.print("[bold]Interactive Controls:[/bold]")
        self.console.print("  • Press [bold green]Enter[/bold green] or type [bold green]'solve'[/bold green] to auto-search internet, inject solution & submit")
        self.console.print("  • Type [bold yellow]'auto'[/bold yellow] to automatically solve all problems in the assessment")
        self.console.print("  • Type [bold cyan]'snap <number/name>'[/bold cyan] (e.g. snap 1, snap 2) to capture current screen")
        self.console.print("  • Type [bold blue]'paste'[/bold blue] to paste your own solution into the editor")
        self.console.print("  • Type [bold magenta]'done'[/bold magenta] or [bold magenta]'exit'[/bold magenta] when finished to generate the Mock Test report\n")

        current_prob = 1
        while True:
            cmd = Prompt.ask(f"[bold cyan]Mock Test (Problem {current_prob}) >[/bold cyan]", default="solve")
            cmd_clean = cmd.strip().lower()

            if cmd_clean in ("done", "exit", "quit"):
                logger.info("Finishing Mock Test and generating report...")
                break

            elif cmd_clean.startswith("snap ") or cmd_clean.startswith("capture "):
                parts = cmd.strip().split(maxsplit=1)
                name = parts[1] if len(parts) > 1 else str(current_prob)
                screenshot_path = self.browser_controller.capture_mock_assessment_screenshot(name)
                if screenshot_path:
                    self.console.print(f"[bold green]✔ Screenshot saved:[/bold green] {screenshot_path}")
                    self.state_manager.update_problem_state("4", name, "COMPLETED")
                    if name.isdigit() and int(name) == current_prob:
                        current_prob += 1

            elif cmd_clean == "auto":
                self.console.print("[bold yellow]Starting automated solver for all mock assessment questions...[/bold yellow]")
                for p_idx in range(current_prob, 5):
                    self.browser_controller.select_mock_problem_tab(p_idx)
                    time.sleep(2)
                    solved = self._solve_mock_problem(p_idx)
                    if solved:
                        current_prob = p_idx + 1
                    else:
                        cont = Prompt.ask(f"Problem {p_idx} not solved automatically. Continue to next problem? [Y/n]", default="y")
                        if cont.strip().lower() == "n":
                            break
                        current_prob = p_idx + 1

            elif cmd_clean in ("paste", "p"):
                prob_info = self.browser_controller.get_mock_assessment_problem()
                solved = self._handle_ai_fallback(current_prob, prob_info)
                if solved:
                    current_prob += 1

            elif cmd_clean in ("solve", ""):
                solved = self._solve_mock_problem(current_prob)
                if solved:
                    current_prob += 1
                else:
                    self.console.print(f"[yellow]Problem {current_prob} was not completed.[/yellow]")

            else:
                self.console.print(f"[yellow]Unknown command '{cmd}'. Type 'solve', 'auto', 'snap', 'paste', or 'done'.[/yellow]")

        self.browser_controller.close()

        # Generate report
        try:
            report_path = self.report_engine.generate_mock_test_report()
            if report_path:
                self.console.print(f"\n[bold green]✔ Mock Test report generated at:[/bold green] {report_path}")
        except Exception as e:
            logger.error(f"Error generating Mock Test report: {e}")

        return True

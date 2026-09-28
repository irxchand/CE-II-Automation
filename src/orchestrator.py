import re
import time
import os
from src.config import MAX_RETRIES, LEETCODE_BASE_URL
from src.logger import logger
from src.state_manager import StateManager
from src.browser_controller import BrowserController
from src.report_engine import ReportEngine
from DrissionPage.errors import PageDisconnectedError
from rich.console import Console
from rich.prompt import Prompt


class Orchestrator:
    def __init__(self, expected_username: str, prn: str, manifests_dir: str = "solutions_manifests", screenshots_dir: str = "screenshots", reports_dir: str = "assignments"):
        self.expected_username = expected_username
        self.prn = prn
        self.state_manager = StateManager(manifests_dir)
        self.browser_controller = BrowserController(screenshots_dir=screenshots_dir)
        self.report_engine = ReportEngine(prn=prn, manifests_dir=manifests_dir, screenshots_dir=screenshots_dir, reports_dir=reports_dir)
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
        # Navigate to assessment and select the first assessment (Online Assessment) according to the rubrics
        self.browser_controller.open_mock_assessment()

        self.console.print("\n[bold cyan]" + "═" * 70 + "[/bold cyan]")
        self.console.print("[bold magenta]LeetCode Mock Assessment (Assignment 4) - Online Assessment[/bold magenta]")
        self.console.print("[bold cyan]" + "═" * 70 + "[/bold cyan]")
        self.console.print("Target: [bold green]https://leetcode.com/assessment/[/bold green] (Online Assessment)\n")
        self.console.print("[bold]Interactive Controls:[/bold]")
        self.console.print("  • Press [bold green]Enter[/bold green] to verify and capture 'Accepted' screenshot for current problem")
        self.console.print("  • Type [bold cyan]'snap <number/name>'[/bold cyan] (e.g. snap 1, snap 2, snap summary) to capture the screen")
        self.console.print("  • Type [bold yellow]'auto'[/bold yellow] to run automated solution injection for Assignment 4 questions")
        self.console.print("  • Type [bold magenta]'done'[/bold magenta] or [bold magenta]'exit'[/bold magenta] when finished to generate the Mock Test report\n")

        current_prob = 1
        while True:
            cmd = Prompt.ask(f"[bold cyan]Mock Test (Problem {current_prob}) >[/bold cyan]", default="")
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
                self.console.print("[bold yellow]Running automated submission for Assignment 4 questions...[/bold yellow]")
                self.browser_controller.close()
                return self.run_assignment("4")

            else:
                logger.info(f"Verifying manual submission for Problem {current_prob}...")
                verified, screenshot_path = self.browser_controller.verify_manual_submission("4", str(current_prob))
                if verified and screenshot_path:
                    self.console.print(f"[bold green]✔ Problem {current_prob} verified: Accepted! Screenshot saved:[/bold green] {screenshot_path}")
                    self.state_manager.update_problem_state("4", str(current_prob), "COMPLETED")
                    current_prob += 1
                else:
                    self.console.print("[bold yellow]Verification could not find green 'Accepted' on the screen.[/bold yellow]")
                    snap_anyway = Prompt.ask("Take full-page screenshot anyway? [y/N]", default="n")
                    if snap_anyway.strip().lower() == "y":
                        screenshot_path = self.browser_controller.capture_mock_assessment_screenshot(str(current_prob))
                        if screenshot_path:
                            self.console.print(f"[bold green]✔ Screenshot saved:[/bold green] {screenshot_path}")
                            self.state_manager.update_problem_state("4", str(current_prob), "COMPLETED")
                            current_prob += 1

        self.browser_controller.close()

        # Generate report
        try:
            report_path = self.report_engine.generate_mock_test_report()
            if report_path:
                self.console.print(f"\n[bold green]✔ Mock Test report generated at:[/bold green] {report_path}")
        except Exception as e:
            logger.error(f"Error generating Mock Test report: {e}")

        return True

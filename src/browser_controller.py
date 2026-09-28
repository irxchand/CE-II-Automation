import os
import time
from DrissionPage import ChromiumPage, ChromiumOptions
from DrissionPage.errors import PageDisconnectedError
from pydantic import BaseModel
from typing import Optional
from src.logger import logger


class SubmissionResult(BaseModel):
    success: bool
    status_text: Optional[str] = None
    failure_reason: Optional[str] = None
    screenshot_path: Optional[str] = None
    error_output: Optional[str] = None
    difficulty: Optional[str] = None


class EditorAdapter:
    """
    Handles writing code into LeetCode's Monaco editor and verifying
    the editor actually contains the expected code before submission.

    Strategy order:
      1. Monaco model API — model.setValue() / model.getValue()
      2. CDP Input.insertText — Chrome DevTools Protocol text insertion
      3. Controlled page recovery — reload once, retry strategies 1-2
    """

    def __init__(self, page: ChromiumPage):
        self.page = page

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_editor_code(self, code: str) -> bool:
        """
        Write *code* into the active Monaco editor and verify.
        Returns True only when read-back verification succeeds.
        """
        # ----- Strategy 1: Monaco model API -----
        if self._try_monaco_model(code) == True:
            return True

        # ----- Strategy 2: CDP Input.insertText -----
        if self._try_cdp_insert(code) == True:
            return True

        # ----- Strategy 3: Controlled page recovery (single reload) -----
        logger.warning("Both editor strategies failed. Performing controlled page reload...")
        try:
            self.page.refresh()
            self._wait_for_editor_ready()
        except Exception as e:
            logger.error(f"Page reload failed: {e}")
            return False

        # Retry strategy 1 after reload
        if self._try_monaco_model(code) == True:
            return True

        # Retry strategy 2 after reload
        if self._try_cdp_insert(code) == True:
            return True

        logger.error("All editor injection strategies exhausted.")
        return False

    # ------------------------------------------------------------------
    # Strategy 1: Monaco model.setValue / getValue
    # ------------------------------------------------------------------

    def _try_monaco_model(self, code: str) -> bool:
        logger.debug("Strategy 1: Monaco model API")

        # Detect Monaco availability
        has_monaco = self.page.run_js(
            "return typeof monaco !== 'undefined' && monaco.editor !== undefined;"
        )
        if not has_monaco:
            logger.info("Monaco global not available. Skipping strategy 1.")
            return False

        logger.debug("Editor detected: Monaco")

        # Get the active editor model
        has_model = self.page.run_js(
            "return monaco.editor.getModels().length > 0;"
        )
        if not has_model:
            logger.warning("No Monaco editor models found.")
            return False

        logger.debug("Editor model detected")

        # Write through Monaco model
        # Write through Monaco model using base64 to avoid all escaping issues
        import base64
        encoded = base64.b64encode(code.encode('utf-8')).decode('utf-8')
        logger.debug("Writing solution through Monaco model (model.setValue)")
        self.page.run_js(f"""
            const models = monaco.editor.getModels();
            let targetModel = models[0];
            for (let m of models) {{
                if (m.uri && (m.uri.toString().includes('solution') || m.uri.toString().includes('snippet'))) {{
                    targetModel = m;
                    break;
                }}
            }}
            const decoded = decodeURIComponent(escape(atob('{encoded}')));
            targetModel.setValue(decoded);
        """)

        time.sleep(0.5)  # Brief stabilisation

        # Read back through Monaco model — independent path from setValue
        readback = self.page.run_js("""
            const models = monaco.editor.getModels();
            let targetModel = models[0];
            for (let m of models) {{
                if (m.uri && (m.uri.toString().includes('solution') || m.uri.toString().includes('snippet'))) {{
                    targetModel = m;
                    break;
                }}
            }}
            return targetModel.getValue();
        """)
        readback = readback or ""

        logger.debug(f"Editor read-back length: {len(readback)}")
        return self._verify(code, readback)

    # ------------------------------------------------------------------
    # Strategy 2: CDP Input.insertText
    # ------------------------------------------------------------------

    def _try_cdp_insert(self, code: str) -> bool:
        logger.debug("Strategy 2: CDP Input.insertText")

        # Focus the Monaco hidden textarea
        focused = self.page.run_js("""
            const ta = document.querySelector('textarea.inputarea');
            if (ta) { ta.focus(); return true; }
            return false;
        """)
        if not focused:
            logger.warning("Could not focus editor textarea for CDP insert.")
            return False

        time.sleep(0.3)

        # Select-all via CDP
        self.page.run_cdp('Input.dispatchKeyEvent',
                          type='rawKeyDown', windowsVirtualKeyCode=65,
                          code='KeyA', key='a', modifiers=2)  # 2 = Ctrl
        self.page.run_cdp('Input.dispatchKeyEvent',
                          type='keyUp', windowsVirtualKeyCode=65,
                          code='KeyA', key='a', modifiers=2)
        time.sleep(0.2)

        # Delete selection via CDP
        self.page.run_cdp('Input.dispatchKeyEvent',
                          type='rawKeyDown', windowsVirtualKeyCode=8,
                          code='Backspace', key='Backspace')
        self.page.run_cdp('Input.dispatchKeyEvent',
                          type='keyUp', windowsVirtualKeyCode=8,
                          code='Backspace', key='Backspace')
        time.sleep(0.3)

        # Insert text via CDP — this feeds directly into the focused element's
        # input pipeline without using the OS clipboard.
        logger.info("Inserting text via CDP Input.insertText")
        self.page.run_cdp('Input.insertText', text=code)

        time.sleep(0.8)  # Let Monaco process the input

        # Dismiss any autocomplete widgets triggered by the insertion
        self.page.run_cdp('Input.dispatchKeyEvent',
                          type='rawKeyDown', windowsVirtualKeyCode=27,
                          code='Escape', key='Escape')
        self.page.run_cdp('Input.dispatchKeyEvent',
                          type='keyUp', windowsVirtualKeyCode=27,
                          code='Escape', key='Escape')

        time.sleep(0.3)

        # Read back — prefer Monaco model if available, else fall back to DOM
        readback = self._read_editor_content()
        logger.debug(f"Editor read-back length: {len(readback)}")
        return self._verify(code, readback)

    # ------------------------------------------------------------------
    # Read-back helpers
    # ------------------------------------------------------------------

    def _read_editor_content(self) -> str:
        """Read the actual editor content, preferring the Monaco model."""
        # Try Monaco model first (independent verification path)
        content = self.page.run_js("""
            try {
                if (typeof monaco !== 'undefined' && monaco.editor.getModels().length > 0) {
                    return monaco.editor.getModels()[0].getValue();
                }
            } catch(e) {}
            return null;
        """)
        if content:
            return content

        # Fallback: read from the visible DOM lines
        view_lines = self.page.ele('css:.view-lines')
        return view_lines.text if view_lines else ""

    # ------------------------------------------------------------------
    # Verification
    # ------------------------------------------------------------------

    def _verify(self, expected: str, actual: str) -> bool:
        """
        Verify that *actual* editor content substantially matches *expected*.
        Normalises whitespace for comparison but checks key invariants exactly.
        """
        if not actual or len(actual.strip()) < 5:
            logger.warning("Verification FAILED — editor is empty or near-empty")
            return False

        # Check for class Solution
        if "class Solution" in expected and "class Solution" not in actual:
            logger.warning("Verification FAILED — 'class Solution' missing from editor")
            return False

        # Check for the expected method name (first def after class Solution)
        import re
        method_match = re.search(r'def (\w+)\(self', expected)
        if method_match:
            method_name = method_match.group(1)
            if method_name not in actual:
                logger.warning(f"Verification FAILED — method '{method_name}' missing from editor")
                return False

        # Normalised length comparison (allow ±20% for whitespace differences)
        norm_expected = ' '.join(expected.split())
        norm_actual = ' '.join(actual.split())
        ratio = len(norm_actual) / max(len(norm_expected), 1)
        if ratio < 0.5:
            logger.warning(f"Verification FAILED — content too short (ratio={ratio:.2f})")
            return False

        logger.debug("Editor verification: SUCCESS")
        return True

    # ------------------------------------------------------------------
    # Readiness detection
    # ------------------------------------------------------------------

    def _wait_for_editor_ready(self, timeout: int = 30) -> str:
        """
        Wait until the Monaco editor container and model are interactive.
        Returns "READY" when ready, "SUBSCRIBER_ONLY" if locked, "TIMEOUT" otherwise.
        """
        logger.debug("Waiting for editor readiness...")
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                if self.page.run_js("return document.body.innerText.includes('Subscribe to unlock');"):
                    logger.warning("Subscriber only problem detected.")
                    return "SUBSCRIBER_ONLY"

                editor_el = self.page.ele('css:.monaco-editor', timeout=2)
                if editor_el:
                    # Check for Monaco model
                    has_model = self.page.run_js("""
                        return typeof monaco !== 'undefined'
                            && monaco.editor
                            && monaco.editor.getModels().length > 0;
                    """)
                    if has_model:
                        logger.debug("Editor ready: Monaco model available")
                        return "READY"

                    # Even without the global, the editor container exists
                    textarea = self.page.ele('css:textarea.inputarea', timeout=2)
                    if textarea:
                        logger.info("Editor ready: textarea.inputarea present")
                        return "READY"
            except PageDisconnectedError:
                raise
            except Exception:
                pass
            time.sleep(1)

        logger.warning("Editor readiness timeout")
        return "TIMEOUT"

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    @staticmethod
    def _js_escape(code: str) -> str:
        """Escape a string for safe embedding inside a JS template literal."""
        return (code
                .replace('\\', '\\\\')
                .replace('`', '\\`')
                .replace('$', '\\$'))


class BrowserController:
    def __init__(self, profile_dir: str = ".local/browser-profile", screenshots_dir: str = "screenshots"):
        self.profile_dir = os.path.abspath(profile_dir)
        self.screenshots_dir = os.path.abspath(screenshots_dir)
        self.page = None
        self._editor_adapter = None
        self._last_difficulty = None

    def initialize(self) -> None:
        logger.info("Initializing DrissionPage...")
        co = ChromiumOptions()
        co.set_user_data_path(self.profile_dir)
        co.set_argument('--window-size=1280,800')
        co.set_pref('profile.default_content_setting_values.clipboard', 1)
        self.page = ChromiumPage(co)
        self._editor_adapter = EditorAdapter(self.page)

    # ------------------------------------------------------------------
    # Page lifecycle helpers
    # ------------------------------------------------------------------

    def _reconnect_if_needed(self) -> bool:
        """Detect and recover from a disconnected browser page."""
        try:
            _ = self.page.url  # Probe connection
            return "READY"
        except (PageDisconnectedError, Exception):
            logger.warning("Page disconnected. Attempting to reinitialise...")
            try:
                self.initialize()
                return "READY"
            except Exception as e:
                logger.error(f"Reinitialisation failed: {e}")
                return "TIMEOUT"

    def _safe_navigate(self, url: str, retries: int = 2) -> bool:
        """Navigate to *url* with disconnect recovery."""
        for attempt in range(retries):
            try:
                self.page.get(url)
                return "READY"
            except PageDisconnectedError:
                logger.warning(f"PageDisconnectedError during navigation (attempt {attempt+1})")
                if not self._reconnect_if_needed():
                    return "TIMEOUT"
            except Exception as e:
                logger.error(f"Navigation error: {e}")
                return "TIMEOUT"
        return "TIMEOUT"

    # ------------------------------------------------------------------
    # Authentication
    # ------------------------------------------------------------------

    def interactive_login(self, expected_username: str) -> bool:
        logger.info("Navigating to LeetCode for interactive login...")
        if not self._safe_navigate("https://leetcode.com/accounts/login/"):
            return "TIMEOUT"

        logger.info("Please log in manually if not already logged in. Waiting for user profile...")

        while True:
            try:
                avatar = self.page.ele('css:a[href^="/u/"]', timeout=45)
                if avatar:
                    href = avatar.attr('href')
                    logged_in_username = href.strip('/').split('/')[-1] if href else ""
                    logger.info(f"Detected username: {logged_in_username}")
                    if logged_in_username.lower() != expected_username.lower():
                        logger.error(f"Username mismatch: Expected {expected_username}, found {logged_in_username}")
                        return "TIMEOUT"
                    return "READY"
                else:
                    logger.warning("Timeout waiting for login. Refreshing...")
                    self.page.refresh()
            except PageDisconnectedError:
                logger.error("Browser disconnected during login.")
                return "TIMEOUT"
            except Exception as e:
                logger.error(f"Login error: {e}")
                return "TIMEOUT"

    # ------------------------------------------------------------------
    # Page preparation helpers
    # ------------------------------------------------------------------

    def _dismiss_popups(self):
        """Dismiss LeetCode tour / promo / dialog popups."""
        try:
            self.page.run_js("""
                const texts = ["Skip", "Got it", "Close", "Maybe Later", "Done", "No thanks"];
                document.querySelectorAll('button, a').forEach(b => {
                    if (b.innerText && texts.some(t => b.innerText.trim() === t)) {
                        b.click();
                    }
                });
                document.querySelectorAll('[role="dialog"]').forEach(d => d.remove());
                document.querySelectorAll('.ReactModalPortal').forEach(d => d.remove());
            """)
        except Exception:
            pass

    def _select_language(self, language: str):
        """Click the language selector and pick *language*."""
        logger.info(f"Selecting language: {language}")
        self.page.run_js(f"""
            let buttons = Array.from(document.querySelectorAll('button'));
            let langBtn = buttons.find(b => {{
                const t = b.textContent.trim();
                return ['C++', 'Java', 'Python', 'Python3', 'Auto', 'C', 'MySQL', 'Pandas'].includes(t);
            }});
            if (langBtn) {{
                langBtn.click();
                setTimeout(() => {{
                    let options = Array.from(document.querySelectorAll('div, span, li'));
                    let target = options.find(o => o.textContent.trim() === '{language}');
                    if (target) target.click();
                }}, 400);
            }}
        """)
        time.sleep(1)

    def _scrape_difficulty(self) -> Optional[str]:
        """Scrape problem difficulty (Easy/Medium/Hard) from the loaded problem page."""
        try:
            # Wait a little bit for the description pane to render
            time.sleep(2)
            # Find elements containing the specific text
            for diff in ["Easy", "Medium", "Hard"]:
                if self.page.ele(f'text:{diff}'):
                    logger.info(f"Difficulty scraped: {diff}")
                    self._last_difficulty = diff
                    return diff
        except Exception as e:
            logger.warning(f"Could not scrape difficulty: {e}")
        self._last_difficulty = None
        return None

    # ------------------------------------------------------------------
    # Submission
    # ------------------------------------------------------------------

    def submit_solution(
        self,
        url: str,
        code: str,
        problem_title: str,
        language: str = "Python",
        assignment_id: str = "1",
        problem_id: str = "0",
    ) -> SubmissionResult:
        logger.info(f"Loading solution from JSON for: {problem_title}")
        logger.info(f"Navigating to {url}")

        if not self._safe_navigate(url):
            return SubmissionResult(success=False, failure_reason="Navigation failed / page disconnected")

        # ------ Readiness: wait for problem page ------
        try:
            self.page.ele('css:.monaco-editor', timeout=15)
        except Exception:
            pass  # We'll check again below

        # Scrape difficulty from the problem page
        difficulty = self._scrape_difficulty()

        self._dismiss_popups()
        self._select_language(language)

        # ------ Wait for editor to be fully interactive ------
        # Use standard timeout (30s)
        editor_timeout = 30
        editor_status = self._editor_adapter._wait_for_editor_ready(timeout=editor_timeout)
        if editor_status == "SUBSCRIBER_ONLY":
            return SubmissionResult(success=False, failure_reason="Subscriber Only", difficulty=difficulty)
        elif editor_status != "READY":
            return SubmissionResult(success=False, failure_reason="Editor did not become ready", difficulty=difficulty)

        # Small stabilisation delay
        time.sleep(1)

        # ------ Inject code through EditorAdapter ------
        injection_ok = self._editor_adapter.set_editor_code(code)

        if not injection_ok:
            logger.error("Editor verification FAILED — submission blocked")
            return SubmissionResult(success=False, failure_reason="Editor injection failed verification")

        logger.debug("Editor verification SUCCESS — submitting")

        # Dismiss autocomplete / overlays before clicking submit
        try:
            self.page.run_js("""
                document.querySelectorAll('[role="dialog"]').forEach(d => d.remove());
                document.querySelectorAll('.ReactModalPortal').forEach(d => d.remove());
            """)
        except Exception:
            pass

        time.sleep(1)

        # ------ Click Submit ------
        current_url = self.page.url
        submit_btn = self.page.ele('css:[data-e2e-locator="console-submit-button"]')
        if submit_btn:
            submit_btn.click(by_js=True)
        else:
            logger.error("Submit button not found!")
            return SubmissionResult(success=False, failure_reason="Submit button not found")

        # ------ Wait for evaluation results ------
        logger.debug("Waiting for evaluation results...")
        return self._wait_for_result(current_url, assignment_id, problem_id)

    # ------------------------------------------------------------------
    # Result parsing
    # ------------------------------------------------------------------

    def _wait_for_result(self, previous_url: str, assignment_id: str, problem_id: str) -> SubmissionResult:
        """Poll the submission page for a final verdict."""
        # Wait up to 10s for either URL change to /submissions/ or the submission result panel to appear
        for _ in range(10):
            try:
                if ("/submissions/" in self.page.url) or self.page.ele('css:[data-e2e-locator="submission-result"]'):
                    break
            except PageDisconnectedError:
                if not self._reconnect_if_needed():
                    return SubmissionResult(success=False, failure_reason="Page disconnected after submit")
            time.sleep(1)

        # Indicators that the submission is still being evaluated
        evaluating_indicators = (
            "Pending...", "Status: Evaluating", "Restrictions Check",
            "Judging", "Speed Up", "preparing runtime environment",
            "running test cases", "Submitting", "Evaluating",
        )

        known_verdicts = [
            "Accepted", "Wrong Answer", "Runtime Error", "Compile Error", 
            "Time Limit Exceeded", "Memory Limit Exceeded", 
            "Output Limit Exceeded"
        ]

        result_text = ""

        for _ in range(90):
            try:
                # 1. Primary Strategy: Check dedicated LeetCode submission result element
                result_ele = self.page.ele('css:[data-e2e-locator="submission-result"]')
                if result_ele:
                    ele_text = result_ele.text.strip()
                    if ele_text:
                        # If still evaluating, keep waiting
                        if any(ind.lower() in ele_text.lower() for ind in evaluating_indicators):
                            time.sleep(1)
                            continue

                        # Check errors first to avoid false accepted
                        for verdict in known_verdicts[1:]:
                            if verdict.lower() in ele_text.lower():
                                result_text = verdict
                                break
                        if not result_text and "accepted" in ele_text.lower():
                            result_text = "Accepted"

                        if result_text:
                            break
                        if not any(ind.lower() in ele_text.lower() for ind in evaluating_indicators):
                            result_text = ele_text
                            break

                # 2. Secondary Strategy: Check result container in submissions tab
                container_ele = self.page.ele('css:div[class*="status-column"], div[class*="result-container"], div[class*="submission-detail"]')
                if container_ele:
                    ctext = container_ele.text.strip()
                    if any(ind.lower() in ctext.lower() for ind in evaluating_indicators):
                        time.sleep(1)
                        continue
                    for verdict in known_verdicts[1:]:
                        if verdict.lower() in ctext.lower():
                            result_text = verdict
                            break
                    if not result_text and "accepted" in ctext.lower():
                        result_text = "Accepted"
                    if result_text:
                        break

                # 3. Fallback: If on submissions URL, scan body text but check evaluating first
                body = self.page.ele('tag:body')
                page_text = body.text if body else ""

                if any(indicator in page_text for indicator in evaluating_indicators):
                    time.sleep(1)
                    continue

                if "/submissions/" in self.page.url:
                    for kw in known_verdicts:
                        if kw in page_text:
                            result_text = kw
                            break
                    if result_text:
                        break
            except PageDisconnectedError:
                if not self._reconnect_if_needed():
                    return SubmissionResult(success=False, failure_reason="Page disconnected during evaluation")
            time.sleep(1)

        if not result_text:
            return SubmissionResult(success=False, failure_reason="Timeout waiting for submission result")

        if result_text.lower() == "accepted":
            logger.info(f"[bold green]Submission Result: {result_text}[/bold green]")
        else:
            logger.info(f"[bold red]Submission Result: {result_text}[/bold red]")

        if result_text == "Accepted":
            screenshot_dir = os.path.abspath(os.path.join(self.screenshots_dir, f"assignment_{assignment_id}"))
            os.makedirs(screenshot_dir, exist_ok=True)
            screenshot_path = os.path.join(screenshot_dir, f"{problem_id}.png").replace('\\', '/')

            # Wait 5 seconds for the Accepted screen to fully render
            logger.info("Waiting 5 seconds for Accepted screen to fully render...")
            time.sleep(5)
            try:
                # Maximize window and take full page screenshot to prevent empty/cropped images
                try:
                    self.page.set.window.max()
                    time.sleep(1)
                except Exception:
                    pass
                self.page.get_screenshot(path=screenshot_path, full_page=True)
                logger.info(f"[bold cyan]Screenshot captured:[/bold cyan] [cyan]{screenshot_path}[/cyan]")
            except Exception as e:
                logger.warning(f"Screenshot capture failed: {e}")
                screenshot_path = None

            return SubmissionResult(success=True, status_text="Accepted", screenshot_path=screenshot_path, difficulty=self._last_difficulty)
        else:
            # No screenshot for non-Accepted results
            return SubmissionResult(
                success=False,
                status_text=result_text,
                failure_reason=result_text,
                error_output=result_text,
                difficulty=self._last_difficulty,
            )

    def verify_manual_submission(self, assignment_id: str, problem_id: str) -> tuple[bool, Optional[str]]:
        """Verify that the current page actually shows 'Accepted' before capturing screenshot."""
        time.sleep(2)
        error_indicators = ["wrong answer", "runtime error", "compile error", "time limit exceeded", "memory limit exceeded"]
        
        result_ele = self.page.ele('css:[data-e2e-locator="submission-result"]')
        ele_text = result_ele.text.strip() if result_ele else ""
        
        if any(err in ele_text.lower() for err in error_indicators):
            logger.error(f"Manual verification failed: Submission element indicates '{ele_text}'.")
            return False, None
            
        is_accepted = False
        if "accepted" in ele_text.lower():
            is_accepted = True
        else:
            container = self.page.ele('css:div[class*="status-column"], div[class*="submission-detail"], div[class*="result-container"]')
            if container:
                ctext = container.text.strip()
                if any(err in ctext.lower() for err in error_indicators):
                    logger.error("Manual verification failed: Submission container indicates an error.")
                    return False, None
                if "accepted" in ctext.lower():
                    is_accepted = True

        if not is_accepted:
            logger.error("Manual verification failed: 'Accepted' verdict not found on screen.")
            return False, None

        screenshot_dir = os.path.abspath(os.path.join(self.screenshots_dir, f"assignment_{assignment_id}"))
        os.makedirs(screenshot_dir, exist_ok=True)
        screenshot_path = os.path.join(screenshot_dir, f"{problem_id}.png").replace('\\', '/')
        try:
            self.page.set.window.max()
            time.sleep(1)
        except Exception:
            pass
        self.page.get_screenshot(path=screenshot_path, full_page=True)
        logger.info(f"[bold cyan]Screenshot captured:[/bold cyan] [cyan]{screenshot_path}[/cyan]")
        return True, screenshot_path

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def close(self):
        try:
            if self.page:
                self.page.quit()
        except Exception:
            pass

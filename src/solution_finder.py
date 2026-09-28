import json
import os
import re
import urllib.parse
from typing import Optional, Tuple, Dict, Any, List
import requests
from src.logger import logger

class SolutionFinder:
    """
    Finds Python solutions for LeetCode problems by searching:
    1. Local manifests (solutions_manifests/*.json, manifests/*.json)
    2. GitHub repository: doocs/leetcode (raw content across 3000+ problems)
    3. GitHub repository: walkccc/LeetCode (raw solutions)
    4. LeetCode GraphQL query to resolve title/slug
    5. Fallback web searches
    """

    def __init__(self, manifests_dir: str = "solutions_manifests"):
        self.manifests_dir = manifests_dir
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        })

    def find_solution(self, title: str, problem_id: Optional[str] = None) -> Tuple[Optional[str], str]:
        """
        Find best Python solution for given problem title or ID.
        Returns: (solution_code, source_description)
        """
        clean_title, extracted_id = self._parse_title_and_id(title, problem_id)
        pid = extracted_id or problem_id

        logger.info(f"Searching solution for: ID={pid or 'Unknown'}, Title='{clean_title}'")

        # Step 1: Local Manifests
        local_sol = self._search_local_manifests(pid, clean_title)
        if local_sol:
            logger.info(f"[bold green][OK] Solution found in {local_sol[1]}[/bold green]")
            return self._clean_code(local_sol[0]), local_sol[1]

        # Step 2: If we don't have problem_id, try resolving via LeetCode GraphQL
        resolved_title = clean_title
        if not pid and clean_title:
            gql_info = self._resolve_via_graphql(clean_title)
            if gql_info:
                pid = gql_info.get("id")
                resolved_title = gql_info.get("title") or clean_title
                logger.info(f"Resolved via LeetCode GraphQL: #{pid} {resolved_title}")

        # Step 3: GitHub doocs/leetcode (direct raw)
        if pid and str(pid).isdigit():
            num = int(pid)
            doocs_sol = self._search_doocs_direct(num, resolved_title)
            if doocs_sol:
                logger.info(f"[bold green][OK] Solution found in {doocs_sol[1]}[/bold green]")
                return self._clean_code(doocs_sol[0]), doocs_sol[1]

            # Step 4: GitHub walkccc/LeetCode (direct raw)
            walkccc_sol = self._search_walkccc(num, resolved_title)
            if walkccc_sol:
                logger.info(f"[bold green][OK] Solution found in {walkccc_sol[1]}[/bold green]")
                return self._clean_code(walkccc_sol[0]), walkccc_sol[1]

            # Step 5: GitHub doocs/leetcode via folder search (API)
            doocs_api_sol = self._search_doocs_api(num)
            if doocs_api_sol:
                logger.info(f"[bold green][OK] Solution found in {doocs_api_sol[1]}[/bold green]")
                return self._clean_code(doocs_api_sol[0]), doocs_api_sol[1]

        # Step 6: Search by title in GitHub raw via DuckDuckGo / web search
        web_sol = self._search_web_for_solution(clean_title, pid)
        if web_sol:
            logger.info(f"[bold green][OK] Solution found in {web_sol[1]}[/bold green]")
            return self._clean_code(web_sol[0]), web_sol[1]

        logger.warning(f"Could not automatically find solution for: #{pid or '?'} {clean_title}")
        return None, "Not found"

    def _parse_title_and_id(self, title: str, problem_id: Optional[str]) -> Tuple[str, Optional[str]]:
        """Parse clean title and extract problem number if present."""
        clean = title.strip()
        extracted_id = None

        # Check for patterns like "1. Two Sum", "01. Two Sum", "#1 Two Sum", "Problem 1: Two Sum"
        m = re.match(r'^(?:problem\s*)?#?(\d+)[\.\:\-\s]+(.+)$', clean, re.IGNORECASE)
        if m:
            extracted_id = m.group(1)
            clean = m.group(2).strip()

        # Remove trailing info like " - LeetCode", " - Assessment"
        clean = re.sub(r'\s*-\s*(LeetCode|Assessment|Mock Test).*$', '', clean, flags=re.IGNORECASE).strip()

        return clean, (problem_id or extracted_id)

    def _search_local_manifests(self, problem_id: Optional[str], clean_title: str) -> Optional[Tuple[str, str]]:
        """Check all local manifest files."""
        dirs_to_check = [self.manifests_dir, "manifests", "solutions_manifests"]
        for d in dirs_to_check:
            if not os.path.exists(d):
                continue
            for fn in os.listdir(d):
                if not fn.endswith(".json"):
                    continue
                path = os.path.join(d, fn)
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        items = json.load(f)
                    if isinstance(items, list):
                        for item in items:
                            code = item.get("solution_code")
                            if not code:
                                continue
                            item_id = str(item.get("leetcode_id", ""))
                            item_title = item.get("title", "").strip().lower()

                            if problem_id and item_id == str(problem_id):
                                return code, f"Local manifest ({fn}: #{item_id} {item.get('title')})"
                            if clean_title and clean_title.lower() == item_title:
                                return code, f"Local manifest ({fn}: {item.get('title')})"
                except Exception:
                    continue
        return None

    def _search_doocs_direct(self, problem_num: int, title: str) -> Optional[Tuple[str, str]]:
        """Query doocs/leetcode raw GitHub content directly."""
        r_start = (problem_num // 100) * 100
        r_end = r_start + 99
        r_dir = f"{r_start:04d}-{r_end:04d}"

        # Title variations to test
        variations = [
            title,
            title.replace("-", " "),
            title.replace("'", ""),
            title.replace("’", ""),
            re.sub(r'[^a-zA-Z0-9\s]', '', title),
        ]
        unique_vars = []
        for v in variations:
            v_clean = v.strip()
            if v_clean and v_clean not in unique_vars:
                unique_vars.append(v_clean)

        for var in unique_vars:
            folder_name = f"{problem_num:04d}.{var}"
            quoted_folder = urllib.parse.quote(folder_name)
            url = f"https://raw.githubusercontent.com/doocs/leetcode/main/solution/{r_dir}/{quoted_folder}/Solution.py"
            try:
                resp = self.session.get(url, timeout=6)
                if resp.status_code == 200 and "class Solution" in resp.text:
                    return resp.text, f"doocs/leetcode ({folder_name})"
            except Exception:
                continue

        return None

    def _search_walkccc(self, problem_num: int, title: str) -> Optional[Tuple[str, str]]:
        """Query walkccc/LeetCode raw solutions."""
        variations = [
            f"{problem_num}. {title}",
            f"{problem_num}. {title.replace('-', ' ')}",
            f"{problem_num}. {re.sub(r'[^a-zA-Z0-9\s]', '', title)}",
        ]
        for var in variations:
            quoted_folder = urllib.parse.quote(var.strip())
            url = f"https://raw.githubusercontent.com/walkccc/LeetCode/main/solutions/{quoted_folder}/{problem_num}.py"
            try:
                resp = self.session.get(url, timeout=6)
                if resp.status_code == 200 and "class Solution" in resp.text:
                    return resp.text, f"walkccc/LeetCode ({var})"
            except Exception:
                continue
        return None

    def _search_doocs_api(self, problem_num: int) -> Optional[Tuple[str, str]]:
        """List GitHub directory to find the exact folder name matching problem_num."""
        r_start = (problem_num // 100) * 100
        r_end = r_start + 99
        r_dir = f"{r_start:04d}-{r_end:04d}"
        api_url = f"https://api.github.com/repos/doocs/leetcode/contents/solution/{r_dir}"

        try:
            resp = self.session.get(api_url, timeout=8)
            if resp.status_code == 200:
                prefix = f"{problem_num:04d}."
                for item in resp.json():
                    name = item.get("name", "")
                    if name.startswith(prefix):
                        raw_url = f"https://raw.githubusercontent.com/doocs/leetcode/main/solution/{r_dir}/{urllib.parse.quote(name)}/Solution.py"
                        sol_resp = self.session.get(raw_url, timeout=6)
                        if sol_resp.status_code == 200 and "class Solution" in sol_resp.text:
                            return sol_resp.text, f"doocs/leetcode ({name})"
        except Exception:
            pass
        return None

    def _resolve_via_graphql(self, title: str) -> Optional[Dict[str, str]]:
        """Query LeetCode public GraphQL to resolve title slug to questionFrontendId."""
        slug = re.sub(r'[^a-z0-9]+', '-', title.lower()).strip('-')
        query = """
        query getQuestionDetail($titleSlug: String!) {
            question(titleSlug: $titleSlug) {
                questionFrontendId
                title
                titleSlug
                difficulty
            }
        }
        """
        try:
            resp = self.session.post(
                "https://leetcode.com/graphql",
                json={"query": query, "variables": {"titleSlug": slug}},
                timeout=6
            )
            if resp.status_code == 200:
                data = resp.json().get("data", {}).get("question")
                if data:
                    return {
                        "id": data.get("questionFrontendId"),
                        "title": data.get("title"),
                        "difficulty": data.get("difficulty")
                    }
        except Exception:
            pass
        return None

    def _search_web_for_solution(self, title: str, problem_id: Optional[str]) -> Optional[Tuple[str, str]]:
        """Fallback search using DuckDuckGo HTML for LeetCode Python solution."""
        query = f"site:github.com/doocs/leetcode Solution.py {problem_id or ''} {title}"
        url = f"https://html.duckduckgo.com/html/?q={urllib.parse.quote(query)}"
        try:
            resp = self.session.get(url, timeout=8)
            if resp.status_code == 200:
                matches = re.findall(r'doocs/leetcode/(?:blob|raw)/main/solution/([^"\'>\s]+)', resp.text)
                for match in matches:
                    if match.endswith("Solution.py"):
                        raw_url = f"https://raw.githubusercontent.com/doocs/leetcode/main/solution/{match}"
                        sol_resp = self.session.get(raw_url, timeout=6)
                        if sol_resp.status_code == 200 and "class Solution" in sol_resp.text:
                            return sol_resp.text, f"GitHub doocs/leetcode ({match})"
        except Exception:
            pass
        return None

    def _clean_code(self, code: str) -> str:
        """Strip markdown fences and formatting artifacts."""
        cleaned = code.strip()

        if "```python" in cleaned:
            parts = cleaned.split("```python")
            if len(parts) > 1:
                cleaned = parts[1].split("```")[0]
        elif "```" in cleaned:
            parts = cleaned.split("```")
            if len(parts) > 1:
                cleaned = parts[1].split("```")[0]

        return cleaned.strip()

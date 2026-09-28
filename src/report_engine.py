import os
import json
from datetime import datetime
from docx import Document
from docx.shared import Inches, RGBColor, Pt
from src.state_manager import StateManager
from src.logger import logger

class ReportEngine:
    def __init__(self, prn: str, manifests_dir: str = "solutions_manifests", screenshots_dir: str = None, reports_dir: str = None):
        self.prn = prn
        self.state_manager = StateManager(manifests_dir)
        # Force screenshots dir to .local/screenshots where they are actually saved
        self.screenshots_dir = os.path.join(".local", "screenshots")
        self.reports_dir = os.path.join(".local", "reports") if reports_dir is None else reports_dir
        os.makedirs(self.reports_dir, exist_ok=True)
        self.subscriber_ids = ['2880', '2885', '2890', '1068', '511', '550', '346', '534', '569', '578', '580', '612', '613', '614', '615', '618', '1076', '1077', '1082', '1083', '1084', '1098', '1126', '1132', '1141', '1142', '1149', '1164', '1173', '1193', '1204']

    def generate_report(self, assignment_id: str) -> str:
        logger.info(f"Generating report for Assignment {assignment_id}...")
        try:
            data = self.state_manager.load_manifest(assignment_id)
        except Exception as e:
            logger.error(f"Cannot load manifest for report generation: {e}")
            return ""

        doc = Document()

        # Load user details
        config = {}
        config_path = os.path.join(".local", "config.json")
        if os.path.exists(config_path):
            with open(config_path, "r", encoding="utf-8") as f:
                config = json.load(f)
                
        name = config.get("name", "Unknown")
        prn = config.get("prn", self.prn)
        div = config.get("division", "Unknown")
        batch = config.get("batch", "Unknown")

        doc.add_heading(f'Assignment {assignment_id}', 0)
        
        # Add User Details Section
        doc.add_paragraph(f"Name: {name}")
        doc.add_paragraph(f"PRN: {prn}")
        doc.add_paragraph(f"Division: {div}")
        doc.add_paragraph(f"Batch: {batch}")
        doc.add_paragraph("") # Spacer
        
        for idx, item in enumerate(data):
            title = item.get('title', 'Unknown')
            problem_id = str(item.get('leetcode_id', ''))
            doc.add_heading(f"Problem {idx + 1}", level=1)
            
            table = doc.add_table(rows=6, cols=2)
            table.style = 'Table Grid'
            
            # Header Row
            hdr_cells = table.rows[0].cells
            hdr_cells[0].text = 'Field'
            hdr_cells[1].text = 'Details'
            
            # Problem ID Row
            row_1 = table.rows[1].cells
            row_1[0].text = 'Problem ID'
            row_1[1].text = problem_id
            
            # Problem Name Row
            row_2 = table.rows[2].cells
            row_2[0].text = 'Problem Name'
            row_2[1].text = title
            
            # Difficulty Row
            row_3 = table.rows[3].cells
            row_3[0].text = 'Difficulty'
            row_3[1].text = item.get('difficulty', 'Unknown')
            
            # Submission Date Row
            row_4 = table.rows[4].cells
            row_4[0].text = 'Submission Date'
            # Look up state for date, default to blank or placeholder if not found
            prob_state_data = self.state_manager._read_state().get(str(assignment_id), {}).get(problem_id, {})
            submission_date = prob_state_data.get("timestamp", "") or datetime.today().strftime('%Y-%m-%d')
            row_4[1].text = submission_date

            # Screenshot Row
            row_5 = table.rows[5].cells
            row_5[0].text = 'Accepted Submission Screenshot'
            possible_paths = [
                os.path.join(self.screenshots_dir, f"assignment_{assignment_id}", f"{problem_id}.png"),
                os.path.join("screenshots", f"assignment_{assignment_id}", f"{problem_id}.png"),
                os.path.join(".local", "screenshots", f"assignment_{assignment_id}", f"{problem_id}.png"),
            ]
            screenshot_path = next((p for p in possible_paths if os.path.exists(p)), None)
            prob_state = prob_state_data.get("state", "")
            if problem_id in self.subscriber_ids or prob_state == "SUBSCRIBER_ONLY":
                row_5[1].text = "SUBSCRIBER ONLY"
            elif screenshot_path:
                paragraph = row_5[1].paragraphs[0]
                run = paragraph.add_run()
                run.add_picture(screenshot_path, width=Inches(4.5))
            else:
                row_5[1].text = "(Paste Screenshot Here)"
                
            doc.add_page_break()

        self._enforce_styles(doc)
        output_path = os.path.join(self.reports_dir, f"{self.prn}_assignment_{assignment_id}.docx")
        doc.save(output_path)
        logger.info(f"Report successfully generated at {output_path}")
        return output_path

    def generate_mock_test_report(self) -> str:
        logger.info(f"Generating Mock Test report...")
        assignment_id = "4"
        try:
            data = self.state_manager.load_manifest(assignment_id)
        except Exception as e:
            logger.error(f"Cannot load manifest for Mock Test: {e}")
            data = []

        doc = Document()
        doc.add_heading(f'Mock Test (Assignment 4) - PRN: {self.prn}', 0)

        # Load user configuration
        config = {}
        config_path = os.path.join(".local", "config.json")
        if os.path.exists(config_path):
            with open(config_path, "r", encoding="utf-8") as f:
                config = json.load(f)

        name = config.get("name", "Unknown")
        prn = config.get("prn", self.prn)
        div = config.get("division", "Unknown")
        batch = config.get("batch", "Unknown")
        username = config.get("username", "")
        profile_link = f"https://leetcode.com/u/{username}/" if username else "https://leetcode.com"

        # ------------------------------------------------------------------
        # 1. Student Information Table on First Page (per Rubrics)
        # ------------------------------------------------------------------
        doc.add_heading('Student Information', level=1)
        student_table = doc.add_table(rows=7, cols=2)
        student_table.style = 'Table Grid'

        student_info = [
            ("Field", "Details"),
            ("Student Name", name),
            ("PRN Number", prn),
            ("Division", div),
            ("Batch", batch),
            ("LeetCode Username", username),
            ("LeetCode Profile Link", profile_link)
        ]
        for r_idx, (fld, val) in enumerate(student_info):
            cells = student_table.rows[r_idx].cells
            cells[0].text = fld
            cells[1].text = val

        doc.add_page_break()

        # ------------------------------------------------------------------
        # 2. Problem-wise Submission Screenshots (per Rubrics)
        # ------------------------------------------------------------------
        for idx, item in enumerate(data):
            title = item.get('title', f'Problem {idx + 1}')
            problem_id = str(item.get('leetcode_id', idx + 1))
            doc.add_heading(f"Problem {idx + 1}", level=1)

            table = doc.add_table(rows=6, cols=2)
            table.style = 'Table Grid'

            # Header Row
            hdr_cells = table.rows[0].cells
            hdr_cells[0].text = 'Field'
            hdr_cells[1].text = 'Details'

            # Problem ID Row
            row_1 = table.rows[1].cells
            row_1[0].text = 'Problem ID'
            row_1[1].text = problem_id

            # Problem Name Row
            row_2 = table.rows[2].cells
            row_2[0].text = 'Problem Name'
            row_2[1].text = title

            # Difficulty Row
            row_3 = table.rows[3].cells
            row_3[0].text = 'Difficulty'
            row_3[1].text = item.get('difficulty', 'Unknown')

            # Submission Date Row
            row_4 = table.rows[4].cells
            row_4[0].text = 'Submission Date'
            prob_state_data = self.state_manager._read_state().get(str(assignment_id), {}).get(problem_id, {})
            submission_date = prob_state_data.get("timestamp", "") or datetime.today().strftime('%Y-%m-%d')
            row_4[1].text = submission_date

            # Screenshot Row
            row_5 = table.rows[5].cells
            row_5[0].text = 'Accepted Submission Screenshot'
            possible_paths = [
                os.path.join(self.screenshots_dir, f"assignment_{assignment_id}", f"{problem_id}.png"),
                os.path.join(self.screenshots_dir, f"assignment_{assignment_id}", f"{idx + 1}.png"),
                os.path.join("screenshots", f"assignment_{assignment_id}", f"{problem_id}.png"),
                os.path.join("screenshots", f"assignment_{assignment_id}", f"{idx + 1}.png"),
                os.path.join(".local", "screenshots", f"assignment_{assignment_id}", f"{problem_id}.png"),
                os.path.join(".local", "screenshots", f"assignment_{assignment_id}", f"{idx + 1}.png"),
            ]
            screenshot_path = next((p for p in possible_paths if os.path.exists(p)), None)
            prob_state = prob_state_data.get("state", "")
            if problem_id in self.subscriber_ids or prob_state == "SUBSCRIBER_ONLY":
                row_5[1].text = "SUBSCRIBER ONLY"
            elif screenshot_path:
                paragraph = row_5[1].paragraphs[0]
                run = paragraph.add_run()
                run.add_picture(screenshot_path, width=Inches(5.0))
            else:
                row_5[1].text = "(Paste Screenshot Here)"

            doc.add_page_break()

        # Check for any extra mock test screenshots (summary, assessment results, etc.)
        extra_dirs = [
            os.path.join(self.screenshots_dir, f"assignment_{assignment_id}"),
            os.path.join(".local", "screenshots", f"assignment_{assignment_id}"),
            os.path.join("screenshots", f"assignment_{assignment_id}")
        ]
        already_used = {str(item.get('leetcode_id', '')) for item in data} | {str(idx + 1) for idx in range(len(data))}
        found_extras = set()
        for d in extra_dirs:
            if os.path.exists(d):
                for fname in os.listdir(d):
                    if fname.lower().endswith(".png"):
                        base = os.path.splitext(fname)[0]
                        if base not in already_used and base not in found_extras:
                            found_extras.add(base)
                            img_path = os.path.join(d, fname)
                            doc.add_heading(f"Assessment Screenshot - {base.replace('_', ' ').title()}", level=1)
                            p = doc.add_paragraph()
                            run = p.add_run()
                            run.add_picture(img_path, width=Inches(5.5))
                            doc.add_page_break()

        self._enforce_styles(doc)

        # Save to {PRN}_MockTest.docx and {PRN}.docx per rubric instructions
        output_path = os.path.join(self.reports_dir, f"{self.prn}_MockTest.docx")
        alt_output_path = os.path.join(self.reports_dir, f"{self.prn}.docx")
        try:
            doc.save(output_path)
            logger.info(f"Mock Test Report successfully generated at {output_path}")
            try:
                doc.save(alt_output_path)
                logger.info(f"Also saved PRN copy to {alt_output_path}")
            except Exception:
                pass
        except PermissionError:
            raise PermissionError(f"Cannot save report to {output_path}. Please close the document if it is currently open in Word and try again.")
        return output_path

    def _enforce_styles(self, doc):
        from docx.oxml.ns import qn
        for style in doc.styles:
            if hasattr(style, 'font'):
                style.font.name = 'Times New Roman'
                style.font.color.rgb = RGBColor(0, 0, 0)
                if style.font._element is not None:
                    rPr = style.font._element.get_or_add_rPr()
                    rFonts = rPr.get_or_add_rFonts()
                    rFonts.set(qn('w:ascii'), 'Times New Roman')
                    rFonts.set(qn('w:hAnsi'), 'Times New Roman')
                    rFonts.set(qn('w:cs'), 'Times New Roman')

        for p in doc.paragraphs:
            for run in p.runs:
                run.font.name = 'Times New Roman'
                run.font.color.rgb = RGBColor(0, 0, 0)
        
        for table in doc.tables:
            for row in table.rows:
                for cell in row.cells:
                    for p in cell.paragraphs:
                        for run in p.runs:
                            run.font.name = 'Times New Roman'
                            run.font.color.rgb = RGBColor(0, 0, 0)

import os
import json
from docx import Document
from docx.shared import Inches, RGBColor, Pt
from src.state_manager import StateManager
from src.logger import logger

class ReportEngine:
    def __init__(self, prn: str, manifests_dir: str = "solutions_manifests", screenshots_dir: str = None, reports_dir: str = None):
        self.prn = prn
        self.state_manager = StateManager(manifests_dir)
        self.screenshots_dir = os.path.join(".local", "screenshots") if screenshots_dir is None else screenshots_dir
        self.reports_dir = os.path.join(".local", "reports") if reports_dir is None else reports_dir
        os.makedirs(self.reports_dir, exist_ok=True)

    def generate_report(self, assignment_id: str) -> str:
        logger.info(f"Generating report for Assignment {assignment_id}...")
        try:
            data = self.state_manager.load_manifest(assignment_id)
        except Exception as e:
            logger.error(f"Cannot load manifest for report generation: {e}")
            return ""

        doc = Document()
        
        # Enforce Times New Roman and Black color across all styles
        for style_name in ['Normal', 'Title', 'Heading 1', 'Heading 2', 'Heading 3', 'Table Grid']:
            try:
                style = doc.styles[style_name]
                if hasattr(style, 'font'):
                    style.font.name = 'Times New Roman'
                    style.font.color.rgb = RGBColor(0, 0, 0)
            except KeyError:
                pass

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
            doc.add_heading(f"{idx + 1}. {title}", level=1)
            
            # Add table for rubric compliance
            table = doc.add_table(rows=2, cols=2)
            table.style = 'Table Grid'
            hdr_cells = table.rows[0].cells
            hdr_cells[0].text = 'Problem Name'
            hdr_cells[1].text = 'Difficulty'
            
            row_cells = table.rows[1].cells
            row_cells[0].text = title
            row_cells[1].text = item.get('difficulty', 'Unknown')

            doc.add_heading('Submission Screenshot', level=2)
            problem_id = str(item.get('leetcode_id', ''))
            screenshot_path = os.path.join(self.screenshots_dir, f"assignment_{assignment_id}", f"{problem_id}.png")
            prob_state = self.state_manager._read_state().get(str(assignment_id), {}).get(problem_id, {}).get("state", "")
            if prob_state == "SUBSCRIBER_ONLY":
                doc.add_paragraph("SUBSCRIBER ONLY")
            elif os.path.exists(screenshot_path):
                doc.add_picture(screenshot_path, width=Inches(6.0))
                
            doc.add_page_break()

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
            return ""

        doc = Document()
        doc.add_heading(f'Mock Test (Assignment 4) - PRN: {self.prn}', 0)
        
        for idx, item in enumerate(data):
            title = item.get('title', 'Unknown')
            doc.add_heading(f"{idx + 1}. {title}", level=1)
            
            doc.add_heading('Submission Screenshot', level=2)
            problem_id = str(item.get('leetcode_id', ''))
            screenshot_path = os.path.join(self.screenshots_dir, f"assignment_{assignment_id}", f"{problem_id}.png")
            if os.path.exists(screenshot_path):
                doc.add_picture(screenshot_path, width=Inches(6.0))
                
            doc.add_page_break()

        output_path = os.path.join(self.reports_dir, f"{self.prn}_MockTest.docx")
        try:
            doc.save(output_path)
            logger.info(f"Mock Test Report successfully generated at {output_path}")
        except PermissionError:
            raise PermissionError(f"Cannot save report to {output_path}. Please close the document if it is currently open in Word and try again.")
        return output_path

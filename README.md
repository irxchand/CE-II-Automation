# Career Essentials LeetCode Automation System 

## Overview
The Career Essentials LeetCode Automation System is a highly robust, interactive tool designed to completely automate the repetitive process of executing LeetCode solutions, capturing verified screenshots, and compiling rubric-compliant Word (DOCX) reports. 

By automating navigation, execution, and documentation, this system ensures 100% compliance with assignment rubrics while reducing manual documentation time to zero.

## Features 
- **Interactive Menu UI**: A sleek, easy-to-use terminal interface to manage configuration, automation, and reporting without complex CLI arguments.
- **Customizable Output Locations**: Easily configure where your screenshots and reports are saved (e.g. directly into your git cloned repository).
- **Automated Execution**: Iterates through manifest files, navigating to each problem and safely injecting solutions.
- **Deterministic Capture**: Automatically captures screenshots upon successful problem acceptance.
- **State Persistence**: Crash-recoverable local state ensures you never have to re-run successful problems.
- **Automated Reporting**: Instantly generates your final `[PRN].docx` files ready for submission.

## Setup Instructions 

### Prerequisites
- Python 3.10+
- Google Chrome (or compatible Chromium browser)

### Installation
1. Clone the repository to your local machine.
2. Install the required Python packages:
   ```bash
   pip install -r requirements.txt
   ```
3. **Run the one-time setup** (enables auto-pull & notifies the repo owner):
   ```bash
   python setup.py
   ```
   This registers a background task that automatically pulls the latest code every minute — no manual steps needed after this.
   
   To remove auto-pull later: `python setup.py --uninstall`

## Usage 

Launch the interactive menu by running:
```bash
python main.py
```

You will be greeted with the Interactive Menu:

```
╭───────────────────────────────────────╮
│ Career Essentials LeetCode Automation │
│ Interactive Menu                      │
╰───────────────────────────────────────╯
  1. Configure User Identity
  2. Run Browser Automation
  3. Generate Report
  4. Exit
```

### Option 1: Configure User Identity 
Before running your first assignment, configure your identity metadata and output locations. This ensures your Word documents are generated with the correct headers and files go to the right place.

*Note: The first time you run this and save your config, the system will automatically create a hidden `.local/` directory to store your `config.json` and persistent tracking state.*

You will be prompted to enter:
- Full Name
- PRN
- Division
- Batch
- LeetCode Username
- **Screenshots Directory**: Defaults to `screenshots` in your repository root. This is where `assignment_X/` folders will be created to store your `.png` captures.
- **Reports Directory**: Defaults to `reports` in your repository root. This is where the final `.docx` reports will be generated.

### Option 2: Run Browser Automation 
Select this option to begin solving a specific Assignment (1-4). 
- *The system will launch a browser for interactive login. Once logged in, it will automatically begin processing.*
- *This option exclusively focuses on solving problems and capturing screenshots. It will **not** generate the final report.*

### Option 3: Generate Report 
Select this option once your browser automation is completely finished. It will compile all the captured screenshots and problem statuses into a formatted Microsoft Word (`.docx`) file for submission.

## Architecture & State 
The system is built with a **Local-First** philosophy. All operations happen on your machine. State is persisted locally. If the automation is interrupted, restarting it will resume exactly from the last unverified problem.

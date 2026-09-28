import json
import re

file_path = 'solutions_manifests/assignment_1.json'
with open(file_path, 'r', encoding='utf-8') as f:
    data = json.load(f)

for problem in data:
    # 2877 to 2891 are the Pandas problems
    if 2877 <= problem.get('leetcode_id', 0) <= 2891:
        # The user said "PANDAS IS NO OPTION IT IS IN THE CODE, FIX IT"
        # So we change language back to Python (which is the default anyway if we just delete it)
        # We will delete 'language' so it defaults to Python, or explicitly set it
        problem['language'] = 'Python3' 
        
        # We must fix the wrong URLs! We can just delete 'url' so orchestrator regenerates it.
        if 'url' in problem:
            del problem['url']

with open(file_path, 'w', encoding='utf-8') as f:
    json.dump(data, f, indent=4)

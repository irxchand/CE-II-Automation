import json
import os
from typing import Dict, Any, List
from src.logger import logger

class StateManager:
    def __init__(self, manifests_dir: str = "solutions_manifests", local_dir: str = ".local"):
        self.manifests_dir = manifests_dir
        self.local_dir = local_dir
        self.state_file = os.path.join(self.local_dir, "state.json")
        
        if not os.path.exists(self.local_dir):
            os.makedirs(self.local_dir)
            
        if not os.path.exists(self.state_file):
            self._write_state({})

    def _read_state(self) -> Dict[str, Any]:
        try:
            with open(self.state_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return {}

    def _write_state(self, state_data: Dict[str, Any]):
        tmp_file = self.state_file + ".tmp"
        with open(tmp_file, 'w', encoding='utf-8') as f:
            json.dump(state_data, f, indent=4)
        # Atomic file replacement
        os.replace(tmp_file, self.state_file)

    def get_manifest_path(self, assignment_id: str) -> str:
        return os.path.join(self.manifests_dir, f"assignment_{assignment_id}.json")

    def load_manifest(self, assignment_id: str) -> List[Dict[str, Any]]:
        path = self.get_manifest_path(assignment_id)
        if not os.path.exists(path):
            logger.error(f"Manifest for assignment {assignment_id} not found at {path}")
            raise FileNotFoundError(f"Manifest for assignment {assignment_id} not found at {path}")
            
        with open(path, 'r', encoding='utf-8') as f:
            manifest_data = json.load(f)
            
        # Merge static manifest with dynamic local state tracker
        state_data = self._read_state()
        assign_state = state_data.get(str(assignment_id), {})
        
        for item in manifest_data:
            l_id = str(item.get('leetcode_id', ''))
            if l_id in assign_state:
                item['state'] = assign_state[l_id].get('state', item.get('state', 'PENDING'))
                if 'solution_code' in assign_state[l_id]:
                    item['solution_code'] = assign_state[l_id]['solution_code']
                if 'difficulty' in assign_state[l_id]:
                    item['difficulty'] = assign_state[l_id]['difficulty']
            else:
                item['state'] = item.get('state', 'PENDING')
                
        return manifest_data

    def update_problem_state(self, assignment_id: str, leetcode_id: int, state: str, solution_code: str = None) -> None:
        """
        Updates the FSM tracker in .local/state.json using an atomic swap algorithm.
        This prevents file corruption and protects the original source manifests.
        """
        try:
            state_data = self._read_state()
            assign_id_str = str(assignment_id)
            if assign_id_str not in state_data:
                state_data[assign_id_str] = {}
                
            l_id_str = str(leetcode_id)
            if l_id_str not in state_data[assign_id_str]:
                state_data[assign_id_str][l_id_str] = {}
                
            state_data[assign_id_str][l_id_str]['state'] = state
            if solution_code is not None:
                state_data[assign_id_str][l_id_str]['solution_code'] = solution_code
                
            self._write_state(state_data)
            logger.info(f"Updated state for LeetCode ID {leetcode_id} in assignment {assignment_id} to '{state}'.")
            
        except Exception as e:
            logger.error(f"Failed to update problem state: {e}")
            raise

    def update_problem_difficulty(self, assignment_id: str, leetcode_id: int, difficulty: str) -> None:
        """Store the scraped difficulty in the state tracker."""
        try:
            state_data = self._read_state()
            assign_id_str = str(assignment_id)
            if assign_id_str not in state_data:
                state_data[assign_id_str] = {}
                
            l_id_str = str(leetcode_id)
            if l_id_str not in state_data[assign_id_str]:
                state_data[assign_id_str][l_id_str] = {}
                
            state_data[assign_id_str][l_id_str]['difficulty'] = difficulty
                
            self._write_state(state_data)
            logger.info(f"Updated difficulty for LeetCode ID {leetcode_id} to '{difficulty}'.")
            
            # Also update the static manifest directly
            manifest_path = self.get_manifest_path(assignment_id)
            if os.path.exists(manifest_path):
                with open(manifest_path, 'r', encoding='utf-8') as f:
                    manifest_data = json.load(f)
                
                updated = False
                for item in manifest_data:
                    if str(item.get('leetcode_id')) == str(leetcode_id):
                        if item.get('difficulty') != difficulty:
                            item['difficulty'] = difficulty
                            updated = True
                        break
                
                if updated:
                    # Write to temporary file first for atomic swap
                    tmp_manifest = f"{manifest_path}.tmp"
                    with open(tmp_manifest, 'w', encoding='utf-8') as f:
                        json.dump(manifest_data, f, indent=4)
                    os.replace(tmp_manifest, manifest_path)
                    logger.info(f"Persisted difficulty to manifest {manifest_path}")

        except Exception as e:
            logger.error(f"Failed to update difficulty for problem {leetcode_id}: {e}")
            raise

import json
import os
import random
import time
from app.config import config
from app.services.comfyui.client import ComfyUIClient
from app.db import models
from app.utils import to_web_path

class ComfyRunner:
    def __init__(self):
        self.client = ComfyUIClient()
        self.workflows_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "workflows")

    def _load_workflow(self, filename):
        with open(os.path.join(self.workflows_dir, filename), 'r', encoding='utf-8') as f:
            return json.load(f)

    def run_gen_base(self, task: models.Task, callback=None, cancel_check_func=None):
        """
        Runs the GEN_BASE workflow (txt2img).
        callback: function(event_type, data)
        cancel_check_func: function() -> bool
        """
        player = task.player
        workflow = self._load_workflow("wf_base_character.json")
        
        # Parse inputs from task payload
        payload = {}
        if task.payload_json:
            try:
                payload = json.loads(task.payload_json)
            except:
                pass
                
        width = payload.get("width", 1024)
        height = payload.get("height", 768)
        batch_size = 1
        
        # Seed logic: if 0 or missing, random; else use provided
        seed = payload.get("seed", 264590)
        if seed == 0:
            seed = random.randint(1, 9999999999)
        
        # 6.3 Replace fields
        # - Pos prompt: id="91" -> inputs.value
        # - Neg prompt: id="92:7" -> inputs.text (Wait, check node type, usually CLIPTextEncode is inputs.text, Primitive is inputs.value)
        #   The user said: id="92:7" -> inputs.text. I will follow instructions.
        # - Resolution: id="92:58" -> inputs.width / inputs.height
        # - Sampler: id="92:3" -> inputs.seed ...
        # - SaveImage: id="90" -> inputs.filename_prefix
        
        # Important: The user provided node IDs like "92:7". This implies group nodes or specific complex IDs? 
        # Usually ComfyUI IDs are strings like "1", "2". "92:7" suggests maybe a Group Node or the user is looking at a specific UI representation.
        # Since I don't have the actual JSON, I must rely on the user's IDs. 
        # However, "92:7" is not a standard top-level node ID format usually (unless it's nested).
        # But I will use them as keys in the dictionary.
        
        # NOTE: If the workflow was exported as API format, the IDs are keys in the JSON object.
        
        # Helper to safely set input
        def set_input(node_id, field, value):
            if node_id in workflow:
                if 'inputs' not in workflow[node_id]:
                    workflow[node_id]['inputs'] = {}
                workflow[node_id]['inputs'][field] = value
            else:
                print(f"Warning: Node {node_id} not found in workflow")

        # 1. Positive Prompt
        # Check if style_pos is provided in payload (passed via task.payload_json or injected via arguments?)
        # TaskManager doesn't modify payload_json for style injection. 
        # But we can look up project style? ComfyRunner shouldn't do DB lookups.
        # TaskManager should have passed it.
        # Let's see... TaskManager calls run_gen_base(task, ...).
        # We can access task.player.project.style inside run_gen_base!
        
        style = task.player.project.style
        style_pos = style.style_pos if style else ""
        style_neg = style.style_neg if style else ""
        
        # Combine Style + Player Prompt
        # Requirement: "所有给 Qwen / Wan2.2 的提示词，画风只能来自项目 preset"
        # Does this mean ONLY style preset? No, "画风只能来自..." implies style dictates the vibe.
        # Player prompt provides subject details.
        # So we concatenate: Style Prefix + Player Description
        
        final_pos = f"{style_pos}\n{player.prompt_pos or ''}"
        final_neg = f"{style_neg}\n{player.prompt_neg or ''}"
        
        set_input("91", "value", final_pos)
        
        # 2. Negative Prompt
        set_input("92:7", "text", final_neg)
        
        # 3. Resolution
        set_input("92:58", "width", width)
        set_input("92:58", "height", height)
        set_input("92:58", "batch_size", batch_size)
        
        # 4. Sampler
        set_input("92:3", "seed", seed)
        # Other sampler params could be set here
        
        # 5. SaveImage Prefix
        # Format: {task_id}_base
        filename_prefix = f"{task.id}_base"
        set_input("90", "filename_prefix", filename_prefix)

        # --- Debug Logging for ComfyUI API ---
        print("\n" + "="*60)
        print(f" [ComfyUI API Request] Task: {task.task_type} | ID: {task.id}")
        print(f" Workflow File: wf_base_character.json")
        print("-" * 60)
        print(" [Node 91] Positive Prompt")
        print(f"  -> value: {final_pos[:100]}...")
        print("-" * 30)
        print(" [Node 92:7] Negative Prompt")
        print(f"  -> text: {final_neg[:100]}...")
        print("-" * 30)
        print(" [Node 92:58] Resolution")
        print(f"  -> width: {width}, height: {height}")
        print("-" * 30)
        print(" [Node 92:3] Sampler")
        print(f"  -> seed: {seed}")
        print("="*60 + "\n")
        # -------------------------------------

        # Submit
        print(f"Submitting GEN_BASE task {task.id} to ComfyUI...")
        response = self.client.queue_prompt(workflow)
        prompt_id = response['prompt_id']
        
        # Wait
        print(f"Waiting for task {task.id} (prompt_id: {prompt_id})...")
        
        def internal_callback(event, data):
            if callback:
                callback(event, data)
                
        history = self.client.wait_for_completion(prompt_id, callback=internal_callback, cancel_check_func=cancel_check_func)
        
        # Download and Organize
        # Target: output/<project_code>/players/<player_id>_<player_name>/base/
        project_code = task.project.project_code
        player_folder_name = f"{player.id}_{player.player_name}"
        save_dir = os.path.join(config.OUTPUT_DIR, project_code, "players", player_folder_name, "base")
        
        print(f"Downloading outputs to {save_dir}...")
        results = self.client.download_outputs(history, save_dir)
        
        # Find the result image
        # Assuming node "90" produced the image
        if "90" in results and results["90"]:
            # Get the first image path relative to project root or static mount
            abs_path = results["90"][0]
            # Convert to relative path for DB: "output/..."
            # We mounted /output to config.OUTPUT_DIR
            # So the URL path should be output/project_code/...
            
            # The physical path is abs_path.
            # config.OUTPUT_DIR is x:\...\output
            # We want the path relative to the app root (kt_ai_studio) to serve it via StaticFiles?
            # Actually, we mounted /output to the physical OUTPUT_DIR.
            # So the web path is output/project_code/players/...
            
            rel_path = os.path.relpath(abs_path, os.path.dirname(config.OUTPUT_DIR))
            # rel_path is like "output\project\..."
            # Normalize to forward slashes
            rel_path = rel_path.replace("\\", "/")
            
            return {"base_image_path": rel_path}
        else:
            raise Exception("No image output found from node 90")

    def run_gen_scene_base(self, task: models.Task, callback=None, cancel_check_func=None):
        """
        Runs the GEN_SCENE_BASE workflow (txt2img).
        Reuses wf_base_character.json but with Scene prompts.
        """
        scene = task.scene
        workflow = self._load_workflow("wf_base_character.json")
        
        # Parse inputs
        payload = {}
        if task.payload_json:
            try:
                payload = json.loads(task.payload_json)
            except:
                pass
                
        width = payload.get("width", 1024)
        height = payload.get("height", 768)
        batch_size = 1
        
        seed = payload.get("seed", 264590)
        if seed == 0:
            seed = random.randint(1, 9999999999)
        
        def set_input(node_id, field, value):
            if node_id in workflow:
                if 'inputs' not in workflow[node_id]:
                    workflow[node_id]['inputs'] = {}
                workflow[node_id]['inputs'][field] = value
            else:
                print(f"Warning: Node {node_id} not found in workflow")

        # 1. Prompts
        # Project Style
        # Requirement: "style_pos + \n + scene.prompt_pos"
        # Since scene.prompt_pos is generated with style awareness, maybe we just use it?
        # But instructions say: "style_pos + \n + scene.prompt_pos"
        # Let's do as instructed.
        
        # We need to fetch the style object again?
        # Task object has scene which has style_id.
        # But we can access scene.project.style if not snapshotted?
        # Or we can assume task payload or DB logic handled it.
        # Let's use scene.project.style (current style) or scene.style_id?
        # Scene creation bound style_id.
        # Ideally we fetch that style. But scene.project.style is easier.
        # Let's assume project style is what we want (Project Lock).
        
        style = scene.project.style
        style_pos = style.style_pos if style else ""
        style_neg = style.style_neg if style else ""
        
        # System 补强 NEG
        # Note: LLM logic already appends mandatory negatives in normalize_scene_negative_prompt?
        # Wait, normalize_scene_negative_prompt does append mandatory negatives.
        # But the Requirement 7.2 says: "style_neg + \n + scene.prompt_neg + \n + 系统补强neg"
        # If `scene.prompt_neg` already contains style_neg and system_neg (from normalize function), then we might double add.
        # Let's check `normalize_scene_negative_prompt` in openai_provider.py.
        # It adds style_neg, raw_neg, and mandatory_neg.
        # So `scene.prompt_neg` ALREADY contains everything!
        # So for NEG, we just use `scene.prompt_neg`.
        
        final_pos = f"{style_pos}\n{scene.prompt_pos}"
        final_neg = scene.prompt_neg # Already normalized and merged
        
        set_input("91", "value", final_pos)
        set_input("92:7", "text", final_neg)
        
        # 2. Resolution & Seed
        set_input("92:58", "width", width)
        set_input("92:58", "height", height)
        set_input("92:58", "batch_size", batch_size)
        set_input("92:3", "seed", seed)
        
        # 3. SaveImage Prefix
        filename_prefix = f"{task.id}_scene_base"
        set_input("90", "filename_prefix", filename_prefix)

        # --- Debug Logging for ComfyUI API ---
        print("\n" + "="*60)
        print(f" [ComfyUI API Request] Task: {task.task_type} | ID: {task.id}")
        print(f" Workflow File: wf_base_character.json")
        print("-" * 60)
        print(" [Node 91] Positive Prompt")
        print(f"  -> value: {final_pos[:100]}...")
        print("-" * 30)
        print(" [Node 92:7] Negative Prompt")
        print(f"  -> text: {final_neg[:100]}...")
        print("-" * 30)
        print(" [Node 92:58] Resolution")
        print(f"  -> width: {width}, height: {height}")
        print("-" * 30)
        print(" [Node 92:3] Sampler")
        print(f"  -> seed: {seed}")
        print("="*60 + "\n")
        # -------------------------------------

        # Submit
        print(f"Submitting GEN_SCENE_BASE task {task.id}...")
        response = self.client.queue_prompt(workflow)
        prompt_id = response['prompt_id']
        
        # Wait
        def internal_callback(event, data):
            if callback:
                callback(event, data)
                
        history = self.client.wait_for_completion(prompt_id, callback=internal_callback, cancel_check_func=cancel_check_func)
        
        # Download
        # Target: output/<project_code>/scenes/<scene_id>_<scene_name>/base/
        project_code = task.project.project_code
        scene_folder_name = f"{scene.id}_{scene.name}"
        save_dir = os.path.join(config.OUTPUT_DIR, project_code, "scenes", scene_folder_name, "base")
        
        print(f"Downloading outputs to {save_dir}...")
        results = self.client.download_outputs(history, save_dir)
        
        if "90" in results and results["90"]:
            abs_path = results["90"][0]
            rel_path = os.path.relpath(abs_path, os.path.dirname(config.OUTPUT_DIR)).replace("\\", "/")
            return {"base_image_path": rel_path}
        else:
            raise Exception("No image output found from node 90")

    def run_gen_8views(self, task: models.Task, callback=None, cancel_check_func=None):
        """
        Runs the GEN_8VIEWS workflow (img2img/edit).
        """
        player = task.player
        if not player.base_image_path:
            raise ValueError("Player has no base image for 8-view generation")
            
        workflow = self._load_workflow("wf_8views.json")
        
        # Parse inputs from task payload
        payload = {}
        if task.payload_json:
            try:
                payload = json.loads(task.payload_json)
            except:
                pass
                
        # Default defaults
        width = payload.get("width", 1024)
        height = payload.get("height", 768)
        
        # Seed logic
        seed = payload.get("seed", 264590)
        if seed == 0:
            seed = random.randint(1, 9999999999)
        
        # Calculate megapixels for ImageScaleToTotalPixels
        megapixels = round((width * height) / 1000000.0, 2)
        # Ensure at least 0.1 to avoid errors
        if megapixels < 0.1: 
            megapixels = 0.1
        
        # Upload Base Image
        # Construct full path to base image
        # player.base_image_path is like "output/project/..." or "/output/project/..."
        # We need absolute path
        # If it starts with /output or output, we need to handle it.
        # But wait, player.base_image_path is stored as RELATIVE path usually "output/..."
        # BUT config.OUTPUT_DIR is absolute.
        
        rel_path = player.base_image_path
        if rel_path.startswith("/"):
            rel_path = rel_path[1:]
            
        # If rel_path starts with "output/", we need to know where "output" is relative to.
        # Our convention: config.OUTPUT_DIR is ".../output".
        # So if DB says "output/project/...", and config.OUTPUT_DIR is ".../output",
        # then joining os.path.dirname(config.OUTPUT_DIR) with "output/project/..." works.
        
        base_image_abs_path = os.path.join(os.path.dirname(config.OUTPUT_DIR), rel_path)
        
        if not os.path.exists(base_image_abs_path):
             # Try joining with config.OUTPUT_DIR directly if path doesn't start with output?
             # No, standard is output/...
             print(f"Error: Base image not found at {base_image_abs_path}")
             raise ValueError(f"Base image not found: {base_image_abs_path}")
        
        print(f"Uploading base image {base_image_abs_path}...")
        upload_resp = self.client.upload_image(base_image_abs_path)
        uploaded_filename = upload_resp["name"]
        
        # Helper
        def set_input(node_id, field, value):
            if node_id in workflow:
                if 'inputs' not in workflow[node_id]:
                    workflow[node_id]['inputs'] = {}
                workflow[node_id]['inputs'][field] = value
            else:
                print(f"Warning: Node {node_id} not found in workflow")

        # 1. Input Image
        set_input("25", "image", uploaded_filename)
        
        # 2. Prompts (66-73) -> inputs.value
        # User said "Default no change", but we can set them if needed. 
        # For now, skipping text replacement as per "can be default".
        
        # 3. SaveImage Prefixes (31, 34, 36, 38, 41, 43, 45, 47)
        # BUG FIX: Use a unique random string in prefix to avoid ComfyUI filename increments (00001, 00002)
        # when re-running tasks with same ID.
        import string
        rand_str = ''.join(random.choices(string.ascii_lowercase + string.digits, k=6))
        
        view_map = {
            "31": "close",
            "34": "wide",
            "36": "right45",
            "38": "right90",
            "41": "aerial",
            "43": "low",
            "45": "left45",
            "47": "left90"
        }
        
        # KSamplers IDs for 8 views
        ksampler_ids = [
            "65:33:21", # close
            "65:35:21", # wide
            "65:37:21", # right45
            "65:39:21", # right90
            "65:42:21", # aerial
            "65:44:21", # low
            "65:46:21", # left45
            "65:40:21"  # left90 (Note: view_map has 47 for left90 save node, but KSampler ID logic matches JSON)
        ]
        
        # ImageScaler IDs for 8 views
        scaler_ids = [
            "65:33:28",
            "65:35:28",
            "65:37:28",
            "65:39:28",
            "65:42:28",
            "65:44:28",
            "65:46:28",
            "65:40:28"
        ]
        
        # Set Seed for all KSamplers
        for kid in ksampler_ids:
            set_input(kid, "seed", seed)
            
        # Set Megapixels for all Scalers
        for sid in scaler_ids:
            set_input(sid, "megapixels", megapixels)
        
        # We need this mapping for the callback to know which prefix to look for
        # filename_prefix = f"{task.id}_{rand_str}_{view_name}"
        prefix_map = {} 
        
        for node_id, view_name in view_map.items():
            prefix = f"{task.id}_{rand_str}_{view_name}"
            prefix_map[node_id] = prefix
            set_input(node_id, "filename_prefix", prefix)
            
        # 4. Seed (Optional)
        # ALREADY SET ABOVE
        
        # --- Debug Logging for ComfyUI API ---
        print("\n" + "="*60)
        print(f" [ComfyUI API Request] Task: {task.task_type} | ID: {task.id}")
        print(f" Workflow File: wf_8views.json")
        print("-" * 60)
        print(" [Node 25] LoadImage (Base)")
        print(f"  -> image: {uploaded_filename}")
        print("-" * 30)
        print(" [KSamplers] Seed")
        print(f"  -> seed: {seed}")
        print("-" * 30)
        print(" [ImageScalers] Megapixels")
        print(f"  -> megapixels: {megapixels}")
        print("="*60 + "\n")
        # -------------------------------------

        # Submit
        print(f"Submitting GEN_8VIEWS task {task.id}...")
        response = self.client.queue_prompt(workflow)
        prompt_id = response['prompt_id']
        
        # Prepare for incremental updates
        views_json = {}
        project_code = task.project.project_code
        player_folder_name = f"{player.id}_{player.player_name}"
        save_dir = os.path.join(config.OUTPUT_DIR, project_code, "players", player_folder_name, "views")
        os.makedirs(save_dir, exist_ok=True)
        
        # State for progress calculation
        self.views_done = 0
        self.last_progress = 0
        total_views = len(view_map)
        start_time = time.time()
        view_times = [] # List of durations for each view
        last_view_finish_time = start_time
        
        def internal_callback(event, data):
            # Pass progress through
            if event == 'progress':
                # Calculate global progress
                val = data.get('value', 0)
                max_val = data.get('max', 1)
                
                if max_val > 0:
                    node_progress = val / max_val
                    # Global = (views_done + node_progress) / total_views
                    global_p = ((self.views_done + node_progress) / total_views) * 100
                    global_p = min(max(global_p, 0), 99)
                    
                    if callback:
                        # Estimate ETA
                        # If we have completed views, use their average
                        # Else use elapsed time and progress?
                        
                        eta = 0
                        elapsed = time.time() - start_time
                        if self.views_done > 0:
                            avg_time = elapsed / self.views_done
                            remaining_views = total_views - self.views_done - node_progress
                            eta = int(avg_time * remaining_views)
                        elif global_p > 5: # Wait until 5% to guess
                            # Estimate based on linear progress
                            total_estimated = elapsed / (global_p / 100)
                            eta = int(total_estimated - elapsed)
                        
                        # Use time-based progress if ETA is available and reasonable
                        # REVERTED: Time-based progress was confusing user when ETA was inaccurate.
                        # New Strategy: Hybrid Step-Based
                        # Global = (views_done + node_progress) / total_views
                        
                        # node_progress comes from KSampler step/total_steps (0.0 to 1.0)
                        # views_done is integer 0..7
                        # So this is mathematically accurate to the generation process.
                        
                        global_p = ((self.views_done + node_progress) / total_views) * 100
                            
                        # Prevent regression
                        global_p = max(global_p, self.last_progress)
                        global_p = min(max(global_p, 0), 99)
                        self.last_progress = global_p
                        
                        callback('progress', {
                            'value': global_p, 
                            'max': 100, 
                            'eta': eta,
                            'views_done': self.views_done,
                            'total_views': total_views
                        })
                    
            elif event == 'node_finished':
                node_id = data.get('node_id')
                if node_id in view_map:
                    self.views_done += 1
                    view_name = view_map[node_id]
                    
                    now = time.time()
                    duration = now - last_view_finish_time
                    view_times.append(duration)
                    # last_view_finish_time = now # Wait, parallel execution? ComfyUI usually sequential for this workflow.
                    
                    print(f"Node {node_id} ({view_name}) finished. Attempting direct download...")
                    
                    try:
                        prefix = prefix_map[node_id]
                        expected_filename = f"{prefix}_00001_.png"
                        image_data = self.client.get_image(expected_filename, "", "output")
                        
                        save_path = os.path.join(save_dir, expected_filename)
                        with open(save_path, 'wb') as f:
                            f.write(image_data)
                        
                        rel_path = os.path.relpath(save_path, os.path.dirname(config.OUTPUT_DIR)).replace("\\", "/")
                        views_json[view_name] = rel_path
                        
                        # Recalculate ETA based on completed views
                        elapsed = time.time() - start_time
                        avg_time = elapsed / self.views_done
                        remaining = total_views - self.views_done
                        eta = int(avg_time * remaining)
                        
                        # Recalculate Progress (Step-based)
                        # We just finished a view, so node_progress is effectively 0 for the next one
                        global_p = (self.views_done / total_views) * 100
                            
                        global_p = min(max(global_p, 0), 99)
                        
                        if callback:
                            callback('view_generated', {
                                'view_name': view_name, 
                                'path': rel_path,
                                'views_json': views_json
                            })
                            
                            callback('progress', {
                                'value': global_p, 
                                'max': 100, 
                                'eta': eta,
                                'views_done': self.views_done,
                                'total_views': total_views
                            })
                            
                    except Exception as e:
                        print(f"Error handling incremental update for node {node_id}: {e}")

        # Wait
        history = self.client.wait_for_completion(prompt_id, callback=internal_callback, cancel_check_func=cancel_check_func)
        
        # Download (Final sweep to ensure everything is caught)
        
        results = self.client.download_outputs(history, save_dir)
        
        # Map results to views
        views_json = {}
        for node_id, paths in results.items():
            if node_id in view_map and paths:
                view_name = view_map[node_id]
                # Rel path
                abs_path = paths[0]
                rel_path = os.path.relpath(abs_path, os.path.dirname(config.OUTPUT_DIR)).replace("\\", "/")
                views_json[view_name] = rel_path
                
        return {"views_json": views_json}

    def run_scene_merge(self, task, current_img_path, player_img_path, prompt_pos, prompt_neg, seed, callback=None, cancel_check_func=None):
        """
        Run Qwen Image Edit for Scene Merge.
        """
        workflow = self._load_workflow("qwen_Image_edit_subgraphed.json")
        
        # Upload images
        if not os.path.exists(current_img_path):
            raise ValueError(f"Scene image not found: {current_img_path}")
        if not os.path.exists(player_img_path):
            raise ValueError(f"Player image not found: {player_img_path}")
            
        print(f"Uploading scene image {current_img_path}...")
        resp1 = self.client.upload_image(current_img_path)
        scene_filename = resp1["name"]
        
        print(f"Uploading player image {player_img_path}...")
        resp2 = self.client.upload_image(player_img_path)
        player_filename = resp2["name"]
        
        def set_input(node_id, field, value):
            if node_id in workflow:
                if 'inputs' not in workflow[node_id]:
                    workflow[node_id]['inputs'] = {}
                workflow[node_id]['inputs'][field] = value
            else:
                print(f"Warning: Node {node_id} not found in workflow")
        
        # Node 78: Load Image (Scene / Background)
        set_input("78", "image", scene_filename)
        
        # Node 120: Load Image (Character / Foreground)
        set_input("120", "image", player_filename)
        
        # Node 115: Prompts and Seed
        set_input("115:111", "prompt", prompt_pos)
        set_input("115:110", "prompt", prompt_neg)
        set_input("115:3", "seed", seed)
        
        # Node 60: Save Image (Filename Prefix)
        filename_prefix = f"scenemerge_{task.id}"
        set_input("60", "filename_prefix", filename_prefix)
        
        # --- Debug Logging for ComfyUI API ---
        print("\n" + "="*60)
        print(f" [ComfyUI API Request] Task: {task.task_type} | ID: {task.id}")
        print(f" Workflow File: qwen_Image_edit_subgraphed.json")
        print("-" * 60)
        print(" [Node 78] LoadImage (Scene/Background)")
        print(f"  -> image: {scene_filename}")
        print("-" * 30)
        print(" [Node 120] LoadImage (Character/Foreground)")
        print(f"  -> image: {player_filename}")
        print("-" * 30)
        print(" [Node 115] Qwen Image Edit (Prompts)")
        print(f"  -> prompt_pos (115:111): {prompt_pos}")
        print(f"  -> prompt_neg (115:110): {prompt_neg}")
        print(f"  -> seed (115:3): {seed}")
        print("-" * 30)
        print(" [Node 60] SaveImage (Filename Prefix)")
        print(f"  -> filename_prefix: {filename_prefix}")
        print("="*60 + "\n")
        # -------------------------------------
        
        # Submit
        print(f"Submitting GEN_SCENE_MERGE task {task.id}...")
        response = self.client.queue_prompt(workflow)
        prompt_id = response['prompt_id']
        
        # Wait
        def internal_callback(event, data):
            if callback:
                callback(event, data)
                
        history = self.client.wait_for_completion(prompt_id, callback=internal_callback, cancel_check_func=cancel_check_func)
        
        # Download
        # Target: output/<project_code>/scenes/<scene_id>_<scene_name>/merge/
        scene = task.scene
        project_code = task.project.project_code
        # Sanitize scene name for folder
        import re
        safe_scene_name = re.sub(r'[\\/*?:"<>|]', "", scene.name)
        scene_folder_name = f"{scene.id}_{safe_scene_name}"
        
        save_dir = os.path.join(config.OUTPUT_DIR, project_code, "scenes", scene_folder_name, "merge")
        os.makedirs(save_dir, exist_ok=True)
        
        print(f"Downloading outputs to {save_dir}...")
        results = self.client.download_outputs(history, save_dir)
        
        # Find result
        if results and "60" in results:
            # We expect image from SaveImage node 60.
            paths = results["60"]
            if paths:
                # Return the first image found
                abs_path = paths[0]
                
                # Check if it matches our prefix to avoid picking up random files
                filename = os.path.basename(abs_path)
                if not filename.startswith(filename_prefix):
                    # Fallback search in directory if ComfyUI returned weird path
                    # Or try to find the correct file
                    candidates = [f for f in os.listdir(save_dir) if f.startswith(filename_prefix) and f.endswith(".png")]
                    if candidates:
                        # Pick latest
                        candidates.sort(key=lambda x: os.path.getmtime(os.path.join(save_dir, x)), reverse=True)
                        abs_path = os.path.join(save_dir, candidates[0])
                
                # Use os.path.relpath based on config.OUTPUT_DIR parent
                base_dir = os.path.dirname(config.OUTPUT_DIR)
                rel_path = os.path.relpath(abs_path, base_dir).replace("\\", "/")
                return {"merge_image_path": rel_path}
            
        raise Exception("No image output found for Scene Merge from Node 60")

    def run_gen_video(self, task: models.Task, callback=None, cancel_check_func=None):
        """
        Runs the GEN_VIDEO workflow (Wan2.2 Image-to-Video).
        """
        video = task.video
        scene = video.scene
        
        workflow = self._load_workflow("video_wan2_2_14B_i2v.json")
        
        # Parse inputs
        payload = {}
        if task.payload_json:
            try:
                payload = json.loads(task.payload_json)
            except:
                pass
                
        # Parameters
        width = payload.get("width", 640)
        height = payload.get("height", 640)
        length = payload.get("length", 81)
        fps = payload.get("fps", 16)
        seed = payload.get("seed", 0)
        # Remove the random seed logic if seed is 0, because 0 is a valid seed? 
        # Actually user wants to use the configured seed.
        # But if the payload explicitly sends 0, does it mean "random" or "seed 0"?
        # In other functions (gen_base), 0 means random.
        # But here the user says: "why isn't it 264590 as configured in web page? It used a random value."
        # This implies the web page sent 264590, but the backend ignored it or overwrote it?
        # Or maybe the web page sent 0 (if user didn't change it and default was 0 before)?
        # Wait, if the user configured 264590 in the UI, payload.get("seed") should be 264590.
        # If payload.get("seed") is 264590, the condition `if seed == 0` is false, so it should use 264590.
        # The log shows "Noise Seed -> noise_seed: 3667400612", which looks like a random int.
        # This means `seed` was 0 when entering the condition.
        # So payload.get("seed") returned 0.
        # Why did the payload contain 0?
        # Maybe the UI form didn't submit the updated value?
        # Or the task payload wasn't constructed correctly?
        # The task is created in videos.py: generate_video_route.
        # It creates a Task. But does it put the video parameters into task.payload_json?
        # Let's check videos.py.
        
        if seed == 0:
            seed = random.randint(1, 9999999999)
            
        # Prompts (from DB or payload?)
        # Task payload usually contains the prompts generated by LLM step
        prompt_pos = payload.get("prompt_pos", video.prompt_pos or "")
        prompt_neg = payload.get("prompt_neg", video.prompt_neg or "")
        
        # Input Image (Scene Merged Image)
        if not scene.merged_image_path:
            raise ValueError("Scene has no merged image for video generation")
            
        # Resolve absolute path
        # scene.merged_image_path is relative like "output/project/..."
        base_dir = os.path.dirname(config.OUTPUT_DIR)
        input_image_abs_path = os.path.join(base_dir, scene.merged_image_path)
        
        if not os.path.exists(input_image_abs_path):
            raise ValueError(f"Input image not found: {input_image_abs_path}")
            
        print(f"Uploading input image {input_image_abs_path}...")
        resp = self.client.upload_image(input_image_abs_path)
        uploaded_filename = resp["name"]
        
        def set_input(node_id, field, value):
            if node_id in workflow:
                if 'inputs' not in workflow[node_id]:
                    workflow[node_id]['inputs'] = {}
                workflow[node_id]['inputs'][field] = value
            else:
                print(f"Warning: Node {node_id} not found in workflow")
                
        # 1. Input Image (Node 97)
        set_input("97", "image", uploaded_filename)
        
        # 2. Prompts
        set_input("93", "text", prompt_pos)
        set_input("89", "text", prompt_neg)
        
        # 3. Parameters (Node 98: WanImageToVideo)
        set_input("98", "width", width)
        set_input("98", "height", height)
        set_input("98", "length", length)
        
        # 4. FPS (Node 94: CreateVideo) - wait, check JSON
        # Node 94 inputs: fps, images
        set_input("94", "fps", fps)
        
        # 5. Seed (Node 86: KSamplerAdvanced - Noise Seed)
        set_input("86", "noise_seed", seed)
        # Node 85 also has noise_seed, usually they should match or be controlled?
        # User instructions: "86的 noise_seed，可以在页面配置后..."
        # Just 86 mentioned. But usually sampler chain needs consistent seed or handled by Comfy.
        # Let's set 85 too if it exists and has seed, just in case, or stick to 86 as requested.
        # The provided JSON has 85 noise_seed=0 (fixed?) and 86 noise_seed=264590.
        # I will set 86 as requested.
        
        # 6. Save Video (Node 108)
        filename_prefix = f"video_{task.id}"
        set_input("108", "filename_prefix", filename_prefix)
        
        # --- Debug Logging for ComfyUI API ---
        print("\n" + "="*60)
        print(f" [ComfyUI API Request] Task: {task.task_type} | ID: {task.id}")
        print(f" Workflow File: video_wan2_2_14B_i2v.json")
        print("-" * 60)
        print(" [Node 97] LoadImage")
        print(f"  -> image: {uploaded_filename}")
        print("-" * 30)
        print(" [Node 93] Positive Prompt")
        print(f"  -> text: {prompt_pos[:100]}...")
        print("-" * 30)
        print(" [Node 89] Negative Prompt")
        print(f"  -> text: {prompt_neg[:100]}...")
        print("-" * 30)
        print(" [Node 98] WanImageToVideo Params")
        print(f"  -> width: {width}, height: {height}, length: {length}")
        print("-" * 30)
        print(" [Node 94] FPS")
        print(f"  -> fps: {fps}")
        print("-" * 30)
        print(" [Node 86] Noise Seed")
        print(f"  -> noise_seed: {seed}")
        print("-" * 30)
        print(" [Node 108] Filename Prefix")
        print(f"  -> filename_prefix: {filename_prefix}")
        print("="*60 + "\n")
        # -------------------------------------
        
        # Submit
        print(f"Submitting GEN_VIDEO task {task.id}...")
        response = self.client.queue_prompt(workflow)
        prompt_id = response['prompt_id']
        
        # Wait
        def internal_callback(event, data):
            if callback:
                callback(event, data)
                
        history = self.client.wait_for_completion(prompt_id, callback=internal_callback, cancel_check_func=cancel_check_func)
        
        # Download
        # Target: output/<project_code>/scenes/<scene_id>_<scene_name>/video/
        project_code = task.project.project_code
        # Sanitize scene name
        import re
        safe_scene_name = re.sub(r'[\\/*?:"<>|]', "", scene.name)
        scene_folder_name = f"{scene.id}_{safe_scene_name}"
        
        save_dir = os.path.join(config.OUTPUT_DIR, project_code, "scenes", scene_folder_name, "video")
        os.makedirs(save_dir, exist_ok=True)
        
        print(f"Downloading outputs to {save_dir}...")
        results = self.client.download_outputs(history, save_dir)
        
        # Find video output (Node 108)
        if "108" in results and results["108"]:
            abs_path = results["108"][0] # First video
            
            # Rel path
            base_dir = os.path.dirname(config.OUTPUT_DIR)
            rel_path = os.path.relpath(abs_path, base_dir).replace("\\", "/")
            return {"video_path": rel_path}
            
        raise Exception("No video output found from Node 108")

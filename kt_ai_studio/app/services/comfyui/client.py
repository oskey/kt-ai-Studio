import json
import urllib.request
import urllib.parse
import websocket # websocket-client
import uuid
import time
import os
import shutil
from app.config import config

class ComfyUIClient:
    def __init__(self, base_url=config.COMFYUI_BASE_URL, ws_url=config.COMFYUI_WS_URL):
        self.base_url = base_url
        self.ws_url = ws_url
        self.client_id = str(uuid.uuid4())

    def queue_prompt(self, prompt_workflow):
        p = {"prompt": prompt_workflow, "client_id": self.client_id}
        data = json.dumps(p).encode('utf-8')
        req = urllib.request.Request(f"{self.base_url}/prompt", data=data)
        return json.loads(urllib.request.urlopen(req).read())

    def interrupt(self):
        """Interrupts the current execution in ComfyUI"""
        req = urllib.request.Request(f"{self.base_url}/interrupt", method='POST')
        try:
            # Set timeout to prevent hanging if ComfyUI is unresponsive
            # Reduced to 2s for faster UI response
            urllib.request.urlopen(req, timeout=2)
            return True
        except Exception as e:
            print(f"Failed to interrupt ComfyUI: {e}")
            return False

    def get_history(self, prompt_id):
        with urllib.request.urlopen(f"{self.base_url}/history/{prompt_id}") as response:
            return json.loads(response.read())

    def get_image(self, filename, subfolder, folder_type):
        data = {"filename": filename, "subfolder": subfolder, "type": folder_type}
        url_values = urllib.parse.urlencode(data)
        with urllib.request.urlopen(f"{self.base_url}/view?{url_values}") as response:
            return response.read()

    def upload_image(self, file_path, overwrite=True):
        """Uploads an image to ComfyUI input directory"""
        url = f"{self.base_url}/upload/image"
        
        # Use requests or httpx for multipart upload would be easier, 
        # but sticking to standard lib or what we have. 
        # Actually requirements has httpx. Let's switch to httpx for this method or everything if possible.
        # But for now, simple multipart via requests/httpx
        import httpx
        
        filename = os.path.basename(file_path)
        with open(file_path, 'rb') as f:
            files = {'image': (filename, f, 'image/png')}
            data = {'overwrite': str(overwrite).lower()}
            response = httpx.post(url, files=files, data=data)
            
        if response.status_code == 200:
            return response.json() # Returns {"name": "filename.png", ...}
        else:
            raise Exception(f"Failed to upload image: {response.text}")

    def wait_for_completion(self, prompt_id, timeout=600, callback=None, cancel_check_func=None):
        """
        Connects to WS and waits for execution to finish.
        Returns the history/outputs for the prompt_id.
        callback: function(event_type, data)
        cancel_check_func: function() -> bool. If returns True, raises InterruptedError.
        """
        import time
        from websocket import WebSocketException
        
        start_time = time.time()
        last_node = None
        ws = None
        retry_count = 0
        max_retries = 3
        
        while True:
            # Check for external cancellation
            if cancel_check_func and cancel_check_func():
                if ws:
                    try:
                        ws.close()
                    except:
                        pass
                raise InterruptedError("Task execution cancelled by manager")

            try:
                if not ws:
                    ws = websocket.WebSocket()
                    ws.connect(f"{self.ws_url}?clientId={self.client_id}")
                    # print(f"WS Connected for prompt {prompt_id}")
                
                # Check timeout
                if time.time() - start_time > timeout:
                    raise TimeoutError("ComfyUI generation timed out")
                
                # Receive with a small timeout to allow checking loop condition
                ws.settimeout(5) 
                try:
                    out = ws.recv()
                except websocket.WebSocketTimeoutException:
                    # Just a read timeout, check overall timeout and continue
                    continue
                
                if isinstance(out, str):
                    message = json.loads(out)
                    
                    if message['type'] == 'executing':
                        data = message['data']
                        if data['prompt_id'] == prompt_id:
                            new_node = data['node']
                            
                            if last_node is not None and new_node != last_node:
                                if callback:
                                    callback('node_finished', {'node_id': last_node, 'prompt_id': prompt_id})
                            
                            last_node = new_node
                            
                            if new_node is None:
                                # Execution done
                                break
                                
                    elif message['type'] == 'progress':
                        data = message['data']
                        if callback:
                            callback('progress', data)
                            
            except (ConnectionResetError, WebSocketException, OSError) as e:
                print(f"WS Connection Error: {e}. Retrying ({retry_count}/{max_retries})...")
                if ws:
                    try:
                        ws.close()
                    except:
                        pass
                ws = None
                retry_count += 1
                if retry_count > max_retries:
                    raise e
                time.sleep(2) # Wait before retry
                
            except Exception as e:
                # Unexpected error
                if ws:
                    ws.close()
                raise e
            
        if ws:
            ws.close()
            
        return self.get_history(prompt_id)[prompt_id]

    def download_outputs(self, history, output_dir_base):
        """
        Downloads images from history to local output_dir.
        Returns a dict of {node_id: [local_paths]} or similar.
        """
        outputs = history.get('outputs', {})
        results = {}
        
        # Ensure output directory exists (修复 Errno 2)
        os.makedirs(output_dir_base, exist_ok=True)
        
        for node_id, node_output in outputs.items():
            if 'images' in node_output:
                saved_paths = []
                for image in node_output['images']:
                    filename = image['filename']
                    subfolder = image['subfolder']
                    folder_type = image['type']
                    
                    image_data = self.get_image(filename, subfolder, folder_type)
                    
                    # Construct local path
                    # We might want to organize by task or project here, but the caller should handle the final move.
                    # For now, just save to a temp or direct location.
                    # Actually, let's save to the provided output_dir_base
                    
                    # 修复路径问题：使用 os.path.join 确保跨平台兼容
                    save_path = os.path.join(output_dir_base, filename)
                    
                    with open(save_path, 'wb') as f:
                        f.write(image_data)
                    
                    saved_paths.append(save_path)
                results[node_id] = saved_paths
                
        return results

import subprocess
from typing import Optional
import psutil
import httpx
import time
import json
import  urllib.request
import shlex
from typing import Dict, List, Optional, Any
import os
from pathlib import Path
from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict
import threading


class LocalModel(BaseModel):
    name: str
    display_name: str
    path: str
    mmproj: str | None = None  
    server_path: str
    special_arguments: str | None = None
    engine: str

class AppSettings(BaseSettings):
    MODELS: list[LocalModel]
    pdf_directory: str
    # This line triggers the automatic JSON decoder!
    model_config = SettingsConfigDict(env_file=".env")



class VramModelManager:
    def __init__(self, MODEL_LIST, backend_port: int = 8081):
        self.backend_port = backend_port
        self.process: Optional[subprocess.Popen] = None
        self.current_model_id: Optional[str] = None
        self.model_list = MODEL_LIST
        self._sweep_zombie_processes() #Kill anything leftover from before
        self.launch_lock = threading.Lock()

    def _sweep_zombie_processes(self):
        """Hunts down and kills any orphaned llama-server processes from previous crashed runs."""
        print("[VRAM] Performing cold-boot sweep for zombie servers...")
        zombies_killed = 0
        
        for proc in psutil.process_iter(['pid', 'name']):
            try:
                # Check if the executable name contains 'llama-server'
                if 'llama-server' in proc.info['name'].lower():
                    print(f"[VRAM] Found orphaned server (PID: {proc.info['pid']}). Terminating...")
                    proc.kill()
                    zombies_killed += 1
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                pass
                
        if zombies_killed > 0:
            # Give the OS a second to flush the VRAM and release the port
            time.sleep(2.0)
            print("[VRAM] Zombie sweep complete. Port and VRAM cleared.")
        else:
            print("[VRAM] No zombies found. Coast is clear.")

    def stop_active_server(self):
        """Forcefully terminates the running server and blocks until the port/VRAM is free."""
        if not self.process:
            return

        print(f"[VRAM] Evicting '{self.current_model_id}' (PID: {self.process.pid})...")
        try:
            parent = psutil.Process(self.process.pid)
            children = parent.children(recursive=True)
            
            # Kill everything down the tree
            for child in children:
                child.kill()
            parent.kill()

            # Block until OS confirms cleanup to avoid socket collision or VRAM overlap
            psutil.wait_procs([parent] + children, timeout=10)
            print("[VRAM] OS process tree cleared.")
        except psutil.NoSuchProcess:
            pass
        finally:
            self.process = None
            self.current_model_id = None

    def start_server(self, model_display_name: str):
        matching_model = next((m for m in self.model_list.MODELS if m.display_name == model_display_name), None)
        with self.launch_lock:
            try:
                req = urllib.request.Request(f"http://127.0.0.1:{self.backend_port}/v1/models")
                with urllib.request.urlopen(req, timeout=10) as response:
                    if response.getcode() == 200 and self.current_model_id == model_display_name:
                        print("[LOG] Engine is already running. Bypassing launch.")
                        return
            except Exception as e:
                print(f"\n[DIAGNOSTIC] Bypass ping failed! Reason: {type(e).__name__} - {str(e)}")
                pass

            self.stop_active_server()

            if not matching_model:
                raise ValueError(f"Model with display name '{model_display_name}' not found.")
            if not matching_model.server_path:
                raise ValueError(f"Model '{model_display_name}' is missing a llama_server_path in the configuration.")

            args_list = []
            if matching_model.special_arguments:
                args_list = shlex.split(matching_model.special_arguments)

            if matching_model.engine == "llama.cpp":
                cmd = [
                    matching_model.server_path,
                    "-m", matching_model.path,
                    "--port", str(self.backend_port),
                    "--alias", matching_model.name,
                ] + args_list
            elif matching_model.engine == "Fast_flow":
                cmd = [
                    "flm", "serve", matching_model.name,
                    "-p", str(self.backend_port),
                    "--ctx-len", "131072"
                ]

            if matching_model.engine == "Fast_flow":
                env = os.environ.copy()
                env["FLM_DISABLE_UPDATE_CHECK"] = "1"
            else:
                env = None

            print("Launching model")

            # FIX: isolate the child in its own process group on Windows so Ctrl+C
            # (CTRL_C_EVENT) in the console doesn't hit it directly. We now own its
            # entire lifecycle explicitly via stop_active_server()/psutil, instead of
            # racing against the OS delivering the same signal to both processes.
            popen_kwargs = {}
            if os.name == "nt":
                popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP

            self.process = subprocess.Popen(
                cmd,
                stdin=subprocess.DEVNULL,
                stdout=None,
                stderr=None,
                text=True,
                env=env,
                **popen_kwargs
            )

            print("[LOG] Holding proxy pipeline. Waiting for FastFlowLM NPU allocation...")
            api_base = f"http://127.0.0.1:{self.backend_port}"
            print(f"[VRAM] Allocating memory for {matching_model.display_name}. This may take a few minutes...", flush=True)
            print(f"[Lifecycle] Launching: {' '.join(cmd)}", flush=True)

            for _ in range(120):
                try:
                    req = urllib.request.Request(f"{api_base}/v1/models")
                    with urllib.request.urlopen(req, timeout=10) as response:
                        if response.getcode() == 200:
                            data = json.loads(response.read().decode())
                            if any(m.get("id") == matching_model.name for m in data.get("data", [])):
                                print("[LOG] FastFlowLM reporting healthy! Releasing proxy hold.")
                                self.current_model_id = matching_model.display_name
                                break
                except Exception:
                    pass

                time.sleep(1)
                self.current_model_id = matching_model.display_name
                
            

#Makes the list of Models avalible
MODEL_LIST = AppSettings()
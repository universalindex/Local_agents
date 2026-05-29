import subprocess
from typing import Optional
import psutil
import httpx
import time
import shlex
import os
from pathlib import Path
from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict

class LocalModel(BaseModel):
    name: str
    display_name: str
    path: str
    mmproj: str | None = None  
    llama_server_path: str
    special_arguments: str | None = None

class AppSettings(BaseSettings):
    MODELS: list[LocalModel]

    # This line triggers the automatic JSON decoder!
    model_config = SettingsConfigDict(env_file=".env")



class VramModelManager:
    def __init__(self, MODEL_LIST, backend_port: int = 8081):
        self.backend_port = backend_port
        self.process: Optional[subprocess.Popen] = None
        self.current_model_id: Optional[str] = None
        self.model_list = MODEL_LIST
        self._sweep_zombie_processes() #Kill anything leftover from before

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
        """Spawns a new server instance on the shared, unified port."""
        # Enforce single-server port availability by cleaning up first
        if self.current_model_id == model_display_name:
            return
        else:
            self.stop_active_server()
            #Extract model path, name and mmproj from the model list based on the display name
            matching_model = next((m for m in self.model_list.MODELS if m.display_name == model_display_name), None)
            if not matching_model:
                raise ValueError(f"Model with display name '{model_display_name}' not found.") #Shouldn't happen since the UI only sends valid names.
            if not matching_model.llama_server_path:
                raise ValueError(f"Model '{model_display_name}' is missing a llama_server_path in the configuration.") #Also shouldn't happen
            args_list = shlex.split(matching_model.special_arguments)

            cmd = [
                matching_model.llama_server_path,
                "-m", matching_model.path,
                "--port", str(self.backend_port)
            ] + args_list
            #Run the actuall commands so the server spins up
            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            
            self.current_model_id = matching_model.display_name
            print(f"[Lifecycle] Launching: {' '.join(cmd)}")
            
            health_url = f"http://127.0.0.1:{self.backend_port}/health"
            start_time = time.time()
            
            print(f"[VRAM] Allocating memory for {matching_model.display_name}. This may take a few minutes...")

            while True:
                try:
                    with httpx.Client() as client:
                        if client.get(health_url, timeout=1.0).status_code == 200:
                            # THE FIX 2: Add a highly visible success banner
                            print("\n" + "="*50)
                            print(f"✅ [SUCCESS] {matching_model.display_name} is fully loaded and ready!")
                            print("="*50 + "\n")
                            break
                except httpx.RequestError:
                    pass
                except KeyboardInterrupt:
                    print("\n[ABORT] User pressed Ctrl+C. Shutting down server...")
                    self.stop_active_server()
                    raise

                # THE FIX 3: Increase the timeout limit to 300 seconds (5 minutes)
                if time.time() - start_time > 300:
                    self.stop_active_server()
                    raise RuntimeError(f"Model {matching_model.display_name} failed to initialize within 300s.")
                time.sleep(1.0)

#Makes the list of Models avalible
MODEL_LIST = AppSettings()
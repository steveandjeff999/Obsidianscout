import os
import tkinter as tk
from tkinter import ttk, messagebox
import threading

class AuditorApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Herod Corp - Directory Auditor")
        self.root.geometry("400x250")

        # Define ignore lists
        self.ignore_dirs = {'__pycache__', '.git', '.vscode', '.idea', 'configs', 'venv', 'node_modules' }
        self.ignore_exts = {
            '.pyc', '.pyo', '.pyd', '.png', '.jpg', '.jpeg', '.gif', '.db', '.log', '.zip', '.tar', '.gz', '.7z',
            '.bmp', '.ico', '.svg', '.mp4', '.mov', '.exe', '.bin', '.obj'
        }

        # UI Components
        self.label = tk.Label(root, text="Press Start to Audit Directory", font=("Arial", 10))
        self.label.pack(pady=10)

        self.progress = ttk.Progressbar(root, orient="horizontal", length=300, mode="determinate")
        self.progress.pack(pady=20)

        self.start_button = tk.Button(root, text="Start Audit", command=self.start_thread)
        self.start_button.pack(pady=10)

        self.status_label = tk.Label(root, text="", fg="blue")
        self.status_label.pack(pady=5)

    def start_thread(self):
        # Run in a separate thread so the GUI doesn't freeze
        self.start_button.config(state="disabled")
        threading.Thread(target=self.run_audit, daemon=True).start()

    def run_audit(self):
        current_dir = os.getcwd()
        all_files = []
        
        # Initial scan to count total files for progress bar
        for root, dirs, files in os.walk(current_dir):
            dirs[:] = [d for d in dirs if d not in self.ignore_dirs]
            for file in files:
                if os.path.splitext(file)[1].lower() not in self.ignore_exts:
                    all_files.append(os.path.join(root, file))

        total_files_count = len(all_files)
        if total_files_count == 0:
            messagebox.showinfo("Done", "No valid files found.")
            self.start_button.config(state="normal")
            return

        self.progress["maximum"] = total_files_count
        
        total_lines = 0
        total_chars = 0
        processed_count = 0

        for file_path in all_files:
            try:
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                    total_lines += len(content.splitlines())
                    total_chars += len(content)
            except Exception:
                pass
            
            processed_count += 1
            self.progress["value"] = processed_count
            self.status_label.config(text=f"Scanning: {processed_count}/{total_files_count}")
            self.root.update_idletasks()

        # Final Results
        result_msg = (
            f"Audit Complete!\n\n"
            f"Files: {total_files_count}\n"
            f"Lines: {total_lines}\n"
            f"Characters: {total_chars}"
        )
        messagebox.showinfo("Results", result_msg)
        self.start_button.config(state="normal")
        self.status_label.config(text="Scan Finished")

if __name__ == "__main__":
    root = tk.Tk()
    app = AuditorApp(root)
    root.mainloop()
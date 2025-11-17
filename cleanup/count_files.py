import tkinter as tk
from tkinter import filedialog, scrolledtext
import os
import threading # <-- New import for multi-threading

# List of folder names to exclude from the recursive count.
EXCLUDED_FOLDERS = [
    '.git',
    '__pycache__',
    'venv',
    'node_modules',
]

def count_file_stats(folder_path, excluded_folders):
    """
    Recursively counts the total number of files, lines, and characters.
    This function remains the heavy lifting worker.
    """
    total_files = 0
    total_lines = 0
    total_chars = 0
    
    for dirpath, dirnames, filenames in os.walk(folder_path, topdown=True):
        
        # Modify dirnames in place to prevent os.walk from entering excluded directories.
        dirnames[:] = [d for d in dirnames if d not in excluded_folders]

        for filename in filenames:
            file_path = os.path.join(dirpath, filename)
            total_files += 1
            
            # Use a robust try/except/finally block for safety
            try:
                # 1. Byte Count (File Length) - Use 'rb' for all files
                with open(file_path, 'rb') as f:
                    content_bytes = f.read()
                    char_count = len(content_bytes)
                    total_chars += char_count
                
                # 2. Line Count - Only works for text-like files, ignore errors
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    line_count = sum(1 for line in f)
                    total_lines += line_count

            except Exception:
                # Silently fail if file cannot be processed (e.g., permissions)
                pass

    return total_files, total_lines, total_chars

# ====================================================================

class FileCounterApp:
    def __init__(self, master):
        self.master = master
        master.title("Responsive File and Line Counter")
        
        # --- GUI Setup ---
        
        # Folder Path Label
        self.path_label = tk.Label(master, text="Selected Folder: None", wraplength=450, justify=tk.LEFT)
        self.path_label.pack(pady=10, padx=10, fill='x')

        # Status Label (NEW)
        self.status_label = tk.Label(master, text="Ready", fg='green')
        self.status_label.pack(padx=10)
        
        # Exclusions Label
        exclusion_text = "Excluded folders: " + ", ".join(EXCLUDED_FOLDERS)
        tk.Label(master, text=exclusion_text, fg='gray', wraplength=450, justify=tk.LEFT).pack(padx=10)

        # Select Folder Button
        self.select_button = tk.Button(master, text="Select Folder to Analyze", command=self.select_folder)
        self.select_button.pack(pady=15)
        
        # Result Text Area
        self.result_text = scrolledtext.ScrolledText(master, height=12, width=60, state='disabled', wrap=tk.WORD, font=('Courier', 10))
        self.result_text.pack(pady=10, padx=10, fill='both', expand=True)

        self.selected_folder = ""
        self.is_counting = False # State flag to prevent running multiple times

    def select_folder(self):
        """Opens a dialog to select a directory and prepares for count."""
        if self.is_counting:
            return # Don't allow a new selection while counting
            
        folder = filedialog.askdirectory()
        if folder:
            self.selected_folder = folder
            self.path_label.config(text=f"Selected Folder: {self.selected_folder}")
            self.result_text.config(state='normal'); self.result_text.delete(1.0, tk.END); self.result_text.config(state='disabled')
            self.start_counting()

    def start_counting(self):
        """Starts the counting function in a separate thread."""
        self.is_counting = True
        self.status_label.config(text="Processing... please wait.", fg='orange')
        self.select_button.config(state='disabled') # Disable button during work
        
        # Create a new thread for the heavy lifting
        self.worker_thread = threading.Thread(target=self.run_count_threaded)
        self.worker_thread.start()
        
        # Check on the thread periodically to update the GUI when it's done
        self.master.after(100, self.check_thread)

    def run_count_threaded(self):
        """The function executed in the separate thread."""
        try:
            # This is the heavy lifting call
            self.results = count_file_stats(self.selected_folder, EXCLUDED_FOLDERS)
        except Exception as e:
            self.results = None
            print(f"Error in worker thread: {e}")

    def check_thread(self):
        """Checks if the worker thread is finished and updates the GUI."""
        if self.worker_thread.is_alive():
            # Thread is still working, check again in 100ms
            self.master.after(100, self.check_thread)
        else:
            # Thread is done, process and display the results
            self.is_counting = False
            self.select_button.config(state='normal')
            self.status_label.config(text="Finished!", fg='green')
            
            if self.results:
                self.display_results(*self.results)
            else:
                self.display_results(0, 0, 0, error="An unexpected error occurred during counting.")


    def display_results(self, files, lines, chars, error=None):
        """Helper function to format and update the result text widget."""
        
        # Format the numbers for readability
        formatted_files = f"{files:,}"
        formatted_lines = f"{lines:,}"
        formatted_chars = f"{chars:,}"

        output = f"""
--- Analysis Complete ---

Total Files Found:   {formatted_files}
Total Lines of Text: {formatted_lines}
Total File Lengths:  {formatted_chars} characters (bytes)

(Files inside excluded folders were skipped.)
-------------------------
        """
        if error:
             output = f"ERROR: {error}\n{'-' * 25}\n" + output

        self.result_text.config(state='normal')
        self.result_text.delete(1.0, tk.END)
        self.result_text.insert(tk.END, output)
        self.result_text.config(state='disabled')

# --- Main Execution ---
if __name__ == "__main__":
    root = tk.Tk()
    app = FileCounterApp(root)
    root.mainloop()
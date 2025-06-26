import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog
import boto3
import os
import threading
import configparser
from pathlib import Path
import sys
import darkdetect
import pywinstyles
import sv_ttk

def apply_theme_to_titlebar(root):
    if sys.platform == "win32":
        version = sys.getwindowsversion()

        if version.major == 10 and version.build >= 22000:
            # Set the title bar color to the background color on Windows 11 for better appearance
            pywinstyles.change_header_color(root, "#1c1c1c" if sv_ttk.get_theme() == "dark" else "#fafafa")
        elif version.major == 10:
            pywinstyles.apply_style(root, "dark" if sv_ttk.get_theme() == "dark" else "normal")
            # A hacky way to update the title bar's color on Windows 10 (it doesn't update instantly like on Windows 11)
            root.wm_attributes("-alpha", 0.99)
            root.wm_attributes("-alpha", 1)

class S3Manager:
    def __init__(self, root):
        self.root = root
        self.root.title("AWS S3 Manager")
        self.root.iconbitmap(Path(__file__).parent / 's3.ico')
        self.root.geometry("1000x700")
        sv_ttk.set_theme(darkdetect.theme())
        apply_theme_to_titlebar(self.root)

        # AWS configuration paths
        self.aws_dir = Path.home() / '.aws'
        self.credentials_file = self.aws_dir / 'credentials'
        self.config_file = self.aws_dir / 'config'
        
        self.profiles = {}
        self.current_profile = None
        self.s3_client = None
        self.current_bucket = None
        self.current_prefix = ""
        
        self.load_aws_profiles()
        self.setup_gui()
            
    def load_aws_profiles(self):
        """Load AWS profiles from ~/.aws/credentials and ~/.aws/config"""
        self.profiles = {}
        
        try:
            # Load credentials
            credentials_config = configparser.ConfigParser()
            if self.credentials_file.exists():
                credentials_config.read(self.credentials_file)
            
            # Load config
            aws_config = configparser.ConfigParser()
            if self.config_file.exists():
                aws_config.read(self.config_file)
            
            # Get all profile names from both files
            profile_names = set()
            
            # From credentials file
            for section in credentials_config.sections():
                profile_names.add(section)
            
            # From config file (remove 'profile ' prefix)
            for section in aws_config.sections():
                if section.startswith('profile '):
                    profile_names.add(section[8:])  # Remove 'profile ' prefix
                elif section == 'default':
                    profile_names.add(section)
            
            # Build profile data
            for profile_name in profile_names:
                profile_data = {}
                
                # Get credentials
                if credentials_config.has_section(profile_name):
                    cred_section = credentials_config[profile_name]
                    if 'aws_access_key_id' in cred_section:
                        profile_data['aws_access_key_id'] = cred_section['aws_access_key_id']
                    if 'aws_secret_access_key' in cred_section:
                        profile_data['aws_secret_access_key'] = cred_section['aws_secret_access_key']
                    if 'aws_session_token' in cred_section:
                        profile_data['aws_session_token'] = cred_section['aws_session_token']
                
                # Get config settings
                config_section_name = f'profile {profile_name}' if profile_name != 'default' else 'default'
                if aws_config.has_section(config_section_name):
                    config_section = aws_config[config_section_name]
                    if 'region' in config_section:
                        profile_data['region'] = config_section['region']
                    if 'output' in config_section:
                        profile_data['output'] = config_section['output']
                    if 'role_arn' in config_section:
                        profile_data['role_arn'] = config_section['role_arn']
                    if 'source_profile' in config_section:
                        profile_data['source_profile'] = config_section['source_profile']
                
                # Set default region if not specified
                if 'region' not in profile_data:
                    profile_data['region'] = 'us-east-1'
                
                self.profiles[profile_name] = profile_data
            
            if not self.profiles:
                CustomDialog(self.root, "No Profiles Found", 
                    "No AWS profiles found in ~/.aws/credentials or ~/.aws/config.\n"
                    "Please configure your AWS credentials first using 'aws configure' command.")
                
        except Exception as e:
            CustomDialog(self.root, "Error", f"Failed to load AWS profiles: {str(e)}", "error")
            self.profiles = {}
    
    def refresh_profiles(self):
        """Refresh AWS profiles from config files"""
        self.load_aws_profiles()
        self.update_profile_combo()
        if self.current_profile and self.current_profile not in self.profiles:
            self.current_profile = None
            self.s3_client = None
            self.status_var.set("Profile no longer available")
            self.bucket_combo['values'] = []
            self.tree.delete(*self.tree.get_children())
    
    def setup_gui(self):
        """Setup the main GUI"""
        # Main frame
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        # Configure grid weights
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        main_frame.columnconfigure(1, weight=1)
        main_frame.rowconfigure(2, weight=1)
        
        # Profile management section
        profile_frame = ttk.LabelFrame(main_frame, text="AWS Profile", padding="5")
        profile_frame.grid(row=0, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(0, 10))
        profile_frame.columnconfigure(1, weight=1)
        
        ttk.Label(profile_frame, text="Profile:").grid(row=0, column=0, padx=(0, 5))
        
        self.profile_var = tk.StringVar()
        self.profile_combo = ttk.Combobox(profile_frame, textvariable=self.profile_var, state="readonly")
        self.profile_combo.grid(row=0, column=1, sticky=(tk.W, tk.E), padx=(0, 5))
        self.profile_combo.bind('<<ComboboxSelected>>', self.on_profile_selected)
        
        ttk.Button(profile_frame, text="Refresh Profiles", command=self.refresh_profiles).grid(row=0, column=2, padx=(5, 0))
        ttk.Button(profile_frame, text="Open AWS Config", command=self.open_aws_config).grid(row=0, column=3, padx=(5, 0))
        
        # Connection status
        self.status_var = tk.StringVar(value="Not connected")
        ttk.Label(profile_frame, textvariable=self.status_var).grid(row=1, column=0, columnspan=4, pady=(5, 0))
        
        # Bucket frame
        bucket_frame = ttk.LabelFrame(main_frame, text="S3 Buckets", padding="5")
        bucket_frame.grid(row=1, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(0, 10))
        bucket_frame.columnconfigure(1, weight=1)
        
        # Search selection

        ttk.Label(bucket_frame, text="Search:").grid(row=0, column=0, padx=(0, 5))
        self.search_var = tk.StringVar()
        self.search_var.trace('w', self.filter_buckets)
        search_entry = ttk.Entry(bucket_frame, textvariable=self.search_var)
        search_entry.grid(row=0, column=1, sticky=(tk.W, tk.E), padx=(0, 5))
        ttk.Button(bucket_frame, text="Clear", command=lambda: self.search_var.set(''), width=7).grid(row=0, column=2, padx=(5, 0))

        # Bucket selection
        ttk.Label(bucket_frame, text="Bucket:", width=7).grid(row=1, column=0, padx=(0, 5))
        
        self.bucket_var = tk.StringVar()
        self.bucket_combo = ttk.Combobox(bucket_frame, textvariable=self.bucket_var, state="readonly")
        self.bucket_combo.grid(row=1, column=1, sticky=(tk.W, tk.E), padx=(0, 5), pady=(5, 0))
        self.bucket_combo.bind('<<ComboboxSelected>>', self.on_bucket_selected)
        
        ttk.Button(bucket_frame, text="Refresh", command=self.refresh_buckets, width=7).grid(row=1, column=2, padx=(5, 0), pady=(5, 0))
        
        # Current path
        self.path_var = tk.StringVar(value="")
        # Path navigation frame
        path_frame = ttk.Frame(bucket_frame)
        path_frame.grid(row=2, column=0, columnspan=3, sticky=(tk.W, tk.E), pady=(5, 0))
        path_frame.columnconfigure(1, weight=1)
        
        ttk.Label(path_frame, text="Path:", width=7).grid(row=0, column=0, padx=(0, 5))
        path_entry = ttk.Entry(path_frame, textvariable=self.path_var, state="readonly")
        path_entry.grid(row=0, column=1, sticky=(tk.W, tk.E), padx=(0, 5))
        
        nav_frame = ttk.Frame(path_frame)
        nav_frame.grid(row=0, column=2)
        ttk.Button(nav_frame, text="↑", command=self.go_up, width=2).pack(side=tk.LEFT, padx=(5, 2))
        ttk.Button(nav_frame, text="🏠", command=self.go_home, width=2).pack(side=tk.LEFT)
        
        # File browser
        browser_frame = ttk.LabelFrame(main_frame, text="Files and Folders", padding="5")
        browser_frame.grid(row=2, column=0, columnspan=2, sticky=(tk.W, tk.E, tk.N, tk.S))
        browser_frame.columnconfigure(0, weight=1)
        browser_frame.rowconfigure(0, weight=1)
        
        # Treeview for file listing
        columns = ('Name', 'Type', 'Size', 'Modified')
        self.tree = ttk.Treeview(browser_frame, columns=columns, show='tree headings')
        self.tree.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        # Configure columns
        self.tree.heading('#0', text='Name')
        self.tree.heading('Name', text='Name')
        self.tree.heading('Type', text='Type')
        self.tree.heading('Size', text='Size')
        self.tree.heading('Modified', text='Modified')
        
        self.tree.column('#0', width=300)
        self.tree.column('Name', width=0, stretch=False)  # Hidden
        self.tree.column('Type', width=80)
        self.tree.column('Size', width=100)
        self.tree.column('Modified', width=150)
        
        # Scrollbar for treeview
        scrollbar = ttk.Scrollbar(browser_frame, orient=tk.VERTICAL, command=self.tree.yview)
        scrollbar.grid(row=0, column=1, sticky=(tk.N, tk.S))
        self.tree.configure(yscrollcommand=scrollbar.set)
        
        # Bind double-click event
        self.tree.bind('<Double-1>', self.on_item_double_click)
        self.tree.bind('<Button-3>', self.on_right_click)  # Right-click context menu
        
        # Action buttons
        action_frame = ttk.Frame(main_frame)
        action_frame.grid(row=3, column=0, columnspan=2, pady=(10, 0))
        
        ttk.Button(action_frame, text="Create Folder", command=self.create_folder).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(action_frame, text="Delete", command=self.delete_item).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(action_frame, text="Download", command=self.download_file).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(action_frame, text="Refresh", command=self.refresh_current_folder).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(action_frame, text="Upload File", command=self.upload_file).pack(side=tk.LEFT, padx=(0, 5))
        
        # Update profile combo
        self.update_profile_combo()
        
        # Auto-select default profile if available
        if 'default' in self.profiles:
            self.profile_var.set('default')
            self.on_profile_selected()
        
        # Create context menu
        self.context_menu = tk.Menu(self.root, tearoff=0)
        self.context_menu.add_command(label="Download", command=self.download_file)
        self.context_menu.add_command(label="Delete", command=self.delete_item)
        self.context_menu.add_separator()
        self.context_menu.add_command(label="Upload File", command=self.upload_file)
        self.context_menu.add_command(label="Create Folder", command=self.create_folder)
        self.context_menu.add_separator()
        self.context_menu.add_command(label="Refresh Profiles", command=self.refresh_profiles)
    
    def update_profile_combo(self):
        """Update the profile combobox with available profiles"""
        profile_names = list(self.profiles.keys())
        self.profile_combo['values'] = profile_names
        if profile_names and not self.profile_var.get():
            self.profile_var.set(profile_names[0])
    
    def open_aws_config(self):
        """Open AWS configuration directory"""
        import subprocess
        import platform
        
        aws_dir = str(self.aws_dir)
        
        try:
            if platform.system() == 'Windows':
                os.startfile(aws_dir)
            elif platform.system() == 'Darwin':  # macOS
                subprocess.run(['open', aws_dir])
            else:  # Linux
                subprocess.run(['xdg-open', aws_dir])
        except Exception as e:
            CustomDialog(self.root, "Error", f"Failed to open AWS config directory: {str(e)}", "error")
    
    def on_profile_selected(self, event=None):
        """Handle profile selection"""
        profile_name = self.profile_var.get()
        if not profile_name or profile_name not in self.profiles:
            return
        
        try:
            profile = self.profiles[profile_name]
            
            # Create session with profile
            session = boto3.Session(profile_name=profile_name)
            self.s3_client = session.client('s3')
            
            # Test connection
            self.s3_client.list_buckets()
            self.status_var.set(f"Connected to profile: {profile_name} (Region: {profile.get('region', 'default')})")
            self.current_profile = profile_name
            self.refresh_buckets()
            
        except Exception as e:
            # Fallback to manual credential creation if session fails
            try:
                profile = self.profiles[profile_name]
                
                # Check if we have required credentials
                if 'aws_access_key_id' not in profile or 'aws_secret_access_key' not in profile:
                    raise Exception("Missing access key or secret key in profile")
                
                client_kwargs = {
                    'aws_access_key_id': profile['aws_access_key_id'],
                    'aws_secret_access_key': profile['aws_secret_access_key'],
                    'region_name': profile.get('region', 'us-east-1')
                }
                
                # Add session token if available (for temporary credentials)
                if 'aws_session_token' in profile:
                    client_kwargs['aws_session_token'] = profile['aws_session_token']
                
                self.s3_client = boto3.client('s3', **client_kwargs)
                
                # Test connection
                self.s3_client.list_buckets()
                self.status_var.set(f"Connected to profile: {profile_name} (Region: {profile.get('region', 'us-east-1')})")
                self.current_profile = profile_name
                self.refresh_buckets()
                
            except Exception as e2:
                CustomDialog(self.root, "Connection Error", 
                    f"Failed to connect with profile '{profile_name}':\n{str(e2)}\n\n"
                    f"Please check your AWS configuration in:\n"
                    f"• {self.credentials_file}\n"
                    f"• {self.config_file}", "error")
                self.status_var.set("Connection failed")
    
    def refresh_buckets(self):
        """Refresh the list of S3 buckets"""
        if not self.s3_client:
            return
        
        try:
            response = self.s3_client.list_buckets()
            self.all_buckets = [bucket['Name'] for bucket in response['Buckets']]
            self.filter_buckets()
            
            if self.current_bucket and self.current_bucket not in self.all_buckets:
                self.current_bucket = None
                self.tree.delete(*self.tree.get_children())
                self.path_var.set("")
                self.current_prefix = ""
            
        except Exception as e:
            messagebox.showerror("Error", f"Failed to list buckets: {str(e)}")
            self.bucket_combo['values'] = []
            self.all_buckets = []

    def go_home(self):
        """Reset to the root of the current bucket and refresh the view"""
        if self.current_bucket:
            self.current_prefix = ""
            self.path_var.set("")
            self.refresh_current_folder()

    def filter_buckets(self, *args):
        """Filter buckets based on search text"""
        if not hasattr(self, 'all_buckets'):
            self.all_buckets = []
            return

        search_text = self.search_var.get().lower()
        filtered_buckets = [bucket for bucket in self.all_buckets if search_text in bucket.lower()]
        self.bucket_combo['values'] = filtered_buckets
    
    def on_bucket_selected(self, event=None):
        """Handle bucket selection"""
        bucket_name = self.bucket_var.get()
        if bucket_name:
            self.current_bucket = bucket_name
            self.current_prefix = ""
            self.refresh_current_folder()
    
    def refresh_current_folder(self):
        """Refresh the current folder contents"""
        if not self.s3_client or not self.current_bucket:
            return
        
        self.tree.delete(*self.tree.get_children())
        
        try:
            # Update path display
            path_display = f"{self.current_bucket}/"
            if self.current_prefix:
                path_display += self.current_prefix
            self.path_var.set(path_display)
            
            # List objects with current prefix
            paginator = self.s3_client.get_paginator('list_objects_v2')
            pages = paginator.paginate(
                Bucket=self.current_bucket,
                Prefix=self.current_prefix,
                Delimiter='/'
            )
            
            folders = set()
            files = []
            
            for page in pages:
                # Add folders (common prefixes)
                for prefix in page.get('CommonPrefixes', []):
                    folder_name = prefix['Prefix'][len(self.current_prefix):].rstrip('/')
                    if folder_name:
                        folders.add(folder_name)
                
                # Add files
                for obj in page.get('Contents', []):
                    key = obj['Key']
                    if key != self.current_prefix and not key.endswith('/'):
                        file_name = key[len(self.current_prefix):]
                        if '/' not in file_name:  # Only direct children
                            files.append({
                                'name': file_name,
                                'size': obj['Size'],
                                'modified': obj['LastModified'],
                                'key': key
                            })
            
            # Add folders to tree
            for folder in sorted(folders):
                self.tree.insert('', 'end', text=f"📁 {folder}", values=(
                    folder, 'Folder', '', ''
                ), tags=('folder',))
            
            # Add files to tree
            for file_info in sorted(files, key=lambda x: x['name']):
                size_str = self.format_size(file_info['size'])
                modified_str = file_info['modified'].strftime('%Y-%m-%d %H:%M:%S')
                self.tree.insert('', 'end', text=f"📄 {file_info['name']}", values=(
                    file_info['name'], 'File', size_str, modified_str
                ), tags=('file',))
                
        except Exception as e:
            messagebox.showerror("Error", f"Failed to refresh folder: {str(e)}")
    
    def format_size(self, size_bytes):
        """Format file size in human readable format"""
        if size_bytes == 0:
            return "0 B"
        
        size_names = ["B", "KB", "MB", "GB", "TB"]
        i = 0
        while size_bytes >= 1024.0 and i < len(size_names) - 1:
            size_bytes /= 1024.0
            i += 1
        
        return f"{size_bytes:.1f} {size_names[i]}"
    
    def on_item_double_click(self, event):
        """Handle double-click on tree item"""
        selection = self.tree.selection()
        if not selection:
            return
        
        item = selection[0]
        values = self.tree.item(item, 'values')
        
        if len(values) > 1:
            if values[1] == 'Folder':
                # Navigate to folder
                folder_name = values[0]
                self.current_prefix += folder_name + '/'
                self.refresh_current_folder()
            elif values[1] == 'File':
                # Download file to temp directory
                file_name = values[0]
                s3_key = self.current_prefix + file_name
                temp_dir = os.path.join(os.path.expanduser('~'), '.s3browser_temp')
                os.makedirs(temp_dir, exist_ok=True)
                temp_path = os.path.join(temp_dir, file_name)
                
                try:
                    self.s3_client.download_file(self.current_bucket, s3_key, temp_path)
                    
                    # Open file with default application
                    if sys.platform == 'win32':
                        os.startfile(temp_path)
                    elif sys.platform == 'darwin':
                        subprocess.run(['open', temp_path])
                    else:
                        subprocess.run(['xdg-open', temp_path])
                    
                    # Monitor file for changes
                    last_modified = os.path.getmtime(temp_path)
                    
                    def check_for_changes():
                        nonlocal last_modified
                        try:
                            current_modified = os.path.getmtime(temp_path)
                            if current_modified > last_modified:
                                # File was modified, ask to upload
                                if messagebox.askyesno('File Changed', 
                                    f'The file {file_name} has been modified. Upload changes to S3?'):
                                    self.s3_client.upload_file(temp_path, self.current_bucket, s3_key)
                                    # delete the temp file after upload
                                    os.remove(temp_path)
                                    CustomDialog(self.root, 'Success', 'File uploaded successfully')
                                    self.refresh_current_folder()
                                last_modified = current_modified
                            self.root.after(1000, check_for_changes)  # Check every second
                        except Exception as e:
                            messagebox.showerror('Error', f'Failed to monitor file: {str(e)}') # File was deleted or other error
                    
                    self.root.after(1000, check_for_changes)
                    
                except Exception as e:
                    messagebox.showerror('Error', f'Failed to open file: {str(e)}')
    
    def on_right_click(self, event):
        """Handle right-click for context menu"""
        item = self.tree.identify_row(event.y)
        if item:
            self.tree.selection_set(item)
            self.context_menu.post(event.x_root, event.y_root)
    
    def go_up(self):
        """Navigate to parent directory"""
        if not self.current_prefix:
            return
        
        # Remove the last folder from prefix
        parts = self.current_prefix.rstrip('/').split('/')
        if len(parts) > 1:
            self.current_prefix = '/'.join(parts[:-1]) + '/'
        else:
            self.current_prefix = ""
        
        self.refresh_current_folder()
    
    def upload_file(self):
        """Upload a file to the current location"""
        if not self.s3_client or not self.current_bucket:
            messagebox.showwarning("Warning", "No bucket selected")
            return
        
        file_path = filedialog.askopenfilename(title="Select file to upload")
        if not file_path:
            return
        
        file_name = os.path.basename(file_path)
        s3_key = self.current_prefix + file_name
        
        try:
            # Show progress dialog
            progress_dialog = ProgressDialog(self.root, "Uploading", f"Uploading {file_name}...")
            
            def upload_thread():
                try:
                    self.s3_client.upload_file(file_path, self.current_bucket, s3_key)
                    self.root.after(0, lambda: [progress_dialog.destroy(),
                                                CustomDialog(self.root, "Success", f"File uploaded: {file_name}"),
                                              self.refresh_current_folder()])
                except Exception as e:
                    self.root.after(0, lambda: [progress_dialog.destroy(),
                                              messagebox.showerror("Error", f"Upload failed: {str(e)}")])
            
            threading.Thread(target=upload_thread, daemon=True).start()
            
        except Exception as e:
            messagebox.showerror("Error", f"Upload failed: {str(e)}")
    
    def download_file(self):
        """Download the selected file"""
        selection = self.tree.selection()
        if not selection:
            messagebox.showwarning("Warning", "No file selected")
            return
        
        item = selection[0]
        values = self.tree.item(item, 'values')
        
        if len(values) < 2 or values[1] != 'File':
            messagebox.showwarning("Warning", "Please select a file to download")
            return
        
        file_name = values[0]
        s3_key = self.current_prefix + file_name
        
        save_path = filedialog.asksaveasfilename(
            title="Save file as",
            initialfile=file_name
        )
        
        if not save_path:
            return
        
        try:
            progress_dialog = ProgressDialog(self.root, "Downloading", f"Downloading {file_name}...")
            
            def download_thread():
                try:
                    self.s3_client.download_file(self.current_bucket, s3_key, save_path)
                    self.root.after(0, lambda: [progress_dialog.destroy(),
                                              CustomDialog(self.root, "Success", f"File downloaded: {file_name}")])
                except Exception as e:
                    self.root.after(0, lambda: [progress_dialog.destroy(),
                                              messagebox.showerror("Error", f"Download failed: {str(e)}")])
            
            threading.Thread(target=download_thread, daemon=True).start()
            
        except Exception as e:
            messagebox.showerror("Error", f"Download failed: {str(e)}")
    
    def create_folder(self):
        """Create a new folder"""
        if not self.s3_client or not self.current_bucket:
            messagebox.showwarning("Warning", "No bucket selected")
            return
        
        folder_name = simpledialog.askstring("Create Folder", "Enter folder name:")
        if not folder_name:
            return
        
        # Clean folder name
        folder_name = folder_name.strip().replace('/', '_')
        if not folder_name:
            messagebox.showwarning("Warning", "Invalid folder name")
            return
        
        s3_key = self.current_prefix + folder_name + '/'
        
        try:
            # Create empty object to represent folder
            self.s3_client.put_object(
                Bucket=self.current_bucket,
                Key=s3_key,
                Body=b''
            )
            
            CustomDialog(self.root, "Success", f"Folder created: {folder_name}")
            self.refresh_current_folder()
            
        except Exception as e:
            messagebox.showerror("Error", f"Failed to create folder: {str(e)}")
    
    def delete_item(self):
        """Delete the selected item"""
        selection = self.tree.selection()
        if not selection:
            messagebox.showwarning("Warning", "No item selected")
            return
        
        item = selection[0]
        values = self.tree.item(item, 'values')
        item_name = values[0]
        item_type = values[1] if len(values) > 1 else 'Unknown'
        
        if not messagebox.askyesno("Confirm Delete", f"Delete {item_type.lower()} '{item_name}'?"):
            return
        
        try:
            if item_type == 'Folder':
                # Delete all objects with this prefix
                s3_prefix = self.current_prefix + item_name + '/'
                
                paginator = self.s3_client.get_paginator('list_objects_v2')
                pages = paginator.paginate(Bucket=self.current_bucket, Prefix=s3_prefix)
                
                for page in pages:
                    objects = page.get('Contents', [])
                    if objects:
                        delete_keys = [{'Key': obj['Key']} for obj in objects]
                        self.s3_client.delete_objects(
                            Bucket=self.current_bucket,
                            Delete={'Objects': delete_keys}
                        )
            else:
                # Delete single file
                s3_key = self.current_prefix + item_name
                self.s3_client.delete_object(Bucket=self.current_bucket, Key=s3_key)
            
            CustomDialog(self.root, "Success", f"{item_type} deleted: {item_name}")
            self.refresh_current_folder()
            
        except Exception as e:
            messagebox.showerror("Error", f"Delete failed: {str(e)}")


class ProgressDialog:
    def __init__(self, parent, title_msg, message):
        self.dialog = tk.Toplevel(parent)
        self.dialog.title(title_msg)
        self.dialog.geometry("300x100")
        self.dialog.resizable(False, False)
        self.dialog.transient(parent)
        self.dialog.grab_set()
        apply_theme_to_titlebar(self.dialog)
        
        # Center the dialog
        self.dialog.geometry("+%d+%d" % (parent.winfo_rootx() + 100, parent.winfo_rooty() + 100))
        
        frame = ttk.Frame(self.dialog, padding="20")
        frame.pack(fill=tk.BOTH, expand=True)
        
        ttk.Label(frame, text=message).pack()
        
        self.progress = ttk.Progressbar(frame, mode='indeterminate')
        self.progress.pack(pady=(10, 0), fill=tk.X)
        self.progress.start()


    def destroy(self):
        self.progress.stop()
        self.dialog.destroy()

class CustomDialog:
    def __init__(self, parent, title_msg, message, type='info'):
        self.dialog = tk.Toplevel(parent)
        self.dialog.title(title_msg)
        self.dialog.geometry("300x100")
        self.dialog.resizable(False, False)
        self.dialog.transient(parent)
        self.dialog.grab_set()
        if type == 'error':
            self.dialog.iconbitmap(Path(__file__).parent / 'error.ico')
        elif type == 'warning':
            self.dialog.iconbitmap(Path(__file__).parent / 'warning.ico')
        else:
            self.dialog.iconbitmap(Path(__file__).parent / 'info.ico')
        apply_theme_to_titlebar(self.dialog)
        
        # Center the dialog
        self.dialog.geometry("+%d+%d" % (parent.winfo_rootx() + 100, parent.winfo_rooty() + 100))
        
        frame = ttk.Frame(self.dialog, padding="20")
        frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(frame, text=message).pack()
        ttk.Button(frame, text="OK", command=self.dialog.destroy).pack(pady=(10, 0))
        

if __name__ == "__main__":
    root = tk.Tk()
    app = S3Manager(root)
    root.mainloop()
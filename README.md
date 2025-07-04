# TK S3Browser

## Overview

A simple Tkinter-based GUI for managing AWS S3 buckets and objects using Boto3.

## Features

- View S3 buckets per profile
- Create Directories
- Upload files to S3
- Download files from S3
- Delete files from S3
and more...

## Requirements

- AWS CLI (not used directly by the app, but you may need it for setting up profiles)
- AWS profiles set-up in `~/.aws/credentials` and/or `~/.aws/config` and authenticated
- Python 3.x
- Boto3 (from pip)
- darkdetect
- pywinstyles
- sv_ttk

## Usage

1. Run the application:
   ```
   python s3browser.py
   ```

2. Select your AWS profile from the dropdown menu, then click 'Refresh Buckets'.

3. Choose an S3 bucket to view its contents.

4. Use the buttons to upload, download, or delete files. Or right-click on a file for more options.

5. To create a new directory, enter the directory name and click "Create Directory".

## Build

You can build this into an executable using `pyinstaller` as follows:

1. Install PyInstaller if you haven't already:
   ```
   pip install pyinstaller
   ```

2. Navigate to the project directory and run:
   ```
   pyinstaller --windowed --icon=s3.ico --add-data "s3.ico;." --add-data "info.ico;." --add-data "error.ico;." --add-data "warning.ico;." --name "S3 Browser" s3browser.py
   ```

3. After the build completes, you can find the executable in the `dist` folder.
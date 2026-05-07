# Lysa

**A browser-based microscopy image viewer and analysis tool.**

Originally created by **Prashanth Ramachandran**, who initiated the development, named the project, and designed its identity.

## Features

- **Native bit-depth support** - View and adjust 8-bit, 16-bit, and 32-bit images with full dynamic range
- **Channel merging** - Combine fluorescence channels into composites with per-channel contrast control at native bit depth
- **Interactive tools** - ROI statistics, line profiles, and distance measurements
- **Grid view** - View multiple images side by side with drag-to-reorder, per-cell zoom and pan
- **Folders and search** - Organize images into folders, filter by name
- **Sessions** - Save and restore your workspace (images, contrast settings, folders, layout) across app restarts
- **PDF export** - Export images at full resolution, one per page or in a configurable grid layout
- **Colormaps / LUTs** - Gray, Green, Red, Blue, Cyan, Magenta, Yellow, Hot, Cool, Viridis, and more
- **Lazy loading** - Load large folders efficiently; pixel data is fetched on demand

## Quick Start

```bash
git clone https://github.com/Isabelgolda/Lysa.git
cd Lysa
pip install -r requirements.txt
python3 server.py
```

Open **http://localhost:8050** in your browser.

Or use the launch script (macOS / Linux):

```bash
chmod +x run.sh
./run.sh
```

### Requirements

- Python 3.9+
- A modern web browser

## Usage

See the full [User Manual](MANUAL.md) for detailed instructions.

**Load images** by clicking Open Images or dragging files/folders onto the sidebar. Supported formats: TIFF, PNG, JPEG, BMP.

**Adjust contrast** using the Min/Max sliders or the Auto/Min-Max/Full Range buttons. For 16-bit images, sliders automatically scale to the native range.

**Merge channels** by clicking Merge, selecting images, and configuring colors and blend modes. Composites preserve the original bit depth.

**Save your work** with Save Session. Reopen the app later and your sessions will be available from the Load Session dialog.

## Project Structure

```
server.py              - FastAPI backend (image I/O, analysis, session management)
static/index.html      - Frontend (single-file HTML + CSS + JS)
static/jspdf.umd.min.js - PDF export library
requirements.txt       - Python dependencies
run.sh                 - Launch script
```

`uploads/` and `sessions/` are created at runtime and excluded from version control.

## License

This project is provided as-is for research and educational use.

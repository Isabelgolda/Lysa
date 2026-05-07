# Lysa - User Manual

**Microscopy Image Viewer & Analysis Tool**

---

## Getting Started

### Requirements

- Python 3.9 or later
- A modern web browser (Chrome, Firefox, Edge, or Safari)

### Installation

1. Clone the repository:

   ```
   git clone https://github.com/Isabelgolda/Lysa.git
   cd Lysa
   ```

2. (Recommended) Create a virtual environment:

   ```
   python3 -m venv .venv
   source .venv/bin/activate        # macOS / Linux
   .venv\Scripts\activate           # Windows
   ```

3. Install the Python dependencies:

   ```
   pip install -r requirements.txt
   ```

### Running the Application

**Option A - Use the launch script (macOS / Linux):**

```
chmod +x run.sh
./run.sh
```

**Option B - Run directly with Python:**

```
python3 server.py
```

Once the server starts, open your browser to **http://localhost:8050**. Press `Ctrl+C` in the terminal to stop the server.

---

## The Interface

Lysa has four main areas:

- **Top toolbar** - Tool selection (Pan, ROI, Line Profile, Measure) and action buttons (Merge, Save/Load Session, Export PDF, Contrast controls).
- **Left sidebar** - Your image library with search, folders, visibility toggles, and Show All / Hide All controls. The sidebar is resizable by dragging its right edge.
- **Center canvas area** - The main viewing area. In Grid View, all visible images are tiled here. Image tabs open individual images at full size.
- **Bottom info bar** - Shows pixel coordinates and intensity values at native bit depth as you move your mouse over an image.

---

## Loading Images

### Upload Individual Files

Click the **Open Images** button or drag and drop files onto the upload zone. Lysa supports TIFF, PNG, JPEG, and BMP files. Multi-channel 16-bit TIFFs from microscopes are fully supported, and pixel data is preserved at native bit depth.

### Load a Folder

1. **Folder path** - Type or paste the full path to a folder into the input field and press Enter or click Load.
2. **Drag and drop** - Drag a folder from your file manager onto the upload zone. Lysa will recursively find all image files inside.

When loading many images (more than 3), Lysa uses **lazy loading**: images appear in the sidebar immediately, but pixel data is only fetched when you make an image visible. A progress bar shows upload status.

---

## Viewing Images

### Grid View

All visible images are shown side by side in a tiled grid. Click on any image to select it (blue border). The selected image is the target for contrast controls and tools.

- **Close button** - Hover over a grid cell to reveal an **X** button in the top-right corner. Click it to hide the image from the grid without navigating to the sidebar.
- **Drag to reorder** - Drag images within the grid to rearrange their order.
- **Zoom & Pan** - Scroll to zoom into any grid cell. When zoomed in, click and drag to pan through the image regardless of which tool is active.

### Sidebar

Each image card has an **eye icon** to toggle grid visibility. Use **Show All / Hide All** for bulk control. Images are sorted alphabetically by name.

- **Search** - Type in the search box to filter images by name (substring match).
- **Folders** - Create folders to organize images. Drag sidebar cards onto folder headers to move them. Folder contents are sorted alphabetically. Right-click or use folder controls to rename or delete folders.

### Image Tabs (Single-Image View)

**Double-click** any image in the grid to open it in a dedicated tab. You can open multiple tabs and switch between them. Click the **X** on a tab to close it, or click **Grid View** to return to the tiled view.

---

## Adjusting Image Display

All display adjustments are non-destructive. The original data is always preserved.

### Brightness & Contrast

The **Min** and **Max** sliders set the contrast window. For 16-bit images, sliders automatically extend to the full native range (e.g., 0-65535) with adaptive step sizes. Contrast values are preserved across sessions.

### Colormaps (LUTs)

Choose a colormap from the dropdown: **Gray, Green, Red, Blue, Cyan, Magenta, Yellow, Hot, Cool, Viridis**, and more. Useful for visualizing single-channel fluorescence data.

### Auto-Contrast

- **Full Range** - Maps the display to the full 0-255 range.
- **Auto** - Percentile-based stretching (clips the darkest and brightest 0.1%).
- **Min/Max** - Stretches based on the actual minimum and maximum pixel values.

### Invert

Toggles inverted display (light-on-dark becomes dark-on-light).

---

## Tools

Select a tool from the toolbar. The active tool determines what happens when you click and drag on the canvas.

### Pan

Click and drag to pan. Scroll to zoom. This is the default tool. When an image is zoomed in, panning works with any active tool.

### ROI (Region of Interest)

Draw a rectangle to get statistics for that region: mean, standard deviation, min, max, and area in pixels.

### Line Profile

Draw a line to display an intensity profile plot along it. Useful for measuring gradients and edges.

### Measure

Draw a line to measure the distance between two points in pixels.

---

## Merging Channels

Lysa merges channels at **native bit depth**. If your source images are 16-bit, the composite is also 16-bit.

### How to Merge

1. Click **Merge** to enter merge mode.
2. Click images in the grid to select them for merging.
3. Click **Merge Selected**.
4. Configure each channel: choose a false color, adjust weight (0-2x), and pick a blend mode.
5. A live preview updates as you change settings.
6. Click **Merge** to create the composite.

### Per-Channel Contrast

After merging, select the composite and use the per-channel adjustment panel. Each channel's contrast sliders operate in the native range of its source image (e.g., 0-65535 for 16-bit sources).

### Blend Modes

- **Additive** - Pixel values are summed (standard for fluorescence overlays).
- **Max** - Takes the brightest pixel from each channel.
- **Average** - Averages all channel values.

---

## Sessions

Sessions save your entire workspace: images, contrast settings, folders, grid layout, and open tabs.

### Saving

Click **Save Session** in the toolbar. If you loaded a session previously, the dialog pre-fills with its name so you can overwrite it in place, or type a new name to save a copy.

### Loading

Click **Load Session** to see all saved sessions. When the app starts with no images loaded, it automatically opens the session dialog if saved sessions are available.

### Persistence

Sessions survive closing and reopening the app. Image files are stored in the `uploads/` directory and session metadata in `sessions/`. Both are created automatically.

---

## Exporting to PDF

Click **Export PDF** to export visible images. You will be prompted for:

1. **Filename** for the exported PDF.
2. **Layout mode:**
   - **One per page** - Each image gets its own page at full resolution, with proper aspect ratio and orientation.
   - **Grid** - You choose the number of **rows** and **columns** per page. Images that don't fit on one page overflow onto additional pages. Each image is labeled with its filename.

---

## Histogram

When an image is selected, the histogram shows the distribution of pixel intensities. For multi-channel images, each channel is plotted in its respective color. The histogram updates in real time as you adjust contrast or colormaps.

---

## Keyboard Shortcuts & Tips

- **Scroll wheel** on canvas: zoom in/out
- **Click + drag** when zoomed in: pan through the image (works with any tool)
- **Double-click** grid image: open in dedicated tab
- **Click** sidebar eye icon: toggle grid visibility
- **Drag** grid cells: reorder images
- **Drag** sidebar cards onto folder headers: organize into folders
- Drag and drop files or folders onto the upload zone
- The sidebar is resizable by dragging its right edge

---

## Troubleshooting

**The server won't start:**
Make sure all dependencies are installed (`pip install -r requirements.txt`). Check that port 8050 isn't already in use. If it is, stop the other process or change the port in `server.py` (look for `uvicorn.run` at the bottom).

**Images look too dark or too bright:**
Click **Auto** contrast for percentile-based stretching, or **Min/Max** for the full dynamic range.

**Large folders load slowly:**
This is normal for many large TIFF files. Lysa uses lazy loading, so images are only fetched when made visible.

**Tools (ROI, Measure, Line Profile) aren't responding:**
Make sure you have an image selected (blue border) and that you're clicking directly on the image canvas.

---

## Project Structure

```
Lysa/
  server.py              - FastAPI backend (image processing, analysis APIs)
  static/
    index.html           - Complete frontend (HTML + CSS + JS)
    jspdf.umd.min.js     - PDF export library (jsPDF v2.5.1)
    lysa_logo.svg        - Application logo
    lysa_favicon.svg     - Browser favicon
  requirements.txt       - Python dependencies
  run.sh                 - Launch script (macOS / Linux)
  uploads/               - Server-side image storage (auto-created, git-ignored)
  sessions/              - Saved session data (auto-created, git-ignored)
```

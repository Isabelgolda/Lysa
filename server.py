"""
Lysa - Microscopy Image Viewer & Analysis Tool
Inspired by Napari and OMERO

Python backend using FastAPI for image processing, analysis, and serving.
"""

import os
import io
import uuid
import json
import base64
import math
from pathlib import Path
from typing import Optional, List

import numpy as np
from PIL import Image, ImageDraw, ImageFilter
from fastapi import FastAPI, UploadFile, File, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from scipy import ndimage
from skimage import filters, measure, morphology, exposure, segmentation, color

app = FastAPI(title="Lysa", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Storage ---
UPLOAD_DIR = Path(__file__).parent / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)
SESSIONS_DIR = Path(__file__).parent / "sessions"
SESSIONS_DIR.mkdir(exist_ok=True)

# In-memory image store: {image_id: {path, name, metadata, numpy_array}}
image_store = {}


# --- Models ---
class AdjustmentParams(BaseModel):
    brightness: float = 0.0        # -100 to 100
    contrast: float = 1.0          # 0.1 to 3.0
    gamma: float = 1.0             # 0.1 to 5.0
    invert: bool = False
    channel: Optional[str] = None  # "red", "green", "blue", "gray", or None for all


class ROIParams(BaseModel):
    x: int
    y: int
    width: int
    height: int


class LineProfileParams(BaseModel):
    x1: int
    y1: int
    x2: int
    y2: int
    line_width: int = 1


class ThresholdParams(BaseModel):
    method: str = "otsu"           # otsu, manual, adaptive
    value: Optional[float] = None  # for manual threshold
    block_size: int = 35           # for adaptive


class MeasurementParams(BaseModel):
    x1: int
    y1: int
    x2: int
    y2: int
    pixel_size: float = 1.0        # microns per pixel
    pixel_unit: str = "px"


# --- Helpers ---

def normalize_to_uint8(arr: np.ndarray, percentile_low: float = 1.0, percentile_high: float = 99.0) -> np.ndarray:
    """
    Normalize any-bit-depth array to uint8 [0, 255] using percentile scaling.
    This is critical for 16-bit microscopy images where values span 0-65535
    but actual signal may only use a fraction of that range.
    """
    if arr.dtype == np.uint8:
        return arr

    arr_float = arr.astype(np.float64)
    # Use percentile-based scaling for better contrast
    p_low = np.percentile(arr_float, percentile_low)
    p_high = np.percentile(arr_float, percentile_high)

    if p_high <= p_low:
        # Flat image — try full range
        p_low = float(arr_float.min())
        p_high = float(arr_float.max())
    if p_high <= p_low:
        return np.zeros_like(arr, dtype=np.uint8)

    scaled = (arr_float - p_low) / (p_high - p_low) * 255.0
    return np.clip(scaled, 0, 255).astype(np.uint8)


def load_image_array(image_id: str) -> np.ndarray:
    """Load image as numpy array, caching in store."""
    if image_id not in image_store:
        raise HTTPException(404, "Image not found")
    entry = image_store[image_id]
    if entry.get("array") is None:
        img = Image.open(entry["path"])
        entry["array"] = np.array(img)
    return entry["array"]


def load_display_array(image_id: str) -> np.ndarray:
    """Load the 8-bit display-ready version of an image."""
    if image_id not in image_store:
        raise HTTPException(404, "Image not found")
    entry = image_store[image_id]
    if entry.get("display_array") is None:
        arr = load_image_array(image_id)
        entry["display_array"] = normalize_to_uint8(arr)
    return entry["display_array"]


def array_to_png_bytes(arr: np.ndarray) -> bytes:
    """Convert numpy array to PNG bytes."""
    if arr.dtype != np.uint8:
        arr = normalize_to_uint8(arr)
    if len(arr.shape) == 2:
        # Grayscale — convert to RGB for consistent browser handling
        arr = np.stack([arr, arr, arr], axis=-1)
    img = Image.fromarray(arr)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf.read()


def array_to_base64(arr: np.ndarray) -> str:
    """Convert numpy array to base64 PNG string."""
    png_bytes = array_to_png_bytes(arr)
    return base64.b64encode(png_bytes).decode("utf-8")


def ingest_image(file_path: str, filename: str) -> dict:
    """
    Common image ingestion logic: open image, extract metadata, store.
    Returns {"image_id": ..., "metadata": ...}.
    """
    img = Image.open(file_path)
    arr = np.array(img)

    # Compute display array (normalized to uint8)
    display_arr = normalize_to_uint8(arr)

    # Compute percentiles on the original data for auto-contrast info
    if len(arr.shape) == 2:
        flat = arr.flatten().astype(np.float64)
    else:
        flat = np.mean(arr[:, :, :3].astype(np.float64), axis=2).flatten()
    p1 = float(np.percentile(flat, 1))
    p99 = float(np.percentile(flat, 99))

    image_id = str(uuid.uuid4())[:8]

    with open(file_path, "rb") as f:
        size_bytes = os.path.getsize(file_path)

    metadata = {
        "filename": filename,
        "width": img.width,
        "height": img.height,
        "mode": img.mode,
        "channels": len(img.getbands()),
        "bands": list(img.getbands()),
        "dtype": str(arr.dtype),
        "bit_depth": int(arr.dtype.itemsize * 8),
        "size_bytes": size_bytes,
        "min_value": int(arr.min()),
        "max_value": int(arr.max()),
        "mean_value": round(float(arr.mean()), 2),
        "percentile_1": round(p1, 2),
        "percentile_99": round(p99, 2),
    }

    image_store[image_id] = {
        "path": str(file_path),
        "name": filename,
        "metadata": metadata,
        "array": arr,
        "display_array": display_arr,
    }

    return {"image_id": image_id, "metadata": metadata}


# --- Endpoints ---

@app.get("/", response_class=HTMLResponse)
async def root():
    index_path = Path(__file__).parent / "static" / "index.html"
    return HTMLResponse(content=index_path.read_text(), status_code=200)


@app.post("/api/upload")
async def upload_image(file: UploadFile = File(...)):
    """Upload an image and store it."""
    allowed = {".png", ".jpg", ".jpeg", ".tiff", ".tif", ".bmp", ".gif", ".lif"}
    ext = Path(file.filename).suffix.lower()
    if ext not in allowed:
        raise HTTPException(400, f"Unsupported format: {ext}")

    image_id_prefix = str(uuid.uuid4())[:8]
    save_path = UPLOAD_DIR / f"{image_id_prefix}{ext}"

    content = await file.read()
    with open(save_path, "wb") as f:
        f.write(content)

    # LIF files need special handling - redirect to load-lif endpoint
    if ext == ".lif":
        from pydantic import BaseModel as _BM
        lif_params = LifLoadParams(path=str(save_path))
        return await load_lif_file(lif_params)

    result = ingest_image(str(save_path), file.filename)
    return result


@app.get("/api/images")
async def list_images():
    """List all uploaded images."""
    return [
        {"image_id": iid, "name": entry["name"], "metadata": entry["metadata"]}
        for iid, entry in image_store.items()
    ]


@app.delete("/api/images/{image_id}")
async def delete_image(image_id: str):
    """Remove an image."""
    if image_id not in image_store:
        raise HTTPException(404, "Image not found")
    path = image_store[image_id]["path"]
    # Only delete files in the uploads dir (not originals from folders)
    if os.path.exists(path) and str(UPLOAD_DIR) in path:
        os.remove(path)
    del image_store[image_id]
    return {"status": "deleted"}


class FileLoadParams(BaseModel):
    path: str


@app.post("/api/load-file")
async def load_file(params: FileLoadParams):
    """Load a single image by its path on disk — no copy into uploads/."""
    allowed = {".png", ".jpg", ".jpeg", ".tiff", ".tif", ".bmp", ".gif", ".lif"}
    fp = Path(params.path)
    if not fp.is_file():
        raise HTTPException(400, f"File not found: {params.path}")
    if fp.suffix.lower() not in allowed:
        raise HTTPException(400, f"Unsupported format: {fp.suffix}")
    if fp.suffix.lower() == ".lif":
        lif_params = LifLoadParams(path=str(fp))
        return await load_lif_file(lif_params)
    return ingest_image(str(fp), fp.name)


class FolderLoadParams(BaseModel):
    path: str
    pattern: Optional[str] = None  # e.g. "*ch00*" to filter


class LifLoadParams(BaseModel):
    path: str
    image_indices: Optional[List[int]] = None  # which images to load (None = all)


@app.post("/api/load-folder")
async def load_folder(params: FolderLoadParams):
    """Load all supported images from a directory on the server's filesystem."""
    import glob as glob_mod

    folder = Path(params.path)
    if not folder.is_dir():
        raise HTTPException(400, f"Not a valid directory: {params.path}")

    allowed = {".png", ".jpg", ".jpeg", ".tiff", ".tif", ".bmp", ".gif", ".lif"}
    results = []

    # Collect matching files (recursive search into subdirectories)
    if params.pattern:
        files = sorted(folder.rglob(params.pattern))
    else:
        files = sorted(folder.rglob('*'))

    for fp in files:
        if fp.is_file() and fp.suffix.lower() in allowed:
            try:
                result = ingest_image(str(fp), fp.name)
                results.append(result)
            except Exception as e:
                results.append({"error": str(e), "filename": fp.name})

    return {"loaded": len([r for r in results if "image_id" in r]),
            "errors": len([r for r in results if "error" in r]),
            "images": results}


@app.post("/api/load-lif")
async def load_lif_file(params: LifLoadParams):
    """Load images from a Leica LIF file."""
    try:
        from liffile import LifFile
    except ImportError:
        raise HTTPException(
            500,
            "liffile library not installed. Run: pip install liffile[all]"
        )

    lif_path = Path(params.path)
    if not lif_path.is_file() or lif_path.suffix.lower() != '.lif':
        raise HTTPException(400, f"Not a valid LIF file: {params.path}")

    results = []
    try:
        with LifFile(str(lif_path)) as lif:
            # Build list of available images
            image_list = []
            for idx, img in enumerate(lif.images):
                image_list.append({
                    "index": idx,
                    "name": img.name,
                    "sizes": dict(img.sizes) if hasattr(img, 'sizes') else {},
                    "dtype": str(img.dtype) if hasattr(img, 'dtype') else 'unknown',
                })

            # If no indices specified, load all
            indices = params.image_indices if params.image_indices else list(range(len(lif.images)))

            for idx in indices:
                if idx < 0 or idx >= len(lif.images):
                    results.append({"error": f"Index {idx} out of range", "filename": f"index_{idx}"})
                    continue

                lif_img = lif.images[idx]
                img_name = lif_img.name or f"LIF_image_{idx}"

                try:
                    # Get numpy array from the LIF image
                    arr = np.asarray(lif_img.asarray())

                    # Handle multi-dimensional data (ZCYX, CYX, etc.)
                    # We flatten to 2D or 3D for display
                    sizes = dict(lif_img.sizes) if hasattr(lif_img, 'sizes') else {}

                    if arr.ndim > 3:
                        # Take max projection over Z if present, first T, first M
                        # Typical order: T, M, C, Z, Y, X
                        while arr.ndim > 3:
                            if 'Z' in sizes and arr.shape[0] > 1:
                                arr = np.max(arr, axis=0)  # max projection
                                sizes.pop('Z', None)
                            else:
                                arr = arr[0]  # take first slice
                                # Remove first key from sizes
                                if sizes:
                                    first_key = list(sizes.keys())[0]
                                    sizes.pop(first_key, None)

                    if arr.ndim == 3:
                        num_channels = arr.shape[0]
                        if num_channels <= 4:
                            # Channels-first (CYX) -> channels-last (YXC)
                            arr = np.moveaxis(arr, 0, -1)
                            if arr.shape[-1] == 1:
                                arr = arr[:, :, 0]  # squeeze single channel
                            elif arr.shape[-1] == 2:
                                # Pad to 3 channels
                                arr = np.concatenate([arr, np.zeros_like(arr[:, :, :1])], axis=-1)
                        else:
                            # Might be YXC already or spatial
                            pass

                    # Save as temporary TIF for the ingest pipeline
                    tmp_path = UPLOAD_DIR / f"lif_{uuid.uuid4().hex[:8]}.tif"
                    if arr.ndim == 2:
                        pil_img = Image.fromarray(arr)
                    else:
                        # Normalize for saving
                        disp = normalize_to_uint8(arr)
                        pil_img = Image.fromarray(disp)
                    pil_img.save(str(tmp_path))

                    # Re-ingest through the standard pipeline (which saves original array)
                    lif_filename = f"{lif_path.stem}/{img_name}"

                    # Manually ingest with the original array
                    image_id = str(uuid.uuid4())[:8]
                    display_arr = normalize_to_uint8(arr)

                    if len(arr.shape) == 2:
                        flat = arr.flatten().astype(np.float64)
                    else:
                        flat = np.mean(arr[:, :, :3].astype(np.float64), axis=2).flatten()
                    p1 = float(np.percentile(flat, 1))
                    p99 = float(np.percentile(flat, 99))

                    metadata = {
                        "filename": lif_filename,
                        "width": arr.shape[1] if arr.ndim >= 2 else 0,
                        "height": arr.shape[0],
                        "mode": "L" if arr.ndim == 2 else f"{'RGB' if arr.ndim == 3 and arr.shape[2] == 3 else 'RGBA' if arr.ndim == 3 and arr.shape[2] == 4 else 'L'}",
                        "channels": 1 if arr.ndim == 2 else arr.shape[2],
                        "bands": ["L"] if arr.ndim == 2 else ["R", "G", "B"][:arr.shape[2]],
                        "dtype": str(arr.dtype),
                        "bit_depth": int(arr.dtype.itemsize * 8),
                        "size_bytes": arr.nbytes,
                        "min_value": int(arr.min()),
                        "max_value": int(arr.max()),
                        "mean_value": round(float(arr.mean()), 2),
                        "percentile_1": round(p1, 2),
                        "percentile_99": round(p99, 2),
                        "lif_source": str(lif_path),
                        "lif_image_name": img_name,
                        "lif_sizes": sizes,
                    }

                    image_store[image_id] = {
                        "path": str(tmp_path),
                        "name": lif_filename,
                        "metadata": metadata,
                        "array": arr,
                        "display_array": display_arr,
                    }

                    results.append({"image_id": image_id, "metadata": metadata})

                except Exception as e:
                    results.append({"error": str(e), "filename": img_name})

    except Exception as e:
        raise HTTPException(500, f"Failed to read LIF file: {str(e)}")

    return {
        "loaded": len([r for r in results if "image_id" in r]),
        "errors": len([r for r in results if "error" in r]),
        "images": results,
        "available_images": image_list,
    }


@app.get("/api/lif-info")
async def lif_info(path: str):
    """Get info about images inside a LIF file without loading them."""
    try:
        from liffile import LifFile
    except ImportError:
        raise HTTPException(500, "liffile library not installed. Run: pip install liffile[all]")

    lif_path = Path(path)
    if not lif_path.is_file():
        raise HTTPException(400, f"File not found: {path}")

    image_list = []
    with LifFile(str(lif_path)) as lif:
        for idx, img in enumerate(lif.images):
            image_list.append({
                "index": idx,
                "name": img.name,
                "sizes": dict(img.sizes) if hasattr(img, 'sizes') else {},
                "dtype": str(img.dtype) if hasattr(img, 'dtype') else 'unknown',
            })

    return {"path": str(lif_path), "num_images": len(image_list), "images": image_list}


@app.get("/api/images/{image_id}/raw")
async def get_raw_image(image_id: str):
    """Serve the display-ready (8-bit) image as PNG."""
    display = load_display_array(image_id)
    png_data = array_to_png_bytes(display)
    return StreamingResponse(io.BytesIO(png_data), media_type="image/png")


@app.get("/api/images/{image_id}/raw_data")
async def get_raw_data(image_id: str):
    """Serve the original pixel data preserving native bit depth.

    Returns raw little-endian bytes with shape/dtype in response headers so
    the client can window/level 16-bit data without noise-amplifying
    percentile-stretch baked at ingest time.
    """
    if image_id not in image_store:
        raise HTTPException(404, "Image not found")
    entry = image_store[image_id]
    arr = entry.get("array")
    if arr is None:
        # Not yet loaded from disk — trigger the lazy load.
        try:
            arr = load_image_array(image_id)
        except Exception:
            arr = entry.get("display_array")
    if arr is None:
        raise HTTPException(404, "No pixel data available")

    if len(arr.shape) == 2:
        h, w = arr.shape
        c = 1
    elif len(arr.shape) == 3:
        h, w, c = arr.shape
    else:
        raise HTTPException(500, f"Unexpected array shape {arr.shape}")

    contiguous = np.ascontiguousarray(arr)
    body = contiguous.tobytes()

    headers = {
        "X-Width": str(w),
        "X-Height": str(h),
        "X-Channels": str(c),
        "X-Dtype": str(arr.dtype),
        "Access-Control-Expose-Headers": "X-Width, X-Height, X-Channels, X-Dtype",
        "Cache-Control": "no-store",
    }
    return Response(content=body, media_type="application/octet-stream", headers=headers)


@app.get("/api/images/{image_id}/thumbnail")
async def get_thumbnail(image_id: str, size: int = 150):
    """Get a thumbnail (always 8-bit)."""
    display = load_display_array(image_id)
    if len(display.shape) == 2:
        display = np.stack([display, display, display], axis=-1)
    img = Image.fromarray(display)
    img.thumbnail((size, size))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return StreamingResponse(buf, media_type="image/png")


# --- Image Adjustments ---

@app.post("/api/images/{image_id}/adjust")
async def adjust_image(image_id: str, params: AdjustmentParams):
    """Apply brightness, contrast, gamma adjustments."""
    arr = load_display_array(image_id).copy().astype(np.float64)

    # Channel selection
    if params.channel and len(arr.shape) == 3:
        ch_map = {"red": 0, "green": 1, "blue": 2}
        if params.channel == "gray":
            arr = np.mean(arr[:, :, :3], axis=2)
        elif params.channel in ch_map:
            ch = ch_map[params.channel]
            gray = np.zeros_like(arr)
            gray[:, :, ch] = arr[:, :, ch]
            arr = gray

    # Brightness
    arr = arr + params.brightness

    # Contrast
    mean = np.mean(arr)
    arr = (arr - mean) * params.contrast + mean

    # Gamma
    arr = np.clip(arr / 255.0, 0, 1)
    arr = np.power(arr, 1.0 / params.gamma) * 255.0

    # Invert
    if params.invert:
        arr = 255.0 - arr

    arr = np.clip(arr, 0, 255).astype(np.uint8)

    return {"image": array_to_base64(arr)}


# --- Histogram ---

@app.get("/api/images/{image_id}/histogram")
async def get_histogram(image_id: str, bins: int = 256):
    """Compute histogram for each channel."""
    arr = load_image_array(image_id)
    result = {}

    # Use display array (uint8) for histogram to match what user sees
    display = load_display_array(image_id)

    if len(display.shape) == 2:
        hist, edges = np.histogram(display.flatten(), bins=bins, range=(0, 256))
        result["gray"] = hist.tolist()
    elif len(display.shape) == 3:
        channels = ["red", "green", "blue"]
        for i, ch_name in enumerate(channels[:display.shape[2]]):
            hist, _ = np.histogram(display[:, :, i].flatten(), bins=bins, range=(0, 256))
            result[ch_name] = hist.tolist()
        # Also compute luminance histogram
        lum = np.mean(display[:, :, :3], axis=2)
        hist, _ = np.histogram(lum.flatten(), bins=bins, range=(0, 256))
        result["luminance"] = hist.tolist()

    # Include original data range info as separate top-level keys
    # (NOT inside result, since frontend iterates result keys as channel arrays)
    orig = load_image_array(image_id)

    return {
        "histograms": result,
        "bins": bins,
        "original_dtype": str(orig.dtype),
        "original_range": [int(orig.min()), int(orig.max())],
    }


# --- ROI Statistics ---

@app.post("/api/images/{image_id}/roi-stats")
async def roi_statistics(image_id: str, roi: ROIParams):
    """Compute statistics for a region of interest."""
    arr = load_display_array(image_id)
    y1, y2 = roi.y, roi.y + roi.height
    x1, x2 = roi.x, roi.x + roi.width

    y1 = max(0, min(y1, arr.shape[0]))
    y2 = max(0, min(y2, arr.shape[0]))
    x1 = max(0, min(x1, arr.shape[1]))
    x2 = max(0, min(x2, arr.shape[1]))

    region = arr[y1:y2, x1:x2]

    stats = {
        "area_pixels": int(region.shape[0] * region.shape[1]),
        "min": int(region.min()),
        "max": int(region.max()),
        "mean": round(float(region.mean()), 2),
        "std": round(float(region.std()), 2),
        "median": round(float(np.median(region)), 2),
    }

    # Per-channel stats if color
    if len(region.shape) == 3:
        for i, ch in enumerate(["red", "green", "blue"][:region.shape[2]]):
            ch_data = region[:, :, i]
            stats[f"{ch}_mean"] = round(float(ch_data.mean()), 2)
            stats[f"{ch}_std"] = round(float(ch_data.std()), 2)

    # Mini histogram
    hist, _ = np.histogram(region.flatten(), bins=64, range=(0, 256))
    stats["histogram"] = hist.tolist()

    return stats


# --- Line Profile ---

@app.post("/api/images/{image_id}/line-profile")
async def line_profile(image_id: str, params: LineProfileParams):
    """Compute intensity profile along a line."""
    arr = load_display_array(image_id)

    length = int(math.sqrt((params.x2 - params.x1) ** 2 + (params.y2 - params.y1) ** 2))
    if length == 0:
        raise HTTPException(400, "Zero-length line")

    x_coords = np.linspace(params.x1, params.x2, length)
    y_coords = np.linspace(params.y1, params.y2, length)

    profiles = {}
    if len(arr.shape) == 2:
        vals = ndimage.map_coordinates(arr.astype(float), [y_coords, x_coords], order=1)
        profiles["gray"] = vals.tolist()
    else:
        for i, ch in enumerate(["red", "green", "blue"][:arr.shape[2]]):
            vals = ndimage.map_coordinates(arr[:, :, i].astype(float), [y_coords, x_coords], order=1)
            profiles[ch] = vals.tolist()
        # Luminance
        lum = np.mean(arr[:, :, :3].astype(float), axis=2)
        vals = ndimage.map_coordinates(lum, [y_coords, x_coords], order=1)
        profiles["luminance"] = vals.tolist()

    return {
        "profiles": profiles,
        "length_pixels": length,
        "coordinates": {
            "x": x_coords.tolist(),
            "y": y_coords.tolist(),
        }
    }


# --- Measurements ---

@app.post("/api/images/{image_id}/measure")
async def measure_distance(image_id: str, params: MeasurementParams):
    """Measure distance between two points."""
    dx = params.x2 - params.x1
    dy = params.y2 - params.y1
    dist_px = math.sqrt(dx ** 2 + dy ** 2)
    dist_scaled = dist_px * params.pixel_size
    angle = math.degrees(math.atan2(dy, dx))

    return {
        "distance_pixels": round(dist_px, 2),
        "distance_scaled": round(dist_scaled, 4),
        "unit": params.pixel_unit,
        "angle_degrees": round(angle, 2),
        "dx": dx,
        "dy": dy,
    }


# --- Segmentation / Thresholding ---

@app.post("/api/images/{image_id}/threshold")
async def threshold_image(image_id: str, params: ThresholdParams):
    """Apply thresholding for segmentation."""
    # Use display array (uint8) for consistent thresholding
    arr = load_display_array(image_id)

    # Convert to grayscale if needed
    if len(arr.shape) == 3:
        gray = np.mean(arr[:, :, :3], axis=2).astype(np.uint8)
    else:
        gray = arr.copy()

    if params.method == "otsu":
        thresh_val = filters.threshold_otsu(gray)
        binary = gray > thresh_val
    elif params.method == "manual":
        thresh_val = params.value if params.value is not None else 128
        binary = gray > thresh_val
    elif params.method == "adaptive":
        thresh_val = filters.threshold_local(gray, block_size=params.block_size)
        binary = gray > thresh_val
        thresh_val = float(np.mean(thresh_val))
    else:
        raise HTTPException(400, f"Unknown method: {params.method}")

    # Label connected components
    labeled = measure.label(binary)
    regions = measure.regionprops(labeled)

    region_data = []
    for r in regions[:100]:  # limit to 100 regions
        region_data.append({
            "label": int(r.label),
            "area": int(r.area),
            "centroid": [round(r.centroid[0], 1), round(r.centroid[1], 1)],
            "bbox": list(r.bbox),
            "perimeter": round(float(r.perimeter), 2),
            "eccentricity": round(float(r.eccentricity), 4),
        })

    # Create overlay image
    overlay = np.zeros((*binary.shape, 4), dtype=np.uint8)
    overlay[binary, 0] = 0
    overlay[binary, 1] = 255
    overlay[binary, 2] = 100
    overlay[binary, 3] = 140
    overlay[~binary, 3] = 0

    return {
        "threshold_value": round(float(thresh_val), 2),
        "method": params.method,
        "num_regions": len(regions),
        "regions": region_data,
        "overlay": array_to_base64(overlay),
        "binary": array_to_base64((binary.astype(np.uint8) * 255)),
    }


# --- Edge Detection ---

@app.get("/api/images/{image_id}/edges")
async def detect_edges(image_id: str, method: str = "canny", sigma: float = 1.0):
    """Detect edges in the image."""
    # Use display array for consistent edge detection
    arr = load_display_array(image_id)

    if len(arr.shape) == 3:
        gray = np.mean(arr[:, :, :3], axis=2).astype(np.float64) / 255.0
    else:
        gray = arr.astype(np.float64) / 255.0

    if method == "canny":
        edges = filters.farid(gray)  # alternative if canny isn't available
        try:
            from skimage.feature import canny
            edges = canny(gray, sigma=sigma).astype(np.float64)
        except ImportError:
            pass
    elif method == "sobel":
        edges = filters.sobel(gray)
    elif method == "laplacian":
        edges = filters.laplace(gray)
        edges = np.abs(edges)
    else:
        raise HTTPException(400, f"Unknown method: {method}")

    edges = (edges / edges.max() * 255).astype(np.uint8) if edges.max() > 0 else edges.astype(np.uint8)

    return {"image": array_to_base64(edges), "method": method}


# --- Filters ---

@app.get("/api/images/{image_id}/filter")
async def apply_filter(image_id: str, filter_type: str = "gaussian", size: int = 3):
    """Apply image filters."""
    # Use display array for consistent filtering
    arr = load_display_array(image_id).copy()

    if filter_type == "gaussian":
        if len(arr.shape) == 3:
            for c in range(arr.shape[2]):
                arr[:, :, c] = ndimage.gaussian_filter(arr[:, :, c].astype(float), sigma=size / 2).astype(np.uint8)
        else:
            arr = ndimage.gaussian_filter(arr.astype(float), sigma=size / 2).astype(np.uint8)
    elif filter_type == "median":
        if len(arr.shape) == 3:
            for c in range(arr.shape[2]):
                arr[:, :, c] = ndimage.median_filter(arr[:, :, c], size=size)
        else:
            arr = ndimage.median_filter(arr, size=size)
    elif filter_type == "sharpen":
        kernel = np.array([[0, -1, 0], [-1, 5, -1], [0, -1, 0]])
        if len(arr.shape) == 3:
            for c in range(arr.shape[2]):
                arr[:, :, c] = np.clip(ndimage.convolve(arr[:, :, c].astype(float), kernel), 0, 255).astype(np.uint8)
        else:
            arr = np.clip(ndimage.convolve(arr.astype(float), kernel), 0, 255).astype(np.uint8)
    else:
        raise HTTPException(400, f"Unknown filter: {filter_type}")

    return {"image": array_to_base64(arr)}


# --- Merge / Composite Channels ---

class ChannelSpec(BaseModel):
    image_id: str
    channel: str = "green"   # red, green, blue, cyan, magenta, yellow, gray, white
    weight: float = 1.0      # 0.0–2.0

class MergeParams(BaseModel):
    """Legacy 2-image merge (still supported for backward compat)."""
    image_id_1: str
    image_id_2: str
    channel_1: str = "green"
    channel_2: str = "red"
    blend_mode: str = "additive"
    weight_1: float = 1.0
    weight_2: float = 1.0
    name: Optional[str] = None

class MergeNParams(BaseModel):
    """N-channel merge."""
    channels: List[ChannelSpec]
    blend_mode: str = "additive"   # additive, max, average
    name: Optional[str] = None


def _do_merge(channel_specs: List[dict], blend_mode: str, merge_name: Optional[str]):
    """Core merge logic for N images. Each spec has image_id, channel, weight.

    Channels can be a color name (red/green/blue/cyan/magenta/yellow/gray/white)
    which routes the source's grayscale value into the matching R/G/B channels,
    OR "original"/"none" which preserves the source's RGB pixels directly.

    The composite is computed in the native bit depth of the source images: if
    the sources are 16-bit, the result is 16-bit too. This avoids the precision
    loss / noise amplification that came from an early 8-bit downcast.
    """
    ch_map = {
        "red": [0], "green": [1], "blue": [2],
        "cyan": [1, 2], "magenta": [0, 2], "yellow": [0, 1],
        "gray": [0, 1, 2], "white": [0, 1, 2],  # gray and white both map to R=G=B
    }

    # Load each source at its NATIVE bit depth (no percentile stretch).
    raw_arrays = [load_image_array(spec["image_id"]).copy() for spec in channel_specs]

    # Pick the highest-precision integer / float dtype among the sources so the
    # composite can fit all of their values without clipping or quantization.
    def dtype_rank(dt):
        kind_order = {"u": 0, "i": 1, "f": 2}
        return (kind_order.get(dt.kind, 0), dt.itemsize)

    out_dtype = max((a.dtype for a in raw_arrays), key=dtype_rank)
    if out_dtype.kind == "f":
        # Keep floats as float32 for the stored array.
        out_dtype = np.dtype("float32")
        out_max = float(max((np.nanmax(a) if a.size else 1.0) for a in raw_arrays))
        if not np.isfinite(out_max) or out_max <= 0:
            out_max = 1.0
    else:
        out_max = float(np.iinfo(out_dtype).max)

    # Pad all to same size
    h = max(a.shape[0] for a in raw_arrays)
    w = max(a.shape[1] for a in raw_arrays)

    def to_rgb(arr):
        if len(arr.shape) == 2:
            return np.stack([arr, arr, arr], axis=-1)
        return arr[:, :, :3]

    def to_gray(arr):
        if len(arr.shape) == 3:
            return np.mean(arr[:, :, :3].astype(np.float64), axis=2)
        return arr.astype(np.float64)

    def pad_rgb(rgb):
        result = np.zeros((h, w, 3), dtype=np.float64)
        result[:rgb.shape[0], :rgb.shape[1], :] = rgb.astype(np.float64)
        return result

    def pad_gray(g):
        result = np.zeros((h, w), dtype=np.float64)
        result[:g.shape[0], :g.shape[1]] = g
        return result

    # Rescale a source's values into the target dtype's native range so that
    # two sources of different bit depths merge on an even footing.
    def rescale_to_out_range(arr_float, src_dtype):
        if src_dtype.kind == "f":
            # floats are assumed normalized [0, 1]; scale up to out_max
            return arr_float * out_max
        src_max = float(np.iinfo(src_dtype).max)
        if src_max == out_max:
            return arr_float
        return arr_float * (out_max / src_max)

    # Build a per-image RGB layer based on its assigned channel
    layers = []
    for spec, arr in zip(channel_specs, raw_arrays):
        ch_name = spec["channel"]
        weight = spec["weight"]
        src_dtype = arr.dtype
        if ch_name in ("original", "none"):
            # Preserve source RGB directly — no grayscale conversion
            layer = rescale_to_out_range(pad_rgb(to_rgb(arr)), src_dtype) * weight
        else:
            # Convert to grayscale and route into the chosen R/G/B targets
            gray = rescale_to_out_range(pad_gray(to_gray(arr)), src_dtype) * weight
            layer = np.zeros((h, w, 3), dtype=np.float64)
            for t in ch_map.get(ch_name, [1]):
                layer[:, :, t] = gray
        layers.append(layer)

    if blend_mode == "max":
        composite = layers[0].copy()
        for layer in layers[1:]:
            composite = np.maximum(composite, layer)
    elif blend_mode == "average":
        composite = np.zeros((h, w, 3), dtype=np.float64)
        count = np.zeros((h, w, 3), dtype=np.float64)
        for layer in layers:
            mask = layer > 0
            composite += layer
            count += mask.astype(np.float64)
        count = np.maximum(count, 1)
        composite = composite / count
    else:
        # additive (default)
        composite = np.zeros((h, w, 3), dtype=np.float64)
        for layer in layers:
            composite += layer

    # Cast back to the chosen dtype, clipping into its valid range.
    if out_dtype.kind == "f":
        composite = composite.astype(out_dtype)
    else:
        composite = np.clip(composite, 0, out_max).astype(out_dtype)

    # Build name from sources
    names = [image_store[s["image_id"]]["name"] for s in channel_specs]
    if not merge_name:
        merge_name = f"Merge({'+'.join(names)})"

    # Save — use TIFF so we can round-trip 16-bit / float composites.
    image_id = str(uuid.uuid4())[:8]
    save_path = UPLOAD_DIR / f"{image_id}.tif"
    try:
        import tifffile
        tifffile.imwrite(str(save_path), composite)
    except Exception:
        # Fallback to PIL TIFF writer (uint8 only).
        save_path = UPLOAD_DIR / f"{image_id}.png"
        Image.fromarray(np.clip(composite, 0, 255).astype(np.uint8)).save(save_path)

    # Also produce an 8-bit display version for thumbnails / PNG endpoint.
    display_arr = normalize_to_uint8(composite)

    try:
        size_bytes = save_path.stat().st_size
    except Exception:
        size_bytes = 0

    metadata = {
        "filename": merge_name,
        "width": w,
        "height": h,
        "mode": "RGB",
        "channels": 3,
        "bands": ["R", "G", "B"],
        "dtype": str(composite.dtype),
        "size_bytes": size_bytes,
        "min_value": float(composite.min()),
        "max_value": float(composite.max()),
        "mean_value": round(float(composite.mean()), 2),
        "percentile_1": round(float(np.percentile(composite, 1)), 2),
        "percentile_99": round(float(np.percentile(composite, 99)), 2),
        "sources": [s["image_id"] for s in channel_specs],
        "channel_assignments": [s["channel"] for s in channel_specs],
        "blend_mode": blend_mode,
    }

    image_store[image_id] = {
        "path": str(save_path),
        "name": merge_name,
        "metadata": metadata,
        "array": composite,
        "display_array": display_arr,
    }

    return {"image_id": image_id, "metadata": metadata}


@app.post("/api/merge")
async def merge_images(params: MergeParams):
    """Legacy 2-image merge endpoint."""
    specs = [
        {"image_id": params.image_id_1, "channel": params.channel_1, "weight": params.weight_1},
        {"image_id": params.image_id_2, "channel": params.channel_2, "weight": params.weight_2},
    ]
    return _do_merge(specs, params.blend_mode, params.name)


@app.post("/api/merge-n")
async def merge_n_images(params: MergeNParams):
    """N-channel merge endpoint."""
    if len(params.channels) < 2:
        raise HTTPException(400, "Need at least 2 images to merge")
    specs = [{"image_id": c.image_id, "channel": c.channel, "weight": c.weight} for c in params.channels]
    return _do_merge(specs, params.blend_mode, params.name)


# --- Sessions (save/restore named layouts + adjustments) ---

def _ingest_with_id(image_id: str, file_path: str, filename: str):
    """Re-ingest an image into image_store reusing an existing ID. Idempotent."""
    if image_id in image_store:
        return
    if not os.path.exists(file_path):
        raise HTTPException(404, f"Source file missing for {image_id}: {file_path}")
    img = Image.open(file_path)
    arr = np.array(img)
    display_arr = normalize_to_uint8(arr)
    if len(arr.shape) == 2:
        flat = arr.flatten().astype(np.float64)
    else:
        flat = np.mean(arr[:, :, :3].astype(np.float64), axis=2).flatten()
    metadata = {
        "filename": filename,
        "width": img.width,
        "height": img.height,
        "mode": img.mode,
        "channels": len(img.getbands()),
        "bands": list(img.getbands()),
        "dtype": str(arr.dtype),
        "bit_depth": int(arr.dtype.itemsize * 8),
        "size_bytes": os.path.getsize(file_path),
        "min_value": int(arr.min()),
        "max_value": int(arr.max()),
        "mean_value": round(float(arr.mean()), 2),
        "percentile_1": round(float(np.percentile(flat, 1)), 2),
        "percentile_99": round(float(np.percentile(flat, 99)), 2),
    }
    image_store[image_id] = {
        "path": str(file_path),
        "name": filename,
        "metadata": metadata,
        "array": arr,
        "display_array": display_arr,
    }


class SessionSaveParams(BaseModel):
    name: str
    state: dict   # opaque client state blob
    images: List[dict]  # [{image_id, name, file_path}]


def _safe_session_name(name: str) -> str:
    cleaned = "".join(c for c in name if c.isalnum() or c in "-_ ").strip()
    if not cleaned:
        raise HTTPException(400, "Session name must contain alphanumerics")
    return cleaned


@app.post("/api/sessions/save")
async def save_session(params: SessionSaveParams):
    """Save the client's session state to disk under a given name."""
    name = _safe_session_name(params.name)
    # For each referenced image, capture the on-disk path so it can be re-ingested later.
    image_records = []
    for entry in params.images:
        iid = entry.get("image_id")
        if not iid or iid not in image_store:
            continue
        store_entry = image_store[iid]
        image_records.append({
            "image_id": iid,
            "name": store_entry["name"],
            "file_path": store_entry["path"],
            "metadata": store_entry["metadata"],
        })
    payload = {
        "version": 1,
        "name": name,
        "saved_at": __import__("datetime").datetime.now().isoformat(timespec="seconds"),
        "state": params.state,
        "images": image_records,
    }
    out_path = SESSIONS_DIR / f"{name}.json"
    with open(out_path, "w") as f:
        json.dump(payload, f, indent=2, default=str)
    return {"name": name, "saved_at": payload["saved_at"], "image_count": len(image_records)}


@app.get("/api/sessions/list")
async def list_sessions():
    """List all saved sessions."""
    out = []
    for f in sorted(SESSIONS_DIR.glob("*.json")):
        try:
            data = json.loads(f.read_text())
            out.append({
                "name": data.get("name", f.stem),
                "saved_at": data.get("saved_at", ""),
                "image_count": len(data.get("images", [])),
            })
        except Exception:
            continue
    return out


@app.get("/api/sessions/load/{name}")
async def load_session(name: str):
    """Load a saved session: re-ingest images into image_store and return the state blob."""
    name = _safe_session_name(name)
    path = SESSIONS_DIR / f"{name}.json"
    if not path.exists():
        raise HTTPException(404, f"Session '{name}' not found")
    data = json.loads(path.read_text())
    # Restore images into image_store under their original IDs
    missing = []
    for img in data.get("images", []):
        try:
            _ingest_with_id(img["image_id"], img["file_path"], img["name"])
        except HTTPException as e:
            missing.append({"image_id": img["image_id"], "name": img["name"], "error": e.detail})
    return {
        "name": data.get("name", name),
        "saved_at": data.get("saved_at", ""),
        "state": data.get("state", {}),
        "images": data.get("images", []),
        "missing": missing,
    }


@app.delete("/api/sessions/{name}")
async def delete_session(name: str):
    name = _safe_session_name(name)
    path = SESSIONS_DIR / f"{name}.json"
    if path.exists():
        path.unlink()
    return {"deleted": name}


# --- Single Image Viewer (opens in new tab) ---

@app.get("/view/{image_id}")
async def view_image(image_id: str):
    """Serve a standalone viewer page for a single image."""
    if image_id not in image_store:
        raise HTTPException(404, "Image not found")
    meta = image_store[image_id]["metadata"]
    name = image_store[image_id]["name"]
    return HTMLResponse(f"""<!DOCTYPE html>
<html><head>
<title>{name} — Lysa</title>
<style>
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{ background:#0a0a12; display:flex; align-items:center; justify-content:center; height:100vh; overflow:hidden; font-family:system-ui; }}
  img {{ max-width:100vw; max-height:100vh; object-fit:contain; cursor:grab; transition:transform 0.1s; }}
  img.dragging {{ cursor:grabbing; transition:none; }}
  .info {{ position:fixed; top:10px; left:10px; color:#aab; font-size:13px; background:rgba(10,10,18,0.85);
           padding:8px 14px; border-radius:8px; border:1px solid #333; }}
  .info h3 {{ font-size:14px; color:#e6e6ef; margin-bottom:4px; }}
  .controls {{ position:fixed; bottom:14px; left:50%; transform:translateX(-50%); display:flex; gap:6px; }}
  .controls button {{ background:#1a1a2e; color:#ccc; border:1px solid #333; padding:6px 14px;
           border-radius:6px; cursor:pointer; font-size:13px; }}
  .controls button:hover {{ background:#16213e; color:#fff; }}
</style></head><body>
<img id="img" src="/api/images/{image_id}/raw" alt="{name}">
<div class="info">
  <h3>{name}</h3>
  {meta.get('width','')} x {meta.get('height','')} &middot; {meta.get('mode','')}
  {(' &middot; ' + str(meta.get('bit_depth','')) + '-bit') if meta.get('bit_depth',8) > 8 else ''}
</div>
<div class="controls">
  <button onclick="z(1.3)">Zoom +</button>
  <button onclick="z(1/1.3)">Zoom −</button>
  <button onclick="scale=1;tx=0;ty=0;apply()">Fit</button>
</div>
<script>
let scale=1,tx=0,ty=0,drag=false,sx,sy;
const img=document.getElementById('img');
function apply(){{ img.style.transform=`translate(${{tx}}px,${{ty}}px) scale(${{scale}})` }}
function z(f){{ scale=Math.min(Math.max(scale*f,0.1),30); apply() }}
img.addEventListener('wheel',e=>{{ e.preventDefault(); z(e.deltaY<0?1.15:1/1.15) }});
img.addEventListener('mousedown',e=>{{ drag=true; sx=e.clientX-tx; sy=e.clientY-ty; img.classList.add('dragging') }});
window.addEventListener('mousemove',e=>{{ if(drag){{ tx=e.clientX-sx; ty=e.clientY-sy; apply() }} }});
window.addEventListener('mouseup',()=>{{ drag=false; img.classList.remove('dragging') }});
</script></body></html>""")


# --- Serve static files ---
app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8050)

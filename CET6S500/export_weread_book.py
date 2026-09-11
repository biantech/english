#!/usr/bin/env python3
"""Export authorized WeRead page responses through a logged-in browser session."""

from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import html
import json
import logging
import statistics
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

try:
    from playwright.async_api import BrowserContext, Page, Response, async_playwright
except ImportError:  # Keep --help and the installation message available without Playwright.
    BrowserContext = Page = Response = None  # type: ignore[assignment,misc]
    async_playwright = None


DEFAULT_BOOK_URL = "https://weread.qq.com/web/reader/800323e07158c8e0800fd55"
READ_PATH = "/web/book/read"
OCR_SOURCE = Path(__file__).with_name("ocr_image.swift")
OCR_BINARY = Path(tempfile.gettempdir()) / "weread_ocr_image"
CANVAS_TEXT_CAPTURE_SCRIPT = r"""
(() => {
  const capture = { items: [], canvasIds: new WeakMap(), canvases: [], nextCanvasId: 0 };
  Object.defineProperty(window, "__wereadTextCapture", { value: capture });
  const originalFillText = CanvasRenderingContext2D.prototype.fillText;
  CanvasRenderingContext2D.prototype.fillText = function(text, x, y, ...args) {
    if (this.canvas?.closest?.(".wr_canvasContainer")) {
      let canvasId = capture.canvasIds.get(this.canvas);
      if (canvasId === undefined) {
        canvasId = capture.nextCanvasId++;
        capture.canvasIds.set(this.canvas, canvasId);
        capture.canvases[canvasId] = this.canvas;
      }
      const point = new DOMPoint(Number(x), Number(y)).matrixTransform(this.getTransform());
      capture.items.push({ text: String(text), x: point.x, y: point.y, canvasId });
    }
    return originalFillText.call(this, text, x, y, ...args);
  };
})();
"""
logger = logging.getLogger(__name__)


def save_response(output_dir: Path, sequence: int, response: Response, body: bytes) -> Path:
    """Save response metadata and decoded body without exposing request headers."""
    digest = hashlib.sha256(body).hexdigest()
    try:
        payload = json.loads(body.decode("utf-8"))
        suffix = "json"
    except (UnicodeDecodeError, json.JSONDecodeError):
        payload = {"body_hex": body.hex(), "encoding": "hex"}
        suffix = "json"

    record = {
        "sequence": sequence,
        "url": response.url,
        "status": response.status,
        "content_sha256": digest,
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "body": payload,
    }
    path = output_dir / f"page_{sequence:05d}.{suffix}"
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


async def wait_for_login(page: Page, wait_seconds: int) -> None:
    """Give the user time to complete login if the page is not authenticated."""
    logger.info("Browser opened. Complete login in the browser if required.")
    await page.wait_for_timeout(wait_seconds * 1000)
    logger.info("Current page: url=%s title=%s", page.url, await page.title())


async def go_to_book_start(page: Page, render_wait_seconds: int) -> None:
    """Open the catalog and select the first chapter."""
    catalog_panel = page.locator(".readerCatalog").first
    catalog_buttons = page.locator("button.catalog")
    for index in range(await catalog_buttons.count()):
        button = catalog_buttons.nth(index)
        await button.evaluate("element => element.click()")
        await page.wait_for_timeout(250)
        if await catalog_panel.is_visible():
            break
    else:
        logger.warning("Catalog panel was not available; continuing from current reader position")
        return

    first_item = page.locator(".readerCatalog_list_item").first
    await first_item.wait_for(state="visible", timeout=render_wait_seconds * 1000)
    chapter_title = (await first_item.inner_text()).strip()
    logger.info("Starting from first chapter: %s", chapter_title)
    await first_item.click()
    await page.wait_for_timeout(1000)


async def enable_single_page_mode(page: Page) -> None:
    """Switch the desktop reader to single-page navigation when available."""
    control = page.locator(".readerControls_item.isNormalReader").first
    try:
        if await control.is_visible(timeout=1000):
            await control.click()
            await page.wait_for_timeout(1500)
            logger.info("Enabled single-page reader mode")
    except Exception as exc:
        logger.warning("Could not enable single-page reader mode: %s", exc)
    await page.reload(wait_until="domcontentloaded")
    await page.keyboard.press("Home")
    await page.evaluate("window.scrollTo(0, 0)")
    await page.wait_for_timeout(1000)


async def visible_content(page: Page) -> str:
    """Return readable content from the rendered reader area."""
    locator = page.locator(".passage-content").first
    try:
        if await locator.is_visible():
            return (await locator.inner_text(timeout=1000)).strip()
    except Exception:
        pass
    return ""


async def has_visible_canvas(page: Page) -> bool:
    """Check whether the reader has a visible canvas with usable dimensions."""
    for index in range(await page.locator(".wr_canvasContainer canvas").count()):
        canvas = page.locator(".wr_canvasContainer canvas").nth(index)
        try:
            if await canvas.is_visible():
                box = await canvas.bounding_box()
                if box and box["width"] > 1 and box["height"] > 1:
                    return True
        except Exception:
            continue
    return False


async def capture_canvas_images(page: Page) -> list[bytes]:
    """Read the rendered pixel buffer from each reader canvas."""
    images: list[bytes] = []
    canvases = page.locator(".wr_canvasContainer canvas")
    for index in range(await canvases.count()):
        try:
            active = await canvases.nth(index).evaluate(
                """canvas => {
                    const style = getComputedStyle(canvas);
                    const rect = canvas.getBoundingClientRect();
                    return style.display !== 'none' && style.visibility !== 'hidden' &&
                        rect.width > 1 && rect.height > 1;
                }"""
            )
        except Exception:
            active = False
        if not active:
            continue
        try:
            data_url = await canvases.nth(index).evaluate(
                "canvas => canvas.toDataURL('image/png')"
            )
        except Exception as exc:
            logger.warning("Could not read canvas %d: %s", index, exc)
            continue
        prefix = "data:image/png;base64,"
        if data_url.startswith(prefix):
            images.append(base64.b64decode(data_url[len(prefix) :]))
    return images


async def clear_captured_canvas_text(page: Page) -> None:
    """Clear text collected from reader canvas drawing calls."""
    await page.evaluate("window.__wereadTextCapture?.items.splice(0)")


def format_canvas_text(items: list[dict[str, object]]) -> str:
    """Reconstruct lines and paragraphs from canvas drawing coordinates."""
    lines: list[tuple[int, float, str]] = []
    for item in items:
        text = str(item["text"]).replace("\u200b", "").replace("\ufeff", "")
        if not text:
            continue
        canvas_id = int(item["canvasId"])
        y = float(item["y"])
        if lines and lines[-1][0] == canvas_id and abs(lines[-1][1] - y) < 1:
            previous_canvas, previous_y, previous_text = lines[-1]
            lines[-1] = (previous_canvas, previous_y, previous_text + text)
        else:
            lines.append((canvas_id, y, text))

    line_gaps = [
        current[1] - previous[1]
        for previous, current in zip(lines, lines[1:])
        if current[0] == previous[0] and current[1] - previous[1] > 1
    ]
    normal_gap = statistics.median_low(line_gaps) if line_gaps else 0
    output: list[str] = []
    for index, line in enumerate(lines):
        if index:
            previous = lines[index - 1]
            gap = line[1] - previous[1]
            if line[0] != previous[0] or (normal_gap and gap > normal_gap * 1.35):
                output.append("")
        output.append(line[2].rstrip())
    return "\n".join(output).strip()


async def captured_canvas_text(page: Page) -> str:
    """Return exact text passed by the page to the reader canvas."""
    items = await page.evaluate(
        """
        () => {
          const capture = window.__wereadTextCapture;
          if (!capture) return [];
          const visible = new Set();
          capture.canvases.forEach((canvas, id) => {
            const style = getComputedStyle(canvas);
            const rect = canvas.getBoundingClientRect();
            if (style.display !== "none" && style.visibility !== "hidden" &&
                rect.width > 1 && rect.height > 1) visible.add(id);
          });
          return capture.items.filter(item => visible.has(item.canvasId));
        }
        """
    )
    return format_canvas_text(items)


async def current_chapter_title(page: Page) -> str:
    """Return the chapter title shown by the reader."""
    locator = page.locator(".readerTopBar_title_chapter").first
    try:
        return (await locator.inner_text(timeout=1000)).strip()
    except Exception:
        return "Untitled chapter"


async def wait_for_captured_canvas_text(page: Page, wait_seconds: int) -> str:
    """Wait for all canvas blocks in the current reader turn to finish drawing."""
    deadline = asyncio.get_running_loop().time() + wait_seconds
    not_before = asyncio.get_running_loop().time() + min(wait_seconds, 3)
    previous = ""
    stable_polls = 0
    while True:
        text = await captured_canvas_text(page)
        if text:
            if text == previous:
                stable_polls += 1
                if (
                    asyncio.get_running_loop().time() >= not_before
                    and stable_polls >= 3
                ):
                    return text
            else:
                previous = text
                stable_polls = 0
        if asyncio.get_running_loop().time() >= deadline:
            return previous
        await page.wait_for_timeout(250)


async def wait_for_rendered_content(page: Page, wait_seconds: int) -> tuple[str, bool]:
    """Wait until text or canvas content is visible, then return its state."""
    deadline = asyncio.get_running_loop().time() + wait_seconds
    while True:
        text = await visible_content(page)
        if text:
            return text, False
        if await has_visible_canvas(page):
            return "", True
        if asyncio.get_running_loop().time() >= deadline:
            return "", False
        await page.wait_for_timeout(500)


async def wait_for_next_render(
    page: Page, previous_digest: str, wait_seconds: int
) -> tuple[str, str, bool, bytes | None, list[bytes], str]:
    """Poll until a different rendered state appears, tolerating slow networks."""
    deadline = asyncio.get_running_loop().time() + wait_seconds
    while True:
        direct_text = await wait_for_captured_canvas_text(page, 1)
        text, has_canvas = await wait_for_rendered_content(page, 1)
        if has_canvas:
            images = await capture_canvas_images(page)
            image = await capture_screenshot(page)
            digest_source = b"".join(images) if images else image or b""
        else:
            images = []
            image = None
            digest_source = text.encode("utf-8")
        digest = hashlib.sha256(digest_source).hexdigest()
        if (direct_text or text) and digest != previous_digest:
            return direct_text, text, has_canvas, image, images, digest
        if asyncio.get_running_loop().time() >= deadline:
            return direct_text, text, has_canvas, image, images, digest
        await page.wait_for_timeout(500)


async def capture_screenshot(page: Page, path: Path | None = None) -> bytes | None:
    """Capture a screenshot with a viewport fallback when full-page capture times out."""
    try:
        image = await page.screenshot(type="png", full_page=True, timeout=10000)
    except Exception as exc:
        logger.warning("Full-page screenshot failed; using viewport screenshot: %s", exc)
        try:
            image = await page.screenshot(type="png", full_page=False, timeout=10000)
        except Exception as fallback_exc:
            logger.warning("Viewport screenshot failed; continuing without PNG: %s", fallback_exc)
            return None
    if path is not None:
        path.write_bytes(image)
    return image


def build_offline_html(title: str, text: str, image: bytes | None) -> str:
    """Build a self-contained HTML page from rendered text or screenshot pixels."""
    escaped_title = html.escape(title)
    if image:
        encoded_image = base64.b64encode(image).decode("ascii")
        content = (
            f'<img src="data:image/png;base64,{encoded_image}" '
            f'alt="{escaped_title}" class="page-image">'
        )
    else:
        content = f'<pre class="page-text">{html.escape(text)}</pre>'
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escaped_title}</title>
  <style>
    html, body {{ margin: 0; background: #202124; color: #f1f3f4; }}
    main {{ display: flex; justify-content: center; min-height: 100vh; }}
    .page-image {{ display: block; width: auto; max-width: 100%; height: auto; }}
    .page-text {{ box-sizing: border-box; width: min(900px, 100%); margin: 0; padding: 32px;
      white-space: pre-wrap; overflow-wrap: anywhere; font: 18px/1.7 sans-serif; }}
  </style>
</head>
<body><main>{content}</main></body>
</html>
"""


def ensure_ocr_binary() -> Path:
    """Build the macOS Vision OCR helper when it is missing or outdated."""
    if not OCR_SOURCE.is_file():
        raise RuntimeError(f"OCR source was not found: {OCR_SOURCE}")
    if OCR_BINARY.is_file() and OCR_BINARY.stat().st_mtime >= OCR_SOURCE.stat().st_mtime:
        return OCR_BINARY
    logger.info("Building macOS Vision OCR helper.")
    result = subprocess.run(
        ["swiftc", str(OCR_SOURCE), "-o", str(OCR_BINARY)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "Could not build OCR helper")
    return OCR_BINARY


def recognize_image_text(image_path: Path, ocr_binary: Path) -> str:
    """Recognize English and Chinese text in one rendered page image."""
    result = subprocess.run(
        [str(ocr_binary), str(image_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        logger.warning("OCR failed for %s: %s", image_path, result.stderr.strip())
        return ""
    return result.stdout.strip()


def recognize_canvas_text(images: list[bytes], ocr_binary: Path) -> str:
    """Recognize text from canvas pixel buffers in document order."""
    texts: list[str] = []
    with tempfile.TemporaryDirectory(prefix="weread-ocr-") as temp_dir:
        temp_root = Path(temp_dir)
        for index, image in enumerate(images):
            image_path = temp_root / f"canvas_{index:03d}.png"
            image_path.write_bytes(image)
            text = recognize_image_text(image_path, ocr_binary)
            if text:
                texts.append(text)
    return "\n\n".join(texts)


async def save_rendered_page(
    page: Page,
    output_dir: Path,
    sequence: int,
    image: bytes | None,
    canvas_images: list[bytes],
    direct_text: str,
    chapter_title: str,
    save_screenshot: bool,
) -> str:
    """Save a self-contained HTML page and its extracted text or screenshot."""
    html_path = output_dir / f"page_{sequence:05d}.html"
    text_path = output_dir / f"page_{sequence:05d}.txt"
    text = direct_text or await visible_content(page)
    title = f"{await page.title()} - {chapter_title}"
    html_path.write_text(build_offline_html(title, text, image), encoding="utf-8")
    image_path = output_dir / f"page_{sequence:05d}.png"
    if image and (save_screenshot or not text):
        image_path.write_bytes(image)
    if not text and canvas_images:
        ocr_binary = await asyncio.to_thread(ensure_ocr_binary)
        text = await asyncio.to_thread(recognize_canvas_text, canvas_images, ocr_binary)
    elif not text and image:
        ocr_binary = await asyncio.to_thread(ensure_ocr_binary)
        text = await asyncio.to_thread(recognize_image_text, image_path, ocr_binary)
    page_text = f"# {chapter_title}\n\n{text}" if text else f"# {chapter_title}"
    text_path.write_text(page_text + "\n", encoding="utf-8")
    if not text:
        logger.warning("No text was recognized for rendered page %d", sequence)
    logger.info("Saved rendered page %d: %s and %s", sequence, html_path, text_path)
    return page_text


async def export_book(
    book_url: str,
    output_dir: Path,
    profile_dir: Path,
    max_pages: int,
    headed: bool,
    login_wait_seconds: int,
    save_json: bool,
    save_screenshot: bool,
    render_wait_seconds: int,
    from_start: bool,
) -> int:
    if async_playwright is None:
        logger.error("Playwright is not installed. Run: python3 -m pip install playwright")
        return 1
    output_dir.mkdir(parents=True, exist_ok=True)
    profile_dir.mkdir(parents=True, exist_ok=True)
    captured_hashes: set[str] = set()
    captured_count = 0
    exported_texts: list[str] = []
    last_new_response = asyncio.Event()

    async with async_playwright() as playwright:
        context: BrowserContext = await playwright.chromium.launch_persistent_context(
            user_data_dir=str(profile_dir),
            headless=not headed,
        )
        await context.add_init_script(CANVAS_TEXT_CAPTURE_SCRIPT)
        page = await context.new_page()

        async def handle_response(response: Response) -> None:
            nonlocal captured_count
            if urlparse(response.url).path != READ_PATH:
                return
            logger.info("Observed read response: status=%d url=%s", response.status, response.url)
            if response.status != 200:
                return
            try:
                body = await response.body()
            except Exception as exc:  # Playwright may close a response during navigation.
                logger.warning("Could not read response body: %s", exc)
                return
            digest = hashlib.sha256(body).hexdigest()
            if digest in captured_hashes:
                logger.info("Skipped duplicate response: %s", digest[:12])
                return
            captured_hashes.add(digest)
            captured_count += 1
            if save_json:
                path = save_response(output_dir, captured_count, response, body)
                logger.info("Saved response %d: %s", captured_count, path)
            last_new_response.set()

        context.on("response", handle_response)
        await page.goto(book_url, wait_until="domcontentloaded")
        await wait_for_login(page, login_wait_seconds)
        if from_start:
            await clear_captured_canvas_text(page)
            await go_to_book_start(page, render_wait_seconds)
        await enable_single_page_mode(page)
        current_text, current_canvas = await wait_for_rendered_content(page, render_wait_seconds)
        if not current_text and not current_canvas:
            logger.error("No visible reader content found; check login and page access.")
            await context.close()
            return 1
        current_image = await capture_screenshot(page)
        current_canvas_images = await capture_canvas_images(page) if current_canvas else []
        current_direct_text = (
            await wait_for_captured_canvas_text(page, render_wait_seconds)
            if current_canvas
            else ""
        )
        if current_canvas and not current_direct_text:
            logger.error("Canvas is visible but no text was drawn for the first page.")
            await context.close()
            return 1
        current_chapter = await current_chapter_title(page)
        current_digest = hashlib.sha256(
            b"".join(current_canvas_images)
            if current_canvas_images
            else current_image if current_canvas and current_image else current_text.encode("utf-8")
        ).hexdigest()
        exported_texts.append(
            await save_rendered_page(
                page,
                output_dir,
                1,
                current_image,
                current_canvas_images,
                current_direct_text,
                current_chapter,
                save_screenshot or current_canvas,
            )
        )
        for page_number in range(2, max_pages + 1):
            last_new_response.clear()
            await clear_captured_canvas_text(page)
            try:
                await page.keyboard.press("ArrowRight")
            except Exception as exc:
                logger.error("Could not advance to page %d: %s", page_number, exc)
                break
            try:
                await asyncio.wait_for(last_new_response.wait(), timeout=min(8, render_wait_seconds))
            except asyncio.TimeoutError:
                logger.info("No new interface response after page %d; checking visible content.", page_number)
            await page.wait_for_timeout(500)
            next_direct_text, next_text, next_canvas, next_image, next_canvas_images, next_digest = (
                await wait_for_next_render(page, current_digest, render_wait_seconds)
            )
            if next_canvas and not next_direct_text:
                logger.info("Canvas has no newly drawn text after page %d; stopping.", page_number)
                break
            if not next_text and not next_canvas:
                logger.info("No visible reader content after page %d; stopping.", page_number)
                break
            next_chapter = await current_chapter_title(page)
            if next_digest == current_digest:
                logger.info("No visible content change after page %d; stopping.", page_number)
                break
            current_digest = next_digest
            exported_texts.append(
                await save_rendered_page(
                    page,
                    output_dir,
                    page_number,
                    next_image,
                    next_canvas_images,
                    next_direct_text,
                    next_chapter,
                    save_screenshot or next_canvas,
                )
            )

        await context.close()

    book_text = "\n\n".join(text for text in exported_texts if text)
    (output_dir / "book.txt").write_text(book_text + "\n", encoding="utf-8")
    logger.info(
        "Export finished: %d rendered page(s), %d unique response(s).",
        len(exported_texts),
        captured_count,
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--book-url", default=DEFAULT_BOOK_URL)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("/Users/bianjq/work/activity/weread_export"),
    )
    parser.add_argument(
        "--profile-dir",
        type=Path,
        default=Path("/Users/bianjq/work/activity/weread_browser_profile"),
    )
    parser.add_argument("--max-pages", type=int, default=1000)
    parser.add_argument("--headed", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--save-json", action="store_true", help="Save matching interface responses")
    parser.add_argument("--save-screenshot", action="store_true", help="Save a PNG screenshot for each page")
    parser.add_argument("--render-wait-seconds", type=int, default=15)
    parser.add_argument(
        "--from-start",
        action="store_true",
        help="Open the first catalog chapter before exporting",
    )
    parser.add_argument(
        "--login-wait-seconds",
        type=int,
        default=60,
        help="Seconds to wait for browser login (default: 60)",
    )
    args = parser.parse_args()

    if args.max_pages < 1:
        parser.error("--max-pages must be at least 1")
    if args.login_wait_seconds < 0:
        parser.error("--login-wait-seconds must be non-negative")
    if args.render_wait_seconds < 1:
        parser.error("--render-wait-seconds must be at least 1")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    try:
        return asyncio.run(
            export_book(
                args.book_url,
                args.output_dir.resolve(),
                args.profile_dir.resolve(),
                args.max_pages,
                args.headed,
                args.login_wait_seconds,
                args.save_json,
                args.save_screenshot,
                args.render_wait_seconds,
                args.from_start,
            )
        )
    except Exception as exc:
        logger.error("Export failed: %s", exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

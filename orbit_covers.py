"""Course cover images from My Learning.

Covers are fetched by the signed-in My Learning page itself (in the app's isolated script world), so the
browser attaches the Orbit session exactly as it does for the page's own images and no copy of the login
cookies is made. Fetched images are kept in memory and, when a vault key is available, cached on disk as
AES-256-GCM blobs.
"""
import base64
import binascii
import hashlib
import re
import shutil
import time

from PySide6.QtCore import QObject, QRectF, QSize, Qt, QUrl, Signal
from PySide6.QtGui import QImage, QPainter, QPainterPath, QPixmap

COVER_PATH = re.compile(r"/assets/img/course/[\w-]{1,100}")
MAX_BYTES = 4 * 1024 * 1024
CACHE_BYTES = 32 * 1024 * 1024
REQUEST_TIMEOUT = 45


def fill_thumbnail(pixmap, size, radius, ratio=1.0):
    """Crop-to-fill and round a cover at the screen's pixel density, with smooth scaling."""
    width, height = size.width(), size.height()
    target = QPixmap(round(width * ratio), round(height * ratio))
    target.fill(Qt.GlobalColor.transparent)
    scaled = pixmap.scaled(target.size(), Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                           Qt.TransformationMode.SmoothTransformation)
    painter = QPainter(target)
    painter.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform)
    clip = QPainterPath()
    clip.addRoundedRect(QRectF(0, 0, target.width(), target.height()), radius * ratio, radius * ratio)
    painter.setClipPath(clip)
    painter.drawPixmap((target.width() - scaled.width()) // 2, (target.height() - scaled.height()) // 2, scaled)
    painter.end()
    target.setDevicePixelRatio(ratio)
    return target


class CoverStore(QObject):
    changed = Signal()

    def __init__(self, origin, cache_dir, vault=None, request=None, parent=None):
        super().__init__(parent)
        self.origin = QUrl(origin)
        self.vault = vault if vault is not None and vault.available else None
        self.cache_dir = cache_dir
        if self.vault:
            cache_dir.mkdir(parents=True, exist_ok=True)
        shutil.rmtree(cache_dir.with_name("covers-cache"), ignore_errors=True)  # older readable cache
        self.request = request or (lambda url: False)
        self.urls = {}
        self.images = {}
        self.pending = {}   # url -> time sent (0 while queued)
        self.thumbs = {}

    def allowed(self, url):
        return (url.isValid() and (url.scheme(), url.host(), url.port()) ==
                (self.origin.scheme(), self.origin.host(), self.origin.port())
                and not url.userInfo() and COVER_PATH.fullmatch(url.path()) is not None
                and len(url.toString()) <= 2048)

    def set_cover(self, course, address):
        url = QUrl(address) if isinstance(address, str) else QUrl()
        if not self.allowed(url):
            return
        key = url.toString()
        self.urls[course] = key
        if key in self.images or self.load_cached(key):
            return
        sent = self.pending.get(key)
        if sent is None or (sent and time.monotonic() - sent > REQUEST_TIMEOUT):
            self.pending[key] = 0
        self.flush()

    def flush(self):
        """Send queued requests through the signed-in page; anything it cannot take yet stays queued."""
        for key, sent in list(self.pending.items()):
            if not sent and self.request(key):
                self.pending[key] = time.monotonic()

    def receive(self, address, status, encoded):
        key = QUrl(address).toString()
        if key not in self.pending:
            return  # Only answers to our own requests are accepted.
        del self.pending[key]
        if status != 200 or len(encoded) > MAX_BYTES * 4 // 3 + 4:
            return
        try:
            data = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError):
            return
        image = QImage()
        if len(data) > MAX_BYTES or not image.loadFromData(data):
            return
        if image.width() > 640:
            image = image.scaledToWidth(640, Qt.TransformationMode.SmoothTransformation)
        self.images[key] = QPixmap.fromImage(image)
        self.save_cached(key, data)
        self.changed.emit()

    def cache_file(self, key):
        return self.cache_dir / (hashlib.sha256(key.encode()).hexdigest() + ".bin")

    def load_cached(self, key):
        if not self.vault:
            return False
        path = self.cache_file(key)
        try:
            data = self.vault.decrypt(path.read_bytes(), b"cover:" + key.encode())
        except FileNotFoundError:
            return False
        except Exception:  # Tampered, truncated or from another key: drop it and refetch.
            path.unlink(missing_ok=True)
            return False
        image = QImage()
        if not image.loadFromData(data):
            return False
        self.images[key] = QPixmap.fromImage(image)
        path.touch()
        self.changed.emit()
        return True

    def save_cached(self, key, data):
        if not self.vault:
            return
        try:
            self.vault.write(self.cache_file(key), data, b"cover:" + key.encode())
            files = sorted(self.cache_dir.glob("*.bin"), key=lambda item: item.stat().st_mtime)
            total = sum(item.stat().st_size for item in files)
            while files and total > CACHE_BYTES:
                oldest = files.pop(0)
                total -= oldest.stat().st_size
                oldest.unlink(missing_ok=True)
        except OSError:
            pass

    def thumbnail(self, course, size, radius=6, ratio=1.0):
        """Return a cached rounded thumbnail for a course path, or None until its cover has loaded."""
        key = self.urls.get(course)
        pixmap = self.images.get(key) if key else None
        if pixmap is None:
            return None
        cache_key = (key, size.width(), size.height(), radius, ratio)
        if cache_key not in self.thumbs:
            if len(self.thumbs) > 600:
                self.thumbs.clear()
            self.thumbs[cache_key] = fill_thumbnail(pixmap, QSize(size), radius, ratio)
        return self.thumbs[cache_key]

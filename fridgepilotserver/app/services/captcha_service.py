from __future__ import annotations

import base64
import io
import logging
import math
import random
import secrets
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter

from app.common.api_codes import ApiCode
from app.common.response import ApiException

logger = logging.getLogger(__name__)

BG_WIDTH = 320
BG_HEIGHT = 168
PIECE_SIZE = 60
PIECE_PAD = 10
TOLERANCE_PX = 5
TTL_SECONDS = 300

# 验证码背景图只放后端 assets/captcha/，前端不再持有原图；新增素材只改这一处。
BG_DIR = Path(__file__).resolve().parents[1] / "assets" / "captcha"
_BG_GLOBS = ("*.jpg", "*.jpeg", "*.png", "*.webp")
_MAX_BG_PIXELS = 4_000_000

_OFFSET_X_MIN = PIECE_SIZE + 20
_OFFSET_X_MAX = BG_WIDTH - PIECE_SIZE - 16
_OFFSET_Y_MIN = 16
_OFFSET_Y_MAX = BG_HEIGHT - PIECE_SIZE - 16

# 限流：创建 / 失败（按 client_key，通常为 IP）
_CREATE_LIMIT = 20
_CREATE_WINDOW_S = 60.0
_FAIL_LIMIT = 5
_FAIL_WINDOW_S = 60.0
_LOCK_SECONDS = 60.0


@dataclass
class CaptchaChallenge:
    captcha_id: str
    offset_x: int
    offset_y: int
    expires_at: float  # time.monotonic() 截止
    consumed: bool = False
    verified: bool = False
    verified_x: float | None = None


@dataclass
class _RateBucket:
    create_times: list[float] = field(default_factory=list)
    fail_times: list[float] = field(default_factory=list)
    locked_until: float = 0.0


class CaptchaError(ApiException):
    """Captcha-domain API error."""


class CaptchaService:
    """内存版滑块拼图验证码（单进程开发足够；多实例需换 Redis 等）。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._challenges: dict[str, CaptchaChallenge] = {}
        self._rate: dict[str, _RateBucket] = {}
        # path → (mtime, cover 缩放后的 RGBA 大图)
        self._scaled_cache: dict[str, tuple[float, Image.Image]] = {}
        self._bg_paths = self._discover_backgrounds()
        if self._bg_paths:
            logger.info(
                "discovered %d captcha backgrounds from %s",
                len(self._bg_paths),
                BG_DIR,
            )
        else:
            logger.warning(
                "no captcha backgrounds found in %s — create() will fail until assets are added",
                BG_DIR,
            )

    def reset_for_tests(self) -> None:
        """测试夹具：清空挑战与限流状态（不重新扫盘）。"""
        with self._lock:
            self._challenges.clear()
            self._rate.clear()

    def create(self, *, client_key: str = "unknown") -> dict:
        now = time.monotonic()
        with self._lock:
            self._purge_expired_unlocked(now)
            self._assert_not_locked_unlocked(client_key, now)
            self._assert_create_allowed_unlocked(client_key, now)

            offset_x = _secure_randint(_OFFSET_X_MIN, _OFFSET_X_MAX)
            offset_y = _secure_randint(_OFFSET_Y_MIN, _OFFSET_Y_MAX)
            captcha_id = secrets.token_urlsafe(16)
            self._challenges[captcha_id] = CaptchaChallenge(
                captcha_id=captcha_id,
                offset_x=offset_x,
                offset_y=offset_y,
                expires_at=now + TTL_SECONDS,
            )

        # 渲染放锁外，避免 PIL 阻塞其他请求
        try:
            bg, piece = self._render(offset_x, offset_y)
        except CaptchaError:
            with self._lock:
                self._challenges.pop(captcha_id, None)
            raise
        except Exception:
            with self._lock:
                self._challenges.pop(captcha_id, None)
            raise

        return {
            "captcha_id": captcha_id,
            "bg_image": self._to_data_url(bg),
            "piece_image": self._to_data_url(piece),
            # piece_y 仅供前端定位，不参与安全判定
            "piece_y": offset_y,
            "piece_pad": PIECE_PAD,
            "bg_width": BG_WIDTH,
            "bg_height": BG_HEIGHT,
            "piece_size": PIECE_SIZE,
        }

    def check(
        self,
        captcha_id: str,
        offset_x: float,
        *,
        client_key: str = "unknown",
    ) -> None:
        """松手时校验：通过则标记 verified，题目仍保留供登录消费。"""
        x = self._parse_offset(offset_x, client_key=client_key)
        now = time.monotonic()
        with self._lock:
            challenge = self._require_challenge_unlocked(captcha_id, client_key=client_key, now=now)
            if abs(x - challenge.offset_x) > TOLERANCE_PX:
                self._challenges.pop(captcha_id, None)
                logger.info(
                    "captcha check mismatch id=%s… key=%s",
                    captcha_id[:8],
                    client_key,
                )
                self._register_failure_unlocked(client_key, now)
                raise CaptchaError(
                    ApiCode.CAPTCHA_FAILED, "位置不太对，已换一题，请再试一次"
                )
            challenge.verified = True
            challenge.verified_x = x

    def verify_and_consume(
        self,
        captcha_id: str,
        offset_x: float,
        *,
        client_key: str = "unknown",
    ) -> None:
        """登录时最终消费：须位置正确（可先经 check 标记）。"""
        x = self._parse_offset(offset_x, client_key=client_key)
        now = time.monotonic()
        with self._lock:
            challenge = self._require_challenge_unlocked(captcha_id, client_key=client_key, now=now)
            if abs(x - challenge.offset_x) > TOLERANCE_PX:
                self._challenges.pop(captcha_id, None)
                logger.info(
                    "captcha consume mismatch id=%s… key=%s",
                    captcha_id[:8],
                    client_key,
                )
                self._register_failure_unlocked(client_key, now)
                raise CaptchaError(ApiCode.CAPTCHA_FAILED)
            if challenge.verified and challenge.verified_x is not None:
                if abs(x - challenge.verified_x) > TOLERANCE_PX:
                    self._challenges.pop(captcha_id, None)
                    self._register_failure_unlocked(client_key, now)
                    raise CaptchaError(ApiCode.CAPTCHA_FAILED)
            challenge.consumed = True
            self._challenges.pop(captcha_id, None)

    def _parse_offset(self, offset_x: float, *, client_key: str) -> float:
        try:
            x = float(offset_x)
        except (TypeError, ValueError):
            logger.info("captcha rejected reason=bad_x key=%s", client_key)
            self._register_failure(client_key)
            raise CaptchaError(ApiCode.CAPTCHA_FAILED) from None
        if not math.isfinite(x):
            logger.info("captcha rejected reason=non_finite_x key=%s", client_key)
            self._register_failure(client_key)
            raise CaptchaError(ApiCode.CAPTCHA_FAILED)
        return x

    def _require_challenge_unlocked(
        self,
        captcha_id: str,
        *,
        client_key: str,
        now: float,
    ) -> CaptchaChallenge:
        self._assert_not_locked_unlocked(client_key, now)
        if not isinstance(captcha_id, str) or not (8 <= len(captcha_id) <= 64):
            logger.info("captcha rejected reason=bad_id key=%s", client_key)
            raise CaptchaError(ApiCode.CAPTCHA_FAILED)
        challenge = self._challenges.get(captcha_id)
        if challenge is None:
            logger.info("captcha rejected reason=invalid id=%s… key=%s", captcha_id[:8], client_key)
            self._register_failure_unlocked(client_key, now)
            raise CaptchaError(ApiCode.CAPTCHA_FAILED)
        if challenge.consumed:
            logger.info("captcha rejected reason=used id=%s… key=%s", captcha_id[:8], client_key)
            self._register_failure_unlocked(client_key, now)
            raise CaptchaError(ApiCode.CAPTCHA_FAILED)
        if challenge.expires_at < now:
            self._challenges.pop(captcha_id, None)
            logger.info("captcha rejected reason=expired id=%s… key=%s", captcha_id[:8], client_key)
            self._register_failure_unlocked(client_key, now)
            raise CaptchaError(ApiCode.CAPTCHA_FAILED)
        return challenge

    def _register_failure(self, client_key: str) -> None:
        with self._lock:
            self._register_failure_unlocked(client_key, time.monotonic())

    def _register_failure_unlocked(self, client_key: str, now: float) -> None:
        bucket = self._rate.setdefault(client_key, _RateBucket())
        bucket.fail_times = [t for t in bucket.fail_times if now - t <= _FAIL_WINDOW_S]
        bucket.fail_times.append(now)
        if len(bucket.fail_times) >= _FAIL_LIMIT:
            bucket.locked_until = max(bucket.locked_until, now + _LOCK_SECONDS)
            bucket.fail_times.clear()
            logger.warning(
                "captcha locked key=%s for %.0fs after %d failures",
                client_key,
                _LOCK_SECONDS,
                _FAIL_LIMIT,
            )

    def _assert_not_locked_unlocked(self, client_key: str, now: float) -> None:
        bucket = self._rate.get(client_key)
        if bucket is None:
            return
        if bucket.locked_until > now:
            remain = max(1, int(bucket.locked_until - now))
            mins = max(1, (remain + 59) // 60)
            raise CaptchaError(
                ApiCode.CAPTCHA_LOCKED,
                f"尝试次数较多，请约 {mins} 分钟后再试",
            )

    def _assert_create_allowed_unlocked(self, client_key: str, now: float) -> None:
        bucket = self._rate.setdefault(client_key, _RateBucket())
        bucket.create_times = [t for t in bucket.create_times if now - t <= _CREATE_WINDOW_S]
        if len(bucket.create_times) >= _CREATE_LIMIT:
            raise CaptchaError(ApiCode.CAPTCHA_RATE_LIMITED)
        bucket.create_times.append(now)

    def _purge_expired_unlocked(self, now: float) -> None:
        expired = [cid for cid, c in self._challenges.items() if c.expires_at < now]
        for cid in expired:
            self._challenges.pop(cid, None)

    @classmethod
    def _discover_backgrounds(cls) -> list[Path]:
        if not BG_DIR.is_dir():
            return []
        paths: list[Path] = []
        seen: set[str] = set()
        for pattern in _BG_GLOBS:
            for path in BG_DIR.glob(pattern):
                key = str(path.resolve())
                if key in seen:
                    continue
                seen.add(key)
                paths.append(path)
        return sorted(paths, key=lambda p: p.name)

    def _cover_scaled(self, path: Path) -> Image.Image:
        key = str(path.resolve())
        mtime = path.stat().st_mtime
        cached = self._scaled_cache.get(key)
        if cached is not None and cached[0] == mtime:
            return cached[1]

        src = Image.open(path).convert("RGB")
        pixels = src.width * src.height
        if pixels > _MAX_BG_PIXELS:
            factor = math.sqrt(_MAX_BG_PIXELS / pixels)
            src = src.resize(
                (max(1, int(src.width * factor)), max(1, int(src.height * factor))),
                Image.Resampling.LANCZOS,
            )
            logger.info(
                "captcha bg downscaled path=%s from_pixels=%d",
                path.name,
                pixels,
            )

        scale = max(BG_WIDTH / src.width, BG_HEIGHT / src.height)
        new_w = max(BG_WIDTH, int(round(src.width * scale)))
        new_h = max(BG_HEIGHT, int(round(src.height * scale)))
        resized = src.resize((new_w, new_h), Image.Resampling.LANCZOS).convert("RGBA")
        self._scaled_cache[key] = (mtime, resized)
        return resized

    def _load_background(self) -> Image.Image:
        if not self._bg_paths:
            raise CaptchaError(
                ApiCode.CAPTCHA_ASSET_MISSING,
                f"验证码背景图未配置，请将图片放到 {BG_DIR.as_posix()}",
            )
        path = random.choice(self._bg_paths)
        resized = self._cover_scaled(path)
        max_x = max(0, resized.width - BG_WIDTH)
        max_y = max(0, resized.height - BG_HEIGHT)
        x = random.randint(0, max_x) if max_x else 0
        y = random.randint(0, max_y) if max_y else 0
        return resized.crop((x, y, x + BG_WIDTH, y + BG_HEIGHT))

    def _render(self, offset_x: int, offset_y: int) -> tuple[Image.Image, Image.Image]:
        raw = self._load_background()
        soft = self._piece_mask(PIECE_SIZE)
        hard = soft.point(lambda p: 255 if p > 128 else 0)

        crop = raw.crop((offset_x, offset_y, offset_x + PIECE_SIZE, offset_y + PIECE_SIZE))
        piece_core = Image.new("RGBA", (PIECE_SIZE, PIECE_SIZE), (0, 0, 0, 0))
        piece_core.paste(crop, (0, 0), soft)

        bg = raw.copy()
        bg.alpha_composite(self._hole_overlay(hard), (offset_x, offset_y))

        pad = PIECE_PAD
        canvas = Image.new("RGBA", (PIECE_SIZE + pad * 2, PIECE_SIZE + pad * 2), (0, 0, 0, 0))

        shadow = Image.new("RGBA", (PIECE_SIZE, PIECE_SIZE), (0, 0, 0, 0))
        shadow.paste((0, 0, 0, 110), (0, 0), hard)
        shadow = shadow.filter(ImageFilter.GaussianBlur(2.4))
        canvas.alpha_composite(shadow, (pad + 2, pad + 3))

        canvas.paste((255, 255, 255, 245), (pad, pad), self._expand(hard, 1))
        canvas.paste((25, 32, 48, 200), (pad, pad), hard)
        canvas.alpha_composite(piece_core, (pad, pad))
        return bg, canvas

    def _hole_overlay(self, hard: Image.Image) -> Image.Image:
        """半透明深底 + 内阴影 + 细亮描边。"""
        hole = Image.new("RGBA", (PIECE_SIZE, PIECE_SIZE), (0, 0, 0, 0))
        hole.paste((12, 16, 28, 175), (0, 0), hard)

        inset = ImageChops.subtract(hard, self._erode(hard, 5))
        inset = inset.filter(ImageFilter.GaussianBlur(1.6))
        shade = Image.new("RGBA", (PIECE_SIZE, PIECE_SIZE), (0, 0, 0, 0))
        shade.paste((0, 0, 0, 150), (0, 0), inset)
        hole = Image.alpha_composite(hole, shade)

        rim = Image.new("RGBA", (PIECE_SIZE, PIECE_SIZE), (0, 0, 0, 0))
        rim.paste((255, 255, 255, 230), (0, 0), self._ring(hard, outer=2, inner=0))
        hole = Image.alpha_composite(hole, rim)

        inner_rim = Image.new("RGBA", (PIECE_SIZE, PIECE_SIZE), (0, 0, 0, 0))
        inner_rim.paste((0, 0, 0, 110), (0, 0), ImageChops.subtract(hard, self._erode(hard, 1)))
        return Image.alpha_composite(hole, inner_rim)

    def _piece_mask(self, size: int) -> Image.Image:
        """标准拼图块：方身 + 圆头窄颈榫卯（右/下凸，左/上凹）。"""
        scale = 8
        s = size * scale
        mask = Image.new("L", (s, s), 0)
        ImageDraw.Draw(mask).polygon(self._jigsaw_outline(s), fill=255)
        mask = mask.resize((size, size), Image.Resampling.LANCZOS)
        mask = mask.point(lambda p: 255 if p >= 128 else 0)
        return mask.filter(ImageFilter.GaussianBlur(0.25))

    @classmethod
    def _jigsaw_outline(cls, s: int) -> list[tuple[float, float]]:
        """闭合轮廓：真实拼图那种圆头 + 窄颈。"""
        r = s * 0.162
        m = r * 1.62
        x0, y0 = m, m
        x1, y1 = s - m, s - m
        mx, my = (x0 + x1) / 2, (y0 + y1) / 2
        neck = r * 0.48

        pts: list[tuple[float, float]] = [(x0, y0)]

        pts.append((mx - neck, y0))
        pts.extend(cls._knob_curve(mx, y0, r, neck, direction=(0, 1), reverse=True))
        pts.append((x1, y0))

        pts.append((x1, my - neck))
        pts.extend(cls._knob_curve(x1, my, r, neck, direction=(1, 0)))
        pts.append((x1, y1))

        pts.append((mx + neck, y1))
        pts.extend(cls._knob_curve(mx, y1, r, neck, direction=(0, 1)))
        pts.append((x0, y1))

        pts.append((x0, my + neck))
        pts.extend(cls._knob_curve(x0, my, r, neck, direction=(1, 0), reverse=True))
        pts.append((x0, y0))
        return pts

    @staticmethod
    def _knob_curve(
        cx: float,
        cy: float,
        r: float,
        neck: float,
        *,
        direction: tuple[int, int],
        reverse: bool = False,
    ) -> list[tuple[float, float]]:
        """从颈的一侧绕到另一侧，画出圆头窄颈。"""
        dx, dy = direction
        tx, ty = -dy, dx

        def pt(along: float, out: float) -> tuple[float, float]:
            return (cx + tx * along + dx * out, cy + ty * along + dy * out)

        tip = r * 1.18
        p0 = pt(-neck, 0)
        c1 = pt(-neck * 0.92, -r * 0.16)
        c2 = pt(-r * 0.78, tip * 0.88)
        p1 = pt(0, tip)
        c3 = pt(r * 0.78, tip * 0.88)
        c4 = pt(neck * 0.92, -r * 0.16)
        p2 = pt(neck, 0)

        def bez(
            a: tuple[float, float],
            b: tuple[float, float],
            c: tuple[float, float],
            d: tuple[float, float],
            steps: int = 18,
        ) -> list[tuple[float, float]]:
            out: list[tuple[float, float]] = []
            for i in range(1, steps + 1):
                t = i / steps
                u = 1 - t
                out.append(
                    (
                        u**3 * a[0] + 3 * u**2 * t * b[0] + 3 * u * t**2 * c[0] + t**3 * d[0],
                        u**3 * a[1] + 3 * u**2 * t * b[1] + 3 * u * t**2 * c[1] + t**3 * d[1],
                    )
                )
            return out

        curve = bez(p0, c1, c2, p1) + bez(p1, c3, c4, p2)
        if reverse:
            curve.reverse()
        return curve

    @staticmethod
    def _expand(mask: Image.Image, pixels: int) -> Image.Image:
        if pixels <= 0:
            return mask
        return mask.filter(ImageFilter.MaxFilter(pixels * 2 + 1))

    @staticmethod
    def _erode(mask: Image.Image, pixels: int) -> Image.Image:
        if pixels <= 0:
            return mask
        return mask.filter(ImageFilter.MinFilter(pixels * 2 + 1))

    def _ring(self, mask: Image.Image, *, outer: int, inner: int) -> Image.Image:
        outer_m = self._expand(mask, outer)
        inner_m = self._expand(mask, inner) if inner > 0 else mask
        return ImageChops.subtract(outer_m, inner_m)

    @staticmethod
    def _to_data_url(image: Image.Image) -> str:
        buf = io.BytesIO()
        image.save(buf, format="PNG", optimize=True)
        b64 = base64.b64encode(buf.getvalue()).decode("ascii")
        return f"data:image/png;base64,{b64}"


def _secure_randint(lo: int, hi: int) -> int:
    """含上下界的密码学安全整数。"""
    if hi < lo:
        raise ValueError("hi < lo")
    return lo + secrets.randbelow(hi - lo + 1)


_captcha_service = CaptchaService()


def get_captcha_service() -> CaptchaService:
    return _captcha_service

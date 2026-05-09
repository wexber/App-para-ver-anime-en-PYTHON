from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
import json
import multiprocessing as mp
import queue
import random
import re
import time
from io import BytesIO
from typing import Any
from urllib.error import URLError
from urllib.parse import quote_plus, urljoin
from urllib.request import Request, urlopen
import tkinter as tk
from tkinter import messagebox, ttk
import os
import subprocess
import shutil
import threading
import webbrowser

import cloudscraper
from bs4 import BeautifulSoup
from PIL import Image, ImageDraw, ImageFont, ImageTk


APP_TITLE = "AnimeFLV Player"
WINDOW_SIZE = "1440x920"
BG = "#04060b"
PANEL = "#0c1220"
PANEL_2 = "#121a2b"
PANEL_3 = "#182437"
TEXT = "#f8fafc"
MUTED = "#9aa7bd"
ACCENT = "#e50914"
ACCENT_2 = "#f5c542"
SERVER_PREFERENCE = (
    "sw",
    "mega",
    "okru",
    "yu",
    "maru",
    "fembed",
    "netu",
)
QUALITY_PREFERENCE = (
    "1080",
    "720",
    "480",
    "360",
    "240",
)
BLOCKED_SERVERS = {"stape"}
EMBED_BLOCKED_HOSTS = ("streamwish",)
CATALOG_FALLBACK_QUERIES = (
    "naruto",
    "one piece",
    "bleach",
    "dragon ball",
    "jujutsu kaisen",
    "kimetsu no yaiba",
    "shingeki no kyojin",
    "chainsaw man",
    "boku no hero",
    "fullmetal alchemist",
)


def clear_broken_proxy_env() -> None:
    for name in (
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
    ):
        value = os.environ.get(name)
        if value and ("127.0.0.1:9" in value or "localhost:9" in value):
            os.environ.pop(name, None)


clear_broken_proxy_env()


def find_brave_executable() -> str | None:
    candidates = [
        shutil.which("brave"),
        shutil.which("brave.exe"),
        shutil.which("brave-browser"),
        r"C:\\Program Files\\BraveSoftware\\Brave-Browser\\Application\\brave.exe",
        r"C:\\Program Files (x86)\\BraveSoftware\\Brave-Browser\\Application\\brave.exe",
    ]
    for candidate in candidates:
        if candidate and os.path.exists(candidate):
            return candidate
    return None


def open_in_brave(url: str) -> subprocess.Popen | None:
    brave = find_brave_executable()
    if not brave:
        return None
    try:
        return subprocess.Popen(
            [
                brave,
                f"--app={url}",
                "--window-size=1280,720",
                "--start-maximized",
            ],
            close_fds=True,
        )
    except Exception:
        return None


def run_webview_player(url: str, title: str) -> None:
    import webview

    webview.create_window(
        title or "Reproductor",
        url=url,
        width=1280,
        height=720,
        on_top=True,
        confirm_close=True,
    )
    webview.start()


@dataclass
class AnimeEntry:
    id: str = ""
    title: str = ""
    cover: str = ""
    synopsis: str = ""
    rating: str = ""
    type: str = ""
    url: str = ""
    source: str = ""
    raw: Any = None
    episodes: list[dict[str, Any]] = field(default_factory=list)
    genres: list[str] = field(default_factory=list)
    status: str = ""
    alternative_titles: list[str] = field(default_factory=list)


def safe_text(value: Any, fallback: str = "") -> str:
    if value is None:
        return fallback
    if isinstance(value, (list, tuple)):
        return ", ".join(safe_text(item) for item in value if item is not None)
    return str(value)


def make_placeholder(size: tuple[int, int], title: str = "AnimeFLV") -> Image.Image:
    width, height = size
    img = Image.new("RGB", size, "#1b2434")
    draw = ImageDraw.Draw(img)
    draw.rectangle((0, 0, width, height), fill="#1b2434")
    draw.rectangle((0, 0, width, 16), fill=ACCENT)
    draw.rectangle((0, height - 22, width, height), fill="#0f172a")
    draw.ellipse((-70, -40, 220, 250), fill="#273449")
    draw.ellipse((width - 180, height - 180, width + 60, height + 60), fill="#334155")
    label = title.strip() or "AnimeFLV"
    font = ImageFont.load_default()
    text = label[:32]
    text_box = draw.textbbox((0, 0), text, font=font)
    text_w = text_box[2] - text_box[0]
    text_h = text_box[3] - text_box[1]
    draw.rounded_rectangle(
        (
            (width - text_w) / 2 - 16,
            (height - text_h) / 2 - 12,
            (width + text_w) / 2 + 16,
            (height + text_h) / 2 + 12,
        ),
        radius=16,
        fill="#0f172acc",
    )
    draw.text(((width - text_w) / 2, (height - text_h) / 2), text, font=font, fill=TEXT)
    return img


def load_image_from_url(url: str, size: tuple[int, int], referer: str | None = None) -> Image.Image:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
    }
    if referer:
        headers["Referer"] = referer
    request = Request(url, headers=headers)
    with urlopen(request, timeout=15) as response:
        payload = response.read()
    image = Image.open(BytesIO(payload)).convert("RGB")
    image.thumbnail(size, Image.LANCZOS)
    canvas = make_placeholder(size)
    x = (size[0] - image.width) // 2
    y = (size[1] - image.height) // 2
    canvas.paste(image, (x, y))
    return canvas


def normalize_episode_id(item: Any) -> str:
    if isinstance(item, dict):
        for key in ("id", "episodeId", "episode_id", "epsId", "eps_id", "slug"):
            value = item.get(key)
            if value:
                return str(value)
        anime_id = safe_text(item.get("animeId") or item.get("anime_id"))
        number = safe_text(item.get("episode") or item.get("index") or item.get("number"))
        if anime_id and number:
            return f"{anime_id}-{number}"
    return safe_text(item)


def normalize_episode_item(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        episode_id = normalize_episode_id(raw)
        label = (
            safe_text(raw.get("title"))
            or safe_text(raw.get("episode"))
            or safe_text(raw.get("index"))
            or episode_id
        )
        return {
            "id": episode_id,
            "label": label,
            "number": safe_text(raw.get("episode") or raw.get("index") or raw.get("number")),
            "url": safe_text(raw.get("url") or raw.get("link")),
            "raw": raw,
        }

    text = safe_text(raw)
    return {"id": text, "label": text, "number": "", "url": "", "raw": raw}


def normalize_entry(raw: Any) -> AnimeEntry:
    if isinstance(raw, AnimeEntry):
        return raw

    if isinstance(raw, dict):
        source = safe_text(raw.get("source") or raw.get("provider") or raw.get("origin"))
        url = safe_text(raw.get("url") or raw.get("link"))
        if not source:
            if "tioanime.com" in url:
                source = "TioAnime"
            elif "jkanime.net" in url or "jkanime.org" in url:
                source = "JkAnime"
            else:
                source = "AnimeFLV"
        entry = AnimeEntry(
            id=safe_text(
                raw.get("id")
                or raw.get("animeId")
                or raw.get("anime_id")
                or raw.get("title")
            ),
            title=safe_text(raw.get("title") or raw.get("anime") or raw.get("label")),
            cover=safe_text(raw.get("cover") or raw.get("poster") or raw.get("image")),
            synopsis=safe_text(
                raw.get("synopsis")
                or raw.get("description")
                or raw.get("synopsys")
                or raw.get("summary")
            ),
            rating=safe_text(raw.get("rating") or raw.get("score") or raw.get("punctuation")),
            type=safe_text(raw.get("type")),
            url=url,
            source=source,
            raw=raw,
        )
        if isinstance(raw.get("episodes"), list):
            entry.episodes = [normalize_episode_item(ep) for ep in raw["episodes"]]
        if isinstance(raw.get("genres"), list):
            entry.genres = [safe_text(item) for item in raw["genres"] if item is not None]
        if isinstance(raw.get("alternative_titles"), list):
            entry.alternative_titles = [
                safe_text(item) for item in raw["alternative_titles"] if item is not None
            ]
        entry.status = safe_text(raw.get("status") or raw.get("state"))
        return entry

    return AnimeEntry(title=safe_text(raw), id=safe_text(raw), raw=raw)


class AnimeFLVClient:
    def __init__(self):
        self._search_base_url = "https://www4.animeflv.net"
        self._detail_base_url = "https://animeflv.net"
        self._info_cache: dict[str, dict[str, Any]] = {}

    def search(self, query: str) -> list[Any]:
        query = query.strip()
        if not query:
            return []
        last_results: list[Any] = []
        for attempt in range(5):
            last_results = self._search_remote(query)
            if last_results:
                return last_results
            if attempt < 4:
                time.sleep(0.5)
        return last_results

    def catalog(self, limit: int = 10) -> list[Any]:
        return self.catalog_page(1, limit=limit)

    def catalog_page(self, page: int = 1, limit: int = 10) -> list[Any]:
        seen: set[str] = set()
        collected: list[Any] = []

        def add_items(items: list[Any]) -> None:
            for item in items:
                normalized = normalize_entry(item)
                key = self._normalize_cache_key(normalized.id or normalized.url or normalized.title)
                if not key or key in seen:
                    continue
                seen.add(key)
                collected.append(normalized.raw if normalized.raw is not None else item)
                if len(collected) >= limit:
                    return

        try:
            add_items(self._browse_remote(page=page))
        except Exception:
            pass

        if len(collected) < limit and page == 1:
            for query in CATALOG_FALLBACK_QUERIES:
                try:
                    add_items(self._search_remote(query))
                except Exception:
                    continue
                if len(collected) >= limit:
                    break

        return collected[:limit]

    def random_anime(self) -> Any:
        max_pages = self._browse_page_count()
        for _attempt in range(6):
            page = random.randint(1, max_pages) if max_pages > 1 else 1
            try:
                candidates = self._browse_remote(page=page)
            except Exception:
                continue
            if not candidates:
                continue
            chosen = normalize_entry(random.choice(candidates))
            if chosen.title and chosen.url:
                return chosen
        raise RuntimeError("No se pudo seleccionar un anime aleatorio.")

    def info(self, anime_id: str) -> Any:
        cache_key = self._normalize_cache_key(anime_id)
        fresh = {}
        for attempt in range(5):
            fresh = self._anime_detail_remote(anime_id)
            if fresh.get("episodes") or attempt == 4:
                break
            time.sleep(0.5)
        cached = self._info_cache.get(cache_key)
        if cached:
            if not fresh.get("episodes") and cached.get("episodes"):
                fresh["episodes"] = cached["episodes"]
            if not fresh.get("synopsis") and cached.get("synopsis"):
                fresh["synopsis"] = cached["synopsis"]
            if not fresh.get("cover") and cached.get("cover"):
                fresh["cover"] = cached["cover"]
        if fresh.get("episodes") or cached is None:
            self._info_cache[cache_key] = dict(fresh)
        return fresh

    def episode_servers(self, episode_id: str) -> list[Any]:
        return self._episode_servers_remote(episode_id)

    def download_links(self, episode_id: str) -> list[Any]:
        return self._download_links_remote(episode_id)

    def close(self) -> None:
        return None

    def _get_soup(self, url: str) -> BeautifulSoup:
        response = cloudscraper.create_scraper().get(url, timeout=20)
        return BeautifulSoup(response.text, "lxml")

    @staticmethod
    def _extract_image_url(node: Any) -> str:
        if node is None:
            return ""
        for attr in ("src", "data-src", "data-original", "data-lazy-src", "data-cfsrc", "content"):
            value = safe_text(node.get(attr))
            if value:
                return value
        return ""

    def _browse_remote(self, page: int = 1) -> list[dict[str, Any]]:
        url = f"{self._search_base_url}/browse"
        if page > 1:
            url = f"{url}?page={page}"
        soup = self._get_soup(url)
        results: list[dict[str, Any]] = []
        for article in soup.select("div.Container ul.ListAnimes li article"):
            anchor = article.select_one("a[href]")
            if not anchor:
                continue
            title_node = article.select_one("h3.Title") or article.select_one("div.Description .Title strong")
            description_node = article.select_one("div.Description p:nth-of-type(2)")
            type_node = article.select_one("span.Type")
            rating_node = article.select_one("span.Vts")
            cover_node = article.select_one("img")
            href = urljoin(self._detail_base_url, anchor.get("href", ""))
            title = safe_text(title_node.get_text(" ", strip=True) if title_node else anchor.get("title") or "")
            results.append(
                {
                    "id": href.rsplit("/", 1)[-1],
                    "title": title,
                    "cover": urljoin(self._detail_base_url, self._extract_image_url(cover_node)) if cover_node else "",
                    "synopsis": safe_text(description_node.get_text(" ", strip=True) if description_node else ""),
                    "rating": safe_text(rating_node.get_text(" ", strip=True) if rating_node else ""),
                    "type": safe_text(type_node.get_text(" ", strip=True) if type_node else ""),
                    "url": href,
                    "raw": article,
                }
            )
        return results

    def _browse_page_count(self) -> int:
        soup = self._get_soup(f"{self._search_base_url}/browse")
        pages = [1]
        for anchor in soup.select('a[href*="/browse?page="]'):
            href = safe_text(anchor.get("href"))
            match = re.search(r"page=(\d+)", href)
            if match:
                pages.append(int(match.group(1)))
        return max(pages) if pages else 1

    def _search_remote(self, query: str) -> list[dict[str, Any]]:
        url = f"{self._search_base_url}/browse?q={quote_plus(query)}"
        soup = self._get_soup(url)
        return self._extract_anime_cards(soup)

    def _extract_anime_cards(self, soup: BeautifulSoup) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for article in soup.select("div.Container ul.ListAnimes li article"):
            anchor = article.select_one("a[href]")
            if not anchor:
                continue
            title_node = article.select_one("h3.Title") or article.select_one("div.Description .Title strong")
            description_node = article.select_one("div.Description p:nth-of-type(2)")
            type_node = article.select_one("span.Type")
            rating_node = article.select_one("span.Vts")
            cover_node = article.select_one("img")
            href = urljoin(self._detail_base_url, anchor.get("href", ""))
            title = safe_text(title_node.get_text(" ", strip=True) if title_node else anchor.get("title") or "")
            results.append(
                {
                    "id": href.rsplit("/", 1)[-1],
                    "title": title,
                    "cover": urljoin(self._detail_base_url, self._extract_image_url(cover_node)) if cover_node else "",
                    "synopsis": safe_text(description_node.get_text(" ", strip=True) if description_node else ""),
                    "rating": safe_text(rating_node.get_text(" ", strip=True) if rating_node else ""),
                    "type": safe_text(type_node.get_text(" ", strip=True) if type_node else ""),
                    "url": href,
                    "raw": article,
                }
            )
        return results

    def _anime_detail_remote(self, anime_id: str) -> dict[str, Any]:
        url = self._anime_page_url(anime_id)
        soup = self._get_soup(url)

        title_node = soup.select_one("article.Single h1.Title") or soup.select_one("h1")
        synopsis_meta = soup.find("meta", attrs={"name": "description"})
        cover_node = soup.select_one("article.Single figure.Image img")
        banner_node = soup.select_one("article.Single div.Anm-Bg img")
        type_node = soup.select_one("article.Single span.Type")
        rating_node = soup.select_one("article.Single span.Vts")
        genres = [a.get_text(" ", strip=True) for a in soup.select("article.Single .Nvgnrs a, article.Single .Nvgnrs span a")]

        episodes: list[dict[str, Any]] = []
        for link in soup.select("li.Episode a[href]"):
            label = link.get_text(" ", strip=True)
            href = link.get("href", "")
            episodes.append(
                {
                    "id": href.rsplit("/", 1)[-1],
                    "label": label,
                    "number": re.sub(r"\D+", "", label),
                    "url": urljoin(self._detail_base_url, href),
                    "raw": link,
                }
            )

        return {
            "id": anime_id,
            "title": safe_text(title_node.get_text(" ", strip=True) if title_node else ""),
            "cover": urljoin(self._detail_base_url, self._extract_image_url(cover_node)) if cover_node else "",
            "banner": urljoin(self._detail_base_url, self._extract_image_url(banner_node)) if banner_node else "",
            "synopsis": safe_text(synopsis_meta.get("content", "") if synopsis_meta else ""),
            "rating": safe_text(rating_node.get_text(" ", strip=True) if rating_node else ""),
            "type": safe_text(type_node.get_text(" ", strip=True) if type_node else ""),
            "url": url,
            "episodes": episodes,
            "genres": genres,
            "status": "",
            "alternative_titles": [],
            "raw": soup,
        }

    def _episode_servers_remote(self, episode_id: str) -> list[dict[str, Any]]:
        soup = self._get_soup(self._episode_page_url(episode_id))
        script_text = "\n".join(script.get_text("\n", strip=False) for script in soup.find_all("script"))
        match = re.search(r"var\s+videos\s*=\s*(\{.*?\})\s*;", script_text, re.S)
        if not match:
            return []

        try:
            data = json.loads(match.group(1))
        except json.JSONDecodeError:
            return []

        servers: list[dict[str, Any]] = []
        for lang, items in data.items():
            if not isinstance(items, list):
                continue
            for item in items:
                if not isinstance(item, dict):
                    continue
                url = safe_text(item.get("code") or item.get("url") or item.get("link"))
                servers.append(
                    {
                        "label": safe_text(item.get("title") or item.get("server") or "Servidor"),
                        "url": url,
                        "server": safe_text(item.get("server")),
                        "lang": safe_text(lang),
                        "raw": item,
                    }
                )
        return servers

    def _download_links_remote(self, episode_id: str) -> list[dict[str, Any]]:
        soup = self._get_soup(self._episode_page_url(episode_id))
        links: list[dict[str, Any]] = []
        for row in soup.select("table tbody tr"):
            cells = row.find_all("td")
            if len(cells) < 4:
                continue
            anchor = cells[3].select_one("a[href]")
            if not anchor:
                continue
            links.append(
                {
                    "label": safe_text(cells[0].get_text(" ", strip=True)),
                    "url": urljoin(self._detail_base_url, anchor.get("href", "")),
                    "lang": safe_text(cells[2].get_text(" ", strip=True)),
                    "server": safe_text(cells[0].get_text(" ", strip=True)),
                    "raw": row,
                }
            )
        return links

    def _anime_page_url(self, anime_id: str) -> str:
        if anime_id.startswith("http://") or anime_id.startswith("https://"):
            return anime_id
        anime_id = anime_id.replace("/anime/", "").strip("/")
        return urljoin(self._detail_base_url, f"/anime/{anime_id}")

    @staticmethod
    def _normalize_cache_key(value: str) -> str:
        return value.replace("/anime/", "").strip("/").lower()

    def _episode_page_url(self, episode_id: str) -> str:
        if episode_id.startswith("http://") or episode_id.startswith("https://"):
            return episode_id
        episode_id = episode_id.replace("/ver/", "").strip("/")
        return urljoin(self._detail_base_url, f"/ver/{episode_id}")


class ScrollableFrame(ttk.Frame):
    def __init__(self, parent: tk.Widget, *, bg: str, on_scroll=None):
        super().__init__(parent)
        self.on_scroll = on_scroll
        self.canvas = tk.Canvas(self, bg=bg, highlightthickness=0, bd=0)
        self.scrollbar = tk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.inner = ttk.Frame(self)
        self.inner_id = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.canvas.configure(yscrollcommand=self._on_yscroll)

        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")

        self.inner.bind("<Configure>", self._on_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)
        self.canvas.bind_all("<MouseWheel>", self._on_mousewheel, add=True)

    def _on_configure(self, _event=None):
        if self.canvas.winfo_exists():
            self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas_configure(self, event):
        if self.canvas.winfo_exists():
            self.canvas.itemconfigure(self.inner_id, width=event.width)

    def _on_mousewheel(self, event):
        if not self.canvas.winfo_exists():
            return
        try:
            self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        except tk.TclError:
            return

    def _on_yscroll(self, first, last):
        self.scrollbar.set(first, last)
        if callable(self.on_scroll):
            try:
                self.on_scroll(float(first), float(last))
            except Exception:
                pass

    def destroy(self):
        try:
            self.canvas.unbind_all("<MouseWheel>")
        except tk.TclError:
            pass
        super().destroy()


class MediaCard(tk.Frame):
    def __init__(self, parent: tk.Widget, anime: AnimeEntry, command):
        super().__init__(
            parent,
            bg=PANEL_2,
            highlightthickness=1,
            highlightbackground="#26324a",
            highlightcolor="#26324a",
        )
        self.anime = anime
        self.command = command
        self.image_ref = None

        self.accent_strip = tk.Frame(self, bg=ACCENT, height=5)
        self.accent_strip.pack(fill="x")

        self.image_label = tk.Label(self, bg=PANEL_2, width=190, height=270)
        self.image_label.pack(padx=8, pady=(8, 10))

        meta = tk.Frame(self, bg=PANEL_2)
        meta.pack(fill="x", padx=10, pady=(0, 10))

        self.title_label = tk.Label(
            meta,
            text=anime.title or anime.id or "Sin titulo",
            bg=PANEL_2,
            fg=TEXT,
            font=("Bahnschrift SemiBold", 10),
            justify="left",
            wraplength=184,
            anchor="w",
        )
        self.title_label.pack(fill="x")

        subtitle = anime.type or anime.rating or anime.source or "AnimeFLV"
        self.subtitle_label = tk.Label(
            meta,
            text=subtitle,
            bg=PANEL_2,
            fg=MUTED,
            font=("Bahnschrift", 9),
            justify="left",
            anchor="w",
        )
        self.subtitle_label.pack(fill="x", pady=(4, 0))

        self.source_label = tk.Label(
            meta,
            text=(anime.source or "Anime"),
            bg="#0b1020",
            fg=ACCENT_2,
            font=("Bahnschrift SemiBold", 8),
            padx=8,
            pady=2,
        )
        self.source_label.pack(anchor="w", pady=(8, 0))

        badge_text = f"{anime.rating}" if anime.rating else "Ver"
        self.badge = tk.Label(
            meta,
            text=badge_text,
            bg="#0b1020",
            fg=ACCENT_2,
            font=("Bahnschrift SemiBold", 8),
            padx=8,
            pady=2,
        )
        self.badge.pack(anchor="w", pady=(8, 0))

        self._bind_recursive(self)

    def _bind_recursive(self, widget):
        widget.bind("<Button-1>", self._invoke)
        widget.bind("<Enter>", lambda _event: self._hover(True))
        widget.bind("<Leave>", lambda _event: self._hover(False))
        for child in widget.winfo_children():
            self._bind_recursive(child)

    def _hover(self, active: bool):
        color = "#3d4f74" if active else "#26324a"
        self.configure(highlightbackground=color, highlightcolor=color, bg=PANEL_3 if active else PANEL_2)
        for child in self.winfo_children():
            if isinstance(child, (tk.Frame, tk.Label)):
                child.configure(bg=PANEL_3 if active else PANEL_2)
        self.accent_strip.configure(bg=ACCENT if active else ACCENT)

    def _invoke(self, _event=None):
        if callable(self.command):
            self.command(self.anime)

    def set_image(self, image: Image.Image):
        self.image_ref = ImageTk.PhotoImage(image)
        self.image_label.configure(image=self.image_ref, text="")

    def update_metadata(self, anime: AnimeEntry):
        self.anime = anime
        self.title_label.configure(text=anime.title or anime.id or "Sin titulo")
        subtitle = anime.type or anime.rating or anime.source or "AnimeFLV"
        self.subtitle_label.configure(text=subtitle)
        self.source_label.configure(text=anime.source or "Anime")
        self.badge.configure(text=anime.rating or "Ver")

    def set_placeholder(self, text: str):
        placeholder = make_placeholder((190, 270), text)
        self.set_image(placeholder)


class AnimeApp:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title(APP_TITLE)
        self.root.geometry(WINDOW_SIZE)
        self.root.minsize(1200, 820)
        self.root.configure(bg=BG)
        self.root.withdraw()

        self.executor = ThreadPoolExecutor(max_workers=8)
        self.detail_executor = ThreadPoolExecutor(max_workers=2)
        self.ui_queue: queue.Queue[tuple[Callable[..., Any], tuple[Any, ...], dict[str, Any]]] = queue.Queue()
        self.client: MultiSourceAnimeClient | None = None

        self.search_token = 0
        self.detail_token = 0
        self.server_token = 0

        self.results: list[AnimeEntry] = []
        self.current_anime: AnimeEntry | None = None
        self.current_episodes: list[dict[str, Any]] = []
        self.current_servers: list[dict[str, Any]] = []
        self.current_episode_index: int = 0
        self.current_server_index: int = 0
        self.filtered_episodes: list[dict[str, Any]] = []
        self.episodes_loading = False
        self.player_process: mp.Process | None = None
        self.brave_process: subprocess.Popen | None = None
        self.catalog_window: tk.Toplevel | None = None
        self.catalog_cards: list[MediaCard] = []
        self.catalog_card_map: dict[str, MediaCard] = {}
        self.catalog_section_map: dict[str, dict[str, Any]] = {}
        self.catalog_progress_token = 0
        self.catalog_seen_keys: set[str] = set()
        self.catalog_current_page = 1
        self.catalog_total_pages = 1
        self.catalog_page_size = 20
        self.catalog_next_page = 1
        self.catalog_loading_page = False
        self.catalog_has_more = True
        self.catalog_items: list[AnimeEntry] = []
        self.catalog_mode = "browse"
        self.catalog_query = ""
        self.catalog_provider_var = tk.StringVar(value="Todos")
        self.catalog_search_var = tk.StringVar(value="")
        self.autoplay_selected_anime = False
        self.player_visible = False
        self.player_url = ""
        self.player_title = ""

        self.search_var = tk.StringVar(value="naruto")
        self.episode_filter_var = tk.StringVar(value="")
        self.status_var = tk.StringVar(value="Preparando interfaz...")

        self._build_styles()
        self._build_ui()
        self._bind_events()
        self.root.after(50, self._drain_ui_queue)

        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.root.after(200, self.bootstrap)

    def _build_styles(self):
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        style.configure(".", background=BG, foreground=TEXT)
        style.configure("TFrame", background=BG)
        style.configure("Panel.TFrame", background=PANEL)
        style.configure("Panel2.TFrame", background=PANEL_2)
        style.configure("Panel3.TFrame", background=PANEL_3)
        style.configure(
            "TLabel",
            background=BG,
            foreground=TEXT,
            font=("Bahnschrift", 10),
        )
        style.configure(
            "Header.TLabel",
            background=PANEL,
            foreground=TEXT,
            font=("Bahnschrift SemiBold", 20),
        )
        style.configure(
            "SubHeader.TLabel",
            background=PANEL,
            foreground=MUTED,
            font=("Bahnschrift", 9),
        )
        style.configure(
            "Section.TLabel",
            background=PANEL,
            foreground=ACCENT_2,
            font=("Bahnschrift SemiBold", 11),
        )
        style.configure(
            "HeroTitle.TLabel",
            background=PANEL,
            foreground=TEXT,
            font=("Bahnschrift SemiBold", 26),
        )
        style.configure(
            "HeroMeta.TLabel",
            background=PANEL,
            foreground=MUTED,
            font=("Bahnschrift", 10),
        )
        style.configure(
            "Body.TButton",
            font=("Bahnschrift SemiBold", 10),
            padding=(14, 9),
            relief="flat",
        )
        style.configure(
            "TButton",
            font=("Bahnschrift SemiBold", 10),
            padding=(14, 9),
            background=PANEL_2,
            foreground=TEXT,
            relief="flat",
        )
        style.map(
            "TButton",
            background=[("active", PANEL_3)],
            foreground=[("active", TEXT)],
        )
        style.configure(
            "Accent.TButton",
            font=("Bahnschrift SemiBold", 10),
            padding=(14, 9),
            background=ACCENT,
            foreground="#111827",
            relief="flat",
        )
        style.map(
            "Accent.TButton",
            background=[("active", "#ff3b47")],
            foreground=[("active", "#111827")],
        )
        style.configure(
            "TEntry",
            fieldbackground="#0b1020",
            foreground=TEXT,
            insertcolor=TEXT,
            bordercolor="#2a3550",
            lightcolor="#2a3550",
            darkcolor="#2a3550",
            padding=8,
        )

    def _build_ui(self):
        self.shell = tk.Frame(self.root, bg=BG)
        self.shell.pack(fill="both", expand=True)

        self.bg_canvas = tk.Canvas(self.shell, bg=BG, highlightthickness=0, bd=0)
        self.bg_canvas.place(relx=0, rely=0, relwidth=1, relheight=1)
        self._draw_background()

        content = tk.Frame(self.shell, bg=BG)
        content.place(relx=0, rely=0, relwidth=1, relheight=1)

        self._build_header(content)
        self._build_hero(content)
        self._build_library(content)
        self._build_statusbar(content)

    def _build_player_view(self):
        self.player_shell = tk.Frame(self.root, bg=BG)

        header = ttk.Frame(self.player_shell, style="Panel.TFrame", padding=(20, 16))
        header.pack(fill="x", padx=18, pady=(16, 14))

        left = ttk.Frame(header, style="Panel.TFrame")
        left.pack(side="left", fill="y")
        self.player_title_label = ttk.Label(left, text="Reproductor", style="Header.TLabel")
        self.player_title_label.pack(anchor="w")
        self.player_url_label = ttk.Label(
            left,
            text="El episodio se cargara dentro de la app",
            style="SubHeader.TLabel",
        )
        self.player_url_label.pack(anchor="w", pady=(4, 0))

        actions = ttk.Frame(header, style="Panel.TFrame")
        actions.pack(side="right", fill="y")
        ttk.Button(actions, text="Volver al catálogo", style="Accent.TButton", command=self.back_to_catalog).pack(
            side="left", padx=(0, 10)
        )
        ttk.Button(actions, text="Volver al buscador", style="Body.TButton", command=self.back_to_main_view).pack(
            side="left", padx=(0, 10)
        )
        ttk.Button(actions, text="Recargar", style="Body.TButton", command=self.reload_player).pack(
            side="left"
        )

        self.player_frame = HtmlFrame(
            self.player_shell,
            vertical_scrollbar=True,
            horizontal_scrollbar=False,
            javascript_enabled=True,
            images_enabled=True,
            forms_enabled=True,
            objects_enabled=True,
            dark_theme_enabled=True,
            request_timeout=20,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
                )
            },
        )
        self.player_frame.pack(fill="both", expand=True, padx=18, pady=(0, 18))

    def _draw_background(self):
        self.bg_canvas.delete("all")
        self.bg_canvas.create_rectangle(0, 0, 1440, 920, fill=BG, outline="")
        self.bg_canvas.create_oval(-220, -180, 560, 540, fill="#10182a", outline="")
        self.bg_canvas.create_oval(940, -200, 1580, 420, fill="#161f33", outline="")
        self.bg_canvas.create_oval(1040, 500, 1660, 1120, fill="#101826", outline="")
        self.bg_canvas.create_oval(420, 520, 980, 1080, fill="#0e1524", outline="")
        self.bg_canvas.create_line(0, 112, 1440, 112, fill="#1f2940", width=2)
        self.bg_canvas.create_line(0, 114, 1440, 114, fill="#8f0d18", width=1)
        for x in range(0, 1440, 120):
            self.bg_canvas.create_line(x, 0, x + 220, 920, fill="#182033", width=1)

    def _build_header(self, parent):
        header = ttk.Frame(parent, style="Panel.TFrame", padding=(20, 16))
        header.pack(fill="x", padx=18, pady=(16, 14))

        left = ttk.Frame(header, style="Panel.TFrame")
        left.pack(side="left", fill="y")
        ttk.Label(left, text="AnimeFLV", style="Header.TLabel").pack(anchor="w")
        ttk.Label(
            left,
            text="Explora anime, episodios y servidores con una UI tipo streaming",
            style="SubHeader.TLabel",
        ).pack(anchor="w", pady=(4, 0))

        controls = ttk.Frame(header, style="Panel.TFrame")
        controls.pack(side="right", fill="y")

        self.search_entry = ttk.Entry(
            controls,
            textvariable=self.search_var,
            width=42,
            font=("Segoe UI", 11),
        )
        self.search_entry.pack(side="left", padx=(0, 10), ipady=4)
        ttk.Button(controls, text="Catálogo", style="Body.TButton", command=self.show_catalog).pack(
            side="left", padx=(0, 10)
        )
        ttk.Button(controls, text="Buscar", style="Accent.TButton", command=self.search).pack(
            side="left", padx=(0, 10)
        )
        ttk.Button(controls, text="Abrir sitio", style="Body.TButton", command=self.open_site).pack(
            side="left", padx=(0, 10)
        )
        ttk.Button(controls, text="Limpiar", style="Body.TButton", command=self.clear_search).pack(
            side="left"
        )

    def _build_hero(self, parent):
        hero = ttk.Frame(parent, style="Panel.TFrame", padding=18)
        hero.pack(fill="x", padx=18, pady=(0, 14))
        hero.columnconfigure(0, weight=0)
        hero.columnconfigure(1, weight=1)

        self.hero_cover = tk.Label(hero, bg=PANEL_2, fg=TEXT, width=240, height=360, bd=0, relief="flat")
        self.hero_cover.grid(row=0, column=0, rowspan=2, sticky="nw")

        hero_right = ttk.Frame(hero, style="Panel.TFrame")
        hero_right.grid(row=0, column=1, sticky="nsew", padx=(22, 0))
        hero_right.columnconfigure(0, weight=1)

        self.hero_badge = tk.Label(
            hero_right,
            text="DESTACADO",
            bg="#0b1020",
            fg=ACCENT_2,
            font=("Bahnschrift SemiBold", 8),
            padx=10,
            pady=3,
        )
        self.hero_badge.pack(anchor="w")

        self.hero_label = ttk.Label(hero_right, text="Selecciona un anime", style="HeroTitle.TLabel")
        self.hero_label.pack(anchor="w", pady=(8, 0))
        self.hero_meta = ttk.Label(
            hero_right, text="Busca un anime para ver su ficha", style="HeroMeta.TLabel"
        )
        self.hero_meta.pack(anchor="w", pady=(8, 14))

        self.hero_synopsis = tk.Text(
            hero_right,
            height=9,
            wrap="word",
            bg="#0f172a",
            fg=TEXT,
            insertbackground=TEXT,
            relief="flat",
            highlightthickness=0,
            padx=14,
            pady=12,
            font=("Segoe UI", 10),
        )
        self.hero_synopsis.pack(fill="x")
        self.hero_synopsis.insert(
            "1.0", "Cuando hagas una busqueda, la portada y la sinopsis apareceran aqui. Elige un anime para abrir su ficha y saltar directo al capitulo."
        )
        self.hero_synopsis.config(state="disabled")

        actions = ttk.Frame(hero_right, style="Panel.TFrame")
        actions.pack(anchor="w", pady=(14, 0))
        ttk.Button(actions, text="Catálogo", style="Body.TButton", command=self.show_catalog).pack(
            side="left"
        )
        ttk.Button(actions, text="Abrir ficha", style="Accent.TButton", command=self.open_current_anime).pack(
            side="left", padx=(10, 0)
        )
        ttk.Button(actions, text="Ver episodio", style="Body.TButton", command=self.open_selected_server).pack(
            side="left", padx=(10, 0)
        )
        ttk.Button(actions, text="Copiar URL", style="Body.TButton", command=self.copy_selected_server).pack(
            side="left", padx=(10, 0)
        )
        ttk.Button(actions, text="Limpia detalle", style="Body.TButton", command=self.clear_detail).pack(
            side="left", padx=(10, 0)
        )

        side = ttk.Frame(hero, style="Panel.TFrame")
        side.grid(row=0, column=2, rowspan=2, sticky="ns", padx=(18, 0))
        side.columnconfigure(0, weight=1)

        ttk.Label(side, text="Episodios", style="Section.TLabel").pack(anchor="w")
        episode_filter_row = ttk.Frame(side, style="Panel.TFrame")
        episode_filter_row.pack(fill="x", pady=(8, 6))
        self.episode_filter_entry = ttk.Entry(
            episode_filter_row,
            textvariable=self.episode_filter_var,
            font=("Segoe UI", 10),
        )
        self.episode_filter_entry.pack(side="left", fill="x", expand=True)
        ttk.Button(
            episode_filter_row,
            text="Limpiar",
            style="Body.TButton",
            command=self.clear_episode_filter,
        ).pack(side="left", padx=(8, 0))
        episodes_frame = tk.Frame(side, bg=PANEL_2, highlightthickness=1, highlightbackground="#22314c")
        episodes_frame.pack(fill="both", expand=True, pady=(8, 14))
        episodes_scroll = ttk.Scrollbar(episodes_frame, orient="vertical")
        self.episodes_list = tk.Listbox(
            episodes_frame,
            bg="#101827",
            fg=TEXT,
            selectbackground=ACCENT,
            selectforeground="#ffffff",
            relief="flat",
            highlightthickness=0,
            activestyle="none",
            height=11,
            font=("Bahnschrift", 10),
            borderwidth=0,
            exportselection=False,
            yscrollcommand=episodes_scroll.set,
        )
        episodes_scroll.config(command=self.episodes_list.yview)
        self.episodes_list.pack(side="left", fill="both", expand=True, padx=4, pady=4)
        episodes_scroll.pack(side="right", fill="y", pady=4)

        ttk.Label(side, text="Servidores", style="Section.TLabel").pack(anchor="w")
        servers_frame = tk.Frame(side, bg=PANEL_2, highlightthickness=1, highlightbackground="#22314c")
        servers_frame.pack(fill="both", expand=True, pady=(8, 0))
        servers_scroll = ttk.Scrollbar(servers_frame, orient="vertical")
        self.servers_list = tk.Listbox(
            servers_frame,
            bg="#101827",
            fg=TEXT,
            selectbackground=ACCENT,
            selectforeground="#ffffff",
            relief="flat",
            highlightthickness=0,
            activestyle="none",
            height=10,
            font=("Bahnschrift", 10),
            borderwidth=0,
            exportselection=False,
            yscrollcommand=servers_scroll.set,
        )
        servers_scroll.config(command=self.servers_list.yview)
        self.servers_list.pack(side="left", fill="both", expand=True, padx=4, pady=4)
        servers_scroll.pack(side="right", fill="y", pady=4)

    def _build_library(self, parent):
        library = ttk.Frame(parent, style="TFrame")
        library.pack(fill="both", expand=True, padx=18, pady=(0, 14))

        results_panel = ttk.Frame(library, style="Panel.TFrame", padding=18)
        results_panel.pack(side="left", fill="both", expand=True, padx=(0, 10))
        ttk.Label(results_panel, text="Resultados", style="Section.TLabel").pack(anchor="w")
        ttk.Label(
            results_panel,
            text="Tarjetas tipo poster con acceso rapido a cada titulo",
            style="SubHeader.TLabel",
        ).pack(anchor="w", pady=(4, 12))

        self.results_flow = ScrollableFrame(results_panel, bg=PANEL)
        self.results_flow.pack(fill="both", expand=True)
        self.results_container = self.results_flow.inner

        queue_panel = ttk.Frame(library, style="Panel.TFrame", padding=18)
        queue_panel.pack(side="left", fill="both", expand=False)
        queue_panel.configure(width=360)
        queue_panel.pack_propagate(False)

        ttk.Label(queue_panel, text="Actividad", style="Section.TLabel").pack(anchor="w")
        ttk.Label(
            queue_panel,
            text="Selecciona un episodio y luego un servidor para abrirlo en Brave desde la app.",
            style="SubHeader.TLabel",
            wraplength=320,
            justify="left",
        ).pack(anchor="w", pady=(4, 12))

        self.activity_box = tk.Text(
            queue_panel,
            bg="#0f172a",
            fg=TEXT,
            relief="flat",
            highlightthickness=0,
            padx=12,
            pady=12,
            wrap="word",
            font=("Segoe UI", 10),
            height=12,
        )
        self.activity_box.pack(fill="both", expand=True)
        self.activity_box.insert(
            "1.0", "La cola de actividad mostrara el estado de carga y la seleccion actual."
        )
        self.activity_box.config(state="disabled")

    def _build_statusbar(self, parent):
        status = ttk.Frame(parent, style="Panel3.TFrame", padding=(18, 10))
        status.pack(fill="x", padx=18, pady=(0, 18))
        ttk.Label(status, textvariable=self.status_var, style="TLabel").pack(anchor="w")

    def _queue_ui(self, func: Callable[..., Any], *args: Any, **kwargs: Any):
        self.ui_queue.put((func, args, kwargs))

    def _drain_ui_queue(self):
        try:
            while True:
                func, args, kwargs = self.ui_queue.get_nowait()
                try:
                    func(*args, **kwargs)
                except Exception as exc:
                    self.show_error("Error en interfaz", exc)
        except queue.Empty:
            pass
        if self.root.winfo_exists():
            self.root.after(50, self._drain_ui_queue)

    def _catalog_total_pages_estimate(self) -> int:
        client = self._catalog_client()
        if client is None:
            return 1

        providers: list[Any] = []
        if hasattr(client, "primary") and hasattr(client, "secondary"):
            providers.extend([client.primary, client.secondary])
        else:
            providers.append(client)

        pages: list[int] = []
        for provider in providers:
            if provider is None or not hasattr(provider, "_browse_page_count"):
                continue
            try:
                value = int(provider._browse_page_count())
            except Exception:
                continue
            if value > 0:
                pages.append(value)
        return max(pages) if pages else 1

    def _update_catalog_pagination_controls(self):
        total = max(1, int(getattr(self, "catalog_total_pages", 1)))
        current = max(1, int(getattr(self, "catalog_current_page", 1)))
        if hasattr(self, "catalog_page_var"):
            self.catalog_page_var.set(f"Página {current} de {total}")
        if hasattr(self, "catalog_prev_button"):
            self.catalog_prev_button.configure(state=("normal" if current > 1 else "disabled"))
        if hasattr(self, "catalog_next_button"):
            self.catalog_next_button.configure(state=("normal" if current < total else "disabled"))

    def _catalog_prev_page(self):
        if self.catalog_current_page <= 1 or self.catalog_loading_page:
            return
        self.catalog_current_page -= 1
        if self.catalog_mode == "search":
            self.render_catalog(self.catalog_items, reset=True, page=self.catalog_current_page)
        else:
            self._request_catalog_page(self.catalog_current_page, reset=True)

    def _catalog_next_page(self):
        if self.catalog_loading_page:
            return
        if self.catalog_mode == "search":
            if self.catalog_current_page >= self.catalog_total_pages:
                return
            self.catalog_current_page += 1
            self.render_catalog(self.catalog_items, reset=True, page=self.catalog_current_page)
            return
        if self.catalog_current_page >= self.catalog_total_pages:
            return
        self.catalog_current_page += 1
        self._request_catalog_page(self.catalog_current_page, reset=True)

    def _bind_events(self):
        self.search_entry.bind("<Return>", lambda _event: self.search())
        self.episode_filter_var.trace_add("write", lambda *_args: self.apply_episode_filter())
        self.episode_filter_entry.bind("<Return>", lambda _event: self.apply_episode_filter())
        self.episodes_list.bind("<<ListboxSelect>>", self.on_episode_selected)
        self.servers_list.bind("<Double-Button-1>", lambda _event: self.open_selected_server())

    def bootstrap(self):
        self.set_status("Conectando con AnimeFLV...")

        def task():
            try:
                self.client = MultiSourceAnimeClient()
            except Exception as exc:
                self._queue_ui(self.show_dependency_error, exc)
                return
            self._queue_ui(self.show_catalog)

        self.executor.submit(task)

    def show_dependency_error(self, exc: Exception):
        self.set_status("No se pudo cargar la libreria animeflv.")
        messagebox.showerror(
            "Dependencia faltante",
            "No se pudo inicializar la libreria 'animeflv'.\n\n"
            "Instala o reinstala las dependencias del proyecto y vuelve a abrir la app.\n"
            f"Detalle tecnico: {exc}",
        )
        self.add_activity("Fallo la inicializacion: falta la libreria animeflv.")

    def set_status(self, text: str):
        self.status_var.set(text)

    def add_activity(self, text: str):
        self.activity_box.config(state="normal")
        self.activity_box.insert("end", f"\n[OK] {text}")
        self.activity_box.see("end")
        self.activity_box.config(state="disabled")

    def clear_search(self):
        self.search_var.set("")
        self.results = []
        self.clear_detail()
        self._clear_results()
        self.set_status("Busqueda limpiada.")
        self.add_activity("Se limpio la busqueda.")

    def show_catalog(self):
        if self.catalog_window is not None and self.catalog_window.winfo_exists():
            self.catalog_window.lift()
            self.catalog_window.focus_force()
            return

        self.catalog_window = tk.Toplevel(self.root)
        self.catalog_window.title("Catalogo AnimeFLV")
        self.catalog_window.configure(bg=BG)
        self.catalog_window.geometry("1280x820")
        self.catalog_window.minsize(1180, 760)
        self.catalog_window.protocol("WM_DELETE_WINDOW", lambda: self.enter_main_view(start_default=True))

        shell = tk.Frame(self.catalog_window, bg=BG)
        shell.pack(fill="both", expand=True)

        header = ttk.Frame(shell, style="Panel.TFrame", padding=(20, 16))
        header.pack(fill="x", padx=18, pady=(18, 14))

        left = ttk.Frame(header, style="Panel.TFrame")
        left.pack(side="left", fill="y")
        ttk.Label(left, text="Catálogo", style="Header.TLabel").pack(anchor="w")
        ttk.Label(
            left,
            text="Explora anime por categoria y carga mas al bajar",
            style="SubHeader.TLabel",
        ).pack(anchor="w", pady=(4, 0))

        actions = ttk.Frame(header, style="Panel.TFrame")
        actions.pack(side="right", fill="y")
        ttk.Button(actions, text="Anime al azar", style="Body.TButton", command=self.play_random_catalog_anime).pack(
            side="left", padx=(0, 10)
        )
        ttk.Button(actions, text="Entrar al buscador", style="Accent.TButton", command=lambda: self.enter_main_view(start_default=True)).pack(
            side="left", padx=(0, 10)
        )
        ttk.Button(actions, text="Actualizar top", style="Body.TButton", command=self.reload_catalog).pack(
            side="left"
        )

        hero = ttk.Frame(shell, style="Panel.TFrame", padding=18)
        hero.pack(fill="x", padx=18, pady=(0, 14))
        hero.columnconfigure(1, weight=1)

        self.catalog_hero_cover = tk.Label(hero, bg=PANEL_2, bd=0, relief="flat")
        self.catalog_hero_cover.grid(row=0, column=0, rowspan=2, sticky="nw")
        hero_cover = make_placeholder((240, 360), "AnimeFLV")
        self.catalog_hero_ref = ImageTk.PhotoImage(hero_cover)
        self.catalog_hero_cover.configure(image=self.catalog_hero_ref)

        hero_right = ttk.Frame(hero, style="Panel.TFrame")
        hero_right.grid(row=0, column=1, sticky="nsew", padx=(22, 0))
        hero_right.columnconfigure(0, weight=1)

        self.catalog_hero_badge = tk.Label(
            hero_right,
            text="DESTACADO DEL DIA",
            bg="#0b1020",
            fg=ACCENT_2,
            font=("Bahnschrift SemiBold", 8),
            padx=10,
            pady=3,
        )
        self.catalog_hero_badge.pack(anchor="w")

        self.catalog_hero_title = ttk.Label(
            hero_right,
            text="Cargando destacado...",
            style="HeroTitle.TLabel",
        )
        self.catalog_hero_title.pack(anchor="w", pady=(10, 0))

        self.catalog_hero_meta = ttk.Label(
            hero_right,
            text="Un anime destacado para entrar directo al catálogo.",
            style="HeroMeta.TLabel",
        )
        self.catalog_hero_meta.pack(anchor="w", pady=(8, 12))

        self.catalog_hero_synopsis = tk.Text(
            hero_right,
            height=7,
            wrap="word",
            bg="#0f172a",
            fg=TEXT,
            insertbackground=TEXT,
            relief="flat",
            highlightthickness=0,
            padx=14,
            pady=12,
            font=("Bahnschrift", 10),
        )
        self.catalog_hero_synopsis.pack(fill="x")
        self.catalog_hero_synopsis.insert("1.0", "Selecciona una categoría o un anime y el catálogo se va llenando progresivamente.")
        self.catalog_hero_synopsis.config(state="disabled")

        hero_actions = ttk.Frame(hero_right, style="Panel.TFrame")
        hero_actions.pack(anchor="w", pady=(14, 0))
        ttk.Button(hero_actions, text="Ver destacado", style="Accent.TButton", command=self._open_catalog_featured).pack(
            side="left"
        )
        ttk.Button(hero_actions, text="Anime al azar", style="Body.TButton", command=self.play_random_catalog_anime).pack(
            side="left", padx=(10, 0)
        )

        body = ttk.Frame(shell, style="TFrame")
        body.pack(fill="both", expand=True, padx=18, pady=(0, 18))

        self.catalog_info = ttk.Frame(body, style="Panel.TFrame", padding=18)
        self.catalog_info.pack(side="left", fill="both", expand=True)
        ttk.Label(self.catalog_info, text="Catalogo", style="Section.TLabel").pack(anchor="w")
        ttk.Label(
            self.catalog_info,
            text="Un catalogo grande con carga progresiva para descubrir animes sin esperar todo de golpe.",
            style="SubHeader.TLabel",
        ).pack(anchor="w", pady=(4, 10))

        catalog_controls = ttk.Frame(self.catalog_info, style="Panel.TFrame")
        catalog_controls.pack(fill="x", pady=(0, 10))
        ttk.Label(catalog_controls, text="Proveedor", style="SubHeader.TLabel").pack(side="left")
        self.catalog_provider_combo = ttk.Combobox(
            catalog_controls,
            textvariable=self.catalog_provider_var,
            values=("Todos", "AnimeFLV", "JkAnime"),
            state="readonly",
            width=12,
        )
        self.catalog_provider_combo.pack(side="left", padx=(8, 16))
        self.catalog_provider_combo.bind("<<ComboboxSelected>>", self._on_catalog_provider_changed)

        ttk.Label(catalog_controls, text="Buscar", style="SubHeader.TLabel").pack(side="left")
        catalog_search_entry = ttk.Entry(catalog_controls, textvariable=self.catalog_search_var)
        catalog_search_entry.pack(side="left", fill="x", expand=True, padx=(8, 10))
        catalog_search_entry.bind("<Return>", lambda _event: self.search_catalog())
        ttk.Button(catalog_controls, text="Buscar", style="Accent.TButton", command=self.search_catalog).pack(
            side="left", padx=(0, 8)
        )
        ttk.Button(catalog_controls, text="Limpiar", style="Body.TButton", command=self.clear_catalog_search).pack(
            side="left"
        )

        self.catalog_message = ttk.Label(
            self.catalog_info,
            text="Cargando catálogo...",
            style="HeroMeta.TLabel",
        )
        self.catalog_message.pack(anchor="w", pady=(0, 12))

        catalog_pager = ttk.Frame(self.catalog_info, style="Panel.TFrame")
        catalog_pager.pack(fill="x", pady=(0, 12))
        self.catalog_prev_button = ttk.Button(catalog_pager, text="Anterior", style="Body.TButton", command=self._catalog_prev_page)
        self.catalog_prev_button.pack(side="left")
        self.catalog_page_var = tk.StringVar(value="Página 1 de 1")
        ttk.Label(catalog_pager, textvariable=self.catalog_page_var, style="SubHeader.TLabel").pack(side="left", padx=12)
        self.catalog_next_button = ttk.Button(catalog_pager, text="Siguiente", style="Accent.TButton", command=self._catalog_next_page)
        self.catalog_next_button.pack(side="left")

        self.catalog_flow = ScrollableFrame(self.catalog_info, bg=PANEL, on_scroll=self._catalog_scroll_probe)
        self.catalog_flow.pack(fill="both", expand=True)
        self.catalog_container = self.catalog_flow.inner

        side = ttk.Frame(body, style="Panel.TFrame", padding=18)
        side.pack(side="left", fill="y", padx=(14, 0))
        side.configure(width=330)
        side.pack_propagate(False)

        ttk.Label(side, text="Como funciona", style="Section.TLabel").pack(anchor="w")
        ttk.Label(
            side,
            text="1. Elige un titulo del catalogo.\n2. La ficha se abre con portada.\n3. Busca episodios o filtra el capitulo.\n4. Ver episodio abre Brave desde la app.",
            style="SubHeader.TLabel",
            wraplength=290,
            justify="left",
        ).pack(anchor="w", pady=(4, 12))

        self.catalog_preview = tk.Label(side, bg=PANEL_2, bd=0, relief="flat")
        self.catalog_preview.pack(fill="x", pady=(0, 12))
        preview = make_placeholder((290, 410), "AnimeFLV")
        self.catalog_preview_ref = ImageTk.PhotoImage(preview)
        self.catalog_preview.configure(image=self.catalog_preview_ref)

        self.catalog_title = ttk.Label(side, text="Selecciona un anime", style="HeroTitle.TLabel", wraplength=290)
        self.catalog_title.pack(anchor="w")
        self.catalog_detail = ttk.Label(
            side,
            text="El catalogo se va completando mientras haces scroll para mantenerlo rapido.",
            style="HeroMeta.TLabel",
            wraplength=290,
            justify="left",
        )
        self.catalog_detail.pack(anchor="w", pady=(8, 0))

        self.root.after(50, self.reload_catalog)

    def reload_catalog(self):
        if self.client is None:
            return
        self.catalog_mode = "browse"
        self.catalog_query = ""
        if hasattr(self, "catalog_search_var"):
            self.catalog_search_var.set("")
        self.catalog_message.configure(text="Cargando catalogo por categorias...")
        self.set_status("Cargando catalogo inicial...")
        self.add_activity("Cargando catalogo inicial")
        self.catalog_progress_token += 1
        self.catalog_loading_page = False
        self.catalog_current_page = 1
        self.catalog_total_pages = self._catalog_total_pages_estimate()
        self.catalog_has_more = True
        self.catalog_next_page = 1
        self.catalog_seen_keys = set()
        self.catalog_card_map = {}
        self.catalog_items = []
        self._update_catalog_pagination_controls()

        self._request_catalog_page(1, reset=True)

    def search_catalog(self):
        if self.client is None:
            return
        query = self.catalog_search_var.get().strip()
        if not query:
            self.reload_catalog()
            return

        provider_label = self._catalog_provider_label()
        client = self._catalog_client()
        if client is None:
            self.set_status("No hay proveedor disponible para buscar.")
            return

        self.catalog_mode = "search"
        self.catalog_query = query
        self.catalog_progress_token += 1
        self.catalog_loading_page = True
        self.catalog_has_more = False
        self.catalog_current_page = 1
        self.catalog_total_pages = 1
        self.catalog_next_page = 1
        self.catalog_seen_keys = set()
        self.catalog_card_map = {}
        self.catalog_items = []
        self.catalog_message.configure(text=f"Buscando '{query}' en {provider_label}...")
        self.set_status(f"Buscando en el catalogo: {query}")
        self.add_activity(f"Buscando en catalogo: {query} ({provider_label})")

        token = self.catalog_progress_token

        def task():
            try:
                raw_items = client.search(query)
                items = [normalize_entry(item) for item in raw_items]
            except Exception as exc:
                self._queue_ui(self._finish_catalog_page_load, token, 1, [], True, exc)
                return
            self._queue_ui(self._finish_catalog_page_load, token, 1, items, True)

        self.executor.submit(task)

    def clear_catalog_search(self):
        if hasattr(self, "catalog_search_var"):
            self.catalog_search_var.set("")
        self.catalog_mode = "browse"
        self.catalog_query = ""
        self.reload_catalog()

    def _on_catalog_provider_changed(self, _event=None):
        if self.catalog_mode == "search" and self.catalog_search_var.get().strip():
            self.search_catalog()
        else:
            self.reload_catalog()

    def _catalog_provider_label(self) -> str:
        provider = safe_text(self.catalog_provider_var.get()).strip().lower()
        if provider == "jkanime":
            return "JkAnime"
        if provider == "animeflv":
            return "AnimeFLV"
        return "Todos"

    def _catalog_client(self):
        if self.client is None:
            return None
        provider = safe_text(self.catalog_provider_var.get()).strip().lower()
        if provider == "animeflv" and hasattr(self.client, "primary"):
            return self.client.primary
        if provider == "jkanime" and hasattr(self.client, "secondary"):
            return self.client.secondary
        return self.client

    def _request_catalog_page(self, page: int, reset: bool = False):
        if self.client is None:
            return
        if self.catalog_loading_page or (not reset and not self.catalog_has_more):
            return

        self.catalog_loading_page = True
        provider_label = self._catalog_provider_label()
        self.catalog_message.configure(text=f"Cargando catalogo... pagina {page} ({provider_label})")
        self.set_status(f"Cargando catalogo pagina {page}...")
        self.add_activity(f"Cargando catalogo pagina {page} ({provider_label})")
        token = self.catalog_progress_token
        limit = self.catalog_page_size
        client = self._catalog_client()
        if client is None:
            self.catalog_loading_page = False
            return

        def task():
            try:
                raw_items = client.catalog_page(page=page, limit=limit)
                items = [normalize_entry(item) for item in raw_items]
            except Exception as exc:
                self._queue_ui(self._finish_catalog_page_load, token, page, [], reset, exc)
                return
            self._queue_ui(self._finish_catalog_page_load, token, page, items, reset)

        self.executor.submit(task)

    def _finish_catalog_page_load(self, token: int, page: int, items: list[AnimeEntry], reset: bool, error: Exception | None = None):
        self.catalog_loading_page = False
        if token != self.catalog_progress_token:
            return
        if error is not None:
            self.show_error("Error al cargar catalogo", error)
            self.set_status("No se pudo cargar el catalogo.")
            self.catalog_message.configure(text="No se pudo cargar el catalogo.")
            return

        self.catalog_current_page = page
        self.render_catalog(items, reset=reset, page=page)

    def play_random_catalog_anime(self):
        if self.client is None:
            self.set_status("Esperando la libreria animeflv...")
            return

        self.set_status("Buscando un anime al azar en AnimeFLV...")
        self.add_activity("Buscando un anime al azar en el catalogo amplio.")

        def task():
            try:
                anime = normalize_entry(self.client.random_anime())
            except Exception as exc:
                self._queue_ui(self._fallback_random_catalog_anime, exc)
                return
            self._queue_ui(self._start_random_anime, anime)

        self.executor.submit(task)

    def _start_random_anime(self, anime: AnimeEntry):
        if not anime.title and not anime.id:
            self._fallback_random_catalog_anime(RuntimeError("No se obtuvo un anime valido al azar."))
            return
        self.set_status(f"Reproduciendo al azar: {anime.title or anime.id}")
        self.add_activity(f"Anime al azar seleccionado: {anime.title or anime.id}")
        self.choose_catalog_anime(anime)

    def _fallback_random_catalog_anime(self, exc: Exception):
        items = getattr(self, "catalog_items", [])
        if items:
            anime = random.choice(items)
            self.set_status(
                f"No se pudo abrir un random global, usando el catalogo: {anime.title or anime.id}"
            )
            self.add_activity(
                f"Fallback al catalogo tras error en random global: {exc}"
            )
            self.choose_catalog_anime(anime)
            return

        self.show_error("No se pudo elegir un anime al azar", exc)
        self.set_status("No se pudo elegir un anime al azar.")
        self.add_activity("Fallo la seleccion aleatoria del catalogo.")

    def render_catalog(self, items: list[AnimeEntry], reset: bool = False, page: int = 1):
        if self.catalog_window is None or not self.catalog_window.winfo_exists():
            return

        if reset:
            for child in self.catalog_container.winfo_children():
                child.destroy()
            self.catalog_cards = []
            self.catalog_card_map = {}
            self.catalog_section_map = {}
            self.catalog_seen_keys = set()
            self.catalog_progress_token += 1

        if not items:
            if reset:
                if self.catalog_mode == "search" and self.catalog_query:
                    self.catalog_message.configure(
                        text=f"No se encontraron resultados para '{self.catalog_query}' en {self._catalog_provider_label()}."
                    )
                    self.set_status("Sin resultados en el catalogo.")
                else:
                    self.catalog_message.configure(text="No se pudo cargar un catalogo inicial.")
                    self.set_status("Catalogo vacio.")
            else:
                self.catalog_message.configure(text="No hay mas animes para cargar.")
            self.catalog_current_page = 1
            self.catalog_total_pages = 1
            self._update_catalog_pagination_controls()
            return

        unique_items: list[AnimeEntry] = []
        for anime in items:
            key = self._catalog_item_key(anime)
            if not key or key in self.catalog_seen_keys:
                continue
            self.catalog_seen_keys.add(key)
            unique_items.append(anime)

        if not unique_items:
            if reset:
                self.catalog_message.configure(text="No se pudo cargar un catalogo inicial.")
                self.set_status("Catalogo vacio.")
            self.catalog_current_page = 1
            self.catalog_total_pages = 1
            self._update_catalog_pagination_controls()
            return

        self.catalog_items = unique_items
        if page == 1:
            featured = self._pick_catalog_featured(unique_items)
            if featured is not None:
                self._set_catalog_hero(featured)

        if self.catalog_mode == "search":
            total_pages = max(1, math.ceil(len(self.catalog_items) / self.catalog_page_size))
            self.catalog_total_pages = total_pages
            self.catalog_current_page = max(1, min(page, total_pages))
            start = (self.catalog_current_page - 1) * self.catalog_page_size
            page_items = self.catalog_items[start:start + self.catalog_page_size]
            message_text = (
                f"Mostrando {len(self.catalog_items)} resultado(s) para '{self.catalog_query}' en "
                f"{self._catalog_provider_label()}."
            )
            self.set_status("Resultados listos en el catalogo.")
        else:
            self.catalog_total_pages = max(1, self.catalog_total_pages)
            self.catalog_current_page = max(1, min(page, self.catalog_total_pages))
            page_items = self.catalog_items[: self.catalog_page_size]
            message_text = f"Mostrando {len(page_items)} anime(s) en la pagina {self.catalog_current_page} de {self.catalog_total_pages}."
            self.set_status("Selecciona un anime del catalogo.")

        for child in self.catalog_container.winfo_children():
            child.destroy()

        grid = ttk.Frame(self.catalog_container, style="Panel.TFrame")
        grid.pack(fill="x", expand=False)
        columns = 4
        for index, anime in enumerate(page_items):
            row = index // columns
            col = index % columns
            card = MediaCard(grid, anime, self.choose_catalog_anime)
            card.grid(row=row, column=col, padx=12, pady=12, sticky="n")
            card.set_placeholder(anime.title or anime.id)
            self.catalog_cards.append(card)
            key = self._catalog_item_key(anime)
            if key:
                self.catalog_card_map[key] = card
            self.executor.submit(self._load_card_artwork, card, anime, (190, 270))

        for col in range(columns):
            grid.grid_columnconfigure(col, weight=1, uniform="catalog_cards")

        self._update_catalog_pagination_controls()
        self.catalog_message.configure(text=message_text)
        self.set_status("Selecciona un anime del catalogo.")

    def _dedupe_catalog_items(self, items: list[AnimeEntry]) -> list[AnimeEntry]:
        unique: list[AnimeEntry] = []
        seen: set[str] = set()
        for anime in items:
            key = self._catalog_item_key(anime)
            if not key or key in seen:
                continue
            seen.add(key)
            unique.append(anime)
        return unique

    def _append_catalog_section(self, section_title: str, section_items: list[AnimeEntry]):
        if not section_items:
            return

        section = self._ensure_catalog_section(section_title)
        for anime in section_items:
            key = self._catalog_item_key(anime)
            if not key or key in section["seen"]:
                continue
            section["seen"].add(key)
            card = MediaCard(section["inner"], anime, self.choose_catalog_anime)
            card.pack(side="left", padx=(0, 14), pady=(0, 6))
            card.set_placeholder(anime.title or anime.id)
            self.catalog_cards.append(card)
            self.catalog_card_map[key] = card
            section["items"].append(anime)
            section["count_label"].configure(text=f"{len(section['items'])} titulo(s)")
            self.executor.submit(self._load_card_artwork, card, anime, (190, 270))

    def _ensure_catalog_section(self, section_title: str) -> dict[str, Any]:
        if not hasattr(self, "catalog_section_map"):
            self.catalog_section_map = {}

        section = self.catalog_section_map.get(section_title)
        if section is not None:
            return section

        section_frame = ttk.Frame(self.catalog_container, style="Panel.TFrame", padding=(0, 8, 0, 18))
        section_frame.pack(fill="x", expand=False, pady=(0, 12))
        title_row = ttk.Frame(section_frame, style="Panel.TFrame")
        title_row.pack(fill="x", pady=(0, 8))
        ttk.Label(title_row, text=section_title, style="Section.TLabel").pack(side="left", anchor="w")
        count_label = ttk.Label(title_row, text="0 titulo(s)", style="SubHeader.TLabel")
        count_label.pack(side="left", padx=(10, 0))
        strip = self._build_horizontal_strip(section_frame)
        strip["frame"].pack(fill="x", expand=False)
        section = {
            "frame": section_frame,
            "title_row": title_row,
            "count_label": count_label,
            "inner": strip["inner"],
            "canvas": strip["canvas"],
            "items": [],
            "seen": set(),
        }
        self.catalog_section_map[section_title] = section
        self.catalog_sections.append(strip)
        return section

    def _catalog_scroll_probe(self, first: float, last: float):
        return

    def _pick_catalog_featured(self, items: list[AnimeEntry]) -> AnimeEntry | None:
        if not items:
            return None

        def score(anime: AnimeEntry) -> tuple[float, int, int]:
            rating_text = safe_text(anime.rating).strip()
            try:
                rating = float(re.search(r"\d+(?:\.\d+)?", rating_text).group(0)) if re.search(r"\d+(?:\.\d+)?", rating_text) else 0.0
            except Exception:
                rating = 0.0
            has_cover = 0 if anime.cover else 1
            has_genres = 0 if anime.genres else 1
            return (-rating, has_cover, has_genres)

        return sorted(items, key=score)[0]

    def _set_catalog_hero(self, anime: AnimeEntry):
        if self.catalog_window is None or not self.catalog_window.winfo_exists():
            return

        self.catalog_hero_title.configure(text=anime.title or "Sin titulo")
        hero_meta_parts = [part for part in [anime.type, anime.rating, anime.source] if part]
        self.catalog_hero_meta.configure(text="   ".join(hero_meta_parts) if hero_meta_parts else "Anime destacado del catalogo")
        self.catalog_hero_synopsis.config(state="normal")
        self.catalog_hero_synopsis.delete("1.0", tk.END)
        synopsis = anime.synopsis or "Selecciona este anime para abrir su ficha y seguir con episodios y servidores."
        self.catalog_hero_synopsis.insert("1.0", synopsis)
        self.catalog_hero_synopsis.config(state="disabled")

        def task():
            cover = anime.cover or ""
            if not cover:
                image = make_placeholder((240, 360), anime.title or anime.id)
                self._queue_ui(self._apply_catalog_hero, image)
                return
            try:
                image = load_image_from_url(cover, (240, 360), referer=anime.url or self._detail_base_url)
            except Exception:
                image = make_placeholder((240, 360), anime.title or anime.id)
            self._queue_ui(self._apply_catalog_hero, image)

        self.executor.submit(task)
        self.catalog_hero_featured = anime

    def _apply_catalog_hero(self, image: Image.Image):
        self.catalog_hero_ref = ImageTk.PhotoImage(image)
        self.catalog_hero_cover.configure(image=self.catalog_hero_ref)

    def _open_catalog_featured(self):
        anime = getattr(self, "catalog_hero_featured", None)
        if anime is not None:
            self.choose_catalog_anime(anime)

    def _build_catalog_sections(self, items: list[AnimeEntry]) -> list[tuple[str, list[AnimeEntry]]]:
        sections: dict[str, list[AnimeEntry]] = {}
        for anime in items:
            category = self._catalog_category_for(anime)
            sections.setdefault(category, [])
            if self._catalog_item_key(anime) not in {self._catalog_item_key(existing) for existing in sections[category]}:
                sections[category].append(anime)

        ordered: list[tuple[str, list[AnimeEntry]]] = []
        for label in self._catalog_category_order():
            source_items = sections.get(label, [])
            if len(source_items) >= 1:
                ordered.append((label, source_items))

        others = sections.get("Otros", [])
        if others:
            ordered.append(("Otros", others))
        return ordered

    def _catalog_item_key(self, anime: AnimeEntry) -> str:
        return safe_text(anime.url or anime.id or anime.title).strip().lower()

    def _catalog_category_order(self) -> list[str]:
        return [
            "Ciencia ficción",
            "Terror",
            "Acción",
            "Aventura",
            "Fantasía",
            "Comedia",
            "Drama",
            "Romance",
            "Misterio",
            "Isekai",
            "Slice of Life",
            "Deportes",
            "Escuela",
            "Películas",
            "OVA",
            "Especiales",
        ]

    def _catalog_category_for(self, anime: AnimeEntry) -> str:
        title_text = safe_text(anime.title).strip().lower()
        synopsis_text = safe_text(anime.synopsis).strip().lower()
        genres = [safe_text(item).strip().lower() for item in anime.genres if safe_text(item).strip()]
        genre_text = " | ".join([title_text, synopsis_text, " | ".join(genres)])

        genre_map = [
            ("Ciencia ficción", ("ciencia fic", "sci-fi", "scifi", "science fiction", "cyberpunk", "mecha", "futur")),
            ("Terror", ("terror", "horror", "gore", "suspenso", "thriller")),
            ("Acción", ("acción", "accion", "action", "batalla", "shounen", "shonen")),
            ("Aventura", ("aventura", "adventure", "travel")),
            ("Fantasía", ("fantas", "fantasy", "magic", "magia")),
            ("Comedia", ("comedia", "comedy", "parodia")),
            ("Drama", ("drama", "melodrama")),
            ("Romance", ("romance", "romantic", "shoujo")),
            ("Misterio", ("misterio", "mystery", "detective", "investig")),
            ("Isekai", ("isekai",)),
            ("Slice of Life", ("slice of life", "vida cotidiana", "cotidiana")),
            ("Deportes", ("deporte", "sports", "sport")),
            ("Escuela", ("escolar", "school", "academia", "student")),
        ]

        for label, needles in genre_map:
            if any(needle in genre_text for needle in needles):
                return label

        type_text = safe_text(anime.type).strip().lower()
        if "pel" in type_text or "movie" in type_text:
            return "Películas"
        if "ova" in type_text:
            return "OVA"
        if "special" in type_text:
            return "Especiales"

        return "Otros"

    def _build_horizontal_strip(self, parent: tk.Widget) -> dict[str, Any]:
        wrapper = tk.Frame(parent, bg=PANEL)
        canvas = tk.Canvas(wrapper, bg=PANEL, highlightthickness=0, bd=0, height=340)
        scrollbar = tk.Scrollbar(wrapper, orient="horizontal", command=canvas.xview)
        inner = tk.Frame(canvas, bg=PANEL)
        window_id = canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.configure(xscrollcommand=scrollbar.set)

        def _on_configure(_event=None):
            canvas.configure(scrollregion=canvas.bbox("all"))

        def _on_canvas(event):
            canvas.itemconfigure(window_id, height=event.height)

        inner.bind("<Configure>", _on_configure)
        canvas.bind("<Configure>", _on_canvas)
        canvas.pack(fill="x", expand=True)
        scrollbar.pack(fill="x")
        return {"frame": wrapper, "canvas": canvas, "inner": inner, "scrollbar": scrollbar}

    def _load_card_artwork(self, card: MediaCard, anime: AnimeEntry, size: tuple[int, int]):
        url_candidates = [anime.cover]

        for url in url_candidates:
            url = safe_text(url).strip()
            if not url:
                continue
            try:
                image = load_image_from_url(url, size, referer=anime.url or self._detail_base_url)
            except Exception:
                continue
            self.root.after(
                0,
                lambda image=image, card=card: card.set_image(image) if card.winfo_exists() else None,
            )
            return

        fallback = make_placeholder(size, anime.title or anime.id)
        self.root.after(
            0,
            lambda image=fallback, card=card: card.set_image(image) if card.winfo_exists() else None,
        )

    def _progressive_fill_catalog(self, token: int, items: list[AnimeEntry]):
        if self.client is None:
            return

        for index, anime in enumerate(items):
            if token != self.catalog_progress_token:
                return

            try:
                detail = self.client.info(anime.url or anime.id or anime.title)
            except Exception:
                detail = None

            if token != self.catalog_progress_token:
                return

            detail_entry = normalize_entry(detail if detail is not None else anime)
            merged = anime
            if detail_entry.title:
                merged.title = detail_entry.title
            if detail_entry.cover:
                merged.cover = detail_entry.cover
            if detail_entry.rating:
                merged.rating = detail_entry.rating
            if detail_entry.type:
                merged.type = detail_entry.type
            if detail_entry.source:
                merged.source = detail_entry.source
            if detail_entry.genres:
                merged.genres = detail_entry.genres
            if detail_entry.synopsis:
                merged.synopsis = detail_entry.synopsis

            key = self._catalog_item_key(merged)
            card = self.catalog_card_map.get(key)
            if card is None:
                continue

            def update_card(card=card, anime=merged):
                if not card.winfo_exists():
                    return
                card.update_metadata(anime)
                if anime.cover:
                    self._load_card_artwork(card, anime, (190, 270))

            self._queue_ui(update_card)
            if index < len(items) - 1:
                time.sleep(0.08)

        if token == self.catalog_progress_token:
            self._queue_ui(lambda: self.catalog_message.configure(text="Catalogo listo. Puedes seguir explorando."))

    def choose_catalog_anime(self, anime: AnimeEntry):
        self.search_var.set(anime.title or anime.id)
        self.current_anime = anime
        self.autoplay_selected_anime = True
        self.enter_main_view(start_default=False)
        self.root.after(120, lambda anime=anime: self.load_anime(anime))

    def enter_main_view(self, start_default: bool = False):
        if self.catalog_window is not None and self.catalog_window.winfo_exists():
            self.catalog_window.destroy()
        self.catalog_window = None
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()
        self.set_status("Listo para buscar o reproducir.")
        if start_default and self.current_anime is None:
            self.root.after(200, self.search)

    def search(self):
        query = self.search_var.get().strip()
        if not query:
            self.set_status("Escribe un titulo para buscar.")
            return
        if self.client is None:
            self.set_status("Esperando la libreria animeflv...")
            return

        self.search_token += 1
        token = self.search_token
        self.set_status(f"Buscando '{query}'...")
        self.add_activity(f"Buscando: {query}")
        self._clear_results()
        placeholder = ttk.Label(self.results_container, text="Cargando resultados...", style="HeroMeta.TLabel")
        placeholder.grid(row=0, column=0, sticky="w", padx=4, pady=4)

        def task():
            try:
                raw_results = self.client.search(query)
                results = [normalize_entry(item) for item in raw_results]
            except Exception as exc:
                self._queue_ui(self.show_error, "Error en busqueda", exc)
                return

            self._queue_ui(self.populate_results, token, results, query)

        self.executor.submit(task)

    def _clear_results(self):
        for child in self.results_container.winfo_children():
            child.destroy()

    def populate_results(self, token: int, results: list[AnimeEntry], query: str):
        if token != self.search_token:
            return

        self.results = results
        self._clear_results()

        if not results:
            empty = ttk.Label(
                self.results_container,
                text=f"No se encontro nada para '{query}'.",
                style="HeroMeta.TLabel",
            )
            empty.grid(row=0, column=0, sticky="w", padx=4, pady=4)
            self.set_status("Sin resultados.")
            return

        columns = 4
        for index, anime in enumerate(results[:24]):
            row = index // columns
            col = index % columns
            card = MediaCard(self.results_container, anime, self.load_anime)
            card.grid(row=row, column=col, padx=10, pady=10, sticky="n")
            card.set_placeholder(anime.title or anime.id)
            self.executor.submit(self._load_card_artwork, card, anime, (180, 255))

        for col in range(columns):
            self.results_container.grid_columnconfigure(col, weight=1, uniform="cards")

        self.set_status(f"{len(results)} resultado(s) para '{query}'.")
        self.add_activity(f"Se cargaron {len(results)} resultados para {query}.")
        self.load_anime(results[0])

    def _load_card_image(self, card: MediaCard, url: str, fallback: str):
        if not url:
            return
        try:
            image = load_image_from_url(url, (180, 255), referer=self._detail_base_url)
        except (URLError, OSError, ValueError):
            image = make_placeholder((180, 255), fallback)

        self._queue_ui(card.set_image, image)

    def load_anime(self, anime: AnimeEntry):
        if self.client is None:
            return

        self.detail_token += 1
        token = self.detail_token
        self.current_anime = anime
        self.current_episodes = []
        self.filtered_episodes = []
        self.current_servers = []
        self.current_episode_index = 0
        self.current_server_index = 0
        self.episode_filter_var.set("")
        self.episodes_loading = True
        self.episodes_list.delete(0, tk.END)
        self.episodes_list.insert(tk.END, "Cargando episodios...")
        self.episodes_list.itemconfig(0, foreground=MUTED, background="#101827")
        self.servers_list.delete(0, tk.END)
        self.servers_list.insert(tk.END, "Cargando servidores...")
        self.servers_list.itemconfig(0, foreground=MUTED, background="#101827")
        self.set_status(f"Cargando ficha de {anime.title or anime.id}...")
        self.add_activity(f"Abriendo ficha: {anime.title or anime.id}")

        self._set_hero(anime)
        self._set_hero_cover(anime.cover, anime.title or anime.id)

        def task():
            detail_client = AnimeFLVClient()
            try:
                normalized = None
                for attempt in range(3):
                    raw = detail_client.info(anime.url or anime.id or anime.title)
                    normalized = self._normalize_info(raw, anime)
                    if normalized.episodes or attempt == 2:
                        break
                    time.sleep(0.35)
                if normalized is None:
                    raise RuntimeError("No se pudo normalizar la ficha del anime.")
            except Exception as exc:
                self._queue_ui(self.show_error, "Error al cargar anime", exc)
                return
            finally:
                detail_client.close()

            self._queue_ui(self._apply_loaded_anime, token, normalized)

        self.detail_executor.submit(task)

    def _apply_loaded_anime(self, token: int, anime: AnimeEntry):
        if token != self.detail_token:
            return

        self.current_anime = anime
        self._set_hero(anime)
        self._set_hero_cover(anime.cover, anime.title or anime.id)
        self.populate_episodes(anime.episodes)

        meta = [part for part in [anime.type, anime.status, f"Rating {anime.rating}"] if part]
        if anime.genres:
            meta.append("Generos: " + ", ".join(anime.genres))
        if anime.alternative_titles:
            meta.append("Alias: " + ", ".join(anime.alternative_titles[:3]))
        if anime.source:
            meta.append(f"Fuente: {anime.source}")
        self.hero_meta.configure(text="   ".join(meta) if meta else "Sin metadatos disponibles")
        self._set_hero_synopsis(anime.synopsis or "No hay sinopsis disponible.")
        self.set_status(f"Ficha cargada: {anime.title or anime.id}.")
        self.add_activity(f"Ficha lista: {anime.title or anime.id}")

        if self.autoplay_selected_anime and anime.episodes:
            self.autoplay_selected_anime = False
            self.episodes_list.selection_clear(0, tk.END)
            self.episodes_list.selection_set(0)
            self.episodes_list.see(0)
            self.load_servers(anime.episodes[0], autoplay=True)
        else:
            self.autoplay_selected_anime = False

    def _normalize_info(self, raw: Any, fallback: AnimeEntry) -> AnimeEntry:
        if isinstance(raw, list) and raw:
            raw = raw[0]
        if isinstance(raw, dict) and isinstance(raw.get("info"), list) and raw["info"]:
            raw = raw["info"][0]

        anime = normalize_entry(raw if raw is not None else fallback.raw or fallback)
        if not anime.id:
            anime.id = fallback.id
        if not anime.title:
            anime.title = fallback.title
        if not anime.cover:
            anime.cover = fallback.cover
        if not anime.synopsis:
            anime.synopsis = fallback.synopsis
        if not anime.rating:
            anime.rating = fallback.rating

        raw_dict = raw if isinstance(raw, dict) else {}
        episodes = raw_dict.get("episodes")
        if isinstance(episodes, list):
            anime.episodes = [normalize_episode_item(item) for item in episodes]
        else:
            anime.episodes = self._extract_episodes(raw_dict)

        genres = raw_dict.get("genres") if isinstance(raw_dict, dict) else None
        if isinstance(genres, list):
            anime.genres = [safe_text(item) for item in genres if item is not None]
        elif isinstance(raw_dict.get("genre"), list):
            anime.genres = [safe_text(item) for item in raw_dict["genre"] if item is not None]

        anime.status = safe_text(raw_dict.get("status") or raw_dict.get("state") or anime.status)
        if isinstance(raw_dict.get("alternative_titles"), list):
            anime.alternative_titles = [
                safe_text(item) for item in raw_dict["alternative_titles"] if item is not None
            ]

        return anime

    def _extract_episodes(self, raw: dict[str, Any]) -> list[dict[str, Any]]:
        candidates = [
            raw.get("episode"),
            raw.get("eps"),
            raw.get("videos"),
            raw.get("videos_data"),
            raw.get("servers"),
            raw.get("data"),
        ]
        for candidate in candidates:
            if isinstance(candidate, list):
                return [normalize_episode_item(item) for item in candidate]
        return []


class JkAnimeClient:
    def __init__(self):
        self._base_url = "https://jkanime.net"
        self._directory_url = f"{self._base_url}/directorio"
        self._home_cache: list[dict[str, Any]] = []
        self._info_cache: dict[str, dict[str, Any]] = {}
        self._directory_cache: dict[int, list[dict[str, Any]]] = {}

    def search(self, query: str) -> list[Any]:
        query = query.strip()
        if not query:
            return self.catalog(limit=10)
        try:
            items = self._search_remote(query)
            if items:
                return items
        except Exception:
            pass
        lowered = query.lower()
        fallback: list[dict[str, Any]] = []
        for page in range(1, min(self._browse_page_count(), 8) + 1):
            try:
                for item in self._browse_remote(page=page):
                    entry = normalize_entry(item)
                    haystack = " ".join(
                        safe_text(part).lower()
                        for part in (
                            entry.title,
                            entry.synopsis,
                            entry.type,
                            entry.status,
                            " ".join(entry.genres),
                        )
                        if safe_text(part)
                    )
                    if lowered not in haystack:
                        continue
                    key = self._normalize_cache_key(entry.url or entry.id or entry.title)
                    if not key or any(self._normalize_cache_key(existing.get("url") or existing.get("id") or existing.get("title")) == key for existing in fallback):
                        continue
                    fallback.append(entry.raw if entry.raw is not None else item)
                    if len(fallback) >= 40:
                        return fallback
            except Exception:
                continue
        return fallback

    def catalog(self, limit: int = 10) -> list[Any]:
        return self.catalog_page(1, limit=limit)

    def catalog_page(self, page: int = 1, limit: int = 10) -> list[Any]:
        items = self._browse_remote(page=max(1, page))
        if not items and page == 1:
            items = self._home_anime_items(limit=max(limit, 20))
        return items[:limit]

    def random_anime(self) -> Any:
        pages = self._browse_page_count()
        for _ in range(6):
            page = random.randint(1, max(1, pages))
            try:
                items = self._browse_remote(page=page)
            except Exception:
                continue
            if items:
                return random.choice(items)
        raise RuntimeError("No se pudo cargar JkAnime.")

    def info(self, anime_id: str) -> Any:
        url = self._resolve_url(anime_id)
        if not url:
            raise RuntimeError("Anime sin URL valida en JkAnime.")
        cache_key = self._normalize_cache_key(url)
        cached = self._info_cache.get(cache_key, {})
        fresh = self._anime_detail_remote(url)
        if cached:
            if not fresh.get("episodes") and cached.get("episodes"):
                fresh["episodes"] = cached["episodes"]
            if not fresh.get("synopsis") and cached.get("synopsis"):
                fresh["synopsis"] = cached["synopsis"]
            if not fresh.get("cover") and cached.get("cover"):
                fresh["cover"] = cached["cover"]
        self._info_cache[cache_key] = dict(fresh)
        return fresh

    def episode_servers(self, episode_id: str) -> list[Any]:
        url = self._resolve_url(episode_id)
        if not url:
            return []
        return [{"label": "JkAnime", "url": url, "source": "JkAnime"}]

    def download_links(self, episode_id: str) -> list[Any]:
        return self.episode_servers(episode_id)

    def close(self) -> None:
        return None

    def _normalize_cache_key(self, value: str) -> str:
        value = safe_text(value).strip().lower()
        return re.sub(r"[^a-z0-9]+", "-", value).strip("-")

    def _resolve_url(self, anime_id: str) -> str:
        anime_id = safe_text(anime_id).strip()
        if not anime_id:
            return ""
        if anime_id.startswith("http://") or anime_id.startswith("https://"):
            return anime_id
        if anime_id.startswith("jkanime:"):
            anime_id = anime_id.split(":", 1)[1]
        if anime_id.startswith("/"):
            anime_id = anime_id.lstrip("/")
        if anime_id.startswith("directorio/") or anime_id.startswith("capitulo/") or anime_id.startswith("playlist/"):
            return urljoin(self._base_url, anime_id)
        return urljoin(self._base_url, f"/{anime_id.strip('/')}/")

    def _get_soup(self, url: str) -> BeautifulSoup:
        return BeautifulSoup(self._get_html(url), "lxml")

    def _get_html(self, url: str) -> str:
        response = cloudscraper.create_scraper().get(url, timeout=20)
        return response.text

    @staticmethod
    def _extract_image_url(node: Any) -> str:
        if node is None:
            return ""
        for attr in ("src", "data-src", "data-original", "data-lazy-src", "data-srcset", "content"):
            value = safe_text(node.get(attr))
            if value:
                return value.split()[0]
        return ""

    def _browse_page_count(self) -> int:
        soup = self._get_soup(f"{self._directory_url}?p=1")
        pages = [1]
        for anchor in soup.select('a[href*="/directorio?p="]'):
            href = safe_text(anchor.get("href"))
            match = re.search(r"[?&]p=(\d+)", href)
            if match:
                pages.append(int(match.group(1)))
        return max(pages) if pages else 1

    def _browse_remote(self, page: int = 1) -> list[dict[str, Any]]:
        page = max(1, page)
        cached = self._directory_cache.get(page)
        if cached is not None:
            return list(cached)

        html = self._get_html(f"{self._directory_url}?p={page}")
        items = self._extract_directory_items(html)
        if not items:
            items = self._extract_anime_cards(BeautifulSoup(html, "lxml"))
        self._directory_cache[page] = list(items)
        return list(items)

    def _search_remote(self, query: str) -> list[dict[str, Any]]:
        lowered = query.strip().lower()
        if not lowered:
            return []

        results: list[dict[str, Any]] = []
        seen: set[str] = set()
        page_count = max(1, min(self._browse_page_count(), 12))
        for page in range(1, page_count + 1):
            for item in self._browse_remote(page=page):
                entry = normalize_entry(item)
                haystack = " ".join(
                    safe_text(part).lower()
                    for part in (
                        entry.title,
                        entry.synopsis,
                        entry.type,
                        entry.status,
                        " ".join(entry.genres),
                    )
                    if safe_text(part)
                )
                if lowered not in haystack:
                    continue
                key = self._normalize_cache_key(entry.url or entry.id or entry.title)
                if not key or key in seen:
                    continue
                seen.add(key)
                results.append(entry.raw if entry.raw is not None else item)
                if len(results) >= 40:
                    return results
        return results

    def _extract_directory_items(self, html: str) -> list[dict[str, Any]]:
        match = re.search(r"var\s+animes\s*=\s*(\{.*?\})\s*;", html, re.S)
        if not match:
            return []
        try:
            payload = json.loads(match.group(1))
        except json.JSONDecodeError:
            return []

        items = payload.get("data", [])
        if not isinstance(items, list):
            return []

        results: list[dict[str, Any]] = []
        seen: set[str] = set()
        for item in items:
            if not isinstance(item, dict):
                continue
            slug = safe_text(item.get("slug"))
            title = safe_text(item.get("title") or item.get("short_title") or slug)
            url = safe_text(item.get("url") or urljoin(self._base_url, f"/{slug.strip('/')}/"))
            if not title or not url:
                continue
            key = self._normalize_cache_key(url or slug or title)
            if not key or key in seen:
                continue
            seen.add(key)
            studio = item.get("studios")
            studio_name = ""
            studio_id = ""
            if isinstance(studio, dict):
                studio_name = safe_text(studio.get("nombre") or studio.get("name"))
                studio_id = safe_text(studio.get("id"))
            elif isinstance(studio, str):
                studio_name = safe_text(studio)
            results.append(
                {
                    "id": f"jkanime:{slug or self._normalize_cache_key(url)}",
                    "title": title,
                    "cover": safe_text(item.get("image")),
                    "synopsis": safe_text(item.get("synopsis")),
                    "rating": "",
                    "type": safe_text(item.get("tipo") or item.get("type") or "JkAnime"),
                    "url": url,
                    "source": "JkAnime",
                    "genres": [safe_text(item.get("type"))] if safe_text(item.get("type")) else [],
                    "status": safe_text(item.get("estado") or item.get("status")),
                    "alternative_titles": [safe_text(item.get("short_title"))] if safe_text(item.get("short_title")) else [],
                    "raw": item,
                }
            )
        return results

    def _extract_anime_cards(self, soup: BeautifulSoup) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        seen: set[str] = set()
        blocked_titles = {
            "salir",
            "inicio",
            "directorio",
            "buscar",
            "top",
            "historial",
            "comunidad",
            "comentarios",
            "categorias",
            "categorías",
            "episodios",
            "episodio",
            "aplicacion",
            "aplicación",
            "descargar",
            "registrarse",
            "registro",
            "iniciar sesion",
            "iniciar sesión",
            "login",
            "logout",
            "ver ahora",
            "global",
            "mas",
            "más",
        }
        for anchor in soup.select("a[href]"):
            href = safe_text(anchor.get("href"))
            if not href or href.startswith(("http://", "https://")):
                continue
            if any(
                href.startswith(prefix)
                for prefix in (
                    "/directorio",
                    "/buscar",
                    "/historial",
                    "/top",
                    "/comunidad",
                    "/categorias",
                    "/ep",
                    "/chat",
                    "/usuario",
                    "/dash",
                    "/login",
                    "/registro",
                    "/privacy",
                )
            ):
                continue
            if href.count("/") > 3:
                continue
            if anchor.find_parent(["nav", "header", "footer", "aside"]) is not None:
                continue
            img = anchor.select_one("img") or (anchor.find_parent().select_one("img") if anchor.find_parent() else None)
            if img is None:
                continue
            title = safe_text(anchor.get_text(" ", strip=True) or anchor.get("title") or anchor.get("aria-label") or "")
            if not title and img is not None:
                title = safe_text(img.get("alt") or img.get("title") or "")
            normalized_title = title.strip().lower()
            if not title or len(title) < 2:
                continue
            if normalized_title in blocked_titles:
                continue
            if any(normalized_title.startswith(prefix) for prefix in ("salir", "iniciar", "registr", "descargar", "ver ahora")):
                continue
            key = self._normalize_cache_key(href or title)
            if not key or key in seen:
                continue
            seen.add(key)
            results.append(
                {
                    "id": f"jkanime:{href.strip('/').split('/')[-1]}",
                    "title": title,
                    "cover": urljoin(self._base_url, self._extract_image_url(img)) if img else "",
                    "synopsis": "",
                    "rating": "",
                    "type": "JkAnime",
                    "url": urljoin(self._base_url, href),
                    "source": "JkAnime",
                    "raw": anchor,
                }
            )
        return results

    def _home_anime_items(self, limit: int | None = None) -> list[dict[str, Any]]:
        if self._home_cache:
            items = list(self._home_cache)
            return items[:limit] if limit else items
        items = self._browse_remote(page=1)
        self._home_cache = list(items)
        return items[:limit] if limit else items

    def _anime_detail_remote(self, url: str) -> dict[str, Any]:
        soup = self._get_soup(url)

        title_node = soup.select_one("h1") or soup.select_one("article h1")
        synopsis_node = soup.select_one("meta[name='description']")
        cover_node = soup.select_one("img")
        type_node = soup.select_one("span.Type")
        rating_node = soup.select_one("span.Vts")
        genre_nodes = soup.select("a[href*='genero'], a[href*='genre'], a[href*='/directorio/']")
        episodes: list[dict[str, Any]] = []

        episode_links = soup.select(
            'a[href*="/capitulo/"], a[href*="/capitulos/"], a[href*="/episodio/"], a[href*="/episodios/"], a[href*="/video/"]'
        )
        for link in episode_links:
            href = safe_text(link.get("href"))
            label = safe_text(link.get_text(" ", strip=True) or link.get("title") or href)
            if not href or not label:
                continue
            episodes.append(
                {
                    "id": f"jkanime:{href.strip('/')}",
                    "label": label,
                    "number": re.sub(r"\D+", "", label),
                    "url": urljoin(self._base_url, href),
                    "raw": link,
                }
            )

        if not episodes:
            for link in soup.select("a[href]"):
                href = safe_text(link.get("href"))
                label = safe_text(link.get_text(" ", strip=True) or link.get("title") or href)
                if "/playlist/" not in href or not label:
                    continue
                episodes.append(
                    {
                        "id": f"jkanime:{href.strip('/')}",
                        "label": label,
                        "number": "",
                        "url": urljoin(self._base_url, href),
                        "raw": link,
                    }
                )

        return {
            "id": f"jkanime:{self._normalize_cache_key(url)}",
            "title": safe_text(title_node.get_text(" ", strip=True) if title_node else ""),
            "cover": urljoin(self._base_url, self._extract_image_url(cover_node)) if cover_node else "",
            "synopsis": safe_text(synopsis_node.get("content", "") if synopsis_node else ""),
            "rating": safe_text(rating_node.get_text(" ", strip=True) if rating_node else ""),
            "type": safe_text(type_node.get_text(" ", strip=True) if type_node else "JkAnime"),
            "url": url,
            "episodes": episodes,
            "genres": [safe_text(item.get_text(" ", strip=True)) for item in genre_nodes if item is not None],
            "status": "",
            "alternative_titles": [],
            "source": "JkAnime",
            "raw": soup,
        }


class MultiSourceAnimeClient:
    def __init__(self):
        self.primary = AnimeFLVClient()
        self.secondary = JkAnimeClient()

    def search(self, query: str) -> list[Any]:
        merged: list[Any] = []
        seen: set[str] = set()
        for source_items in (self.primary.search(query), self.secondary.search(query)):
            for item in source_items:
                entry = normalize_entry(item)
                key = self._normalize_cache_key(entry.url or entry.id or entry.title)
                if not key or key in seen:
                    continue
                seen.add(key)
                merged.append(entry.raw if entry.raw is not None else item)
        return merged

    def catalog(self, limit: int = 10) -> list[Any]:
        return self.catalog_page(1, limit=limit)

    def catalog_page(self, page: int = 1, limit: int = 10) -> list[Any]:
        merged: list[Any] = []
        seen: set[str] = set()
        primary_items = self.primary.catalog_page(page, limit=limit)
        secondary_items = self.secondary.catalog_page(page, limit=limit)
        for source_items in (primary_items, secondary_items):
            for item in source_items:
                entry = normalize_entry(item)
                key = self._normalize_cache_key(entry.url or entry.id or entry.title)
                if not key or key in seen:
                    continue
                seen.add(key)
                merged.append(entry.raw if entry.raw is not None else item)
                if len(merged) >= limit:
                    return merged[:limit]
        return merged[:limit]

    def random_anime(self) -> Any:
        pools: list[Any] = []
        for provider in (self.primary, self.secondary):
            try:
                pools.append(provider.random_anime())
            except Exception:
                continue
        if not pools:
            raise RuntimeError("No se pudo obtener un anime aleatorio desde las fuentes disponibles.")
        return random.choice(pools)

    def info(self, anime_id: str) -> Any:
        source = self._source_for(anime_id)
        if source == "JkAnime":
            return self.secondary.info(anime_id)
        return self.primary.info(anime_id)

    def episode_servers(self, episode_id: str) -> list[Any]:
        source = self._source_for(episode_id)
        if source == "JkAnime":
            return self.secondary.episode_servers(episode_id)
        return self.primary.episode_servers(episode_id)

    def download_links(self, episode_id: str) -> list[Any]:
        source = self._source_for(episode_id)
        if source == "JkAnime":
            return self.secondary.download_links(episode_id)
        return self.primary.download_links(episode_id)

    def close(self) -> None:
        self.primary.close()
        self.secondary.close()

    @staticmethod
    def _normalize_cache_key(value: str) -> str:
        value = safe_text(value).strip().lower()
        return re.sub(r"[^a-z0-9]+", "-", value).strip("-")

    @staticmethod
    def _source_for(anime_id: str) -> str:
        value = safe_text(anime_id).lower()
        if "jkanime.net" in value or value.startswith("jkanime:"):
            return "JkAnime"
        return "AnimeFLV"


_ANIME_APP_METHODS = (
    "load_anime",
    "_load_card_image",
    "_normalize_info",
    "_extract_episodes",
    "render_anime",
    "_set_hero",
    "_set_hero_synopsis",
    "_set_hero_cover",
    "_show_catalog_selection",
    "_apply_catalog_preview",
    "_apply_hero_cover",
    "populate_episodes",
    "_episode_matches_filter",
    "_format_episode_label",
    "_format_server_label",
    "apply_episode_filter",
    "clear_episode_filter",
    "on_episode_selected",
    "load_servers",
    "_normalize_server",
    "_extract_resolution",
    "_is_blocked_server",
    "render_servers",
    "_selected_server",
    "_preferred_server_index",
    "open_selected_server",
    "play_selected_server",
    "copy_selected_server",
    "clear_detail",
    "open_site",
    "open_current_anime",
    "_restore_main_window",
    "_show_main_shell",
    "_show_player_shell",
    "show_player_view",
    "_watch_brave_window",
    "_restore_after_brave_close",
    "_restore_current_selection",
    "reload_player",
    "back_to_main_view",
    "back_to_catalog",
    "_close_player",
    "show_error",
    "on_close",
    "run",
)

for _method_name in _ANIME_APP_METHODS:
    _method = globals().get(_method_name)
    if callable(_method) and not hasattr(AnimeApp, _method_name):
        setattr(AnimeApp, _method_name, _method)

    def render_anime(self, token: int, anime: AnimeEntry):
        if token != self.detail_token:
            return

        self.current_anime = anime
        self._set_hero(anime)
        self._set_hero_cover(anime.cover, anime.title or anime.id)
        self.populate_episodes(anime.episodes)

        meta = [part for part in [anime.type, anime.status, f"Rating {anime.rating}"] if part]
        if anime.genres:
            meta.append("Generos: " + ", ".join(anime.genres))
        if anime.alternative_titles:
            meta.append("Alias: " + ", ".join(anime.alternative_titles[:3]))
        if anime.source:
            meta.append(f"Fuente: {anime.source}")
        self.hero_meta.configure(text="   ".join(meta) if meta else "Sin metadatos disponibles")
        self._set_hero_synopsis(anime.synopsis or "No hay sinopsis disponible.")
        self.set_status(f"Ficha cargada: {anime.title or anime.id}.")
        self.add_activity(f"Ficha lista: {anime.title or anime.id}")

        if self.autoplay_selected_anime and anime.episodes:
            self.autoplay_selected_anime = False
            self.episodes_list.selection_clear(0, tk.END)
            self.episodes_list.selection_set(0)
            self.episodes_list.see(0)
            self.load_servers(anime.episodes[0], autoplay=True)
        else:
            self.autoplay_selected_anime = False

    def _set_hero(self, anime: AnimeEntry):
        self.hero_label.configure(text=anime.title or "Sin titulo")

    def _set_hero_synopsis(self, text: str):
        self.hero_synopsis.config(state="normal")
        self.hero_synopsis.delete("1.0", tk.END)
        self.hero_synopsis.insert("1.0", text)
        self.hero_synopsis.config(state="disabled")

    def _set_hero_cover(self, url: str, fallback: str):
        if not url:
            image = make_placeholder((240, 360), fallback)
            self.hero_ref = ImageTk.PhotoImage(image)
            self.hero_cover.configure(image=self.hero_ref, text="")
            return

        def task():
            try:
                image = load_image_from_url(url, (240, 360), referer=self.current_anime.url if self.current_anime else self._detail_base_url)
            except (URLError, OSError, ValueError):
                image = make_placeholder((240, 360), fallback)
            self._queue_ui(self._apply_hero_cover, image)

        self.detail_executor.submit(task)

    def _show_catalog_selection(self, anime: AnimeEntry):
        if self.catalog_window is None or not self.catalog_window.winfo_exists():
            return

        self.catalog_title.configure(text=anime.title or "Sin titulo")
        info_lines = []
        if anime.type:
            info_lines.append(anime.type)
        if anime.rating:
            info_lines.append(f"Rating {anime.rating}")
        if anime.status:
            info_lines.append(anime.status)
        if anime.source:
            info_lines.append(anime.source)
        self.catalog_detail.configure(
            text="   ".join(info_lines) if info_lines else "Selecciona un anime para abrirlo en la vista principal."
        )

        if anime.cover:
            def task():
                try:
                    image = load_image_from_url(anime.cover, (290, 410), referer=anime.url or self._detail_base_url)
                except (URLError, OSError, ValueError):
                    image = make_placeholder((290, 410), anime.title or anime.id)
                self._queue_ui(self._apply_catalog_preview, image)

            self.executor.submit(task)
        else:
            preview = make_placeholder((290, 410), anime.title or anime.id)
            self._apply_catalog_preview(preview)

    def _apply_catalog_preview(self, image: Image.Image):
        self.catalog_preview_ref = ImageTk.PhotoImage(image)
        self.catalog_preview.configure(image=self.catalog_preview_ref)

    def _apply_hero_cover(self, image: Image.Image):
        self.hero_ref = ImageTk.PhotoImage(image)
        self.hero_cover.configure(image=self.hero_ref, text="")

    def populate_episodes(self, episodes: list[dict[str, Any]]):
        self.current_episodes = episodes
        self.episodes_loading = False
        self.apply_episode_filter()

    def _episode_matches_filter(self, episode: dict[str, Any], query: str) -> bool:
        if not query:
            return True
        label = safe_text(episode.get("label") or episode.get("id")).lower()
        episode_id = safe_text(episode.get("id")).lower()
        number = safe_text(episode.get("number")).lower()
        return query in label or query in episode_id or query in number

    def _format_episode_label(self, episode: dict[str, Any]) -> str:
        label = safe_text(episode.get("label") or episode.get("id") or "Episodio").strip()
        number = safe_text(episode.get("number")).strip()
        if number and number not in label.lower():
            return f"EP {number}  •  {label}"
        return label

    def _format_server_label(self, server: dict[str, Any]) -> str:
        label = safe_text(server.get("label") or "Servidor").strip()
        quality = int(server.get("quality") or 0)
        if quality:
            return f"{label}  •  {quality}p"
        return label

    def apply_episode_filter(self):
        query = safe_text(self.episode_filter_var.get()).strip().lower()
        episodes = self.current_episodes or []
        self.filtered_episodes = [episode for episode in episodes if self._episode_matches_filter(episode, query)]
        self.episodes_list.delete(0, tk.END)

        if self.episodes_loading:
            self.episodes_list.insert(tk.END, "Cargando episodios...")
            self.episodes_list.itemconfig(0, foreground=MUTED, background="#101827")
            return

        if not episodes:
            self.episodes_list.insert(tk.END, "No se encontraron episodios.")
            return

        if not self.filtered_episodes:
            self.episodes_list.insert(tk.END, "No hay episodios que coincidan.")
            self.episodes_list.itemconfig(0, foreground=MUTED, background="#101827")
            return

        for index, item in enumerate(self.filtered_episodes):
            self.episodes_list.insert(tk.END, self._format_episode_label(item))
            try:
                self.episodes_list.itemconfig(index, foreground=TEXT, background="#101827")
            except tk.TclError:
                pass
        self.episodes_list.selection_clear(0, tk.END)
        self.episodes_list.selection_set(0)
        self.episodes_list.see(0)

    def on_episode_selected(self, _event=None):
        selection = self.episodes_list.curselection()
        if not selection:
            return
        index = selection[0]
        if index >= len(self.filtered_episodes):
            return
        episode = self.filtered_episodes[index]
        if episode not in self.current_episodes:
            return
        self.current_episode_index = self.current_episodes.index(episode)
        self.load_servers(episode, autoplay=True)

    def clear_episode_filter(self):
        self.episode_filter_var.set("")
        self.apply_episode_filter()

    def load_servers(self, episode: dict[str, Any], autoplay: bool = False):
        if self.client is None:
            return

        episode_id = episode.get("id") or episode.get("url")
        if not episode_id:
            self.set_status("El episodio no tiene id utilizable.")
            return

        self.server_token += 1
        token = self.server_token
        self.servers_list.delete(0, tk.END)
        self.servers_list.insert(tk.END, "Cargando servidores...")
        self.set_status(f"Cargando servidores de {episode.get('label', episode_id)}...")
        self.add_activity(f"Buscando servidores para {episode.get('label', episode_id)}")

        def task():
            detail_client = AnimeFLVClient()
            try:
                servers = detail_client.episode_servers(str(episode.get("url") or episode_id))
                if not servers:
                    servers = detail_client.download_links(str(episode.get("url") or episode_id))
                normalized = [
                    item
                    for item in (self._normalize_server(server) for server in servers)
                    if not self._is_blocked_server(item)
                ]
            except Exception as exc:
                self._queue_ui(self.show_error, "Error al cargar servidores", exc)
                return
            finally:
                detail_client.close()

            self._queue_ui(self.render_servers, token, normalized, episode, autoplay)

        self.detail_executor.submit(task)

    def _normalize_server(self, raw: Any) -> dict[str, Any]:
        if isinstance(raw, dict):
            label = safe_text(raw.get("server") or raw.get("name") or raw.get("title") or raw.get("label"))
            url = safe_text(
                raw.get("url")
                or raw.get("link")
                or raw.get("href")
                or raw.get("source")
                or raw.get("code")
            )
            quality = self._extract_resolution(label, url, raw)
            return {"label": label or "Servidor", "url": url, "raw": raw, "quality": quality}
        quality = self._extract_resolution(safe_text(raw), safe_text(raw), raw)
        return {"label": safe_text(raw), "url": safe_text(raw), "raw": raw, "quality": quality}

    def _extract_resolution(self, *parts: Any) -> int:
        text_parts: list[str] = []
        for part in parts:
            if isinstance(part, dict):
                try:
                    text_parts.append(json.dumps(part, ensure_ascii=False))
                except Exception:
                    text_parts.append(str(part))
            else:
                text_parts.append(safe_text(part))
        combined = " ".join(piece.lower() for piece in text_parts if piece)
        match = re.search(r"(?<!\d)(\d{3,4})(?:\s*p)?", combined)
        if match:
            try:
                value = int(match.group(1))
                if 144 <= value <= 4320:
                    return value
            except ValueError:
                pass
        return 0

    def _is_blocked_server(self, server: dict[str, Any]) -> bool:
        label = safe_text(server.get("label") or server.get("server")).lower()
        raw = server.get("raw")
        code = ""
        if isinstance(raw, dict):
            code = safe_text(raw.get("server") or raw.get("title") or raw.get("name")).lower()
        return any(blocked in label or blocked in code for blocked in BLOCKED_SERVERS)

    def render_servers(self, token: int, servers: list[dict[str, Any]], episode: dict[str, Any], autoplay: bool = False):
        if token != self.server_token:
            return

        self.current_servers = servers
        self.servers_list.delete(0, tk.END)
        if not servers:
            self.servers_list.insert(tk.END, "No hay servidores disponibles.")
            self.set_status("No se encontraron servidores para ese episodio.")
            self.servers_list.itemconfig(0, foreground=MUTED, background="#101827")
            return

        for index, server in enumerate(servers):
            self.servers_list.insert(tk.END, self._format_server_label(server))
            try:
                self.servers_list.itemconfig(index, foreground=TEXT, background="#101827")
            except tk.TclError:
                pass

        best_index = self._preferred_server_index(servers)
        self.current_server_index = best_index
        self.servers_list.selection_clear(0, tk.END)
        self.servers_list.selection_set(best_index)
        self.set_status(f"{len(servers)} servidor(es) para {episode.get('label', 'el episodio')}.")
        self.add_activity(f"Servidores cargados para {episode.get('label', 'episodio')}")

        if autoplay:
            self.play_selected_server()

    def _selected_server(self) -> dict[str, Any] | None:
        selection = self.servers_list.curselection()
        if not selection or selection[0] >= len(self.current_servers):
            return None
        return self.current_servers[selection[0]]

    def _preferred_server_index(self, servers: list[dict[str, Any]]) -> int:
        if not servers:
            return 0

        def score(server: dict[str, Any]) -> tuple[int, int, int, int]:
            label = safe_text(server.get("label") or server.get("server")).lower()
            raw = server.get("raw")
            code = ""
            url = safe_text(server.get("url")).lower()
            quality = int(server.get("quality") or 0)
            if isinstance(raw, dict):
                code = safe_text(raw.get("server") or raw.get("title") or raw.get("name")).lower()

            has_url = 0 if safe_text(server.get("url")).strip() else 1
            quality_score = -quality if quality > 0 else 99999

            for idx, preferred in enumerate(SERVER_PREFERENCE):
                if preferred in label or preferred in code:
                    return (quality_score, has_url, idx, 0)
            return (quality_score, has_url, len(SERVER_PREFERENCE), 0)

        ranked = sorted(enumerate(servers), key=lambda item: score(item[1]))
        return ranked[0][0] if ranked else 0

    def open_selected_server(self):
        selected = self._selected_server()
        if not selected:
            if self.current_anime and self.current_anime.url:
                return self.show_player_view(self.current_anime.url, self.current_anime.title or "Ficha del anime")
                if open_in_brave(self.current_anime.url):
                    self._restore_main_window()
                    return
                webbrowser.open(self.current_anime.url)
                self.set_status("Abriendo la ficha del anime en el navegador.")
                self._restore_main_window()
            else:
                self.set_status("Selecciona un episodio o servidor primero.")
            return

        url = selected.get("url", "")
        if not url:
            self.set_status("El servidor seleccionado no tiene URL.")
            return
        server_selection = self.servers_list.curselection()
        if server_selection:
            self.current_server_index = server_selection[0]
        else:
            self.current_server_index = self._preferred_server_index(self.current_servers)
        return self.show_player_view(url, f"Reproduciendo {selected.get('label', 'Servidor')}")
        if open_in_brave(url):
            self.set_status(f"Abriendo en Brave: {selected.get('label', 'Servidor')}")
            self.add_activity(f"Reproduciendo: {selected.get('label', 'Servidor')}")
            self._restore_main_window()
            return
        self._close_player()
        self.set_status(f"Abriendo reproductor: {selected.get('label', 'Servidor')}")
        self.add_activity(f"Reproduciendo: {selected.get('label', 'Servidor')}")
        try:
            self.player_process = mp.get_context("spawn").Process(
                target=run_webview_player,
                args=(url, f"Reproduciendo {selected.get('label', 'Servidor')}"),
                daemon=True,
            )
            self.player_process.start()
        except Exception as exc:
            self.player_process = None
            self.show_error("No se pudo abrir el reproductor", exc)
            self.set_status("Cayó al navegador por compatibilidad.")
            webbrowser.open(url)

    def play_selected_server(self):
        self.open_selected_server()

    def copy_selected_server(self):
        selected = self._selected_server()
        if not selected:
            self.set_status("Selecciona un servidor primero.")
            return

        url = selected.get("url", "")
        if not url:
            self.set_status("El servidor seleccionado no tiene URL.")
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(url)
        self.set_status("URL copiada al portapapeles.")
        self.add_activity("URL copiada al portapapeles.")

    def clear_detail(self):
        self.current_anime = None
        self.current_episodes = []
        self.filtered_episodes = []
        self.current_servers = []
        self.episode_filter_var.set("")
        self.hero_label.configure(text="Selecciona un anime")
        self.hero_meta.configure(text="Busca un anime para ver su ficha")
        self._set_hero_synopsis("Cuando hagas una busqueda, la portada y la sinopsis apareceran aqui.")
        placeholder = make_placeholder((240, 360), "AnimeFLV")
        self.hero_ref = ImageTk.PhotoImage(placeholder)
        self.hero_cover.configure(image=self.hero_ref, text="")
        self.episodes_list.delete(0, tk.END)
        self.servers_list.delete(0, tk.END)

    def open_site(self):
        self.show_player_view("https://www3.animeflv.net/", "AnimeFLV")

    def open_current_anime(self):
        if self.current_anime and self.current_anime.url:
            self.show_player_view(self.current_anime.url, self.current_anime.title or "Ficha del anime")
            return
        self.set_status("No hay un anime seleccionado con URL disponible.")

    def _restore_main_window(self):
        self.root.after(150, lambda: (self.root.deiconify(), self.root.lift(), self.root.focus_force()))

    def _show_main_shell(self):
        if self.player_visible:
            self.player_shell.pack_forget()
            self.player_visible = False
        self.shell.pack(fill="both", expand=True)
        self.root.title(APP_TITLE)
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def _show_player_shell(self):
        self.shell.pack_forget()
        if self.catalog_window is not None and self.catalog_window.winfo_exists():
            self.catalog_window.destroy()
        self.catalog_window = None
        self.player_shell.pack(fill="both", expand=True)
        self.player_visible = True

    def show_player_view(self, url: str, title: str):
        if not url:
            self.set_status("No hay URL para reproducir.")
            return
        try:
            self.player_url = url
            self.player_title = title or "Reproductor"
            brave_proc = open_in_brave(url)
            if brave_proc is None:
                webbrowser.open(url)
                self.set_status(f"Abriendo en navegador: {self.player_title}")
                self.add_activity(f"Reproduciendo: {self.player_title}")
                return
            self.brave_process = brave_proc
            self.root.title(f"{APP_TITLE} - {self.player_title}")
            self.set_status(f"Abriendo en Brave: {self.player_title}")
            self.add_activity(f"Reproduciendo: {self.player_title}")
            self.root.withdraw()
            threading.Thread(target=self._watch_brave_window, daemon=True).start()
        except Exception as exc:
            self.show_error("No se pudo abrir el reproductor", exc)
            webbrowser.open(url)
            self.back_to_main_view()

    def _watch_brave_window(self):
        proc = self.brave_process
        if proc is None:
            return
        try:
            proc.wait()
        except Exception:
            pass
        finally:
            self.brave_process = None
        self.root.after(0, self._restore_after_brave_close)

    def _restore_after_brave_close(self):
        self.root.deiconify()
        self._show_main_shell()
        self._restore_current_selection()
        self.set_status("Volviste al buscador.")

    def _restore_current_selection(self):
        if self.current_episodes:
            episode_index = min(max(self.current_episode_index, 0), len(self.current_episodes) - 1)
            episode = self.current_episodes[episode_index]
            visible_index = episode_index
            if self.filtered_episodes:
                try:
                    visible_index = self.filtered_episodes.index(episode)
                except ValueError:
                    visible_index = None
            if visible_index is not None:
                self.episodes_list.selection_clear(0, tk.END)
                self.episodes_list.selection_set(visible_index)
                self.episodes_list.see(visible_index)
        if self.current_servers:
            server_index = min(max(self.current_server_index, 0), len(self.current_servers) - 1)
            self.servers_list.selection_clear(0, tk.END)
            self.servers_list.selection_set(server_index)
            self.servers_list.see(server_index)

    def reload_player(self):
        if self.player_url:
            self.show_player_view(self.player_url, self.player_title)

    def back_to_main_view(self):
        self._show_main_shell()
        self.set_status("Volviste al buscador.")

    def back_to_catalog(self):
        self._show_main_shell()
        self.set_status("Volviste al catálogo.")
        self.root.after(100, self.show_catalog)

    def _close_player(self):
        proc = self.player_process
        if proc is not None and proc.is_alive():
            proc.terminate()
            proc.join(timeout=2)
        self.player_process = None

    def show_error(self, title: str, exc: Exception):
        self.set_status(f"{title}: {exc}")
        messagebox.showerror(title, str(exc))
        self.add_activity(f"Error: {title}")

    def on_close(self):
        self._close_player()
        if self.catalog_window is not None and self.catalog_window.winfo_exists():
            self.catalog_window.destroy()
        if self.client is not None:
            self.client.close()
        self.detail_executor.shutdown(wait=False, cancel_futures=True)
        self.executor.shutdown(wait=False, cancel_futures=True)
        self.root.destroy()

    def run(self):
        self.root.mainloop()


for _method_name in _ANIME_APP_METHODS:
    if hasattr(MultiSourceAnimeClient, _method_name) and not hasattr(AnimeApp, _method_name):
        setattr(AnimeApp, _method_name, getattr(MultiSourceAnimeClient, _method_name))


def main():
    try:
        app = AnimeApp()
    except RuntimeError as exc:
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("AnimeFLV Player", str(exc))
        root.destroy()
        return
    app.run()


if __name__ == "__main__":
    main()

from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from app.bulletins.config import Settings


class AuthenticationError(RuntimeError):
    pass


class CrawlError(RuntimeError):
    pass


@dataclass(frozen=True)
class BulletinLink:
    url: str
    title: str
    filename: str
    number: int | None
    year: int | None
    month: int | None
    original_url: str | None = None
    verified: bool = True
    validation_error: str | None = None
    remote_content_length: int | None = None
    remote_etag: str | None = None
    remote_last_modified: str | None = None


MONTHS = {
    "janvier": 1,
    "fevrier": 2,
    "février": 2,
    "mars": 3,
    "avril": 4,
    "mai": 5,
    "juin": 6,
    "juillet": 7,
    "aout": 8,
    "août": 8,
    "septembre": 9,
    "octobre": 10,
    "novembre": 11,
    "decembre": 12,
    "décembre": 12,
}

MONTH_NAMES = {
    1: "Janvier",
    2: "Fevrier",
    3: "Mars",
    4: "Avril",
    5: "Mai",
    6: "Juin",
    7: "Juillet",
    8: "Aout",
    9: "Septembre",
    10: "Octobre",
    11: "Novembre",
    12: "Decembre",
}

ACCENTED_MONTH_NAMES = {
    2: "Février",
    8: "Août",
    12: "Décembre",
}


PDF_URL_RE = re.compile(
    r"(?:(?:https?:)?//[^\s\"'<>]+|/[^\s\"'<>]+|[A-Za-z0-9À-ÿ_./%+-]+)\.pdf(?:\?[^\s\"'<>]*)?",
    re.IGNORECASE,
)


def safe_filename(name: str) -> str:
    name = unquote(name).strip().replace("/", "-").replace("\\", "-")
    name = re.sub(r"[^A-Za-z0-9._À-ÿ -]+", "_", name)
    name = re.sub(r"\s+", "-", name)
    if not name.lower().endswith(".pdf"):
        name += ".pdf"
    return name[:180]


def parse_bulletin_metadata(url: str, title: str) -> tuple[str, int | None, int | None, int | None]:
    parsed = urlparse(url)
    filename = safe_filename(os.path.basename(parsed.path) or title or "bulletin.pdf")
    haystack = f"{filename} {title}".lower()

    number: int | None = None
    patterns = [
        r"(?:^|[^0-9])0*(\d{1,3})(?:[-_ .]|$)",
        r"bulletin\s*n?[°ºo]?\s*0*(\d{1,3})",
        r"n[°ºo]\s*0*(\d{1,3})",
    ]
    for pattern in patterns:
        match = re.search(pattern, haystack, flags=re.IGNORECASE)
        if match:
            value = int(match.group(1))
            if 1 <= value <= 999:
                number = value
                break

    year: int | None = None
    year_match = re.search(r"(19\d{2}|20\d{2})", haystack)
    if year_match:
        year = int(year_match.group(1))

    month: int | None = None
    normalized = normalize_for_match(haystack)
    for name, value in MONTHS.items():
        if normalize_for_match(name) in normalized:
            month = value
            break

    return filename, number, year, month




def is_index_bulletins_filename(filename: str) -> bool:
    """Return True for the remote PDF that is only the bulletin index.

    This file is useful on the club website but it is not a bulletin. It must
    not be downloaded, displayed or indexed as a searchable bulletin.
    """
    return safe_filename(filename).lower() == "000-index_bulletins.pdf"

def normalize_for_match(value: str) -> str:
    return (
        value.lower()
        .replace("é", "e")
        .replace("è", "e")
        .replace("ê", "e")
        .replace("ë", "e")
        .replace("û", "u")
        .replace("ù", "u")
        .replace("ü", "u")
        .replace("ô", "o")
        .replace("ö", "o")
        .replace("à", "a")
        .replace("â", "a")
        .replace("î", "i")
        .replace("ï", "i")
        .replace("ç", "c")
    )


class EntraideCrawler:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": settings.user_agent})
        self.allowed_hosts = {
            host
            for host in (urlparse(settings.login_url).hostname, urlparse(settings.bulletins_url).hostname)
            if host
        }

    def _allowed_remote_url(self, url: str) -> bool:
        parsed = urlparse(url)
        return parsed.scheme == "https" and parsed.hostname in self.allowed_hosts

    def _require_allowed_remote_url(self, url: str) -> None:
        if not self._allowed_remote_url(url):
            raise CrawlError(f"URL distante non autorisée : {url}")

    def login(self, username: str, password: str) -> None:
        login_page = self._get(self.settings.login_url)
        soup = BeautifulSoup(login_page.text, "html.parser")
        form = self._find_login_form(soup)
        if not form:
            raise AuthenticationError("Formulaire de connexion introuvable sur la page de login.")

        action = form.get("action") or self.settings.login_url
        submit_url = urljoin(self.settings.login_url, action)
        method = (form.get("method") or "post").lower()
        payload = self._build_login_payload(form, username, password)

        if method == "get":
            response = self._get(submit_url, params=payload)
        else:
            response = self._post(submit_url, data=payload)

        if self._page_still_has_login_form(response.text):
            raise AuthenticationError("Identifiant ou mot de passe incorrect, ou session refusee par le site.")

        # Validation concrete : la page des bulletins doit devenir accessible et contenir au moins un lien PDF.
        bulletins_page = self._get(self.settings.bulletins_url)
        pdf_links = self._extract_pdf_links(bulletins_page.text, self.settings.bulletins_url)
        if not pdf_links:
            if self._page_still_has_login_form(bulletins_page.text):
                raise AuthenticationError("Connexion refusee ou session expiree avant acces aux bulletins.")
            raise AuthenticationError(
                "Connexion possible, mais aucun PDF trouve sur la page des bulletins. Verifiez les droits du compte ou la structure du site."
            )

    def discover_bulletins(self) -> list[BulletinLink]:
        response = self._get(self.settings.bulletins_url)
        if self._page_still_has_login_form(response.text):
            raise AuthenticationError("La session n'est plus connectee au site membre.")

        raw_links = self._extract_pdf_links(response.text, self.settings.bulletins_url)
        dedup: dict[str, BulletinLink] = {}
        for raw_url, title in raw_links:
            initial_filename, number, year, month = parse_bulletin_metadata(raw_url, title)
            if is_index_bulletins_filename(initial_filename):
                continue
            (
                resolved_url,
                verified,
                validation_error,
                remote_content_length,
                remote_etag,
                remote_last_modified,
            ) = self._resolve_pdf_url(raw_url, title, number, year, month)

            final_filename, n2, y2, m2 = parse_bulletin_metadata(resolved_url, title or initial_filename)
            filename = final_filename if verified else initial_filename
            if is_index_bulletins_filename(filename):
                continue
            number = number if number is not None else n2
            year = year if year is not None else y2
            month = month if month is not None else m2
            clean_title = title.strip() or filename

            dedup[resolved_url] = BulletinLink(
                url=resolved_url,
                title=clean_title,
                filename=filename,
                number=number,
                year=year,
                month=month,
                original_url=raw_url,
                verified=verified,
                validation_error=validation_error,
                remote_content_length=remote_content_length,
                remote_etag=remote_etag,
                remote_last_modified=remote_last_modified,
            )

        return sorted(
            dedup.values(),
            key=lambda b: (
                b.number if b.number is not None else 999999,
                b.year if b.year is not None else 999999,
                b.filename,
            ),
        )

    def download_pdf(self, url: str, target_path: Path) -> tuple[str, int | None, str | None, str | None]:
        self._require_allowed_remote_url(url)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        with self.session.get(url, stream=True, timeout=self.settings.http_timeout_seconds, allow_redirects=True) as response:
            response.raise_for_status()
            self._require_allowed_remote_url(response.url)
            content_type = response.headers.get("Content-Type", "")
            announced = response.headers.get("Content-Length")
            if announced and announced.isdigit() and int(announced) > self.settings.max_pdf_bytes:
                raise CrawlError(f"PDF trop volumineux ({announced} octets).")

            tmp_path = target_path.with_suffix(target_path.suffix + ".tmp")
            sha = hashlib.sha256()
            size = 0
            first_chunk_checked = False
            with tmp_path.open("wb") as fh:
                try:
                    for chunk in response.iter_content(chunk_size=1024 * 512):
                        if not chunk:
                            continue
                        if not first_chunk_checked:
                            first_chunk_checked = True
                            if not self._looks_like_pdf(url, content_type, chunk):
                                raise CrawlError(f"La reponse distante n'est pas un PDF valide : {url}")
                        size += len(chunk)
                        if size > self.settings.max_pdf_bytes:
                            raise CrawlError(f"PDF trop volumineux (limite {self.settings.max_pdf_bytes} octets).")
                        fh.write(chunk)
                        sha.update(chunk)
                except Exception:
                    try:
                        tmp_path.unlink(missing_ok=True)
                    finally:
                        raise
            tmp_path.replace(target_path)

            etag = response.headers.get("ETag")
            last_modified = response.headers.get("Last-Modified")
            content_length = response.headers.get("Content-Length")
            length = int(content_length) if content_length and content_length.isdigit() else size
            return sha.hexdigest(), length, etag, last_modified

    def _resolve_pdf_url(
        self,
        raw_url: str,
        title: str,
        number: int | None,
        year: int | None,
        month: int | None,
    ) -> tuple[str, bool, str | None, int | None, str | None, str | None]:
        errors: list[str] = []
        for candidate in self._candidate_pdf_urls(raw_url, title, number, year, month):
            ok, final_url, error, metadata = self._probe_pdf_url(candidate)
            if ok:
                return (
                    final_url,
                    True,
                    None,
                    metadata.get("content_length"),
                    metadata.get("etag"),
                    metadata.get("last_modified"),
                )
            if error:
                errors.append(f"{candidate} -> {error}")
        return raw_url, False, "; ".join(errors[-4:]) or "aucune variante de fichier PDF valide trouvee", None, None, None

    def _candidate_pdf_urls(
        self,
        raw_url: str,
        title: str,
        number: int | None,
        year: int | None,
        month: int | None,
    ) -> list[str]:
        candidates: list[str] = []

        def add(url: str) -> None:
            absolute = urljoin(self.settings.bulletins_url, url)
            if self._allowed_remote_url(absolute) and absolute not in candidates:
                candidates.append(absolute)

        add(raw_url)

        parsed_base = urlparse(self.settings.bulletins_url)
        origin = f"{parsed_base.scheme}://{parsed_base.netloc}"
        raw_path = urlparse(urljoin(self.settings.bulletins_url, raw_url)).path
        raw_dir = raw_path.rsplit("/", 1)[0] + "/" if "/" in raw_path else "/"

        dirs = [
            urljoin(origin, "/wp/Bulletins/"),
            urljoin(origin, raw_dir),
            urljoin(origin, "/wp/bulletins/"),
            urljoin(origin, "/wp/wp-content/docs/bulletins/"),
        ]

        names = self._candidate_pdf_names(raw_url, title, number, year, month)
        for directory in dirs:
            for name in names:
                add(urljoin(directory, name))

        return candidates

    def _candidate_pdf_names(
        self,
        raw_url: str,
        title: str,
        number: int | None,
        year: int | None,
        month: int | None,
    ) -> list[str]:
        names: list[str] = []

        def add(name: str) -> None:
            if not name:
                return
            clean = name.strip()
            if not clean.lower().endswith(".pdf"):
                clean += ".pdf"
            if clean not in names:
                names.append(clean)

        raw_name = unquote(os.path.basename(urlparse(raw_url).path))
        add(raw_name)
        if title.lower().endswith(".pdf"):
            add(title)

        if number is not None and year is not None and month is not None:
            month_names = [MONTH_NAMES[month]]
            if month in ACCENTED_MONTH_NAMES:
                month_names.append(ACCENTED_MONTH_NAMES[month])

            for month_name in month_names:
                normalized_month = normalize_for_match(month_name).capitalize()
                for m in dict.fromkeys([month_name, normalized_month]):
                    add(f"{number:03d}-{m}-{year}.pdf")
                    add(f"{number:03d}_{m}-{year}.pdf")
                    add(f"{number}-{m}-{year}.pdf")
                    add(f"{number}_{m}-{year}.pdf")
                    add(f"{number}_{m}-{year}_Bulletin-{number}.pdf")
                    add(f"Bulletin-{number:03d}-{m}-{year}.pdf")
                    add(f"Bulletin_{number:03d}_{m}_{year}.pdf")

        return names

    def _probe_pdf_url(self, url: str) -> tuple[bool, str, str | None, dict[str, int | str | None]]:
        headers = {"Range": "bytes=0-15"}
        if not self._allowed_remote_url(url):
            return False, url, "domaine non autorisé", {}
        try:
            with self.session.get(
                url,
                headers=headers,
                stream=True,
                timeout=self.settings.http_timeout_seconds,
                allow_redirects=True,
            ) as response:
                if not self._allowed_remote_url(response.url):
                    return False, response.url, "redirection vers un domaine non autorisé", {}
                metadata = self._response_pdf_metadata(response)
                if response.status_code == 404:
                    return False, response.url, "404 introuvable", metadata
                if response.status_code in {401, 403}:
                    return False, response.url, f"HTTP {response.status_code} non autorise", metadata
                if response.status_code >= 400:
                    return False, response.url, f"HTTP {response.status_code}", metadata
                content_type = response.headers.get("Content-Type", "")
                first = b""
                for chunk in response.iter_content(chunk_size=16):
                    if chunk:
                        first = chunk
                        break
                if self._looks_like_pdf(response.url, content_type, first):
                    return True, response.url, None, metadata
                return False, response.url, f"reponse non PDF ({content_type or 'type inconnu'})", metadata
        except requests.RequestException as exc:
            return False, url, str(exc), {}

    @staticmethod
    def _response_pdf_metadata(response: requests.Response) -> dict[str, int | str | None]:
        content_length: int | None = None
        content_range = response.headers.get("Content-Range", "")
        match = re.search(r"/([0-9]+)\s*$", content_range)
        if match:
            content_length = int(match.group(1))
        else:
            raw_length = response.headers.get("Content-Length")
            if raw_length and raw_length.isdigit():
                content_length = int(raw_length)
        return {
            "content_length": content_length,
            "etag": response.headers.get("ETag"),
            "last_modified": response.headers.get("Last-Modified"),
        }

    @staticmethod
    def _looks_like_pdf(url: str, content_type: str, first_bytes: bytes) -> bool:
        if first_bytes.lstrip().startswith(b"%PDF-"):
            return True
        if "pdf" in content_type.lower():
            return True
        return False

    def _get(self, url: str, **kwargs) -> requests.Response:
        self._require_allowed_remote_url(url)
        response = self.session.get(url, timeout=self.settings.http_timeout_seconds, allow_redirects=True, **kwargs)
        response.raise_for_status()
        self._require_allowed_remote_url(response.url)
        return response

    def _post(self, url: str, **kwargs) -> requests.Response:
        self._require_allowed_remote_url(url)
        response = self.session.post(url, timeout=self.settings.http_timeout_seconds, allow_redirects=True, **kwargs)
        response.raise_for_status()
        self._require_allowed_remote_url(response.url)
        return response

    @staticmethod
    def _find_login_form(soup: BeautifulSoup):
        password_input = soup.find("input", {"type": "password"})
        if not password_input:
            return None
        return password_input.find_parent("form")

    @staticmethod
    def _build_login_payload(form, username: str, password: str) -> dict[str, str]:
        payload: dict[str, str] = {}
        inputs = form.find_all("input")
        for inp in inputs:
            name = inp.get("name")
            if not name:
                continue
            payload[name] = inp.get("value") or ""

        password_field = None
        username_field = None
        for inp in inputs:
            name = inp.get("name")
            if not name:
                continue
            input_type = (inp.get("type") or "text").lower()
            lname = name.lower()
            if input_type == "password" and password_field is None:
                password_field = name
            elif username_field is None and (
                lname in {"username", "user", "login", "email", "name"}
                or "user" in lname
                or "login" in lname
                or "mail" in lname
            ):
                username_field = name

        if not username_field:
            for inp in inputs:
                name = inp.get("name")
                input_type = (inp.get("type") or "text").lower()
                if name and input_type in {"text", "email"}:
                    username_field = name
                    break

        if not username_field or not password_field:
            raise AuthenticationError("Impossible d'identifier les champs login/mot de passe du formulaire.")

        payload[username_field] = username
        payload[password_field] = password
        return payload

    @staticmethod
    def _page_still_has_login_form(html: str) -> bool:
        soup = BeautifulSoup(html, "html.parser")
        return EntraideCrawler._find_login_form(soup) is not None

    @staticmethod
    def _extract_pdf_links(html: str, base_url: str) -> list[tuple[str, str]]:
        soup = BeautifulSoup(html, "html.parser")
        links: list[tuple[str, str]] = []
        seen: set[str] = set()

        def add(raw: str, label: str = "") -> None:
            raw = str(raw or "").strip()
            if not raw or ".pdf" not in raw.lower():
                return
            for match in PDF_URL_RE.findall(raw):
                absolute = urljoin(base_url, match.strip())
                if absolute in seen:
                    continue
                seen.add(absolute)
                text = " ".join(str(label or "").split())
                links.append((absolute, text))

        for a in soup.find_all("a"):
            text = " ".join(a.get_text(" ", strip=True).split())
            for attr in ["href", "data-href", "data-url", "data-file", "onclick"]:
                if a.has_attr(attr):
                    add(str(a.get(attr) or ""), text)

        for tag in soup.find_all(True):
            text = " ".join(tag.get_text(" ", strip=True).split()) if tag.name == "a" else ""
            for attr_value in tag.attrs.values():
                if isinstance(attr_value, list):
                    attr_value = " ".join(str(v) for v in attr_value)
                add(str(attr_value), text)

        # Dernier filet de securite : certains sites impriment les URLs PDF dans du JS ou du texte brut.
        add(html, "")
        return links

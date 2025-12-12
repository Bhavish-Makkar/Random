import requests
from bs4 import BeautifulSoup
import json
from datetime import datetime, timezone, timedelta
import time
import os
import re
import logging
 
# ===================== LOGGING CONFIG =====================
 
 
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
LOG_FILE = os.environ.get("PIPELINE_LOG_FILE", "weather_pipeline.log")
 
from token_store import get_access_token
 
from logging_config import get_email_logger
logger = get_email_logger()
 
# ===================== ENV LOADING =====================
 
def load_env(path: str = ".env") -> None:
    """Minimal .env loader (no external dependency)."""
    if not os.path.exists(path):
        logger.debug("No .env file found at %s, skipping env load.", path)
        return
 
    logger.debug("Loading environment variables from %s", path)
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
 
            if '=' in line:
                key, value = line.split('=', 1)
                key = key.strip()
                value = value.strip().strip('"\'')
                if key not in os.environ:
                    os.environ[key] = value
                    logger.debug("Loaded env var: %s", key)
 
# Load .env early
load_env()
 
ENV = os.environ.get("ENV", "").lower()
IS_LOCAL_ENV = (ENV == "local")
logger.info("ENV=%s | IS_LOCAL_ENV=%s", ENV, IS_LOCAL_ENV)
 
# ===================== CONFIG =====================
 
  # <--- or keep your hardcoded token
USER_EMAIL = os.environ.get("USER_EMAIL")      # mailbox you are operating on
 
 
if not USER_EMAIL:
    logger.critical("USER_EMAIL is not set. Please set it in .env or code.")
    raise RuntimeError("USER_EMAIL is not set. Please set it in .env or code.")
 
logger.info("Configured USER_EMAIL=%s", USER_EMAIL)
 
def build_headers():
    """Always use latest access token from token_store."""
    access_token = get_access_token()
    return {
        "Authorization": f"Bearer {access_token}",
        "Prefer": 'outlook.body-content-type="html"',
    }
 
def build_archive_headers():
    """Headers for JSON POST calls (move, reply, etc.)."""
    access_token = get_access_token()
    return {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }
 
GRAPH_BASE = "https://graph.microsoft.com/v1.0"
 
OUTPUT_DIR = "email_extracts"
 
# Only create directory upfront if ENV=local (global mode won't save files)
if IS_LOCAL_ENV and not os.path.exists(OUTPUT_DIR):
    os.makedirs(OUTPUT_DIR)
    logger.info("Created output directory: %s", OUTPUT_DIR)
 
IST_OFFSET = timezone(timedelta(hours=5, minutes=30))
 
MONTH_MAP = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4,
    "may": 5, "jun": 6, "jul": 7, "aug": 8,
    "sep": 9, "oct": 10, "nov": 11, "dec": 12
}
 
# Canonical required fields (used for error reporting + checks)
REQUIRED_FIELDS = {
    "station",
    "weatherPhenomenon",
    "operationProbability",
    "advisoryTimePeriodStartUTC",
    "advisoryTimePeriodEndUTC",
}
 
# ===================== UTILS =====================
 
def sanitize_filename(filename: str) -> str:
    safe_name = re.sub(r'[<>:"/\\|?*]', '_', filename)
    logger.debug("Sanitized filename '%s' -> '%s'", filename, safe_name)
    return safe_name
 
def convert_to_ist_format(utc_datetime_str: str) -> str:
    try:
        utc_dt = datetime.fromisoformat(utc_datetime_str.replace('Z', '+00:00'))
        ist_dt = utc_dt.astimezone(IST_OFFSET)
        formatted = ist_dt.strftime("%Y-%m-%dT%H:%M:%SZ+05:30")
        logger.debug("Converted UTC '%s' -> IST formatted '%s'", utc_datetime_str, formatted)
        return formatted
    except Exception as e:
        logger.warning("Failed to convert '%s' to IST, using now. Error: %s", utc_datetime_str, e)
        ist_dt = datetime.now(IST_OFFSET)
        return ist_dt.strftime("%Y-%m-%dT%H:%M:%SZ+05:30")
 
def parse_mail_received_datetime(dt_str: str):
    if not dt_str:
        logger.debug("parse_mail_received_datetime called with empty string.")
        return None
    try:
        dt = datetime.fromisoformat(dt_str.replace('Z', '+00:00')).astimezone(timezone.utc)
        logger.debug("Parsed mail received datetime '%s' -> %s", dt_str, dt)
        return dt
    except Exception as e:
        logger.warning("Failed to parse mail received datetime '%s': %s", dt_str, e)
        return None
 
def build_utc_from_dd_mon_hhmm(match_obj, mail_dt_utc):
    try:
        if not match_obj:
            logger.debug("build_utc_from_dd_mon_hhmm called with None match_obj.")
            return None
 
        hhmm = match_obj.group(1)   # 1500
        day = int(match_obj.group(2))  # 23
        mon_abbr = match_obj.group(3).lower()  # nov
 
        if len(hhmm) == 4:
            hour = int(hhmm[:2])
            minute = int(hhmm[2:])
        elif len(hhmm) == 3:
            hour = int(hhmm[:1])
            minute = int(hhmm[1:])
        else:
            logger.warning("Unexpected hhmm format: '%s'", hhmm)
            return None
 
        month = MONTH_MAP.get(mon_abbr)
        if not month:
            logger.warning("Unknown month abbreviation: '%s'", mon_abbr)
            return None
 
        if mail_dt_utc is None:
            year = datetime.now(timezone.utc).year
        else:
            year = mail_dt_utc.year
            if mail_dt_utc.month == 12 and month == 1:
                year += 1
 
        dt_utc = datetime(year, month, day, hour, minute, 0, tzinfo=timezone.utc)
        logger.debug(
            "Built UTC datetime from '%s %d %s' with mail_dt=%s -> %s",
            hhmm, day, mon_abbr, mail_dt_utc, dt_utc
        )
        return dt_utc
    except Exception as e:
        logger.error("Error in build_utc_from_dd_mon_hhmm: %s", e)
        return None
 
def parse_advisory_times(window_lines, mail_received_dt_str):
    """
    Extract raw Start UTC and raw End UTC from table.
    Column mapping in text:
      1) Start UTC
      2) Start LT
      3) End UTC
      4) End LT
    """
    pattern = re.compile(r'(\d{3,4}/\d{1,2}\s*[A-Za-z]{3})')
    matches = []
 
    for line in window_lines:
        for m in pattern.finditer(line):
            matches.append(m.group(1).strip())
 
    logger.debug("parse_advisory_times found matches: %s", matches)
 
    # We need at least 3 matches (index 0 = start UTC, index 2 = end UTC)
    if len(matches) < 3:
        logger.warning("Insufficient advisory time matches (found %d, need >=3).", len(matches))
        return None
 
    start_raw = matches[0]    # Start UTC
    end_raw = matches[2]      # End UTC (correct column)
 
    logger.debug("Advisory times parsed: start_raw='%s', end_raw='%s'", start_raw, end_raw)
    return start_raw, end_raw
 
# ===================== FIELD LABEL CHECK =====================
 
def check_mandatory_fields_in_html(html_content: str):
    """
    Returns list of missing required field labels (by name from REQUIRED_FIELDS).
    """
    required_keys = REQUIRED_FIELDS
 
    if not html_content or not html_content.strip():
        logger.warning("HTML content empty while checking mandatory fields.")
        return list(required_keys)
 
    html_lower = html_content.lower()
    simple = re.sub(r'[^a-z0-9]', '', html_lower)
 
    present = set()
 
    if 'station' in html_lower or 'station' in simple:
        present.add("station")
 
    cond_weather = (
        ('weather' in html_lower and ('phenomenon' in html_lower or 'phenom' in html_lower))
        or 'weatherphenomenon' in simple
        or 'weatherphenom' in simple
    )
    if cond_weather:
        present.add("weatherPhenomenon")
 
    cond_op_prob = (
        (('operation' in html_lower or 'operational' in html_lower)
         and ('probability' in html_lower or 'probab' in html_lower))
        or 'operationprobability' in simple
        or 'operationalprobability' in simple
        or 'operationprobab' in simple
    )
    if cond_op_prob:
        present.add("operationProbability")
 
    cond_start_utc = (
        ('advisory' in html_lower and 'start' in html_lower and 'utc' in html_lower)
        or 'advisorytimeperiodstartutc' in simple
        or 'timeperiodstartutc' in simple
        or 'periodstartutc' in simple
    )
    if cond_start_utc:
        present.add("advisoryTimePeriodStartUTC")
 
    cond_end_utc = (
        ('advisory' in html_lower and 'end' in html_lower and 'utc' in html_lower)
        or 'advisorytimeperiodendutc' in simple
        or 'timeperiodendutc' in simple
        or 'periodendutc' in simple
    )
    if cond_end_utc:
        present.add("advisoryTimePeriodEndUTC")
 
    missing = [k for k in required_keys if k not in present]
    if missing:
        logger.info("Mandatory fields missing in HTML: %s", missing)
    else:
        logger.debug("All mandatory fields present in HTML.")
 
    return missing
 
# ===================== NLP-STYLE EXTRACTION =====================
 
def extract_weather_stations_nlp(html_content: str, mail_received_dt: str = None):
    logger.debug("Starting NLP extraction of weather stations.")
    soup = BeautifulSoup(html_content, "html.parser")
    text = soup.get_text("\n", strip=True)
    lines = [l.strip() for l in text.splitlines() if l.strip()]
 
    stations = []
    n = len(lines)
    i = 0
 
    logger.debug("Total lines extracted from HTML: %d", n)
 
    while i < n:
        line = lines[i]
 
        # Station code = exactly 3 uppercase letters
        if re.fullmatch(r"[A-Z]{3}", line):
            station_code = line
            logger.debug("Found potential station code at line %d: %s", i, station_code)
            entry = {"station": station_code}
 
            window = lines[i + 1: i + 15]
 
            # ---------- operationProbability (FIXED) ----------
            prob_val = None
 
            for w in window:
                m = re.search(r"(\d{1,3})\s*%", w)
                if m:
                    val = int(m.group(1))
                    if 0 <= val <= 100:
                        prob_val = val
                        logger.debug("Found operationProbability=%d for station=%s", prob_val, station_code)
                        break
 
            if prob_val is not None:
                entry["operationProbability"] = prob_val
 
            # ---------- weatherPhenomenon ----------
            for w in window:
                if re.fullmatch(r"[A-Z]{2,6}", w) and w != station_code:
                    entry["weatherPhenomenon"] = w
                    logger.debug("Found weatherPhenomenon=%s for station=%s", w, station_code)
                    break
 
            # ---------- advisory times (UTC only) ----------
            time_result = parse_advisory_times(window, mail_received_dt)
 
            if time_result:
                start_utc_str, end_utc_str = time_result
                start_utc_formatted = build_utc_from_dd_mon_hhmm(
                    re.match(r'(\d{3,4})/(\d{1,2})\s*([A-Za-z]{3})', start_utc_str),
                    parse_mail_received_datetime(mail_received_dt)
                )
                end_utc_formatted = build_utc_from_dd_mon_hhmm(
                    re.match(r'(\d{3,4})/(\d{1,2})\s*([A-Za-z]{3})', end_utc_str),
                    parse_mail_received_datetime(mail_received_dt)
                )
                entry["advisoryTimePeriodStartUTC"] = (
                    start_utc_formatted.strftime("%Y-%m-%dT%H:%M:%S")
                    if start_utc_formatted else start_utc_str
                )
                entry["advisoryTimePeriodEndUTC"] = (
                    end_utc_formatted.strftime("%Y-%m-%dT%H:%M:%S")
                    if end_utc_formatted else end_utc_str
                )
                logger.debug(
                    "Station=%s advisory times: start=%s end=%s",
                    station_code,
                    entry["advisoryTimePeriodStartUTC"],
                    entry["advisoryTimePeriodEndUTC"],
                )
 
            # Mandatory 5 fields only
            mandatory = [
                "station",
                "weatherPhenomenon",
                "operationProbability",
                "advisoryTimePeriodStartUTC",
                "advisoryTimePeriodEndUTC",
            ]
            if all(k in entry for k in mandatory):
                stations.append(entry)
                logger.info(
                    "Completed station entry: %s", entry
                )
            else:
                logger.info(
                    "Incomplete station entry for '%s', missing fields, ignoring: %s",
                    station_code,
                    [k for k in mandatory if k not in entry],
                )
 
        i += 1
 
    logger.info("NLP extraction complete. Total valid stations: %d", len(stations))
    return stations
 
# ===================== GRAPH API EMAIL FUNCTIONS =====================
 
def get_all_messages(page_size: int = 50, max_pages: int = None):
    url = (
        f"{GRAPH_BASE}/users/{USER_EMAIL}/mailFolders/Inbox/messages"
        f"?$top={page_size}"
        "&$orderby=receivedDateTime desc"
        "&$select=id,subject,receivedDateTime,from"
    )
 
    all_messages = []
    page_count = 0
 
    logger.info("Starting fetch of messages from Inbox with page_size=%d", page_size)
 
    while url and (max_pages is None or page_count < max_pages):
        logger.info("Fetching page %d...", page_count + 1)
        resp = requests.get(url, headers=build_headers())
 
        if resp.status_code != 200:
            logger.error("Error fetching messages: %s", resp.status_code)
            logger.error("Response: %s", resp.text)
            break
 
        data = resp.json()
        messages = data.get("value", [])
        all_messages.extend(messages)
 
        logger.info(
            "Retrieved %d messages from page %d",
            len(messages),
            page_count + 1
        )
 
        url = data.get("@odata.nextLink")
        page_count += 1
        time.sleep(0.5)
 
    logger.info("Total messages retrieved: %d", len(all_messages))
    return all_messages
 
def get_message_body_html(message_id: str) -> str:
    url = (
        f"{GRAPH_BASE}/users/{USER_EMAIL}/messages/{message_id}"
        "?$select=subject,body"
    )
 
    logger.debug("Fetching message body for message_id=%s", message_id)
    resp = requests.get(url, headers=build_headers())
    if resp.status_code != 200:
        logger.error(
            "Error fetching message body for %s: %s | Response: %s",
            message_id,
            resp.status_code,
            resp.text,
        )
        return ""
 
    data = resp.json()
    body = data.get("body", {})
    return body.get("content", "")
 
# ===================== SEND ERROR EMAIL TO SENDER (NOW AS REPLY) =====================
 
def send_advisory_error_email(message, missing_fields, invalid_fields, extra_reason: str | None = None):
    """
    Reply back to the SAME wrong email (not a new email).
    Uses:
      POST /users/{USER_EMAIL}/messages/{message_id}/reply
    """
    try:
        from_obj = message.get("from") or {}
        email_addr_obj = from_obj.get("emailAddress") or {}
        sender_address = email_addr_obj.get("address")
        message_id = message.get("id")
 
        if not message_id:
            logger.error("Cannot send reply: message id missing in message object.")
            return
 
        original_subject = message.get("subject") or "your weather advisory email"
        logger.info(
            "Sending advisory error email as reply for message_id=%s subject='%s'",
            message_id,
            original_subject,
        )
 
        lines: list[str] = []
        lines.append("Dear Sender,")
        lines.append("")
        lines.append("We attempted to process your recent weather advisory email,")
        lines.append("but could not extract the required JSON payload due to the following issue(s):")
        lines.append("")
 
        if missing_fields:
            lines.append("Missing parameter(s):")
            for f in missing_fields:
                lines.append(f"  - " + f)
            lines.append("")
 
        if invalid_fields:
            lines.append("Invalid / improperly formatted parameter(s):")
            for f in invalid_fields:
                lines.append(f"  - " + f)
            lines.append("")
 
        if extra_reason:
            lines.append("Additional details:")
            lines.append(f"  - {extra_reason}")
            lines.append("")
 
        lines.append("Required parameters are:")
        for f in REQUIRED_FIELDS:
            lines.append(f"  - {f}")
        lines.append("")
        lines.append("Please ensure all required parameters are present and in the correct format,")
        lines.append("then resend the advisory email so that it can be processed and forwarded to Event Hub.")
        lines.append("")
        lines.append("This is an automated notification. No reply is necessary.")
 
        body_text = "\n".join(lines)
 
        url = f"{GRAPH_BASE}/users/{USER_EMAIL}/messages/{message_id}/reply"
        payload = {
            "comment": body_text
        }
 
        resp = requests.post(url, headers=build_archive_headers(), json=payload)
        if resp.status_code == 202:
            if sender_address:
                logger.info(
                    "Replied with parameter error notification to %s for message_id=%s",
                    sender_address,
                    message_id,
                )
            else:
                logger.info(
                    "Replied with parameter error notification to original message (sender address not resolved). message_id=%s",
                    message_id,
                )
        else:
            logger.error(
                "Failed to send parameter error reply. Status=%s Response=%s",
                resp.status_code,
                resp.text,
            )
    except Exception as e:
        logger.exception("Exception while sending error reply: %s", e)
 
# ===================== ARCHIVE HELPERS =====================
 
def get_archive_folder_id() -> str | None:
    """
    Fetch the Archive folder and return its id for USER_EMAIL.
    Uses the well-known 'Archive' folder name.
    """
    url = f"{GRAPH_BASE}/users/{USER_EMAIL}/mailFolders/Archive"
    logger.debug("Fetching Archive folder id for user %s", USER_EMAIL)
    resp = requests.get(url, headers=build_archive_headers())
 
    if resp.status_code == 200:
        data = resp.json()
        folder_id = data.get("id")
        if folder_id:
            logger.debug("Archive folder id=%s", folder_id)
            return folder_id
        else:
            logger.error("Archive folder found but no id field present.")
            return None
    else:
        logger.error(
            "Failed to get Archive folder. Status=%s Response=%s",
            resp.status_code,
            resp.text,
        )
        return None
 
def move_message_to_archive(message_id: str) -> bool:
    """
    Move the given message to the Archive folder.
    Returns True if moved successfully, False otherwise.
    """
    logger.info("Attempting to move message_id=%s to Archive.", message_id)
    archive_id = get_archive_folder_id()
    if not archive_id:
        logger.error("Could not resolve Archive folder id. Skipping archive move.")
        return False
 
    url = f"{GRAPH_BASE}/users/{USER_EMAIL}/messages/{message_id}/move"
    body = {"destinationId": archive_id}
 
    resp = requests.post(url, headers=build_archive_headers(), json=body)
 
    if resp.status_code == 201:  # Created = moved successfully
        moved_msg = resp.json()
        logger.info(
            "Message moved to Archive. New folder id=%s New message id=%s",
            moved_msg.get("parentFolderId"),
            moved_msg.get("id"),
        )
        return True
    else:
        logger.error(
            "Failed to move message to Archive. Status=%s Response=%s",
            resp.status_code,
            resp.text,
        )
        return False
 
# ===================== MAIN PROCESSING =====================
 
def process_single_email(message):
    try:
        logger.info("Processing single email id=%s subject='%s'",
                    message.get("id"), (message.get("subject") or "")[:80])
        body_html = get_message_body_html(message["id"])
        if not body_html:
            logger.warning("No HTML body found – Skipping this email (id=%s).", message.get("id"))
            try:
                send_advisory_error_email(
                    message,
                    missing_fields=list(REQUIRED_FIELDS),
                    invalid_fields=[],
                    extra_reason="Email body did not contain any HTML content or could not be read."
                )
            except Exception as notify_err:
                logger.exception("Failed to send parameter error email: %s", notify_err)
 
            try:
                moved = move_message_to_archive(message["id"])
                if not moved:
                    logger.error("Could not move this message to Archive after error email.")
            except Exception as arch_err:
                logger.exception("Exception while moving to Archive after error email: %s", arch_err)
 
            return None
 
        # 1) Check mandatory field labels
        missing_fields = check_mandatory_fields_in_html(body_html)
        if missing_fields:
            logger.info(
                "Missing mandatory field(s) in mail body for id=%s: %s – Skipping this email.",
                message.get("id"),
                ", ".join(missing_fields),
            )
            try:
                send_advisory_error_email(
                    message,
                    missing_fields=missing_fields,
                    invalid_fields=[],
                    extra_reason=None
                )
            except Exception as notify_err:
                logger.exception("Failed to send parameter error email: %s", notify_err)
 
            try:
                moved = move_message_to_archive(message["id"])
                if not moved:
                    logger.error("Could not move this message to Archive after error email.")
            except Exception as arch_err:
                logger.exception("Exception while moving to Archive after error email: %s", arch_err)
 
            return None
 
        logger.info("All 5 mandatory field labels found in body – running NLP extractor...")
 
        stations = extract_weather_stations_nlp(
            body_html,
            mail_received_dt=message.get("receivedDateTime", "")
        )
 
        if not stations:
            logger.info(
                "NLP extractor could not find any complete stations – Skipping this email id=%s.",
                message.get("id"),
            )
            try:
                send_advisory_error_email(
                    message,
                    missing_fields=[],
                    invalid_fields=list(REQUIRED_FIELDS),
                    extra_reason="Field labels are present, but values are missing or not in the expected format."
                )
            except Exception as notify_err:
                logger.exception("Failed to send parameter error email: %s", notify_err)
 
            try:
                moved = move_message_to_archive(message["id"])
                if not moved:
                    logger.error("Could not move this message to Archive after error email.")
            except Exception as arch_err:
                logger.exception("Exception while moving to Archive after error email: %s", arch_err)
 
            return None
 
        weather_advisory = {
            "createdAt": convert_to_ist_format(message.get("receivedDateTime", "")),
            "stations": stations
        }
        logger.info(
            "Successfully built weather_advisory for message_id=%s with %d station(s).",
            message.get("id"),
            len(stations),
        )
        return weather_advisory
 
    except Exception as e:
        logger.exception("Error processing email id=%s: %s", message.get("id"), e)
        try:
            send_advisory_error_email(
                message,
                missing_fields=[],
                invalid_fields=[],
                extra_reason=f"Internal processing error: {e}"
            )
        except Exception as notify_err:
            logger.exception("Failed to send parameter error email: %s", notify_err)
 
        try:
            moved = move_message_to_archive(message["id"])
            if not moved:
                logger.error("Could not move this message to Archive after error email.")
        except Exception as arch_err:
            logger.exception("Exception while moving to Archive after error email: %s", arch_err)
 
        return None
 
def process_all_emails(save_files: bool | None = None):
    """
    When imported by send_events.py:
      - Typically you won't call this; you'll use process_single_email.
    When run directly (python info_table.py):
      - save_files=True  -> JSON files created in OUTPUT_DIR
      - save_files=False -> no files created, just extraction + logs
 
    If save_files is None, we default to ENV:
      - ENV=local  -> save_files=True
      - ENV=global -> save_files=False
    """
    if save_files is None:
        save_files = IS_LOCAL_ENV
 
    logger.info("=" * 60)
    logger.info("  WEATHER ADVISORY EMAIL PROCESSOR – NLP VERSION")
    logger.info("=" * 60)
    logger.info("ENV = %s | save_files = %s", ENV, save_files)
    logger.info("Uses label detection + NLP-style window parsing around station codes.")
    if save_files:
        logger.info("JSON files WILL be created in %s/", OUTPUT_DIR)
    else:
        logger.info("JSON will NOT be saved, only extracted in memory.")
 
    all_messages = get_all_messages(page_size=50)
    successful_extractions = 0
    skipped_emails = 0
 
    for idx, message in enumerate(all_messages):
        subject = message.get('subject', 'No Subject')[:80]
        logger.info(
            "Processing email %d/%d: %s",
            idx + 1,
            len(all_messages),
            subject,
        )
 
        weather_advisory = process_single_email(message)
 
        if weather_advisory:
            if save_files:
                if not os.path.exists(OUTPUT_DIR):
                    os.makedirs(OUTPUT_DIR, exist_ok=True)
                    logger.info("Created output directory during processing: %s", OUTPUT_DIR)
 
                subject_clean = sanitize_filename(message.get("subject", "No_Subject")[:30])
                date_clean = message.get("receivedDateTime", "")[:10].replace("-", "_")
                filename = f"{idx + 1:03d}_{date_clean}_{subject_clean}.json"
                filepath = os.path.join(OUTPUT_DIR, filename)
 
                with open(filepath, "w", encoding="utf-8") as f:
                    json.dump(weather_advisory, f, indent=2, ensure_ascii=False)
 
                station_count = len(weather_advisory["stations"])
                logger.info(
                    "Extracted %d station(s) – Saved to %s",
                    station_count,
                    filename,
                )
            else:
                station_count = len(weather_advisory["stations"])
                logger.info(
                    "Extracted %d station(s) – (not saving to disk, save_files=False)",
                    station_count,
                )
 
            successful_extractions += 1
        else:
            skipped_emails += 1
 
        time.sleep(0.2)
 
    logger.info("=" * 60)
    logger.info(" EMAIL PROCESSING SUMMARY")
    logger.info("=" * 60)
    logger.info(" Total emails processed: %d", len(all_messages))
    logger.info(" Successful extractions: %d", successful_extractions)
    logger.info(" Skipped emails: %d", skipped_emails)
    if save_files:
        logger.info(" Files saved in: %s/", OUTPUT_DIR)
    else:
        logger.info(" No files saved (save_files=False).")
 
    return len(all_messages), successful_extractions
 
def main():
    try:
        save_files = IS_LOCAL_ENV
        process_all_emails(save_files=save_files)
    except requests.HTTPError as e:
        logger.exception("HTTP Error: %s", e)
    except Exception as e:
        logger.exception("Error: %s", e)
 
if __name__ == "__main__":
    main()

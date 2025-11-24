import requests
from bs4 import BeautifulSoup
import json
from datetime import datetime, timezone, timedelta
import time
import os
import re
 
# ===================== ENV LOADING =====================
 
def load_env(path: str = ".env") -> None:
    """Minimal .env loader (no external dependency)."""
    if not os.path.exists(path):
        return
 
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
 
# Load .env early
load_env()
 
ENV = os.environ.get("ENV", "").lower()
IS_LOCAL_ENV = (ENV == "local")
 
# ===================== CONFIG =====================
 
# NOTE: better to read from env, but keeping your current hardcoded token for now

ACCESS_TOKEN=
USER_EMAIL=
if not ACCESS_TOKEN:
    raise RuntimeError("ACCESS_TOKEN is not set. Please set it in .env or code.")
if not USER_EMAIL:
    raise RuntimeError("USER_EMAIL is not set. Please set it in .env or code.")
 
# For normal Graph GETs (body, messages etc.)
headers = {
    "Authorization": f"Bearer {ACCESS_TOKEN}",
    "Prefer": 'outlook.body-content-type="html"'
}
 
# Base URL for Microsoft Graph
GRAPH_BASE = "https://graph.microsoft.com/v1.0"
 
# Separate headers for JSON POST calls (like move → Archive)
archive_headers = {
    "Authorization": f"Bearer {ACCESS_TOKEN}",
    "Content-Type": "application/json",
}
 
OUTPUT_DIR = "email_extracts"
 
# Only create directory upfront if ENV=local (global mode won't save files)
if IS_LOCAL_ENV and not os.path.exists(OUTPUT_DIR):
    os.makedirs(OUTPUT_DIR)
 
IST_OFFSET = timezone(timedelta(hours=5, minutes=30))
 
MONTH_MAP = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4,
    "may": 5, "jun": 6, "jul": 7, "aug": 8,
    "sep": 9, "oct": 10, "nov": 11, "dec": 12
}
 
# ===================== UTILS =====================
 
def sanitize_filename(filename: str) -> str:
    return re.sub(r'[<>:"/\\|?*]', '_', filename)
 
def convert_to_ist_format(utc_datetime_str: str) -> str:
    """
    Keep as-is (tumhari existing createdAt formatting).
    """
    try:
        utc_dt = datetime.fromisoformat(utc_datetime_str.replace('Z', '+00:00'))
        ist_dt = utc_dt.astimezone(IST_OFFSET)
        return ist_dt.strftime("%Y-%m-%dT%H:%M:%SZ+05:30")
    except Exception:
        ist_dt = datetime.now(IST_OFFSET)
        return ist_dt.strftime("%Y-%m-%dT%H:%M:%SZ+05:30")
 
def parse_mail_received_datetime(dt_str: str):
    """
    Mail ke receivedDateTime ko datetime object me convert karo (UTC aware).
    """
    if not dt_str:
        return None
    try:
        # Graph format: 2025-11-22T13:45:10Z
        return datetime.fromisoformat(dt_str.replace('Z', '+00:00')).astimezone(timezone.utc)
    except Exception:
        return None
 
def build_utc_from_dd_mon_hhmm(match_obj, mail_dt_utc):
    """
    '1500/23 Nov' jaisi string se proper UTC datetime banao.
    Year agar missing hai to mail ke year se lo.
    """
    try:
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
            return None
 
        month = MONTH_MAP.get(mon_abbr)
        if not month:
            return None
 
        # 1) Default year = mail receive year
        if mail_dt_utc is None:
            year = datetime.now(timezone.utc).year
        else:
            year = mail_dt_utc.year
 
            # Dec mail, Jan advisory -> next year
            if mail_dt_utc.month == 12 and month == 1:
                year += 1
 
        dt_utc = datetime(year, month, day, hour, minute, 0, tzinfo=timezone.utc)
        return dt_utc
    except Exception:
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
 
    # We need at least 3 matches (index 0 = start UTC, index 2 = end UTC)
    if len(matches) < 3:
        return None
 
    start_raw = matches[0]    # Start UTC
    end_raw = matches[2]      # End UTC (correct column)
 
    return start_raw, end_raw
 
 
# ===================== FIELD LABEL CHECK =====================
 
def check_mandatory_fields_in_html(html_content: str):
    required_keys = {
        "station",
        "weatherPhenomenon",
        "operationProbability",
        "advisoryTimePeriodStartUTC",
        "advisoryTimePeriodEndUTC",
    }
 
    if not html_content or not html_content.strip():
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
    return missing
 
# ===================== NLP-STYLE EXTRACTION =====================
 
def extract_weather_stations_nlp(html_content: str, mail_received_dt: str = None):
    soup = BeautifulSoup(html_content, "html.parser")
    text = soup.get_text("\n", strip=True)
    lines = [l.strip() for l in text.splitlines() if l.strip()]
 
    stations = []
    n = len(lines)
    i = 0
 
    while i < n:
        line = lines[i]
 
        # Station code = exactly 3 uppercase letters
        if re.fullmatch(r"[A-Z]{3}", line):
            station_code = line
            entry = {"station": station_code}
 
            window = lines[i + 1: i + 15]
 
            # ---------- operationProbability (FIXED) ----------
            prob_val = None
 
            # 1) Prefer numbers that are directly associated with a % sign,
            #    e.g. "30%", " 75 %", etc.
            for w in window:
                m = re.search(r"(\d{1,3})\s*%", w)
                if m:
                    val = int(m.group(1))
                    if 0 <= val <= 100:
                        prob_val = val
                        break
 
 
 
 
            if prob_val is not None:
                # store as integer, % sign is ignored
                entry["operationProbability"] = prob_val
 
            # ---------- weatherPhenomenon ----------
            for w in window:
                if re.fullmatch(r"[A-Z]{2,6}", w) and w != station_code:
                    entry["weatherPhenomenon"] = w
                    break
 
            # ---------- advisory times (UTC only) ----------
            time_result = parse_advisory_times(window, mail_received_dt)
            if time_result:
                start_utc_str, end_utc_str = time_result
                entry["advisoryTimePeriodStartUTC"] = start_utc_str
                entry["advisoryTimePeriodEndUTC"] = end_utc_str
 
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
 
        i += 1
 
    return stations
 
# ===================== GRAPH API EMAIL FUNCTIONS =====================
 
def get_all_messages(page_size: int = 50, max_pages: int = None):
    url = (
        f"{GRAPH_BASE}/users/{USER_EMAIL}/messages"
        f"?$top={page_size}"
        "&$orderby=receivedDateTime desc"
        "&$select=id,subject,receivedDateTime,from"
    )
 
    all_messages = []
    page_count = 0
 
    while url and (max_pages is None or page_count < max_pages):
        print(f"Fetching page {page_count + 1}...")
        resp = requests.get(url, headers=headers)
 
        if resp.status_code != 200:
            print(f"Error fetching messages: {resp.status_code}")
            print("Response:", resp.text)
            break
 
        data = resp.json()
        messages = data.get("value", [])
        all_messages.extend(messages)
 
        print(f"Retrieved {len(messages)} messages from page {page_count + 1}")
 
        url = data.get("@odata.nextLink")
        page_count += 1
        time.sleep(0.5)
 
    print(f"Total messages retrieved: {len(all_messages)}")
    return all_messages
 
def get_message_body_html(message_id: str) -> str:
    url = (
        f"{GRAPH_BASE}/users/{USER_EMAIL}/messages/{message_id}"
        "?$select=subject,body"
    )
 
    resp = requests.get(url, headers=headers)
    if resp.status_code != 200:
        print(f"Error fetching message body for {message_id}: {resp.status_code}")
        print("Response:", resp.text)
        return ""
 
    data = resp.json()
    body = data.get("body", {})
    return body.get("content", "")
 
# ===================== ARCHIVE HELPERS =====================
 
def get_archive_folder_id() -> str | None:
    """
    Fetch the Archive folder and return its id for USER_EMAIL.
    Uses the well-known 'Archive' folder name.
    """
    url = f"{GRAPH_BASE}/users/{USER_EMAIL}/mailFolders/Archive"
    resp = requests.get(url, headers=archive_headers)
 
    if resp.status_code == 200:
        data = resp.json()
        folder_id = data.get("id")
        if folder_id:
            return folder_id
        else:
            print("   ⚠️ Archive folder found but no id field.")
            return None
    else:
        print("   ⚠️ Failed to get Archive folder.")
        print("      Status:", resp.status_code)
        print("      Response:", resp.text)
        return None
 
def move_message_to_archive(message_id: str) -> bool:
    """
    Move the given message to the Archive folder.
    Returns True if moved successfully, False otherwise.
    """
    archive_id = get_archive_folder_id()
    if not archive_id:
        print("   ⚠️ Could not resolve Archive folder id. Skipping archive move.")
        return False
 
    url = f"{GRAPH_BASE}/users/{USER_EMAIL}/messages/{message_id}/move"
    body = {"destinationId": archive_id}
 
    resp = requests.post(url, headers=archive_headers, json=body)
 
    if resp.status_code == 201:  # Created = moved successfully
        moved_msg = resp.json()
        print("   📁 Message moved to Archive.")
        print("      New folder id:", moved_msg.get("parentFolderId"))
        print("      New message id:", moved_msg.get("id"))
        return True
    else:
        print("   ⚠️ Failed to move message to Archive.")
        print("      Status:", resp.status_code)
        print("      Response:", resp.text)
        return False
 
# ===================== MAIN PROCESSING =====================
 
def process_single_email(message):
    try:
        body_html = get_message_body_html(message["id"])
        if not body_html:
            print("   ❌ No HTML body found – Skipping this email.")
            return None
 
        # 1) Check mandatory field labels
        missing_fields = check_mandatory_fields_in_html(body_html)
        if missing_fields:
            print(f"   ❌ Missing mandatory field(s) in mail body: {', '.join(missing_fields)} – Skipping this email.")
            return None
 
        print("   ✅ All 5 mandatory field labels found in body – running NLP extractor...")
 
        stations = extract_weather_stations_nlp(
            body_html,
            mail_received_dt=message.get("receivedDateTime", "")
        )
 
        if not stations:
            print("   ❌ NLP extractor could not find any complete stations – Skipping this email.")
            return None
 
        weather_advisory = {
            "createdAt": convert_to_ist_format(message.get("receivedDateTime", "")),
            "stations": stations
        }
        return weather_advisory
 
    except Exception as e:
        print(f"   ❌ Error processing email: {e}")
        return None
 
def process_all_emails(save_files: bool | None = None):
    """
    When imported by send_events.py:
      - Typically you won't call this; you'll use process_single_email.
    When run directly (python test2.py):
      - save_files=True  -> JSON files created in OUTPUT_DIR
      - save_files=False -> no files created, just extraction + logs
 
    If save_files is None, we default to ENV:
      - ENV=local  -> save_files=True
      - ENV=global -> save_files=False
    """
    if save_files is None:
        save_files = IS_LOCAL_ENV
 
    print("=" * 60)
    print("🌤️  WEATHER ADVISORY EMAIL PROCESSOR – NLP VERSION")
    print("=" * 60)
    print(f"ENV = {ENV} | save_files = {save_files}")
    print("🔍 Uses label detection + NLP-style window parsing around station codes.")
    if save_files:
        print("💾 JSON files WILL be created in email_extracts/")
    else:
        print("📡 JSON will NOT be saved, only extracted in memory.\n")
 
    all_messages = get_all_messages(page_size=50)
    successful_extractions = 0
    skipped_emails = 0
 
    for idx, message in enumerate(all_messages):
        subject = message.get('subject', 'No Subject')[:80]
        print(f"\nProcessing email {idx + 1}/{len(all_messages)}: {subject}...")
 
        weather_advisory = process_single_email(message)
 
        if weather_advisory:
            if save_files:
                # Ensure directory exists if we are saving
                if not os.path.exists(OUTPUT_DIR):
                    os.makedirs(OUTPUT_DIR, exist_ok=True)
 
                subject_clean = sanitize_filename(message.get("subject", "No_Subject")[:30])
                date_clean = message.get("receivedDateTime", "")[:10].replace("-", "_")
                filename = f"{idx + 1:03d}_{date_clean}_{subject_clean}.json"
                filepath = os.path.join(OUTPUT_DIR, filename)
 
                with open(filepath, "w", encoding="utf-8") as f:
                    json.dump(weather_advisory, f, indent=2, ensure_ascii=False)
 
                station_count = len(weather_advisory["stations"])
                print(f"   ✅ Extracted {station_count} station(s) – Saved to {filename}")
            else:
                station_count = len(weather_advisory["stations"])
                print(f"   ✅ Extracted {station_count} station(s) – (not saving to disk, save_files=False)")
 
            successful_extractions += 1
        else:
            skipped_emails += 1
 
        time.sleep(0.2)
 
    print("\n" + "=" * 60)
    print("🎯 EMAIL PROCESSING SUMMARY")
    print("=" * 60)
    print(f"📧 Total emails processed: {len(all_messages)}")
    print(f"✅ Successful extractions: {successful_extractions}")
    print(f"⏭️  Skipped emails: {skipped_emails}")
    if save_files:
        print(f"📁 Files saved in: {OUTPUT_DIR}/")
    else:
        print("📁 No files saved (save_files=False).")
 
    return len(all_messages), successful_extractions
 
def main():
    try:
        # Standalone behavior:
        #   ENV=local  -> save_files=True
        #   ENV=global -> save_files=False
        save_files = IS_LOCAL_ENV
        process_all_emails(save_files=save_files)
    except requests.HTTPError as e:
        print(f"❌ HTTP Error: {e}")
    except Exception as e:
        print(f"❌ Error: {e}")
 
if __name__ == "__main__":
    main()
 

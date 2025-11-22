import requests
import pandas as pd
from bs4 import BeautifulSoup
import json
from datetime import datetime, timezone, timedelta
import time
import os
import re
 
 
 
 
# Load environment variables
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
 
# Check environment
IS_LOCAL_ENV = os.environ.get("ENV", "").lower() == "local"
 
# ------------- CONFIG -------------
ACCESS_TOKEN = 
USER_EMAIL=
 
headers = {
    "Authorization": f"Bearer {ACCESS_TOKEN}",
    "Prefer": 'outlook.body-content-type="html"'
}
 
# Create output directory only for local environment
OUTPUT_DIR = "email_extracts"
if IS_LOCAL_ENV and not os.path.exists(OUTPUT_DIR):
    os.makedirs(OUTPUT_DIR)
 
 
def sanitize_filename(filename):
    """Remove invalid characters from filename"""
    return re.sub(r'[<>:"/\\|?*]', '_', filename)
 
def convert_to_ist_format(utc_datetime_str):
    """Convert UTC datetime string to IST format like in mod.json"""
    try:
        # Parse the UTC datetime
        utc_dt = datetime.fromisoformat(utc_datetime_str.replace('Z', '+00:00'))
        # Convert to IST (UTC+5:30)
        ist_offset = timezone(timedelta(hours=5, minutes=30))
        ist_dt = utc_dt.astimezone(ist_offset)
        return ist_dt.strftime("%Y-%m-%dT%H:%M:%SZ+05:30")
    except:
        # Fallback to current time in IST format
        return datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ+05:30")
 
# ------------- HTML PARSING AND VALIDATION FUNCTIONS -------------
 
def extract_tables_from_html_body(html_content):
    """
    Extract all table data from HTML body content.
    Returns structured table data with headers and rows.
    """
    if not html_content or not html_content.strip():
        return []
       
    soup = BeautifulSoup(html_content, "html.parser")
    tables = soup.find_all("table")
   
    if not tables:
        return []
   
    extracted_tables = []
   
    for table_idx, table in enumerate(tables):
        table_rows = table.find_all("tr")
       
        if len(table_rows) < 2:  # Need at least header + 1 data row
            continue
           
        # Extract header row
        header_row = None
        data_rows = []
       
        for row in table_rows:
            cells = row.find_all(["td", "th"])
            if not cells:
                continue
               
            cell_texts = [cell.get_text(strip=True) for cell in cells]
           
            # First row with content becomes header
            if header_row is None:
                header_row = cell_texts
            else:
                data_rows.append(cell_texts)
       
        # Convert to structured format
        if header_row and data_rows:
            table_data = []
            for row in data_rows:
                # Ensure row has same number of columns as header
                while len(row) < len(header_row):
                    row.append("")
               
                # Create row dictionary
                row_dict = {}
                for i, header in enumerate(header_row):
                    if i < len(row):
                        row_dict[header.strip() if header else f"Column_{i+1}"] = row[i].strip()
                    else:
                        row_dict[header.strip() if header else f"Column_{i+1}"] = ""
               
                table_data.append(row_dict)
           
            if table_data:
                extracted_tables.append({
                    "table_index": table_idx,
                    "headers": header_row,
                    "data": table_data
                })
   
    return extracted_tables
 
def check_mandatory_fields_in_html(html_content):
    """
    Check if HTML body content contains all 5 mandatory fields.
    Returns True if all fields are present, False otherwise.
   
    Mandatory fields:
    - station
    - weatherPhenomenon
    - operationProbability
    - advisoryTimePeriodStartUTC
    - advisoryTimePeriodEndUTC
    """
    if not html_content:
        return False
   
    # Convert to lowercase for case-insensitive matching
    html_lower = html_content.lower()
   
    # Define field patterns to search for
    mandatory_patterns = [
        ["station"],
        ["weather", "phenomenon"],
        ["operation", "probability", "operational", "probability"],
        ["advisory", "start", "utc", "period", "start", "utc"],
        ["advisory", "end", "utc", "period", "end", "utc"]
    ]
   
    fields_found = 0
   
    for pattern_group in mandatory_patterns:
        field_found = False
        for pattern in pattern_group:
            if pattern in html_lower:
                field_found = True
                break
        if field_found:
            fields_found += 1
   
    return fields_found >= 5
 
def extract_weather_stations_from_tables(tables):
    """
    Extract weather station data from tables with exact values from HTML.
    NO artificial defaults - only use original values from email content.
   
    Returns list of station dictionaries with original values.
    """
    stations = []
   
    for table in tables:
        headers = table.get("headers", [])
        table_data = table.get("data", [])
       
        if not headers or not table_data:
            continue
       
        # Map headers to our field names (case-insensitive matching)
        header_mapping = {}
        for i, header in enumerate(headers):
            header_lower = header.lower().strip()
           
            if "station" in header_lower:
                header_mapping["station"] = i
            elif "weather" in header_lower and "phenomenon" in header_lower:
                header_mapping["weatherPhenomenon"] = i
            elif "operation" in header_lower and "probability" in header_lower:
                header_mapping["operationProbability"] = i
            elif ("advisory" in header_lower and "start" in header_lower and "utc" in header_lower) or \
                 ("start" in header_lower and "utc" in header_lower):
                header_mapping["advisoryTimePeriodStartUTC"] = i
            elif ("advisory" in header_lower and "end" in header_lower and "utc" in header_lower) or \
                 ("end" in header_lower and "utc" in header_lower):
                header_mapping["advisoryTimePeriodEndUTC"] = i
            elif ("advisory" in header_lower and "start" in header_lower and ("lt" in header_lower or "local" in header_lower)) or \
                 ("start" in header_lower and ("lt" in header_lower or "local" in header_lower)):
                header_mapping["advisoryTimePeriodStartLT"] = i
            elif ("advisory" in header_lower and "end" in header_lower and ("lt" in header_lower or "local" in header_lower)) or \
                 ("end" in header_lower and ("lt" in header_lower or "local" in header_lower)):
                header_mapping["advisoryTimePeriodEndLT"] = i
       
        # Extract station data from each row
        for row_dict in table_data:
            station_entry = {}
           
            # Extract values using exact positions from headers
            for field_name, header_index in header_mapping.items():
                if header_index < len(headers):
                    header_name = headers[header_index]
                    value = row_dict.get(header_name, "").strip()
                   
                    if value:  # Only add non-empty values
                        if field_name == "station":
                            # Validate station code (3 letters, uppercase)
                            if len(value) == 3 and value.isalpha() and value.isupper():
                                station_entry[field_name] = value
                        elif field_name == "operationProbability":
                            # Convert to integer
                            try:
                                station_entry[field_name] = int(float(value))
                            except (ValueError, TypeError):
                                continue  # Skip if conversion fails
                        else:
                            # Use exact value for other fields
                            station_entry[field_name] = value
           
            # Only add station if it has ALL 5 mandatory fields
            mandatory_fields = ["station", "weatherPhenomenon", "operationProbability",
                              "advisoryTimePeriodStartUTC", "advisoryTimePeriodEndUTC"]
           
            if all(field in station_entry for field in mandatory_fields):
                stations.append(station_entry)
   
    return stations
 
# ------------- EMAIL PROCESSING FUNCTIONS -------------
 
def get_all_messages(page_size: int = 50, max_pages: int = None):
    """
    Get all messages from the mailbox with pagination.
    Returns a list of message objects with basic info.
    """
    url = (
        f"https://graph.microsoft.com/v1.0/users/{USER_EMAIL}/messages"
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
       
        # Check for next page
        url = data.get("@odata.nextLink")
        page_count += 1
       
        # Add small delay to avoid rate limiting
        time.sleep(0.5)
   
    print(f"Total messages retrieved: {len(all_messages)}")
    return all_messages
 
def get_message_body_html(message_id: str) -> str:
    """
    Fetch full message body (HTML) for given message_id.
    """
    url = (
        f"https://graph.microsoft.com/v1.0/users/{USER_EMAIL}/messages/{message_id}"
        "?$select=subject,body"
    )
 
    resp = requests.get(url, headers=headers)
    if resp.status_code != 200:
        print(f"Error fetching message body for {message_id}: {resp.status_code}")
        return ""
 
    data = resp.json()
    body = data.get("body", {})
    return body.get("content", "")
 
def process_single_email(message):
    """
    Process a single email and extract weather advisory data if valid.
    Returns weather advisory dict or None if invalid.
    """
    try:
        # Get email HTML body
        body_html = get_message_body_html(message["id"])
        if not body_html:
            return None
       
        # Check if HTML contains mandatory fields
        if not check_mandatory_fields_in_html(body_html):
            print("   ❌ Missing mandatory fields in HTML body - Skipping")
            return None
       
        print("   ✅ All mandatory fields found in HTML - Processing...")
       
        # Extract tables from HTML
        tables = extract_tables_from_html_body(body_html)
        if not tables:
            print("   ❌ No tables found in HTML - Skipping")
            return None
       
        # Extract weather stations with original values
        stations = extract_weather_stations_from_tables(tables)
        if not stations:
            print("   ❌ No valid weather stations extracted - Skipping")
            return None
       
        # Create weather advisory with original values
        weather_advisory = {
            "createdAt": convert_to_ist_format(message.get("receivedDateTime", "")),
            "stations": stations
        }
       
        return weather_advisory
       
    except Exception as e:
        print(f"   ❌ Error processing email: {e}")
        return None
 
def process_all_emails():
    """
    Process all emails and extract weather advisory data.
    Only processes emails with all 5 mandatory fields.
    """
    if not IS_LOCAL_ENV:
        print("❌ File creation only available in local environment (ENV=local)")
        return 0, 0
       
    print("🔍 Starting email processing with HTML body validation...")
    print("📋 Required fields: station, weatherPhenomenon, operationProbability, advisoryTimePeriodStartUTC, advisoryTimePeriodEndUTC")
    print("🎯 Only original values from email content will be used (no artificial defaults)")
   
    # Get all messages without limits
    all_messages = get_all_messages(page_size=50)
    successful_extractions = 0
    skipped_emails = 0
   
    for idx, message in enumerate(all_messages):
        subject = message.get('subject', 'No Subject')[:50]
        print(f"\nProcessing email {idx + 1}/{len(all_messages)}: {subject}...")
       
        # Process the email
        weather_advisory = process_single_email(message)
       
        if weather_advisory:
            # Save to JSON file in local environment
            if IS_LOCAL_ENV:
                # Create filename from subject and date
                subject_clean = sanitize_filename(message.get("subject", "No_Subject")[:30])
                date_clean = message.get("receivedDateTime", "")[:10].replace("-", "_")
                filename = f"{idx + 1:03d}_{date_clean}_{subject_clean}.json"
                filepath = os.path.join(OUTPUT_DIR, filename)
               
                # Save weather advisory JSON
                with open(filepath, "w", encoding="utf-8") as f:
                    json.dump(weather_advisory, f, indent=2, ensure_ascii=False)
               
                station_count = len(weather_advisory["stations"])
                print(f"   ✅ Extracted {station_count} valid station(s) - Saved to {filename}")
           
            successful_extractions += 1
        else:
            skipped_emails += 1
       
        # Add small delay to avoid rate limiting
        time.sleep(0.2)
   
    print(f"\n" + "="*60)
    print("🎯 EMAIL PROCESSING SUMMARY")
    print(f"="*60)
    print(f"📧 Total emails processed: {len(all_messages)}")
    print(f"✅ Successful extractions: {successful_extractions}")
    print(f"⏭️  Skipped emails: {skipped_emails}")
    print(f"📁 Files saved in: {OUTPUT_DIR}/")
   
    return len(all_messages), successful_extractions
 
def main():
    try:
        print("="*60)
        print("🌤️  WEATHER ADVISORY EMAIL PROCESSOR V2")
        print("="*60)
        print("🔍 HTML Body Content Parser with Original Value Extraction")
        print("📋 Mandatory Fields Validation: 5 required fields")
        print("🚫 No Artificial Defaults: Only original email values used")
        print()
       
        # Process all emails
        total_processed, successful = process_all_emails()
       
        print(f"\n" + "="*50)
        print("✅ PROCESSING COMPLETE!")
        print(f"="*50)
        print(f"Total emails processed: {total_processed}")
        print(f"Successful extractions: {successful}")
       
        # List all created files
        if successful > 0 and IS_LOCAL_ENV:
            print(f"\n📁 Created files in {OUTPUT_DIR}/:")
            for filename in sorted(os.listdir(OUTPUT_DIR)):
                if filename.endswith('.json'):
                    print(f"  - {filename}")
       
    except requests.HTTPError as e:
        print(f"❌ HTTP Error: {e}")
    except Exception as e:
        print(f"❌ Error: {e}")
 
if __name__ == "__main__":
    main()
 

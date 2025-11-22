import requests
import pandas as pd
from bs4 import BeautifulSoup
import json
from datetime import datetime
import time
import os
import re
 
# ------------- CONFIG -------------
ACCESS_TOKEN = 
USER_EMAIL
 
headers = {
    "Authorization": f"Bearer {ACCESS_TOKEN}",
    "Prefer": 'outlook.body-content-type="html"'
}
 
# Create output directory for individual email JSONs
OUTPUT_DIR = "email_extracts"
if not os.path.exists(OUTPUT_DIR):
    os.makedirs(OUTPUT_DIR)
 
# ------------- HELPERS -------------
 
def sanitize_filename(filename):
    """Remove invalid characters from filename"""
    return re.sub(r'[<>:"/\\|?*]', '_', filename)
 
 
def get_all_messages(page_size: int = 50, max_pages: int = None):
    """Get all messages from the mailbox with pagination."""
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
       
        url = data.get("@odata.nextLink")
        page_count += 1
        time.sleep(0.5)
   
    print(f"Total messages retrieved: {len(all_messages)}")
    return all_messages
 
 
def get_message_body_html(message_id: str) -> str:
    """Fetch full message body (HTML) for given message_id."""
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
 
 
def extract_weather_stations_from_table(html: str):
    """
    Extract weather station data in the format similar to mod.json.
    This function looks for tables with weather advisory data.
    """
    if not html.strip():
        return []
       
    soup = BeautifulSoup(html, "html.parser")
    tables = soup.find_all("table")
   
    if not tables:
        return []
   
    stations = []
   
    for table in tables:
        rows = table.find_all("tr")
        if len(rows) < 2:
            continue
           
        # Extract all text content from table
        table_text = table.get_text(separator='\n', strip=True)
        lines = [line.strip() for line in table_text.split('\n') if line.strip()]
       
        # Look for station codes (3-letter airport codes)
        station_codes = []
        for line in lines:
            # Match 3-letter airport codes
            if re.match(r'^[A-Z]{3}$', line):
                station_codes.append(line)
       
        # For each station found, create a station entry
        for station_code in station_codes:
            # Skip if it's a header or common word
            if station_code in ['ROW', 'THE', 'AND', 'FOR', 'ALL']:
                continue
               
            station_entry = {
                "station": station_code,
                "weatherPhenomenon": "FG",  # Default to fog, can be enhanced
                "operationProbability": 50,  # Default probability
                "advisoryTimePeriodStartUTC": datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ"),
                "advisoryTimePeriodEndUTC": (datetime.now().replace(hour=datetime.now().hour + 2)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "advisoryTimePeriodStartLT": datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ+05:30"),
                "advisoryTimePeriodEndLT": (datetime.now().replace(hour=datetime.now().hour + 2)).strftime("%Y-%m-%dT%H:%M:%SZ+05:30")
            }
            stations.append(station_entry)
   
    return stations
 
 
def extract_enhanced_weather_data(html: str, email_date: str):
    """
    Enhanced extraction that tries to parse weather phenomena and probabilities.
    """
    if not html.strip():
        return []
       
    soup = BeautifulSoup(html, "html.parser")
   
    # Get the full text to analyze
    full_text = soup.get_text(separator=' ', strip=True)
   
    # Common weather phenomena patterns
    weather_patterns = {
        'FG': ['fog', 'mist', 'visibility'],
        'TSRA': ['thunderstorm', 'rain', 'precipitation'],
        'SN': ['snow', 'snowing'],
        'BR': ['haze', 'hazy'],
        'DU': ['dust', 'dusty'],
        'SA': ['sand', 'sandstorm']
    }
   
    # Extract station codes
    station_codes = re.findall(r'\b[A-Z]{3}\b', full_text)
    # Filter out common non-station codes
    exclude_codes = ['THE', 'AND', 'FOR', 'ALL', 'UTC', 'IST', 'GMT', 'PST', 'EST', 'MST', 'CST']
    station_codes = [code for code in station_codes if code not in exclude_codes]
   
    # Remove duplicates while preserving order
    unique_stations = []
    for station in station_codes:
        if station not in unique_stations:
            unique_stations.append(station)
   
    stations = []
   
    for station_code in unique_stations:
        # Determine weather phenomenon based on text content
        weather_phenom = "FG"  # Default
        for phenom, keywords in weather_patterns.items():
            if any(keyword.lower() in full_text.lower() for keyword in keywords):
                weather_phenom = phenom
                break
       
        # Try to extract probability if mentioned
        probability = 50  # Default
        prob_match = re.search(r'(\d+)%', full_text)
        if prob_match:
            probability = int(prob_match.group(1))
       
        # Parse email date for timing
        try:
            email_dt = datetime.fromisoformat(email_date.replace('Z', '+00:00'))
        except:
            email_dt = datetime.now()
       
        # Create advisory time periods (example: 2 hours from email time)
        start_time = email_dt
        end_time = email_dt.replace(hour=email_dt.hour + 2) if email_dt.hour < 22 else email_dt.replace(hour=23, minute=59)
       
        station_entry = {
            "station": station_code,
            "weatherPhenomenon": weather_phenom,
            "operationProbability": probability,
            "advisoryTimePeriodStartUTC": start_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "advisoryTimePeriodEndUTC": end_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "advisoryTimePeriodStartLT": start_time.strftime("%Y-%m-%dT%H:%M:%SZ+05:30"),
            "advisoryTimePeriodEndLT": end_time.strftime("%Y-%m-%dT%H:%M:%SZ+05:30")
        }
        stations.append(station_entry)
   
    return stations
 
 
def process_single_email(message, index):
    """Process a single email and create individual JSON file."""
    print(f"Processing email {index}: {message.get('subject', 'No Subject')[:50]}...")
   
    email_data = {
        "message_id": message["id"],
        "subject": message.get("subject", ""),
        "received_date": message.get("receivedDateTime", ""),
        "from": message.get("from", {}).get("emailAddress", {}).get("address", "") if message.get("from") else "",
        "processing_status": "success"
    }
   
    try:
        # Get email body
        body_html = get_message_body_html(message["id"])
       
        if body_html:
            # Extract weather station data
            stations = extract_enhanced_weather_data(body_html, message.get("receivedDateTime", ""))
           
            # Create weather advisory format similar to mod.json
            weather_advisory = {
                "createdAt": datetime.now().isoformat() + "+05:30",
                "emailSubject": message.get("subject", ""),
                "emailDate": message.get("receivedDateTime", ""),
                "emailFrom": message.get("from", {}).get("emailAddress", {}).get("address", "") if message.get("from") else "",
                "stations": stations
            }
           
            # Create filename from subject and date
            subject_clean = sanitize_filename(message.get("subject", "No_Subject")[:50])
            date_clean = message.get("receivedDateTime", "")[:10].replace("-", "_")
            filename = f"{index:03d}_{date_clean}_{subject_clean}.json"
            filepath = os.path.join(OUTPUT_DIR, filename)
           
            # Save individual email JSON
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(weather_advisory, f, indent=2, ensure_ascii=False)
           
            print(f"  Found {len(stations)} station(s) - Saved to {filename}")
           
            return {
                "email_data": email_data,
                "weather_advisory": weather_advisory,
                "filename": filename,
                "stations_count": len(stations)
            }
        else:
            print("  No body content")
            return {
                "email_data": email_data,
                "weather_advisory": None,
                "filename": None,
                "stations_count": 0
            }
           
    except Exception as e:
        print(f"  Error processing email: {e}")
        email_data["processing_status"] = f"error: {str(e)}"
        return {
            "email_data": email_data,
            "weather_advisory": None,
            "filename": None,
            "stations_count": 0
        }
 
 
def process_all_emails():
    """Process all emails and extract weather data."""
    print("Starting to fetch all messages...")
   
    # Get all messages (limit pages for testing)
    all_messages = get_all_messages(page_size=50, max_pages=5)  # Remove max_pages=5 to get all emails
   
    results = {
        "extraction_date": datetime.now().isoformat(),
        "total_emails_processed": 0,
        "emails_with_weather_data": 0,
        "total_stations_found": 0,
        "processed_emails": []
    }
   
    for idx, message in enumerate(all_messages, 1):
        result = process_single_email(message, idx)
        results["processed_emails"].append(result)
        results["total_emails_processed"] += 1
       
        if result["weather_advisory"] and result["stations_count"] > 0:
            results["emails_with_weather_data"] += 1
            results["total_stations_found"] += result["stations_count"]
       
        # Add delay to avoid rate limiting
        time.sleep(0.2)
   
    return results
 
 
def main():
    try:
        print("Starting weather advisory extraction process...")
        print(f"Output directory: {OUTPUT_DIR}")
       
        # Process all emails
        results = process_all_emails()
       
        # Save summary results
        summary_file = "weather_extraction_summary.json"
        with open(summary_file, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
       
        print(f"\n" + "="*60)
        print("EXTRACTION COMPLETE!")
        print(f"="*60)
        print(f"Total emails processed: {results['total_emails_processed']}")
        print(f"Emails with weather data: {results['emails_with_weather_data']}")
        print(f"Total stations found: {results['total_stations_found']}")
        print(f"Individual email JSONs saved in: {OUTPUT_DIR}/")
        print(f"Summary saved to: {summary_file}")
       
        # List all created files
        print(f"\nCreated files:")
        for result in results["processed_emails"]:
            if result["filename"]:
                print(f"  - {result['filename']} ({result['stations_count']} stations)")
       
    except requests.HTTPError as e:
        print("HTTPError:", e)
    except Exception as e:
        print("Error:", e)
 
 
if __name__ == "__main__":
    main()
 

from typing import Any, List, Dict, Optional
import asyncio
from datetime import datetime, timedelta
from motor.motor_asyncio import AsyncIOMotorClient
import json
from dotenv import load_dotenv
import os, time, httpx
from fastmcp import FastMCP, Context
from fastmcp.server.dependencies import get_access_token, AccessToken, get_context
from fastmcp.server.auth.providers.jwt import JWTVerifier
from fastmcp.server.middleware import Middleware, MiddlewareContext
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse
from toon import encode
from openai import AzureOpenAI

from fastmcp.server.auth import TokenVerifier, AccessToken as AuthAccessToken
import base64, json, time

from functools import wraps
from inspect import signature
import logging
import sys

from fastmcp.server.middleware.rate_limiting import (
    SlidingWindowRateLimitingMiddleware
)


# Load environment variables from .env file
load_dotenv()

# Configure logging to display only in terminal
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)

logger = logging.getLogger(__name__)

# MongoDB configuration
MONGODB_URL = os.getenv("MONGODB_URL", "mongodb://localhost:27017")
DATABASE_NAME = os.getenv("DATABASE_NAME", "metar_data")
COLLECTION_METAR = os.getenv("COLLECTION_METAR", "metar_data")

# ------------------- Config (server-only secrets) -------------------
TENANT_ID = os.getenv("TENANT_ID")
APP_ID = os.getenv("APP_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")
PORT = int(os.getenv("PORT"))
SERVER_CLIENT_ID = os.getenv("SERVER_CLIENT_ID")

# OpenID metadata
JWKS_URI = f"https://login.microsoftonline.com/{TENANT_ID}/discovery/v2.0/keys"
ISSUER = f"https://sts.windows.net/{TENANT_ID}/"
AUDIENCE = f"api://{SERVER_CLIENT_ID}"



# ------------------- MCP with JWT verification ----------------------
# class ExpiryIssuerAudienceVerifier(TokenVerifier):
#     def __init__(
#         self,
#         *,
#         issuer: str | None = None,
#         audience: str | list[str] | None = None,
#         required_scopes: list[str] | None = None,
#         base_url: str | None = None,
#         clock_skew_seconds: int = 60,
#     ):
#         super().__init__(required_scopes=required_scopes, base_url=base_url)
#         self.issuer = issuer
#         self.audience = audience
#         self.clock_skew_seconds = clock_skew_seconds

#     def _extract_scopes(self, claims: dict[str, Any]) -> list[str]:
#         for claim in ["scope", "scp"]:
#             if claim in claims:
#                 if isinstance(claims[claim], str):
#                     return claims[claim].split()
#                 elif isinstance(claims[claim], list):
#                     return claims[claim]
#         return []

#     async def verify_token(self, token: str) -> AuthAccessToken | None:
#         try:
#             parts = token.split(".")
#             if len(parts) != 3:
#                 return None
#             payload_b64 = parts[1]
#             payload_b64 += "=" * ((-len(payload_b64)) % 4)  # base64url padding
#             claims = json.loads(
#                 base64.urlsafe_b64decode(payload_b64.encode("utf-8")).decode("utf-8")
#             )

#             # Expiration check only
#             exp = claims.get("exp")
#             now = int(time.time())
#             if exp is None or now > int(exp) + self.clock_skew_seconds:
#                 return None

#             # Issuer check
#             if self.issuer and claims.get("iss") != self.issuer:
#                 return None

#             # Audience check
#             if self.audience is not None:
#                 aud = claims.get("aud")
#                 audience_valid = False
#                 if isinstance(self.audience, list):
#                     if isinstance(aud, list):
#                         audience_valid = any(expected in aud for expected in self.audience)
#                     else:
#                         audience_valid = aud in self.audience
#                 else:
#                     if isinstance(aud, list):
#                         audience_valid = self.audience in aud
#                     else:
#                         audience_valid = aud == self.audience
#                 if not audience_valid:
#                     return None

#             client_id = claims.get("client_id") or claims.get("azp") or claims.get("sub") or "unknown"
#             scopes = self._extract_scopes(claims)

#             return AuthAccessToken(
#                 token=token,
#                 client_id=str(client_id),
#                 scopes=scopes,
#                 expires_at=int(exp),
#                 claims=claims,
#             )
#         except Exception:
#             return None

# Use local expiry + iss/aud checks only (no JWKS/issuer calls)
# auth = ExpiryIssuerAudienceVerifier(issuer=ISSUER, audience=AUDIENCE)

auth = JWTVerifier(
    jwks_uri=JWKS_URI,
    issuer=ISSUER,
    audience=AUDIENCE,
)

# ----- rate limiting middleware ------
 


def get_client_id_from_context(context: MiddlewareContext) -> str:
    """Extract OID from the access token for rate limiting."""
    try:
        token: AccessToken | None = get_access_token()
        if token and token.claims:
            return token.claims.get("oid", "anonymous")
        return "global"
    except Exception:
        return "global"
    

rate_limiter = SlidingWindowRateLimitingMiddleware(
    max_requests=10,           # Allow 10 requests
    window_minutes=1,           # Per minute
    get_client_id=get_client_id_from_context  # Use OID as client ID
)

#------------------------- tool filtering middleware -------------------------

class ListingFilterMiddleware(Middleware):
    async def on_list_tools(self, context: MiddlewareContext, call_next):
        result = await call_next(context)
        
        try:
            token: AccessToken | None = get_access_token()
            if not token:
                return []  
                
            user_roles = token.claims.get('roles', [])
            
            has_read = "WeatherDataRead" in user_roles
            has_write = "WeatherDataWrite" in user_roles
            
            # No weather roles = no tools
            if not has_read and not has_write:
                return []
            
            # Filter tools based on permissions
            filtered_tools = []
            for tool in result:
                tool_tags = tool.tags or []
                
                # Allow tool if user has required permissions
                if "WeatherDataRead" in tool_tags and has_read:
                    filtered_tools.append(tool)
                elif "WeatherDataWrite" in tool_tags and has_write:
                    filtered_tools.append(tool)
            
            return filtered_tools
            
        except Exception as e:
            logger.error(f"Error in tool filtering: {e}", exc_info=True)
            return []  # On error, return no tools (fail-safe)

mcp = FastMCP(name="metar-weather", auth=auth)
mcp.add_middleware(rate_limiter)
mcp.add_middleware(ListingFilterMiddleware())

# Global MongoDB client
client = None
db = None

llm = AzureOpenAI(
    api_key=os.getenv("subscription_key"),
    api_version=os.getenv("api_version"),
    azure_endpoint=os.getenv("endpoint"),
)

graph_msg = """"
            You are an intelligent agent capable of converting given data into a format suitable JSON format for ChartPanel and TablePanel components.
            convert the given data into a JSON structure that includes both table data and chart data.
            {
                "type": "RUN_FINISHED",
                "table": {
                    "columns": ["Flight", "From", "To", "Status", "Delay (min)"],
                    "rows": [
                    { "Flight": "AI100", "From": "BLR", "To": "DEL", "Status": "Cancelled", "Delay (min)": 0 },
                    { "Flight": "AI101", "From": "CCU", "To": "BOM", "Status": "Cancelled", "Delay (min)": 10 },
                    { "Flight": "AI102", "From": "CCU", "To": "HYD", "Status": "On Time", "Delay (min)": 60 },
                    { "Flight": "AI103", "From": "BOM", "To": "BLR", "Status": "Cancelled", "Delay (min)": 20 },
                    { "Flight": "AI104", "From": "CCU", "To": "DEL", "Status": "On Time", "Delay (min)": 15 },
                    { "Flight": "AI105", "From": "BOM", "To": "MAA", "Status": "Cancelled", "Delay (min)": 45 },
                    { "Flight": "AI106", "From": "CCU", "To": "DEL", "Status": "On Time", "Delay (min)": 60 }
                    ]
                },
                "chart": {
                    "data": [
                    { "day": "Mon", "bookings": 37 },
                    { "day": "Tue", "bookings": 31 },
                    { "day": "Wed", "bookings": 44 },
                    { "day": "Thu", "bookings": 45 },
                    { "day": "Fri", "bookings": 37 },
                    { "day": "Sat", "bookings": 35 },
                    { "day": "Sun", "bookings": 36 }
                    ],
                    "xKey": "day",
                    "yKey": "bookings",
                    "chartType": "line" or "bar"
                }
            }

            Instructions:
            1. always keep the type as "RUN_FINISHED".
            2. do not provide any additional explanation, comments, context, or interpretation.

            
            """

async def get_mongodb_client():
    """Get MongoDB client connection."""
    global client, db
    if client is None:
        client = AsyncIOMotorClient(MONGODB_URL)
        db = client[DATABASE_NAME]
    return client, db

def format_metar_data(metar_doc: Dict) -> str:
    """Format METAR data into a readable string."""
    station = metar_doc.get('stationICAO', 'Unknown')
    iata = metar_doc.get('stationIATA', 'N/A')
    processed_timestamp = metar_doc.get('processed_timestamp', 'Unknown')
    
    result = f"🛩️  Station: {station}"
    if iata:
        result += f" ({iata})"
    result += f"\n Last Updated: {processed_timestamp}\n"
    
    if metar_doc.get('hasMetarData') and 'metar' in metar_doc:
        metar = metar_doc['metar']
        raw_data = metar.get('rawData', 'N/A')
        result += f" Raw METAR: {raw_data}\n"
        
        if 'decodedData' in metar and 'observation' in metar['decodedData']:
            obs = metar['decodedData']['observation']
            result += f"\n Weather Conditions:\n"
            result += f"   Temperature: {obs.get('airTemperature', 'N/A')}\n"
            result += f"   Dewpoint: {obs.get('dewpointTemperature', 'N/A')}\n"
            result += f"   Wind: {obs.get('windSpeed', 'N/A')} from {obs.get('windDirection', 'N/A')}\n"
            result += f"   Visibility: {obs.get('horizontalVisibility', 'N/A')}\n"
            result += f"   Pressure: {obs.get('observedQNH', 'N/A')}\n"
            
            if obs.get('cloudLayers'):
                result += f"   Clouds: {', '.join(obs['cloudLayers'])}\n"
            
            if obs.get('weatherConditions'):
                result += f"   Weather: {obs['weatherConditions']}\n"
    
    if metar_doc.get('hasTaforData') and 'tafor' in metar_doc:
        tafor = metar_doc['tafor']
        raw_taf = tafor.get('rawData', 'N/A')
        result += f"\n📊 TAF: {raw_taf}\n"
    
    return result

# ------------------- Tools (protected by JWTVerifier) ---------------
@mcp.tool(tags=["WeatherDataRead"])
async def search_metar_data(
    station_icao: str = None,
    station_iata: str = None,
    weather_condition: str = None,
    temperature_min: float = None,
    temperature_max: float = None,
    visibility_min: int = None,
    visibility_max: int = None,
    wind_speed_min: float = None,
    wind_speed_max: float = None,
    pressure_min: float = None,
    pressure_max: float = None,
    cloud_type: str = None,
    fir_region: str = None,
    hours_back: int = None,
    limit: int = 10
) -> str:
    """Generic search for METAR data with multiple optional filters.

    Args:
        station_icao: Filter by ICAO code (e.g., 'VOTP', 'VIDP', 'VOBG')
        station_iata: Filter by IATA code (e.g., 'TIR', 'BOM', 'DEL')
        weather_condition: Search in raw METAR data (e.g., 'Rain', 'fog', 'CB')
        temperature_min: Minimum temperature in Celsius
        temperature_max: Maximum temperature in Celsius
        visibility_min: Minimum visibility in meters
        visibility_max: Maximum visibility in meters
        wind_speed_min: Minimum wind speed in m/s
        wind_speed_max: Maximum wind speed in m/s
        pressure_min: Minimum pressure in hPa
        pressure_max: Maximum pressure in hPa
        cloud_type: Search for cloud types in raw data (e.g., 'CB', 'SCT', 'OVC')
        fir_region: Filter by FIR region (e.g., 'Chennai', 'Mumbai')
        hours_back: Look back N hours from now
        limit: Maximum results to return (set default as: 10, max: 50)
    """
    try:
        _, db = await get_mongodb_client()
        
        # Build the query
        query = {}
        
        # Station filters
        if station_icao:
            query["stationICAO"] = station_icao.upper()
        if station_iata:
            query["stationIATA"] = station_iata.upper()
        
        # FIR region filter
        if fir_region:
            query["metar.firRegion"] = {"$regex": fir_region, "$options": "i"}
        
        # Time filter
        if hours_back:
            time_threshold = datetime.now() - timedelta(hours=hours_back)
            query["timestamp"] = {"$gte": time_threshold}
        
        # Weather condition filter (search in raw METAR data)
        if weather_condition:
            query["metar.decodedData.observation.weatherConditions"] = weather_condition
        
        # Cloud type filter (search in raw METAR data)
        if cloud_type:
            query["metar.rawData"] = {"$regex": cloud_type, "$options": "i"}
        
        # Temperature filters
        if temperature_min is not None or temperature_max is not None:
            temp_query = {}
            if temperature_min is not None:
                temp_query["$gte"] = str(temperature_min)
            if temperature_max is not None:
                temp_query["$lte"] = str(temperature_max)
            query["metar.decodedData.observation.airTemperature"] = temp_query
        
        # Visibility filters
        if visibility_min is not None or visibility_max is not None:
            vis_query = {}
            if visibility_min is not None:
                vis_query["$gte"] = str(visibility_min)
            if visibility_max is not None:
                vis_query["$lte"] = str(visibility_max)
            query["metar.decodedData.observation.horizontalVisibility"] = vis_query
        
        # Wind speed filters
        if wind_speed_min is not None or wind_speed_max is not None:
            wind_query = {}
            if wind_speed_min is not None:
                wind_query["$gte"] = str(wind_speed_min)
            if wind_speed_max is not None:
                wind_query["$lte"] = str(wind_speed_max)
            query["metar.decodedData.observation.windSpeed"] = wind_query
        
        # Pressure filters
        if pressure_min is not None or pressure_max is not None:
            pressure_query = {}
            if pressure_min is not None:
                pressure_query["$gte"] = str(pressure_min)
            if pressure_max is not None:
                pressure_query["$lte"] = str(pressure_max)
            query["metar.decodedData.observation.observedQNH"] = pressure_query
        
        # Limit results
        limit = min(limit, 50)
        
        # Execute the query
        logger.info(f"Executing MongoDB query: {query}")
        cursor = db[COLLECTION_METAR].find(query).sort("timestamp", -1).limit(limit)
        results = await cursor.to_list(length=limit)
        
        if not results:
            filters = []
            if station_icao: filters.append(f"ICAO: {station_icao}")
            if station_iata: filters.append(f"IATA: {station_iata}")
            if weather_condition: filters.append(f"Weather: {weather_condition}")
            if temperature_min: filters.append(f"Temp ≥ {temperature_min}°C")
            if temperature_max: filters.append(f"Temp ≤ {temperature_max}°C")
            if visibility_min: filters.append(f"Visibility ≥ {visibility_min}m")
            if visibility_max: filters.append(f"Visibility ≤ {visibility_max}m")
            if wind_speed_min: filters.append(f"Wind ≥ {wind_speed_min} m/s")
            if wind_speed_max: filters.append(f"Wind ≤ {wind_speed_max} m/s")
            if pressure_min: filters.append(f"Pressure ≥ {pressure_min} hPa")
            if pressure_max: filters.append(f"Pressure ≤ {pressure_max} hPa")
            if cloud_type: filters.append(f"Cloud: {cloud_type}")
            if fir_region: filters.append(f"FIR: {fir_region}")
            if hours_back: filters.append(f"Last {hours_back}h")
            
            return f"No METAR data found with filters: {', '.join(filters)}"
        
        # Format results
        result = f"🔍 METAR Search Results ({len(results)} documents found):\n"
        applied_filters = [f"{k}: {v}" for k, v in locals().items() if v is not None and k not in ['db', 'cursor', 'results', 'limit', 'hours_back', 'query']]
        if applied_filters:
            result += f"Filters: {', '.join(applied_filters)}\n"
        result += "=" * 80 + "\n\n"
        
        for i, doc in enumerate(results, 1):
            result += f"--- Result {i} ---\n"
            result += format_metar_data(doc)
            result += "\n"
        
        return result
        
    except Exception as e:
        logger.error(f"Error in search_metar_data: {e}", exc_info=True)
        return f"Error executing search: {str(e)}"

@mcp.tool(tags=["WeatherDataRead"])
async def list_available_stations() -> str:
    """List all available weather stations with their codes."""
    try:
        _, db = await get_mongodb_client()
        
        # Get unique ICAO codes
        icao_codes = await db[COLLECTION_METAR].distinct("stationICAO")
        icao_codes.sort()
        
        # Get unique IATA codes (non-null)
        iata_codes = await db[COLLECTION_METAR].distinct("stationIATA")
        iata_codes = [code for code in iata_codes if code is not None]
        iata_codes.sort()
        
        # Get station count
        total_stations = await db[COLLECTION_METAR].count_documents({})
        
        result = f"📡 Available Weather Stations ({total_stations} total reports)\n"
        result += "=" * 50 + "\n\n"
        
        result += f"🛩️  ICAO Codes ({len(icao_codes)} stations):\n"
        for i, code in enumerate(icao_codes, 1):
            result += f"   {i:3d}. {code}"
            if i % 10 == 0:
                result += "\n"
            else:
                result += "  "
        if len(icao_codes) % 10 != 0:
            result += "\n"
        
        result += f"\n🏢 IATA Codes ({len(iata_codes)} stations):\n"
        for i, code in enumerate(iata_codes, 1):
            result += f"   {i:3d}. {code}"
            if i % 10 == 0:
                result += "\n"
            else:
                result += "  "
        if len(iata_codes) % 10 != 0:
            result += "\n"
        
        return result
        
    except Exception as e:
        logger.error(f"Error in list_available_stations: {e}", exc_info=True)
        return f"Error retrieving station list: {str(e)}"

@mcp.tool(tags=["WeatherDataRead"])
async def get_metar_statistics() -> str:
    """Get statistics about the METAR database."""
    try:
        _, db = await get_mongodb_client()
        
        # Get basic counts
        total_metar = await db[COLLECTION_METAR].count_documents({})
        
        # Get unique station counts
        unique_icao = len(await db[COLLECTION_METAR].distinct("stationICAO"))
        unique_iata = len([code for code in await db[COLLECTION_METAR].distinct("stationIATA") if code is not None])
        
        # Get date range
        earliest = await db[COLLECTION_METAR].find({}, {"metar.updatedTime": 1}).sort("metar.updatedTime", 1).limit(1).to_list(1)
        latest = await db[COLLECTION_METAR].find({}, {"metar.updatedTime": 1}).sort("metar.updatedTime", -1).limit(1).to_list(1)
        
        # Get data availability
        with_metar = await db[COLLECTION_METAR].count_documents({"hasMetarData": True})
        with_taf = await db[COLLECTION_METAR].count_documents({"hasTaforData": True})
        
        result = f"📊 METAR Database Statistics\n"
        result += "=" * 40 + "\n\n"
        
        result += f"📈 Document Counts:\n"
        result += f"   METAR Reports: {total_metar:,}\n\n"
        
        result += f"🛩️  Station Information:\n"
        result += f"   Unique ICAO Codes: {unique_icao}\n"
        result += f"   Unique IATA Codes: {unique_iata}\n\n"
        
        result += f"📅 Data Range:\n"
        if earliest:
            result += f"   Earliest: {earliest[0]['metar']['updatedTime']}\n"
        if latest:
            result += f"   Latest: {latest[0]['metar']['updatedTime']}\n\n"
        
        result += f"✅ Availability:\n"
        result += f"   Reports with METAR: {with_metar:,} ({with_metar/total_metar*100:.1f}%)\n"
        result += f"   Reports with TAF: {with_taf:,} ({with_taf/total_metar*100:.1f}%)\n"
        
        return result
        
    except Exception as e:
        logger.error(f"Error in get_metar_statistics: {e}", exc_info=True)
        return f"Error retrieving statistics: {str(e)}"

@mcp.tool(tags=["WeatherDataRead"])
async def raw_mongodb_query_find(query_json: str, limit: int = 10) -> str:
    """Execute a raw MongoDB query for find queries against the METAR database."""
    try:
        _, db = await get_mongodb_client()
        
        # Parse the query JSON
        try:
            query = json.loads(query_json)
        except json.JSONDecodeError as e:
            return f"Invalid JSON query: {str(e)}\n\nExample: '{{\"stationICAO\": \"VOTP\"}}'"
        
        # Limit the number of results
        limit = min(limit, 50)
        
        logger.info(f"Executing raw MongoDB query: {query}")
        # cursor = db[COLLECTION_METAR].aggregate(query)
        cursor = db[COLLECTION_METAR].find(query).sort("metar.updatedTime", -1).limit(limit)

        results = await cursor.to_list(length=limit)
        
        if not results:
            return f"No documents found matching query: {query_json}"
                
        result = f"🔍 Raw MongoDB Query Results ({len(results)} documents found):\n"
        result += f"Query: {query_json}\n"
        result += "=" * 60 + "\n\n"
        
        for i, doc in enumerate(results, 1):
            result += f"--- Result {i} ---\n"
            result += format_metar_data(doc)
            result += "\n"
        
        return result
        
    except Exception as e:
        logger.error(f"Error in raw_mongodb_query_find: {e}", exc_info=True)
        return f"Error executing query: {str(e)}"

@mcp.tool(tags=["WeatherDataRead"])
async def raw_mongodb_query_aggregate(query_json: str, limit: int = 10) -> str:
    """Execute a raw MongoDB aggregate query against the METAR database."""
    try:
        _, db = await get_mongodb_client()
        
        # Parse the query JSON
        try:
            query = json.loads(query_json)
        except json.JSONDecodeError as e:
            return f"Invalid JSON query: {str(e)}\n\nExample: '{{\"stationICAO\": \"VOTP\"}}'"
        
        # Limit the number of results
        limit = min(limit, 50)
        
        logger.info(f"Executing raw MongoDB query: {query}")
        cursor = db[COLLECTION_METAR].aggregate(query)
        # cursor = db[COLLECTION_METAR].find(query).sort("metar.updatedTime", -1).limit(limit)

        results = await cursor.to_list(length=limit)
        
        if not results:
            return f"No documents found matching query: {query_json}"
        
        # Format results
        logger.debug(f"Aggregate query results: {results}")

        toon_result = encode(results)
        # result = f"🔍 Raw MongoDB Query Results ({len(results)} documents found):\n"
        # result += f"Query: {query_json}\n"
        # result += "=" * 60 + "\n\n"
        
        # for i, doc in enumerate(results, 1):
        #     result += f"--- Result {i} ---\n"
        #     result += format_metar_data(doc)
        #     result += "\n"
        
        return toon_result
        
    except Exception as e:
        logger.error(f"Error in raw_mongodb_query_aggregate: {e}", exc_info=True)
        return f"Error executing query: {str(e)}"

@mcp.tool(tags=["WeatherDataWrite"])
async def table_and_graph_JSON_generater(response_data:str) -> str:
    """Generate JSON for table and graph visualization of METAR data. from the data provided by LLM.
    
    Args:
        response_data: response from LLM
    """

    prompt = response_data
    messages = [
                {"role": "system", "content": graph_msg},
                {"role": "user", "content": "The User prompt is as follows:\n" + prompt}
            ]
    # Request LLM analysis
    response = llm.chat.completions.create(
                    model=os.getenv("deployment"),
                    messages=messages,
                )
    result = response.choices[0].message.content
    logger.info(f"Generated Table and Graph JSON: {result}")
    return result


# @mcp.tool(tags=["WeatherDataWrite"])
# async def add_metar_data(metar_raw: str, email: str = "system@occhub.com") -> str:
#     """Add new METAR data to the external weather service.
    
#     Args:
#         metar_raw: Raw METAR string (e.g., "VEPT 021330Z 08009KT 4500 HZ SCT018 BKN100 30/26 Q1001 NOSIG")
#         email: Email address for the request (optional, defaults to system email)
#     """
#     try:
#         # External API endpoint
#         url = "https://occhub-metar-ms-6eocchub-dev.apps.ocpnonprodcl01.goindigo.in/api/weather/add"
        
#         # Get authentication token
#         access_token: AccessToken | None = get_access_token()
#         if not access_token:
#             return f"❌ No authentication token available"
            
#         # Extract the actual token string
#         bearer_token = access_token.token
        
#         # Prepare headers
#         headers = {
#             "Authorization": f"Bearer {bearer_token}",
#             "Content-Type": "application/json"
#         }
        
#         # Prepare payload with correct field names
#         payload = {
#             "raw_data": metar_raw,
#             "email": email
#         }
        
#         logger.info(f"Sending METAR data to external API: {metar_raw}")
#         logger.info(f"Using email: {email}")
#         logger.debug(f"Payload: {payload}")
        
#         # Make the HTTP request using httpx (async)
#         async with httpx.AsyncClient() as client:
#             resp = await client.post(url, headers=headers, json=payload, timeout=30)
            
#             logger.info(f"Response status code: {resp.status_code}")
#             logger.debug(f"Response body: {resp.text}")
            
#             if resp.status_code in [200, 201]:
#                 return f"✅ Successfully added METAR data for {metar_raw[:4]}. Status: {resp.status_code}, Response: {resp.text}"
#             elif resp.status_code == 422:
#                 return f"❌ Validation error: {resp.text}. Please check the METAR format and email address."
#             else:
#                 return f"❌ Failed to add METAR data. Status: {resp.status_code}, Response: {resp.text}"
            
#     except httpx.TimeoutException:
#         return f"⏰ Request timeout when adding METAR data: {metar_raw[:4]}"
#     except httpx.RequestError as e:
#         return f"🌐 Network error when adding METAR data: {str(e)}"
#     except Exception as e:
#         logger.error(f"Error in add_metar_data: {e}", exc_info=True)
#         return f"💥 Unexpected error when adding METAR data: {str(e)}"


@mcp.tool(tags=["WeatherDataWrite"])
async def ping() -> str:
    """Simple ping tool for testing authentication."""
    return "🏓 Pong! Authentication working correctly."



# ------------------- Custom routes (public) -------------------------
@mcp.custom_route("/health", methods=["GET"])
async def health_check_route(request: Request):
    """Health check endpoint - no authentication required."""
    return JSONResponse({
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "server": "metar-weather-mcp",
        "azure_config": {
            "auth_enabled": True
        }
    })

@mcp.custom_route("/", methods=["GET"])
async def root(request: Request):
    return JSONResponse({
        "service": "METAR Weather MCP Server",
        "status": "healthy",
        "endpoints": {
            "mcp": "/mcp",
            "health": "/health",
            "auth_info": "/auth/token"
        },
        "description": "Weather API service for operational control hub",
        "authentication": "Azure AD JWT required for MCP endpoints",
        "auth_method": "Direct Azure AD authentication - clients authenticate directly with Azure AD"
    })

if __name__ == "__main__":
    # Initialize and run the server
    logger.info("METAR MCP Server with Azure Authentication starting...")
    logger.info(f"MongoDB URL: {MONGODB_URL}")
    logger.info(f"Database: {DATABASE_NAME}")
    logger.info(f"Collection: {COLLECTION_METAR}")
    logger.info(f"Azure Tenant ID: {TENANT_ID}")
    logger.info(f"Azure App ID: {APP_ID}")
    logger.info(f"Port: {PORT}")
    logger.info("Server ready! Waiting for HTTP requests...")
    

    # mcp.run(transport="streamable-http", host="0.0.0.0", port=PORT)

    mcp.run(transport="streamable-http", host="127.0.0.1", port=PORT)

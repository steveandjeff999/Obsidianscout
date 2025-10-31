# Obsidian-Scout REST API Documentation
**Version 1.0.2.0 | Last Updated: October 8, 2025**

Complete reference for the Obsidian-Scout REST API, WebSocket API, and Server-to-Server Sync API.

---

## Table of Contents

### Core REST API
1. [Overview](#overview)
2. [Authentication](#authentication)
3. [API Key Management](#api-key-management)
4. [Base URL & Endpoints](#base-url--endpoints)
5. [Team Data Endpoints](#team-data-endpoints)
6. [Event Data Endpoints](#event-data-endpoints)
7. [Match Data Endpoints](#match-data-endpoints)
8. [Scouting Data Endpoints](#scouting-data-endpoints)
9. [Analytics Endpoints](#analytics-endpoints)
10. [Sync Operations Endpoints](#sync-operations-endpoints)
11. [Team Lists Endpoints](#team-lists-endpoints)
12. [Health & Status](#health--status)

### Advanced APIs
13. [Server-to-Server Sync API](#server-to-server-sync-api)
14. [Real-time Replication API](#real-time-replication-api)
15. [WebSocket Events](#websocket-events)

### Reference
16. [Error Codes](#error-codes)
17. [Rate Limiting](#rate-limiting)
18. [Code Examples](#code-examples)
19. [Best Practices](#best-practices)

---

## Overview

The Obsidian-Scout API suite provides **programmatic access** to all scouting data, real-time collaboration features, and server synchronization capabilities. The API is designed for FRC scouting teams who need to:

- **Build custom integrations** with external tools and dashboards
- **Automate data collection** from multiple devices
- **Synchronize data** between multiple server instances
- **Access real-time updates** via WebSocket connections
- **Export data** for external analysis

### Key Features

 **RESTful Design** - Standard HTTP methods (GET, POST, PUT, DELETE)  
 **Team Isolation** - Every API key is scoped to a specific scouting team  
 **Fine-Grained Permissions** - Control exactly what each API key can do  
 **Rate Limiting** - Prevent abuse with configurable limits  
 **Pagination Support** - Handle large datasets efficiently  
 **Real-Time Replication** - Server-to-server database synchronization  
 **WebSocket Support** - Live updates for chat, drawings, and data changes  
 **Catch-Up Sync** - Automatic recovery after disconnections  
 **JSON Responses** - Clean, predictable data formats

### API Architecture

Obsidian-Scout provides **three interconnected API systems**:

1. **REST API (`/api/v1/`)** - Core data access and operations
2. **Sync API (`/api/sync/`)** - Server-to-server synchronization
3. **Real-time API (`/api/realtime/`)** - Real-time database replication
4. **WebSocket API** - Live collaboration (chat, drawing, presence)

### Current Version

- **REST API Version**: 1.0
- **Application Version**: 1.0.2.0
- **All REST endpoints prefixed with**: `/api/v1/`

---

## Authentication

### API Key Format

API keys use a secure format for easy identification and validation:

```
sk_live_XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX
```

**Format Specifications:**
- **Prefix**: `sk_live_` (indicates live/production key)
- **Total Length**: 40 characters
- **Character Set**: Alphanumeric (base62: A-Z, a-z, 0-9)
- **Example**: `sk_live_abc123def456ghi789jkl012mno345`

### Providing the API Key

You can authenticate using **three methods** (in order of security preference):

#### 1. Authorization Header ( Recommended)
```http
Authorization: Bearer sk_live_your_api_key_here
```

**Best for**: Production applications, server-to-server communication

#### 2. X-API-Key Header
```http
X-API-Key: sk_live_your_api_key_here
```

**Best for**: Legacy systems or APIs that don't support Authorization header

#### 3. Query Parameter (️ Use with caution)
```http
GET /api/v1/teams?api_key=sk_live_your_api_key_here
```

**Best for**: Quick testing only (keys visible in URLs, logs, and browser history)

**Security Best Practice**: Always use Authorization or X-API-Key headers in production environments.

### Permissions System

Each API key has **fine-grained permissions** that control exactly what operations it can perform:

| Permission | Description | Access Level | Operations |
|-----------|-------------|--------------|------------|
| `team_data_access` | View teams, events, and basic data | Read Only | GET /teams, /events, /info |
| `scouting_data_read` | Read match and scouting data | Read Only | GET /matches, /scouting-data |
| `scouting_data_write` | Create new scouting entries | Read + Write | POST /scouting-data |
| `analytics_access` | Access analytics and statistics | Read Only | GET /analytics/* |
| `sync_operations` | Trigger and monitor sync | Read + Execute | GET/POST /sync/* |

**Permission Combinations:**
- **Read-Only Access**: `team_data_access` + `scouting_data_read` + `analytics_access`
- **Full Data Access**: All read permissions + `scouting_data_write`
- **Sync Management**: `sync_operations` (typically requires other permissions)

**Checking Permissions:**
```bash
# Get your current permissions
curl -H "Authorization: Bearer sk_live_your_key" \
  https://your-server.com/api/v1/info
```

### Team Isolation

Every API key is **permanently registered** to a specific **scouting team number** during creation. This provides automatic data isolation:

**How It Works:**
1. API key created with `scouting_team_number=1234`
2. All queries automatically filter by `scouting_team_number=1234`
3. Cannot access or modify data from other teams

**Security Benefits:**
 **Data Privacy** - Teams cannot see each other's scouting data  
 **Multi-Team Support** - Multiple teams can use same server safely  
 **Automatic Filtering** - No need to specify team in every request  
 **Prevents Data Leaks** - Impossible to accidentally access wrong team's data  

**Example:**
```javascript
// Team 1234's API key
GET /api/v1/teams
// Returns: Only teams scouted by team 1234

// Team 5678's API key
GET /api/v1/teams
// Returns: Only teams scouted by team 5678
```

---

## API Key Management

### Creating API Keys

API keys are created through the **web interface** by administrators:

**Steps to Create:**
1. Navigate to **Admin Panel** → **API Keys** (`/api-keys/manage`)
2. Click **"Create New API Key"**
3. Configure the key:
   - **Name**: Descriptive name (e.g., "Mobile App", "Analytics Bot")
   - **Team Number**: Your scouting team number (auto-filled)
   - **Permissions**: Select operations this key can perform
   - **Rate Limit**: Requests per hour (default: 1000)
   - **Expiration**: Optional expiration date
4. Click **"Create Key"**
5. **Copy the API key immediately** - it's only shown once!

### Managing Existing Keys

**View All Keys:**
- Navigate to `/api-keys/manage`
- See list of all keys with status, permissions, and usage

**View Key Details:**
```bash
GET /api-keys/{key_id}
```

**Update Key Permissions:**
```bash
PUT /api-keys/{key_id}
Content-Type: application/json

{
  "name": "Updated Name",
  "permissions": {
    "team_data_access": true,
    "scouting_data_read": true
  }
}
```

**Delete Key:**
```bash
DELETE /api-keys/{key_id}
```

**Reactivate Expired Key:**
```bash
POST /api-keys/{key_id}/reactivate
```

**View Usage Statistics:**
```bash
GET /api-keys/{key_id}/usage
```

### Testing API Keys

**Quick Test Endpoint:**
```bash
GET /api-keys/test?api_key=sk_live_your_key

# Returns:
{
  "valid": true,
  "key_name": "My API Key",
  "team_number": 1234,
  "permissions": {...}
}
```

---

## Base URL & Endpoints

**Base URL**: `https://your-server.com/api/v1/`

### Available Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/info` | GET | Get API information and key status |
| `/teams` | GET | List teams |
| `/teams/{id}` | GET | Get team details |
| `/events` | GET | List events |
| `/events/{id}` | GET | Get event details |
| `/matches` | GET | List matches |
| `/matches/{id}` | GET | Get match details |
| `/scouting-data` | GET | List scouting data entries |
| `/scouting-data` | POST | Create scouting data entry |
| `/analytics/team-performance` | GET | Get team performance analytics |
| `/sync/status` | GET | Get sync status |
| `/sync/trigger` | POST | Trigger sync operation |
| `/team-lists/do-not-pick` | GET | Get do-not-pick list |
| `/health` | GET | Health check |
| `/all` | GET | Export all team data |

---

## Team Data Endpoints

### GET /api/v1/info

Get API information and current key status.

**Permission Required**: `team_data_access`

#### Response
```json
{
  "success": true,
  "api_version": "1.0",
  "api_key": {
    "id": 1,
    "name": "My API Key",
    "team_number": 1234,
    "permissions": {
      "team_data_access": true,
      "scouting_data_read": true
    },
    "rate_limit_per_hour": 1000,
    "created_at": "2025-01-01T00:00:00",
    "last_used_at": "2025-10-08T12:00:00"
  },
  "server_time": "2025-10-08T12:34:56",
  "endpoints": {
    "teams": "/api/v1/teams",
    "team_details": "/api/v1/teams/{team_id}",
    ...
  }
}
```

---

### GET /api/v1/teams

List all teams belonging to your scouting team.

**Permission Required**: `team_data_access`

#### Query Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `event_id` | integer | Filter by event ID |
| `team_number` | integer | Filter by specific team number |
| `limit` | integer | Max results per page (default: 100, max: 1000) |
| `offset` | integer | Pagination offset (default: 0) |

#### Example Request
```bash
curl -H "Authorization: Bearer sk_live_your_key" \
  "https://your-server.com/api/v1/teams?event_id=1&limit=50"
```

#### Response
```json
{
  "success": true,
  "teams": [
    {
      "id": 1,
      "team_number": 254,
      "team_name": "The Cheesy Poofs",
      "location": "San Jose, CA, USA",
      "scouting_team_number": 1234,
      "events": [
        {"id": 1, "name": "Silicon Valley Regional", "code": "casj"}
      ]
    },
    ...
  ],
  "count": 50,
  "total_count": 150,
  "limit": 50,
  "offset": 0,
  "requesting_team": 1234
}
```

---

### GET /api/v1/teams/{team_id}

Get detailed information about a specific team.

**Permission Required**: `team_data_access`

#### Path Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `team_id` | integer | Team database ID |

#### Example Request
```bash
curl -H "Authorization: Bearer sk_live_your_key" \
  "https://your-server.com/api/v1/teams/1"
```

#### Response
```json
{
  "success": true,
  "team": {
    "id": 1,
    "team_number": 254,
    "team_name": "The Cheesy Poofs",
    "location": "San Jose, CA, USA",
    "scouting_team_number": 1234,
    "events": [
      {"id": 1, "name": "Silicon Valley Regional", "code": "casj"}
    ],
    "scouting_data_count": 42,
    "recent_matches": [
      {
        "id": 10,
        "match_number": 15,
        "match_type": "qual",
        "red_alliance": "[254, 971, 1678]",
        "blue_alliance": "[1323, 2056, 4414]",
        "red_score": 125,
        "blue_score": 98,
        "winner": "red"
      },
      ...
    ]
  }
}
```

---

## Event Data Endpoints

### GET /api/v1/events

List all events that have teams from your scouting team.

**Permission Required**: `team_data_access`

#### Query Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `code` | string | Filter by event code (partial match) |
| `location` | string | Filter by location (partial match) |
| `limit` | integer | Max results per page (default: 100, max: 1000) |
| `offset` | integer | Pagination offset (default: 0) |

#### Example Request
```bash
curl -H "Authorization: Bearer sk_live_your_key" \
  "https://your-server.com/api/v1/events?location=California"
```

#### Response
```json
{
  "success": true,
  "events": [
    {
      "id": 1,
      "name": "Silicon Valley Regional",
      "code": "casj",
      "location": "San Jose, CA, USA",
      "start_date": "2025-03-15",
      "end_date": "2025-03-18",
      "team_count": 48
    },
    ...
  ],
  "count": 10,
  "total_count": 25,
  "limit": 100,
  "offset": 0
}
```

---

### GET /api/v1/events/{event_id}

Get detailed information about a specific event.

**Permission Required**: `team_data_access`

#### Path Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `event_id` | integer | Event database ID |

#### Response
```json
{
  "success": true,
  "event": {
    "id": 1,
    "name": "Silicon Valley Regional",
    "code": "casj",
    "location": "San Jose, CA, USA",
    "start_date": "2025-03-15",
    "end_date": "2025-03-18",
    "team_count": 48,
    "match_count": 120,
    "teams": [
      {"id": 1, "team_number": 254, "team_name": "The Cheesy Poofs"},
      ...
    ],
    "recent_matches": [
      {
        "id": 10,
        "match_number": 15,
        "match_type": "qual",
        "red_alliance": "[254, 971, 1678]",
        "blue_alliance": "[1323, 2056, 4414]",
        "red_score": 125,
        "blue_score": 98,
        "winner": "red"
      },
      ...
    ]
  }
}
```

---

## Match Data Endpoints

### GET /api/v1/matches

List matches from events with your team.

**Permission Required**: `scouting_data_read`

#### Query Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `event_id` | integer | Filter by event ID |
| `match_type` | string | Filter by match type (qual, playoff, final) |
| `team_number` | integer | Filter by team participation |
| `match_number` | integer | Filter by match number |
| `limit` | integer | Max results per page (default: 100, max: 1000) |
| `offset` | integer | Pagination offset (default: 0) |

#### Example Request
```bash
curl -H "Authorization: Bearer sk_live_your_key" \
  "https://your-server.com/api/v1/matches?event_id=1&team_number=254"
```

#### Response
```json
{
  "success": true,
  "matches": [
    {
      "id": 10,
      "match_number": 15,
      "match_type": "qual",
      "event_id": 1,
      "red_alliance": "[254, 971, 1678]",
      "blue_alliance": "[1323, 2056, 4414]",
      "red_score": 125,
      "blue_score": 98,
      "winner": "red",
      "scouting_team_number": 1234
    },
    ...
  ],
  "count": 25,
  "total_count": 120,
  "limit": 100,
  "offset": 0
}
```

---

### GET /api/v1/matches/{match_id}

Get detailed information about a specific match.

**Permission Required**: `scouting_data_read`

#### Response
```json
{
  "success": true,
  "match": {
    "id": 10,
    "match_number": 15,
    "match_type": "qual",
    "event_id": 1,
    "red_alliance": "[254, 971, 1678]",
    "blue_alliance": "[1323, 2056, 4414]",
    "red_score": 125,
    "blue_score": 98,
    "winner": "red",
    "scouting_team_number": 1234,
    "scouting_data_count": 6,
    "scouting_entries": [
      {
        "id": 100,
        "team_id": 1,
        "scout": "John Doe",
        "timestamp": "2025-03-15T14:30:00",
        "scouting_team_number": 1234
      },
      ...
    ]
  }
}
```

---

## Scouting Data Endpoints

### GET /api/v1/scouting-data

List scouting data entries for your team.

**Permission Required**: `scouting_data_read`

#### Query Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `team_id` | integer | Filter by team database ID |
| `match_id` | integer | Filter by match database ID |
| `scout` | string | Filter by scout name (partial match) |
| `limit` | integer | Max results per page (default: 100, max: 1000) |
| `offset` | integer | Pagination offset (default: 0) |

#### Example Request
```bash
curl -H "Authorization: Bearer sk_live_your_key" \
  "https://your-server.com/api/v1/scouting-data?match_id=10"
```

#### Response
```json
{
  "success": true,
  "scouting_data": [
    {
      "id": 100,
      "team_id": 1,
      "match_id": 10,
      "data": {
        "auto_speaker": 3,
        "auto_amp": 1,
        "teleop_speaker": 12,
        "teleop_amp": 4,
        "endgame": "park",
        "notes": "Strong shooter, consistent"
      },
      "scout": "John Doe",
      "timestamp": "2025-03-15T14:30:00",
      "scouting_team_number": 1234
    },
    ...
  ],
  "count": 50,
  "total_count": 500,
  "limit": 100,
  "offset": 0
}
```

---

### POST /api/v1/scouting-data

Create a new scouting data entry.

**Permission Required**: `scouting_data_write`

#### Request Body

```json
{
  "team_id": 1,
  "match_id": 10,
  "data": {
    "auto_speaker": 3,
    "auto_amp": 1,
    "teleop_speaker": 12,
    "teleop_amp": 4,
    "endgame": "park",
    "notes": "Strong shooter, consistent"
  },
  "scout": "John Doe"
}
```

#### Required Fields

- `team_id` (integer): Team database ID
- `match_id` (integer): Match database ID
- `data` (object): Scouting data JSON object
- `scout` (string): Scout name

#### Example Request
```bash
curl -X POST \
  -H "Authorization: Bearer sk_live_your_key" \
  -H "Content-Type: application/json" \
  -d '{"team_id":1,"match_id":10,"data":{"auto_speaker":3},"scout":"John"}' \
  "https://your-server.com/api/v1/scouting-data"
```

#### Response
```json
{
  "success": true,
  "message": "Scouting data created successfully",
  "scouting_data": {
    "id": 101,
    "team_id": 1,
    "match_id": 10,
    "scout": "John Doe",
    "timestamp": "2025-10-08T14:35:22"
  }
}
```

---

## Analytics Endpoints

### GET /api/v1/analytics/team-performance

Get performance analytics for a team.

**Permission Required**: `analytics_access`

#### Query Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `team_id` | integer | One required | Team database ID |
| `team_number` | integer | One required | Team number |
| `event_id` | integer | No | Filter by event |

**Note**: Either `team_id` or `team_number` must be provided.

#### Example Request
```bash
curl -H "Authorization: Bearer sk_live_your_key" \
  "https://your-server.com/api/v1/analytics/team-performance?team_number=254&event_id=1"
```

#### Response
```json
{
  "success": true,
  "analytics": {
    "team_id": 1,
    "team_number": 254,
    "team_name": "The Cheesy Poofs",
    "total_scouting_entries": 42,
    "unique_matches_scouted": 42,
    "data_quality_score": 100,
    "last_scouted": "2025-03-18T16:45:00"
  }
}
```

---

## Sync Operations Endpoints

### GET /api/v1/sync/status

Get current sync status and data counts.

**Permission Required**: `sync_operations`

#### Response
```json
{
  "success": true,
  "sync_status": {
    "team_number": 1234,
    "last_check": "2025-10-08T14:35:22",
    "data_counts": {
      "teams": 150,
      "matches": 1200,
      "scouting_data": 5000,
      "events": 25
    },
    "sync_available": true
  }
}
```

---

### POST /api/v1/sync/trigger

Trigger a sync operation.

**Permission Required**: `sync_operations`

#### Request Body

```json
{
  "type": "full"
}
```

#### Sync Types

- `full`: Full sync of all data
- `teams`: Sync teams only
- `matches`: Sync matches only
- `scouting_data`: Sync scouting data only

#### Response
```json
{
  "success": true,
  "message": "Full sync triggered successfully",
  "sync_id": "sync_1696780000",
  "estimated_completion": "2025-10-08T14:40:22"
}
```

---

## Team Lists Endpoints

### GET /api/v1/team-lists/do-not-pick

Get the "do not pick" list for your team.

**Permission Required**: `team_data_access`

#### Response
```json
{
  "success": true,
  "do_not_pick_list": [
    {
      "id": 1,
      "team_id": 15,
      "team_number": 5555,
      "team_name": "Unreliable Team",
      "reason": "Frequent mechanical failures",
      "timestamp": "2025-03-15T10:00:00"
    },
    ...
  ],
  "count": 3
}
```

---

## Health & Status

### GET /api/v1/health

API health check endpoint for monitoring service availability.

**Permission Required**: `team_data_access`

#### Response
```json
{
  "success": true,
  "status": "healthy",
  "timestamp": "2025-10-08T14:35:22",
  "version": "1.0",
  "team_number": 1234
}
```

---

### GET /api/v1/all

Export all data for your scouting team (administrative use).

**Permission Required**: `team_data_access`

#### Response
```json
{
  "success": true,
  "team_number": 1234,
  "teams": [...],
  "events": [...],
  "matches": [...],
  "scouting_data": [...]
}
```

**Note**: This endpoint returns ALL data for your team and may be large. Use with caution. Excellent for administrative exports and backups.

---

## Server-to-Server Sync API

The Sync API (`/api/sync/`) enables **multi-server deployments** where multiple Obsidian-Scout instances can synchronize data in real-time.

### Use Cases

- **Event Coverage**: Multiple servers at different field locations
- **Redundancy**: Backup server that stays in sync
- **Geographic Distribution**: Servers in different regions
- **Load Balancing**: Distribute load across multiple instances

### Sync API Endpoints

#### GET /api/sync/ping

**Health check for sync server availability.**

```bash
curl https://remote-server.com/api/sync/ping
```

**Response:**
```json
{
  "status": "ok",
  "timestamp": "2025-10-08T14:35:22",
  "version": "1.0.0",
  "server_id": "universal-sync"
}
```

---

#### GET /api/sync/changes

**Get database changes since a specific timestamp for simplified sync.**

**Query Parameters:**
- `since` (required): ISO 8601 timestamp
- `server_id` (optional): Requesting server identifier
- `catchup_mode` (optional): `true` for larger batches during catch-up

```bash
curl "https://remote-server.com/api/sync/changes?since=2025-10-08T12:00:00Z&server_id=server1"
```

**Response:**
```json
{
  "changes": [
    {
      "id": 1,
      "type": "insert",
      "table": "scouting_data",
      "record_id": 123,
      "data": {...},
      "timestamp": "2025-10-08T14:30:00"
    }
  ],
  "count": 1,
  "timestamp": "2025-10-08T14:35:22",
  "server_id": "universal-sync"
}
```

**Catch-Up Mode:**
- Normal: Returns up to 100 changes
- Catch-up: Returns all pending changes (use after disconnection)

---

#### POST /api/sync/receive-changes

**Receive and apply changes from another server.**

**Request Body:**
```json
{
  "changes": [
    {
      "type": "insert",
      "table": "teams",
      "record_id": 456,
      "data": {
        "team_number": 254,
        "team_name": "The Cheesy Poofs"
      }
    }
  ],
  "server_id": "server1",
  "catchup_mode": false
}
```

**Response:**
```json
{
  "success": true,
  "applied_count": 1,
  "timestamp": "2025-10-08T14:35:22",
  "catchup_mode": false
}
```

---

#### GET /api/sync/servers

**Get list of configured sync servers.**

```bash
curl https://your-server.com/api/sync/servers
```

**Response:**
```json
{
  "servers": [
    {
      "id": 1,
      "name": "Field Server 1",
      "host": "192.168.1.100",
      "port": 5000,
      "protocol": "https",
      "is_active": true,
      "last_ping": "2025-10-08T14:30:00",
      "ping_success": true
    }
  ],
  "count": 1
}
```

---

#### POST /api/sync/servers

**Add a new sync server.**

**Request Body:**
```json
{
  "name": "Field Server 2",
  "host": "192.168.1.101",
  "port": 5000,
  "protocol": "https"
}
```

### Sync Configuration

**Automatic Sync:**
Obsidian-Scout includes a **Universal Sync System** that automatically:
- Detects database changes
- Queues changes for replication
- Sends to configured sync servers
- Retries failed transmissions
- Handles catch-up after disconnections

**Manual Sync:**
Use the Admin Panel → Sync Monitor to:
- View sync status
- Trigger manual sync
- Monitor sync queue
- View sync logs

---

## Real-time Replication API

The Real-time API (`/api/realtime/`) provides **immediate database replication** for sub-second synchronization between servers.

### How It Works

1. **Change Detection**: Database operations are captured in real-time
2. **Operation Packaging**: Changes packaged as insert/update/delete operations
3. **Immediate Transmission**: Sent to remote servers instantly
4. **Conflict Resolution**: Timestamps used to resolve conflicts
5. **Loop Prevention**: Replication disabled during application to prevent loops

### Real-time API Endpoints

#### POST /api/realtime/receive

**Receive and apply a real-time database operation from another server.**

**Request Body:**
```json
{
  "operation": {
    "type": "insert",
    "table": "scouting_data",
    "record_id": 789,
    "data": {
      "id": 789,
      "team_id": 1,
      "match_id": 10,
      "data": {"auto_speaker": 3},
      "scout": "John Doe",
      "timestamp": "2025-10-08T14:35:00"
    }
  },
  "source_server_id": "server1"
}
```

**Supported Tables:**
- `users` / `user`
- `scouting_data`
- `matches` / `match`
- `teams` / `team`
- `events` / `event`

**Operation Types:**
- `insert`: Create new record
- `update`: Update existing record
- `delete`: Delete record (soft delete if supported)

**Response:**
```json
{
  "success": true,
  "operation_type": "insert",
  "table": "scouting_data",
  "record_id": 789,
  "timestamp": "2025-10-08T14:35:22"
}
```

---

#### GET /api/realtime/ping

**Health check for real-time replication service.**

```bash
curl https://your-server.com/api/realtime/ping
```

**Response:**
```json
{
  "status": "ok",
  "service": "real-time-replication",
  "timestamp": "2025-10-08T14:35:22"
}
```

### Replication Features

**Automatic Features:**
 **Datetime Field Processing** - Automatic parsing and conversion  
 **Upsert Logic** - Insert if new, update if exists  
 **Soft Deletes** - Preserves records with `is_active=False`  
 **Loop Prevention** - Changes from replication don't re-replicate  
 **Error Recovery** - Automatic rollback on failures  

---

## WebSocket Events

Obsidian-Scout uses **Socket.IO** for real-time collaboration features including chat, strategy drawing, and presence.

### Connection

```javascript
const socket = io('https://your-server.com', {
  transports: ['websocket', 'polling']
});

socket.on('connect', () => {
  console.log('Connected:', socket.id);
});
```

### Chat Events

#### Send Message
```javascript
socket.emit('send_message', {
  message: 'Hello team!',
  channel: 'general',
  recipient: null  // or username for DM
});
```

#### Receive Message
```javascript
socket.on('receive_message', (data) => {
  console.log(`${data.sender}: ${data.message}`);
  // data: { sender, message, channel, timestamp, is_direct }
});
```

#### Join Channel
```javascript
socket.emit('join_channel', {
  channel: 'scouting'
});
```

### Drawing Events

#### Join Drawing Room
```javascript
socket.emit('join_drawing', {
  drawing_id: 'field-2024-001'
});
```

#### Send Drawing Data
```javascript
socket.emit('drawing_data', {
  drawing_id: 'field-2024-001',
  data: {
    type: 'line',
    points: [[100, 100], [200, 200]],
    color: '#FF0000',
    width: 2
  }
});
```

#### Receive Drawing Updates
```javascript
socket.on('drawing_update', (data) => {
  // data: { drawing_id, data, user }
  renderDrawing(data);
});
```

#### Clear Canvas
```javascript
socket.emit('clear_canvas', {
  drawing_id: 'field-2024-001'
});

socket.on('canvas_cleared', (data) => {
  clearCanvas();
});
```

### Presence Events

#### User Join/Leave
```javascript
socket.on('user_joined', (data) => {
  console.log(`${data.username} joined`);
});

socket.on('user_left', (data) => {
  console.log(`${data.username} left`);
});
```

### Data Sync Events

#### Data Updated
```javascript
socket.on('data_updated', (data) => {
  // data: { type, id, action }
  // type: 'team', 'match', 'scouting_data'
  // action: 'created', 'updated', 'deleted'
  refreshData(data.type, data.id);
});
```

---

## Error Codes

The API uses standard HTTP status codes:

| Status Code | Meaning | Description |
|------------|---------|-------------|
| 200 | OK | Request succeeded |
| 201 | Created | Resource created successfully |
| 400 | Bad Request | Invalid request parameters |
| 401 | Unauthorized | Invalid or missing API key |
| 403 | Forbidden | Insufficient permissions |
| 404 | Not Found | Resource not found or not accessible |
| 429 | Too Many Requests | Rate limit exceeded |
| 500 | Internal Server Error | Server error occurred |

### Error Response Format

```json
{
  "error": "Detailed error message",
  "code": "ERROR_CODE"
}
```

### Common Error Codes

| Code | Description |
|-------------------|-------------|
| `INVALID_API_KEY` | API key is invalid or expired |
| `INSUFFICIENT_PERMISSIONS` | API key lacks required permission |
| `RATE_LIMIT_EXCEEDED` | Too many requests |

---

## Rate Limiting

Each API key has a **configurable rate limit** to prevent abuse and ensure fair resource allocation.

### Rate Limit Configuration

- **Default Limit**: 1000 requests per hour
- **Configurable**: Can be adjusted per API key
- **Window**: Rolling 1-hour window
- **Scope**: Per API key (not per endpoint)

### Rate Limit Tracking

The API tracks:
-  **Requests per hour**: Count within rolling window
-  **Current usage**: Real-time counter
-  **Last request time**: For usage statistics
-  **Time until reset**: When limit resets

### When Rate Limited

**Response (HTTP 429):**
```json
{
  "error": "Rate limit exceeded. Current: 1001/1000 requests per hour",
  "code": "RATE_LIMIT_EXCEEDED",
  "retry_after": 3600
}
```

### Best Practices for Rate Limits

#### 1. Implement Caching
```python
import time
from functools import lru_cache

@lru_cache(maxsize=100)
def get_teams_cached(api_key, event_id=None):
    # Cache results for repeated calls
    return api_get_teams(api_key, event_id)

# Clear cache periodically
get_teams_cached.cache_clear()
```

#### 2. Use Efficient Pagination
```python
# Bad: Making many small requests
for i in range(0, 1000, 10):
    get_teams(limit=10, offset=i)  # 100 requests!

# Good: Using larger page sizes
for i in range(0, 1000, 100):
    get_teams(limit=100, offset=i)  # 10 requests
```

#### 3. Implement Exponential Backoff
```python
def api_call_with_backoff(url, headers, max_retries=3):
    for attempt in range(max_retries):
        response = requests.get(url, headers=headers)
        
        if response.status_code == 429:
            wait_time = 2 ** attempt  # 1s, 2s, 4s
            print(f"Rate limited, waiting {wait_time}s...")
            time.sleep(wait_time)
            continue
        
        return response
    
    raise Exception("Max retries exceeded")
```

#### 4. Monitor Your Usage
```python
# Check current usage
response = requests.get(
    f"https://your-server.com/api-keys/{key_id}/usage",
    headers=headers
)

usage = response.json()
print(f"Used: {usage['requests_last_hour']}/{usage['rate_limit_per_hour']}")
```

#### 5. Batch Operations
```python
# Bad: Individual requests for each record
for record in records:
    create_scouting_data(record)  # Many requests

# Good: Batch where possible
batch_create_scouting_data(records)  # One request
```

### Increasing Rate Limits

If you need higher limits:
1. Navigate to **Admin Panel** → **API Keys**
2. Edit your API key
3. Increase **Rate Limit Per Hour**
4. Save changes

**Recommended Limits:**
- **Manual Testing**: 100-500 requests/hour
- **Automated Tools**: 1000-2000 requests/hour
- **High-Volume Apps**: 5000+ requests/hour (monitor server load)

---

## Code Examples

### Python Examples

#### Basic Setup

```python
import requests

API_KEY = "sk_live_your_api_key_here"
BASE_URL = "https://your-server.com/api/v1"

headers = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json"
}

# Get teams
response = requests.get(f"{BASE_URL}/teams", headers=headers)
teams = response.json()

print(f"Found {teams['count']} teams")
for team in teams['teams']:
    print(f"Team {team['team_number']}: {team['team_name']}")

# Create scouting data
scouting_data = {
    "team_id": 1,
    "match_id": 10,
    "data": {
        "auto_speaker": 3,
        "teleop_speaker": 12
    },
    "scout": "Python Script"
}

response = requests.post(
    f"{BASE_URL}/scouting-data",
    headers=headers,
    json=scouting_data
)

print(response.json())
```

### JavaScript Example

```javascript
const API_KEY = 'sk_live_your_api_key_here';
const BASE_URL = 'https://your-server.com/api/v1';

const headers = {
    'Authorization': `Bearer ${API_KEY}`,
    'Content-Type': 'application/json'
};

// Get matches
fetch(`${BASE_URL}/matches?event_id=1`, { headers })
    .then(response => response.json())
    .then(data => {
        console.log(`Found ${data.count} matches`);
        data.matches.forEach(match => {
            console.log(`Match ${match.match_number}: ${match.winner} won`);
        });
    });

// Get team performance
fetch(`${BASE_URL}/analytics/team-performance?team_number=254`, { headers })
    .then(response => response.json())
    .then(data => {
        console.log('Team Performance:', data.analytics);
    });
```

### cURL Examples

```bash
# Get API info
curl -H "Authorization: Bearer sk_live_your_key" \
  https://your-server.com/api/v1/info

# Get teams with filters
curl -H "Authorization: Bearer sk_live_your_key" \
  "https://your-server.com/api/v1/teams?event_id=1&limit=10"

# Get scouting data
curl -H "Authorization: Bearer sk_live_your_key" \
  "https://your-server.com/api/v1/scouting-data?match_id=10"

# Create scouting data
curl -X POST \
  -H "Authorization: Bearer sk_live_your_key" \
  -H "Content-Type: application/json" \
  -d '{
    "team_id": 1,
    "match_id": 10,
    "data": {"auto_speaker": 3, "teleop_speaker": 12},
    "scout": "API User"
  }' \
  https://your-server.com/api/v1/scouting-data

# Trigger sync
curl -X POST \
  -H "Authorization: Bearer sk_live_your_key" \
  -H "Content-Type: application/json" \
  -d '{"type": "full"}' \
  https://your-server.com/api/v1/sync/trigger
```

---

## Best Practices

### Security

####  DO
- **Use HTTPS** in production environments
- **Store API keys securely** (environment variables, key vaults)
- **Use Authorization header** instead of query parameters
- **Rotate keys periodically** (every 90 days recommended)
- **Create separate keys** for different applications
- **Set minimum required permissions** for each key
- **Monitor key usage** for suspicious activity
- **Delete unused keys** immediately

####  DON'T
- **Don't commit keys to version control** (.env files, config files)
- **Don't share keys** between teams or applications
- **Don't use query parameters** for API keys in production
- **Don't log API keys** in application logs
- **Don't give excessive permissions** to keys
- **Don't ignore expired keys** - delete them

### Performance

#### Optimize Requests
```python
# Bad: Making many sequential requests
for team_id in team_ids:
    team = get_team(team_id)  # N requests

# Good: Use filters to get multiple teams
teams = get_teams(event_id=event_id)  # 1 request
```

#### Use Pagination Wisely
```python
# Good: Fetch what you need
teams = get_teams(limit=50, offset=0)

# Better: Process in chunks
def get_all_teams():
    offset = 0
    limit = 100
    all_teams = []
    
    while True:
        teams = get_teams(limit=limit, offset=offset)
        if not teams['teams']:
            break
        
        all_teams.extend(teams['teams'])
        offset += limit
    
    return all_teams
```

#### Cache Strategically
```python
import time

class APICache:
    def __init__(self, ttl=300):  # 5 minute TTL
        self.cache = {}
        self.ttl = ttl
    
    def get(self, key):
        if key in self.cache:
            data, timestamp = self.cache[key]
            if time.time() - timestamp < self.ttl:
                return data
        return None
    
    def set(self, key, data):
        self.cache[key] = (data, time.time())

cache = APICache(ttl=300)

def get_teams_cached():
    cached = cache.get('teams')
    if cached:
        return cached
    
    teams = api_get_teams()
    cache.set('teams', teams)
    return teams
```

### Error Handling

#### Robust Error Handling
```python
import requests
import logging
from tenacity import retry, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)

class APIError(Exception):
    def __init__(self, status_code, message, code=None):
        self.status_code = status_code
        self.message = message
        self.code = code
        super().__init__(self.message)

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10)
)
def api_request(method, endpoint, **kwargs):
    """Make API request with automatic retry and error handling"""
    try:
        response = requests.request(method, endpoint, **kwargs)
        
        if response.status_code == 200:
            return response.json()
        elif response.status_code == 201:
            return response.json()
        elif response.status_code == 401:
            raise APIError(401, "Authentication failed")
        elif response.status_code == 403:
            raise APIError(403, "Permission denied")
        elif response.status_code == 404:
            raise APIError(404, "Resource not found")
        elif response.status_code == 429:
            logger.warning("Rate limited, retrying...")
            raise APIError(429, "Rate limit exceeded")
        else:
            error_data = response.json()
            raise APIError(
                response.status_code,
                error_data.get('error', 'Unknown error'),
                error_data.get('code')
            )
    
    except requests.exceptions.ConnectionError:
        logger.error("Connection failed")
        raise
    except requests.exceptions.Timeout:
        logger.error("Request timed out")
        raise
```

### Data Validation

#### Validate Before Sending
```python
from jsonschema import validate, ValidationError

# Define schema
scouting_schema = {
    "type": "object",
    "properties": {
        "team_id": {"type": "integer"},
        "match_id": {"type": "integer"},
        "data": {"type": "object"},
        "scout": {"type": "string"}
    },
    "required": ["team_id", "match_id", "data", "scout"]
}

def create_scouting_data(data):
    # Validate first
    try:
        validate(instance=data, schema=scouting_schema)
    except ValidationError as e:
        raise ValueError(f"Invalid data: {e.message}")
    
    # Then send
    return api_post('/api/v1/scouting-data', data)
```

### Monitoring and Logging

#### Track API Usage
```python
import logging
import time
from functools import wraps

logger = logging.getLogger(__name__)

def track_api_call(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        start = time.time()
        
        try:
            result = func(*args, **kwargs)
            duration = time.time() - start
            
            logger.info(
                f"API call: {func.__name__}, "
                f"duration: {duration:.2f}s, "
                f"status: success"
            )
            
            return result
        
        except Exception as e:
            duration = time.time() - start
            
            logger.error(
                f"API call: {func.__name__}, "
                f"duration: {duration:.2f}s, "
                f"status: failed, "
                f"error: {str(e)}"
            )
            
            raise
    
    return wrapper

@track_api_call
def get_teams():
    return api_request('GET', '/api/v1/teams')
```

---

## Additional Resources

### Related Documentation

- **CONNECTIONS_AND_SYNC.md** - Complete sync system guide
- **USER_ROLES_AND_PERMISSIONS.md** - User roles and access control
- **ADMIN_GUIDE.md** - Administrative operations and management
- **TROUBLESHOOTING.md** - Common issues and solutions
- **DUAL_API_README.md** - FIRST API and The Blue Alliance integration

### Integration Examples

**Python SDK Example:**
```python
# Example: Complete integration with error handling
import requests
from typing import Dict, List, Optional

class ObsidianScoutAPI:
    def __init__(self, base_url: str, api_key: str):
        self.base_url = base_url.rstrip('/')
        self.api_key = api_key
        self.session = requests.Session()
        self.session.headers.update({
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json'
        })
    
    def get_teams(self, event_id: Optional[int] = None, 
                  limit: int = 100, offset: int = 0) -> Dict:
        """Get teams with optional filtering"""
        params = {'limit': limit, 'offset': offset}
        if event_id:
            params['event_id'] = event_id
        
        response = self.session.get(
            f'{self.base_url}/api/v1/teams',
            params=params
        )
        response.raise_for_status()
        return response.json()
    
    def create_scouting_data(self, team_id: int, match_id: int,
                            data: Dict, scout: str) -> Dict:
        """Create new scouting data entry"""
        payload = {
            'team_id': team_id,
            'match_id': match_id,
            'data': data,
            'scout': scout
        }
        
        response = self.session.post(
            f'{self.base_url}/api/v1/scouting-data',
            json=payload
        )
        response.raise_for_status()
        return response.json()
    
    def get_team_analytics(self, team_number: int, 
                           event_id: Optional[int] = None) -> Dict:
        """Get team performance analytics"""
        params = {'team_number': team_number}
        if event_id:
            params['event_id'] = event_id
        
        response = self.session.get(
            f'{self.base_url}/api/v1/analytics/team-performance',
            params=params
        )
        response.raise_for_status()
        return response.json()

# Usage
api = ObsidianScoutAPI('https://your-server.com', 'sk_live_your_key')
teams = api.get_teams(event_id=1)
analytics = api.get_team_analytics(team_number=254)
```

**JavaScript/Node.js Example:**
```javascript
// Example: Complete Node.js integration
const axios = require('axios');

class ObsidianScoutAPI {
  constructor(baseURL, apiKey) {
    this.client = axios.create({
      baseURL: baseURL,
      headers: {
        'Authorization': `Bearer ${apiKey}`,
        'Content-Type': 'application/json'
      }
    });
  }
  
  async getTeams(eventId = null, limit = 100, offset = 0) {
    const params = { limit, offset };
    if (eventId) params.event_id = eventId;
    
    const response = await this.client.get('/api/v1/teams', { params });
    return response.data;
  }
  
  async createScoutingData(teamId, matchId, data, scout) {
    const payload = {
      team_id: teamId,
      match_id: matchId,
      data: data,
      scout: scout
    };
    
    const response = await this.client.post('/api/v1/scouting-data', payload);
    return response.data;
  }
  
  async getTeamAnalytics(teamNumber, eventId = null) {
    const params = { team_number: teamNumber };
    if (eventId) params.event_id = eventId;
    
    const response = await this.client.get(
      '/api/v1/analytics/team-performance',
      { params }
    );
    return response.data;
  }
}

// Usage
const api = new ObsidianScoutAPI('https://your-server.com', 'sk_live_your_key');

(async () => {
  try {
    const teams = await api.getTeams(1);
    console.log(`Found ${teams.count} teams`);
    
    const analytics = await api.getTeamAnalytics(254);
    console.log('Team Analytics:', analytics.analytics);
  } catch (error) {
    console.error('API Error:', error.response?.data || error.message);
  }
})();
```

### Quick Reference

**Most Common Endpoints:**
```bash
# Get API info and check key
GET /api/v1/info

# List teams
GET /api/v1/teams?event_id=1&limit=50

# Get specific team
GET /api/v1/teams/123

# List matches
GET /api/v1/matches?event_id=1&team_number=254

# Get scouting data
GET /api/v1/scouting-data?match_id=10

# Create scouting data
POST /api/v1/scouting-data
Body: {"team_id":1,"match_id":10,"data":{...},"scout":"Name"}

# Get team analytics
GET /api/v1/analytics/team-performance?team_number=254

# Export all team data
GET /api/v1/all
```

### Testing Tools

**Postman Collection:**
1. Import Obsidian-Scout API collection
2. Set environment variables:
   - `base_url`: Your server URL
   - `api_key`: Your API key
3. Run requests or full collection tests

**cURL Test Script:**
```bash
#!/bin/bash

API_KEY="sk_live_your_key_here"
BASE_URL="https://your-server.com"

# Test API connectivity
echo "Testing API connectivity..."
curl -H "Authorization: Bearer $API_KEY" \
  "$BASE_URL/api/v1/health"

# Get API info
echo -e "\n\nGetting API info..."
curl -H "Authorization: Bearer $API_KEY" \
  "$BASE_URL/api/v1/info"

# Get teams
echo -e "\n\nGetting teams..."
curl -H "Authorization: Bearer $API_KEY" \
  "$BASE_URL/api/v1/teams?limit=5"
```

### Support and Community

**Need Help?**
- **GitHub Repository**: https://github.com/steveandjeff999/Obsidianscout
- **Issues**: Report bugs and request features on GitHub Issues
- **Discussions**: Ask questions in GitHub Discussions
- **Wiki**: Additional documentation and community guides

**Application Version**: 1.0.2.0  
**API Version**: 1.0  
**Last Updated**: October 8, 2025

---

** Happy Scouting!**  
This documentation covers all current API features. For updates, check the GitHub repository and CHANGELOG.txt.

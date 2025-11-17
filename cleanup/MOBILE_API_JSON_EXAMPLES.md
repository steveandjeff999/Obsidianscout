# Mobile API JSON Examples

This document provides JSON request/response examples for integrating with the Obsidian Scout mobile API. All authenticated endpoints require a Bearer token in the Authorization header.

## Table of Contents
- [Authentication](#authentication)
- [Alliance Selection](#alliance-selection)
- [Match Strategy](#match-strategy)
- [Team Analytics & Graphs](#team-analytics--graphs)
- [Scouting Data](#scouting-data)
- [Common Data Models](#common-data-models)

---

## Authentication

### Login
**Endpoint:** `POST /api/mobile/auth/login`

**Request:**
```json
{
  "username": "scout123",
  "password": "myPassword123"
}
```

**Alternative Request (with team number):**
```json
{
  "username": "scout123",
  "password": "myPassword123",
  "team_number": 5454
}
```

**Response:**
```json
{
  "success": true,
  "token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "user": {
    "id": 42,
    "username": "scout123",
    "team_number": 5454,
    "roles": ["scout", "analytics"],
    "profile_picture": "img/avatars/default.png"
  },
  "expires_at": "2025-10-25T12:00:00Z"
}
```

### Using the Token
All subsequent requests must include the token in the Authorization header:
```
Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
```

---

## Alliance Selection

### Get Alliance Selections
**Endpoint:** `GET /api/mobile/alliances?event_id={event_id}`

**Headers:**
```
Authorization: Bearer YOUR_TOKEN_HERE
```

**Response:**
```json
{
  "success": true,
  "alliances": [
    {
      "id": 1,
      "alliance_number": 1,
      "captain": {
        "team_id": 15,
        "team_number": 5454,
        "team_name": "The Bionics",
        "metrics": {
          "total_points": 125.5,
          "auto_points": 35.2,
          "teleop_points": 75.8,
          "endgame_points": 14.5,
          "consistency": 0.87
        }
      },
      "first_pick": {
        "team_id": 23,
        "team_number": 1234,
        "team_name": "Team Name",
        "metrics": {
          "total_points": 98.3,
          "auto_points": 25.0,
          "teleop_points": 60.5,
          "endgame_points": 12.8,
          "consistency": 0.82
        }
      },
      "second_pick": {
        "team_id": 47,
        "team_number": 5678,
        "team_name": "Another Team",
        "metrics": {
          "total_points": 87.9,
          "auto_points": 20.5,
          "teleop_points": 55.4,
          "endgame_points": 12.0,
          "consistency": 0.79
        }
      },
      "third_pick": null,
      "alliance_total_points": 311.7,
      "event_id": 5
    },
    {
      "id": 2,
      "alliance_number": 2,
      "captain": {
        "team_id": 18,
        "team_number": 9999,
        "team_name": "Top Team",
        "metrics": {
          "total_points": 142.0,
          "auto_points": 40.0,
          "teleop_points": 85.0,
          "endgame_points": 17.0,
          "consistency": 0.92
        }
      },
      "first_pick": null,
      "second_pick": null,
      "third_pick": null,
      "alliance_total_points": 142.0,
      "event_id": 5
    }
  ],
  "event": {
    "id": 5,
    "name": "Colorado Regional",
    "code": "CALA",
    "location": "Denver, CO"
  },
  "count": 2
}
```

### Update Alliance Selection
**Endpoint:** `POST /api/mobile/alliances/update`

**Headers:**
```
Authorization: Bearer YOUR_TOKEN_HERE
Content-Type: application/json
```

**Request:**
```json
{
  "alliance_id": 1,
  "event_id": 5,
  "captain": 5454,
  "first_pick": 1234,
  "second_pick": 5678,
  "third_pick": null
}
```

**Response:**
```json
{
  "success": true,
  "message": "Alliance updated successfully",
  "alliance": {
    "id": 1,
    "alliance_number": 1,
    "captain": 5454,
    "first_pick": 1234,
    "second_pick": 5678,
    "third_pick": null,
    "event_id": 5
  }
}
```

### Get Team Recommendations
**Endpoint:** `GET /api/mobile/alliances/recommendations?event_id={event_id}&exclude_teams=5454,1234`

**Headers:**
```
Authorization: Bearer YOUR_TOKEN_HERE
```

**Response:**
```json
{
  "success": true,
  "recommendations": [
    {
      "team_id": 23,
      "team_number": 9999,
      "team_name": "Top Team",
      "rank": 1,
      "metrics": {
        "total_points": 142.0,
        "auto_points": 40.0,
        "teleop_points": 85.0,
        "endgame_points": 17.0,
        "consistency": 0.92,
        "match_count": 12
      },
      "strengths": ["High scoring", "Consistent auto", "Reliable endgame"],
      "concerns": [],
      "recommended_role": "first_pick"
    },
    {
      "team_id": 47,
      "team_number": 5678,
      "team_name": "Great Team",
      "rank": 2,
      "metrics": {
        "total_points": 125.5,
        "auto_points": 35.2,
        "teleop_points": 75.8,
        "endgame_points": 14.5,
        "consistency": 0.87,
        "match_count": 11
      },
      "strengths": ["Strong teleop", "Good defense"],
      "concerns": ["Lower auto performance"],
      "recommended_role": "first_pick"
    }
  ],
  "do_not_pick": [
    {
      "team_id": 89,
      "team_number": 1111,
      "team_name": "Problem Team",
      "reason": "Consistently breaks down during matches"
    }
  ],
  "avoid_list": [
    {
      "team_id": 92,
      "team_number": 2222,
      "team_name": "Risky Team",
      "reason": "Unreliable autonomous"
    }
  ],
  "count": 2
}
```

### Add Team to Do Not Pick List
**Endpoint:** `POST /api/mobile/alliances/do-not-pick`

**Headers:**
```
Authorization: Bearer YOUR_TOKEN_HERE
Content-Type: application/json
```

**Request:**
```json
{
  "team_id": 89,
  "event_id": 5,
  "reason": "Robot consistently breaks down during matches"
}
```

**Response:**
```json
{
  "success": true,
  "message": "Team added to Do Not Pick list",
  "entry": {
    "id": 15,
    "team_id": 89,
    "team_number": 1111,
    "event_id": 5,
    "reason": "Robot consistently breaks down during matches",
    "timestamp": "2025-10-18T10:30:00Z"
  }
}
```

---

## Match Strategy

### Get Match Strategy Analysis
**Endpoint:** `GET /api/mobile/matches/{match_id}/strategy`

**Headers:**
```
Authorization: Bearer YOUR_TOKEN_HERE
```

**Response:**
```json
{
  "success": true,
  "match": {
    "id": 42,
    "match_number": 15,
    "match_type": "Qualification",
    "event_id": 5,
    "scheduled_time": "2025-10-18T14:30:00Z",
    "predicted_time": "2025-10-18T14:35:00Z"
  },
  "red_alliance": {
    "teams": [5454, 1234, 5678],
    "predicted_score": 145.2,
    "win_probability": 0.62,
    "team_details": [
      {
        "team_number": 5454,
        "team_name": "The Bionics",
        "position": 1,
        "role": "primary_scorer",
        "metrics": {
          "total_points": 125.5,
          "auto_points": 35.2,
          "teleop_points": 75.8,
          "endgame_points": 14.5,
          "consistency": 0.87
        },
        "recent_performance": [120, 130, 125, 122, 128],
        "strengths": ["High teleop scoring", "Consistent endgame"],
        "weaknesses": []
      },
      {
        "team_number": 1234,
        "team_name": "Team Name",
        "position": 2,
        "role": "supporting_scorer",
        "metrics": {
          "total_points": 98.3,
          "auto_points": 25.0,
          "teleop_points": 60.5,
          "endgame_points": 12.8,
          "consistency": 0.82
        },
        "recent_performance": [95, 102, 98, 97, 100],
        "strengths": ["Good auto", "Reliable"],
        "weaknesses": ["Lower scoring capacity"]
      },
      {
        "team_number": 5678,
        "team_name": "Another Team",
        "position": 3,
        "role": "defense",
        "metrics": {
          "total_points": 87.9,
          "auto_points": 20.5,
          "teleop_points": 55.4,
          "endgame_points": 12.0,
          "consistency": 0.79
        },
        "recent_performance": [85, 90, 88, 87, 92],
        "strengths": ["Good defense"],
        "weaknesses": ["Inconsistent scoring"]
      }
    ]
  },
  "blue_alliance": {
    "teams": [9999, 2222, 3333],
    "predicted_score": 132.8,
    "win_probability": 0.38,
    "team_details": [
      {
        "team_number": 9999,
        "team_name": "Top Team",
        "position": 1,
        "role": "primary_scorer",
        "metrics": {
          "total_points": 142.0,
          "auto_points": 40.0,
          "teleop_points": 85.0,
          "endgame_points": 17.0,
          "consistency": 0.92
        },
        "recent_performance": [140, 145, 138, 144, 142],
        "strengths": ["Highest scorer", "Very consistent"],
        "weaknesses": []
      },
      {
        "team_number": 2222,
        "team_name": "Mid Team",
        "position": 2,
        "role": "supporting_scorer",
        "metrics": {
          "total_points": 78.5,
          "auto_points": 18.0,
          "teleop_points": 50.5,
          "endgame_points": 10.0,
          "consistency": 0.68
        },
        "recent_performance": [75, 82, 70, 80, 78],
        "strengths": [],
        "weaknesses": ["Inconsistent", "Lower scoring"]
      },
      {
        "team_number": 3333,
        "team_name": "Weak Team",
        "position": 3,
        "role": "minimal_contribution",
        "metrics": {
          "total_points": 45.2,
          "auto_points": 10.0,
          "teleop_points": 30.2,
          "endgame_points": 5.0,
          "consistency": 0.55
        },
        "recent_performance": [40, 50, 42, 48, 45],
        "strengths": [],
        "weaknesses": ["Low scoring", "Very inconsistent"]
      }
    ]
  },
  "strategy_recommendations": {
    "red_alliance": {
      "focus": "Capitalize on teleop scoring advantage",
      "auto_strategy": "Team 5454 should focus on high-value targets, 1234 provides support",
      "teleop_strategy": "Team 5454 primary scorer, 1234 supporting, 5678 on defense",
      "endgame_strategy": "All teams capable of consistent endgame, coordinate timing",
      "key_matchups": [
        "5454 vs 9999 - scoring duel, push for efficiency",
        "5678 should defend 9999 to reduce their impact"
      ]
    },
    "blue_alliance": {
      "focus": "Rely heavily on 9999 performance, protect their scoring",
      "auto_strategy": "9999 must maximize auto, others provide minimal contribution",
      "teleop_strategy": "9999 primary scorer, others stay out of the way",
      "endgame_strategy": "9999 reliable, 2222 and 3333 unpredictable",
      "key_matchups": [
        "9999 vs 5454 - critical matchup for blue",
        "Avoid defense from 5678 on 9999"
      ]
    }
  },
  "simulation_results": {
    "simulations_run": 1000,
    "red_wins": 620,
    "blue_wins": 380,
    "red_win_probability": 0.62,
    "blue_win_probability": 0.38,
    "score_distribution": {
      "red_mean": 145.2,
      "red_std": 18.5,
      "red_min": 95,
      "red_max": 185,
      "blue_mean": 132.8,
      "blue_std": 22.3,
      "blue_min": 75,
      "blue_max": 195
    }
  },
  "notes": "Red alliance has better depth and consistency. Blue relies heavily on team 9999.",
  "last_updated": "2025-10-18T12:00:00Z"
}
```

### Get All Match Strategies for Event
**Endpoint:** `GET /api/mobile/matches/strategies?event_id={event_id}`

**Headers:**
```
Authorization: Bearer YOUR_TOKEN_HERE
```

**Response:**
```json
{
  "success": true,
  "event": {
    "id": 5,
    "name": "Colorado Regional",
    "code": "CALA"
  },
  "strategies": [
    {
      "match_id": 42,
      "match_number": 15,
      "match_type": "Qualification",
      "scheduled_time": "2025-10-18T14:30:00Z",
      "red_alliance": [5454, 1234, 5678],
      "blue_alliance": [9999, 2222, 3333],
      "red_predicted_score": 145.2,
      "blue_predicted_score": 132.8,
      "red_win_probability": 0.62,
      "has_detailed_strategy": true
    },
    {
      "match_id": 43,
      "match_number": 16,
      "match_type": "Qualification",
      "scheduled_time": "2025-10-18T14:40:00Z",
      "red_alliance": [1111, 4444, 7777],
      "blue_alliance": [5454, 8888, 2222],
      "red_predicted_score": 120.5,
      "blue_predicted_score": 135.8,
      "red_win_probability": 0.42,
      "has_detailed_strategy": true
    }
  ],
  "count": 2
}
```

### Save Strategy Drawing
**Endpoint:** `POST /api/mobile/matches/{match_id}/strategy/drawing`

**Headers:**
```
Authorization: Bearer YOUR_TOKEN_HERE
Content-Type: application/json
```

**Request:**
```json
{
  "match_id": 42,
  "drawing_data": {
    "version": "1.0",
    "background_image": "field_2025.png",
    "objects": [
      {
        "type": "path",
        "id": "path_1",
        "color": "#FF0000",
        "width": 3,
        "points": [
          {"x": 100, "y": 150},
          {"x": 200, "y": 250},
          {"x": 300, "y": 200}
        ],
        "label": "Team 5454 auto path"
      },
      {
        "type": "arrow",
        "id": "arrow_1",
        "color": "#0000FF",
        "width": 2,
        "start": {"x": 150, "y": 300},
        "end": {"x": 400, "y": 350},
        "label": "Game piece route"
      },
      {
        "type": "marker",
        "id": "marker_1",
        "color": "#00FF00",
        "position": {"x": 500, "y": 400},
        "icon": "target",
        "label": "Scoring target"
      },
      {
        "type": "text",
        "id": "text_1",
        "position": {"x": 250, "y": 100},
        "text": "Primary scoring zone",
        "fontSize": 16,
        "color": "#000000"
      }
    ]
  }
}
```

**Response:**
```json
{
  "success": true,
  "message": "Strategy drawing saved",
  "match_id": 42,
  "last_updated": "2025-10-18T12:15:00Z"
}
```

---

## Team Analytics & Graphs

### Get Team Performance Metrics
**Endpoint:** `GET /api/mobile/teams/{team_id}/metrics?event_id={event_id}`

**Headers:**
```
Authorization: Bearer YOUR_TOKEN_HERE
```

**Response:**
```json
{
  "success": true,
  "team": {
    "id": 15,
    "team_number": 5454,
    "team_name": "The Bionics",
    "location": "Parker, CO"
  },
  "event": {
    "id": 5,
    "name": "Colorado Regional",
    "code": "CALA"
  },
  "metrics": {
    "match_count": 12,
    "total_points": 125.5,
    "total_points_std": 15.2,
    "auto_points": 35.2,
    "auto_points_std": 5.8,
    "teleop_points": 75.8,
    "teleop_points_std": 10.5,
    "endgame_points": 14.5,
    "endgame_points_std": 3.2,
    "consistency": 0.87,
    "win_rate": 0.75,
    "custom_metrics": {
      "accuracy": 0.82,
      "gamepieces_per_match": 18.5,
      "scoring_frequency": 6.7,
      "defense_rating": 3.8
    }
  },
  "match_history": [
    {
      "match_id": 10,
      "match_number": 1,
      "match_type": "Qualification",
      "alliance": "red",
      "total_points": 120,
      "auto_points": 33,
      "teleop_points": 72,
      "endgame_points": 15,
      "won": true
    },
    {
      "match_id": 15,
      "match_number": 3,
      "match_type": "Qualification",
      "alliance": "blue",
      "total_points": 130,
      "auto_points": 38,
      "teleop_points": 77,
      "endgame_points": 15,
      "won": true
    },
    {
      "match_id": 20,
      "match_number": 5,
      "match_type": "Qualification",
      "alliance": "red",
      "total_points": 125,
      "auto_points": 35,
      "teleop_points": 76,
      "endgame_points": 14,
      "won": false
    }
  ],
  "trends": {
    "improving": ["teleop_points", "consistency"],
    "declining": [],
    "stable": ["auto_points", "endgame_points"]
  },
  "ranking": {
    "overall": 3,
    "by_total_points": 3,
    "by_auto_points": 5,
    "by_consistency": 2,
    "total_teams": 48
  }
}
```

### Get Multi-Team Graph Data
**Endpoint:** `POST /api/mobile/graphs/compare`

**Headers:**
```
Authorization: Bearer YOUR_TOKEN_HERE
Content-Type: application/json
```

**Request:**
```json
{
  "team_numbers": [5454, 1234, 9999, 5678],
  "event_id": 5,
  "metric": "total_points",
  "graph_types": ["line", "bar", "radar"],
  "data_view": "averages"
}
```

**Response:**
```json
{
  "success": true,
  "event": {
    "id": 5,
    "name": "Colorado Regional",
    "code": "CALA"
  },
  "metric": "total_points",
  "metric_display_name": "Total Points",
  "data_view": "averages",
  "teams": [
    {
      "team_number": 5454,
      "team_name": "The Bionics",
      "color": "#FF6384",
      "value": 125.5,
      "std_dev": 15.2,
      "match_count": 12
    },
    {
      "team_number": 1234,
      "team_name": "Team Name",
      "color": "#36A2EB",
      "value": 98.3,
      "std_dev": 18.5,
      "match_count": 11
    },
    {
      "team_number": 9999,
      "team_name": "Top Team",
      "color": "#FFCE56",
      "value": 142.0,
      "std_dev": 12.8,
      "match_count": 12
    },
    {
      "team_number": 5678,
      "team_name": "Another Team",
      "color": "#4BC0C0",
      "value": 87.9,
      "std_dev": 20.3,
      "match_count": 10
    }
  ],
  "graphs": {
    "line": {
      "type": "line",
      "labels": ["Match 1", "Match 2", "Match 3", "Match 4", "Match 5", "Match 6", "Match 7", "Match 8", "Match 9", "Match 10", "Match 11", "Match 12"],
      "datasets": [
        {
          "label": "5454 - The Bionics",
          "data": [120, 130, 125, 122, 128, 132, 124, 120, 135, 125, 118, 127],
          "borderColor": "#FF6384",
          "backgroundColor": "rgba(255, 99, 132, 0.2)",
          "tension": 0.4
        },
        {
          "label": "1234 - Team Name",
          "data": [95, 102, 98, 97, 100, 105, 92, 95, 110, 98, 93, null],
          "borderColor": "#36A2EB",
          "backgroundColor": "rgba(54, 162, 235, 0.2)",
          "tension": 0.4
        },
        {
          "label": "9999 - Top Team",
          "data": [140, 145, 138, 144, 142, 148, 135, 140, 150, 142, 138, 145],
          "borderColor": "#FFCE56",
          "backgroundColor": "rgba(255, 206, 86, 0.2)",
          "tension": 0.4
        },
        {
          "label": "5678 - Another Team",
          "data": [85, 90, 88, 87, 92, 95, 82, 89, 92, 78, null, null],
          "borderColor": "#4BC0C0",
          "backgroundColor": "rgba(75, 192, 192, 0.2)",
          "tension": 0.4
        }
      ]
    },
    "bar": {
      "type": "bar",
      "labels": ["5454", "1234", "9999", "5678"],
      "datasets": [
        {
          "label": "Average Total Points",
          "data": [125.5, 98.3, 142.0, 87.9],
          "backgroundColor": ["#FF6384", "#36A2EB", "#FFCE56", "#4BC0C0"]
        }
      ]
    },
    "radar": {
      "type": "radar",
      "labels": ["Total Points", "Auto Points", "Teleop Points", "Endgame Points", "Consistency"],
      "datasets": [
        {
          "label": "5454 - The Bionics",
          "data": [125.5, 35.2, 75.8, 14.5, 87],
          "borderColor": "#FF6384",
          "backgroundColor": "rgba(255, 99, 132, 0.2)"
        },
        {
          "label": "1234 - Team Name",
          "data": [98.3, 25.0, 60.5, 12.8, 82],
          "borderColor": "#36A2EB",
          "backgroundColor": "rgba(54, 162, 235, 0.2)"
        },
        {
          "label": "9999 - Top Team",
          "data": [142.0, 40.0, 85.0, 17.0, 92],
          "borderColor": "#FFCE56",
          "backgroundColor": "rgba(255, 206, 86, 0.2)"
        },
        {
          "label": "5678 - Another Team",
          "data": [87.9, 20.5, 55.4, 12.0, 79],
          "borderColor": "#4BC0C0",
          "backgroundColor": "rgba(75, 192, 192, 0.2)"
        }
      ]
    }
  }
}
```

### Get Team Rankings
**Endpoint:** `GET /api/mobile/teams/rankings?event_id={event_id}&metric=total_points`

**Headers:**
```
Authorization: Bearer YOUR_TOKEN_HERE
```

**Response:**
```json
{
  "success": true,
  "event": {
    "id": 5,
    "name": "Colorado Regional",
    "code": "CALA"
  },
  "metric": "total_points",
  "metric_display_name": "Total Points",
  "rankings": [
    {
      "rank": 1,
      "team_id": 23,
      "team_number": 9999,
      "team_name": "Top Team",
      "value": 142.0,
      "std_dev": 12.8,
      "match_count": 12,
      "consistency": 0.92
    },
    {
      "rank": 2,
      "team_id": 15,
      "team_number": 5454,
      "team_name": "The Bionics",
      "value": 125.5,
      "std_dev": 15.2,
      "match_count": 12,
      "consistency": 0.87
    },
    {
      "rank": 3,
      "team_id": 28,
      "team_number": 1234,
      "team_name": "Team Name",
      "value": 98.3,
      "std_dev": 18.5,
      "match_count": 11,
      "consistency": 0.82
    },
    {
      "rank": 4,
      "team_id": 47,
      "team_number": 5678,
      "team_name": "Another Team",
      "value": 87.9,
      "std_dev": 20.3,
      "match_count": 10,
      "consistency": 0.79
    }
  ],
  "count": 4,
  "total_teams": 48
}
```

### Get Available Metrics
**Endpoint:** `GET /api/mobile/config/metrics`

**Headers:**
```
Authorization: Bearer YOUR_TOKEN_HERE
```

**Response:**
```json
{
  "success": true,
  "metrics": [
    {
      "id": "tot",
      "name": "Total Points",
      "category": "scoring",
      "description": "Average total points scored per match",
      "unit": "points",
      "higher_is_better": true
    },
    {
      "id": "apt",
      "name": "Auto Points",
      "category": "scoring",
      "description": "Average autonomous points",
      "unit": "points",
      "higher_is_better": true
    },
    {
      "id": "tpt",
      "name": "Teleop Points",
      "category": "scoring",
      "description": "Average teleoperated points",
      "unit": "points",
      "higher_is_better": true
    },
    {
      "id": "ept",
      "name": "Endgame Points",
      "category": "scoring",
      "description": "Average endgame points",
      "unit": "points",
      "higher_is_better": true
    },
    {
      "id": "consistency",
      "name": "Consistency",
      "category": "performance",
      "description": "Performance consistency (0-1, higher is better)",
      "unit": "ratio",
      "higher_is_better": true
    },
    {
      "id": "accuracy",
      "name": "Scoring Accuracy",
      "category": "performance",
      "description": "Percentage of successful scoring attempts",
      "unit": "percentage",
      "higher_is_better": true
    },
    {
      "id": "gamepieces_per_match",
      "name": "Game Pieces Per Match",
      "category": "scoring",
      "description": "Average number of game pieces scored",
      "unit": "count",
      "higher_is_better": true
    },
    {
      "id": "scoring_frequency",
      "name": "Scoring Frequency",
      "category": "performance",
      "description": "Game pieces scored per minute",
      "unit": "per_minute",
      "higher_is_better": true
    }
  ]
}
```

---

## Scouting Data

### Submit Scouting Data
**Endpoint:** `POST /api/mobile/scouting/submit`

**Headers:**
```
Authorization: Bearer YOUR_TOKEN_HERE
Content-Type: application/json
```

**Request:**
```json
{
  "team_id": 15,
  "match_id": 42,
  "offline_id": "550e8400-e29b-41d4-a716-446655440000",
  "data": {
    "auto_speaker_scored": 5,
    "auto_amp_scored": 2,
    "auto_leave": true,
    "teleop_speaker_scored": 15,
    "teleop_amp_scored": 8,
    "teleop_amplified_speaker": 3,
    "teleop_trap_scored": 1,
    "endgame_climbed": "success",
    "endgame_harmony": true,
    "defense_rating": 4,
    "driver_skill": 5,
    "notes": "Very strong match, good driving"
  }
}
```

**Response:**
```json
{
  "success": true,
  "scouting_id": 1523,
  "message": "Scouting data submitted successfully",
  "offline_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

### Bulk Submit Scouting Data (Offline Sync)
**Endpoint:** `POST /api/mobile/scouting/bulk-submit`

**Headers:**
```
Authorization: Bearer YOUR_TOKEN_HERE
Content-Type: application/json
```

**Request:**
```json
{
  "entries": [
    {
      "team_id": 15,
      "match_id": 42,
      "offline_id": "550e8400-e29b-41d4-a716-446655440000",
      "timestamp": "2025-10-18T10:30:00Z",
      "data": {
        "auto_speaker_scored": 5,
        "auto_amp_scored": 2,
        "teleop_speaker_scored": 15,
        "endgame_climbed": "success"
      }
    },
    {
      "team_id": 23,
      "match_id": 43,
      "offline_id": "660e8400-e29b-41d4-a716-446655440001",
      "timestamp": "2025-10-18T11:00:00Z",
      "data": {
        "auto_speaker_scored": 3,
        "auto_amp_scored": 1,
        "teleop_speaker_scored": 12,
        "endgame_climbed": "failed"
      }
    }
  ]
}
```

**Response:**
```json
{
  "success": true,
  "submitted": 2,
  "failed": 0,
  "results": [
    {
      "offline_id": "550e8400-e29b-41d4-a716-446655440000",
      "success": true,
      "scouting_id": 1523
    },
    {
      "offline_id": "660e8400-e29b-41d4-a716-446655440001",
      "success": true,
      "scouting_id": 1524
    }
  ]
}
```

---

### Fetch Scouting Data (All / List)

This endpoint returns the same scouting rows shown in the web UI at `/scouting/list` and is scoped to the scouting team contained in your mobile token. By default the endpoint returns all scouting entries for the scouting team (the team doing the scouting). Do NOT pass your own scouting team number as the `team_number` filter — this is a common mistake and will be ignored. Use the `team_number` query param only to filter by the scouted team's number (for example, `team_number=4944`).

**Endpoint:** `GET /api/mobile/scouting/all`

**Headers:**
```
Authorization: Bearer YOUR_TOKEN_HERE
Accept: application/json
```

**Query params (all optional):**
- `team_number` (int) — the team that was scouted (e.g. 4944). Leave empty to return all scouted teams for your scouting team.
- `team_id` (int) — optional Team.id instead of team_number.
- `event_id` (int or event code) — accepts numeric id or event code string (e.g. `arsea`).
- `match_id` (int) — filter by a specific Match.id.
- `limit` (int) — max rows to return (default 200).
- `offset` (int) — pagination offset.
- `scoped` (0|1) — debugging only. Default is `1` and results are constrained to the scouting team from the token. Use `scoped=0` to bypass token scoping for debugging (not recommended for production).

**Example: fetch all scouting rows for your scouting team (recommended):**

PowerShell:
```powershell
$hdr = @{ Authorization = "Bearer YOUR_TOKEN_HERE" }
Invoke-RestMethod -Uri "http://localhost:8080/api/mobile/scouting/all?limit=50" -Headers $hdr -Method GET
```

**Example: fetch only entries for scouted team 4944:**

```powershell
$hdr = @{ Authorization = "Bearer YOUR_TOKEN_HERE" }
Invoke-RestMethod -Uri "http://localhost:8080/api/mobile/scouting/all?team_number=4944&limit=50" -Headers $hdr -Method GET
```

**Example: fetch entries for event code `arsea`:**

```powershell
$hdr = @{ Authorization = "Bearer YOUR_TOKEN_HERE" }
Invoke-RestMethod -Uri "http://localhost:8080/api/mobile/scouting/all?event_id=arsea&limit=50" -Headers $hdr -Method GET
```

**Example: debug unscoped (bypass token scoping, debugging only):**

```powershell
$hdr = @{ Authorization = "Bearer YOUR_TOKEN_HERE" }
Invoke-RestMethod -Uri "http://localhost:8080/api/mobile/scouting/all?limit=50&scoped=0" -Headers $hdr -Method GET
```

**Response shape (matches web list):**

```json
{
  "success": true,
  "count": 4,
  "total": 4,
  "entries": [
    {
      "id": 401,
      "team_id": 120,
      "team_number": 16,
      "team_name": "Team 16",
      "match_id": 210,
      "match_number": 1,
      "match_type": "Qualification",
      "event_id": 7,
      "event_code": "arsea",
      "alliance": "None",
      "scout_name": "Seth Herod",
      "scout_id": 4,
      "scouting_station": null,
      "timestamp": "2025-10-19T06:28:00Z",
      "scouting_team_number": 5454,
      "data": { "auto_speaker_scored": 2, "teleop_speaker_scored": 10 }
    }
  ]
}
```

Notes:
- If you pass `team_number` equal to the scouting team in your token (for example `team_number=5454` when your token is for scouting team 5454), the server will ignore the filter and return all entries for your scouting team (this prevents the common mistake of filtering out all results).
- `event_id` accepts event codes (e.g. `arsea`) and numeric IDs. The server resolves codes to the numeric Event.id where possible.

### Using the Tk test UI

The `tools/tk_scouting_all_ui.py` helper included in this repository can be used to exercise this endpoint:
- Run: `python tools/tk_scouting_all_ui.py`
- Login with username/password and your scouting team number (e.g. `5454`). The returned token will be stored in the Token field.
- Leave the "Filter by scouted team#" field empty to fetch all rows for your scouting team.
- Optionally enter a scouted `team_number` (e.g. `4944`) to filter down to a single team.


## Common Data Models

### Team Object
```json
{
  "id": 15,
  "team_number": 5454,
  "team_name": "The Bionics",
  "location": "Parker, CO"
}
```

### Match Object
```json
{
  "id": 42,
  "match_number": 15,
  "match_type": "Qualification",
  "event_id": 5,
  "red_alliance": "5454,1234,5678",
  "blue_alliance": "9999,2222,3333",
  "red_score": 145,
  "blue_score": 132,
  "winner": "red",
  "scheduled_time": "2025-10-18T14:30:00Z",
  "predicted_time": "2025-10-18T14:35:00Z"
}
```

### Event Object
```json
{
  "id": 5,
  "name": "Colorado Regional",
  "code": "CALA",
  "location": "Denver, CO",
  "timezone": "America/Denver",
  "start_date": "2025-10-16",
  "end_date": "2025-10-19",
  "year": 2025
}
```

### Metrics Object
```json
{
  "match_count": 12,
  "total_points": 125.5,
  "total_points_std": 15.2,
  "auto_points": 35.2,
  "auto_points_std": 5.8,
  "teleop_points": 75.8,
  "teleop_points_std": 10.5,
  "endgame_points": 14.5,
  "endgame_points_std": 3.2,
  "consistency": 0.87,
  "win_rate": 0.75
}
```

---

## Error Responses

All endpoints may return error responses in the following format:

```json
{
  "success": false,
  "error": "Human-readable error message",
  "error_code": "ERROR_CODE_IDENTIFIER"
}
```

### Common Error Codes

- `AUTH_REQUIRED` - No authentication token provided
- `INVALID_TOKEN` - Token is invalid or expired
- `USER_NOT_FOUND` - User account not found or inactive
- `MISSING_DATA` - Required data not provided in request
- `MISSING_FIELD` - Specific required field missing
- `TEAM_NOT_FOUND` - Requested team not found
- `MATCH_NOT_FOUND` - Requested match not found
- `EVENT_NOT_FOUND` - Requested event not found
- `PERMISSION_DENIED` - User doesn't have permission for this action
- `VALIDATION_ERROR` - Data validation failed
- `INTERNAL_ERROR` - Server error occurred

### Example Error Response
```json
{
  "success": false,
  "error": "Team not found for your scouting team",
  "error_code": "TEAM_NOT_FOUND"
}
```

---

## Notes

1. **Timestamps**: All timestamps are in ISO 8601 format with UTC timezone (e.g., `2025-10-18T12:00:00Z`)

2. **Team Isolation**: All data is automatically filtered by the authenticated user's scouting team number

3. **Pagination**: Endpoints that return lists typically support `limit` and `offset` query parameters

4. **Offline Support**: Use `offline_id` (UUID) to track submissions made while offline and sync later with bulk submit

5. **Token Expiration**: Tokens expire after 7 days. Use the refresh endpoint or re-login to get a new token

6. **Rate Limiting**: The API may implement rate limiting. Check response headers for rate limit information

7. **Data Validation**: All submitted data is validated against the current game configuration

8. **Alliance Mode**: If your scouting team is in alliance mode, data may be aggregated from multiple teams in the alliance

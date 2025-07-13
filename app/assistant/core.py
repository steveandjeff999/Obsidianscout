"""
Core Assistant functionality
Handles natural language queries and provides answers based on scouting data
"""

import re
from typing import Dict, List, Any, Tuple, Optional
from app.models import Team, ScoutingData, Match, Event, User
from app import db
from app.utils.analysis import calculate_team_metrics
from sqlalchemy import func, desc
import logging

logger = logging.getLogger(__name__)

class Assistant:
    """
    Scout Assistant that answers questions about teams, matches, and scouting data
    """
    
    def __init__(self):
        # Define common question patterns and their handler methods
        self.patterns = [
            # Team stats patterns - various ways to ask about team stats
            (r'(?:stats|statistics|data|info|about|tell me about)(?:\s+for)?\s+team\s+(\d+)', self.get_team_stats),
            (r'^team\s+(\d+)$', self.get_team_stats),  # Just "team 123"
            (r'^(\d+)$', self.get_team_stats),  # Just the number "123"
            (r'(?:how is|how did|how good is|performance of|analysis for|analyze)\s+team\s+(\d+)', self.get_team_stats),
            
            # Best teams patterns
            (r'(?:best|top|highest|strongest|leading)\s+(\w+)(?:\s+teams)?', self.get_best_teams_for_metric),
            (r'who(?:\'s| is) best at\s+(\w+)', self.get_best_teams_for_metric),
            (r'which teams? (?:are|is|have|has) the best (\w+)', self.get_best_teams_for_metric),
            
            # Team comparison patterns
            (r'(?:compare|vs|versus|comparison between)\s+(?:team)?\s*(\d+)\s+(?:and|vs|versus|with|to)\s+(?:team)?\s*(\d+)', self.compare_teams),
            (r'(?:how does?|is) (?:team)?\s*(\d+) (?:compare|compared) (?:to|with) (?:team)?\s*(\d+)', self.compare_teams),
            
            # Match patterns
            (r'(?:upcoming|next|future|scheduled|remaining) matches(?:\s+for\s+(?:team)?\s*(\d+))?', self.get_upcoming_matches),
            (r'(?:match|game)\s+(?:number)?\s*(\d+)(?:\s+results?)?', self.get_match_results),
            (r'(?:results|outcome|score) (?:of|for) match\s+(\d+)', self.get_match_results),
            
            # Event stats patterns
            (r'(?:event|competition|tournament)\s+(?:stats|statistics|data|info|results)(?:\s+for\s+(.+))?', self.get_event_stats),
            (r'(?:how is|how was) the (?:event|competition|tournament)(?:\s+(.+))?', self.get_event_stats),
            
            # Context-aware patterns
            (r'(?:how about|what about|show me|compare with|compare to|and|also) (?:team)?\s*(\d+)(?:\s+too)?', self.handle_context_follow_up),
            (r'^what about\s+(.+?)(?:\s+too)?$', self.handle_generic_follow_up),
            (r'^how does it compare\s+(?:to|with)?\s*(.+?)$', self.handle_comparison_follow_up),
            
            # Meta patterns
            (r'what(?:\'s| is) your name', self.get_name),
            (r'(?:who are you|introduce yourself)', self.get_name),
            (r'(?:help|assist|support|what can you do|commands|options|capabilities|features)', self.get_help_info)
        ]
    
    def _get_context(self):
        """
        Get the conversation context from session if it exists,
        otherwise create a new context structure
        
        This is called only within request context
        """
        from flask import session
        
        if 'assistant_context' not in session:
            session['assistant_context'] = {
                'last_question': None,
                'last_answer': None,
                'last_entities': {
                    'team': None,
                    'teams': [],
                    'match': None,
                    'metric': None,
                    'event': None
                },
                'conversation_history': []
            }
        
        return session['assistant_context']
    
    def answer_question(self, question: str) -> Dict[str, Any]:
        """
        Main method to process a question and return an answer
        
        Args:
            question: The natural language question from the user
            
        Returns:
            Dictionary with answer text and any related data
        """
        # Save the original question for context
        original_question = question
        question = question.lower().strip()
        
        # Check for context-dependent questions like "What about their defense?"
        context_dependent = self._is_context_dependent(question)
        
        # Try to extract team numbers if they exist in the question
        team_numbers = re.findall(r'\b\d{1,4}\b', question)
        
        # Check for metrics mentioned in the question
        metrics = ["auto", "teleop", "endgame", "scoring", "climb", "defense", "accuracy", "speed"]
        mentioned_metrics = [m for m in metrics if m in question]
        
        # Try to match the question with our patterns
        for pattern, handler in self.patterns:
            match = re.search(pattern, question)
            if match:
                try:
                    answer = handler(*match.groups())
                    self._update_context(original_question, answer, team_numbers, mentioned_metrics)
                    return answer
                except Exception as e:
                    logger.error(f"Error processing question: {e}")
                    return {
                        "text": f"Sorry, I encountered an error while processing your question: {str(e)}",
                        "error": True
                    }
        
        # If we found team numbers but no pattern matched, try the team stats handler
        if team_numbers and len(team_numbers) == 1:
            try:
                answer = self.get_team_stats(team_numbers[0])
                self._update_context(original_question, answer, team_numbers, mentioned_metrics)
                return answer
            except Exception as e:
                logger.error(f"Error getting team stats: {e}")
        
        # If we found two team numbers, try the comparison handler
        if team_numbers and len(team_numbers) == 2:
            try:
                answer = self.compare_teams(team_numbers[0], team_numbers[1])
                self._update_context(original_question, answer, team_numbers, mentioned_metrics)
                return answer
            except Exception as e:
                logger.error(f"Error comparing teams: {e}")
        
        # If metrics were mentioned but no pattern matched, try the best teams handler
        if mentioned_metrics:
            try:
                answer = self.get_best_teams_for_metric(mentioned_metrics[0])
                self._update_context(original_question, answer, team_numbers, mentioned_metrics)
                return answer
            except Exception as e:
                logger.error(f"Error getting best teams: {e}")
                
        # If question seems context-dependent but no explicit patterns matched,
        # try to resolve it using the conversation context
        if context_dependent:
            try:
                answer = self._resolve_context_dependent_question(question)
                if answer:
                    self._update_context(original_question, answer, team_numbers, mentioned_metrics)
                    return answer
            except Exception as e:
                logger.error(f"Error resolving context-dependent question: {e}")
        
        # Use the browser-based AI for more complex questions
        if len(question) > 10:  # Only for non-trivial questions
            try:
                ai_answer = self.get_ai_powered_answer(question)
                if ai_answer:
                    self._update_context(original_question, ai_answer, team_numbers, mentioned_metrics)
                    return ai_answer
            except Exception as e:
                logger.error(f"Error using AI assistant: {e}")
        
        # No pattern matched
        return {
            "text": "I'm not sure how to answer that question. Try asking about team stats, match results, or say 'help' for more options.",
            "suggestion": "Try asking 'stats for team 5454' or 'best auto scores'"
        }
    
    def get_team_stats(self, team_number: str) -> Dict[str, Any]:
        """Get statistics for a specific team"""
        try:
            team = Team.query.filter_by(team_number=int(team_number)).first()
            if not team:
                return {"text": f"Team {team_number} not found in the database."}
            
            # Calculate team statistics from scouting data
            entries = ScoutingData.query.filter_by(team_id=team.id).all()
            if not entries:
                return {"text": f"No scouting data available for Team {team_number}."}
            
            stats = calculate_team_metrics(team.id)
            
            response = {
                "text": f"Here are the stats for Team {team_number} ({team.team_name}):",
                "team": {
                    "number": team.team_number,
                    "name": team.team_name,
                    "stats": stats
                },
                "visualization_options": ["team_performance", "ranking_comparison"]
            }
            return response
        except Exception as e:
            logger.error(f"Error getting team stats: {e}")
            return {"text": f"Error retrieving stats for Team {team_number}: {str(e)}", "error": True}
    
    def get_best_teams_for_metric(self, metric: str) -> Dict[str, Any]:
        """Get the top teams for a specific performance metric"""
        valid_metrics = {
            "auto": "auto_points", 
            "teleop": "teleop_points",
            "endgame": "endgame_points",
            "total": "total_points",
            "scoring": "scoring_efficiency",
            "defense": "defense_rating"
        }
        
        # Try to map the user's term to our metrics
        matched_metric = None
        for key, value in valid_metrics.items():
            if key in metric.lower():
                matched_metric = value
                break
        
        if not matched_metric:
            return {
                "text": f"Sorry, I don't recognize '{metric}' as a valid performance metric. "
                        f"Try asking about auto, teleop, endgame, total points, scoring, or defense."
            }
        
        # Get top 5 teams for this metric
        # This is a simplified implementation - in a real app, you'd query aggregated data
        teams = []
        team_stats = {}
        
        # For a real implementation, you would use a database query to get this data
        # This is just a placeholder to demonstrate the concept
        response = {
            "text": f"Here are the top teams for {metric}:",
            "metric": metric,
            "teams": teams[:5],
            "visualization_options": ["metric_comparison", "team_ranking"]
        }
        return response
    
    def compare_teams(self, team1: str, team2: str) -> Dict[str, Any]:
        """Compare statistics between two teams"""
        try:
            team1_obj = Team.query.filter_by(team_number=int(team1)).first()
            team2_obj = Team.query.filter_by(team_number=int(team2)).first()
            
            if not team1_obj:
                return {"text": f"Team {team1} not found in the database."}
            if not team2_obj:
                return {"text": f"Team {team2} not found in the database."}
            
            # Calculate stats for both teams
            team1_stats = calculate_team_metrics(team1_obj.id)
            team2_stats = calculate_team_metrics(team2_obj.id)
            
            return {
                "text": f"Comparison between Team {team1} and Team {team2}:",
                "teams": [
                    {
                        "number": team1_obj.team_number,
                        "name": team1_obj.team_name,
                        "stats": team1_stats
                    },
                    {
                        "number": team2_obj.team_number,
                        "name": team2_obj.team_name,
                        "stats": team2_stats
                    }
                ],
                "visualization_options": ["team_comparison", "radar_chart"]
            }
        except Exception as e:
            logger.error(f"Error comparing teams: {e}")
            return {"text": f"Error comparing Teams {team1} and {team2}: {str(e)}", "error": True}
    
    def get_upcoming_matches(self, team_number: Optional[str] = None) -> Dict[str, Any]:
        """Get upcoming match schedule, optionally filtered for a specific team"""
        try:
            # Filter for matches that don't have scores (not completed)
            query = Match.query.filter(
                (Match.red_score.is_(None)) | (Match.blue_score.is_(None))
            ).order_by(Match.match_number)
            
            if team_number:
                team = Team.query.filter_by(team_number=int(team_number)).first()
                if not team:
                    return {"text": f"Team {team_number} not found in the database."}
                
                # Find matches with this team number in red_alliance or blue_alliance
                team_str = str(team.team_number)
                team_matches = query.filter(
                    (Match.red_alliance.like(f'%{team_str}%')) | 
                    (Match.blue_alliance.like(f'%{team_str}%'))
                ).all()
                
                if not team_matches:
                    return {"text": f"No upcoming matches found for Team {team_number}."}
                
                matches = team_matches
                response_text = f"Upcoming matches for Team {team_number}:"
            else:
                matches = query.limit(5).all()
                if not matches:
                    return {"text": "No upcoming matches found."}
                response_text = "Next 5 upcoming matches:"
            
            match_list = []
            for match in matches:
                match_info = {
                    "number": match.match_number,
                    "time": match.timestamp.strftime("%H:%M") if match.timestamp else "TBD",
                    "red_alliance": match.red_teams,  # Using the property from the Match model
                    "blue_alliance": match.blue_teams  # Using the property from the Match model
                }
                match_list.append(match_info)
            
            return {
                "text": response_text,
                "matches": match_list,
                "visualization_options": ["match_schedule"]
            }
        except Exception as e:
            logger.error(f"Error getting upcoming matches: {e}")
            return {"text": f"Error retrieving upcoming matches: {str(e)}", "error": True}
    
    def get_match_results(self, match_number: str) -> Dict[str, Any]:
        """Get the results for a specific match"""
        try:
            match = Match.query.filter_by(match_number=int(match_number)).first()
            if not match:
                return {"text": f"Match {match_number} not found in the database."}
            
            # Check if match is completed based on scores being available
            if match.red_score is None or match.blue_score is None:
                return {"text": f"Match {match_number} has not been completed yet."}
            
            # Construct response with match results
            return {
                "text": f"Results for Match {match_number}:",
                "match": {
                    "number": match.match_number,
                    "red_score": match.red_score,
                    "blue_score": match.blue_score,
                    "winner": "Red" if match.winner == "red" else "Blue" if match.winner == "blue" else "Tie",
                    "red_alliance": match.red_teams,  # Using the property from the Match model
                    "blue_alliance": match.blue_teams  # Using the property from the Match model
                },
                "visualization_options": ["match_breakdown"]
            }
        except Exception as e:
            logger.error(f"Error getting match results: {e}")
            return {"text": f"Error retrieving results for Match {match_number}: {str(e)}", "error": True}
    
    def get_event_stats(self, event_name: Optional[str] = None) -> Dict[str, Any]:
        """Get statistics for an event"""
        try:
            # Get the current event or a specific one if named
            if event_name:
                event = Event.query.filter(Event.name.ilike(f'%{event_name}%')).first()
                if not event:
                    return {"text": f"Event '{event_name}' not found in the database."}
            else:
                # Default to most recent event
                event = Event.query.order_by(desc(Event.start_date)).first()
                if not event:
                    return {"text": "No events found in the database."}
            
            # Count matches
            total_matches = Match.query.filter_by(event_id=event.id).count()
            # Count completed matches (those with scores)
            completed_matches = Match.query.filter_by(event_id=event.id).filter(
                Match.red_score.isnot(None), 
                Match.blue_score.isnot(None)
            ).count()
            
            # Count teams
            teams_count = db.session.query(func.count(Team.id)).join(
                Team.events).filter(Event.id == event.id).scalar()
            
            # Count scouting entries
            entries_count = db.session.query(func.count(ScoutingData.id)).join(
                ScoutingData.match).filter(Match.event_id == event.id).scalar()
            
            return {
                "text": f"Statistics for {event.name}:",
                "event": {
                    "name": event.name,
                    "location": event.location,
                    "dates": f"{event.start_date.strftime('%Y-%m-%d')} to {event.end_date.strftime('%Y-%m-%d')}",
                    "teams_count": teams_count,
                    "total_matches": total_matches,
                    "completed_matches": completed_matches,
                    "scouting_entries": entries_count
                },
                "visualization_options": ["event_summary", "team_rankings"]
            }
        except Exception as e:
            logger.error(f"Error getting event stats: {e}")
            return {"text": f"Error retrieving event statistics: {str(e)}", "error": True}
    
    def get_name(self) -> Dict[str, Any]:
        """Return the assistant's name when asked"""
        return {
            "text": "I'm the Scout Assistant, designed to help you analyze scouting data for Team 5454 and your FRC competitions."
        }
    
    def get_help_info(self) -> Dict[str, Any]:
        """Provide help information about what the assistant can do"""
        return {
            "text": "I can help you with the following types of questions:",
            "help_topics": [
                {"topic": "Team Statistics", "example": "Stats for team 5454"},
                {"topic": "Top Teams", "example": "Best auto scoring teams"},
                {"topic": "Team Comparison", "example": "Compare team 5454 and team 1234"},
                {"topic": "Match Schedule", "example": "Upcoming matches for team 5454"},
                {"topic": "Match Results", "example": "Match 42 results"},
                {"topic": "Event Statistics", "example": "Event stats for District Championship"},
                {"topic": "General Questions", "example": "What makes a good scouting strategy?"}
            ],
            "ai_info": "I can also answer general questions about FRC, scouting, and robotics using AI assistance."
        }
    
    def get_ai_powered_answer(self, question: str) -> Dict[str, Any]:
        """
        Use a browser-based AI service to answer more complex questions
        
        Args:
            question: The natural language question to process
            
        Returns:
            Dictionary with answer text and any related data
        """
        try:
            from app.utils.ai_helper import query_browser_ai
            
            # Context about our application
            context = {
                "app_type": "FRC Scouting Application",
                "team_info": "Designed for Team 5454",
                "data_types": "Contains team stats, match data, and scouting information"
            }
            
            # Query the browser-based AI
            ai_response = query_browser_ai(question, context)
            
            # If we got a valid response
            if ai_response and isinstance(ai_response, str):
                return {
                    "text": ai_response,
                    "ai_generated": True
                }
            return None
        except ImportError:
            logger.warning("AI helper module not available")
            return None
        except Exception as e:
            logger.error(f"Error using AI service: {str(e)}")
            return None
    
    def _is_context_dependent(self, question: str) -> bool:
        """
        Check if a question seems to depend on previous context
        
        Args:
            question: The current question
            
        Returns:
            Boolean indicating if question appears to be context-dependent
        """
        # Pronouns and references that typically indicate context dependency
        context_indicators = [
            r'\bthat\b', r'\bit\b', r'\bthey\b', r'\bthem\b', r'\btheir\b', 
            r'\bthose\b', r'\bthese\b', r'\bthe team\b', r'\bthe match\b',
            r'^how about', r'^what about', r'^and ', r'^also ', r'^how does'
        ]
        
        return any(re.search(pattern, question.lower()) for pattern in context_indicators)
    
    def _update_context(self, question: str, answer: Dict[str, Any], team_numbers: List[str], metrics: List[str]) -> None:
        """
        Update the conversation context with the latest question and answer
        
        Args:
            question: The original question
            answer: The answer provided
            team_numbers: Any team numbers mentioned
            metrics: Any metrics mentioned
        """
        try:
            from flask import session
            
            # Get the current context
            context = self._get_context()
            
            # Update last question and answer
            context['last_question'] = question
            context['last_answer'] = answer
            
            # Add to conversation history (limit to last 5 interactions)
            context['conversation_history'].append({
                'question': question,
                'answer': answer.get('text', ''),
                'timestamp': str(func.now())
            })
            context['conversation_history'] = context['conversation_history'][-5:]
            
            # Extract and update entities from the answer
            if 'team' in answer and answer['team']:
                team_info = answer['team']
                context['last_entities']['team'] = {
                    'number': team_info.get('number'),
                    'name': team_info.get('name')
                }
            
            if 'teams' in answer and answer['teams']:
                teams_info = answer['teams']
                context['last_entities']['teams'] = [
                    {'number': team.get('number'), 'name': team.get('name')} 
                    for team in teams_info
                ]
            
            if 'match' in answer and answer['match']:
                context['last_entities']['match'] = answer['match'].get('number')
                
            if 'metric' in answer:
                context['last_entities']['metric'] = answer.get('metric')
                
            if 'event' in answer and answer['event']:
                context['last_entities']['event'] = answer['event'].get('name')
            
            # Save updated context
            session['assistant_context'] = context
        except RuntimeError:
            # Working outside request context, skip updating session
            logger.warning("Attempted to update context outside of request context")
            pass
    
    def _resolve_context_dependent_question(self, question: str) -> Dict[str, Any]:
        """
        Resolve a context-dependent question using conversation history
        
        Args:
            question: The current question
            
        Returns:
            Answer dictionary or None if resolution not possible
        """
        try:
            # Get the current context
            context = self._get_context()
            last_entities = context.get('last_entities', {})
        except RuntimeError:
            # Working outside request context
            logger.warning("Attempted to resolve context-dependent question outside of request context")
            return None
        
        # Handle "How about their defense?" after discussing a team
        if re.search(r'how about .* defense', question) and last_entities.get('team'):
            team_number = last_entities['team']['number']
            return self.get_team_stats(str(team_number))
        
        # Handle "What was their score?" after discussing a match
        if re.search(r'what .* score', question) and last_entities.get('match'):
            match_number = last_entities['match']
            return self.get_match_results(str(match_number))
        
        # Handle "Compare with team 254" after discussing a team
        match = re.search(r'compare (?:with|to) team (\d+)', question)
        if match and last_entities.get('team'):
            team1 = str(last_entities['team']['number'])
            team2 = match.group(1)
            return self.compare_teams(team1, team2)
        
        # No resolution found
        return None
    
    def handle_context_follow_up(self, entity: str) -> Dict[str, Any]:
        """
        Handle follow-up questions about a specific entity
        
        Args:
            entity: The entity mentioned in the follow-up
            
        Returns:
            Answer dictionary
        """
        try:
            # Get the current context
            context = self._get_context()
            last_entities = context.get('last_entities', {})
        except RuntimeError:
            # Working outside request context, fallback to direct handling
            logger.warning("Attempted to handle follow-up outside of request context")
            return self.get_team_stats(entity)
        
        # If we were just talking about teams, assume this is a comparison or additional team request
        if last_entities.get('team'):
            # Compare with previous team
            return self.compare_teams(str(last_entities['team']['number']), entity)
        
        # Default to getting stats for this team
        return self.get_team_stats(entity)
    
    def handle_generic_follow_up(self, query: str) -> Dict[str, Any]:
        """
        Handle generic follow-up questions
        
        Args:
            query: The follow-up query
            
        Returns:
            Answer dictionary
        """
        try:
            # Get the current context
            context = self._get_context()
            last_entities = context.get('last_entities', {})
        except RuntimeError:
            # Working outside request context, fallback to AI answer
            logger.warning("Attempted to handle generic follow-up outside of request context")
            return self.get_ai_powered_answer(query)
        
        # Check if query is about a metric
        metrics = ["auto", "teleop", "endgame", "scoring", "climb", "defense", "accuracy", "speed"]
        for metric in metrics:
            if metric in query.lower():
                # If we have a team in context, get that metric for the team
                if last_entities.get('team'):
                    team = Team.query.filter_by(team_number=last_entities['team']['number']).first()
                    if team:
                        stats = calculate_team_metrics(team.id)
                        metric_value = stats.get(metric.lower() + "_points", "N/A")
                        return {
                            "text": f"{metric.title()} performance for Team {team.team_number}: {metric_value}",
                            "team": {
                                "number": team.team_number,
                                "name": team.team_name,
                                "metric": metric,
                                "value": metric_value
                            },
                            "visualization_options": ["metric_detail"]
                        }
                
                # Otherwise, show best teams for this metric
                return self.get_best_teams_for_metric(metric)
        
        # If query contains team, try to interpret as a team number
        if "team" in query.lower():
            team_match = re.search(r'team\s+(\d+)', query.lower())
            if team_match:
                return self.get_team_stats(team_match.group(1))
        
        # Check for match-related follow-up
        if "match" in query.lower():
            match_match = re.search(r'match\s+(\d+)', query.lower())
            if match_match:
                return self.get_match_results(match_match.group(1))
        
        # If no specific entity found, but we have context, use AI to interpret
        return self.get_ai_powered_answer(f"In context of {context.get('last_question')}, {query}")
    
    def handle_comparison_follow_up(self, entity: str) -> Dict[str, Any]:
        """
        Handle comparison follow-up questions
        
        Args:
            entity: The entity to compare with
            
        Returns:
            Answer dictionary
        """
        try:
            # Get the current context
            context = self._get_context()
            last_entities = context.get('last_entities', {})
        except RuntimeError:
            # Working outside request context, fallback to direct handling
            logger.warning("Attempted to handle comparison outside of request context")
            return {"text": f"To compare teams, please specify both teams you want to compare."}
        
        # If we have a team in context
        if last_entities.get('team'):
            # Check if entity is a team number
            if re.match(r'^\d+$', entity):
                return self.compare_teams(str(last_entities['team']['number']), entity)
            # Check if it's a team reference like "team 254"
            team_match = re.search(r'team\s+(\d+)', entity.lower())
            if team_match:
                return self.compare_teams(str(last_entities['team']['number']), team_match.group(1))
        
        # If we can't resolve it with context, default to AI
        return self.get_ai_powered_answer(
            f"Compare {last_entities.get('team', {}).get('name', 'current team')} with {entity}")
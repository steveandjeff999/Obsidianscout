"""
Core Assistant functionality
Handles natural language queries and provides answers based on scouting data
"""

import re
from typing import Dict, List, Any, Tuple, Optional
import difflib
import string
from datetime import datetime, timezone
from app.models import Team, ScoutingData, Match, Event, User
from app.utils.api_utils import safe_int_team_number
from app import db
from flask_login import current_user
from app.utils.analysis import calculate_team_metrics
from app.utils.config_manager import get_current_game_config
from sqlalchemy import func, desc
import logging

try:
    import requests
except ImportError:
    requests = None

logger = logging.getLogger(__name__)

class Assistant:
    """
    Intelligent Scout Assistant - Conversational AI for scouting data analysis
    Provides LLM-like natural conversation while maintaining lightweight performance
    """
    
    def __init__(self):
        # Conversation state for context-aware responses
        self.conversation_memory = {
            'recent_teams': [],
            'recent_topics': [],
            'user_preferences': {},
            'conversation_depth': 0,
            'knowledge_cache': {},  # Cache for external knowledge queries
            'entity_mentions': []  # Track mentioned entities
        }
        
        # FRC-specific knowledge base
        self.frc_knowledge = {
            'dean kamen': 'Dean Kamen is the founder of FIRST (For Inspiration and Recognition of Science and Technology) and inventor of the Segway, among many other innovations.',
            'woodie flowers': 'Woodie Flowers was a beloved FIRST mentor and MIT professor who championed gracious professionalism in robotics.',
            'gracious professionalism': 'Gracious Professionalism is a core FIRST value that emphasizes competing with respect, kindness, and high-quality work.',
            'coopertition': 'Coopertition is a FIRST philosophy combining cooperation and competition, where teams help each other while competing.',
            'first': 'FIRST (For Inspiration and Recognition of Science and Technology) is a robotics organization founded by Dean Kamen in 1989.',
            'frc': 'FIRST Robotics Competition (FRC) is the high school division of FIRST, featuring large robots competing in complex games.',
            'blue alliance': 'The Blue Alliance is a popular FRC data platform providing match schedules, results, and team statistics.',
            'chief delphi': 'Chief Delphi is the primary online forum and community hub for FRC teams worldwide.'
        }
        
        # Define common question patterns and their handler methods
        self.patterns = [
            # PRIMARY COMPARISON - Must be first to catch short formats like "5454 and 16"
            (r'^\s*(\d{1,4})\s+(?:and|vs|versus|v)\s+(\d{1,4})\s*$', self.compare_teams),
            (r'^\s*(?:team\s+)?(\d{1,4})\s+(?:and|vs|versus|v)\s+(?:team\s+)?(\d{1,4})\s*$', self.compare_teams),
            
            # Team stats patterns - various ways to ask about team stats
            (r'(?:stats|statistics|data|info|about|tell me about)(?:\s+for)?\s+team\s+(\d+)', self.get_team_stats),
            (r'^team\s+(\d+)$', self.get_team_stats),  # Just "team 123"
            (r'^(\d+)$', self.get_team_stats),  # Just the number "123"
            (r'(?:how is|how did|how good is|performance of|analysis for|analyze)\s+team\s+(\d+)', self.get_team_stats),
            
            # Best teams patterns
            (r'(?:best|top|highest|strongest|leading)\s+(\w+)(?:\s+teams)?', self.get_best_teams_for_metric),
            (r'who(?:\'s| is) best at\s+(\w+)', self.get_best_teams_for_metric),
            (r'which teams? (?:are|is|have|has) the best (\w+)', self.get_best_teams_for_metric),
            
            # Team comparison patterns (improved to catch more variations)
            (r'(?:compare|vs|versus|comparison between)\s+(?:team)?\s*(\d+)\s+(?:and|vs|versus|with|to)\s+(?:team)?\s*(\d+)', self.compare_teams),
            (r'(?:how does?|is) (?:team)?\s*(\d+) (?:compare|compared) (?:to|with) (?:team)?\s*(\d+)', self.compare_teams),
            (r'(?:team)?\s*(\d+)\s+(?:vs|versus)\s+(?:team)?\s*(\d+)', self.compare_teams),
            (r'difference between (?:team)?\s*(\d+) and (?:team)?\s*(\d+)', self.compare_teams),
            
            # Match patterns with optional match type
            (r'(?:upcoming|next|future|scheduled|remaining)\s+(?:(practice|qual|qualification|playoff|elim|elimination)\s+)?matches(?:\s+for\s+(?:team)?\s*(\d+))?', self._handle_upcoming_matches),
            (r'(?:team)?\s*(\d+)\s+(?:upcoming|next)\s+(practice|qual|qualification|playoff|elim|elimination)\s+matches', self.get_upcoming_matches_team_first),
            # Match results with optional match type - match type comes BEFORE number
            (r'(?:(practice|qual|qualification|playoff|elim|elimination)\s+)?(?:match|game)\s+(?:number)?\s*(\d+)(?:\s+results?)?', self._handle_match_results),
            (r'(?:results|outcome|score)\s+(?:of|for)\s+(?:(practice|qual|qualification|playoff|elim|elimination)\s+)?match\s+(\d+)', self._handle_match_results),
            # Short forms like 'qual 5' or 'playoff 3' (without the word 'match')
            (r'^(?:(practice|qual|qualification|playoff|elim|elimination)\s+)(\d+)$', self._handle_match_results),
            
            # Trend analysis patterns
            (r'(?:trend|trends|trajectory|progression|improvement)\s+(?:for\s+)?(?:team\s+)?(\d+)', self.analyze_team_trends),
            (r'(?:is|are)\s+(?:team\s+)?(\d+)\s+(?:improving|getting better|declining|getting worse)', self.analyze_team_trends),
            (r'(?:team\s+)?(\d+)\s+(?:over time|performance history|historical)', self.analyze_team_trends),
            
            # Prediction patterns
            (r'(?:predict|prediction|forecast)\s+(?:for\s+)?(?:team\s+)?(\d+)', self.predict_team_performance),
            (r'(?:will|can)\s+(?:team\s+)?(\d+)\s+(?:win|beat|defeat)', self.predict_match_outcome),
            (r'(?:who will win|winner prediction|match prediction)\s+(?:match\s+)?(\d+)', self.predict_match_winner),
            
            # Historical comparison patterns
            (r'(?:compare|contrast)\s+(?:team\s+)?(\d+)\s+(?:to\s+)?(?:last\s+)?(year|season|event)', self.compare_historical),
            (r'(?:team\s+)?(\d+)\s+(?:vs|versus)\s+(?:last\s+)?(year|season|event)', self.compare_historical),
            
            # Advanced analytics patterns
            (r'(?:consistency|reliable|reliability)\s+(?:of\s+)?(?:team\s+)?(\d+)', self.analyze_consistency),
            (r'(?:peak|best|optimal)\s+(?:performance|match)\s+(?:for\s+)?(?:team\s+)?(\d+)', self.find_peak_performance),
            (r'(?:weak|weakness|weaknesses)\s+(?:of\s+)?(?:team\s+)?(\d+)', self.analyze_weaknesses),
            (r'(?:strength|strengths)\s+(?:of\s+)?(?:team\s+)?(\d+)', self.analyze_strengths),
            
            # What-if and scenario patterns
            (r'(?:what if|if)\s+(?:team\s+)?(\d+)\s+(?:and|&)\s+(?:team\s+)?(\d+)\s+(?:team up|alliance|together)', self.predict_alliance),
            (r'(?:alliance|team up)\s+(?:with|between)\s+(?:team\s+)?(\d+)\s+(?:and|&)\s+(?:team\s+)?(\d+)', self.predict_alliance),
            
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
            (r'(?:help|assist|support|what can you do|commands|options|capabilities|features)', self.get_help_info),
            # Summarization of local help docs
            (r'(?:summarize|summary of|summarise|brief)\s+(?:help|docs|documentation)(?:\s+for\s+(.+))?', self.summarize_help_docs)
        ]

        # Additional loose keyword-based handlers (checked if regex patterns don't match)
        self.loose_keywords = [
            (['scout', 'scouting', 'scout role'], self.get_scout_role),
            (['api', 'api docs', 'explain api', 'how api works'], self.explain_api_docs),
            (['role', 'roles', 'user roles', 'user role', 'permissions'], self.get_user_roles)
        ]
    
    def _get_scouting_team_number(self):
        """Safely get scouting team number - returns None if not in user context (e.g., during testing)."""
        try:
            from flask_login import current_user
            return current_user.scouting_team_number if hasattr(current_user, 'scouting_team_number') else None
        except:
            return None
    
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
        Main method to process a question and return an intelligent, context-aware answer
        Uses multi-stage analysis: NLU → Pattern matching → Semantic search → Contextual reasoning → AI fallback
        
        Args:
            question: The natural language question from the user
            
        Returns:
            Dictionary with answer text and any related data
        """
        # Save the original question for context
        original_question = question
        question = question.lower().strip()
        
        # Track conversation depth for adaptive responses
        self.conversation_memory['conversation_depth'] += 1
        
        # Advanced query decomposition - break down complex queries
        query_parts = self._decompose_query(question)
        
        # Analyze question intent and complexity
        question_analysis = self._analyze_question(question)
        is_complex = question_analysis.get('complexity', 'simple') in ['complex', 'multi_part']
        
        # Detect if this is a general knowledge query vs scouting data query
        is_data_query = self._is_scouting_data_query(question)
        is_knowledge_query = self._is_general_knowledge_query(question)
        
        # Check for context-dependent questions like "What about their defense?"
        context_dependent = self._is_context_dependent(question)
        
        # Try to extract team numbers if they exist in the question
        team_numbers = re.findall(r'\b\d{1,4}\b', question)
        
        # Check for metrics mentioned in the question (define early for use in early detection)
        metrics = ["auto", "teleop", "endgame", "scoring", "climb", "defense", "accuracy", "speed"]
        mentioned_metrics = [m for m in metrics if m in question]
        
        # Early detection: Short comparison queries like "5454 and 16"
        if len(team_numbers) >= 2 and len(question.split()) <= 5:
            # This is likely a simple team comparison
            if any(word in question.lower() for word in ['and', 'vs', 'versus', 'v']):
                try:
                    answer = self.compare_teams(team_numbers[0], team_numbers[1])
                    if not answer:
                        logger.error("compare_teams returned None")
                        answer = {"text": f"Could not compare teams {team_numbers[0]} and {team_numbers[1]}.", "error": True}
                    elif not answer.get('error'):
                        # Only add suggestions if no error
                        answer = self._add_proactive_suggestions(answer, question, {'complexity': 'simple', 'requires_comparison': True})
                    self._update_context(original_question, answer, team_numbers, mentioned_metrics)
                    return answer
                except Exception as e:
                    logger.error(f"Error in early comparison detection: {e}", exc_info=True)
                    return {
                        "text": f"I encountered an error comparing teams {team_numbers[0]} and {team_numbers[1]}: {str(e)}",
                        "error": True,
                        "suggestion": "Try asking 'stats for team X' for individual team information."
                    }
        
        # Handle general knowledge queries with external sources
        if is_knowledge_query and not is_data_query:
            knowledge_answer = self._get_external_knowledge(question, original_question)
            if knowledge_answer:
                self._update_context(original_question, knowledge_answer, team_numbers, mentioned_metrics)
                return knowledge_answer
        
        # Handle multi-part queries that combine data + knowledge
        if len(query_parts) > 1:
            combined_answer = self._handle_multi_part_query(query_parts, original_question)
            if combined_answer:
                self._update_context(original_question, combined_answer, team_numbers, mentioned_metrics)
                return combined_answer
        
        # First: try the lightweight NLU intent predictor (if available)
        try:
            from app.assistant.nlu import predict_intent
            intent, confidence = predict_intent(question)
            # If we have a confident intent, dispatch to the mapped handler
            if intent and confidence >= 0.7:  # Slightly lower threshold for better coverage
                intent_map = {
                    'scout_role': self.get_scout_role,
                    'api_docs': self.explain_api_docs,
                    'user_roles': self.get_user_roles,
                    'summarize_help': self.summarize_help_docs,
                    'team_stats': self.get_team_stats,
                    'match_results': self.get_match_results,
                    'team_comparison': self.compare_teams,
                    'best_teams': self.get_best_teams_for_metric,
                    'team_last_match': self.get_team_last_match,
                    'team_trends': self.analyze_team_trends,
                    'team_prediction': self.predict_team_performance,
                    'match_prediction': self.predict_match_winner,
                    'consistency_analysis': self.analyze_consistency,
                    'peak_analysis': self.find_peak_performance,
                    'weakness_analysis': self.analyze_weaknesses,
                    'strength_analysis': self.analyze_strengths
                }
                handler = intent_map.get(intent)
                if handler:
                    # Some intents require extracting an entity (team/match/topic)
                    if intent == 'team_stats':
                        m = re.search(r'team\s*(\d{1,4})', question)
                        if m:
                            ans = handler(m.group(1))
                            self._update_context(original_question, ans, team_numbers, mentioned_metrics)
                            return ans
                    elif intent == 'match_results':
                        m = re.search(r'match\s*(\d{1,4})', question)
                        if m:
                            ans = handler(m.group(1))
                            self._update_context(original_question, ans, team_numbers, mentioned_metrics)
                            return ans
                    elif intent == 'summarize_help':
                        # try to extract a topic after 'for' if present
                        topic = None
                        m = re.search(r'for\s+([\w\s\-\_]+)$', question)
                        if m:
                            topic = m.group(1).strip()
                        ans = handler(topic)
                        self._update_context(original_question, ans, team_numbers, mentioned_metrics)
                        return ans
                    elif intent == 'team_comparison':
                        # Extract two team numbers with improved pattern matching
                        # Try multiple patterns for better extraction
                        teams = []
                        
                        # Pattern 1: "team 5454" style
                        team_matches = re.findall(r'team\s*(\d{1,4})', question)
                        teams.extend(team_matches)
                        
                        # Pattern 2: standalone numbers if we don't have 2 teams yet
                        if len(teams) < 2:
                            standalone = re.findall(r'(?:^|\s)(\d{1,4})(?:\s|$|\b)', question)
                            # Filter to likely team numbers (4 digits or less)
                            for num in standalone:
                                if num not in teams and len(num) <= 4:
                                    teams.append(num)
                        
                        # Remove duplicates while preserving order
                        seen = set()
                        unique_teams = []
                        for t in teams:
                            if t not in seen:
                                seen.add(t)
                                unique_teams.append(t)
                        
                        if len(unique_teams) >= 2:
                            ans = handler(unique_teams[0], unique_teams[1])
                            self._update_context(original_question, ans, team_numbers, mentioned_metrics)
                            return ans
                    elif intent == 'best_teams':
                        # Extract metric if mentioned
                        metric = 'total'
                        for m in ['auto', 'teleop', 'endgame', 'scoring', 'defense']:
                            if m in question:
                                metric = m
                                break
                        ans = handler(metric)
                        self._update_context(original_question, ans, team_numbers, mentioned_metrics)
                        return ans
                    elif intent == 'team_last_match':
                        # Extract team number
                        m = re.search(r'team\s*(\d{1,4})|^(\d{1,4})', question)
                        if m:
                            team_num = m.group(1) or m.group(2)
                            ans = handler(team_num)
                            self._update_context(original_question, ans, team_numbers, mentioned_metrics)
                            return ans
                    elif intent in ['team_trends', 'team_prediction', 'consistency_analysis', 
                                   'peak_analysis', 'weakness_analysis', 'strength_analysis']:
                        # Extract team number for single-team analysis
                        m = re.search(r'team\s*(\d{1,4})|(?:^|\s)(\d{1,4})(?:\s|$)', question)
                        if m:
                            team_num = m.group(1) or m.group(2)
                            ans = handler(team_num)
                            self._update_context(original_question, ans, team_numbers, mentioned_metrics)
                            return ans
                    elif intent == 'match_prediction':
                        # Extract match number
                        m = re.search(r'match\s*(\d{1,4})|(?:^|\s)(\d{1,4})(?:\s|$)', question)
                        if m:
                            match_num = m.group(1) or m.group(2)
                            ans = handler(match_num)
                            self._update_context(original_question, ans, team_numbers, mentioned_metrics)
                            return ans
                    else:
                        ans = handler()
                        self._update_context(original_question, ans, team_numbers, mentioned_metrics)
                        return ans
        except Exception:
            # If NLU module or prediction fails, continue with existing flow
            pass

        # Try to match the question with our patterns
        for pattern, handler in self.patterns:
            match = re.search(pattern, question)
            if match:
                try:
                    answer = handler(*match.groups())
                    # Enhance with intelligent suggestions and related queries
                    answer = self._add_proactive_suggestions(answer, question, question_analysis)
                    self._update_context(original_question, answer, team_numbers, mentioned_metrics)
                    return answer
                except Exception as e:
                    logger.error(f"Error processing question: {e}")
                    return {
                        "text": f"Sorry, I encountered an error while processing your question: {str(e)}",
                        "error": True
                    }

        # If no regex matched, try loose/fuzzy keyword matching to detect intent
        loose = self._fuzzy_detect_intent(question)
        if loose:
            try:
                answer = loose(question)
                self._update_context(original_question, answer, team_numbers, mentioned_metrics)
                return answer
            except Exception as e:
                logger.error(f"Error in loose intent handler: {e}")

        # Next: try semantic search against local help docs (match question to relevant sections)
        try:
            import os
            from app.utils.doc_summarizer import semantic_search_sections, summarize_text
            base_dir = os.path.dirname(os.path.dirname(__file__))
            help_folder = os.path.normpath(os.path.join(base_dir, '..', 'help'))
            if os.path.isdir(help_folder):
                hits = semantic_search_sections(question, help_folder, top_n=2)
                if hits:
                    # Build a combined response from top hit(s)
                    fragments = []
                    citations = []
                    for h in hits:
                        frag = summarize_text(h['section_text'], max_sentences=2)
                        fragments.append(f"{h.get('section_heading') or h['file']}: {frag}")
                        citations.append({
                            'file': h['file'],
                            'path': h['path'],
                            'lines': (h['start'], h['end']),
                            'excerpt': h['section_text'][:800]
                        })
                    resp_text = '\n'.join(fragments[:2])
                    return {
                        'text': resp_text,
                        'citations': citations[:2]
                    }
        except Exception:
            # if semantic search fails, continue to AI fallback
            pass
        
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
        
        # No pattern matched - provide intelligent fallback response
        return {
            "text": (
                "I understand you're looking for information, but I need a bit more context to provide the most helpful answer. "
                "\n\n**Here's what I can help you with:**\n\n"
                "**Team Analysis:**\n"
                "• 'Stats for team 5454' - Get comprehensive performance metrics\n"
                "• 'Compare team 254 and team 1234' - Side-by-side team comparison\n"
                "• 'Best auto scoring teams' - Top performers by specific metrics\n\n"
                "**Match Information:**\n"
                "• 'Match 42 results' - Detailed match breakdown and scores\n"
                "• 'Upcoming matches for team 5454' - Schedule and match predictions\n\n"
                "**Documentation & Help:**\n"
                "• 'Explain scouting' - Learn about effective scouting strategies\n"
                "• 'What are user roles' - Understand permission levels\n"
                "• 'How does the API work' - API documentation and integration guides\n"
                "• 'Summarize help' - Overview of available documentation\n\n"
                "Feel free to ask your question in a different way, or try one of the examples above. "
                "I'm designed to understand natural language, so don't worry about exact phrasing!"
            ),
            "suggestion": "Try rephrasing your question or ask about team stats, matches, or documentation",
            "helpful": True
        }

    def _fuzzy_detect_intent(self, question: str):
        """Return a handler based on fuzzy keyword matching or None."""
        q = question.lower()
        q_norm = self._normalize_text(q)
        tokens = set(q_norm.split())

        # First pass: exact token or substring matches (high confidence)
        for keywords, handler in getattr(self, 'loose_keywords', []):
            for kw in keywords:
                kw_norm = self._normalize_text(kw)
                # exact token match
                if kw_norm in tokens:
                    return handler
                # substring match
                if kw_norm in q_norm:
                    return handler

        # Second pass: token-level fuzzy matching with higher threshold
        best_match = None
        best_score = 0.0
        for keywords, handler in getattr(self, 'loose_keywords', []):
            for kw in keywords:
                kw_norm = self._normalize_text(kw)
                for token in tokens:
                    score = difflib.SequenceMatcher(None, kw_norm, token).ratio()
                    if score > best_score:
                        best_score = score
                        best_match = handler

        if best_score >= 0.78:
            return best_match

        return None

    def _analyze_question(self, question: str) -> Dict[str, Any]:
        """Analyze question to understand intent, complexity, and required reasoning."""
        analysis = {
            'complexity': 'simple',
            'question_type': 'factual',
            'requires_comparison': False,
            'requires_reasoning': False,
            'temporal_aspect': None
        }
        
        # Check for complex multi-part questions
        if any(word in question for word in [' and ', ' or ', ' but ', ' also ']):
            analysis['complexity'] = 'multi_part'
        
        # Check question type
        if question.startswith(('why', 'how come')):
            analysis['question_type'] = 'explanatory'
            analysis['requires_reasoning'] = True
        elif question.startswith(('how', 'what way')):
            analysis['question_type'] = 'procedural'
        elif question.startswith(('should', 'would', 'could')):
            analysis['question_type'] = 'advisory'
            analysis['requires_reasoning'] = True
        elif any(word in question for word in ['compare', 'vs', 'versus', 'better', 'worse', 'difference']):
            analysis['requires_comparison'] = True
        
        # Check for temporal aspects
        if any(word in question for word in ['trend', 'improving', 'getting better', 'over time', 'recently']):
            analysis['temporal_aspect'] = 'trend'
        elif any(word in question for word in ['predict', 'will', 'going to', 'future']):
            analysis['temporal_aspect'] = 'predictive'
        
        # Assess overall complexity
        if analysis['requires_reasoning'] or analysis['requires_comparison']:
            if analysis['complexity'] != 'multi_part':
                analysis['complexity'] = 'complex'
        
        return analysis
    
    def _decompose_query(self, question: str) -> List[str]:
        """Decompose complex queries into multiple sub-queries."""
        # Split on conjunctions that indicate multiple intents
        separators = [' and also ', ' and then ', ' also ', '; ']
        parts = [question]
        
        for sep in separators:
            new_parts = []
            for part in parts:
                if sep in part:
                    new_parts.extend(part.split(sep))
                else:
                    new_parts.append(part)
            parts = new_parts
        
        # Clean and filter parts
        return [p.strip() for p in parts if len(p.strip()) > 3]
    
    def _is_scouting_data_query(self, question: str) -> bool:
        """Detect if query is about scouting data (teams, matches, stats)."""
        data_indicators = [
            r'\bteam\s+\d{1,4}\b',
            r'\bmatch\s+\d{1,4}\b',
            r'\b(stats|statistics|data|performance|score|points)\b',
            r'\b(compare|vs|versus)\b',
            r'\b(best|top|highest|leading)\b.*\bteam',
            r'\b(upcoming|next|schedule)\b.*\bmatch',
            r'\b(alliance|selection|pick)\b'
        ]
        return any(re.search(pattern, question, re.IGNORECASE) for pattern in data_indicators)
    
    def _is_general_knowledge_query(self, question: str) -> bool:
        """Detect if query is about general knowledge (people, concepts, history)."""
        # Don't treat single words as knowledge queries unless they match known entities
        if len(question.split()) <= 1:
            # Check if it's a known FRC entity
            return any(term in question.lower() for term in self.frc_knowledge.keys())
        
        knowledge_indicators = [
            r'^(who is|who was|what is|what was|tell me about|explain)\b',
            r'\b(history|founded|inventor|creator|origin)\b',
            r'\b(dean kamen|woodie flowers|gracious professionalism|coopertition)\b',
            r'\b(meaning|definition|concept|idea)\b'
        ]
        return any(re.search(pattern, question, re.IGNORECASE) for pattern in knowledge_indicators)
    
    def _get_external_knowledge(self, question: str, original_question: str) -> Optional[Dict[str, Any]]:
        """Retrieve knowledge from external sources (Wikipedia, built-in knowledge base)."""
        # First check built-in FRC knowledge
        q_lower = question.lower()
        for term, info in self.frc_knowledge.items():
            if term in q_lower:
                return {
                    'text': f"**{term.title()}**\n\n{info}\n\n*This is core FRC knowledge. Ask me about scouting data for team-specific insights!*",
                    'source': 'frc_knowledge',
                    'formatted': True
                }
        
        # Extract potential entity from query
        entity = self._extract_entity_from_query(question)
        if not entity:
            return None
        
        # Check cache first
        cache_key = entity.lower()
        if cache_key in self.conversation_memory['knowledge_cache']:
            cached = self.conversation_memory['knowledge_cache'][cache_key]
            if cached.get('timestamp'):
                # Use cache if less than 1 hour old
                age = (datetime.now(timezone.utc) - cached['timestamp']).seconds
                if age < 3600:
                    return cached['response']
        
        # Try Wikipedia
        wiki_response = self._query_wikipedia(entity)
        if wiki_response:
            # Cache the response
            self.conversation_memory['knowledge_cache'][cache_key] = {
                'response': wiki_response,
                'timestamp': datetime.now(timezone.utc)
            }
            return wiki_response
        
        return None
    
    def _extract_entity_from_query(self, question: str) -> Optional[str]:
        """Extract the main entity being asked about."""
        # Match "who is X" or "what is X" patterns
        patterns = [
            r'who (?:is|was|are|were)\s+([\w\s]+?)(?:\?|$)',
            r'what (?:is|was|are|were)\s+([\w\s]+?)(?:\?|$)',
            r'tell me about\s+([\w\s]+?)(?:\?|$)',
            r'explain\s+([\w\s]+?)(?:\?|$)'
        ]
        
        for pattern in patterns:
            match = re.search(pattern, question, re.IGNORECASE)
            if match:
                entity = match.group(1).strip()
                # Filter out scouting-specific terms
                if not re.search(r'\b(team|match|score|stat|data|performance)\b', entity, re.IGNORECASE):
                    return entity
        
        return None
    
    def _query_wikipedia(self, entity: str) -> Optional[Dict[str, Any]]:
        """Query Wikipedia API for information about an entity."""
        # Check if requests library is available
        if requests is None:
            logger.warning("requests library not available - Wikipedia features disabled")
            return None
        
        try:
            # Wikipedia API endpoint
            api_url = 'https://en.wikipedia.org/api/rest_v1/page/summary/'
            
            # Clean entity name for URL
            entity_url = entity.replace(' ', '_')
            
            # Make request with timeout
            response = requests.get(
                f"{api_url}{entity_url}",
                timeout=5,
                headers={
                    'User-Agent': 'FRC-Scouting-Assistant/1.0',
                    'Accept': 'application/json'
                }
            )
            
            if response.status_code == 200:
                # Check if response is actually JSON
                content_type = response.headers.get('Content-Type', '')
                if 'json' not in content_type.lower():
                    logger.warning(f"Wikipedia returned non-JSON content for {entity}: {content_type}")
                    return None
                
                try:
                    data = response.json()
                except ValueError as e:
                    logger.error(f"Failed to parse Wikipedia JSON for {entity}: {e}")
                    return None
                
                # Extract key information
                title = data.get('title', entity)
                extract = data.get('extract', '')
                url = data.get('content_urls', {}).get('desktop', {}).get('page', '')
                
                if extract:
                    # Limit extract length
                    if len(extract) > 500:
                        extract = extract[:500] + '...'
                    
                    response_text = f"**{title}** (via Wikipedia)\n\n{extract}\n\n"
                    
                    if url:
                        response_text += f" [Read more on Wikipedia]({url})\n\n"
                    
                    response_text += "*This is general knowledge. Ask me about scouting data for team-specific insights!*"
                    
                    return {
                        'text': response_text,
                        'source': 'wikipedia',
                        'entity': title,
                        'url': url,
                        'formatted': True
                    }
            elif response.status_code == 404:
                logger.info(f"Wikipedia page not found for: {entity}")
                return None
            else:
                logger.warning(f"Wikipedia API returned status {response.status_code} for: {entity}")
                return None
            
        except Exception as e:
            if 'Timeout' in str(type(e).__name__):
                logger.warning(f"Wikipedia query timeout for entity: {entity}")
            else:
                logger.error(f"Error querying Wikipedia for {entity}: {e}")
            return None
    
    def _handle_multi_part_query(self, query_parts: List[str], original_question: str) -> Optional[Dict[str, Any]]:
        """Handle queries with multiple intents by answering each part."""
        if len(query_parts) <= 1:
            return None
        
        # Prevent infinite recursion
        if hasattr(self, '_in_multipart') and self._in_multipart:
            return None
        
        # Answer each part separately
        answers = []
        self._in_multipart = True
        
        try:
            for idx, part in enumerate(query_parts[:3], 1):  # Limit to 3 parts
                try:
                    part_answer = self.answer_question(part)
                
                    if part_answer and not part_answer.get('error'):
                        part_text = part_answer.get('text', '')
                        # Truncate if too long
                        if len(part_text) > 400:
                            part_text = part_text[:400] + '...'
                        answers.append({
                            'query': part,
                            'answer': part_text,
                            'number': idx
                        })
                except Exception as e:
                    logger.error(f"Error processing query part '{part}': {e}")
                    continue
        finally:
            # Always clean up recursion flag
            self._in_multipart = False
        
        if len(answers) >= 2:
            # Synthesize combined response
            response_text = "**Multi-Part Query Response**\n\n"
            response_text += "I've broken down your question into parts:\n\n"
            
            for ans in answers:
                response_text += f"**{ans['number']}. {ans['query']}**\n{ans['answer']}\n\n---\n\n"
            
            response_text += "*I can answer each part separately if you'd like more detail on any aspect.*"
            
            return {
                'text': response_text,
                'multi_part': True,
                'parts': answers,
                'formatted': True
            }
        
        return None
    
    def _generate_intelligent_response(self, base_response: Dict[str, Any], question_analysis: Dict[str, Any], question: str) -> Dict[str, Any]:
        """Enhance base response with intelligent reasoning and context."""
        text = base_response.get('text', '')
        
        # Add reasoning for explanatory questions
        if question_analysis['question_type'] == 'explanatory' and 'why' in question.lower():
            # Add contextual reasoning
            if 'team' in base_response:
                team_num = base_response['team'].get('number')
                if team_num:
                    reasoning = f"\n\n**Analysis:** Based on the data patterns for Team {team_num}, "
                    reasoning += "this performance profile suggests strategic design choices optimized for specific game elements. "
                    reasoning += "Consider how these metrics align with successful alliance strategies in recent competitions."
                    text += reasoning
        
        # Add comparative insights
        if question_analysis['requires_comparison'] and 'teams' in base_response:
            teams = base_response.get('teams', [])
            if len(teams) >= 2:
                insight = "\n\n**Comparative Insight:** "
                insight += "When evaluating these teams for alliance selection, consider not just raw scores but consistency, "
                insight += "complementary capabilities, and performance under pressure in elimination matches."
                text += insight
        
        # Add conversational elements
        if self.conversation_memory['conversation_depth'] > 3:
            followup = "\n\n*I'm building context from our conversation. Feel free to ask follow-up questions or dive deeper into any specific aspect.*"
            text += followup
        
        base_response['text'] = text
        base_response['enhanced'] = True
        return base_response
    
    def _add_proactive_suggestions(self, response: Dict[str, Any], question: str, analysis: Dict[str, Any]) -> Dict[str, Any]:
        """Add intelligent, proactive suggestions for follow-up queries based on context."""
        suggestions = []
        
        # Team-specific suggestions
        if 'team' in response and response['team']:
            team_num = response['team'].get('number')
            if team_num:
                # Check conversation memory for potential comparisons
                recent_teams = [t for t in self.conversation_memory['recent_teams'] if t != team_num]
                if recent_teams and len(recent_teams) > 0:
                    other_team = recent_teams[-1]
                    suggestions.append(f"Compare with team {other_team}")
                else:
                    suggestions.append(f"Compare team {team_num} with another team")
                
                if 'match' not in question.lower():
                    suggestions.append(f"Show upcoming matches for team {team_num}")
        
        # Comparison suggestions
        if 'teams' in response and len(response.get('teams', [])) >= 2:
            suggestions.append("Analyze individual team strengths in detail")
            suggestions.append("Show other teams with similar performance")
        
        # Match-related suggestions
        if 'match' in response:
            suggestions.append("Show team statistics from this match")
            suggestions.append("View upcoming matches")
        
        # Documentation suggestions
        if response.get('topic') in ['scout_role', 'api', 'user_roles']:
            suggestions.append("Ask about specific implementation details")
            suggestions.append("Summarize other help topics")
        
        # Add contextual suggestions based on conversation depth
        if self.conversation_memory['conversation_depth'] > 2 and not suggestions:
            suggestions.append("Ask about team comparisons")
            suggestions.append("View top performing teams")
        
        # Add suggestions to response
        if suggestions:
            suggestion_text = "\\n\\n**\ud83d\udca1 You might also want to:**\\n"
            for idx, sugg in enumerate(suggestions[:3], 1):  # Limit to 3 suggestions
                suggestion_text += f"  {idx}. {sugg}\\n"
            
            response['text'] = response.get('text', '') + suggestion_text
            response['suggestions'] = suggestions[:3]
        
        return response
    
    def _normalize_text(self, text: str) -> str:
        """Lowercase, remove punctuation, collapse whitespace, and handle a few common misspellings."""
        t = text.lower()
        # remove punctuation
        t = t.translate(str.maketrans('', '', string.punctuation))
        # basic misspelling corrections (can be extended)
        corrections = {
            'explane': 'explain',
            'summarize': 'summarize',
            'summarise': 'summarize',
            'scoutng': 'scouting'
        }
        for bad, good in corrections.items():
            t = t.replace(bad, good)
        # collapse whitespace
        t = ' '.join(t.split())
        return t

    def get_scout_role(self, _unused=None) -> Dict[str, Any]:
        """Return a helpful, intelligent description of the scout role in FRC and how the app supports it."""
        text = (
            "**Understanding the Scout Role in FRC**\n\n"
            "In FIRST Robotics Competition (FRC), scouting is a critical strategic function that involves systematically "
            "observing and recording robot performance data during matches. A scout's primary responsibility is to collect "
            "accurate, objective information about robot capabilities, strengths, and weaknesses.\n\n"
            "**Key Responsibilities:**\n"
            "• **Autonomous Period**: Track scoring accuracy, starting position, and reliability\n"
            "• **Teleoperated Period**: Document game piece manipulation, cycle times, and scoring consistency\n"
            "• **Endgame**: Record climbing ability, positioning success, and bonus point contributions\n"
            "• **Qualitative Observations**: Note defensive play, driver skill, mechanical reliability, and strategic tendencies\n\n"
            "**Best Practices for Effective Scouting:**\n"
            "• Maintain consistency across all matches using standardized metrics\n"
            "• Focus on observable, measurable behaviors rather than subjective opinions\n"
            "• Record data in real-time to ensure accuracy\n"
            "• Include brief notes on exceptional performances or mechanical issues\n\n"
        )
        app_help = (
            "**How This Application Supports Your Scouting Efforts:**\n\n"
            "Our intelligent scouting platform streamlines the entire data collection and analysis process:\n"
            "• **Structured Forms**: Customizable scouting interfaces aligned with current game mechanics\n"
            "• **Real-time Sync**: Automatic data synchronization across devices for seamless team collaboration\n"
            "• **Advanced Analytics**: Automated calculation of team metrics, trends, and performance predictions\n"
            "• **Visual Insights**: Interactive charts and graphs for quick pattern recognition\n"
            "• **Smart Assistant**: Natural language queries to instantly access any data point or analysis\n"
            "• **Alliance Selection Tools**: Data-driven recommendations for optimal alliance choices\n\n"
            "You can ask me specific questions like 'stats for team 5454' or 'compare team 254 and team 1234' to dive deeper into the data."
        )
        return {"text": f"{text}{app_help}", "topic": "scout_role", "formatted": True}

    def explain_api_docs(self, _unused=None) -> Dict[str, Any]:
        """Provide intelligent explanation of the application's API with comprehensive details."""
        # Attempt to find local API documentation in help folder
        try:
            import os
            from app.utils.doc_summarizer import summarize_markdown_file
            base_dir = os.path.dirname(os.path.dirname(__file__))
            help_folder = os.path.normpath(os.path.join(base_dir, '..', 'help'))
            candidates = [f for f in os.listdir(help_folder) if 'api' in f.lower() and f.lower().endswith('.md')]
            if candidates:
                path = os.path.join(help_folder, candidates[0])
                s = summarize_markdown_file(path)
                enhanced_text = (
                    f"**API Documentation Overview**\n\n"
                    f"{s.get('summary')}\n\n"
                    f"The API provides programmatic access to all scouting data and analytics. "
                    f"For complete endpoint details, authentication requirements, and request/response examples, "
                    f"please refer to the full API documentation."
                )
                return {"text": enhanced_text, "citation": s.get('citation'), "formatted": True}
        except Exception:
            pass

        # Enhanced generic explanation
        generic = (
            "**Application Programming Interface (API)**\n\n"
            "Our RESTful API provides secure, programmatic access to the scouting platform's data and functionality. "
            "The API enables integration with external tools, custom analytics pipelines, and automated workflows.\n\n"
            "**Key Capabilities:**\n"
            "• **Team Data Retrieval**: Access comprehensive team statistics, performance metrics, and historical data\n"
            "• **Match Information**: Query match schedules, results, and detailed breakdowns\n"
            "• **Scouting Data**: Retrieve individual scouting entries and aggregated analytics\n"
            "• **Real-time Updates**: Subscribe to live data feeds during competitions\n\n"
            "**Standard Features:**\n"
            "• JSON response format for easy parsing\n"
            "• RESTful design principles for intuitive endpoint structure\n"
            "• Authentication and authorization for secure access\n"
            "• Comprehensive error handling with descriptive status codes\n\n"
            "For detailed endpoint documentation, request formats, and code examples, "
            "please refer to the API_DOCUMENTATION.md file in the help folder or ask me to summarize specific sections."
        )
        return {"text": generic, "topic": "api", "formatted": True}

    def get_user_roles(self, _unused=None) -> Dict[str, Any]:
        """Provide intelligent explanation of user roles and permissions with context."""
        try:
            import os
            from app.utils.doc_summarizer import summarize_markdown_file
            base_dir = os.path.dirname(os.path.dirname(__file__))
            help_folder = os.path.normpath(os.path.join(base_dir, '..', 'help'))
            candidates = [f for f in os.listdir(help_folder) if 'role' in f.lower() or 'permissions' in f.lower()]
            if candidates:
                path = os.path.join(help_folder, candidates[0])
                s = summarize_markdown_file(path)
                enhanced_text = (
                    f"**{s.get('title', 'User Roles and Permissions')}**\n\n"
                    f"{s.get('summary')}\n\n"
                    f"Understanding these role distinctions helps ensure proper access control and data security "
                    f"while enabling team members to efficiently perform their designated functions."
                )
                return {"text": enhanced_text, "citation": s.get('citation'), "formatted": True}
        except Exception:
            pass

        # Enhanced generic explanation with better formatting
        text = (
            "**User Roles and Permission Levels**\n\n"
            "The application implements a role-based access control (RBAC) system to ensure security "
            "and appropriate access to functionality based on user responsibilities.\n\n"
            "**Role Hierarchy:**\n\n"
            "**• Superadmin (Highest Privilege)**\n"
            "  - Full system administration access\n"
            "  - User account management and role assignment\n"
            "  - System configuration and security settings\n"
            "  - Database management and backup operations\n"
            "  - Application-wide settings and game configuration\n\n"
            "**• Admin (Team Leadership)**\n"
            "  - Team-level data management and oversight\n"
            "  - Match schedule and event configuration\n"
            "  - Analytics and reporting access\n"
            "  - Scout assignment and workflow management\n"
            "  - AI assistant configuration\n\n"
            "**• Scout/User (Standard Access)**\n"
            "  - Create and submit scouting entries\n"
            "  - View team statistics and match data\n"
            "  - Access assigned scouting workflows\n"
            "  - Use the intelligent assistant for queries\n"
            "  - Generate standard reports and visualizations\n\n"
            "**Security Note:** Permission levels are enforced at both the UI and API layers to prevent "
            "unauthorized access. For deployment-specific role configurations, please consult your "
            "team's administrator or refer to the USER_ROLES_AND_PERMISSIONS.md documentation."
        )
        return {"text": text, "topic": "user_roles", "formatted": True}
    
    def analyze_team_trends(self, team_number: str) -> Dict[str, Any]:
        """Analyze performance trends and trajectory for a team over time."""
        try:
            team = Team.query.filter_by(team_number=safe_int_team_number(team_number)).first()
            if not team:
                return {"text": f"Team {team_number} not found in the database."}
            
            # Get all scouting entries ordered by match
            # Exclude alliance-copied data when not in alliance mode
            scouting_team_num = self._get_scouting_team_number()
            query = ScoutingData.query.filter_by(team_id=team.id)
            if scouting_team_num:
                query = query.filter_by(scouting_team_number=scouting_team_num)
            # Exclude alliance-copied data
            from sqlalchemy import or_
            query = query.filter(
                or_(
                    ScoutingData.scout_name == None,
                    ~ScoutingData.scout_name.like('[Alliance-%')
                )
            )
            entries = query.join(Match).order_by(Match.match_number).all()
            
            if len(entries) < 3:
                return {"text": f"Not enough data to analyze trends for Team {team_number}. Need at least 3 matches."}
            
            # Calculate trends over time
            match_scores = []
            for entry in entries:
                # Use calculate_metric to get point values
                auto = entry.calculate_metric('apt') or 0
                teleop = entry.calculate_metric('tpt') or 0
                endgame = entry.calculate_metric('ept') or 0
                total = entry.calculate_metric('tot') or (auto + teleop + endgame)
                match_scores.append({
                    'match': entry.match_id,
                    'match_number': entry.match.match_number if entry.match else 0,
                    'total': total,
                    'score': total,  # Add for visualizer compatibility
                    'auto': auto,
                    'teleop': teleop,
                    'endgame': endgame
                })
            
            # Analyze trend direction
            first_half_avg = sum(m['total'] for m in match_scores[:len(match_scores)//2]) / (len(match_scores)//2)
            second_half_avg = sum(m['total'] for m in match_scores[len(match_scores)//2:]) / (len(match_scores) - len(match_scores)//2)
            
            trend_diff = second_half_avg - first_half_avg
            trend_pct = (trend_diff / max(first_half_avg, 1)) * 100
            
            # Build response
            response_text = f" **Trend Analysis for Team {team_number}**\n\n"
            
            if trend_pct > 15:
                response_text += f" **Trajectory:** Strongly improving (+{trend_pct:.1f}%)\n"
                response_text += f"Team {team_number} is showing significant improvement over their matches. "
                response_text += f"Average score increased from {first_half_avg:.1f} to {second_half_avg:.1f} points.\n\n"
            elif trend_pct > 5:
                response_text += f" **Trajectory:** Steadily improving (+{trend_pct:.1f}%)\n"
                response_text += f"Team {team_number} is getting better with each match. "
                response_text += f"Average score increased from {first_half_avg:.1f} to {second_half_avg:.1f} points.\n\n"
            elif trend_pct > -5:
                response_text += f"️ **Trajectory:** Stable ({trend_pct:+.1f}%)\n"
                response_text += f"Team {team_number} is performing consistently across matches with minimal variation.\n\n"
            elif trend_pct > -15:
                response_text += f"️ **Trajectory:** Declining ({trend_pct:.1f}%)\n"
                response_text += f"Team {team_number} performance has decreased from {first_half_avg:.1f} to {second_half_avg:.1f} points.\n\n"
            else:
                response_text += f" **Trajectory:** Significantly declining ({trend_pct:.1f}%)\n"
                response_text += f"Team {team_number} is showing concerning performance drop.\n\n"
            
            # Recent performance
            recent = match_scores[-3:]
            recent_avg = sum(m['total'] for m in recent) / len(recent)
            response_text += f" **Recent Form (Last 3 Matches):** {recent_avg:.1f} avg points\n\n"
            
            # Component analysis
            auto_trend = sum(m['auto'] for m in match_scores[len(match_scores)//2:]) / (len(match_scores) - len(match_scores)//2) - \
                        sum(m['auto'] for m in match_scores[:len(match_scores)//2]) / (len(match_scores)//2)
            teleop_trend = sum(m['teleop'] for m in match_scores[len(match_scores)//2:]) / (len(match_scores) - len(match_scores)//2) - \
                          sum(m['teleop'] for m in match_scores[:len(match_scores)//2]) / (len(match_scores)//2)
            
            response_text += "**Component Trends:**\n"
            if auto_trend > 2:
                response_text += f"  • Autonomous: Improving significantly (+{auto_trend:.1f})\n"
            elif auto_trend > 0:
                response_text += f"  • Autonomous: Slightly improving (+{auto_trend:.1f})\n"
            else:
                response_text += f"  • Autonomous: Declining ({auto_trend:.1f})\n"
            
            if teleop_trend > 5:
                response_text += f"  • Teleoperated: Major improvement (+{teleop_trend:.1f})\n"
            elif teleop_trend > 0:
                response_text += f"  • Teleoperated: Improving (+{teleop_trend:.1f})\n"
            else:
                response_text += f"  • Teleoperated: Declining ({teleop_trend:.1f})\n"
            
            # Calculate linear regression for trend line
            x_vals = list(range(len(match_scores)))
            y_vals = [m['total'] for m in match_scores]
            
            # Simple linear regression
            n = len(x_vals)
            x_mean = sum(x_vals) / n
            y_mean = sum(y_vals) / n
            
            numerator = sum((x - x_mean) * (y - y_mean) for x, y in zip(x_vals, y_vals))
            denominator = sum((x - x_mean) ** 2 for x in x_vals)
            
            slope = numerator / denominator if denominator != 0 else 0
            intercept = y_mean - slope * x_mean
            
            return {
                "text": response_text,
                "trend_data": {
                    "team_number": team_number,
                    "matches_analyzed": len(match_scores),
                    "trend_percentage": trend_pct,
                    "first_half_avg": first_half_avg,
                    "second_half_avg": second_half_avg,
                    "recent_avg": recent_avg
                },
                # Frontend expects a list of visualization option keys; include the type name
                "visualization_options": ["trend_chart"],
                # Provide the actual visualization payload in a predictable key so the
                # frontend will POST the full response object to /assistant/visualize
                "visualization_data": {
                    "team_number": team_number,
                    "match_scores": match_scores,
                    "slope": slope,
                    "intercept": intercept
                }
            }
        except Exception as e:
            logger.error(f"Error analyzing trends for team {team_number}: {e}")
            return {"text": f"Error analyzing trends: {str(e)}", "error": True}
    
    def predict_team_performance(self, team_number: str) -> Dict[str, Any]:
        """Predict future performance based on historical trends."""
        try:
            # Get trend analysis first
            trend_result = self.analyze_team_trends(team_number)
            if trend_result.get('error'):
                return trend_result
            
            trend_data = trend_result.get('trend_data', {})
            trend_pct = trend_data.get('trend_percentage', 0)
            recent_avg = trend_data.get('recent_avg', 0)
            
            # Make prediction
            predicted_score = recent_avg * (1 + trend_pct / 200)  # Conservative prediction
            
            response_text = f" **Performance Prediction for Team {team_number}**\n\n"
            response_text += f"**Predicted Next Match Score:** {predicted_score:.1f} points\n\n"
            
            confidence = min(95, 50 + abs(trend_pct) * 2)
            response_text += f"**Confidence Level:** {confidence:.0f}%\n\n"
            
            if trend_pct > 10:
                response_text += " **Outlook:** Based on their improving trend, expect strong performance. "
                response_text += f"Team {team_number} is likely to score around {predicted_score:.0f} points.\n\n"
            elif trend_pct < -10:
                response_text += " **Outlook:** Recent decline suggests caution. "
                response_text += f"Performance may drop to around {predicted_score:.0f} points.\n\n"
            else:
                response_text += "️ **Outlook:** Consistent performance expected. "
                response_text += f"Team {team_number} should score around {predicted_score:.0f} points.\n\n"
            
            response_text += "**Recommendation:** "
            if predicted_score > 70:
                response_text += "High-value alliance pick. Strong scoring potential."
            elif predicted_score > 40:
                response_text += "Solid mid-tier performer. Reliable for balanced alliances."
            else:
                response_text += "Developing team. Consider role specialization."
            
            return {
                "text": response_text,
                "prediction": {
                    "team_number": team_number,
                    "predicted_score": predicted_score,
                    "confidence": confidence,
                    "trend_pct": trend_pct
                }
            }
        except Exception as e:
            logger.error(f"Error predicting performance for team {team_number}: {e}")
            return {"text": f"Error making prediction: {str(e)}", "error": True}
    
    def predict_match_outcome(self, team_number: str) -> Dict[str, Any]:
        """Predict if a team will win their next match."""
        return self.predict_team_performance(team_number)
    
    def predict_match_winner(self, match_number: str) -> Dict[str, Any]:
        """Predict the winner of a specific match."""
        try:
            match = Match.query.filter_by(match_number=int(match_number)).first()
            if not match:
                return {"text": f"Match {match_number} not found."}
            
            # Get teams in match
            red_teams = match.red_teams
            blue_teams = match.blue_teams
            
            if not red_teams or not blue_teams:
                return {"text": f"Match {match_number} does not have complete alliance information."}
            
            # Calculate alliance strengths
            from app.utils.analytics import calculate_team_metrics
            
            red_strength = 0
            for team_num in red_teams:
                team = Team.query.filter_by(team_number=safe_int_team_number(team_num)).first()
                if team:
                    metrics = calculate_team_metrics(team.id).get('metrics', {})
                    red_strength += metrics.get('total_points', 0) or 0
            
            blue_strength = 0
            for team_num in blue_teams:
                team = Team.query.filter_by(team_number=safe_int_team_number(team_num)).first()
                if team:
                    metrics = calculate_team_metrics(team.id).get('metrics', {})
                    blue_strength += metrics.get('total_points', 0) or 0
            
            # Make prediction
            total_strength = red_strength + blue_strength
            red_probability = (red_strength / max(total_strength, 1)) * 100 if total_strength > 0 else 50
            blue_probability = 100 - red_probability
            
            response_text = f" **Match {match_number} Prediction**\n\n"
            response_text += f"**Red Alliance:** {', '.join(map(str, red_teams))}\n"
            response_text += f"**Blue Alliance:** {', '.join(map(str, blue_teams))}\n\n"
            
            if red_probability > 60:
                response_text += f" **Predicted Winner:** Red Alliance ({red_probability:.0f}% confidence)\n"
                response_text += f"**Predicted Score:** Red {red_strength:.0f} - Blue {blue_strength:.0f}\n"
            elif blue_probability > 60:
                response_text += f" **Predicted Winner:** Blue Alliance ({blue_probability:.0f}% confidence)\n"
                response_text += f"**Predicted Score:** Blue {blue_strength:.0f} - Red {red_strength:.0f}\n"
            else:
                response_text += f"️ **Prediction:** Close match! Too close to call confidently.\n"
                response_text += f"**Estimated Scores:** Red {red_strength:.0f} - Blue {blue_strength:.0f}\n"
            
            return {
                "text": response_text,
                "prediction": {
                    "match_number": match_number,
                    "red_probability": red_probability,
                    "blue_probability": blue_probability,
                    "red_strength": red_strength,
                    "blue_strength": blue_strength
                }
            }
        except Exception as e:
            logger.error(f"Error predicting match {match_number}: {e}")
            return {"text": f"Error making prediction: {str(e)}", "error": True}
    
    def compare_historical(self, team_number: str, timeframe: str) -> Dict[str, Any]:
        """Compare current performance to historical data."""
        return {"text": f"Historical comparison for Team {team_number} vs {timeframe} coming soon! This feature requires historical event data."}
    
    def analyze_consistency(self, team_number: str) -> Dict[str, Any]:
        """Analyze how consistent a team's performance is."""
        try:
            team = Team.query.filter_by(team_number=safe_int_team_number(team_number)).first()
            if not team:
                return {"text": f"Team {team_number} not found."}
            
            scouting_team_num = self._get_scouting_team_number()
            query = ScoutingData.query.filter_by(team_id=team.id)
            if scouting_team_num:
                query = query.filter_by(scouting_team_number=scouting_team_num)
            # Exclude alliance-copied data
            from sqlalchemy import or_
            query = query.filter(
                or_(
                    ScoutingData.scout_name == None,
                    ~ScoutingData.scout_name.like('[Alliance-%')
                )
            )
            entries = query.all()
            
            if len(entries) < 3:
                return {"text": f"Not enough data to analyze consistency for Team {team_number}."}
            
            # Calculate scores using metrics
            scores = [e.calculate_metric('tot') or 0 for e in entries]
            avg = sum(scores) / len(scores)
            variance = sum((s - avg) ** 2 for s in scores) / len(scores)
            std_dev = variance ** 0.5
            coefficient_of_variation = (std_dev / max(avg, 1)) * 100
            
            response_text = f" **Consistency Analysis for Team {team_number}**\n\n"
            response_text += f"**Average Score:** {avg:.1f} points\n"
            response_text += f"**Standard Deviation:** {std_dev:.1f}\n"
            response_text += f"**Coefficient of Variation:** {coefficient_of_variation:.1f}%\n\n"
            
            if coefficient_of_variation < 15:
                response_text += " **Rating:** Extremely consistent - very reliable performer\n"
                response_text += "This team delivers predictable results match after match."
            elif coefficient_of_variation < 25:
                response_text += " **Rating:** Consistent - dependable team\n"
                response_text += "This team usually performs close to their average."
            elif coefficient_of_variation < 40:
                response_text += "️ **Rating:** Somewhat inconsistent - variable performance\n"
                response_text += "This team can have good matches but also struggles sometimes."
            else:
                response_text += " **Rating:** Highly inconsistent - unpredictable\n"
                response_text += "This team's performance varies significantly between matches."
            
            return {
                "text": response_text,
                "consistency": {
                    "team_number": team_number,
                    "avg_score": avg,
                    "std_dev": std_dev,
                    "cv": coefficient_of_variation,
                    "matches_analyzed": len(scores)
                }
            }
        except Exception as e:
            logger.error(f"Error analyzing consistency for team {team_number}: {e}")
            return {"text": f"Error analyzing consistency: {str(e)}", "error": True}
    
    def find_peak_performance(self, team_number: str) -> Dict[str, Any]:
        """Find the team's best match and optimal conditions."""
        try:
            team = Team.query.filter_by(team_number=safe_int_team_number(team_number)).first()
            if not team:
                return {"text": f"Team {team_number} not found."}
            
            # Exclude alliance-copied data
            from sqlalchemy import or_
            entries = ScoutingData.query.filter_by(
                team_id=team.id,
                scouting_team_number=current_user.scouting_team_number
            ).filter(
                or_(
                    ScoutingData.scout_name == None,
                    ~ScoutingData.scout_name.like('[Alliance-%')
                )
            ).join(Match).order_by(Match.match_number).all()
            
            if not entries:
                return {"text": f"No scouting data for Team {team_number}."}
            
            # Find peak performance
            best_entry = max(entries, key=lambda e: e.calculate_metric('tot') or 0)
            best_score = best_entry.calculate_metric('tot') or 0
            
            response_text = f"⭐ **Peak Performance for Team {team_number}**\n\n"
            response_text += f"**Best Match:** Match {best_entry.match_id}\n"
            response_text += f"**Peak Score:** {best_score:.0f} points\n\n"
            response_text += f"**Breakdown:**\n"
            response_text += f"  • Autonomous: {best_entry.calculate_metric('apt') or 0:.0f} pts\n"
            response_text += f"  • Teleoperated: {best_entry.calculate_metric('tpt') or 0:.0f} pts\n"
            response_text += f"  • Endgame: {best_entry.calculate_metric('ept') or 0:.0f} pts\n\n"
            
            avg_score = sum(e.calculate_metric('tot') or 0 for e in entries) / len(entries)
            improvement_potential = best_score - avg_score
            
            response_text += f"**Analysis:** This team's peak is {improvement_potential:.0f} points above their average. "
            if improvement_potential > 20:
                response_text += "They have high ceiling potential when performing optimally!"
            else:
                response_text += "They perform consistently near their peak."
            
            return {"text": response_text}
        except Exception as e:
            logger.error(f"Error finding peak for team {team_number}: {e}")
            return {"text": f"Error finding peak performance: {str(e)}", "error": True}
    
    def analyze_weaknesses(self, team_number: str) -> Dict[str, Any]:
        """Identify team weaknesses based on data."""
        try:
            team = Team.query.filter_by(team_number=safe_int_team_number(team_number)).first()
            if not team:
                return {"text": f"Team {team_number} not found."}
            
            analytics_result = calculate_team_metrics(team.id)
            stats = analytics_result.get('metrics', {})
            
            if not stats:
                return {"text": f"No data available for Team {team_number}."}
            
            response_text = f" **Weakness Analysis for Team {team_number}**\n\n"
            
            weaknesses = []
            auto = stats.get('auto_points', 0) or 0
            teleop = stats.get('teleop_points', 0) or 0
            endgame = stats.get('endgame_points', 0) or 0
            total = auto + teleop + endgame
            
            if auto < 10:
                weaknesses.append(f"️ **Weak Autonomous** ({auto:.1f} pts avg) - Limited auto scoring ability")
            if teleop < 20:
                weaknesses.append(f"️ **Low Teleoperated Output** ({teleop:.1f} pts avg) - Struggles during driver control")
            if endgame < 5:
                weaknesses.append(f"️ **Minimal Endgame** ({endgame:.1f} pts avg) - Missing endgame opportunities")
            if total < 30:
                weaknesses.append(f"️ **Overall Low Scoring** ({total:.1f} pts avg) - Needs improvement across all phases")
            
            if weaknesses:
                response_text += "\n".join(weaknesses)
                response_text += "\n\n**Recommendation:** Focus scouting efforts on how they can improve these areas or pair with alliance partners who excel here."
            else:
                response_text += " No significant weaknesses detected! Team {team_number} is performing well across all game phases."
            
            return {"text": response_text}
        except Exception as e:
            logger.error(f"Error analyzing weaknesses for team {team_number}: {e}")
            return {"text": f"Error analyzing weaknesses: {str(e)}", "error": True}
    
    def analyze_strengths(self, team_number: str) -> Dict[str, Any]:
        """Identify team strengths based on data."""
        try:
            team = Team.query.filter_by(team_number=safe_int_team_number(team_number)).first()
            if not team:
                return {"text": f"Team {team_number} not found."}
            
            analytics_result = calculate_team_metrics(team.id)
            stats = analytics_result.get('metrics', {})
            
            if not stats:
                return {"text": f"No data available for Team {team_number}."}
            
            response_text = f" **Strength Analysis for Team {team_number}**\n\n"
            
            strengths = []
            auto = stats.get('auto_points', 0) or 0
            teleop = stats.get('teleop_points', 0) or 0
            endgame = stats.get('endgame_points', 0) or 0
            total = auto + teleop + endgame
            
            if auto > 20:
                strengths.append(f"⭐ **Excellent Autonomous** ({auto:.1f} pts avg) - Strong auto scorer")
            elif auto > 10:
                strengths.append(f" **Good Autonomous** ({auto:.1f} pts avg) - Reliable auto points")
            
            if teleop > 50:
                strengths.append(f"⭐ **Dominant Teleoperated** ({teleop:.1f} pts avg) - Elite driver control")
            elif teleop > 30:
                strengths.append(f" **Strong Teleoperated** ({teleop:.1f} pts avg) - Good scoring during driver period")
            
            if endgame > 20:
                strengths.append(f"⭐ **Elite Endgame** ({endgame:.1f} pts avg) - Consistent endgame execution")
            elif endgame > 10:
                strengths.append(f" **Solid Endgame** ({endgame:.1f} pts avg) - Reliable endgame points")
            
            if total > 80:
                strengths.append(f" **Elite Overall Scorer** ({total:.1f} pts avg) - Top-tier performance")
            elif total > 50:
                strengths.append(f" **Strong Overall Performance** ({total:.1f} pts avg) - Solid all-around team")
            
            if strengths:
                response_text += "\n".join(strengths)
                response_text += f"\n\n**Alliance Value:** Excellent pick for alliances needing "
                if auto > teleop and auto > endgame:
                    response_text += "autonomous points."
                elif teleop > auto and teleop > endgame:
                    response_text += "consistent teleoperated scoring."
                elif endgame > auto and endgame > teleop:
                    response_text += "endgame specialists."
                else:
                    response_text += "balanced, versatile performers."
            else:
                response_text += " Team is developing - strengths not yet clearly defined. Monitor for emerging capabilities."
            
            return {"text": response_text}
        except Exception as e:
            logger.error(f"Error analyzing strengths for team {team_number}: {e}")
            return {"text": f"Error analyzing strengths: {str(e)}", "error": True}
    
    def predict_alliance(self, team1: str, team2: str) -> Dict[str, Any]:
        """Predict how well two teams would work together in an alliance."""
        try:
            from app.utils.analytics import calculate_team_metrics
            
            t1 = Team.query.filter_by(team_number=safe_int_team_number(team1)).first()
            t2 = Team.query.filter_by(team_number=safe_int_team_number(team2)).first()
            
            if not t1 or not t2:
                return {"text": f"One or both teams not found."}
            
            metrics1 = calculate_team_metrics(t1.id).get('metrics', {})
            metrics2 = calculate_team_metrics(t2.id).get('metrics', {})
            
            # Calculate combined potential
            combined_score = (metrics1.get('total_points', 0) or 0) + (metrics2.get('total_points', 0) or 0)
            
            # Analyze synergy
            auto1 = metrics1.get('auto_points', 0) or 0
            auto2 = metrics2.get('auto_points', 0) or 0
            teleop1 = metrics1.get('teleop_points', 0) or 0
            teleop2 = metrics2.get('teleop_points', 0) or 0
            
            response_text = f" **Alliance Prediction: Team {team1} + Team {team2}**\n\n"
            response_text += f"**Combined Scoring Potential:** {combined_score:.0f} points\n\n"
            
            synergies = []
            if auto1 > 15 or auto2 > 15:
                synergies.append(" Strong autonomous coverage")
            if teleop1 + teleop2 > 60:
                synergies.append(" Excellent teleoperated scoring")
            if combined_score > 100:
                synergies.append(" Elite total output - championship-caliber alliance")
            
            if synergies:
                response_text += "**Synergies:**\n" + "\n".join(f"  {s}" for s in synergies) + "\n\n"
            
            if combined_score > 120:
                response_text += " **Rating:** Exceptional alliance - strong contender for elimination rounds"
            elif combined_score > 80:
                response_text += " **Rating:** Solid alliance - good playoff potential"
            elif combined_score > 50:
                response_text += "️ **Rating:** Moderate alliance - can compete effectively"
            else:
                response_text += "️ **Rating:** Developing alliance - may struggle in competitive matches"
            
            return {
                "text": response_text,
                "alliance_prediction": {
                    "team1": team1,
                    "team2": team2,
                    "combined_score": combined_score,
                    "synergy_level": len(synergies)
                }
            }
        except Exception as e:
            logger.error(f"Error predicting alliance {team1} + {team2}: {e}")
            return {"text": f"Error predicting alliance: {str(e)}", "error": True}
    
    def _generate_team_insights(self, stats: Dict[str, Any], entries: List) -> str:
        """Generate intelligent insights about team performance."""
        insights = []
        
        # Analyze consistency
        if len(entries) >= 3:
            insights.append(f" **Data Quality:** {len(entries)} match entries analyzed")
        
        # Performance level assessment
        total_points = stats.get('total_points', 0) or stats.get('tot', 0)
        if total_points:
            if total_points > 80:
                insights.append("⭐ **Performance Level:** Elite scorer - consistently high output")
            elif total_points > 50:
                insights.append(" **Performance Level:** Strong performer - reliable contributor")
            elif total_points > 30:
                insights.append("→ **Performance Level:** Developing - shows potential")
            else:
                insights.append("→ **Performance Level:** Baseline capabilities")
        
        # Analyze strengths
        strengths = []
        auto = stats.get('auto_points', 0)
        teleop = stats.get('teleop_points', 0)
        endgame = stats.get('endgame_points', 0)
        
        if auto and total_points and auto / max(total_points, 1) > 0.3:
            strengths.append("strong autonomous")
        if teleop and total_points and teleop / max(total_points, 1) > 0.5:
            strengths.append("dominant teleoperated play")
        if endgame and endgame > 15:
            strengths.append("reliable endgame execution")
        
        if strengths:
            insights.append(f" **Key Strengths:** {', '.join(strengths)}")
        
        # Strategic recommendations
        if auto and auto > 20:
            insights.append(" **Alliance Value:** High autonomous scorer - valuable for qualification points")
        elif endgame and endgame > 20:
            insights.append(" **Alliance Value:** Strong endgame specialist - critical for close matches")
        
        return '\n'.join(insights) if insights else "Performance data available - see detailed metrics below."
    
    def get_team_stats(self, team_number: str) -> Dict[str, Any]:
        """Get statistics for a specific team"""
        try:
            team = Team.query.filter_by(team_number=safe_int_team_number(team_number)).first()
            if not team:
                return {"text": f"Team {team_number} not found in the database."}
            # Calculate team statistics from scouting data
            # Exclude alliance-copied data
            from sqlalchemy import or_
            entries = ScoutingData.query.filter_by(team_id=team.id, scouting_team_number=current_user.scouting_team_number).filter(
                or_(
                    ScoutingData.scout_name == None,
                    ~ScoutingData.scout_name.like('[Alliance-%')
                )
            ).all()
            if not entries:
                return {"text": f"No scouting data available for Team {team_number}."}
            analytics_result = calculate_team_metrics(team.id)
            stats = analytics_result.get('metrics', {})
            # Build HTML table of averages with display names
            from flask import current_app
            game_config = get_current_game_config()
            metric_display_names = {}
            if 'data_analysis' in game_config and 'key_metrics' in game_config['data_analysis']:
                for metric in game_config['data_analysis']['key_metrics']:
                    metric_display_names[metric['id']] = metric.get('name', metric['id'])
            table_html = '<table class="table table-sm table-bordered" style="width:auto; margin-top:10px;"><thead><tr><th>Metric</th><th>Average</th></tr></thead><tbody>'
            for k, v in stats.items():
                display_name = metric_display_names.get(k, k.replace("_", " ").title())
                if isinstance(v, (int, float)):
                    table_html += f'<tr><td>{display_name}</td><td>{v:.2f}</td></tr>'
                else:
                    table_html += f'<tr><td>{display_name}</td><td>{v}</td></tr>'
            table_html += '</tbody></table>'
            # Prepare data for Chart.js: total points per match
            match_labels = []
            match_points = []
            total_metric_id = 'tot'
            from flask import current_app
            game_config = get_current_game_config()
            if 'data_analysis' in game_config and 'key_metrics' in game_config['data_analysis']:
                for metric in game_config['data_analysis']['key_metrics']:
                    if 'total' in metric.get('id', '').lower() or 'tot' == metric.get('id', '').lower():
                        total_metric_id = metric.get('id')
                        break
            for entry in entries:
                match_label = f"M{entry.match.match_number}" if entry.match else f"Entry {entry.id}"
                match_labels.append(match_label)
                try:
                    pts = entry.calculate_metric(total_metric_id)
                except Exception:
                    pts = 0
                match_points.append(pts)
            chart_id = f"team-{team.team_number}-graph"
            chartjs_html = f'''
<canvas id="{chart_id}" height="200"></canvas>
<script>
setTimeout(function() {{
  var ctx = document.getElementById('{chart_id}').getContext('2d');
  if (window['{chart_id}_chart']) window['{chart_id}_chart'].destroy();
  window['{chart_id}_chart'] = new Chart(ctx, {{
    type: 'line',
    data: {{
      labels: {match_labels},
      datasets: [{{
        label: 'Total Points',
        data: {match_points},
        borderColor: 'rgba(54, 162, 235, 1)',
        backgroundColor: 'rgba(54, 162, 235, 0.2)',
        fill: true,
        tension: 0.2
      }}]
    }},
    options: {{
      responsive: true,
      plugins: {{ legend: {{ display: false }} }},
      scales: {{
        y: {{ beginAtZero: true }}
      }}
    }}
  }});
}}, 100);
</script>
'''
            # Generate intelligent insights
            insights = self._generate_team_insights(stats, entries)
            
            response_text = f"**Team {team_number} - {team.team_name}**\n\n{insights}\n\n{table_html}{chartjs_html}"
            
            response = {
                "text": response_text,
                "team": {
                    "number": team.team_number,
                    "name": team.team_name,
                    "stats": stats
                },
                "visualization_options": ["team_performance", "ranking_comparison"],
                "insights": insights
            }
            
            # Track in conversation memory
            if team.team_number not in self.conversation_memory['recent_teams']:
                self.conversation_memory['recent_teams'].append(team.team_number)
            
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
        
        # Get top teams for this metric from database
        try:
            from sqlalchemy import desc
            # Query teams with calculated metrics
            all_teams = Team.query.filter_by(scouting_team_number=current_user.scouting_team_number).all()
            team_scores = []
            
            for team in all_teams:
                analytics = calculate_team_metrics(team.id)
                stats = analytics.get('metrics', {})
                score = stats.get(matched_metric, 0)
                if score and score > 0:
                    team_scores.append({
                        'team': team,
                        'score': score,
                        'stats': stats
                    })
            
            # Sort by score
            team_scores.sort(key=lambda x: x['score'], reverse=True)
            top_teams = team_scores[:5]
            
            if not top_teams:
                return {
                    "text": f"No team data available yet for {metric}. Teams need to have completed matches with scouting data.",
                    "suggestion": "Try asking about a specific team, or check back after more matches are scouted."
                }
            
            # Generate intelligent analysis
            analysis = [f"**Top Performers - {metric.replace('_', ' ').title()}**\n"]
            analysis.append("Based on current scouting data, here are the highest-performing teams in this category:\n")
            
            for idx, item in enumerate(top_teams, 1):
                team = item['team']
                score = item['score']
                medal = ['', '', '', '4️⃣', '5️⃣'][idx-1]
                analysis.append(f"{medal} **Team {team.team_number}** ({team.team_name}): {score:.1f} points")
            
            # Add strategic insights
            if top_teams:
                top_score = top_teams[0]['score']
                analysis.append(f"\n**Insights:**")
                analysis.append(f"  • The leading team averages {top_score:.1f} points in {metric.replace('_', ' ')}")
                
                if len(top_teams) >= 2:
                    gap = top_teams[0]['score'] - top_teams[1]['score']
                    if gap < 5:
                        analysis.append(f"  • The top {len(top_teams)} teams are highly competitive (within {gap:.1f} points)")
                    else:
                        analysis.append(f"  • Clear performance leader with {gap:.1f} point advantage")
                
                analysis.append(f"\n*These rankings are based on average performance. Consider consistency and recent trends for alliance selection.*")
            
            response = {
                "text": '\n'.join(analysis),
                "metric": metric,
                "teams": [{'number': item['team'].team_number, 'name': item['team'].team_name, 'score': item['score']} for item in top_teams],
                "visualization_options": ["metric_comparison", "team_ranking"]
            }
            return response
        except Exception as e:
            logger.error(f"Error calculating top teams: {e}")
            return {
                "text": f"I found the top teams for {metric}, but encountered an issue calculating detailed metrics. Try asking about a specific team for detailed analysis.",
                "metric": metric
            }
    
    def _generate_comparison_analysis(self, team1_obj, team1_stats, team2_obj, team2_stats) -> str:
        """Generate intelligent comparative analysis between two teams."""
        analysis = []
        analysis.append(f"**Comparative Analysis: Team {team1_obj.team_number} vs Team {team2_obj.team_number}**\n")
        
        # Overall performance comparison
        t1_total = team1_stats.get('total_points', 0) or team1_stats.get('tot', 0)
        t2_total = team2_stats.get('total_points', 0) or team2_stats.get('tot', 0)
        
        if t1_total and t2_total:
            diff_pct = abs(t1_total - t2_total) / max(t1_total, t2_total) * 100
            if diff_pct < 10:
                analysis.append(" **Overall Assessment:** Very evenly matched - performance within 10%")
            else:
                leader = team1_obj.team_number if t1_total > t2_total else team2_obj.team_number
                analysis.append(f" **Overall Assessment:** Team {leader} has a {diff_pct:.1f}% scoring advantage")
        
        # Detailed metric comparison
        metrics_comparison = []
        
        t1_auto = team1_stats.get('auto_points', 0)
        t2_auto = team2_stats.get('auto_points', 0)
        if t1_auto or t2_auto:
            auto_leader = team1_obj.team_number if t1_auto > t2_auto else team2_obj.team_number
            metrics_comparison.append(f"Autonomous: Team {auto_leader} leads ({max(t1_auto, t2_auto):.1f} pts)")
        
        t1_teleop = team1_stats.get('teleop_points', 0)
        t2_teleop = team2_stats.get('teleop_points', 0)
        if t1_teleop or t2_teleop:
            teleop_leader = team1_obj.team_number if t1_teleop > t2_teleop else team2_obj.team_number
            metrics_comparison.append(f"Teleoperated: Team {teleop_leader} leads ({max(t1_teleop, t2_teleop):.1f} pts)")
        
        t1_endgame = team1_stats.get('endgame_points', 0)
        t2_endgame = team2_stats.get('endgame_points', 0)
        if t1_endgame or t2_endgame:
            endgame_leader = team1_obj.team_number if t1_endgame > t2_endgame else team2_obj.team_number
            metrics_comparison.append(f"Endgame: Team {endgame_leader} leads ({max(t1_endgame, t2_endgame):.1f} pts)")
        
        if metrics_comparison:
            analysis.append("\n**Performance Breakdown:**")
            for comp in metrics_comparison:
                analysis.append(f"  • {comp}")
        
        # Strategic insights
        analysis.append("\n**Strategic Considerations:**")
        
        # Complementary analysis
        if t1_auto > t2_auto and t2_teleop > t1_teleop:
            analysis.append(f"  •  **Complementary strengths** - Team {team1_obj.team_number}'s auto pairs well with Team {team2_obj.team_number}'s teleop")
        elif t1_teleop > t2_teleop and t2_endgame > t1_endgame:
            analysis.append(f"  •  **Complementary strengths** - Team {team1_obj.team_number}'s teleop pairs well with Team {team2_obj.team_number}'s endgame")
        
        # Alliance recommendation
        if t1_total and t2_total and abs(t1_total - t2_total) / max(t1_total, t2_total) < 0.15:
            analysis.append("  • ️ **Alliance potential:** Both teams show similar capabilities - could form a balanced alliance")
        
        analysis.append("\n*This analysis is based on current scouting data. Consider recent trends and match context for alliance decisions.*")
        
        return '\n'.join(analysis)
    
    def compare_teams(self, team1: str, team2: str) -> Dict[str, Any]:
        """Compare statistics between two teams"""
        try:
            team1_obj = Team.query.filter_by(team_number=safe_int_team_number(team1)).first()
            team2_obj = Team.query.filter_by(team_number=safe_int_team_number(team2)).first()
            
            if not team1_obj:
                return {"text": f"Team {team1} not found in the database."}
            if not team2_obj:
                return {"text": f"Team {team2} not found in the database."}
            
            # Calculate stats for both teams
            team1_analytics = calculate_team_metrics(team1_obj.id)
            team1_stats = team1_analytics.get('metrics', {})
            team2_analytics = calculate_team_metrics(team2_obj.id)
            team2_stats = team2_analytics.get('metrics', {})
            
            # Generate intelligent comparison
            comparison_text = self._generate_comparison_analysis(team1_obj, team1_stats, team2_obj, team2_stats)
            
            return {
                "text": comparison_text,
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
                "visualization_options": ["team_comparison", "radar_chart"],
                "comparative_analysis": True
            }
        except Exception as e:
            logger.error(f"Error comparing teams: {e}")
            return {"text": f"Error comparing Teams {team1} and {team2}: {str(e)}", "error": True}
    
    def _handle_upcoming_matches(self, match_type: Optional[str] = None, team_number: Optional[str] = None) -> Dict[str, Any]:
        """Wrapper that reorders arguments from regex (match_type, team_number) to function order."""
        return self.get_upcoming_matches(team_number=team_number, match_type=match_type)
    
    def get_upcoming_matches_team_first(self, team_number: str, match_type: str) -> Dict[str, Any]:
        """Wrapper for team-first queries like 'team 5454 upcoming qualification matches'."""
        return self.get_upcoming_matches(team_number=team_number, match_type=match_type)
    
    def _handle_match_results(self, match_type: Optional[str], match_number: str) -> Dict[str, Any]:
        """Wrapper to handle match results with optional match type from regex."""
        return self.get_match_results(match_number=match_number, match_type=match_type)
    
    def get_upcoming_matches(self, team_number: Optional[str] = None, match_type: Optional[str] = None) -> Dict[str, Any]:
        """Get upcoming match schedule, optionally filtered for a specific team and match type.
        
        Args:
            team_number: Optional team number to filter matches
            match_type: Optional match type ('practice', 'qualification', 'playoff')
        """
        try:
            # Filter for matches that don't have scores (not completed)
            query = Match.query.filter(
                (Match.red_score.is_(None)) | (Match.blue_score.is_(None))
            )
            
            # Filter by match type if specified (case-insensitive)
            if match_type:
                match_type_map = {
                    'practice': 'practice',
                    'qual': 'qualification',
                    'qualification': 'qualification',
                    'playoff': 'playoff',
                    'elim': 'playoff',
                    'elimination': 'playoff',
                    'semifinals': 'semifinals',
                    'semis': 'semifinals',
                    'finals': 'finals'
                }
                normalized_type = match_type_map.get(match_type.lower())
                if normalized_type:
                    # Case-insensitive comparison
                    from sqlalchemy import func
                    query = query.filter(func.lower(Match.match_type) == normalized_type.lower())
            
            query = query.order_by(Match.match_number)
            
            if team_number:
                team = Team.query.filter_by(team_number=safe_int_team_number(team_number)).first()
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
                match_type_str = f" {match_type}" if match_type else ""
                response_text = f"Upcoming{match_type_str} matches for Team {team_number}:"
            else:
                matches = query.limit(5).all()
                if not matches:
                    return {"text": "No upcoming matches found."}
                match_type_str = f" {match_type}" if match_type else ""
                response_text = f"Next 5 upcoming{match_type_str} matches:"
            
            match_list = []
            for match in matches:
                # Format match type for display
                match_type_display = {
                    'practice': ' Practice',
                    'qualification': ' Qualification',
                    'playoff': ' Playoff'
                }.get(match.match_type, match.match_type.title())
                
                match_info = {
                    "number": match.match_number,
                    "type": match.match_type,
                    "type_display": match_type_display,
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
    
    def get_match_results(self, match_number: str, match_type: Optional[str] = None) -> Dict[str, Any]:
        """Get the results for a specific match, optionally filtered by match type.
        
        Args:
            match_number: The match number to retrieve
            match_type: Optional match type ('practice', 'qual', 'qualification', 'playoff', 'elim')
        """
        try:
            # Build query for match number
            query = Match.query.filter_by(match_number=int(match_number))
            
            # Filter by match type if specified (case-insensitive)
            if match_type:
                match_type_map = {
                    'practice': 'practice',
                    'qual': 'qualification',
                    'qualification': 'qualification',
                    'playoff': 'playoff',
                    'elim': 'playoff',
                    'elimination': 'playoff',
                    'semifinals': 'semifinals',
                    'semis': 'semifinals',
                    'finals': 'finals'
                }
                normalized_type = match_type_map.get(match_type.lower())
                if normalized_type:
                    # Case-insensitive comparison using ilike or lower
                    from sqlalchemy import func
                    query = query.filter(func.lower(Match.match_type) == normalized_type.lower())
            
            match = query.first()
            if not match:
                type_str = f" {match_type}" if match_type else ""
                return {"text": f"Match {match_number}{type_str} not found in the database."}
            
            # Check if match is completed based on scores being available
            if match.red_score is None or match.blue_score is None:
                match_type_display = {
                    'practice': ' Practice',
                    'qualification': ' Qualification',
                    'playoff': ' Playoff'
                }.get(match.match_type, match.match_type.title())
                return {"text": f"{match_type_display} Match {match_number} has not been completed yet."}
            
            # Format match type for display
            match_type_display = {
                'practice': ' Practice',
                'qualification': ' Qualification',
                'playoff': ' Playoff'
            }.get(match.match_type, match.match_type.title())
            
            # Construct response with match results
            return {
                "text": f"Results for {match_type_display} Match {match_number}:",
                "match": {
                    "number": match.match_number,
                    "type": match.match_type,
                    "type_display": match_type_display,
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
    
    def get_team_last_match(self, team_number: str) -> Dict[str, Any]:
        """Get the most recent match for a specific team with intelligent analysis."""
        try:
            team = Team.query.filter_by(team_number=safe_int_team_number(team_number)).first()
            if not team:
                return {"text": f"Team {team_number} not found in the database."}
            
            # Find the most recent match for this team
            team_str = str(team.team_number)
            
            # Get all matches where this team participated
            matches = Match.query.filter(
                (Match.red_alliance.like(f'%{team_str}%')) | 
                (Match.blue_alliance.like(f'%{team_str}%'))
            ).order_by(desc(Match.match_number)).all()
            
            if not matches:
                return {"text": f"No matches found for Team {team_number}."}
            
            last_match = matches[0]
            
            # Determine which alliance the team was on
            was_red = team_str in str(last_match.red_alliance)
            alliance_color = "Red" if was_red else "Blue"
            alliance_teams = last_match.red_teams if was_red else last_match.blue_teams
            opponent_teams = last_match.blue_teams if was_red else last_match.red_teams
            
            # Check if match is completed
            if last_match.red_score is None or last_match.blue_score is None:
                return {
                    "text": f"**Team {team_number}'s Most Recent Match**\\n\\nMatch {last_match.match_number} (Upcoming)\\n"
                           f"Team {team_number} will compete on the **{alliance_color} Alliance** with: {', '.join([f'Team {t}' for t in alliance_teams if str(t) != team_str])}\\n"
                           f"Against: {', '.join([f'Team {t}' for t in opponent_teams])}\\n\\n"
                           f"*This match hasn't been played yet. Check back after the match for detailed analysis!*",
                    "match_status": "upcoming"
                }
            
            # Match is completed - provide detailed analysis
            team_score = last_match.red_score if was_red else last_match.blue_score
            opponent_score = last_match.blue_score if was_red else last_match.red_score
            won = team_score > opponent_score
            margin = abs(team_score - opponent_score)
            
            # Get scouting data for this match if available
            scouting_entry = ScoutingData.query.filter_by(
                team_id=team.id,
                match_id=last_match.id
            ).first()
            
            analysis = []
            analysis.append(f"**Team {team_number}'s Most Recent Match**\\n")
            analysis.append(f"**Match {last_match.match_number}** - {alliance_color} Alliance\\n")
            
            # Result with emoji
            result_emoji = "\ud83c\udfc6" if won else "\ud83d\udd35"
            result_text = "Victory" if won else "Loss"
            analysis.append(f"{result_emoji} **{result_text}** - {team_score} to {opponent_score} ({margin} point margin)\\n")
            
            # Alliance composition
            analysis.append(f"**Alliance Partners:** {', '.join([f'Team {t}' for t in alliance_teams if str(t) != team_str])}")
            analysis.append(f"**Opponents:** {', '.join([f'Team {t}' for t in opponent_teams])}\\n")
            
            # Add scouting insights if available
            if scouting_entry:
                try:
                    from flask import current_app
                    game_config = get_current_game_config()
                    
                    # Calculate key metrics
                    auto = scouting_entry.calculate_metric('auto_points')
                    teleop = scouting_entry.calculate_metric('teleop_points')
                    endgame = scouting_entry.calculate_metric('endgame_points')
                    
                    analysis.append("**Performance Breakdown:**")
                    if auto: analysis.append(f"  \u2022 Autonomous: {auto} points")
                    if teleop: analysis.append(f"  \u2022 Teleoperated: {teleop} points")
                    if endgame: analysis.append(f"  \u2022 Endgame: {endgame} points")
                    
                    if scouting_entry.notes:
                        analysis.append(f"\\n**Scout Notes:** {scouting_entry.notes}")
                except Exception as e:
                    logger.error(f"Error calculating match metrics: {e}")
            else:
                analysis.append("*No detailed scouting data available for this match.*")
            
            # Add context and suggestions
            if len(matches) > 1:
                analysis.append(f"\\n\ud83d\udcca Team {team_number} has played {len(matches)} matches total.")
            
            analysis.append("\\n\ud83d\udca1 **Want more insights?**")
            analysis.append(f"  \u2022 Ask 'stats for team {team_number}' for comprehensive performance analysis")
            analysis.append(f"  \u2022 Ask 'compare team {team_number} with [another team]' for head-to-head comparison")
            
            return {
                "text": '\\n'.join(analysis),
                "match": {
                    "number": last_match.match_number,
                    "team_score": team_score,
                    "opponent_score": opponent_score,
                    "won": won,
                    "alliance": alliance_color
                },
                "formatted": True
            }
            
        except Exception as e:
            logger.error(f"Error getting last match for team {team_number}: {e}")
            return {"text": f"Error retrieving last match for Team {team_number}: {str(e)}", "error": True}
    
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
        """Return the assistant's name and introduction when asked"""
        return {
            "text": (
                "I'm your **Intelligent Scouting Assistant**, a sophisticated AI-powered tool designed to help you "
                "analyze FIRST Robotics Competition scouting data with ease.\n\n"
                "**What I Do:**\n"
                "I provide instant access to team statistics, match results, performance analytics, and strategic insights "
                "through natural language queries. I'm trained to understand context, handle casual phrasing, and even work "
                "with misspelled questions - so you can focus on strategy instead of wrestling with complex database queries.\n\n"
                "**Built for Team 5454 and the FRC Community**\n"
                "Whether you're preparing for alliance selection, analyzing opponent strategies, or just exploring the data, "
                "I'm here to help you make informed, data-driven decisions quickly and confidently.\n\n"
                "Ask me anything about teams, matches, scouting strategies, or just say 'help' to see what I can do!"
            ),
            "formatted": True
        }
    
    def get_help_info(self) -> Dict[str, Any]:
        """Provide intelligent, comprehensive help information about assistant capabilities"""
        return {
            "text": (
                "**Welcome to Your Intelligent Scouting Assistant!**\n\n"
                "I'm designed to help you quickly access and analyze scouting data using natural language queries. "
                "I understand context, handle misspellings, and can interpret your questions even if they're phrased casually.\n\n"
                "**My Capabilities:**"
            ),
            "help_topics": [
                {
                    "topic": "Team Performance Analysis",
                    "description": "Get comprehensive statistics, trends, and insights for any team",
                    "examples": ["Stats for team 5454", "How is team 254 doing", "Analyze team 1234 performance"]
                },
                {
                    "topic": "Team Comparisons",
                    "description": "Side-by-side analysis of multiple teams",
                    "examples": ["Compare team 5454 and team 1234", "Team 254 vs team 118", "Difference between team 5454 and 1234"]
                },
                {
                    "topic": "Top Performers & Rankings",
                    "description": "Identify best teams by specific metrics",
                    "examples": ["Best auto scoring teams", "Top teleop performers", "Highest scoring teams"]
                },
                {
                    "topic": "Match Information",
                    "description": "Access match schedules, results, and detailed breakdowns",
                    "examples": ["Match 42 results", "Upcoming matches for team 5454", "Who won match 12"]
                },
                {
                    "topic": "Event Statistics",
                    "description": "Competition-wide analytics and summaries",
                    "examples": ["Event stats", "Event stats for District Championship", "How is the event going"]
                },
                {
                    "topic": "Scouting & Strategy Guidance",
                    "description": "Learn effective scouting techniques and best practices",
                    "examples": ["Explain scouting", "What does a scout do", "Scouting best practices"]
                },
                {
                    "topic": "Documentation & API",
                    "description": "Access technical documentation and integration guides",
                    "examples": ["How does the API work", "Explain user roles", "Summarize help docs"]
                }
            ],
            "features": [
                " Natural language understanding - ask questions however feels natural to you",
                " Spell-tolerant - I can understand questions even with typos",
                " Context-aware - I remember recent questions to better understand follow-ups",
                " Real-time data analysis - All responses use current scouting data",
                " Visual insights - Many queries include interactive charts and graphs",
                " Citation tracking - Documentation responses include source references"
            ],
            "tips": (
                "**Pro Tips:**\n"
                "• Be specific when asking about teams (include team numbers)\n"
                "• Use comparison keywords like 'vs', 'compare', or 'difference' for team comparisons\n"
                "• Ask follow-up questions - I maintain context from previous queries\n"
                "• Don't worry about exact phrasing - I'm trained to understand variations and misspellings"
            ),
            "formatted": True
        }

    def summarize_help_docs(self, topic: Optional[str] = None) -> Dict[str, Any]:
        """Summarize local help/docs files and return a concise summary with citations.

        If topic is provided, attempt to match filenames or headings; otherwise summarize top files.
        """
        try:
            from app.utils.doc_summarizer import summarize_help_folder, summarize_markdown_file
            import os
            # determine help folder relative to app package
            base_dir = os.path.dirname(os.path.dirname(__file__))
            help_folder = os.path.join(base_dir, '..', 'help')
            help_folder = os.path.normpath(help_folder)

            if topic:
                # try to find a file matching the topic
                topic_clean = str(topic).strip().lower()
                candidates = [f for f in os.listdir(help_folder) if f.lower().endswith('.md') and topic_clean in f.lower()]
                if candidates:
                    # summarize first match
                    path = os.path.join(help_folder, candidates[0])
                    summary = summarize_markdown_file(path)
                    return {
                        'text': f"Summary of {summary.get('title')}: {summary.get('summary')}",
                        'citation': summary.get('citation'),
                        'file': summary.get('file')
                    }
                # if no filename match, try summarizing all and match headings
                all_summaries = summarize_help_folder(help_folder, limit=20)
                matching = [s for s in all_summaries if any(topic_clean in (h or '').lower() for h in s.get('headings', []))]
                if matching:
                    s = matching[0]
                    return {
                        'text': f"Summary of {s.get('title')}: {s.get('summary')}",
                        'citation': s.get('citation'),
                        'file': s.get('file')
                    }
                return {'text': f"No help document found for '{topic}'. Try a more general query like 'summarize help'."}
            else:
                # summarize top help files
                summaries = summarize_help_folder(help_folder, limit=6)
                if not summaries:
                    return {'text': 'No help documents available.'}
                # build a short combined summary
                fragments = []
                citations = []
                for s in summaries:
                    fragments.append(f"{s.get('title')}: {s.get('summary')}")
                    citations.append(s.get('citation'))
                combined = ' \n'.join(fragments[:4])
                return {
                    'text': combined,
                    'citations': citations[:4]
                }
        except Exception as e:
            logger.error(f"Error summarizing help docs: {e}")
            return {"text": "Error summarizing help documents."}
    
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
            
            # Track entity mentions for advanced reasoning
            if 'entity' in answer:
                entity_name = answer.get('entity')
                if entity_name not in context.get('entity_mentions', []):
                    context.setdefault('entity_mentions', []).append(entity_name)
            
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
                        analytics_result = calculate_team_metrics(team.id)
                        stats = analytics_result.get('metrics', {})
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
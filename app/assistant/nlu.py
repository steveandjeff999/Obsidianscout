"""Small in-app NLU: intent classification using TF-IDF + LogisticRegression when available.

This is intentionally tiny and trained on a handful of synthetic examples to improve
matching for the most common assistant intents (scout role, api, user roles, summarize, team stats, match results).
If sklearn is not available the module falls back to a rule-based matcher.
"""
from typing import Tuple, Optional
import re
import difflib

# Common misspellings and corrections for FRC/scouting terms
SPELL_CORRECTIONS = {
    'scoutng': 'scouting',
    'scoting': 'scouting',
    'scoutin': 'scouting',
    'explane': 'explain',
    'explian': 'explain',
    'expain': 'explain',
    'summarize': 'summarize',
    'summarise': 'summarize',
    'summerize': 'summarize',
    'sumarize': 'summarize',
    'documention': 'documentation',
    'documentaion': 'documentation',
    'permisions': 'permissions',
    'permissons': 'permissions',
    'statistcs': 'statistics',
    'statisics': 'statistics',
    'perfomance': 'performance',
    'performence': 'performance',
    'analuze': 'analyze',
    'analize': 'analyze',
    'matche': 'match',
    'resulst': 'results',
    'resutls': 'results'
}

def correct_spelling(text: str) -> str:
    """Apply spell corrections to common misspellings."""
    words = text.lower().split()
    corrected = []
    for word in words:
        # Strip punctuation for matching
        clean_word = word.strip('.,!?;:')
        if clean_word in SPELL_CORRECTIONS:
            corrected.append(SPELL_CORRECTIONS[clean_word])
        else:
            # Try fuzzy matching for close misspellings
            matches = difflib.get_close_matches(clean_word, SPELL_CORRECTIONS.keys(), n=1, cutoff=0.85)
            if matches:
                corrected.append(SPELL_CORRECTIONS[matches[0]])
            else:
                corrected.append(word)
    return ' '.join(corrected)

EXAMPLES = [
    # Scout role - various natural phrasings
    ('tell me about the scout role', 'scout_role'),
    ('what is scouting', 'scout_role'),
    ('explain scouting', 'scout_role'),
    ('how do i scout', 'scout_role'),
    ('what does a scout do', 'scout_role'),
    ('scouting responsibilities', 'scout_role'),
    ('what should i know about scouting', 'scout_role'),
    
    # API documentation
    ('explain how the api works', 'api_docs'),
    ('how does the api work', 'api_docs'),
    ('api documentation', 'api_docs'),
    ('tell me about the api', 'api_docs'),
    ('show me api endpoints', 'api_docs'),
    ('how to use the api', 'api_docs'),
    ('api reference', 'api_docs'),
    
    # User roles and permissions
    ('explain user roles', 'user_roles'),
    ('what are the roles', 'user_roles'),
    ('user permissions', 'user_roles'),
    ('what can different users do', 'user_roles'),
    ('role permissions', 'user_roles'),
    ('access levels', 'user_roles'),
    
    # Help and documentation
    ('summarize help', 'summarize_help'),
    ('summarize api docs', 'summarize_help'),
    ('show me the documentation', 'summarize_help'),
    ('what documentation is available', 'summarize_help'),
    ('help docs', 'summarize_help'),
    ('give me an overview', 'summarize_help'),
    
    # Team statistics - natural variations
    ('stats for team 5454', 'team_stats'),
    ('team 5454 stats', 'team_stats'),
    ('show me team 5454', 'team_stats'),
    ('how is team 5454 doing', 'team_stats'),
    ('tell me about team 5454', 'team_stats'),
    ('team 5454 performance', 'team_stats'),
    ('what are the stats for team 5454', 'team_stats'),
    ('analyze team 5454', 'team_stats'),
    ('data on team 5454', 'team_stats'),
    
    # Match results
    ('match 42 results', 'match_results'),
    ('who won match 42', 'match_results'),
    ('match 42 score', 'match_results'),
    ('what happened in match 42', 'match_results'),
    ('show me match 42', 'match_results'),
    ('match 42 outcome', 'match_results'),
    # Short-hand match queries
    ('qual 42', 'match_results'),
    ('playoff 5', 'match_results'),
    ('practice 2', 'match_results'),
    
    # Trend analysis
    ('trends for team 5454', 'team_trends'),
    ('is team 254 improving', 'team_trends'),
    ('team 1234 performance over time', 'team_trends'),
    ('trajectory of team 118', 'team_trends'),
    
    # Predictions
    ('predict team 5454 performance', 'team_prediction'),
    ('will team 254 win', 'match_prediction'),
    ('who will win match 5', 'match_prediction'),
    ('forecast for team 118', 'team_prediction'),
    
    # Advanced analytics
    ('consistency of team 5454', 'consistency_analysis'),
    ('peak performance for team 254', 'peak_analysis'),
    ('weaknesses of team 1234', 'weakness_analysis'),
    ('strengths of team 118', 'strength_analysis'),
    ('qualification match 42', 'match_results'),
    ('playoff match 5', 'match_results'),
    ('practice match 1', 'match_results'),
    
    # Last/recent match for teams
    ('5454s last match', 'team_last_match'),
    ('team 5454 last match', 'team_last_match'),
    ('most recent match for team 5454', 'team_last_match'),
    ('team 5454 latest match', 'team_last_match'),
    ('5454 most recent match', 'team_last_match'),
    ('what was team 5454s last match', 'team_last_match'),
    
    # Team comparison (including short formats)
    ('compare team 5454 and team 1234', 'team_comparison'),
    ('team 5454 vs team 1234', 'team_comparison'),
    ('5454 vs 1234', 'team_comparison'),
    ('5454 and 1234', 'team_comparison'),
    ('5454 v 1234', 'team_comparison'),
    ('how does team 5454 compare to team 1234', 'team_comparison'),
    ('difference between team 5454 and team 1234', 'team_comparison'),
    
    # Best teams queries
    ('best teams', 'best_teams'),
    ('top teams', 'best_teams'),
    ('highest scoring teams', 'best_teams'),
    ('who are the best teams', 'best_teams'),
    ('show me the top performers', 'best_teams')
]


def _rule_based_intent(text: str) -> Tuple[Optional[str], float]:
    """Enhanced rule-based intent detection with comprehensive pattern matching."""
    t = text.lower()
    
    # Scout role patterns (high priority for scouting-specific terms)
    if re.search(r'\b(scout|scouting|scout role|scouter)\b', t) and not re.search(r'\bteam\s+\d', t):
        return 'scout_role', 0.85
    
    # API documentation patterns
    if re.search(r'\b(api|endpoints?|rest|documentation)\b', t):
        if re.search(r'\b(how|work|use|explain|docs?)\b', t):
            return 'api_docs', 0.85
    
    # User roles and permissions
    if re.search(r'\b(role|roles|permission|permissions|access|user role)\b', t):
        if not re.search(r'\bscout role\b', t):  # Avoid confusion with scout role
            return 'user_roles', 0.85
    
    # Help/documentation summarization
    if re.search(r'\b(summariz|summarise|summary|brief|overview|help docs?)\b', t):
        return 'summarize_help', 0.8
    
    # Team comparison (two team numbers)
    team_nums = re.findall(r'\bteam\s+(\d{1,4})\b|\b(\d{1,4})\b', t)
    if len(team_nums) >= 2:
        # Simple format: "5454 and 16" or "254 vs 118"
        if re.search(r'\b(and|vs|versus|v|against|compar|difference)\b', t):
            return 'team_comparison', 0.95
        # If just two numbers mentioned, likely a comparison
        if len(t.split()) <= 6:  # Short query with 2 numbers
            return 'team_comparison', 0.85
    
    # Team statistics (single team)
    if re.search(r'\bteam\s+\d{1,4}\b', t):
        if re.search(r'\b(stat|stats|statistics|performance|data|info|about|analyz)\b', t):
            return 'team_stats', 0.9
            # Just "team 5454" without other context
        return 'team_stats', 0.85
    
    # Special case: "last match" or "most recent match" for a team
    if re.search(r'\b(last|latest|most recent|final)\s+match\b', t):
        if re.search(r'\bteam\s+\d{1,4}\b', t) or re.search(r'^\d{1,4}', t):
            return 'team_last_match', 0.9
    
    # Match results
    if re.search(r'\bmatch\s+\d{1,4}\b', t):
        return 'match_results', 0.9    # Best teams queries
    if re.search(r'\b(best|top|highest|strongest|leading|greatest)\b', t):
        if re.search(r'\b(team|teams|robot|robots|performer)\b', t):
            return 'best_teams', 0.8
    
    return None, 0.0


def predict_intent(text: str) -> Tuple[Optional[str], float]:
    """Predict intent and return (intent_name, confidence).

    Uses a tiny TF-IDF+LogReg model if sklearn is available, otherwise rule-based.
    Applies spell correction before prediction.
    """
    # Apply spell correction first
    corrected_text = correct_spelling(text)
    
    try:
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.linear_model import LogisticRegression
        # train on the small synthetic dataset
        X = [ex[0] for ex in EXAMPLES]
        y = [ex[1] for ex in EXAMPLES]
        vect = TfidfVectorizer(ngram_range=(1,2), stop_words='english', max_features=100).fit(X + [corrected_text])
        Xv = vect.transform(X)
        tv = vect.transform([corrected_text])
        clf = LogisticRegression(max_iter=300, C=1.0).fit(Xv, y)
        probs = clf.predict_proba(tv)[0]
        labels = clf.classes_
        best_idx = int(probs.argmax())
        # Boost confidence if multiple high probabilities suggest same intent
        return labels[best_idx], float(probs[best_idx])
    except Exception:
        return _rule_based_intent(corrected_text)

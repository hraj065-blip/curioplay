import secrets
import string
import time
import random
import re
import os
import requests  # REQUIRED for Grammar API
from flask import (
    Flask, render_template, request, redirect,
    url_for, session, jsonify, abort
)

app = Flask(__name__)

# --- CONFIG: STATIC SECRET KEY ---
app.secret_key = os.environ.get("SECRET_KEY", "Keep_This_Static_Key_Safe_For_Event_2026")

# ===============================
# CONFIGURATION
# ===============================
WORD_BANK = [
    "Apple", "Bread", "Candy", "Dream", "Eagle", "Flame", "Grape", "Heart", 
    "Island", "Juice", "Knife", "Lemon", "Music", "Night", "Ocean", "Paper", 
    "Queen", "River", "Stone", "Table", "Uncle", "Voice", "Water", "Young", 
    "Zebra", "Beach", "Cloud", "Dance", "Earth", "Fruit", "Green", "House", 
    "Light", "Money", "Onion", "Piano", "Radio", "Shirt", "Tiger", "Train", 
    "Watch", "World", "Chair", "Dress", "Glass", "Mouse", "Phone", "Spoon", 
    "Truck", "Plant","tree", "moon", "star", "book", "lake", "wind", "sand", "rock", "road", "snow",
    "apple", "river", "table", "cloud", "stone", "light", "bread", "green", "smile", "grass",
    "desert", "forest", "summer", "winter", "spring", "travel", "silver", "sunset", "bright", "gentle",
    "morning", "evening", "harmony", "freedom", "balance", "picture", "lantern", "journey", "crystal", "meadow",
    "melody", "ocean", "horizon", "captain", "village", "canyon", "planet", "harbor", "beacon", "memory"
]

GAMES = {}

# ===============================
# HELPERS
# ===============================
def make_id(n=6):
    return "".join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(n))

def scramble(word):
    word = word.lower()
    if len(word) <= 3: return word
    arr = list(word)
    while True:
        random.shuffle(arr)
        if "".join(arr) != word:
            return "".join(arr)

def cleanup_old_games():
    """Removes games older than 4 hours to save memory."""
    current_time = time.time()
    expired = []
    for gid, game in GAMES.items():
        if game.get("start_time") and (current_time - game["start_time"] > 14400):
            expired.append(gid)
    for gid in expired:
        del GAMES[gid]

# ===============================
# PAGE ROUTES
# ===============================
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/create_game", methods=["POST"])
def create_game():
    cleanup_old_games() 
    data = request.json or {}
    duration = int(data.get("duration", 10))
    game_id = make_id(5)
    
    GAMES[game_id] = {
        "id": game_id,
        "state": "lobby",
        "start_time": None,
        "end_time": None,
        "duration_sec": duration * 60,
        "words": random.sample(WORD_BANK * 5, 100),
        "teams": {}
    }
    session["game_id"] = game_id
    return jsonify({"game_id": game_id, "admin_url": url_for('admin_page', game_id=game_id)})

@app.route("/admin/<game_id>")
def admin_page(game_id):
    game = GAMES.get(game_id)
    if not game: abort(404)
    return render_template("admin.html", game=game)

@app.route("/join/<game_id>", methods=["GET", "POST"])
def join_page(game_id):
    game = GAMES.get(game_id)
    if not game: abort(404)

    if request.method == "POST":
        team_name = request.form.get("team_name", "").strip().upper()
        player_name = request.form.get("player_name", "").strip()
        role = request.form.get("role", "p1").lower() 

        if team_name not in game["teams"]:
            game["teams"][team_name] = {
                "name": team_name, 
                "score": 0, 
                "p1_idx": 0, 
                "p1_solved_history": [], 
                "p1_attempts": 5, 
                "p2_dice_sum": None, 
                "used_sentences": [], 
                "current_scramble": None, 
                "current_scramble_idx": -1, 
                "players": {}
            }
        
        token = make_id(8)
        game["teams"][team_name]["players"][token] = {"name": player_name, "role": role}
        session["game_id"] = game_id
        session["team_name"] = team_name
        session["token"] = token
        return redirect(url_for("player_page"))

    return render_template("join.html", game=game)

@app.route("/play")
def player_page():
    game_id = session.get("game_id")
    team_name = session.get("team_name")
    token = session.get("token")
    
    if not game_id or not team_name or not token:
        return redirect(url_for("index"))
    
    game = GAMES.get(game_id)
    if not game:
        session.clear() 
        return redirect(url_for("index"))
    
    team = game["teams"].get(team_name)
    if not team:
        return redirect(url_for("index"))
        
    player = team["players"].get(token)
    if not player:
        session.clear()
        return redirect(url_for("index"))

    return render_template("player.html", game=game, team=team, player=player, token=token)

# ===============================
# API LOGIC
# ===============================
@app.route("/api/start", methods=["POST"])
def api_start():
    data = request.json or {}
    game_id = data.get("game_id") or session.get("game_id")
    if not game_id and GAMES: game_id = list(GAMES.keys())[-1]
    game = GAMES.get(game_id)
    if game:
        game["state"] = "running"
        game["start_time"] = time.time()
        game["end_time"] = time.time() + game["duration_sec"]
        return jsonify({"status": "started"})
    return jsonify({"error": "No game found"}), 404

@app.route("/api/sync", methods=["POST"])
def api_sync():
    game_id = session.get("game_id")
    team_name = session.get("team_name")
    token = session.get("token")
    
    if not game_id or not team_name:
        return jsonify({"state": "lobby", "time_left": 0, "team_score": 0}), 200

    game = GAMES.get(game_id)
    team = game["teams"].get(team_name) if game else None
    
    if not game or not team:
        return jsonify({"state": "lobby"}), 200

    time_left = max(0, int(game["end_time"] - time.time())) if game["state"] == "running" else 0
    
    if game["state"] == "running" and time_left <= 0:
        game["state"] = "finished"

    response = {
        "state": game["state"],
        "time_left": time_left,
        "team_score": team["score"]
    }

    if token in team["players"]:
        role = team["players"][token]["role"].lower()
        if role == "p1":
            current_idx = team["p1_idx"]
            if "current_scramble_idx" not in team:
                team["current_scramble_idx"] = -1
                team["current_scramble"] = None
            if team["current_scramble_idx"] != current_idx and current_idx < len(game["words"]):
                raw_word = game["words"][current_idx]
                team["current_scramble"] = scramble(raw_word)
                team["current_scramble_idx"] = current_idx
            response["p1_data"] = {"scrambled": team["current_scramble"], "attempts": team["p1_attempts"]}
        else:
            active = len(team["p1_solved_history"]) > 0
            if "p2_dice_sum" not in team: team["p2_dice_sum"] = None
            if active and team["p2_dice_sum"] is None:
                team["p2_dice_sum"] = random.randint(4, 10)
            target = team["p1_solved_history"][-1] if active else ""
            response["p2_data"] = {"active": active, "target_word": target, "dice_sum": team["p2_dice_sum"]}

    return jsonify(response)

@app.route("/api/action", methods=["POST"])
def api_action():
    data = request.json
    game = GAMES.get(session.get("game_id"))
    team = game["teams"].get(session.get("team_name"))
    if not game or not team: return jsonify({"status":"error"})
    action = data.get("action")

    # --- PENALTY LOGIC ---
    if action == "cheat_tab_switch":
        team["score"] = max(0, team["score"] - 100)
        return jsonify({"status": "penalty"})

    # --- PLAYER 1 GUESS ---
    if action == "guess" and game["state"] == "running":
        guess = data.get("value", "").lower().strip()
        
        # Check boundaries
        if team["p1_idx"] >= len(game["words"]):
             return jsonify({"status": "finished"})

        actual = game["words"][team["p1_idx"]].lower() 
        
        if guess == actual:
            team["p1_solved_history"].append(game["words"][team["p1_idx"]])
            team["score"] += 50 + (team["p1_attempts"] * 10)
            team["p1_idx"] += 1
            team["p1_attempts"] = 5
            return jsonify({"status": "correct"})
        
        # Wrong guess
        team["p1_attempts"] -= 1
        
        # --- SKIP LOGIC (-20 Penalty) ---
        if team["p1_attempts"] <= 0:
            team["p1_idx"] += 1      # Skip current word
            team["p1_attempts"] = 5  # Reset attempts
            team["score"] -= 20      # <--- DEDUCT 20 POINTS
            return jsonify({"status": "skip", "msg": "Out of attempts! -20 Points."})

        return jsonify({"status": "wrong"})

    # --- PLAYER 2 SUBMIT ---
    if action == "submit_sentence" and game["state"] == "running":
        val = data.get("value", "").strip()
        required = team["p2_dice_sum"]
        
        if not team["p1_solved_history"]:
             return jsonify({"status": "error", "msg": "Wait for Player 1!"})

        target = team["p1_solved_history"][-1].lower()
        
        if not val:
            return jsonify({"status": "error", "msg": "Type a sentence first!"})
            
        words = re.findall(r'\b\w+\b', val)
        if len(words) != required:
            return jsonify({"status": "error", "msg": f"Need exactly {required} words"})
            
        if target not in [w.lower() for w in words]:
             return jsonify({"status": "error", "msg": f"Must include '{target}'"})

        used = [s.lower() for s in team.get("used_sentences", [])]
        if val.lower() in used:
             return jsonify({"status": "error", "msg": "You already used that sentence!"})

        try:
            resp = requests.post(
                "https://api.languagetool.org/v2/check",
                data={'text': val, 'language': 'en-US'},
                timeout=2
            )
            if resp.status_code == 200:
                matches = resp.json().get('matches', [])
                for m in matches:
                    if m['rule']['issueType'] in ['grammar', 'misspelling']:
                        return jsonify({"status": "error", "msg": f"Grammar: {m['message']}"})
        except Exception:
            if not val[0].isupper():
                return jsonify({"status": "error", "msg": "Start with a Capital letter!"})
            if val[-1] not in ['.', '!', '?']:
                return jsonify({"status": "error", "msg": "End with punctuation (. ! ?)"})

        team["score"] += required * 5
        
        if "used_sentences" not in team: team["used_sentences"] = []
        team["used_sentences"].append(val)
        
        team["p2_dice_sum"] = None 

        return jsonify({"status": "correct"})

    return jsonify({"status": "error"})

@app.route("/api/leaderboard/<game_id>")
def api_leaderboard(game_id):
    game = GAMES.get(game_id)
    if not game: return jsonify([])
    lb = [{"name": t["name"], "score": t["score"]} for t in game["teams"].values()]
    return jsonify(sorted(lb, key=lambda x: x["score"], reverse=True)[:8])

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5005, debug=True, threaded=True)

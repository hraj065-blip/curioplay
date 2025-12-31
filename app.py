import secrets
import string
import time
import random
import re
from flask import (
    Flask, render_template, request, redirect,
    url_for, session, jsonify, abort
)

app = Flask(__name__)
app.secret_key = secrets.token_hex(16)

# ... (Configuration & Helpers same as before) ...
WORD_BANK = ["algorithm", "bandwidth", "cipher", "database", "python", "flask", "docker", "cloud", "binary", "cache"] * 10
GAMES = {}

def make_id(n=6):
    return "".join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(n))

def scramble(word):
    if len(word) <= 3: return word
    arr = list(word)
    while True:
        random.shuffle(arr)
        if "".join(arr) != word: return "".join(arr)

@app.route("/")
def index(): return render_template("index.html")

@app.route("/create_game", methods=["POST"])
def create_game():
    data = request.json or {}
    duration = int(data.get("duration", 10))
    game_id = make_id(5)
    GAMES[game_id] = {
        "id": game_id, "state": "lobby", "start_time": None, "end_time": None,
        "duration_sec": duration * 60, "words": random.sample(WORD_BANK, len(WORD_BANK)), "teams": {}
    }
    session["game_id"] = game_id
    return jsonify({"game_id": game_id, "admin_url": url_for('admin_page', game_id=game_id)})

@app.route("/admin/<game_id>")
def admin_page(game_id):
    return render_template("admin.html", game=GAMES.get(game_id) or abort(404))

@app.route("/join/<game_id>", methods=["GET", "POST"])
def join_page(game_id):
    game = GAMES.get(game_id)
    if not game: abort(404)
    if request.method == "POST":
        team_name = request.form.get("team_name", "").strip().upper()
        player_name = request.form.get("player_name", "").strip()
        role = request.form.get("role", "p1").lower() # Force lowercase

        if team_name not in game["teams"]:
            game["teams"][team_name] = {
                "name": team_name, "score": 0, "p1_idx": 0, "p2_idx": 0,
                "p1_solved_history": [], "p1_attempts": 5, "p2_dice_sum": None,
                "current_scramble": None, "current_scramble_idx": -1, "players": {}
            }
        token = make_id(8)
        game["teams"][team_name]["players"][token] = {"name": player_name, "role": role}
        session.update({"game_id": game_id, "team_name": team_name, "token": token})
        return redirect(url_for("player_page"))
    return render_template("join.html", game=game)

@app.route("/play")
def player_page():
    game = GAMES.get(session.get("game_id"))
    team = game["teams"].get(session.get("team_name")) if game else None
    if not team: return redirect(url_for("index"))
    return render_template("player.html", game=game, team=team, player=team["players"].get(session.get("token")), token=session.get("token"))

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
    return jsonify({"error": "No game"}), 404

@app.route("/api/sync", methods=["POST"])
def api_sync():
    game = GAMES.get(session.get("game_id"))
    team = game["teams"].get(session.get("team_name")) if game else None
    token = session.get("token")

    if not game or not team: return jsonify({"state": "lobby"}), 200

    time_left = max(0, int(game["end_time"] - time.time())) if game["state"] == "running" else 0
    resp = {"state": game["state"], "time_left": time_left, "team_score": team["score"]}

    if token in team["players"]:
        role = team["players"][token]["role"].lower()
        
        if role == "p1":
            # SCRAMBLE LOCK LOGIC
            idx = team["p1_idx"]
            if team.get("current_scramble_idx") != idx:
                team["current_scramble"] = scramble(game["words"][idx])
                team["current_scramble_idx"] = idx
            resp["p1_data"] = {"scrambled": team["current_scramble"], "attempts": team["p1_attempts"]}
        
        else: # P2
            active = team["p1_idx"] > team["p2_idx"]
            if active and team["p2_dice_sum"] is None: team["p2_dice_sum"] = random.randint(3, 10)
            target = team["p1_solved_history"][team["p2_idx"]] if active else ""
            resp["p2_data"] = {"active": active, "target_word": target, "dice_sum": team["p2_dice_sum"]}

    return jsonify(resp)

@app.route("/api/action", methods=["POST"])
def api_action():
    data = request.json
    game = GAMES.get(session.get("game_id"))
    team = game["teams"].get(session.get("team_name")) if game else None
    if not team: return jsonify({"status":"error"})
    
    action = data.get("action")
    if action == "cheat_tab_switch":
        team["score"] = max(0, team["score"] - 5)
        return jsonify({"status": "penalty"})

    if action == "guess":
        guess = data.get("value", "").lower().strip()
        actual = game["words"][team["p1_idx"]]
        if guess == actual:
            team["p1_solved_history"].append(actual)
            team["score"] += 50 + (team["p1_attempts"] * 10)
            team["p1_idx"] += 1
            team["p1_attempts"] = 5
            team["p2_idx"] = team["p1_idx"] - 1 # P2 follows P1
            team["p2_dice_sum"] = None
            return jsonify({"status": "correct"})
        else:
            team["p1_attempts"] -= 1
            return jsonify({"status": "wrong"})

    if action == "submit_sentence":
        words = re.findall(r'\b\w+\b', data.get("value", ""))
        required = team["p2_dice_sum"]
        target = team["p1_solved_history"][team["p2_idx"]]
        if len(words) != required: return jsonify({"status": "error", "msg": f"Need {required} words"})
        if target.lower() not in [w.lower() for w in words]: return jsonify({"status": "error", "msg": f"Include '{target}'"})
        team["score"] += required * 5
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
from __future__ import annotations
import logging, flask
from core.controller import media_player

log = logging.getLogger(__name__)

bp = flask.Blueprint('media', __name__, url_prefix='/media')

def configure(a: flask.Flask):
    a.register_blueprint(bp)

@bp.route("/state", methods=["GET"])
def api_state():
    if not media_player:
        return flask.jsonify({"error": "No media player initialized"}), 400
    return flask.jsonify(media_player.to_json())

@bp.route("/select/<name>", methods=["POST"])
def api_select(name):
    if not media_player:
        return flask.jsonify({"error": "No media player initialized"}), 400
    if media_player.select_track(name):
        return flask.jsonify({"ok": True})
    return flask.jsonify({"error": "Track not found"}), 404

@bp.route("/play", methods=["POST"])
def api_play():
    if not media_player:
        return flask.jsonify({"error": "No song loaded"}), 400
    if media_player.play():
        return flask.jsonify({"ok": True})
    return flask.jsonify({"error": "Failed to play"}), 500

@bp.route("/pause", methods=["POST"])
def api_pause():
    if not media_player:
        return flask.jsonify({"error": "No song loaded"}), 400
    if media_player.pause():
        return flask.jsonify({"ok": True})
    return flask.jsonify({"error": "Failed to pause"}), 500

@bp.route("/restart", methods=["POST"])
def api_restart():
    if not media_player:
        return flask.jsonify({"error": "No song loaded"}), 400
    if media_player.restart():
        return flask.jsonify({"ok": True})
    return flask.jsonify({"error": "Failed to restart"}), 500

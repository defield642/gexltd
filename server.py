from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from threading import Lock

from flask import Flask, abort, jsonify, request, send_from_directory

BASE_DIR = Path(__file__).resolve().parent
STATE_FILE = Path(os.environ.get('GEX_STATE_FILE', str(BASE_DIR / 'data.json'))).expanduser()
STATE_LOCK = Lock()
DEFAULT_STATE = {'investors': []}

app = Flask(__name__, static_folder=None)


def normalize_investor(inv: dict) -> dict:
    today = __import__('datetime').datetime.utcnow().date().isoformat()
    transactions = inv.get('transactions') if isinstance(inv.get('transactions'), list) else []
    normalized_transactions = []
    for tx in transactions:
        if not isinstance(tx, dict):
            continue
        normalized_transactions.append({
            'amount': float(tx.get('amount') or 0),
            'date': tx.get('date') or today,
            'type': tx.get('type') or 'initial',
        })

    computed_total = sum(tx['amount'] for tx in normalized_transactions)
    total_investment = inv.get('totalInvestment')
    try:
        total_investment = float(total_investment)
    except (TypeError, ValueError):
        total_investment = computed_total

    latest_deposit = inv.get('latestDeposit')
    try:
        latest_deposit = float(latest_deposit)
    except (TypeError, ValueError):
        latest_deposit = normalized_transactions[-1]['amount'] if normalized_transactions else total_investment

    if not normalized_transactions:
        normalized_transactions = [{
            'amount': total_investment,
            'date': today,
            'type': 'initial',
        }]

    return {
        **inv,
        'id': int(inv.get('id') or 0),
        'name': str(inv.get('name') or '').strip(),
        'latestDeposit': latest_deposit,
        'totalInvestment': total_investment,
        'transactions': normalized_transactions,
    }


def normalize_state(raw_state: dict | None) -> dict:
    if not isinstance(raw_state, dict):
        raw_state = {}
    investors = raw_state.get('investors')
    if not isinstance(investors, list):
        investors = []
    return {'investors': [normalize_investor(inv) for inv in investors if isinstance(inv, dict)]}


def load_state() -> dict:
    if not STATE_FILE.exists():
        return normalize_state(DEFAULT_STATE)
    try:
        with STATE_FILE.open('r', encoding='utf-8') as handle:
            return normalize_state(json.load(handle))
    except (OSError, json.JSONDecodeError):
        return normalize_state(DEFAULT_STATE)


def save_state(state: dict) -> dict:
    normalized = normalize_state(state)
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp_fd, tmp_path = tempfile.mkstemp(prefix='data.', suffix='.json', dir=str(STATE_FILE.parent))
    try:
        with os.fdopen(tmp_fd, 'w', encoding='utf-8') as handle:
            json.dump(normalized, handle, indent=2, ensure_ascii=False)
            handle.write('\n')
        os.replace(tmp_path, STATE_FILE)
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
    return normalized



@app.get('/api/health')
def health():
    return jsonify({'ok': True})


@app.get('/api/state')
def api_get_state():
    with STATE_LOCK:
        return jsonify(load_state())


@app.post('/api/state')
def api_set_state():
    payload = request.get_json(silent=True) or {}
    state = payload.get('state', payload)
    if not isinstance(state, dict):
        return jsonify({'error': 'Invalid state payload'}), 400
    with STATE_LOCK:
        return jsonify(save_state(state))


@app.route('/', defaults={'path': ''})
@app.route('/<path:path>')
def serve(path: str):
    if path.startswith('api/'):
        abort(404)
    requested = BASE_DIR / path if path else BASE_DIR / 'index.html'
    if path and requested.is_file():
        return send_from_directory(BASE_DIR, path)
    return send_from_directory(BASE_DIR, 'index.html')


if __name__ == '__main__':
    port = int(os.environ.get('PORT', '10000'))
    app.run(host='0.0.0.0', port=port)

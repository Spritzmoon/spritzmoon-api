#!/usr/bin/env python3
"""
SpritzMoon Global Blockchain Backend
Real-time multi-device synchronization with persistent blockchain
"""

from flask import Flask, request, jsonify, render_template_string
from flask_cors import CORS
import sqlite3
import json
import time
import hashlib
import random
import string
from datetime import datetime, timedelta
import threading
import os

app = Flask(__name__)
CORS(app)

# Database configuration
DB_PATH = '/tmp/spritzmoon_global.db'

def init_database():
    """Initialize the global blockchain database"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Create tables
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS devices (
            id TEXT PRIMARY KEY,
            balance REAL DEFAULT 0,
            mining_rate REAL DEFAULT 1.5,
            last_seen INTEGER,
            faucet_last_claim INTEGER DEFAULT 0,
            created_at INTEGER
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS global_blockchain (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tx_id TEXT UNIQUE,
            type TEXT,
            from_device TEXT,
            to_device TEXT,
            amount REAL,
            timestamp INTEGER,
            block_hash TEXT,
            created_at INTEGER
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS mining_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            device_id TEXT,
            start_time INTEGER,
            end_time INTEGER,
            duration REAL,
            earned REAL,
            tx_id TEXT,
            created_at INTEGER
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS global_stats (
            key TEXT PRIMARY KEY,
            value TEXT,
            updated_at INTEGER
        )
    ''')
    
    # Initialize genesis block if not exists
    cursor.execute('SELECT COUNT(*) FROM global_blockchain')
    if cursor.fetchone()[0] == 0:
        genesis_tx = generate_tx_id()
        cursor.execute('''
            INSERT INTO global_blockchain 
            (tx_id, type, from_device, to_device, amount, timestamp, block_hash, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (genesis_tx, 'genesis', 'Genesis Block', 'Global Network', 0, 
              int(time.time() * 1000), 'genesis_hash', int(time.time())))
    
    # Initialize global stats
    stats = {
        'total_blocks': 1,
        'total_users': 0,
        'active_users': 0,
        'total_transactions': 1,
        'total_hash_rate': 0,
        'founder_percentage': 5.71
    }
    
    for key, value in stats.items():
        cursor.execute('''
            INSERT OR REPLACE INTO global_stats (key, value, updated_at)
            VALUES (?, ?, ?)
        ''', (key, str(value), int(time.time())))
    
    conn.commit()
    conn.close()

def generate_tx_id():
    """Generate unique transaction ID"""
    chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789'
    return 'TX_' + ''.join(random.choice(chars) for _ in range(8))

def generate_device_id():
    """Generate unique device ID based on request fingerprint"""
    # Use IP, User-Agent, and timestamp for uniqueness
    fingerprint = f"{request.remote_addr}_{request.headers.get('User-Agent', '')}_{int(time.time())}"
    hash_obj = hashlib.md5(fingerprint.encode())
    hash_hex = hash_obj.hexdigest()
    
    part1 = hash_hex[:8].upper()
    part2 = hash_hex[8:14].upper()
    part3 = str(random.randint(10, 99))
    
    return f"SPM_{part1}_{part2}_{part3}"

def calculate_mining_rate(device_id):
    """Calculate mining rate based on device ID"""
    hash_str = device_id.replace('SPM_', '').replace('_', '')
    hash_sum = sum(ord(c) for c in hash_str)
    return 1.0 + (hash_sum % 100) / 100  # Rate between 1.00 and 1.99

def get_db_connection():
    """Get database connection"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def update_global_stats():
    """Update global statistics"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Count total users
    cursor.execute('SELECT COUNT(*) FROM devices')
    total_users = cursor.fetchone()[0]
    
    # Count active users (last seen within 1 hour)
    one_hour_ago = int(time.time() * 1000) - (60 * 60 * 1000)
    cursor.execute('SELECT COUNT(*) FROM devices WHERE last_seen > ?', (one_hour_ago,))
    active_users = cursor.fetchone()[0]
    
    # Count total transactions
    cursor.execute('SELECT COUNT(*) FROM global_blockchain')
    total_transactions = cursor.fetchone()[0]
    
    # Calculate total hash rate
    cursor.execute('SELECT SUM(mining_rate) FROM devices WHERE last_seen > ?', (one_hour_ago,))
    result = cursor.fetchone()[0]
    total_hash_rate = result if result else 0
    
    # Update stats
    stats = {
        'total_users': total_users,
        'active_users': active_users,
        'total_transactions': total_transactions,
        'total_hash_rate': total_hash_rate
    }
    
    for key, value in stats.items():
        cursor.execute('''
            UPDATE global_stats SET value = ?, updated_at = ?
            WHERE key = ?
        ''', (str(value), int(time.time()), key))
    
    conn.commit()
    conn.close()
    return stats

@app.route('/')
def index():
    """Serve the main application"""
    return render_template_string(open('/home/ubuntu/spritzmoon-real-global/index.html').read())

@app.route('/api/device/register', methods=['POST'])
def register_device():
    """Register a new device or get existing device info"""
    try:
        data = request.get_json() or {}
        device_id = data.get('device_id')
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        if device_id:
            # Check if device exists
            cursor.execute('SELECT * FROM devices WHERE id = ?', (device_id,))
            device = cursor.fetchone()
            
            if device:
                # Update last seen
                cursor.execute('''
                    UPDATE devices SET last_seen = ? WHERE id = ?
                ''', (int(time.time() * 1000), device_id))
                conn.commit()
                
                return jsonify({
                    'success': True,
                    'device_id': device_id,
                    'balance': device['balance'],
                    'mining_rate': device['mining_rate'],
                    'faucet_last_claim': device['faucet_last_claim']
                })
        
        # Generate new device ID
        new_device_id = generate_device_id()
        mining_rate = calculate_mining_rate(new_device_id)
        current_time = int(time.time() * 1000)
        
        # Insert new device
        cursor.execute('''
            INSERT INTO devices (id, balance, mining_rate, last_seen, created_at)
            VALUES (?, ?, ?, ?, ?)
        ''', (new_device_id, 0, mining_rate, current_time, int(time.time())))
        
        # Add registration transaction to global blockchain
        tx_id = generate_tx_id()
        cursor.execute('''
            INSERT INTO global_blockchain 
            (tx_id, type, from_device, to_device, amount, timestamp, block_hash, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (tx_id, 'registration', 'Global Network', new_device_id, 0, 
              current_time, f'block_{tx_id}', int(time.time())))
        
        conn.commit()
        conn.close()
        
        update_global_stats()
        
        return jsonify({
            'success': True,
            'device_id': new_device_id,
            'balance': 0,
            'mining_rate': mining_rate,
            'faucet_last_claim': 0,
            'tx_id': tx_id
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/blockchain/transactions', methods=['GET'])
def get_transactions():
    """Get all blockchain transactions"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT tx_id, type, from_device, to_device, amount, timestamp
            FROM global_blockchain
            ORDER BY timestamp DESC
            LIMIT 100
        ''')
        
        transactions = []
        for row in cursor.fetchall():
            transactions.append({
                'id': row['tx_id'],
                'type': row['type'],
                'from': row['from_device'],
                'to': row['to_device'],
                'amount': row['amount'],
                'timestamp': row['timestamp']
            })
        
        conn.close()
        return jsonify({'success': True, 'transactions': transactions})
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/blockchain/stats', methods=['GET'])
def get_stats():
    """Get global blockchain statistics"""
    try:
        update_global_stats()
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute('SELECT key, value FROM global_stats')
        stats_raw = cursor.fetchall()
        
        stats = {}
        for row in stats_raw:
            try:
                stats[row['key']] = float(row['value'])
            except:
                stats[row['key']] = row['value']
        
        conn.close()
        return jsonify({'success': True, 'stats': stats})
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/faucet/claim', methods=['POST'])
def claim_faucet():
    """Claim faucet reward"""
    try:
        data = request.get_json()
        device_id = data.get('device_id')
        
        if not device_id:
            return jsonify({'success': False, 'error': 'Device ID required'}), 400
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Get device info
        cursor.execute('SELECT * FROM devices WHERE id = ?', (device_id,))
        device = cursor.fetchone()
        
        if not device:
            return jsonify({'success': False, 'error': 'Device not found'}), 404
        
        # Check cooldown (24 hours)
        current_time = int(time.time() * 1000)
        cooldown_time = 24 * 60 * 60 * 1000  # 24 hours in milliseconds
        
        if device['faucet_last_claim'] and (current_time - device['faucet_last_claim']) < cooldown_time:
            remaining = cooldown_time - (current_time - device['faucet_last_claim'])
            return jsonify({
                'success': False, 
                'error': 'Faucet on cooldown',
                'remaining_ms': remaining
            }), 429
        
        # Claim faucet
        faucet_amount = 100.0
        new_balance = device['balance'] + faucet_amount
        
        # Update device
        cursor.execute('''
            UPDATE devices 
            SET balance = ?, faucet_last_claim = ?, last_seen = ?
            WHERE id = ?
        ''', (new_balance, current_time, current_time, device_id))
        
        # Add transaction to blockchain
        tx_id = generate_tx_id()
        cursor.execute('''
            INSERT INTO global_blockchain 
            (tx_id, type, from_device, to_device, amount, timestamp, block_hash, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (tx_id, 'faucet', 'Global Faucet', device_id, faucet_amount, 
              current_time, f'block_{tx_id}', int(time.time())))
        
        conn.commit()
        conn.close()
        
        update_global_stats()
        
        return jsonify({
            'success': True,
            'tx_id': tx_id,
            'amount': faucet_amount,
            'new_balance': new_balance
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/mining/start', methods=['POST'])
def start_mining():
    """Start mining session"""
    try:
        data = request.get_json()
        device_id = data.get('device_id')
        
        if not device_id:
            return jsonify({'success': False, 'error': 'Device ID required'}), 400
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Get device info
        cursor.execute('SELECT * FROM devices WHERE id = ?', (device_id,))
        device = cursor.fetchone()
        
        if not device:
            return jsonify({'success': False, 'error': 'Device not found'}), 404
        
        # Start mining session
        current_time = int(time.time() * 1000)
        cursor.execute('''
            INSERT INTO mining_sessions (device_id, start_time, created_at)
            VALUES (?, ?, ?)
        ''', (device_id, current_time, int(time.time())))
        
        # Update last seen
        cursor.execute('''
            UPDATE devices SET last_seen = ? WHERE id = ?
        ''', (current_time, device_id))
        
        conn.commit()
        conn.close()
        
        return jsonify({
            'success': True,
            'mining_rate': device['mining_rate'],
            'start_time': current_time
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/mining/stop', methods=['POST'])
def stop_mining():
    """Stop mining session and calculate reward"""
    try:
        data = request.get_json()
        device_id = data.get('device_id')
        
        if not device_id:
            return jsonify({'success': False, 'error': 'Device ID required'}), 400
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Get device info
        cursor.execute('SELECT * FROM devices WHERE id = ?', (device_id,))
        device = cursor.fetchone()
        
        if not device:
            return jsonify({'success': False, 'error': 'Device not found'}), 404
        
        # Get latest mining session
        cursor.execute('''
            SELECT * FROM mining_sessions 
            WHERE device_id = ? AND end_time IS NULL
            ORDER BY start_time DESC LIMIT 1
        ''', (device_id,))
        
        session = cursor.fetchone()
        if not session:
            return jsonify({'success': False, 'error': 'No active mining session'}), 400
        
        # Calculate reward
        current_time = int(time.time() * 1000)
        duration_ms = current_time - session['start_time']
        duration_minutes = duration_ms / (1000 * 60)
        earned = duration_minutes * device['mining_rate']
        
        # Update mining session
        tx_id = generate_tx_id()
        cursor.execute('''
            UPDATE mining_sessions 
            SET end_time = ?, duration = ?, earned = ?, tx_id = ?
            WHERE id = ?
        ''', (current_time, duration_minutes, earned, tx_id, session['id']))
        
        # Update device balance
        new_balance = device['balance'] + earned
        cursor.execute('''
            UPDATE devices 
            SET balance = ?, last_seen = ?
            WHERE id = ?
        ''', (new_balance, current_time, device_id))
        
        # Add transaction to blockchain
        cursor.execute('''
            INSERT INTO global_blockchain 
            (tx_id, type, from_device, to_device, amount, timestamp, block_hash, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (tx_id, 'mining', 'Mining Reward', device_id, earned, 
              current_time, f'block_{tx_id}', int(time.time())))
        
        conn.commit()
        conn.close()
        
        update_global_stats()
        
        return jsonify({
            'success': True,
            'tx_id': tx_id,
            'earned': earned,
            'duration_minutes': duration_minutes,
            'new_balance': new_balance
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/transfer', methods=['POST'])
def transfer_spm():
    """Transfer SPM between devices"""
    try:
        data = request.get_json()
        from_device = data.get('from_device')
        to_device = data.get('to_device')
        amount = float(data.get('amount', 0))
        
        if not from_device or not to_device or amount <= 0:
            return jsonify({'success': False, 'error': 'Invalid parameters'}), 400
        
        if from_device == to_device:
            return jsonify({'success': False, 'error': 'Cannot send to yourself'}), 400
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Get sender info
        cursor.execute('SELECT * FROM devices WHERE id = ?', (from_device,))
        sender = cursor.fetchone()
        
        if not sender:
            return jsonify({'success': False, 'error': 'Sender not found'}), 404
        
        if sender['balance'] < amount:
            return jsonify({'success': False, 'error': 'Insufficient balance'}), 400
        
        # Get or create recipient
        cursor.execute('SELECT * FROM devices WHERE id = ?', (to_device,))
        recipient = cursor.fetchone()
        
        current_time = int(time.time() * 1000)
        
        if not recipient:
            # Create recipient device
            recipient_rate = calculate_mining_rate(to_device)
            cursor.execute('''
                INSERT INTO devices (id, balance, mining_rate, last_seen, created_at)
                VALUES (?, ?, ?, ?, ?)
            ''', (to_device, 0, recipient_rate, current_time, int(time.time())))
        
        # Process transfer
        new_sender_balance = sender['balance'] - amount
        cursor.execute('SELECT balance FROM devices WHERE id = ?', (to_device,))
        recipient_balance = cursor.fetchone()['balance']
        new_recipient_balance = recipient_balance + amount
        
        # Update balances
        cursor.execute('''
            UPDATE devices SET balance = ?, last_seen = ? WHERE id = ?
        ''', (new_sender_balance, current_time, from_device))
        
        cursor.execute('''
            UPDATE devices SET balance = ?, last_seen = ? WHERE id = ?
        ''', (new_recipient_balance, current_time, to_device))
        
        # Add transaction to blockchain
        tx_id = generate_tx_id()
        cursor.execute('''
            INSERT INTO global_blockchain 
            (tx_id, type, from_device, to_device, amount, timestamp, block_hash, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (tx_id, 'transfer', from_device, to_device, amount, 
              current_time, f'block_{tx_id}', int(time.time())))
        
        conn.commit()
        conn.close()
        
        update_global_stats()
        
        return jsonify({
            'success': True,
            'tx_id': tx_id,
            'amount': amount,
            'sender_new_balance': new_sender_balance,
            'recipient_new_balance': new_recipient_balance
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/device/balance', methods=['GET'])
def get_balance():
    """Get device balance"""
    try:
        device_id = request.args.get('device_id')
        
        if not device_id:
            return jsonify({'success': False, 'error': 'Device ID required'}), 400
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute('SELECT balance FROM devices WHERE id = ?', (device_id,))
        device = cursor.fetchone()
        
        if not device:
            return jsonify({'success': False, 'error': 'Device not found'}), 404
        
        conn.close()
        
        return jsonify({
            'success': True,
            'balance': device['balance']
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({
        'success': True,
        'status': 'healthy',
        'timestamp': int(time.time() * 1000)
    })

if __name__ == '__main__':
    # Initialize database
    init_database()
    
    # Start the server
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)


